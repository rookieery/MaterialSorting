// PieceQtyDialog —— 数量编辑弹窗（US-012）。
//
// 草稿 + 确定模式：打开弹窗后从 qtyStore 读初值进本地草稿（draftQty / draftGlobal），
// 用户编辑仅改草稿；点确定才写 qtyStore；点取消 / 遮罩 / ESC 仅 closeQtyDialog()，
// 草稿丢弃。这避免切 global 瞬间把其它码同 label 置灰后无法回滚的体验问题。
//
// 状态来源拆分：
//   - 显隐目标（label + size）→ uploadStore.qtyDialog（点卡片头 序号(数量) 时写入）
//   - 初值草稿（draftQty / draftGlobal）→ 本组件 useState，open 时初始化、close 时丢弃
//   - 写入 → qtyStore.setPieceGlobal / setPiecePerSize（确定时调）
//
// ESC 监听：dialog 打开（target!==null）时挂 window.keydown、关闭时卸载（无残留）。
//
// 关键约束（与 US-012 / US-011 一致）：
//   - getPieceDisplay 是 qtyStore 消费唯一入口；初值 draftQty = display.qty；
//     draftGlobal 初值 = (mode==='global' && globalSource===size)。
//   - clampQty 是数量值规整入口；用 type=number input 仍要在 blur 时 clamp 兜底（防
//     上下箭头超界 / 字符串粘贴非数字）。
//   - 不引入 CSS 框架；.piece-qty-dialog-overlay / .piece-qty-dialog-modal /
//     .qty-input-group / .qty-switch 全部沿用 style.css 暗背景 + 绿色 #2ea06c 同色系。

import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { clampQty, getPieceDisplay, useQtyStore } from '../../store/qtyStore';
import { useUploadStore } from '../../store/uploadStore';
import { Switch } from './Switch';

/** null 码（通用）的人读文案；与 SizeTabs NULL_SIZE_LABEL 同语义。 */
function sizeLabel(size: number | null): string {
  return size === null ? '通用' : String(size);
}

export function PieceQtyDialog(): JSX.Element | null {
  const target = useUploadStore((s) => s.qtyDialog);
  const closeQtyDialog = useUploadStore((s) => s.closeQtyDialog);

  // 用 key 强制在 target 切换时重建内部子组件 —— 子组件用 useState 初始化草稿，
  // key 变化保证每次 open 都从 store 重新读初值，避免 StrictMode 双 mount / 同 label
  // 二次 open 时草稿残留。
  return (
    <>
      {target !== null && (
        <PieceQtyDialogInner
          key={`${target.label}-${target.size ?? 'null'}`}
          label={target.label}
          size={target.size}
          onClose={closeQtyDialog}
        />
      )}
    </>
  );
}

interface InnerProps {
  label: string;
  size: number | null;
  onClose: () => void;
}

function PieceQtyDialogInner({ label, size, onClose }: InnerProps): JSX.Element {
  const quantities = useQtyStore((s) => s.quantities);
  const setPiecePerSize = useQtyStore((s) => s.setPiecePerSize);
  const setPieceGlobal = useQtyStore((s) => s.setPieceGlobal);

  // 初值：从 qtyStore getPieceDisplay 读
  //   draftQty    = display.qty
  //   draftGlobal = (mode==='global' && globalSource===size)
  // 严格按 US-012 / US-011 口径：用 selector 而非直接读 quantities[label]。
  const initial = getPieceDisplay(quantities, label, size);
  const initialGlobal =
    quantities[label]?.mode === 'global' && quantities[label]?.globalSource === size;

  const [draftQty, setDraftQty] = useState<number>(initial.qty);
  const [draftGlobal, setDraftGlobal] = useState<boolean>(initialGlobal);

  // ESC 监听：组件 mount 时挂、unmount 时卸载（无残留）。
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  function handleDec(): void {
    setDraftQty((q) => clampQty(q - 1));
  }

  function handleInc(): void {
    setDraftQty((q) => clampQty(q + 1));
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>): void {
    // 实时跟随：input.value 是字符串；非数字 Number 得 NaN，clampQty 兜底为 0
    const v = Number(e.target.value);
    setDraftQty(Number.isNaN(v) ? 0 : clampQty(v));
  }

  function handleInputBlur(e: React.FocusEvent<HTMLInputElement>): void {
    // blur 时 clamp 兜底（防上下箭头超界 / 字符串粘贴）
    setDraftQty(clampQty(e.target.value));
  }

  function handleConfirm(): void {
    if (draftGlobal) {
      setPieceGlobal(label, size, draftQty);
    } else {
      setPiecePerSize(label, size, draftQty);
    }
    onClose();
  }

  function handleOverlayMouseDown(e: React.MouseEvent): void {
    // 仅当 mousedown 落在 overlay 自身（不是冒泡上来的子元素）时关闭
    if (e.target === e.currentTarget) onClose();
  }

  return createPortal(
    <div
      className="piece-qty-dialog-overlay"
      onMouseDown={handleOverlayMouseDown}
      data-testid="piece-qty-dialog-overlay"
    >
      <div
        className="piece-qty-dialog-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`裁片 ${label} 码 ${sizeLabel(size)} 数量编辑`}
      >
        <div className="piece-qty-dialog-title">
          裁片 {label} · 码 {sizeLabel(size)}
        </div>

        <div className="qty-input-group">
          <button
            type="button"
            className="qty-step qty-dec"
            onClick={handleDec}
            disabled={draftQty <= 0}
            aria-label="减少数量"
            data-testid="qty-dec"
          >
            −
          </button>
          <input
            type="number"
            className="qty-input"
            min={0}
            max={99}
            step={1}
            value={draftQty}
            onChange={handleInputChange}
            onBlur={handleInputBlur}
            aria-label="数量"
            data-testid="qty-input"
          />
          <button
            type="button"
            className="qty-step qty-inc"
            onClick={handleInc}
            aria-label="增加数量"
            data-testid="qty-inc"
          >
            +
          </button>
        </div>

        <div className="qty-switch">
          <Switch
            checked={draftGlobal}
            onChange={setDraftGlobal}
            labelOff="仅当前尺码"
            labelOn="全部尺码"
            data-testid="qty-switch"
          />
        </div>

        <div className="piece-qty-dialog-actions">
          <button
            type="button"
            className="qty-btn qty-cancel"
            onClick={onClose}
            data-testid="qty-cancel"
          >
            取消
          </button>
          <button
            type="button"
            className="qty-btn qty-confirm"
            onClick={handleConfirm}
            data-testid="qty-confirm"
          >
            确定
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
