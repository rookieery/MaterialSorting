"""把提取的裁片导出为单片 R12 DXF（富怡 ET 兼容），供排料管线消费。

每文件含一个裁片（5 层）：
  layer 1  = 毛版外轮廓(闭合 POLYLINE)
  layer 14 = 净版轮廓(闭合 POLYLINE，US-024)
  layer 8  = 内部线(多条 POLYLINE，US-024)
  layer 4  = 刺口(POINT，位置；法线读时按最近边重算，US-024)
  layer 7  = 布纹线(LINE，保留原始方向；排料时按方向旋转统一水平)

库函数 ``write_piece_dxf`` 由 ``web/server._commit_to_nesting_sync`` 调用：上传母版 →
切单裁片 ``{label}_{size}.dxf`` 到 ``out/uploads/<doc_id>_pieces/``（裁片 g 码来自
``nesting_engine.labeling.assign_codes``，本模块不做任何名称识别）。原 CLI
``ms-export-dxf`` 已移除（Web 上传取代），生成 intermediate 的唯一途径是
「Web 上传母版 → commit-to-nesting」。

US-024：layer14/8/4 仅当 PieceOutline 携带对应字段（来自 ``collect_pieces_with_details``）
才写出；旧调用方（仅 layer1+layer7 的 PieceOutline）向后兼容 —— 字段缺省/default_factory=[])
时跳过额外 layer，写出与原行为一致。
"""
from __future__ import annotations

import logging
from pathlib import Path

import ezdxf
from ezdxf.lldxf.const import POLYLINE_CLOSED

# 抑制 ezdxf 的 R12 $INSUNITS 等已知无害警告（R12 规范不导出单位变量，单位 mm 隐式）
logging.getLogger("ezdxf").setLevel(logging.ERROR)

def write_piece_dxf(piece, out_path: Path) -> None:
    """写单片 R12 DXF（5 层，向后兼容旧 PieceOutline 仅含 layer1+layer7）。

    US-024：若 PieceOutline 携带 ``net_polygon`` / ``internal_lines`` / ``notches``
    （来自 ``collect_pieces_with_details``），则同时写出 layer14/8/4。法线信息不存盘
    （POINT 仅 location）—— 读时由 ``nesting_bounds.load_pieces._read_piece_full`` 按
    outline 最近边重算（与 ``collect._nearest_edge_with_normal`` 同算法）。
    """
    doc = ezdxf.new("R12")
    doc.header["$MEASUREMENT"] = 1     # metric（单位 mm 隐式，R12 不写 $INSUNITS）
    msp = doc.modelspace()
    doc.layers.add("1", color=1)      # 毛版外轮廓
    doc.layers.add("7", color=7)      # 布纹线
    # US-024：5 层额外 layer（与 collect.LAYER_MAPPING 一致；layer id 字符串）
    doc.layers.add("14", color=3)     # 净版
    doc.layers.add("8", color=6)      # 内部线
    doc.layers.add("4", color=2)      # 刺口

    pts = [(float(x), float(y)) for x, y in piece.polygon_mm]
    poly = msp.add_polyline2d(pts, dxfattribs={"layer": "1"})
    if piece.is_closed:
        poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED

    # US-024 layer14 净版（闭合 POLYLINE；空 list / <2 顶点跳过）
    net_poly = getattr(piece, "net_polygon", None) or []
    if len(net_poly) >= 2:
        net_pts = [(float(x), float(y)) for x, y in net_poly]
        net_ent = msp.add_polyline2d(net_pts, dxfattribs={"layer": "14"})
        net_ent.dxf.flags = net_ent.dxf.flags | POLYLINE_CLOSED

    # US-024 layer8 内部线（多条 POLYLINE，不闭合）
    internal_lines = getattr(piece, "internal_lines", None) or []
    for line in internal_lines:
        if len(line) < 2:
            continue
        line_pts = [(float(x), float(y)) for x, y in line]
        msp.add_polyline2d(line_pts, dxfattribs={"layer": "8"})

    # US-024 layer4 刺口（POINT 位置；法线不存盘，读时按 outline 最近边重算）
    notches = getattr(piece, "notches", None) or []
    for notch in notches:
        # notch 格式 (x, y, nx, ny) —— 法线 (nx, ny) 丢弃
        msp.add_point((float(notch[0]), float(notch[1])), dxfattribs={"layer": "4"})

    if piece.grain_line:
        gl = piece.grain_line
        msp.add_line((float(gl[0]), float(gl[1])), (float(gl[2]), float(gl[3])),
                     dxfattribs={"layer": "7"})
    doc.saveas(str(out_path))
