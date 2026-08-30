# -*- coding: utf-8 -*-
"""极限运行三臂 A/B 离线回放器（US-004 验收前置）：同总预算 4h 对拍
extreme（race 门杀 × 极限参数）vs race 默认档 vs 均分 600s×24。

用法：
    python scripts/extreme_ab_replay.py [--trials 20000] [--time-total 14400]

曲线库 = 既有 25-seed 池（pctgrid_t600 p0.70/et0，600s 实测曲线，加载口径复用
scripts/depth_ab_analyze.py 的 load_arm/gate_value：result.json real_density 为
该 seed 全程最优可行解、density > 终值的帧必为不可行帧 → 剔除后取 t 截点的
可行 incumbent 最大值）。race 回放语义逐字复用 US-001 decide_race_kill：
首 seed 豁免、bar 含被杀者单调只升、门值 g <= bar 即杀（严格破纪录才续跑）、
每 seed 至多一笔；名义记账复用 cli.portfolio.race_plan 口径（首 602.5s 全程 +
门段 302.5s / race 默认档 182.5s + 92.5s，含 2.5s 启动开销，import 单一真相源）。

三臂（T = 14400s 总预算）：
    extreme      race@600s 门 300s × p070/et0（池原生参数，即 --extreme 展开档）；
    race_default race@180s 门 90s（现行高级运行默认档，曲线截到 180s）；
    split24      均分 600s × 24 seeds 无门杀（曲线取全程终值）。

bootstrap：池内**不放回**抽样（distinct seed 语义，与方案 §2.5 E[max] 曲线同
口径 —— 真实 run 种子流无重复）；池耗尽后重洗续抽（race 臂 4h 需 43~151 轮 >
池 25 条的唯一口径，E[best] 有界 = 池最大值，n>25 的右尾不外推）。固定种子
20260829 可复现。
副表（真实参数敏感性）：race_default / split24 换 p0.80/et1 5-seed 池回放
（端到端两臂的真实求解参数），extreme 臂无副表（池即其原生参数）。
锚点行：extreme 臂对池内 seed 0-24 按序确定性回放（真实 run 的前 25 轮
恰为种子流 0..24，与池一一对应，零抽样方差）。

输出：stdout 三表 + 机器可读 out/config_runs/_probes/extreme_ab_replay.json。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pctgrid_analyze import EPS  # noqa: E402  不可行帧过滤口径单一真相源

# 名义记账与规划 = cli.portfolio 单一真相源（race_plan），防止回放口径与生产
# 控制器漂移（race_plan 返回 (计划种子数上限, 门时刻秒)）。
_SERVER_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'materialSorting-server', 'src')
sys.path.insert(0, _SERVER_SRC)
from materialsorting.cli.portfolio import race_plan  # noqa: E402

RUNS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '..', 'materialSorting-server', 'out', 'config_runs')
OUT_JSON = os.path.join(RUNS_ROOT, '_probes', 'extreme_ab_replay.json')
RNG_SEED = 20260829          # bootstrap 固定种子（可复现）
BOOTSTRAP_TRIALS = 20000

# 25-seed 极限参数池（--extreme 原生曲线）：p0.70/et0/600s/workers4/depth4。
EXTREME_POOL_PATTERNS = ('pctgrid_t600_p070_et0', 'pctgrid_t600_p070et0s5_14',
                         'pctgrid_t600_p070et0s15_24')
# 现行默认参数池（race 默认档 / 均分臂的真实求解参数）：p0.80/et1/600s。
DEFAULT_POOL_PATTERNS = ('pctgrid_t600_p080',)


def load_pool(patterns, want_pct, want_et) -> dict[int, tuple[float, list]]:
    """读一个曲线池：{seed: (real_density_pt, curve)}（口径 = depth_ab_analyze.load_arm）。

    want_et=True → early_termination 键缺席（= 现行默认 True）；quadtree_depth
    键缺席 = 4（池全部为缺省 depth，方案 §2.6 定论）。曲线缺失的 seed 跳过。
    """
    out: dict[int, tuple[float, list]] = {}
    for pattern in patterns:
        for run_dir in sorted(glob.glob(os.path.join(RUNS_ROOT, pattern + '_*'))):
            rp = os.path.join(run_dir, 'result.json')
            if not os.path.exists(rp):
                continue
            r = json.load(open(rp, encoding='utf-8'))
            for s in r['solve']:
                o = s['solver_opts']
                if abs(o.get('exploration_pct', 0.8) - want_pct) > 1e-9:
                    continue
                if o.get('early_termination', True) is not want_et:
                    continue
                cp = os.path.join(run_dir, f"curve_s{s['seed']}.json")
                curve = json.load(open(cp, encoding='utf-8')) if os.path.exists(cp) else []
                out[s['seed']] = (s['real_density'] * 100, curve)
    return out


def feasible_at(curve: list, t_cap: float, final_pt: float) -> float | None:
    """t <= t_cap 内可行 incumbent 最大密度（depth_ab_analyze.gate_value 口径）。

    不可行帧过滤器：density > 该 seed 全程 real_density 的帧必为不可行（final 是
    全程最优可行解），剔除后取截点内最大值；截点内无帧返回 None。
    """
    feas = [f['density'] for f in curve
            if f['density'] * 100 <= final_pt + EPS and f['elapsed'] <= t_cap]
    return max(feas) * 100 if feas else None


def curve_caps(pool_items, caps) -> list[list[float]]:
    """预计算每条曲线在各截点的可行 incumbent 值（bootstrap 热路径去 O(帧数)）。

    截点集固定（门 / 预算 / 全程），bootstrap 只查表不扫帧 —— 20000 次 × 百轮
    的回放从小时级降到秒级；值口径与 feasible_at 逐点一致（None → 0.0 兜底，
    池内曲线均在门时刻前有帧，兜底实际不触发）。
    """
    table = []
    for _final_pt, curve in pool_items:
        table.append([feasible_at(curve, cap, _final_pt) or 0.0 for cap in caps])
    return table


def _draw_deck(values, deck, rng):
    """池内不放回抽一条（distinct seed 语义）；池耗尽重洗一次再抽。

    n <= 池大小时 = 超几何抽样（与方案 §2.5 E[max] 曲线同口径：真实 run 的种子
    流无重复）；n > 池大小（race 臂 4h 需 43~151 轮 > 25）后续轮只能重抽 ——
    permutation bootstrap 口径，右尾有界 = 池最大值（不外推，报告口径声明）。
    """
    if not deck:
        deck.extend(values)
        rng.shuffle(deck)
    return deck.pop(rng.randrange(len(deck)))


def race_replay_trial(values, total_budget, budget, gate_tau, rng):
    """单次 race 回放（bootstrap 一次）：(best_pt, n_tried, n_kept, n_gated, spent)。

    ``values`` = curve_caps 产物，每元素 [门值, 预算值]。语义对齐
    PortfolioController race 模式：启动前复核 spent + 门段 <= T（can_start_next）；
    首 seed 豁免跑满；其余 seed 门值 g 与 bar（历史门值 max，含被杀者）比较 ——
    g <= bar 即杀（记门段、交付 g），严格破纪录续跑满（记全程、交付预算截点内
    可行最优）；bar 每门帧后只升。
    """
    _n_planned, gate = race_plan(total_budget, budget, gate_tau)
    full_unit = budget + 2.5
    gate_unit = gate + 2.5
    spent, bar, best = 0.0, None, -1.0
    n = kept = gated = 0
    deck: list = []
    while spent + gate_unit <= total_budget + 1e-9:
        g, run_v = _draw_deck(values, deck, rng)
        n += 1
        killed = n > 1 and bar is not None and g <= bar
        if killed:
            gated += 1
            spent += gate_unit
            best = max(best, g)
        else:
            kept += 1
            spent += full_unit
            best = max(best, run_v)
        bar = g if bar is None or g > bar else bar
    return best, n, kept, gated, spent


def split_replay_trial(values, n_seeds, rng):
    """单次均分回放：n_seeds 条曲线各跑满预算（无门杀），best = 终值 max。"""
    deck: list = []
    vals = [_draw_deck(values, deck, rng)[0] for _ in range(n_seeds)]
    return max(vals), n_seeds, n_seeds, 0, 0.0


def race_replay_ordered(pool: dict, total_budget, budget, gate_tau):
    """确定性按序回放（无 bootstrap）：种子流 = strategy_seed_stream(cfg.seeds=[0])。

    池内 seed 按真实种子流顺序消费（0,1,2,...），池耗尽即止 —— 真实 run 的
    前 len(pool) 轮零抽样方差预测；返回 (best, 逐轮事件, 名义记账累计)。
    """
    _n_planned, gate = race_plan(total_budget, budget, gate_tau)
    full_unit, gate_unit = budget + 2.5, gate + 2.5
    spent, bar, best = 0.0, None, -1.0
    events = []
    for i, seed in enumerate(sorted(pool), start=1):
        if spent + gate_unit > total_budget + 1e-9:
            break
        final_pt, curve = pool[seed]
        g = feasible_at(curve, gate, final_pt)
        run_v = feasible_at(curve, budget, final_pt)
        if run_v is None:
            run_v = 0.0
        if g is None:
            g = run_v
        killed = i > 1 and bar is not None and g <= bar
        events.append({'round': i, 'seed': seed, 'gate_pt': round(g, 3),
                       'killed': killed})
        if killed:
            spent += gate_unit
            best = max(best, g)
        else:
            spent += full_unit
            best = max(best, run_v)
        bar = g if bar is None or g > bar else bar
    return best, events, spent


def arm_stats(name, trials):
    """trials = [(best, n, kept, gated), ...] → 汇总 dict + 一行打印。"""
    bests = [t[0] for t in trials]
    n = len(bests)
    e = sum(bests) / n
    p905 = sum(1 for b in bests if b >= 90.5) / n
    p910 = sum(1 for b in bests if b >= 91.0) / n
    p915 = sum(1 for b in bests if b >= 91.5) / n
    e_tried = sum(t[1] for t in trials) / n
    e_kept = sum(t[2] for t in trials) / n
    e_gated = sum(t[3] for t in trials) / n
    print(f'  {name:<14} E[best]={e:6.3f}  best={max(bests):.3f}  '
          f'P(>=90.5)={p905:.3f}  P(>=91.0)={p910:.3f}  P(>=91.5)={p915:.3f}  '
          f'E[轮数]={e_tried:5.1f}（留 {e_kept:4.1f} / 杀 {e_gated:4.1f}）')
    return {'name': name, 'E_best': round(e, 3), 'best': round(max(bests), 3),
            'P_ge_90_5': round(p905, 4), 'P_ge_91_0': round(p910, 4),
            'P_ge_91_5': round(p915, 4), 'E_rounds': round(e_tried, 1),
            'E_kept': round(e_kept, 1), 'E_gated': round(e_gated, 1)}


def main():
    ap = argparse.ArgumentParser(description='极限运行三臂 A/B 离线回放（US-004）')
    ap.add_argument('--trials', type=int, default=BOOTSTRAP_TRIALS)
    ap.add_argument('--time-total', type=int, default=14400)
    args = ap.parse_args()
    T = float(args.time_total)

    p25 = load_pool(EXTREME_POOL_PATTERNS, 0.7, False)
    p5d = load_pool(DEFAULT_POOL_PATTERNS, 0.8, True)
    if len(p25) != 25:
        raise SystemExit(f'25-seed 池不完整：读到 {len(p25)} 条（期望 25）')
    if len(p5d) != 5:
        raise SystemExit(f'默认参数池不完整：读到 {len(p5d)} 条（期望 5）')
    print(f'曲线库：极限参数池 {len(p25)} seeds（p0.70/et0/600s，best '
          f'{max(v[0] for v in p25.values()):.3f}pt）| '
          f'默认参数池 {len(p5d)} seeds（p0.80/et1/600s，best '
          f'{max(v[0] for v in p5d.values()):.3f}pt）')
    print(f'总预算 T={T:g}s | race_plan：extreme {race_plan(T, 600, 0.5)}（计划数, 门s）'
          f' | race 默认 {race_plan(T, 180, 0.5)}')

    items25 = [p25[s] for s in sorted(p25)]
    items5d = [p5d[s] for s in sorted(p5d)]
    # 各臂截点集（秒）：race 两臂 = 门 + 预算；均分臂 = 全程。
    _, gate300 = race_plan(T, 600, 0.5)
    _, gate90 = race_plan(T, 180, 0.5)
    v25_extreme = curve_caps(items25, [gate300, 600.0])
    v25_race = curve_caps(items25, [gate90, 180.0])
    v25_split = curve_caps(items25, [1e9])
    v5d_race = curve_caps(items5d, [gate90, 180.0])
    v5d_split = curve_caps(items5d, [1e9])

    print(f'\n主表（共同曲线库 = 25-seed p0.70/et0 池；bootstrap {args.trials} 次，'
          f'种子 {RNG_SEED}；三臂同曲线库隔离「策略」效应）')
    rows_main = []
    rng = random.Random(RNG_SEED)
    rows_main.append(arm_stats('extreme', [
        race_replay_trial(v25_extreme, T, 600, 0.5, rng)[:4] for _ in range(args.trials)]))
    rng = random.Random(RNG_SEED)
    rows_main.append(arm_stats('race_default', [
        race_replay_trial(v25_race, T, 180, 0.5, rng)[:4] for _ in range(args.trials)]))
    rng = random.Random(RNG_SEED)
    rows_main.append(arm_stats('split24', [
        split_replay_trial(v25_split, 24, rng)[:4] for _ in range(args.trials)]))

    print('\n副表（真实参数敏感性：race_default / split24 换 p0.80/et1 5-seed 池；'
          'extreme 无副表 = 池即原生参数）')
    rows_sens = []
    rng = random.Random(RNG_SEED)
    rows_sens.append(arm_stats('race_default', [
        race_replay_trial(v5d_race, T, 180, 0.5, rng)[:4] for _ in range(args.trials)]))
    rng = random.Random(RNG_SEED)
    rows_sens.append(arm_stats('split24', [
        split_replay_trial(v5d_split, 24, rng)[:4] for _ in range(args.trials)]))

    best25, events25, spent25 = race_replay_ordered(p25, T, 600, 0.5)
    print(f'\n锚点（extreme 臂确定性按序回放：种子流 0..{max(sorted(p25))} 与真实 run '
          f'前 {len(events25)} 轮一一对应，零抽样方差）')
    print(f'  前 {len(events25)} 轮交付 best = {best25:.3f}pt，名义记账 '
          f'{spent25:.1f}s / {T:g}s（剩余预算由池外新 seed 25+ 继续吸收，'
          f'bootstrap 有界不外推）')
    print(f'  门杀 {sum(1 for e in events25 if e["killed"])}/{len(events25)} 轮；'
          f'存活轮序号：{[e["round"] for e in events25 if not e["killed"]]}')

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    payload = {
        'generated_at': __import__('time').strftime('%Y-%m-%dT%H:%M:%S'),
        'time_total_s': int(T), 'trials': args.trials, 'rng_seed': RNG_SEED,
        'pool_extreme': {'n': len(p25), 'seeds': sorted(p25),
                         'finals_pt': {str(s): round(p25[s][0], 3) for s in sorted(p25)}},
        'pool_default': {'n': len(p5d), 'seeds': sorted(p5d),
                         'finals_pt': {str(s): round(p5d[s][0], 3) for s in sorted(p5d)}},
        'main_table': rows_main, 'sensitivity_table': rows_sens,
        'anchor_ordered': {'rounds': len(events25), 'best_pt': round(best25, 3),
                           'spent_nominal_s': round(spent25, 1), 'events': events25},
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'\n机器可读全量 -> {os.path.abspath(OUT_JSON)}')


if __name__ == '__main__':
    main()
