// PanelSplitter —— 左侧面板与主区之间的伸缩分隔条（2026-10-05，VS Code sash 风格）。
//
// 职责：
//   1. 8px 宽透明热区（负 margin 贴在 .panel 右边框上，净占宽 0，主区不损失像素），
//      hover / 拖拽中显示 2px 蓝色竖线（#0078d4）+ cursor: col-resize（CSS 实现，
//      见 style.css `.panel-splitter`；拖拽中 :active 由 pointer capture 保持）。
//   2. pointerdown 捕获（setPointerCapture，拖出元素 / 压到 SVG 画布上事件仍路由
//      回本元素）→ pointermove 按 delta 增减宽度 → pointerup 释放；范围 clamp
//      （200~300）在 uiStore.setPanelWidth 内统一把关。
//   3. 双击重置默认 248（VS Code sash 同款行为）；拖动期间 body.panel-resizing
//      统一 col-resize 光标 + 禁文本选择（拖到 SVG 画布/数量矩阵上光标不变样、
//      不误选文字）。
//
// 设计要点：
//   - 宽度真相源 = uiStore.panelWidth（UploadPanel / ControlPanel 订阅渲染 inline
//     width），本组件只写不持有 —— 两页共享同值，切 Tab 不跳变。
//   - delta 基准（startRef 记按下时的 clientX + 当时宽度）而非 clientX 直读面板右缘：
//     与 clamp 解耦 —— 拖过头继续反向拖立即生效无死区，且不受面板起点位置影响。
//   - 拖拽中不写 localStorage（高频 IO 无意义），pointerup 时 persist 一次。
//   - jsdom 无 setPointerCapture → 能力探测跳过（测试仍可 fireEvent 拖拽；
//     onLostPointerCapture 兜底真实浏览器的捕获丢失，如元素被移出 DOM）。

import { useRef } from 'react';
import type { JSX, PointerEvent as ReactPointerEvent } from 'react';
import { PANEL_W_MAX, PANEL_W_MIN, useUiStore } from '../store/uiStore';

export function PanelSplitter(): JSX.Element {
  /** 拖拽进行中 flag（ref 非 state：拖拽期间本组件零重渲染，视觉态走 CSS :active）。 */
  const draggingRef = useRef(false);
  /** 拖拽基准：按下时 clientX + 当时面板宽（新宽 = w + (clientX − x)）。 */
  const startRef = useRef({ x: 0, w: 0 });

  function handlePointerDown(e: ReactPointerEvent<HTMLDivElement>): void {
    // 仅左键拖拽（右键保留给上下文菜单 / 编辑画布手势族）。
    if (e.button !== 0) return;
    if (typeof e.currentTarget.setPointerCapture === 'function') {
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    draggingRef.current = true;
    startRef.current = { x: e.clientX, w: useUiStore.getState().panelWidth };
    document.body.classList.add('panel-resizing');
  }

  function handlePointerMove(e: ReactPointerEvent<HTMLDivElement>): void {
    if (!draggingRef.current) return;
    const { x, w } = startRef.current;
    useUiStore.getState().setPanelWidth(w + (e.clientX - x));
  }

  /** 结束拖拽：撤 body class + 落一次 localStorage（幂等 —— 非拖拽态调用电溶）。 */
  function endDrag(): void {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    document.body.classList.remove('panel-resizing');
    useUiStore.getState().persistPanelWidth();
  }

  // aria-valuenow 订阅当前宽度：每次拖动多一次本组件轻重渲染（树只有本节点），
  // 换取 role=separator 的完整可访问性（min/max/now 齐备）。
  const width = useUiStore((s) => s.panelWidth);

  return (
    <div
      className="panel-splitter"
      role="separator"
      aria-orientation="vertical"
      aria-label="调整左侧面板宽度"
      aria-valuemin={PANEL_W_MIN}
      aria-valuemax={PANEL_W_MAX}
      aria-valuenow={width}
      title="拖动调整宽度 · 双击重置"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onLostPointerCapture={endDrag}
      onDoubleClick={() => useUiStore.getState().resetPanelWidth()}
    />
  );
}
