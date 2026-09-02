"""起始端成套前后幅（prefix）核心构造模块（US-001，建议1 v2）。

机制（依据 ``.docs/business/起始端成套前后幅_版师确认清单.md`` v3 §3/§7 + P0 探针
``out/tmp_probe/prefix_lib.py`` 移植收敛）：用户指认前/后幅 g 码后，在满足 **2+2
资格**（该码 front demand == 2 且 back demand == 2 —— 版师 P2：「总量 2 片或
6 片的码不行」）的尺码中 seeded 随机取一（FR-4，不出 UI），4 片（前×2 + 后×2
同码）按版师 P1 形态**构造性竖排贴靠**：interleave 交错序（前后前后，FR-10 定稿）
+ 相邻片头尾相对 180° 交替 + Y 轴向 ``_slide_touch_y`` 贴触（粗扫 + 二分，无 RNG，
确定性毫秒级）→ 成员**原始轮廓**@带内位 union → ``_solid_region`` 焊接连通 →
``erode(d_g)`` → ``_clean_polygon`` → 平移归一化，产 ``PS_*`` 组合片（``BandChunk``
同构，可直接喂 ``waist_band.expand_placements``，offset 减号权威式）；组合片以
普通自由 Item 进主解（orientations=[0., 180.]，FR-5 决策③：版师认可整列头尾
调换），前缀空隙与外部空隙由主解 NFP 邻接跨界共同填充（版师 P3 答复的字面实现）。
钉位守卫（组合片未锚定布头时的段置换）在 US-002 ``permute_pin``。

性质是**业务规则**（布头第一列成套形态的构造性保证），不是利用率优化器 ——
P0 实测密度代价 −0.14pt ≈ 0、组合片 4/4 seed 自然锚定布头。

US-002 增补**段置换钉位 + 驱逐重插**（P5 严格顶零位的守卫路径，探针
``permute_pin`` / ``reinsert_evicted`` 移植收敛）：组合片未自然锚定布头时
（P0 实测 4/4 锚定 ⇒ 本路径常态零触发），割线 c1=a 硬性 + c2∈[b0, b0+flex]
柔性选线（最小化 straddler）→ A/C/B 三组刚体重排（组间 x 区间不相交 ⇒ 无新
重叠、总长不增）→ straddler 驱逐重插（①随组平移 +x 微调梯回原窝 ②
``waist_band._slide_touch`` 自右滑触 ③尾端贴触追加兜底）→ ``constraints.validate``
+ y≤gate_nest 全版复检，失败回退置换前布局（LNS 纪律：交付物恒过检）。
三守卫缺一不可（P0 灾难 −17.72pt 三因）：``skip_at_head=6.0``（常态锚定零
触发）、``eps=5.0``（≥ erode 包络外凸，防贴墙片误判 straddler）、``flex=400.0``
（c2 柔性选线最小化驱逐）。编排入口 ``pin_prefix_layout``（纯函数语义，US-003
final 置换挂钩单点）。

rot180 负坐标框架坑（P0 踩过，单测锁死）：成员关于原点旋转 180° 后落负坐标区，
必须**先归一到原点**再做候选对齐 + 滑触，记账平移补偿 ``tr = (xoff − b0,
yoff − b1)``（b0/b1 = 旋转后 bounds 最小角）—— 缺此补偿成员几何会整体侧移
并排、贴触形态全毁。

2026-09-02 增补**顶部异码补片 + 联合选码搜索**（prd-prefix-extra-piece，
三项定案：无可行退回 4 片 / 不设缝隙阈值永远取最接近门幅者 / 保留 0°/180°
翻转自由度）：``build_prefix_plan`` additive ``extra_pid`` 追加第 5 成员
（异码前/后幅，同款候选 x + ``_slide_touch_y`` 贴触滑移，rot 遍历
``EXTRA_ROT_CANDIDATES`` 取 union bbox 面积增长最小、平手取 0.0）；
``select_prefix_plan`` 把选码从 seeded 随机升级为**近满幅联合几何搜索** ——
遍历 (套装码 A × 片型 × 异码码 B)，每组合补片朝向委派上述 FR-3 规则内定
（**需求2「弧线相切」当日修复**：此前搜索层显式枚举 rot 再按 max-H 排序，
嵌入贴合使 H 变矮、被近满幅判据反向惩罚 ⇒ 系统性选中浅搁弧峰朝向留楔形
空隙；委派后每组合即自身最贴合朝向），取 5 片原始轮廓 union bbox 总高
H ≤ gate_nest − ``PREFIX_GATE_MARGIN_MM`` 的最大者（安全余量 10mm：贴线
组合在主解条带放不下 ⇒ spyrrow 放置器 panic，2026-09-02 residual 0.307mm
事故修复；平手按迭代序确定性裁决，全流程无 RNG；seed 只在兜底路径消费），
web 求解与预览共用的单一真相源。

分层约束：本模块属 ``nesting_engine``，仅 import 标准库 + shapely + 本包兄弟
模块（``constraints`` / ``sparrow_baseline`` / ``sparrow_experiments`` /
``waist_band``）+ 下层 ``nesting_bounds``；**禁 import web/cli**（组合片构造的
单一真相源，web US-003 接线 / 未来 CLI 共用；AST 守卫在 ``tests/test_prefix.py``）。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import zlib
from pathlib import Path

from shapely.affinity import translate
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .. import paths
from .constraints import (
    MAX_OVERLAP_MM,
    MAX_ROTATION_TOL_DEG,
    discretize_orientations,
    validate,
)
from .sparrow_baseline import (
    _clean_polygon,
    _transform_polygon,
    solve_with_progress,
)
from .sparrow_experiments import erode_polygon
from .waist_band import (
    MAX_COMPOSITE_VERTICES,
    SIMPLIFY_TOLERANCE_MM,
    BandChunk,
    BandError,
    _exterior_coords,
    _slide_touch,
    _solid_region,
    _valid_geometry,
    expand_placements,
)

# 前缀组合片 pid 前缀（全链路泄漏哨兵：manifest/frame/final/前端/导出永不允许 PS_）。
PREFIX_PID_PREFIX = 'PS_'
# 组合片在主解的允许朝向（FR-5 决策③ 2026-08-25：版师认可整列头尾调换，0°/180°
# 均严格顺布纹；与 waist_band.COMPOSITE_ORIENTATIONS 同口径，主解 Item 构造用）。
PREFIX_ORIENTATIONS = (0.0, 180.0)
# 成员交错序合法值（FR-10 定稿 interleave：前后前后；grouped 备档 —— P0 实测 2
# 封闭腔 = spyrrow 死区，如未来否决只切 build_prefix_plan 默认值一行）。
PREFIX_ORDERS = ('interleave', 'grouped')
# 成员数（前×2 + 后×2，恰用尽资格码 demand；extra_pid 补片时为 5）。
PREFIX_MEMBER_COUNT = 4
# 异码补片朝向候选（2026-09-02 需求：补片头尾双向，均严格顺布纹）。
# ``build_prefix_plan`` 直调（extra_rot=None）按 union bbox 面积增长择优、
# 平手取 0.0；``select_prefix_plan`` 搜索时逐 rot 显式展开（平手裁决 rot0 先）。
EXTRA_ROT_CANDIDATES = (0.0, 180.0)
# 近满幅可行性安全余量（mm，2026-09-02 修复）：组合片高度逼近求解条带（残余
# <10mm）时 spyrrow 放置器无解，Rust 侧 panic ``strip-width is running away``
# （实测 5336 无 per_type（d_g=0）选码 residual 0.307mm 必炸；panic 抛出的
# PanicException 是 BaseException 子类，worker 的 except Exception 捕不住，
# 对外误报「solver 返回 None」）。留 10mm 稳定可行（占 1980 门幅 0.5%，近满幅
# 形态无感）。H 判据统一收紧、兜底 4 片竖排高守卫同口径 —— d_g>0 时 erode 对
# 非水平边缘的收缩 < 2·d_g，余量同样不保证，故不按 d_g 折算。
PREFIX_GATE_MARGIN_MM = 10.0
# Y 向滑移粗扫步进（mm，镜像 waist_band.CHAIN_SLIDE_STEP_MM）。
SLIDE_STEP_MM = 20.0
# 滑移二分次数（40 次 ⇒ 收敛精度 ~2^-40×扫描区间，远小于 0.01mm）。
BISECT_ITERS = 40
# 相邻成员贴触判据（mm，镜像 waist_band.CHAIN_GAP_EPS_MM —— 版师验收口径，
# 非 bbox fill）。
GAP_EPS_MM = 1.0
# ---- US-002 段置换钉位三守卫（P0 灾难 −17.72pt 三因，缺一不可） ----
# ① 组合片已在布头的跳过阈值（mm）：comp min_x ≤ 此值整体跳过置换（P0 实测
# 4/4 seed 自然锚定 0.0~0.2mm ⇒ 常态零触发；无此守卫会对已锚定布局无谓重排）。
PIN_SKIP_AT_HEAD_MM = 6.0
# ② straddler / 组归属判据容差（mm）：须 ≥ erode 合法外凸深度（2·d 包络，
# 5336 d_g=2 ⇒ 贴墙片 bd[0] 可低至 −2），防贴墙片误判 straddler 被驱逐；
# 5.0 ≥ 2·MAX(d)=4（P0 标定）。
PIN_STRADDLER_EPS_MM = 5.0
# ③ c2 割线柔性窗口（mm）：c2 ∈ [b0, b0+flex] 内在片棱边候选里柔性选线
# （最小化 straddler 数、次小 c2）—— c1=a 硬性贴零位，c2 过窄无候选余地、
# 过宽割进 B 组腹地（400 ≈ 前后幅片长量级）。
PIN_CUT_FLEX_MM = 400.0
# 驱逐重插 ②+x 微调梯（mm）：组平移回位失败后逐档右探原窝附近空间。
PIN_NUDGE_LADDER_MM = (0.0, 1.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 300.0)
# 尾端贴触追加兜底的 width_growth 警戒线（mm）：超过仅 warn 不回退（交付物已过
# validate 复检），记入 stats 供 US-003 prefix_runs 工件审计。
PIN_WIDTH_GROWTH_WARN_MM = 50.0
# 重插候选 x 下限容差（mm）：驱逐片新窝 eroded bounds[0] ≥ −0.5（钉位语义
# x=0 是布头；组员贴零位残差 ≤eps 属构造容差，驱逐片去新窝没有理由越界）。
PIN_X_FLOOR_TOL_MM = 0.5
# 全版复检 y 容差（mm）：求解器约束 erode 后形状 ∈ [0, strip_height]，原形可
# 合法外凸 ≤ MAX_OVERLAP_MM=10 + 数值余量（与 cli.lns_bands.Y_TOLERANCE_MM
# 同源口径 —— 引擎层禁 import cli，此处镜像）。
PIN_RECHECK_Y_TOLERANCE_MM = 11.0

_log = logging.getLogger(__name__)


class PrefixError(Exception):
    """前缀构造失败（无资格码 / 副本不齐 2+2 / 前后幅不同码 / 竖排超高 / 形态退化）。

    web 编排层（US-003）按需捕获转结构化 error（band 同契约）。"""


def prefix_seed_for(seed, front, back) -> int:
    """主解 seed + 前/后幅 g 码 → 资格码选取 seed（确定性派生，FR-4/FR-12）。

    勿用 ``hash()``（对 str 有 PYTHONHASHSEED 随机化，跨进程不可重放）；
    ``zlib.crc32`` 纯函数、稳定（``waist_band.band_seed_for`` 同套路）。
    """
    return zlib.crc32(f'{seed}|{front}|{back}'.encode('utf-8'))


def _demand_of(qmap, size_key) -> int:
    """数量映射取值（缺键/非数值 → 0 —— 缺码 demand 口径与资格规则一致）。"""
    try:
        return int(qmap.get(size_key, 0))
    except (TypeError, ValueError):
        return 0


def eligible_sizes(quantities, front_label, back_label, sizes=None) -> list:
    """P2 资格规则逐码校验：该码 front demand == 2 且 back demand == 2。

    版师 P2 原话「总量 2 片或 6 片的码不行」⇒ 恒等式资格（demand==2 恰用尽
    2+2），0/1/3/缺码均不合格。quantities 口径与 ``web.solver.build_pid_meta``
    一致：``{label: {sizeKey(str): N}}``；None / 缺码 → demand 缺省（≠2 同样
    不合格 —— quantities=null 全 demand=1 场景资格码为空，属 FR-9 结构化 error
    而非静默关闭）。

    Parameters
    ----------
    quantities : dict | None
        数量矩阵 ``{label: {sizeKey: N}}``。
    front_label / back_label : str
        前/后幅 g 码（如 'g02' / 'g03'）。
    sizes : 可选
        用户所排尺码过滤（求解 sizes 列表；缺省 = 两 g 码数量映射键并集）。
        资格码必须真实进入主解实例（build_pid_meta 已按 sizes 过滤），不过滤
        会选到无 pid 的码（5336：quantities 含 37/39/40 demand 2+2，但 sizes
        只排 [31..36,38] → 资格码 {32,33,34,35,38}）。

    Returns
    -------
    list[int]
        升序资格码列表（空列表 = 无资格，调用方按 FR-9 早退）。
    """
    qf = (quantities or {}).get(front_label) or {}
    qb = (quantities or {}).get(back_label) or {}
    if not isinstance(qf, dict):
        qf = {}
    if not isinstance(qb, dict):
        qb = {}
    universe = set(qf) | set(qb)
    if sizes is not None:
        want = {'null' if s is None else str(s) for s in sizes}
        universe &= want
    out = []
    for sk in universe:
        try:
            si = int(sk)
        except (TypeError, ValueError):
            continue                    # 'null'（size=None）非数字码，无资格概念
        if _demand_of(qf, sk) == 2 and _demand_of(qb, sk) == 2:
            out.append(si)
    return sorted(out)


def pick_prefix_size(eligible, *, seed, front, back) -> int:
    """资格码集合中 seeded 随机取一（FR-4：自动选取、不出 UI）。

    ``random.Random(prefix_seed_for(seed, front, back))`` 派生 —— **勿用全局
    random / hash()**（跨进程不可重放）；候选先排序归一（集合/列表输入序不
    影响结果，确定性口径的一部分）。空集合抛 ``PrefixError``（文案指路数量
    矩阵，US-003 直接复用）。
    """
    sizes = sorted({int(s) for s in eligible})
    if not sizes:
        raise PrefixError(
            f'无 2+2 资格码（front={front}, back={back}）—— '
            f'请在数量矩阵把所选码前后幅配成 2+2')
    return random.Random(prefix_seed_for(seed, front, back)).choice(sizes)


def _member_spec(front_pid, back_pid, order) -> list:
    """4 片成员序列 ``[(pid, rot), ...]``：interleave=前后前后 / grouped=前前
    后后；rot 交替 0/180（相邻片头尾相对，版师 P1 参照形态）。order 非法抛
    ``ValueError``。"""
    if order == 'interleave':
        seq = [front_pid, back_pid, front_pid, back_pid]
    elif order == 'grouped':
        seq = [front_pid, front_pid, back_pid, back_pid]
    else:
        raise ValueError(f'order 非法: {order!r}（合法值 {PREFIX_ORDERS}）')
    return [(pid, 0.0 if i % 2 == 0 else 180.0) for i, pid in enumerate(seq)]


def _slide_touch_y(g_moving, g_fixed, x_offset):
    """从上方远端竖直滑到与 g_fixed 首次贴触（``waist_band._slide_touch`` 的
    Y 轴镜像：前缀竖排沿门幅纵向堆叠）。

    可行域（不碰撞的 y 区间）非凸 —— 必须从行进方向远端（上方）起步找**首个**
    碰撞界，再在 (碰撞, 不碰撞) 区间二分到贴触点。g_moving 须已归一到原点
    （调用方保证）。返回 ``(放置几何, dy)``，dy 为施加的 y 平移量：
    ``translate(g_moving, x_offset, dy) == 放置几何``。
    """
    mb = g_moving.bounds
    fb = g_fixed.bounds
    h = mb[3] - mb[1]
    y_start = fb[3] + h + 50.0                # 上方远处起步
    y_end = fb[1] - h - 5.0

    def place(y_bottom):
        return translate(g_moving, xoff=x_offset, yoff=y_bottom - mb[1])

    def collides(y_bottom):
        return place(y_bottom).intersection(g_fixed).area >= 1e-6

    if collides(y_start):
        return place(y_start), y_start - mb[1]
    hit = None
    y = y_start
    while y > y_end:
        yn = max(y - SLIDE_STEP_MM, y_end)
        if collides(yn):
            hit = (yn, y)                     # (碰撞, 不碰撞)
            break
        y = yn
    if hit is None:
        return place(y_end), y_end - mb[1]
    a, b = hit
    for _i in range(BISECT_ITERS):
        mid = (a + b) / 2.0
        if collides(mid):
            a = mid
        else:
            b = mid
    return place(b), b - mb[1]                # b = 行进方向首个贴触位（不碰撞侧）


def _eroded_at_rot(polygon, rot):
    """eroded 碰撞轮廓 @ 朝向（rot≠0 先绕原点旋转再 ``buffer(0)`` 修复）。"""
    g = _valid_geometry(polygon)
    if rot != 0.0:
        g = _valid_geometry(_transform_polygon(polygon, rot, (0.0, 0.0)))
    return g


def _place_next(placed, occupied, pid, rot, g_rot):
    """单成员贴靠放置（候选 x 对齐 + ``_slide_touch_y`` 贴触滑移）：取 union
    bbox 面积增长最小（平手取先序候选 —— 确定性），就地 append 到 ``placed``
    并返回新 occupied（union）。记账 tr=(xoff−b0, yoff−b1)（rot180 负坐标
    补偿，权威式 —— 缺此补偿成员几何整体侧移并排，单测锁死）。"""
    b0, b1 = g_rot.bounds[0], g_rot.bounds[1]               # 补偿基准
    g0 = translate(g_rot, xoff=-b0, yoff=-b1)               # 先归一到原点
    ub = occupied.bounds
    w = g0.bounds[2] - g0.bounds[0]
    pb = placed[-1][3].bounds
    best = None
    for xo in sorted({0.0, ub[0], ub[2] - w, pb[0], pb[2] - w}):
        geom, dy = _slide_touch_y(g0, occupied, xo)
        nb = geom.bounds
        cost = ((max(nb[2], ub[2]) - min(nb[0], ub[0]))
                * (max(nb[3], ub[3]) - min(nb[1], ub[1])))
        if best is None or cost < best[0] - 1e-9:           # 平手取先序候选
            best = (cost, geom, xo, dy)
    _cost, geom, xoff, yoff = best
    # 记账补偿：放置几何 = translate(rotate(原轮廓)∘translate(−b0,−b1), xoff, yoff)
    #         ⇒ transform 链语义 tr = (xoff − b0, yoff − b1)（rot180 关键）
    placed.append((pid, rot, (xoff - b0, yoff - b1), geom))
    return unary_union([occupied, geom])


def _assert_touch_gaps(placed):
    """相邻成员贴触缝隙守卫（> ``GAP_EPS_MM`` 即形态质量悬崖，禁无声降级 ——
    从 ``_place_members`` 尾部抽出，2026-09-02：补片 rot 候选循环内也要逐 rot
    校验，贴触不合格的朝向没有候选资格）。"""
    gaps = [float(placed[i - 1][3].distance(placed[i][3]))
            for i in range(1, len(placed))]
    if gaps and max(gaps) > GAP_EPS_MM:
        raise PrefixError(
            f'前缀成员贴触失败（最大缝隙 {max(gaps):.2f}mm > {GAP_EPS_MM}mm）—— '
            f'形态质量悬崖，禁无声降级')


def _place_members(pid_meta, front_pid, back_pid, order, extra_pid=None,
                   extra_rot=None):
    """构造性竖排贴靠成员放置（``build_prefix_plan`` 步骤 2 抽出的单一实现，
    2026-09-02）。

    4 片基座（``_member_spec`` interleave 交错序 + rot 交替 0/180 头尾相对）
    与抽出前**逐字节一致**；``extra_pid`` 给定时追加第 5 成员 = **顶部异码
    补片**：同款候选 x 集合 + ``_slide_touch_y`` 滑到与已占 union 首次贴触
    （eroded 碰撞口径）；``extra_rot=None`` 时遍历 ``EXTRA_ROT_CANDIDATES``
    逐 rot 放置 + 贴触校验（单 rot 失败只记错误不炸整组合，全败才 raise ——
    2026-09-02「任一 rot 可行即组合可行」语义），可行者中取 union bbox 面积
    增长最小（平手取 0.0，FR-3 = 弧线相切嵌入形态自动胜出），显式给定时只试
    该朝向（``select_prefix_plan`` 胜者重建 / 单测用）。

    Returns
    -------
    list[tuple]
        ``[(pid, rot, tr, geom), ...]`` —— tr = transform 链记账平移（权威式
        ``(xoff−b0, yoff−b1)``）；geom = eroded 碰撞口径放置几何。

    Raises
    ------
    PrefixError
        相邻成员贴触缝隙 > ``GAP_EPS_MM``（含补片↔顶片；形态质量悬崖，禁无声
        降级 —— ``select_prefix_plan`` 捕获后跳过该候选）。
    """
    placed = []            # [(pid, rot, tr, geom)]：tr = transform 链记账平移
    occupied = None
    for pid, rot in _member_spec(front_pid, back_pid, order):
        g_rot = _eroded_at_rot(pid_meta[pid]['polygon'], rot)   # eroded 碰撞口径
        if occupied is None:
            b0, b1 = g_rot.bounds[0], g_rot.bounds[1]
            placed.append((pid, rot, (-b0, -b1),
                           translate(g_rot, xoff=-b0, yoff=-b1)))
            occupied = placed[0][3]
            continue
        occupied = _place_next(placed, occupied, pid, rot, g_rot)
    if extra_pid is not None:
        rot_cands = EXTRA_ROT_CANDIDATES if extra_rot is None \
            else (float(extra_rot),)
        best = None       # (union bbox 面积, placed 副本, occupied) —— 平手取先序
        first_err = None
        for rot in rot_cands:
            trial = list(placed)                          # 基座列表不被污染
            try:
                occ = _place_next(trial, occupied, extra_pid, rot,
                                  _eroded_at_rot(pid_meta[extra_pid]['polygon'],
                                                 rot))
                _assert_touch_gaps(trial)     # rot 候选资格：贴触合格才算数
            except PrefixError as e:          # 单 rot 失败不炸整组合 → 试下一 rot
                first_err = first_err or e
                continue
            nb = occ.bounds
            area = (nb[2] - nb[0]) * (nb[3] - nb[1])
            if best is None or area < best[0] - 1e-9:     # 平手取先序 rot（0.0）
                best = (area, trial, occ)
        if best is None:                      # 全 rot 皆败 → 透传首个错误（现行文案）
            raise first_err
        _area, placed, occupied = best
    _assert_touch_gaps(placed)
    return placed


def _raw_union(placed, pid_meta, pieces_by_id):
    """成员**原始轮廓**@记账位 union（竖排高守卫 / bbox / offset 同一口径：
    erode 只进碰撞口径，union 与包络断言用原始轮廓，不缩面积/不缩簇）。"""
    footprints = []
    for pid, rot, tr, _g in placed:
        orig = pieces_by_id.get(pid, {}).get('polygon') or pid_meta[pid]['polygon']
        footprints.append(_valid_geometry(_transform_polygon(orig, rot, tr)))
    return unary_union(footprints)


def _stack_height(placed, pid_meta, pieces_by_id):
    """成员原始轮廓 union bbox 高度（近满幅判据 H —— 与竖排高守卫同口径，
    ``select_prefix_plan`` 可行性 H ≤ gate_nest 用）。"""
    b = _raw_union(placed, pid_meta, pieces_by_id).bounds
    return float(b[3] - b[1])


def _extra_candidates(pid_meta, front_label, back_label):
    """补片候选池（FR-2，从 pid_meta 派生 —— sizes/quantities 过滤已内含）：
    label ∈ {front, back}、size 数字码、demand ≥ 1（≠A 在搜索层按 A 过滤）。

    Returns
    -------
    list[tuple]
        ``[(label, size_int, pid), ...]`` —— front 先于 back、size 升序（搜索
        迭代序 = 平手裁决序，确定性）。
    """
    order = {front_label: 0, back_label: 1}
    rows = []
    for pid, meta in pid_meta.items():
        label = meta.get('label')
        if label not in order:
            continue
        s = meta.get('size')
        if s is None or isinstance(s, bool):
            continue
        try:
            si = int(s)
        except (TypeError, ValueError):
            continue        # 'null'（size=None 键）/ 非数字码无补片资格
        if int(meta.get('demand') or 0) < 1:
            continue
        rows.append((order[label], si, pid))
    rows.sort()
    return [(front_label if oi == 0 else back_label, si, pid)
            for oi, si, pid in rows]


def build_prefix_plan(pid_meta, pieces_by_id, *, front_pid, back_pid, d_g,
                      gate_nest, order='interleave', extra_pid=None,
                      extra_rot=None):
    """构造前缀 4 片竖排贴靠组合片（版师 P1 形态，单一真相源；US-003 编排接线）。

    2026-09-02 additive ``extra_pid``（顶部异码补片，第 5 成员）：同款候选 x
    集合 + ``_slide_touch_y`` 滑到与已占 union 首次贴触（eroded 碰撞口径），
    ``extra_rot=None`` 时 rot 遍历 ``EXTRA_ROT_CANDIDATES`` 取 union bbox 面积
    增长最小（平手取 0.0）；``extra_pid=None`` 时输出与 4 片路径**逐字节一致**
    （既有用例零改动 = 回归红线）。联合选码入口见 ``select_prefix_plan``。

    构造管线（探针 ``prefix_lib.build_prefix_plan`` 移植收敛）：
    1. 成员序 interleave（前后前后）+ rot 交替 0/180（头尾相对）；
    2. 逐成员 Y 向 ``_slide_touch_y`` 贴触滑移（``_place_members``，候选 x 对齐
       = 0 / 已排 bbox 左右缘 / 前成员左右缘，粗扫 + 二分，无 RNG），取 union
       bbox 面积增长最小（平手取先序候选 —— 确定性）；
    3. 成员**原始轮廓**@带内位 → union → ``_solid_region`` 焊接 → ``erode(d_g)``
       → ``_clean_polygon`` → 平移归一化（记录 offset，展开减号）。

    Parameters
    ----------
    pid_meta : dict
        ``web.solver.build_pid_meta`` 产物（碰撞口径 = 已腐蚀 polygon，不二次
        腐蚀；demand 即该 pid 进主解的副本数）。
    pieces_by_id : dict
        intermediate 原始裁片 ``{pid: {'polygon': 原始轮廓, ...}}``（union 与
        包络断言用**原始**轮廓；erode 只进碰撞口径，不缩面积/不缩簇）。
    front_pid / back_pid : str
        前/后幅 pid（``f'{label}_{size}'``；资格码经 ``eligible_sizes`` +
        ``pick_prefix_size``/``select_prefix_plan`` 选定后拼出；须同码、各
        demand==2）。
    d_g : float
        组合片 erode 深度（= max(d_front, d_back) 保守，由调用方裁定 —— 前后幅
        per_type d 可能不同，取 max 保证重叠公差最严格片不超限）。
    gate_nest : float
        求解约束幅宽（竖排高上限基准 = 输入门幅 − ``PREFIX_GATE_MARGIN_MM``
        安全余量，2026-09-02 起与 ``select_prefix_plan`` 的可行线同口径）。
    order : str
        成员交错序（FR-10 定稿 ``'interleave'``；``'grouped'`` 备档）。
    extra_pid : str, optional
        顶部异码补片 pid（第 5 成员；候选资格 = label∈{front,back}、数字码、
        ≠套装码、demand≥1 —— ``select_prefix_plan`` 的派生池同规则）。
    extra_rot : float, optional
        补片朝向（``EXTRA_ROT_CANDIDATES`` 内的值）；None = 遍历择优（面积
        增长最小、平手 0.0）。``select_prefix_plan`` 胜者重建时钉搜索选定朝向。

    Returns
    -------
    tuple ``(chunk, gaps, holes)``
        chunk : BandChunk —— pid ``PS_{front}+{back}@{size}``（补片时追加
            ``+{extra_label}@{extra_size}`` 如 ``PS_g02+g03@34+g02@32``；可
            直接喂 ``waist_band.expand_placements``，offset 减号权威式）；
        gaps : list[float] —— 相邻成员贴触缝隙（mm，eroded 碰撞口径，版师
            验收口径；4 片 3 条 / 5 片 4 条含补片↔顶片）；
        holes : int —— 组合片外轮廓封闭腔数（P0 实测：interleave 0 / grouped 2）。

    Raises
    ------
    ValueError
        order 非法值。
    PrefixError
        副本不齐 2+2 / 前后幅不同码 / 补片资格不符 / 竖排超高 / 贴触形态
        失败 / 组合片退化。
    """
    # ---- 1) 成员序 + 副本/同码/补片资格守卫 --------------------------------
    _member_spec(front_pid, back_pid, order)   # order 非法早抛（原异常次序）
    fm = pid_meta.get(front_pid)
    bm = pid_meta.get(back_pid)
    for pid, meta in ((front_pid, fm), (back_pid, bm)):
        demand = int(meta['demand']) if meta is not None else 0
        if meta is None or demand != 2:
            raise PrefixError(
                f'前缀成员 {pid} 副本不齐 2+2（demand={demand}）—— '
                f'资格码须该码前、后幅各恰好 2 片')
    if fm['size'] != bm['size']:
        raise PrefixError(
            f'前后幅不同码（{front_pid} size={fm["size"]} vs {back_pid} '
            f'size={bm["size"]}）—— 前缀 4 片须同码')
    front_label = fm.get('label') if fm.get('label') is not None \
        else front_pid.split('_')[0]
    back_label = bm.get('label') if bm.get('label') is not None \
        else back_pid.split('_')[0]
    extra_meta = None
    extra_label = None
    if extra_pid is not None:
        extra_meta = pid_meta.get(extra_pid)
        if extra_meta is None or int(extra_meta.get('demand') or 0) < 1:
            raise PrefixError(
                f'前缀补片 {extra_pid} 无可用副本（候选资格：label∈'
                f'{{{front_label},{back_label}}}、数字码、≠套装码、demand≥1）')
        if extra_pid in (front_pid, back_pid):
            raise PrefixError(
                f'前缀补片 {extra_pid} 与套装同码 —— 异码补片须 ≠ 套装码')
        extra_label = extra_meta.get('label') \
            if extra_meta.get('label') is not None else extra_pid.split('_')[0]
        if extra_label not in (front_label, back_label):
            raise PrefixError(
                f'前缀补片 {extra_pid} 片型 {extra_label} 非前/后幅 g 码'
                f'（候选资格 label∈{{{front_label},{back_label}}}）')

    # ---- 2) 构造性竖排贴靠（_place_members，无 RNG；rot180 负坐标框架补偿
    #         见模块 docstring；贴触缝隙守卫在 _place_members 内）------------
    placed = _place_members(pid_meta, front_pid, back_pid, order,
                            extra_pid=extra_pid, extra_rot=extra_rot)
    members = [{'pid': pid, 'rotation': rot, 'translation': [tr[0], tr[1]]}
               for pid, rot, tr, _g in placed]
    gaps = [float(placed[i - 1][3].distance(placed[i][3]))
            for i in range(1, len(placed))]

    # ---- 3) 原始轮廓 union → 焊接连通 → erode(d_g) → clean → 归一化 --------
    union = _raw_union(placed, pid_meta, pieces_by_id)
    minx, miny, maxx, maxy = union.bounds
    offset = (float(minx), float(miny))
    bbox = {'width_mm': float(maxx - minx), 'height_mm': float(maxy - miny)}
    # 安全条带界 = 门幅 − PREFIX_GATE_MARGIN_MM（与 select_prefix_plan 的
    # limit 同口径，2026-09-02 修复）：兜底 4 片路径同样不许贴线（d_g=0 时
    # 组合片碰撞轮廓 == 原始 union，残余 <margin 在主解条带放不下 ⇒ spyrrow
    # panic「strip-width is running away」）。
    strip_h = float(gate_nest) - PREFIX_GATE_MARGIN_MM
    if bbox['height_mm'] > strip_h + 1e-6:
        cnt_txt = '5 片（4 同码 + 异码补片）' if extra_pid is not None \
            else '4 片同码'
        raise PrefixError(
            f'前缀簇竖排高 {bbox["height_mm"]:.0f}mm > 安全条带界 '
            f'{strip_h:.0f}mm（门幅 {float(gate_nest):.0f} − 余量 '
            f'{PREFIX_GATE_MARGIN_MM:.0f}；{cnt_txt}竖排超高，组合片主解放不下）')

    try:
        solid = _solid_region(union)
    except BandError as e:
        raise PrefixError(f'前缀簇焊接不连通: {e}') from e
    holes = len(solid.interiors)
    outline = _exterior_coords(solid)
    if d_g > 0:
        outline = erode_polygon(outline, float(d_g))   # 失败自动回退原轮廓（超集安全方向）
    if len(outline) > MAX_COMPOSITE_VERTICES:
        outline = _exterior_coords(
            Polygon(outline).simplify(SIMPLIFY_TOLERANCE_MM, preserve_topology=True))
    comp = _clean_polygon(outline)
    if len(comp) < 3:
        raise PrefixError(f'前缀组合片 erode({d_g}) 后顶点<3，退化')
    comp = [[x - offset[0], y - offset[1]] for x, y in comp]    # 平移归一化（减 offset）

    # ---- 4) 带内填充率（成员原面积和 / union bbox 面积，实际占用口径）-------
    area_sum = sum(float(pid_meta[m['pid']]['area_mm2']) for m in members)
    bbox_area = bbox['width_mm'] * bbox['height_mm']
    fill_pct = (area_sum / bbox_area * 100.0) if bbox_area > 0 else 0.0

    ps_pid = f'{PREFIX_PID_PREFIX}{front_label}+{back_label}@{fm["size"]}'
    if extra_pid is not None:
        ps_pid += f'+{extra_label}@{extra_meta["size"]}'
    return (BandChunk(
        pid=ps_pid,
        label=front_label,
        polygon=comp,
        offset=offset,
        members=members,
        fill_pct=fill_pct,
        bbox=bbox,
        seed=0,            # 构造无 RNG（区别 band v1 带内子求解）—— 恒 0 占位
        d_g=float(d_g),
        tol_g=0.0,         # 成员朝向恒 grain 锁 {0,180}，tol 不参与构造（band 同口径）
    ), gaps, holes)


# --------------------------------- 选码搜索（顶部异码补片，2026-09-02 需求）


def select_prefix_plan(pid_meta, pieces_by_id, *, front_label, back_label,
                       quantities, sizes, d_g, gate_nest, seed,
                       order='interleave', trace=None):
    """近满幅联合选码搜索（单一真相源：web 求解与预览共用；取代 seeded 随机）。

    机制（prd-prefix-extra-piece，生产参考件形态：4 片同码套装 + 顶部 1 片
    异码前/后幅，整列近满幅）：遍历 (套装码 A × 片型 × 异码码 B) —— 对每组
    合构造性滑移贴触（``_place_members``，eroded 碰撞口径），补片朝向由其
    内置 **FR-3 规则**择优（union bbox 面积增长最小、平手取 0.0 = 弧线相切
    嵌入形态胜出；2026-09-02 需求2 修复 —— 此前搜索层显式枚举 rot 再按
    max-H 排序，会系统性选中「浅搁弧峰」朝向、留下楔形空隙），H = 5 片
    **原始轮廓** union bbox 高度（与竖排高守卫同口径），可行 = H ≤ gate_nest
    − ``PREFIX_GATE_MARGIN_MM``（安全余量：组合片碰撞轮廓（d_g=0 时即原始
    union）贴到条带时 spyrrow 放置器 panic，2026-09-02 residual 0.307mm
    事故起因）且贴触缝隙 ≤ ``GAP_EPS_MM``；**组合间取 H 最大者**（最接近
    安全线，不设缝隙阈值 —— 残余交主解 NFP 填小片，用户定案 2026-09-02 ②
    —— 每组合已是自身最贴合朝向，取高者与相切嵌合并行不悖），平手按迭代
    序 ``(A 升序, front 先于 back, B 升序)`` 确定性裁决 —— **全流程无 RNG**
    （``seed`` 只在兜底路径消费）。基座自身超高/贴触失败的 A 直接跳过（补片
    只会更高）。

    兜底（用户定案 ①）：全无可行组合 → ``pick_prefix_size``（crc32 seeded，
    含资格码为空时 PrefixError 现行文案）+ 4 片 ``build_prefix_plan``，与
    现行行为完全一致，``info['fallback']=True``。胜者按搜索选定朝向跑一次
    完整管线（``build_prefix_plan(extra_pid, extra_rot=…)``）产 5 片 chunk。

    Parameters
    ----------
    pid_meta / pieces_by_id : dict
        同 ``build_prefix_plan``（候选池从 pid_meta 派生 —— sizes/quantities
        过滤已内含，单一真相）。
    front_label / back_label : str
        前/后幅 g 码（如 'g02' / 'g03'）。
    quantities / sizes :
        同 ``eligible_sizes``（资格码 P2 规则 2+2；sizes = 用户所排尺码过滤）。
    d_g / gate_nest / order :
        同 ``build_prefix_plan``。
    seed : int
        仅兜底路径的 ``pick_prefix_size`` 消费（搜索路径确定性、与 seed 无关）。
    trace : list, optional
        给定时逐候选 append ``{'size','label','extra_size','rotation'|None,
        'height_mm'|None,'feasible','reason'}``（冒烟候选表用；不影响选码；
        rotation = FR-3 择优朝向，不可行时 None）。

    Returns
    -------
    tuple ``(chunk, gaps, holes, info)``
        info : dict —— ``{'size': A, 'extra': {'pid','label','size','rotation'}
        | None, 'height_mm', 'residual_mm' (= gate_nest − H), 'fallback': bool,
        'n_candidates': int (实际尝试的 (A,片型,B) 组合数，含不可行；rot 不
        枚举 —— 每组合由 FR-3 内定一个)}。
    """
    elig = eligible_sizes(quantities, front_label, back_label, sizes=sizes)
    cands = _extra_candidates(pid_meta, front_label, back_label)
    # 安全余量（PREFIX_GATE_MARGIN_MM，2026-09-02 修复）：见常量注释 —— 贴线
    # 组合（残余 <10mm）在主解条带放不下 ⇒ spyrrow panic。
    limit = float(gate_nest) - PREFIX_GATE_MARGIN_MM
    best = None            # (H, A, label, extra_pid, rot)
    n_candidates = 0
    for A in sorted(elig):
        fpid, bpid = f'{front_label}_{A}', f'{back_label}_{A}'
        if fpid not in pid_meta or bpid not in pid_meta:
            continue                    # 资格码无对应 pid（数据不一致）→ 跳过
        try:
            base = _place_members(pid_meta, fpid, bpid, order)
        except PrefixError:
            continue                    # 基座贴触失败 → 跳过
        if _stack_height(base, pid_meta, pieces_by_id) > limit:
            continue                    # 基座自身超高 → 补片只会更高，跳过
        for _label, B, epid in cands:
            if B == A:
                continue                # 异码 ≠A（同码 pid 即基座成员，demand 守恒会破）
            n_candidates += 1
            row = {'size': A, 'label': _label, 'extra_size': B,
                   'rotation': None, 'height_mm': None,
                   'feasible': False, 'reason': ''}
            if trace is not None:
                trace.append(row)
            try:
                # rot 不在搜索层枚举（2026-09-02 需求2「弧线相切」修复）：显式
                # 枚举 + max-H 判据会系统性选中「浅搁」朝向 —— 嵌入贴合使 H 变
                # 矮、恰好被近满幅判据反向惩罚。委派 _place_members 的 FR-3 规
                # 则（union bbox 面积增长最小、平手取 0.0）= 自动选相切嵌入。
                placed = _place_members(
                    pid_meta, fpid, bpid, order, extra_pid=epid)
            except PrefixError as e:
                row['reason'] = f'贴触失败({e})'
                continue
            rot = float(placed[-1][1])                    # FR-3 选定朝向（回收）
            H = _stack_height(placed, pid_meta, pieces_by_id)
            row['rotation'] = rot
            row['height_mm'] = round(float(H), 3)
            if H > limit:
                row['reason'] = '竖排超高'
                continue
            row['feasible'] = True
            if best is None or H > best[0] + 1e-9:    # 平手取先序（确定性裁决）
                best = (H, A, _label, epid, rot)
    if best is None:
        # 兜底（用户定案①）：与现行行为完全一致（含 elig 空 → PrefixError 文案）
        size = pick_prefix_size(elig, seed=seed, front=front_label,
                                back=back_label)
        chunk, gaps, holes = build_prefix_plan(
            pid_meta, pieces_by_id, front_pid=f'{front_label}_{size}',
            back_pid=f'{back_label}_{size}', d_g=d_g, gate_nest=gate_nest,
            order=order)
        info = {'size': int(size), 'extra': None,
                'height_mm': float(chunk.bbox['height_mm']),
                'residual_mm': float(gate_nest) - float(chunk.bbox['height_mm']),
                'fallback': True, 'n_candidates': n_candidates}
        return chunk, gaps, holes, info
    H, A, label, epid, rot = best
    chunk, gaps, holes = build_prefix_plan(
        pid_meta, pieces_by_id, front_pid=f'{front_label}_{A}',
        back_pid=f'{back_label}_{A}', d_g=d_g, gate_nest=gate_nest,
        order=order, extra_pid=epid, extra_rot=rot)
    em = pid_meta[epid]
    info = {'size': int(A),
            'extra': {'pid': epid, 'label': em.get('label'),
                      'size': em.get('size'), 'rotation': float(rot)},
            'height_mm': float(chunk.bbox['height_mm']),
            'residual_mm': float(gate_nest) - float(chunk.bbox['height_mm']),
            'fallback': False, 'n_candidates': n_candidates}
    return chunk, gaps, holes, info


# ------------------------------------------- US-002 段置换钉位 + 驱逐重插


def _world_raw_geom(placement, pid_meta, pieces_by_id):
    """placement → 原始轮廓 shapely 几何（世界系；id 必为真实 pid —— ``PS_``
    组合片已在上游 ``expand_placements`` 展开，总长/密度按原始轮廓口径）。"""
    orig = (pieces_by_id.get(placement['id']) or {}).get('polygon') \
        or pid_meta[placement['id']]['polygon']
    return _valid_geometry(_transform_polygon(
        orig, placement['rotation'], placement['translation']))


def _eroded_geom(placement, pid_meta):
    """placement → erode 碰撞轮廓 shapely 几何（求解器合法性口径：eroded 两两
    不相交即合法 —— 重插碰撞检测同此口径）。"""
    return _valid_geometry(_transform_polygon(
        pid_meta[placement['id']]['polygon'], placement['rotation'],
        placement['translation']))


def permute_pin(placements, geoms_raw, geoms_eroded, comp_world, prefix_idx, *,
                flex=PIN_CUT_FLEX_MM, eps=PIN_STRADDLER_EPS_MM,
                skip_at_head=PIN_SKIP_AT_HEAD_MM):
    """段置换钉位：前缀组合片段（x 占据 [a, b0]）平移到 x=0，其余段刚体重排。

    机制（确认清单 §3.3，探针 ``prefix_lib.permute_pin`` 移植）：

    - 组合片已在头部（a ≤ ``skip_at_head``）→ **整体跳过**（E=∅，零代价 ——
      P0 灾难 −17.72pt 的修复：组合片常态已锚定布头，置换本属多余）；
    - c1 = a（硬性，组合片贴零位）；c2 在 [b0, b0+``flex``] 柔性选线（片棱边
      候选中**最小化 straddler 数**、次小 c2 —— 尽量零驱逐）；
    - A = x-span ⊆ [c1−eps, c2+eps]（前缀成员 + 深窝填充片，**强制含
      prefix_idx**）；C = max_x ≤ c1+eps（头部左侧段）；B = min_x ≥ c2−eps
      （割线右侧段）；横跨割线的 straddler 驱逐（``eps`` ≥ d 包络，防贴墙片
      bd[0]=−2 误判）；
    - 重排 = A(−a) + C(紧随 A) + B(紧随 C)：组间 x 区间不相交 ⇒ 无新重叠、
      总长不增（段间隙被压缩，x 刚体平移不动 y）。

    Parameters
    ----------
    placements : list[dict]
        ``{'id','rotation','translation'}``（**已展开**，无 PS_）；**就地修改**
        （translation[0] += 组平移），geoms 同步平移 —— 纯函数入口见
        ``pin_prefix_layout``。
    geoms_raw / geoms_eroded : list[shapely]
        与 placements 逐条对应的原始/erode 轮廓几何（就地同步平移）。
    comp_world : shapely geometry
        组合片 eroded 轮廓@主解世界位（``chunk.polygon`` 施加主解 rotation/
        translation）。
    prefix_idx : sequence[int]
        组合片 4 成员在 placements 中的下标（强制并入 A 组；空序列 ValueError）。
    flex / eps / skip_at_head : float
        三守卫参数（模块常量缺省，P0 标定锁死）。

    Returns
    -------
    tuple ``(placements, shift, stats)``
        placements : list[dict] —— 同入参列表（就地修改后返回，链式便利）；
        shift : dict[int, float] —— 逐片组平移量（index → dx，mm）；
        stats : dict —— ``skipped`` / ``a`` / ``b0`` / ``c2`` / ``nA`` / ``nC``
            / ``nB`` / ``n_evicted`` / ``evicted_idx`` / ``group``（idx→'A'/'B'/
            'C'）。跳过时组字段全零。
    """
    if not prefix_idx:
        raise ValueError('prefix_idx 不能为空（须含组合片展开成员下标）')
    bounds = [g.bounds for g in geoms_raw]
    a, b0 = comp_world.bounds[0], comp_world.bounds[2]
    if a <= skip_at_head:
        st = {'skipped': True, 'a': round(a, 3), 'b0': round(b0, 3), 'c2': None,
              'nA': 0, 'nC': 0, 'nB': 0, 'n_evicted': 0, 'evicted_idx': [],
              'group': {}}
        return placements, {}, st

    def _straddles(bd, c):
        return bd[0] < c - eps and bd[2] > c + eps

    c2_cands = {b0}
    for bd in bounds:
        for v in (bd[0], bd[2]):
            if b0 <= v <= b0 + flex:
                c2_cands.add(v)
    c2 = min(c2_cands, key=lambda c: (sum(1 for bd in bounds if _straddles(bd, c)), c))

    prefix_set = set(prefix_idx)
    A = [i for i, bd in enumerate(bounds)
         if i in prefix_set or (bd[0] >= a - eps and bd[2] <= c2 + eps)]
    A_set = set(A)
    C = [i for i, bd in enumerate(bounds)
         if i not in A_set and bd[2] <= a + eps]
    B = [i for i, bd in enumerate(bounds)
         if i not in A_set and bd[0] >= c2 - eps]
    taken = A_set | set(C) | set(B)
    E = [i for i in range(len(placements)) if i not in taken]

    group = {i: 'A' for i in A}
    group.update({i: 'C' for i in C})
    group.update({i: 'B' for i in B})

    # 段拼接：A 贴零位（−a），C 紧随 A 右缘，B 紧随 C 右缘（组间 x 区间不相交）
    shift = {}
    dxA = -a
    a_max = max(bounds[i][2] for i in A) + dxA
    if C:
        c_dx = a_max - min(bounds[i][0] for i in C)
        for i in C:
            shift[i] = c_dx
        c_max = max(bounds[i][2] + c_dx for i in C)
    else:
        c_max = a_max
    if B:
        b_dx = c_max - min(bounds[i][0] for i in B)
        for i in B:
            shift[i] = b_dx
    for i in A:
        shift[i] = dxA

    for i, dxi in shift.items():
        placements[i]['translation'][0] += dxi
        geoms_raw[i] = translate(geoms_raw[i], xoff=dxi)
        geoms_eroded[i] = translate(geoms_eroded[i], xoff=dxi)

    stats = {'skipped': False, 'a': round(a, 3), 'b0': round(b0, 3),
             'c2': round(c2, 3), 'nA': len(A), 'nC': len(C), 'nB': len(B),
             'n_evicted': len(E), 'evicted_idx': E, 'group': group}
    return placements, shift, stats


def reinsert_evicted(placements, geoms_raw, geoms_eroded, evicted, shift,
                     pid_meta, *, gate_nest):
    """驱逐片贪心重插（eroded 碰撞口径 = 求解器合法性），确定性无 RNG。

    三优先序（确认清单 §3.4）：

    1. **原窝回位** —— 原位置施加组平移 dxA/dxC/dxB（凹口随组平移仍在，多数
       情况下整片仍合法即零代价回位；候选 = shift 值降序）；
    2. **+x 微调梯** —— ``PIN_NUDGE_LADDER_MM``（0..300mm）逐档右探原窝附近；
    3. **自右滑触** —— ``waist_band._slide_touch`` 同法（候选 y = 已占棱边 ∪
       0/gate 底，eroded 碰撞口径，代价 = 全局宽度，平手取先序 y）；全部失败
       时**尾端贴触追加兜底**（cur_max + 片宽 + 60mm，width_growth 计入 stats，
       超阈值 warn）。

    逐片按**面积降序**入占（大件先挑窝，小件填缝 —— 平手 tie-break 确定性）；
    候选统一要求 eroded bounds[0] ≥ −``PIN_X_FLOOR_TOL_MM``（x=0 是布头，
    驱逐片新窝不越界）。**就地修改** placements/geoms；返回 stats dict
    （``n_home`` / ``n_nudge`` / ``n_slide`` / ``width_before`` / ``final_width``
    / ``width_growth`` —— width_before 为**置换后**口径（驱逐片仍在原窝），
    growth 只度量重插自身足迹影响）。
    """
    E_set = set(evicted)
    placed_idx = [i for i in range(len(placements)) if i not in E_set]
    # 空占用（全部驱逐，理论不可达）→ unary_union([]) 空 GeometryCollection，
    # intersection 面积恒 0（一切候选合法），防御性退化安全。
    occupied = unary_union([geoms_eroded[i] for i in placed_idx])
    width_before = max((g.bounds[2] for g in geoms_raw), default=0.0)
    n_home = n_nudge = n_slide = 0
    group_shift_cands = sorted({s for s in shift.values() if s != 0.0},
                               reverse=True)

    for e in sorted(evicted, key=lambda i: -float(pid_meta[placements[i]['id']]
                                                  ['area_mm2'])):
        ge = geoms_eroded[e]
        b = ge.bounds
        w, h = b[2] - b[0], b[3] - b[1]
        cur_max = max((geoms_raw[i].bounds[2] for i in placed_idx), default=0.0)
        cand = None

        def _legal(sx):
            c2_ = translate(ge, xoff=sx)
            if c2_.bounds[0] < -PIN_X_FLOOR_TOL_MM:
                return None                      # 布头下限（x=0 语义）
            return c2_ if c2_.intersection(occupied).area < 1e-6 else None

        # ① 组平移回位 + ② +x 微调梯（tier 显式标记：梯值与组平移值撞车时
        # 仍按来源计数，勿用值隶属判断）
        for tier, cands in (('home', group_shift_cands),
                            ('nudge', PIN_NUDGE_LADDER_MM)):
            for sx in cands:
                cand = _legal(sx)
                if cand is not None:
                    if tier == 'home':
                        n_home += 1
                    else:
                        n_nudge += 1
                    break
            if cand is not None:
                break
        # ③ 自右滑触（全部候选失败时尾端贴触追加兜底）
        if cand is None:
            g0n = translate(ge, xoff=-b[0], yoff=-b[1])   # 归一到原点
            # 候选 y = 棱边四类对齐（bottom↔bottom / top↔top / bottom↔top /
            # top↔bottom）∪ {0, gate 底}。探针只生成前两类 ⇒ 走廊类凹口
            # （驱逐片底对占用顶）永不可达，此处补全（仍棱边口径，确定性）。
            ys = {0.0, gate_nest - h}
            for i in placed_idx + [j for j in evicted if j != e]:
                bi = geoms_eroded[i].bounds
                ys |= {bi[1], bi[3], bi[1] - h, bi[3] - h}
            best = None
            for y in sorted(ys):
                if y < -2.0 or y + h > gate_nest + 2.0:
                    continue
                g_at = translate(g0n, xoff=cur_max + w + 60.0, yoff=y)
                geom_t, _dx = _slide_touch(g_at, occupied, 0.0)
                if geom_t.bounds[0] < -PIN_X_FLOOR_TOL_MM:
                    # 走廊畅通滑过头 ⇒ 贴 x=0 布头墙（钉位语义：x=0 是布头，
                    # 探针直接放行负坐标属缺陷，此处钳制后仍过碰撞复检）
                    geom_t = translate(g0n, xoff=0.0, yoff=y)
                if geom_t.intersection(occupied).area >= 1e-6:
                    continue
                costw = max(cur_max, geom_t.bounds[2])
                if best is None or costw < best[1]:      # 平手取先序 y（确定性）
                    best = (geom_t, costw)
            if best is not None:
                cand = best[0]
            else:                                         # 尾端贴触追加兜底
                cand = translate(ge, xoff=cur_max + w + 60.0 - b[0])
            n_slide += 1

        delta_x = cand.bounds[0] - b[0]
        delta_y = cand.bounds[1] - b[1]
        placements[e]['translation'][0] += delta_x
        placements[e]['translation'][1] += delta_y
        geoms_eroded[e] = cand
        geoms_raw[e] = translate(geoms_raw[e], xoff=delta_x, yoff=delta_y)
        occupied = unary_union([occupied, cand])
        placed_idx.append(e)

    width_after = max((g.bounds[2] for g in geoms_raw), default=0.0)
    min_x = min(min((g.bounds[0] for g in geoms_raw), default=0.0), 0.0)
    growth = width_after - width_before
    stats = {'n_home': n_home, 'n_nudge': n_nudge, 'n_slide': n_slide,
             'width_before': round(width_before, 3),
             'final_width': round(width_after - min_x, 3),
             'width_growth': round(growth, 3)}
    if growth > PIN_WIDTH_GROWTH_WARN_MM and n_slide:
        _log.warning('前缀驱逐重插含尾端追加（slide 兜底 %d 片）：width_growth '
                     '%.1fmm 超警戒线 %.0fmm（交付物已过 validate 复检，明细见 stats）',
                     n_slide, growth, PIN_WIDTH_GROWTH_WARN_MM)
    return stats


def _recheck_layout(placements, geoms_raw, gate_nest):
    """置换后全版复检：``constraints.validate`` + y ≤ gate_nest（LNS 纪律）。

    与 ``cli.lns_bands.recheck_layout`` 同源口径（引擎层禁 import cli，此处
    镜像）：``validate`` 的 x 界检查是老位图引擎的幅宽方向，sparrow 世界坐标
    Y=门幅 ⇒ 传 **(y, x) 交换**坐标（再整体 + y 容差平移、gate 同步放宽
    2×容差，容纳 erode 合法外凸），覆盖「数量 / 幅宽向界内 / 用布长度正向」；
    y 向另按 ``gate_nest`` 复检（越界片计数）。``validate`` 只消费
    点列的 x 极值 ⇒ 每片传 bbox 角点（shapely MultiPolygon 免展开分叉）。

    返回 ``(ok, issues)``。
    """
    strip_h = float(gate_nest)
    tol = PIN_RECHECK_Y_TOLERANCE_MM
    width = max((g.bounds[2] for g in geoms_raw), default=0.0)
    carriers = [_PidCarrier(pl['id']) for pl in placements]
    swapped = [(carriers[k],
                [(g.bounds[1] + tol, g.bounds[0]), (g.bounds[3] + tol, g.bounds[0]),
                 (g.bounds[1] + tol, g.bounds[2]), (g.bounds[3] + tol, g.bounds[2])])
               for k, g in enumerate(geoms_raw)]
    ok, issues = validate(swapped, swapped, width, strip_h + 2 * tol, 1.0)
    y_viol = sum(1 for g in geoms_raw
                 if g.bounds[3] > strip_h + tol)
    if y_viol:
        issues = list(issues) + [
            f'{y_viol} 片越过求解门幅 y<={strip_h:.0f}mm']
    return bool(ok and y_viol == 0), list(issues)


class _PidCarrier:
    """``constraints.validate`` 的 piece 载体（只读 ``pid`` 属性）。"""

    __slots__ = ('pid',)

    def __init__(self, pid):
        self.pid = pid


def pin_prefix_layout(placements, pid_meta, pieces_by_id, chunk, comp_rotation,
                      comp_translation, prefix_idx, *, gate_nest,
                      flex=PIN_CUT_FLEX_MM, eps=PIN_STRADDLER_EPS_MM,
                      skip_at_head=PIN_SKIP_AT_HEAD_MM):
    """置换钉位终检编排（US-003 final 挂钩单点）：permute → reinsert → 复检。

    纯函数语义：**不修改入参 placements**（内部工作副本），恒返回新列表 ——
    复检失败回退 = 返回置换前布局副本（LNS 纪律：交付物恒过检）。组合片
    min_x ≤ ``skip_at_head`` 时零触碰直通（P0 常态锚定路径，PIN ≡ FREE）。

    Parameters
    ----------
    placements : list[dict]
        final 布局（**已展开**：PS_ 已替换为 4 成员条目，无组合片条目）。
    pid_meta / pieces_by_id : dict
        ``build_pid_meta`` 产物 / intermediate 原始裁片（erode 与原始轮廓口径）。
    chunk : BandChunk
        ``build_prefix_plan`` 产物（组合片 polygon）。
    comp_rotation / comp_translation : float, Sequence[float]
        组合片在主解 final 的旋转 / 平移（展开所用同一位）。
    prefix_idx : sequence[int]
        4 成员在 placements 中的下标。
    gate_nest : float
        求解约束幅宽（复检 gate 界，= 输入门幅即实际幅宽）。

    Returns
    -------
    tuple ``(placements, stats)``
        placements : list[dict] —— 新列表（跳过/回退时为原布局副本）；
        stats : dict —— ``permute_pin`` stats 平铺 + ``reinsert``（子 dict 或
            None）+ ``rolled_back`` + ``issues``（US-003 落 prefix_runs 工件）。
    """
    backup = [{'id': p['id'], 'rotation': p['rotation'],
               'translation': [p['translation'][0], p['translation'][1]]}
              for p in placements]
    work = [{'id': p['id'], 'rotation': p['rotation'],
             'translation': [p['translation'][0], p['translation'][1]]}
            for p in placements]
    geoms_raw = [_world_raw_geom(p, pid_meta, pieces_by_id) for p in work]
    geoms_eroded = [_eroded_geom(p, pid_meta) for p in work]
    comp_world = _valid_geometry(_transform_polygon(
        chunk.polygon, comp_rotation, comp_translation))

    work, _shift, st = permute_pin(
        work, geoms_raw, geoms_eroded, comp_world, prefix_idx,
        flex=flex, eps=eps, skip_at_head=skip_at_head)
    if st['skipped']:
        return backup, {**st, 'reinsert': None, 'rolled_back': False, 'issues': []}

    rstats = reinsert_evicted(work, geoms_raw, geoms_eroded,
                              st['evicted_idx'], _shift, pid_meta,
                              gate_nest=gate_nest)
    ok, issues = _recheck_layout(work, geoms_raw, gate_nest)
    stats = {**st, 'reinsert': rstats, 'rolled_back': not ok, 'issues': issues}
    if not ok:
        _log.warning('前缀置换复检失败，回退置换前布局: %s', '; '.join(issues))
        return backup, stats
    return work, stats


# --------------------------------------------------------------- 冒烟入口

def _smoke_pid_meta(pieces, *, sizes=None, quantities=None, per_type=None) -> dict:
    """冒烟用最小 pid_meta（镜像 ``web.solver.build_pid_meta`` 核心流水线 —— 引擎
    层禁 import web，此处只复现构造所需字段：sizes 过滤 → demand → per_type d
    覆盖（``MAX_OVERLAP_MM`` 钳制）→ erode → clean）。"""
    if sizes:
        want = {int(s) for s in sizes}
        pieces = [p for p in pieces if p['size'] in want]
    pid_meta = {}
    for p in pieces:
        label = p.get('label')
        sk = 'null' if p['size'] is None else str(p['size'])
        qmap = (quantities or {}).get(label) if label is not None else None
        demand = int(qmap.get(sk, 0)) if isinstance(qmap, dict) else 1
        if demand <= 0:
            continue
        over = (per_type or {}).get(label) if label is not None else None
        d = float(over.get('d', 0.0)) if isinstance(over, dict) else 0.0
        d = min(d, MAX_OVERLAP_MM)
        poly = p['polygon']
        if d > 0:
            poly = erode_polygon(poly, d)
        poly = _clean_polygon(poly)
        if len(poly) < 3:
            continue
        pid_meta[p['pid']] = {
            'size': p['size'], 'color': '#000000', 'polygon': poly,
            'area_mm2': p['area_mm2'], 'label': label, 'demand': demand,
            'net_polygon': [], 'internal_lines': [], 'notches': [],
            'grain_line': None,
        }
    return pid_meta


def _pin_demo(pid_meta, pieces_by_id, chunk, per_type, *, gate_nest, seed,
              time_budget) -> bool:
    """US-002 置换演示冒烟：组合片自由进解 → 展开置换钉位 → 断言守卫语义。

    5336 真实数据主解（短预算）：PS 组合片 + pid 级扣减构造 spyrrow 实例（探针
    ``probe2_ab_three_arm.solve_free`` 同构，引擎层不 import web —— item 构造
    镜像 ``web.solver.build_instance`` 的 Item 层），解后展开 4 成员 →
    ``pin_prefix_layout`` 终检编排。断言（P0 回归口径）：

    - 组合片自然锚定布头（min_x ≤ 6mm）⇒ 置换跳过、布局逐字节不变（PIN ≡ FREE，
      密度差 0.00pt —— P0 实测 4/4 seed 行为）；
    - 未锚定 ⇒ 置换后组合片 min_x ≤ 6mm 且复检通过不回退。

    返回是否全部断言通过。
    """
    import spyrrow

    member_pids = {m['pid'] for m in chunk.members}
    items = []
    for pid, meta in pid_meta.items():
        if pid in member_pids:
            continue
        tol = float(((per_type or {}).get(meta['label']) or {}).get('tol', 0.0))
        items.append(spyrrow.Item(
            id=pid, shape=[(float(x), float(y)) for x, y in meta['polygon']],
            demand=int(meta['demand']),
            allowed_orientations=discretize_orientations(min(tol, MAX_ROTATION_TOL_DEG))))
    items.append(spyrrow.Item(
        id=chunk.pid, shape=[(float(x), float(y)) for x, y in chunk.polygon],
        demand=1, allowed_orientations=list(PREFIX_ORIENTATIONS)))
    inst = spyrrow.StripPackingInstance(
        name='prefix_pin_demo', strip_height=float(gate_nest), items=items)
    scfg = spyrrow.StripPackingConfig(
        total_computation_time=int(time_budget), seed=int(seed),
        quadtree_depth=4, num_workers=4)
    sol, _curve, elapsed = solve_with_progress(inst, scfg)

    comp = next((pi for pi in sol.placed_items if pi.id == chunk.pid), None)
    if comp is None:
        print(f'FAIL: 主解未放置组合片 {chunk.pid}（placed={len(sol.placed_items)}）')
        return False
    members = expand_placements(chunk, comp.rotation, comp.translation)
    placements = [{'id': pi.id, 'rotation': pi.rotation,
                   'translation': [pi.translation[0], pi.translation[1]]}
                  for pi in sol.placed_items if pi.id != chunk.pid]
    placements += members
    prefix_idx = list(range(len(placements) - len(members), len(placements)))

    total_area = sum(float(m['area_mm2']) * int(m['demand'])
                     for m in pid_meta.values())

    def _report(pls):
        geoms = [_world_raw_geom(p, pid_meta, pieces_by_id) for p in pls]
        width = max(g.bounds[2] for g in geoms) \
            - min(min(g.bounds[0] for g in geoms), 0.0)
        pmin = min(geoms[i].bounds[0] for i in prefix_idx)
        return width, total_area / (width * gate_nest) * 100.0, pmin

    w0, d0, pmin0 = _report(placements)
    print(f'  [demo] FREE: width={w0:.0f}mm density={d0:.2f}% '
          f'comp_min_x={pmin0:.1f}mm（head_already={pmin0 <= PIN_SKIP_AT_HEAD_MM}）'
          f' {elapsed:.0f}s')
    out, st = pin_prefix_layout(
        placements, pid_meta, pieces_by_id, chunk, comp.rotation,
        comp.translation, prefix_idx, gate_nest=gate_nest)
    if st['skipped']:
        same = all(a['translation'] == b['translation'] and a['id'] == b['id']
                   for a, b in zip(out, placements))
        w1, d1, pmin1 = _report(out)
        print(f'  [demo] PIN : skipped=True（组合片已在头部 a={st["a"]}mm）'
              f' layout_identical={same}')
        print(f'  [demo] PIN : width={w1:.0f}mm density={d1:.2f}% '
              f'prefix_min_x={pmin1:.1f}mm Δdensity={d1 - d0:+.2f}pt')
        if not same or w1 != w0:
            print('FAIL: 跳过路径不得改动布局（PIN 应逐字节 == FREE）')
            return False
        print('  [demo] PASS: 置换跳过，PIN ≡ FREE（P0 常态锚定回归口径）')
        return True

    r = st.get('reinsert') or {}
    w1, d1, pmin1 = _report(out)
    print(f'  [demo] PIN : a={st["a"]} b0={st["b0"]} c2={st["c2"]} '
          f'A/C/B={st["nA"]}/{st["nC"]}/{st["nB"]} '
          f'evicted={st["n_evicted"]} (home/nudge/slide='
          f'{r.get("n_home")}/{r.get("n_nudge")}/{r.get("n_slide")} '
          f'growth={r.get("width_growth")}mm rolled_back={st["rolled_back"]})')
    print(f'  [demo] PIN : width={w1:.0f}mm density={d1:.2f}% '
          f'prefix_min_x={pmin1:.1f}mm Δdensity={d1 - d0:+.2f}pt')
    if pmin1 > PIN_SKIP_AT_HEAD_MM:
        print(f'FAIL: 置换后组合片 min_x {pmin1:.1f}mm > {PIN_SKIP_AT_HEAD_MM}mm')
        return False
    if st['rolled_back']:
        print('FAIL: 复检失败被回退（构造性用例不允许）')
        return False
    print('  [demo] PASS: 置换钉位 min_x ≤ 6mm 且复检通过')
    return True


def main(argv=None) -> int:
    """冒烟入口：``python -m materialsorting.nesting_engine.prefix``。

    默认 5336 真实数据（``data/configs/5336_coded_really.json`` + intermediate）
    对拍 P0 直测数字：interleave bbox 1155×1458 / fill 83.3% / 贴触 0.00mm /
    封闭腔 0。2026-09-02 起追加**选码搜索段**（``select_prefix_plan``）：打印
    候选表（逐 (A,片型,B,rot) 的 H 与可行性）+ 选定组合 + residual。``--pin-demo``
    追加 US-002 置换演示（构造 + 短预算主解 + 钉位断言）。intermediate 缺失时
    提示先 commit（ms-run-config 或 web 上传）。
    """
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description='prefix 前缀组合片构造/置换冒烟（US-001/US-002）')
    ap.add_argument('--intermediate', default=paths.INTERMEDIATE,
                    help='pieces_intermediate.json 路径')
    ap.add_argument(
        '--config', default=str(Path(paths.DATA_DIR) / 'configs'
                                / '5336_coded_really.json'),
        help='config JSON（sizes/quantities/per_type；不存在则 quantities=None）')
    ap.add_argument('--front', default='g02', help='前幅 g 码')
    ap.add_argument('--back', default='g03', help='后幅 g 码')
    ap.add_argument('--seed', type=int, default=0, help='资格码选取 seed')
    ap.add_argument('--pin-demo', action='store_true',
                    help='追加段置换钉位演示（spyrrow 短预算主解 + 守卫断言）')
    ap.add_argument('--time', type=int, default=5,
                    help='置换演示主解预算（秒，仅 --pin-demo）')
    args = ap.parse_args(argv)

    if not os.path.exists(args.intermediate):
        print(f'ERROR: intermediate 不存在: {args.intermediate}\n'
              f'  先 commit 母版生成（如 ms-run-config data/configs/'
              f'5336_coded_really.json --time 5），再以 --intermediate 指向'
              f' pieces_intermediate.json')
        return 1
    with open(args.intermediate, encoding='utf-8') as f:
        doc = json.load(f)
    pieces = doc['pieces']
    gate_nest = float(doc['gate_mm'])
    cfg = {}
    if os.path.exists(args.config):
        with open(args.config, encoding='utf-8') as f:
            cfg = json.load(f)
        print(f'config: {args.config}')
    sizes = cfg.get('sizes')
    quantities = cfg.get('quantities')
    per_type = cfg.get('per_type') or {}
    pid_meta = _smoke_pid_meta(
        pieces, sizes=sizes, quantities=quantities, per_type=per_type)

    print(f'== prefix 构造冒烟（front={args.front} back={args.back} '
          f'seed={args.seed} gate_nest={gate_nest:.0f}mm '
          f'{len(pid_meta)} pids）==')
    elig = eligible_sizes(quantities, args.front, args.back, sizes=sizes)
    print(f'  资格码: {elig}')
    d_g = max(
        min(float((per_type.get(args.front) or {}).get('d', 0.0)),
            MAX_OVERLAP_MM),
        min(float((per_type.get(args.back) or {}).get('d', 0.0)),
            MAX_OVERLAP_MM))
    pieces_by_id = {p['pid']: p for p in pieces}
    try:
        size = pick_prefix_size(elig, seed=args.seed,
                                front=args.front, back=args.back)
        print(f'  seeded 随机选取: size {size}（seed={args.seed}，确定性）')
        interleave_chunk = None
        for order in PREFIX_ORDERS:
            chunk, gaps, holes = build_prefix_plan(
                pid_meta, pieces_by_id,
                front_pid=f'{args.front}_{size}',
                back_pid=f'{args.back}_{size}',
                d_g=d_g, gate_nest=gate_nest, order=order)
            if order == 'interleave':
                interleave_chunk = chunk
            print(f'  {order:11}: {chunk.pid} bbox '
                  f'{chunk.bbox["width_mm"]:.0f}x{chunk.bbox["height_mm"]:.0f}mm '
                  f'fill={chunk.fill_pct:.1f}% '
                  f'gaps={["%.2f" % g for g in gaps]} holes={holes} '
                  f'verts={len(chunk.polygon)}')
    except (PrefixError, ValueError) as e:
        print(f'FAIL {type(e).__name__}: {e}')
        return 1

    print('== 选码搜索（顶部异码补片近满幅，select_prefix_plan）==')
    trace = []
    try:
        sel_chunk, sel_gaps, sel_holes, sel_info = select_prefix_plan(
            pid_meta, pieces_by_id, front_label=args.front,
            back_label=args.back, quantities=quantities, sizes=sizes,
            d_g=d_g, gate_nest=gate_nest, seed=args.seed, trace=trace)
    except (PrefixError, ValueError) as e:
        print(f'FAIL {type(e).__name__}: {e}')
        return 1
    if trace:
        print(f'  候选表（{len(trace)} 组合，可行 = H ≤ gate '
              f'{gate_nest:.0f}mm 且贴触 ≤{GAP_EPS_MM:.0f}mm）:')
        for row in trace:
            hs = f'{row["height_mm"]:8.1f}' if row['height_mm'] is not None \
                else '     n/a'
            rs = f'rot{row["rotation"]:.0f}' if row['rotation'] is not None \
                else 'rot-'
            print(f'    A@{row["size"]:<3} + {row["label"]}@'
                  f'{row["extra_size"]:<3} {rs}: '
                  f'H={hs} {"可行" if row["feasible"] else "否(" + row["reason"] + ")"}')
    if sel_info['fallback']:
        print(f'  无可行 5 片组合 → 兜底 4 片 seeded（size={sel_info["size"]}，'
              f'与现行行为一致；seed 只在此路径消费）')
    else:
        ex = sel_info['extra']
        print(f'  选定: 套装@{sel_info["size"]} + 顶部 {ex["label"]}@{ex["size"]}'
              f'（rot {ex["rotation"]:.0f}°）H={sel_info["height_mm"]:.1f}mm '
              f'residual={sel_info["residual_mm"]:.1f}mm / gate '
              f'{gate_nest:.0f}mm（{sel_info["n_candidates"]} 组合，无 RNG）')
        print(f'  {sel_chunk.pid} bbox '
              f'{sel_chunk.bbox["width_mm"]:.0f}x'
              f'{sel_chunk.bbox["height_mm"]:.0f}mm '
              f'fill={sel_chunk.fill_pct:.1f}% '
              f'gaps={["%.2f" % g for g in sel_gaps]} holes={sel_holes} '
              f'members={len(sel_chunk.members)} '
              f'verts={len(sel_chunk.polygon)}')
    if args.pin_demo:
        print(f'== prefix 置换演示（{args.time}s 预算主解，US-002 守卫断言）==')
        if not _pin_demo(pid_meta, pieces_by_id, interleave_chunk, per_type,
                         gate_nest=gate_nest, seed=args.seed,
                         time_budget=args.time):
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
