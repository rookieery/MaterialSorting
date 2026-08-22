// StrategyRunButton —— 「高级运行」入口按钮 + Modal 单例挂载点（US-005；范本
// PerTypeOverrides.tsx）。
//
// 入口规则：
//   - disabled = solving（主画布 running —— 前端互斥防 CPU 竞争扭曲 race 门时刻
//     判据）|| 未 commit（doc === null，无排料数据可跑）。
//   - 策略运行中（starting/running）入口徽标「运行中」—— 关着弹窗也可见
//     （useStrategyPoll 关弹窗 15s 低频轮询维持）。
//
// useStrategyPoll 挂在本组件（常驻单实例）：open = 弹窗是否打开（订阅
// controlPanelStore.modal 派生）—— StrategyRunModal 不再自挂，避免双重轮询。
// StrategyRunModal 订阅 controlPanelStore.modal 自显隐（声明式受控 Portal）。

import type { JSX } from 'react';
import type { StartContext } from '../../lib/params';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { useStrategyStore } from '../../store/strategyStore';
import { useStrategyPoll } from '../../hooks/useStrategyPoll';
import type { StrategyResult } from '../../types/strategy';
import { StrategyRunModal } from './StrategyRunModal';

export interface StrategyRunButtonProps {
  /** 主画布求解中（入口 disabled + Modal 执行按钮互斥）。 */
  solving: boolean;
  /** handleStart 同源 start 上下文构造器（Modal 执行时现取 —— 数量矩阵编辑后即时生效）。 */
  buildStartContext: () => StartContext;
  /** US-006 应用到主画布回调（未传 → 应用按钮 disabled）。 */
  onApplyStrategy?: (result: StrategyResult) => void;
  /** 入口 disabled（solving || 未 commit，ControlPanel 计算；band 已不互斥）。 */
  disabled?: boolean;
  /**
   * 置灰原因悬停说明（缺省不渲染 title —— solving / 未 commit 的既有置灰不加
   * 说明；band 开启互斥的 title 已随 2026-08-22 解除互斥移除）。
   */
  title?: string;
}

export function StrategyRunButton({
  solving,
  buildStartContext,
  onApplyStrategy,
  disabled = false,
  title,
}: StrategyRunButtonProps): JSX.Element {
  const openModal = useControlPanelStore((s) => s.openModal);
  const modalOpen = useControlPanelStore((s) => s.modal) === 'strategy_run';
  const phase = useStrategyStore((s) => s.phase);
  // 单实例轮询闸：开弹窗 2s / 关弹窗 15s（活性态），终态停。
  useStrategyPoll(modalOpen);
  const running = phase === 'starting' || phase === 'running';

  return (
    <div className="strategy-wrapper">
      <button
        type="button"
        className="strategy-btn"
        disabled={disabled}
        title={title}
        onClick={() => openModal('strategy_run')}
        data-testid="strategy-btn"
      >
        高级运行：长时策略排料
        {running && (
          <span className="strategy-badge" data-testid="strategy-badge">
            运行中
          </span>
        )}
      </button>
      {/* 模态单例：订阅 controlPanelStore 自显隐；Portal 到 document.body */}
      <StrategyRunModal
        solving={solving}
        buildStartContext={buildStartContext}
        onApplyStrategy={onApplyStrategy}
      />
    </div>
  );
}
