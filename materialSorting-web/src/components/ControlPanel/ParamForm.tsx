// ParamForm —— 幅宽 / 时长输入（与旧 index.html `<div class="field row">` 等价）。
//
// 字段按字符串持有（与 input.value 一致），交由 collectParams / parseGate / parseTime 解析。
// DOM 沿用旧 style.css `.field.row` / `label` / `input[type=number]`（US-008 前 CSS 不动）。
//
// 2026-08-28 版师要求幅宽两位小数口径：step=0.01 支持小数步进（parseGate parseFloat），
// 失焦 normalizeGate 归一化（两位小数 + [50,400] 钳制），默认显示 175.00。

import { normalizeGate } from '../../lib/params';
//
// 2026-08-22 seed UI 隐藏（界面只支持单 seed 模式）：删 base seed 输入行 + seed/onSeed
// props —— FormState.seed 字段保留恒默认 '0'（parseSeed 恒 0，WS StartPayload.seed=0
// 契约不变）；多 seed 对比开关（MultiSeedControls）同批拆除，见 ControlPanel 注释。

export interface ParamFormProps {
  /** 幅宽（cm）输入值字符串。 */
  gate: string;
  /** 时长（秒）输入值字符串。 */
  time: string;
  /** 幅宽输入变化时回调（传入 input.value 字符串）。 */
  onGate: (v: string) => void;
  /** 时长输入变化时回调（传入 input.value 字符串）。 */
  onTime: (v: string) => void;
  /** US-027 求解中冻结幅宽 / 时长编辑（与 StartButton disabled 同套机制）。 */
  disabled?: boolean;
}

export function ParamForm({ gate, time, onGate, onTime, disabled = false }: ParamFormProps) {
  return (
    <>
      <div className="field row">
        <label>幅宽(cm)</label>
        <input
          id="gate"
          type="number"
          value={gate}
          min={50}
          max={400}
          step={0.01}
          disabled={disabled}
          onChange={(e) => onGate(e.target.value)}
          onBlur={(e) => onGate(normalizeGate(e.target.value))}
        />
      </div>
      <div className="field row">
        <label>时长(秒)</label>
        <input
          id="time"
          type="number"
          value={time}
          min={5}
          max={3600}
          disabled={disabled}
          onChange={(e) => onTime(e.target.value)}
        />
      </div>
    </>
  );
}
