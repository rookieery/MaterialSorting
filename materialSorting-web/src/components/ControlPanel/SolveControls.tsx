// US-028 SolveControls —— 按 phase 渲染的求解按钮组（替代单一 StartButton）。
//
// 五态渲染（phase 由 NestingPage 持有，本组件纯受控）：
//   idle    → 「开始求解」（等价旧 StartButton，调 onStart；保留 #start id 复用 CSS）
//   running → 「停止」（调 onStop；#stop id，红色警示）
//   stopped → 「重新开始」（调 onRestart；#restart id）
//   done    → 「再次求解」（调 onRestart；#restart id，文案差异区分 done / stopped|error）
//   error   → 「重新开始」（调 onRestart；#restart id）
//
// 「导出」按钮不在本组件 —— 由 ExportButtons 独立渲染（受 phase==='running' 禁用）。
// stopped/done/error 态「导出」可用（registry 保留帧时），中间方案提示由 ExportButtons 内 partial flag 渲染。
//
// a11y：每个按钮带 aria-label（含「求解」语义；停止/重新开始可键盘触发 = 原生 button 默认可聚焦）。
// 视觉沿用 style.css 暗色系（不引入 CSS 框架）：#start 绿、#stop 红、#restart 绿（与 #start 同色，主操作语义）。

import type { SolvePhase } from '../../types/solvePhase';

export interface SolveControlsProps {
  /** 求解状态机五态（NestingPage 持有；本组件纯受控）。 */
  phase: SolvePhase;
  /** idle 态点击「开始求解」（ControlPanel.handleStart 内含码号校验）。 */
  onStart: () => void;
  /** running 态点击「停止」（调 useSolveRun.stop → 后端 terminate → onDone 切 phase）。 */
  onStop: () => void;
  /** stopped/done/error 态点击「重新开始 / 再次求解」（用 lastStartCfgRef 走 handleStart）。 */
  onRestart: () => void;
}

export function SolveControls({ phase, onStart, onStop, onRestart }: SolveControlsProps) {
  if (phase === 'running') {
    return (
      <button
        id="stop"
        type="button"
        className="solve-btn stop"
        onClick={onStop}
        aria-label="停止求解"
      >
        停止
      </button>
    );
  }

  if (phase === 'stopped' || phase === 'error') {
    return (
      <button
        id="restart"
        type="button"
        className="solve-btn restart"
        onClick={onRestart}
        aria-label="重新开始求解"
      >
        重新开始
      </button>
    );
  }

  if (phase === 'done') {
    return (
      <button
        id="restart"
        type="button"
        className="solve-btn restart"
        onClick={onRestart}
        aria-label="再次求解"
      >
        再次求解
      </button>
    );
  }

  // idle（默认）
  return (
    <button
      id="start"
      type="button"
      className="solve-btn start"
      onClick={onStart}
      aria-label="开始求解"
    >
      开始求解
    </button>
  );
}
