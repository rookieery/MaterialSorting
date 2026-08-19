"""PC-002 ``cli/portfolio`` 控制器 + ``run_config`` portfolio 旗标测试。

驱动方式：**fake solve**（``run_serial_portfolio(solve=...)`` / monkeypatch
``rc_mod.solve_pieces``）注入确定帧序列，覆盖：
  - incumbent banking：3 seed 交错轨迹下 incumbent = 全局最大帧 density、来源字段
    正确；被 kill / 中途停止（Ctrl-C）的 seed 的最优帧参与全局最优（修复 best
    只看 per-seed 终值的盲区）；
  - R0 达标即停：seed2 中途达标 → seed2 被 stop（killed=True + R0 kill_reason）、
    seed3 不再启动（per_seed 无记录）、退出码 0；触发帧先入账后停；
  - 无 --target：跑满全队列，行为与旧版一致；
  - result.json portfolio 段 / best 语义：多 seed → best == incumbent（含完整
    placed_items）；单 seed 无 --target → 空 portfolio 段 + best 旧语义；
  - ``--target`` 越界 / ``--params`` 坏文件 → 退出码 1；
  - 进度输出：per-seed 新最优行 + 跨 seed 反超 incumbent 行 + 轮次头（--quiet 全抑制）；
  - 分层：portfolio 模块级不 import web。
"""
from __future__ import annotations

import ast
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
from materialsorting.cli.config import load_config
from materialsorting.cli.pipeline import commit_from_config, new_run_dir
from materialsorting.cli.portfolio import (ControllerParamsError, PortfolioController,
                                           R0_REASON, load_controller_params,
                                           run_serial_portfolio)
from materialsorting.cli.run_config import main
from materialsorting.web import server as server_mod

# 与 test_cli_run_config 同构的合成母版：6 片有码号（sizes 28/29 各 3 片）。
_SYNTH_BLOCKS = [
    ('blk x.28', (0.12345, 0.6789, 400.123456, 700.987654)),
    ('blk x.29', (0.12345, 0.6789, 400.123456, 720.987654)),
    ('zz 9.28', (1.5, 2.25, 200.111111, 90.222222)),
    ('zz 9.29', (1.5, 2.25, 200.111111, 95.222222)),
    ('M55#2 a.28', (2.75, 3.125, 120.333333, 60.444444)),
    ('M55#2 a.29', (2.75, 3.125, 120.333333, 65.444444)),
]
_N_PIECES = len(_SYNTH_BLOCKS)


def _make_master_dxf(path: Path) -> Path:
    doc = ezdxf.new('R12')
    for name, (x, y, w, h) in _SYNTH_BLOCKS:
        blk = doc.blocks.new(name=name)
        poly = blk.add_polyline2d(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], dxfattribs={'layer': '1'})
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
    master = _make_master_dxf(tmp_path / 'synthetic_master.dxf')
    return tmp_path, runs, master


# ------------------------------------------------------- fake solve 驱动装置


def _frame(seed: int, idx: int, elapsed: float, density: float) -> dict:
    """构造一帧：placed_items 布局编码 (seed, idx) —— 验证 incumbent 来源字段用。"""
    return {
        'type': 'frame',
        'elapsed': float(elapsed),
        'phase': 'exploring',
        'density': float(density),
        'density_sparrow': float(density) + 0.02,
        'width_mm': 50000.0 - float(seed) * 1000.0 - float(idx) * 10.0,
        'placed_items': [
            {'id': f'g0{k + 1}_28', 'rotation': 0.0,
             'translation': [float(seed * 10000 + idx * 100 + k), 0.0]}
            for k in range(_N_PIECES)
        ],
    }


def _rec(seed: int, frames: list[dict], *, killed=False, reason=None) -> dict:
    """帧序列 → solve_pieces 同形返回记录（killed 时取 best-so-far 帧口径）。"""
    best = max(frames, key=lambda fr: fr['density']) if frames else None
    final = frames[-1] if frames else None
    rec = {
        'seed': seed, 'n_items': _N_PIECES, 'n_eroded': 0,
        'total_area_mm2': 1_000_000.0,
        'width_mm': (best if killed else final)['width_mm'],
        'real_density': (best if killed else final)['density'],
        'density_sparrow': (best if killed else final)['density_sparrow'],
        'placed_items': _N_PIECES,
        'elapsed': (best if killed else final)['elapsed'],
    }
    if killed:
        rec['killed'] = True
        rec['kill_reason'] = reason or 'should_stop'
    return rec


def _fake_solve(trajectories: dict[int, list[tuple[float, float]]],
                *, interrupt_at: tuple[int, int] | None = None,
                calls: list[int] | None = None):
    """构造伪 solve：按 ``{seed: [(elapsed, density), ...]}`` 逐帧回调。

    契约镜像 ``solve_pieces``：每帧先 ``on_progress``（入账）再 ``should_stop``
    （触发即停，best-so-far 帧交付 ``killed=True``）；``interrupt_at=(seed, idx)``
    在该帧投递后抛 KeyboardInterrupt（Ctrl-C 中断路径）。
    """
    def solve(cfg, run_dir, *, seed, time_budget=None, on_progress=None,
              should_stop=None, **kw):
        if calls is not None:
            calls.append(seed)
        frames: list[dict] = []
        for idx, (elapsed, d) in enumerate(trajectories[seed]):
            fr = _frame(seed, idx, elapsed, d)
            frames.append(fr)
            if on_progress is not None:
                on_progress(fr)
            if interrupt_at is not None and (seed, idx) == interrupt_at:
                raise KeyboardInterrupt
            if should_stop is not None:
                verdict = should_stop(fr)
                if verdict:
                    return _rec(seed, frames, killed=True,
                                reason=verdict if isinstance(verdict, str) else None)
        return _rec(seed, frames)

    return solve


def _run(trajectories, seeds, *, target=None, params=None, echo=None,
         interrupt_at=None, calls=None):
    controller = PortfolioController(seeds=seeds, target=target, params=params, echo=echo)
    run = run_serial_portfolio(
        None, None, controller=controller, time_budget=2,
        solve=_fake_solve(trajectories, interrupt_at=interrupt_at, calls=calls))
    return run


# ------------------------------------------------------- AC#1 incumbent banking


def test_incumbent_is_global_max_frame_across_seeds():
    """AC#1：3 seed 交错轨迹 → incumbent = 全局最大帧 density，来源字段正确
    （seed/frame_index/elapsed/width_mm/placed_items 均取自该帧）。"""
    traj = {0: [(1.0, 0.80), (2.0, 0.84)],
            1: [(1.0, 0.82), (2.0, 0.86)],
            2: [(1.0, 0.83), (2.0, 0.85)]}
    run = _run(traj, [0, 1, 2])
    inc = run.controller.incumbent
    assert inc['density'] == pytest.approx(0.86, abs=1e-9)   # 全局最大帧（seed1 第 2 帧）
    assert inc['seed'] == 1 and inc['frame_index'] == 1
    assert inc['elapsed'] == pytest.approx(2.0)
    assert inc['width_mm'] == pytest.approx(50000.0 - 1000.0 - 10.0)
    expect_placed = _frame(1, 1, 2.0, 0.86)['placed_items']
    assert inc['placed_items'] == expect_placed             # 完整布局来自来源帧


def test_incumbent_strict_improvement_only():
    """等值不覆盖：后 seed 追平全局最优不夺走 incumbent（先到者持有）。"""
    traj = {0: [(1.0, 0.86)], 1: [(1.0, 0.86)]}
    run = _run(traj, [0, 1])
    assert run.controller.incumbent['seed'] == 0
    assert run.controller.incumbent['frame_index'] == 0


def test_killed_seed_best_frame_joins_incumbent():
    """AC#1：被 kill 的 seed 最优帧参与全局最优 —— seed1 第 1 帧 0.88 触发 R0 被
    kill，其峰值（=触发帧）高于 seed0 终值与 seed2 全部帧，incumbent 归 seed1。"""
    traj = {0: [(1.0, 0.80), (2.0, 0.82)],
            1: [(1.0, 0.88), (2.0, 0.80)],   # 峰值后回落（best-so-far 交付口径）
            2: [(1.0, 0.83), (2.0, 0.84)]}
    run = _run(traj, [0, 1, 2], target=0.88)   # 仅 seed1 第 1 帧达标
    inc = run.controller.incumbent
    assert inc['seed'] == 1 and inc['frame_index'] == 0
    assert inc['density'] == pytest.approx(0.88, abs=1e-9)
    assert [r['seed'] for r in run.solves] == [0, 1]         # seed2 不再启动
    assert run.solves[1]['killed'] is True
    assert run.solves[1]['kill_reason'] == R0_REASON
    # kill 后回落的帧（0.80）不覆盖 incumbent：per_seed best_density 停在峰值
    assert run.controller.per_seed[1]['best_density'] == pytest.approx(0.88, abs=1e-9)


def test_r0_first_frame_immediately_banked():
    """首帧即达标：触发帧先入账（incumbent 非空）后停 —— killed 永不空手。"""
    traj = {0: [(1.0, 0.90), (2.0, 0.85)], 1: [(1.0, 0.70)]}
    run = _run(traj, [0, 1], target=0.90)
    assert run.controller.queue_stopped is True
    assert [r['seed'] for r in run.solves] == [0]
    assert run.controller.incumbent['density'] == pytest.approx(0.90, abs=1e-9)
    assert run.controller.incumbent['frame_index'] == 0


def test_interrupted_seed_frames_already_banked():
    """AC#1（中途停止）：seed1 第 2 帧后 Ctrl-C → 已收帧入账 incumbent（交付
    不变量），solves 只含 seed0，last_round 定位中断轮。"""
    traj = {0: [(1.0, 0.80), (2.0, 0.81)],
            1: [(1.0, 0.83), (2.0, 0.85), (3.0, 0.84)]}
    run = _run(traj, [0, 1, 2], interrupt_at=(1, 1))
    assert run.interrupted is True
    assert run.last_round == (2, 1)
    assert [r['seed'] for r in run.solves] == [0]
    inc = run.controller.incumbent
    assert inc['seed'] == 1 and inc['frame_index'] == 1       # 中断前的已收帧
    assert inc['density'] == pytest.approx(0.85, abs=1e-9)


# ------------------------------------------------------- AC#2 R0 达标即停


def test_r0_stops_seed_and_skips_remaining():
    """AC#2：seed2（队列第 2 个）中途达标 → 该 seed 被 stop、seed3 不再启动、
    per_seed 对未启动 seed 无记录；退出码 0 由 CLI 层测试覆盖。"""
    calls: list[int] = []
    traj = {0: [(1.0, 0.70), (2.0, 0.72)],
            1: [(1.0, 0.74), (2.0, 0.78), (3.0, 0.76)],
            2: [(1.0, 0.90)]}
    run = _run(traj, [0, 1, 2], target=0.78, calls=calls)
    assert calls == [0, 1]                       # seed3 从未启动
    assert run.controller.queue_stopped is True
    assert run.interrupted is False
    assert [r['seed'] for r in run.solves] == [0, 1]
    assert run.solves[1]['killed'] is True
    assert run.solves[1]['kill_reason'] == R0_REASON
    assert [e['seed'] for e in run.controller.per_seed] == [0, 1]   # 无 seed2 记录
    # 触发帧（0.78）先入账后停：incumbent = 该帧（全局最大）
    assert run.controller.incumbent['density'] == pytest.approx(0.78, abs=1e-9)
    assert run.controller.incumbent['seed'] == 1
    assert run.controller.incumbent['frame_index'] == 1


def test_no_target_runs_full_queue():
    """AC#2：无 --target → 行为与现版一致（跑满全队列、无 killed、队列不停止）。"""
    calls: list[int] = []
    traj = {0: [(1.0, 0.80)], 1: [(1.0, 0.85)], 2: [(1.0, 0.82)]}
    run = _run(traj, [0, 1, 2], calls=calls)
    assert calls == [0, 1, 2]
    assert run.controller.queue_stopped is False
    assert [r['seed'] for r in run.solves] == [0, 1, 2]
    assert all('killed' not in r for r in run.solves)
    assert all(e['killed'] is False for e in run.controller.per_seed)


# ------------------------------------------------------- AC#3 portfolio 段 / best 语义


def test_portfolio_section_and_best_semantics():
    """AC#3：激活（多 seed）→ 段字段齐全 + best == incumbent；不激活（单 seed 无
    target）→ 空 portfolio 段 + best 旧语义（solve 数组 real_density 最大者、
    并列取先执行者）。"""
    traj = {0: [(1.0, 0.80), (2.0, 0.84)], 1: [(1.0, 0.86)]}
    run = _run(traj, [0, 1])
    sec = run.controller.portfolio_section()
    assert set(sec) == {'target', 'incumbent', 'per_seed', 'theta_history'}
    assert sec['target'] is None
    assert run.controller.best_record(run.solves) == sec['incumbent']
    assert [set(e) for e in sec['per_seed']] == [
        {'seed', 'killed', 'kill_reason', 'best_density', 'elapsed'}] * 2
    assert sec['theta_history'] == []
    assert sec['per_seed'][0]['best_density'] == pytest.approx(0.84, abs=1e-9)
    assert sec['per_seed'][1]['best_density'] == pytest.approx(0.86, abs=1e-9)

    # 不激活：单 seed 无 target → 空段 + 旧 best（帧 0.90 高于 final 0.85 也不入 best）
    run_single = _run({5: [(1.0, 0.90), (2.0, 0.85)]}, [5])
    assert run_single.controller.portfolio_section() == \
        {'target': None, 'incumbent': None, 'per_seed': [], 'theta_history': []}
    assert run_single.controller.best_record(run_single.solves) == run_single.solves[0]
    assert run_single.controller.best_record(run_single.solves)['real_density'] \
        == pytest.approx(0.85, abs=1e-9)          # 旧语义 = final，不看帧


def test_params_stored_on_controller():
    """--params 加载的标定参数保存于控制器（PC-003 消费；PC-002 只透传）。"""
    run = _run({0: [(1.0, 0.8)]}, [0], target=0.9,
               params={'tau0': 0.3, 'W': 10})
    assert run.controller.params == {'tau0': 0.3, 'W': 10}


# ------------------------------------------------------- load_controller_params


def test_load_controller_params_matrix(tmp_path):
    """--params 加载矩阵：合法（含 BOM）/ 不存在 / 非法 JSON / 顶层非对象。"""
    ok = tmp_path / 'params_ok.json'
    ok.write_bytes(b'\xef\xbb\xbf{"tau0": 0.3}')       # 带 BOM（utf-8-sig 容错）
    assert load_controller_params(ok) == {'tau0': 0.3}

    with pytest.raises(ControllerParamsError, match='不存在'):
        load_controller_params(tmp_path / 'nope.json')
    bad = tmp_path / 'params_bad.json'
    bad.write_text('{not json', encoding='utf-8')
    with pytest.raises(ControllerParamsError, match='不是合法 JSON'):
        load_controller_params(bad)
    arr = tmp_path / 'params_arr.json'
    arr.write_text('[1, 2]', encoding='utf-8')
    with pytest.raises(ControllerParamsError, match='JSON 对象'):
        load_controller_params(arr)


# ------------------------------------------------------- 进度输出（AC#4）


def test_progress_lines_takeover_and_per_seed():
    """AC#4：per-seed 新最优行保留旧格式；跨 seed 反超打 incumbent 行；
    轮次头与全部进度行在 --quiet 下全抑制（echo=None）。"""
    lines: list[str] = []

    def echo(msg: str) -> None:
        lines.append(msg)

    traj = {0: [(1.0, 0.80), (2.0, 0.84)],
            1: [(1.0, 0.82), (2.0, 0.86)]}
    _run(traj, [0, 1], echo=echo)
    assert any('（原面积口径新最优）' in m and '[seed 0]' in m for m in lines)
    assert any('（原面积口径新最优）' in m and '[seed 1]' in m for m in lines)
    takeover = [m for m in lines if 'incumbent' in m]
    assert len(takeover) == 1                             # seed1 反超 0.86 恰一次
    assert 'seed 1' in takeover[0] and '86.00%' in takeover[0]
    assert '全局最优' in takeover[0]

    quiet_lines: list[str] = []

    def qecho(msg: str) -> None:
        quiet_lines.append(msg)

    # --quiet = echo=None：静默不影响 banking（incumbent 照常入账、无任何输出）
    run_quiet = _run(traj, [0, 1], echo=None)
    assert not quiet_lines
    assert run_quiet.controller.incumbent['density'] == pytest.approx(0.86, abs=1e-9)
    # echo 给定但零反超（单 seed）：无 incumbent 行（输出与旧版一致，见下一条测试）
    _run({3: [(1.0, 0.8), (2.0, 0.9)]}, [3], echo=qecho)
    assert all('incumbent' not in m for m in quiet_lines)


def test_first_seed_improvements_no_incumbent_line():
    """首 seed 的自我刷新不打 incumbent 行（单 seed 输出与旧版逐字一致）。"""
    lines: list[str] = []

    def echo(msg: str) -> None:
        lines.append(msg)

    _run({0: [(1.0, 0.80), (2.0, 0.84), (3.0, 0.82)]}, [0], echo=echo)
    assert len(lines) == 2                                # 仅两条 per-seed 新最优
    assert all('incumbent' not in m for m in lines)
    assert all('（原面积口径新最优）' in m for m in lines)


# ------------------------------------------------------- main() 端到端（AC#2/AC#3）


def _patch_fake_solve(monkeypatch, trajectories):
    from materialsorting.cli import run_config as rc_mod
    monkeypatch.setattr(rc_mod, 'solve_pieces', _fake_solve(trajectories))


def test_main_r0_end_to_end(iso_env, capsys, monkeypatch):
    """AC#2 端到端：--target 下 seed2 中途达标 → 退出码 0、seed3 不启动、
    portfolio 段（target/incumbent/per_seed killed）与 best==incumbent 落盘。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg_r0.json', master, seeds=[0, 1, 2])
    traj = {0: [(1.0, 0.70), (2.0, 0.72)],
            1: [(1.0, 0.74), (2.0, 0.78), (3.0, 0.76)],
            2: [(1.0, 0.90)]}
    _patch_fake_solve(monkeypatch, traj)

    rc = main([str(cfg_path), '--time', '2', '--target', '0.78'])
    out = capsys.readouterr().out
    assert rc == 0                                        # R0 提前停仍成功
    assert 'R0 达标即停' in out and '剩余 1 个 seed 未启动' in out
    assert '── 第 1/3 轮（seed=0）开始 ──' in out         # --target 下轮次头在场

    (rd,) = list(runs.iterdir())
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert set(result) == {'config', 'commit', 'solve', 'best', 'portfolio'}
    assert [s['seed'] for s in result['solve']] == [0, 1]
    assert result['solve'][1]['killed'] is True
    assert result['solve'][1]['kill_reason'] == R0_REASON
    sec = result['portfolio']
    assert sec['target'] == 0.78
    assert [e['seed'] for e in sec['per_seed']] == [0, 1]
    assert sec['per_seed'][1]['killed'] is True
    assert sec['per_seed'][1]['kill_reason'] == R0_REASON
    assert sec['per_seed'][1]['best_density'] == pytest.approx(0.78, abs=1e-9)
    assert sec['theta_history'] == []
    inc = sec['incumbent']
    assert inc['density'] == pytest.approx(0.78, abs=1e-9)
    assert inc['seed'] == 1 and inc['frame_index'] == 1
    assert isinstance(inc['placed_items'], list) \
        and len(inc['placed_items']) == _N_PIECES          # 完整布局（非计数）
    assert result['best'] == inc                          # best 与 incumbent 一致
    # 末行汇总（incumbent 形态归一后格式不变）
    last_line = out.strip().splitlines()[-1]
    assert 'real_density（原面积口径）= 78.00%' in last_line
    assert f'片数 = {_N_PIECES}' in last_line


def test_main_single_seed_no_target_empty_portfolio(iso_env, capsys, monkeypatch):
    """AC#3：不带 --target 的单 seed 运行 → 空 portfolio 段、best 与旧语义兼容
    （best == solve[0]，real_density=final 口径）。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg_single.json', master)
    traj = {0: [(1.0, 0.90), (2.0, 0.85)]}               # 帧峰 0.90 > final 0.85
    _patch_fake_solve(monkeypatch, traj)

    rc = main([str(cfg_path), '--time', '2', '--quiet'])
    assert rc == 0
    (rd,) = list(runs.iterdir())
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert result['portfolio'] == {'target': None, 'incumbent': None,
                                   'per_seed': [], 'theta_history': []}
    assert result['best'] == result['solve'][0]           # 旧语义引用（非 incumbent）
    assert result['best']['real_density'] == pytest.approx(0.85, abs=1e-9)
    out = capsys.readouterr().out
    assert '轮（seed=' not in out                          # 单 seed 无旗标：无轮次头
    assert 'real_density（原面积口径）= 85.00%' in out.strip().splitlines()[-1]


def test_main_no_target_multi_seed_best_is_incumbent(iso_env, monkeypatch):
    """AC#1 盲区修复端到端：多 seed 无 --target → best=incumbent（帧级全局最优，
    可高于任一 seed 终值）。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg_multi.json', master, seeds=[0, 1])
    traj = {0: [(1.0, 0.80), (2.0, 0.86), (3.0, 0.84)],  # seed0 帧峰 0.86、终值 0.84
            1: [(1.0, 0.84), (2.0, 0.85)]}               # seed1 终值 0.85
    _patch_fake_solve(monkeypatch, traj)

    rc = main([str(cfg_path), '--time', '2', '--quiet'])
    assert rc == 0
    (rd,) = list(runs.iterdir())
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    inc = result['portfolio']['incumbent']
    assert inc['seed'] == 0 and inc['frame_index'] == 1
    assert inc['density'] == pytest.approx(0.86, abs=1e-9)
    assert result['best'] == inc                          # 高于两 seed 终值（0.85）
    assert max(s['real_density'] for s in result['solve']) < 0.86


def test_main_target_out_of_range_exit_1(iso_env, capsys, monkeypatch):
    """--target 越界（0 / >1）→ 配置错误退出 1，不建 run_dir。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg_t.json', master)
    for bad in ('0', '1.5', '-0.1'):
        rc = main([str(cfg_path), '--target', bad])
        assert rc == 1
        assert '--target' in capsys.readouterr().err
    assert list(runs.iterdir()) == []


def test_main_params_flag_valid_and_invalid(iso_env, capsys, monkeypatch):
    """--params：合法文件加载通过（rc=0）；不存在 / 非法 JSON → 配置错误退出 1。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg_p.json', master)
    traj = {0: [(1.0, 0.8)]}
    _patch_fake_solve(monkeypatch, traj)

    ok = tmp / 'controller_params.json'
    ok.write_text(json.dumps({'tau0': 0.3, 'W': 10}), encoding='utf-8')
    assert main([str(cfg_path), '--time', '2', '--quiet',
                 '--params', str(ok)]) == 0

    rc = main([str(cfg_path), '--params', str(tmp / 'nope.json')])
    assert rc == 1 and '参数文件不存在' in capsys.readouterr().err
    bad = tmp / 'bad.json'
    bad.write_text('{oops', encoding='utf-8')
    rc = main([str(cfg_path), '--params', str(bad)])
    assert rc == 1 and '不是合法 JSON' in capsys.readouterr().err


def test_main_r0_with_quiet_still_prints_outcome(iso_env, capsys, monkeypatch):
    """--quiet 抑制轮次头/进度/incumbent 行，但 R0 终局事件与最终汇总仍输出。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg_q.json', master, seeds=[0, 1])
    traj = {0: [(1.0, 0.60)], 1: [(1.0, 0.62), (2.0, 0.64)]}
    _patch_fake_solve(monkeypatch, traj)

    rc = main([str(cfg_path), '--time', '2', '--quiet', '--target', '0.64'])
    out = capsys.readouterr().out
    assert rc == 0
    assert '轮（seed=' not in out and '（原面积口径新最优）' not in out
    assert 'R0 达标即停' in out
    assert 'real_density（原面积口径）= 64.00%' in out.strip().splitlines()[-1]


# ------------------------------------------------------- 分层 + 导入冒烟


def test_layering_portfolio_no_web_import():
    """portfolio 模块级（含函数内）不 import web —— 只经 pipeline 间接复用。"""
    from materialsorting.cli import portfolio as pf
    tree = ast.parse(Path(pf.__file__).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parts = [p for p in (node.module or '').split('.') if p]
            assert 'web' not in parts, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert 'web' not in alias.name.split('.'), alias.name


def test_module_import_smoke():
    """``python -m materialsorting.cli.portfolio`` 导入零输出零副作用。"""
    import os
    import subprocess
    env = {**os.environ, 'PYTHONPATH': str(_SRC)}
    r = subprocess.run([sys.executable, '-m', 'materialsorting.cli.portfolio'],
                       capture_output=True, env=env, cwd=str(_SRC.parent), timeout=60)
    assert r.returncode == 0
    assert r.stdout == b'' and r.stderr == b''


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

