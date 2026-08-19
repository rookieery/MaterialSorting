"""PC-009 ``run_config`` run 统计库 + ``portfolio`` θ₀ 按实例类校准测试。

覆盖（PRD tasks/prd-serial-seed-portfolio.md PC-009 验收标准）：

  - ``run_stats_class_key``：确定性（同输入同 key，10 位十六进制短哈希）、组件
    敏感性（source / sizes / quantities / per_type 任一变动 → 不同 key）、dict
    组件键序无关（sort_keys 规范化）；
  - ``calibrate_theta0`` 纯函数矩阵：命中且 ≥5 条 → min(target, 历史最大
    best_density + 0.003)；min 封顶（历史最高 + 余量 > target → θ₀ = target）；
    不足 5 条 → target（info=None）；恰 5 条触发；不同 class_key 互不污染；坏
    记录（缺 best_density / 非数值 / bool）不计入样本；
  - ``load_run_stats``：缺文件 → []；坏 JSON 行 / 非 dict 行跳过；空行剔除；
  - ``main`` 端到端（fake solve 注入帧序列）：连跑 2 次 → JSONL 恰 2 行、字段
    完整；R0 提前停路径也落盘（n_killed 计入被 R0 停下的 seed）；θ₀ 端到端
    （预置 5 条同 class 历史 + --target → 启动校准说明行 + kill_decisions.jsonl
    决策 theta 字段 = 校准值 + R0 不受影响：帧密度 < target 时队列跑满）；
  - θ₀ 只影响 kill 门槛回归（控制器直驱）：θ₀ < target 时 density ∈ [θ₀, target)
    的帧 should_stop 恒 falsy、density ≥ target 才 R0；θ₀ 翻转 R2 判决（默认 θ
    必死 → 校准后存活）；
  - 写盘失败（RUN_STATS_JSONL 指向目录 → open OSError）不抛出、run 正常完成
    （rc 0 + stderr 警告 + 末行汇总照常）。
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
from materialsorting.cli.portfolio import (R0_REASON, R2_REASON, THETA0_MARGIN,
                                           THETA0_MIN_RECORDS, PortfolioController,
                                           calibrate_theta0, load_run_stats,
                                           run_stats_class_key)
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
        blk.add_line((x + 10, y + h / 2), (x + w - 10, y + h / 2), dxfattribs={'layer': '7'})
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


# ------------------------------------------------------- fake solve 驱动装置


def _frame(seed: int, idx: int, elapsed: float, density: float,
           phase: str = 'exploring') -> dict:
    return {
        'type': 'frame',
        'elapsed': float(elapsed),
        'phase': phase,
        'density': float(density),
        'density_sparrow': float(density) + 0.02,
        'width_mm': 50000.0 - float(seed) * 1000.0 - float(idx) * 10.0,
        'placed_items': [
            {'id': f'g0{k + 1}_28', 'rotation': 0.0,
             'translation': [float(seed * 10000 + idx * 100 + k), 0.0]}
            for k in range(_N_PIECES)
        ],
    }


def _fake_solve(trajectories: dict[int, list[tuple]],
                calls: list[int] | None = None):
    """构造伪 solve（契约镜像 ``solve_pieces``）：逐帧 on_progress → should_stop
    （触发即停，best-so-far 帧交付 killed=True），跑满交付末帧。

    轨迹条目为 ``(elapsed, density)`` 或 ``(elapsed, density, phase)``（缺省
    ``'exploring'``；R2 压缩期判决需要 ``'compressing'`` 帧驱动）。
    """

    def solve(cfg, run_dir, *, seed, time_budget=None, on_progress=None,
              should_stop=None, **kw):
        if calls is not None:
            calls.append(seed)
        frames: list[dict] = []
        for idx, item in enumerate(trajectories[seed]):
            elapsed, d = item[0], item[1]
            phase = item[2] if len(item) > 2 else 'exploring'
            fr = _frame(seed, idx, elapsed, d, phase)
            frames.append(fr)
            if on_progress is not None:
                on_progress(fr)
            if should_stop is not None:
                verdict = should_stop(fr)
                if verdict:
                    best = max(frames, key=lambda f: f['density'])
                    return {'seed': seed, 'real_density': best['density'],
                            'width_mm': best['width_mm'], 'placed_items': _N_PIECES,
                            'elapsed': best['elapsed'], 'killed': True,
                            'kill_reason': verdict if isinstance(verdict, str) else None}
        final = frames[-1]
        return {'seed': seed, 'real_density': final['density'],
                'width_mm': final['width_mm'], 'placed_items': _N_PIECES,
                'elapsed': final['elapsed']}

    return solve


def _patch_fake_solve(monkeypatch, trajectories, calls=None):
    from materialsorting.cli import run_config as rc_mod
    monkeypatch.setattr(rc_mod, 'solve_pieces', _fake_solve(trajectories, calls))


def _read_stats(stats: Path) -> list[dict]:
    return [json.loads(l) for l in
            stats.read_text(encoding='utf-8').splitlines() if l.strip()]


# ------------------------------------------------------- class_key 纯函数


def test_run_stats_class_key_stable_and_sensitive():
    """同输入同 key（10 位十六进制）；四个组件任一变动 → 不同 key；dict 键序无关。"""
    args = ('/m/master.dxf', [31, 32], {'g01': {'31': 2, '32': 1}}, {'g01': {'d': 2}})
    key = run_stats_class_key(*args)
    assert key == run_stats_class_key(*args)
    assert len(key) == 10
    assert all(c in '0123456789abcdef' for c in key)
    assert key != run_stats_class_key('/m/other.dxf', args[1], args[2], args[3])
    assert key != run_stats_class_key(args[0], [31], args[2], args[3])
    assert key != run_stats_class_key(args[0], None, args[2], args[3])
    assert key != run_stats_class_key(args[0], args[1], {'g01': {'31': 3, '32': 1}}, args[3])
    assert key != run_stats_class_key(args[0], args[1], args[2], {'g01': {'d': 3}})
    # dict 组件键序无关（sort_keys 规范化）：写入侧与读取侧口径天然一致的前提。
    assert key == run_stats_class_key(
        args[0], args[1], {'g01': {'32': 1, '31': 2}}, {'g01': {'d': 2}})


def test_load_run_stats_tolerates_missing_and_bad_lines(tmp_path):
    """缺文件 → []；坏 JSON 行 / 非 dict 行跳过；空行剔除。"""
    assert load_run_stats(tmp_path / 'nope.jsonl') == []
    p = tmp_path / 'rs.jsonl'
    p.write_text('\n'.join([
        json.dumps({'class_key': 'k', 'best_density': 0.9}),
        '{not json',
        json.dumps(['not', 'a', 'dict']),
        '',
        json.dumps({'class_key': 'k2'}),   # 缺 best_density：保留（calibrate 侧跳过）
    ]) + '\n', encoding='utf-8')
    assert load_run_stats(p) == [{'class_key': 'k', 'best_density': 0.9},
                                 {'class_key': 'k2'}]


# ------------------------------------------------------- calibrate_theta0 纯函数


def _hist(class_key: str, densities) -> list[dict]:
    return [{'class_key': class_key, 'best_density': d} for d in densities]


def test_calibrate_theta0_hit_min_with_target_cap():
    """AC#2：命中且 ≥5 条 → min(target, max + 0.003)；历史最高 + 余量超 target → 封顶。"""
    recs = _hist('k', (0.86, 0.875, 0.88, 0.89, 0.896))
    theta0, info = calibrate_theta0(recs, 'k', 0.9)
    assert theta0 == pytest.approx(0.896 + THETA0_MARGIN)      # 0.899
    assert info == {'n_records': 5, 'max_density': pytest.approx(0.896)}
    # min 封顶：max + margin 越过 target → θ₀ = target（校准不抬门槛）。
    theta0_cap, info_cap = calibrate_theta0(recs, 'k', 0.88)
    assert theta0_cap == pytest.approx(0.88)
    assert info_cap['n_records'] == 5        # 命中信息仍在（说明行可打）


def test_calibrate_theta0_insufficient_records():
    """AC#2：不足 5 条（0 / 4 条）→ target、info=None；恰 5 条触发。"""
    assert calibrate_theta0([], 'k', 0.9) == (0.9, None)
    theta0, info = calibrate_theta0(_hist('k', (0.8, 0.81, 0.82, 0.83)), 'k', 0.9)
    assert theta0 == pytest.approx(0.9) and info is None
    assert calibrate_theta0(_hist('k', (0.8,) * THETA0_MIN_RECORDS), 'k', 0.9)[1] \
        is not None


def test_calibrate_theta0_class_isolation():
    """AC#2：不同 class_key 互不污染 —— 他类 5 条高样本不触发当前类校准。"""
    recs = _hist('other', (0.95, 0.955, 0.96, 0.965, 0.97)) + _hist('k', (0.8, 0.81))
    theta0, info = calibrate_theta0(recs, 'k', 0.9)
    assert theta0 == pytest.approx(0.9) and info is None
    # 当前类补足 5 条后才用本类最大值（0.83，不受他类 0.97 影响）。
    recs += _hist('k', (0.82, 0.83, 0.825))
    theta0, info = calibrate_theta0(recs, 'k', 0.9)
    assert theta0 == pytest.approx(0.83 + THETA0_MARGIN)
    assert info['n_records'] == 5


def test_calibrate_theta0_skips_bad_records():
    """坏记录（缺 best_density / 非数值 / bool / 非 dict）不计入样本数。"""
    recs = _hist('k', (0.86, 0.875, 0.88, 0.89)) + [
        {'class_key': 'k'},                          # 缺 best_density
        {'class_key': 'k', 'best_density': 'x'},     # 非数值
        {'class_key': 'k', 'best_density': True},    # bool（JSON true 不是密度）
        'not a dict',
    ]
    theta0, info = calibrate_theta0(recs, 'k', 0.9)
    assert theta0 == pytest.approx(0.9) and info is None   # 有效样本仍 4 条 < 5


# ------------------------------------------------------- θ₀ 只影响 kill 门槛（回归）


def test_theta0_does_not_affect_r0_stop_condition():
    """AC#2 回归：θ₀ 降门槛后，density ∈ [θ₀, target) 的帧 R0 不停、kill 不触发；
    density ≥ target 才 R0（停止条件恒用 --target 真值）。"""
    c = PortfolioController(seeds=[1, 2], target=0.9, theta0=0.7)
    assert c.theta == pytest.approx(0.7)               # θ₀ 生效为 kill 门槛锚
    stop = c.make_should_stop(seed=2, index=2)
    assert stop({'density': 0.7}) is False             # = θ₀：R0 不停（无标定 kill 不触发）
    assert stop({'density': 0.8999}) is False          # 贴近 target 仍不停
    assert stop({'density': 0.9}) == R0_REASON         # 恒用 --target
    # 对照：不给 θ₀ → θ = target（旧行为零回归）。
    assert PortfolioController(seeds=[1, 2], target=0.9).theta == pytest.approx(0.9)


def test_theta0_flips_r2_verdict():
    """θ₀ 实际进入 kill 判据：默认 θ=target 判必死（R2 记录）→ 校准 θ₀ 后同轨迹存活。

    轨迹：seed 1 锚定 0.7（incumbent），seed 2 首压缩帧 d=0.85、uplift 默认
    0.005 —— 默认 θ=0.9 时 ``0.85 + 0.005 < max(0.9, I+ε)`` 必死；θ₀=0.8 时门槛
    ``max(0.8, 0.851)=0.851 ≤ 0.855`` 存活（θ₀ 只降 kill 门槛的证据）。
    """

    def _drive(controller):
        p1 = controller.make_progress(seed=1, index=1)      # seed 1 锚定：incumbent 0.7
        p1({'density': 0.7, 'elapsed': 1.0, 'phase': 'exploring',
            'width_mm': 1000.0, 'placed_items': []})
        p2 = controller.make_progress(seed=2, index=2)      # seed 2 best 0.85（反超）
        p2({'density': 0.85, 'elapsed': 1.0, 'phase': 'exploring',
            'width_mm': 1000.0, 'placed_items': []})
        stop = controller.make_should_stop(seed=2, index=2)
        return stop({'density': 0.85, 'elapsed': 2.0, 'phase': 'compressing',
                     'width_mm': 1000.0, 'placed_items': []})

    default_c = PortfolioController(seeds=[1, 2], target=0.9, time_budget=10)
    assert _drive(default_c) is False                       # shadow 只记不杀
    assert [d['rule'] for d in default_c.kill_decisions] == [R2_REASON]
    assert default_c.kill_decisions[0]['theta'] == pytest.approx(0.9)

    calibrated_c = PortfolioController(seeds=[1, 2], target=0.9, time_budget=10,
                                       theta0=0.8)
    assert _drive(calibrated_c) is False
    assert calibrated_c.kill_decisions == []    # 0.85 + 0.005 ≥ max(0.8, 0.851) → 存活


# ------------------------------------------------------- main 端到端（fake solve）


def test_two_runs_append_two_complete_lines(iso_env, capsys, monkeypatch):
    """AC#1：连跑 2 次 → JSONL 恰 2 行、字段完整；class_key 与写入组件自洽。"""
    tmp, runs, stats, master = iso_env
    cfg_path = _write_config(tmp / 'cfg_2run.json', master, seeds=[0, 1])
    traj = {0: [(1.0, 0.80), (2.0, 0.82)], 1: [(1.0, 0.81), (2.0, 0.83)]}
    _patch_fake_solve(monkeypatch, traj)
    assert main([str(cfg_path), '--time', '2', '--name', 'runA', '--quiet']) == 0
    _patch_fake_solve(monkeypatch, traj)
    assert main([str(cfg_path), '--time', '2', '--name', 'runB', '--quiet']) == 0
    capsys.readouterr()

    entries = _read_stats(stats)
    assert len(entries) == 2                              # 恰 2 行（append-only）
    for e in entries:
        assert set(e) == {'ts', 'source', 'sizes', 'class_key', 'seeds', 'target',
                          'best_density', 'n_killed', 'elapsed_total', 'config'}
        assert e['ts']                                    # ISO 时间戳非空
        assert e['source'] == str(master.resolve())       # load_config 解析后的绝对路径
        assert e['sizes'] is None and e['seeds'] == [0, 1]
        assert e['target'] is None and e['n_killed'] == 0
        assert e['config'] == {'time': 2, 'per_type': {}, 'quantities': None}
        assert e['elapsed_total'] >= 0
        # class_key 与条目自身组件自洽（写入侧单一真相源 run_stats_class_key）。
        assert e['class_key'] == run_stats_class_key(
            e['source'], e['sizes'], e['config']['quantities'], e['config']['per_type'])
    # best_density = 各 run 交付最优（两 run 同轨迹 → 同值 0.83，多 seed incumbent）。
    assert entries[0]['best_density'] == pytest.approx(0.83, abs=1e-9)
    assert entries[1]['best_density'] == pytest.approx(0.83, abs=1e-9)


def test_r0_early_stop_path_writes_stats(iso_env, capsys, monkeypatch):
    """AC#1：R0 提前停路径也落盘（target 回显 + n_killed 计入被 R0 停下的 seed）。"""
    tmp, runs, stats, master = iso_env
    cfg_path = _write_config(tmp / 'cfg_r0.json', master, seeds=[0, 1])
    calls: list[int] = []
    _patch_fake_solve(monkeypatch, {0: [(0.5, 0.55), (1.0, 0.62)],
                                    1: [(0.5, 0.58)]}, calls)
    rc = main([str(cfg_path), '--time', '2', '--target', '0.6',
               '--name', 'r0stop', '--quiet'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'R0 达标即停' in out and 'θ₀ 校准' not in out   # 无历史 → 不校准
    assert calls == [0]                           # seed 1 未启动（队列被 R0 截断）

    entries = _read_stats(stats)
    assert len(entries) == 1
    e = entries[0]
    assert e['target'] == pytest.approx(0.6)
    assert e['best_density'] == pytest.approx(0.62, abs=1e-9)  # 触发帧先入账后停
    assert e['n_killed'] == 1                     # R0 停下的 seed killed=True
    assert e['seeds'] == [0, 1]


def test_main_theta0_calibrated_from_stats(iso_env, capsys, monkeypatch):
    """AC#2 端到端：预置 5 条同 class 历史 + --target → 校准说明行 + 决策 theta 字段
    = 校准值；θ₀ 不影响 R0（帧密度 < target → 队列跑满）。"""
    tmp, runs, stats, master = iso_env
    cfg_path = _write_config(tmp / 'cfg_theta0.json', master, seeds=[0, 1])
    ckey = run_stats_class_key(str(master.resolve()), None, None, {})
    with open(stats, 'a', encoding='utf-8') as f:
        for v in (0.86, 0.875, 0.88, 0.89, 0.896):
            f.write(json.dumps({'class_key': ckey, 'best_density': v}) + '\n')
    calls: list[int] = []
    # seed 1（队列序 2）首压缩帧 d=0.852 + uplift 0.005 < θ₀ 0.899 → shadow 记 R2。
    _patch_fake_solve(monkeypatch, {0: [(1.0, 0.84), (2.0, 0.85)],
                                    1: [(1.0, 0.845), (2.0, 0.852, 'compressing')]},
                      calls)

    rc = main([str(cfg_path), '--time', '2', '--target', '0.9',
               '--name', 'theta0', '--quiet'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'θ₀ 校准' in out and ckey in out and '5 条历史' in out
    assert '89.90%' in out and '89.33%' not in out      # 0.896 + 0.003 = 0.899

    # θ₀ 只影响 kill 门槛：帧峰值 0.852 < target 0.9 → R0 不触发、队列跑满。
    assert calls == [0, 1]
    # 校准值真实进入引擎：kill_decisions.jsonl 的 theta 字段 = 0.899（非 target 0.9）。
    (rd,) = [d for d in runs.iterdir() if d.name.startswith('theta0_')]
    decisions = [json.loads(l) for l in
                 (rd / 'kill_decisions.jsonl').read_text(encoding='utf-8').splitlines()
                 if l.strip()]
    assert decisions and decisions[0]['theta'] == pytest.approx(0.899)
    assert decisions[0]['rule'] == R2_REASON

    # 本次 run 结束再追加 1 行 → 6 条历史（同 class 持续沉淀，越测越准）。
    entries = _read_stats(stats)
    assert len(entries) == 6
    assert entries[-1]['class_key'] == ckey
    assert entries[-1]['best_density'] == pytest.approx(0.852, abs=1e-9)
    assert entries[-1]['target'] == pytest.approx(0.9)


def test_stats_write_failure_warns_and_run_completes(iso_env, capsys, monkeypatch):
    """AC#3：写盘失败（目标路径是目录 → open OSError）不抛出、rc 0、warning log、
    末行汇总照常。"""
    tmp, runs, stats, master = iso_env
    bomb = tmp / 'bomb_dir'
    bomb.mkdir()
    monkeypatch.setattr(paths_mod, 'RUN_STATS_JSONL', str(bomb))
    cfg_path = _write_config(tmp / 'cfg_bomb.json', master)
    _patch_fake_solve(monkeypatch, {0: [(1.0, 0.8), (2.0, 0.81)]})
    rc = main([str(cfg_path), '--time', '2', '--name', 'bomb', '--quiet'])
    assert rc == 0
    captured = capsys.readouterr()
    assert '警告' in captured.err and 'run 统计落盘失败' in captured.err
    last_line = captured.out.strip().splitlines()[-1]
    assert 'real_density（原面积口径）' in last_line     # 末行汇总不受旁路失败影响
    (rd,) = [d for d in runs.iterdir() if d.name.startswith('bomb_')]
    assert (rd / 'result.json').exists()                 # 求解交付物完整在场
    assert not stats.exists()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
