// US-001 App 集成 smoke 测试：
//   AC#1 顶部 <nav class="tabbar"> + 两 Tab
//   AC#3 超排页 ControlPanel（id="start"）+ main 在 activeTab=nesting 时可见
//   AC#4 切 preview 后 nesting .page 加 .hidden（不卸载，DOM 仍在）
//   AC#4 切回 nesting 后 preview .page 加 .hidden，nesting 取消 .hidden
//   默认 activeTab=preview（首页落上传预览）
//   Tooltip 单例仍挂载在 body（US-006 不变量 #3 不破）

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { App } from '../App';
import { useUiStore } from '../store/uiStore';
import { useUploadStore } from '../store/uploadStore';
import type { ParsedDoc } from '../types/parsed';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// useSolveRun 内部 new WebSocket —— App 集成渲染时只 mount 不 start，不会触发 WS，
// 但 ControlPanel 受控 form 不发请求；为保险 stub WebSocket ctor。
class MockWS {
  static instances: MockWS[] = [];
  url: string;
  constructor(url: string) {
    this.url = url;
    MockWS.instances.push(this);
  }
  close() {}
}
vi.stubGlobal('WebSocket', MockWS);

// 构造一份「已解析」状态的 doc，让 PreviewPage 的 US-016 联动 effect
// 把 nestingEnabled 对齐到 true（与生产流程「上传→解析成功→切超排」一致）。
// 不这么做的话，App mount → PreviewPage mount → status=idle → setNestingEnabled(false)，
// 会让后续 setTab('nesting') 被 uiStore guard 静默拦截。
function makeParsedDoc(): ParsedDoc {
  return {
    doc_id: 'app-test-doc',
    filename: 'M1787.dxf',
    sizes: [{ size: 28, pieces: [{ label: 'A', name: '前片', polygon: [], internal_lines: [], notches: [], net_polygon: [], grain_line: null }] }],
  };
}

let container: HTMLDivElement | null = null;
let root: Root | null = null;
// US-018：App → ControlPanel → PerTypeOverridesModal + PtypePreviewModal 都会 fetch /api/ptypes；
// stub 防止 act warning + 真实网络调用。
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;

beforeEach(() => {
  MockWS.instances = [];
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  // US-016：uploadStore 处于 done+doc → PreviewPage 联动 setNestingEnabled(true)。
  // 这样 beforeEach 显式 setTab('nesting') 才不会被 uiStore guard 静默拦截。
  useUploadStore.getState().reset();
  useUploadStore.setState({ status: 'done', doc: makeParsedDoc() });
  useUiStore.getState().setNestingEnabled(true);
  useUiStore.getState().setTab('nesting');
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((_input: unknown) =>
    Promise.resolve(
      new Response(JSON.stringify({ representatives: {} }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  ) as unknown as MockInstance<(...args: unknown[]) => Promise<Response>>;
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
  useUiStore.getState().setNestingEnabled(false);
  useUiStore.getState().setTab('preview');
  if (fetchSpy) {
    fetchSpy.mockRestore();
    fetchSpy = null;
  }
});

function renderApp(): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  });
  return container!;
}

describe('App Tab 集成（US-001）', () => {
  it('渲染 <nav class="tabbar"> + 两个 <button class="tab">', () => {
    const el = renderApp();
    expect(el.querySelector('nav.tabbar')).not.toBeNull();
    const tabs = el.querySelectorAll('button.tab');
    expect(tabs.length).toBe(2);
    expect(tabs[0].textContent).toBe('超排');
    expect(tabs[1].textContent).toBe('上传预览');
  });

  it('activeTab=nesting：超排页可见（无 .hidden），含 ControlPanel + main', () => {
    const el = renderApp();
    const pages = el.querySelectorAll('.page');
    expect(pages.length).toBe(2);
    // nesting page 没有 .hidden
    const nestingPage = pages[0];
    expect(nestingPage.classList.contains('hidden')).toBe(false);
    // ControlPanel 内有 #start 按钮（沿用 legacy CSS id）
    expect(nestingPage.querySelector('#start')).not.toBeNull();
    // main 区域
    expect(nestingPage.querySelector('main.main')).not.toBeNull();
    // preview page 有 .hidden
    expect(pages[1].classList.contains('hidden')).toBe(true);
  });

  it('默认 activeTab=preview：首页展示上传预览页，超排页 .hidden', () => {
    // 还原到 store 默认值（beforeEach 显式设了 nesting），验证 App 对默认值的渲染。
    // 同时还原 uploadStore 到 idle（beforeEach 已设 done+doc 以保 nestingEnabled=true），
    // 此测试专门验证「未上传」空态，故需 idle 让 PreviewPage 渲染 .preview-empty。
    act(() => {
      useUploadStore.getState().reset();
      useUiStore.getState().setTab('preview');
    });
    const el = renderApp();
    const pages = el.querySelectorAll('.page');
    // preview page 可见、nesting page 隐藏
    expect(pages[0].classList.contains('hidden')).toBe(true);
    expect(pages[1].classList.contains('hidden')).toBe(false);
    // 上传预览空态卡片可见（未上传）
    expect(pages[1].querySelector('.preview-empty')).not.toBeNull();
  });

  it('切到 preview：nesting 加 .hidden（DOM 不卸载，ControlPanel 仍在），preview 取消 .hidden', () => {
    // 此测试验证「已上传」状态下切 preview 后 DOM 不卸载（ControlPanel 仍在）；
    // beforeEach 设的 done+doc 让 PreviewPage 渲染 SizeTabs+ParsedPiecesView（非 .preview-empty）。
    const el = renderApp();
    act(() => {
      useUiStore.getState().setTab('preview');
    });
    const pages = el.querySelectorAll('.page');
    expect(pages[0].classList.contains('hidden')).toBe(true);
    expect(pages[1].classList.contains('hidden')).toBe(false);
    // 关键：ControlPanel 仍在 DOM（AC#4 不卸载，求解状态保真）
    expect(pages[0].querySelector('#start')).not.toBeNull();
    expect(pages[0].querySelector('main.main')).not.toBeNull();
    // preview page 顶层容器可见（US-016 联动后已上传→显示 SizeTabs+ParsedPiecesView，
    // 不再是 .preview-empty；此处断言 .preview-page 容器存在即可证明 preview 页正常渲染）
    expect(pages[1].querySelector('.preview-page')).not.toBeNull();
  });

  it('切回 nesting：状态对称（preview .hidden，nesting 可见）', () => {
    const el = renderApp();
    act(() => {
      useUiStore.getState().setTab('preview');
    });
    act(() => {
      // nestingEnabled 在 beforeEach 已置 true，US-015 解锁闸不阻拦
      useUiStore.getState().setTab('nesting');
    });
    const pages = el.querySelectorAll('.page');
    expect(pages[0].classList.contains('hidden')).toBe(false);
    expect(pages[1].classList.contains('hidden')).toBe(true);
  });

  it('Tooltip 单例仍 Portal 到 body（US-006 不变量 #3 不破）', () => {
    renderApp();
    const tooltip = document.body.querySelector('.tooltip');
    expect(tooltip).not.toBeNull();
  });

  it('点击 preview Tab → activeTab 切换（端到端 store → UI）', () => {
    const el = renderApp();
    const tabs = el.querySelectorAll('button.tab');
    act(() => {
      tabs[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(useUiStore.getState().activeTab).toBe('preview');
    const pages = el.querySelectorAll('.page');
    expect(pages[0].classList.contains('hidden')).toBe(true);
    expect(pages[1].classList.contains('hidden')).toBe(false);
  });
});
