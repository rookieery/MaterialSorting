# -*- coding: utf-8 -*-
"""腰头成带旋转探针（补充实验，2026-08-24）。

主实验（exp_band_rot.py）结论：±3° 世界角在面积/宽度贪心与整带微倾下均零收益。
本脚本补三个假设的定向探针，全部用真实 5336 g05 数据：

  A 成对旋转扫描 : 真实相邻码对（锚 180°）动片 r∈[172..188]∪[-8..8] 0.5° 步
                   × 连续 dy（15mm 粗 + 1mm 细），逐 r 记录合并 bbox 最小面积/宽。
                   ⇒ 局部几何定论：旋转对成对贴合是否有利、最优相对角多少。
  B 链间微倾搜索 : 三链各自 θ∈{-3..3}°（343 组合）倾斜后重新 _stack_chains
                   堆叠，取整带 union bbox 最小。⇒ 链间相对角是否有收益。
  C 递进扇形诊断 : 版师图样式 —— 每片相对前片递进 δ（世界角不设限，纯诊断），
                   δ∈{0,±2,±4,±6,±8}°，连续 dy 贴靠，量链 bbox 面积/宽。
                   ⇒ 版师 5-8° 扇形在本几何上是否真的更紧。
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

from shapely.affinity import rotate as sh_rotate
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'materialSorting-server' / 'src'))

from exp_band_rot import (  # noqa: E402
    GATE, INTERMEDIATE, LABEL, LOG_LINES, OUT_DIR, build_chains, log,
    nest_aligned, _rot2)
from materialsorting.nesting_engine import waist_band as wb  # noqa: E402
from materialsorting.nesting_engine.sparrow_baseline import _clean_polygon  # noqa: E402
from materialsorting.nesting_engine.waist_band import (  # noqa: E402
    _bbox_area, _geom_at, _member_sort_key, _slide_touch, _valid_geometry)
from materialsorting.web.solver import build_pid_meta  # noqa: E402


def load():
    doc = json.loads(INTERMEDIATE.read_text(encoding='utf-8'))
    pieces = doc['pieces']
    cfg = json.loads((ROOT / 'data/configs/5336_coded_really.json')
                     .read_text(encoding='utf-8'))
    pid_meta, _ta, _n = build_pid_meta(
        pieces, sizes=cfg['sizes'], per_type=cfg['per_type'],
        quantities=cfg['quantities'])
    g05 = {pid: m for pid, m in pid_meta.items() if m['label'] == LABEL}
    polys = {pid: _clean_polygon(m['polygon']) for pid, m in g05.items()}
    return pid_meta, g05, polys


def pair_best(g_anchor, g_move0, r, dy_coarse=15.0, dy_fine=1.0, refine_top=3):
    """动片转到 r 后，连续 dy 滑移贴靠，返回 (min_area, min_width, dy*)。"""
    g0 = sh_rotate(g_move0, r, origin=(0, 0), use_radians=False)
    gb, pb = g0.bounds, g_anchor.bounds
    y_lo, y_hi = pb[1] - gb[3], pb[3] - gb[1]
    n = max(1, int(math.ceil((y_hi - y_lo) / dy_coarse)))

    def cost_at(yo):
        if yo + gb[3] < pb[1] or yo + gb[1] > pb[3]:
            return None
        _, dx = _slide_touch(g0, g_anchor, yo)
        b = (gb[0] + dx, gb[1] + yo, gb[2] + dx, gb[3] + yo)
        return _bbox_area(pb, b), max(pb[2], b[2]) - min(pb[0], b[0])

    cands = []
    for i in range(n + 1):
        c = cost_at(y_lo + (y_hi - y_lo) * i / n)
        if c is not None:
            cands.append((c[0], c[1], y_lo + (y_hi - y_lo) * i / n))
    cands.sort(key=lambda t: t[0])
    best = None
    for _a, _w, yo in cands[:refine_top]:
        for k in range(int(2 * dy_coarse / dy_fine) + 1):
            c = cost_at(yo - dy_coarse + dy_fine * k)
            if c is not None and (best is None or c[0] < best[0]):
                best = (c[0], c[1], yo - dy_coarse + dy_fine * k)
    return best


def probe_a(g05, polys):
    log('\n======== 探针 A：成对旋转扫描（真实相邻码对）========')
    chain0 = build_chains(_PM, polys, lambda pids, ps: nest_aligned(
        pids, ps, [0.0, 180.0]))[0]
    order = [m['pid'] for m in chain0]          # 降序放置序（翻转前升序记录）
    sizes = {pid: g05[pid]['size'] for pid in g05}
    log(f'链0 放置序: {[(p.split("_")[-1]) for p in order]}')
    rots = [180 + d for d in range(-8, 9)] + [0 + d for d in range(-8, 9)]
    rots = sorted({round(r % 360, 1) for r in rots})
    for a_pid, m_pid in zip(order, order[1:]):
        anchor = _geom_at(polys[a_pid], 180.0,
                          [0.0, 0.0]) if False else sh_rotate(
            _valid_geometry(polys[a_pid]), 180.0, origin=(0, 0))
        anchor = anchor  # 锚定 180°
        t0 = time.time()
        curve = []
        for r in rots:
            b = pair_best(anchor, _valid_geometry(polys[m_pid]), r)
            if b:
                curve.append((r, b[0], b[1]))
        base = min((c for c in curve if abs(c[0] - 180.0) < 1e-6),
                   default=None)
        bmin = min(curve, key=lambda c: c[1])
        wmin = min(curve, key=lambda c: c[2])
        log(f'对 {a_pid.split("_")[-1]}→{m_pid.split("_")[-1]}: '
            f'r=180° 面积 {base[1]:.0f} 宽 {base[2]:.1f} | '
            f'最小面积 r={bmin[0]:.1f}° {bmin[1]:.0f} ({(bmin[1] - base[1]) / base[1] * 100:+.2f}%) | '
            f'最小宽 r={wmin[0]:.1f}° {wmin[2]:.1f} ({(wmin[2] - base[2]) / base[2] * 100:+.2f}%)'
            f'  ({time.time() - t0:.0f}s)')
    (OUT_DIR / 'probe_a.txt').write_text('\n'.join(LOG_LINES),
                                         encoding='utf-8')


def probe_b(polys):
    log('\n======== 探针 B：链间微倾暴力搜索（各链 θ∈[-3,3]°，重堆叠）========')
    chains = build_chains(_PM, polys, lambda pids, ps: nest_aligned(
        pids, ps, [0.0, 180.0]))
    areas = {pid: float(m['area_mm2']) for pid, m in _G05.items()}

    def tilt_chain(ch, th):
        return [{'pid': m['pid'],
                 'rotation': (m['rotation'] + th) % 360.0,
                 'translation': _rot2(m['translation'], th)} for m in ch]

    def band_metrics(placed):
        u = unary_union([_geom_at(polys[m['pid']], m['rotation'],
                                  m['translation']) for m in placed])
        b = u.bounds
        return ((b[2] - b[0]) * (b[3] - b[1]), b[2] - b[0], b[3] - b[1],
                sum(areas[m['pid']] for m in placed)
                / ((b[2] - b[0]) * (b[3] - b[1])) * 100.0)

    base_m = band_metrics(wb._stack_chains(chains, polys))
    log(f'基线（全 θ=0）: bbox {base_m[1]:.1f}x{base_m[2]:.1f}mm '
        f'fill {base_m[3]:.2f}%')
    best = None
    thetas = [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0]
    t0 = time.time()
    for t0_ in thetas:
        for t1 in thetas:
            for t2 in thetas:
                tc = [tilt_chain(chains[0], t0_), tilt_chain(chains[1], t1),
                      tilt_chain(chains[2], t2)]
                m = band_metrics(wb._stack_chains(tc, polys))
                if best is None or m[0] < best[0][0]:
                    best = (m, (t0_, t1, t2))
    m, (bt0, bt1, bt2) = best
    log(f'最优 θ=({bt0:+.0f},{bt1:+.0f},{bt2:+.0f})°: bbox {m[1]:.1f}x'
        f'{m[2]:.1f}mm fill {m[3]:.2f}%  | Δ面积 {(m[0] - base_m[0]) / base_m[0] * 100:+.2f}%'
        f'  Δfill {m[3] - base_m[3]:+.2f}pt  ({time.time() - t0:.0f}s, 343 组合)')


def probe_c(polys):
    log('\n======== 探针 C：递进扇形（版师图样式，世界角不设限，纯诊断）========')
    chains = build_chains(_PM, polys, lambda pids, ps: nest_aligned(
        pids, ps, [0.0, 180.0]))
    order = [m['pid'] for m in chains[0]]        # 降序
    areas = {pid: float(m['area_mm2']) for pid, m in _G05.items()}

    def fan_chain(delta, base_rot=180.0):
        packed = None
        placed = []
        for k, pid in enumerate(order):
            r = (base_rot + delta * k) % 360.0
            g0 = sh_rotate(_valid_geometry(polys[pid]), r, origin=(0, 0))
            if packed is None:
                gb = g0.bounds
                meta = {'pid': pid, 'rotation': r,
                        'translation': [-gb[0], -gb[1]]}
                packed = _geom_at(polys[pid], r, meta['translation'])
            else:
                pb = packed.bounds
                bb = pair_best(packed, _valid_geometry(polys[pid]), r,
                               dy_coarse=15.0, dy_fine=2.0)
                yo = bb[2]
                _, dx = _slide_touch(g0, packed, yo)
                meta = {'pid': pid, 'rotation': r, 'translation': [dx, yo]}
                packed = unary_union(
                    [packed, _geom_at(polys[pid], r, [dx, yo])])
            placed.append(meta)
        u = unary_union([_geom_at(polys[m['pid']], m['rotation'],
                                  m['translation']) for m in placed])
        b = u.bounds
        fill = sum(areas[m['pid']] for m in placed) \
            / ((b[2] - b[0]) * (b[3] - b[1])) * 100.0
        return {'width': b[2] - b[0], 'height': b[3] - b[1],
                'area': (b[2] - b[0]) * (b[3] - b[1]), 'fill': fill,
                'end_deg': (delta * (len(order) - 1))}

    base = fan_chain(0.0)
    log(f'δ=0（均匀 180°，即生产基线）: 宽 {base["width"]:.1f} 高 '
        f'{base["height"]:.1f} 链bbox面积 {base["area"]:.0f} fill {base["fill"]:.2f}%')
    for d in (2.0, -2.0, 4.0, -4.0, 6.0, -6.0, 8.0, -8.0):
        m = fan_chain(d)
        log(f'δ={d:+.0f}° (末片世界角 {d * 6:+.0f}°): 宽 {m["width"]:7.1f} '
            f'({(m["width"] - base["width"]) / base["width"] * 100:+6.2f}%)  '
            f'高 {m["height"]:7.1f}  bbox面积 {(m["area"] - base["area"]) / base["area"] * 100:+6.2f}%'
            f'  fill {m["fill"]:.2f}%')


_PM, _G05, _POLYS = None, None, None

if __name__ == '__main__':
    _PM, _G05, _POLYS = load()
    which = sys.argv[1] if len(sys.argv) > 1 else 'abc'
    if 'a' in which:
        probe_a(_G05, _POLYS)
    if 'b' in which:
        probe_b(_POLYS)
    if 'c' in which:
        probe_c(_POLYS)
    (OUT_DIR / 'probe_log.txt').write_text('\n'.join(LOG_LINES),
                                           encoding='utf-8')
