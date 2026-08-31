"""PLT 唛架信息表格（2026-08-30 v5：单线字体 + 共线边框 + 3cm 起始 + 单元格居中）。

对齐用户 2026-08-30 定稿口径（v4 结构保留，v5 细节四项）：

- **位置**：排料图**外围**——表格区左缘 = 唛架末端 width_mm + TABLE_GAP_MM
  （v5 = 0：**表格外框左缘与唛架右边框共用一条线**，中间空隙移除，用户定案），
  **不在唛架边框内、不占排料区、不计入用料**（切割时布上没有这块，只在 PLT
  图纸上展示；PS 纸长仍覆盖表格区防止被 WT 裁掉）。
- **起始位置**（v5）：从唛架**右下顶点**（世界 (width_mm, 0)，用户软件视图
  的右下角）**垂直向上 3cm** —— 列 0（方案名称）自 y=TABLE_Y_START_MM=30mm
  起沿 +y 排开，不再贴 y=0 布边。
- **版式（v4 核心）**：**key 行 + value 行的两行网格**（对标前端「裁片设置」
  表格：第一行 key、第二行 value、行列分隔线、外框）。**文字旋转 90°**——
  基线沿世界 +y（门幅方向）、字顶朝世界 −x（朝向唛架），基
  ``u=(0,1), w=(-1,0)``（右手系 det=+1，直接过 plt_text 防镜像守卫）。
  生产排料软件视图（= 切割视图逆时针旋 90°，x 竖直）里该表格呈现为正常
  水平可读的两行表：**key 行在上、value 行在下**（世界 −x 侧 = 视图上方 ⇒
  key 行带最靠唛架），14 字段自下向上 = 世界 +y 顺序排列。
- **字段 = 列**：14 个字段各占一列，**列宽自适应**
  = max(key 宽, value 宽) + 2×CELL_PAD_MM（v5 内衬 3→10mm：单元格内容
  **居中**且离左右边至少 1cm，用户定案）。
- **字体（v5）**：单线矢量字（plt_text 默认路径：汉字笔画中线 + Hershey
  Roman Simplex ASCII），对拍生产件一笔单线观感；未覆盖字符 Noto 轮廓回退。
- **表长自适应**（用户定案：不需要和幅宽等长）：外框
  [x0, x0+W]×[Y_START, Y_START+L]，L = Σ列宽 ≤ gate − EDGE − Y_START；
  超限先全表缩字高（12→7mm 下限）再等比压列宽（单元格内 shrink+尾截断
  兜底），窄门幅记 warning。
- **字高统一**：全部字段（含方案名称）TABLE_CHAR_H_MM=12mm——v3 的方案
  名称 36mm 大字被用户否决（「应该和其它字段字体保持一样大」）。

14 字段（列 0→列 13）与来源：

=====  ============= ==================================================
列     标签           来源
=====  ============= ==================================================
 0     方案名称       勾选尺码计算（见下）
 1     床次           手输（默认 A料）
 2     经纱缩水       手输（默认 0.0%）
 3     纬纱缩水       手输（默认 0.0%）
 4     利用率         real_density×100，2 位小数 + %
 5     幅宽           gate_mm/1000，3 位小数 + m
 6     料长           width_mm/1000，3 位小数 + m（**不含表格/引导**）
 7     本床包含套数   方案名称算出的套数
 8     每套用料       料长÷套数，3 位小数 + m
 9     片数           len(world_pieces)（placed 已含 demand 多副本）
10     排料师         手输（默认空）
11     绘图时间       算法出结果时刻 ``%Y-%m-%d %H:%M``（无秒）
12     样板号         手输（默认 noname）
13     备注           手输（默认空）
=====  ============= ==================================================

方案名称口径（用户例：``(30+34+35)+(31+32+33)*1.5+(36)*0.5=8套``）：

- 每码系数 = 该码**面积最大裁片**的同 pid 计数 ÷ 2（前/后幅数量永远相等，
  取面积最大者最有代表性；demand 多副本在 world_pieces 里逐条展开，计数
  即需求副本数）；
- 同系数码括号分组、组内码升序 '+' 连接，组间按组内最小码排序；系数 1 无
  后缀，其余 ``*1.5`` 式（数值去尾零）；
- 套数 = Σ系数（去尾零 + ``套``）。

零回归红线：``write_marker_plt(info_table=None)`` 输出逐字节不变（表格是
纯 additive 外挂层）。文字是文件级元数据 PU/PD 笔画，「PLT 永不加文字」
口径指 g 码不进 PLT，与此不冲突且仍无 LB/VS 指令。
"""
from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from .plt_text import text_strokes, text_width


class TablePayloadError(ValueError):
    """/export payload ``table`` 段非法（路由层转 400 结构化错误）。"""


# ===================== 几何常量（v5 两行网格自适应版式）=====================
TABLE_GAP_MM = 0.0         # 唛架末端 width_mm → 表格区左缘（v5：0 = 外框左缘
                           # 与唛架右边框共用一条线，空隙移除，用户定案）
TABLE_Y_START_MM = 30.0    # 列 0 起始 y：唛架右下顶点 (width,0) 垂直向上 3cm
TABLE_CHAR_H_MM = 12.0     # 全字段统一字高（含方案名称；用户嫌 18 偏大）
TABLE_CHAR_H_MIN_MM = 7.0  # 表长超限 shrink 下限
ROW_BAND_H_MM = 18.0       # 每条行带高（沿 x）= 字高 + 2×3mm 上下衬
CELL_PAD_MM = 10.0         # 单元格内衬（列宽方向沿 y；v5：≥1cm + 内容居中）
TABLE_EDGE_PAD_MM = 20.0   # 表长安全余量：Y_START+L ≤ gate − 20
N_TABLE_ROWS = 14          # 字段数 = 列数
# 表格区总宽（沿 x）= key 行带 + value 行带（纸上元数据，不计入用料）
TABLE_W_MM = 2.0 * ROW_BAND_H_MM  # = 36

# 手输字段：payload 键 → (默认值, 截断长度)
_HAND_FIELDS = {
    'bed_no': ('A料', 20),
    'warp_shrink': ('0.0%', 12),
    'weft_shrink': ('0.0%', 12),
    'planner': ('', 20),
    'style_no': ('noname', 30),
    'remark': ('', 60),
}


@dataclass(frozen=True)
class InfoTable:
    """唛架信息表格内容（手输 6 + 自动 8，渲染口径见 _row_texts）。"""

    # 手输（parse_table_payload 产物直通）
    bed_no: str
    warp_shrink: str
    weft_shrink: str
    planner: str
    style_no: str
    remark: str
    # 自动
    plan_name: str          # 方案名称（勾选尺码计算式）
    sets_count: float       # 本床包含套数 = Σ每码系数
    utilization_pct: float  # 利用率（real_density×100）
    gate_m: float           # 幅宽（m）
    fabric_len_m: float     # 料长（m，不含表格/引导）
    per_set_m: float        # 每套用料（m；套数 0 时无意义，渲染 '--'）
    total_pieces: int       # 片数 = len(world_pieces)
    draw_time_str: str      # 绘图时间 '%Y-%m-%d %H:%M'


def _fold_ws(s: str) -> str:
    """内部连续空白折叠单空格（防手输换行/多空格撑爆列宽）。"""
    return ' '.join(s.split())


def _fmt_num(x: float) -> str:
    """数值去尾零（1.0→'1'，7.5→'7.5'，0.5→'0.5'）。"""
    s = f'{x:.3f}'.rstrip('0').rstrip('.')
    return s if s else '0'


def parse_table_payload(raw):
    """校验 /export payload 的 ``table`` 段 → 手输字段 dict（None → None）。

    全字段可选字符串，缺省取默认值（A料/0.0%/0.0%/空/noname/空）；int/float
    宽容转 str（API 调用者传裸数字不炸）；strip + 内部空白折叠 + 超长截断
    （截断记 warning，不静默）。非 dict / 字段非字符串抛
    :class:`TablePayloadError`（路由层 400）。
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TablePayloadError('信息表格 table 段必须是对象')
    out = {}
    for key, (default, cap) in _HAND_FIELDS.items():
        val = raw.get(key, default)
        if val is None:
            val = ''
        if isinstance(val, bool):
            raise TablePayloadError(f'信息表格字段 {key} 必须是字符串')
        if isinstance(val, (int, float)):
            val = str(val)
        if not isinstance(val, str):
            raise TablePayloadError(f'信息表格字段 {key} 必须是字符串')
        val = _fold_ws(val.strip())
        if len(val) > cap:
            logging.warning('PLT 信息表格字段 %s 超长（%d 字符），截断到 %d',
                            key, len(val), cap)
            val = val[:cap]
        out[key] = val
    return out


def _size_key(s):
    """尺码排序键：数值码按数值升序，非数值垫后按字典序。"""
    try:
        return (0, float(s), '')
    except (TypeError, ValueError):
        return (1, 0.0, str(s))


def _plan_name_and_sets(world_pieces):
    """方案名称 + 套数（口径见模块 docstring）。

    返回 ``(plan_name, sets)``；world_pieces 为空 → ``('--', 0.0)``。
    """
    if not world_pieces:
        return '--', 0.0
    cnt = Counter(pc.get('pid') for pc in world_pieces)
    # 每码面积最大裁片的 pid（前/后幅数量恒等，面积最大者代表该码数量）
    largest = {}
    for pc in world_pieces:
        size = pc.get('size')
        area = float(pc.get('area_mm2') or 0.0)
        prev = largest.get(size)
        if prev is None or area > prev[1]:
            largest[size] = (pc.get('pid'), area)
    coeff = {size: cnt.get(pid, 0) / 2.0 for size, (pid, _a) in largest.items()}
    sizes = sorted(largest, key=_size_key)
    # 同系数全局分组（非相邻分组：用户例 30/34/35 同组与 31-33 穿插），
    # 组内码升序，组间按组内最小码排序
    by_coeff = {}
    for s in sizes:
        by_coeff.setdefault(coeff[s], []).append(s)
    groups = sorted(by_coeff.items(), key=lambda kv: _size_key(kv[1][0]))
    parts = []
    for c, ss in groups:
        part = '(' + '+'.join(str(s) for s in ss) + ')'
        if c != 1:
            part += f'*{_fmt_num(c)}'
        parts.append(part)
    sets = math.fsum(coeff[s] for s in sizes)
    return '+'.join(parts) + f'={_fmt_num(sets)}套', sets


def build_info_table(world_pieces, *, width_mm, gate_mm, density, table_in, now=None):
    """补自动字段 → :class:`InfoTable`（手输 6 字段从 table_in 直通）。"""
    dt = datetime.now() if now is None else now
    plan_name, sets = _plan_name_and_sets(world_pieces)
    fabric_len_m = float(width_mm) / 1000.0
    per_set_m = fabric_len_m / sets if sets > 0 else 0.0
    return InfoTable(
        bed_no=table_in['bed_no'],
        warp_shrink=table_in['warp_shrink'],
        weft_shrink=table_in['weft_shrink'],
        planner=table_in['planner'],
        style_no=table_in['style_no'],
        remark=table_in['remark'],
        plan_name=plan_name,
        sets_count=sets,
        utilization_pct=float(density) * 100.0,
        gate_m=float(gate_mm) / 1000.0,
        fabric_len_m=fabric_len_m,
        per_set_m=per_set_m,
        total_pieces=len(world_pieces),
        draw_time_str=dt.strftime('%Y-%m-%d %H:%M'),
    )


def _row_texts(t: InfoTable) -> list:
    """14 字段 ``(key, value)`` 对（列 0→13 = 方案名称..备注；value 空 → ''
    仅渲染 key，不再拼「标签 值」单行——v4 用户定案 key/value 分行）。"""
    util = f'{t.utilization_pct:.2f}%' if t.utilization_pct > 0 else '--'
    per_set = f'{t.per_set_m:.3f}m' if t.sets_count > 0 else '--'
    rows = [
        ('方案名称', t.plan_name),
        ('床次', t.bed_no),
        ('经纱缩水', t.warp_shrink),
        ('纬纱缩水', t.weft_shrink),
        ('利用率', util),
        ('幅宽', f'{t.gate_m:.3f}m'),
        ('料长', f'{t.fabric_len_m:.3f}m'),
        ('本床包含套数', _fmt_num(t.sets_count)),
        ('每套用料', per_set),
        ('片数', str(t.total_pieces)),
        ('排料师', t.planner),
        ('绘图时间', t.draw_time_str),
        ('样板号', t.style_no),
        ('备注', t.remark),
    ]
    assert len(rows) == N_TABLE_ROWS
    return rows


# 槽位元数据：(key, manual) 与 _row_texts 渲序一一对齐（标签从 _row_texts 取
# 不重复维护；长度 assert + 测试标签对齐双锁）。preview_rows 消费——前端导出
# 弹窗只读展示 8 自动字段用（2026-08-31），列序权威恒在本模块。
_ROW_META = (
    ('plan_name', False), ('bed_no', True), ('warp_shrink', True),
    ('weft_shrink', True), ('utilization', False), ('gate', False),
    ('fabric_len', False), ('sets', False), ('per_set', False),
    ('pieces', False), ('planner', True), ('draw_time', False),
    ('style_no', True), ('remark', True),
)
assert len(_ROW_META) == N_TABLE_ROWS


def preview_rows(t: InfoTable) -> list:
    """14 行 ``[{key, label, value, manual}]``（顺序/格式 = _row_texts 同一真相源）。

    供 ``/api/plt-table-preview`` 端点返回给前端导出弹窗：manual 行渲染手输
    输入框（值取前端本地草稿，此处 value = 默认值仅供参考），非 manual 行
    只读展示 value 成品字符串（前端零公式镜像）。
    """
    return [{'key': k, 'label': label, 'value': val, 'manual': m}
            for (k, m), (label, val) in zip(_ROW_META, _row_texts(t))]


def _column_layout(t: InfoTable, *, gate_mm: float):
    """14 列自适应布局 → ``(pairs, char_h, widths)``。

    列宽 = max(key 宽, value 宽) + 2×CELL_PAD（标称字高下实测）；
    Σ列宽 > gate − EDGE − Y_START（起始 30mm + 顶部余量）时全表缩字高
    （advance 随字高严格线性，一遍缩放即贴合；下限 TABLE_CHAR_H_MIN_MM），
    到下限仍超等比压列宽（渲染层按压缩后列宽 shrink+尾截断兜底）。
    """
    pairs = _row_texts(t)
    req = []
    for key, val in pairs:
        w = text_width(key, TABLE_CHAR_H_MM)
        if val:
            w = max(w, text_width(val, TABLE_CHAR_H_MM))
        req.append(w)
    fixed = 2.0 * CELL_PAD_MM * len(req)
    max_len = max(float(gate_mm) - TABLE_EDGE_PAD_MM - TABLE_Y_START_MM, 60.0)
    char_h = TABLE_CHAR_H_MM
    total_req = math.fsum(req)
    if total_req + fixed > max_len:
        char_h = max(TABLE_CHAR_H_MIN_MM,
                     TABLE_CHAR_H_MM * (max_len - fixed) / total_req)
        scale = char_h / TABLE_CHAR_H_MM
        req = [r * scale for r in req]
        logging.warning('PLT 信息表格：门幅 %.0fmm 偏小，14 列自适应表长超限，'
                        '字高 %.1f→%.1fmm', float(gate_mm), TABLE_CHAR_H_MM, char_h)
    widths = [r + 2.0 * CELL_PAD_MM for r in req]
    total = math.fsum(widths)
    if total > max_len:  # 字高到 7mm 下限仍超 → 等比压列 + 单元格内截断
        squeeze = max_len / total
        widths = [w * squeeze for w in widths]
        logging.warning('PLT 信息表格：门幅 %.0fmm 偏小，字高已到 %.1fmm 下限仍'
                        '超限，等比压列宽（长值单元格将尾部截断）',
                        float(gate_mm), TABLE_CHAR_H_MIN_MM)
    return pairs, char_h, widths


def info_table_polylines(t: InfoTable, *, table_x0: float, gate_mm: float) -> list:
    """表格 → 世界 mm 折线 ``[(closed, points)]``。

    版式（见模块 docstring）：外框 [x0, x0+W]×[Y0, Y0+L]（Y0 = 30mm 起始、
    L = Σ列宽自适应，不与幅宽等长）+ 1 条 key|value 行分隔线（沿 y，视图里
    水平）+ 13 条列分隔线（沿 x，视图里竖直）+ 14 列文字（key 行带最靠唛架、
    value 行带在外，均基线沿 +y、字顶朝 −x，基 u=(0,1)/w=(-1,0) 右手系，
    生产视图水平正立；**单元格内居中** = 列方向 (列宽−文宽)/2 起画）。
    **不裁剪**（元数据，裁剪切坏文字）。
    """
    pairs, char_h, widths = _column_layout(t, gate_mm=gate_mm)
    total = math.fsum(widths)
    x1 = table_x0 + TABLE_W_MM
    xm = table_x0 + ROW_BAND_H_MM              # key|value 行带边界
    y_start = TABLE_Y_START_MM                 # 右下顶点垂直向上 3cm

    out: list = []
    # 外框（自适应表长，自 y_start 起向上排）
    out.append((True, [(table_x0, y_start), (x1, y_start),
                       (x1, y_start + total), (table_x0, y_start + total)]))
    # key|value 行分隔线（沿 y 贯穿表长）
    out.append((False, [(xm, y_start), (xm, y_start + total)]))
    # 列分隔线（沿 x 贯穿表宽，列边界 = 起始 + 累计列宽）
    y_edge = y_start
    for w in widths[:-1]:
        y_edge += w
        out.append((False, [(table_x0, y_edge), (x1, y_edge)]))

    # 文字：key 行带中心 x0+9 / value 行带中心 x0+27，基线 = 带心 + char_h/2
    # （字顶朝 −x 延伸）；单元格内**居中**：起画 y = 列左缘 + (列宽−文宽)/2
    # （文宽按 shrink 后 fit 封顶，压列时段不会越出居中盒），fit = 列宽 − 2×pad
    base_x_key = table_x0 + ROW_BAND_H_MM * 0.5 + char_h * 0.5
    base_x_val = table_x0 + ROW_BAND_H_MM * 1.5 + char_h * 0.5
    y0 = y_start
    for (key, val), w in zip(pairs, widths):
        for text, base_x in ((key, base_x_key), (val, base_x_val)):
            if not text:
                continue
            fit = w - 2.0 * CELL_PAD_MM
            eff = min(text_width(text, char_h), fit)
            for closed, poly in text_strokes(
                    text, origin=(base_x, y0 + (w - eff) * 0.5),
                    u=(0.0, 1.0), w=(-1.0, 0.0),
                    char_h_mm=char_h, fit_width_mm=fit,
                    min_char_h_mm=TABLE_CHAR_H_MIN_MM):
                if len(poly) >= 2:
                    out.append((closed, poly))
        y0 += w
    return out
