// PerTypeOverridesModal —— 高级配置：每裁片（g 码 × 码号）覆盖矩阵弹窗。
//
// 演化：US-018 每片型 10 中文列 → US-003 label 键切换（g 码动态列、2 行 d/tol）→
// US-004 矩阵化：行 = 参与排料码号、列 = g 码并集、格 = (g 码, 码号) d/tol 双输入
// —— 与上传预览 QtyMatrix 同构（复用其交互范式与样式：.qty-label-badge 徽章 /
// .qty-rowfill-btn「≡」整列设值 / .qty-fill-* 弹层），per_type 键随动两级嵌套
// {label: {sizeKey: {d, tol}}}（lib/params PerTypeFormMap）。
//
// 声明式受控 Portal（参考 PieceZoomModal）：
//   - 订阅 controlPanelStore.modal === 'per_type' 自显隐；null 时不挂 DOM。
//   - Portal 到 document.body（不被 .page overflow/display:none 裁切）。
//   - 关闭交互：确定 / 取消 / ✕ 按钮 / 遮罩 mousedown / ESC。
//
// 矩阵布局：
//   - 列（thead）= /api/ptypes representatives 键（当前母版 g 码并集）∪ form.per_type
//     已配置键（fetch 失败时保留已配置项），按 compareByLabel 数值序（与 QtyMatrix
//     列序同口径）。列头 = 缩略图（点击 openPreviewLabel 放大预览，hover/aria 只报
//     g 码）+ g 码徽章 +「≡」整列设值（QtyMatrix 同款范式）。
//   - 行（tbody）= uploadStore.doc.sizes（后端已升序、null 殿后）；doc=null（未解析
//     母版）→ fallback SIZES（与 SizePicker chip 同源，保后端开发模式可用）。已配置
//     per_type 中出现、但不在行集的 sizeKey 追加为行（旧配置保持可见可改，不静默丢）。
//   - 格 = d / tol 两个小输入（空 = 继承全局默认 0/0，placeholder 提示）；blur 规整
//     到 [0, max]（全局上限 10mm / 45°，不按片型）。doc 中该 g 码无此码号的组合渲染
//     disabled「—」（QtyMatrix 缺片格同口径）；label 完全不在 doc 时不判缺 ——
//     parse 与 commit 数据可能暂时不同步，不阻塞配置（后端命不中为 no-op）。
//
// 缩略图数据源：挂载时 fetch GET /api/ptypes 取 representatives（键 = g 码），存本地
// state；loading 占位「…」；fetch 失败降级为空 reps（列集退回已配置键，不阻塞）。
// 缩略图用 PiecePreviewSVG compact 模式渲染，layer-aware。
//
// 草稿 + 确定模式：打开时把 form.per_type 深拷贝进本地 draft（矩阵化后不再预填 '0' ——
// 空串 = 继承默认，语义与格内 placeholder 一致）；编辑/整列设值只改 draft；点确定把
// draft 剔除双侧全空格子后回写 form.per_type + 关闭；取消/遮罩/ESC 仅关 modal、草稿丢弃。
//
// 整列设值（≡）：点列头「≡」→ 居中弹层输入统一 d/tol → 应用写该列全部行（draft 级）；
// 弹层复用 QtyMatrix 的 .qty-fill-* 样式段；ESC/遮罩/取消只关弹层不关本 modal。
//
// 裁片放大预览：点击 thead 缩略图触发 openPreviewLabel(label)；PtypePreviewModal 叠在
// 本模态之上（z-index 更高）；关闭预览时本模态草稿保留。
//
// 关键不变量：各层 modal 独立 ESC ——
//   - 本组件 ESC listener 内判 previewLabel===null 且整列设值弹层未开才关闭。
//   - PtypePreviewModal 自己的 ESC listener 始终只关 previewLabel。
//
// 不引入 CSS 框架；.per-type-overlay / .per-type-modal / .per-type-table / .ptype-thumb
// 沿用 style.css 暗背景 #26282e + #2ea06c 同色系；矩阵格双输入 / 缺片格样式见
// .per-type-cell 段。

import { useEffect, useMemo, useRef, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { MAX_OVERLAP_MM, MAX_ROTATION_TOL_DEG } from '../../constants/v03';
import { SIZES } from '../../constants/sizes';
import { perTypeSizeKey, type PerTypeFormMap, type PerTypeFormValue } from '../../lib/params';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { useUploadStore } from '../../store/uploadStore';
import type { ParsedPiece } from '../../types/parsed';
import type { PtypeRepresentative, PtypesResponse } from '../../types/ptype';
import { PiecePreviewSVG } from '../preview/PiecePreviewSVG';

/** ≤ 字符（U+2264）—— 输入框 placeholder 上限提示。 */
const LE = '≤';

/** null 码（通用）的人读文案；与 SizePicker / QtyMatrix 同语义。 */
function sizeLabel(size: number | null): string {
  return size === null ? '通用' : String(size);
}

/**
 * g 码比较器（g01<g02<…<g99<g100：先长度再字典序）。g 码两位零填充下
 * 「先长度再字典序」= 数值序（g100 三位自然排后），**勿去零填充**（'g10'<'g9' 字典序
 * 会错）。列序与 QtyMatrix 列头口径一致。
 */
function compareByLabel(a: string, b: string): number {
  if (a.length !== b.length) return a.length - b.length;
  return a < b ? -1 : a > b ? 1 : 0;
}

/** 把草稿字符串规整到 [0, max]：负值/超限收边；空串保留（= 继承默认，语义同 0）。 */
function clampDraft(v: string, max: number): string {
  const t = v.trim();
  if (t === '') return v;
  const n = parseFloat(t);
  if (Number.isNaN(n)) return v;
  return String(Math.min(Math.max(n, 0), max));
}

/** 把 form.per_type 深拷贝为 draft（不预填：空串 = 继承默认 0/0，与格内 placeholder 一致）。 */
function initializeDraft(values: PerTypeFormMap): PerTypeFormMap {
  const draft: PerTypeFormMap = {};
  for (const label of Object.keys(values)) {
    const sizeMap = values[label];
    if (!sizeMap) continue;
    const copy: Record<string, PerTypeFormValue> = {};
    for (const sk of Object.keys(sizeMap)) {
      const v = sizeMap[sk];
      if (v) copy[sk] = { d: v.d, tol: v.tol };
    }
    draft[label] = copy;
  }
  return draft;
}

/** 确定回写前剔除双侧全空的 (label, sizeKey) 格子（与 collectParams 空串剔除口径一致）。 */
function pruneDraft(draft: PerTypeFormMap): PerTypeFormMap {
  const out: PerTypeFormMap = {};
  for (const label of Object.keys(draft)) {
    const sizeMap = draft[label];
    if (!sizeMap) continue;
    const kept: Record<string, PerTypeFormValue> = {};
    for (const sk of Object.keys(sizeMap)) {
      const v = sizeMap[sk];
      if (v && (v.d.trim() !== '' || v.tol.trim() !== '')) kept[sk] = { d: v.d, tol: v.tol };
    }
    if (Object.keys(kept).length > 0) out[label] = kept;
  }
  return out;
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
  /** 每 (g 码, 码号) 的 d/tol 输入字符串（来自 ControlPanel form.per_type，两级嵌套）。 */
  values: PerTypeFormMap;
  /** 确定时回写 ControlPanel form.per_type（已剔除全空格子）。 */
  onChange: (next: PerTypeFormMap) => void;
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
  values: PerTypeFormMap;
  onChange: (next: PerTypeFormMap) => void;
  onClose: () => void;
  onOpenPreviewLabel: (label: string) => void;
}

function PerTypeOverridesModalInner({
  values,
  onChange,
  onClose,
  onOpenPreviewLabel,
}: InnerProps): JSX.Element {
  // 草稿：mount 时深拷贝 values。key 强制每次 open 重建（避免残留）。
  const [draft, setDraft] = useState<PerTypeFormMap>(() => initializeDraft(values));

  // 缩略图数据：mount 时 fetch GET /api/ptypes（键 = g 码）；loading / error 三态。
  // fetch 失败降级为 {} → 列集退回 values 已配置键（不阻塞 d/tol 配置）。
  const [representatives, setRepresentatives] = useState<Record<string, PtypeRepresentative>>({});
  const [loadingReps, setLoadingReps] = useState<boolean>(true);

  // 整列设值弹层：目标列 + fixed 定位中心点（一次至多一个；null = 关）。
  const [fill, setFill] = useState<{ label: string; x: number; y: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // 行集 = doc.sizes（升序 null 殿后）∪ values 已配置 sizeKey（追加，保旧配置可见）；
  // doc=null → SIZES fallback（与 SizePicker chip 同源，保后端开发模式可用）。
  const doc = useUploadStore((s) => s.doc);
  const rows: (number | null)[] = useMemo(() => {
    const base: (number | null)[] = doc ? doc.sizes.map((s) => s.size) : [...SIZES];
    const seen = new Set(base.map(perTypeSizeKey));
    const out = [...base];
    for (const label of Object.keys(values)) {
      for (const sk of Object.keys(values[label] ?? {})) {
        if (!seen.has(sk)) {
          seen.add(sk);
          out.push(sk === 'null' ? null : Number(sk));
        }
      }
    }
    return out;
  }, [doc, values]);

  // 列集 = reps 键（当前母版 g 码并集）∪ values 已配置键（fetch 失败时保留已配置项），
  // 按 compareByLabel 数值序。reps 未到位时先渲染 values 键，fetch 成功后扩列。
  const orderedLabels: string[] = useMemo(() => {
    const keys = new Set<string>(Object.keys(representatives));
    for (const k of Object.keys(values)) keys.add(k);
    return Array.from(keys).sort(compareByLabel);
  }, [representatives, values]);

  // 缺片判定（QtyMatrix 同口径）：label 在 doc 中存在（至少一码有它）但该码没有 →
  // disabled「—」。label 完全不在 doc（parse/commit 暂不同步、或旧配置键）→ 不判缺，
  // 保持可配（后端命不中为 no-op，不阻塞）。
  const labelsInDoc = useMemo(() => {
    const m = new Map<string, Set<string>>();
    if (!doc) return m;
    for (const s of doc.sizes) {
      const sk = perTypeSizeKey(s.size);
      for (const p of s.pieces) {
        let set = m.get(p.label);
        if (!set) m.set(p.label, (set = new Set()));
        set.add(sk);
      }
    }
    return m;
  }, [doc]);

  function cellMissing(label: string, sk: string): boolean {
    const inDoc = labelsInDoc.get(label);
    if (!inDoc) return false;
    return !inDoc.has(sk);
  }

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

  // ESC 监听：放大预览（previewLabel）与整列设值弹层打开时让位（各层独立 ESC）；
  // 本 listener 仅在两者都关闭时关 modal，避免多层同时关闭。
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key !== 'Escape') return;
      // 双层 modal：放大预览打开时 ESC 只关预览，不关底层高级配置（关键约定）
      if (useControlPanelStore.getState().previewLabel !== null) return;
      if (fill !== null) return; // 整列设值弹层自己处理 ESC
      e.preventDefault();
      onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, fill]);

  function updateDraftCell(label: string, sk: string, key: 'd' | 'tol', v: string): void {
    setDraft((prev) => {
      const sizeMap = { ...(prev[label] ?? {}) };
      const old = sizeMap[sk] ?? { d: '', tol: '' };
      sizeMap[sk] = { ...old, [key]: v };
      return { ...prev, [label]: sizeMap };
    });
  }

  /** 整列设值应用：写该列全部行（draft 级；留空一侧 = 该侧整列继承默认）。
   *  QtyMatrix「不给缺片码造 phantom 键」同款：missing 行不写（doc 缺席判定时全行写）。 */
  function applyColumnFill(label: string, d: string, tol: string): void {
    setDraft((prev) => {
      const sizeMap = { ...(prev[label] ?? {}) };
      for (const size of rows) {
        const sk = perTypeSizeKey(size);
        if (cellMissing(label, sk)) continue;
        sizeMap[sk] = { d, tol };
      }
      return { ...prev, [label]: sizeMap };
    });
    setFill(null);
  }

  function handleConfirm(): void {
    onChange(pruneDraft(draft));
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

  /** 打开整列设值弹层：定位中心 = 表格容器可视区中心（fixed 定位，QtyMatrix 同款）。 */
  function openFill(label: string): void {
    if (fill?.label === label) {
      setFill(null);
      return;
    }
    const rect = wrapRef.current?.getBoundingClientRect();
    setFill({
      label,
      x: rect ? rect.left + rect.width / 2 : 0,
      y: rect ? rect.top + rect.height / 2 : 0,
    });
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

        <div className="per-type-table-wrap" ref={wrapRef}>
          <table className="per-type-table">
            <thead>
              <tr>
                <th className="per-type-rowhead" scope="col">
                  码号
                </th>
                {orderedLabels.map((label) => {
                  const rep = representatives[label];
                  return (
                    <th key={label} scope="col" className="ptype-col">
                      <button
                        type="button"
                        className="ptype-thumb"
                        onClick={() => onOpenPreviewLabel(label)}
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
                      <div className="qty-colhead-meta">
                        {/* g 码徽章与上传预览 QtyMatrix 列头同款同口径（键即 g 码） */}
                        <span className="qty-label-badge">{label}</span>
                        {/* 整列设值 icon（QtyMatrix 同款 .qty-rowfill-btn）：点击开居中弹层 */}
                        <button
                          type="button"
                          className="qty-rowfill-btn"
                          aria-label={`裁片 ${label} 整列设值`}
                          title="整列设值：批量设置该裁片全部码号的 d/tol"
                          data-testid={`per-type-fill-btn-${label}`}
                          onClick={() => openFill(label)}
                        >
                          ≡
                        </button>
                      </div>
                      {fill?.label === label ? (
                        <ColumnFillPopover
                          label={label}
                          x={fill.x}
                          y={fill.y}
                          onApply={applyColumnFill}
                          onClose={() => setFill(null)}
                        />
                      ) : null}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((size) => {
                const sk = perTypeSizeKey(size);
                return (
                  <tr key={sk}>
                    <th className="per-type-rowhead" scope="row">
                      {sizeLabel(size)}
                    </th>
                    {orderedLabels.map((label) => {
                      if (cellMissing(label, sk)) {
                        return (
                          <td key={label} className="per-type-cell missing">
                            <span className="per-type-missing" title="该码号无此裁片">
                              —
                            </span>
                          </td>
                        );
                      }
                      const v = draft[label]?.[sk] ?? { d: '', tol: '' };
                      return (
                        <td key={label} className="per-type-cell">
                          <input
                            type="number"
                            min={0}
                            max={MAX_OVERLAP_MM}
                            step={0.5}
                            placeholder={`d${LE}${MAX_OVERLAP_MM}`}
                            value={v.d}
                            onChange={(e) => updateDraftCell(label, sk, 'd', e.target.value)}
                            onBlur={(e) =>
                              updateDraftCell(label, sk, 'd', clampDraft(e.target.value, MAX_OVERLAP_MM))
                            }
                            data-testid={`d-${label}-${sk}`}
                            aria-label={`裁片 ${label} 码 ${sizeLabel(size)} 重合`}
                          />
                          <input
                            type="number"
                            min={0}
                            max={MAX_ROTATION_TOL_DEG}
                            step={1}
                            placeholder={`t${LE}${MAX_ROTATION_TOL_DEG}`}
                            value={v.tol}
                            onChange={(e) => updateDraftCell(label, sk, 'tol', e.target.value)}
                            onBlur={(e) =>
                              updateDraftCell(label, sk, 'tol', clampDraft(e.target.value, MAX_ROTATION_TOL_DEG))
                            }
                            data-testid={`tol-${label}-${sk}`}
                            aria-label={`裁片 ${label} 码 ${sizeLabel(size)} 旋转`}
                          />
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="per-type-hint dim small">
          行 = 码号、列 = 裁片 g 码；重合 0–{MAX_OVERLAP_MM}mm、旋转 0–{MAX_ROTATION_TOL_DEG}°
          （全局上限）。空值 = 继承全局默认（不重合 / 锁布纹线）；「—」= 该码号无此裁片。
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

// ---------------------------------------------------------------------------
// ColumnFillPopover —— 列头「≡ 整列设值」弹层（输入统一 d/tol → draft 整列写）。
// ---------------------------------------------------------------------------

interface ColumnFillPopoverProps {
  label: string;
  /** 弹层中心点（视口坐标，px）：开层时算好的表容器可视区中心。 */
  x: number;
  y: number;
  onApply: (label: string, d: string, tol: string) => void;
  onClose: () => void;
}

/**
 * 整列设值弹层：草稿 + 应用模式（应用才写 draft）。d/tol 任一侧留空 = 该侧整列继承
 * 默认（清空该侧）。关闭三路径：取消 / 遮罩 mousedown / ESC；Enter 快捷应用。
 * 复用 QtyMatrix 的 .qty-fill-* 样式段（同构弹层，暗底同色系）；Portal 到 body +
 * fixed 居中（不锚列头，避免被裁剪/盖住，QtyMatrix 2026-08-16 修复同款定位）。
 */
function ColumnFillPopover({ label, x, y, onApply, onClose }: ColumnFillPopoverProps): JSX.Element {
  const [dDraft, setDDraft] = useState<string>('');
  const [tolDraft, setTolDraft] = useState<string>('');

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

  function apply(): void {
    // blur 规整同主矩阵输入（负值/超限收边；空串保留 = 继承默认）
    onApply(label, clampDraft(dDraft, MAX_OVERLAP_MM), clampDraft(tolDraft, MAX_ROTATION_TOL_DEG));
  }

  return createPortal(
    <>
      <div
        className="qty-popover-backdrop qty-popover-backdrop--per-type"
        onMouseDown={onClose}
        aria-hidden="true"
        data-testid="per-type-fill-backdrop"
      />
      <div
        className="qty-fill-popover qty-fill-popover--per-type"
        role="dialog"
        aria-label={`裁片 ${label} 整列设值`}
        style={{ left: x, top: y }}
      >
        <div className="qty-fill-title">裁片 {label} · 整列设值</div>
        <div className="qty-fill-row">
          <label htmlFor={`per-type-fill-d-${label}`}>重合 d</label>
          <input
            id={`per-type-fill-d-${label}`}
            className="qty-fill-input"
            type="number"
            min={0}
            max={MAX_OVERLAP_MM}
            step={0.5}
            placeholder={`d${LE}${MAX_OVERLAP_MM}`}
            value={dDraft}
            autoFocus
            aria-label="整列重合 d"
            data-testid="per-type-fill-d"
            onChange={(e) => setDDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                apply();
              }
            }}
          />
        </div>
        <div className="qty-fill-row">
          <label htmlFor={`per-type-fill-tol-${label}`}>旋转 t</label>
          <input
            id={`per-type-fill-tol-${label}`}
            className="qty-fill-input"
            type="number"
            min={0}
            max={MAX_ROTATION_TOL_DEG}
            step={1}
            placeholder={`t${LE}${MAX_ROTATION_TOL_DEG}`}
            value={tolDraft}
            aria-label="整列旋转 t"
            data-testid="per-type-fill-tol"
            onChange={(e) => setTolDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                apply();
              }
            }}
          />
        </div>
        <div className="qty-fill-hint">写入该裁片全部码号；留空一侧 = 该侧继承全局默认</div>
        <div className="qty-fill-actions">
          <button type="button" className="qty-fill-cancel" onClick={onClose}>
            取消
          </button>
          <button type="button" className="qty-fill-apply" onClick={apply}>
            应用
          </button>
        </div>
      </div>
    </>,
    document.body,
  );
}
