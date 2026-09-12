// FileNameModal —— 「文件名」确认弹窗（2026-09-12 导出文件名需求 1）。
//
// 保存（.msn）与导出 DXF/PNG（无自有弹窗的直通格式）点击后先经本弹窗：
// 标题「文件名」+ 单输入框（预填当前合成默认名，defaultExportFilename /
// defaultStateFilename 镜像后端合成式）+ 底部 取消/确认。**输入与预填均为名称
// 主体、不带扩展名**（2026-09-12 用户定案：格式已知、后缀无需用户经手）——
// 确认后以 save_as 回传，后端清洗时按格式自动补正确后缀。
//
// 骨板对齐 ExportInfoModal 的纯取消型惯例：ESC / 遮罩 / ✕ / 取消 = 只关不导
// （onCancel 清 pending；ControlPanel 条件渲染本组件，不进 controlPanelStore ——
// 打开时刻面板被遮罩挡住，不可能与其他 store 弹窗共存）。Enter = 确认（单输入
// 框弹窗的键盘期望）；输入 trim 后为空 → 确认置灰（不静默回退默认名）。
//
// PLT / PLT 毛版不走本弹窗（需求 2）：文件名输入区嵌在 ExportInfoModal 顶部，
// 取消/确认共用该弹窗按钮。

import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';

export interface FileNameModalProps {
  /** 弹窗预填默认名（名称主体，无扩展名；ControlPanel 在打开时刻计算）。 */
  defaultName: string;
  /** 导出/保存中（确认按钮置灰防连击，useExport.exporting 单一旗）。 */
  exporting: boolean;
  /** 确认（name = trim 后输入值，非空调用方保证 —— 按钮空名已置灰兜底）。 */
  onConfirm: (name: string) => void;
  /** 取消（含 ESC / 遮罩 / ✕ —— 只关不导）。 */
  onCancel: () => void;
}

export function FileNameModal({
  defaultName,
  exporting,
  onConfirm,
  onCancel,
}: FileNameModalProps): JSX.Element {
  // 草稿 local state：mount 初始化自 defaultName（ControlPanel 条件渲染 →
  // 每次打开都是新 mount，重开弹窗重新预填；编辑中不因父级重渲染被覆盖）。
  const [name, setName] = useState(defaultName);
  const trimmed = name.trim();

  // ESC 关闭（仅关弹窗，不导出；ExportInfoModal 同款）。
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      onCancel();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);

  /** 唯一提交路径（按钮点击 / 输入框 Enter 共用；空名/导出中静默不触发）。 */
  function handleConfirm(): void {
    if (exporting || trimmed === '') return;
    onConfirm(trimmed);
  }

  function handleOverlayMouseDown(e: React.MouseEvent): void {
    if (e.target === e.currentTarget) onCancel();
  }

  function handleModalMouseDown(e: React.MouseEvent): void {
    e.stopPropagation();
  }

  return createPortal(
    <div
      className="strategy-overlay"
      onMouseDown={handleOverlayMouseDown}
      data-testid="save-name-overlay"
    >
      <div
        className="strategy-modal"
        role="dialog"
        aria-modal="true"
        aria-label="文件名"
        onMouseDown={handleModalMouseDown}
      >
        <div className="strategy-head">
          <span className="strategy-title">文件名</span>
          <button
            type="button"
            className="strategy-close"
            aria-label="关闭"
            onClick={onCancel}
            data-testid="save-name-close"
          >
            ✕
          </button>
        </div>

        <div className="strategy-field">
          <input
            id="save-name-input"
            type="text"
            className="strategy-text-input"
            data-testid="save-name-input"
            value={name}
            placeholder="输入导出文件名"
            spellCheck={false}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleConfirm();
              }
            }}
          />
        </div>
        <div className="strategy-hint">留空不可确认。</div>

        <div className="strategy-actions">
          <button
            type="button"
            className="strategy-btn-again"
            onClick={onCancel}
            data-testid="save-name-cancel"
          >
            取消
          </button>
          <button
            type="button"
            className="strategy-btn-exec"
            disabled={exporting || trimmed === ''}
            onClick={handleConfirm}
            title={exporting ? '正在导出…' : undefined}
            data-testid="save-name-confirm"
          >
            确认
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
