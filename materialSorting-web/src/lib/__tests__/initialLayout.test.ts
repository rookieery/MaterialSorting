// initialLayout.test.ts —— 初始布局 API 封装单测（prd-initial-layout US-004）：
//   1) fetchWarmCapability：GET /api/warm-capability（无 body）+ 响应解析 +
//      非 2xx / 非 JSON / 形态异常（缺 supported / supported 非布尔）降级矩阵；
//   2) generateInitialLayout：POST /api/initial-layout/generate JSON 载荷逐键
//      透传（sizes/per_type/quantities/params/gate_mm/band/prefix/seed）+ 成功
//      响应解析（manifest/placed/width_mm/density/composite?/prefix? 段原样
//      透传，composite 畸形段滤为缺席）+ 502/409 error 中文透传 / ok!==true
//      形态异常 / fetch 抛错上抛（调用方 catch 落弹窗红字）。

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { fetchWarmCapability, generateInitialLayout } from '../initialLayout';
import { markSessionProbedForTest, resetSessionForTest } from '../api';

let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
/** 收到的请求 (url, init) 序列（断言 method/body/headers）。 */
let calls: { url: string; init?: RequestInit }[] = [];

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** 当前 mock 路由表（用例内覆写；未命中 → 200 空对象）。 */
const ROUTES: Record<string, () => Response> = {};

beforeEach(() => {
  markSessionProbedForTest();
  calls = [];
  for (const k of Object.keys(ROUTES)) delete ROUTES[k];
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const hit = ROUTES[url];
    return Promise.resolve(hit ? hit() : json({}));
  }) as (...args: unknown[]) => Promise<Response>);
});

afterEach(() => {
  fetchSpy?.mockRestore();
  fetchSpy = null;
  resetSessionForTest();
});

describe('fetchWarmCapability (初始布局 US-004)', () => {
  it('GET /api/warm-capability（无 body）→ {supported, version} 解析', async () => {
    ROUTES['/api/warm-capability'] = () => json({ supported: true, version: '0.9.0+ms1' });
    const cap = await fetchWarmCapability();
    expect(cap).toEqual({ supported: true, version: '0.9.0+ms1' });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe('/api/warm-capability');
    expect(calls[0].init?.body).toBeUndefined(); // GET 无 body
  });

  it('supported:false 正常解析（不支持态是合法响应非错误）', async () => {
    ROUTES['/api/warm-capability'] = () => json({ supported: false, version: '(未安装)' });
    const cap = await fetchWarmCapability();
    expect(cap).toEqual({ supported: false, version: '(未安装)' });
  });

  it('非 2xx → Error（HTTP 状态码文案）', async () => {
    ROUTES['/api/warm-capability'] = () => json({ error: 'x' }, 500);
    await expect(fetchWarmCapability()).rejects.toThrow('热启动能力探测失败（HTTP 500）');
  });

  it('形态异常（缺 supported / supported 非布尔）→ Error 中文', async () => {
    ROUTES['/api/warm-capability'] = () => json({ version: '0.9.0' });
    await expect(fetchWarmCapability()).rejects.toThrow('响应形态异常');
    ROUTES['/api/warm-capability'] = () => json({ supported: 'yes', version: '0.9.0' });
    await expect(fetchWarmCapability()).rejects.toThrow('响应形态异常');
  });

  it('非 JSON 响应体 → Error「响应不是有效 JSON」', async () => {
    ROUTES['/api/warm-capability'] = () => new Response('not-json', { status: 200 });
    await expect(fetchWarmCapability()).rejects.toThrow('响应不是有效 JSON');
  });

  it('fetch 抛错（后端未起）→ 上抛（调用方 probeCapability catch 静默）', async () => {
    fetchSpy!.mockImplementation(() => Promise.reject(new TypeError('Failed to fetch')));
    await expect(fetchWarmCapability()).rejects.toThrow();
  });
});

describe('generateInitialLayout (初始布局 US-004)', () => {
  /** plain 成功响应（composite/prefix 缺席）。 */
  function plainOk(): Response {
    return json({
      ok: true,
      manifest: { type: 'manifest', gate_mm: 1750, total_area_mm2: 1000, n_eroded: 0, pieces: [] },
      placed: [{ id: 'g01_28', rotation: 0, translation: [10, 20] }],
      width_mm: 600,
      density: 85.5,
    });
  }

  it('POST /api/initial-layout/generate：JSON 载荷逐键透传 + 响应解析（plain 无 composite/prefix 键）', async () => {
    ROUTES['/api/initial-layout/generate'] = plainOk;
    const r = await generateInitialLayout({
      sizes: [28, 30],
      per_type: { g01: { d: 2 } },
      quantities: { g01: { '28': 2 } },
      params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
      gate_mm: 1750,
      band: { enabled: true, label: 'g05' },
      prefix: { enabled: true, front: 'g02', back: 'g03' },
      seed: 3,
    });
    // 载荷：method/headers/body 逐键
    expect(calls).toHaveLength(1);
    const init = calls[0].init!;
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(JSON.parse(String(init.body))).toEqual({
      sizes: [28, 30],
      per_type: { g01: { d: 2 } },
      quantities: { g01: { '28': 2 } },
      params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
      gate_mm: 1750,
      band: { enabled: true, label: 'g05' },
      prefix: { enabled: true, front: 'g02', back: 'g03' },
      seed: 3,
    });
    // 响应：ok 剥离 + 四主键透传 + composite/prefix 缺席（无键，非 undefined 值）
    expect((r as unknown as Record<string, unknown>).ok).toBeUndefined();
    expect(r.manifest).toEqual({
      type: 'manifest', gate_mm: 1750, total_area_mm2: 1000, n_eroded: 0, pieces: [],
    });
    expect(r.placed).toEqual([{ id: 'g01_28', rotation: 0, translation: [10, 20] }]);
    expect(r.width_mm).toBe(600);
    expect(r.density).toBe(85.5);
    expect('composite' in r).toBe(false);
    expect('prefix' in r).toBe(false);
  });

  it('band/prefix 开：composite{placed_items(含 WB_), demand_map} + prefix 段原样透传', async () => {
    const composite = {
      placed_items: [
        { id: 'WB_g05', rotation: 0, translation: [0, 100] },
        { id: 'g01_28', rotation: 90, translation: [50, 60] },
      ],
      demand_map: { WB_g05: 1, 'g01_28': 2 },
    };
    const prefix = { size: 34, pid: 'PS_g02+g03@34', extra: null, residual_mm: 1.2, fallback: false };
    ROUTES['/api/initial-layout/generate'] = () =>
      json({
        ok: true,
        manifest: { type: 'manifest', gate_mm: 1750, total_area_mm2: 1, n_eroded: 0, pieces: [] },
        placed: [],
        width_mm: 700,
        density: 90,
        composite,
        prefix,
      });
    const r = await generateInitialLayout({ band: { enabled: true, label: 'g05' } });
    expect(r.composite).toEqual(composite);
    expect(r.prefix).toEqual(prefix);
  });

  it('composite 畸形段（placed_items 缺）→ 滤为缺席（plain 降级）', async () => {
    ROUTES['/api/initial-layout/generate'] = () =>
      json({
        ok: true,
        manifest: { type: 'manifest' },
        placed: [],
        width_mm: 1,
        density: 1,
        composite: { demand_map: { a: 1 } },
      });
    const r = await generateInitialLayout({});
    expect('composite' in r).toBe(false);
  });

  it('502/409 {error: 中文} → Error 透传后端文案', async () => {
    ROUTES['/api/initial-layout/generate'] = () =>
      json({ error: '求解失败: worker process exited unexpectedly (code=1)' }, 502);
    await expect(generateInitialLayout({})).rejects.toThrow(
      '初始布局生成失败：求解失败: worker process exited unexpectedly (code=1)',
    );
    ROUTES['/api/initial-layout/generate'] = () =>
      json({ error: '该会话初始布局正在生成中，请稍候再试' }, 409);
    await expect(generateInitialLayout({})).rejects.toThrow(
      '初始布局生成失败：该会话初始布局正在生成中，请稍候再试',
    );
  });

  it('ok !== true（半截响应）→ Error 形态异常', async () => {
    ROUTES['/api/initial-layout/generate'] = () => json({ placed: [] });
    await expect(generateInitialLayout({})).rejects.toThrow('初始布局生成失败：响应形态异常');
  });

  it('fetch 抛错（后端未起）→ 上抛 Error（调用方 catch 落弹窗红字）', async () => {
    fetchSpy!.mockImplementation(() => Promise.reject(new TypeError('Failed to fetch')));
    await expect(generateInitialLayout({})).rejects.toThrow();
  });
});
