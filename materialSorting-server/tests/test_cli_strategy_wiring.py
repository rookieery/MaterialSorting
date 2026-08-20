"""US-002 ``--strategy`` 双模式接线（run_config 旗标 + PortfolioController 消费 +
solve_pieces ``artifact_suffix``）。

覆盖三层：

  - **旗标裁决**（main 退出码矩阵）：--strategy 值域（choices 外退出 1 非
    argparse 的 2）/ 策略模式 --time 总预算必填 / 与 --kill 显式同给互斥 / 4 个
    参数旗标是从属旗标（单独给出退出 1）/ --race-gate (0,1) 开区间 / 预算不足
    （race_plan / se_plan 的 StrategyBudgetError → 退出 1，不留空 run_dir）；
  - **race 接线**（fake solve 帧协议：on_progress 先于 should_stop、终止交付
    best-so-far）：首 seed 豁免跑满、门杀决策行落 kill_decisions.jsonl（S_tau=bar
    参照、theta=null 重载）、被杀 best 参与 incumbent banking、名义记账收口
    （计划 seed 未启动）、--quiet 门杀行仍打、--target 共存 R0 优先；
  - **se 接线**：阶段 1 k 轮 screen 预算筛选 + 阶段 2 冠军（real_density argmax）
    同 seed 以 ext 预算延长（``_ext`` 产物防覆盖 + solve 条目 phase=extension），
    R0 提前停不进延长；
  - **零回归**：无 --strategy 时 result.json 不加 strategy/mode 键 + ``--help``
    含新旗标。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.cli.portfolio import (R5_REASON, STRATEGY_STARTUP_S,
                                           race_plan)
from materialsorting.cli.run_config import main
from materialsorting.web import server as server_mod

# 与 test_cli_run_config 同构的合成母版（6 片有码号 28/29 + 1 片 size=None）。
_SYNTH_BLOCKS = [
    ('blk x.28', (0.12345, 0.6789, 400.123456, 700.987654)),
    ('blk x.29', (0.12345, 0.6789, 400.123456, 720.987654)),
    ('zz 9.28', (1.5, 2.25, 200.111111, 90.222222)),
    ('zz 9.29', (1.5, 2.25, 200.111111, 95.222222)),
    ('M55#2 a.28', (2.75, 3.125, 120.333333, 60.444444)),
    ('M55#2 a.29', (2.75, 3.125, 120.333333, 65.444444)),
]


def _make_master_dxf(path: Path) -> Path:
    doc = ezdxf.new('R12')
    for name, (x, y, w, h) in _SYNTH_BLOCKS:
        blk = doc.blocks.new(name=name)
        poly = blk.add_polyline2d(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], dxfattribs={'layer': '1'})
        poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
        blk.add_line((x + 10, y + h / 2), (x + w - 10, y + h / 2), dxfattribs={'layer': '7'})
    blk = doc.blocks.new(name='noname nosize')
    poly = blk.add_polyline2d([(0, 0), (80, 0), (80, 50), (0, 50)], dxfattribs={'layer': '1'})
    poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
    doc.saveas(str(path))
    return path


def _write_config(path: Path, master: Path, **extra) -> Path:
    cfg = {'master_dxf': str(master), 'gate_mm': 1980, 'time': 2}
    cfg.update(extra)
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
    return path


@pytest.fixture
def iso_env(tmp_path, monkeypatch):
    """隔离环境：CONFIG_RUNS_DIR / INTERMEDIATE / uploads 全指到 tmp_path。"""
    runs = tmp_path / 'config_runs'
    runs.mkdir()
    inter = tmp_path / 'web_intermediate.json'
    inter.write_text('{"sentinel": true}', encoding='utf-8')
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(runs))
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE', str(inter))
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', uploads)
    master = _make_master_dxf(tmp_path / 'synthetic_master.dxf')
    return tmp_path, runs, inter, uploads, master


class _FakeSolve:
    """模拟 ``pipeline.solve_pieces`` 帧协议的 fake（monkeypatch 进 run_config）。

    逐帧 ``on_progress`` 先于 ``should_stop``（与 solve_pieces 的调用序一致 ——
    banking 先行，R0/门杀帧必在 incumbent 候选内）；should_stop 真值 → 该 seed
    以 best-so-far 帧交付（``killed=True`` + ``kill_reason``），后续帧不投；
    产物按 ``curve_s{seed}{suffix}.json`` / ``best_frame_s{seed}{suffix}.json``
    落盘（契约同形，供 ``_ext`` 防覆盖断言）。轨迹键 = ``(seed, suffix)``。
    """

    def __init__(self, traj: dict):
        self.traj = traj
        self.calls: list[tuple] = []
        self.strategy_json_at_first_solve: dict | None = None

    def __call__(self, cfg, run_dir, *, seed, time_budget=None, on_progress=None,
                 should_stop=None, solver_opts=None, artifact_suffix='', **kw):
        self.calls.append((int(seed), time_budget, artifact_suffix))
        rd = Path(run_dir)
        if len(self.calls) == 1:
            p = rd / 'strategy.json'      # R1：首轮求解开始时 strategy.json 已在场
            if p.exists():
                self.strategy_json_at_first_solve = json.loads(
                    p.read_text(encoding='utf-8'))
        frames = self.traj[(int(seed), artifact_suffix)]
        best = None                       # (frame_index, elapsed, density)
        reason = None
        walked: list[dict] = []
        for idx, (elapsed, density) in enumerate(frames):
            report = {'elapsed': elapsed, 'phase': 'exploring', 'density': density,
                      'density_sparrow': round(density - 0.01, 6), 'width_mm': 5000.0,
                      'placed_items': [{'pid': 'g01_28', 'x': elapsed, 'y': density}]}
            walked.append({'elapsed': elapsed, 'phase': 'exploring',
                           'density': density, 'width_mm': 5000.0})
            if on_progress is not None:
                on_progress(report)
            if best is None or density > best[2]:
                best = (idx, elapsed, density)
            if should_stop is not None and reason is None:
                verdict = should_stop(report)
                if verdict:
                    reason = verdict if isinstance(verdict, str) and verdict else 'should_stop'
                    break
        (rd / f'curve_s{seed}{artifact_suffix}.json').write_text(
            json.dumps(walked, ensure_ascii=False), encoding='utf-8')
        (rd / f'best_frame_s{seed}{artifact_suffix}.json').write_text(
            json.dumps({'seed': int(seed), 'frame_index': best[0], 'elapsed': best[1],
                        'density': best[2], 'width_mm': 5000.0,
                        'placed_items': [{'pid': 'g01_28'}]}, ensure_ascii=False),
            encoding='utf-8')
        rec = {'seed': int(seed), 'n_items': 6, 'n_eroded': 0, 'total_area_mm2': 1.0,
               'width_mm': 5000.0, 'density_sparrow': round(best[2] - 0.01, 6),
               'placed_items': len(walked), 'elapsed': float(frames[-1][0])}
        if reason is not None:
            rec.update({'real_density': best[2], 'killed': True,
                        'kill_reason': reason})
        else:
            rec['real_density'] = frames[-1][1]
        return rec


def _patch_solve(monkeypatch, traj) -> _FakeSolve:
    from materialsorting.cli import run_config as rc_mod
    fake = _FakeSolve(traj)
    monkeypatch.setattr(rc_mod, 'solve_pieces', fake)
    return fake


def _only_run_dir(runs: Path) -> Path:
    dirs = [d for d in runs.iterdir() if d.is_dir()]
    assert len(dirs) == 1
    return dirs[0]


def _read_kill_decisions(rd: Path) -> list[dict]:
    text = (rd / 'kill_decisions.jsonl').read_text(encoding='utf-8')
    return [json.loads(line) for line in text.splitlines() if line]


# ------------------------------------------------------- 旗标裁决（退出码矩阵）


def test_strategy_value_out_of_choices_exit_1(iso_env, capsys):
    """--strategy 值域手工校验（choices 外退出 1 而非 argparse 的 2），不留空 run_dir。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--strategy', 'bogus', '--time', '600'])
    assert rc == 1
    err = capsys.readouterr().err
    assert '--strategy 须为 se 或 race' in err and 'bogus' in err
    assert list(runs.iterdir()) == []              # 配置错误在 new_run_dir 之前拦下


def test_strategy_requires_total_budget_time(iso_env, capsys):
    """策略模式 --time = 总预算秒数且必填（缺省退出 1，错误信息明示）。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--strategy'])
    assert rc == 1
    assert '策略模式需 --time 总预算' in capsys.readouterr().err
    assert list(runs.iterdir()) == []


@pytest.mark.parametrize('mode_argv', [['--strategy', 'race'], ['--strategy', 'se']])
@pytest.mark.parametrize('kill', ['shadow', 'on', 'off'])
def test_strategy_kill_explicit_mutex_exit_1(iso_env, capsys, mode_argv, kill):
    """--strategy 与 --kill 显式同给退出 1（判据内建，R1/R2 引擎不评估）；
    缺省不传 --kill 的策略运行不受影响（默认 shadow 在策略模式下恒 off）。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), *mode_argv, '--time', '600', '--kill', kill])
    assert rc == 1
    assert '--strategy 与 --kill 互斥' in capsys.readouterr().err
    assert list(runs.iterdir()) == []


def test_strategy_subordinate_flags_require_strategy(iso_env, capsys):
    """4 个参数旗标是从属旗标：单独给出（无 --strategy）= 配置错误退出 1。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--se-screen', '30'])
    assert rc == 1
    assert '须与 --strategy 同给' in capsys.readouterr().err
    assert list(runs.iterdir()) == []


@pytest.mark.parametrize('gate', ['0', '1.0', '1.5', '-0.1'])
def test_race_gate_open_interval_exit_1(iso_env, capsys, gate):
    """--race-gate 须为 (0,1) 开区间（端点 0/1 也拒绝）。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--strategy', '--time', '600',
               '--race-budget', '60', '--race-gate', gate])
    assert rc == 1
    assert '--race-gate' in capsys.readouterr().err
    assert list(runs.iterdir()) == []


@pytest.mark.parametrize('argv_extra,expect_rc', [
    (['--strategy', '--time', '100'], 1),                   # 默认 180/0.5：需 ≥ 275
    (['--strategy', 'se', '--time', '100'], 1),             # 默认 90/180：需 ≥ 275
    (['--strategy', '--time', '274'], 1),                   # 边界：差 1s
    (['--strategy', '--time', '184', '--race-budget', '120'], 1),   # 122.5+62.5=185 > 184
])
def test_budget_insufficient_exit_1(iso_env, capsys, argv_extra, expect_rc):
    """预算不足（T < 最小配置）退出 1（race_plan / se_plan 的 StrategyBudgetError）。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), *argv_extra])
    assert rc == expect_rc
    assert '预算不足' in capsys.readouterr().err
    assert list(runs.iterdir()) == []


def test_race_plan_pure_arithmetic():
    """race_plan 纯函数：计划数 = 首 seed 全程豁免 + 其余门段记账上限；边界手算对拍。"""
    assert race_plan(1200) == (12, 90.0)      # 182.5 + 11×92.5 = 1200 恰用满
    assert race_plan(240, 60, 0.5) == (6, 30.0)   # 62.5 + 5×32.5 = 225 ≤ 240
    assert race_plan(275) == (2, 90.0)        # 恰好 1 豁免 + 1 门杀候选
    with pytest.raises(Exception) as ei:
        race_plan(274.9)
    assert isinstance(ei.value, ValueError)


# ------------------------------------------------------- race 接线（fake solve 帧协议）

# race 冒烟矩阵（--race-budget 60 --race-gate 0.5 → 门 30s；T=189 计划 [0,1,2,3]）：
#   seed0（队列 1，豁免）门值 0.840 跑满 0.860；seed1 门值 0.839 不高于 bar 0.840 门杀；
#   seed2 门值 0.850 破纪录续跑 0.880；seed3 名义预算不足未启动
#   （62.5 + 32.5 + 62.5 = 157.5，+ 门段 32.5 = 190 大于 189）。
_RACE_TRAJ = {
    (0, ''): [(10.0, 0.800), (30.0, 0.840), (60.0, 0.860)],
    (1, ''): [(10.0, 0.800), (31.0, 0.839)],
    (2, ''): [(10.0, 0.810), (31.0, 0.850), (60.0, 0.880)],
    (3, ''): [(10.0, 0.500)],              # 不应被消费（预算收口）
}


def _race_argv(cfg_path, *extra):
    return [str(cfg_path), '--strategy', '--time', '189',
            '--race-budget', '60', '--race-gate', '0.5', *extra]


def test_race_gate_kill_end_to_end(iso_env, capsys, monkeypatch):
    """race 端到端：豁免/门杀/续跑/预算收口 + 决策行 + strategy.json + portfolio 段。"""
    tmp, runs, inter, uploads, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    fake = _patch_solve(monkeypatch, _RACE_TRAJ)
    rc = main(_race_argv(cfg_path))
    out = capsys.readouterr().out
    assert rc == 0
    # 每轮预算 = race_budget（60s），无 should_stop 早停者跑满轨迹
    assert fake.calls == [(0, 60, ''), (1, 60, ''), (2, 60, '')]
    assert '策略模式 race（门杀）' in out and '计划 ≤ 4 个 seed' in out
    assert '第 1/4 轮（seed=0）' in out and '第 3/4 轮（seed=2）' in out
    assert 'race 预算收口：1 个计划 seed 未启动' in out
    rd = _only_run_dir(runs)
    # ---- strategy.json（R1：commit 后、首轮求解前写；首轮 solve 时已可读）
    first_seen = fake.strategy_json_at_first_solve
    assert first_seen is not None
    assert first_seen['mode'] == 'race' and first_seen['total_budget'] == 189
    assert first_seen['planned_seeds'] == [0, 1, 2, 3]
    assert first_seen['race'] == {'gate_seconds': 30.0} and first_seen['started_at']
    plan = json.loads((rd / 'strategy.json').read_text(encoding='utf-8'))
    assert plan == first_seen
    # ---- kill_decisions.jsonl：每 seed 至多一笔（0 豁免放行 / 1 杀 / 2 破纪录放行）
    rows = _read_kill_decisions(rd)
    assert [r['seed'] for r in rows] == [0, 1, 2]
    assert all(r['rule'] == R5_REASON for r in rows)
    assert [r['would_kill'] for r in rows] == [False, True, False]
    r1 = rows[1]
    assert r1['d'] == 0.839 and r1['S_tau'] == 0.84      # S_tau 重载 = bar 参照值
    assert r1['theta'] is None                            # race 不维护 θ
    assert r1['tau'] == round(31.0 / 60, 4) and r1['I'] == 0.86
    assert rows[2]['S_tau'] == 0.84    # bar=max(门值 0.84, 被杀 seed1 门值 0.839)=0.84
    # 门杀行（判据事件行）
    assert 'race 门杀（R5_race_gate）' in out and 'seed 1' in out
    # ---- result.json：portfolio 段 mode + race 子段；incumbent = 全局最大帧
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    pf = result['portfolio']
    assert pf['mode'] == 'race'
    assert pf['race'] == {'gate_seconds': 30.0, 'kept_seeds': [0, 2],
                          'gated_seeds': [1]}
    assert pf['kill_mode'] == 'off' and pf['theta_history'] == []   # 引擎 off、θ 不维护
    assert [e['seed'] for e in pf['per_seed']] == [0, 1, 2]
    assert [e['phase'] for e in pf['per_seed']] == ['race'] * 3
    killed = pf['per_seed'][1]
    assert killed['killed'] is True and killed['kill_reason'] == R5_REASON
    assert killed['best_density'] == 0.839               # 被杀 best 入 banking 池
    assert pf['incumbent']['density'] == 0.88 and pf['incumbent']['seed'] == 2
    assert result['best'] == pf['incumbent']
    # config 回显：time=总预算 + strategy 参数段（无旗标运行不加该键）
    assert result['config']['time'] == 189
    assert result['config']['strategy'] == {'mode': 'race', 'race_budget': 60,
                                            'race_gate': 0.5}
    # solve 数组：3 条、被杀条目 killed=True + kill_reason
    assert [s['seed'] for s in result['solve']] == [0, 1, 2]
    assert result['solve'][1]['killed'] is True
    assert '各 seed real_density' in out and '[kill] race 模式：3 条' in out
    assert inter.read_text(encoding='utf-8') == '{"sentinel": true}'   # web 事实源零触碰
    assert list(uploads.iterdir()) == []


def test_race_gate_kill_line_printed_with_quiet(iso_env, capsys, monkeypatch):
    """--quiet 抑制进度帧/轮次头，但门杀行（判据事件）与终局汇总照打。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    _patch_solve(monkeypatch, _RACE_TRAJ)
    rc = main(_race_argv(cfg_path, '--quiet'))
    out = capsys.readouterr().out
    assert rc == 0
    assert 'race 门杀（R5_race_gate）' in out
    assert '── 第 1/4 轮' not in out and '[seed 1]' not in out   # 进度/轮次头被抑制
    assert '[kill] race 模式：3 条' in out and 'real_density（原面积口径）' in out


def test_race_target_r0_stops_queue_before_gate_candidates(iso_env, capsys, monkeypatch):
    """--target 共存：R0 达标即停优先于模式继续（剩余 seed 不启动、退出码 0）。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    traj = {(0, ''): [(10.0, 0.800), (30.0, 0.840), (40.0, 0.860)]}   # 门豁免后 0.86 达标
    fake = _patch_solve(monkeypatch, traj)
    rc = main(_race_argv(cfg_path, '--target', '0.86'))
    out = capsys.readouterr().out
    assert rc == 0
    assert fake.calls == [(0, 60, '')]                  # 队列停止：seed1/2/3 不启动
    assert 'R0 达标即停' in out and 'incumbent real_density=86.00%' in out
    rd = _only_run_dir(runs)
    rows = _read_kill_decisions(rd)
    assert len(rows) == 1 and rows[0]['seed'] == 0 and rows[0]['would_kill'] is False
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    pf = result['portfolio']
    assert pf['target'] == 0.86 and pf['race']['gated_seeds'] == []
    assert result['solve'][0]['kill_reason'] == 'R0_target_reached'


def test_race_seed_stream_fill_and_decision_schema(iso_env, capsys, monkeypatch):
    """种子流：config seeds 原样入流 + max+1 补齐（planned_seeds 无重复；config 层
    已拒重复种子，去重仅 US-001 纯函数防御）；决策行字段与 kill_decisions schema
    同构（ASCII 键名全集）。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[7, 2])
    traj = {
        (7, ''): [(10.0, 0.800), (30.0, 0.840), (60.0, 0.860)],   # 队列 1 豁免
        (2, ''): [(10.0, 0.800), (31.0, 0.839)],                  # 不高于 bar 0.840 门杀
        (8, ''): [(10.0, 0.810), (31.0, 0.850), (60.0, 0.870)],   # max(7,2)+1 补齐
    }
    fake = _patch_solve(monkeypatch, traj)
    rc = main(_race_argv(cfg_path))
    assert rc == 0
    assert [c[0] for c in fake.calls] == [7, 2, 8]      # 去重保序 + max+1 补齐
    rd = _only_run_dir(runs)
    plan = json.loads((rd / 'strategy.json').read_text(encoding='utf-8'))
    assert plan['planned_seeds'] == [7, 2, 8, 9]        # 计划 4 个（实际启动 3 个）
    assert len(set(plan['planned_seeds'])) == 4         # 无重复不变量
    rows = _read_kill_decisions(rd)
    for row in rows:
        assert set(row) == {'t', 'seed', 'rule', 'd', 'tau', 'S_tau', 'theta',
                            'I', 'would_kill'}
    assert [r['seed'] for r in rows] == [7, 2, 8]


# ------------------------------------------------------- se 接线（两段式筛延）

# se 冒烟矩阵（--time 160 --se-screen 20 --se-extend 40 → k=(160-42.5)//22.5=5）：
#   筛选 5 轮 seed[0..4]（终值 0.80/0.82/0.81/0.83/0.79）→ 冠军 seed3；延长 0.86。
_SE_TRAJ = {
    (0, ''): [(5.0, 0.78), (20.0, 0.80)],
    (1, ''): [(5.0, 0.80), (20.0, 0.82)],
    (2, ''): [(5.0, 0.79), (20.0, 0.81)],
    (3, ''): [(5.0, 0.81), (20.0, 0.83)],
    (4, ''): [(5.0, 0.77), (20.0, 0.79)],
    (3, '_ext'): [(5.0, 0.82), (20.0, 0.84), (40.0, 0.86)],
}


def _se_argv(cfg_path, *extra):
    return [str(cfg_path), '--strategy', 'se', '--time', '160',
            '--se-screen', '20', '--se-extend', '40', *extra]


def test_se_two_phase_end_to_end(iso_env, capsys, monkeypatch):
    """se 端到端：k 轮 screen 筛选 + 冠军 ext 延长（_ext 产物 + phase=extension）。"""
    tmp, runs, inter, uploads, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    fake = _patch_solve(monkeypatch, _SE_TRAJ)
    rc = main(_se_argv(cfg_path))
    out = capsys.readouterr().out
    assert rc == 0
    # 阶段 1 五轮 screen 预算 20s + 阶段 2 冠军 seed3 ext 预算 40s（suffix=_ext）
    assert fake.calls == [(0, 20, ''), (1, 20, ''), (2, 20, ''), (3, 20, ''),
                          (4, 20, ''), (3, 40, '_ext')]
    assert '策略模式 se（筛延）' in out and '阶段 1' in out and '延长' in out
    assert '第 5/5 轮（seed=4）' in out
    assert '延长轮（seed=3·筛选冠军）开始' in out
    rd = _only_run_dir(runs)
    # strategy.json：se 块（k_screens/screen_s/ext_s）+ 计划种子流 = k 个筛选 seed
    plan = json.loads((rd / 'strategy.json').read_text(encoding='utf-8'))
    assert plan['mode'] == 'se' and plan['total_budget'] == 160
    assert plan['planned_seeds'] == [0, 1, 2, 3, 4]
    assert plan['se'] == {'k_screens': 5, 'screen_s': 20, 'ext_s': 40}
    assert plan['started_at']
    # _ext 产物在场且不覆盖筛选产物（同 seed 双份曲线共存）
    assert (rd / 'curve_s3.json').exists() and (rd / 'best_frame_s3.json').exists()
    assert (rd / 'curve_s3_ext.json').exists()
    ext_best = json.loads((rd / 'best_frame_s3_ext.json').read_text(encoding='utf-8'))
    assert ext_best['density'] == 0.86 and ext_best['seed'] == 3
    screen_curve = json.loads((rd / 'curve_s3.json').read_text(encoding='utf-8'))
    ext_curve = json.loads((rd / 'curve_s3_ext.json').read_text(encoding='utf-8'))
    assert [e['density'] for e in screen_curve] == [0.81, 0.83]   # 筛选产物未被动
    assert [e['density'] for e in ext_curve] == [0.82, 0.84, 0.86]
    # result.json：solve 数组 6 条（末条 phase=extension、seed=冠军）、portfolio.se
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert len(result['solve']) == 6
    ext_rec = result['solve'][-1]
    assert ext_rec['seed'] == 3 and ext_rec['phase'] == 'extension'
    assert ext_rec['real_density'] == 0.86
    assert all('phase' not in s for s in result['solve'][:-1])    # 筛选条目无 phase
    pf = result['portfolio']
    assert pf['mode'] == 'se'
    assert pf['se'] == {'k_screens': 5, 'screen_s': 20, 'ext_s': 40, 'champion': 3}
    assert [e['phase'] for e in pf['per_seed']] == ['screen'] * 5 + ['extension']
    # incumbent = 延长帧 0.86 大于等于全部筛选终值（延长入 banking 池）
    assert pf['incumbent']['density'] == 0.86 and pf['incumbent']['seed'] == 3
    assert pf['incumbent']['density'] >= max(0.80, 0.82, 0.81, 0.83, 0.79)
    assert result['best'] == pf['incumbent']
    assert result['config']['strategy'] == {'mode': 'se', 'se_screen': 20,
                                            'se_extend': 40}
    assert 'seed 3=86.00%（延长）' in out
    assert inter.read_text(encoding='utf-8') == '{"sentinel": true}'
    assert list(uploads.iterdir()) == []


def test_se_r0_stop_skips_extension(iso_env, capsys, monkeypatch):
    """R0 提前停（阶段 1 达标）不进延长：无 _ext 产物、champion=None、队列停止。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    traj = {(0, ''): [(5.0, 0.80), (15.0, 0.86)]}
    fake = _patch_solve(monkeypatch, traj)
    rc = main(_se_argv(cfg_path, '--target', '0.85'))
    out = capsys.readouterr().out
    assert rc == 0
    assert fake.calls == [(0, 20, '')]                  # R0 即停：其余筛选 + 延长不跑
    assert 'R0 达标即停' in out and '剩余 4 个 seed 未启动' in out
    rd = _only_run_dir(runs)
    assert not (rd / 'curve_s0_ext.json').exists()
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert result['portfolio']['se']['champion'] is None
    assert result['portfolio']['incumbent']['density'] == 0.86


def test_se_champion_is_argmax_real_density(iso_env, monkeypatch):
    """冠军 = solve 记录 real_density argmax（并列取先执行者）。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    traj = {
        (0, ''): [(5.0, 0.80), (20.0, 0.80)],
        (1, ''): [(5.0, 0.80), (20.0, 0.80)],          # 并列 0.80：冠军取先执行者 seed0
        (2, ''): [(5.0, 0.79), (20.0, 0.79)],
        (0, '_ext'): [(5.0, 0.81), (40.0, 0.81)],
    }
    fake = _patch_solve(monkeypatch, traj)
    rc = main([str(cfg_path), '--strategy', 'se', '--time', '130',
               '--se-screen', '20', '--se-extend', '40'])
    assert rc == 0
    # se_plan(130, 20, 40) = (130-62.5)//22.5 = 3 → 筛选 3 轮 + 冠军 seed0 延长
    assert [c[0] for c in fake.calls] == [0, 1, 2, 0]
    assert fake.calls[-1][2] == '_ext' and fake.calls[-1][1] == 40
    rd = _only_run_dir(runs)
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert result['portfolio']['se']['champion'] == 0
    assert result['portfolio']['se']['k_screens'] == 3


# ------------------------------------------------------- 零回归 + 冒烟


def test_legacy_result_json_has_no_strategy_keys(iso_env, capsys, monkeypatch):
    """无 --strategy 时 result.json 与现版结构一致：config 无 strategy 键、
    portfolio 无 mode 键（键集与 PC-002/003 基线逐项对拍）。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0, 1])
    traj = {(0, ''): [(1.0, 0.80), (2.0, 0.81)], (1, ''): [(1.0, 0.79), (2.0, 0.82)]}
    _patch_solve(monkeypatch, traj)
    rc = main([str(cfg_path), '--time', '2'])
    assert rc == 0
    rd = _only_run_dir(runs)
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert set(result) == {'config', 'commit', 'solve', 'best', 'portfolio'}
    assert 'strategy' not in result['config']
    assert set(result['config']) == {'path', 'master_dxf', 'sizes', 'gate_mm',
                                     'time', 'seeds', 'per_type', 'quantities'}
    assert 'mode' not in result['portfolio'] and 'race' not in result['portfolio']
    assert 'se' not in result['portfolio']
    assert set(result['portfolio']) == {'target', 'incumbent', 'per_seed',
                                        'theta_history', 'kill_mode'}
    assert 'strategy.json' not in [p.name for p in rd.iterdir()]
    assert not (rd / 'kill_decisions.jsonl').exists()  # 无 target 无 race：不落决策文件


def test_solve_pieces_artifact_suffix_real(iso_env):
    """solve_pieces artifact_suffix 契约（真实求解 2s）：_ext 后缀产物独立落盘、
    缺省 '' 与现行文件名逐字一致。"""
    from materialsorting.cli.config import load_config
    from materialsorting.cli.pipeline import commit_from_config, new_run_dir, solve_pieces
    tmp, _, _, _, master = iso_env
    cfg = load_config(_write_config(tmp / 'cfg_sp.json', master))
    run_dir = new_run_dir('sp_suffix')
    commit_from_config(cfg, run_dir)
    rec = solve_pieces(cfg, run_dir, seed=0, time_budget=2, artifact_suffix='_ext')
    assert 0.0 < rec['real_density'] < 1.0
    assert (run_dir / 'curve_s0_ext.json').exists()
    assert (run_dir / 'best_frame_s0_ext.json').exists()
    assert not (run_dir / 'curve_s0.json').exists()    # 缺省名不被占用
    best = json.loads((run_dir / 'best_frame_s0_ext.json').read_text(encoding='utf-8'))
    # 真实求解帧序列非单调（末帧解可能劣于历史最优帧）→ 最优帧密度 ≥ 末帧回报值
    assert best['seed'] == 0 and best['density'] >= rec['real_density']
    rec2 = solve_pieces(cfg, run_dir, seed=0, time_budget=2)
    assert (run_dir / 'curve_s0.json').exists()        # 缺省名照常（互不覆盖）
    assert rec2['real_density'] > 0


def test_help_contains_strategy_flags():
    """--help 含 5 个新旗标（python -m 子进程冒烟）。"""
    proc = subprocess.run(
        [sys.executable, '-m', 'materialsorting.cli.run_config', '--help'],
        capture_output=True, text=True, encoding='utf-8', cwd=str(_SRC.parents[1]))
    assert proc.returncode == 0
    for flag in ('--strategy', '--se-screen', '--se-extend', '--race-budget',
                 '--race-gate'):
        assert flag in proc.stdout


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
