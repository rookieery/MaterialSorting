"""腰头成带核心模块（US-009）—— 带内聚排 + 组合片构造 + 展开纯函数。

机制（依据 ``.docs/business/腰头成带_落地方案.md`` §2，2026-08-21 定稿；US-014
修订）：腰头 g 码裁片在**全幅**（钳主解可写幅宽 ``PLOT_SAFE_MAX_Y_MM``）带内独立
小求解聚排，**成对形态重试选解**（固定派生 seed 序列取首个同码全成对解 ——
成对以带内聚排形态实现、不写求解硬约束；窄条带与 1161mm 长成员 + grain ±3°
锁定矛盾，已否决）→ 成员**原始轮廓**@带内位 ``shapely.unary_union`` → 焊接连通 →
``erode(d_g)`` → ``_clean_polygon`` → 平移归一化（记录 offset），整簇 union 外轮廓
作为一片虚拟组合片（``WB_*`` pid）投入主求解；主解帧发射前用 ``expand_placements``
把组合片 placement 展开回成员 placement。性质是**业务规则**（确定性聚排形态），
不是利用率优化器 —— 验收线 = 形态保证 + 密度不显著劣化。

分层约束：本模块属 ``nesting_engine``，仅 import 标准库 + shapely + 本包兄弟模块
（``sparrow_baseline`` / ``sparrow_experiments`` / ``constraints``）+ 下层
``nesting_bounds``；**禁 import web**（组合片构造与展开的单一真相源，web 与未来
CLI 共用）。

展开权威式（黄金单测锁死，见 ``expand_placements`` docstring）::

    rot_f = m.rot + c.rot
    tr_f  = R(c.rot)·(m.tr − offset) + c.tr        # offset=(minx,miny)，注意是减号
"""
from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field

from shapely.geometry import Polygon
from shapely.ops import unary_union

from ..nesting_bounds.load_pieces import NEST_GATE_MM, PLOT_SAFE_MAX_Y_MM
from .constraints import discretize_orientations
from .sparrow_baseline import _clean_polygon, _transform_polygon
from .sparrow_experiments import erode_polygon

# 组合片 pid 前缀（全链路泄漏哨兵：manifest/frame/final/前端/导出永不允许出现 WB_）。
COMPOSITE_PID_PREFIX = 'WB_'
# 组合片在主解的允许朝向（FR-8 版师确认 2026-08-21：成带后整块不再旋转，0°/180°
# 均严格顺布纹、仅头尾调换；±3° 抖动会使整块 bbox 膨胀且产生斜缝 —— 工艺公差属于
# 裁片不属于带。旋转自由度只存在于带内成员贴排（各自 grain tol 内））。
COMPOSITE_ORIENTATIONS = (0.0, 180.0)
# 组合片轮廓顶点阈值：超阈值时对最终轮廓 simplify(0.05)（弧形腰片 union 后可达
# ~500+ 顶点，NFP 代价是 US-010 微基准关注点；0.05mm 偏差 ≪ 包络容差 0.5mm）。
MAX_COMPOSITE_VERTICES = 600
SIMPLIFY_TOLERANCE_MM = 0.05
# 带内子求解默认预算（初值 15s/带，与 fill 曲线挂钩 —— 落地方案 §2.5；US-010 实测标定）。
DEFAULT_BAND_TIME_BUDGET_S = 15
# 带内填充率下限（%）：腰 g05 实测 ~70%+（实际占用 bbox 口径），裤耳 g06 类 13%
# 灾难形态在此拦截。禁止无声 shelf 兜底 —— 异常 fail-fast 抛 BandQualityError。
FILL_FLOOR_PCT = 45.0
# 带内子求解 worker 数：**锁 1**。实测 spyrrow 同 seed 下 num_workers=1 与 =4 结果
# 不同（多 worker 改变搜索轨迹），而确定性验收要求同 seed 可重放 —— 固定值是重放
# 不变量之一（BandChunk 之外），带内仅 ~14 片小实例单 worker 足够。
BAND_NUM_WORKERS = 1
# 焊接初始半径（mm）：strip 解成员间常有亚毫米~数毫米缝隙（sparrow 不保证贴触），
# closing(X, r) = X⊕r⊖r（恒 ⊇ X）把 ≤2r 的缝焊成整带单组合片；缝隙更大时半径逐次
# 翻倍直至连通（见 ``_solid_region``）。成员原始轮廓本身已含 d_g 外扩，正常紧排解
# 缝隙远小于 2×WELD_RADIUS_MM，r 不增长、外轮廓凹口（FR-9 密度回收来源）保持开放。
WELD_RADIUS_MM = 1.0
# 焊接半径上限（mm）：超过仍不连通 = 解真正散落（fill 下限理应已拦截），fail-fast。
WELD_RADIUS_MAX_MM = 512.0
# 同码成对相邻判据的边距容差（mm）：同 pid 副本最近**边距** <= 此值视为成对
# 相邻（US-014 形态判据 + band_accept 验收同口径）。取 10 与 ``WELD_RADIUS_MM``
# 注释同源：spyrrow 紧排解实测缝隙 0.01~10mm（不保证贴触）。
PAIR_ADJ_EPS_MM = 10.0
# 成对形态重试次数：每次独立派生 seed 重解全带，取首个「同码全成对」解。
# US-014 实测（5336 g05，2s/次）：成对形态出现率 ~50%/次（主解 seed 0/1/2 的
# 首试分别 100%/31%/54%，6 次内必有 —— 全败概率 ~1.6%，届时 BandQualityError
# fail-fast 禁无声降级）。单次全量求解 + 输入 size-major 序**不**保证同码相邻
# （spyrrow 不按喂入序聚排，实测 3 seed 中 2 个同码对散落 400mm+）。
BAND_MAX_TRIES = 6


class BandError(Exception):
    """成带失败基类（web 层按需捕获转结构化 error）。"""


class DegenerateBand(BandError):
    """带退化：总副本 1（无法成对/聚簇）或组合片轮廓腐蚀后不足 3 顶点。"""


class BandQualityError(BandError):
    """带质量不达标：填充率低于下限 / 副本守恒失败 / 解散落不成块。

    禁止无声 shelf 兜底（落地方案 §2.5）—— 质量悬崖必须显式报错。"""


def band_seed_for(seed, label) -> int:
    """主解 seed + label → 带内子求解 seed（确定性派生）。

    勿用 ``hash()``：对 str 有 PYTHONHASHSEED 随机化，跨进程不可重放；
    ``zlib.crc32`` 纯函数、稳定且无碰撞顾虑（band seed 只需跨 label/seed 可区分）。
    """
    return zlib.crc32(f'{seed}|{label}'.encode('utf-8'))


def _member_sort_key(meta: dict, pid: str):
    """size-major 排序键（成员收集/输出定序 —— 同码副本列表相邻，落地方案
    §2.4；size=None 排最后（v2 schema 理论上 size 恒非 None，防御性兜底））。"""
    size = meta.get('size')
    if size is None:
        return (1, 0.0, pid)
    return (0, float(size), pid)


@dataclass
class BandChunk:
    """成带产物：整带单组合片 + 成员带内位 + 展开所需全部几何（纯 JSON 可序列化）。

    ``polygon`` 为归一化组合片轮廓（原点系，erode d_g + clean 后）；主解构造
    ``spyrrow.Item(id=pid, shape=polygon, demand=1, allowed_orientations=
    list(COMPOSITE_ORIENTATIONS))``。``offset`` 是成员 union bbox 最小角（带内
    绝对坐标），展开时**减去**（见 ``expand_placements``）。
    """

    pid: str                      # 组合片 pid（WB_ 前缀，如 WB_g05）
    label: str                    # 腰头 g 码
    polygon: list                 # 归一化组合片轮廓 [[x,y],...]（erode d_g 后）
    offset: tuple                 # (minx, miny)：成员 union bbox 最小角（展开减号）
    members: list                 # [{'pid','rotation','translation'}] 逐副本带内位（size-major 序）
    fill_pct: float               # 带内填充率（成员原面积和 / union bbox 面积 ×100）
    bbox: dict                    # {'width_mm','height_mm'} union bbox（实际占用，非全幅）
    seed: int                     # 带内子求解实际使用的 seed（crc32 派生，回放对拍用）
    d_g: float                    # 该 g 码重合公差（组合片 erode 深度）
    tol_g: float                  # 该 g 码旋转公差（成员带内离散角）
    n_members: int = field(init=False)

    def __post_init__(self):
        self.n_members = len(self.members)

    @property
    def total_demand(self) -> int:
        """成员副本总数（= Σ pid_meta demand，守恒断言口径）。"""
        return len(self.members)

    def to_dict(self) -> dict:
        """JSON 可序列化 dict（US-011 band_runs 工件 / 确定性对拍用；纯几何不含
        wall-clock —— 同 seed 两跑 ``json.dumps`` 相等）。"""
        return {
            'pid': self.pid,
            'label': self.label,
            'polygon': [[float(x), float(y)] for x, y in self.polygon],
            'offset': [float(self.offset[0]), float(self.offset[1])],
            'members': [
                {
                    'pid': m['pid'],
                    'rotation': float(m['rotation']),
                    'translation': [float(m['translation'][0]),
                                    float(m['translation'][1])],
                }
                for m in self.members
            ],
            'n_members': self.n_members,
            'fill_pct': round(float(self.fill_pct), 4),
            'bbox': {'width_mm': float(self.bbox['width_mm']),
                     'height_mm': float(self.bbox['height_mm'])},
            'seed': int(self.seed),
            'd_g': float(self.d_g),
            'tol_g': float(self.tol_g),
        }


def expand_placements(chunk: BandChunk, rotation: float, translation) -> list:
    """组合片主解放置 → 成员 placement 列表（展开权威式，黄金单测锁死）。

    推导（与 PlacedItem docstring / ``sparrow_baseline._transform_polygon`` /
    ``web.export_geometry.apply_transform`` / 前端 ``lib/geometry.ts`` 四处同构
    —— 先绕原点旋转再平移）::

        成员带内足迹   P_band  = R(m.rot)·p + m.tr
        组合片归一化   P_comp  = P_band − offset          # offset=(minx,miny)，减号
        主解放置       P_world = R(c.rot)·P_comp + c.tr
        合并 ⇒  rot_f  =  m.rot + c.rot
                tr_f   =  R(c.rot)·(m.tr − offset) + c.tr  # 注意是减号

    Parameters
    ----------
    chunk : BandChunk
        ``build_band_plan`` 产物（offset / members 均带内绝对坐标）。
    rotation : float
        组合片在主解的旋转角（度；容忍 spyrrow 负角如 -180.0）。
    translation : Sequence[float]
        组合片在主解的平移 (tx, ty)。

    Returns
    -------
    list[dict]
        ``[{'id': pid, 'rotation': rot_f, 'translation': [tx, ty]}, ...]`` —— 逐副本
        一条（守恒：Σ 条数 == Σ demand），shape 与 ``solve_worker._emit_placed``
        对齐，US-011 在该单点直接替换 WB_ 条目。
    """
    rad = math.radians(float(rotation))
    c, s = math.cos(rad), math.sin(rad)
    ox, oy = float(chunk.offset[0]), float(chunk.offset[1])
    ctx, cty = float(translation[0]), float(translation[1])
    out = []
    for m in chunk.members:
        dx = float(m['translation'][0]) - ox        # m.tr − offset（减号！）
        dy = float(m['translation'][1]) - oy
        out.append({
            'id': m['pid'],
            'rotation': (float(m['rotation']) + float(rotation)) % 360.0,
            'translation': [dx * c - dy * s + ctx, dx * s + dy * c + cty],
        })
    return out


def _solid_region(union) -> Polygon:
    """union → 整带连通单 Polygon（closing 焊接，恒 ⊇ 原 union）。

    strip 解成员间常有缝隙（sparrow 不保证贴触，实测同 seed 2s 解即有 0.01~10mm
    缝），``unary_union`` 可得 MultiPolygon；「整带单组合片」要求连通区域，故用
    closing(X, r) = X ⊕r ⊖r 焊接：数学上恒为原集合的超集（包络断言不受影响），
    r 从 ``WELD_RADIUS_MM`` 起翻倍直到结果连通。半径增大只填充更宽的凹口/缝隙
    （散落解浪费面积，fill 下限已在构造期拦截真正散落）；到上限仍不连通视为病态。
    """
    r = WELD_RADIUS_MM
    while True:
        welded = union.buffer(r).buffer(-r)
        if welded.geom_type == 'Polygon' and not welded.is_empty:
            return welded
        if r >= WELD_RADIUS_MAX_MM:
            raise BandQualityError(
                f'带内解散落不成块（焊接半径 {r:.0f}mm 仍不连通），拒绝构造组合片')
        r = min(r * 2.0, WELD_RADIUS_MAX_MM)


def _exterior_coords(poly) -> list:
    """shapely Polygon → 外环坐标 list[[x,y]]（去闭合尾点；内腔丢弃 —— FR-9 v1 死区）。"""
    coords = list(poly.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [[float(x), float(y)] for x, y in coords]


def _valid_geometry(coords):
    """世界坐标轮廓 → 有效几何（union 输入）。

    真实 DXF 离散化轮廓可能有微自交（实测 M1787 g05 弧线即触发
    ``TopologyException: side location conflict``），``buffer(0)`` 是 shapely
    标准修复（与 ``erode_polygon`` 同法）；修复后为空（极端退化）回退凸包 ——
    包络安全超集方向（多占不多漏）。
    """
    g = Polygon(coords)
    if g.is_valid:
        return g
    repaired = g.buffer(0)
    if not repaired.is_empty:
        return repaired          # Polygon 或 MultiPolygon（均有效，union 可直接吃）
    return g.convex_hull


def _pairs_complete(placed: list, polys: dict,
                    eps_mm: float = PAIR_ADJ_EPS_MM) -> bool:
    """全带同码成对完整性检查：每个多副本 pid 的每个副本到同 pid 最近邻的
    **边距** <= eps（重试选解判据，US-014 形态判据引擎侧同口径）。

    边距（shapely ``distance``）与朝向无关 —— 头尾翻转 180° 成对（FR-8 形态，
    L/w≈6 长片中心连线沿长边、中心距可达 L 量级而物理边距 ~0）只有边距口径能
    正确判相邻。``polys`` 为成员（已腐蚀）轮廓，与 spyrrow 放置口径一致。
    """
    groups: dict = {}
    for m in placed:
        groups.setdefault(m['pid'], []).append(m)
    for pid, copies in groups.items():
        if len(copies) < 2:
            continue
        geoms = []
        for m in copies:
            g = _valid_geometry(
                _transform_polygon(polys[pid], m['rotation'], m['translation']))
            geoms.append(g if g.geom_type == 'Polygon' else g.convex_hull)
        if any(min(a.distance(b) for j, b in enumerate(geoms) if j != i) > eps_mm
               for i, a in enumerate(geoms)):
            return False
    return True


def _slot_fallback(member_pids: list, pid_meta: dict, polys: dict) -> list:
    """重试全败后的确定性槽位兜底：逐 pid 副本沿 X bbox 槽位并排、块沿 X 拼接。

    构造性成对（相邻槽对面边距 = 0 <= eps，slot 宽 = 足迹 bbox 宽故槽内不可能
    重叠）；代价是放弃嵌套形态 —— fill = Σarea / 槽位带 bbox（矩形类 ~100%、
    弧形腰片 ~40%），整带 fill 下限（``FILL_FLOOR_PCT``）仍在下游兜底拦截劣质
    形态（弧形片兜底即 fail-fast，矩形/多边形类兜底即最优紧排）。仅当重试
    ``BAND_MAX_TRIES`` 次全败时启用（实测真实 5336 g05 成对形态出现率 ~50%/次，
    全败概率 ~1.6%；合成矩形小实例 spyrrow 短预算不聚排、走本兜底属正常路径）。
    """
    placed = []
    cursor = 0.0
    for pid in member_pids:                      # size-major 序（块序 = 码序）
        poly = polys[pid]
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        slot_w = max(xs) - min(xs)
        ox, oy = -min(xs), -min(ys)              # 块内归一到原点
        for _i in range(int(pid_meta[pid]['demand'])):
            placed.append({
                'pid': pid,
                'rotation': 0.0,
                'translation': [cursor + ox, oy],
            })
            cursor += slot_w
    return placed


def build_band_plan(pid_meta, pieces_by_id, *, label, seed,
                    gate_nest=NEST_GATE_MM, d_g=0.4, tol_g=3.0,
                    time_budget=DEFAULT_BAND_TIME_BUDGET_S,
                    fill_floor=FILL_FLOOR_PCT) -> BandChunk:
    """带内聚排 → 组合片构造（单一真相源；web 编排在 US-011 接线）。

    Parameters
    ----------
    pid_meta : dict
        ``web.solver.build_pid_meta`` 产物 ``{pid: {label, size, demand, polygon,
        area_mm2, ...}}``。成员 Item 直接用其**已腐蚀** polygon（不二次腐蚀）；
        demand>0 过滤已由 build_pid_meta 完成（此处再校验兜底）。
    pieces_by_id : dict
        intermediate 原始裁片 ``{pid: {'polygon': 原始轮廓, ...}}`` —— union 与
        包络断言用**原始**轮廓（erode 只进 spyrrow 碰撞，不缩面积/不缩带）。
    label : str
        腰头 g 码（如 'g05'；跨母版漂移由用户在 UI 指认）。
    seed : int
        主解 seed；带内 seed = ``band_seed_for(seed, label)``（crc32 派生，确定性）。
    gate_nest : float
        带内子求解约束带高度（全幅有效幅宽，缺省 ``NEST_GATE_MM``）。
    d_g : float
        该 g 码重合公差（应与构造 pid_meta 时该 label 的 per_type d 同值；组合片
        union 后 erode 深度 —— 使主解其他裁片对带边界保持与单片相同的 d_g 邻接语义）。
    tol_g : float
        该 g 码旋转公差（成员带内 orientations = ``discretize_orientations(tol_g)``，
        grain 锁 {0,180}±tol）。
    time_budget : int
        带内子求解总预算（秒）—— 重试均摊（每次 ``max(1, total//BAND_MAX_TRIES)``，
        US-014 起成对形态重试选解；原单次全量语义废弃）。
    fill_floor : float
        带内填充率下限（%），低于即 BandQualityError（禁止无声兜底）。

    Returns
    -------
    BandChunk
    """
    import spyrrow

    # ---- 1) 成员收集 + 副本守恒前置校验 -----------------------------------
    member_pids = sorted(
        (pid for pid, m in pid_meta.items()
         if m.get('label') == label and int(m.get('demand', 0)) > 0),
        key=lambda pid: _member_sort_key(pid_meta[pid], pid))
    if not member_pids:
        raise ValueError(f'band label {label!r} 无 demand>0 裁片（0 副本，不可成带）')
    total_demand = sum(int(pid_meta[pid]['demand']) for pid in member_pids)
    if total_demand == 1:
        raise DegenerateBand(
            f'band label {label!r} 总副本 1 —— 单片无成对/聚簇意义，直接走主解')

    # ---- 2) 带内子求解（全幅；成对形态重试选解 —— US-014） -------------------
    # PRD 非目标口径「成对以带内排序 + 验收指标实现，不写求解硬约束」。实测
    # spyrrow 不按喂入序聚排（输入 size-major 序无效），单次解同码对可散落
    # 400mm+；但同码全成对的紧排解在解空间中常见（实测 ~50%/次）。故用固定
    # 派生 seed 序列重试取**首个成对完整解**（确定性：同主 seed 重放同序列），
    # BAND_MAX_TRIES 次全败 = 形态质量悬崖 → BandQualityError fail-fast。
    # 幅宽钳 min(gate, PLOT_SAFE_MAX_Y_MM)：组合片要进主解条带（build_instance
    # strip_height=min(gate,1910)），超幅组合片主解放不下。
    band_seed = band_seed_for(seed, label)
    try_time = max(1, int(time_budget) // BAND_MAX_TRIES)
    items = []
    polys: dict = {}
    for pid in member_pids:
        meta = pid_meta[pid]
        poly = _clean_polygon(meta['polygon'])
        if len(poly) < 3:
            raise DegenerateBand(f'成员 {pid} 腐蚀/清洗后顶点<3，不可成带')
        polys[pid] = poly
        items.append(spyrrow.Item(
            id=pid,
            shape=[(float(x), float(y)) for x, y in poly],
            demand=int(meta['demand']),
            allowed_orientations=discretize_orientations(tol_g),
        ))
    placed = None
    for k in range(BAND_MAX_TRIES):
        instance = spyrrow.StripPackingInstance(
            name=f'band_{label}_try{k}', strip_height=float(
                min(gate_nest, PLOT_SAFE_MAX_Y_MM)), items=items)
        config = spyrrow.StripPackingConfig(
            total_computation_time=try_time,
            seed=band_seed_for(band_seed, f'try{k}'),   # 重试 seed 确定性派生
            num_workers=BAND_NUM_WORKERS)
        sol = instance.solve(config)
        cand = [
            {
                'pid': pi.id,
                'rotation': float(pi.rotation) % 360.0,   # spyrrow 可回负角（如 -180）
                'translation': [float(pi.translation[0]), float(pi.translation[1])],
            }
            for pi in sol.placed_items
        ]
        if len(cand) != total_demand:
            raise BandQualityError(
                f'带内求解副本守恒失败: 放置 {len(cand)} != Σdemand {total_demand}')
        if _pairs_complete(cand, polys):
            placed = cand
            break
    if placed is None:
        placed = _slot_fallback(member_pids, pid_meta, polys)

    # ---- 3) 原始轮廓@带内位 → union → 焊接连通 → erode(d_g) → clean → 归一化
    footprints = []
    for m in placed:
        orig = pieces_by_id.get(m['pid'], {}).get('polygon')
        if not orig:
            orig = pid_meta[m['pid']]['polygon']   # 防御兜底：腐蚀后轮廓（包络安全方向）
        footprints.append(_valid_geometry(
            _transform_polygon(orig, m['rotation'], m['translation'])))
    union = unary_union(footprints)
    minx, miny, maxx, maxy = union.bounds
    offset = (float(minx), float(miny))
    bbox = {'width_mm': float(maxx - minx), 'height_mm': float(maxy - miny)}

    solid = _solid_region(union)
    outline = _exterior_coords(solid)
    if d_g > 0:
        outline = erode_polygon(outline, float(d_g))   # 失败自动回退原轮廓（超集安全方向）
    if len(outline) > MAX_COMPOSITE_VERTICES:
        outline = _exterior_coords(
            Polygon(outline).simplify(SIMPLIFY_TOLERANCE_MM, preserve_topology=True))
    comp = _clean_polygon(outline)
    if len(comp) < 3:
        raise DegenerateBand(
            f'band label {label!r} 组合片轮廓 erode({d_g}) 后顶点<3，带退化')
    comp = [[x - offset[0], y - offset[1]] for x, y in comp]   # 平移归一化（减 offset）

    # ---- 4) 带内填充率（实际占用 bbox 口径，非全幅）+ 质量下限 --------------
    area_sum = sum(float(pid_meta[m['pid']]['area_mm2']) for m in placed)
    bbox_area = bbox['width_mm'] * bbox['height_mm']
    fill_pct = (area_sum / bbox_area * 100.0) if bbox_area > 0 else 0.0
    if fill_pct < float(fill_floor):
        raise BandQualityError(
            f'带内填充率 {fill_pct:.1f}% < 下限 {fill_floor}%'
            f'（{label} 不适合成带或解散落）')

    # ---- 5) 成员输出定序（size-major + 几何键：同码相邻 + 确定性） ----------
    placed.sort(key=lambda m: (
        _member_sort_key(pid_meta[m['pid']], m['pid']),
        m['rotation'], m['translation'][0], m['translation'][1]))

    return BandChunk(
        pid=f'{COMPOSITE_PID_PREFIX}{label}',
        label=label,
        polygon=comp,
        offset=offset,
        members=placed,
        fill_pct=fill_pct,
        bbox=bbox,
        seed=band_seed,
        d_g=float(d_g),
        tol_g=float(tol_g),
    )

