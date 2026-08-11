// PtypePreviewModal —— 片型放大预览模态（US-018 AC#7）。
//
// 点击 PerTypeOverridesModal 表头缩略图触发（controlPanelStore.openPreviewPtype）；
// 叠在 PerTypeOverridesModal 之上（z-index 更高），关闭时仅关自身、底层草稿保留。
//
// 与 PieceZoomModal（US-013）同模式：
//   - 声明式受控 Portal：订阅 controlPanelStore.previewPtype + 本地 representatives；
//     previewPtype=null 时不渲染。
//   - Portal 到 document.body（与 PieceQtyDialog/PieceZoomModal/PerTypeOverridesModal 同目标）。
//   - 关闭交互三方式（AC#10）：✕ / 遮罩 mousedown / ESC（独立于 PerTypeOverridesModal）。
//
// 数据源（D10/D11）：本模态自身 fetch /api/ptypes（与 PerTypeOverridesModal 各自独立缓存，
// 简单且解耦；fetch 是 cheap 单端点）。representatives[previewPtype] 不存在 → 渲染空体
// （降级：fetch 失败、空 state、ptype 缺代表裁片，均退化为「无预览」）。
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
    label: '', // 放大预览不展示 A/B/C 标注（ptype 代表裁片跨码合并，label 无意义）
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

  // 代表裁片缓存：mount 时 fetch 一次（与 PerTypeOverridesModal 各自缓存，简单解耦）。
  // PerTypeOverridesModal 重新 fetch 是为了刷新；本模态挂在 ControlPanel 顶层常驻，
  // 只 fetch 一次即可（modal 关闭再开不重 fetch，representatives 不变）。
  const [representatives, setRepresentatives] = useState<Record<string, PtypeRepresentative>>({});

  useEffect(() => {
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
  }, []);

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
        aria-label={`片型放大预览 ${previewPtype}`}
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
        <div className="ptype-preview-head">
          <span className="ptype-preview-name">{previewPtype}</span>
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
