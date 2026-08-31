// Toast —— 全局轻提示单例（非阻断；App 生命周期挂载一次）。
//
// 与 SessionExpiredModal（阻断式）的三点差异：
//   1. 不挡交互 —— fixed 右上角栈，无遮罩，pointer-events 仅自身卡片；
//   2. 不自动消失（2026-08-31 修订）—— 数据异常告知不能被错过，唯一出口 =
//      每条 ✕ dismissToast（store 层同文案去重，防重复触发叠条）；
//   3. 无遮罩可并存 —— 与页面操作互不干扰。
//
// 挂载方式：App 顶层单例（与 Tooltip / TourOverlay / SessionExpiredModal 同模式），
// 订阅 toastStore 渲染；空队列渲染 null（零开销）。
//
// z-index 1500 —— 低于 tour(2000) / session-block(3000)（阻断优先级更高的层在上），
// 高于业务 modal(1000-1300)，保证跨页面可见（当前触发源在上传预览页）。

import type { JSX } from 'react';
import { useToastStore } from '../store/toastStore';

export function Toast(): JSX.Element | null {
  const toasts = useToastStore((s) => s.toasts);
  const dismissToast = useToastStore((s) => s.dismissToast);
  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="toast-item">
          <span className="toast-msg">{t.message}</span>
          <button
            type="button"
            className="toast-close"
            aria-label="关闭提示"
            onClick={() => dismissToast(t.id)}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
