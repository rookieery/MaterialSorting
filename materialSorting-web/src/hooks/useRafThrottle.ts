// useRafThrottle —— 全局 ~10fps 渲染节流闸。
//
// 旧 legacy/app.js 的等价物：用 `globalLastDraw + performance.now()` 在 onFrame 里节流。
// 迁移到 React 后：把「是否到了重绘时刻」从 onFrame 中剥离出来，单独由 rAF 推进；
// 一旦判定到点，bump renderTick —— NestSVG / NestLabel 订阅后做 imperative 更新。
//
// 设计要点：
//   1. active = false 时完全不调度（无求解时 0 CPU）。
//   2. rAF + 时间戳闸，100ms 间隔 —— 与旧版 `RENDER_INTERVAL_MS = 100` 一致。
//   3. rAF 在隐藏标签页会自动暂停（浏览器节流），避免隐藏时浪费 CPU。
//   4. effect 依赖 [active, bump]，bump 来自 zustand 是稳定引用（不影响重订阅）。

import { useEffect } from 'react';
import { useAppStore } from '../store/appStore';

/** 当 active 为 true 时，每 100ms 自增一次 renderTick。 */
export function useRafThrottle(active: boolean): void {
  const bump = useAppStore((s) => s.bumpRenderTick);

  useEffect(() => {
    if (!active) return;
    let raf = 0;
    let last = 0;
    const tick = (now: number) => {
      if (now - last >= RENDER_INTERVAL_MS) {
        last = now;
        bump();
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, bump]);
}

/** 全局渲染节流间隔（ms）。与旧 app.js RENDER_INTERVAL_MS 一致。 */
export const RENDER_INTERVAL_MS = 100;
