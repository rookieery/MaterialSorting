"""E2E: 合成贴边 marker 走真实 write_marker_plt，验证 Y 绘制平移几何。

合成形态复刻 3321：片精确贴 y=0 与 y=gate 两沿 + 表格。输出落 out/_y_lead_check.plt
（供 scripts/_probe_redline.py 复测）。预期：门幅框画在 y[5, gate+5]、内容 min-y >= 1
（贴沿片 = 5）、对拍点：修复前同场景框 y[0,gate]。
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
            "area_mm2": w * h, "net_polygon": [], "internal_lines": [],
            "notches": [], "grain_line": None}

world = [
    piece("A@0",   0.0, 0.0,    300.0, 400.0),   # 贴 y=0 下沿
    piece("B@top", 300.0, GATE - 400.0, 300.0, 400.0),  # 贴 y=gate 上沿
    piece("C",     600.0, 500.0, 300.0, 300.0),
]
info = build_info_table(world, width_mm=WIDTH, gate_mm=GATE, density=0.874, table_in=parse_table_payload({}) or {})
raw = write_marker_plt(world, width_mm=WIDTH, gate_mm=GATE, title="ylead", info_table=info)
out = Path('out/_y_lead_check.plt')
out.write_bytes(raw)
print('wrote', out, len(raw), 'bytes')
