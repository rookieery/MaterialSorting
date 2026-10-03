// prd-initial-layout US-005（2026-10-03）EditCanvas「初始布局模式」可缺省 props：
//   1) 默认 props 回归锁：不传新 props = 现行编辑弹窗行为 —— 空格四态在场、组
//      标记 / 图例行缺席（既有 EditCanvas.test 64 例全绿为行为基线，此处补新增
//      视觉的缺席反向锁）。
//   2) allowMirror=false：空格收窄 {0°,180°} 两态掉头（两按回原始、mirror 恒无）、
//      O / I 镜像键零变换。
//   3) allowFineRotate=false：L/K（含 Shift ±10°）零变换。
//   4) pieceGroup 整组拖动：全组同 delta 联动（store 多条 setWorkingItem + DOM
//      5 层同帧）、组包络钳制（minX≥0 / minY≥0 / maxY≤gate，钳 delta 非逐片）、
//      非成员不动；Alt+左键组拖不吸附；组内单片不可编辑（键盘全键 + 旋转手柄
//      隐藏 + 点柄位防御零变换）；非成员片拖动 / 空格 / 吸附照常；组成员视觉
//      标记（.edit-piece-grouped + data-edit-group）+ 指南图例行。
//   5) onIllegalOverlapCountChange：红色（非法）重叠片数回调 —— 重叠双方各计
//      1（pen>额度口径与指标面板同源）、琥珀（额度内压线）不计、拖动分离归零、
//      值变才触达、非选中路径（setWorkingItem 直写）同样触达。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditCanvas, type EditCanvasProps } from '../EditCanvas';
import { computeLayoutStats, useEditStore } from '../../../store/editStore';
import { runRegistry, type RunRecord } from '../../../store/runRegistry';
import type { PlacedItem, Polygon, Pt } from '../../../types/piece';
import type { FrameMsg, ManifestMsg } from '../../../types/ws';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  runRegistry.clear();
  useEditStore.getState().invalidate();
  // jsdom 无 PointerEvent —— polyfill（同 EditCanvas.test 套路）。
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

// ---- fixture：三片 500×500（gate 1000）；a/b 同 label g01（band 组语义）、c 独立 ----

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

/** caliber 双片：raw 500² / erode 490²、d=5（压线额度 d_i+d_j=10，琥珀/红边界）。 */
function makeManifestCaliber2(): ManifestMsg {
  const raw: Polygon = [
    [0, 0],
    [500, 0],
    [500, 500],
    [0, 500],
  ];
  const eroded: Polygon = [
    [5, 5],
    [495, 5],
    [495, 495],
    [5, 495],
  ];
  return {
    type: 'manifest',
    gate_mm: GATE,
    total_area_mm2: 500000,
    n_eroded: 2,
    pieces: [
      {
        id: 'a_28',
        label: 'g01',
        size: 28,
        color: '#ff0000',
        area_mm2: 250000,
        polygon: eroded,
        raw_polygon: raw,
        d_mm: 5,
      },
      {
        id: 'b_30',
        label: 'g02',
        size: 30,
        color: '#00ff00',
        area_mm2: 250000,
        polygon: eroded,
        raw_polygon: raw,
        d_mm: 5,
      },
    ],
  };
}

/** a@[0,0] + b@[600,0]（组）+ c@[1600,0]（非成员）→ 包络 maxX 2100。 */
const GROUP_PLACED: PlacedItem[] = [
  { id: 'a_28', rotation: 0, translation: [0, 0] },
  { id: 'b_30', rotation: 0, translation: [600, 0] },
  { id: 'c_32', rotation: 0, translation: [1600, 0] },
];

/** 组映射：a/b（band label g01 全部副本）→ 'band:g01'；其余 null。 */
function bandGroup(pid: string): string | null {
  return pid === 'a_28' || pid === 'b_30' ? 'band:g01' : null;
}

function seedRun(placed: PlacedItem[], manifest: ManifestMsg = makeManifest3()): RunRecord {
  const run = runRegistry.create(0);
  run.manifest = manifest;
  // 宽/密度与 computeLayoutStats 同口径（viewBox 初始锚；不影响交互断言）。
  const { widthMm, density } = computeLayoutStats(placed, manifest);
  const frame: FrameMsg = {
    type: 'frame',
    index: 0,
    elapsed: 1,
    phase: 'final',
    density,
    density_sparrow: 0.5,
    width_mm: widthMm,
    placed_items: placed.map((it) => ({
      id: it.id,
      rotation: it.rotation,
      translation: [it.translation[0], it.translation[1]] as [number, number],
      ...(it.mirror === true ? { mirror: true } : {}),
    })),
  };
  run.frames.push(frame);
  run.lastFrame = frame;
  run.finalDensity = density;
  return run;
}

/** 挂载（US-005 props 直传；mode 恒 full —— 形态与本文件断言面无关）。 */
function mountInitial(
  props: Partial<EditCanvasProps> = {},
  run: RunRecord = seedRun(GROUP_PLACED),
): SVGSVGElement {
  act(() => {
    useEditStore.getState().open(run);
  });
  act(() => {
    root!.render(<EditCanvas mode="full" {...props} />);
  });
  return document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
}

function roughPolyOf(svg: SVGSVGElement, stroke: string): SVGPolygonElement {
  const el = svg.querySelector(`:scope g > polygon[stroke="${stroke}"]`);
  if (!el) throw new Error(`rough polygon ${stroke} not found`);
  return el as SVGPolygonElement;
}

function mockRect(svg: SVGSVGElement, width: number, height: number): void {
  (svg as unknown as { getBoundingClientRect: () => DOMRect }).getBoundingClientRect = () =>
    ({ width, height, x: 0, y: 0, top: 0, left: 0, right: width, bottom: height }) as DOMRect;
}

function firePointer(
  el: Element,
  type: 'pointerdown' | 'pointermove' | 'pointerup',
  clientX: number,
  clientY: number,
  button = 0,
  alt = false,
): void {
  el.dispatchEvent(
    new PointerEvent(type, {
      bubbles: true,
      cancelable: true,
      pointerId: 1,
      clientX,
      clientY,
      button,
      altKey: alt,
    }),
  );
}

function fireKey(
  target: EventTarget,
  key: string,
  opts?: { shiftKey?: boolean; repeat?: boolean },
): void {
  target.dispatchEvent(
    new KeyboardEvent('keydown', {
      key,
      bubbles: true,
      cancelable: true,
      shiftKey: opts?.shiftKey ?? false,
      repeat: opts?.repeat ?? false,
    }),
  );
}

/** 选中并收手（无拖动位移）。 */
function selectPiece(svg: SVGSVGElement, stroke: string): void {
  act(() => {
    const p = roughPolyOf(svg, stroke);
    firePointer(p, 'pointerdown', 10, 10);
    firePointer(p, 'pointerup', 10, 10);
  });
}

/** working 值快照（toEqual 比较用）。 */
function snapshotWorking(): PlacedItem[] {
  return useEditStore
    .getState()
    .working.map((it) => ({ ...it, translation: [...it.translation] as Pt }));
}

// ============================================================
// 默认 props 回归锁（新增视觉缺席 + 四态在场）
// ============================================================

describe('EditCanvas 默认 props 回归锁 (US-005)', () => {
  it('不传新 props：组标记/图例行缺席、空格仍四态（第一按 = 垂直镜像 mirror+180）', () => {
    const svg = mountInitial({});
    expect(document.querySelector('[data-testid="edit-guide-group-row"]')).toBeNull();
    expect(document.querySelectorAll('.edit-piece-grouped').length).toBe(0);
    // 空格四态在场（两态掉头的第一按是 rot180 无 mirror —— mirror 位参与即可区分）。
    selectPiece(svg, '#0000ff');
    act(() => {
      fireKey(window, ' ');
    });
    const w = useEditStore.getState().working;
    expect(w[2].rotation).toBe(180);
    expect(w[2].mirror).toBe(true);
  });

  it('pieceGroup 在场但无成员命中（plain 布局映射全 null）→ 图例行不渲染、无标记', () => {
    mountInitial({ pieceGroup: () => null });
    expect(document.querySelector('[data-testid="edit-guide-group-row"]')).toBeNull();
    expect(document.querySelectorAll('.edit-piece-grouped').length).toBe(0);
  });
});

// ============================================================
// 手势收窄：allowMirror / allowFineRotate
// ============================================================

describe('EditCanvas allowMirror=false 空格两态 (US-005)', () => {
  const PLACED: PlacedItem[] = [
    { id: 'a_28', rotation: 0, translation: [600, 250] },
    { id: 'b_30', rotation: 0, translation: [1600, 250] },
    { id: 'c_32', rotation: 0, translation: [2600, 250] },
  ];

  it('空格 {0°,180°} 两态掉头：质心锚定精确值 + 两按回原始 + mirror 恒无', () => {
    const svg = mountInitial({ allowMirror: false }, seedRun(PLACED));
    selectPiece(svg, '#ff0000');
    act(() => {
      fireKey(window, ' ');
    });
    let w = useEditStore.getState().working;
    // c_world=(850,500)，rot180 c_local=(−250,−250) → t'=(1100,750)（钳制零干扰）
    expect(w[0].rotation).toBe(180);
    expect(w[0].translation[0]).toBeCloseTo(1100, 9);
    expect(w[0].translation[1]).toBeCloseTo(750, 9);
    expect(w[0].mirror).toBeUndefined();
    act(() => {
      fireKey(window, ' ');
    });
    w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(0);
    expect(w[0].translation[0]).toBeCloseTo(600, 9);
    expect(w[0].translation[1]).toBeCloseTo(250, 9);
    expect(w[0].mirror).toBeUndefined();
  });

  it('空格两态 × 残余角同款语义：37° ↔ 217° 交替（allowFineRotate 缺省不受扰）', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 37, translation: [600, 250] },
      { id: 'b_30', rotation: 0, translation: [1600, 250] },
      { id: 'c_32', rotation: 0, translation: [2600, 250] },
    ];
    const svg = mountInitial({ allowMirror: false }, seedRun(placed));
    selectPiece(svg, '#ff0000');
    act(() => {
      fireKey(window, ' ');
    });
    let w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(217); // 37 + 180（half 翻转）
    act(() => {
      fireKey(window, ' ');
    });
    w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(37); // 217 − 180（half 翻回，残余角保留）
    expect(w[0].mirror).toBeUndefined();
  });

  it('O / I 镜像键零变换（大小写同键命中）', () => {
    const svg = mountInitial({ allowMirror: false }, seedRun(PLACED));
    selectPiece(svg, '#ff0000');
    const before = snapshotWorking();
    act(() => {
      fireKey(window, 'o');
      fireKey(window, 'i');
      fireKey(window, 'O');
      fireKey(window, 'I');
    });
    expect(useEditStore.getState().working).toEqual(before);
  });
});

describe('EditCanvas allowFineRotate=false (US-005)', () => {
  it('L/K（含 Shift ±10°）零变换', () => {
    const svg = mountInitial({ allowFineRotate: false });
    selectPiece(svg, '#ff0000');
    const before = snapshotWorking();
    act(() => {
      fireKey(window, 'l');
      fireKey(window, 'k');
      fireKey(window, 'L', { shiftKey: true });
      fireKey(window, 'K', { shiftKey: true });
    });
    expect(useEditStore.getState().working).toEqual(before);
  });
});

// ============================================================
// pieceGroup 整组拖动
// ============================================================

describe('EditCanvas 整组拖动 (US-005)', () => {
  /** 拖动比尺：rect 1050×500 · viewBox 2100×1000 → meet s = 0.5 px/mm。 */

  it('命中组成员 → 全组同 delta 联动（store 多条 setWorkingItem + DOM 5 层同帧），非成员不动', () => {
    const svg = mountInitial({ pieceGroup: bandGroup });
    mockRect(svg, 1050, 500);
    const roughA = roughPolyOf(svg, '#ff0000');
    const roughB = roughPolyOf(svg, '#00ff00');
    act(() => {
      firePointer(roughA, 'pointerdown', 100, 100);
      firePointer(roughA, 'pointermove', 200, 100); // +100px → +200mm（dy 0）
      firePointer(roughA, 'pointerup', 200, 100);
    });
    const w = useEditStore.getState().working;
    expect(w[0].translation).toEqual([200, 0]);
    expect(w[1].translation).toEqual([800, 0]);
    expect(w[2].translation).toEqual([1600, 0]); // 非成员不动
    expect(w.map((it) => it.rotation)).toEqual([0, 0, 0]);
    // DOM 同帧落笔（两成员 points 都更新）
    expect(roughA.getAttribute('points')).toBe('200,0 700,0 700,500 200,500');
    expect(roughB.getAttribute('points')).toBe('800,0 1300,0 1300,500 800,500');
  });

  it('组包络钳制：minX<0 / minY<0 同 delta 截住（钳 delta 非逐片 —— 全组恒同位移）', () => {
    const run = seedRun([
      { id: 'a_28', rotation: 0, translation: [100, 100] },
      { id: 'b_30', rotation: 0, translation: [600, 100] },
      { id: 'c_32', rotation: 0, translation: [1600, 0] },
    ]);
    const svg = mountInitial({ pieceGroup: bandGroup }, run);
    mockRect(svg, 1050, 500);
    const roughA = roughPolyOf(svg, '#ff0000');
    act(() => {
      firePointer(roughA, 'pointerdown', 100, 100);
      // dx = −150px/0.5 = −300mm、dy = −(100px)/0.5 = −200mm
      firePointer(roughA, 'pointermove', -50, 200);
      firePointer(roughA, 'pointerup', -50, 200);
    });
    // 组 bbox0 = [100..1100]×[100..600]：原始 (−300,−200) → cdx=−100（minX 钳 0）、
    // cdy=−100（minY 钳 0）—— 全组同钳后位移。
    const w = useEditStore.getState().working;
    expect(w[0].translation).toEqual([0, 0]);
    expect(w[1].translation).toEqual([500, 0]);
  });

  it('组包络钳制：maxY>gate 组贴顶截住（dy 归零全组不动）', () => {
    const run = seedRun([
      { id: 'a_28', rotation: 0, translation: [100, 500] },
      { id: 'b_30', rotation: 0, translation: [600, 500] },
      { id: 'c_32', rotation: 0, translation: [1600, 0] },
    ]);
    const svg = mountInitial({ pieceGroup: bandGroup }, run);
    mockRect(svg, 1050, 500);
    const roughA = roughPolyOf(svg, '#ff0000');
    act(() => {
      firePointer(roughA, 'pointerdown', 100, 100);
      firePointer(roughA, 'pointermove', 100, 50); // dy = +100mm → 组 maxY 1100 > 1000
      firePointer(roughA, 'pointerup', 100, 50);
    });
    const w = useEditStore.getState().working;
    expect(w[0].translation).toEqual([100, 500]);
    expect(w[1].translation).toEqual([600, 500]);
  });

  it('组内单片不可编辑：键盘 L/K/空格/O/I/R 全零变换 + 旋转手柄隐藏（点柄位防御零变换）', () => {
    const svg = mountInitial({ pieceGroup: bandGroup });
    selectPiece(svg, '#ff0000');
    const before = snapshotWorking();
    act(() => {
      fireKey(window, 'l');
      fireKey(window, 'k');
      fireKey(window, ' ');
      fireKey(window, 'o');
      fireKey(window, 'i');
      fireKey(window, 'r');
    });
    expect(useEditStore.getState().working).toEqual(before);
    // 旋转手柄对组成员隐藏（display:none —— 无旋转 affordance）
    const handle = document.querySelector('[data-testid="edit-rotate-handle"]');
    expect(handle).not.toBeNull();
    expect((handle!.closest('g') as SVGGElement).style.display).toBe('none');
    // 防御双保险：直接派发 pointerdown 到隐藏手柄 → 不起会话零变换
    act(() => {
      firePointer(handle!, 'pointerdown', 10, 10);
      firePointer(handle!, 'pointermove', 80, 10);
      firePointer(handle!, 'pointerup', 80, 10);
    });
    expect(useEditStore.getState().working).toEqual(before);
    // 选中非成员后手柄恢复显示（成员资格判定不粘滞）
    selectPiece(svg, '#0000ff');
    const handle2 = document.querySelector('[data-testid="edit-rotate-handle"]');
    expect((handle2!.closest('g') as SVGGElement).style.display).toBe('');
  });

  it('Alt+左键组拖不吸附：留 6mm 缝松手落点原样（无伙伴高亮）', () => {
    const svg = mountInitial({ pieceGroup: bandGroup });
    mockRect(svg, 1050, 500);
    const roughA = roughPolyOf(svg, '#ff0000');
    act(() => {
      firePointer(roughA, 'pointerdown', 0, 100, 0, true);
      firePointer(roughA, 'pointermove', 247, 100, 0, true); // +494mm → 组 [494..1594]
      firePointer(roughA, 'pointerup', 247, 100, 0, true);
    });
    // 组右缘 1594 与非成员 c(1600) 留 6mm 缝（≤ ATTRACT_MAX_GAP 单片必吸）——
    // 组拖不吸附：全组落点 = 拖动结果原样。
    const w = useEditStore.getState().working;
    expect(w[0].translation).toEqual([494, 0]);
    expect(w[1].translation).toEqual([1094, 0]);
    expect(w[2].translation).toEqual([1600, 0]);
    expect(document.querySelector('[data-testid="edit-snap-partner"]')).toBeNull();
  });

  it('非成员片照常：拖动只动自身 + 空格四态在场（组映射不收窄非成员手势）', () => {
    const svg = mountInitial({ pieceGroup: bandGroup });
    mockRect(svg, 1050, 500);
    const roughC = roughPolyOf(svg, '#0000ff');
    act(() => {
      firePointer(roughC, 'pointerdown', 100, 100);
      firePointer(roughC, 'pointermove', 200, 100); // +200mm
      firePointer(roughC, 'pointerup', 200, 100);
    });
    const w = useEditStore.getState().working;
    expect(w[2].translation).toEqual([1800, 0]);
    expect(w[0].translation).toEqual([0, 0]);
    expect(w[1].translation).toEqual([600, 0]);
    // 键盘照常：空格第一按 = 垂直镜像（四态，非两态）
    act(() => {
      fireKey(window, ' ');
    });
    const w2 = useEditStore.getState().working;
    expect(w2[2].rotation).toBe(180);
    expect(w2[2].mirror).toBe(true);
  });

  it('非成员片 Alt+左键吸附照常（组映射在场不干扰）', () => {
    const svg = mountInitial({ pieceGroup: bandGroup });
    mockRect(svg, 1050, 500);
    const roughC = roughPolyOf(svg, '#0000ff');
    act(() => {
      firePointer(roughC, 'pointerdown', 200, 100, 0, true);
      // −494mm → c@[1106,0]，与组右缘 b(maxX 1100) 留 6mm 缝
      firePointer(roughC, 'pointermove', -47, 100, 0, true);
      firePointer(roughC, 'pointerup', -47, 100, 0, true);
    });
    const w = useEditStore.getState().working;
    expect(w[2].translation[0]).toBeCloseTo(1100, 8); // attract 吸到触点
    expect(w[2].translation[1]).toBeCloseTo(0, 9);
    expect(w[0].translation).toEqual([0, 0]);
    expect(w[1].translation).toEqual([600, 0]);
    expect(document.querySelector('[data-testid="edit-snap-partner"]')).not.toBeNull();
  });

  it('组成员视觉标记 + 指南图例行（.edit-piece-grouped + data-edit-group；非成员无标记）', () => {
    const svg = mountInitial({ pieceGroup: bandGroup });
    const a = roughPolyOf(svg, '#ff0000');
    const b = roughPolyOf(svg, '#00ff00');
    const c = roughPolyOf(svg, '#0000ff');
    expect(a.classList.contains('edit-piece-grouped')).toBe(true);
    expect(a.getAttribute('data-edit-group')).toBe('band:g01');
    expect(b.classList.contains('edit-piece-grouped')).toBe(true);
    expect(b.getAttribute('data-edit-group')).toBe('band:g01');
    expect(c.classList.contains('edit-piece-grouped')).toBe(false);
    expect(c.hasAttribute('data-edit-group')).toBe(false);
    const row = document.querySelector('[data-testid="edit-guide-group-row"]');
    expect(row?.textContent).toContain('组合成员片（整组拖动）');
    // 图例文案不回潮「形态/保存」（既有指南反向锁同款口径）
    const guideText = document.querySelector('[data-testid="edit-guide"]')?.textContent ?? '';
    expect(guideText).not.toContain('形态');
    expect(guideText).not.toContain('保存');
  });
});

// ============================================================
// onIllegalOverlapCountChange 非法重叠计数
// ============================================================

describe('EditCanvas onIllegalOverlapCountChange (US-005)', () => {
  it('红色重叠片数：重叠双方各计 1；拖动分离归零；值变才触达', () => {
    const spy = vi.fn();
    // a@[0,0] b@[400,50] 交 100×450（默认夹具无 d_mm → 额度 0；顶点采样 pen 50 > 0
    // → 红 —— y 错位 50 保证顶点严格落入，边对齐退化是指标面板同款已知近似口径）。
    const run = seedRun([
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [400, 50] },
    ]);
    const svg = mountInitial({ onIllegalOverlapCountChange: spy }, run);
    expect(spy).toHaveBeenCalledTimes(1); // 挂载首帧即触达（不依赖选中态）
    expect(spy).toHaveBeenLastCalledWith(2);
    // 拖 b 分离（+400mm → [800,50] 无相交邻居）→ 0
    mockRect(svg, 1050, 500);
    const roughB = roughPolyOf(svg, '#00ff00');
    act(() => {
      firePointer(roughB, 'pointerdown', 100, 100);
      firePointer(roughB, 'pointermove', 300, 100);
      firePointer(roughB, 'pointerup', 300, 100);
    });
    expect(spy).toHaveBeenLastCalledWith(0);
    expect(spy).toHaveBeenCalledTimes(2); // 值变才触达（终值单次）
  });

  it('琥珀（压线额度内）不计入、超额度红计入 —— 与指标面板同口径；非交互路径同样触达', () => {
    const spy = vi.fn();
    const run = seedRun(
      [
        { id: 'a_28', rotation: 0, translation: [0, 0] },
        { id: 'b_30', rotation: 0, translation: [495, 50] },
      ],
      makeManifestCaliber2(),
    );
    mountInitial({ onIllegalOverlapCountChange: spy }, run);
    // 交 5×450、pen 5.0 ≤ 额度 10 → 琥珀不计
    expect(spy).toHaveBeenLastCalledWith(0);
    // 直写 working（非选中路径）：b → [450,50] pen 50 > 额度 10 → 红双方
    act(() => {
      useEditStore.getState().setWorkingItem(1, { translation: [450, 50] });
    });
    expect(spy).toHaveBeenLastCalledWith(2);
  });

  it('回调缺席（默认 props）零计算零触达 —— 既有编辑弹窗行为不变锁', () => {
    const run = seedRun([
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [400, 50] },
    ]);
    expect(() => mountInitial({}, run)).not.toThrow();
  });
});
