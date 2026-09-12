// AppState —— Zustand 单字段 store。
//
// 设计原则（与 AGENTS.md / .docs/technical/agent-component-map.md 关键不变量 #2 一致）：
//   高频渲染数据（frames / lastFrame）落在 runRegistry 的 mutable 引用里，**不进 React state**。
//   此 store 只持有：
//     1. `renderTick` —— useRafThrottle 每 ~100ms 自增一次，NestSVG / NestLabel
//        通过订阅 renderTick 逃逸 React reconciliation，直接 setAttribute / 重读 mutable。
//
//   （原第 2 字段 `seekTime`（US-006 回放 scrub 时间）随回放功能于 2026-09-12 移除。）

import { create } from 'zustand';

export interface AppState {
  /** 全局渲染节流闸 —— 每 ~100ms 自增一次，订阅者据此重绘 imperative DOM。 */
  renderTick: number;
  /** 自增 renderTick（由 useRafThrottle 调用）。 */
  bumpRenderTick: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  renderTick: 0,
  bumpRenderTick: () => set((s) => ({ renderTick: s.renderTick + 1 })),
}));
