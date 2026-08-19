"""US-003 ``cli/run_config.main`` + ``cli/pipeline.solve_pieces`` 测试。

合成母版（与 ``test_cli_pipeline.py`` 同构）走「commit → 求解」全链路：
solve_pieces 的指标口径（real_density=total_area/(width*gate)、placed==Σdemand、
per_type/quantities 透传）、main 的退出码矩阵（0/1）、result.json 落盘结构、
进度/汇总输出、web 事实源零触碰、分层（run_config 不 import web；pipeline 对
web.solver 仅函数内延迟 import）。
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
from materialsorting.cli.pipeline import commit_from_config, new_run_dir, solve_pieces
from materialsorting.cli.run_config import _clean_run_name, main
from materialsorting.web import server as server_mod

# 与 test_cli_pipeline 同构的合成母版：6 片有码号（sizes 28/29 各 3 片）+1 片 size=None。
_SYNTH_BLOCKS = [
    ('blk x.28', (0.12345, 0.6789, 400.123456, 700.987654)),
    ('blk x.29', (0.12345, 0.6789, 400.123456, 720.987654)),
    ('zz 9.28', (1.5, 2.25, 200.111111, 90.222222)),
    ('zz 9.29', (1.5, 2.25, 200.111111, 95.222222)),
    ('M55#2 a.28', (2.75, 3.125, 120.333333, 60.444444)),
    ('M55#2 a.29', (2.75, 3.125, 120.333333, 65.444444)),
]
_N_PIECES = len(_SYNTH_BLOCKS)                 # 6 片进 intermediate（g01..g06 × 28/29）


def _make_master_dxf(path: Path) -> Path:
    doc = ezdxf.new('R12')
    for name, (x, y, w, h) in _SYNTH_BLOCKS:
        blk = doc.blocks.new(name=name)
        poly = blk.add_polyline2d(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], dxfattribs={'layer': '1'})
        poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
        blk.add_line((x + 10, y + h / 2), (x + w - 10, y + h / 2), dxfattribs={'layer': '7'})
    blk = doc.blocks.new(name='noname nosize')     # size=None → commit 跳过
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


# ------------------------------------------------------- solve_pieces（AC#1）


def test_solve_pieces_metrics_and_demand_sum(iso_env):
    """solve_pieces：real_density=total_area/(width*gate) 原面积口径、placed==Σdemand、
    per_type 全 0 → n_eroded=0；quantities demand=2 → 副本翻倍计入 Σdemand。"""
    tmp, _, _, _, master = iso_env
    cfg = load_config(_write_config(tmp / 'cfg_basic.json', master))
    run_dir = new_run_dir('sp_basic')
    commit_from_config(cfg, run_dir)

    rec = solve_pieces(cfg, run_dir, seed=0, time_budget=2)

    assert rec['seed'] == 0
    assert rec['n_items'] == _N_PIECES
    assert rec['n_eroded'] == 0                       # per_type 缺省全 0
    assert rec['placed_items'] == _N_PIECES           # demand 缺省全 1
    assert rec['width_mm'] > 0
    assert 0.0 < rec['real_density'] < 1.0
    # 原面积口径公式对拍（分母 = width × gate，与 web _apply_density_dual 同式）
    expect = rec['total_area_mm2'] / (rec['width_mm'] * cfg.gate_mm)
    assert rec['real_density'] == pytest.approx(expect, abs=1e-4)
    assert rec['density_sparrow'] > 0                 # sparrow 自报口径同时在场
    assert rec['elapsed'] >= 0

    # quantities：g01 码 28 demand=2（label 命中且码号命中）；g01_29 label 命中但
    # 码号缺 → demand=0 跳过（D2）→ n_items=5、Σdemand=placed=6
    cfg_q = load_config(_write_config(
        tmp / 'cfg_qty.json', master, quantities={'g01': {'28': 2}}))
    rec_q = solve_pieces(cfg_q, run_dir, seed=0, time_budget=2)
    assert rec_q['n_items'] == _N_PIECES - 1          # g01_29 demand=0 不进实例
    assert rec_q['placed_items'] == 6                 # g01_28×2 + 其余 4 片各 1


def test_solve_pieces_erode_count_via_per_type(iso_env):
    """per_type d>0 → 命中 g 码全部码号 erode（n_eroded=2：g01 的 28/29 两片）。"""
    tmp, _, _, _, master = iso_env
    cfg = load_config(_write_config(
        tmp / 'cfg_erode.json', master, per_type={'g01': {'d': 2}}))
    run_dir = new_run_dir('sp_erode')
    commit_from_config(cfg, run_dir)
    rec = solve_pieces(cfg, run_dir, seed=0, time_budget=2)
    assert rec['n_eroded'] == 2                       # g01_28 + g01_29
    assert rec['placed_items'] == _N_PIECES


def test_solve_pieces_rejects_incomplete_solution(iso_env, monkeypatch):
    """解不完整（placed != Σdemand）→ RuntimeError（exit 2 的数据源）。"""
    tmp, _, _, _, master = iso_env
    cfg = load_config(_write_config(tmp / 'cfg_bad.json', master))
    run_dir = new_run_dir('sp_bad')
    commit_from_config(cfg, run_dir)

    import materialsorting.web.solver as web_solver

    class _FakeSol:                                    # 只放 1 片（Σdemand=6）
        width = 1000.0
        density = 0.5
        placed_items = [object()]

    def _fake_solve_with_callback(instance, config, on_report, **kw):
        return _FakeSol(), 0.1, None

    # pipeline 延迟 import 取的是 web_solver 模块属性 → patch 模块即生效
    monkeypatch.setattr(web_solver, 'solve_with_callback', _fake_solve_with_callback)
    with pytest.raises(RuntimeError, match='Σdemand'):
        solve_pieces(cfg, run_dir, seed=0, time_budget=1)


# ------------------------------------------------------- main / run_config（AC#2）


def test_main_end_to_end_smoke(iso_env, capsys):
    """AC 冒烟（合成母版缩小版）：rc=0、result.json 结构、进度帧 + 末行汇总、
    web 事实源零触碰。"""
    tmp, runs, inter, uploads, master = iso_env
    cfg_path = _write_config(tmp / 'cfg_run.json', master)
    inter_before = inter.read_bytes()

    rc = main([str(cfg_path), '--time', '2'])
    out = capsys.readouterr().out
    assert rc == 0
    assert '原面积口径新最优' in out                    # 进度帧口径
    last_line = out.strip().splitlines()[-1]
    assert 'real_density（原面积口径）' in last_line
    assert '用布长度' in last_line and '片数' in last_line and '耗时' in last_line
    assert str(runs.resolve()) in last_line             # 末行含 run_dir 完整路径

    # run_dir 命名 = 配置 stem（合法，无需清洗）+ 时间戳
    run_dirs = list(runs.iterdir())
    assert len(run_dirs) == 1
    rd = run_dirs[0]
    assert rd.name.startswith('cfg_run_')

    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert set(result) == {'config', 'commit', 'solve'}
    assert result['config']['master_dxf'] == str(master.resolve())
    assert result['config']['time'] == 2                # --time 覆盖后回显生效值
    assert result['config']['seeds'] == [0]
    assert result['commit']['n_pieces'] == _N_PIECES
    assert len(result['solve']) == 1
    s = result['solve'][0]
    for k in ('seed', 'width_mm', 'real_density', 'density_sparrow', 'elapsed'):
        assert k in s, k
    assert s['placed_items'] == _N_PIECES == s['n_items']

    # web 事实源零触碰（FR-5）
    assert inter.read_bytes() == inter_before
    assert list(uploads.iterdir()) == []


def test_main_name_override_and_clean(iso_env, capsys):
    """--name 覆盖 run_name；非法字符清洗（非法 → '_'）。"""
    tmp, runs, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg.json', master)
    rc = main([str(cfg_path), '--name', 'a<b>:b/c?d', '--time', '2', '--quiet'])
    assert rc == 0
    assert capsys.readouterr().out                     # quiet 仍有汇总
    (rd,) = list(runs.iterdir())
    assert rd.name.startswith('a_b__b_c_d_')


def test_main_quiet_suppresses_progress(iso_env, capsys):
    """--quiet：无进度帧/心跳，仍保留最终汇总。"""
    tmp, _, _, _, master = iso_env
    cfg_path = _write_config(tmp / 'cfg_q.json', master)
    rc = main([str(cfg_path), '--time', '2', '--quiet'])
    out = capsys.readouterr().out
    assert rc == 0
    assert '原面积口径新最优' not in out and '心跳' not in out
    assert 'real_density（原面积口径）' in out


def test_main_config_error_exit_1(iso_env, capsys):
    """配置失败 → 退出码 1（stderr 含 ConfigError 消息），不建 run_dir。"""
    tmp, runs, _, _, _ = iso_env
    rc = main([str(tmp / 'nope.json')])
    assert rc == 1
    assert '配置错误' in capsys.readouterr().err
    assert list(runs.iterdir()) == []


def test_main_commit_failure_exit_1(iso_env, capsys):
    """管线失败（master_dxf 配置校验通过但文件消失）→ 退出码 1。"""
    tmp, _, _, _, _ = iso_env
    ghost = tmp / 'ghost.dxf'
    ghost.write_bytes(b'not a dxf')
    cfg_path = _write_config(tmp / 'cfg_bad_master.json', ghost)
    rc = main([str(cfg_path)])
    assert rc == 1
    assert '管线失败' in capsys.readouterr().err


def test_clean_run_name():
    """run_name 清洗：Windows 非法字符 → '_'、去首尾空白/点、空回退 'run'。"""
    assert _clean_run_name('a<b>:b/c?d') == 'a_b__b_c_d'
    assert _clean_run_name('  spaced. ') == 'spaced'
    assert _clean_run_name('???') == '___'           # 全非法字符 → 下划线（合法目录名）
    assert _clean_run_name('正常名-1.2') == '正常名-1.2'


# ------------------------------------------------------- 分层（AC#4）


def test_layering_run_config_no_web_import():
    """run_config 全模块（含函数内）不 import web —— 只经 pipeline 间接复用。"""
    from materialsorting.cli import run_config as rc
    tree = ast.parse(Path(rc.__file__).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parts = [p for p in (node.module or '').split('.') if p]
            assert 'web' not in parts, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert 'web' not in alias.name.split('.'), alias.name


def test_layering_pipeline_web_solver_lazy_only():
    """pipeline 对 web 的依赖仅限 solve_pieces 函数内延迟 import（web.solver，
    纯求解封装）；模块级（tree.body）不 import web —— 导入冒烟零副作用的前提。"""
    from materialsorting.cli import pipeline as pl
    tree = ast.parse(Path(pl.__file__).read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert 'web' not in (node.module or '').split('.'), node.module
    lazy = [n for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.level == 2 and n.module == 'web.solver']
    assert len(lazy) == 1                              # solve_pieces 内唯一延迟 import


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
