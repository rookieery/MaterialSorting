// US-005 strategyStore 单测：状态机 + 四路由 fetch 契约。
//   - start 202 → POST /api/strategy/start（载荷逐字段）+ 立即 refresh → running
//   - start 409 → phase error + 后端 error 文案透传
//   - refresh 映射 status.state（running / orphan；非法载荷不动 phase）
//   - refresh done → 拉 result 恰一次（result 非 null 后不再拉）
//   - stop → POST /api/strategy/stop + refresh 收敛 stopped
//   - reset 全清回 idle

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { useStrategyStore } from '../strategyStore';
import type { StrategyResult, StrategyStatus } from '../../types/strategy';

let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
let statusPayload: unknown = { state: 'idle' };
let resultPayload: unknown = null;
let startStatus = 202;
let startBodies: unknown[] = [];
let stopCalls = 0;

const RESULT: StrategyResult = {
  state: 'done',
  mode: 'race',
  run_dir: 'out/config_runs/web_race_x_1',
  manifest: { gate_mm: 1980, total_area_mm2: 1e6, n_eroded: 0, pieces: [] },
  best: {
    seed: 3, frame_index: 5, elapsed: 120.5, density: 0.8838,
    density_sparrow: 0.9, width_mm: 7100.5, placed_items: [],
  },
  summary: { per_seed: [], mode: 'race', race: { gate_seconds: 90, kept_seeds: [0], gated_seeds: [1, 2] } },
};

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

beforeEach(() => {
  useStrategyStore.getState().reset();
  statusPayload = { state: 'idle' };
  resultPayload = null;
  startStatus = 202;
  startBodies = [];
  stopCalls = 0;
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/api/strategy/start')) {
      startBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      if (startStatus !== 202) {
        return Promise.resolve(json({ error: START_ERROR_TEXT }, startStatus));
      }
      return Promise.resolve(json({ started: true, pid: 4321, mode: 'race', minutes: 20, run_name: 'web_race_x' }, 202));
    }
    if (url.includes('/api/strategy/stop')) {
      stopCalls += 1;
      return Promise.resolve(json({ stopped: true, pid: 4321 }));
    }
    if (url.includes('/api/strategy/status')) {
      return Promise.resolve(json(statusPayload));
    }
    if (url.includes('/api/strategy/result')) {
      return Promise.resolve(resultPayload === null ? json({ error: 'no result' }, 404) : json(resultPayload));
    }
    return Promise.resolve(json({}));
  }) as (...args: unknown[]) => Promise<Response>);
});

/** 409 时返回的后端 error 文案（用例可覆写）。 */
let START_ERROR_TEXT = '已有进行中的策略运行（或检测到遗留 marker），请先停止/清理';

afterEach(() => {
  fetchSpy?.mockRestore();
  fetchSpy = null;
});

function resultFetchCount(): number {
  return fetchSpy!.mock.calls.filter((c: unknown[]) => String(c[0]).includes('/api/strategy/result')).length;
}

describe('strategyStore (US-005)', () => {
  it('start 202 → POST /api/strategy/start 载荷逐字段 + 立即 refresh → running', async () => {
    statusPayload = { state: 'running', mode: 'race', total_budget_sec: 1200, elapsed_sec: 3.2 } as StrategyStatus;
    await useStrategyStore.getState().start({
      mode: 'race', minutes: 20, seed: 7, gate_mm: 1980,
      sizes: [30, 32], per_type: { g01: { d: 2 } }, quantities: { g01: { '30': 2 } },
    });
    expect(startBodies).toHaveLength(1);
    expect(startBodies[0]).toEqual({
      mode: 'race', minutes: 20, seed: 7, gate_mm: 1980,
      sizes: [30, 32], per_type: { g01: { d: 2 } }, quantities: { g01: { '30': 2 } },
    });
    const s = useStrategyStore.getState();
    expect(s.phase).toBe('running');
    expect(s.lastStart?.minutes).toBe(20);
    expect(s.errorMessage).toBeNull();
  });

  it('start 409 → phase error + 后端 error 文案透传', async () => {
    startStatus = 409;
    await useStrategyStore.getState().start({ mode: 'race', minutes: 10, seed: 0, gate_mm: 1980 });
    const s = useStrategyStore.getState();
    expect(s.phase).toBe('error');
    expect(s.errorMessage).toContain('已有进行中的策略运行');
  });

  it('refresh 映射 status.state（running / orphan；非法载荷不动 phase）', async () => {
    statusPayload = { state: 'running', mode: 'se' } as StrategyStatus;
    await useStrategyStore.getState().refresh();
    expect(useStrategyStore.getState().phase).toBe('running');
    expect(useStrategyStore.getState().status?.mode).toBe('se');

    statusPayload = { state: 'orphan', alive: true, pid: 4321 } as StrategyStatus;
    await useStrategyStore.getState().refresh();
    expect(useStrategyStore.getState().phase).toBe('orphan');

    // 非法载荷（无 state 字段 —— mock fetch 场景）→ 保留上一状态不炸。
    statusPayload = { representatives: {} };
    await useStrategyStore.getState().refresh();
    expect(useStrategyStore.getState().phase).toBe('orphan');
  });

  it('refresh done → 拉 result 恰一次（后续 refresh 不重复拉）', async () => {
    resultPayload = RESULT;
    statusPayload = { state: 'done', mode: 'race' } as StrategyStatus;
    await useStrategyStore.getState().refresh();
    const s1 = useStrategyStore.getState();
    expect(s1.phase).toBe('done');
    expect(s1.result?.best.density).toBe(0.8838);
    expect(resultFetchCount()).toBe(1);

    await useStrategyStore.getState().refresh();
    await useStrategyStore.getState().refresh();
    expect(resultFetchCount()).toBe(1);
    expect(useStrategyStore.getState().result).toEqual(RESULT);
  });

  it('stop → POST /api/strategy/stop + refresh 收敛 stopped（顺手拉 result）', async () => {
    resultPayload = RESULT;
    statusPayload = { state: 'stopped', mode: 'race' } as StrategyStatus;
    await useStrategyStore.getState().stop();
    expect(stopCalls).toBe(1);
    const s = useStrategyStore.getState();
    expect(s.phase).toBe('stopped');
    expect(s.result).not.toBeNull();
  });

  it('reset 全清回 idle（result / lastStart / errorMessage）', async () => {
    resultPayload = RESULT;
    statusPayload = { state: 'done' } as StrategyStatus;
    await useStrategyStore.getState().refresh();
    expect(useStrategyStore.getState().result).not.toBeNull();
    useStrategyStore.getState().reset();
    const s = useStrategyStore.getState();
    expect(s.phase).toBe('idle');
    expect(s.status).toBeNull();
    expect(s.result).toBeNull();
    expect(s.lastStart).toBeNull();
    expect(s.errorMessage).toBeNull();
  });

  it('reset 使在飞 refresh 失效（再次运行后过期 done 响应不回写 —— reset 是终审）', async () => {
    // 场景：server 内存终态 done（上一 run result 常驻）；开弹窗触发 refresh（在飞），
    // 用户立刻点「再次运行」（reset）→ 在飞响应落地必须被丢弃，否则弹窗被拽回结果态。
    let releaseStatus: (() => void) | null = null;
    fetchSpy!.mockImplementation(((input: unknown) => {
      const url = String(input);
      if (url.includes('/api/strategy/status')) {
        return new Promise<Response>((resolve) => {
          releaseStatus = () => resolve(json({ state: 'done', mode: 'race' } as StrategyStatus));
        });
      }
      return Promise.resolve(json({}));
    }) as (...args: unknown[]) => Promise<Response>);
    resultPayload = RESULT;

    const p = useStrategyStore.getState().refresh(); // 在飞（未 resolve）
    useStrategyStore.getState().reset(); // 「再次运行」
    releaseStatus!(); // 过期响应此刻才落地
    await p;
    await Promise.resolve();

    const s = useStrategyStore.getState();
    expect(s.phase).toBe('idle'); // 不被 done 回写
    expect(s.status).toBeNull();
    expect(s.result).toBeNull(); // 连带 result 拉取也被代际号挡住
  });
});

// ============================================================
// US-002：resultApplied 生命周期 + refresh idle 采纳守卫（恢复路径必要条件）
// ============================================================

describe('strategyStore：resultApplied 生命周期（US-002）', () => {
  it('初值 false；done 结果拉取落定后仍 false；markResultApplied 置位', async () => {
    expect(useStrategyStore.getState().resultApplied).toBe(false);
    resultPayload = RESULT;
    statusPayload = { state: 'done', mode: 'race' } as StrategyStatus;
    await useStrategyStore.getState().refresh();
    expect(useStrategyStore.getState().resultApplied).toBe(false); // 落定 ≠ 应用
    useStrategyStore.getState().markResultApplied();
    expect(useStrategyStore.getState().resultApplied).toBe(true);
    // 重复置位幂等
    useStrategyStore.getState().markResultApplied();
    expect(useStrategyStore.getState().resultApplied).toBe(true);
  });

  it('start 清 resultApplied（随 result:null 一起）；reset 同清', async () => {
    resultPayload = RESULT;
    statusPayload = { state: 'done', mode: 'race' } as StrategyStatus;
    await useStrategyStore.getState().refresh();
    useStrategyStore.getState().markResultApplied();

    // 新 run 后端槽已空（新 run 进行中/已结束由后续 status 决定 —— 此处 idle 即
    // 「start 清 result」的最小验证面）
    statusPayload = { state: 'idle' };
    await useStrategyStore.getState().start({ mode: 'race', minutes: 10, seed: 0, gate_mm: 1980 });
    expect(useStrategyStore.getState().result).toBeNull();
    expect(useStrategyStore.getState().resultApplied).toBe(false);

    useStrategyStore.getState().reset();
    expect(useStrategyStore.getState().result).toBeNull();
    expect(useStrategyStore.getState().resultApplied).toBe(false);
  });
});

describe('strategyStore：refresh idle 采纳守卫（US-002 恢复写回态）', () => {
  it('恢复态（result 在场 + phase=done）→ idle 不降级（新 sid 后端槽空恒见 idle）', async () => {
    // 模拟 applyRestorePayload 第 6 步写回（store 直写，恢复路径同构）
    useStrategyStore.setState({
      phase: 'done',
      status: null,
      result: RESULT,
      resultApplied: false,
      errorMessage: null,
      lastStart: null,
    });
    statusPayload = { state: 'idle' };
    await useStrategyStore.getState().refresh();
    const s = useStrategyStore.getState();
    // 不被 idle 打回：弹窗结果态保住
    expect(s.phase).toBe('done');
    expect(s.result).toEqual(RESULT);
    expect(s.status).toBeNull(); // idle 载荷不写回（status null = 结果态渲染不受扰）
    // 也不触发 result 重复拉取（恢复写回的 result 即真相）
    expect(resultFetchCount()).toBe(0);
  });

  it('result===null 的 stuck starting → idle 既有恢复出口不变（守卫只护 result 在场者）', async () => {
    useStrategyStore.setState({ phase: 'starting', status: null, result: null });
    statusPayload = { state: 'idle' };
    await useStrategyStore.getState().refresh();
    expect(useStrategyStore.getState().phase).toBe('idle');
  });

  it('result 在场但 phase≠done（stopped 常驻）→ idle 照常采纳（守卫窄门：仅恢复写回态）', async () => {
    useStrategyStore.setState({
      phase: 'stopped',
      status: null,
      result: { ...RESULT, state: 'stopped' },
    });
    statusPayload = { state: 'idle' };
    await useStrategyStore.getState().refresh();
    expect(useStrategyStore.getState().phase).toBe('idle');
  });
});
