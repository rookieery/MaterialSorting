// US-027 stop() + phase 状态机测试：
//   1) stop() 对每个 open WS 发 {action:"stop"}（非 OPEN 跳过）
//   2) 收到 {type:"stopped"} 后 finish 触发、rec.stopped===true、onDone 调一次
//   3) NestingPage phase 转换：running->(stop)->stopped / running->(error)->error / running->(final)->done
//   4) running 态冻结参数编辑（SizePicker/ParamForm/MultiSeed/PerType 均 disabled）
//
// 复用 useSolveRun.test.tsx 的 MockWS 模式，额外补 readyState 字段（stop() 仅对 OPEN 发）。

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { StrictMode, useEffect, type MutableRefObject } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { useSolveRun, type StartConfig } from '../hooks/useSolveRun';
import { runRegistry } from '../store/runRegistry';
import { NestingPage } from '../components/NestingPage';
import { useUploadStore } from '../store/uploadStore';
import type { ServerMsg } from '../types/ws';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---- Mock WebSocket（含 readyState，供 stop() 判 OPEN）----
interface MockWS {
  url: string;
  readyState: number;
  onopen: ((ev?: unknown) => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  onclose: ((ev?: unknown) => void) | null;
  onerror: ((ev?: unknown) => void) | null;
  sent: string[];
  send: (data: string) => void;
  close: () => void;
}
const mockInstances: MockWS[] = [];

function makeMockWS(url: string): MockWS {
  const inst: MockWS = {
    url,
    readyState: 1,
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    sent: [],
    send(data: string) {
      inst.sent.push(data);
    },
    close() {
      inst.readyState = 3;
      inst.onclose?.();
    },
  };
  mockInstances.push(inst);
  return inst;
}

class MockWebSocketCtor {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  constructor(url: string) {
    return makeMockWS(url) as unknown as WebSocket;
  }
}

let realWS: typeof WebSocket | undefined;
let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;

beforeEach(() => {
  mockInstances.length = 0;
  realWS = globalThis.WebSocket;
  (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket =
    MockWebSocketCtor as unknown as typeof WebSocket;
  runRegistry.clear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((_input: unknown) =>
    Promise.resolve(
      new Response(JSON.stringify({ representatives: {} }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  ) as unknown as MockInstance<(...args: unknown[]) => Promise<Response>>;
});

afterEach(() => {
  if (realWS !== undefined) {
    (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket = realWS;
  }
  runRegistry.clear();
  if (root) {
    const r = root;
    act(() => {
      r.unmount();
    });
    root = null;
  }
  container?.remove();
  container = null;
  if (fetchSpy) {
    fetchSpy.mockRestore();
    fetchSpy = null;
  }
});

function mountHook(
  callbacks: Parameters<typeof useSolveRun>[0] = {},
): MutableRefObject<ReturnType<typeof useSolveRun>> {
  const ref: MutableRefObject<ReturnType<typeof useSolveRun>> = {
    current: { start: () => {}, stop: () => {}, isStarted: false },
  };
  function Probe() {
    const api = useSolveRun(callbacks);
    useEffect(() => {
      ref.current = api;
    });
    return null;
  }
  act(() => {
    root?.render(
      <StrictMode>
        <Probe />
      </StrictMode>,
    );
  });
  return ref;
}

const BASE_CFG: StartConfig = {
  sizes: [30],
  time: 1,
  seed: 0,
  gate_mm: 1980,
  params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
};

describe('US-027 useSolveRun.stop + case stopped', () => {
  it('1) stop() 对每个 readyState===OPEN 的 WS 发 {action:stop}；非 OPEN 跳过', () => {
    const ref = mountHook({});
    act(() => ref.current.start({ ...BASE_CFG, seed: 1 }));
    act(() => ref.current.start({ ...BASE_CFG, seed: 2 }));
    expect(mockInstances).toHaveLength(2);

    mockInstances[0].readyState = 3; // CLOSED

    act(() => ref.current.stop());

    expect(mockInstances[0].sent).toEqual([]);
    expect(mockInstances[1].sent).toHaveLength(1);
    const parsed = JSON.parse(mockInstances[1].sent[0]);
    expect(parsed).toEqual({ action: 'stop' });
  });

  it('2) 收到 {type:stopped} -> rec.stopped===true + finish 触发 onDone（仅一次）', () => {
    const onDone = vi.fn();
    const ref = mountHook({ onDone });
    act(() => ref.current.start(BASE_CFG));
    const ws = mockInstances[0];

    const frame: ServerMsg = {
      type: 'frame',
      index: 0,
      elapsed: 0.5,
      phase: 'exploring',
      density: 0.4,
      density_sparrow: 0.42,
      width_mm: 1200,
      placed_items: [],
    };
    const stopped: ServerMsg = { type: 'stopped', reason: 'user_requested' };

    act(() => {
      ws.onmessage?.({ data: JSON.stringify(frame) });
      ws.onmessage?.({ data: JSON.stringify(stopped) });
    });

    const rec = runRegistry.list()[0];
    expect(rec.stopped).toBe(true);
    expect(rec.done).toBe(true);
    expect(rec.error).toBeNull();
    expect(rec.lastFrame).not.toBeNull();
    expect(rec.frames).toHaveLength(1);
    expect(rec.finalDensity).toBe(0);
    expect(onDone).toHaveBeenCalledTimes(1);
    act(() => ws.onclose?.());
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});

function mountNestingPage(): void {
  act(() => {
    root?.render(
      <StrictMode>
        <NestingPage />
      </StrictMode>,
    );
  });
}

function startSolveViaPanel(): void {
  const checkbox = container!.querySelector<HTMLInputElement>('.sizes input[type=checkbox]')!;
  act(() => checkbox.click());
  const btn = container!.querySelector<HTMLButtonElement>('#start')!;
  act(() => btn.click());
}

function statusText(): string {
  return container!.querySelector<HTMLElement>('#status')!.textContent ?? '';
}

describe('US-027 NestingPage phase 转换', () => {
  beforeEach(() => {
    useUploadStore.getState().reset();
    mountNestingPage();
  });

  it('3a) running->(stopped)->stopped：状态行含「已停止」+ #stop 切 #restart（US-028 SolveControls）', () => {
    startSolveViaPanel();
    expect(mockInstances).toHaveLength(1);
    // US-028：running 态 SolveControls 渲染 #stop（不渲染 #start）
    expect(container!.querySelector('#start')).toBeNull();
    const stopBtn = container!.querySelector<HTMLButtonElement>('#stop')!;
    expect(stopBtn).not.toBeNull();
    expect(stopBtn.disabled).toBe(false);

    const ws = mockInstances[0];
    const stopped: ServerMsg = { type: 'stopped', reason: 'user_requested' };
    act(() => ws.onmessage?.({ data: JSON.stringify(stopped) }));

    // stopped 态 SolveControls 渲染 #restart「开始求解」（文案与 idle 统一）
    expect(container!.querySelector('#stop')).toBeNull();
    const restartBtn = container!.querySelector<HTMLButtonElement>('#restart')!;
    expect(restartBtn).not.toBeNull();
    expect(restartBtn.textContent).toBe('开始求解');
    expect(statusText()).toContain('已停止');
    expect(statusText()).toContain('中间方案');
  });

  it('3b) running->(error)->error：状态行含「错误」+ #restart 切「重新开始」', () => {
    startSolveViaPanel();
    const ws = mockInstances[0];
    act(() =>
      ws.onmessage?.({ data: JSON.stringify({ type: 'error', message: '构造失败' }) }),
    );
    // error 态 SolveControls 渲染 #restart「开始求解」
    const restartBtn = container!.querySelector<HTMLButtonElement>('#restart')!;
    expect(restartBtn).not.toBeNull();
    expect(restartBtn.textContent).toBe('开始求解');
    expect(statusText()).toContain('错误');
    expect(statusText()).toContain('构造失败');
  });

  it('3c) running->(final)->done：状态行含「完成」+ density + #restart 切「再次求解」', () => {
    startSolveViaPanel();
    const ws = mockInstances[0];
    const finalMsg: ServerMsg = {
      type: 'final',
      density: 0.78,
      density_sparrow: 0.8,
      width_mm: 900,
      elapsed: 1.2,
      n_frames: 3,
      n_eroded: 0,
    };
    act(() => ws.onmessage?.({ data: JSON.stringify(finalMsg) }));
    // done 态 SolveControls 渲染 #restart「开始求解」（文案统一）
    const restartBtn = container!.querySelector<HTMLButtonElement>('#restart')!;
    expect(restartBtn).not.toBeNull();
    expect(restartBtn.textContent).toBe('开始求解');
    expect(statusText()).toContain('完成');
    expect(statusText()).toContain('78.00%');
  });

  it('3d) running 态冻结参数编辑（SizePicker/ParamForm/MultiSeed/PerType 均 disabled）', () => {
    expect(container!.querySelector<HTMLInputElement>('#time')!.disabled).toBe(false);
    expect(container!.querySelector<HTMLInputElement>('#seed')!.disabled).toBe(false);
    expect(container!.querySelector<HTMLInputElement>('#multi_seed')!.disabled).toBe(false);
    expect(container!.querySelector<HTMLInputElement>('#seed_count')!.disabled).toBe(false);
    expect(container!.querySelector<HTMLButtonElement>('.per-type-btn')!.disabled).toBe(false);
    const sizeInput = container!.querySelectorAll<HTMLInputElement>('.sizes input[type=checkbox]')[0]!;
    expect(sizeInput.disabled).toBe(false);

    startSolveViaPanel();

    expect(container!.querySelector<HTMLInputElement>('#time')!.disabled).toBe(true);
    expect(container!.querySelector<HTMLInputElement>('#seed')!.disabled).toBe(true);
    expect(container!.querySelector<HTMLInputElement>('#multi_seed')!.disabled).toBe(true);
    expect(container!.querySelector<HTMLInputElement>('#seed_count')!.disabled).toBe(true);
    expect(container!.querySelector<HTMLButtonElement>('.per-type-btn')!.disabled).toBe(true);
    const sizeInputRunning = container!.querySelectorAll<HTMLInputElement>('.sizes input[type=checkbox]')[0]!;
    expect(sizeInputRunning.disabled).toBe(true);
  });
});
