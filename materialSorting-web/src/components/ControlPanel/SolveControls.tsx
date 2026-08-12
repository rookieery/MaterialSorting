// US-028 SolveControls —— 按 phase 渲染的求解按钮组（替代单一 StartButton）。
//
// 两态渲染（phase 由 NestingPage 持有，本组件纯受控）：
//   running              → 「停止」（调 onStop；#stop id，红色警示）
//   idle/stopped/done/   → 「开始求解」（文案统一，不再区分「重新开始 / 再次求解」——
//     error                 发起求解的语义一致，靠 phase 切换即可识别当前阶段）
//
// 文案统一后 idle 调 onStart、stopped/done/error 调 onRestart（NestingPage 用 lastStartCfgRef
// 走 handleStart，复用上次参数），但对用户呈现都是「开始求解」。id 保留 #start / #restart 区分
// 作 CSS / 测试钩子（视觉同色：均为绿色主操作）。
//
// startDisabled：码号未选时「开始求解」置灰（ControlPanel 据 form.sizes.length===0 计算）。
//   running 态「停止」按钮不受影响（停止总是可用）。
//
// 「导出」按钮不在本组件 —— 由 ExportButtons 独立渲染（受 phase==='running' 禁用）。
// stopped/done/error 态「导出」可用（registry 保留帧时），中间方案提示由 ExportButtons 内 partial flag 渲染。
//
// a11y：每个按钮带 aria-label（含「求解」语义；原生 button 默认可聚焦，Enter/Space 触发 click）。
// 视觉沿用 style.css 暗色系（不引入 CSS 框架）：#start/#restart 绿、#stop 红。

import type { SolvePhase } from '../../types/solvePhase';

export interface SolveControlsProps {
  /** 求解状态机五态（NestingPage 持有；本组件纯受控）。 */
  phase: SolvePhase;
  /** idle 态点击「开始求解」（ControlPanel.handleStart 内含码号校验）。 */
  onStart: () => void;
  /** running 态点击「停止」（调 useSolveRun.stop → 后端 terminate → onDone 切 phase）。 */
  onStop: () => void;
  /** stopped/done/error 态点击「开始求解」（用 lastStartCfgRef 走 handleStart 复用上次参数）。 */
  onRestart: () => void;
  /** 码号未选时「开始求解」置灰（ControlPanel 据 form.sizes 计算）；默认 false。 */
  startDisabled?: boolean;
}

export function SolveControls({ phase, onStart, onStop, onRestart, startDisabled = false }: SolveControlsProps) {
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

  // idle / stopped / done / error —— 统一「开始求解」文案。
  // idle 调 onStart（读当前 form）；stopped/done/error 调 onRestart（复用 lastStartCfgRef）。
  // id / className 保留区分（#start vs #restart）作 CSS 与测试钩子，视觉同色。
  const isIdle = phase === 'idle';
  return (
    <button
      id={isIdle ? 'start' : 'restart'}
      type="button"
      className={`solve-btn ${isIdle ? 'start' : 'restart'}`}
      onClick={isIdle ? onStart : onRestart}
      disabled={startDisabled}
      aria-label="开始求解"
    >
      开始求解
    </button>
  );
}
