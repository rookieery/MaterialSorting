"""US-003 ``cli/calibration`` simulate 策略双档（se180 / race180）测试。

合成配对曲线（short 100s + full 300s，5s 帧距 → 门帧恰在 90s）驱动，覆盖：

  - 单场景回放结构：se「k 轮筛选 + 冠军延长恰一次」（筛选读 short 终值、延长读
    full 180s 帧、并列取先执行者）；race「首 seed 豁免参照 + 门杀省时再投资」
    （被杀记门段 92.5、跑满记全程 182.5，启动数 > 均分全程轮数）；
  - 「同 seed 不二次续跑」：race 门后不再判（每 seed 至多一笔决策）、se 冠军
    延长恰一次；
  - R0 恒先（--target 共存）：race 续跑窗口内达标停整场景、se 筛选期达标跳过
    延长；
  - 指标与报告字段：ETT 口径（与 kill/θ 档同构）+ E[max] 口径（delivered /
    oracle / 漏 max 率 / 配对 uniform90 基线与增益）；CLI 端到端（控制台双档行 +
    报告 strategies 行 + pools 配对计数 + 确定性）；
  - DRY 断言：双档回放与 US-001 fixture 回放器共享 ``portfolio`` 判据单一真相源
    （``se_plan`` / ``race_plan`` / ``decide_race_kill``，monkeypatch spy +
    函数对象同一性）；
  - 推荐候选：策略双档纳入 ``recommend_strategy``（判据同现有：ETT/误杀率双
    达标），params 为 ``--strategy`` 旗标形；
  - 降级路径：总预算不足（T < 275 名义最小配置）/ 无同 seed 配对曲线 →
    metrics=None + note（不进推荐）。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.cli import calibration as cal
from materialsorting.cli import portfolio as pf
from materialsorting.cli.calibration import (SIM_STRATEGY_GRID,
                                             evaluate_strategy_tier,
                                             recommend_strategy,
                                             simulate_strategy_scenario)
from materialsorting.cli.portfolio import FULL_UNIT_S, SEED_UNIT_S, race_plan

TARGET = 0.85
_SE_SPEC = next(s for s in SIM_STRATEGY_GRID if s['name'] == 'se180')
_RACE_SPEC = next(s for s in SIM_STRATEGY_GRID if s['name'] == 'race180')


# ------------------------------------------------------- 合成配对曲线装置


def _frames(values: dict, native: float) -> list[dict]:
    """{elapsed: density} 阶梯 → 5s 帧距曲线（native 为末帧时刻，密度单调不降）。"""
    out = []
    t = 5.0
    while t <= native + 1e-9:
        v = values[max(k for k in values if k <= t + 1e-9)]
        out.append({'elapsed': float(t), 'phase': 'exploring',
                    'density': float(v), 'density_sparrow': float(v) + 0.01,
                    'width_mm': 50000.0})
        t += 5.0
    return out


def _pair(s90: float, f90: float, f180: float) -> tuple:
    """配对曲线：short（90s 终值 s90，原生 100s）+ full（门值 f90 @90s、180s 帧值
    f180，原生 300s）—— 跨 fork 结构：f90 独立于 s90（不同 fork 噪声）。"""
    return _frames({5.0: s90}, 100.0), _frames({5.0: f90, 95.0: f180}, 300.0)


def _run(argv: list) -> tuple:
    """进程内调 ``cal.main(argv)``，捕获 stdout/stderr（规避 Windows GBK 重定向）。"""
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        rc = cal.main(list(argv))
    return rc, buf_out.getvalue(), buf_err.getvalue()


@pytest.fixture
def iso_env(tmp_path, monkeypatch):
    """隔离环境：CALIBRATION_DIR 指向 tmp（simulate 只读曲线）。"""
    cal_root = tmp_path / 'portfolio_calibration'
    cal_root.mkdir()
    monkeypatch.setattr(paths_mod, 'CALIBRATION_DIR', str(cal_root))
    return tmp_path, cal_root


def _seed_paired_tag(cal_root: Path, tag: str = 'sim2') -> Path:
    """配对 tag 目录：base 同 seed 0..5 配对（3 好 + 3 差）+ variant_0 4 配对。

    好 pair：short@90 = 0.86（首帧即达 TARGET）、full 门值 0.85、180s 帧 0.88；
    差 pair：short@90 = 0.70、门值 0.68、180s 帧 0.71（永不达标）。
    """
    good, bad = _pair(0.86, 0.85, 0.88), _pair(0.70, 0.68, 0.71)
    groups = {'base': {i: (good if i < 3 else bad) for i in range(6)},
              'variant_0': {i: (_pair(0.86, 0.85, 0.87) if i < 2
                                else _pair(0.70, 0.68, 0.70)) for i in range(4)}}
    for grp, curves in groups.items():
        for sub in ('short', 'full'):
            d = cal_root / tag / grp / sub
            d.mkdir(parents=True, exist_ok=True)
            for seed, pair in curves.items():
                (d / f'curve_s{seed}.json').write_text(
                    json.dumps(pair[0 if sub == 'short' else 1],
                               ensure_ascii=False), encoding='utf-8')
    return cal_root / tag


# ------------------------------------------------------- 单场景回放（合成池）


def test_se_replay_screen_and_extend_structure():
    """se：se_plan(T) 轮筛选（short 终值）+ 冠军（argmax，并列取先）延长恰一次
    （full 180s 帧）；wall = 筛选段 + 延长段实际帧时刻。"""
    pairs = [_pair(0.80, 0.79, 0.83), _pair(0.86, 0.84, 0.90),
             _pair(0.82, 0.81, 0.83), _pair(0.84, 0.83, 0.83),
             _pair(0.70, 0.69, 0.71)]
    r = simulate_strategy_scenario(pairs, 'se', 600.0)
    assert r['started'] == 4                                  # se_plan(600) = (4, 180)
    outcomes = [(e['outcome'], e['index']) for e in r['per_seed']]
    assert outcomes == [('screen', 1), ('screen', 2), ('screen', 3),
                        ('screen', 4), ('extension', 2)]       # 冠军 = 筛选值 argmax
    assert r['per_seed'][-1]['champion'] is True
    assert sum(e['outcome'] == 'extension' for e in r['per_seed']) == 1
    assert r['delivered'] == pytest.approx(0.90)               # 延长读 full 180s 帧
    assert r['wall_time'] == pytest.approx(4 * 90.0 + 180.0)   # 实际帧时刻口径
    assert r['oracle_max'] == pytest.approx(0.90)              # 启动 seed 全程潜力 max
    assert r['miss_max'] is False
    assert r['reached'] is False                               # 无 target 不评估 R0
    # 并列取先执行者：两轮筛选值相同 → 冠军 = 队列序靠前者。
    tie = [_pair(0.86, 0.84, 0.88), _pair(0.86, 0.84, 0.90), _pair(0.70, 0.69, 0.71)]
    r2 = simulate_strategy_scenario(tie, 'se', 300.0)          # se_plan(300) = (1, 180)
    assert r2['started'] == 1
    assert [(e['outcome'], e['index']) for e in r2['per_seed']] == \
        [('screen', 1), ('extension', 1)]


def test_race_replay_gate_kill_reinvests_budget():
    """race：门杀省时再投资 —— 被杀 seed 只记门段 92.5（名义），同预算启动数 >
    均分全程轮数；被杀者交付门值 best-so-far、破纪录者续跑满 180s。"""
    pairs = [_pair(0.80, 0.80, 0.82), _pair(0.79, 0.79, 0.78),
             _pair(0.82, 0.81, 0.85), _pair(0.80, 0.805, 0.79),
             _pair(0.84, 0.83, 0.87), _pair(0.90, 0.99, 0.95)]
    r = simulate_strategy_scenario(pairs, 'race', 600.0)
    assert race_plan(600.0) == (5, 90.0)                       # 计划上界（全门杀乐观）
    assert r['started'] == 4                                   # 预算收口：第 5 个不启动
    assert r['started'] > int(600.0 // FULL_UNIT_S)            # 4 > 3：省时再投资
    assert [e['outcome'] for e in r['per_seed']] == ['full', 'kill', 'full', 'kill']
    assert [e['t_stop'] for e in r['per_seed']] == [180.0, 90.0, 180.0, 90.0]
    assert r['delivered'] == pytest.approx(0.85)               # 破纪录者 180s 帧
    assert r['wall_time'] == pytest.approx(180 + 90 + 180 + 90)
    assert r['oracle_max'] == pytest.approx(0.85) and r['miss_max'] is False


def test_race_first_seed_exempt_and_bar_reference():
    """首 seed 无条件豁免（最低门值也不杀，其门值入 bar 作后续参照）。"""
    pairs = [_pair(0.70, 0.70, 0.72), _pair(0.80, 0.80, 0.83),
             _pair(0.75, 0.75, 0.74)]
    r = simulate_strategy_scenario(pairs, 'race', 1000.0)
    assert [e['outcome'] for e in r['per_seed']] == ['full', 'full', 'kill']
    assert r['per_seed'][0]['t_stop'] == 180.0                 # 豁免 → 跑满


def test_race_judged_once_and_se_extended_once(monkeypatch):
    """「同 seed 不二次续跑」联合性质：race 门后不再判（非 None 决策数 = 启动
    seed 数，门后帧/密度跃升不再评估）；se 冠军延长恰一次。"""
    calls = {'rows': 0}
    orig = cal.decide_race_kill

    def spy(best, elapsed, state):
        row = orig(best, elapsed, state)
        if row is not None:
            calls['rows'] += 1
        return row

    monkeypatch.setattr(cal, 'decide_race_kill', spy)
    pairs = [_pair(0.80, 0.80, 0.86), _pair(0.85, 0.85, 0.90)]
    r = simulate_strategy_scenario(pairs, 'race', 400.0)
    assert [e['outcome'] for e in r['per_seed']] == ['full', 'full']
    assert calls['rows'] == r['started'] == 2                  # 每 seed 至多一笔
    # se：k 轮筛选 + 恰一次延长（同 seed 不二次续跑）。
    r2 = simulate_strategy_scenario(pairs + [_pair(0.70, 0.69, 0.71)], 'se', 600.0)
    assert sum(e['outcome'] == 'extension' for e in r2['per_seed']) == 1


def test_strategy_scenario_r0_precedence():
    """R0 恒先（--target 共存）：race 续跑窗口内达标停整场景（wall = 前序 + 达标
    时刻，剩余队列不启动）；se 筛选期达标跳过延长。"""
    # race：seed1 必死跑满（门值 0.70 豁免）；seed2 破纪录续跑、150s 帧达标 R0。
    late = _frames({5.0: 0.80, 95.0: 0.84, 150.0: 0.87}, 300.0)
    pairs = [_pair(0.86, 0.70, 0.72), (_frames({5.0: 0.70}, 100.0), late),
             _pair(0.90, 0.90, 0.95)]
    r = simulate_strategy_scenario(pairs, 'race', 600.0, target=TARGET)
    assert [e['outcome'] for e in r['per_seed']] == ['full', 'r0']
    assert r['per_seed'][1]['t_stop'] == 150.0
    assert r['reached'] and r['wall_time'] == pytest.approx(180.0 + 150.0)
    assert r['started'] == 2                                   # R0 后剩余不启动
    # se：首轮筛选 short 首帧即达标 → 跳过延长（队列停）。
    r2 = simulate_strategy_scenario(pairs, 'se', 600.0, target=TARGET)
    assert [e['outcome'] for e in r2['per_seed']] == ['r0']
    assert r2['reached'] and r2['wall_time'] == pytest.approx(5.0)
    assert all(e['outcome'] != 'extension' for e in r2['per_seed'])


# ------------------------------------------------------- 指标 / 报告 / CLI


def test_strategy_tier_metrics_and_cli_end_to_end(iso_env):
    """evaluate_strategy_tier 指标字段（ETT + E[max] 双口径）+ CLI 端到端：控制台
    双档行、报告 strategies 行、pools 配对计数、变体 held-out、确定性。"""
    tmp_path, cal_root = iso_env
    _seed_paired_tag(cal_root)
    rc, out, err = _run(['simulate', '--tag', 'sim2', '--target', str(TARGET),
                         '--budget', '600', '--scenarios', '50'])
    assert rc == 0, err
    assert '策略双档 E[max] 口径' in out
    assert out.count('se180') >= 2 and out.count('race180') >= 2   # 主表 + E[max] 表

    rep = json.loads((cal_root / 'sim2' / 'analysis' / 'simulation_report.json')
                     .read_text(encoding='utf-8'))
    assert rep['pools']['base']['pairs'] == 6
    assert rep['pools']['variants']['pairs'] == 4
    se = rep['strategies']['se180']
    race = rep['strategies']['race180']
    for st, mode, k_exp, b_exp in ((se, 'se', 4, 90.0), (race, 'race', 5, 180.0)):
        assert st['kind'] == 'strategy' and st['mode'] == mode
        assert st['k'] == k_exp and st['per_seed_budget'] == b_exp
        assert st['total_budget'] == 600.0 and st['kill_params'] is None
        assert st['envelope'] is None and st['n_eligible'] == 6
        assert st['base']['n_scenarios'] == 50 and st['base']['mode'] == 'bootstrap'
        # 变体池 4^6 = 4096 ≤ 上限 → 全枚举精确。
        assert st['variants']['n_scenarios'] == 4096
        assert st['variants']['mode'] == 'exhaustive'
        for m in (st['base'], st['variants']):
            assert m is not None
            assert {'ett', 'ett_reached', 'p_reach', 'delivered_mean',
                    'delivered_sigma', 'oracle_max_mean', 'miss_max_rate',
                    'uniform90_delivered_mean', 'gain_vs_uniform90',
                    'started_mean', 'n_kills', 'false_kill_rate'} <= set(m)
            assert m['ett'] > 0 and 0.0 <= m['p_reach'] <= 1.0
            assert 0.0 <= m['miss_max_rate'] <= 1.0
            # gain = 未舍入均值差再 round(6)（与两侧已舍入均值差容差 2e-6）。
            assert m['gain_vs_uniform90'] == pytest.approx(
                m['delivered_mean'] - m['uniform90_delivered_mean'], abs=2e-6)
    assert se['plan']['k_screens'] == 4 and se['plan']['ext_s'] == 180.0
    assert race['plan']['n_planned'] == 5 and race['plan']['gate_seconds'] == 90.0
    assert race['base']['n_kills'] > 0 and race['base']['false_kill_rate'] == 0.0
    assert se['base']['n_kills'] == 0                           # se 无门杀
    # 确定性：同输入两次运行，除 generated 外逐字节一致。
    _run(['simulate', '--tag', 'sim2', '--target', str(TARGET),
          '--budget', '600', '--scenarios', '50'])
    rep2 = json.loads((cal_root / 'sim2' / 'analysis' / 'simulation_report.json')
                      .read_text(encoding='utf-8'))
    rep.pop('generated'), rep2.pop('generated')
    assert rep == rep2


def test_strategy_tiers_share_us001_criteria_dry(monkeypatch):
    """DRY 断言：双档回放与 US-001 fixture 回放器共享 ``portfolio`` 判据单一真相源
    （函数对象同一性 + monkeypatch spy 证明回放确实调用它们）。"""
    assert cal.decide_race_kill is pf.decide_race_kill
    assert cal.se_plan is pf.se_plan and cal.race_plan is pf.race_plan
    pool = [_pair(0.80, 0.80, 0.85), _pair(0.70, 0.70, 0.72),
            _pair(0.86, 0.85, 0.88)]
    spies = {}
    for name in ('decide_race_kill', 'se_plan', 'race_plan'):
        orig = getattr(cal, name)
        seen = []

        def wrap(*a, _orig=orig, _seen=seen, **kw):
            _seen.append(a)
            return _orig(*a, **kw)

        monkeypatch.setattr(cal, name, wrap)
        spies[name] = seen
    evaluate_strategy_tier(pool, _RACE_SPEC, target=TARGET, total_budget=600.0)
    assert spies['race_plan'] and spies['decide_race_kill']
    evaluate_strategy_tier(pool, _SE_SPEC, target=TARGET, total_budget=600.0)
    assert spies['se_plan']


def test_recommend_strategy_includes_strategy_tiers():
    """推荐候选纳入双档（判据同现有）：ETT/误杀率双达标 → params 为 --strategy
    旗标形；变体 ETT 劣化 / 误杀率 >= 5% 淘汰。"""
    def _metrics(ett, fkr=0.0, kills=3):
        return {'ett': ett, 'p_reach': 0.9, 'ett_reached': ett, 'n_unreachable': 1,
                'n_scenarios': 100, 'mode': 'exhaustive', 'n_kills': kills,
                'n_false_kills': int(fkr * kills), 'false_kill_rate': fkr}

    def _strat_entry(mode, base, variants, plan):
        return {'kind': 'strategy', 'mode': mode, 'k': 5, 'per_seed_budget': 180.0,
                'total_budget': 600.0, 'plan': plan, 'kill_params': None,
                'envelope': None, 'base': base, 'variants': variants}

    race_plan_d = {'n_planned': 5, 'race_budget': 180.0, 'race_gate_tau': 0.5,
                   'gate_seconds': 90.0}
    se_plan_d = {'k_screens': 4, 'screen_s': 90.0, 'ext_s': 180.0}
    entries = {
        'single': {'kind': 'baseline', 'k': 1, 'per_seed_budget': 600.0,
                   'kill_params': None, 'envelope': None,
                   'base': _metrics(100.0, kills=0),
                   'variants': _metrics(120.0, kills=0)},
        'kill_a': {'kind': 'kill', 'k': 3, 'per_seed_budget': 200.0,
                   'kill_params': {'tau0': 0.2, 'W': 5.0, 'm': 0.01},
                   'envelope': {}, 'base': _metrics(70.0),
                   'variants': _metrics(90.0)},
        'race180': _strat_entry('race', _metrics(60.0), _metrics(80.0), race_plan_d),
        'se180': _strat_entry('se', _metrics(65.0), _metrics(200.0), se_plan_d),
    }
    rec = recommend_strategy(entries, target=TARGET, source='simulate:t',
                             has_variants=True)
    assert rec['qualified'] == ['kill_a', 'race180']            # se180 变体 ETT 劣化淘汰
    assert rec['strategy'] == 'race180'                         # base ETT 最小者
    p = rec['params']
    assert p['strategy'] == 'race' and p['time'] == 600
    assert p['race_budget'] == 180.0 and p['race_gate'] == 0.5
    assert p['calibrated'] is True and p['target'] == TARGET
    assert rec['ett_gain_base'] == pytest.approx(0.4)
    # se 档胜出 → se 旗标形；误杀率 >= 5% 淘汰。
    entries['race180'] = _strat_entry('race', _metrics(60.0, fkr=0.06),
                                      _metrics(80.0, fkr=0.06), race_plan_d)
    entries['se180'] = _strat_entry('se', _metrics(62.0), _metrics(80.0), se_plan_d)
    rec2 = recommend_strategy(entries, target=TARGET, source='simulate:t',
                              has_variants=True)
    assert rec2['strategy'] == 'se180'
    assert rec2['params']['strategy'] == 'se' and rec2['params']['time'] == 600
    assert rec2['params']['se_screen'] == 90.0 and rec2['params']['se_extend'] == 180.0


def test_strategy_tier_degradation_paths(iso_env):
    """降级：总预算 < 名义最小配置（full 182.5 + 门段 92.5 = 275）→ metrics=None +
    note；预算够但无同 seed 配对曲线 → metrics=None + note（不进推荐）。"""
    tmp_path, cal_root = iso_env
    pool = [_pair(0.80, 0.80, 0.85)]
    for spec in (_SE_SPEC, _RACE_SPEC):
        st = evaluate_strategy_tier(pool, spec, target=TARGET, total_budget=200.0)
        assert st['metrics'] is None and st['k'] is None and st['plan'] is None
        assert '最小配置' in st['note']
        assert SEED_UNIT_S + FULL_UNIT_S == 275.0               # 名义最小配置对拍
    st = evaluate_strategy_tier([], _RACE_SPEC, target=TARGET, total_budget=600.0)
    assert st['metrics'] is None and '配对' in st['note']
    # CLI：short-only tag（无 full 组）在充足预算下双档行降级、rc=0。
    d = cal_root / 'sim3' / 'base' / 'short'
    d.mkdir(parents=True)
    for seed in range(3):
        (d / f'curve_s{seed}.json').write_text(
            json.dumps(_pair(0.8, 0.8, 0.85)[0]), encoding='utf-8')
    rc, out, err = _run(['simulate', '--tag', 'sim3', '--target', str(TARGET),
                         '--budget', '600', '--scenarios', '20'])
    assert rc == 0, err
    rep = json.loads((cal_root / 'sim3' / 'analysis' / 'simulation_report.json')
                     .read_text(encoding='utf-8'))
    for name in ('se180', 'race180'):
        assert rep['strategies'][name]['base'] is None
        assert '配对' in rep['strategies'][name]['note']
        assert rep['strategies'][name]['variants'] is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
