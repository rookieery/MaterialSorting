"""配置驱动的 commit 管线编排（CLI 侧镜像 ``web/server._commit_to_nesting_sync``）。

``commit_from_config(cfg, run_dir)`` 在**独立时间戳 run_dir**（``out/config_runs/
<run_name>_<YYYYMMDD-HHMMSS>/``）内跑通「母版解析 → g 码赋号 → 切单裁片 → manifest
sidecar → load_nest_pieces → intermediate 落盘」全管线，产出与 web commit **同口径**
的排料输入（schema v2），但**不触碰 web 事实源**（``paths.INTERMEDIATE`` 与
``out/uploads/``，FR-5：cli 子包唯一可写目录是 ``paths.CONFIG_RUNS_DIR``）。

与 web commit 的刻意差异（其余逐字段一致，含 rounding 位数）：

  - intermediate 落 ``run_dir/pieces_intermediate.json``（非 ``paths.INTERMEDIATE``），
    **不写 .bak**（时间戳 run_dir 天然全新，无旧产物可备份/清理）；
  - 顶层省略 web 专属 ``label_representatives``（GET /api/ptypes 缩略图用，CLI 无消费方）；
  - ``gate_mm`` 写 ``cfg.gate_mm``（配置驱动，与该 run 求解密度分母同源；web commit
    固定写 ``GATE_MM=1980`` 显示常量 —— 示例配置 gate_mm=1980 时两者同值）。

镜像维护约定：``server._commit_to_nesting_sync`` 的 piece schema（pid/label/size/
polygon/bbox/area_mm2/n_verts/allowed_angles + 5 层透传 + rounding 位数）变更时，
本模块 ``_piece_record`` 必须同步（web 层零改动约束下无法抽共享函数，只能镜像）。

``solve_pieces(cfg, run_dir, *, seed, ...)``（US-003；PC-001 起进程化）：单 seed
求解封装 —— 读 ``run_dir/pieces_intermediate.json`` → 主进程 ``web.solver.
build_instance`` 取 meta（demand_sum 校验 / total_area / n_items / n_eroded）→
``web.solver.solve_with_callback_proc`` **多进程版**求解（spyrrow 对象不可 pickle，
子进程内重建 instance 是 proc 设计固有成本，秒级）。切换动机：``should_stop``
逐帧中止需要持有进程句柄 ``terminate()``（OS 级回收，唯一可靠终止 spyrrow Rust
原生 solve 的方式 —— threading 版不可中断）。density 双口径换算发生在
``solve_with_callback_proc`` 内部（同一 ``web.solver._apply_density_dual`` = 同一
公式同一口径，web 层零改动约束下 CLI 不复制公式）：``density`` = 原面积口径
``total_area/(width*gate_mm)``（版师 / 90% 生死线），``density_sparrow`` = sparrow
自报（erode 后，仅参考）。

PC-001 落盘（run_dir 内，逐帧/逐 seed 写，不攒内存）：

  - ``curve_s{seed}.json``：帧轨迹 ``[{elapsed, phase, density, density_sparrow,
    width_mm}, ...]`` —— **不含 placed_items**（控体积；布局只在 best 帧文件里）；
  - ``best_frame_s{seed}.json``：该 seed 最优帧完整布局（``density`` 原面积口径，
    严格大于当前最优才覆盖写）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import paths
from ..dxf_parser.collect import collect_pieces_with_details
from ..dxf_parser.export_dxf import write_piece_dxf
from ..nesting_bounds.load_pieces import load_nest_pieces, PIECES_MANIFEST_NAME
from ..nesting_engine.labeling import assign_codes, size_sort_key

__all__ = ['new_run_dir', 'commit_from_config', 'solve_pieces',
           '_curve_entry', '_best_frame_record']


def new_run_dir(run_name: str) -> Path:
    """创建并返回全新时间戳 run_dir：``CONFIG_RUNS_DIR/<run_name>_<YYYYMMDD-HHMMSS>``。

    时间戳本地时间秒级精度 —— 重跑生成新目录互不覆盖（保留历史），同秒同名并发会
    落同一目录（文档已注明避免）。``run_name`` 由调用方清洗（``run_config`` 负责
    配置 stem / ``--name`` 覆盖 + 非法字符清洗）；本函数只做拼接与 mkdir。
    """
    run_dir = Path(paths.CONFIG_RUNS_DIR) / f'{run_name}_{time.strftime("%Y%m%d-%H%M%S")}'
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _piece_record(p) -> dict:
    """NestPiece → intermediate piece 条目（schema v2，与 server._commit_to_nesting_sync 逐字段一致）。

    rounding 位数与 web 严格对齐：polygon/net_polygon/internal_lines/notches 点 3 位、
    notch 法线 4 位、bbox 2 位、area 1 位。5 层字段（net_polygon/internal_lines/
    notches/grain_line）不参与 sparrow NFP 碰撞，仅渲染/导出透传。
    """
    return {
        'pid': p.pid,
        'label': p.label,
        'size': p.size,
        'polygon': [[round(x, 3), round(y, 3)] for x, y in p.polygon],
        'bbox': [round(v, 2) for v in p.bbox],
        'area_mm2': round(p.area_mm2, 1),
        'n_verts': len(p.polygon),
        'allowed_angles': [0, 180],   # v0.3 布纹线约束（与 web 同口径）
        'net_polygon': [[round(x, 3), round(y, 3)] for x, y in p.net_polygon],
        'internal_lines': [
            [[round(x, 3), round(y, 3)] for x, y in line]
            for line in p.internal_lines
        ],
        'notches': [
            [round(x, 3), round(y, 3), round(nx, 4), round(ny, 4)]
            for x, y, nx, ny in p.notches
        ],
        'grain_line': (
            [round(v, 3) for v in p.grain_line] if p.grain_line is not None else None
        ),
    }


def commit_from_config(cfg, run_dir) -> dict:
    """配置驱动的独立 commit 管线：切片 + manifest + intermediate 全落 ``run_dir``。

    编排镜像 ``web/server._commit_to_nesting_sync``（同一 ``collect_pieces_with_details``
    → ``assign_codes`` → ``write_piece_dxf`` → ``load_nest_pieces`` 链路，AC#5 同
    ``(block_name, size, piece_index)`` 必得同 g 码）：

    1. ``collect_pieces_with_details`` 取母版全部 5 层（layer1/14/8/4/7）；
    2. ``assign_codes`` 赋 g 码（label 先行，与 parse/web commit 同源同序）；
    3. ``run_dir/pieces/`` 下写 ``{label}_{size}.dxf`` + ``pieces_manifest.json`` sidecar；
    4. ``load_nest_pieces`` manifest 驱动布纹对齐 + 归一化（无镜像展开）；
    5. intermediate（schema v2）落 ``run_dir/pieces_intermediate.json``。

    只消费 ``cfg.master_dxf`` / ``cfg.gate_mm``（sizes/quantities/per_type/time/seeds
    是**求解期**参数，commit 阶段不过滤、全量切片 —— 与 web commit 同口径）。
    size 为 None 的片跳过（无法落 ``{label}_{size}.dxf`` 文件名），记入 ``skipped``。

    Returns
    -------
    dict
        commit 摘要：``source`` / ``run_dir`` / ``pieces_dir`` / ``intermediate`` /
        ``sizes`` / ``n_pieces`` / ``total_area_mm2`` / ``n_written_dxf`` /
        ``n_skipped`` / ``skipped``（US-003 result.json 的 commit 段数据源）。
    """
    run_dir = Path(run_dir)
    pieces = collect_pieces_with_details(Path(cfg.master_dxf))
    if not pieces:
        raise RuntimeError(f'母版未提取到任何裁片（layer1 POLYLINE 为空）: {cfg.master_dxf}')

    # g 码最先（label 先行）：与 parse / web commit 同一 assign_codes（同 collect、
    # 同排序键、同母版码规则），同一 (block_name, size, piece_index) 必得同码（AC#5）。
    codes_by_size = assign_codes(pieces)

    # 时间戳 run_dir 天然全新 —— 无需清空旧切片（web commit 的 rmtree 幂等清理不适用）。
    pieces_dir = run_dir / 'pieces'
    pieces_dir.mkdir(parents=True, exist_ok=True)

    # 按码升序 × 码内有序写 {label}_{size}.dxf + manifest 条目（manifest 驱动加载的
    # 唯一语义源；文件名仅人读）。
    manifest: list[dict] = []
    skipped: list[str] = []
    for size in sorted(codes_by_size.keys(), key=size_sort_key):
        for p, code in codes_by_size[size]:
            if p.size is None:
                skipped.append(f'{p.block_name}#{p.piece_index}(size 解析为 None)')
                continue
            fname = f'{code}_{p.size}.dxf'
            write_piece_dxf(p, pieces_dir / fname)
            manifest.append({'file': fname, 'label': code, 'size': p.size})

    if not manifest:
        raise RuntimeError('未写出任何单裁片（母版全部裁片 size 解析为 None）')
    with open(pieces_dir / PIECES_MANIFEST_NAME, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)

    nest_pieces = load_nest_pieces(str(pieces_dir))
    if not nest_pieces:
        raise RuntimeError('load_nest_pieces 未返回裁片（pieces_manifest.json 为空）')

    doc = {
        'source': Path(cfg.master_dxf).name,
        'gate_mm': float(cfg.gate_mm),
        'n_pieces': len(nest_pieces),
        'total_area_mm2': round(sum(p.area_mm2 for p in nest_pieces), 1),
        'pieces': [_piece_record(p) for p in nest_pieces],
        # 顶层无 label_representatives（web 专属，见模块 docstring「刻意差异」）。
    }
    intermediate_path = run_dir / 'pieces_intermediate.json'
    with open(intermediate_path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)

    return {
        'source': doc['source'],
        'run_dir': str(run_dir),
        'pieces_dir': str(pieces_dir),
        'intermediate': str(intermediate_path),
        'sizes': sorted({m['size'] for m in manifest}),
        'n_pieces': len(nest_pieces),
        'total_area_mm2': doc['total_area_mm2'],
        'n_written_dxf': len(manifest),
        'n_skipped': len(skipped),
        'skipped': skipped,
    }


def _dump_json(path: Path, payload) -> None:
    """JSON 落盘（UTF-8、ensure_ascii=False，与 intermediate/result.json 同风格）。"""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)


def _curve_entry(report: dict) -> dict:
    """frame → ``curve_s{seed}.json`` 单帧条目（**不含 placed_items**，控体积）。

    字段白名单 + rounding：elapsed 3 位（与 worker ``_emit_frame`` 一致）、density
    双口径 6 位（与 solve 指标一致）、width 2 位。
    """
    return {
        'elapsed': round(float(report.get('elapsed', 0.0)), 3),
        'phase': str(report.get('phase', '')),
        'density': round(float(report.get('density', 0.0)), 6),
        'density_sparrow': round(float(report.get('density_sparrow', 0.0)), 6),
        'width_mm': round(float(report.get('width_mm', 0.0)), 2),
    }


def _best_frame_record(seed: int, frame_index: int, report: dict) -> dict:
    """frame → ``best_frame_s{seed}.json`` 完整记录（含 placed_items 布局）。

    ``frame_index`` 是该 seed 帧序（0 起，与 ``curve_s{seed}.json`` 下标对齐）——
    portfolio incumbent 的来源字段（PC-002 消费）。
    """
    placed = report.get('placed_items') or []
    return {
        'seed': int(seed),
        'frame_index': int(frame_index),
        'elapsed': round(float(report.get('elapsed', 0.0)), 3),
        'phase': str(report.get('phase', '')),
        'density': round(float(report['density']), 6),
        'density_sparrow': round(float(report.get('density_sparrow', 0.0)), 6),
        'width_mm': round(float(report.get('width_mm', 0.0)), 2),
        'n_placed': len(placed),
        'placed_items': placed,
    }


def solve_pieces(cfg, run_dir, *, seed: int, time_budget: int | None = None,
                 on_progress=None, should_stop=None) -> dict:
    """配置驱动的单 seed 求解（PC-001 起进程化 + 帧轨迹落盘 + 可中止）。

    读 ``run_dir/pieces_intermediate.json``（``commit_from_config`` 产物；每轮求解
    重新 ``build_instance``，不重复 parse/commit —— 多 seed 串行复用同一份 commit
    产物的语义由此成立）。主进程先 ``build_instance`` 取 meta（``demand_sum`` 校验
    / ``total_area`` / ``n_items`` / ``n_eroded``），再交 ``solve_with_callback_proc``
    **多进程版**求解 —— spyrrow 对象不可 pickle，子进程内重建 instance 是 proc 设计
    固有成本（秒级）；换来的是调用方可经 ``should_stop`` 逐帧触发 ``terminate()``
    中止子进程（OS 级回收，唯一可靠终止 spyrrow Rust 原生 solve 的方式）。

    逐帧落盘（run_dir 内，不攒内存；见模块 docstring「PC-001 落盘」）：
      - ``curve_s{seed}.json``：全部帧的 ``{elapsed, phase, density,
        density_sparrow, width_mm}``（**增量 append** —— exploring 期 ~5ms 一帧、
        300s 预算可上万帧，整文件重写是 O(N²) 磁盘写；seed 结束/中断时 finally 补
        右括号收口成合法 JSON 数组）；
      - ``best_frame_s{seed}.json``：该 seed 最优帧完整 ``placed_items``，``density``
        严格大于当前最优才覆盖写（等值不重写，避免无谓 I/O）。

    Parameters
    ----------
    cfg : NestRunConfig
        求解期参数取 ``sizes`` / ``per_type`` / ``quantities``（commit 期未消费的字段
        在此生效）；``time`` 仅作 ``time_budget`` 缺省值。
    run_dir : Path
        commit 产物目录（须含 ``pieces_intermediate.json``）。
    seed : int
        sparrow 随机种子（``build_instance(seed=...)``）。
    time_budget : int | None
        覆盖单轮求解时长（秒）；None → ``cfg.time``。
    on_progress : callable(dict) | None
        每个中间解帧回调一次。帧已经 ``web.solver._apply_density_dual`` 换算（在
        ``solve_with_callback_proc`` 内完成，CLI 不复制公式）—— ``density`` =
        **原面积口径** ``total_area/(width_mm*gate_mm)``（90% 生死线口径），
        ``density_sparrow`` = sparrow 自报（erode 后，仅参考）。「新最优过滤 / 心跳
        节流」属 CLI 呈现层职责，由调用方（``run_config``）在回调内实现。
    should_stop : callable(dict) -> bool | str | None
        每帧评估是否中止（``True`` / 非空字符串 → 停）。触发即走 terminate 链路杀
        子进程（``terminate → cancel_join_thread → drain ≤50ms → join(5)``，由
        ``solve_with_callback_proc`` finally 保证），本函数以该 seed **best-so-far
        帧**作为结果返回（``killed=True`` + ``kill_reason``）；返回字符串时作为
        ``kill_reason``（portfolio 控制器报规则名），``True`` 用缺省 ``'should_stop'``。
        恒 ``False`` / 不传 = 现行行为（跑满预算）。

    Returns
    -------
    dict
        单 seed 求解指标（result.json ``solve`` 数组元素）：``seed`` / ``n_items``
        （进 sparrow 的 Item 数）/ ``n_eroded`` / ``total_area_mm2`` / ``width_mm``
        / ``real_density``（原面积口径）/ ``density_sparrow`` / ``placed_items``
        （放置副本数）/ ``elapsed``（wall-clock 秒）。**被 should_stop 中止时**额外
        含 ``killed=True`` / ``kill_reason``，且 ``width_mm`` / ``real_density`` /
        ``density_sparrow`` / ``placed_items`` 取终止前 best-so-far 帧（不再做
        ``placed == Σdemand`` 完整性校验 —— 中间帧允许未放满）。

    Raises
    ------
    RuntimeError
        求解失败（子进程抛错 / 未返回 final）、``len(placed_items) != Σdemand``
        （正常结束的解不完整，不允许静默截断）、或被中止时一帧未收（无 best-so-far
        可交付）。
    """
    # 延迟 import（约定同 solve_worker）：cli → web.solver 是合规向下依赖，但避免
    # `python -m materialsorting.cli.pipeline` 导入冒烟时拉起 web 包链。
    from ..web.solver import build_instance, load_pieces, solve_with_callback_proc

    seed = int(seed)
    _, gate_mm, pieces = load_pieces(str(Path(run_dir) / 'pieces_intermediate.json'))
    solve_params = {
        'time_budget': int(cfg.time if time_budget is None else time_budget),
        'seed': seed,
        'sizes': cfg.sizes,
        'per_type': cfg.per_type,
        'quantities': cfg.quantities,
    }
    # 主进程先建一次实例只取 meta（demand_sum / total_area / n_items / n_eroded）——
    # 避免在 CLI 复制 demand 查询逻辑（单一真相源仍是 web.solver.build_instance）。
    instance, _config, _pid_meta, total_area, n_eroded = build_instance(
        pieces, gate_mm, **solve_params)
    n_items = len(instance.items)
    demand_sum = int(sum(it.demand for it in instance.items))

    curve_path = Path(run_dir) / f'curve_s{seed}.json'
    best_path = Path(run_dir) / f'best_frame_s{seed}.json'
    state: dict = {'best': None, 'reason': None, 'proc': None, 'n_frames': 0}

    # curve 增量写：sparrow exploring 期 ~5ms 一帧（300s 预算可上万帧），整文件重写
    # 是 O(N²) 磁盘写（实测 5s 冒烟即 ~75MB）—— 改为打开一次、逐帧 append 条目，
    # seed 结束（含 Ctrl-C 的 finally）补右括号收口成合法 JSON 数组。
    curve_file = open(curve_path, 'w', encoding='utf-8')
    curve_file.write('[\n')

    def _on_process(proc) -> None:
        # 持有子进程句柄：should_stop 触发时在帧回调内就地 terminate（US-026 同款链路）。
        state['proc'] = proc

    def _on_manifest(_manifest: dict) -> None:
        # meta 已由主进程 build_instance 提供（total_area/pid_meta/n_eroded），manifest
        # 消息只确认子进程口径一致，无需重复消费。
        return None

    def _on_report(report: dict) -> None:
        # 密度双口径换算已由 solve_with_callback_proc 内 _apply_density_dual 完成。
        idx = state['n_frames']
        state['n_frames'] = idx + 1
        curve_file.write((',' if idx else '') +
                         json.dumps(_curve_entry(report), ensure_ascii=False) + '\n')
        best = state['best']
        if best is None or report['density'] > best['density']:
            state['best'] = _best_frame_record(seed, idx, report)
            _dump_json(best_path, state['best'])
        if on_progress is not None:
            on_progress(report)
        if state['reason'] is None and should_stop is not None:
            verdict = should_stop(report)
            if verdict:
                state['reason'] = verdict if isinstance(verdict, str) and verdict else 'should_stop'
                proc = state['proc']
                if proc is not None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass                  # 子进程已退出等：交 solve_with_callback_proc 收尾

    try:
        _proc, final, elapsed, err = solve_with_callback_proc(
            pieces, gate_mm, solve_params,
            on_manifest=_on_manifest, on_report=_on_report, on_process=_on_process)
    finally:
        # 收口成合法 JSON 数组（KeyboardInterrupt / 求解异常 / killed 路径都走这里，
        # Ctrl-C 不留半截 curve；仅硬崩溃（进程被杀）才可能缺右括号）。
        curve_file.write(']\n')
        curve_file.close()

    # 被 should_stop 中止：以 best-so-far 帧交付（err/final 缺席是 terminate 的预期形态）。
    if state['reason'] is not None:
        best = state['best']
        if best is None:
            raise RuntimeError(
                f'seed {seed} 被中止（{state["reason"]}）时未收到任何帧，无 best-so-far 可交付')
        return {
            'seed': seed,
            'n_items': n_items,
            'n_eroded': int(n_eroded),
            'total_area_mm2': round(total_area, 1),
            'width_mm': best['width_mm'],
            'real_density': best['density'],
            'density_sparrow': best['density_sparrow'],
            'placed_items': best['n_placed'],
            'elapsed': round(elapsed, 1),
            'killed': True,
            'kill_reason': state['reason'],
        }

    if err is not None:
        raise RuntimeError(f'sparrow solve 抛错: {err}')
    if final is None:
        raise RuntimeError('sparrow solve 未返回解（sol=None）')

    n_placed = len(final.get('placed_items') or [])
    if n_placed != demand_sum:
        raise RuntimeError(
            f'解不完整：placed_items={n_placed} != Σdemand={demand_sum}（裁片未全部放置）')

    return {
        'seed': seed,
        'n_items': n_items,
        'n_eroded': int(n_eroded),
        'total_area_mm2': round(total_area, 1),
        'width_mm': round(float(final['width_mm']), 2),
        'real_density': round(float(final['density']), 6),
        'density_sparrow': round(float(final['density_sparrow']), 6),
        'placed_items': n_placed,
        'elapsed': round(elapsed, 1),
    }
