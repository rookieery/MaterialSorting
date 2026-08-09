// SizePicker —— 码号多选 chip 复选（与旧 index.html `<div id="sizes">` 等价）。
//
// 与旧 vanilla 实现 renderSizePicker 一致：SIZES 全量 chip，默认全选；点击 chip 切换勾选。
// 受控：父级持有 sizes 数组，toggle 时回调。
//
// DOM 沿用旧 style.css `.sizes` / `.chip` / `.chip input` 类（US-008 前 CSS 不动）。

import { SIZES } from '../../constants/sizes';

export interface SizePickerProps {
  /** 已勾选码号（按 SIZES 顺序渲染；toggle 由父级处理）。 */
  selected: number[];
  /** 切换某码号勾选状态时回调。 */
  onChange: (next: number[]) => void;
}

export function SizePicker({ selected, onChange }: SizePickerProps) {
  const selectedSet = new Set(selected);
  return (
    <div className="field">
      <div className="field-label">码号（多选）</div>
      <div className="sizes">
        {SIZES.map((s) => {
          const checked = selectedSet.has(s);
          return (
            <span className="chip" key={s}>
              <input
                id={`sz_${s}`}
                type="checkbox"
                value={s}
                checked={checked}
                onChange={() => {
                  const next = checked
                    ? selected.filter((x) => x !== s)
                    : [...selected, s].sort((a, b) => a - b);
                  onChange(next);
                }}
              />
              <label htmlFor={`sz_${s}`}>{s}</label>
            </span>
          );
        })}
      </div>
    </div>
  );
}
