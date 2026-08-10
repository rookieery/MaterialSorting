# -*- coding: utf-8 -*-
"""渲染 腰-30 block，把 layer 2/4 的 POINT 旁边标上它们的 TEXT 编号(#N)，
让版师直观判断这些点是什么。用完即删。
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
    for block in doc.blocks:
        if decode(block.name) != "腰-30":
            continue
        outline, net, grain = [], [], None
        l2, l4 = [], []  # (x,y,label)
        for e in block:
            t = e.dxftype()
            ln = str(e.dxf.layer)
            if t == "POLYLINE" and ln == "1":
                outline.append([(float(v.dxf.location.x), float(v.dxf.location.y)) for v in e.vertices])
            elif t == "POLYLINE" and ln == "14":
                net.append([(float(v.dxf.location.x), float(v.dxf.location.y)) for v in e.vertices])
            elif t == "LINE" and ln == "7":
                grain = (float(e.dxf.start.x), float(e.dxf.start.y), float(e.dxf.end.x), float(e.dxf.end.y))
        # 先收 POINT，再收 TEXT 并按最近邻配对
        pts2, pts4 = [], []
        for e in block:
            if e.dxftype() != "POINT": continue
            ln = str(e.dxf.layer); loc = e.dxf.location
            (pts2 if ln == "2" else pts4 if ln == "4" else None).append((float(loc.x), float(loc.y))) if ln in ("2","4") else None
        txts = {2: [], 4: []}
        for e in block:
            if e.dxftype() != "TEXT": continue
            ln = str(e.dxf.layer)
            if ln not in ("2", "4"): continue
            loc = e.dxf.insert
            txts[int(ln)].append((decode(e.dxf.text), float(loc.x), float(loc.y)))
        # 给每个 POINT 找最近 TEXT
        def match(pts, labels):
            out = []
            used = set()
            for px, py in pts:
                best, bi = None, -1
                for i, (lab, tx, ty) in enumerate(labels):
                    if i in used: continue
                    d = (px-tx)**2 + (py-ty)**2
                    if best is None or d < best: best, bi = d, i
                if bi >= 0:
                    out.append((px, py, labels[bi][0])); used.add(bi)
                else:
                    out.append((px, py, "?"))
            return out
        l2 = match(pts2, txts[2])
        l4 = match(pts4, txts[4])

        # bbox
        allp = [pt for poly in outline for pt in poly] + [pt for poly in net for pt in poly] + pts2 + pts4
        if grain: allp += [(grain[0],grain[1]),(grain[2],grain[3])]
        minx, miny = min(x for x,_ in allp), min(y for _,y in allp)
        maxx, maxy = max(x for x,_ in allp), max(y for _,y in allp)
        W, H, pad = 1000, 500, 70
        dx, dy = (maxx-minx) or 1, (maxy-miny) or 1
        sc = min((W-2*pad)/dx, (H-2*pad)/dy)
        ox = pad - minx*sc + ((W-2*pad)-dx*sc)/2
        oy = pad + maxy*sc + ((H-2*pad)-dy*sc)/2
        def tx(x,y): return (ox+x*sc, oy-y*sc)

        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="sans-serif">',
               '<rect width="100%" height="100%" fill="#111"/>',
               '<text x="16" y="26" fill="#fff" font-size="16">腰-30 · layer2(青 编号) + layer4(黄 编号) 参考点</text>',
               '<text x="16" y="46" fill="#9be" font-size="12">蓝=毛版轮廓 绿虚=净版 红虚=布纹线</text>']
        # outline
        for poly in outline:
            pp = [tx(x,y) for x,y in poly]
            d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x,y in pp) + " Z"
            out.append(f'<path d="{d}" fill="rgba(74,158,255,0.08)" stroke="#4a9eff" stroke-width="2.2"/>')
        for poly in net:
            pp = [tx(x,y) for x,y in poly]
            d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x,y in pp) + " Z"
            out.append(f'<path d="{d}" fill="none" stroke="#39d353" stroke-width="1.8" stroke-dasharray="7 4"/>')
        if grain:
            out.append(f'<line x1="{tx(grain[0],grain[1])[0]:.1f}" y1="{tx(grain[0],grain[1])[1]:.1f}" x2="{tx(grain[2],grain[3])[0]:.1f}" y2="{tx(grain[2],grain[3])[1]:.1f}" stroke="#ff5454" stroke-width="2" stroke-dasharray="8 4"/>')
        # layer 4 点(黄) 先画在下层
        for x,y,lab in l4:
            sx,sy = tx(x,y)
            out.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="4.5" fill="#ffeb3b"/>')
            out.append(f'<text x="{sx+7:.1f}" y="{sy+4:.1f}" fill="#ffeb3b" font-size="11">{lab}</text>')
        # layer 2 点(青)
        for x,y,lab in l2:
            sx,sy = tx(x,y)
            out.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="4" fill="#00e5ff"/>')
            out.append(f'<text x="{sx-6:.1f}" y="{sy-7:.1f}" fill="#00e5ff" font-size="11" text-anchor="end">{lab}</text>')
        out.append('</svg>')
        outdir = Path(__file__).resolve().parents[1] / "scripts" / "preview"; outdir.mkdir(exist_ok=True)
        (outdir / "labeled_waist30.svg").write_text("\n".join(out), encoding="utf-8")
        print("写出 _inspect_preview/labeled_waist30.svg")
        print(f"layer2 点={len(l2)} layer4 点={len(l4)}")

if __name__ == "__main__":
    main()
