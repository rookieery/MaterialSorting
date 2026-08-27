// US-005 SessionExpiredModal 单测：阻断式全屏模态（唯一出口 = 刷新按钮）。
//   AC1 未阻断 → 渲染 null（零 DOM 开销）。
//   AC2 session_expired → 「会话已过期（10 分钟无操作），请刷新页面」（不显示上次活动时间）。
//   AC3 session_limit → 「当前使用用户过多（最多 4 人同时在线），请稍后尝试」。
//   AC4 点击「刷新页面」→ location.reload()；无 ✕ / ESC / 遮罩关闭路径。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { SessionExpiredModal } from '../SessionExpiredModal';
import { resetSessionForTest, triggerSessionBlock } from '../../lib/api';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
// jsdom location.reload 未实现 —— 替换为 vi.fn() 断言点击行为。
let reloadMock: ReturnType<typeof vi.fn> | null = null;

beforeEach(() => {
  resetSessionForTest();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  reloadMock = vi.fn();
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: { ...window.location, reload: reloadMock },
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
  resetSessionForTest();
});

function renderModal(): HTMLElement {
  act(() => {
    root!.render(<SessionExpiredModal />);
  });
  return container!;
}

describe('SessionExpiredModal（US-005）', () => {
  it('AC1 未阻断 → 渲染 null（无 overlay DOM）', () => {
    const el = renderModal();
    expect(el.querySelector('.session-block-overlay')).toBeNull();
  });

  it('AC2 session_expired → 指定文案（不显示上次活动时间）+ 刷新按钮可重载', () => {
    const el = renderModal();
    act(() => {
      triggerSessionBlock('session_expired');
    });
    const overlay = el.querySelector('.session-block-overlay');
    expect(overlay).not.toBeNull();
    expect(overlay!.getAttribute('role')).toBe('alertdialog');
    expect(el.querySelector('.session-block-text')!.textContent).toBe(
      '会话已过期（10 分钟无操作），请刷新页面',
    );
    // 唯一出口：刷新按钮 → location.reload()
    const btn = el.querySelector<HTMLButtonElement>('.session-block-reload');
    expect(btn).not.toBeNull();
    expect(btn!.textContent).toBe('刷新页面');
    act(() => {
      btn!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(reloadMock).toHaveBeenCalledTimes(1);
  });

  it('AC3 session_limit → 指定文案', () => {
    const el = renderModal();
    act(() => {
      triggerSessionBlock('session_limit');
    });
    expect(el.querySelector('.session-block-text')!.textContent).toBe(
      '当前使用用户过多（最多 4 人同时在线），请稍后尝试',
    );
  });

  it('AC4 无关闭路径：ESC / 遮罩点击后弹窗仍在（阻断式，刷新是唯一出口）', () => {
    const el = renderModal();
    act(() => {
      triggerSessionBlock('session_expired');
    });
    const overlay = el.querySelector('.session-block-overlay')!;
    act(() => {
      overlay.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    // 仍在 DOM 且未触发 reload
    expect(el.querySelector('.session-block-overlay')).not.toBeNull();
    expect(reloadMock).not.toHaveBeenCalled();
    // 无关闭按钮（不渲染 ✕）
    expect(el.querySelector('.modal-close, .close-btn')).toBeNull();
  });
});
