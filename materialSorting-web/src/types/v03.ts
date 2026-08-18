// v0.3 工艺约束类型。2026-08-17 起重合/旋转改全局上限（后端 constraints.py
// MAX_OVERLAP_MM=10 / MAX_ROTATION_TOL_DEG=45，前端同名常量在 constants/v03.ts），
// 不再按片型钳制。裁片编号化重构 US-004 起 per_type 键 = (g 码 label, 码号 sizeKey)
// 两级嵌套，形如 { g03: { '28': { d: 1.5, tol: 2 } }, ... }，空时序列化为 null。

/**
 * 两档全局参数（WS 契约遗留字段；US-019 起主面板输入已删，collectParams 恒填全 0，
 * 实际每裁片差异走 per_type。内外两档概念已随裁片编号化重构删除，仅保留字段兼容契约）。
 */
export interface SolveParams {
  /** 全局重合（erode）mm 档位 ext。 */
  d_ext: number;
  /** 全局重合（erode）mm 档位 int。 */
  d_int: number;
  /** 全局旋转公差 ° 档位 ext。 */
  tol_ext: number;
  /** 全局旋转公差 ° 档位 int。 */
  tol_int: number;
}

/** 单 (g 码, 码号) 高级覆盖（d/tol 上限 = 全局 10mm / 45°；缺维度 = 继承全局默认 0/0）。 */
export interface PerTypeOverride {
  d?: number;
  tol?: number;
}

/**
 * { label: { sizeKey: { d?, tol? } } }（label = g01+ 裁片码；sizeKey 口径与 qtyStore
 * 一致：number→String(size)，null 码→'null'）。US-004 起两级嵌套——后端 build_instance
 * 按 (piece.label, str(piece.size)) 命中即覆盖。空对象在 StartPayload 序列化为 null。
 */
export type PerTypeOverrides = Record<string, Record<string, PerTypeOverride>>;
