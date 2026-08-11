"""加载排料裁片：单裁片 DXF → 布纹线对齐水平 → 归一化到原点 → 成对镜像展开。

输入：material sorting/data/m1787_直筒/{类型}_{码号}.dxf
输出：list[NestPiece]，每片已归一化（bbox 左下角在原点）、布纹线已对齐水平。

阶段 0 不上 v0.3 全约束：成对片镜像展开为 L/R 两片后**独立排**（不强制对称位置），
布纹线仅用于"读取后对齐水平"这一步，之后不再约束旋转。

US-024：5 层（毛版 polygon + 净版 net_polygon + 内部线 internal_lines + 刺口 notches
+ 布纹线 grain_line）全部从单裁片 DXF 读取（layer1/14/8/4/7）并随同一管线变换
（grain-align rotation → normalize → 可选 mirror → 再 normalize）。求解仍只用毛版
polygon 做 sparrow NFP 碰撞，其余 4 层仅透传供渲染/导出。
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from .. import paths
from ..dxf_parser import reader, geometry, collect as _collect

GATE_MM = 1980.0  # 门幅（有效排料宽度，不扣布边）

# v0.3 规则的成对类（镜像展开为 L/R 两片）
PAIR_TYPES = {'前片', '后片', '腰', '前袋', '后袋', '机头'}
ALL_TYPES = ['前片', '后片', '腰', '前袋', '后袋', '机头', '单排', '双排', '火机袋', '裤耳']
DEFAULT_SIZES = [28, 29, 30, 31, 33, 34, 35, 36]  # 用户需求：8 套，跳过 32


@dataclass
class NestPiece:
    """排料裁片（已归一化、布纹线已对齐水平）。

    US-024 起除 ``polygon`` 外还携带 4 层细节（``net_polygon`` / ``internal_lines`` /
    ``notches`` / ``grain_line``），仅用于渲染与导出透传，**不参与 sparrow NFP 碰撞**
    （碰撞仍只用 ``polygon``）。字段缺省值保证旧调用方零改动可用。
    """
    pid: str                                            # 唯一 ID，如 '前片_28_L'
    ptype: str                                          # 裁片类型
    size: int                                           # 码号
    side: str                                           # 'L' / 'R' / 'M'(单片)
    polygon: list[tuple[float, float]]                  # 顶点，bbox 左下角在原点
    bbox: tuple[float, float, float, float]             # (minx,miny,maxx,maxy)
    area_mm2: float
    source: str                                         # 源 DXF 文件名
    # US-024：5 层细节（渲染/导出透传，不进 sparrow NFP）。default_factory 保证旧
    # 调用方（仅传 pid/ptype/.../source）零改动可用。
    net_polygon: list[tuple[float, float]] = field(default_factory=list)
    internal_lines: list[list[tuple[float, float]]] = field(default_factory=list)
    notches: list[tuple[float, float, float, float]] = field(default_factory=list)  # (x,y,nx,ny)
    grain_line: tuple[float, float, float, float] | None = None

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


def _rotate_normal(nx: float, ny: float, deg: float) -> tuple[float, float]:
    """旋转单位法线向量（无平移）。deg=0 立即返回。"""
    if deg == 0:
        return (nx, ny)
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return (c * nx - s * ny, s * nx + c * ny)


def _mirror_x(pts):
    """沿 Y 轴镜像（x → -x），用于生成成对的右片。"""
    return [(-x, y) for x, y in pts]


def _normalize(pts):
    """平移使 bbox 左下角到原点。返回 (新顶点, bbox)。"""
    bb = geometry.bbox_of(pts)
    dx, dy = -bb[0], -bb[1]
    pts2 = [(x + dx, y + dy) for x, y in pts]
    return pts2, geometry.bbox_of(pts2)


def _grain_rotation_deg(grain_deg):
    """与 ``_align_grain_horizontal`` 同口径的旋转角度（度）。

    返回 0.0（已水平/未知）或 ±90.0（竖直需转水平）。提出为独立函数便于 5 层一起施变换。
    """
    if grain_deg is None:
        return 0.0
    a = (grain_deg + 180) % 360 - 180  # 归一到 [-180,180]
    if abs(a) <= 45 or abs(abs(a) - 180) <= 45:
        return 0.0                          # 已水平
    if abs(abs(a) - 90) <= 45:
        return -90.0 if a > 0 else 90.0     # 竖直 → 水平
    return 0.0


def _apply_layer_transforms(
    *,
    polygon: list[tuple[float, float]],
    net_polygon: list[tuple[float, float]],
    internal_lines: list[list[tuple[float, float]]],
    notches: list[tuple[float, float, float, float]],
    grain_line: tuple[float, float, float, float] | None,
    rotate_deg: float,
    mirror: bool,
):
    """对 5 层统一施行 rotate → mirror → normalize（以 polygon 的 bbox 为基准）。

    与 ``load_nest_pieces`` 既有 ``_align_grain_horizontal`` + ``_normalize`` +
    ``_mirror_x`` 链路同语义，扩展到全 5 层：

    1. ``rotate_deg≠0``：所有点/线绕原点旋转；notch 点旋转、法线旋转（无平移）；
       grain_line 两端点旋转。
    2. ``mirror=True``：所有点/线 x→-x；notch 点 x→-x、法线 nx→-nx；grain_line 端点 x→-x。
    3. normalize：以 polygon 当时的 bbox 平移到原点，**同一平移量**施加到所有层
       （保证视觉共域）。

    返回 (polygon', net_polygon', internal_lines', notches', grain_line', bbox', area')。
    """
    # 1. Rotation
    if rotate_deg:
        polygon = _rotate(polygon, rotate_deg)
        net_polygon = _rotate(net_polygon, rotate_deg) if net_polygon else []
        internal_lines = [_rotate(line, rotate_deg) for line in internal_lines]
        notches = [(x, y) + _rotate_normal(nx, ny, rotate_deg) for x, y, nx, ny in notches]
        if grain_line is not None:
            (rx1, ry1), (rx2, ry2) = _rotate(
                [(grain_line[0], grain_line[1]), (grain_line[2], grain_line[3])], rotate_deg)
            grain_line = (rx1, ry1, rx2, ry2)
    # 2. Mirror
    if mirror:
        polygon = _mirror_x(polygon)
        net_polygon = _mirror_x(net_polygon) if net_polygon else []
        internal_lines = [_mirror_x(line) for line in internal_lines]
        # notch: (x,y,nx,ny) → (-x,y,-nx,ny)
        notches = [(-x, y, -nx, ny) for x, y, nx, ny in notches]
        if grain_line is not None:
            grain_line = (-grain_line[0], grain_line[1], -grain_line[2], grain_line[3])
    # 3. Normalize（以 polygon bbox 为基准，所有层共享 dx/dy）
    bbox = geometry.bbox_of(polygon)
    dx, dy = -bbox[0], -bbox[1]
    polygon = [(x + dx, y + dy) for x, y in polygon]
    bbox = geometry.bbox_of(polygon)
    if net_polygon:
        net_polygon = [(x + dx, y + dy) for x, y in net_polygon]
    internal_lines = [[(x + dx, y + dy) for x, y in line] for line in internal_lines]
    notches = [(x + dx, y + dy, nx, ny) for x, y, nx, ny in notches]
    if grain_line is not None:
        grain_line = (grain_line[0] + dx, grain_line[1] + dy,
                      grain_line[2] + dx, grain_line[3] + dy)
    area = geometry.polygon_area(polygon)
    return polygon, net_polygon, internal_lines, notches, grain_line, bbox, area


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


def _read_piece_full(dxf_path):
    """读单裁片 DXF 全 5 层（US-024）。

    返回 ``(polygon, grain_deg, net_polygon, internal_lines, notch_pts, grain_line)``，
    其中 ``notch_pts`` 是 ``[(x, y, nx, ny), ...]`` —— 法线 (nx, ny) 由 outline 最近边
    重算（与 ``collect._nearest_edge_with_normal`` 同算法）。旧 DXF（仅 layer1+layer7）
    的 4 层字段返回空/None，向后兼容。
    """
    doc = reader.load_doc(dxf_path)
    poly = None
    grain_deg = None
    net_polygon: list[tuple[float, float]] = []
    internal_lines: list[list[tuple[float, float]]] = []
    notch_pts_raw: list[tuple[float, float]] = []
    grain_line: tuple[float, float, float, float] | None = None

    for e in doc.modelspace():
        et = e.dxftype()
        layer = str(e.dxf.layer)
        if et == 'POLYLINE' and layer == '1':
            poly = reader.polyline_points(e)
        elif et == 'LINE' and layer == '7':
            x1, y1 = float(e.dxf.start.x), float(e.dxf.start.y)
            x2, y2 = float(e.dxf.end.x), float(e.dxf.end.y)
            grain_deg = geometry.line_angle_deg((x1, y1), (x2, y2))
            grain_line = (x1, y1, x2, y2)
        elif et == 'POLYLINE' and layer == '14':
            pts = reader.polyline_points(e)
            if pts and len(pts) >= 2:
                net_polygon = [(float(x), float(y)) for x, y in pts]
        elif et == 'POLYLINE' and layer == '8':
            pts = reader.polyline_points(e)
            if pts and len(pts) >= 2:
                internal_lines.append([(float(x), float(y)) for x, y in pts])
        elif et == 'POINT' and layer == '4':
            try:
                loc = e.dxf.location
                notch_pts_raw.append((float(loc.x), float(loc.y)))
            except Exception:
                continue

    # notch 法线按 outline 最近边重算（与 collect._assign_notch 同语义，单 outline）
    notches: list[tuple[float, float, float, float]] = []
    if notch_pts_raw and poly and len(poly) >= 3:
        sa = _collect._signed_area(poly)
        for x, y in notch_pts_raw:
            _, _, nx, ny = _collect._nearest_edge_with_normal((x, y), poly, sa)
            notches.append((x, y, nx, ny))
    else:
        notches = [(x, y, 0.0, 0.0) for x, y in notch_pts_raw]

    return poly, grain_deg, net_polygon, internal_lines, notches, grain_line


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
    """加载全部排料裁片（5 层透传，US-024）。

    data_dir: 单裁片 DXF 所在目录
    sizes:    码号列表，默认 DEFAULT_SIZES
    types:    裁片类型列表，默认 ALL_TYPES

    每片读 5 层（layer1/14/8/4/7），对成对类生成 L/R 两片：L = rotate+normalize，
    R = rotate+mirror+normalize。所有层共用同一变换链（``_apply_layer_transforms``），
    保证视觉共域。``polygon`` 是 sparrow NFP 碰撞输入；其余 4 层仅渲染/导出透传。
    """
    sizes = sizes or DEFAULT_SIZES
    types = types or ALL_TYPES
    pieces: list[NestPiece] = []
    for size in sizes:
        for ptype in types:
            path = os.path.join(data_dir, f'{ptype}_{size}.dxf')
            if not os.path.exists(path):
                continue
            poly, grain_deg, net, internal, notches, grain_line = _read_piece_full(path)
            if poly is None or len(poly) < 3:
                continue
            rot = _grain_rotation_deg(grain_deg)
            base = os.path.basename(path)

            # L（或单片 M）：rotate → normalize
            (L_poly, L_net, L_int, L_notches, L_grain, L_bbox, L_area) = _apply_layer_transforms(
                polygon=poly, net_polygon=net, internal_lines=internal,
                notches=notches, grain_line=grain_line,
                rotate_deg=rot, mirror=False,
            )
            if ptype in PAIR_TYPES:
                # R：rotate → mirror → normalize（独立于 L 的 normalize）
                (R_poly, R_net, R_int, R_notches, R_grain, R_bbox, R_area) = _apply_layer_transforms(
                    polygon=poly, net_polygon=net, internal_lines=internal,
                    notches=notches, grain_line=grain_line,
                    rotate_deg=rot, mirror=True,
                )
                pieces.append(NestPiece(
                    f'{ptype}_{size}_L', ptype, size, 'L', L_poly, L_bbox, L_area, base,
                    net_polygon=L_net, internal_lines=L_int, notches=L_notches, grain_line=L_grain,
                ))
                pieces.append(NestPiece(
                    f'{ptype}_{size}_R', ptype, size, 'R', R_poly, R_bbox, R_area, base,
                    net_polygon=R_net, internal_lines=R_int, notches=R_notches, grain_line=R_grain,
                ))
            else:
                pieces.append(NestPiece(
                    f'{ptype}_{size}_M', ptype, size, 'M', L_poly, L_bbox, L_area, base,
                    net_polygon=L_net, internal_lines=L_int, notches=L_notches, grain_line=L_grain,
                ))
    return pieces


if __name__ == '__main__':
    ps = load_nest_pieces(paths.PIECES_DIR)
    by_t = {}
    for p in ps:
        by_t[p.ptype] = by_t.get(p.ptype, 0) + 1
    print(f'加载 {len(ps)} 片 | 各类型: {by_t} | 总面积 {sum(p.area_mm2 for p in ps)/1e6:.3f} m2')
