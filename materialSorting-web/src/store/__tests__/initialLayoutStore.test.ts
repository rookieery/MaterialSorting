// initialLayoutStore.test.ts —— 初始布局状态中心单测（prd-initial-layout US-004）：
//   1) store 类型形态：初始态 {supported:null, saved:null, generating:false,
//      genSeed:0, error:null} + 六动作（probeCapability/setSaved/clear/
//      setGenerating/bumpGenSeed/setError）+ isStale 均函数；
//   2) fingerprint 稳定性（run_stats class_key 组件口径）：同上下文同串 / 键序
//      无关（per_type·quantities 内层键序）/ None 与空同判（per_type·quantities
//      null ≡ {}；band·prefix 关闭 ≡ null ≡ enabled falsy）/ sizes 勾选序无关；
//   3) isStale：七组件任一变更判 true / 同指纹 false / saved 缺席 true；
//   4) setSaved / clear / bumpGenSeed / setGenerating / setError 行为；
//   5) probeCapability：探测成功落定 + 幂等短路（二次调用不再发）+ 失败保持
//      null 可重试。

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import {
  __resetInitialLayoutStoreForTest,
  initialLayoutFingerprint,
  useInitialLayoutStore,
  type InitialLayoutFingerprintInput,
} from '../initialLayoutStore';
import { markSessionProbedForTest, resetSessionForTest } from '../../lib/api';
import type { PerTypeOverrides, SolveParams } from '../../types/v03';

const PARAMS: SolveParams = { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 };

/** 基线指纹输入（collectStartContext 同构；各用例在此之上单字段漂移）。 */
function baseInput(): InitialLayoutFingerprintInput {
  return {
    sizes: [28, 34],
    per_type: { g01: { d: 2 } },
    quantities: { g01: { '28': 2, '34': 1 } },
    params: { ...PARAMS },
    gate_mm: 1750,
    band: null,
    prefix: null,
  };
}

beforeEach(() => {
  markSessionProbedForTest();
  __resetInitialLayoutStoreForTest();
});

afterEach(() => {
  resetSessionForTest();
  __resetInitialLayoutStoreForTest();
});

describe('store 类型形态 (初始布局 US-004)', () => {
  it('初始态五字段 + 动作均为函数', () => {
    const s = useInitialLayoutStore.getState();
    expect(s.supported).toBeNull();
    expect(s.saved).toBeNull();
    expect(s.generating).toBe(false);
    expect(s.genSeed).toBe(0);
    expect(s.error).toBeNull();
    expect(typeof s.probeCapability).toBe('function');
    expect(typeof s.setSaved).toBe('function');
    expect(typeof s.clear).toBe('function');
    expect(typeof s.setGenerating).toBe('function');
    expect(typeof s.bumpGenSeed).toBe('function');
    expect(typeof s.setError).toBe('function');
    expect(typeof s.isStale).toBe('function');
  });
});

describe('initialLayoutFingerprint 稳定性（class_key 组件口径）', () => {
  it('同输入两次调用 → 同串（确定性）', () => {
    expect(initialLayoutFingerprint(baseInput())).toBe(initialLayoutFingerprint(baseInput()));
  });

  it('键序无关：per_type / quantities / params 内层键插入序不同 → 同串', () => {
    const a = baseInput();
    const b: InitialLayoutFingerprintInput = {
      ...a,
      per_type: { g02: { tol: 3 }, g01: { d: 2 } } as PerTypeOverrides,
      quantities: { g02: { '34': 1 }, g01: { '34': 1, '28': 2 } },
      params: { tol_int: 0, tol_ext: 0, d_int: 0, d_ext: 0 },
    };
    // 补齐 a 侧同键集（b 比 a 多 g02 —— 消除变量后对拍纯键序效应）
    a.per_type = { g01: { d: 2 }, g02: { tol: 3 } };
    a.quantities = { g01: { '28': 2, '34': 1 }, g02: { '34': 1 } };
    expect(initialLayoutFingerprint(a)).toBe(initialLayoutFingerprint(b));
  });

  it('None 与空同判：per_type/quantities null ≡ {}', () => {
    const withNull = baseInput();
    withNull.per_type = null;
    withNull.quantities = null;
    const withEmpty = baseInput();
    withEmpty.per_type = {};
    withEmpty.quantities = {};
    expect(initialLayoutFingerprint(withNull)).toBe(initialLayoutFingerprint(withEmpty));
  });

  it('per_type 条目内 undefined 同判（{d:1} ≡ {d:1,tol:undefined}）', () => {
    const a = baseInput();
    const b = baseInput();
    b.per_type = { g01: { d: 2, tol: undefined } };
    expect(initialLayoutFingerprint(a)).toBe(initialLayoutFingerprint(b));
  });

  it('band/prefix 关闭三形态同判：null ≡ {enabled:false} ≡ {enabled:false, 残留 label}', () => {
    const n = baseInput();
    const f1 = baseInput();
    f1.band = { enabled: false, label: '' };
    f1.prefix = { enabled: false, front: '', back: '' };
    const f2 = baseInput();
    f2.band = { enabled: false, label: 'g05' };
    f2.prefix = { enabled: false, front: 'g02', back: 'g03' };
    expect(initialLayoutFingerprint(n)).toBe(initialLayoutFingerprint(f1));
    expect(initialLayoutFingerprint(n)).toBe(initialLayoutFingerprint(f2));
  });

  it('sizes 勾选序无关（[28,34] ≡ [34,28]）', () => {
    const a = baseInput();
    const b = baseInput();
    b.sizes = [34, 28];
    expect(initialLayoutFingerprint(a)).toBe(initialLayoutFingerprint(b));
  });

  it('开启态组件入指纹：band label / prefix front·back 变更 → 不同串', () => {
    const a = baseInput();
    a.band = { enabled: true, label: 'g05' };
    a.prefix = { enabled: true, front: 'g02', back: 'g03' };
    const b = baseInput();
    b.band = { enabled: true, label: 'g06' };
    b.prefix = { enabled: true, front: 'g02', back: 'g04' };
    expect(initialLayoutFingerprint(a)).not.toBe(initialLayoutFingerprint(b));
  });
});

describe('isStale (初始布局 US-004)', () => {
  /** 保存一份基线指纹的 saved 布局（最小合法形态）。 */
  function saveBaseline(): string {
    const fp = initialLayoutFingerprint(baseInput());
    useInitialLayoutStore.getState().setSaved({
      displayPlaced: [{ id: 'g01_28', rotation: 0, translation: [0, 0] }],
      warmPlaced: [{ id: 'g01_28', rotation: 0, translation: [0, 0] }],
      demandMap: null,
      fingerprint: fp,
      widthMm: 600,
      bandUsed: false,
      prefixUsed: false,
    });
    return fp;
  }

  it('同指纹 → false（不失效）', () => {
    const fp = saveBaseline();
    expect(useInitialLayoutStore.getState().isStale(fp)).toBe(false);
  });

  it('saved 缺席 → true（无可新鲜态）', () => {
    expect(
      useInitialLayoutStore.getState().isStale(initialLayoutFingerprint(baseInput())),
    ).toBe(true);
  });

  it('七组件任一变更判 true：sizes / per_type / quantities / params / gate_mm / band / prefix', () => {
    const fp = saveBaseline();
    const drifts: InitialLayoutFingerprintInput[] = [];
    const d1 = baseInput(); d1.sizes = [28];
    const d2 = baseInput(); d2.per_type = { g01: { d: 3 } };
    const d3 = baseInput(); d3.quantities = { g01: { '28': 3, '34': 1 } };
    const d4 = baseInput(); d4.params = { ...PARAMS, d_ext: 1 };
    const d5 = baseInput(); d5.gate_mm = 1980;
    const d6 = baseInput(); d6.band = { enabled: true, label: 'g05' };
    const d7 = baseInput(); d7.prefix = { enabled: true, front: 'g02', back: 'g03' };
    drifts.push(d1, d2, d3, d4, d5, d6, d7);
    expect(drifts).toHaveLength(7);
    for (const d of drifts) {
      expect(useInitialLayoutStore.getState().isStale(initialLayoutFingerprint(d))).toBe(true);
    }
    // 对照：原指纹仍 false（drift 不污染 saved）
    expect(useInitialLayoutStore.getState().isStale(fp)).toBe(false);
  });
});

describe('setSaved / clear / 轻量写入器', () => {
  it('setSaved 落态 + 清空 error；clear 只清 saved（genSeed 保留续增）', () => {
    const st = useInitialLayoutStore.getState();
    st.setError('生成失败');
    expect(useInitialLayoutStore.getState().error).toBe('生成失败');
    st.setSaved({
      displayPlaced: [],
      warmPlaced: [],
      demandMap: { WB_g05: 1 },
      fingerprint: 'fp',
      widthMm: 700,
      bandUsed: true,
      prefixUsed: false,
    });
    const s1 = useInitialLayoutStore.getState();
    expect(s1.saved).not.toBeNull();
    expect(s1.saved!.fingerprint).toBe('fp');
    expect(s1.saved!.demandMap).toEqual({ WB_g05: 1 });
    expect(s1.saved!.bandUsed).toBe(true);
    expect(s1.saved!.prefixUsed).toBe(false);
    expect(s1.saved!.widthMm).toBe(700);
    expect(s1.error).toBeNull(); // 保存成功清 error
    useInitialLayoutStore.getState().bumpGenSeed(); // genSeed 0→1
    useInitialLayoutStore.getState().clear();
    const s2 = useInitialLayoutStore.getState();
    expect(s2.saved).toBeNull();
    expect(s2.genSeed).toBe(1); // clear 不动 genSeed
    expect(s2.isStale('fp')).toBe(true); // cleared → stale
  });

  it('bumpGenSeed 递增并返回新值；setGenerating / setError 写入', () => {
    const st = useInitialLayoutStore.getState();
    expect(st.bumpGenSeed()).toBe(1);
    expect(st.bumpGenSeed()).toBe(2);
    expect(useInitialLayoutStore.getState().genSeed).toBe(2);
    st.setGenerating(true);
    expect(useInitialLayoutStore.getState().generating).toBe(true);
    st.setError(null);
    expect(useInitialLayoutStore.getState().error).toBeNull();
  });
});

describe('probeCapability (App 启动拉一次)', () => {
  let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
  let warmCalls = 0;
  /** 当前 mock 回包（用例内覆写）。 */
  const CURRENT: { capability: unknown } = { capability: { supported: true, version: '0.9.0+ms1' } };

  beforeEach(() => {
    warmCalls = 0;
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown) => {
      if (String(input).includes('/api/warm-capability')) {
        warmCalls += 1;
        return Promise.resolve(
          new Response(JSON.stringify(CURRENT.capability), { status: 200 }),
        );
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
    }) as (...args: unknown[]) => Promise<Response>);
  });

  afterEach(() => {
    fetchSpy?.mockRestore();
    fetchSpy = null;
  });

  it('成功落定 supported + 幂等短路（二次调用不再发）', async () => {
    CURRENT.capability = { supported: false, version: '0.9.0' };
    await useInitialLayoutStore.getState().probeCapability();
    expect(useInitialLayoutStore.getState().supported).toBe(false);
    await useInitialLayoutStore.getState().probeCapability();
    expect(warmCalls).toBe(1); // 已落定 → 短路
  });

  it('探测失败（形态异常）→ 保持 null，下次调用可重试', async () => {
    CURRENT.capability = { version: '0.9.0' }; // 缺 supported → fetchWarmCapability 抛
    await useInitialLayoutStore.getState().probeCapability();
    expect(useInitialLayoutStore.getState().supported).toBeNull();
    expect(warmCalls).toBe(1);
    CURRENT.capability = { supported: true, version: '0.9.0+ms1' };
    await useInitialLayoutStore.getState().probeCapability(); // null 未落定 → 可重试
    expect(useInitialLayoutStore.getState().supported).toBe(true);
    expect(warmCalls).toBe(2);
  });
});
