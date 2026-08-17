// US-018 PerTypeOverridesModal integration tests (>=14 cases):
//   AC: modal=null does not render DOM (no portal content)
//   AC: modal='per_type' renders overlay + modal + aria-label
//   AC: thead renders 10 ptype columns (no internal/external badges — US-019 移除内外区分)
//   AC: tbody renders 2 rows (重合 + 旋转)
//   AC: mount triggers fetch('/api/ptypes')
//   AC: fetch failure degrades to name-only (no crash, no thumbnail svg)
//   AC: fetch success renders representatives[ptype] via PiecePreviewSVG compact + 编号徽章
//   AC: columns ordered by 编号 A→J（与上传预览行序一致）；无 label 片型殿后
//   AC: thumbnail hover/aria =「编号-放大预览」不含片型名
//   AC: initial draft reads form.per_type（预填全 '0'/'0'，2026-08-17 起不再按内部片预填 10）
//   AC: editing draft does NOT call onChange immediately
//   AC: confirm calls onChange + onClose (modal closes)
//   AC: cancel does not call onChange (draft discarded)
//   AC: overlay mousedown closes (draft discarded)
//   AC: ESC closes (draft discarded)
//   AC: close button (✕) closes
//   AC: clicking thumbnail opens PtypePreviewModal (previewPtype set)

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PerTypeOverridesModal } from '../PerTypeOverridesModal';
import { PtypePreviewModal } from '../PtypePreviewModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import type { PtypesResponse } from '../../../types/ptype';
import type { PerTypeFormValue } from '../../../lib/params';
import { V03_PTYPES, MAX_OVERLAP_MM, MAX_ROTATION_TOL_DEG } from '../../../constants/v03';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
/** 当前 mock 返回的 representatives 数据（每次 fetch 创建新 Response，避免 body 被消费两次）。 */
let mockReps: PtypesResponse = { representatives: {} };

/** 含 2 个 ptype 代表裁片的响应（覆盖 layer-aware 渲染 + 编号徽章断言）。 */
const TWO_REPS: PtypesResponse = {
  representatives: {
    前片: {
      label: 'A',
      polygon: [
        [0, 0],
        [100, 0],
        [100, 60],
        [0, 60],
      ],
    },
    后片: {
      label: 'B',
      polygon: [
        [0, 0],
        [80, 0],
        [80, 80],
        [0, 80],
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

function renderModal(
  values: Record<string, PerTypeFormValue> = {},
  onChange: (next: Record<string, PerTypeFormValue>) => void = () => {},
): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <PerTypeOverridesModal values={values} onChange={onChange} />
      </StrictMode>,
    );
  });
  // 让 useEffect 内的 fetch promise 跑完（resolve/reject 微任务 flush）
  return container!;
}

async function flushFetch(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('PerTypeOverridesModal (US-018)', () => {
  it('modal=null does not render (no DOM mounted)', () => {
    renderModal();
    expect(document.body.querySelector('.per-type-overlay')).toBeNull();
  });

  it('modal=per_type renders overlay + modal + aria-label', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const overlay = document.body.querySelector('.per-type-overlay');
    const modal = document.body.querySelector('.per-type-modal');
    expect(overlay).not.toBeNull();
    expect(modal).not.toBeNull();
    expect(modal!.getAttribute('aria-label')).toContain('高级配置');
    expect(modal!.getAttribute('aria-modal')).toBe('true');
  });

  it('thead renders 10 ptype columns (no internal/external badges)', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const heads = document.body.querySelectorAll('thead .ptype-col');
    expect(heads).toHaveLength(V03_PTYPES.length);
    // 无 reps（mockReps={}）→ 全部兜底片型名，按 V03_PTYPES 顺序
    const names = Array.from(heads).map((h) => h.querySelector('.ptype-name')!.textContent);
    expect(names).toEqual(V03_PTYPES);
    // 不含内外徽章（旧 <i>内</i>）
    expect(document.body.querySelector('.ptype-name i')).toBeNull();
    expect(document.body.querySelector('.ptype-col i')).toBeNull();
  });

  it('tbody renders 2 rows (重合 + 旋转)', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const rows = document.body.querySelectorAll('tbody tr');
    expect(rows).toHaveLength(2);
    // 行头文案
    const rowHeads = Array.from(rows).map((r) => r.querySelector('.per-type-rowhead')!.textContent);
    expect(rowHeads).toContain('重合');
    expect(rowHeads).toContain('旋转');
  });

  it('mount triggers fetch("/api/ptypes")', async () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    expect(fetchSpy).toHaveBeenCalled();
    const urls = fetchSpy!.mock.calls.map((c: unknown[]) => c[0]);
    expect(urls.some((u: unknown) => String(u).includes('/api/ptypes'))).toBe(true);
  });

  it('fetch failure degrades to name-only (no crash, no thumbnail svg)', async () => {
    fetchSpy!.mockImplementation((_input: unknown) => Promise.reject(new Error('network')));
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    // 不渲染 svg.piece-preview-svg（无代表裁片）
    expect(document.body.querySelector('.ptype-thumb svg')).toBeNull();
    // 但仍有 10 列 ptype 名
    expect(document.body.querySelectorAll('.ptype-name')).toHaveLength(V03_PTYPES.length);
    // 缩略图按钮 disabled（无 rep → disabled=true）
    const thumbBtn = document.body.querySelector('.ptype-thumb') as HTMLButtonElement;
    expect(thumbBtn.disabled).toBe(true);
  });

  it('fetch success renders representatives[ptype] via PiecePreviewSVG compact', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    // 前片 / 后片 渲染 svg.piece-preview-svg；其它 ptype 无（fetch 只返这 2 个）
    const svgs = document.body.querySelectorAll('.ptype-thumb svg.piece-preview-svg');
    expect(svgs.length).toBe(2);
    // compact 模式不渲染 label text
    expect(document.body.querySelectorAll('.ptype-thumb text[data-role="label"]')).toHaveLength(0);
    // rep.label → 编号徽章（与上传预览 QtyMatrix 同款），其余列兜底片型名
    const badges = document.body.querySelectorAll('thead .qty-label-badge');
    expect(badges).toHaveLength(2);
    expect(badges[0].textContent).toBe('A');
    expect(badges[1].textContent).toBe('B');
    expect(document.body.querySelectorAll('thead .ptype-name')).toHaveLength(
      V03_PTYPES.length - 2,
    );
  });

  it('columns ordered by 编号 A→J（与上传预览行序一致）；无 label 片型殿后保持原相对序', async () => {
    // 故意打乱 label↔片型映射（腰=A、后片=B、前片=C）：列序必须按编号排，不按 V03_PTYPES 固定序
    mockReps = {
      representatives: {
        腰: { label: 'A', polygon: [[0, 0], [60, 0], [60, 40], [0, 40]] },
        后片: { label: 'B', polygon: [[0, 0], [80, 0], [80, 80], [0, 80]] },
        前片: { label: 'C', polygon: [[0, 0], [100, 0], [100, 60], [0, 60]] },
      },
    };
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    // 前 3 列编号徽章 = A/B/C（腰/后片/前片）
    const badges = Array.from(document.body.querySelectorAll('thead .qty-label-badge')).map(
      (b) => b.textContent,
    );
    expect(badges).toEqual(['A', 'B', 'C']);
    // 列头与输入列对齐：第 1 列（A=腰）正下方的重合 input 是 d-腰
    const firstCol = document.body.querySelector('thead .ptype-col')!;
    expect(firstCol.querySelector('.qty-label-badge')!.textContent).toBe('A');
    const firstRowInput = document.body.querySelector('tbody tr')!.querySelector('input')!;
    expect(firstRowInput.getAttribute('data-testid')).toBe('d-腰');
    // 无 label 的 7 个片型殿后，保持 V03_PTYPES 相对序
    const names = Array.from(document.body.querySelectorAll('thead .ptype-name')).map(
      (n) => n.textContent,
    );
    expect(names).toEqual(V03_PTYPES.filter((pt) => !['前片', '后片', '腰'].includes(pt)));
  });

  it('no reps → columns fall back to V03_PTYPES 原序（无重排）', async () => {
    mockReps = { representatives: {} };
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const heads = document.body.querySelectorAll('thead .ptype-col');
    const names = Array.from(heads).map((h) => h.querySelector('.ptype-name')!.textContent);
    expect(names).toEqual(V03_PTYPES);
  });

  it('thumbnail hover/aria =「编号-放大预览」，不含片型名', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    // 有编号：只报 A-放大预览（不出现「前片」）
    const thumb = document.body.querySelector<HTMLButtonElement>('[data-testid="ptype-thumb-前片"]')!;
    expect(thumb.title).toBe('A-放大预览');
    expect(thumb.getAttribute('aria-label')).toBe('A-放大预览');
    // 无 rep（无编号）→ 兜底片型名作标识
    const thumbFallback = document.body.querySelector<HTMLButtonElement>(
      '[data-testid="ptype-thumb-单排"]',
    )!;
    expect(thumbFallback.title).toBe('单排-放大预览');
  });

  it('initial draft prefills all 0/0 when form.per_type empty（2026-08-17 起统一默认 0）', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    // 内部片型（单排）不再预填 10，统一 '0'/'0'
    const dDanPai = document.body.querySelector<HTMLInputElement>(
      `[data-testid="d-单排"]`,
    );
    const tolDanPai = document.body.querySelector<HTMLInputElement>(
      `[data-testid="tol-单排"]`,
    );
    expect(dDanPai!.value).toBe('0');
    expect(tolDanPai!.value).toBe('0');
    // 外部片型（前片）同为 '0'/'0'
    const dQianPian = document.body.querySelector<HTMLInputElement>(`[data-testid="d-前片"]`);
    const tolQianPian = document.body.querySelector<HTMLInputElement>(`[data-testid="tol-前片"]`);
    expect(dQianPian!.value).toBe('0');
    expect(tolQianPian!.value).toBe('0');
  });

  it('initial draft preserves form.per_type non-empty values', () => {
    useControlPanelStore.getState().openModal('per_type');
    const values: Record<string, PerTypeFormValue> = {
      前片: { d: '1.5', tol: '2' },
    };
    renderModal(values);
    const dQianPian = document.body.querySelector<HTMLInputElement>(`[data-testid="d-前片"]`);
    const tolQianPian = document.body.querySelector<HTMLInputElement>(`[data-testid="tol-前片"]`);
    expect(dQianPian!.value).toBe('1.5');
    expect(tolQianPian!.value).toBe('2');
    // 未填的 ptype 仍走统一预填 '0'
    const dDanPai = document.body.querySelector<HTMLInputElement>(`[data-testid="d-单排"]`);
    expect(dDanPai!.value).toBe('0');
  });

  it('editing draft does NOT call onChange immediately', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, onChange);
    const dInput = document.body.querySelector<HTMLInputElement>(`[data-testid="d-前片"]`)!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(dInput, '2');
      dInput.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('confirm calls onChange + onClose (modal closes)', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, onChange);
    // 改一个值
    const dInput = document.body.querySelector<HTMLInputElement>(`[data-testid="d-前片"]`)!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(dInput, '2');
      dInput.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const confirm = document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!;
    act(() => confirm.click());
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as Record<string, PerTypeFormValue>;
    expect(next['前片'].d).toBe('2');
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('cancel does not call onChange (draft discarded)', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, onChange);
    // 改一个值
    const dInput = document.body.querySelector<HTMLInputElement>(`[data-testid="d-前片"]`)!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(dInput, '5');
      dInput.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const cancel = document.body.querySelector<HTMLButtonElement>('.per-type-btn-cancel')!;
    act(() => cancel.click());
    expect(onChange).not.toHaveBeenCalled();
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('overlay mousedown closes (draft discarded)', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, onChange);
    const overlay = document.body.querySelector('.per-type-overlay') as HTMLDivElement;
    act(() => {
      overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('ESC closes (draft discarded) when previewPtype is null', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, onChange);
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('ESC does NOT close modal when previewPtype is open (AC#10 双层独立)', () => {
    // 同时挂 PtypePreviewModal 模拟双层场景（生产时两者同挂于 ControlPanel/PerTypeOverrides）
    useControlPanelStore.getState().openModal('per_type');
    useControlPanelStore.getState().openPreviewPtype('前片');
    act(() => {
      root!.render(
        <StrictMode>
          <>
            <PerTypeOverridesModal values={{}} onChange={() => {}} />
            <PtypePreviewModal />
          </>
        </StrictMode>,
      );
    });
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    // 预览关闭，底层 modal 保留
    expect(useControlPanelStore.getState().previewPtype).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');
  });

  it('close button (✕) closes', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const closeBtn = document.body.querySelector<HTMLButtonElement>('.per-type-close')!;
    act(() => closeBtn.click());
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('clicking thumbnail opens PtypePreviewModal (previewPtype set)', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const thumb = document.body.querySelector<HTMLButtonElement>('[data-testid="ptype-thumb-前片"]')!;
    expect(thumb.disabled).toBe(false);
    act(() => thumb.click());
    expect(useControlPanelStore.getState().previewPtype).toBe('前片');
  });

  it('inputs carry global caps d≤10 / t≤45 (no per-ptype limits)', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const LE = '≤';
    for (const pt of V03_PTYPES) {
      const dInput = document.body.querySelector<HTMLInputElement>(`[data-testid="d-${pt}"]`);
      const tolInput = document.body.querySelector<HTMLInputElement>(`[data-testid="tol-${pt}"]`);
      // placeholder / max 均为全局固定上限，不再按片型
      expect(dInput!.placeholder).toBe(`d${LE}${MAX_OVERLAP_MM}`);
      expect(tolInput!.placeholder).toBe(`t${LE}${MAX_ROTATION_TOL_DEG}`);
      expect(dInput!.max).toBe(String(MAX_OVERLAP_MM));
      expect(tolInput!.max).toBe(String(MAX_ROTATION_TOL_DEG));
    }
  });

  it('blur clamps draft into [0, max] (d→10, tol→45)', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const dInput = document.body.querySelector<HTMLInputElement>(`[data-testid="d-前片"]`)!;
    const tolInput = document.body.querySelector<HTMLInputElement>(`[data-testid="tol-前片"]`)!;
    // 原型 setter 绕过 React value tracker（与同文件既有 input 测试同模式）；
    // React 以 focusout 委托 onBlur，故 blur 用 bubbling focusout 触发。
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(dInput, '99');
      dInput.dispatchEvent(new Event('input', { bubbles: true }));
      dInput.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
      setter.call(tolInput, '-3');
      tolInput.dispatchEvent(new Event('input', { bubbles: true }));
      tolInput.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    });
    expect(dInput.value).toBe('10');
    expect(tolInput.value).toBe('0');
  });

  it('mousedown inside modal does NOT bubble-close (modal self-click safe)', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const modal = document.body.querySelector('.per-type-modal') as HTMLDivElement;
    act(() => {
      modal.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(useControlPanelStore.getState().modal).toBe('per_type');
  });
});
