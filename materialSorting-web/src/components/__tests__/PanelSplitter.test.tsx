// PanelSplitter 单测（2026-10-05 面板伸缩分隔条）：
//   - 渲染：role=separator + aria min/max/now（默认 248）
//   - 拖拽：pointerdown → pointermove 按 delta 增减 uiStore.panelWidth，clamp 200/300
//   - delta 基准与钳制解耦：从越界位置反向拖立即生效（无死区）
//   - 拖拽期间 body.panel-resizing 挂 / pointerup 摘 + localStorage 落值
//   - 非左键（button=2）不进入拖拽
//   - 双击重置默认 248
//
// jsdom 无 PointerEvent 类与 setPointerCapture → 用 MouseEvent 派发 pointer* 事件名
// （React 按事件名监听，clientX/button 是 MouseEvent 属性）；组件内 setPointerCapture
// 能力探测跳过，拖拽逻辑不依赖捕获即可全链路复验。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PanelSplitter } from '../PanelSplitter';
import { PANEL_W_DEFAULT, useUiStore } from '../../store/uiStore';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  // 面板宽回默认 + 清记忆，避免前一个测试残留（store 单例跨用例共享）。
  useUiStore.setState({ panelWidth: PANEL_W_DEFAULT });
  localStorage.removeItem('ms_panel_w');
  document.body.classList.remove('panel-resizing');
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
  document.body.classList.remove('panel-resizing');
});

function mountSplitter(): HTMLDivElement {
  act(() => {
    root!.render(
      <StrictMode>
        <PanelSplitter />
      </StrictMode>,
    );
  });
  const el = container!.querySelector<HTMLDivElement>('.panel-splitter');
  expect(el).not.toBeNull();
  return el!;
}

/** 派发 pointer 系 / dblclick 事件（MouseEvent 承载 clientX/button，React 按事件名路由）。 */
function fire(el: HTMLElement, type: string, opts: { clientX?: number; button?: number } = {}): void {
  act(() => {
    el.dispatchEvent(
      new MouseEvent(type, {
        bubbles: true,
        cancelable: true,
        clientX: opts.clientX ?? 0,
        button: opts.button ?? 0,
      }),
    );
  });
}

describe('PanelSplitter', () => {
  it('渲染 role=separator + aria 范围与当前值', () => {
    const el = mountSplitter();
    expect(el.getAttribute('role')).toBe('separator');
    expect(el.getAttribute('aria-orientation')).toBe('vertical');
    expect(el.getAttribute('aria-valuemin')).toBe('200');
    expect(el.getAttribute('aria-valuemax')).toBe('300');
    expect(el.getAttribute('aria-valuenow')).toBe('248');
  });

  it('拖拽按 delta 增减宽度并钳制在 [200, 300]', () => {
    const el = mountSplitter();
    fire(el, 'pointerdown', { clientX: 300 }); // 基准：x=300, w=248
    fire(el, 'pointermove', { clientX: 360 }); // +60 → 308 → 钳 300
    expect(useUiStore.getState().panelWidth).toBe(300);
    fire(el, 'pointermove', { clientX: 320 }); // +20 → 268
    expect(useUiStore.getState().panelWidth).toBe(268);
    fire(el, 'pointermove', { clientX: 100 }); // −200 → 68 → 钳 200
    expect(useUiStore.getState().panelWidth).toBe(200);
  });

  it('越界后反向拖立即生效（delta 基准与钳制解耦，无死区）', () => {
    const el = mountSplitter();
    fire(el, 'pointerdown', { clientX: 400 }); // 基准：x=400, w=248
    fire(el, 'pointermove', { clientX: 800 }); // +400 → 钳 300（越界 100px）
    expect(useUiStore.getState().panelWidth).toBe(300);
    fire(el, 'pointermove', { clientX: 750 }); // 逻辑宽 248+350=598 仍 >300，钳 300
    expect(useUiStore.getState().panelWidth).toBe(300);
    fire(el, 'pointermove', { clientX: 340 }); // 逻辑宽 248−60=188 → 钳 200（立即回界内）
    expect(useUiStore.getState().panelWidth).toBe(200);
  });

  it('拖拽期间 body.panel-resizing 挂载，pointerup 摘除并落 localStorage', () => {
    const el = mountSplitter();
    fire(el, 'pointerdown', { clientX: 100 });
    expect(document.body.classList.contains('panel-resizing')).toBe(true);
    expect(localStorage.getItem('ms_panel_w')).toBeNull(); // 拖拽中不碰 IO
    fire(el, 'pointermove', { clientX: 150 }); // → 298
    expect(useUiStore.getState().panelWidth).toBe(298);
    fire(el, 'pointerup');
    expect(document.body.classList.contains('panel-resizing')).toBe(false);
    expect(localStorage.getItem('ms_panel_w')).toBe('298');
  });

  it('pointermove 未按下时是 no-op（悬停不移动宽度）', () => {
    const el = mountSplitter();
    fire(el, 'pointermove', { clientX: 999 });
    expect(useUiStore.getState().panelWidth).toBe(PANEL_W_DEFAULT);
  });

  it('非左键（button=2）不进入拖拽', () => {
    const el = mountSplitter();
    fire(el, 'pointerdown', { clientX: 100, button: 2 });
    fire(el, 'pointermove', { clientX: 200 });
    expect(useUiStore.getState().panelWidth).toBe(PANEL_W_DEFAULT);
    expect(document.body.classList.contains('panel-resizing')).toBe(false);
  });

  it('双击重置默认 248 并落盘', () => {
    const el = mountSplitter();
    fire(el, 'pointerdown', { clientX: 100 });
    fire(el, 'pointermove', { clientX: 140 }); // → 288
    fire(el, 'pointerup');
    expect(useUiStore.getState().panelWidth).toBe(288);
    fire(el, 'dblclick');
    expect(useUiStore.getState().panelWidth).toBe(PANEL_W_DEFAULT);
    expect(localStorage.getItem('ms_panel_w')).toBe('248');
  });
});
