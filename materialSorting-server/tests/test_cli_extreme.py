"""US-001 ``--extreme`` 极限运行糖衣旗标（run_config 展开 + 互斥 + 统计回显）。

覆盖（PRD stories US-001 验收标准）：

  - **展开等价性**：``--extreme --time T`` 与手敲三件套（``--strategy race
    --race-budget 600 --race-gate 0.5 --solver-opts 三键``）的 result.json（含
    config.strategy / config.solver_opts / solve 回显 / portfolio / best）、
    strategy.json（started_at 除外）、kill_decisions.jsonl **逐字段一致**；
    opts 恰三键、**无 quadtree_depth 键**（缺省 4，方案 §2.6 A/B 已否决调优）；
    solve 调用收到的每轮 solver_opts 同为三键固定档；
  - **互斥矩阵**：--extreme 与 --strategy / --kill / --solver-opts /
    --rotate-opts / --se-screen / --se-extend / --race-budget / --race-gate
    任一同给 → 退出码 1 + 中文报错 + 不留空 run_dir（糖衣旗标独占策略与旋钮）；
  - **--extreme-budget**：单独给出（无 --extreme）→ 退出 1（从属旗标）；非
    600/1200（0/900/2400）→ 退出 1（2400s+ 门判别力失效硬边界）；1200 档展开
    race_budget=1200 / 门 600s；
  - **预算下限**：T < 905 沿用 race_plan 的 StrategyBudgetError 报错路径退出 1
    （600 档 = 首轮全程 602.5 + 一轮门段 302.5）；--extreme 无 --time → 策略
    模式守卫退出 1；
  - **run_stats.jsonl**：extreme 行 config 段含 ``"extreme": {"budget": 600}``、
    class_key 与手敲臂一致（历史可比）；非 extreme 行无该键（零回归）；
  - **--help** 含两个新旗标（python -m 子进程冒烟）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.cli.portfolio import R5_REASON
from materialsorting.cli.run_config import (EXTREME_BUDGETS, EXTREME_BUDGET_S,
                                            EXTREME_SOLVER_OPTS, main)
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

# 手敲三件套等价臂的 --solver-opts（与 EXTREME_SOLVER_OPTS 逐字段一致）。
_MANUAL_OPTS_JSON = ('{"exploration_pct": 0.7, "early_termination": false,'
                     ' "num_workers": 4}')


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
    """隔离环境：CONFIG_RUNS_DIR / INTERMEDIATE / uploads / RUN_STATS_JSONL 全指 tmp。"""
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
    return tmp_path, runs, stats, master


class _FakeSolve:
    """模拟 ``pipeline.solve_pieces`` 帧协议的 fake（monkeypatch 进 run_config）。

    契约镜像 test_cli_strategy_wiring._FakeSolve，额外记录每轮收到的
    ``solver_opts``（US-001 展开等价性断言）并在 solve 记录回显（与
    ``solve_pieces`` 非空 opts 附 ``solver_opts`` 字段的真实行为一致）。
    """

    def __init__(self, traj: dict):
        self.traj = traj
        self.calls: list[tuple] = []          # (seed, time_budget, suffix, opts)

    def __call__(self, cfg, run_dir, *, seed, time_budget=None, on_progress=None,
                 should_stop=None, solver_opts=None, artifact_suffix='', **kw):
        self.calls.append((int(seed), time_budget, artifact_suffix, solver_opts))
        rd = Path(run_dir)
        frames = self.traj[(int(seed), artifact_suffix)]
        best = None                           # (frame_index, elapsed, density)
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
        if solver_opts:
            rec['solver_opts'] = dict(solver_opts)          # 真实 solve_pieces 回显口径
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


def _read_kill_decisions(rd: Path) -> list[dict]:
    text = (rd / 'kill_decisions.jsonl').read_text(encoding='utf-8')
    return [json.loads(line) for line in text.splitlines() if line]


def _read_stats(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding='utf-8').splitlines() if line]


# ---------------------------------------------- 极端矩阵（600 档 / T=905 最小配置）
# race_plan(905, 600, 0.5) = (2, 300.0)：seed0（队列 1，豁免）门值 0.840 跑满 0.860；
# seed1 门值 0.839 <= bar 0.840 门杀（名义 602.5 + 302.5 = 905 恰用满）。
_EXTREME_TRAJ = {
    (0, ''): [(50.0, 0.800), (300.0, 0.840), (600.0, 0.860)],
    (1, ''): [(50.0, 0.799), (301.0, 0.839)],
}


def test_extreme_expansion_equivalent_to_manual_three_flags(iso_env, capsys,
                                                            monkeypatch):
    """展开等价性：--extreme 与手敲三件套的产物逐字段一致（started_at 除外）。

    糖衣旗标唯一合法差异 = run_stats.jsonl 的 config.extreme 键（additive 回显）。
    """
    tmp, runs, stats, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    fake = _patch_solve(monkeypatch, _EXTREME_TRAJ)
    rc = main([str(cfg_path), '--extreme', '--time', '905', '--name', 'eq_extreme'])
    assert rc == 0
    out = capsys.readouterr().out
    # ---- 启动行：race 展开参数 + 极限标注 + solver_opts 回显（--quiet 也打口径）
    assert '[extreme] 极限运行' in out
    assert '策略模式 race（门杀）：总预算 905s，每 seed 600s 预算，门时刻 300s' in out
    assert 'solver_opts: {"exploration_pct": 0.7, "early_termination": false,' \
           ' "num_workers": 4}' in out
    # ---- solve 调用形：每轮预算 600 + 固定三键 opts（无 quadtree_depth）
    assert [c[:2] for c in fake.calls] == [(0, 600), (1, 600)]
    assert all(c[3] == EXTREME_SOLVER_OPTS for c in fake.calls)
    assert set(EXTREME_SOLVER_OPTS) == {'exploration_pct', 'early_termination',
                                        'num_workers'}
    assert 'quadtree_depth' not in EXTREME_SOLVER_OPTS
    extreme_rd = runs / ('eq_extreme_' + time.strftime('%Y%m%d-%H%M%S'))
    assert extreme_rd.is_dir()
    result_ext = json.loads((extreme_rd / 'result.json').read_text(encoding='utf-8'))
    plan_ext = json.loads((extreme_rd / 'strategy.json').read_text(encoding='utf-8'))
    rows_ext = _read_kill_decisions(extreme_rd)

    # ---- 手敲三件套对照臂（同 cfg 同 traj，唯一差异 = 旗标写法）
    fake2 = _patch_solve(monkeypatch, _EXTREME_TRAJ)
    rc2 = main([str(cfg_path), '--strategy', '--time', '905', '--name', 'eq_manual',
                '--race-budget', '600', '--race-gate', '0.5',
                '--solver-opts', _MANUAL_OPTS_JSON])
    assert rc2 == 0
    capsys.readouterr()
    assert [c[:2] for c in fake2.calls] == [(0, 600), (1, 600)]
    manual_rd = runs / ('eq_manual_' + time.strftime('%Y%m%d-%H%M%S'))
    assert manual_rd.is_dir()
    result_man = json.loads((manual_rd / 'result.json').read_text(encoding='utf-8'))
    plan_man = json.loads((manual_rd / 'strategy.json').read_text(encoding='utf-8'))
    rows_man = _read_kill_decisions(manual_rd)

    # ---- 逐字段一致：result.json（solve 回显 opts 三键 / portfolio / best 同构）。
    # commit.run_dir / config.path 内嵌本 run 目录与配置路径（两臂 run_name 不同、
    # cfg 同文件），归一为占位符后比较 —— 其余键全部逐字段对拍。
    for r in (result_ext, result_man):
        r['commit']['run_dir'] = '<RUN_DIR>'
        r['commit']['pieces_dir'] = '<PIECES_DIR>'
        r['commit']['intermediate'] = '<INTERMEDIATE>'
        r['config']['path'] = '<CFG>'
    assert result_ext == result_man
    assert result_ext['config']['strategy'] == {'mode': 'race', 'race_budget': 600,
                                                'race_gate': 0.5}
    assert result_ext['config']['solver_opts'] == EXTREME_SOLVER_OPTS
    for rec in result_ext['solve']:
        assert rec['solver_opts'] == EXTREME_SOLVER_OPTS
        assert 'quadtree_depth' not in rec['solver_opts']
    assert [r['seed'] for r in result_ext['solve']] == [0, 1]
    assert result_ext['solve'][1]['killed'] is True
    assert result_ext['best'] == result_ext['portfolio']['incumbent']
    # ---- strategy.json（mode=race 复用；started_at 时间戳除外）+ 门杀决策
    plan_ext.pop('started_at'), plan_man.pop('started_at')
    assert plan_ext == plan_man == {'mode': 'race', 'total_budget': 905,
                                    'planned_seeds': [0, 1],
                                    'race': {'gate_seconds': 300.0}}
    assert rows_ext == rows_man
    assert [r['seed'] for r in rows_ext] == [0, 1]
    assert all(r['rule'] == R5_REASON for r in rows_ext)
    assert [r['would_kill'] for r in rows_ext] == [False, True]

    # ---- run_stats.jsonl：extreme 行 additive 加档位键、class_key 与手敲臂一致
    lines = _read_stats(stats)
    assert len(lines) == 2
    ext_line, man_line = lines
    assert ext_line['config']['extreme'] == {'budget': 600}
    assert 'extreme' not in man_line['config']
    assert ext_line['class_key'] == man_line['class_key']
    assert ext_line['best_density'] == man_line['best_density']


def test_extreme_non_extreme_run_stats_no_extreme_key(iso_env, capsys, monkeypatch):
    """零回归：无 --extreme 的普通 run，run_stats 行 config 段无 extreme 键。"""
    tmp, runs, stats, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    _patch_solve(monkeypatch, {(0, ''): [(1.0, 0.80), (2.0, 0.81)]})
    rc = main([str(cfg_path), '--time', '2'])
    assert rc == 0
    capsys.readouterr()
    (line,) = _read_stats(stats)
    assert 'extreme' not in line['config']
    assert set(line['config']) == {'time', 'per_type', 'quantities'}


# -------------------------------------------------------------- 互斥矩阵


@pytest.mark.parametrize('flag_argv', [
    ['--strategy'],
    ['--strategy', 'race'],
    ['--strategy', 'se'],
    ['--kill', 'shadow'],
    ['--solver-opts', '{"exploration_pct": 0.7}'],
    ['--rotate-opts'],
    ['--se-screen', '90'],
    ['--se-extend', '180'],
    ['--race-budget', '600'],
    ['--race-gate', '0.5'],
])
def test_extreme_mutex_with_strategy_and_knob_flags_exit_1(iso_env, capsys, flag_argv):
    """--extreme 与任一策略/旋钮旗标同给 → 退出 1 + 中文报错，不留空 run_dir。"""
    tmp, runs, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--extreme', '--time', '905', *flag_argv])
    assert rc == 1
    err = capsys.readouterr().err
    assert '--extreme 与' in err and '互斥' in err
    assert flag_argv[0] in err                       # 报错点名冲突旗标
    assert list(runs.iterdir()) == []                # 配置错误在 new_run_dir 之前拦下


@pytest.mark.parametrize('budget', ['0', '900', '2400', '-600'])
def test_extreme_budget_domain_rejects_non_600_1200(iso_env, capsys, budget):
    """--extreme-budget 仅收 600/1200 两档（2400s+ 门判别力失效硬边界）。"""
    tmp, runs, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--extreme', '--time', '905',
               '--extreme-budget', budget])
    assert rc == 1
    err = capsys.readouterr().err
    assert '--extreme-budget 仅收 600 或 1200' in err and budget in err
    assert list(runs.iterdir()) == []


def test_extreme_budget_subordinate_flag_requires_extreme(iso_env, capsys):
    """--extreme-budget 单独给出（无 --extreme）= 从属旗标笔误，退出 1。"""
    tmp, runs, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--extreme-budget', '600'])
    assert rc == 1
    assert '--extreme-budget 须与 --extreme 同给' in capsys.readouterr().err
    assert list(runs.iterdir()) == []


# ------------------------------------------------------- 预算下限与必填守卫


@pytest.mark.parametrize('total', ['904', '600', '100'])
def test_extreme_total_budget_below_min_reuses_race_plan_error(iso_env, capsys, total):
    """T < 905（600 档 = 首轮全程 602.5 + 一轮门段 302.5）→ 沿用 race_plan 的
    StrategyBudgetError 报错路径退出 1（race 概念上至少 1 豁免 + 1 门杀候选）。"""
    tmp, runs, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--extreme', '--time', total])
    assert rc == 1
    assert '预算不足' in capsys.readouterr().err
    assert list(runs.iterdir()) == []


def test_extreme_requires_total_budget_time(iso_env, capsys):
    """--extreme 无 --time → 策略模式守卫退出 1（糖衣展开复用，零新机制）。"""
    tmp, runs, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--extreme'])
    assert rc == 1
    assert '策略模式需 --time 总预算' in capsys.readouterr().err
    assert list(runs.iterdir()) == []


# ------------------------------------------------------- 1200 档展开（预算上界）


def test_extreme_budget_1200_expands_race_budget_and_gate(iso_env, capsys,
                                                          monkeypatch):
    """--extreme-budget 1200：race_budget=1200、门 600s、统计档位回显 1200。"""
    tmp, runs, stats, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0])
    # race_plan(1810, 1200, 0.5) = (2, 600.0)：seed0 豁免跑满 / seed1 门杀。
    traj = {(0, ''): [(100.0, 0.800), (600.0, 0.840), (1200.0, 0.860)],
            (1, ''): [(100.0, 0.799), (601.0, 0.839)]}
    fake = _patch_solve(monkeypatch, traj)
    rc = main([str(cfg_path), '--extreme', '--time', '1810',
               '--extreme-budget', '1200', '--name', 'e1200'])
    assert rc == 0
    out = capsys.readouterr().out
    assert '每 seed 1200s 预算，门时刻 600s' in out
    assert [c[:2] for c in fake.calls] == [(0, 1200), (1, 1200)]
    assert all(c[3] == EXTREME_SOLVER_OPTS for c in fake.calls)
    (line,) = _read_stats(stats)
    assert line['config']['extreme'] == {'budget': 1200}
    dirs = [d for d in runs.iterdir() if d.name.startswith('e1200_')]
    assert len(dirs) == 1
    plan = json.loads((dirs[0] / 'strategy.json').read_text(encoding='utf-8'))
    assert plan['race'] == {'gate_seconds': 600.0} and plan['total_budget'] == 1810


# ------------------------------------------------------- 常量契约 + --help 冒烟


def test_extreme_constants_contract():
    """常量契约：opts 三键固化实验结论值；预算档恰 600/1200、默认 600。"""
    assert EXTREME_SOLVER_OPTS == {'exploration_pct': 0.7,
                                   'early_termination': False, 'num_workers': 4}
    assert EXTREME_BUDGETS == (600, 1200)
    assert EXTREME_BUDGET_S == 600


def test_help_contains_extreme_flags():
    """--help 含两个新旗标（python -m 子进程冒烟，AC：跑通即分层无反向）。"""
    proc = subprocess.run(
        [sys.executable, '-m', 'materialsorting.cli.run_config', '--help'],
        capture_output=True, text=True, encoding='utf-8', cwd=str(_SRC.parents[1]))
    assert proc.returncode == 0
    assert '--extreme' in proc.stdout and '--extreme-budget' in proc.stdout


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
