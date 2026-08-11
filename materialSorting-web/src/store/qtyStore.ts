// QtyState —— 裁片数量状态 store（US-011）。
//
// 单一真相源：以片型 label（A/B/C...）为 key，跨码匹配同一片型。每个 label 两种模式：
//   - per-size（默认）：perSize[sizeKey] 独立持有该码数量。
//   - global         ：在某码（globalSource）设为全局后，全码共享 globalValue；
//                      非 source 码 getPieceDisplay 返回 editable=false + reason 含来源码。
//
// 与 uploadStore 完全解耦：本 store 仅管数量，不依赖 React（纯 Zustand），便于纯函数测试。
// US-011 仅前端 UI，不进 commit / 排料。

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

/** sizeLabel：null -> '通用'（人读文案）；否则 String(size)。与 SizeTabs 的 NULL_SIZE_LABEL 同语义。 */
function sizeLabel(size: number | null): string {
  return size === null ? '通用' : String(size);
}

/** getPieceDisplay 返回结构：用于卡片头渲染（数量 + 可编辑性 + 不可编辑原因）。 */
export interface PieceDisplay {
  qty: number;
  editable: boolean;
  reason: string | null;
}

/**
 * getPieceDisplay —— 纯函数 selector：读 map + label + size -> { qty, editable, reason }。
 * 四分支：
 *   1. label 未配置       -> { qty:0, editable:true, reason:null }
 *   2. mode per-size      -> { qty: perSize[sizeKey] ?? 0, editable:true, reason:null }
 *   3. mode global + source -> { qty: globalValue, editable:true, reason:null }
 *   4. mode global + 非 source -> { qty: globalValue, editable:false, reason:'该数值已在「<src>」尺码处使用全局数量' }
 */
export function getPieceDisplay(
  map: PieceQuantityMap,
  label: string,
  size: number | null,
): PieceDisplay {
  const q = map[label];
  if (!q) return { qty: 0, editable: true, reason: null };
  if (q.mode === 'per-size') {
    return { qty: q.perSize[sizeKey(size)] ?? 0, editable: true, reason: null };
  }
  // global 模式
  if (q.globalSource === size) {
    return { qty: q.globalValue, editable: true, reason: null };
  }
  return {
    qty: q.globalValue,
    editable: false,
    reason: '该数值已在「' + sizeLabel(q.globalSource) + '」尺码处使用全局数量',
  };
}

export interface QtyState {
  /** 全部 label 的数量映射；默认 {}（无任何配置）。 */
  quantities: PieceQuantityMap;
  /**
   * per-size 模式下设该 label 在该码数量（value 经 clampQty）。
   * 若当前是 global 模式则先切回 per-size（globalValue 继承到 perSize[globalSource]、
   * 清空 global 字段）再写入。
   */
  setPiecePerSize: (label: string, size: number | null, value: number) => void;
  /**
   * 切 global 模式：mode='global'、globalValue=clampQty(value)、globalSource=sourceSize。
   * perSize 保留（切回 per-size 时仍可用），不主动清。
   */
  setPieceGlobal: (label: string, sourceSize: number | null, value: number) => void;
  /** 清空为 {}（重传 / reset 路径接入）。 */
  resetQuantities: () => void;
  /**
   * 按 (label × size) 列表批量初始化默认数量：每个 label 在其出现的每个码下 perSize=1
   * （per-size 模式）。全量重建 quantities（旧值整体替换）。
   * 供 DXF 解析完成 / 重传时由集成层（PreviewPage）调用 —— 把「每尺码每片默认 1」物化进
   * store（单一真相源；下游 commit / 排料直接读 map，不靠 selector 兜底默认值）。
   * entries 由调用方从 doc.sizes.flatMap(s => s.pieces.map(p => ({label, size: s.size}))) 构造，
   * 故本 store 仍不依赖 parsed 类型，与 uploadStore 完全解耦。
   */
  hydrateDefault: (entries: ReadonlyArray<{ label: string; size: number | null }>) => void;
}

export const useQtyStore = create<QtyState>((set) => ({
  quantities: {},
  setPiecePerSize: (label, size, value) =>
    set((s) => {
      const prev = s.quantities[label];
      const clamped = clampQty(value);
      const sk = sizeKey(size);

      // 从 global 切回 per-size：globalValue 继承到 perSize[globalSource]，清空 global 字段。
      // per-size 模式下 prev.perSize 直接复用。新建 label 走空对象兜底。
      // globalSource 可为 null（用户在「通用」码切 global），sizeKey(null)='null' 兜底正确。
      const perSize: Record<string, number> = prev ? { ...prev.perSize } : {};
      if (prev?.mode === 'global') {
        perSize[sizeKey(prev.globalSource)] = prev.globalValue;
      }
      perSize[sk] = clamped;

      const next: PieceQuantity = {
        mode: 'per-size',
        perSize,
        globalValue: 0,
        globalSource: null,
      };
      return { quantities: { ...s.quantities, [label]: next } };
    }),
  setPieceGlobal: (label, sourceSize, value) =>
    set((s) => {
      const prev = s.quantities[label];
      const perSize = prev ? { ...prev.perSize } : {};
      const next: PieceQuantity = {
        mode: 'global',
        perSize,
        globalValue: clampQty(value),
        globalSource: sourceSize,
      };
      return { quantities: { ...s.quantities, [label]: next } };
    }),
  resetQuantities: () => set({ quantities: {} }),
  hydrateDefault: (entries) =>
    set(() => {
      const map: PieceQuantityMap = {};
      for (const { label, size } of entries) {
        // 同 label 多次出现（跨码 / 同码多片复用 label）累加到同一 perSize；同一 (label,size)
        // 重复写 1 幂等。map 每次 hydrate 全量重建，无旧 state 别名，原地 mutate 安全。
        const q =
          map[label] ?? { mode: 'per-size', perSize: {}, globalValue: 0, globalSource: null };
        q.perSize[sizeKey(size)] = 1;
        map[label] = q;
      }
      return { quantities: map };
    }),
}));
