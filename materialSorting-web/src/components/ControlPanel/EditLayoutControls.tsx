// EditLayoutControls —— 主面板「编辑排料」区块（US-004：保存/重置与主界面集成）。
//
// 位置：StatusLine 与 ExportButtons 之间（「导出最优方案」上方）—— 编辑（人工微调）
// 与导出同属「拿到解之后」的动作分组，紧邻排布引导「先编辑后导出」。
//
// 激活口径与导出按钮一致（ExportButtons.hasLastFrame 同款）：registry 存在 lastFrame
// 的 run（含 stopped best-so-far 与策略/极限合成 record —— 均是 lastFrame 非空的
// RunRecord，零改动命中）且 phase !== 'running'。三层 disabled 防御同站内惯例
// （TabBar setTab guard 同款）：
//   1. native disabled 属性（a11y / 键盘 tab 序列不响应）；
//   2. onClick 内 if (disabled) return（合成事件 / devtools 删属性旁路）；
//   3. store 动作自守卫 —— open 无 lastFrame 清态返回 false；reset 校验 run 仍在
//      registry（重解 clear 后旧引用拒绝）且 baseline 在案，幂等 false 不炸。
//
// 「编辑」→ controlPanelStore.openModal('edit_layout')（EditLayoutModal 受控自显）。
// 「重置」= 自定义暗色 confirm（EditConfirmLayer 同组件，与弹窗 ✕ dirty 确认复用）
// → 确认后 editStore.reset()：恢复 open 时刻快照的基线全套（placed / width /
// density / viewBoxMaxW）+ bumpRenderTick 主视图即时重绘。无编辑会话（baseline
// null —— 刷新后未开过弹窗）/ 陈旧 run → reset 返回 false 幂等无操作。
//
// 订阅 renderTick（ExportButtons 同款）：lastFrame 是 mutable 引用不进 React state，
// 求解 final 到达后靠 bump 触发本组件 reconciliation 重算 hasResult。

import { useState } from 'react';
import type { JSX } from 'react';
import { EditConfirmLayer } from '../edit/EditConfirmLayer';
import { useAppStore } from '../../store/appStore';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { useEditStore } from '../../store/editStore';
import { runRegistry } from '../../store/runRegistry';
import type { SolvePhase } from '../../types/solvePhase';

export interface EditLayoutControlsProps {
  /** 求解状态机五态（running 态置灰 —— 与导出按钮一致）。 */
  phase: SolvePhase;
}

/** 重置确认文案（PRD US-004 原文）。 */
const RESET_CONFIRM_MESSAGE = '确认将当前更新后的排料布局重置回初始布局';

export function EditLayoutControls({ phase }: EditLayoutControlsProps): JSX.Element {
  const openModal = useControlPanelStore((s) => s.openModal);
  // 订阅仅为触发 reconciliation（hasLastFrame 从 mutable registry 现读）。
  const renderTick = useAppStore((s) => s.renderTick);
  void renderTick;

  const [confirmReset, setConfirmReset] = useState(false);

  // 与 ExportButtons.hasLastFrame 同源判式：存在推过帧的 run 即可点（含 stopped
  // best-so-far 与策略/极限合成 record）；running 态置灰。
  const hasResult = runRegistry.list().some((r) => r.lastFrame !== null);
  const disabled = phase === 'running' || !hasResult;

  function handleEdit(): void {
    if (disabled) return; // 二层防御（一层 native disabled；三层 store open 自守卫）
    openModal('edit_layout');
  }

  function handleResetClick(): void {
    if (disabled) return; // 同上三层防御
    setConfirmReset(true);
  }

  function handleResetConfirm(): void {
    setConfirmReset(false);
    // 三层防御落点：stale run / baseline 缺席 → false 幂等（主视图不动）。
    useEditStore.getState().reset();
  }

  return (
    <div className="edit-controls" data-tour="edit-controls">
      <div className="field-label">编辑排料</div>
      <div className="edit-controls-btns">
        <button
          type="button"
          className="edit-controls-btn"
          disabled={disabled}
          onClick={handleEdit}
          title={disabled ? '先完成一次求解（或停止保留中间方案）后可编辑' : undefined}
          data-testid="edit-controls-edit"
        >
          编辑
        </button>
        <button
          type="button"
          className="edit-controls-btn edit-controls-btn--reset"
          disabled={disabled}
          onClick={handleResetClick}
          title={disabled ? '先完成一次求解（或停止保留中间方案）后可重置' : undefined}
          data-testid="edit-controls-reset"
        >
          重置
        </button>
      </div>
      {confirmReset && (
        <EditConfirmLayer
          message={RESET_CONFIRM_MESSAGE}
          onConfirm={handleResetConfirm}
          onCancel={() => setConfirmReset(false)}
        />
      )}
    </div>
  );
}
