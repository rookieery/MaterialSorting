// PieceZoomModal —— 放大预览模态（US-013；裁片编号化重构 US-003 起头部只显 g 码 + 码号，
// 中文 block 名已从契约删除）。
//
// 单击 QtyMatrix 行头缩略图时弹出该裁片的大图模态（zoom.size = 缩略图 rep 自身的码，
// 所见即所放大），复用 PiecePreviewSVG 的 5 层命令式渲染（scale(1,-1) 翻转不变量保留）。
// 原 ParsedPiecesView 卡片图形区点击入口随图形预览区拆除删除（两入口弹同一模态，冗余）。
//
// 声明式受控（矩阵化重构 US-003 起预览页唯一模态）：
//   - 订阅 uploadStore.zoom + doc；zoom=null 或 doc=null 时渲染 null。
//   - Portal 到 document.body（不被 .page overflow/display:none 裁切；与 Tooltip 同 Portal 目标）。
//   - 关闭交互三方式（D4）：✕ 按钮 / 遮罩空白 / ESC；ESC 监听挂卸载成对。
//   - 仅展示（无可编辑控件），故无需草稿 state；数量编辑入口在 QtyMatrix（数量弹窗已拆除）。
//
// 头部信息（详情模态追求信息完整，与卡片头追求简洁互补）：
//   [g码徽章] {qty}份 · 码 {sizeLabel(size)}
//   - 数量与卡片头同口径：qtyStore getPieceDisplay(quantities, label, size).qty，
//     单位「份」（一份 = 母版一个轮廓，数量即一切、不合成镜像）。
//   - 唯一标识 = g 码（v2 契约 parse 响应无 name 字段）。
//
// 关键约束：
//   - 跨码匹配同一裁片按 label（g 码次序），与 qtyStore / QtyMatrix 同口径。
//   - 防御性兜底：doc.sizes 找不到匹配码、或码内 pieces 找不到匹配 label → 渲染 null
//     （不挂 DOM；理论不会发生，因 openZoom 由 QtyMatrix 在已挂载缩略图上调）。
//   - 不引入 CSS 框架；.piece-zoom-overlay / .piece-zoom-modal / .piece-zoom-close /
//     .piece-zoom-body 全部沿用 style.css 暗背景 + 绿色 #2ea06c 同色系。
//   - 复用 PiecePreviewSVG 的 pad=20（比卡片默认 pad=14 加大留白，放大显示更舒适）。

import { useEffect } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { PiecePreviewSVG } from './PiecePreviewSVG';
import { useUploadStore } from '../../store/uploadStore';
import { getPieceDisplay, useQtyStore } from '../../store/qtyStore';
import type { ParsedPiece } from '../../types/parsed';

/** null 码（通用）的人读文案；与 QtyMatrix 列头「通用」同语义。 */
function sizeLabel(size: number | null): string {
  return size === null ? '通用' : String(size);
}

/**
 * 从 doc + zoom 目标定位 ParsedPiece。
 * 防御性兜底：找不到码 / 找不到 label → 返回 null（组件渲染 null）。
 */
function locatePiece(
  doc: { sizes: { size: number | null; pieces: ParsedPiece[] }[] } | null,
  label: string,
  size: number | null,
): { piece: ParsedPiece } | null {
  if (!doc) return null;
  const matched = doc.sizes.find((s) => s.size === size);
  if (!matched) return null;
  const piece = matched.pieces.find((p) => p.label === label);
  if (!piece) return null;
  return { piece };
}

export function PieceZoomModal(): JSX.Element | null {
  const zoom = useUploadStore((s) => s.zoom);
  const doc = useUploadStore((s) => s.doc);
  const closeZoom = useUploadStore((s) => s.closeZoom);
  const quantities = useQtyStore((s) => s.quantities);

  // ESC 监听：zoom !== null 时挂 window.keydown、关闭时卸载（无残留）。
  // 必须在 hooks 层无条件调用（不能在条件分支里），故判 zoom!==null 在 listener 内。
  useEffect(() => {
    if (zoom === null) return;
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeZoom();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [zoom, closeZoom]);

  if (zoom === null || doc === null) return null;

  // 防御性兜底：找不到码 / 找不到 label → 不渲染（理论不会发生，因 openZoom 由已挂载卡片触发）
  const located = locatePiece(doc, zoom.label, zoom.size);
  if (!located) return null;
  const { piece } = located;
  const display = getPieceDisplay(quantities, zoom.label, zoom.size);

  function handleOverlayClick(e: React.MouseEvent): void {
    // 仅当 click 落在 overlay 自身（不是冒泡上来的子元素）时关闭
    if (e.target === e.currentTarget) closeZoom();
  }

  function handleModalClick(e: React.MouseEvent): void {
    // modal 内点击不冒泡到 overlay 触发关闭
    e.stopPropagation();
  }

  return createPortal(
    <div
      className="piece-zoom-overlay"
      onClick={handleOverlayClick}
      data-testid="piece-zoom-overlay"
    >
      <div
        className="piece-zoom-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`裁片 ${zoom.label} 码 ${sizeLabel(zoom.size)} 放大预览`}
        onClick={handleModalClick}
      >
        <button
          type="button"
          className="piece-zoom-close"
          aria-label="关闭"
          onClick={closeZoom}
          data-testid="piece-zoom-close"
        >
          ✕
        </button>
        <div className="piece-zoom-head">
          <span className="piece-card-label">{piece.label}</span>
          <span className="piece-zoom-qty">{display.qty}份</span>
          <span className="piece-zoom-meta"> · 码 {sizeLabel(zoom.size)}</span>
        </div>
        <div className="piece-zoom-body">
          <PiecePreviewSVG piece={piece} pad={20} />
        </div>
      </div>
    </div>,
    document.body,
  );
}
