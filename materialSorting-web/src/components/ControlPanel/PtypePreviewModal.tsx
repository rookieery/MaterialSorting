// PtypePreviewModal —— 片型放大预览模态（US-018 AC#7）。
//
// 点击 PerTypeOverridesModal 表头缩略图触发（controlPanelStore.openPreviewPtype）；
// 叠在 PerTypeOverridesModal 之上（z-index 更高），关闭时仅关自身、底层草稿保留。
//
// 与 PieceZoomModal（US-013）同模式：
//   - 声明式受控 Portal：订阅 controlPanelStore.previewPtype + 本地 representatives；
//     previewPtype=null 时不渲染。
//   - Portal 到 document.body（与 PieceZoomModal/PerTypeOverridesModal 同目标）。
//   - 关闭交互三方式（AC#10）：✕ / 遮罩 mousedown / ESC（独立于 PerTypeOverridesModal）。
//
// 数据源（D10/D11；2026-08-17 修复数据不一致 bug）：**每次打开（previewPtype 变非
// null）重新 fetch** /api/ptypes —— 旧实现只在应用加载时 fetch 一次，重传母版 commit
// 后 PerTypeOverridesModal（每次打开都 fetch）缩略图已更新而本模态仍持旧缓存，
// 同一列两张图对不上。打开期间遮罩挡住上传入口，state 不会再变，两处数据一致。
// fetch 期间保留上次 reps（不闪 loading）。representatives[previewPtype] 不存在 →
// 渲染空体（降级：fetch 失败、空 state、ptype 缺代表裁片，均退化为「无预览」）。
//
// 头部编号（2026-08-17）：rep.label（代表裁片在上传预览里的 g01+ 编号，与
// QtyMatrix 列头同口径）徽章复用 .piece-card-label（PieceZoomModal 头部同款）；
// rep.label 缺席（旧 intermediate / fetch 降级）兜底片型名。hover/aria 只报编号
// 不报片型名：`${编号}-放大预览`（与 PerTypeOverridesModal 缩略图 hover 同格式）。
//
// layer-aware 渲染（D11）：复用 PiecePreviewSVG 全量渲染（非 compact 模式，pad=20，
// 与 PieceZoomModal 一致）。v1 仅外轮廓；US-024 intermediate 扩 5 层后自动带 5 层。
//
// 关键不变量（AC#10）：ESC 独立 —— 本模态 ESC listener 始终只关 previewPtype，
// 不触碰 modal（底层高级配置弹窗的 ESC listener 内判 previewPtype===null 才关，双层独立）。
//
// 不引入 CSS 框架；.ptype-preview-overlay / .ptype-preview-modal / .ptype-preview-close /
// .ptype-preview-body 全部沿用 style.css 暗背景 + #2ea06c 同色系（与 PieceZoomModal 一致）。

import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { useControlPanelStore } from '../../store/controlPanelStore';
import type { ParsedPiece } from '../../types/parsed';
import type { PtypeRepresentative, PtypesResponse } from '../../types/ptype';
import { PiecePreviewSVG } from '../preview/PiecePreviewSVG';

/** 把 PtypeRepresentative 扩展为 ParsedPiece（label 空、name=ptype）。 */
function repToPiece(rep: PtypeRepresentative, ptype: string): ParsedPiece {
  return {
    label: '', // 放大预览不展示 g 码标注（ptype 代表裁片跨码合并，label 无意义）
    name: ptype,
    polygon: rep.polygon,
    internal_lines: rep.internal_lines ?? [],
    notches: rep.notches ?? [],
    net_polygon: rep.net_polygon ?? [],
    grain_line: rep.grain_line ?? null,
  };
}

export function PtypePreviewModal(): JSX.Element | null {
  const previewPtype = useControlPanelStore((s) => s.previewPtype);
  const closePreviewPtype = useControlPanelStore((s) => s.closePreviewPtype);

  // 代表裁片缓存：**每次 previewPtype 打开时重新 fetch**（弹窗遮罩挡住上传入口，
  // 打开期间 state 不会再变 → 与 PerTypeOverridesModal 缩略图数据保证一致）。
  // fetch 期间保留上次 reps（不闪 loading）；null 时跳过（关闭态不发请求）。
  const [representatives, setRepresentatives] = useState<Record<string, PtypeRepresentative>>({});

  useEffect(() => {
    if (previewPtype === null) return;
    let cancelled = false;
    fetch('/api/ptypes')
      .then((r) => r.json() as Promise<PtypesResponse>)
      .then((data) => {
        if (cancelled) return;
        setRepresentatives(data.representatives ?? {});
      })
      .catch(() => {
        if (cancelled) return;
        setRepresentatives({});
      });
    return () => {
      cancelled = true;
    };
  }, [previewPtype]);

  // ESC 监听（AC#10）：本模态 ESC 始终只关 previewPtype，不双层关闭。
  // 必须在 hooks 层无条件调用（不能在条件分支里），判 previewPtype!==null 在 listener 内。
  useEffect(() => {
    if (previewPtype === null) return;
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.preventDefault();
        closePreviewPtype();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [previewPtype, closePreviewPtype]);

  if (previewPtype === null) return null;
  const rep = representatives[previewPtype];
  // 头部：编号徽章（与上传预览 QtyMatrix 列头同口径）优先，片型名兜底；
  // hover/aria 统一「编号-放大预览」格式，不含片型名。
  const headText = rep?.label ?? previewPtype;
  const headTitle = `${headText}-放大预览`;

  function handleOverlayMouseDown(e: React.MouseEvent): void {
    if (e.target === e.currentTarget) closePreviewPtype();
  }

  function handleModalMouseDown(e: React.MouseEvent): void {
    e.stopPropagation();
  }

  return createPortal(
    <div
      className="ptype-preview-overlay"
      onMouseDown={handleOverlayMouseDown}
      data-testid="ptype-preview-overlay"
    >
      <div
        className="ptype-preview-modal"
        role="dialog"
        aria-modal="true"
        aria-label={headTitle}
        onMouseDown={handleModalMouseDown}
      >
        <button
          type="button"
          className="ptype-preview-close"
          aria-label="关闭"
          onClick={closePreviewPtype}
          data-testid="ptype-preview-close"
        >
          ✕
        </button>
        <div className="ptype-preview-head" title={headTitle}>
          {rep?.label ? (
            <span className="piece-card-label">{rep.label}</span>
          ) : (
            <span className="ptype-preview-name">{previewPtype}</span>
          )}
        </div>
        <div className="ptype-preview-body">
          {rep ? (
            <PiecePreviewSVG piece={repToPiece(rep, previewPtype)} pad={20} />
          ) : (
            <div className="ptype-preview-empty">代表裁片数据不可用</div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
