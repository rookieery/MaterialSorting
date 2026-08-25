"""US-001 prefix 核心构造模块测试（资格码 + PS 组合片 + 展开契约）。

覆盖（tasks/prd-prefix-head-set.md US-001 验收标准）：
1. ``eligible_sizes``：P2 资格规则逐码校验（两 g 码 demand 均 ==2；总量 2 或
   6 片不合格），0/1/2/3/缺码五态 + 5336 g02/g03 同构对拍（{32,33,34,35,38}，
   sizes 过滤缺一不可 —— quantities 含 37/39/40 demand 2+2 但不在所排尺码）；
2. ``pick_prefix_size``：seeded 随机确定性（crc32 派生 + 排序归一，勿用全局
   random/hash()）、输入序无关、空集合 PrefixError（文案指路数量矩阵）；
3. ``build_prefix_plan``：4 片（前×2+后×2 同码）interleave 竖排贴靠形态、
   **rot180 负坐标框架记账**（tr=(xoff−b0, yoff−b1)，重构几何与放置几何逐点
   一致 —— P0 曾因缺此补偿致片侧移并排）、守卫（order ValueError / 副本不齐
   2+2 / 不同码 / 竖排超高 min(gate,1910) PrefixError）；
4. 展开契约黄金用例：组合片 rot=0 与 rot=180 两组手算对拍（复用
   ``waist_band.expand_placements``，offset 减号权威式）；构造 chunk 包络断言
   union(成员原轮廓@展开位) ⊆ composite@主解位 ⊕ d_g（容差 0.5mm）；展开后
   恰 4 条成员 placement（无 PS_ 泄漏）；
5. 确定性：构造无 RNG，同输入两跑 ``to_dict()`` JSON 相等；
6. 分层纯度：模块级不 import web/cli（AST 守卫，镜像 test_waist_band 套路）。

合成夹具：5336 g02/g03 前后幅同构 L 形/阶梯形（非中心对称 —— rot180 框架坑
对拍敏感；1153×484 / 1155×360 两大片量级），d_g=2.0 与 5336 per_type 同值。
"""
from __future__ import annotations

import ast
import json
import random
import zlib
from pathlib import Path

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from materialsorting.nesting_engine import prefix
from materialsorting.nesting_engine import waist_band as wb
from materialsorting.nesting_engine.sparrow_baseline import _transform_polygon
from materialsorting.nesting_engine.sparrow_experiments import erode_polygon
from materialsorting.nesting_engine.prefix import (
    GAP_EPS_MM,
    PREFIX_MEMBER_COUNT,
    PREFIX_ORIENTATIONS,
    PREFIX_PID_PREFIX,
    PrefixError,
    build_prefix_plan,
    eligible_sizes,
    pick_prefix_size,
    prefix_seed_for,
)


# ------------------------------------------------------------- 合成夹具

def _panel_piece(pid, label, size, pts):
    """合成 v2 schema 裁片（与 test_waist_band._rect_piece 同构，多边形任意）。"""
    return {
        'pid': pid, 'label': label, 'size': size, 'polygon': pts,
        'area_mm2': Polygon(pts).area,
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
    }


def _front_pts(w=600.0, h=470.0):
    """前幅 L 形（5336 g02 1153×484 同量级缩放；右上缺角 → 非中心对称）。"""
    return [[0.0, 0.0], [w, 0.0], [w, h * 0.55], [w * 0.45, h * 0.55],
            [w * 0.45, h], [0.0, h]]


def _back_pts(w=640.0, h=350.0):
    """后幅阶梯形（5336 g03 1155×360 同量级缩放；左下内收 → 非中心对称）。"""
    return [[0.0, 0.0], [w, 0.0], [w, h], [w * 0.3, h],
            [w * 0.3, h * 0.4], [0.0, h * 0.4]]


def _prefix_ctx(sizes=(34,), d_g=2.0, demand=2, front='g02', back='g03',
                h_mul=1.0):
    """5336 g02/g03 前后幅同构上下文（每码各 1 pid、demand=2 = 2+2）。

    返回 ``(pid_meta, pieces_by_id)``：pid_meta.polygon 为 erode(d_g) 后轮廓
    （build_pid_meta 同口径）；pieces_by_id 存原始轮廓（union/包络断言口径）。
    h_mul 等比放大高度（竖排超高守卫用例：4 片堆叠 > 1910）。
    """
    pieces_by_id = {}
    pid_meta = {}
    for s in sizes:
        for label, pts in ((front, _front_pts()), (back, _back_pts())):
            if h_mul != 1.0:
                pts = [[x, y * h_mul] for x, y in pts]
            pid = f'{label}_{s}'
            p = _panel_piece(pid, label, s, pts)
            pieces_by_id[pid] = p
            poly = erode_polygon(p['polygon'], d_g) if d_g > 0 else p['polygon']
            pid_meta[pid] = {
                'size': s, 'color': '#000000', 'polygon': poly,
                'area_mm2': p['area_mm2'], 'label': label, 'demand': demand,
                'net_polygon': [], 'internal_lines': [], 'notches': [],
                'grain_line': None,
            }
    return pid_meta, pieces_by_id


def _build34(pid_meta, pieces, **kw):
    kw.setdefault('gate_nest', 1910.0)
    return build_prefix_plan(pid_meta, pieces, front_pid='g02_34',
                             back_pid='g03_34', d_g=2.0, **kw)


# ------------------------------------------------------- eligible_sizes

# 5336 g02/g03 数量行同构（sizes 只排 [31..36,38]，quantities 含 30/37/39/40）。
_Q5336_ROW = {'30': 2, '31': 1, '32': 2, '33': 2, '34': 2, '35': 2, '36': 3,
              '37': 2, '38': 2, '39': 2, '40': 2}
_Q5336 = {'g02': dict(_Q5336_ROW), 'g03': dict(_Q5336_ROW),
          'g04': {'34': 2, '35': 2}}                      # 无关 g 码不干扰
_SIZES5336 = [31, 32, 33, 34, 35, 36, 38]


def test_eligible_sizes_5336_parity():
    """5336 同构对拍：g02/g03 → {32,33,34,35,38}（31=1+1、36=3+3 不合格；
    37/39/40 demand 2+2 但不在所排尺码 → 不算资格）。"""
    assert eligible_sizes(_Q5336, 'g02', 'g03', sizes=_SIZES5336) \
        == [32, 33, 34, 35, 38]


def test_eligible_sizes_five_states():
    """五态覆盖：demand 0/1/2/3 + 缺码（仅 ==2 双合格）。"""
    q = {'g02': {'30': 0, '31': 1, '32': 2, '33': 3},      # front 四态
         'g03': {'30': 2, '31': 2, '32': 2, '33': 2, '34': 2}}   # 34 缺 front 码
    assert eligible_sizes(q, 'g02', 'g03') == [32]


def test_eligible_sizes_empty_and_null_quantities():
    """quantities=None / g 码不在矩阵 / sizes 过滤淘汰唯一资格码 → 空（FR-9 早退）。"""
    assert eligible_sizes(None, 'g02', 'g03') == []
    assert eligible_sizes({'g05': {'34': 2}}, 'g02', 'g03') == []
    assert eligible_sizes({'g02': {'34': 2}, 'g03': {'34': 2}},
                          'g02', 'g03', sizes=[31, 32]) == []


# ------------------------------------------------------ pick_prefix_size

def test_prefix_seed_crc32_derivation():
    """seed 派生口径锁定：zlib.crc32(f'{seed}|{front}|{back}')，勿用 hash()。"""
    assert prefix_seed_for(0, 'g02', 'g03') == zlib.crc32(b'0|g02|g03')
    assert prefix_seed_for(1, 'g02', 'g03') == zlib.crc32(b'1|g02|g03')
    assert prefix_seed_for(0, 'g02', 'g03') != prefix_seed_for(0, 'g02', 'g04')


def test_pick_prefix_size_seeded_deterministic():
    """同 seed 两跑同码 + 输入序无关（集合/乱序列表归一）+ 手算对拍。"""
    elig = [32, 33, 34, 35, 38]
    for seed in range(8):
        a = pick_prefix_size(elig, seed=seed, front='g02', back='g03')
        b = pick_prefix_size(set(reversed(elig)), seed=seed,
                             front='g02', back='g03')
        want = random.Random(prefix_seed_for(seed, 'g02', 'g03')).choice(
            sorted(elig))
        assert a == b == want and a in elig


def test_pick_prefix_size_empty_raises():
    """空集合 → PrefixError，文案指路数量矩阵（US-003 复用）。"""
    with pytest.raises(PrefixError, match=r'2\+2'):
        pick_prefix_size([], seed=0, front='g02', back='g03')


# --------------------------------------------------- build_prefix_plan

def test_build_prefix_plan_form_and_rot180_accounting():
    """形态 + rot180 记账权威式：tr 复现放置几何（P0 负坐标坑锁死）。

    记账对拍：以成员 (pid, rotation, translation) 直接 _transform_pid_meta
    polygon 重构几何 —— 若实现漏掉 tr=(xoff−b0, yoff−b1) 补偿，rot180 成员
    几何整体偏移 (b0,b1)，贴触缝隙与 bbox 立即爆掉。
    """
    pid_meta, pieces = _prefix_ctx()
    chunk, gaps, holes = _build34(pid_meta, pieces)

    # 4 成员 interleave 序（前后前后）+ rot 交替 0/180（头尾相对）
    assert [m['pid'] for m in chunk.members] \
        == ['g02_34', 'g03_34', 'g02_34', 'g03_34']
    assert [m['rotation'] for m in chunk.members] == [0.0, 180.0, 0.0, 180.0]
    assert chunk.pid == f'{PREFIX_PID_PREFIX}g02+g03@34'
    assert chunk.n_members == PREFIX_MEMBER_COUNT == 4
    assert chunk.d_g == 2.0
    assert list(PREFIX_ORIENTATIONS) == [0.0, 180.0]           # FR-5 决策③

    # 记账权威式重构放置几何（eroded 碰撞口径）
    geoms = [Polygon(_transform_polygon(pid_meta[m['pid']]['polygon'],
                                        m['rotation'], m['translation']))
             for m in chunk.members]
    for i in range(3):
        assert geoms[i].distance(geoms[i + 1]) <= GAP_EPS_MM, i   # 贴触
    assert len(gaps) == 3 and max(gaps) <= GAP_EPS_MM

    # 竖排形态：高 > 宽（沿门幅纵向堆叠，非侧移并排）；成员 y 区间相邻衔接
    assert chunk.bbox['height_mm'] > chunk.bbox['width_mm']
    for i in range(3):
        bot = max(geoms[i].bounds[1], geoms[i + 1].bounds[1])
        top = min(geoms[i].bounds[3], geoms[i + 1].bounds[3])
        assert top - bot > -0.5, i        # 相邻 y 区间衔接（咬合或齐平，无纵向断开）
    # 重构几何（eroded）⊆ 原始轮廓@同位（erode 只缩不涨）且 bbox 差 ≤ 2·d_g/边
    u = unary_union(geoms)
    raw = unary_union([Polygon(_transform_polygon(
        pieces[m['pid']]['polygon'], m['rotation'], m['translation']))
        for m in chunk.members])
    assert u.within(raw.buffer(1e-6))
    assert raw.bounds[2] - raw.bounds[0] - (u.bounds[2] - u.bounds[0]) \
        <= 4 * chunk.d_g + 0.5

    # 原始轮廓 union bbox 同口径（chunk.offset/bbox 由原始轮廓决定）
    assert raw.bounds == pytest.approx(
        (chunk.offset[0], chunk.offset[1],
         chunk.offset[0] + chunk.bbox['width_mm'],
         chunk.offset[1] + chunk.bbox['height_mm']), abs=0.5)

    # fill 口径：成员原面积和 / union bbox 面积（实际占用，非全幅）
    area_sum = sum(pid_meta[m['pid']]['area_mm2'] for m in chunk.members)
    assert chunk.fill_pct == pytest.approx(
        area_sum / (chunk.bbox['width_mm'] * chunk.bbox['height_mm']) * 100.0,
        abs=1e-6)


def test_build_prefix_plan_guards():
    """守卫：order ValueError / 副本不齐 2+2（1、3、pid 缺失）/ 不同码 /
    竖排超高（min(gate_nest,1910)，不静默截断）。"""
    pid_meta, pieces = _prefix_ctx()
    with pytest.raises(ValueError, match='order'):
        _build34(pid_meta, pieces, order='weave')

    for pid, dem in (('g02_34', 1), ('g03_34', 3)):
        m = dict(pid_meta)
        m[pid] = {**pid_meta[pid], 'demand': dem}
        with pytest.raises(PrefixError, match=r'2\+2'):
            _build34(m, pieces)
    with pytest.raises(PrefixError, match=r'2\+2'):
        build_prefix_plan(pid_meta, pieces, front_pid='g02_99',
                          back_pid='g03_34', d_g=2.0, gate_nest=1910.0)

    m2, p2 = _prefix_ctx(sizes=(34, 35))
    with pytest.raises(PrefixError, match='不同码'):
        build_prefix_plan(m2, p2, front_pid='g02_34', back_pid='g03_35',
                          d_g=2.0, gate_nest=1910.0)

    # 竖排超高：gate_nest 直接钳（800 < 堆叠高）与 gate_nest>1910 钳 PLOT_SAFE
    with pytest.raises(PrefixError, match='竖排高'):
        _build34(pid_meta, pieces, gate_nest=800.0)
    tall_meta, tall_pieces = _prefix_ctx(h_mul=1.6)    # 4 片堆叠 > 1910
    with pytest.raises(PrefixError, match='竖排高'):
        _build34(tall_meta, tall_pieces, gate_nest=3000.0)


def test_build_prefix_plan_deterministic_to_dict():
    """构造无 RNG：同输入两跑 to_dict JSON 相等（含 gaps/holes）。"""
    pid_meta, pieces = _prefix_ctx()
    c1, g1, h1 = _build34(pid_meta, pieces)
    c2, g2, h2 = _build34(pid_meta, pieces)
    assert json.dumps(c1.to_dict(), sort_keys=True) \
        == json.dumps(c2.to_dict(), sort_keys=True)
    assert g1 == g2 and h1 == h2


def test_interleave_order_no_closed_cavities():
    """FR-10 定稿依据：interleave 交错序封闭腔 0（缺口全开放，无 spyrrow 死区）；
    grouped 备档在同类几何下产生封闭腔（5336 真实数据 P0 实测 2，合成同构 1）。"""
    pid_meta, pieces = _prefix_ctx()
    _c, _g, holes_inter = _build34(pid_meta, pieces, order='interleave')
    _c2, _g2, holes_grouped = _build34(pid_meta, pieces, order='grouped')
    assert holes_inter == 0
    assert holes_grouped >= 1


# ------------------------------------------------- 展开契约（黄金用例）

def _hand_ps_chunk():
    """黄金用例手造 PS chunk：offset=(10,20) 非零（对拍「减号」错误最敏感）。"""
    return wb.BandChunk(
        pid='PS_g02+g03@34', label='g02',
        polygon=[[0.0, 0.0], [120.0, 0.0], [120.0, 200.0], [0.0, 200.0]],
        offset=(10.0, 20.0),
        members=[
            {'pid': 'g02_34', 'rotation': 0.0, 'translation': [15.0, 25.0]},
            {'pid': 'g03_34', 'rotation': 180.0, 'translation': [115.0, 125.0]},
        ],
        fill_pct=80.0, bbox={'width_mm': 120.0, 'height_mm': 200.0},
        seed=0, d_g=2.0, tol_g=0.0,
    )


def test_expand_golden_rot0_hand_computed():
    """rot=0 手算对拍：rot_f = m.rot + 0；tr_f = R(0)·(m.tr − offset) + c.tr。

    成员 1：(15−10, 25−20)+(100,50) = (105,55)；成员 2：(115−10, 125−20)+
    (100,50) = (205,155)。若 offset 误用加号，tr_f 会变 (125,95)/(225,295)。
    """
    out = wb.expand_placements(_hand_ps_chunk(), 0.0, (100.0, 50.0))
    assert len(out) == 2
    assert out[0]['id'] == 'g02_34' and out[0]['rotation'] == 0.0
    assert out[0]['translation'] == pytest.approx([105.0, 55.0], abs=1e-9)
    assert out[1]['id'] == 'g03_34' and out[1]['rotation'] == 180.0
    assert out[1]['translation'] == pytest.approx([205.0, 155.0], abs=1e-9)


def test_expand_golden_rot180_hand_computed():
    """rot=180 手算对拍（FR-5 决策③：orientations 放开 [0.,180.] 后必须覆盖）。

    R(180°) = diag(−1,−1)。成员 1：−(5,5)+(1000,500) = (995,495)，rot_f=180；
    成员 2：−(105,105)+(1000,500) = (895,395)，rot_f=(180+180)%360=0。
    """
    out = wb.expand_placements(_hand_ps_chunk(), 180.0, (1000.0, 500.0))
    assert out[0]['id'] == 'g02_34'
    assert out[0]['rotation'] == 180.0                      # 0 + 180
    assert out[0]['translation'] == pytest.approx([995.0, 495.0], abs=1e-9)
    assert out[1]['id'] == 'g03_34'
    assert out[1]['rotation'] == 0.0                        # (180+180) % 360
    assert out[1]['translation'] == pytest.approx([895.0, 395.0], abs=1e-9)


def test_constructed_chunk_expand_envelope_both_orientations():
    """构造 chunk 展开契约：恰 4 条成员 placement + 包络断言（两朝向）。

    union(成员原轮廓@展开位) ⊆ composite@主解位 ⊕ d_g（容差 0.5mm）—— c.rot
    取 PREFIX_ORIENTATIONS 两态；展开 id 全为成员 pid（无 PS_ 泄漏）。
    """
    pid_meta, pieces = _prefix_ctx()
    chunk, _gaps, _holes = _build34(pid_meta, pieces)
    for c_rot, c_tr in [(0.0, (700.0, 300.0)), (180.0, (2000.0, 1500.0))]:
        expanded = wb.expand_placements(chunk, c_rot, c_tr)
        assert len(expanded) == 4                           # 恰 4 条（2+2）
        assert all(e['id'] in pid_meta for e in expanded)   # 无 PS_ 泄漏
        comp_world = Polygon(_transform_polygon(chunk.polygon, c_rot, c_tr))
        member_union = unary_union([
            Polygon(_transform_polygon(
                pieces[e['id']]['polygon'], e['rotation'], e['translation']))
            for e in expanded
        ])
        # ⊕ d_g，容差 0.5mm。join_style=mitre：d_g=2（5336 前后幅 per_type）时圆角
        # join 在 90° 凸角处漏 d_g·(√2−1)≈0.83mm（erode⊕dilate = opening ⊂ 原形的
        # 数学性质，与单片 erode_polygon 同源），mitre 保真实偏移曲线 ⇒ 断言严格。
        padded = comp_world.buffer(chunk.d_g + 0.5, join_style=2)
        assert padded.contains(member_union), (c_rot, c_tr)


# --------------------------------------------------------------- 分层纯度

def test_module_layering_purity():
    """分层未反向：prefix.py 模块级 import 只 stdlib + shapely + 向下/同层
    （nesting_bounds / nesting_engine 兄弟 / paths），禁 import web/cli
    （AST 守卫，镜像 test_waist_band 套路）。"""
    src = Path(prefix.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'argparse', 'json', 'os', 'pathlib', 'random',
               'sys', 'zlib', 'shapely', 'materialsorting',
               'nesting_bounds', 'nesting_engine'}
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert not mod.startswith('materialsorting.web'), \
                '模块级禁止 import web（分层单向）'
            assert not mod.startswith('materialsorting.cli'), \
                '模块级禁止 import cli（分层单向）'
            # 相对 import：level=1 解析到本包兄弟模块（constraints/waist_band 等），
            # level=2 只到父包 materialsorting（paths）
            names = {'nesting_engine'} if node.level == 1 \
                else ({'materialsorting'} if node.level >= 2
                      else {mod.split('.')[0]})
        else:
            continue
        assert names <= allowed, sorted(names - allowed)
    # 源级哨兵：任何 web/cli 引用（含函数内延迟 import）都不允许
    assert 'materialsorting.web' not in src and 'materialsorting.cli' not in src
    assert 'from ..web' not in src and 'from .web' not in src
    assert 'from ..cli' not in src and 'from .cli' not in src
