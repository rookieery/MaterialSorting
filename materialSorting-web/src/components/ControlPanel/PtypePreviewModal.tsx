// PtypePreviewModal —— 裁片放大预览模态（US-018 AC#7；裁片编号化重构 US-003 起
// previewPtype→previewLabel，目标键 = 裁片 g 码，头部显 g 码徽章）。
//
// 点击 PerTypeOverridesModal 表头缩略图触发（controlPanelStore.openPreviewLabel）；
// 叠在 PerTypeOverridesModal 之上（z-index 更高），关闭时仅关自身、底层草稿保留。
//
// 与 PieceZoomModal（US-013）同模式：
//   - 声明式受控 Portal：订阅 controlPanelStore.previewLabel + 本地 representatives；
//     previewLabel=null 时不渲染。
//   - Portal 到 document.body（与 PieceZoomModal/PerTypeOverridesModal 同目标）。
//   - 关闭交互三方式（AC#10）：✕ / 遮罩 mousedown / ESC（独立于 PerTypeOverridesModal）。
//
// 数据源（D10/D11；2026-08-17 修复数据不一致 bug）：**每次打开（previewLabel 变非
// null）重新 fetch** /api/ptypes —— 旧实现只在应用加载时 fetch 一次，重传母版 commit
// 后 PerTypeOverridesModal（每次打开都 fetch）缩略图已更新而本模态仍持旧缓存，
// 同一列两张图对不上。打开期间遮罩挡住上传入口，state 不会再变，两处数据一致。
// fetch 期间保留上次 reps（不闪 loading）。representatives 键 = 裁片 g 码（v2 起
// ptype 键已删），representatives[previewLabel] 不存在 → 渲染空体（降级：fetch 失败、
// 空 state、g 码缺代表裁片，均退化为「无预览」）。
//
// 头部：g 码徽章（rep.label 与 Record 键同值，兜底用 previewLabel 键本身）复用
// .piece-card-label（PieceZoomModal 头部同款）；hover/aria 只报 g 码：
// `${g码}-放大预览`（与 PerTypeOverridesModal 缩略图 hover 同格式）。
//
// layer-aware 渲染（D11）：复用 PiecePreviewSVG 全量渲染（非 compact 模式，pad=20，
// 与 PieceZoomModal 一致；label 传入 → 图上叠印 g 码标注，与上传预览放大同观感）。
//
// 关键不变量（AC#10）：ESC 独立 —— 本模态 ESC listener 始终只关 previewLabel，
// 不触碰 modal（底层高级配置弹窗的 ESC listener 内判 previewLabel===null 才关，双层
// 独立）。本 listener 消费 ESC 时 stopImmediatePropagation()：底层 listener 若因注册
// 顺序在本模态之后执行（其重渲染会挪动注册位，届时 previewLabel 已被置 null），
// 被阻断而不误关底层。
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

/** 把 PtypeRepresentative 扩展为 ParsedPiece（label = 该代表裁片 g 码，图上叠印标注）。 */
function repToPiece(rep: PtypeRepresentative, label: string): ParsedPiece {
  return {
    label,
    polygon: rep.polygon,
    internal_lines: rep.internal_lines ?? [],
    notches: rep.notches ?? [],
    net_polygon: rep.net_polygon ?? [],
    grain_line: rep.grain_line ?? null,
  };
}

export function PtypePreviewModal(): JSX.Element | null {
  const previewLabel = useControlPanelStore((s) => s.previewLabel);
  const closePreviewLabel = useControlPanelStore((s) => s.closePreviewLabel);

  // 代表裁片缓存：**每次 previewLabel 打开时重新 fetch**（弹窗遮罩挡住上传入口，
  // 打开期间 state 不会再变 → 与 PerTypeOverridesModal 缩略图数据保证一致）。
  // fetch 期间保留上次 reps（不闪 loading）；null 时跳过（关闭态不发请求）。
  const [representatives, setRepresentatives] = useState<Record<string, PtypeRepresentative>>({});

  useEffect(() => {
    if (previewLabel === null) return;
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
  }, [previewLabel]);

  // ESC 监听（AC#10）：本模态 ESC 始终只关 previewLabel，不双层关闭。
  // 必须在 hooks 层无条件调用（不能在条件分支里），判 previewLabel!==null 在 listener 内。
  useEffect(() => {
    if (previewLabel === null) return;
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.preventDefault();
        // 顶层消费信号：阻断 window 上后注册的底层 per_type ESC listener（其重渲染
        // 会把 listener 挪到注册队尾，若仅靠 previewLabel 判断，此时已被本函数置
        // null）。stopImmediatePropagation 不依赖事件 cancelable（jsdom 合成事件
        // 默认不可取消，preventDefault 不改变 defaultPrevented）。
        e.stopImmediatePropagation();
        closePreviewLabel();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [previewLabel, closePreviewLabel]);

  if (previewLabel === null) return null;
  const rep = representatives[previewLabel];
  // 头部：g 码徽章（rep.label 与 Record 键同值，兜底 previewLabel 键本身 —— 键即 g 码）；
  // hover/aria 统一「g 码-放大预览」格式。
  const headText = rep?.label ?? previewLabel;
  const headTitle = `${headText}-放大预览`;

  function handleOverlayMouseDown(e: React.MouseEvent): void {
    if (e.target === e.currentTarget) closePreviewLabel();
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
          onClick={closePreviewLabel}
          data-testid="ptype-preview-close"
        >
          ✕
        </button>
        <div className="ptype-preview-head" title={headTitle}>
          <span className="piece-card-label">{headText}</span>
        </div>
        <div className="ptype-preview-body">
          {rep ? (
            <PiecePreviewSVG piece={repToPiece(rep, headText)} pad={20} />
          ) : (
            <div className="ptype-preview-empty">代表裁片数据不可用</div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
