"""加载排料裁片：pieces_manifest.json 驱动 → 布纹线对齐水平 → 归一化到原点。

输入：单裁片 DXF 目录 + ``pieces_manifest.json`` sidecar（Web 流程由 server.py 写出到
``out/uploads/<doc_id>_pieces/``，manifest 条目 ``[{file, label, size}]``）。
输出：list[NestPiece]，每片已归一化（bbox 左下角在原点）、布纹线已对齐水平。

manifest 驱动（v2）：文件名 ``{label}_{size}.dxf`` 仅人读，加载语义全在 sidecar；
无镜像展开 —— 母版出什么轮廓就排什么轮廓，每片排几份由 WS quantities 决定
（「数量即一切」）。布纹线仅用于"读取后对齐水平"这一步，之后不再约束旋转。

US-024：5 层（毛版 polygon + 净版 net_polygon + 内部线 internal_lines + 刺口 notches
+ 布纹线 grain_line）全部从单裁片 DXF 读取（layer1/14/8/4/7）并随同一管线变换
（grain-align rotation → normalize）。求解仍只用毛版 polygon 做 sparrow NFP 碰撞，
其余 4 层仅透传供渲染/导出。
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

from ..dxf_parser import reader, geometry, collect as _collect

GATE_MM = 1980.0  # 门幅：布幅**显示**口径（UI viewBox / PNG / DXF / PLT 外框），不扣布边
# 绘图仪 Y 可写幅宽（LIKE + WT「高速网口输出中心 V8.8」现场口径，设备端最终确认前按 1910）。
# 布幅与可写幅宽之差（1980−1910=70mm）属内部差：界面/导出仍显示门幅 1980，**求解约束带
# 压到 1910**（NEST_GATE_MM），否则 marker 顶部落在绘图仪行程外 —— 小车撞导轨，
# 2026-08 现场撞机根因。2026-08-20 起**密度分母同取 min(gate_mm, 1910)**（实际幅宽口径，
# 单一换算点 web.solver._apply_density_dual）；前端 NestSVG 以 manifest gate_nest_mm 画
# 红虚线标实际可排边界。换机器/换布幅只改这两个常量，NEST_GATE_MM 自动跟随。
PLOT_SAFE_MAX_Y_MM = 1910.0
NEST_GATE_MM = min(GATE_MM, PLOT_SAFE_MAX_Y_MM)  # 有效排料宽度（求解 strip 高度上限 + 密度分母口径）

DEFAULT_SIZES = [28, 29, 30, 31, 33, 34, 35, 36]  # 用户需求：8 套，跳过 32
# 切片目录 sidecar 文件名（加载驱动源；缺失 = 旧版切片目录，明确报错不静默兼容）
PIECES_MANIFEST_NAME = 'pieces_manifest.json'


@dataclass
class NestPiece:
    """排料裁片（已归一化、布纹线已对齐水平）。

    ``pid = f'{label}_{size}'``（如 ``g03_28``）—— 裁片 g 码是全链路主键；
    无 ptype / side（镜像概念已删除：母版 N 个轮廓 → N 个 NestPiece，零合成）。

    US-024 起除 ``polygon`` 外还携带 4 层细节（``net_polygon`` / ``internal_lines`` /
    ``notches`` / ``grain_line``），仅用于渲染与导出透传，**不参与 sparrow NFP 碰撞**
    （碰撞仍只用 ``polygon``）。字段缺省值保证旧调用方零改动可用。
    """
    pid: str                                            # 唯一 ID，如 'g03_28'
    label: str                                          # 裁片 g 码（主键）
    size: int                                           # 码号
    polygon: list[tuple[float, float]]                  # 顶点，bbox 左下角在原点
    bbox: tuple[float, float, float, float]             # (minx,miny,maxx,maxy)
    area_mm2: float
    source: str                                         # 源 DXF 文件名
    # US-024：5 层细节（渲染/导出透传，不进 sparrow NFP）。default_factory 保证旧
    # 调用方（仅传 pid/label/size/polygon/bbox/area/source）零改动可用。
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


def _grain_rotation_deg(grain_deg):
    """布纹线对齐水平所需的旋转角度（度）。

    返回 0.0（已水平/未知）或 ±90.0（竖直需转水平）。
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
):
    """对 5 层统一施行 rotate → normalize（以 polygon 的 bbox 为基准）。

    1. ``rotate_deg≠0``：所有点/线绕原点旋转；notch 点旋转、法线旋转（无平移）；
       grain_line 两端点旋转。
    2. normalize：以 polygon 当时的 bbox 平移到原点，**同一平移量**施加到所有层
       （保证视觉共域）。

    返回 (polygon', net_polygon', internal_lines', notches', grain_line', bbox', area')。
    """
    # 1. Rotation
    if rotate_deg:
        polygon = _rotate(polygon, rotate_deg)
        net_polygon = _rotate(net_polygon, rotate_deg) if net_polygon else []
        internal_lines = [_rotate(line, rotate_deg) for line in internal_lines]
        # notch 点必须随片旋转（旧实现只转法线不转点 → 竖直布纹片 rot=±90 时刺口
        # 飞出轮廓 3m+；PLT 导出 600 越界点、PNG/DXF 同源污染）
        notches = [
            _rotate([(x, y)], rotate_deg)[0] + _rotate_normal(nx, ny, rotate_deg)
            for x, y, nx, ny in notches
        ]
        if grain_line is not None:
            (rx1, ry1), (rx2, ry2) = _rotate(
                [(grain_line[0], grain_line[1]), (grain_line[2], grain_line[3])], rotate_deg)
            grain_line = (rx1, ry1, rx2, ry2)
    # 2. Normalize（以 polygon bbox 为基准，所有层共享 dx/dy）
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


# ---------------- 主加载入口 ----------------

def load_nest_pieces(data_dir):
    """manifest 驱动加载全部排料裁片（5 层透传，US-024）。

    data_dir: 单裁片 DXF 所在目录，须含 ``pieces_manifest.json`` sidecar
              （条目 ``[{file, label, size}]``，由 ``web/server._commit_to_nesting_sync``
              写出）。

    每条 manifest 条目读对应 DXF 的 5 层（layer1/14/8/4/7），施行 grain-align rotation
    → normalize（所有层共用同一变换链 ``_apply_layer_transforms``），产出
    ``NestPiece(pid=f'{label}_{size}')``。无镜像展开：母版 N 个轮廓 → N 个 NestPiece。

    旧版切片目录（无 sidecar / 切片文件缺失 / 轮廓无效）明确报错「请重新 commit」，
    不静默兼容（FR-9）。
    """
    manifest_path = os.path.join(data_dir, PIECES_MANIFEST_NAME)
    if not os.path.exists(manifest_path):
        raise RuntimeError(
            f'切片目录缺少 {PIECES_MANIFEST_NAME}（旧版切片目录），请重新 commit 母版')
    with open(manifest_path, encoding='utf-8') as f:
        manifest = json.load(f)

    pieces: list[NestPiece] = []
    for item in manifest:
        fname = item['file']
        label, size = item['label'], item['size']
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            raise RuntimeError(f'切片文件缺失：{fname}，请重新 commit 母版')
        poly, grain_deg, net, internal, notches, grain_line = _read_piece_full(path)
        if poly is None or len(poly) < 3:
            raise RuntimeError(f'切片 {fname} 无有效 layer1 轮廓，请重新 commit 母版')
        rot = _grain_rotation_deg(grain_deg)
        (t_poly, t_net, t_int, t_notches, t_grain, bbox, area) = _apply_layer_transforms(
            polygon=poly, net_polygon=net, internal_lines=internal,
            notches=notches, grain_line=grain_line,
            rotate_deg=rot,
        )
        pieces.append(NestPiece(
            pid=f'{label}_{size}', label=label, size=size,
            polygon=t_poly, bbox=bbox, area_mm2=area, source=os.path.basename(path),
            net_polygon=t_net, internal_lines=t_int,
            notches=t_notches, grain_line=t_grain,
        ))
    return pieces


if __name__ == '__main__':
    # CLI 冒烟：python -m materialsorting.nesting_bounds.load_pieces <pieces_dir>
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else '.'
    loaded = load_nest_pieces(target)
    print(f'loaded {len(loaded)} pieces from {target}')
    for np_ in loaded[:5]:
        print(f'  pid={np_.pid} area={np_.area_mm2:.1f} bbox={np_.bbox}')
