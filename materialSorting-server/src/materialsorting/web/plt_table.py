"""PLT 唛架信息表格（2026-08-30 v3：旋转 90° 生产同款版式）。

对齐生产环境 PLT（data/PC-20250508NJIF_noname_28150251.plt 逆向实测，
2026-08-30 用户图1/图2 对拍定稿；v2 横排版被否，根因 = 文字方向与行堆叠
轴向都与生产相反）：

- **位置**：排料图**外围**——表格区从唛架末端 width_mm + TABLE_GAP_MM 起，
  **不在唛架边框内、不占排料区、不计入用料**（切割时布上没有这块，只在 PLT
  图纸上展示；PS 纸长仍覆盖表格区防止被 WT 裁掉）。生产实测内容末端→表格
  起画 ~55mm，这里取 20mm（v2 已定案不动）。
- **版式（v3 核心）**：**文字旋转 90°**——基线沿世界 +y（门幅方向）、字顶朝
  世界 −x（朝向唛架），基 ``u=(0,1), w=(-1,0)``（右手系 det=+1，直接过
  plt_text 防镜像守卫，无需 v2 的 post-flip）。生产排料软件视图里该方向即
  水平可读（其视图 = 切割视图逆时针旋 90°，x 竖直）；**14 行沿 +x 逐行堆叠**
  （生产视图里 = 自下而上一行一字段的竖排条），行间沿线分隔线。
- **行序**：row0 = 方案名称（最靠唛架，生产同款独立大字块，字高
  PLAN_CHAR_H_MM）→ row13 = 备注（最远端），与用户「从最下面往上 1..14」
  编号及生产文件 x 序（大字方案块→标签区）双对拍一致。
- **行距/字高**：生产实测标签字高 ~14-18mm、行距 ~18-25mm、大字方案块
  ~55-60mm 行带；取 12mm/24mm（用户嫌 v1 的 18mm 偏大）+ 方案名称 36mm/55mm。
  行沿 x 堆叠 ⇒ 表格宽度与门幅无关；门幅只约束文字长度方向（可用长 =
  gate − 2×TABLE_TEXT_Y0_MM，超长 shrink 到 7mm 下限后尾部截断）。
- **外框**：单个闭合矩形 [x0, x0+W]×[0, gate]（生产表格笔画贴满整幅门幅）
  + 13 条行间分隔线（沿 y 贯穿，生产/用户截图均可见行分隔细线）。

14 字段（row0→row13）与来源：

=====  ============= ==================================================
行     标签           来源
=====  ============= ==================================================
 0     方案名称       勾选尺码计算（见下；生产 = 独立大字块）
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

from .plt_text import text_strokes


class TablePayloadError(ValueError):
    """/export payload ``table`` 段非法（路由层转 400 结构化错误）。"""


# ===================== 几何常量（v3 旋转 90° 生产同款版式）=====================
TABLE_GAP_MM = 20.0        # 唛架末端 width_mm → 表格区左缘（世界 +x）
TABLE_PAD_X_MM = 10.0      # 外框 → row0 文字带
PLAN_CHAR_H_MM = 36.0      # row0 方案名称字高（生产大字块 ~55-60mm 行带）
PLAN_ROW_PITCH_MM = 55.0   # row0 行带宽度（沿 x）
TABLE_CHAR_H_MM = 12.0     # row1-13 字高（生产标签 ~14-18mm，用户嫌 18 偏大）
TABLE_ROW_PITCH_MM = 24.0  # row1-13 行距（沿 x；生产 ~18-25mm）
TABLE_CHAR_H_MIN_MM = 7.0  # shrink 下限（文字长度方向超门幅可用长时缩字高）
TABLE_TEXT_Y0_MM = 40.0    # 每行文字起画离 y=0 布边（生产 ~20-40mm）
TABLE_TAIL_X_MM = 10.0     # 末行带 → 外框右缘
N_TABLE_ROWS = 14
# 表格区总宽（沿 x）= pad + 方案行带 + 13×行距 + tail（纸上元数据，不计入用料）
TABLE_W_MM = (TABLE_PAD_X_MM + PLAN_ROW_PITCH_MM
              + (N_TABLE_ROWS - 1) * TABLE_ROW_PITCH_MM + TABLE_TAIL_X_MM)  # = 387

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
    """唛架信息表格内容（手输 6 + 自动 8，渲染口径见 _cell_texts）。"""

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


def _cell_texts(t: InfoTable) -> list:
    """14 行「标签 值」文本（**row0→row13** = 方案名称..备注，沿 +x 逐行；生产
    标签值间是空格分隔，非冒号；空值只渲染标签）。"""
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
    return [f'{lab} {val}' if val else lab for lab, val in rows]


def _row_center_x(table_x0: float, i: int) -> float:
    """第 i 行文字带中心（世界 x）。row0 = 方案名称大字带，其后 13 行等距。"""
    if i == 0:
        return table_x0 + TABLE_PAD_X_MM + PLAN_ROW_PITCH_MM * 0.5
    return (table_x0 + TABLE_PAD_X_MM + PLAN_ROW_PITCH_MM
            + (i - 1) * TABLE_ROW_PITCH_MM + TABLE_ROW_PITCH_MM * 0.5)


def info_table_polylines(t: InfoTable, *, table_x0: float, gate_mm: float) -> list:
    """表格 → 世界 mm 折线 ``[(closed, points)]``。

    版式（生产逆向，见模块 docstring）：外框 [x0, x0+W]×[0,gate] + 13 条沿 y
    行间分隔线 + 14 行文字（基线沿 +y、字顶朝 −x，基 u=(0,1)/w=(-1,0) 右手系）。
    行沿 +x 堆叠 ⇒ 表宽与门幅无关；门幅只限文字长度（可用长 = gate − 2×
    TABLE_TEXT_Y0_MM，超长 shrink 到 7mm 后尾部截断，窄门幅记 warning）。
    **不裁剪**（元数据，裁剪切坏文字）。
    """
    gate_f = float(gate_mm)
    fit_len = max(gate_f - 2.0 * TABLE_TEXT_Y0_MM, 60.0)
    if fit_len < 600.0:
        logging.warning('PLT 信息表格：门幅 %.0fmm 偏小，文字长度方向可用仅 '
                        '%.0fmm（超长行将缩字高/截断）', gate_f, fit_len)

    out: list = []
    # 外框：单个闭合矩形，贴满整幅门幅（生产表格笔画 y∈[0,gate]）
    x1 = table_x0 + TABLE_W_MM
    out.append((True, [(table_x0, 0.0), (x1, 0.0), (x1, gate_f), (table_x0, gate_f)]))

    # 行间分隔线（沿 y 贯穿；生产排料视图里 = 每行之间的水平细线）
    for k in range(N_TABLE_ROWS - 1):
        xs = table_x0 + TABLE_PAD_X_MM + PLAN_ROW_PITCH_MM + k * TABLE_ROW_PITCH_MM
        out.append((False, [(xs, 0.0), (xs, gate_f)]))

    # 行文字：u=(0,1) 沿 +y 书写、w=(-1,0) 字顶朝 −x（朝唛架）——生产排料视图
    # （切割视图逆时针旋 90°）里水平正立可读，与 v2 post-flip 横排版互为镜像定稿
    for i, text in enumerate(_cell_texts(t)):
        if not text:
            continue
        char_h = PLAN_CHAR_H_MM if i == 0 else TABLE_CHAR_H_MM
        cx = _row_center_x(table_x0, i)
        for poly in text_strokes(text, origin=(cx + char_h * 0.5, TABLE_TEXT_Y0_MM),
                                 u=(0.0, 1.0), w=(-1.0, 0.0),
                                 char_h_mm=char_h, fit_width_mm=fit_len,
                                 min_char_h_mm=TABLE_CHAR_H_MIN_MM):
            if len(poly) >= 2:
                out.append((True, poly))
    return out
