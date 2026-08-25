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

rot180 负坐标框架坑（P0 踩过，单测锁死）：成员关于原点旋转 180° 后落负坐标区，
必须**先归一到原点**再做候选对齐 + 滑触，记账平移补偿 ``tr = (xoff − b0,
yoff − b1)``（b0/b1 = 旋转后 bounds 最小角）—— 缺此补偿成员几何会整体侧移
并排、贴触形态全毁。

分层约束：本模块属 ``nesting_engine``，仅 import 标准库 + shapely + 本包兄弟
模块（``constraints`` / ``sparrow_baseline`` / ``sparrow_experiments`` /
``waist_band``）+ 下层 ``nesting_bounds``；**禁 import web/cli**（组合片构造的
单一真相源，web US-003 接线 / 未来 CLI 共用；AST 守卫在 ``tests/test_prefix.py``）。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import zlib
from pathlib import Path

from shapely.affinity import translate
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .. import paths
from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
from .constraints import MAX_OVERLAP_MM
from .sparrow_baseline import _clean_polygon, _transform_polygon
from .sparrow_experiments import erode_polygon
from .waist_band import (
    MAX_COMPOSITE_VERTICES,
    SIMPLIFY_TOLERANCE_MM,
    BandChunk,
    BandError,
    _exterior_coords,
    _solid_region,
    _valid_geometry,
)

# 前缀组合片 pid 前缀（全链路泄漏哨兵：manifest/frame/final/前端/导出永不允许 PS_）。
PREFIX_PID_PREFIX = 'PS_'
# 组合片在主解的允许朝向（FR-5 决策③ 2026-08-25：版师认可整列头尾调换，0°/180°
# 均严格顺布纹；与 waist_band.COMPOSITE_ORIENTATIONS 同口径，主解 Item 构造用）。
PREFIX_ORIENTATIONS = (0.0, 180.0)
# 成员交错序合法值（FR-10 定稿 interleave：前后前后；grouped 备档 —— P0 实测 2
# 封闭腔 = spyrrow 死区，如未来否决只切 build_prefix_plan 默认值一行）。
PREFIX_ORDERS = ('interleave', 'grouped')
# 成员数（前×2 + 后×2，恰用尽资格码 demand）。
PREFIX_MEMBER_COUNT = 4
# Y 向滑移粗扫步进（mm，镜像 waist_band.CHAIN_SLIDE_STEP_MM）。
SLIDE_STEP_MM = 20.0
# 滑移二分次数（40 次 ⇒ 收敛精度 ~2^-40×扫描区间，远小于 0.01mm）。
BISECT_ITERS = 40
# 相邻成员贴触判据（mm，镜像 waist_band.CHAIN_GAP_EPS_MM —— 版师验收口径，
# 非 bbox fill）。
GAP_EPS_MM = 1.0


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


def build_prefix_plan(pid_meta, pieces_by_id, *, front_pid, back_pid, d_g,
                      gate_nest, order='interleave'):
    """构造前缀 4 片竖排贴靠组合片（版师 P1 形态，单一真相源；US-003 编排接线）。

    构造管线（探针 ``prefix_lib.build_prefix_plan`` 移植收敛）：
    1. 成员序 interleave（前后前后）+ rot 交替 0/180（头尾相对）；
    2. 逐成员 Y 向 ``_slide_touch_y`` 贴触滑移（候选 x 对齐 = 0 / 已排 bbox 左右
       缘 / 前成员左右缘，粗扫 + 二分，无 RNG），取 union bbox 面积增长最小
       （平手取先序候选 —— 确定性）；
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
        ``pick_prefix_size`` 选定后拼出；须同码、各 demand==2）。
    d_g : float
        组合片 erode 深度（= max(d_front, d_back) 保守，由调用方裁定 —— 前后幅
        per_type d 可能不同，取 max 保证重叠公差最严格片不超限）。
    gate_nest : float
        求解约束幅宽（竖排高上限基准，钳 ``min(gate_nest, PLOT_SAFE_MAX_Y_MM)``）。
    order : str
        成员交错序（FR-10 定稿 ``'interleave'``；``'grouped'`` 备档）。

    Returns
    -------
    tuple ``(chunk, gaps, holes)``
        chunk : BandChunk —— pid ``PS_{front}+{back}@{size}``（可直接喂
            ``waist_band.expand_placements``，offset 减号权威式）；
        gaps : list[float] —— 相邻成员贴触缝隙（mm，eroded 碰撞口径，版师
            验收口径）；
        holes : int —— 组合片外轮廓封闭腔数（P0 实测：interleave 0 / grouped 2）。

    Raises
    ------
    ValueError
        order 非法值。
    PrefixError
        副本不齐 2+2 / 前后幅不同码 / 竖排超高 / 贴触形态失败 / 组合片退化。
    """
    # ---- 1) 成员序 + 副本/同码守卫 ----------------------------------------
    spec = _member_spec(front_pid, back_pid, order)
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

    # ---- 2) 构造性竖排贴靠（无 RNG；rot180 负坐标框架补偿见模块 docstring）--
    placed = []            # [(pid, rot, tr, geom)]：tr = transform 链记账平移
    occupied = None
    for pid, rot in spec:
        g_rot = _valid_geometry(pid_meta[pid]['polygon'])       # eroded 碰撞口径
        if rot != 0.0:
            g_rot = _valid_geometry(
                _transform_polygon(pid_meta[pid]['polygon'], rot, (0.0, 0.0)))
        b0, b1 = g_rot.bounds[0], g_rot.bounds[1]               # 补偿基准
        g0 = translate(g_rot, xoff=-b0, yoff=-b1)               # 先归一到原点
        if occupied is None:
            placed.append((pid, rot, (-b0, -b1), g0))
            occupied = g0
            continue
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
        #         ⇒ transform 链语义 tr = (xoff − b0, yoff − b1)（rot180 关键，单测锁死）
        placed.append((pid, rot, (xoff - b0, yoff - b1), geom))
        occupied = unary_union([occupied, geom])

    members = [{'pid': pid, 'rotation': rot, 'translation': [tr[0], tr[1]]}
               for pid, rot, tr, _g in placed]
    gaps = [float(placed[i - 1][3].distance(placed[i][3]))
            for i in range(1, len(placed))]
    if gaps and max(gaps) > GAP_EPS_MM:
        raise PrefixError(
            f'前缀成员贴触失败（最大缝隙 {max(gaps):.2f}mm > {GAP_EPS_MM}mm）—— '
            f'形态质量悬崖，禁无声降级')

    # ---- 3) 原始轮廓 union → 焊接连通 → erode(d_g) → clean → 归一化 --------
    footprints = []
    for pid, rot, tr, _g in placed:
        orig = pieces_by_id.get(pid, {}).get('polygon') or pid_meta[pid]['polygon']
        footprints.append(_valid_geometry(_transform_polygon(orig, rot, tr)))
    union = unary_union(footprints)
    minx, miny, maxx, maxy = union.bounds
    offset = (float(minx), float(miny))
    bbox = {'width_mm': float(maxx - minx), 'height_mm': float(maxy - miny)}
    strip_h = min(float(gate_nest), PLOT_SAFE_MAX_Y_MM)
    if bbox['height_mm'] > strip_h + 1e-6:
        raise PrefixError(
            f'前缀簇竖排高 {bbox["height_mm"]:.0f}mm > 条带 {strip_h:.0f}mm'
            f'（4 片同码竖排超高，组合片主解放不下）')

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

    front_label = fm.get('label') if fm.get('label') is not None \
        else front_pid.split('_')[0]
    back_label = bm.get('label') if bm.get('label') is not None \
        else back_pid.split('_')[0]
    return (BandChunk(
        pid=f'{PREFIX_PID_PREFIX}{front_label}+{back_label}@{fm["size"]}',
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


def main(argv=None) -> int:
    """冒烟入口：``python -m materialsorting.nesting_engine.prefix``。

    默认 5336 真实数据（``data/configs/5336_coded_really.json`` + intermediate）
    对拍 P0 直测数字：interleave bbox 1155×1458 / fill 83.3% / 贴触 0.00mm /
    封闭腔 0。intermediate 缺失时提示先 commit（ms-run-config 或 web 上传）。
    """
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='prefix 前缀组合片构造冒烟（US-001）')
    ap.add_argument('--intermediate', default=paths.INTERMEDIATE,
                    help='pieces_intermediate.json 路径')
    ap.add_argument(
        '--config', default=str(Path(paths.DATA_DIR) / 'configs'
                                / '5336_coded_really.json'),
        help='config JSON（sizes/quantities/per_type；不存在则 quantities=None）')
    ap.add_argument('--front', default='g02', help='前幅 g 码')
    ap.add_argument('--back', default='g03', help='后幅 g 码')
    ap.add_argument('--seed', type=int, default=0, help='资格码选取 seed')
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
    gate_nest = min(float(doc['gate_mm']), PLOT_SAFE_MAX_Y_MM)
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
    try:
        size = pick_prefix_size(elig, seed=args.seed,
                                front=args.front, back=args.back)
        print(f'  seeded 随机选取: size {size}（seed={args.seed}，确定性）')
        d_g = max(
            min(float((per_type.get(args.front) or {}).get('d', 0.0)),
                MAX_OVERLAP_MM),
            min(float((per_type.get(args.back) or {}).get('d', 0.0)),
                MAX_OVERLAP_MM))
        for order in PREFIX_ORDERS:
            chunk, gaps, holes = build_prefix_plan(
                pid_meta, {p['pid']: p for p in pieces},
                front_pid=f'{args.front}_{size}',
                back_pid=f'{args.back}_{size}',
                d_g=d_g, gate_nest=gate_nest, order=order)
            print(f'  {order:11}: {chunk.pid} bbox '
                  f'{chunk.bbox["width_mm"]:.0f}x{chunk.bbox["height_mm"]:.0f}mm '
                  f'fill={chunk.fill_pct:.1f}% '
                  f'gaps={["%.2f" % g for g in gaps]} holes={holes} '
                  f'verts={len(chunk.polygon)}')
    except (PrefixError, ValueError) as e:
        print(f'FAIL {type(e).__name__}: {e}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
