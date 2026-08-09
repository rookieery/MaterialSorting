// ErodeInputs —— 重合 erode 内/外两档（与旧 index.html `<div id="d_ext">` `<div id="d_int">` 等价）。
//
// 字段按字符串持有，collectParams 做解析。step 0.5 与旧 index.html 一致；min=0 防负值。
// DOM 沿用旧 style.css `.grid2` / `label` / `input[type=number]`。

export interface ErodeInputsProps {
  /** 外片 erode mm（input.value 字符串）。 */
  d_ext: string;
  /** 内片 erode mm。 */
  d_int: string;
  /** 外片 erode 输入变化时回调。 */
  onDExt: (v: string) => void;
  /** 内片 erode 输入变化时回调。 */
  onDInt: (v: string) => void;
}

export function ErodeInputs({ d_ext, d_int, onDExt, onDInt }: ErodeInputsProps) {
  return (
    <div className="field">
      <div className="field-label">
        重合 erode (mm) <span className="dim">内/外两档</span>
      </div>
      <div className="grid2">
        <label>
          外部 d_ext
          <input
            id="d_ext"
            type="number"
            value={d_ext}
            min={0}
            step={0.5}
            onChange={(e) => onDExt(e.target.value)}
          />
        </label>
        <label>
          内部 d_int
          <input
            id="d_int"
            type="number"
            value={d_int}
            min={0}
            step={0.5}
            onChange={(e) => onDInt(e.target.value)}
          />
        </label>
      </div>
    </div>
  );
}
