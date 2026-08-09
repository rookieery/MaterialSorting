// AppState —— Zustand 单字段（+ seek） store。
//
// 设计原则（与 AGENTS.md / .docs/technical/agent-component-map.md 关键不变量 #2 一致）：
//   高频渲染数据（frames / lastFrame）落在 runRegistry 的 mutable 引用里，**不进 React state**。
//   此 store 只持有：
//     1. `renderTick` —— useRafThrottle 每 ~100ms 自增一次，NestSVG / NestLabel / ConvergenceCurve
//        通过订阅 renderTick 逃逸 React reconciliation，直接 setAttribute / 重读 mutable。
//     2. `seekTime`  —— US-006 回放时间（s）。-1 = 跟随 live（用 lastFrame）；>=0 = 拖动 seekbar
//        后的 scrub 时间，NestSVG / SeekReadout 切到 frameAtTime(run, seekTime)。

import { create } from 'zustand';

export interface AppState {
  /** 全局渲染节流闸 —— 每 ~100ms 自增一次，订阅者据此重绘 imperative DOM。 */
  renderTick: number;
  /** 自增 renderTick（由 useRafThrottle 调用）。 */
  bumpRenderTick: () => void;
  /** US-006 回放时间（s）。-1 = 跟随 live；>=0 = scrub 到该时间点。 */
  seekTime: number;
  /** 设置 seekTime（拖 seekbar / 全部完成时默认到末尾 / 新 start 重置 -1）。 */
  setSeekTime: (t: number) => void;
}

export const useAppStore = create<AppState>((set) => ({
  renderTick: 0,
  bumpRenderTick: () => set((s) => ({ renderTick: s.renderTick + 1 })),
  seekTime: -1,
  setSeekTime: (t) => set({ seekTime: t }),
}));
