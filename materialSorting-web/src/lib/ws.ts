// WS URL 构造（dev / prod 自适配）。
//   dev  —— Vite :5173 经 proxy 转发 → :8000
//   prod —— FastAPI 同源 :8000 直接 serve WS
// 协议随页面：https → wss，否则 ws。host 用 location.host 保持同源（与旧 vanilla 实现 一致）。
//
// US-005（多会话）：拼 ``?sid=`` query（浏览器 WS 不能自定义 Header，后端
// routes_ws 从 query 读 sid；缺省/空串 → default 会话）。sid 与 HTTP 的
// X-Session-Id 同源（lib/session.getSessionId），HTTP / WS 归属同一会话。

import { getSessionId } from './session';

/** 返回相对 host 的 WS URL：`${proto}://${location.host}/ws/solve?sid=<sid>`。 */
export function solveWsUrl(): string {
  const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${location.host}/ws/solve?sid=${encodeURIComponent(getSessionId())}`;
}
