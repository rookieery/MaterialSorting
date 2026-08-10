# -*- coding: utf-8 -*-
"""探查 pass3：把代表 block 的所有 layer 渲染成彩色 SVG，让版师肉眼判断
每层语义 / 刀口是否真的存在。产出 _inspect_preview/*.svg。
用完即删。
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import ezdxf


def decode(s):
    try:
        return s.encode("latin-1").decode("gbk")
    except Exception:
        return s


def load(path):
    try:
        r = ezdxf.recover.readfile(str(path))
        return r[0] if isinstance(r, tuple) else r
    except Exception:
        return ezdxf.readfile(str(path))


def collect_block(block):
    outlines, net, grains, l8 = [], [], [], []
    pts = defaultdict(list)
    for e in block:
        t = e.dxftype()
        try:
            ln = str(e.dxf.layer)
        except Exception:
            ln = "?"
        if t == "POLYLINE":
            v = [(float(p.dxf.location.x), float(p.dxf.location.y)) for p in e.vertices]
            if len(v) < 2:
                continue
            if ln == "1" and len(v) >= 3:
                outlines.append(v)
            elif ln == "14" and len(v) >= 3:
                net.append(v)
            elif ln == "8":
                l8.append(v)
        elif t == "LINE" and ln == "7":
            grains.append((float(e.dxf.start.x), float(e.dxf.start.y),
                           float(e.dxf.end.x), float(e.dxf.end.y)))
        elif t == "POINT":
            loc = e.dxf.location
            pts[ln].append((float(loc.x), float(loc.y)))
    return outlines, net, grains, l8, pts


def bbox_of(polys_and_pts):
    xs, ys = [], []
    for item in polys_and_pts:
        if isinstance(item, tuple):
            if len(item) == 4:        # grain (x1,y1,x2,y2)
                xs += [item[0], item[2]]; ys += [item[1], item[3]]
            elif len(item) == 2:      # single point (x,y)
                xs.append(item[0]); ys.append(item[1])
        else:                         # list of (x,y) = polyline
            for x, y in item:
                xs.append(x); ys.append(y)
    if not xs:
        return 0, 0, 1, 1
    return min(xs), min(ys), max(xs), max(ys)


def render_svg(tag, bname, outlines, net, grains, l8, pts, focus_outline=None):
    """focus_outline: 若指定，只渲染落在该 outline bbox 附近的实体（聚焦单片）。"""
    # 收集所有几何算全局 bbox
    allgeo = outlines + net + l8 + grains + [pt for pl in pts.values() for pt in pl]
    minx, miny, maxx, maxy = bbox_of(allgeo)
    if focus_outline is not None:
        ox = [p[0] for p in focus_outline]; oy = [p[1] for p in focus_outline]
        minx, maxx = min(ox), max(ox)
        miny, maxy = min(oy), max(oy)
        pad = 60
    else:
        pad = 40
    W, H = 900, 1200
    dx = (maxx - minx) or 1.0
    dy = (maxy - miny) or 1.0
    scale = min((W - 2 * pad) / dx, (H - 2 * pad) / dy)
    ox0 = pad - minx * scale + ((W - 2 * pad) - dx * scale) / 2
    oy0 = pad + maxy * scale + ((H - 2 * pad) - dy * scale) / 2

    def tx(x, y):
        return (ox0 + x * scale, oy0 - y * scale)

    def in_focus(x, y):
        if focus_outline is None:
            return True
        return (minx - 80) <= x <= (maxx + 80) and (miny - 80) <= y <= (maxy + 80)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="sans-serif">',
        '<rect width="100%" height="100%" fill="#111"/>',
        f'<text x="14" y="24" fill="#fff" font-size="16">{tag}: {bname}</text>',
    ]
    legend = [
        ("layer1 毛版outline", "#4a9eff"),
        ("layer14 净版", "#39d353"),
        ("layer7 布纹线", "#ff5454"),
        ("layer8 内部线", "#ffb000"),
        ("layer2 POINT", "#00e5ff"),
        ("layer3 POINT", "#e040fb"),
        ("layer4 POINT", "#ffeb3b"),
        ("layer13 POINT", "#ffffff"),
    ]
    for i, (name, col) in enumerate(legend):
        ly = 48 + i * 20
        out.append(f'<rect x="14" y="{ly - 11}" width="14" height="12" fill="{col}"/>')
        out.append(f'<text x="34" y="{ly}" fill="#ddd" font-size="12">{name}</text>')

    # POINT 层（先画，避免压住线）
    pt_layers = {"3": ("#e040fb", 1.1), "2": ("#00e5ff", 1.8), "4": ("#ffeb3b", 2.0), "13": ("#fff", 2.5)}
    for ln, (col, r) in pt_layers.items():
        if ln not in pts:
            continue
        for x, y in pts[ln]:
            if not in_focus(x, y):
                continue
            sx, sy = tx(x, y)
            out.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{r}" fill="{col}" opacity="0.85"/>')

    # layer 8 内部线
    for poly in l8:
        if focus_outline is not None:
            mx = sum(p[0] for p in poly) / len(poly)
            my = sum(p[1] for p in poly) / len(poly)
            if not in_focus(mx, my):
                continue
        pts2 = [tx(x, y) for x, y in poly]
        d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts2)
        out.append(f'<path d="{d}" fill="none" stroke="#ffb000" stroke-width="2.2"/>')

    # layer 14 净版
    for poly in net:
        if focus_outline is not None:
            mx = sum(p[0] for p in poly) / len(poly)
            my = sum(p[1] for p in poly) / len(poly)
            if not in_focus(mx, my):
                continue
        pts2 = [tx(x, y) for x, y in poly]
        d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts2) + " Z"
        out.append(f'<path d="{d}" fill="none" stroke="#39d353" stroke-width="2.0" '
                   f'stroke-dasharray="8 5"/>')

    # layer 1 outline
    for i, poly in enumerate(outlines):
        if focus_outline is not None and poly is not focus_outline:
            # 聚焦时只画目标片
            mx = sum(p[0] for p in poly) / len(poly)
            my = sum(p[1] for p in poly) / len(poly)
            if not in_focus(mx, my):
                continue
        pts2 = [tx(x, y) for x, y in poly]
        d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts2) + " Z"
        out.append(f'<path d="{d}" fill="rgba(74,158,255,0.10)" stroke="#4a9eff" stroke-width="2.4"/>')

    # layer 7 布纹线
    for x1, y1, x2, y2 in grains:
        if focus_outline is not None:
            if not in_focus((x1 + x2) / 2, (y1 + y2) / 2):
                continue
        sx1, sy1 = tx(x1, y1); sx2, sy2 = tx(x2, y2)
        out.append(f'<line x1="{sx1:.1f}" y1="{sy1:.1f}" x2="{sx2:.1f}" y2="{sy2:.1f}" '
                   f'stroke="#ff5454" stroke-width="2.0" stroke-dasharray="9 5"/>')

    out.append("</svg>")
    return "\n".join(out)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    root = Path(__file__).resolve().parents[1]
    data = root / "data"
    outdir = root / "scripts" / "preview"
    outdir.mkdir(exist_ok=True)

    files = [
        ("5156", data / "5156#直筒13%7%大货围加9）双针(1).dxf"),
        ("M1787", data / "M1787#直筒14%7%大货围加9）双针30码脚口8英寸(1)(2).dxf"),
    ]
    for tag, f in files:
        if not f.exists():
            print(f"[跳过] {f}")
            continue
        doc = load(f)
        for block in doc.blocks:
            if block.name.startswith("*"):
                continue
            bname = decode(block.name)
            # 只渲染 28 码的 腰 block（小、全 layer）和主片 block（复杂）
            if not bname.endswith("-28") and not bname.endswith(".28"):
                continue
            outlines, net, grains, l8, pts = collect_block(block)
            kind = "main" if (len(outlines) >= 5) else bname.rsplit(".", 1)[-1].rsplit("-", 1)[0]
            if "腰" not in bname and len(outlines) < 5:
                # 只取主片和腰
                if "单" not in bname and "双" not in bname:
                    pass
            # 主片 block：额外渲染聚焦第 0 片（前/后片）
            if len(outlines) >= 5:
                svg_all = render_svg(f"{tag}-主片block(全部)", bname, outlines, net, grains, l8, pts)
                (outdir / f"{tag}_main_all.svg").write_text(svg_all, encoding="utf-8")
                # 聚焦最大片
                biggest = max(outlines, key=lambda p: len(p))
                svg_f = render_svg(f"{tag}-主片block(聚焦最大片)", bname, outlines, net, grains, l8, pts,
                                   focus_outline=biggest)
                (outdir / f"{tag}_main_focus.svg").write_text(svg_f, encoding="utf-8")
            elif "腰" in bname:
                svg = render_svg(f"{tag}-腰block", bname, outlines, net, grains, l8, pts)
                (outdir / f"{tag}_waist.svg").write_text(svg, encoding="utf-8")
            elif "单" in bname:
                svg = render_svg(f"{tag}-单block", bname, outlines, net, grains, l8, pts)
                (outdir / f"{tag}_dan.svg").write_text(svg, encoding="utf-8")
    print(f"SVG 已输出到: {outdir}")
    for p in sorted(outdir.glob("*.svg")):
        print(f"  {p.name}")


if __name__ == "__main__":
    main()
