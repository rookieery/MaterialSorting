"""腰头成带核心模块（US-009；v2 2026-08-21 构造性链构造重写）
—— 链构造 + 组合片构造 + 展开纯函数。

机制（依据 ``.docs/business/腰头成带_落地方案.md`` §2 + 版师形态指正 2026-08-21）：
腰头 g 码裁片按「每码第 k 副本」拆成 N 条**单副本异码链**（版师构造：链内片片
贴触、缝隙只在链间，**不需要同码成对**），构造性滑移贴靠贪心逐链紧排（确定性、
毫秒级、无预算依赖 —— 替换 v1 的 spyrrow strip 带内子求解：其目标是最短用布 X
而非贴触，产 48% 对角阶梯，且 US-014 成对重试在单副本配置空真失效）。链构造
按弧片**手性自适应**（2026-08-27，M1787 g10）：凸左弧片（5336 g05 族）「size
降序 + 整链点对称翻转」、镜像凸右弧片（M1787 g10 族，与 g05 互为镜像）「升序 +
不翻转」⇒ 终态同为 **开口（凹口）朝左、最大码在最右端**（v2 版师形态判据；翻
转支成员各自 rot+180 是合法布纹旋转、无镜像）→ 链间滑移堆叠 → 成员**原始
轮廓**@带内位 ``shapely.unary_union`` → 焊接连通 → ``erode(d_g)`` →
``_clean_polygon`` → 平移归一化（记录 offset），整簇 union 外轮廓作为一片虚拟
组合片（``WB_*`` pid）投入主求解；主解帧发射前用 ``expand_placements`` 把组合片
placement 展开回成员 placement。性质是**业务规则**（确定性聚排形态），不是利用率
优化器 —— 验收线 = 形态保证（链内贴触 + 开口/码序）+ 密度不显著劣化（实测紧带
进主解 +2.27pt vs OFF）。

直腰头分叉（2026-08-24 版师指正，882# g01）：成员均为**平板直条**（质心短轴
偏移 < ``FLAT_CENTROID_EPS_MM``）时，贪心的 side-by-side 候选 bbox 面积在端部
形状互补/浮点噪声级打平（实测六候选互差 <1e-6mm²），严格小于的贪心被逐片翻盘
⇒ 交替翻转+上下换锚的对角阶梯乱象（用户图1）。直腰头版师形态（图2）= **同底
齐平、片片同向、无翻转、大码在右** —— 升序构造 + 单候选 (rot0, 'bottom')，
面积与乱象形态等价（差 <0.1%，纯形态规则）；弧形片（质心偏移 ~18-22mm，判据
分离度 18×）仍走嵌套贪心，行为不变。多副本（2026-08-24 版师二次指正）不再按
「每码第 k 副本」拆 N 链并排 —— 链交界会形成「最大码|最小码」的整带高差深谷
（交叉布局）；**全副本展开为单条全局从短到长**的单调阶梯（同码副本相邻），
等宽条带并排 bbox 与顺序无关，面积零代价。

横向弯腰头分叉（v3 2026-08-28，3069 g11）：成员为**长轴横置的扁弧片**（⌣ 形、
布纹沿弧长 0°、开口朝上/下，实测 1057×161）时，既有 X 向滑移构造失效（片被迫
端对端串成 ~11m 双行错切带、fill 44% 撞下限被拒）—— 版师形态（用户参考图）=
**同向弧片逐层竖排（居中对齐、层距=条厚）、多副本链间互扣**。实现 = 构造帧整体
**T-转置**（反射 (x,y)→(y,x)）后复用既有贪心/堆叠机器：T·R(r)·T = R(−r) 共轭
保 proxy 旋转 {0} ⇔ 实空间 {0,180} 布纹合法（90° 旋转做 proxy 已实测否决：映射
回 ±90° 非法 / 片横躺被迫端对端）。单一朝向构造（母版原向即版师形态，⌣/⌢ 皆
合法、无手性分支），闸门 = 贴触 + 大码在底 + 旋转合法。实测 3069 g11：10 码
demand1 = 1270×792mm / fill 77.3% / 贴触 0.00mm；demand2 两链互扣 fill 80.2%。

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

from ..nesting_bounds.load_pieces import GATE_MM
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
# 直腰头（平板直条）判据阈值（mm）：单片质心沿**短轴**相对 bbox 中心的偏移
# |off| < 阈值 ⇒ 直条（长边平直、质心居中，实测 882# g01 全员 0.00mm）；弧形
# （新月）腰片质心被凸侧拉偏（实测 5336 g05 -18~-22mm）—— 分离度 18×，阈值
# 沿用 ``_opening_side`` flat_eps=1.0 口径。沿短轴取偏移：弯曲发生在长轴法向，
# 端部形状不对称只影响长轴向质心、不干扰本判据。
FLAT_CENTROID_EPS_MM = 1.0


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
        """JSON 可序列化 dict（确定性对拍用；纯几何不含 wall-clock —— 同 seed
        两跑 ``json.dumps`` 相等）。"""
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


def _slide_touch(g_moving, g_fixed, y_offset):
    """从右侧远端滑到与 g_fixed 首次贴触：粗扫定界 + 二分收敛。

    可行域（不碰撞的 x 区间）非凸 —— 必须从行进方向远端起步找**首个**碰撞界，
    再在 (碰撞, 不碰撞) 区间二分到贴触点；双向起步二分会卡进远端凹口。
    y_offset = 施加于 g_moving 的 y 平移量。返回 ``(放置几何, dx)``，其中 dx 为
    施加的 x 平移量（``translate(g_moving, dx, y_offset) == 放置几何``）—— 调用方
    按 transform 记账语义直接入 placement，勿再拿「左边缘坐标」当平移量。
    """
    mb = g_moving.bounds
    fb = g_fixed.bounds
    w = mb[2] - mb[0]
    x_start = fb[2] + w + 50.0              # 右侧远处起步（v2 链构造默认方向）
    x_end = fb[0] - w - 5.0
    step = -CHAIN_SLIDE_STEP_MM

    def place(x_left):
        return translate(g_moving, xoff=x_left - mb[0], yoff=y_offset)

    def collides(x_left):
        return place(x_left).intersection(g_fixed).area >= 1e-6

    if collides(x_start):
        return place(x_start), x_start - mb[0]   # 起点就碰（y 对齐重叠）：直接放
    hit = None
    x = x_start
    while x > x_end:
        xn = max(x + step, x_end)
        if collides(xn):
            hit = (xn, x)                   # (碰撞, 不碰撞)
            break
        x = xn
    if hit is None:
        return place(x_end), x_end - mb[0]
    a, b = hit
    for _i in range(CHAIN_BISECT_ITERS):
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


def _is_flat_piece(g, eps=FLAT_CENTROID_EPS_MM) -> bool:
    """单片是否「平板直条」：质心沿**短轴**相对 bbox 中心的偏移 < eps。

    直腰头长边平直、质心居中（882# g01 实测全员 0.00mm）；弧形（新月）腰片
    质心被凸侧拉偏（5336 g05 实测 -18~-22mm）—— 判据只看长轴法向（短轴）偏移，
    端部形状不对称（长轴向质心偏移，882# 实测 -2.31mm）不干扰。
    """
    minx, miny, maxx, maxy = g.bounds
    if (maxy - miny) >= (maxx - minx):          # 长轴纵向 → 弯曲看横向偏移
        return abs(g.centroid.x - (minx + maxx) / 2) < eps
    return abs(g.centroid.y - (miny + maxy) / 2) < eps


def _long_axis_x(g) -> bool:
    """单片长轴是否横置（bbox 宽 > 高）—— 横向弯腰头（3069 g11 族）判据。

    「非 flat 弧片 + 长轴横置」⇒ 弧面沿 Y 起伏、开口朝上/下 —— 版师形态为逐层
    竖排（v3 分支）；长轴纵置（5336 g05 / M1787 g10 族）走既有望远镜嵌套不变。
    腰片长宽比悬殊（1057 vs 161），判据无歧义边界。
    """
    minx, miny, maxx, maxy = g.bounds
    return (maxx - minx) > (maxy - miny)


def _transpose_placements(placed):
    """proxy 帧放置 → 实空间放置（转置反射 T:(x,y)→(y,x) 的共轭映射）。

    proxy 放置几何 = R(r)·Tp + t（p=实空间片），T·R(r)·T = R(−r)（反射共轭
    反转角度）⇒ 实空间等价放置 = R(−r)·p + Tt：**rot 取负、平移交换分量**。
    proxy rots {0,180} ⇔ 实空间 {0,180}（布纹合法）；90° 旋转做 proxy 无此
    性质（映射回 ±90° 非法）—— 勿把 T 换成 R(±90)。
    """
    return [{'pid': m['pid'],
             'rotation': (-float(m['rotation'])) % 360.0,
             'translation': [float(m['translation'][1]),
                             float(m['translation'][0])]}
            for m in placed]


def _chain_nest(member_pids, polys, rots=(0.0, 180.0),
                y_aligns=CHAIN_Y_ALIGNS):
    """构造性滑移贴靠贪心：首片锚定原点，后续每片 ``rots`` × ``y_aligns``
    滑移贴触到已排 union，取 union bbox 面积增长最小（确定性、无 RNG）。

    ``member_pids`` 顺序即放置顺序（弧形凸左：调用方给 size **降序** —— 与
    「升序+右滑 = 开口朝右」相对，降序构造经 ``_flip_chain`` 后得开口朝左+
    最大码在右；弧形凸右（镜像，M1787 g10）：**升序** + 不翻转即开口朝左+
    最大码在右；直腰头：**升序** + ``rots=(0.0,)`` + ``y_aligns=('bottom',)``
    单候选 —— 近矩形条带的多候选面积噪声级打平会让贪心交替翻盘产对角阶梯，
    版师形态（图2）要求同底齐平、片片同向、无翻转；多副本时**含重复 pid**
    （全副本展开单链，全局从短到长））。
    碰撞口径 = ``polys``（pid_meta 已腐蚀轮廓，与 v1 spyrrow Item 同口径）。
    """
    packed = None
    placed = []
    for pid in member_pids:
        candidates = []
        for r in rots:
            g0 = rotate(_valid_geometry(polys[pid]), r, origin=(0, 0))
            gb = g0.bounds
            if packed is None:
                g = translate(g0, xoff=-gb[0], yoff=-gb[1])
                candidates.append((g, {'pid': pid, 'rotation': r,
                                       'translation': [-gb[0], -gb[1]]}))
                continue
            pb = packed.bounds
            for y_align in y_aligns:
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

    合法布纹旋转、无镜像；同时翻转开口方向与 X 向码序 —— 凸左弧片的「降序构造 +
    本翻转」⇒ 开口朝左、最大码在最右（v2 版师形态判据的几何根基）。镜像凸右弧片
    （M1787 g10 族）不经本函数 —— 升序构造+不翻转即达同终态（翻转反而开口朝右
    被闸门拒，见 ``build_band_plan`` 手性自适应）。
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


def _stack_chains(chains, polys, y_aligns=CHAIN_Y_ALIGNS):
    """多链堆叠为单成员集（弧形多副本路径）：逐链按 ``y_aligns`` 滑移贴靠到已
    堆叠 union，取 union bbox 面积增长最小。**不做翻链变体**（翻转会反转开口
    方向，违反 v2 形态判据）。直腰头不经过本函数（全副本单链，无链间堆叠）。"""
    placed = list(chains[0])
    packed = unary_union([_geom_at(polys[m['pid']], m['rotation'],
                                   m['translation']) for m in placed])
    for ch in chains[1:]:
        ch_u = unary_union([_geom_at(polys[m['pid']], m['rotation'],
                                     m['translation']) for m in ch])
        pb, gb = packed.bounds, ch_u.bounds
        best = None
        for y_align in y_aligns:
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
                    gate_nest=GATE_MM, d_g=0.4, tol_g=3.0,
                    fill_floor=FILL_FLOOR_PCT) -> BandChunk:
    """构造性链构造 → 组合片构造（单一真相源；web 编排在 US-011 接线）。

    版师形态（v2，2026-08-21；手性自适应 2026-08-27；横向弯腰头 v3 2026-08-28）：
    每码第 k 副本一条链 → 凸左弧片降序构造+整链翻转 / 镜像凸右弧片升序构造不翻转
    （终态同为开口朝左、最大码在最右）→ 链间滑移堆叠 → union/erode/归一化；
    长轴横置弧片（3069 g11 横向弯腰头）走 T-转置支：同向弧片逐层竖排、大码在底、
    链间互扣（见模块 docstring 与分支注释）。

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
        组合片高度上限基准（= 输入门幅即实际幅宽：组合片须进主解条带，超幅主解
        放不下；链构造无 strip 约束，事后显式校验）。
    d_g : float
        该 g 码重合公差（应与构造 pid_meta 时该 label 的 per_type d 同值；组合片
        union 后 erode 深度 —— 使主解其他裁片对带边界保持与单片相同的 d_g 邻接语义）。
    tol_g : float
        该 g 码旋转公差（记录进 chunk；链构造成员朝向恒取 grain 锁 {0,180}，严于
        ``discretize_orientations(tol_g)`` —— FR-8 同口径：工艺公差属裁片不属于带）。
    fill_floor : float
        带内填充率下限（%），低于即 BandQualityError（灾难形态兜底；主判据是
        链内贴触 ``CHAIN_GAP_EPS_MM``）。

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

    # ---- 2) 构造性链构造（v2 版师形态） -------------------------------------
    # 版师构造（2026-08-21 指正）：每码第 k 副本一条链 —— 链内片片贴触、缝隙只在
    # 链间，不需要同码成对。v1 spyrrow strip 带内子求解目标是最短用布 X 而非贴触
    # （产 48% 对角阶梯、预算 ×30 仅 +4.1pt 结构性卡死；US-014 成对重试在单副本
    # 配置空真失效），整体弃用。碰撞口径 = 已腐蚀轮廓（与 v1 Item 同口径）。
    band_seed = band_seed_for(seed, label)

    def _member_poly(pid):
        poly = _clean_polygon(pid_meta[pid]['polygon'])
        if len(poly) < 3:
            raise DegenerateBand(f'成员 {pid} 腐蚀/清洗后顶点<3，不可成带')
        return poly

    polys: dict = {pid: _member_poly(pid) for pid in member_pids}
    # 直腰头分叉（2026-08-24 版师指正，882# g01 图1→图2）：成员均为平板直条时改走
    # 「同底齐平」构造 —— 近矩形条带的 side-by-side 候选 bbox 面积在端部形状互补/
    # 浮点噪声级打平（实测 882# g01 六候选互差 <1e-6mm²），严格小于的贪心被逐片
    # 翻盘 ⇒ 交替翻转+上下换锚的对角阶梯乱象。直腰头版师形态 = 同底齐平、片片
    # 同向、无翻转、大码在右（面积差 <0.1%，纯形态规则）；弧形片（质心短轴偏移
    # ~18-22mm，判据分离度 18×）仍走嵌套贪心（构造方向按手性自适应，见下方
    # else 分支）。
    member_geoms = {pid: _valid_geometry(polys[pid]) for pid in member_pids}
    flat = all(_is_flat_piece(g) for g in member_geoms.values())
    # 横向弯腰头分叉（v3 2026-08-28，3069 g11）：非 flat 弧片且全员长轴横置 ⇒
    # 开口朝上/下，走 T-转置竖排支（构造帧 = proxy，见下方 elif 分支）。
    transverse = (not flat) and all(
        _long_axis_x(g) for g in member_geoms.values())
    proxy = ({pid: [[y, x] for x, y in polys[pid]] for pid in polys}
             if transverse else None)

    def _check_chain(chain, rightmost_pid, k=None, ctor='降序+翻转'):
        """链形态三闸门：贴触 / 开口朝左 / 最右成员 = 最大码（程序自校验）。"""
        nth = f'第 {k} 链' if k is not None else '单链'
        gap = _chain_gap(chain, polys)
        if gap > CHAIN_GAP_EPS_MM:
            raise BandQualityError(
                f'链 {label!r} {nth}贴触失败（最大缝隙 {gap:.2f}mm > '
                f'{CHAIN_GAP_EPS_MM}mm）—— 形态质量悬崖，禁无声降级')
        if _opening_side(chain, polys) == 'right':
            raise BandQualityError(
                f'链 {label!r} {nth}开口朝右（{ctor}构造异常）')
        # 最右成员 = 最大码（含重复 pid 安全：逐成员取 argmax，不做 dict 折叠）
        cx_pid = max(
            (_geom_at(polys[m['pid']], m['rotation'],
                      m['translation']).centroid.x, m['pid'])
            for m in chain)[1]
        if cx_pid != rightmost_pid:
            raise BandQualityError(
                f'链 {label!r} {nth}最右成员非最大码（构造异常）')

    def _check_chain_y(chain, bottom_pid, k=None):
        """横向弧片链形态三闸门（实空间口径，chain 须先 ``_transpose_placements``）：
        贴触 / 最底成员 = 最大码 / 成员旋转 ∈ {0,180}（程序自校验）。

        与 ``_check_chain`` 平行；开口朝向**不设闸** —— 单一朝向构造
        （rots=(0,)）下开口 = 母版原向，⌣/⌢ 皆为版师合法形态（参考图只要求
        同向竖排，不规定凹口朝上/朝下）。
        """
        nth = f'第 {k} 链' if k is not None else '单链'
        gap = _chain_gap(chain, polys)
        if gap > CHAIN_GAP_EPS_MM:
            raise BandQualityError(
                f'链 {label!r} {nth}贴触失败（最大缝隙 {gap:.2f}mm > '
                f'{CHAIN_GAP_EPS_MM}mm）—— 形态质量悬崖，禁无声降级')
        for m in chain:
            if float(m['rotation']) % 180.0 != 0.0:
                raise BandQualityError(
                    f'链 {label!r} {nth}成员 {m["pid"]} 旋转 '
                    f'{m["rotation"]:.0f}° 非法（横向支构造保证 0/180°，'
                    f'映射异常）')
        cy_pid = min(
            (_geom_at(polys[m['pid']], m['rotation'],
                      m['translation']).centroid.y, m['pid'])
            for m in chain)[1]
        if cy_pid != bottom_pid:
            raise BandQualityError(
                f'链 {label!r} {nth}最底成员非最大码（构造异常）')

    chains = []
    if flat:
        # 直腰头多副本（2026-08-24 版师二次指正）：N 条「每码第 k 副本」链并排会在
        # 链交界形成「最大码|最小码」的整带高差深谷（图1 交叉布局）；版师形态 =
        # **全副本单链全局从短到长**（图2 单调阶梯，同码副本相邻）。等宽条带
        # flush-bottom 并排的 bbox 宽 = Σ条宽、高 = max 条高，与顺序无关 ——
        # 面积零代价，纯形态规则。单副本时退化为与旧版逐字节一致的单链升序。
        copies = [pid for pid in member_pids
                  for _ in range(int(pid_meta[pid]['demand']))]
        copies.sort(key=lambda pid: _member_sort_key(pid_meta[pid], pid))
        chain = _norm_chain(
            _chain_nest(copies, polys, rots=(0.0,), y_aligns=('bottom',)),
            polys)
        _check_chain(chain, rightmost_pid=copies[-1], ctor='升序同底齐平')
        chains.append(chain)
    elif transverse:
        # v3 横向弯腰头（3069 g11 族）：长轴横置弧片，版师形态 = 同向弧片逐层
        # **竖排**（居中、层距=条厚）、多副本链间互扣（用户参考图）。构造帧 =
        # T-转置 proxy（上方已建）：proxy 内即「长轴纵置弧片 + X 滑嵌套」—— 完整
        # 复用既有贪心/堆叠机器，proxy-X 滑 ⇔ 实空间 Y 滑（竖排），y_aligns 候选
        # ⇔ 实空间 X 对齐（'mid'=居中）。**单一朝向 rots=(0,)**：实空间全员
        # rot 0 = 母版原向（⌣/⌢ 皆合法形态，无需手性分支/翻转 —— 与直腰头分叉
        # 同理，多朝向候选的 bbox 噪声级打平会让贪心交替翻盘产错切带，实测
        # rots=(0,180) 时产出 11m 双行错切带 fill 44% 被拒）。降序构造 = 大码
        # 先放 ⇒ 实空间大码在链底（打底锚，参考图确定性默认）。闸门与尾部
        # （union/erode/带高/fill）零改动 —— placed 映射回实空间后走共享路径。
        max_demand = max(int(pid_meta[pid]['demand']) for pid in member_pids)
        for k in range(max_demand):
            chain_pids = sorted(
                (pid for pid in member_pids if int(pid_meta[pid]['demand']) > k),
                key=lambda pid: _member_sort_key(pid_meta[pid], pid),
                reverse=True)          # 降序：大码先放 ⇒ T 映射后大码在链底
            chain = _norm_chain(
                _chain_nest(chain_pids, proxy, rots=(0.0,)), proxy)
            _check_chain_y(_transpose_placements(chain),
                           bottom_pid=chain_pids[0], k=k)
            chains.append(chain)
    else:
        # 手性自适应（2026-08-27，M1787 g10 排查定案）：弧片凹口朝向随母版画法
        # 可左可右（布纹对齐只做 ±90° 转正、无手性规范化）—— v2「降序构造(开口
        # 朝右)+整链翻转⇒开口朝左」只对凸左弧片（5336 g05 族，质心偏移 −18~
        # −22mm）成立；镜像弧片（凸右、单片开口朝左，M1787 g10 实测 +15~+20mm）
        # 降序构造本就开口朝左，再翻转反而朝右被本闸门拒（99.9% 码组合必挂）——
        # 改走「升序构造+不翻转」，终态形态同为开口朝左+最大码在最右（实测贴触
        # 0.00mm / fill 76.8%）。判据 = 逐成员单片开口**全员** 'left' 才走镜像支
        # （'flat'/混合朝向回退 v2 原路径，既有母版行为不变）。
        mirrored = all(
            _opening_side([{'pid': pid, 'rotation': 0.0,
                            'translation': [0.0, 0.0]}], polys) == 'left'
            for pid in member_pids)
        max_demand = max(int(pid_meta[pid]['demand']) for pid in member_pids)
        for k in range(max_demand):
            chain_pids = sorted(
                (pid for pid in member_pids if int(pid_meta[pid]['demand']) > k),
                key=lambda pid: _member_sort_key(pid_meta[pid], pid),
                reverse=not mirrored)   # 凸左：降序+翻转后大码最右；镜像：升序即大码最右
            chain = _norm_chain(
                _flip_chain(_chain_nest(chain_pids, polys))
                if not mirrored else _chain_nest(chain_pids, polys), polys)
            _check_chain(chain,
                         rightmost_pid=(chain_pids[-1] if mirrored
                                        else chain_pids[0]),
                         k=k, ctor='升序不翻转' if mirrored else '降序+翻转')
            chains.append(chain)
    # 链堆叠须在**构造帧**内滑移（横向支 = proxy，proxy-X 滑 ⇔ 实空间 Y 滑互扣），
    # 横向支随后一次性映射回实空间（rot 取负、平移交换，见 _transpose_placements）。
    placed = (chains[0] if len(chains) == 1
              else _stack_chains(chains, proxy if transverse else polys))
    if transverse:
        placed = _transpose_placements(placed)
    if len(placed) != total_demand:
        raise BandQualityError(
            f'链构造副本守恒失败: 放置 {len(placed)} != Σdemand {total_demand}')

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
    strip_h = float(gate_nest)
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

