"""US-002 ``--strategy`` 双模式接线（run_config 旗标 + PortfolioController 消费 +
solve_pieces ``artifact_suffix``）+ US-003 se 延长轮 warm 真顺延接线。

覆盖三层：

  - **旗标裁决**（main 退出码矩阵）：--strategy 值域（choices 外退出 1 非
    argparse 的 2）/ 策略模式 --time 总预算必填 / 与 --kill 显式同给互斥 / 4 个
    参数旗标是从属旗标（单独给出退出 1）/ --race-gate (0,1) 开区间 / 预算不足
    （race_plan / se_plan 的 StrategyBudgetError → 退出 1，不留空 run_dir）；
    US-003：--se-warm 值域 {on,off} 外退出 1 / 须与 --strategy se 同给（无策略
    或 race 下给出 = 从属旗标笔误退出 1）/ 与 --extreme 互斥；
  - **race 接线**（fake solve 帧协议：on_progress 先于 should_stop、终止交付
    best-so-far）：首 seed 豁免跑满、门杀决策行落 kill_decisions.jsonl（S_tau=bar
    参照、theta=null 重载）、被杀 best 参与 incumbent banking、名义记账收口
    （计划 seed 未启动）、--quiet 门杀行仍打、--target 共存 R0 优先；
  - **se 接线**：阶段 1 k 轮 screen 预算筛选 + 阶段 2 冠军（real_density argmax）
    同 seed 以 ext 预算延长（``_ext`` 产物防覆盖 + solve 条目 phase=extension），
    R0 提前停不进延长；US-003 warm：默认 on 透传 ``warm_best_frame=True`` 到
    延长轮 solve 调用形 / 回退矩阵（off / unsupported 前置，no_best_frame /
    invalid_best_frame / no_composite_view 装载点）各独立用例 + 回退 warn 行 +
    strategy.json 计划态与 result.json·run_stats 实际灌入态 additive 键 +
    solve_pieces 装载点（真 build_instance + 桩 solve_with_callback_proc）载荷
    精确对拍（二期 2026-09-19 band/prefix 解禁：band 开 + 边车 composite 段 →
    组合视角载荷 / 缺段 → no_composite_view）；
  - **零回归**：无 --strategy 时 result.json 不加 strategy/mode 键 + ``--help``
    含新旗标 + 无旗标 legacy 运行 stdout 逐字节对拍哨兵（US-003）。
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
from materialsorting.cli.portfolio import (R5_REASON, SE_WARM_REASONS,
                                           race_plan, se_warm_plan)
from materialsorting.cli.run_config import main
from materialsorting.nesting_engine import warmstart
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
    """隔离环境：CONFIG_RUNS_DIR / INTERMEDIATE / RUN_STATS_JSONL / uploads 全指
    到 tmp_path（US-003 起 run_stats 也隔离 —— 此前本文件测试会向真实
    out/run_stats.jsonl 追加行）。"""
    runs = tmp_path / 'config_runs'
    runs.mkdir()
    inter = tmp_path / 'web_intermediate.json'
    inter.write_text('{"sentinel": true}', encoding='utf-8')
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    stats = tmp_path / 'run_stats.jsonl'
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(runs))
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE', str(inter))
    monkeypatch.setattr(paths_mod, 'RUN_STATS_JSONL', str(stats))
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', uploads)
    master = _make_master_dxf(tmp_path / 'synthetic_master.dxf')
    return tmp_path, runs, inter, uploads, master


@pytest.fixture(autouse=True)
def _warm_ms0(monkeypatch):
    """全文件钉死 warm 能力探测 = False（0.9.0+ms0 纯重建 wheel 态）。

    本文件测 CLI 接线而非 wheel 检测（那是 tests/test_warmstart.py 的多态矩阵）；
    钉死避免环境漂移（未来 .venv 装入 0.9.0+ms1 私有 wheel 后默认路径翻转成
    真 warm，断言全炸）。需要 True 的用例在自身内再 monkeypatch 覆盖（同一
    monkeypatch 实例，后写胜出、逆序还原）。
    """
    monkeypatch.setattr(warmstart, 'warm_start_supported', lambda: False)


class _FakeSolve:
    """模拟 ``pipeline.solve_pieces`` 帧协议的 fake（monkeypatch 进 run_config）。

    逐帧 ``on_progress`` 先于 ``should_stop``（与 solve_pieces 的调用序一致 ——
    banking 先行，R0/门杀帧必在 incumbent 候选内）；should_stop 真值 → 该 seed
    以 best-so-far 帧交付（``killed=True`` + ``kill_reason``），后续帧不投；
    产物按 ``curve_s{seed}{suffix}.json`` / ``best_frame_s{seed}{suffix}.json``
    落盘（契约同形，供 ``_ext`` 防覆盖断言）。轨迹键 = ``(seed, suffix)``。

    US-003：``warm_flags`` 逐调用记录是否收到 ``warm_best_frame=True`` 策略标志
    （portfolio 前置判定通过的延长轮才带）；收到的调用模拟 solve_pieces 契约在
    返回记录附 ``warm: True``（装载点行为由独立的 solve_pieces 级测试覆盖）。
    """

    def __init__(self, traj: dict):
        self.traj = traj
        self.calls: list[tuple] = []
        self.warm_flags: list[bool] = []
        self.strategy_json_at_first_solve: dict | None = None

    def __call__(self, cfg, run_dir, *, seed, time_budget=None, on_progress=None,
                 should_stop=None, solver_opts=None, artifact_suffix='', **kw):
        warm = bool(kw.get('warm_best_frame'))
        self.calls.append((int(seed), time_budget, artifact_suffix))
        self.warm_flags.append(warm)
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
        if warm:
            rec['warm'] = True      # solve_pieces 契约：warm_best_frame=True 必带
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


# ------------------------------------------------------- US-003 --se-warm 旗标裁决


def test_se_warm_value_out_of_domain_exit_1(iso_env, capsys):
    """--se-warm 值域手工校验（on/off 外退出 1 而非 argparse choices 的 2）。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main(_se_argv(cfg_path, '--se-warm', 'bogus'))
    assert rc == 1
    err = capsys.readouterr().err
    assert '--se-warm 须为 on 或 off' in err and 'bogus' in err
    assert list(runs.iterdir()) == []              # 配置错误在 new_run_dir 之前拦下


@pytest.mark.parametrize('argv_extra', [
    ['--se-warm', 'on'],                                  # 无 --strategy
    ['--strategy', '--time', '600', '--se-warm', 'off'],  # race 模式（非 se）
])
def test_se_warm_subordinate_requires_strategy_se(iso_env, capsys, argv_extra):
    """--se-warm 须与 --strategy se 同给：无策略 / race 模式下给出 = 笔误退出 1。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), *argv_extra])
    assert rc == 1
    assert '--se-warm 须与 --strategy se 同给' in capsys.readouterr().err
    assert list(runs.iterdir()) == []


def test_extreme_se_warm_conflict_exit_1(iso_env, capsys):
    """--extreme 与 --se-warm 互斥（糖衣旗标独占策略与旋钮，同 4 个参数旗标口径）。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--extreme', '--time', '905', '--se-warm', 'on'])
    assert rc == 1
    assert '--extreme 与 --se-warm 互斥' in capsys.readouterr().err
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
    # strategy.json：se 块（k_screens/screen_s/ext_s + US-003 warm 计划态）+ 计划
    # 种子流 = k 个筛选 seed（本文件 autouse 钉 warm 不支持 → 计划态回退）。
    plan = json.loads((rd / 'strategy.json').read_text(encoding='utf-8'))
    assert plan['mode'] == 'se' and plan['total_budget'] == 160
    assert plan['planned_seeds'] == [0, 1, 2, 3, 4]
    assert plan['se'] == {'k_screens': 5, 'screen_s': 20, 'ext_s': 40,
                          'warm': False, 'warm_reason': 'unsupported'}
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
    # US-003：config.strategy additive 实际灌入态（unsupported 回退 → False+原因）
    assert result['config']['strategy'] == {'mode': 'se', 'se_screen': 20,
                                            'se_extend': 40, 'warm': False,
                                            'warm_reason': 'unsupported'}
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


# --------------------------------------------- US-003 se 延长轮 warm 真顺延接线


def _read_stats(path: Path) -> list[dict]:
    text = Path(path).read_text(encoding='utf-8')
    return [json.loads(line) for line in text.splitlines() if line]


def test_se_warm_plan_matrix(monkeypatch):
    """se_warm_plan 纯函数矩阵：off 恒回退（不探测）/ unsupported / 全过 →
    (True, None)。二期（2026-09-19）起 band/prefix 不再前置回退（组合视角
    边车旁路解禁）—— band/prefix 开 + 能力就绪 → (True, None) 照常接线。"""
    from types import SimpleNamespace
    cfg_plain = SimpleNamespace(band=None, prefix=None)
    cfg_band = SimpleNamespace(band={'enabled': True, 'label': 'g05'}, prefix=None)
    cfg_prefix = SimpleNamespace(band=None,
                                 prefix={'enabled': True, 'front': 'g02',
                                         'back': 'g03'})
    monkeypatch.setattr(warmstart, 'warm_start_supported', lambda: True)
    assert se_warm_plan(cfg_plain, False) == (False, 'off')
    assert se_warm_plan(cfg_plain, True) == (True, None)
    # 二期解禁回归锁：band/prefix 开不再是前置回退（一期此处为
    # (False, 'band_prefix_on') —— 成员级 placed 与组合片实例 pid 宇宙错位，
    # 已由边车 composite 段 + worker 宇宙复检桥接）。
    assert se_warm_plan(cfg_band, True) == (True, None)
    assert se_warm_plan(cfg_prefix, True) == (True, None)
    monkeypatch.setattr(warmstart, 'warm_start_supported', lambda: False)
    assert se_warm_plan(cfg_plain, True) == (False, 'unsupported')
    # 判定序 off → unsupported：off 不探测（先于一切）；unsupported 下 band
    # 开关无关（更根本的能力成因优先）。
    assert se_warm_plan(cfg_band, True) == (False, 'unsupported')
    assert se_warm_plan(cfg_plain, False) == (False, 'off')   # off 先于探测


def test_se_warm_on_passes_flag_to_ext_solve(iso_env, capsys, monkeypatch):
    """warm on（默认、无 --se-warm 旗标）+ 能力探测 True：延长轮 solve 调用形多收
    warm_best_frame=True（筛选轮不带）+ strategy.json 计划态 / result.json·run_stats
    实际灌入态 additive 记 warm: true（true 时无 warm_reason 键）。"""
    monkeypatch.setattr(warmstart, 'warm_start_supported', lambda: True)
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    fake = _patch_solve(monkeypatch, _SE_TRAJ)
    rc = main(_se_argv(cfg_path))                  # 默认 on：不带 --se-warm 旗标
    out = capsys.readouterr().out
    assert rc == 0
    assert fake.warm_flags == [False] * 5 + [True]    # 5 轮筛选不带、延长轮带
    assert '延长轮 warm 真顺延' in out
    assert 'warm 回退' not in out
    rd = _only_run_dir(runs)
    plan = json.loads((rd / 'strategy.json').read_text(encoding='utf-8'))
    assert plan['se']['warm'] is True and 'warm_reason' not in plan['se']
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    st = result['config']['strategy']
    assert st['warm'] is True and 'warm_reason' not in st
    assert result['solve'][-1]['warm'] is True         # 延长轮 solve 记录附灌入态
    assert all('warm' not in s for s in result['solve'][:-1])
    entries = _read_stats(tmp / 'run_stats.jsonl')
    assert len(entries) == 1
    assert entries[0]['config']['warm'] is True
    assert 'warm_reason' not in entries[0]['config']


def test_se_warm_default_unsupported_fallback_replay(iso_env, capsys, monkeypatch):
    """默认 on 但 wheel 不支持（当前 0.9.0+ms0 装载态）→ 回退现状重放：延长轮
    solve 调用形与无 warm 逐字节一致（不带 warm_best_frame 键）+ warn 一行 +
    计划态/实际态 additive 记 warm: false + warm_reason: unsupported。"""
    monkeypatch.setattr(warmstart, 'warm_start_supported', lambda: False)
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    fake = _patch_solve(monkeypatch, _SE_TRAJ)
    rc = main(_se_argv(cfg_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert fake.warm_flags == [False] * 6              # 全轮不带 warm 键（回退重放）
    assert 'se 延长轮 warm 回退 → 现状重放（warm_reason=unsupported）' in out
    rd = _only_run_dir(runs)
    plan = json.loads((rd / 'strategy.json').read_text(encoding='utf-8'))
    assert plan['se']['warm'] is False
    assert plan['se']['warm_reason'] == 'unsupported'
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    st = result['config']['strategy']
    assert st['warm'] is False and st['warm_reason'] == 'unsupported'
    assert all('warm' not in s for s in result['solve'])
    entries = _read_stats(tmp / 'run_stats.jsonl')
    assert entries[0]['config']['warm'] is False
    assert entries[0]['config']['warm_reason'] == 'unsupported'


def test_se_warm_off_explicit_fallback(iso_env, capsys, monkeypatch):
    """--se-warm off 显式回退：即使能力探测 True 也不接线（solve 全轮不带 warm
    键），warm_reason='off'（用户显式选择照常入档可审计）。"""
    monkeypatch.setattr(warmstart, 'warm_start_supported', lambda: True)
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    fake = _patch_solve(monkeypatch, _SE_TRAJ)
    rc = main(_se_argv(cfg_path, '--se-warm', 'off'))
    out = capsys.readouterr().out
    assert rc == 0
    assert fake.warm_flags == [False] * 6
    assert 'se 延长轮 warm 回退 → 现状重放（warm_reason=off）' in out
    rd = _only_run_dir(runs)
    plan = json.loads((rd / 'strategy.json').read_text(encoding='utf-8'))
    assert plan['se'] == {'k_screens': 5, 'screen_s': 20, 'ext_s': 40,
                          'warm': False, 'warm_reason': 'off'}
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    st = result['config']['strategy']
    assert st['warm'] is False and st['warm_reason'] == 'off'


@pytest.mark.parametrize('cfg_extra', [
    {'band': {'enabled': True, 'label': 'g01'}},
    {'prefix': {'enabled': True, 'front': 'g01', 'back': 'g02'}},
])
def test_se_warm_band_prefix_on_engages(iso_env, capsys, monkeypatch, cfg_extra):
    """二期解禁（2026-09-19）：cfg.band / cfg.prefix 开 + 能力就绪 → warm 照常
    接线（一期 'band_prefix_on' 前置回退已删）—— 延长轮 solve 收
    warm_best_frame=True、计划态/实际态 warm: true、无回退行。"""
    monkeypatch.setattr(warmstart, 'warm_start_supported', lambda: True)
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0], **cfg_extra)
    fake = _patch_solve(monkeypatch, _SE_TRAJ)
    rc = main(_se_argv(cfg_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert fake.warm_flags == [False] * 5 + [True]    # 筛选 5 轮不带、延长轮带
    assert 'warm 回退' not in out
    rd = _only_run_dir(runs)
    plan = json.loads((rd / 'strategy.json').read_text(encoding='utf-8'))
    assert plan['se']['warm'] is True and 'warm_reason' not in plan['se']
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    st = result['config']['strategy']
    assert st['warm'] is True and 'warm_reason' not in st


def test_se_warm_reason_enum_is_closed():
    """warm_reason 枚举闭包：八类回退原因与 portfolio 常量对拍（文档单一真相源；
    二期删 'band_prefix_on'、增装载点 no_composite_view 与 worker 三类）。"""
    assert SE_WARM_REASONS == ('off', 'unsupported', 'no_best_frame',
                               'invalid_best_frame', 'no_composite_view',
                               'worker_unsupported', 'worker_serialize_failed',
                               'instance_mismatch')


# --------------------------------------- US-003 solve_pieces warm 装载点（真 build_instance + 桩 proc）


class _FakeProc:
    """桩 ``web.solver.solve_with_callback_proc``：记录 initial_solution / band /
    prefix / record_composite 调用形并直接回 final（placed = 全量 Σdemand，
    正常完成路径）。record_composite（二期）透传记录供旁路断言。"""

    def __init__(self, demand_pids: list[str]):
        self.demand_pids = demand_pids
        self.calls: list[dict] = []

    def __call__(self, pieces, gate_mm, solve_params, *, on_manifest, on_report,
                 on_process=None, on_stage=None, drain_interval=0.2,
                 band=None, prefix=None, initial_solution=None,
                 record_composite=False):
        self.calls.append({'initial_solution': initial_solution, 'band': band,
                           'prefix': prefix, 'record_composite': record_composite,
                           'time_budget': solve_params['time_budget']})
        final = {
            'placed_items': [
                {'id': pid, 'rotation': 0.0, 'translation': [float(i) * 100.0, 0.0]}
                for i, pid in enumerate(self.demand_pids)],
            'width_mm': 3000.0, 'density': 0.75, 'density_sparrow': 0.7,
        }
        return None, final, 2.0, None


def _warm_setup(tmp, master, monkeypatch, *, supported=True, cfg_extra=None):
    """真 commit（合成母版 → 6 片 demand=1）+ 桩 proc；返回 (cfg, run_dir, pids,
    fake)。pids = intermediate 真实 pid 集（warm 边车 placed 的合法 id 域）。"""
    monkeypatch.setattr(warmstart, 'warm_start_supported', lambda: supported)
    from materialsorting.cli.config import load_config
    from materialsorting.cli.pipeline import commit_from_config, new_run_dir
    from materialsorting.web import solver as solver_mod
    cfg = load_config(_write_config(tmp / 'cfg_warm.json', master,
                                    **(cfg_extra or {})))
    run_dir = new_run_dir('warm_load')
    commit_from_config(cfg, run_dir)
    doc = json.loads((run_dir / 'pieces_intermediate.json').read_text(
        encoding='utf-8'))
    pids = [p['pid'] for p in doc['pieces']]
    assert len(pids) == 6                       # 合成母版 6 片全 demand=1 → Σdemand=6
    fake = _FakeProc(pids)
    monkeypatch.setattr(solver_mod, 'solve_with_callback_proc', fake)
    return cfg, run_dir, pids, fake


def _write_best_frame(run_dir: Path, pids: list[str], *, width_mm=4321.5,
                      placed: list[dict] | None = None,
                      composite: dict | None = None) -> None:
    """写筛选轮 best_frame_s0.json 边车（placed 缺省 = 6 条恰好完整解）。

    ``composite``（二期）：band/prefix 筛选轮 worker 记录的组合视角段
    ``{'placed_items': [...], 'demand_map': {...}}`` —— 非 None 时落进边车
    （additive 键，与 ``pipeline._best_frame_record`` 产物同形）。"""
    if placed is None:
        placed = [{'id': pid, 'rotation': 0, 'translation': [i * 120, 30]}
                  for i, pid in enumerate(pids)]
    rec = {'seed': 0, 'frame_index': 3, 'density': 0.8,
           'width_mm': width_mm, 'placed_items': placed}
    if composite is not None:
        rec['composite'] = composite
    (run_dir / 'best_frame_s0.json').write_text(
        json.dumps(rec, ensure_ascii=False), encoding='utf-8')


def test_solve_pieces_warm_best_frame_loads_payload(iso_env, monkeypatch):
    """装载点主路径：边车 placed + width_mm → build_initial_solution 载荷精确
    对拍（int→float 归一、顺序保持）透传 solve_with_callback_proc(initial_solution=
    <dict>)，返回记录附 warm: True。"""
    tmp, _, _, _, master = iso_env
    cfg, run_dir, pids, fake = _warm_setup(tmp, master, monkeypatch)
    _write_best_frame(run_dir, pids)
    from materialsorting.cli.pipeline import solve_pieces
    rec = solve_pieces(cfg, run_dir, seed=0, time_budget=2,
                       warm_best_frame=True, artifact_suffix='_ext')
    expect = {'strip_width': 4321.5,
              'placed_items': [{'id': pid, 'rotation': 0.0,
                                'translation': [float(i * 120), 30.0]}
                               for i, pid in enumerate(pids)]}
    assert fake.calls[0]['initial_solution'] == expect   # 载荷在调用形上透传
    assert rec['warm'] is True and 'warm_reason' not in rec
    assert rec['real_density'] == 0.75                   # final 直通（求解照常）
    assert (run_dir / 'curve_s0_ext.json').exists()      # 延长轮轨迹照常落盘
    # 桩 proc 不投帧 → best_frame_s0_ext.json 不产生（逐帧落盘依赖 on_report，
    # 该面已由 test_solve_pieces_artifact_suffix_real 真求解覆盖）


def test_solve_pieces_warm_composite_loads_payload(iso_env, monkeypatch):
    """二期（2026-09-19）band/prefix 解禁主路径：band 开 + 边车含 composite 段
    → 装载点改读该段构造**组合视角**载荷（placed 含 WB_、demand_map 用边车
    记录的组合宇宙而非主进程全量 pid_meta），band 照常下传、record_composite
    =True 透传（CLI 落盘路径恒请求旁路），记录附 warm: True。"""
    tmp, _, _, _, master = iso_env
    cfg, run_dir, pids, fake = _warm_setup(
        tmp, master, monkeypatch,
        cfg_extra={'band': {'enabled': True, 'label': 'g01'}})
    # 组合宇宙：label g01 两 pid 被 exclude_labels 整排除 + WB_g01 demand=1。
    g01 = [p for p in pids if p.startswith('g01_')]
    comp_demand = {p: 1 for p in pids if not p.startswith('g01_')}
    comp_demand['WB_g01'] = 1
    comp_placed = [{'id': pid, 'rotation': 0, 'translation': [i * 120, 30]}
                   for i, pid in enumerate(sorted(comp_demand))]
    _write_best_frame(run_dir, pids, composite={'placed_items': comp_placed,
                                                'demand_map': comp_demand})
    from materialsorting.cli.pipeline import solve_pieces
    rec = solve_pieces(cfg, run_dir, seed=0, time_budget=2,
                       warm_best_frame=True, artifact_suffix='_ext')
    expect = {'strip_width': 4321.5,
              'placed_items': [{'id': pid, 'rotation': 0.0,
                                'translation': [float(i * 120), 30.0]}
                               for i, pid in enumerate(sorted(comp_demand))]}
    call = fake.calls[0]
    assert call['initial_solution'] == expect   # 组合视角载荷（含 WB_g01）
    assert call['band'] == {'label': 'g01'}      # band 照常下传（现状重放面不变）
    assert call['record_composite'] is True      # CLI 落盘路径恒请求旁路
    assert rec['warm'] is True and 'warm_reason' not in rec
    # 组合宇宙对拍：g01 成员 pid 不在载荷（被组合片承载）、WB_g01 在。
    ids = [it['id'] for it in call['initial_solution']['placed_items']]
    assert 'WB_g01' in ids
    assert not any(p in ids for p in g01)


@pytest.mark.parametrize('scenario,supported,best_mode,cfg_extra,expect_reason', [
    ('边车缺失', True, None, None, 'no_best_frame'),
    ('边车损坏（非法 JSON）', True, 'corrupt', None, 'no_best_frame'),
    ('部分解（校验失败）', True, 'partial', None, 'invalid_best_frame'),
    ('能力不支持', False, 'full', None, 'unsupported'),
    # 二期（2026-09-19）：band 开不再前置回退，改读边车 composite 段 —— 一期
    # 产物/缺段 → 'no_composite_view'（装载点回退，band 本身照常下传）。
    ('band 开 + 边车缺 composite 段', True, 'full',
     {'band': {'enabled': True, 'label': 'g01'}}, 'no_composite_view'),
])
def test_solve_pieces_warm_fallback_matrix(iso_env, monkeypatch, scenario,
                                           supported, best_mode, cfg_extra,
                                           expect_reason):
    """装载点回退矩阵：任一命中 → 不带载荷现状重放（initial_solution=None）+
    记录附 warm: False + warm_reason，绝不抛、不炸轮。"""
    tmp, _, _, _, master = iso_env
    cfg, run_dir, pids, fake = _warm_setup(tmp, master, monkeypatch,
                                           supported=supported,
                                           cfg_extra=cfg_extra)
    if best_mode == 'full':
        _write_best_frame(run_dir, pids)
    elif best_mode == 'partial':
        _write_best_frame(run_dir, pids[:-1])           # 5 条 ≠ Σdemand=6
    elif best_mode == 'corrupt':
        (run_dir / 'best_frame_s0.json').write_text('{"trunc', encoding='utf-8')
    from materialsorting.cli.pipeline import solve_pieces
    rec = solve_pieces(cfg, run_dir, seed=0, time_budget=2,
                       warm_best_frame=True, artifact_suffix='_ext')
    assert rec['warm'] is False and rec['warm_reason'] == expect_reason, scenario
    assert fake.calls[0]['initial_solution'] is None    # 回退：不带载荷
    assert rec['real_density'] == 0.75                  # 求解照常跑完（不炸轮）
    if cfg_extra and 'band' in cfg_extra:
        # band 回退只退 warm：band 本身照常下传（现状重放 = band on 的普通求解）
        assert fake.calls[0]['band'] == {'label': 'g01'}


def test_solve_pieces_warm_flag_absent_zero_regress(iso_env, monkeypatch):
    """缺省不传 warm_best_frame：即使边车在场也不读、载荷 None、记录无 warm 键
    （无旗标调用形与返回形零回归）。"""
    tmp, _, _, _, master = iso_env
    cfg, run_dir, pids, fake = _warm_setup(tmp, master, monkeypatch)
    _write_best_frame(run_dir, pids)                    # 边车在场：证明不被读
    from materialsorting.cli.pipeline import solve_pieces
    rec = solve_pieces(cfg, run_dir, seed=0, time_budget=2)
    assert fake.calls[0]['initial_solution'] is None
    assert 'warm' not in rec and 'warm_reason' not in rec
    assert set(rec) == {'seed', 'n_items', 'n_eroded', 'total_area_mm2',
                        'width_mm', 'real_density', 'density_sparrow',
                        'placed_items', 'elapsed'}


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


def test_legacy_no_flag_output_byte_for_byte(iso_env, capsys, monkeypatch):
    """零回归哨兵（US-003）：无 --strategy/--se-warm 的 legacy 运行 stdout
    逐字节对拍 —— 确定性 fake 轨迹下全部行内容可先验推演（时间戳目录与 commit
    数值事后读回拼入），格式串与现行源逐字同构：任何输出增量（如误加 warm 行）
    或格式漂移都会破坏本对拍。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0, 1])
    traj = {(0, ''): [(1.0, 0.80), (2.0, 0.82)],
            (1, ''): [(1.0, 0.81), (2.0, 0.83)]}
    fake = _patch_solve(monkeypatch, traj)
    assert main([str(cfg_path), '--time', '2']) == 0
    out = capsys.readouterr().out
    rd = _only_run_dir(runs)
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    c = result['commit']

    def seed_line(seed: int, elapsed: float, density: float) -> str:
        return (f'[seed {seed}] {elapsed:7.1f}s {"exploring":<14} '
                f'real_density={density:.2%}（原面积口径新最优） '
                f'width={5000.0:.0f}mm')

    expected = '\n'.join([
        f'run_dir: {rd}',
        f'配置: {Path(cfg_path).resolve()} | 求解时长: 2s | seeds: [0, 1]',
        '多 seed 串行 2 轮 × 2s，预计总时长 ≈ 4s（不含解析/切片）',
        f"commit: n_pieces={c['n_pieces']} "
        f"total_area={c['total_area_mm2']:,.1f}mm² sizes={c['sizes']} "
        f"skipped={c['n_skipped']}",
        '── 第 1/2 轮（seed=0）开始 ──',
        seed_line(0, 1.0, 0.80),
        seed_line(0, 2.0, 0.82),
        '── 第 2/2 轮（seed=1）开始 ──',
        seed_line(1, 1.0, 0.81),
        '[portfolio] seed 1 frame 1 反超 → incumbent（全局最优）'
        'real_density=83.00%（原面积口径） width=5000mm',
        '各 seed real_density（原面积口径）: seed 0=82.00% | seed 1=83.00%',
        'best = seed 1 frame 1（incumbent，帧级全局最优）',
        'real_density（原面积口径）= 83.00% | 用布长度 = 5000mm | 片数 = 1 | '
        f'耗时 = 2.0s | run_dir = {rd.resolve()}',
    ]) + '\n'
    assert out == expected
    # result.json / solve 调用形零增量：无任何 warm/strategy 面
    assert 'strategy' not in result['config']
    assert all('warm' not in s for s in result['solve'])
    assert fake.warm_flags == [False, False]
    assert 'warm' not in out                                 # 输出零 warm 字样


def test_help_contains_strategy_flags():
    """--help 含 6 个策略族旗标（python -m 子进程冒烟，US-003 增 --se-warm）。"""
    proc = subprocess.run(
        [sys.executable, '-m', 'materialsorting.cli.run_config', '--help'],
        capture_output=True, text=True, encoding='utf-8', cwd=str(_SRC.parents[1]))
    assert proc.returncode == 0
    for flag in ('--strategy', '--se-screen', '--se-extend', '--se-warm',
                 '--race-budget', '--race-gate'):
        assert flag in proc.stdout


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
