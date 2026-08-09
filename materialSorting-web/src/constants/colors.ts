// 颜色常量（与旧 app.js PHASE_COLORS / SEED_COLORS 一致）。
//
// PHASE_COLORS：单 seed 收敛曲线按 sparrow phase_name() 着色散点（exploring/compressing/final）。
// SEED_COLORS：多 seed 收敛曲线按 run 序号着色路径（最多 6 seed）。
//
// 注：US-005 ConvergenceCurve 会消费这两个常量，US-004 仅落地数据，不动渲染。

/** sparrow phase → 散点颜色。 */
export const PHASE_COLORS = {
  exploring: '#1f77b4',
  compressing: '#ff7f0e',
  final: '#2ca02c',
} as const;

/** 多 seed 时 run 序号 → 路径颜色（最多 6 个）。与旧 app.js SEED_COLORS 字面量一致。 */
export const SEED_COLORS = ['#1f77b4', '#d62728', '#2ca02c', '#ff7f0e', '#9467bd', '#17becf'];
