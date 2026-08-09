// ParamForm —— 时长 / base seed 输入（与旧 index.html `<div class="field row">` 等价）。
//
// 字段按字符串持有（与 input.value 一致），交由 collectParams / parseTime / parseSeed 解析。
// DOM 沿用旧 style.css `.field.row` / `label` / `input[type=number]`（US-008 前 CSS 不动）。

export interface ParamFormProps {
  /** 时长（秒）输入值字符串。 */
  time: string;
  /** base seed 输入值字符串。 */
  seed: string;
  /** 时长输入变化时回调（传入 input.value 字符串）。 */
  onTime: (v: string) => void;
  /** seed 输入变化时回调（传入 input.value 字符串）。 */
  onSeed: (v: string) => void;
}

export function ParamForm({ time, seed, onTime, onSeed }: ParamFormProps) {
  return (
    <>
      <div className="field row">
        <label>时长(秒)</label>
        <input
          id="time"
          type="number"
          value={time}
          min={5}
          max={3600}
          onChange={(e) => onTime(e.target.value)}
        />
      </div>
      <div className="field row">
        <label>seed</label>
        <input
          id="seed"
          type="number"
          value={seed}
          onChange={(e) => onSeed(e.target.value)}
        />
      </div>
    </>
  );
}
