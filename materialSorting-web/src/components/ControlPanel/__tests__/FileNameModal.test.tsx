// FileNameModal（2026-09-12 需求 1）测试：保存 / DXF·PNG 导出的「文件名」确认弹窗。
//   1. 标题「文件名」+ 输入框预填 defaultName + 取消/确认按钮
//   2. 取消路径四条（取消按钮 / ✕ / ESC / 遮罩）= 只关不导
//   3. 确认 → onConfirm 携 trim 后输入值（编辑生效）
//   4. 空名（纯空白）→ 确认置灰；exporting → 确认置灰
//   5. Enter = 确认（单输入框键盘期望）
//
// 套路同 ExportInfoModal.test：createRoot + act + data-testid，不包 StrictMode。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { FileNameModal } from '../FileNameModal';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

const DEFAULT_NAME = 'M1787_码28-30_88.42pct_seed0';

function renderModal(
  onConfirm: (name: string) => void = vi.fn(),
  onCancel: () => void = vi.fn(),
  exporting = false,
): void {
  act(() => {
    root!.render(
      <FileNameModal
        defaultName={DEFAULT_NAME}
        exporting={exporting}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
  });
}

/** 模拟用户输入（React 受控 input：原生 value setter + input 事件防值追踪吞改）。 */
function setName(value: string): void {
  const input = document.querySelector<HTMLInputElement>('[data-testid="save-name-input"]')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

function confirmBtn(): HTMLButtonElement {
  return document.querySelector<HTMLButtonElement>('[data-testid="save-name-confirm"]')!;
}

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
});

describe('FileNameModal（2026-09-12 需求 1）', () => {
  it('标题「文件名」+ 输入框预填 defaultName + 取消/确认按钮在场', () => {
    renderModal();
    const modal = document.querySelector('.strategy-modal')!;
    expect(modal.getAttribute('aria-label')).toBe('文件名');
    expect(modal.querySelector('.strategy-title')!.textContent).toBe('文件名');
    const input = modal.querySelector<HTMLInputElement>('[data-testid="save-name-input"]')!;
    expect(input.value).toBe(DEFAULT_NAME);
    expect(modal.querySelector<HTMLButtonElement>('[data-testid="save-name-cancel"]')!.textContent)
      .toBe('取消');
    expect(confirmBtn().textContent).toBe('确认');
    expect(confirmBtn().disabled).toBe(false);
  });

  it.each([
    ['取消按钮', () => document.querySelector<HTMLButtonElement>('[data-testid="save-name-cancel"]')!.click()],
    ['✕', () => document.querySelector<HTMLButtonElement>('[data-testid="save-name-close"]')!.click()],
    ['ESC', () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))],
    ['遮罩', () => {
      const overlay = document.querySelector<HTMLElement>('[data-testid="save-name-overlay"]')!;
      overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    }],
  ])('取消路径（%s）→ onCancel 只关不导', (_name, trigger) => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    renderModal(onConfirm, onCancel);
    act(() => {
      trigger();
    });
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('确认 → onConfirm 携 trim 后的编辑值', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    renderModal(onConfirm, onCancel);
    setName('  夏季新款_28-30  ');
    act(() => {
      confirmBtn().click();
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][0]).toBe('夏季新款_28-30');
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('空名（清空/纯空白）→ 确认置灰，不触发 onConfirm', () => {
    const onConfirm = vi.fn();
    renderModal(onConfirm);
    setName('   ');
    expect(confirmBtn().disabled).toBe(true);
    act(() => {
      confirmBtn().click(); // disabled 点击无事件；兜底 handleConfirm 空名短路
    });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('exporting → 确认置灰（防连击）', () => {
    renderModal(vi.fn(), vi.fn(), true);
    expect(confirmBtn().disabled).toBe(true);
  });

  it('输入框 Enter = 确认（trim 值）', () => {
    const onConfirm = vi.fn();
    renderModal(onConfirm);
    setName('回车确认');
    const input = document.querySelector<HTMLInputElement>('[data-testid="save-name-input"]')!;
    act(() => {
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][0]).toBe('回车确认');
  });
});
