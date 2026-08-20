"""US-001 ``cli/portfolio`` 策略双模式判据纯函数 + 配对曲线回放回归。

覆盖两层：

  - **判据单测**（``race_gate_seconds`` / ``strategy_seed_stream`` /
    ``decide_race_kill`` / ``se_plan``）：门帧边界（首帧恰 ``>=`` / ``<``
    gate_seconds）、``<=`` 判杀边界（等于 bar 杀、严格破纪录放行）、首 seed
    豁免、bar 含被杀者门值、门后不再判（每 seed 至多一笔）、种子流补齐与
    无重复、se_plan 算术与预算不足分支、race 同 seed 永不二次续跑（确定性
    重放 + 严格破纪录联合性质）；
  - **回放回归**：``fixtures/strategy_curves_8.json``（8 配对 seed 降采样
    曲线小宇宙，b90s/b180f 跨 fork 结构如实保留）+ 固定 bootstrap seed 重放
    uniform90 / SE / race 三策略 —— T=1200 与 T=3600 两模式 − uniform90
    ≥ +0.1pt、T=3600 漏 max 率 ≤ 5%（漏 max = 交付 < 采样 seed 全程 max
    占比）。回放器在测试内，不依赖 out/ 标定产物。
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting.cli.portfolio import (FULL_UNIT_S, R5_REASON, RACE_BUDGET_S,
                                           RACE_GATE_TAU, SEED_UNIT_S, SE_EXT_S,
                                           SE_SCREEN_S, STRATEGY_STARTUP_S,
                                           StrategyBudgetError, decide_race_kill,
                                           race_gate_seconds, se_plan,
                                           strategy_seed_stream)

_FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'strategy_curves_8.json'
# 固定 bootstrap：重跑同分布（种子序列可复现，回归断言确定性）。
_BOOT_SEED = 20260820
_BOOT_N = 3000
_BOOT_LEN = 48          # 采样序列长度（T=3600 全 kill 口径最多 ~38 轮，留余量）


# -------------------------------------------------------------- 判据单测


def test_constants_and_gate_seconds():
    """常量自洽（名义记账 = 预算 + 启动开销）与门时刻算术。"""
    assert R5_REASON == 'R5_race_gate'
    assert SEED_UNIT_S == SE_SCREEN_S + STRATEGY_STARTUP_S == 92.5
    assert FULL_UNIT_S == SE_EXT_S + STRATEGY_STARTUP_S == 182.5
    assert race_gate_seconds(RACE_BUDGET_S, RACE_GATE_TAU) == 90.0
    assert race_gate_seconds(60, 0.5) == 30.0
    assert race_gate_seconds(180, 0.25) == 45.0


def test_seed_stream_cfg_priority_then_max_plus_one_fill():
    """config seeds 优先消费，不足按 max+1 递增补齐。"""
    assert strategy_seed_stream([5, 3], 5) == [5, 3, 6, 7, 8]
    assert strategy_seed_stream([0], 4) == [0, 1, 2, 3]
    assert strategy_seed_stream([42, 7, 9], 3) == [42, 7, 9]   # 恰好不补


def test_seed_stream_empty_cfg_dedup_and_zero_n():
    """空 config 从 1 起补齐（max(∅)=0 基线约定）；自带重复去重保序；n<=0 空。"""
    assert strategy_seed_stream([], 3) == [1, 2, 3]
    assert strategy_seed_stream(None, 2) == [1, 2]
    assert strategy_seed_stream([7, 7, 2, 7], 4) == [7, 2, 8, 9]
    assert strategy_seed_stream([5, 6], 0) == []


def test_seed_stream_no_duplicates_invariant():
    """无重复不变量：任意 config（含负数 / 稀疏 / 重复）下补齐不撞已选 seed。"""
    for cfg, n in [([-3, 0], 6), ([100, 3, 100], 5), ([], 8), ([1, 2, 3], 1)]:
        stream = strategy_seed_stream(cfg, n)
        assert len(stream) == n
        assert len(set(stream)) == n
        expect_prefix = list(dict.fromkeys(cfg or []))[:n]
        assert stream[:len(expect_prefix)] == expect_prefix


def _race_state(seed=9, index=2, bar=0.86, gate=90.0, budget=180.0,
                incumbent=None, judged=False):
    return {'seed': seed, 'index': index, 'gate_seconds': gate, 'budget': budget,
            'bar': bar, 'incumbent': incumbent, 'judged': judged}


def test_decide_kill_before_gate_frame_is_none():
    """门帧前不判：首帧恰 < gate_seconds 返回 None（门帧 = 首帧 elapsed >= gate）。"""
    st = _race_state()
    assert decide_race_kill(0.80, 0.0, st) is None
    assert decide_race_kill(0.90, 89.999, st) is None
    assert st['judged'] is False            # 未消费「一笔」名额


@pytest.mark.parametrize('elapsed,decision', [(90.0, True), (90.001, True)])
def test_decide_gate_frame_boundary_inclusive(elapsed, decision):
    """首帧恰 >= gate_seconds 即门帧：等于门时刻也判（含边界）。"""
    st = _race_state(bar=0.86)
    row = decide_race_kill(0.8599, elapsed, st)
    assert (row is not None) is decision
    assert row['t'] == round(elapsed, 3)
    assert row['rule'] == R5_REASON and row['would_kill'] is True


def test_decide_equal_to_bar_kills_strict_break_passes():
    """``<=`` 判杀边界：等于 bar 杀、严格破纪录（> bar）放行续跑。"""
    st = _race_state(bar=0.86)
    assert decide_race_kill(0.86, 90.0, st)['would_kill'] is True      # 等于 -> 杀
    st = _race_state(bar=0.86)
    row = decide_race_kill(0.860001, 90.0, st)
    assert row['would_kill'] is False                                  # 破纪录 -> 续跑
    assert st['bar'] == 0.860001                                       # 门值入 bar


def test_decide_first_seed_unconditionally_exempt():
    """首 seed（队列序 1）无条件豁免：即使门值低于 bar 也不杀（有 bar 亦豁免）。"""
    st = _race_state(index=1, bar=0.90)
    row = decide_race_kill(0.80, 90.0, st)
    assert row is not None and row['would_kill'] is False
    assert st['bar'] == 0.90            # 门值 0.80 不抬 bar（max 只升）


def test_decide_no_bar_reference_means_no_kill():
    """bar=None（尚无门值历史，如 seed1 被提前 R0）时不可评估 → 不杀，bar := d。"""
    st = _race_state(index=2, bar=None)
    row = decide_race_kill(0.70, 95.0, st)
    assert row is not None and row['would_kill'] is False
    assert row['S_tau'] is None and st['bar'] == 0.70


def test_decide_bar_includes_killed_seeds_gate_values():
    """bar = 历史所有 seed 门值最大值（含被杀者 / 续跑者门值一并入账）。"""
    st = _race_state(index=2, bar=0.84)
    row = decide_race_kill(0.87, 90.0, st)     # 0.87 > 0.84 破纪录续跑
    assert row['would_kill'] is False and st['bar'] == 0.87
    st2 = _race_state(index=3, bar=0.84)
    assert decide_race_kill(0.83, 90.0, st2)['would_kill'] is True    # 被杀
    assert st2['bar'] == 0.84                  # 被杀门值 <= bar 不改 bar
    # 被杀者门值若为新高：先抬 bar 再判后续 —— 后续 seed 以含被杀者的 bar 为参照。
    st3 = _race_state(index=2, bar=0.80)
    decide_race_kill(0.84, 90.0, st3)          # 0.84 > 0.80 破纪录续跑（不杀）
    st4 = _race_state(index=3, bar=st3['bar'])
    assert decide_race_kill(0.84, 90.0, st4)['would_kill'] is True    # 等于含前者的 bar -> 杀


def test_decide_at_most_one_row_per_seed_after_gate():
    """门后不再判（每 seed 至多一笔）：判过（杀 / 放行）之后任意帧恒 None。"""
    st = _race_state(bar=0.86)
    assert decide_race_kill(0.85, 90.0, st)['would_kill'] is True
    for elapsed in (91.0, 120.0, 179.9):
        assert decide_race_kill(0.99, elapsed, st) is None
    st2 = _race_state(bar=0.86)
    assert decide_race_kill(0.87, 90.0, st2)['would_kill'] is False
    assert decide_race_kill(0.86, 150.0, st2) is None   # 放行后亦不再复审


def test_decide_row_schema_isomorphic_to_kill_decisions():
    """决策 dict 与 kill_decisions 行同构（键集 + race 重载：S_tau=bar、theta=None）。"""
    st = _race_state(seed=123, bar=0.8430, incumbent=0.8500)
    row = decide_race_kill(0.8425, 90.0, st)
    assert set(row) == {'t', 'seed', 'rule', 'd', 'tau', 'S_tau', 'theta', 'I',
                        'would_kill'}
    assert row['seed'] == 123 and row['d'] == 0.8425
    assert row['tau'] == 0.5                       # elapsed / race 预算
    assert row['S_tau'] == 0.843                   # bar 参照值（重载）
    assert row['theta'] is None                    # race 不维护 θ（重载）
    assert row['I'] == 0.85 and row['t'] == 90.0


def test_race_same_seed_never_rejudged_joint_property():
    """「确定性重放 + 严格破纪录」联合性质：破纪录续跑的 seed 永不二次续跑 / 补杀。

    同 seed 重放到门帧判放行后，后续帧（含密度回落 / 再破纪录）均不再评估 ——
    race 对一个 seed 至多消费一次门帧决策，续跑即跑满预算。
    """
    st = _race_state(index=2, bar=0.84)
    frames = [(0.80, 45.0), (0.845, 89.0), (0.845, 90.0), (0.85, 100.0),
              (0.84, 130.0), (0.88, 179.0), (0.90, 179.9)]
    rows = [decide_race_kill(d, t, st) for d, t in frames]
    # 门帧 = 第 3 帧（首帧 elapsed >= 90）：破纪录 0.845 > 0.84 放行；之后全 None。
    assert rows[:2] == [None, None]
    assert rows[2]['would_kill'] is False
    assert rows[3:] == [None] * (len(frames) - 3)


def test_se_plan_default_arithmetic():
    """k = max(1, (T − FULL_UNIT) // SEED_UNIT)（默认 90/180 档手算对拍）。"""
    assert se_plan(600) == (4, 180.0)       # 417.5 // 92.5 = 4
    assert se_plan(1200) == (11, 180.0)     # 11x92.5 + 182.5 = 1200 恰用满
    assert se_plan(1800) == (17, 180.0)
    assert se_plan(3600) == (36, 180.0)
    assert se_plan(10_000) == (106, 180.0)


def test_se_plan_budget_insufficient_branch():
    """T < FULL_UNIT + SEED_UNIT（连 1 筛 + 1 延都装不下）→ StrategyBudgetError。"""
    with pytest.raises(StrategyBudgetError):
        se_plan(274.9)
    assert se_plan(275.0) == (1, 180.0)     # 恰好最小配置：边界含等号
    assert issubclass(StrategyBudgetError, ValueError)


def test_se_plan_custom_units_scale():
    """自定义筛选 / 延长预算按同口径记账（US-002 冒烟档 30/60 @ T=300）。"""
    assert se_plan(300, 30, 60) == (7, 60.0)      # (300-62.5)//32.5 = 7
    assert se_plan(95, 30, 60) == (1, 60.0)       # 62.5+32.5=95 恰好
    with pytest.raises(StrategyBudgetError):
        se_plan(94.9, 30, 60)
    assert se_plan(1200, screen_s=90, ext_s=180)[0] == 11   # 显式传默认 == 缺省


# -------------------------------------------------------------- 回放回归（fixture）


def _load_fixture() -> list[dict]:
    data = json.loads(_FIXTURE.read_text(encoding='utf-8'))
    return data['seeds']


def _at(curve: list[list[float]], t: float) -> float:
    """曲线取值（单调包络阶梯）：t 时刻值 = 最后一个 ``pt <= t`` 的密度。"""
    v = 0.0
    for pt, d in curve:
        if pt <= t + 1e-9:
            v = d
        else:
            break
    return v


def _replay_uniform90(seq: list[dict], total: float) -> tuple[float, list[dict]]:
    """均分基线：k x 90s 串行（k = T // SEED_UNIT_S），交付 = 各 seed 90s 终值 max。"""
    k = int(total // SEED_UNIT_S)
    started = seq[:k]
    return max(_at(s['b90s'], SE_SCREEN_S) for s in started), started


def _replay_se(seq: list[dict], total: float) -> tuple[float, list[dict]]:
    """SE 筛延：k 轮 90s 筛选 + 冠军（b90s 终值 argmax）180s 延长（b180f fork）。"""
    k, _ext = se_plan(total)
    screens = seq[:k]
    champ = max(screens, key=lambda s: _at(s['b90s'], SE_SCREEN_S))
    best = max(max(_at(s['b90s'], SE_SCREEN_S) for s in screens),
               _at(champ['b180f'], SE_EXT_S))
    return best, screens


def _replay_race(seq: list[dict], total: float) -> tuple[float, list[dict]]:
    """race 门杀回放：每 seed 180s 预算，门帧 90s 处 ``decide_race_kill`` 判杀。

    名义记账：被杀 seed 消耗门段（gate + 启动开销），续跑 seed 消耗全程
    （budget + 启动开销）；start 条件 spent + 门段 <= T（被杀省出的预算由
    串行队列自然吸收）。与 US-002 控制器同一判据单一真相源。
    """
    gate = race_gate_seconds(RACE_BUDGET_S, RACE_GATE_TAU)
    unit_gate, unit_full = gate + STRATEGY_STARTUP_S, RACE_BUDGET_S + STRATEGY_STARTUP_S
    spent, delivered, bar, incumbent = 0.0, 0.0, None, None
    started: list[dict] = []
    for index, s in enumerate(seq, start=1):
        if spent + unit_gate > total:
            break
        st = {'seed': s['seed'], 'index': index, 'gate_seconds': gate,
              'budget': RACE_BUDGET_S, 'bar': bar, 'incumbent': incumbent,
              'judged': False}
        row = decide_race_kill(_at(s['b180f'], gate), gate, st)
        assert row is not None                       # 门帧必出决策（回放口径）
        if row['would_kill']:
            delivered = max(delivered, _at(s['b180f'], gate))
            spent += unit_gate
        else:
            delivered = max(delivered, _at(s['b180f'], RACE_BUDGET_S))
            spent += unit_full
        bar, incumbent = st['bar'], delivered
        started.append(s)
    return delivered, started


def _bootstrap_means(total: float) -> dict:
    """固定 bootstrap seed 配对重放三策略（同一 seed 序列，配对比较）。"""
    pool = _load_fixture()
    rng = random.Random(_BOOT_SEED)
    acc = {'uniform90': 0.0, 'se': 0.0, 'race': 0.0}
    miss = {'se': 0, 'race': 0}
    for _ in range(_BOOT_N):
        seq = [pool[rng.randrange(len(pool))] for _ in range(_BOOT_LEN)]
        u, _u_started = _replay_uniform90(seq, total)
        s, s_started = _replay_se(seq, total)
        r, r_started = _replay_race(seq, total)
        acc['uniform90'] += u
        acc['se'] += s
        acc['race'] += r
        # 漏 max = 交付 < 采样 seed 全程 max（180s fork 终值 = 各 seed 潜力上界）。
        for key, delivered, started in (('se', s, s_started), ('race', r, r_started)):
            oracle = max(_at(x['b180f'], RACE_BUDGET_S) for x in started)
            if delivered < oracle - 1e-9:
                miss[key] += 1
    means = {k: v / _BOOT_N for k, v in acc.items()}
    means.update({f'miss_{k}': v / _BOOT_N for k, v in miss.items()})
    return means


def test_fixture_pairs_and_envelope():
    """fixture 契约：8 配对 seed、端点 = 实测对（b90s 终值 / b180f@180）、单调包络。"""
    seeds = _load_fixture()
    pairs = [(84.27, 84.39), (83.78, 83.82), (86.35, 86.90), (83.52, 83.81),
             (87.00, 87.22), (84.00, 85.72), (83.74, 84.84), (83.57, 84.26)]
    assert len(seeds) == 8
    assert len({s['seed'] for s in seeds}) == 8
    for s, (b90, b180) in zip(seeds, pairs):
        for key, horizon in (('b90s', 90.0), ('b180f', 180.0)):
            ts = [p[0] for p in s[key]]
            ds = [p[1] for p in s[key]]
            assert all(b > a for a, b in zip(ts, ts[1:]))          # 时间严格递增
            assert all(b >= a for a, b in zip(ds, ds[1:]))         # 密度单调包络
            assert ts[-1] <= horizon
            assert all(t2 - t1 >= 1.0 for t1, t2 in zip(ts, ts[1:]))  # 每秒 <= 1 帧
        assert s['b90s'][-1][1] == pytest.approx(b90 / 100.0, abs=1e-9)
        assert s['b180f'][-1][1] == pytest.approx(b180 / 100.0, abs=1e-9)
        # 跨 fork 结构如实保留：b180f@90（race 门值）!= b90s 终值（不同 fork 噪声）。
        assert _at(s['b180f'], 90.0) != s['b90s'][-1][1]


def test_replay_race_kill_structure_on_ordered_pool():
    """确定性回放（顺序池，T=1200）：首 seed 豁免、门杀省预算、最强门值 seed 续跑。"""
    seq = _load_fixture()
    delivered, started = _replay_race(seq, 1200.0)
    assert started[0]['seed'] == seq[0]['seed']          # 首 seed 必启动且豁免
    assert delivered == pytest.approx(0.8722, abs=1e-9)  # seed105 门值 87.02 全场最高
    assert len(started) < int(1200 // SEED_UNIT_S)       # 全程轮吃满名义预算
    # 门杀存在性：seed102 门值 0.8376 <= bar（seed101 门值 0.8430）→ 判杀。
    st = {'seed': seq[1]['seed'], 'index': 2, 'gate_seconds': 90.0,
          'budget': RACE_BUDGET_S, 'bar': _at(seq[0]['b180f'], 90.0),
          'incumbent': None, 'judged': False}
    assert decide_race_kill(_at(seq[1]['b180f'], 90.0), 90.0, st)['would_kill'] is True


def test_replay_regression_t1200_both_modes_beat_uniform90():
    """T=1200（20min 档）：SE / race − uniform90 >= +0.1pt。"""
    m = _bootstrap_means(1200.0)
    assert m['se'] - m['uniform90'] >= 0.001
    assert m['race'] - m['uniform90'] >= 0.001
    assert 0.85 < m['uniform90'] < 0.88               # 量级护栏（小宇宙 ±0.15pt）


def test_replay_regression_t3600_gain_and_miss_max():
    """T=3600（1h 档）：增益 >= +0.1pt 且两模式漏 max 率 <= 5%。"""
    m = _bootstrap_means(3600.0)
    assert m['se'] - m['uniform90'] >= 0.001
    assert m['race'] - m['uniform90'] >= 0.001
    assert m['miss_se'] <= 0.05
    assert m['miss_race'] <= 0.05


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
