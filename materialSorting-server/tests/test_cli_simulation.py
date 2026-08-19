"""PC-005 ``cli/calibration`` simulate ETT 离线仿真器测试。

合成曲线（已知分布）驱动，覆盖：
  - 纯函数：截断 / R0 口径达标时刻 / best-so-far / 条件期望增量与截断插值下界
    （AC#2：kill 时刻 incumbent 估计 ≥ 该时刻 best-so-far）；
  - 按预算 B 重采样的成功包络（成功 = 预算内达标；原生归一包络套小预算会误判）；
  - ``simulate_portfolio`` 单场景回放（复用 PortfolioController：R0 停队列 /
    seed 1 豁免 / R1 kill / 误杀 oracle / R3 θ 衰减改变后续 R2 判决）；
  - AC#1 理论排序：best-of-k < 单 seed（同总预算下多抽便宜签）；分离度大时
    激进 kill < 保守 kill（省时计入 ETT）—— 全枚举场景手算对拍；
  - 推荐判据（AC#3）：base 与变体 ETT 双不劣于单 seed + 误杀率 < 5%，参数字段
    与 controller_params.json 同构；
  - CLI 端到端：simulation_report.json 落盘 + 控制台表格 + 变体 held-out +
    --shadow-log 假阳性统计 + 确定性（除 generated 外逐字节一致）+ 错误路径；
  - ``python -m materialsorting.cli.calibration simulate --help`` 冒烟 + 分层
    （calibration 全模块禁 import web，沿用 test_cli_calibration 的 AST 断言）。
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.cli import calibration as cal
from materialsorting.cli.calibration import (SIM_STRATEGY_GRID,
                                             best_density_upto,
                                             conditional_gain,
                                             envelope_at_budget,
                                             evaluate_strategy,
                                             interpolate_truncated_final,
                                             main, recommend_strategy,
                                             shadow_log_stats,
                                             simulate_portfolio,
                                             simulate_tag, time_to_target,
                                             truncate_curve)
from materialsorting.cli.portfolio import KILL_DEFAULTS, R1_REASON, R2_REASON

TARGET = 0.85


# ------------------------------------------------------- 合成曲线装置（已知分布）


def _mk_curve(points, compress_from=None) -> list[dict]:
    """(elapsed, density) 序列 → curve 帧（compress_from 起相位切 compressing）。"""
    return [{'elapsed': float(t),
             'phase': ('compressing' if compress_from is not None and i >= compress_from
                       else 'exploring'),
             'density': float(d), 'density_sparrow': float(d) + 0.01,
             'width_mm': 50000.0 - i * 10.0}
            for i, (t, d) in enumerate(points)]


def _pairs(densities: dict, native: float = 100.0) -> list:
    """{elapsed: density} + 5s 间隔补齐到 native（迟滞判据需要密集帧）。"""
    out = []
    t = 5.0
    while t <= native:
        known = max(k for k in densities if k <= t)
        out.append((t, densities.get(t, densities[known])))
        t += 5.0
    return out


def _reacher(native: float = 100.0) -> list[dict]:
    """快升达标者：5/10/15s 爬 0.72/0.73/0.74，20s 起达标 0.86（>= TARGET）。"""
    return _mk_curve(_pairs({5.0: 0.72, 10.0: 0.73, 15.0: 0.74, 20.0: 0.86}, native))


def _doomed(offset: float = 0.55, native: float = 100.0) -> list[dict]:
    """必死者：全程 0.55x 低位爬升，永不达标（与达标轨迹分离度大）。"""
    dens = {5.0: round(offset + 5.0 * 0.0002, 6),
            native: round(offset + native * 0.0002, 6)}
    return _mk_curve(_pairs(dens, native))


def _spec(name: str) -> dict:
    return next(s for s in SIM_STRATEGY_GRID if s['name'] == name)


def _run(argv: list[str]) -> tuple[int, str, str]:
    """进程内调 ``cal.main(argv)``，捕获 stdout/stderr（规避 Windows GBK 重定向）。"""
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        rc = cal.main(list(argv))
    return rc, buf_out.getvalue(), buf_err.getvalue()


@pytest.fixture
def iso_env(tmp_path, monkeypatch):
    """隔离环境：CALIBRATION_DIR 指向 tmp（simulate 只读曲线，无需 commit/master）。"""
    cal_root = tmp_path / 'portfolio_calibration'
    cal_root.mkdir()
    monkeypatch.setattr(paths_mod, 'CALIBRATION_DIR', str(cal_root))
    return tmp_path, cal_root


def _seed_curves(cal_root: Path, tag: str, groups: dict) -> Path:
    """直接往 tag 目录写曲线文件（simulate 的输入侧，不经求解）。"""
    for rel, curves in groups.items():
        d = cal_root / tag / rel
        d.mkdir(parents=True, exist_ok=True)
        for seed, curve in curves.items():
            (d / f'curve_s{seed}.json').write_text(
                json.dumps(curve, ensure_ascii=False), encoding='utf-8')
    return cal_root / tag


# ------------------------------------------------------- 纯函数（含 AC#2 下界）


def test_curve_helpers():
    """截断前缀过滤 / R0 口径达标时刻（当前帧非 best-so-far）/ best-so-far。"""
    c = _reacher(native=30.0)
    assert [fr['elapsed'] for fr in truncate_curve(c, 12.0)] == [5.0, 10.0]
    assert truncate_curve(c, 4.0) == []                       # 早于首帧
    assert time_to_target(c, TARGET) == 20.0                  # 首个达标帧
    assert time_to_target(_doomed(native=30.0), TARGET) is None
    assert best_density_upto(c, 12.0) == 0.73
    assert best_density_upto(c, 4.0) is None


def test_conditional_gain_and_interpolation_bound():
    """AC#2：截断插值 = kill 时刻 best + 条件期望增量，且 >= kill 时刻 best-so-far。"""
    gain = _mk_curve([(10, 0.6), (50, 0.7), (100, 0.8)])
    flat = _mk_curve([(10, 0.5), (100, 0.5)])
    pool = [gain, flat]
    # tau=0.1（t=10）→ 预算末（t=100）的池级期望增量：[(0.8-0.6), (0.5-0.5)] 均值 0.1
    assert conditional_gain(pool, 0.1, 100.0) == pytest.approx(0.1)
    # tau 处尚无帧的曲线不计入条件样本；全池无样本 → 0
    assert conditional_gain([_mk_curve([(50, 0.7), (100, 0.8)])], 0.1, 100.0) == 0.0
    # 物理下界：插值估计 >= kill 时刻 best-so-far（增量非负）
    for curve, t_kill in ((gain, 10.0), (flat, 10.0), (gain, 50.0)):
        est = interpolate_truncated_final(curve, t_kill, pool, 100.0)
        assert est >= best_density_upto(curve, t_kill)
    assert interpolate_truncated_final(gain, 10.0, pool, 100.0) == pytest.approx(0.7)
    # kill 早于首帧：无 best-so-far 可估 → None
    assert interpolate_truncated_final(gain, 5.0, pool, 100.0) is None


def test_envelope_at_budget():
    """按预算 B 重采样：成功 = 预算内达标（预算后才达标者不进包络）、单调不降、
    网格 = tau*B 绝对墙钟。"""
    reach, doomed = _reacher(native=100.0), _doomed(native=100.0)
    env = envelope_at_budget([reach, doomed], TARGET, 40.0)
    assert env                                        # 达标者在预算内 → 包络非空
    assert list(env.values()) == sorted(env.values())  # 单调不降
    assert env['0.15'] == pytest.approx(0.73)          # tau*40=6s → 首个 elapsed>=6 帧即 @10s
    assert env['0.25'] == pytest.approx(0.73)          # tau*40=10s
    assert env['1.00'] == pytest.approx(0.86)
    # 预算 15s：达标时刻 20s > 预算 → 无成功曲线 → 空（R1 禁用）
    assert envelope_at_budget([reach, doomed], TARGET, 15.0) == {}
    # 预算 20s：恰在预算末帧达标 → 成功
    assert envelope_at_budget([reach], TARGET, 20.0)['1.00'] == pytest.approx(0.86)


# ------------------------------------------------------- simulate_portfolio 回放


def _agg_kill_params(**over):
    return {'tau0': 0.1, 'W': 3.0, 'm': 0.02, 'uplift_q95': 0.005, **over}


def test_simulate_portfolio_r0_full_and_kill():
    """R0 停队列 + seed 1 豁免（跑满）+ R1 kill 迟滞 + 误杀 oracle + wall-time。"""
    # 无 kill（best-of-k 形）：seed1 必死跑满 30s，seed2 达标 R0@20 → wall=50。
    r = simulate_portfolio([_doomed(native=30.0), _reacher(native=30.0)],
                           target=TARGET, budget=30.0)
    assert [e['outcome'] for e in r['per_seed']] == ['full', 'r0']
    assert r['reached'] and r['wall_time'] == 50.0
    assert r['total_budget'] == 60.0
    # kill 档（B=30，包络源自 [reacher]）：seed2 必死者 R1 kill@10（tau0=0.1、W=3、
    # m=0.02：t=5 起表、t=10 迟滞满）；seed3 达标 R0@20。
    env = envelope_at_budget([_reacher(native=30.0)], TARGET, 30.0)
    r2 = simulate_portfolio(
        [_doomed(native=30.0), _doomed(native=30.0), _reacher(native=30.0)],
        target=TARGET, budget=30.0, kill_params=_agg_kill_params(), envelope=env)
    assert [e['outcome'] for e in r2['per_seed']] == ['full', 'kill', 'r0']
    assert r2['per_seed'][1]['reason'] == R1_REASON
    assert r2['per_seed'][1]['t_stop'] == 10.0
    assert r2['per_seed'][1]['false_kill'] is False    # 必死者被杀 = 正确 kill
    assert r2['wall_time'] == 30.0 + 10.0 + 20.0       # kill 省时计入 wall-time
    # 误杀 oracle：慢热达标者（25s 达标 > kill@15）被杀 → false_kill=True。
    slow = _mk_curve([(5, 0.6), (10, 0.62), (15, 0.63), (20, 0.64), (25, 0.87),
                      (30, 0.87)])
    r3 = simulate_portfolio([_doomed(native=30.0), slow], target=TARGET, budget=30.0,
                            kill_params=_agg_kill_params(), envelope=env)
    assert [e['outcome'] for e in r3['per_seed']] == ['full', 'kill']
    assert r3['per_seed'][1]['false_kill'] is True
    assert r3['reached'] is False


def test_simulate_portfolio_unreachable_incumbent():
    """不可达场景 incumbent 终值：max(跑满 best, 被杀插值)，插值 >= kill 时刻 best。"""
    from materialsorting.cli.calibration import scenario_incumbent_final
    doomed1, doomed2 = _doomed(native=30.0), _doomed(offset=0.54, native=30.0)
    env = envelope_at_budget([_reacher(native=30.0)], TARGET, 30.0)
    r = simulate_portfolio([doomed1, doomed2], target=TARGET, budget=30.0,
                           kill_params=_agg_kill_params(), envelope=env)
    assert r['reached'] is False
    inc = scenario_incumbent_final(r['per_seed'], [doomed1, doomed2], 30.0)
    assert inc is not None
    full_best = best_density_upto(doomed1, 30.0)       # seed1 跑满贡献（精确）
    killed_best = best_density_upto(doomed2, r['per_seed'][1]['t_stop'])
    assert inc >= full_best
    assert inc >= killed_best                          # AC#2 下界（插值 >= best@kill）


def test_theta_decay_changes_later_r2_verdict():
    """R3 theta 衰减在回放内生效：连杀 >= m_streak → theta:=I+delta 只降门槛，
    后续 R2 判决翻转（不衰减则同 seed 也被杀）。"""
    a = _mk_curve([(10, 0.6), (20, 0.8), (100, 0.8)], compress_from=1)   # seed1 锚定
    b = _mk_curve([(5, 0.4), (10, 0.5), (100, 0.5)], compress_from=1)    # 必死（R2）
    c = _mk_curve([(5, 0.4), (10, 0.5), (100, 0.5)], compress_from=1)
    d = _mk_curve([(5, 0.7), (10, 0.802), (100, 0.802)], compress_from=1)
    base = {'tau0': 1.0, 'W': 10.0, 'm': 0.005, 'epsilon': 0.001,
            'uplift_q95': 0.005}                       # tau0=1.0 → R1 禁用，纯 R2/R3
    # m_streak=2：B、C 连杀后 theta := 0.8+0.005=0.805 → D（0.802+0.005 >= 0.805）存活。
    r_fast = simulate_portfolio([a, b, c, d], target=TARGET, budget=100.0,
                                kill_params={**base, 'delta': 0.005, 'm_streak': 2})
    assert [e['outcome'] for e in r_fast['per_seed']] == ['full', 'kill', 'kill', 'full']
    assert r_fast['per_seed'][1]['reason'] == R2_REASON
    assert r_fast['wall_time'] == 100.0 + 10.0 + 10.0 + 100.0
    # m_streak=3：连杀 2 不足 → theta 恒 0.85 → D 也被 R2 杀（0.807 < 0.85）。
    r_slow = simulate_portfolio([a, b, c, d], target=TARGET, budget=100.0,
                                kill_params={**base, 'delta': 0.005, 'm_streak': 3})
    assert [e['outcome'] for e in r_slow['per_seed']] == ['full', 'kill', 'kill', 'kill']
    assert r_slow['per_seed'][3]['reason'] == R2_REASON


# ------------------------------------------------------- AC#1 理论排序（手算对拍）


def test_ett_ordering_best_of_k_beats_single():
    """AC#1：同总预算（k*B 恒等）下 ETT：single(60) > best_of_2(52.5) > best_of_3。"""
    pool = [_reacher(), _doomed()]                     # 50% 达标率、t_reach=20、原生 100s
    common = dict(target=TARGET, total_budget=100.0, n_scenarios=500, env_q=0.25,
                  uplift_q95=0.005)
    single = evaluate_strategy(pool, _spec('single'), **common)
    bo2 = evaluate_strategy(pool, _spec('best_of_2'), **common)
    bo3 = evaluate_strategy(pool, _spec('best_of_3'), **common)
    assert single['metrics']['mode'] == 'exhaustive'   # |pool|^k=2 <= 上限 → 全枚举
    assert single['metrics']['ett'] == pytest.approx(60.0)        # (20+100)/2
    assert bo2['metrics']['ett'] == pytest.approx(52.5)           # (20+20+70+100)/4
    assert bo3['metrics']['ett'] == pytest.approx(46.667, rel=1e-3)
    assert bo3['metrics']['ett'] < bo2['metrics']['ett'] < single['metrics']['ett']
    assert bo3['metrics']['p_reach'] > bo2['metrics']['p_reach'] \
        > single['metrics']['p_reach']                 # 0.875 > 0.75 > 0.5
    assert single['metrics']['unreachable_incumbent_mean'] is not None


def test_ett_ordering_aggressive_kill_beats_conservative():
    """AC#1：分离度大时 ETT：kill_aggressive(37.92) < kill_conservative(43.54)
    < single(60)；误杀率 0（必死者被杀、达标者始终在包络上方）。"""
    pool = [_reacher(), _doomed()]
    common = dict(target=TARGET, total_budget=100.0, n_scenarios=500, env_q=0.25,
                  uplift_q95=0.005)
    single = evaluate_strategy(pool, _spec('single'), **common)
    aggr = evaluate_strategy(pool, _spec('kill_aggressive'), **common)
    cons = evaluate_strategy(pool, _spec('kill_conservative'), **common)
    for st in (aggr, cons):
        assert st['metrics']['n_kills'] > 0            # 迟滞判据确有 kill（手算 10s/25s）
        assert st['metrics']['false_kill_rate'] == 0.0
    assert aggr['metrics']['ett'] == pytest.approx(37.9167, rel=1e-3)
    assert cons['metrics']['ett'] == pytest.approx(43.5417, rel=1e-3)
    assert aggr['metrics']['ett'] < cons['metrics']['ett'] < single['metrics']['ett']


# ------------------------------------------------------- AC#3 推荐判据（纯）


def _metrics(ett, fkr=0.0, kills=3):
    return {'ett': ett, 'p_reach': 0.9, 'ett_reached': ett, 'n_unreachable': 1,
            'unreachable_incumbent_mean': 0.8, 'n_scenarios': 100, 'mode': 'exhaustive',
            'n_kills': kills, 'n_false_kills': int(fkr * kills), 'false_kill_rate': fkr}


def _entry(kind, kill, base, variants=None, envelope=None, k=3):
    return {'kind': kind, 'k': k, 'per_seed_budget': 100.0 / k,
            'kill_params': kill, 'n_eligible': 6, 'envelope': envelope,
            'uplift_q95': 0.005, 'base': base, 'variants': variants}


def test_recommend_strategy_criteria():
    """AC#3：双达标筛选（base/变体 ETT 不劣于单 seed + 误杀率 <5%）+ 参数同构。"""
    env = {'0.20': 0.72, '1.00': 0.86}
    entries = {
        'single': _entry('baseline', None, _metrics(100.0, kills=0),
                         _metrics(120.0, kills=0)),
        'kill_a': _entry('kill', {'tau0': 0.2, 'W': 5.0, 'm': 0.01},
                         _metrics(60.0), _metrics(80.0), env),
        'kill_b': _entry('kill', {'tau0': 0.1, 'W': 3.0, 'm': 0.02},
                         _metrics(50.0), _metrics(130.0), env),   # 变体劣于基线 → 排除
        'kill_c': _entry('kill', {'tau0': 0.3, 'W': 10.0, 'm': 0.005},
                         _metrics(55.0, fkr=0.06), _metrics(90.0, fkr=0.06), env),
        'theta_x': _entry('theta', {'tau0': 0.2, 'W': 5.0, 'm': 0.01, 'delta': 0.005,
                                    'm_streak': 2}, _metrics(70.0), _metrics(100.0),
                          env, k=4),                        # 误杀率 >=5% → 排除
    }
    rec = recommend_strategy(entries, target=TARGET, source='simulate:t', has_variants=True)
    assert rec['strategy'] == 'kill_a'                    # 合格者中 base ETT 最小
    assert rec['qualified'] == ['kill_a', 'theta_x']
    assert rec['ett_gain_base'] == pytest.approx(0.4)
    p = rec['params']
    assert p['calibrated'] is True and p['target'] == TARGET
    assert {'tau0', 'W', 'm', 'epsilon', 'delta', 'm_streak', 'uplift_q95',
            'envelope'} <= set(p)                          # controller_params.json 同构
    assert p['tau0'] == 0.2 and p['envelope'] == env
    assert p['epsilon'] == KILL_DEFAULTS['epsilon']        # 未列键回落保守默认
    assert p['n_seeds'] == 3 and p['per_seed_time'] == pytest.approx(100.0 / 3)
    # 单 seed 基线无数据 → 不硬推
    bad = {'single': _entry('baseline', None, None)}
    assert recommend_strategy(bad, target=TARGET, source='s',
                              has_variants=False)['strategy'] is None
    # 无合格档 → None + note
    worse = {'single': _entry('baseline', None, _metrics(10.0, kills=0)),
             'kill_z': _entry('kill', {'tau0': 0.2}, _metrics(50.0))}
    r2 = recommend_strategy(worse, target=TARGET, source='s', has_variants=False)
    assert r2['strategy'] is None and '无档位' in r2['note']


# ------------------------------------------------------- shadow 日志统计（纯）

# 行分隔符经 chr(10) 构造（避免源码里的反斜杠转义序列歧义）。
_NL = chr(10)


def _write_shadow_dir(root: Path, curves: dict) -> Path:
    log = root / 'kill_decisions.jsonl'
    lines = [
        {'t': 25.0, 'seed': 2, 'rule': 'R1_envelope', 'd': 0.55, 'tau': 0.25,
         'S_tau': 0.72, 'theta': 0.85, 'I': 0.8, 'would_kill': True},
        {'t': 30.0, 'seed': 3, 'rule': 'R2_compression_verdict', 'd': 0.5, 'tau': 0.3,
         'S_tau': None, 'theta': 0.85, 'I': 0.8, 'would_kill': True},
        {'t': 40.0, 'seed': 4, 'rule': 'R1_envelope', 'd': 0.55, 'tau': 0.4,
         'S_tau': 0.73, 'theta': 0.85, 'I': 0.8, 'would_kill': True},
        {'t': 50.0, 'seed': 5, 'rule': 'R1_envelope', 'd': 0.55, 'tau': 0.5,
         'S_tau': 0.73, 'theta': 0.85, 'I': 0.8, 'would_kill': False},
        '{"broken json',
    ]
    body = _NL.join(json.dumps(e) if isinstance(e, dict) else e for e in lines) + _NL
    log.write_text(body, encoding='utf-8')
    for seed, curve in curves.items():
        (root / f'curve_s{seed}.json').write_text(
            json.dumps(curve, ensure_ascii=False), encoding='utf-8')
    return log


def test_shadow_log_stats(tmp_path):
    """would-kill 假阳性：决策后达标=假阳性、不达标=正确、缺曲线不计率、分桶。"""
    late = _mk_curve([(10, 0.5), (30, 0.55), (50, 0.87), (100, 0.87)])  # 50s 才达标
    log = _write_shadow_dir(tmp_path, {2: _doomed(), 3: late})          # seed4 无曲线
    st = shadow_log_stats(log, TARGET)
    assert st['n_lines'] == 5 and st['n_bad_json'] == 1
    assert st['n_would_kill'] == 3                       # would_kill=False 不计
    assert st['n_evaluated'] == 2 and st['n_no_curve'] == 1
    assert st['n_false_positive'] == 1                   # seed3 假阳性；seed2 正确
    assert st['false_positive_rate'] == pytest.approx(0.5)
    assert st['by_rule']['R1_envelope']['false_positive'] == 0
    assert st['by_rule']['R2_compression_verdict']['false_positive_rate'] == 1.0
    with pytest.raises(cal.CalibrationError):
        shadow_log_stats(tmp_path / 'nope.jsonl', TARGET)


def _seed_sim_tag(cal_root: Path, tag: str = 'sim1') -> Path:
    """仿真 tag 目录：base/short 6 seed（3 reacher + 3 doomed）+ variant_0 4 条。

    曲线原生时长 100s（--budget 缺省 = 100）；doomed 起点略低于 reacher 平台，
    激进 kill 明显占优的分离度。
    """
    groups = {'base': {i: (_reacher() if i < 3 else _doomed()) for i in range(6)},
              'variant_0': {i: (_reacher() if i < 2 else _doomed(offset=0.56))
                            for i in range(4)}}
    for grp, curves in groups.items():
        grp_dir = cal_root / tag / grp / 'short'
        grp_dir.mkdir(parents=True, exist_ok=True)
        for seed, curve in curves.items():
            (grp_dir / f'curve_s{seed}.json').write_text(
                json.dumps(curve, ensure_ascii=False), encoding='utf-8')
    return cal_root / tag


def test_cli_simulate_end_to_end(iso_env):
    """rc=0 + 表格/推荐/报告路径 + 报告结构 + 同输入两次运行逐字节一致。"""
    tmp_path, cal_root = iso_env
    _seed_sim_tag(cal_root)
    rc, out, err = _run(['simulate', '--tag', 'sim1', '--target', str(TARGET)])
    assert rc == 0, err
    assert '总预算 100s' in out and 'base 曲线 6 条' in out
    assert '变体曲线 4 条（held-out）' in out
    for name in ('single', 'best_of_3', 'kill_aggressive', 'theta_slow'):
        assert name in out
    assert '[simulate] 推荐: ' in out and '报告: ' in out

    rep = json.loads((cal_root / 'sim1' / 'analysis' / 'simulation_report.json')
                     .read_text(encoding='utf-8'))
    assert rep['target'] == TARGET and rep['total_budget'] == 100.0
    assert list(rep['strategies']) == [s['name'] for s in SIM_STRATEGY_GRID]
    for st in rep['strategies'].values():
        assert st['base'] is not None and st['variants'] is not None
        for m in (st['base'], st['variants']):
            assert m['ett'] > 0 and 0.0 <= m['p_reach'] <= 1.0
    rec = rep['recommendation']
    assert rec['strategy'] is not None
    assert rec['strategy'] in ('kill_conservative', 'kill_moderate',
                               'kill_aggressive', 'theta_fast', 'theta_slow')
    assert rec['ett_base'] < rec['ett_baseline_base']      # 优于单 seed 基线
    assert rec['false_kill_rate_base'] == 0.0              # 合成池无迟达标者
    p = rec['params']
    assert p['calibrated'] is True and p['envelope']
    assert p['n_seeds'] == rep['strategies'][rec['strategy']]['k']
    assert p['per_seed_time'] == pytest.approx(100.0 / p['n_seeds'], rel=1e-3)
    assert p['target'] == TARGET and p['source'].startswith('simulate:')

    # 确定性：同输入两次运行，除 generated 外逐字节一致。
    _run(['simulate', '--tag', 'sim1', '--target', str(TARGET)])
    rep2 = json.loads((cal_root / 'sim1' / 'analysis' / 'simulation_report.json')
                      .read_text(encoding='utf-8'))
    rep.pop('generated')
    rep2.pop('generated')
    assert rep == rep2


def test_cli_simulate_budget_eligibility(iso_env):
    """预算超全部曲线原生时长 → 单 seed 基线无数据不推荐；小预算可推荐。"""
    tmp_path, cal_root = iso_env
    _seed_sim_tag(cal_root)
    rc, out, err = _run(['simulate', '--tag', 'sim1', '--target', str(TARGET),
                         '--budget', '200'])
    assert rc == 0, err
    rep = json.loads((cal_root / 'sim1' / 'analysis' / 'simulation_report.json')
                     .read_text(encoding='utf-8'))
    assert rep['strategies']['single']['base'] is None
    assert 'eligible=0' in rep['strategies']['single']['note']
    assert rep['recommendation']['strategy'] is None

    rc, out, err = _run(['simulate', '--tag', 'sim1', '--target', str(TARGET),
                         '--budget', '60', '--scenarios', '100'])
    assert rc == 0, err
    assert ('[simulate] 推荐: kill_' in out) or ('[simulate] 推荐: theta_' in out)
    rep60 = json.loads((cal_root / 'sim1' / 'analysis' / 'simulation_report.json')
                       .read_text(encoding='utf-8'))
    assert all(st['base'] is not None for st in rep60['strategies'].values())


def test_cli_simulate_with_shadow_log(iso_env):
    """--shadow-log：真实 would-kill 假阳性统计进报告与控制台。"""
    tmp_path, cal_root = iso_env
    _seed_sim_tag(cal_root)
    late = _mk_curve([(10, 0.5), (30, 0.55), (50, 0.87), (100, 0.87)])
    log = _write_shadow_dir(cal_root / 'sim1', {2: _doomed(), 3: late})
    rc, out, err = _run(['simulate', '--tag', 'sim1', '--target', str(TARGET),
                         '--shadow-log', str(log)])
    assert rc == 0, err
    assert 'shadow 日志: 3 条 would-kill' in out
    assert '假阳性 1（50.0%）' in out
    rep = json.loads((cal_root / 'sim1' / 'analysis' / 'simulation_report.json')
                     .read_text(encoding='utf-8'))
    assert rep['shadow_log']['n_evaluated'] == 2
    assert rep['shadow_log']['false_positive_rate'] == pytest.approx(0.5)


def test_cli_simulate_errors(iso_env):
    tmp_path, cal_root = iso_env
    _seed_sim_tag(cal_root)
    bad_argv = [
        ['simulate', '--tag', 'sim1', '--target', '0'],             # target 越界
        ['simulate', '--tag', 'sim1', '--target', str(TARGET),
         '--env-quantile', '0.9'],
        ['simulate', '--tag', 'sim1', '--target', str(TARGET), '--scenarios', '0'],
        ['simulate', '--tag', 'sim1', '--target', str(TARGET), '--budget', '0'],
        ['simulate', '--tag', 'nope', '--target', str(TARGET)],     # tag 无曲线
    ]
    for argv in bad_argv:
        rc, out, err = _run(argv)
        assert rc == 1, (argv, out, err)
        assert '配置错误' in err or '标定错误' in err
        assert not (cal_root / 'nope' / 'analysis').exists()
    # 缺 --tag / 缺 --target：argparse 自身报错（exit 2，非配置错误路径）。
    with pytest.raises(SystemExit) as ei:
        _run(['simulate', '--target', str(TARGET)])
    assert ei.value.code == 2


def test_module_help_smoke():
    """``python -m materialsorting.cli.calibration simulate --help`` 跑通（AC#4）。"""
    import os
    env = {**os.environ, 'PYTHONPATH': str(_SRC)}
    r = subprocess.run(
        [sys.executable, '-m', 'materialsorting.cli.calibration',
         'simulate', '--help'],
        capture_output=True, env=env, cwd=str(_SRC.parent), timeout=60)
    assert r.returncode == 0, r.stderr
    assert b'usage' in r.stdout.lower()
    assert b'--shadow-log' in r.stdout


def test_simulate_tag_pool_contract(iso_env):
    """simulate_tag 返回值契约：pools 统计 + k×B ≈ 总预算 + 报告路径。"""
    tmp_path, cal_root = iso_env
    tag_dir = _seed_sim_tag(cal_root)
    result = simulate_tag(tag_dir, TARGET)
    rep, path = result['report'], result['path']
    assert rep['pools']['base'] == {'n_curves': 6, 'short': 6, 'full': 0}
    assert rep['pools']['variants'] == {'n_curves': 4,
                                        'by_variant': {'variant_0': 4}}
    for st in rep['strategies'].values():
        assert st['k'] * st['per_seed_budget'] == pytest.approx(
            rep['total_budget'], abs=0.05)
    assert path.endswith('simulation_report.json')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
