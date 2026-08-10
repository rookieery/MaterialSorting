// ParsedPiecesView —— 当前 activeSize 下全部裁片的 grid 视图（US-008；US-014 改造卡片头）。
//
// 职责：
//   1. 从 uploadStore 读 doc + activeSize，过滤出当前码的全部 pieces。
//   2. 渲染响应式 grid（每片一张卡片：PiecePreviewSVG + A/B/C 徽章 + 序号(数量)）。
//   3. 卡片图形区点击 → 放大预览（US-013 PieceZoomModal）；序号(数量) 点击 → 数量弹窗
//      （US-012 PieceQtyDialog）。两个交互入口严格区分（详见点击区域分离约定）。
//   4. 空态：当前码无 pieces（极少见，但兜底：后端返回某码 pieces=[]）→ 显示「该码无裁片」。
//
// 卡片头改造（US-014）：
//   - 旧：[.piece-card-label] + [.piece-card-name]（label 徽章 + 中文母版名）
//   - 新：[.piece-card-label] + [.piece-card-qty]（label 徽章 + 序号(数量) 按钮）
//   - 序号 = piece 在当前码 pieces 数组的 index+1（与 label 字母次序一致：A=1, B=2, ...）
//   - 数量 + 可编辑性 从 qtyStore getPieceDisplay(quantities, label, activeSize) 读：
//     * editable=true  → <button class="piece-card-qty" onClick=openQtyDialog>{seq}({qty})</button>
//     * editable=false → <span class="piece-card-qty disabled" title={reason}>{seq}({qty})</span>
//       （global 非 source 时置灰，native title 提供 hover 提示文案）
//
// 点击区域分离（US-014 关键约定）：
//   - .piece-card-qty（button）onClick → openQtyDialog + e.stopPropagation（防冒泡）
//     虽然 .piece-card-qty 在 .piece-card-head 内（与 .piece-card-body 平级，bubbling 不会
//     跨兄弟节点），但 stopPropagation 是双重防御 —— 防未来结构重组（如把 qty 移到 body 内）。
//   - .piece-card-body（SVG 包裹层）onClick → openZoom；role=button + tabIndex + Enter/Space
//     支持键盘触发（a11y，与 UploadPanel drop-zone 同模式）。
//
// 设计原则（CLAUDE.md / AGENTS.md US-007/US-011 关键约定）：
//   - 单片卡片用 PiecePreviewSVG 的 **单片模式**（多片能力留作未来扩展，US-007 AC#4）。
//   - 卡片视觉与 .nest-card 同口径（暗背景 #2a2c32 + 圆角 + 上方标签头 + 下方 SVG 自适应）。
//   - 不引入 CSS 框架，沿用 style.css 的 .piece-card / .piece-card-head / .piece-card-body。
//   - grid 用 CSS Grid auto-fill + minmax(220px,1fr)：浏览器宽度自适应列数，避免窗口缩小时
//     单卡被压扁（每片 polygon 形状不规则，最小宽度需要保证 SVG 不退化成窄条）。
//   - key 用 `${label}-${name}`：label 在码内唯一（A/B/C/...），name 也唯一；两者拼合跨码安全。
//   - 数量 map 以 label 为 key 跨码匹配同一片型，不直接读 quantities[label]，统一走
//     getPieceDisplay selector（与 PieceQtyDialog/PieceZoomModal 同口径）。
//
// 性能注意：
//   - 每片卡片各挂一个 PiecePreviewSVG（独立 useEffect 建 flipGroup）。M1787 每码 ~10 片 ×
//     5 层 imperative DOM ≈ 100+ 节点，是可接受的开销（切码时一次性重建）。
//   - 切码时 ParsedPiecesView 整组重渲染（受 activeSize 驱动），旧卡片 unmount 自动 GC。
//   - 数量状态变化（qtyStore）→ 组件订阅 quantities selector → re-render；低频 UI 操作，开销可接受。
//
// 空态：doc=null 时 PreviewPage 走整体空态分支，不渲染本组件（双重防御）。

import type { JSX } from 'react';
import { PiecePreviewSVG } from './PiecePreviewSVG';
import { useUploadStore } from '../../store/uploadStore';
import { getPieceDisplay, useQtyStore } from '../../store/qtyStore';
import type { ParsedPiece } from '../../types/parsed';

export function ParsedPiecesView(): JSX.Element {
  const doc = useUploadStore((s) => s.doc);
  const activeSize = useUploadStore((s) => s.activeSize);
  const openQtyDialog = useUploadStore((s) => s.openQtyDialog);
  const openZoom = useUploadStore((s) => s.openZoom);
  const quantities = useQtyStore((s) => s.quantities);

  // doc=null 时 PreviewPage 走整体空态分支（双重防御）。
  if (!doc) return <></>;

  // 找当前 activeSize 对应的 ParsedSize；理论一定存在（SizeTabs 只能切到 doc.sizes 里的码），
  // 防御性兜底：找不到时显示空态。
  const matched = doc.sizes.find((s) => s.size === activeSize);
  const pieces: ParsedPiece[] = matched ? matched.pieces : [];

  // .piece-card-body 键盘触发 openZoom（a11y，与 UploadPanel drop-zone 同模式）
  function handleBodyKeyDown(e: React.KeyboardEvent, label: string, size: number | null): void {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openZoom(label, size);
    }
  }

  return (
    <div className="parsed-pieces-view">
      {pieces.length === 0 ? (
        <div className="parsed-pieces-empty">该尺码无裁片</div>
      ) : (
        <div className="piece-grid">
          {pieces.map((p, idx) => {
            const seq = idx + 1;
            const display = getPieceDisplay(quantities, p.label, activeSize);
            return (
              <div key={`${p.label}-${p.name}`} className="piece-card">
                <div className="piece-card-head">
                  <span className="piece-card-label">{p.label}</span>
                  {display.editable ? (
                    <button
                      type="button"
                      className="piece-card-qty"
                      // stopPropagation 双重防御：即使未来 qty 移到 body 内也不会触发 zoom
                      onClick={(e) => {
                        e.stopPropagation();
                        openQtyDialog(p.label, activeSize);
                      }}
                    >
                      {seq}({display.qty})
                    </button>
                  ) : (
                    <span
                      className="piece-card-qty disabled"
                      title={display.reason ?? undefined}
                    >
                      {seq}({display.qty})
                    </span>
                  )}
                </div>
                <div
                  className="piece-card-body"
                  role="button"
                  tabIndex={0}
                  aria-label={`放大预览裁片 ${p.label}`}
                  onClick={() => openZoom(p.label, activeSize)}
                  onKeyDown={(e) => handleBodyKeyDown(e, p.label, activeSize)}
                >
                  <PiecePreviewSVG piece={p} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
