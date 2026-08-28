"""US-007（PC-007）``cli/lns.py`` LNS 波段重排核心模块单测。

覆盖 PRD 验收：
  - 波段切分（slab 几何 / 局部密度公式 / 空段密度 0 / pid 组整组归段不拆分）；
  - 子实例同口径（build_instance 的 erode/tol/orientations/strip_height 与母实例
    一致，g 码 per_type 命中）；
  - 带人工空洞的 fixture：一轮后总宽缩短 ≥ 空洞宽 50%，全片在场（数量 = Σdemand，
    demand>1 副本数不变）；空段（纯空洞）splice 让位；
  - 拒绝路径：子解不优于原段 → 输入布局逐字节不变；
  - 预算耗尽 / 重叠护栏 / y 越界回退；
  - CLI 端到端（result_lns.json + lns_compare.svg + stdout 汇总）、--help 冒烟、
    分层纯度（模块级不 import web）；
  - 真实 sparrow 子求解冒烟（多进程链路）。
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from materialsorting.cli import lns
from materialsorting.nesting_bounds.load_pieces import GATE_MM

# ------------------------------------------------------------ fixture 基元


def _rect(pid, label, size, w, h):
    return {
        'pid': pid, 'label': label, 'size': size,
        'polygon': [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]],
        'bbox': [0.0, 0.0, float(w), float(h)],
        'area_mm2': round(w * h, 1), 'n_verts': 4, 'allowed_angles': [0, 180],
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
    }


def _pieces():
    return [
        _rect('g01_30', 'g01', 30, 800, 500),   # A
        _rect('g02_30', 'g02', 30, 800, 500),   # B
        _rect('g03_30', 'g03', 30, 700, 500),   # C
        _rect('g04_30', 'g04', 30, 500, 400),   # D（demand=2 两副本）
    ]


def _at(pid, x, y=0.0):
    return {'id': pid, 'rotation': 0.0, 'translation': [float(x), float(y)]}


def _layout():
    """人工空洞 fixture：A[0,800) + 600mm 空洞 + B/D 叠层 + C，总宽 3300。"""
    return [
        _at('g01_30', 0, 0),        # A  [0,800)×[0,500)
        _at('g02_30', 1400, 0),     # B  [1400,2200)×[0,500)
        _at('g04_30', 1400, 600),   # D1 [1400,1900)×[600,1000)
        _at('g04_30', 1900, 600),   # D2 [1900,2400)×[600,1000)
        _at('g03_30', 2600, 0),     # C  [2600,3300)×[0,500)
    ]


def _by_id(pieces):
    return {p['pid']: p for p in pieces}


# ------------------------------------------------------------ fake 子求解


def _column_packer(pieces_subset, gate_mm, params, limit=None):
    """确定性「好」解：副本竖着摞在 x=0（超出 limit 换列）—— span = 最宽列。"""
    limit = GATE_MM if limit is None else float(limit)
    qty = params.get('quantities') or {}
    placed, x, y, colw = [], 0.0, 0.0, 0.0
    for p in pieces_subset:
        sk = 'null' if p['size'] is None else str(p['size'])
        n = int((qty.get(p.get('label')) or {}).get(sk, 1))
        w, h = p['bbox'][2], p['bbox'][3]
        for _ in range(n):
            if y + h > limit:
                x += colw
                y = 0.0
                colw = 0.0
            placed.append({'id': p['pid'], 'rotation': 0.0,
                           'translation': [x, y]})
            y += h
            colw = max(colw, w)
    return {'placed_items': placed, 'width_mm': x + colw}


def _row_packer(pieces_subset, gate_mm, params):
    """确定性「差」解：副本横排 y=0 —— span = Σ宽（几乎总不优于原段）。"""
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


class _CountingSolve:
    """包装 fake solve 计调用次数（断言预算耗尽路径零调用等）。"""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def __call__(self, pieces_subset, gate_mm, params):
        self.calls += 1
        return self.inner(pieces_subset, gate_mm, params)


# ------------------------------------------------------------ 波段切分


def test_split_bands_slabs_and_density():
    bands = lns.split_bands(_layout(), _by_id(_pieces()), 2000.0)
    assert len(bands) == 2
    b0, b1 = bands
    assert b0['x_start'] == 0.0 and b0['x_end'] == 2000.0 and b0['slab_width'] == 2000.0
    assert b1['x_start'] == 2000.0 and b1['x_end'] == 3300.0 and b1['slab_width'] == 1300.0
    assert b0['positions'] == [0, 1, 2, 3] and b1['positions'] == [4]
    assert b0['m'] == 0.0 and b0['M'] == 2400.0 and b0['span'] == 2400.0
    assert b1['m'] == 2600.0 and b1['M'] == 3300.0 and b1['span'] == 700.0
    # 局部密度 = 段内片面积和 /（段宽 × 默认门幅）
    assert b0['density'] == pytest.approx(1_200_000 / (2000.0 * GATE_MM))
    assert b1['density'] == pytest.approx(350_000 / (1300.0 * GATE_MM))


def test_split_bands_pid_group_no_split():
    """demand>1 的 pid 全部副本整段进波段，禁止拆分（按首副本中心归段）。"""
    bands = lns.split_bands(_layout(), _by_id(_pieces()), 2000.0)
    b0, b1 = bands
    assert set(b0['pids']) == {'g01_30', 'g02_30', 'g04_30'}
    assert b0['pids'] == ['g01_30', 'g02_30', 'g04_30']   # 首副本出现序
    assert b1['pids'] == ['g03_30']
    # g04 两副本（positions 2、3）都归 B0
    assert 2 in b0['positions'] and 3 in b0['positions']


def test_split_bands_empty_band_density_zero():
    pieces = [_rect('g01_30', 'g01', 30, 800, 500), _rect('g03_30', 'g03', 30, 700, 500)]
    layout = [_at('g01_30', 0, 0), _at('g03_30', 3000, 0)]
    bands = lns.split_bands(layout, _by_id(pieces), 1000.0)
    assert len(bands) == 4
    assert bands[0]['positions'] == [0] and bands[0]['pids'] == ['g01_30']
    assert bands[1]['positions'] == [] and bands[1]['pids'] == []
    assert bands[1]['density'] == 0.0
    assert bands[1]['m'] == 1000.0 and bands[1]['M'] == 2000.0
    assert bands[3]['positions'] == [1]


def test_split_bands_unknown_pid_raises():
    with pytest.raises(lns.LnsError):
        lns.split_bands([_at('nope_30', 0, 0)], _by_id(_pieces()), 2000.0)


# ------------------------------------------------------------ 子实例参数


def test_band_solve_params_from_copy_counts():
    bands = lns.split_bands(_layout(), _by_id(_pieces()), 2000.0)
    params = lns.band_solve_params(bands[0], _layout(), _by_id(_pieces()),
                                   per_type={'g01': {'d': 2.0, 'tol': 5.0}},
                                   sizes=[30, 32], time_budget=7, seed=42)
    assert params['time_budget'] == 7
    assert params['seed'] == 42
    assert params['sizes'] == [30, 32]
    assert params['per_type'] == {'g01': {'d': 2.0, 'tol': 5.0}}
    # quantities 从段内实际副本数推导：Σ == 段内位置数（4），g04 = 2 副本
    assert params['quantities'] == {'g01': {'30': 1}, 'g02': {'30': 1},
                                    'g04': {'30': 2}}
    assert sum(int(n) for m in params['quantities'].values()
               for n in m.values()) == len(bands[0]['positions'])


def test_band_solve_params_missing_label_returns_none():
    pieces = _pieces() + [_rect('raw_30', None, 30, 300, 200)]
    layout = _layout() + [_at('raw_30', 100, 1400)]
    bands = lns.split_bands(layout, _by_id(pieces), 2000.0)
    assert bands[0]['pids'][-1] == 'raw_30'
    assert lns.band_solve_params(bands[0], layout, _by_id(pieces)) is None


def test_sub_instance_same_caliber():
    """同口径：erode/tol/orientations/strip_height 钳制与母实例一致，g 码命中。"""
    from shapely.geometry import Polygon

    from materialsorting.web.solver import build_instance, discretize_orientations

    pieces = [_rect('g01_30', 'g01', 30, 600, 400),
              _rect('g02_30', 'g02', 30, 500, 300)]
    per_type = {'g01': {'d': 2.0, 'tol': 5.0}, 'g02': {'d': 0.0, 'tol': 0.0}}
    m_inst, _cfg, m_meta, m_area, m_eroded = build_instance(
        pieces, 1980.0, time_budget=2, seed=1, sizes=[30], per_type=per_type,
        quantities={'g01': {'30': 2}, 'g02': {'30': 1}})
    s_inst, _cfg2, s_meta, s_area, s_eroded = build_instance(
        pieces[:1], 1980.0, time_budget=2, seed=1, sizes=[30], per_type=per_type,
        quantities={'g01': {'30': 2}})

    # strip_height = 输入门幅原样（2026-08-28 起无 1910 钳制），母子同口径
    assert m_inst.strip_height == pytest.approx(1980.0)
    assert s_inst.strip_height == pytest.approx(1980.0)
    assert s_inst.strip_height == pytest.approx(m_inst.strip_height)

    m_items = {it.id: it for it in m_inst.items}
    s_items = {it.id: it for it in s_inst.items}
    assert set(m_items) == {'g01_30', 'g02_30'} and set(s_items) == {'g01_30'}
    # erode 同口径：g01 d=2 → 母/子形完全一致且确有腐蚀；g02 d=0 → 原面积
    assert list(s_items['g01_30'].shape) == list(m_items['g01_30'].shape)
    # 腐蚀后面积 ≈ (w-2d)(h-2d)（buffer 圆角略小，1% 容差）
    assert Polygon(m_items['g01_30'].shape).area == pytest.approx(600 * 400 - 2 * (600 + 400), rel=0.01)
    assert Polygon(m_items['g02_30'].shape).area == pytest.approx(500 * 300)
    assert m_eroded == s_eroded == 1
    assert m_area == pytest.approx(600 * 400 * 2 + 500 * 300)
    assert s_area == pytest.approx(600 * 400 * 2)
    # orientations 同 tol 离散（180 对称 + 5° 网格），母子一致
    assert list(s_items['g01_30'].allowed_orientations) == list(m_items['g01_30'].allowed_orientations)
    assert list(s_items['g01_30'].allowed_orientations) == list(discretize_orientations(5.0))
    # demand 透传：demand>1 副本量母子一致
    assert s_items['g01_30'].demand == m_items['g01_30'].demand == 2
    assert s_meta['g01_30']['demand'] == m_meta['g01_30']['demand'] == 2


# ------------------------------------------------------------ run_lns 核心循环


def test_hole_fixture_one_round_recovers():
    """人工空洞 fixture：一轮后总宽缩短 ≥ 空洞宽 50%，全片在场。"""
    pieces, layout = _pieces(), _layout()
    out = lns.run_lns(layout, pieces, 1980.0, band_width=2000.0,
                      time_budget=30.0, rounds=3, solve=_column_packer)
    assert out['improved'] is True
    assert out['stop_reason'] == 'no_band_improvable'
    shrink = out['before']['width_mm'] - out['after']['width_mm']
    assert shrink >= 600 * 0.5                       # 空洞 600mm 的 ≥50%
    # 全片在场：数量 = Σdemand（5），demand>1 的 g04 副本数不变（2）
    assert len(out['placed_items']) == 5
    assert sum(1 for it in out['placed_items'] if it['id'] == 'g04_30') == 2
    # 前后口径：原面积密度提升、总宽缩短
    assert out['after']['width_mm'] < out['before']['width_mm']
    assert out['after']['density'] > out['before']['density']
    assert out['after']['n_placed'] == out['before']['n_placed'] == 5
    # 复检双通过
    assert out['recheck']['ok'] is True
    assert out['recheck']['issues'] == []
    assert out['recheck']['y_violations'] == 0
    assert out['recheck']['reverted'] is False
    # 至少一轮成功明细
    acc = [d for d in out['rounds_detail'] if d['accepted']]
    assert acc and all(d['span_new'] < d['span_old'] for d in acc)


def test_empty_band_spliced_without_solve():
    """纯空洞段：无需子求解直接 splice，后续波段左移。"""
    pieces = [_rect('g01_30', 'g01', 30, 800, 500), _rect('g03_30', 'g03', 30, 700, 500)]
    layout = [_at('g01_30', 0, 0), _at('g03_30', 3000, 0)]   # 空洞 [800,3000)
    solve = _CountingSolve(_row_packer)                       # 差解必被拒
    out = lns.run_lns(layout, pieces, 1980.0, band_width=1000.0,
                      time_budget=30.0, rounds=5, solve=solve)
    # 两个 1000mm 空段各 splice 一次：3700 → 1700（末轮两实段差解被拒）
    assert out['after']['width_mm'] == pytest.approx(1700.0)
    assert out['improved'] is True
    assert len(out['placed_items']) == 2
    assert solve.calls == 2                                    # 仅第 3 轮两实段各试一次
    splice = [d for d in out['rounds_detail'] if d['accepted'] and 'splice' in d['note']]
    assert len(splice) == 2


def test_reject_path_byte_identical():
    """拒绝路径：子解不优于原段 → 输入布局逐字节不变。"""
    pieces, layout = _pieces(), _layout()
    snapshot = json.dumps(layout, ensure_ascii=False)
    out = lns.run_lns(layout, pieces, 1980.0, band_width=2000.0,
                      time_budget=30.0, rounds=2, solve=_row_packer)
    assert out['improved'] is False
    assert out['stop_reason'] == 'no_band_improvable'
    assert json.dumps(out['placed_items'], ensure_ascii=False) == snapshot
    assert out['after']['width_mm'] == out['before']['width_mm']
    rej = [d for d in out['rounds_detail'] if not d['accepted']]
    assert rej


def test_budget_exhaustion_skips_solve():
    pieces, layout = _pieces(), _layout()
    snapshot = json.dumps(layout, ensure_ascii=False)
    solve = _CountingSolve(_column_packer)
    out = lns.run_lns(layout, pieces, 1980.0, band_width=2000.0,
                      time_budget=0.2, rounds=5, solve=solve)
    assert out['stop_reason'] == 'budget_exhausted'
    assert solve.calls == 0
    assert out['improved'] is False
    assert json.dumps(out['placed_items'], ensure_ascii=False) == snapshot


def test_y_overflow_reverts_to_input():
    """y 越界（> 输入门幅 1980）→ 复检失败回退，输出保持输入。"""
    pieces = [_rect('g01_30', 'g01', 30, 400, 500)]
    layout = [_at('g01_30', 0, 0), _at('g01_30', 600, 0), _at('g01_30', 1200, 0),
              _at('g01_30', 1800, 0), _at('g01_30', 2400, 0)]
    snapshot = json.dumps(layout, ensure_ascii=False)

    def tall_packer(pieces_subset, gate_mm, params):
        # 5 副本竖摞不换列：顶部 2500mm 越界（> gate 1980 + 容差），但 span 400
        # 极优 → 会先被接受再复检回退
        return {'placed_items': [{'id': 'g01_30', 'rotation': 0.0,
                                  'translation': [0.0, float(i * 500)]}
                                 for i in range(5)],
                'width_mm': 400.0}

    out = lns.run_lns(layout, pieces, 1980.0, band_width=5000.0,
                      time_budget=30.0, rounds=2, solve=tall_packer)
    assert out['improved'] is False
    # 初检抓到 y 越界 → reverted=True；回退后交付布局复检通过（如实在案）
    assert out['recheck']['reverted'] is True
    assert out['recheck']['ok'] is True
    assert out['after']['width_mm'] == out['before']['width_mm']
    assert json.dumps(out['placed_items'], ensure_ascii=False) == snapshot


def test_overlap_guard_blocks_new_collision():
    """跨组重叠护栏：新段解把片压进后续波段既占区 → 拒绝保持原布局。"""
    pieces = [_rect('g01_30', 'g01', 30, 1800, 300),   # A2 宽片
              _rect('g02_30', 'g02', 30, 100, 100),    # S 小片
              _rect('g03_30', 'g03', 30, 1000, 300)]   # F 后续段片
    layout = [_at('g01_30', 0, 0), _at('g02_30', 1900, 0), _at('g03_30', 1500, 300)]

    def crafted(pieces_subset, gate_mm, params):
        # 把 S 塞进 (1600,300) —— 与 F[1500,2500)×[300,600) 完全重叠
        return {'placed_items': [{'id': 'g01_30', 'rotation': 0.0,
                                  'translation': [0.0, 0.0]},
                                 {'id': 'g02_30', 'rotation': 0.0,
                                  'translation': [1600.0, 300.0]}],
                'width_mm': 1800.0}

    snapshot = json.dumps(layout, ensure_ascii=False)
    out = lns.run_lns(layout, pieces, 1980.0, band_width=2000.0,
                      time_budget=30.0, rounds=1, solve=crafted)
    assert out['improved'] is False
    assert json.dumps(out['placed_items'], ensure_ascii=False) == snapshot
    notes = [d.get('note', '') for d in out['rounds_detail']]
    assert any('重叠' in n for n in notes)


def test_run_lns_unknown_pid_and_band_width_default():
    pieces, layout = _pieces(), _layout()
    out = lns.run_lns(layout, pieces, 1980.0,
                      time_budget=30.0, rounds=1, solve=_row_packer)
    assert out['band_width_mm'] == pytest.approx(1.5 * GATE_MM)
    with pytest.raises(lns.LnsError):
        lns.run_lns([_at('nope_30', 0, 0)], pieces, 1980.0)


# ------------------------------------------------------------ CLI 端到端


def _make_run_dir(tmp_path, pieces, placed, *, gate=1980.0, seed=3):
    run_dir = tmp_path / 'run_20260819_120000'
    run_dir.mkdir(parents=True)
    inter = {'source': 'test.dxf', 'gate_mm': gate, 'pieces': pieces}
    (run_dir / 'pieces_intermediate.json').write_text(
        json.dumps(inter, ensure_ascii=False), encoding='utf-8')
    result = {'config': {'per_type': None,
                         'sizes': sorted({p['size'] for p in pieces}), 'time': 5},
              'best': None,
              'portfolio': {'incumbent': {'density': 0.1, 'width_mm': 3300.0,
                                          'seed': seed, 'frame_index': 0,
                                          'elapsed': 1.0,
                                          'placed_items': placed}}}
    (run_dir / 'result.json').write_text(
        json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return run_dir


def test_cli_end_to_end_fake(tmp_path, capsys, monkeypatch):
    run_dir = _make_run_dir(tmp_path, _pieces(), _layout())
    monkeypatch.setattr(lns, '_solve_band', _column_packer)
    rc = lns.main(['--run-dir', str(run_dir), '--time', '30', '--rounds', '3',
                   '--band-width', '2000'])
    assert rc == 0
    out = json.loads((run_dir / 'result_lns.json').read_text(encoding='utf-8'))
    assert out['source']['run_dir'].endswith('run_20260819_120000')
    assert out['source']['incumbent_seed'] == 3
    assert out['source']['config_echo']['sizes'] == [30]
    assert out['band_width_mm'] == 2000.0
    assert out['improved'] is True
    assert out['after']['width_mm'] < out['before']['width_mm']
    assert len(out['placed_items']) == 5
    assert out['recheck']['ok'] is True
    svg = (run_dir / 'lns_compare.svg').read_text(encoding='utf-8')
    assert svg.count('scale(1,-1)') == 2          # 双面板翻转组
    assert 'LNS 前' in svg and 'LNS 后' in svg and '尺码图例' in svg   # 图例=尺码维度（2026-08-20 换键）
    assert '>30</text>' in svg                                       # 图例条目是码号（非 g 码）
    stdout = capsys.readouterr().out
    assert '[LNS] before:' in stdout and 'improved=True' in stdout
    assert 'result_lns.json' in stdout


def test_cli_missing_inputs_exit_1(tmp_path, capsys):
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert lns.main(['--run-dir', str(empty)]) == 1
    assert 'result.json' in capsys.readouterr().err
    only_result = tmp_path / 'only_result'
    only_result.mkdir()
    (only_result / 'result.json').write_text('{}', encoding='utf-8')
    assert lns.main(['--run-dir', str(only_result)]) == 1
    assert 'pieces_intermediate.json' in capsys.readouterr().err
    # result.json 无 incumbent/best 布局
    run_dir = _make_run_dir(tmp_path / 'r2', _pieces(), _layout())
    doc = json.loads((run_dir / 'result.json').read_text(encoding='utf-8'))
    doc['portfolio']['incumbent']['placed_items'] = []
    (run_dir / 'result.json').write_text(
        json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    assert lns.main(['--run-dir', str(run_dir)]) == 1
    assert 'incumbent' in capsys.readouterr().err


def test_cli_bad_flags_exit_1(tmp_path, capsys):
    run_dir = _make_run_dir(tmp_path, _pieces(), _layout())
    assert lns.main(['--run-dir', str(run_dir), '--time', '0']) == 1
    assert 'time' in capsys.readouterr().err
    assert lns.main(['--run-dir', str(run_dir), '--rounds', '0']) == 1
    assert 'rounds' in capsys.readouterr().err
    assert lns.main(['--run-dir', str(run_dir), '--band-width', '-5']) == 1
    assert 'band-width' in capsys.readouterr().err


def test_cli_help_smoke():
    r = subprocess.run([sys.executable, '-m', 'materialsorting.cli.lns', '--help'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120)
    assert r.returncode == 0
    assert '--run-dir' in r.stdout and '--band-width' in r.stdout


def test_module_layering_purity():
    """分层未反向：lns.py 模块级 import 只向下（cli ← nesting_bounds/engine）。"""
    src = Path(lns.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'argparse', 'json', 'math', 'sys', 'time', 'pathlib', 'types',
               '__future__', 'materialsorting',
               'nesting_bounds', 'nesting_engine'}
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or '')
            assert not mod.startswith('materialsorting.web'), \
                '模块级禁止 import web（须在函数内延迟引入）'
            names = {mod.split('.')[0]}
        else:
            continue
        assert names <= allowed | {'materialsorting'}, sorted(names)
    # web 延迟 import 也只允许 solver 入口（不允许 server）
    assert 'from ..web.server' not in src and 'web.server' not in src


def test_real_solve_smoke(tmp_path, capsys):
    """真实 sparrow 子求解冒烟：多进程链路端到端（空段 splice 保底改进）。"""
    pieces = [_rect('g01_28', 'g01', 28, 500, 800), _rect('g02_28', 'g02', 28, 300, 400)]
    placed = [_at('g01_28', 0, 0), _at('g02_28', 1600, 0)]   # 空洞 [500,1600)
    run_dir = _make_run_dir(tmp_path, pieces, placed, seed=7)
    rc = lns.main(['--run-dir', str(run_dir), '--time', '6', '--rounds', '2',
                   '--band-width', '800'])
    assert rc == 0
    out = json.loads((run_dir / 'result_lns.json').read_text(encoding='utf-8'))
    assert out['source']['incumbent_seed'] == 7
    assert len(out['placed_items']) == 2                 # 全片在场
    assert out['recheck']['ok'] is True                  # constraints.validate 双通过
    assert out['recheck']['y_violations'] == 0
    assert out['improved'] is True                       # 空段 splice 确定性改进
    assert out['after']['width_mm'] <= out['before']['width_mm']
    assert (run_dir / 'lns_compare.svg').is_file()
    assert 'improved=True' in capsys.readouterr().out


def test_straddling_copies_never_shift_negative():
    """回归：跨段散布的 pid 副本不得被「后续段左移」推出 x<0（几何判定后续）。"""
    pieces = [_rect('g05_30', 'g05', 30, 300, 400),    # S（demand=2，副本散布）
              _rect('g06_30', 'g06', 30, 500, 300)]    # T
    layout = [_at('g05_30', 3500, 0),   # S1（首副本 → 组归段 3，但足迹散布）
              _at('g05_30', 100, 800),  # S2（同组副本在最左端）
              _at('g06_30', 1200, 0)]   # T
    out = lns.run_lns(layout, pieces, 1980.0, band_width=1000.0,
                      time_budget=30.0, rounds=4, solve=_column_packer)
    geoms = lns._layout_geometry(out['placed_items'], _by_id(pieces))
    assert all(g[1] >= -0.001 for g in geoms)          # 无片被推到 x<0
    assert out['improved'] is True                     # 空段 splice 仍生效
    assert out['after']['width_mm'] < out['before']['width_mm']
    assert out['recheck']['ok'] is True
