// US-008 PreviewPage 集成测试（US-014 扩：模态挂载 + reset 联动 + 端到端）：
//   AC#3 左 UploadPanel + 右（SizeTabs + ParsedPiecesView）布局
//   AC#3 未上传（doc=null）右侧显示整体空态提示
//   AC#3 已解析（status=done + doc）挂载 SizeTabs + ParsedPiecesView
//
// US-014 新增：
//   - 顶层挂 <PieceQtyDialog/> + <PieceZoomModal/>（默认 store null 不渲染 DOM）
//   - 解析完成 / 重传（doc_id 变化）联动 qtyStore.hydrateDefault（每片默认 1）；
//     reset（doc→null）联动 qtyStore.resetQuantities
//   - 端到端：切码 → 点数量(片) → 切全局 + 确定 → 切回原码 → 置灰 title 含来源码
//
// US-016 新增（Tab 解锁联动）：
//   - mount idle 时 setNestingEnabled(false)
//   - done + doc → setNestingEnabled(true)
//   - error → setNestingEnabled(false)
//   - reset → setNestingEnabled(false)
//   - 重传（doc_id 变化）短暂 false（uploading）后 true（done）
//   - 关键不变量：setNestingEnabled(false) 不强制切 Tab（用户在 nesting Tab 时 reset 不切回）
//
// 测试模式参考 UploadPanel.test.tsx + App.test.tsx：渲染入 container，
// 通过 uploadStore.setState 驱动分支，断言 DOM 结构。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PreviewPage } from '../PreviewPage';
import { useUploadStore } from '../../../store/uploadStore';
import { useQtyStore } from '../../../store/qtyStore';
import { useUiStore } from '../../../store/uiStore';
import type { ParsedDoc, ParsedPiece } from '../../../types/parsed';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// UploadPanel 内 useParseDxf 仅在文件上传时才用 fetch；PreviewPage 集成渲染时不会触发，
// 但 stub 一下防止任何意外 fetch（与 App.test.tsx stub WebSocket 同防御思路）。

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  useUploadStore.getState().reset();
  useQtyStore.getState().resetQuantities();
  // US-016：重置 nestingEnabled 到默认 false（避免前一个测试 setNestingEnabled(true) 残留）
  useUiStore.getState().setNestingEnabled(false);
  useUiStore.getState().setTab('preview');
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
  document.body.innerHTML = '';
  useUploadStore.getState().reset();
  useQtyStore.getState().resetQuantities();
  useUiStore.getState().setNestingEnabled(false);
  useUiStore.getState().setTab('preview');
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

  it('切 activeSize 到 30 → ParsedPiecesView 刷新到 2 片（解析后默认 1片）', () => {
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
    const qtyTexts = Array.from(el.querySelectorAll('.piece-card-qty')).map((n) => n.textContent);
    expect(qtyTexts.length).toBe(2);
    // 解析完成后每片默认数量 1（PreviewPage mount 时 hydrateDefault）
    expect(qtyTexts).toContain('1片');
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

// US-014 模态挂载 + reset 联动 + 端到端
describe('PreviewPage (US-014) 模态挂载', () => {
  it('顶层挂 PieceQtyDialog + PieceZoomModal（默认 store null 不渲染 DOM）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    // qtyDialog=null / zoom=null → 两个模态都不渲染 DOM（Portal 到 body）
    expect(document.body.querySelector('.piece-qty-dialog-overlay')).toBeNull();
    expect(document.body.querySelector('.piece-zoom-overlay')).toBeNull();
  });

  it('qtyDialog 写入 → PieceQtyDialog 自显隐', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    act(() => {
      useUploadStore.getState().openQtyDialog('A', 28);
    });
    expect(document.body.querySelector('.piece-qty-dialog-overlay')).not.toBeNull();
  });

  it('zoom 写入 → PieceZoomModal 自显隐', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    act(() => {
      useUploadStore.getState().openZoom('A', 28);
    });
    expect(document.body.querySelector('.piece-zoom-overlay')).not.toBeNull();
  });
});

describe('PreviewPage (US-014) qtyStore 联动（hydrate 默认 1 / reset 清空）', () => {
  it('解析完成（首次上传 / 已有 doc 挂载）→ 每码每片默认数量 1', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    const map = useQtyStore.getState().quantities;
    // makeDoc：28 码 A，30 码 A+B
    expect(map.A.perSize).toEqual({ '28': 1, '30': 1 });
    expect(map.B.perSize).toEqual({ '30': 1 });
  });

  it('uploadStore.reset() 联动 qtyStore.resetQuantities（doc→null 触发）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    // 先填一些数量（包 act，触发 ParsedPiecesView re-render）
    act(() => {
      useQtyStore.getState().setPiecePerSize('A', 28, 5);
    });
    expect(Object.keys(useQtyStore.getState().quantities).length).toBeGreaterThan(0);
    // 调 reset
    act(() => {
      useUploadStore.getState().reset();
    });
    expect(useQtyStore.getState().quantities).toEqual({});
  });

  it('重传（doc_id 变化）重新 hydrate 默认 1，旧编辑被覆盖', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    act(() => {
      useQtyStore.getState().setPiecePerSize('A', 28, 5);
    });
    expect(useQtyStore.getState().quantities.A.perSize['28']).toBe(5);
    // 模拟重传：doc_id 变化（同 sizes）→ 重新 hydrate，旧编辑 5 被默认 1 覆盖
    act(() => {
      useUploadStore.setState({
        status: 'done',
        doc: { doc_id: 'newid', filename: 'M9999.dxf', sizes: makeDoc().sizes },
        activeSize: 28,
      });
    });
    const map = useQtyStore.getState().quantities;
    expect(map.A.perSize).toEqual({ '28': 1, '30': 1 });
    expect(map.B.perSize).toEqual({ '30': 1 });
  });

  it('切 activeSize 不触发 hydrate/reset（doc_id 不变，数量保留）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    act(() => {
      useQtyStore.getState().setPiecePerSize('A', 28, 5);
    });
    act(() => {
      useUploadStore.getState().setSize(30);
    });
    // 数量应保留
    expect(useQtyStore.getState().quantities.A.perSize['28']).toBe(5);
  });
});

describe('PreviewPage (US-014) 端到端', () => {
  it('解析成功 → 切码 → 点数量(片) → 切全局+确定 → 切另一码 → 对应片置灰 title 含来源码', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    const el = renderPage();
    // 切到 30 码（label A 在 30 码 pieces[0]）
    act(() => {
      useUploadStore.getState().setSize(30);
    });
    // 点 A 片数量(片) 按钮 → 弹数量弹窗
    const qtyButton = el.querySelector('.piece-card .piece-card-qty') as HTMLButtonElement;
    expect(qtyButton.tagName).toBe('BUTTON');
    act(() => {
      qtyButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    // 弹窗已显示
    expect(document.body.querySelector('.piece-qty-dialog-overlay')).not.toBeNull();
    // 切换 Switch 到「全部尺码」（global）
    const sw = document.body.querySelector('button.switch') as HTMLButtonElement;
    expect(sw.getAttribute('aria-checked')).toBe('false');
    act(() => {
      sw.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(sw.getAttribute('aria-checked')).toBe('true');
    // 点确定
    const confirm = document.body.querySelector('.qty-confirm') as HTMLButtonElement;
    act(() => {
      confirm.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    // qtyStore 已写入 global 模式（source=30）
    const q = useQtyStore.getState().quantities.A;
    expect(q.mode).toBe('global');
    expect(q.globalSource).toBe(30);
    // 弹窗已关闭
    expect(document.body.querySelector('.piece-qty-dialog-overlay')).toBeNull();
    // 切回 28 码 → A 片应置灰（disabled span + title 含「30」）
    act(() => {
      useUploadStore.getState().setSize(28);
    });
    const disabledQty = el.querySelector('.piece-card .piece-card-qty')!;
    expect(disabledQty.tagName).toBe('SPAN');
    expect(disabledQty.classList.contains('disabled')).toBe(true);
    expect(disabledQty.getAttribute('title')).toContain('30');
  });
});

// US-016 Tab 解锁联动（PreviewPage subscribe uploadStore → uiStore.setNestingEnabled）
describe('PreviewPage (US-016) Tab 解锁联动', () => {
  it('mount 时 status=idle → setNestingEnabled(false)（默认锁定）', () => {
    // mount 前先污染 nestingEnabled=true，验证 mount 时会被对齐回 false
    useUiStore.getState().setNestingEnabled(true);
    expect(useUiStore.getState().nestingEnabled).toBe(true);
    renderPage();
    expect(useUiStore.getState().nestingEnabled).toBe(false);
  });

  it('status=done + doc 非 null → setNestingEnabled(true)', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    expect(useUiStore.getState().nestingEnabled).toBe(true);
  });

  it('status=error → setNestingEnabled(false)', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    expect(useUiStore.getState().nestingEnabled).toBe(true);
    // 切 error → 锁回
    act(() => {
      useUploadStore.setState({ status: 'error', error: '解析失败' });
    });
    expect(useUiStore.getState().nestingEnabled).toBe(false);
  });

  it('uploadStore.reset() → setNestingEnabled(false)（doc→null 触发）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    expect(useUiStore.getState().nestingEnabled).toBe(true);
    act(() => {
      useUploadStore.getState().reset();
    });
    expect(useUiStore.getState().nestingEnabled).toBe(false);
  });

  it('重传（doc_id 变化）短暂 false（uploading）后 true（done）', () => {
    // 首次解析：done + doc1 → true
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    expect(useUiStore.getState().nestingEnabled).toBe(true);
    // 用户重传：status 切 uploading（doc_id 仍旧，但 status 不再 done）→ false
    act(() => {
      useUploadStore.setState({ status: 'uploading', error: null });
    });
    expect(useUiStore.getState().nestingEnabled).toBe(false);
    // 新解析完成：doc_id 变化，status=done → true
    act(() => {
      useUploadStore.setState({
        status: 'done',
        doc: { doc_id: 'newid', filename: 'M9999.dxf', sizes: makeDoc().sizes },
        activeSize: 28,
        error: null,
      });
    });
    expect(useUiStore.getState().nestingEnabled).toBe(true);
  });

  it('关键不变量：setNestingEnabled(false) 不强制切 Tab（用户在 nesting Tab 时 reset 不切回）', () => {
    // 模拟用户已成功上传并切到 nesting Tab
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setTab('nesting');
    expect(useUiStore.getState().activeTab).toBe('nesting');
    // 用户在 nesting Tab 点 reset（如重传）→ setNestingEnabled(false) 但 activeTab 不被强制切回
    act(() => {
      useUploadStore.getState().reset();
    });
    expect(useUiStore.getState().nestingEnabled).toBe(false);
    // 关键不变量：activeTab 仍是 nesting（setNestingEnabled 仅控「能否进入」，不强制切出）
    expect(useUiStore.getState().activeTab).toBe('nesting');
  });

  it('uploading 中 → setNestingEnabled(false)（mount 即对齐）', () => {
    // mount 时 status=uploading → false（无可用解析数据）
    useUploadStore.setState({ status: 'uploading' });
    useUiStore.getState().setNestingEnabled(true); // 污染
    renderPage();
    expect(useUiStore.getState().nestingEnabled).toBe(false);
  });

  it('已 done 后切 uploading（重传）→ false，再切 done → true（状态机循环）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: makeDoc(),
      activeSize: 28,
    });
    renderPage();
    expect(useUiStore.getState().nestingEnabled).toBe(true);
    // 重传 uploading
    act(() => {
      useUploadStore.setState({ status: 'uploading', error: null });
    });
    expect(useUiStore.getState().nestingEnabled).toBe(false);
    // 失败
    act(() => {
      useUploadStore.setState({ status: 'error', error: '网络错' });
    });
    expect(useUiStore.getState().nestingEnabled).toBe(false);
    // 重试成功
    act(() => {
      useUploadStore.setState({
        status: 'done',
        doc: { doc_id: 'retry', filename: 'M1787.dxf', sizes: makeDoc().sizes },
        activeSize: 28,
        error: null,
      });
    });
    expect(useUiStore.getState().nestingEnabled).toBe(true);
  });
});
