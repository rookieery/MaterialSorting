// api.ts —— 全站统一 HTTP 出口（US-005 多会话前端接入）。
//
// 职责（三合一，本文件是**唯一**裸 fetch 调用点 —— grep 'fetch(' 应仅命中此处）：
//   1. 注入 ``X-Session-Id`` Header（sid 来自 lib/session.getSessionId，真实用户
//      请求结构性必带 sid，不落 default 会话）；
//   2. 拦截响应 ``code=session_expired / session_limit``（后端 401/429 结构化错误体）
//      → 触发全局阻断弹窗（SessionExpiredModal，刷新页面是唯一出口）；
//   3. 弹窗期间后续请求被拦截**不再发出**（swallow —— 抛 SessionBlockedError，
//      各调用方现有 catch 落自己的 error 态，反正被全屏弹窗遮住）。
//
// 会话先行（mount 竞态修复）：App 挂载时 POST /api/session 探测建会话，但 React
// 子组件 effect 先于父组件跑（NestingPage 的策略轮询 mount 即发 /api/strategy/
// status）——未注册 sid 先于探测到达后端会吃 401「已过期」误弹窗。故 apiFetch
// 统一 ``await ensureSession()``：首次调用触发一次 POST /api/session（模块级
// once-promise，并发共享、失败静默不重试），任何会话作用域请求结构性晚于建会话。
//
// 阻断状态：模块级单例 + 订阅列表（不引 zustand —— lib 不依赖 store 层；组件用
// React 18 useSyncExternalStore 订阅）。幂等：首个 code 定终身（过期后超限等
// 竞态以先到者为准；刷新后页面重载自然清零）。session_expired 触发时顺手丢弃
// 当前 sid —— 后端墓碑（US-001）1h 拒重建过期 sid，刷新带旧 sid 只会 401 死循环；
// 清 sid 后 reload 铸造全新会话，「刷新页面」按钮才是真出口。
//
// WS 侧同口径：lib/ws.solveWsUrl() 拼 ``?sid=``，useSolveRun 对 error 帧
// ``code`` 键调 triggerSessionBlock —— HTTP / WS 两个入口共用本状态。

import { clearPersistedSessionId, getSessionId } from './session';

/** 会话 Header 名（与后端各路由 ``request.headers.get('x-session-id')`` 对应）。 */
export const SESSION_HEADER = 'X-Session-Id';

/** 阻断码（后端 sessions.SessionExpiredError / SessionLimitError 的 code 键）。 */
export type SessionBlockCode = 'session_expired' | 'session_limit';

/** 弹窗期间请求被拦截时抛出的错误（调用方 catch 落 error 态；message 中文可直显）。 */
export class SessionBlockedError extends Error {
  readonly code: SessionBlockCode;

  constructor(code: SessionBlockCode) {
    super('会话已阻断，请刷新页面后重试');
    this.name = 'SessionBlockedError';
    this.code = code;
  }
}

// ---------------------------------------------------------------- 阻断状态（pub/sub）

let blocked: SessionBlockCode | null = null;
const listeners = new Set<() => void>();

/** 当前阻断码（null = 未阻断）。useSyncExternalStore 的 getSnapshot。 */
export function getSessionBlock(): SessionBlockCode | null {
  return blocked;
}

/** 订阅阻断状态变化（触发一次即终态 —— 无解除路径，刷新页面重置）。返回退订函数。 */
export function subscribeSessionBlock(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/**
 * 触发全局阻断弹窗（HTTP 401/429 code 响应与 WS error 帧 code 共用入口）。
 * 幂等：已阻断时静默忽略（首个 code 定终身）。
 *
 * session_expired 同时丢弃当前 sid（后端墓碑 1h 拒重建旧 sid —— 刷新后必须换新
 * sid 才能真正「重来」，否则探测 401 死循环）；session_limit 保留 sid（会话本身
 * 仍有效，稍后重试可原会话续用）。
 */
export function triggerSessionBlock(code: SessionBlockCode): void {
  if (blocked) return;
  if (code === 'session_expired') clearPersistedSessionId();
  blocked = code;
  for (const fn of listeners) fn();
}

// ---------------------------------------------------------------- Header 合并

/**
 * 把调用方 headers（支持 Headers 实例 / 数组 / 普通对象）合并为带 X-Session-Id 的
 * **普通对象**（不用 Headers 实例 —— 保持调用方/测试可按 Record 属性直取的旧口径；
 * fetch 两者都接受）。已有同名键覆写为当前 sid。
 */
export function mergeSessionHeaders(headers?: HeadersInit): Record<string, string> {
  const out: Record<string, string> = {};
  if (headers) {
    if (typeof Headers !== 'undefined' && headers instanceof Headers) {
      headers.forEach((v, k) => {
        out[k] = v;
      });
    } else if (Array.isArray(headers)) {
      for (const [k, v] of headers) out[k] = v;
    } else {
      for (const [k, v] of Object.entries(headers)) out[k] = String(v);
    }
  }
  out[SESSION_HEADER] = getSessionId();
  return out;
}

// ---------------------------------------------------------------- 会话探测（once）

/** 一次性探测 promise（模块级缓存：并发 apiFetch 共享；失败也缓存不重试）。 */
let sessionProbe: Promise<void> | null = null;
/** 探测已落定（成功/失败皆算）—— 置位后 apiFetch 不再 await（同步进 fetch，行为与旧裸 fetch 逐字节一致）。 */
let probedSettled = false;

function isBlockCode(v: unknown): v is SessionBlockCode {
  return v === 'session_expired' || v === 'session_limit';
}

/** 401/429 响应尝试读 ``code`` 键触发阻断（非 JSON / fake Response 无 clone → 忽略）。 */
async function inspectSessionError(res: Response): Promise<void> {
  if (res.ok || (res.status !== 401 && res.status !== 429)) return;
  try {
    const cloned = typeof res.clone === 'function' ? res.clone() : null;
    const data = cloned ? ((await cloned.json()) as { code?: unknown } | null) : null;
    if (data && typeof data === 'object' && isBlockCode(data.code)) {
      triggerSessionBlock(data.code);
    }
  } catch {
    // 非 JSON 错误体 / clone 失败 —— 忽略（原响应照常返回给调用方）
  }
}

/**
 * 确保会话已注册（once）：首次调用发 ``POST /api/session``（裸 fetch —— 不经
 * apiFetch 防递归），并发调用共享同一 promise；429/401 带 code 由
 * inspectSessionError 触发阻断；网络错静默（后续请求自身错误路径兜底）。
 */
export function ensureSession(): Promise<void> {
  if (!sessionProbe) {
    sessionProbe = (async () => {
      try {
        if (blocked) return;
        const res = await fetch('/api/session', {
          method: 'POST',
          headers: mergeSessionHeaders(),
        });
        await inspectSessionError(res);
      } catch {
        // 网络错（后端未起）—— 静默；probePromise 缓存失败态，后续请求不再重探
      } finally {
        probedSettled = true;
      }
    })();
  }
  return sessionProbe;
}

/**
 * 统一 fetch 出口：确保会话先行 → 注入 X-Session-Id → 拦截 401/429 code。
 *
 * - 阻断期间调用 → 直接抛 SessionBlockedError（**请求不发出**）；
 * - 探测期间调用 → await 同一 probe promise（结构性晚于建会话，防 mount 竞态
 *   误弹「已过期」）；探测若触发阻断 → 本请求同样不发；
 * - 401/429 才 clone 读错误体（错误体小；原 Response 交还调用方走既有错误处理，
 *   弹窗遮罩下用户不可见）；
 * - 其余状态码（200/400/404/422…）原样返回，调用方行为与裸 fetch 完全一致。
 */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  if (blocked) throw new SessionBlockedError(blocked);
  // 会话先行门：探测未落定时 await（并发共享 once-promise）；已落定则同步直进
  // fetch（不引入额外微任务，调用方时序与旧裸 fetch 完全一致）。
  if (!probedSettled) await ensureSession();
  if (blocked) throw new SessionBlockedError(blocked);
  const res = await fetch(input, { ...init, headers: mergeSessionHeaders(init?.headers) });
  await inspectSessionError(res);
  return res;
}

/**
 * App 挂载探测：``POST /api/session``（幂等建会话 / 刷活性，ensureSession once）。
 *
 * - 429 超限（第 5 个窗口）/ 401 过期（服务重启丢内存会话）→ 后端带 code 错误体
 *   → 触发阻断弹窗（页面加载即弹「用户过多」，无需先上传）；
 * - 200 / 400 / 网络错（后端未起）→ 静默（后续真实操作的错误路径各自处理）。
 */
export async function probeSession(): Promise<void> {
  await ensureSession();
}

// ---------------------------------------------------------------- 测试隔离

/** 测试隔离：清阻断 + 探测状态（下一测首次 apiFetch 会重新探测一次）。 */
export function resetSessionForTest(): void {
  blocked = null;
  sessionProbe = null;
  probedSettled = false;
}

/**
 * 测试便捷：预置「已探测」（apiFetch 同步直进 fetch，不发 /api/session）—— 不关心
 * 会话语义的存量用例 fetch 计数 / 首调 URL 断言零改动。
 */
export function markSessionProbedForTest(): void {
  sessionProbe = Promise.resolve();
  probedSettled = true;
}
