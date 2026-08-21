"""腰头成带核心模块（US-009；v2 2026-08-21 构造性链构造重写；US-015 v1.1 混填料）
—— 链构造 + 填料填充 + 组合片构造 + 展开纯函数。

机制（依据 ``.docs/business/腰头成带_落地方案.md`` §2 + 版师形态指正 2026-08-21）：
腰头 g 码裁片按「每码第 k 副本」拆成 N 条**单副本异码链**（版师构造：链内片片
贴触、缝隙只在链间，**不需要同码成对**），构造性滑移贴靠贪心逐链紧排（确定性、
毫秒级、无预算依赖 —— 替换 v1 的 spyrrow strip 带内子求解：其目标是最短用布 X
而非贴触，产 48% 对角阶梯，且 US-014 成对重试在单副本配置空真失效）。链构造
「size 降序 + 整链点对称翻转」⇒ **开口（凹口）朝左、最大码在最右端**（v2 版师
形态判据；成员各自 rot+180 是合法布纹旋转、无镜像）→ 链间滑移堆叠 → 成员**原始
轮廓**@带内位 ``shapely.unary_union`` → 焊接连通 → ``erode(d_g)`` →
``_clean_polygon`` → 平移归一化（记录 offset），整簇 union 外轮廓作为一片虚拟
组合片（``WB_*`` pid）投入主求解；主解帧发射前用 ``expand_placements`` 把组合片
placement 展开回成员 placement。性质是**业务规则**（确定性聚排形态），不是利用率
优化器 —— 验收线 = 形态保证（链内贴触 + 开口/码序）+ 密度不显著劣化（实测紧带
进主解 +1.4pt vs OFF）。

US-015 v1.1 填料混带（唯一实测过 break-even 线的形态：混带 72.5% > 线
62.4~63.6%，纯腰 54.8~60.9% 不过线 —— US-010 闸门口径）：``fillers`` 指认的
任意 g 码（版师确认无白名单约束）全部副本在**腰链堆叠完成后**经 ``_fill_gaps``
贪心塞进带内空隙（v1「封闭肋间内腔死区」的填料回收；v2 链构造下即凹口/链间
空隙），并进 union/展开/守恒/泄漏全口径；带内成员碰撞口径的 d 抬到
``BAND_INNER_D_MM``（2~4mm 取保守端 2.0）—— 肋间切口端部被开到小件可入宽度
（主解 NFP 邻接可深入），原始轮廓间隙 ≥2×2.0mm。

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

from shapely.affinity import rotate, translate
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

from ..nesting_bounds.load_pieces import NEST_GATE_MM, PLOT_SAFE_MAX_Y_MM
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
# 【v1 遗产·deprecated】带内子求解预算：v2 构造性链构造毫秒级完成、无预算依赖。
# 常量与 ``build_band_plan(time_budget=...)`` 形参保留仅为 ``solve_worker`` /
# ``routes_band`` / ``band_accept`` / ``waist_band_gate`` 的 import 兼容（接受即忽略）。
DEFAULT_BAND_TIME_BUDGET_S = 15
# 带内填充率下限（%）：v2 起降为**灾难形态兜底**（裤耳 g06 类 13% 在此拦截）——
# 主判据是链内贴触 ``CHAIN_GAP_EPS_MM``（新月片 bbox 空隙是构造性的，版师接受，
# 弧形腰片实测 fill 63~80% 均合法）。禁止无声 shelf 兜底 —— 异常 fail-fast 抛
# BandQualityError。
FILL_FLOOR_PCT = 45.0
# 焊接初始半径（mm）：v2 成员碰撞口径是**已腐蚀**轮廓（pid_meta.polygon，erode
# d_g），贴触即原轮廓间隙 ~2·d_g；closing(X, r) = X⊕r⊖r（恒 ⊇ X）把 ≤2r 的缝焊成
# 整带单组合片，缝隙更大时半径逐次翻倍直至连通（见 ``_solid_region``）。正常紧排
# 缝隙远小于 2×WELD_RADIUS_MM，r 不增长、外轮廓凹口（FR-9 密度回收来源）保持开放。
WELD_RADIUS_MM = 1.0
# 焊接半径上限（mm）：超过仍不连通 = 解真正散落（贴触判据理应已拦截），fail-fast。
WELD_RADIUS_MAX_MM = 512.0
# 【v1 遗产·deprecated】同码成对相邻判据的边距容差（mm）：v2 链构造不需要成对
# （版师形态 = 单副本异码链）；常量保留仅为 ``web.band_accept``（US-014 验收
# 口径）import 兼容。
PAIR_ADJ_EPS_MM = 10.0
# ---- v2 构造性链构造参数（exp_band_fill.py / exp_rightband.py 探针标定） ----
# 链内贴触判据（mm）：每片到最近邻**边距**的最大值上限（碰撞口径 = 已腐蚀轮廓，
# 实测 0.00；新月片 bbox fill 不是版师验收口径）。
CHAIN_GAP_EPS_MM = 1.0
# 滑移粗扫步进（mm）：可行域非凸，从右侧远处向左粗扫找首个碰撞界后二分收敛。
CHAIN_SLIDE_STEP_MM = 20.0
# 滑移二分次数（40 次 ⇒ 收敛精度 ~2^-40×扫描区间，远小于 0.01mm）。
CHAIN_BISECT_ITERS = 40
# 链构造/堆叠的 y 对齐候选（链: 片对已排 union；堆叠: 链对已堆叠 union）。
CHAIN_Y_ALIGNS = ('bottom', 'mid', 'top', 'b2t', 't2b')
# US-015 填料滑移二分次数（24 次 ⇒ 收敛精度 2^-24×2000 ≈ 0.0001mm，远小于 0.01mm
# 贴触判据；填料候选量大（成员边 y 候选 × 双向），比链构造的 40 次省 40% 用时，
# 实测 5336 g05+g07+g08 28 副本 ~5s）。
FILLER_BISECT_ITERS = 24
# US-015 混带带内碰撞 d 下限（mm）：填料开启时全部带成员（腰+填料）的带内碰撞轮廓
# 在该 label 既有腐蚀（per_type d）之上补腐蚀到此深度 —— 贴触 ⇒ 原始轮廓间隙
# ≥2×本值，肋间切口端部开到小件可入宽度（PRD「band 内 d 适度放大 2~4mm」取保守
# 端；纯腰路径不受影响 = v2 行为零回归）。组合片外轮廓 erode 深度仍为 d_g（包络
# 断言口径不变）。
BAND_INNER_D_MM = 2.0


class BandError(Exception):
    """成带失败基类（web 层按需捕获转结构化 error）。"""


class DegenerateBand(BandError):
    """带退化：总副本 1（单片无成带意义）或成员/组合片轮廓腐蚀后不足 3 顶点。"""


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
    fill_pct: float               # 带内填充率（成员原面积和 / union bbox 面积 ×100；US-015 起含填料面积）
    bbox: dict                    # {'width_mm','height_mm'} union bbox（实际占用，非全幅）
    seed: int                     # 带内子求解实际使用的 seed（crc32 派生，回放对拍用）
    d_g: float                    # 该 g 码重合公差（组合片 erode 深度）
    tol_g: float                  # 该 g 码旋转公差（成员带内离散角）
    fillers: tuple = ()           # US-015 混带填料 g 码（记录/工件回放；空 = 纯腰 v2）
    n_members: int = field(init=False)

    def __post_init__(self):
        self.n_members = len(self.members)

    @property
    def total_demand(self) -> int:
        """成员副本总数（= Σ pid_meta demand，守恒断言口径；US-015 起含填料副本）。"""
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
            'fillers': [str(f) for f in self.fillers],
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

    v2 链构造成员碰撞口径是已腐蚀轮廓，贴触即原轮廓间隙 ~2·d_g（v1 为 spyrrow
    解 0.01~10mm 缝），``unary_union`` 可得 MultiPolygon；「整带单组合片」要求
    连通区域，故用 closing(X, r) = X ⊕r ⊖r 焊接：数学上恒为原集合的超集（包络
    断言不受影响），r 从 ``WELD_RADIUS_MM`` 起翻倍直到结果连通。半径增大只填充
    更宽的凹口/缝隙（真正散落已被链贴触判据在构造期拦截）；到上限仍不连通视为
    病态。
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


def _geom_at(poly, rot, tr):
    """轮廓@放置位（`_transform_polygon` + `_valid_geometry` 修复）。"""
    return _valid_geometry(_transform_polygon(poly, rot, tr))


def _y_align_off(y_align, pb, gb) -> float:
    """CHAIN_Y_ALIGNS 名 → moving(gb) 相对 fixed(pb) 的 y 平移量（对齐语义单一真相源，
    ``_chain_nest`` / ``_stack_chains`` / ``_fill_gaps`` 三处共用）。"""
    if y_align == 'bottom':
        return pb[1] - gb[1]
    if y_align == 'top':
        return pb[3] - gb[3]
    if y_align == 'b2t':
        return pb[3] - gb[1]
    if y_align == 't2b':
        return pb[1] - gb[3]
    return (pb[1] + pb[3]) / 2 - (gb[1] + gb[3]) / 2      # 'mid'


def _slide_touch(g_moving, g_fixed, y_offset, from_left=False,
                 bisect_iters=CHAIN_BISECT_ITERS, prep_fixed=None):
    """从远端滑到与 g_fixed 首次贴触：粗扫定界 + 二分收敛（默认右侧起步向左）。

    可行域（不碰撞的 x 区间）非凸 —— 必须从行进方向远端起步找**首个**碰撞界，
    再在 (碰撞, 不碰撞) 区间二分到贴触点；双向起步二分会卡进远端凹口。
    ``from_left=True``（US-015 填料专用）从左侧远处向右滑 —— 带开口朝左，左起
    滑移可深入凹口填进空隙（右起滑移会被凸侧先拦住）。
    y_offset = 施加于 g_moving 的 y 平移量。返回 ``(放置几何, dx)``，其中 dx 为
    施加的 x 平移量（``translate(g_moving, dx, y_offset) == 放置几何``）—— 调用方
    按 transform 记账语义直接入 placement，勿再拿「左边缘坐标」当平移量。

    ``bisect_iters`` / ``prep_fixed``（US-015 填料热路径旋钮）：填料候选量大，可
    降二分精度（``FILLER_BISECT_ITERS``）并传入复用的 prepared 几何（bbox 级快速
    预筛）提速；缺省即 v2 链构造口径，行为逐字节不变。
    """
    mb = g_moving.bounds
    fb = g_fixed.bounds
    w = mb[2] - mb[0]
    if from_left:
        x_start = fb[0] - w - 50.0          # 左侧远处起步
        x_end = fb[2] + w + 5.0
        step = CHAIN_SLIDE_STEP_MM
    else:
        x_start = fb[2] + w + 50.0          # 右侧远处起步（v2 链构造默认方向）
        x_end = fb[0] - w - 5.0
        step = -CHAIN_SLIDE_STEP_MM

    def place(x_left):
        return translate(g_moving, xoff=x_left - mb[0], yoff=y_offset)

    def collides(x_left):
        p = place(x_left)
        if prep_fixed is not None and not prep_fixed.intersects(p):
            return False                    # bbox 级预筛（prepared，语义同面积测试）
        return p.intersection(g_fixed).area >= 1e-6

    if collides(x_start):
        return place(x_start), x_start - mb[0]   # 起点就碰（y 对齐重叠）：直接放
    hit = None
    x = x_start
    while (step > 0 and x < x_end) or (step < 0 and x > x_end):
        xn = min(x + step, x_end) if step > 0 else max(x + step, x_end)
        if collides(xn):
            hit = (xn, x)                   # (碰撞, 不碰撞)
            break
        x = xn
    if hit is None:
        return place(x_end), x_end - mb[0]
    a, b = hit
    for _i in range(int(bisect_iters)):
        mid = (a + b) / 2.0
        if collides(mid):
            a = mid
        else:
            b = mid
    return place(b), b - mb[0]              # b = 行进方向首个贴触位（不碰撞侧）


def _bbox_area(pb, gb) -> float:
    """两 bbox 合并面积 —— ``bbox(A∪B) = merge(bbox A, bbox B)``（解析式，与
    ``unary_union([A,B]).bounds`` 逐值相等；贪心 cost 热路径免做 union）。"""
    return (max(pb[2], gb[2]) - min(pb[0], gb[0])) * (max(pb[3], gb[3]) - min(pb[1], gb[1]))


def _chain_nest(member_pids, polys):
    """构造性滑移贴靠贪心：首片锚定原点，后续每片 rot{0,180} × 5 种 y 对齐
    滑移贴触到已排 union，取 union bbox 面积增长最小（确定性、无 RNG）。

    ``member_pids`` 顺序即放置顺序（调用方给 size **降序** —— 与「升序+右滑 =
    开口朝右」相对，降序构造经 ``_flip_chain`` 后得开口朝左+最大码在右）。
    碰撞口径 = ``polys``（pid_meta 已腐蚀轮廓，与 v1 spyrrow Item 同口径）。
    """
    packed = None
    placed = []
    for pid in member_pids:
        candidates = []
        for r in (0.0, 180.0):
            g0 = rotate(_valid_geometry(polys[pid]), r, origin=(0, 0))
            gb = g0.bounds
            if packed is None:
                g = translate(g0, xoff=-gb[0], yoff=-gb[1])
                candidates.append((g, {'pid': pid, 'rotation': r,
                                       'translation': [-gb[0], -gb[1]]}))
                continue
            pb = packed.bounds
            for y_align in CHAIN_Y_ALIGNS:
                yo = _y_align_off(y_align, pb, gb)
                g, dx = _slide_touch(g0, packed, yo)
                candidates.append((g, {'pid': pid, 'rotation': r,
                                       'translation': [dx, yo]}))
        best = None
        for g, meta in candidates:
            b = g.bounds
            cost = (b[2] - b[0]) * (b[3] - b[1]) if packed is None \
                else _bbox_area(packed.bounds, b)
            if best is None or cost < best[0]:
                best = (cost, g, meta)
        _, g, meta = best
        packed = g if packed is None else unary_union([packed, g])
        placed.append(meta)
    return placed


def _flip_chain(placed):
    """整链点对称翻转（绕原点 180°）：成员各自 (rot+180, tr 取负)。

    合法布纹旋转、无镜像；同时翻转开口方向与 X 向码序 —— 「降序构造 + 本翻转」
    ⇒ 开口朝左、最大码在最右（v2 版师形态判据的几何根基）。
    """
    return [{'pid': m['pid'],
             'rotation': (float(m['rotation']) + 180.0) % 360.0,
             'translation': [-float(m['translation'][0]),
                             -float(m['translation'][1])]}
            for m in placed]


def _norm_chain(placed, polys):
    """归一到 union bbox 原点（返回平移后的新成员 list）。"""
    u = unary_union([_geom_at(polys[m['pid']], m['rotation'], m['translation'])
                     for m in placed])
    minx, miny = u.bounds[0], u.bounds[1]
    return [{'pid': m['pid'], 'rotation': m['rotation'],
             'translation': [m['translation'][0] - minx,
                             m['translation'][1] - miny]}
            for m in placed]


def _stack_chains(chains, polys):
    """多链堆叠为单成员集：逐链 5 种 y 对齐滑移贴靠到已堆叠 union，取 union
    bbox 面积增长最小。**不做翻链变体**（翻转会反转开口方向，违反 v2 形态判据）。"""
    placed = list(chains[0])
    packed = unary_union([_geom_at(polys[m['pid']], m['rotation'],
                                   m['translation']) for m in placed])
    for ch in chains[1:]:
        ch_u = unary_union([_geom_at(polys[m['pid']], m['rotation'],
                                     m['translation']) for m in ch])
        pb, gb = packed.bounds, ch_u.bounds
        best = None
        for y_align in CHAIN_Y_ALIGNS:
            yo = _y_align_off(y_align, pb, gb)
            _, dx = _slide_touch(ch_u, packed, yo)
            cand = [dict(m, translation=[m['translation'][0] + dx,
                                         m['translation'][1] + yo]) for m in ch]
            b = ch_u.bounds
            b = (b[0] + dx, b[1] + yo, b[2] + dx, b[3] + yo)
            cost = _bbox_area(pb, b)        # 解析合并（与 union 后 bounds 逐值相等）
            if best is None or cost < best[0]:
                best = (cost, cand)
        _, cand = best
        cand_geoms = [_geom_at(polys[c['pid']], c['rotation'], c['translation'])
                      for c in cand]
        packed = unary_union([packed, *cand_geoms])
        placed = placed + cand
    return placed


def _fill_gaps(filler_units, polys, placed):
    """US-015 填料贪心填充：腰链堆叠完成后，把填料副本逐个塞进带内空隙。

    每副本候选 = rot{0,180} × **成员边 y 候选**（已排 union bbox 上下边 + 每片
    bbox 上下边，各对齐填料底/顶 —— 凹口/链间空隙都贴着某条成员边，5 个全局
    y 对齐实测够不着：填料只会堆在带端部把 bbox 撑大、fill 反降）× **双向**
    （右起 + 左起）滑移贴触 —— 带开口朝左，左起滑移才能深入凹口（v1「封闭
    肋间内腔」死区在 v2 链构造下即凹口/链间空隙，填料在此回收）；取 union
    bbox 面积增长最小（解析合并 ``_bbox_area``，与 ``_chain_nest``/``_stack_chains``
    同一确定性贪心口径，无 RNG；实测 5336 g05 P0 + g07 fill 79.5%→86.5% 且
    bbox 收窄）。

    ``filler_units`` = 逐副本展开的 pid 序列（调用方按 (g 码, size, pid) 定序保证
    确定性）；碰撞口径 = ``polys``（混带下已含 ``BAND_INNER_D_MM`` 补腐蚀）。
    返回填料带内位 list（与 ``placed`` 同 shape，调用方拼接）。
    """
    geoms = [_geom_at(polys[m['pid']], m['rotation'], m['translation'])
             for m in placed]
    packed = unary_union(geoms)
    out = []
    for pid in filler_units:
        pb = packed.bounds
        candidates = []
        for r in (0.0, 180.0):
            g0 = rotate(_valid_geometry(polys[pid]), r, origin=(0, 0))
            gb = g0.bounds
            ys: set = set()
            for edge in (pb[1], pb[3]):
                ys.add(round(edge - gb[1], 3))     # 填料底对齐边
                ys.add(round(edge - gb[3], 3))     # 填料顶对齐边
            for g in geoms:
                mb2 = g.bounds
                for edge in (mb2[1], mb2[3]):
                    ys.add(round(edge - gb[1], 3))
                    ys.add(round(edge - gb[3], 3))
            prepped = prep(packed)                 # 候选共享 prepared 快速预筛
            for yo in sorted(ys):
                for from_left in (False, True):
                    g, dx = _slide_touch(
                        g0, packed, yo, from_left=from_left,
                        bisect_iters=FILLER_BISECT_ITERS, prep_fixed=prepped)
                    candidates.append((g, {'pid': pid, 'rotation': r,
                                           'translation': [dx, yo]}))
        best = None
        for g, meta in candidates:
            cost = _bbox_area(pb, g.bounds)
            if best is None or cost < best[0]:
                best = (cost, g, meta)
        _, g, meta = best
        packed = unary_union([packed, g])
        geoms.append(g)
        out.append(meta)
    return out


def _chain_gap(placed, polys):
    """链内最大相邻缝隙（mm）：每片到最近其他片**边距**的最大值（0 = 片片贴触）。

    版师验收口径 —— 贴触而非 bbox fill（新月片 bbox 空隙是构造性的、可接受）。
    """
    gs = [_geom_at(polys[m['pid']], m['rotation'], m['translation'])
          for m in placed]
    if len(gs) < 2:
        return 0.0
    return max(min(gs[j].distance(g) for j in range(len(gs)) if j != i)
               for i, g in enumerate(gs))


def _opening_side(placed, polys, flat_eps=1.0):
    """链开口（凹口）方向：凸侧拉质心 ⇒ 开口 = 质心相对 bbox 中心 X 偏移的反侧。

    已在 v1 真实链校准（判 right = 版师目测 right）；|偏移| < flat_eps 视为
    'flat'（矩形/对称片无开口概念，判据空真）。返回 'left' / 'right' / 'flat'。
    """
    u = unary_union([_geom_at(polys[m['pid']], m['rotation'], m['translation'])
                     for m in placed])
    minx, _, maxx, _ = u.bounds
    off = u.centroid.x - (minx + maxx) / 2
    if abs(off) < flat_eps:
        return 'flat'
    return 'left' if off > 0 else 'right'


def build_band_plan(pid_meta, pieces_by_id, *, label, seed,
                    gate_nest=NEST_GATE_MM, d_g=0.4, tol_g=3.0,
                    fillers=(), filler_ds=None,
                    time_budget=DEFAULT_BAND_TIME_BUDGET_S,
                    fill_floor=FILL_FLOOR_PCT) -> BandChunk:
    """构造性链构造 → 填料填充 → 组合片构造（单一真相源；web 编排在 US-011 接线）。

    版师形态（v2，2026-08-21）：每码第 k 副本一条链 → 降序构造+整链翻转（开口
    朝左、最大码在最右）→ 链间滑移堆叠 → US-015 填料 ``_fill_gaps`` 贪心塞隙 →
    union/erode/归一化（v1 管线不变）。

    Parameters
    ----------
    pid_meta : dict
        ``web.solver.build_pid_meta`` 产物 ``{pid: {label, size, demand, polygon,
        area_mm2, ...}}``。链构造碰撞用其**已腐蚀** polygon（不二次腐蚀）；
        demand>0 过滤已由 build_pid_meta 完成（此处再校验兜底）。
    pieces_by_id : dict
        intermediate 原始裁片 ``{pid: {'polygon': 原始轮廓, ...}}`` —— union 与
        包络断言用**原始**轮廓（erode 只进碰撞口径，不缩面积/不缩带）。
    label : str
        腰头 g 码（如 'g05'；跨母版漂移由用户在 UI 指认）。
    seed : int
        主解 seed；``BandChunk.seed`` = ``band_seed_for(seed, label)``（crc32 派生
        确定性身份标识 —— 链构造无 RNG，同输入即逐字节可重放）。
    gate_nest : float
        组合片高度上限基准（钳 ``min(gate_nest, PLOT_SAFE_MAX_Y_MM)``：组合片须进
        主解条带，超幅主解放不下；链构造无 strip 约束，事后显式校验）。
    d_g : float
        该 g 码重合公差（应与构造 pid_meta 时该 label 的 per_type d 同值；组合片
        union 后 erode 深度 —— 使主解其他裁片对带边界保持与单片相同的 d_g 邻接语义）。
    tol_g : float
        该 g 码旋转公差（记录进 chunk；链构造成员朝向恒取 grain 锁 {0,180}，严于
        ``discretize_orientations(tol_g)`` —— FR-8 同口径：工艺公差属裁片不属于带）。
    fillers : sequence[str]
        US-015 混带填料 g 码（版师确认无白名单约束；数量上限/存在性/与主 g 码
        不同由 ``routes_ws._parse_band`` 服务端校验，此处兜底 0 副本 ValueError）。
        填料全部副本在腰链堆叠后经 ``_fill_gaps`` 塞进带内空隙并进 union/展开/
        守恒口径；空 = 纯腰 v2 路径（碰撞 d 不放大，行为逐字节不变）。
    filler_ds : dict | None
        填料各 label 的重合公差 ``{label: d}``（``_resolve_d_tol`` 逐 label 裁定，
        由调用方传入；缺省视为 0）—— 混带补腐蚀深度的计算基准（见
        ``BAND_INNER_D_MM``）。
    time_budget : int
        【deprecated no-op】v1 带内子求解预算；构造性链构造毫秒级完成、无预算
        依赖。形参保留仅为调用方（solve_worker/routes_band/band_accept/gate）兼容。
    fill_floor : float
        带内填充率下限（%），低于即 BandQualityError（灾难形态兜底；主判据是
        链内贴触 ``CHAIN_GAP_EPS_MM``）。US-015 起分子 = 腰 + 填料面积和。

    Returns
    -------
    BandChunk
    """
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
            f'band label {label!r} 总副本 1 —— 单片无成带意义，直接走主解')

    # US-015 填料成员收集（同一 demand>0 口径；0 副本/与主码同值 fail-fast）。
    fillers = [str(f) for f in (fillers or []) if str(f)]
    if label in fillers:
        raise ValueError(f'band 填料不可与主 g 码相同（{label!r}）')
    filler_ds = dict(filler_ds or {})
    filler_members: list = []               # [(label, pid)]，定序保证确定性
    for f in fillers:
        f_pids = sorted(
            (pid for pid, m in pid_meta.items()
             if m.get('label') == f and int(m.get('demand', 0)) > 0),
            key=lambda pid: _member_sort_key(pid_meta[pid], pid))
        if not f_pids:
            raise ValueError(f'band 填料 {f!r} 无 demand>0 裁片（0 副本，不可混带）')
        filler_members.extend((f, pid) for pid in f_pids)
    total_filler = sum(int(pid_meta[pid]['demand']) for _f, pid in filler_members)

    # ---- 2) 构造性链构造（v2 版师形态） -------------------------------------
    # 版师构造（2026-08-21 指正）：每码第 k 副本一条链 —— 链内片片贴触、缝隙只在
    # 链间，不需要同码成对。v1 spyrrow strip 带内子求解目标是最短用布 X 而非贴触
    # （产 48% 对角阶梯、预算 ×30 仅 +4.1pt 结构性卡死；US-014 成对重试在单副本
    # 配置空真失效），整体弃用。碰撞口径 = 已腐蚀轮廓（与 v1 Item 同口径）；US-015
    # 混带时在该口径上补腐蚀到 BAND_INNER_D_MM（肋间切口端部开到小件可入宽度）。
    band_seed = band_seed_for(seed, label)
    inner_floor = BAND_INNER_D_MM if fillers else 0.0

    def _member_poly(pid, lbl):
        poly = _clean_polygon(pid_meta[pid]['polygon'])
        if len(poly) < 3:
            raise DegenerateBand(f'成员 {pid} 腐蚀/清洗后顶点<3，不可成带')
        base_d = float(d_g) if lbl == label else float(filler_ds.get(lbl, 0.0))
        extra = max(inner_floor - base_d, 0.0)
        if extra > 0:
            deeper = erode_polygon(poly, extra)   # 失败自动回退原轮廓（碰撞超集安全方向）
            if len(deeper) >= 3:
                poly = _clean_polygon(deeper)
        return poly

    polys: dict = {pid: _member_poly(pid, label) for pid in member_pids}
    for f, pid in filler_members:
        polys[pid] = _member_poly(pid, f)
    max_demand = max(int(pid_meta[pid]['demand']) for pid in member_pids)
    chains = []
    for k in range(max_demand):
        chain_pids = sorted(
            (pid for pid in member_pids if int(pid_meta[pid]['demand']) > k),
            key=lambda pid: _member_sort_key(pid_meta[pid], pid),
            reverse=True)                   # size 降序（版师链序；首锚片=最大码）
        chain = _norm_chain(_flip_chain(_chain_nest(chain_pids, polys)), polys)
        gap = _chain_gap(chain, polys)
        if gap > CHAIN_GAP_EPS_MM:
            raise BandQualityError(
                f'链 {label!r} 第 {k} 链贴触失败（最大缝隙 {gap:.2f}mm > '
                f'{CHAIN_GAP_EPS_MM}mm）—— 形态质量悬崖，禁无声降级')
        if _opening_side(chain, polys) == 'right':
            raise BandQualityError(
                f'链 {label!r} 第 {k} 链开口朝右（降序+翻转构造异常）')
        # 最大码在最右（降序+翻转构造保证；程序断言自校验 —— 首锚片翻转后落
        # 最右端，右端成员应即 chain_pids[0]）
        cx = {m['pid']: _geom_at(polys[m['pid']], m['rotation'],
                                 m['translation']).centroid.x for m in chain}
        if max(cx, key=cx.get) != chain_pids[0]:
            raise BandQualityError(
                f'链 {label!r} 第 {k} 链最右成员非最大码（降序+翻转构造异常）')
        chains.append(chain)
    placed = chains[0] if len(chains) == 1 else _stack_chains(chains, polys)
    if len(placed) != total_demand:
        raise BandQualityError(
            f'链构造副本守恒失败: 放置 {len(placed)} != Σdemand {total_demand}')

    # US-015 填料填充：腰链形态定形后塞隙（填料不进链 —— 链是腰头版师构造；
    # 填料贴触口径同 polys，逐副本展开保序确定性）。
    filler_units: list = []
    for _f, pid in filler_members:
        filler_units.extend([pid] * int(pid_meta[pid]['demand']))
    if filler_units:
        placed = placed + _fill_gaps(filler_units, polys, placed)
        if len(placed) != total_demand + total_filler:
            raise BandQualityError(
                f'混带副本守恒失败: 放置 {len(placed)} != '
                f'Σdemand {total_demand + total_filler}（腰 {total_demand} + '
                f'填料 {total_filler}）')

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
    strip_h = float(min(gate_nest, PLOT_SAFE_MAX_Y_MM))
    if bbox['height_mm'] > strip_h + 1e-6:
        raise BandQualityError(
            f'带高 {bbox["height_mm"]:.0f}mm > 主解条带 {strip_h:.0f}mm'
            f'（{label} 链堆叠超高，组合片主解放不下）')

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
    # US-015 起分子 = 腰 + 填料面积和（A/B「带区域效率 = 带板 bbox 内腰+填料面积/
    # 占用」的同一口径）。
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
        fillers=tuple(fillers),
    )

