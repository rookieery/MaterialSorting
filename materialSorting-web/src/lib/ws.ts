// WS URL 构造（dev / prod 自适配）。
//   dev  —— Vite :5173 经 proxy 转发 → :8000
//   prod —— FastAPI 同源 :8000 直接 serve WS
// 协议随页面：https → wss，否则 ws。host 用 location.host 保持同源（与旧 app.js 一致）。

/** 返回相对 host 的 WS URL：`${proto}://${location.host}/ws/solve`。 */
export function solveWsUrl(): string {
  const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${location.host}/ws/solve`;
}
