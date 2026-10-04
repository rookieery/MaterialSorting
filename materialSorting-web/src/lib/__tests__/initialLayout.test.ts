// initialLayout.test.ts —— 初始布局 API 封装单测（prd-initial-layout US-004）：
//   1) fetchWarmCapability：GET /api/warm-capability（无 body）+ 响应解析 +
//      非 2xx / 非 JSON / 形态异常（缺 supported / supported 非布尔）降级矩阵；
//   2) generateInitialLayout：POST /api/initial-layout/generate JSON 载荷逐键
//      透传（sizes/per_type/quantities/params/gate_mm/band/prefix/seed）+ 成功
//      响应解析（manifest/placed/width_mm/density/composite?/prefix? 段原样
//      透传，composite 畸形段滤为缺席）+ 502/409 error 中文透传 / ok!==true
//      形态异常 / fetch 抛错上抛（调用方 catch 落弹窗红字）。
//   3) US-006 保存组装纯函数：assembleWarmPlaced（band/prefix 组位移双组独立
//      记账 + 非组组合条目跳过由 working 非成员承接 + 前缀尾下划线不误吞
//      g051 + 未编辑零位移 + mirror 剥离 + 守恒 |out| = Σ demand）/
//      plainWarmPlaced（working 全量三键形态 + mirror 剥离）。

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { fetchWarmCapability, generateInitialLayout, warmStateReasonText } from '../initialLayout';
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

// ================= US-006：保存组装纯函数（assembleWarmPlaced / plainWarmPlaced） =================
//
// 宇宙（band=g05 + prefix={g02,g03} 双开，展开视图 6 条 + 组合宇宙 5 条）：
//   working/baseline 下标对齐（editStore.open 快照语义）：
//     0 g051_28 非成员（g051 ≠ g05 —— 尾下划线防前缀误吞，放最前验证组扫描跳过）
//     1 g05_28  band 成员（编辑 +[30,10] → band delta）
//     2 g02_28  prefix 成员（编辑 +[5,7] → prefix delta）
//     3 g03_28  prefix 成员（同组刚性同移）
//     4 g01_28  非成员（编辑 [50,60]→[70,60] + mirror:true → 验证最新值承接 + 剥离）
//     5 g01_28  非成员第 2 副本（未动）
//   composite（组合宇宙）：WB_g05 / PS_g02+g03@28 / g01_28×2（非组组合条目，
//   组装时跳过由 working 承接）；demand_map {WB_g05:1, PS:1, g01_28:2} → Σ=4。
import {
  assembleWarmPlaced,
  plainWarmPlaced,
  type CompositePlacedItem,
} from '../initialLayout';
import type { PlacedItem, Pt } from '../../types/piece';

function p(id: string, x: number, y: number, rotation = 0, mirror?: boolean): PlacedItem {
  return {
    id,
    rotation,
    translation: [x, y] as Pt,
    ...(mirror === true ? { mirror: true } : {}),
  };
}
function c(id: string, x: number, y: number, rotation = 0): CompositePlacedItem {
  return { id, rotation, translation: [x, y] as Pt };
}

/** 双开宇宙基线（未编辑 = working 同值）。 */
function groupedFixture(): {
  baseline: PlacedItem[];
  working: PlacedItem[];
  composite: CompositePlacedItem[];
  demandMap: Record<string, number>;
} {
  const baseline: PlacedItem[] = [
    p('g051_28', 0, 0),
    p('g05_28', 0, 0),
    p('g02_28', 0, 0),
    p('g03_28', 0, 0),
    p('g01_28', 50, 60),
    p('g01_28', 150, 60),
  ];
  const working: PlacedItem[] = [
    p('g051_28', 0, 0),
    p('g05_28', 30, 10), // band 组整体 +[30,10]
    p('g02_28', 5, 7), // prefix 组整体 +[5,7]
    p('g03_28', 5, 7),
    p('g01_28', 70, 60, 0, true), // 非成员编辑（+ mirror 防御性剥离）
    p('g01_28', 150, 60),
  ];
  const composite: CompositePlacedItem[] = [
    c('WB_g05', 0, 100),
    c('PS_g02+g03@28', 10, 20),
    c('g051_28', 0, 0), // 非组组合条目（组装时跳过 —— working 承接最新值）
    c('g01_28', 50, 60, 90), // 同上
    c('g01_28', 150, 60),
  ];
  const demandMap: Record<string, number> = {
    WB_g05: 1,
    'PS_g02+g03@28': 1,
    g051_28: 1,
    g01_28: 2,
  };
  return { baseline, working, composite, demandMap };
}

const GROUPS = { bandLabel: 'g05', prefixPids: ['g02_28', 'g03_28'] as readonly string[] };

describe('assembleWarmPlaced (US-006 保存组装)', () => {
  it('双组独立记账：WB_ += band delta、PS_ += prefix delta；非组组合条目跳过由 working 非成员最新值承接；mirror 剥离；g051 不被 g05 前缀误吞', () => {
    const { baseline, working, composite, demandMap } = groupedFixture();
    const out = assembleWarmPlaced(working, baseline, composite, GROUPS);
    // 组条目：delta 记账（组位移差叠加在组合基线位置上）
    // 条数 = 2 组条目 + 3 非成员（g051_28 不被 g05_ 前缀误吞 → 单片承接 + g01×2）
    expect(out.map((it) => it.id)).toEqual([
      'WB_g05', 'PS_g02+g03@28', 'g051_28', 'g01_28', 'g01_28',
    ]);
    expect(out[0]).toEqual(c('WB_g05', 30, 110)); // [0,100]+[30,10]
    expect(out[1]).toEqual(c('PS_g02+g03@28', 15, 27)); // [10,20]+[5,7]
    // 非成员：当前 working 值（编辑生效 + rotation 沿 working + mirror 键消失）
    expect(out[2]).toEqual(c('g051_28', 0, 0));
    expect(out[3]).toEqual(c('g01_28', 70, 60));
    expect(out[4]).toEqual(c('g01_28', 150, 60));
    expect('mirror' in (out[3] as object)).toBe(false);
    // 非组组合条目（composite[2] rotation 90）绝不出现 —— 被 working 值取代
    expect(out.some((it) => it.rotation === 90)).toBe(false);
    // 守恒：|out| = Σ demand_map
    const total = Object.values(demandMap).reduce((a, b) => a + b, 0);
    expect(out.length).toBe(total);
  });

  it('未编辑（working ≡ baseline）→ 双组零位移，组条目原位', () => {
    const { baseline, composite } = groupedFixture();
    const out = assembleWarmPlaced(baseline, baseline, composite, GROUPS);
    expect(out[0]).toEqual(c('WB_g05', 0, 100));
    expect(out[1]).toEqual(c('PS_g02+g03@28', 10, 20));
    expect(out).toHaveLength(5); // 2 组条目 + 3 非成员（g051_28 + g01×2）
  });

  it('仅 band 开（prefixPids 空）→ PS_ 条目零位移 + working prefix 片按非成员逐条承接', () => {
    const { baseline, working, composite } = groupedFixture();
    const out = assembleWarmPlaced(working, baseline, composite, {
      bandLabel: 'g05',
      prefixPids: [],
    });
    expect(out[0]).toEqual(c('WB_g05', 30, 110));
    expect(out[1]).toEqual(c('PS_g02+g03@28', 10, 20)); // prefix 关 → 零位移
    // g02/g03 现为非成员 → working 值逐条进入
    const ids = out.map((it) => it.id);
    expect(ids).toEqual([
      'WB_g05', 'PS_g02+g03@28', 'g051_28', 'g02_28', 'g03_28', 'g01_28', 'g01_28',
    ]);
    expect(out[3]).toEqual(c('g02_28', 5, 7));
  });

  it('成员 id 错位（基线与 working 下标不对齐）→ 组 delta 回退零（守恒优先，宁可保基线位置）', () => {
    const { working, composite } = groupedFixture();
    // 基线首条 id 错位（理论不可达 —— open 快照保序；防御路径验证）
    const badBaseline: PlacedItem[] = [...groupedFixture().baseline];
    badBaseline[1] = p('gXX_28', 0, 0);
    const out = assembleWarmPlaced(working, badBaseline, composite, GROUPS);
    expect(out[0]).toEqual(c('WB_g05', 0, 100)); // band delta null → ZERO
    expect(out[1]).toEqual(c('PS_g02+g03@28', 15, 27)); // prefix 未错位照常记账
  });
});

describe('plainWarmPlaced (US-006 plain 组装)', () => {
  it('working 全量三键形态逐条映射 + mirror 剥离 + 条目数守恒', () => {
    const working: PlacedItem[] = [
      p('g01_28', 10, 20),
      p('g03_34', 30, 40, 180, true),
      p('g01_28', 50, 60, 180),
    ];
    const out = plainWarmPlaced(working);
    expect(out).toEqual([
      c('g01_28', 10, 20),
      c('g03_34', 30, 40, 180),
      c('g01_28', 50, 60, 180),
    ]);
    expect(out).toHaveLength(3);
    for (const it of out) expect(Object.keys(it).sort()).toEqual(['id', 'rotation', 'translation']);
  });

  it('空 working → 空数组', () => {
    expect(plainWarmPlaced([])).toEqual([]);
  });
});

// ============================================================
// US-007 warmStateReasonText —— final.warm_state.reason 语义族
// 映射（后端双形态：token 码 + build_warm_payload 中文串 → 三族固定
// toast 文案；未识别 reason 兜底 invalid 族，保证每条降级必有一条中文提示）。
// ============================================================
describe('warmStateReasonText (US-007 final warm_state toast 映射)', () => {
  it('unsupported 族：token unsupported / worker_unsupported → 不支持热启动文案', () => {
    expect(warmStateReasonText('unsupported')).toBe(
      '当前 spyrrow 版本不支持热启动，已按普通方式运行',
    );
    expect(warmStateReasonText('worker_unsupported')).toBe(
      '当前 spyrrow 版本不支持热启动，已按普通方式运行',
    );
  });

  it('unsupported 族：后端中文串（需 0.9.0+ms1 及以上私有 wheel）→ 同文案（子串匹配）', () => {
    expect(
      warmStateReasonText('当前 spyrrow 版本不支持热启动（需 0.9.0+ms1 及以上私有 wheel）'),
    ).toBe('当前 spyrrow 版本不支持热启动，已按普通方式运行');
  });

  it('mismatch 族：token instance_mismatch → 数量或参数不一致文案', () => {
    expect(warmStateReasonText('instance_mismatch')).toBe(
      '数量或参数与初始布局不一致，已按普通方式运行',
    );
  });

  it('mismatch 族：后端中文串（需求映射外的裁片 id…母版或数量/参数已变更）→ 同文案', () => {
    expect(
      warmStateReasonText('初始布局第 3 条含当前需求映射外的裁片 id g07_34（母版或数量/参数已变更？）'),
    ).toBe('数量或参数与初始布局不一致，已按普通方式运行');
  });

  it('invalid 族：token invalid_* / warmstart ValueError 中文串 / 空串 → 校验未通过文案', () => {
    expect(warmStateReasonText('invalid_geometry')).toBe(
      '初始布局校验未通过，已按普通方式运行',
    );
    expect(warmStateReasonText('warmstart: invalid rotation')).toBe(
      '初始布局校验未通过，已按普通方式运行',
    );
    // reason 缺席（后端 engaged=false 必带 reason，防御口径）→ 兜底 invalid 族
    expect(warmStateReasonText('')).toBe('初始布局校验未通过，已按普通方式运行');
  });

  it('worker_serialize_failed → invalid 族（装载点解析成功但 worker 序列化失败，非版本问题）', () => {
    expect(warmStateReasonText('worker_serialize_failed')).toBe(
      '初始布局校验未通过，已按普通方式运行',
    );
  });
});
