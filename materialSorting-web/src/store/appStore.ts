// AppState —— Zustand 单字段 store。
//
// 设计原则（与 AGENTS.md / .docs/agent-component-map.md 关键不变量 #2 一致）：
//   高频渲染数据（frames / lastFrame）落在 runRegistry 的 mutable 引用里，**不进 React state**。
//   此 store 只持有一个 `renderTick` 单字段 —— useRafThrottle 每 ~100ms 自增一次，
//   NestSVG / NestLabel 通过订阅 renderTick 逃逸 React reconciliation，直接 setAttribute / 重读 mutable。
//
// 这样 React 不会因为高频 frame push 触发 reconciliation 风暴；只有真正需要重绘的 imperative
// DOM（polygon points / 翻转组 viewBox）通过 ref + setAttribute 更新。

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
