// SizePicker —— 码号多选 chip 复选（US-017 起从 uploadStore.doc 动态读码号）。
//
// US-017 关键变化：
//   - chip 列表来自 `useUploadStore(s=>s.doc)`：doc 非空 → `doc.sizes.map(s=>s.size)`
//     （后端已按 _size_sort_key 排序，前端不二次排序）；doc=null → fallback
//     `constants/sizes.ts:SIZES`（保后端开发模式下排料页可用）。
//   - null 码 chip 文案显示「通用」（与 SizeTabs NULL_SIZE_LABEL 同语义）。
//   - selected 类型扩为 `(number | null)[]`（doc 可能含 null 通用码）。
//
// 总裁片数量（chip 下方实时展示）：总实际裁剪数 = Σ 所选码号每片有效 demand。
//   - demand 来自 qtyStore.quantities（per-size / global 两模式，与 serializeQuantities 同口径）。
//   - 未配置的 (label,size) → demand 1（与「每片每码排 1 份」默认 + 后端空 quantities 回退
//     demand=1 一致；故未 hydrate 也能正确显示 = 裁片数）。
//   - 订阅 quantities：demand 在预览页改过后，回到排料页即正确反映（排料页本身不改 demand）。
//   - doc=null（fallback SIZES，无裁片数据）→ null，UI 显示「—」。
//
// 受控：父级（ControlPanel form.sizes）持有 selected 数组，toggle 时回调 onChange。
// DOM 沿用 style.css `.sizes` / `.chip` / `.chip input` / `.field-label` / `.sizes-total` 类。

import type { JSX } from 'react';
import { SIZES } from '../../constants/sizes';
import { useQtyStore } from '../../store/qtyStore';
import { useUploadStore } from '../../store/uploadStore';
import type { ParsedDoc } from '../../types/parsed';
import type { PieceQuantityMap } from '../../types/qty';

/** null 码（母版中代表「通用/不分码」）的人读文案（与 SizeTabs NULL_SIZE_LABEL 同语义）。 */
const NULL_SIZE_LABEL = '通用';

/** chip 的稳定 key（null → 'null'，number → String(n)）；用于 React key / DOM id。 */
function sizeKey(s: number | null): string {
  return s === null ? 'null' : String(s);
}

/** chip 的人读文案（null →「通用」，number → String(n)）。 */
function sizeLabel(s: number | null): string {
  return s === null ? NULL_SIZE_LABEL : String(s);
}

/**
 * 读取 (label, size) 的有效 demand；未配置 → 1。
 *
 * 与 qtyStore.getPieceDisplay 的区别：后者未配置 → 0（store 作单一真相源，依赖 hydrate 物化
 * 默认 1）；本函数面向「总实际裁剪数」展示，未配置应按默认 1 计（与「每片每码排 1 份」+
 * 后端空 quantities 回退 demand=1 一致），否则未 hydrate 时会把全部裁片算成 0。
 *
 * 口径（per-size / global 两模式与 serializeQuantities 一致）：
 *   - label 未配置        → 1
 *   - per-size + 该码有值 → perSize[sizeKey]
 *   - per-size + 该码缺省 → 1
 *   - global              → globalValue（全码共享，含 source 与非 source）
 */
export function effectiveDemand(
  quantities: PieceQuantityMap,
  label: string,
  size: number | null,
): number {
  const q = quantities[label];
  if (!q) return 1;
  if (q.mode === 'per-size') {
    const v = q.perSize[sizeKey(size)];
    return v === undefined ? 1 : v;
  }
  return q.globalValue;
}

/**
 * 总实际裁剪数 = Σ 所选码号每片有效 demand。doc=null（无裁片数据）→ null。
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
  // 订阅 quantities：demand 变化（预览页编辑）→ 总数实时重算。SizePicker 是排料页叶子组件，
  // 订阅仅重渲染自身（排料页不改 demand，实际触发频率低）。
  const quantities = useQtyStore((s) => s.quantities);
  const chipSizes: (number | null)[] = doc
    ? doc.sizes.map((s) => s.size)
    : [...SIZES];
  const selectedSet = new Set(selected);

  // 总实际裁剪数：所选码号每片 × demand 之和（见 computeTotalCutPieces）。
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
