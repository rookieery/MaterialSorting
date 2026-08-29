// ExtremeRunButton —— 「极限运行」入口按钮 + Modal 单例挂载点（US-003；范本
// StrategyRunButton —— 范本注释见彼处，此处只记差异）。
//
// 与「高级运行」并排同级（ControlPanel .strategy-entry-row 双列；不进高级运行
// 的 race/se 模式选择 —— 极限参数已按实验结论固化，无可调项）。极限运行中
// （starting/running）入口徽标「运行中」—— useStrategyPoll 关弹窗 15s 低频轮询
// 维持（store = useExtremeStore，端点 /api/extreme/status，与策略族互不重叠 ⇒
// 全应用无双跑轮询）。
//
// 同会话「极限 ↔ 高级」单飞互斥由后端 409 兜底（文案区分对方：「已有进行中的
// 极限运行/策略运行…请先停止/清理」，error 态透传展示）；入口 disabled 与高级
// 运行同口径：solving（主画布 running）|| 未 commit（doc === null）。

import type { JSX } from 'react';
import type { StartContext } from '../../lib/params';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { useExtremeStore } from '../../store/strategyStore';
import { useStrategyPoll } from '../../hooks/useStrategyPoll';
import type { StrategyResult } from '../../types/strategy';
import { ExtremeRunModal } from './ExtremeRunModal';

export interface ExtremeRunButtonProps {
  /** 主画布求解中（入口 disabled + Modal 执行按钮互斥）。 */
  solving: boolean;
  /** handleStart 同源 start 上下文构造器（Modal 执行时现取 —— collectStartContext 单一实现）。 */
  buildStartContext: () => StartContext;
  /** 结果态「应用到主画布」回调（复用 NestingPage.applyStrategyResult 合成 RunRecord；未传 → disabled）。 */
  onApplyExtreme?: (result: StrategyResult) => void;
  /** 入口 disabled（solving || 未 commit，ControlPanel 计算）。 */
  disabled?: boolean;
  /** 置灰原因悬停说明（缺省不渲染）。 */
  title?: string;
}

export function ExtremeRunButton({
  solving,
  buildStartContext,
  onApplyExtreme,
  disabled = false,
  title,
}: ExtremeRunButtonProps): JSX.Element {
  const openModal = useControlPanelStore((s) => s.openModal);
  const modalOpen = useControlPanelStore((s) => s.modal) === 'extreme_run';
  const phase = useExtremeStore((s) => s.phase);
  // 单族单实例轮询闸：开弹窗 2s / 关弹窗 15s（活性态），终态停。
  useStrategyPoll(modalOpen, useExtremeStore);
  const running = phase === 'starting' || phase === 'running';

  return (
    <div className="strategy-wrapper">
      <button
        type="button"
        className="strategy-btn extreme"
        disabled={disabled}
        title={title}
        onClick={() => openModal('extreme_run')}
        data-testid="extreme-btn"
      >
        极限运行：极限利用率长跑
        {running && (
          <span className="strategy-badge" data-testid="extreme-badge">
            运行中
          </span>
        )}
      </button>
      {/* 模态单例：订阅 controlPanelStore 自显隐（与 strategy_run 单例互斥）；Portal 到 document.body */}
      <ExtremeRunModal
        solving={solving}
        buildStartContext={buildStartContext}
        onApplyExtreme={onApplyExtreme}
      />
    </div>
  );
}
