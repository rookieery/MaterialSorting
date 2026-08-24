"""US-009 waist_band 核心模块测试（v2 2026-08-21：构造性链构造替换 spyrrow 带内求解）。

覆盖（tasks/prd-waist-band.md US-009 验收标准 + v2 版师形态）：
1. 展开黄金用例：rot=180 + 带偏移成员**手算对拍**（权威式 rot_f / tr_f，offset 减号）
   + 变换链等价（先带内变换、减 offset、再组合片变换 == 直接展开）；
2. 包络断言：union(成员原轮廓@展开位) ⊆ composite@主解位 ⊕ d_g（容差 0.5mm）；
3. 副本守恒：Σ 展开成员条数 == Σ demand（5336 g05 同构 7 码 × 2 = 14/14）；
4. 异常路径：0 副本 ValueError、总副本 1 DegenerateBand、fill 超限 BandQualityError；
5. 确定性：band seed = zlib.crc32 派生（勿用 hash()）、同 seed 两跑 to_dict JSON 相等；
6. 分层纯度：模块级不 import web（AST 守卫，套路同 test_cli_lns）；
7. v2 版师形态（真实弧形几何）：链内贴触 ≤ ``CHAIN_GAP_EPS_MM``、开口朝左、
   最大码在最右（降序构造 + 整链点对称翻转）；
8. 直腰头平坦模式（2026-08-24 版师指正，882# g01）：判据分离（矩形直条 vs
   月牙弧）+ 全链路形态（片片 rot=0 无翻转、同底齐平、**多副本单链全局从短到
   长**（单调阶梯，N 链交叉深谷必挂）、大码最右、带高=最高片、副本数不均匀）。

合成夹具：矩形（结构同 5336 g05：7 码 × demand 2）+ 月牙弧（曲率相近异码嵌套）
+ 异高竖条（882# g01 直腰头同构：10 码 × demand 2，高度互异放大交替翻转让乱象可判）。
"""
from __future__ import annotations

import ast
import json
import math
import zlib
from pathlib import Path

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from materialsorting.nesting_engine import waist_band
from materialsorting.nesting_engine.sparrow_baseline import _transform_polygon
from materialsorting.nesting_engine.sparrow_experiments import erode_polygon
from materialsorting.nesting_engine.waist_band import (
    COMPOSITE_ORIENTATIONS,
    COMPOSITE_PID_PREFIX,
    BandChunk,
    BandQualityError,
    DegenerateBand,
    band_seed_for,
    build_band_plan,
    expand_placements,
)

def _rect_piece(pid, label, size, w, h):
    """合成 v2 schema 裁片（矩形原轮廓，与 test_solver_label._piece 同构）。"""
    return {
        'pid': pid, 'label': label, 'size': size,
        'polygon': [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]],
        'area_mm2': float(w) * float(h),
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
    }


def _band_ctx(label='g05', sizes=(28, 29, 30, 31, 33, 34, 35), demand=2,
              w=60.0, h=300.0, d_g=0.4):
    """5336 g05 同构上下文：7 码 × demand 2 = 14 副本。

    返回 ``(pid_meta, pieces_by_id)``：pid_meta.polygon 为 erode(d_g) 后轮廓
    （build_pid_meta 同口径 —— 带 Item 用已腐蚀多边形不二次腐蚀）；pieces_by_id
    存原始轮廓（union / 包络断言口径）。
    """
    pieces_by_id = {}
    pid_meta = {}
    for s in sizes:
        pid = f'{label}_{s}'
        p = _rect_piece(pid, label, s, w, h)
        pieces_by_id[pid] = p
        poly = erode_polygon(p['polygon'], d_g) if d_g > 0 else p['polygon']
        pid_meta[pid] = {
            'size': s, 'color': '#000000', 'polygon': poly,
            'area_mm2': p['area_mm2'], 'label': label, 'demand': demand,
            'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
        }
    return pid_meta, pieces_by_id


def _arc_piece(pid, label, size, r_in, thick=68.0, half_deg=19.0, n=24):
    """合成月牙腰片（v2 形态用例）：−X 轴向离散环形扇带，凸侧朝 −X。

    默认参数与朝向取 5336 g05 真实几何族（r≈1550+、thick≈68、half≈19°、rot0
    单片质心偏移 −18~−22mm 即凸侧 −X）—— 异码曲率相近、可贴触嵌套；开口方向
    判据 ``_opening_side`` 在此类几何上有信号（对称片返回 'flat'）。
    """
    r_out = r_in + thick
    pts = []
    for i in range(n + 1):          # 外弧（凸侧）180−half → 180+half
        a = math.radians(180.0 - half_deg + 2.0 * half_deg * i / n)
        pts.append([r_out * math.cos(a), r_out * math.sin(a)])
    for i in range(n + 1):          # 内弧（凹侧）180+half → 180−half
        a = math.radians(180.0 + half_deg - 2.0 * half_deg * i / n)
        pts.append([r_in * math.cos(a), r_in * math.sin(a)])
    return {
        'pid': pid, 'label': label, 'size': size, 'polygon': pts,
        'area_mm2': Polygon(pts).area,
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
    }


def _arc_ctx(label='g05', sizes=(28, 29, 30, 31, 33, 34, 35), demand=2, d_g=0.4):
    """弧形腰片上下文：7 码 × demand 2（同 _band_ctx 结构，r_in=1550+40·(码−28)
    —— 5336 g05 真实几何族参数，链构造实测片片贴触）。"""
    pieces_by_id = {}
    pid_meta = {}
    for s in sizes:
        pid = f'{label}_{s}'
        p = _arc_piece(pid, label, s, r_in=1550.0 + (float(s) - 28.0) * 40.0)
        pieces_by_id[pid] = p
        poly = erode_polygon(p['polygon'], d_g) if d_g > 0 else p['polygon']
        pid_meta[pid] = {
            'size': s, 'color': '#000000', 'polygon': poly,
            'area_mm2': p['area_mm2'], 'label': label, 'demand': demand,
            'net_polygon': [], 'internal_lines': [], 'notches': [],
            'grain_line': None,
        }
    return pid_meta, pieces_by_id


def _hand_chunk():
    """黄金用例手造 chunk：offset=(10,20) 非零（对拍「减号」错误最敏感）。"""
    return BandChunk(
        pid='WB_g09', label='g09',
        polygon=[[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]],
        offset=(10.0, 20.0),
        members=[
            {'pid': 'g09_30', 'rotation': 0.0, 'translation': [15.0, 25.0]},
            {'pid': 'g09_31', 'rotation': 180.0, 'translation': [115.0, 125.0]},
        ],
        fill_pct=80.0, bbox={'width_mm': 100.0, 'height_mm': 100.0},
        seed=7, d_g=0.4, tol_g=3.0,
    )


# --------------------------------------------------------------- 展开黄金用例

def test_expand_golden_rot180_hand_computed():
    """rot=180 手算对拍：rot_f = m.rot + c.rot；tr_f = R(c.rot)·(m.tr − offset) + c.tr。

    R(180°) = diag(−1,−1)。成员 1：R(180)(5,5)+(1000,500) = (995,495)；
    成员 2：R(180)(105,105)+(1000,500) = (895,395)，rot_f = (180+180)%360 = 0。
    若 offset 误用加号，tr_f 会变 (1015,515)/(1125,605) —— 本断言即锁死减号。
    """
    out = expand_placements(_hand_chunk(), 180.0, (1000.0, 500.0))
    assert len(out) == 2
    assert out[0]['id'] == 'g09_30'
    assert out[0]['rotation'] == 180.0                       # 0 + 180
    assert out[0]['translation'] == pytest.approx([995.0, 495.0], abs=1e-9)
    assert out[1]['id'] == 'g09_31'
    assert out[1]['rotation'] == 0.0                         # (180+180) % 360
    assert out[1]['translation'] == pytest.approx([895.0, 395.0], abs=1e-9)


def test_expand_matches_transform_chain():
    """展开结果与「带内变换 → 减 offset → 组合片变换」三步链逐点等价（权威语义）。

    覆盖 c.rot ∈ {0, 180, 177}（0/180 为主解仅有的两个朝向，177 验证任意角公式）；
    tr_f 与 m.rot 无关（成员自转已折入 R(rot_f)），两个成员 tr_f 差恒 = R(c.rot)·Δm。
    """
    chunk = _hand_chunk()
    sample = [(3.0, 7.0), (40.0, 7.0), (40.0, 33.0), (3.0, 33.0)]
    for c_rot, c_tr in [(0.0, (100.0, 50.0)), (180.0, (1000.0, 500.0)),
                        (177.0, (300.0, 200.0))]:
        out = expand_placements(chunk, c_rot, c_tr)
        for m, e in zip(chunk.members, out):
            direct = _transform_polygon(sample, e['rotation'], e['translation'])
            band = _transform_polygon(sample, m['rotation'], m['translation'])
            shifted = [(x - chunk.offset[0], y - chunk.offset[1]) for x, y in band]
            chained = _transform_polygon(shifted, c_rot, c_tr)
            for (dx, dy), (cx, cy) in zip(direct, chained):
                assert abs(dx - cx) < 1e-6 and abs(dy - cy) < 1e-6, (c_rot, m)


def test_expand_tolerates_negative_composite_rotation():
    """spyrrow 可回负角（实测 -180.0）：-180 与 180 展开结果一致（%360 归一）。"""
    a = expand_placements(_hand_chunk(), -180.0, (1000.0, 500.0))
    b = expand_placements(_hand_chunk(), 180.0, (1000.0, 500.0))
    assert a == b


# --------------------------------------------- build_band_plan 真实求解路径

def test_build_band_plan_conservation_pid_and_ordering():
    """副本守恒 14/14 + WB_ pid + 成员 size-major 定序（同码相邻）+ 归一化在原点。"""
    pid_meta, pieces = _band_ctx()
    chunk = build_band_plan(pid_meta, pieces, label='g05', seed=0)

    total_demand = sum(m['demand'] for m in pid_meta.values())
    assert total_demand == 14                                    # 5336 g05: 7 码 × 2
    assert chunk.total_demand == 14
    assert all(m['pid'] in pid_meta for m in chunk.members)      # 无 WB_ 混入成员
    assert chunk.pid == f'{COMPOSITE_PID_PREFIX}g05'             # WB_g05
    assert list(COMPOSITE_ORIENTATIONS) == [0.0, 180.0]          # FR-8 不带抖动
    assert chunk.n_members == 14 and chunk.total_demand == chunk.n_members

    # size-major：成员输出按 (size, pid, 几何) 定序 —— 同码副本列表相邻
    sizes_seq = [pid_meta[m['pid']]['size'] for m in chunk.members]
    assert sizes_seq == sorted(sizes_seq)

    # 平移归一化：组合片轮廓落在原点附近（min ≥ −0.5，max ≤ bbox + 0.5）
    xs = [p[0] for p in chunk.polygon]
    ys = [p[1] for p in chunk.polygon]
    assert min(xs) > -0.5 and min(ys) > -0.5
    assert max(xs) < chunk.bbox['width_mm'] + 0.5
    assert max(ys) < chunk.bbox['height_mm'] + 0.5

    # 带内填充率口径：实际占用 bbox（非全幅 1910），矩形紧排应显著高于 45% 下限
    assert chunk.fill_pct > 45.0
    # US-014：组合片须进主解条带（build_instance strip=min(gate, PLOT_SAFE_MAX_Y_MM)
    # =1910）—— 带内求解幅宽已同口径钳制，高度 <= 1910（等高合法：主解 y=0 可放）。
    from materialsorting.nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
    assert 0 < chunk.bbox['width_mm']
    assert chunk.bbox['height_mm'] <= PLOT_SAFE_MAX_Y_MM + 1e-6


def test_build_band_plan_envelope_assertion():
    """包络断言：union(成员原轮廓@展开位) ⊆ composite@主解位 ⊕ d_g（容差 0.5mm）。

    c.rot 取主解仅有的两个朝向 0/180（FR-8）；成员用**原始**轮廓（pieces_by_id 口径）。
    """
    pid_meta, pieces = _band_ctx()
    chunk = build_band_plan(pid_meta, pieces, label='g05', seed=0)
    for c_rot, c_tr in [(0.0, (700.0, 300.0)), (180.0, (2000.0, 1500.0))]:
        expanded = expand_placements(chunk, c_rot, c_tr)
        assert len(expanded) == 14                               # 守恒（展开侧）
        comp_world = Polygon(_transform_polygon(chunk.polygon, c_rot, c_tr))
        member_union = unary_union([
            Polygon(_transform_polygon(
                pieces[e['id']]['polygon'], e['rotation'], e['translation']))
            for e in expanded
        ])
        padded = comp_world.buffer(chunk.d_g + 0.5)              # ⊕ d_g，容差 0.5mm
        assert padded.contains(member_union), (c_rot, c_tr)
        # 展开结果无 WB_ 泄漏（id 全为成员 pid）
        assert all(e['id'] in pid_meta for e in expanded)


# --------------------------------------------------------------- 异常路径

def test_zero_copies_raises_value_error():
    """0 副本：label 不存在 / 该 label 全部 demand=0 → ValueError（求解前早退）。"""
    pid_meta, pieces = _band_ctx()
    with pytest.raises(ValueError, match='0 副本'):
        build_band_plan(pid_meta, pieces, label='g99', seed=0)
    zero_meta = {pid: {**m, 'demand': 0} for pid, m in pid_meta.items()}
    with pytest.raises(ValueError, match='0 副本'):
        build_band_plan(zero_meta, pieces, label='g05', seed=0)


def test_single_copy_raises_degenerate_band():
    """总副本 1（单片）→ DegenerateBand（无成对/聚簇意义，求解前早退）。"""
    pid_meta, pieces = _band_ctx(sizes=(28,), demand=1)
    assert sum(m['demand'] for m in pid_meta.values()) == 1
    with pytest.raises(DegenerateBand, match='总副本 1'):
        build_band_plan(pid_meta, pieces, label='g05', seed=0)


def test_fill_below_floor_raises_band_quality_error():
    """fill < 下限 → BandQualityError（禁止无声 shelf 兜底）。

    v2 矩形链构造确定性 fill ≈116%（腐蚀轮廓贴触 ⇒ 原轮廓接触处 ≤2·d_g 重叠），
    下限抬到 130% 必触发 —— 构造确定性使断言不依赖任何求解器行为。
    """
    pid_meta, pieces = _band_ctx()
    with pytest.raises(BandQualityError, match='填充率'):
        build_band_plan(pid_meta, pieces, label='g05', seed=0, fill_floor=130.0)


# --------------------------------------------------------------- 确定性

def test_band_seed_crc32_derivation():
    """band seed = zlib.crc32(f'{seed}|{label}') 派生：跨 seed / 跨 label 可区分。"""
    assert band_seed_for(0, 'g05') == zlib.crc32(b'0|g05')
    assert band_seed_for(1, 'g05') == zlib.crc32(b'1|g05')
    assert band_seed_for(0, 'g09') == zlib.crc32(b'0|g09')
    assert band_seed_for(0, 'g05') != band_seed_for(1, 'g05')
    assert band_seed_for(0, 'g05') != band_seed_for(0, 'g09')
    assert isinstance(band_seed_for(0, 'g05'), int)


def test_build_band_plan_deterministic_same_seed():
    """同 seed 两跑 to_dict JSON 相等（num_workers 锁 1 + crc32 seed + 纯几何产物）。"""
    pid_meta, pieces = _band_ctx()
    c1 = build_band_plan(pid_meta, pieces, label='g05', seed=0)
    c2 = build_band_plan(pid_meta, pieces, label='g05', seed=0)
    j1 = json.dumps(c1.to_dict(), sort_keys=True)
    j2 = json.dumps(c2.to_dict(), sort_keys=True)
    assert j1 == j2
    # JSON 可序列化（确定性对拍口径）+ seed 字段即派生 seed
    doc = json.loads(j1)
    assert doc['seed'] == band_seed_for(0, 'g05') == c1.seed
    # 跨 seed 派生 seed 不同（多 seed 连跑各自独立可重放）
    c3 = build_band_plan(pid_meta, pieces, label='g05', seed=1)
    assert c3.seed == band_seed_for(1, 'g05')


# ------------------------------------------------- v2 构造性链形态（版师判据）

def test_arc_chain_contact_gap_and_form():
    """v2 版师形态（弧形单链机制）：链内贴触 ≤ ``CHAIN_GAP_EPS_MM`` + 开口朝左
    + 最大码在最右（降序构造 + 整链点对称翻转 —— 与 build_band_plan 第 2 步同序）。"""
    from materialsorting.nesting_engine.waist_band import (
        CHAIN_GAP_EPS_MM, _chain_gap, _chain_nest, _flip_chain, _geom_at,
        _norm_chain, _opening_side)
    pid_meta, _pieces = _arc_ctx(demand=1)
    polys = {pid: waist_band._clean_polygon(m['polygon'])
             for pid, m in pid_meta.items()}
    chain_pids = sorted(
        pid_meta, key=lambda p: waist_band._member_sort_key(pid_meta[p], p),
        reverse=True)                     # size 降序（版师链序）
    chain = _norm_chain(_flip_chain(_chain_nest(chain_pids, polys)), polys)
    assert _chain_gap(chain, polys) <= CHAIN_GAP_EPS_MM       # 片片贴触
    assert _opening_side(chain, polys) == 'left'              # 开口朝左
    cx = {m['pid']: _geom_at(polys[m['pid']], m['rotation'],
                             m['translation']).centroid.x for m in chain}
    assert max(cx, key=cx.get) == chain_pids[0]               # 最大码最右


def test_arc_band_chunk_two_chains():
    """弧形全链路（demand=2 → 双链堆叠）：守恒 14/14 + WB_ pid + fill 过灾难下限
    + 带高进主解条带 + 整带开口朝左（链同向、堆叠不翻链）。"""
    from materialsorting.nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
    from materialsorting.nesting_engine.waist_band import _opening_side
    pid_meta, pieces = _arc_ctx()
    chunk = build_band_plan(pid_meta, pieces, label='g05', seed=0)
    assert chunk.n_members == 14 and chunk.total_demand == 14
    assert chunk.pid == f'{COMPOSITE_PID_PREFIX}g05'
    assert chunk.fill_pct > 45.0                             # 灾难形态下限
    assert 0 < chunk.bbox['width_mm']
    assert chunk.bbox['height_mm'] <= PLOT_SAFE_MAX_Y_MM + 1e-6
    polys = {m['pid']: waist_band._clean_polygon(pid_meta[m['pid']]['polygon'])
             for m in chunk.members}
    assert _opening_side(chunk.members, polys) == 'left'


# ------------------------------------- 直腰头平坦模式（2026-08-24 版师指正）

def _strip_ctx(label='g01', sizes=(29, 30, 31, 32, 33, 34, 35, 36, 38, 40),
               demand=2, w=68.0, d_g=0.4):
    """882# g01 直腰头同构上下文：10 码 × demand 2 = 20 副本，竖条宽 ≈68、
    高随码递增（999→1351，实测族 999~1286 同构）—— 高度互异使修复前的
    「交替翻转 + 上下换锚」对角阶梯乱象可被断言判别（等高矩形看不出来）。"""
    pieces_by_id, pid_meta = {}, {}
    for s in sizes:
        h = 999.0 + (float(s) - 29.0) * 32.0
        pid = f'{label}_{s}'
        p = _rect_piece(pid, label, s, w, h)
        pieces_by_id[pid] = p
        poly = erode_polygon(p['polygon'], d_g) if d_g > 0 else p['polygon']
        pid_meta[pid] = {
            'size': s, 'color': '#000000', 'polygon': poly,
            'area_mm2': p['area_mm2'], 'label': label, 'demand': demand,
            'net_polygon': [], 'internal_lines': [], 'notches': [],
            'grain_line': None,
        }
    return pid_meta, pieces_by_id


def test_flat_detector_separates_rect_from_arc():
    """``_is_flat_piece`` 判据分离：矩形直条 True（质心短轴偏移 0.00mm）、
    月牙弧 False（偏移 ~18-22mm）—— 与 882# g01 / 5336 g05 实测分离度 18× 同构。"""
    from materialsorting.nesting_engine.waist_band import _is_flat_piece
    rect_meta, _ = _band_ctx(sizes=(28, 29))
    arc_meta, _ = _arc_ctx(sizes=(28, 29))
    for pid, m in rect_meta.items():
        g = waist_band._valid_geometry(waist_band._clean_polygon(m['polygon']))
        assert _is_flat_piece(g) is True, pid
    for pid, m in arc_meta.items():
        g = waist_band._valid_geometry(waist_band._clean_polygon(m['polygon']))
        assert _is_flat_piece(g) is False, pid


def test_flat_band_chunk_form():
    """直腰头全链路（882# g01 同构，demand=2 = 20 副本单链）：片片 rot=0
    无翻转 + 全员底边 y=0 同底齐平 + **全局从短到长**（多副本单链单调阶梯，
    非「每码第 k 副本」N 链并排的交叉深谷）+ 大码最右/小码最左 + 带高=最高
    单片 + 腐蚀条带宽合计（缝隙 0）—— 版师图2 形态程序化判据。"""
    from materialsorting.nesting_engine.waist_band import _geom_at
    pid_meta, pieces = _strip_ctx()
    chunk = build_band_plan(pid_meta, pieces, label='g01', seed=0)
    assert chunk.n_members == 20 and chunk.total_demand == 20   # 10 码 × 2 守恒
    assert chunk.pid == f'{COMPOSITE_PID_PREFIX}g01'
    assert chunk.fill_pct > 45.0                                # 灾难形态下限
    polys = {pid: waist_band._clean_polygon(m['polygon'])
             for pid, m in pid_meta.items()}
    gs = [(m['pid'], _geom_at(polys[m['pid']], m['rotation'], m['translation']))
          for m in chunk.members]
    assert all(m['rotation'] == 0.0 for m in chunk.members)     # 无 180 翻转
    assert all(abs(g.bounds[1]) < 1e-6 for _pid, g in gs)       # 同底齐平
    # 全局单调阶梯：按质心 x 升序 ⇔ 码序非降（同码副本相邻）—— 旧 N 链并排
    # 产出 [29..40, 29..40] 在此断言必挂（链交界「最大|最小」交叉深谷）
    x_sorted = [pid_meta[pid]['size'] for pid, _g
                in sorted(gs, key=lambda t: t[1].centroid.x)]
    assert x_sorted == sorted(x_sorted)
    # 同底 ⇒ 带高 = 最高单片**原始**轮廓高（组合片 bbox 由原始 union 腐蚀而来，
    # 成员 polys 已腐蚀矮 2·d_g）—— 顶阶梯而非上下交替的「最高+最低」和
    orig_h = max(Polygon(pieces[pid]['polygon']).bounds[3] for pid in pieces)
    assert chunk.bbox['height_mm'] == pytest.approx(orig_h, abs=1.0)
    # 版师码序：全局升序 ⇒ 最大码最右、最小码最左（两端同码副本）
    assert max(gs, key=lambda t: t[1].centroid.x)[0] == 'g01_40'
    assert min(gs, key=lambda t: t[1].centroid.x)[0] == 'g01_29'
    # 紧排无重叠：union 面积 = Σ 片面积（贴触合法、重叠非法）
    assert unary_union([g for _pid, g in gs]).area == pytest.approx(
        sum(g.area for _pid, g in gs), rel=1e-9)
    # 缝隙 0：带宽 = 20 片 × 腐蚀宽（68−2·d_g）—— 与顺序无关，面积零代价
    assert chunk.bbox['width_mm'] == pytest.approx(
        20 * (68.0 - 2 * 0.4), abs=2.0)


def test_flat_band_nonuniform_demand():
    """直腰头副本数不均匀（quantities 矩阵可异码不同副本）：全副本单链全局
    升序仍成立 —— 每码按 demand 展开、同码相邻、整带单调无交叉深谷。"""
    from collections import Counter

    from materialsorting.nesting_engine.waist_band import _geom_at
    demands = {29: 1, 30: 2, 31: 3, 32: 2, 33: 1, 34: 2,
               35: 1, 36: 2, 38: 1, 40: 2}
    pid_meta, pieces = _strip_ctx()
    for pid, m in pid_meta.items():
        m['demand'] = demands[m['size']]
    chunk = build_band_plan(pid_meta, pieces, label='g01', seed=0)
    total = sum(demands.values())
    assert chunk.n_members == total and chunk.total_demand == total
    polys = {pid: waist_band._clean_polygon(m['polygon'])
             for pid, m in pid_meta.items()}
    gs = sorted(
        ((_geom_at(polys[m['pid']], m['rotation'],
                   m['translation']).centroid.x, pid_meta[m['pid']]['size'])
         for m in chunk.members), key=lambda t: t[0])
    sizes_seq = [s for _x, s in gs]
    assert sizes_seq == sorted(sizes_seq)                     # 全局单调
    assert Counter(sizes_seq) == Counter(demands)             # 副本守恒
    assert all(m['rotation'] == 0.0 for m in chunk.members)   # 无翻转
    assert all(abs(_geom_at(polys[m['pid']], m['rotation'],
                            m['translation']).bounds[1]) < 1e-6
               for m in chunk.members)                        # 同底齐平


def test_flat_band_chunk_deterministic():
    """直腰头路径确定性：同 seed 两跑 to_dict JSON 逐字节相等（纯几何构造、无 RNG）。"""
    pid_meta, pieces = _strip_ctx()
    j1 = json.dumps(build_band_plan(pid_meta, pieces, label='g01', seed=0).to_dict(),
                    sort_keys=True)
    j2 = json.dumps(build_band_plan(pid_meta, pieces, label='g01', seed=0).to_dict(),
                    sort_keys=True)
    assert j1 == j2


# --------------------------------------------------------------- 分层纯度

def test_module_layering_purity():
    """分层未反向：waist_band.py 模块级 import 只向下/同层（nesting_engine ← nesting_bounds），
    禁 import web（AST 守卫，套路同 test_cli_lns.test_module_layering_purity）。"""
    src = Path(waist_band.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'math', 'zlib', 'dataclasses',
               'shapely', 'materialsorting', 'nesting_bounds', 'nesting_engine'}
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert not mod.startswith('materialsorting.web'), \
                '模块级禁止 import web（分层单向）'
            # 相对 import（level≥1）解析到本包兄弟模块（constraints 等），视为同层
            names = {'nesting_engine'} if node.level else {mod.split('.')[0]}
        else:
            continue
        assert names <= allowed, sorted(names - allowed)
    # 源级哨兵：任何 web 引用（含函数内延迟 import）都不允许
    assert 'materialsorting.web' not in src
    assert 'from ..web' not in src and 'from .web' not in src


def test_expand_rotation_normalized():
    """展开 rotation 归一化到 [0,360)：成员 183° + 组合片 180° → 3.0°。"""
    chunk = BandChunk(
        pid='WB_g05', label='g05',
        polygon=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
        offset=(0.0, 0.0),
        members=[{'pid': 'g05_28', 'rotation': 183.0, 'translation': [0.0, 0.0]}],
        fill_pct=90.0, bbox={'width_mm': 10.0, 'height_mm': 10.0},
        seed=1, d_g=0.4, tol_g=3.0,
    )
    out = expand_placements(chunk, 180.0, (0.0, 0.0))
    assert out[0]['rotation'] == pytest.approx(3.0, abs=1e-9)
    # 旋转量级无关紧要，但 tr 用 R(180)：translation = R(180)·(0,0) + (0,0) = (0,0)
    assert out[0]['translation'] == pytest.approx([0.0, 0.0], abs=1e-9)

