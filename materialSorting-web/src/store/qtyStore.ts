// QtyState —— 裁片数量状态 store（US-011；矩阵化重构 US-001 简化 + setRowAll）。
//
// 单一真相源：以片型 label（A/B/C/...）为 key，跨码匹配同一片型。每码独立持有数量
// （perSize[sizeKey]）；baseValue 是该行的基准值，仅 UI 特例高亮用，不参与序列化。
//
// 与 uploadStore 完全解耦：本 store 仅管数量，不依赖 React（纯 Zustand），便于纯函数测试。
// US-011 仅前端 UI，不进 commit / 排料；WS 线格式由 lib/params.serializeQuantities 扁平化。

import { create } from 'zustand';
import type { PieceQuantity, PieceQuantityMap } from '../types/qty';

/**
 * clampQty —— 把任意输入规整为 [0,99] 整数。
 * 负数 / NaN / 非数字 -> 0；小数 -> 截断；>99 -> 99。
 */
export function clampQty(v: unknown): number {
  return Math.max(0, Math.min(99, Math.trunc(Number(v) || 0)));
}

/** sizeKey：number -> String(size)；null -> 'null'（perSize 的 key 空间）。 */
function sizeKey(size: number | null): string {
  return size === null ? 'null' : String(size);
}

/** getPieceDisplay 返回结构：用于卡片头 / 矩阵格渲染（数量 + 可编辑性）。 */
export interface PieceDisplay {
  qty: number;
  editable: boolean;
}

/**
 * getPieceDisplay —— 纯函数 selector：读 map + label + size -> { qty, editable }。
 * 分支：
 *   1. label 未配置                -> { qty:0, editable:true }
 *   2. 该码无此裁片（hydrate 后     -> { qty:0, editable:false }
 *      perSize 无该 sizeKey）
 *   3. 正常                         -> { qty: perSize[sizeKey] ?? 0, editable:true }
 */
export function getPieceDisplay(
  map: PieceQuantityMap,
  label: string,
  size: number | null,
): PieceDisplay {
  const q = map[label];
  if (!q) return { qty: 0, editable: true };
  const sk = sizeKey(size);
  // hydrate 对 doc 内每个 (label,size) 物化 perSize=1，故 sizeKey 缺席 = 该码无此裁片。
  return { qty: q.perSize[sk] ?? 0, editable: sk in q.perSize };
}

export interface QtyState {
  /** 全部 label 的数量映射；默认 {}（无任何配置）。 */
  quantities: PieceQuantityMap;
  /** 设该 label 在该码数量（value 经 clampQty）。baseValue 不动（格内编辑不改基准）。 */
  setPiecePerSize: (label: string, size: number | null, value: number) => void;
  /**
   * 整行填充：把 sizes 列出的每个码 perSize 写为 clampQty(value)，并把 baseValue 置为该值
   * （矩阵行头「填充默认值」入口）。sizes 外的既有码保留原值。
   */
  setRowAll: (label: string, sizes: ReadonlyArray<number | null>, value: number) => void;
  /** 清空为 {}（重传 / reset 路径接入）。 */
  resetQuantities: () => void;
  /**
   * 按 (label × size) 列表批量初始化默认数量：每个 label 在其出现的每个码下
   * perSize=1、baseValue=1（默认基准）。全量重建 quantities（旧值整体替换）。
   * 供 DXF 解析完成 / 重传时由集成层（PreviewPage）调用 —— 把「每尺码每片默认 1」物化进
   * store（单一真相源；下游 commit / 排料直接读 map，不靠 selector 兜底默认值）。
   * entries 由调用方从 doc.sizes.flatMap(s => s.pieces.map(p => ({label, size: s.size})))
   * 构造，故本 store 仍不依赖 parsed 类型，与 uploadStore 完全解耦。
   */
  hydrate: (entries: ReadonlyArray<{ label: string; size: number | null }>) => void;
}

export const useQtyStore = create<QtyState>((set) => ({
  quantities: {},
  setPiecePerSize: (label, size, value) =>
    set((s) => {
      const prev = s.quantities[label];
      const clamped = clampQty(value);
      const sk = sizeKey(size);
      // 新建 label 走空对象兜底 + baseValue 默认 1（未填充时的特例高亮基准）。
      const next: PieceQuantity = {
        perSize: { ...(prev?.perSize ?? {}), [sk]: clamped },
        baseValue: prev?.baseValue ?? 1,
      };
      return { quantities: { ...s.quantities, [label]: next } };
    }),
  setRowAll: (label, sizes, value) =>
    set((s) => {
      const prev = s.quantities[label];
      const clamped = clampQty(value);
      // 整行写 perSize：sizes 内每码写 clamped；sizes 外既有码保留（非破坏合并）。
      const perSize: Record<string, number> = { ...(prev?.perSize ?? {}) };
      for (const size of sizes) {
        perSize[sizeKey(size)] = clamped;
      }
      const next: PieceQuantity = { perSize, baseValue: clamped };
      return { quantities: { ...s.quantities, [label]: next } };
    }),
  resetQuantities: () => set({ quantities: {} }),
  hydrate: (entries) =>
    set(() => {
      const map: PieceQuantityMap = {};
      for (const { label, size } of entries) {
        // 同 label 多次出现（跨码 / 同码多片复用 label）累加到同一 perSize；同一 (label,size)
        // 重复写 1 幂等。map 每次 hydrate 全量重建，无旧 state 别名，原地 mutate 安全。
        const q = map[label] ?? { perSize: {}, baseValue: 1 };
        q.perSize[sizeKey(size)] = 1;
        map[label] = q;
      }
      return { quantities: map };
    }),
}));
