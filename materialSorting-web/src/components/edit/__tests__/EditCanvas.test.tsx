// 编辑排料 US-002 EditCanvas 单测 + US-003 拖动/旋转/重合指标：
//   1) 全量渲染骨架：bg / fab / 翻转组（translate(0 gate) scale(1 -1)）+ 5 层节点
//      （每 working 下标一份，与主视图 NestSVG 同构 —— points / 配色逐属性一致）
//   2) demand 多副本「出现序」：同 pid 两条 working → 两个独立 DOM 副本各承一处
//   3) 毛板模式：4 层工艺 display:none、毛版 + 尺码色保留；切回完整版可恢复
//   4) 滚轮指针锚缩放（mock CTM）：锚点经 world→user（gate−wy）换算 —— Y 翻转镜像
//      陷阱锁死；viewBox 变化后 clientToWorld 仍取回同一世界点（AC）
//   5) CTM 不可得 → 视图中心锚退化
//   6) 空白拖动平移（mock getBoundingClientRect）；毛版 polygon pointerdown 不起平移
//   7) 滚轮中心锚缩放（CTM 缺席退化）+「全览」按钮复位 + MIN_VB_W 钳制
//      （± 放缩按钮 2026-09-05 删除 —— 滚轮唯一缩放入口；指南卡片/工具区形态 select 同日加；
//       同日四轮：形态标题文案删 + 指南「形态/保存」两行删，反向锁见工具区用例）
//   US-003：8) 拖动（translation 精确值 / 提层 / 多副本 / fab 伸缩）
//           9) 钳制（Y 下界上界按被拖片 bbox / x<0 钳 0 / 右界自由）
//          10) 旋转（手柄绕质心自由角 + pivot 随动 + 布纹线随转 / 空白点击取消选中）
//          11) 重合指标（三值精确 / ≤10 琥珀 / >10 红 / >45° 红 / 拖动中 rAF 实时）
//   edit-keyboard US-005：12) 键盘变换（L/K/Shift/空格/O/I 逐键精确值 + 质心锚定
//              片不漂移 + clamp + e.repeat 规则 + 守卫链逐条：表单控件/无选中/禁用）
//   edit-keyboard US-006：13) R 键片级重置（拖动+L 旋转+O 镜像后按 R 逐字段回算法
//              基线（mirror 清零）、其余片与 lastFrame 不动、5 层 points + 指标/手柄
//              同帧回基线；e.repeat 忽略 + 守卫链：未选中/确认层打开/resetItem
//              守卫 false 静默不动不炸）
//
// jsdom 缺口：PointerEvent 未实现（beforeEach polyfill）；getScreenCTM/createSVGPoint
// 缺失（mock 复合矩阵，同 editGeometry.test 套路）。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditCanvas, type EditViewMode } from '../EditCanvas';
import { useEditStore } from '../../../store/editStore';
import { runRegistry, type RunRecord } from '../../../store/runRegistry';
import { transformPolygon } from '../../../lib/editGeometry';
import type { PlacedItem, Pt } from '../../../types/piece';
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
      // edit-keyboard US-003：镜像夹具透传（omit-when-false —— 无镜像项零键，既有
      // 用例 placed 项无 mirror → 字节级不变）。
      ...(it.mirror === true ? { mirror: true } : {}),
    })),
  };
  run.frames.push(frame);
  run.lastFrame = frame;
  run.finalDensity = frame.density;
  return run;
}

function mountCanvas(
  mode: EditViewMode,
  run: RunRecord,
  interactionEnabled = true,
): SVGSVGElement {
  act(() => {
    useEditStore.getState().open(run);
  });
  act(() => {
    root!.render(<EditCanvas mode={mode} interactionEnabled={interactionEnabled} />);
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

/** 键盘变换（edit-keyboard US-005）：target 上派发 keydown（window = 画布常规路径；
 *  控件元素 = 守卫链用例 —— bubbles 到 window 时 target 是控件本身）。 */
function fireKey(
  target: EventTarget,
  key: string,
  opts?: { shiftKey?: boolean; repeat?: boolean },
): KeyboardEvent {
  const ev = new KeyboardEvent('keydown', {
    key,
    bubbles: true,
    cancelable: true,
    shiftKey: opts?.shiftKey ?? false,
    repeat: opts?.repeat ?? false,
  });
  target.dispatchEvent(ev);
  return ev;
}

/** 世界多边形顶点均值（质心锚定「片不漂移」断言用，与组件 centroidOf 同式）。 */
function polyCentroid(poly: readonly Pt[]): Pt {
  let x = 0;
  let y = 0;
  for (const p of poly) {
    x += p[0];
    y += p[1];
  }
  return [x / poly.length, y / poly.length];
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

  it('毛版 polygon pointerdown 不起平移（归 US-003 拖动接管 —— viewBox 不动）', () => {
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

  it('滚轮中心锚缩放（CTM 缺席退化）+「全览」复位初始；± 按钮已删除（2026-09-05）', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const { g } = skeleton(svg);
    // CTM 缺席 → 滚轮锚退化视图中心（与旧 ± 按钮同数学：k=0.8/1.25 中心锚）
    (g as unknown as { getScreenCTM: () => null }).getScreenCTM = () => null;
    const reset = document.querySelector('[data-testid="edit-zoom-reset"]') as HTMLButtonElement;
    expect(reset.textContent).toContain('全览');
    expect(document.querySelector('[data-testid="edit-zoom-in"]')).toBeNull();
    expect(document.querySelector('[data-testid="edit-zoom-out"]')).toBeNull();

    act(() => {
      fireWheel(svg, 176, 120, -100); // deltaY<0 → 放大 k=0.8（中心 (550,500)）
    });
    expect(svg.getAttribute('viewBox')).toBe('110 100 880 800');
    act(() => {
      fireWheel(svg, 176, 120, 100); // deltaY>0 → 缩小 k=1.25 → 恰回初始
    });
    expect(svg.getAttribute('viewBox')).toBe('0 0 1100 1000');

    act(() => {
      fireWheel(svg, 176, 120, -100);
      fireWheel(svg, 176, 120, -100);
    });
    expect(svg.getAttribute('viewBox')).toBe('198 180 704 640');
    act(() => {
      reset.click();
    });
    expect(svg.getAttribute('viewBox')).toBe('0 0 1100 1000');
  });

  it('连续滚轮放大钳制 MIN_VB_W=20（刀口级下限）', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const { g } = skeleton(svg);
    (g as unknown as { getScreenCTM: () => null }).getScreenCTM = () => null;
    act(() => {
      for (let i = 0; i < 25; i++) fireWheel(svg, 176, 120, -100);
    });
    const vb = svg.getAttribute('viewBox')!;
    const w = Number(vb.split(' ')[2]);
    expect(w).toBe(20);
  });

  it('工具区 =「全览」+ 形态 select（无标题文案，四轮删）+ 操作指南卡片常驻（五条手势 + 键盘行）', () => {
    mountCanvas('full', seedRun(PLACED_AB));
    // 形态 select 在画布左上工具区内（footer 仅存保存按钮）；2026-09-05 四轮起
    // 「形态」标题文案删除 —— label 内不得再有文本节点（option 文案在 select 内）。
    const modeLabel = document.querySelector('.edit-layout-canvas-tools .edit-layout-mode');
    expect(modeLabel?.querySelector('[data-testid="edit-layout-mode"]')).not.toBeNull();
    const labelOwnText = Array.from(modeLabel?.childNodes ?? [])
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => n.textContent?.trim() ?? '')
      .join('');
    expect(labelOwnText).toBe('');
    // 操作指南（画布右下）：五条画布手势 + edit-keyboard US-005 键盘行逐关键词在场；
    // 四轮删的「形态」「保存」两行不得回潮（反向锁 —— 键盘行文案同样避开二词）。
    const guide = document.querySelector('[data-testid="edit-guide"]');
    expect(guide).not.toBeNull();
    const text = guide?.textContent ?? '';
    for (const kw of ['拖动裁片', '旋转', '滚轮', '平移', '取消选中', '键盘']) {
      expect(text).toContain(kw);
    }
    for (const gone of ['形态', '保存']) {
      expect(text).not.toContain(gone);
    }
  });
});

// ============================================================
// 拖动（US-003）：translation 精确断言 / 提层 / 多副本 / fab 伸缩
// ============================================================

/** 拖动夹具比尺：rect 550×500 · viewBox 1100×1000 → meet s = 0.5 px/mm（整除友好）。 */

function roughPolyOf(svg: SVGSVGElement, stroke: string): SVGPolygonElement {
  const el = svg.querySelector(`:scope g > polygon[stroke="${stroke}"]`);
  if (!el) throw new Error(`rough polygon ${stroke} not found`);
  return el as SVGPolygonElement;
}

describe('EditCanvas 拖动 (US-003)', () => {
  it('拖动更新 working 下标项 translation（精确值）+ 被拖片 points + fab 随包络伸缩', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    mockRect(svg, 550, 500); // s = 0.5
    const roughB = roughPolyOf(svg, '#00ff00');
    act(() => {
      firePointer(roughB, 'pointerdown', 100, 100);
      firePointer(roughB, 'pointermove', 200, 50); // dClient (100,-50) → world (200,+100)
      firePointer(roughB, 'pointerup', 200, 50);
    });
    const w = useEditStore.getState().working;
    expect(w[1].rotation).toBe(0);
    expect(w[1].translation[0]).toBeCloseTo(800, 10);
    expect(w[1].translation[1]).toBeCloseTo(100, 10);
    expect(w[0].translation).toEqual([0, 0]); // 其余片不动
    expect(roughB.getAttribute('points')).toBe('800,100 1300,100 1300,600 800,600');
    const fab = svg.childNodes[1] as SVGRectElement;
    expect(fab.getAttribute('width')).toBe('1300'); // maxX 1300（右界自由拖）
  });

  it('被拖片提层置顶（5 层节点移到全部裁片之上、UI 覆盖层之下）+ 手柄出现', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const { g } = skeleton(svg);
    const roughA = g.childNodes[0] as SVGPolygonElement;
    act(() => {
      firePointer(roughA, 'pointerdown', 10, 10);
      firePointer(roughA, 'pointerup', 10, 10);
    });
    // 原 [a×5, b] → 提层后 [b, a×5, uiLayer]
    expect(g.childNodes.length).toBe(7);
    expect((g.childNodes[0] as SVGPolygonElement).getAttribute('fill')).toBe('#00ff00');
    expect(g.childNodes[0]).not.toBe(roughA);
    const uiLayer = g.childNodes[6] as SVGGElement;
    expect(uiLayer.childNodes.length).toBe(2); // overlapG + handleG
    expect(document.querySelector('[data-testid="edit-rotate-handle"]')).not.toBeNull();
  });

  it('多副本：同 pid 两条 working，拖第 2 副本只动下标 1（出现序寻址）', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'a_28', rotation: 0, translation: [600, 0] },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    mockRect(svg, 550, 500);
    const copies = Array.from(
      svg.querySelectorAll(':scope g > polygon[stroke="#ff0000"]'),
    ) as SVGPolygonElement[];
    expect(copies.length).toBe(2);
    act(() => {
      firePointer(copies[1], 'pointerdown', 100, 100);
      firePointer(copies[1], 'pointermove', 150, 100); // dx=50px → +100mm
      firePointer(copies[1], 'pointerup', 150, 100);
    });
    const w = useEditStore.getState().working;
    expect(w[0].translation).toEqual([0, 0]);
    expect(w[1].translation[0]).toBeCloseTo(700, 10);
    expect(w[1].translation[1]).toBeCloseTo(0, 10);
  });
});

// ============================================================
// 拖动钳制（US-003）：Y ∈ [0,gate] 按被拖片 bbox / x<0 钳 0 / 右界自由
// ============================================================

describe('EditCanvas 拖动钳制 (US-003)', () => {
  it('Y 下界：被拖片 bbox minY<0 上抬至 0', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [600, 100] },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    mockRect(svg, 550, 500);
    const roughB = roughPolyOf(svg, '#00ff00');
    act(() => {
      firePointer(roughB, 'pointerdown', 100, 100);
      firePointer(roughB, 'pointermove', 100, 300); // dy_world=-400 → 候选 ty=-300
      firePointer(roughB, 'pointerup', 100, 300);
    });
    const w = useEditStore.getState().working;
    expect(w[1].translation[1]).toBeCloseTo(0, 9); // 钳到 0（未钳为 -300）
    expect(w[1].translation[0]).toBeCloseTo(600, 10);
  });

  it('Y 上界：被拖片 bbox maxY>gate 下压至 gate（gate=1000）', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [600, 600] },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    mockRect(svg, 550, 500);
    const roughB = roughPolyOf(svg, '#00ff00');
    act(() => {
      firePointer(roughB, 'pointerdown', 100, 100);
      firePointer(roughB, 'pointermove', 100, 20); // dy_world=+160 → 候选 ty=760、maxY=1260
      firePointer(roughB, 'pointerup', 100, 20);
    });
    const w = useEditStore.getState().working;
    expect(w[1].translation[1]).toBeCloseTo(500, 9); // maxY 1260→1000：ty 760→500
  });

  it('x<0 钳 0；x 右界不钳（自由拖出原布局）', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [100, 0] },
      { id: 'b_30', rotation: 0, translation: [600, 0] },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    mockRect(svg, 550, 500);
    const roughA = roughPolyOf(svg, '#ff0000');
    act(() => {
      firePointer(roughA, 'pointerdown', 100, 100);
      firePointer(roughA, 'pointermove', 0, 100); // dx_world=-200 → 候选 tx=-100
      firePointer(roughA, 'pointerup', 0, 100);
    });
    expect(useEditStore.getState().working[0].translation[0]).toBeCloseTo(0, 9); // 钳 0

    act(() => {
      firePointer(roughA, 'pointerdown', 100, 100);
      firePointer(roughA, 'pointermove', 400, 100); // dx_world=+600 → 0+600=600（右界无钳）
      firePointer(roughA, 'pointerup', 400, 100);
    });
    expect(useEditStore.getState().working[0].translation[0]).toBeCloseTo(600, 10);
  });
});

// ============================================================
// 旋转（US-003）：选中片质心上方手柄，拖柄绕质心自由转角
// ============================================================

describe('EditCanvas 旋转 (US-003)', () => {
  it('拖旋转手柄：绕质心转 90°（自由角，无吸附）+ translation pivot 随动 + 布纹线随转', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    const { g } = skeleton(svg);
    // CTM mock：world = (2.5·cx, 1000 − 2.5·cy)
    mockCTM(svg, g, mockMat(0.4, 0, 0, -0.4, 0, 400));
    // 先选中 a（质心 (250,250)，grain (100,250)-(400,250)）
    const roughA = g.childNodes[0] as SVGPolygonElement;
    act(() => {
      firePointer(roughA, 'pointerdown', 10, 10);
      firePointer(roughA, 'pointerup', 10, 10);
    });
    const handle = document.querySelector(
      '[data-testid="edit-rotate-handle"]',
    ) as SVGCircleElement;
    // 起手 world (625,625)：绕质心方位角 45°；收手 world (-125,625)：方位角 135° → dAng=+90
    act(() => {
      firePointer(handle, 'pointerdown', 250, 150);
      firePointer(handle, 'pointermove', -50, 150);
      firePointer(handle, 'pointerup', -50, 150);
    });
    const w = useEditStore.getState().working;
    expect(w[0].rotation).toBeCloseTo(90, 6);
    // pivot 公式：t' = (250,250) + R(90)((0,0)-(250,250)) = (500,0)；方块绕质心转 90°
    // 足印不变（[0,500]²）→ 无钳制介入
    expect(w[0].translation[0]).toBeCloseTo(500, 6);
    expect(w[0].translation[1]).toBeCloseTo(0, 6);
    // 布纹线随片同步旋转：(100,250)→(250,100)、(400,250)→(250,400)（r2 截断字符串）
    const grainA = svg.querySelector(':scope g > line[stroke="#e53e3e"]') as SVGLineElement;
    expect(grainA.getAttribute('x1')).toBe('250');
    expect(grainA.getAttribute('y1')).toBe('100');
    expect(grainA.getAttribute('x2')).toBe('250');
    expect(grainA.getAttribute('y2')).toBe('400');
    // 毛版 points：R(90) (x,y)→(−y,x) + (500,0) —— 顶点序重排但足印同方 [0,500]²
    expect(roughA.getAttribute('points')).toBe('500,0 500,500 0,500 0,0');
  });

  it('手柄只对选中片出现（质心上方）；空白点击取消选中', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    expect(document.querySelector('[data-testid="edit-rotate-handle"]')).toBeNull();
    expect(document.querySelector('[data-testid="edit-metrics"]')).toBeNull();
    const roughB = roughPolyOf(svg, '#00ff00');
    act(() => {
      firePointer(roughB, 'pointerdown', 10, 10);
      firePointer(roughB, 'pointerup', 10, 10);
    });
    const handle = document.querySelector(
      '[data-testid="edit-rotate-handle"]',
    ) as SVGCircleElement;
    expect(handle).not.toBeNull();
    // b@[600,0] 质心 (850,250)：手柄在质心正上方（世界 +Y = 翻转组内屏幕上方）
    expect(Number(handle.getAttribute('cx'))).toBeCloseTo(850, 6);
    expect(Number(handle.getAttribute('cy'))).toBeGreaterThan(250);
    expect(document.querySelector('[data-testid="edit-metrics"]')).not.toBeNull();
    // 空白点击（无位移 down-up）→ 取消选中
    act(() => {
      firePointer(svg, 'pointerdown', 5, 5);
      firePointer(svg, 'pointerup', 5, 5);
    });
    expect(document.querySelector('[data-testid="edit-metrics"]')).toBeNull();
    const handleG = handle.parentNode as SVGGElement;
    expect(handleG.style.display).toBe('none');
  });
});

// ============================================================
// 重合指标（US-003）：三值精确 / 阈值着色 / 高亮 / 拖动中实时
// ============================================================

function metricsText(id: string): string {
  const el = document.querySelector(`[data-testid="${id}"]`);
  if (!el) throw new Error(`metrics ${id} not found`);
  return el.textContent ?? '';
}

function metricsClass(id: string): string {
  const el = document.querySelector(`[data-testid="${id}"]`);
  if (!el) throw new Error(`metrics ${id} not found`);
  return (el as HTMLElement).className;
}

/** 选中并收手（无拖动位移）。 */
function selectPiece(svg: SVGSVGElement, stroke: string): void {
  act(() => {
    const p = roughPolyOf(svg, stroke);
    firePointer(p, 'pointerdown', 10, 10);
    firePointer(p, 'pointerup', 10, 10);
  });
}

describe('EditCanvas 重合指标 (US-003)', () => {
  it('无重合：面积 0 / 穿透 0（中性色）/ 偏离 0°，无交集高亮；脚注注明算法碰撞口径', () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB)); // a/b 相离
    selectPiece(svg, '#00ff00');
    expect(metricsText('edit-metrics-area')).toBe('0.0 mm²（0.00 cm²）');
    expect(metricsText('edit-metrics-depth')).toBe('0.0 mm');
    expect(metricsClass('edit-metrics-depth')).not.toContain('warn');
    expect(metricsClass('edit-metrics-depth')).not.toContain('danger');
    expect(metricsText('edit-metrics-rot')).toBe('0.0°');
    expect(svg.querySelectorAll('polygon[fill="rgba(255, 64, 64, 0.42)"]').length).toBe(0);
    expect(document.querySelector('[data-testid="edit-metrics"]')!.textContent).toContain(
      '按算法碰撞口径',
    );
  });

  it('重合精确值：面积 50×450=22500 mm²（225.00 cm²）、穿透 50.0 mm → >10 红', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [450, 50] },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    selectPiece(svg, '#00ff00');
    expect(metricsText('edit-metrics-area')).toBe('22500.0 mm²（225.00 cm²）');
    expect(metricsText('edit-metrics-depth')).toBe('50.0 mm');
    expect(metricsClass('edit-metrics-depth')).toContain('danger');
    expect(metricsClass('edit-metrics-depth')).not.toContain('warn');
    // bbox 相交邻居渲染红色半透明交集 polygon（一个邻居 ≥1 环）
    expect(
      svg.querySelectorAll('polygon[fill="rgba(255, 64, 64, 0.42)"]').length,
    ).toBeGreaterThan(0);
  });

  it('穿透 ≤10mm 琥珀：b@[495,50] 交 5×450、穿透 5.0', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [495, 50] },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    selectPiece(svg, '#00ff00');
    expect(metricsText('edit-metrics-area')).toBe('2250.0 mm²（22.50 cm²）');
    expect(metricsText('edit-metrics-depth')).toBe('5.0 mm');
    expect(metricsClass('edit-metrics-depth')).toContain('warn');
    expect(metricsClass('edit-metrics-depth')).not.toContain('danger');
  });

  it('旋转偏离 >45° 红：b rot 90（面积 400×450=180000、穿透 50）', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 90, translation: [600, 50] },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    selectPiece(svg, '#00ff00');
    expect(metricsText('edit-metrics-area')).toBe('180000.0 mm²（1800.00 cm²）');
    expect(metricsText('edit-metrics-depth')).toBe('50.0 mm');
    expect(metricsText('edit-metrics-rot')).toBe('90.0°');
    expect(metricsClass('edit-metrics-rot')).toContain('danger');
  });

  it('拖动中（rAF 帧）指标实时刷新 —— 无需抬手', async () => {
    const svg = mountCanvas('full', seedRun(PLACED_AB));
    mockRect(svg, 550, 500);
    const roughB = roughPolyOf(svg, '#00ff00');
    act(() => {
      firePointer(roughB, 'pointerdown', 100, 100);
    });
    expect(metricsText('edit-metrics-area')).toBe('0.0 mm²（0.00 cm²）'); // 起手无重合
    act(() => {
      firePointer(roughB, 'pointermove', 25, 75); // dClient(-75,-25) → world(-150,+50) → b@[450,50]
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30)); // 等 rAF 帧落（拖动未抬手）
    });
    expect(metricsText('edit-metrics-area')).toBe('22500.0 mm²（225.00 cm²）');
    expect(metricsText('edit-metrics-depth')).toBe('50.0 mm');
    expect(
      svg.querySelectorAll('polygon[fill="rgba(255, 64, 64, 0.42)"]').length,
    ).toBeGreaterThan(0);
    act(() => {
      firePointer(roughB, 'pointerup', 25, 75);
    });
  });
});

// ============================================================
// 镜像渲染（edit-keyboard US-003）：working 项 mirror:true → 5 层 points/端点
// 全部 x 取负（局部 x 翻转 → 旋转 → 平移，x′ = −x·c − y·s + tx）；placementSig
// 含 mirror 段；拖动帧 clamp/池增量/DOM 同口径透传（applyEditPlacement 覆写语义）。
// ============================================================

describe('EditCanvas 镜像渲染 (edit-keyboard US-003)', () => {
  it('mirror:true 5 层 points 全部 x 取负（手算对拍）；无镜像片逐字节不变', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [600, 0], mirror: true },
      { id: 'b_30', rotation: 0, translation: [600, 0] },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    const { g } = skeleton(svg);
    // 毛版 [[0,0],[500,0],[500,500],[0,500]]：x′ = −x + 600
    const roughA = g.childNodes[0] as SVGPolygonElement;
    expect(roughA.getAttribute('points')).toBe('600,0 100,0 100,500 600,500');
    // 净版 [[50,50],[450,50],[450,450],[50,450]] → (550,50)(150,50)(150,450)(550,450)
    const netA = g.childNodes[1] as SVGPolygonElement;
    expect(netA.getAttribute('points')).toBe('550,50 150,50 150,450 550,450');
    // 内部线 [[100,100],[400,100]] → (500,100)-(200,100)
    const internalA = g.childNodes[2] as SVGPolylineElement;
    expect(internalA.getAttribute('points')).toBe('500,100 200,100');
    // 刺口 [250,0,0,-1] 端点 (250,4)/(250,-4) → x 取负 +600 = (350,±4)
    const notchA = g.childNodes[3] as SVGLineElement;
    expect(notchA.getAttribute('x1')).toBe('350');
    expect(notchA.getAttribute('y1')).toBe('4');
    expect(notchA.getAttribute('x2')).toBe('350');
    expect(notchA.getAttribute('y2')).toBe('-4');
    // 布纹线 [100,250,400,250] → (500,250)-(200,250)
    const grainA = g.childNodes[4] as SVGLineElement;
    expect(grainA.getAttribute('x1')).toBe('500');
    expect(grainA.getAttribute('y1')).toBe('250');
    expect(grainA.getAttribute('x2')).toBe('200');
    expect(grainA.getAttribute('y2')).toBe('250');
    // 同帧无镜像片走缺省路径（x 不取负）
    const roughB = g.childNodes[5] as SVGPolygonElement;
    expect(roughB.getAttribute('points')).toBe('600,0 1100,0 1100,500 600,500');
  });

  it('mirror + rot 90 复合（x 取负在旋转前）：x′ = −y+tx、y′ = −x+ty', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 90, translation: [600, 500], mirror: true },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    const { g } = skeleton(svg);
    const roughA = g.childNodes[0] as SVGPolygonElement;
    // (0,0)→(600,500)；(500,0)→(600,0)；(500,500)→(100,0)；(0,500)→(100,500)
    expect(roughA.getAttribute('points')).toBe('600,500 600,0 100,0 100,500');
  });

  it('placementSig 含 mirror 段：replaceWorking 翻转 mirror（同 rot/tr）→ 5 层重写', () => {
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [600, 0], mirror: true },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    const { g } = skeleton(svg);
    const roughA = g.childNodes[0] as SVGPolygonElement;
    expect(roughA.getAttribute('points')).toBe('600,0 100,0 100,500 600,500');
    // 关镜像（同 rot/tr）：签名含 mirror 段 → 重写；缺席则误判无变化 → 画布陈旧
    act(() => {
      useEditStore.getState().replaceWorking([{ id: 'a_28', rotation: 0, translation: [600, 0] }]);
    });
    expect(roughA.getAttribute('points')).toBe('600,0 1100,0 1100,500 600,500');
    // 开回镜像：再重写（双向翻转都生效）
    act(() => {
      useEditStore.getState().replaceWorking([
        { id: 'a_28', rotation: 0, translation: [600, 0], mirror: true },
      ]);
    });
    expect(roughA.getAttribute('points')).toBe('600,0 100,0 100,500 600,500');
  });

  it('拖动镜像片：clampPlacement 按镜像 bbox 钳制（minX<0 右推）、working 不掉镜像标志', () => {
    // 镜像 a_28 @ tr[600,0]：世界 x ∈ [100,600]。左拖候选 tx=100 → 镜像 minX=−400 <0
    // → 钳到 minX=0（tx=500）；若按非镜像 bbox 算（x∈[100,600] 不越界）则不钳 —— 本
    // 断言即锁 clampPlacement 的 mirror 参按镜像几何生效。
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [600, 0], mirror: true },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    mockRect(svg, 550, 500); // s = 0.5
    const roughA = roughPolyOf(svg, '#ff0000');
    act(() => {
      firePointer(roughA, 'pointerdown', 100, 100);
      firePointer(roughA, 'pointermove', -150, 100); // dx=−500mm → 候选 tx=100
      firePointer(roughA, 'pointerup', -150, 100);
    });
    const w = useEditStore.getState().working;
    expect(w[0].mirror).toBe(true); // setWorkingItem 增量更新不掉标志（US-002 透传）
    expect(w[0].translation[0]).toBeCloseTo(500, 9); // 镜像 minX −400 → 钳 0
    expect(roughA.getAttribute('points')).toBe('500,0 0,0 0,500 500,500');
  });

  it('拖动帧池增量透传 mirror：镜像 b(+100mm) 与 a 交 490×400（丢镜像则 0）', () => {
    // a@[0,0]（x∈[0,500]²）；镜像 b@[410,100]（x∈[−90,410]，y∈[100,600]）右拖 +100mm
    // → tr[510,100]：镜像世界 x∈[10,510] → 与 a 交 x[10,500]×y[100,500] = 490×400；
    // 若 applyEditPlacement 帧内覆回非镜像（x∈[510,1010]）→ 与 a 分离面积 0 —— 精确
    // 值断言锁「池增量显式传 mirror」接线。
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [410, 100], mirror: true },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    mockRect(svg, 550, 500);
    const roughB = roughPolyOf(svg, '#00ff00');
    act(() => {
      firePointer(roughB, 'pointerdown', 100, 100);
      firePointer(roughB, 'pointermove', 150, 100); // dx=+100mm → tr[510,100]
      firePointer(roughB, 'pointerup', 150, 100);
    });
    expect(useEditStore.getState().working[1].mirror).toBe(true);
    expect(metricsText('edit-metrics-area')).toBe('196000.0 mm²（1960.00 cm²）');
    // 穿透：镜像 b 顶点 (10,100) 严格落入 a，到 a 边界最近距离 10（x 距左界 10）
    expect(metricsText('edit-metrics-depth')).toBe('10.0 mm');
  });
});

// ============================================================
// 键盘变换（edit-keyboard US-005）：window keydown 守卫链（表单控件 /
// 无选中 / interactionEnabled=false）+ L/K/Shift/空格/O/I 逐键精确值 +
// 质心锚定片不漂移 + clampPlacement + e.repeat 规则。
//
// 数学锚点（手算 + node 对拍锁死）：a_28 方块 c_local=(250,250)；
// t' = c_world − R(rot')·M(m')·c_local；R(1°)·c_local =
// (250(cos1−sin1), 250(sin1+cos1))。
// ============================================================

describe('EditCanvas 键盘变换 (edit-keyboard US-005)', () => {
  /** 精确值夹具：a@[600,250]（c_world=(850,500)）+ b 远置 —— ±11° 内零钳制干扰。 */
  const KB_PLACED: PlacedItem[] = [
    { id: 'a_28', rotation: 0, translation: [600, 250] },
    { id: 'b_30', rotation: 0, translation: [1600, 250] },
  ];
  const SQ: Pt[] = [
    [0, 0],
    [500, 0],
    [500, 500],
    [0, 500],
  ];

  it('L=+1° / K=−1° / Shift ±10°：rotation + 质心锚定 translation 精确值；片不漂移；整型往返回原位', () => {
    const svg = mountCanvas('full', seedRun(KB_PLACED));
    selectPiece(svg, '#ff0000');
    // L 一次：t' = (850,500) − R(1°)·(250,250)，±11° 范围零钳制（锚定通式原样落）
    const r1 = Math.PI / 180;
    const c1 = Math.cos(r1);
    const s1 = Math.sin(r1);
    act(() => {
      fireKey(window, 'l');
    });
    let w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(1);
    expect(w[0].translation[0]).toBeCloseTo(850 - 250 * (c1 - s1), 9);
    expect(w[0].translation[1]).toBeCloseTo(500 - 250 * (s1 + c1), 9);
    expect(w[0].mirror).toBeUndefined();
    // 片不漂移：变换后世界多边形顶点均值仍 = c_world (850,500)
    let c = polyCentroid(transformPolygon(SQ, w[0].rotation, w[0].translation));
    expect(c[0]).toBeCloseTo(850, 9);
    expect(c[1]).toBeCloseTo(500, 9);
    // DOM 5 层同帧落笔（毛版 points 手算 r2 对拍）
    const roughA = roughPolyOf(svg, '#ff0000');
    expect(roughA.getAttribute('points')).toBe(
      '604.4,245.67 1104.33,254.4 1095.6,754.33 595.67,745.6',
    );

    // Shift+L（e.key='L' 大写同键命中）步长 10° → 11°（c_world 未漂 ⇒ 同锚点通式）
    const r11 = (11 * Math.PI) / 180;
    act(() => {
      fireKey(window, 'L', { shiftKey: true });
    });
    w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(11);
    expect(w[0].translation[0]).toBeCloseTo(850 - 250 * (Math.cos(r11) - Math.sin(r11)), 9);
    expect(w[0].translation[1]).toBeCloseTo(500 - 250 * (Math.sin(r11) + Math.cos(r11)), 9);

    // K −1° → 10°；Shift+K −10° → 0°：整型往返，translation 回 (600,250)
    act(() => {
      fireKey(window, 'k');
      fireKey(window, 'K', { shiftKey: true });
    });
    w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(0);
    expect(w[0].translation[0]).toBeCloseTo(600, 9);
    expect(w[0].translation[1]).toBeCloseTo(250, 9);
    expect(w[0].mirror).toBeUndefined();
  });

  it('变换后 clampPlacement：Y 下界（minY<0 上抬至 0）+ minX<0 右推 + 旋转手柄随帧刷新', () => {
    // a@[600,0] 按 L：未钳 t'y = 250−250(sin1+cos1) = −4.325 → 上抬至 0；x 无钳。
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [600, 0] },
      { id: 'b_30', rotation: 0, translation: [1600, 0] },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    selectPiece(svg, '#ff0000');
    const handle = document.querySelector(
      '[data-testid="edit-rotate-handle"]',
    ) as SVGCircleElement;
    const cyBefore = Number(handle.getAttribute('cy'));
    const r1 = Math.PI / 180;
    const lift = 250 * (Math.sin(r1) + Math.cos(r1)) - 250; // 质心被钳上抬量 4.3250…
    act(() => {
      fireKey(window, 'l');
    });
    const w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(1);
    expect(w[0].translation[1]).toBeCloseTo(0, 9); // 未钳为 −4.325 → 钳 0
    expect(w[0].translation[0]).toBeCloseTo(850 - 250 * (Math.cos(r1) - Math.sin(r1)), 9); // x 无钳
    // 手柄同帧刷新：cy 随质心上移 4.325mm（updateHandle 接线锁）
    expect(Number(handle.getAttribute('cy')) - cyBefore).toBeCloseTo(lift, 5);

    // a@[0,250] 按 L：minX = −4.325 → 右推，代数闭式恰 tx = 500·sin(1°)；y 无钳
    const placed2: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [0, 250] },
      { id: 'b_30', rotation: 0, translation: [1600, 250] },
    ];
    const svg2 = mountCanvas('full', seedRun(placed2));
    selectPiece(svg2, '#ff0000');
    act(() => {
      fireKey(window, 'l');
    });
    const w2 = useEditStore.getState().working;
    expect(w2[0].translation[0]).toBeCloseTo(500 * Math.sin(r1), 9); // 8.7262（未钳 4.4012）
    expect(w2[0].translation[1]).toBeCloseTo(500 - 250 * (Math.sin(r1) + Math.cos(r1)), 9);
  });

  it('空格 = rot+180（质心锚定 (1100,750)）+ preventDefault；mirror 不动', () => {
    const svg = mountCanvas('full', seedRun(KB_PLACED));
    selectPiece(svg, '#ff0000');
    let ev: KeyboardEvent | null = null;
    act(() => {
      ev = fireKey(window, ' ');
    });
    expect(ev!.defaultPrevented).toBe(true); // 防 body 滚动
    const w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(180);
    // R(180°)·c_local ≈ (−250,−250)（sin π ~1e-16 噪声）→ t' = (850,500)+(250,250)
    expect(w[0].translation[0]).toBeCloseTo(1100, 9);
    expect(w[0].translation[1]).toBeCloseTo(750, 9);
    expect(w[0].mirror).toBeUndefined();
    // 掉头后同足印（世界 bbox [600,1100]×[250,750] 不变）
    const roughA = roughPolyOf(svg, '#ff0000');
    expect(roughA.getAttribute('points')).toBe('1100,750 600,750 600,250 1100,250');
  });

  it('O = toggle mirror（rot 不变）：水平镜像绕质心竖轴翻转；再按回非镜像（omit-when-false 键消失）', () => {
    const svg = mountCanvas('full', seedRun(KB_PLACED));
    selectPiece(svg, '#ff0000');
    const roughA = roughPolyOf(svg, '#ff0000');
    act(() => {
      fireKey(window, 'o');
    });
    let w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(0);
    expect(w[0].mirror).toBe(true);
    // t' = c_world − M·c_local = (850,500) − (−250,250) = (1100,250)
    expect(w[0].translation[0]).toBeCloseTo(1100, 9);
    expect(w[0].translation[1]).toBeCloseTo(250, 9);
    expect(roughA.getAttribute('points')).toBe('1100,250 600,250 600,750 1100,750');
    // 大写 O（Shift 的 e.key='O'）同键命中；toggle 回非镜像 —— mirror 键消失
    act(() => {
      fireKey(window, 'O');
    });
    w = useEditStore.getState().working;
    expect('mirror' in w[0]).toBe(false);
    expect(w[0].translation[0]).toBeCloseTo(600, 9);
    expect(w[0].translation[1]).toBeCloseTo(250, 9);
    expect(roughA.getAttribute('points')).toBe('600,250 1100,250 1100,750 600,750');
  });

  it('I = toggle mirror + rot+180：垂直镜像（diag(1,−1)=R(180°)·diag(−1,1) 复合律，共用单标志）', () => {
    const svg = mountCanvas('full', seedRun(KB_PLACED));
    selectPiece(svg, '#ff0000');
    const roughA = roughPolyOf(svg, '#ff0000');
    act(() => {
      fireKey(window, 'i');
    });
    const w = useEditStore.getState().working;
    expect(w[0].mirror).toBe(true);
    expect(w[0].rotation).toBe(180);
    // t' = c_world − R(180°)·M·c_local = (850,500) − (250,−250) = (600,750)：
    // 足印同 bbox 绕质心横轴上下翻转（y 250..750 关于 500 镜像）
    expect(w[0].translation[0]).toBeCloseTo(600, 9);
    expect(w[0].translation[1]).toBeCloseTo(750, 9);
    expect(roughA.getAttribute('points')).toBe('600,750 1100,750 1100,250 600,250');
  });

  it('键盘 O 池增量 + 指标实时：镜像 b 关镜像 → 质心锚定 + minX 钳 0 → 与 a 交 500×400', () => {
    // a@[0,0]；镜像 b@[410,100]（世界 x∈[−90,410]）与 a 交 410×400=164000。按 O：
    // 锚定 t'=(−90,100) → minX 钳 0 → b@[0,100] 非镜像（x∈[0,500]）与 a 交
    // 500×400=200000 —— 若池增量沿用旧 mirror（true）则指标停在 164000（锁接线）。
    const placed: PlacedItem[] = [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [410, 100], mirror: true },
    ];
    const svg = mountCanvas('full', seedRun(placed));
    selectPiece(svg, '#00ff00');
    expect(metricsText('edit-metrics-area')).toBe('164000.0 mm²（1640.00 cm²）');
    act(() => {
      fireKey(window, 'o');
    });
    const w = useEditStore.getState().working;
    expect(w[1].mirror).toBeUndefined();
    expect(w[1].translation[0]).toBeCloseTo(0, 9); // 锚定 −90 → 钳 0
    expect(w[1].translation[1]).toBeCloseTo(100, 9);
    expect(metricsText('edit-metrics-area')).toBe('200000.0 mm²（2000.00 cm²）');
  });

  it('e.repeat：L 放行连发（auto-repeat 每击 +1°）；空格/O/I 忽略 repeat（幂等键防抖动）', () => {
    const svg = mountCanvas('full', seedRun(KB_PLACED));
    selectPiece(svg, '#ff0000');
    act(() => {
      fireKey(window, 'l', { repeat: true });
      fireKey(window, 'l', { repeat: true });
    });
    expect(useEditStore.getState().working[0].rotation).toBe(2);
    act(() => {
      fireKey(window, ' ', { repeat: true });
      fireKey(window, 'o', { repeat: true });
      fireKey(window, 'i', { repeat: true });
    });
    const w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(2); // 三幂等键 repeat 全忽略
    expect(w[0].mirror).toBeUndefined();
  });

  it('守卫链：表单控件聚焦（INPUT/SELECT/TEXTAREA/BUTTON/contentEditable）零变换 —— 形态 select 按 L/空格无效', () => {
    const svg = mountCanvas('full', seedRun(KB_PLACED));
    selectPiece(svg, '#ff0000');
    // 画布左上形态 select（真实控件）：键盘归控件 —— 冒泡到 window 时 target=select
    const modeSelect = document.querySelector('[data-testid="edit-layout-mode"]') as Element;
    act(() => {
      fireKey(modeSelect, 'l');
      fireKey(modeSelect, ' ');
    });
    let w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(0);
    expect(w[0].translation).toEqual([600, 250]);
    // 其余四类控件同守卫（挂 container 内冒泡到 window，target = 控件自身；
    // jsdom 不解析 contenteditable 属性 → 直接锁 isContentEditable 属性值）
    const input = document.createElement('input');
    const textarea = document.createElement('textarea');
    const button = document.createElement('button');
    const editable = document.createElement('div');
    Object.defineProperty(editable, 'isContentEditable', { value: true });
    for (const el of [input, textarea, button, editable]) container!.appendChild(el);
    act(() => {
      fireKey(input, 'l');
      fireKey(textarea, ' ');
      fireKey(button, 'o');
      fireKey(editable, 'i');
    });
    w = useEditStore.getState().working;
    expect(w[0]).toEqual({ id: 'a_28', rotation: 0, translation: [600, 250] });
  });

  it('守卫链：无选中片 → 全键零变换', () => {
    mountCanvas('full', seedRun(KB_PLACED));
    act(() => {
      fireKey(window, 'l');
      fireKey(window, ' ');
      fireKey(window, 'o');
      fireKey(window, 'i');
    });
    expect(useEditStore.getState().working[0]).toEqual({
      id: 'a_28',
      rotation: 0,
      translation: [600, 250],
    });
  });

  it('守卫链：interactionEnabled=false（确认层打开）→ 全键禁用；恢复 true 后同键生效（ref 读现值）', () => {
    const run = seedRun(KB_PLACED);
    const svg = mountCanvas('full', run, false);
    selectPiece(svg, '#ff0000'); // 指针选中不受键盘总闸影响（确认层挡 pointer 热区）
    act(() => {
      fireKey(window, 'l');
      fireKey(window, ' ');
      fireKey(window, 'o');
      fireKey(window, 'i');
    });
    expect(useEditStore.getState().working[0]).toEqual({
      id: 'a_28',
      rotation: 0,
      translation: [600, 250],
    });
    // 确认层关闭（EditLayoutModal 传回 true）：监听器未重挂，经 interactionRef 生效
    act(() => {
      root!.render(<EditCanvas mode="full" interactionEnabled />);
    });
    act(() => {
      fireKey(window, 'l');
    });
    expect(useEditStore.getState().working[0].rotation).toBe(1);
  });
});

// ============================================================
// R 键片级重置（edit-keyboard US-006）：resetItem 恢复算法基线（= 会话首次 open
// 的算法原始布局，R 会连已保存编辑一起抹掉 —— 定案接受）+ refreshPieceView 单点
// 同帧刷新（DOM 5 层 + 池增量 + 指标/手柄）。
//
// 数学锚点（手算锁死）：基线 a@[600,250] + b@[1000,250]（初始包络 maxX 1500 →
// vb 1500×1000，mockRect 750×500 → meet s=0.5）；基线重合 = [1000,1100]×[250,750]
// = 100×500 = 50000 mm²（R 后池增量必须按基线几何重算的判别值 —— 池陈旧则值错）；
// 手柄 r = clamp(1500×0.015)=22.5、off=3r=67.5 → 基线质心 (850,500) 上方 cy=567.5。
// ============================================================

describe('EditCanvas R 键片级重置 (edit-keyboard US-006)', () => {
  /** 基线：a@[600,250] 与 b@[1000,250] 基线交 100×500=50000（R 后判别值）。 */
  const RST_PLACED: PlacedItem[] = [
    { id: 'a_28', rotation: 0, translation: [600, 250] },
    { id: 'b_30', rotation: 0, translation: [1000, 250] },
  ];

  it('正常恢复：拖动 + L 旋转 + O 镜像后按 R → 逐字段回基线（mirror 清零）、其余片与 lastFrame 不动、5 层 points + 指标/手柄同帧回基线', () => {
    const run = seedRun(RST_PLACED);
    const svg = mountCanvas('full', run);
    mockRect(svg, 750, 500); // vb 1500×1000 → meet s = 0.5
    const roughA = roughPolyOf(svg, '#ff0000');
    const roughB = roughPolyOf(svg, '#00ff00');
    const handle = () =>
      document.querySelector('[data-testid="edit-rotate-handle"]') as SVGCircleElement;
    selectPiece(svg, '#ff0000');
    expect(metricsText('edit-metrics-area')).toBe('50000.0 mm²（500.00 cm²）'); // 基线交

    // ① 拖动：dClient (+300,−100) → world (+600,+200) → a@[1200,450]（与 b 交 300×300）
    act(() => {
      firePointer(roughA, 'pointerdown', 100, 100);
      firePointer(roughA, 'pointermove', 400, 0);
      firePointer(roughA, 'pointerup', 400, 0);
    });
    expect(metricsText('edit-metrics-area')).toBe('90000.0 mm²（900.00 cm²）');
    // ② L 旋转 +1°（质心锚定）+ ③ O 水平镜像 —— R 前置编辑态
    act(() => {
      fireKey(window, 'l');
      fireKey(window, 'o');
    });
    let w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(1);
    expect(w[0].mirror).toBe(true);
    expect(metricsText('edit-metrics-rot')).toBe('1.0°');
    expect(Number(handle().getAttribute('cy'))).toBeCloseTo(767.5, 6); // 质心 (1450,700)

    // ④ R：working[0] 逐字段回基线（mirror 键消失）、其余片与 lastFrame 不动
    act(() => {
      fireKey(window, 'r');
    });
    w = useEditStore.getState().working;
    expect(w[0]).toEqual({ id: 'a_28', rotation: 0, translation: [600, 250] });
    expect('mirror' in w[0]).toBe(false); // omit-when-false：基线无镜像 → 键消失
    expect(w[1]).toEqual({ id: 'b_30', rotation: 0, translation: [1000, 250] });
    // 只写 working 草稿不写 run（保存才落盘 —— resetItem 语义，R 链路不得旁路）
    expect(run.lastFrame!.placed_items).toEqual([
      { id: 'a_28', rotation: 0, translation: [600, 250] },
      { id: 'b_30', rotation: 0, translation: [1000, 250] },
    ]);
    // 画布 5 层回基线值（毛版 points 手算）+ 其余片 DOM 不动
    expect(roughA.getAttribute('points')).toBe('600,250 1100,250 1100,750 600,750');
    expect(roughB.getAttribute('points')).toBe('1000,250 1500,250 1500,750 1000,750');
    // 指标/手柄同帧刷新（refreshPieceView 接线锁：面积按基线几何重算 + 质心回基线；
    // 主渲染 effect 不触指标/手柄 —— 漏调用则面板停在编辑态旧值）
    expect(metricsText('edit-metrics-area')).toBe('50000.0 mm²（500.00 cm²）');
    expect(metricsText('edit-metrics-rot')).toBe('0.0°');
    expect(handle().getAttribute('cy')).toBe('567.5');
  });

  it('e.repeat 忽略：按住 R（auto-repeat）零动作；抬手单击正常重置（幂等键防抖）', () => {
    const svg = mountCanvas('full', seedRun(RST_PLACED));
    selectPiece(svg, '#ff0000');
    act(() => {
      fireKey(window, 'l');
    });
    expect(useEditStore.getState().working[0].rotation).toBe(1);
    act(() => {
      fireKey(window, 'r', { repeat: true });
      fireKey(window, 'r', { repeat: true });
    });
    expect(useEditStore.getState().working[0].rotation).toBe(1); // repeat 全忽略
    act(() => {
      fireKey(window, 'r');
    });
    expect(useEditStore.getState().working[0].rotation).toBe(0); // 非 repeat 生效
  });

  it('守卫链：未选中片（空白点击取消选中后）→ R 无效；重新选中后 R 生效', () => {
    const svg = mountCanvas('full', seedRun(RST_PLACED));
    selectPiece(svg, '#ff0000');
    act(() => {
      fireKey(window, 'l');
      fireKey(window, 'o');
    });
    // 空白点击（无位移 down-up）→ 取消选中（守卫③拦截 R）
    act(() => {
      firePointer(svg, 'pointerdown', 5, 5);
      firePointer(svg, 'pointerup', 5, 5);
    });
    expect(document.querySelector('[data-testid="edit-metrics"]')).toBeNull();
    act(() => {
      fireKey(window, 'r');
    });
    let w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(1); // 无选中 → R 无效
    expect(w[0].mirror).toBe(true);
    // 重新选中 → R 生效
    selectPiece(svg, '#ff0000');
    act(() => {
      fireKey(window, 'r');
    });
    w = useEditStore.getState().working;
    expect(w[0]).toEqual({ id: 'a_28', rotation: 0, translation: [600, 250] });
  });

  it('守卫链：确认层打开（interactionEnabled=false）→ R 禁用；恢复 true 后 R 生效（ref 读现值）', () => {
    const svg = mountCanvas('full', seedRun(RST_PLACED));
    selectPiece(svg, '#ff0000');
    act(() => {
      fireKey(window, 'l');
      fireKey(window, 'o');
    });
    // 确认层打开（EditLayoutModal 传 !confirmDiscard）：监听器不重挂，interactionRef 生效
    act(() => {
      root!.render(<EditCanvas mode="full" interactionEnabled={false} />);
    });
    act(() => {
      fireKey(window, 'r');
    });
    let w = useEditStore.getState().working;
    expect(w[0].rotation).toBe(1); // 总闸拦截
    expect(w[0].mirror).toBe(true);
    // 确认层关闭：恢复 true 后同键生效
    act(() => {
      root!.render(<EditCanvas mode="full" interactionEnabled />);
    });
    act(() => {
      fireKey(window, 'r');
    });
    w = useEditStore.getState().working;
    expect(w[0]).toEqual({ id: 'a_28', rotation: 0, translation: [600, 250] });
    expect('mirror' in w[0]).toBe(false);
  });

  it('resetItem 返回 false（id 错位守卫命中）→ 静默不动不炸（不按 pid 寻址）', () => {
    const run = seedRun(RST_PLACED);
    const svg = mountCanvas('full', run);
    selectPiece(svg, '#ff0000');
    // 人为制造 id 错位（working 的 pidSeq 不变 → 不触发骨架重建/清选中，R 链路直达
    // resetItem 的 id 对齐守卫）：baseline[0].id ≠ working[0].id —— 同 pid 多副本
    // 下标错位防御的等价形态，store 层拒绝且绝不静默按 pid 找同名项。
    const bl = useEditStore.getState().baseline!;
    act(() => {
      useEditStore.setState({
        baseline: {
          ...bl,
          placedItems: [{ id: 'zz_28', rotation: 5, translation: [7, 8] }, bl.placedItems[1]],
        },
      });
    });
    const before = useEditStore.getState().working[0];
    expect(() => {
      act(() => {
        fireKey(window, 'r');
      });
    }).not.toThrow();
    expect(useEditStore.getState().working[0]).toBe(before); // 静默不动（原引用原样）
    const roughA = roughPolyOf(svg, '#ff0000');
    expect(roughA.getAttribute('points')).toBe('600,250 1100,250 1100,750 600,750'); // DOM 不动
  });
});
