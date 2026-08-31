"""US-033 PLT/HPGL 导出生成器单测。

覆盖 spec AC#13 + 现场撞机修正（2026-08，对照生产 PLT data/PC-20250508NJIF*.plt）：
  - 闭合不变量（polygon PD 末点 = PU 首点，与 DXF POLYLINE 闭合策略一致）
  - 坐标 ×40 缩放（100mm → 4000 HPGL plotter unit）+ X 走纸引导 PLOT_LEAD_X_MM
    + Y 绘制平移 PLOT_LEAD_Y_MM=TABLE_W_MM=36（2026-08-31 用户定案：整张图纸一起
    离图纸原点 36mm=表格宽，首版 5mm 被反馈太短；纯绘制层位移，框内相对几何不变）
  - 首条 ``IN;`` 初始化指令（头部四连发合并一行，对齐生产 PLT）
  - **全程单笔 SP1**（2026-08-24 用户要求统一颜色：WT 预览按笔号着色，首版按层
    分 SP1-SP5 五笔预览呈多色，统一为门幅框蓝色；生产 PLT 实测同样全程仅 SP1）
  - 空层跳过（net/internal/notches/grain 空 → 该层无笔画）
  - PD 分块：每条 ≤10 点且整行 ≤110B（防设备行缓冲溢出坐标错位乱走）
  - 门幅边界（2026-08-28 版师定案：输入幅宽 = 实际幅宽）：内容按 y ≤ gate_mm
    裁剪削平（世界坐标层，裁剪后再 +Y 平移 → 绘制顶 = (gate+36)×40）；门幅框
    满幅 [0, gate]（2026-08-31 撤销旧 Y 双边内缩 5mm：贴边裁片穿框被切割软件
    读作越界布料，框=裁剪界=求解带三口径合一）；绘制层全体 Y + PLOT_LEAD_Y_MM
  - bytes 返回类型 + 全 ASCII + CRLF 行尾

生产 PLT 封装对齐（data/PC-20250508NJIF*.plt 口径）：
  - 头部 ``IN;PS<纸长>;SP1;PW0.08;``（PS = 引导 + max(用布长, 内容最大X) + 尾余量）
  - 尾部 ``PU;PG;`` 出纸收尾一行
  - 不输出 VS 速度 / LB 文字指令
  - 越界校验 ``_plt_frame_stats``（对齐 gate 的变换链路 bug 检测，正常 0）

测试用合成 5 层裁片（不依赖 intermediate / sparrow），断言 PLT 文本结构正确。
"""
from __future__ import annotations

import logging

import pytest

from materialsorting.web.export import (
    write_marker_plt, _plt_frame_stats, _PLT_PD_MAX_PTS)


def _full_piece(pid="P1", ptype="qian"):
    """5 层全有的合成裁片（用于全层坐标/层序 + 闭合不变量测试）。"""
    return {
        "pid": pid,
        "ptype": ptype,
        "size": 30,
        "color": "#ff0000",
        "polygon": [(0.0, 0.0), (100.0, 0.0), (100.0, 200.0), (0.0, 200.0)],
        "area_mm2": 20000.0,
        "net_polygon": [(10.0, 10.0), (90.0, 10.0), (90.0, 190.0), (10.0, 190.0)],
        "internal_lines": [[(20.0, 20.0), (80.0, 20.0)]],
        "notches": [(50.0, 0.0, 0.0, -1.0)],
        "grain_line": (50.0, 50.0, 50.0, 150.0),
    }


def _bare_piece(pid="P1", ptype="qian"):
    """仅毛版的裁片（4 个工艺层全空 → 用于空层跳过测试）。"""
    return {
        "pid": pid,
        "ptype": ptype,
        "polygon": [(0.0, 0.0), (10.0, 0.0), (10.0, 20.0), (0.0, 20.0)],
        "area_mm2": 200.0,
        "net_polygon": [],
        "internal_lines": [],
        "notches": [],
        "grain_line": None,
    }


def _plt(world_pieces, **kw) -> str:
    """write_marker_plt 输出 → 归一化 LF 文本（测试断言用，屏蔽 CRLF）。"""
    return write_marker_plt(world_pieces, **kw).decode("ascii").replace("\r\n", "\n")


def _body_section(lines: list[str]) -> list[str]:
    """头部一行之后的全部指令行（全程单笔 SP1，无按笔分段声明）。"""
    return lines[1:]


def _polylines(section: list[str]) -> list[list[str]]:
    """几何指令行 → 折线列表（每条 = 扁平坐标 token 流，PU 起点 + 后续 PD 续画）。

    PD 分块续画（HPGL 语义）后一条折线可能横跨多条 PD 行，这里拼回完整点列。
    """
    polys, cur = [], None
    for line in section:
        if line.startswith("PU") and "," in line:
            if cur:
                polys.append(cur)
            cur = line[2:].rstrip(";").split(",")
        elif line.startswith("PD"):
            cur.extend(line[2:].rstrip(";").split(","))
    if cur:
        polys.append(cur)
    return polys


# --------------------------------------------- 头部协议（IN/PS/SP1/PW）

def test_first_command_is_IN():
    """输出首条指令 IN;（HPGL Initialize）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="hi")
    assert out.startswith("IN;")


def test_header_one_line_declares_paper_size_pen_and_width():
    """头部对齐生产 PLT：IN;PS<纸长>;SP1;PW0.08; 四连发一行。

    PS 纸长 = (走纸引导 20 + max(用布长 500, 内容最大X 100) + 尾余量 10) × 40
    = 21200（生产文件头部即单行四连发）。
    """
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    assert out.split("\n")[0] == "IN;PS21200;SP1;PW0.08;"


def test_no_velocity_or_label_commands():
    """生产 PLT 无 VS 速度 / LB 文字指令 → 不输出（兼容性交给设备端）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="M1787 x")
    assert "VS" not in out
    assert "LB" not in out


# --------------------------------------------- bytes + 全 ASCII + CRLF


def test_returns_bytes_and_ascii_decodable():
    """返回 bytes 类型且 .decode("ascii") 不抛异常。"""
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="ascii_only")
    assert isinstance(out, bytes)
    out.decode("ascii")  # no UnicodeDecodeError


def test_crlf_line_endings():
    """行尾全 CRLF（生产文件口径；部分 WT 解析器对纯 LF 不 tolerant）。"""
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="").decode("ascii")
    assert "\r\n" in out
    assert out.count("\r\n") == out.count("\n")   # 无裸 LF
    assert out.count("\r") == out.count("\n")     # 无裸 CR


# --------------------------------------------- 尾部 PG 出纸


def test_ends_with_pen_up_and_page_feed():
    """尾部 PU;PG; 一行（抬笔 + 出纸结束页，生产 PLT 收尾指令同行）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="t")
    assert out.rstrip("\n").endswith("PU;PG;")


# --------------------------------------------- 坐标 ×40 缩放 + X 走纸引导


def test_coordinate_scaled_by_40_with_lead_shift():
    """世界坐标(mm) ×40 round：X 另加走纸引导 PLOT_LEAD_X_MM=20mm（生产内容 24mm 起画），
    Y 另加绘制平移 PLOT_LEAD_Y_MM=36mm=表格宽（2026-08-31 用户定案）。

    polygon 顶点 (100,0)→(4800,1440); (100,200)→(4800,9440)；门幅框 500 宽 → 800..20800。
    """
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    assert "4800,1440" in out
    assert "4800,9440" in out
    assert "800,9440" in out
    # 门幅框：x 0..500 → 800..20800，y 满幅 0..1000 → +36mm 平移后 1440..41440
    assert "20800,1440" in out
    assert "20800,41440" in out


def test_x_lead_shift_no_content_at_paper_origin():
    """X 引导 + Y 平移后不再有任何 PU 贴纸原点 0 起画（走纸/幅宽向定位余量）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    lines = out.split("\n")
    assert "PU800,1440;" in lines        # outline 起点 (0,0) → +20mm/+36mm
    assert not any(l.startswith("PU0,") for l in lines)


def test_coordinate_rounded_to_integer():
    """坐标 round 取整：浮点 mm × 40 后必为整数（无小数点 / 负号）。"""
    piece = {
        "pid": "P",
        "ptype": "A",
        "polygon": [(0.1, 0.2), (10.3, 0.4), (10.5, 20.6), (0.7, 20.8)],
        "net_polygon": [],
        "internal_lines": [],
        "notches": [],
        "grain_line": None,
    }
    out = _plt([piece], width_mm=100, gate_mm=100, title="")
    for line in out.split("\n"):
        if line.startswith("PD"):
            coords = line[2:].rstrip(";")
            for tok in coords.split(","):
                assert tok.isdigit(), f"non-integer coord {tok!r} in PD line {line!r}"


# --------------------------------------------- PD 分块（防行缓冲溢出）


def test_pd_chunks_within_limits():
    """PD 分块：每条 ≤10 点（`_PLT_PD_MAX_PTS`）且整行 ≤110B（生产 ≤11 点/118B 内的紧值）。"""
    n = 40
    poly = [(float(i * 5), float(i % 7) * 10) for i in range(n)]   # 长折线不闭合
    piece = {"pid": "P", "ptype": "A", "polygon": poly, "net_polygon": [],
             "internal_lines": [], "notches": [], "grain_line": None}
    out = _plt([piece], width_mm=500, gate_mm=1000, title="")
    pd_lines = [l for l in out.split("\n") if l.startswith("PD")]
    assert len(pd_lines) >= 4, "40 点折线必须分块（单条塞不下）"
    for line in pd_lines:
        assert len(line) <= 110, f"PD 行超长 {len(line)}B: {line!r}"
        assert (line[2:-1].count(",") + 1) // 2 <= _PLT_PD_MAX_PTS
    # 分块续画不丢点：闭合 polygon → PU 首点之外的 n-1 点 + 闭合回起点 1 点 = n，
    # 另加门幅框 4 点（点数 = 坐标数 // 2）
    total_pts = sum((l[2:-1].count(",") + 1) // 2 for l in pd_lines)
    assert total_pts == n + 4


# --------------------------------------------- 闭合不变量（含分块续画）


def test_polygon_closed_first_point_equals_last():
    """闭合不变量：层序前两条折线（门幅框 + outline）末点 == 首点。

    PUx0,y0;PD...;（可分块）—— 分块续画拼回后 PD 末点必须回到 PU 首点。
    """
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    polys = _polylines(_body_section(out.split("\n")))
    assert len(polys) >= 2
    for tokens in polys[:2]:    # 门幅框 + 毛版 outline（层序在前）
        assert tokens[:2] == tokens[-2:], (
            f"closure broken: first={tokens[:2]} last={tokens[-2:]}")


def test_border_full_band_no_inset():
    """门幅框（层序首条折线）世界坐标满幅 [0, gate]：2026-08-31 撤销 Y 双边内缩 5mm
    —— 贴边裁片精确贴求解约束带 0/gate，框=裁剪界=求解带三口径合一。绘制层全体
    +PLOT_LEAD_Y_MM=36mm 平移后画在 [36, gate+36]（gate=1980 → 顶 2016mm）——纯
    位移，跨度恰 = gate 证明满幅未内缩。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1980, title="")
    border = _polylines(_body_section(out.split("\n")))[0]
    xs = [int(border[i]) for i in range(0, len(border), 2)]
    ys = [int(border[i + 1]) for i in range(0, len(border), 2)]
    assert min(ys) == int(36 * 40)              # 下沿离图纸原点 36mm=表格宽（绘制平移）
    assert max(ys) == int((36 + 1980) * 40)     # 上沿 = 平移 + 输入幅宽 1980
    assert max(ys) - min(ys) == 1980 * 40       # 跨度恰满幅（无内缩）
    assert min(xs) == int(20 * 40)              # X 走纸引导
    assert max(xs) == int((20 + 500) * 40)


def test_border_four_corners_present():
    """门幅框四角（X 引导后 800..20800 × Y 平移后 1440..41440）全在首条折线中。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    border = ",".join(_polylines(_body_section(out.split("\n")))[0])
    for corner in ("800,1440", "20800,1440", "20800,41440", "800,41440"):
        assert corner in border, f"corner {corner} missing from border {border!r}"


# --------------------------------------------- 单笔输出（统一颜色）


def test_single_pen_sp1_only_even_with_all_layers():
    """全文件单笔：5 层全有也只有头部一次 SP1（WT 预览单色 = 门幅框蓝色；
    生产 PLT 实测全程仅 SP1）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="hi")
    assert out.count("SP1;") == 1
    for pen in (2, 3, 4, 5, 6):
        assert f"SP{pen};" not in out


def test_empty_layers_no_extra_strokes():
    """空层跳过：net/internal/notches/grain 全空 → 体里只有门幅框 + outline 2 条折线。"""
    out = _plt([_bare_piece()], width_mm=100, gate_mm=100, title="")
    assert out.count("SP1;") == 1
    lines = out.split("\n")
    assert sum(1 for l in lines if l.startswith("PU") and "," in l) == 2
    assert sum(1 for l in lines if l.startswith("PD")) == 2


def test_partial_layers_present_in_single_pen_body():
    """部分层：仅 net + grain → 两层笔画都在单笔体里（坐标含 +20mm 引导）。"""
    piece = {
        "pid": "P",
        "ptype": "A",
        "polygon": [(0.0, 0.0), (10.0, 0.0), (10.0, 20.0), (0.0, 20.0)],
        "net_polygon": [(1.0, 1.0), (9.0, 1.0), (9.0, 19.0), (1.0, 19.0)],
        "internal_lines": [],
        "notches": [],
        "grain_line": (5.0, 5.0, 5.0, 15.0),
    }
    out = _plt([piece], width_mm=100, gate_mm=100, title="")
    body = "\n".join(_body_section(out.split("\n")))
    assert "840,1480" in body      # net 起点 (1,1) → +20/+36mm → (840,1480)
    assert "1000,1640" in body     # grain A 端 (5,5) → (1000,1640)
    assert "1000,2040" in body     # grain B 端 (5,15)
    assert out.count("SP1;") == 1


def test_multi_piece_single_pen_flat_stream():
    """多片单笔平铺：3 片 outline 连续输出，全文只头部一次 SP1。"""
    pieces = [
        _bare_piece(pid="P1", ptype="A"),
        _bare_piece(pid="P2", ptype="B"),
        _bare_piece(pid="P3", ptype="C"),
    ]
    out = _plt(pieces, width_mm=1000, gate_mm=1000, title="")
    lines = out.split("\n")
    assert out.count("SP1;") == 1
    # PU/PD 折线各 4 条：门幅框 + 3 片 outline（每片 4 点单块装得下）
    assert sum(1 for l in lines if l.startswith("PU") and "," in l) == 4
    assert sum(1 for l in lines if l.startswith("PD")) == 4


# --------------------------------------------- 5 层坐标/层序校验（端到端）


def test_all_layers_present_in_dxf_layer_order():
    """5 层坐标全在单笔体里，层序与 write_marker_dxf 一致：
    门幅框+outline → net → internal → notch → grain（坐标含 +20mm 走纸引导
    + 36mm Y 绘制平移）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    body = "\n".join(_body_section(out.split("\n")))

    # 门幅框角 20800,41440 + outline 角 (100,200)→(4800,9440)
    assert "4800,9440" in body and "20800,41440" in body
    # net 起点 (10,10) → +36mm → (1200,1840)
    assert "1200,1840" in body
    # internal 起点 (20,20) → (1600,2240)
    assert "1600,2240" in body
    # notch：(50,±4) → X 2800；y=4 → 1600、y=-4 → 1280（+36mm 后不再触 clamp）
    assert "2800,1600" in body and "2800,1280" in body
    # grain：(50,50)→(50,150) → (2800,3440)→(2800,7440)
    assert "2800,3440" in body and "2800,7440" in body
    # 层序：outline < net < internal < grain（notch 在 internal 与 grain 之间）
    assert (body.index("4800,9440") < body.index("1200,1840")
            < body.index("1600,2240") < body.index("2800,1600")
            < body.index("2800,3440"))


# --------------------------------------------- 门幅裁剪（防御）


def test_content_above_gate_clipped():
    """越出输入门幅的几何被削平/丢弃：裁剪在世界坐标层 y ≤ 1980mm，绘制再 +36mm
    平移 → 全文件 Y ≤ 80640u（2016mm）。"""
    piece = {
        "pid": "TOP", "ptype": "A",
        "polygon": [(0.0, 1950.0), (100.0, 1950.0), (100.0, 2100.0), (0.0, 2100.0)],
        "net_polygon": [],
        "internal_lines": [],
        "notches": [(50.0, 2090.0, 0.0, 1.0)],          # 两端点 2086/2094 全越界
        "grain_line": (50.0, 1950.0, 50.0, 2050.0),      # 跨界：画到 1980 截断
    }
    out = _plt([piece], width_mm=200, gate_mm=1980, title="")
    ymax = 0
    for line in out.split("\n"):
        if line.startswith(("PU", "PD")) and "," in line:
            ys = [int(t) for t in line[2:].rstrip(";").split(",")][1::2]
            ymax = max(ymax, max(ys))
    assert ymax <= int((36 + 1980) * 40)   # 80640：裁剪界 1980 + 平移 36mm
    # 部分越界 polygon 削平到门幅线（交点 y=1980mm + 平移），不是整片丢弃
    assert "80640" in out
    # 刺口全越界 → 整段丢弃无笔画；布纹线跨界截断到 y=1980（(50,1950)→(50,1980)）
    assert "2800,79440" in out and "2800,80640" in out


def test_clip_warning_logged(caplog):
    """越输入门幅裁剪时记 warning（求解布局应落在门幅内，越出 = 链路 bug 线索）。"""
    piece = {
        "pid": "TOP", "ptype": "A",
        "polygon": [(0.0, 1950.0), (100.0, 1950.0), (100.0, 2100.0), (0.0, 2100.0)],
        "net_polygon": [], "internal_lines": [], "notches": [], "grain_line": None,
    }
    with caplog.at_level(logging.WARNING):
        write_marker_plt([piece], width_mm=200, gate_mm=1980, title="")
    assert "越出输入门幅" in caplog.text


# --------------------------------------------- 越界校验（防御）


def test_frame_stats_zero_for_in_frame_piece():
    """片全在门幅框内（含 notch 端点）→ 越界点数 0，最大X=轮廓最右。"""
    piece = dict(_full_piece(), notches=[(50.0, 100.0, 1.0, 0.0)])   # 内位刺口
    n_out, max_x = _plt_frame_stats([piece], width_mm=500, gate_mm=1000)
    assert n_out == 0
    assert max_x == 100.0


def test_frame_stats_counts_all_layers():
    """越界点计入全部 5 层（notch 按**点**计；端点外伸属工艺正常，见 PS 用例）。

    曾因 notch 未随片旋转产生 600 越界点把 WT 预览拉变形。
    """
    piece = {
        "pid": "P",
        "ptype": "A",
        "polygon": [(0.0, 0.0), (10.0, 0.0), (10.0, 20.0), (0.0, 20.0)],
        "net_polygon": [(999.0, 5.0), (999.0, 15.0)],       # 越界 2
        "internal_lines": [[(0.0, 1999.0), (5.0, 1999.0)]],  # 越界 2（1999>1000）
        "notches": [(600.0, 10.0, 1.0, 0.0)],               # 越界 1（点 600>500.5）
        "grain_line": (-100.0, 5.0, -100.0, 15.0),          # 越界 2
    }
    n_out, max_x = _plt_frame_stats([piece], width_mm=500, gate_mm=1000)
    assert n_out == 7
    assert max_x == 999.0   # 内容最大 X（net 轮廓最右）


def test_paper_size_covers_notch_extension_beyond_outline():
    """边缘片 notch 端点超出轮廓 bbox 几 mm → PS 纸长覆盖内容最大 X + 引导 + 尾余量。"""
    piece = {
        "pid": "P",
        "ptype": "A",
        "polygon": [(0.0, 0.0), (490.0, 0.0), (490.0, 20.0), (0.0, 20.0)],
        "net_polygon": [],
        "internal_lines": [],
        "notches": [(490.0, 10.0, 1.0, 0.0)],   # 端点 494mm > 轮廓 490mm
        "grain_line": None,
    }
    out = _plt([piece], width_mm=490, gate_mm=100, title="")
    # PS = (引导 20 + max(490, 494) + 尾余量 10) × 40 = 20960（若漏掉 notch 端点
    # 或余量会取小值，内容被 WT 按纸长截断）
    assert "PS20960;" in out


# --------------------------------------------- 边界


def test_IN_before_PS_before_PW_before_SP1():
    """指令顺序：IN; → PS; → SP1; → PW;（头部一行内自左向右，对齐生产头部协议）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    assert out.index("IN;") < out.index("PS21200;") < out.index("SP1;") < out.index("PW0.08;")


def test_empty_world_pieces_still_emits_header_and_border():
    """空 world_pieces（无裁片）→ 仍输出头部一行 + SP1 门幅框（防御性边界）。"""
    out = _plt([], width_mm=300, gate_mm=600, title="")
    assert out.startswith("IN;")
    assert "PS13200;" in out       # (20 + 300 + 10) × 40
    assert "PW0.08;" in out
    assert "SP1;" in out
    for pen in range(2, 6):
        assert f"SP{pen};" not in out


# --------------------------------------------- 布纹箭头线 + 尺码×数量标注
# （2026-08-24，对照生产 PLT data/PC-20250508NJIF*.plt 逆向实测，见 export_plt
#   模块注释：画向 u=A→B 随片旋转；B 端单头双羽 30mm/15°；标注「尺码*数量」
#   沿 u 阅读、字顶朝 w=(-uy,ux)（右手系防镜像）、基线离杆 10mm、中心锚 0.85·L；
#   正向片标注在杆视觉上方、180° 片翻到杆视觉下方且随片倒置）


def _piece_with_grain(pid="P1", size=30, grain=(100.0, 50.0, 400.0, 50.0)):
    """横杆布纹线合成裁片（默认 L→R 画向，size=30 → 标注 "30*1"）。"""
    return {
        "pid": pid, "ptype": "A", "size": size,
        "polygon": [(0.0, 0.0), (500.0, 0.0), (500.0, 100.0), (0.0, 100.0)],
        "area_mm2": 50000.0,
        "net_polygon": [], "internal_lines": [], "notches": [],
        "grain_line": grain,
    }


def _all_pts(out: str) -> list[tuple[int, int]]:
    """全文件（单笔）全部顶点（PU 坐标对，含 PD 分块续画拼接）。"""
    return [(int(p[i]), int(p[i + 1]))
            for p in _polylines(_body_section(out.split("\n")))
            for i in range(0, len(p), 2)]


def _grain_strokes(out: str, n_pieces: int) -> list[list[str]]:
    """布纹层折线（层序最后一块）：跳过门幅框 + 每片 1 条 outline 的前导折线。"""
    return _polylines(_body_section(out.split("\n")))[1 + n_pieces:]


def _grain_pts(out: str) -> list[tuple[int, int]]:
    """布纹层顶点（单笔后按层序切片：门幅框+outline 之后即布纹笔画）。"""
    return [(int(p[i]), int(p[i + 1]))
            for p in _grain_strokes(out, 1)
            for i in range(0, len(p), 2)]


def test_grain_arrow_single_head_at_destination_end():
    """箭头线 = 光杆 + **B 端（画向前端）单头对称双羽**——箭头指向原始布纹画向，
    A 端（尾端）无羽（2026-08-24 用户明确要求单头，非生产 PLT 双端形态）。

    _full_piece 竖杆 A(50,50)→B(50,150)：u=(0,1)、w=(-1,0)（双羽 ±w 对称，
    坐标与 w 手性无关）。
    双羽 tip = B − 30·cos15°·u ± 30·sin15°·w = (57.764, 121.022)/(42.236, 121.022)
    → +20/+36mm 平移后 (3111,6281)/(2489,6281)；A 端箭羽坐标（3111,4599）必须不存在。
    """
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    sp5 = ",".join(f"{x},{y}" for x, y in _all_pts(out))
    assert "3111,6281" in sp5
    assert "2489,6281" in sp5
    assert "3111,4599" not in sp5      # 尾端 A 无羽
    assert "2800,3440" in sp5 and "2800,7440" in sp5


def test_label_side_and_orientation_follow_grain_direction():
    """标注侧别/正反随画向（w=(-uy,ux) 右手系）：L→R 杆标注在 file +y
    （基线 60mm/字顶 70mm → +36mm 平移后 y_u 3840..4240，视觉在杆上方、正展示）；
    R→L 杆翻到 file −y（2640..3040，随片倒置、视觉在杆下方）—— 生产同款。"""
    l2r = _plt([_piece_with_grain(grain=(100.0, 50.0, 400.0, 50.0))],
               width_mm=500, gate_mm=1000, title="")
    r2l = _plt([_piece_with_grain(grain=(400.0, 50.0, 100.0, 50.0))],
               width_mm=500, gate_mm=1000, title="")

    ys_l2r = [y for _x, y in _grain_pts(l2r)]
    ys_r2l = [y for _x, y in _grain_pts(r2l)]
    # L→R：杆 y=3440、B 端头部双羽尖 3129/3751（±w 对称）、标注 3840..4240
    assert min(ys_l2r) == 3129 and max(ys_l2r) == 4240
    # R→L：杆 y=3440、B 端（file 左端）头部双羽尖 3129/3751、标注 2640..3040
    assert max(ys_r2l) == 3751 and min(ys_r2l) == 2640

    # 锚位 0.85·L（画向前端）：L→R 标注中心 x=355 → 标注笔画 x_u ∈ [14000,16000]
    label_xs = [x for x, y in _grain_pts(l2r) if 3840 <= y <= 4240]
    assert len(label_xs) > 10, "标注笔画应存在"
    assert 14000 <= min(label_xs) and max(label_xs) <= 16000


def test_label_glyph_chirality_follows_grain_direction():
    """字形手性（防镜像回归，2026-08-24 用户截图纠正）：'7' 的长横杠在**字顶带**
    —— L→R 片 y=4240（file +y 视觉上方、正展示；含 +36mm 平移）；R→L 片 y=2640
    （字顶朝 file −y，整字随片倒置）。首版 w=(uy,-ux) 左手系时横杠落到基线对侧
    （L→R 在 2640 / R→L 在 4240），所有文字无论画向全部镜像。"""
    l2r = _plt([_piece_with_grain(size=7)],                     # 标注 "7*1"
               width_mm=500, gate_mm=1000, title="")
    r2l = _plt([_piece_with_grain(size=7, grain=(400.0, 50.0, 100.0, 50.0))],
               width_mm=500, gate_mm=1000, title="")
    sp5_l2r = ",".join(f"{x},{y}" for x, y in _grain_pts(l2r))
    sp5_r2l = ",".join(f"{x},{y}" for x, y in _grain_pts(r2l))
    # L→R：'7' 字顶横杠两端 (339.7,70)/(346.54,70)mm → (14388,4240)/(14662,4240)
    assert "14388,4240" in sp5_l2r and "14662,4240" in sp5_l2r
    assert "14388,2640" not in sp5_l2r     # 镜像（左手系）时横杠在基线对侧
    # R→L：横杠随片倒置翻到 y=2640；(160.3,30)/(153.46,30)mm → (7212,2640)/(6938,2640)
    assert "7212,2640" in sp5_r2l and "6938,2640" in sp5_r2l
    assert "7212,4240" not in sp5_r2l      # 镜像时横杠在杆上侧


def test_label_size_and_multiplicity():
    """标注内容 = 尺码*数量（数量 = 同 pid 副本数，demand>1 时 sparrow 发 N 条
    placed_items → world_pieces N 行同 pid）。

    笔画数固定可数：杆+双羽 3 笔；'3'2+'0'1+'*'3+'1'2=8 → "30*1" 共 11 笔；
    "30*2"（'2' 单笔）每片 10 笔，2 副本共 20 笔。
    """
    one = _plt([_piece_with_grain()], width_mm=500, gate_mm=1000, title="")
    two = _plt([_piece_with_grain(), _piece_with_grain()],
               width_mm=1000, gate_mm=1000, title="")
    assert len(_grain_strokes(one, 1)) == 11
    assert len(_grain_strokes(two, 2)) == 20


def test_label_skipped_for_missing_or_unsupported_size():
    """size=None / 字库外字符（"3X"、30.5 带 '.'）→ 整段不标注（all-or-nothing：
    "30.5" 缺 '.' 会读成 "305"，宁缺勿错），布纹层仅剩箭头线 3 笔。"""
    for size in (None, "3X", 30.5):
        piece = _piece_with_grain(size=size)
        out = _plt([piece], width_mm=500, gate_mm=1000, title="")
        assert len(_grain_strokes(out, 1)) == 3, f"size={size!r} 应跳过标注"


def test_short_shaft_centers_label_and_scales_barbs():
    """杆短于文本宽 → 标注锚点退回杆中点（防尾端大量溢出）；箭羽按杆长 45% 收缩。"""
    piece = _piece_with_grain(grain=(100.0, 50.0, 130.0, 50.0))   # 杆长 30mm < W 43.8
    out = _plt([piece], width_mm=500, gate_mm=1000, title="")
    pts = _grain_pts(out)
    label_xs = [x for x, y in pts if 3840 <= y <= 4240]
    assert 4500 <= min(label_xs) and max(label_xs) <= 6300   # 中心 x=115 → [93,137]mm
    # 头部双羽收缩到 30·0.45=13.5mm：tips = (130−13.5·cos15°, 50±13.5·sin15°)
    # = (116.96, 53.49)/(116.96, 46.51) → +36mm 平移 (5478,3580)/(5478,3300)
    sp5 = ",".join(f"{x},{y}" for x, y in pts)
    assert "5478,3580" in sp5 and "5478,3300" in sp5


def test_degenerate_zero_length_grain_emits_nothing():
    """零长布纹线（两端点重合）→ 布纹层无笔画（防御边界：体里仅门幅框+outline）。"""
    piece = _piece_with_grain(grain=(50.0, 50.0, 50.0, 50.0))
    out = _plt([piece], width_mm=500, gate_mm=1000, title="")
    assert len(_polylines(_body_section(out.split("\n")))) == 2


def test_label_clipped_at_gate():
    """顶部片标注越出输入门幅 1980 → 削平不越程（工艺线口径：裁剪不告警、布纹笔画
    仍在；裁剪在世界坐标层，绘制含 +36mm 平移 → 上界 (1980+36)×40）。"""
    piece = _piece_with_grain(grain=(50.0, 1960.0, 350.0, 1960.0))   # L→R → 标注在杆上侧越界
    out = _plt([piece], width_mm=400, gate_mm=1980, title="")
    ymax = 0
    for line in out.split("\n"):
        if line.startswith(("PU", "PD")) and "," in line:
            ys = [int(t) for t in line[2:].rstrip(";").split(",")][1::2]
            ymax = max(ymax, max(ys))
    assert ymax <= int((36 + 1980) * 40)
    assert len(_grain_strokes(out, 1)) > 0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
