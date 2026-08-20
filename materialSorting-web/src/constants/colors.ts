// 颜色常量（与旧 vanilla 实现 PHASE_COLORS / SEED_COLORS 一致）。
//
// PHASE_COLORS：单 seed 收敛曲线按 sparrow phase_name() 着色散点（exploring/compressing/final）。
// SEED_COLORS：多 seed 收敛曲线按 run 序号着色路径（最多 6 seed）。
//
// 注：US-005 ConvergenceCurve 会消费这两个常量，US-004 仅落地数据，不动渲染。
//
// US-024 起 LAYER5_COLORS：5 层裁片配色（毛版/净版/内部线/刺口/布纹线），由
// PiecePreviewSVG / NestSVG 共享，保证预览页/排料页/导出 PNG 视觉一致（与后端
// web/export.py LAYER5_COLOR_* 字面量同口径）。排料页毛版用尺码配色（后端
// size_color，尺码 → 16 色循环表，2026-08-20 起同码同色跨片型一致；画布图例见
// SizeLegend.tsx）；其余 4 层用工艺色（与版师认知一致）。

/** sparrow phase → 散点颜色。 */
export const PHASE_COLORS = {
  exploring: '#1f77b4',
  compressing: '#ff7f0e',
  final: '#2ca02c',
} as const;

/** 多 seed 时 run 序号 → 路径颜色（最多 6 个）。与旧 vanilla 实现 SEED_COLORS 字面量一致。 */
export const SEED_COLORS = ['#1f77b4', '#d62728', '#2ca02c', '#ff7f0e', '#9467bd', '#17becf'];

/**
 * US-024 5 层裁片配色（毛版 + 净版 + 内部线 + 刺口 + 布纹线）。
 *
 * 与 PiecePreviewSVG（上传预览页）历史配色 1:1 一致 —— US-024 把字面量抽到本共享常量，
 * NestSVG（排料页）与 web/export.py（PNG/DXF 导出）同步消费。
 * - ROUGH_FILL/STROKE：仅预览页单片用（排料页毛版用尺码颜色，导出 PNG 同）。
 * - NET/INTERNAL/NOTCH/GRAIN：四层工艺色，所有渲染场景共享。
 */
export const LAYER5_COLORS = {
  /** layer1 毛版半透明蓝实心（上传预览页 PiecePreviewSVG 配色；排料页 NestSVG 用尺码颜色）。 */
  ROUGH_FILL: 'rgba(80, 140, 200, 0.22)',
  ROUGH_STROKE: '#3f7fbf',
  /** layer14 净版绿虚线（所有场景同色）。 */
  NET: '#33cc33',
  /** layer8 内部线橙实线（所有场景同色）。 */
  INTERNAL: '#ff8c1a',
  /** layer4 刺口黄短线段（所有场景同色）。 */
  NOTCH: '#ffd700',
  /** layer7 布纹线红虚线（所有场景同色）。 */
  GRAIN: '#e53e3e',
} as const;

/** US-024 刺口短线段长度（mm，与 PiecePreviewSVG NOTCH_LEN_MM 同口径；版师待确认）。 */
export const NOTCH_LEN_MM = 8;
