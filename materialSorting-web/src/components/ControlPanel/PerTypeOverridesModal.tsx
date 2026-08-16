// PerTypeOverridesModal —— 高级配置：每片型覆盖弹窗（US-018）。
//
// 声明式受控 Portal（参考 PieceZoomModal）：
//   - 订阅 controlPanelStore.modal === 'per_type' 自显隐；null 时不挂 DOM。
//   - Portal 到 document.body（不被 .page overflow/display:none 裁切）。
//   - 关闭交互（AC#10）：确定 / 取消 / ✕ 按钮 / 遮罩 mousedown / ESC。
//
// 表格布局（D10 / AC#3）：
//   - thead 列 = V03_PTYPES 10 个片型（每列缩略图 64×64 + 片型名，不含内外徽章）。
//   - tbody 行 = 2 行：重合 input + 旋转 input；空 placeholder 提示 d≤ / t≤ 上限。
//   - 表格 overflow-x:auto（10 列窄屏溢出）。
//
// 缩略图数据源（D10 / AC#4）：挂载时 fetch GET /api/ptypes（US-020）取 representatives，
// 存本地 state；loading 占位（片型名首字 + 灰底）；fetch 失败降级为片型名文字（不阻塞）。
// 缩略图用 PiecePreviewSVG compact 模式渲染 representatives[ptype]，layer-aware（D11）：
// v1 仅画 polygon，US-024 后数据带 5 层则画 5 层，本组件无需改。
//
// 草稿 + 确定模式（AC#5）：打开时从 form.per_type 读初值进本地 draft（D7 预填：
// INTERNAL_TYPES 重合=10、旋转=0，其余 0/0，保留旧默认行为）；编辑仅改 draft；
// 点确定回写 form.per_type + 关闭；取消/遮罩/ESC 仅关 modal、草稿丢弃。
//
// 片型放大预览（AC#7）：点击 thead 缩略图触发 openPreviewPtype(ptype)；
// PtypePreviewModal 叠在本模态之上（z-index 更高）；关闭预览时本模态草稿保留。
//
// 关键不变量（AC#10）：两层 modal 各自独立 ESC ——
//   - 本组件 ESC listener 内判 previewPtype===null 才关闭，避免预览打开时双层同时关闭。
//   - PtypePreviewModal 自己的 ESC listener 始终只关 previewPtype。
//
// 不引入 CSS 框架；.per-type-overlay / .per-type-modal / .per-type-table / .ptype-thumb
// 全部沿用 style.css 暗背景 #26282e + #2ea06c 同色系（与 PieceZoomModal 一致）。

import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { V03_PTYPES, V03_TABLE } from '../../constants/v03';
import type { PerTypeFormValue } from '../../lib/params';
import { useControlPanelStore } from '../../store/controlPanelStore';
import type { ParsedPiece } from '../../types/parsed';
import type { PtypeRepresentative, PtypesResponse } from '../../types/ptype';
import { PiecePreviewSVG } from '../preview/PiecePreviewSVG';

/** v0.3 内部片型集合（与后端 INTERNAL_TYPES 一致；D7 预填重合='10'）。 */
const INTERNAL_PTYPES = new Set(['单排', '双排', '火机袋', '裤耳']);

/** ≤ 字符（U+2264）—— 与旧 PerTypeOverrides placeholder 一致。 */
const LE = '≤';

/**
 * 把 form.per_type 展开 + D7 预填为 draft 全量 10 行（PerTypeFormValue）。
 * 空 form.per_type[pt] → D7 预填（internal=10/0，external=0/0）；
 * 非空 → 保留用户已填值。
 */
function initializeDraft(values: Record<string, PerTypeFormValue>): Record<string, PerTypeFormValue> {
  const draft: Record<string, PerTypeFormValue> = {};
  for (const pt of V03_PTYPES) {
    const v = values[pt];
    if (v && (v.d.trim() !== '' || v.tol.trim() !== '')) {
      draft[pt] = { d: v.d, tol: v.tol };
    } else {
      // D7 预填：内部片型重合='10'、旋转='0'；其余 '0'/'0'
      draft[pt] = { d: INTERNAL_PTYPES.has(pt) ? '10' : '0', tol: '0' };
    }
  }
  return draft;
}

/** 把 PtypeRepresentative（无 label/name）扩展为 PiecePreviewSVG 接受的 ParsedPiece 形状。 */
function repToPiece(rep: PtypeRepresentative, ptype: string): ParsedPiece {
  return {
    label: '', // compact 模式不渲染 label，空串安全
    name: ptype,
    polygon: rep.polygon,
    internal_lines: rep.internal_lines ?? [],
    notches: rep.notches ?? [],
    net_polygon: rep.net_polygon ?? [],
    grain_line: rep.grain_line ?? null,
  };
}

export interface PerTypeOverridesModalProps {
  /** 每片型的 d/tol 输入字符串（来自 ControlPanel form.per_type）。 */
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
  const openPreviewPtype = useControlPanelStore((s) => s.openPreviewPtype);

  if (modal !== 'per_type') return null;

  return (
    <PerTypeOverridesModalInner
      key="per-type-modal"
      values={values}
      onChange={onChange}
      onClose={closeModal}
      onOpenPreviewPtype={openPreviewPtype}
    />
  );
}

interface InnerProps {
  values: Record<string, PerTypeFormValue>;
  onChange: (next: Record<string, PerTypeFormValue>) => void;
  onClose: () => void;
  onOpenPreviewPtype: (ptype: string) => void;
}

function PerTypeOverridesModalInner({
  values,
  onChange,
  onClose,
  onOpenPreviewPtype,
}: InnerProps): JSX.Element {
  // 草稿：mount 时从 values + D7 预填初始化。key 强制每次 open 重建（避免残留）。
  const [draft, setDraft] = useState<Record<string, PerTypeFormValue>>(() => initializeDraft(values));

  // 缩略图数据：mount 时 fetch GET /api/ptypes；loading / error 三态。
  // fetch 失败降级为 {} → 表头仅显示片型名文字，不阻塞重合/旋转配置（AC#4）。
  const [representatives, setRepresentatives] = useState<Record<string, PtypeRepresentative>>({});
  const [loadingReps, setLoadingReps] = useState<boolean>(true);

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
        // 降级：空 representatives，表头仅片型名（不阻塞重合/旋转配置）
        setRepresentatives({});
        setLoadingReps(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ESC 监听（AC#10）：previewPtype !== null 时由 PtypePreviewModal 处理 ESC（双层独立）。
  // 本 listener 仅在 previewPtype===null 时关 modal，避免双层同时关闭。
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key !== 'Escape') return;
      // 双层 modal：放大预览打开时 ESC 只关预览，不关底层高级配置（AC#10 关键约定）
      if (useControlPanelStore.getState().previewPtype !== null) return;
      e.preventDefault();
      onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  function updateDraft(pt: string, key: 'd' | 'tol', v: string): void {
    setDraft((prev) => ({
      ...prev,
      [pt]: { ...prev[pt], [key]: v },
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

  function handleThumbClick(ptype: string): void {
    onOpenPreviewPtype(ptype);
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
        aria-label="高级配置：每片型覆盖"
        onMouseDown={handleModalMouseDown}
      >
        <div className="per-type-head">
          <span className="per-type-title">高级配置：每片型覆盖</span>
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
                  片型
                </th>
                {V03_PTYPES.map((pt) => {
                  const rep = representatives[pt];
                  return (
                    <th key={pt} scope="col" className="ptype-col">
                      <button
                        type="button"
                        className="ptype-thumb"
                        onClick={() => handleThumbClick(pt)}
                        aria-label={`放大预览 ${pt}`}
                        data-testid={`ptype-thumb-${pt}`}
                        disabled={!rep}
                      >
                        {rep ? (
                          <PiecePreviewSVG piece={repToPiece(rep, pt)} compact />
                        ) : (
                          <span className="ptype-thumb-placeholder" aria-hidden="true">
                            {loadingReps ? '…' : pt.slice(0, 1)}
                          </span>
                        )}
                      </button>
                      <span className="ptype-name">{pt}</span>
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
                {V03_PTYPES.map((pt) => {
                  const entry = V03_TABLE[pt];
                  const v = draft[pt] ?? { d: '', tol: '' };
                  return (
                    <td key={pt}>
                      <input
                        type="number"
                        min={0}
                        step={0.5}
                        placeholder={`d${LE}${entry.d}`}
                        value={v.d}
                        onChange={(e) => updateDraft(pt, 'd', e.target.value)}
                        data-testid={`d-${pt}`}
                        aria-label={`${pt} 重合`}
                      />
                    </td>
                  );
                })}
              </tr>
              <tr>
                <th className="per-type-rowhead" scope="row">
                  旋转
                </th>
                {V03_PTYPES.map((pt) => {
                  const entry = V03_TABLE[pt];
                  const v = draft[pt] ?? { d: '', tol: '' };
                  return (
                    <td key={pt}>
                      <input
                        type="number"
                        min={0}
                        step={1}
                        placeholder={`t${LE}${entry.tol}`}
                        value={v.tol}
                        onChange={(e) => updateDraft(pt, 'tol', e.target.value)}
                        data-testid={`tol-${pt}`}
                        aria-label={`${pt} 旋转`}
                      />
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
        </div>

        <div className="per-type-hint dim small">
          空值 = 继承两档；填值 = 覆盖该维度。受 v0.3 单片上限约束（d=重合 mm，t=旋转 度）。
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
