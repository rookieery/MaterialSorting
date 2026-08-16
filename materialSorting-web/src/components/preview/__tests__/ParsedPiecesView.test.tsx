// US-008 ParsedPiecesView 集成测试（卡片头 [label徽章]+只读数量(份)+svg）：
//   AC#2 渲染当前 activeSize 下的全部 pieces（grid，每片卡片含 PiecePreviewSVG + A/B/C + {qty}份）
//   AC#2 切换 activeSize 后 grid 内容跟着刷新
//   AC#2 当前码 pieces=[] 时显示「该尺码无裁片」空态
//   doc=null 时组件渲染为空（空态由 PreviewPage 兜底）
//
// 矩阵化重构 US-003 改造：
//   - 区标题「图形预览 · 码 X」随 activeSize 变化（null 码 →「通用」）
//   - 卡片头数量为只读 <span>「{qty}份」（无 button / 无弹窗交互；编辑入口在 QtyMatrix）
//   - 该码无此裁片（perSize 缺 sizeKey）时 .piece-card-qty.disabled 置灰 span
//   - .piece-card-body 点击 openZoom；role=button + tabIndex + Enter/Space
//
// 测试模式参考 UploadPanel.test.tsx + PiecePreviewSVG.test.tsx：渲染入 container，
// 通过 uploadStore.setState 驱动组件渲染，断言 DOM 结构。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ParsedPiecesView } from '../ParsedPiecesView';
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
    label: 'A',
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

function makeDoc(sizes: { size: number | null; pieces: ParsedPiece[] }[]): ParsedDoc {
  return { doc_id: 'deadbeef', filename: 'M1787.dxf', sizes };
}

function renderView(): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <ParsedPiecesView />
      </StrictMode>,
    );
  });
  return container!;
}

describe('ParsedPiecesView (US-008) AC#2 渲染结构', () => {
  it('doc=null 时渲染为空（空态由 PreviewPage 兜底）', () => {
    const el = renderView();
    expect(el.querySelector('.parsed-pieces-view')).toBeNull();
  });

  it('渲染当前 activeSize 下的全部 pieces（每片一张卡片）', () => {
    const pieces = [
      makePiece({ label: 'A', name: '前片' }),
      makePiece({ label: 'B', name: '后片' }),
      makePiece({ label: 'C', name: '腰' }),
    ];
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([
        { size: 28, pieces },
        { size: 30, pieces: [makePiece({ label: 'A', name: '前片30' })] },
      ]),
      activeSize: 28,
    });
    const el = renderView();
    const cards = el.querySelectorAll('.piece-card');
    expect(cards.length).toBe(3);
  });

  it('每片卡片含 label 徽章 + 只读数量(份) + PiecePreviewSVG（无裁片名残留）', () => {
    const pieces = [
      makePiece({ label: 'A', name: '前片' }),
      makePiece({ label: 'B', name: '后片' }),
    ];
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces }]),
      activeSize: 28,
    });
    const el = renderView();
    const cards = el.querySelectorAll('.piece-card');
    expect(cards.length).toBe(2);
    const card0 = cards[0];
    expect(card0.querySelector('.piece-card-label')!.textContent).toBe('A');
    expect(card0.querySelector('.piece-card-qty')!.textContent).toBe('0份');
    expect(card0.querySelector('svg')).not.toBeNull();
    expect(card0.querySelector('.piece-card-name')).toBeNull();
    const card1 = cards[1];
    expect(card1.querySelector('.piece-card-label')!.textContent).toBe('B');
    expect(card1.querySelector('.piece-card-qty')!.textContent).toBe('0份');
  });

  it('grid 容器含 .piece-grid class', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece()] }]),
      activeSize: 28,
    });
    const el = renderView();
    expect(el.querySelector('.piece-grid')).not.toBeNull();
  });

  it('key 用 label-name（不同片名/标签不会冲突）', () => {
    const pieces = [
      makePiece({ label: 'A', name: '前片' }),
      makePiece({ label: 'B', name: '后片' }),
      makePiece({ label: 'A', name: '腰' }),
    ];
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces }]),
      activeSize: 28,
    });
    const el = renderView();
    expect(el.querySelectorAll('.piece-card').length).toBe(3);
  });
});

// US-003 区标题：图形预览 · 码 X
describe('ParsedPiecesView (US-003) 区标题', () => {
  it('区标题显示「图形预览 · 码 28」（activeSize=28）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece()] }]),
      activeSize: 28,
    });
    const el = renderView();
    const title = el.querySelector('[data-testid="parsed-pieces-title"]')!;
    expect(title).not.toBeNull();
    expect(title.textContent).toBe('图形预览 · 码 28');
  });

  it('切 activeSize → 区标题跟随（28 → 30）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([
        { size: 28, pieces: [makePiece({ label: 'A', name: '前片28' }), makePiece({ label: 'B', name: '后片28' })] },
        { size: 30, pieces: [makePiece({ label: 'A', name: '前片30' })] },
      ]),
      activeSize: 28,
    });
    const el = renderView();
    expect(el.querySelector('[data-testid="parsed-pieces-title"]')!.textContent).toBe('图形预览 · 码 28');
    act(() => {
      useUploadStore.getState().setSize(30);
    });
    expect(el.querySelector('[data-testid="parsed-pieces-title"]')!.textContent).toBe('图形预览 · 码 30');
  });

  it('null 码（通用）→ 区标题显示「图形预览 · 码 通用」', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([
        { size: 28, pieces: [makePiece()] },
        { size: null, pieces: [makePiece({ label: 'C', name: '腰通用' })] },
      ]),
      activeSize: null,
    });
    const el = renderView();
    expect(el.querySelector('[data-testid="parsed-pieces-title"]')!.textContent).toBe('图形预览 · 码 通用');
  });

  it('activeSize 不在 doc.sizes 里（防御）→ 区标题仍渲染 + 空态', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece()] }]),
      activeSize: 99,
    });
    const el = renderView();
    expect(el.querySelector('[data-testid="parsed-pieces-title"]')!.textContent).toBe('图形预览 · 码 99');
    expect(el.querySelector('.piece-card')).toBeNull();
    expect(el.querySelector('.parsed-pieces-empty')).not.toBeNull();
  });
});

describe('ParsedPiecesView (US-008) AC#2 切码刷新', () => {
  it('切换 activeSize 后 grid 内容跟着刷新（不同码不同裁片数）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([
        { size: 28, pieces: [makePiece({ label: 'A', name: '前片28' }), makePiece({ label: 'B', name: '后片28' })] },
        { size: 30, pieces: [makePiece({ label: 'A', name: '前片30' })] },
      ]),
      activeSize: 28,
    });
    const el = renderView();
    expect(el.querySelectorAll('.piece-card').length).toBe(2);

    act(() => {
      useUploadStore.getState().setSize(30);
    });
    expect(el.querySelectorAll('.piece-card').length).toBe(1);
    expect(el.querySelector('.piece-card-qty')!.textContent).toBe('0份');
  });

  it('当前码 pieces=[] 时显示「该尺码无裁片」', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [] }]),
      activeSize: 28,
    });
    const el = renderView();
    expect(el.querySelector('.piece-card')).toBeNull();
    const empty = el.querySelector('.parsed-pieces-empty');
    expect(empty).not.toBeNull();
    expect(empty!.textContent).toContain('该尺码无裁片');
  });
});

// US-003 矩阵化重构：卡片头数量只读（值 = getPieceDisplay().qty + 「份」）
describe('ParsedPiecesView (US-003) 数量(份) 只读渲染', () => {
  it('每片数量默认 0 渲染 0份（A/B/C 三片均未配置 quantities）', () => {
    const pieces = [
      makePiece({ label: 'A', name: '前片' }),
      makePiece({ label: 'B', name: '后片' }),
      makePiece({ label: 'C', name: '腰' }),
    ];
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces }]),
      activeSize: 28,
    });
    const el = renderView();
    const qtyEls = el.querySelectorAll('.piece-card-qty');
    expect(qtyEls.length).toBe(3);
    expect(qtyEls[0].textContent).toBe('0份');
    expect(qtyEls[1].textContent).toBe('0份');
    expect(qtyEls[2].textContent).toBe('0份');
  });

  it('qty 从 qtyStore getPieceDisplay 读（per-size 显示对应码数量）', () => {
    useQtyStore.getState().setPiecePerSize('A', 28, 5);
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece({ label: 'A', name: '前片' })] }]),
      activeSize: 28,
    });
    const el = renderView();
    expect(el.querySelector('.piece-card-qty')!.textContent).toBe('5份');
  });

  it('数量为只读 <span>（无 button，点击无交互副作用）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece({ label: 'A', name: '前片' })] }]),
      activeSize: 28,
    });
    const el = renderView();
    const qty = el.querySelector('.piece-card-qty')!;
    expect(qty.tagName).toBe('SPAN');
    // 点击不触发 zoom（数量编辑入口在 QtyMatrix）
    expect(useUploadStore.getState().zoom).toBeNull();
    act(() => {
      qty.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useUploadStore.getState().zoom).toBeNull();
  });

  it('该码无此裁片（perSize 缺 sizeKey）时 .piece-card-qty.disabled 为置灰 <span>', () => {
    useQtyStore.getState().setPiecePerSize('A', 30, 7);
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([
        { size: 28, pieces: [makePiece({ label: 'A', name: '前片28' })] },
        { size: 30, pieces: [makePiece({ label: 'A', name: '前片30' })] },
      ]),
      activeSize: 28,
    });
    const el = renderView();
    const qty = el.querySelector('.piece-card-qty')!;
    expect(qty.tagName).toBe('SPAN');
    expect(qty.classList.contains('disabled')).toBe(true);
    expect(qty.textContent).toBe('0份');
    act(() => {
      useUploadStore.getState().setSize(30);
    });
    const qty30 = el.querySelector('.piece-card-qty')!;
    expect(qty30.tagName).toBe('SPAN');
    expect(qty30.classList.contains('disabled')).toBe(false);
    expect(qty30.textContent).toBe('7份');
  });
});

describe('ParsedPiecesView (US-014) 卡片图形区点击放大预览', () => {
  it('.piece-card-body 点击 openZoom(label, size)', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece({ label: 'A', name: '前片' })] }]),
      activeSize: 28,
    });
    const el = renderView();
    const body = el.querySelector('.piece-card-body')!;
    expect(useUploadStore.getState().zoom).toBeNull();
    act(() => {
      body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    const zoom = useUploadStore.getState().zoom;
    expect(zoom).not.toBeNull();
    expect(zoom!.label).toBe('A');
    expect(zoom!.size).toBe(28);
  });

  it('.piece-card-body 含 role=button + tabIndex=0（a11y）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece()] }]),
      activeSize: 28,
    });
    const el = renderView();
    const body = el.querySelector('.piece-card-body')!;
    expect(body.getAttribute('role')).toBe('button');
    expect(body.getAttribute('tabIndex')).toBe('0');
  });

  it('Enter 键触发 openZoom（键盘 a11y）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece({ label: 'A', name: '前片' })] }]),
      activeSize: 28,
    });
    const el = renderView();
    const body = el.querySelector('.piece-card-body')!;
    expect(useUploadStore.getState().zoom).toBeNull();
    act(() => {
      body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
    expect(useUploadStore.getState().zoom).not.toBeNull();
  });

  it('Space 键触发 openZoom（键盘 a11y）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece({ label: 'A', name: '前片' })] }]),
      activeSize: 28,
    });
    const el = renderView();
    const body = el.querySelector('.piece-card-body')!;
    act(() => {
      body.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    });
    expect(useUploadStore.getState().zoom).not.toBeNull();
  });
});
