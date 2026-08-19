"""PC-003 ``cli/portfolio`` kill 引擎（R1/R2/R3 + shadow mode）测试。

驱动方式：**fake solve**（3 元组轨迹 ``(elapsed, density, phase)``）+ 控制器直驱
（``make_progress`` / ``make_should_stop`` 手动投帧），覆盖：

  - 纯函数判据：``r1_below_envelope`` / ``r2_below_threshold`` 边界（等值不杀 /
    incumbent 缺席退化 θ / max(θ, I+ε) 门槛选取）；
  - ``make_envelope`` 阶梯查表（网格前 None / 空与非法 → None 即 R1 禁用）；
  - ``resolve_kill_params`` 覆盖矩阵（未知 / 负值 / bool / 字符串一律回退默认）；
  - seed 1 豁免（锚定交付下限 + 校准样本，豁免看队列序号不看 seed 值）；
  - R0 恒用 --target 真值（θ 衰减后达标仍停）；
  - R2 压缩首帧判决（exploring 不判 / 首 compressing 帧判 / 判过不复审 / uplift
    默认与 --params 覆盖）；
  - R3 连杀触发 θ 衰减且只影响后续 kill 判据（决策日志 theta 字段留痕）/ 单调
    只降（I+δ 抬不过 θ）/ 非 kill 结束清零连杀；
  - R1 W 秒迟滞（瞬时下探不杀 / 持续 W 秒杀 / τ0 门限）；
  - shadow 绝不终止求解（should_stop 仅 R0 触发）+ 决策记录字段完整；
  - on 模式真杀：killed=True + kill_reason，best 帧仍入 incumbent（PC-002 联动）；
  - CLI ``--kill``：on 无标定自动降级 shadow 并 warn / on + calibrated 真杀 /
    off 不落 kill_decisions.jsonl / 无 --target 引擎不激活。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.cli.portfolio import (KILL_DEFAULTS, R0_REASON, R1_REASON,
                                           R2_REASON, PortfolioController,
                                           make_envelope, r1_below_envelope,
                                           r2_below_threshold,
                                           resolve_kill_params,
                                           run_serial_portfolio)
from materialsorting.cli.run_config import main
from materialsorting.web import server as server_mod

_SYNTH_BLOCKS = [
    ('blk x.28', (0.12345, 0.6789, 400.123456, 700.987654)),
    ('blk x.29', (0.12345, 0.6789, 400.123456, 720.987654)),
    ('zz 9.28', (1.5, 2.25, 200.111111, 90.222222)),
    ('zz 9.29', (1.5, 2.25, 200.111111, 95.222222)),
]
_N_PIECES = len(_SYNTH_BLOCKS)


@pytest.fixture
def iso_env(tmp_path, monkeypatch):
    """隔离环境（CONFIG_RUNS_DIR / INTERMEDIATE / uploads 全指 tmp）+ 合成母版。"""
    runs = tmp_path / 'config_runs'
    runs.mkdir()
    inter = tmp_path / 'web_intermediate.json'
    inter.write_text('{"sentinel": true}', encoding='utf-8')
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(runs))
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE', str(inter))
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', uploads)
    doc = ezdxf.new('R12')
    for name, (x, y, w, h) in _SYNTH_BLOCKS:
        blk = doc.blocks.new(name=name)
        poly = blk.add_polyline2d(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], dxfattribs={'layer': '1'})
        poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
    master = tmp_path / 'synthetic_master.dxf'
    doc.saveas(str(master))
    cfg = tmp_path / 'cfg.json'
    cfg.write_text(json.dumps(
        {'master_dxf': str(master), 'gate_mm': 1980, 'time': 2, 'seeds': [0, 1]},
        ensure_ascii=False), encoding='utf-8')
    return tmp_path, runs, cfg


def _frame(seed: int, idx: int, elapsed: float, density: float, phase: str) -> dict:
    return {
        'type': 'frame', 'elapsed': float(elapsed), 'phase': phase,
        'density': float(density), 'density_sparrow': float(density) + 0.02,
        'width_mm': 50000.0 - float(seed) * 1000.0 - float(idx) * 10.0,
        'placed_items': [
            {'id': f'g0{k + 1}_28', 'rotation': 0.0,
             'translation': [float(seed * 10000 + idx * 100 + k), 0.0]}
            for k in range(_N_PIECES)],
    }


def _fake_solve_ph(trajs, *, calls=None, verdicts=None):
    """3 元组轨迹 fake solve（契约镜像 solve_pieces：on_progress 先于 should_stop）。

    ``verdicts`` 给定时逐帧记录 ``(seed, verdict)`` —— shadow 断言「should_stop
    仅由 R0 触发（其余恒 falsy）」用。
    """
    def solve(cfg, run_dir, *, seed, time_budget=None, on_progress=None,
              should_stop=None, **kw):
        if calls is not None:
            calls.append(seed)
        frames: list[dict] = []
        for idx, (elapsed, d, phase) in enumerate(trajs[seed]):
            fr = _frame(seed, idx, elapsed, d, phase)
            frames.append(fr)
            if on_progress is not None:
                on_progress(fr)
            if should_stop is not None:
                verdict = should_stop(fr)
                if verdicts is not None:
                    verdicts.append((seed, verdict))
                if verdict:
                    best = max(frames, key=lambda f: f['density'])
                    return {'seed': seed, 'n_items': _N_PIECES, 'n_eroded': 0,
                            'total_area_mm2': 1_000_000.0,
                            'width_mm': best['width_mm'],
                            'real_density': best['density'],
                            'density_sparrow': best['density_sparrow'],
                            'placed_items': _N_PIECES, 'elapsed': best['elapsed'],
                            'killed': True,
                            'kill_reason': verdict if isinstance(verdict, str)
                            else 'should_stop'}
        final = frames[-1]
        return {'seed': seed, 'n_items': _N_PIECES, 'n_eroded': 0,
                'total_area_mm2': 1_000_000.0, 'width_mm': final['width_mm'],
                'real_density': final['density'],
                'density_sparrow': final['density_sparrow'],
                'placed_items': _N_PIECES, 'elapsed': final['elapsed']}
    return solve


def _run_kill(trajs, seeds, *, target, params=None, kill='shadow', echo=None,
              notify=None, time_budget=100.0, verdicts=None):
    decisions: list[dict] = []
    ctl = PortfolioController(seeds=seeds, target=target, params=params, echo=echo,
                              kill=kill, time_budget=time_budget, notify=notify,
                              on_decision=decisions.append)
    run = run_serial_portfolio(
        None, None, controller=ctl, time_budget=time_budget,
        solve=_fake_solve_ph(trajs, verdicts=verdicts))
    return run, decisions


def _drive(ctl, seed, index, frames):
    """控制器直驱：手动投帧（on_progress → should_stop），返回全部 should_stop 判定。"""
    prog = ctl.make_progress(seed, index=index)
    stop = ctl.make_should_stop(seed, index=index)
    out = []
    for fr in frames:
        prog(fr)
        out.append(stop(fr))
    return out


def _fr(elapsed, density, phase='exploring'):
    return {'elapsed': float(elapsed), 'phase': phase, 'density': float(density),
            'density_sparrow': float(density) + 0.02, 'width_mm': 50000.0,
            'placed_items': []}


# ------------------------------------------------------- 纯函数判据（AC#1）


def test_pure_r1_below_envelope_boundaries():
    """R1 纯判据：严格小于才 below；S(τ)=None（无标定/网格前）恒不 below。

    数值取二进制精确（dyadic）避免 0.80-0.005 类十进制边界的浮点歧义。
    """
    assert r1_below_envelope(0.5, 1.0, 0.5) is False       # 等值（S−m）不杀
    assert r1_below_envelope(0.4375, 1.0, 0.5) is True     # 严格小于余量线
    assert r1_below_envelope(0.10, None, 0.005) is False   # 无包络 → R1 不可评估
    assert r1_below_envelope(0.10, 0.80, 0.9) is False     # 余量大于包络 → 恒不杀


def test_pure_r2_below_threshold_boundaries():
    """R2 纯判据：门槛 = max(θ, I+ε)；I 缺席退化 θ；严格小于才杀。

    数值取二进制精确（dyadic）避免 0.82+0.001 类十进制边界的浮点歧义。
    """
    # I+ε（0.75+0.125=0.875）> θ（0.5）→ 门槛取 I+ε
    assert r2_below_threshold(0.5, 0.25, 0.5, 0.75, 0.125) is True    # 0.75 < 0.875
    assert r2_below_threshold(0.625, 0.25, 0.5, 0.75, 0.125) is False  # 0.875 等值不杀
    # θ（0.875）> I+ε（0.625）→ 门槛取 θ
    assert r2_below_threshold(0.5, 0.25, 0.875, 0.5, 0.125) is True
    assert r2_below_threshold(0.625, 0.25, 0.875, 0.5, 0.125) is False
    # incumbent 缺席 → 门槛退化为 θ
    assert r2_below_threshold(0.5, 0.25, 0.875, None, 0.125) is True
    assert r2_below_threshold(0.625, 0.25, 0.875, None, 0.125) is False


def test_make_envelope_step_lookup():
    """S(τ) 阶梯查表：最大网格点 ≤ τ；网格前 None；空/全非法/非 dict → None。"""
    s = make_envelope({'envelope': {'0.3': 0.80, '0.4': 0.85}})
    assert s(0.29) is None and s(0.3) == pytest.approx(0.80)
    assert s(0.35) == pytest.approx(0.80) and s(0.4) == pytest.approx(0.85)
    assert s(0.41) == pytest.approx(0.85) and s(1.2) == pytest.approx(0.85)
    assert make_envelope({}) is None                          # 无 envelope 键
    assert make_envelope({'envelope': {}}) is None            # 空
    assert make_envelope({'envelope': {'a': 'b'}}) is None    # 全非法数值
    assert make_envelope({'envelope': [0.8]}) is None         # 非 dict


def test_resolve_kill_params_overrides():
    """--params 数值覆盖：合法数值生效；负值 / bool / 字符串 / 未知键回退默认。"""
    merged = resolve_kill_params({'tau0': 0.5, 'W': 20, 'm': -1, 'epsilon': 'x',
                                  'delta': True, 'uplift_q95': 0.02, 'hack': 9})
    assert merged['tau0'] == 0.5 and merged['W'] == 20.0
    assert merged['uplift_q95'] == 0.02
    assert merged['m'] == KILL_DEFAULTS['m']                  # 负值回退
    assert merged['epsilon'] == KILL_DEFAULTS['epsilon']      # 字符串回退
    assert merged['delta'] == KILL_DEFAULTS['delta']          # bool 回退
    assert merged['m_streak'] == KILL_DEFAULTS['m_streak']
    assert 'hack' not in merged


# --------------------------------------------- seed 1 豁免 / R0 不受 θ 影响


def test_seed1_exempt_by_queue_index_not_seed_value():
    """AC#1：seed 1（队列首）永不 kill —— 豁免看队列序号不看 seed 值：同样的必死
    轨迹，第 1 个 seed 跑满，第 2 个被 R2 淘汰。"""
    traj = {7: [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')],
            9: [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')]}
    run, decisions = _run_kill(traj, [7, 9], target=0.9, kill='on')
    assert 'killed' not in run.solves[0]                      # 队列首豁免（seed=7）
    assert run.solves[1]['killed'] is True
    assert run.solves[1]['kill_reason'] == R2_REASON          # seed=9（队列第 2）
    assert [e['seed'] for e in decisions] == [9]


def test_r0_uses_real_target_despite_theta_decay():
    """AC#1：θ 衰减只降 kill 门槛 —— θ=82.3% 后 90% 帧仍触发 R0（恒用 --target）。"""
    traj = {0: [(5, 0.80, 'exploring'), (10, 0.82, 'compressing')],   # 队列首：跑满
            1: [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')],    # R2 kill
            2: [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')],    # R2 kill → streak=2
            3: [(5, 0.90, 'exploring')]}                             # R0 达标
    run, _ = _run_kill(traj, [0, 1, 2, 3], target=0.9, kill='on',
                       params={'m_streak': 2})
    assert run.controller.theta == pytest.approx(0.823)        # min(0.9, 0.82+δ)
    assert len(run.controller.theta_history) == 1
    assert run.solves[3]['killed'] is True
    assert run.solves[3]['kill_reason'] == R0_REASON           # 不是 kill 规则
    assert run.controller.queue_stopped is True


# ------------------------------------------------------- R2 压缩首帧判决


def test_r2_only_first_compressing_frame_and_phase_gate():
    """AC#1：R2 只在首帧 phase=='compressing' 判决 —— exploring 期同样必死不判；
    判过（无论杀否）不再复审（后续 compressing 帧不产生新决策）。"""
    ctl = PortfolioController(seeds=[9], target=0.9, kill='shadow', time_budget=100)
    verdicts = _drive(ctl, 9, index=2, frames=[
        _fr(5, 0.60, 'exploring'),      # 必死但 exploring：不判 R2
        _fr(8, 0.61, 'exploring'),
        _fr(10, 0.61, 'compressing'),   # 首压缩帧：判决（shadow 只记）
        _fr(15, 0.62, 'compressing'),   # 已判过：不复审（无第二条决策）
        _fr(20, 0.62, 'exploring'),
    ])
    assert verdicts == [False, False, False, False, False]    # shadow 绝不触发
    assert [(e['rule'], e['t']) for e in ctl.kill_decisions] == [(R2_REASON, 10.0)]


def test_r2_uplift_default_and_params_override():
    """R2 uplift：无标定用保守默认 0.005（0.845 < 0.9 杀）；--params 覆盖放大后
    同帧不再必死（0.84+0.1=0.94 ≥ 0.9 不杀）。"""
    traj_kill = {0: [(5, 0.80, 'exploring')],
                 1: [(5, 0.84, 'exploring'), (8, 0.84, 'compressing')]}
    run, decisions = _run_kill(traj_kill, [0, 1], target=0.9, kill='on')
    assert run.solves[1]['kill_reason'] == R2_REASON           # 0.845 < 0.9

    run2, decisions2 = _run_kill(traj_kill, [0, 1], target=0.9, kill='on',
                                 params={'uplift_q95': 0.1})
    assert 'killed' not in run2.solves[1]                      # 0.94 ≥ 0.9：存活
    assert decisions2 == []


# ------------------------------------------------------- R3 θ 衰减


def test_r3_decay_after_streak_only_affects_later_judgments():
    """AC#1：连杀 m_streak=3 才衰减；衰减前判决的 θ 留痕 0.9；衰减后同分位 seed
    （0.82+uplift=0.825 vs 新门槛 max(0.823, I+ε)=0.823）存活 —— 只影响后续判据。"""
    hopeless = [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')]
    traj = {10: [(5, 0.80, 'exploring'), (10, 0.82, 'compressing')],  # 队列首跑满
            11: hopeless, 12: hopeless, 13: hopeless,                 # 三连杀
            14: [(5, 0.82, 'exploring'), (8, 0.82, 'compressing')]}   # 衰减后存活
    notify: list[str] = []
    run, decisions = _run_kill(traj, [10, 11, 12, 13, 14], target=0.9,
                               kill='on', notify=notify.append)
    assert [r['seed'] for r in run.solves if r.get('killed')] == [11, 12, 13]
    assert all(e['theta'] == pytest.approx(0.9) for e in decisions)   # 判决时 θ 未衰减
    assert 'killed' not in run.solves[4]                      # seed 14：0.825 ≥ 0.823 存活
    th = run.controller.theta_history
    assert len(th) == 1 and th[0]['after_seed'] == 13 and th[0]['kill_streak'] == 3
    assert th[0]['theta_old'] == pytest.approx(0.9)
    assert th[0]['theta'] == pytest.approx(0.823)
    assert th[0]['incumbent'] == pytest.approx(0.82)
    assert run.controller.theta == pytest.approx(0.823)
    assert len(notify) == 1 and 'θ 衰减' in notify[0] and '82.30%' in notify[0]


def test_r3_monotone_no_raise_and_streak_reset():
    """R3：I+δ 抬不过 θ（min 单调只降，无 history 条目）；非 kill 结束清零连杀
    （kill×2 → 跑满 → kill×2 不触发衰减）。"""
    # I=0.899 → I+δ=0.902 > θ=0.9：不抬
    traj = {0: [(5, 0.899, 'exploring'), (10, 0.899, 'compressing')],
            1: [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')],
            2: [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')],
            3: [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')]}
    run, _ = _run_kill(traj, [0, 1, 2, 3], target=0.9, kill='on')
    assert run.controller.theta == pytest.approx(0.9)          # 不抬
    assert run.controller.theta_history == []

    # kill, kill, 跑满, kill, kill：连杀被跑满打断 → 不衰减
    traj2 = {0: [(5, 0.80, 'exploring')],
             1: [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')],
             2: [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')],
             3: [(5, 0.83, 'exploring'), (9, 0.83, 'exploring')],   # 跑满（0.835<0.9）
             4: [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')],
             5: [(5, 0.60, 'exploring'), (8, 0.61, 'compressing')]}
    run2, _ = _run_kill(traj2, [0, 1, 2, 3, 4, 5], target=0.9, kill='on')
    assert run2.controller.theta == pytest.approx(0.9)         # streak 未达 3
    assert run2.controller.theta_history == []


# ------------------------------------------------------- R1 包络 + 迟滞


def test_r1_sustained_window_kills():
    """R1：包络下方持续 ≥ W 秒才杀（τ>τ0 前置；决策在窗口满足的那一帧）。"""
    traj = {0: [(5, 0.80, 'exploring')],
            1: [(32, 0.70, 'exploring'),     # τ=0.32>0.3，0.70 < 0.80-0.005：起表
                (38, 0.71, 'exploring'),     # 6s < W：不杀
                (43, 0.71, 'exploring')]}    # 11s ≥ W=10：杀
    run, decisions = _run_kill(traj, [0, 1], target=0.9, kill='on',
                               params={'envelope': {'0.3': 0.80}})
    assert run.solves[1]['killed'] is True
    assert run.solves[1]['kill_reason'] == R1_REASON
    assert len(decisions) == 1 and decisions[0]['t'] == 43.0


def test_r1_transient_dip_no_kill():
    """AC#1：W 秒迟滞 —— 瞬时下探（4s 内追平包络）不杀，随后也不翻旧账。"""
    traj = {0: [(5, 0.80, 'exploring')],
            1: [(32, 0.70, 'exploring'),     # 包络下方起表
                (36, 0.80, 'exploring'),     # 4s 后追平：计时清零
                (99, 0.80, 'exploring')]}    # 跑满：永不杀
    run, decisions = _run_kill(traj, [0, 1], target=0.9, kill='on',
                               params={'envelope': {'0.3': 0.80}})
    assert 'killed' not in run.solves[1]
    assert decisions == []


def test_r1_tau0_gate_and_no_calibration_disable():
    """AC#1：τ ≤ τ0 不评估（即便在包络下方）；无标定 envelope 时 R1 整体禁用。"""
    traj_tau = {0: [(5, 0.80, 'exploring')],
                1: [(30, 0.70, 'exploring'),   # τ=0.30 不 > τ0：不评估
                    (35, 0.80, 'exploring'),   # 追平（此后 d 单调不再下探）
                    (90, 0.80, 'exploring')]}
    run, _ = _run_kill(traj_tau, [0, 1], target=0.9, kill='on',
                       params={'envelope': {'0.3': 0.80}})
    assert 'killed' not in run.solves[1]

    traj_hopeless = {0: [(5, 0.80, 'exploring')],
                     1: [(32, 0.10, 'exploring'), (60, 0.10, 'exploring'),
                         (99, 0.10, 'exploring')]}
    run2, decisions2 = _run_kill(traj_hopeless, [0, 1], target=0.9, kill='on')
    assert 'killed' not in run2.solves[1]                     # 无标定 → R1 禁用
    assert decisions2 == []


# ------------------------------------------------------- shadow / 决策记录（AC#2）


def test_shadow_never_stops_solve_and_logs_full_entries():
    """AC#2：shadow 绝不终止求解（should_stop 全程 falsy，仅 R0 才会真值）；决策
    记录字段完整 {t, seed, rule, d, tau, S_tau, theta, I, would_kill}。"""
    traj = {0: [(5, 0.80, 'exploring')],
            1: [(32, 0.70, 'exploring'), (38, 0.71, 'exploring'),
                (43, 0.71, 'exploring'), (90, 0.72, 'exploring')]}
    verdicts: list = []
    run, decisions = _run_kill(traj, [0, 1], target=0.99, kill='shadow',
                               params={'envelope': {'0.3': 0.80}}, verdicts=verdicts)
    assert 'killed' not in run.solves[1]                      # 跑满 4 帧
    assert run.solves[1]['elapsed'] == 90.0                   # 末帧交付（未被终止）
    assert all(not v for _s, v in verdicts)                   # shadow：恒 falsy
    assert run.controller.queue_stopped is False
    assert len(decisions) == 1                                # (seed, rule) 去重
    e = decisions[0]
    assert set(e) == {'t', 'seed', 'rule', 'd', 'tau', 'S_tau', 'theta', 'I',
                      'would_kill'}
    assert e['t'] == 43.0 and e['seed'] == 1 and e['rule'] == R1_REASON
    assert e['d'] == pytest.approx(0.71)                      # best-so-far
    assert e['tau'] == pytest.approx(0.43)
    assert e['S_tau'] == pytest.approx(0.80)
    assert e['theta'] == pytest.approx(0.99) and e['I'] == pytest.approx(0.80)
    assert e['would_kill'] is True


def test_on_mode_killed_seed_best_frame_joins_incumbent():
    """AC#3（PC-002 联动）：被 kill 的 seed 记录 killed=True + kill_reason，其
    best 帧仍入 incumbent（帧峰 0.84 > 队列首 0.80）。"""
    traj = {0: [(5, 0.80, 'exploring')],
            1: [(5, 0.84, 'exploring'),      # 帧峰（先入账）
                (10, 0.62, 'compressing')]}  # R2 判决帧（best-so-far 仍 0.84）
    run, _ = _run_kill(traj, [0, 1], target=0.9, kill='on')
    rec = run.solves[1]
    assert rec['killed'] is True and rec['kill_reason'] == R2_REASON
    assert rec['real_density'] == pytest.approx(0.84)         # best-so-far 交付
    inc = run.controller.incumbent
    assert inc['seed'] == 1 and inc['frame_index'] == 0       # 被 kill seed 的帧峰
    assert inc['density'] == pytest.approx(0.84)
    ps = run.controller.per_seed[1]
    assert ps['killed'] is True and ps['kill_reason'] == R2_REASON
    assert ps['best_density'] == pytest.approx(0.84)


# ------------------------------------------------------- CLI --kill 旗标（AC#2）


def _patch(monkeypatch, trajs):
    from materialsorting.cli import run_config as rc_mod
    monkeypatch.setattr(rc_mod, 'solve_pieces', _fake_solve_ph(trajs))


def test_main_kill_on_without_calibration_degrades_to_shadow(iso_env, capsys,
                                                             monkeypatch):
    """AC#1：--kill on 无标定参数 → 自动降级 shadow（stderr warn）+ 引擎只记不杀。"""
    tmp, runs, cfg = iso_env
    traj = {0: [(5, 0.80, 'exploring')],
            1: [(32, 0.70, 'exploring'), (45, 0.70, 'compressing'),
                (90, 0.72, 'exploring')]}   # R2 判决帧（shadow 只记）
    _patch(monkeypatch, traj)
    rc = main([str(cfg), '--time', '100', '--target', '0.99', '--kill', 'on'])
    assert rc == 0
    err = capsys.readouterr().err
    assert '降级 shadow' in err and 'calibrated' in err
    (rd,) = list(runs.iterdir())
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert result['portfolio']['kill_mode'] == 'shadow'
    assert 'killed' not in result['solve'][1]                 # 降级后不真杀
    lines = (rd / 'kill_decisions.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(lines) >= 1                                    # 决策照记
    entry = json.loads(lines[0])
    assert set(entry) == {'t', 'seed', 'rule', 'd', 'tau', 'S_tau', 'theta', 'I',
                          'would_kill'}


def test_main_kill_on_with_calibration_really_kills(iso_env, capsys, monkeypatch):
    """--kill on + 标定就绪（calibrated: true + envelope）→ 真杀（R1 kill_reason）。"""
    tmp, runs, cfg = iso_env
    params = tmp / 'controller_params.json'
    params.write_text(json.dumps(
        {'calibrated': True, 'envelope': {'0.3': 0.80}}), encoding='utf-8')
    traj = {0: [(5, 0.80, 'exploring')],
            1: [(32, 0.70, 'exploring'), (45, 0.70, 'exploring'),   # 13s ≥ W=10
                (60, 0.71, 'exploring')]}
    _patch(monkeypatch, traj)
    rc = main([str(cfg), '--time', '100', '--target', '0.99', '--kill', 'on',
               '--params', str(params)])
    assert rc == 0
    cap = capsys.readouterr()                     # err + out 一次取全（二次读取为空）
    assert '降级' not in cap.err
    (rd,) = list(runs.iterdir())
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert result['portfolio']['kill_mode'] == 'on'
    assert result['solve'][1]['killed'] is True
    assert result['solve'][1]['kill_reason'] == R1_REASON
    lines = (rd / 'kill_decisions.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1 and json.loads(lines[0])['rule'] == R1_REASON
    assert '[kill] on 模式：1 条 kill 判定已写' in cap.out


def test_main_kill_off_and_default_shadow(iso_env, capsys, monkeypatch):
    """--kill off：不评估不落 kill_decisions.jsonl；缺省（无旗标）= shadow。"""
    tmp, runs, cfg = iso_env
    traj = {0: [(1.0, 0.60, 'exploring')]}
    _patch(monkeypatch, traj)
    rc = main([str(cfg), '--time', '2', '--target', '0.5', '--kill', 'off',
               '--name', 'offrun'])
    assert rc == 0
    (rd,) = list(runs.iterdir())
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert result['portfolio']['kill_mode'] == 'off'
    assert not (rd / 'kill_decisions.jsonl').exists()

    traj2 = {0: [(1.0, 0.60, 'exploring'), (2.0, 0.60, 'exploring')]}
    _patch(monkeypatch, traj2)
    rc2 = main([str(cfg), '--time', '2', '--target', '0.55', '--name', 'defrun'])
    assert rc2 == 0
    (rd2,) = [d for d in runs.iterdir() if d != rd]
    result2 = json.loads((rd2 / 'result.json').read_text(encoding='utf-8'))
    assert result2['portfolio']['kill_mode'] == 'shadow'      # 缺省 shadow
    assert (rd2 / 'kill_decisions.jsonl').exists()            # 空文件也在场
    assert (rd2 / 'kill_decisions.jsonl').read_text(encoding='utf-8') == ''


def test_main_kill_needs_target(iso_env, capsys, monkeypatch):
    """引擎仅 --target 给定时激活：--kill on 无 --target → stderr 提示 + off。"""
    tmp, runs, cfg = iso_env
    traj = {0: [(1.0, 0.60, 'exploring'), (2.0, 0.62, 'compressing')],
            1: [(1.0, 0.58, 'exploring'), (2.0, 0.59, 'compressing')]}
    _patch(monkeypatch, traj)
    rc = main([str(cfg), '--time', '2', '--kill', 'on'])
    assert rc == 0
    err = capsys.readouterr().err
    assert '--kill 需要 --target' in err
    (rd,) = list(runs.iterdir())
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert result['portfolio']['kill_mode'] == 'off'
    assert not (rd / 'kill_decisions.jsonl').exists()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
