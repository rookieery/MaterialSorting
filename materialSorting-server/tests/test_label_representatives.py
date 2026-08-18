"""每 g 码代表裁片选取测试（v2：label 键，取代旧 ptype 键）。

关键不变量：``_build_label_representatives`` 与 ``_build_parse_payload`` 共用
``labeling.assign_codes`` 单一真相源 —— 高级配置弹窗列头 g 码与上传预览 QtyMatrix
列头（同码缩略图）指同一片；且代表取自**最小码**首个有效片。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting.web.server import _build_label_representatives


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


def _pieces():
    """两码两组（group_key 即 block 模板身份）；几何故意错开验证代表取最小码。

    - 码 30（最小码）：k_a 组 → g01，k_b 组 → g02（group_key 字典序，T4）。
    - 码 32：两组几何上下互换 —— 若代表不取最小码，几何就张冠李戴。
    - size=None 旁路片：不参与代表（无码可排）。
    """
    return [
        # 码 30：k_a 宽 40（供「代表取自最小码」几何断言）
        _FakePiece('k_a#0', 30, _rect(0, 200, 40, 40)),
        _FakePiece('k_b#0', 30, _rect(0, 100, 30, 30)),
        # 码 32：k_a 宽 60（与码 30 区分）
        _FakePiece('k_b#0', 32, _rect(0, 200, 60, 40)),
        _FakePiece('k_a#0', 32, _rect(0, 100, 60, 30)),
        # size=None 片（无码组，不产生代表）
        _FakePiece('k_x#0', None, _rect(0, 0, 10, 10)),
    ]


def test_reps_keyed_by_label_from_smallest_size():
    reps = _build_label_representatives(_pieces())
    # 两 g 码齐（键 = g 码，非 ptype）
    assert set(reps) == {'g01', 'g02'}
    assert reps['g01']['label'] == 'g01'
    assert reps['g02']['label'] == 'g02'
    # 代表几何取自最小码（码 30 g01 宽 40；码 32 是 60）
    xs = [pt[0] for pt in reps['g01']['polygon']]
    assert max(xs) - min(xs) == 40
    xs = [pt[0] for pt in reps['g02']['polygon']]
    assert max(xs) - min(xs) == 30


def test_reps_carry_5_layers_and_label():
    reps = _build_label_representatives(_pieces())
    for label, rep in reps.items():
        assert rep['label'] == label
        # 5 层字段白名单（layer-aware 前端渲染契约）
        assert {'label', 'polygon', 'net_polygon', 'internal_lines',
                'notches', 'grain_line'} <= set(rep)
        assert rep['grain_line'] is None   # FakePiece 无布纹线
