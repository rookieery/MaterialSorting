// US-029 TourOverlay 单测（≥4 项）：
//   - activeTour=null 不渲染
//   - 激活渲染 overlay + spotlight + bubble
//   - spotlight 贴目标 rect（left/top/width/height 匹配 getBoundingClientRect）
//   - 零尺寸回退居中（spotlight display:none + bubble translate(-50%, -50%)）

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { TourOverlay } from '../TourOverlay';
import { useTourStore } from '../../store/tourStore';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  localStorage.clear();
  useTourStore.setState({
    activeTour: null,
    stepIndex: 0,
    seen: { preview: false, nesting: false },
  });
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
  // 清 body 上残留 tour overlay
  for (const el of Array.from(document.body.querySelectorAll('.tour-overlay'))) el.remove();
  // 清测试添加的目标元素
  for (const el of Array.from(document.body.querySelectorAll('nav.tabbar'))) el.remove();
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

describe('TourOverlay (US-029)', () => {
  it('activeTour=null 不渲染（return null）', () => {
    renderOverlay();
    expect(document.body.querySelector('.tour-overlay')).toBeNull();
  });

  it('激活时渲染 overlay + spotlight + bubble（Portal 到 body）', () => {
    // 创建目标元素（DEMO_PREVIEW_TOUR step0 selector = .tabbar）
    const target = document.createElement('nav');
    target.className = 'tabbar';
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

    // bubble 内有标题 + 正文（DEMO_PREVIEW_TOUR step0 内容）
    expect(overlay!.querySelector('.tour-title')?.textContent).toContain('欢迎使用');
    expect(overlay!.querySelector('.tour-body')).not.toBeNull();
    // 按钮：上一步（disabled，第一步）/ 下一步 / 跳过
    const prevBtn = overlay!.querySelector('[data-testid="tour-prev"]') as HTMLButtonElement;
    expect(prevBtn.disabled).toBe(true); // 第一步 prev disabled
    expect(overlay!.querySelector('[data-testid="tour-next"]')).not.toBeNull();
    expect(overlay!.querySelector('[data-testid="tour-skip"]')).not.toBeNull();
  });

  it('spotlight 贴目标 rect（left/top/width/height 匹配 getBoundingClientRect）', () => {
    const target = document.createElement('nav');
    target.className = 'tabbar';
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
    const target = document.createElement('nav');
    target.className = 'tabbar';
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
    // 创建两个目标元素（DEMO step0: .tabbar, step1: .tab-content）
    const tabbar = document.createElement('nav');
    tabbar.className = 'tabbar';
    mockRect(tabbar, { left: 0, top: 0, width: 400, height: 40 });
    document.body.appendChild(tabbar);

    const tabContent = document.createElement('div');
    tabContent.className = 'tab-content';
    mockRect(tabContent, { left: 0, top: 41, width: 800, height: 600 });
    document.body.appendChild(tabContent);

    act(() => {
      useTourStore.getState().start('preview');
    });
    renderOverlay();

    // step0 spotlight 贴 .tabbar
    let spotlight = document.body.querySelector('.tour-spotlight') as HTMLDivElement;
    expect(spotlight.style.left).toBe('0px');
    expect(spotlight.style.top).toBe('0px');
    expect(spotlight.style.width).toBe('400px');

    // 推进到 step1（DEMO step0 告知型，next 直接推进）
    act(() => {
      useTourStore.getState().next(); // stepIndex 0 → 1
    });

    // step1 spotlight 贴 .tab-content
    spotlight = document.body.querySelector('.tour-spotlight') as HTMLDivElement;
    expect(spotlight.style.top).toBe('41px');
    expect(spotlight.style.width).toBe('800px');

    tabbar.remove();
    tabContent.remove();
  });
});
