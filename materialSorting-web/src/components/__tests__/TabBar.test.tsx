// US-001 TabBar 集成测试：
//   AC#1 渲染两 Tab（排料 / 上传预览），默认 nesting active
//   AC#1 active Tab 带 .active class + aria-pressed=true
//   AC#4 点击切换 uiStore.activeTab（display:none 由 App 控制，TabBar 只切 store）
//   视觉一致性：根 <nav class="tabbar"> + <button class="tab">

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { TabBar } from '../TabBar';
import { useUiStore } from '../../store/uiStore';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  // 重置 store 状态
  useUiStore.getState().setTab('nesting');
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
});

function renderBar(): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <TabBar />
      </StrictMode>,
    );
  });
  return container!;
}

describe('TabBar', () => {
  it('渲染 <nav class="tabbar"> + 两个 <button class="tab">', () => {
    const el = renderBar();
    const nav = el.querySelector('nav.tabbar');
    expect(nav).not.toBeNull();
    const tabs = el.querySelectorAll('button.tab');
    expect(tabs.length).toBe(2);
    expect(tabs[0].textContent).toBe('排料');
    expect(tabs[1].textContent).toBe('上传预览');
  });

  it('默认 nesting Tab 带 .active + aria-pressed=true', () => {
    const el = renderBar();
    const tabs = el.querySelectorAll('button.tab');
    expect(tabs[0].classList.contains('active')).toBe(true);
    expect(tabs[0].getAttribute('aria-pressed')).toBe('true');
    expect(tabs[1].classList.contains('active')).toBe(false);
    expect(tabs[1].getAttribute('aria-pressed')).toBe('false');
  });

  it('点击 "上传预览" 切换 activeTab=preview + .active 转移', () => {
    const el = renderBar();
    const tabs = el.querySelectorAll('button.tab');
    act(() => {
      tabs[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useUiStore.getState().activeTab).toBe('preview');
    // 重读 DOM（act 后 React 重渲染）
    const tabsAfter = el.querySelectorAll('button.tab');
    expect(tabsAfter[0].classList.contains('active')).toBe(false);
    expect(tabsAfter[1].classList.contains('active')).toBe(true);
  });

  it('点击 "排料" 从 preview 切回 nesting', () => {
    useUiStore.getState().setTab('preview');
    const el = renderBar();
    const tabs = el.querySelectorAll('button.tab');
    act(() => {
      tabs[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useUiStore.getState().activeTab).toBe('nesting');
  });

  it('Tab 顺序固定：排料在前（默认入口）', () => {
    const el = renderBar();
    const tabs = el.querySelectorAll('button.tab');
    expect(tabs[0].textContent).toBe('排料');
    expect(tabs[1].textContent).toBe('上传预览');
  });
});
