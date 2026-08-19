"""US-002 ``cli/pipeline.commit_from_config`` 测试：独立 run_dir、镜像 web commit、零触碰 web 事实源。

合成「未录入名称」母版（与 ``test_commit_pipeline.py`` 同构，坐标带小数以暴露
rounding 位数差异）跑两条管线对拍：web ``_commit_to_nesting_sync``（monkeypatch
隔离到 tmp）vs CLI ``commit_from_config``（run_dir 同在 tmp）—— piece 条目必须
**逐字段一致**（含 rounding 位数），顶层唯一差异 = 省略 web 专属
``label_representatives``；web 事实源（paths.INTERMEDIATE / uploads）零写入。
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_REPO_ROOT = Path(__file__).resolve().parents[2]

from materialsorting import paths as paths_mod
from materialsorting.cli.config import NestRunConfig
from materialsorting.cli.pipeline import commit_from_config, new_run_dir
from materialsorting.nesting_bounds.load_pieces import PIECES_MANIFEST_NAME
from materialsorting.web import server as server_mod
from materialsorting.web.server import _commit_to_nesting_sync
from materialsorting.web.solver import load_pieces as solver_load_pieces

# 「未录入名称」block + 小数坐标（web/CLI 任一侧 rounding 位数不一致即对拍失败）。
_SYNTH_BLOCKS = [
    ('blk x.28', (0.12345, 0.6789, 400.123456, 700.987654)),
    ('blk x.29', (0.12345, 0.6789, 400.123456, 720.987654)),
    ('zz 9.28', (1.5, 2.25, 200.111111, 90.222222)),
    ('zz 9.29', (1.5, 2.25, 200.111111, 95.222222)),
    ('M55#2 a.28', (2.75, 3.125, 120.333333, 60.444444)),
    ('M55#2 a.29', (2.75, 3.125, 120.333333, 65.444444)),
]
_N_OUTLINES_SIZED = len(_SYNTH_BLOCKS)      # size!=None 轮廓数（= intermediate 条数）


def _make_master_dxf(path: Path) -> Path:
    """合成母版：6 片有码号 + 1 片无码号尾缀（size=None，commit 跳过）。"""
    doc = ezdxf.new('R12')
    for name, (x, y, w, h) in _SYNTH_BLOCKS:
        blk = doc.blocks.new(name=name)
        poly = blk.add_polyline2d(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
            dxfattribs={'layer': '1'})
        poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
        blk.add_line((x + 10, y + h / 2), (x + w - 10, y + h / 2),
                     dxfattribs={'layer': '7'})
    blk = doc.blocks.new(name='noname nosize')   # 无码号尾缀 -> size=None
    poly = blk.add_polyline2d([(0, 0), (80, 0), (80, 50), (0, 50)],
                              dxfattribs={'layer': '1'})
    poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
    doc.saveas(str(path))
    return path


@pytest.fixture
def iso_env(tmp_path, monkeypatch):
    """隔离环境：uploads / INTERMEDIATE / CONFIG_RUNS_DIR 全指到 tmp_path。"""
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    inter = tmp_path / 'web_intermediate.json'          # web 事实源哨兵（预置内容）
    inter.write_text('{"sentinel": true}', encoding='utf-8')
    runs = tmp_path / 'config_runs'
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', uploads)
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE', str(inter))
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(runs))
    master = _make_master_dxf(tmp_path / 'synthetic_master.dxf')
    return tmp_path, uploads, inter, runs, master


def _cfg(master, gate_mm=1980.0) -> NestRunConfig:
    """最小可用配置（commit 只消费 master_dxf / gate_mm，其余求解期参数缺省）。"""
    return NestRunConfig(master_dxf=Path(master), gate_mm=gate_mm)


def test_commit_writes_run_dir_artifacts(iso_env):
    """AC#1：run_dir/pieces/ 切片 + manifest + intermediate；条数 = size!=None 轮廓数。"""
    tmp, _, _, runs, master = iso_env
    run_dir = new_run_dir('smoke')
    summary = commit_from_config(_cfg(master), run_dir)

    assert Path(summary['run_dir']) == run_dir
    assert run_dir.parent == runs
    assert re.fullmatch(r'smoke_\d{8}-\d{6}', run_dir.name), run_dir.name
    assert summary['n_written_dxf'] == _N_OUTLINES_SIZED
    assert summary['n_pieces'] == _N_OUTLINES_SIZED
    assert summary['n_skipped'] == 1                     # 仅 size=None 片跳过
    assert 'size 解析为 None' in summary['skipped'][0]
    assert summary['sizes'] == [28, 29]
    assert summary['source'] == master.name

    # pieces/ 切片 DXF 数 + manifest 条目数 = size!=None 轮廓数
    pieces_dir = run_dir / 'pieces'
    dxf_files = [f for f in os.listdir(pieces_dir) if f.endswith('.dxf')]
    assert len(dxf_files) == _N_OUTLINES_SIZED
    manifest = json.loads((pieces_dir / PIECES_MANIFEST_NAME).read_text(encoding='utf-8'))
    assert len(manifest) == _N_OUTLINES_SIZED
    for item in manifest:
        assert set(item) == {'file', 'label', 'size'}
        assert item['file'] == f"{item['label']}_{item['size']}.dxf"
        assert (pieces_dir / item['file']).exists()

    # intermediate 落 run_dir（gate_mm 配置驱动），schema v2 无 ptype/side、无 .bak
    inter = run_dir / 'pieces_intermediate.json'
    doc = json.loads(inter.read_text(encoding='utf-8'))
    assert doc['gate_mm'] == 1980.0
    assert doc['n_pieces'] == _N_OUTLINES_SIZED == len(doc['pieces'])
    assert 'label_representatives' not in doc            # web 专属，CLI 省略
    for p in doc['pieces']:
        assert p['pid'] == f"{p['label']}_{p['size']}"
        assert 'ptype' not in p and 'side' not in p
    assert not list(run_dir.glob('*.bak'))
    assert summary['total_area_mm2'] == doc['total_area_mm2']


def test_gate_mm_from_config(iso_env):
    """gate_mm 写 cfg.gate_mm（配置驱动，与该 run 密度分母同源；web 固定 1980）。"""
    tmp, _, _, _, master = iso_env
    run_dir = tmp / 'run_gate1500'
    commit_from_config(_cfg(master, gate_mm=1500.0), run_dir)
    doc = json.loads((run_dir / 'pieces_intermediate.json').read_text(encoding='utf-8'))
    assert doc['gate_mm'] == 1500.0


def test_load_back_via_web_solver(iso_env):
    """AC#2：web.solver.load_pieces 读回成功，pieces 数与 manifest 一致（schema v2 自证）。"""
    tmp, _, _, _, master = iso_env
    run_dir = tmp / 'run_lb'
    commit_from_config(_cfg(master), run_dir)
    doc, gate, pieces = solver_load_pieces(str(run_dir / 'pieces_intermediate.json'))
    manifest = json.loads((run_dir / 'pieces' / PIECES_MANIFEST_NAME).read_text(encoding='utf-8'))
    assert len(pieces) == len(manifest) == _N_OUTLINES_SIZED
    assert gate == 1980.0
    assert {p['pid'] for p in pieces} == {f"{m['label']}_{m['size']}" for m in manifest}


def test_web_fact_sources_untouched(iso_env):
    """AC#3：CLI commit 只写 run_dir —— INTERMEDIATE 哨兵内容/mtime 不变、无 .bak、
    uploads 无新条目（结构隔离 + 行为回归双保险）。"""
    tmp, uploads, inter, runs, master = iso_env
    before = inter.read_bytes()
    before_mtime = inter.stat().st_mtime_ns
    uploads_before = {p.relative_to(uploads).as_posix() for p in uploads.rglob('*')}

    commit_from_config(_cfg(master), runs / 'iso_run')

    assert inter.read_bytes() == before
    assert inter.stat().st_mtime_ns == before_mtime
    assert not (tmp / 'web_intermediate.bak').exists()
    assert {p.relative_to(uploads).as_posix() for p in uploads.rglob('*')} == uploads_before
    # run_dir 外（config_runs 直下）无散落文件
    assert [p.name for p in runs.iterdir()] == ['iso_run']


def test_cli_matches_web_commit_field_by_field(iso_env):
    """AC#4 对拍（合成母版）：pid 集合 / total_area_mm2 / 逐 pid piece 条目全等
    （小数坐标暴露 rounding 位数差异）；顶层唯一差异 = label_representatives。"""
    tmp, _, web_inter, runs, master = iso_env
    web_result = _commit_to_nesting_sync('deadbeef', str(master), master.name)
    run_dir = runs / 'duel'
    cli_result = commit_from_config(_cfg(master), run_dir)

    web_doc = json.loads(web_inter.read_text(encoding='utf-8'))
    cli_doc = json.loads((run_dir / 'pieces_intermediate.json').read_text(encoding='utf-8'))

    assert web_result['n_pieces'] == cli_result['n_pieces'] == _N_OUTLINES_SIZED
    wp = {p['pid']: p for p in web_doc['pieces']}
    cp = {p['pid']: p for p in cli_doc['pieces']}
    assert set(wp) == set(cp)
    assert web_doc['total_area_mm2'] == cli_doc['total_area_mm2']
    for pid in wp:
        assert wp[pid] == cp[pid], f'piece 字段不一致 @ {pid}'
    # 顶层：source/gate_mm/n_pieces/total_area_mm2 同；label_representatives 仅 web 有
    assert 'label_representatives' in web_doc
    assert 'label_representatives' not in cli_doc
    for k in ('source', 'gate_mm', 'n_pieces', 'total_area_mm2'):
        assert web_doc[k] == cli_doc[k], k


def test_new_run_dir_timestamped_and_kept(iso_env):
    """new_run_dir：时间戳目录，重跑不覆盖（同秒同名 exist_ok 幂等返回同一目录）。"""
    _, _, _, runs, _ = iso_env
    d1 = new_run_dir('myrun')
    assert d1.parent == runs and d1.is_dir()
    assert re.fullmatch(r'myrun_\d{8}-\d{6}', d1.name)
    d2 = new_run_dir('myrun')
    assert d2 == d1 or (d2.is_dir() and d1.is_dir())


def test_layering_no_web_server_import():
    """AC#5 分层：pipeline 全模块（任意层级 import）不得 import web.server；
    模块级兄弟包 import 仅允许向下（dxf_parser/nesting_bounds/nesting_engine/paths）。"""
    import materialsorting.cli.pipeline as pl
    tree = ast.parse(Path(pl.__file__).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parts = [p for p in (node.module or '').split('.') if p]
            assert 'server' not in parts, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert 'server' not in alias.name.split('.'), alias.name
    allowed = {'dxf_parser', 'nesting_bounds', 'nesting_engine', 'paths'}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            assert (node.module or '').split('.')[0] in allowed, node.module


def test_run_as_module_no_side_effects():
    """AC#5 冒烟：python -m materialsorting.cli.pipeline 退出码 0、零输出。"""
    env = {**os.environ, 'PYTHONPATH': str(_SRC)}
    r = subprocess.run([sys.executable, '-m', 'materialsorting.cli.pipeline'],
                       capture_output=True, env=env, cwd=str(_REPO_ROOT), timeout=120)
    assert r.returncode == 0
    assert r.stdout == b''
    assert r.stderr == b''


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
