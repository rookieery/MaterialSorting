"""PLT 唛架信息表格构建单测（plt_table v5，2026-08-30 单线字 + 共线边框版）。

覆盖：
  - parse_table_payload：缺省 None / 非 dict 拒绝 / 非字符串拒绝（数字宽容转
    str）/ 字符串清洗（折空白、超长截断 + warning）
  - _plan_name_and_sets 方案名称口径（用户例逐字对拍）：
    (30+34+35)+(31+32+33)*1.5+(36)*0.5=8套 —— 每码系数 = 面积最大裁片同 pid
    计数÷2、同系数全局分组、组间按组内最小码排序
  - build_info_table 数值口径：料长=width/1000 **不含表格**、幅宽/料长/每套
    用料 3 位小数、绘图时间无秒、套数 0 守卫
  - _row_texts：14 字段序（列 0→13 = 方案名称..备注，沿 +y 逐列）+ 各字段
    格式（key/value 分离，不再「标签 值」拼单行）+ 空值 value=''
  - info_table_polylines v5 几何：外框闭合矩形 [x0,x0+36]×[Y0,Y0+L]
    （**Y0=30mm：唛架右下顶点垂直向上 3cm 起排**，v5 定案；表长 L 自适应 <
    gate−20−30，不与幅宽等长）、1 条 key|value 行分隔线（沿 y）、13 条列
    分隔线（沿 x）、key 行带最靠唛架 / value 行带在外、**单元格内容居中且离
    列边 ≥CELL_PAD=10mm**（v5 定案）、全字段统一字高、文字旋转 90°（基线沿
    +y、字厚沿 x ≈ 字高）、小门幅缩字高/压列 + warning
  - 集成 write_marker_plt(info_table=...)：PS 纸长覆盖表格（v5 共线后
    content_max = width+0+36）、**边框恒为 width_mm 不延伸**、料长不含表、
    纯 ASCII、无 LB/VS、info_table=None 与缺省逐字节一致

字体未就位（plt_text 依赖捆绑字体）→ skipif 整组跳过。
"""
from __future__ import annotations

import math
import os
from datetime import datetime

import pytest

from materialsorting import paths
from materialsorting.web.plt_table import (
    CELL_PAD_MM, N_TABLE_ROWS, ROW_BAND_H_MM, TABLE_CHAR_H_MM,
    TABLE_EDGE_PAD_MM, TABLE_GAP_MM, TABLE_W_MM, TABLE_Y_START_MM, InfoTable,
    TablePayloadError, _column_layout, _plan_name_and_sets, _row_texts,
    build_info_table, info_table_polylines, parse_table_payload, preview_rows)

_HAS_FONT = os.path.exists(paths.PLT_FONT_PATH)

pytestmark = pytest.mark.skipif(not _HAS_FONT, reason='捆绑字体未就位（resources/fonts）')


def _piece(pid: str, size: str, area: float = 100.0, n: int = 1) -> list[dict]:
    """同 pid n 副本（模拟 demand 多副本展开后的 world_pieces）。"""
    return [{'pid': pid, 'size': size, 'area_mm2': area,
             'polygon': [(0, 0), (10, 0), (10, 20), (0, 20)]} for _ in range(n)]


def _simple_world() -> list[dict]:
    """单码 28：前幅 2 副本（面积最大）+ 小片 1 → 系数 1、套数 1、片数 3。"""
    return _piece('front_28', '28', 100.0, 2) + _piece('small_28', '28', 50.0, 1)


def _user_example_world() -> list[dict]:
    """用户举例的 7 码布局：30/34/35 系数1、31/32/33 系数1.5、36 系数0.5。"""
    world = _piece('front_30', '30', 100.0, 2) + _piece('small_30', '30', 50.0, 1)
    for s in ('31', '32', '33'):
        world += _piece(f'front_{s}', s, 100.0, 3)
    for s in ('34', '35'):
        world += _piece(f'front_{s}', s, 100.0, 2)
    world += _piece('front_36', '36', 100.0, 1)
    return world


def _table(world=None, **kw) -> InfoTable:
    base = dict(width_mm=500.0, gate_mm=1480.0, density=0.8486,
                table_in=parse_table_payload({}) or {},
                now=datetime(2025, 5, 8, 15, 2, 51))
    base.update(kw)
    return build_info_table(world if world is not None else _simple_world(), **base)


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
    assert out == {'bed_no': 'A料', 'warp_shrink': '0.0%', 'weft_shrink': '0.0%',
                   'planner': '', 'style_no': 'noname', 'remark': ''}


def test_parse_bad_types_rejected():
    for bad in ([1], {'a': 1}, True):
        with pytest.raises(TablePayloadError):
            parse_table_payload({'bed_no': bad})


def test_parse_number_coerced_to_str():
    assert parse_table_payload({'bed_no': 153})['bed_no'] == '153'
    assert parse_table_payload({'warp_shrink': 1.5})['warp_shrink'] == '1.5'


def test_parse_null_treated_as_empty():
    assert parse_table_payload({'planner': None})['planner'] == ''


def test_parse_string_cleaning_and_truncation(caplog):
    with caplog.at_level('WARNING'):
        out = parse_table_payload({'remark': 'a\r\nb\t c', 'planner': '张' * 25})
    assert out['remark'] == 'a b c'
    assert out['planner'] == '张' * 20
    assert any('截断' in r.message for r in caplog.records)


# --------------------------------------------- 方案名称 / 套数

def test_plan_name_user_example_exact():
    """用户例逐字对拍：(30+34+35)+(31+32+33)*1.5+(36)*0.5=8套。"""
    name, sets = _plan_name_and_sets(_user_example_world())
    assert name == '(30+34+35)+(31+32+33)*1.5+(36)*0.5=8套'
    assert sets == 8.0


def test_plan_name_single_size_coeff_one():
    name, sets = _plan_name_and_sets(_simple_world())
    assert name == '(28)=1套'
    assert sets == 1.0


def test_plan_name_coeff_two():
    """前幅+后幅各 2 副本（同码 4 片最大 pid）→ 系数 2。"""
    name, sets = _plan_name_and_sets(_piece('front_28', '28', 100.0, 4))
    assert name == '(28)*2=2套'
    assert sets == 2.0


def test_plan_name_empty_world():
    assert _plan_name_and_sets([]) == ('--', 0.0)


def test_plan_name_largest_piece_wins():
    """面积最大裁片的 pid 计数才是分子 —— 小面积片副本再多不计入。"""
    world = (_piece('front_30', '30', 100.0, 2) + _piece('small_30', '30', 50.0, 5)
             + _piece('front_31', '31', 80.0, 2))
    # 30：最大 pid front_30 计 2 → 系数 1；31：front_31 计 2 → 系数 1
    assert _plan_name_and_sets(world)[0] == '(30+31)=2套'


# --------------------------------------------- build_info_table 口径

def test_build_info_table_values():
    t = _table(_user_example_world(),
               table_in=parse_table_payload({'bed_no': '153'}) or {})
    assert t.fabric_len_m == pytest.approx(0.5)        # width/1000，不含表格/引导
    assert t.gate_m == pytest.approx(1.48)
    assert t.utilization_pct == pytest.approx(84.86)
    assert t.per_set_m == pytest.approx(0.5 / 8.0)     # 料长÷套数
    assert t.sets_count == 8.0
    assert t.total_pieces == len(_user_example_world())
    assert t.draw_time_str == '2025-05-08 15:02'       # 无秒
    assert t.bed_no == '153'


def test_build_info_table_zero_sets_guard():
    t = build_info_table([], width_mm=100, gate_mm=1480, density=0.5,
                         table_in=parse_table_payload({}) or {},
                         now=datetime(2025, 1, 1))
    assert t.plan_name == '--'
    assert t.sets_count == 0.0
    assert t.per_set_m == 0.0


# --------------------------------------------- _row_texts 字段序与格式

def test_row_texts_fields_and_formats():
    """14 字段 (key, value) 对：列 0=方案名称..列 13=备注；key/value 分离。"""
    rows = _row_texts(_table())
    assert len(rows) == 14
    assert rows[0] == ('方案名称', '(28)=1套')          # 列 0（视图最左）
    assert rows[1] == ('床次', 'A料')
    assert rows[2] == ('经纱缩水', '0.0%')
    assert rows[3] == ('纬纱缩水', '0.0%')
    assert rows[4] == ('利用率', '84.86%')
    assert rows[5] == ('幅宽', '1.480m')
    assert rows[6] == ('料长', '0.500m')
    assert rows[7] == ('本床包含套数', '1')
    assert rows[8] == ('每套用料', '0.500m')            # 0.5÷1，3 位小数
    assert rows[9] == ('片数', '3')
    assert rows[10] == ('排料师', '')                   # 默认空 → value='' 只渲染 key
    assert rows[11] == ('绘图时间', '2025-05-08 15:02')
    assert rows[12] == ('样板号', 'noname')
    assert rows[13] == ('备注', '')                     # 列 13（视图最右）


def test_row_texts_dash_when_empty():
    rows = _row_texts(_table([], density=0.0))
    assert rows[0] == ('方案名称', '--')
    assert rows[7] == ('本床包含套数', '0')
    assert rows[4] == ('利用率', '--')
    assert rows[8] == ('每套用料', '--')


# --------------------------------------------- preview_rows 预览行（弹窗端点消费）

def test_preview_rows_order_flags_and_alignment():
    """preview_rows（/api/plt-table-preview 消费，2026-08-31）：key 序 / manual
    标记序锁 _ROW_META（列序权威），(label, value) 逐槽 == _row_texts ——
    preview_rows 不自带第二份文案，防槽位元数据与渲染序脱钩。"""
    t = _table(_user_example_world())
    rows = preview_rows(t)
    assert [r['key'] for r in rows] == [
        'plan_name', 'bed_no', 'warp_shrink', 'weft_shrink', 'utilization',
        'gate', 'fabric_len', 'sets', 'per_set', 'pieces', 'planner',
        'draw_time', 'style_no', 'remark']
    assert [r['manual'] for r in rows] == [
        False, True, True, True, False, False, False, False, False, False,
        True, False, True, True]
    assert [(r['label'], r['value']) for r in rows] == _row_texts(t)
    assert rows[0]['value'] == '(30+34+35)+(31+32+33)*1.5+(36)*0.5=8套'
    assert rows[4]['value'] == '84.86%'
    assert rows[9]['value'] == str(len(_user_example_world()))
    # manual 行 value = 手输默认值（弹窗手输由前端本地草稿渲染，仅供参考）
    assert rows[1]['value'] == 'A料'
    assert rows[12]['value'] == 'noname'


# --------------------------------------------- _column_layout 自适应列宽

def test_column_layout_adaptive_total_under_gate():
    """常规门幅：12mm 标称字高不缩，Σ列宽自适应且 ≤ gate − 20 − 30（起始 30mm
    后的可用表长）。"""
    _pairs, char_h, widths = _column_layout(_table(_user_example_world()),
                                            gate_mm=1480.0)
    assert len(widths) == N_TABLE_ROWS
    assert char_h == TABLE_CHAR_H_MM                  # 门幅充裕不缩字
    total = sum(widths)
    assert total <= 1480.0 - TABLE_EDGE_PAD_MM - TABLE_Y_START_MM + 0.01
    assert total > 400.0                              # 内容真实存在（自适应非定长）
    # 方案名称列（value 最长）明显宽于窄列（如 床次）
    assert widths[0] > widths[1]
    # v5：列宽含 2×10mm 内衬（内容离列左右边 ≥1cm）
    assert all(w >= 2.0 * CELL_PAD_MM for w in widths)


def test_column_layout_tiny_gate_shrinks_then_squeezes(caplog):
    """小门幅：先缩字高到 7mm 下限、仍超则等比压列，Σ列宽恒 ≤ gate−20−30。"""
    with caplog.at_level('WARNING'):
        _pairs, char_h, widths = _column_layout(_table(_user_example_world()),
                                                gate_mm=400.0)
    assert char_h < TABLE_CHAR_H_MM                   # 触发缩字高
    assert any('门幅' in r.message and '偏小' in r.message for r in caplog.records)
    assert sum(widths) <= 400.0 - TABLE_EDGE_PAD_MM - TABLE_Y_START_MM + 0.01


# --------------------------------------------- info_table_polylines v5 几何

# table_x0 = width_mm + TABLE_GAP_MM(0)：外框左缘与唛架右边框**共用一条线**
X0 = 500.0 + TABLE_GAP_MM
GATE = 1480.0
XM = X0 + ROW_BAND_H_MM          # key|value 行带边界


def _split(out):
    """→ (外框, 分隔线列表, 文本笔画列表)。

    v5 单线字起文字笔画开放（closed=False），与分隔线同旗标 —— 改按几何分类：
    分隔线 = 2 点轴对齐直线且跨度 ≥20mm（外框沿 x 跨 36mm / 行分隔沿 y 贯穿
    表长），文字单笔 ≤1 字高（12mm）恒短于 20mm。
    """
    frame = out[0]
    seps, texts = [], []
    for o in out[1:]:
        pts = o[1]
        is_sep = (len(pts) == 2
                  and (abs(pts[0][0] - pts[1][0]) < 1e-6
                       or abs(pts[0][1] - pts[1][1]) < 1e-6)
                  and math.hypot(pts[1][0] - pts[0][0],
                                 pts[1][1] - pts[0][1]) >= 20.0)
        (seps if is_sep else texts).append(o)
    return frame, seps, texts


def test_polylines_frame_adaptive_length():
    """外框闭合矩形 [x0, x0+36]×[Y0, Y0+L]：Y0=30mm（右下顶点向上 3cm，v5）、
    **L 自适应**（top < gate−20，不与幅宽等长）；全部点落在表格区无越界。"""
    out = info_table_polylines(_table(), table_x0=X0, gate_mm=GATE)
    assert out, '应有笔画'
    closed0, pts0 = out[0]
    assert closed0 and len(pts0) == 4
    assert {round(v, 2) for v in (p[0] for p in pts0)} == {X0, X0 + TABLE_W_MM}
    ys = {round(v, 2) for v in (p[1] for p in pts0)}
    top = max(ys)
    assert ys == {TABLE_Y_START_MM, round(top, 2)}    # 底边 = 30mm 起始线
    assert top < GATE - TABLE_EDGE_PAD_MM + 0.01      # 自适应表长（v3 满门幅已否）
    assert top > 300.0                                # 14 列内容真实占位
    for _c, pts in out:
        for x, y in pts:
            assert X0 - 0.01 <= x <= X0 + TABLE_W_MM + 0.01
            assert TABLE_Y_START_MM - 0.01 <= y <= top + 0.01


def test_polylines_row_divider_and_column_dividers():
    """1 条 key|value 行分隔线（沿 y 贯穿表长）+ 13 条列分隔线（沿 x 贯穿表宽，
    y 边界 = 30 + 累计列宽单调递增）。"""
    out = info_table_polylines(_table(), table_x0=X0, gate_mm=GATE)
    frame, seps, _texts = _split(out)
    top = max(p[1] for p in frame[1])
    along_y = [s for s in seps if abs(s[1][0][0] - s[1][1][0]) < 1e-6]
    along_x = [s for s in seps if abs(s[1][0][1] - s[1][1][1]) < 1e-6]
    assert len(along_y) == 1                          # key|value 行分隔线
    pts = along_y[0][1]
    assert {round(p[0], 2) for p in pts} == {round(XM, 2)}
    assert {round(p[1], 2) for p in pts} == {TABLE_Y_START_MM, round(top, 2)}
    assert len(along_x) == N_TABLE_ROWS - 1           # 13 条列分隔线
    edges = [round(s[1][0][1], 2) for s in along_x]
    assert edges == sorted(edges)
    assert TABLE_Y_START_MM < min(edges) < max(edges) < top


def test_polylines_key_band_nearer_marker_value_band_outer():
    """key 行带最靠唛架（x ∈ [x0, x0+18]）、value 行带在外（x > 边界），
    单条文字笔画不跨行带（v4 两行网格核心结构；v5 单线字下降部 ≤0.13em×12
    ≈1.5mm，key 基线 x0+15 下探后仍不越界）。"""
    out = info_table_polylines(_table(_user_example_world()), table_x0=X0,
                               gate_mm=GATE)
    _frame, _seps, texts = _split(out)
    assert texts, '应有文本笔画'
    key_strokes = [pts for _c, pts in texts
                   if all(p[0] <= XM + 0.5 for p in pts)]
    val_strokes = [pts for _c, pts in texts
                   if all(p[0] >= XM - 0.5 for p in pts)]
    assert key_strokes and val_strokes                # 两行带均有文字
    assert len(key_strokes) + len(val_strokes) == len(texts)  # 无跨带笔画
    # key 行带文字全部落在 [x0, x0+18+0.5]（视图第一行 = key）
    for pts in key_strokes:
        assert all(X0 - 0.01 <= p[0] <= XM + 0.5 for p in pts)
    # value 行带文字全部 ≥ 边界（视图第二行 = value）
    for pts in val_strokes:
        assert all(p[0] >= XM - 0.5 for p in pts)


def test_polylines_uniform_char_height():
    """全字段统一字高（v4 定案）：任何文字笔画 x 向厚度 ≤ 12mm+3（v3 方案名称
    36mm 大字已否决；单线汉字归一盒 0.88em、括号全高 ~0.97em 均在此内）。"""
    out = info_table_polylines(_table(_user_example_world()), table_x0=X0,
                               gate_mm=GATE)
    _frame, _seps, texts = _split(out)
    for _c, pts in texts:
        xs = [p[0] for p in pts]
        assert max(xs) - min(xs) <= TABLE_CHAR_H_MM + 3.0


def test_polylines_text_rotated_90_columns_along_y():
    """文字旋转 90°：基线沿 +y（长值 y 跨度远大于字厚）、**单元格内容居中**——
    value 为空的列宽 = key 宽 + 2×10mm，key 起画 y ≈ Y0 + CELL_PAD（离列边
    ≥1cm，v5 定案）、字顶朝 −x（笔画 x ≤ 基线+2）。"""
    out = info_table_polylines(_table(), table_x0=X0, gate_mm=GATE)
    _frame, _seps, texts = _split(out)
    all_pts = [p for _c, pts in texts for p in pts]
    # 最靠下的文字 = 空 value 列的 key，居中后起画 ≈ Y0+CELL_PAD（容差 1.5）
    assert min(p[1] for p in all_pts) == pytest.approx(
        TABLE_Y_START_MM + CELL_PAD_MM, abs=1.5)
    # 任何文字墨迹不侵入单元格左右 10mm 内衬（居中 + fit 封顶共同保证）
    assert min(p[1] for p in all_pts) >= TABLE_Y_START_MM + CELL_PAD_MM - 0.5
    # key 行带基线 = x0+9+6 = x0+15：字顶朝 −x；单线 ASCII 下降部（括号
    # −0.12em）下探 ~1.5mm → 允许到基线+3.5mm（仍在 18mm 行带内）
    key_pts = [p for _c, pts in texts for p in pts if p[0] <= XM + 0.5]
    assert max(p[0] for p in key_pts) <= X0 + ROW_BAND_H_MM * 0.5 \
        + TABLE_CHAR_H_MM * 0.5 + 3.5
    # 基线沿 +y：文本整体 y 跨度（14 列自适应表长）远大于 x 跨度（36mm 表宽）
    # —— 文字长轴沿 y 展开（每条折线是单字形轮廓，断言用整体跨度）
    assert (max(p[1] for p in all_pts) - min(p[1] for p in all_pts)) \
        > (max(p[0] for p in all_pts) - min(p[0] for p in all_pts)) * 5.0


def test_polylines_tiny_gate_no_clip_all_columns_present(caplog):
    """小门幅：缩字高/压列 + warning，全部点仍 y ≤ gate，14 列文字全在
    （列结构不因门幅变小而丢字段）。"""
    with caplog.at_level('WARNING'):
        out = info_table_polylines(_table(gate_mm=400.0), table_x0=X0,
                                   gate_mm=400.0)
    assert any('门幅' in r.message and '偏小' in r.message for r in caplog.records)
    ys = [p[1] for _c, pts in out for p in pts]
    assert max(ys) <= 400.0 + 0.01
    _frame, _seps, texts = _split(out)
    # 14 列：每列都应有 key 文字（value 空的列只有 key）
    along_x = [s for s in _seps if abs(s[1][0][1] - s[1][1][1]) < 1e-6]
    edges = ([TABLE_Y_START_MM] + [s[1][0][1] for s in along_x] + [max(ys)])
    for i in range(N_TABLE_ROWS):
        lo, hi = edges[i], edges[i + 1]
        assert any(lo <= p[1] <= hi for _c, pts in texts for p in pts), \
            f'第 {i} 列无笔画'


# --------------------------------------------- 集成 write_marker_plt

def test_write_marker_plt_table_paper_border_and_ascii():
    from materialsorting.web.export import write_marker_plt
    t = _table(_user_example_world(),
               table_in=parse_table_payload({'bed_no': '153'}) or {})
    raw = write_marker_plt(_user_example_world(), width_mm=500.0, gate_mm=1480.0,
                           title='M1787', info_table=t)
    out = raw.decode('ascii')                    # 中文 → 轮廓坐标，全 ASCII
    assert 'LB' not in out and 'VS' not in out
    # PS 纸长 = (引导 20 + 内容 500+0+36 + 尾 10) × 40 = 22640（覆盖表格区；
    # v5 共线 gap=0，比 v4 的 23440 短 800 = 20mm×40）
    assert out.split('\r\n')[0] == 'IN;PS22640;SP1;PW0.08;'
    # 表格外框右缘 x=(20+500+0+36)×40=22240 存在；v4 间隙版角点 23040 不存在
    assert '22240,' in out
    assert '23040,' not in out
    # **边框不延伸**：边框 x1 = width_mm=500 → +引导 = 520×40=20800 竖边存在
    # （与表格外框左缘共用一条线：500×40+引导 同一 x）
    assert '20800,' in out
    assert '44200,' not in out and '44520,' not in out and '47600,' not in out
    assert '37080,' not in out                   # v3 表宽 387 的外框右缘已废
    # 料长不含表格：0.500m（3 位小数）由 _row_texts 单测锁定，这里锁纸长口径


def test_write_marker_plt_none_equals_omitted():
    """零回归红线：info_table=None 与完全不传 → 逐字节一致。"""
    from materialsorting.web.export import write_marker_plt
    world = _simple_world()
    kw = dict(width_mm=500.0, gate_mm=1480.0, title='M1787')
    a = write_marker_plt(world, info_table=None, **kw)
    b = write_marker_plt(world, **kw)
    assert a == b


def test_write_marker_plt_table_no_y_clipping_on_tiny_gate(caplog):
    """小门幅下表格笔画不经 y≤gate 裁剪（元数据）；门幅偏小 warning 提示。"""
    from materialsorting.web.export import write_marker_plt
    with caplog.at_level('WARNING'):
        raw = write_marker_plt(_simple_world(), width_mm=500.0, gate_mm=400.0,
                               title='t', info_table=_table(gate_mm=400.0))
    out = raw.decode('ascii')
    assert any('门幅' in r.message and '偏小' in r.message for r in caplog.records)
    assert '22240,' in out                       # 外框右缘完整画出


# --------------------------------------------- 毛版左表副本（clean=True，2026-08-31）


def _pu_polys(out: str) -> list[list[str]]:
    """PLT 文本 → PU 起笔折线坐标 token 流（PD 分块续画拼回，同 test_export_plt）。"""
    polys, cur = [], None
    for line in out.split('\r\n'):
        if line.startswith('PU') and ',' in line:
            if cur:
                polys.append(cur)
            cur = line[2:].rstrip(';').split(',')
        elif line.startswith('PD'):
            cur.extend(line[2:].rstrip(';').split(','))
    if cur:
        polys.append(cur)
    return polys


def test_write_marker_plt_clean_left_table_copy():
    """毛版 + 表格：唛架左端再画一份同内容表格（对齐生产参考件左表结构）。

    - X 引导扩为 20+0+36=56：PS = (56 + 536 + 10)×40 = 24080；
    - 左表三竖缘 = 外框左 (−36+56)×40=800、key|value 分隔 1520、value 带外缘
      (0+56)×40=2240 **与门幅框左缘共线**（参考件 x=24 处 n=2 同构）；
    - 左右两表**逐折线全等**（+500mm=+20000u 位移）：同 info_table → 同
      _column_layout 布局，文字朝向与世界坐标同向（无镜像）。
    """
    from materialsorting.web.export import write_marker_plt
    world = _user_example_world()
    t = _table(world, table_in=parse_table_payload({'bed_no': '153'}) or {})
    raw = write_marker_plt(world, width_mm=500.0, gate_mm=1480.0, title='',
                           info_table=t, clean=True)
    out = raw.decode('ascii')
    assert out.split('\r\n')[0] == 'IN;PS24080;SP1;PW0.08;'
    # 左表外框左下角 (−36, 30)、分隔线下端 (−18, 30) → +56 引导 +36 平移 → ×40
    assert 'PU800,2640;' in out and 'PU1520,2640;' in out
    # 门幅框左下角 (0,0) → 2240,1440：与左表 value 带外缘共用一条竖线
    assert 'PU2240,1440;' in out
    # 右表原样：左缘 (500+56)×40=22240 起画、外缘 (536+56)×40=23680
    assert 'PU22240,2640;' in out and '23680,' in out
    # 左右两表折线集全等（模 500mm 位移）：门幅框 x∈[2240,22240] 与裁片
    # x∈[2240,2640] 按区间排除后，左表 = max_x≤2240、右表 = min_x≥22240
    polys = _pu_polys(out)
    xtok = lambda p: [int(p[i]) for i in range(0, len(p), 2)]
    left = [p for p in polys if max(xtok(p)) <= 2240]
    right = [p for p in polys if min(xtok(p)) >= 22240]
    # 两表 x0 差 = width−(−(gap+W)) = 536mm = 21440u（左表 x0=−36、右表 x0=+500）
    shift = lambda p: [str(int(p[i]) + 21440) if i % 2 == 0 else p[i]
                       for i in range(len(p))]
    assert left and right
    assert sorted(map(tuple, map(shift, left))) == sorted(map(tuple, right))


def test_write_marker_plt_full_has_no_left_table():
    """全量版（clean=False）带表格：只有右表，无左表（X 引导仍 20）。"""
    from materialsorting.web.export import write_marker_plt
    world = _user_example_world()
    t = _table(world, table_in=parse_table_payload({'bed_no': '153'}) or {})
    out = write_marker_plt(world, width_mm=500.0, gate_mm=1480.0, title='',
                           info_table=t).decode('ascii')
    assert out.split('\r\n')[0] == 'IN;PS22640;SP1;PW0.08;'   # (20+536+10)×40
    assert 'PU800,2640;' not in out                            # 无左表角点
    assert 'PU1520,2640;' not in out
