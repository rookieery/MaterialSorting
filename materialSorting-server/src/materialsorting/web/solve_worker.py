"""排料求解子进程 worker — 把 build_instance + solve 封装进独立进程（US-025）。

从 daemon threading 模型（旧 ``solver.solve_with_callback``）迁到 ``multiprocessing.Process``
模型，让调用方拿到 ``Process`` 句柄可随时 ``terminate()``（OS 级回收，唯一可靠终止
spyrrow Rust 原生 ``solve()`` 的方式 —— 全包无 cancel/abort/stop/pause/kill/terminate
匹配，threading.Thread 无法安全终止原生代码线程）。

spyrrow 对象不可 pickle，故 ``build_instance`` 必须在子进程内执行，只把 JSON 可序列化
数据（pid_meta / frame / final / error）经 ``multiprocessing.Queue`` 传回主进程。

US-011（腰头成带编排）：``band`` 配置非空时，本 worker 先在**进程内**构造腰头带
（``waist_band.build_band_plan`` v2 构造性链构造 —— 不 spawn 孙进程：
``routes_ws._terminate_solve_process`` 的 terminate 不级联孙进程，同步调用随本进程
一并被 OS 回收，stop 后无存活 python 子进程），投 ``{kind:stage}``（manifest 前唯一
一次）+ 落 ``band_runs`` 工件，随后主实例以 ``exclude_labels={label}`` 构造并把
组合片（WB_ pid）追加进 items；帧/final 发射经 ``_emit_placed`` **单点**把组合片
placement 展开回成员 placement（三处发射点共享该序列化器 → WB_ 永不出现在
manifest/frame/final）。

US-015（v1.1 填料混带）：``band.fillers`` 的填料 g 码在 ``_build_band`` 进
``build_band_plan(fillers=...)``（同一展开/守恒/泄漏口径 —— 组合片含填料，展开后
成员 pid 含填料副本）；主实例扣减扩为 ``exclude_labels={label} ∪ fillers``
（同一 Item 构造层跳过路径，pid_meta/total_area/manifest 仍逐字段不变）。

**picklable 约束（Windows spawn）**：``solve_worker`` 必须是**顶层函数**、无闭包、参数
全部 JSON 可序列化（list/dict/float/int/str）。子进程 spawn 时会通过 pickle 重建本函数。
"""
from __future__ import annotations

import json
import sys
import threading
import time


def solve_worker(pieces_snapshot, gate_mm, solve_params, result_queue, band=None):
    """子进程入口：[band] → build_instance → manifest → solve → frame* → final | error。

    Parameters
    ----------
    pieces_snapshot : list[dict]
        intermediate 的 pieces 字段（纯 JSON；spyrrow 对象尚未构造）。
    gate_mm : float
        门幅（mm，spyrrow 世界坐标 Y 范围）。
    solve_params : dict
        拆给 ``build_instance`` 的关键字参数 —— ``time_budget`` / ``seed`` / ``sizes``
        / ``params`` / ``per_type`` / ``quantities`` / ``solver_opts``（US-006，全部
        JSON 可序列化；``solver_opts`` 原样透传给 ``build_instance`` 做白名单清洗，
        本 worker 不解释旋钮语义）。
    result_queue : multiprocessing.Queue
        子进程 → 主进程的消息队列。投递内容全部 JSON 可序列化，spyrrow 对象绝不跨进程：
        - ``{kind:'stage', stage, fill_pct, bbox, fallback, elapsed}``（US-011：band
          开启时 manifest 前唯一一次，带内聚排完成统计）
        - ``{kind:'manifest', pid_meta, total_area, n_eroded, gate_mm}``
        - ``{kind:'frame', report}`` 每个 sparrow 中间解（report 内含 density/width_mm/placed_items）
        - ``{kind:'final', final}`` 末态解（同 frame 但 type=final、无 phase）
        - ``{kind:'error', message}`` 异常路径（成带失败 / build_instance 抛错 / solve
          崩溃；band 失败只投 error 不投 manifest，与 build 失败同契约）
    band : dict | None
        US-011/015 成带配置 ``{'label': str, 'fillers': list[str],
        'time_budget': int|None}``（routes_ws 服务端校验产物）。None/缺 label =
        关闭，走原五元路径。``BandChunk`` 只在本进程存活，绝不跨进程（frame/final
        里的组合片条目已展开成成员 placement —— 含 US-015 填料副本）。

    density 双口径换算（关键不变量 #1）**不在子进程做**：子进程原样透传 sparrow 自报
    density；主进程在处理 frame 时按 ``total_area/(width*gate)`` 换算为原面积口径
    （total_area 由 manifest 数据带入主进程）。
    """
    # 延迟 import：子进程 spawn 时 ``from .solver import build_instance`` 触发整条
    # web 包链（含 sparrow_baseline 等重模块）import；放函数内让父进程 spawn 子进程
    # 的开销与子进程 import 开销分离，也避免主进程 ``from .solve_worker import solve_worker``
    # 时强制 import sparrow_baseline（保持 ``__init__`` 零副作用）。
    from .solver import build_instance

    band_chunk = None
    if isinstance(band, dict) and band.get('label'):
        band_chunk = _build_band(pieces_snapshot, gate_mm, solve_params, band, result_queue)
        if band_chunk is None:
            return   # 成带失败：error 已投（只投 error 不投 manifest）

    extra_items = None
    if band_chunk is not None:
        # 组合片 demand=1、朝向 [0,180] 顺布纹不带抖动（FR-8）。**必须构造期传入**
        # （extra_items）：spyrrow ``instance.items`` 是 Rust 侧副本 list，构造后
        # append 不生效（实测组合片整解缺席 —— 见 build_instance docstring）。
        from ..nesting_engine.waist_band import COMPOSITE_ORIENTATIONS
        extra_items = [{
            'id': band_chunk.pid,
            'polygon': band_chunk.polygon,
            'demand': 1,
            'orientations': list(COMPOSITE_ORIENTATIONS),
        }]

    try:
        instance, config, pid_meta, total_area, n_eroded = build_instance(
            pieces_snapshot, gate_mm,
            exclude_labels=(
                {band_chunk.label, *band_chunk.fillers}
                if band_chunk is not None else None),
            extra_items=extra_items,
            **solve_params
        )
    except Exception as e:
        result_queue.put({'kind': 'error', 'message': f'构造实例失败: {e}'})
        return

    # 1) manifest：base 几何 + 颜色 + US-024 5 层。total_area 透传到主进程供 density
    #    双口径换算。band 开启时 manifest 与 band off **逐字段一致**（exclude_labels
    #    只跳 Item 层，pid_meta/total_area 原样），pid_meta 恒无 WB_ 条目。
    result_queue.put({
        'kind': 'manifest',
        'pid_meta': pid_meta,
        'total_area': total_area,
        'n_eroded': n_eroded,
        'gate_mm': float(gate_mm),
    })

    # 2) solve + drain 投递 frame。sparrow 的 instance.solve 是阻塞调用，ProgressQueue
    #    thread-safe —— 复用旧 threading 骨架：子进程内再开一个 daemon 子线程跑 solve，
    #    主线程 drain；如此才能在 solve 阻塞期间持续投递 frame。terminate() 整个子进程
    #    时这些线程随进程一起回收（OS 级），无遗留。
    import spyrrow

    progress = spyrrow.ProgressQueue()
    holder: dict = {}
    t0 = time.time()

    def _solve():
        try:
            holder['sol'] = instance.solve(config, progress=progress)
        except Exception as e:
            holder['err'] = e

    th = threading.Thread(target=_solve, daemon=True)
    th.start()
    while th.is_alive():
        for rtype, mid in progress.drain():
            result_queue.put({'kind': 'frame',
                              'report': _emit_frame(rtype, mid, t0, band_chunk)})
        time.sleep(0.2)
    th.join()
    for rtype, mid in progress.drain():
        result_queue.put({'kind': 'frame',
                          'report': _emit_frame(rtype, mid, t0, band_chunk)})

    err = holder.get('err')
    if err is not None:
        result_queue.put({'kind': 'error', 'message': f'求解失败: {err}'})
        return

    sol = holder.get('sol')
    if sol is None:
        # 理论上不可达（err 为 None 则 sol 必被赋值）；防御性兜底。
        result_queue.put({'kind': 'error', 'message': '求解失败: solver 返回 None'})
        return

    # 3) final：末态解。density 仍为 sparrow 自报口径，主进程处理时按 total_area 换算。
    result_queue.put({
        'kind': 'final',
        'final': {
            'type': 'final',
            'density': float(sol.density),
            'width_mm': float(sol.width),
            'elapsed': round(time.time() - t0, 3),
            'placed_items': _emit_placed(sol.placed_items, band_chunk),
        },
    })


# ------------------------------------------------------- US-011 成带（进程内）


def _build_band(pieces_snapshot, gate_mm, solve_params, band, result_queue):
    """成带（US-011 编排层）：本进程内同步跑 ``build_band_plan``（v2 构造性链
    构造，确定性毫秒级 —— 2026-08-21 起替换 v1 spyrrow 带内子求解）。

    进程模型（落地方案 §2.6）：**不 spawn 孙进程** —— 父级 ``terminate()`` 不级联
    孙进程，band 跑在本 worker 进程内（同步调用）则随进程整体被 OS 回收，stop 后
    无存活 python 子进程。

    d_g/tol_g 与主实例同源裁定（``_resolve_d_tol`` 单一真相源 —— FR-3 带内 per_type
    沿用该 g 码的 d/tol；US-015 填料各 label 同法逐个裁定，喂 ``filler_ds`` 计算
    混带补腐蚀深度）；带高守卫 = min(gate_mm, PLOT_SAFE_MAX_Y_MM)（与主解同口径）。
    ``band.time_budget`` 为 deprecated no-op（构造性链构造无预算依赖，接受即忽略）。

    失败（BandError/ValueError 等）投 ``{kind:error}``（「成带失败」前缀，只投 error
    不投 manifest —— 与 build_instance 抛错同契约）返回 None；成功投 ``{kind:stage}``
    （fill_pct/bbox/fallback=False/elapsed，manifest 前唯一一次）+ 落 ``band_runs``
    工件后返回 ``BandChunk``（只在本进程存活，绝不跨队列）。
    """
    from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
    from ..nesting_engine.waist_band import (
        DEFAULT_BAND_TIME_BUDGET_S, BandError, build_band_plan)
    from .solver import _resolve_d_tol, build_pid_meta

    label = str(band['label'])
    fillers = [str(f) for f in (band.get('fillers') or [])]
    t0 = time.time()
    try:
        pdef = {'d_ext': 0.0, 'd_int': 0.0, 'tol_ext': 0.0, 'tol_int': 0.0}
        pdef.update(solve_params.get('params') or {})
        d_g, tol_g = _resolve_d_tol(label, pdef, solve_params.get('per_type'))
        filler_ds = {}
        for f in fillers:
            filler_ds[f], _tol_f = _resolve_d_tol(f, pdef, solve_params.get('per_type'))
        pid_meta, _area, _n = build_pid_meta(
            pieces_snapshot,
            sizes=solve_params.get('sizes'),
            per_type=solve_params.get('per_type'),
            quantities=solve_params.get('quantities'),
            params=solve_params.get('params'))
        chunk = build_band_plan(
            pid_meta, {p['pid']: p for p in pieces_snapshot},
            label=label,
            seed=int(solve_params.get('seed', 0)),
            gate_nest=min(float(gate_mm), PLOT_SAFE_MAX_Y_MM),
            d_g=d_g, tol_g=tol_g,
            fillers=fillers, filler_ds=filler_ds,
            time_budget=int(band.get('time_budget') or DEFAULT_BAND_TIME_BUDGET_S))
    except (BandError, ValueError) as e:
        result_queue.put({'kind': 'error', 'message': f'成带失败: {e}'})
        return None
    except Exception as e:            # noqa: BLE001 进程边界：几何异常也须早退成 error 不崩进程
        result_queue.put({'kind': 'error', 'message': f'成带失败: {e}'})
        return None

    elapsed = time.time() - t0
    result_queue.put({
        'kind': 'stage', 'stage': 'band',
        'fill_pct': round(float(chunk.fill_pct), 2),
        'bbox': {'width_mm': float(chunk.bbox['width_mm']),
                 'height_mm': float(chunk.bbox['height_mm'])},
        'fallback': False,
        'elapsed': round(elapsed, 2),
    })
    _write_band_artifact(chunk, int(solve_params.get('seed', 0)), elapsed)
    return chunk


def _write_band_artifact(chunk, seed, band_elapsed):
    """band 几何工件 → ``paths.OUT_DIR/band_runs/*.json``（US-014 回放对拍数据源）。

    内容 = ``BandChunk.to_dict()``（分块轮廓 + 成员带内位 + fill/bbox/派生 seed/
    d_g/tol_g）+ ``main_seed`` / ``band_elapsed``；写失败仅 warn（band_runs 是对拍
    工件，不阻塞求解主链路）。OUT_DIR 经环境变量 ``MS_OUT_DIR`` 随 spawn 传递，
    测试可隔离。
    """
    try:
        from pathlib import Path

        from .. import paths
        out_dir = Path(paths.OUT_DIR) / 'band_runs'
        out_dir.mkdir(parents=True, exist_ok=True)
        doc = chunk.to_dict()
        doc['main_seed'] = int(seed)
        doc['band_elapsed'] = round(float(band_elapsed), 3)
        dest = out_dir / time.strftime(
            f'band_{chunk.label}_seed{int(seed)}_%Y%m%d_%H%M%S.json')
        with open(dest, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False)
    except Exception as e:
        print(f'[solve_worker] band_runs 工件写失败（仅 warn，不影响求解）: {e}',
              file=sys.stderr)


def _emit_frame(rtype, sol, t0, band=None):
    """把 spyrrow 的 (ReportType, Solution) → JSON 可序列化 frame dict。

    顶层函数（非闭包）；density 为 sparrow 自报口径，主进程再换算为原面积口径。
    ``band``（BandChunk）非 None 时组合片条目在 ``_emit_placed`` 单点展开（US-011）。
    """
    return {
        'type': 'frame',
        'elapsed': round(time.time() - t0, 3),
        'phase': rtype.phase_name(),
        'density': float(sol.density),
        'width_mm': float(sol.width),
        'placed_items': _emit_placed(sol.placed_items, band),
    }


def _emit_placed(placed_items, band=None):
    """spyrrow PlacedItem 列表 → JSON list[{id, rotation, translation}]。

    US-011 **展开单点**：``band``（``BandChunk``）非 None 时，组合片（WB_ pid）条目
    在此展开回成员 placement（``expand_placements`` 权威式，shape 与本函数产物对齐）
    —— 帧与 final 三处发射点共享本序列化器，WB_ pid 永不出现在跨进程产物。
    """
    from ..nesting_engine.waist_band import expand_placements

    out = []
    for pi in placed_items:
        tx, ty = pi.translation
        if band is not None and pi.id == band.pid:
            out.extend(expand_placements(band, float(pi.rotation), (float(tx), float(ty))))
            continue
        out.append({
            'id': pi.id,
            'rotation': float(pi.rotation),
            'translation': [float(tx), float(ty)],
        })
    return out
