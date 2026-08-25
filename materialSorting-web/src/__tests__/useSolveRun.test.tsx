// US-002 useSolveRun 单测：
//   1) mock WS 推 manifest + frame + final → hook 正确分发 + Registry 落盘
//   2) StrictMode 双 mount 不会触发两次 WS 连接（start 不在 effect 里）
//   3) StartPayload 字段逐项与 server.py 期望一致（per_type 空时为 null）

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StrictMode, useEffect, type MutableRefObject } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { useSolveRun, type StartConfig } from '../hooks/useSolveRun';
import { runRegistry } from '../store/runRegistry';
import type { ServerMsg, StartPayload } from '../types/ws';

// 告知 React 此环境支持 act()（jsdom 默认不会自动设置）。
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---- Mock WebSocket ----
interface MockWS {
  url: string;
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
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    sent: [],
    send(data: string) {
      inst.sent.push(data);
    },
    close() {
      inst.onclose?.();
    },
  };
  mockInstances.push(inst);
  return inst;
}

// 用一个最小 ctor 占位，让 hook 内 new WebSocket(url) 拿到的就是 mock 实例。
class MockWebSocketCtor {
  constructor(url: string) {
    return makeMockWS(url) as unknown as WebSocket;
  }
}

let realWS: typeof WebSocket | undefined;
let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  mockInstances.length = 0;
  realWS = globalThis.WebSocket;
  (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket =
    MockWebSocketCtor as unknown as typeof WebSocket;
  runRegistry.clear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
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
});

function mountHook(
  callbacks: Parameters<typeof useSolveRun>[0] = {},
): MutableRefObject<ReturnType<typeof useSolveRun>['start']> {
  const startRef: MutableRefObject<ReturnType<typeof useSolveRun>['start']> = {
    current: () => {
      /* placeholder */
    },
  };
  function Probe() {
    const { start } = useSolveRun(callbacks);
    useEffect(() => {
      startRef.current = start;
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
  return startRef;
}

describe('useSolveRun', () => {
  it('StrictMode 双 mount 不触发 WS 连接（start 显式调用前 0 连接）', () => {
    mountHook({});
    expect(mockInstances).toHaveLength(0);
  });

  it('start() 打开 WS 并发送首条 StartPayload（per_type 缺省 → null）', () => {
    const startRef = mountHook({});
    const cfg: StartConfig = {
      sizes: [30, 32],
      time: 120,
      seed: 0,
      gate_mm: 1980,
      params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
    };
    act(() => startRef.current(cfg));
    expect(mockInstances).toHaveLength(1);
    const ws = mockInstances[0];
    expect(ws.url).toMatch(/\/ws\/solve$/);
    act(() => ws.onopen?.());
    expect(ws.sent).toHaveLength(1);
    const parsed: StartPayload = JSON.parse(ws.sent[0]);
    expect(parsed).toEqual<StartPayload>({
      action: 'start',
      sizes: [30, 32],
      time: 120,
      seed: 0,
      gate_mm: 1980,
      params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
      per_type: null,
      // US-022：quantities 缺省 → null（后端回退全片 demand=1）。
      quantities: null,
      // US-012：band 缺省 → null（后端 _parse_band 见 null = 关闭，旧行为不变）。
      band: null,
      // US-004：prefix 缺省 → null（后端 _parse_prefix 见 null = 关闭，旧行为不变）。
      prefix: null,
    });
  });

  it('manifest + frame + final 正确分发 + Registry 落盘（density 双口径）', () => {
    const onManifest = vi.fn();
    const onFrame = vi.fn();
    const onFinal = vi.fn();
    const onDone = vi.fn();
    const startRef = mountHook({ onManifest, onFrame, onFinal, onDone });

    act(() =>
      startRef.current({
        sizes: [30],
        time: 1,
        seed: 7,
        gate_mm: 1980,
        params: { d_ext: 1, d_int: 0, tol_ext: 1, tol_int: 0 },
      }),
    );
    expect(mockInstances).toHaveLength(1);
    const ws = mockInstances[0];

    const manifest: ServerMsg = {
      type: 'manifest',
      gate_mm: 1980,
      total_area_mm2: 100000,
      n_eroded: 2,
      pieces: [],
    };
    const frame: ServerMsg = {
      type: 'frame',
      index: 0,
      elapsed: 0.5,
      phase: 'exploring',
      density: 0.5, // 原面积口径
      density_sparrow: 0.55, // erode 后 sparrow 自报
      width_mm: 1000,
      placed_items: [{ id: 'p1', rotation: 0, translation: [10, 20] }],
    };
    const finalMsg: ServerMsg = {
      type: 'final',
      density: 0.62,
      density_sparrow: 0.65,
      width_mm: 900,
      elapsed: 1.5,
      n_frames: 1,
      n_eroded: 2,
    };

    act(() => {
      ws.onmessage?.({ data: JSON.stringify(manifest) });
      ws.onmessage?.({ data: JSON.stringify(frame) });
      ws.onmessage?.({ data: JSON.stringify(finalMsg) });
    });

    expect(onManifest).toHaveBeenCalledTimes(1);
    expect(onFrame).toHaveBeenCalledTimes(1);
    expect(onFinal).toHaveBeenCalledTimes(1);
    // onDone 在 final 触发一次（onclose 不应二次触发 —— done flag）
    expect(onDone).toHaveBeenCalledTimes(1);

    // Registry 落盘
    const runs = runRegistry.list();
    expect(runs).toHaveLength(1);
    const rec = runs[0];
    expect(rec.seed).toBe(7);
    expect(rec.frames).toHaveLength(1);
    expect(rec.frames[0]).toMatchObject({ density: 0.5, density_sparrow: 0.55 });
    expect(rec.lastFrame).toBe(rec.frames[0]);
    expect(rec.viewBoxMaxW).toBe(1000);
    expect(rec.finalDensity).toBe(0.62);
    expect(rec.finalDensitySparrow).toBe(0.65);
    expect(rec.done).toBe(true);
    expect(rec.manifest?.gate_mm).toBe(1980);

    // 模拟 server 关 WS —— onDone 不应再触发
    act(() => ws.onclose?.());
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('error 消息走 onError 分支并标记 done', () => {
    const onError = vi.fn();
    const onDone = vi.fn();
    const startRef = mountHook({ onError, onDone });
    act(() =>
      startRef.current({
        sizes: [30],
        time: 1,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
      }),
    );
    const ws = mockInstances[0];
    act(() =>
      ws.onmessage?.({
        data: JSON.stringify({ type: 'error', message: '构造实例失败: boom' }),
      }),
    );
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toMatchObject({
      type: 'error',
      message: '构造实例失败: boom',
    });
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(runRegistry.list()[0].error).toBe('构造实例失败: boom');
    expect(runRegistry.list()[0].done).toBe(true);
  });

  it('WS URL 走相对 host（dev/prod 自适配，不被写死成 :8000/:5173）', () => {
    const startRef = mountHook({});
    act(() =>
      startRef.current({
        sizes: [],
        time: 1,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
      }),
    );
    const url = mockInstances[0].url;
    // proto 与 host 必须从 location 推导，而非硬编码
    expect(url).toBe(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/solve`);
  });

  it('per_type 非空时透传（不抹平为 null）', () => {
    const startRef = mountHook({});
    act(() =>
      startRef.current({
        sizes: [30],
        time: 1,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
        per_type: { g03: { d: 1, tol: 1 } },
      }),
    );
    const ws = mockInstances[0];
    act(() => ws.onopen?.());
    const parsed: StartPayload = JSON.parse(ws.sent[0]);
    expect(parsed.per_type).toEqual({ g03: { d: 1, tol: 1 } });
  });

  it('US-022 quantities 非空时透传到 StartPayload（label→sizeKey→demand）', () => {
    const startRef = mountHook({});
    const quantities = {
      g01: { '30': 2, '32': 0 },
      g02: { '30': 1, '32': 1 },
    };
    act(() =>
      startRef.current({
        sizes: [30, 32],
        time: 1,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
        quantities,
      }),
    );
    const ws = mockInstances[0];
    act(() => ws.onopen?.());
    const parsed: StartPayload = JSON.parse(ws.sent[0]);
    expect(parsed.quantities).toEqual(quantities);
  });

  it('US-022 quantities 缺省 → null（后端回退全片 demand=1）', () => {
    const startRef = mountHook({});
    act(() =>
      startRef.current({
        sizes: [30],
        time: 1,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
      }),
    );
    const ws = mockInstances[0];
    act(() => ws.onopen?.());
    const parsed: StartPayload = JSON.parse(ws.sent[0]);
    expect(parsed.quantities).toBeNull();
  });

  // ============================================================
  // US-024 manifest 5 层字段分发（net_polygon/internal_lines/notches/grain_line）
  // 后端扩 manifest 后，hook onmessage 按 type='manifest' 落 runRegistry，无字段丢失。
  // ============================================================
  it('US-024 manifest 含 5 层字段 → Registry 落盘保真（net/internal/notches/grain）', () => {
    const onManifest = vi.fn();
    const startRef = mountHook({ onManifest });
    act(() =>
      startRef.current({
        sizes: [30],
        time: 1,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
      }),
    );
    const ws = mockInstances[0];

    const manifest: ServerMsg = {
      type: 'manifest',
      gate_mm: 1980,
      total_area_mm2: 100000,
      n_eroded: 0,
      pieces: [
        {
          id: 'p1',
          label: 'g01',
          size: 30,
          color: '#ff0000',
          area_mm2: 12345,
          polygon: [[0, 0], [10, 0], [10, 10], [0, 10]],
          // US-024 5 层字段
          net_polygon: [[1, 1], [9, 1], [9, 9], [1, 9]],
          internal_lines: [[[2, 2], [8, 8]]],
          notches: [[5, 0, 0, -1]],
          grain_line: [3, 5, 7, 5],
        },
        {
          id: 'p2',
          label: 'g02',
          size: 32,
          color: '#00ff00',
          area_mm2: 23456,
          polygon: [[0, 0], [20, 0], [20, 20], [0, 20]],
          // p2 不带 5 层字段（向后兼容验证）
        },
      ],
    };
    act(() => ws.onmessage?.({ data: JSON.stringify(manifest) }));

    expect(onManifest).toHaveBeenCalledTimes(1);
    const rec = runRegistry.list()[0];
    expect(rec.manifest).not.toBeNull();
    expect(rec.manifest!.pieces).toHaveLength(2);
    // p1 5 层字段保真
    const p1 = rec.manifest!.pieces[0];
    expect(p1.net_polygon).toEqual([[1, 1], [9, 1], [9, 9], [1, 9]]);
    expect(p1.internal_lines).toEqual([[[2, 2], [8, 8]]]);
    expect(p1.notches).toEqual([[5, 0, 0, -1]]);
    expect(p1.grain_line).toEqual([3, 5, 7, 5]);
    // p2 缺字段 → undefined（layer-aware 渲染层跳过）
    const p2 = rec.manifest!.pieces[1];
    expect(p2.net_polygon).toBeUndefined();
    expect(p2.internal_lines).toBeUndefined();
    expect(p2.notches).toBeUndefined();
    expect(p2.grain_line).toBeUndefined();
  });

  // ============================================================
  // US-012 腰头成带：band 透传（StartPayload 序列化）+ stage 消息分发（run 不 finish）
  // ============================================================
  it('US-012 band 开且有效 → StartPayload.band = {enabled:true,label}（不带 ack）', () => {
    const startRef = mountHook({});
    act(() =>
      startRef.current({
        sizes: [30],
        time: 120,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
        band: { enabled: true, label: 'g05' },
      }),
    );
    const ws = mockInstances[0];
    act(() => ws.onopen?.());
    const parsed: StartPayload = JSON.parse(ws.sent[0]);
    expect(parsed.band).toEqual({ enabled: true, label: 'g05' });
    // 序列化无 ack 键（仅 US-013 确认弹窗对硬警告形态显式置）
    expect(JSON.parse(JSON.stringify(parsed.band!))).toEqual({ enabled: true, label: 'g05' });
  });

  it('US-012 band 显式 null → StartPayload.band = null（band 关，与缺省同线格式）', () => {
    const startRef = mountHook({});
    act(() =>
      startRef.current({
        sizes: [30],
        time: 1,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
        band: null,
      }),
    );
    const ws = mockInstances[0];
    act(() => ws.onopen?.());
    const parsed: StartPayload = JSON.parse(ws.sent[0]);
    expect(parsed.band).toBeNull();
  });

  it('US-012 stage 消息 → rec.stage 落盘 + onStage 回调；run 不 finish（后续 manifest/final 正常）', () => {
    const onStage = vi.fn();
    const onManifest = vi.fn();
    const onFinal = vi.fn();
    const onDone = vi.fn();
    const startRef = mountHook({ onStage, onManifest, onFinal, onDone });
    act(() =>
      startRef.current({
        sizes: [30],
        time: 1,
        seed: 3,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
        band: { enabled: true, label: 'g05' },
      }),
    );
    const ws = mockInstances[0];

    // FR-2：stage（band 带内聚排统计）在 manifest 前唯一一次。
    const stage: ServerMsg = {
      type: 'stage',
      stage: 'band',
      fill_pct: 54.8,
      bbox: { width_mm: 3400, height_mm: 1910 },
      fallback: false,
      elapsed: 15.2,
    };
    act(() => ws.onmessage?.({ data: JSON.stringify(stage) }));

    expect(onStage).toHaveBeenCalledTimes(1);
    expect(onStage.mock.calls[0][0]).toMatchObject({
      type: 'stage',
      stage: 'band',
      fill_pct: 54.8,
    });
    const rec = runRegistry.list()[0];
    expect(rec.stage).toMatchObject({ type: 'stage', stage: 'band', fill_pct: 54.8 });
    // **run 不 finish**：stage 不是终态 —— done 仍 false、onDone 未触发
    expect(rec.done).toBe(false);
    expect(onDone).not.toHaveBeenCalled();

    // 后续 manifest → final 正常流转（stage 不影响生命周期）
    act(() =>
      ws.onmessage?.({
        data: JSON.stringify({
          type: 'manifest',
          gate_mm: 1980,
          total_area_mm2: 1,
          n_eroded: 0,
          pieces: [],
        }),
      }),
    );
    expect(onManifest).toHaveBeenCalledTimes(1);
    act(() =>
      ws.onmessage?.({
        data: JSON.stringify({
          type: 'final',
          density: 0.87,
          density_sparrow: 0.89,
          width_mm: 9000,
          elapsed: 1.2,
          n_frames: 3,
          n_eroded: 0,
        }),
      }),
    );
    expect(onFinal).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(rec.done).toBe(true);
    // stage 统计保留（信息记录，不被 final 清除）
    expect(rec.stage).not.toBeNull();
  });

  // ============================================================
  // US-004 起始端成套前后幅：prefix 透传（StartPayload 序列化，无 size 键）+
  // stage('prefix') 消息分发（size 回显资格码，run 不 finish）
  // ============================================================
  it('US-004 prefix 开且有效 → StartPayload.prefix = {enabled,front,back}（无 size 键）', () => {
    const startRef = mountHook({});
    act(() =>
      startRef.current({
        sizes: [30],
        time: 120,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
        prefix: { enabled: true, front: 'g02', back: 'g03' },
      }),
    );
    const ws = mockInstances[0];
    act(() => ws.onopen?.());
    const parsed: StartPayload = JSON.parse(ws.sent[0]);
    expect(parsed.prefix).toEqual({ enabled: true, front: 'g02', back: 'g03' });
    // 序列化无 size 键（资格码后端 seeded 随机选取 —— 决策②）
    expect(Object.keys(JSON.parse(JSON.stringify(parsed.prefix!)))).toEqual(['enabled', 'front', 'back']);
    // band 与 prefix 可同开（互不干扰，各自独立键）
  });

  it('US-004 prefix 显式 null → StartPayload.prefix = null（prefix 关，与缺省同线格式）', () => {
    const startRef = mountHook({});
    act(() =>
      startRef.current({
        sizes: [30],
        time: 1,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
        prefix: null,
      }),
    );
    const ws = mockInstances[0];
    act(() => ws.onopen?.());
    const parsed: StartPayload = JSON.parse(ws.sent[0]);
    expect(parsed.prefix).toBeNull();
  });

  it('US-004 band+prefix 双开 → 两键各自透传（StartPayload 线格式独立）', () => {
    const startRef = mountHook({});
    act(() =>
      startRef.current({
        sizes: [30],
        time: 1,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
        band: { enabled: true, label: 'g05' },
        prefix: { enabled: true, front: 'g02', back: 'g03' },
      }),
    );
    const ws = mockInstances[0];
    act(() => ws.onopen?.());
    const parsed: StartPayload = JSON.parse(ws.sent[0]);
    expect(parsed.band).toEqual({ enabled: true, label: 'g05' });
    expect(parsed.prefix).toEqual({ enabled: true, front: 'g02', back: 'g03' });
  });

  it('US-004 stage(prefix) → rec.stage 落盘 + onStage 回调（size 回显）；run 不 finish', () => {
    const onStage = vi.fn();
    const onManifest = vi.fn();
    const onDone = vi.fn();
    const startRef = mountHook({ onStage, onManifest, onDone });
    act(() =>
      startRef.current({
        sizes: [30],
        time: 1,
        seed: 3,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
        prefix: { enabled: true, front: 'g02', back: 'g03' },
      }),
    );
    const ws = mockInstances[0];

    // FR-2：stage('prefix') 在 manifest 前唯一一次（双开时 band→prefix 序）；
    // size 回显后端 seeded 随机选中的资格码（前端无法预知）。
    const stage: ServerMsg = {
      type: 'stage',
      stage: 'prefix',
      size: 34,
      fill_pct: 83.6,
      bbox: { width_mm: 1155, height_mm: 1458 },
      fallback: false,
      holes: 0,
      elapsed: 0.4,
    };
    act(() => ws.onmessage?.({ data: JSON.stringify(stage) }));

    expect(onStage).toHaveBeenCalledTimes(1);
    expect(onStage.mock.calls[0][0]).toMatchObject({
      type: 'stage',
      stage: 'prefix',
      size: 34,
      holes: 0,
    });
    const rec = runRegistry.list()[0];
    expect(rec.stage).toMatchObject({ type: 'stage', stage: 'prefix', size: 34 });
    // **run 不 finish**：stage 不是终态 —— done 仍 false、onDone 未触发
    expect(rec.done).toBe(false);
    expect(onDone).not.toHaveBeenCalled();

    // 后续 manifest 正常流转（stage 不影响生命周期）
    act(() =>
      ws.onmessage?.({
        data: JSON.stringify({
          type: 'manifest',
          gate_mm: 1980,
          total_area_mm2: 1,
          n_eroded: 0,
          pieces: [],
        }),
      }),
    );
    expect(onManifest).toHaveBeenCalledTimes(1);
    // rec.stage 保留 prefix 统计（双开时后到的 stage 覆盖 rec.stage，msg 本体经回调判别）
    expect(rec.stage).toMatchObject({ stage: 'prefix', size: 34 });
  });

  it('US-012 未知消息类型仍 default:break 静默忽略（不 throw / 不 finish；旧后端不发 stage 也安全）', () => {
    const onDone = vi.fn();
    const startRef = mountHook({ onDone });
    act(() =>
      startRef.current({
        sizes: [30],
        time: 1,
        seed: 0,
        gate_mm: 1980,
        params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
      }),
    );
    const ws = mockInstances[0];
    // 未知 type / 缺 type —— 静默丢弃，run 继续
    expect(() =>
      act(() => {
        ws.onmessage?.({ data: JSON.stringify({ type: 'telemetry', payload: 1 }) });
        ws.onmessage?.({ data: JSON.stringify({ hello: 'world' }) });
      }),
    ).not.toThrow();
    expect(onDone).not.toHaveBeenCalled();
    expect(runRegistry.list()[0].done).toBe(false);
    // 非 JSON —— 既有行为：解析失败静默 return
    expect(() => act(() => ws.onmessage?.({ data: 'not-json' }))).not.toThrow();
  });
});
