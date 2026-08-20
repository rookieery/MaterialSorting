"""导出 · DXF（ezdxf R12 + POLYLINE marker，ET2008 兼容）。

从 web/export.py 拆出（2026-08-20，纯机械搬移、行为零变更）。复刻
material sorting/nesting_bounds/export.py 已验证套路，坚决不用 LWPOLYLINE ——
ET2008 读 LWPOLYLINE 轮廓会消失。每片按尺码 ACI 上色 + 门幅边框 + ASCII 标题。

US-024：DXF 含 5 层（毛版 polygon + 净版 net_polygon + 内部线 internal_lines +
刺口 notches + 布纹线 grain_line）。毛版 layer1 是裁切轮廓（ACI 按尺码）；其余 4 层
为工艺参考，各自独立 layer（14/8/4/7）。

US-002：全链路 label 键 —— 片型名 / TYPE_ACI / TYPE_ORDER 整体退场。2026-08-20
颜色换键为尺码：DXF ACI = ``((size - 28) % 24) + 1``、颜色 = ``size_color``（每片
g 码文字叠印不变，颜色=尺码、文字=片型互补编码）。

几何数据 = export_geometry.placed_to_world 的世界坐标 5 层，与 PNG / PLT 一致。
"""
from __future__ import annotations

import logging
import os
import tempfile

import ezdxf

# 裁片码质心定位（g 码叠印用；labeling 单一真相源的算子）
from ..nesting_engine.labeling import centroid
from .export_geometry import size_aci

# 抑制 ezdxf R12 $INSUNITS 等已知无害警告
logging.getLogger('ezdxf').setLevel(logging.ERROR)


# ===================== DXF（R12 POLYLINE，ET 兼容）=====================
# US-024 多 layer 名（与 collect.LAYER_MAPPING / export_dxf.write_piece_dxf 一致；R12 layer 名是字符串）
_DXF_LAYER_OUTLINE = '1'   # 毛版外轮廓（裁切层）
_DXF_LAYER_NET = '14'      # 净版
_DXF_LAYER_INTERNAL = '8'  # 内部线
_DXF_LAYER_NOTCH = '4'     # 刺口（POINT）
_DXF_LAYER_GRAIN = '7'     # 布纹线
_DXF_LAYER_TEXT = 'TEXT'   # g 码裁片标识（2026-08-18；独立层与裁切/工艺层隔离）


def write_marker_dxf(world_pieces, *, width_mm: float, gate_mm: float, title: str) -> bytes:
    """写排料 marker DXF：R12，门幅边框 + 每片 5 层 POLYLINE/POINT（按 layer 分）+ g 码 TEXT + ASCII 标题。

    US-024：每片除 layer1 毛版（闭合 POLYLINE，ACI 按尺码 ``((size - 28) % 24) + 1``）外，附加：
      - layer14 净版（闭合 POLYLINE，color=3 绿）
      - layer8 内部线（多条 POLYLINE，color=6 橙，不闭合）
      - layer4 刺口（POINT，color=2 黄）
      - layer7 布纹线（LINE，color=7 红）
    2026-08-18：每片质心附加 TEXT 层 ASCII 裁片码（``g01-30`` = g 码-码号；label
    缺席（旧 intermediate）跳过），独立 layer 'TEXT' 与裁切/工艺层隔离。
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
        # 2026-08-20：ACI 随尺码（((size - SIZE_ANCHOR) % 24) + 1；非数字兜底 7）
        aci = size_aci(pc.get('size'))
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

        # g 码标识（2026-08-18）：每片质心 ASCII TEXT（g 码-码号，如 ``g01-30``；
        # size 为 None 时只印 g 码），独立 layer 'TEXT'。label 缺席（旧
        # intermediate）跳过。纯 ASCII，无 GBK/字库坑（同标题口径）。
        label = pc.get('label')
        if label:
            cx, cy = centroid(pc['polygon'])
            text = f"{label}-{pc['size']}" if pc.get('size') is not None else label
            msp.add_text(text, dxfattribs={
                'height': 25, 'insert': (round(cx, 2), round(cy, 2)),
                'layer': _DXF_LAYER_TEXT, 'color': 7})

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
