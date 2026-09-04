// 编辑排料 US-003 降级路径单测：polygon-clipping 布尔交异常 →「bbox 交高亮 +
// 面积按 bbox 估算」不阻塞拖动（PRD US-003 任务 5 口径）。
//
// vi.mock('polygon-clipping') 令 intersection 恒抛 —— 只影响本文件（模块图隔离），
// 其余用例走真实 Martinez 实现。夹具与 EditCanvas.test 同款：a/b 两 500×500 方。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// mock 同时给出具名 + default 两种形态（overlap.ts 的 namespace+default 互操作解析
// 会先探 default —— vitest mock 代理对未定义键直接抛错，缺 default 会误炸）。
vi.mock('polygon-clipping', () => {
  const boom = (): never => {
    throw new Error('clipping boom');
  };
  return { intersection: boom, default: { intersection: boom } };
});

import { EditCanvas } from '../EditCanvas';
import { useEditStore } from '../../../store/editStore';
import { runRegistry, type RunRecord } from '../../../store/runRegistry';
import type { PlacedItem } from '../../../types/piece';
import type { FrameMsg, ManifestMsg } from '../../../types/ws';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  runRegistry.clear();
  useEditStore.getState().invalidate();
  (window as unknown as { PointerEvent?: unknown }).PointerEvent = class extends MouseEvent {};
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
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
  useEditStore.getState().invalidate();
});

const GATE = 1000;

function makeManifest(): ManifestMsg {
  return {
    type: 'manifest',
    gate_mm: GATE,
    total_area_mm2: 500000,
    n_eroded: 0,
    pieces: [
      {
        id: 'a_28',
        label: 'g01',
        size: 28,
        color: '#ff0000',
        area_mm2: 250000,
        polygon: [
          [0, 0], [500, 0], [500, 500], [0, 500],
        ],
      },
      {
        id: 'b_30',
        label: 'g02',
        size: 30,
        color: '#00ff00',
        area_mm2: 250000,
        polygon: [
          [0, 0], [500, 0], [500, 500], [0, 500],
        ],
      },
    ],
  };
}

function seedRun(placed: PlacedItem[]): RunRecord {
  const run = runRegistry.create(0);
  run.manifest = makeManifest();
  const frame: FrameMsg = {
    type: 'frame',
    index: 0,
    elapsed: 1,
    phase: 'final',
    density: 0.5,
    density_sparrow: 0.5,
    width_mm: 1100,
    placed_items: placed.map((it) => ({
      id: it.id,
      rotation: it.rotation,
      translation: [it.translation[0], it.translation[1]] as [number, number],
    })),
  };
  run.frames.push(frame);
  run.lastFrame = frame;
  run.finalDensity = frame.density;
  return run;
}

function mountCanvas(): SVGSVGElement {
  act(() => {
    useEditStore.getState().open(seedRun([
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [450, 50] },
    ]));
  });
  act(() => {
    root!.render(<EditCanvas mode="full" />);
  });
  return document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
}

function firePointer(el: Element, type: 'pointerdown' | 'pointermove' | 'pointerup', x: number, y: number): void {
  el.dispatchEvent(
    new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: 1, clientX: x, clientY: y }),
  );
}

describe('EditCanvas 重合指标降级 (US-003)', () => {
  it('布尔交异常 → bbox 交高亮（矩形环）+ 面积按 bbox 估算 + 面板标注，不阻塞拖动', () => {
    const svg = mountCanvas();
    const roughB = svg.querySelector(':scope g > polygon[stroke="#00ff00"]') as SVGPolygonElement;

    // 选中 b（与 a 交 [450,500]x[50,500]）→ 降级路径
    act(() => {
      firePointer(roughB, 'pointerdown', 10, 10);
      firePointer(roughB, 'pointerup', 10, 10);
    });
    const panel = document.querySelector('[data-testid="edit-metrics"]') as HTMLElement;
    expect(panel).not.toBeNull();
    expect(panel.getAttribute('data-degraded')).toBe('1');
    // 面积 = bbox 交 50×450 = 22500（本夹具两轴对齐方 → 与精确值同数，口径为 bbox 估算）
    expect(
      document.querySelector('[data-testid="edit-metrics-area"]')!.textContent,
    ).toBe('22500.0 mm²（225.00 cm²） · bbox 估算');
    // 穿透深度是独立纯函数（无布尔交）—— 继续如实计算 50.0
    expect(
      document.querySelector('[data-testid="edit-metrics-depth"]')!.textContent,
    ).toBe('50.0 mm');
    // 高亮 = bbox 交矩形环（自建 4 点，非 clipping 输出）
    const hilite = svg.querySelector('polygon[fill="rgba(255, 64, 64, 0.42)"]');
    expect(hilite).not.toBeNull();
    expect(hilite!.getAttribute('points')).toBe('450,50 500,50 500,500 450,500');

    // 拖动不被阻塞：右移 b 到 [700,0]（与 a 分离 → bbox 亦无交，面积 0）
    (svg as unknown as { getBoundingClientRect: () => DOMRect }).getBoundingClientRect = () =>
      ({ width: 550, height: 500, x: 0, y: 0, top: 0, left: 0, right: 550, bottom: 500 }) as DOMRect;
    act(() => {
      firePointer(roughB, 'pointerdown', 100, 100);
      firePointer(roughB, 'pointermove', 300, 100); // dx=200px → +400mm → 450+400=850
      firePointer(roughB, 'pointerup', 300, 100);
    });
    const w = useEditStore.getState().working;
    expect(w[1].translation[0]).toBeCloseTo(850, 10);
    expect(panel.getAttribute('data-degraded')).toBe('0'); // 无交邻居 → 不再走降级分支
    expect(
      document.querySelector('[data-testid="edit-metrics-area"]')!.textContent,
    ).toBe('0.0 mm²（0.00 cm²）');
  });
});
