// Tooltip —— 片信息浮层（US-006 AC#4..#6）。
//
// 与旧 vanilla 前身 `tooltipEl` 等价：单一 DOM 节点，高频 mousemove 直接 mutate
// style.left/top/display + innerHTML，**不进 React state**（避免 reconciliation 风暴）。
//
// 关键设计：
//   1. React Portal 到 document.body（fixed 定位基准，不被 SVG transform 影响）。
//   2. 模块级单例 _el：Tooltip 组件 mount 时 registerTooltipEl(el)，unmount 时置 null；
//      NestSVG mousemove 处理器调 showTooltip / hideTooltip 操作 DOM，不持有 React 引用。
//   3. style 由 imperative 唯一写入（JSX 不带 style prop），避免 React reconciliation 覆盖。
//
// AC#5：fixed 定位，鼠标 +14/+14 偏移（与旧 vanilla 实现 `e.clientX + 14` 字面量一致）。
// AC#6：mouseleave 隐藏；切换 hover polygon 时 setHovered 自动移除旧 class。

import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

let _el: HTMLDivElement | null = null;
let _hovered: SVGPolygonElement | null = null;

/** 注册 Tooltip DOM（Tooltip 组件 mount/unmount 时调用）。 */
function registerTooltipEl(el: HTMLDivElement | null): void {
  _el = el;
}

/**
 * 设置当前 hover 的 polygon（class 切换；与旧 vanilla 实现 `hoveredEl` 一致）。
 * 新旧相同 → no-op；新旧不同 → 移除旧 class、加新 class。
 * poly=null → 仅清除旧 class。
 */
export function setHovered(poly: SVGPolygonElement | null): void {
  if (_hovered === poly) return;
  if (_hovered) _hovered.classList.remove('hover');
  _hovered = poly;
  if (poly) poly.classList.add('hover');
}

/** 清除 hover（mouseleave / 新求解 start 时调用）。 */
export function clearHovered(): void {
  if (_hovered) _hovered.classList.remove('hover');
  _hovered = null;
}

/**
 * 显示 Tooltip（imperative；高频调用，不走 React state）。
 * AC#5：fixed 定位，鼠标 +14/+14 偏移。
 */
export function showTooltip(x: number, y: number, html: string): void {
  const el = _el;
  if (!el) return;
  el.style.display = 'block';
  el.style.left = `${x + 14}px`;
  el.style.top = `${y + 14}px`;
  el.innerHTML = html;
}

/** 隐藏 Tooltip（mousemove 落到非 polygon / mouseleave / 新 start）。 */
export function hideTooltip(): void {
  if (_el) _el.style.display = 'none';
}

/**
 * Tooltip 组件 —— App 内只渲染一个。
 *
 * 内部：useEffect 在 mount 时把 ref.current 注册到模块单例 + 设 display:none；unmount 时反注册。
 * style 不写 JSX（仅 className），保证 React reconciliation 不会覆盖 imperative 写入。
 */
export function Tooltip(): React.JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.display = 'none';
    registerTooltipEl(el);
    return () => {
      registerTooltipEl(null);
      clearHovered();
    };
  }, []);
  return createPortal(<div ref={ref} className="tooltip" />, document.body);
}
