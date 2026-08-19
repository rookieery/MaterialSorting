r"""LNS 波段重排核心模块（PC-007 / US-007）—— 对 portfolio 最优布局做波段级
ruin-and-recreate，突破单 seed 收敛分布上限。

用法（console_script 或 ``python -m`` 等价）::

    ms-lns --run-dir <dir> --time 30 --rounds 5 [--band-width 2865]
    python -m materialsorting.cli.lns --run-dir <dir> --time 30 --rounds 5

输入：``run_dir`` 内 ``result.json``（布局取 ``portfolio.incumbent.placed_items``，
缺席回退 ``best.placed_items`` —— 旧式多 seed run 的 best 只存 int 计数，布局在
边车 ``best_frame_s{seed}.json``，``_incumbent`` 按此回填）+
``pieces_intermediate.json``（原始轮廓 / 原面积的单一数据源）。算法（每轮 = 按段
局部密度升序逐段尝试，首个接受即完成该轮）：

  ① 按 x 切竖直波段（sparrow 世界坐标 X=用布长度；缺省段宽 1.5×NEST_GATE_MM）。
     pid 组按**首副本中心**归段 —— demand>1 的 pid 全部副本整段进波段重排（禁止
     拆分；solver 常把同 pid 副本撒满全幅，此时段足迹 [m, M] 跨全宽、重排为
     「子集整体重解」，护栏之下通常无改进空间 → 安全 no-op，见护栏段）。
  ② 每段局部密度 = 段内片**原面积**和 /（段宽 × NEST_GATE_MM），升序取最差段。
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
     复检 + ``y ≤ PLOT_SAFE_MAX_Y_MM`` 越界复检（容差 Y_TOLERANCE_MM=11mm 容纳
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
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from ..nesting_bounds.load_pieces import NEST_GATE_MM, PLOT_SAFE_MAX_Y_MM
from ..nesting_engine.constraints import validate
from ..nesting_engine.labeling import code_sort_key
from ..nesting_engine.sparrow_baseline import label_color

__all__ = ['ACCEPT_EPS_MM', 'DEFAULT_BAND_WIDTH', 'LnsError', 'split_bands',
           'band_solve_params', 'run_lns', 'recheck_layout', 'write_compare_svg',
           'postprocess_run_dir', 'main']

# 接受阈值 ε（mm）：新段跨度须比原段跨度窄 ε 以上（消浮点噪声 / 取整抖动）。
ACCEPT_EPS_MM = 0.5
# y 越界复检容差（mm）：求解器约束的是 **erode 后** 形状 ∈ [0, strip_height]，原形
# 可合法外凸 ≤ erode 深度（MAX_OVERLAP_MM=10）+ 数值余量 —— 与生产导出口径同源
# （export 对 y>1910 削平裁剪而非判废）。LNS 复检只拦**粗暴越界**（子解溢出约束带）。
Y_TOLERANCE_MM = 11.0
# 跨组重叠护栏逐对容差（mm²）：任一跨组位置对的交集面积比原布局同对超出此值
# 即拒绝（防「净增为零、局部恶化」的重叠 redistribution；容差只吸收坐标 rounding）。
GUARD_SLACK_MM2 = 1.0
# 最小子求解预算（秒）：剩余预算低于此值视为耗尽（int 秒预算无法有意义分配）。
MIN_SUB_TIME_SEC = 1.0
# 缺省波段宽 = 1.5 × NEST_GATE_MM（≈2865mm； Jeans 片长 ~1.3m，段内约两片纵深）。
DEFAULT_BAND_WIDTH = 1.5 * NEST_GATE_MM


class LnsError(ValueError):
    """LNS 输入错误（布局为空 / pid 不在 intermediate / 参数非法等，CLI 退出 1）。"""


# ---------------------------------------------------------------- 几何基元


def _world_polygon(piece, rotation, translation):
    """intermediate 原始 polygon + placement → 世界坐标点列。

    与 ``web.export.apply_transform`` / ``sparrow_baseline._transform_polygon``
    同公式（world = R(θ)·(x,y) + t）；本模块不 import web.export（其模块级拉
    matplotlib），4 行公式内联 + 注明同源。
    """
    r = math.radians(float(rotation))
    c, s = math.cos(r), math.sin(r)
    tx, ty = float(translation[0]), float(translation[1])
    return [(x * c - y * s + tx, x * s + y * c + ty) for x, y in piece['polygon']]


def _layout_geometry(placed_items, pieces_by_id):
    """逐项 ``[(world_poly, xmin, xmax)]``（原始轮廓口径 = 真实 marker 足迹）。

    pid 不在 intermediate 时抛 ``LnsError`` —— 数量不变量优先，绝不静默丢片
    （export.placed_to_world 的 warning-跳过策略对 LNS 不可接受：丢片即改 Σdemand）。
    """
    geoms = []
    for it in placed_items:
        p = pieces_by_id.get(it['id'])
        if p is None:
            raise LnsError(
                f"布局含 intermediate 之外的 pid {it['id']!r}（incumbent 与 pieces 不匹配）")
        poly = _world_polygon(p, it.get('rotation', 0.0), it.get('translation', [0, 0]))
        xs = [x for x, _ in poly]
        geoms.append((poly, min(xs), max(xs)))
    return geoms


# ---------------------------------------------------------------- 波段切分


def split_bands(placed_items, pieces_by_id, band_width):
    """布局 → 波段列表（index 升序；pid 组按**首个副本**中心整组归段，禁止拆分）。

    返回 ``list[dict]``，每段：

      - ``index`` / ``x_start`` / ``x_end`` / ``slab_width``：竖直 slab 几何
        （[i·bw, (i+1)·bw)，末段截至布局总宽）；
      - ``positions`` / ``pids``：段内条目在布局列表中的下标 / pid 集（组内全部
        副本整段进入，demand>1 不拆分）；
      - ``m`` / ``M`` / ``span``：段内片的**实际足迹**（min xmax / max xmax），
        空段退化为 slab 本身（纯空洞，splice 直接整段让位）；
      - ``density``：段内片**原面积**和 /（slab_width × NEST_GATE_MM）。

    ``band_width`` 非正抛 ``LnsError``；布局总宽 ≤0（理论不可达，防御）返回 []。
    """
    bw = float(band_width)
    if bw <= 0:
        raise LnsError(f'band_width 须为正数（mm），当前 {bw}')
    geoms = _layout_geometry(placed_items, pieces_by_id)
    total_width = max((g[2] for g in geoms), default=0.0)
    if total_width <= 0.0:
        return []
    n_bands = max(1, int(math.ceil(total_width / bw - 1e-9)))
    bands = [{'index': i,
              'x_start': i * bw,
              'x_end': min((i + 1) * bw, total_width),
              'positions': [], 'pids': []} for i in range(n_bands)]
    group_band: dict[str, int] = {}
    for pos, it in enumerate(placed_items):
        pid = it['id']
        bi = group_band.get(pid)
        if bi is None:
            _poly, xmin, xmax = geoms[pos]
            center = (xmin + xmax) / 2.0
            bi = min(n_bands - 1, max(0, int(center // bw)))
            group_band[pid] = bi
            bands[bi]['pids'].append(pid)
        bands[bi]['positions'].append(pos)
    out = []
    for b in bands:
        slab = b['x_end'] - b['x_start']
        if b['positions']:
            m = min(geoms[p][1] for p in b['positions'])
            cap = max(geoms[p][2] for p in b['positions'])
            area = sum(float(pieces_by_id[placed_items[p]['id']]['area_mm2'])
                       for p in b['positions'])
        else:
            m, cap, area = b['x_start'], b['x_end'], 0.0
        out.append({**b, 'slab_width': slab, 'm': m, 'M': cap, 'span': cap - m,
                    'density': (area / (slab * NEST_GATE_MM)) if slab > 0 else 0.0})
    return out


def band_solve_params(band, placed_items, pieces_by_id, *, per_type=None,
                      sizes=None, time_budget=1, seed=0):
    """段 → ``web.solver.build_instance`` 同口径子实例参数 dict。

    quantities 按段内**实际副本数**派生（见模块 docstring ③：与母 demand 表在该
    pid 上的投影等价，中间帧 incumbent 也成立）。段内含无 label 裁片（旧
    intermediate）时无法经 quantities 表达 demand → 返回 None（调用方跳过该段，
    数量不变量优先）。返回 dict 的键与 ``build_instance`` 关键字一一对应。
    """
    quantities: dict = {}
    for pos in band['positions']:
        p = pieces_by_id[placed_items[pos]['id']]
        label = p.get('label')
        if label is None:
            return None
        sk = 'null' if p['size'] is None else str(p['size'])
        size_map = quantities.setdefault(label, {})
        size_map[sk] = size_map.get(sk, 0) + 1
    return {
        'time_budget': int(time_budget),
        'seed': int(seed),
        'sizes': sizes,
        'per_type': per_type,
        'quantities': quantities,
    }


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


# ---------------------------------------------------------------- 重叠护栏


def _bbox_of(poly):
    xs = [x for x, _ in poly]
    ys = [y for _, y in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _pair_area(geoms, i, j):
    """shapely 精确交集面积；bbox 不相交直接 0（绝大多数对在此短路）。"""
    a0, a1, a2, a3 = _bbox_of(geoms[i])
    b0, b1, b2, b3 = _bbox_of(geoms[j])
    if a0 >= b2 or b0 >= a2 or a1 >= b3 or b1 >= a3:
        return 0.0
    from shapely.geometry import Polygon
    return float(Polygon(geoms[i]).intersection(Polygon(geoms[j])).area)


def _cross_overlap_ok(old_polys, new_polys, band_pos, later_pos):
    """跨组重叠护栏（见模块 docstring）：**逐对**不劣化才放行。

    对每个跨组对 ``(i, j)``（``band × fixed``、``band × later``、``later × fixed``）
    要求 ``new_area(i,j) ≤ old_area(i,j) + GUARD_SLACK_MM2`` —— 不允许把重叠
    「挪个位置藏起来」（净增为零但局部恶化的 redistribution 一律拒）。段内（子求
    解语义）与左移段内部（刚体平移）的非重叠性由构造保持，不查。原布局里合法的
    d-erode 重叠在同对基线内自然放行。返回 ``(ok, note)``；shapely 不可用 →
    ``(True, '护栏跳过')``（降级为 PC-007 规格行为，明细留痕）。
    """
    try:
        import shapely.geometry  # noqa: F401
    except Exception:
        return True, 'shapely 不可用，护栏跳过'
    n = len(old_polys)
    band_set = set(band_pos)
    later_set = set(later_pos)
    fixed = [p for p in range(n) if p not in band_set and p not in later_set]
    pairs = ([(i, j) for i in band_pos for j in fixed]
             + [(i, j) for i in band_pos for j in later_pos]
             + [(i, j) for i in later_pos for j in fixed])
    worst = None
    try:
        for i, j in pairs:
            d = _pair_area(new_polys, i, j) - _pair_area(old_polys, i, j)
            if d > GUARD_SLACK_MM2:
                worst = (i, j, d)
                break
    except Exception:
        return True, '护栏内部异常，跳过'
    if worst is not None:
        i, j, d = worst
        return False, f'位置对 #{i}×#{j} 重叠增 {d:.1f}mm²（逐对不劣化被破坏）'
    return True, 'ok'


# ---------------------------------------------------------------- 复检


def recheck_layout(placed_items, pieces_by_id, gate_mm):
    """PC-007 ⑤ 全版复检：``constraints.validate`` + ``y ≤ PLOT_SAFE_MAX_Y_MM``。

    ``validate`` 的 x 界检查是门幅方向（老位图引擎口径 x=幅宽），而 sparrow 世界
    坐标 Y=门幅 → 传 **(y, x) 交换**坐标（再整体 +Y_TOLERANCE_MM 平移、gate 同步
    放宽 2×Y_TOLERANCE_MM，容纳 erode 合法外凸），gate 与求解约束带
    ``strip_height=min(gate, PLOT_SAFE)`` 同源，覆盖「数量 / 幅宽向界内 / 用布
    正向」三项；y 向另按 ``PLOT_SAFE_MAX_Y_MM`` 复检（越界片计数，容差
    ``Y_TOLERANCE_MM``）。返回 ``(ok, issues, y_violations)``。
    """
    geoms = _layout_geometry(placed_items, pieces_by_id)
    width = max((g[2] for g in geoms), default=0.0)
    carriers = [SimpleNamespace(pid=it['id']) for it in placed_items]
    swapped = [(carriers[k], [(y + Y_TOLERANCE_MM, x) for x, y in geoms[k][0]])
               for k in range(len(geoms))]
    ok, issues = validate(swapped, swapped, width,
                          NEST_GATE_MM + 2 * Y_TOLERANCE_MM, 1.0)
    y_viol = sum(1 for poly, _xm, _mx in geoms
                 if max(y for _, y in poly) > PLOT_SAFE_MAX_Y_MM + Y_TOLERANCE_MM)
    if y_viol:
        issues = list(issues) + [
            f'{y_viol} 片越过绘图仪可写幅宽 y<={PLOT_SAFE_MAX_Y_MM:.0f}mm']
    return bool(ok and y_viol == 0), list(issues), y_viol


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
        门幅（density 分母口径；子求解约束带在 build_instance 内钳
        ``min(gate_mm, PLOT_SAFE_MAX_Y_MM)``，与母实例同口径）。
    per_type / sizes : result.json ``config`` 段回显的同名求解参数（子实例同口径
        透传：erode/tol/orientations 钳制行为与母实例一致）。
    band_width : float | None
        波段宽（mm）；None → ``DEFAULT_BAND_WIDTH``（= 1.5×NEST_GATE_MM）。
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
            bands = split_bands(current, pieces_by_id, bw)
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


# ---------------------------------------------------------------- 对比 SVG


def _fmt(x: float) -> str:
    """浮点 → SVG 紧凑字符串（与 sparrow_baseline._fmt 同口径）。"""
    return ('%.2f' % x).rstrip('0').rstrip('.')


def write_compare_svg(out_path, *, before, after, pieces_by_id, gate_mm,
                      title='LNS 前后对比'):
    """前后双面板对比 SVG（``run_dir/lns_compare.svg``）。

    - 坐标口径与其余排料 SVG 一致：viewBox 毫米、每面板一个
      ``translate(0, 面板底) scale(1,-1)`` 翻转组（数据 y 向上，与 PNG / R12-DXF
      导出同口径）；
    - 配色 ``label_color``（g 码 16 色循环单一真相源）；
    - 面板题注（正常 y 坐标系）：caption + width + 原面积口径 density；
    - 两面板共用宽度标尺（取 max(width)），缩短量一眼可对照。

    ``before`` / ``after`` 形如 ``{'placed': [...], 'width_mm': W, 'density': d,
    'caption': 'LNS 前'}``；``pieces_by_id`` 为 intermediate pid → piece 映射
    （原始轮廓渲染，与导出同源）。
    """
    gate = float(gate_mm)
    W = max(float(before['width_mm']), float(after['width_mm']), 1.0)
    cap = gate * 0.075 + 30.0            # 题注带高（mm 画面单位）
    mx = gate * 0.03
    legend_w = gate * 0.24
    font = max(gate * 0.022, 12.0)
    title_h = font * 1.9
    svg_w = W + 2 * mx + legend_w
    svg_h = title_h + 2 * (cap + gate) + 3 * mx

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.1f %.1f" '
        'width="%.0f" height="%.0f" font-family="sans-serif">'
        % (svg_w, svg_h, svg_w / 8, svg_h / 8),
        '<text x="%.1f" y="%.1f" font-size="%.0f" fill="#111" '
        'font-weight="bold">%s</text>' % (mx, title_h * 0.72, font * 1.2, title),
    ]
    for i, lay in enumerate((before, after)):
        oy = title_h + mx + i * (cap + gate + mx) + cap
        ox = mx
        w = max(float(lay['width_mm']), 1.0)
        caption = '%s：width=%.0fmm  density=%.2f%%' % (
            lay.get('caption', ''), float(lay['width_mm']), float(lay['density']) * 100)
        parts.append(
            '<text x="%.1f" y="%.1f" font-size="%.0f" fill="#222" '
            'font-weight="bold">%s</text>' % (ox, oy - cap * 0.45, font, caption))
        parts.append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#fafafa" '
            'stroke="#333" stroke-width="%.1f"/>' % (ox, oy, w, gate, max(W, gate) * 0.002))
        parts.append('<g transform="translate(%.1f,%.1f) scale(1,-1)">' % (ox, oy + gate))
        for it in lay['placed']:
            p = pieces_by_id.get(it['id'])
            if p is None or len(p['polygon']) < 3:
                continue
            world = _world_polygon(p, it.get('rotation', 0.0),
                                   it.get('translation', [0, 0]))
            pts = ' '.join('%s,%s' % (_fmt(x), _fmt(y)) for x, y in world)
            color = label_color(p.get('label'))
            parts.append(
                '<polygon points="%s" fill="%s" fill-opacity="0.55" '
                'stroke="%s" stroke-width="%.1f"/>' % (pts, color, color,
                                                       max(W, gate) * 0.0015))
        parts.append('</g>')

    # 图例（右侧整列，正常 y 坐标系）：两面板出现的 g 码并集，code_sort_key 数值序
    labels = sorted({(pieces_by_id.get(it['id']) or {}).get('label')
                     for lay in (before, after) for it in lay['placed']} - {None},
                    key=code_sort_key)
    lx = mx + W + mx * 0.6
    ly = title_h + mx + cap
    step = gate * 0.035
    if labels:
        parts.append('<text x="%.1f" y="%.1f" font-size="%.0f" '
                     'font-weight="bold" fill="#222">裁片图例</text>' % (lx, ly, font))
        ly += step * 1.4
        for t in labels:
            color = label_color(t)
            parts.append(
                '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" '
                'fill-opacity="0.55" stroke="%s"/>'
                % (lx, ly - step * 0.7, step * 1.2, step * 1.2, color, color))
            parts.append('<text x="%.1f" y="%.1f" font-size="%.0f" '
                         'fill="#333">%s</text>' % (lx + step * 1.8, ly, font * 0.9, t))
            ly += step
    parts.append('</svg>')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))


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
                   help='波段宽 mm（缺省 1.5×NEST_GATE_MM≈2865；小段宽 = 更细粒度'
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
