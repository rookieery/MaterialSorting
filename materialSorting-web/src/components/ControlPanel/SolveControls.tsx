// US-028 SolveControls —— 按 phase 渲染的求解按钮组（替代单一 StartButton）。
//
// 两态渲染（phase 由 NestingPage 持有，本组件纯受控）：
//   running              → 「停止」（调 onStop；#stop id，红色警示）
//   idle/stopped/done/   → 「普通运行」（2026-09-14 由「开始求解」改名，与「高级运行 /
//     error                 极限运行」入口文案统一成三级运行族；不再区分「重新开始 /
//                           再次求解」—— 发起求解的语义一致，靠 phase 切换即可识别当前阶段）
//
// 所有非 running 态统一调 onStart（读当前 form）。曾存在 idle→onStart、其余→onRestart
// （重放 lastStartCfgRef 快照）的双路径：phase 一旦离开 idle 永不回归，导致首次求解后
// 用户改任何参数（multi_seed / 码号 / 幅宽 / 数量等）都不生效 —— 已删除快照重放，收敛单一路径。
// id 保留 #start / #restart 区分作 CSS / 测试钩子（视觉同色：均为绿色主操作）。
//
// startDisabled：码号未选时「普通运行」置灰（ControlPanel 据 form.sizes.length===0 计算）。
//   running 态「停止」按钮不受影响（停止总是可用）。
//
// 初始布局 chip 三态（prd-initial-layout US-007，仅非 running 态渲染在按钮下方）：
//   'fresh' =「将基于初始布局运行 ×清除」（×清除 = initialLayoutStore.clear 只清
//             saved，弹窗再保存即恢复）/ 'stale' =「初始布局已失效（参数已变更）」
//             （amber，无清除键 —— 重开弹窗自动重生成覆盖）/ 'none' = 无 chip。
//   附注「仅普通运行生效」恒随 chip 在场（高级/极限运行忽略初始布局 —— HTTP config
//   不带 initial 键，本组件 chip 只是普通运行的增益提示）。
//
// 「导出」按钮不在本组件 —— 由 ExportButtons 独立渲染（受 phase==='running' 禁用）。
// stopped/done/error 态「导出」可用（registry 保留帧时），中间方案提示由 ExportButtons 内 partial flag 渲染。
//
// a11y：每个按钮带 aria-label（原生 button 默认可聚焦，Enter/Space 触发 click）。
// 视觉沿用 style.css 暗色系（不引入 CSS 框架）：#start/#restart 绿、#stop 红。

import type { SolvePhase } from '../../types/solvePhase';

/** 初始布局 chip 三态（ControlPanel 据 saved + isStale(指纹) 派生，本组件纯受控）。 */
export type InitialChipState = 'fresh' | 'stale' | 'none';

export interface SolveControlsProps {
  /** 求解状态机五态（NestingPage 持有；本组件纯受控）。 */
  phase: SolvePhase;
  /** 非 running 态点击「普通运行」（ControlPanel.handleStart 读当前 form，内含码号校验）。 */
  onStart: () => void;
  /** running 态点击「停止」（调 useSolveRun.stop → 后端 terminate → onDone 切 phase）。 */
  onStop: () => void;
  /** 码号未选时「普通运行」置灰（ControlPanel 据 form.sizes 计算）；默认 false。 */
  startDisabled?: boolean;
  /** 初始布局 chip 三态（US-007）；默认 'none'（无 chip，既有渲染逐字节不变）。 */
  initialChip?: InitialChipState;
  /** chip「×清除」回调（fresh 态渲染清除键；ControlPanel 接 initialLayoutStore.clear）。 */
  onClearInitial?: () => void;
}

export function SolveControls({
  phase,
  onStart,
  onStop,
  startDisabled = false,
  initialChip = 'none',
  onClearInitial,
}: SolveControlsProps) {
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

  // idle / stopped / done / error —— 统一「普通运行」文案，统一走 onStart（读当前 form）。
  // id / className 保留区分（#start vs #restart）作 CSS 与测试钩子，视觉同色。
  const isIdle = phase === 'idle';
  return (
    <>
      <button
        id={isIdle ? 'start' : 'restart'}
        type="button"
        className={`solve-btn ${isIdle ? 'start' : 'restart'}`}
        onClick={onStart}
        disabled={startDisabled}
        aria-label="普通运行"
      >
        普通运行
      </button>
      {/* 初始布局 chip（US-007 三态；'none' 不渲染任何节点 —— 既有 DOM 零变化）。 */}
      {initialChip === 'fresh' && (
        <div className="solve-initial-chip" data-testid="initial-chip">
          <span className="solve-initial-chip-text">将基于初始布局运行</span>
          <button
            type="button"
            className="solve-initial-chip-clear"
            aria-label="清除初始布局"
            title="清除已保存的初始布局（普通运行不再附带）"
            onClick={onClearInitial}
            data-testid="initial-chip-clear"
          >
            ×清除
          </button>
        </div>
      )}
      {initialChip === 'stale' && (
        <div
          className="solve-initial-chip stale"
          data-testid="initial-chip-stale"
          title="参数已变更，重新打开「设置初始布局」会自动重新生成"
        >
          初始布局已失效（参数已变更）
        </div>
      )}
      {initialChip !== 'none' && (
        <div className="solve-initial-chip-note" data-testid="initial-chip-note">
          仅普通运行生效
        </div>
      )}
    </>
  );
}
