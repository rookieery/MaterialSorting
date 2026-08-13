// US-001 TabBar 集成测试：
//   AC#1 渲染两 Tab（超排 / 上传预览），默认 preview active
//   AC#1 active Tab 带 .active class + aria-pressed=true
//   AC#4 点击切换 uiStore.activeTab（display:none 由 App 控制，TabBar 只切 store）
//   视觉一致性：根 <nav class="tabbar"> + <button class="tab">
// US-015 新增 3 项（nestingEnabled 解锁闸）：
//   - disabled 时点击不调 setTab（关键不变量）
//   - disabled 视觉有 .disabled class + aria-disabled + native disabled
//   - 启用后正常切换
// US-032 新增 7 项（下拉菜单三项 + 关闭交互）：
//   - 菜单默认不渲染，点击「操作指引」展开
//   - 三项菜单各自触发正确 action（replay-preview / replay-nesting / reset）
//   - 点外部关闭、ESC 关闭、aria-expanded 跟随

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { TabBar } from '../TabBar';
import { useUiStore } from '../../store/uiStore';
import { useTourStore } from '../../store/tourStore';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  // 重置 store 状态到默认 preview + 锁定超排 Tab
  useUiStore.getState().setTab('preview');
  useUiStore.getState().setNestingEnabled(false);
  // US-032：重置 tourStore（避免跨测试污染菜单 action 验证）
  localStorage.clear();
  useTourStore.setState({
    activeTour: null,
    stepIndex: 0,
    seen: { preview: true, nesting: true },
  });
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
    expect(tabs[0].textContent).toBe('上传预览');
    expect(tabs[1].textContent).toBe('超排');
  });

  it('默认 preview Tab 带 .active + aria-pressed=true', () => {
    const el = renderBar();
    const tabs = el.querySelectorAll('button.tab');
    expect(tabs[0].classList.contains('active')).toBe(true);
    expect(tabs[0].getAttribute('aria-pressed')).toBe('true');
    expect(tabs[1].classList.contains('active')).toBe(false);
    expect(tabs[1].getAttribute('aria-pressed')).toBe('false');
  });

  it('点击 "超排" 切换 activeTab=nesting + .active 转移', () => {
    // US-015：需先解锁超排 Tab，否则 disabled 不响应点击
    useUiStore.getState().setNestingEnabled(true);
    const el = renderBar();
    const tabs = el.querySelectorAll('button.tab');
    act(() => {
      tabs[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useUiStore.getState().activeTab).toBe('nesting');
    // 重读 DOM（act 后 React 重渲染）
    const tabsAfter = el.querySelectorAll('button.tab');
    expect(tabsAfter[1].classList.contains('active')).toBe(true);
    expect(tabsAfter[0].classList.contains('active')).toBe(false);
  });

  it('点击 "上传预览" 从 nesting 切回 preview', () => {
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setTab('nesting');
    const el = renderBar();
    const tabs = el.querySelectorAll('button.tab');
    act(() => {
      tabs[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useUiStore.getState().activeTab).toBe('preview');
  });

  it('Tab 顺序固定：上传预览在前、超排在后', () => {
    const el = renderBar();
    const tabs = el.querySelectorAll('button.tab');
    expect(tabs[0].textContent).toBe('上传预览');
    expect(tabs[1].textContent).toBe('超排');
  });
});

describe('TabBar US-015 超排 Tab 解锁闸', () => {
  it('disabled 时点击不调 setTab（关键不变量）', () => {
    // 默认 nestingEnabled=false：超排 Tab disabled，点击不切
    const el = renderBar();
    const tabs = el.querySelectorAll('button.tab');
    act(() => {
      tabs[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useUiStore.getState().activeTab).toBe('preview');
  });

  it('disabled 视觉有 .disabled class + aria-disabled + native disabled', () => {
    // 默认 nestingEnabled=false
    const el = renderBar();
    const tabs = el.querySelectorAll('button.tab');
    // 超排 Tab（index 1）置灰
    expect(tabs[1].classList.contains('disabled')).toBe(true);
    expect(tabs[1].getAttribute('aria-disabled')).toBe('true');
    expect((tabs[1] as HTMLButtonElement).disabled).toBe(true);
    // 上传预览 Tab（index 0）不受影响
    expect(tabs[0].classList.contains('disabled')).toBe(false);
    expect(tabs[0].getAttribute('aria-disabled')).toBe('false');
    expect((tabs[0] as HTMLButtonElement).disabled).toBe(false);
  });

  it('启用后正常切换：setNestingEnabled(true) → 点击超排切 activeTab=nesting', () => {
    useUiStore.getState().setNestingEnabled(true);
    const el = renderBar();
    const tabsBefore = el.querySelectorAll('button.tab');
    // 启用后超排 Tab 不再 disabled
    expect(tabsBefore[1].classList.contains('disabled')).toBe(false);
    expect((tabsBefore[1] as HTMLButtonElement).disabled).toBe(false);
    act(() => {
      tabsBefore[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useUiStore.getState().activeTab).toBe('nesting');
  });

  it('nestingEnabled 切换时 TabBar 重渲染：false→true 移除 disabled，true→false 加回', () => {
    const el = renderBar();
    const readNesting = () => {
      // 按文案定位超排 Tab（顺序变更后 querySelector 首个已非超排，文案定位更稳）
      const t = Array.from(el.querySelectorAll('button.tab')).find(
        (b) => b.textContent === '超排',
      );
      return {
        disabledClass: t?.classList.contains('disabled') ?? false,
        nativeDisabled: (t as HTMLButtonElement | undefined)?.disabled ?? false,
      };
    };
    // 初始锁定
    expect(readNesting().disabledClass).toBe(true);
    expect(readNesting().nativeDisabled).toBe(true);
    // 解锁
    act(() => {
      useUiStore.getState().setNestingEnabled(true);
    });
    expect(readNesting().disabledClass).toBe(false);
    expect(readNesting().nativeDisabled).toBe(false);
    // 重锁
    act(() => {
      useUiStore.getState().setNestingEnabled(false);
    });
    expect(readNesting().disabledClass).toBe(true);
    expect(readNesting().nativeDisabled).toBe(true);
  });
});

describe('TabBar US-032 操作指引下拉菜单', () => {
  it('菜单默认不渲染；点击「操作指引」展开三项菜单', () => {
    const el = renderBar();
    // 初始无菜单
    expect(el.querySelector('[data-testid="tour-menu"]')).toBeNull();
    // 找「操作指引」按钮（非 .tab class）
    const entry = el.querySelector('button.tour-entry') as HTMLButtonElement;
    expect(entry).not.toBeNull();
    expect(entry.getAttribute('aria-expanded')).toBe('false');

    act(() => {
      entry.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    const menu = el.querySelector('[data-testid="tour-menu"]');
    expect(menu).not.toBeNull();
    // 三项菜单
    expect(menu!.querySelector('[data-testid="tour-menu-replay-preview"]')).not.toBeNull();
    expect(menu!.querySelector('[data-testid="tour-menu-replay-nesting"]')).not.toBeNull();
    expect(menu!.querySelector('[data-testid="tour-menu-reset"]')).not.toBeNull();
    // aria-expanded=true
    const entryAfter = el.querySelector('button.tour-entry') as HTMLButtonElement;
    expect(entryAfter.getAttribute('aria-expanded')).toBe('true');
  });

  it('点击「重看上传预览指引」→ start("preview")', () => {
    const el = renderBar();
    const entry = el.querySelector('button.tour-entry') as HTMLButtonElement;
    act(() => {
      entry.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    const btn = el.querySelector('[data-testid="tour-menu-replay-preview"]') as HTMLButtonElement;
    act(() => {
      btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useTourStore.getState().activeTour).toBe('preview');
    expect(useTourStore.getState().stepIndex).toBe(0);
    // 菜单关闭
    expect(el.querySelector('[data-testid="tour-menu"]')).toBeNull();
  });

  it('点击「重看超排指引」→ start("nesting")', () => {
    const el = renderBar();
    const entry = el.querySelector('button.tour-entry') as HTMLButtonElement;
    act(() => {
      entry.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    const btn = el.querySelector('[data-testid="tour-menu-replay-nesting"]') as HTMLButtonElement;
    act(() => {
      btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useTourStore.getState().activeTour).toBe('nesting');
    expect(useTourStore.getState().stepIndex).toBe(0);
  });

  it('点击「重置全部指引」→ resetSeen（清 localStorage seen，不启动 tour）', () => {
    // 先 markSeen 写 localStorage（需 seen=false 才能 markSeen 写入）
    useTourStore.setState({ seen: { preview: false, nesting: false } });
    useTourStore.getState().markSeen('preview');
    expect(localStorage.getItem('ms.tour.seen.preview')).toBe('1');

    const el = renderBar();
    const entry = el.querySelector('button.tour-entry') as HTMLButtonElement;
    act(() => {
      entry.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    const btn = el.querySelector('[data-testid="tour-menu-reset"]') as HTMLButtonElement;
    act(() => {
      btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    // seen 清空
    expect(useTourStore.getState().seen.preview).toBe(false);
    expect(useTourStore.getState().seen.nesting).toBe(false);
    expect(localStorage.getItem('ms.tour.seen.preview')).toBeNull();
    expect(localStorage.getItem('ms.tour.seen.nesting')).toBeNull();
    // 不启动 tour（区别于旧 US-029 行为；下次进 Tab 由 auto-trigger 触发）
    expect(useTourStore.getState().activeTour).toBeNull();
  });

  it('点击菜单外部关闭菜单', () => {
    const el = renderBar();
    const entry = el.querySelector('button.tour-entry') as HTMLButtonElement;
    act(() => {
      entry.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(el.querySelector('[data-testid="tour-menu"]')).not.toBeNull();

    // 模拟点击外部（document mousedown 落在 container 外）
    act(() => {
      document.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });

    expect(el.querySelector('[data-testid="tour-menu"]')).toBeNull();
  });

  it('ESC 关闭菜单', () => {
    const el = renderBar();
    const entry = el.querySelector('button.tour-entry') as HTMLButtonElement;
    act(() => {
      entry.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(el.querySelector('[data-testid="tour-menu"]')).not.toBeNull();

    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });

    expect(el.querySelector('[data-testid="tour-menu"]')).toBeNull();
  });

  it('再次点击「操作指引」切换菜单（toggle）', () => {
    const el = renderBar();
    const entry = el.querySelector('button.tour-entry') as HTMLButtonElement;
    // 展开
    act(() => {
      entry.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(el.querySelector('[data-testid="tour-menu"]')).not.toBeNull();
    // 收起
    act(() => {
      entry.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(el.querySelector('[data-testid="tour-menu"]')).toBeNull();
  });
});
