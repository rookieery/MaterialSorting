// Switch —— 受控开关（US-012）。
//
// 用于 PieceQtyDialog 顶部的「仅当前尺码 / 全部尺码」二态切换。
// 受控：父组件持 checked，子组件仅触发 onChange(v)。视觉为暗底滑块 + 绿色 active，
// 与 .size-chip.active / StartButton 同色系（#2ea06c）。不引入 CSS 框架。
//
// a11y：role="switch" + aria-checked={checked}（WAI-ARIA Authoring Practices 1.2），
// 原生 <button> 保证键盘 Tab focus + Enter/Space 触发（与 native checkbox 行为一致 ——
// button 默认 Enter/Space 触发 click）。disabled 时 button 自带 disabled 属性，
// 不响应点击 + 不参与 tab 序列。

import type { JSX } from 'react';

export interface SwitchProps {
  /** 当前是否为 on 状态（受控）。 */
  checked: boolean;
  /** 切换回调；调用方决定是否真的更新 checked。 */
  onChange: (v: boolean) => void;
  /** on 状态下右侧文案（如「全部尺码」）。 */
  labelOn: string;
  /** off 状态下左侧文案（如「仅当前尺码」）。 */
  labelOff: string;
  /** 禁用（不响应点击 + 灰化）；默认 false。 */
  disabled?: boolean;
  /** 测试 hook（data-testid）。 */
  'data-testid'?: string;
}

export function Switch({
  checked,
  onChange,
  labelOn,
  labelOff,
  disabled = false,
  'data-testid': dataTestId,
}: SwitchProps): JSX.Element {
  function handleClick(): void {
    if (disabled) return; // 双重防御：button disabled 已拦，这里兜底
    onChange(!checked);
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={`switch${checked ? ' on' : ''}${disabled ? ' disabled' : ''}`}
      disabled={disabled}
      onClick={handleClick}
      data-testid={dataTestId}
    >
      {/* 滑块轨道：左侧 labelOff / 右侧 labelOn；视觉用 CSS .switch-track 平移滑块 */}
      <span className="switch-track">
        <span className="switch-label-off">{labelOff}</span>
        <span className="switch-label-on">{labelOn}</span>
        <span className="switch-thumb" />
      </span>
    </button>
  );
}
