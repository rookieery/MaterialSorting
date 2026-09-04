// EditConfirmLayer —— 编辑排料自定义暗色小确认层（US-004）。
//
// 编辑排料两处「弃稿 / 回退」动作的二次确认，同一组件复用（不用 window.confirm ——
// 暗色主题 + 行为可控）：
//   1. 主面板「编辑排料 → 重置」：确认将当前更新后的排料布局重置回初始布局
//      （EditLayoutControls，文案由调用方传入）；
//   2. 编辑弹窗右上 ✕ dirty（working ≠ 已保存布局，editStore.itemsEqual 判定）：
//      「放弃未保存的修改？」确认后弃稿关窗（EditLayoutModal）。
//
// 交互口径（与编辑弹窗同哲学）：只有按钮一条路 —— 不挂 ESC、遮罩点击不动作
// （取消是安全侧动作，但保持「显式点击」一致性）；Portal 到 document.body
// （逃逸 edit-layout-modal 的 overflow:hidden 圆角裁切），z-index 1350 =
// edit-layout(1250) / band-zoom(1300) 之上 —— 确认门活跃期间盖住一切。
// 纯受控组件：显隐由父级条件渲染，自身无 state。

import type { JSX } from 'react';
import { createPortal } from 'react-dom';

export interface EditConfirmLayerProps {
  /** 确认文案（调用方口径：重置 / 放弃修改各自的 PRD 文案）。 */
  message: string;
  /** 确认回调（重置 → editStore.reset()；放弃修改 → 弃稿关窗）。 */
  onConfirm: () => void;
  /** 取消回调（关闭确认层，保持原状）。 */
  onCancel: () => void;
  /** 确认按钮文案（默认「确认」）。 */
  confirmText?: string;
  /** 取消按钮文案（默认「取消」）。 */
  cancelText?: string;
}

export function EditConfirmLayer({
  message,
  onConfirm,
  onCancel,
  confirmText = '确认',
  cancelText = '取消',
}: EditConfirmLayerProps): JSX.Element {
  return createPortal(
    <div className="edit-confirm-overlay" data-testid="edit-confirm-overlay">
      <div
        className="edit-confirm-modal"
        role="alertdialog"
        aria-modal="true"
        aria-label={message}
      >
        <div className="edit-confirm-message" data-testid="edit-confirm-message">
          {message}
        </div>
        <div className="edit-confirm-actions">
          <button
            type="button"
            className="edit-confirm-cancel"
            onClick={onCancel}
            data-testid="edit-confirm-cancel"
          >
            {cancelText}
          </button>
          <button
            type="button"
            className="edit-confirm-ok"
            onClick={onConfirm}
            data-testid="edit-confirm-ok"
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
