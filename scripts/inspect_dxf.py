# -*- coding: utf-8 -*-
"""临时探查脚本：盘点两个生产母版的 layer / 实体分布，并专猎刀口。
用完即删。用法：python inspect_dxf.py "<path1>" "<path2>" ...
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import ezdxf


def decode(s: str) -> str:
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("gbk")
    except Exception:
        return s


def load(path: str):
    try:
        r = ezdxf.recover.readfile(path)
        return r[0] if isinstance(r, tuple) else r
    except Exception:
        return ezdxf.readfile(path)


def inspect(path: Path) -> None:
    print("=" * 90)
    print(f"文件: {path.name}")
    print("=" * 90)
    doc = load(str(path))

    # ---- 1. Header ----
    hdr = doc.header
    print(f"$ACADVER      = {hdr.get('$ACADVER', '?')}")
    print(f"$INSUNITS     = {hdr.get('$INSUNITS', '?')}")
    print(f"$DWGCODEPAGE  = {hdr.get('$DWGCODEPAGE', '?')}")
    print(f"modelspace 实体数 = {len(list(doc.modelspace()))}")

    # ---- 2. Layer 表 ----
    print("\n--- Layer 表（name | color）---")
    for layer in doc.layers:
        try:
            print(f"  {layer.dxf.name!r:24} color={layer.dxf.color}")
        except Exception:
            print(f"  {layer}")

    # ---- 3. 全局实体类型计数（blocks 定义内）----
    global_types = Counter()
    layer_entity = defaultdict(Counter)   # layer -> {dxftype: count}
    block_layer_entity = defaultdict(lambda: defaultdict(Counter))  # block -> layer -> {type: count}
    anon = 0
    real_blocks = 0
    for block in doc.blocks:
        if block.name.startswith("*"):
            anon += 1
            continue
        real_blocks += 1
        bname = decode(block.name)
        for e in block:
            t = e.dxftype()
            global_types[t] += 1
            try:
                ln = str(e.dxf.layer)
            except Exception:
                ln = "?"
            layer_entity[ln][t] += 1
            block_layer_entity[bname][ln][t] += 1
    print(f"\n非匿名 block 数 = {real_blocks}，匿名 block 数 = {anon}")
    print("\n--- 全局实体类型计数（blocks 内）---")
    for t, c in global_types.most_common():
        print(f"  {t:14} {c}")

    print("\n--- Layer × 实体类型矩阵（blocks 内）---")
    for ln in sorted(layer_entity):
        parts = ", ".join(f"{t}×{c}" for t, c in layer_entity[ln].most_common())
        print(f"  layer {ln!r:10} → {parts}")

    # ---- 4. 刀口猎杀 ----
    print("\n--- 刀口候选排查 ---")
    # (a) POINT 实体
    point_count = 0
    point_layers = Counter()
    point_samples = []
    for block in doc.blocks:
        if block.name.startswith("*"):
            continue
        for e in block:
            if e.dxftype() == "POINT":
                point_count += 1
                try:
                    point_layers[str(e.dxf.layer)] += 1
                except Exception:
                    point_layers["?"] += 1
                if len(point_samples) < 5:
                    try:
                        loc = e.dxf.location
                        point_samples.append((round(float(loc.x), 1), round(float(loc.y), 1)))
                    except Exception:
                        pass
    print(f"  POINT 实体总数 = {point_count}  按layer: {dict(point_layers)}  样本: {point_samples}")

    # (b) POLYLINE 顶点 bulge != 0（弧顶点，常作刀口/圆角）
    bulge_verts = 0
    bulge_samples = []
    # (c) POLYLINE 顶点宽度突变（start_width/end_width 非默认，某些 CAD 用它标刀口）
    width_verts = 0
    width_samples = []
    for block in doc.blocks:
        if block.name.startswith("*"):
            continue
        for e in block:
            if e.dxftype() != "POLYLINE":
                continue
            for v in e.vertices:
                try:
                    b = float(v.dxf.bulge)
                except Exception:
                    b = 0.0
                if abs(b) > 1e-6:
                    bulge_verts += 1
                    if len(bulge_samples) < 8:
                        loc = v.dxf.location
                        bulge_samples.append((round(float(loc.x), 1), round(float(loc.y), 1), round(b, 3)))
                try:
                    sw = float(v.dxf.start_width)
                    ew = float(v.dxf.end_width)
                except Exception:
                    sw = ew = 0.0
                if sw > 1e-3 or ew > 1e-3:
                    width_verts += 1
                    if len(width_samples) < 8:
                        loc = v.dxf.location
                        width_samples.append((round(float(loc.x), 1), round(float(loc.y), 1), round(sw, 2), round(ew, 2)))
    print(f"  非零 bulge 顶点数 = {bulge_verts}  样本(x,y,bulge): {bulge_samples}")
    print(f"  非零宽度顶点数   = {width_verts}  样本(x,y,sw,ew): {width_samples}")

    # (d) CIRCLE / ARC 实体（小圆/弧也可能作刀口）
    circ = Counter()
    for block in doc.blocks:
        if block.name.startswith("*"):
            continue
        for e in block:
            if e.dxftype() in ("CIRCLE", "ARC"):
                try:
                    circ[(e.dxftype(), str(e.dxf.layer))] += 1
                except Exception:
                    circ[(e.dxftype(), "?")] += 1
    print(f"  CIRCLE/ARC 计数 = {dict(circ) if circ else '无'}")

    # (e) 短 LINE 段（长度 < 30mm，可能作刀口标记），按 layer 统计
    short_lines = defaultdict(int)
    short_samples = []
    for block in doc.blocks:
        if block.name.startswith("*"):
            continue
        for e in block:
            if e.dxftype() != "LINE":
                continue
            try:
                dx = float(e.dxf.end.x) - float(e.dxf.start.x)
                dy = float(e.dxf.end.y) - float(e.dxf.start.y)
                length = (dx * dx + dy * dy) ** 0.5
                ln = str(e.dxf.layer)
            except Exception:
                continue
            if length < 30.0:
                short_lines[ln] += 1
                if len(short_samples) < 10:
                    short_samples.append((ln, round(length, 1)))
    print(f"  短LINE段(<30mm) 按layer: {dict(short_lines) if short_lines else '无'}  样本(layer,len): {short_samples}")

    # ---- 5. 前 3 个非匿名 block 的明细（看 block 结构）----
    print("\n--- 前 3 个非匿名 block 明细 ---")
    shown = 0
    for block in doc.blocks:
        if block.name.startswith("*"):
            continue
        bname = decode(block.name)
        le = block_layer_entity.get(bname, {})
        print(f"  block {bname!r}:")
        for ln in sorted(le):
            parts = ", ".join(f"{t}×{c}" for t, c in le[ln].most_common())
            print(f"      layer {ln!r:8} → {parts}")
        shown += 1
        if shown >= 3:
            break
    print()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = sys.argv[1:]
    if not args:
        # 默认探查 data/ 下两个生产母版
        root = Path(__file__).resolve().parents[1] / "data"
        args = [
            str(root / "5156#直筒13%7%大货围加9）双针(1).dxf"),
            str(root / "M1787#直筒14%7%大货围加9）双针30码脚口8英寸(1)(2).dxf"),
        ]
    for a in args:
        p = Path(a)
        if not p.exists():
            print(f"[跳过] 找不到: {a}")
            continue
        inspect(p)


if __name__ == "__main__":
    main()
