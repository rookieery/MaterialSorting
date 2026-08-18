// US-006 Tooltip 单测：
//   - 注册 / 反注册（mount/unmount）模块单例
//   - showTooltip / hideTooltip imperative 写 style + innerHTML
//   - setHovered / clearHovered 切换 polygon.hover class（AC#6）
//   - 切换 polygon 时旧 class 自动移除
//   - Portal 挂到 body（AC#5）

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  Tooltip,
  showTooltip,
  hideTooltip,
  setHovered,
  clearHovered,
} from '../Tooltip';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  // 清掉 body 上残留 tooltip（前一个测试 unmount 应已清，但保险）
  for (const el of Array.from(document.body.querySelectorAll('.tooltip'))) el.remove();
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
  for (const el of Array.from(document.body.querySelectorAll('.tooltip'))) el.remove();
});

function mountTooltip(): HTMLDivElement | null {
  act(() => {
    root!.render(
      <StrictMode>
        <Tooltip />
      </StrictMode>,
    );
  });
  return document.body.querySelector('.tooltip');
}

function makePolygon(): SVGPolygonElement {
  // SVG namespace polygon + dataset 填充（与 NestSVG 实际产物一致）。
  const SVGNS = 'http://www.w3.org/2000/svg';
  const poly = document.createElementNS(SVGNS, 'polygon') as SVGPolygonElement;
  poly.dataset.label = 'g01';
  poly.dataset.size = '30';
  poly.dataset.area = '12345';
  return poly;
}

describe('Tooltip (US-006 AC#4..#6)', () => {
  it('mount 后 Portal 挂到 body，初始 display:none（AC#5）', () => {
    const el = mountTooltip();
    expect(el).not.toBeNull();
    expect(el!.tagName).toBe('DIV');
    expect(el!.className).toBe('tooltip');
    expect(el!.parentElement).toBe(document.body);
    expect(el!.style.display).toBe('none');
  });

  it('showTooltip 写 left/top/display/innerHTML（+14 偏移，AC#5）', () => {
    mountTooltip();
    showTooltip(100, 200, 'hello<br>world');
    const el = document.body.querySelector('.tooltip') as HTMLDivElement;
    expect(el.style.display).toBe('block');
    expect(el.style.left).toBe('114px'); // 100 + 14
    expect(el.style.top).toBe('214px'); // 200 + 14
    expect(el.innerHTML).toBe('hello<br>world');
  });

  it('hideTooltip 设 display:none', () => {
    mountTooltip();
    showTooltip(0, 0, 'x');
    hideTooltip();
    const el = document.body.querySelector('.tooltip') as HTMLDivElement;
    expect(el.style.display).toBe('none');
  });

  it('showTooltip 在 Tooltip 未挂载时是 no-op（不抛错）', () => {
    expect(() => showTooltip(0, 0, 'x')).not.toThrow();
  });

  it('unmount 后 showTooltip 是 no-op（已反注册）', () => {
    mountTooltip();
    expect(() => {
      if (root) {
        const r = root;
        act(() => {
          r.unmount();
        });
        root = null;
      }
      showTooltip(0, 0, 'x');
    }).not.toThrow();
    // body 已无 .tooltip
    expect(document.body.querySelector('.tooltip')).toBeNull();
  });
});

describe('setHovered / clearHovered (US-006 AC#6)', () => {
  it('setHovered 给 polygon 加 hover class', () => {
    const poly = makePolygon();
    setHovered(poly);
    expect(poly.classList.contains('hover')).toBe(true);
  });

  it('setHovered 同一 polygon 两次 → 不重复操作（幂等）', () => {
    const poly = makePolygon();
    setHovered(poly);
    setHovered(poly);
    expect(poly.classList.contains('hover')).toBe(true);
    // classList 长度为 1（不重复 add）
    expect(poly.classList.length).toBe(1);
  });

  it('切换 polygon：旧的移除 class，新的加 class（AC#6 核心）', () => {
    const p1 = makePolygon();
    const p2 = makePolygon();
    setHovered(p1);
    expect(p1.classList.contains('hover')).toBe(true);
    expect(p2.classList.contains('hover')).toBe(false);

    setHovered(p2);
    expect(p1.classList.contains('hover')).toBe(false); // ← 旧的移除
    expect(p2.classList.contains('hover')).toBe(true);
  });

  it('setHovered(null) 移除当前高亮', () => {
    const poly = makePolygon();
    setHovered(poly);
    setHovered(null);
    expect(poly.classList.contains('hover')).toBe(false);
  });

  it('clearHovered 移除当前高亮', () => {
    const poly = makePolygon();
    setHovered(poly);
    clearHovered();
    expect(poly.classList.contains('hover')).toBe(false);
  });

  it('clearHovered 无当前高亮时是 no-op（不抛错）', () => {
    expect(() => clearHovered()).not.toThrow();
  });
});
