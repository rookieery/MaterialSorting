// ToleranceInputs —— 旋转公差 tol 内/外两档（与旧 index.html `<div id="tol_ext">` `<div id="tol_int">` 等价）。
//
// max=45 与旧 index.html 一致（v0.3 §3 单片最大旋转公差 = 裤耳 45°）。字段按字符串持有。

export interface ToleranceInputsProps {
  /** 外片旋转公差 °（input.value 字符串）。 */
  tol_ext: string;
  /** 内片旋转公差 °。 */
  tol_int: string;
  /** 外片 tol 输入变化时回调。 */
  onTolExt: (v: string) => void;
  /** 内片 tol 输入变化时回调。 */
  onTolInt: (v: string) => void;
}

export function ToleranceInputs({ tol_ext, tol_int, onTolExt, onTolInt }: ToleranceInputsProps) {
  return (
    <div className="field">
      <div className="field-label">
        旋转公差 (°) <span className="dim">布纹线 ±N</span>
      </div>
      <div className="grid2">
        <label>
          外部 tol_ext
          <input
            id="tol_ext"
            type="number"
            value={tol_ext}
            min={0}
            max={45}
            onChange={(e) => onTolExt(e.target.value)}
          />
        </label>
        <label>
          内部 tol_int
          <input
            id="tol_int"
            type="number"
            value={tol_int}
            min={0}
            max={45}
            onChange={(e) => onTolInt(e.target.value)}
          />
        </label>
      </div>
    </div>
  );
}
