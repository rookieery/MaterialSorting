// US-027 SolvePhase —— 求解状态机五态（驱动 US-028 SolveControls 按钮组渲染）。
//
// 转换图（NestingPage 持有，onDone 汇总线区分）：
//   idle ──start──▶ running ──final────▶ done
//                   running ──stopped──▶ stopped
//                   running ──error────▶ error
//   stopped/done/error ──restart──▶ running（经 handleRestart = clear + handleStart）
//
// 关键不变量：phase 切换只发生在 NestingPage；子组件（ControlPanel / SolveControls）
// 纯受控渲染，不自持 phase。多 seed 场景所有 onDone 到齐后才统一切 phase。

/** 求解状态机五态。 */
export type SolvePhase = 'idle' | 'running' | 'stopped' | 'done' | 'error';
