// US-018 PtypePreviewModal integration tests（裁片编号化重构 US-003 起：
// /api/ptypes representatives 键 = 裁片 g 码；store previewPtype→previewLabel）：
//   AC: previewLabel=null does not render DOM（且不发 fetch —— 打开才 ensureLoaded）
//   AC: previewLabel + fetch success renders overlay + modal + PiecePreviewSVG (svg.piece-preview-svg)
//   AC: 会话缓存：重开不重取（2026-08-25 起与 PerTypeOverridesModal 共享 ptypeStore，
//       失效挂点 = commit done invalidate —— 替代旧「每次打开重新 fetch」口径）
//   AC: 头部 g 码徽章（rep.label；缺 label 兜底 Record 键，键即 g 码）
//   AC: ✕ button closes
//   AC: overlay mousedown closes
//   AC: ESC closes (independent of underlying modal)
//   AC: stacked with PerTypeOverridesModal: close preview keeps底层 modal
//   AC: fetch 失败 / representative 缺失 → 降级空态（不崩溃）

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PtypePreviewModal } from '../PtypePreviewModal';
import { PerTypeOverridesModal } from '../PerTypeOverridesModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { usePtypeStore } from '../../../store/ptypeStore';
import type { ParsedPt } from '../../../types/parsed';
import type { PtypesResponse } from '../../../types/ptype';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
/** 当前 mock 返回的 representatives（每次 fetch 创建新 Response，避免 body 复用问题）。 */
let mockReps: PtypesResponse = { representatives: {} };

const SQUARE: ParsedPt[] = [
  [0, 0],
  [100, 0],
  [100, 60],
  [0, 60],
];

/** 键 = 裁片 g 码（v2 契约，rep.label 与键同值）。 */
const REPS: PtypesResponse = {
  representatives: {
    g01: { label: 'g01', polygon: SQUARE },
  },
};

beforeEach(() => {
  useControlPanelStore.getState().closeModal();
  useControlPanelStore.getState().closePreviewLabel();
  // ptypeStore 会话缓存重置：已 ready 时组件不再 fetch，后续用例的 mockReps 失效。
  usePtypeStore.getState().reset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  mockReps = { representatives: {} };
  // mockImplementation 每次 fetch 创建新 Response（StrictMode 双 mount 会调 2 次 fetch；
  // mockResolvedValue 共享同一 Response 会被首次 .json() 消费完，第二次报 body 已读）。
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
  useControlPanelStore.getState().closePreviewLabel();
  usePtypeStore.getState().reset();
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
  it('previewLabel=null does not render (no DOM mounted, no fetch)', async () => {
    renderModal();
    expect(document.body.querySelector('.ptype-preview-overlay')).toBeNull();
    await flushFetch();
    // 关闭态不发请求（fetch 只在打开时触发）
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('previewLabel + fetch success renders overlay + modal + PiecePreviewSVG', async () => {
    mockReps = REPS;
    useControlPanelStore.getState().openPreviewLabel('g01');
    renderModal();
    await flushFetch();
    const overlay = document.body.querySelector('.ptype-preview-overlay');
    const modal = document.body.querySelector('.ptype-preview-modal');
    expect(overlay).not.toBeNull();
    expect(modal).not.toBeNull();
    // hover/aria 统一「g 码-放大预览」格式
    expect(modal!.getAttribute('aria-label')).toBe('g01-放大预览');
    expect(modal!.querySelector('.ptype-preview-head')!.getAttribute('title')).toBe('g01-放大预览');
    const svg = modal!.querySelector('svg.piece-preview-svg');
    expect(svg).not.toBeNull();
    // 头部 g 码徽章（与上传预览同口径）
    expect(modal!.querySelector('.piece-card-label')!.textContent).toBe('g01');
  });

  it('会话缓存：重开不重取；invalidate（commit done）后重取（stale-cache 由失效挂点防）', async () => {
    mockReps = REPS;
    useControlPanelStore.getState().openPreviewLabel('g01');
    renderModal();
    await flushFetch();
    const callsAfterFirst = fetchSpy!.mock.calls.length;
    expect(callsAfterFirst).toBeGreaterThanOrEqual(1);
    // 关闭再开（换 g 码）→ ptypeStore 缓存命中，不发新请求
    act(() => {
      useControlPanelStore.getState().closePreviewLabel();
    });
    await flushFetch();
    act(() => {
      useControlPanelStore.getState().openPreviewLabel('g02');
    });
    await flushFetch();
    expect(fetchSpy!.mock.calls.length).toBe(callsAfterFirst);
    // commit done → invalidate → 放大层开着时重取（数据恒与底层弹窗缩略图一致：
    // 两处共享同一份缓存，而非各自每次拉）
    act(() => {
      usePtypeStore.getState().invalidate();
    });
    await flushFetch();
    expect(fetchSpy!.mock.calls.length).toBeGreaterThan(callsAfterFirst);
  });

  it('rep 缺 label 字段（旧数据）→ 头部兜底 Record 键本身（键即 g 码）', async () => {
    mockReps = {
      representatives: {
        g07: { polygon: SQUARE },
      },
    };
    useControlPanelStore.getState().openPreviewLabel('g07');
    renderModal();
    await flushFetch();
    const modal = document.body.querySelector('.ptype-preview-modal');
    expect(modal!.querySelector('.piece-card-label')!.textContent).toBe('g07');
  });

  it('✕ button closes', async () => {
    useControlPanelStore.getState().openPreviewLabel('g01');
    renderModal();
    await flushFetch();
    const closeBtn = document.body.querySelector<HTMLButtonElement>('.ptype-preview-close')!;
    act(() => closeBtn.click());
    expect(useControlPanelStore.getState().previewLabel).toBeNull();
  });

  it('overlay mousedown closes', async () => {
    useControlPanelStore.getState().openPreviewLabel('g01');
    renderModal();
    await flushFetch();
    const overlay = document.body.querySelector('.ptype-preview-overlay') as HTMLDivElement;
    act(() => {
      overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(useControlPanelStore.getState().previewLabel).toBeNull();
  });

  it('ESC closes (independent of underlying modal)', async () => {
    useControlPanelStore.getState().openPreviewLabel('g01');
    renderModal();
    await flushFetch();
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(useControlPanelStore.getState().previewLabel).toBeNull();
  });

  it('stacked with PerTypeOverridesModal: close preview keeps 底层 modal + draft', async () => {
    mockReps = REPS;
    const onChange = vi.fn();
    // 两层并行 mount：PerTypeOverridesModal（底层）+ PtypePreviewModal（上层）
    useControlPanelStore.getState().openModal('per_type');
    useControlPanelStore.getState().openPreviewLabel('g01');
    act(() => {
      root!.render(
        <StrictMode>
          <>
            <PerTypeOverridesModal
              values={{}}
              onChange={onChange}
              band={{ enabled: false, label: '' }}
              onBandChange={() => {}}
              prefix={{ enabled: false, front: '', back: '' }}
              onPrefixChange={() => {}}
              sizes={[28, 29]}
              gateMm={1980}
            />
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
    expect(useControlPanelStore.getState().previewLabel).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');
    // 底层 modal 仍在（草稿保留）
    expect(document.body.querySelector('.per-type-overlay')).not.toBeNull();
    // onChange 未被调用（草稿未确认）
    expect(onChange).not.toHaveBeenCalled();
  });

  it('representative 缺失渲染降级空态（fetch 失败 / g 码无代表裁片）', async () => {
    fetchSpy!.mockImplementation((_input: unknown) => Promise.reject(new Error('network')));
    useControlPanelStore.getState().openPreviewLabel('g09');
    renderModal();
    await flushFetch();
    // modal 仍渲染（不崩溃），但 body 显示降级空态
    const modal = document.body.querySelector('.ptype-preview-modal');
    expect(modal).not.toBeNull();
    expect(modal!.querySelector('.ptype-preview-empty')).not.toBeNull();
    expect(modal!.querySelector('svg.piece-preview-svg')).toBeNull();
  });
});
