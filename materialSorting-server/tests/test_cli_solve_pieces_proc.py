"""PC-001 ``cli/pipeline.solve_pieces`` 进程化 + 帧轨迹落盘 + ``should_stop`` 中止测试。

驱动方式分两层：
  - **fake solve**（monkeypatch ``web.solver.solve_with_callback_proc``）：注入确定
    帧序列，覆盖 curve/best_frame 落盘语义、killed 交付口径、恒 False 等价性；
  - **真实多进程求解**（合成母版 commit 产物）：terminate 链路端到端（真子进程被杀、
    on_process 句柄 join 无孤儿）+ 无 should_stop 回归。

帧字典口径与 ``web/solve_worker._emit_frame`` 一致（density 已在
``solve_with_callback_proc`` 内换算为原面积口径 —— fake 直接给出双口径终值）。
"""
from __future__ import annotations

import json
import multiprocessing
import sys
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import materialsorting.web.solver as web_solver
from materialsorting import paths as paths_mod
from materialsorting.nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
from materialsorting.cli.config import load_config
from materialsorting.cli.pipeline import commit_from_config, new_run_dir, solve_pieces

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
    """隔离环境（CONFIG_RUNS_DIR 指 tmp）+ 已 commit 的 run_dir + 已加载配置。"""
    runs = tmp_path / 'config_runs'
    runs.mkdir()
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(runs))
    master = _make_master_dxf(tmp_path / 'synthetic_master.dxf')
    cfg = load_config(_write_config(tmp_path / 'cfg.json', master))
    run_dir = new_run_dir('pc001')
    commit_from_config(cfg, run_dir)
    return tmp_path, runs, run_dir, cfg


# ------------------------------------------------------- fake solve 驱动装置


class _FakeProc:
    """伪 ``multiprocessing.Process`` 句柄：记录 terminate，join 后判死。"""

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
        return -15 if self.terminated else 0


def _placed(n: int) -> list[dict]:
    """n 条假放置记录（id 形如 g01_28，与合成母版 pid 同风格）。"""
    pids = ['g01_28', 'g02_29', 'g03_28', 'g04_29', 'g05_28', 'g06_29']
    return [{'id': pids[i % len(pids)], 'rotation': 0.0,
             'translation': [float(i * 100), 0.0]} for i in range(n)]


def _frame(i: int, density: float, *, elapsed=None, phase='exploring',
           width_mm=None, n_placed=None) -> dict:
    """构造一帧（density 为原面积口径终值，density_sparrow 略高 —— erode 后更松）。"""
    return {
        'type': 'frame',
        'elapsed': float(i * 1.5 if elapsed is None else elapsed),
        'phase': phase,
        'density': density,
        'density_sparrow': density + 0.02,
        'width_mm': 50000.0 - i * 100.0 if width_mm is None else width_mm,
        'placed_items': _placed(_N_PIECES if n_placed is None else n_placed),
    }


def _fake_proc_solver(frames, final=None):
    """构造伪 ``solve_with_callback_proc``：逐帧同步回调，terminate 后停止投帧。

    ``on_report`` 内 ``solve_pieces`` 会同步调 ``should_stop`` → 触发伪句柄
    ``terminate()`` → 本 fake 察觉后停止投帧并按「被终止」形态返回（final=None、
    err=exitcode 消息），与真实 terminate 链路的返回形态一致。
    """
    def _impl(pieces, gate_mm, solve_params, *, on_manifest, on_report,
              on_process=None, **kw):
        proc = _FakeProc()
        if on_process is not None:
            on_process(proc)
        on_manifest({'pid_meta': {}, 'total_area': 0.0, 'n_eroded': 0,
                     'gate_mm': float(gate_mm)})
        for fr in frames:
            on_report(dict(fr))
            if proc.terminated:
                break
        if proc.terminated:
            return proc, None, 42.0, 'worker process exited unexpectedly (code=-15)'
        last = frames[-1]
        final_data = final if final is not None else {
            'type': 'final',
            'density': last['density'],
            'density_sparrow': last['density_sparrow'],
            'width_mm': last['width_mm'],
            'elapsed': last['elapsed'],
            'placed_items': last['placed_items'],
        }
        return proc, final_data, 42.0, None
    return _impl


# ------------------------------------------------------- AC#3 curve / best_frame


def test_curve_and_best_frame_artifacts(iso_env, monkeypatch):
    """AC#3：curve 帧数 ≥1、elapsed 单调不减、条目白名单无 placed_items；
    best_frame density = 曲线内最大帧 density、frame_index 对齐、含完整布局。"""
    _, _, run_dir, cfg = iso_env
    frames = [_frame(0, 0.50), _frame(1, 0.55), _frame(2, 0.53), _frame(3, 0.60)]
    monkeypatch.setattr(web_solver, 'solve_with_callback_proc',
                        _fake_proc_solver(frames))

    rec = solve_pieces(cfg, run_dir, seed=7, time_budget=2)

    curve = json.loads((run_dir / 'curve_s7.json').read_text(encoding='utf-8'))
    assert len(curve) == 4
    for c in curve:
        assert set(c) == {'elapsed', 'phase', 'density', 'density_sparrow', 'width_mm'}
    elapsed = [c['elapsed'] for c in curve]
    assert elapsed == sorted(elapsed)                 # 单调不减
    assert [c['density'] for c in curve] == [0.5, 0.55, 0.53, 0.6]

    best = json.loads((run_dir / 'best_frame_s7.json').read_text(encoding='utf-8'))
    assert best['density'] == max(c['density'] for c in curve)
    assert best['density_sparrow'] == pytest.approx(best['density'] + 0.02)
    assert best['frame_index'] == 3                   # 与曲线下标对齐
    assert best['seed'] == 7
    assert len(best['placed_items']) == _N_PIECES     # 完整布局只在 best 帧文件
    assert best['n_placed'] == _N_PIECES
    assert curve[best['frame_index']]['density'] == best['density']

    # 正常路径记录与旧版字段完全一致（零回归：不新增 killed 键）
    assert set(rec) == {'seed', 'n_items', 'n_eroded', 'total_area_mm2', 'width_mm',
                        'real_density', 'density_sparrow', 'placed_items', 'elapsed'}
    assert rec['real_density'] == pytest.approx(0.6, abs=1e-9)
    assert rec['placed_items'] == _N_PIECES
    assert rec['width_mm'] == pytest.approx(best['width_mm'], abs=1e-9)


def test_best_frame_strict_improvement_only(iso_env, monkeypatch):
    """等值不覆盖：[0.5, 0.6, 0.6, 0.55] → best_frame 停在首个 0.6（frame_index=1）。"""
    _, _, run_dir, cfg = iso_env
    frames = [_frame(0, 0.50), _frame(1, 0.60), _frame(2, 0.60), _frame(3, 0.55)]
    monkeypatch.setattr(web_solver, 'solve_with_callback_proc',
                        _fake_proc_solver(frames))
    solve_pieces(cfg, run_dir, seed=0, time_budget=2)
    best = json.loads((run_dir / 'best_frame_s0.json').read_text(encoding='utf-8'))
    assert best['density'] == 0.6 and best['frame_index'] == 1


def test_curve_flushed_on_keyboard_interrupt(iso_env, monkeypatch):
    """AC#4 前置：求解中途 KeyboardInterrupt → 已收帧仍全部落盘（finally 写全）。"""
    _, _, run_dir, cfg = iso_env
    frames = [_frame(0, 0.50), _frame(1, 0.55)]

    def _impl(pieces, gate_mm, solve_params, *, on_manifest, on_report,
              on_process=None, **kw):
        if on_process is not None:
            on_process(_FakeProc())
        on_manifest({'pid_meta': {}, 'total_area': 0.0, 'n_eroded': 0,
                     'gate_mm': float(gate_mm)})
        for fr in frames:
            on_report(dict(fr))
        raise KeyboardInterrupt

    monkeypatch.setattr(web_solver, 'solve_with_callback_proc', _impl)
    with pytest.raises(KeyboardInterrupt):
        solve_pieces(cfg, run_dir, seed=3, time_budget=2)

    curve = json.loads((run_dir / 'curve_s3.json').read_text(encoding='utf-8'))
    assert [c['density'] for c in curve] == [0.5, 0.55]
    assert (run_dir / 'best_frame_s3.json').exists()


# ------------------------------------------------------- AC#2 should_stop 语义


def test_should_stop_false_equivalent_to_absent(iso_env, monkeypatch):
    """AC#2：should_stop 恒 False 与不传等价（记录逐字段相等，仅 seed 不同）。"""
    _, _, run_dir, cfg = iso_env
    frames = [_frame(0, 0.5), _frame(1, 0.58)]
    monkeypatch.setattr(web_solver, 'solve_with_callback_proc',
                        _fake_proc_solver(frames))
    r_a = solve_pieces(cfg, run_dir, seed=1, time_budget=2)
    r_b = solve_pieces(cfg, run_dir, seed=2, time_budget=2,
                       should_stop=lambda fr: False)
    assert r_a == {**r_b, 'seed': 1}
    assert 'killed' not in r_a and 'killed' not in r_b


def test_should_stop_true_terminates_and_returns_best_so_far(iso_env, monkeypatch):
    """AC#2：触发 should_stop → 子进程被 terminate（伪句柄断言 + join 无孤儿）、
    返回 killed=True、density = 终止前 best-so-far 帧原面积口径（非末帧）、
    killed 路径不做 placed==Σdemand 完整性校验。"""
    _, _, run_dir, cfg = iso_env
    # 帧序列 0.50 / 0.62 / 0.55，第 2 帧后触发停止 → 交付 best=0.62（非末帧 0.55）；
    # 各帧只放 3 片（Σdemand=6）—— killed 路径不做完整性校验。
    frames = [_frame(0, 0.50, n_placed=3), _frame(1, 0.62, n_placed=3),
              _frame(2, 0.55, n_placed=3)]
    fake = _fake_proc_solver(frames)
    handle: dict = {}

    def _impl(pieces, gate_mm, solve_params, *, on_manifest, on_report,
              on_process=None, **kw):
        def _capture(proc):
            handle['proc'] = proc
            if on_process is not None:
                on_process(proc)
        return fake(pieces, gate_mm, solve_params, on_manifest=on_manifest,
                    on_report=on_report, on_process=_capture, **kw)

    monkeypatch.setattr(web_solver, 'solve_with_callback_proc', _impl)
    seen: list[float] = []

    def _stop(fr):
        seen.append(fr['density'])
        return len(seen) >= 2

    rec = solve_pieces(cfg, run_dir, seed=5, time_budget=2, should_stop=_stop)

    assert rec['killed'] is True
    assert rec['kill_reason'] == 'should_stop'
    assert rec['real_density'] == pytest.approx(0.62, abs=1e-9)   # best-so-far，非末帧
    assert rec['density_sparrow'] == pytest.approx(0.64, abs=1e-9)
    assert rec['placed_items'] == 3                              # 中间帧副本数原样交付
    assert rec['seed'] == 5 and rec['n_items'] == _N_PIECES
    assert set(rec) == {'seed', 'n_items', 'n_eroded', 'total_area_mm2', 'width_mm',
                        'real_density', 'density_sparrow', 'placed_items', 'elapsed',
                        'killed', 'kill_reason'}

    proc = handle['proc']
    assert proc.terminated is True                               # 确实调了 terminate
    proc.join(timeout=5)
    assert not proc.is_alive()                                   # 无孤儿

    # 被截断的曲线只含已投帧（第 3 帧因 terminate 不再到达）
    curve = json.loads((run_dir / 'curve_s5.json').read_text(encoding='utf-8'))
    assert [c['density'] for c in curve] == [0.5, 0.62]


def test_should_stop_string_reason_recorded(iso_env, monkeypatch):
    """should_stop 返回非空字符串 → 作为 kill_reason 透传（portfolio 规则名通道）。"""
    _, _, run_dir, cfg = iso_env
    monkeypatch.setattr(web_solver, 'solve_with_callback_proc',
                        _fake_proc_solver([_frame(0, 0.4), _frame(1, 0.7)]))
    rec = solve_pieces(cfg, run_dir, seed=9, time_budget=2,
                       should_stop=lambda fr: 'R0_target_reached' if fr['density'] >= 0.7 else False)
    assert rec['kill_reason'] == 'R0_target_reached'
    assert rec['real_density'] == pytest.approx(0.7, abs=1e-9)


def test_should_stop_evaluated_after_frame_banked(iso_env, monkeypatch):
    """中止判定发生在帧入账之后：首帧即停也有 best-so-far 可交付（killed 永不空手）。"""
    _, _, run_dir, cfg = iso_env
    monkeypatch.setattr(web_solver, 'solve_with_callback_proc',
                        _fake_proc_solver([_frame(0, 0.4), _frame(1, 0.7)]))
    rec = solve_pieces(cfg, run_dir, seed=4, time_budget=2,
                       should_stop=lambda fr: True)
    assert rec['killed'] is True
    assert rec['real_density'] == pytest.approx(0.4, abs=1e-9)   # 首帧即 best-so-far
    best = json.loads((run_dir / 'best_frame_s4.json').read_text(encoding='utf-8'))
    assert best['frame_index'] == 0


# ------------------------------------------------------- 真实多进程回归（AC#1/AC#2）


def test_real_proc_solve_no_should_stop_smoke(iso_env):
    """AC#1 真实链路：无 should_stop 的多进程求解与旧 threading 版行为等价 ——
    完整解（placed==Σdemand）、双口径密度对拍、curve/best_frame 落盘。"""
    _, _, run_dir, cfg = iso_env
    rec = solve_pieces(cfg, run_dir, seed=0, time_budget=3)

    assert rec['seed'] == 0
    assert rec['n_items'] == _N_PIECES
    assert rec['placed_items'] == _N_PIECES
    expect = rec['total_area_mm2'] / (rec['width_mm'] * min(cfg.gate_mm, PLOT_SAFE_MAX_Y_MM))
    assert rec['real_density'] == pytest.approx(expect, abs=1e-4)
    assert rec['density_sparrow'] > 0
    assert 'killed' not in rec

    curve = json.loads((run_dir / 'curve_s0.json').read_text(encoding='utf-8'))
    assert len(curve) >= 1
    elapsed = [c['elapsed'] for c in curve]
    assert elapsed == sorted(elapsed)
    best = json.loads((run_dir / 'best_frame_s0.json').read_text(encoding='utf-8'))
    assert best['density'] == max(c['density'] for c in curve)
    assert len(best['placed_items']) == _N_PIECES


def test_real_proc_terminate_end_to_end(iso_env, monkeypatch):
    """AC#2 真实 terminate 链路：首帧即停 → 真子进程被杀（exitcode≠0、join 无孤儿）、
    返回 killed=True 且 density/width = 终止前 best-so-far 帧（与 best_frame 文件对拍）。"""
    _, _, run_dir, cfg = iso_env
    real = web_solver.solve_with_callback_proc
    handle: dict = {}

    def _capture(pieces, gate_mm, solve_params, *, on_manifest, on_report,
                 on_process=None, **kw):
        def _wrap(proc):
            handle['proc'] = proc
            if on_process is not None:
                on_process(proc)
        return real(pieces, gate_mm, solve_params, on_manifest=on_manifest,
                    on_report=on_report, on_process=_wrap, **kw)

    monkeypatch.setattr(web_solver, 'solve_with_callback_proc', _capture)
    rec = solve_pieces(cfg, run_dir, seed=1, time_budget=60,
                       should_stop=lambda fr: True)

    assert rec['killed'] is True and rec['kill_reason'] == 'should_stop'
    curve = json.loads((run_dir / 'curve_s1.json').read_text(encoding='utf-8'))
    assert len(curve) >= 1
    best = json.loads((run_dir / 'best_frame_s1.json').read_text(encoding='utf-8'))
    assert rec['real_density'] == pytest.approx(best['density'], abs=1e-9)
    assert rec['width_mm'] == best['width_mm']
    assert rec['placed_items'] == best['n_placed']

    proc = handle['proc']
    proc.join(timeout=5)
    assert not proc.is_alive()                       # 无孤儿进程
    assert proc.exitcode != 0                        # OS 级回收（terminate 生效）
    assert all(c.name != 'solve_worker' for c in multiprocessing.active_children())


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
