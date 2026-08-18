"""US-002 求解/导出层 label 键测试。

覆盖：
  1. ``label_color``（LABEL_COLORS 单一真相源）：同码同色、16 色循环、非 g 码兜底；
  2. ``label_aci``（DXF ACI 公式 ``((code-1) % 24) + 1``）：正码段、循环、兜底；
  3. ``build_instance`` per_type 按 ``label`` 命中即覆盖（2026-08-18 回退 US-004 矩阵化
     后单级：erode/tol 落在该 g 码**全部码号**上），未命中 / 旧 ptype 键 / 旧两级键为 no-op；
  4. ``build_instance`` quantities demand 直译（0 跳过、N 多副本、total_area×demand）；
  5. pid_meta / 中间键全 label 化（无 ptype、color=label_color）；
  6. ``constraints.validate`` 删成对齐套校验后对无 ptype/side 的裁片直接可用。
"""
from __future__ import annotations

from collections import namedtuple

import pytest

from materialsorting.nesting_engine.sparrow_baseline import (
    LABEL_PALETTE, DEFAULT_COLOR, label_color,
)
from materialsorting.nesting_engine.constraints import validate
from materialsorting.web.export import label_aci


def _piece(pid, label, size, w=500.0, h=800.0):
    """合成 v2 schema 裁片（label 键、无 ptype/side）。"""
    return {
        'pid': pid, 'label': label, 'size': size,
        'polygon': [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]],
        'area_mm2': w * h,
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
    }


# --------------------------------------------- label_color（LABEL_COLORS 单一真相源）

def test_label_color_same_code_same_color_and_palette_cycle():
    """g01→表头色、g17 循环回 g01 色（16 色循环表）；同码恒同色。"""
    assert label_color('g01') == LABEL_PALETTE[0]
    assert label_color('g02') == LABEL_PALETTE[1]
    assert label_color('g16') == LABEL_PALETTE[15]
    assert label_color('g17') == LABEL_PALETTE[0]      # (17-1) % 16 == 0
    assert label_color('g33') == LABEL_PALETTE[0]      # 再绕一圈仍回表头
    assert len(set(LABEL_PALETTE)) == 16               # 16 色互不相同
    assert label_color('g05') == label_color('g05')


def test_label_color_invalid_falls_back_to_default():
    """None / 非 g 码（旧 ptype 名等）兜底 DEFAULT_COLOR。"""
    assert label_color(None) == DEFAULT_COLOR
    assert label_color('前片') == DEFAULT_COLOR
    assert label_color('') == DEFAULT_COLOR
    assert label_color(123) == DEFAULT_COLOR


# --------------------------------------------- label_aci（DXF ACI 公式）

def test_label_aci_formula_and_cycle():
    """ACI = ((code-1) % 24) + 1：g01→1、g24→24、g25→1；非 g 码兜底 7。"""
    assert label_aci('g01') == 1
    assert label_aci('g10') == 10
    assert label_aci('g24') == 24
    assert label_aci('g25') == 1       # ((25-1) % 24) + 1
    assert label_aci('g49') == 1
    assert label_aci(None) == 7
    assert label_aci('前片') == 7


# --------------------------------------------- build_instance per_type（label 单级命中）

def _build(pieces, **kw):
    from materialsorting.web.solver import build_instance
    return build_instance(pieces, 1980.0, time_budget=1, seed=0, **kw)


def test_per_type_label_hit_overrides_erode_and_tol():
    """per_type.g01={d,tol} 命中 → g01 全部码号被 erode/放开旋转，g02 不受影响。"""
    pieces = [
        _piece('g01_28', 'g01', 28), _piece('g01_30', 'g01', 30),
        _piece('g02_28', 'g02', 28),
    ]
    inst, _cfg, meta, _area, n_eroded = _build(
        pieces, per_type={'g01': {'d': 2.0, 'tol': 10.0}})

    assert n_eroded == 2                                   # g01 两个码号都腐蚀（label 级命中）
    # erode 后 g01 多边形仍是矩形（shapely 对矩形的腐蚀结果），面积变小
    g01_poly = meta['g01_28']['polygon']
    xs = [p[0] for p in g01_poly]
    assert max(xs) < 500.0                                 # 500 - 2×2 收边
    # 旋转公差命中 → 离散角度集扩展（10° 步进 1° 应含 10.0）
    items = {it.id: it for it in inst.items}
    assert 10.0 in items['g01_28'].allowed_orientations
    assert 10.0 in items['g01_30'].allowed_orientations    # 同 g 码其他码号同样生效
    assert list(items['g02_28'].allowed_orientations) == [0.0, 180.0]   # 未命中保持布纹线


def test_per_type_miss_falls_back_and_old_keys_are_noop():
    """label 不命中 / 旧 ptype 键 / 旧两级（US-004 矩阵化）键 → 回退全局默认（0/0），
    无 erode、锁 {0,180}；旧两级 payload 在 label 层取不到 d/tol，对称向后兼容不崩。"""
    pieces = [_piece('g01_28', 'g01', 28), _piece('g02_28', 'g02', 28)]
    # label g99 不命中
    _inst, _cfg, _meta, _area, n1 = _build(pieces, per_type={'g99': {'d': 2.0}})
    assert n1 == 0
    # 旧 ptype 键（v1 时代的中文片型名）不再命中 → no-op
    _inst, _cfg, _meta, _area, n2 = _build(pieces, per_type={'前片': {'d': 5.0}})
    assert n2 == 0
    # 旧两级 payload（US-004 矩阵化时代的 {label:{sizeKey:{...}}}）→ label 层取不到
    # d/tol → 回退默认，no-op 不崩（未刷新的旧前端页面残留 payload 场景）
    _inst, _cfg, _meta, _area, n3 = _build(
        pieces, per_type={'g01': {'28': {'d': 2.0, 'tol': 10.0}}})
    assert n3 == 0
    # 命中但只给 d（缺 tol）→ tol 回退全局默认 0
    inst, _cfg, _meta, _area, n4 = _build(pieces, per_type={'g02': {'d': 1.0}})
    assert n4 == 1
    items = {it.id: it for it in inst.items}
    assert list(items['g02_28'].allowed_orientations) == [0.0, 180.0]


def test_per_type_clamped_by_global_caps():
    """d/tol 超全局上限（10mm / 45°）收边，不透传超限值。"""
    pieces = [_piece('g01_28', 'g01', 28)]
    from materialsorting.nesting_engine.constraints import (
        MAX_OVERLAP_MM, MAX_ROTATION_TOL_DEG,
    )
    _inst, _cfg, _meta, _area, n_eroded = _build(
        pieces, per_type={'g01': {'d': 99.0, 'tol': 99.0}})
    assert n_eroded == 1
    assert MAX_OVERLAP_MM == 10.0 and MAX_ROTATION_TOL_DEG == 45.0   # 上限口径锁定


# --------------------------------------------- build_instance quantities demand

def test_quantities_demand_translation():
    """quantities 直译：0 跳过、N 多副本、total_area = Σ(area×demand)。"""
    pieces = [_piece('g01_28', 'g01', 28), _piece('g02_28', 'g02', 28, w=300.0, h=400.0)]
    inst, _cfg, meta, total_area, _n = _build(
        pieces, quantities={'g01': {'28': 2}, 'g02': {'28': 0}})

    items = {it.id: it for it in inst.items}
    assert set(items) == {'g01_28'}                       # g02 demand=0 跳过
    assert items['g01_28'].demand == 2
    assert meta['g01_28']['demand'] == 2                  # 透传（前端建 N 副本）
    assert total_area == pytest.approx(500.0 * 800.0 * 2)  # 面积 × demand


def test_pid_meta_is_label_keyed_with_label_color():
    """pid_meta 无 ptype 键；color = label_color(label)（16 色循环表单一真相源）。"""
    pieces = [_piece('g01_28', 'g01', 28)]
    _inst, _cfg, meta, _area, _n = _build(pieces)
    m = meta['g01_28']
    assert 'ptype' not in m
    assert m['label'] == 'g01'
    assert m['color'] == label_color('g01') == LABEL_PALETTE[0]


# --------------------------------------------- constraints.validate（成对齐套校验已删）

def test_validate_works_without_ptype_side_attributes():
    """validate 不再读 ptype/side（成对齐套校验删除），裸 pid 裁片可直接校验。"""
    P = namedtuple('P', 'pid')
    poly = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    placed_world = [(P('g01_28'), poly), (P('g02_28'), poly)]
    ok, issues = validate(placed_world, placed_world, used=500.0, gate=1980.0, res=1.0)
    assert ok and issues == []

    # 超门幅仍报issue（其余校验不动）
    bad = [(P('g01_28'), [(0.0, 0.0), (3000.0, 0.0), (3000.0, 100.0), (0.0, 100.0)])]
    ok2, issues2 = validate(bad, bad, used=500.0, gate=1980.0, res=1.0)
    assert not ok2 and any('超门幅' in s for s in issues2)
