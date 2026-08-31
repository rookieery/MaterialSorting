// ExportInfoModal —— 「导出 PLT · 唛架信息表格」弹窗（2026-08-31 v3 全 14 字段展示）。
//
// 生产环境 PLT 在排料图外围带 14 字段信息表格（横排竖直堆叠、不占排料区）；
// 6 个手输字段系统里没有，导出 PLT 前在此填写。v3 起弹窗**按最终表格列序展示
// 全部 14 字段**（用户需求：其余字段也展示但不可编辑、顺序 = 最终表格）——
// 8 个自动字段（方案名称/床次旁的利用率/幅宽/料长/套数/每套用料/片数/绘图时间）
// 只读展示成品字符串，手动/自动按服务端返回列序交错（床次..排料师..样板号/备注
// 位置随最终表格重排）。
//
// 数据源 = POST /api/plt-table-preview（mount 时 bestRun 的几何子集，与
// useExport POST /export 同源字段）：列序/格式权威在后端 plt_table._row_texts
// 单一真相源，前端零公式镜像（方案名称系数/demand 多副本计数不在 TS 复刻，
// 后端改列序弹窗自动跟）。**优雅降级**：预览未返回/失败/无解 → 维持 v2 形态
// （6 手输 + 提示行），预览永不阻塞确认导出（导出时后端照算）。绘图时间预览 =
// 请求时刻，最终 PLT 以导出时刻重算（分钟精度通常一致）。
//
// 范本 ExtremeRunModal 的**纯取消型**骨架（v2 起保持）：ESC / 遮罩 / ✕ / 取消 =
// 只关弹窗不导出，「导出 PLT」= 唯一提交路径（生产信息是裁剪车间凭据，误触
// 导出比多点一步贵）。声明式受控 Portal：订阅 controlPanelStore.modal ===
// 'export_info' 自显隐；草稿 mount 时从 localStorage 记忆值初始化（跨导出记住
// 排料师/床次等，lib/exportTable.ts），确认时落盘 + 回调 onConfirm 后关闭。
// 打开入口：ControlPanel.handleExport fmt==='plt' 分流（PNG/DXF 直通不弹窗）。

import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { apiFetch } from '../../lib/api';
import {
  type ExportTableFields,
  type PltPreviewRow,
  loadExportTable,
  saveExportTable,
} from '../../lib/exportTable';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { runRegistry } from '../../store/runRegistry';

export interface ExportInfoModalProps {
  /** 是否导出中（useExport.exporting —— 提交按钮互斥防连击）。 */
  exporting: boolean;
  /** 确认导出：携带手输字段（ControlPanel.handlePltConfirm → exportAs(variant, …, table)）。 */
  onConfirm: (fields: ExportTableFields) => void;
  /** PLT 变体（2026-08-31）：'plt-clean' 毛版只改弹窗文案，字段填写流程与全量版共用
   *  （同一份 14 字段 → 毛版唛架左右两表同内容）。 */
  variant?: 'plt' | 'plt-clean';
}

/** manual 槽位：预览行 snake_case key → 草稿字段（camelCase）。后端新增手输
 * key 且此处未映射 → 该行跳过（导出时后端取默认值，不致崩）。 */
const KEY_TO_FIELD: Partial<Record<string, keyof ExportTableFields>> = {
  bed_no: 'bedNo',
  warp_shrink: 'warpShrink',
  weft_shrink: 'weftShrink',
  planner: 'planner',
  style_no: 'styleNo',
  remark: 'remark',
};

/** 手输槽位渲染元数据（id/label/placeholder 沿用 v2 kebab-case 契约不动）。 */
interface ManualMeta {
  label: string;
  ph: string;
  id: string;
  textarea?: boolean;
}

const MANUAL_META: Record<keyof ExportTableFields, ManualMeta> = {
  bedNo: { label: '床次', ph: '默认 A料', id: 'export-info-bed-no' },
  warpShrink: { label: '经纱缩水', ph: '默认 0.0%', id: 'export-info-warp-shrink' },
  weftShrink: { label: '纬纱缩水', ph: '默认 0.0%', id: 'export-info-weft-shrink' },
  planner: { label: '排料师', ph: '可空', id: 'export-info-planner' },
  styleNo: { label: '样板号', ph: '默认 noname', id: 'export-info-style-no' },
  remark: { label: '备注', ph: '可空', id: 'export-info-remark', textarea: true },
};

export function ExportInfoModal(props: ExportInfoModalProps): JSX.Element | null {
  const modal = useControlPanelStore((s) => s.modal);
  if (modal !== 'export_info') return null;
  return <ExportInfoModalInner key="export-info-modal" {...props} />;
}

function ExportInfoModalInner({
  exporting,
  onConfirm,
  variant = 'plt',
}: ExportInfoModalProps): JSX.Element {
  const closeModal = useControlPanelStore((s) => s.closeModal);

  // 草稿 local state（mount 初始化自 localStorage 记忆值；不进 FormState ——
  // form 在 doc_id 变化时整体重置，生产信息与母版无关）。
  const [fields, setFields] = useState<ExportTableFields>(() => loadExportTable());

  // v3：14 字段预览行（null = 加载中/失败/无解 → v2 降级形态）。失败仅置标记
  // 换提示文案，确认导出不受影响（导出时后端照算）。
  const [previewRows, setPreviewRows] = useState<PltPreviewRow[] | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);

  // mount 一次性取预览：bestRun 几何子集（与 useExport POST /export 同源字段）。
  // 无解不发请求（导出按钮无 lastFrame 本就 disabled，纯防御）。
  useEffect(() => {
    const run = runRegistry.bestRun();
    if (!run?.lastFrame) {
      setPreviewFailed(true);
      return;
    }
    let alive = true;
    apiFetch('/api/plt-table-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gate_mm: run.manifest?.gate_mm ?? 0,
        width_mm: run.lastFrame.width_mm,
        density: run.finalDensity,
        placed: run.lastFrame.placed_items,
      }),
    })
      .then(async (res): Promise<PltPreviewRow[]> => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { rows?: PltPreviewRow[] };
        if (!Array.isArray(data.rows) || data.rows.length === 0) {
          throw new Error('rows 缺失');
        }
        return data.rows;
      })
      .then((rows) => {
        if (alive) setPreviewRows(rows);
      })
      .catch(() => {
        // 网络错 / 非 2xx / 载荷异常 —— 静默降级 v2 形态（不 toast 不阻塞）
        if (alive) setPreviewFailed(true);
      });
    return () => {
      alive = false; // 弹窗先关：丢弃迟到响应
    };
  }, []);

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

  /** 手输槽位输入块（id/data-testid/placeholder 与 v2 逐一保持，kebab-case 契约）。 */
  function renderManualField(field: keyof ExportTableFields): JSX.Element {
    const meta = MANUAL_META[field];
    return (
      <div className="strategy-field" key={field}>
        <label htmlFor={meta.id}>{meta.label}</label>
        {meta.textarea ? (
          <textarea
            id={meta.id}
            className="strategy-textarea"
            data-testid={meta.id}
            rows={2}
            maxLength={60}
            value={fields.remark}
            placeholder={meta.ph}
            onChange={(e) => patch({ remark: e.target.value })}
          />
        ) : (
          <input
            id={meta.id}
            type="text"
            className="strategy-text-input"
            data-testid={meta.id}
            value={fields[field]}
            placeholder={meta.ph}
            onChange={(e) => patch({ [field]: e.target.value } as Partial<ExportTableFields>)}
          />
        )}
      </div>
    );
  }

  /** 自动字段只读行（紧凑单行：label 左 / 成品串右）。 */
  function renderAutoRow(row: PltPreviewRow): JSX.Element {
    return (
      <div className="export-ro-row" key={row.key} data-testid={`export-info-auto-${row.key}`}>
        <span className="export-ro-label">{row.label}</span>
        <span className="export-ro-value">{row.value}</span>
      </div>
    );
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
        aria-label={variant === 'plt-clean' ? '导出 PLT（毛版）唛架信息表格' : '导出 PLT 唛架信息表格'}
        onMouseDown={handleModalMouseDown}
      >
        <div className="strategy-head">
          <span className="strategy-title">
            {variant === 'plt-clean' ? '导出 PLT（毛版）· 唛架信息表格' : '导出 PLT · 唛架信息表格'}
          </span>
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

        {previewRows === null ? (
          // 降级形态（加载中/失败/无解）= v2：6 手输 + 提示行，导出照常
          <>
            {renderManualField('bedNo')}
            {renderManualField('warpShrink')}
            {renderManualField('weftShrink')}
            {renderManualField('planner')}
            {renderManualField('styleNo')}
            {renderManualField('remark')}
            <div className="strategy-hint" data-testid="export-info-auto-hint">
              {previewFailed
                ? '其余字段（方案名称 / 套数 / 利用率 / 幅宽 / 料长 / 每套用料 / 片数 / 绘图时间）'
                  + '导出时由系统自动计算，当前预览不可用'
                : '正在计算其余自动字段（方案名称 / 套数 / 利用率 / 幅宽 / 料长 / 每套用料 / 片数 / 绘图时间）…'}
              {variant === 'plt-clean'
                ? '（毛版在排料图左右两端各附一份同内容表格，不占排料区、不计入用料）'
                : '（表格附在排料图外围，不占排料区、不计入用料）'}
            </div>
          </>
        ) : (
          // 全 14 字段：服务端返回列序（= 最终表格列序）交错渲染；
          // 未知 manual key（后端新字段未映射）跳过，自动字段照常展示
          <>
            {previewRows.map((row) => {
              if (!row.manual) return renderAutoRow(row);
              const field = KEY_TO_FIELD[row.key];
              return field ? renderManualField(field) : null;
            })}
            <div className="strategy-hint">
              {variant === 'plt-clean'
                ? '毛版在排料图左右两端各附一份同内容表格（不占排料区、不计入用料）；'
                  + '裁片只画最外层毛版轮廓与尺码*数量标注；'
                : '信息表格附在排料图外围（不占排料区、不计入用料）；'}
              自动字段在导出时以最新解重算（绘图时间为导出时刻）
            </div>
          </>
        )}

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
            disabled={exporting}
            onClick={handleConfirm}
            title={exporting ? '正在导出…' : undefined}
            data-testid="export-info-confirm"
          >
            {variant === 'plt-clean' ? '导出 PLT（毛版）' : '导出 PLT'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
