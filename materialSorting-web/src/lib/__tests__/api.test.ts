// US-005 api.ts 单测：apiFetch 统一出口（Header 注入 + 会话先行门 + 阻断拦截）。
//   AC1 所有请求带 X-Session-Id（与既有 Content-Type 合并，普通对象可属性直取）。
//   AC2 会话先行：首次 apiFetch 前置一次 POST /api/session（once，并发共享）——
//      mount 竞态（子组件 effect 先于 App 探测发请求）结构性消除。
//   AC3 401/429 带 code 错误体 → 触发全局阻断；原 Response 照常返回给调用方。
//   AC4 阻断期间后续 apiFetch → 抛 SessionBlockedError 且 fetch 不再被调用。
//   AC5 非 401/429 / 无 code / 非 JSON —— 不触发阻断。
//   AC6 triggerSessionBlock 幂等（首个 code 定终身）+ 订阅通知。
//   AC7 probeSession：200 静默；429 code → 阻断（第 5 窗口页面加载即弹）。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SESSION_HEADER,
  SessionBlockedError,
  apiFetch,
  ensureSession,
  getSessionBlock,
  markSessionProbedForTest,
  mergeSessionHeaders,
  probeSession,
  resetSessionForTest,
  subscribeSessionBlock,
  triggerSessionBlock,
} from '../api';
import { getSessionId, resetSessionIdForTest } from '../session';

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

/** URL 路由 mock：/api/session → 200；其他 URL → overrides 命中或 200。 */
function mockFetchRoute(overrides: Record<string, Response> = {}) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown) => {
    const url = String(input);
    if (url.includes('/api/session')) return Promise.resolve(json({ ok: true }));
    if (overrides[url]) return Promise.resolve(overrides[url]);
    return Promise.resolve(json({ ok: true }));
  }) as unknown as typeof fetch);
}

beforeEach(() => {
  localStorage.clear();
  resetSessionIdForTest();
  resetSessionForTest();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  resetSessionIdForTest();
  resetSessionForTest();
});

describe('apiFetch Header 注入（US-005 AC1）', () => {
  it('无 headers 调用也带 X-Session-Id（= 当前 sid）', async () => {
    const spy = mockFetchRoute();
    const res = await apiFetch('/api/ptypes');
    expect(res.ok).toBe(true);
    const call = spy.mock.calls.find((c) => String(c[0]) === '/api/ptypes')!;
    const headers = call[1]!.headers as Record<string, string>;
    expect(headers[SESSION_HEADER]).toBe(getSessionId());
  });

  it('与既有 Content-Type 合并（普通对象属性直取，两键都在）', async () => {
    const spy = mockFetchRoute();
    await apiFetch('/api/strategy/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    const call = spy.mock.calls.find((c) => String(c[0]) === '/api/strategy/start')!;
    const headers = call[1]!.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers[SESSION_HEADER]).toBe(getSessionId());
  });

  it('mergeSessionHeaders：Headers 实例 / 数组形态归一为普通对象', () => {
    // Headers 实例按规范小写化键名（HTTP header 大小写不敏感）—— 归一后属性直取
    expect(mergeSessionHeaders(new Headers({ 'Content-Type': 'application/json' }))).toEqual({
      'content-type': 'application/json',
      [SESSION_HEADER]: getSessionId(),
    });
    expect(
      mergeSessionHeaders([['Accept', 'application/json']] as HeadersInit),
    ).toEqual({
      Accept: 'application/json',
      [SESSION_HEADER]: getSessionId(),
    });
  });
});

describe('会话先行门（US-005 AC2）', () => {
  it('首次 apiFetch 前置一次 POST /api/session（探测先于业务请求）', async () => {
    const spy = mockFetchRoute();
    await apiFetch('/api/strategy/status');
    expect(String(spy.mock.calls[0][0])).toBe('/api/session');
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe('POST');
    expect(String(spy.mock.calls[1][0])).toBe('/api/strategy/status');
  });

  it('探测 once：多次 apiFetch 只发一次 /api/session（并发共享 promise）', async () => {
    const spy = mockFetchRoute();
    await Promise.all([apiFetch('/a'), apiFetch('/b')]);
    await apiFetch('/c');
    const probes = spy.mock.calls.filter((c) => String(c[0]).includes('/api/session'));
    expect(probes.length).toBe(1);
    expect(spy.mock.calls.length).toBe(4); // 1 probe + a + b + c
  });

  it('探测 429 触发阻断 → 排队中的业务请求不再发出（第 5 窗口 mount 场景）', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown) =>
      Promise.resolve(
        String(input).includes('/api/session')
          ? json({ code: 'session_limit', error: '用户过多' }, 429)
          : json({ ok: true }),
      )) as unknown as typeof fetch);
    await expect(apiFetch('/api/strategy/status')).rejects.toBeInstanceOf(SessionBlockedError);
    // 只发了探测，业务请求被 swallow
    expect(spy.mock.calls.map((c) => String(c[0]))).toEqual(['/api/session']);
    expect(getSessionBlock()).toBe('session_limit');
  });

  it('markSessionProbedForTest：预置已探测 → apiFetch 直发不再探测（存量用例零改动）', async () => {
    markSessionProbedForTest();
    const spy = mockFetchRoute();
    await apiFetch('/a');
    expect(spy.mock.calls.length).toBe(1);
    expect(String(spy.mock.calls[0][0])).toBe('/a');
  });

  it('ensureSession = probeSession 同一 once promise（App 挂载探测幂等）', async () => {
    const spy = mockFetchRoute();
    await Promise.all([probeSession(), ensureSession(), probeSession()]);
    const probes = spy.mock.calls.filter((c) => String(c[0]).includes('/api/session'));
    expect(probes.length).toBe(1);
  });
});

describe('apiFetch 会话阻断拦截（US-005 AC3-AC5）', () => {
  it('AC3 401 {code:session_expired} → 触发阻断 + 原 Response 原样返回', async () => {
    const spy = mockFetchRoute({
      '/api/ptypes': json({ code: 'session_expired', error: '会话已过期' }, 401),
    });
    const res = await apiFetch('/api/ptypes');
    expect(res.status).toBe(401);
    expect(getSessionBlock()).toBe('session_expired');
    // 原响应 body 未被消费（clone 读 code，本体留给调用方）
    const data = (await res.json()) as { code: string };
    expect(data.code).toBe('session_expired');
    expect(spy).toHaveBeenCalled();
  });

  it('AC3 429 {code:session_limit} → 阻断码 session_limit', async () => {
    mockFetchRoute({
      '/api/strategy/status': json({ code: 'session_limit', error: '用户过多' }, 429),
    });
    await apiFetch('/api/strategy/status');
    expect(getSessionBlock()).toBe('session_limit');
  });

  it('AC4 阻断期间后续 apiFetch → SessionBlockedError 且 fetch 不发出', async () => {
    const spy = mockFetchRoute({
      '/api/ptypes': json({ code: 'session_expired', error: 'x' }, 401),
    });
    await apiFetch('/api/ptypes');
    const callsAfterFirst = spy.mock.calls.length;
    await expect(apiFetch('/api/ptypes')).rejects.toBeInstanceOf(SessionBlockedError);
    await expect(apiFetch('/api/strategy/status')).rejects.toThrow('会话已阻断');
    // 关键：swallow —— 后续调用没有真正发起网络请求
    expect(spy.mock.calls.length).toBe(callsAfterFirst);
  });

  it('AC5 401 无 code / 400 / 200 —— 均不触发阻断', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ error: 'no code' }, 401));
    await apiFetch('/a');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ error: 'bad request' }, 400));
    await apiFetch('/b');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ ok: true }));
    await apiFetch('/c');
    expect(getSessionBlock()).toBeNull();
  });

  it('AC6 triggerSessionBlock 幂等（首个 code 定终身）+ 订阅者收到一次通知', () => {
    const fn = vi.fn();
    const unsub = subscribeSessionBlock(fn);
    triggerSessionBlock('session_limit');
    triggerSessionBlock('session_expired'); // 已阻断 → 静默忽略
    expect(getSessionBlock()).toBe('session_limit');
    expect(fn).toHaveBeenCalledTimes(1);
    unsub();
  });

  it('AC8 session_expired 丢弃 sid（墓碑 1h 拒重建 —— 刷新换新 sid 才是出口）', async () => {
    const sidBefore = getSessionId();
    expect(localStorage.getItem('ms_sid')).toBe(sidBefore);
    mockFetchRoute({
      '/api/ptypes': json({ code: 'session_expired', error: '会话已过期' }, 401),
    });
    await apiFetch('/api/ptypes');
    expect(getSessionBlock()).toBe('session_expired');
    // ms_sid 已清：下一次 getSessionId（= 刷新后的新页面）铸造全新 sid
    expect(localStorage.getItem('ms_sid')).toBeNull();
    expect(getSessionId()).not.toBe(sidBefore);
    expect(getSessionId()).toMatch(/^[0-9a-f]{32}$/);
  });

  it('AC8 session_limit 保留 sid（会话仍有效 —— 稍后重试原会话续用）', async () => {
    const sidBefore = getSessionId();
    mockFetchRoute({
      '/api/ptypes': json({ code: 'session_limit', error: '用户过多' }, 429),
    });
    await apiFetch('/api/ptypes');
    expect(getSessionBlock()).toBe('session_limit');
    expect(getSessionId()).toBe(sidBefore);
  });
});

describe('probeSession（US-005 AC7）', () => {
  it('200 → 静默不阻断（POST /api/session + X-Session-Id）', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ ok: true, sid: 'x' }));
    await expect(probeSession()).resolves.toBeUndefined();
    expect(getSessionBlock()).toBeNull();
    expect(String(spy.mock.calls[0][0])).toBe('/api/session');
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe('POST');
  });

  it('429 code:session_limit → 页面加载即阻断（第 5 窗口无需先上传）', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      json({ code: 'session_limit', error: '用户过多' }, 429),
    );
    await expect(probeSession()).resolves.toBeUndefined();
    expect(getSessionBlock()).toBe('session_limit');
  });

  it('网络错 → 探测静默（后端未起不炸 UI）', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(probeSession()).resolves.toBeUndefined();
    expect(getSessionBlock()).toBeNull();
  });
});
