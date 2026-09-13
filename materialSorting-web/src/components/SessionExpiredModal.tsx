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
// 文案（US-003 会话过期自动恢复起 session_expired 改版）：
//   session_expired → 「会话已过期，刷新页面后将恢复工作状态」—— 停留期不再清
//      sid（旧 sid 留作刷新后启动期恢复的 from_sid），刷新 = 恢复而不是丢数据；
//      按钮仍 location.reload()（刷新动作即恢复入口，用户定案：停留期绝不自动
//      恢复 —— 变相保活会话、浪费资源）。
//   session_limit   → 「当前使用用户过多（最多 6 人同时在线），请稍后尝试」
//      （PRD US-005 原文案不变；保 sid 语义不变）。
//
// 订阅方式：React 18 useSyncExternalStore（lib/api 的模块级 pub/sub；不引 zustand
// —— lib 不依赖 store 层，组件侧零额外状态）。code === null 时渲染 null（零开销）。

import { useSyncExternalStore } from 'react';
import type { JSX } from 'react';
import { getSessionBlock, subscribeSessionBlock, type SessionBlockCode } from '../lib/api';

/** 各阻断码的标题 + 正文（不显示上次活动时间）。 */
const COPY: Record<SessionBlockCode, { title: string; text: string }> = {
  session_expired: {
    title: '会话已过期',
    text: '会话已过期，刷新页面后将恢复工作状态',
  },
  session_limit: {
    title: '当前使用用户过多',
    text: '当前使用用户过多（最多 6 人同时在线），请稍后尝试',
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
