"""PLT 唛架末端「文件信息表格」构建（2026-08-30）。

生产 PLT（data/PC-20250508NJIF*.plt，ET 排料软件产出）在唛架末端带 12 字段
两列标签表：旋转 90°、贴 y=0 布边、占末端 ~565mm×~300mm、在门幅边框内且
长度计入用料（生产件 bbox 10058.9mm ≈ 表内用料 10.06m 已对拍）。本模块按
逆向测量规格重建该表格，文字来自 plt_text 矢量引擎（捆绑 Noto Sans SC 轮廓，
无 LB 指令口径不变）。

字段来源（2026-08-30 与用户确认）：
  - 手输 6 字段（前端导出弹窗，localStorage 记忆）：床次/铺布层数/拉布方式/
    排料师/款式号/备注 —— 系统里没有的生产计划信息
  - 系统自动 6 字段：
      用料(m)   = (width_mm + GAP + LEN)/1000，2 位小数 —— 含表格段（生产口径）
      幅宽      = gate_mm 整数
      利用率    = real_density×100，2 位 + '%'（density≤0 → '--'）
      单耗(m)   = 用料 ÷ 每层件数，3 位小数（生产 10.06/80=0.126 已对拍）
      共N件     = 每层件数 × 层数（640=80×8 已对拍）；每层件数 = len(world_pieces)
                  （placed 已含 demand 多副本）
      日期时间  = 导出时刻（服务端生成，'YYYY-MM-DD HH:MM:SS'）

层序：表格笔画在 export_plt 五层（outline→net→internal→notch→grain）之后
追加为独立 _LAYER_TABLE 桶（元数据与裁片几何分离）；**不过 y≤gate 裁剪**
（裁剪切坏文字；gate 异常小时仅 warning）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from .plt_text import text_strokes, text_width

# ---- 几何常量（生产件逆向测量，E2E 目检后如需微调只动这里） ----
TABLE_GAP_MM = 20.0    # 唛架末端 width_mm → 表格区起点间隙（裁切分离）
TABLE_LEN_MM = 565.0   # 表格区总长 = PAD_X 55 + 6×ROW_PITCH 75 + TAIL 60（计入用料）
TABLE_PAD_X_MM = 55.0  # 表格起点 → 第 0 行行带中心
TABLE_TAIL_X_MM = 60.0  # 末行行带中心 → 表格终点
ROW_PITCH_MM = 75.0    # 行距（生产实测 2500-3000u 取整）
TABLE_COL_W_MM = 150.0  # 每列宽（沿 y）：列1 y∈[0,150]、列2 y∈[150,300]
TABLE_PAD_Y_MM = 12.0  # 列内文字离列边（shrink 可用宽 = 150-2×12 = 126mm）
TABLE_CHAR_H_MM = 18.0   # 标称字高（生产 18-20mm；Noto em 全宽，长格自动 shrink）
TABLE_CHAR_H_MIN_MM = 9.0   # shrink-to-fit 下限（低于此不可读，改为尾部截断）
TABLE_LABEL_GAP_MM = 15.0   # 标签到值的间隙（生产观感 ~0.75 字高）
TABLE_SEP_LINE_Y_MM = 150.0  # 列分隔细单线（y=150 横贯表格区）
# 文字方向：False = u=(0,1) 沿 +y 阅读（生产同款，cw 旋转渲染后水平可读）；
# True = u=(0,-1)。字顶 w=(-uy,ux) 恒右手系（plt_text 手性防御）。
TABLE_TEXT_FLIP = False
# 行序：True = row 0（备注）靠唛架一侧（生产同款）；False = 反序
TABLE_ROW_ORDER_FROM_MARKER = True

# 手输字段长度上限（超长截断 + warning；弹窗层另有软上限，这里兜底）与
# 缺省值（2026-08-30 用户确认：层数 1 / 单向 / noname，其余空）
_MAX_LEN = {'bed_no': 20, 'lay_method': 10, 'planner': 20, 'style_no': 30,
            'remark': 60}
_STR_DEFAULTS = {'bed_no': '', 'lay_method': '单向', 'planner': 'noname',
                 'style_no': '', 'remark': ''}
_PLY_MAX = 999   # 铺布层数上限（防 0/负数/离谱值进生产文件）

_COL1_FIELDS = ('备注', '排料师', '款式', '日期时间', '床次', '面料利用率', '幅宽')
_COL2_FIELDS = ('单耗（米）', '铺布层数', '拉布方式', '用料（米）')


class TablePayloadError(ValueError):
    """/export payload 的 table 对象非法（路由转 400 结构化 JSON）。"""


@dataclass(frozen=True)
class InfoTable:
    """表格字段全集（手输 6 + 自动 6；渲染口径见模块 docstring）。"""

    # 手输（导出弹窗）
    bed_no: str = ''
    ply_count: int = 1
    lay_method: str = '单向'
    planner: str = 'noname'
    style_no: str = ''
    remark: str = ''
    # 系统自动（build_info_table 补全）
    fabric_len_m: float = 0.0       # 用料(m) 含表格段
    gate_mm: float = 0.0            # 幅宽
    utilization_pct: float = 0.0    # 利用率（百分比数值；≤0 渲染 '--'）
    per_layer_pieces: int = 0       # 每层件数 = len(world_pieces)
    unit_consumption_m: float = 0.0  # 单耗(m) = 用料 ÷ 每层件数
    datetime_str: str = ''          # 导出时刻


def parse_table_payload(raw) -> dict | None:
    """/export payload 的 table 对象 → 规范化 dict（build_info_table 的 table_in）。

    None / 非 dict → None（不带表格，旧调用零变化）；字段缺省取默认（层数 1 /
    单向 / noname / 其余空）。字符串清洗：strip + 换行制表折成空格 + 超长截断
    （warning）；ply_count 非正整数或 >999 → TablePayloadError。
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TablePayloadError(f'table 需为对象，got {type(raw).__name__}')

    out: dict = {}

    def _clean_str(key: str) -> str:
        if key not in raw:
            return _STR_DEFAULTS[key]      # 键缺省 → 约定默认（单向/noname/…）
        v = raw[key]
        if v is None:
            return ''    # 显式 null/空串 = 用户清空（不回填默认）
        if v is None:
            return ''
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(v)
        if not isinstance(v, str):
            raise TablePayloadError(f'{key} 需为字符串，got {type(v).__name__}')
        v = ' '.join(v.split())   # 折叠换行/制表/连续空白（表格单行渲染）
        limit = _MAX_LEN[key]
        if len(v) > limit:
            logging.warning('PLT 信息表格：字段 %s 超长（%d 字符），截断为 %d',
                            key, len(v), limit)
            v = v[:limit]
        return v

    for key in _MAX_LEN:
        out[key] = _clean_str(key)

    ply = raw.get('ply_count', 1)
    if ply is None:
        ply = 1
    if isinstance(ply, bool) or not isinstance(ply, (int, float)):
        raise TablePayloadError(f'ply_count 需为整数，got {type(ply).__name__}')
    if isinstance(ply, float):
        if not ply.is_integer():
            raise TablePayloadError(f'ply_count 需为整数，got {ply}')
        ply = int(ply)
    if not (1 <= ply <= _PLY_MAX):
        raise TablePayloadError(f'ply_count 需在 1..{_PLY_MAX}，got {ply}')
    out['ply_count'] = ply
    return out


def build_info_table(world_pieces, *, width_mm: float, gate_mm: float,
                     density: float, table_in: dict,
                     now: datetime | None = None) -> InfoTable:
    """规范化的手输字段 + 求解上下文 → InfoTable（补全系统自动字段）。

    每层件数 = len(world_pieces)（placed_to_world 已含 demand 多副本，
    同 pid N 行 = N 件）。
    """
    per_layer = len(world_pieces)
    fabric_len_m = (float(width_mm) + TABLE_GAP_MM + TABLE_LEN_MM) / 1000.0
    unit = fabric_len_m / per_layer if per_layer > 0 else 0.0
    dt = (now or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
    return InfoTable(
        bed_no=table_in.get('bed_no', ''),
        ply_count=int(table_in.get('ply_count', 1)),
        lay_method=table_in.get('lay_method', '单向'),
        planner=table_in.get('planner', 'noname'),
        style_no=table_in.get('style_no', ''),
        remark=table_in.get('remark', ''),
        fabric_len_m=fabric_len_m,
        gate_mm=float(gate_mm),
        utilization_pct=float(density) * 100.0,
        per_layer_pieces=per_layer,
        unit_consumption_m=unit,
        datetime_str=dt,
    )


def _cell_texts(t: InfoTable) -> list[tuple[list[str], list[float]]]:
    """12 格 → [(该格文本段列表, 段后间隙列表)]。每段 = label / value / 注记。"""
    util = f'{t.utilization_pct:.2f}%' if t.utilization_pct > 0 else '--'
    unit = f'{t.unit_consumption_m:.3f}' if t.per_layer_pieces > 0 else '--'
    col1_vals = (t.remark, t.planner, t.style_no, t.datetime_str, t.bed_no,
                 util, str(int(round(t.gate_mm))))
    col2_vals = (unit, str(t.ply_count), t.lay_method, f'{t.fabric_len_m:.2f}')

    cells: list[tuple[list[str], list[float]]] = []
    for label, val in zip(_COL1_FIELDS, col1_vals):
        # 空值 → 仅渲染标签（生产件「备注」空行同款）
        segs = [label] + ([val] if val else [])
        gaps = [TABLE_LABEL_GAP_MM] * (len(segs) - 1)
        cells.append((segs, gaps))
    for label, val in zip(_COL2_FIELDS, col2_vals):
        segs = [label] + ([val] if val else [])
        gaps = [TABLE_LABEL_GAP_MM] * (len(segs) - 1)
        cells.append((segs, gaps))
    # 列2 末行：共N件注记（生产同款整句、无 label:value 结构）
    cells.append(([f'共{t.per_layer_pieces * t.ply_count}件'], []))
    return cells


def _cell_strokes(segs: list[str], gaps: list[float], *, row_cx: float,
                  y0: float) -> list[list[tuple[float, float]]]:
    """一格（label + gap + value）→ 世界 mm 折线。整格 shrink-to-fit（长值如
    「面料利用率 84.86%」按 Noto em 全宽计 165mm > 126mm 可用宽，统一缩到
    ~13.7mm 而非混排两号字）；压到下限仍超由 text_strokes 尾部截断。"""
    fit_w = TABLE_COL_W_MM - 2 * TABLE_PAD_Y_MM
    char_h = TABLE_CHAR_H_MM
    total = (sum(text_width(s, char_h) for s in segs) + sum(gaps)) if segs else 0.0
    if total > fit_w > 0:
        char_h = max(TABLE_CHAR_H_MIN_MM, char_h * fit_w / total)
    ux, uy = (0.0, -1.0) if TABLE_TEXT_FLIP else (0.0, 1.0)
    wx, wy = -uy, ux                      # 右手系字顶方向（plt_text 防御同款）
    baseline_x = row_cx + char_h / 2.0    # 基线在行带中心 +h/2，字顶向 −x
    strokes: list[list[tuple[float, float]]] = []
    y = y0
    for i, s in enumerate(segs):
        if s:
            budget = fit_w - (y - y0)
            strokes.extend(text_strokes(
                s, origin=(baseline_x, y), u=(ux, uy), w=(wx, wy),
                char_h_mm=char_h, fit_width_mm=budget if budget > 0 else None))
            y += text_width(s, char_h)
        if i < len(gaps):
            y += gaps[i]
    return strokes


def info_table_polylines(t: InfoTable, *,
                         table_x0: float) -> list[tuple[bool, list]]:
    """InfoTable → [(closed, points)] 世界 mm 折线（文本轮廓 closed=True、
    分隔线 closed=False），交 export_plt._plt_polyline 输出。

    table_x0 = 表格区起点 x（= width_mm + TABLE_GAP_MM，由调用方传入，本模块
    不依赖求解宽度）。全部点落在 [table_x0, table_x0+565]×[0,300]（元数据，
    不过 y≤gate 裁剪；gate 异常小仅 warning）。
    """
    if t.gate_mm and t.gate_mm < 2 * TABLE_COL_W_MM + 20:
        logging.warning('PLT 信息表格：门幅 %.0fmm 小于表格宽度 ~%dmm，'
                        '表格可能压门幅上边框（不裁剪文字，按原样输出）',
                        t.gate_mm, 2 * TABLE_COL_W_MM)

    out: list[tuple[bool, list]] = []
    n_rows_col1 = len(_COL1_FIELDS)   # 7
    n_rows_col2 = len(_COL2_FIELDS) + 1   # 5（含共N件注记行）

    def _row_cx(col: int, row: int, n_rows: int) -> float:
        idx = row if TABLE_ROW_ORDER_FROM_MARKER else (n_rows - 1 - row)
        return table_x0 + TABLE_PAD_X_MM + idx * ROW_PITCH_MM

    cells = _cell_texts(t)
    for col, n_rows in ((0, n_rows_col1), (1, n_rows_col2)):
        for row in range(n_rows):
            segs, gaps = cells[row if col == 0 else n_rows_col1 + row]
            out.extend(
                (True, st) for st in _cell_strokes(
                    segs, gaps, row_cx=_row_cx(col, row, n_rows),
                    y0=col * TABLE_COL_W_MM + TABLE_PAD_Y_MM))

    # 分隔线：列间细单线（y=150 横贯）+ 各列行间细分线（行带中心之间）
    out.append((False, [(table_x0, TABLE_SEP_LINE_Y_MM),
                        (table_x0 + TABLE_LEN_MM, TABLE_SEP_LINE_Y_MM)]))
    for col, n_rows in ((0, n_rows_col1), (1, n_rows_col2)):
        y0, y1 = col * TABLE_COL_W_MM, (col + 1) * TABLE_COL_W_MM
        for i in range(n_rows - 1):
            cx_a = _row_cx(col, i, n_rows)
            cx_b = _row_cx(col, i + 1, n_rows)
            xm = (cx_a + cx_b) / 2.0
            out.append((False, [(xm, y0), (xm, y1)]))
    return out
