"""US-001 commit 管线 v2 测试：label 先行、零丢片、manifest 驱动、AC#5 对齐。

合成「未录入名称」母版（block 名为空格/数字/新款代号，无任何片型语义）走
``_commit_to_nesting_sync`` 全管线：现状 v1 会因无 GROUP_NAMES 映射直接丢片，v2 必须
0 丢片、全片有 g 码、intermediate 条数 = 母版 size≠None 轮廓数（每轮廓恰一条，
无镜像合成）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.nesting_bounds.load_pieces import (
    load_nest_pieces, PIECES_MANIFEST_NAME)
from materialsorting.web import server as server_mod
from materialsorting.web.server import _build_parse_payload, _commit_to_nesting_sync
from materialsorting.web.solver import load_pieces as solver_load_pieces

_GCODE_RE = re.compile(r'^g\d{2,}$')

# 「未录入名称」block（名 = 空格/数字/新款代号；M55#2 a 剥码号后无编号尾缀）。
# 每个 block 模板在 28/29 两码各出一片（与真实母版同构：组集跨码一致 → T4 跨码同号）。
_SYNTH_BLOCKS = [
    ('blk x.28', (0, 0, 400, 700)),
    ('blk x.29', (0, 0, 400, 720)),
    ('zz 9.28', (0, 0, 200, 90)),
    ('zz 9.29', (0, 0, 200, 95)),
    ('M55#2 a.28', (0, 0, 120, 60)),
    ('M55#2 a.29', (0, 0, 120, 65)),
]
_N_OUTLINES_SIZED = len(_SYNTH_BLOCKS)      # size≠None 轮廓数（= intermediate 条数）


def _make_master_dxf(path: Path) -> Path:
    """合成母版：5 片有码号 + 1 片无码号尾缀（size=None，commit 跳过/parse 入 null 组）。"""
    doc = ezdxf.new('R12')
    for name, (x, y, w, h) in _SYNTH_BLOCKS:
        blk = doc.blocks.new(name=name)
        poly = blk.add_polyline2d(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
            dxfattribs={'layer': '1'})
        poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
        blk.add_line((x + 10, y + h / 2), (x + w - 10, y + h / 2),
                     dxfattribs={'layer': '7'})
    blk = doc.blocks.new(name='noname nosize')   # 无码号尾缀 → size=None
    poly = blk.add_polyline2d([(0, 0), (80, 0), (80, 50), (0, 50)],
                              dxfattribs={'layer': '1'})
    poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
    doc.saveas(str(path))
    return path


@pytest.fixture
def commit_env(tmp_path, monkeypatch):
    """隔离环境：UPLOADS_DIR 与 paths.INTERMEDIATE 指到 tmp_path。"""
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', uploads)
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE', str(tmp_path / 'pieces_intermediate.json'))
    master = _make_master_dxf(tmp_path / 'synthetic_master.dxf')
    return tmp_path, uploads, master


def _run_commit(env, doc_id='deadbeef'):
    tmp_path, uploads, master = env
    return _commit_to_nesting_sync(doc_id, str(master), master.name)


def test_commit_unnamed_master_no_drop_all_coded(commit_env):
    """合成无名 block 母版 commit：0 丢片、100% 有 g 码、每轮廓恰一条（无镜像合成）。"""
    result = _run_commit(commit_env)
    # 5 片 size≠None 全写出（v1 现状会因无 GROUP_NAMES 映射全部 skip 丢片）
    assert result['n_written_dxf'] == _N_OUTLINES_SIZED
    assert result['n_pieces'] == _N_OUTLINES_SIZED
    assert result['n_skipped'] == 1            # 仅 size=None 片跳过
    assert 'size 解析为 None' in result['skipped'][0]
    assert result['sizes'] == [28, 29]

    doc = json.loads(Path(paths_mod.INTERMEDIATE).read_text(encoding='utf-8'))
    pieces = doc['pieces']
    assert len(pieces) == _N_OUTLINES_SIZED    # intermediate 条数 = 母版轮廓数
    for p in pieces:
        assert _GCODE_RE.match(p['label']), p        # 100% 有 g 码
        assert p['pid'] == f"{p['label']}_{p['size']}"
        assert 'ptype' not in p and 'side' not in p  # schema v2 无 ptype/side
    # 顶层 label_representatives 键 = g 码
    reps = doc['label_representatives']
    assert set(reps) == {'g01', 'g02', 'g03'}
    assert 'ptype_representatives' not in doc
    # 跨码同号（T4）：同一 block 模板（blk x / zz 9）在 28/29 同码
    label_by = {(p['label'], p['size']) for p in pieces}
    assert ('g02', 28) in label_by and ('g02', 29) in label_by
    assert ('g03', 28) in label_by and ('g03', 29) in label_by


def test_commit_writes_manifest_and_label_dxf(commit_env):
    """切片目录 = {label}_{size}.dxf + pieces_manifest.json sidecar（加载驱动源）。"""
    _run_commit(commit_env, doc_id='cafe01')
    pieces_dir = Path(server_mod.UPLOADS_DIR) / 'cafe01_pieces'
    manifest_path = pieces_dir / PIECES_MANIFEST_NAME
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert len(manifest) == _N_OUTLINES_SIZED
    for item in manifest:
        assert set(item) == {'file', 'label', 'size'}
        assert (pieces_dir / item['file']).exists()
        assert item['file'] == f"{item['label']}_{item['size']}.dxf"
    # manifest 驱动加载：load_nest_pieces 直接可跑，pid = {label}_{size}
    nest = load_nest_pieces(str(pieces_dir))
    assert len(nest) == _N_OUTLINES_SIZED
    assert all(n.pid == f'{n.label}_{n.size}' for n in nest)


def test_commit_parse_label_alignment_ac5(commit_env):
    """AC#5：parse 响应与 commit intermediate 按码逐片 label 对齐（面积互证）。"""
    from materialsorting.dxf_parser.collect import collect_pieces_with_details
    _, _, master = commit_env
    raw = collect_pieces_with_details(Path(master))
    payload = _build_parse_payload('doc1', master.name, raw)

    # 响应契约 v2：pieces 无 name/ptype/paired，仅 label + 5 层
    for size_group in payload['sizes']:
        for piece in size_group['pieces']:
            assert set(piece) == {'label', 'polygon', 'internal_lines',
                                  'notches', 'net_polygon', 'grain_line'}
            assert _GCODE_RE.match(piece['label'])

    doc = json.loads(Path(paths_mod.INTERMEDIATE).read_text(encoding='utf-8')) \
        if Path(paths_mod.INTERMEDIATE).exists() else None
    assert doc is None   # parse 不落盘，先 commit
    _run_commit(commit_env)
    doc = json.loads(Path(paths_mod.INTERMEDIATE).read_text(encoding='utf-8'))

    # 逐码：label 列表一致（顺序 = assign_codes 同源同序）
    parse_by_size = {g['size']: [p['label'] for p in g['pieces']]
                     for g in payload['sizes']}
    inter_by_size = {}
    for p in doc['pieces']:
        inter_by_size.setdefault(p['size'], []).append(p['label'])
    # null 码组（size=None）只在 parse 出现，commit 跳过 —— 先剔再比较
    assert parse_by_size.pop(None) == ['g01']
    assert parse_by_size == inter_by_size

    # 几何互证：同 (size, label) 面积一致（布纹对齐旋转不改面积）
    parse_area = {}
    for g in payload['sizes']:
        if g['size'] is None:
            continue
        for p in g['pieces']:
            xs = [pt[0] for pt in p['polygon']]
            ys = [pt[1] for pt in p['polygon']]
            parse_area[(p['label'], g['size'])] = (max(xs) - min(xs)) * (max(ys) - min(ys))
    for p in doc['pieces']:
        key = (p['label'], p['size'])
        assert key in parse_area
        assert p['area_mm2'] == pytest.approx(parse_area[key], rel=1e-6), key


def test_commit_idempotent(commit_env):
    """同 doc_id 重跑 commit：切片目录先清空重写，intermediate 结果一致。"""
    r1 = _run_commit(commit_env, doc_id='retry01')
    r2 = _run_commit(commit_env, doc_id='retry01')
    assert r1['n_pieces'] == r2['n_pieces'] == _N_OUTLINES_SIZED
    assert r1['total_area_mm2'] == r2['total_area_mm2']


def test_load_nest_pieces_old_dir_errors(tmp_path):
    """旧版切片目录（无 pieces_manifest.json）明确报错「请重新 commit」。"""
    old_dir = tmp_path / 'old_pieces'
    old_dir.mkdir()
    (old_dir / '前片_28_L.dxf').write_bytes(b'')   # v1 风格文件名，无 sidecar
    with pytest.raises(RuntimeError, match='请重新 commit'):
        load_nest_pieces(str(old_dir))


def test_solver_load_pieces_rejects_v1(tmp_path):
    """旧版 intermediate（schema v1，片含 ptype）明确报错，不静默双读。"""
    v1 = {
        'source': 'old.dxf', 'gate_mm': 1980.0, 'n_pieces': 1,
        'total_area_mm2': 1.0,
        'pieces': [{'pid': '前片_28_L', 'ptype': '前片', 'size': 28, 'side': 'L',
                    'label': 'g01', 'polygon': [[0, 0], [1, 0], [1, 1]],
                    'area_mm2': 1.0}],
        'ptype_representatives': {},
    }
    p = tmp_path / 'v1_intermediate.json'
    p.write_text(json.dumps(v1, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(RuntimeError, match='请重新 commit'):
        solver_load_pieces(str(p))


def test_solver_load_pieces_accepts_v2(tmp_path):
    """v2 intermediate（label-only）正常加载。"""
    v2 = {
        'source': 'new.dxf', 'gate_mm': 1980.0, 'n_pieces': 1,
        'total_area_mm2': 1.0,
        'pieces': [{'pid': 'g01_28', 'label': 'g01', 'size': 28,
                    'polygon': [[0, 0], [1, 0], [1, 1]], 'area_mm2': 1.0}],
        'label_representatives': {},
    }
    p = tmp_path / 'v2_intermediate.json'
    p.write_text(json.dumps(v2, ensure_ascii=False), encoding='utf-8')
    doc, gate, pieces = solver_load_pieces(str(p))
    assert gate == 1980.0 and len(pieces) == 1 and pieces[0]['pid'] == 'g01_28'
