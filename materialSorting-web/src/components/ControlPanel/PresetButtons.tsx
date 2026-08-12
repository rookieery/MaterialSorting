// PresetButtons —— 时长一键预设（与旧 index.html `<button id="preset_preview/_exact">` 等价）。
//
// 旧 vanilla 实现：preview → time = 120；exact → time = 600。这里直接 onPreset(120 / 600)。
// DOM 沿用旧 style.css `.field.row.presets` / `button.preset`。

export interface PresetButtonsProps {
  /** 预设时间秒数（120 / 600）。父级应将 time 字段更新为 String(seconds)。 */
  onPreset: (seconds: number) => void;
  /** US-027 求解中冻结预设按钮（与 StartButton disabled 同套机制）。 */
  disabled?: boolean;
}

export function PresetButtons({ onPreset, disabled = false }: PresetButtonsProps) {
  return (
    <div className="field row presets">
      <button type="button" className="preset" disabled={disabled} onClick={() => onPreset(120)}>
        预览 120s
      </button>
      <button type="button" className="preset" disabled={disabled} onClick={() => onPreset(600)}>
        精排 600s
      </button>
    </div>
  );
}
