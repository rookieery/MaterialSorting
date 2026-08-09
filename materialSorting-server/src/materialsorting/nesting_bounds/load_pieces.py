"""加载排料裁片：单裁片 DXF → 布纹线对齐水平 → 归一化到原点 → 成对镜像展开。

输入：material sorting/data/m1787_直筒/{类型}_{码号}.dxf
输出：list[NestPiece]，每片已归一化（bbox 左下角在原点）、布纹线已对齐水平。

阶段 0 不上 v0.3 全约束：成对片镜像展开为 L/R 两片后**独立排**（不强制对称位置），
布纹线仅用于"读取后对齐水平"这一步，之后不再约束旋转。
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

from .. import paths
from ..dxf_parser import reader, geometry

GATE_MM = 1980.0  # 门幅（有效排料宽度，不扣布边）

# v0.3 规则的成对类（镜像展开为 L/R 两片）
PAIR_TYPES = {'前片', '后片', '腰', '前袋', '后袋', '机头'}
ALL_TYPES = ['前片', '后片', '腰', '前袋', '后袋', '机头', '单排', '双排', '火机袋', '裤耳']
DEFAULT_SIZES = [28, 29, 30, 31, 33, 34, 35, 36]  # 用户需求：8 套，跳过 32


@dataclass
class NestPiece:
    """排料裁片（已归一化、布纹线已对齐水平）。"""
    pid: str                                    # 唯一 ID，如 '前片_28_L'
    ptype: str                                  # 裁片类型
    size: int                                   # 码号
    side: str                                   # 'L' / 'R' / 'M'(单片)
    polygon: list[tuple[float, float]]          # 顶点，bbox 左下角在原点
    bbox: tuple[float, float, float, float]     # (minx,miny,maxx,maxy)
    area_mm2: float
    source: str                                 # 源 DXF 文件名

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


# ---------------- 几何变换 ----------------

def _rotate(pts, deg):
    """绕原点旋转 deg 度。"""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [(c * x - s * y, s * x + c * y) for x, y in pts]


def _mirror_x(pts):
    """沿 Y 轴镜像（x → -x），用于生成成对的右片。"""
    return [(-x, y) for x, y in pts]


def _normalize(pts):
    """平移使 bbox 左下角到原点。返回 (新顶点, bbox)。"""
    bb = geometry.bbox_of(pts)
    dx, dy = -bb[0], -bb[1]
    pts2 = [(x + dx, y + dy) for x, y in pts]
    return pts2, geometry.bbox_of(pts2)


# ---------------- DXF 读取 + 布纹对齐 ----------------

def _read_piece(dxf_path):
    """读单裁片 DXF：返回 (polygon_mm, grain_angle_deg)。"""
    doc = reader.load_doc(dxf_path)
    poly, grain = None, None
    for e in doc.modelspace():
        if e.dxftype() == 'POLYLINE' and str(e.dxf.layer) == '1':
            poly = reader.polyline_points(e)
        elif e.dxftype() == 'LINE' and str(e.dxf.layer) == '7':
            grain = geometry.line_angle_deg(
                (float(e.dxf.start.x), float(e.dxf.start.y)),
                (float(e.dxf.end.x), float(e.dxf.end.y)))
    return poly, grain


def _align_grain_horizontal(poly, grain_deg):
    """布纹线对齐水平：竖直布纹旋转 ±90° 使其变水平；水平则不动。"""
    if grain_deg is None:
        return poly
    a = (grain_deg + 180) % 360 - 180  # 归一到 [-180,180]
    if abs(a) <= 45 or abs(abs(a) - 180) <= 45:
        return poly                          # 已水平
    if abs(abs(a) - 90) <= 45:
        return _rotate(poly, -90 if a > 0 else 90)   # 竖直 → 水平
    return poly


# ---------------- 主加载入口 ----------------

def load_nest_pieces(data_dir, sizes=None, types=None):
    """加载全部排料裁片。

    data_dir: 单裁片 DXF 所在目录
    sizes:    码号列表，默认 DEFAULT_SIZES
    types:    裁片类型列表，默认 ALL_TYPES
    """
    sizes = sizes or DEFAULT_SIZES
    types = types or ALL_TYPES
    pieces: list[NestPiece] = []
    for size in sizes:
        for ptype in types:
            path = os.path.join(data_dir, f'{ptype}_{size}.dxf')
            if not os.path.exists(path):
                continue
            poly, grain = _read_piece(path)
            if poly is None or len(poly) < 3:
                continue
            poly = _align_grain_horizontal(poly, grain)
            poly, bbox = _normalize(poly)
            area = geometry.polygon_area(poly)
            base = os.path.basename(path)
            if ptype in PAIR_TYPES:
                rpoly, rbbox = _normalize(_mirror_x(poly))
                pieces.append(NestPiece(f'{ptype}_{size}_L', ptype, size, 'L', poly, bbox, area, base))
                pieces.append(NestPiece(f'{ptype}_{size}_R', ptype, size, 'R', rpoly, rbbox,
                                        geometry.polygon_area(rpoly), base))
            else:
                pieces.append(NestPiece(f'{ptype}_{size}_M', ptype, size, 'M', poly, bbox, area, base))
    return pieces


if __name__ == '__main__':
    ps = load_nest_pieces(paths.PIECES_DIR)
    by_t = {}
    for p in ps:
        by_t[p.ptype] = by_t.get(p.ptype, 0) + 1
    print(f'加载 {len(ps)} 片 | 各类型: {by_t} | 总面积 {sum(p.area_mm2 for p in ps)/1e6:.3f} m2')
