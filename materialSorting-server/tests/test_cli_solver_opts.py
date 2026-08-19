"""PC-006 solver_opts 透传与配置轮换测试。

三层驱动：
  - ``build_instance`` 直测（synthetic pieces）：不传 solver_opts 时 config 字段与
    现状一致；exploration_pct 换算两段 int 秒（与 total_computation_time 互斥）；
    越界 clamp；quadtree_depth/num_workers 透传；非法值忽略。
  - 透传链：solve_pieces 把 solver_opts 并入 solve_params（monkeypatch fake proc
    断言）+ 真多进程 solve_worker 消费（JSON 可序列化、Windows spawn 安全）。
  - 轮换（fake solve）：k=5、池 4 档时第 5 个 seed 回到 pool[0]；--solver-opts 与
    --rotate-opts 同给 / JSON 坏串 / 非对象 → 退出码 1；固定档全 seed 生效 +
    result.json config 段回显；--rotate-opts 时 config 段回显 rotate_opts。
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import materialsorting.web.solver as web_solver
from materialsorting import paths as paths_mod
from materialsorting.cli.config import load_config
from materialsorting.cli.pipeline import commit_from_config, new_run_dir, solve_pieces
from materialsorting.cli.portfolio import PortfolioController, run_serial_portfolio
from materialsorting.cli.run_config import (SOLVER_OPTS_POOL, main,
                                            rotation_opts_for)
from materialsorting.web.solver import build_instance, solve_with_callback_proc

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
    master = _make_master_dxf(tmp_path / 'synthetic_master.dxf')
    return tmp_path, runs, master


# --------------------------------------------- AC#1 build_instance 直测


def test_build_instance_no_opts_matches_baseline(synthetic_pieces):
    """AC#1：不传 solver_opts（含 None / 空档）时 config 字段与现状逐项一致 ——
    total 模式（80/20 自动分段）+ quadtree_depth=4 + num_workers=4 + seed 透传。"""
    pieces, gate_mm = synthetic_pieces
    _, cfg, _, _, _ = build_instance(pieces, gate_mm, time_budget=60, seed=7)
    # 现状 = StripPackingConfig(total_computation_time=60, seed=7, num_workers=4)
    # 的 spyrrow 默认行为：80% 探索 / 20% 压缩。
    assert cfg.exploration_time == timedelta(seconds=48)
    assert cfg.compression_time == timedelta(seconds=12)
    assert cfg.quadtree_depth == 4
    assert cfg.num_workers == 4
    assert cfg.seed == 7
    # None / 空档 / 白名单全非法 → 同一形态（现行行为不变）。
    for opts in (None, {}, {'bogus': 1, 'exploration_pct': 'oops'}):
        _, cfg2, _, _, _ = build_instance(
            pieces, gate_mm, time_budget=60, seed=7, solver_opts=opts)
        assert (cfg2.exploration_time, cfg2.compression_time,
                cfg2.quadtree_depth, cfg2.num_workers, cfg2.seed) == (
            cfg.exploration_time, cfg.compression_time,
            cfg.quadtree_depth, cfg.num_workers, cfg.seed)


def test_build_instance_exploration_pct_two_segments(synthetic_pieces):
    """AC#1：exploration_pct=0.6 → 两段 int 秒、和 ≈ time_budget（60/40）；
    两段模式与 total_computation_time 互斥（不再报 "not all 3" ValueError）。"""
    pieces, gate_mm = synthetic_pieces
    _, cfg, _, _, _ = build_instance(
        pieces, gate_mm, time_budget=100, seed=1,
        solver_opts={'exploration_pct': 0.6})
    assert cfg.exploration_time == timedelta(seconds=60)
    assert cfg.compression_time == timedelta(seconds=40)
    total = (cfg.exploration_time + cfg.compression_time).total_seconds()
    assert abs(total - 100) <= 1.0                     # 和 ≈ time_budget（int 取整容差）
    assert total == int(total)                          # 两段均为 int 秒
    # 换一档配比（0.9）：90/10。
    _, cfg9, _, _, _ = build_instance(
        pieces, gate_mm, time_budget=100, seed=1, solver_opts={'exploration_pct': 0.9})
    assert cfg9.exploration_time == timedelta(seconds=90)
    assert cfg9.compression_time == timedelta(seconds=10)
    # 小预算下两段均 >=1s（pct 极端也不出 0s 段）。
    _, cfg5, _, _, _ = build_instance(
        pieces, gate_mm, time_budget=5, seed=1, solver_opts={'exploration_pct': 0.95})
    assert cfg5.exploration_time >= timedelta(seconds=1)
    assert cfg5.compression_time >= timedelta(seconds=1)


def test_build_instance_exploration_pct_clamped(synthetic_pieces):
    """AC#1：越界 clamp —— pct<0.1 → 0.1、pct>0.95 → 0.95（100s 预算 → 10/90、95/5）。"""
    pieces, gate_mm = synthetic_pieces
    _, lo, _, _, _ = build_instance(
        pieces, gate_mm, time_budget=100, seed=1, solver_opts={'exploration_pct': 0.01})
    assert lo.exploration_time == timedelta(seconds=10)
    assert lo.compression_time == timedelta(seconds=90)
    _, hi, _, _, _ = build_instance(
        pieces, gate_mm, time_budget=100, seed=1, solver_opts={'exploration_pct': 5.0})
    assert hi.exploration_time == timedelta(seconds=95)
    assert hi.compression_time == timedelta(seconds=5)


def test_build_instance_quadtree_workers_passthrough(synthetic_pieces):
    """AC#1：quadtree_depth / num_workers 透传；depth 越界 clamp 到 [3,5]、
    workers 下限 1；非数值忽略回默认。"""
    pieces, gate_mm = synthetic_pieces
    _, cfg, _, _, _ = build_instance(
        pieces, gate_mm, time_budget=30, seed=1,
        solver_opts={'quadtree_depth': 5, 'num_workers': 2})
    assert cfg.quadtree_depth == 5
    assert cfg.num_workers == 2
    _, deep, _, _, _ = build_instance(
        pieces, gate_mm, time_budget=30, seed=1, solver_opts={'quadtree_depth': 9})
    assert deep.quadtree_depth == 5                    # 越界 clamp
    _, shallow, _, _, _ = build_instance(
        pieces, gate_mm, time_budget=30, seed=1, solver_opts={'quadtree_depth': 1})
    assert shallow.quadtree_depth == 3
    _, w0, _, _, _ = build_instance(
        pieces, gate_mm, time_budget=30, seed=1, solver_opts={'num_workers': 0})
    assert w0.num_workers == 1
    _, junk, _, _, _ = build_instance(
        pieces, gate_mm, time_budget=30, seed=1,
        solver_opts={'quadtree_depth': 'deep', 'num_workers': None})
    assert junk.quadtree_depth == 4 and junk.num_workers == 4   # 非法忽略 = 默认


def test_build_instance_opts_do_not_touch_instance(synthetic_pieces):
    """旋钮只改 config 不改 instance：strip_height / items / pid_meta 与无旋钮一致
    （求解约束带 = min(gate, PLOT_SAFE) 口径不受 solver_opts 扰动）。"""
    pieces, gate_mm = synthetic_pieces
    i1, _, meta1, area1, _ = build_instance(pieces, gate_mm, time_budget=30, seed=1)
    i2, _, meta2, area2, _ = build_instance(
        pieces, gate_mm, time_budget=30, seed=1,
        solver_opts={'exploration_pct': 0.5, 'quadtree_depth': 3})
    assert i1.strip_height == i2.strip_height
    assert [it.id for it in i1.items] == [it.id for it in i2.items]
    assert set(meta1) == set(meta2)
    assert area1 == area2


# --------------------------------------------- AC#2 透传链（solve_pieces / worker）


class _FakeProc:
    def __init__(self):
        self.terminated = False
        self.joined = False

    def is_alive(self) -> bool:
        return not (self.terminated or self.joined)

    def terminate(self) -> None:
        self.terminated = True

    def join(self, timeout=None) -> None:
        self.joined = True

    @property
    def exitcode(self):
        return 0


def _capturing_proc_solver(captured):
    """伪 solve_with_callback_proc：记录收到的 solve_params，同步投一帧 + final。"""
    def _impl(pieces, gate_mm, solve_params, *, on_manifest, on_report,
              on_process=None, **kw):
        captured.append(json.loads(json.dumps(solve_params)))   # 必须 JSON 可序列化
        proc = _FakeProc()
        if on_process is not None:
            on_process(proc)
        on_manifest({'pid_meta': {}, 'total_area': 1.0, 'n_eroded': 0,
                     'gate_mm': float(gate_mm)})
        frame = {'type': 'frame', 'elapsed': 1.0, 'phase': 'exploring',
                 'density': 0.8, 'density_sparrow': 0.82, 'width_mm': 5000.0,
                 'placed_items': [{'id': 'g01_28', 'rotation': 0.0,
                                   'translation': [0.0, 0.0]}] * _N_PIECES}
        on_report(frame)
        return proc, dict(frame, type='final'), 1.0, None
    return _impl


def test_solve_pieces_passes_opts_into_solve_params(iso_env, monkeypatch):
    """AC#2：solve_pieces 把 solver_opts 原样并入 solve_params（JSON 可序列化），
    返回记录附带 solver_opts 回显；不传时记录字段与旧版一致（零回归）。"""
    tmp, _, master = iso_env
    cfg = load_config(_write_config(tmp / 'cfg.json', master))
    run_dir = new_run_dir('pc006')
    commit_from_config(cfg, run_dir)

    captured = []
    monkeypatch.setattr(web_solver, 'solve_with_callback_proc',
                        _capturing_proc_solver(captured))
    opts = {'exploration_pct': 0.7, 'quadtree_depth': 5}
    rec = solve_pieces(cfg, run_dir, seed=3, time_budget=2, solver_opts=opts)

    assert len(captured) == 1
    assert captured[0]['solver_opts'] == opts             # 原样并入 solve_params
    assert captured[0]['seed'] == 3
    assert rec['solver_opts'] == opts                      # 记录回显

    # 不传：solve_params 仍带 solver_opts=None 键（build_instance 收 None = no-op），
    # 返回记录不含 solver_opts 键（旧字段集零回归）。
    captured.clear()
    rec2 = solve_pieces(cfg, run_dir, seed=3, time_budget=2)
    assert captured[0]['solver_opts'] is None
    assert 'solver_opts' not in rec2


def test_solver_opts_through_real_worker_spawn(real_or_synthetic_pieces):
    """AC#2：真多进程链路 —— solve_params 含 solver_opts 经 spawn 进子进程，
    solve_worker 原样交给 build_instance 构造两段模式 config 求解成功（不因
    旋钮坏键 / picklable 问题崩）。"""
    pieces, gate_mm = real_or_synthetic_pieces
    proc, final, elapsed, err = solve_with_callback_proc(
        pieces, gate_mm,
        {'time_budget': 2, 'seed': 1,
         'solver_opts': {'exploration_pct': 0.6, 'quadtree_depth': 3,
                         'bogus_key': 'ignored'}},
        on_manifest=lambda m: None, on_report=lambda r: None)
    assert err is None, f'unexpected error: {err}'
    assert final is not None
    assert proc.exitcode == 0


# --------------------------------------------- AC#3 轮换与 CLI 旗标


def _recording_fake_solve(captured):
    """fake solve：记录 (seed, solver_opts)，返回合法单帧记录。"""
    def _solve(cfg, run_dir, *, seed, time_budget=None, on_progress=None,
               should_stop=None, solver_opts=None):
        captured.append((seed, solver_opts))
        fr = {'elapsed': 1.0, 'phase': 'exploring', 'density': 0.8,
              'density_sparrow': 0.82, 'width_mm': 5000.0, 'placed_items': []}
        if on_progress is not None:
            on_progress(fr)
        return {'seed': seed, 'n_items': 1, 'n_eroded': 0, 'total_area_mm2': 1.0,
                'width_mm': 5000.0, 'real_density': 0.8, 'density_sparrow': 0.82,
                'placed_items': 0, 'elapsed': 1.0}
    return _solve


def test_rotation_pool_wraps_at_k5():
    """AC#3：池 4 档、k=5 → 第 5 个 seed 回到 pool[0]（空档 = 默认行为）。"""
    assert len(SOLVER_OPTS_POOL) == 4
    assert SOLVER_OPTS_POOL[0] is None                    # 池首空档 = 默认行为
    captured = []
    controller = PortfolioController(seeds=[0, 1, 2, 3, 4])
    run_serial_portfolio(
        None, None, controller=controller, time_budget=2,
        solve=_recording_fake_solve(captured),
        solver_opts_for=lambda index, seed: rotation_opts_for(index))
    assert [s for s, _ in captured] == [0, 1, 2, 3, 4]
    # 逐 seed 期望：pool[0..3] 后回到 pool[0]；空档以 solver_opts=None 到达。
    expected = [SOLVER_OPTS_POOL[i % 4] for i in range(5)]
    assert [o for _, o in captured] == expected
    assert captured[4][1] is SOLVER_OPTS_POOL[0]          # 第 5 个 seed 回到 pool[0]


def test_run_serial_portfolio_no_opts_for_keeps_call_shape():
    """solver_opts_for 缺省 = 现行调用形（solve 不收 solver_opts 键，旧 fake 兼容）。"""
    seen_kwargs = []

    def solve(cfg, run_dir, **kwargs):
        seen_kwargs.append(kwargs)
        return {'seed': kwargs['seed'], 'n_items': 1, 'n_eroded': 0,
                'total_area_mm2': 1.0, 'width_mm': 1.0, 'real_density': 0.5,
                'density_sparrow': 0.5, 'placed_items': 0, 'elapsed': 1.0}

    controller = PortfolioController(seeds=[0, 1])
    run = run_serial_portfolio(None, None, controller=controller,
                               time_budget=2, solve=solve)
    assert len(run.solves) == 2
    assert all('solver_opts' not in kw for kw in seen_kwargs)


def test_main_mutex_and_bad_json_exit_1(iso_env, capsys):
    """AC#3：--solver-opts 与 --rotate-opts 同给 → 退出码 1；JSON 坏串 / 非
    JSON 对象同按配置错误退出 1（且不创建 run_dir）。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--solver-opts', '{"exploration_pct": 0.7}',
               '--rotate-opts'])
    assert rc == 1
    assert '互斥' in capsys.readouterr().err
    rc = main([str(cfg_path), '--solver-opts', '{oops'])
    assert rc == 1
    assert '--solver-opts' in capsys.readouterr().err
    rc = main([str(cfg_path), '--solver-opts', '[1, 2]'])
    assert rc == 1
    assert 'JSON 对象' in capsys.readouterr().err
    assert list(runs.iterdir()) == []                     # 配置错误不创建 run_dir


def test_main_solver_opts_fixed_all_seeds(iso_env, capsys, monkeypatch):
    """AC#3：--solver-opts 固定档全 seed 生效（每个 seed 收到同一 dict），
    result.json config 段回显 solver_opts；stdout 有旋钮生效行。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg2.json', master, seeds=[0, 42])
    captured = []
    from materialsorting.cli import run_config as rc_mod
    monkeypatch.setattr(rc_mod, 'solve_pieces', _recording_fake_solve(captured))

    opts = {'exploration_pct': 0.9}
    rc = main([str(cfg_path), '--time', '2', '--solver-opts', json.dumps(opts)])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'solver_opts:' in out and '全 seed 生效' in out
    assert [o for _, o in captured] == [opts, opts]       # 全 seed 同档
    (rd,) = list(runs.iterdir())
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert result['config']['solver_opts'] == opts        # config 段回显
    assert 'rotate_opts' not in result['config']


def test_main_rotate_opts_pool_sequence(iso_env, capsys, monkeypatch):
    """AC#3：--rotate-opts 逐 seed 取池档（k=5 池 4 档：空档/档1/档2/档3/空档），
    result.json config 段回显 rotate_opts: true。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg3.json', master, seeds=[0, 1, 2, 3, 4])
    captured = []
    from materialsorting.cli import run_config as rc_mod
    monkeypatch.setattr(rc_mod, 'solve_pieces', _recording_fake_solve(captured))

    rc = main([str(cfg_path), '--time', '2', '--rotate-opts'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'rotate_opts:' in out and '4 档' in out
    assert [o for _, o in captured] == [
        SOLVER_OPTS_POOL[0], SOLVER_OPTS_POOL[1],
        SOLVER_OPTS_POOL[2], SOLVER_OPTS_POOL[3], SOLVER_OPTS_POOL[0]]
    (rd,) = list(runs.iterdir())
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert result['config']['rotate_opts'] is True
    assert 'solver_opts' not in result['config']


def test_main_no_flags_config_section_unchanged(iso_env, capsys, monkeypatch):
    """无旗标：result.json config 段字段集与 PC-001 基线一致（不加旋钮键）。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg4.json', master)
    captured = []
    from materialsorting.cli import run_config as rc_mod
    monkeypatch.setattr(rc_mod, 'solve_pieces', _recording_fake_solve(captured))

    rc = main([str(cfg_path), '--time', '2'])
    assert rc == 0
    (rd,) = list(runs.iterdir())
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert set(result['config']) == {'path', 'master_dxf', 'sizes', 'gate_mm',
                                     'time', 'seeds', 'per_type', 'quantities'}
    assert captured[0][1] is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
