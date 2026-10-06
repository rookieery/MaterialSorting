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
from shapely.affinity import translate
from shapely.geometry import Polygon

from materialsorting.nesting_engine import polish
from materialsorting.nesting_engine.polish import (
    PolishError,
    _derotate_ladder,
    _polish_once,
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
    """单片 rot=25 居空场 → 回正 ∈ {0,180}、dev=0、零重合、质心位移最小（=0）。

    贴附 pass（2026-10-05 默认启用）随后会把回正后的片聚拢到墙角 —— 质心/
    单 move 断言锚定 derotate move 本身（moves[0]），attach move 只验 kind。
    """
    pieces = {'g01_30': _piece('g01_30', 300, 100)}
    placed = [_pl('g01_30', 25, 500, 500)]
    snap = _snapshot(placed)
    out, rep = polish_layout(placed, pieces, 2000.0)

    assert _rotation_dev(out[0]['rotation']) == 0.0
    assert out[0]['rotation'] in (0.0, 180.0)
    assert rep['after']['overlap_pairs'] == 0
    mv = rep['moves'][0]
    assert mv['kind'] == 'derotate' and mv['index'] == 0 and mv['pid'] == 'g01_30'
    assert mv['from']['rotation'] == 25.0 and mv['to']['rotation'] in (0.0, 180.0)
    assert all(m['kind'] == 'attach' for m in rep['moves'][1:])
    # 质心锚定：derotate move 前后世界质心不动（位移最小 = 0，空场无障碍）
    g0 = _world('g01_30', pieces, placed[0]['rotation'], placed[0]['translation'])
    g1 = _world('g01_30', pieces, mv['to']['rotation'], mv['to']['translation'])
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
    # 分离 move 在前（moves[0]）；贴附 pass 随后把两片聚拢到布头（新默认）
    assert rep['moves'][0]['kind'] == 'separate'
    assert all(m['kind'] == 'attach' for m in rep['moves'][1:])
    assert rep['residual'] == []
    # 最小分离：分离 move 沿分离轴只移 ~5mm（bbox 全高量级 145/295mm 是非最小路径）
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
    """唯一分离方向越门幅（+y 越顶、−y/−x 被邻片堵）→ 分离 move 被拒。

    守卫意图 = U/L 重合对保持未分离且两者原地不动；其余未贴附片（B/W）被
    贴附 pass 合法聚拢属 2026-10-05 起新默认行为，不与守卫冲突。
    """
    pieces = {'g01_30': _piece('g01_30', 200, 120),      # U 顶部贴门幅
              'g02_30': _piece('g02_30', 200, 80, label='g02'),   # L 与 U 叠 5mm
              'g03_30': _piece('g03_30', 200, 175, label='g03'),  # B 堵 −y
              'g04_30': _piece('g04_30', 600, 200, label='g04')}  # W 堵 −x
    placed = [_pl('g01_30', 0, 600, 880), _pl('g02_30', 0, 650, 875),
              _pl('g03_30', 0, 650, 700), _pl('g04_30', 0, 0, 800)]
    out, rep = polish_layout(placed, pieces, 1000.0)

    assert out[0]['translation'] == placed[0]['translation']
    assert out[1]['translation'] == placed[1]['translation']
    assert all(m['kind'] == 'attach' for m in rep['moves'])
    assert all(m['index'] in (2, 3) for m in rep['moves'])
    assert rep['before']['overlap_pairs'] == 1
    assert [r for r in rep['residual'] if r['kind'] == 'overlap']


def test_guard_envelope_growth_rejected():
    """包络守卫在新搜索下的行为演进（2026-10-06）：旧「唯一空位在 +x 尾部外」
    场景被四向滑贴解锁 —— 斜片 −x 滑贴 114mm 贴 g02 东缘归位 0°、包络反而
    收缩（741.5→700）。守卫仍逐 move 生效（本例所有 move 包络不增；越门幅
    拒绝路径由 ④ 独立覆盖）。"""
    pieces = {'g01_30': _piece('g01_30', 400, 40),
              'g02_30': _piece('g02_30', 300, 600, label='g02')}
    placed = [_pl('g02_30', 0, 0, 200), _pl('g01_30', 25, 379, 200)]
    out, rep = polish_layout(placed, pieces, 1000.0)

    assert rep['after']['width_mm'] <= rep['before']['width_mm'] + 0.5
    assert rep['after']['overlap_pairs'] == 0
    g1 = _world('g01_30', pieces, out[1]['rotation'], out[1]['translation'])
    g2 = _world('g02_30', pieces, out[0]['rotation'], out[0]['translation'])
    assert g1.intersection(g2).area == 0.0
    assert g1.distance(g2) <= 1e-3          # 归位后贴附（贴附不降级）
    # 斜片已归位（四向滑贴解锁了旧 bbox 对齐够不到的位）
    mv = [m for m in rep['moves'] if m['kind'] == 'derotate']
    assert mv and mv[0]['index'] == 1
    assert _rotation_dev(out[1]['rotation']) == 0.0


# ------------------------------------------------------- AC#5 多副本 index 寻址

def test_multicopy_index_addressing():
    """同 pid 3 副本仅第 2 条斜置 → derotate 按 index 寻址；贴附 pass 随后
    聚拢未贴附副本（新默认），第 1 条贴布头副本恒不动。"""
    pieces = {'g01_30': _piece('g01_30', 300, 100)}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g01_30', 25, 600, 600),
              _pl('g01_30', 0, 1200, 0)]
    out, rep = polish_layout(placed, pieces, 2000.0)

    assert rep['moves'][0]['kind'] == 'derotate'
    assert rep['moves'][0]['index'] == 1
    assert rep['moves'][0]['from']['rotation'] == 25.0
    assert out[0]['id'] == out[1]['id'] == out[2]['id'] == 'g01_30'
    assert (out[0]['rotation'], out[0]['translation']) == \
        (placed[0]['rotation'], placed[0]['translation'])
    assert all(m['index'] != 0 for m in rep['moves'])
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
    """report 结构：before/after 七指标 + moves/residual/excluded/attach_moves/
    escape_moves/elapsed_sec/rounds（attach_moves 2026-10-05、escape_moves
    2026-10-06、rounds 2026-10-06 迭代至不动点 additive）。"""
    pieces = {'g01_30': _piece('g01_30', 200, 150)}
    placed = [_pl('g01_30', 0, 0, 0)]
    out, rep = polish_layout(placed, pieces, 1000.0)
    assert set(rep) == {'before', 'after', 'moves', 'residual', 'excluded',
                        'attach_moves', 'escape_moves', 'elapsed_sec', 'rounds'}
    assert rep['attach_moves'] == 0 and isinstance(rep['attach_moves'], int)
    assert rep['escape_moves'] == 0 and isinstance(rep['escape_moves'], int)
    assert rep['rounds'] == 1 and isinstance(rep['rounds'], int)
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
    """AC#1：横排留 ≥30mm 空隙 → 包络减少 ≥29mm、零新重合（几何级）。

    三片横排各留 30mm 空隙：g01 已贴布头不动；g02 滑 30mm 贴 g01；g03 级联
    滑 60mm 贴 g02 新位 → 包络 360→300（−60 ≥ 29）。贴附 pass（2026-10-05
    默认先行）收空隙，compact 档无剩可收（同结果零回滚留痕）。
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
    assert all(m['kind'] == 'attach' for m in rep['moves'])
    assert rep['attach_moves'] == 2
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
    """exclude 命中片零贴附移动，但仍作障碍：右侧片 −x 滑贴它停下（不撞布头墙）。"""
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
    assert any(m['kind'] == 'attach' for m in rep['moves'])


def test_compact_rollback_when_no_envelope_gain():
    """compact=true ≡ false 逐元素相同（贴附 pass 先行收空隙后 compact 档零
    move 回滚不留痕）；g02 的滑贴以 attach move 出现在两档（落位一致）。"""
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
    assert o0 == o1 and r0 == r1                 # 两档逐元素相同（回滚无留痕）
    assert all(m['kind'] == 'attach' for m in r1['moves'])   # compact 零 move
    assert o1[1]['translation'][0] == pytest.approx(100.0, abs=1e-3)  # 贴 g01 右缘


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


# ------------------------------------------- 贴附 pass（attach，2026-10-05）

def test_attach_south_closes_vertical_gap():
    """竖向留 140mm 空隙 → south 趟滑贴到下方片顶边 +1nm、零重合、料长不变
    （编辑画布大空白带场景的合成最小复现）。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 0, 300)]
    out, rep = polish_layout(placed, pieces, 1000.0)

    assert rep['attach_moves'] == 1
    mv = rep['moves'][0]
    assert mv['kind'] == 'attach' and mv['index'] == 1
    assert mv['detail'].startswith('−y')
    assert out[1]['translation'][1] == pytest.approx(160.0, abs=1e-2)
    g1 = _world('g01_30', pieces, out[0]['rotation'], out[0]['translation'])
    g2 = _world('g02_30', pieces, out[1]['rotation'], out[1]['translation'])
    assert g1.intersection(g2).area == 0.0
    assert g1.distance(g2) <= 1e-3                 # 贴附到位（触距 ~1nm）
    assert rep['after']['overlap_pairs'] == 0
    assert rep['after']['width_mm'] == rep['before']['width_mm']  # south 不动料长


def test_attach_snug_skip_keeps_snug_angle():
    """贴附保持的减少旋转（2026-10-06 新语义，取代 2026-10-05 snug 一刀切
    冻结 + 方案 A）：3° 斜片距邻片 0.65mm（干净贴附、严格档）→ **照旧进阶梯**，
    归位到更小角度且新位贴附（「更小角度同样贴附才动、动则必贴」）；同款
    斜片在空场（宽松档）也归位。旧断言「保角 + residual」是冻结时代行为，
    5156 实勘证其误伤（手眼可行位引擎视而不见）后废除。"""
    pieces = {'g01_30': _piece('g01_30', 200, 150),
              'g02_30': _piece('g02_30', 200, 150, label='g02')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 3, 208.5, 0)]
    out, rep = polish_layout(placed, pieces, 1000.0)

    # 严格档：归位（0° 首选）+ 新位贴附 + 无重合
    mv = rep['moves'][0]
    assert mv['kind'] == 'derotate' and mv['index'] == 1
    assert mv['from']['rotation'] == pytest.approx(3.0)
    assert _rotation_dev(out[1]['rotation']) == 0.0
    assert not any(r['kind'] == 'rotation' and r['index'] == 1
                   for r in rep['residual'])
    g1 = _world('g01_30', pieces, out[0]['rotation'], out[0]['translation'])
    g2 = _world('g02_30', pieces, out[1]['rotation'], out[1]['translation'])
    assert g1.intersection(g2).area == 0.0
    assert g1.distance(g2) <= 1e-3          # 动则必贴
    # 对照：未贴附斜片（宽松档）同样归位
    placed2 = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 3, 600, 600)]
    out2, rep2 = polish_layout(placed2, pieces, 1000.0)
    assert _rotation_dev(out2[1]['rotation']) == 0.0
    assert rep2['moves'][0]['kind'] == 'derotate'


def test_attach_press_overlap_not_snug_derotates():
    """方案 A（2026-10-05 同日收紧）：压线相交（交面积 >0.1mm²）不算已贴附
    —— 3° 斜片角部咬进邻片（5156 race 腰头成带实勘复现）→ 进归位阶梯
    转平（0° 首选位即合法、压线随之消失），贴附 pass 随后吸贴。"""
    pieces = {'g01_30': _piece('g01_30', 200, 150),
              'g02_30': _piece('g02_30', 200, 150, label='g02')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 3, 207.0, 0)]
    out, rep = polish_layout(placed, pieces, 1000.0)

    # 入态确有压线重合（角部咬入 ~7.7mm²）
    assert rep['before']['overlap_pairs'] == 1
    # 归位先行：斜片转平（不再被「相交=已贴附」误判 snug 冻结）
    mv = rep['moves'][0]
    assert mv['kind'] == 'derotate' and mv['index'] == 1
    assert mv['from']['rotation'] == 3.0 and mv['to']['rotation'] == 0.0
    assert _rotation_dev(out[1]['rotation']) == 0.0
    assert all(m['kind'] in ('attach',) for m in rep['moves'][1:])
    assert not any(r['kind'] == 'rotation' and r['index'] == 1
                   for r in rep['residual'])
    # 终态：压线消失 + 与邻片贴附（贴触零重合）
    g1 = _world('g01_30', pieces, out[0]['rotation'], out[0]['translation'])
    g2 = _world('g02_30', pieces, out[1]['rotation'], out[1]['translation'])
    assert g1.intersection(g2).area == 0.0
    assert g1.distance(g2) <= 1e-3


def test_attach_slides_to_walls():
    """孤立片重力压实 → 滑到布头 x=0 与下门幅 y=0 墙（两 move、钳制在界内）。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160)}
    placed = [_pl('g01_30', 0, 300, 400)]
    out, rep = polish_layout(placed, pieces, 1000.0)

    assert rep['attach_moves'] == 2
    assert [m['detail'][:2] for m in rep['moves']] == ['−x', '−y']
    assert out[0]['translation'] == pytest.approx([0.0, 0.0], abs=1e-3)
    g = _world('g01_30', pieces, out[0]['rotation'], out[0]['translation'])
    assert g.bounds[0] >= -1e-6 and g.bounds[1] >= -1e-6   # 钳制在 [0,gate] 内


def test_attach_cascade_west_then_south():
    """错位空隙级联：片先 west 贴墙、再 south 贴到下方片顶 —— 两趟交替一轮
    收敛到 (0,160)。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 150, 300)]
    out, rep = polish_layout(placed, pieces, 1000.0)

    assert out[1]['translation'] == pytest.approx([0.0, 160.0], abs=1e-2)
    assert rep['attach_moves'] == 2
    g1 = _world('g01_30', pieces, out[0]['rotation'], out[0]['translation'])
    g2 = _world('g02_30', pieces, out[1]['rotation'], out[1]['translation'])
    assert g1.intersection(g2).area == 0.0
    assert g1.distance(g2) <= 1e-3


def test_attach_invariants_on_loose_layout():
    """不变量总检：松散多片布局（含斜片/多副本）贴附后 —— 全图两两交集面积
    精确 0、y∈[0,gate]、包络不增、pid 多重集守恒、确定性双跑全等。"""
    pieces = {'g01_30': _piece('g01_30', 300, 100),
              'g02_30': _piece('g02_30', 200, 150, label='g02')}
    placed = [_pl('g01_30', 25, 100, 100), _pl('g02_30', 15, 480, 180),
              _pl('g01_30', 155, 900, 900)]
    out, rep = polish_layout(placed, pieces, 1500.0)

    assert rep['attach_moves'] >= 1
    geoms = [_world(p['id'], pieces, p['rotation'], p['translation']) for p in out]
    for i in range(3):
        for j in range(i + 1, 3):
            assert geoms[i].intersection(geoms[j]).area == 0.0
        assert geoms[i].bounds[1] >= -1e-6 and geoms[i].bounds[3] <= 1500.0 + 1e-6
    assert rep['after']['width_mm'] <= rep['before']['width_mm'] + 0.5
    assert Counter(p['id'] for p in out) == {'g01_30': 2, 'g02_30': 1}
    o2, r2 = polish_layout(placed, pieces, 1500.0)
    r2.pop('elapsed_sec')
    rep_d = {k: v for k, v in rep.items() if k != 'elapsed_sec'}
    assert out == o2 and rep_d == r2


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
    mv = rep['moves'][0]
    assert mv['kind'] == 'derotate'
    assert all(m['kind'] == 'attach' for m in rep['moves'][1:])  # 贴附聚拢随后
    g0 = _world('gL_30', pieces, placed[0]['rotation'],
                placed[0]['translation'], mirror=True)
    g1 = _world('gL_30', pieces, mv['to']['rotation'],
                mv['to']['translation'], mirror=True)
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
    assert rep['moves'][0]['kind'] == 'separate'
    assert all(m['kind'] == 'attach' for m in rep['moves'][1:])
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
    """US-004：−x 滑贴按镜像世界几何（镜像片贴真实右缘）+ 落位手算，move 后
    mirror 透传（贴附 pass 先行，compact 档同结果零回滚留痕）。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02')}
    # 镜像 g02 @ tx=230 → x∈[130,230]，与 g01 右缘 x=100 留 30mm 空隙
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 230, 0, mirror=True)]
    out, rep = polish_layout(placed, pieces, 160.0, compact=True)

    assert [m['kind'] for m in rep['moves']] == ['attach']
    assert rep['moves'][0]['index'] == 1
    assert out[1].get('mirror') is True
    assert out[1]['translation'][0] == pytest.approx(200.0, abs=1e-3)
    g2 = _world('g02_30', pieces, out[1]['rotation'],
                out[1]['translation'], mirror=True)
    assert g2.bounds[0] == pytest.approx(100.0, abs=1e-3)   # 贴 g01 真实右缘
    assert rep['after']['width_mm'] == pytest.approx(200.0, abs=1e-3)


def test_mirror_compact_rollback_preserves_mirror():
    """US-004：compact 回滚路径（maxX 不减）经 items 快照重建 —— mirror 若不在
    快照里会被静默蒸发；锁「回滚后 mirror 仍在 + 与非 compact 档逐元素相同」
    （贴附 pass 先行滑贴，compact 档零 move 回滚，两档仍逐元素相同）。"""
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
    assert all(m['kind'] == 'attach' for m in r1['moves'])   # compact 零 move
    assert o1[1].get('mirror') is True           # 回滚不蒸发镜像标志
    assert o1[1]['translation'][0] == pytest.approx(200.0, abs=1e-3)  # 贴附落位


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


# ------------------------------------------------- 逃逸兜底（2026-10-06）

def test_scan_to_clean_primitive():
    """_scan_to_clean 原语：U 形槽窄窗（~10mm）命中 + 落位干净 + 无窗 None +
    起点已净返回 0 —— 锁死「必须 10mm 形状级细采样」（20mm 粗扫步必漏窄窗，
    3069 g09_29 实勘依据）。"""
    mover = Polygon([[100.0, 25.0], [150.0, 25.0], [150.0, 50.0], [100.0, 50.0]])
    u_slot = Polygon([[0.0, 0.0], [140.0, 0.0], [140.0, 50.0], [90.0, 50.0],
                      [90.0, 20.0], [30.0, 20.0], [30.0, 50.0], [0.0, 50.0]])
    geoms = [mover, u_slot]
    bounds = [g.bounds for g in geoms]
    # −x 逃逸窗：mover 完全入槽需 x∈[30,90] → t∈[60,70]，窗宽 10mm < 20mm 粗扫步
    t = polish._scan_to_clean(mover, 0, geoms, bounds, 1000.0, 'x', -1.0, 100.0)
    assert t is not None and 59.9 < t <= 70.0
    moved = translate(mover, xoff=-t)
    assert moved.intersection(u_slot).area <= 0.1     # 落位零正面积重合
    # 无窗（实体墙，无槽）→ None
    wall = Polygon([[0.0, 0.0], [140.0, 0.0], [140.0, 50.0], [0.0, 50.0]])
    geoms2 = [mover, wall]
    assert polish._scan_to_clean(mover, 0, geoms2, [g.bounds for g in geoms2],
                                 1000.0, 'x', -1.0, 100.0) is None
    # 起点已净 → 0（远处片无涉）
    far = Polygon([[500.0, 0.0], [600.0, 0.0], [600.0, 50.0], [500.0, 50.0]])
    geoms3 = [mover, far]
    assert polish._scan_to_clean(mover, 0, geoms3, [g.bounds for g in geoms3],
                                 1000.0, 'x', -1.0, 100.0) == 0.0


def test_separate_escape_rects():
    """separate-escape（2026-10-06）：双侧受压条片在双 mover 最小分离全败后
    +x 扫描到全净位逃逸。夹具：地板左/天花板中均 exclude（禁其最小分离让路）、
    远右包络锚（封 −x 大位移的守卫②口径）、+y 落位阻挡（封天花板上方）——
    所有常规分离路径被守卫拒，唯一出路是 +x 楔口逃逸。"""
    pieces = {'g01_30': _piece('g01_30', 200, 150),
              'g02_30': _piece('g02_30', 160, 150, label='g02'),
              'g03_30': _piece('g03_30', 60, 110, label='g03'),
              'g04_30': _piece('g04_30', 100, 400, label='g04'),
              'g05_30': _piece('g05_30', 300, 100, label='g05')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 100, 245),
              _pl('g03_30', 0, 170, 145), _pl('g04_30', 0, 600, 0),
              _pl('g05_30', 0, 0, 500)]
    out, rep = polish_layout(placed, pieces, 1000.0,
                             exclude={'labels': ['g01', 'g02']})
    assert rep['before']['overlap_pairs'] == 2
    assert rep['after']['overlap_pairs'] == 0
    esc = [m for m in rep['moves'] if m['kind'] == 'separate-escape']
    assert len(esc) == 1 and esc[0]['pid'] == 'g03_30'
    assert '+x逃逸' in esc[0]['detail']
    dx = esc[0]['to']['translation'][0] - esc[0]['from']['translation'][0]
    assert 89.0 <= dx <= 91.0
    # exclude 片（地板/天花板）零移动；终态三方两两零正面积重合
    assert all(m['pid'] not in ('g01_30', 'g02_30') for m in rep['moves'])
    g = [_world(p['id'], pieces, p['rotation'], p['translation']) for p in out[:3]]
    assert g[0].intersection(g[1]).area <= 0.1
    assert g[0].intersection(g[2]).area <= 0.1
    assert g[1].intersection(g[2]).area <= 0.1


def _dent_pocket_layout():
    """夹具 B（2026-10-06）：平底地板 + 底边带凹兜的天花板（兜 x[225,445]、深
    14mm —— 凹兜是凹特征，对族 A 的 bbox 棱对齐候选完全不可见），5° 条片双侧
    受压且族 A/B 全败；唯一出路 = 0° 台阶 −x 逃逸入兜（逃逸窗 t∈[37,57]，
    窄于 20mm 粗扫步 —— 3069 g09_29 同构机制）。"""
    floor = [[-600.0, 0.0], [600.0, 0.0], [600.0, 30.0], [-600.0, 30.0]]
    ceil = [[-600.0, 66.0], [225.0, 66.0], [225.0, 80.0], [445.0, 80.0],
            [445.0, 66.0], [600.0, 66.0], [600.0, 1000.0], [-600.0, 1000.0]]

    def _pp(pid, label, poly):
        return {'pid': pid, 'label': label, 'size': 28, 'polygon': poly,
                'area_mm2': Polygon(poly).area, 'net_polygon': [],
                'internal_lines': [], 'notches': [], 'grain_line': None}

    pieces = {'g06_30': _pp('g06_30', 'g06', floor),
              'g07_30': _pp('g07_30', 'g07', ceil),
              'g08_30': _piece('g08_30', 200, 40, label='g08')}
    # 5° 条片世界 bbox 中心放 (382, 50)：0° 质心锚带恰为 y[30,70]（贴地板顶）
    import math as _m
    _r = _m.radians(5.0)
    ctr = (_m.cos(_r) * 100 - _m.sin(_r) * 20, _m.sin(_r) * 100 + _m.cos(_r) * 20)
    placed = [_pl('g06_30', 0, 0, 0), _pl('g07_30', 0, 0, 0),
              _pl('g08_30', 5, 382.0 - ctr[0], 50.0 - ctr[1])]
    return pieces, placed, 1000.0


def test_derotate_escape_dent_pocket():
    """derotate-escape（2026-10-06）：受压斜片 0° 台阶 −x 逃逸入凹兜 ——
    重合归零 + dev 5→0 + exclude 片零移动 + 确定性双跑全等。"""
    pieces, placed, gate = _dent_pocket_layout()
    out, rep = polish_layout(placed, pieces, gate, exclude={'labels': ['g06', 'g07']})
    assert rep['before']['overlap_pairs'] == 2
    assert rep['after']['overlap_pairs'] == 0
    assert _rotation_dev(out[2]['rotation']) == 0.0
    esc = [m for m in rep['moves'] if m['kind'] == 'derotate-escape']
    assert len(esc) == 1 and esc[0]['pid'] == 'g08_30'
    assert '−x逃逸' in esc[0]['detail']
    assert rep['escape_moves'] == 1
    assert all(m['pid'] not in ('g06_30', 'g07_30') for m in rep['moves'])
    out2, rep2 = polish_layout(placed, pieces, gate, exclude={'labels': ['g06', 'g07']})
    r1 = dict(rep); r1.pop('elapsed_sec')
    r2 = dict(rep2); r2.pop('elapsed_sec')
    assert out == out2 and r1 == r2


def test_escape_budget_off_restores_legacy_behavior(monkeypatch):
    """扫描预算置 0 = 逃逸兜底关闭 → 回到旧代码路径（夹具 B 保持受压 residual、
    无 escape move）—— 锁死「兜底只在预算内介入，关闭即旧行为」。"""
    monkeypatch.setattr(polish, 'ESCAPE_SCAN_BUDGET', 0)
    pieces, placed, gate = _dent_pocket_layout()
    out, rep = polish_layout(placed, pieces, gate, exclude={'labels': ['g06', 'g07']})
    assert rep['escape_moves'] == 0
    assert not any(m['kind'] in ('derotate-escape', 'separate-escape')
                   for m in rep['moves'])
    assert rep['after']['overlap_pairs'] == 2      # 受压保持（旧行为）
    assert out[2]['rotation'] == placed[2]['rotation']


# ------------------------------------------- 外层迭代至不动点（2026-10-06）

def _grid(rows, cols):
    """rows×cols 网格富夹具（性能测试同构缩小版）：相邻列 2mm 横叠 + 每 5 片
    10° 斜置 —— 单趟预算/门控（attach 3 轮帽、角度预算、②′ 脏区门）下跑不完
    的典型形态，多轮迭代显著收敛（8×8 实测：重合 21→2、Σ偏差 30°→0）。"""
    pieces, placed, gate = {}, [], 2000.0
    idx = 0
    for row in range(rows):
        y = row * 165.0
        for col in range(cols):
            pid = f'g{idx // 10 + 1:02d}_{28 + idx % 10}'
            pieces[pid] = _piece(pid, 100, 140, label=f'g{idx // 10 + 1:02d}')
            placed.append(_pl(pid, 10.0 if idx % 5 == 0 else 0.0,
                              col * 98.0, y))
            idx += 1
    return pieces, placed, gate


def test_multiround_converges_beyond_single_pass():
    """外层迭代严格优于单趟 + 四大不变量：moves 前缀 = 单趟全等（首轮等价
    独立单次调用）、宽度锚不蠕变（全循环累计 ≤ +0.5mm）、收敛态复跑零 move
    （真不动点）、attach/escape 计数与拼接 moves 自洽（UI 冒烟 S2h 同口径）。"""
    pieces, placed, gate = _grid(8, 8)
    _, r1 = polish_layout(placed, pieces, gate)
    outN, rN = polish_layout(placed, pieces, gate,
                             max_rounds=polish.POLISH_ROUNDS_MAX)
    assert r1['rounds'] == 1
    assert rN['rounds'] >= 2
    assert rN['moves'][:len(r1['moves'])] == r1['moves']
    assert rN['after']['overlap_pairs'] < r1['after']['overlap_pairs']
    assert rN['after']['rotation_dev_sum_deg'] < r1['after']['rotation_dev_sum_deg']
    assert (rN['after']['width_mm']
            <= rN['before']['width_mm'] + polish.WIDTH_TOL_MM + 1e-9)
    _, rR = polish_layout(outN, pieces, gate,
                          max_rounds=polish.POLISH_ROUNDS_MAX)
    assert rR['moves'] == []
    assert rN['attach_moves'] == sum(1 for m in rN['moves']
                                     if m['kind'] == 'attach')
    assert rN['escape_moves'] == sum(1 for m in rN['moves']
                                     if m['kind'].endswith('-escape'))


def test_multiround_determinism_double_run():
    """多轮同输入双跑全等（rounds 键入册；elapsed_sec 除外）。"""
    pieces, placed, gate = _grid(6, 6)
    o1, r1 = polish_layout(placed, pieces, gate,
                           max_rounds=polish.POLISH_ROUNDS_MAX)
    o2, r2 = polish_layout(placed, pieces, gate,
                           max_rounds=polish.POLISH_ROUNDS_MAX)
    r1.pop('elapsed_sec')
    r2.pop('elapsed_sec')
    assert o1 == o2 and r1 == r2


def test_polish_once_width_anchor_semantics():
    """守卫② 锚语义直测：width_anchor=None 自测本趟包络（历史行为，south 贴附
    move 放行）；锚收紧 2mm 后宽度中性 move 全拒（new_width > anchor+0.5）→
    零 move 返回输入原对象 —— 外层多轮冻结锚的防蠕变机制即建于此。"""
    pieces = {'g01_30': _piece('g01_30', 100, 160),
              'g02_30': _piece('g02_30', 100, 160, label='g02')}
    placed = [_pl('g01_30', 0, 0, 0), _pl('g02_30', 0, 0, 300)]
    o0, r0, wb = _polish_once(placed, pieces, 1000.0)
    assert r0['moves'] and wb == 100.0
    o1, r1, _ = _polish_once(placed, pieces, 1000.0, width_anchor=98.0)
    assert r1['moves'] == [] and o1 is placed


def _stub_report(width_before, width_after, moves):
    metrics = lambda w: {'overlap_pairs': 1, 'max_penetration_mm': 0.0,
                         'total_overlap_area_mm2': 1.0, 'rotated_pieces': 0,
                         'rotation_dev_sum_deg': 0.0, 'width_mm': w,
                         'density': 50.0}
    return {'before': metrics(width_before), 'after': metrics(width_after),
            'moves': moves, 'residual': [], 'excluded': [],
            'attach_moves': len(moves), 'escape_moves': 0}


def _make_stub(calls):
    """桩工厂：每次调用消费 calls 一项 (moves, wb, wa)，耗尽后重复末项；
    记录每次收到的 width_anchor 供锚穿线断言。"""
    state = {'i': 0, 'anchors': []}

    def _stub(placed, pieces_by_id, gate_mm, *, exclude=None, compact=False,
              width_anchor=None):
        moves, wb, wa = calls[min(state['i'], len(calls) - 1)]
        state['i'] += 1
        state['anchors'].append(width_anchor)
        out = [dict(p) for p in placed] if moves else placed
        return out, _stub_report(wb, wa, moves), wb

    return _stub, state


def test_wrapper_loop_contract(monkeypatch):
    """外层循环契约（桩测轮间机制）：cap 钳制 / churn 停机不回滚 / 零 move
    停机 / 首轮零 move 原对象 / 锚首轮自测次轮冻结 / 报告组合 / 非法
    max_rounds fail-fast。"""
    mv = [{'index': 0, 'pid': 'g01_30', 'kind': 'attach', 'from': {},
           'to': {}, 'detail': 'stub'}]
    pieces = {'g01_30': _piece('g01_30', 100, 160)}
    placed = [_pl('g01_30', 0, 0, 0)]

    # (b) cap：每轮 1 move + width 严格改进 → 跑满 cap（50 钳到 POLISH_ROUNDS_MAX）
    stub, state = _make_stub([(mv, 1000.0, 999.0)])
    monkeypatch.setattr(polish, '_polish_once', stub)
    _, rep = polish_layout(placed, pieces, 1000.0, max_rounds=50)
    assert rep['rounds'] == polish.POLISH_ROUNDS_MAX
    assert len(rep['moves']) == polish.POLISH_ROUNDS_MAX
    assert state['anchors'][0] is None                    # 首轮自测
    assert all(a == 1000.0 for a in state['anchors'][1:])  # 次轮起冻结

    # (c) churn：有 move 但四项核心指标无一项严格改进 → 停在 rounds=1（move
    # 保留不回滚 —— 逐 move 守卫已保证不劣化）
    stub, _ = _make_stub([(mv, 1000.0, 1000.0)])
    monkeypatch.setattr(polish, '_polish_once', stub)
    _, rep = polish_layout(placed, pieces, 1000.0, max_rounds=8)
    assert rep['rounds'] == 1 and len(rep['moves']) == 1

    # (a) 第 2 轮零 move：rounds=2、moves 只含首轮、计数累计
    stub, _ = _make_stub([(mv, 1000.0, 999.0), ([], 999.0, 999.0)])
    monkeypatch.setattr(polish, '_polish_once', stub)
    _, rep = polish_layout(placed, pieces, 1000.0, max_rounds=8)
    assert rep['rounds'] == 2 and len(rep['moves']) == 1
    assert rep['attach_moves'] == 1 and rep['escape_moves'] == 0

    # 首轮零 move：输入 list 原对象（逐字节不变量）
    stub, _ = _make_stub([([], 1000.0, 1000.0)])
    monkeypatch.setattr(polish, '_polish_once', stub)
    out, rep = polish_layout(placed, pieces, 1000.0, max_rounds=8)
    assert out is placed and rep['moves'] == [] and rep['rounds'] == 1

    # 报告组合：before = 首轮起跑态、after = 末轮终态
    stub, _ = _make_stub([(mv, 1000.0, 999.0), ([], 999.0, 998.5)])
    monkeypatch.setattr(polish, '_polish_once', stub)
    _, rep = polish_layout(placed, pieces, 1000.0, max_rounds=8)
    assert rep['before']['width_mm'] == 1000.0
    assert rep['after']['width_mm'] == 998.5

    # 非法 max_rounds：fail-fast（web 层 400 前置，引擎兜底）
    for bad in (0, -1, 2.5, '3', True, None):
        with pytest.raises(PolishError, match='max_rounds'):
            polish_layout(placed, pieces, 1000.0, max_rounds=bad)


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
