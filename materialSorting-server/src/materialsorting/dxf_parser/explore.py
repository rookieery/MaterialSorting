"""排料母版 DXF 全裁片解析探索 CLI。

流程：遍历所有 block 定义 → 每条 layer1 闭合 POLYLINE = 一个裁片 →
按 group_key(去码号block名#序号) 分组 → 每组一个文件夹(内含各码 SVG + JSON) →
另出全量 CSV 与总览 SVG。

用法：
    python explore.py                              # 用默认母版 data/M1787*(2).dxf
    python explore.py --dxf "data/xxx.dxf" --out "../_output"
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

from .. import paths
from .model import PieceOutline
from . import geometry, reader


# ---------------------------------------------------------------- 提取

def collect_pieces(path: Path) -> list[PieceOutline]:
    """从母版提取所有裁片（每条 layer1 POLYLINE 一片），原样保留顶点。"""
    doc = reader.load_doc(str(path))
    pieces: list[PieceOutline] = []

    for block in doc.blocks:
        if block.name.startswith("*"):
            continue  # 跳过匿名块（*D*, *P* 等）
        bname_raw = block.name
        bname = reader.decode_str(bname_raw)
        size = reader.parse_size(bname)
        group_base = reader.strip_size(bname)
        ents = list(block)

        # layer1 POLYLINE = 裁片外轮廓（顶点 < 3 的退化片跳过）
        l1_polys: list[list[tuple[float, float]]] = []
        l1_ents = []
        for e in ents:
            if e.dxftype() == "POLYLINE" and str(e.dxf.layer) == "1":
                pts = reader.polyline_points(e)
                if pts and len(pts) >= 3:
                    l1_polys.append(pts)
                    l1_ents.append(e)
        if not l1_polys:
            continue

        # layer7 LINE = 布纹线（每片一条，方向因裁片而异：多数水平，机头/腰为竖直）
        grains: list[tuple[float, float, float, float]] = []
        for e in ents:
            if e.dxftype() == "LINE" and str(e.dxf.layer) == "7":
                grains.append((float(e.dxf.start.x), float(e.dxf.start.y),
                               float(e.dxf.end.x), float(e.dxf.end.y)))
        matched = geometry.match_grain(grains, l1_polys)

        for idx, pts in enumerate(l1_polys):
            peri = geometry.polygon_perimeter(pts)
            area = geometry.polygon_area(pts)
            bb = geometry.bbox_of(pts)
            closed = reader.is_polyline_closed(l1_ents[idx])
            gl = matched[idx]
            gl_ang = geometry.line_angle_deg((gl[0], gl[1]), (gl[2], gl[3])) if gl else None
            if gl_ang is None:
                gl_orient = "unknown"
            elif abs(gl_ang) <= 45.0:
                gl_orient = "horizontal"
            else:
                gl_orient = "vertical"
            pieces.append(PieceOutline(
                source_file=path.name,
                block_name_raw=bname_raw,
                block_name=bname,
                size=size,
                piece_index=idx,
                group_key=f"{group_base}#{idx}",
                polygon_mm=[(float(x), float(y)) for x, y in pts],
                is_closed=closed,
                vertex_count=len(pts),
                perimeter_mm=float(peri),
                area_mm2=float(area),
                bbox_mm=(float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])),
                grain_line=tuple(float(v) for v in gl) if gl else None,
                grain_angle_deg=float(gl_ang) if gl_ang is not None else None,
                grain_orientation=gl_orient,
            ))
    return pieces


# ---------------------------------------------------------------- 输出命名

def sanitize(s: str) -> str:
    """把 block 名清理成合法文件夹名片段。"""
    out = []
    for ch in s:
        if ch.isalnum() or ch in "_-":
            out.append(ch)
        else:
            out.append("_")
    s2 = "".join(out)
    while "__" in s2:
        s2 = s2.replace("__", "_")
    return s2.strip("_") or "x"


def group_label(group_base: str) -> str:
    """主片 block(类型为空) 标 'main'，其余取 noname. 之后的部分。"""
    tail = group_base
    prefix = "noname."
    if tail.startswith(prefix):
        tail = tail[len(prefix):]
    tail = tail.rstrip(".")
    if tail == "":
        return "main"
    return sanitize(tail)


def group_sort_key(members: list[PieceOutline]):
    """主片组排前，其余按 block 名 + 序号。"""
    gb = reader.strip_size(members[0].block_name)
    is_main = 0 if gb.rstrip(".") == "noname" else 1
    return (is_main, gb, members[0].piece_index)


# ---------------------------------------------------------------- SVG

def _flip(pts, bbox, w, h, pad=30):
    """DXF 坐标(数学系,y向上) → SVG 视口(y向下)，等比缩放居中。"""
    minx, miny, maxx, maxy = bbox
    dx = (maxx - minx) or 1.0
    dy = (maxy - miny) or 1.0
    scale = min((w - 2 * pad) / dx, (h - 2 * pad) / dy)
    ox = pad - minx * scale + ((w - 2 * pad) - dx * scale) / 2
    oy = pad + maxy * scale + ((h - 2 * pad) - dy * scale) / 2
    return [(ox + x * scale, oy - y * scale) for x, y in pts]


def _color_for(key: str) -> str:
    """稳定(不随 PYTHONHASHSEED 变)的分组配色。"""
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16) % 360
    return f"hsl({h},65%,55%)"


def piece_svg(p: PieceOutline, w: int = 520, h: int = 680) -> str:
    mapped = _flip(p.polygon_mm, p.bbox_mm, w, h)
    d = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in mapped) + (" Z" if p.is_closed else "")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="sans-serif" font-size="13">',
        '<rect width="100%" height="100%" fill="#fafafa"/>',
        f'<path d="{d}" fill="rgba(80,140,220,0.25)" stroke="#224466" stroke-width="1.5"/>',
    ]
    if p.grain_line:
        gl = p.grain_line
        gm = _flip([(gl[0], gl[1]), (gl[2], gl[3])], p.bbox_mm, w, h)
        parts.append(
            f'<line x1="{gm[0][0]:.2f}" y1="{gm[0][1]:.2f}" x2="{gm[1][0]:.2f}" '
            f'y2="{gm[1][1]:.2f}" stroke="#cc3333" stroke-width="1.6" stroke-dasharray="7 4"/>'
        )
    area_cm2 = p.area_mm2 / 100.0
    peri_cm = p.perimeter_mm / 10.0
    parts.append(f'<text x="12" y="22" fill="#111">{p.block_name}  ·  size={p.size}  ·  idx={p.piece_index}</text>')
    parts.append(
        f'<text x="12" y="42" fill="#444">verts={p.vertex_count}  closed={int(p.is_closed)}  '
        f'peri={peri_cm:.1f}cm  area={area_cm2:.1f}cm²</text>'
    )
    if p.grain_angle_deg is not None:
        parts.append(
            f'<text x="12" y="62" fill="#cc3333">grain={p.grain_angle_deg:.2f}°  ({p.grain_orientation})</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def overview_svg(pieces: list[PieceOutline], w: int = 1700, h: int = 1200, pad: int = 50) -> str:
    xs, ys = [], []
    for p in pieces:
        xs.append(p.bbox_mm[0]); xs.append(p.bbox_mm[2])
        ys.append(p.bbox_mm[1]); ys.append(p.bbox_mm[3])
    gminx, gminy, gmaxx, gmaxy = min(xs), min(ys), max(xs), max(ys)
    dx = (gmaxx - gminx) or 1.0
    dy = (gmaxy - gminy) or 1.0
    scale = min((w - 2 * pad) / dx, (h - 2 * pad - 220) / dy)  # 底部留图例
    ox = pad - gminx * scale
    oy = pad + gmaxy * scale

    def tx(x, y):
        return (ox + x * scale, oy - y * scale)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="sans-serif" font-size="12">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="12" y="22" fill="#111" font-size="16">全裁片总览 · {pieces[0].source_file if pieces else ""} · 共 {len(pieces)} 片</text>',
    ]
    for p in pieces:
        pts = [tx(x, y) for x, y in p.polygon_mm]
        d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts) + (" Z" if p.is_closed else "")
        col = _color_for(p.group_key)
        out.append(
            f'<path d="{d}" fill="{col}" fill-opacity="0.30" stroke="{col}" '
            f'stroke-width="0.8" stroke-opacity="0.9"/>'
        )

    # 图例（按 g 编号顺序）
    groups: dict[str, list[PieceOutline]] = {}
    for p in pieces:
        groups.setdefault(p.group_key, []).append(p)
    ordered = sorted(groups.keys(), key=lambda k: group_sort_key(groups[k]))
    out.append(f'<text x="12" y="{h - 200}" fill="#333" font-size="13">分组图例（{len(ordered)} 组）：</text>')
    gx, gy = 12, h - 178
    col_w = 420
    per_row = max(1, w // col_w)
    for i, k in enumerate(ordered):
        members = groups[k]
        label = group_label(reader.strip_size(members[0].block_name))
        col = _color_for(k)
        r, c = divmod(i, per_row)
        x = gx + c * col_w
        y = gy + r * 22
        out.append(f'<rect x="{x}" y="{y}" width="16" height="11" fill="{col}" fill-opacity="0.6" stroke="#333"/>')
        out.append(
            f'<text x="{x + 22}" y="{y + 10}" fill="#222">g{i:02d} {label}_idx{members[0].piece_index} '
            f'· n={len(members)} · {members[0].block_name}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- 落盘

def write_outputs(pieces: list[PieceOutline], outdir: Path) -> list[tuple[int, str, str, int]]:
    """按 group_key 分组写到 outdir。返回 [(group_no, label, block_name, count), ...]。"""
    outdir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[PieceOutline]] = {}
    for p in pieces:
        groups.setdefault(p.group_key, []).append(p)
    ordered = sorted(groups.keys(), key=lambda k: group_sort_key(groups[k]))

    summary: list[tuple[PieceOutline, int, str]] = []
    info: list[tuple[int, str, str, int]] = []
    for i, k in enumerate(ordered):
        members = sorted(groups[k], key=lambda p: (p.size if p.size is not None else 0))
        gb = reader.strip_size(members[0].block_name)
        label = group_label(gb)
        idx = members[0].piece_index
        folder = outdir / f"g{i:02d}_{label}_idx{idx}"
        folder.mkdir(parents=True, exist_ok=True)
        for p in members:
            (folder / f"size_{p.size}.svg").write_text(piece_svg(p), encoding="utf-8")
        (folder / "pieces.json").write_text(
            json.dumps([p.to_dict() for p in members], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for p in members:
            summary.append((p, i, label))
        info.append((i, label, members[0].block_name, len(members)))

    write_csv(outdir / "_all_pieces.csv", summary)
    (outdir / "_overview.svg").write_text(overview_svg(pieces), encoding="utf-8")
    return info


def write_csv(path: Path, rows: list[tuple[PieceOutline, int, str]]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "group_no", "group_label", "group_key", "block_name", "size", "idx",
            "closed", "verts", "peri_mm", "area_mm2", "peri_cm", "area_cm2",
            "bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy", "grain_deg", "grain_orient",
        ])
        for p, gi, label in rows:
            bb = p.bbox_mm
            w.writerow([
                f"g{gi:02d}", label, p.group_key, p.block_name, p.size, p.piece_index,
                int(p.is_closed), p.vertex_count, round(p.perimeter_mm, 1), round(p.area_mm2, 1),
                round(p.perimeter_mm / 10, 2), round(p.area_mm2 / 100, 2),
                round(bb[0], 1), round(bb[1], 1), round(bb[2], 1), round(bb[3], 1),
                "" if p.grain_angle_deg is None else round(p.grain_angle_deg, 2),
                p.grain_orientation,
            ])


# ---------------------------------------------------------------- CLI

def resolve_dxf(arg: str) -> Path | None:
    if any(c in arg for c in "*?["):
        hits = sorted(glob.glob(arg))
        return Path(hits[0]) if hits else None
    p = Path(arg)
    if p.exists():
        return p
    hits = sorted(glob.glob(arg))
    return Path(hits[0]) if hits else None


def main():
    # Windows 终端默认 GBK，重定向/管道捕获时强制 UTF-8，避免中文乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="排料母版 DXF 全裁片解析探索")
    ap.add_argument("--dxf", default=paths.MASTER_DXF_GLOB, help="母版 DXF 路径或通配符")
    ap.add_argument("--out", default=paths.SPARROW_DIR, help="输出目录")
    args = ap.parse_args()

    dxf_path = resolve_dxf(args.dxf)
    if dxf_path is None or not dxf_path.exists():
        print(f"[ERROR] 找不到 DXF: {args.dxf}", file=sys.stderr)
        sys.exit(1)
    outdir = Path(args.out)

    print(f"读取母版: {dxf_path}")
    pieces = collect_pieces(dxf_path)
    print(f"提取裁片: {len(pieces)} 片")

    info = write_outputs(pieces, outdir)
    print(f"分组数:   {len(info)} 组")
    print(f"输出目录: {outdir}\n")
    print(f"{'组':<6}{'标签':<16}{'block(样本)':<34}{'片数':<6}")
    for gi, label, bname, n in info:
        print(f"g{gi:02d}   {label:<16}{bname:<34}{n:<6}")


if __name__ == "__main__":
    main()
