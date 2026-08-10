# -*- coding: utf-8 -*-
"""探查 pass2：对每个 block，把各 point 层(layer 2/3/4/13)的点按
"到 layer1 轮廓的距离" 分类，判断它们到底是 轮廓加密 / 内部填充 / 刀口。
同时看 layer 8 POLYLINE 是否在轮廓内部(=内部线条)。
用完即删。
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
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


def point_seg_dist(px, py, x1, y1, x2, y2):
    """点到线段距离。"""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * dx, y1 + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def point_poly_min_dist(px, py, poly):
    """点到多边形边界的最短距离。"""
    best = float("inf")
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        d = point_seg_dist(px, py, x1, y1, x2, y2)
        if d < best:
            best = d
    return best


def point_in_poly(px, py, poly):
    """射线法点在多边形内。"""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def inspect(path):
    print("=" * 88)
    print(f"文件: {path.name}")
    print("=" * 88)
    doc = load(path)

    # 按 block 聚合
    blocks = []
    for block in doc.blocks:
        if block.name.startswith("*"):
            continue
        bname = decode(block.name)
        outlines = []  # layer1 POLYLINE 顶点列表
        l8_polys = []
        pts_by_layer = defaultdict(list)  # layer -> [(x,y),...]
        for e in block:
            t = e.dxftype()
            try:
                ln = str(e.dxf.layer)
            except Exception:
                ln = "?"
            if t == "POLYLINE":
                pts = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in e.vertices]
                if ln == "1" and len(pts) >= 3:
                    outlines.append(pts)
                elif ln == "8" and len(pts) >= 2:
                    l8_polys.append(pts)
            elif t == "POINT":
                loc = e.dxf.location
                pts_by_layer[ln].append((float(loc.x), float(loc.y)))
        blocks.append((bname, outlines, l8_polys, pts_by_layer))

    # 选 3 个代表 block 深入看：主片(6 outline)、腰(1 outline)、单(1 outline 固定片)
    # 先按 outline 数排序找代表
    by_outline_count = sorted(blocks, key=lambda b: (-len(b[1]), b[0]))
    targets = []
    seen_kinds = set()
    for bname, outlines, l8, pts in by_outline_count:
        # 用 block 名的"类型"部分去重
        kind = decode(bname).rsplit("-", 1)[0] if "-" in bname else bname
        # 取一个主片、一个腰、一个小片
        for key, label in [("noname..", "主片"), ("腰", "腰"), ("单", "单"), ("-", "主片5156")]:
            if label not in seen_kinds and (key in bname):
                targets.append((label, bname, outlines, l8, pts))
                seen_kinds.add(label)
                break
    if not targets:
        targets = [(b[0], b[0], b[1], b[2], b[3]) for b in blocks[:3]]

    for label, bname, outlines, l8_polys, pts_by_layer in targets:
        print(f"\n### block [{label}] {bname!r}  outline数={len(outlines)}  layer8线数={len(l8_polys)}")
        if not outlines:
            print("  （无 layer1 outline，跳过）")
            continue
        # 每片 outline 的基本信息
        for i, poly in enumerate(outlines):
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            print(f"  outline[{i}] verts={len(poly)} bbox=({min(xs):.0f},{min(ys):.0f})-({max(xs):.0f},{max(ys):.0f})")

        # 分类各 point 层
        TOL_ON = 2.0  # mm，距轮廓边<2mm 视为"贴轮廓"
        for ln in sorted(pts_by_layer):
            pts = pts_by_layer[ln]
            if ln not in ("2", "3", "4", "13"):
                continue
            on, inside, outside, near = 0, 0, 0, 0
            dists = []
            for px, py in pts:
                md = min(point_poly_min_dist(px, py, poly) for poly in outlines)
                dists.append(md)
                if md <= TOL_ON:
                    on += 1
                elif md <= 8.0:
                    near += 1
                else:
                    # 判断在哪个片内部
                    in_any = any(point_in_poly(px, py, poly) for poly in outlines)
                    if in_any:
                        inside += 1
                    else:
                        outside += 1
            dists.sort()
            med = dists[len(dists) // 2] if dists else 0
            p10 = dists[len(dists) // 10] if dists else 0
            p90 = dists[len(dists) * 9 // 10] if dists else 0
            print(f"  layer {ln:3} POINT数={len(pts):5} | 贴轮廓(<2mm)={on:5} 近轮廓(2-8)={near:4} "
                  f"内部={inside:4} 外部={outside:4} | 距离 p10={p10:.2f} 中位={med:.2f} p90={p90:.2f} mm")

        # layer 8 POLYLINE 是否在 outline 内部（取每条线中点判断）
        for i, poly in enumerate(l8_polys):
            mx = sum(p[0] for p in poly) / len(poly)
            my = sum(p[1] for p in poly) / len(poly)
            in_any = any(point_in_poly(mx, my, o) for o in outlines)
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            print(f"  layer8 线[{i}] verts={len(poly)} 中点在outline内={in_any} "
                  f"bbox=({min(xs):.0f},{min(ys):.0f})-({max(xs):.0f},{max(ys):.0f})")
    print()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    root = Path(__file__).resolve().parents[1] / "data"
    files = [
        root / "5156#直筒13%7%大货围加9）双针(1).dxf",
        root / "M1787#直筒14%7%大货围加9）双针30码脚口8英寸(1)(2).dxf",
    ]
    for f in files:
        if f.exists():
            inspect(f)
        else:
            print(f"[跳过] {f}")


if __name__ == "__main__":
    main()
