"""2026-09-19 全端物理口径统一：``_apply_density_dual`` 物理包络换算单测。

背景（bug 复现 run ``web_87eec6_se_36433b_20260919-200515``）：sparrow 自报
width = **erode 碰撞轮廓包络**（per_type d>0 时比毛版短最多 ~d，本例 g02 d=8
短 6.6mm），旧 real_density 分母用它 → 求解器侧利用率偏乐观 +0.07pt
（90.22%），与编辑弹窗物理口径（``computeLayoutStats``：ceil(raw maxX) →
90.15%）分裂。修复 = 主进程换算点把 width_mm/density 换成物理包络 ceil 口径
（前端 ``computeLayoutStats`` 同公式，编辑弹窗为基准）。

测试锁：
  1. ``_physical_width_mm`` = 编辑弹窗同公式（ceil + ε；rotation/mirror 变换
     与 ``export_geometry.apply_transform`` 逐点对拍 = 跨模块公式一致性锚）；
  2. ``_apply_density_dual`` 物理路径（width_sparrow_mm 备查 + density 重算）
     与兼容回退路径（pid_raw 缺席 / pid 不在场 → 旧口径，无 width_sparrow_mm）；
  3. ``_raw_polygon_map`` 降级链（raw_polygon 优先 → polygon 回退 → 跳过空）。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting.web.solver import (
    _apply_density_dual,
    _physical_width_mm,
    _raw_polygon_map,
)


# --------------------------------------------- _physical_width_mm 公式

def test_physical_width_basic_and_ceil():
    """maxX=8659.7754 → ceil 8660（bug run 实测数字）。"""
    pid_raw = {'a': [(0, 0), (100, 0), (100, 50), (0, 50)]}
    placed = [{'id': 'a', 'rotation': 0.0, 'translation': [8559.7754, 0.0]}]
    assert _physical_width_mm(placed, pid_raw) == 8660


def test_physical_width_eps_absorbs_float_noise():
    """整数贴边 + ~1e-13 float 噪声（90° 旋转级）→ 不无辜 +1mm（1100 非 1101）。"""
    pid_raw = {'a': [(0, 0), (100, 0), (100, 50), (0, 50)]}
    placed = [{'id': 'a', 'rotation': 0.0, 'translation': [1000.0000000000001, 0.0]}]
    assert _physical_width_mm(placed, pid_raw) == 1100


def test_physical_width_rotation_180():
    """180°：世界 x ∈ [tx−110, tx−10] → maxX = 490。"""
    pid_raw = {'a': [(10, 0), (110, 0), (110, 50), (10, 50)]}
    placed = [{'id': 'a', 'rotation': 180.0, 'translation': [500.0, 0.0]}]
    assert _physical_width_mm(placed, pid_raw) == 490


def test_physical_width_mirror_parity_with_export_apply_transform():
    """mirror + 任意角与 export apply_transform 逐点对拍（跨模块公式一致性锚）。"""
    from materialsorting.web.export_geometry import apply_transform
    poly = [(3.5, -2.0), (17.25, 4.75), (9.0, 33.0), (-5.0, 12.5)]
    placed = [{'id': 'a', 'rotation': 37.0, 'translation': [123.4, -45.6],
               'mirror': True}]
    w = _physical_width_mm(placed, {'a': poly})
    world = apply_transform(poly, 37.0, [123.4, -45.6], True)
    assert w == math.ceil(max(x for x, _ in world) - 1e-9)


def test_physical_width_missing_pid_and_empty():
    """placed 空 / pid 不在 pid_raw → None（调用方回退求解器口径）。"""
    pid_raw = {'a': [(0, 0), (1, 0), (1, 1)]}
    assert _physical_width_mm([], pid_raw) is None
    assert _physical_width_mm(
        [{'id': 'zzz', 'rotation': 0.0, 'translation': [0, 0]}], pid_raw) is None


# --------------------------------------------- _raw_polygon_map 降级链

def test_raw_polygon_map_fallback_chain():
    meta = {
        'a': {'raw_polygon': [[0, 0], [1, 0], [1, 1]], 'polygon': [[9, 9]]},
        'b': {'polygon': [[0, 0], [2, 0], [2, 2]]},   # 无 raw → polygon 回退
        'c': {},                                        # 全空 → 跳过
    }
    m = _raw_polygon_map(meta)
    assert m == {'a': [[0, 0], [1, 0], [1, 1]], 'b': [[0, 0], [2, 0], [2, 2]]}
    assert _raw_polygon_map(None) == {}
    assert _raw_polygon_map('not-a-dict') == {}


# --------------------------------------------- _apply_density_dual 双路径

def test_apply_density_dual_physical_path_bug_run_numbers():
    """物理路径：width_sparrow_mm 备查 + width/density 重算 —— bug run 数字复现
    （erode 包络 8653.18 / 毛版 8660 → 90.22% 偏乐观 vs 90.15% 物理）。"""
    pid_raw = {'a': [(0, 0), (100, 0), (100, 50), (0, 50)]}
    rep = {'density': 0.91, 'width_mm': 8653.18,
           'placed_items': [{'id': 'a', 'rotation': 0.0,
                             'translation': [8559.7754, 0.0]}]}
    _apply_density_dual(rep, 13661577.3, 1750.0, pid_raw)
    assert rep['width_sparrow_mm'] == pytest.approx(8653.18)
    assert rep['width_mm'] == pytest.approx(8660.0)
    assert rep['density_sparrow'] == pytest.approx(0.91)
    # 编辑弹窗同值：13661577.3/(8660×1750) = 90.1457% → 显示 90.15%
    assert rep['density'] == pytest.approx(13661577.3 / (8660.0 * 1750.0))
    assert rep['density'] * 100 == pytest.approx(90.1457, abs=1e-3)


def test_apply_density_dual_fallback_legacy_caliber():
    """兼容回退：pid_raw 缺席（legacy 合成帧 / 直接单测调用）→ 旧口径（分母 =
    sparrow 自报 width_mm），且不携带 width_sparrow_mm。"""
    rep = {'density': 0.91, 'width_mm': 8000.0,
           'placed_items': [{'id': 'a', 'rotation': 0.0, 'translation': [0, 0]}]}
    _apply_density_dual(rep, 1_000_000.0, 1000.0)
    assert 'width_sparrow_mm' not in rep
    assert rep['width_mm'] == pytest.approx(8000.0)
    assert rep['density'] == pytest.approx(1_000_000.0 / (8000.0 * 1000.0))
    assert rep['density_sparrow'] == pytest.approx(0.91)
    # pid_raw 在场但 pid 不在其中（manifest 与 placed 错位）→ 同款回退。
    rep2 = {'density': 0.9, 'width_mm': 500.0,
            'placed_items': [{'id': 'zzz', 'rotation': 0.0, 'translation': [0, 0]}]}
    _apply_density_dual(rep2, 1000.0, 100.0, {'a': [(0, 0), (1, 0), (1, 1)]})
    assert 'width_sparrow_mm' not in rep2
    assert rep2['width_mm'] == pytest.approx(500.0)
    assert rep2['density'] == pytest.approx(1000.0 / (500.0 * 100.0))
