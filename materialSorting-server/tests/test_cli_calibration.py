"""PC-004 ``cli/calibration`` 标定管线测试（batch / variants / analyze）。

驱动方式：**fake solve**（契约镜像 ``solve_pieces``：写 curve_s/best_frame_s 落盘 +
返回 rec）注入确定轨迹，覆盖：
  - 变体生成器（纯）：确定性（同参数两次生成逐字节一致）、抖动只作用于 sizes 内
    条目、保底 1 片、工艺维度逐字段固定、生成物过 ``load_config`` 校验；
  - batch/variants 编排：串行不变量（任一时刻至多 1 个求解）、目录结构稳定、
    续跑跳过已完成 seed、Ctrl-C 中断安全（manifest interrupted + 已完成产物在场）；
  - analyze（纯函数 + CLI）：包络单调性、uplift 分位数、达标/失败分离度、
    train/test 误杀回测、小样本拒绝下发、泛化报告误杀率字段；
  - 产物只落 ``out/portfolio_calibration/``（CONFIG_RUNS_DIR / INTERMEDIATE /
    uploads 零触碰）；
  - 分层：calibration 模块不 import web + ``python -m`` --help 冒烟。
"""
from __future__ import annotations

import ast
import json
import random
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
from materialsorting.cli import calibration as cal
from materialsorting.cli.calibration import (backtest, curve_stats,
                                             envelope_from_curves,
                                             generate_variants,
                                             jitter_quantities, main,
                                             rank_correlation, replay_r1,
                                             run_batch, run_variants,
                                             separation_tau0, split_train_test,
                                             spearman, uplift_distribution)
from materialsorting.cli.config import load_config

# 与 test_cli_portfolio 同构的合成母版：6 片有码号（sizes 28/29 各 3 片）。
_SYNTH_BLOCKS = [
    ('blk x.28', (0.12345, 0.6789, 400.123456, 700.987654)),
    ('blk x.29', (0.12345, 0.6789, 400.123456, 720.987654)),
    ('zz 9.28', (1.5, 2.25, 200.111111, 90.222222)),
    ('zz 9.29', (1.5, 2.25, 200.111111, 95.222222)),
    ('M55#2 a.28', (2.75, 3.125, 120.333333, 60.444444)),
    ('M55#2 a.29', (2.75, 3.125, 120.333333, 65.444444)),
]

# 变体生成器测试用的 7 键原始配置（sizes [31,32] → "33"/"null" 是惰性条目）。
_BASE_RAW = {
    'master_dxf': 'data/some_master.dxf', 'gate_mm': 1980, 'time': 300,
    'seeds': [0], 'sizes': [31, 32],
    'per_type': {'g01': {'d': 5, 'tol': 8}, 'g06': {'d': 10, 'tol': 45}},
    'quantities': {'g01': {'31': 2, '32': 3, '33': 4, 'null': 1},
                   'g02': {'31': 1, '32': 1}},
}

# 回测用 kill 参数（数值与 KILL_DEFAULTS 同风格）。
_KP = {'tau0': 0.1, 'W': 10.0, 'm': 0.005, 'epsilon': 0.001, 'delta': 0.003,
       'm_streak': 3, 'uplift_q95': 0.005}


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
    cfg = {'master_dxf': str(master), 'gate_mm': 1980, 'time': 2,
           'sizes': [28, 29],
           'quantities': {'g01': {'28': 2, '29': 1}, 'g02': {'28': 1, '29': 2},
                          'g03': {'28': 1, '29': 1}}}
    cfg.update(extra)
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
    return path


@pytest.fixture
def iso_env(tmp_path, monkeypatch):
    """隔离环境：CALIBRATION_DIR / CONFIG_RUNS_DIR / INTERMEDIATE 全指 tmp + 合成母版。"""
    cal_root = tmp_path / 'portfolio_calibration'
    runs = tmp_path / 'config_runs'
    runs.mkdir()
    inter = tmp_path / 'web_intermediate.json'
    inter.write_text('{"sentinel": true}', encoding='utf-8')
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(paths_mod, 'CALIBRATION_DIR', str(cal_root))
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(runs))
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE', str(inter))
    master = _make_master_dxf(tmp_path / 'synthetic_master.dxf')
    return tmp_path, cal_root, runs, inter, uploads, master


# ------------------------------------------------------- fake solve 驱动装置


def _mk_curve(points, compress_from=None) -> list[dict]:
    """(elapsed, density) 序列 → curve 帧（compress_from 起相位切 compressing）。"""
    return [{'elapsed': float(t),
             'phase': ('compressing' if compress_from is not None and i >= compress_from
                       else 'exploring'),
             'density': float(d), 'density_sparrow': float(d) + 0.01,
             'width_mm': 50000.0 - i * 10.0}
            for i, (t, d) in enumerate(points)]


def _write_solve_artifacts(run_dir: Path, seed: int, curve: list[dict]) -> None:
    """镜像 solve_pieces 落盘契约：curve_s{seed}.json + best_frame_s{seed}.json。"""
    (run_dir / f'curve_s{seed}.json').write_text(
        json.dumps(curve, ensure_ascii=False), encoding='utf-8')
    best_i = max(range(len(curve)), key=lambda i: curve[i]['density'])
    best = {'seed': seed, 'frame_index': best_i,
            'density': curve[best_i]['density'], 'n_placed': 6,
            'placed_items': [{'id': f'g0{k + 1}_28', 'rotation': 0.0,
                              'translation': [float(seed * 100 + k), 0.0]}
                             for k in range(6)]}
    (run_dir / f'best_frame_s{seed}.json').write_text(
        json.dumps(best, ensure_ascii=False), encoding='utf-8')


def _fake_solve(curves: dict[tuple[str, int], list[dict]], *, active: dict | None = None,
                calls: list | None = None, cfgs: list | None = None,
                interrupt_on: tuple[str, int] | None = None):
    """伪 solve：按 ``{(组相对路径, seed): 曲线}`` 落盘并返回 rec。

    ``active`` 注入串行不变量守卫（进入时必须为 0，嵌套即断言失败）；
    ``interrupt_on=(组, seed)`` 在该 seed **写盘前**抛 KeyboardInterrupt
    （模拟求解中被断，该 seed 无完整产物）。
    """
    def solve(cfg, run_dir, *, seed, time_budget=None, on_progress=None,
              should_stop=None, **kw):
        rd = Path(run_dir)
        rel = f'{rd.parent.name}/{rd.name}'
        if active is not None:
            assert active['n'] == 0, '串行不变量被破坏：并发求解'
            active['n'] += 1
        try:
            if calls is not None:
                calls.append((rel, int(seed)))
            if cfgs is not None:
                cfgs.append(cfg)
            if interrupt_on is not None and (rel, int(seed)) == interrupt_on:
                raise KeyboardInterrupt
            curve = curves[(rel, int(seed))]
            _write_solve_artifacts(rd, int(seed), curve)
            if on_progress is not None:
                for fr in curve:
                    on_progress(fr)
            return {'seed': int(seed), 'n_items': 6, 'n_eroded': 0,
                    'total_area_mm2': 1_000_000.0,
                    'width_mm': curve[-1]['width_mm'],
                    'real_density': curve[-1]['density'],
                    'density_sparrow': curve[-1]['density_sparrow'],
                    'placed_items': 6, 'elapsed': curve[-1]['elapsed']}
        finally:
            if active is not None:
                active['n'] -= 1

    return solve


def _trajs(specs: dict, compress_from=None) -> dict[tuple[str, int], list[dict]]:
    """``{(组, seed): [(elapsed, density), ...]}`` → fake solve 曲线表。"""
    return {k: _mk_curve(pts, compress_from) for k, pts in specs.items()}


# ------------------------------------------------------- AC#2 变体生成器（纯）


def test_variant_generator_deterministic():
    """AC#2：确定性 —— 同参数两次生成逐字节一致（json.dumps 全等）。"""
    v1 = generate_variants(_BASE_RAW, 4)
    v2 = generate_variants(_BASE_RAW, 4)
    assert len(v1) == 4
    assert json.dumps(v1, ensure_ascii=False) == json.dumps(v2, ensure_ascii=False)


def test_variant_jitter_scope_and_floor():
    """AC#2：抖动只作用于 sizes 内条目（"33"/"null" 惰性不动）、max(1, n±1) 约束。"""
    out = jitter_quantities(_BASE_RAW['quantities'], [31, 32], random.Random(0))
    for g, size_map in out.items():
        base_map = _BASE_RAW['quantities'][g]
        assert list(size_map.keys()) == list(base_map.keys())   # 键序原样
        for sk, n in size_map.items():
            if sk in ('31', '32'):
                assert n in {max(1, base_map[sk] + d) for d in (-1, 0, 1)}
            else:
                assert n == base_map[sk]                        # sizes 子集外不动
    # n=1 条目保底：任意 RNG 下全部 ≥ 1（抖不没整 g 码）
    tiny = {'quantities': {'g01': {'31': 1, '32': 1}}, 'sizes': [31, 32]}
    for i in range(20):
        v = generate_variants(tiny, 1)[0]
        assert all(n >= 1 for n in v['quantities']['g01'].values())


def test_variant_craft_fields_identical():
    """AC#2：per_type/gate_mm/master_dxf/sizes（及 time/seeds）与基配置逐字段相同。"""
    for v in generate_variants(_BASE_RAW, 4):
        assert set(v) == set(_BASE_RAW)
        for k in ('master_dxf', 'sizes', 'gate_mm', 'time', 'seeds', 'per_type'):
            assert v[k] == _BASE_RAW[k], k
    # 至少一个变体的 quantities 确实被抖动（6 条可抖条目，确定性结果）
    assert any(v['quantities'] != _BASE_RAW['quantities']
               for v in generate_variants(_BASE_RAW, 4))


# ------------------------------------------------------- AC#1 batch 编排


def test_run_batch_layout_and_serial(iso_env):
    """AC#1：串行不变量 + 目录结构稳定（commit 一次 + base/short|full 曲线与
    best 帧全部落盘 + manifest complete）。"""
    tmp, cal_root, _runs, _i, _u, master = iso_env
    cfg = load_config(_write_config(tmp / 'cfg.json', master))
    tag_dir = cal.calibration_dir('t1')
    tag_dir.mkdir(parents=True)
    trajs = _trajs({(f'base/short', s): [(1.0, 0.70 + s * 0.01), (2.0, 0.72 + s * 0.01)]
                    for s in range(3)}
                   | {(f'base/full', s): [(1.0, 0.80), (2.0, 0.82 + s * 0.01), (3.0, 0.81)]
                      for s in range(2)})
    active = {'n': 0}
    calls: list = []
    res = run_batch(cfg, tag_dir, short_seeds=3, short_time=2, full_seeds=2,
                    full_time=3, solve=_fake_solve(trajs, active=active, calls=calls))
    assert active['n'] == 0                                    # 无嵌套进入
    assert calls == [('base/short', 0), ('base/short', 1), ('base/short', 2),
                     ('base/full', 0), ('base/full', 1)]        # 先短组后全组、逐 seed
    assert (tag_dir / 'commit' / 'pieces_intermediate.json').is_file()
    for s in range(3):
        for name in (f'curve_s{s}.json', f'best_frame_s{s}.json'):
            assert (tag_dir / 'base' / 'short' / name).is_file()
    for s in range(2):
        for name in (f'curve_s{s}.json', f'best_frame_s{s}.json'):
            assert (tag_dir / 'base' / 'full' / name).is_file()
    # 组目录内 intermediate 副本在场（solve_pieces 的 run_dir 契约）
    for grp in ('short', 'full'):
        assert (tag_dir / 'base' / grp / 'pieces_intermediate.json').is_file()
        man = json.loads((tag_dir / 'base' / grp / 'manifest.json')
                         .read_text(encoding='utf-8'))
        assert man['status'] == 'complete'
        assert man['time'] == (2 if grp == 'short' else 3)
        assert all(e['status'] == 'done' for e in man['seeds'].values())
    assert [e['status'] for e in res['short']['seeds'].values()] == ['done'] * 3


def test_run_batch_resume_skips_completed(iso_env):
    """AC#1 续跑：已完成 seed（curve+best_frame 在场）跳过，第二次零求解。"""
    tmp, cal_root, _r, _i, _u, master = iso_env
    cfg = load_config(_write_config(tmp / 'cfg.json', master))
    tag_dir = cal.calibration_dir('t2')
    tag_dir.mkdir(parents=True)
    trajs = _trajs({('base/short', s): [(1.0, 0.7)] for s in range(2)}
                   | {('base/full', 0): [(1.0, 0.8)]})
    calls: list = []
    run_batch(cfg, tag_dir, short_seeds=2, short_time=2, full_seeds=1, full_time=2,
              solve=_fake_solve(trajs, calls=calls))
    assert len(calls) == 3
    calls.clear()
    run_batch(cfg, tag_dir, short_seeds=2, short_time=2, full_seeds=1, full_time=2,
              solve=_fake_solve(trajs, calls=calls))
    assert calls == []                                          # 全部跳过
    man = json.loads((tag_dir / 'base' / 'short' / 'manifest.json')
                     .read_text(encoding='utf-8'))
    assert all(e['status'] == 'skipped' for e in man['seeds'].values())
    assert man['status'] == 'complete'


def test_run_batch_interrupt_safe(iso_env):
    """AC#1 Ctrl-C：seed1 求解中中断 → KeyboardInterrupt 传播、已完成 seed0 产物
    在场、manifest 记 interrupted（重跑可续）。"""
    tmp, cal_root, _r, _i, _u, master = iso_env
    cfg = load_config(_write_config(tmp / 'cfg.json', master))
    tag_dir = cal.calibration_dir('t3')
    tag_dir.mkdir(parents=True)
    trajs = _trajs({('base/short', s): [(1.0, 0.7)] for s in range(3)}
                   | {('base/full', 0): [(1.0, 0.8)]})
    with pytest.raises(KeyboardInterrupt):
        run_batch(cfg, tag_dir, short_seeds=3, short_time=2, full_seeds=1,
                  full_time=2, solve=_fake_solve(trajs, interrupt_on=('base/short', 1)))
    assert (tag_dir / 'base' / 'short' / 'curve_s0.json').is_file()
    assert (tag_dir / 'base' / 'short' / 'best_frame_s0.json').is_file()
    assert not (tag_dir / 'base' / 'short' / 'curve_s1.json').exists()
    assert not (tag_dir / 'base' / 'full').exists()           # full 组未启动
    man = json.loads((tag_dir / 'base' / 'short' / 'manifest.json')
                     .read_text(encoding='utf-8'))
    assert man['status'] == 'interrupted'
    assert man['seeds']['0']['status'] == 'done'
    # 续跑：seed0 跳过、seed1/2 补齐、状态回 complete
    calls: list = []
    run_batch(cfg, tag_dir, short_seeds=3, short_time=2, full_seeds=1, full_time=2,
              solve=_fake_solve(trajs, calls=calls))
    assert calls == [('base/short', 1), ('base/short', 2), ('base/full', 0)]
    man = json.loads((tag_dir / 'base' / 'short' / 'manifest.json')
                     .read_text(encoding='utf-8'))
    assert man['status'] == 'complete'
    assert man['seeds']['0']['status'] == 'skipped'


# ------------------------------------------------------- AC#1 variants 编排


def test_run_variants_orchestration(iso_env, monkeypatch):
    """AC#1：变体配置生成 + 逐变体 short/full 组串行落盘；commit 复用不再重切；
    变体 cfg 的 quantities 已抖动且过 load_config 校验（AC#2）。"""
    tmp, cal_root, _r, _i, _u, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    cfg = load_config(cfg_path)
    tag_dir = cal.calibration_dir('t4')
    tag_dir.mkdir(parents=True)
    run_batch(cfg, tag_dir, short_seeds=1, short_time=2, full_seeds=1, full_time=2,
              solve=_fake_solve(_trajs({('base/short', 0): [(1.0, 0.7)],
                                        ('base/full', 0): [(1.0, 0.8)]})))
    # commit 已在场：再跑 variants 不得重切（复用同一份 commit 产物）
    def _bomb(*a, **kw):
        raise AssertionError('commit_from_config 不应被再次调用（应复用已有 commit）')
    monkeypatch.setattr(cal, 'commit_from_config', _bomb)

    trajs = _trajs({(f'variant_{i}/{grp}', s): [(1.0, 0.7 + i * 0.01)]
                    for i in range(2) for grp in ('short', 'full') for s in range(2)})
    active = {'n': 0}
    cfgs: list = []
    calls: list = []
    res = run_variants(cfg, tag_dir, n_variants=2, short_seeds=2, short_time=2,
                       full_seeds=1, full_time=2,
                       solve=_fake_solve(trajs, active=active, calls=calls, cfgs=cfgs),
                       base_raw=json.loads(cfg_path.read_text(encoding='utf-8')))
    assert active['n'] == 0
    assert calls == [('variant_0/short', 0), ('variant_0/short', 1),
                     ('variant_0/full', 0), ('variant_1/short', 0),
                     ('variant_1/short', 1), ('variant_1/full', 0)]
    for i in range(2):
        v_path = tag_dir / f'variant_{i}.json'
        assert v_path.is_file()
        v_cfg = load_config(v_path)                            # AC#2：合法 7 键
        assert v_cfg.master_dxf == cfg.master_dxf and v_cfg.gate_mm == cfg.gate_mm
        assert v_cfg.per_type == cfg.per_type and v_cfg.sizes == cfg.sizes
        for s in range(2):
            assert (tag_dir / f'variant_{i}' / 'short' / f'curve_s{s}.json').is_file()
        assert (tag_dir / f'variant_{i}' / 'full' / 'curve_s0.json').is_file()
        assert res[f'variant_{i}']['short']['status'] == 'complete'
    # 求解收到的变体 cfg：quantities 是抖动后的（至少一个变体与基不同）
    base_q = cfg.quantities
    assert any(c.quantities != base_q for c in cfgs)
    # 变体文件与确定性生成器逐字节一致
    raw = json.loads((tmp / 'cfg.json').read_text(encoding='utf-8'))
    for i, v in enumerate(generate_variants(raw, 2)):
        assert json.loads((tag_dir / f'variant_{i}.json').read_text(
            encoding='utf-8')) == v


# ------------------------------------------------------- analyze 纯函数


def test_curve_stats_fields():
    """终值/best/time-to-best/收敛平台/uplift 口径。"""
    c = _mk_curve([(10, 0.5), (50, 0.7), (80, 0.78), (100, 0.8)], compress_from=1)
    st = curve_stats(c)
    assert st['n_frames'] == 4
    assert st['final_density'] == pytest.approx(0.8)
    assert st['best_density'] == pytest.approx(0.8)
    assert st['time_to_best'] == pytest.approx(100.0)
    assert st['plateau_sec'] == pytest.approx(0.0)
    # 峰值在中间：平台 = 末帧 − best 帧
    st2 = curve_stats(_mk_curve([(10, 0.5), (50, 0.8), (100, 0.79)]))
    assert st2['best_density'] == pytest.approx(0.8)
    assert st2['time_to_best'] == pytest.approx(50.0)
    assert st2['plateau_sec'] == pytest.approx(50.0)
    assert st2['plateau_ratio'] == pytest.approx(0.5)
    # uplift：首压缩帧 best-so-far(0.7) → 最终 best(0.8) 的增量
    assert st['uplift'] == pytest.approx(0.1)
    assert curve_stats(_mk_curve([(10, 0.5)]))['uplift'] is None   # 无压缩帧


def test_envelope_monotone_and_grid():
    """AC#3 包络单调性 + τ 网格 + 低位分位数取值（手算对拍）。"""
    a = _mk_curve([(10, 0.5), (50, 0.7), (100, 0.85)])
    b = _mk_curve([(10, 0.6), (50, 0.75), (100, 0.82)])
    env = envelope_from_curves([a, b], 0.8, 0.25)
    assert sorted(env) == [f'{t:.2f}' for t in cal.TAU_GRID]   # 0.05~1.0 共 20 格
    vals = [env[k] for k in sorted(env)]
    assert vals == sorted(vals)                                # 单调不降
    assert env['0.05'] == pytest.approx(0.525)                 # q25([0.5, 0.6])
    assert env['0.15'] == pytest.approx(0.7125)                # q25([0.7, 0.75])
    assert env['1.00'] == pytest.approx(0.8275)                # q25([0.85, 0.82])
    # 全不达标 → 空包络
    assert envelope_from_curves([a], 0.99) == {}


def test_uplift_quantiles():
    """AC#3 uplift 分位数（q50/q95 手算对拍 + 无压缩帧不计入）。"""
    c1 = _mk_curve([(5, 0.7), (30, 0.75), (60, 0.79), (100, 0.80)], compress_from=1)
    c2 = _mk_curve([(5, 0.72), (30, 0.76), (100, 0.79)], compress_from=1)
    plain = _mk_curve([(5, 0.6), (100, 0.62)])                 # 无压缩帧
    up = uplift_distribution([c1, c2, plain])
    assert up['n'] == 2
    assert up['q50'] == pytest.approx(0.04)                    # [0.05, 0.03] 中位
    assert up['q95'] == pytest.approx(0.049)                   # 0.03*0.05+0.05*0.95
    assert uplift_distribution([plain]) == {'q50': None, 'q95': None, 'n': 0}


def test_separation_and_rank_correlation():
    """AC#3 达标/失败分离度 → τ0 推荐；短/全秩相关（同 seed 值配对）。"""
    success = [_mk_curve([(10, 0.7), (50, 0.8), (100, 0.85)]),
               _mk_curve([(10, 0.72), (50, 0.82), (100, 0.86)])]
    fail = [_mk_curve([(10, 0.55), (50, 0.58), (100, 0.6)]),
            _mk_curve([(10, 0.56), (50, 0.6), (100, 0.62)])]
    sep = separation_tau0(success + fail, 0.8)
    assert sep['tau0_recommended'] == pytest.approx(0.05)      # 首格点即分离
    assert sep['gap_at_tau0'] > 0
    assert separation_tau0(success, 0.8)['tau0_recommended'] == \
        pytest.approx(0.3)                                     # 无失败侧 → 回退默认

    hi = _mk_curve([(10, 0.8), (100, 0.86)])
    lo = _mk_curve([(10, 0.7), (100, 0.72)])
    mid = _mk_curve([(10, 0.75), (100, 0.8)])
    rc = rank_correlation({0: lo, 1: hi, 2: mid}, {0: lo, 1: hi, 2: mid})
    assert rc['n_pairs'] == 3 and rc['spearman_best'] == pytest.approx(1.0)
    rc_anti = rank_correlation({0: lo, 1: hi, 2: mid}, {0: hi, 1: lo, 2: mid})
    assert rc_anti['spearman_best'] == pytest.approx(-1.0)
    assert rank_correlation({0: hi}, {0: hi})['spearman_best'] is None  # 配对不足
    assert spearman([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)


def test_replay_r1_semantics():
    """AC#3 R1 离线重放：迟滞（持续 W 秒才杀）/ 瞬时下探不杀 / τ0 门限 / 追平清零。"""
    env = {'0.10': 0.70, '0.50': 0.75, '1.00': 0.80}
    fail = _mk_curve([(5, 0.6), (20, 0.62), (60, 0.63), (100, 0.64)])
    late = _mk_curve([(5, 0.55), (20, 0.6), (35, 0.62), (50, 0.85), (100, 0.9)])
    solid = _mk_curve([(5, 0.7), (20, 0.78), (100, 0.88)])
    assert replay_r1(fail, env, _KP) is True      # 包络下方持续 ≥10s → kill
    assert replay_r1(late, env, _KP) is True      # 慢热达标者也会被判（回测计误杀）
    assert replay_r1(solid, env, _KP) is False    # 一直在包络上方 → 不杀
    # τ0 门限：tau0=1.0 时全程不评估 → 不杀
    kp_late = {**_KP, 'tau0': 1.0}
    assert replay_r1(fail, env, kp_late) is False
    # 瞬时下探 4s 后追平（< W=10s）→ 不杀；追平清零后不再累计
    env_flat = {'0.10': 0.75, '1.00': 0.75}
    transient = _mk_curve([(5, 0.7), (20, 0.6), (24, 0.6), (30, 0.76), (100, 0.9)])
    assert replay_r1(transient, env_flat, _KP) is False
    sustained = _mk_curve([(5, 0.7), (20, 0.6), (31, 0.6), (100, 0.65)])
    assert replay_r1(sustained, env_flat, _KP) is True         # 31−20=11s ≥ W
    # 空 envelope / 坏 envelope → 恒 False（R1 禁用）
    assert replay_r1(fail, {}, _KP) is False


def test_backtest_and_split():
    """AC#3 train/test 误杀回测：would-kill 计数与误杀（本可达标被杀）口径正确；
    确定性二分（键字典序奇偶）。"""
    fail = _mk_curve([(5, 0.6), (20, 0.62), (60, 0.63), (100, 0.64)])
    late = _mk_curve([(5, 0.55), (20, 0.6), (35, 0.62), (50, 0.85), (100, 0.9)])
    solid = _mk_curve([(5, 0.7), (20, 0.78), (100, 0.88)])
    env = {'0.10': 0.70, '0.50': 0.75, '1.00': 0.80}
    bt = backtest([fail, late, solid], 0.8, _KP, env)
    assert bt == {'n': 3, 'would_kill': 2, 'false_kill': 1, 'false_kill_rate': 0.5}
    assert backtest([solid], 0.8, _KP, env)['false_kill_rate'] == 0.0  # 无 would-kill

    curves = {'base_full_s0': solid, 'base_full_s1': fail,
              'base_short_s0': late, 'base_short_s1': solid}
    train, test = split_train_test(curves)
    assert len(train) == len(test) == 2
    assert id(train[0]) == id(curves['base_full_s0'])          # 字典序 even → train
    assert id(test[0]) == id(curves['base_full_s1'])


def test_generalization_report():
    """AC#3 泛化报告：base 包络 × 变体误杀率字段 + 可迁移性判定 + 无变体降级。"""
    env = {'0.10': 0.70, '0.50': 0.75, '1.00': 0.80}
    solid = _mk_curve([(5, 0.7), (20, 0.78), (100, 0.88)])
    fail = _mk_curve([(5, 0.6), (20, 0.62), (100, 0.63)])
    late = _mk_curve([(5, 0.55), (20, 0.6), (35, 0.62), (50, 0.85), (100, 0.9)])
    g = cal.generalization_report({'variant_0': [solid, fail]}, 0.8, _KP, env)
    assert g['variants']['variant_0']['would_kill'] == 1
    assert g['variants']['variant_0']['false_kill'] == 0
    assert g['variants']['variant_0']['false_kill_rate'] == 0.0
    assert g['overall']['false_kill_rate'] == 0.0
    assert g['transferable'] is True                            # 全部 < 5%
    g_bad = cal.generalization_report({'variant_0': [late, fail]}, 0.8, _KP, env)
    assert g_bad['variants']['variant_0']['would_kill'] == 2
    assert g_bad['variants']['variant_0']['false_kill'] == 1
    assert g_bad['variants']['variant_0']['false_kill_rate'] == 0.5
    assert g_bad['transferable'] is False
    g_none = cal.generalization_report({}, 0.8, _KP, env)
    assert g_none['overall'] is None and g_none['transferable'] is None
    assert '无变体曲线' in g_none['note']


# ------------------------------------------------------- CLI 端到端


def _seed_tag_curves(cal_root: Path, tag: str, short: dict[int, list],
                     full: dict[int, list] | None = None,
                     variants: dict[str, dict[str, dict[int, list]]] | None = None):
    """直接往 tag 目录写曲线文件（analyze 的输入侧，不经求解）。"""
    tag_dir = cal_root / tag
    for grp, curves in (('short', short), ('full', full or {})):
        d = tag_dir / 'base' / grp
        d.mkdir(parents=True, exist_ok=True)
        for seed, curve in curves.items():
            _write_solve_artifacts(d, seed, curve)
    for name, groups in (variants or {}).items():
        for grp, curves in groups.items():
            d = tag_dir / name / grp
            d.mkdir(parents=True, exist_ok=True)
            for seed, curve in curves.items():
                _write_solve_artifacts(d, seed, curve)
    return tag_dir


def test_cli_batch_end_to_end(iso_env, capsys, monkeypatch):
    """AC#1/AC#4 端到端：batch CLI 跑通（真 commit + fake solve）、目录契约成立、
    产物只落 portfolio_calibration（config_runs 空 + web 事实源哨兵不变）。"""
    tmp, cal_root, runs, inter, uploads, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    monkeypatch.setattr(cal, 'solve_pieces', _fake_solve(
        _trajs({('base/short', 0): [(1.0, 0.7), (2.0, 0.72)],
                ('base/full', 0): [(1.0, 0.8), (2.0, 0.82)]})))

    rc = main(['batch', '--config', str(cfg_path), '--tag', 'e2e',
               '--short-seeds', '1', '--short-time', '2',
               '--full-seeds', '1', '--full-time', '2'])
    out = capsys.readouterr().out
    assert rc == 0
    assert '标定根目录' in out and '[batch] 完成' in out
    assert '预计求解总时长 ≈ 4s' in out
    tag_dir = cal_root / 'e2e'
    assert (tag_dir / 'base_config.json').is_file()
    assert (tag_dir / 'commit' / 'pieces_intermediate.json').is_file()
    assert (tag_dir / 'base' / 'short' / 'curve_s0.json').is_file()
    assert (tag_dir / 'base' / 'full' / 'best_frame_s0.json').is_file()
    # AC#4：产物只落 out/portfolio_calibration/ —— config_runs / web 事实源零触碰
    assert list(runs.iterdir()) == []
    assert json.loads(inter.read_text(encoding='utf-8')) == {'sentinel': True}
    assert list(uploads.iterdir()) == []
    # 配置错误路径：不存在的 config → 退出码 1
    assert main(['batch', '--config', str(tmp / 'nope.json')]) == 1
    assert '配置错误' in capsys.readouterr().err
    # 非法旗标值 → 标定错误退出 1
    assert main(['batch', '--config', str(cfg_path), '--short-seeds', '0']) == 1


def test_cli_variants_end_to_end(iso_env, capsys, monkeypatch):
    """AC#1 端到端：variants CLI 生成 variant_{i}.json（过 load_config）+ 逐变体
    short/full 组曲线落盘 + commit 复用。"""
    tmp, cal_root, _r, _i, _u, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    trajs = _trajs({('base/short', 0): [(1.0, 0.7), (2.0, 0.72)],
                    ('base/full', 0): [(1.0, 0.8)]}
                   | {(f'variant_{i}/{grp}', 0): [(1.0, 0.7 + i * 0.01)]
                      for i in range(2) for grp in ('short', 'full')})
    solve = _fake_solve(trajs)
    monkeypatch.setattr(cal, 'solve_pieces', solve)
    # 先 batch 建 commit（variants 复用同一份 commit）
    assert main(['batch', '--config', str(cfg_path), '--tag', 'e2e',
                 '--short-seeds', '1', '--short-time', '2',
                 '--full-seeds', '1', '--full-time', '2']) == 0
    rc = main(['variants', '--config', str(cfg_path), '--tag', 'e2e',
               '--variants', '2', '--short-seeds', '1', '--short-time', '2',
               '--full-seeds', '1', '--full-time', '2'])
    capsys.readouterr()
    assert rc == 0
    tag_dir = cal_root / 'e2e'
    for i in range(2):
        assert load_config(tag_dir / f'variant_{i}.json').gate_mm == 1980
        assert (tag_dir / f'variant_{i}' / 'short' / 'curve_s0.json').is_file()
        assert (tag_dir / f'variant_{i}' / 'full' / 'curve_s0.json').is_file()


def test_cli_analyze_end_to_end(iso_env, capsys):
    """AC#3 端到端：analyze 聚合 base+变体曲线 → analysis/ 三产物；calibrated=true
    （≥10 seed）、泛化报告含误杀率字段、控制台摘要行。"""
    _tmp, cal_root, _r, _i, _u, _m = iso_env
    # 12 short + 4 full：10 达标（快升 0.85+）+ 6 失败（低位 0.6x）；变体 1 个。
    short = {s: _mk_curve([(10, 0.5), (50, 0.7), (100, 0.85 if s < 10 else 0.62)],
                          compress_from=1) for s in range(12)}
    full = {s: _mk_curve([(10, 0.5), (150, 0.72), (300, 0.85 if s < 3 else 0.64)],
                         compress_from=1) for s in range(4)}
    var0 = {'variant_0': {'short': {0: _mk_curve([(10, 0.5), (50, 0.7), (100, 0.84)],
                                                       compress_from=1),
                                    1: _mk_curve([(10, 0.4), (50, 0.55), (100, 0.6)])},
                          'full': {0: _mk_curve([(10, 0.5), (150, 0.74), (300, 0.86)],
                                                compress_from=1)}}}
    _seed_tag_curves(cal_root, 'an1', short, full, var0)

    rc = main(['analyze', '--tag', 'an1', '--target', '0.8'])
    out = capsys.readouterr().out
    assert rc == 0
    tag_dir = cal_root / 'an1'
    params = json.loads((tag_dir / 'analysis' / 'controller_params.json')
                        .read_text(encoding='utf-8'))
    summary = json.loads((tag_dir / 'analysis' / 'summary.json')
                         .read_text(encoding='utf-8'))
    general = json.loads((tag_dir / 'analysis' / 'generalization.json')
                         .read_text(encoding='utf-8'))
    assert params['calibrated'] is True
    assert set(params['envelope']) == {f'{t:.2f}' for t in cal.TAU_GRID}
    assert {'tau0', 'W', 'm', 'epsilon', 'delta', 'm_streak', 'uplift_q95'} <= set(params)
    assert summary['base']['short']['n_seeds'] == 12
    assert summary['base']['short']['p_reach'] == pytest.approx(10 / 12, abs=1e-4)
    assert summary['base']['full']['n_seeds'] == 4
    assert summary['rank_correlation']['n_pairs'] == 4
    assert 'variant_0' in summary['variants']
    assert 'false_kill_rate' in general['variants']['variant_0']   # AC#3 泛化字段
    assert 'overall' in general and 'transferable' in general
    assert '误杀回测' in out and 'controller_params: calibrated=true' in out
    assert '泛化: 1 个变体' in out
    # 与 --params 消费方兼容：portfolio.load_controller_params 可加载
    from materialsorting.cli.portfolio import load_controller_params
    assert load_controller_params(tag_dir / 'analysis' / 'controller_params.json') \
        == params


def test_cli_analyze_small_sample_rejects(iso_env, capsys):
    """AC#3 小样本拒绝下发：3 条 base 曲线 → calibrated=false + 空 envelope。"""
    _tmp, cal_root, _r, _i, _u, _m = iso_env
    short = {s: _mk_curve([(10, 0.5), (100, 0.85)], compress_from=1) for s in range(3)}
    _seed_tag_curves(cal_root, 'small', short)
    rc = main(['analyze', '--tag', 'small', '--target', '0.8'])
    out = capsys.readouterr().out
    assert rc == 0
    params = json.loads((cal_root / 'small' / 'analysis' / 'controller_params.json')
                        .read_text(encoding='utf-8'))
    assert params['calibrated'] is False
    assert params['envelope'] == {}                    # 空 envelope → R1 整体禁用
    assert 'calibrated=false' in out


def test_cli_analyze_errors(iso_env, capsys):
    """analyze 输入校验：--target 越界退出 1；tag 无 base/short 曲线退出 1。"""
    _tmp, cal_root, _r, _i, _u, _m = iso_env
    assert main(['analyze', '--tag', 'none', '--target', '0.8']) == 1
    assert '无曲线' in capsys.readouterr().err
    short = {0: _mk_curve([(10, 0.5), (100, 0.85)])}
    _seed_tag_curves(cal_root, 'ok', short)
    assert main(['analyze', '--tag', 'ok', '--target', '0']) == 1
    assert '--target' in capsys.readouterr().err
    assert main(['analyze', '--tag', 'ok', '--target', '0.8',
                 '--env-quantile', '0.9']) == 1
    assert '--env-quantile' in capsys.readouterr().err


# ------------------------------------------------------- 分层 + 导入冒烟


def test_layering_calibration_no_web_import():
    """calibration 全模块（含函数内）不 import web —— 经 pipeline 间接复用求解。"""
    tree = ast.parse(Path(cal.__file__).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parts = [p for p in (node.module or '').split('.') if p]
            assert 'web' not in parts, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert 'web' not in alias.name.split('.'), alias.name


def test_module_help_smoke():
    """``python -m materialsorting.cli.calibration <子命令> --help`` 四入口冒烟。"""
    import os
    env = {**os.environ, 'PYTHONPATH': str(_SRC)}
    for cmd in ('batch', 'variants', 'analyze', 'simulate'):
        r = subprocess.run(
            [sys.executable, '-m', 'materialsorting.cli.calibration', cmd, '--help'],
            capture_output=True, env=env, cwd=str(_SRC.parent), timeout=60)
        assert r.returncode == 0, (cmd, r.stderr)
        assert b'usage' in r.stdout.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
