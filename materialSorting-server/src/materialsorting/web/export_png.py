"""导出 · PNG（matplotlib Agg 渲染排料 marker）。

从 web/export.py 拆出（2026-08-20，纯机械搬移、行为零变更）。matplotlib
（cairosvg 缺失且 Windows 有 native 库坑，故弃用）；配色复用
sparrow_baseline.size_color（尺码 → 16 色循环表，与工作台屏幕同色；2026-08-20
起由 g 码换键为尺码，同码同色跨片型一致）。几何数据 = export_geometry.
placed_to_world 的世界坐标 5 层（毛版 polygon + 净版 net_polygon + 内部线
internal_lines + 刺口 notches + 布纹线 grain_line），与 DXF / PLT 一致。

US-024：每片在毛版之上叠加 net_polygon(绿虚线) + internal_lines(橙) +
notches(黄短线段) + grain_line(红虚线)，与前端 NestSVG 视觉一致。
"""
from __future__ import annotations

# ---- matplotlib 无显示环境 ----
import matplotlib
matplotlib.use('Agg')
# CJK 字体（标题/图例有中文；Windows 用 Microsoft YaHei，缺则回退）
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon as MplPolygon, Patch, Rectangle  # noqa: E402

from ..nesting_engine.sparrow_baseline import size_color
# 裁片码质心定位（g 码叠印用；labeling 单一真相源的算子）
from ..nesting_engine.labeling import centroid
from .export_geometry import (
    LAYER5_COLOR_NET,
    LAYER5_COLOR_INTERNAL,
    LAYER5_COLOR_NOTCH,
    LAYER5_COLOR_GRAIN,
    NOTCH_LEN_MM,
)


# ===================== PNG（matplotlib）=====================
def render_png(world_pieces, *, width_mm: float, gate_mm: float, title: str) -> bytes:
    """渲染排料 PNG：门幅矩形 + 每片 5 层（毛版尺码配色 + 工艺线）+ g 码标识 + 标题 + 尺码图例。

    US-024：每片在毛版多边形之上叠加 net_polygon(绿虚线) + internal_lines(橙) +
    notches(黄短线段) + grain_line(红虚线)，与前端 NestSVG 视觉一致。
    2026-08-18：每片质心叠印 g01+ 裁片码（深灰小字，zorder=3 在 5 层之上；label
    缺席（旧 intermediate）跳过），打印产物可对照界面找片。
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
        # g 码标识 —— 每片质心深灰小字（5 层之上；多副本同 pid 各自 placement 同码
        # 各印，与界面/图例可对照；label 缺席（旧 intermediate）跳过）
        label = pc.get('label')
        if label:
            cx, cy = centroid(pc['polygon'])
            ax.text(cx, cy, label, fontsize=7, color='#333333',
                    ha='center', va='center', zorder=3)

    ax.set_xlim(0, width_mm)
    ax.set_ylim(0, gate_mm)
    ax.set_aspect('equal', adjustable='box')
    ax.axis('off')
    ax.set_title(title, fontsize=11, pad=10)

    # 尺码图例（放外侧右栏，bbox_inches='tight' 会纳入画布，绝不压住裁片）
    # 2026-08-20：条目 = 本次 placed 的尺码并集，数值序；同码同色跨片型一致
    # （size_color 单一真相源，与求解屏幕 / CLI SVG 一致）。
    present = {pc.get('size') for pc in world_pieces}
    present.discard(None)
    handles = [Patch(facecolor=size_color(t), edgecolor=size_color(t), label=str(t))
               for t in sorted(present)]
    if handles:
        ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(1.01, 1.0),
                  fontsize=8, frameon=False, title='尺码')

    import io
    buf = io.BytesIO()
    fig.savefig(buf, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
