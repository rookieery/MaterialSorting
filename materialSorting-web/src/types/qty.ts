// PieceQuantity / PieceQuantityMap —— 数量状态类型契约（US-011）。
//
// 数量以片型 label（A/B/C...）为 key —— 按 label 跨码匹配同一片型，每个 label 有两种模式：
//   - 'per-size'：每码独立（默认）。perSize 用 sizeKey（number->String、null->'null'）索引。
//   - 'global' ：全码共享一个值。在某码（globalSource）设为全局后，其它码同 label 置灰只读。
//
// 与 uploadStore 完全解耦：uploadStore 管 doc/activeSize，本 store 独立管数量。
// commit/排料不消费本 store（US-011 仅前端 UI）。

/** 数量模式：per-size（默认）/ global（全码共享）。 */
export type QtyMode = 'per-size' | 'global';

/** 单 label 的数量状态。 */
export interface PieceQuantity {
  /** 当前模式。新建默认 'per-size'，setPieceGlobal 切 'global'。 */
  mode: QtyMode;
  /** per-size 模式下的码号 -> 数量 映射；key 用 sizeKey（String(size) 或 'null'）。 */
  perSize: Record<string, number>;
  /** global 模式下的全码共享值；per-size 模式下保留旧值或 0（不参与展示）。 */
  globalValue: number;
  /** global 模式下触发全局的来源码号；per-size 模式下为 null。 */
  globalSource: number | null;
}

/** 全部 label 的数量映射（label = A/B/C/...，跨码匹配同一片型）。 */
export type PieceQuantityMap = Record<string /* label */, PieceQuantity>;
