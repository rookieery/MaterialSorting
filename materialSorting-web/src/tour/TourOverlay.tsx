// TourOverlay —— tour 高亮引擎（US-029 基础设施 / US-032 关闭交互 + reduced-motion + scrollIntoView）。
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
// US-032 新增：
//   - 关闭交互完备：ESC 关闭（window keydown）；遮罩点击关闭（onMouseDown e.target===e.currentTarget，
//     参考 .piece-qty-dialog-overlay 模式，spotlight pointer-events:none 让点击穿透到 overlay）；
//     「跳过」按钮 markSeen + close（视为已读不再自动触发）。
//   - prefers-reduced-motion：检测 window.matchMedia，为真时 overlay 加 .tour-reduced-motion class，
//     CSS 禁用 spotlight/bubble 过渡动画（直接定位）。
//   - scrollIntoView：高亮前 element.scrollIntoView({block:'nearest'})，避免目标在视口外时聚光灯
//     贴到视口边缘外。
//   - StrictMode 双 mount 幂等：所有 listener 在 useEffect cleanup 中卸载，StrictMode 双 mount 下
//     add → cleanup → add 最终仅一套 listener（参考 Tooltip.tsx registerTooltipEl 单例范式）。
//
// 关键设计（参考 Tooltip.tsx 命令式 Portal 单例范式）：
//   - App 内只挂一个 TourOverlay（App.tsx 顶层单例）。
//   - 定位用 useLayoutEffect imperative 写 style.left/top/width/height（不走 React state）。
//   - bubble 宽度由 CSS max-width 决定（340px），高度由内容撑开；position 用 transform 微调。

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { JSX, MouseEvent } from 'react';
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

/** 读元素的 viewport 坐标 rect；null 或零尺寸返回 null（回退居中）。US-032 改为接收 element（避免 querySelector 重复调用）。 */
function readRect(el: Element | null): Rect | null {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return null;
  return { left: r.left, top: r.top, width: r.width, height: r.height };
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** placement 级联回退（目标贴近视口边缘 / 几乎铺满时）。
 *
 * 顺序：原方向 → 反向 → 交叉方向（水平放不下试垂直，垂直放不下试水平）→ center 兜底。
 *
 * bug3 根因：旧版只在「原方向 ↔ 反向」之间二选一，当目标几乎铺满视口（如 result 步的
 * nest-wrap 占满右侧、左右两侧都放不下 340px 气泡）时回退原方向，computeBubblePos 的
 * 'right' 分支把气泡 left 钳到 vw-8、translate(0,-50%) 让它向右溢出视口 —— 表现为
 * 「只有聚光灯框选、没有介绍气泡」。现改为四方向都不满足时退到 center，保证气泡始终可见。 */
export function flipPlacement(placement: Placement, rect: Rect): Placement {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const bw = Math.min(BUBBLE_MAX_WIDTH_PX, vw - VIEWPORT_PADDING_PX * 2);

  // 各方向是否有空间放下气泡（水平按 bw，垂直按保守估算 BUBBLE_EST_HEIGHT）。
  const fitsRight = rect.left + rect.width + BUBBLE_GAP_PX + bw <= vw - VIEWPORT_PADDING_PX;
  const fitsLeft = rect.left - BUBBLE_GAP_PX - bw >= VIEWPORT_PADDING_PX;
  const fitsBottom =
    rect.top + rect.height + BUBBLE_GAP_PX + BUBBLE_EST_HEIGHT <= vh - VIEWPORT_PADDING_PX;
  const fitsTop = rect.top - BUBBLE_GAP_PX - BUBBLE_EST_HEIGHT >= VIEWPORT_PADDING_PX;

  // 级联顺序：首选原方向 → 反向 → 交叉方向；全不满足时函数末尾兜底 center。
  const cascade: readonly Placement[] =
    placement === 'right'
      ? ['right', 'left', 'bottom', 'top']
      : placement === 'left'
        ? ['left', 'right', 'bottom', 'top']
        : placement === 'bottom'
          ? ['bottom', 'top', 'right', 'left']
          : placement === 'top'
            ? ['top', 'bottom', 'right', 'left']
            : ['center'];

  for (const p of cascade) {
    if (p === 'center') return 'center';
    if (p === 'right' && fitsRight) return 'right';
    if (p === 'left' && fitsLeft) return 'left';
    if (p === 'bottom' && fitsBottom) return 'bottom';
    if (p === 'top' && fitsTop) return 'top';
  }
  return 'center';
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
  // US-032：prefers-reduced-motion 检测（matchMedia + change listener）
  const [reducedMotion, setReducedMotion] = useState(false);

  const bump = useCallback(() => setTick((t) => t + 1), []);

  const active = tour.activeTour !== null && tour.currentStep !== null;

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

  // US-032：prefers-reduced-motion 检测 + 变化监听
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReducedMotion(mq.matches);
    const handler = (e: MediaQueryListEvent): void => setReducedMotion(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  // US-032：ESC 关闭 tour（仅 active 时挂 window keydown）
  useEffect(() => {
    if (!active) return;
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.preventDefault();
        tour.close();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, tour.close]);

  // US-032：遮罩点击关闭（仅落在 overlay 自身，e.target===e.currentTarget；spotlight pointer-events:none
  // 让点击穿透到 overlay；bubble pointer-events:auto 点击不冒泡到 overlay close 判定）
  const handleOverlayMouseDown = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      if (e.target === e.currentTarget) {
        tour.close();
      }
    },
    [tour.close],
  );

  // useLayoutEffect：DOM 变更后、paint 前同步定位 spotlight + bubble（无闪烁）
  useLayoutEffect(() => {
    if (!active || !tour.currentStep) return;
    const step = tour.currentStep;

    // US-032：高亮前 scrollIntoView，避免目标在视口外时聚光灯贴到视口边缘外。
    // typeof guard 防止 jsdom 等环境未实现 scrollIntoView（不阻塞定位逻辑）。
    const el = document.querySelector(step.selector);
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'nearest' });
    }
    const rect = readRect(el);
    const isZero = rect === null;

    if (spotlightRef.current) {
      const spotlightEl = spotlightRef.current;
      if (isZero) {
        spotlightEl.style.display = 'none';
      } else {
        spotlightEl.style.display = 'block';
        spotlightEl.style.left = rect.left + 'px';
        spotlightEl.style.top = rect.top + 'px';
        spotlightEl.style.width = rect.width + 'px';
        spotlightEl.style.height = rect.height + 'px';
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
    <div
      className={`tour-overlay${reducedMotion ? ' tour-reduced-motion' : ''}`}
      onMouseDown={handleOverlayMouseDown}
      data-testid="tour-overlay"
    >
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
            onClick={tour.skip}
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
