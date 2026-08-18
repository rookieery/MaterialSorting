// PieceQuantity / PieceQuantityMap —— 数量状态类型契约（US-011；矩阵化重构 US-001 简化）。
//
// 数量以片型 label（g01+ 裁片码）为 key —— 按 label 跨码匹配同一片型，每码独立持有数量
// （perSize 用 sizeKey 索引：number->String、null->'null'）。
//
// baseValue：该行的「基准值」，仅 UI 特例高亮用（格子值 ≠ baseValue 且整行非全同 → 高亮），
// 不参与序列化 / WS 线格式。来源：hydrate 写 1（默认基准）、setRowAll 写填充值、
// setPiecePerSize 新建 label 时兜底 1（纯逐格手改场景高亮以 1 为基准）。
//
// 与 uploadStore 完全解耦：uploadStore 管 doc/activeSize，本 store 独立管数量。
// commit/排料不消费本 store（仅前端 UI）。

/** 单 label 的数量状态。 */
export interface PieceQuantity {
  /** 码号 -> 数量 映射；key 用 sizeKey（String(size) 或 'null'）。 */
  perSize: Record<string, number>;
  /** 行基准值（UI 特例高亮基准；不参与序列化）。 */
  baseValue: number;
}

/** 全部 label 的数量映射（label = g01+ 裁片码，跨码匹配同一片型）。 */
export type PieceQuantityMap = Record<string /* label */, PieceQuantity>;
