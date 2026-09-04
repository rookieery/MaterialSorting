// 编辑排料 US-002 EditCanvas 单测：
//   1) 全量渲染骨架：bg / fab / 翻转组（translate(0 gate) scale(1 -1)）+ 5 层节点
//      （每 working 下标一份，与主视图 NestSVG 同构 —— points / 配色逐属性一致）
//   2) demand 多副本「出现序」：同 pid 两条 working → 两个独立 DOM 副本各承一处
//   3) 毛板模式：4 层工艺 display:none、毛版 + 尺码色保留；切回完整版可恢复
//   4) 滚轮指针锚缩放（mock CTM）：锚点经 world→user（gate−wy）换算 —— Y 翻转镜像
//      陷阱锁死；viewBox 变化后 clientToWorld 仍取回同一世界点（AC）
//   5) CTM 不可得 → 视图中心锚退化
//   6) 空白拖动平移（mock getBoundingClientRect）；毛版 polygon pointerdown 不起平移
//   7) ＋/－/重置视图按钮（中心锚）+ MIN_VB_W 钳制
//
// jsdom 缺口：PointerEvent 未实现（beforeEach polyfill）；getScreenCTM/createSVGPoint
// 缺失（mock 复合矩阵，同 editGeometry.test 套路）。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditCanvas, type EditViewMode } from '../EditCanvas';
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
  // jsdom 无 PointerEvent —— polyfill（PRD US-003 口径：extends MouseEvent 即可，
  // 本组件只读 pointerId/clientX/clientY）。
  (window as unknown as { PointerEvent?: unknown }).PointerEvent =
    class extends MouseEvent {};
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

// ---- fixture（数字全手算锁死）----
// gate 1000；a_28 = 500×500 全 5 层；b_30 = 500×500 仅毛版；placed a@[0,0] b@[600,0]
// → 包络 maxX = 1100（= frame.width_mm，computeLayoutStats 同值）；total_area 500000。

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
        net_polygon: [
          [50, 50], [450, 50], [450, 450], [50, 450],
        ],
        internal_lines: [
          [[100, 100], [400, 100]],
        ],
        notches: [
          [250, 0, 0, -1],
        ],
        grain_line: [100, 250, 400, 250],
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

/** a@[0,0] + b@[600,0]（包络 maxX 1100）。 */
const PLACED_AB: PlacedItem[] = [
  { id: 'a_28', rotation: 0, translation: [0, 0] },
  { id: 'b_30', rotation: 0, translation: [600, 0] },
];

function seedRun(placed: PlacedItem[], manifest: ManifestMsg = makeManifest()): RunRecord {
  const run = runRegistry.create(0);
  run.manifest = manifest;
  const width = 1100; // = ceil(包络 maxX)，与 computeLayoutStats 一致
  const frame: FrameMsg = {
    type: 'frame',
    index: 0,
    elapsed: 1,
    phase: 'final',
    density: manifest.total_area_mm2 / (width * manifest.gate_mm),
    density_sparrow: 0.5,
    width_mm: width,
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

function mountCanvas(mode: EditViewMode, run: RunRecord): SVGSVGElement {
  act(() => {
    useEditStore.getState().open(run);
  });
  act(() => {
    root!.render(<EditCanvas mode={mode} />);
  });
  return document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
}

function rerender(mode: EditViewMode): void {
  act(() => {
    root!.render(<EditCanvas mode={mode} />);
  });
}

/** 骨架断言用：svg 直子节点 [bg, fab, flipGroup]。 */
function skeleton(svg: SVGSVGElement): {
  bg: SVGRectElement;
  fab: SVGRectElement;
  g: SVGGElement;
} {
  expect(svg.childNodes.length).toBe(3);
  return {
    bg: svg.childNodes[0] as SVGRectElement,
    fab: svg.childNodes[1] as SVGRectElement,
    g: svg.childNodes[2] as SVGGElement,
  };
}

// ---- mock CTM（同 editGeometry.test 的 mockMat 套路）----

/** 2x3 仿射矩阵（DOMMatrix 2D：x' = a·x + c·y + e；y' = b·x + d·y + f）。 */
interface MockMat {
  a: number;
  b: number;
  c: number;
  d: number;
  e: number;
  f: number;
  inverse: () => MockMat;
}

function mockMat(a: number, b: number, c: number, d: number, e: number, f: number): MockMat {
  const inverse = (): MockMat => {
    const det = a * d - b * c;
    const ia = d / det;
    const ib = -b / det;
    const ic = -c / det;
    const id = a / det;
    return mockMat(ia, ib, ic, id, -(ia * e + ic * f), -(ib * e + id * f));
  };
  return { a, b, c, d, e, f, inverse };
}

/** mock flipGroup CTM + svg.createSVGPoint。 */
function mockCTM(svg: SVGSVGElement, g: SVGGElement, ctm: MockMat): void {
  (g as unknown as { getScreenCTM: () => MockMat }).getScreenCTM = () => ctm;
  (svg as unknown as { createSVGPoint: () => unknown }).createSVGPoint = () => {
    const pt = {
      x: 0,
      y: 0,
      matrixTransform(m: MockMat) {
        return { x: m.a * pt.x + m.c * pt.y + m.e, y: m.b * pt.x + m.d * pt.y + m.f };
      },
    };
    return pt;
  };
}

/** mock svg.getBoundingClientRect（平移比尺 s = min(w/vb.w, h/vb.h)）。 */
function mockRect(svg: SVGSVGElement, width: number, height: number): void {
  (svg as unknown as { getBoundingClientRect: () => DOMRect }).getBoundingClientRect = () =>
    ({ width, height, x: 0, y: 0, top: 0, left: 0, right: width, bottom: height }) as DOMRect;
}

function fireWheel(
  el: Element,
  clientX: number,
  clientY: number,
  deltaY: number,
): void {
  el.dispatchEvent(
    new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX, clientY, deltaY }),
  );
}

function firePointer(
  el: Element,
  type: 'pointerdown' | 'pointermove' | 'pointerup',
  clientX: number,
  clientY: number,
): void {
  el.dispatchEvent(
    new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: 1, clientX, clientY }),
  );
}

// ============================================================
// 全量渲染（5 层同构）
// ============================================================

describe('EditCanvas 全量渲染 (US-002)', () => {
  it('骨架：bg + fab + 翻转组 translate(0 1000) scale(1 -1)；初始 viewBox = 0 0 1100 1000', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const { bg, fab, g } = skeleton(svg);
    expect(bg.getAttribute('fill')).toBe('#eef0f3');
    expect(fab.getAttribute('stroke-dasharray')).toBe('8 5');
    expect(g.getAttribute('transform')).toBe('translate(0 1000) scale(1 -1)');
    expect(svg.getAttribute('viewBox')).toBe('0 0 1100 1000');
    expect(svg.getAttribute('preserveAspectRatio')).toBe('xMinYMid meet');
    // bg 跟随 viewBox 铺满；fab 世界锚定（宽 = 包络料长 1100 = computeLayoutStats）
    expect(bg.getAttribute('width')).toBe('1100');
    expect(bg.getAttribute('height')).toBe('1000');
    expect(fab.getAttribute('width')).toBe('1100');
    expect(fab.getAttribute('height')).toBe('1000');
  });

  it('5 层全量：每 working 下标一份节点，points / 配色与主视图 NestSVG 同构', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const { g } = skeleton(svg);
    // a_28（5 层）5 节点 + b_30（仅毛版）1 节点 = 6
    expect(g.childNodes.length).toBe(6);

    const roughA = g.childNodes[0] as SVGPolygonElement;
    expect(roughA.tagName).toBe('polygon');
    expect(roughA.getAttribute('fill')).toBe('#ff0000');
    expect(roughA.dataset.label).toBe('g01');
    expect(roughA.style.display).toBe(''); // placed → 显示
    expect(roughA.getAttribute('points')).toBe('0,0 500,0 500,500 0,500');

    const netA = g.childNodes[1] as SVGPolygonElement;
    expect(netA.getAttribute('stroke')).toBe('#33cc33');
    expect(netA.getAttribute('stroke-dasharray')).toBe('6 3');
    expect(netA.style.display).toBe('');
    expect(netA.getAttribute('points')).toBe('50,50 450,50 450,450 50,450');

    const internalA = g.childNodes[2] as SVGPolylineElement;
    expect(internalA.getAttribute('stroke')).toBe('#ff8c1a');
    expect(internalA.getAttribute('points')).toBe('100,100 400,100');
    expect(internalA.style.display).toBe('');

    // notch [250,0,0,-1]：法线 ±4（NOTCH_LEN_MM/2）→ (250,4)-(250,-4)
    const notchA = g.childNodes[3] as SVGLineElement;
    expect(notchA.getAttribute('stroke')).toBe('#ffd700');
    expect(notchA.getAttribute('x1')).toBe('250');
    expect(notchA.getAttribute('y1')).toBe('4');
    expect(notchA.getAttribute('x2')).toBe('250');
    expect(notchA.getAttribute('y2')).toBe('-4');
    expect(notchA.style.display).toBe('');

    const grainA = g.childNodes[4] as SVGLineElement;
    expect(grainA.getAttribute('stroke')).toBe('#e53e3e');
    expect(grainA.getAttribute('x1')).toBe('100');
    expect(grainA.getAttribute('y1')).toBe('250');
    expect(grainA.getAttribute('x2')).toBe('400');
    expect(grainA.getAttribute('y2')).toBe('250');
    expect(grainA.style.display).toBe('');

    const roughB = g.childNodes[5] as SVGPolygonElement;
    expect(roughB.getAttribute('fill')).toBe('#00ff00');
    expect(roughB.getAttribute('points')).toBe('600,0 1100,0 1100,500 600,500');
    expect(roughB.style.display).toBe('');
  });

  it('旋转 + 平移与主视图同公式（b 片 rot 90 tr [600,0]）', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 90, translation: [600, 0] },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    const { g } = skeleton(svg);
    const roughB = g.childNodes[5] as SVGPolygonElement;
    // (0,0)→(600,0)；(500,0)→(0,500)+(600,0)=(600,500)；(500,500)→(−500,500)+(600,0)=(100,500)；
    // (0,500)→(−500,0)+(600,0)=(100,0) —— 与 NestSVG rotation 90° 用例同公式（r2 截断）
    expect(roughB.getAttribute('points')).toBe('600,0 600,500 100,500 100,0');
  });

  it('多副本「出现序」：同 pid 两条 working → 两个独立 DOM 副本各承一处（不互相覆盖）', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'a_28', rotation: 0, translation: [600, 0] },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    const { g } = skeleton(svg);
    // a_28 5 层 × 2 副本 = 10 节点
    expect(g.childNodes.length).toBe(10);
    const polys = Array.from(g.querySelectorAll('polygon')).filter(
      (p) => p.getAttribute('stroke') === '#ff0000',
    );
    expect(polys.length).toBe(2);
    // 第 k 次出现 → 第 k 副本（编辑 store 下标寻址口径）
    expect(polys[0].getAttribute('points')).toBe('0,0 500,0 500,500 0,500');
    expect(polys[1].getAttribute('points')).toBe('600,0 1100,0 1100,500 600,500');
    expect(polys[0].style.display).toBe('');
    expect(polys[1].style.display).toBe('');
  });

  it('working 变化（同 manifest）只更新 points 不重建骨架', () => {
    const run = seedRun(PLACED_AB);
    const svg = mountCanvas('full', run);
    const { g } = skeleton(svg);
    const roughB = g.childNodes[5] as SVGPolygonElement;
    const nodesBefore = g.childNodes.length;

    act(() => {
      useEditStore.getState().setWorkingItem(1, { translation: [700, 100] });
    });
    // 同 pidSeq（a_28 b_30）→ 不重建；b 毛版 points 更新（+100,+100）
    expect(g.childNodes.length).toBe(nodesBefore);
    expect(roughB.getAttribute('points')).toBe('700,100 1200,100 1200,600 700,600');
    // fab 宽随包络伸缩（maxX 1200）—— 与状态条同一真相源
    const fab = svg.childNodes[1] as SVGRectElement;
    expect(fab.getAttribute('width')).toBe('1200');
  });
});

// ============================================================
// 完整版 / 毛板切换
// ============================================================

describe('EditCanvas 毛板模式 (US-002)', () => {
  it("mode='rough'：4 层工艺 display:none、毛版 + 尺码色保留；切回 'full' 恢复", () => {
    const run = seedRun(PLACED_AB);
    const svg = mountCanvas('full', run);
    const { g } = skeleton(svg);

    rerender('rough');
    const roughA = g.childNodes[0] as SVGPolygonElement;
    const netA = g.childNodes[1] as SVGPolygonElement;
    const internalA = g.childNodes[2] as SVGPolylineElement;
    const notchA = g.childNodes[3] as SVGLineElement;
    const grainA = g.childNodes[4] as SVGLineElement;
    // 毛版恒显 + 尺码色保留
    expect(roughA.style.display).toBe('');
    expect(roughA.getAttribute('fill')).toBe('#ff0000');
    // 4 层工艺隐藏
    expect(netA.style.display).toBe('none');
    expect(internalA.style.display).toBe('none');
    expect(notchA.style.display).toBe('none');
    expect(grainA.style.display).toBe('none');
    // 节点不重建（display 切换可恢复、即时）
    expect(g.childNodes.length).toBe(6);

    rerender('full');
    expect(roughA.style.display).toBe('');
    expect(netA.style.display).toBe('');
    expect(internalA.style.display).toBe('');
    expect(notchA.style.display).toBe('');
    expect(grainA.style.display).toBe('');
  });
});

// ============================================================
// 滚轮缩放（指针锚）
// ============================================================

describe('EditCanvas 滚轮缩放 (US-002)', () => {
  it('指针锚缩放：world→user 换算（gate−wy），锚点世界位置不动 —— Y 翻转镜像陷阱锁死', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const { g } = skeleton(svg);
    // rect 440×400 · viewBox 1100×1000 → meet scale 0.4（无 letterbox）：
    // client = (0.4·wx, 400 − 0.4·wy)
    mockCTM(svg, g, mockMat(0.4, 0, 0, -0.4, 0, 400));

    // 指针 client (176,120) → world (440,700) → user (440, 1000−700=300)
    // deltaY<0 放大 ×0.8：x = 440−440·0.8 = 88；y = 300−300·0.8 = 60；w=880 h=800
    // （若误用 worldY=700 当锚 → y = 700−700·0.8 = 140 ≠ 60 —— 本断言即锁此陷阱）
    act(() => {
      fireWheel(svg, 176, 120, -100);
    });
    expect(svg.getAttribute('viewBox')).toBe('88 60 880 800');
    // bg 跟随 viewBox；fab 世界锚定不动
    const bg = svg.childNodes[0] as SVGRectElement;
    const fab = svg.childNodes[1] as SVGRectElement;
    expect(bg.getAttribute('x')).toBe('88');
    expect(bg.getAttribute('y')).toBe('60');
    expect(bg.getAttribute('width')).toBe('880');
    expect(bg.getAttribute('height')).toBe('800');
    expect(fab.getAttribute('width')).toBe('1100');
    expect(fab.getAttribute('x')).toBe('0');
  });

  it('viewBox 已变化后 clientToWorld 仍取回同一世界点（AC：缩放链下坐标正确）', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const { g } = skeleton(svg);
    // 第一档：vb "0 0 1100 1000" → 缩放后 vb "88 60 880 800"
    mockCTM(svg, g, mockMat(0.4, 0, 0, -0.4, 0, 400));
    act(() => {
      fireWheel(svg, 176, 120, -100);
    });
    expect(svg.getAttribute('viewBox')).toBe('88 60 880 800');

    // 第二档：新 vb 下 meet scale = min(440/880, 400/800) = 0.5：
    // client = (0.5·(wx−88), 0.5·((1000−wy)−60)) = (0.5wx−44, 470−0.5wy)
    // 同一指针 client (176,120) 仍 = world (440,700)（缩放锚不动性）
    mockCTM(svg, g, mockMat(0.5, 0, 0, -0.5, -44, 470));
    act(() => {
      fireWheel(svg, 176, 120, -100);
    });
    // 锚 user (440,300)：x = 440−(440−88)·0.8 = 158.4；y = 300−(300−60)·0.8 = 108
    expect(svg.getAttribute('viewBox')).toBe('158.4 108 704 640');
  });

  it('deltaY>0 缩小 ×1.25（同锚公式）', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const { g } = skeleton(svg);
    mockCTM(svg, g, mockMat(0.4, 0, 0, -0.4, 0, 400));
    // 锚 user (440,300)：x = 440−440·1.25 = −110；y = 300−300·1.25 = −75
    act(() => {
      fireWheel(svg, 176, 120, 100);
    });
    expect(svg.getAttribute('viewBox')).toBe('-110 -75 1375 1250');
  });

  it('CTM 不可得 → 退化为视图中心锚', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const { g } = skeleton(svg);
    (g as unknown as { getScreenCTM: () => null }).getScreenCTM = () => null;
    act(() => {
      fireWheel(svg, 176, 120, -100);
    });
    // 中心 (550,500) k=0.8：x = 550−440 = 110；y = 500−400 = 100
    expect(svg.getAttribute('viewBox')).toBe('110 100 880 800');
  });
});

// ============================================================
// 平移 + 视图工具按钮
// ============================================================

describe('EditCanvas 平移与视图工具 (US-002)', () => {
  it('空白拖动平移：屏幕位移 / 比尺（meet min 比）反向移动 viewBox 原点', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    mockRect(svg, 440, 400); // s = min(440/1100, 400/1000) = 0.4 px/mm
    act(() => {
      firePointer(svg, 'pointerdown', 10, 20);
      firePointer(svg, 'pointermove', 34, 12); // dx=+24 dy=−8 → x −60 / y +20
    });
    expect(svg.getAttribute('viewBox')).toBe('-60 20 1100 1000');
    const bg = svg.childNodes[0] as SVGRectElement;
    expect(bg.getAttribute('x')).toBe('-60');
    expect(bg.getAttribute('y')).toBe('20');
    act(() => {
      firePointer(svg, 'pointerup', 34, 12);
    });
  });

  it('毛版 polygon pointerdown 不起平移（US-003 拖动接管预留）', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const { g } = skeleton(svg);
    mockRect(svg, 440, 400);
    const roughA = g.childNodes[0] as SVGPolygonElement;
    act(() => {
      firePointer(roughA, 'pointerdown', 10, 10); // target=polygon → 不起平移
      firePointer(svg, 'pointermove', 50, 40);
    });
    expect(svg.getAttribute('viewBox')).toBe('0 0 1100 1000');
  });

  it('＋/－ 按钮中心锚缩放、重置视图回初始', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const zoomIn = document.querySelector('[data-testid="edit-zoom-in"]') as HTMLButtonElement;
    const zoomOut = document.querySelector('[data-testid="edit-zoom-out"]') as HTMLButtonElement;
    const reset = document.querySelector('[data-testid="edit-zoom-reset"]') as HTMLButtonElement;

    act(() => {
      zoomIn.click();
    });
    expect(svg.getAttribute('viewBox')).toBe('110 100 880 800');
    act(() => {
      zoomOut.click(); // 中心 (550,500) ×1.25 → 恰回初始
    });
    expect(svg.getAttribute('viewBox')).toBe('0 0 1100 1000');

    act(() => {
      zoomIn.click();
      zoomIn.click();
    });
    expect(svg.getAttribute('viewBox')).toBe('198 180 704 640');
    act(() => {
      reset.click();
    });
    expect(svg.getAttribute('viewBox')).toBe('0 0 1100 1000');
  });

  it('连续放大钳制 MIN_VB_W=20（刀口级下限）', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const zoomIn = document.querySelector('[data-testid="edit-zoom-in"]') as HTMLButtonElement;
    act(() => {
      for (let i = 0; i < 25; i++) zoomIn.click();
    });
    const vb = svg.getAttribute('viewBox')!;
    const w = Number(vb.split(' ')[2]);
    expect(w).toBe(20);
  });
});
