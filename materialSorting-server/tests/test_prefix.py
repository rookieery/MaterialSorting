"""US-001 prefix 核心构造模块测试（资格码 + PS 组合片 + 展开契约）+ US-002
段置换钉位 / 驱逐重插测试。

覆盖（tasks/prd-prefix-head-set.md US-001/US-002 验收标准）：
1. ``eligible_sizes``：P2 资格规则逐码校验（两 g 码 demand 均 ==2；总量 2 或
   6 片不合格），0/1/2/3/缺码五态 + 5336 g02/g03 同构对拍（{32,33,34,35,38}，
   sizes 过滤缺一不可 —— quantities 含 37/39/40 demand 2+2 但不在所排尺码）；
2. ``pick_prefix_size``：seeded 随机确定性（crc32 派生 + 排序归一，勿用全局
   random/hash()）、输入序无关、空集合 PrefixError（文案指路数量矩阵）；
3. ``build_prefix_plan``：4 片（前×2+后×2 同码）interleave 竖排贴靠形态、
   **rot180 负坐标框架记账**（tr=(xoff−b0, yoff−b1)，重构几何与放置几何逐点
   一致 —— P0 曾因缺此补偿致片侧移并排）、守卫（order ValueError / 副本不齐
   2+2 / 不同码 / 竖排超高 gate_nest PrefixError）；
4. 展开契约黄金用例：组合片 rot=0 与 rot=180 两组手算对拍（复用
   ``waist_band.expand_placements``，offset 减号权威式）；构造 chunk 包络断言
   union(成员原轮廓@展开位) ⊆ composite@主解位 ⊕ d_g（容差 0.5mm）；展开后
   恰 4 条成员 placement（无 PS_ 泄漏）；
5. 确定性：构造无 RNG，同输入两跑 ``to_dict()`` JSON 相等；
6. 分层纯度：模块级不 import web/cli（AST 守卫，镜像 test_waist_band 套路）；
7. ``permute_pin``（US-002）：三守卫参数锁死（skip_at_head=6.0 / eps=5.0 /
   flex=400.0）+ 头部跳过（P0 常态锚定零触发）/ c2 柔性选线最小化 straddler /
   eps 防贴墙片误判 / A·C·B 刚体重排 x 独占 y 不动 + 构造性中部布局（组合片
   min_x ≤ 6mm、总长不增）；
8. ``reinsert_evicted``（US-002）：三优先序各有单测（①组平移回位 ②+x 微调
   梯 ③自右滑触 + 尾端贴触追加兜底）+ 尾端追加 width_growth 超阈值 warn +
   确定性（面积降序、无 RNG）；
9. ``pin_prefix_layout`` 终检编排（US-002/US-003 单点）：构造性用例（min_x
   ≤ 6mm、validate 通过不回退、new_L ≤ L+0.5mm、入参不被修改）+ P0 回归
   （4 头部位姿全部跳过、PIN ≡ FREE 密度差 0.00pt）+ 复检失败回退置换前布局；
10. **选码搜索（顶部异码补片，2026-09-02 prd-prefix-extra-piece）**：
    ``select_prefix_plan`` 近满幅联合几何搜索 —— 最优拟合（矩形竖排夹具 H
    精确手算，多可行取 H 最大者）、候选池资格（demand<1/非数字码不入池、
    B==A 搜索层排除，泄漏即夺魁的可观察证伪）、平手确定性裁决（L 形同构两
    码全组合 H 恒等 ⇒ (A 升序, front 先, B 升序, rot0 先)）+ 双跑 to_dict/
    info 全等且与 seed 无关、兜底与现行 pick+build 逐字节一致（fallback=True）、
    补片 rot180 记账权威式 + 5 片两朝向展开包络、补片直调守卫（demand<1/
    同码/非前后幅/竖排超高）、5 成员展开黄金用例（offset 减号手算 rot0/180）。

合成夹具：5336 g02/g03 前后幅同构 L 形/阶梯形（非中心对称 —— rot180 框架坑
对拍敏感；1153×484 / 1155×360 两大片量级），d_g=2.0 与 5336 per_type 同值；
置换用例以矩形填充片 + 真实构造 chunk 组版（d=0 填充片 erode==raw ⇒ bbox
不相交 ⇔ 布局合法，组归属手算可验）；选码搜索用矩形竖排夹具（同宽 ⇒ 候选
x 全塌缩 {0} ⇒ H = Σ高 精确可手算，d_g=0 ⇒ erode==raw）。
"""
from __future__ import annotations

import ast
import inspect
import json
import logging
import random
import zlib
from pathlib import Path

import pytest
from shapely.affinity import translate
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from materialsorting.nesting_engine import prefix
from materialsorting.nesting_engine import waist_band as wb
from materialsorting.nesting_engine.sparrow_baseline import _transform_polygon
from materialsorting.nesting_engine.sparrow_experiments import erode_polygon
from materialsorting.nesting_engine.prefix import (
    EXTRA_ROT_CANDIDATES,
    GAP_EPS_MM,
    PIN_CUT_FLEX_MM,
    PIN_NUDGE_LADDER_MM,
    PIN_SKIP_AT_HEAD_MM,
    PIN_STRADDLER_EPS_MM,
    PIN_WIDTH_GROWTH_WARN_MM,
    PREFIX_GATE_MARGIN_MM,
    PREFIX_MEMBER_COUNT,
    PREFIX_ORIENTATIONS,
    PREFIX_PID_PREFIX,
    PrefixError,
    build_prefix_plan,
    eligible_sizes,
    permute_pin,
    pick_prefix_size,
    pin_prefix_layout,
    prefix_seed_for,
    reinsert_evicted,
    select_prefix_plan,
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
    h_mul 等比放大高度（竖排超高守卫用例：4 片堆叠 ≈2333 > 门幅 1980）。
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
    kw.setdefault('gate_nest', 1980.0)
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
    竖排超高（gate_nest，不静默截断）。"""
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
                          back_pid='g03_34', d_g=2.0, gate_nest=1980.0)

    m2, p2 = _prefix_ctx(sizes=(34, 35))
    with pytest.raises(PrefixError, match='不同码'):
        build_prefix_plan(m2, p2, front_pid='g02_34', back_pid='g03_35',
                          d_g=2.0, gate_nest=1980.0)

    # 竖排超高：gate_nest=800 < 堆叠高直接拒；2026-08-28 起不再钳 1910 ——
    # 超高构造（堆叠 ≈2333）在门幅 1980 仍拒，但 gate_nest=3000 放行（旧口径必拒）
    with pytest.raises(PrefixError, match='竖排高'):
        _build34(pid_meta, pieces, gate_nest=800.0)
    tall_meta, tall_pieces = _prefix_ctx(h_mul=1.6)    # 4 片堆叠 ≈2333
    with pytest.raises(PrefixError, match='竖排高'):
        _build34(tall_meta, tall_pieces, gate_nest=1980.0)
    chunk_tall, _gaps, _holes = _build34(tall_meta, tall_pieces, gate_nest=3000.0)
    assert 1980.0 < chunk_tall.bbox['height_mm'] <= 3000.0   # 无 1910 钳制


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
    allowed = {'__future__', 'argparse', 'json', 'logging', 'os', 'pathlib',
               'random', 'sys', 'zlib', 'shapely', 'materialsorting',
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


# --------------------------------------- US-002 段置换钉位 + 驱逐重插

GATE = 1980.0   # 2026-08-28 起：输入幅宽 = 实际幅宽（无 1910 钳制）


def _filler(pid, x0, y0, x1, y1):
    """矩形填充片（**局部轮廓** + 绝对 translation —— 与 intermediate pid 同
    口径：polygon 归一原点，placement 施放）。返回 (placement, pid_meta 条目,
    piece 条目)。"""
    w, h = x1 - x0, y1 - y0
    poly = [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]]
    area = w * h
    return (
        {'id': pid, 'rotation': 0.0, 'translation': [x0, y0]},
        {'size': 34, 'color': '#000', 'polygon': poly, 'area_mm2': area,
         'label': pid.split('_')[0], 'demand': 1, 'net_polygon': [],
         'internal_lines': [], 'notches': [], 'grain_line': None},
        {'pid': pid, 'label': pid.split('_')[0], 'size': 34, 'polygon': poly,
         'area_mm2': area, 'net_polygon': [], 'internal_lines': [],
         'notches': [], 'grain_line': None},
    )


def _rect_ctx(rects):
    """矩形布局夹具：``[(pid, x0, y0, x1, y1)]`` → (placements, geoms_raw,
    geoms_eroded, pid_meta, pieces_by_id)。d=0 ⇒ erode == raw ⇒ bbox 两两不相交
    ⇔ 布局合法（组归属 / 组平移量全可手算）。"""
    placements, geoms = [], []
    pid_meta, pieces_by_id = {}, {}
    for pid, x0, y0, x1, y1 in rects:
        placement, meta, piece = _filler(pid, x0, y0, x1, y1)
        placements.append(placement)
        geoms.append(box(x0, y0, x1, y1))
        pid_meta[pid] = meta
        pieces_by_id[pid] = piece
    return placements, geoms, list(geoms), pid_meta, pieces_by_id


def _members_rects(x0, y_top=1900.0):
    """4 成员矩形堆叠（comp_world bbox = [x0, x0+600] × [800, y_top]）。"""
    h = (y_top - 800.0) / 4.0
    return [(f'g02_34#{k}', x0, 800.0 + k * h, x0 + 600.0, 800.0 + (k + 1) * h)
            for k in range(4)]


def _width_of(pls, pid_meta, pieces_by_id):
    """原始轮廓 bbox 总长（raw-width 口径：max_x − min(min_x, 0)）。"""
    geoms = [prefix._world_raw_geom(p, pid_meta, pieces_by_id) for p in pls]
    return max(g.bounds[2] for g in geoms) - min(min(g.bounds[0] for g in geoms), 0.0)


# -------------------------------------------------- permute_pin 守卫与分组


def test_permute_pin_guard_params_locked():
    """AC#1：三守卫参数 + 微调梯锁死（P0 灾难 −17.72pt 三因标定值，
    inspect 签名缺省 == 模块常量）。"""
    sig = inspect.signature(permute_pin)
    assert sig.parameters['skip_at_head'].default == PIN_SKIP_AT_HEAD_MM == 6.0
    assert sig.parameters['eps'].default == PIN_STRADDLER_EPS_MM == 5.0
    assert sig.parameters['flex'].default == PIN_CUT_FLEX_MM == 400.0
    assert PIN_NUDGE_LADDER_MM == (0.0, 1.0, 5.0, 10.0, 20.0, 50.0, 100.0,
                                   200.0, 300.0)
    # stats 结构（跳过 / 置换两路）恒含 AC 要求字段
    pls, gr, ge, _pm, _pb = _rect_ctx(
        _members_rects(0.2) + [('f_b', 700.0, 0.0, 1200.0, 790.0)])
    _out, _sh, st = permute_pin(pls, gr, ge, box(0.2, 800, 600.2, 1900), [0, 1, 2, 3])
    assert st['skipped'] is True
    assert {'skipped', 'nA', 'nC', 'nB', 'n_evicted'} <= set(st)
    assert (st['nA'], st['nC'], st['nB'], st['n_evicted']) == (0, 0, 0, 0)


def test_permute_pin_skip_at_head_short_circuit():
    """skip_at_head=6.0 守卫：a ≤ 6 整体跳过零触碰（P0 常态锚定路径，布局
    逐字节不变）；a = 6.5 触发置换钉到 0。"""
    # a=0.2：跳过 + 就地零修改
    pls, gr, ge, _pm, _pb = _rect_ctx(
        _members_rects(0.2) + [('f_b', 700.0, 0.0, 1200.0, 790.0)])
    snap = [dict(p, translation=list(p['translation'])) for p in pls]
    gsnap = [g.bounds for g in gr]
    out, shift, st = permute_pin(pls, gr, ge, box(0.2, 800, 600.2, 1900), [0, 1, 2, 3])
    assert st['skipped'] is True and shift == {}
    assert out is pls and pls == snap and [g.bounds for g in gr] == gsnap
    # a=6.5 > 6：触发置换，成员钉到 min_x=0
    pls2, gr2, ge2, _pm2, _pb2 = _rect_ctx(
        _members_rects(6.5) + [('f_b', 700.0, 0.0, 1200.0, 790.0)])
    _out2, _sh2, st2 = permute_pin(pls2, gr2, ge2, box(6.5, 800, 606.5, 1900),
                                   [0, 1, 2, 3])
    assert st2['skipped'] is False
    assert min(gr2[i].bounds[0] for i in range(4)) == pytest.approx(0.0, abs=1e-9)


def test_permute_pin_mid_layout_regroup():
    """构造性中部布局：A(成员+a1)/C(c1)/B(b1) 刚体重排 + straddler(s1) 驱逐。

    手算（comp [2000,2600]，唯一 c2 候选 b0=2600 —— s1.x2=3020 > b0+flex）：
    A=−2000 → comp[0,600] a1[50,500]；C 紧随 → c1[600,2500]；B 紧随 →
    b1[2500,3100]；总长 3700 → 3100（段间隙压缩，总长不增）；y 全程不动。
    """
    pls, gr, ge, _pm, _pb = _rect_ctx(
        _members_rects(2000.0)
        + [('f_c1', 0.0, 0.0, 1900.0, 790.0),
           ('f_a1', 2050.0, 0.0, 2500.0, 300.0),
           ('f_b1', 3100.0, 0.0, 3700.0, 900.0),
           ('f_s1', 2590.0, 310.0, 3020.0, 790.0)])
    y_before = [p['translation'][1] for p in pls]
    out, shift, st = permute_pin(pls, gr, ge, box(2000, 800, 2600, 1900),
                                 [0, 1, 2, 3])
    assert st['skipped'] is False
    assert (st['nA'], st['nC'], st['nB'], st['n_evicted']) == (5, 1, 1, 1)
    assert st['evicted_idx'] == [7] and 7 not in st['group']
    assert st['group'] == {0: 'A', 1: 'A', 2: 'A', 3: 'A', 4: 'C', 5: 'A',
                           6: 'B'}
    assert st['a'] == pytest.approx(2000.0) and st['c2'] == pytest.approx(2600.0)
    # A/C/B 组平移量（手算对拍）
    assert shift[0] == pytest.approx(-2000.0)
    assert shift[4] == pytest.approx(600.0)      # C：a_max(600) − c_min(0)
    assert shift[6] == pytest.approx(-600.0)     # B：c_max(2500) − b_min(3100)
    # 就地修改 + 返回同一列表；y 不动（x 刚体平移）
    assert out is pls
    assert [p['translation'][1] for p in pls] == y_before
    assert pls[0]['translation'][0] == pytest.approx(0.0)
    assert gr[4].bounds[0] == pytest.approx(600.0)
    assert gr[6].bounds[2] == pytest.approx(3100.0)
    # 总长不增（置换段；驱逐片原位不计）
    placed_w = max(gr[i].bounds[2] for i in (0, 1, 2, 3, 4, 5, 6)) \
        - min(min(gr[i].bounds[0] for i in (0, 1, 2, 3, 4, 5, 6)), 0.0)
    assert placed_w == pytest.approx(3100.0)
    assert placed_w <= 3700.0 + 0.5


def test_permute_pin_flexible_cut_line_minimizes_straddlers():
    """flex=400 柔性选线：c2 取 straddler 数最小者（2660：0 个）而非最小候选
    （b0=2600：1 个）⇒ s1 并入 A 零驱逐；flex=0 退化为硬切 b0 ⇒ s1 被驱逐。"""
    rects = _members_rects(2000.0) + [
        ('f_s1', 2560.0, 0.0, 2660.0, 300.0),
        ('f_b1', 2700.0, 1300.0, 3300.0, 1900.0)]
    pls, gr, ge, _pm, _pb = _rect_ctx(rects)
    _out, _sh, st = permute_pin(pls, gr, ge, box(2000, 800, 2600, 1900),
                                [0, 1, 2, 3])
    assert st['c2'] == pytest.approx(2660.0)      # 最小 straddler 击败最小 c2
    assert st['n_evicted'] == 0 and st['group'][4] == 'A'
    assert st['group'][5] == 'B'

    pls2, gr2, ge2, _pm2, _pb2 = _rect_ctx(rects)
    _out2, _sh2, st2 = permute_pin(pls2, gr2, ge2, box(2000, 800, 2600, 1900),
                                   [0, 1, 2, 3], flex=0.0)
    assert st2['c2'] == pytest.approx(2600.0)     # 窗口塌缩只剩 b0
    assert st2['n_evicted'] == 1 and st2['evicted_idx'] == [4]


def test_permute_pin_eps_wall_hugger():
    """eps=5.0 守卫：贴割线片（bd[0]=b0−3）判 B 组不驱逐；eps 收紧到 0.1 即被
    误判 straddler 驱逐（守卫值 ≥ d 包络 2·d=4 的实证）。"""
    rects = _members_rects(2000.0) + [('f_b1', 2597.0, 0.0, 3300.0, 790.0)]
    pls, gr, ge, _pm, _pb = _rect_ctx(rects)
    _out, _sh, st = permute_pin(pls, gr, ge, box(2000, 800, 2600, 1900),
                                [0, 1, 2, 3])
    assert st['n_evicted'] == 0 and st['group'][4] == 'B'

    pls2, gr2, ge2, _pm2, _pb2 = _rect_ctx(rects)
    _out2, _sh2, st2 = permute_pin(pls2, gr2, ge2, box(2000, 800, 2600, 1900),
                                   [0, 1, 2, 3], eps=0.1)
    assert st2['n_evicted'] == 1 and st2['evicted_idx'] == [4]


def test_permute_pin_empty_prefix_idx_raises():
    """prefix_idx 空 = 调用方契约破坏（A 组无组合片可钉），ValueError。"""
    pls, gr, ge, _pm, _pb = _rect_ctx(_members_rects(2000.0))
    with pytest.raises(ValueError, match='prefix_idx'):
        permute_pin(pls, gr, ge, box(2000, 800, 2600, 1900), [])


# ---------------------------------------------------- reinsert_evicted 三优先序


def test_reinsert_priority_home():
    """① 组平移回位：原窝与占用碰撞，但组平移候选（shift 值）合法 ⇒ 零代价
    回位（n_home=1，微调梯未启用）。"""
    pls, gr, ge, pm, _pb = _rect_ctx(
        [('f_p', 0.0, 0.0, 100.0, 100.0), ('f_e', 50.0, 50.0, 150.0, 150.0)])
    st = reinsert_evicted(pls, gr, ge, [1], {0: 60.0}, pm, gate_nest=GATE)
    assert (st['n_home'], st['n_nudge'], st['n_slide']) == (1, 0, 0)
    assert pls[1]['translation'] == pytest.approx([110.0, 50.0])
    assert ge[1].bounds == pytest.approx((110.0, 50.0, 210.0, 150.0))


def test_reinsert_priority_nudge():
    """② +x 微调梯：组平移与 0/1/5/10/20 均碰撞，梯到 50mm 让出原窝 ⇒ 贴触
    回位（n_nudge=1；若误用组平移值判 tier，计数即错）。"""
    pls, gr, ge, pm, _pb = _rect_ctx(
        [('f_p', 0.0, 0.0, 100.0, 100.0), ('f_e', 50.0, 50.0, 150.0, 150.0)])
    st = reinsert_evicted(pls, gr, ge, [1], {0: -20.0}, pm, gate_nest=GATE)
    assert (st['n_home'], st['n_nudge'], st['n_slide']) == (0, 1, 0)
    assert pls[1]['translation'] == pytest.approx([100.0, 50.0])
    assert ge[1].bounds == pytest.approx((100.0, 50.0, 200.0, 150.0))


def test_reinsert_priority_slide():
    """③ 自右滑触：两块全宽占用夹出 y∈[855,1055] 走廊，驱逐片（恰好走廊高）
    在原窝与占用相撞、x 向全部梯档相撞 ⇒ 自右滑触穿越走廊滑过头被钳到 x=0
    布头墙（贴触零增长 —— cost 取全局宽度最小候选）；确定性双跑对拍。"""
    rects = [('f_pa', 0.0, 0.0, 700.0, 855.0),
             ('f_pb', 0.0, 1055.0, 700.0, 1910.0),
             ('f_e', 300.0, 850.0, 650.0, 1050.0)]

    def _run():
        pls, gr, ge, pm, _pb = _rect_ctx(rects)
        st = reinsert_evicted(pls, gr, ge, [2], {}, pm, gate_nest=GATE)
        return json.dumps(pls, sort_keys=True), st, ge[2].bounds

    j1, st, bnd = _run()
    assert (st['n_home'], st['n_nudge'], st['n_slide']) == (0, 0, 1)
    # 走廊候选 y=855 滑到 x<0 被钳回 x=0，全局宽度 700 < 尾随 1050 ⇒ 胜出
    assert bnd == pytest.approx((0.0, 855.0, 350.0, 1055.0))
    assert st['width_growth'] == pytest.approx(0.0)   # 贴触贴插不增长总长
    j2, st2, bnd2 = _run()
    assert j1 == j2 and st2 == st and bnd2 == bnd      # 无 RNG，双跑逐字节一致


def test_reinsert_tail_fallback_growth_warn(caplog):
    """③ 兜底：驱逐片高 2030 > 门幅 1980+容差，全部 y 候选失效 ⇒ 尾端贴触追加
    （+片宽+60mm），width_growth=260 计入 stats 且超 50mm 警戒线 warn。"""
    pls, gr, ge, pm, _pb = _rect_ctx(
        [('f_p', 0.0, 0.0, 500.0, 1910.0), ('f_e', 50.0, 0.0, 150.0, 2030.0)])
    with caplog.at_level(logging.WARNING,
                         logger='materialsorting.nesting_engine.prefix'):
        st = reinsert_evicted(pls, gr, ge, [1], {}, pm, gate_nest=GATE)
    assert st['n_slide'] == 1
    assert ge[1].bounds == pytest.approx((660.0, 0.0, 760.0, 2030.0))
    assert st['width_growth'] == pytest.approx(260.0)
    assert st['width_growth'] > PIN_WIDTH_GROWTH_WARN_MM
    assert any('width_growth' in r.message for r in caplog.records)


def test_reinsert_area_desc_order_multi_evicted():
    """多驱逐片按**面积降序**入占（tie-break 确定性）：大片 e2（14000mm²）先
    占 f_p 顶上走廊贴墙位（x=0），小片 e1（4000mm²）后贴 e2 右侧同底 —— 终位
    坐标即锁处理序（若误用升序，e1/e2 终位互换即爆）；双跑逐字节一致。
    f_p 高 1500 在顶上留出 480mm 走廊：贴墙候选成本 = max(cur_max, 片宽) =
    500.0 **精确浮点**（走廊畅通滑过头被钳 x=0），列内贴触候选 ≈570 带二分
    ~1e-9 噪声但被 max() 丢弃 —— 不再有「靠噪声取胜的平手」（旧全高夹具
    1910 口径下 y 选择即噪声 Tie，2026-08-28 门幅 1980 已翻案，故重造）。"""
    rects = [('f_p', 0.0, 0.0, 500.0, 1500.0),
             ('f_e1', 20.0, 400.0, 60.0, 500.0),
             ('f_e2', 10.0, 1400.0, 80.0, 1600.0)]

    def _run():
        pls, gr, ge, pm, _pb = _rect_ctx(rects)
        st = reinsert_evicted(pls, gr, ge, [1, 2], {}, pm, gate_nest=GATE)
        return json.dumps(pls, sort_keys=True), st, ge[1].bounds, ge[2].bounds

    j1, st, b1, b2 = _run()
    assert (st['n_home'], st['n_nudge'], st['n_slide']) == (0, 0, 2)
    assert b2 == pytest.approx((0.0, 1500.0, 70.0, 1700.0))    # 大片先占走廊贴墙
    assert b1 == pytest.approx((70.0, 1500.0, 110.0, 1600.0))  # 小片贴 e2 右侧同底
    assert st['width_growth'] == pytest.approx(0.0)            # 走廊贴插不增长总长
    j2, st2, b1b, b2b = _run()
    assert j1 == j2 and st2 == st and (b1b, b2b) == (b1, b2)


# ----------------------------------------------- pin_prefix_layout 终检编排


def _mid_layout():
    """真实构造 chunk 置于版面中部（模拟异常解）+ 矩形填充片四类归属。

    comp rot=0 @ (2000,100) ⇒ bbox x [2000, 2640]（b0=2640）、y [100, 1728]；
    c1 [0,1900]→C；a1 [2050,2500]×y[0,90]→A；s1 [2560,3060]×y[1750,1890] 跨
    b0（x2=3060 > b0+flex=3040 ⇒ 唯一 c2 候选 b0）→ straddler；b1 [3100,3700]→B。
    """
    pid_meta, pieces_by_id = _prefix_ctx()
    chunk, _gaps, _holes = _build34(pid_meta, pieces_by_id)
    comp_tr = (2000.0, 100.0)
    members = wb.expand_placements(chunk, 0.0, comp_tr)
    placements = []
    for pid, x0, y0, x1, y1 in (
            ('f_c1', 0.0, 0.0, 1900.0, 790.0),
            ('f_a1', 2050.0, 0.0, 2500.0, 90.0),
            ('f_s1', 2560.0, 1750.0, 3060.0, 1890.0),
            ('f_b1', 3100.0, 0.0, 3700.0, 900.0)):
        placement, meta, piece = _filler(pid, x0, y0, x1, y1)
        pid_meta[pid] = meta
        pieces_by_id[pid] = piece
        placements.append(placement)
    start = len(placements)
    placements += members
    return placements, pid_meta, pieces_by_id, chunk, comp_tr, \
        list(range(start, len(placements)))


def test_pin_prefix_layout_constructive_e2e():
    """AC#2 构造性用例：组合片版面中部 → 置换后 min_x ≤ 6mm、validate 复检通过
    不回退、总长不增（new_L ≤ L+0.5mm）、入参不被修改、确定性双跑一致。"""
    placements, pid_meta, pieces_by_id, chunk, comp_tr, pidx = _mid_layout()
    snapshot = [dict(p, translation=list(p['translation'])) for p in placements]
    old_w = _width_of(placements, pid_meta, pieces_by_id)

    out, st = pin_prefix_layout(placements, pid_meta, pieces_by_id, chunk,
                                0.0, comp_tr, pidx, gate_nest=GATE)
    assert st['skipped'] is False
    assert (st['nA'], st['nC'], st['nB'], st['n_evicted']) == (5, 1, 1, 1)
    assert st['rolled_back'] is False and st['issues'] == []   # validate 复检通过
    assert st['reinsert']['n_home'] == 1 and st['reinsert']['n_slide'] == 0
    # 组合片（eroded 口径）钉到 x=0；成员原轮廓外凸 ≤ d_g 量级
    comp = Polygon(_transform_polygon(chunk.polygon, 0.0, comp_tr))
    comp_shift = translate(comp, xoff=-float(st['a']))
    assert comp_shift.bounds[0] == pytest.approx(0.0, abs=1e-6)
    member_geoms = [prefix._eroded_geom(out[i], pid_meta) for i in pidx]
    assert min(g.bounds[0] for g in member_geoms) <= PIN_SKIP_AT_HEAD_MM
    assert min(g.bounds[0] for g in member_geoms) >= -PIN_STRADDLER_EPS_MM
    # 总长不增（AC 容差 0.5mm）
    new_w = _width_of(out, pid_meta, pieces_by_id)
    assert new_w <= old_w + 0.5, (new_w, old_w)
    # 纯函数语义：入参 placements 不被修改
    assert placements == snapshot
    # 展开成员 4 条（2+2）且无 PS_ 泄漏
    assert len(out) == len(placements)
    assert sorted(out[i]['id'] for i in pidx) == ['g02_34', 'g02_34',
                                                  'g03_34', 'g03_34']
    assert all(not p['id'].startswith(PREFIX_PID_PREFIX) for p in out)
    # 确定性：双跑逐字节一致（帧对拍口径）
    out2, st2 = pin_prefix_layout(placements, pid_meta, pieces_by_id, chunk,
                                  0.0, comp_tr, pidx, gate_nest=GATE)
    assert json.dumps(out2, sort_keys=True) == json.dumps(out, sort_keys=True)
    assert st2 == st


@pytest.mark.parametrize('head_off', [0.0, 0.2, 2.0, 5.9])
def test_pin_prefix_layout_head_anchor_skip_p0(head_off):
    """AC#4 P0 回归：组合片自然锚定布头（4 头部位姿代 4 seed）⇒ 置换跳过、
    布局逐字节不变（PIN ≡ FREE）、总长/密度差 0.00pt —— P0 探针 4/4 seed
    「FREE≈PIN 且置换跳过」的机制级复现。"""
    pid_meta, pieces_by_id = _prefix_ctx()
    chunk, _gaps, _holes = _build34(pid_meta, pieces_by_id)
    # comp_world bounds[0] == head_off（chunk.polygon 归一坐标自带 ~2mm 内偏，
    # 平移量按轮廓最小角反推，a 值精确命中参数化档位）
    comp_tr = (head_off - min(x for x, _y in chunk.polygon), 100.0)
    placements = []
    for pid, x0, y0, x1, y1 in (('f_c', 0.0, 0.0, 400.0, 90.0),
                                ('f_b', 700.0, 0.0, 1200.0, 90.0)):
        placement, meta, piece = _filler(pid, x0, y0, x1, y1)
        pid_meta[pid] = meta
        pieces_by_id[pid] = piece
        placements.append(placement)
    placements += wb.expand_placements(chunk, 0.0, comp_tr)
    pidx = [2, 3, 4, 5]
    total_area = sum(float(m['area_mm2']) * int(m['demand'])
                     for m in pid_meta.values())
    w_in = _width_of(placements, pid_meta, pieces_by_id)
    d_in = total_area / (w_in * GATE) * 100.0

    out, st = pin_prefix_layout(placements, pid_meta, pieces_by_id, chunk,
                                0.0, comp_tr, pidx, gate_nest=GATE)
    assert st['skipped'] is True and st['reinsert'] is None
    assert st['rolled_back'] is False and st['issues'] == []
    assert out == placements                                   # 零触碰直通
    w_out = _width_of(out, pid_meta, pieces_by_id)
    d_out = total_area / (w_out * GATE) * 100.0
    assert w_out == w_in                                       # 总长不变
    assert d_out - d_in == 0.0                                 # 密度差 0.00pt


def test_pin_prefix_layout_rollback_on_recheck_fail():
    """复检失败回退：布局含 y=2000 > 1980+11 越界片（模拟异常解），置换后
    y 违例仍在 ⇒ ``rolled_back`` 且返回置换前布局（LNS 纪律：交付物恒过检）。"""
    placements, pid_meta, pieces_by_id, chunk, comp_tr, pidx = _mid_layout()
    placement, meta, piece = _filler('f_bad', 3800.0, 0.0, 4000.0, 2000.0)
    pid_meta['f_bad'] = meta
    pieces_by_id['f_bad'] = piece
    placements.append(placement)
    snapshot = [dict(p, translation=list(p['translation'])) for p in placements]

    out, st = pin_prefix_layout(placements, pid_meta, pieces_by_id, chunk,
                                0.0, comp_tr, pidx, gate_nest=GATE)
    assert st['skipped'] is False
    assert st['rolled_back'] is True and st['issues']
    assert any('幅' in i for i in st['issues'])
    assert out == snapshot                                     # 回退 = 原布局
    assert placements == snapshot                             # 入参亦不被修改


# --------------------------- 选码搜索（顶部异码补片，2026-09-02 需求）


def _stack_ctx(heights, *, demands=None, width=200.0):
    """矩形竖排夹具（选码搜索用）：``heights = {(label, size): 高}``，
    ``demands`` 覆写 ``{(label, size): N}``（缺省 2 = 2+2 资格）。矩形同宽 ⇒
    候选 x 全塌缩 {0} ⇒ 纯竖排 H = Σ高（d_g=0 ⇒ erode==raw，精确可手算）。"""
    demands = demands or {}
    pieces_by_id, pid_meta = {}, {}
    for (label, size), h in heights.items():
        pid = f'{label}_{size}'
        pts = [[0.0, 0.0], [width, 0.0], [width, h], [0.0, h]]
        p = _panel_piece(pid, label, size, pts)
        pieces_by_id[pid] = p
        pid_meta[pid] = {
            'size': size, 'color': '#000000', 'polygon': [list(pt) for pt in pts],
            'area_mm2': p['area_mm2'], 'label': label,
            'demand': int(demands.get((label, size), 2)),
            'net_polygon': [], 'internal_lines': [], 'notches': [],
            'grain_line': None,
        }
    return pid_meta, pieces_by_id


def _qty_of(pid_meta):
    """pid_meta → quantities 矩阵（``{label: {sizeKey: demand}}``，sizeKey 口径
    与 build_pid_meta / eligible_sizes 一致：number→str、None→'null'）。"""
    q = {}
    for m in pid_meta.values():
        if m['label'] is None:
            continue
        sk = 'null' if m['size'] is None else str(m['size'])
        q.setdefault(m['label'], {})[sk] = m['demand']
    return q


def _select(pid_meta, pieces, **kw):
    """select_prefix_plan 测试速记（g02/g03 + pid_meta 派生 quantities/sizes）。"""
    kw.setdefault('gate_nest', 1980.0)
    kw.setdefault('d_g', 0.0)
    kw.setdefault('seed', 0)
    return select_prefix_plan(
        pid_meta, pieces, front_label='g02', back_label='g03',
        quantities=_qty_of(pid_meta),
        sizes=sorted({m['size'] for m in pid_meta.values()
                      if m['size'] is not None}), **kw)


_BEST_FIT = {('g02', 34): 300.0, ('g03', 34): 250.0,     # 基座(34)=1100
             ('g02', 36): 400.0, ('g03', 36): 350.0,     # 基座(36)=1500
             ('g02', 38): 420.0, ('g03', 38): 360.0}     # 基座(38)=1560


def test_extra_rot_candidates_locked():
    """补片朝向候选锁死：(0.0, 180.0) 均严格顺布纹（2026-09-02 定案③ 保留
    翻转自由度）；组合片主解朝向 PREFIX_ORIENTATIONS 同口径不变。"""
    assert EXTRA_ROT_CANDIDATES == (0.0, 180.0)
    assert tuple(PREFIX_ORIENTATIONS) == (0.0, 180.0)


def test_select_prefix_plan_best_fit():
    """最优拟合：H 手算 —— A@38 基座 1560 + g02@36 补片 400 = 1960 为全场
    最大可行（次高 A@36+g02@38=1920）⇒ 取 H 最大者；断言 A/片型/B/members=5
    （4 同码 + 顶异码）/第 5 成员在顶/贴触 ≤1mm/H ≤ gate/residual=gate−H/
    pid 追加段/候选表计数。"""
    pid_meta, pieces = _stack_ctx(_BEST_FIT)
    trace = []
    chunk, gaps, holes, info = _select(pid_meta, pieces, trace=trace)
    assert info['fallback'] is False
    assert info['size'] == 38
    assert info['extra'] == {'pid': 'g02_36', 'label': 'g02', 'size': 36,
                             'rotation': 0.0}    # 矩形 rot180 同高 ⇒ 平手 rot0 先
    assert chunk.pid == 'PS_g02+g03@38+g02@36'
    assert chunk.n_members == 5
    assert [m['pid'] for m in chunk.members] == ['g02_38', 'g03_38',
                                                 'g02_38', 'g03_38', 'g02_36']
    assert len(gaps) == 4 and max(gaps) <= GAP_EPS_MM and holes == 0
    # 第 5 成员在顶（权威式记账重构 eroded 几何，底边搭基座顶）
    geoms = [Polygon(_transform_polygon(pid_meta[m['pid']]['polygon'],
                                        m['rotation'], m['translation']))
             for m in chunk.members]
    assert geoms[4].bounds[1] >= max(g.bounds[3] for g in geoms[:4]) - 0.5
    assert chunk.bbox['height_mm'] == pytest.approx(1960.0, abs=0.5)
    assert info['height_mm'] == pytest.approx(1960.0, abs=0.5)   # 同口径
    assert info['height_mm'] <= 1980.0
    assert info['residual_mm'] == pytest.approx(20.0, abs=0.5)   # gate − H
    # 候选表：6 pid 池 − 每 A 2 个 B==A × 3 A × 2 rot = 24 次尝试（含不可行）
    assert len(trace) == info['n_candidates'] == 24
    feas = [r for r in trace if r['feasible']]
    assert len(feas) >= 2                          # 两可行组合取 H 大者（AC#3）
    assert max(r['height_mm'] for r in feas) == pytest.approx(1960.0, abs=0.5)


def test_extra_pool_eligibility():
    """候选池资格（FR-2）：demand<1、非数字码（size=None 通用码）不入池、
    B==A 搜索层排除 —— 唯一可用异码 g03@36 胜出（H=1910）；demand=0 的
    g02@36 与 400mm null 码片若泄漏将以 1960 夺魁，可观察证伪。"""
    pid_meta, pieces = _stack_ctx(
        {('g02', 38): 420.0, ('g03', 38): 360.0,
         ('g02', 36): 400.0, ('g03', 36): 350.0},
        demands={('g02', 36): 0})                  # g02@36 demand 0 → 不入池
    pid_meta['g02_null'] = {                       # null 通用码 → 非数字码不入池
        'size': None, 'color': '#000000',
        'polygon': [[0.0, 0.0], [200.0, 0.0], [200.0, 400.0], [0.0, 400.0]],
        'area_mm2': 80000.0, 'label': 'g02', 'demand': 2,
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None}
    assert prefix._extra_candidates(pid_meta, 'g02', 'g03') == [
        ('g02', 38, 'g02_38'), ('g03', 36, 'g03_36'), ('g03', 38, 'g03_38')]
    chunk, _gaps, _holes, info = _select(pid_meta, pieces)
    assert eligible_sizes(_qty_of(pid_meta), 'g02', 'g03',
                          sizes=[36, 38]) == [38]  # 36 缺 g02 2+2 资格
    assert info['size'] == 38
    assert info['extra']['pid'] == 'g03_36'        # ≠A 且 demand≥1 的唯一者
    assert chunk.members[-1]['pid'] == 'g03_36'
    assert info['n_candidates'] == 2               # (g03,36) × 2 rot（余 B==A 排除）
    assert info['height_mm'] == pytest.approx(1910.0, abs=0.5)


def test_select_prefix_plan_tie_break_and_determinism():
    """平手裁决 + 双跑确定性：L 形同构两码全组合 H 恒等（g02 补片 2094 /
    g03 补片 1974 两档，跨 A/rot 精确平手）⇒ 按迭代序 (A 升序, front 先于
    back, B 升序, rot0 先) 取 (A=34, g02@36, rot0)；同输入双跑
    (to_dict, gaps, holes, info) 全等且搜索路径与 seed 无关。"""
    pid_meta, pieces = _prefix_ctx(sizes=(34, 36))
    kw = dict(front_label='g02', back_label='g03',
              quantities=_qty_of(pid_meta), sizes=[34, 36], d_g=2.0,
              gate_nest=2200.0)                    # 2094/1974 均可行
    ca, ga, ha, ia = select_prefix_plan(pid_meta, pieces, seed=0, **kw)
    cb, gb, hb, ib = select_prefix_plan(pid_meta, pieces, seed=7, **kw)
    assert json.dumps(ca.to_dict(), sort_keys=True) \
        == json.dumps(cb.to_dict(), sort_keys=True)
    assert ga == gb and ha == hb and ia == ib      # 双跑全等（无 RNG）
    assert ia['size'] == 34                        # 平手 A 升序
    assert ia['extra'] == {'pid': 'g02_36', 'label': 'g02', 'size': 36,
                           'rotation': 0.0}        # front 先于 back + rot0 先
    assert ia['fallback'] is False
    assert ia['height_mm'] == pytest.approx(2094.0, abs=1.0)
    assert ia['residual_mm'] == pytest.approx(106.0, abs=1.0)   # 2200 − 2094
    assert ia['n_candidates'] == 8                 # 2 A × (2 异码 × 2 rot)
    assert len(ca.members) == 5 and max(ga) <= GAP_EPS_MM


def test_select_prefix_plan_fallback_parity():
    """兜底（用户定案①）：全无可行组合（gate=1250：基座 1100 可容、任何补片
    ≥250 超高；g03@36 demand 3 ⇒ elig={34}）→ pick_prefix_size +
    build_prefix_plan 与现行逐字节一致（to_dict/gaps/holes 全等）+
    info.fallback=True/extra=None（seed 只在兜底路径消费）。"""
    pid_meta, pieces = _stack_ctx(
        {('g02', 34): 300.0, ('g03', 34): 250.0,
         ('g02', 36): 400.0, ('g03', 36): 350.0},
        demands={('g03', 36): 3})                  # 36 失 2+2 资格（在池可当补片）
    q = _qty_of(pid_meta)
    assert eligible_sizes(q, 'g02', 'g03', sizes=[34, 36]) == [34]
    chunk, gaps, holes, info = select_prefix_plan(
        pid_meta, pieces, front_label='g02', back_label='g03', quantities=q,
        sizes=[34, 36], d_g=0.0, gate_nest=1250.0, seed=5)
    ref, ref_gaps, ref_holes = build_prefix_plan(
        pid_meta, pieces, front_pid='g02_34', back_pid='g03_34',
        d_g=0.0, gate_nest=1250.0)
    assert json.dumps(chunk.to_dict(), sort_keys=True) \
        == json.dumps(ref.to_dict(), sort_keys=True)
    assert gaps == ref_gaps and holes == ref_holes
    assert len(chunk.members) == 4                 # 兜底恒 4 片
    assert info == {'size': 34, 'extra': None,
                    'height_mm': ref.bbox['height_mm'],
                    'residual_mm': 1250.0 - ref.bbox['height_mm'],
                    'fallback': True, 'n_candidates': 4}


def test_select_prefix_plan_gate_margin_rejects_fitline():
    """门幅安全余量（2026-09-02 修复回归锁）：H ∈ (gate−MARGIN, gate] 的贴线
    组合判不可行 —— 5336 无 per_type 事故（residual 0.307mm 组合片在主解条带
    放不下 ⇒ spyrrow panic「strip-width is running away」被误报为「solver
    返回 None」）不再复发；次高安全候选胜出且 residual ≥ MARGIN 恒成立。

    H 手算（gate=1980，安全线 1970）：A38+g03@36 = 1975 贴线（旧口径 1980
    放行且为最高者）→ 拒；A38+g02@36 = 1960 → 胜；A36+g02@38 = 2050 /
    A36+g03@38 = 1990 超线。
    """
    pid_meta, pieces = _stack_ctx(
        {('g02', 38): 420.0, ('g03', 38): 360.0,     # 基座(38)=1560
         ('g02', 36): 400.0, ('g03', 36): 415.0})    # 基座(36)=1630
    trace = []
    chunk, _gaps, _holes, info = _select(pid_meta, pieces, trace=trace)
    assert info['fallback'] is False
    assert info['size'] == 38
    assert info['extra']['pid'] == 'g02_36'          # 贴线 g03@36 被余量拦下
    assert info['height_mm'] == pytest.approx(1960.0, abs=0.5)
    # 收敛不变量：胜者到门幅的残余 ≥ 安全余量（贴线组合永不入选）
    assert info['residual_mm'] >= PREFIX_GATE_MARGIN_MM - 1e-6
    fitline = [r for r in trace
               if r['extra_size'] == 36 and r['label'] == 'g03']
    assert fitline and all(not r['feasible'] for r in fitline)
    assert all(r['reason'] == '竖排超高' for r in fitline)


def test_select_prefix_plan_all_fitline_falls_back():
    """全部组合贴线（唯一异码 g03@36：1560+415=1975 > 1970）→ 兜底 4 片
    （用户定案①路径；兜底基座 1560 ≤ 安全线放行）。"""
    pid_meta, pieces = _stack_ctx(
        {('g02', 38): 420.0, ('g03', 38): 360.0, ('g03', 36): 415.0})
    chunk, _gaps, _holes, info = _select(pid_meta, pieces)
    assert info['fallback'] is True
    assert info['extra'] is None
    assert info['size'] == 38                        # elig 唯一码（36 缺 2+2）
    assert len(chunk.members) == 4
    assert info['height_mm'] == pytest.approx(1560.0, abs=0.5)
    assert info['residual_mm'] >= PREFIX_GATE_MARGIN_MM - 1e-6


def test_build_prefix_plan_fitline_base_rejected():
    """兜底路径守卫同口径：基座自身贴线（4 片堆叠 1975，gate=1980 余 5mm <
    MARGIN）→ PrefixError「安全条带界」；同基座在 gate=2000（余 25mm）放行
    —— 守卫相对门幅，非绝对高度。"""
    pid_meta, pieces = _stack_ctx({('g02', 34): 495.0, ('g03', 34): 492.5})
    with pytest.raises(PrefixError, match='安全条带界'):
        build_prefix_plan(pid_meta, pieces, front_pid='g02_34',
                          back_pid='g03_34', d_g=0.0, gate_nest=1980.0)
    chunk, _g, _h = build_prefix_plan(pid_meta, pieces, front_pid='g02_34',
                                      back_pid='g03_34', d_g=0.0, gate_nest=2000.0)
    assert chunk.bbox['height_mm'] == pytest.approx(1975.0, abs=0.5)


def test_extra_rot180_accounting_and_envelope():
    """补片 rot180 记账权威式（镜像 form_and_rot180_accounting）+ 5 片两朝向
    展开包络：显式 extra_rot=180 构造 —— 第 5 成员 tr 复现放置几何（负坐标
    补偿缺失即侧移爆缝）、gaps 4 条全 ≤1mm、第 5 成员在顶、
    union(成员原轮廓@展开位) ⊆ composite ⊕ d_g。"""
    pid_meta, pieces = _prefix_ctx(sizes=(34, 36))
    chunk, gaps, holes = build_prefix_plan(
        pid_meta, pieces, front_pid='g02_34', back_pid='g03_34', d_g=2.0,
        gate_nest=2200.0, extra_pid='g02_36', extra_rot=180.0)
    assert chunk.pid == 'PS_g02+g03@34+g02@36'
    assert chunk.n_members == 5
    assert chunk.members[-1]['pid'] == 'g02_36'
    assert chunk.members[-1]['rotation'] == 180.0
    assert len(gaps) == 4 and max(gaps) <= GAP_EPS_MM and holes == 0
    # 记账权威式重构放置几何（eroded 碰撞口径）
    geoms = [Polygon(_transform_polygon(pid_meta[m['pid']]['polygon'],
                                        m['rotation'], m['translation']))
             for m in chunk.members]
    for i in range(4):
        assert geoms[i].distance(geoms[i + 1]) <= GAP_EPS_MM, i
    assert geoms[4].bounds[1] == pytest.approx(
        max(g.bounds[3] for g in geoms[:4]), abs=0.5)   # 第 5 成员在顶
    assert chunk.bbox['height_mm'] == pytest.approx(2094.0, abs=1.0)
    for c_rot, c_tr in [(0.0, (700.0, 300.0)), (180.0, (2000.0, 1500.0))]:
        expanded = wb.expand_placements(chunk, c_rot, c_tr)
        assert len(expanded) == 5                       # 恰 5 条（2+2+补片）
        assert all(e['id'] in pid_meta for e in expanded)   # 无 PS_ 泄漏
        comp_world = Polygon(_transform_polygon(chunk.polygon, c_rot, c_tr))
        member_union = unary_union([
            Polygon(_transform_polygon(
                pieces[e['id']]['polygon'], e['rotation'], e['translation']))
            for e in expanded])
        # ⊕ d_g（join_style=mitre 保真实偏移曲线，同 4 片包络用例口径）
        assert comp_world.buffer(chunk.d_g + 0.5, join_style=2).contains(
            member_union), (c_rot, c_tr)


def test_build_prefix_plan_extra_guards():
    """补片直调守卫：pid 缺失/demand<1 → PrefixError（候选资格文案）；与套装
    同码（B==A）拒；片型非前/后幅 g 码拒；5 片竖排超高守卫沿用（基座 1628
    ≤1980 可容、+补片 2094 >1980 拒 —— 不设缝隙阈值也不放宽门幅界）。"""
    pid_meta, pieces = _prefix_ctx(sizes=(34, 36))
    m0 = dict(pid_meta)
    m0['g02_36'] = {**pid_meta['g02_36'], 'demand': 0}
    with pytest.raises(PrefixError, match='无可用副本'):
        build_prefix_plan(m0, pieces, front_pid='g02_34', back_pid='g03_34',
                          d_g=2.0, gate_nest=1980.0, extra_pid='g02_36')
    with pytest.raises(PrefixError, match='无可用副本'):
        build_prefix_plan(pid_meta, pieces, front_pid='g02_34',
                          back_pid='g03_34', d_g=2.0, gate_nest=1980.0,
                          extra_pid='g02_99')       # pid 不在 pid_meta
    with pytest.raises(PrefixError, match='同码'):
        build_prefix_plan(pid_meta, pieces, front_pid='g02_34',
                          back_pid='g03_34', d_g=2.0, gate_nest=1980.0,
                          extra_pid='g03_34')
    p5 = _panel_piece('g05_36', 'g05', 36, _back_pts())
    m5 = dict(pid_meta)
    m5['g05_36'] = {'size': 36, 'color': '#000',
                    'polygon': erode_polygon(p5['polygon'], 2.0),
                    'area_mm2': p5['area_mm2'], 'label': 'g05', 'demand': 1,
                    'net_polygon': [], 'internal_lines': [], 'notches': [],
                    'grain_line': None}
    with pytest.raises(PrefixError, match='非前/后幅'):
        build_prefix_plan(m5, pieces, front_pid='g02_34', back_pid='g03_34',
                          d_g=2.0, gate_nest=1980.0, extra_pid='g05_36')
    with pytest.raises(PrefixError, match='竖排高'):
        build_prefix_plan(pid_meta, pieces, front_pid='g02_34',
                          back_pid='g03_34', d_g=2.0, gate_nest=1980.0,
                          extra_pid='g02_36')


def _hand_ps_chunk5():
    """5 成员黄金 chunk（镜像 _hand_ps_chunk + 3 条成员；offset=(10,20) 非零
    对「减号」错误最敏感；rot/片型混排覆盖 rot_f 取模与跨片型补片位）。"""
    return wb.BandChunk(
        pid='PS_g02+g03@34+g02@32', label='g02',
        polygon=[[0.0, 0.0], [120.0, 0.0], [120.0, 260.0], [0.0, 260.0]],
        offset=(10.0, 20.0),
        members=[
            {'pid': 'g02_34', 'rotation': 0.0, 'translation': [15.0, 25.0]},
            {'pid': 'g03_34', 'rotation': 180.0, 'translation': [115.0, 125.0]},
            {'pid': 'g02_34', 'rotation': 180.0, 'translation': [65.0, 85.0]},
            {'pid': 'g03_34', 'rotation': 0.0, 'translation': [95.0, 45.0]},
            {'pid': 'g02_32', 'rotation': 180.0, 'translation': [55.0, 165.0]},
        ],
        fill_pct=80.0, bbox={'width_mm': 120.0, 'height_mm': 260.0},
        seed=0, d_g=2.0, tol_g=0.0,
    )


def test_expand_golden_5members_rot0_hand_computed():
    """rot=0 手算对拍（5 条）：tr_f = m.tr − offset + c.tr ⇒
    (105,55)/(205,155)/(155,115)/(185,75)/(145,195)。offset 误用加号即整体
    +(20,40) 爆。"""
    out = wb.expand_placements(_hand_ps_chunk5(), 0.0, (100.0, 50.0))
    assert [e['id'] for e in out] == ['g02_34', 'g03_34', 'g02_34', 'g03_34',
                                      'g02_32']
    assert [e['rotation'] for e in out] == [0.0, 180.0, 180.0, 0.0, 180.0]
    want = [[105.0, 55.0], [205.0, 155.0], [155.0, 115.0], [185.0, 75.0],
            [145.0, 195.0]]
    assert all(e['translation'] == pytest.approx(w, abs=1e-9)
               for e, w in zip(out, want))


def test_expand_golden_5members_rot180_hand_computed():
    """rot=180 手算对拍（R(180)=diag(−1,−1)）：−(m.tr−offset)+(1000,500) ⇒
    (995,495)/(895,395)/(945,435)/(915,475)/(955,355)；rot_f=(m.rot+180)%360。"""
    out = wb.expand_placements(_hand_ps_chunk5(), 180.0, (1000.0, 500.0))
    assert [e['rotation'] for e in out] == [180.0, 0.0, 0.0, 180.0, 0.0]
    want = [[995.0, 495.0], [895.0, 395.0], [945.0, 435.0], [915.0, 475.0],
            [955.0, 355.0]]
    assert all(e['translation'] == pytest.approx(w, abs=1e-9)
               for e, w in zip(out, want))
