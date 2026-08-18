"""每片型代表裁片选取 + 编号口径测试（2026-08-17 编号化、2026-08-18 切 g 码）。

关键不变量：``_build_ptype_representatives`` 与 ``labeling.compute_size_ptype_labels``
（= parse 响应赋号口径）共用 ``labeling.assign_codes`` 单一真相源 —— 高级配置弹窗
列头编号徽章与上传预览 QtyMatrix 列头（同编号缩略图）指同一片；且代表取自**最小码**
首个片。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting.dxf_parser.export_dxf import GROUP_NAMES
from materialsorting.nesting_engine.labeling import compute_size_ptype_labels
from materialsorting.web.server import _build_ptype_representatives


def _rect(x: float, y: float, w: float, h: float):
    """轴对齐矩形（DXF 数学系，Y 向上），顶点质心 = (x + w/2, y + h/2)。"""
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


class _FakePiece:
    """PieceOutline duck-type（labeling / server 只读下列属性）。"""

    def __init__(self, group_key, size, polygon_mm, block_name='B', piece_index=0):
        self.group_key = group_key
        self.size = size
        self.polygon_mm = polygon_mm
        self.block_name = block_name
        self.piece_index = piece_index
        xs = [p[0] for p in polygon_mm]
        ys = [p[1] for p in polygon_mm]
        self.area_mm2 = (max(xs) - min(xs)) * (max(ys) - min(ys))
        self.net_polygon = []
        self.internal_lines = []
        self.notches = []
        self.grain_line = None


# 手写 gmap（g00=后片 g01=前片 g09=腰，与真实 GROUP_NAMES 对齐；绕开 assign_group_no
# 的 group_sort_key 对合成数据的不确定性 —— 生产链路两函数拿同一 gmap）。
GMAP = {'k_hou': 'g00', 'k_qian': 'g01', 'k_yao': 'g09'}


def _pieces():
    """两码三片型；质心 Y 决定码内排序（视觉上方优先）。

    - 码 30（最小码）：前片最上 → g01，后片居中 → g02，腰最下 → g03。
    - 码 32：排序故意反转（腰最上）→ 若代表不取最小码，编号会张冠李戴。
    """
    return [
        # 码 30：前片宽 40（供「代表取自最小码」几何断言）
        _FakePiece('k_qian', 30, _rect(0, 200, 40, 40)),   # 质心 y=220 → g01
        _FakePiece('k_hou', 30, _rect(0, 100, 30, 30)),    # 质心 y=115 → g02
        _FakePiece('k_yao', 30, _rect(0, 0, 20, 20)),      # 质心 y=10  → g03
        # 码 32：腰最上（前片宽 60，与码 30 区分）
        _FakePiece('k_yao', 32, _rect(0, 200, 60, 40)),
        _FakePiece('k_qian', 32, _rect(0, 100, 60, 30)),
        _FakePiece('k_hou', 32, _rect(0, 0, 60, 20)),
    ]


def test_reps_from_smallest_size_with_parse_aligned_labels():
    reps = _build_ptype_representatives(_pieces(), GMAP, GROUP_NAMES)
    # 三片型齐
    assert set(reps) == {'前片', '后片', '腰'}
    # 编号 = 码 30（最小码）内 parse 赋号：前片 g01 / 后片 g02 / 腰 g03
    assert reps['前片']['label'] == 'g01'
    assert reps['后片']['label'] == 'g02'
    assert reps['腰']['label'] == 'g03'
    # 代表几何取自最小码（码 30 前片宽 40；码 32 是 60）
    xs = [pt[0] for pt in reps['前片']['polygon']]
    assert max(xs) - min(xs) == 40


def test_reps_labels_match_compute_size_ptype_labels():
    pieces = _pieces()
    reps = _build_ptype_representatives(pieces, GMAP, GROUP_NAMES)
    label_map = compute_size_ptype_labels(pieces, GMAP, GROUP_NAMES)
    # 逐片型：代表编号 == parse 赋号在 (最小码 30, ptype) 的编号 —— 上传预览与
    # 高级配置弹窗「编号 → 图形」一致的核心不变量。
    for ptype, rep in reps.items():
        assert rep['label'] == label_map[(30, ptype)], ptype
