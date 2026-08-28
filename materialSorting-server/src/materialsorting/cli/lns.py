r"""LNS 波段重排核心模块（PC-007 / US-007）—— 对 portfolio 最优布局做波段级
ruin-and-recreate，突破单 seed 收敛分布上限。

用法（console_script 或 ``python -m`` 等价）::

    ms-lns --run-dir <dir> --time 30 --rounds 5 [--band-width 2970]
    python -m materialsorting.cli.lns --run-dir <dir> --time 30 --rounds 5

输入：``run_dir`` 内 ``result.json``（布局取 ``portfolio.incumbent.placed_items``，
缺席回退 ``best.placed_items`` —— 旧式多 seed run 的 best 只存 int 计数，布局在
边车 ``best_frame_s{seed}.json``，``_incumbent`` 按此回填）+
``pieces_intermediate.json``（原始轮廓 / 原面积的单一数据源）。算法（每轮 = 按段
局部密度升序逐段尝试，首个接受即完成该轮）：

  ① 按 x 切竖直波段（sparrow 世界坐标 X=用布长度；缺省段宽 1.5×默认门幅）。
     pid 组按**首副本中心**归段 —— demand>1 的 pid 全部副本整段进波段重排（禁止
     拆分；solver 常把同 pid 副本撒满全幅，此时段足迹 [m, M] 跨全宽、重排为
     「子集整体重解」，护栏之下通常无改进空间 → 安全 no-op，见护栏段）。
  ② 每段局部密度 = 段内片**原面积**和 /（段宽 × 输入门幅 gate_mm），升序取最差段。
  ③ 段内裁片构造同口径子实例（``web.solver.build_instance``）：per_type/sizes 按
     result.json config 回显原样透传；quantities 按**段内实际副本数**派生 —— pid ↔
     (label, sizeKey) 一一对应且 pid 组禁止拆分，故派生 demand ≡ 母 quantities 在
     该 pid 上的投影，且对未放满的中间帧 incumbent 也精确成立（按在场副本重排，
     不凭空补 demand）。子求解经 ``solve_with_callback_proc`` 多进程（与
     pipeline.solve_pieces 同链路）。
  ④ 新段跨度 < 原段跨度 − ε（ACCEPT_EPS_MM）→ 接受：段内换新放置（新段左缘对齐
     原段左缘，接受条件保证新足迹 ⊆ 原足迹 [m, M]）、**完全位于 M 右侧**的片左移
     splice（「后续」按几何判定而非段序 —— 跨段散布的 pid 副本若按段序左移会被
     推出 x<0）、总宽缩短；否则拒绝（布局不动，幂等安全 —— 无任何接受时输出 =
     输入列表原对象，逐字节不变）。空段（纯空洞）无需求解即整段让位。
  ⑤ 循环 rounds 直到整轮无段可改进或预算耗尽；结束 ``constraints.validate`` 全版
     复检 + ``y ≤ gate_mm`` 越界复检（容差 Y_TOLERANCE_MM=11mm 容纳
     erode 合法外凸，与 export 削平口径同源），失败回退输入布局（交付物恒过检）。

输出（``run_dir`` 内）：``result_lns.json``（新 placed_items + 前后 density/width
对比 + 逐段尝试明细）+ ``lns_compare.svg``（前后双面板对比，坐标口径 / 配色与其余
排料 SVG 一致）。

PC-008（US-008）起 ``postprocess_run_dir`` 是 run_dir 级共用编排入口（``ms-lns``
CLI 与 ``run_config --lns`` 后处理同一条代码路径）：读 ``result.json`` 选布局 →
``run_lns`` 核心循环 → 双产物落盘，返回写盘 payload；输入错误经异常上抛由调用方
决定呈现（CLI 退出 1 / run_config 降级 warn 跳过）。

跨组重叠护栏（超出 PC-007 验收口径的工程加固）：重排只保证段内非重叠（子求解
语义同母求解，重合公差 d 的合法重叠照常允许）与段间 x 空间让位，但波段边界处
互相咬合（interlock）的片在 splice 后可能产生**新**重叠 —— ``constraints.validate``
不查重叠，静默产出重叠 marker 比不改进更糟。故接受前用 shapely 精确比较
「新放置段 × 不动片」「左移段 × 不动片」**每一对**的交集面积，任一对超过原布局
同对基线 + 1mm² 即拒绝（逐对不劣化，杜绝「净增为零、局部恶化」的 redistribution；
原布局里合法的 d-erode 重叠在同对基线内自然放行；shapely 不可用时护栏降级跳过
并在明细留痕）。

分层：cli → web.solver（延迟 import，与 pipeline 同约定）→ nesting_engine →
nesting_bounds，无反向依赖；模块级 import 不拉 web/spyrrow（``--help`` 冒烟零负担）。

模块拆分（行为零变更）：共享基元（常量 / ``LnsError`` / 几何算子 / 波段切分 /
重叠护栏 / 全版复检）在 ``lns_bands``，对比 SVG 渲染在 ``lns_svg``；本模块保留
``run_lns`` 核心循环（含 ``_solve_band`` 注入点 —— 单测经本模块属性 monkeypatch，
须留在本模块全局命名空间解析）与 CLI / run_dir 编排入口，并 re-export 全部公共
符号（``__all__`` 不变，原路径可导入）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from materialsorting.cli.lns_bands import (ACCEPT_EPS_MM, DEFAULT_BAND_WIDTH,
                                           GUARD_SLACK_MM2, MIN_SUB_TIME_SEC,
                                           Y_TOLERANCE_MM, LnsError,
                                           _cross_overlap_ok, _layout_geometry,
                                           _world_polygon, band_solve_params,
                                           recheck_layout, split_bands)
from materialsorting.cli.lns_svg import write_compare_svg

__all__ = ['ACCEPT_EPS_MM', 'DEFAULT_BAND_WIDTH', 'LnsError', 'split_bands',
           'band_solve_params', 'run_lns', 'recheck_layout', 'write_compare_svg',
           'postprocess_run_dir', 'main']


# ---------------------------------------------------------------- 子求解


def _solve_band(pieces_subset, gate_mm, solve_params):
    """真实子求解：``solve_with_callback_proc`` 多进程（与 pipeline.solve_pieces
    同链路，Windows spawn 安全、可 OS 级终止）。返回 final dict（含 placed_items /
    width_mm）；失败抛 RuntimeError（调用方按「该段无改进」处理，不崩整个 LNS）。"""
    # 延迟 import：cli → web.solver 合规向下依赖，但不让模块 import 拉 web 链。
    from ..web.solver import solve_with_callback_proc
    _proc, final, _elapsed, err = solve_with_callback_proc(
        pieces_subset, gate_mm, solve_params,
        on_manifest=lambda _m: None, on_report=lambda _r: None)
    if err is not None:
        raise RuntimeError(err)
    if final is None:
        raise RuntimeError('子求解未返回 final')
    return final


# ---------------------------------------------------------------- 核心循环


def _shifted(items, positions, dx):
    """布局副本：指定位置条目 x 平移 dx（其余条目原对象共享；返回新列表）。"""
    cand = list(items)
    for pos in positions:
        it = items[pos]
        tx, ty = it['translation']
        cand[pos] = {'id': it['id'],
                     'rotation': round(float(it.get('rotation', 0.0)), 6),
                     'translation': [round(float(tx) + dx, 6), round(float(ty), 6)]}
    return cand


def run_lns(placed_items, pieces, gate_mm, *, per_type=None, sizes=None,
            band_width=None, time_budget=30.0, rounds=5, solve=None,
            base_seed=0, echo=None):
    """波段重排核心循环（纯编排 + 几何，文件 I/O 由 CLI 呈现层负责）。

    Parameters
    ----------
    placed_items : list[dict]
        输入布局（result.json incumbent/best 的 ``{id, rotation, translation}``）。
    pieces : list[dict]
        intermediate 的 pieces（原始轮廓 / 原面积单一数据源）。
    gate_mm : float
        门幅（density 分母口径；子求解约束带在 build_instance 内 = gate_mm，
        与母实例同口径）。
    per_type / sizes : result.json ``config`` 段回显的同名求解参数（子实例同口径
        透传：erode/tol/orientations 钳制行为与母实例一致）。
    band_width : float | None
        波段宽（mm）；None → ``DEFAULT_BAND_WIDTH``（= 1.5×默认门幅）。
    time_budget : float
        LNS 总预算（秒，墙钟）。子求解按「剩余预算 / 剩余轮数」取整分配（≥1s，
        提前结束的轮把余量让给后续轮）；剩余 < ``MIN_SUB_TIME_SEC`` 即耗尽停。
    rounds : int
        最大轮数。每轮按段局部密度升序逐段尝试（空段密度 0 最先出列），首个
        接受即完成该轮；整轮无一接受 → 无段可改进，提前终止。
    solve : callable | None
        子求解注入点（缺省 ``_solve_band`` 真实多进程求解；单测注入 fake packer）。
        签名 ``solve(pieces_subset, gate_mm, solve_params) -> {'placed_items', ...}``，
        抛异常按「该段无改进」记录后继续。
    base_seed : int
        子求解种子基（``base_seed + 1 + round*1000 + band_index``，确定性可复现）。
    echo : callable | None
        接受事件进度行输出（CLI 传 print；None 静默）。

    Returns
    -------
    dict
        ``{band_width_mm, rounds_requested, rounds_executed, stop_reason,
        time_budget_sec, elapsed, improved, before, after, delta, rounds_detail,
        recheck, placed_items}``。**无任何接受时 ``placed_items`` 为输入列表原对象**
        （拒绝路径逐字节不变量）；有接受但终检失败 → 回退输入布局（``recheck.reverted``
        留痕）。Ctrl-C 捕获为 ``stop_reason='interrupted'``（已完成轮保留在结果里）。
    """
    t0 = time.monotonic()
    if not placed_items:
        raise LnsError('输入布局为空（incumbent 无 placed_items）')
    rounds = int(rounds)
    if rounds < 1:
        raise LnsError(f'rounds 须 >= 1，当前 {rounds}')
    if float(time_budget) <= 0:
        raise LnsError(f'time_budget 须为正（秒），当前 {time_budget}')
    bw = DEFAULT_BAND_WIDTH if band_width is None else float(band_width)
    if bw <= 0:
        raise LnsError(f'band_width 须为正数（mm），当前 {bw}')
    if solve is None:
        solve = _solve_band

    pieces_by_id = {p['pid']: p for p in pieces}
    geoms0 = _layout_geometry(placed_items, pieces_by_id)   # 兼验 pid 在场
    total_area = sum(float(pieces_by_id[it['id']]['area_mm2']) for it in placed_items)
    width_before = max(max(g[2] for g in geoms0), 0.0)
    # 密度分母 = 输入门幅（与 _apply_density_dual 同口径，回写 result.json 的
    # incumbent density 与 solve 段 real_density 保持一致）。
    density_before = total_area / (width_before * float(gate_mm))

    current = list(placed_items)      # 浅拷贝：接受时替换元素为新 dict，绝不动入参
    improved_any = False
    rounds_detail: list[dict] = []
    stop_reason = 'no_bands'
    interrupted = False
    rd = 0
    try:
        while rd < rounds:
            remaining = time_budget - (time.monotonic() - t0)
            if remaining < MIN_SUB_TIME_SEC:
                stop_reason = 'budget_exhausted'
                break
            bands = split_bands(current, pieces_by_id, bw, gate_mm=float(gate_mm))
            if not bands:
                break
            accepted = None
            budget_hit = False
            for band in sorted(bands, key=lambda b: (b['density'], b['index'])):
                detail = {'round': rd + 1, 'band': band['index'],
                          'x_start': round(band['x_start'], 2),
                          'x_end': round(band['x_end'], 2),
                          'density': round(band['density'], 6),
                          'span_old': round(band['span'], 2),
                          'span_new': None, 'delta': None,
                          'accepted': False, 'note': ''}
                rounds_detail.append(detail)
                # 「后续」按**几何**定义：完全位于本段占用右缘 M 右侧的片才左移。
                # pid 组可能跨段散布（solver 常把同 pid 副本撒满全幅），按 band
                # index 取「后面所有段」会把左边的散布副本推出 x<0（负坐标 bug），
                # 故此处用片 bbox 与 M 的关系判定；跨在 M 左侧的散布片视为不动片。
                band_set = set(band['positions'])
                geoms_now = _layout_geometry(current, pieces_by_id)
                later_pos = [k for k, g in enumerate(geoms_now)
                             if k not in band_set and g[1] >= band['M'] - ACCEPT_EPS_MM]
                # ---- 空段（纯空洞）：无需求解，后续片整体左移段宽
                if not band['positions']:
                    if not later_pos or band['span'] <= ACCEPT_EPS_MM:
                        detail['note'] = ('空段且无后续片可让位，跳过' if not later_pos
                                          else '空段过窄（≤ε），跳过')
                        continue
                    cand = _shifted(current, later_pos, -band['span'])
                    old_polys = [g[0] for g in geoms_now]
                    new_polys = [g[0] for g in _layout_geometry(cand, pieces_by_id)]
                    ok_g, note_g = _cross_overlap_ok(old_polys, new_polys,
                                                     list(band['positions']), later_pos)
                    if not ok_g:
                        detail['note'] = '空段 splice 被护栏拒绝：' + note_g
                        continue
                    current = cand
                    detail.update(span_new=0.0, delta=round(band['span'], 2),
                                  accepted=True,
                                  note='空段 splice：后续片整体左移段宽')
                    improved_any = True
                    accepted = band
                    if echo is not None:
                        echo('[LNS] r%d 段#%d [%.0f,%.0f) 空段 %.0fmm → '
                             '后续片左移 %.0fmm 接受'
                             % (rd + 1, band['index'], band['x_start'],
                                band['x_end'], band['span'], band['span']))
                    break
                # ---- 非空段：同口径子实例 + 子求解
                params = band_solve_params(band, current, pieces_by_id,
                                           per_type=per_type, sizes=sizes)
                if params is None:
                    detail['note'] = '段内含无 label 裁片（旧 intermediate），跳过'
                    continue
                remaining = time_budget - (time.monotonic() - t0)
                if remaining < MIN_SUB_TIME_SEC:
                    budget_hit = True
                    stop_reason = 'budget_exhausted'
                    detail['note'] = '预算耗尽，未尝试'
                    break
                params['time_budget'] = max(
                    1, int(round(remaining / max(1, rounds - rd))))
                params['seed'] = int(base_seed) + 1 + rd * 1000 + band['index']
                band_pid_set = set(band['pids'])
                pieces_subset = [p for p in pieces if p['pid'] in band_pid_set]
                try:
                    sub = solve(pieces_subset, gate_mm, params)
                    sub_placed = list(sub['placed_items'])
                except Exception as e:                    # 子求解失败 = 该段无改进
                    detail['note'] = '子求解失败: ' + str(e)
                    continue
                if len(sub_placed) != len(band['positions']):
                    detail['note'] = ('子解数量不符（%d != %d），拒绝'
                                      % (len(sub_placed), len(band['positions'])))
                    continue
                sub_geoms = [_world_polygon(pieces_by_id[it['id']],
                                            it.get('rotation', 0.0),
                                            it.get('translation', [0, 0]))
                             for it in sub_placed]
                sub_min = min(min(x for x, _ in poly) for poly in sub_geoms)
                sub_max = max(max(x for x, _ in poly) for poly in sub_geoms)
                sub_span = sub_max - sub_min
                detail['span_new'] = round(sub_span, 2)
                if sub_span >= band['span'] - ACCEPT_EPS_MM:
                    detail['note'] = ('子解不优（%.1f >= %.1f - ε），拒绝'
                                      % (sub_span, band['span']))
                    continue
                delta = band['span'] - sub_span
                # 候选布局：段位换新放置（左缘对齐原段左缘 m）、后续波段左移 delta
                shift = band['m'] - sub_min
                cand = _shifted(current, later_pos, -delta)
                for k, pos in enumerate(band['positions']):
                    it = sub_placed[k]
                    tx, ty = it.get('translation', [0, 0])
                    cand[pos] = {'id': it['id'],
                                 'rotation': round(float(it.get('rotation', 0.0)), 6),
                                 'translation': [round(float(tx) + shift, 6),
                                                 round(float(ty), 6)]}
                old_polys = [g[0] for g in _layout_geometry(current, pieces_by_id)]
                new_polys = [g[0] for g in _layout_geometry(cand, pieces_by_id)]
                ok, note = _cross_overlap_ok(old_polys, new_polys,
                                             band['positions'], later_pos)
                if not ok:
                    detail['note'] = '重叠护栏拒绝：' + note
                    continue
                detail.update(delta=round(delta, 2), accepted=True,
                              note=('接受：段跨 %.1f→%.1fmm，后续左移 %.1fmm'
                                    % (band['span'], sub_span, delta)))
                current = cand
                improved_any = True
                accepted = band
                if echo is not None:
                    echo('[LNS] r%d 段#%d [%.0f,%.0f) 局部密度 %.1f%% → 段跨 '
                         '%.0f→%.0fmm（Δ%.0fmm）接受'
                         % (rd + 1, band['index'], band['x_start'], band['x_end'],
                            band['density'] * 100, band['span'], sub_span, delta))
                break
            if budget_hit:
                break
            if accepted is None:
                stop_reason = 'no_band_improvable'
                break
            rd += 1
        else:
            stop_reason = 'rounds_cap'
    except KeyboardInterrupt:
        interrupted = True
        stop_reason = 'interrupted'
    if stop_reason == 'no_bands' and rd >= rounds:
        stop_reason = 'rounds_cap'

    geoms_f = _layout_geometry(current, pieces_by_id)
    width_after = max(max(g[2] for g in geoms_f), 0.0)
    density_after = total_area / (width_after * float(gate_mm))
    ok, issues, y_viol = recheck_layout(current, pieces_by_id, gate_mm)
    reverted = False
    if improved_any and not ok:
        # 终检失败回退输入布局：交付物恒过检（输入为求解器产物，本身应过检；
        # 回退后重跑一次复检把状态如实记录在 result_lns.json）。
        reverted = True
        current = list(placed_items)
        width_after, density_after = width_before, density_before
        ok, issues, y_viol = recheck_layout(current, pieces_by_id, gate_mm)

    return {
        'band_width_mm': round(bw, 2),
        'rounds_requested': rounds,
        'rounds_executed': rd,
        'stop_reason': stop_reason,
        'interrupted': interrupted,
        'time_budget_sec': float(time_budget),
        'elapsed': round(time.monotonic() - t0, 1),
        'improved': bool(improved_any and not reverted),
        'before': {'width_mm': round(width_before, 2),
                   'density': round(density_before, 6),
                   'n_placed': len(placed_items)},
        'after': {'width_mm': round(width_after, 2),
                  'density': round(density_after, 6),
                  'n_placed': len(current)},
        'delta': {'width_mm': round(width_before - width_after, 2),
                  'density': round(density_after - density_before, 6)},
        'rounds_detail': rounds_detail,
        'recheck': {'ok': bool(ok), 'issues': issues, 'y_violations': int(y_viol),
                    'reverted': reverted},
        'placed_items': current,
    }


# ---------------------------------------------------------------- CLI


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog='ms-lns',
        description='LNS 波段重排：对 run_dir 最优布局（portfolio incumbent）做波段级 '
                    'ruin-and-recreate，输出 result_lns.json + 前后对比 SVG')
    p.add_argument('--run-dir', required=True, metavar='DIR',
                   help='ms-run-config 的 run 目录（须含 result.json 与 '
                        'pieces_intermediate.json）')
    p.add_argument('--time', type=int, default=30, metavar='N',
                   help='LNS 总预算（秒，默认 30；子求解按剩余预算/剩余轮数分配，'
                        '耗尽即停）')
    p.add_argument('--rounds', type=int, default=5, metavar='N',
                   help='最大轮数（默认 5；整轮无段可改进提前停）')
    p.add_argument('--band-width', type=float, default=None, metavar='MM',
                   help='波段宽 mm（缺省 1.5×默认门幅≈2970；小段宽 = 更细粒度'
                        '重排）')
    return p.parse_args(argv)


def _incumbent(doc: dict, run_dir: Path | None = None) -> dict:
    """result.json → 布局来源记录（portfolio.incumbent 优先，回退 best）。

    portfolio run（US-002+）：``portfolio.incumbent.placed_items`` = 完整布局 list。
    旧式多 seed run：``best.placed_items`` 只是 int 计数（控体积），完整布局在
    边车 ``best_frame_s{seed}.json`` —— run_dir 给定时按 best.seed 读边车回填。
    """
    inc = (doc.get('portfolio') or {}).get('incumbent') or doc.get('best') or {}
    if isinstance(inc.get('placed_items'), list) and inc['placed_items']:
        return inc
    if run_dir is not None and isinstance(inc.get('seed'), (int, float)):
        side = Path(run_dir) / ('best_frame_s%d.json' % int(inc['seed']))
        if side.is_file():
            try:
                frame = json.loads(side.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                frame = {}
            if isinstance(frame.get('placed_items'), list) and frame['placed_items']:
                return frame
    raise LnsError('result.json 无 incumbent/best placed_items（尚无求解产物）')


def postprocess_run_dir(run_dir, *, time_budget, rounds, band_width=None,
                        echo=None, solve=None) -> dict:
    """run_dir 级 LNS 编排（PC-008：``ms-lns`` CLI 与 ``run_config --lns`` 共用入口）。

    读 ``run_dir/result.json``（布局来源 = ``_incumbent``：portfolio.incumbent
    优先，旧式 best 的 int 计数回退 ``best_frame_s{seed}.json`` 边车）+
    ``pieces_intermediate.json`` → ``run_lns`` 核心循环 → ``result_lns.json`` +
    ``lns_compare.svg`` 落盘。返回写盘 payload（``source`` 段 + ``run_lns`` 全部
    结果键 —— ``improved`` / ``before`` / ``after`` / ``rounds_detail`` /
    ``placed_items`` 等，调用方据此裁决回写）。

    输入缺失 / 无布局 / 参数非法抛 ``LnsError``（或 ``OSError`` /
    ``JSONDecodeError``），由调用方决定呈现：ms-lns 退出 1；run_config 降级为
    warn 跳过后处理（不否定已完成求解的交付物）。``solve`` 为子求解注入点
    （缺省真实多进程链路；单测注入 fake packer）。Ctrl-C 由 ``run_lns`` 内部
    捕获为 ``interrupted=True``（已完成轮保留在结果里），本函数不半写任何文件。
    """
    run_dir = Path(run_dir)
    doc = json.loads((run_dir / 'result.json').read_text(encoding='utf-8'))
    inter = json.loads((run_dir / 'pieces_intermediate.json').read_text(encoding='utf-8'))
    inc = _incumbent(doc, run_dir)
    placed_items = inc['placed_items']
    cfg = doc.get('config') or {}
    pieces = inter['pieces']
    gate_mm = float(inter['gate_mm'])
    seed = inc.get('seed')
    base_seed = int(seed) if isinstance(seed, (int, float)) else 0
    solve_kw = {} if solve is None else {'solve': solve}
    res = run_lns(placed_items, pieces, gate_mm,
                  per_type=cfg.get('per_type'), sizes=cfg.get('sizes'),
                  band_width=band_width, time_budget=time_budget,
                  rounds=rounds, base_seed=base_seed, echo=echo, **solve_kw)
    out = {'source': {'run_dir': str(run_dir.resolve()), 'result': 'result.json',
                      'intermediate': 'pieces_intermediate.json',
                      'incumbent_seed': base_seed,
                      'config_echo': {'per_type': cfg.get('per_type'),
                                      'sizes': cfg.get('sizes')}},
           **res}
    with open(run_dir / 'result_lns.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    write_compare_svg(run_dir / 'lns_compare.svg',
                      before=dict(res['before'], placed=placed_items,
                                  caption='LNS 前（incumbent）'),
                      after=dict(res['after'], placed=res['placed_items'],
                                 caption='LNS 后'),
                      pieces_by_id={p['pid']: p for p in pieces}, gate_mm=gate_mm)
    return out


def main(argv: list[str] | None = None) -> int:
    # 首行防乱码：Windows 管道/重定向默认 GBK，强制 UTF-8（与 run_config 同款）。
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError, OSError):
        pass
    args = _parse_args(argv)
    if args.time < 1:
        print('配置错误: --time 须 >= 1 秒，当前 %d' % args.time, file=sys.stderr)
        return 1
    if args.rounds < 1:
        print('配置错误: --rounds 须 >= 1，当前 %d' % args.rounds, file=sys.stderr)
        return 1
    if args.band_width is not None and args.band_width <= 0:
        print('配置错误: --band-width 须为正数（mm），当前 %s' % args.band_width,
              file=sys.stderr)
        return 1

    run_dir = Path(args.run_dir)
    result_path = run_dir / 'result.json'
    inter_path = run_dir / 'pieces_intermediate.json'
    if not result_path.is_file():
        print('输入错误: %s 不存在（须先 ms-run-config 产出 run_dir）'
              % result_path.resolve(), file=sys.stderr)
        return 1
    if not inter_path.is_file():
        print('输入错误: %s 不存在' % inter_path.resolve(), file=sys.stderr)
        return 1

    try:
        out = postprocess_run_dir(run_dir, time_budget=args.time,
                                  rounds=args.rounds, band_width=args.band_width,
                                  echo=print)
    except (LnsError, ValueError, KeyError, TypeError, OSError,
            json.JSONDecodeError) as e:
        print('LNS 输入错误: %s' % e, file=sys.stderr)
        return 1

    b, a, dlt = out['before'], out['after'], out['delta']
    print('[LNS] before: width=%.0fmm density=%.2f%% | after: width=%.0fmm '
          'density=%.2f%% | Δwidth=%+.0fmm Δdensity=%+.2fpt | rounds=%d/%d（%s）'
          'improved=%s'
          % (b['width_mm'], b['density'] * 100, a['width_mm'], a['density'] * 100,
             dlt['width_mm'], dlt['density'] * 100, out['rounds_executed'],
             out['rounds_requested'], out['stop_reason'], out['improved']))
    if out['recheck']['reverted']:
        print('[LNS] 终检未过（%s），已回退输入布局' % out['recheck']['issues'],
              file=sys.stderr)
    print('[LNS] result_lns.json → %s | lns_compare.svg → %s'
          % ((run_dir / 'result_lns.json').resolve(),
             (run_dir / 'lns_compare.svg').resolve()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
