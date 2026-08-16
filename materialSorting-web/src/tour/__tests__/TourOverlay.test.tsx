// US-029/US-030/US-032 TourOverlay 单测：
//   - activeTour=null 不渲染
//   - 激活渲染 overlay + spotlight + bubble
//   - spotlight 贴目标 rect（left/top/width/height 匹配 getBoundingClientRect）
//   - 零尺寸回退居中（spotlight display:none + bubble translate(-50%, -50%)）
//   - US-030：等待态气泡渲染 readyHint + 下一步 disabled（advance-on-ready）
//   - US-032：ESC 关闭 tour（bug1：close 即 markSeen，不再自动触发）
//   - US-032：遮罩点击关闭（e.target===e.currentTarget；close 即 markSeen）
//   - US-032：bubble 点击不关闭
//   - US-032：skip 按钮 markSeen + close
//   - US-032：reduced-motion 加 .tour-reduced-motion class

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { TourOverlay, flipPlacement } from '../TourOverlay';
import { useTourStore } from '../../store/tourStore';
import { useUploadStore } from '../../store/uploadStore';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  localStorage.clear();
  useTourStore.setState({
    activeTour: null,
    stepIndex: 0,
    seen: { preview: true, nesting: true }, // seen=true 防止 auto-trigger 干扰（本测试手动 start）
  });
  // uploadStore 默认 idle → parsed.ready=false（等待态测试依赖此初值）
  useUploadStore.getState().reset();
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
  // 清 body 上残留 tour overlay + 测试添加的目标元素
  for (const el of Array.from(document.body.querySelectorAll('.tour-overlay'))) el.remove();
  for (const el of Array.from(document.body.querySelectorAll('[data-tour], .tab-content, nav.tabbar'))) el.remove();
});

function renderOverlay(): void {
  act(() => {
    root!.render(
      <StrictMode>
        <TourOverlay />
      </StrictMode>,
    );
  });
}

/** 给元素 mock getBoundingClientRect（jsdom 默认返回全零，需手动设置 rect 值）。 */
function mockRect(el: Element, rect: { left: number; top: number; width: number; height: number }): void {
  el.getBoundingClientRect = () => ({
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
    right: rect.left + rect.width,
    bottom: rect.top + rect.height,
    x: rect.left,
    y: rect.top,
    toJSON: () => ({}),
  });
}

describe('TourOverlay (US-029/US-030)', () => {
  it('activeTour=null 不渲染（return null）', () => {
    renderOverlay();
    expect(document.body.querySelector('.tour-overlay')).toBeNull();
  });

  it('激活时渲染 overlay + spotlight + bubble（Portal 到 body）', () => {
    // previewTour step0 (upload) selector = [data-tour="drop-zone"]
    const target = document.createElement('div');
    target.setAttribute('data-tour', 'drop-zone');
    mockRect(target, { left: 0, top: 0, width: 400, height: 40 });
    document.body.appendChild(target);

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    const overlay = document.body.querySelector('.tour-overlay');
    expect(overlay).not.toBeNull();
    expect(overlay!.parentElement).toBe(document.body);
    expect(overlay!.querySelector('.tour-spotlight')).not.toBeNull();
    expect(overlay!.querySelector('.tour-bubble')).not.toBeNull();

    // bubble 内有标题 + 正文（previewTour upload 步内容）
    expect(overlay!.querySelector('.tour-title')?.textContent).toContain('上传');
    expect(overlay!.querySelector('.tour-body')).not.toBeNull();
    // 按钮：上一步（disabled，第一步）/ 下一步 / 跳过
    const prevBtn = overlay!.querySelector('[data-testid="tour-prev"]') as HTMLButtonElement;
    expect(prevBtn.disabled).toBe(true); // 第一步 prev disabled
    expect(overlay!.querySelector('[data-testid="tour-next"]')).not.toBeNull();
    expect(overlay!.querySelector('[data-testid="tour-skip"]')).not.toBeNull();
  });

  it('spotlight 贴目标 rect（left/top/width/height 匹配 getBoundingClientRect）', () => {
    const target = document.createElement('div');
    target.setAttribute('data-tour', 'drop-zone');
    document.body.appendChild(target);
    const rect = { left: 120, top: 30, width: 300, height: 44 };
    mockRect(target, rect);

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    const spotlight = document.body.querySelector('.tour-spotlight') as HTMLDivElement;
    expect(spotlight).not.toBeNull();
    expect(spotlight.style.left).toBe(`${rect.left}px`);
    expect(spotlight.style.top).toBe(`${rect.top}px`);
    expect(spotlight.style.width).toBe(`${rect.width}px`);
    expect(spotlight.style.height).toBe(`${rect.height}px`);
    expect(spotlight.style.display).toBe('block');
  });

  it('零尺寸回退居中（display:none 元素 → spotlight display:none + bubble 居中）', () => {
    // display:none → getBoundingClientRect 返回全零（jsdom 行为）
    const target = document.createElement('div');
    target.setAttribute('data-tour', 'drop-zone');
    target.style.display = 'none';
    document.body.appendChild(target);

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    const spotlight = document.body.querySelector('.tour-spotlight') as HTMLDivElement;
    expect(spotlight).not.toBeNull();
    // spotlight 隐藏（零尺寸回退）
    expect(spotlight.style.display).toBe('none');

    // bubble 居中（translate(-50%, -50%)）
    const bubble = document.body.querySelector('.tour-bubble') as HTMLDivElement;
    expect(bubble).not.toBeNull();
    expect(bubble.style.transform).toBe('translate(-50%, -50%)');
  });

  it('步骤切换时 spotlight 跟随新目标（step0 → step1 selector 变化）', () => {
    // previewTour step0 (upload) = [data-tour="drop-zone"]
    const dropZone = document.createElement('div');
    dropZone.setAttribute('data-tour', 'drop-zone');
    mockRect(dropZone, { left: 0, top: 0, width: 400, height: 40 });
    document.body.appendChild(dropZone);

    // previewTour step1 (parsed) = [data-tour="qty-matrix"]（矩阵化重构 US-005 迁自旧 size-tabs）
    const qtyMatrix = document.createElement('div');
    qtyMatrix.setAttribute('data-tour', 'qty-matrix');
    mockRect(qtyMatrix, { left: 0, top: 41, width: 800, height: 60 });
    document.body.appendChild(qtyMatrix);

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    // step0 spotlight 贴 drop-zone
    let spotlight = document.body.querySelector('.tour-spotlight') as HTMLDivElement;
    expect(spotlight.style.left).toBe('0px');
    expect(spotlight.style.top).toBe('0px');
    expect(spotlight.style.width).toBe('400px');

    // 推进到 step1（store.next 直增 stepIndex；TourOverlay 读 currentStep 切 selector）
    act(() => {
      useTourStore.getState().next(); // stepIndex 0 → 1
    });

    // step1 spotlight 贴 qty-matrix
    spotlight = document.body.querySelector('.tour-spotlight') as HTMLDivElement;
    expect(spotlight.style.top).toBe('41px');
    expect(spotlight.style.width).toBe('800px');

    dropZone.remove();
    qtyMatrix.remove();
  });

  it('US-030 等待态：联动步 ready=false 时气泡渲染 readyHint + 下一步 disabled', () => {
    // step0 (upload) 告知型 → step1 (parsed) ready-gated。uploadStore idle → parsed.ready=false。
    const dropZone = document.createElement('div');
    dropZone.setAttribute('data-tour', 'drop-zone');
    mockRect(dropZone, { left: 0, top: 0, width: 200, height: 100 });
    document.body.appendChild(dropZone);

    const qtyMatrix = document.createElement('div');
    qtyMatrix.setAttribute('data-tour', 'qty-matrix');
    mockRect(qtyMatrix, { left: 0, top: 200, width: 500, height: 50 });
    document.body.appendChild(qtyMatrix);

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    // step0 (upload) 告知型：无等待态
    expect(document.body.querySelector('.tour-waiting')).toBeNull();
    const nextBtn0 = document.body.querySelector('[data-testid="tour-next"]') as HTMLButtonElement;
    expect(nextBtn0.disabled).toBe(false);

    // 推进到 step1 (parsed)：ready=false → 等待态
    act(() => {
      useTourStore.getState().next(); // stepIndex 0 → 1
    });

    // 等待态：readyHint 渲染（parsed.readyHint 含「上传」提示）
    const waiting = document.body.querySelector('.tour-waiting');
    expect(waiting).not.toBeNull();
    expect(waiting!.textContent).toContain('上传');
    // 下一步 disabled（等待 ready）
    const nextBtn1 = document.body.querySelector('[data-testid="tour-next"]') as HTMLButtonElement;
    expect(nextBtn1.disabled).toBe(true);

    dropZone.remove();
    qtyMatrix.remove();
  });
});

describe('TourOverlay US-032 关闭交互 + reduced-motion', () => {
  it('ESC 关闭 tour（window keydown → activeTour=null）+ close 即 markSeen（bug1）', () => {
    const target = document.createElement('div');
    target.setAttribute('data-tour', 'drop-zone');
    mockRect(target, { left: 0, top: 0, width: 200, height: 100 });
    document.body.appendChild(target);
    // bug1：从 seen=false 起步，验证 ESC 关闭后 markSeen（不再自动触发）
    useTourStore.setState({ seen: { preview: false, nesting: false } });

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    expect(document.body.querySelector('.tour-overlay')).not.toBeNull();

    // 按 ESC
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });

    expect(useTourStore.getState().activeTour).toBeNull();
    expect(document.body.querySelector('.tour-overlay')).toBeNull();
    // close 即 markSeen：ESC 关掉 = 已读，切回 Tab 不再自动触发
    expect(useTourStore.getState().seen.preview).toBe(true);
    expect(localStorage.getItem('ms.tour.seen.preview')).toBe('1');

    target.remove();
  });

  it('遮罩点击关闭（mousedown 落在 overlay 自身 e.target===e.currentTarget）+ close 即 markSeen（bug1）', () => {
    const target = document.createElement('div');
    target.setAttribute('data-tour', 'drop-zone');
    mockRect(target, { left: 0, top: 0, width: 200, height: 100 });
    document.body.appendChild(target);
    useTourStore.setState({ seen: { preview: false, nesting: false } });

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    const overlay = document.body.querySelector('.tour-overlay') as HTMLDivElement;
    expect(overlay).not.toBeNull();

    // 模拟点击 overlay 自身（mousedown target=currentTarget=overlay）
    act(() => {
      const ev = new MouseEvent('mousedown', { bubbles: true });
      Object.defineProperty(ev, 'target', { value: overlay });
      Object.defineProperty(ev, 'currentTarget', { value: overlay });
      overlay.dispatchEvent(ev);
    });

    expect(useTourStore.getState().activeTour).toBeNull();
    // close 即 markSeen（bug1）
    expect(useTourStore.getState().seen.preview).toBe(true);

    target.remove();
  });

  it('bubble 点击不关闭（mousedown target=bubble，≠ currentTarget=overlay）', () => {
    const target = document.createElement('div');
    target.setAttribute('data-tour', 'drop-zone');
    mockRect(target, { left: 0, top: 0, width: 200, height: 100 });
    document.body.appendChild(target);

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    const bubble = document.body.querySelector('.tour-bubble') as HTMLDivElement;
    expect(bubble).not.toBeNull();

    // 点击 bubble 内部（mousedown target=bubble）— 不关闭
    act(() => {
      const ev = new MouseEvent('mousedown', { bubbles: true });
      Object.defineProperty(ev, 'target', { value: bubble });
      bubble.dispatchEvent(ev);
    });

    expect(useTourStore.getState().activeTour).toBe('preview'); // 仍激活

    target.remove();
  });

  it('skip 按钮 markSeen(activeTour) + close', () => {
    const target = document.createElement('div');
    target.setAttribute('data-tour', 'drop-zone');
    mockRect(target, { left: 0, top: 0, width: 200, height: 100 });
    document.body.appendChild(target);

    // 确保 seen=false（skip 应该 markSeen=true）
    useTourStore.setState({ seen: { preview: false, nesting: false } });

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    const skipBtn = document.body.querySelector('[data-testid="tour-skip"]') as HTMLButtonElement;
    expect(skipBtn).not.toBeNull();

    act(() => {
      skipBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    // markSeen + close
    expect(useTourStore.getState().seen.preview).toBe(true);
    expect(localStorage.getItem('ms.tour.seen.preview')).toBe('1');
    expect(useTourStore.getState().activeTour).toBeNull();

    target.remove();
  });

  it('reduced-motion=true 时 overlay 加 .tour-reduced-motion class', () => {
    // mock matchMedia 返回 prefers-reduced-motion: reduce
    const matchMediaSpy = vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
      matches: query === '(prefers-reduced-motion: reduce)',
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }));

    const target = document.createElement('div');
    target.setAttribute('data-tour', 'drop-zone');
    mockRect(target, { left: 0, top: 0, width: 200, height: 100 });
    document.body.appendChild(target);

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    const overlay = document.body.querySelector('.tour-overlay') as HTMLDivElement;
    expect(overlay.classList.contains('tour-reduced-motion')).toBe(true);

    target.remove();
    matchMediaSpy.mockRestore();
  });

  it('reduced-motion=false 时 overlay 不加 .tour-reduced-motion class', () => {
    const matchMediaSpy = vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
      matches: false, // 不偏好 reduced-motion
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }));

    const target = document.createElement('div');
    target.setAttribute('data-tour', 'drop-zone');
    mockRect(target, { left: 0, top: 0, width: 200, height: 100 });
    document.body.appendChild(target);

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    const overlay = document.body.querySelector('.tour-overlay') as HTMLDivElement;
    expect(overlay.classList.contains('tour-reduced-motion')).toBe(false);

    target.remove();
    matchMediaSpy.mockRestore();
  });
});

// bug3：flipPlacement 级联回退 —— 目标几乎铺满视口时气泡不能被定位到屏外。
// jsdom 默认视口 1024×768；bw = min(340, 1024-16) = 340，BUBBLE_EST_HEIGHT = 220。
describe('flipPlacement 级联回退 (bug3)', () => {
  const origW = window.innerWidth;
  const origH = window.innerHeight;

  beforeEach(() => {
    // 显式锁定视口，防其它用例 / 环境漂移影响「放得下 / 放不下」边界判断。
    window.innerWidth = 1024;
    window.innerHeight = 768;
  });
  afterEach(() => {
    window.innerWidth = origW;
    window.innerHeight = origH;
  });

  it('目标铺满视口 + right → center（result 步 nest-wrap 占满右侧，旧逻辑气泡出屏）', () => {
    // nest-wrap 实测：左 panel 占 248px 后几乎横跨剩余宽度 + 占满高度。
    const nestWrap = { left: 264, top: 0, width: 760, height: 768 };
    expect(flipPlacement('right', nestWrap)).toBe('center');
  });

  it('目标铺满整个视口 + bottom → center（垂直方向也兜底）', () => {
    const full = { left: 0, top: 0, width: 1024, height: 768 };
    expect(flipPlacement('bottom', full)).toBe('center');
  });

  it('目标铺满整个视口 + right → center', () => {
    const full = { left: 0, top: 0, width: 1024, height: 768 };
    expect(flipPlacement('right', full)).toBe('center');
  });

  it('右侧有空间 + right → 不翻转', () => {
    // 小目标靠左，右侧足够放下 340px 气泡（right + gap + 340 = 562 <= 1016）。
    const small = { left: 10, top: 100, width: 200, height: 100 };
    expect(flipPlacement('right', small)).toBe('right');
  });

  it('底部溢出但顶部有空间 + bottom → 翻转到 top（保留原 flip 行为）', () => {
    // 目标贴近视口底部，下方放不下 220px 气泡，上方有空间。
    const nearBottom = { left: 100, top: 600, width: 300, height: 100 };
    expect(flipPlacement('bottom', nearBottom)).toBe('top');
  });

  it('底部溢出且顶部也放不下 + bottom → 交叉回退到 right/left，再不济 center', () => {
    // 目标又高又宽（垂直放不下），右侧够放 → 退到 right。
    const tallWide = { left: 10, top: 0, width: 200, height: 768 };
    expect(flipPlacement('bottom', tallWide)).toBe('right');
  });

  it('placement center → center', () => {
    const rect = { left: 100, top: 100, width: 200, height: 100 };
    expect(flipPlacement('center', rect)).toBe('center');
  });
});
