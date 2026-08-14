"""US-033 PLT/HPGL 导出生成器单测。

覆盖 spec AC#13：
  - 闭合不变量（polygon PD 末点 = PU 首点，与 DXF POLYLINE 闭合策略一致）
  - 坐标 ×40 缩放（100mm → 4000 HPGL plotter unit）
  - 首条 ``IN;`` 初始化指令
  - 6 个笔号（SP1-SP6）各有数据时至少出现一次
  - 空层跳过（net/internal/notches/grain 空 → 对应 SP 不出现）
  - 多片计数（N 个 polygon → SP1 PU+PD 组出现 N 次）
  - bytes 返回类型 + 全 ASCII
  - 门幅框四角 + 闭合

生产 PLT 封装对齐（data/PC-20250508NJIF*.plt 口径）：
  - 头部 ``IN;PS<纸长>;SP1;PW0.08;``（PS 声明整幅纸长，无 PS 时 WT 按默认页幅裁切）
  - 尾部 ``PU;PG;`` 出纸收尾
  - 行尾 CRLF
  - 不输出 VS 速度 / LB 文字指令
  - 越界校验 ``_plt_frame_stats``（正常 0，notch 变换缺陷时 >0）+ PS 取内容最大 X

测试用合成 5 层裁片（不依赖 intermediate / sparrow），断言 PLT 文本结构正确。
"""
from __future__ import annotations

import pytest

from materialsorting.web.export import write_marker_plt, _plt_frame_stats


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


# --------------------------------------------- 头部协议（IN/PS/SP1/PW）


def test_first_command_is_IN():
    """输出首条指令 IN;（HPGL Initialize）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="hi")
    assert out.startswith("IN;")


def test_header_declares_paper_size_pen_and_width():
    """头部对齐生产 PLT：IN;PS<纸长>;SP1;PW0.08; 四连发。

    PS 纸长 = 用布长度 × 40（生产文件 PS 值 == 全文件最大 X 坐标，同口径）。
    """
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    lines = out.split("\n")
    assert lines[0] == "IN;"
    assert lines[1] == "PS20000;"          # 500mm × 40
    assert lines[2] == "SP1;"
    assert lines[3] == "PW0.08;"


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
    """尾部 PU;PG;（抬笔 + 出纸结束页，生产 PLT 收尾指令）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="t")
    assert out.rstrip("\n").endswith("PU;\nPG;")


# --------------------------------------------- 坐标 ×40 缩放


def test_coordinate_scaled_by_40():
    """世界坐标(mm) × 40 后 round 取整：100mm → 4000 HPGL plotter unit。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    # polygon 顶点 (100,0) → (4000,0); (100,200) → (4000,8000)
    assert "4000,0" in out
    assert "4000,8000" in out
    assert "0,8000" in out
    # 门幅框 500×1000 → 20000×40000
    assert "20000,0" in out
    assert "20000,40000" in out


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


# --------------------------------------------- 闭合不变量


def test_polygon_closed_first_point_equals_last_in_PD():
    """闭合不变量：SP1 outline 的 PU 首点 == PD 末点（物理闭合，与 DXF POLYLINE 一致）。

    PUx0,y0;PD...xN,yN,x0,y0; —— PU 抬笔到首点，PD 走完所有边并回到首点。
    """
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    lines = out.split("\n")
    start = lines.index("PW0.08;")   # 跳过头部（SP1; 笔声明后第一个 PU 是 SP6 门幅框）
    for i in range(start, len(lines)):
        line = lines[i]
        if line.startswith("SP1;"):
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("PU"):
                    pu_line = lines[j]
                    pu_part, pd_part = pu_line.split("PD", 1)
                    first_coord = pu_part[2:].rstrip(";")
                    pd_coords = pd_part.rstrip(";")
                    assert pd_coords.endswith(first_coord), (
                        f"closure broken: PU first={first_coord!r} "
                        f"but PD does not end with it: {pd_coords!r}")
                    return  # 只校验首个 SP1（其余同构）
            pytest.fail("SP1 declared but no PU followed")
    pytest.fail("no SP1 outline section found")


def test_border_closed_back_to_origin():
    """门幅框 SP6 PD 末点 = (0,0)（物理闭合）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    lines = out.split("\n")
    border_section = ""
    for i, line in enumerate(lines):
        if line.startswith("SP6;"):
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("SP"):
                    break
                border_section += lines[j]
            break
    assert border_section, "SP6 declared but no PU/PD followed"
    assert border_section.rstrip().endswith("0,0;"), (
        f"border not closed at origin: {border_section!r}")


# --------------------------------------------- 门幅框四角


def test_border_four_corners_present():
    """门幅框四角 (0,0)(W,0)(W,G)(0,G) 全在 SP6 的 PD 序列中。"""
    W, G = 500.0, 1000.0
    out = _plt([_full_piece()], width_mm=W, gate_mm=G, title="")
    expected_corners_scaled = ["0,0", "20000,0", "20000,40000", "0,40000"]
    lines = out.split("\n")
    border_section = ""
    for i, line in enumerate(lines):
        if line.startswith("SP6;"):
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("SP"):
                    break
                border_section += lines[j]
            break
    for corner in expected_corners_scaled:
        assert corner in border_section, (
            f"corner {corner} missing from border section {border_section!r}")


# --------------------------------------------- 6 个笔号各出现一次


def test_all_six_pens_present_with_full_data():
    """5 层全有的裁片 + 门幅框 → SP1..SP6 各至少出现一次。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="hi")
    for pen in range(1, 7):
        assert f"SP{pen};" in out, (
            f"SP{pen}; missing (pen should be present when layer has data)")


# --------------------------------------------- 空层跳过


def test_empty_layers_skipped():
    """空层跳过：net/internal/notches/grain 全空 → SP2/3/4/5 不出现（仅 SP1 + SP6）。"""
    out = _plt([_bare_piece()], width_mm=100, gate_mm=100, title="")
    assert "SP1;" in out   # outline（头部 SP1; 也算，另见 test_partial_layers）
    assert "SP6;" in out   # border
    assert "SP2;" not in out
    assert "SP3;" not in out
    assert "SP4;" not in out
    assert "SP5;" not in out


def test_partial_layers_only_emits_present_pens():
    """部分层：仅 net + grain → SP1/2/5/6 出现，SP3/4 不出现。"""
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
    assert "SP6;" in out
    assert "SP3;" not in out
    assert "SP4;" not in out


# --------------------------------------------- 多片计数


def test_multi_piece_outline_count():
    """N 片 polygon → SP1 PU+PD 组出现 N 次。"""
    pieces = [
        _bare_piece(pid="P1", ptype="A"),
        _bare_piece(pid="P2", ptype="B"),
        _bare_piece(pid="P3", ptype="C"),
    ]
    out = _plt(pieces, width_mm=1000, gate_mm=1000, title="")
    # SP1 出现 4 次（头部 1 次 + 每片 1 次 × 3）
    assert out.count("SP1;") == 4
    # PU 总数：1 门幅框 + 3 outline + 尾部 PU; = 5
    assert out.count("PU") == 5


# --------------------------------------------- 5 层笔号语义校验（端到端）


def test_each_layer_uses_correct_pen_number():
    """5 层各用对应笔号：SP1 outline / SP2 net / SP3 internal / SP4 notch / SP5 grain。

    断言每个 SPn 紧跟的 PU/PD 几何与该层语义匹配（坐标特征可辨识）。
    """
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    lines = out.split("\n")

    def find_pd_after(sp_prefix, start=0):
        for i in range(start, len(lines)):
            if lines[i] == sp_prefix:
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("PU"):
                        return lines[j]
        return ""

    # SP1 outline：(0,0) 起，含 4000,8000 角点（跳过头部 SP1; 笔声明，从 PW 之后找）
    sp1_pd = find_pd_after("SP1;", start=lines.index("PW0.08;"))
    assert "0,0" in sp1_pd and "4000,8000" in sp1_pd, f"SP1 outline mismatch: {sp1_pd!r}"

    # SP2 net：起点 (10*40, 10*40) = (400,400)
    sp2_pd = find_pd_after("SP2;")
    assert "400,400" in sp2_pd, f"SP2 net start mismatch: {sp2_pd!r}"

    # SP3 internal：起点 (20*40, 20*40) = (800,800)
    sp3_pd = find_pd_after("SP3;")
    assert "800,800" in sp3_pd, f"SP3 internal start mismatch: {sp3_pd!r}"

    # SP4 notch：notch 在 (50,0) 法线 (0,-1) half=4，两端点 (50, 4) (50, -4) → clamp 非负
    # (50*40, 4*40)=(2000,160) 与 (2000,0)
    sp4_pd = find_pd_after("SP4;")
    assert "2000,160" in sp4_pd and "2000,0" in sp4_pd, f"SP4 notch mismatch: {sp4_pd!r}"

    # SP5 grain：两端点 (50,50)→(50,150) → (2000,2000)→(2000,6000)
    sp5_pd = find_pd_after("SP5;")
    assert "2000,2000" in sp5_pd and "2000,6000" in sp5_pd, f"SP5 grain mismatch: {sp5_pd!r}"


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
    """边缘片 notch 端点超出轮廓 bbox 几 mm → PS 纸长取内容最大 X（不裁内容）。"""
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
    # PS = max(490, 494) × 40 = 19760（若按布宽 490 取 19600 会裁掉 notch 端点）
    assert "PS19760;" in out


# --------------------------------------------- 边界


def test_IN_before_PS_before_PW_before_SP6():
    """指令顺序：IN; → PS; → SP1; → PW; → SP6;（对齐生产头部协议）。"""
    out = _plt([_full_piece()], width_mm=500, gate_mm=1000, title="")
    idx_in = out.index("IN;")
    idx_ps = out.index("PS20000;")
    idx_sp1 = out.index("SP1;")
    idx_pw = out.index("PW0.08;")
    idx_sp6 = out.index("SP6;")   # 门幅框是首个绘图 SP
    assert idx_in < idx_ps < idx_sp1 < idx_pw < idx_sp6


def test_empty_world_pieces_still_emits_header_and_border():
    """空 world_pieces（无裁片）→ 仍输出头部 IN;PS;SP1;PW; + SP6 门幅框（防御性边界）。"""
    out = _plt([], width_mm=300, gate_mm=600, title="")
    assert out.startswith("IN;")
    assert "PS12000;" in out       # 300mm × 40
    assert "PW0.08;" in out
    assert "SP6;" in out
    # 无 SP1-5 绘图段（头部 SP1; 是笔声明，绘图段 SP2-5 不出现）
    for pen in range(2, 6):
        assert f"SP{pen};" not in out


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
