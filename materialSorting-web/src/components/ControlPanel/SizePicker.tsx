// SizePicker —— 码号多选 chip 复选（US-017 起从 uploadStore.doc 动态读码号）。
//
// US-017 关键变化：
//   - chip 列表来自 `useUploadStore(s=>s.doc)`：doc 非空 → `doc.sizes.map(s=>s.size)`
//     （后端已按 _size_sort_key 排序，前端不二次排序）；doc=null → fallback
//     `constants/sizes.ts:SIZES`（保后端开发模式下排料页可用）。
//   - selected 类型扩为 `(number | null)[]`（FormState 契约；doc 可能含 null 通用码）。
//
// null 通用码不渲染 chip（2026-08-31）：null 组 = 块名末尾带不出码号的裁片，大概率
// 母版命名有问题；且下游 WS/export 载荷本就过滤 null（collectStartContext /
// filterSizes，「通用」片从不参与求解），渲染 chip 只会让「总裁片数量」虚高误导。
// 改为解析完成时 toast 提示（useParseDxf），排查入口保留在预览页 QtyMatrix「通用」行。
//
// 总裁片数量（chip 下方实时展示；裁片编号化重构 US-003 起 = Σ 所选码号每片有效数量）：
//   - 数量来自 qtyStore.quantities（perSize，与 serializeQuantities 同口径）；
//     数量即一切 —— 每份对应母版一个轮廓，不合成镜像（配对 ×2 概念已删除）。
//   - 未配置的 (label,size) → 1（与「每片每码排 1 份」默认 + 后端空 quantities 回退
//     demand=1 一致；故未 hydrate 也能正确显示 = 裁片数）。
//   - 订阅 quantities：数量在预览页改过后，回到排料页即正确反映（排料页本身不改数量）。
//   - doc=null（fallback SIZES，无裁片数据）→ null，UI 显示「—」。
//   - selected 残留 null 跳过不计（与 WS/export 过滤 null 同口径；UI 上已无入口，
//     纯防御 —— 外部直接调 computeTotalCutPieces 传 null 时总数不虚高）。
//
// 受控：父级（ControlPanel form.sizes）持有 selected 数组，toggle 时回调 onChange。
// DOM 沿用 style.css `.sizes` / `.chip` / `.chip input` / `.field-label` / `.sizes-total` 类。

import type { JSX } from 'react';
import { SIZES } from '../../constants/sizes';
import { useQtyStore } from '../../store/qtyStore';
import { useUploadStore } from '../../store/uploadStore';
import type { ParsedDoc } from '../../types/parsed';
import type { PieceQuantityMap } from '../../types/qty';

/** perSize 键口径（number → String(n)，null → 'null'；与 qtyStore/serializeQuantities 一致，
 * effectiveDemand 查 perSize 仍需 'null' 键空间）。 */
function sizeKey(s: number | null): string {
  return s === null ? 'null' : String(s);
}

/** chip 的人读文案（number → String(n)；chip 列表已过滤 null）。 */
function sizeLabel(s: number): string {
  return String(s);
}

/**
 * 读取 (label, size) 的有效数量；未配置 → 1。
 *
 * 与 qtyStore.getPieceDisplay 的区别：后者未配置 → 0（store 作单一真相源，依赖 hydrate 物化
 * 默认 1）；本函数面向「总裁片数量」展示，未配置应按默认 1 计（与「每片每码排 1 份」+
 * 后端空 quantities 回退 demand=1 一致），否则未 hydrate 时会把全部裁片算成 0。
 *
 * 口径（perSize 与 serializeQuantities 一致）：
 *   - label 未配置        → 1
 *   - 该码有值            → perSize[sizeKey]
 *   - 该码缺省            → 1
 */
export function effectiveDemand(
  quantities: PieceQuantityMap,
  label: string,
  size: number | null,
): number {
  const q = quantities[label];
  if (!q) return 1;
  const v = q.perSize[sizeKey(size)];
  return v === undefined ? 1 : v;
}

/**
 * 总裁片数量 = Σ 所选码号每片有效数量（US-003 起数量即一切口径；一份 = 母版一个轮廓，
 * 不合成镜像）。doc=null（无裁片数据）→ null。
 *
 * 纯函数（便于单测）：不读 store，入参 doc / selected / quantities 全显式。
 */
export function computeTotalCutPieces(
  doc: ParsedDoc | null,
  selected: ReadonlyArray<number | null>,
  quantities: PieceQuantityMap,
): number | null {
  if (!doc) return null;
  let total = 0;
  for (const sizeVal of selected) {
    // null 通用码不计（与 WS/export 载荷过滤 null 同口径；UI 已无勾选入口，纯防御）。
    if (sizeVal === null) continue;
    const entry = doc.sizes.find((sz) => sz.size === sizeVal);
    if (!entry) continue;
    for (const piece of entry.pieces) {
      total += effectiveDemand(quantities, piece.label, sizeVal);
    }
  }
  return total;
}

export interface SizePickerProps {
  /** 已勾选码号（顺序遵循父级；toggle 由父级处理）。可能含 null（通用码）。 */
  selected: (number | null)[];
  /** 切换某码号勾选状态时回调（顺序保留 chip 列表原顺序，不二次排序）。 */
  onChange: (next: (number | null)[]) => void;
  /** US-027 求解中冻结码号编辑（与 StartButton disabled 同套机制）。 */
  disabled?: boolean;
}

export function SizePicker({ selected, onChange, disabled = false }: SizePickerProps): JSX.Element {
  // US-017：动态从 uploadStore.doc 读码号列表；doc=null 时 fallback 到 SIZES。
  const doc = useUploadStore((s) => s.doc);
  // 订阅 quantities：数量变化（预览页编辑）→ 总数实时重算。SizePicker 是排料页叶子组件，
  // 订阅仅重渲染自身（排料页不改数量，实际触发频率低）。
  const quantities = useQtyStore((s) => s.quantities);
  const chipSizes: number[] = doc
    ? doc.sizes.map((s) => s.size).filter((s): s is number => s !== null)
    : [...SIZES];
  const selectedSet = new Set(selected);

  // 总裁片数量：所选码号每片 × 数量之和（见 computeTotalCutPieces）。
  const totalPieces = computeTotalCutPieces(doc, selected, quantities);

  return (
    <div className="field">
      <div className="field-label">码号（多选）</div>
      <div className="sizes">
        {chipSizes.map((s) => {
          const key = sizeKey(s);
          const checked = selectedSet.has(s);
          const id = `sz_${key}`;
          return (
            <span className="chip" key={key}>
              <input
                id={id}
                type="checkbox"
                value={key}
                checked={checked}
                disabled={disabled}
                onChange={() => {
                  const next = checked
                    ? selected.filter((x) => x !== s)
                    : [...selected, s];
                  onChange(next);
                }}
              />
              <label htmlFor={id}>{sizeLabel(s)}</label>
            </span>
          );
        })}
      </div>
      <div className="sizes-total" aria-live="polite">
        总裁片数量：<strong>{totalPieces === null ? '—' : `${totalPieces} 片`}</strong>
      </div>
    </div>
  );
}
