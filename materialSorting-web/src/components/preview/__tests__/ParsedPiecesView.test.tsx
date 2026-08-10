// US-008 ParsedPiecesView 集成测试（US-014 改造：卡片头 [label徽章]+序号(数量)+svg）：
//   AC#2 渲染当前 activeSize 下的全部 pieces（grid，每片卡片含 PiecePreviewSVG + A/B/C + 序号(数量)）
//   AC#2 切换 activeSize 后 grid 内容跟着刷新
//   AC#2 当前码 pieces=[] 时显示「该尺码无裁片」空态
//   doc=null 时组件渲染为空（空态由 PreviewPage 兜底）
//
// US-014 新增：
//   - 序号 = pieces 数组 index+1（A=1, B=2, ...）
//   - 数量默认 0 渲染 序号(0)
//   - editable 时 .piece-card-qty 为 <button>，点击 openQtyDialog
//   - global 非 source 时 .piece-card-qty.disabled 为 <span>，title 含来源码
//   - .piece-card-body 点击 openZoom；role=button + tabIndex + Enter/Space
//   - .piece-card-qty stopPropagation 不冒泡到 body
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

  it('每片卡片含 label 徽章 + 序号(数量) + PiecePreviewSVG（无裁片名残留）', () => {
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
    // 第一张卡片：A + 序号(数量) 默认 1(0) + svg
    const card0 = cards[0];
    expect(card0.querySelector('.piece-card-label')!.textContent).toBe('A');
    expect(card0.querySelector('.piece-card-qty')!.textContent).toBe('1(0)');
    expect(card0.querySelector('svg')).not.toBeNull();
    // .piece-card-name 已废弃，不应存在
    expect(card0.querySelector('.piece-card-name')).toBeNull();
    // 第二张卡片：B + 2(0) + svg
    const card1 = cards[1];
    expect(card1.querySelector('.piece-card-label')!.textContent).toBe('B');
    expect(card1.querySelector('.piece-card-qty')!.textContent).toBe('2(0)');
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
    // 验证 key 不冲突：A-前片 + B-后片 + A-后片（不同 name 但 label 重复，应渲染成功）
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

    // 切到 30 码：序号重置为 1（30 码 pieces 数组 index+1）
    act(() => {
      useUploadStore.getState().setSize(30);
    });
    expect(el.querySelectorAll('.piece-card').length).toBe(1);
    expect(el.querySelector('.piece-card-qty')!.textContent).toBe('1(0)');
  });

  it('activeSize 不在 doc.sizes 里（防御）→ 显示空态', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece()] }]),
      activeSize: 99,
    });
    const el = renderView();
    expect(el.querySelector('.piece-card')).toBeNull();
    expect(el.querySelector('.parsed-pieces-empty')).not.toBeNull();
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

// US-014 卡片头序号(数量) + 双模态集成
describe('ParsedPiecesView (US-014) 序号(数量) 渲染', () => {
  it('序号 = pieces 数组 index+1（A=1, B=2, C=3）', () => {
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
    expect(qtyEls[0].textContent).toBe('1(0)');
    expect(qtyEls[1].textContent).toBe('2(0)');
    expect(qtyEls[2].textContent).toBe('3(0)');
  });

  it('qty 默认 0 渲染 序号(0)（label 未配置 quantities）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece({ label: 'A', name: '前片' })] }]),
      activeSize: 28,
    });
    const el = renderView();
    const qty = el.querySelector('.piece-card-qty')!;
    expect(qty.textContent).toBe('1(0)');
  });

  it('qty 从 qtyStore getPieceDisplay 读（per-size 模式显示对应码数量）', () => {
    useQtyStore.getState().setPiecePerSize('A', 28, 5);
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece({ label: 'A', name: '前片' })] }]),
      activeSize: 28,
    });
    const el = renderView();
    expect(el.querySelector('.piece-card-qty')!.textContent).toBe('1(5)');
  });

  it('editable 时 .piece-card-qty 为 <button>，点击 openQtyDialog', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece({ label: 'A', name: '前片' })] }]),
      activeSize: 28,
    });
    const el = renderView();
    const qty = el.querySelector('.piece-card-qty')!;
    expect(qty.tagName).toBe('BUTTON');
    expect(useUploadStore.getState().qtyDialog).toBeNull();
    act(() => {
      qty.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    const dialog = useUploadStore.getState().qtyDialog;
    expect(dialog).not.toBeNull();
    expect(dialog!.label).toBe('A');
    expect(dialog!.size).toBe(28);
  });

  it('global 非 source 时 .piece-card-qty.disabled 为 <span>，title 含来源码', () => {
    // 在 30 码切 global，看 28 码：应渲染 span.disabled + title 含「30」
    useQtyStore.getState().setPieceGlobal('A', 30, 7);
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
    // title 含来源码 30
    expect(qty.getAttribute('title')).toContain('30');
    // 显示全局值 7
    expect(qty.textContent).toBe('1(7)');
  });

  it('global source 码自身仍为 <button>（source 可编辑）', () => {
    useQtyStore.getState().setPieceGlobal('A', 30, 7);
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([
        { size: 28, pieces: [makePiece({ label: 'A', name: '前片28' })] },
        { size: 30, pieces: [makePiece({ label: 'A', name: '前片30' })] },
      ]),
      activeSize: 30,
    });
    const el = renderView();
    const qty = el.querySelector('.piece-card-qty')!;
    expect(qty.tagName).toBe('BUTTON');
    expect(qty.classList.contains('disabled')).toBe(false);
    expect(qty.textContent).toBe('1(7)');
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

  it('.piece-card-qty 点击不冒泡到 body（stopPropagation 双重防御）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc([{ size: 28, pieces: [makePiece({ label: 'A', name: '前片' })] }]),
      activeSize: 28,
    });
    const el = renderView();
    const qty = el.querySelector('.piece-card-qty') as HTMLButtonElement;
    expect(useUploadStore.getState().zoom).toBeNull();
    expect(useUploadStore.getState().qtyDialog).toBeNull();
    act(() => {
      qty.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    // 应仅触发 openQtyDialog，不触发 openZoom
    expect(useUploadStore.getState().qtyDialog).not.toBeNull();
    expect(useUploadStore.getState().zoom).toBeNull();
  });
});
