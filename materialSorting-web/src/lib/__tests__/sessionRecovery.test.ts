// 会话过期自动恢复 US-003 单测：启动期恢复（ensureSession 探测 401 三分支）+
// 旧 sid 非铸造捕获时序 + once-probe 并发收敛 + 停留期不清 sid 不自动恢复。
//
// 本文件 import '../sessionRecovery' 即注册恢复钩子（生产 = App.tsx 静态 import，
// 同一装载副作用）—— 集成用例全部经 apiFetch/ensureSession 真实链路驱动。
//
//   - 启动 401 三分支：recover 200（applyRestorePayload 回显 + toast + 新 sid
//     重探放行）/ 404（静默兜底新会话 + toast）/ 429（既有阻断弹窗，文案不变）；
//     另网络失败同 404 兜底；
//   - 时序红线：peek 旧 sid（非铸造）→ clear → 铸新 → recover body from_sid=旧、
//     header=新；
//   - 并发收敛：恢复全程在 once-promise 内 —— N 并发 apiFetch = 1 探测 + 1
//     recover + 1 重探 + N 业务（无请求风暴）；
//   - 停留期（探测已落定）业务 401：只阻断不恢复、sid 保留（刷新后恢复的
//     from_sid 来源）。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SESSION_HEADER,
  SessionBlockedError,
  apiFetch,
  ensureSession,
  getSessionBlock,
  markSessionProbedForTest,
  resetSessionForTest,
} from '../api';
import { getSessionId, resetSessionIdForTest } from '../session';
import {
  TOAST_NEW_SESSION,
  TOAST_RECOVERED,
  recoverExpiredSession,
} from '../sessionRecovery';
import { DEFAULT_FORM } from '../params';
import { __resetToastsForTest, useToastStore } from '../../store/toastStore';
import { useEditStore } from '../../store/editStore';
import { useFormStore } from '../../store/formStore';
import { usePtypeStore } from '../../store/ptypeStore';
import { useQtyStore } from '../../store/qtyStore';
import { runRegistry } from '../../store/runRegistry';
import { useSynthRunStore } from '../../store/synthRunStore';
import { useUiStore } from '../../store/uiStore';
import { useUploadStore } from '../../store/uploadStore';
import type { ParsedDoc } from '../../types/parsed';
import type { StateRestoreResponse } from '../../types/stateFile';

/** 过期旧 sid（合法 32-hex，预置 localStorage 模拟「刷新前已持有」）。 */
const OLD_SID = '0123456789abcdef0123456789abcdef';

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

/** 恢复响应夹具（withRun=true 含 run 块 → applyRestorePayload 切超排 Tab）。 */
function makeRestore(withRun = false): StateRestoreResponse {
  const piece = (label: string) => ({
    label,
    polygon: [],
    internal_lines: [],
    notches: [],
    net_polygon: [],
    grain_line: null,
  });
  const parse: ParsedDoc = {
    doc_id: 'recovered-doc-1',
    filename: 'M1787.dxf',
    sizes: [{ size: 28, pieces: [piece('g01')] }],
  };
  const base: StateRestoreResponse = {
    doc_id: 'recovered-doc-1',
    filename: 'M1787.dxf',
    parse,
    manifest: { gate_mm: 1750, total_area_mm2: 500000, n_eroded: 0, pieces: [] },
    final: null,
    placed: null,
    run: null,
    form: { ...DEFAULT_FORM, sizes: [28], gate: '175.00' },
    quantities: { g01: { '28': 3 } },
    quantities_base: null,
  };
  if (!withRun) return base;
  const fin = {
    density: 0.7,
    density_sparrow: 0.68,
    width_mm: 5000,
    elapsed: 10,
    n_frames: 1,
    n_eroded: 0,
  };
  const placed = [{ id: 'g01_28', rotation: 0, translation: [10, 20] as [number, number] }];
  return {
    ...base,
    final: fin,
    placed,
    run: { seed: 7, final: fin, placed },
  };
}

interface RouteOpts {
  /** /api/session 携旧 sid（= 过期探测）时的响应。 */
  probeOld?: () => Response | Promise<Response>;
  /** /api/state-recover 响应。 */
  recover?: () => Response | Promise<Response>;
  /** 其余业务请求响应。 */
  other?: () => Response;
}

/** URL + X-Session-Id 路由 mock（默认：探测 200 / recover 200 / 业务 200）。 */
function mockRoute(opts: RouteOpts = {}) {
  return vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation((((input: unknown, init?: RequestInit) => {
      const url = String(input);
      const headers = (init?.headers ?? {}) as Record<string, string>;
      const sid = headers[SESSION_HEADER] ?? headers['x-session-id'] ?? '';
      if (url.includes('/api/state-recover')) {
        return Promise.resolve(opts.recover ? opts.recover() : json(makeRestore(true)));
      }
      if (url.includes('/api/session')) {
        if (opts.probeOld && sid === OLD_SID) return Promise.resolve(opts.probeOld());
        return Promise.resolve(json({ ok: true }));
      }
      return Promise.resolve(opts.other ? opts.other() : json({ ok: true }));
    }) as unknown as typeof fetch));
}

/** 预置「刷新页面」现场：localStorage 持旧 sid + 全部模块缓存/阻断态复位。 */
function presetFreshLoad(): void {
  localStorage.setItem('ms_sid', OLD_SID);
  resetSessionIdForTest();
}

beforeEach(() => {
  localStorage.clear();
  resetSessionIdForTest();
  resetSessionForTest();
  __resetToastsForTest();
  useFormStore.getState().reset();
  useQtyStore.getState().resetQuantities();
  runRegistry.clear();
  useUploadStore.getState().reset();
  usePtypeStore.getState().reset();
  useSynthRunStore.setState({ token: 0, seed: 0, note: '', origin: undefined });
  useEditStore.getState().invalidate();
  useUiStore.setState({
    activeTab: 'preview',
    nestingEnabled: false,
    sessionRecovering: false,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  resetSessionIdForTest();
  resetSessionForTest();
});

describe('启动期 401 三分支（ensureSession 集成，US-003）', () => {
  it('recover 200 → applyRestorePayload 回显 + toast + 新 sid 重探放行（原请求从未先发，无需重放）', async () => {
    presetFreshLoad();
    const spy = mockRoute({
      probeOld: () => json({ code: 'session_expired', error: '会话已过期' }, 401),
    });

    const res = await apiFetch('/api/ptypes');
    expect(res.ok).toBe(true);

    // 请求时序：过期探测 → recover → 新 sid 重探 → 业务请求
    const urls = spy.mock.calls.map((c) => String(c[0]));
    expect(urls[0]).toBe('/api/session');
    expect(urls[1]).toBe('/api/state-recover');
    expect(urls[2]).toBe('/api/session');
    expect(urls[3]).toBe('/api/ptypes');

    // recover 载荷：body from_sid = 旧 sid（非铸造捕获）；header = 铸新后的 sid
    const recoverCall = spy.mock.calls[1];
    const recoverHeaders = recoverCall[1]!.headers as Record<string, string>;
    const newSid = recoverHeaders[SESSION_HEADER];
    expect(newSid).toMatch(/^[0-9a-f]{32}$/);
    expect(newSid).not.toBe(OLD_SID);
    expect(JSON.parse(String(recoverCall[1]!.body))).toEqual({ from_sid: OLD_SID });

    // 重探 + 业务请求均带新 sid；localStorage 已落新 sid；未阻断
    expect((spy.mock.calls[2][1]!.headers as Record<string, string>)[SESSION_HEADER]).toBe(newSid);
    expect((spy.mock.calls[3][1]!.headers as Record<string, string>)[SESSION_HEADER]).toBe(newSid);
    expect(localStorage.getItem('ms_sid')).toBe(newSid);
    expect(getSessionBlock()).toBeNull();

    // 恢复编排零改动复用：母版/数量矩阵回显 + run 块 → 切超排 Tab
    const up = useUploadStore.getState();
    expect(up.status).toBe('done');
    expect(up.doc!.doc_id).toBe('recovered-doc-1');
    expect(useQtyStore.getState().quantities['g01']!.perSize['28']).toBe(3);
    expect(useUiStore.getState().activeTab).toBe('nesting');

    // toast + 加载态复位
    expect(useToastStore.getState().toasts.map((t) => t.message)).toEqual([TOAST_RECOVERED]);
    expect(useUiStore.getState().sessionRecovering).toBe(false);
  });

  it('recover 404（快照不在/已消费/超 TTL）→ 静默兜底 + toast 已开启新会话 + 放行', async () => {
    presetFreshLoad();
    const spy = mockRoute({
      probeOld: () => json({ code: 'session_expired', error: '会话已过期' }, 401),
      recover: () =>
        json({ code: 'checkpoint_not_found', error: '未找到可恢复的工作状态' }, 404),
    });

    const res = await apiFetch('/api/ptypes');
    expect(res.ok).toBe(true);
    expect(getSessionBlock()).toBeNull();

    // 新会话就绪：sid 已换新 + 重探放行；无恢复态残留（doc 仍空、Tab 仍 preview）
    const newSid = localStorage.getItem('ms_sid');
    expect(newSid).not.toBe(OLD_SID);
    expect(String(spy.mock.calls[2][0])).toBe('/api/session');
    expect(useUploadStore.getState().doc).toBeNull();
    expect(useUiStore.getState().activeTab).toBe('preview');
    expect(useToastStore.getState().toasts.map((t) => t.message)).toEqual([TOAST_NEW_SESSION]);
    expect(useUiStore.getState().sessionRecovering).toBe(false);
  });

  it('recover 429（满员）→ 既有阻断弹窗（session_limit 文案不变）+ 业务请求被拦 + 无重探', async () => {
    presetFreshLoad();
    const spy = mockRoute({
      probeOld: () => json({ code: 'session_expired', error: '会话已过期' }, 401),
      recover: () => json({ code: 'session_limit', error: '用户过多' }, 429),
    });

    await expect(apiFetch('/api/strategy/status')).rejects.toBeInstanceOf(SessionBlockedError);
    expect(getSessionBlock()).toBe('session_limit');

    // 探测 1 次 + recover 1 次，无重探、无业务请求；无 toast（弹窗已足）
    const urls = spy.mock.calls.map((c) => String(c[0]));
    expect(urls).toEqual(['/api/session', '/api/state-recover']);
    expect(useToastStore.getState().toasts).toEqual([]);
    expect(useUiStore.getState().sessionRecovering).toBe(false);
  });

  it('recover 网络失败 → 兜底 toast + 新会话就绪放行（不阻断）', async () => {
    presetFreshLoad();
    const spy = mockRoute({
      probeOld: () => json({ code: 'session_expired', error: '会话已过期' }, 401),
      recover: () => Promise.reject(new TypeError('Failed to fetch')),
    });

    const res = await apiFetch('/api/ptypes');
    expect(res.ok).toBe(true);
    expect(getSessionBlock()).toBeNull();
    expect(useToastStore.getState().toasts.map((t) => t.message)).toEqual([TOAST_NEW_SESSION]);
    expect(String(spy.mock.calls[2][0])).toBe('/api/session'); // 新 sid 重探放行
  });
});

describe('旧 sid 非铸造捕获时序（peek → clear → 铸新 红线）', () => {
  it('直调 recoverExpiredSession：from_sid=旧 sid、X-Session-Id=新铸 sid、localStorage 落新', async () => {
    presetFreshLoad();
    const spy = mockRoute();

    await recoverExpiredSession();

    expect(spy.mock.calls.length).toBe(1); // 恰一次 recover，无探测掺入
    const call = spy.mock.calls[0];
    expect(String(call[0])).toBe('/api/state-recover');
    expect((call[1] as RequestInit).method).toBe('POST');
    const headers = call[1]!.headers as Record<string, string>;
    expect(JSON.parse(String(call[1]!.body))).toEqual({ from_sid: OLD_SID });
    // header sid = 铸新值（不等于旧），且已落盘（刷新后粘住新会话）
    expect(headers[SESSION_HEADER]).toMatch(/^[0-9a-f]{32}$/);
    expect(headers[SESSION_HEADER]).not.toBe(OLD_SID);
    expect(localStorage.getItem('ms_sid')).toBe(headers[SESSION_HEADER]);
    expect(getSessionId()).toBe(headers[SESSION_HEADER]);
  });

  it('无旧 sid（缓存与 localStorage 双空）→ 空 from_sid 400 → 静默新会话 toast 不崩', async () => {
    mockRoute({
      recover: () => json({ error: 'from_sid 非法' }, 400),
    });
    await recoverExpiredSession();
    expect(useToastStore.getState().toasts.map((t) => t.message)).toEqual([TOAST_NEW_SESSION]);
    expect(getSessionBlock()).toBeNull();
  });
});

describe('once-probe 并发收敛（恢复全程 single-flight）', () => {
  it('3 并发 apiFetch：1 过期探测 + 1 recover + 1 重探 + 3 业务（无请求风暴）', async () => {
    presetFreshLoad();
    // 首探挂起：并发业务请求先排队，释放后才走恢复 —— 验证 once-promise 收敛。
    let releaseProbe!: (r: Response) => void;
    const gate = new Promise<Response>((r) => {
      releaseProbe = r;
    });
    const spy = mockRoute({
      probeOld: () =>
        gate.then(() => json({ code: 'session_expired', error: '会话已过期' }, 401)),
    });

    const pending = Promise.all([apiFetch('/a'), apiFetch('/b'), apiFetch('/c')]);
    await Promise.resolve(); // 让探测 fetch 先发出
    releaseProbe(json({ code: 'session_expired', error: '会话已过期' }, 401));
    const results = await pending;
    expect(results.every((r) => r.ok)).toBe(true);

    const urls = spy.mock.calls.map((c) => String(c[0]));
    expect(urls.filter((u) => u === '/api/session').length).toBe(2); // 旧 1 + 新 1
    expect(urls.filter((u) => u === '/api/state-recover').length).toBe(1);
    expect(urls.filter((u) => u === '/api/ptypes').length).toBe(0);
    expect(urls.filter((u) => ['/a', '/b', '/c'].includes(u)).length).toBe(3);

    // 排队业务请求全部带新 sid
    const newSid = localStorage.getItem('ms_sid')!;
    for (const call of spy.mock.calls.slice(3)) {
      expect((call[1]!.headers as Record<string, string>)[SESSION_HEADER]).toBe(newSid);
    }
  });

  it('恢复期间 sessionRecovering=true（轻加载态在场），落定复位', async () => {
    presetFreshLoad();
    let releaseRecover!: (r: Response) => void;
    const gate = new Promise<Response>((r) => {
      releaseRecover = r;
    });
    mockRoute({
      probeOld: () => json({ code: 'session_expired', error: '会话已过期' }, 401),
      recover: () => gate,
    });

    const pending = apiFetch('/a');
    await vi.waitFor(() => {
      expect(useUiStore.getState().sessionRecovering).toBe(true);
    });

    releaseRecover(json(makeRestore()));
    await pending;
    expect(useUiStore.getState().sessionRecovering).toBe(false);
  });

  it('健康探测 200 → recover 端点零命中（恢复只在 401 session_expired 触发）', async () => {
    presetFreshLoad();
    const spy = mockRoute();
    await ensureSession();
    await apiFetch('/a');
    const urls = spy.mock.calls.map((c) => String(c[0]));
    expect(urls).toEqual(['/api/session', '/a']);
    expect(localStorage.getItem('ms_sid')).toBe(OLD_SID); // sid 未被动过
  });
});

describe('停留期 401（US-003 定案：不自动恢复、不清 sid）', () => {
  it('探测落定后业务请求 401 → 只阻断；sid 保留 + recover 零调用', async () => {
    const sid = getSessionId(); // 正常铸造 sid（探测前）
    markSessionProbedForTest(); // 探测已过 —— 后续 401 = 停留期过期
    const spy = mockRoute({
      other: () => json({ code: 'session_expired', error: '会话已过期' }, 401),
    });

    const res = await apiFetch('/api/ptypes');
    expect(res.status).toBe(401);
    expect(getSessionBlock()).toBe('session_expired');

    // 旧 sid 留给刷新后启动期恢复作 from_sid：不清、不换、不发 recover
    expect(localStorage.getItem('ms_sid')).toBe(sid);
    expect(getSessionId()).toBe(sid);
    expect(spy.mock.calls.map((c) => String(c[0]))).toEqual(['/api/ptypes']);
  });
});
