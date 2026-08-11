// SizePicker —— 码号多选 chip 复选（US-017 起从 uploadStore.doc 动态读码号）。
//
// US-017 关键变化：
//   - chip 列表来自 `useUploadStore(s=>s.doc)`：doc 非空 → `doc.sizes.map(s=>s.size)`
//     （后端已按 _size_sort_key 排序，前端不二次排序）；doc=null → fallback
//     `constants/sizes.ts:SIZES`（保后端开发模式下排料页可用）。
//   - null 码 chip 文案显示「通用」（与 SizeTabs NULL_SIZE_LABEL 同语义）。
//   - selected 类型扩为 `(number | null)[]`（doc 可能含 null 通用码）。
//
// 受控：父级（ControlPanel form.sizes）持有 selected 数组，toggle 时回调 onChange。
// DOM 沿用 style.css `.sizes` / `.chip` / `.chip input` / `.field-label` 类。

import type { JSX } from 'react';
import { SIZES } from '../../constants/sizes';
import { useUploadStore } from '../../store/uploadStore';

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

export interface SizePickerProps {
  /** 已勾选码号（顺序遵循父级；toggle 由父级处理）。可能含 null（通用码）。 */
  selected: (number | null)[];
  /** 切换某码号勾选状态时回调（顺序保留 chip 列表原顺序，不二次排序）。 */
  onChange: (next: (number | null)[]) => void;
}

export function SizePicker({ selected, onChange }: SizePickerProps): JSX.Element {
  // US-017：动态从 uploadStore.doc 读码号列表；doc=null 时 fallback 到 SIZES。
  const doc = useUploadStore((s) => s.doc);
  const chipSizes: (number | null)[] = doc
    ? doc.sizes.map((s) => s.size)
    : [...SIZES];
  const selectedSet = new Set(selected);

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
    </div>
  );
}
