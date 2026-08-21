# -*- coding: utf-8 -*-
"""US-015 v1.1 填料混带 A/B 验收探针（产物只落 out/config_runs/_probes/）。

口径与 web/band_accept.py（US-014）同构：5336 uploads 源、web 默认 params 全 0
（g05 d=0.0）、无 kill、P0 需求表（accept_quantities）、ACCEPT_SIZES 码表；
差异仅在 on 臂 band 配置带 ``fillers``（混带）。判据（tasks/prd-waist-band.md
US-015 AC#3）：
  1. 带区域效率：on 臂 stage fill_pct（带板 bbox 内腰+填料面积/占用，build_band_plan
     同口径直出）>= break-even 参考线 62.4%；
  2. 全局劣化：off vs on(fillers) x seed {0,1,2} 的 real_density 均值劣化 <=1.0pt；
  3. 守恒/泄漏：final placed_items 无 WB_，成员 pid 按 demand 出现 N 次（腰+填料）。

用法：py -3.11 scripts/us015_band_ab.py [--intermediate PATH] [--fillers g07,g08]
       [--seeds 0,1,2] [--time 120] [--quick]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'materialSorting-server' / 'src'))

from materialsorting.web.band_accept import (  # noqa: E402
    ACCEPT_SIZES, accept_quantities, load_accept_pieces, run_arm, web_default_params)
from materialsorting import paths  # noqa: E402

BREAK_EVEN_PCT = 62.4          # US-010 闸门实测混带/纯腰分界线下沿（单一真相源同值）
DENSITY_ACCEPT_PT = 1.0        # 全局劣化验收线（US-014 同值）


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--intermediate', default=None)
    ap.add_argument('--fillers', default='g07')
    ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('--time', type=int, default=120)
    ap.add_argument('--band-time', type=int, default=None)
    ap.add_argument('--quick', action='store_true', help='秒级冒烟（结论无意义）')
    args = ap.parse_args(argv)

    if args.quick:
        seeds, main_t = [0], 6
    else:
        seeds = [int(s) for s in args.seeds.split(',')]
        main_t = int(args.time)
    fillers = [f.strip() for f in args.fillers.split(',') if f.strip()]

    default_int = ROOT / 'materialSorting-server' / 'out' / 'config_runs'
    import glob
    cands = sorted(glob.glob(str(default_int / 'us015_probe_*' / 'pieces_intermediate.json')))
    inter = Path(args.intermediate) if args.intermediate else Path(cands[-1])
    _doc, pieces, gate_mm, pieces_by_id = load_accept_pieces(str(inter))
    print(f'intermediate={inter}')
    print(f'fillers={fillers} seeds={seeds} main={main_t}s')

    qty = accept_quantities()
    params = web_default_params()
    band_cfg = {'label': 'g05', 'fillers': fillers}
    if args.band_time:
        band_cfg['time_budget'] = int(args.band_time)

    rows = []
    off_vals, on_vals = [], []
    for seed in seeds:
        sp = {'time_budget': main_t, 'seed': seed, 'sizes': list(ACCEPT_SIZES),
              'params': dict(params), 'per_type': None, 'quantities': qty}
        off = run_arm(pieces, gate_mm, sp, band=None)
        on = run_arm(pieces, gate_mm, sp, band=dict(band_cfg))
        if not off['ok'] or not on['ok']:
            print(f'seed {seed}: off_ok={off["ok"]} on_ok={on["ok"]} '
                  f'err={off["error"] or on["error"]}')
            continue
        off_d = float(off['final']['density']) * 100.0
        on_d = float(on['final']['density']) * 100.0
        stage = on['stage'] or {}
        fill = stage.get('fill_pct')
        # 守恒：final 末帧 placed_items 计数 vs P0 需求
        last = on['frames'][-1] if on['frames'] else None
        counts = {}
        for pi in (last or {}).get('placed_items', []):
            counts[pi['id']] = counts.get(pi['id'], 0) + 1
        expect = {}
        for p in pieces:
            lbl = p.get('label')
            sk = 'null' if p.get('size') is None else str(p.get('size'))
            if int(p.get('size') or 0) in ACCEPT_SIZES or p.get('size') in ACCEPT_SIZES:
                d = qty.get(lbl, {}).get(sk, 1) if lbl in qty else 1
                expect[p['pid']] = d
        n_ok = all(counts.get(k, 0) == v for k, v in expect.items()) and \
            not any(str(k).startswith('WB_') for k in counts)
        rows.append({'seed': seed, 'off_pct': round(off_d, 3), 'on_pct': round(on_d, 3),
                     'deg_pt': round(off_d - on_d, 3),
                     'fill_pct': fill, 'stage_bbox': stage.get('bbox'),
                     'stage_elapsed': stage.get('elapsed'),
                     'n_frames': len(on['frames']),
                     'width_mm': round(float(on['final']['width_mm']), 1),
                     'conservation_ok': bool(n_ok)})
        off_vals.append(off_d)
        on_vals.append(on_d)
        print(f'seed {seed}: off={off_d:.2f}% on={on_d:.2f}% 劣化 {off_d - on_d:+.3f}pt | '
              f'混带 fill={fill}% bbox={stage.get("bbox")} | 守恒 {"OK" if n_ok else "FAIL"}')

    mean_deg = round(statistics.mean(off_vals) - statistics.mean(on_vals), 3) \
        if len(off_vals) == len(on_vals) and off_vals else None
    fills = [r['fill_pct'] for r in rows if r['fill_pct'] is not None]
    fill_pass = bool(fills) and min(fills) >= BREAK_EVEN_PCT
    dens_pass = mean_deg is not None and mean_deg <= DENSITY_ACCEPT_PT
    cons_pass = all(r['conservation_ok'] for r in rows)
    verdict = 'accept' if (fill_pass and dens_pass and cons_pass) else 'reject'
    print(f'均值劣化 {mean_deg}pt -> {"PASS" if dens_pass else "FAIL"}'
          f'（<= {DENSITY_ACCEPT_PT}pt）；混带 fill min={min(fills) if fills else None}% -> '
          f'{"PASS" if fill_pass else "FAIL"}（>= {BREAK_EVEN_PCT}%）；'
          f'守恒 {"PASS" if cons_pass else "FAIL"}；verdict={verdict}')

    out_dir = Path(paths.CONFIG_RUNS_DIR) / '_probes'
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / 'us015_ab_report.json'
    doc = {'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'fillers': fillers,
           'seeds': seeds, 'main_time': main_t, 'rows': rows,
           'mean_deg_pt': mean_deg, 'break_even_pct': BREAK_EVEN_PCT,
           'fill_pass': fill_pass, 'density_pass': dens_pass,
           'conservation_pass': cons_pass, 'verdict': verdict}
    dest.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'report -> {dest}')
    return 0 if verdict == 'accept' else 1


if __name__ == '__main__':
    sys.exit(main())
