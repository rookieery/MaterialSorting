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
   最大码在最右（降序构造 + 整链点对称翻转）。

合成夹具：矩形（结构同 5336 g05：7 码 × demand 2）+ 月牙弧（曲率相近异码嵌套）。
``time_budget`` 形参 v2 起 deprecated no-op（构造性链构造毫秒级，传值仅验证兼容）。
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

# v1 带内求解预算（秒）：v2 起 deprecated no-op，传值仅为形参兼容回归。
_SOLVE_BUDGET_S = 2


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
    chunk = build_band_plan(pid_meta, pieces, label='g05', seed=0,
                            time_budget=_SOLVE_BUDGET_S)

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
    chunk = build_band_plan(pid_meta, pieces, label='g05', seed=0,
                            time_budget=_SOLVE_BUDGET_S)
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
        build_band_plan(pid_meta, pieces, label='g99', seed=0,
                        time_budget=_SOLVE_BUDGET_S)
    zero_meta = {pid: {**m, 'demand': 0} for pid, m in pid_meta.items()}
    with pytest.raises(ValueError, match='0 副本'):
        build_band_plan(zero_meta, pieces, label='g05', seed=0,
                        time_budget=_SOLVE_BUDGET_S)


def test_single_copy_raises_degenerate_band():
    """总副本 1（单片）→ DegenerateBand（无成对/聚簇意义，求解前早退）。"""
    pid_meta, pieces = _band_ctx(sizes=(28,), demand=1)
    assert sum(m['demand'] for m in pid_meta.values()) == 1
    with pytest.raises(DegenerateBand, match='总副本 1'):
        build_band_plan(pid_meta, pieces, label='g05', seed=0,
                        time_budget=_SOLVE_BUDGET_S)


def test_fill_below_floor_raises_band_quality_error():
    """fill < 下限 → BandQualityError（禁止无声 shelf 兜底）。

    v2 矩形链构造确定性 fill ≈116%（腐蚀轮廓贴触 ⇒ 原轮廓接触处 ≤2·d_g 重叠），
    下限抬到 130% 必触发 —— 构造确定性使断言不依赖任何求解器行为。
    """
    pid_meta, pieces = _band_ctx()
    with pytest.raises(BandQualityError, match='填充率'):
        build_band_plan(pid_meta, pieces, label='g05', seed=0,
                        time_budget=_SOLVE_BUDGET_S, fill_floor=130.0)


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
    c1 = build_band_plan(pid_meta, pieces, label='g05', seed=0,
                         time_budget=_SOLVE_BUDGET_S)
    c2 = build_band_plan(pid_meta, pieces, label='g05', seed=0,
                         time_budget=_SOLVE_BUDGET_S)
    j1 = json.dumps(c1.to_dict(), sort_keys=True)
    j2 = json.dumps(c2.to_dict(), sort_keys=True)
    assert j1 == j2
    # JSON 可序列化（US-011 band_runs 工件口径）+ seed 字段即派生 seed
    doc = json.loads(j1)
    assert doc['seed'] == band_seed_for(0, 'g05') == c1.seed
    # 跨 seed 派生 seed 不同（多 seed 连跑各自独立可重放）
    c3 = build_band_plan(pid_meta, pieces, label='g05', seed=1,
                         time_budget=_SOLVE_BUDGET_S)
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
    chunk = build_band_plan(pid_meta, pieces, label='g05', seed=0,
                            time_budget=_SOLVE_BUDGET_S)
    assert chunk.n_members == 14 and chunk.total_demand == 14
    assert chunk.pid == f'{COMPOSITE_PID_PREFIX}g05'
    assert chunk.fill_pct > 45.0                             # 灾难形态下限
    assert 0 < chunk.bbox['width_mm']
    assert chunk.bbox['height_mm'] <= PLOT_SAFE_MAX_Y_MM + 1e-6
    polys = {m['pid']: waist_band._clean_polygon(pid_meta[m['pid']]['polygon'])
             for m in chunk.members}
    assert _opening_side(chunk.members, polys) == 'left'


# ------------------------------------------------- US-015 混带填料（v1.1）

def _mixed_ctx(filler_sizes=(28,), filler_demand=4, fw=40.0, fh=100.0):
    """混带上下文：腰 g05（_band_ctx 同构 7 码 × 2 = 14 副本）+ 填料 g06 小矩形。

    返回 (pid_meta, pieces_by_id, total_waist, total_filler)。填料小件形态
    （40×100 ≪ 60×300 腰片）对应真实母版里 g07/g08 类小裁片塞肋间空隙场景。
    """
    pid_meta, pieces = _band_ctx()
    for s in filler_sizes:
        pid = f'g06_{s}'
        p = _rect_piece(pid, 'g06', s, fw, fh)
        pieces[pid] = p
        poly = erode_polygon(p['polygon'], 0.4) if 0.4 > 0 else p['polygon']
        pid_meta[pid] = {
            'size': s, 'color': '#000000', 'polygon': poly,
            'area_mm2': p['area_mm2'], 'label': 'g06', 'demand': filler_demand,
            'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
        }
    total_filler = filler_demand * len(filler_sizes)
    return pid_meta, pieces, 14, total_filler


def test_fillers_conservation_members_and_dict():
    """US-015 守恒口径：腰 14 + 填料 4 = 18 副本全进 members；fillers 记录进 chunk/to_dict。"""
    pid_meta, pieces, n_waist, n_filler = _mixed_ctx()
    chunk = build_band_plan(pid_meta, pieces, label='g05', seed=0,
                            fillers=['g06'], filler_ds={'g06': 0.4},
                            time_budget=_SOLVE_BUDGET_S)
    filler_pids = {pid for pid, m in pid_meta.items() if m['label'] == 'g06'}
    waist_pids = {pid for pid, m in pid_meta.items() if m['label'] == 'g05'}
    member_pids = [m['pid'] for m in chunk.members]
    # 守恒：腰 + 填料全部副本（无 WB_ 混入、无丢片）
    assert chunk.n_members == n_waist + n_filler == 18
    assert member_pids.count('g06_28') == n_filler
    assert sum(1 for p in member_pids if p in waist_pids) == n_waist
    assert all(p in waist_pids | filler_pids for p in member_pids)
    assert chunk.total_demand == n_waist + n_filler
    # fillers 序列化（band_runs 工件回放口径）
    assert chunk.fillers == ('g06',)
    assert chunk.to_dict()['fillers'] == ['g06']
    # 填料进了带内：fill 分子 = 腰 + 填料面积和（同 bbox 口径），仍过灾难下限
    assert chunk.fill_pct > 45.0


def test_fillers_envelope_and_expansion():
    """US-015 包络断言（填料同口径）：union(成员原轮廓@展开位) ⊆ composite ⊕ d_g
    + 展开无 WB_ 泄漏 + 混带下腰成员原轮廓重叠深度 ≤ 2·BAND_INNER_D_MM + 0.5
    （带内碰撞补腐蚀把肋间切口端部开到小件可入宽度 —— 重叠深度即腐蚀深度口径：
    erode(e) 贴触 ⇒ 原轮廓接触区重叠 ≤ 2e，混带 e=BAND_INNER_D_MM、纯腰 e=d_g）。"""
    from materialsorting.nesting_engine.waist_band import BAND_INNER_D_MM
    assert 2.0 <= BAND_INNER_D_MM <= 4.0      # 版师口径 2~4mm 取保守端
    pid_meta, pieces, _n_w, _n_f = _mixed_ctx()
    chunk = build_band_plan(pid_meta, pieces, label='g05', seed=0,
                            fillers=['g06'], filler_ds={'g06': 0.4},
                            time_budget=_SOLVE_BUDGET_S)
    waist_pids = {pid for pid, m in pid_meta.items() if m['label'] == 'g05'}
    for c_rot, c_tr in [(0.0, (700.0, 300.0)), (180.0, (2000.0, 1500.0))]:
        expanded = expand_placements(chunk, c_rot, c_tr)
        assert len(expanded) == 18                     # 守恒（展开侧含填料）
        comp_world = Polygon(_transform_polygon(chunk.polygon, c_rot, c_tr))
        member_union = unary_union([
            Polygon(_transform_polygon(
                pieces[e['id']]['polygon'], e['rotation'], e['translation']))
            for e in expanded
        ])
        assert comp_world.buffer(chunk.d_g + 0.5).contains(member_union), (c_rot, c_tr)
        assert all(e['id'] in pid_meta for e in expanded)   # 无 WB_ 泄漏
    # 混带碰撞口径：腰成员原轮廓两两重叠深度 ≤ 2·BAND_INNER_D_MM + 0.5（双侧各腐蚀
    # e 后贴触 —— 深度超过该值即碰撞腐蚀失效）
    geoms = _placed_originals(chunk, pieces)
    half = BAND_INNER_D_MM + 0.25
    for i, a in enumerate(geoms):
        for b in geoms[i + 1:]:
            assert a.buffer(-half).disjoint(b.buffer(-half)), (i, a.distance(b))


def _placed_originals(chunk, pieces_by_id):
    """成员原始轮廓@带内位（包络/间距断言共用口径）。"""
    return [Polygon(_transform_polygon(pieces_by_id[m['pid']]['polygon'],
                                       m['rotation'], m['translation']))
            for m in chunk.members]


def test_arc_fillers_fill_gaps_and_open_ribs():
    """US-015 弧形形态（真实 g05 几何族）：混带 fill 高于纯腰（填料塞进肋间空隙，
    「切口端部开到小件可入宽度」的效果判据）+ 填料全落带内 + 填料-腰原轮廓重叠
    深度 ≤ BAND_INNER_D_MM + d_f + 0.5（碰撞正确性）。"""
    from materialsorting.nesting_engine.waist_band import BAND_INNER_D_MM
    pid_meta, pieces = _arc_ctx()
    for s in (28,):
        pid = 'g06_28'
        p = _rect_piece(pid, 'g06', s, 60.0, 80.0)
        pieces[pid] = p
        pid_meta[pid] = {
            'size': s, 'color': '#000000',
            'polygon': erode_polygon(p['polygon'], 0.4),
            'area_mm2': p['area_mm2'], 'label': 'g06', 'demand': 3,
            'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
        }
    pure = build_band_plan(pid_meta, pieces, label='g05', seed=0,
                           time_budget=_SOLVE_BUDGET_S)
    mixed = build_band_plan(pid_meta, pieces, label='g05', seed=0,
                            fillers=['g06'], filler_ds={'g06': 0.4},
                            time_budget=_SOLVE_BUDGET_S)
    # 填料塞隙效果：fill（分子=腰+填料面积和）高于纯腰，且带板 bbox 不放大
    assert mixed.fill_pct > pure.fill_pct
    assert mixed.bbox['width_mm'] <= pure.bbox['width_mm'] + 1.0
    assert mixed.bbox['height_mm'] <= pure.bbox['height_mm'] + 1.0
    # 填料全落带内（bbox 内），与腰原轮廓重叠深度 ≤ BAND_INNER_D_MM + 0.4 + 0.5
    waist_pids = {pid for pid, m in pid_meta.items() if m['label'] == 'g05'}
    waist_union = unary_union([
        Polygon(_transform_polygon(pieces[m['pid']]['polygon'],
                                   m['rotation'], m['translation']))
        for m in mixed.members if m['pid'] in waist_pids])
    fillers = [
        Polygon(_transform_polygon(pieces[m['pid']]['polygon'],
                                   m['rotation'], m['translation']))
        for m in mixed.members if m['pid'] not in waist_pids]
    assert len(fillers) == 3
    half = BAND_INNER_D_MM + 0.4 + 0.25
    for f in fillers:
        assert f.buffer(-half).disjoint(waist_union.buffer(-half))
        cx, cy = f.centroid.x, f.centroid.y
        assert -1.0 <= cx <= mixed.bbox['width_mm'] + 1.0
        assert -1.0 <= cy <= mixed.bbox['height_mm'] + 1.0


def test_fillers_deterministic_same_seed():
    """混带确定性：同 seed 两跑 to_dict JSON 相等（_fill_gaps 贪心无 RNG）。"""
    pid_meta, pieces, _n_w, _n_f = _mixed_ctx()
    c1 = build_band_plan(pid_meta, pieces, label='g05', seed=0,
                         fillers=['g06'], filler_ds={'g06': 0.4},
                         time_budget=_SOLVE_BUDGET_S)
    c2 = build_band_plan(pid_meta, pieces, label='g05', seed=0,
                         fillers=['g06'], filler_ds={'g06': 0.4},
                         time_budget=_SOLVE_BUDGET_S)
    assert json.dumps(c1.to_dict(), sort_keys=True) == json.dumps(c2.to_dict(), sort_keys=True)


def test_filler_same_as_label_raises():
    """填料 = 主 g 码 → ValueError（fail-fast，服务端校验的兜底防线）。"""
    pid_meta, pieces, _n_w, _n_f = _mixed_ctx()
    with pytest.raises(ValueError, match='不可与主 g 码相同'):
        build_band_plan(pid_meta, pieces, label='g05', seed=0, fillers=['g05'],
                        time_budget=_SOLVE_BUDGET_S)


def test_filler_zero_copies_raises():
    """填料 label 不存在 / 全部 demand=0 → ValueError（0 副本不可混带）。"""
    pid_meta, pieces, _n_w, _n_f = _mixed_ctx()
    with pytest.raises(ValueError, match='0 副本'):
        build_band_plan(pid_meta, pieces, label='g05', seed=0, fillers=['g99'],
                        time_budget=_SOLVE_BUDGET_S)
    zero = {pid: ({**m, 'demand': 0} if m['label'] == 'g06' else m)
            for pid, m in pid_meta.items()}
    with pytest.raises(ValueError, match='0 副本'):
        build_band_plan(zero, pieces, label='g05', seed=0, fillers=['g06'],
                        time_budget=_SOLVE_BUDGET_S)


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

