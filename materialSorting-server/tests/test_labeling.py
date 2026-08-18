"""labeling g 码编号体系单测（v2：label 先行、名称无关、T4 跨码同号）。

覆盖：``label_for`` 边界 / ``code_sort_key`` 数值序 / ``master_code_from_block_name``
保守识别规则矩阵（含仓内真实易误伤 block 名）/ ``collect_master_codes``
all-or-nothing（有效片 = 全部 size≠None 片，不要求任何名称映射）/ ``assign_codes``
顺序与母版复用两模式 + group_key 前置排序键跨码同号（T4）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting.nesting_engine.labeling import (
    label_for,
    code_sort_key,
    master_code_from_block_name,
    collect_master_codes,
    assign_codes,
    sequential_sort_key,
)


def _rect(x: float, y: float, w: float, h: float):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


class _FakePiece:
    """PieceOutline duck-type（labeling 只读下列属性）。"""

    def __init__(self, group_key, size, polygon_mm, block_name='B', piece_index=0):
        self.group_key = group_key
        self.size = size
        self.polygon_mm = polygon_mm
        self.block_name = block_name
        self.piece_index = piece_index
        xs = [p[0] for p in polygon_mm]
        ys = [p[1] for p in polygon_mm]
        self.area_mm2 = (max(xs) - min(xs)) * (max(ys) - min(ys))


# ---------------------------------------------------------------- label_for / 排序

def test_label_for_boundaries():
    # 零填充两位，>99 片自然升位；每码裁片数实测 ≤10，g100 仅兜底
    assert [label_for(i) for i in (0, 1, 9, 98, 99)] == ['g01', 'g02', 'g10', 'g99', 'g100']


def test_code_sort_key_numeric_order():
    codes = ['g10', 'g02', 'g100', 'g01']
    assert sorted(codes, key=code_sort_key) == ['g01', 'g02', 'g10', 'g100']
    assert code_sort_key('g03') == 3
    assert code_sort_key('非码') == 0   # 非 g 码兜底 0


# ---------------------------------------------------------------- 母版编号识别

def test_master_code_from_block_name():
    # 命中：剥码号尾缀后以显式前缀编号结尾；G/# 与非零填充均规范化
    assert master_code_from_block_name('前片g03.30') == 'g03'
    assert master_code_from_block_name('前片g3-30') == 'g03'
    assert master_code_from_block_name('腰G7.28') == 'g07'
    assert master_code_from_block_name('袋#12.32') == 'g12'
    assert master_code_from_block_name('g04') == 'g04'
    # 不命中：仓内真实母版 block 名（无编号标定，必须走默认顺序赋号）
    assert master_code_from_block_name('noname.双排.28') is None
    # 易误伤：款号/码段数字（含西里尔字母 С）绝不能被当成编号
    assert master_code_from_block_name('noname.M1787#28-32С33-38') is None
    # 纯数字尾缀拒绝（与码号/款号数字歧义）
    assert master_code_from_block_name('前片3') is None
    assert master_code_from_block_name('前片-3') is None   # '-3' 按码号尾缀剥掉
    # 4 位数字不识别（保守：码号/款号多为多位数字）
    assert master_code_from_block_name('前片g0330') is None


# ---------------------------------------------------------------- all-or-nothing

def _coded_pieces(with_code=True, dup_in_size=False):
    """码 30 三组片（group_key 互异）+1 片 size=None 旁路片；block 名带/不带显式编号。"""
    qian = f'前片g05.30' if with_code else 'noname.前片.30'
    hou = '后片g02.30' if with_code else 'noname.后片.30'
    yao = '腰g09.30' if with_code else 'noname.腰.30'
    if dup_in_size:
        yao = '腰g02.30'   # 与后片同码冲突
    return [
        _FakePiece('k_qian#0', 30, _rect(0, 200, 40, 40), block_name=qian),
        _FakePiece('k_hou#0', 30, _rect(0, 100, 30, 30), block_name=hou),
        _FakePiece('k_yao#0', 30, _rect(0, 0, 20, 20), block_name=yao),
        # size=None 片不参与 all-or-nothing 校验（非「有效片」）
        _FakePiece('k_x#0', None, _rect(100, 0, 10, 10), block_name='noname.旁'),
    ]


def test_collect_master_codes_all_hit():
    codes = collect_master_codes(_coded_pieces())
    assert codes is not None
    assert set(codes.values()) == {'g02', 'g05', 'g09'}


def test_collect_master_codes_unmapped_group_participates():
    # v2：有效片 = 全部 size≠None 片 —— 「未录入名称」组（block 名无意义）同样参与
    # all-or-nothing 校验；任一无编号 → 整体回退（v1 会因无 GROUP_NAMES 映射直接丢片）。
    pieces = [
        _FakePiece('k_a#0', 30, _rect(0, 0, 40, 40), block_name='blk a.30'),
        _FakePiece('k_b#0', 30, _rect(0, 100, 30, 30), block_name='blk b.30'),  # 无编号
    ]
    assert collect_master_codes(pieces) is None


def test_collect_master_codes_missing_one_falls_back():
    # 任一有效片无编号 → None（整体回退顺序赋号，绝不混编）
    assert collect_master_codes(_coded_pieces(with_code=False)) is None


def test_collect_master_codes_dup_in_size_falls_back():
    # 同码内编号冲突 → None
    assert collect_master_codes(_coded_pieces(dup_in_size=True)) is None


def test_collect_master_codes_same_code_across_sizes_ok():
    # 同一片型各码同号（前片-28/前片-30 都 g05）放行：demand 键是 (label, sizeKey)
    pieces = [
        _FakePiece('k_qian#0', 28, _rect(0, 0, 40, 40), block_name='前片g05.28'),
        _FakePiece('k_qian#0', 30, _rect(0, 0, 40, 40), block_name='前片g05.30'),
    ]
    codes = collect_master_codes(pieces)
    assert codes is not None
    assert list(codes.values()) == ['g05', 'g05']


# ---------------------------------------------------------------- assign_codes 两模式

def test_assign_codes_sequential_group_key_first():
    # 顺序模式排序键前置 group_key（T4）：组间按 group_key 字典序，组内按
    # parse_member_sort_key（上方/左/大片优先）。'k_a' < 'k_b' < 'k_y' → a 组片拿 g01。
    pieces = [
        _FakePiece('k_y#0', 30, _rect(0, 200, 40, 40)),   # 几何最上但组序最后 → g03
        _FakePiece('k_a#0', 30, _rect(0, 100, 30, 30)),   # → g01
        _FakePiece('k_b#0', 30, _rect(0, 0, 20, 20)),     # → g02
    ]
    out = assign_codes(pieces)
    assert [c for _, c in out[30]] == ['g01', 'g02', 'g03']
    assert out[30][0][0].group_key == 'k_a#0'


def test_assign_codes_sequential_same_code_across_sizes():
    # T4 核心不变量：同一 block 模板（同 group_key）在各码得到同一 g 码 —— 码 28/30
    # 几何故意错开（码 30 的 b 组画在最上），组序仍保证跨码同号。
    pieces = [
        _FakePiece('k_a#0', 28, _rect(0, 200, 40, 40)),
        _FakePiece('k_b#0', 28, _rect(0, 100, 30, 30)),
        _FakePiece('k_b#0', 30, _rect(0, 200, 30, 30)),   # 码 30：b 组画最上
        _FakePiece('k_a#0', 30, _rect(0, 100, 40, 40)),
    ]
    out = assign_codes(pieces)
    code28 = {p.group_key: c for p, c in out[28]}
    code30 = {p.group_key: c for p, c in out[30]}
    assert code28 == {'k_a#0': 'g01', 'k_b#0': 'g02'}
    assert code30 == {'k_a#0': 'g01', 'k_b#0': 'g02'}   # 跨码同号


def test_assign_codes_sequential_deterministic_ac5():
    # AC#5：parse 与 commit 各自对同一母版跑 assign_codes → 同一 (block_name, size,
    # piece_index) 必得同码（两次独立调用结果一致，不经 (size, ptype) 中转）。
    pieces = [
        _FakePiece('k_a#0', 30, _rect(0, 200, 40, 40), block_name='blk a.30', piece_index=0),
        _FakePiece('k_a#1', 30, _rect(0, 100, 30, 30), block_name='blk a.30', piece_index=1),
        _FakePiece('k_b#0', 28, _rect(0, 0, 20, 20), block_name='blk b.28', piece_index=0),
    ]
    run1 = {(p.block_name, p.size, p.piece_index): c
            for pairs in assign_codes(pieces).values() for p, c in pairs}
    run2 = {(p.block_name, p.size, p.piece_index): c
            for pairs in assign_codes(pieces).values() for p, c in pairs}
    assert run1 == run2
    assert run1 == {('blk a.30', 30, 0): 'g01', ('blk a.30', 30, 1): 'g02',
                    ('blk b.28', 28, 0): 'g01'}


def test_assign_codes_master_reuse_orders_by_code():
    # 母版复用：输出按母版码数值序（UI 列序 = 码序）；size=None 片（母版码不覆盖）
    # 走顺序补号 —— v2 该组内无母版码，自然从 g01 起
    pieces = [
        _FakePiece('k_qian#0', 30, _rect(0, 200, 40, 40), block_name='前片g05.30'),
        _FakePiece('k_hou#0', 30, _rect(0, 100, 30, 30), block_name='后片g02.30'),
        _FakePiece('k_yao#0', 30, _rect(0, 0, 20, 20), block_name='腰g09.30'),
        _FakePiece('k_x#0', None, _rect(100, 0, 10, 10), block_name='noname.旁'),
    ]
    out = assign_codes(pieces)
    assert [c for _, c in out[30]] == ['g02', 'g05', 'g09']
    assert [c for _, c in out[None]] == ['g01']   # size=None 组顺序补号（组内无母版码）


def test_sequential_sort_key_group_key_precedes_geometry():
    p_low_a = _FakePiece('k_a#0', 30, _rect(0, 0, 10, 10))
    p_high_b = _FakePiece('k_b#0', 30, _rect(0, 500, 10, 10))
    assert sequential_sort_key(p_low_a) < sequential_sort_key(p_high_b)
