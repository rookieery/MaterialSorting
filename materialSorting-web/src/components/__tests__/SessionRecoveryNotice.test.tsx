// 会话过期自动恢复 US-003 单测：SessionRecoveryNotice 轻加载态。
//   - 空态（sessionRecovering=false）→ 渲染 null（零 DOM 开销）；
//   - 恢复中 → 「正在恢复工作状态…」状态告知（role=status，非阻断无按钮）。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { SessionRecoveryNotice } from '../SessionRecoveryNotice';
import { useUiStore } from '../../store/uiStore';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  useUiStore.setState({ sessionRecovering: false });
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
  useUiStore.setState({ sessionRecovering: false });
});

describe('SessionRecoveryNotice（US-003）', () => {
  it('空态 → 渲染 null（未恢复期间零 DOM）', () => {
    act(() => {
      root!.render(<SessionRecoveryNotice />);
    });
    expect(container!.querySelector('.session-recovery-notice')).toBeNull();
  });

  it('恢复中 → 「正在恢复工作状态…」状态告知（role=status）', () => {
    act(() => {
      root!.render(<SessionRecoveryNotice />);
    });
    act(() => {
      useUiStore.setState({ sessionRecovering: true });
    });
    const el = container!.querySelector('.session-recovery-notice');
    expect(el).not.toBeNull();
    expect(el!.getAttribute('role')).toBe('status');
    expect(el!.textContent).toBe('正在恢复工作状态…');
    // 轻加载态非阻断：无按钮无遮罩
    expect(el!.querySelector('button')).toBeNull();
  });

  it('恢复落定（复位）→ 通知消失', () => {
    act(() => {
      root!.render(<SessionRecoveryNotice />);
    });
    act(() => {
      useUiStore.setState({ sessionRecovering: true });
    });
    expect(container!.querySelector('.session-recovery-notice')).not.toBeNull();
    act(() => {
      useUiStore.setState({ sessionRecovering: false });
    });
    expect(container!.querySelector('.session-recovery-notice')).toBeNull();
  });
});
