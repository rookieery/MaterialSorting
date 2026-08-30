"""PLT 唛架信息表格构建单测（plt_table v3，2026-08-30 旋转 90° 生产同款版式）。

覆盖：
  - parse_table_payload：缺省 None / 非 dict 拒绝 / 非字符串拒绝（数字宽容转
    str）/ 字符串清洗（折空白、超长截断 + warning）
  - _plan_name_and_sets 方案名称口径（用户例逐字对拍）：
    (30+34+35)+(31+32+33)*1.5+(36)*0.5=8套 —— 每码系数 = 面积最大裁片同 pid
    计数÷2、同系数全局分组、组间按组内最小码排序
  - build_info_table 数值口径：料长=width/1000 **不含表格**、幅宽/料长/每套
    用料 3 位小数、绘图时间无秒、套数 0 守卫
  - _cell_texts：14 行序（row0→row13 = 方案名称..备注，沿 +x 逐行）+ 各行
    格式（标签空格值，生产口径）+ 空值只渲染标签
  - info_table_polylines v3 几何：外框闭合矩形 [x0,x0+W]×[0,gate]、13 条沿 y
    行间分隔线、14 行沿 +x 堆叠（row0 方案名称大字带最靠唛架）、文字旋转
    90°（基线沿 +y、字厚沿 x ≈ 字高）、小门幅文字 shrink + warning
  - 集成 write_marker_plt(info_table=...)：PS 纸长覆盖表格、**边框恒为
    width_mm 不延伸**、料长不含表、纯 ASCII、无 LB/VS、info_table=None 与
    缺省逐字节一致

字体未就位（plt_text 依赖捆绑字体）→ skipif 整组跳过。
"""
from __future__ import annotations

import os
from datetime import datetime

import pytest

from materialsorting import paths
from materialsorting.web.plt_table import (
    PLAN_CHAR_H_MM, PLAN_ROW_PITCH_MM, TABLE_CHAR_H_MM, TABLE_GAP_MM,
    TABLE_PAD_X_MM, TABLE_ROW_PITCH_MM, TABLE_TEXT_Y0_MM, TABLE_W_MM,
    InfoTable, TablePayloadError, _plan_name_and_sets, _row_center_x,
    build_info_table, info_table_polylines, parse_table_payload)

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


# --------------------------------------------- _cell_texts 行序与格式

def test_cell_texts_rows_and_formats():
    from materialsorting.web.plt_table import _cell_texts
    cells = _cell_texts(_table())
    assert len(cells) == 14
    assert cells[0] == '方案名称 (28)=1套'             # row0 最靠唛架（生产大字块位）
    assert cells[1] == '床次 A料'
    assert cells[2] == '经纱缩水 0.0%'
    assert cells[3] == '纬纱缩水 0.0%'
    assert cells[4] == '利用率 84.86%'
    assert cells[5] == '幅宽 1.480m'
    assert cells[6] == '料长 0.500m'
    assert cells[7] == '本床包含套数 1'
    assert cells[8] == '每套用料 0.500m'               # 0.5÷1，3 位小数
    assert cells[9] == '片数 3'
    assert cells[10] == '排料师'                       # 默认空 → 只渲染标签
    assert cells[11] == '绘图时间 2025-05-08 15:02'
    assert cells[12] == '样板号 noname'
    assert cells[13] == '备注'                         # row13 最远端


def test_cell_texts_dash_when_empty():
    from materialsorting.web.plt_table import _cell_texts
    cells = _cell_texts(_table([], density=0.0))
    assert cells[0] == '方案名称 --'
    assert cells[7] == '本床包含套数 0'
    assert cells[4] == '利用率 --'
    assert cells[8] == '每套用料 --'


# --------------------------------------------- info_table_polylines v3 几何

X0 = 520.0
GATE = 1480.0


def _split(out):
    """→ (外框, 分隔线列表, 文本笔画列表)。"""
    frame = out[0]
    seps = [o for o in out[1:] if not o[0]]
    texts = [o for o in out[1:] if o[0]]
    return frame, seps, texts


def test_polylines_frame_and_region():
    out = info_table_polylines(_table(), table_x0=X0, gate_mm=GATE)
    assert out, '应有笔画'
    closed0, pts0 = out[0]
    assert closed0 and len(pts0) == 4
    assert {round(v, 2) for v in (p[0] for p in pts0)} == {X0, X0 + TABLE_W_MM}
    assert {round(v, 2) for v in (p[1] for p in pts0)} == {0.0, GATE}
    # 全部点落在表格区 x∈[x0, x0+W]、y∈[0, gate]（无越界，不裁剪口径下自然满足）
    for _c, pts in out:
        for x, y in pts:
            assert X0 - 0.01 <= x <= X0 + TABLE_W_MM + 0.01
            assert -0.01 <= y <= GATE + 0.01


def test_polylines_row_separators_along_y():
    """13 条行间分隔线：沿 y 贯穿 0..gate、x 在行带边界上（生产视图=水平细线）。"""
    out = info_table_polylines(_table(), table_x0=X0, gate_mm=GATE)
    _frame, seps, _texts = _split(out)
    assert len(seps) == 13
    for k, (closed, pts) in enumerate(seps):
        assert not closed and len(pts) == 2
        xs = {round(p[0], 2) for p in pts}
        assert xs == {round(X0 + TABLE_PAD_X_MM + PLAN_ROW_PITCH_MM
                            + k * TABLE_ROW_PITCH_MM, 2)}
        assert {round(p[1], 2) for p in pts} == {0.0, GATE}


def test_polylines_rows_stack_along_x_plan_name_nearest_marker():
    """14 行沿 +x 堆叠：row0 方案名称 x 厚 ≈ 36mm（大字带）、其余 ≈ 12mm；
    行带中心单调递增，行间不串带。"""
    out = info_table_polylines(_table(_user_example_world()), table_x0=X0,
                               gate_mm=GATE)
    _frame, _seps, texts = _split(out)
    assert texts, '应有文本笔画'
    xs_all = [p[0] for _c, pts in texts for p in pts]
    for i in range(14):
        cx = _row_center_x(X0, i)
        band = [p for _c, pts in texts for p in pts
                if cx - TABLE_ROW_PITCH_MM / 2 <= p[0] < cx + TABLE_ROW_PITCH_MM / 2]
        assert band, f'第 {i} 行无笔画'
    # row0 大字：文本笔画 x 跨度 ≈ 36mm 字高级别
    cx0 = _row_center_x(X0, 0)
    row0 = [p for _c, pts in texts for p in pts
            if cx0 - PLAN_ROW_PITCH_MM / 2 <= p[0] < cx0 + PLAN_ROW_PITCH_MM / 2]
    assert max(p[0] for p in row0) - min(p[0] for p in row0) > 20.0
    # row1 普通行：x 厚 ≈ 12mm 字高（旋转 90°：字厚沿 x、行文沿 y）
    cx1 = _row_center_x(X0, 1)
    row1 = [p for _c, pts in texts for p in pts
            if cx1 - TABLE_ROW_PITCH_MM / 2 <= p[0] < cx1 + TABLE_ROW_PITCH_MM / 2]
    assert max(p[0] for p in row1) - min(p[0] for p in row1) <= TABLE_CHAR_H_MM + 2.0


def test_polylines_text_rotated_90_reading_plus_y():
    """文字旋转 90°：基线沿 +y（y 跨度远大于字厚）、起画 y ≈ TABLE_TEXT_Y0_MM、
    字顶朝 −x（行带内 glyph x 全部 ≤ 基线 origin = cx + h/2）。"""
    out = info_table_polylines(_table(), table_x0=X0, gate_mm=GATE)
    _frame, _seps, texts = _split(out)
    cx1 = _row_center_x(X0, 1)          # row1 = '床次 A料'
    row1 = [p for _c, pts in texts for p in pts
            if cx1 - TABLE_ROW_PITCH_MM / 2 <= p[0] < cx1 + TABLE_ROW_PITCH_MM / 2]
    ys = [p[1] for p in row1]
    xs = [p[0] for p in row1]
    assert min(ys) == pytest.approx(TABLE_TEXT_Y0_MM, abs=1.0)   # 起画贴 TABLE_TEXT_Y0
    assert max(ys) - min(ys) > 30.0     # '床次 A料' 6 字符 × 12mm ≈ 60mm 沿 y
    # 字顶朝 −x（基线 origin = cx + h/2 为界，括号等 descender 允许 ~2mm 下探）
    assert max(xs) <= cx1 + TABLE_CHAR_H_MM / 2 + 2.0


def test_polylines_tiny_gate_shrinks_text_length(caplog):
    """小门幅：行沿 x 堆叠不受门幅影响（14 行全在）；文字长度方向 shrink，
    全部点仍 y ≤ gate + warning。"""
    with caplog.at_level('WARNING'):
        out = info_table_polylines(_table(gate_mm=400.0), table_x0=X0,
                                   gate_mm=400.0)
    assert any('门幅' in r.message and '偏小' in r.message for r in caplog.records)
    ys = [p[1] for _c, pts in out for p in pts]
    assert max(ys) <= 400.0 + 0.01
    # 行带仍 14 行有笔画（沿 x 堆叠与门幅无关）
    _frame, _seps, texts = _split(out)
    for i in range(14):
        cx = _row_center_x(X0, i)
        assert any(cx - TABLE_ROW_PITCH_MM / 2 <= p[0] < cx + TABLE_ROW_PITCH_MM / 2
                   for _c, pts in texts for p in pts), f'第 {i} 行无笔画'


# --------------------------------------------- 集成 write_marker_plt

def test_write_marker_plt_table_paper_border_and_ascii():
    from materialsorting.web.export import write_marker_plt
    t = _table(_user_example_world(),
               table_in=parse_table_payload({'bed_no': '153'}) or {})
    raw = write_marker_plt(_user_example_world(), width_mm=500.0, gate_mm=1480.0,
                           title='M1787', info_table=t)
    out = raw.decode('ascii')                    # 中文 → 轮廓坐标，全 ASCII
    assert 'LB' not in out and 'VS' not in out
    # PS 纸长 = (引导 20 + 内容 500+20+387 + 尾 10) × 40 = 37480（覆盖表格区）
    assert out.split('\r\n')[0] == 'IN;PS37480;SP1;PW0.08;'
    # 表格外框右缘 x=(20+500+20+387)×40=37080 存在
    assert '37080,' in out
    # **边框不延伸**：边框 x1 = width_mm=500 → +引导 = 520×40=20800 竖边存在；
    # 且不存在旧口径的边框延伸角 44520/44200/47600
    assert '20800,' in out
    assert '44200,' not in out and '44520,' not in out and '47600,' not in out
    # 料长不含表格：0.500m（3 位小数）由 _cell_texts 单测锁定，这里锁纸长口径


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
    assert '37080,' in out                       # 外框右缘完整画出
