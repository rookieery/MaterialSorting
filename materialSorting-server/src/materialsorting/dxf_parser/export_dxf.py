"""把提取的裁片导出为 DXF（每类型×每码一个文件），供排料算法使用。

输出 R12 DXF（富怡 ET 兼容），每文件含一个裁片：
  layer 1 = 毛版外轮廓(闭合 POLYLINE)
  layer 7 = 布纹线(LINE，保留原始方向；排料时按方向旋转统一水平)
命名：<类型>_<码号>.dxf，如 后片_30.dxf
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
    doc = ezdxf.new("R12")
    doc.header["$MEASUREMENT"] = 1     # metric（单位 mm 隐式，R12 不写 $INSUNITS）
    msp = doc.modelspace()
    doc.layers.add("1", color=1)      # 毛版外轮廓
    doc.layers.add("7", color=7)      # 布纹线

    pts = [(float(x), float(y)) for x, y in piece.polygon_mm]
    poly = msp.add_polyline2d(pts, dxfattribs={"layer": "1"})
    if piece.is_closed:
        poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED

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
    pieces = explore.collect_pieces(src)
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
