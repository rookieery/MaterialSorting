"""US-033 PLT/HPGL 导出生成器单测。

覆盖 spec AC#13：
  - 闭合不变量（polygon PD 末点 = PU 首点，与 DXF POLYLINE 闭合策略一致）
  - 坐标 ×40 缩放（100mm → 4000 HPGL plotter unit）
  - 首条 ``IN;`` 初始化指令
  - 6 个笔号（SP1-SP6）各有数据时至少出现一次
  - 空层跳过（net/internal/notches/grain 空 → 对应 SP 不出现）
  - 多片计数（N 个 polygon → SP1 PU+PD 组出现 N 次）
  - ``LB<title>chr(3);`` 文字指令 + ETX 终止符
  - bytes 返回类型 + 全 ASCII
  - 门幅框四角 + 闭合

测试用合成 5 层裁片（不依赖 intermediate / sparrow），断言 PLT 文本结构正确。
"""
from __future__ import annotations

import pytest

from materialsorting.web.export import write_marker_plt


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


# --------------------------------------------- AC#13 首条 IN; + 速度


def test_first_command_is_IN():
    """输出首条指令 IN;（HPGL Initialize）。"""
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="hi")
    assert out.decode("ascii").startswith("IN;")


def test_contains_velocity_command():
    """含 VS80; 速度指令（_PLT_VELOCITY=80）。"""
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="hi")
    assert b"VS80;" in out


# --------------------------------------------- AC#13 bytes + 全 ASCII


def test_returns_bytes_and_ascii_decodable():
    """返回 bytes 类型且 .decode("ascii") 不抛异常（含 chr(3) ETX 也是 ASCII 控制符）。"""
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="ascii_only")
    assert isinstance(out, bytes)
    out.decode("ascii")  # no UnicodeDecodeError


# --------------------------------------------- AC#13 坐标 ×40 缩放


def test_coordinate_scaled_by_40():
    """世界坐标(mm) × 40 后 round 取整：100mm → 4000 HPGL plotter unit。"""
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="").decode("ascii")
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
    out = write_marker_plt([piece], width_mm=100, gate_mm=100, title="").decode("ascii")
    # 所有 HPGL 坐标应为整数 —— PD 行内坐标以 , 分隔，全为数字
    for line in out.split("\n"):
        if line.startswith("PD"):
            coords = line[2:].rstrip(";")
            for tok in coords.split(","):
                assert tok.isdigit(), f"non-integer coord {tok!r} in PD line {line!r}"


# --------------------------------------------- AC#13 闭合不变量


def test_polygon_closed_first_point_equals_last_in_PD():
    """闭合不变量：SP1 outline 的 PU 首点 == PD 末点（物理闭合，与 DXF POLYLINE 一致）。

    PUx0,y0;PD...xN,yN,x0,y0; —— PU 抬笔到首点，PD 走完所有边并回到首点。
    """
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="").decode("ascii")
    lines = out.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("SP1;"):
            # 下一个 PU 行即 outline（_plt_polyline 输出 "PU...;PD...;" 同行）
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("PU"):
                    pu_line = lines[j]
                    # PU<x>,<y>;PD<x1>,<y1>,...,<x0>,<y0>;
                    pu_part, pd_part = pu_line.split("PD", 1)
                    first_coord = pu_part[2:].rstrip(";")   # strip "PU" + trailing ";"
                    pd_coords = pd_part.rstrip(";")
                    assert pd_coords.endswith(first_coord), (
                        f"closure broken: PU first={first_coord!r} "
                        f"but PD does not end with it: {pd_coords!r}")
                    return  # 只校验首个 SP1（其余同构）
            pytest.fail("SP1 declared but no PU followed")


def test_border_closed_back_to_origin():
    """门幅框 SP6 PD 末点 = (0,0)（物理闭合）。"""
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="").decode("ascii")
    lines = out.split("\n")
    border_section = ""
    for i, line in enumerate(lines):
        if line.startswith("SP6;"):
            # 收集后续 PU/PD 行直到下一个 SP
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("SP"):
                    break
                border_section += lines[j]
            break
    assert border_section, "SP6 declared but no PU/PD followed"
    # PD 末点应是 0,0（PU0,0;PD...,0,0;）
    assert border_section.rstrip().endswith("0,0;"), (
        f"border not closed at origin: {border_section!r}")


# --------------------------------------------- AC#13 门幅框四角


def test_border_four_corners_present():
    """门幅框四角 (0,0)(W,0)(W,G)(0,G) 全在 SP6 的 PD 序列中。"""
    W, G = 500.0, 1000.0
    out = write_marker_plt([_full_piece()], width_mm=W, gate_mm=G, title="").decode("ascii")
    # W×40=20000, G×40=40000
    expected_corners_scaled = ["0,0", "20000,0", "20000,40000", "0,40000"]
    # SP6 段：抽出门幅框 PU+PD 文本
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


# --------------------------------------------- AC#13 6 个笔号各出现一次


def test_all_six_pens_present_with_full_data():
    """5 层全有的裁片 + 门幅框 → SP1..SP6 各至少出现一次。"""
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="").decode("ascii")
    for pen in range(1, 7):
        assert f"SP{pen};" in out, (
            f"SP{pen}; missing (pen should be present when layer has data)")


# --------------------------------------------- AC#13 空层跳过


def test_empty_layers_skipped():
    """空层跳过：net/internal/notches/grain 全空 → SP2/3/4/5 不出现（仅 SP1 + SP6）。"""
    out = write_marker_plt([_bare_piece()], width_mm=100, gate_mm=100, title="").decode("ascii")
    assert "SP1;" in out   # outline
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
    out = write_marker_plt([piece], width_mm=100, gate_mm=100, title="").decode("ascii")
    assert "SP1;" in out
    assert "SP2;" in out
    assert "SP5;" in out
    assert "SP6;" in out
    assert "SP3;" not in out
    assert "SP4;" not in out


# --------------------------------------------- AC#13 多片计数


def test_multi_piece_outline_count():
    """N 片 polygon → SP1 PU+PD 组出现 N 次。"""
    pieces = [
        _bare_piece(pid="P1", ptype="A"),
        _bare_piece(pid="P2", ptype="B"),
        _bare_piece(pid="P3", ptype="C"),
    ]
    out = write_marker_plt(pieces, width_mm=1000, gate_mm=1000, title="").decode("ascii")
    # SP1 出现 3 次（每片一次）
    assert out.count("SP1;") == 3
    # PU 总数：1 门幅框 + 3 outline = 4
    assert out.count("PU") == 4


# --------------------------------------------- AC#13 LB 文字指令 + ETX 终止


def test_LB_with_ETX_terminator_when_title_nonempty():
    """title 非空 → LB<title>chr(3); 出现，chr(3)=ETX 是 LB 默认终止符。"""
    title = "M1787 util=87.50pct L=120.0cm gate=1980 seed=1"
    out = write_marker_plt([_full_piece()], width_mm=1200, gate_mm=1980, title=title)
    expected = ("LB" + title + chr(3) + ";").encode("ascii")
    assert expected in out, f"LB title+ETX not found; expected {expected!r} in output"


def test_LB_skipped_when_title_empty():
    """title 空字符串 → 不输出 LB 指令。"""
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="").decode("ascii")
    assert "LB" not in out


# --------------------------------------------- AC#13 5 层笔号语义校验（端到端）


def test_each_layer_uses_correct_pen_number():
    """5 层各用对应笔号：SP1 outline / SP2 net / SP3 internal / SP4 notch / SP5 grain。

    断言每个 SPn 紧跟的 PU/PD 几何与该层语义匹配（坐标特征可辨识）。
    """
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="").decode("ascii")
    lines = out.split("\n")

    def find_pd_after(sp_prefix):
        for i, line in enumerate(lines):
            if line == sp_prefix:
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("PU"):
                        return lines[j]
        return ""

    # SP1 outline：(0,0) 起，含 4000,8000 角点
    sp1_pd = find_pd_after("SP1;")
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


# --------------------------------------------- 附加：IN; / VS; 顺序 + 边界


def test_IN_before_VS_before_SP():
    """指令顺序：IN; 先于 VS; 先于首个 SP;（HPGL 初始化协议）。"""
    out = write_marker_plt([_full_piece()], width_mm=500, gate_mm=1000, title="").decode("ascii")
    idx_in = out.index("IN;")
    idx_vs = out.index("VS80;")
    idx_sp = out.index("SP6;")   # 门幅框是首个 SP
    assert idx_in < idx_vs < idx_sp


def test_empty_world_pieces_still_emits_IN_and_border():
    """空 world_pieces（无裁片）→ 仍输出 IN; + VS; + SP6 门幅框（防御性边界）。"""
    out = write_marker_plt([], width_mm=300, gate_mm=600, title="").decode("ascii")
    assert out.startswith("IN;")
    assert "VS80;" in out
    assert "SP6;" in out
    # 无 SP1-5
    for pen in range(1, 6):
        assert f"SP{pen};" not in out


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
