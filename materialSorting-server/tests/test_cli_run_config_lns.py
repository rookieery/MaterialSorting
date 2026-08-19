"""US-008（PC-008）``run_config --lns``：LNS 后处理接入 portfolio 编排测试。

驱动方式：fake ``solve_pieces``（monkeypatch ``rc_mod.solve_pieces``，帧布局按
用例构造 —— 「人工空洞」布局把末片甩到远端 x，让缺省波段宽（1.5×NEST_GATE_MM）
下必出**纯空洞段**，LNS 空段 splice 无需求解即确定性改进）+ fake ``_solve_band``
（monkeypatch ``lns_mod._solve_band``，row packer 差解恒拒 —— 改进只来自 splice，
不依赖真求解器）。覆盖 PRD 验收：

  - 改进路径：incumbent 的 density/width_mm/placed_items 更新（seed/frame_index
    出处保持）+ ``lns`` 段 before/after/delta/轮次明细；best 与 portfolio.incumbent
    同步；末行汇总取 LNS 后口径；
  - 不优路径：result.json 与 LNS 启动时刻**逐字节一致**（跨 run 对拍因 run_dir
    时间戳路径天然不同，故以「LNS 入口快照 vs 终态」为口径），无 lns 键，明细仍
    写 result_lns.json + lns_compare.svg；
  - ``--lns`` × ``--target``：R0 提前停后同样执行后处理（对达标解再压宽度）；
  - Ctrl-C 中断安全：LNS 环节内中断（fake 子求解抛 KeyboardInterrupt → run_lns
    内部捕获）→ 已完成轮写 result_lns.json、主 result.json 一次性完整回写不半写、
    退出码 130；LNS 窗口外中断 → 130 且 result.json 不动；
  - 旗标裁决：``--lns-time`` / ``--lns-rounds`` 单独给出 / 值 <1 → 配置错误
    退出 1 不建 run_dir；``--quiet`` 抑制 LNS 进度行但保留前后两行汇总与启动行；
  - 单 seed 旧语义：best 帧边车（best_frame_s{seed}.json）回填路径 + lns 段
    （portfolio 段保持空、best 保持 solve 记录语义）；
  - LNS 输入错误（无布局可回填）降级 stderr warn 跳过，退出码 0、交付物不受影响；
  - ``--help`` 子进程冒烟 + 分层（run_config 模块级不 import web）。
"""
from __future__ import annotations

import ast
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
from materialsorting.cli.run_config import main
from materialsorting.web import server as server_mod

# 与 test_cli_run_config 同构的合成母版（含 layer-7 布纹线，片不旋转）：6 片有码号。
_SYNTH_BLOCKS = [
    ('blk x.28', (0.12345, 0.6789, 400.123456, 700.987654)),
    ('blk x.29', (0.12345, 0.6789, 400.123456, 720.987654)),
    ('zz 9.28', (1.5, 2.25, 200.111111, 90.222222)),
    ('zz 9.29', (1.5, 2.25, 200.111111, 95.222222)),
    ('M55#2 a.28', (2.75, 3.125, 120.333333, 60.444444)),
    ('M55#2 a.29', (2.75, 3.125, 120.333333, 65.444444)),
]
_N_PIECES = len(_SYNTH_BLOCKS)

# 末片甩到的远端 x（缺省波段宽 1.5×1910=2865：[2865,5730) 成纯空洞段，
# splice 确定性缩短总宽）。
_FAR_X = 6000.0


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


# ------------------------------------------------------- fake 驱动装置


def _layout_of(pieces: list, kind: str) -> list:
    """布局构造：``holey`` = 前 n-1 片叠在 x≈0 + 末片甩到 _FAR_X（人工空洞）；
    ``compact`` = 全部叠在 x≈0（单波段，row packer 差解恒拒 → 不改进）。"""
    if kind == 'holey':
        placed = [{'id': p['pid'], 'rotation': 0.0, 'translation': [0.0, 0.0]}
                  for p in pieces[:-1]]
        placed.append({'id': pieces[-1]['pid'], 'rotation': 0.0,
                       'translation': [_FAR_X, 0.0]})
        return placed
    return [{'id': p['pid'], 'rotation': 0.0, 'translation': [0.0, 0.0]}
            for p in pieces]


def _rec(seed: int, frames: list, *, killed=False, reason=None) -> dict:
    """帧序列 → solve_pieces 同形返回记录（killed 时取 best-so-far 帧口径）。"""
    best = max(frames, key=lambda fr: fr['density']) if frames else None
    ref = best if killed else frames[-1]
    rec = {
        'seed': seed, 'n_items': _N_PIECES, 'n_eroded': 0,
        'total_area_mm2': 1_000_000.0,
        'width_mm': ref['width_mm'], 'real_density': ref['density'],
        'density_sparrow': ref['density_sparrow'],
        'placed_items': _N_PIECES, 'elapsed': ref['elapsed'],
    }
    if killed:
        rec['killed'] = True
        rec['kill_reason'] = reason or 'should_stop'
    return rec


def _fake_solve(traj: dict, *, sidecar=False, calls: list | None = None):
    """伪 solve_pieces：``traj = {seed: [(density, layout_kind), ...]}`` 逐帧投递。

    契约镜像 ``solve_pieces``：每帧先 ``on_progress``（banking）再 ``should_stop``
    （触发即停，best-so-far 帧交付 ``killed=True``）；``sidecar=True`` 时镜像写
    ``best_frame_s{seed}.json``（单 seed 旧语义 best 的布局回填路径）。帧
    ``width_mm`` 恒报 9000（LNS 前后宽度由几何重算，与帧汇报值独立）。
    """
    def solve(cfg, run_dir, *, seed, time_budget=None, on_progress=None,
              should_stop=None, **kw):
        if calls is not None:
            calls.append(seed)
        pieces = json.loads((Path(run_dir) / 'pieces_intermediate.json')
                            .read_text(encoding='utf-8'))['pieces']
        frames = []

        def _finish(killed=False, reason=None):
            if sidecar and frames:
                best = max(frames, key=lambda fr: fr['density'])
                (Path(run_dir) / ('best_frame_s%d.json' % seed)).write_text(
                    json.dumps({'seed': seed, 'density': best['density'],
                                'width_mm': best['width_mm'],
                                'placed_items': best['placed_items']},
                               ensure_ascii=False), encoding='utf-8')
            return _rec(seed, frames, killed=killed, reason=reason)

        for idx, (d, kind) in enumerate(traj[seed]):
            fr = {'elapsed': float(idx + 1), 'phase': 'exploring',
                  'density': float(d), 'density_sparrow': float(d) + 0.02,
                  'width_mm': 9000.0, 'placed_items': _layout_of(pieces, kind)}
            frames.append(fr)
            if on_progress is not None:
                on_progress(fr)
            if should_stop is not None:
                verdict = should_stop(fr)
                if verdict:
                    return _finish(killed=True,
                                   reason=verdict if isinstance(verdict, str) else None)
        return _finish()

    return solve


def _row_packer(pieces_subset, gate_mm, params):
    """确定性「差」子解：副本横排 y=0 —— span = Σ宽，几乎总不优于原段（恒拒）。"""
    qty = params.get('quantities') or {}
    placed, x = [], 0.0
    for p in pieces_subset:
        sk = 'null' if p['size'] is None else str(p['size'])
        n = int((qty.get(p.get('label')) or {}).get(sk, 1))
        w = p['bbox'][2]
        for _ in range(n):
            placed.append({'id': p['pid'], 'rotation': 0.0,
                           'translation': [x, 0.0]})
            x += w
    return {'placed_items': placed, 'width_mm': x}


class _KiSolve:
    """fake 子求解：首次调用抛 KeyboardInterrupt（模拟 LNS 环节内 Ctrl-C）。"""

    def __init__(self):
        self.calls = 0

    def __call__(self, pieces_subset, gate_mm, params):
        self.calls += 1
        raise KeyboardInterrupt


def _patch(monkeypatch, traj, *, solve=None, sidecar=False, calls=None):
    """统一 monkeypatch：run_config.solve_pieces ← fake 轨迹；lns._solve_band ←
    差解 / KI 求解。返回 (rc_mod, lns_mod) 引用便于用例内再定制。"""
    from materialsorting.cli import lns as lns_mod
    from materialsorting.cli import run_config as rc_mod
    monkeypatch.setattr(rc_mod, 'solve_pieces',
                        _fake_solve(traj, sidecar=sidecar, calls=calls))
    monkeypatch.setattr(lns_mod, '_solve_band',
                        solve if solve is not None else _row_packer)
    return rc_mod, lns_mod


# ------------------------------------------------------- AC#1 改进 / 不优路径


def test_improved_updates_incumbent_and_adds_lns_section(iso_env, capsys, monkeypatch):
    """AC#1 改进路径：空段 splice 确定性改进 → incumbent 的 density/width_mm/
    placed_items 更新（seed/frame_index 出处保持）、lns 段含 before/after/
    delta/轮次明细、best 同步、result_lns.json + lns_compare.svg 落盘、
    stdout 前后两行 + 末行取 LNS 后口径。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0, 1])
    _patch(monkeypatch, {0: [(0.5, 'holey')], 1: [(0.4, 'holey'), (0.6, 'holey')]})

    rc = main([str(cfg_path), '--time', '2', '--lns', '--lns-time', '3',
               '--lns-rounds', '2'])
    assert rc == 0
    stdout = capsys.readouterr().out
    assert 'LNS 后处理: time=3s rounds=2' in stdout          # 启动说明行（恒打）
    assert '空段' in stdout                                   # LNS 接受进度行（echo=print）
    assert '[LNS] 前' in stdout and '[LNS] 后' in stdout
    assert 'improved=True' in stdout

    (rd,) = list(runs.iterdir())
    doc = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    lns = doc['lns']
    assert set(lns) == {'time_budget_sec', 'rounds_requested', 'rounds_executed',
                        'stop_reason', 'interrupted', 'elapsed', 'band_width_mm',
                        'improved', 'before', 'after', 'delta', 'recheck',
                        'rounds_detail', 'base_seed', 'result_lns', 'compare_svg'}
    assert lns['improved'] is True and lns['interrupted'] is False
    assert lns['time_budget_sec'] == 3.0 and lns['rounds_requested'] == 2
    assert lns['after']['width_mm'] < lns['before']['width_mm']
    assert lns['after']['density'] > lns['before']['density']
    assert lns['delta']['width_mm'] > 0
    assert lns['rounds_detail'] and any(d['accepted'] for d in lns['rounds_detail'])
    assert lns['base_seed'] == 1                              # incumbent 来源 seed
    # incumbent 三字段更新；seed/frame_index 保持来源帧出处
    inc = doc['portfolio']['incumbent']
    assert inc['density'] == lns['after']['density']
    assert inc['width_mm'] == lns['after']['width_mm']
    assert inc['seed'] == 1 and inc['frame_index'] == 1
    assert doc['best'] == inc                                # best 与 incumbent 同步
    out = json.loads((rd / 'result_lns.json').read_text(encoding='utf-8'))
    assert out['improved'] is True
    assert out['placed_items'] == inc['placed_items']        # 改进布局 = 回写布局
    assert out['recheck']['ok'] is True
    assert (rd / 'lns_compare.svg').is_file()
    # 末行汇总（real_density 契约）取 LNS 后口径
    last_line = stdout.strip().splitlines()[-1]
    assert 'real_density（原面积口径）' in last_line
    assert ('%.2f%%' % (lns['after']['density'] * 100)) in last_line


def test_not_improved_result_json_byte_identical(iso_env, capsys, monkeypatch):
    """AC#1 不优路径：compact 布局无空洞且差解恒拒 → result.json 与 LNS 启动时刻
    逐字节一致（无 lns 键），明细仍写 result_lns.json + lns_compare.svg。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0, 1])
    rc_mod, _lns_mod = _patch(monkeypatch, {0: [(0.5, 'compact')],
                                            1: [(0.6, 'compact')]})
    snap = {}
    orig = rc_mod.postprocess_run_dir

    def _snapshot_then_run(run_dir, **kw):
        snap['bytes'] = (Path(run_dir) / 'result.json').read_bytes()
        return orig(run_dir, **kw)

    monkeypatch.setattr(rc_mod, 'postprocess_run_dir', _snapshot_then_run)

    rc = main([str(cfg_path), '--time', '2', '--lns', '--lns-time', '3',
               '--lns-rounds', '2'])
    assert rc == 0
    stdout = capsys.readouterr().out
    assert '[LNS] 前' in stdout and '[LNS] 后' in stdout and 'improved=False' in stdout

    (rd,) = list(runs.iterdir())
    assert (rd / 'result.json').read_bytes() == snap['bytes']   # 逐字节不变
    doc = json.loads(snap['bytes'])
    assert 'lns' not in doc
    out = json.loads((rd / 'result_lns.json').read_text(encoding='utf-8'))
    assert out['improved'] is False
    assert (rd / 'lns_compare.svg').is_file()


# ------------------------------------------------------- AC#2 --target 组合


def test_r0_early_stop_still_runs_lns(iso_env, capsys, monkeypatch):
    """AC#2：--target R0 提前停（剩余 seed 不启动）后同样执行 LNS 后处理 ——
    对达标解也可再压宽度。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0, 1, 2])
    calls = []
    _patch(monkeypatch, {0: [(0.6, 'holey'), (0.55, 'holey')],
                         1: [(0.4, 'holey')], 2: [(0.4, 'holey')]}, calls=calls)

    rc = main([str(cfg_path), '--time', '2', '--target', '0.5', '--lns',
               '--lns-time', '3', '--lns-rounds', '2'])
    assert rc == 0
    assert calls == [0]                                      # R0：seed 1/2 未启动
    stdout = capsys.readouterr().out
    assert 'R0 达标即停' in stdout
    assert stdout.index('R0 达标即停') < stdout.index('[LNS] 前')   # 先停队再后处理
    assert 'improved=True' in stdout

    (rd,) = list(runs.iterdir())
    doc = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert doc['lns']['improved'] is True
    assert doc['portfolio']['incumbent']['seed'] == 0        # 达标帧（含空洞布局）
    assert doc['portfolio']['incumbent']['width_mm'] == doc['lns']['after']['width_mm']
    assert (rd / 'result_lns.json').is_file()


# ------------------------------------------------------- AC#3 Ctrl-C 中断安全


def test_ctrl_c_inside_lns_writes_result_lns(iso_env, capsys, monkeypatch):
    """AC#3：Ctrl-C 在 LNS 环节内（run_lns 捕获）→ 已完成轮写 result_lns.json、
    主 result.json 一次性完整回写（不半写、可解析）、退出码 130。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0, 1])
    ki = _KiSolve()
    _patch(monkeypatch, {0: [(0.5, 'holey')], 1: [(0.6, 'holey')]}, solve=ki)

    rc = main([str(cfg_path), '--time', '2', '--quiet', '--lns', '--lns-time', '3'])
    assert rc == 130
    assert ki.calls >= 1                                     # 中断发生在子求解处
    err = capsys.readouterr().err
    assert '[中断]' in err and 'result_lns.json' in err

    (rd,) = list(runs.iterdir())
    out = json.loads((rd / 'result_lns.json').read_text(encoding='utf-8'))
    assert out['interrupted'] is True
    assert out['rounds_executed'] >= 1                       # 已完成轮保留
    assert any(d['accepted'] for d in out['rounds_detail'])  # 第 1 轮 splice 已接受
    # 主 result.json 完整可解析（未半写）：已完成改进照常入账
    doc = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert doc['lns']['interrupted'] is True and doc['lns']['improved'] is True
    assert doc['portfolio']['incumbent']['placed_items'] == out['placed_items']
    assert [s['seed'] for s in doc['solve']] == [0, 1]       # solve 数组完整


def test_ctrl_c_outside_lns_window(iso_env, capsys, monkeypatch):
    """AC#3（窗口外兜底）：Ctrl-C 落在 LNS 编排窗口（读文件/落盘前）→ 130、
    result.json 保持 portfolio 终态不动、无 result_lns.json。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0, 1])
    rc_mod, _lns_mod = _patch(monkeypatch, {0: [(0.5, 'holey')], 1: [(0.6, 'holey')]})

    def _bomb(run_dir, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(rc_mod, 'postprocess_run_dir', _bomb)
    rc = main([str(cfg_path), '--time', '2', '--lns'])
    assert rc == 130
    assert '[中断]' in capsys.readouterr().err
    (rd,) = list(runs.iterdir())
    doc = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert 'lns' not in doc and doc['portfolio']['incumbent'] is not None
    assert not (rd / 'result_lns.json').exists()


# ------------------------------------------------------- 旗标裁决与输出


def test_lns_flags_validation(iso_env, capsys):
    """--lns-time/--lns-rounds 单独给出（笔误）或值 <1 → 配置错误退出 1、不建 run_dir。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--lns-time', '5'])
    assert rc == 1
    assert '须与 --lns 同给' in capsys.readouterr().err
    rc = main([str(cfg_path), '--lns-rounds', '3'])
    assert rc == 1
    assert '须与 --lns 同给' in capsys.readouterr().err
    rc = main([str(cfg_path), '--lns', '--lns-time', '0'])
    assert rc == 1 and '--lns-time' in capsys.readouterr().err
    rc = main([str(cfg_path), '--lns', '--lns-rounds', '0'])
    assert rc == 1 and '--lns-rounds' in capsys.readouterr().err
    assert list(runs.iterdir()) == []                        # 不留空 run_dir


def test_quiet_suppresses_lns_progress_keeps_summary(iso_env, capsys, monkeypatch):
    """--quiet：LNS 接受进度行（echo）抑制，前后两行汇总与启动说明行仍打。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master, seeds=[0, 1])
    _patch(monkeypatch, {0: [(0.5, 'holey')], 1: [(0.6, 'holey')]})

    rc = main([str(cfg_path), '--time', '2', '--quiet', '--lns', '--lns-time', '3'])
    assert rc == 0
    stdout = capsys.readouterr().out
    assert '空段' not in stdout                              # run_lns echo 抑制
    assert 'LNS 后处理: time=3s rounds=5' in stdout          # 启动说明行（默认轮数 5）
    assert '[LNS] 前' in stdout and '[LNS] 后' in stdout     # 汇总两行（终局口径）
    (rd,) = list(runs.iterdir())
    doc = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert doc['lns']['improved'] is True


# ------------------------------------------------------- 旧语义 / 降级 / 冒烟


def test_single_seed_best_frame_sidecar_path(iso_env, capsys, monkeypatch):
    """单 seed 无旗标（portfolio 非激活）：布局经 best_frame_s{seed}.json 边车回填；
    改进写 lns 段，portfolio 段保持空、best 保持 solve 记录旧语义。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)       # seeds 缺省 [0]
    _patch(monkeypatch, {0: [(0.5, 'holey')]}, sidecar=True)

    rc = main([str(cfg_path), '--time', '2', '--lns', '--lns-time', '3'])
    assert rc == 0
    (rd,) = list(runs.iterdir())
    doc = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert doc['portfolio']['incumbent'] is None             # 非激活段保持空
    assert doc['best'] == doc['solve'][0]                    # best 旧语义
    assert doc['lns']['improved'] is True                    # 后处理改进入 lns 段
    assert doc['lns']['base_seed'] == 0
    out = json.loads((rd / 'result_lns.json').read_text(encoding='utf-8'))
    assert out['source']['incumbent_seed'] == 0              # 边车回填路径生效
    assert out['improved'] is True


def test_lns_input_error_degrades_to_warning(iso_env, capsys, monkeypatch):
    """LNS 输入错误（旧语义 run 无 best 帧边车可回填）→ stderr warn 跳过后处理，
    退出码 0、result.json 不动、汇总照常收尾（后处理失败不否定交付物）。"""
    tmp, runs, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)       # 单 seed 无旗标 → 非激活
    _patch(monkeypatch, {0: [(0.5, 'holey')]})               # sidecar=False → 无边车

    rc = main([str(cfg_path), '--time', '2', '--lns', '--lns-time', '3'])
    assert rc == 0
    captured = capsys.readouterr()
    assert 'LNS 后处理失败' in captured.err
    assert 'real_density（原面积口径）' in captured.out      # 汇总照常
    (rd,) = list(runs.iterdir())
    doc = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert 'lns' not in doc
    assert not (rd / 'result_lns.json').exists()


def test_help_smoke():
    """AC#5：``python -m materialsorting.cli.run_config --help`` 跑通且含新旗标。"""
    r = subprocess.run([sys.executable, '-m', 'materialsorting.cli.run_config', '--help'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120)
    assert r.returncode == 0
    for flag in ('--lns', '--lns-time', '--lns-rounds'):
        assert flag in r.stdout


def test_layering_run_config_module_imports_pure():
    """分层未反向：run_config 模块级 import 不含 web（PC-008 新增 .lns 兄弟导入）。"""
    from materialsorting.cli import run_config as rc
    tree = ast.parse(Path(rc.__file__).read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert 'web' not in (node.module or '').split('.'), node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert 'web' not in alias.name.split('.'), alias.name


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
