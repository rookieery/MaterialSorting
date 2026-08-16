"""排料可视化工作台 · 导出（PNG + ASTM/AAMA 风格 R12-DXF marker + HPGL/PLT 文本）。

服务端统一导出，用**真实母版轮廓**（pieces_intermediate.json 的原始 polygon，非 eroded）
放到排料变换位，保证 PNG / DXF / PLT 三格式几何一致、且可直接裁剪 / 绘图。

- PNG：matplotlib（cairosvg 缺失且 Windows 有 native 库坑，故弃用）。配色复用
  sparrow_baseline.PTYPE_COLORS（与工作台屏幕同色）。
- DXF：ezdxf R12 + POLYLINE（复刻 material sorting/nesting_bounds/export.py 已验证套路，
  坚决不用 LWPOLYLINE —— ET2008 轮廓消失坑）。每片按类型 ACI 上色 + 门幅边框 + ASCII 标题。
- PLT：US-033 新增。HPGL/HP-GL 纯文本（``IN;``/``PS;``/``SP;``/``PU;``/``PD;``/``PG;``），
  喂 WT「高速网口输出 V8.8」+ LIKE 绘图仪的原生 PLT 链路（DXF 在该软件实测无法打印）。
  5 层笔号 SP1-SP5（门幅框并入 SP1，按笔分组每笔只声明一次），与 DXF layer1/14/8/4/7
  同语义；纯标准库，无新依赖。现场撞机修正（对照生产 PLT data/PC-20250508NJIF*.plt）：
  内容/门幅框压进 PLOT_SAFE_MAX_Y_MM=1910 可写幅宽（Y 超程小车撞导轨硬限位）、
  PD 按生产口径分块（≤10 点/行 ≤110B，防设备行缓冲溢出坐标错位）、X 加走纸引导、
  PS 纸长含引导 + 尾余量。

US-024：PNG 与 DXF 都含 5 层（毛版 polygon + 净版 net_polygon + 内部线 internal_lines +
刺口 notches + 布纹线 grain_line）。毛版 layer1 是裁切轮廓（DXF ACI 按片型）；其余 4 层
为工艺参考，DXF 各自独立 layer（14/8/4/7），PNG 用与 PiecePreviewSVG 同口径的配色
（net 绿 / internal 橙 / notch 黄 / grain 红）。US-033：PLT 同样含 5 层（SP1-SP5）。

坐标系：spyrrow 世界坐标 X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上
（与前端 SVG `scale(1,-1)` 翻转后一致 → PNG 直接对应屏幕观感；PLT 不带翻转，与绘图仪
走纸 / 幅宽天然一致）。
"""
from __future__ import annotations

import logging
import math
import os
import sys
import tempfile

# ---- matplotlib 无显示环境 ----
import matplotlib
matplotlib.use('Agg')
# CJK 字体（标题/图例有中文；Windows 用 Microsoft YaHei，缺则回退）
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon as MplPolygon, Patch, Rectangle  # noqa: E402

import ezdxf  # noqa: E402

# 抑制 ezdxf R12 $INSUNITS 等已知无害警告
logging.getLogger('ezdxf').setLevel(logging.ERROR)

# 复用排料引擎的类型配色（PNG 与屏幕同色）
from ..nesting_engine.sparrow_baseline import PTYPE_COLORS, DEFAULT_COLOR
# 绘图仪可写幅宽（单一事实源：nesting_bounds 定义，web/solver 求解约束同源引用）
from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM

# DXF ACI 色号（与 nesting_bounds/export.py 一致；10 类全覆盖）
TYPE_ACI = {
    '前片': 1, '后片': 2, '腰': 3, '前袋': 4, '后袋': 5, '机头': 6,
    '单排': 7, '双排': 8, '火机袋': 9, '裤耳': 10,
}
# 图例固定顺序（仅出现过的才画）
TYPE_ORDER = ['前片', '后片', '腰', '前袋', '后袋', '机头', '单排', '双排', '火机袋', '裤耳']

# US-024：5 层配色（与前端 constants/colors.ts LAYER5_COLORS 同口径，确保 PNG/前端视觉一致）
LAYER5_COLOR_NET = '#33cc33'       # layer14 净版绿虚线
LAYER5_COLOR_INTERNAL = '#ff8c1a'  # layer8 内部线橙实线
LAYER5_COLOR_NOTCH = '#ffd700'     # layer4 刺口黄短线段
LAYER5_COLOR_GRAIN = '#e53e3e'     # layer7 布纹线红虚线
# 刺口短线段长度（mm，与前端 PiecePreviewSVG NOTCH_LEN_MM 一致；版师待确认）
NOTCH_LEN_MM = 8.0


# ===================== 几何 =====================
def apply_transform(polygon, rotation_deg: float, translation):
    """二维旋转 + 平移：world = R(θ)·(x,y) + (tx,ty)（与前端 pointsStr 同公式）。"""
    r = math.radians(rotation_deg)
    c, s = math.cos(r), math.sin(r)
    tx, ty = float(translation[0]), float(translation[1])
    return [(x * c - y * s + tx, x * s + y * c + ty) for x, y in polygon]


def _transform_normal(nx: float, ny: float, rotation_deg: float) -> tuple[float, float]:
    """旋转法线向量（无平移）——notch 法线随裁片姿态旋转。"""
    r = math.radians(rotation_deg)
    c, s = math.cos(r), math.sin(r)
    return (c * nx - s * ny, s * nx + c * ny)


def placed_to_world(placed, pieces_by_id):
    """把 placed_items 转成世界坐标裁片列表（含 5 层，US-024）。

    placed: [{id, rotation, translation:[tx,ty]}, ...]
    pieces_by_id: {pid: piece_dict}（piece_dict 含原始 polygon/ptype/size/area_mm2 +
                  US-024 5 层字段 net_polygon/internal_lines/notches/grain_line）
    → [{pid, ptype, size, polygon(world), color, area_mm2,
        net_polygon, internal_lines, notches, grain_line}, ...]

    对 5 层全部按 placement 的 rotation+translation 变换到世界坐标：
      - polygon / net_polygon / internal_lines 顶点 → ``apply_transform``（点变换）
      - notch (x, y, nx, ny)：点变换 (x,y) + 法线旋转变换 (nx,ny)
      - grain_line [x1,y1,x2,y2]：两端点变换
    """
    out = []
    for it in placed:
        pid = it.get('id')
        p = pieces_by_id.get(pid)
        if p is None:
            logging.warning('导出跳过：pid %s 在 PIECES 中找不到', pid)
            continue
        rot = float(it.get('rotation', 0.0))
        tr = it.get('translation', [0, 0])
        world_poly = apply_transform(p['polygon'], rot, tr)

        # US-024 5 层：从 intermediate 透传 + 同步 placement 变换
        net_raw = p.get('net_polygon') or []
        internal_raw = p.get('internal_lines') or []
        notches_raw = p.get('notches') or []
        grain_raw = p.get('grain_line')

        world_net = apply_transform(net_raw, rot, tr) if net_raw else []
        world_internal = [apply_transform(line, rot, tr) for line in internal_raw]
        # notch: (x, y, nx, ny) → 旋转点 + 旋转法线（无平移）
        world_notches = []
        for x, y, nx, ny in notches_raw:
            wx, wy = apply_transform([(x, y)], rot, tr)[0]
            wnx, wny = _transform_normal(nx, ny, rot)
            world_notches.append((wx, wy, wnx, wny))
        world_grain = None
        if grain_raw and len(grain_raw) == 4:
            (gx1, gy1), (gx2, gy2) = apply_transform(
                [(grain_raw[0], grain_raw[1]), (grain_raw[2], grain_raw[3])], rot, tr)
            world_grain = (gx1, gy1, gx2, gy2)

        out.append({
            'pid': pid,
            'ptype': p['ptype'],
            'size': p.get('size'),
            'polygon': world_poly,
            'color': PTYPE_COLORS.get(p['ptype'], DEFAULT_COLOR),   # 与屏幕同色
            'area_mm2': p.get('area_mm2'),
            # US-024：5 层世界坐标数据（PNG + DXF 共用）
            'net_polygon': world_net,
            'internal_lines': world_internal,
            'notches': world_notches,
            'grain_line': world_grain,
        })
    return out


# ===================== PNG（matplotlib）=====================
def render_png(world_pieces, *, width_mm: float, gate_mm: float, title: str) -> bytes:
    """渲染排料 PNG：门幅矩形 + 每片 5 层（毛版类型配色 + 工艺线）+ 标题 + 类型图例。

    US-024：每片在毛版多边形之上叠加 net_polygon(绿虚线) + internal_lines(橙) +
    notches(黄短线段) + grain_line(红虚线)，与前端 NestSVG 视觉一致。
    """
    long_mm = max(width_mm, gate_mm, 1.0)
    long_in = 14.0
    fig_w = long_in * width_mm / long_mm
    fig_h = long_in * gate_mm / long_mm

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor('#eef0f3')

    # 门幅/用布边框（裁床轮廓）
    ax.add_patch(Rectangle((0, 0), width_mm, gate_mm,
                           facecolor='#ffffff', edgecolor='#8a8a8a',
                           linewidth=1.0, linestyle='--', zorder=0))
    # 每片：5 层（zorder 1=毛版实心 → 2=净版/内部/刺口/布纹 叠加）
    for pc in world_pieces:
        # 毛版（layer1）
        ax.add_patch(MplPolygon(pc['polygon'], closed=True,
                                facecolor=pc['color'], edgecolor=pc['color'],
                                alpha=0.55, linewidth=0.8, zorder=1))
        # 净版（layer14）—— 绿虚线，无填充
        if pc.get('net_polygon') and len(pc['net_polygon']) >= 2:
            ax.add_patch(MplPolygon(pc['net_polygon'], closed=True,
                                    fill=False, edgecolor=LAYER5_COLOR_NET,
                                    linewidth=0.7, linestyle='--', zorder=2))
        # 内部线（layer8）—— 橙实线
        for line in pc.get('internal_lines') or []:
            if len(line) < 2:
                continue
            xs = [pt[0] for pt in line]
            ys = [pt[1] for pt in line]
            ax.plot(xs, ys, color=LAYER5_COLOR_INTERNAL, linewidth=0.6,
                    solid_capstyle='round', zorder=2)
        # 刺口（layer4）—— 黄短线段，沿法线 NOTCH_LEN_MM
        half = NOTCH_LEN_MM / 2.0
        for (x, y, nx, ny) in pc.get('notches') or []:
            ax.plot([x - nx * half, x + nx * half],
                    [y - ny * half, y + ny * half],
                    color=LAYER5_COLOR_NOTCH, linewidth=1.0, solid_capstyle='round', zorder=2)
        # 布纹线（layer7）—— 红虚线
        gl = pc.get('grain_line')
        if gl and len(gl) == 4:
            ax.plot([gl[0], gl[2]], [gl[1], gl[3]],
                    color=LAYER5_COLOR_GRAIN, linewidth=0.7,
                    linestyle='--', zorder=2)

    ax.set_xlim(0, width_mm)
    ax.set_ylim(0, gate_mm)
    ax.set_aspect('equal', adjustable='box')
    ax.axis('off')
    ax.set_title(title, fontsize=11, pad=10)

    # 类型图例（放外侧右栏，bbox_inches='tight' 会纳入画布，绝不压住裁片）
    present = {pc['ptype'] for pc in world_pieces}
    handles = [Patch(facecolor=PTYPE_COLORS.get(t, DEFAULT_COLOR),
                     edgecolor=PTYPE_COLORS.get(t, DEFAULT_COLOR), label=t)
               for t in TYPE_ORDER if t in present]
    if handles:
        ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(1.01, 1.0),
                  fontsize=8, frameon=False, title='片型')

    import io
    buf = io.BytesIO()
    fig.savefig(buf, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


# ===================== DXF（R12 POLYLINE，ET 兼容）=====================
# US-024 多 layer 名（与 collect.LAYER_MAPPING / export_dxf.write_piece_dxf 一致；R12 layer 名是字符串）
_DXF_LAYER_OUTLINE = '1'   # 毛版外轮廓（裁切层）
_DXF_LAYER_NET = '14'      # 净版
_DXF_LAYER_INTERNAL = '8'  # 内部线
_DXF_LAYER_NOTCH = '4'     # 刺口（POINT）
_DXF_LAYER_GRAIN = '7'     # 布纹线


def write_marker_dxf(world_pieces, *, width_mm: float, gate_mm: float, title: str) -> bytes:
    """写排料 marker DXF：R12，门幅边框 + 每片 5 层 POLYLINE/POINT（按 layer 分）+ ASCII 标题。

    US-024：每片除 layer1 毛版（闭合 POLYLINE，ACI 按片型）外，附加：
      - layer14 净版（闭合 POLYLINE，color=3 绿）
      - layer8 内部线（多条 POLYLINE，color=6 橙，不闭合）
      - layer4 刺口（POINT，color=2 黄）
      - layer7 布纹线（LINE，color=7 红）
    ET2008 兼容：layer1 是唯一裁切轮廓；附加 layer 仅工艺参考，裁床切 layer1。
    """
    doc = ezdxf.new('R12')
    doc.header['$MEASUREMENT'] = 1   # metric（mm 隐式，R12 不写 $INSUNITS）
    msp = doc.modelspace()

    # 门幅/用布边框（裁床轮廓）
    msp.add_polyline2d(
        [(0, 0), (width_mm, 0), (width_mm, gate_mm), (0, gate_mm), (0, 0)],
        dxfattribs={'color': 7})

    # 每片：5 层
    for pc in world_pieces:
        ptype = pc['ptype']
        aci = TYPE_ACI.get(ptype, 7)
        # layer1 毛版（闭合 POLYLINE；首尾补点闭合；不用 LWPOLYLINE —— ET2008 轮廓消失）
        pts = [(round(x, 2), round(y, 2)) for x, y in pc['polygon']]
        if len(pts) >= 2 and pts[0] != pts[-1]:
            pts.append(pts[0])
        msp.add_polyline2d(pts, dxfattribs={'color': aci, 'layer': _DXF_LAYER_OUTLINE})

        # US-024 layer14 净版（闭合 POLYLINE）
        net_pts = [(round(x, 2), round(y, 2)) for x, y in (pc.get('net_polygon') or [])]
        if len(net_pts) >= 2:
            if net_pts[0] != net_pts[-1]:
                net_pts.append(net_pts[0])
            msp.add_polyline2d(net_pts, dxfattribs={'color': 3, 'layer': _DXF_LAYER_NET})

        # US-024 layer8 内部线（多条 POLYLINE，不闭合）
        for line in pc.get('internal_lines') or []:
            if len(line) < 2:
                continue
            line_pts = [(round(x, 2), round(y, 2)) for x, y in line]
            msp.add_polyline2d(line_pts, dxfattribs={'color': 6, 'layer': _DXF_LAYER_INTERNAL})

        # US-024 layer4 刺口（POINT 位置；法线不进 DXF，渲染/前端按需重算）
        for (x, y, _nx, _ny) in pc.get('notches') or []:
            msp.add_point((round(x, 2), round(y, 2)),
                          dxfattribs={'color': 2, 'layer': _DXF_LAYER_NOTCH})

        # US-024 layer7 布纹线（LINE 两端点）
        gl = pc.get('grain_line')
        if gl and len(gl) == 4:
            msp.add_line((round(gl[0], 2), round(gl[1], 2)),
                         (round(gl[2], 2), round(gl[3], 2)),
                         dxfattribs={'color': 7, 'layer': _DXF_LAYER_GRAIN})

    # ASCII 标题（避免 GBK/编码坑）
    if title:
        msp.add_text(title, dxfattribs={'height': 40, 'insert': (0, gate_mm + 60)})

    # ezdxf 走文件路径最稳，写临时文件再读字节
    tmp = tempfile.NamedTemporaryFile(suffix='.dxf', delete=False)
    tmp.close()
    try:
        doc.saveas(tmp.name)
        with open(tmp.name, 'rb') as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


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
    PLT 无文字指令，字库兼容性交给设备端）。

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
