// v0.3 工艺约束类型。2026-08-17 起重合/旋转改全局上限（后端 constraints.py
// MAX_OVERLAP_MM=10 / MAX_ROTATION_TOL_DEG=45，前端同名常量在 constants/v03.ts），
// 不再按片型钳制。per_type 形如 { 前片: { d: 1, tol: 1 }, ... }，空时序列化为 null。

/** 两档参数（US-019 起主面板输入已删，collectParams 恒填全 0；保留字段兼容 WS 契约）。 */
export interface SolveParams {
  /** 外片 erode mm。 */
  d_ext: number;
  /** 内片 erode mm（单排/双排/火机袋/裤耳）。 */
  d_int: number;
  /** 外片旋转公差 °。 */
  tol_ext: number;
  /** 内片旋转公差 °。 */
  tol_int: number;
}

/** 每片型高级覆盖（d/tol 上限 = 全局 10mm / 45°；空串 = 继承两档同 0）。 */
export interface PerTypeOverride {
  d?: number;
  tol?: number;
}

/** { ptype: { d?, tol? } }。空对象在 StartPayload 序列化为 null。 */
export type PerTypeOverrides = Record<string, PerTypeOverride>;
