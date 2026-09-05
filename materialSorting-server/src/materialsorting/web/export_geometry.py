"""导出共享层 · 几何变换与配色（placed → 世界坐标 5 层 + 尺码 ACI/颜色常量）。

从 web/export.py 拆出（2026-08-20，纯机械搬移、行为零变更）：PNG（export_png）/
DXF（export_dxf）/ PLT（export_plt）三格式共用 ``placed_to_world`` 的同一份
**真实母版轮廓**世界坐标数据（pieces_intermediate.json 的原始 polygon，非 eroded，
放到排料变换位），保证三格式几何一致、且可直接裁剪 / 绘图。

- 配色复用 sparrow_baseline.size_color（尺码 → 16 色循环表，与工作台屏幕同色；
  2026-08-20 起由 g 码换键为尺码，同码同色跨片型一致）。
- US-024：5 层 = 毛版 polygon + 净版 net_polygon + 内部线 internal_lines +
  刺口 notches + 布纹线 grain_line。

坐标系：spyrrow 世界坐标 X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上
（与前端 SVG `scale(1,-1)` 翻转后一致 → PNG 直接对应屏幕观感）。
"""
from __future__ import annotations

import logging
import math

# 复用排料引擎的尺码配色（PNG 与屏幕同色；16 色循环表单一真相源在 sparrow_baseline）
from ..nesting_engine.sparrow_baseline import size_color, SIZE_ANCHOR


def size_aci(size) -> int:
    """尺码 → DXF ACI 色号 ``((size - SIZE_ANCHOR) % 24) + 1``（非数字兜底 7 白）。

    ACI 1-24 是色轮全谱，锚点 52 起循环回 1（与 SIZE_PALETTE 16 色循环同思想，
    色域不同源）；锚点与 ``size_color`` 共用 sparrow_baseline.SIZE_ANCHOR（=28）。
    """
    if isinstance(size, bool) or not isinstance(size, (int, float)):
        return 7
    return (int(size) - SIZE_ANCHOR) % 24 + 1


# US-024：5 层配色（与前端 constants/colors.ts LAYER5_COLORS 同口径，确保 PNG/前端视觉一致）
LAYER5_COLOR_NET = '#33cc33'       # layer14 净版绿虚线
LAYER5_COLOR_INTERNAL = '#ff8c1a'  # layer8 内部线橙实线
LAYER5_COLOR_NOTCH = '#ffd700'     # layer4 刺口黄短线段
LAYER5_COLOR_GRAIN = '#e53e3e'     # layer7 布纹线红虚线
# 刺口短线段长度（mm，与前端 PiecePreviewSVG NOTCH_LEN_MM 一致；版师待确认）
NOTCH_LEN_MM = 8.0


# ===================== 几何 =====================
def apply_transform(polygon, rotation_deg: float, translation, mirror: bool = False):
    """二维旋转 + 平移：world = R(θ)·(x,y) + (tx,ty)（与前端 pointsStr 同公式）。

    mirror=True（edit-keyboard US-004，缺省 false 逐字节不变）：局部 x 先取负再
    旋转 ``world = R(θ)·diag(−1,1)·(x,y) + t``，展开
    ``x' = −x·c − y·s + tx / y' = −x·s + y·c + ty`` —— 与前端
    ``editGeometry.transformPolygon`` mirror 分支同输入输出逐点相等（单测对拍
    锁死）。缺省 false / 显式 false 与旧实现逐字节一致。
    """
    r = math.radians(rotation_deg)
    c, s = math.cos(r), math.sin(r)
    tx, ty = float(translation[0]), float(translation[1])
    out = []
    for x, y in polygon:
        x0 = -x if mirror else x
        out.append((x0 * c - y * s + tx, x0 * s + y * c + ty))
    return out


def _transform_normal(nx: float, ny: float, rotation_deg: float,
                      mirror: bool = False) -> tuple[float, float]:
    """旋转法线向量（无平移）——notch 法线随裁片姿态旋转。

    mirror=True（US-004）：法线是**向量**，反射下 x 分量先取负再旋转
    （``R(θ)·diag(−1,1)·(nx,ny)``；点变换同公式但无平移项）。
    """
    r = math.radians(rotation_deg)
    c, s = math.cos(r), math.sin(r)
    x0 = -nx if mirror else nx
    return (c * x0 - s * ny, s * x0 + c * ny)


def placed_to_world(placed, pieces_by_id):
    """把 placed_items 转成世界坐标裁片列表（含 5 层，US-024）。

    placed: [{id, rotation, translation:[tx,ty], mirror?}, ...]
    pieces_by_id: {pid: piece_dict}（intermediate 直查，零重放；piece_dict 含原始
                  polygon/label/size/area_mm2 + US-024 5 层字段 net_polygon/
                  internal_lines/notches/grain_line）
    → [{pid, size, polygon(world), color, area_mm2, label,
        net_polygon, internal_lines, notches, grain_line}, ...]

    颜色 = ``size_color(size)``（尺码 → 16 色循环表，与求解屏幕/CLI SVG 同源）。

    对 5 层全部按 placement 的 rotation+translation 变换到世界坐标：
      - polygon / net_polygon / internal_lines 顶点 → ``apply_transform``（点变换）
      - notch (x, y, nx, ny)：点变换 (x,y) + 法线旋转变换 (nx,ny)
      - grain_line [x1,y1,x2,y2]：两端点变换

    mirror（edit-keyboard US-004，omit-when-false 可选键）：``it.get('mirror')
    is True`` → 5 层全部走 mirror 分支（毛版/净版/内部线/布纹线点变换 + notch
    法线按向量镜像）；缺省/False 与无该键逐字节相同（/export 路由零改动，
    placed 键直通）。
    """
    out = []
    for it in placed:
        pid = it.get('id')
        p = pieces_by_id.get(pid)
        if p is None:
            logging.warning('导出跳过：pid %s 在 PIECES 中找不到', pid)
            continue
        rot = float(it.get('rotation', 0.0))
        tr = it.get('translation', [0, 0])
        mirror = it.get('mirror') is True
        world_poly = apply_transform(p['polygon'], rot, tr, mirror)

        # US-024 5 层：从 intermediate 透传 + 同步 placement 变换
        net_raw = p.get('net_polygon') or []
        internal_raw = p.get('internal_lines') or []
        notches_raw = p.get('notches') or []
        grain_raw = p.get('grain_line')

        world_net = apply_transform(net_raw, rot, tr, mirror) if net_raw else []
        world_internal = [apply_transform(line, rot, tr, mirror)
                          for line in internal_raw]
        # notch: (x, y, nx, ny) → 旋转点 + 旋转法线（无平移；镜像时 nx 取负）
        world_notches = []
        for x, y, nx, ny in notches_raw:
            wx, wy = apply_transform([(x, y)], rot, tr, mirror)[0]
            wnx, wny = _transform_normal(nx, ny, rot, mirror)
            world_notches.append((wx, wy, wnx, wny))
        world_grain = None
        if grain_raw and len(grain_raw) == 4:
            (gx1, gy1), (gx2, gy2) = apply_transform(
                [(grain_raw[0], grain_raw[1]), (grain_raw[2], grain_raw[3])],
                rot, tr, mirror)
            world_grain = (gx1, gy1, gx2, gy2)

        # US-002：label 键直取（TEXT/质心叠印随 g 码不变）；颜色 2026-08-20 起随尺码
        # （size_color；旧 intermediate size=None → 兜底灰、TEXT 跳过逻辑不变）。
        out.append({
            'pid': pid,
            'size': p.get('size'),
            'polygon': world_poly,
            'color': size_color(p.get('size')),
            'area_mm2': p.get('area_mm2'),
            # g 码裁片标识（PNG 质心叠印 / DXF TEXT 用；旧 intermediate 无 → None 跳过）
            'label': p.get('label'),
            # US-024：5 层世界坐标数据（PNG + DXF 共用）
            'net_polygon': world_net,
            'internal_lines': world_internal,
            'notches': world_notches,
            'grain_line': world_grain,
        })
    return out
