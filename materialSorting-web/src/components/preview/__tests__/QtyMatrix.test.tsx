// 矩阵化重构 US-002 QtyMatrix 集成测试（2026-08-16 转置回归：行 = 尺码，列 = 裁片，
// 对齐 PerTypeOverridesModal 高级配置弹窗「裁片作列 + 列头缩略图」风格）：
//   - 列 = 全码 label 并集（保序，最小码 pieces 顺序优先）；列头 = 大缩略图
//     + 序号徽章 + 常驻「≡」整列设值 icon（裁片名走缩略图 title；名称 span / ×2 徽章 /
//     旧文字「填充」按钮不再回来）
//   - 行 = doc.sizes 全码（null 殿后「通用」，无 null 不渲染该行）+ 行尾小计列；
//     行头点击 setSize + active 高亮
//   - 格子 blur / Enter / Tab 提交走 clampQty 写 qtyStore；0 格子 .zero + title；缺片格 disabled「—」
//   - 特例高亮 .override（≠baseValue 且整列非全同；整列同值不高亮）
//   - 列级整列设值（icon → 居中弹层 → setRowAll 整列写；整表「重置为默认 1」按钮已拆）
//   - 小计：行尾每码小计列 + 底部每裁片合计行 + 工具条总片数 + 全 0 警示
//     （US-004 起物理片数口径 = Σ demand × (paired?2:1)；×2 徽章已拆，缺字段 ×1 兜底）
//   - 缩略图点击 openZoom(label, rep.size)（所见即所放大；label 不在 activeSize 时回退码）
//   - Enter/Tab 跳格 = 列优先平铺序（同裁片沿列向下跨码 → 下一裁片列顶；末格回卷）
//
// 测试模式（原参考已拆除的 ParsedPiecesView.test.tsx）：渲染入 container，store.setState
// 驱动，断言 DOM 结构 + store 状态。React 受控 input 用 native setter + input event 模拟。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QtyMatrix } from '../QtyMatrix';
import { useUploadStore } from '../../../store/uploadStore';
import { useQtyStore } from '../../../store/qtyStore';
import type { ParsedDoc, ParsedPiece } from '../../../types/parsed';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  useUploadStore.getState().reset();
  useQtyStore.getState().resetQuantities();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) {
    const r = root;
    act(() => {
      r.unmount();
    });
    root = null;
  }
  container?.remove();
  container = null;
  useUploadStore.getState().reset();
  useQtyStore.getState().resetQuantities();
});

/** 构造一片：方框 100x80 在 (10,20)-(110,100)，可选覆盖字段。 */
function makePiece(overrides: Partial<ParsedPiece> = {}): ParsedPiece {
  return {
    label: 'g01',
    name: '前片',
    polygon: [
      [10, 20],
      [110, 20],
      [110, 100],
      [10, 100],
    ],
    internal_lines: [],
    notches: [],
    net_polygon: [],
    grain_line: null,
    ...overrides,
  };
}

/**
 * 标准三码 doc：
 *   28: A + B；30: A + B + C；null: C。
 * 转置后：行序 28,30,通用；列序 A,B,C；缺片格 = C@28、A@null、B@null。
 */
function makeStdDoc(): ParsedDoc {
  return {
    doc_id: 'deadbeef',
    filename: 'M1787.dxf',
    sizes: [
      { size: 28, pieces: [makePiece({ label: 'g01', name: '前片28' }), makePiece({ label: 'g02', name: '后片28' })] },
      { size: 30, pieces: [makePiece({ label: 'g01', name: '前片30' }), makePiece({ label: 'g02', name: '后片30' }), makePiece({ label: 'g03', name: '腰30' })] },
      { size: null, pieces: [makePiece({ label: 'g03', name: '腰通用' })] },
    ],
  };
}

/** 按 PreviewPage 同口径 hydrate（每 (label,size)=1 + baseValue=1）。 */
function hydrateDoc(doc: ParsedDoc): void {
  useQtyStore
    .getState()
    .hydrate(doc.sizes.flatMap((s) => s.pieces.map((p) => ({ label: p.label, size: s.size }))));
}

function renderMatrix(): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <QtyMatrix />
      </StrictMode>,
    );
  });
  return container!;
}

/** React 受控 input 设值（native setter + input event，AGENTS.md US-004 模式）。 */
function setInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

function fireKey(el: Element, key: string): void {
  el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
}

function clickEl(el: Element): void {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
}

/** 定位某 (label, size) 的可编辑格子 input（aria-label 精确匹配）。 */
function cellInput(el: HTMLElement, label: string, size: number | null): HTMLInputElement {
  const sizeText = size === null ? '通用' : String(size);
  return el.querySelector<HTMLInputElement>(
    `input[aria-label="裁片 ${label} 码 ${sizeText} 数量"]`,
  )!;
}

describe('QtyMatrix (US-002 转置) 行列结构', () => {
  it('doc=null 时渲染为空（空态由 PreviewPage 兜底）', () => {
    const el = renderMatrix();
    expect(el.querySelector('.qty-matrix')).toBeNull();
  });

  it('行 = doc.sizes 全码（null 殿后「通用」），行头 = 码按钮（当前码高亮）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    const el = renderMatrix();
    const rows = el.querySelectorAll('tbody tr');
    expect(rows.length).toBe(3);
    const btns = el.querySelectorAll<HTMLButtonElement>('tbody .qty-size-btn');
    expect(Array.from(btns).map((b) => b.textContent)).toEqual(['28', '30', '通用']);
    // activeSize=28 行头高亮（aria-pressed 表当前码）
    expect(btns[0].classList.contains('active')).toBe(true);
    expect(btns[0].getAttribute('aria-pressed')).toBe('true');
    expect(btns[1].classList.contains('active')).toBe(false);
    // 首个行头挂 tour 锚点（previewTour set-qty 步）
    expect(rows[0].querySelector('[data-tour="qty-rowhead"]')).not.toBeNull();
  });

  it('列 = 全码 label 并集（最小码 pieces 顺序优先），列头 = 缩略图+徽章+整列设值 icon', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    const el = renderMatrix();
    const badges = el.querySelectorAll('thead .qty-label-badge');
    expect(Array.from(badges).map((b) => b.textContent)).toEqual(['g01', 'g02', 'g03']);
    const heads = el.querySelectorAll('thead th');
    expect(heads[0].textContent).toBe('尺码');
    expect(heads[heads.length - 1].textContent).toBe('小计');
    // 列头 A：缩略图（title 悬浮裁片名）+ ≡ icon（常驻，title 悬浮提示）
    const colA = heads[1];
    expect(colA.querySelector('.qty-thumb svg')).not.toBeNull();
    expect(colA.querySelector<HTMLElement>('.qty-thumb')!.getAttribute('title')).toBe(
      '前片28 · 放大预览',
    );
    const fill = colA.querySelector<HTMLButtonElement>('[data-testid="qty-rowfill-g01"]');
    expect(fill).not.toBeNull();
    expect(fill!.textContent).toBe('≡');
    expect(fill!.getAttribute('aria-label')).toBe('裁片 g01 整列设值');
    expect(fill!.getAttribute('title')).toBe('整列设值：批量设置该裁片全部尺码数量');
    // 旧行头简化拆除项零残留（文字「填充」按钮 / ×2 徽章 / 裁片名 span）
    expect(colA.querySelector('.qty-fill-btn')).toBeNull();
    expect(colA.querySelector('.qty-paired-badge')).toBeNull();
    expect(colA.querySelector('.qty-rowname')).toBeNull();
  });

  it('缩略图 rep 优先 activeSize 版本（切码后列头缩略图 title 跟随）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 30 });
    const el = renderMatrix();
    const thumbs = el.querySelectorAll<HTMLElement>('thead .qty-thumb');
    expect(thumbs[0].getAttribute('title')).toBe('前片30 · 放大预览');
  });

  it('无 null 码时不渲染「通用」行', () => {
    const doc: ParsedDoc = {
      doc_id: 'd2',
      filename: 'x.dxf',
      sizes: [
        { size: 28, pieces: [makePiece({ label: 'g01' })] },
        { size: 30, pieces: [makePiece({ label: 'g01' })] },
      ],
    };
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    const el = renderMatrix();
    const btns = el.querySelectorAll('tbody .qty-size-btn');
    expect(Array.from(btns).map((b) => b.textContent)).toEqual(['28', '30']);
  });

  it('缺片格渲染 disabled「—」（C@28 缺、A/B 无通用行）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    const el = renderMatrix();
    const rows = el.querySelectorAll('tbody tr');
    // 28 码行第三格（C 列）是缺片格
    const row28 = rows[0];
    expect(row28.children[3].classList.contains('missing')).toBe(true);
    const c28 = row28.children[3].querySelector('.qty-cell.missing input')!;
    expect((c28 as HTMLInputElement).disabled).toBe(true);
    expect((c28 as HTMLInputElement).value).toBe('—');
    // 通行（第三行）A/B 列均缺片（C@通用 存在）
    const rowNull = rows[2];
    expect(rowNull.children[1].classList.contains('missing')).toBe(true);
    expect(rowNull.children[2].classList.contains('missing')).toBe(true);
  });
});

describe('QtyMatrix (US-002 转置) 行头切码（activeSize 切换，列缩略图跟随）', () => {
  it('点击行头调 setSize(该码)，当前 activeSize 行头高亮', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    const el = renderMatrix();
    const btns = el.querySelectorAll<HTMLButtonElement>('tbody .qty-size-btn');
    expect(btns[0].classList.contains('active')).toBe(true);
    expect(btns[1].getAttribute('aria-pressed')).toBe('false');
    act(() => {
      clickEl(btns[1]);
    });
    expect(useUploadStore.getState().activeSize).toBe(30);
    const btnsAfter = el.querySelectorAll<HTMLButtonElement>('tbody .qty-size-btn');
    expect(btnsAfter[1].classList.contains('active')).toBe(true);
    expect(btnsAfter[0].classList.contains('active')).toBe(false);
  });

  it('点击 null 码行头调 setSize(null)', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    const el = renderMatrix();
    const btns = el.querySelectorAll<HTMLButtonElement>('tbody .qty-size-btn');
    act(() => {
      clickEl(btns[2]);
    });
    expect(useUploadStore.getState().activeSize).toBeNull();
  });
});

describe('QtyMatrix (US-002 转置) 列头缩略图 openZoom', () => {
  it('点击缩略图 openZoom(label, rep.size)：label 在 activeSize → 放大当前码版本', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    const el = renderMatrix();
    const thumb = el.querySelectorAll<HTMLButtonElement>('thead .qty-thumb')[0]!;
    act(() => {
      clickEl(thumb);
    });
    expect(useUploadStore.getState().zoom).toEqual({ label: 'g01', size: 28 });
  });

  it('label 不在 activeSize（C@28 缺片）→ 放大回退码 rep（C@30），不静默失败', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    const el = renderMatrix();
    // C 列：28 码缺片，rep 回退首个含它的码 30
    const thumb = el.querySelectorAll<HTMLButtonElement>('thead .qty-thumb')[2]!;
    act(() => {
      clickEl(thumb);
    });
    expect(useUploadStore.getState().zoom).toEqual({ label: 'g03', size: 30 });
  });
});

describe('QtyMatrix (US-002) 格内编辑（clampQty + 提交路径）', () => {
  it('blur 提交：值过 clampQty 写 setPiecePerSize（150→99）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    const input = cellInput(el, 'g01', 28);
    act(() => {
      input.focus();
    });
    act(() => {
      setInputValue(input, '150');
    });
    act(() => {
      input.blur();
    });
    expect(useQtyStore.getState().quantities.g01.perSize['28']).toBe(99);
    expect(input.value).toBe('99');
  });

  it('blur 提交 clamp 下界：-3 → 0（0 = 该码不排此片，可编辑）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    const input = cellInput(el, 'g02', 30);
    act(() => {
      input.focus();
    });
    act(() => {
      setInputValue(input, '-3');
    });
    act(() => {
      input.blur();
    });
    expect(useQtyStore.getState().quantities.g02.perSize['30']).toBe(0);
  });

  it('blur 提交小数截断：2.7 → 2', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    const input = cellInput(el, 'g01', 30);
    act(() => {
      input.focus();
    });
    act(() => {
      setInputValue(input, '2.7');
    });
    act(() => {
      input.blur();
    });
    expect(useQtyStore.getState().quantities.g01.perSize['30']).toBe(2);
  });

  it('Enter 提交并移到下一格（列优先平铺序：A@28 → A@30 同裁片下一码）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    const a28 = cellInput(el, 'g01', 28);
    const a30 = cellInput(el, 'g01', 30);
    act(() => {
      a28.focus();
    });
    act(() => {
      setInputValue(a28, '2');
      fireKey(a28, 'Enter');
    });
    expect(useQtyStore.getState().quantities.g01.perSize['28']).toBe(2);
    expect(document.activeElement).toBe(a30);
  });

  it('Tab 提交并移到下一格（跳过缺片 disabled 格：A@30 → B@28 跨到下一裁片列）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    const a30 = cellInput(el, 'g01', 30);
    // A 列 30 码之后是通用码缺片格（disabled）→ 下一可编辑格 = B 列 28 码
    const b28 = cellInput(el, 'g02', 28);
    act(() => {
      a30.focus();
    });
    act(() => {
      setInputValue(a30, '3');
      fireKey(a30, 'Tab');
    });
    expect(useQtyStore.getState().quantities.g01.perSize['30']).toBe(3);
    expect(document.activeElement).toBe(b28);
  });

  it('末格 Enter 回卷首格', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    const last = cellInput(el, 'g03', null);
    const first = cellInput(el, 'g01', 28);
    act(() => {
      last.focus();
    });
    act(() => {
      fireKey(last, 'Enter');
    });
    expect(document.activeElement).toBe(first);
  });
});

describe('QtyMatrix (US-002) 0 格子与特例高亮', () => {
  it('数量 0 格子 .zero 类名 + title 说明（区别于缺片 —）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    useQtyStore.getState().setPiecePerSize('g01', 28, 0);
    const el = renderMatrix();
    const td = cellInput(el, 'g01', 28).closest('td')!;
    expect(td.classList.contains('zero')).toBe(true);
    expect(cellInput(el, 'g01', 28).getAttribute('title')).toBe('数量 0：该码不排此裁片');
    // 0 是显式数量，格子仍可编辑（非 disabled）
    expect(cellInput(el, 'g01', 28).disabled).toBe(false);
  });

  it('hydrate 默认（全 1 + base 1）整列同值 → 无 .override', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    expect(el.querySelectorAll('.qty-cell.override').length).toBe(0);
  });

  it('个别格 ≠ baseValue 且整列非全同 → 仅该格 .override', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    useQtyStore.getState().setPiecePerSize('g01', 28, 2);
    const el = renderMatrix();
    const a28 = cellInput(el, 'g01', 28).closest('td')!;
    const a30 = cellInput(el, 'g01', 30).closest('td')!;
    const b28 = cellInput(el, 'g02', 28).closest('td')!;
    expect(a28.classList.contains('override')).toBe(true);
    expect(a30.classList.contains('override')).toBe(false);
    expect(b28.classList.contains('override')).toBe(false);
  });

  it('整列同值不高亮（逐格手改 B 列全 3，base 仍 1）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    useQtyStore.getState().setPiecePerSize('g02', 28, 3);
    useQtyStore.getState().setPiecePerSize('g02', 30, 3);
    const el = renderMatrix();
    expect(el.querySelectorAll('.qty-cell.override').length).toBe(0);
  });

  it('整列填充后改一格：仅特例格高亮（填充=base，特例=偏离）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    useQtyStore.getState().setRowAll('g01', [28, 30], 2);
    useQtyStore.getState().setPiecePerSize('g01', 28, 1);
    const el = renderMatrix();
    expect(el.querySelectorAll('.qty-cell.override').length).toBe(1);
    expect(cellInput(el, 'g01', 28).closest('td')!.classList.contains('override')).toBe(true);
  });
});

describe('QtyMatrix (US-002) 小计与总片数（缺 paired 字段 → ×1 旧口径兼容）', () => {
  it('行尾每码小计列 + 底部每裁片合计行 + 工具条总片数', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    // 行尾小计（每码）：28 = A+B = 2，30 = A+B+C = 3，通用 = C = 1
    const rowTotals = Array.from(el.querySelectorAll('.qty-rowtotal')).map((td) => td.textContent);
    expect(rowTotals).toEqual(['2', '3', '1']);
    // 底部合计（每裁片）：A=28+30=2，B=2，C=30+通用=2；末格 = 总 6
    const subtotals = Array.from(el.querySelectorAll('tfoot .qty-subtotal')).map((td) => td.textContent);
    expect(subtotals).toEqual(['2', '2', '2', '6']);
    expect(el.querySelector('[data-testid="qty-total"]')!.textContent).toBe('6');
  });

  it('改一格后全部小计即时联动', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    useQtyStore.getState().setPiecePerSize('g01', 28, 4);
    const el = renderMatrix();
    // 28 码行尾小计 = 4(A) + 1(B) = 5；缺片格（C@28）不计
    expect(el.querySelectorAll('.qty-rowtotal')[0].textContent).toBe('5');
    // A 列合计 = 4(28) + 1(30) = 5
    const subtotals = Array.from(el.querySelectorAll('tfoot .qty-subtotal')).map((td) => td.textContent);
    expect(subtotals).toEqual(['5', '2', '2', '9']);
    expect(el.querySelector('[data-testid="qty-total"]')!.textContent).toBe('9');
  });

  it('缺片格不计入小计（C@28 为 — 不加）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    // 28 码小计 = A+B = 2（C 缺片不贡献）
    expect(el.querySelectorAll('.qty-rowtotal')[0].textContent).toBe('2');
  });

  it('全 0 时红色警示显示；有量时隐藏', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    useQtyStore.getState().setRowAll('g01', [28, 30], 0);
    useQtyStore.getState().setRowAll('g02', [28, 30], 0);
    useQtyStore.getState().setRowAll('g03', [30, null], 0);
    let el = renderMatrix();
    expect(el.querySelector('[data-testid="qty-zero-warn"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="qty-total"]')!.textContent).toBe('0');
    // 恢复一格 → 警示消失
    act(() => {
      useQtyStore.getState().setPiecePerSize('g01', 28, 1);
    });
    el = container!;
    expect(el.querySelector('[data-testid="qty-zero-warn"]')).toBeNull();
  });
});

/**
 * US-004 物理片数口径 doc：三码两片型（含配对）。
 *   28: A 前片(paired) + B 单排(内片)；30: A + B；null: B。
 * 默认全 demand=1 → 物理片数：A 列 = 2 码 × 1 份 × 2 = 4；B 列 = 2+1 份 × 1 = 3。
 */
function makePairedDoc(): ParsedDoc {
  return {
    doc_id: 'paired1',
    filename: 'M1787-paired.dxf',
    sizes: [
      {
        size: 28,
        pieces: [
          makePiece({ label: 'g01', name: '前片28', ptype: '前片', paired: true }),
          makePiece({ label: 'g02', name: '单排28', ptype: '单排', paired: false }),
        ],
      },
      {
        size: 30,
        pieces: [
          makePiece({ label: 'g01', name: '前片30', ptype: '前片', paired: true }),
          makePiece({ label: 'g02', name: '单排30', ptype: '单排', paired: false }),
        ],
      },
      { size: null, pieces: [makePiece({ label: 'g02', name: '单排通用', ptype: '单排', paired: false })] },
    ],
  };
}

describe('QtyMatrix (US-004) 物理片数口径（配对片 ×2；×2 徽章已随列头简化拆除）', () => {
  it('配对片列头不再渲染「×2」徽章（口径说明收敛到总片数 title）', () => {
    useUploadStore.setState({ status: 'done', doc: makePairedDoc(), activeSize: 28 });
    const el = renderMatrix();
    const colA = el.querySelectorAll('thead th')[1];
    expect(colA.querySelector('.qty-paired-badge')).toBeNull();
    expect(el.querySelector('[data-testid="qty-paired-A"]')).toBeNull();
    // 口径说明迁到工具条总片数 title
    expect(el.querySelector<HTMLElement>('.qty-total')!.getAttribute('title')).toContain(
      '配对片型每份排左右（L+R）2 物理片',
    );
  });

  it('底部每裁片合计 = Σ demand × (paired?2:1)：A(配对,2码×1份)=4，B(内片,3份)=3', () => {
    useUploadStore.setState({ status: 'done', doc: makePairedDoc(), activeSize: 28 });
    hydrateDoc(makePairedDoc());
    const el = renderMatrix();
    const subtotals = Array.from(el.querySelectorAll('tfoot .qty-subtotal')).map((td) => td.textContent);
    expect(subtotals).toEqual(['4', '3', '7']);
  });

  it('行尾每码小计 + 工具条总片数 = 物理片数：28=(1×2)+(1×1)=3，30=3，通用=1，总 7', () => {
    useUploadStore.setState({ status: 'done', doc: makePairedDoc(), activeSize: 28 });
    hydrateDoc(makePairedDoc());
    const el = renderMatrix();
    const rowTotals = Array.from(el.querySelectorAll('.qty-rowtotal')).map((td) => td.textContent);
    expect(rowTotals).toEqual(['3', '3', '1']);
    expect(el.querySelector('[data-testid="qty-total"]')!.textContent).toBe('7');
  });

  it('改配对片 demand → 物理片数按 ×2 联动（A@28=2 → 28 码小计 3+2=5，总 9）', () => {
    const doc = makePairedDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    useQtyStore.getState().setPiecePerSize('g01', 28, 2);
    const el = renderMatrix();
    const rowTotals = Array.from(el.querySelectorAll('.qty-rowtotal')).map((td) => td.textContent);
    // 28 = A(2份×2) + B(1) = 5；30 = 3；通用 = 1
    expect(rowTotals).toEqual(['5', '3', '1']);
    // A 列合计 = 2×2(28) + 1×2(30) = 6；B 列 = 3；总 9
    const subtotals = Array.from(el.querySelectorAll('tfoot .qty-subtotal')).map((td) => td.textContent);
    expect(subtotals).toEqual(['6', '3', '9']);
  });

  it('同 label 跨码 paired 不一致时按格取值（防御：A@30 缺字段 → 该格 ×1）', () => {
    const doc: ParsedDoc = {
      doc_id: 'mixed',
      filename: 'mixed.dxf',
      sizes: [
        { size: 28, pieces: [makePiece({ label: 'g01', ptype: '前片', paired: true })] },
        { size: 30, pieces: [makePiece({ label: 'g01' })] }, // 缺 paired 字段 → ×1
      ],
    };
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    // A 列合计 = 1×2 + 1×1 = 3（按格乘数，不按列统一）
    const subtotals = Array.from(el.querySelectorAll('tfoot .qty-subtotal')).map((td) => td.textContent);
    expect(subtotals).toEqual(['3', '3']);
    expect(el.querySelector('[data-testid="qty-total"]')!.textContent).toBe('3');
    // ×2 徽章已拆：混合配对列也不渲染列级徽章
    expect(el.querySelector('[data-testid="qty-paired-A"]')).toBeNull();
  });

  it('全 0 警示不受乘数影响（配对片全 0 → 总片数 0 + 警示）', () => {
    const doc = makePairedDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    useQtyStore.getState().setRowAll('g01', [28, 30], 0);
    useQtyStore.getState().setRowAll('g02', [28, 30, null], 0);
    const el = renderMatrix();
    expect(el.querySelector('[data-testid="qty-zero-warn"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="qty-total"]')!.textContent).toBe('0');
  });
});

describe('QtyMatrix (US-002 转置) 列级整列设值（工具条整表重置已拆）', () => {
  /** 打开 A 列弹层（点列头「≡」icon）；弹层 portal 到 document.body，一律从 document 查询。 */
  function openFillPopover(el: HTMLElement): HTMLInputElement {
    act(() => {
      clickEl(el.querySelector<HTMLButtonElement>('[data-testid="qty-rowfill-g01"]')!);
    });
    return document.querySelector<HTMLInputElement>('[data-testid="qty-fill-input"]')!;
  }

  it('工具条无整表重置按钮（整表回 1 改走逐列整列设值）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    expect(el.querySelector('.qty-reset-btn')).toBeNull();
  });

  it('点 icon 开弹层：输入初值 = 当前列基准 baseValue', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    useQtyStore.getState().setRowAll('g01', [28, 30], 2); // A 列基准 2
    const el = renderMatrix();
    const input = openFillPopover(el);
    expect(input.value).toBe('2');
  });

  it('弹层 portal 到 body + fixed 居中：不在矩阵容器内（逃离 sticky 列头遮挡与滚动裁剪）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    openFillPopover(el);
    // 触发按钮留在表格内；弹层本体（含 backdrop）portal 到 body、矩阵容器内零残留
    expect(el.querySelector('.qty-fill-popover')).toBeNull();
    expect(el.querySelector('[data-testid="qty-popover-backdrop"]')).toBeNull();
    const popover = document.querySelector<HTMLElement>('.qty-fill-popover')!;
    expect(popover).not.toBeNull();
    expect(document.querySelector('[data-testid="qty-popover-backdrop"]')).not.toBeNull();
    // 定位中心 inline 化（jsdom rect 全 0 → 0px；真实浏览器为矩阵容器可视区中心）
    expect(popover.style.left).toBe('0px');
    expect(popover.style.top).toBe('0px');
  });

  it('弹层标题与 aria 为「整列设值」口径（转置后批量对象 = 该裁片全部尺码）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    openFillPopover(el);
    const popover = document.querySelector<HTMLElement>('.qty-fill-popover')!;
    expect(popover.getAttribute('aria-label')).toBe('裁片 g01 整列设值');
    expect(popover.querySelector('.qty-fill-title')!.textContent).toBe('裁片 g01 · 整列设值');
  });

  it('应用：该列整列写 setRowAll(x, labelSizes, X) + 弹层关闭，其它列不动，小计联动', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    const input = openFillPopover(el);
    act(() => {
      setInputValue(input, '3');
      clickEl(document.querySelector<HTMLButtonElement>('.qty-fill-apply')!);
    });
    const q = useQtyStore.getState().quantities;
    // A 只写实际存在的码（28/30；通用缺片码不写），baseValue 同步
    expect(q.g01).toEqual({ perSize: { '28': 3, '30': 3 }, baseValue: 3 });
    // 其它列不受影响
    expect(q.g02).toEqual({ perSize: { '28': 1, '30': 1 }, baseValue: 1 });
    expect(q.g03).toEqual({ perSize: { '30': 1, null: 1 }, baseValue: 1 });
    // 弹层关闭（backdrop + input 卸载）
    expect(document.querySelector('[data-testid="qty-fill-input"]')).toBeNull();
    // 总片数联动：A 3+3 + B 1+1 + C 1+1 = 10；整列同值 → 无特例高亮
    expect(el.querySelector('[data-testid="qty-total"]')!.textContent).toBe('10');
    expect(el.querySelectorAll('.qty-cell.override').length).toBe(0);
  });

  it('Enter 快捷应用（同点「应用」）', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    const input = openFillPopover(el);
    act(() => {
      setInputValue(input, '2');
      fireKey(input, 'Enter');
    });
    expect(useQtyStore.getState().quantities.g01).toEqual({
      perSize: { '28': 2, '30': 2 },
      baseValue: 2,
    });
    expect(document.querySelector('[data-testid="qty-fill-input"]')).toBeNull();
  });

  it('取消 / backdrop / ESC 三路关闭不写 store', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    // 取消按钮
    let input = openFillPopover(el);
    act(() => {
      setInputValue(input, '7');
      clickEl(document.querySelector<HTMLButtonElement>('.qty-fill-cancel')!);
    });
    expect(document.querySelector('[data-testid="qty-fill-input"]')).toBeNull();
    expect(useQtyStore.getState().quantities.g01.perSize['28']).toBe(1);
    // backdrop mousedown（点外关闭）
    input = openFillPopover(el);
    act(() => {
      setInputValue(input, '7');
      document.querySelector<HTMLElement>('[data-testid="qty-popover-backdrop"]')!.dispatchEvent(
        new MouseEvent('mousedown', { bubbles: true }),
      );
    });
    expect(document.querySelector('[data-testid="qty-fill-input"]')).toBeNull();
    expect(useQtyStore.getState().quantities.g01.perSize['28']).toBe(1);
    // ESC（window keydown）
    input = openFillPopover(el);
    act(() => {
      setInputValue(input, '7');
      fireKey(input, 'Escape');
    });
    expect(document.querySelector('[data-testid="qty-fill-input"]')).toBeNull();
    expect(useQtyStore.getState().quantities.g01.perSize['28']).toBe(1);
  });

  it('特例兼容（UI 路径）：整列设值后单格改 → 仅该格 .override 高亮', () => {
    const doc = makeStdDoc();
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    hydrateDoc(doc);
    const el = renderMatrix();
    const input = openFillPopover(el);
    act(() => {
      setInputValue(input, '2');
      clickEl(document.querySelector<HTMLButtonElement>('.qty-fill-apply')!);
    });
    // A 列整列 2 后，单格 A@28 改 3（聚焦 → 输入 → blur 提交）→ 仅该格特例
    const a28 = cellInput(el, 'g01', 28);
    act(() => {
      a28.focus();
    });
    act(() => {
      setInputValue(a28, '3');
      a28.blur();
    });
    expect(el.querySelectorAll('.qty-cell.override').length).toBe(1);
    expect(a28.closest('td')!.classList.contains('override')).toBe(true);
    expect(cellInput(el, 'g01', 30).closest('td')!.classList.contains('override')).toBe(false);
  });
});
