"""LNS 共享基元：常量 / LnsError / 几何算子 / 波段切分 / 重叠护栏 / 全版复检（cli.lns 门面的底层模块）。"""
from __future__ import annotations

import math
from types import SimpleNamespace

from ..nesting_bounds.load_pieces import NEST_GATE_MM, PLOT_SAFE_MAX_Y_MM
from ..nesting_engine.constraints import validate

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

    quantities 按段内**实际副本数**派生（见 cli/lns.py 模块 docstring ③：与母
    demand 表在该 pid 上的投影等价，中间帧 incumbent 也成立）。段内含无 label
    裁片（旧 intermediate）时无法经 quantities 表达 demand → 返回 None（调用方
    跳过该段，数量不变量优先）。返回 dict 的键与 ``build_instance`` 关键字一一对应。
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
    """跨组重叠护栏（见 cli/lns.py 模块 docstring）：**逐对**不劣化才放行。

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
