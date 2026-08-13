// US-031 nestingTour 单测（≥3 项）：
//   1. result/export 步 ready 在 runRegistry 无帧时 false
//   2. result/export 步 ready 在 runRegistry 有帧时 true
//   3. 5 步 selector 全部能在已渲染的超排页 query 到（jsdom 挂载 NestingPage + mock fetch）
//
// 设计：
//   - 测 1/2 直接调 nestingTour.steps[i].ready()（读 runRegistry 模块级单例快照），
//     不挂 React 组件 —— ready 谓词是纯 store 快照读取，无需 DOM。
//   - 测 3 挂载 NestingPage（含 ControlPanel + NestsGrid + ConvergenceCurve + PlaybackBar），
//     stub fetch 防 PtypePreviewModal 的 /api/ptypes 触发 act warning；
//     NestingPage 初 mount 时 seeds=[] → useRafThrottle(false) 不启动 rAF、useSolveRun 不连 WS。
//
// runRegistry 是模块级 mutable 单例：beforeEach clear() 保证用例间隔离；
// 测 2 在 clear 后 create + 手动 push frame 模拟「求解已产出首帧」。

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { StrictMode } from 'react';
import { nestingTour } from '../steps/nestingTour';
import { runRegistry } from '../../store/runRegistry';
import { useUiStore } from '../../store/uiStore';
import type { FrameMsg } from '../../types/ws';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;

beforeEach(() => {
  runRegistry.clear();
  // nestingTour.before 会 setTab('nesting')；nestingEnabled 默认 false 会静默不切。
  // 测 3 需在 nesting tab 渲染，解锁保证 before 副作用生效（与真实流程一致：commit 后才解锁）。
  useUiStore.setState({ activeTab: 'preview', nestingEnabled: true });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  // PtypePreviewModal mount 时 fetch /api/ptypes；stub 防 act warning + unhandled rejection。
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
  if (root) {
    const r = root;
    act(() => {
      r.unmount();
    });
    root = null;
  }
  container?.remove();
  container = null;
  runRegistry.clear();
  if (fetchSpy) {
    fetchSpy.mockRestore();
    fetchSpy = null;
  }
});

describe('nestingTour ready predicates (US-031)', () => {
  it('1. result/export ready=false 当 runRegistry 无帧', () => {
    const resultStep = nestingTour.steps.find((s) => s.id === 'result');
    const exportStep = nestingTour.steps.find((s) => s.id === 'export');
    expect(resultStep).toBeDefined();
    expect(exportStep).toBeDefined();
    expect(resultStep!.ready!()).toBe(false);
    expect(exportStep!.ready!()).toBe(false);
  });

  it('2. result/export ready=true 当 runRegistry 有帧（lastFrame!==null）', () => {
    const rec = runRegistry.create(42);
    const frame: FrameMsg = {
      type: 'frame',
      index: 0,
      elapsed: 1,
      phase: 'exploring',
      density: 0.5,
      density_sparrow: 0.5,
      width_mm: 1000,
      placed_items: [],
    };
    rec.frames.push(frame);
    rec.lastFrame = frame;

    const resultStep = nestingTour.steps.find((s) => s.id === 'result');
    const exportStep = nestingTour.steps.find((s) => s.id === 'export');
    expect(resultStep!.ready!()).toBe(true);
    expect(exportStep!.ready!()).toBe(true);
  });
});

describe('nestingTour 锚点 selector 渲染 (US-031)', () => {
  it('3. 5 步 selector 全部能在已渲染的超排页 query 到', async () => {
    const { NestingPage } = await import('../../components/NestingPage');
    act(() => {
      root!.render(
        <StrictMode>
          <NestingPage />
        </StrictMode>,
      );
    });

    // 5 步锚点全部能 query 到（nestingTour.steps[i].selector）
    for (const step of nestingTour.steps) {
      const el = container!.querySelector(step.selector);
      expect(el, `selector "${step.selector}" (step ${step.id}) 应在 NestingPage 渲染后存在`).not.toBeNull();
    }

    // 再核验各锚点 id 命中预期的 step（防 step 顺序 / selector 漂移）
    expect(container!.querySelector('[data-tour="doc-banner"]')).not.toBeNull();
    expect(container!.querySelector('[data-tour="param-form"]')).not.toBeNull();
    expect(container!.querySelector('[data-tour="start-btn"]')).not.toBeNull();
    expect(container!.querySelector('[data-tour="nest-wrap"]')).not.toBeNull();
    expect(container!.querySelector('[data-tour="export-group"]')).not.toBeNull();
  });

  it('4. nestingTour 共 5 步且 id 序列符合 PRD（doc-banner/params/solve/result/export）', () => {
    expect(nestingTour.tabId).toBe('nesting');
    expect(nestingTour.steps).toHaveLength(5);
    expect(nestingTour.steps.map((s) => s.id)).toEqual([
      'doc-banner',
      'params',
      'solve',
      'result',
      'export',
    ]);
  });

  it('5. 前 3 步告知型（无 ready）；result + export 联动型（有 ready + readyHint）', () => {
    const [s0, s1, s2, s3, s4] = nestingTour.steps;
    expect(s0.ready).toBeUndefined(); // doc-banner
    expect(s1.ready).toBeUndefined(); // params
    expect(s2.ready).toBeUndefined(); // solve
    expect(s3.ready).toBeDefined(); // result（联动闸门，与 previewTour 的 parsed 步同构）
    expect(s3.readyHint).toBeDefined();
    expect(s4.ready).toBeDefined(); // export（收尾闸门）
    expect(s4.readyHint).toBeDefined();
  });
});
