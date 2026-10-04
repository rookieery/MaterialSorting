// 批量框选移动（marqueeSelect，2026-10-04 用户需求）EditCanvas 单测：
//   1) 默认 props 回归锁：不传 marqueeSelect → 按钮/指南行缺席（编辑弹窗零变化）。
//   2) 模式开关：按钮文案 区域选择 ⇄ 取消框选 + crosshair 光标 + Esc 退出。
//   3) 橡皮筋「完全覆盖」语义：物理毛版世界 bbox 整体在矩形内才入选（半覆盖不选）；
//      选中集 = .edit-marquee-selected 类 + 并集 bbox 虚线矩形（矩形 = 选中块包络）。
//   4) 刚性组原子扩展：pieceGroup 组任一成员被覆盖 → 全组入选（组不可被框选拆散）。
//   5) 框选块整体拖动：全组同 delta（store 多条 setWorkingItem）+ 组包络钳制
//      （minX≥0）+ 矩形随组平移 + 非选中片不动 + 选中态拖后保持。
//   6) 模式内交互面：单片拖动不可用（按未选中片 = 起框选不起拖动）、pan 手势被
//      占用（viewBox 不动）。
//   7) 取消语义（用户定案 2026-10-04）：单击（<3px）= 清选中、位置保留不回滚。
//
// CTM mock = 单位阵（world == client，同 EditCanvas.test mockMat 套路）→ 橡皮筋
// 世界坐标可直接按 client 断言；viewScale 用 mockRect(1050,500) → s=0.5 px/mm。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditCanvas, type EditCanvasProps } from '../EditCanvas';
import { computeLayoutStats, useEditStore } from '../../../store/editStore';
import { runRegistry, type RunRecord } from '../../../store/runRegistry';
import type { PlacedItem, Polygon } from '../../../types/piece';
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

// ---- fixture：三片 500×500（gate 1000）a@[0,0] b@[600,0] c@[1600,0] → 包络 2100 ----

const GATE = 1000;

function makeManifest3(): ManifestMsg {
  const raw: Polygon = [
    [0, 0],
    [500, 0],
    [500, 500],
    [0, 500],
  ];
  const piece = (id: string, label: string, size: number, color: string) => ({
    id,
    label,
    size,
    color,
    area_mm2: 250000,
    polygon: raw,
  });
  return {
    type: 'manifest',
    gate_mm: GATE,
    total_area_mm2: 750000,
    n_eroded: 0,
    pieces: [
      piece('a_28', 'g01', 28, '#ff0000'),
      piece('b_30', 'g01', 30, '#00ff00'),
      piece('c_32', 'g02', 32, '#0000ff'),
    ],
  };
}

/** a@[0,0] + b@[600,0]（band 组语义）+ c@[1600,0]（非成员）→ 包络 maxX 2100。 */
const PLACED: PlacedItem[] = [
  { id: 'a_28', rotation: 0, translation: [0, 0] },
  { id: 'b_30', rotation: 0, translation: [600, 0] },
  { id: 'c_32', rotation: 0, translation: [1600, 0] },
];

/** 组映射：a/b（band label g01 全部副本）→ 'band:g01'；其余 null。 */
function bandGroup(pid: string): string | null {
  return pid === 'a_28' || pid === 'b_30' ? 'band:g01' : null;
}

function seedRun(): RunRecord {
  const run = runRegistry.create(0);
  run.manifest = makeManifest3();
  const { widthMm, density } = computeLayoutStats(PLACED, run.manifest);
  const frame: FrameMsg = {
    type: 'frame',
    index: 0,
    elapsed: 1,
    phase: 'final',
    density,
    density_sparrow: 0.5,
    width_mm: widthMm,
    placed_items: PLACED.map((it) => ({
      id: it.id,
      rotation: it.rotation,
      translation: [it.translation[0], it.translation[1]] as [number, number],
    })),
  };
  run.frames.push(frame);
  run.lastFrame = frame;
  run.finalDensity = density;
  return run;
}

/** 挂载 + mockRect(1050,500)（s=0.5 px/mm）+ 单位 CTM（world == client）。 */
function mountMarquee(props: Partial<EditCanvasProps> = {}): SVGSVGElement {
  act(() => {
    useEditStore.getState().open(seedRun());
  });
  act(() => {
    root!.render(<EditCanvas mode="full" {...props} />);
  });
  const svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
  (svg as unknown as { getBoundingClientRect: () => DOMRect }).getBoundingClientRect = () =>
    ({ width: 1050, height: 500, x: 0, y: 0, top: 0, left: 0, right: 1050, bottom: 500 }) as DOMRect;
  // 单位阵 CTM：clientToWorld(client) = [clientX, clientY]（绘制/命中断言直读 client）。
  const flip = svg.querySelector('g') as SVGGElement;
  const idMat = {
    a: 1,
    b: 0,
    c: 0,
    d: 1,
    e: 0,
    f: 0,
    inverse: () => idMat,
  };
  (flip as unknown as { getScreenCTM: () => typeof idMat }).getScreenCTM = () => idMat;
  (svg as unknown as { createSVGPoint: () => unknown }).createSVGPoint = () => {
    const pt = {
      x: 0,
      y: 0,
      matrixTransform(m: typeof idMat) {
        return { x: m.a * pt.x + m.c * pt.y + m.e, y: m.b * pt.x + m.d * pt.y + m.f };
      },
    };
    return pt;
  };
  return svg;
}

function roughPolyOf(svg: SVGSVGElement, stroke: string): SVGPolygonElement {
  const el = svg.querySelector(`:scope g > polygon[stroke="${stroke}"]`);
  if (!el) throw new Error(`rough polygon ${stroke} not found`);
  return el as SVGPolygonElement;
}

function firePointer(
  el: Element,
  type: 'pointerdown' | 'pointermove' | 'pointerup',
  clientX: number,
  clientY: number,
): void {
  el.dispatchEvent(
    new PointerEvent(type, {
      bubbles: true,
      cancelable: true,
      pointerId: 1,
      clientX,
      clientY,
      button: 0,
    }),
  );
}

function fireKey(target: EventTarget, key: string): void {
  target.dispatchEvent(
    new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }),
  );
}

function toggleBtn(): HTMLButtonElement {
  const el = document.querySelector('[data-testid="edit-marquee-toggle"]');
  if (!el) throw new Error('marquee toggle not found');
  return el as HTMLButtonElement;
}

function selectedCount(): number {
  return document.querySelectorAll('.edit-marquee-selected').length;
}

function marqueeRect(): SVGRectElement | null {
  return document.querySelector('[data-testid="edit-marquee-rect"]') as SVGRectElement | null;
}

/** 进入框选模式（点按钮）。 */
function enterMode(): void {
  act(() => {
    toggleBtn().click();
  });
}

/** 画一个框（svg 空白起手 → 拖动 → 松手）。 */
function drawRect(svg: SVGSVGElement, x0: number, y0: number, x1: number, y1: number): void {
  act(() => {
    firePointer(svg, 'pointerdown', x0, y0);
    firePointer(svg, 'pointermove', x1, y1);
    firePointer(svg, 'pointerup', x1, y1);
  });
}

// ============================================================

describe('EditCanvas marqueeSelect 默认 props 回归锁', () => {
  it('不传 marqueeSelect → 按钮/指南行缺席（编辑弹窗行为零变化）', () => {
    mountMarquee({});
    expect(document.querySelector('[data-testid="edit-marquee-toggle"]')).toBeNull();
    expect(document.querySelector('[data-testid="edit-guide-marquee-row"]')).toBeNull();
  });

  it('marqueeSelect 在场 → 按钮初始「区域选择」+ 指南批量行', () => {
    const svg = mountMarquee({ marqueeSelect: true });
    expect(toggleBtn().textContent).toContain('区域选择');
    expect(svg.style.cursor).toBe('');
    const row = document.querySelector('[data-testid="edit-guide-marquee-row"]');
    expect(row?.textContent).toContain('区域选择模式');
    // 指南反向锁口径（EditCanvas.test 同款）：新增行不得含「形态/保存」
    expect(row?.textContent).not.toContain('形态');
    expect(row?.textContent).not.toContain('保存');
  });
});

describe('EditCanvas marqueeSelect 模式开关', () => {
  it('按钮切入/切出 + crosshair 光标 + Esc 退出（等同按钮）', () => {
    const svg = mountMarquee({ marqueeSelect: true });
    enterMode();
    expect(toggleBtn().textContent).toContain('取消框选');
    expect(svg.style.cursor).toBe('crosshair');
    // Esc 退出：文案复位 + 光标复位
    act(() => {
      fireKey(window, 'Escape');
    });
    expect(toggleBtn().textContent).toContain('区域选择');
    expect(svg.style.cursor).toBe('');
    // 再切入后按钮切出同效
    enterMode();
    act(() => {
      toggleBtn().click();
    });
    expect(toggleBtn().textContent).toContain('区域选择');
  });
});

describe('EditCanvas marqueeSelect 框选「完全覆盖」', () => {
  it('矩形完全覆盖才入选：a 全覆盖入选、b 半覆盖不选、c 在框外不选', () => {
    const svg = mountMarquee({ marqueeSelect: true });
    enterMode();
    // 矩形 [0..520]²：a bbox [0..500]² ⊆ ✓；b bbox [600..1100] 半覆盖 ✗；c 远外 ✗
    drawRect(svg, 0, 0, 520, 520);
    const sel = document.querySelectorAll('.edit-marquee-selected');
    expect(sel.length).toBe(1);
    expect(sel[0].getAttribute('stroke')).toBe('#ff0000'); // a 的 layer1
    // 矩形 = 选中块并集 bbox（a 的 [0..500]²），非橡皮筋几何
    const rect = marqueeRect();
    expect(rect).not.toBeNull();
    expect(parseFloat(rect!.getAttribute('x')!)).toBeCloseTo(0, 6);
    expect(parseFloat(rect!.getAttribute('y')!)).toBeCloseTo(0, 6);
    expect(parseFloat(rect!.getAttribute('width')!)).toBeCloseTo(500, 6);
    expect(parseFloat(rect!.getAttribute('height')!)).toBeCloseTo(500, 6);
    // working 未动（框选纯选择零位移）
    expect(useEditStore.getState().working).toEqual(PLACED);
  });

  it('刚性组原子扩展：pieceGroup 组任一成员被覆盖 → 全组入选（组不可拆散）', () => {
    const svg = mountMarquee({ marqueeSelect: true, pieceGroup: bandGroup });
    enterMode();
    // 矩形只覆盖 a，但 a/b 同 band 组 → b 原子扩展入选
    drawRect(svg, 0, 0, 520, 520);
    expect(selectedCount()).toBe(2);
  });

  it('无 pieceGroup（默认 props）同矩形只选 a —— 扩展是 pieceGroup 在场的行为', () => {
    const svg = mountMarquee({ marqueeSelect: true });
    enterMode();
    drawRect(svg, 0, 0, 520, 520);
    expect(selectedCount()).toBe(1);
  });

  it('零命中 = 清选中（模式保持，可再画新框替换选集）', () => {
    const svg = mountMarquee({ marqueeSelect: true });
    enterMode();
    drawRect(svg, 0, 0, 520, 520);
    expect(selectedCount()).toBe(1);
    // 画一个不含任何完整片的新框（只盖住 b 的一半）→ 选中清空
    drawRect(svg, 700, 0, 900, 400);
    expect(selectedCount()).toBe(0);
    expect(marqueeRect()).toBeNull();
    expect(toggleBtn().textContent).toContain('取消框选'); // 模式保持
    // 再画覆盖 a+b 的框 → 新选集落定
    drawRect(svg, 0, 0, 1150, 520);
    expect(selectedCount()).toBe(2);
  });
});

describe('EditCanvas marqueeSelect 框选块整体拖动', () => {
  /** 前置：进入模式并框选 a+b（矩形 [0..1150]×[0..520]）。 */
  function setupSelectAB(): SVGSVGElement {
    const svg = mountMarquee({ marqueeSelect: true });
    enterMode();
    drawRect(svg, 0, 0, 1150, 520);
    expect(selectedCount()).toBe(2);
    return svg;
  }

  it('按住选中片拖动 = 全组同 delta（store 多条 setWorkingItem）+ 矩形随组平移 + 非选中不动', () => {
    const svg = setupSelectAB();
    const roughA = roughPolyOf(svg, '#ff0000');
    const rect0 = marqueeRect()!;
    expect(parseFloat(rect0.getAttribute('x')!)).toBeCloseTo(0, 6);
    act(() => {
      firePointer(roughA, 'pointerdown', 100, 100);
      firePointer(roughA, 'pointermove', 200, 100); // +100px / 0.5 = +200mm
      firePointer(roughA, 'pointerup', 200, 100);
    });
    const w = useEditStore.getState().working;
    expect(w[0].translation).toEqual([200, 0]);
    expect(w[1].translation).toEqual([800, 0]);
    expect(w[2].translation).toEqual([1600, 0]); // c 不动
    // 矩形随组平移：[0..1100] → [200..1300]
    const rect = marqueeRect()!;
    expect(parseFloat(rect.getAttribute('x')!)).toBeCloseTo(200, 6);
    expect(parseFloat(rect.getAttribute('width')!)).toBeCloseTo(1100, 6);
    // 选中态拖后保持（可继续拖）
    expect(selectedCount()).toBe(2);
  });

  it('组包络钳制：minX≥0（拖出布头截住，全组不动）', () => {
    const svg = setupSelectAB();
    const roughA = roughPolyOf(svg, '#ff0000');
    act(() => {
      firePointer(roughA, 'pointerdown', 100, 100);
      firePointer(roughA, 'pointermove', -200, 100); // dx = −600mm → 组 minX 0 钳 0
      firePointer(roughA, 'pointerup', -200, 100);
    });
    const w = useEditStore.getState().working;
    expect(w[0].translation).toEqual([0, 0]);
    expect(w[1].translation).toEqual([600, 0]);
  });

  it('多帧拖动矩形不累加（rAF 多 move 合帧：矩形终位 = 起手 + 末帧位移，冒烟 12 步 6.4× 过冲回归锁）', () => {
    const svg = setupSelectAB();
    const roughA = roughPolyOf(svg, '#ff0000');
    act(() => {
      firePointer(roughA, 'pointerdown', 100, 100);
      // 模拟渐进 move 流（首版 bug：sel.bbox += cdx 增量累加，Σcdx_k ≈ 6.5× 末帧）
      for (let k = 1; k <= 12; k++) firePointer(roughA, 'pointermove', 100 + (200 * k) / 12, 100);
      firePointer(roughA, 'pointerup', 300, 100);
    });
    const w = useEditStore.getState().working;
    expect(w[0].translation).toEqual([400, 0]); // 末帧 dx = +400mm 绝对位移
    const rect = marqueeRect()!;
    // 矩形 = 起手 bbox [0..1100] + 400（绝不为 Σ增量 ≈ [0..1100] + 2600）
    expect(parseFloat(rect.getAttribute('x')!)).toBeCloseTo(400, 6);
    expect(parseFloat(rect.getAttribute('width')!)).toBeCloseTo(1100, 6);
  });

  it('单击空白 = 清选中、位置保留（用户定案不回滚）+ 单击后模式保持', () => {
    const svg = setupSelectAB();
    const roughA = roughPolyOf(svg, '#ff0000');
    act(() => {
      firePointer(roughA, 'pointerdown', 100, 100);
      firePointer(roughA, 'pointermove', 200, 100);
      firePointer(roughA, 'pointerup', 200, 100);
    });
    // 单击空白（位移 <3px）→ 清选中；已移动的位置保留
    act(() => {
      firePointer(svg, 'pointerdown', 10, 10);
      firePointer(svg, 'pointerup', 10, 10);
    });
    expect(selectedCount()).toBe(0);
    expect(marqueeRect()).toBeNull();
    const w = useEditStore.getState().working;
    expect(w[0].translation).toEqual([200, 0]);
    expect(w[1].translation).toEqual([800, 0]);
    expect(toggleBtn().textContent).toContain('取消框选');
  });
});

describe('EditCanvas marqueeSelect 模式内交互面', () => {
  it('按未选中片 = 起框选不起单片拖动（密排布局框选起点允许落在片上）', () => {
    const svg = mountMarquee({ marqueeSelect: true });
    enterMode();
    drawRect(svg, 0, 0, 520, 520); // 选中 a
    expect(selectedCount()).toBe(1);
    // 按 c（未选中片）画框：c 位置不动（若误起单片拖动会位移）
    const roughC = roughPolyOf(svg, '#0000ff');
    act(() => {
      firePointer(roughC, 'pointerdown', 1700, 100);
      firePointer(roughC, 'pointermove', 1550, -20); // 框 [1550..1700]×[−20..100]
      firePointer(roughC, 'pointerup', 1550, -20);
    });
    const w = useEditStore.getState().working;
    expect(w[2].translation).toEqual([1600, 0]); // c 未被拖动
    expect(w[0].translation).toEqual([0, 0]); // a 也不动
    expect(selectedCount()).toBe(0); // 新框零命中 → 清选中
  });

  it('pan 手势被占用：空白拖动画框 viewBox 不动（滚轮/全览不受影响）', () => {
    const svg = mountMarquee({ marqueeSelect: true });
    enterMode();
    expect(svg.getAttribute('viewBox')).toBe('0 0 2100 1000');
    drawRect(svg, 100, 100, 400, 300);
    expect(svg.getAttribute('viewBox')).toBe('0 0 2100 1000'); // 未平移
  });
});
