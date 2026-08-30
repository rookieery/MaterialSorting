"""导出 · PLT/HPGL（LIKE 绘图仪 / WT「高速网口输出 V8.8」纯文本 marker）。

从 web/export.py 拆出（2026-08-20，纯机械搬移、行为零变更）。几何数据 =
export_geometry.placed_to_world 的世界坐标 5 层，与 PNG / R12-DXF 三者几何
口径完全一致（PLT 不带前端 SVG 的 ``scale(1,-1)`` 翻转，与绘图仪走纸 / 幅宽
天然一致；裁剪仅发生在 PLT 绘制口径，不回写中间数据）。
"""
from __future__ import annotations

import logging
import math
from collections import Counter

from .export_geometry import NOTCH_LEN_MM
from .plt_table import TABLE_GAP_MM, TABLE_W_MM, InfoTable, info_table_polylines


# ===================== PLT/HPGL（LIKE 绘图仪 / WT V8.8）=====================
# US-033：排料 marker → HPGL/HP-GL 文本（纯 ASCII，application/plt）。
# 现场实测：现有 DXF 导出在 WT「高速网口输出中心 V8.8 网络版」+ LIKE 绘图仪上无法正常打印，
# 该软件原生吃 PLT/HPGL（与 ET 排料软件同口径），故新增 PLT 链路。
#
# 1mm = 40 HPGL 绘图单位（plotter unit ≈ 0.025mm）；世界坐标 mm × 40 后 round 取整。
# 单笔输出（2026-08-24 用户要求统一颜色）：全程仅头部一次 SP1——WT 预览按笔号
# 着色，首版按层分 SP1-SP5 五笔预览呈多色，统一为门幅框的蓝色（=SP1 渲染色）；
# 生产 PLT 实测同样全程仅 SP1 一笔（1 处 SP1 / 0 处 PC），勿回退多笔。
#
# 封装口径对齐生产 PLT（data/PC-20250508NJIF*.plt，ET 排料软件实际产出）：
#   - 头部 IN;PS<纸长>;SP1;PW0.08; 一行 —— PS 声明整幅纸长（无 PS 时 WT 按默认
#     A0/A3 页幅解释，7m+ 长的 marker 会被裁切/分页）；PW 统一 0.08mm 细线宽
#   - 尾部 PU;PG;（PG 出纸结束页）
#   - 行尾 CRLF（生产文件全 CRLF）
#   - 不输出 VS 速度 / LB 文字指令（生产文件均无，LB 字库兼容性交给设备端）
#
# 现场撞机修正（2026-08，对照生产 PLT 逐项核出的设备级差异；幅宽口径 2026-08-28
# 版师定案后收敛为「输入门幅即实际幅宽」，撞机确认系当时那台机器无法处理 1980
# 幅宽所致 —— 求解/导出不再扣 70mm，幅宽受限的设备由用户直接输入更小门幅）：
#   - 门幅框/内容界：按输入 gate_mm 画框（上沿内缩边距）并裁剪（削平不缩放，
#     绝不变形）。历史上界 1910（PLOT_SAFE_MAX_Y_MM）已随 70mm 钳制整体移除。
#   - PD 分块：旧导出单条 PD 塞整片轮廓（实测最长 2994B / 229 点），国产 HP-GL
#     解释器行缓冲普遍仅百余字节，溢出后坐标流错位 → 小车乱走须急停（生产 PLT
#     单条 ≤11 点 / 行 ≤118B 的刻意分行即为此）。→ ≤10 点/行且 ≤110B 分块续画。
#   - 走纸引导：旧导出 X 贴 0 起画无定位余量（生产 PLT 内容起画 24mm）。
#     → 全体 X + PLOT_LEAD_X_MM；PS 纸长 = 引导 + max(用布长, 内容最大X) + 尾余量。
#
# 布纹箭头线 + 尺码×数量标注（2026-08-24，对照生产 PLT 逆向实测）：
#   - 旧导出布纹线是两端点光杆直线，方向不明。→ **单头箭头线**：箭头指向画向
#     u=A→B 的前端 B（= 母版 layer7 LINE 的原始画向，端点顺序经 load_pieces
#     布纹对齐 + placement 变换全程保序，方向真实可得：母版 5336 实测 110 条
#     布纹线每 g 码画向固定，g01~g09 → +X、g10 腰 → -X）。头部为对称双羽
#     （各长 30mm、与杆轴夹角 ~15°，短杆按 45% 杆长收缩）。
#     首版曾复刻生产 PLT 的双端箭羽形态，用户明确要求改单头指原始方向。
#   - 生产 PLT 在杆旁标注「尺码*数量」（如 30*2，字高 ~10mm），且**字体正反随
#     布纹线画向**：标注沿画向 u=A→B 阅读、字顶朝 w=(-uy,ux)（画向左法线；
#     (u,w) 右手系保证字形不镜像）、基线离杆 10mm（字顶离杆 ~20mm）、中心锚
#     在 0.85·L 画向前端。正向（+X）片字顶朝上、标注视觉在杆**上方**；180° 片
#     画向反向 ⇒ 箭头与标注一齐随片倒置、标注翻到杆视觉**下方** —— 片相对
#     标注，生产同款。（首版 w=(uy,-ux) 左手系：所有文字不分画向全部镜像，
#     2026-08-24 用户截图纠正为右手系。）
#   - 生产文件全程**无 LB 文字指令**：文字 = PU/PD 矢量笔画（ET 矢量字库），
#     设备无关。本导出同款：内置数字 0-9 + '*' 单笔矢量小字库（笔画输出），
#     字库外字符（非数字尺码）整段跳过不标注（all-or-nothing，防丢字歧义）。
_PLT_SCALE = 40          # 1mm = 40 HPGL 绘图单位（0.025mm）
_PLT_PEN_WIDTH_MM = 0.08 # PW 笔宽 mm（与生产 PLT 一致的细线宽）
_PLT_PEN = 1             # 全文件唯一笔号（单色导出，见模块注释；生产 PLT 同款仅 SP1）
# 层收集桶（输出层序 = 门幅框+毛版轮廓 → 净版 → 内部线 → 刺口 → 布纹线，与
# write_marker_dxf 层序一致）。2026-08-24 单笔化后仅作分组收集，不再对应输出笔号。
_LAYER_OUTLINE = 'outline'    # 毛版裁切轮廓 + 门幅框（DXF layer1）
_LAYER_NET = 'net'            # 净版（DXF layer14）
_LAYER_INTERNAL = 'internal'  # 内部线（DXF layer8）
_LAYER_NOTCH = 'notch'        # 刺口（DXF layer4）
_LAYER_GRAIN = 'grain'        # 布纹线（DXF layer7）
# 唛架信息表格（2026-08-30，层序最末）：12 字段标签表 = 文件级元数据，与裁片
# 几何分离（不进五层口径）；笔画不过 y≤gate 裁剪（裁剪切坏文字），见 plt_table。
_LAYER_TABLE = 'table'

# 门幅框/裁剪界 = 输入 gate_mm（2026-08-28 版师定案：输入幅宽即实际幅宽）。
# 求解约束带同口径，这里按 gate_mm 裁剪属兜底防线（旧 intermediate / 求解 bug）。
PLOT_LEAD_X_MM = 20.0          # X 走纸起始引导余量（生产 PLT 内容起画 24mm）
PLOT_TAIL_X_MM = 10.0          # PS 纸长在内容之后的尾余量（生产 PS−maxX ≈ 10mm）
PLOT_BORDER_MARGIN_Y_MM = 5.0  # 门幅框 Y 内缩（生产外框下沿 5.1mm；内容 0 起画不内缩）
# ET 生产分块口径：单条 PD ≤11 点 / 行 ≤118B；取更紧的 10 点 / 110B
_PLT_PD_MAX_PTS = 10
_PLT_LINE_MAX_BYTES = 110

# 布纹箭头线 + 尺码×数量标注参数（生产 PLT data/PC-20250508NJIF*.plt 实测，见模块注释）
_GRAIN_BARB_LEN_MM = 30.0          # 箭头羽长（生产实测 30mm）
_GRAIN_BARB_ANGLE_DEG = 15.0       # 箭羽与杆轴夹角（生产实测 ~15°）
_GRAIN_BARB_MAX_SHAFT_FRAC = 0.45  # 短杆保护：箭羽最长压到杆长 45%
_LABEL_CHAR_H_MM = 10.0            # 标注字高（生产数字簇高 ~10mm）
_LABEL_PITCH_MM = 12.0             # 字距 cell（生产 "30*2" ~50mm/4 字 ≈ 1.2×字高）
_LABEL_BASELINE_OFF_MM = 10.0      # 基线离杆距离（沿 w；生产簇心 ~15mm/簇高 ~10）
_LABEL_ANCHOR_FRAC = 0.85          # 标注中心锚在杆上的位置（生产簇心中位数 0.85·L）


def _plt_pt(x: float, y: float) -> str:
    """世界坐标 (mm) → HPGL 整数坐标字符串 ``"x,y"``（×40 round，clamp 非负）。

    X 统一加走纸引导余量 PLOT_LEAD_X_MM（生产 PLT 内容 24mm 起画，贴 0 起画无
    定位余量）；Y 不平移（生产内容同样 ~0 起画）。HPGL 坐标必须是非负整数；
    clamp 防御 placed_to_world 极端边界返回负值（实测 placed 全在门幅内 ≥0，
    但取整后 -0.0 / 极小负值 → 0 兜底）。
    """
    ix = max(0, round((float(x) + PLOT_LEAD_X_MM) * _PLT_SCALE))
    iy = max(0, round(float(y) * _PLT_SCALE))
    return f'{ix},{iy}'


def _plt_polyline(closed: bool, points) -> list[str]:
    """多边形/折线 → 分块指令行列表：``PU`` 首点一行 + ``PD`` 每 ≤10 点且 ≤110B 一行。

    对齐 ET 生产 PLT 分块口径（单条 PD ≤11 点 / 行 ≤118B）：国产 HP-GL 解释器
    行缓冲普遍仅百余字节，超长单条指令会溢出，坐标流错位后小车乱走。PD 后续
    块从当前位置自动续画（HPGL 语义），分块不改变几何。

    points: list[(x, y)] 世界坐标 mm，至少 2 点。
    closed: True → PD 末尾追加首点（物理闭合，与 DXF POLYLINE 闭合策略一致）；
            False → 仅画到末点（线段 / 折线 / 内部线 / 布纹线）。

    返回指令行列表（空层返回 []，调用方 extend 进 cmds）。
    """
    if len(points) < 2:
        return []
    rest = list(points[1:])
    if closed:
        rest.append(points[0])
    lines = [f'PU{_plt_pt(*points[0])};']
    chunk: list[str] = []
    for p in rest:
        s = _plt_pt(*p)
        # 'PD' + payload + ';' 整行 ≤ _PLT_LINE_MAX_BYTES；不足则先 flushed 再续
        if chunk and (len(chunk) >= _PLT_PD_MAX_PTS
                      or len(','.join(chunk + [s])) + 3 > _PLT_LINE_MAX_BYTES):
            lines.append('PD' + ','.join(chunk) + ';')
            chunk = []
        chunk.append(s)
    if chunk:
        lines.append('PD' + ','.join(chunk) + ';')
    return lines


# ---------- 门幅框裁剪（y ≤ gate_mm 半平面；削平不缩放） ----------
def _y_clip_point(a, b, ymax: float):
    """线段 ab 与水平线 y=ymax 的交点（a/b 分居两侧时调用）。"""
    t = (ymax - a[1]) / (b[1] - a[1])
    return (a[0] + (b[0] - a[0]) * t, ymax)


def _clip_closed_y(points, ymax: float):
    """闭合多边形按 y ≤ ymax 半平面裁剪（Sutherland–Hodgman 单边版）。

    返回 ``(裁剪后点列, 越过 ymax 的顶点数)``：全越界 → 空点列（该层不绘制）；
    部分越界 → 越界处在 y=ymax 上削平（交点入列），几何绝不缩放变形。
    """
    out: list[tuple[float, float]] = []
    n_above = sum(1 for _x, y in points if y > ymax)
    if not points:
        return out, 0
    prev = points[-1]
    for cur in points:
        prev_in, cur_in = prev[1] <= ymax, cur[1] <= ymax
        if cur_in:
            if not prev_in:
                out.append(_y_clip_point(prev, cur, ymax))
            out.append(cur)
        elif prev_in:
            out.append(_y_clip_point(prev, cur, ymax))
        prev = cur
    return out, n_above


def _clip_open_y(points, ymax: float):
    """开放折线按 y ≤ ymax 裁剪 → 若干可见段（越界段丢弃，跨界处收到交点截断）。

    返回 ``(段列表, 越过 ymax 的顶点数)``。内部线 / 布纹线 / 刺口等非闭合几何用。
    """
    runs: list[list[tuple[float, float]]] = []
    n_above = sum(1 for _x, y in points if y > ymax)
    cur: list[tuple[float, float]] | None = None
    for a, b in zip(points, points[1:]):
        a_in, b_in = a[1] <= ymax, b[1] <= ymax
        if a_in and b_in:
            if cur is None:
                cur = [a]
            cur.append(b)
        elif a_in:            # 本段出界：画到交点截断，起笔待重置
            if cur is None:
                cur = [a]
            cur.append(_y_clip_point(a, b, ymax))
            runs.append(cur)
            cur = None
        elif b_in:            # 本段入界：从交点重新起笔
            cur = [_y_clip_point(a, b, ymax), b]
        # 双出界：整段丢弃
    if cur:
        runs.append(cur)
    return runs, n_above


# ---------- 布纹箭头线 + 尺码×数量标注（2026-08-24，生产 PLT 逆向） ----------
def _glyph_ellipse(cx: float, cy: float, rx: float, ry: float,
                   n: int = 12) -> list[tuple[float, float]]:
    """单位字库椭圆笔画（'0'/'8'/'9' 用；n 段折线逼近 + 首点重复物理闭合）。"""
    pts = [(cx + rx * math.cos(2.0 * math.pi * i / n),
            cy + ry * math.sin(2.0 * math.pi * i / n)) for i in range(n)]
    return pts + [pts[0]]


# 单笔矢量小字库：数字 0-9 + '*'（生产 PLT 无 LB 文字指令，文字即 PU/PD 笔画）。
# 单位坐标系：字高 y∈[0,1]（基线 0 / 字顶 1）、字身 x∈[0.05,0.65]、字距 cell=1.0
# （映射：x×_LABEL_PITCH_MM、y×_LABEL_CHAR_H_MM）。'.' 等字库外字符由调用方整段跳过。
_LABEL_GLYPHS: dict[str, list[list[tuple[float, float]]]] = {
    '0': [_glyph_ellipse(0.35, 0.50, 0.26, 0.48)],
    '1': [[(0.10, 0.78), (0.30, 1.00), (0.30, 0.00)],
          [(0.08, 0.00), (0.55, 0.00)]],
    '2': [[(0.05, 0.75), (0.15, 0.95), (0.38, 1.00), (0.55, 0.85),
           (0.50, 0.62), (0.25, 0.32), (0.05, 0.00), (0.60, 0.00)]],
    '3': [[(0.06, 0.82), (0.22, 1.00), (0.46, 0.96), (0.56, 0.80),
           (0.44, 0.62), (0.28, 0.56)],
          [(0.28, 0.56), (0.50, 0.50), (0.60, 0.34), (0.54, 0.10),
           (0.32, 0.00), (0.08, 0.10)]],
    '4': [[(0.48, 1.00), (0.05, 0.32), (0.65, 0.32)],
          [(0.48, 1.00), (0.48, 0.00)]],
    '5': [[(0.55, 1.00), (0.12, 1.00), (0.09, 0.55), (0.30, 0.66),
           (0.50, 0.62), (0.60, 0.45), (0.53, 0.15), (0.30, 0.00), (0.08, 0.10)]],
    '6': [[(0.48, 1.00), (0.18, 0.75), (0.07, 0.42), (0.09, 0.18),
           (0.24, 0.02), (0.45, 0.00), (0.60, 0.12), (0.60, 0.32),
           (0.46, 0.46), (0.24, 0.46), (0.10, 0.34)]],
    '7': [[(0.05, 1.00), (0.62, 1.00), (0.32, 0.00)]],
    '8': [_glyph_ellipse(0.35, 0.73, 0.22, 0.27),
          _glyph_ellipse(0.35, 0.27, 0.28, 0.27)],
    '9': [_glyph_ellipse(0.35, 0.72, 0.26, 0.27),
          [(0.60, 0.74), (0.62, 0.35), (0.52, 0.05), (0.28, 0.00)]],
    '*': [[(0.35, 0.17), (0.35, 0.73)],
          [(0.13, 0.30), (0.57, 0.60)],
          [(0.13, 0.60), (0.57, 0.30)]],
}


def _grain_label_text(pc, pid_counts: Counter) -> str | None:
    """裁片 → 标注文本 ``"{尺码}*{数量}"``（数量 = 同 pid 在 marker 中的副本数）。

    尺码取 ``pc['size']``（placed_to_world 透传；浮点整值转整）。文本含字库外
    字符（非 0-9/'*'，如非数字尺码 / 小数点）→ 整段返回 None 不标注：少画一个
    字符比不画更危险（"30.5" 缺 '.' 读成 "305"），all-or-nothing 与母版编号
    复用同哲学。
    """
    size = pc.get('size')
    if size is None:
        return None
    if isinstance(size, float) and size.is_integer():
        size = int(size)
    text = f'{size}*{pid_counts[pc.get("pid")]}'
    if any(ch not in _LABEL_GLYPHS for ch in text):
        logging.debug('PLT 布纹标注跳过（矢量字库外字符）：%r', text)
        return None
    return text


def _grain_annotation_strokes(gl, label_text: str | None) -> list[list[tuple[float, float]]]:
    """布纹线 (x1,y1,x2,y2) + 标注文本 → 世界坐标笔画列表（调用方逐笔过 Y 裁剪）。

    生产 PLT 逆向几何（见模块注释「布纹箭头线 + 尺码×数量标注」）：

    - 画向 ``u = A→B 单位向量``（grain_line 两端点随片旋转/平移变换，方向即
      母版原始布纹画向）；``w = (-uy, ux)`` 为字顶方向（画向左法线，(u,w) 右手
      系 —— 左手系会让字形无论画向正反全部镜像）。
    - 箭头线 = 光杆 + **B 端（画向前端）单头对称双羽**（各长 30mm、夹角 15°；
      短杆时羽长按杆长 45% 上限收缩）—— 箭头指向原始布纹线方向。
    - 标注沿 u 阅读、字顶朝 w、**基线离杆 10mm**（字顶离杆 ~20mm）、中心锚
      0.85·L 画向前端（文本宽于杆时退回杆中点）。正向片标注视觉在杆上方；
      180° 片 u 反向 ⇒ 箭头与标注一齐翻向/翻侧倒置（视觉在杆下方）——
      字体正反随布纹线方向，片相对、生产同款。
    """
    ax_, ay_, bx_, by_ = (float(gl[i]) for i in range(4))
    dx, dy = bx_ - ax_, by_ - ay_
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return []
    ux, uy = dx / length, dy / length
    # 字顶方向取画向左法线：(u, w) 必须右手系（det>0），否则字形映射是镜像，
    # 无论画向正反文字全部"反"（首版 w=(uy,-ux) 左手系即此 bug，用户截图纠正）
    wx, wy = -uy, ux

    strokes: list[list[tuple[float, float]]] = [[(ax_, ay_), (bx_, by_)]]
    barb = min(_GRAIN_BARB_LEN_MM, _GRAIN_BARB_MAX_SHAFT_FRAC * length)
    fb = barb * math.cos(math.radians(_GRAIN_BARB_ANGLE_DEG))
    sb = barb * math.sin(math.radians(_GRAIN_BARB_ANGLE_DEG))
    # B 端单头双羽：从杆端向画向反侧收拢（±w 对称），箭头指向 u 方向
    strokes.append([(bx_, by_), (bx_ - fb * ux + sb * wx, by_ - fb * uy + sb * wy)])
    strokes.append([(bx_, by_), (bx_ - fb * ux - sb * wx, by_ - fb * uy - sb * wy)])

    if label_text:
        width = (len(label_text) - 1 + 0.65) * _LABEL_PITCH_MM
        t = 0.5 * length if width > length else _LABEL_ANCHOR_FRAC * length
        cx = ax_ + t * ux + _LABEL_BASELINE_OFF_MM * wx
        cy = ay_ + t * uy + _LABEL_BASELINE_OFF_MM * wy
        x0 = -width / 2.0
        for i, char_strokes in enumerate(_LABEL_GLYPHS[ch] for ch in label_text):
            for pts in char_strokes:
                strokes.append([
                    (cx + (x0 + (i + gx) * _LABEL_PITCH_MM) * ux
                         + gy * _LABEL_CHAR_H_MM * wx,
                     cy + (x0 + (i + gx) * _LABEL_PITCH_MM) * uy
                         + gy * _LABEL_CHAR_H_MM * wy)
                    for gx, gy in pts])
    return strokes


def write_marker_plt(world_pieces, *, width_mm: float, gate_mm: float, title: str,
                     info_table: InfoTable | None = None) -> bytes:
    """写排料 marker PLT/HPGL 文本（ASCII ``bytes``，安全幅面口径见模块注释）。

    ``info_table``（2026-08-30 唛架信息表格，additive 缺省 None 零变化）：
    给定时在唛架末端外围追加 14 字段标签表（plt_table 构建，v3 旋转 90° 生产
    同款：文字沿 +y、行沿 +x 堆叠），门幅边框恒为 width_mm 不延伸、表格不占
    排料区不计入用料，PS 纸长延伸覆盖表格区（防 WT 裁页）。表格笔画追加为独立
    ``_LAYER_TABLE`` 桶（层序最末）、**不过 y≤gate 裁剪**（元数据保护）。

    生成 HPGL/HP-GL 指令序列（封装口径对齐生产 PLT）：
    ``IN;PS<纸长>;SP1;PW0.08;`` 头部一行 → **全程单笔 SP1**（2026-08-24 用户要求
    统一颜色：WT 预览按笔号着色，首版按层分 SP1-SP5 五笔预览呈多色，统一为门幅框
    的蓝色；生产 PLT 实测同样全程仅 SP1）→ 层序仍与 write_marker_dxf 一致（门幅框+
    毛版轮廓 → 净版 → 内部线 → 刺口 → 布纹线，仅收集顺序、无 SP 切换）→
    ``PU;PG;`` 出纸收尾一行。
    ``title`` 参数仅为与 ``write_marker_dxf`` 同签名保留，**不输出 LB 文字指令**；
    布纹线层为**箭头线 + 尺码×数量标注**（2026-08-24 起随生产 PLT 口径，文字以
    PU/PD 矢量笔画输出、正反随布纹线画向，见 ``_grain_annotation_strokes``；PNG/DXF
    的逐片 g 码标识仍**不进 PLT**）。

    门幅框与裁剪界（2026-08-28 版师定案：输入幅宽即实际幅宽，见模块注释）：
      - 求解约束带 = gate_mm（web/solver ``build_instance`` 同口径）；这里按
        ``y ≤ gate_mm`` 半平面**裁剪**（削平不缩放）属兜底防线。裁到**轮廓层**
        （polygon/net/internal）说明 marker 不完整（旧 intermediate / 求解 bug），
        记 warning；刺口/布纹线等工艺线外伸几 mm 属正常，直接削平不告警
        （生产 PLT 同口径）。
      - 门幅框上沿 = gate_mm − 边距内缩，不贴输入门幅边界。
      - 全体 X + ``PLOT_LEAD_X_MM`` 走纸引导；PS 纸长 = 引导 + max(用布长, 内容
        最大 X) + 尾余量，内容全部落在声明纸幅内且留余量。
      - PD 按生产口径分块（≤10 点/行 ≤110B），防设备行缓冲溢出。

    坐标系：spyrrow 世界坐标 X=用布长度(0..width)、Y=门幅(0..gate) Y 向上（与绘图仪
    走纸 / 幅宽天然一致），**绝不带前端 SVG 的 ``scale(1,-1)`` 翻转**（那只是屏幕显示
    口径）；与 PNG / R12-DXF 三者几何口径完全一致（同 ``placed_to_world`` 输出，
    裁剪仅发生在 PLT 绘制口径，不回写中间数据）。

    与 ``write_marker_dxf`` 对齐：同签名 + 同几何数据源 + 同闭合策略。仅输出格式不同：
    PLT 是纯文本（``'\\r\\n'.join(cmds).encode('ascii')``，CRLF 行尾与生产文件一致，
    **无需临时文件**），DXF 走 ezdxf 写盘读字节。空层跳过（``net_polygon`` 空则该层
    不输出笔画）；裁剪后不足 2 点的层同样跳过。另校验全部坐标在门幅框内（对齐
    gate 的变换链路 bug 检测，正常应为 0；曾因 notch 旋转缺陷产生 600 越界点把
    WT 预览拉变形）。
    """
    # 越界校验（对齐全门幅 gate 的变换链路 bug 检测）+ 内容实际最大 X（刺口沿法线
    # ±half 延伸，边缘片端点可超出轮廓 bbox 几 mm；PS 纸长要覆盖它）
    n_out, max_x = _plt_frame_stats(world_pieces, width_mm=width_mm, gate_mm=gate_mm)
    if n_out:
        logging.warning('PLT 导出：%d 个几何点越出门幅框 %.0f×%.0fmm（检查 notch/'
                        'grain 变换链路）', n_out, width_mm, gate_mm)

    # 按层收集指令行（层序与 write_marker_dxf 一致），输出时全部并入单笔 SP1：
    # 2026-08-24 用户要求全文件统一颜色（WT 预览按笔号着多色），生产 PLT 实测
    # 全程仅 SP1 一笔。桶仅作层序分组，不再对应输出笔号。
    layer_lines = {layer: [] for layer in
                   (_LAYER_OUTLINE, _LAYER_NET, _LAYER_INTERNAL, _LAYER_NOTCH,
                    _LAYER_GRAIN, _LAYER_TABLE)}
    clipped_pids: set = set()
    # 标注数量口径：同 pid 副本数（demand>1 时 sparrow 对同 pid 发 N 条
    # placed_items，placed_to_world 即 N 行同 pid —— 计数即需求副本数）
    pid_counts = Counter(pc.get('pid') for pc in world_pieces)

    # 门幅/用布边框（层序之首，与生产 PLT 同为 SP1 单笔）——闭合矩形 4 角；Y 上沿
    # 按输入门幅内缩边距，下沿内缩，不贴门幅边界。恒为 width_mm：信息表格在排料
    # 图外围（2026-08-30 v2：不占排料区、不计入用料，切割时布上无此内容）。
    border_y1 = float(gate_mm) - PLOT_BORDER_MARGIN_Y_MM
    border_x1 = width_mm
    border = [(0.0, PLOT_BORDER_MARGIN_Y_MM),
              (border_x1, PLOT_BORDER_MARGIN_Y_MM),
              (border_x1, border_y1),
              (0.0, border_y1)]
    layer_lines[_LAYER_OUTLINE].extend(_plt_polyline(closed=True, points=border))

    # 逐片 5 层，全部先过 y ≤ 输入门幅半平面裁剪（outline → net → internal → notch → grain）
    gate_f = float(gate_mm)
    for pc in world_pieces:
        pid = pc.get('pid')

        # 毛版裁切轮廓（闭合；层序首层）
        poly = pc.get('polygon') or []
        if len(poly) >= 2:
            clipped, n_above = _clip_closed_y(poly, gate_f)
            if n_above:
                clipped_pids.add(pid)
            if len(clipped) >= 2:
                layer_lines[_LAYER_OUTLINE].extend(_plt_polyline(closed=True, points=clipped))

        # 净版 net_polygon（闭合）
        net = pc.get('net_polygon') or []
        if len(net) >= 2:
            clipped, n_above = _clip_closed_y(net, gate_f)
            if n_above:
                clipped_pids.add(pid)
            if len(clipped) >= 2:
                layer_lines[_LAYER_NET].extend(_plt_polyline(closed=True, points=clipped))

        # 内部线 internal_lines（逐条不闭合，裁剪后可能裂成多段）
        for line in pc.get('internal_lines') or []:
            if len(line) < 2:
                continue
            runs, n_above = _clip_open_y(line, gate_f)
            if n_above:
                clipped_pids.add(pid)
            for run in runs:
                layer_lines[_LAYER_INTERNAL].extend(_plt_polyline(closed=False, points=run))

        # 刺口 notches（沿法线 NOTCH_LEN_MM 短线段，与 PNG 同口径）。求解已钳制
        # 在门幅内，刺口 ±half 外伸越线属工艺正常（生产 PLT 内容同样越框几 mm），
        # 直接削平、不计入 clipped_pids 告警
        half = NOTCH_LEN_MM / 2.0
        for (x, y, nx, ny) in pc.get('notches') or []:
            seg = [(x - nx * half, y - ny * half), (x + nx * half, y + ny * half)]
            runs, _n_above = _clip_open_y(seg, gate_f)
            for run in runs:
                layer_lines[_LAYER_NOTCH].extend(_plt_polyline(closed=False, points=run))

        # 布纹线 grain_line：单头箭头线（指向原始画向 B 端）+ 尺码*数量标注
        # （几何规则见 _grain_annotation_strokes）。同为工艺线，越线削平不告警
        gl = pc.get('grain_line')
        if gl and len(gl) == 4:
            for stroke in _grain_annotation_strokes(gl, _grain_label_text(pc, pid_counts)):
                runs, _n_above = _clip_open_y(stroke, gate_f)
                for run in runs:
                    layer_lines[_LAYER_GRAIN].extend(_plt_polyline(closed=False, points=run))

    if clipped_pids:
        sample = ','.join(sorted(map(str, clipped_pids))[:5])
        logging.warning('PLT 导出：%d 个裁片的几何越出输入门幅 %.0fmm，超出部分'
                        '已裁剪不绘制（如 %s…）。求解布局应落在门幅内，请检查'
                        ' intermediate / 求解链路', len(clipped_pids),
                        gate_f, sample)

    # 唛架信息表格（2026-08-30 v3，层序最末）：外框 + 行间分隔线 + 14 行旋转
    # 90° 文本笔画直接进 _LAYER_TABLE 桶 —— **不过 y≤gate 裁剪**（元数据，
    # 裁剪切坏文字；gate 偏小由 info_table_polylines 内 warning 提示），复用
    # _plt_polyline 分块口径。
    if info_table is not None:
        table_x0 = float(width_mm) + TABLE_GAP_MM
        for closed, pts in info_table_polylines(info_table, table_x0=table_x0,
                                                gate_mm=gate_f):
            layer_lines[_LAYER_TABLE].extend(_plt_polyline(closed=closed, points=pts))

    # 头部一行（对齐生产 PLT）：PS 纸长 = 走纸引导 + max(用布长, 内容最大X) + 尾余量；
    # 带信息表格时内容总长 = 用布长 + 表格段（gap+表宽 —— 表格在纸上是元数据、
    # 不计入用料，但 PS 纸长要覆盖它防 WT 裁页）
    content_max = (width_mm + TABLE_GAP_MM + TABLE_W_MM if info_table is not None
                   else width_mm)
    paper_len = int(round((PLOT_LEAD_X_MM + max(content_max, max_x) + PLOT_TAIL_X_MM)
                          * _PLT_SCALE))
    cmds: list[str] = [
        f'IN;PS{paper_len};SP{_PLT_PEN};PW{_PLT_PEN_WIDTH_MM};']
    # 单笔输出：头部已声明 SP1，全部层按层序并入同一笔、无 SP 切换（生产 PLT
    # 全程单笔同构；空层桶自然贡献 0 行）
    for layer in (_LAYER_OUTLINE, _LAYER_NET, _LAYER_INTERNAL, _LAYER_NOTCH,
                  _LAYER_GRAIN, _LAYER_TABLE):
        cmds.extend(layer_lines[layer])
    cmds.append('PU;PG;')   # 抬笔 + 出纸收尾一行（生产 PLT 以 PU;PG; 结束）

    return '\r\n'.join(cmds).encode('ascii')


def _plt_frame_stats(world_pieces, *, width_mm: float, gate_mm: float):
    """越界校验 + 内容实际最大 X（PS 纸长取值用）。

    返回 ``(越界点数, 最大X_mm)``：

    - 越界点数：polygon / net_polygon / internal_lines / grain_line 全层顶点 +
      notch **点**（不含沿法线 ±half 的绘制延伸——边缘片刺口外伸门幅几 mm 是
      工艺正常现象，生产 PLT 同样允许），容差 0.5mm（取整误差）。正常应为 0；
      非 0 说明上游变换链路有缺陷（如 notch 未随片旋转）或求解结果越幅。
    - 最大X：**绘制口径**（含 notch 端点延伸），PS 纸长据此取值（另加走纸引导
      PLOT_LEAD_X_MM / 尾余量 PLOT_TAIL_X_MM）保证内容不裁。
    """
    tol = 0.5
    n = 0
    max_x = 0.0

    def _see(x: float, y: float, *, count: bool) -> bool:
        nonlocal max_x
        if x > max_x:
            max_x = x
        return count and (x < -tol or y < -tol or x > width_mm + tol or y > gate_mm + tol)

    half = NOTCH_LEN_MM / 2.0
    for pc in world_pieces:
        for poly in [pc.get('polygon') or [], pc.get('net_polygon') or []]:
            n += sum(1 for x, y in poly if _see(x, y, count=True))
        for line in pc.get('internal_lines') or []:
            n += sum(1 for x, y in line if _see(x, y, count=True))
        for x, y, nx, ny in pc.get('notches') or []:
            n += 1 if _see(x, y, count=True) else 0
            _see(x + nx * half, y + ny * half, count=False)   # 绘制端点只计入 max_x
            _see(x - nx * half, y - ny * half, count=False)
        gl = pc.get('grain_line')
        if gl and len(gl) == 4:
            n += sum(1 for i in (0, 2) if _see(gl[i], gl[i + 1], count=True))
    return n, max_x
