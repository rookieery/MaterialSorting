// StartButton —— 启动求解按钮（与旧 index.html `<button id="start">` 等价）。
//
// disabled 由父级传（solving 中）。点击触发 onClick（父级负责校验码号 + 调 useSolveRun.start）。
// DOM 沿用旧 style.css `button#start` —— 因此保留 id="start"（US-008 清理时再换 class）。

export interface StartButtonProps {
  /** 求解中（按钮禁用 + 文案变 求解中…）。 */
  solving: boolean;
  /** 点击启动（父级已校验码号非空等前置）。 */
  onClick: () => void;
}

export function StartButton({ solving, onClick }: StartButtonProps) {
  return (
    <button id="start" type="button" disabled={solving} onClick={onClick}>
      {solving ? '求解中…' : '开始求解'}
    </button>
  );
}
