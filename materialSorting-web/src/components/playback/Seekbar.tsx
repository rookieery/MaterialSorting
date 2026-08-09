// Seekbar —— 回放时间滑块（US-006 AC#1..#3）。
//
// 与旧 legacy/app.js `#seek` 等价（受控 range input）。
//   - 求解中 / 未启动：disabled，max=0，value=0（与旧 app.js startSolve 重置一致）
//   - 全部 run 完成：max = ceil(maxElapsed)（至少 1，避免 max<min），value 默认到末尾
//   - 用户拖动：onInput → setSeekTime(t)，NestSVG / SeekReadout 切到 frameAtTime(run, t)
//
// 受控输入约定（与 React 18 兼容）：
//   value 由父级 PlaybackBar 算 max，加 useAppStore.seekTime 决定显示值。
//   - seekTime >= 0（用户已拖过 / 全完成时被 setSeekTime(me) 推到末尾）→ value = seekTime
//   - seekTime = -1（live / 未启动）→ value = max（求解结束后默认到末尾）
//
// id="seek" 保留以复用 legacy CSS（#seek { width: 100% }）。

import { useAppStore } from '../../store/appStore';

export interface SeekbarProps {
  /** 最大值（s）。0 = 禁用（求解中 / 无 run）。 */
  max: number;
  /** 是否禁用（求解未全部完成）。 */
  disabled: boolean;
}

export function Seekbar({ max, disabled }: SeekbarProps): React.JSX.Element {
  const seekTime = useAppStore((s) => s.seekTime);
  const setSeekTime = useAppStore((s) => s.setSeekTime);

  // disabled 时 max=0 value=0（与旧 app.js `$('seek').max=0; $('seek').value=0` 一致）。
  // 启用时 effectiveMax 至少 1（避免 max<min，浏览器会 clamp 但语义上 1 更稳）。
  const effectiveMax = disabled ? 0 : Math.max(max, 1);
  const value = disabled ? 0 : seekTime >= 0 ? Math.min(seekTime, effectiveMax) : effectiveMax;

  return (
    <input
      id="seek"
      type="range"
      min={0}
      max={effectiveMax}
      value={value}
      disabled={disabled}
      onInput={(e) => setSeekTime(parseInt((e.target as HTMLInputElement).value, 10))}
    />
  );
}
