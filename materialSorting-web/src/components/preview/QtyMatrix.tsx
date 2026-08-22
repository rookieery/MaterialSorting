// QtyMatrix —— 尺码 × 裁片数量矩阵（矩阵化重构 US-002；2026-08-16 行列转置，对齐
// PerTypeOverridesModal 高级配置弹窗的「裁片作列」风格；裁片编号化重构 US-003 起数量
// 口径 = Σ perSize 数量，配对 ×2 概念删除 —— 数量即一切，母版 N 个轮廓 × 数量）。
//
// 职责（一屏看全 + 直接编辑 + 即时小计）：
//   1. 列 = 全码 label 并集（按 doc.sizes 顺序首次出现排序 → 最小码 pieces 顺序优先，
//      后续码新增 label 追加在尾部）；列头 = 缩略图（PiecePreviewSVG compact 80×80，
//      点击放大，title/aria = g 码）+「序号徽章」+「≡」整列设值 icon（见 6，缩略图
//      下方常驻小按钮）。列头与高级配置弹窗 thead（缩略图 + g 码徽章）同构，观感一致。
//   2. 行 = doc.sizes 全码（null 码殿后显示「通用」，无 null 码不渲染该行）+ 行尾小计列；
//      行头是 button，点击 setSize(该码) 切换 activeSize（决定列头缩略图优先显示哪个码
//      版本的裁片），当前 activeSize 行头高亮。
//   3. 格子 = 内联 number input：点击直接键入、Enter/Tab 提交并移到下一格、blur 提交；
//      值一律过 clampQty（[0,99] 整数）写 setPiecePerSize。数量 0 格子显著暗色样式
//      （语义 = 该码不排此片，title 说明）；某码缺该 label 的格子渲染 disabled「—」
//      （区别于 0，不可编辑）。
//   4. 特例高亮：格子值 ≠ 该列 baseValue 且整列非全同 → .override（整列同值不高亮，
//      避免逐格手改满屏噪点）；baseValue 缺席兜底 1（未填充时的高亮基准）。
//   5. 小计反馈（US-003 起 = Σ perSize 数量）：行尾小计列（每码）/ 底部合计行（每裁片）/
//      工具条总片数 = 数量之和（每份对应母版一个轮廓，不合成镜像；口径说明在总片数
//      title）。全 0 红色警示。
//   6. 列级整列设值（2026-08-16 转置回归，适配纯图列头）：点缩略图下方「≡」icon（title
//      悬浮提示「整列设值」）→ 弹层输入统一值 X → setRowAll 整列写（值 + baseValue=X）。
//      特例兼容 = 应用后单格再改（.override 高亮，见 4）。弹层 createPortal 到 body +
//      fixed 居中于矩阵容器可视区（开层时取 .qty-matrix rect 中心）：不锚 sticky 列头 ——
//      列头 z-index:3 层叠上下文内的 absolute 弹层会被 sticky 行头盖住，且超出
//      .qty-matrix-scroll（overflow:auto）会被裁剪/撑出滚动条（2026-08-16 修复）。
//
// 设计原则（CLAUDE.md / AGENTS.md 矩阵化重构关键约定）：
//   - 单一真相源：doc/activeSize/setSize/openZoom 来自 uploadStore，quantities/
//     setPiecePerSize/setRowAll 来自 qtyStore；本组件不持业务状态（仅弹层开关 +
//     格子草稿两个 UI 态）。数量读取一律走 getPieceDisplay selector（不直接读
//     quantities[label]，与 PieceZoomModal 同口径）。转置是纯视图层变更：store
//     （label → perSize）与 serializeQuantities 输出口径零改动。
//   - 整列写（整列设值弹层入口）只写该 label 实际存在的码（labelSizes），不给缺片码造
//     phantom perSize 键（避免 getPieceDisplay editable 语义与 serializeQuantities
//     输出被污染）。
//   - 布局（高度）：app 是 100vh flex 壳，.qty-matrix flex:1 + .qty-matrix-scroll
//     flex:1/min-height:0 —— 矩阵滚动区吃满 .preview-main 剩余高度，只在真实不够时
//     纵向滚动。转置后行数 = 码数（≤8 + 合计行）、行高 ~34px（缩略图集中在表头），
//     一屏看全比旧行式布局（每行 92px 缩略图行头）更容易。
//   - 布局（列宽）：表格 table-layout:fixed，列宽只由首行 th width 决定 —— 行头
//     88px/小计列 56px 定宽钉死；裁片列 width:auto 按规范「均分剩余水平空间」把全部
//     富余平分掉。窄屏（≤1366）列宽下限由表格 inline min-width floor（88 + 96×N + 56，
//     N=裁片列数动态）保证：列宽和超出容器自然横向滚动（与高级配置弹窗 10 列横滚同
//     机制）。
//   - 缩略图点击 openZoom(label, rep.size) 复用 PieceZoomModal（US-013 声明式受控模态，
//     PreviewPage 顶层单例）。传 rep 自己的码而非 activeSize：所见即所放大，且该 label
//     不在 activeSize 时（rep 已回退其它码）不会静默失败。
//   - tour 锚点（矩阵化重构 US-005）：根容器 data-tour="qty-matrix"（previewTour parsed 步，
//     指引矩阵浏览与列头缩略图放大）；首个码行头 data-tour="qty-rowhead"（set-qty 步，
//     指引格内编辑 / 整列设值 / 特例高亮）。步骤内容重大变更时 bump TOUR_VERSION
//     强制老用户重看（见 tour/steps/index.ts；转置已 bump）。
//
// 性能注意：
//   - 每列头一个 PiecePreviewSVG compact 缩略图（M1787 10 列 × 5 层 imperative DOM ≈ 60+
//     节点，低频 UI 开销可接受；切码时 repPiece 换源整组重建，PiecePreviewSVG 内建幂等）。
//   - 数量编辑（qtyStore set）→ 组件订阅 quantities 整体 re-render；矩阵 ~12×10 格规模，
//     低频 UI 操作开销可接受，不做 cell 级 memo。

import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { PiecePreviewSVG } from './PiecePreviewSVG';
import { useUploadStore } from '../../store/uploadStore';
import { clampQty, getPieceDisplay, useQtyStore } from '../../store/qtyStore';
import type { ParsedPiece } from '../../types/parsed';

/** null 码（通用）的人读文案；与 SizePicker/PreviewPage「通用」同语义。 */
function sizeLabel(size: number | null): string {
  return size === null ? '通用' : String(size);
}

// 列宽常量（与 style.css 同值，双向引用，改任一处须同步另一处）：
//   - ROWHEAD_W = .qty-corner/.qty-rowhead 行头定宽；TOTAL_COL_W = .qty-total-col
//     小计列定宽（fixed 布局下首行 width 钉死，不吸收富余）。
//   - COL_MIN_W = 裁片列下限：fixed 布局下裁片列 width:auto 均分富余、可缩到 0，
//     此下限经表格 inline min-width floor（ROWHEAD_W + N×COL_MIN_W + TOTAL_COL_W，
//     max(100%, …px)）保证 —— 窄屏列宽和超出容器触发横向滚动，宽屏仍撑满面板。
//     96 = 缩略图 80 + 列头 padding 4×2 + 边框余量（缩略图 80×80 自 2026-08 起，
//     细长裁片 5 层线条可辨；高级配置弹窗 .ptype-thumb 仍 64，两者观感不再对齐）。
const ROWHEAD_W = 88;
const COL_MIN_W = 96;
const TOTAL_COL_W = 56;

/** sizeKey 口径与 qtyStore / params.serializeQuantities 一致：number->String；null->'null'。 */
function sizeKeyOf(size: number | null): string {
  return size === null ? 'null' : String(size);
}

/** 矩阵列模型：label + 该 label 实际存在的码列表（整列写 / 重置范围）。 */
interface MatrixCol {
  label: string;
  sizes: (number | null)[];
}

// ---------------------------------------------------------------------------
// QtyMatrixCell —— 单个数量格子（内联编辑 + 草稿同步 + Enter/Tab 跳格）。
// ---------------------------------------------------------------------------

interface QtyMatrixCellProps {
  /** 裁片 g 码（g01+ 零填充，跨码匹配同一裁片）。 */
  label: string;
  /** 该格码号（number 或 null=通用）。 */
  size: number | null;
  /** store 侧当前值（getPieceDisplay().qty）。 */
  value: number;
  /** 特例高亮（值 ≠ baseValue 且整列非全同）。 */
  override: boolean;
  /** 平铺格索引 labelIdx-sizeIdx（Enter/Tab 跳格导航用，列优先序）。 */
  cellKey: string;
  /** 提交（值已过 clampQty；与 store 值相同则不触发）。 */
  onCommit: (value: number) => void;
  /** Enter/Tab 提交后跳到下一格（平铺顺序）。 */
  onNext: (cellKey: string) => void;
}

/**
 * 数量格子：本地草稿（draft string）+ blur / Enter / Tab 提交。
 *
 * - 草稿不实时 clamp：允许清空重输 / 输入中间态，提交时统一 clampQty 规整。
 * - store 侧外部变更（整列重置 / 其它入口改值）经 useEffect 同步进「未聚焦」格子的草稿；
 *   聚焦中的格子保持用户草稿（blur 时若草稿与 store 值一致则不重复写入）。
 * - 点击 / 聚焦时 select()：直接键入覆盖旧值（零额外点击成本）。
 * - Enter 与 Tab 同语义：preventDefault 后手动移焦到平铺顺序下一格（末格回卷首格）。
 */
function QtyMatrixCell({
  label,
  size,
  value,
  override,
  cellKey,
  onCommit,
  onNext,
}: QtyMatrixCellProps): JSX.Element {
  const [draft, setDraft] = useState<string>(String(value));
  const focusedRef = useRef(false);

  // store 侧外部变更（整列重置 / 其它入口改值）同步草稿（聚焦中的格子除外）。
  useEffect(() => {
    if (!focusedRef.current) setDraft(String(value));
  }, [value]);

  function commit(raw: string): void {
    const v = clampQty(raw);
    if (raw !== String(v)) setDraft(String(v));
    if (v !== value) onCommit(v);
  }

  return (
    <td
      className={
        "qty-cell" +
        (value === 0 ? " zero" : "") +
        (override ? " override" : "")
      }
    >
      <input
        className="qty-cell-input"
        type="number"
        min={0}
        max={99}
        step={1}
        inputMode="numeric"
        value={draft}
        data-cell={cellKey}
        aria-label={"裁片 " + label + " 码 " + sizeLabel(size) + " 数量"}
        title={value === 0 ? "数量 0：该码不排此裁片" : undefined}
        onFocus={(e) => {
          focusedRef.current = true;
          // 全选：直接键入覆盖旧值（点击即编辑，无清空成本）
          e.currentTarget.select();
        }}
        onBlur={() => {
          focusedRef.current = false;
          commit(draft);
        }}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === "Tab") {
            e.preventDefault();
            commit(draft);
            onNext(cellKey);
          }
        }}
      />
    </td>
  );
}

// ---------------------------------------------------------------------------
// ColFillPopover —— 列头「≡ 整列设值」弹层（输入统一值 X → setRowAll 整列写）。
// ---------------------------------------------------------------------------

interface ColFillPopoverProps {
  label: string;
  /** 初值 = 该列当前 baseValue（默认基准）。 */
  base: number;
  /** 弹层中心点（视口坐标，px）：开层时算好的矩阵容器可视区中心。 */
  x: number;
  y: number;
  onApply: (label: string, value: number) => void;
  onClose: () => void;
}

/**
 * 列级整列设值弹层：草稿 + 应用模式（应用才写 store）。
 * 关闭三路径：取消 / 遮罩（透明 backdrop mousedown）/ ESC；Enter 快捷应用。
 *
 * 定位（2026-08-16 修复展示异常）：createPortal 到 body + position:fixed 居中于
 * (x, y)（inline left/top + translate(-50%,-50%)），不锚 sticky 列头 —— 列头
 * z-index:3 层叠上下文内的 absolute 弹层会被 sticky 行头盖住，且超出
 * .qty-matrix-scroll（overflow:auto）边界会被裁剪/撑出滚动条。
 * backdrop 是 fixed 全屏透明层（z 低于弹层），既承接点外关闭又不挡表格视觉。
 */
function ColFillPopover({ label, base, x, y, onApply, onClose }: ColFillPopoverProps): JSX.Element {
  const [draft, setDraft] = useState<string>(String(base));

  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function apply(): void {
    onApply(label, clampQty(draft));
  }

  return createPortal(
    <>
      <div
        className="qty-popover-backdrop"
        onMouseDown={onClose}
        aria-hidden="true"
        data-testid="qty-popover-backdrop"
      />
      <div
        className="qty-fill-popover"
        role="dialog"
        aria-label={"裁片 " + label + " 整列设值"}
        style={{ left: x, top: y }}
      >
        <div className="qty-fill-title">裁片 {label} · 整列设值</div>
        <div className="qty-fill-row">
          <label htmlFor={"qty-fill-" + label}>统一数量</label>
          <input
            id={"qty-fill-" + label}
            className="qty-fill-input"
            type="number"
            min={0}
            max={99}
            step={1}
            value={draft}
            autoFocus
            aria-label="整列设值数量"
            data-testid="qty-fill-input"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                apply();
              }
            }}
          />
        </div>
        <div className="qty-fill-hint">写入该裁片全部尺码；个别尺码要不同值时，应用后单击对应格子修改</div>
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

// ---------------------------------------------------------------------------
// QtyMatrix 主组件
// ---------------------------------------------------------------------------

/**
 * 尺码 × 裁片数量矩阵（行 = 尺码，列 = 裁片）。doc=null 时渲染 null（空态由
 * PreviewPage 兜底，双重防御）。
 *
 * 数据派生（每 render 重算，doc 稳定引用 + 规模 ~10 行 × 12 列，开销可接受）：
 *   - piecesByLabel：label → (sizeKey → ParsedPiece)，供列存在性 / 缩略图 rep 定位。
 *   - cols：按 doc.sizes 顺序首次出现的 label 并集（最小码 pieces 顺序优先）。
 *   - repPiece(label)：优先 activeSize 的同 label 片（行头切码后列缩略图跟随显示该码
 *     版本），activeSize 无此 label 时回退首个含它的码。
 */
export function QtyMatrix(): JSX.Element | null {
  const doc = useUploadStore((s) => s.doc);
  const activeSize = useUploadStore((s) => s.activeSize);
  const setSize = useUploadStore((s) => s.setSize);
  const openZoom = useUploadStore((s) => s.openZoom);
  const quantities = useQtyStore((s) => s.quantities);
  const setPiecePerSize = useQtyStore((s) => s.setPiecePerSize);
  const setRowAll = useQtyStore((s) => s.setRowAll);

  // UI 态：整列设值弹层（目标列 + fixed 定位中心点，一次至多一个）。
  const [fill, setFill] = useState<{ label: string; x: number; y: number } | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);

  if (!doc) return null;

  const sizeRows: (number | null)[] = doc.sizes.map((s) => s.size);

  // label 并集（保序）：doc.sizes 升序遍历，首次出现顺序 = 最小码 pieces 顺序优先。
  const piecesByLabel = new Map<string, Map<string, ParsedPiece>>();
  const labelOrder: string[] = [];
  for (const s of doc.sizes) {
    for (const p of s.pieces) {
      let bySize = piecesByLabel.get(p.label);
      if (!bySize) {
        bySize = new Map();
        piecesByLabel.set(p.label, bySize);
        labelOrder.push(p.label);
      }
      bySize.set(sizeKeyOf(s.size), p);
    }
  }

  function cellExists(label: string, size: number | null): boolean {
    return piecesByLabel.get(label)?.has(sizeKeyOf(size)) ?? false;
  }

  function cellQty(label: string, size: number | null): number {
    return getPieceDisplay(quantities, label, size).qty;
  }

  /** 该 label 存在的码列表（整列写 / 重置范围：不写缺片码，防 phantom perSize 键）。 */
  function labelSizes(label: string): (number | null)[] {
    return sizeRows.filter((c) => cellExists(label, c));
  }

  /** 缩略图 rep 片：优先 activeSize 版本，回退首个含它的码；返回片 + 所属码
      （缩略图点击 openZoom 传 rep 自身的码而非 activeSize：所见即所放大，且该 label
      不在 activeSize 时不会静默失败）。 */
  function repPiece(label: string): { piece: ParsedPiece; size: number | null } | null {
    const bySize = piecesByLabel.get(label);
    if (!bySize) return null;
    const inActive = bySize.get(sizeKeyOf(activeSize));
    if (inActive) return { piece: inActive, size: activeSize };
    for (const c of sizeRows) {
      const p = bySize.get(sizeKeyOf(c));
      if (p) return { piece: p, size: c };
    }
    return null;
  }

  /** 特例高亮基准：baseValue 缺席（未 hydrate / 手建 label）兜底 1。 */
  function colBase(label: string): number {
    return quantities[label]?.baseValue ?? 1;
  }

  /** 整列是否全同（全同则整列不高亮，避免逐格手改满屏噪点）。 */
  function colAllSame(label: string): boolean {
    const sizes = labelSizes(label);
    if (sizes.length === 0) return true;
    const first = cellQty(label, sizes[0]);
    return sizes.every((c) => cellQty(label, c) === first);
  }

  const cols: MatrixCol[] = labelOrder.map((label) => ({ label, sizes: labelSizes(label) }));

  // 小计（US-003 起口径 = Σ perSize 数量；一份 = 母版一个轮廓，不合成镜像）。
  //   - labelTotals：每裁片合计（tfoot 底部合计行，按列）。
  //   - sizeSubtotals：每码小计（tbody 行尾小计列）。
  const labelTotals: number[] = cols.map((c) =>
    c.sizes.reduce<number>((acc, s) => acc + cellQty(c.label, s), 0),
  );
  const sizeSubtotals: number[] = sizeRows.map((s) =>
    cols.reduce<number>((acc, c) => acc + (cellExists(c.label, s) ? cellQty(c.label, s) : 0), 0),
  );
  const total = sizeSubtotals.reduce<number>((a, b) => a + b, 0);

  /** Enter/Tab 跳格：平铺顺序下一格（末格回卷首格）。平铺序 = 列优先（同裁片沿列
      向下跨码 → 再到下一裁片列顶），与旧行式布局「沿一行编辑完一个裁片」的工作流
      等价 —— DOM 是行优先（按码逐片），故按 cellKey (labelIdx-sizeIdx) 数值序重排。 */
  function focusNextCell(current: string): void {
    const table = tableRef.current;
    if (!table) return;
    const inputs = Array.from(
      table.querySelectorAll<HTMLInputElement>("input.qty-cell-input:not([disabled])"),
    );
    if (inputs.length === 0) return;
    const keyOf = (i: HTMLInputElement): [number, number] => {
      const parts = (i.dataset.cell ?? "0-0").split("-").map(Number);
      return [parts[0] || 0, parts[1] || 0];
    };
    const sorted = inputs.slice().sort((a, b) => {
      const [al, as] = keyOf(a);
      const [bl, bs] = keyOf(b);
      return al - bl || as - bs;
    });
    const idx = sorted.findIndex((i) => i.dataset.cell === current);
    if (idx < 0) return;
    const next = sorted[(idx + 1) % sorted.length];
    next.focus();
    next.select();
  }

  /** 打开整列设值弹层：定位中心 = 矩阵容器可视区中心（fixed 定位，见 ColFillPopover）。 */
  function openFill(label: string): void {
    if (fill?.label === label) {
      setFill(null);
      return;
    }
    const rect = rootRef.current?.getBoundingClientRect();
    setFill({
      label,
      x: rect ? rect.left + rect.width / 2 : 0,
      y: rect ? rect.top + rect.height / 2 : 0,
    });
  }

  /** 整列设值应用：写该 label 实际存在的码（labelSizes）+ 关弹层。 */
  function handleFillApply(label: string, value: number): void {
    setRowAll(label, labelSizes(label), value);
    setFill(null);
  }

  return (
    <div className="qty-matrix" ref={rootRef} data-testid="qty-matrix" data-tour="qty-matrix">
      <div className="qty-matrix-toolbar">
        <span className="qty-total" title="总片数 = 各尺码数量之和；每份对应母版一个轮廓（不合成镜像）">
          总片数 <strong data-testid="qty-total">{total}</strong>
        </span>
        {total === 0 && cols.length > 0 ? (
          <span className="qty-zero-warn" data-testid="qty-zero-warn">
            全部尺码数量为 0，无法求解
          </span>
        ) : null}
      </div>

      <div className="qty-matrix-scroll">
        <table
          className="qty-matrix-table"
          ref={tableRef}
          style={{
            minWidth: `max(100%, ${ROWHEAD_W + COL_MIN_W * cols.length + TOTAL_COL_W}px)`,
          }}
        >
          <thead>
            <tr>
              <th className="qty-corner" scope="col">
                尺码
              </th>
              {cols.map((c) => {
                const rep = repPiece(c.label);
                return (
                  <th className="qty-colhead" scope="col" key={c.label}>
                    {/* th 保持 table-cell（display:flex 会拆掉表格布局），内部 flex 布局
                        由 .qty-colhead-inner 承担 */}
                    <div className="qty-colhead-inner">
                      <button
                        type="button"
                        className="qty-thumb"
                        aria-label={"放大预览裁片 " + c.label}
                        title={c.label + " · 放大预览"}
                        onClick={() => rep && openZoom(c.label, rep.size)}
                      >
                        {rep ? <PiecePreviewSVG piece={rep.piece} compact /> : null}
                      </button>
                      <div className="qty-colhead-meta">
                        <span className="qty-label-badge">{c.label}</span>
                        {/* 整列设值 icon：缩略图下方常驻，hover title 提示，点击开居中弹层
                            （类名沿用旧 .qty-rowfill-btn / qty-rowfill-*，转置前 ≡ 在行头） */}
                        <button
                          type="button"
                          className="qty-rowfill-btn"
                          aria-label={"裁片 " + c.label + " 整列设值"}
                          title="整列设值：批量设置该裁片全部尺码数量"
                          data-testid={"qty-rowfill-" + c.label}
                          onClick={() => openFill(c.label)}
                        >
                          ≡
                        </button>
                      </div>
                    </div>
                    {fill?.label === c.label ? (
                      <ColFillPopover
                        label={c.label}
                        base={colBase(c.label)}
                        x={fill.x}
                        y={fill.y}
                        onApply={handleFillApply}
                        onClose={() => setFill(null)}
                      />
                    ) : null}
                  </th>
                );
              })}
              <th className="qty-colhead qty-total-col" scope="col">
                小计
              </th>
            </tr>
          </thead>
          <tbody>
            {sizeRows.map((size, si) => {
              const isActive = size === activeSize;
              return (
                <tr key={sizeKeyOf(size)}>
                  <th
                    className="qty-rowhead"
                    scope="row"
                    data-tour={si === 0 ? "qty-rowhead" : undefined}
                  >
                    <button
                      type="button"
                      className={"qty-size-btn" + (isActive ? " active" : "")}
                      aria-pressed={isActive}
                      onClick={() => setSize(size)}
                    >
                      {sizeLabel(size)}
                    </button>
                  </th>
                  {cols.map((c, li) => {
                    const cellKey = li + "-" + si;
                    if (!cellExists(c.label, size)) {
                      return (
                        <td className="qty-cell missing" key={c.label}>
                          <input
                            className="qty-cell-input"
                            type="text"
                            value="—"
                            disabled
                            readOnly
                            aria-label={"裁片 " + c.label + " 码 " + sizeLabel(size) + " 无此裁片"}
                            title="该尺码无此裁片"
                          />
                        </td>
                      );
                    }
                    const v = cellQty(c.label, size);
                    return (
                      <QtyMatrixCell
                        key={c.label}
                        label={c.label}
                        size={size}
                        value={v}
                        override={!colAllSame(c.label) && v !== colBase(c.label)}
                        cellKey={cellKey}
                        onCommit={(nv) => setPiecePerSize(c.label, size, nv)}
                        onNext={focusNextCell}
                      />
                    );
                  })}
                  <td className="qty-rowtotal">{sizeSubtotals[si]}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th className="qty-rowhead qty-subtotal-rowhead" scope="row">
                合计
              </th>
              {cols.map((c, li) => (
                <td className="qty-subtotal" key={c.label}>
                  {labelTotals[li]}
                </td>
              ))}
              <td className="qty-subtotal qty-subtotal-total">{total}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
