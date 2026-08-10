// US-008 SizeTabs 集成测试：
//   AC#1 渲染 doc.sizes 全部尺码 chip（按后端返回顺序，null→「通用」）
//   AC#1 当前 activeSize 的 chip 加 .active + aria-selected=true
//   AC#1 点击 chip 调用 uploadStore.setSize(size) 切 activeSize
//   doc=null 时组件渲染为空（空态由 PreviewPage 兜底）
//
// 测试模式参考 TabBar.test.tsx：渲染入 container，dispatch native click event，
// 直接读 uploadStore.getState() 验证 store 状态变化。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { SizeTabs } from '../SizeTabs';
import { useUploadStore } from '../../../store/uploadStore';
import type { ParsedDoc } from '../../../types/parsed';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
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
  useUploadStore.getState().reset();
});

function makeDoc(sizes: { size: number | null; pieces?: unknown[] }[] = [
  { size: 28 },
  { size: 30 },
  { size: 32 },
  { size: null },
]): ParsedDoc {
  return {
    doc_id: 'deadbeef',
    filename: 'M1787.dxf',
    sizes: sizes.map((s) => ({
      size: s.size,
      pieces: (s.pieces ?? []) as never[],
    })) as ParsedDoc['sizes'],
  };
}

function renderTabs(): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <SizeTabs />
      </StrictMode>,
    );
  });
  return container!;
}

describe('SizeTabs (US-008) AC#1 尺码 chip 列表', () => {
  it('doc=null 时渲染为空（空态由 PreviewPage 兜底）', () => {
    const el = renderTabs();
    expect(el.querySelector('.size-tabs')).toBeNull();
    expect(el.querySelectorAll('button').length).toBe(0);
  });

  it('渲染 doc.sizes 全部尺码 chip（按后端顺序）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28 }, { size: 30 }, { size: 32 }]),
      activeSize: 28,
    });
    const el = renderTabs();
    const chips = el.querySelectorAll('button.size-chip');
    expect(chips.length).toBe(3);
    expect(chips[0].textContent).toBe('28');
    expect(chips[1].textContent).toBe('30');
    expect(chips[2].textContent).toBe('32');
  });

  it('null 码渲染为「通用」', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28 }, { size: null }]),
      activeSize: 28,
    });
    const el = renderTabs();
    const chips = el.querySelectorAll('button.size-chip');
    expect(chips.length).toBe(2);
    expect(chips[0].textContent).toBe('28');
    expect(chips[1].textContent).toBe('通用');
  });

  it('role=tablist + 每个 chip role=tab + aria-selected', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28 }, { size: 30 }]),
      activeSize: 30,
    });
    const el = renderTabs();
    const tablist = el.querySelector('.size-tabs');
    expect(tablist).not.toBeNull();
    expect(tablist!.getAttribute('role')).toBe('tablist');
    const chips = el.querySelectorAll('button.size-chip');
    for (const chip of chips) {
      expect(chip.getAttribute('role')).toBe('tab');
    }
  });
});

describe('SizeTabs (US-008) AC#1 active 高亮 + 切换', () => {
  it('当前 activeSize 的 chip 加 .active + aria-selected=true', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28 }, { size: 30 }, { size: 32 }]),
      activeSize: 30,
    });
    const el = renderTabs();
    const chips = el.querySelectorAll('button.size-chip');
    expect(chips[0].classList.contains('active')).toBe(false);
    expect(chips[1].classList.contains('active')).toBe(true);
    expect(chips[2].classList.contains('active')).toBe(false);
    expect(chips[1].getAttribute('aria-selected')).toBe('true');
    expect(chips[0].getAttribute('aria-selected')).toBe('false');
  });

  it('点击 chip 调用 setSize(size) 切换 activeSize', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28 }, { size: 30 }, { size: 32 }]),
      activeSize: 28,
    });
    const el = renderTabs();
    const chips = el.querySelectorAll('button.size-chip');
    act(() => {
      chips[2].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useUploadStore.getState().activeSize).toBe(32);
    // 重读 DOM（act 后 React 重渲染，.active 转移到 32）
    const chipsAfter = el.querySelectorAll('button.size-chip');
    expect(chipsAfter[0].classList.contains('active')).toBe(false);
    expect(chipsAfter[2].classList.contains('active')).toBe(true);
  });

  it('点击 null 码 chip 调用 setSize(null)', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28 }, { size: null }]),
      activeSize: 28,
    });
    const el = renderTabs();
    const chips = el.querySelectorAll('button.size-chip');
    act(() => {
      chips[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useUploadStore.getState().activeSize).toBeNull();
  });

  it('activeSize=null 时无 chip 加 .active（防御：找不到匹配项）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28 }, { size: 30 }]),
      activeSize: null,
    });
    const el = renderTabs();
    const activeChips = el.querySelectorAll('button.size-chip.active');
    expect(activeChips.length).toBe(0);
  });
});
