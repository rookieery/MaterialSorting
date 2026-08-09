// v0.3 工艺约束类型（与 constraints.py MAX_OVERLAP / ROTATION_TOL / INTERNAL_TYPES 对应）。
// per_type 形如 { 前片: { d: 1, tol: 1 }, ... }，空时序列化为 null。

/** 两档参数（外片 / 内片 各一组）。 */
export interface SolveParams {
  /** 外片 erode mm（≤ MAX_OVERLAP[ptype]）。 */
  d_ext: number;
  /** 内片 erode mm（单排/双排/火机袋/裤耳）。 */
  d_int: number;
  /** 外片旋转公差 °（≤ ROTATION_TOL[ptype]）。 */
  tol_ext: number;
  /** 内片旋转公差 °。 */
  tol_int: number;
}

/** 每片型高级覆盖（任一字段缺省 → 回退两档）。 */
export interface PerTypeOverride {
  d?: number;
  tol?: number;
}

/** { ptype: { d?, tol? } }。空对象在 StartPayload 序列化为 null。 */
export type PerTypeOverrides = Record<string, PerTypeOverride>;
