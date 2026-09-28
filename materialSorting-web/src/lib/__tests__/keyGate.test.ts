// key 授权 US-007 ensureRunAllowed 单测：POST /api/key/precheck 契约 + 宽容放行
// 口径 + 失败 Toast 出口（三入口共用单一实现，文案一致性由共源性保证）。
//   - 载荷：doc_source = uploadStore 当前 doc 的 filename（与后端闸门 basename
//     样例豁免口径对齐）；无 doc → null
//   - {ok:true[,reason]} → 放行（reason 透传，debug 可观测），不弹 Toast
//   - {ok:false,message} → 拦截 + Toast（message 原样；缺失 → 兜底文案）
//   - 200 无 ok 键（mock fetch 兜底分支 / 半截响应）→ 宽容放行（权威闸门在
//     后端 US-005 fail-closed；前端预检漏拦最多晚一拍由后端拦下，绝不误拦 ——
//     既有 store/modal 测试零改动的兼容基石）
//   - 非 2xx → 拦截 + {error} 透传（无则 HTTP 兜底）
//   - fetch 抛错（MS 后端不可达）→ 拦截 + 本地兜底文案（前端不自行判断网络 ——
//     keyserver 侧断网文案由后端 precheck 映射，此处只兜 MS 后端自身）

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { ensureRunAllowed } from '../keyGate';
import { markSessionProbedForTest, resetSessionForTest } from '../api';
import { __resetToastsForTest, useToastStore } from '../../store/toastStore';
import { useUploadStore } from '../../store/uploadStore';
import type { ParsedDoc } from '../../types/parsed';

let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
let precheckBodies: unknown[] = [];

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

function toastMessages(): string[] {
  return useToastStore.getState().toasts.map((t) => t.message);
}

beforeEach(() => {
  markSessionProbedForTest();
  __resetToastsForTest();
  useUploadStore.getState().reset();
  precheckBodies = [];
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/api/key/precheck')) {
      precheckBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      return Promise.resolve(json(CURRENT.precheck));
    }
    return Promise.resolve(json({}));
  }) as (...args: unknown[]) => Promise<Response>);
});

afterEach(() => {
  fetchSpy?.mockRestore();
  fetchSpy = null;
  resetSessionForTest();
  __resetToastsForTest();
  useUploadStore.getState().reset();
});

/** 当前 mock 回包（用例内覆写 CURRENT.precheck）。 */
const CURRENT: { precheck: unknown } = { precheck: { ok: true } };

describe('keyGate ensureRunAllowed (key 授权 US-007)', () => {
  it('POST /api/key/precheck；doc_source = uploadStore 当前 doc 的 filename', async () => {
    const doc = { doc_id: 'abc', filename: 'M1787样例.dxf', sizes: [] } as unknown as ParsedDoc;
    useUploadStore.setState({ doc, status: 'done' });
    CURRENT.precheck = { ok: true };
    const r = await ensureRunAllowed();
    expect(r).toEqual({ ok: true });
    expect(precheckBodies).toEqual([{ doc_source: 'M1787样例.dxf' }]);
    expect(toastMessages()).toEqual([]);
  });

  it('无 doc → doc_source: null（后端无样例豁免 → 走 key 判定）', async () => {
    CURRENT.precheck = { ok: true, reason: 'off' };
    const r = await ensureRunAllowed();
    expect(r).toEqual({ ok: true, reason: 'off' }); // 豁免原因透传（debug 可观测）
    expect(precheckBodies).toEqual([{ doc_source: null }]);
  });

  it('{ok:false,message} → 拦截 + Toast（message 原样；后端断网文案即此路径）', async () => {
    CURRENT.precheck = { ok: false, message: '无法连接授权服务器，请检查网络后重试' };
    const r = await ensureRunAllowed();
    expect(r).toEqual({ ok: false, message: '无法连接授权服务器，请检查网络后重试' });
    expect(toastMessages()).toEqual(['无法连接授权服务器，请检查网络后重试']);
  });

  it('{ok:false} 无 message → 兜底文案 + Toast', async () => {
    CURRENT.precheck = { ok: false };
    const r = await ensureRunAllowed();
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.message).toBe('授权校验未通过，请检查 key 状态');
    expect(toastMessages()).toHaveLength(1);
  });

  it('200 无 ok 键（mock 兜底分支 / 半截响应）→ 宽容放行不弹 Toast（零改动兼容基石）', async () => {
    CURRENT.precheck = { representatives: {} };
    const r = await ensureRunAllowed();
    expect(r).toEqual({ ok: true });
    expect(toastMessages()).toEqual([]);
  });

  it('非 2xx → 拦截 + {error} 透传（无则 HTTP 兜底）+ Toast', async () => {
    fetchSpy!.mockImplementation(((input: unknown) => {
      const url = String(input);
      if (url.includes('/api/key/precheck')) {
        precheckBodies.push(null);
        return Promise.resolve(json({ error: '请求体须为 JSON 对象' }, 400));
      }
      return Promise.resolve(json({}));
    }) as (...args: unknown[]) => Promise<Response>);
    let r = await ensureRunAllowed();
    expect(r).toEqual({ ok: false, message: '请求体须为 JSON 对象' });
    expect(toastMessages()).toEqual(['请求体须为 JSON 对象']);

    fetchSpy!.mockImplementation(((input: unknown) => {
      const url = String(input);
      if (url.includes('/api/key/precheck')) {
        precheckBodies.push(null);
        return Promise.resolve(new Response('nope', { status: 502 }));
      }
      return Promise.resolve(json({}));
    }) as (...args: unknown[]) => Promise<Response>);
    r = await ensureRunAllowed();
    expect(r).toEqual({ ok: false, message: '运行前校验失败（HTTP 502）' });
  });

  it('fetch 抛错（MS 后端不可达）→ 拦截 + 本地兜底文案 + Toast（永不抛错）', async () => {
    fetchSpy!.mockImplementation(() => Promise.reject(new TypeError('Failed to fetch')));
    const r = await ensureRunAllowed();
    expect(r).toEqual({ ok: false, message: '无法连接服务器，请检查网络后重试' });
    expect(toastMessages()).toEqual(['无法连接服务器，请检查网络后重试']);
  });
});
