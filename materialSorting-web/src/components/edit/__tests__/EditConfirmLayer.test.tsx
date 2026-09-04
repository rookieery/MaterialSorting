// 编辑排料 US-004 EditConfirmLayer 单测：自定义暗色小确认层（主面板重置 confirm 与
// 弹窗 ✕ dirty 确认共用组件）—— Portal 到 body、文案透传、双按钮回调、
// 默认按钮文案（确认/取消）、自定义文案透传。纯受控无自身 state。
// （重置/弃稿各自的业务接线断言在 EditLayoutControls.test / EditLayoutModal.test。）

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditConfirmLayer } from '../EditConfirmLayer';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
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
  document.body.innerHTML = '';
});

function renderLayer(props: Parameters<typeof EditConfirmLayer>[0]): void {
  act(() => {
    root!.render(<EditConfirmLayer {...props} />);
  });
}

describe('EditConfirmLayer (US-004)', () => {
  it('Portal 到 body（逃逸编辑弹窗 overflow:hidden）+ 文案透传', () => {
    renderLayer({ message: '确认将当前更新后的排料布局重置回初始布局', onConfirm: () => {}, onCancel: () => {} });
    // 挂在 body 直下（非 container 内）
    const overlay = document.body.querySelector('[data-testid="edit-confirm-overlay"]');
    expect(overlay).not.toBeNull();
    expect(container!.contains(overlay!)).toBe(false);
    expect(
      document.querySelector('[data-testid="edit-confirm-message"]')!.textContent,
    ).toBe('确认将当前更新后的排料布局重置回初始布局');
  });

  it('默认按钮文案 确认/取消；自定义文案透传', () => {
    renderLayer({ message: 'm', onConfirm: () => {}, onCancel: () => {} });
    expect(
      document.querySelector('[data-testid="edit-confirm-ok"]')!.textContent,
    ).toBe('确认');
    expect(
      document.querySelector('[data-testid="edit-confirm-cancel"]')!.textContent,
    ).toBe('取消');
    renderLayer({ message: 'm', onConfirm: () => {}, onCancel: () => {}, confirmText: '放弃', cancelText: '继续编辑' });
    expect(
      document.querySelector('[data-testid="edit-confirm-ok"]')!.textContent,
    ).toBe('放弃');
    expect(
      document.querySelector('[data-testid="edit-confirm-cancel"]')!.textContent,
    ).toBe('继续编辑');
  });

  it('双按钮各自回调（取消保持原状 / 确认执行动作）', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    renderLayer({ message: 'm', onConfirm, onCancel });
    act(() => {
      (document.querySelector('[data-testid="edit-confirm-cancel"]') as HTMLButtonElement).click();
    });
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
    act(() => {
      (document.querySelector('[data-testid="edit-confirm-ok"]') as HTMLButtonElement).click();
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('ESC keydown 与遮罩 mousedown 均无动作（显式按钮唯一路径）', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    renderLayer({ message: 'm', onConfirm, onCancel });
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      document
        .querySelector('[data-testid="edit-confirm-overlay"]')!
        .dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
    expect(
      document.querySelector('[data-testid="edit-confirm-overlay"]'),
    ).not.toBeNull();
  });
});
