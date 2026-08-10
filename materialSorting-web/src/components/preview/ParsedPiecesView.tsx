// ParsedPiecesView —— 当前 activeSize 下全部裁片的 grid 视图（US-008）。
//
// 职责：
//   1. 从 uploadStore 读 doc + activeSize，过滤出当前码的全部 pieces。
//   2. 渲染响应式 grid（每片一张卡片：PiecePreviewSVG + A/B/C 标签 + 裁片名）。
//   3. 空态：当前码无 pieces（极少见，但兜底：后端返回某码 pieces=[]）→ 显示「该码无裁片」。
//
// 设计原则（CLAUDE.md / AGENTS.md US-007 关键约定）：
//   - 单片卡片用 PiecePreviewSVG 的 **单片模式**（多片能力留作未来扩展，US-007 AC#4）。
//   - 卡片视觉与 .nest-card 同口径（暗背景 #2a2c32 + 圆角 + 上方标签头 + 下方 SVG 自适应）。
//   - 不引入 CSS 框架，沿用 style.css 的 .piece-card / .piece-card-head / .piece-card-body。
//   - grid 用 CSS Grid auto-fill + minmax(220px,1fr)：浏览器宽度自适应列数，避免窗口缩小时
//     单卡被压扁（每片 polygon 形状不规则，最小宽度需要保证 SVG 不退化成窄条）。
//   - key 用 `${label}-${name}`：label 在码内唯一（A/B/C/...），name 也唯一；两者拼合跨码安全。
//
// 性能注意：
//   - 每片卡片各挂一个 PiecePreviewSVG（独立 useEffect 建 flipGroup）。M1787 每码 ~10 片 ×
//     5 层 imperative DOM ≈ 100+ 节点，是可接受的开销（切码时一次性重建）。
//   - 切码时 ParsedPiecesView 整组重渲染（受 activeSize 驱动），旧卡片 unmount 自动 GC。
//
// 空态：doc=null 时 PreviewPage 走整体空态分支，不渲染本组件（双重防御）。

import type { JSX } from 'react';
import { PiecePreviewSVG } from './PiecePreviewSVG';
import { useUploadStore } from '../../store/uploadStore';
import type { ParsedPiece } from '../../types/parsed';

export function ParsedPiecesView(): JSX.Element {
  const doc = useUploadStore((s) => s.doc);
  const activeSize = useUploadStore((s) => s.activeSize);

  // doc=null 时 PreviewPage 走整体空态分支（双重防御）。
  if (!doc) return <></>;

  // 找当前 activeSize 对应的 ParsedSize；理论一定存在（SizeTabs 只能切到 doc.sizes 里的码），
  // 防御性兜底：找不到时显示空态。
  const matched = doc.sizes.find((s) => s.size === activeSize);
  const pieces: ParsedPiece[] = matched ? matched.pieces : [];

  return (
    <div className="parsed-pieces-view">
      {pieces.length === 0 ? (
        <div className="parsed-pieces-empty">该尺码无裁片</div>
      ) : (
        <div className="piece-grid">
          {pieces.map((p) => (
            <div key={`${p.label}-${p.name}`} className="piece-card">
              <div className="piece-card-head">
                <span className="piece-card-label">{p.label}</span>
                <span className="piece-card-name">{p.name}</span>
              </div>
              <div className="piece-card-body">
                <PiecePreviewSVG piece={p} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
