# -*- coding: utf-8 -*-
"""读 layer 2/4 上 POINT 旁边的 TEXT 标签内容 + 对应坐标，判断它们是刀口还是别的。
聚焦 腰-30（有 2/4 双层 TEXT）和 -30 主片。用完即删。
"""
from __future__ import annotations
import sys
from pathlib import Path
import ezdxf

def decode(s):
    try: return s.encode("latin-1").decode("gbk")
    except Exception: return s

def load(path):
    try:
        r = ezdxf.recover.readfile(str(path)); return r[0] if isinstance(r, tuple) else r
    except Exception:
        return ezdxf.readfile(str(path))

def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    p = Path(__file__).resolve().parents[1] / "data" / "5156#直筒13%7%大货围加9）双针(1).dxf"
    doc = load(p)
    targets = {"腰-30", "-30"}
    for block in doc.blocks:
        if block.name.startswith("*"):
            continue
        bname = decode(block.name)
        if bname not in targets:
            continue
        print(f"\n===== block {bname!r} =====")
        layer2_pts, layer4_pts = [], []
        texts = []  # (layer, text, x, y)
        for e in block:
            t = e.dxftype()
            try: ln = str(e.dxf.layer)
            except Exception: ln = "?"
            if t == "POINT" and ln in ("2", "4"):
                loc = e.dxf.location
                (layer2_pts if ln == "2" else layer4_pts).append((round(float(loc.x),1), round(float(loc.y),1)))
            elif t == "TEXT" and ln in ("2", "4"):
                loc = e.dxf.insert if e.dxf.hasattr("insert") else e.dxf.start
                texts.append((ln, decode(e.dxf.text), round(float(loc.x),1), round(float(loc.y),1)))
            elif t == "MTEXT" and ln in ("2", "4"):
                texts.append((ln, decode(e.plain_text()), 0, 0))
        print(f"  layer2 POINT({len(layer2_pts)}): {layer2_pts[:8]}")
        print(f"  layer4 POINT({len(layer4_pts)}): {layer4_pts[:8]}")
        print(f"  layer2/4 TEXT({len(texts)}):")
        for ln, txt, x, y in texts[:20]:
            print(f"    [{ln}] {txt!r}  @({x},{y})")

if __name__ == "__main__":
    main()
