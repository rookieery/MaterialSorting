// ParsedPiecesView —— 当前 activeSize 下全部裁片的 grid 视图（US-008；US-014 卡片头；
// 矩阵化重构 US-003 降级为「按码图形预览」区）。
//
// 职责：
//   1. 从 uploadStore 读 doc + activeSize，过滤出当前码的全部 pieces。
//   2. 区标题「图形预览 · 码 X」标明当前码（X = activeSize 码号 / 「通用」）；码切换由
//      QtyMatrix 列头点击驱动（tab 切换职责已移交矩阵列头，SizeTabs 已随 US-003 拆除）。
//   3. 渲染响应式 grid（每片一张卡片：PiecePreviewSVG + A/B/C 徽章 + 只读数量）。
//      卡片头数量是**只读** span（数量编辑统一走 QtyMatrix 格内编辑 / 整行填充），
//      单位「份」：配对片 1 份 = L+R 2 物理片（与后端 demand 语义一致，US-004 起矩阵
//      行头以配对徽章说明实际片数）。
//   4. 点卡片图形区 → 放大预览（US-013 PieceZoomModal，role=button/tabIndex/
//      Enter/Space a11y 保留）。
//   5. 空态：activeSize 不在 doc.sizes（防御兜底）或当前码 pieces=[] → 「该码无裁片」。
//
// 卡片头（US-003 矩阵化重构：数量改只读）：
//   - [.piece-card-label] + [.piece-card-qty]（label 徽章 + 只读数量 span「N 份」）
//   - 数量从 qtyStore getPieceDisplay(quantities, label, activeSize) 读：
//     * 正常 → <span class="piece-card-qty">{qty}份</span>（数量编辑入口在 QtyMatrix）
//     * 该码无此裁片（editable=false）→ <span class="piece-card-qty disabled"
//       title="该尺码未配置此裁片数量">{qty}份</span>（当前码 pieces 均有 hydrate
//       记录，理论不触发；保留作防御）
//
// 设计原则（CLAUDE.md / AGENTS.md US-007/US-011 关键约定）：
//   - 单片卡片用 PiecePreviewSVG 的 **单片模式**（多片能力留作未来扩展，US-007 AC#4）。
//   - 卡片视觉与 .nest-card 同口径（暗背景 #2a2c32 + 圆角 + 上方标签头 + 下方 SVG 自适应）。
//   - 不引入 CSS 框架，沿用 style.css 的 .piece-card / .piece-card-head / .piece-card-body。
//   - grid 用 CSS Grid auto-fill + minmax(220px,1fr)：浏览器宽度自适应列数，避免窗口缩小时
//     单卡被压扁（每片 polygon 形状不规则，最小宽度需要保证 SVG 不退化成窄条）。
//   - key 用 `${label}-${name}`：label 在码内唯一（A/B/C/...），name 也唯一；两者拼合跨码安全。
//   - 数量 map 以 label 为 key 跨码匹配同一片型，不直接读 quantities[label]，统一走
//     getPieceDisplay selector（与 QtyMatrix / PieceZoomModal 同口径）。
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

/** null 码（母版中代表「通用/不分码」）的人读文案；与 QtyMatrix 列头同语义。 */
const NULL_SIZE_LABEL = '通用';

/** 码号人读文案（null →「通用」，number → String(n)）。 */
function sizeLabel(size: number | null): string {
  return size === null ? NULL_SIZE_LABEL : String(size);
}

export function ParsedPiecesView(): JSX.Element {
  const doc = useUploadStore((s) => s.doc);
  const activeSize = useUploadStore((s) => s.activeSize);
  const openZoom = useUploadStore((s) => s.openZoom);
  const quantities = useQtyStore((s) => s.quantities);

  // doc=null 时 PreviewPage 走整体空态分支（双重防御）。
  if (!doc) return <></>;

  // 找当前 activeSize 对应的 ParsedSize；理论一定存在（QtyMatrix 列头只能切到 doc.sizes
  // 里的码），防御性兜底：找不到时显示空态。
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
      <div className="parsed-pieces-title" data-testid="parsed-pieces-title">
        图形预览 · 码 {sizeLabel(activeSize)}
      </div>
      {pieces.length === 0 ? (
        <div className="parsed-pieces-empty">该尺码无裁片</div>
      ) : (
        <div className="piece-grid">
          {pieces.map((p) => {
            const display = getPieceDisplay(quantities, p.label, activeSize);
            return (
              <div key={`${p.label}-${p.name}`} className="piece-card">
                <div className="piece-card-head">
                  <span className="piece-card-label">{p.label}</span>
                  {/* 只读数量（单位「份」：配对片 1 份 = L+R 2 物理片）；编辑入口在 QtyMatrix */}
                  <span
                    className={
                      'piece-card-qty' + (display.editable ? '' : ' disabled')
                    }
                    title={display.editable ? undefined : '该尺码未配置此裁片数量'}
                  >
                    {display.qty}份
                  </span>
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
