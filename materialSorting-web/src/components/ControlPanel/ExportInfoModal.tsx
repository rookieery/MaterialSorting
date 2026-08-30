// ExportInfoModal —— 「导出 PLT · 唛架信息表格」填写弹窗（2026-08-30 v2 重写）。
//
// 生产环境 PLT 在排料图外围带 14 字段信息表格（横排竖直堆叠、不占排料区）；
// 6 个手输字段系统里没有，导出 PLT 前在此填写（其余 8 个后端自动算 —— 方案名称/
// 套数/利用率/幅宽/料长/每套用料/片数/绘图时间）。范本 ExtremeRunModal 的
// **纯取消型**骨架：ESC / 遮罩 / ✕ / 取消 = 只关弹窗不导出，「导出 PLT」=
// 唯一提交路径（生产信息是裁剪车间凭据，误触导出比多点一步贵）。
//
// 声明式受控 Portal：订阅 controlPanelStore.modal === 'export_info' 自显隐
// （与其他弹窗单例互斥）；草稿 mount 时从 localStorage 记忆值初始化（跨导出
// 记住排料师/床次等，lib/exportTable.ts），确认时落盘 + 回调 onConfirm 后关闭。
// 打开入口：ControlPanel.handleExport fmt==='plt' 分流（PNG/DXF 直通不弹窗）。
// v2 全字段自由字符串无校验（默认 A料/0.0%/0.0%/空/noname/空）。

import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import {
  type ExportTableFields,
  loadExportTable,
  saveExportTable,
} from '../../lib/exportTable';
import { useControlPanelStore } from '../../store/controlPanelStore';

export interface ExportInfoModalProps {
  /** 是否导出中（useExport.exporting —— 提交按钮互斥防连击）。 */
  exporting: boolean;
  /** 确认导出：携带手输字段（ControlPanel.handlePltConfirm → exportAs('plt', …, table)）。 */
  onConfirm: (fields: ExportTableFields) => void;
}

export function ExportInfoModal(props: ExportInfoModalProps): JSX.Element | null {
  const modal = useControlPanelStore((s) => s.modal);
  if (modal !== 'export_info') return null;
  return <ExportInfoModalInner key="export-info-modal" {...props} />;
}

function ExportInfoModalInner({ exporting, onConfirm }: ExportInfoModalProps): JSX.Element {
  const closeModal = useControlPanelStore((s) => s.closeModal);

  // 草稿 local state（mount 初始化自 localStorage 记忆值；不进 FormState ——
  // form 在 doc_id 变化时整体重置，生产信息与母版无关）。
  const [fields, setFields] = useState<ExportTableFields>(() => loadExportTable());

  // ESC 关闭（仅关弹窗，不导出）。
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      closeModal();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [closeModal]);

  function patch(p: Partial<ExportTableFields>): void {
    setFields((prev) => ({ ...prev, ...p }));
  }

  /** 唯一提交路径：落盘记忆 + 回调导出 + 关闭。 */
  function handleConfirm(): void {
    if (exporting) return; // 按钮已置灰，兜底
    saveExportTable(fields);
    onConfirm(fields);
    closeModal();
  }

  function handleOverlayMouseDown(e: React.MouseEvent): void {
    if (e.target === e.currentTarget) closeModal();
  }

  function handleModalMouseDown(e: React.MouseEvent): void {
    e.stopPropagation();
  }

  return createPortal(
    <div
      className="strategy-overlay"
      onMouseDown={handleOverlayMouseDown}
      data-testid="export-info-overlay"
    >
      <div
        className="strategy-modal"
        role="dialog"
        aria-modal="true"
        aria-label="导出 PLT 唛架信息表格"
        onMouseDown={handleModalMouseDown}
      >
        <div className="strategy-head">
          <span className="strategy-title">导出 PLT · 唛架信息表格</span>
          <button
            type="button"
            className="strategy-close"
            aria-label="关闭"
            onClick={closeModal}
            data-testid="export-info-close"
          >
            ✕
          </button>
        </div>

        <div className="strategy-field">
          <label htmlFor="export-info-bed-no">床次</label>
          <input
            id="export-info-bed-no"
            type="text"
            className="strategy-text-input"
            data-testid="export-info-bed-no"
            value={fields.bedNo}
            placeholder="默认 A料"
            onChange={(e) => patch({ bedNo: e.target.value })}
          />
        </div>
        <div className="strategy-field">
          <label htmlFor="export-info-warp-shrink">经纱缩水</label>
          <input
            id="export-info-warp-shrink"
            type="text"
            className="strategy-text-input"
            data-testid="export-info-warp-shrink"
            value={fields.warpShrink}
            placeholder="默认 0.0%"
            onChange={(e) => patch({ warpShrink: e.target.value })}
          />
        </div>
        <div className="strategy-field">
          <label htmlFor="export-info-weft-shrink">纬纱缩水</label>
          <input
            id="export-info-weft-shrink"
            type="text"
            className="strategy-text-input"
            data-testid="export-info-weft-shrink"
            value={fields.weftShrink}
            placeholder="默认 0.0%"
            onChange={(e) => patch({ weftShrink: e.target.value })}
          />
        </div>
        <div className="strategy-field">
          <label htmlFor="export-info-planner">排料师</label>
          <input
            id="export-info-planner"
            type="text"
            className="strategy-text-input"
            data-testid="export-info-planner"
            value={fields.planner}
            placeholder="可空"
            onChange={(e) => patch({ planner: e.target.value })}
          />
        </div>
        <div className="strategy-field">
          <label htmlFor="export-info-style-no">样板号</label>
          <input
            id="export-info-style-no"
            type="text"
            className="strategy-text-input"
            data-testid="export-info-style-no"
            value={fields.styleNo}
            placeholder="默认 noname"
            onChange={(e) => patch({ styleNo: e.target.value })}
          />
        </div>
        <div className="strategy-field">
          <label htmlFor="export-info-remark">备注</label>
          <textarea
            id="export-info-remark"
            className="strategy-textarea"
            data-testid="export-info-remark"
            rows={2}
            maxLength={60}
            value={fields.remark}
            placeholder="可空"
            onChange={(e) => patch({ remark: e.target.value })}
          />
        </div>

        <div className="strategy-hint" data-testid="export-info-auto-hint">
          其余字段系统自动计算：方案名称 / 套数 / 利用率 / 幅宽 / 料长 / 每套用料 /
          片数 / 绘图时间（表格附在排料图外围，不占排料区、不计入用料）
        </div>

        <div className="strategy-actions">
          <button
            type="button"
            className="strategy-btn-again"
            onClick={closeModal}
            data-testid="export-info-cancel"
          >
            取消
          </button>
          <button
            type="button"
            className="strategy-btn-exec"
            data-testid="export-info-confirm"
            disabled={exporting}
            onClick={handleConfirm}
            title={exporting ? '正在导出…' : undefined}
          >
            导出 PLT
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
