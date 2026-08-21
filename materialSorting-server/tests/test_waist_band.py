"""US-009 waist_band 核心模块测试。

覆盖（tasks/prd-waist-band.md US-009 验收标准）：
1. 展开黄金用例：rot=180 + 带偏移成员**手算对拍**（权威式 rot_f / tr_f，offset 减号）
   + 变换链等价（先带内变换、减 offset、再组合片变换 == 直接展开）；
2. 包络断言：union(成员原轮廓@展开位) ⊆ composite@主解位 ⊕ d_g（容差 0.5mm）；
3. 副本守恒：Σ 展开成员条数 == Σ demand（5336 g05 同构 7 码 × 2 = 14/14）；
4. 异常路径：0 副本 ValueError、总副本 1 DegenerateBand、fill 超限 BandQualityError；
5. 确定性：band seed = zlib.crc32 派生（勿用 hash()）、同 seed 两跑 to_dict JSON 相等；
6. 分层纯度：模块级不 import web（AST 守卫，套路同 test_cli_lns）。

真实求解用 2s 小预算 + 合成矩形（结构同 5336 g05：7 码 × demand 2）。
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

# 真实求解预算（秒）：14 片矩形 strip 解足够收敛，整文件实测 ~10s。
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

    矩形紧排 fill 实测 <102%（成员原轮廓接触处 ≤2·d_g 重叠），下限抬到 103% 必触发
    —— 不依赖求解质量，杜绝用例对求解器行为的脆弱耦合。
    """
    pid_meta, pieces = _band_ctx()
    with pytest.raises(BandQualityError, match='填充率'):
        build_band_plan(pid_meta, pieces, label='g05', seed=0,
                        time_budget=_SOLVE_BUDGET_S, fill_floor=103.0)


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

