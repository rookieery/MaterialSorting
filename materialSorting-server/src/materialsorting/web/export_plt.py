"""导出 · PLT/HPGL（LIKE 绘图仪 / WT「高速网口输出 V8.8」纯文本 marker）。

从 web/export.py 拆出（2026-08-20，纯机械搬移、行为零变更）。几何数据 =
export_geometry.placed_to_world 的世界坐标 5 层，与 PNG / R12-DXF 三者几何
口径完全一致（PLT 不带前端 SVG 的 ``scale(1,-1)`` 翻转，与绘图仪走纸 / 幅宽
天然一致；裁剪仅发生在 PLT 绘制口径，不回写中间数据）。
"""
from __future__ import annotations

import logging

# 绘图仪可写幅宽（单一事实源：nesting_bounds 定义，web/solver 求解约束同源引用）
from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
from .export_geometry import NOTCH_LEN_MM


# ===================== PLT/HPGL（LIKE 绘图仪 / WT V8.8）=====================
# US-033：排料 marker → HPGL/HP-GL 文本（纯 ASCII，application/plt）。
# 现场实测：现有 DXF 导出在 WT「高速网口输出中心 V8.8 网络版」+ LIKE 绘图仪上无法正常打印，
# 该软件原生吃 PLT/HPGL（与 ET 排料软件同口径），故新增 PLT 链路。
#
# 1mm = 40 HPGL 绘图单位（plotter unit ≈ 0.025mm）；世界坐标 mm × 40 后 round 取整。
# 笔号语义：SP1=毛版裁切轮廓+门幅框 / SP2=净版 / SP3=内部线 / SP4=刺口 / SP5=布纹线；
# WT V8.8 中可按笔号分配不同物理笔 / 切割刀（物理映射由设备端配置）。
#
# 封装口径对齐生产 PLT（data/PC-20250508NJIF*.plt，ET 排料软件实际产出）：
#   - 头部 IN;PS<纸长>;SP1;PW0.08; 一行 —— PS 声明整幅纸长（无 PS 时 WT 按默认
#     A0/A3 页幅解释，7m+ 长的 marker 会被裁切/分页）；PW 统一 0.08mm 细线宽
#   - 尾部 PU;PG;（PG 出纸结束页）
#   - 行尾 CRLF（生产文件全 CRLF）
#   - 不输出 VS 速度 / LB 文字指令（生产文件均无，LB 字库兼容性交给设备端）
#
# 现场撞机修正（2026-08，对照生产 PLT 逐项核出的设备级差异）：
#   - 安全幅面：机器实际可写幅宽 ~1910mm < 求解门幅 1980mm。旧导出把门幅框画在
#     y=0/1980、顶部刺口伸到 1983.9mm，Y 超程小车撞导轨硬限位（生产 PLT 内容
#     Y ≤ 1912mm、外框上沿 1895mm）。→ 内容按 y ≤ PLOT_SAFE_MAX_Y_MM 半平面裁剪
#     （削平不缩放，绝不变形），门幅框上沿压进可写幅宽，越界裁片记 warning。
#   - PD 分块：旧导出单条 PD 塞整片轮廓（实测最长 2994B / 229 点），国产 HP-GL
#     解释器行缓冲普遍仅百余字节，溢出后坐标流错位 → 小车乱走须急停（生产 PLT
#     单条 ≤11 点 / 行 ≤118B 的刻意分行即为此）。→ ≤10 点/行且 ≤110B 分块续画。
#   - 走纸引导：旧导出 X 贴 0 起画无定位余量（生产 PLT 内容起画 24mm）。
#     → 全体 X + PLOT_LEAD_X_MM；PS 纸长 = 引导 + max(用布长, 内容最大X) + 尾余量。
_PLT_SCALE = 40          # 1mm = 40 HPGL 绘图单位（0.025mm）
_PLT_PEN_WIDTH_MM = 0.08 # PW 笔宽 mm（与生产 PLT 一致的细线宽）
_PEN_OUTLINE = 1         # 毛版裁切轮廓 + 门幅框（DXF layer1）
_PEN_NET = 2             # 净版（DXF layer14）
_PEN_INTERNAL = 3        # 内部线（DXF layer8）
_PEN_NOTCH = 4           # 刺口（DXF layer4）
_PEN_GRAIN = 5           # 布纹线（DXF layer7）

# 安全幅面：PLOT_SAFE_MAX_Y_MM（Y 可写幅宽上限，超出裁剪防撞机）已在顶部从
# nesting_bounds.load_pieces import —— 与求解约束带 NEST_GATE_MM=min(门幅, 该值)
# 单一事实源，换机器/布幅只改 nesting_bounds 一处。求解已钳制到该值内，这里再
# 裁剪属二道防线（兜旧 intermediate / 求解 bug）。
PLOT_LEAD_X_MM = 20.0          # X 走纸起始引导余量（生产 PLT 内容起画 24mm）
PLOT_TAIL_X_MM = 10.0          # PS 纸长在内容之后的尾余量（生产 PS−maxX ≈ 10mm）
PLOT_BORDER_MARGIN_Y_MM = 5.0  # 门幅框 Y 内缩（生产外框下沿 5.1mm；内容 0 起画不内缩）
# ET 生产分块口径：单条 PD ≤11 点 / 行 ≤118B；取更紧的 10 点 / 110B
_PLT_PD_MAX_PTS = 10
_PLT_LINE_MAX_BYTES = 110


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


# ---------- 安全幅面裁剪（y ≤ PLOT_SAFE_MAX_Y_MM 半平面；削平不缩放） ----------
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


def write_marker_plt(world_pieces, *, width_mm: float, gate_mm: float, title: str) -> bytes:
    """写排料 marker PLT/HPGL 文本（ASCII ``bytes``，安全幅面口径见模块注释）。

    生成 HPGL/HP-GL 指令序列（封装口径对齐生产 PLT）：
    ``IN;PS<纸长>;SP1;PW0.08;`` 头部一行 → 按笔分组输出（每笔只声明一次 ``SPn;``）：
    ``SP1`` 门幅框+全部毛版轮廓 → ``SP2..SP5`` 逐层净版/内部线/刺口/布纹线（与
    DXF layer1/14/8/4/7 同映射）→ ``PU;PG;`` 出纸收尾一行。笔号语义见 ``_PEN_*``。
    ``title`` 参数仅为与 ``write_marker_dxf`` 同签名保留，**不输出 LB 文字**（生产
    PLT 无文字指令，字库兼容性交给设备端；PNG/DXF 的逐片 g 码标识同样**不进 PLT**，
    撞机/字库风险优先）。

    安全幅面（防撞机，见模块注释「现场撞机修正」）：
      - 求解侧已把约束带钳到 ``min(门幅, PLOT_SAFE_MAX_Y_MM)``（web/solver
        ``build_instance``，nesting_bounds 单一事实源）；这里再按 ``y ≤ 1910mm``
        半平面**裁剪**（削平不缩放）属二道防线。裁到**轮廓层**（polygon/net/
        internal）说明 marker 不完整（旧 intermediate / 求解 bug），记 warning；
        刺口/布纹线等工艺线外伸几 mm 属正常，直接削平不告警（生产 PLT 同口径）。
      - 门幅框上沿压进可写幅宽（min(gate, 1910−边距)），不贴 y=1980 机械边界。
      - 全体 X + ``PLOT_LEAD_X_MM`` 走纸引导；PS 纸长 = 引导 + max(用布长, 内容
        最大 X) + 尾余量，内容全部落在声明纸幅内且留余量。
      - PD 按生产口径分块（≤10 点/行 ≤110B），防设备行缓冲溢出。

    坐标系：spyrrow 世界坐标 X=用布长度(0..width)、Y=门幅(0..gate) Y 向上（与绘图仪
    走纸 / 幅宽天然一致），**绝不带前端 SVG 的 ``scale(1,-1)`` 翻转**（那只是屏幕显示
    口径）；与 PNG / R12-DXF 三者几何口径完全一致（同 ``placed_to_world`` 输出，
    裁剪仅发生在 PLT 绘制口径，不回写中间数据）。

    与 ``write_marker_dxf`` 对齐：同签名 + 同几何数据源 + 同闭合策略。仅输出格式不同：
    PLT 是纯文本（``'\\r\\n'.join(cmds).encode('ascii')``，CRLF 行尾与生产文件一致，
    **无需临时文件**），DXF 走 ezdxf 写盘读字节。空层跳过（``net_polygon`` 空则不输出
    SP2，依此类推）；裁剪后不足 2 点的层同样跳过。另校验全部坐标在门幅框内（对齐
    gate 的变换链路 bug 检测，正常应为 0；曾因 notch 旋转缺陷产生 600 越界点把
    WT 预览拉变形）。
    """
    # 越界校验（对齐全门幅 gate 的变换链路 bug 检测）+ 内容实际最大 X（刺口沿法线
    # ±half 延伸，边缘片端点可超出轮廓 bbox 几 mm；PS 纸长要覆盖它）
    n_out, max_x = _plt_frame_stats(world_pieces, width_mm=width_mm, gate_mm=gate_mm)
    if n_out:
        logging.warning('PLT 导出：%d 个几何点越出门幅框 %.0f×%.0fmm（检查 notch/'
                        'grain 变换链路）', n_out, width_mm, gate_mm)

    # 按笔分组收集指令行：每笔只声明一次 SP（生产 PLT 全程单笔；逐片逐层切换 SP
    # 在设备端的物理映射未知，578 次切换属无谓风险）。层序与 write_marker_dxf 一致。
    pen_lines = {pen: [] for pen in
                 (_PEN_OUTLINE, _PEN_NET, _PEN_INTERNAL, _PEN_NOTCH, _PEN_GRAIN)}
    clipped_pids: set = set()

    # 门幅/用布边框（并入 SP1，与生产 PLT 同笔）——闭合矩形 4 角；Y 上沿压进可写
    # 幅宽（门幅超出时框住的是可绘区域），下沿内缩，不贴机械边界
    border_y1 = min(gate_mm, PLOT_SAFE_MAX_Y_MM) - PLOT_BORDER_MARGIN_Y_MM
    border = [(0.0, PLOT_BORDER_MARGIN_Y_MM),
              (width_mm, PLOT_BORDER_MARGIN_Y_MM),
              (width_mm, border_y1),
              (0.0, border_y1)]
    pen_lines[_PEN_OUTLINE].extend(_plt_polyline(closed=True, points=border))

    # 逐片 5 层，全部先过 y ≤ 可写幅宽半平面裁剪（outline → net → internal → notch → grain）
    for pc in world_pieces:
        pid = pc.get('pid')

        # SP1 毛版裁切轮廓（闭合）
        poly = pc.get('polygon') or []
        if len(poly) >= 2:
            clipped, n_above = _clip_closed_y(poly, PLOT_SAFE_MAX_Y_MM)
            if n_above:
                clipped_pids.add(pid)
            if len(clipped) >= 2:
                pen_lines[_PEN_OUTLINE].extend(_plt_polyline(closed=True, points=clipped))

        # SP2 净版 net_polygon（闭合）
        net = pc.get('net_polygon') or []
        if len(net) >= 2:
            clipped, n_above = _clip_closed_y(net, PLOT_SAFE_MAX_Y_MM)
            if n_above:
                clipped_pids.add(pid)
            if len(clipped) >= 2:
                pen_lines[_PEN_NET].extend(_plt_polyline(closed=True, points=clipped))

        # SP3 内部线 internal_lines（逐条不闭合，裁剪后可能裂成多段）
        for line in pc.get('internal_lines') or []:
            if len(line) < 2:
                continue
            runs, n_above = _clip_open_y(line, PLOT_SAFE_MAX_Y_MM)
            if n_above:
                clipped_pids.add(pid)
            for run in runs:
                pen_lines[_PEN_INTERNAL].extend(_plt_polyline(closed=False, points=run))

        # SP4 刺口 notches（沿法线 NOTCH_LEN_MM 短线段，与 PNG 同口径）。求解已钳制
        # 在可写幅宽内，刺口 ±half 外伸越线属工艺正常（生产 PLT 内容同样到 1912），
        # 直接削平、不计入 clipped_pids 告警
        half = NOTCH_LEN_MM / 2.0
        for (x, y, nx, ny) in pc.get('notches') or []:
            seg = [(x - nx * half, y - ny * half), (x + nx * half, y + ny * half)]
            runs, _n_above = _clip_open_y(seg, PLOT_SAFE_MAX_Y_MM)
            for run in runs:
                pen_lines[_PEN_NOTCH].extend(_plt_polyline(closed=False, points=run))

        # SP5 布纹线 grain_line（两端点直线；同为工艺线，越线削平不告警）
        gl = pc.get('grain_line')
        if gl and len(gl) == 4:
            runs, _n_above = _clip_open_y([(gl[0], gl[1]), (gl[2], gl[3])],
                                          PLOT_SAFE_MAX_Y_MM)
            for run in runs:
                pen_lines[_PEN_GRAIN].extend(_plt_polyline(closed=False, points=run))

    if clipped_pids:
        sample = ','.join(sorted(map(str, clipped_pids))[:5])
        logging.warning('PLT 导出：%d 个裁片的几何越过绘图仪可写幅宽 %.0fmm，超出部分'
                        '已裁剪不绘制（如 %s…）。求解门幅 %.0fmm 超出可写幅宽，需缩小'
                        '求解门幅重排才能输出完整 marker', len(clipped_pids),
                        PLOT_SAFE_MAX_Y_MM, sample, gate_mm)

    # 头部一行（对齐生产 PLT）：PS 纸长 = 走纸引导 + max(用布长, 内容最大X) + 尾余量
    paper_len = int(round((PLOT_LEAD_X_MM + max(width_mm, max_x) + PLOT_TAIL_X_MM)
                          * _PLT_SCALE))
    cmds: list[str] = [
        f'IN;PS{paper_len};SP{_PEN_OUTLINE};PW{_PLT_PEN_WIDTH_MM};']
    for pen in (_PEN_OUTLINE, _PEN_NET, _PEN_INTERNAL, _PEN_NOTCH, _PEN_GRAIN):
        if pen_lines[pen]:
            cmds.append(f'SP{pen};')
            cmds.extend(pen_lines[pen])
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
