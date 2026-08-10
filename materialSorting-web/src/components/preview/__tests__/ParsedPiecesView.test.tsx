// US-008 ParsedPiecesView 集成测试：
//   AC#2 渲染当前 activeSize 下的全部 pieces（grid，每片卡片含 PiecePreviewSVG + A/B/C + 名）
//   AC#2 切换 activeSize 后 grid 内容跟着刷新
//   AC#2 当前码 pieces=[] 时显示「该尺码无裁片」空态
//   doc=null 时组件渲染为空（空态由 PreviewPage 兜底）
//
// 测试模式参考 UploadPanel.test.tsx + PiecePreviewSVG.test.tsx：渲染入 container，
// 通过 uploadStore.setState 驱动组件渲染，断言 DOM 结构。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ParsedPiecesView } from '../ParsedPiecesView';
import { useUploadStore } from '../../../store/uploadStore';
import type { ParsedDoc, ParsedPiece } from '../../../types/parsed';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  useUploadStore.getState().reset();
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

  it('每片卡片含 A/B/C 标签 + 裁片名 + PiecePreviewSVG', () => {
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
    // 第一张卡片：A + 前片 + svg
    const card0 = cards[0];
    expect(card0.querySelector('.piece-card-label')!.textContent).toBe('A');
    expect(card0.querySelector('.piece-card-name')!.textContent).toBe('前片');
    expect(card0.querySelector('svg')).not.toBeNull();
    // 第二张卡片：B + 后片 + svg
    const card1 = cards[1];
    expect(card1.querySelector('.piece-card-label')!.textContent).toBe('B');
    expect(card1.querySelector('.piece-card-name')!.textContent).toBe('后片');
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

    // 切到 30 码
    act(() => {
      useUploadStore.getState().setSize(30);
    });
    expect(el.querySelectorAll('.piece-card').length).toBe(1);
    expect(el.querySelector('.piece-card-name')!.textContent).toBe('前片30');
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
