"""US-033 PLT/HPGL 导出生成器单测。

覆盖 spec AC#13 + 现场撞机修正（2026-08，对照生产 PLT data/PC-20250508NJIF*.plt）：
  - 闭合不变量（polygon PD 末点 = PU 首点，与 DXF POLYLINE 闭合策略一致）
  - 坐标 ×40 缩放（100mm → 4000 HPGL plotter unit）+ X 走纸引导 PLOT_LEAD_X_MM
  - 首条 ``IN;`` 初始化指令（头部四连发合并一行，对齐生产 PLT）
  - 5 个笔号（SP1-SP5）按**笔分组**输出：每笔只声明一次（门幅框并入 SP1）
  - 空层跳过（net/internal/notches/grain 空 → 对应 SP 不出现）
  - PD 分块：每条 ≤10 点且整行 ≤110B（防设备行缓冲溢出坐标错位乱走）
  - 安全幅面：内容按 y ≤ PLOT_SAFE_MAX_Y_MM(1910) 裁剪削平，全文件 Y 不超程；
    门幅框上沿压进可写幅宽、下沿内缩
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
    write_marker_plt, _plt_frame_stats, PLOT_SAFE_MAX_Y_MM, _PLT_PD_MAX_PTS)


def _full_piece(pid="P1", ptype="qian"):
    """5 层全有的合成裁片（用于 SP1-SP5 全笔号 + 闭合不变量测试）。"""
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


def _sp_section(lines, pen: int) -> list[str]:
    """截取 ``SPn;`` 声明行之后到下一 SP 行之前的几何指令行（按笔分组的段）。"""
    section: list[str] = []
    in_sec = False
    for line in lines:
        if line.startswith("SP"):
            if in_sec:
                break
            in_sec = (line == f"SP{pen};")
            continue
        if in_sec:
            section.append(line)
    return section


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
    """世界坐标(mm) ×40 round：X 另加走纸引导 PLOT_LEAD_X_MM=20mm（生产内容 24mm 起画）。

    polygon 顶点 (100,0)→(4800,0); (100,200)→(4800,8000)；门幅框 500 宽 → 800..20800。
    """
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    assert "4800,0" in out
    assert "4800,8000" in out
    assert "800,8000" in out
    # 门幅框：x 0..500 → 800..20800，y 5..995 → 200..39800
    assert "20800,200" in out
    assert "20800,39800" in out


def test_x_lead_shift_no_content_at_paper_origin():
    """X 引导后不再有任何 PU 贴纸原点 0 起画（走纸定位余量）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    lines = out.split("\n")
    assert "PU800,0;" in lines           # outline 起点 (0,0) → +20mm
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
    """闭合不变量：SP1 段（门幅框 + outline）每条折线末点 == 首点。

    PUx0,y0;PD...;（可分块）—— 分块续画拼回后 PD 末点必须回到 PU 首点。
    """
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    polys = _polylines(_sp_section(out.split("\n"), 1))
    assert len(polys) == 2   # 门幅框 + 毛版 outline
    for tokens in polys:
        assert tokens[:2] == tokens[-2:], (
            f"closure broken: first={tokens[:2]} last={tokens[-2:]}")


def test_border_inset_and_within_safe_area():
    """门幅框并入 SP1：Y 下沿内缩 5mm、上沿压进可写幅宽（gate=1980 → 顶 1905mm）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1980, title="")
    border = _polylines(_sp_section(out.split("\n"), 1))[0]
    xs = [int(border[i]) for i in range(0, len(border), 2)]
    ys = [int(border[i + 1]) for i in range(0, len(border), 2)]
    assert min(ys) == 5 * 40            # 下沿内缩 PLOT_BORDER_MARGIN_Y_MM
    assert max(ys) == 1905 * 40         # min(1980, 1910-5) = 1905，不贴 y=1980
    assert min(xs) == int(20 * 40)      # X 走纸引导
    assert max(xs) == int((20 + 500) * 40)


def test_border_four_corners_present():
    """门幅框四角（引导后 800..20800 × 内缩 200..39800）全在 SP1 首条折线中。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    border = ",".join(_polylines(_sp_section(out.split("\n"), 1))[0])
    for corner in ("800,200", "20800,200", "20800,39800", "800,39800"):
        assert corner in border, f"corner {corner} missing from border {border!r}"


# --------------------------------------------- 5 个笔号按笔分组


def test_all_five_pens_present_with_full_data():
    """5 层全有的裁片 → SP1..SP5 各出现（门幅框并入 SP1，不再有 SP6）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="hi")
    for pen in range(1, 6):
        assert f"SP{pen};" in out, f"SP{pen}; missing"
    assert "SP6;" not in out


def test_empty_layers_skipped():
    """空层跳过：net/internal/notches/grain 全空 → SP2/3/4/5 不出现（仅 SP1）。"""
    out = _plt([_bare_piece()], width_mm=100, gate_mm=100, title="")
    assert "SP1;" in out
    for pen in range(2, 6):
        assert f"SP{pen};" not in out


def test_partial_layers_only_emits_present_pens():
    """部分层：仅 net + grain → SP1/2/5 出现，SP3/4 不出现。"""
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
    assert "SP2;" in out
    assert "SP5;" in out
    assert "SP3;" not in out
    assert "SP4;" not in out


def test_multi_piece_pen_grouping():
    """按笔分组：3 片 outline 合并进一次 SP1 声明（不再逐片切笔）。"""
    pieces = [
        _bare_piece(pid="P1", ptype="A"),
        _bare_piece(pid="P2", ptype="B"),
        _bare_piece(pid="P3", ptype="C"),
    ]
    out = _plt(pieces, width_mm=1000, gate_mm=1000, title="")
    lines = out.split("\n")
    # SP1; 出现 2 次：头部一行里的笔声明 + 分组绘图段声明 1 次
    assert out.count("SP1;") == 2
    # PU/PD 折线各 4 条：门幅框 + 3 片 outline（每片 4 点单块装得下）
    assert sum(1 for l in lines if l.startswith("PU") and "," in l) == 4
    assert sum(1 for l in lines if l.startswith("PD")) == 4


# --------------------------------------------- 5 层笔号语义校验（端到端）


def test_each_layer_uses_correct_pen_number():
    """5 层各用对应笔号：SP1 门幅框+outline / SP2 net / SP3 internal / SP4 notch / SP5 grain。

    坐标含 +20mm 走纸引导（X 全体 +800u），按笔分组后各层在自己的 SP 段内。
    """
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    lines = out.split("\n")

    def section_joined(pen):
        return ",".join(",".join(p) for p in _polylines(_sp_section(lines, pen)))

    # SP1：门幅框角 20800,39800 + outline 角 (100,200)→(4800,8000)
    sp1 = section_joined(1)
    assert "4800,8000" in sp1 and "20800,39800" in sp1

    # SP2 net：起点 (10,10) → (1200,400)
    assert "1200,400" in section_joined(2)

    # SP3 internal：起点 (20,20) → (1600,800)
    assert "1600,800" in section_joined(3)

    # SP4 notch：(50,±4) → X 2800；y=-4 clamp 到 0
    sp4 = section_joined(4)
    assert "2800,160" in sp4 and "2800,0" in sp4

    # SP5 grain：(50,50)→(50,150) → (2800,2000)→(2800,6000)
    sp5 = section_joined(5)
    assert "2800,2000" in sp5 and "2800,6000" in sp5


# --------------------------------------------- 安全幅面常量（单一事实源）


def test_plot_safe_max_y_single_source():
    """PLOT_SAFE_MAX_Y_MM 单一事实源：export 与 nesting_bounds 同一对象。

    求解约束带（web/solver strip_height）与 PLT 裁剪都用它 —— 换机器/布幅只改
    nesting_bounds 一处，NEST_GATE_MM=min(GATE_MM, PLOT_SAFE_MAX_Y_MM) 自动跟随。
    """
    from materialsorting.nesting_bounds import load_pieces as _lp
    assert PLOT_SAFE_MAX_Y_MM is _lp.PLOT_SAFE_MAX_Y_MM
    assert _lp.NEST_GATE_MM == min(_lp.GATE_MM, _lp.PLOT_SAFE_MAX_Y_MM)


# --------------------------------------------- 安全幅面裁剪（防撞机）


def test_content_above_plot_safe_max_clipped():
    """越过可写幅宽 1910mm 的几何被削平/丢弃：全文件 Y ≤ 76400u（1910mm）。"""
    piece = {
        "pid": "TOP", "ptype": "A",
        "polygon": [(0.0, 1850.0), (100.0, 1850.0), (100.0, 1975.0), (0.0, 1975.0)],
        "net_polygon": [],
        "internal_lines": [],
        "notches": [(50.0, 1970.0, 0.0, 1.0)],          # 两端点 1966/1974 全越界
        "grain_line": (50.0, 1900.0, 50.0, 1960.0),      # 跨界：画到 1910 截断
    }
    out = _plt([piece], width_mm=200, gate_mm=1980, title="")
    ymax = 0
    for line in out.split("\n"):
        if line.startswith(("PU", "PD")) and "," in line:
            ys = [int(t) for t in line[2:].rstrip(";").split(",")][1::2]
            ymax = max(ymax, max(ys))
    assert ymax <= int(PLOT_SAFE_MAX_Y_MM * 40)   # 76400：绝不超可写幅宽
    # 部分越界 polygon 削平到安全线（交点 y=1910mm），不是整片丢弃
    assert "76400" in out
    # 刺口全越界 → SP4 整层无绘制内容，不声明
    assert "SP4;" not in out


def test_clip_warning_logged(caplog):
    """越可写幅宽裁剪时记 warning（提示缩小求解门幅重排，marker 不完整）。"""
    piece = {
        "pid": "TOP", "ptype": "A",
        "polygon": [(0.0, 1850.0), (100.0, 1850.0), (100.0, 1975.0), (0.0, 1975.0)],
        "net_polygon": [], "internal_lines": [], "notches": [], "grain_line": None,
    }
    with caplog.at_level(logging.WARNING):
        write_marker_plt([piece], width_mm=200, gate_mm=1980, title="")
    assert "可写幅宽" in caplog.text


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


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
