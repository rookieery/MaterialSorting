# -*- coding: utf-8 -*-
"""exploration_pct 网格实验分析器（Phase 1/2 判读单一真相源）。

用法：
    python scripts/pctgrid_analyze.py [glob 模式（默认 pctgrid_t600_p*）]

输入：out/config_runs/<name>_<时间戳>/ 下的 result.json + curve_s{seed}.json。
输出：stdout 汇总表 + out/config_runs/pctgrid_summary.csv（追加）。

方法论（Phase 0 核验结论）：
- 主判据 = result.solve[i].real_density（原面积口径，per-seed final 可行最优）；
- curve 的 phase 字段 ≠ 时间阶段：压缩段仍会发 ExplImproving（"exploring"）帧。
  切换点取首帧 compressing 的 elapsed（无则回退 pct*T+3.5s，3.4s 为实测固定启动偏移）；
- density > 该 seed real_density 的帧必为不可行帧（best 是全程最优可行解）→ 剔除；
- 可行 incumbent 轨迹 = 密度 ≤ best 的帧序列，其严格增长点即改进事件。
"""
from __future__ import annotations

import csv
import glob
import json
import os
import sys
from collections import defaultdict

RUNS_ROOT = os.path.join(os.path.dirname(__file__), '..', 'materialSorting-server', 'out', 'config_runs')
EPS = 1e-9
GROW_EPS = 1e-6  # 可行密度严格增长的判定步长


def seed_curve_metrics(curve: list[dict], best: float, T: float, pct: float) -> dict:
    """单 seed 曲线的相位观测量。"""
    if not curve:
        return {}
    cmpr_ts = [f['elapsed'] for f in curve if f['phase'] == 'compressing']
    t_switch = cmpr_ts[0] if cmpr_ts else pct * T + 3.5
    feas = [f for f in curve if f['density'] <= best + EPS]
    n_infeas = len(curve) - len(feas)
    # 可行 incumbent 严格增长事件（改进事件）
    events = []
    cur = -1.0
    for f in feas:
        if f['density'] > cur + GROW_EPS:
            events.append((f['elapsed'], f['density']))
            cur = f['density']
    t_sat = events[-1][0] if events else 0.0
    # 切换点处的可行密度与压缩段增益
    feas_at_switch = [f['density'] for f in feas if f['elapsed'] <= t_switch]
    d_at_switch = max(feas_at_switch, default=0.0)
    final = max(f['density'] for f in feas) if feas else 0.0
    # 探索末窗口（切换点前 10%）改进事件数：探索未饱和信号
    n_events_late_expl = sum(1 for t, _ in events if 0.9 * t_switch <= t <= t_switch)
    # 压缩段末 10% 窗口 CmprFeas：压缩饥饿信号（离结束仍近距成功）
    t_end = curve[-1]['elapsed']
    last_cmpr = cmpr_ts[-1] if cmpr_ts else None
    return {
        't_switch': round(t_switch, 1),
        'n_infeas_frames': n_infeas,
        'n_events': len(events),
        't_sat': round(t_sat, 1),
        't_sat_over_T': round(t_sat / T, 3),
        'cmpr_gain_pt': round((final - d_at_switch) * 100, 3),
        'n_cmpr': len(cmpr_ts),
        'last_cmpr_gap_s': round(t_end - last_cmpr, 1) if last_cmpr else None,
        'n_events_late_expl': n_events_late_expl,
        'final_density': round(final, 5),
    }


def main(pattern: str = 'pctgrid_t600_p*') -> None:
    rows = []
    for run_dir in sorted(glob.glob(os.path.join(RUNS_ROOT, pattern + '_*'))):
        rp = os.path.join(run_dir, 'result.json')
        if not os.path.exists(rp):
            continue
        r = json.load(open(rp, encoding='utf-8'))
        T = r['config']['time']
        for s in r['solve']:
            pct = s['solver_opts'].get('exploration_pct', 0.8)
            et = s['solver_opts'].get('early_termination', True)
            et_label = 'et0' if et is False else 'et1'
            cp = os.path.join(run_dir, f"curve_s{s['seed']}.json")
            curve = json.load(open(cp, encoding='utf-8')) if os.path.exists(cp) else []
            m = seed_curve_metrics(curve, s['real_density'], T, pct)
            rows.append({'run': os.path.basename(run_dir), 'pct': pct, 'et': et_label,
                         'seed': s['seed'],
                         'real_density_pt': round(s['real_density'] * 100, 3),
                         'width_mm': round(s['width_mm'], 1), **m})

    if not rows:
        print(f'no runs match: {pattern}')
        return

    # ---- 档位汇总（pct × early_termination 双键分组） ----
    by_key = defaultdict(list)
    for row in rows:
        by_key[(row['pct'], row['et'])].append(row)
    print(f'{"pct":>5} {"et":>4} {"n":>2} {"mean_pt":>8} {"best_pt":>8} {"range_pt":>8} '
          f'{"t_sat/T":>7} {"cmpr_gain":>9} {"n_cmpr":>6} {"late_expl":>9}')
    for (pct, et) in sorted(by_key):
        g = by_key[(pct, et)]
        dens = [x['real_density_pt'] for x in g]
        mean = sum(dens) / len(dens)
        print(f'{pct:>5} {et:>4} {len(g):>2} {mean:>8.3f} {max(dens):>8.3f} '
              f'{max(dens)-min(dens):>8.3f} '
              f'{sum(x["t_sat_over_T"] for x in g)/len(g):>7.3f} '
              f'{sum(x["cmpr_gain_pt"] for x in g)/len(g):>9.3f} '
              f'{sum(x["n_cmpr"] for x in g)/len(g):>6.1f} '
              f'{sum(x["n_events_late_expl"] for x in g)/len(g):>9.1f}')

    # ---- 配对差 vs 基线档（每档与最高档均值的对照组两两配对：以 0.8/et1 为基线） ----
    base = {x['seed']: x['real_density_pt'] for x in by_key.get((0.8, 'et1'), [])}
    if base:
        print('\n配对差 (pt, 同 seed，负 = 劣于 p0.80/et1)：')
        for (pct, et) in sorted(by_key):
            if (pct, et) == (0.8, 'et1'):
                continue
            diffs = [(x['seed'], x['real_density_pt'] - base[x['seed']])
                     for x in by_key[(pct, et)] if x['seed'] in base]
            if diffs:
                txt = '  '.join(f's{s}:{d:+.3f}' for s, d in diffs)
                same_sign = len({d > 0 for _, d in diffs}) == 1
                print(f'  p{pct:.2f}/{et} vs p0.80/et1: {txt}'
                      f'  | mean {sum(d for _, d in diffs)/len(diffs):+.3f}'
                      f'{"  [全同向]" if same_sign and len(diffs) > 1 else ""}')

    # ---- 明细 + CSV ----
    print('\n明细：')
    for row in rows:
        print(f'  {row["run"]} seed={row["seed"]} pct={row["pct"]} '
              f'dens={row["real_density_pt"]:.3f}pt t_switch={row.get("t_switch")} '
              f't_sat/T={row.get("t_sat_over_T")} cmpr_gain={row.get("cmpr_gain_pt")}pt '
              f'n_cmpr={row.get("n_cmpr")} n_infeas={row.get("n_infeas_frames")}')
    out_csv = os.path.join(RUNS_ROOT, 'pctgrid_summary.csv')
    new = not os.path.exists(out_csv)
    with open(out_csv, 'a', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f'\nCSV -> {os.path.abspath(out_csv)}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'pctgrid_t600_p*')
