// US-018 PtypePreviewModal integration tests (>=6 cases):
//   AC: previewPtype=null does not render DOM（且不发 fetch —— 2026-08-17 起打开才 fetch）
//   AC: previewPtype + fetch success renders overlay + modal + PiecePreviewSVG (svg.piece-preview-svg)
//   AC: 每次打开重新 fetch（修复与弹窗缩略图数据不一致的旧缓存 bug）
//   AC: rep.label → 头部编号徽章；无 label 兜底片型名
//   AC: ✕ button closes
//   AC: overlay mousedown closes
//   AC: ESC closes (independent of underlying modal)
//   AC: stacked with PerTypeOverridesModal: close preview keeps底层 modal

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PtypePreviewModal } from '../PtypePreviewModal';
import { PerTypeOverridesModal } from '../PerTypeOverridesModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import type { PtypesResponse } from '../../../types/ptype';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
/** 当前 mock 返回的 representatives（每次 fetch 创建新 Response，避免 body 复用问题）。 */
let mockReps: PtypesResponse = { representatives: {} };

const REPS: PtypesResponse = {
  representatives: {
    前片: {
      label: 'g01',
      polygon: [
        [0, 0],
        [100, 0],
        [100, 60],
        [0, 60],
      ],
    },
  },
};

beforeEach(() => {
  useControlPanelStore.getState().closeModal();
  useControlPanelStore.getState().closePreviewPtype();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  mockReps = { representatives: {} };
  // 用 mockImplementation 每次 fetch 创建新 Response（StrictMode 双 mount 会调 2 次 fetch；
  // mockResolvedValue 共享同一 Response 会被首次 .json() 消费完，第二次报 "body stream already read"）。
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((_input: unknown) =>
    Promise.resolve(
      new Response(JSON.stringify(mockReps), {
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
  document.body.innerHTML = '';
  useControlPanelStore.getState().closeModal();
  useControlPanelStore.getState().closePreviewPtype();
  if (fetchSpy) {
    fetchSpy.mockRestore();
    fetchSpy = null;
  }
});

async function flushFetch(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function renderModal(): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <PtypePreviewModal />
      </StrictMode>,
    );
  });
  return container!;
}

describe('PtypePreviewModal (US-018)', () => {
  it('previewPtype=null does not render (no DOM mounted, no fetch)', async () => {
    renderModal();
    expect(document.body.querySelector('.ptype-preview-overlay')).toBeNull();
    await flushFetch();
    // 关闭态不发请求（fetch 只在打开时触发）
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('previewPtype + fetch success renders overlay + modal + PiecePreviewSVG', async () => {
    mockReps = REPS;
    useControlPanelStore.getState().openPreviewPtype('前片');
    renderModal();
    await flushFetch();
    const overlay = document.body.querySelector('.ptype-preview-overlay');
    const modal = document.body.querySelector('.ptype-preview-modal');
    expect(overlay).not.toBeNull();
    expect(modal).not.toBeNull();
    // hover/aria 统一「编号-放大预览」格式，不含片型名
    expect(modal!.getAttribute('aria-label')).toBe('g01-放大预览');
    expect(modal!.querySelector('.ptype-preview-head')!.getAttribute('title')).toBe('g01-放大预览');
    const svg = modal!.querySelector('svg.piece-preview-svg');
    expect(svg).not.toBeNull();
    // rep.label → 头部编号徽章（与上传预览同口径），不再显示片型名
    expect(modal!.querySelector('.piece-card-label')!.textContent).toBe('g01');
    expect(modal!.querySelector('.ptype-preview-name')).toBeNull();
  });

  it('refetches on every open (stale-cache bug fix: 与弹窗缩略图数据保持一致)', async () => {
    mockReps = REPS;
    useControlPanelStore.getState().openPreviewPtype('前片');
    renderModal();
    await flushFetch();
    expect(fetchSpy!.mock.calls.length).toBeGreaterThanOrEqual(1);
    // 关闭再开（换 ptype）→ 再次 fetch
    act(() => {
      useControlPanelStore.getState().closePreviewPtype();
    });
    await flushFetch();
    const callsAfterClose = fetchSpy!.mock.calls.length;
    act(() => {
      useControlPanelStore.getState().openPreviewPtype('后片');
    });
    await flushFetch();
    expect(fetchSpy!.mock.calls.length).toBeGreaterThan(callsAfterClose);
  });

  it('rep without label falls back to ptype name in head', async () => {
    // 旧 intermediate 无 label 字段 → 头部兜底片型名
    mockReps = {
      representatives: {
        前片: {
          polygon: [
            [0, 0],
            [100, 0],
            [100, 60],
            [0, 60],
          ],
        },
      },
    };
    useControlPanelStore.getState().openPreviewPtype('前片');
    renderModal();
    await flushFetch();
    const modal = document.body.querySelector('.ptype-preview-modal');
    expect(modal!.querySelector('.ptype-preview-name')!.textContent).toBe('前片');
    expect(modal!.querySelector('.piece-card-label')).toBeNull();
  });

  it('✕ button closes', async () => {
    useControlPanelStore.getState().openPreviewPtype('前片');
    renderModal();
    await flushFetch();
    const closeBtn = document.body.querySelector<HTMLButtonElement>('.ptype-preview-close')!;
    act(() => closeBtn.click());
    expect(useControlPanelStore.getState().previewPtype).toBeNull();
  });

  it('overlay mousedown closes', async () => {
    useControlPanelStore.getState().openPreviewPtype('前片');
    renderModal();
    await flushFetch();
    const overlay = document.body.querySelector('.ptype-preview-overlay') as HTMLDivElement;
    act(() => {
      overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(useControlPanelStore.getState().previewPtype).toBeNull();
  });

  it('ESC closes (independent of underlying modal)', async () => {
    useControlPanelStore.getState().openPreviewPtype('前片');
    renderModal();
    await flushFetch();
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(useControlPanelStore.getState().previewPtype).toBeNull();
  });

  it('stacked with PerTypeOverridesModal: close preview keeps 底层 modal + draft', async () => {
    mockReps = REPS;
    const onChange = vi.fn();
    // 两层都挂载（PerTypeOverrides 内含 PerTypeOverridesModal + PtypePreviewModal，
    // 但本测试直接两层并行 mount 模拟同效果）
    useControlPanelStore.getState().openModal('per_type');
    useControlPanelStore.getState().openPreviewPtype('前片');
    act(() => {
      root!.render(
        <StrictMode>
          <>
            <PerTypeOverridesModal values={{}} onChange={onChange} />
            <PtypePreviewModal />
          </>
        </StrictMode>,
      );
    });
    await flushFetch();
    // 两层 overlay 都存在
    expect(document.body.querySelector('.per-type-overlay')).not.toBeNull();
    expect(document.body.querySelector('.ptype-preview-overlay')).not.toBeNull();

    // ESC 只关放大预览，不关底层
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(useControlPanelStore.getState().previewPtype).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');
    // 底层 modal 仍在（草稿保留）
    expect(document.body.querySelector('.per-type-overlay')).not.toBeNull();
    // onChange 未被调用（草稿未确认）
    expect(onChange).not.toHaveBeenCalled();
  });

  it('representative 缺失渲染降级空态（fetch 失败 / ptype 无代表裁片）', async () => {
    fetchSpy!.mockImplementation((_input: unknown) => Promise.reject(new Error('network')));
    useControlPanelStore.getState().openPreviewPtype('腰');
    renderModal();
    await flushFetch();
    // modal 仍渲染（不崩溃），但 body 显示降级空态
    const modal = document.body.querySelector('.ptype-preview-modal');
    expect(modal).not.toBeNull();
    expect(modal!.querySelector('.ptype-preview-empty')).not.toBeNull();
    expect(modal!.querySelector('svg.piece-preview-svg')).toBeNull();
  });
});
