// US-005 useStrategyPoll 单测（fake fetch + fake timers）：
//   - mount / open 翻转 → 立即 refresh 一次（页面刷新恢复进度的入口）
//   - 活性态 open=true → 2s 周期（1999ms 不刷 / +1ms 刷）
//   - 活性态 open=false → 15s 低频（关弹窗维持入口徽标）
//   - 终态（done）→ 停轮询（60s 无新 status 请求）+ done 后 result 恰拉一次

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react';
import { useStrategyPoll } from '../useStrategyPoll';
import { useStrategyStore } from '../../store/strategyStore';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
let statusPayload: unknown = { state: 'idle' };
let resultPayload: unknown = null;

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

function statusCalls(): number {
  return fetchSpy!.mock.calls.filter((c: unknown[]) => String(c[0]).includes('/api/strategy/status')).length;
}

function resultCalls(): number {
  return fetchSpy!.mock.calls.filter((c: unknown[]) => String(c[0]).includes('/api/strategy/result')).length;
}

let container: HTMLDivElement | null = null;
let root: Root | null = null;

function renderProbe(open: boolean): void {
  act(() => {
    root!.render(<Probe open={open} />);
  });
}

function Probe({ open }: { open: boolean }): null {
  useStrategyPoll(open);
  return null;
}

beforeEach(() => {
  vi.useFakeTimers();
  useStrategyStore.getState().reset();
  statusPayload = { state: 'idle' };
  resultPayload = null;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input: unknown) => {
    const url = String(input);
    if (url.includes('/api/strategy/status')) return Promise.resolve(json(statusPayload));
    if (url.includes('/api/strategy/result')) {
      return Promise.resolve(resultPayload === null ? json({}, 404) : json(resultPayload));
    }
    return Promise.resolve(json({}));
  }) as unknown as MockInstance<(...args: unknown[]) => Promise<Response>>;
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
  container = null;
  vi.useRealTimers();
  fetchSpy?.mockRestore();
  fetchSpy = null;
  useStrategyStore.getState().reset();
});

describe('useStrategyPoll (US-005)', () => {
  it('mount 立即 refresh 一次；open 翻转再立即 refresh（恢复进度入口）', async () => {
    statusPayload = { state: 'running', mode: 'race' };
    renderProbe(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(statusCalls()).toBe(1);
    expect(useStrategyStore.getState().phase).toBe('running');

    renderProbe(true); // 关 → 开
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(statusCalls()).toBe(2);
  });

  it('活性态 open=true → 2s 周期（1999ms 不刷，+1ms 刷）', async () => {
    statusPayload = { state: 'running', mode: 'race' };
    renderProbe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(statusCalls()).toBe(1); // mount refresh

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(statusCalls()).toBe(1); // 2s 未到不刷

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(statusCalls()).toBe(2); // 2s 到点刷
  });

  it('活性态 open=false → 15s 低频（14.9s 不刷，15s 刷 —— 维持入口徽标）', async () => {
    statusPayload = { state: 'running', mode: 'race' };
    renderProbe(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(statusCalls()).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(14999);
    });
    expect(statusCalls()).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(statusCalls()).toBe(2);
  });

  it('终态（done）停轮询 + done 后 result 恰拉一次', async () => {
    statusPayload = { state: 'done', mode: 'race' };
    resultPayload = { state: 'done', best: { density: 0.88 }, summary: { per_seed: [], mode: 'race' } };
    renderProbe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(useStrategyStore.getState().phase).toBe('done');
    expect(resultCalls()).toBe(1); // done → result 拉一次

    // 终态 60s 无任何新请求（轮询已停；result 不重复拉）。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(statusCalls()).toBe(1);
    expect(resultCalls()).toBe(1);
  });

  it('idle 终态不建轮询（mount refresh 后 60s 无新请求）', async () => {
    statusPayload = { state: 'idle' };
    renderProbe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(useStrategyStore.getState().phase).toBe('idle');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(statusCalls()).toBe(1);
  });
});
