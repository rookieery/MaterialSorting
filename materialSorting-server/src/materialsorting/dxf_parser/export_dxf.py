"""把提取的裁片导出为 DXF（每类型×每码一个文件），供排料算法使用。

输出 R12 DXF（富怡 ET 兼容），每文件含一个裁片：
  layer 1  = 毛版外轮廓(闭合 POLYLINE)
  layer 14 = 净版轮廓(闭合 POLYLINE，US-024)
  layer 8  = 内部线(多条 POLYLINE，US-024)
  layer 4  = 刺口(POINT，位置；法线读时按最近边重算，US-024)
  layer 7  = 布纹线(LINE，保留原始方向；排料时按方向旋转统一水平)
命名：<类型>_<码号>.dxf，如 后片_30.dxf

US-024：layer14/8/4 仅当 PieceOutline 携带对应字段（来自 ``collect_pieces_with_details``）
才写出；旧调用方（仅 layer1+layer7 的 PieceOutline）向后兼容 —— 字段缺省/default_factory=[])
时跳过额外 layer，写出与原行为一致。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import ezdxf
from ezdxf.lldxf.const import POLYLINE_CLOSED

# 抑制 ezdxf 的 R12 $INSUNITS 等已知无害警告（R12 规范不导出单位变量，单位 mm 隐式）
logging.getLogger("ezdxf").setLevel(logging.ERROR)

from .. import paths
from . import explore
from .collect import collect_pieces_with_details

# group 编号 → 类型名（用户基于 SVG 人工识别确认）
GROUP_NAMES = {
    "g00": "后片", "g01": "前片", "g02": "机头", "g03": "裤耳",
    "g04": "前袋", "g05": "火机袋", "g06": "后袋", "g07": "单排",
    "g08": "双排", "g09": "腰",
}


def assign_group_no(pieces) -> dict[str, str]:
    """复用 explore 的排序逻辑，把 group_key 映射为 g00..g09。"""
    groups: dict[str, list] = {}
    for p in pieces:
        groups.setdefault(p.group_key, []).append(p)
    ordered = sorted(groups.keys(), key=lambda k: explore.group_sort_key(groups[k]))
    return {k: f"g{i:02d}" for i, k in enumerate(ordered)}


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


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="导出裁片为 DXF（按类型命名）")
    ap.add_argument("--dxf", default=paths.MASTER_DXF_GLOB)
    ap.add_argument("--out", default=paths.PIECES_DIR)
    args = ap.parse_args()

    src = explore.resolve_dxf(args.dxf)
    if src is None or not src.exists():
        print(f"[ERROR] 找不到 DXF: {args.dxf}", file=sys.stderr)
        sys.exit(1)
    # US-024：用 collect_pieces_with_details 取代 explore.collect_pieces，让 write_piece_dxf
    # 拿到 PieceOutline 全 5 层（layer1+layer7+layer14+layer8+layer4）。assign_group_no 与
    # write_piece_dxf 兼容 PieceOutline additive 扩展（旧调用方零改动）。
    pieces = collect_pieces_with_details(src)
    gmap = assign_group_no(pieces)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    count = 0
    by_type: dict[str, int] = {}
    for p in pieces:
        gno = gmap[p.group_key]
        name = GROUP_NAMES.get(gno)
        if name is None:
            continue
        write_piece_dxf(p, outdir / f"{name}_{p.size}.dxf")
        by_type[name] = by_type.get(name, 0) + 1
        count += 1

    print(f"读取母版: {src}")
    print(f"生成 DXF: {count} 个 → {outdir}")
    print("按类型:")
    for name in GROUP_NAMES.values():
        if name in by_type:
            print(f"  {name}: {by_type[name]} 码")


if __name__ == "__main__":
    main()
