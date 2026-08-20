"""排料可视化工作台 · 导出门面（PNG + R12-DXF marker + PLT 文本三格式）。

2026-08-20 起 export.py 由单文件（658 行）拆为四个 ``export_*`` 模块（纯机械
搬移、行为零变更，PNG/DXF/PLT 产物逐字节一致），本文件保留为门面 re-export
全部原有符号 —— 外部消费方 ``from .export import X`` 路径不变：

- ``export_geometry``：共享几何与配色 —— ``placed_to_world``（placed_items →
  世界坐标 5 层裁片列表）、``apply_transform``、``size_aci``（DXF ACI 公式）、
  5 层配色常量 ``LAYER5_COLOR_*`` / ``NOTCH_LEN_MM``；
- ``export_png``：``render_png``（matplotlib Agg；模块级 ``matplotlib.use('Agg')``
  与 CJK 字体 rcParams 副作用随 import 生效，与拆分前一致）；
- ``export_dxf``：``write_marker_dxf``（R12 + POLYLINE，ET2008 兼容，禁
  LWPOLYLINE；模块级 ezdxf 警告抑制副作用随 import 生效）；
- ``export_plt``：``write_marker_plt``（HPGL/HP-GL 纯文本，LIKE 绘图仪 / WT
  V8.8 安全幅面口径；``_plt_frame_stats`` / 分块常量供单测取用）。

三格式统一消费 ``placed_to_world`` 的**真实母版轮廓**（pieces_intermediate.json
的原始 polygon，非 eroded）放到排料变换位，几何一致、可直接裁剪 / 绘图。格式
细节与现场撞机修正见各自模块 docstring。依赖方向不变：web → nesting_engine /
nesting_bounds（颜色 ``size_color``/``SIZE_ANCHOR``、质心 ``centroid``、可写幅宽
``PLOT_SAFE_MAX_Y_MM`` 单一真相源仍在底层模块，此处仅为旧模块属性保持而 re-export）。
"""
from __future__ import annotations

from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM  # noqa: F401（旧 export 模块属性保持）
from ..nesting_engine.labeling import centroid  # noqa: F401（同上）
from ..nesting_engine.sparrow_baseline import SIZE_ANCHOR, size_color  # noqa: F401（同上）
from .export_dxf import write_marker_dxf
from .export_geometry import (
    LAYER5_COLOR_GRAIN,
    LAYER5_COLOR_INTERNAL,
    LAYER5_COLOR_NET,
    LAYER5_COLOR_NOTCH,
    NOTCH_LEN_MM,
    apply_transform,
    placed_to_world,
    size_aci,
)
from .export_png import render_png
from .export_plt import (
    _PLT_PD_MAX_PTS,
    _plt_frame_stats,
    PLOT_BORDER_MARGIN_Y_MM,
    PLOT_LEAD_X_MM,
    PLOT_TAIL_X_MM,
    write_marker_plt,
)
