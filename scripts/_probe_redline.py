"""Probe: locate the long border line(s) near the fabric selvage in PLT markers.

Compares production PLT (ET output) vs project-exported PLT:
  - header PS / SP pen usage
  - global bbox
  - long horizontal lines (constant y = gate-direction edges, appear as long
    VERTICAL lines in the rotated production view)
  - long vertical lines (constant x = length-direction edges, appear as long
    HORIZONTAL lines in the rotated production view)
  - census of all polylines whose min-y < 20mm (what lives at the selvage)

Usage: py -3.11 scripts/_probe_redline.py <file.plt> [...]
All output ASCII. Coordinates in mm (40 HPGL units = 1mm).
"""
from __future__ import annotations

import re
import sys
from collections import Counter

U = 40.0  # HPGL plotter units per mm


def parse_plt(path):
    raw = open(path, 'rb').read().decode('ascii', 'replace')
    polys = []            # list of (pen, pts_units)
    sp_counter = Counter()
    ps_val = None
    cur = None            # {'pen':.., 'pts':[..]}
    pos = None
    pen = '1'

    def flush():
        nonlocal cur
        if cur is not None and len(cur['pts']) >= 2:
            polys.append((cur['pen'], cur['pts']))
        cur = None

    for tok in raw.split(';'):
        t = tok.strip()
        if not t:
            continue
        m = re.match(r'^([A-Z]{2})(.*)$', t, re.S)
        if not m:
            continue
        op, rest = m.group(1), m.group(2)
        nums = [int(v) for v in re.findall(r'-?\d+', rest)]
        if op == 'SP':
            flush()
            pen = rest.strip() or '0'
            sp_counter[pen] += 1
            continue
        if op == 'PS':
            flush()
            if nums:
                ps_val = nums[0]
            continue
        if op in ('PU', 'PD', 'PA'):
            pts = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
            if not pts:
                if op == 'PU':
                    flush()
                continue
            if op == 'PU':
                flush()
                pos = pts[-1]
            else:
                if cur is None:
                    cur = {'pen': pen, 'pts': [pos] if pos is not None else []}
                cur['pts'].extend(pts)
                pos = pts[-1]
        else:
            flush()
    flush()
    return polys, sp_counter, ps_val


def cluster(lines):
    """lines: (coord_mm, a_mm, b_mm, len_mm, pen) -> merged rows."""
    cl = {}
    for c, a, b, L, pen in lines:
        cl.setdefault(round(c), []).append((a, b, L, pen))
    out = []
    for k in sorted(cl):
        segs = cl[k]
        tot = sum(s[2] for s in segs)
        a = min(s[0] for s in segs)
        b = max(s[1] for s in segs)
        out.append((k, len(segs), tot, a, b, sorted({s[3] for s in segs})))
    return out


def analyze(path):
    polys, spc, ps_val = parse_plt(path)
    print('=' * 78)
    print('FILE:', path.split('/')[-1])
    print('SP pen usage:', dict(spc), '| PS(paper len units):', ps_val,
          f'({ps_val / U:.0f}mm)' if ps_val else '')
    xs = [p[0] for _pen, pts in polys for p in pts]
    ys = [p[1] for _pen, pts in polys for p in pts]
    print(f'polys={len(polys)}  bbox mm: x[{min(xs) / U:.1f},{max(xs) / U:.1f}] '
          f'y[{min(ys) / U:.1f},{max(ys) / U:.1f}]')

    horiz, vert = [], []
    for pen, pts in polys:
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if abs(y1 - y0) <= 20 and abs(x1 - x0) >= 8000:      # 0.5mm, 200mm
                horiz.append(((y0 + y1) / 2 / U, min(x0, x1) / U,
                              max(x0, x1) / U, abs(x1 - x0) / U, pen))
            if abs(x1 - x0) <= 20 and abs(y1 - y0) >= 8000:
                vert.append(((x0 + x1) / 2 / U, min(y0, y1) / U,
                             max(y0, y1) / U, abs(y1 - y0) / U, pen))
    print('-- long lines const-y (gate edges; vertical in production view):')
    for k, n, tot, a, b, pens in cluster(horiz):
        print(f'   y={k:>5}mm  n={n:<3} totlen={tot:>7.0f}mm  x[{a:.0f},{b:.0f}]  pens={pens}')
    print('-- long lines const-x (length edges; horizontal in production view):')
    for k, n, tot, a, b, pens in cluster(vert):
        print(f'   x={k:>5}mm  n={n:<3} totlen={tot:>7.0f}mm  y[{a:.0f},{b:.0f}]  pens={pens}')

    print('-- polylines with min-y < 25mm (selvage-zone census, first 45 by min-y):')
    rows = []
    for pen, pts in polys:
        py = [p[1] for p in pts]
        px = [p[0] for p in pts]
        if min(py) / U < 25:
            rows.append((min(py) / U, min(px) / U, max(px) / U, len(pts),
                         (max(py) - min(py)) / U, (max(px) - min(px)) / U, pen))
    rows.sort()
    for r in rows[:45]:
        print(f'   ymin={r[0]:7.2f}  x[{r[1]:7.1f},{r[2]:7.1f}] w={r[5]:6.1f} '
              f'h={r[4]:6.1f} pts={r[3]:<4} pen={r[6]}')
    print(f'   ... total {len(rows)} polys reach below y=25mm')
    # min-y histogram in 1mm bins for all polys
    hist = Counter(int(r[0]) for r in
                   ((min(p[1] for p in pts) / U,) for _pen, pts in polys))
    lo = min(hist)
    print('-- poly min-y histogram (1mm bins, lowest 12):',
          {k: hist[k] for k in range(lo, lo + 12)})


for f in sys.argv[1:]:
    analyze(f)
