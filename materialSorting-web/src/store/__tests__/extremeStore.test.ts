// US-003 extremeStore 单测（族参数化工厂 createRunStore 的极限族实例）：
//   - start 202 → POST /api/extreme/start（time_total_s 秒载荷；band/prefix 可选键
//     由弹窗层组装，2026-08-30 起支持透传，store 层不感知）
//     + 立即 refresh → running
//   - start 409 → phase error + 后端 error 文案透传（互斥文案区分对方）
//   - refresh 族过滤：/api/extreme/status 报对方族 run（mode se/race/缺失）不进
//     phase；mode='extreme' 正常采纳；idle 恒采纳（恢复出口）
//   - refresh done → 拉 /api/extreme/result 恰一次
//   - stop → POST /api/extreme/stop + refresh 收敛 stopped
//   - reset 全清回 idle

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { useExtremeStore, useStrategyStore } from '../strategyStore';
import type { StrategyResult, StrategyStatus } from '../../types/strategy';

let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
let statusPayload: unknown = { state: 'idle' };
let resultPayload: unknown = null;
let startStatus = 202;
let startBodies: unknown[] = [];
let stopCalls = 0;

const RESULT: StrategyResult = {
  state: 'done',
  mode: 'extreme',
  run_dir: 'out/config_runs/web_extreme_x_1',
  manifest: { gate_mm: 1980, total_area_mm2: 1e6, n_eroded: 0, pieces: [] },
  best: {
    seed: 3, frame_index: 5, elapsed: 120.5, density: 0.8838,
    density_sparrow: 0.9, width_mm: 7100.5, placed_items: [],
  },
  summary: { per_seed: [], mode: 'race', race: { gate_seconds: 300, kept_seeds: [0], gated_seeds: [1, 2] } },
};

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

beforeEach(() => {
  useExtremeStore.getState().reset();
  statusPayload = { state: 'idle' };
  resultPayload = null;
  startStatus = 202;
  startBodies = [];
  stopCalls = 0;
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/api/extreme/start')) {
      startBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      if (startStatus !== 202) {
        return Promise.resolve(json({ error: START_409_TEXT }, startStatus));
      }
      return Promise.resolve(json({ started: true, pid: 8642, mode: 'extreme', run_name: 'web_extreme_x', time_total_s: 7200 }, 202));
    }
    if (url.includes('/api/extreme/stop')) {
      stopCalls += 1;
      return Promise.resolve(json({ stopped: true, pid: 8642 }));
    }
    if (url.includes('/api/extreme/status')) {
      return Promise.resolve(json(statusPayload));
    }
    if (url.includes('/api/extreme/result')) {
      return Promise.resolve(resultPayload === null ? json({ error: 'no result' }, 404) : json(resultPayload));
    }
    return Promise.resolve(json({}));
  }) as (...args: unknown[]) => Promise<Response>);
});

/** 409 时返回的后端互斥文案（与 web/strategy.py US-002 逐字节一致）。 */
const START_409_TEXT = '已有进行中的极限运行（或检测到遗留 marker），请先停止/清理';

afterEach(() => {
  fetchSpy?.mockRestore();
  fetchSpy = null;
});

function resultFetchCount(): number {
  return fetchSpy!.mock.calls.filter((c: unknown[]) => String(c[0]).includes('/api/extreme/result')).length;
}

describe('extremeStore (US-003)', () => {
  it('start 202 → POST /api/extreme/start 载荷逐字段（time_total_s 秒）+ 立即 refresh → running', async () => {
    statusPayload = { state: 'running', mode: 'extreme', total_budget_sec: 7200, elapsed_sec: 3.2 } as StrategyStatus;
    await useExtremeStore.getState().start({
      time_total_s: 7200, seed: 7, gate_mm: 1980,
      sizes: [30, 32], per_type: { g01: { d: 2 } }, quantities: { g01: { '30': 2 } },
    });
    expect(startBodies).toHaveLength(1);
    expect(startBodies[0]).toEqual({
      time_total_s: 7200, seed: 7, gate_mm: 1980,
      sizes: [30, 32], per_type: { g01: { d: 2 } }, quantities: { g01: { '30': 2 } },
    });
    const s = useExtremeStore.getState();
    expect(s.phase).toBe('running');
    expect(s.lastStart?.time_total_s).toBe(7200);
    expect(s.errorMessage).toBeNull();
  });

  it('start 409 → phase error + 后端互斥文案透传（区分对方 = 极限运行）', async () => {
    startStatus = 409;
    await useExtremeStore.getState().start({ time_total_s: 3600, seed: 0, gate_mm: 1980 });
    const s = useExtremeStore.getState();
    expect(s.phase).toBe('error');
    expect(s.errorMessage).toContain('已有进行中的极限运行');
  });

  it('refresh 族过滤：对方族 run（mode se/race/缺失）不进本族 phase；mode=extreme 采纳；idle 恒采纳', async () => {
    statusPayload = { state: 'running', mode: 'race' } as StrategyStatus;
    await useExtremeStore.getState().refresh();
    expect(useExtremeStore.getState().phase).toBe('idle');

    statusPayload = { state: 'running', mode: 'se' } as StrategyStatus;
    await useExtremeStore.getState().refresh();
    expect(useExtremeStore.getState().phase).toBe('idle');

    statusPayload = { state: 'orphan', alive: true, pid: 4321 } as StrategyStatus;
    await useExtremeStore.getState().refresh();
    expect(useExtremeStore.getState().phase).toBe('idle');

    statusPayload = { state: 'running', mode: 'extreme' } as StrategyStatus;
    await useExtremeStore.getState().refresh();
    expect(useExtremeStore.getState().phase).toBe('running');

    statusPayload = { state: 'idle' };
    await useExtremeStore.getState().refresh();
    expect(useExtremeStore.getState().phase).toBe('idle');
    expect(useExtremeStore.getState().status?.state).toBe('idle');
  });

  it('反向：策略族 refresh 同样忽略 extreme run（族过滤对称）', async () => {
    const calls: string[] = [];
    fetchSpy!.mockImplementation(((input: unknown) => {
      const url = String(input);
      calls.push(url);
      if (url.includes('/api/strategy/status')) {
        return Promise.resolve(json({ state: 'running', mode: 'extreme' }));
      }
      return Promise.resolve(json({}));
    }) as (...args: unknown[]) => Promise<Response>);
    await useStrategyStore.getState().refresh();
    expect(useStrategyStore.getState().phase).toBe('idle');
    expect(calls.some((u) => u.includes('/api/strategy/status'))).toBe(true);
  });

  it('refresh done → 拉 /api/extreme/result 恰一次（后续 refresh 不重复拉）', async () => {
    resultPayload = RESULT;
    statusPayload = { state: 'done', mode: 'extreme' } as StrategyStatus;
    await useExtremeStore.getState().refresh();
    const s1 = useExtremeStore.getState();
    expect(s1.phase).toBe('done');
    expect(s1.result?.mode).toBe('extreme');
    expect(resultFetchCount()).toBe(1);

    await useExtremeStore.getState().refresh();
    await useExtremeStore.getState().refresh();
    expect(resultFetchCount()).toBe(1);
    expect(useExtremeStore.getState().result).toEqual(RESULT);
  });

  it('stop → POST /api/extreme/stop + refresh 收敛 stopped（顺手拉 result）', async () => {
    resultPayload = RESULT;
    statusPayload = { state: 'stopped', mode: 'extreme' } as StrategyStatus;
    await useExtremeStore.getState().stop();
    expect(stopCalls).toBe(1);
    const s = useExtremeStore.getState();
    expect(s.phase).toBe('stopped');
    expect(s.result).not.toBeNull();
  });

  it('reset 全清回 idle（result / lastStart / errorMessage）', async () => {
    resultPayload = RESULT;
    statusPayload = { state: 'done', mode: 'extreme' } as StrategyStatus;
    await useExtremeStore.getState().refresh();
    expect(useExtremeStore.getState().result).not.toBeNull();
    useExtremeStore.getState().reset();
    const s = useExtremeStore.getState();
    expect(s.phase).toBe('idle');
    expect(s.status).toBeNull();
    expect(s.result).toBeNull();
    expect(s.errorMessage).toBeNull();
    expect(s.lastStart).toBeNull();
  });
});
