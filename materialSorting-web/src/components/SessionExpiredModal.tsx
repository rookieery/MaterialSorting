// SessionExpiredModal —— 会话阻断式全屏模态（US-005 多会话前端接入）。
//
// 触发源（两路共用 lib/api 的阻断状态）：
//   - HTTP：apiFetch 拦截后端 401/429 结构化错误体 code=session_expired/session_limit；
//   - WS：useSolveRun 对 error 帧 code 键调 triggerSessionBlock。
//
// 阻断语义（与普通 modal 的三点差异）：
//   1. **无关闭路径** —— 不注册 ESC、遮罩点击不关、不渲染 ✕；唯一出口 =
//      「刷新页面」按钮 location.reload()（后端会话已死/满员，旧页面数据不可信，
//      刷新 = 干净新会话 / 稍后再试）；
//   2. **全屏遮挡** —— fixed inset:0 + 不透明遮罩（z-index 3000，高于 tour 2000），
//      弹窗期间一切 UI 不可交互；
//   3. **请求拦截** —— lib/api 弹窗期间 apiFetch 直接抛 SessionBlockedError，
//      后续 HTTP 请求不再发出（本组件只负责展示，拦截逻辑在 lib/api）。
//
// 文案（PRD US-005 指定）：
//   session_expired → 「会话已过期（10 分钟无操作），请刷新页面」（不显示上次活动时间）
//   session_limit   → 「当前使用用户过多（最多 4 人同时在线），请稍后尝试」
//
// 订阅方式：React 18 useSyncExternalStore（lib/api 的模块级 pub/sub；不引 zustand
// —— lib 不依赖 store 层，组件侧零额外状态）。code === null 时渲染 null（零开销）。

import { useSyncExternalStore } from 'react';
import type { JSX } from 'react';
import { getSessionBlock, subscribeSessionBlock, type SessionBlockCode } from '../lib/api';

/** 各阻断码的标题 + 正文（PRD 指定文案，不显示上次活动时间）。 */
const COPY: Record<SessionBlockCode, { title: string; text: string }> = {
  session_expired: {
    title: '会话已过期',
    text: '会话已过期（10 分钟无操作），请刷新页面',
  },
  session_limit: {
    title: '当前使用用户过多',
    text: '当前使用用户过多（最多 4 人同时在线），请稍后尝试',
  },
};

/** 阻断式全屏模态（App 生命周期单例挂载；未阻断时渲染 null）。 */
export function SessionExpiredModal(): JSX.Element | null {
  const code = useSyncExternalStore(subscribeSessionBlock, getSessionBlock);
  if (code === null) return null;
  const copy = COPY[code];
  return (
    <div className="session-block-overlay" role="alertdialog" aria-modal="true" aria-label={copy.title}>
      <div className="session-block-modal">
        <div className="session-block-title">{copy.title}</div>
        <p className="session-block-text">{copy.text}</p>
        <button
          type="button"
          className="session-block-reload"
          onClick={() => window.location.reload()}
        >
          刷新页面
        </button>
      </div>
    </div>
  );
}
