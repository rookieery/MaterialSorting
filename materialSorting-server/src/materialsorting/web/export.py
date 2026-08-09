"""排料可视化工作台 · 导出（PNG + ASTM/AAMA 风格 R12-DXF marker）。

服务端统一导出，用**真实母版轮廓**（pieces_intermediate.json 的原始 polygon，非 eroded）
放到排料变换位，保证 PNG 与 DXF 几何一致、且可直接裁剪。

- PNG：matplotlib（cairosvg 缺失且 Windows 有 native 库坑，故弃用）。配色复用
  sparrow_baseline.PTYPE_COLORS（与工作台屏幕同色）。
- DXF：ezdxf R12 + POLYLINE（复刻 material sorting/nesting_bounds/export.py 已验证套路，
  坚决不用 LWPOLYLINE —— ET2008 轮廓消失坑）。每片按类型 ACI 上色 + 门幅边框 + ASCII 标题。

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


# ===================== 几何 =====================
def apply_transform(polygon, rotation_deg: float, translation):
    """二维旋转 + 平移：world = R(θ)·(x,y) + (tx,ty)（与前端 pointsStr 同公式）。"""
    r = math.radians(rotation_deg)
    c, s = math.cos(r), math.sin(r)
    tx, ty = float(translation[0]), float(translation[1])
    return [(x * c - y * s + tx, x * s + y * c + ty) for x, y in polygon]


def placed_to_world(placed, pieces_by_id):
    """把 placed_items 转成世界坐标裁片列表。

    placed: [{id, rotation, translation:[tx,ty]}, ...]
    pieces_by_id: {pid: piece_dict}（piece_dict 含原始 polygon/ptype/size/area_mm2）
    → [{pid, ptype, size, polygon(world), color, area_mm2}, ...]（pid 查不到的跳过）
    """
    out = []
    for it in placed:
        pid = it.get('id')
        p = pieces_by_id.get(pid)
        if p is None:
            logging.warning('导出跳过：pid %s 在 PIECES 中找不到', pid)
            continue
        world = apply_transform(p['polygon'], float(it.get('rotation', 0.0)), it.get('translation', [0, 0]))
        out.append({
            'pid': pid,
            'ptype': p['ptype'],
            'size': p.get('size'),
            'polygon': world,
            'color': PTYPE_COLORS.get(p['ptype'], DEFAULT_COLOR),   # 与屏幕同色
            'area_mm2': p.get('area_mm2'),
        })
    return out


# ===================== PNG（matplotlib）=====================
def render_png(world_pieces, *, width_mm: float, gate_mm: float, title: str) -> bytes:
    """渲染排料 PNG：门幅矩形 + 每片多边形（类型配色）+ 标题 + 类型图例。"""
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
    # 每片
    for pc in world_pieces:
        ax.add_patch(MplPolygon(pc['polygon'], closed=True,
                                facecolor=pc['color'], edgecolor=pc['color'],
                                alpha=0.55, linewidth=0.8, zorder=1))

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
def write_marker_dxf(world_pieces, *, width_mm: float, gate_mm: float, title: str) -> bytes:
    """写排料 marker DXF：R12，门幅边框 + 每片闭合 POLYLINE（按类型 ACI）+ ASCII 标题。"""
    doc = ezdxf.new('R12')
    doc.header['$MEASUREMENT'] = 1   # metric（mm 隐式，R12 不写 $INSUNITS）
    msp = doc.modelspace()

    # 门幅/用布边框（裁床轮廓）
    msp.add_polyline2d(
        [(0, 0), (width_mm, 0), (width_mm, gate_mm), (0, gate_mm), (0, 0)],
        dxfattribs={'color': 7})

    # 每片：闭合 POLYLINE（首尾补点闭合；不用 LWPOLYLINE —— ET2008 轮廓消失）
    for pc in world_pieces:
        pts = [(round(x, 2), round(y, 2)) for x, y in pc['polygon']]
        if len(pts) >= 2 and pts[0] != pts[-1]:
            pts.append(pts[0])
        msp.add_polyline2d(pts, dxfattribs={'color': TYPE_ACI.get(pc['ptype'], 7)})

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
