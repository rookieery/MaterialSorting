"""E2E: 合成贴边 marker 走真实 write_marker_plt(clean=True)，对拍毛版口径。

对拍参考件 data/PC-20250508NJIF_5028-1#_29223513.plt 的毛版形态（2026-08-31；
命名当日由「净版」更名，与裁片「毛版轮廓」统一，协议值 'plt-clean' 不变）：
  1. 唛架左右各一份同内容表格（左表 value 带外缘与门幅左边框共线）；
  2. 正文每片只有毛版 polygon 闭合轮廓 + 尺码*数量标注（无净版线/内部线/刀口/布纹箭头线）。
片精确贴 y=0 / y=gate 两沿（复刻 3321 形态）。输出落 out/_clean_check.plt 与
out/_clean_check_full.plt（同载荷 clean=False 对照），供 scripts/_probe_redline.py 复测。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'materialSorting-server' / 'src'))
from materialsorting.web.export import write_marker_plt
from materialsorting.web.plt_table import build_info_table, parse_table_payload

GATE = 1700.0
WIDTH = 900.0


def piece(pid, x, y, w, h):
    return {"pid": pid, "ptype": "A", "size": 30,
            "polygon": [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
            "area_mm2": w * h,
            "net_polygon": [(x + 10, y + 10), (x + w - 10, y + 10), (x + w - 10, y + h - 10), (x + 10, y + h - 10)],
            "internal_lines": [[(x + 20, y + 20), (x + 40, y + 20)]],
            "notches": [(x + w / 2, y, 0.0, 1.0), (x + w / 2, y + h, 0.0, -1.0)],
            "grain_line": [x + w / 2, y + 30, x + w / 2, y + h - 30]}


world = [
    piece("A@0",   0.0, 0.0,    300.0, 400.0),   # 贴 y=0 下沿
    piece("B@top", 300.0, GATE - 400.0, 300.0, 400.0),  # 贴 y=gate 上沿
    piece("C",     600.0, 500.0, 300.0, 300.0),
]
info = build_info_table(world, width_mm=WIDTH, gate_mm=GATE, density=0.874,
                        table_in=parse_table_payload({}) or {})

raw_clean = write_marker_plt(world, width_mm=WIDTH, gate_mm=GATE, title="clean",
                             info_table=info, clean=True)
Path('out/_clean_check.plt').write_bytes(raw_clean)
raw_full = write_marker_plt(world, width_mm=WIDTH, gate_mm=GATE, title="cleanfull",
                            info_table=info)
Path('out/_clean_check_full.plt').write_bytes(raw_full)
print('wrote out/_clean_check.plt', len(raw_clean), 'bytes; full', len(raw_full), 'bytes')
