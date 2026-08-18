"""labeling g 码编号体系单测（2026-08-18 裁片标识统一为 g01+ 编号）。

覆盖：``label_for`` 边界 / ``code_sort_key`` 数值序 / ``master_code_from_block_name``
保守识别规则矩阵（含仓内真实易误伤 block 名）/ ``collect_master_codes``
all-or-nothing / ``assign_codes`` 顺序与母版复用两模式。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting.dxf_parser.export_dxf import GROUP_NAMES
from materialsorting.nesting_engine.labeling import (
    label_for,
    code_sort_key,
    master_code_from_block_name,
    collect_master_codes,
    assign_codes,
    compute_size_ptype_labels,
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


GMAP = {'k_hou': 'g00', 'k_qian': 'g01', 'k_yao': 'g09'}


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
    """码 30 三片型（+1 片无映射旁路片）；block 名带/不带显式编号。"""
    qian = f'前片g05.30' if with_code else 'noname.前片.30'
    hou = '后片g02.30' if with_code else 'noname.后片.30'
    yao = '腰g09.30' if with_code else 'noname.腰.30'
    if dup_in_size:
        yao = '腰g02.30'   # 与后片同码冲突
    return [
        _FakePiece('k_qian', 30, _rect(0, 200, 40, 40), block_name=qian),
        _FakePiece('k_hou', 30, _rect(0, 100, 30, 30), block_name=hou),
        _FakePiece('k_yao', 30, _rect(0, 0, 20, 20), block_name=yao),
        # 旁路片：无 GROUP_NAMES 映射（不参与 all-or-nothing 校验）
        _FakePiece('k_x', 30, _rect(100, 0, 10, 10), block_name='noname.旁.30'),
    ]


def test_collect_master_codes_all_hit():
    codes = collect_master_codes(_coded_pieces(), GMAP, GROUP_NAMES)
    assert codes is not None
    assert set(codes.values()) == {'g02', 'g05', 'g09'}


def test_collect_master_codes_missing_one_falls_back():
    # 任一有效片无编号 → None（整体回退顺序赋号，绝不混编）
    assert collect_master_codes(_coded_pieces(with_code=False), GMAP, GROUP_NAMES) is None


def test_collect_master_codes_dup_in_size_falls_back():
    # 同码内编号冲突 → None
    assert collect_master_codes(_coded_pieces(dup_in_size=True), GMAP, GROUP_NAMES) is None


def test_collect_master_codes_same_code_across_sizes_ok():
    # 同一片型各码同号（前片-28/前片-30 都 g05）放行：demand 键是 (label, sizeKey)
    pieces = [
        _FakePiece('k_qian', 28, _rect(0, 0, 40, 40), block_name='前片g05.28'),
        _FakePiece('k_qian', 30, _rect(0, 0, 40, 40), block_name='前片g05.30'),
    ]
    codes = collect_master_codes(pieces, GMAP, GROUP_NAMES)
    assert codes is not None
    assert list(codes.values()) == ['g05', 'g05']


# ---------------------------------------------------------------- assign_codes 两模式

def test_assign_codes_sequential_per_size_restart():
    # 无母版编号：码内 parse_member_sort_key 排序（上方/左/大片优先）+ 位置赋码，
    # 每码独立从 g01 起（与旧 A/B/C 同语义）
    pieces = [
        _FakePiece('k_qian', 30, _rect(0, 200, 40, 40)),   # 质心 y=220 → g01
        _FakePiece('k_hou', 30, _rect(0, 100, 30, 30)),    # → g02
        _FakePiece('k_yao', 30, _rect(0, 0, 20, 20)),      # → g03
        _FakePiece('k_yao', 32, _rect(0, 200, 60, 40)),    # 码 32 重起 → g01
    ]
    out = assign_codes(pieces, GMAP, GROUP_NAMES)
    assert [c for _, c in out[30]] == ['g01', 'g02', 'g03']
    assert [c for _, c in out[32]] == ['g01']


def test_assign_codes_master_reuse_orders_by_code():
    # 母版复用：输出按母版码数值序（UI 列序 = 码序）；无编号旁路片（ptype 无映射）
    # 续在最大母版码之后（g09 → 旁路片 g10），不与母版码冲突
    pieces = [
        _FakePiece('k_qian', 30, _rect(0, 200, 40, 40), block_name='前片g05.30'),
        _FakePiece('k_hou', 30, _rect(0, 100, 30, 30), block_name='后片g02.30'),
        _FakePiece('k_yao', 30, _rect(0, 0, 20, 20), block_name='腰g09.30'),
        _FakePiece('k_x', 30, _rect(100, 0, 10, 10), block_name='noname.旁.30'),
    ]
    out = assign_codes(pieces, GMAP, GROUP_NAMES)
    codes = [c for _, c in out[30]]
    assert codes == ['g02', 'g05', 'g09', 'g10']
    # 对应片型：后片 g02 / 前片 g05 / 腰 g09（几何序被码序取代）
    labels = compute_size_ptype_labels(pieces, GMAP, GROUP_NAMES)
    assert labels[(30, '后片')] == 'g02'
    assert labels[(30, '前片')] == 'g05'
    assert labels[(30, '腰')] == 'g09'


def test_assign_codes_master_reuse_matches_parse_and_intermediate():
    # 关键不变量 AC#5：parse 赋号（compute_size_ptype_labels）与代表裁片同源同码
    pieces = [
        _FakePiece('k_qian', 30, _rect(0, 200, 40, 40), block_name='前片g05.30'),
        _FakePiece('k_hou', 30, _rect(0, 100, 30, 30), block_name='后片g02.30'),
    ]
    out = assign_codes(pieces, GMAP, GROUP_NAMES)
    label_map = compute_size_ptype_labels(pieces, GMAP, GROUP_NAMES)
    for p, code in out[30]:
        ptype = GROUP_NAMES.get(GMAP.get(p.group_key))
        if ptype is not None:
            assert label_map[(30, ptype)] == code
