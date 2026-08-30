"""PLT 唛架信息表格构建单测（plt_table，2026-08-30）。

覆盖：
  - parse_table_payload：缺省 None / 非 dict 拒绝 / ply_count 非法值拒绝 /
    字符串清洗（折空白、超长截断 + warning）
  - build_info_table 数值口径（生产件 PC-20250508NJIF 已对拍）：
    用料(m) 含表格段、单耗 = 用料÷每层件数、共N件 = 件数×层数、日期格式
  - info_table_polylines 几何：点全部落在表格区 [x0, x0+565]×[0,300]、
    列分隔线 y=150 存在、空值格仍有标签笔画、文本 closed/分隔线 open
  - shrink-to-fit：超长值压字高到下限后尾部截断
  - 集成 write_marker_plt(info_table=...)：PS 纸长/边框延伸、纯 ASCII、无 LB

字体未就位（plt_text 依赖捆绑字体）→ skipif 整组跳过。
"""
from __future__ import annotations

import os
from datetime import datetime

import pytest

from materialsorting import paths
from materialsorting.web.plt_table import (
    TABLE_GAP_MM, TABLE_LEN_MM, InfoTable, TablePayloadError,
    build_info_table, info_table_polylines, parse_table_payload)

_HAS_FONT = os.path.exists(paths.PLT_FONT_PATH)

pytestmark = pytest.mark.skipif(not _HAS_FONT, reason='捆绑字体未就位（resources/fonts）')


def _pieces(n: int = 2) -> list[dict]:
    return [{'pid': f'P{i}', 'polygon': [(0, 0), (10, 0), (10, 20), (0, 20)]}
            for i in range(n)]


def _table(**kw) -> InfoTable:
    base = dict(width_mm=500.0, gate_mm=1480.0, density=0.8486,
                table_in=parse_table_payload({}) or {}, now=datetime(2025, 5, 8, 15, 2, 51))
    base.update(kw)
    return build_info_table(_pieces(2), **base)


# --------------------------------------------- parse_table_payload

def test_parse_none_returns_none():
    assert parse_table_payload(None) is None


def test_parse_non_dict_rejected():
    with pytest.raises(TablePayloadError):
        parse_table_payload([1, 2])
    with pytest.raises(TablePayloadError):
        parse_table_payload('x')


def test_parse_defaults():
    out = parse_table_payload({})
    assert out == {'bed_no': '', 'ply_count': 1, 'lay_method': '单向',
                   'planner': 'noname', 'style_no': '', 'remark': ''}


@pytest.mark.parametrize('bad', ['0', -1, 0, 1.5, 1000, True, 'abc'])
def test_parse_bad_ply_count_rejected(bad):
    with pytest.raises(TablePayloadError):
        parse_table_payload({'ply_count': bad})


def test_parse_ply_count_int_from_float():
    assert parse_table_payload({'ply_count': 8.0})['ply_count'] == 8


def test_parse_string_cleaning_and_truncation(caplog):
    with caplog.at_level('WARNING'):
        out = parse_table_payload({'remark': 'a\r\nb\t c', 'planner': '张' * 25})
    assert out['remark'] == 'a b c'
    assert out['planner'] == '张' * 20
    assert any('截断' in r.message for r in caplog.records)


def test_parse_number_coerced_to_str():
    assert parse_table_payload({'bed_no': 153})['bed_no'] == '153'


# --------------------------------------------- build_info_table 口径

def test_build_info_table_values():
    """生产口径对拍：用料含表格段 / 单耗=用料÷件数 / 共N件=件数×层数 / 日期格式。"""
    t = _table(table_in=parse_table_payload({'ply_count': 8, 'bed_no': '153'}))
    assert t.fabric_len_m == pytest.approx((500.0 + TABLE_GAP_MM + TABLE_LEN_MM) / 1000.0)   # 1.085
    assert t.per_layer_pieces == 2
    assert t.unit_consumption_m == pytest.approx(1.085 / 2)
    assert t.utilization_pct == pytest.approx(84.86)
    assert t.datetime_str == '2025-05-08 15:02:51'
    assert t.ply_count == 8
    assert t.bed_no == '153'
    # 共N件 = 2×8 = 16（在渲染文本里，间接经 polylines 有笔画断言）


def test_build_info_table_zero_pieces_guard():
    t = build_info_table([], width_mm=100, gate_mm=1480, density=0.5,
                         table_in={}, now=datetime(2025, 1, 1))
    assert t.per_layer_pieces == 0
    assert t.unit_consumption_m == 0.0


# --------------------------------------------- info_table_polylines 几何

def test_polylines_in_table_region():
    out = info_table_polylines(_table(), table_x0=520.0)
    assert out, '应有笔画'
    x0 = 520.0
    for closed, pts in out:
        for x, y in pts:
            assert x0 - 0.01 <= x <= x0 + TABLE_LEN_MM + 0.01
            assert -0.01 <= y <= 300.0 + 0.01


def test_polylines_have_separator_and_closed_flags():
    out = info_table_polylines(_table(), table_x0=520.0)
    opens = [pts for closed, pts in out if not closed]
    # 列分隔线 y=150 横贯
    assert any(len(pts) == 2 and all(abs(p[1] - 150.0) < 0.01 for p in pts)
               for pts in opens)
    # 行间细分线（开放）与文本轮廓（闭合）并存
    assert sum(1 for closed, _ in out if closed) > 50    # 12 格字形轮廓
    assert len(opens) >= 6 + 4 + 1                        # 6+4 行间线 + 1 列线


def test_polylines_empty_value_cells_still_draw_label():
    """空备注/床次/款式 → 值为空但标签仍渲染（笔画数远大于 0 即可，
    精确空值语义由 _cell_texts 覆盖）。"""
    from materialsorting.web.plt_table import _cell_texts
    cells = _cell_texts(_table())
    assert cells[0][0] == ['备注']            # remark 空 → 仅标签
    assert cells[4][0] == ['床次']
    labels = {segs[0] for segs, _ in cells}
    assert '面料利用率' in labels and '用料（米）' in labels


def test_polylines_utilization_dash_when_no_density():
    t = _table(density=0.0)
    out = info_table_polylines(t, table_x0=520.0)
    assert out    # '--' 仍渲染（不崩、不空）


def test_shrink_long_remark():
    """60 字备注：18mm×60=1080mm 远超 126mm 可用宽 → 压到下限 9mm 后尾部截断。"""
    from materialsorting.web.plt_table import _cell_strokes
    strokes = _cell_strokes(['长' * 60], [], row_cx=100.0, y0=12.0)
    ys = [p[1] for st in strokes for p in st]
    xs = [p[0] for st in strokes for p in st]
    assert max(ys) - min(ys) <= 126.0 + 1.0   # 若未截断会拉到 ~1000mm
    # 压到下限 9mm em：墨迹厚度 ~8.3mm（未缩时 18mm em 墨迹 ~16.6mm）
    assert max(xs) - min(xs) < 9.5


# --------------------------------------------- 集成 write_marker_plt

def test_write_marker_plt_with_table_extends_paper_and_border():
    from materialsorting.web.export import write_marker_plt
    world = _pieces(2) + [{'pid': 'PX', 'polygon': [(0, 0), (100, 0), (100, 200),
                                                    (0, 200)]}]
    t = _table(table_in=parse_table_payload({'ply_count': 8, 'bed_no': '153',
                                             'planner': 'noname'}))
    raw = write_marker_plt(world, width_mm=500.0, gate_mm=1480.0,
                           title='M1787', info_table=t)
    out = raw.decode('ascii')                    # 中文 → 轮廓坐标，全 ASCII
    assert 'LB' not in out and 'VS' not in out
    # PS 纸长 = (引导 20 + 内容总长 500+20+565 + 尾 10) × 40 = 44600
    assert out.split('\r\n')[0] == 'IN;PS44600;SP1;PW0.08;'
    # 边框延伸到表格末端：x=(1085+20)×40=44200 的竖边角点存在
    assert '44200,' in out


def test_write_marker_plt_table_no_y_clipping_on_tiny_gate(caplog):
    """小门幅下表格文字不削平（元数据不过 y≤gate 裁剪）+ warning 提示。"""
    from materialsorting.web.export import write_marker_plt
    t = _table(gate_mm=200.0)
    with caplog.at_level('WARNING'):
        raw = write_marker_plt(_pieces(2), width_mm=500.0, gate_mm=200.0,
                               title='t', info_table=t)
    out = raw.decode('ascii')
    # 表格列2 文字顶到 y≈288mm；若被削平则全部 y ≤ 200×40=8000
    ys = []
    for line in out.split('\r\n'):
        for tok in line.replace(';', ',').split(','):
            if tok.strip().isdigit():
                ys.append(int(tok))
    # 成对坐标取 y（奇数位）——粗断言：存在 y > 200×40 的表格笔画
    ys_paired = [v for i, v in enumerate(ys) if i % 2 == 1]
    assert any(v > 200 * 40 for v in ys_paired)
    assert any('压门幅' in r.message for r in caplog.records)
