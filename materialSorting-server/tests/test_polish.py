"""polish 引擎层确定性后处理单测（US-001，prd-edit-polish）。

夹具全部合成矩形（schema v2 最小字段），不依赖 intermediate / spyrrow；
物理毛版轮廓口径（原始 polygon）与 /export 同源。
"""
from __future__ import annotations

import ast
import time
from collections import Counter
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from materialsorting.nesting_engine import polish
from materialsorting.nesting_engine.polish import (
    PolishError,
    _derotate_ladder,
    _rotation_dev,
    _sep_translate,
    _transform_polygon,
    polish_layout,
)


def _piece(pid, w, h, label=None):
    return {'pid': pid, 'label': label or pid.split('_')[0], 'size': 28,
            'polygon': [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]],
            'area_mm2': float(w * h), 'net_polygon': [], 'internal_lines': [],
            'notches': [], 'grain_line': None}


def _pl(pid, rot, tx, ty):
    return {'id': pid, 'rotation': float(rot), 'translation': [float(tx), float(ty)]}


def _world(pid, pieces, rot, tr):
    return Polygon(_transform_polygon(pieces[pid]['polygon'], rot, tr))


def _snapshot(placed):
    return [(p['id'], p['rotation'], list(p['translation'])) for p in placed]


# ------------------------------------------------------------- AC#1 斜片回正

def test_empty_field_tilted_piece_derotates():
    """单片 rot=25 居空场 → 回正 ∈ {0,180}、dev=0、零重合、质心位移最小（=0）。"""
    pieces = {'g01_30': _piece('g01_30', 300, 100)}
    placed = [_pl('g01_30', 25, 500, 500)]
    snap = _snapshot(placed)
    out, rep = polish_layout(placed, pieces, 2000.0)

    assert _rotation_dev(out[0]['rotation']) == 0.0
    assert out[0]['rotation'] in (0.0, 180.0)
    assert rep['after']['overlap_pairs'] == 0
    assert len(rep['moves']) == 1
    mv = rep['moves'][0]
    assert mv['kind'] == 'derotate' and mv['index'] == 0 and mv['pid'] == 'g01_30'
    assert mv['from']['rotation'] == 25.0 and mv['to']['rotation'] in (0.0, 180.0)
    # 质心锚定：旋转前后世界质心不动（位移最小 = 0，空场无障碍）
    g0 = _world('g01_30', pieces, placed[0]['rotation'], placed[0]['translation'])
    g1 = _world('g01_30', pieces, out[0]['rotation'], out[0]['translation'])
    assert g0.centroid.distance(g1.centroid) < 1e-6
    # 诊断指标：斜片 1→0、Σ偏差 25→0
    assert rep['before']['rotated_pieces'] == 1
    assert rep['after']['rotated_pieces'] == 0
    assert rep['before']['rotation_dev_sum_deg'] == 25.0
    assert rep['after']['rotation_dev_sum_deg'] == 0.0
    # 纯函数：输入未被就地修改
    assert _snapshot(placed) == snap


# ----------------------------------------------------------- AC#2 重合清零

def test_separable_overlap_pair_cleared():
    """两片叠 5mm 且上方有空位 → polish 后 shapely 交集面积精确 = 0。"""
    pieces = {'g01_30': _piece('g01_30', 200, 150),
              'g02_30': _piece('g02_30', 200, 150, label='g02')}
    placed = [_pl('g01_30', 0, 100, 100), _pl('g02_30', 0, 100, 245)]
    out, rep = polish_layout(placed, pieces, 1000.0)

    inter = _world('g01_30', pieces, out[0]['rotation'],
                   out[0]['translation']).intersection(
        _world('g02_30', pieces, out[1]['rotation'], out[1]['translation']))
    assert inter.area == 0.0
    assert rep['before']['overlap_pairs'] == 1
    assert rep['after']['overlap_pairs'] == 0
    assert rep['before']['max_penetration_mm'] == 5.0
    assert [m['kind'] for m in rep['moves']] == ['separate']
    assert rep['residual'] == []
    # 最小分离：动片沿分离轴只移 ~5mm（bbox 全高量级 145/295mm 是非最小路径）
    mv = rep['moves'][0]
    dy = mv['to']['translation'][1] - mv['from']['translation'][1]
    dx = mv['to']['translation'][0] - mv['from']['translation'][0]
    delta = dy if abs(dy) > abs(dx) else dx
    assert abs(abs(delta) - 5.0) < 0.01


# ---------------------------------------------------------- AC#3 紧密 no-op

def test_tight_layout_noop_byte_identical():
    """满门幅贴触链叠 2mm（d 余量形态）→ 输出 list 原对象、moves==[]、residual 如实。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02'),
              'g03_30': _piece('g03_30', 100, 160, label='g03')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 98, 0),
              _pl('g03_30', 0, 196, 0)]
    out, rep = polish_layout(placed, pieces, 160.0)

    assert out is placed                    # 逐字节不变量：list 原对象
    assert rep['moves'] == []
    assert rep['before']['overlap_pairs'] == 2
    ov = [r for r in rep['residual'] if r['kind'] == 'overlap']
    assert sorted(r['indices'] for r in ov) == [[0, 1], [1, 2]]
    assert all(r['area_mm2'] > 0 for r in ov)


# --------------------------------------------------------- AC#4 守卫拒绝路径

def test_guard_gate_rejected():
    """唯一分离方向越门幅（+y 越顶、−y/−x 被邻片堵）→ move 被拒。"""
    pieces = {'g01_30': _piece('g01_30', 200, 120),      # U 顶部贴门幅
              'g02_30': _piece('g02_30', 200, 80, label='g02'),   # L 与 U 叠 5mm
              'g03_30': _piece('g03_30', 200, 175, label='g03'),  # B 堵 −y
              'g04_30': _piece('g04_30', 600, 200, label='g04')}  # W 堵 −x
    placed = [_pl('g01_30', 0, 600, 880), _pl('g02_30', 0, 650, 875),
              _pl('g03_30', 0, 650, 700), _pl('g04_30', 0, 0, 800)]
    out, rep = polish_layout(placed, pieces, 1000.0)

    assert out is placed
    assert rep['moves'] == []
    assert rep['before']['overlap_pairs'] == 1
    assert [r for r in rep['residual'] if r['kind'] == 'overlap']


def test_guard_envelope_growth_rejected():
    """唯一空位在 +x 尾部外：rot0 bbox 更宽的斜片任何候选位都增包络 → 被拒。"""
    pieces = {'g01_30': _piece('g01_30', 400, 40),
              'g02_30': _piece('g02_30', 300, 600, label='g02')}
    placed = [_pl('g02_30', 0, 0, 200), _pl('g01_30', 25, 379, 200)]
    out, rep = polish_layout(placed, pieces, 1000.0)

    assert out is placed
    assert rep['moves'] == []
    rot_res = [r for r in rep['residual'] if r['kind'] == 'rotation']
    assert len(rot_res) == 1 and rot_res[0]['index'] == 1
    assert rot_res[0]['dev_deg'] == 25.0


# ------------------------------------------------------- AC#5 多副本 index 寻址

def test_multicopy_index_addressing():
    """同 pid 3 副本仅第 2 条需微调 → 其余两条逐字段不变（按 index 寻址）。"""
    pieces = {'g01_30': _piece('g01_30', 300, 100)}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g01_30', 25, 600, 600),
              _pl('g01_30', 0, 1200, 0)]
    out, rep = polish_layout(placed, pieces, 2000.0)

    assert len(rep['moves']) == 1 and rep['moves'][0]['index'] == 1
    assert rep['moves'][0]['from']['rotation'] == 25.0
    assert out[0]['id'] == out[1]['id'] == out[2]['id'] == 'g01_30'
    assert (out[0]['rotation'], out[0]['translation']) == \
        (placed[0]['rotation'], placed[0]['translation'])
    assert (out[2]['rotation'], out[2]['translation']) == \
        (placed[2]['rotation'], placed[2]['translation'])
    assert _rotation_dev(out[1]['rotation']) == 0.0
    # pid 多重集守恒（守卫④：绝不 pid 去重）
    assert Counter(p['id'] for p in out) == {'g01_30': 3}


# ---------------------------------------------------------- AC#6 排除集语义

def _exclude_fixture():
    pieces = {'g01_30': _piece('g01_30', 200, 150),
              'g02_30': _piece('g02_30', 200, 150, label='g02'),
              'g03_30': _piece('g03_30', 200, 150, label='g03')}
    placed = [_pl('g01_30', 0, 100, 760),    # A（将被 exclude）
              _pl('g02_30', 0, 100, 460),    # B：+y 最小分离位落在 A 上
              _pl('g03_30', 0, 100, 600)]    # C：与 B 叠 10mm
    return pieces, placed


def test_exclude_by_labels_immovable_but_obstacle():
    """exclude 命中实例零移动；第三片朝它滑移仍被它挡住（障碍语义）。"""
    pieces, placed = _exclude_fixture()
    out, rep = polish_layout(placed, pieces, 1000.0, exclude={'labels': ['g01']})

    assert rep['excluded'] == [0]
    assert all(m['index'] != 0 for m in rep['moves'])
    assert out[0]['translation'] == placed[0]['translation']
    assert out[0]['rotation'] == placed[0]['rotation']
    # B/C 重合被解，且 B 没有落进 A（+y 被 A 挡下 → 改走 −y）
    ga = _world('g01_30', pieces, out[0]['rotation'], out[0]['translation'])
    gb = _world('g02_30', pieces, out[1]['rotation'], out[1]['translation'])
    gc = _world('g03_30', pieces, out[2]['rotation'], out[2]['translation'])
    assert gb.intersection(gc).area == 0.0
    assert gb.intersection(ga).area == 0.0
    assert any(m['index'] == 1 and '−y' in m['detail'] for m in rep['moves'])


def test_exclude_by_pids_immovable():
    """pids 键同语义（labels/pids 双键，缺省 None）。"""
    pieces, placed = _exclude_fixture()
    out, rep = polish_layout(placed, pieces, 1000.0, exclude={'pids': ['g01_30']})
    assert rep['excluded'] == [0]
    assert out[0]['translation'] == placed[0]['translation']


# --------------------------------------------------------------- AC#7 确定性

def test_determinism_double_run():
    """同输入连跑两次，placed_new 与 report 数值全等（elapsed_sec 除外）。"""
    pieces = {'g01_30': _piece('g01_30', 300, 100),
              'g02_30': _piece('g02_30', 200, 150, label='g02')}
    placed = [_pl('g01_30', 25, 100, 100), _pl('g02_30', 15, 280, 180),
              _pl('g01_30', 155, 700, 900)]
    o1, r1 = polish_layout(placed, pieces, 1500.0)
    o2, r2 = polish_layout(placed, pieces, 1500.0)
    r1.pop('elapsed_sec')
    r2.pop('elapsed_sec')
    assert o1 == o2 and r1 == r2


# ----------------------------------------------------------- 结构与边界

def test_report_shape():
    """report 结构：before/after 七指标 + moves/residual/excluded/elapsed_sec。"""
    pieces = {'g01_30': _piece('g01_30', 200, 150)}
    placed = [_pl('g01_30', 0, 0, 0)]
    out, rep = polish_layout(placed, pieces, 1000.0)
    assert set(rep) == {'before', 'after', 'moves', 'residual', 'excluded',
                        'elapsed_sec'}
    fields = {'overlap_pairs', 'max_penetration_mm', 'total_overlap_area_mm2',
              'rotated_pieces', 'rotation_dev_sum_deg', 'width_mm', 'density'}
    assert set(rep['before']) == fields and set(rep['after']) == fields
    for mv in rep['moves']:
        assert set(mv) == {'index', 'pid', 'kind', 'from', 'to', 'detail'}


def test_density_real_metric():
    """density = real 口径 Σ(area×multiplicity)/(width×gate)（百分数）。"""
    pieces = {'g01_30': _piece('g01_30', 200, 150)}       # 30000mm²
    placed = [_pl('g01_30', 0, 0, 0), _pl('g01_30', 0, 200, 0)]
    out, rep = polish_layout(placed, pieces, 1000.0)
    assert rep['before']['width_mm'] == 400.0
    assert rep['before']['density'] == pytest.approx(
        2 * 30000.0 / (400.0 * 1000.0) * 100.0)


def test_empty_placed_noop():
    placed = []
    out, rep = polish_layout(placed, {}, 1000.0)
    assert out is placed
    assert rep['before'] == rep['after']
    assert rep['before']['overlap_pairs'] == 0
    assert rep['before']['density'] == 0.0
    assert rep['before']['width_mm'] == 0.0
    assert rep['moves'] == [] and rep['residual'] == []


def test_unknown_pid_raises():
    pieces = {'g01_30': _piece('g01_30', 200, 150)}
    with pytest.raises(PolishError, match='母版已变更'):
        polish_layout([_pl('gXX_30', 0, 0, 0)], pieces, 1000.0)


def test_input_never_mutated():
    """纯函数：有 move 时输入 placements 逐字段不变（输出为新对象）。"""
    pieces = {'g01_30': _piece('g01_30', 200, 150),
              'g02_30': _piece('g02_30', 200, 150, label='g02')}
    placed = [_pl('g01_30', 25, 100, 100), _pl('g02_30', 0, 150, 200)]
    snap = _snapshot(placed)
    out, rep = polish_layout(placed, pieces, 1000.0)
    assert rep['moves']                      # 本夹具确有 move（斜片回正）
    assert _snapshot(placed) == snap
    assert out is not placed


def test_compact_kwarg_accepted_additive():
    """compact 键位为 US-005 预留：实现前 compact=True 与缺省逐元素相同。"""
    pieces = {'g01_30': _piece('g01_30', 300, 100),
              'g02_30': _piece('g02_30', 200, 150, label='g02')}
    placed = [_pl('g01_30', 25, 100, 100), _pl('g02_30', 0, 280, 100)]
    o0, r0 = polish_layout(placed, pieces, 1000.0)
    o1, r1 = polish_layout(placed, pieces, 1000.0, compact=True)
    r0.pop('elapsed_sec')
    r1.pop('elapsed_sec')
    assert o0 == o1 and r0 == r1


# --------------------------------------------------------------- 单元算子

def test_rotation_dev_and_ladder():
    assert _rotation_dev(0.0) == 0.0
    assert _rotation_dev(180.0) == 0.0
    assert _rotation_dev(-25.0) == pytest.approx(25.0)
    assert _rotation_dev(155.0) == pytest.approx(25.0)
    assert _rotation_dev(205.0) == pytest.approx(25.0)
    # 阶梯：先试基线（dev=0）、全部严格降 dev、只取最近基线一侧
    lad = _derotate_ladder(25.0)
    assert lad[0] == 0.0
    assert all(_rotation_dev(a) < 25.0 for a in lad)
    assert _derotate_ladder(0.0) == [] and _derotate_ladder(180.0) == []
    assert _derotate_ladder(155.0)[0] == 180.0
    # 最近基线一侧：rot=25 的候选不含 180 附近的角
    assert all(abs(a) <= 25.0 or abs(a - 360.0) <= 25.0 for a in lad)


def test_sep_translate_x_negative_direction():
    """−x 最小分离方向符号锁死（bbox 分离界 = mb[2] − ob[0]）。"""
    ga = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    gb = Polygon([(98, 0), (198, 0), (198, 100), (98, 100)])
    res = _sep_translate(ga, gb, 'x', -1.0)
    assert res is not None
    dx, dy, t = res
    assert dx == pytest.approx(-2.0, abs=0.01) and dy == 0.0
    assert t == pytest.approx(2.0, abs=0.01)
    moved = Polygon([(dx, dy), (100 + dx, dy), (100 + dx, 100 + dy), (dx, 100 + dy)])
    assert moved.intersection(gb).area == 0.0


# --------------------------------------------------------------- 分层纯度

def test_module_layering_purity():
    """分层未反向：polish.py 模块级 import 只 stdlib + shapely + 向下/同层，
    禁 import web/cli（AST 守卫，镜像 test_prefix/test_waist_band 套路）。"""
    src = Path(polish.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'argparse', 'json', 'math', 'os', 'sys', 'time',
               'collections', 'shapely', 'materialsorting', 'nesting_bounds',
               'nesting_engine'}
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert not mod.startswith('materialsorting.web'), \
                '模块级禁止 import web（分层单向）'
            assert not mod.startswith('materialsorting.cli'), \
                '模块级禁止 import cli（分层单向）'
            names = {'nesting_engine'} if node.level == 1 \
                else ({'materialsorting'} if node.level >= 2
                      else {mod.split('.')[0]})
        else:
            continue
        assert names <= allowed, sorted(names - allowed)
    # 源级哨兵：任何 web/cli 引用（含函数内延迟 import）都不允许
    assert 'materialsorting.web' not in src and 'materialsorting.cli' not in src
    assert 'from ..web' not in src and 'from .web' not in src


def test_smoke_main_fixtures_pass(capsys):
    """`python -m` 冒烟同一代码路径：合成夹具自检全过 exit 0。"""
    assert polish.main([]) == 0
    out = capsys.readouterr().out
    assert 'PASS' in out


# --------------------------------------------------------------- 性能预算

def test_performance_120_pieces_under_5s():
    """性能预算：~120 片带重合与斜片 ≤5s（AC 口径：bbox 预筛 + 逐 move 局部检查）。"""
    pieces = {}
    placed = []
    gate = 2000.0
    idx = 0
    for row in range(12):
        y = row * 165.0
        for col in range(10):
            pid = f'g{idx // 10 + 1:02d}_{28 + idx % 10}'
            pieces[pid] = _piece(pid, 100, 140, label=f'g{idx // 10 + 1:02d}')
            rot = 10.0 if idx % 5 == 0 else 0.0
            placed.append(_pl(pid, rot, col * 98.0, y))
            idx += 1
    t0 = time.perf_counter()
    out, rep = polish_layout(placed, pieces, gate)
    elapsed = time.perf_counter() - t0
    assert len(placed) == 120
    assert elapsed < 5.0
    assert rep['after']['overlap_pairs'] <= rep['before']['overlap_pairs']
    assert rep['after']['width_mm'] <= rep['before']['width_mm'] + 0.5
