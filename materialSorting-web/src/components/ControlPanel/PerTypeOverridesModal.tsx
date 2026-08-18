// PerTypeOverridesModal —— 高级配置：每裁片（g 码）覆盖弹窗（US-018；裁片编号化重构
// US-003 起 V03_PTYPES 固定 10 中文列删除，列集 = /api/ptypes representatives 键
// —— 裁片 g 码，动态随当前母版。2026-08-18 回退 US-004 矩阵化（行=码号 × 列=g 码
// 逐格 d/tol）：重合/旋转是片型工艺属性、与码号无关，按码号细分无业务差异，
// 收敛回 per_type 单级 {g 码: {d, tol}}，与后端 build_instance 同步回单级命中）。
//
// 声明式受控 Portal（参考 PieceZoomModal）：
//   - 订阅 controlPanelStore.modal === 'per_type' 自显隐；null 时不挂 DOM。
//   - Portal 到 document.body（不被 .page overflow/display:none 裁切）。
//   - 关闭交互（AC#10）：确定 / 取消 / ✕ 按钮 / 遮罩 mousedown / ESC。
//
// 表格布局（D10 / AC#3；2026-08-17 编号化 + 全局上限改造）：
//   - thead 列 = 当前母版 g 码并集（/api/ptypes 键 ∪ form.per_type 已配置键），按
//     compareByLabel 数值序（与上传预览 QtyMatrix 列序一致口径）。每列缩略图 64×64 +
//     g 码徽章 —— 复用上传预览 QtyMatrix 的 .qty-label-badge。
//   - tbody 行 = 2 行：重合 input（0–10mm）+ 旋转 input（0–45°）；全局上限不按片型；
//     blur 规整到 [0, max]。
//   - hover / aria 只报 g 码：`${g码}-放大预览`。
//   - 表格 overflow-x:auto（多列窄屏溢出）。reps 未到位（loading / 未 commit / fetch
//     失败）→ 列集退回 values 已配置键（可能为空 → 仅行头，不阻塞）。
//
// 缩略图数据源（D10 / AC#4）：挂载时 fetch GET /api/ptypes（US-020）取 representatives
// （键 = g 码），存本地 state；loading 占位「…」；fetch 失败降级为空 reps（不阻塞）。
// 缩略图用 PiecePreviewSVG compact 模式渲染 representatives[label]，layer-aware（D11）。
//
// 草稿 + 确定模式（AC#5）：打开时从 form.per_type 读初值进本地 draft（已配置键保留，
// 空值预填 '0'/'0'）；fetch 到位的 g 码未配置格渲染空串（= 继承默认 0，placeholder 提示）；
// 编辑仅改 draft；点确定回写 form.per_type + 关闭；取消/遮罩/ESC 仅关 modal、草稿丢弃。
//
// 裁片放大预览（AC#7）：点击 thead 缩略图触发 openPreviewLabel(label)；
// PtypePreviewModal 叠在本模态之上（z-index 更高）；关闭预览时本模态草稿保留。
//
// 关键不变量（AC#10）：两层 modal 各自独立 ESC ——
//   - 本组件 ESC listener 内判 previewLabel===null 才关闭，避免预览打开时双层同时关闭。
//   - PtypePreviewModal 自己的 ESC listener 始终只关 previewLabel。
//
// 不引入 CSS 框架；.per-type-overlay / .per-type-modal / .per-type-table / .ptype-thumb
// 全部沿用 style.css 暗背景 #26282e + #2ea06c 同色系（与 PieceZoomModal 一致）。

import { useEffect, useMemo, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { MAX_OVERLAP_MM, MAX_ROTATION_TOL_DEG } from '../../constants/v03';
import type { PerTypeFormValue } from '../../lib/params';
import { useControlPanelStore } from '../../store/controlPanelStore';
import type { ParsedPiece } from '../../types/parsed';
import type { PtypeRepresentative, PtypesResponse } from '../../types/ptype';
import { PiecePreviewSVG } from '../preview/PiecePreviewSVG';

/** ≤ 字符（U+2264）—— 输入框 placeholder 上限提示。 */
const LE = '≤';

/**
 * g 码比较器（g01<g02<…<g99<g100：先长度再字典序）。g 码两位零填充下
 * 「先长度再字典序」= 数值序（g100 三位自然排后），**勿去零填充**（'g10'<'g9' 字典序
 * 会错）。列序与 QtyMatrix 列头（最小码 pieces 顺序）口径一致。
 */
function compareByLabel(a: string, b: string): number {
  if (a.length !== b.length) return a.length - b.length;
  return a < b ? -1 : a > b ? 1 : 0;
}

/** 把草稿字符串规整到 [0, max]：负值/超限收边；空串保留（= 继承两档，语义同 0）。 */
function clampDraft(v: string, max: number): string {
  const t = v.trim();
  if (t === '') return v;
  const n = parseFloat(t);
  if (Number.isNaN(n)) return v;
  return String(Math.min(Math.max(n, 0), max));
}

/**
 * 把 form.per_type 已配置键展开为 draft（PerTypeFormValue）。
 * 空值（d/tol 全空串）→ 预填 '0'/'0'（统一默认 0）；非空 → 保留用户已填值。
 * reps 到位后新增的 g 码不在 draft（渲染层兜底空串 = 继承默认 0，placeholder 提示）。
 */
function initializeDraft(values: Record<string, PerTypeFormValue>): Record<string, PerTypeFormValue> {
  const draft: Record<string, PerTypeFormValue> = {};
  for (const label of Object.keys(values)) {
    const v = values[label];
    if (v && (v.d.trim() !== '' || v.tol.trim() !== '')) {
      draft[label] = { d: v.d, tol: v.tol };
    } else {
      draft[label] = { d: '0', tol: '0' };
    }
  }
  return draft;
}

/** 把 PtypeRepresentative 扩展为 PiecePreviewSVG 接受的 ParsedPiece 形状（compact 不渲染 label）。 */
function repToPiece(rep: PtypeRepresentative): ParsedPiece {
  return {
    label: '', // compact 模式不渲染 label，空串安全
    polygon: rep.polygon,
    internal_lines: rep.internal_lines ?? [],
    notches: rep.notches ?? [],
    net_polygon: rep.net_polygon ?? [],
    grain_line: rep.grain_line ?? null,
  };
}

export interface PerTypeOverridesModalProps {
  /** 每裁片（g 码）的 d/tol 输入字符串（来自 ControlPanel form.per_type）。 */
  values: Record<string, PerTypeFormValue>;
  /** 确定时回写 ControlPanel form.per_type。 */
  onChange: (next: Record<string, PerTypeFormValue>) => void;
}

export function PerTypeOverridesModal({
  values,
  onChange,
}: PerTypeOverridesModalProps): JSX.Element | null {
  const modal = useControlPanelStore((s) => s.modal);
  const closeModal = useControlPanelStore((s) => s.closeModal);
  const openPreviewLabel = useControlPanelStore((s) => s.openPreviewLabel);

  if (modal !== 'per_type') return null;

  return (
    <PerTypeOverridesModalInner
      key="per-type-modal"
      values={values}
      onChange={onChange}
      onClose={closeModal}
      onOpenPreviewLabel={openPreviewLabel}
    />
  );
}

interface InnerProps {
  values: Record<string, PerTypeFormValue>;
  onChange: (next: Record<string, PerTypeFormValue>) => void;
  onClose: () => void;
  onOpenPreviewLabel: (label: string) => void;
}

function PerTypeOverridesModalInner({
  values,
  onChange,
  onClose,
  onOpenPreviewLabel,
}: InnerProps): JSX.Element {
  // 草稿：mount 时从 values 已配置键初始化。key 强制每次 open 重建（避免残留）。
  const [draft, setDraft] = useState<Record<string, PerTypeFormValue>>(() => initializeDraft(values));

  // 缩略图数据：mount 时 fetch GET /api/ptypes（键 = g 码）；loading / error 三态。
  // fetch 失败降级为 {} → 列集退回 values 已配置键（不阻塞重合/旋转配置，AC#4）。
  const [representatives, setRepresentatives] = useState<Record<string, PtypeRepresentative>>({});
  const [loadingReps, setLoadingReps] = useState<boolean>(true);

  // 列集 = reps 键（当前母版 g 码并集）∪ values 已配置键（fetch 失败时保留已配置项），
  // 按 compareByLabel 数值序。reps 未到位时先渲染 values 键，fetch 成功后扩列。
  const orderedLabels: string[] = useMemo(() => {
    const keys = new Set<string>(Object.keys(representatives));
    for (const k of Object.keys(values)) keys.add(k);
    return Array.from(keys).sort(compareByLabel);
  }, [representatives, values]);

  useEffect(() => {
    let cancelled = false;
    setLoadingReps(true);
    fetch('/api/ptypes')
      .then((r) => r.json() as Promise<PtypesResponse>)
      .then((data) => {
        if (cancelled) return;
        setRepresentatives(data.representatives ?? {});
        setLoadingReps(false);
      })
      .catch(() => {
        if (cancelled) return;
        // 降级：空 representatives，列集退回 values 键（不阻塞重合/旋转配置）
        setRepresentatives({});
        setLoadingReps(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ESC 监听（AC#10）：previewLabel !== null 时由 PtypePreviewModal 处理 ESC（双层独立）。
  // 本 listener 仅在 previewLabel===null 时关 modal，避免双层同时关闭。
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key !== 'Escape') return;
      // 双层 modal：放大预览打开时 ESC 只关预览，不关底层高级配置（AC#10 关键约定）
      if (useControlPanelStore.getState().previewLabel !== null) return;
      e.preventDefault();
      onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  function updateDraft(label: string, key: 'd' | 'tol', v: string): void {
    setDraft((prev) => ({
      ...prev,
      [label]: { d: prev[label]?.d ?? '', tol: prev[label]?.tol ?? '', [key]: v },
    }));
  }

  function handleConfirm(): void {
    onChange(draft);
    onClose();
  }

  function handleOverlayMouseDown(e: React.MouseEvent): void {
    // 仅当 mousedown 落在 overlay 自身（不是冒泡上来的子元素）时关闭
    if (e.target === e.currentTarget) onClose();
  }

  function handleModalMouseDown(e: React.MouseEvent): void {
    // modal 内 mousedown 不冒泡到 overlay 触发关闭
    e.stopPropagation();
  }

  function handleThumbClick(label: string): void {
    onOpenPreviewLabel(label);
  }

  return createPortal(
    <div
      className="per-type-overlay"
      onMouseDown={handleOverlayMouseDown}
      data-testid="per-type-overlay"
    >
      <div
        className="per-type-modal"
        role="dialog"
        aria-modal="true"
        aria-label="高级配置：每裁片覆盖"
        onMouseDown={handleModalMouseDown}
      >
        <div className="per-type-head">
          <span className="per-type-title">高级配置：每裁片覆盖</span>
          <button
            type="button"
            className="per-type-close"
            aria-label="关闭"
            onClick={onClose}
            data-testid="per-type-close"
          >
            ✕
          </button>
        </div>

        <div className="per-type-table-wrap">
          <table className="per-type-table">
            <thead>
              <tr>
                <th className="per-type-rowhead" scope="col">
                  裁片
                </th>
                {orderedLabels.map((label) => {
                  const rep = representatives[label];
                  return (
                    <th key={label} scope="col" className="ptype-col">
                      <button
                        type="button"
                        className="ptype-thumb"
                        onClick={() => handleThumbClick(label)}
                        aria-label={`${label}-放大预览`}
                        title={`${label}-放大预览`}
                        data-testid={`ptype-thumb-${label}`}
                        disabled={!rep}
                      >
                        {rep ? (
                          <PiecePreviewSVG piece={repToPiece(rep)} compact />
                        ) : (
                          <span className="ptype-thumb-placeholder" aria-hidden="true">
                            {loadingReps ? '…' : label.slice(0, 1)}
                          </span>
                        )}
                      </button>
                      {/* g 码徽章与上传预览 QtyMatrix 列头同款同口径（键即 g 码） */}
                      <span className="qty-label-badge">{label}</span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th className="per-type-rowhead" scope="row">
                  重合
                </th>
                {orderedLabels.map((label) => {
                  const v = draft[label] ?? { d: '', tol: '' };
                  return (
                    <td key={label}>
                      <input
                        type="number"
                        min={0}
                        max={MAX_OVERLAP_MM}
                        step={0.5}
                        placeholder={`d${LE}${MAX_OVERLAP_MM}`}
                        value={v.d}
                        onChange={(e) => updateDraft(label, 'd', e.target.value)}
                        onBlur={(e) => updateDraft(label, 'd', clampDraft(e.target.value, MAX_OVERLAP_MM))}
                        data-testid={`d-${label}`}
                        aria-label={`裁片 ${label} 重合`}
                      />
                    </td>
                  );
                })}
              </tr>
              <tr>
                <th className="per-type-rowhead" scope="row">
                  旋转
                </th>
                {orderedLabels.map((label) => {
                  const v = draft[label] ?? { d: '', tol: '' };
                  return (
                    <td key={label}>
                      <input
                        type="number"
                        min={0}
                        max={MAX_ROTATION_TOL_DEG}
                        step={1}
                        placeholder={`t${LE}${MAX_ROTATION_TOL_DEG}`}
                        value={v.tol}
                        onChange={(e) => updateDraft(label, 'tol', e.target.value)}
                        onBlur={(e) => updateDraft(label, 'tol', clampDraft(e.target.value, MAX_ROTATION_TOL_DEG))}
                        data-testid={`tol-${label}`}
                        aria-label={`裁片 ${label} 旋转`}
                      />
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
        </div>

        <div className="per-type-hint dim small">
          重合 0–{MAX_OVERLAP_MM}mm、旋转 0–{MAX_ROTATION_TOL_DEG}°（全局上限）；默认 0 =
          不重合 / 锁布纹线。空值 = 继承（同 0）。
        </div>

        <div className="per-type-actions">
          <button
            type="button"
            className="per-type-btn-cancel"
            onClick={onClose}
            data-testid="per-type-cancel"
          >
            取消
          </button>
          <button
            type="button"
            className="per-type-btn-confirm"
            onClick={handleConfirm}
            data-testid="per-type-confirm"
          >
            确定
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
