// ParamForm —— 幅宽输入 + 满核运行开关（与旧 index.html `<div class="field row">` 等价）。
//
// 字段按字符串持有（与 input.value 一致），交由 collectParams / parseGate 解析。
// DOM 沿用旧 style.css `.field.row` / `label` / `input[type=number]`（US-008 前 CSS 不动）。
//
// 2026-08-28 版师要求幅宽两位小数口径：step=0.01 支持小数步进（parseGate parseFloat），
// 失焦 normalizeGate 归一化（两位小数 + [50,400] 钳制），默认显示 175.00。
//
// 2026-10-05 超排交互优化（用户要求）：
//   - 「时长(秒)」输入行移出面板 → 「普通运行」弹窗（NormalRunModal，点开始前确认
//     时长）；form.time 字段保留（弹窗确认时回写），time/onTime props 随行删除；
//   - 「满核运行」开关自高级/极限运行弹窗移入（幅宽下方，通用配置三族运行同享；
//     随母版重置）。开关视觉复用 .strategy-switch 无框滑块 —— 面板行容器换
//     .panel-switch-field（.field.row 的 `label { width: 56px }` 会压坏开关行排版）。

import { normalizeGate } from '../../lib/params';
//
// 2026-08-22 seed UI 隐藏（界面只支持单 seed 模式）：删 base seed 输入行 + seed/onSeed
// props —— FormState.seed 字段保留恒默认 '0'（parseSeed 恒 0，WS StartPayload.seed=0
// 契约不变）；多 seed 对比开关（MultiSeedControls）同批拆除，见 ControlPanel 注释。

export interface ParamFormProps {
  /** 幅宽（cm）输入值字符串。 */
  gate: string;
  /** 满核运行开关（2026-10-05 由高级/极限运行弹窗移入通用配置）。 */
  fullCores: boolean;
  /** 幅宽输入变化时回调（传入 input.value 字符串）。 */
  onGate: (v: string) => void;
  /** 满核开关切换回调。 */
  onFullCores: (v: boolean) => void;
  /** US-027 求解中冻结幅宽编辑 / 满核开关（与 StartButton disabled 同套机制）。 */
  disabled?: boolean;
}

export function ParamForm({ gate, fullCores, onGate, onFullCores, disabled = false }: ParamFormProps) {
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
      {/* 满核运行开关（.strategy-switch 无框滑块结构同款；文案按用户要求去「是否」
          前缀）。checked 回调透传 boolean，禁用态冻结在求解中。 */}
      <div className="panel-switch-field">
        <label className="strategy-switch-row">
          <span className="strategy-switch">
            <input
              type="checkbox"
              checked={fullCores}
              disabled={disabled}
              onChange={(e) => onFullCores(e.target.checked)}
            />
            <span className="strategy-switch-track" />
          </span>
          <span className="strategy-switch-text">满核运行</span>
        </label>
      </div>
    </>
  );
}
