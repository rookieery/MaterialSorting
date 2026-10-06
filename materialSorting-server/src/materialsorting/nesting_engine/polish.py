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
  **贴附保持的减少旋转**（2026-10-06 重写；前史：2026-10-05「已贴附片跳过
  归位」+ 同日方案 A「压线相交不算贴附」，两版一刀切冻结均在 5156 race 腰头
  成带实勘中暴露误伤）：所有 dev>0 片一律进阶梯（**干净贴附不再冻结** ——
  更小角度同样贴附时必须动，版师手眼可行、引擎不能视而不见）；阶梯 =
  ``_derotate_ladder_fine``（dev ≤ 10° 用 **1° 步进**，5° 步进够不到 −9°/−7°
  这类手眼可行位；降幅 ≥ 0.05° 防浮点噪声孪生角）；候选 = 族 B **四向滑贴
  首触**（质心锚定 + 环形补锚 ±20/±40mm，Alt+左键 attract 语义四向版，滑移
  ≤ 100mm 防跨唛架远跳）+ 族 A 质心锚定/邻域棱对齐（位移升序）；**严格档**
  （干净贴附片，``_snug``）候选位必须自身也贴附（``_attached`` ≤ 0.05mm，
  「更小角度同样贴附才动、动则必贴」，贴附不降级）；宽松档（压线/悬浮片）
  合法位即受、贴附 pass 随后收拢；找不到合格位保持原角留 residual。
  **C 族逃逸兜底**（2026-10-06 derotate-escape：受压片在常规候选全败后，质心/
  原位双锚四向 ``_scan_to_clean`` 扫描到全净位 —— 窄逃逸窗可 ~10mm 且常只在
  原位锚射线上，质心锚与原位锚差 ~2mm 即错过）。永不
  增大旋转（只向基线回退）；
- ③ **去重叠**：重叠对按穿透深度降序（平手按 (i,j) 下标），最小分离平移
  （镜像 ``waist_band._slide_touch`` 的二分滑移机器：从当前重叠位向 +y/−y/−x
  二分到贴触 + 1nm 防贴死微抬），方向优先 ±y、−x 不增料长；一片失败换动
  另一片；都失败记 residual —— **只在「免费」时做**（不增料长、零新重合），
  版师 per_type d 工艺余量语义不受影响（不强行动归零 d 预算内的必要贴触）；
  双 mover 全败后**逃逸兜底**（2026-10-06 separate-escape：``_scan_to_clean``
  四向扫描到全净位 —— 楔形双侧受压下单伙伴最小分离必落第三者）；
- ③½ **贴附**（attach，默认启用，2026-10-05 裁床裁板需求）：重力压实 ——
  west 趟（minX 升序级联，compact 同骨架）+ south 趟（minY 升序镜像）交替
  逐片滑到与障碍或墙（布头 x=0 / 下门幅 y=0）首次贴触 + 1nm 回退，至多
  ``ATTACH_ROUNDS_MAX`` 轮、整轮零 move 早退（势函数 Σ(minX+minY) 严格递减
  保证终止）。纯平移：永不增大旋转、永不新重合（首触即停）；south 不动 x
  ⇒ 包络守卫天然过；贴附即消除该对重合（重合/贴附不互斥）；exclude 片恒作
  障碍（band/prefix 刚性组不破）；
- ④ **压缩回收**（``compact=True`` 才启用，US-005）：自布头方向（minX 升序、
  平手下标）逐片 ``−x`` 滑贴（``_slide_west_touch`` 粗扫+二分到与全图障碍或
  x=0 布头墙首次贴触 + 1nm 回退，镜像 ``waist_band._slide_touch`` 机器）——
  左片先贴、右片随后贴新位，级联把去旋/分离释放的空隙收进料长；**接受条件 =
  全图物理包络 maxX 严格变小**（终检不过整段回滚 —— 无改进逐字节不变，
  compact=true 输出与非 compact 档全等；贴附 west 趟同算法先行后本档通常
  无剩可收，语义保留作兜底）；
- ⑤ **报告**：before/after 七指标（重叠对数/最大穿透/总重合面积/旋转偏差片数/
  Σ偏差/料长/密度）+ moves 逐条明细 + residual（终态重合对 + 旋转残留如实
  上报，不硬凑零）+ excluded + attach_moves（贴附 move 计数）+
  escape_moves（逃逸 move 计数，2026-10-06）+ elapsed_sec；
  density = real 口径 ``Σ(area×multiplicity)/(width×gate)``（原面积，非 erode）。

**逐 move 五道守卫**（任一不过弃该 move，最坏全 no-op）：y∈[0,gate]（2026-10-06
B1：d>0 贴边片毛版出界量按初始位冻结豁免 —— 候选不劣于现状即过，门内片零变化）/
全图物理包络不增（width ≤ width_before + 0.5mm 容差，minX<0 布头外凸同计 —— 包络
是双向的）/ 位移片 vs 全图轮廓零正面积重合（2026-10-06 B2：``collide_polygons``
在场按**碰撞轮廓**（= manifest erode polygon = 前端判红同源）裁决 —— d 预算内
保留压线不误杀；缺省按毛版绝对零重合 = 旧行为；对 d=0 片两口径同严）/
pid 多重集守恒（demand>1 同 pid N 条按**数组下标**逐实例寻址，
绝不 pid 去重 —— 与前端 editStore「同 pid 第 k 次出现 = 第 k 副本」同口径）/
exclude 集片永不被移动（仍作为障碍参与他人检查）。

**无改进时返回输入 list 原对象**（逐字节不变量，LNS 同款哲学：无严格改进
不回写）。确定性：无 RNG、排序平手一律按下标裁决、同输入同输出。

**mirror 镜像片（edit-keyboard US-004，omit-when-false 可选键）**：
``placed`` 条目可带 ``mirror: true``（局部 x 翻转 ``world = R(rot)·diag(−1,1)·p + t``，
与前端 transformPolygon / 后端 export_geometry.apply_transform 同一约定）——
诊断/pass ③分离/pass ④compact 全部按镜像后的正确几何计算（``_world_geom``
与 derotate 共用「local = [(-x, y)] 预处理 + 标准变换」实现，t' 质心补偿公式
不变）；items 重建（compact 快照/出口）omit-when-false 透传 mirror；无改进
路径返回输入 list 原对象（含 mirror）逐字节不变。derotate 基线集 {0°,180°}
不受影响 —— diag(−1,1) 保持 x 轴方向，布纹合法性与 mirror 无关。缺省
False：所有既有路径键集与行为逐字节不变（additive 零回归）。

分层约束：本模块属 ``nesting_engine``，仅 import 标准库 + shapely + 本包兄弟
模块（``constraints`` / ``sparrow_baseline`` / ``waist_band``）+ 父包 ``paths``；
**禁 import web/cli**（AST 守卫在 tests/test_polish.py）。``compact`` 旗标为
US-005 压缩回收档（缺省 false = pass ④ 整段跳过）。**贴附 pass（2026-10-05）
默认启用**：默认微调 = 去旋转（snug 跳过）+ 去重叠 + 贴附 —— 相比 US-001~003
时代，松散布局的默认输出多了贴附聚拢（紧凑布局零 move 时仍返回输入 list
原对象，逐字节不变量不变）。
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
from shapely import prepare as _shapely_prepare


def _hits(ga, gb) -> bool:
    """两几何是否**正面积相交**（prepared 快谓词，2026-10-06）。

    ``intersects 且非 touches``：边/角贴触（面积 0）不算相交，部分重叠与
    **包含**都算 —— ``overlaps()`` 对包含形态返回 False（A∩B=B 违反
    "≠A 且 ≠B"），曾放行整片 containment 叠压（5156 实测 165mm 穿透红对
    31 个）。语义 = 旧 ``intersection().area ≥ COLLIDE_AREA_EPS_MM2`` 的
    布尔化（面积阈值只滤退化窄条，两者在工艺尺度等价）。"""
    return ga.intersects(gb) and not ga.touches(gb)

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
# 滑贴二分次数（2026-10-06 性能分层）：滑贴的粗扫括段 ≤1 步（20mm），
# 24 轮 = 0.3nm 精度已足（分离 pass ③ 终位仍用满精度 40 轮）。
SLIDE_BISECT_ITERS = 24
# 去旋转邻域候选的障碍筛选扩张（mm）：候选只对 bbox 距离在此范围内的片生成
# （远片的对齐位必然远超位移最小候选，剪枝省守卫开销）。
NEIGHBOR_MARGIN_MM = 50.0
# 压缩回收粗扫步长（mm）：``waist_band.CHAIN_SLIDE_STEP_MM`` 同款（−x 滑贴
# 首个碰撞界的定界扫描）。
COMPACT_SCAN_STEP_MM = 20.0
# 压缩回收「包络 maxX 严格变小」判定阈值（mm）：小于此视为数值噪声 → 整段
# 回滚（无改进逐字节不变）。
COMPACT_GAIN_EPS_MM = 1e-6
# 贴附（attach，2026-10-05）轮数上限：west+south 各一趟为一轮；整轮零 move
# 早退 + 势函数 Σ(minX+minY) 严格递减双保险终止（上限兜底最坏耗时）。
ATTACH_ROUNDS_MAX = 3
# 「已贴附」判据（mm）：片到任一其他片距离 ≤ 此值（相交=距离 0，d>0 琥珀
# 工艺贴触也算）或贴住布头/上下门幅边 → 去旋转跳过（贴附优先于旋转）。
# waist_band.CHAIN_GAP_EPS_MM=1.0 同值先例。
ATTACH_SNUG_EPS_MM = 1.0
# 贴附滑移量有效阈值（mm）：小于此视为已贴触/数值噪声，不产生 move
# （COMPACT_GAIN_EPS_MM 同口径独立命名，语义各自锚定）。
ATTACH_GAIN_EPS_MM = 1e-6
# 贴附保持归位（2026-10-06「贴附保持的减少旋转」）：细阶梯角度上限（°）——
# dev ≤ 此值用 1° 步进（5° 步进会漏掉 −9°/−7° 这类手眼可行位，5156 g05_30
# 实勘网格证明），更大偏差维持 5° 步进控成本。
DEROT_FINE_MAX_DEG = 10.0
# 阶梯候选最小有效降幅（°）：小于此视为浮点噪声孪生角（如 dev=10.000014
# 的当前角本身被 discretize 生成为候选），不当归位候选。
DEROT_MIN_GAIN_DEG = 0.05
# 贴附保持接受判据（mm）：严格贴附片的归位候选位距任一邻片/墙 ≤ 此值才算
# 「动则必贴」（四向滑贴首触位天然满足；B 族的唯一接受口径）。
ATTACH_KEEP_EPS_MM = 0.05
# 族 B 四向滑贴的滑移上限（mm）：防跨唛架远跳（贴附语义是就近微调，
# 5156 g08_33 实测 183mm 级换邻居已属边缘，100mm 封顶）。
DEROT_SLIDE_CAP_MM = 100.0
# 严格档分离锚的碰撞邻居上限（个）：质心锚在新角度与邻片微相交时，用
# pass ③ 同款最小分离（四向）生成补锚 —— 手眼可行的中间位几乎都是某条
# 最小分离向量（5156 实勘：g05_30 需 (0,+5)、g05_36 需 (+5,−30) 级锚）。
DEROT_SEP_COLLIDERS = 3
# 族 B 小步进锚（mm）：质心锚无碰撞时口袋里仍可能有 (±5/±10) 级中间位
# （分离锚无从生成 —— 无碰撞可分离），补轴对小步进覆盖。
DEROT_NUDGE_ANCHORS = ((5.0, 0.0), (-5.0, 0.0), (0.0, 5.0), (0.0, -5.0))
# 分离补锚的分量上限（mm）：最小分离向量可能巨大（远处碰撞邻居的 bbox 分离
# 界），超出贴附语义的就地微调范围一律丢弃（5156 实勘有效锚 ≤ ~70mm 级）。
DEROT_SEP_MAX_MM = 150.0
# 归位角度预算（片×角试验数，两巡合计）：确定性全局封顶，防大文件最坏情
# 形（几十个顽固片 × 19 角 × 多锚）拖爆 5s 预算；耗尽后该片保持原角留
# residual（如实上报）。
DEROT_ANGLE_BUDGET = 4000
# 族 A 棱对齐候选的障碍数上限（个）：按 bbox 距离取最近若干，远片对齐位
# 位移必大、按位移升序永轮不到 —— 纯守卫开销削减。
DEROT_OFFSET_OBSTACLES = 8
# 分离补锚的二分轮数：锚点只是滑贴起点（非终位），~0.01mm 级进度足够
# （pass ③ 终位分离仍用满精度 BISECT_ITERS）—— cProfile 实测 sep 锚生
# 成占大头（5810 次 × 40 轮），降到 14 轮省 ~2/3。
DEROT_SEP_ITERS = 10
# 逃逸扫描（derotate-escape / separate-escape，2026-10-06）：形状级采样步长（mm）。
# 干净窗可窄于 _slide_axis_touch 的 20mm 粗扫（3069 g09_29 实勘逃逸窗 ~10mm 宽，
# 20mm 粗扫与 bbox 事件扫描均漏检 —— 首触语义假设自由区单调，逃逸语义的干净窗
# 由障碍形状决定、可任意窄）—— 10mm 形状采样 + 二分收敛左边界；窄于此步长的窗
# 仍会漏（残差上限，如实上报 residual 不硬凑）。
ESCAPE_SCAN_STEP_MM = 10.0
# 逃逸扫描平移上限（mm）：与 DEROT_SLIDE_CAP_MM 同语义（就近微调、防跨唛架远跳）。
ESCAPE_SCAN_CAP_MM = 100.0
# 逃逸扫描全局预算（次，两巡合计）：确定性封顶防大文件最坏情形（3069 实测
# 137 片 / 1551 次扫描 / 命中 1，耗时 +24%），耗尽后不再扫、留 residual。
ESCAPE_SCAN_BUDGET = 4000
# 分离二巡（③′，2026-10-06 B4）重合对数上限：脏区重扫的确定性成本封顶（穿透
# 降序取前 N）—— 零 move 时不产生任何开销，超限对留 residual 如实上报。
SEP2_PAIR_CAP = 400


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


def _derotate_ladder_fine(rot: float) -> list:
    """贴附保持归位的候选角阶梯（2026-10-06「贴附保持的减少旋转」）。

    与 ``_derotate_ladder`` 同约束（只取最近基线一侧、dev 严格下降、
    (新dev, 角度) 升序先试基线），差异：dev ≤ ``DEROT_FINE_MAX_DEG`` 用
    1° 步进（原 5° 步进会漏掉 −9°/−7° 这类手眼可行位 —— 5156 g05_30
    实勘：网格搜索证明减 1°+微移+滑贴可贴附，5° 阶梯永远够不到）；
    且要求降幅 ≥ ``DEROT_MIN_GAIN_DEG``，防浮点噪声孪生角（dev=10.000014
    的当前角被 discretize 生成）混进候选导致「零降幅归位」假成功。dev≤0
    返回空。
    """
    r = float(rot) % 360.0
    dev = _rotation_dev(r)
    if dev <= DEV_EPS_DEG:
        return []
    base = _nearest_baseline(r)
    # 阈值带容差：dev=10.000014 级浮点噪声不得把片踢回 5° 粗步进
    # （5156 g05_30 实勘：恰好卡在门外、−9° 可行位永远够不到）。
    step = 1.0 if dev <= DEROT_FINE_MAX_DEG + DEROT_MIN_GAIN_DEG else 5.0
    cands = {(0.0, round(base % 360.0, 2))}
    k = 1
    while k * step < dev - 1e-9:
        for a in (round((base - k * step) % 360.0, 2),
                  round((base + k * step) % 360.0, 2)):
            cands.add((_rotation_dev(a), a))
        k += 1
    return [a for d, a in sorted(cands) if d < dev - DEROT_MIN_GAIN_DEG]


def _world_collide(placement, pieces_by_id, collide_polygons):
    """placement → 碰撞口径世界几何（``collide_polygons`` 命中 pid 用腐蚀轮廓，
    未命中返回 None = 回退毛版 —— 守卫最严方向）。

    ``collide_polygons``（2026-10-06 B2「压线收敛」）= web 层经 ``build_pid_meta``
    同一管线产出的 per-pid 局部腐蚀轮廓（= manifest ``polygon`` = 前端判红单一
    真相源；d=0 片 web 侧直接传毛版，避免 clean 抽稀噪声）。变换与
    ``_world_geom`` 完全同款（平移/旋转/镜像与腐蚀可交换，镜像同 ``x→−x``
    预处理）。缺省（``collide_polygons=None``）调用方不触本函数 —— 守卫③与
    逃逸脏判据走毛版绝对零重合（旧行为，零回归）。
    """
    if not collide_polygons:
        return None
    lc = collide_polygons.get(placement['id'])
    if lc is None:
        return None
    if placement.get('mirror') is True:
        lc = [(-x, y) for x, y in lc]
    return _valid_geometry(_transform_polygon(
        lc, float(placement.get('rotation', 0.0)),
        placement.get('translation', (0.0, 0.0))))


def _world_geom(placement, pieces_by_id):
    """placement → 物理毛版轮廓 shapely 几何（世界系；与 /export 同口径：
    ``pieces_by_id`` 原始 polygon 施加 rotation+translation，非 eroded）。

    mirror（edit-keyboard US-004）：``placement.get('mirror') is True`` → 局部
    x 先取负预处理（``local = [(-x, y)]``）再走标准 ``_transform_polygon``，
    等价 ``R(rot)·diag(−1,1)·p + t``（与前端 transformPolygon / 后端
    apply_transform 同一约定，缺省 False 逐字节不变）。
    """
    piece = pieces_by_id.get(placement['id'])
    if piece is None or not piece.get('polygon'):
        raise PolishError(
            f"placed pid {placement['id']!r} 不在 pieces_by_id（母版已变更？"
            f"请重新求解/上传）")
    local = piece['polygon']
    if placement.get('mirror') is True:
        local = [(-x, y) for x, y in local]
    return _valid_geometry(_transform_polygon(
        local, float(placement.get('rotation', 0.0)),
        placement.get('translation', (0.0, 0.0))))


def _rebuild_item(it):
    """items 条目 → 出口/快照重建 dict（US-004 mirror omit-when-false 透传）。

    compact 快照与最终出口共用：``{id, rotation, translation}`` 逐字段重建 +
    ``mirror: True`` 只在镜像片携带（缺省无键 —— 与前端 PlacedItem 序列化
    「有镜像才带键」同口径，恒发 mirror:false 会红掉前端精确锁键集用例）。
    """
    out = {'id': it['id'], 'rotation': it['rotation'],
           'translation': [it['translation'][0], it['translation'][1]]}
    if it.get('mirror') is True:
        out['mirror'] = True
    return out


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


def _sep_translate(g_moving, g_other, axis, sign, iters=None):
    """最小分离平移：沿 axis('x'/'y')·sign(±1) 二分到贴触 + 1nm 防贴死微抬。

    镜像 ``waist_band._slide_touch`` 的二分机器（lo 恒碰撞 / hi 恒自由 ——
    hi 取 bbox 分离保证界，必自由）：返回 ``(dx, dy, t)``（t = 平移量 mm，
    非负）或 None（该方向 bbox 分离界 ≤ 0，非重合形态）。终点贴触侧 + 1nm，
    shapely 交集严格为空（面积精确 0）。``iters`` 可降精度（锚点生成只要
    ~0.01mm 级、pass ③ 终位要满精度，2026-10-06 性能分层）。
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
        return _hits(moved, g_other)

    lo, hi = 0.0, free          # lo 碰撞（当前重合），hi 自由（bbox 分离）
    for _ in range(BISECT_ITERS if iters is None else iters):
        mid = (lo + hi) / 2.0
        if collides(mid):
            lo = mid
        else:
            hi = mid
    t = hi + SEP_NUDGE_MM
    dx = sign * t if axis == 'x' else 0.0
    dy = sign * t if axis == 'y' else 0.0
    return dx, dy, t


def _slide_axis_touch(g_moving, obstacles, t_wall, axis, sign):
    """自当前位沿 ``axis('x'/'y')·sign`` 滑到与 ``obstacles`` 首次贴触或墙。

    ``waist_band._slide_touch`` 同款「粗扫定界 + 二分收敛」机器的方向参数化
    变体（``_slide_west_touch`` 的通用化，west = ('x', −1)、south = ('y', −1)；
    可行域非凸，须从当前位起步找**首个**碰撞界）。``obstacles`` 为调用方预筛
    后的滑移路径相关障碍（正交轴带重叠 + 滑移轴可达）；``t_wall`` = 墙限
    （滑移量上限，west 到 x=0 布头墙 / south 到 y=0 下门幅）。返回滑移量
    t ∈ [0, t_wall]：

    - 当前位已碰撞（残留重合纠缠，pass ③ 未解的必要贴触）→ 0（不可滑，
      交给 residual 口径，不强行撕开）；
    - 全程自由 → ``t_wall``（贴墙，回收墙侧空隙）；
    - 否则二分到首个贴触点后回退 1nm（``SEP_NUDGE_MM``，终态与障碍交集
      面积精确 0 —— 与 ``_sep_translate`` 防贴死同口径）。
    """
    def _collides(t):
        moved = translate(g_moving,
                          xoff=sign * t if axis == 'x' else 0.0,
                          yoff=sign * t if axis == 'y' else 0.0)
        mb = moved.bounds
        for g2 in obstacles:
            if _bbox_overlaps(mb, g2.bounds) and _hits(moved, g2):
                return True
        return False

    if _collides(0.0):
        return 0.0
    # 跳过必自由区（2026-10-06 性能）：多边形接触必以 bbox 重叠为前提 ——
    # 直达首个障碍的 bbox 平面（或墙），免 20mm 盲扫长滑（自由滑 6000mm 到
    # 布头原需 300 步 collides）。任一障碍已 bbox 重叠（gap≤0，互锁非凸常
    # 态）则退回 0 起全扫。
    b_start = g_moving.bounds
    jump = t_wall
    for g2 in obstacles:
        bm = g2.bounds
        if axis == 'x':
            if bm[3] < b_start[1] or b_start[3] < bm[1]:
                continue
            gap = (b_start[0] - bm[2]) if sign < 0 else (bm[0] - b_start[2])
        else:
            if bm[2] < b_start[0] or b_start[2] < bm[0]:
                continue
            gap = (b_start[1] - bm[3]) if sign < 0 else (bm[1] - b_start[3])
        if gap <= 0.0:
            jump = 0.0
            break
        if gap < jump:
            jump = gap
    t_free, t_hit, t = max(jump - 1e-9, 0.0), None, min(jump, t_wall)
    while t < t_wall:
        tn = min(t + COMPACT_SCAN_STEP_MM, t_wall)
        if _collides(tn):
            t_hit = tn
            break
        t_free = tn
        t = tn
    if t_hit is None:
        return t_wall                      # 全程自由 → 贴墙
    a, b = t_free, t_hit                   # a 自由 / b 碰撞（首个碰撞界）
    for _ in range(SLIDE_BISECT_ITERS):
        mid = (a + b) / 2.0
        if _collides(mid):
            b = mid
        else:
            a = mid
    return max(a - SEP_NUDGE_MM, 0.0)      # 贴触位回退 1nm（自由侧）


def _slide_west_touch(g_moving, obstacles, t_wall):
    """自当前位沿 ``−x`` 滑到首次贴触或 x=0 布头墙（US-005；通用机器的 −x 特化）。

    薄兼容入口：``_slide_axis_touch`` 通用化前的历史签名（compact 站点与
    既有测试引用），行为逐字节不变。
    """
    return _slide_axis_touch(g_moving, obstacles, t_wall, 'x', -1.0)


def _scan_to_clean(g, idx, geoms, bounds, gate, axis, sign, cap,
                   y_hi_slack=0.0, y_lo_slack=0.0, cg=None, cgeoms_arr=None):
    """自受压位沿 ``axis('x'/'y')·sign(±1)`` 扫描首个「对全图零正面积重合」平移位。

    逃逸原语（2026-10-06，derotate-escape / separate-escape 兜底）：与
    ``_slide_axis_touch`` 的「首触」语义互为对偶 —— 那里起点必净、粗扫 20mm 安全
    （自由区单调）；本原语**起点可以是受压态**，且干净窗可窄于粗扫步长（3069
    g09_29 实勘：5° 受压条片在 4° 台阶的 −x 逃逸窗仅 ~10mm 宽，20mm 粗扫与
    bbox 事件扫描均漏检），必须形状级 ``ESCAPE_SCAN_STEP_MM`` 采样。返回首个
    干净平移量 t（+ ``SEP_NUDGE_MM``；首净点天然 ≈ 贴触位，「动则必贴」语义
    不破），无干净窗 / 出门幅返回 None，起点已净返回 0。确定性：固定步长
    采样 + ``SLIDE_BISECT_ITERS`` 轮二分，无 RNG。

    ``y_hi_slack``/``y_lo_slack``（2026-10-06 B1）：该片毛版初始出界余量 ——
    门幅脏判据与限幅同款「不得比现状更出界」规则（d=0 片恒 0 = 旧行为）。
    ``cg``/``cgeoms_arr``（2026-10-06 B2）：碰撞口径几何（缺省 None = 用毛版
    ``g``/``geoms``，旧行为）——「全净位」按碰撞轮廓裁决，d 预算内压线不算脏。
    """
    n = len(geoms)
    cg_eff = g if cg is None else cg
    cgs = geoms if cgeoms_arr is None else cgeoms_arr

    def _dirty(t):
        moved = translate(g, xoff=sign * t if axis == 'x' else 0.0,
                          yoff=sign * t if axis == 'y' else 0.0)
        cmoved = translate(cg_eff, xoff=sign * t if axis == 'x' else 0.0,
                           yoff=sign * t if axis == 'y' else 0.0)
        b = moved.bounds
        if b[1] < -y_lo_slack - GATE_EPS_MM \
                or b[3] > gate + y_hi_slack + GATE_EPS_MM:
            return True
        for k in range(n):
            if k == idx:
                continue
            if _bbox_overlaps(b, bounds[k]) and _hits(cmoved, cgs[k]) \
                    and cmoved.intersection(cgs[k]).area > OVERLAP_AREA_EPS_MM2:
                return True
        return False

    if not _dirty(0.0):
        return 0.0
    if axis == 'y':                       # 门幅限幅（出门幅即脏；B1 余量同口径）
        cap = min(cap, (gate + y_hi_slack - g.bounds[3]) / sign if sign > 0
                  else (g.bounds[1] + y_lo_slack) / -sign)
    t_free = None
    t = ESCAPE_SCAN_STEP_MM
    while t <= cap:
        if not _dirty(t):
            t_free = t
            break
        t += ESCAPE_SCAN_STEP_MM
    if t_free is None:
        return None
    lo, hi = t_free - ESCAPE_SCAN_STEP_MM, t_free   # lo 脏（含 0）/ hi 净
    for _ in range(SLIDE_BISECT_ITERS):
        mid = (lo + hi) / 2.0
        if _dirty(mid):
            lo = mid
        else:
            hi = mid
    return hi + SEP_NUDGE_MM


# --------------------------------------------------------------- 主入口

def polish_layout(placed, pieces_by_id, gate_mm, *, exclude=None, compact=False,
                  collide_polygons=None):
    """确定性后处理主入口（纯函数：不修改入参 ``placed``）。

    Parameters
    ----------
    placed : list[dict]
        ``[{'id', 'rotation', 'translation':[tx,ty], 'mirror'?: true}, ...]``
        —— 同 pid 多副本按**数组下标**逐实例寻址（绝不 pid 去重，与前端
        editStore 同口径）；``mirror`` 为 omit-when-false 可选键（US-004：
        局部 x 翻转，出口同口径透传，缺省/False 与无该键逐字节相同）。
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
    collide_polygons : dict | None
        ``{pid: 局部腐蚀轮廓}``（2026-10-06 B2「压线收敛」，缺省 None = 旧行为
        逐字节不变）：web 层经 ``build_pid_meta`` 同一管线产出（= manifest
        ``polygon`` = 前端判红单一真相源；d=0 片传毛版本身）。命中 pid 的守卫③
        与逃逸脏判据按**碰撞轮廓零重合**裁决 —— d 预算内的保留压线不再误杀
        候选（与 sparrow 自身合法性同口径），对 d=0 片（碰撞轮廓 = 毛版）拒得
        与旧版同严；pid 未命中回退毛版（最严方向）。诊断/pass③ 配对与报告
        七指标仍是毛版口径（压线/穿透数值语义不变）。

    Returns
    -------
    tuple ``(placed_new, report)``
        placed_new : 无任何 move 时**返回输入 list 原对象**（逐字节不变量）；
            有 move 时为新列表（全量新 dict，未动片字段值不变）。
        report : ``{before, after, moves, residual, excluded, attach_moves,
            escape_moves, elapsed_sec}``（``attach_moves`` = 贴附 pass move 计数，
            2026-10-05；``escape_moves`` = 逃逸兜底 move 计数，2026-10-06）。
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
        # US-004：mirror omit-when-false 透传（items 内部与出口一致 —— mirror 只在
        # True 时带键，缺省/False 与旧键集逐字节相同）。
        item = {'id': pid, 'rotation': float(p.get('rotation', 0.0)),
                'translation': [float(p['translation'][0]),
                                float(p['translation'][1])]}
        if p.get('mirror') is True:
            item['mirror'] = True
        items.append(item)
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
    # 守卫① 门幅出界余量（2026-10-06 B1「压线收敛」）：sparrow 只约束 erode 轮廓，
    # d>0 贴边片的毛版可合法出界 ~d 毫米（882 实勘 g02_29 y∈[1725,1755]）——旧
    # y∈[0,gate] 硬卡使这类片**任何**候选（含纯水平移动）都被判死、全程冻结。
    # 按初始位冻结「已出界量」，候选不得比现状更出界（单调不劣化：门内片仍然
    # 一步出不去；出界片可在同等出界量内活动，往里挪自然放行）。d=0 布局
    # slack≡0，与旧判定逐字节相同。
    gate_hi_slack = [max(0.0, b[3] - gate) for b in bounds]
    gate_lo_slack = [max(0.0, -b[1]) for b in bounds]
    moves = []
    touched = set()          # 被动过的片（②′ 脏区门控：只重试环境变过的片）
    # 逃逸兜底（2026-10-06）：重合在案片集合（初始诊断一次性计算 —— 守卫③碰撞
    # 口径保证碰撞重合只减不增（毛版压线可在 d 预算内新增），静态集是保守超集；
    # 用于 C 族触发门）+ 全局扫描预算/命中计数（derotate-escape 与
    # separate-escape 共享）。
    pressed = {_ix for _p in pairs for _ix in (_p['i'], _p['j'])}
    escape_scan_budget = ESCAPE_SCAN_BUDGET
    escape_moves = 0
    # 碰撞口径几何（2026-10-06 B2）：collide_polygons 缺省 → cgeoms 与 geoms
    # 同引用，守卫③/逃逸自动退回毛版绝对零重合（旧行为）；命中 pid 用腐蚀
    # 轮廓（web 层 build_pid_meta 同一管线），未命中 pid 回退毛版（最严方向）。
    cgeoms = geoms
    if collide_polygons:
        cgeoms = []
        for _k, _p in enumerate(placed):
            _cg = _world_collide(_p, pieces_by_id, collide_polygons)
            cgeoms.append(geoms[_k] if _cg is None else _cg)
    # 全图几何预制备（shapely prepared predicate，2026-10-06 性能）：后续对
    # geoms[k] 的 overlaps/intersects 布尔判定走空间索引快路径（贴附保持
    # 归位引入海量谓词调用后，intersection().area 28µs/次成热点）。幂等
    # in-place，不改几何值；_apply 落位的新几何同样补制备。
    for _g in geoms:
        _shapely_prepare(_g)
    if cgeoms is not geoms:
        for _g in cgeoms:
            _shapely_prepare(_g)

    # 守卫② 包络的 O(1) 加速缓存（2026-10-06 贴附保持归位引入海量 _move_ok
    # 调用后，逐次 O(n) 扫 maxX/minX 成为热点）：全图 bounds maxX 前两大 /
    # minX 前两小，「他人极值」= 跳过自己的第一项。_apply 落位后 O(n) 重建
    # （move 数量级 ~数百，重建可忽略）。
    _env_max2 = []
    _env_min2 = []

    def _rebuild_env():
        nonlocal _env_max2, _env_min2
        _env_max2 = sorted(((bounds[k][2], k) for k in range(n)),
                           reverse=True)[:2]
        _env_min2 = sorted((bounds[k][0], k) for k in range(n))[:2]

    _rebuild_env()

    def _others_max_x(idx):
        for v, k in _env_max2:
            if k != idx:
                return v
        return 0.0

    def _others_min_x(idx):
        for v, k in _env_min2:
            if k != idx:
                return v
        return 0.0

    def _move_ok(idx, geom, cgeom=None):
        """逐 move 守卫 ①②③⑤（守卫 ④ pid 守恒结构性成立，出口处终检）。

        守卫③（2026-10-06 B2）：候选位对全图**碰撞轮廓**零正面积重合 ——
        ``cgeom``/``cgeoms`` 为碰撞口径几何（``collide_polygons`` 缺省时与毛版
        同引用 = 旧行为；pid 未命中亦回退毛版）。d 预算内保留压线不再误杀
        候选（与 sparrow 自身合法性同口径），对 d=0 片（碰撞轮廓 = 毛版）拒得
        与旧版同严。bbox 预筛仍用毛版 bounds（超集，安全）。"""
        if idx in excluded:                                   # 守卫⑤ exclude
            return False
        b = geom.bounds
        if b[1] < -gate_lo_slack[idx] - GATE_EPS_MM \
                or b[3] > gate + gate_hi_slack[idx] + GATE_EPS_MM:  # 守卫①（B1 出界余量）
            return False
        new_width = max(_others_max_x(idx), b[2]) \
            - min(min(_others_min_x(idx), b[0]), 0.0)
        if new_width > width_before + WIDTH_TOL_MM:           # 守卫② 包络不增
            return False
        cg = geom if cgeom is None else cgeom
        for k in range(n):                                    # 守卫③（B2 碰撞口径）
            if k == idx:
                continue
            if _bbox_overlaps(b, bounds[k]) and _hits(cg, cgeoms[k]) \
                    and cg.intersection(cgeoms[k]).area > OVERLAP_AREA_EPS_MM2:
                return False
        return True

    def _apply(idx, rot_new, tr_new, geom_new, kind, detail, cgeom_new=None):
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
        cgeoms[idx] = geom_new if cgeom_new is None else cgeom_new
        bounds[idx] = geom_new.bounds
        touched.add(idx)
        _shapely_prepare(geom_new)
        if cgeoms[idx] is not geom_new:
            _shapely_prepare(cgeoms[idx])
        _rebuild_env()

    def _snug(i):
        """片 i 是否**严格贴附**（干净贴附分类器，2026-10-05 引入、2026-10-06
        转职）：与任一其他片**干净贴触**（距离 ≤ ``ATTACH_SNUG_EPS_MM`` 且交
        面积 ≤ ``OVERLAP_AREA_EPS_MM2``）或贴住布头/上下门幅边 → True。

        2026-10-05 曾用作「已贴附跳过归位」的一刀切冻结；同日方案 A 收紧
        （压线相交不算贴附）；**2026-10-06 起不再冻结任何片** —— 命中者改作
        **严格档**：归位候选位必须自身也贴附（``_attached``，贴附不降级），
        落实「更小角度同样贴附才动、动则必贴」；压线/悬浮片走宽松档（合法位
        即可，贴附 pass 随后收拢）。"""
        b = bounds[i]
        gi = geoms[i]
        touching = (b[0] <= ATTACH_SNUG_EPS_MM          # 贴布头（含外凸）
                    or b[1] <= ATTACH_SNUG_EPS_MM       # 贴下门幅
                    or b[3] >= gate - ATTACH_SNUG_EPS_MM)  # 贴上门幅
        for k in range(n):
            if k == i:
                continue
            if not _bbox_overlaps(
                    (b[0] - ATTACH_SNUG_EPS_MM, b[1] - ATTACH_SNUG_EPS_MM,
                     b[2] + ATTACH_SNUG_EPS_MM, b[3] + ATTACH_SNUG_EPS_MM),
                    bounds[k]):
                continue
            gk = geoms[k]
            if _hits(gi, gk) and \
                    gi.intersection(gk).area > OVERLAP_AREA_EPS_MM2:
                return False         # 压线相交 ≠ 干净贴附 → 宽松档
            if not touching and gi.distance(gk) <= ATTACH_SNUG_EPS_MM:
                touching = True
        return touching

    def _attached(g, i):
        """候选位 g 是否**已贴附**（贴附保持接受判据，2026-10-06）：距任一
        其他片 ≤ ``ATTACH_KEEP_EPS_MM``，或贴住布头/下/上门幅（同阈值）。"""
        b = g.bounds
        if b[0] <= ATTACH_KEEP_EPS_MM or b[1] <= ATTACH_KEEP_EPS_MM \
                or b[3] >= gate - ATTACH_KEEP_EPS_MM:
            return True
        be = (b[0] - ATTACH_KEEP_EPS_MM, b[1] - ATTACH_KEEP_EPS_MM,
              b[2] + ATTACH_KEEP_EPS_MM, b[3] + ATTACH_KEEP_EPS_MM)
        for k in range(n):
            if k == i:
                continue
            if _bbox_overlaps(be, bounds[k]) \
                    and g.distance(geoms[k]) <= ATTACH_KEEP_EPS_MM:
                return True
        return False

    def _escape_ok(idx, g_from, tr_from, rot_new, detail, require_attached=False,
                   cg_from=None):
        """逃逸兜底（2026-10-06，derotate-escape / separate-escape 共享闭包）：
        自 ``g_from`` 四向（±y 优先、−x 次之，+x 由包络守卫自然把关）扫描到
        全净位，过守卫即落位返回 True。方向序与 pass ③ 分离优先级同款；确定性
        （固定步长采样 + 二分）；全局 ``escape_scan_budget`` 封顶。仅作为常规
        候选全败后的兜底调用 —— 既有成功路径的 move 序列不受扰动。"""
        nonlocal escape_moves, escape_scan_budget
        for axis, sign in (('y', 1.0), ('y', -1.0), ('x', -1.0), ('x', 1.0)):
            if escape_scan_budget <= 0:
                break
            escape_scan_budget -= 1
            t = _scan_to_clean(g_from, idx, geoms, bounds, gate, axis, sign,
                               ESCAPE_SCAN_CAP_MM,
                               y_hi_slack=gate_hi_slack[idx],
                               y_lo_slack=gate_lo_slack[idx],
                               cg=cg_from, cgeoms_arr=cgeoms)
            if t is None or t <= ATTACH_GAIN_EPS_MM:
                continue
            g = translate(g_from, xoff=sign * t if axis == 'x' else 0.0,
                          yoff=sign * t if axis == 'y' else 0.0)
            cg = g if cg_from is None else translate(
                cg_from, xoff=sign * t if axis == 'x' else 0.0,
                yoff=sign * t if axis == 'y' else 0.0)
            if not _move_ok(idx, g, cg) \
                    or (require_attached and not _attached(g, idx)):
                continue
            tr = (tr_from[0] + (sign * t if axis == 'x' else 0.0),
                  tr_from[1] + (sign * t if axis == 'y' else 0.0))
            d = '−x' if (axis, sign) == ('x', -1.0) else (
                '−y' if (axis, sign) == ('y', -1.0) else (
                    '+x' if axis == 'x' else '+y'))
            _apply(idx, rot_new, tr, g,
                   'derotate-escape'
                   if abs(rot_new - items[idx]['rotation']) > 1e-9
                   else 'separate-escape',
                   f'{detail}，{d}逃逸 {t:.2f}mm', cgeom_new=cg)
            escape_moves += 1
            return True
        return False

    def _try_apply(i, target_rot, tr, g, how, rot_cur, cg=None):
        """接受一个归位候选（守卫外的高层包装：记账 detail + _apply）。"""
        old_tr = items[i]['translation']
        _apply(i, target_rot, tr, g, 'derotate',
               f'rot {rot_cur:.2f}→{target_rot:.2f}（dev '
               f'{_rotation_dev(rot_cur):.2f}→{_rotation_dev(target_rot):.2f}°），'
               f'{how}位移 {math.hypot(tr[0] - old_tr[0], tr[1] - old_tr[1]):.2f}mm',
               cgeom_new=cg)

    def _slide_anchor_ok(i, ga, ta, cga=None):
        """族 B：自锚点 ga 四向（−x/−y/+x/+y）滑贴到首触取候选 —— Alt+左键
        attract 语义的四向版（贴附方向可能在东/北侧，west/south 重力模型够不
        着）。到位即天然贴附；滑移上限 ``DEROT_SLIDE_CAP_MM``（防跨唛架远
        跳）。返回首个「守卫全过 + 贴附」位，无则 None。"""
        # 锚点级碰撞预检（2026-10-06 性能）：锚位与任一邻片正面积相交时四个
        # 方向的 collides(0) 必全真（t=0 早退），一次判定省 4 次滑贴全程。
        ba0 = ga.bounds
        for m in range(n):
            if m == i:
                continue
            if _bbox_overlaps(ba0, bounds[m]) and _hits(ga, geoms[m]):
                return None
        ba = ga.bounds
        for axis, sign in (('x', -1.0), ('y', -1.0), ('x', 1.0), ('y', 1.0)):
            if axis == 'x':
                wall = ba[0] if sign < 0 else DEROT_SLIDE_CAP_MM
            else:
                wall = min(gate - ba[3], DEROT_SLIDE_CAP_MM) if sign > 0 \
                    else ba[1]
            wall = min(wall, DEROT_SLIDE_CAP_MM)
            if wall <= ATTACH_GAIN_EPS_MM:
                continue
            reach = DEROT_SLIDE_CAP_MM
            obst = []
            for m in range(n):
                if m == i:
                    continue
                bm = bounds[m]
                if axis == 'x':
                    if bm[3] < ba[1] or ba[3] < bm[1]:
                        continue
                    if bm[2] < ba[0] - reach or bm[0] > ba[2] + reach:
                        continue
                else:
                    if bm[2] < ba[0] or ba[2] < bm[0]:
                        continue
                    if bm[3] < ba[1] - reach or bm[1] > ba[3] + reach:
                        continue
                obst.append(geoms[m])
            t = _slide_axis_touch(ga, obst, wall, axis, sign)
            if t <= ATTACH_GAIN_EPS_MM:
                continue
            g = translate(ga, xoff=sign * t if axis == 'x' else 0.0,
                          yoff=sign * t if axis == 'y' else 0.0)
            cg = g if cga is None else translate(
                cga, xoff=sign * t if axis == 'x' else 0.0,
                yoff=sign * t if axis == 'y' else 0.0)
            if _move_ok(i, g, cg) and _attached(g, i):
                tr = (ta[0] + (sign * t if axis == 'x' else 0.0),
                      ta[1] + (sign * t if axis == 'y' else 0.0))
                d = '−x' if (axis, sign) == ('x', -1.0) else \
                    ('−y' if (axis, sign) == ('y', -1.0) else
                     ('+x' if axis == 'x' else '+y'))
                return tr, g, cg, f'{d}滑贴'
        return None

    # ---- pass ②/②′ 去旋转（2026-10-06「贴附保持的减少旋转」重写）----
    # dev 降序（平手下标）。所有 dev>0 片一律进阶梯（干净贴附不再一刀切冻
    # 结）；严格贴附片（_snug）候选必须自身贴附（贴附不降级）；压线/悬浮片
    # 宽松档（合法位即可，贴附 pass 随后收拢）。阶梯 = _derotate_ladder_fine
    # （dev≤10° 用 1° 步进）。候选族：B 四向滑贴首触（质心锚 + 碰撞邻居最小
    # 分离补锚 + 小步进锚）与 A 质心锚定/邻域棱对齐（严格档均须新位贴附）。
    # 找不到合格位则保持原角（residual 如实上报）。
    # 二巡（②′）：分离+贴附重排口袋后，原角片的可行位才可能出现（5156
    # g05_30 实勘：原始态全阶梯无可行位，贴附后 −9°+微移即贴），故 ③½ 后
    # 再扫一轮 + 补一轮贴附收拢微缝。
    derot_angle_budget = DEROT_ANGLE_BUDGET

    def _derotate_sweep(only=None):
        """only = 脏区集合（②′ 只重试自身或邻域被动过的片，None = 全量）。"""
        nonlocal derot_angle_budget
        sw = [i for i in range(n)
              if i not in excluded
              and _rotation_dev(items[i]['rotation']) > DEV_EPS_DEG
              and (only is None or i in only)]
        sw.sort(key=lambda i: (-_rotation_dev(items[i]['rotation']), i))
        for i in sw:
            rot_cur = items[i]['rotation']
            if _rotation_dev(rot_cur) <= DEV_EPS_DEG:
                continue
            strict = _snug(i)
            local = pieces_by_id[items[i]['id']]['polygon']
            # US-004：镜像片 derotate 同一预处理 —— local x 先取负（c_local 用
            # 镜像后多边形质心），t' 补偿公式不变。
            if items[i].get('mirror') is True:
                local = [(-x, y) for x, y in local]
            # B2：碰撞口径局部轮廓（未命中 pid → None = 候选 cg 回退毛版），
            # mirror 同款取负 —— 平移/旋转/镜像与腐蚀可交换。
            local_col = None
            if collide_polygons:
                lc = collide_polygons.get(items[i]['id'])
                if lc is not None:
                    local_col = [(-x, y) for x, y in lc] \
                        if items[i].get('mirror') is True else lc
            c_local = Polygon(local).centroid
            # 质心锚定：c_world = R(rot)·c_local + t（仿射保质心 ⇒ 世界质心即锚）
            c_world = geoms[i].centroid
            obstacles = [k for k in range(n)
                         if k != i and _bbox_overlaps(
                             (bounds[k][0] - NEIGHBOR_MARGIN_MM,
                              bounds[k][1] - NEIGHBOR_MARGIN_MM,
                              bounds[k][2] + NEIGHBOR_MARGIN_MM,
                              bounds[k][3] + NEIGHBOR_MARGIN_MM), bounds[i])]
            placed_move = False
            for target_rot in _derotate_ladder_fine(rot_cur):
                if derot_angle_budget <= 0:
                    break                 # 全局角度预算耗尽：保持原角（residual）
                derot_angle_budget -= 1
                r = math.radians(target_rot)
                c, s = math.cos(r), math.sin(r)
                t0x = c_world.x - (c_local.x * c - c_local.y * s)
                t0y = c_world.y - (c_local.x * s + c_local.y * c)
                g0 = _valid_geometry(_transform_polygon(
                    local, target_rot, (t0x, t0y)))
                cg0 = None if local_col is None else _valid_geometry(
                    _transform_polygon(local_col, target_rot, (t0x, t0y)))
                # 族 B 锚点集：质心锚 + 碰撞邻居最小分离补锚（+严格档小步进
                # 锚）。碰撞判据与 _slide_axis_touch 的 collides 同阈值
                # （≥1e-9mm²）—— 0.001~0.1mm² 的微相交会让滑贴四向全灭
                # （t=0 早退）却不构成诊断级重合，最小分离正是手眼可行的
                # 中间位（5156 g05_30 需 (0,+5) 级锚）；无碰撞的干净口袋靠
                # 小步进锚覆盖 (±5/±10) 级中间位（仅严格档，控成本）。
                anchors_fb = [(0.0, 0.0)]
                b0 = g0.bounds
                colliders = [k for k in range(n)
                             if k != i and _bbox_overlaps(b0, bounds[k])
                             and _hits(g0, geoms[k])][:DEROT_SEP_COLLIDERS]
                for k in colliders:
                    for axis, sign in (('y', 1.0), ('y', -1.0),
                                       ('x', -1.0), ('x', 1.0)):
                        sep = _sep_translate(g0, geoms[k], axis, sign,
                                             iters=DEROT_SEP_ITERS)
                        if sep is not None \
                                and abs(sep[0]) <= DEROT_SEP_MAX_MM \
                                and abs(sep[1]) <= DEROT_SEP_MAX_MM \
                                and (sep[0], sep[1]) not in anchors_fb:
                            anchors_fb.append((sep[0], sep[1]))
                anchors_fb.sort(key=lambda a: math.hypot(a[0], a[1]))
                anchors = list(anchors_fb) + \
                    [a for a in DEROT_NUDGE_ANCHORS] if strict else anchors_fb
                if strict:
                    # 严格档先行：族 B 四向滑贴首触（新位天然贴附 = 贴附不降级）
                    for adx, ady in anchors:
                        ga = translate(g0, xoff=adx, yoff=ady) if (adx or ady) else g0
                        cga = None if cg0 is None else (
                            translate(cg0, xoff=adx, yoff=ady)
                            if (adx or ady) else cg0)
                        hit = _slide_anchor_ok(i, ga, (t0x + adx, t0y + ady), cga)
                        if hit is not None:
                            tr, g, cg, how = hit
                            _try_apply(i, target_rot, tr, g, how, rot_cur, cg)
                            placed_move = True
                            break
                    if placed_move:
                        break
                # 族 A：质心锚定原位 + 障碍/门幅棱边对齐（逐轴独立），按
                # (位移, dx, dy) 升序取首个过守卫位；宽松档首个合法位即受
                # （旧行为），严格档还须新位贴附。障碍取 bbox 距离最近 ≤8 个
                # （远片对齐位位移必大、永轮不到，纯省守卫开销）。
                offs = {(0.0, 0.0)}
                bi = bounds[i]
                near = sorted(
                    obstacles,
                    key=lambda k: (
                        max(bi[0] - bounds[k][2], bounds[k][0] - bi[2], 0.0)
                        + max(bi[1] - bounds[k][3], bounds[k][1] - bi[3], 0.0),
                        k))[:DEROT_OFFSET_OBSTACLES]
                for k in near:
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
                    cg = None if cg0 is None else (
                        translate(cg0, xoff=dx, yoff=dy) if (dx or dy) else cg0)
                    if _move_ok(i, g, cg) and (not strict or _attached(g, i)):
                        _try_apply(i, target_rot, tr, g, '邻域', rot_cur, cg)
                        placed_move = True
                        break
                if placed_move:
                    break
                if not strict:
                    # 宽松档兜底：族 B（质心 + 分离补锚，无小步进锚控成本）
                    # 四向滑贴首触 —— A 全败时贴附位仍是改进。
                    for adx, ady in anchors_fb:
                        ga = translate(g0, xoff=adx, yoff=ady) if (adx or ady) else g0
                        cga = None if cg0 is None else (
                            translate(cg0, xoff=adx, yoff=ady)
                            if (adx or ady) else cg0)
                        hit = _slide_anchor_ok(i, ga, (t0x + adx, t0y + ady), cga)
                        if hit is not None:
                            tr, g, cg, how = hit
                            _try_apply(i, target_rot, tr, g, how, rot_cur, cg)
                            placed_move = True
                            break
                    if placed_move:
                        break
                # 兜底 C 族（2026-10-06 逃逸扫描）：常规候选（严格档 B→A / 宽松档
                # A→B）全败且该片诊断在案（受压）时，双锚（质心 + 原位）四向扫描
                # 到全净位 —— 窄逃逸窗常只在原位锚射线上（3069 g09_29 实勘：质心
                # 锚与原位锚差 ~2mm 恰错过 ~10mm 窗）。首净点 ≈ 贴触位，贴附不
                # 降级；接受仍走同款五守卫。必须挂阶梯内而非管线末尾 —— 终局时
                # attach 已重排环境，逃逸窗可能已关。
                if i in pressed:
                    _tx, _ty = items[i]['translation']
                    if _escape_ok(i, g0, (t0x, t0y), target_rot,
                                  f'rot {rot_cur:.2f}→{target_rot:.2f}，质心锚',
                                  require_attached=strict, cg_from=cg0):
                        placed_move = True
                    else:
                        _g_id = _valid_geometry(_transform_polygon(
                            local, target_rot, (_tx, _ty)))
                        _cg_id = None if local_col is None else \
                            _valid_geometry(_transform_polygon(
                                local_col, target_rot, (_tx, _ty)))
                        if _escape_ok(i, _g_id, (_tx, _ty), target_rot,
                                      f'rot {rot_cur:.2f}→{target_rot:.2f}，原位锚',
                                      require_attached=strict, cg_from=_cg_id):
                            placed_move = True
                if placed_move:
                    break

    derot = [i for i in range(n)
             if i not in excluded
             and _rotation_dev(items[i]['rotation']) > DEV_EPS_DEG]
    derot.sort(key=lambda i: (-_rotation_dev(items[i]['rotation']), i))
    _derotate_sweep()

    # ---- pass ③ 去重叠（穿透深度降序、平手 (i,j)；最小分离 ±y 优先、−x 次之）----
    def _separate_sweep(pair_list):
        """pass ③ 主体（2026-10-06 B4 闭包化：一巡全量 ``pairs`` / 二巡 ③′ 脏区
        重合对共用同一机器）。"""
        for pair in pair_list:
            i, j = pair['i'], pair['j']
            if _pair_stats(geoms[i], geoms[j]) is None:   # 早前 move 已顺带解离
                continue
            done = False
            for mover, other in ((i, j), (j, i)):      # 一片失败换动另一片
                if mover in excluded:
                    continue
                cands = []
                for prio, (axis, sign) in enumerate(
                        (('y', 1.0), ('y', -1.0), ('x', -1.0))):
                    sep = _sep_translate(geoms[mover], geoms[other], axis, sign)
                    if sep is not None:
                        dx, dy, t = sep
                        cands.append((t, prio, dx, dy))
                for t, prio, dx, dy in sorted(cands):  # 最小分离平移优先
                    old_tr = items[mover]['translation']
                    tr = (old_tr[0] + dx, old_tr[1] + dy)
                    g = translate(geoms[mover], xoff=dx, yoff=dy)
                    cg = translate(cgeoms[mover], xoff=dx, yoff=dy)
                    if _move_ok(mover, g, cg):
                        direction = '+y' if prio == 0 else ('−y' if prio == 1 else '−x')
                        _apply(mover, items[mover]['rotation'], tr, g, 'separate',
                               f'与 placed[{other}]（{items[other]["id"]}）分离：'
                               f'{direction} 最小平移 {t:.2f}mm', cgeom_new=cg)
                        done = True
                        break
                if done:
                    break
            # 逃逸兜底（2026-10-06）：双 mover 最小分离全败（楔形双侧受压下单伙伴
            # 最小分离必落在另一侧墙上）时，自当前位当前角四向扫描到全净位 —— 纯
            # 平移形态的楔口逃逸；exclude 片跳过不扫。
            if not done:
                for mover, other in ((i, j), (j, i)):
                    if mover in excluded:
                        continue
                    if _escape_ok(mover, geoms[mover], items[mover]['translation'],
                                  items[mover]['rotation'],
                                  f'与 placed[{other}]（{items[other]["id"]}）分离',
                                  cg_from=cgeoms[mover]):
                        break

    pairs.sort(key=lambda p: (-p['penetration_mm'], p['i'], p['j']))
    _separate_sweep(pairs)

    # ---- pass ③½ 贴附（attach，默认启用）：重力压实 west+south 交替滑贴 ----
    # 2026-10-05 裁床裁板需求：裁片片片贴合方便走刀。west 趟复用 compact 的
    # 级联骨架（minX 升序、左片先贴新位），south 趟镜像（minY 升序、下片先
    # 贴）；贴墙（布头 x=0 / 下门幅 y=0）与贴障碍同权。纯平移 + 首触即停 +
    # 1nm 回退 ⇒ 永不增大旋转、永不新重合；south 不动 x ⇒ 包络守卫天然过。
    # 整轮零 move 早退 + 势函数 Σ(minX+minY) 严格递减双保险终止；轮数上限
    # 兜底最坏耗时。贴附 move 无 pass 级回滚（每 move 个体守卫，move 本身
    # 即贴附改进）；exclude 片永不作 mover、恒作障碍（band/prefix 刚性组不破）。
    # 2026-10-06 闭包化：②′ 归位二巡后再补一轮收拢微缝（零 move 即早退）。
    attach_moves = 0

    def _attach_sweep():
        nonlocal attach_moves
        for _round in range(ATTACH_ROUNDS_MAX):
            moved = 0
            # west 趟：自布头方向级联 −x 滑贴（障碍剪枝同 compact：x 可达 +
            # 布头墙左侧不可达剔除 + y 带重叠）。
            for k in sorted((k for k in range(n) if k not in excluded),
                            key=lambda k: (bounds[k][0], k)):
                if bounds[k][0] <= ATTACH_GAIN_EPS_MM:
                    continue             # 已贴布头（或 minX≤0 外凸）：不可再滑
                b_k = bounds[k]
                obstacles = [geoms[m] for m in range(n)
                             if m != k
                             and bounds[m][0] < b_k[2]        # 滑移路径 x 可达
                             and bounds[m][2] > 0.0           # 布头墙左侧不可达
                             and not (bounds[m][3] < b_k[1]
                                      or b_k[3] < bounds[m][1])]
                t = _slide_axis_touch(geoms[k], obstacles, b_k[0], 'x', -1.0)
                if t <= ATTACH_GAIN_EPS_MM:
                    continue
                tr = (items[k]['translation'][0] - t,
                      items[k]['translation'][1])
                g = translate(geoms[k], xoff=-t)
                cg = translate(cgeoms[k], xoff=-t)
                if _move_ok(k, g, cg):
                    _apply(k, items[k]['rotation'], tr, g, 'attach',
                           f'−x 滑贴贴附 {t:.2f}mm', cgeom_new=cg)
                    moved += 1
            # south 趟：门幅下边方向级联 −y 滑贴（镜像剪枝：y 可达 + 下门幅墙
            # 下侧不可达剔除 + x 带重叠）。
            for k in sorted((k for k in range(n) if k not in excluded),
                            key=lambda k: (bounds[k][1], k)):
                if bounds[k][1] <= ATTACH_GAIN_EPS_MM:
                    continue             # 已贴下门幅：不可再滑
                b_k = bounds[k]
                obstacles = [geoms[m] for m in range(n)
                             if m != k
                             and bounds[m][1] < b_k[3]        # 滑移路径 y 可达
                             and bounds[m][3] > 0.0           # 下门幅墙下侧不可达
                             and not (bounds[m][2] < b_k[0]
                                      or b_k[2] < bounds[m][0])]
                t = _slide_axis_touch(geoms[k], obstacles, b_k[1], 'y', -1.0)
                if t <= ATTACH_GAIN_EPS_MM:
                    continue
                tr = (items[k]['translation'][0],
                      items[k]['translation'][1] - t)
                g = translate(geoms[k], yoff=-t)
                cg = translate(cgeoms[k], yoff=-t)
                if _move_ok(k, g, cg):
                    _apply(k, items[k]['rotation'], tr, g, 'attach',
                           f'−y 滑贴贴附 {t:.2f}mm', cgeom_new=cg)
                    moved += 1
            attach_moves += moved
            if not moved:
                break                      # 不动点：整轮零 move 早退

    _attach_sweep()

    # ---- pass ③′ 分离二巡（2026-10-06 B4 压线收敛）+ 补一轮贴附 ----
    # attach 重排（数百 move 级环境剧变）后，一巡失败的分离可行位才可能出现
    # （882 实勘：[9]g01_33 的 −y 候选在 attach 后已可通过、但 pass ③ 只在
    # attach 前跑一次 —— 修复机会被顺序吞掉）。脏区门控镜像 ②′：只重扫「自身
    # 或邻域（NEIGHBOR_MARGIN）被动过」的片的现存重合对（环境未变者可行性
    # 不变）；重合对数 SEP2_PAIR_CAP 确定性封顶（穿透降序取前 N，大文件防拖爆
    # 预算）；逃逸触发门 pressed 随重扫增补（保守超集）。零重扫对 → 整段 no-op。
    only3 = set(touched)
    for k in list(touched):
        bk = (bounds[k][0] - NEIGHBOR_MARGIN_MM, bounds[k][1] - NEIGHBOR_MARGIN_MM,
              bounds[k][2] + NEIGHBOR_MARGIN_MM, bounds[k][3] + NEIGHBOR_MARGIN_MM)
        for i in range(n):
            if _bbox_overlaps(bk, bounds[i]):
                only3.add(i)
    re_pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            if i not in only3 and j not in only3:
                continue
            st = _pair_stats(geoms[i], geoms[j])
            if st is not None:
                re_pairs.append({'i': i, 'j': j,
                                 'area_mm2': st[0], 'penetration_mm': st[1]})
    re_pairs.sort(key=lambda p: (-p['penetration_mm'], p['i'], p['j']))
    if len(re_pairs) > SEP2_PAIR_CAP:
        re_pairs = re_pairs[:SEP2_PAIR_CAP]
    pressed |= {_ix for _p in re_pairs for _ix in (_p['i'], _p['j'])}
    _separate_sweep(re_pairs)
    _attach_sweep()

    # ---- pass ②′ 贴附保持归位 · 二巡 + 补一轮贴附（2026-10-06）----
    # 分离+贴附重排口袋后，一巡失败的斜片可行位才可能出现（5156 g05_30：
    # 原始态全阶梯无可行位、贴附态 −9°+微移即贴）。脏区门控：只重试「自身
    # 或邻域（NEIGHBOR_MARGIN）被动过」的片 —— 环境未变者可行性不变，大
    # 文件下砍掉二巡大头开销。二巡后补一轮贴附收拢宽松档归位留下的微缝。
    only2 = set(touched)
    for k in list(touched):
        bk = (bounds[k][0] - NEIGHBOR_MARGIN_MM, bounds[k][1] - NEIGHBOR_MARGIN_MM,
              bounds[k][2] + NEIGHBOR_MARGIN_MM, bounds[k][3] + NEIGHBOR_MARGIN_MM)
        for i in range(n):
            if i not in excluded and _bbox_overlaps(bk, bounds[i]):
                only2.add(i)
    _derotate_sweep(only=only2)
    _attach_sweep()

    # ---- pass ④ 压缩回收（compact=True；自布头方向逐片 −x 滑贴收空隙）----
    if compact:
        snap_items = [_rebuild_item(it) for it in items]
        snap_geoms = list(geoms)
        snap_cgeoms = list(cgeoms)
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
            cg = translate(cgeoms[k], xoff=-t)
            if _move_ok(k, g, cg):
                _apply(k, items[k]['rotation'], tr, g, 'compact',
                       f'−x 滑贴回收空隙 {t:.2f}mm', cgeom_new=cg)
        max_x_tail = max((b[2] for b in bounds), default=0.0)
        if not max_x_tail < max_x_head - COMPACT_GAIN_EPS_MM:
            # 包络 maxX 未严格变小：整段回滚（无改进逐字节不变 —— 输出与非
            # compact 档全等、moves/residual 不留孤儿记录）。
            items = snap_items
            geoms = snap_geoms
            cgeoms = snap_cgeoms
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
              'attach_moves': attach_moves,
              'escape_moves': escape_moves,
              'elapsed_sec': round(time.perf_counter() - t0, 3)}

    if not moves:                       # 无改进：输入 list 原对象逐字节不变
        return placed, report
    if Counter(p['id'] for p in items) != multiplicity:   # 守卫④ 终检
        raise PolishError('pid 多重集守恒失败（内部不变量被破坏）')
    out = [_rebuild_item(it) for it in items]
    return out, report


# --------------------------------------------------------------- 冒烟入口

def _rect_piece(pid, w, h, label='g01', size=28):
    """冒烟/夹具用矩形裁片（schema v2 最小字段）。"""
    return {'pid': pid, 'label': label, 'size': size,
            'polygon': [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]],
            'bbox': [0.0, 0.0, w, h], 'area_mm2': float(w * h), 'n_verts': 4,
            'net_polygon': [], 'internal_lines': [], 'notches': [],
            'grain_line': None}


def _l_piece(pid, label='g09', size=28):
    """冒烟/夹具用 L 形非对称裁片（US-004 镜像判别性夹具：镜像前后空缺角
    互换 —— 右上空缺镜像后到左上，镜像与否几何/包络可判别）。"""
    poly = [[0.0, 0.0], [200.0, 0.0], [200.0, 60.0], [60.0, 60.0],
            [60.0, 150.0], [0.0, 150.0]]          # 面积 200×60 + 60×90 = 17400
    return {'pid': pid, 'label': label, 'size': size, 'polygon': poly,
            'bbox': [0.0, 0.0, 200.0, 150.0], 'area_mm2': 17400.0,
            'n_verts': 6, 'net_polygon': [], 'internal_lines': [], 'notches': [],
            'grain_line': None}


def _pl(pid, rot, tx, ty, mirror=False):
    """placement 夹具构造（mirror=True 带 omit-when-false 可选键，US-004）。"""
    it = {'id': pid, 'rotation': float(rot), 'translation': [float(tx), float(ty)]}
    if mirror:
        it['mirror'] = True
    return it


def _world_polygon(pid, pieces_by_id, rot, tr, mirror=False):
    """夹具断言用世界坐标 shapely Polygon（与 _world_geom 同变换口径含镜像）。"""
    poly = pieces_by_id[pid]['polygon']
    if mirror:
        poly = [(-x, y) for x, y in poly]
    return Polygon(_transform_polygon(poly, float(rot), tr))


def _smoke_fixtures() -> bool:
    """合成夹具自检（AC 口径复刻；全部通过返回 True）。"""
    ok = True

    def _check(name, cond, detail=''):
        nonlocal ok
        print(f'  [{name}] {"PASS" if cond else "FAIL"}'
              f'{(" " + detail) if detail else ""}')
        ok = ok and bool(cond)

    # ① 空白旁斜片：单片 25° 居空场 → 回正 dev=0、质心零位移（贴附 pass 随后
    #    会把片聚拢到墙角，质心断言锚定 derotate move 本身）
    pieces = {'g01_30': _rect_piece('g01_30', 300, 100)}
    placed = [_pl('g01_30', 25, 500, 500)]
    out, rep = polish_layout(placed, pieces, 2000.0)
    m0 = rep['moves'][0]
    g0 = _world_polygon('g01_30', pieces, placed[0]['rotation'],
                        placed[0]['translation'])
    g1 = _world_polygon('g01_30', pieces, m0['to']['rotation'],
                        m0['to']['translation'])
    _check('空白旁斜片', _rotation_dev(out[0]['rotation']) == 0.0
           and m0['kind'] == 'derotate'
           and rep['after']['overlap_pairs'] == 0
           and g0.centroid.distance(g1.centroid) < 1e-6,
           f'rot={out[0]["rotation"]:.1f} moves={len(rep["moves"])}')

    # ② 可分离重合对：叠 5mm → 交集面积精确 0（分离后贴附 pass 继续聚拢到布头）
    pieces = {'g01_30': _rect_piece('g01_30', 200, 150),
              'g02_30': _rect_piece('g02_30', 200, 150, label='g02')}
    placed = [_pl('g01_30', 0, 100, 100), _pl('g02_30', 0, 100, 245)]
    out, rep = polish_layout(placed, pieces, 1000.0)
    inter = _world_polygon('g01_30', pieces, out[0]['rotation'],
                           out[0]['translation']).intersection(
        _world_polygon('g02_30', pieces, out[1]['rotation'],
                       out[1]['translation']))
    _check('可分离重合对', inter.area == 0.0
           and any(m['kind'] == 'separate' for m in rep['moves'])
           and rep['attach_moves'] >= 1,
           f'交集面积={inter.area:.3g} 重合对 '
           f'{rep["before"]["overlap_pairs"]}→{rep["after"]["overlap_pairs"]} '
           f'attach={rep["attach_moves"]}')

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

    # ④ 守卫·越门幅：唯一分离方向 +y 越门幅（上下左右全堵）—— 守卫意图 =
    #    U/L 重合对保持未分离且两者原地不动；其余未贴附片（B/W）被贴附 pass
    #    合法聚拢属新默认行为（2026-10-05），不与守卫冲突。
    pieces = {'g01_30': _rect_piece('g01_30', 200, 120),
              'g02_30': _rect_piece('g02_30', 200, 80, label='g02'),
              'g03_30': _rect_piece('g03_30', 200, 175, label='g03'),
              'g04_30': _rect_piece('g04_30', 600, 200, label='g04')}
    placed = [_pl('g01_30', 0, 600, 880),   # U：顶部贴门幅
              _pl('g02_30', 0, 650, 875),   # L：与 U 叠 5mm
              _pl('g03_30', 0, 650, 700),   # B：堵 −y
              _pl('g04_30', 0, 0, 800)]     # W：堵 −x（左墙）
    out, rep = polish_layout(placed, pieces, 1000.0)
    _check('守卫·越门幅拒绝',
           out[0]['translation'] == placed[0]['translation']
           and out[1]['translation'] == placed[1]['translation']
           and all(m['kind'] == 'attach' for m in rep['moves'])
           and any(r['kind'] == 'overlap' for r in rep['residual']),
           f'moves={[(m["index"], m["kind"]) for m in rep["moves"]]} '
           f'residual={len(rep["residual"])}')

    # ⑤ 守卫·包络（2026-10-06 行为演进）：旧「唯一空位在 +x 尾部外」场景被
    #    四向滑贴解锁 —— 斜片 −x 滑贴贴 g02 东缘归位 0°、包络反而收缩；守卫
    #    仍逐 move 生效（所有 move 包络不增；越门幅拒绝由 ④ 独立覆盖）。
    pieces = {'g01_30': _rect_piece('g01_30', 400, 40),
              'g02_30': _rect_piece('g02_30', 300, 600, label='g02')}
    placed = [_pl('g02_30', 0, 0, 200), _pl('g01_30', 25, 379, 200)]
    out, rep = polish_layout(placed, pieces, 1000.0)
    g1 = _world_polygon('g01_30', pieces, out[1]['rotation'],
                        out[1]['translation'])
    g2 = _world_polygon('g02_30', pieces, out[0]['rotation'],
                        out[0]['translation'])
    _check('守卫·包络（滑贴解锁归位）',
           _rotation_dev(out[1]['rotation']) == 0.0
           and rep['moves'][0]['kind'] == 'derotate'
           and rep['after']['width_mm'] <= rep['before']['width_mm'] + 0.5
           and rep['after']['overlap_pairs'] == 0
           and g1.intersection(g2).area == 0.0
           and g1.distance(g2) <= 1e-3,
           f'width {rep["before"]["width_mm"]}→{rep["after"]["width_mm"]} '
           f'moves={[m["kind"] for m in rep["moves"]]}')

    # ⑥ 多副本：同 pid 3 副本仅第 2 条斜置（derotate 按 index 寻址；贴附
    #    pass 随后聚拢未贴附副本属新默认行为，第 1 条贴布头副本恒不动）
    pieces = {'g01_30': _rect_piece('g01_30', 300, 100)}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g01_30', 25, 600, 600),
              _pl('g01_30', 0, 1200, 0)]
    out, rep = polish_layout(placed, pieces, 2000.0)
    _check('多副本按 index 寻址',
           rep['moves'][0]['kind'] == 'derotate'
           and rep['moves'][0]['index'] == 1
           and out[0]['translation'] == placed[0]['translation']
           and out[0]['rotation'] == placed[0]['rotation']
           and all(m['index'] != 0 for m in rep['moves'])
           and _rotation_dev(out[1]['rotation']) == 0.0,
           f'moves={[(m["index"], m["kind"]) for m in rep["moves"]]}')

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
    #    （贴附 pass 先行收空隙，compact 档通常无剩可收 → moves 全为 attach）
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
           and all(m['kind'] == 'attach' for m in rep['moves'])
           and rep['attach_moves'] == 2,
           f'width {rep["before"]["width_mm"]}→{rep["after"]["width_mm"]} '
           f'moves={[(m["index"], m["kind"]) for m in rep["moves"]]}')

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

    # ⑪ 镜像斜片（US-004）：L 形非对称镜像片 25° 居空场 → 回正 + mirror 透传
    #    + 质心锚定（c_local 用镜像后多边形质心，t' 补偿公式不变；贴附 pass
    #    随后会把片聚拢到墙角，质心断言锚定 derotate move 本身）
    pieces = {'g09_30': _l_piece('g09_30')}
    placed = [_pl('g09_30', 25, 600, 600, mirror=True)]
    out, rep = polish_layout(placed, pieces, 2000.0)
    m0 = rep['moves'][0]
    g0 = _world_polygon('g09_30', pieces, placed[0]['rotation'],
                        placed[0]['translation'], mirror=True)
    g1 = _world_polygon('g09_30', pieces, m0['to']['rotation'],
                        m0['to']['translation'], mirror=True)
    _check('镜像斜片 derotate', out[0].get('mirror') is True
           and m0['kind'] == 'derotate'
           and _rotation_dev(out[0]['rotation']) == 0.0
           and g0.centroid.distance(g1.centroid) < 1e-6,
           f'rot={out[0]["rotation"]:.1f} moves={len(rep["moves"])}')

    # ⑫ 镜像片 no-op（US-004）：紧凑含镜像片（分离方向全被守卫拒）→ 输入 list
    #     原对象（mirror 键原样保留，逐字节不变量）
    pieces = {'g01_30': _rect_piece('g01_30', 100, 160),
              'g02_30': _rect_piece('g02_30', 100, 160, label='g02')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 98, 0, mirror=True)]
    out, rep = polish_layout(placed, pieces, 160.0)
    _check('镜像片 no-op 原对象', out is placed and rep['moves'] == []
           and placed[1].get('mirror') is True,
           f'moves={len(rep["moves"])} residual={len(rep["residual"])}')

    # ⑬ 贴附·south 闭合空白带（2026-10-05）：竖向留 140mm 空隙 → −y 滑贴到
    #     下方片顶边 +1nm、零重合（截图空白带场景的合成最小复现）
    pieces = {'g01_30': _rect_piece('g01_30', 100, 160),
              'g02_30': _rect_piece('g02_30', 100, 160, label='g02')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 0, 300)]
    out, rep = polish_layout(placed, pieces, 1000.0)
    _check('贴附 south 闭合空白带',
           rep['attach_moves'] == 1
           and abs(out[1]['translation'][1] - 160.0) < 0.01
           and rep['moves'][0]['detail'].startswith('−y')
           and rep['after']['overlap_pairs'] == 0,
           f'ty={out[1]["translation"][1]:.3f} '
           f'attach={rep["attach_moves"]}')

    # ⑭ 贴附保持的减少旋转（2026-10-06 新语义）：3° 斜片距邻片 0.65mm（干净
    #     贴附、严格档）→ 照旧进阶梯归位到 0° 且新位贴附（「更小角度同样贴附
    #     才动、动则必贴」；旧 snug 一刀切冻结已废除 —— 5156 实勘误伤）
    pieces = {'g01_30': _rect_piece('g01_30', 200, 150),
              'g02_30': _rect_piece('g02_30', 200, 150, label='g02')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 3, 208.5, 0)]
    out, rep = polish_layout(placed, pieces, 1000.0)
    g1 = _world_polygon('g01_30', pieces, out[0]['rotation'],
                        out[0]['translation'])
    g2 = _world_polygon('g02_30', pieces, out[1]['rotation'],
                        out[1]['translation'])
    _check('贴附斜片归位且保贴附',
           _rotation_dev(out[1]['rotation']) == 0.0
           and rep['moves'][0]['kind'] == 'derotate'
           and g1.intersection(g2).area == 0.0
           and g1.distance(g2) <= 1e-3
           and not any(r['kind'] == 'rotation' for r in rep['residual']),
           f'rot={out[1]["rotation"]:.1f} '
           f'moves={[m["kind"] for m in rep["moves"]]}')

    # ⑮ 贴附·贴墙（2026-10-05）：孤立片重力压实滑到布头 x=0 与下门幅 y=0 墙
    pieces = {'g01_30': _rect_piece('g01_30', 100, 160)}
    placed = [_pl('g01_30', 0, 300, 400)]
    out, rep = polish_layout(placed, pieces, 1000.0)
    _check('贴附贴墙（布头+下门幅）',
           out[0]['translation'][0] <= 1e-3
           and out[0]['translation'][1] <= 1e-3
           and rep['attach_moves'] == 2,
           f'tr={out[0]["translation"]} attach={rep["attach_moves"]}')

    # ⑯ 逃逸·平移兜底（2026-10-06 separate-escape）：双侧受压条片在常规分离
    #     全败后 +x 扫描到全净位（详见 tests/test_polish.py 同构夹具）
    pieces = {'g01_30': _rect_piece('g01_30', 200, 150),
              'g02_30': _rect_piece('g02_30', 160, 150, label='g02'),
              'g03_30': _rect_piece('g03_30', 60, 110, label='g03'),
              'g04_30': _rect_piece('g04_30', 100, 400, label='g04'),
              'g05_30': _rect_piece('g05_30', 300, 100, label='g05')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 100, 245),
              _pl('g03_30', 0, 170, 145), _pl('g04_30', 0, 600, 0),
              _pl('g05_30', 0, 0, 500)]
    out, rep = polish_layout(placed, pieces, 1000.0,
                             exclude={'labels': ['g01', 'g02']})
    esc = [m for m in rep['moves'] if m['kind'] == 'separate-escape']
    _check('逃逸平移兜底（separate-escape）',
           rep['before']['overlap_pairs'] == 2
           and rep['after']['overlap_pairs'] == 0
           and len(esc) == 1 and '+x逃逸' in esc[0]['detail']
           and rep['escape_moves'] == 1,
           f'escape={rep["escape_moves"]} {esc[0]["detail"] if esc else ""}')

    # ⑰ 逃逸·换角兜底（2026-10-06 derotate-escape）：5° 受压条片 0° 台阶 −x
    #     逃逸入天花板凹兜（凹兜对 bbox 棱对齐不可见 —— 窄窗只有细采样够得到）
    import math as _m
    _floor = [[-600.0, 0.0], [600.0, 0.0], [600.0, 30.0], [-600.0, 30.0]]
    _ceil = [[-600.0, 66.0], [225.0, 66.0], [225.0, 80.0], [445.0, 80.0],
             [445.0, 66.0], [600.0, 66.0], [600.0, 1000.0], [-600.0, 1000.0]]

    def _pp(pid, label, poly):
        return {'pid': pid, 'label': label, 'size': 28, 'polygon': poly,
                'area_mm2': Polygon(poly).area, 'net_polygon': [],
                'internal_lines': [], 'notches': [], 'grain_line': None}

    _r = _m.radians(5.0)
    _ctr = (_m.cos(_r) * 100 - _m.sin(_r) * 20, _m.sin(_r) * 100 + _m.cos(_r) * 20)
    pieces = {'g06_30': _pp('g06_30', 'g06', _floor),
              'g07_30': _pp('g07_30', 'g07', _ceil),
              'g08_30': _rect_piece('g08_30', 200, 40, label='g08')}
    placed = [_pl('g06_30', 0, 0, 0), _pl('g07_30', 0, 0, 0),
              _pl('g08_30', 5, 382.0 - _ctr[0], 50.0 - _ctr[1])]
    out, rep = polish_layout(placed, pieces, 1000.0,
                             exclude={'labels': ['g06', 'g07']})
    esc = [m for m in rep['moves'] if m['kind'] == 'derotate-escape']
    _check('逃逸换角兜底（derotate-escape）',
           rep['before']['overlap_pairs'] == 2
           and rep['after']['overlap_pairs'] == 0
           and _rotation_dev(out[2]['rotation']) == 0.0
           and len(esc) == 1 and '−x逃逸' in esc[0]['detail'],
           f'escape={rep["escape_moves"]} {esc[0]["detail"] if esc else ""}')

    # ⑱ 守卫①出界余量（2026-10-06 B1 压线收敛）：贴边片毛版出界 3mm（sparrow 只
    #     约束 erode 轮廓的既成事实）—— +y 更出界、−y 被 C/D2 全高堵死（逃逸也
    #     死）、−x 是唯一分离向且 y 不变。旧 y∈[0,gate] 硬卡把 −x 也判死（纯水平
    #     移动 y bounds 原样出界）→ 全灭 residual；新规则「不劣于初始出界量」放行
    #     −x（贴附 pass 随后自由聚拢，断言锚定 separate move 本身）。
    pieces = {'g01_30': _rect_piece('g01_30', 100, 30),
              'g02_30': _rect_piece('g02_30', 100, 30, label='g02'),
              'g03_30': _rect_piece('g03_30', 100, 130, label='g03'),
              'g04_30': _rect_piece('g04_30', 100, 70, label='g04')}
    placed = [_pl('g01_30', 0, 500, 95),    # A：y∈[95,125]，gate=122 → 出界 3
              _pl('g02_30', 0, 420, 95),    # B：与 A 叠 20mm（分离对象）
              _pl('g03_30', 0, 560, 0),     # C：全高右柱，堵 A/B 的 −y 与逃逸
              _pl('g04_30', 0, 420, 20)]    # D2：堵 B 的 −y 落位
    out, rep = polish_layout(placed, pieces, 122.0)
    sep = [m for m in rep['moves'] if m['kind'] == 'separate' and '−x' in m['detail']]
    _check('守卫①出界余量解冻贴边片',
           len(sep) == 1 and sep[0]['index'] == 0
           and rep['after']['overlap_pairs'] == 0
           and abs(sep[0]['to']['translation'][1]
                   - sep[0]['from']['translation'][1]) < 1e-6,
           f'moves={[(m["index"], m["kind"]) for m in rep["moves"]]} '
           f'residual={len(rep["residual"])}')

    # ⑲ 守卫③碰撞口径（2026-10-06 B2 压线收敛）：A 与 B 叠 10mm（目标对）、与
    #     C 叠 20mm（d 预算设计压线 —— collide 轮廓局部内缩 25mm 与 A 干净）；
    #     四面墙堵住 ±y/−x/+x 的毛版净窗（旧行为全灭双对 residual，判别性在
    #     tests/test_polish.py 双模式断言）。碰撞口径下 A −y 10 落点对 C 的 erode
    #     轮廓零重合 → 放行（保留压线不再误杀候选）。
    pieces = {
        'g01_30': _rect_piece('g01_30', 100, 40),           # A @ (200,100)
        'g02_30': _rect_piece('g02_30', 100, 40, 'g02'),    # B @ (240,130)
        'g03_30': _rect_piece('g03_30', 120, 80, 'g03'),    # C @ (100,90)
        'g04_30': _rect_piece('g04_30', 100, 70, 'g04'),    # 下墙 @ (200,20)
        'g05_30': _rect_piece('g05_30', 100, 70, 'g05'),    # 上墙 @ (200,170)
        'g06_30': _rect_piece('g06_30', 100, 40, 'g06'),    # 左墙 @ (0,100)
        'g07_30': _rect_piece('g07_30', 100, 40, 'g07')}    # 右塞 @ (350,130)
    placed = [_pl('g01_30', 0, 200, 100), _pl('g02_30', 0, 240, 130),
              _pl('g03_30', 0, 100, 90), _pl('g04_30', 0, 200, 20),
              _pl('g05_30', 0, 200, 170), _pl('g06_30', 0, 0, 100),
              _pl('g07_30', 0, 350, 130)]
    out, rep = polish_layout(
        placed, pieces, 1000.0,
        exclude={'labels': ['g04', 'g05', 'g06', 'g07']},
        collide_polygons={'g03_30': [[25.0, 25.0], [95.0, 25.0],
                                     [95.0, 55.0], [25.0, 55.0]]})
    sep = [m for m in rep['moves'] if m['kind'] == 'separate']
    g_out = [_world_polygon(p['id'], pieces, p['rotation'], p['translation'])
             for p in out]
    _check('守卫③碰撞口径放行预算内压线',
           any(m['index'] == 0 and '−y' in m['detail'] for m in sep)
           and g_out[0].intersection(g_out[1]).area == 0.0
           and g_out[0].intersection(g_out[2]).area == 0.0,
           f'seps={[(m["index"], m["detail"]) for m in sep]} '
           f'after_pairs={rep["after"]["overlap_pairs"]}（C×左墙新预算压线如实入报告）')

    # ㉑ 分离二巡 ③′（2026-10-06 B4 压线收敛）：M×P 叠 5mm，唯一分离向 +y 5mm
    #     的落位被悬浮薄片 X 楔住（pass③ 全灭、四向逃逸全被 D4/包络/门幅封死）；
    #     attach west 把 X 拖到布头（150mm）后落位净空 —— ③′ 脏区重扫补上这刀
    #     （顺序证明：X 的 attach move 在 separate move 之前）。
    pieces = {'g01_30': _rect_piece('g01_30', 100, 50),           # M @ (100,45)
              'g02_30': _rect_piece('g02_30', 100, 50, 'g02'),    # P @ (100,0)
              'g03_30': _rect_piece('g03_30', 100, 50, 'g03'),    # D4 左墙 @ (0,45)
              'g04_30': _rect_piece('g04_30', 60, 4, 'g04')}      # X 悬浮片 @ (150,96)
    placed = [_pl('g01_30', 0, 100, 45), _pl('g02_30', 0, 100, 0),
              _pl('g03_30', 0, 0, 45), _pl('g04_30', 0, 150, 96)]
    out, rep = polish_layout(placed, pieces, 145.0)
    moves = rep['moves']
    i_att = next((k for k, m in enumerate(moves)
                  if m['kind'] == 'attach' and m['pid'] == 'g04_30'), None)
    i_sep = next((k for k, m in enumerate(moves) if m['kind'] == 'separate'), None)
    _check('分离二巡（attach 后重扫）',
           rep['before']['overlap_pairs'] == 1
           and rep['after']['overlap_pairs'] == 0
           and i_att is not None and i_sep is not None and i_att < i_sep,
           f'moves={[(m["pid"], m["kind"]) for m in moves]}')
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
          f'separate={kinds.get("separate", 0)} '
          f'attach={kinds.get("attach", 0)}）'
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

    默认合成夹具自检（AC 十七项口径：斜片回正/重合分离/紧密 no-op/守卫×2/
    多副本 index 寻址/排除集障碍/确定性双跑/compact 回收/compact 无空隙
    逐元素相同/镜像斜片 derotate+透传/镜像片 no-op 原对象/贴附 south 闭合
    空白带/贴附斜片归位且保贴附/贴附贴墙/逃逸平移兜底/逃逸换角兜底），全过打印
    PASS、exit 0。
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
