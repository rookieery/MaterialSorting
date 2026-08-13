// TourOverlay —— tour 高亮引擎（US-029）。
//
// 订阅 tourStore（via useTour）：activeTour===null 时 return null；激活时 createPortal 到
// document.body 渲染：
//   .tour-overlay    全屏容器（position:fixed; inset:0; z-index:2000；高于 ptype-preview 1200）。
//   .tour-spotlight  聚光灯（贴 querySelector(selector).getBoundingClientRect()，
//                    box-shadow:0 0 0 9999px rgba(0,0,0,0.6) 镂空 + #2ea06c 边框；pointer-events:none）。
//   .tour-bubble     气泡（按 placement 在聚光灯四周贴边，溢出视口自动翻向；pointer-events:auto）。
//
// 零尺寸兜底：query 到元素 getBoundingClientRect 全零时回退「居中气泡无高亮」，不报错。
//
// 重算时机（AC）：步骤切换、window resize、scroll（capture 全局）、advance-on-ready 状态变化时
// 重新读 getBoundingClientRect。tick state（resize/scroll listener bump）触发 re-render。
//
// 关键设计（参考 Tooltip.tsx 命令式 Portal 单例范式）：
//   - App 内只挂一个 TourOverlay（App.tsx 顶层单例）。
//   - 定位用 useLayoutEffect imperative 写 style.left/top/width/height（不走 React state）。
//   - bubble 宽度由 CSS max-width 决定（340px），高度由内容撑开；position 用 transform 微调。

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { useTour } from './useTour';
import type { Placement } from './types';

/** 气泡与聚光灯之间的间距（px）。 */
const BUBBLE_GAP_PX = 12;
/** 视口安全边距（px）。 */
const VIEWPORT_PADDING_PX = 8;
/** 气泡最大宽度（px）；CSS 同步 .tour-bubble max-width。 */
const BUBBLE_MAX_WIDTH_PX = 340;
/** 气泡高度保守估算（flip 判断用；实际高度由内容决定）。 */
const BUBBLE_EST_HEIGHT = 220;

interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** 读目标元素的 viewport 坐标 rect；null 或零尺寸返回 null（回退居中）。 */
function readTargetRect(selector: string): Rect | null {
  const el = document.querySelector(selector);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return null;
  return { left: r.left, top: r.top, width: r.width, height: r.height };
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** placement 翻向（溢出视口时）。 */
function flipPlacement(placement: Placement, rect: Rect): Placement {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const bw = Math.min(BUBBLE_MAX_WIDTH_PX, vw - VIEWPORT_PADDING_PX * 2);
  if (placement === 'bottom' && rect.top + rect.height + BUBBLE_GAP_PX + BUBBLE_EST_HEIGHT > vh - VIEWPORT_PADDING_PX) {
    return rect.top - BUBBLE_GAP_PX - BUBBLE_EST_HEIGHT >= VIEWPORT_PADDING_PX ? 'top' : 'bottom';
  }
  if (placement === 'top' && rect.top - BUBBLE_GAP_PX - BUBBLE_EST_HEIGHT < VIEWPORT_PADDING_PX) {
    return rect.top + rect.height + BUBBLE_GAP_PX + BUBBLE_EST_HEIGHT <= vh - VIEWPORT_PADDING_PX ? 'bottom' : 'top';
  }
  if (placement === 'right' && rect.left + rect.width + BUBBLE_GAP_PX + bw > vw - VIEWPORT_PADDING_PX) {
    return rect.left - BUBBLE_GAP_PX - bw >= VIEWPORT_PADDING_PX ? 'left' : 'right';
  }
  if (placement === 'left' && rect.left - BUBBLE_GAP_PX - bw < VIEWPORT_PADDING_PX) {
    return rect.left + rect.width + BUBBLE_GAP_PX + bw <= vw - VIEWPORT_PADDING_PX ? 'right' : 'left';
  }
  return placement;
}

interface BubblePos {
  left: number;
  top: number;
  transform: string;
}

/** 根据 placement + spotlight rect 计算 bubble 定位（left/top + transform）。 */
function computeBubblePos(placement: Placement, rect: Rect | null): BubblePos {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (placement === 'center' || !rect) {
    return { left: vw / 2, top: vh / 2, transform: 'translate(-50%, -50%)' };
  }
  const eff = flipPlacement(placement, rect);
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const halfBW = BUBBLE_MAX_WIDTH_PX / 2;
  switch (eff) {
    case 'top':
      return {
        left: clamp(cx, halfBW + VIEWPORT_PADDING_PX, vw - halfBW - VIEWPORT_PADDING_PX),
        top: Math.max(VIEWPORT_PADDING_PX, rect.top - BUBBLE_GAP_PX),
        transform: 'translate(-50%, -100%)',
      };
    case 'bottom':
      return {
        left: clamp(cx, halfBW + VIEWPORT_PADDING_PX, vw - halfBW - VIEWPORT_PADDING_PX),
        top: Math.min(vh - VIEWPORT_PADDING_PX, rect.top + rect.height + BUBBLE_GAP_PX),
        transform: 'translate(-50%, 0)',
      };
    case 'left':
      return {
        left: Math.max(VIEWPORT_PADDING_PX, rect.left - BUBBLE_GAP_PX),
        top: clamp(cy, VIEWPORT_PADDING_PX, vh - VIEWPORT_PADDING_PX),
        transform: 'translate(-100%, -50%)',
      };
    case 'right':
      return {
        left: Math.min(vw - VIEWPORT_PADDING_PX, rect.left + rect.width + BUBBLE_GAP_PX),
        top: clamp(cy, VIEWPORT_PADDING_PX, vh - VIEWPORT_PADDING_PX),
        transform: 'translate(0, -50%)',
      };
    default:
      return { left: vw / 2, top: vh / 2, transform: 'translate(-50%, -50%)' };
  }
}

export function TourOverlay(): JSX.Element | null {
  const tour = useTour();
  const spotlightRef = useRef<HTMLDivElement>(null);
  const bubbleRef = useRef<HTMLDivElement>(null);
  // tick 由 resize/scroll listener bump，触发 re-render → useLayoutEffect 重读 rect
  const [, setTick] = useState(0);

  const bump = useCallback(() => setTick((t) => t + 1), []);

  // resize / scroll(capture) listener：目标元素位置变 → 重算聚光灯
  useEffect(() => {
    window.addEventListener('resize', bump);
    // capture=true：捕获子滚动容器（如 .panel overflow:auto）的 scroll 事件
    window.addEventListener('scroll', bump, true);
    return () => {
      window.removeEventListener('resize', bump);
      window.removeEventListener('scroll', bump, true);
    };
  }, [bump]);

  const active = tour.activeTour !== null && tour.currentStep !== null;

  // useLayoutEffect：DOM 变更后、paint 前同步定位 spotlight + bubble（无闪烁）
  useLayoutEffect(() => {
    if (!active || !tour.currentStep) return;
    const step = tour.currentStep;
    const rect = readTargetRect(step.selector);
    const isZero = rect === null;

    if (spotlightRef.current) {
      const el = spotlightRef.current;
      if (isZero) {
        el.style.display = 'none';
      } else {
        el.style.display = 'block';
        el.style.left = rect.left + 'px';
        el.style.top = rect.top + 'px';
        el.style.width = rect.width + 'px';
        el.style.height = rect.height + 'px';
      }
    }

    if (bubbleRef.current) {
      const placement: Placement = step.placement ?? 'bottom';
      const eff = isZero ? 'center' : placement;
      const pos = computeBubblePos(eff, rect);
      bubbleRef.current.style.left = pos.left + 'px';
      bubbleRef.current.style.top = pos.top + 'px';
      bubbleRef.current.style.transform = pos.transform;
    }
  }); // 无 dep array：每次 re-render 都跑（确保 resize/scroll/tick 后位置同步）

  const step = tour.currentStep;
  if (!active || !step) return null;

  return createPortal(
    <div className="tour-overlay" data-testid="tour-overlay">
      <div className="tour-spotlight" ref={spotlightRef} data-testid="tour-spotlight" />
      <div
        className="tour-bubble"
        ref={bubbleRef}
        role="dialog"
        aria-modal="false"
        aria-label={step.title}
        data-testid="tour-bubble"
      >
        <div className="tour-title">{step.title}</div>
        <div className="tour-body">{step.body}</div>
        {tour.waiting && tour.readyHint && (
          <div className="tour-waiting" data-testid="tour-waiting">
            {tour.readyHint}
          </div>
        )}
        <div className="tour-buttons">
          <button
            type="button"
            className="tour-btn tour-btn-prev"
            onClick={tour.prev}
            disabled={tour.isFirstStep}
            data-testid="tour-prev"
          >
            上一步
          </button>
          <button
            type="button"
            className="tour-btn tour-btn-next"
            onClick={tour.next}
            disabled={tour.waiting}
            data-testid="tour-next"
          >
            {tour.isLastStep ? '完成' : '下一步'}
          </button>
          <button
            type="button"
            className="tour-btn tour-btn-skip"
            onClick={tour.close}
            data-testid="tour-skip"
          >
            跳过
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
