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
    _slide_west_touch,
    _transform_polygon,
    polish_layout,
)


def _piece(pid, w, h, label=None):
    return {'pid': pid, 'label': label or pid.split('_')[0], 'size': 28,
            'polygon': [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]],
            'area_mm2': float(w * h), 'net_polygon': [], 'internal_lines': [],
            'notches': [], 'grain_line': None}


def _l_piece(pid, label=None):
    """L 形非对称裁片（US-004 镜像判别性夹具）：右上空缺镜像后到左上 ——
    镜像与否几何/包络可判别（矩形镜像后平移可等价，判别力不足）。"""
    return {'pid': pid, 'label': label or pid.split('_')[0], 'size': 28,
            'polygon': [[0.0, 0.0], [200.0, 0.0], [200.0, 60.0], [60.0, 60.0],
                        [60.0, 150.0], [0.0, 150.0]],
            'area_mm2': 17400.0, 'net_polygon': [], 'internal_lines': [],
            'notches': [], 'grain_line': None}


def _pl(pid, rot, tx, ty, mirror=False):
    it = {'id': pid, 'rotation': float(rot), 'translation': [float(tx), float(ty)]}
    if mirror:
        it['mirror'] = True
    return it


def _world(pid, pieces, rot, tr, mirror=False):
    poly = pieces[pid]['polygon']
    if mirror:
        poly = [(-x, y) for x, y in poly]
    return Polygon(_transform_polygon(poly, rot, tr))


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
    """US-005 落地后 additive 口径（AC#2）：无空隙可收夹具下 compact=True 与
    缺省逐元素相同（紧密链全纠缠 → pass ④ 零 move + maxX 不变不回滚留痕）。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02'),
              'g03_30': _piece('g03_30', 100, 160, label='g03')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 98, 0),
              _pl('g03_30', 0, 196, 0)]
    o0, r0 = polish_layout(placed, pieces, 160.0)
    o1, r1 = polish_layout(placed, pieces, 160.0, compact=True)
    r0.pop('elapsed_sec')
    r1.pop('elapsed_sec')
    assert o0 == o1 and r0 == r1


# --------------------------------------------------- US-005 压缩回收档

def test_compact_reclaims_gap_envelope_shrinks():
    """AC#1：横排留 ≥30mm 空隙 → compact 包络减少 ≥29mm、零新重合（几何级）。

    三片横排各留 30mm 空隙：g01 已贴布头不动；g02 滑 30mm 贴 g01；g03 级联
    滑 60mm 贴 g02 新位 → 包络 360→300（−60 ≥ 29）。
    """
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02'),
              'g03_30': _piece('g03_30', 100, 160, label='g03')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 130, 0),
              _pl('g03_30', 0, 260, 0)]
    out, rep = polish_layout(placed, pieces, 160.0, compact=True)
    assert rep['after']['width_mm'] <= rep['before']['width_mm'] - 29.0
    assert rep['after']['overlap_pairs'] == 0
    assert rep['after']['density'] >= rep['before']['density'] - 1e-6
    assert [m['index'] for m in rep['moves']] == [1, 2]
    assert all(m['kind'] == 'compact' for m in rep['moves'])
    # 落位精确：g02 贴 g01 右缘（x=100）、g03 级联贴 g02 新右缘（x=200）
    assert out[1]['translation'][0] == pytest.approx(100.0, abs=1e-3)
    assert out[2]['translation'][0] == pytest.approx(200.0, abs=1e-3)
    assert out[0]['translation'] == placed[0]['translation']   # 未动片逐字段不变
    # 零新重合（物理毛版轮廓两两交集面积精确 0）
    geoms = [_world(p['id'], pieces, p['rotation'], p['translation']) for p in out]
    for i in range(3):
        for j in range(i + 1, 3):
            assert geoms[i].intersection(geoms[j]).area == 0.0
    # 确定性：compact 档同输入双跑全等（elapsed_sec 除外）
    out2, rep2 = polish_layout(placed, pieces, 160.0, compact=True)
    rep2.pop('elapsed_sec')
    rep_d = {k: v for k, v in rep.items() if k != 'elapsed_sec'}
    assert out == out2 and rep_d == rep2


def test_compact_excluded_immovable_but_obstacle():
    """exclude 命中片零压缩移动，但仍作障碍：右侧片 −x 滑贴它停下（不撞布头墙）。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02')}
    placed = [_pl('g01_30', 0, 50, 0), _pl('g02_30', 0, 200, 0)]
    out, rep = polish_layout(placed, pieces, 160.0, compact=True,
                             exclude={'labels': ['g01']})
    assert rep['excluded'] == [0]
    assert all(m['index'] != 0 for m in rep['moves'])
    assert out[0]['translation'] == placed[0]['translation']
    # g02 滑贴 g01 右缘 x=150（障碍语义：无它本应滑到布头 x=0）
    assert out[1]['translation'][0] == pytest.approx(150.0, abs=1e-3)
    assert rep['after']['width_mm'] == pytest.approx(250.0, abs=1e-3)
    assert any(m['kind'] == 'compact' for m in rep['moves'])


def test_compact_rollback_when_no_envelope_gain():
    """中段片可滑但 maxX 不减（右缘片 excluded 不可动）→ 整段回滚：
    输出与 moves与非 compact 档逐元素相同（无改进逐字节不变）。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02'),
              'g03_30': _piece('g03_30', 100, 160, label='g03')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 150, 0),
              _pl('g03_30', 0, 280, 0)]
    kw = {'exclude': {'labels': ['g03']}}
    o0, r0 = polish_layout(placed, pieces, 160.0, **kw)
    o1, r1 = polish_layout(placed, pieces, 160.0, compact=True, **kw)
    r0.pop('elapsed_sec')
    r1.pop('elapsed_sec')
    assert o0 == o1 and r0 == r1
    assert o1[1]['translation'] == placed[1]['translation']   # g02 滑移被回滚


def test_compact_entangled_piece_skipped():
    """残留重合纠缠片（当前位已碰撞）不参与压缩滑移（交给 residual 口径，
    不强行撕开版师 per_type d 工艺余量内的必要贴触）。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02')}
    # 紧密叠 2mm 对（d 余量形态）：无空位可分离 → residual；compact 不动它们
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 98, 0)]
    out, rep = polish_layout(placed, pieces, 160.0, compact=True)
    assert out is placed and rep['moves'] == []
    assert len(rep['residual']) == 1


# --------------------------------------------------- US-004 镜像片（edit-keyboard）

def test_mirror_world_geom_hand_computed():
    """US-004：``_world_geom`` 镜像片世界多边形手算对拍 —— 先局部 x 取负再旋转
    （``R(rot)·diag(−1,1)·p + t``），rot=0 精确 / rot=90 浮点近似逐点相等。"""
    pieces = {'gL_30': _l_piece('gL_30')}
    # rot=0, tr=(1000,500)：x' = −x+1000, y' = y+500（c=1,s=0 精确）
    g = polish._world_geom(
        {'id': 'gL_30', 'rotation': 0.0, 'translation': [1000.0, 500.0],
         'mirror': True}, pieces)
    expect0 = [(-x + 1000.0, y + 500.0) for x, y in pieces['gL_30']['polygon']]
    assert list(g.exterior.coords)[:-1] == expect0
    # rot=90, tr=(1000,500)：x' = −y+1000, y' = −x+500（c=cos90°≈6.1e-17 近似）
    g = polish._world_geom(
        {'id': 'gL_30', 'rotation': 90.0, 'translation': [1000.0, 500.0],
         'mirror': True}, pieces)
    expect90 = [(-y + 1000.0, -x + 500.0) for x, y in pieces['gL_30']['polygon']]
    assert list(g.exterior.coords)[:-1] == pytest.approx(expect90, abs=1e-9)


def test_mirror_tilted_derotate_passthrough_centroid_anchored():
    """US-004：镜像 L 形斜片 25° 居空场 → derotate 回正、mirror 透传、质心锚定
    （c_local 用镜像后多边形质心，t' 补偿公式不变 —— 镜像几何质心零漂移）。"""
    pieces = {'gL_30': _l_piece('gL_30')}
    placed = [_pl('gL_30', 25, 600, 600, mirror=True)]
    snap = _snapshot(placed)
    out, rep = polish_layout(placed, pieces, 2000.0)

    assert _rotation_dev(out[0]['rotation']) == 0.0
    assert out[0]['rotation'] in (0.0, 180.0)
    assert out[0].get('mirror') is True                 # omit-when-false 透传
    assert len(rep['moves']) == 1 and rep['moves'][0]['kind'] == 'derotate'
    g0 = _world('gL_30', pieces, placed[0]['rotation'],
                placed[0]['translation'], mirror=True)
    g1 = _world('gL_30', pieces, out[0]['rotation'],
                out[0]['translation'], mirror=True)
    assert g0.centroid.distance(g1.centroid) < 1e-6     # 质心锚定不漂移
    assert rep['after']['overlap_pairs'] == 0
    assert _snapshot(placed) == snap                    # 纯函数不改入参


def test_mirror_diagnosis_and_separation_on_mirrored_geometry():
    """US-004 判别性夹具：小方块落在「镜像后才有材料」的 L 空缺角对侧 ——
    诊断/分离必须按镜像几何算（漏 mirror 则 overlap_pairs=0、零 move），
    分离终态按镜像世界几何交集面积精确 0，mirror 在 move 后仍透传。"""
    pieces = {'gL_30': _l_piece('gL_30'), 'gS_30': _piece('gS_30', 40, 40,
                                                          label='gS')}
    # 镜像 L @ (200,0)：立柱占 x∈[140,200]×y∈[60,150]（未镜像时该区为空缺角）
    placed = [_pl('gL_30', 0, 200, 0, mirror=True),
              _pl('gS_30', 0, 150, 70)]
    out, rep = polish_layout(placed, pieces, 1000.0)

    assert rep['before']['overlap_pairs'] == 1
    assert rep['before']['total_overlap_area_mm2'] == pytest.approx(1600.0)
    assert rep['after']['overlap_pairs'] == 0
    assert [m['kind'] for m in rep['moves']] == ['separate']
    # 镜像片被动分离后 mirror 仍在、未镜像片无键（omit-when-false 双向）
    assert out[0].get('mirror') is True
    assert 'mirror' not in out[1]
    gl = _world('gL_30', pieces, out[0]['rotation'],
                out[0]['translation'], mirror=True)
    gs = _world('gS_30', pieces, out[1]['rotation'], out[1]['translation'])
    assert gl.intersection(gs).area == 0.0


def test_mirror_noop_returns_input_object():
    """US-004 无改进不变量：含镜像片的紧凑纠缠布局（分离方向全被守卫拒）→
    输出 = 输入 list 原对象（mirror 键逐字节保留），moves==[]。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 98, 0, mirror=True)]
    out, rep = polish_layout(placed, pieces, 160.0)

    assert out is placed                       # 原对象（含 mirror）逐字节不变
    assert placed[1].get('mirror') is True
    assert rep['moves'] == []
    assert [r['kind'] for r in rep['residual']] == ['overlap']


def test_mirror_compact_preserves_mirror():
    """US-004：compact −x 滑贴按镜像世界几何（镜像片贴真实右缘）+ 落位手算，
    move 后 mirror 透传。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02')}
    # 镜像 g02 @ tx=230 → x∈[130,230]，与 g01 右缘 x=100 留 30mm 空隙
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 230, 0, mirror=True)]
    out, rep = polish_layout(placed, pieces, 160.0, compact=True)

    assert [m['kind'] for m in rep['moves']] == ['compact']
    assert rep['moves'][0]['index'] == 1
    assert out[1].get('mirror') is True
    assert out[1]['translation'][0] == pytest.approx(200.0, abs=1e-3)
    g2 = _world('g02_30', pieces, out[1]['rotation'],
                out[1]['translation'], mirror=True)
    assert g2.bounds[0] == pytest.approx(100.0, abs=1e-3)   # 贴 g01 真实右缘
    assert rep['after']['width_mm'] == pytest.approx(200.0, abs=1e-3)


def test_mirror_compact_rollback_preserves_mirror():
    """US-004：compact 回滚路径（maxX 不减）经 items 快照重建 —— mirror 若不在
    快照里会被静默蒸发；锁「回滚后 mirror 仍在 + 与非 compact 档逐元素相同」。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02'),
              'g03_30': _piece('g03_30', 100, 160, label='g03')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 230, 0, mirror=True),
              _pl('g03_30', 0, 360, 0)]
    kw = {'exclude': {'labels': ['g03']}}
    o0, r0 = polish_layout(placed, pieces, 160.0, **kw)
    o1, r1 = polish_layout(placed, pieces, 160.0, compact=True, **kw)
    r0.pop('elapsed_sec')
    r1.pop('elapsed_sec')
    assert o0 == o1 and r0 == r1                 # 回滚 = 非 compact 档逐元素相同
    assert o1[1].get('mirror') is True           # 回滚不蒸发镜像标志
    assert o1[1]['translation'] == placed[1]['translation']   # 滑移被回滚


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


def test_slide_west_touch_variants():
    """US-005 单元算子 ``_slide_west_touch``：当前位碰撞 → 0 / 全程自由 → 贴
    x=0 布头墙 / 障碍在途 → 二分贴触 + 1nm 回退（终态交集面积精确 0）。"""
    mover = Polygon([(150, 0), (250, 0), (250, 100), (150, 100)])
    # ① 当前位已碰撞（叠 2mm）→ 0（纠缠片不可滑）
    blocker = Polygon([(148, 0), (248, 0), (248, 100), (148, 100)])
    assert _slide_west_touch(mover, [blocker], 150.0) == 0.0
    # ② 全程自由（障碍在上方 y 带外）→ 贴布头墙（t = t_wall = 150）
    far = Polygon([(0, 200), (100, 200), (100, 300), (0, 300)])
    assert _slide_west_touch(mover, [far], 150.0) == 150.0
    # ③ 障碍在途（左邻 x∈[0,100]）→ 二分贴触：滑 ~50mm 到 x=100，回退 1nm
    left = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    t = _slide_west_touch(mover, [left], 150.0)
    assert t == pytest.approx(50.0, abs=1e-3)
    moved = [(x - t, y) for x, y in mover.exterior.coords]
    assert Polygon(moved).intersection(left).area == 0.0


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
