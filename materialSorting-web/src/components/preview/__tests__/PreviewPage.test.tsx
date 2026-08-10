// US-008 PreviewPage 集成测试：
//   AC#3 左 UploadPanel + 右（SizeTabs + ParsedPiecesView）布局
//   AC#3 未上传（doc=null）右侧显示整体空态提示
//   AC#3 已解析（status=done + doc）挂载 SizeTabs + ParsedPiecesView
//
// 测试模式参考 UploadPanel.test.tsx + App.test.tsx：渲染入 container，
// 通过 uploadStore.setState 驱动分支，断言 DOM 结构。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PreviewPage } from '../PreviewPage';
import { useUploadStore } from '../../../store/uploadStore';
import type { ParsedDoc, ParsedPiece } from '../../../types/parsed';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// UploadPanel 内 useParseDxf 仅在文件上传时才用 fetch；PreviewPage 集成渲染时不会触发，
// 但 stub 一下防止任何意外 fetch（与 App.test.tsx stub WebSocket 同防御思路）。

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
  vi.restoreAllMocks();
});

/** 构造一片：方框 100x80。 */
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

function makeDoc(): ParsedDoc {
  return {
    doc_id: 'deadbeef',
    filename: 'M1787.dxf',
    sizes: [
      { size: 28, pieces: [makePiece({ label: 'A', name: '前片28' })] },
      { size: 30, pieces: [makePiece({ label: 'A', name: '前片30' }), makePiece({ label: 'B', name: '后片30' })] },
    ],
  };
}

function renderPage(): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <PreviewPage />
      </StrictMode>,
    );
  });
  return container!;
}

describe('PreviewPage (US-008) AC#3 布局结构', () => {
  it('根 .preview-page 含左侧 UploadPanel + 右侧 .preview-main', () => {
    const el = renderPage();
    const page = el.querySelector('.preview-page');
    expect(page).not.toBeNull();
    expect(page!.querySelector('aside.upload-panel')).not.toBeNull();
    expect(page!.querySelector('.preview-main')).not.toBeNull();
  });

  it('未上传（status=idle + doc=null）右侧显示 .preview-empty 整体空态', () => {
    const el = renderPage();
    const main = el.querySelector('.preview-main');
    expect(main!.querySelector('.preview-empty')).not.toBeNull();
    // 不挂载 SizeTabs / ParsedPiecesView
    expect(main!.querySelector('.size-tabs')).toBeNull();
    expect(main!.querySelector('.parsed-pieces-view')).toBeNull();
  });

  it('uploading 中右侧仍为空态（hasParsed 仅在 done+doc 时 true）', () => {
    useUploadStore.setState({ status: 'uploading' });
    const el = renderPage();
    const main = el.querySelector('.preview-main');
    expect(main!.querySelector('.preview-empty')).not.toBeNull();
    expect(main!.querySelector('.size-tabs')).toBeNull();
  });

  it('error 时右侧仍为空态', () => {
    useUploadStore.setState({ status: 'error', error: '网络错' });
    const el = renderPage();
    const main = el.querySelector('.preview-main');
    expect(main!.querySelector('.preview-empty')).not.toBeNull();
  });
});

describe('PreviewPage (US-008) AC#3 已解析挂载主体', () => {
  it('status=done + doc 非 null → 挂载 SizeTabs + ParsedPiecesView', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    const el = renderPage();
    const main = el.querySelector('.preview-main');
    expect(main!.querySelector('.preview-empty')).toBeNull();
    expect(main!.querySelector('.size-tabs')).not.toBeNull();
    expect(main!.querySelector('.parsed-pieces-view')).not.toBeNull();
  });

  it('SizeTabs 列出 doc 全码（28/30）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    const el = renderPage();
    const chips = el.querySelectorAll('button.size-chip');
    expect(chips.length).toBe(2);
    expect(chips[0].textContent).toBe('28');
    expect(chips[1].textContent).toBe('30');
  });

  it('ParsedPiecesView 渲染当前 activeSize 下的 pieces（28→1 片）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    const el = renderPage();
    expect(el.querySelectorAll('.piece-card').length).toBe(1);
  });

  it('切 activeSize 到 30 → ParsedPiecesView 刷新到 2 片', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    const el = renderPage();
    expect(el.querySelectorAll('.piece-card').length).toBe(1);

    act(() => {
      useUploadStore.getState().setSize(30);
    });
    expect(el.querySelectorAll('.piece-card').length).toBe(2);
    const names = Array.from(el.querySelectorAll('.piece-card-name')).map((n) => n.textContent);
    expect(names).toContain('前片30');
    expect(names).toContain('后片30');
  });

  it('点击 SizeTabs chip 端到端切换 activeSize + grid 刷新', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    const el = renderPage();
    const chips = el.querySelectorAll('button.size-chip');
    act(() => {
      chips[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useUploadStore.getState().activeSize).toBe(30);
    expect(el.querySelectorAll('.piece-card').length).toBe(2);
  });
});
