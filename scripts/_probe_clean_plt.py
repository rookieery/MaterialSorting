"""Probe: deep-dive the 毛版 (clean, 当日由「净版」更名) production PLT reference.

Segments polylines into 3 regions: left table (x<24), marker body (24..4943),
right table (x>4943). For tables: per-band stroke census (key vs value band),
text cluster heights, baseline direction hints. For marker body: census of
short strokes (labels), boundary nubs (notches), long inner lines.

Usage: py -3.11 scripts/_probe_clean_plt.py <file.plt>
Coordinates in mm (40 units = 1mm).
"""
from __future__ import annotations

import re
import sys
from collections import Counter

sys.path.insert(0, 'scripts')
from _probe_redline import parse_plt  # noqa: E402

U = 40.0

path = sys.argv[1]
polys, spc, ps_val = parse_plt(path)

regions = {'left_table': [], 'body': [], 'right_table': []}
for pen, pts in polys:
    xm = sum(p[0] for p in pts) / len(pts) / U
    key = 'left_table' if xm < 24 else ('right_table' if xm > 4943 else 'body')
    regions[key].append((pen, pts))

print('region counts:', {k: len(v) for k, v in regions.items()})

# ---- tables: per-band stroke census ----
for name, x_lo, x_hi in (('left', 0.0, 24.0), ('right', 4943.0, 4967.1)):
    band_a, band_b = [], []   # a = inner 12mm (closer marker), b = outer 12mm
    mid = (x_lo + x_hi) / 2
    for pen, pts in regions[f'{name}_table']:
        for p in pts:
            pass
        cx = sum(p[0] for p in pts) / len(pts) / U
        (band_a if cx < mid else band_b).append((pen, pts))
    def _census(tag, lst):
        ys = [p[1] / U for _pen, pts in lst for p in pts]
        xs = [p[0] / U for _pen, pts in lst for p in pts]
        dy = [max(p[1] for p in pts) / U - min(p[1] for p in pts) / U
              for _pen, pts in lst]
        dx = [max(p[0] for p in pts) / U - min(p[0] for p in pts) / U
              for _pen, pts in lst]
        if not ys:
            print(f'  {name} {tag}: EMPTY')
            return
        print(f'  {name} {tag}: n={len(lst)} y[{min(ys):.0f},{max(ys):.0f}] '
              f'x[{min(xs):.1f},{max(xs):.1f}] '
              f'stroke-extent dx med={sorted(dx)[len(dx)//2]:.1f} '
              f'dy med={sorted(dy)[len(dy)//2]:.1f} '
              f'(dy>dx means char reads along +y)')
    _census('inner-band(closer marker)', band_a)
    _census('outer-band', band_b)

# ---- body: classify content ----
body = regions['body']
long_lines, tiny, small_polys = [], [], []
for pen, pts in body:
    xs = [p[0] / U for p in pts]
    ys = [p[1] / U for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if max(w, h) >= 200:
        long_lines.append((w, h, min(xs), min(ys), len(pts)))
    elif max(w, h) <= 40:
        tiny.append((w, h, min(xs), min(ys), len(pts)))
    else:
        small_polys.append((w, h, min(xs), min(ys), len(pts)))
print(f'\nbody polys={len(body)}: big(>=200mm)={len(long_lines)} '
      f'tiny(<=40mm)={len(tiny)} mid={len(small_polys)}')
print(' big ones (w,h,x,y,pts):')
for row in sorted(long_lines, key=lambda r: -max(r[0], r[1]))[:8]:
    print('   ', tuple(round(v, 1) for v in row))
print(' tiny stroke extent histogram (dx,dy) top:',
      Counter((round(w / 5) * 5, round(h / 5) * 5) for w, h, *_ in tiny)
      .most_common(8))

# ---- label clusters: group tiny strokes by proximity, print a few with extents
def cluster_tiny(tiny, gap=45.0):
    pts_all = []
    for i, (w, h, x, y, n) in enumerate(tiny):
        pts_all.append((x + w / 2, y + h / 2, i))
    used = [False] * len(tiny)
    clusters = []
    for i in range(len(tiny)):
        if used[i]:
            continue
        stack, comp = [i], []
        used[i] = True
        while stack:
            j = stack.pop()
            comp.append(j)
            cx, cy = tiny[j][2] + tiny[j][0] / 2, tiny[j][3] + tiny[j][1] / 2
            for k, (kx, ky, _i) in enumerate(pts_all):
                if not used[k] and abs(kx - cx) < gap and abs(ky - cy) < gap:
                    used[k] = True
                    stack.append(k)
        clusters.append(comp)
    return clusters

clusters = cluster_tiny(tiny)
labeled = [c for c in clusters if len(c) >= 2]
print(f'\nlabel-like clusters (>=2 tiny strokes): {len(labeled)}')
for c in labeled[:12]:
    xs = [tiny[j][2] for j in c] + [tiny[j][2] + tiny[j][0] for j in c]
    ys = [tiny[j][3] for j in c] + [tiny[j][3] + tiny[j][1] for j in c]
    print(f'   x[{min(xs):7.1f},{max(xs):7.1f}] y[{min(ys):7.1f},{max(ys):7.1f}]'
          f'  w={max(xs)-min(xs):5.1f} h={max(ys)-min(ys):5.1f} strokes={len(c)}')
