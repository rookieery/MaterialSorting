// v0.3 片型常量。
//
// 2026-08-17 起：重合/旋转不再有「每片型工艺上限表」（旧 V03_TABLE 已删 —— 后端
// constraints.py 同步改为全局上限 MAX_OVERLAP_MM=10 / MAX_ROTATION_TOL_DEG=45，
// 版师工艺参考保留在 .docs/business/排料规则_详细版.md §3.2/§4）。高级配置弹窗
// 输入框统一 max：重合 10mm / 旋转 45°，默认 0（见 PerTypeOverridesModal）。

/** 全部 10 片型名（顺序固定；per_type 覆盖键 / 高级配置弹窗列序与此一致）。 */
export const V03_PTYPES: string[] = [
  '前片',
  '后片',
  '腰',
  '前袋',
  '后袋',
  '机头',
  '单排',
  '双排',
  '火机袋',
  '裤耳',
];

/** 重合输入全局上限（mm；与后端 constraints.MAX_OVERLAP_MM 一致）。 */
export const MAX_OVERLAP_MM = 10;

/** 旋转输入全局上限（度；与后端 constraints.MAX_ROTATION_TOL_DEG 一致）。 */
export const MAX_ROTATION_TOL_DEG = 45;
