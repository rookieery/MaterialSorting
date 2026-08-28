# -*- coding: utf-8 -*-
"""腰头成带 ±3° 旋转自由度 A/B 实验（版师建议 2026-08-24：给腰头 3° 自由旋转让带内更贴合）。

数据：真实 5336 母版 intermediate（web_race_c199d7 run 目录，生产同源母版）。
配置：data/configs/5336_coded_really.json 的 g05 段（d=0.4, tol=3；14 副本 7 码）。

对照（只换 `_chain_nest` 候选生成 / 事后整带微倾，其余生产逻辑不变）：
  V0 基线      : grain 锁 {0,180} × 5 种 bbox y 对齐（现行生产逻辑）
  V1 ±3°离散   : discretize(3) 14 角 × 5 种 y 对齐（第一轮：零变化 —— y 对齐太粗）
  V3 ±3°连续dy : 14 角 × 连续 dy（粗扫 20mm + top3 细化 2mm），cost=bbox 面积
  V4 ±3°连续dy : 同 V3 但 cost=宽度优先（带高预算富余 1270/1910（旧口径）、带宽才是主解成本）
  V0t 整带微倾 : V0 构造后整带统一旋转 θ∈[-3°,3°] 0.25° 步取最小 union bbox
                 （相对角度不变 ⇒ 无斜缝；各成员世界角 ≤3° 在 tol 内）

用法：
  .venv/Scripts/python.exe scripts/exp_band_rot.py              # band 级 A/B + SVG
  .venv/Scripts/python.exe scripts/exp_band_rot.py --solve 180  # 追加主解 A/B
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
sys.path.insert(0, str(ROOT / 'materialSorting-server' / 'src'))

from materialsorting.nesting_engine import waist_band as wb  # noqa: E402
from materialsorting.nesting_engine.constraints import discretize_orientations  # noqa: E402
from materialsorting.nesting_engine.sparrow_baseline import _clean_polygon  # noqa: E402
from materialsorting.nesting_engine.waist_band import (  # noqa: E402
    _bbox_area, _chain_gap, _flip_chain, _geom_at, _member_sort_key,
    _norm_chain, _slide_touch, _y_align_off, _valid_geometry,
    build_band_plan, CHAIN_Y_ALIGNS)
from materialsorting.web.solver import build_pid_meta  # noqa: E402

INTERMEDIATE = (ROOT / 'materialSorting-server/out/config_runs/'
                'web_race_c199d7_20260822-211724/pieces_intermediate.json')
OUT_DIR = ROOT / 'materialSorting-server/out/band_rot_exp'
LABEL = 'g05'
D_G, TOL_G = 0.4, 3.0
GATE = 1980.0
LOG_LINES = []


def log(msg):
    print(msg, flush=True)
    LOG_LINES.append(msg)


# --------------------------------------------------------------- 链构造变体

def nest_aligned(member_pids, polys, rots):
    """生产 `_chain_nest` 逻辑（rots 泛化）：每 rot × 5 种 bbox y 对齐 → 滑移贴靠
    → 取合并 bbox 面积增长最小。"""
    packed = None
    placed = []
    for pid in member_pids:
        cands = []
        for r in rots:
            g0 = sh_rotate(_valid_geometry(polys[pid]), r, origin=(0, 0))
            if packed is None:
                gb = g0.bounds
                cands.append(((gb[2] - gb[0]) * (gb[3] - gb[1]), g0,
                              {'pid': pid, 'rotation': r,
                               'translation': [-gb[0], -gb[1]]}))
                continue
            pb = packed.bounds
            for y_align in CHAIN_Y_ALIGNS:
                yo = _y_align_off(y_align, pb, g0.bounds)
                g, dx = _slide_touch(g0, packed, yo)
                b = g.bounds
                cands.append((_bbox_area(pb, b), g,
                              {'pid': pid, 'rotation': r,
                               'translation': [dx, yo]}))
        best = min(cands, key=lambda c: c[0])
        placed.append(best[2])
        g = _geom_at(polys[pid], best[2]['rotation'], best[2]['translation'])
        packed = g if packed is None else unary_union([packed, g])
    return placed


def nest_continuous(member_pids, polys, rots, cost_mode='area',
                    dy_coarse=20.0, dy_fine=2.0, refine_top=3):
    """连续 dy 版：每 rot 在 bbox 竖向重叠区间粗扫 dy（每点滑移贴靠）→ cost 排序
    → top-K (rot,dy) 邻域 2mm 细扫。cost: 'area'=bbox 面积；'width'=(宽, 面积)。"""
    packed = None
    placed = []
    for pid in member_pids:
        g0s = [(r, sh_rotate(_valid_geometry(polys[pid]), r, origin=(0, 0)))
               for r in rots]
        gmap = dict(g0s)
        if packed is None:
            _, g0, meta = min(
                (((g.bounds[2] - g.bounds[0]) * (g.bounds[3] - g.bounds[1]),
                  g, {'pid': pid, 'rotation': r,
                      'translation': [-g.bounds[0], -g.bounds[1]]})
                 for r, g in g0s), key=lambda t: t[0])
            placed.append(meta)
            packed = _geom_at(polys[pid], meta['rotation'], meta['translation'])
            continue
        pb = packed.bounds

        def cost_at(r, yo):
            gb = gmap[r].bounds
            if yo + gb[3] < pb[1] or yo + gb[1] > pb[3]:
                return None                      # bbox 竖向无重叠，跳过
            _, dx = _slide_touch(gmap[r], packed, yo)
            b = (gb[0] + dx, gb[1] + yo, gb[2] + dx, gb[3] + yo)
            if cost_mode == 'width':
                return (max(pb[2], b[2]) - min(pb[0], b[0]),
                        _bbox_area(pb, b))
            return _bbox_area(pb, b)

        cands = []
        for r in rots:
            gb = gmap[r].bounds
            y_lo, y_hi = pb[1] - gb[3], pb[3] - gb[1]
            n = max(1, int(math.ceil((y_hi - y_lo) / dy_coarse)))
            for i in range(n + 1):
                yo = y_lo + (y_hi - y_lo) * i / n
                c = cost_at(r, yo)
                if c is not None:
                    cands.append((c, r, yo))
        cands.sort(key=lambda t: t[0])
        best = None
        for _c, r, yo in cands[:refine_top]:
            for k in range(int(2 * dy_coarse / dy_fine) + 1):
                dyf = yo - dy_coarse + dy_fine * k
                c = cost_at(r, dyf)
                if c is not None and (best is None or c < best[0]):
                    best = (c, r, dyf)
        if best is None:
            r, g0 = g0s[0]
            yo = pb[1] - g0.bounds[3]
            best = (float('inf'), r, yo)
        _, r, yo = best
        g, dx = _slide_touch(gmap[r], packed, yo)
        meta = {'pid': pid, 'rotation': r, 'translation': [dx, yo]}
        placed.append(meta)
        packed = unary_union(
            [packed, _geom_at(polys[pid], r, [dx, yo])])
    return placed


def tilt_members(placed, polys, max_deg=3.0, step=0.25):
    """整带统一旋转 θ∈[-max,max]（绕原点），取 union bbox 面积最小的 θ。
    相对角度不变（无斜缝），各成员世界角增量 ≤3°（tol 内）。"""
    best = None
    n = int(max_deg / step)
    for k in range(-n, n + 1):
        th = k * step
        u = unary_union([
            _geom_at(polys[m['pid']], (m['rotation'] + th) % 360.0,
                     _rot2(m['translation'], th)) for m in placed])
        b = u.bounds
        a = (b[2] - b[0]) * (b[3] - b[1])
        if best is None or a < best[0]:
            best = (a, th, b)
    return best[1], best[2]


def _rot2(p, deg):
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    return [p[0] * c - p[1] * s, p[0] * s + p[1] * c]


# --------------------------------------------------------------- 复刻/度量

def build_chains(pid_meta, polys, nest_fn):
    """复刻 build_band_plan 的分链 + 降序 + 翻转归一（与生产同序，供逐链度量）。"""
    member_pids = sorted(
        (pid for pid, m in pid_meta.items()
         if m.get('label') == LABEL and int(m.get('demand', 0)) > 0),
        key=lambda pid: _member_sort_key(pid_meta[pid], pid))
    max_demand = max(int(pid_meta[pid]['demand']) for pid in member_pids)
    chains = []
    for k in range(max_demand):
        chain_pids = sorted(
            (pid for pid in member_pids if int(pid_meta[pid]['demand']) > k),
            key=lambda pid: _member_sort_key(pid_meta[pid], pid), reverse=True)
        chains.append(
            _norm_chain(_flip_chain(nest_fn(chain_pids, polys)), polys))
    return chains


def chain_metrics(chain, pid_meta, polys):
    u = unary_union([_geom_at(polys[m['pid']], m['rotation'],
                              m['translation']) for m in chain])
    minx, miny, maxx, maxy = u.bounds
    area = sum(float(pid_meta[m['pid']]['area_mm2']) for m in chain)
    bbox_area = (maxx - minx) * (maxy - miny)
    return {'n': len(chain), 'width': maxx - minx, 'height': maxy - miny,
            'fill_pct': area / bbox_area * 100.0,
            'gap_mm': _chain_gap(chain, polys),
            'rotations': sorted({round(float(m['rotation']), 2)
                                 for m in chain})}


def render_svg(records, polys, path):
    pad, sy = 20.0, 0.3
    blocks, y_cursor = [], pad
    for rec in records:
        gs = [_geom_at(polys[m['pid']], m['rotation'], m['translation'])
              for ch in rec['chains'] for m in ch]
        x0 = min(g.bounds[0] for g in gs)
        top = max(g.bounds[3] for g in gs)
        bot = min(g.bounds[1] for g in gs)
        blocks.append((rec, gs, x0, top, bot, y_cursor))
        y_cursor += (top - bot) * sy + 56
    total_w = max((max(g.bounds[2] for g in b[1]) - b[2]) * sy
                  for b in blocks) + 2 * pad
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" '
           f'height="{y_cursor + pad:.0f}"><rect width="100%" height="100%" '
           f'fill="#14141c"/>']
    for rec, gs, x0, top, bot, y0 in blocks:
        extra = rec.get('note', '')
        out.append(
            f'<text x="{pad}" y="{y0 + 15:.0f}" fill="#fff" font-size="15" '
            f'font-family="monospace">{rec["name"]}   bbox '
            f'{rec["bbox"]["width_mm"]:.0f}x{rec["bbox"]["height_mm"]:.0f}mm'
            f'   fill {rec["fill_pct"]:.1f}%  {extra}</text>')
        for g in gs:
            pts = ' '.join(
                f'{pad + (x - x0) * sy:.1f},{y0 + 28 + (top - y) * sy:.1f}'
                for x, y in g.exterior.coords)
            out.append(f'<polygon points="{pts}" stroke="#1b1b22" '
                       f'stroke-width="0.5" fill="#7ec8e3" '
                       f'fill-opacity="0.9"/>')
    out.append('</svg>')
    Path(path).write_text('\n'.join(out), encoding='utf-8')


# --------------------------------------------------------------- 主流程

def make_specs(rots3):
    return [
        ('V0  基线{0,180}x5对齐',
         lambda: (lambda pids, ps: nest_aligned(pids, ps, [0.0, 180.0]))),
        ('V1  ±3°x5对齐',
         lambda: (lambda pids, ps: nest_aligned(pids, ps, rots3))),
        ('V3  ±3°连续dy 面积',
         lambda: (lambda pids, ps: nest_continuous(pids, ps, rots3, 'area'))),
        ('V4  ±3°连续dy 宽优先',
         lambda: (lambda pids, ps: nest_continuous(pids, ps, rots3, 'width'))),
    ]


def build_band_plan_call(pid_meta, pieces_by_id):
    return build_band_plan(
        pid_meta, pieces_by_id, label=LABEL, seed=0,
        gate_nest=GATE, d_g=D_G, tol_g=TOL_G)


def run_band_ab():
    doc = json.loads(INTERMEDIATE.read_text(encoding='utf-8'))
    pieces = doc['pieces']
    cfg = json.loads((ROOT / 'data/configs/5336_coded_really.json')
                     .read_text(encoding='utf-8'))
    pid_meta, total_area, _n = build_pid_meta(
        pieces, sizes=cfg['sizes'], per_type=cfg['per_type'],
        quantities=cfg['quantities'])
    g05 = {pid: m for pid, m in pid_meta.items() if m['label'] == LABEL}
    n_copies = sum(m['demand'] for m in g05.values())
    assert n_copies == 14, f'g05 副本数异常: {n_copies}'
    polys = {pid: _clean_polygon(m['polygon']) for pid, m in g05.items()}
    pieces_by_id = {p['pid']: p for p in pieces}
    rots3 = discretize_orientations(TOL_G)
    log(f'成员 {len(polys)} pid / {n_copies} 副本  旋转候选 {len(rots3)} 角:'
        f' {sorted(rots3)}')

    records, chunks = [], {}
    orig_nest = wb._chain_nest
    try:
        for name, mk in make_specs(rots3):
            t0 = time.time()
            nest_fn = mk()
            wb._chain_nest = nest_fn
            try:
                chunk = build_band_plan_call(pid_meta, pieces_by_id)
            except Exception as e:                     # noqa: BLE001
                log(f'[{name}]  构造失败: {e}')
                continue
            chains = build_chains(pid_meta, polys, nest_fn)
            for k, ch in enumerate(chains):
                cm = chain_metrics(ch, pid_meta, polys)
                log(f'  链{k}: {cm["n"]}片 {cm["width"]:7.1f}x'
                    f'{cm["height"]:6.1f}mm  fill {cm["fill_pct"]:5.1f}%'
                    f'  缝隙 {cm["gap_mm"]:.2f}mm  角集 {cm["rotations"]}')
            rec = {'name': name,
                   'bbox': {'width_mm': chunk.bbox['width_mm'],
                            'height_mm': chunk.bbox['height_mm']},
                   'fill_pct': chunk.fill_pct, 'chains': chains}
            log(f'[{name}]  整带 bbox {rec["bbox"]["width_mm"]:.1f}x'
                f'{rec["bbox"]["height_mm"]:.1f}mm  fill {chunk.fill_pct:.2f}%'
                f'  组合片顶点 {len(chunk.polygon)}  '
                f'构造 {time.time() - t0:.1f}s')
            records.append(rec)
            chunks[name] = chunk
    finally:
        wb._chain_nest = orig_nest

    # V0t：基线整带微倾（post-pass，对堆叠结果 members 统一 θ）
    t0 = time.time()
    base_chunk = chunks['V0  基线{0,180}x5对齐']
    th, b = tilt_members(base_chunk.members, polys)
    w, h = b[2] - b[0], b[3] - b[1]
    fill = sum(float(g05[m['pid']]['area_mm2'])
               for m in base_chunk.members) / (w * h) * 100.0
    tilted = [{'pid': m['pid'],
               'rotation': (m['rotation'] + th) % 360.0,
               'translation': _rot2(m['translation'], th)}
              for m in base_chunk.members]
    records.append({'name': 'V0t 基线+整带微倾',
                    'bbox': {'width_mm': w, 'height_mm': h},
                    'fill_pct': fill, 'chains': [tilted],
                    'note': f'theta={th:+.2f}deg'})
    log(f'[V0t 基线+整带微倾]  θ*={th:+.2f}°  整带 bbox {w:.1f}x{h:.1f}mm'
        f'  fill {fill:.2f}%  ({time.time() - t0:.1f}s)')

    base = records[0]
    log('\n==== 对比（vs V0）====')
    for rec in records[1:]:
        dw = rec['bbox']['width_mm'] - base['bbox']['width_mm']
        dh = rec['bbox']['height_mm'] - base['bbox']['height_mm']
        df = rec['fill_pct'] - base['fill_pct']
        log(f'{rec["name"]}: 带宽 {dw:+7.1f}mm '
            f'({dw / base["bbox"]["width_mm"] * 100:+6.2f}%)  '
            f'带高 {dh:+7.1f}mm  fill {df:+5.2f}pt')

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    render_svg(records, polys, OUT_DIR / 'band_rot_compare.svg')
    (OUT_DIR / 'band_rot_results.json').write_text(json.dumps(
        [{'name': r['name'], 'bbox': r['bbox'], 'fill_pct': r['fill_pct'],
          'note': r.get('note', '')} for r in records],
        ensure_ascii=False, indent=2), encoding='utf-8')
    log(f'SVG: {OUT_DIR / "band_rot_compare.svg"}')
    return records, chunks, pieces, cfg, total_area


def run_solve_ab(records, chunks, pieces, cfg, total_area, budget):
    from materialsorting.web.solver import build_instance, solve_with_callback
    strip = GATE

    def one_run(name, chunk):
        inst, conf, _pm, ta, _ne = build_instance(
            pieces, GATE, time_budget=budget, seed=0, sizes=cfg['sizes'],
            per_type=cfg['per_type'], quantities=cfg['quantities'],
            exclude_labels=[LABEL],
            extra_items=[{'id': chunk.pid, 'polygon': chunk.polygon,
                          'demand': 1, 'orientations': [0.0, 180.0]}])
        best = float('inf')

        def on_report(rep):
            nonlocal best
            best = min(best, float(rep['width_mm']))

        sol, elapsed, err = solve_with_callback(inst, conf, on_report)
        if err:
            raise RuntimeError(err)
        if sol is not None:
            best = min(best, float(sol.width))
        real = ta / (best * strip)
        log(f'{name}: width {best:.1f}mm  real_density {real * 100:.2f}%'
            f'  ({elapsed:.0f}s)')
        return {'density_pct': real * 100, 'width_mm': best}

    log(f'\n==== 主解 A/B（seed=0 同 {budget}s，分母幅宽 {strip:.0f}mm）====')
    out = {}
    for rec in records:
        if rec['name'] in chunks:
            out[rec['name']] = one_run(rec['name'], chunks[rec['name']])
    (OUT_DIR / 'band_rot_solve.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    budget = 0
    if '--solve' in sys.argv:
        budget = int(sys.argv[sys.argv.index('--solve') + 1])
    _records, _chunks, _pieces, _cfg, _ta = run_band_ab()
    if budget:
        run_solve_ab(_records, _chunks, _pieces, _cfg, _ta, budget)
    (OUT_DIR / 'band_rot_log.txt').write_text(
        '\n'.join(LOG_LINES), encoding='utf-8')
