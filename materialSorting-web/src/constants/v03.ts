// v0.3 工艺约束常量。
//
// 2026-08-17 起：重合/旋转不再有「每片型工艺上限表」（旧 V03_TABLE 已删 —— 后端
// constraints.py 同步改为全局上限 MAX_OVERLAP_MM=10 / MAX_ROTATION_TOL_DEG=45，
// 版师工艺参考保留在 .docs/business/排料规则_详细版.md §3.2/§4）。高级配置弹窗
// 输入框统一 max：重合 10mm / 旋转 45°，默认 0（见 PerTypeOverridesModal）。
//
// 裁片编号化重构 US-003 起 V03_PTYPES（固定 10 中文片型名）删除：高级配置列集 =
// 当前母版实际 g 码（GET /api/ptypes representatives 键，动态），不再有程序内
// 中文名清单。

/** 重合输入全局上限（mm；与后端 constraints.MAX_OVERLAP_MM 一致）。 */
export const MAX_OVERLAP_MM = 10;

/** 旋转输入全局上限（度；与后端 constraints.MAX_ROTATION_TOL_DEG 一致）。 */
export const MAX_ROTATION_TOL_DEG = 45;
