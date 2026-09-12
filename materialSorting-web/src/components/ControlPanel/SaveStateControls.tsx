// SaveStateControls —— 主面板「保存当前方案状态（.msn）」区块。
//
// 2026-09-12 状态文件入口改判（用户要求）：保存入口从导出格式下拉第 5 项
// 「状态文件（.msn）」（2026-09-11 状态文件 US-003 落地形态）拆出为本独立区块，
// 位于「编辑排料」与「导出最优方案」之间 —— 纯标题栏 + 单「保存」按钮，
// 不带说明行（用户定案；原下拉选中时的保存范围说明行随之删除）。
//
// 按钮状态与导出按钮严格一致（用户需求：「导出按钮高亮可点击时此按钮也才能
// 高亮可点击」）：
//   - 同公式：disabled = solving || exporting || !hasLastFrame
//     （ExportButtons.hasLastFrame 同源判式：registry 存在推过帧的 run 即可点，
//     含 stopped best-so-far 与策略/极限/状态文件恢复合成 record）；
//   - 同数据源：exporting 即 useExport 的 saveState/exportAs 共享单一防连击旗
//     —— 导出在飞时保存置灰、保存在飞时导出也置灰，双向联动零新增机制。
//
// disabled 双层防御（EditLayoutControls 同站内惯例）：native disabled 属性
// （a11y / 键盘 tab 序列不响应）+ onClick 内 if (disabled) return（合成事件 /
// devtools 删属性旁路）。
//
// 订阅 renderTick（ExportButtons/EditLayoutControls 同款）：lastFrame 是 mutable
// 引用不进 React state，求解 final 到达后靠 useRafThrottle bump 触发本组件
// reconciliation，重算 hasLastFrame。

import type { JSX } from 'react';
import { useAppStore } from '../../store/appStore';
import { runRegistry } from '../../store/runRegistry';

export interface SaveStateControlsProps {
  /** 求解中（保存按钮置灰 —— 与导出按钮一致）。来自 ControlPanel phase==='running' 派生。 */
  solving: boolean;
  /** 导出/保存中（保存按钮置灰，防连击；与导出按钮共用 useExport.exporting 单一旗）。 */
  exporting: boolean;
  /** 点击保存（ControlPanel 接 useExport.saveState —— POST /api/state-save，.msn 下载）。 */
  onSave: () => void;
}

export function SaveStateControls({ solving, exporting, onSave }: SaveStateControlsProps): JSX.Element {
  // 订阅仅为触发 reconciliation（hasLastFrame 从 mutable registry 现读）。
  const renderTick = useAppStore((s) => s.renderTick);
  void renderTick;

  // 与 ExportButtons.hasLastFrame 同源判式：存在推过帧的 run 即可点；
  // 公式同导出按钮（solving || exporting || !hasLastFrame）⇒ 状态严格一致。
  const hasResult = runRegistry.list().some((r) => r.lastFrame !== null);
  const disabled = solving || exporting || !hasResult;

  function handleSave(): void {
    if (disabled) return; // 二层防御（一层 native disabled）
    onSave();
  }

  return (
    <div className="save-state-group" data-tour="save-state-group">
      <div className="field-label">保存当前方案状态（.msn）</div>
      <div className="save-state-btns">
        <button
          type="button"
          className="save-state-btn"
          disabled={disabled}
          onClick={handleSave}
          title={disabled ? '先完成一次求解（或停止保留中间方案）后可保存' : undefined}
          data-testid="save-state-btn"
        >
          保存
        </button>
      </div>
    </div>
  );
}
