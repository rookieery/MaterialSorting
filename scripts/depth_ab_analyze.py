# -*- coding: utf-8 -*-
"""quadtree_depth A/B 分析器：同 seed 配对差 + 门判别力（race 兼容性）。

用法：
    python scripts/depth_ab_analyze.py

臂定义（全部 p0.70/et0/600s/workers4，仅 depth 差异）：
    d4（对照）= pctgrid_t600_p070_et0* 既有 run 中 seeds 0-9（quadtree_depth 缺省=4）；
    d3 / d5  = pctgrid_t600_d3_* / pctgrid_t600_d5_*。

观测量：
    - 每 seed real_density（原面积口径，result.json）→ 同 seed 配对差 vs d4；
    - 门判别力 Spearman(门值@300s, 终值)：门值 = 可行 incumbent 在 t≤300s 的最大密度
      （复用 pctgrid_analyze 的不可行帧过滤方法论：density > 终值 best 的帧必为不可行）。
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pctgrid_analyze import EPS  # noqa: E402  不可行帧过滤口径单一真相源

RUNS_ROOT = os.path.join(os.path.dirname(__file__), '..', 'materialSorting-server', 'out', 'config_runs')
GATE_T = 300.0  # race 门位置（τ=0.5 × 600s）


def load_arm(pattern, want_depth=None, seeds=None):
    """读一个臂：{(seed): (real_density, curve)}。want_depth=None → 键缺席（=4）。"""
    out = {}
    for run_dir in sorted(glob.glob(os.path.join(RUNS_ROOT, pattern + '_*'))):
        rp = os.path.join(run_dir, 'result.json')
        if not os.path.exists(rp):
            continue
        r = json.load(open(rp, encoding='utf-8'))
        for s in r['solve']:
            if seeds is not None and s['seed'] not in seeds:
                continue
            o = s['solver_opts']
            if abs(o.get('exploration_pct', 0.8) - 0.7) > 1e-9 or o.get('early_termination') is not False:
                continue
            if o.get('quadtree_depth', 4) != want_depth:
                continue
            cp = os.path.join(run_dir, f"curve_s{s['seed']}.json")
            curve = json.load(open(cp, encoding='utf-8')) if os.path.exists(cp) else []
            out[s['seed']] = (s['real_density'] * 100, curve)
    return out


def gate_value(curve, best):
    """可行 incumbent 在 t≤GATE_T 的最大密度（不可行帧过滤后）。"""
    feas = [f for f in curve if f['density'] <= best / 100 + EPS]
    vals = [f['density'] for f in feas if f['elapsed'] <= GATE_T]
    return max(vals, default=None)


def spearman(xs, ys):
    """Spearman 秩相关（无 scipy 依赖）。"""
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den > 0 else float('nan')


def arm_stats(name, arm):
    dens = {s: v[0] for s, v in arm.items()}
    if not dens:
        print(f'{name}: 无数据')
        return None
    gates = {s: gate_value(c, b) for s, (b, c) in arm.items()}
    ok = [(gates[s], dens[s]) for s in sorted(dens) if gates[s] is not None]
    rho = spearman([g for g, _ in ok], [d for _, d in ok]) if len(ok) >= 3 else float('nan')
    print(f'{name}: n={len(dens)} mean={sum(dens.values())/len(dens):.3f} '
          f'best={max(dens.values()):.3f} gate_rho={rho:.3f} (n_gate={len(ok)})')
    return dens


def main():
    s0_9 = set(range(10))
    d4 = load_arm('pctgrid_t600_*', want_depth=4, seeds=s0_9)
    d3 = load_arm('pctgrid_t600_d3', want_depth=3)
    d5 = load_arm('pctgrid_t600_d5', want_depth=5)

    print(f'{"臂":>4} 统计（门判别力 = Spearman(可行incumbent@300s, 终值)）')
    dens = {n: arm_stats(n, a) for n, a in (('d4', d4), ('d3', d3), ('d5', d5))}

    if dens.get('d4'):
        for name in ('d3', 'd5'):
            if not dens.get(name):
                continue
            print(f'\n配对差（pt，同 seed，vs d4）：{name}')
            for s in sorted(set(dens['d4']) & set(dens[name])):
                print(f'  s{s}: {dens[name][s]:.3f} vs {dens["d4"][s]:.3f} → {dens[name][s]-dens["d4"][s]:+.3f}')
            common = sorted(set(dens['d4']) & set(dens[name]))
            diffs = [dens[name][s] - dens['d4'][s] for s in common]
            if diffs:
                same = len({d > 0 for d in diffs}) == 1
                print(f'  mean {sum(diffs)/len(diffs):+.3f}'
                      f'{"  [全同向]" if same and len(diffs) > 1 else ""}')


if __name__ == '__main__':
    main()
