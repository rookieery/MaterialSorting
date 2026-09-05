"""编辑排料「智能微调」引擎层确定性后处理模块（US-001，prd-edit-polish）。

机制（PRD tasks/prd-edit-polish.md）：spyrrow 目标函数只有料长，重合（per_type
d 腐蚀位图放行的工艺余量）与旋转（离散角度集 ±45°）只是可行性维度 —— 终局
布局常带「旁边有足够空位却不回正/不分离」的负面重合与旋转（版师手动局部微调
补的正是这个结构性缺口）。本模块是标准的**解抛光后处理**：

- ① **诊断**（物理毛版轮廓口径 = ``pieces_by_id`` 原始 polygon，与 /export
  ``placed_to_world`` 同源 —— erode 后轮廓只反映碰撞口径，导出真相是原始轮廓）：
  全图两两重合（bbox 预筛 + shapely 交集面积/穿透深度）+ 旋转偏差审计
  （每片 dev = min(rot mod 180, 180 − rot mod 180)，{0°,180°} 布纹等价合法）；
- ② **去旋转**：dev>0 的片按 dev 降序（平手按下标），沿
  ``constraints.discretize_orientations`` 同款离散角度集向最近基线 {0°,180°}
  步进试放（先试基线，无可行位逐步回退），质心锚定旋转
  ``t' = c_world − R(rot')·c_local``（与 ``sparrow_baseline._transform_polygon``
  / 前端 pointsStr 同式）+ 邻域可行位搜索取**位移最小**可行位（shapely 邻域
  候选：质心锚定原位 + 障碍/门幅棱边对齐，逐候选按位移升序试守卫）；
- ③ **去重叠**：重叠对按穿透深度降序（平手按 (i,j) 下标），最小分离平移
  （镜像 ``waist_band._slide_touch`` 的二分滑移机器：从当前重叠位向 +y/−y/−x
  二分到贴触 + 1nm 防贴死微抬），方向优先 ±y、−x 不增料长；一片失败换动
  另一片；都失败记 residual —— **只在「免费」时做**（不增料长、零新重合），
  版师 per_type d 工艺余量语义不受影响（不强行动归零 d 预算内的必要贴触）；
- ④ **压缩回收**（``compact=True`` 才启用，US-005）：自布头方向（minX 升序、
  平手下标）逐片 ``−x`` 滑贴（``_slide_west_touch`` 粗扫+二分到与全图障碍或
  x=0 布头墙首次贴触 + 1nm 回退，镜像 ``waist_band._slide_touch`` 机器）——
  左片先贴、右片随后贴新位，级联把去旋/分离释放的空隙收进料长；**接受条件 =
  全图物理包络 maxX 严格变小**（终检不过整段回滚 —— 无改进逐字节不变，
  compact=true 输出与非 compact 档全等）；
- ⑤ **报告**：before/after 七指标（重叠对数/最大穿透/总重合面积/旋转偏差片数/
  Σ偏差/料长/密度）+ moves 逐条明细 + residual（终态重合对 + 旋转残留如实
  上报，不硬凑零）+ excluded + elapsed_sec；density = real 口径
  ``Σ(area×multiplicity)/(width×gate)``（原面积，非 erode）。

**逐 move 五道守卫**（任一不过弃该 move，最坏全 no-op）：y∈[0,gate] / 全图
物理包络不增（width ≤ width_before + 0.5mm 容差，minX<0 布头外凸同计 —— 包络
是双向的）/ 位移片 vs 全图物理轮廓零新重合（shapely 精确复核，交集面积
≤ 0.1mm²）/ pid 多重集守恒（demand>1 同 pid N 条按**数组下标**逐实例寻址，
绝不 pid 去重 —— 与前端 editStore「同 pid 第 k 次出现 = 第 k 副本」同口径）/
exclude 集片永不被移动（仍作为障碍参与他人检查）。

**无改进时返回输入 list 原对象**（逐字节不变量，LNS 同款哲学：无严格改进
不回写）。确定性：无 RNG、排序平手一律按下标裁决、同输入同输出。

分层约束：本模块属 ``nesting_engine``，仅 import 标准库 + shapely + 本包兄弟
模块（``constraints`` / ``sparrow_baseline`` / ``waist_band``）+ 父包 ``paths``；
**禁 import web/cli**（AST 守卫在 tests/test_polish.py）。``compact`` 旗标为
US-005 压缩回收档（additive：缺省 false = pass ④ 整段跳过，US-001~003 行为
逐字节不变）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter

from shapely.affinity import translate
from shapely.geometry import Point, Polygon

from .. import paths
from .constraints import discretize_orientations
from .sparrow_baseline import _transform_polygon
from .waist_band import _valid_geometry

# 「重合」判定面积阈值（mm²）：诊断计数与守卫复核同口径（PRD 技术考虑
# 「shapely 零新重合判定交集面积 ≤0.1mm²」）。
OVERLAP_AREA_EPS_MM2 = 0.1
# 分离二分「碰撞」判定面积阈值（mm²）：比 _slide_touch 的 1e-6 更紧一档，
# 配合 1nm 防贴死微抬保证终态交集面积精确为 0。
COLLIDE_AREA_EPS_MM2 = 1e-9
# 分离二分后防贴死微抬（mm，1 纳米 —— 物理无感，换取 shapely 交集严格为空）。
SEP_NUDGE_MM = 1e-9
# 包络守卫容差（mm）：PRD「全图物理包络 maxX ≤ width_before(+0.5mm 容差)」。
WIDTH_TOL_MM = 0.5
# y∈[0,gate] 数值容差（mm）：容纳变换/贴触位浮点噪声（构造容差仍按 0 口径）。
GATE_EPS_MM = 1e-6
# 旋转偏差非零判定（°）。
DEV_EPS_DEG = 1e-9
# 分离二分次数（40 次 ⇒ 收敛精度 ~2^-40×扫描区间，_slide_touch 同款）。
BISECT_ITERS = 40
# 去旋转邻域候选的障碍筛选扩张（mm）：候选只对 bbox 距离在此范围内的片生成
# （远片的对齐位必然远超位移最小候选，剪枝省守卫开销）。
NEIGHBOR_MARGIN_MM = 50.0
# 压缩回收粗扫步长（mm）：``waist_band.CHAIN_SLIDE_STEP_MM`` 同款（−x 滑贴
# 首个碰撞界的定界扫描）。
COMPACT_SCAN_STEP_MM = 20.0
# 压缩回收「包络 maxX 严格变小」判定阈值（mm）：小于此视为数值噪声 → 整段
# 回滚（无改进逐字节不变）。
COMPACT_GAIN_EPS_MM = 1e-6


class PolishError(Exception):
    """polish 输入/内部不变量失败（web 层按需捕获转结构化 error）。"""


# --------------------------------------------------------------- 基元算子

def _rotation_dev(rot: float) -> float:
    """旋转 → 相对布纹基线 {0°,180°} 的偏差（°，∈[0,90]，180° 布纹等价合法）。"""
    r = float(rot) % 360.0
    d = r % 180.0
    return min(d, 180.0 - d)


def _nearest_baseline(rot: float) -> float:
    """旋转 → 最近基线（180 的倍数；90° 平手按 round 半偶规则归 0，确定性）。"""
    r = float(rot) % 360.0
    return round(r / 180.0) * 180.0


def _derotate_ladder(rot: float) -> list:
    """去旋转候选角阶梯：沿 ``discretize_orientations`` 同款离散集向最近基线回退。

    以当前偏差 dev 充当 tol 生成离散角度集（同一步进规则：dev≤5° 步进 1°、
    否则 5°），只取**最近基线一侧**（向 180° 对侧翻是 ~155° 大摆角，非「步进
    回退」）且 dev 严格小于当前值的候选，按 (新 dev, 角度) 升序 —— 先试基线
    （dev=0），无可行位逐步回退。dev≤0 返回空。
    """
    r = float(rot) % 360.0
    dev = _rotation_dev(r)
    if dev <= DEV_EPS_DEG:
        return []
    base = _nearest_baseline(r)
    cands = []
    for a in discretize_orientations(dev):
        a = float(a) % 360.0
        # 只取最近基线一侧：到 base 的带符号角距（(−180,180] 归一）
        dist = (a - base + 180.0) % 360.0 - 180.0
        if abs(dist) > dev + 1e-9:
            continue
        d = _rotation_dev(a)
        if d < dev - DEV_EPS_DEG:
            cands.append((d, a))
    cands.sort()
    return [a for _d, a in cands]


def _world_geom(placement, pieces_by_id):
    """placement → 物理毛版轮廓 shapely 几何（世界系；与 /export 同口径：
    ``pieces_by_id`` 原始 polygon 施加 rotation+translation，非 eroded）。"""
    piece = pieces_by_id.get(placement['id'])
    if piece is None or not piece.get('polygon'):
        raise PolishError(
            f"placed pid {placement['id']!r} 不在 pieces_by_id（母版已变更？"
            f"请重新求解/上传）")
    return _valid_geometry(_transform_polygon(
        piece['polygon'], float(placement.get('rotation', 0.0)),
        placement.get('translation', (0.0, 0.0))))


def _bbox_overlaps(ba, bb) -> bool:
    """bbox 预筛：两 bounds 是否重叠（闭区间，浮点直接比较）。"""
    return not (ba[2] < bb[0] or bb[2] < ba[0] or ba[3] < bb[1] or bb[3] < ba[1])


def _iter_rings(geom):
    """几何 → 外环坐标迭代（Polygon 取 exterior，MultiPolygon 逐子元）。"""
    parts = getattr(geom, 'geoms', None) or (geom,)
    for g in parts:
        if g.geom_type == 'Polygon' and g.exterior is not None:
            yield g.exterior.coords
        elif hasattr(g, 'coords'):
            yield g.coords


def _penetration_depth(ga, gb) -> float:
    """两重合几何的穿透深度（mm）= 深入方的采样点到对方边界的最大距离（双向）。

    与前端 editGeometry.penetrationDepth 同语义（顶点最深点口径），采样点 =
    顶点 + 边中点 —— 共边平贴重合（顶点恰落在对方边界上，如等宽矩形叠压）
    顶点深度恒 0，中点补采样才能量出真实压入深度。非重合对返回 0。
    """
    depth = 0.0
    for src, other in ((ga, gb), (gb, ga)):
        boundary = other.boundary
        for ring in _iter_rings(src):
            pts = list(ring)
            samples = [(x, y) for x, y in pts]
            for k in range(len(pts) - 1):
                x0, y0 = pts[k]
                x1, y1 = pts[k + 1]
                samples.append(((x0 + x1) / 2.0, (y0 + y1) / 2.0))
            for x, y in samples:
                pt = Point(x, y)
                if other.covers(pt):
                    d = pt.distance(boundary)
                    if d > depth:
                        depth = d
    return depth


def _layout_width(geoms) -> float:
    """全图物理包络料长（mm）：``maxX − min(minX, 0)``（x=0 是布头，左侧外凸
    同计入 —— prefix/LNS 同一口径）。"""
    max_x = max((g.bounds[2] for g in geoms), default=0.0)
    min_x = min((g.bounds[0] for g in geoms), default=0.0)
    return max_x - min(min_x, 0.0)


def _pair_stats(ga, gb):
    """两几何重合统计：交集面积 ≤ 阈值 → None；否则 (面积, 穿透深度)。"""
    if not _bbox_overlaps(ga.bounds, gb.bounds):
        return None
    area = ga.intersection(gb).area
    if area <= OVERLAP_AREA_EPS_MM2:
        return None
    return area, _penetration_depth(ga, gb)


def _diagnose(geoms, items, total_area, gate_mm):
    """全图诊断（物理毛版轮廓口径）：七指标摘要 + 重合对明细（i<j 下标序）。

    density = real 口径 ``Σ(area×multiplicity)/(width×gate)``（百分数）。
    """
    pairs = []
    n = len(geoms)
    for i in range(n):
        for j in range(i + 1, n):
            st = _pair_stats(geoms[i], geoms[j])
            if st is None:
                continue
            pairs.append({'i': i, 'j': j, 'area_mm2': st[0],
                          'penetration_mm': st[1]})
    devs = [_rotation_dev(it['rotation']) for it in items]
    width = _layout_width(geoms)
    summary = {
        'overlap_pairs': len(pairs),
        'max_penetration_mm': round(max((p['penetration_mm'] for p in pairs),
                                        default=0.0), 3),
        'total_overlap_area_mm2': round(sum(p['area_mm2'] for p in pairs), 3),
        'rotated_pieces': sum(1 for d in devs if d > DEV_EPS_DEG),
        'rotation_dev_sum_deg': round(sum(devs), 3),
        'width_mm': round(width, 3),
        'density': round(total_area / (width * gate_mm) * 100.0, 3)
        if width > 0.0 else 0.0,
    }
    return summary, pairs


def _sep_translate(g_moving, g_other, axis, sign):
    """最小分离平移：沿 axis('x'/'y')·sign(±1) 二分到贴触 + 1nm 防贴死微抬。

    镜像 ``waist_band._slide_touch`` 的二分机器（lo 恒碰撞 / hi 恒自由 ——
    hi 取 bbox 分离保证界，必自由）：返回 ``(dx, dy, t)``（t = 平移量 mm，
    非负）或 None（该方向 bbox 分离界 ≤ 0，非重合形态）。终点贴触侧 + 1nm，
    shapely 交集严格为空（面积精确 0）。
    """
    mb, ob = g_moving.bounds, g_other.bounds
    if axis == 'y':
        free = (ob[3] - mb[1]) if sign > 0 else (mb[3] - ob[1])
    else:
        free = (ob[2] - mb[0]) if sign > 0 else (mb[2] - ob[0])
    if free <= 0.0:
        return None

    def collides(t):
        moved = translate(g_moving, xoff=sign * t if axis == 'x' else 0.0,
                          yoff=sign * t if axis == 'y' else 0.0)
        return moved.intersection(g_other).area >= COLLIDE_AREA_EPS_MM2

    lo, hi = 0.0, free          # lo 碰撞（当前重合），hi 自由（bbox 分离）
    for _ in range(BISECT_ITERS):
        mid = (lo + hi) / 2.0
        if collides(mid):
            lo = mid
        else:
            hi = mid
    t = hi + SEP_NUDGE_MM
    dx = sign * t if axis == 'x' else 0.0
    dy = sign * t if axis == 'y' else 0.0
    return dx, dy, t


def _slide_west_touch(g_moving, obstacles, t_wall):
    """自当前位沿 ``−x`` 滑到与 ``obstacles`` 首次贴触或 x=0 布头墙（US-005）。

    ``waist_band._slide_touch`` 同款「粗扫定界 + 二分收敛」机器的 −x 向变体
    （可行域非凸，须从当前位起步找**首个**碰撞界）。``obstacles`` 为调用方
    预筛后的滑移路径相关障碍（y 带重叠 + x 可达）；``t_wall`` = 布头墙限
    （滑移量上限，到 x=0 为止）。返回滑移量 t ∈ [0, t_wall]：

    - 当前位已碰撞（残留重合纠缠，pass ③ 未解的必要贴触）→ 0（不可滑，
      交给 residual 口径，不强行撕开）；
    - 全程自由 → ``t_wall``（贴 x=0 布头墙，回收布头空隙）；
    - 否则二分到首个贴触点后回退 1nm（``SEP_NUDGE_MM``，终态与障碍交集
      面积精确 0 —— 与 ``_sep_translate`` 防贴死同口径）。
    """
    def _collides(t):
        moved = translate(g_moving, xoff=-t)
        mb = moved.bounds
        for g2 in obstacles:
            if _bbox_overlaps(mb, g2.bounds) and \
                    moved.intersection(g2).area >= COLLIDE_AREA_EPS_MM2:
                return True
        return False

    if _collides(0.0):
        return 0.0
    t_free, t_hit, t = 0.0, None, 0.0
    while t < t_wall:
        tn = min(t + COMPACT_SCAN_STEP_MM, t_wall)
        if _collides(tn):
            t_hit = tn
            break
        t_free = tn
        t = tn
    if t_hit is None:
        return t_wall                      # 全程自由 → 贴 x=0 布头墙
    a, b = t_free, t_hit                   # a 自由 / b 碰撞（首个碰撞界）
    for _ in range(BISECT_ITERS):
        mid = (a + b) / 2.0
        if _collides(mid):
            b = mid
        else:
            a = mid
    return max(a - SEP_NUDGE_MM, 0.0)      # 贴触位回退 1nm（自由侧）


# --------------------------------------------------------------- 主入口

def polish_layout(placed, pieces_by_id, gate_mm, *, exclude=None, compact=False):
    """确定性后处理主入口（纯函数：不修改入参 ``placed``）。

    Parameters
    ----------
    placed : list[dict]
        ``[{'id', 'rotation', 'translation':[tx,ty]}, ...]`` —— 同 pid 多副本
        按**数组下标**逐实例寻址（绝不 pid 去重，与前端 editStore 同口径）。
    pieces_by_id : dict
        ``{pid: piece_dict}``（intermediate 直查；取原始 polygon = 物理毛版
        轮廓口径，与 /export ``placed_to_world`` 同源）。
    gate_mm : float
        门幅（y ∈ [0, gate]）。
    exclude : dict | None
        ``{'labels': [g码], 'pids': [pid]}`` —— 命中实例永不被移动，仍作为
        障碍参与他人检查（v1 over-conservative：同 pid 全部副本，FR-8）。
    compact : bool
        US-005 压缩回收档（缺省 false）：pass ④ 自布头逐片 −x 滑贴收空隙，
        接受条件 = 全图物理包络 maxX 严格变小（不过则整段回滚 —— additive，
        false 时本段跳过、行为与 US-001 逐字节不变）。

    Returns
    -------
    tuple ``(placed_new, report)``
        placed_new : 无任何 move 时**返回输入 list 原对象**（逐字节不变量）；
            有 move 时为新列表（全量新 dict，未动片字段值不变）。
        report : ``{before, after, moves, residual, excluded, elapsed_sec}``。
    """
    t0 = time.perf_counter()
    gate = float(gate_mm)
    n = len(placed)
    ex_labels = set((exclude or {}).get('labels') or [])
    ex_pids = set((exclude or {}).get('pids') or [])
    excluded = set()
    items = []
    geoms = []
    for i, p in enumerate(placed):
        pid = p['id']
        piece = pieces_by_id.get(pid)
        if piece is None or not piece.get('polygon'):
            raise PolishError(
                f'placed[{i}] pid {pid!r} 不在 pieces_by_id（母版已变更？'
                f'请重新求解/上传）')
        if pid in ex_pids or piece.get('label') in ex_labels:
            excluded.add(i)
        items.append({'id': pid, 'rotation': float(p.get('rotation', 0.0)),
                      'translation': [float(p['translation'][0]),
                                      float(p['translation'][1])]})
        geoms.append(_world_geom(p, pieces_by_id))

    # real 口径密度分母：Σ(原面积 × 副本数)（demand 多副本按出现次数计）。
    multiplicity = Counter(p['id'] for p in placed)
    total_area = 0.0
    for pid, cnt in multiplicity.items():
        piece = pieces_by_id[pid]
        area = piece.get('area_mm2')
        if not area:
            area = Polygon(piece['polygon']).area
        total_area += float(area) * cnt

    before, pairs = _diagnose(geoms, items, total_area, gate)
    width_before = _layout_width(geoms)
    bounds = [g.bounds for g in geoms]
    moves = []

    def _move_ok(idx, geom):
        """逐 move 守卫 ①②③⑤（守卫 ④ pid 守恒结构性成立，出口处终检）。"""
        if idx in excluded:                                   # 守卫⑤ exclude
            return False
        b = geom.bounds
        if b[1] < -GATE_EPS_MM or b[3] > gate + GATE_EPS_MM:  # 守卫① y∈[0,gate]
            return False
        others_max = 0.0
        others_min = 0.0
        for k in range(n):
            if k == idx:
                continue
            others_max = max(others_max, bounds[k][2])
            others_min = min(others_min, bounds[k][0])
        new_width = max(others_max, b[2]) - min(min(others_min, b[0]), 0.0)
        if new_width > width_before + WIDTH_TOL_MM:           # 守卫② 包络不增
            return False
        for k in range(n):                                    # 守卫③ 零新重合
            if k == idx:
                continue
            if _bbox_overlaps(b, bounds[k]) and \
                    geom.intersection(geoms[k]).area > OVERLAP_AREA_EPS_MM2:
                return False
        return True

    def _apply(idx, rot_new, tr_new, geom_new, kind, detail):
        old = items[idx]
        moves.append({
            'index': idx, 'pid': old['id'], 'kind': kind,
            'from': {'rotation': old['rotation'],
                     'translation': list(old['translation'])},
            'to': {'rotation': rot_new, 'translation': list(tr_new)},
            'detail': detail})
        old['rotation'] = rot_new
        old['translation'] = [tr_new[0], tr_new[1]]
        geoms[idx] = geom_new
        bounds[idx] = geom_new.bounds

    # ---- pass ② 去旋转（dev 降序、平手下标；先试基线逐步回退）----
    derot = [i for i in range(n)
             if i not in excluded
             and _rotation_dev(items[i]['rotation']) > DEV_EPS_DEG]
    derot.sort(key=lambda i: (-_rotation_dev(items[i]['rotation']), i))
    for i in derot:
        rot_cur = items[i]['rotation']
        if _rotation_dev(rot_cur) <= DEV_EPS_DEG:
            continue
        local = pieces_by_id[items[i]['id']]['polygon']
        c_local = Polygon(local).centroid
        # 质心锚定：c_world = R(rot)·c_local + t（仿射保质心 ⇒ 世界几何质心即锚）
        c_world = geoms[i].centroid
        obstacles = [k for k in range(n)
                     if k != i and _bbox_overlaps(
                         (bounds[k][0] - NEIGHBOR_MARGIN_MM,
                          bounds[k][1] - NEIGHBOR_MARGIN_MM,
                          bounds[k][2] + NEIGHBOR_MARGIN_MM,
                          bounds[k][3] + NEIGHBOR_MARGIN_MM), bounds[i])]
        placed_move = False
        for target_rot in _derotate_ladder(rot_cur):
            r = math.radians(target_rot)
            c, s = math.cos(r), math.sin(r)
            t0x = c_world.x - (c_local.x * c - c_local.y * s)
            t0y = c_world.y - (c_local.x * s + c_local.y * c)
            g0 = _valid_geometry(_transform_polygon(
                local, target_rot, (t0x, t0y)))
            b0 = g0.bounds
            # 邻域候选：质心锚定原位 + 障碍/门幅棱边对齐（逐轴独立），按
            # (位移, dx, dy) 升序取首个过守卫位（shapely 邻域候选实现自由度）。
            offs = {(0.0, 0.0)}
            for k in obstacles:
                bk = bounds[k]
                for x in (bk[0], bk[2]):
                    offs.add((x - b0[0], 0.0))
                    offs.add((x - b0[2], 0.0))
                for y in (bk[1], bk[3]):
                    offs.add((0.0, y - b0[1]))
                    offs.add((0.0, y - b0[3]))
            offs.add((-b0[0], 0.0))                        # 贴布头 x=0
            offs.add((0.0, -b0[1]))                        # 贴门幅底 y=0
            offs.add((0.0, gate - b0[3]))                  # 贴门幅顶 y=gate
            for dx, dy in sorted(offs, key=lambda o: (math.hypot(o[0], o[1]), o)):
                tr = (t0x + dx, t0y + dy)
                g = translate(g0, xoff=dx, yoff=dy) if (dx or dy) else g0
                if _move_ok(i, g):
                    _apply(i, target_rot, tr, g, 'derotate',
                           f'rot {rot_cur:.2f}→{target_rot:.2f}（dev '
                           f'{_rotation_dev(rot_cur):.2f}→'
                           f'{_rotation_dev(target_rot):.2f}°），'
                           f'质心位移 {math.hypot(dx, dy):.2f}mm')
                    placed_move = True
                    break
            if placed_move:
                break

    # ---- pass ③ 去重叠（穿透深度降序、平手 (i,j)；最小分离 ±y 优先、−x 次之）----
    pairs.sort(key=lambda p: (-p['penetration_mm'], p['i'], p['j']))
    for pair in pairs:
        i, j = pair['i'], pair['j']
        if _pair_stats(geoms[i], geoms[j]) is None:   # 早前 move 已顺带解离
            continue
        for mover, other in ((i, j), (j, i)):          # 一片失败换动另一片
            if mover in excluded:
                continue
            cands = []
            for prio, (axis, sign) in enumerate(
                    (('y', 1.0), ('y', -1.0), ('x', -1.0))):
                sep = _sep_translate(geoms[mover], geoms[other], axis, sign)
                if sep is not None:
                    dx, dy, t = sep
                    cands.append((t, prio, dx, dy))
            done = False
            for t, prio, dx, dy in sorted(cands):      # 最小分离平移优先
                old_tr = items[mover]['translation']
                tr = (old_tr[0] + dx, old_tr[1] + dy)
                g = translate(geoms[mover], xoff=dx, yoff=dy)
                if _move_ok(mover, g):
                    direction = '+y' if prio == 0 else ('−y' if prio == 1 else '−x')
                    _apply(mover, items[mover]['rotation'], tr, g, 'separate',
                           f'与 placed[{other}]（{items[other]["id"]}）分离：'
                           f'{direction} 最小平移 {t:.2f}mm')
                    done = True
                    break
            if done:
                break

    # ---- pass ④ 压缩回收（compact=True；自布头方向逐片 −x 滑贴收空隙）----
    if compact:
        snap_items = [{'id': it['id'], 'rotation': it['rotation'],
                       'translation': list(it['translation'])} for it in items]
        snap_geoms = list(geoms)
        snap_bounds = list(bounds)
        snap_nmoves = len(moves)
        max_x_head = max((b[2] for b in bounds), default=0.0)
        # 自布头方向（minX 升序、平手下标）：左片先贴新位、右片随后贴它 —— 级联
        # 把去旋/分离释放的空隙收进料长（单趟有序扫描即稳定：左侧贴定后不再动）。
        for k in sorted((k for k in range(n) if k not in excluded),
                        key=lambda k: (bounds[k][0], k)):
            t_wall = bounds[k][0]
            if t_wall <= COMPACT_GAIN_EPS_MM:
                continue                 # 已贴布头（或 minX≤0 外凸）：不可再滑
            b_k = bounds[k]
            obstacles = [geoms[m] for m in range(n)
                         if m != k
                         and bounds[m][0] < b_k[2]            # 滑移路径 x 可达
                         and bounds[m][2] > 0.0               # 布头墙左侧不可达
                         and not (bounds[m][3] < b_k[1] or b_k[3] < bounds[m][1])]
            t = _slide_west_touch(geoms[k], obstacles, t_wall)
            if t <= COMPACT_GAIN_EPS_MM:
                continue
            tr = (items[k]['translation'][0] - t, items[k]['translation'][1])
            g = translate(geoms[k], xoff=-t)
            if _move_ok(k, g):
                _apply(k, items[k]['rotation'], tr, g, 'compact',
                       f'−x 滑贴回收空隙 {t:.2f}mm')
        max_x_tail = max((b[2] for b in bounds), default=0.0)
        if not max_x_tail < max_x_head - COMPACT_GAIN_EPS_MM:
            # 包络 maxX 未严格变小：整段回滚（无改进逐字节不变 —— 输出与非
            # compact 档全等，moves/residual 不留孤儿记录）。
            items = snap_items
            geoms = snap_geoms
            bounds = snap_bounds
            del moves[snap_nmoves:]

    # ---- pass ⑤ 报告（终态重算；residual 如实上报不硬凑零）----
    after, final_pairs = _diagnose(geoms, items, total_area, gate)
    residual = [{'kind': 'overlap', 'indices': [p['i'], p['j']],
                 'pids': [items[p['i']]['id'], items[p['j']]['id']],
                 'penetration_mm': round(p['penetration_mm'], 3),
                 'area_mm2': round(p['area_mm2'], 3)} for p in final_pairs]
    residual += [{'kind': 'rotation', 'index': i, 'pid': items[i]['id'],
                  'dev_deg': round(_rotation_dev(items[i]['rotation']), 3)}
                 for i in derot
                 if _rotation_dev(items[i]['rotation']) > DEV_EPS_DEG]
    report = {'before': before, 'after': after, 'moves': moves,
              'residual': residual, 'excluded': sorted(excluded),
              'elapsed_sec': round(time.perf_counter() - t0, 3)}

    if not moves:                       # 无改进：输入 list 原对象逐字节不变
        return placed, report
    if Counter(p['id'] for p in items) != multiplicity:   # 守卫④ 终检
        raise PolishError('pid 多重集守恒失败（内部不变量被破坏）')
    out = [{'id': it['id'], 'rotation': it['rotation'],
            'translation': [it['translation'][0], it['translation'][1]]}
           for it in items]
    return out, report


# --------------------------------------------------------------- 冒烟入口

def _rect_piece(pid, w, h, label='g01', size=28):
    """冒烟/夹具用矩形裁片（schema v2 最小字段）。"""
    return {'pid': pid, 'label': label, 'size': size,
            'polygon': [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]],
            'bbox': [0.0, 0.0, w, h], 'area_mm2': float(w * h), 'n_verts': 4,
            'net_polygon': [], 'internal_lines': [], 'notches': [],
            'grain_line': None}


def _pl(pid, rot, tx, ty):
    """placement 夹具构造。"""
    return {'id': pid, 'rotation': float(rot), 'translation': [float(tx), float(ty)]}


def _world_polygon(pid, pieces_by_id, rot, tr):
    """夹具断言用世界坐标 shapely Polygon（与 _world_geom 同变换口径）。"""
    return Polygon(_transform_polygon(
        pieces_by_id[pid]['polygon'], float(rot), tr))


def _smoke_fixtures() -> bool:
    """合成夹具自检（AC 口径复刻；全部通过返回 True）。"""
    ok = True

    def _check(name, cond, detail=''):
        nonlocal ok
        print(f'  [{name}] {"PASS" if cond else "FAIL"}'
              f'{(" " + detail) if detail else ""}')
        ok = ok and bool(cond)

    # ① 空白旁斜片：单片 25° 居空场 → 回正 dev=0、质心零位移
    pieces = {'g01_30': _rect_piece('g01_30', 300, 100)}
    placed = [_pl('g01_30', 25, 500, 500)]
    out, rep = polish_layout(placed, pieces, 2000.0)
    g0 = _world_polygon('g01_30', pieces, placed[0]['rotation'],
                        placed[0]['translation'])
    g1 = _world_polygon('g01_30', pieces, out[0]['rotation'],
                        out[0]['translation'])
    _check('空白旁斜片', _rotation_dev(out[0]['rotation']) == 0.0
           and rep['after']['overlap_pairs'] == 0
           and g0.centroid.distance(g1.centroid) < 1e-6,
           f'rot={out[0]["rotation"]:.1f} moves={len(rep["moves"])}')

    # ② 可分离重合对：叠 5mm → 交集面积精确 0
    pieces = {'g01_30': _rect_piece('g01_30', 200, 150),
              'g02_30': _rect_piece('g02_30', 200, 150, label='g02')}
    placed = [_pl('g01_30', 0, 100, 100), _pl('g02_30', 0, 100, 245)]
    out, rep = polish_layout(placed, pieces, 1000.0)
    inter = _world_polygon('g01_30', pieces, out[0]['rotation'],
                           out[0]['translation']).intersection(
        _world_polygon('g02_30', pieces, out[1]['rotation'],
                       out[1]['translation']))
    _check('可分离重合对', inter.area == 0.0
           and len(rep['moves']) == 1 and rep['moves'][0]['kind'] == 'separate',
           f'交集面积={inter.area:.3g} 重合对 '
           f'{rep["before"]["overlap_pairs"]}→{rep["after"]["overlap_pairs"]}')

    # ③ 紧密布局：满门幅贴触链叠 2mm（d 余量形态）→ 逐字节不变 + residual 如实
    pieces = {'g01_30': _rect_piece('g01_30', 100, 160),
              'g02_30': _rect_piece('g02_30', 100, 160, label='g02'),
              'g03_30': _rect_piece('g03_30', 100, 160, label='g03')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 98, 0),
              _pl('g03_30', 0, 196, 0)]
    out, rep = polish_layout(placed, pieces, 160.0)
    _check('紧密布局 no-op', out is placed and rep['moves'] == []
           and len(rep['residual']) == 2,
           f'residual={len(rep["residual"])} '
           f'overlap_pairs={rep["after"]["overlap_pairs"]}')

    # ④ 守卫·越门幅：唯一分离方向 +y 越门幅（上下左右全堵）
    pieces = {'g01_30': _rect_piece('g01_30', 200, 120),
              'g02_30': _rect_piece('g02_30', 200, 80, label='g02'),
              'g03_30': _rect_piece('g03_30', 200, 175, label='g03'),
              'g04_30': _rect_piece('g04_30', 600, 200, label='g04')}
    placed = [_pl('g01_30', 0, 600, 880),   # U：顶部贴门幅
              _pl('g02_30', 0, 650, 875),   # L：与 U 叠 5mm
              _pl('g03_30', 0, 650, 700),   # B：堵 −y
              _pl('g04_30', 0, 0, 800)]     # W：堵 −x（左墙）
    out, rep = polish_layout(placed, pieces, 1000.0)
    _check('守卫·越门幅拒绝', out is placed and rep['moves'] == [],
           f'residual={len(rep["residual"])}')

    # ⑤ 守卫·包络增长：唯一空位在 +x 尾部外（rot0 bbox 更宽，全景堵死）
    pieces = {'g01_30': _rect_piece('g01_30', 400, 40),
              'g02_30': _rect_piece('g02_30', 300, 600, label='g02')}
    placed = [_pl('g02_30', 0, 0, 200), _pl('g01_30', 25, 379, 200)]
    out, rep = polish_layout(placed, pieces, 1000.0)
    _check('守卫·包络增长拒绝', out is placed and rep['moves'] == []
           and any(r['kind'] == 'rotation' for r in rep['residual']),
           f'residual_kinds={[r["kind"] for r in rep["residual"]]}')

    # ⑥ 多副本：同 pid 3 副本仅第 2 条需微调（按 index 寻址）
    pieces = {'g01_30': _rect_piece('g01_30', 300, 100)}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g01_30', 25, 600, 600),
              _pl('g01_30', 0, 1200, 0)]
    out, rep = polish_layout(placed, pieces, 2000.0)
    _check('多副本按 index 寻址',
           len(rep['moves']) == 1 and rep['moves'][0]['index'] == 1
           and out[0]['translation'] == placed[0]['translation']
           and out[2]['translation'] == placed[2]['translation']
           and out[2]['rotation'] == placed[2]['rotation'],
           f'moves={[m["index"] for m in rep["moves"]]}')

    # ⑦ 排除集：命中实例零移动、仍作障碍（B 朝 A 方向的 +y 分离被 A 挡下）
    pieces = {'g01_30': _rect_piece('g01_30', 200, 150),
              'g02_30': _rect_piece('g02_30', 200, 150, label='g02'),
              'g03_30': _rect_piece('g03_30', 200, 150, label='g03')}
    placed = [_pl('g01_30', 0, 100, 760),    # A（excluded）
              _pl('g02_30', 0, 100, 460),    # B
              _pl('g03_30', 0, 100, 600)]    # C：与 B 叠 10mm
    out, rep = polish_layout(placed, pieces, 1000.0,
                             exclude={'labels': ['g01']})
    ga = _world_polygon('g01_30', pieces, out[0]['rotation'],
                        out[0]['translation'])
    gb = _world_polygon('g02_30', pieces, out[1]['rotation'],
                        out[1]['translation'])
    gc = _world_polygon('g03_30', pieces, out[2]['rotation'],
                        out[2]['translation'])
    _check('排除集障碍语义',
           out[0]['translation'] == placed[0]['translation']
           and rep['excluded'] == [0]
           and all(m['index'] != 0 for m in rep['moves'])
           and gb.intersection(gc).area == 0.0
           and gb.intersection(ga).area == 0.0,
           f'excluded={rep["excluded"]} '
           f'moves={[m["index"] for m in rep["moves"]]}')

    # ⑧ 确定性：同输入连跑两次全等（elapsed_sec 除外）
    pieces = {'g01_30': _rect_piece('g01_30', 300, 100),
              'g02_30': _rect_piece('g02_30', 200, 150, label='g02')}
    placed = [_pl('g01_30', 25, 100, 100), _pl('g02_30', 15, 280, 180),
              _pl('g01_30', 155, 700, 900)]
    o1, r1 = polish_layout(placed, pieces, 1500.0)
    o2, r2 = polish_layout(placed, pieces, 1500.0)
    r1.pop('elapsed_sec')
    r2.pop('elapsed_sec')
    _check('确定性双跑全等', o1 == o2 and r1 == r2)

    # ⑨ compact 回收（US-005）：横排留 ≥30mm 空隙 → 包络减少 ≥29mm、零新重合
    pieces = {'g01_30': _rect_piece('g01_30', 100, 160),
              'g02_30': _rect_piece('g02_30', 100, 160, label='g02'),
              'g03_30': _rect_piece('g03_30', 100, 160, label='g03')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 130, 0),
              _pl('g03_30', 0, 260, 0)]
    out, rep = polish_layout(placed, pieces, 160.0, compact=True)
    geoms = [_world_polygon(p['id'], pieces, p['rotation'], p['translation'])
             for p in out]
    zero_overlap = all(geoms[i].intersection(geoms[j]).area == 0.0
                       for i in range(3) for j in range(i + 1, 3))
    _check('compact 回收空隙',
           rep['after']['width_mm'] <= rep['before']['width_mm'] - 29.0
           and rep['after']['overlap_pairs'] == 0 and zero_overlap
           and [m['index'] for m in rep['moves']] == [1, 2]
           and all(m['kind'] == 'compact' for m in rep['moves']),
           f'width {rep["before"]["width_mm"]}→{rep["after"]["width_mm"]} '
           f'moves={[m["index"] for m in rep["moves"]]}')

    # ⑩ compact 无空隙可收（US-005）：紧凑链（同 ③）→ 与非 compact 档逐元素相同
    pieces = {'g01_30': _rect_piece('g01_30', 100, 160),
              'g02_30': _rect_piece('g02_30', 100, 160, label='g02'),
              'g03_30': _rect_piece('g03_30', 100, 160, label='g03')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 98, 0),
              _pl('g03_30', 0, 196, 0)]
    o0, r0 = polish_layout(placed, pieces, 160.0)
    o1, r1 = polish_layout(placed, pieces, 160.0, compact=True)
    r0.pop('elapsed_sec')
    r1.pop('elapsed_sec')
    _check('compact 无空隙逐元素相同', o0 == o1 and r0 == r1)
    return ok


def _demo(intermediate_path, n_pieces) -> bool:
    """``--demo``：真实母版几何演示（对齐 prefix ``--pin-demo`` 形态）。

    取 intermediate 前 N 片构造确定性「带病布局」（横排 rot0 片间故意叠 3mm
    制造重合 + 尾部两片 ±25° 斜置制造旋转偏差），跑 polish 打印前后对比与
    move 明细，断言：overlap_pairs 下降、width ≤ before+0.5、密度不降、
    双跑全等。无求解依赖（spyrrow 不参与 —— polish 输入输出全走 placement）。
    """
    with open(intermediate_path, encoding='utf-8') as f:
        doc = json.load(f)
    pieces = doc['pieces'][:max(2, n_pieces)]
    gate = float(doc['gate_mm'])
    pieces_by_id = {p['pid']: p for p in pieces}
    n_flat = max(1, len(pieces) - 2)

    placed = []
    x = 0.0
    for k in range(n_flat):                      # 横排：相邻叠 3mm（同 y 带）
        p = pieces[k]
        rot = 0.0 if k % 2 == 0 else 180.0
        g = _world_geom({'id': p['pid'], 'rotation': rot,
                         'translation': [0.0, 0.0]}, pieces_by_id)
        b = g.bounds
        w = b[2] - b[0]
        if x > 0.0:
            x -= 3.0                             # 故意重合 3mm
        placed.append(_pl(p['pid'], rot, x - b[0], -b[1]))
        x += w
    y_base = gate * 0.6                          # 尾部：两片斜置（空场）
    for off, (p, rot) in enumerate(zip(pieces[n_flat:], (25.0, 155.0))):
        b = _world_geom({'id': p['pid'], 'rotation': rot,
                         'translation': [0.0, 0.0]}, pieces_by_id).bounds
        placed.append(_pl(p['pid'], rot, 50.0 + off * 800.0 - b[0],
                          y_base - b[1]))

    out1, rep = polish_layout(placed, pieces_by_id, gate)
    out2, rep2 = polish_layout(placed, pieces_by_id, gate)
    rep2.pop('elapsed_sec')
    rep_d = {k: v for k, v in rep.items() if k != 'elapsed_sec'}

    def _row(tag, s):
        print(f'  {tag}: 重合对={s["overlap_pairs"]} '
              f'最大穿透={s["max_penetration_mm"]}mm '
              f'重合面积={s["total_overlap_area_mm2"]:.0f}mm² '
              f'斜片={s["rotated_pieces"]} Σ偏差={s["rotation_dev_sum_deg"]}° '
              f'料长={s["width_mm"]}mm 密度={s["density"]:.2f}%')

    print(f'  [demo] {len(placed)} 片（gate={gate:.0f}mm，其中斜置 '
          f'{len(placed) - n_flat} 片）')
    _row('before', rep['before'])
    _row('after ', rep['after'])
    kinds = Counter(m['kind'] for m in rep['moves'])
    print(f'  [demo] moves={len(rep["moves"])}'
          f'（derotate={kinds.get("derotate", 0)} '
          f'separate={kinds.get("separate", 0)}）'
          f' residual={len(rep["residual"])} elapsed={rep["elapsed_sec"]}s')
    for m in rep['moves'][:6]:
        print(f'    - [{m["index"]}] {m["pid"]} {m["kind"]}: {m["detail"]}')
    if len(rep['moves']) > 6:
        print(f'    ...（余 {len(rep["moves"]) - 6} 条）')
    ok = (rep['after']['overlap_pairs'] < rep['before']['overlap_pairs']
          or rep['before']['overlap_pairs'] == 0)
    ok = ok and rep['after']['width_mm'] <= rep['before']['width_mm'] + WIDTH_TOL_MM
    ok = ok and rep['after']['density'] >= rep['before']['density'] - 1e-3
    ok = ok and out1 == out2 and rep_d == rep2
    print(f'  [demo] {"PASS" if ok else "FAIL"}: '
          f'重合下降/料长不增/密度不降/双跑全等')
    return ok


def main(argv=None) -> int:
    """冒烟入口：``python -m materialsorting.nesting_engine.polish``。

    默认合成夹具自检（AC 十项口径：斜片回正/重合分离/紧密 no-op/守卫×2/
    多副本 index 寻址/排除集障碍/确定性双跑/compact 回收/compact 无空隙
    逐元素相同），全过打印 PASS、exit 0。
    ``--demo`` 追加真实母版几何演示（intermediate 前 N 片确定性带病布局 →
    polish 前后对比，形态对齐 prefix ``--pin-demo`` 先例；无 spyrrow 依赖）。
    intermediate 缺失时 ``--demo`` 提示先 commit（默认合成夹具不受影响照常自检）。
    """
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description='polish 编辑排料智能微调引擎冒烟（US-001）')
    ap.add_argument('--intermediate', default=paths.INTERMEDIATE,
                    help='pieces_intermediate.json 路径（--demo 用）')
    ap.add_argument('--demo', action='store_true',
                    help='追加真实母版几何演示（确定性带病布局 → 前后对比）')
    ap.add_argument('--demo-pieces', type=int, default=10,
                    help='--demo 取前 N 片（缺省 10）')
    args = ap.parse_args(argv)

    print('== polish 合成夹具自检（US-001 验收口径）==')
    if not _smoke_fixtures():
        return 1
    if args.demo:
        print('== polish 真实几何演示（--demo）==')
        if not os.path.exists(args.intermediate):
            print(f'ERROR: intermediate 不存在: {args.intermediate}\n'
                  f'  先 commit 母版生成（如 ms-run-config data/configs/'
                  f'5336_coded_really.json --time 5）')
            return 1
        if not _demo(args.intermediate, args.demo_pieces):
            return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
