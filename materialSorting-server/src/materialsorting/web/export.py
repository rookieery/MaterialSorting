"""排料可视化工作台 · 导出（PNG + ASTM/AAMA 风格 R12-DXF marker）。

服务端统一导出，用**真实母版轮廓**（pieces_intermediate.json 的原始 polygon，非 eroded）
放到排料变换位，保证 PNG 与 DXF 几何一致、且可直接裁剪。

- PNG：matplotlib（cairosvg 缺失且 Windows 有 native 库坑，故弃用）。配色复用
  sparrow_baseline.PTYPE_COLORS（与工作台屏幕同色）。
- DXF：ezdxf R12 + POLYLINE（复刻 material sorting/nesting_bounds/export.py 已验证套路，
  坚决不用 LWPOLYLINE —— ET2008 轮廓消失坑）。每片按类型 ACI 上色 + 门幅边框 + ASCII 标题。

US-024：PNG 与 DXF 都含 5 层（毛版 polygon + 净版 net_polygon + 内部线 internal_lines +
刺口 notches + 布纹线 grain_line）。毛版 layer1 是裁切轮廓（DXF ACI 按片型）；其余 4 层
为工艺参考，DXF 各自独立 layer（14/8/4/7），PNG 用与 PiecePreviewSVG 同口径的配色
（net 绿 / internal 橙 / notch 黄 / grain 红）。

坐标系：spyrrow 世界坐标 X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上
（与前端 SVG `scale(1,-1)` 翻转后一致 → PNG 直接对应屏幕观感）。
"""
from __future__ import annotations

import logging
import math
import os
import sys
import tempfile

# ---- matplotlib 无显示环境 ----
import matplotlib
matplotlib.use('Agg')
# CJK 字体（标题/图例有中文；Windows 用 Microsoft YaHei，缺则回退）
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon as MplPolygon, Patch, Rectangle  # noqa: E402

import ezdxf  # noqa: E402

# 抑制 ezdxf R12 $INSUNITS 等已知无害警告
logging.getLogger('ezdxf').setLevel(logging.ERROR)

# 复用排料引擎的类型配色（PNG 与屏幕同色）
from ..nesting_engine.sparrow_baseline import PTYPE_COLORS, DEFAULT_COLOR

# DXF ACI 色号（与 nesting_bounds/export.py 一致；10 类全覆盖）
TYPE_ACI = {
    '前片': 1, '后片': 2, '腰': 3, '前袋': 4, '后袋': 5, '机头': 6,
    '单排': 7, '双排': 8, '火机袋': 9, '裤耳': 10,
}
# 图例固定顺序（仅出现过的才画）
TYPE_ORDER = ['前片', '后片', '腰', '前袋', '后袋', '机头', '单排', '双排', '火机袋', '裤耳']

# US-024：5 层配色（与前端 constants/colors.ts LAYER5_COLORS 同口径，确保 PNG/前端视觉一致）
LAYER5_COLOR_NET = '#33cc33'       # layer14 净版绿虚线
LAYER5_COLOR_INTERNAL = '#ff8c1a'  # layer8 内部线橙实线
LAYER5_COLOR_NOTCH = '#ffd700'     # layer4 刺口黄短线段
LAYER5_COLOR_GRAIN = '#e53e3e'     # layer7 布纹线红虚线
# 刺口短线段长度（mm，与前端 PiecePreviewSVG NOTCH_LEN_MM 一致；版师待确认）
NOTCH_LEN_MM = 8.0


# ===================== 几何 =====================
def apply_transform(polygon, rotation_deg: float, translation):
    """二维旋转 + 平移：world = R(θ)·(x,y) + (tx,ty)（与前端 pointsStr 同公式）。"""
    r = math.radians(rotation_deg)
    c, s = math.cos(r), math.sin(r)
    tx, ty = float(translation[0]), float(translation[1])
    return [(x * c - y * s + tx, x * s + y * c + ty) for x, y in polygon]


def _transform_normal(nx: float, ny: float, rotation_deg: float) -> tuple[float, float]:
    """旋转法线向量（无平移）——notch 法线随裁片姿态旋转。"""
    r = math.radians(rotation_deg)
    c, s = math.cos(r), math.sin(r)
    return (c * nx - s * ny, s * nx + c * ny)


def placed_to_world(placed, pieces_by_id):
    """把 placed_items 转成世界坐标裁片列表（含 5 层，US-024）。

    placed: [{id, rotation, translation:[tx,ty]}, ...]
    pieces_by_id: {pid: piece_dict}（piece_dict 含原始 polygon/ptype/size/area_mm2 +
                  US-024 5 层字段 net_polygon/internal_lines/notches/grain_line）
    → [{pid, ptype, size, polygon(world), color, area_mm2,
        net_polygon, internal_lines, notches, grain_line}, ...]

    对 5 层全部按 placement 的 rotation+translation 变换到世界坐标：
      - polygon / net_polygon / internal_lines 顶点 → ``apply_transform``（点变换）
      - notch (x, y, nx, ny)：点变换 (x,y) + 法线旋转变换 (nx,ny)
      - grain_line [x1,y1,x2,y2]：两端点变换
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
        world_poly = apply_transform(p['polygon'], rot, tr)

        # US-024 5 层：从 intermediate 透传 + 同步 placement 变换
        net_raw = p.get('net_polygon') or []
        internal_raw = p.get('internal_lines') or []
        notches_raw = p.get('notches') or []
        grain_raw = p.get('grain_line')

        world_net = apply_transform(net_raw, rot, tr) if net_raw else []
        world_internal = [apply_transform(line, rot, tr) for line in internal_raw]
        # notch: (x, y, nx, ny) → 旋转点 + 旋转法线（无平移）
        world_notches = []
        for x, y, nx, ny in notches_raw:
            wx, wy = apply_transform([(x, y)], rot, tr)[0]
            wnx, wny = _transform_normal(nx, ny, rot)
            world_notches.append((wx, wy, wnx, wny))
        world_grain = None
        if grain_raw and len(grain_raw) == 4:
            (gx1, gy1), (gx2, gy2) = apply_transform(
                [(grain_raw[0], grain_raw[1]), (grain_raw[2], grain_raw[3])], rot, tr)
            world_grain = (gx1, gy1, gx2, gy2)

        out.append({
            'pid': pid,
            'ptype': p['ptype'],
            'size': p.get('size'),
            'polygon': world_poly,
            'color': PTYPE_COLORS.get(p['ptype'], DEFAULT_COLOR),   # 与屏幕同色
            'area_mm2': p.get('area_mm2'),
            # US-024：5 层世界坐标数据（PNG + DXF 共用）
            'net_polygon': world_net,
            'internal_lines': world_internal,
            'notches': world_notches,
            'grain_line': world_grain,
        })
    return out


# ===================== PNG（matplotlib）=====================
def render_png(world_pieces, *, width_mm: float, gate_mm: float, title: str) -> bytes:
    """渲染排料 PNG：门幅矩形 + 每片 5 层（毛版类型配色 + 工艺线）+ 标题 + 类型图例。

    US-024：每片在毛版多边形之上叠加 net_polygon(绿虚线) + internal_lines(橙) +
    notches(黄短线段) + grain_line(红虚线)，与前端 NestSVG 视觉一致。
    """
    long_mm = max(width_mm, gate_mm, 1.0)
    long_in = 14.0
    fig_w = long_in * width_mm / long_mm
    fig_h = long_in * gate_mm / long_mm

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor('#eef0f3')

    # 门幅/用布边框（裁床轮廓）
    ax.add_patch(Rectangle((0, 0), width_mm, gate_mm,
                           facecolor='#ffffff', edgecolor='#8a8a8a',
                           linewidth=1.0, linestyle='--', zorder=0))
    # 每片：5 层（zorder 1=毛版实心 → 2=净版/内部/刺口/布纹 叠加）
    for pc in world_pieces:
        # 毛版（layer1）
        ax.add_patch(MplPolygon(pc['polygon'], closed=True,
                                facecolor=pc['color'], edgecolor=pc['color'],
                                alpha=0.55, linewidth=0.8, zorder=1))
        # 净版（layer14）—— 绿虚线，无填充
        if pc.get('net_polygon') and len(pc['net_polygon']) >= 2:
            ax.add_patch(MplPolygon(pc['net_polygon'], closed=True,
                                    fill=False, edgecolor=LAYER5_COLOR_NET,
                                    linewidth=0.7, linestyle='--', zorder=2))
        # 内部线（layer8）—— 橙实线
        for line in pc.get('internal_lines') or []:
            if len(line) < 2:
                continue
            xs = [pt[0] for pt in line]
            ys = [pt[1] for pt in line]
            ax.plot(xs, ys, color=LAYER5_COLOR_INTERNAL, linewidth=0.6,
                    solid_capstyle='round', zorder=2)
        # 刺口（layer4）—— 黄短线段，沿法线 NOTCH_LEN_MM
        half = NOTCH_LEN_MM / 2.0
        for (x, y, nx, ny) in pc.get('notches') or []:
            ax.plot([x - nx * half, x + nx * half],
                    [y - ny * half, y + ny * half],
                    color=LAYER5_COLOR_NOTCH, linewidth=1.0, solid_capstyle='round', zorder=2)
        # 布纹线（layer7）—— 红虚线
        gl = pc.get('grain_line')
        if gl and len(gl) == 4:
            ax.plot([gl[0], gl[2]], [gl[1], gl[3]],
                    color=LAYER5_COLOR_GRAIN, linewidth=0.7,
                    linestyle='--', zorder=2)

    ax.set_xlim(0, width_mm)
    ax.set_ylim(0, gate_mm)
    ax.set_aspect('equal', adjustable='box')
    ax.axis('off')
    ax.set_title(title, fontsize=11, pad=10)

    # 类型图例（放外侧右栏，bbox_inches='tight' 会纳入画布，绝不压住裁片）
    present = {pc['ptype'] for pc in world_pieces}
    handles = [Patch(facecolor=PTYPE_COLORS.get(t, DEFAULT_COLOR),
                     edgecolor=PTYPE_COLORS.get(t, DEFAULT_COLOR), label=t)
               for t in TYPE_ORDER if t in present]
    if handles:
        ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(1.01, 1.0),
                  fontsize=8, frameon=False, title='片型')

    import io
    buf = io.BytesIO()
    fig.savefig(buf, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


# ===================== DXF（R12 POLYLINE，ET 兼容）=====================
# US-024 多 layer 名（与 collect.LAYER_MAPPING / export_dxf.write_piece_dxf 一致；R12 layer 名是字符串）
_DXF_LAYER_OUTLINE = '1'   # 毛版外轮廓（裁切层）
_DXF_LAYER_NET = '14'      # 净版
_DXF_LAYER_INTERNAL = '8'  # 内部线
_DXF_LAYER_NOTCH = '4'     # 刺口（POINT）
_DXF_LAYER_GRAIN = '7'     # 布纹线


def write_marker_dxf(world_pieces, *, width_mm: float, gate_mm: float, title: str) -> bytes:
    """写排料 marker DXF：R12，门幅边框 + 每片 5 层 POLYLINE/POINT（按 layer 分）+ ASCII 标题。

    US-024：每片除 layer1 毛版（闭合 POLYLINE，ACI 按片型）外，附加：
      - layer14 净版（闭合 POLYLINE，color=3 绿）
      - layer8 内部线（多条 POLYLINE，color=6 橙，不闭合）
      - layer4 刺口（POINT，color=2 黄）
      - layer7 布纹线（LINE，color=7 红）
    ET2008 兼容：layer1 是唯一裁切轮廓；附加 layer 仅工艺参考，裁床切 layer1。
    """
    doc = ezdxf.new('R12')
    doc.header['$MEASUREMENT'] = 1   # metric（mm 隐式，R12 不写 $INSUNITS）
    msp = doc.modelspace()

    # 门幅/用布边框（裁床轮廓）
    msp.add_polyline2d(
        [(0, 0), (width_mm, 0), (width_mm, gate_mm), (0, gate_mm), (0, 0)],
        dxfattribs={'color': 7})

    # 每片：5 层
    for pc in world_pieces:
        ptype = pc['ptype']
        aci = TYPE_ACI.get(ptype, 7)
        # layer1 毛版（闭合 POLYLINE；首尾补点闭合；不用 LWPOLYLINE —— ET2008 轮廓消失）
        pts = [(round(x, 2), round(y, 2)) for x, y in pc['polygon']]
        if len(pts) >= 2 and pts[0] != pts[-1]:
            pts.append(pts[0])
        msp.add_polyline2d(pts, dxfattribs={'color': aci, 'layer': _DXF_LAYER_OUTLINE})

        # US-024 layer14 净版（闭合 POLYLINE）
        net_pts = [(round(x, 2), round(y, 2)) for x, y in (pc.get('net_polygon') or [])]
        if len(net_pts) >= 2:
            if net_pts[0] != net_pts[-1]:
                net_pts.append(net_pts[0])
            msp.add_polyline2d(net_pts, dxfattribs={'color': 3, 'layer': _DXF_LAYER_NET})

        # US-024 layer8 内部线（多条 POLYLINE，不闭合）
        for line in pc.get('internal_lines') or []:
            if len(line) < 2:
                continue
            line_pts = [(round(x, 2), round(y, 2)) for x, y in line]
            msp.add_polyline2d(line_pts, dxfattribs={'color': 6, 'layer': _DXF_LAYER_INTERNAL})

        # US-024 layer4 刺口（POINT 位置；法线不进 DXF，渲染/前端按需重算）
        for (x, y, _nx, _ny) in pc.get('notches') or []:
            msp.add_point((round(x, 2), round(y, 2)),
                          dxfattribs={'color': 2, 'layer': _DXF_LAYER_NOTCH})

        # US-024 layer7 布纹线（LINE 两端点）
        gl = pc.get('grain_line')
        if gl and len(gl) == 4:
            msp.add_line((round(gl[0], 2), round(gl[1], 2)),
                         (round(gl[2], 2), round(gl[3], 2)),
                         dxfattribs={'color': 7, 'layer': _DXF_LAYER_GRAIN})

    # ASCII 标题（避免 GBK/编码坑）
    if title:
        msp.add_text(title, dxfattribs={'height': 40, 'insert': (0, gate_mm + 60)})

    # ezdxf 走文件路径最稳，写临时文件再读字节
    tmp = tempfile.NamedTemporaryFile(suffix='.dxf', delete=False)
    tmp.close()
    try:
        doc.saveas(tmp.name)
        with open(tmp.name, 'rb') as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
