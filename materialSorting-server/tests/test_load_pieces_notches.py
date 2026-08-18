"""nesting_bounds.load_pieces 刺口变换回归测试。

背景：``_apply_layer_transforms`` 旋转步骤旧实现只旋转 notch 法线、**不旋转 notch 点**，
导致竖直布纹（grain_deg=±90 → rot=±90）的裁片（腰/后袋）刺口点飞出轮廓 3m+，
污染 intermediate → PLT 600 越界点 / PNG / DXF / 前端预览。本文件锁定该缺陷。

v2（裁片编号化重构）：``_apply_layer_transforms`` 删 mirror 参数（镜像概念全链路
删除），仅 rotate → normalize。
"""
from __future__ import annotations

import pytest

from materialsorting.nesting_bounds.load_pieces import _apply_layer_transforms


def _piece_layers():
    """竖直长条裁片（腰片形态）：100(x) × 1000(y)，刺口在右边缘中点。"""
    polygon = [(0.0, 0.0), (100.0, 0.0), (100.0, 1000.0), (0.0, 1000.0)]
    notches = [(100.0, 500.0, 1.0, 0.0)]   # 右边缘中点，法线朝 +x
    return polygon, notches


def test_notch_point_rotates_with_piece():
    """rot=90 时 notch 点必须随片旋转（点 (100,500) → (−500,100) → normalize 在片内）。"""
    polygon, notches = _piece_layers()
    poly, _net, _internal, out_notches, _gl, bbox, _area = _apply_layer_transforms(
        polygon=polygon, net_polygon=[], internal_lines=[],
        notches=notches, grain_line=None,
        rotate_deg=90.0,
    )
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    for x, y, _nx, _ny in out_notches:
        assert min(xs) - 0.5 <= x <= max(xs) + 0.5, (
            f"notch x={x} outside piece [{min(xs)}, {max(xs)}] —— 点未随片旋转")
        assert min(ys) - 0.5 <= y <= max(ys) + 0.5, (
            f"notch y={y} outside piece [{min(ys)}, {max(ys)}] —— 点未随片旋转")
    # 精确值：rot=90 → (100,500)→(-500,100)；poly 旋转后 bbox x∈[-1000,0] y∈[0,100]
    # normalize dx=1000 → notch=(-500+1000, 100)=(500,100)，即新片（100×1000 横放）中部
    # （法线经 cos90/sin90 浮点运算，用 approx 容差比较）
    assert out_notches[0][0] == pytest.approx(500.0, abs=1e-9)
    assert out_notches[0][1] == pytest.approx(100.0, abs=1e-9)
    assert out_notches[0][2] == pytest.approx(0.0, abs=1e-9)
    assert out_notches[0][3] == pytest.approx(1.0, abs=1e-9)


def test_notch_normal_rotates_with_piece():
    """法线随片旋转（无平移）：(1,0) rot=90 → (0,1)。"""
    polygon, notches = _piece_layers()
    _poly, _net, _internal, out_notches, _gl, _bbox, _area = _apply_layer_transforms(
        polygon=polygon, net_polygon=[], internal_lines=[],
        notches=notches, grain_line=None,
        rotate_deg=90.0,
    )
    nx, ny = out_notches[0][2], out_notches[0][3]
    assert abs(nx) < 1e-9 and abs(ny - 1.0) < 1e-9


def test_zero_rotation_passthrough():
    """rot=0 且不镜像：notch 原样（仅 normalize 平移）。"""
    polygon, notches = _piece_layers()
    _poly, _net, _internal, out_notches, _gl, _bbox, _area = _apply_layer_transforms(
        polygon=polygon, net_polygon=[], internal_lines=[],
        notches=notches, grain_line=None,
        rotate_deg=0.0,
    )
    assert out_notches == [(100.0, 500.0, 1.0, 0.0)]


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
