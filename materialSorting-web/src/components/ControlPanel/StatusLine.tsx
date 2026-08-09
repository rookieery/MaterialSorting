// StatusLine —— 状态行（与旧 index.html `<div id="status">` 等价）。
//
// 文案由父级（App）持有，反映：就绪 / 连接中 / 求解中进度 / 完成（含 finalDensity）/ 错误 / 校验失败。
// DOM 沿用旧 style.css `.status`（绿色文字，1.4em 最小高度）。

export interface StatusLineProps {
  /** 状态文案（父级组装）。 */
  text: string;
}

export function StatusLine({ text }: StatusLineProps) {
  return (
    <div className="status" id="status">
      {text}
    </div>
  );
}
