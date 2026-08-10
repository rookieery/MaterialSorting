// US-012 Switch 单测（≥5 项）：
//   AC: role=switch + aria-checked / 点击 onChange(true)/(false) / labelOn/labelOff 文案
//       / disabled 不触发 onChange / 初始 checked 控制

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Switch } from '../Switch';

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
});

function renderSwitch(props: Parameters<typeof Switch>[0]): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <Switch {...props} />
      </StrictMode>,
    );
  });
  return container!;
}

describe('Switch (US-012)', () => {
  it('role=switch + aria-checked 跟随 checked prop', () => {
    const onChange = vi.fn();
    let el = renderSwitch({
      checked: false,
      onChange,
      labelOn: '全部尺码',
      labelOff: '仅当前尺码',
    });
    let btn = el.querySelector('button.switch')!;
    expect(btn.getAttribute('role')).toBe('switch');
    expect(btn.getAttribute('aria-checked')).toBe('false');

    act(() => {
      root!.render(
        <StrictMode>
          <Switch checked={true} onChange={onChange} labelOn="全部尺码" labelOff="仅当前尺码" />
        </StrictMode>,
      );
    });
    btn = el.querySelector('button.switch')!;
    expect(btn.getAttribute('aria-checked')).toBe('true');
  });

  it('checked=false 点击 -> onChange(true)；checked=true 点击 -> onChange(false)', () => {
    const onChange = vi.fn();
    const el = renderSwitch({
      checked: false,
      onChange,
      labelOn: '全部尺码',
      labelOff: '仅当前尺码',
    });
    const btn = el.querySelector('button.switch')!;
    act(() => {
      btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith(true);
    expect(onChange).toHaveBeenCalledTimes(1);

    act(() => {
      root!.render(
        <StrictMode>
          <Switch checked={true} onChange={onChange} labelOn="全部尺码" labelOff="仅当前尺码" />
        </StrictMode>,
      );
    });
    const btn2 = el.querySelector('button.switch')!;
    act(() => {
      btn2.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onChange).toHaveBeenLastCalledWith(false);
  });

  it('labelOn / labelOff 文案在 DOM 中渲染', () => {
    const el = renderSwitch({
      checked: false,
      onChange: vi.fn(),
      labelOn: '全部尺码',
      labelOff: '仅当前尺码',
    });
    expect(el.querySelector('.switch-label-on')!.textContent).toBe('全部尺码');
    expect(el.querySelector('.switch-label-off')!.textContent).toBe('仅当前尺码');
  });

  it('disabled=true -> button.disabled + 点击不触发 onChange', () => {
    const onChange = vi.fn();
    const el = renderSwitch({
      checked: false,
      onChange,
      labelOn: '全部尺码',
      labelOff: '仅当前尺码',
      disabled: true,
    });
    const btn = el.querySelector('button.switch') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    act(() => {
      btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('.on class 跟随 checked（用于 CSS 滑块平移）', () => {
    const onChange = vi.fn();
    const el = renderSwitch({
      checked: true,
      onChange,
      labelOn: '全部尺码',
      labelOff: '仅当前尺码',
    });
    const btn = el.querySelector('button.switch')!;
    expect(btn.classList.contains('on')).toBe(true);
  });
});
