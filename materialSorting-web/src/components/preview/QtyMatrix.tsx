// QtyMatrix —— 裁片 × 尺码数量矩阵（矩阵化重构 US-002）。
//
// 职责（一屏看全 + 直接编辑 + 批量填充 + 即时小计）：
//   1. 行 = 全码 label 并集（按 doc.sizes 顺序首次出现排序 → 最小码 pieces 顺序优先，
//      后续码新增 label 追加在尾部）；行头 = [A 徽章] + 裁片名 + 缩略图（PiecePreviewSVG
//      compact）+ 悬浮「填充」按钮。
//   2. 列 = doc.sizes 全码（null 码殿后显示「通用」，无 null 码不渲染该列）+ 行合计列；
//      列头是 button，点击 setSize(该码) 驱动下方图形预览区（尺码浏览职责原属 SizeTabs，
//      US-003 起由本组件列头承担），当前 activeSize 列头高亮。
//   3. 格子 = 内联 number input：点击直接键入、Enter/Tab 提交并移到下一格、blur 提交；
//      值一律过 clampQty（[0,99] 整数）写 setPiecePerSize。数量 0 格子显著暗色样式
//      （语义 = 该码不排此片，title 说明）；某码缺该 label 的格子渲染 disabled「—」
//      （区别于 0，不可编辑）。
//   4. 特例高亮：格子值 ≠ 该行 baseValue 且整行非全同 → .override（整行同值不高亮，
//      避免逐格手改满屏噪点）；baseValue 缺席兜底 1（未填充时的高亮基准）。
//   5. 行头「填充」popover：输入 X 应用 → setRowAll（整行写该 label 存在的码 + baseValue=X，
//      即「默认值」；特例 = 填充后个别格子再改）。
//   6. 小计反馈：每行合计列 = Σ 该行各码 demand；底部每码小计行 = Σ 该码各 label demand；
//      工具条总片数 = 所有小计之和（本 Story Σdemand 口径；US-004 升级为物理片数口径，
//      配对片 ×2）。全 0 红色警示；「重置为默认 1」整表批量回 1。
//
// 设计原则（CLAUDE.md / AGENTS.md 矩阵化重构关键约定）：
//   - 单一真相源：doc/activeSize/setSize/openZoom 来自 uploadStore，quantities/
//     setPiecePerSize/setRowAll 来自 qtyStore；本组件不持业务状态（仅 popover 开关 +
//     格子草稿两个 UI 态）。数量读取一律走 getPieceDisplay selector（不直接读
//     quantities[label]，与 ParsedPiecesView / PieceZoomModal 同口径）。
//   - 行填充只写该 label 实际存在的码（rowSizes），不给缺片码造 phantom perSize 键
//     （避免 getPieceDisplay editable 语义与 serializeQuantities 输出被污染）。
//   - 布局：矩阵容器 max-height 45vh 内部滚动 + sticky 表头/首列（.qty-matrix-scroll）；
//     窄屏（≤1366）靠行头 220px + 格子 64px 的 min-width 自然横向滚动，不引入 CSS 框架。
//   - 缩略图点击 openZoom(label, activeSize) 复用 PieceZoomModal（US-013 声明式受控模态，
//     PreviewPage 顶层单例）。
//
// 性能注意：
//   - 每行一个 PiecePreviewSVG compact 缩略图（M1787 10 行 × 5 层 imperative DOM ≈ 60+
//     节点，低频 UI 开销可接受；切码时 repPiece 换源整组重建，PiecePreviewSVG 内建幂等）。
//   - 数量编辑（qtyStore set）→ 组件订阅 quantities 整体 re-render；矩阵 ~10×12 格规模，
//     低频 UI 操作开销可接受（与 ParsedPiecesView 同口径，不做 cell 级 memo）。

import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';
import { PiecePreviewSVG } from './PiecePreviewSVG';
import { useUploadStore } from '../../store/uploadStore';
import { clampQty, getPieceDisplay, useQtyStore } from '../../store/qtyStore';
import type { ParsedPiece } from '../../types/parsed';

/** null 码（通用）的人读文案；与 SizePicker/PreviewPage「通用」同语义。 */
function sizeLabel(size: number | null): string {
  return size === null ? '通用' : String(size);
}

/** sizeKey 口径与 qtyStore / params.serializeQuantities 一致：number->String；null->'null'。 */
function sizeKeyOf(size: number | null): string {
  return size === null ? 'null' : String(size);
}

/** 矩阵行模型：label + 该 label 实际存在的码列表（行填充范围）。 */
interface MatrixRow {
  label: string;
  sizes: (number | null)[];
}

// ---------------------------------------------------------------------------
// QtyMatrixCell —— 单个数量格子（内联编辑 + 草稿同步 + Enter/Tab 跳格）。
// ---------------------------------------------------------------------------

interface QtyMatrixCellProps {
  /** 片型 label（A/B/C...，跨码匹配同一片型）。 */
  label: string;
  /** 该格码号（number 或 null=通用）。 */
  size: number | null;
  /** store 侧当前值（getPieceDisplay().qty）。 */
  value: number;
  /** 特例高亮（值 ≠ baseValue 且整行非全同）。 */
  override: boolean;
  /** 平铺格索引 rowIdx-colIdx（Enter/Tab 跳格导航用）。 */
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
 * - store 侧外部变更（整行填充 / 重置）经 useEffect 同步进「未聚焦」格子的草稿；
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

  // store 侧外部变更（行填充 / 重置 / 其它入口改值）同步草稿（聚焦中的格子除外）。
  useEffect(() => {
    if (!focusedRef.current) setDraft(String(value));
  }, [value]);

  function commit(raw: string): void {
    const v = clampQty(raw);
    if (raw !== String(v)) setDraft(String(v));
    if (v !== value) onCommit(v);
  }

  return (
    <td className={"qty-cell" + (value === 0 ? " zero" : "") + (override ? " override" : "")}>
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
// RowFillPopover —— 行头「填充」弹层（输入默认值 X → setRowAll 整行写）。
// ---------------------------------------------------------------------------

interface RowFillPopoverProps {
  label: string;
  /** 初值 = 该行当前 baseValue（默认基准）。 */
  base: number;
  onApply: (label: string, value: number) => void;
  onClose: () => void;
}

/**
 * 行填充 popover：草稿 + 应用模式（应用才写 store）。
 * 关闭三路径：取消 / 遮罩（透明 backdrop mousedown）/ ESC；Enter 快捷应用。
 * backdrop 是 fixed 全屏透明层（z 低于 popover），既承接点外关闭又不挡表格视觉。
 */
function RowFillPopover({ label, base, onApply, onClose }: RowFillPopoverProps): JSX.Element {
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

  return (
    <>
      <div
        className="qty-popover-backdrop"
        onMouseDown={onClose}
        aria-hidden="true"
        data-testid="qty-popover-backdrop"
      />
      <div className="qty-fill-popover" role="dialog" aria-label={"裁片 " + label + " 整行填充"}>
        <div className="qty-fill-title">裁片 {label} · 整行填充</div>
        <div className="qty-fill-row">
          <label htmlFor={"qty-fill-" + label}>默认值</label>
          <input
            id={"qty-fill-" + label}
            className="qty-fill-input"
            type="number"
            min={0}
            max={99}
            step={1}
            value={draft}
            autoFocus
            aria-label="整行填充数量"
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
        <div className="qty-fill-actions">
          <button type="button" className="qty-fill-cancel" onClick={onClose}>
            取消
          </button>
          <button type="button" className="qty-fill-apply" onClick={apply}>
            应用
          </button>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// QtyMatrix 主组件
// ---------------------------------------------------------------------------

/**
 * 裁片 × 尺码数量矩阵。doc=null 时渲染 null（空态由 PreviewPage 兜底，双重防御）。
 *
 * 数据派生（每 render 重算，doc 稳定引用 + 规模 ~10 行 × 12 列，开销可接受）：
 *   - piecesByLabel：label → (sizeKey → ParsedPiece)，供行存在性 / 缩略图 rep 定位。
 *   - rows：按 doc.sizes 顺序首次出现的 label 并集（最小码 pieces 顺序优先）。
 *   - repPiece(label)：优先 activeSize 的同 label 片（缩略图与下方图形预览同码视觉一致），
 *     activeSize 无此 label 时回退首个含它的码。
 */
export function QtyMatrix(): JSX.Element | null {
  const doc = useUploadStore((s) => s.doc);
  const activeSize = useUploadStore((s) => s.activeSize);
  const setSize = useUploadStore((s) => s.setSize);
  const openZoom = useUploadStore((s) => s.openZoom);
  const quantities = useQtyStore((s) => s.quantities);
  const setPiecePerSize = useQtyStore((s) => s.setPiecePerSize);
  const setRowAll = useQtyStore((s) => s.setRowAll);

  // UI 态：行填充 popover 打开目标（一次至多一个）。
  const [fillOpen, setFillOpen] = useState<string | null>(null);
  const tableRef = useRef<HTMLTableElement>(null);

  if (!doc) return null;

  const columns: (number | null)[] = doc.sizes.map((s) => s.size);

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

  /** 该 label 存在的码列表（行填充范围：不写缺片码，防 phantom perSize 键）。 */
  function rowSizes(label: string): (number | null)[] {
    return columns.filter((c) => cellExists(label, c));
  }

  /** 缩略图 rep 片：优先 activeSize 版本，回退首个含它的码。 */
  function repPiece(label: string): ParsedPiece | null {
    const bySize = piecesByLabel.get(label);
    if (!bySize) return null;
    const inActive = bySize.get(sizeKeyOf(activeSize));
    if (inActive) return inActive;
    for (const c of columns) {
      const p = bySize.get(sizeKeyOf(c));
      if (p) return p;
    }
    return null;
  }

  /** 特例高亮基准：baseValue 缺席（未 hydrate / 手建 label）兜底 1。 */
  function rowBase(label: string): number {
    return quantities[label]?.baseValue ?? 1;
  }

  /** 整行是否全同（全同则整行不高亮，避免逐格手改满屏噪点）。 */
  function rowAllSame(label: string): boolean {
    const sizes = rowSizes(label);
    if (sizes.length === 0) return true;
    const first = cellQty(label, sizes[0]);
    return sizes.every((c) => cellQty(label, c) === first);
  }

  const rows: MatrixRow[] = labelOrder.map((label) => ({ label, sizes: rowSizes(label) }));

  // 小计（本 Story Σdemand 口径；US-004 升级物理片数口径 = Σ demand × (paired?2:1)）。
  const rowTotals: number[] = rows.map((r) =>
    r.sizes.reduce<number>((acc, c) => acc + cellQty(r.label, c), 0),
  );
  const sizeSubtotals: number[] = columns.map((c) =>
    rows.reduce<number>(
      (acc, r) => acc + (cellExists(r.label, c) ? cellQty(r.label, c) : 0),
      0,
    ),
  );
  const total = sizeSubtotals.reduce<number>((a, b) => a + b, 0);

  /** Enter/Tab 跳格：平铺顺序下一格（末格回卷首格）。 */
  function focusNextCell(current: string): void {
    const table = tableRef.current;
    if (!table) return;
    const inputs = Array.from(
      table.querySelectorAll<HTMLInputElement>("input.qty-cell-input:not([disabled])"),
    );
    const idx = inputs.findIndex((i) => i.dataset.cell === current);
    if (idx < 0 || inputs.length === 0) return;
    const next = inputs[(idx + 1) % inputs.length];
    next.focus();
    next.select();
  }

  function handleFillApply(label: string, value: number): void {
    setRowAll(label, rowSizes(label), value);
    setFillOpen(null);
  }

  /** 整表重置：每行按其存在的码整行回 1（baseValue 同步 1）。 */
  function handleReset(): void {
    for (const r of rows) setRowAll(r.label, r.sizes, 1);
  }

  return (
    <div className="qty-matrix" data-testid="qty-matrix">
      <div className="qty-matrix-toolbar">
        <span className="qty-total">
          总片数 <strong data-testid="qty-total">{total}</strong>
        </span>
        {total === 0 && rows.length > 0 ? (
          <span className="qty-zero-warn" data-testid="qty-zero-warn">
            全部尺码数量为 0，无法求解
          </span>
        ) : null}
        <button type="button" className="qty-reset-btn" onClick={handleReset}>
          重置为默认 1
        </button>
      </div>

      <div className="qty-matrix-scroll">
        <table className="qty-matrix-table" ref={tableRef}>
          <thead>
            <tr>
              <th className="qty-corner" scope="col">
                裁片
              </th>
              {columns.map((c) => {
                const isActive = c === activeSize;
                return (
                  <th className="qty-colhead" scope="col" key={sizeKeyOf(c)}>
                    <button
                      type="button"
                      className={"qty-size-btn" + (isActive ? " active" : "")}
                      aria-pressed={isActive}
                      onClick={() => setSize(c)}
                    >
                      {sizeLabel(c)}
                    </button>
                  </th>
                );
              })}
              <th className="qty-colhead qty-total-col" scope="col">
                合计
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, ri) => {
              const rep = repPiece(r.label);
              const repName = rep ? rep.name : r.label;
              const base = rowBase(r.label);
              const allSame = rowAllSame(r.label);
              return (
                <tr key={r.label}>
                  <th className="qty-rowhead" scope="row">
                    <span className="qty-label-badge">{r.label}</span>
                    <span className="qty-rowname" title={repName}>
                      {repName}
                    </span>
                    <button
                      type="button"
                      className="qty-thumb"
                      aria-label={"放大预览裁片 " + r.label}
                      title="放大预览"
                      onClick={() => openZoom(r.label, activeSize)}
                    >
                      {rep ? <PiecePreviewSVG piece={rep} compact /> : null}
                    </button>
                    <button
                      type="button"
                      className="qty-fill-btn"
                      onClick={() => setFillOpen(fillOpen === r.label ? null : r.label)}
                    >
                      填充
                    </button>
                    {fillOpen === r.label ? (
                      <RowFillPopover
                        label={r.label}
                        base={base}
                        onApply={handleFillApply}
                        onClose={() => setFillOpen(null)}
                      />
                    ) : null}
                  </th>
                  {columns.map((c, ci) => {
                    const cellKey = ri + "-" + ci;
                    if (!cellExists(r.label, c)) {
                      return (
                        <td className="qty-cell missing" key={sizeKeyOf(c)}>
                          <input
                            className="qty-cell-input"
                            type="text"
                            value="—"
                            disabled
                            readOnly
                            aria-label={"裁片 " + r.label + " 码 " + sizeLabel(c) + " 无此裁片"}
                            title="该尺码无此裁片"
                          />
                        </td>
                      );
                    }
                    const v = cellQty(r.label, c);
                    return (
                      <QtyMatrixCell
                        key={sizeKeyOf(c)}
                        label={r.label}
                        size={c}
                        value={v}
                        override={!allSame && v !== base}
                        cellKey={cellKey}
                        onCommit={(nv) => setPiecePerSize(r.label, c, nv)}
                        onNext={focusNextCell}
                      />
                    );
                  })}
                  <td className="qty-rowtotal">{rowTotals[ri]}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th className="qty-rowhead qty-subtotal-rowhead" scope="row">
                每码小计
              </th>
              {columns.map((c, ci) => (
                <td className="qty-subtotal" key={sizeKeyOf(c)}>
                  {sizeSubtotals[ci]}
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
