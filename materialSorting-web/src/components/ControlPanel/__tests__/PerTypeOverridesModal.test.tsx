// US-018 PerTypeOverridesModal integration tests（裁片编号化重构 US-003 起改写：
// V03_PTYPES 固定 10 中文列已删，列集 = /api/ptypes representatives 键 ∪ values
// 已配置键 —— 全部为裁片 g 码，按 compareByLabel 数值序）：
//   AC: modal=null does not render DOM (no portal content)
//   AC: modal='per_type' renders overlay + modal + aria-label
//   AC: thead 列 = reps 键（g 码徽章）；reps 空 + values 空 → 仅行头列（0 数据列）
//   AC: tbody renders 2 rows (重合 + 旋转)
//   AC: mount triggers apiFetch('/api/ptypes')
//   AC: fetch failure degrades (no crash, 列集退回 values 键)
//   AC: fetch success renders representatives[label] via PiecePreviewSVG compact
//   AC: 列序 = compareByLabel 数值序（g01<g02<g99<g100，长度优先防字典序倒挂）
//   AC: values 已配置键与 reps 键并集（fetch 失败时保留已配置项）
//   AC: thumbnail hover/aria =「g 码-放大预览」不含任何中文片型名
//   AC: initial draft reads form.per_type（空值预填 '0'/'0'）
//   AC: editing draft does NOT call onChange immediately
//   AC: confirm calls onChange + onClose (modal closes)
//   AC: cancel does not call onChange (draft discarded)
//   AC: overlay mousedown / ESC / ✕ 关闭即保存草稿（2026-08-22，回写前全格 clamp）
//   AC: ESC closes when previewLabel null（双层独立 AC#10）
//   AC: ESC does NOT close modal when previewLabel open
//   AC: clicking thumbnail opens PtypePreviewModal (previewLabel set)
//   AC: inputs carry global caps d≤10 / t≤45
//   AC: blur clamps draft into [0, max]
//   AC: mousedown inside modal does NOT bubble-close
//
// 布局设置分区 additions（band 草稿 + 下拉）：
//   AC: 分区标题「布局设置」+ 勾选框「开启腰头成带」+ 子标题「腰头编号」渲染
//   AC: 未勾选时下拉 disabled；勾选启用；band 草稿初值从 props 读入
//   AC: 下拉值域 = reps 键动态（fetch 失败降级 values 键纯文字列表不阻塞）
//   AC: 选中 g 码有 rep → 成带预览缩略（POST /api/band-preview；BandPreviewSVG 尺码
//       着色 + payload 同源断言；失败 → 可读错误文案前置；点击开 band-zoom 第三层
//       放大，ESC 独立不级联 —— 2026-08-24 替换原「原始裁片 80×80 缩略」）
//   AC: confirm 同时回写 per_type + band；取消丢弃 band 草稿（遮罩/ESC 同 confirm
//     回写 —— 关闭即保存）

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PerTypeOverridesModal, type BandFormValue, type PrefixFormValue } from '../PerTypeOverridesModal';
import { PtypePreviewModal } from '../PtypePreviewModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { usePtypeStore } from '../../../store/ptypeStore';
import { useQtyStore } from '../../../store/qtyStore';
import { useUploadStore } from '../../../store/uploadStore';
import type { BandPreviewResponse, PrefixPreviewResponse } from '../../../types/band';
import type { ParsedDoc, ParsedPiece } from '../../../types/parsed';
import type { PtypesResponse } from '../../../types/ptype';
import type { PerTypeFormValue } from '../../../lib/params';
import { MAX_OVERLAP_MM, MAX_ROTATION_TOL_DEG } from '../../../constants/v03';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
/** 当前 mock 返回的 representatives 数据（每次 fetch 创建新 Response，避免 body 被消费两次）。 */
let mockReps: PtypesResponse = { representatives: {} };

/** 含 2 个 g 码代表裁片的响应（键 = g 码，rep.label 与键同值）。 */
const TWO_REPS: PtypesResponse = {
  representatives: {
    g01: {
      label: 'g01',
      polygon: [
        [0, 0],
        [100, 0],
        [100, 60],
        [0, 60],
      ],
    },
    g02: {
      label: 'g02',
      polygon: [
        [0, 0],
        [80, 0],
        [80, 80],
        [0, 80],
      ],
    },
  },
};

/** 成带预览 ok 响应（2 成员 + 组合片轮廓，矩形合成几何）。 */
const BAND_OK: BandPreviewResponse = {
  ok: true,
  label: 'g01',
  fill_pct: 78.5,
  bbox: { width_mm: 1200, height_mm: 300 },
  n_members: 2,
  members: [
    {
      pid: 'g01_28',
      size: 28,
      color: '#1f77b4',
      polygon: [
        [0, 0],
        [600, 0],
        [600, 150],
        [0, 150],
      ],
    },
    {
      pid: 'g01_29',
      size: 29,
      color: '#ff7f0e',
      polygon: [
        [0, 150],
        [600, 150],
        [600, 300],
        [0, 300],
      ],
    },
  ],
  outline: [
    [0, 0],
    [1200, 0],
    [1200, 300],
    [0, 300],
  ],
};

/** 当前 mock 返回的成带预览数据（按 URL 路由分发，见 beforeEach）。 */
let mockBandPreview: BandPreviewResponse = BAND_OK;

/** 前缀组合预览 ok 响应（4 成员同码竖排：g02×2 + g03×2 + 组合片轮廓，矩形合成）。 */
const PREFIX_OK: PrefixPreviewResponse = {
  ok: true,
  front: 'g02',
  back: 'g03',
  size: 28,
  fill_pct: 83.3,
  bbox: { width_mm: 320, height_mm: 1360 },
  n_members: 4,
  members: [
    { pid: 'g02_28', size: 28, color: '#1f77b4', tag: 'g02',
      polygon: [[0, 0], [300, 0], [300, 350], [0, 350]] },
    { pid: 'g03_28', size: 28, color: '#1f77b4', tag: 'g03',
      polygon: [[0, 350], [320, 350], [320, 680], [0, 680]] },
    { pid: 'g02_28', size: 28, color: '#1f77b4', tag: 'g02',
      polygon: [[0, 680], [300, 680], [300, 1030], [0, 1030]] },
    { pid: 'g03_28', size: 28, color: '#1f77b4', tag: 'g03',
      polygon: [[0, 1030], [320, 1030], [320, 1360], [0, 1360]] },
  ],
  outline: [[0, 0], [320, 0], [320, 1360], [0, 1360]],
};

/** 当前 mock 返回的前缀预览数据（按 URL 路由分发，见 beforeEach）。 */
let mockPrefixPreview: PrefixPreviewResponse = PREFIX_OK;

beforeEach(() => {
  useControlPanelStore.getState().closeModal();
  useControlPanelStore.getState().closePreviewLabel();
  // US-004：prefix 默认预选（uploadStore.doc 面积最大两片）与资格码预检（qtyStore）
  // 都读 store —— beforeEach 重置保证各用例隔离（band 用例不依赖两 store 默认态）。
  // ptypeStore 会话缓存同款重置：representatives 已 ready 时组件不再 fetch，后续
  // 用例设置的 mockReps 会失效（2026-08-25 缓存化改造）。
  useUploadStore.getState().reset();
  useQtyStore.getState().resetQuantities();
  usePtypeStore.getState().reset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  mockReps = { representatives: {} };
  mockBandPreview = BAND_OK;
  mockPrefixPreview = PREFIX_OK;
  // 用 mockImplementation 每次 fetch 创建新 Response（StrictMode 双 mount 会调 2 次 fetch；
  // mockResolvedValue 共享同一 Response 会被首次 .json() 消费完，第二次报 body 已读）。
  // 2026-08-24 起按 URL 路由分发：/api/band-preview（成带预览 POST）↔
  // /api/prefix-preview（前缀组合预览 POST，2026-08-25）↔ 其余（/api/ptypes）。
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input: unknown) => {
    const url = typeof input === 'string' ? input : String((input as Request)?.url ?? input);
    const body = url.includes('/api/band-preview')
      ? mockBandPreview
      : url.includes('/api/prefix-preview')
        ? mockPrefixPreview
        : mockReps;
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  }) as unknown as MockInstance<(...args: unknown[]) => Promise<Response>>;
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
  useUploadStore.getState().reset();
  useQtyStore.getState().resetQuantities();
  usePtypeStore.getState().reset();
  if (fetchSpy) {
    fetchSpy.mockRestore();
    fetchSpy = null;
  }
});

function renderModal(
  values: Record<string, PerTypeFormValue> = {},
  onChange: (next: Record<string, PerTypeFormValue>) => void = () => {},
  opts: {
    band?: BandFormValue;
    onBandChange?: (next: BandFormValue) => void;
    prefix?: PrefixFormValue;
    onPrefixChange?: (next: PrefixFormValue) => void;
    sizes?: number[];
    gateMm?: number;
  } = {},
): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <PerTypeOverridesModal
          values={values}
          onChange={onChange}
          band={opts.band ?? { enabled: false, label: '' }}
          onBandChange={opts.onBandChange ?? (() => {})}
          prefix={opts.prefix ?? { enabled: false, front: '', back: '' }}
          onPrefixChange={opts.onPrefixChange ?? (() => {})}
          sizes={opts.sizes ?? [28, 29]}
          gateMm={opts.gateMm ?? 1980}
        />
      </StrictMode>,
    );
  });
  return container!;
}

async function flushFetch(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

/** React 受控 input 设值（native setter + input event，AGENTS.md US-004 模式）。 */
function setInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

/** 勾选 band → 选 g 码（native setter + change）。 */
function enableAndSelect(label: string): void {
  const check = document.body.querySelector<HTMLInputElement>('[data-testid="band-enabled"]')!;
  act(() => check.click());
  selectLabel(label);
}

/** 仅切换下拉 g 码（已勾选场景）。 */
function selectLabel(label: string): void {
  const select = document.body.querySelector<HTMLSelectElement>('[data-testid="band-label-select"]')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(select, label);
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

describe('PerTypeOverridesModal (US-018 / US-003 g 码列)', () => {
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
    // 2026-08-22 标题改名「每裁片覆盖」→「设置算法参数」
    expect(modal!.getAttribute('aria-label')).toBe('高级配置：设置算法参数');
    expect(modal!.querySelector('.per-type-title')!.textContent).toBe('高级配置：设置算法参数');
    expect(modal!.getAttribute('aria-modal')).toBe('true');
  });

  it('thead 列 = reps 键（g 码徽章恒渲染，不再有 .ptype-name 兜底名）', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const heads = document.body.querySelectorAll('thead .ptype-col');
    expect(heads).toHaveLength(2);
    const badges = Array.from(heads).map((h) => h.querySelector('.qty-label-badge')!.textContent);
    expect(badges).toEqual(['g01', 'g02']);
    // 旧中文片型名列头类名零残留
    expect(document.body.querySelector('.ptype-name')).toBeNull();
  });

  it('reps 空 + values 空 → 仅行头列（0 数据列，不阻塞）', async () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    expect(document.body.querySelectorAll('thead .ptype-col')).toHaveLength(0);
    // 行头仍在（裁片）
    expect(document.body.querySelector('thead .per-type-rowhead')!.textContent).toBe('裁片');
    expect(document.body.querySelectorAll('tbody tr')).toHaveLength(2);
  });

  it('tbody renders 2 rows (重合 + 旋转)', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const rows = document.body.querySelectorAll('tbody tr');
    expect(rows).toHaveLength(2);
    const rowHeads = Array.from(rows).map((r) => r.querySelector('.per-type-rowhead')!.textContent);
    expect(rowHeads).toContain('重合');
    expect(rowHeads).toContain('旋转');
  });

  it('mount triggers apiFetch("/api/ptypes")', async () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    expect(fetchSpy).toHaveBeenCalled();
    const urls = fetchSpy!.mock.calls.map((c: unknown[]) => c[0]);
    expect(urls.some((u: unknown) => String(u).includes('/api/ptypes'))).toBe(true);
  });

  it('会话缓存：重开弹窗不重取（缓存命中零请求）；invalidate（commit done）后重取', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const callsAfterFirst = fetchSpy!.mock.calls.length;
    expect(callsAfterFirst).toBeGreaterThanOrEqual(1);
    expect(document.body.querySelectorAll('.ptype-thumb svg.piece-preview-svg').length).toBe(2);

    // 关闭再开 → ptypeStore 缓存命中：不发新请求，缩略图直接渲染（无「…」闪烁）
    act(() => {
      useControlPanelStore.getState().closeModal();
    });
    useControlPanelStore.getState().openModal('per_type');
    // renderModal 用同一 root 重渲染；modal 关闭时 Inner 卸载，重开 = remount
    renderModal();
    await flushFetch();
    expect(fetchSpy!.mock.calls.length).toBe(callsAfterFirst);
    expect(document.body.querySelectorAll('.ptype-thumb svg.piece-preview-svg').length).toBe(2);

    // commit done → invalidate（status idle，representatives 保留）→ 弹窗开着时
    // 订阅 idle 的 effect 重取（无感刷新路径）
    act(() => {
      usePtypeStore.getState().invalidate();
    });
    await flushFetch();
    expect(fetchSpy!.mock.calls.length).toBeGreaterThan(callsAfterFirst);
  });

  it('fetch failure degrades (no crash, 列集退回 values 已配置键)', async () => {
    fetchSpy!.mockImplementation((_input: unknown) => Promise.reject(new Error('network')));
    useControlPanelStore.getState().openModal('per_type');
    const values: Record<string, PerTypeFormValue> = {
      g05: { d: '2', tol: '3' },
    };
    renderModal(values);
    await flushFetch();
    // fetch 失败 → reps 空 → 仅 values 键 g05 列保留，可继续配置（不阻塞）
    const heads = document.body.querySelectorAll('thead .ptype-col');
    expect(heads).toHaveLength(1);
    expect(heads[0].querySelector('.qty-label-badge')!.textContent).toBe('g05');
    // 无代表裁片 → 不渲染缩略图 svg、按钮 disabled
    expect(document.body.querySelector('.ptype-thumb svg')).toBeNull();
    const thumbBtn = document.body.querySelector('.ptype-thumb') as HTMLButtonElement;
    expect(thumbBtn.disabled).toBe(true);
  });

  it('fetch success renders representatives[label] via PiecePreviewSVG compact', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    // g01 / g02 各渲染 svg.piece-preview-svg
    const svgs = document.body.querySelectorAll('.ptype-thumb svg.piece-preview-svg');
    expect(svgs.length).toBe(2);
    // compact 模式不渲染 label text
    expect(document.body.querySelectorAll('.ptype-thumb text[data-role="label"]')).toHaveLength(0);
  });

  it('columns ordered by compareByLabel 数值序（g99 < g100，长度优先防字典序倒挂）', async () => {
    // 故意乱序插入 + 含三位 g 码：字典序会把 g100 排在 g99 前，必须长度优先
    mockReps = {
      representatives: {
        g100: { label: 'g100', polygon: [[0, 0], [60, 0], [60, 40], [0, 40]] },
        g02: { label: 'g02', polygon: [[0, 0], [80, 0], [80, 80], [0, 80]] },
        g99: { label: 'g99', polygon: [[0, 0], [100, 0], [100, 60], [0, 60]] },
      },
    };
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const badges = Array.from(document.body.querySelectorAll('thead .qty-label-badge')).map(
      (b) => b.textContent,
    );
    expect(badges).toEqual(['g02', 'g99', 'g100']);
    // 列头与输入列对齐：第 1 列（g02）正下方的重合 input 是 d-g02
    const firstRowInput = document.body.querySelector('tbody tr')!.querySelector('input')!;
    expect(firstRowInput.getAttribute('data-testid')).toBe('d-g02');
  });

  it('values 已配置键并入列集（reps 无该 g 码也渲染，fetch 失败时保留已配置项）', async () => {
    mockReps = {
      representatives: {
        g01: { label: 'g01', polygon: [[0, 0], [100, 0], [100, 60], [0, 60]] },
      },
    };
    useControlPanelStore.getState().openModal('per_type');
    const values: Record<string, PerTypeFormValue> = {
      g05: { d: '1', tol: '2' },
    };
    renderModal(values);
    await flushFetch();
    const badges = Array.from(document.body.querySelectorAll('thead .qty-label-badge')).map(
      (b) => b.textContent,
    );
    // 并集排序：g01（reps）+ g05（values）
    expect(badges).toEqual(['g01', 'g05']);
    // g05 无 rep → 缩略图 disabled；g01 有 rep → 可点击
    expect(
      (document.body.querySelector('[data-testid="ptype-thumb-g05"]') as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (document.body.querySelector('[data-testid="ptype-thumb-g01"]') as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it('thumbnail hover/aria =「g 码-放大预览」不含任何中文片型名', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const thumb = document.body.querySelector<HTMLButtonElement>('[data-testid="ptype-thumb-g01"]')!;
    expect(thumb.title).toBe('g01-放大预览');
    expect(thumb.getAttribute('aria-label')).toBe('g01-放大预览');
    expect(thumb.title).not.toContain('前片');
  });

  it('initial draft prefills 0/0 for empty form.per_type values', () => {
    useControlPanelStore.getState().openModal('per_type');
    const values: Record<string, PerTypeFormValue> = {
      g01: { d: '', tol: '' },
    };
    renderModal(values);
    const d = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01"]');
    const tol = document.body.querySelector<HTMLInputElement>('[data-testid="tol-g01"]');
    expect(d!.value).toBe('0');
    expect(tol!.value).toBe('0');
  });

  it('initial draft preserves form.per_type non-empty values', () => {
    useControlPanelStore.getState().openModal('per_type');
    const values: Record<string, PerTypeFormValue> = {
      g01: { d: '1.5', tol: '2' },
    };
    renderModal(values);
    const d = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01"]');
    const tol = document.body.querySelector<HTMLInputElement>('[data-testid="tol-g01"]');
    expect(d!.value).toBe('1.5');
    expect(tol!.value).toBe('2');
  });

  it('editing draft does NOT call onChange immediately', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    const values: Record<string, PerTypeFormValue> = {
      g01: { d: '0', tol: '0' },
    };
    renderModal(values, onChange);
    const dInput = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01"]')!;
    act(() => {
      setInputValue(dInput, '2');
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('confirm calls onChange + onClose (modal closes)', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    const values: Record<string, PerTypeFormValue> = {
      g01: { d: '0', tol: '0' },
    };
    renderModal(values, onChange);
    const dInput = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01"]')!;
    act(() => {
      setInputValue(dInput, '2');
    });
    const confirm = document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!;
    act(() => confirm.click());
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as Record<string, PerTypeFormValue>;
    expect(next['g01'].d).toBe('2');
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('cancel does not call onChange (draft discarded)', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    const values: Record<string, PerTypeFormValue> = {
      g01: { d: '0', tol: '0' },
    };
    renderModal(values, onChange);
    const dInput = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01"]')!;
    act(() => {
      setInputValue(dInput, '5');
    });
    const cancel = document.body.querySelector<HTMLButtonElement>('.per-type-btn-cancel')!;
    act(() => cancel.click());
    expect(onChange).not.toHaveBeenCalled();
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('overlay mousedown saves draft + closes (关闭即保存)', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g01: { d: '0', tol: '0' } }, onChange);
    const dInput = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01"]')!;
    act(() => {
      setInputValue(dInput, '2.5');
    });
    const overlay = document.body.querySelector('.per-type-overlay') as HTMLDivElement;
    act(() => {
      overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect((onChange.mock.calls[0][0] as Record<string, PerTypeFormValue>)['g01'].d)
      .toBe('2.5');
  });

  it('overlay mousedown 保存路径先 clamp 未规整值（mousedown 先于 blur）', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g01: { d: '0', tol: '0' } }, onChange);
    const dInput = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01"]')!;
    const tolInput = document.body.querySelector<HTMLInputElement>('[data-testid="tol-g01"]')!;
    act(() => {
      setInputValue(dInput, '99');      // 超 MAX_OVERLAP_MM，未经 blur 规整
      setInputValue(tolInput, '99');    // 超 MAX_ROTATION_TOL_DEG
    });
    const overlay = document.body.querySelector('.per-type-overlay') as HTMLDivElement;
    act(() => {
      overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    const next = onChange.mock.calls[0][0] as Record<string, PerTypeFormValue>;
    expect(next['g01'].d).toBe(String(MAX_OVERLAP_MM));       // '10'
    expect(next['g01'].tol).toBe(String(MAX_ROTATION_TOL_DEG)); // '45'
  });

  it('ESC saves draft + closes when previewLabel is null (关闭即保存)', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g01: { d: '0', tol: '0' } }, onChange);
    const dInput = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01"]')!;
    act(() => {
      setInputValue(dInput, '3');
    });
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect((onChange.mock.calls[0][0] as Record<string, PerTypeFormValue>)['g01'].d)
      .toBe('3');
  });

  it('ESC does NOT close modal when previewLabel is open (AC#10 双层独立)', () => {
    // 同时挂 PtypePreviewModal 模拟双层场景（生产时两者同挂于 ControlPanel）
    useControlPanelStore.getState().openModal('per_type');
    useControlPanelStore.getState().openPreviewLabel('g01');
    act(() => {
      root!.render(
        <StrictMode>
          <>
            <PerTypeOverridesModal
              values={{}}
              onChange={() => {}}
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
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    // 预览关闭，底层 modal 保留
    expect(useControlPanelStore.getState().previewLabel).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');
  });

  it('close button (✕) saves draft + closes (关闭即保存)', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g01: { d: '0', tol: '0' } }, onChange);
    const dInput = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01"]')!;
    act(() => {
      setInputValue(dInput, '4');
    });
    const closeBtn = document.body.querySelector<HTMLButtonElement>('.per-type-close')!;
    act(() => closeBtn.click());
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect((onChange.mock.calls[0][0] as Record<string, PerTypeFormValue>)['g01'].d)
      .toBe('4');
  });

  it('clicking thumbnail opens PtypePreviewModal (previewLabel set)', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const thumb = document.body.querySelector<HTMLButtonElement>('[data-testid="ptype-thumb-g01"]')!;
    expect(thumb.disabled).toBe(false);
    act(() => thumb.click());
    expect(useControlPanelStore.getState().previewLabel).toBe('g01');
  });

  it('inputs carry global caps d≤10 / t≤45', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const LE = '≤';
    for (const label of ['g01', 'g02']) {
      const dInput = document.body.querySelector<HTMLInputElement>(`[data-testid="d-${label}"]`);
      const tolInput = document.body.querySelector<HTMLInputElement>(`[data-testid="tol-${label}"]`);
      expect(dInput!.placeholder).toBe(`d${LE}${MAX_OVERLAP_MM}`);
      expect(tolInput!.placeholder).toBe(`t${LE}${MAX_ROTATION_TOL_DEG}`);
      expect(dInput!.max).toBe(String(MAX_OVERLAP_MM));
      expect(tolInput!.max).toBe(String(MAX_ROTATION_TOL_DEG));
      // aria 报 g 码
      expect(dInput!.getAttribute('aria-label')).toBe(`裁片 ${label} 重合`);
      expect(tolInput!.getAttribute('aria-label')).toBe(`裁片 ${label} 旋转`);
    }
  });

  it('blur clamps draft into [0, max] (d→10, tol→0)', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const dInput = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01"]')!;
    const tolInput = document.body.querySelector<HTMLInputElement>('[data-testid="tol-g01"]')!;
    // React 以 focusout 委托 onBlur，故用 bubbling focusout 触发
    act(() => {
      setInputValue(dInput, '99');
      dInput.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
      setInputValue(tolInput, '-3');
      tolInput.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    });
    expect(dInput.value).toBe('10');
    expect(tolInput.value).toBe('0');
  });

  it('reps 到位的新 g 码（draft 无键）渲染空串 = 继承默认 0（placeholder 提示）', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal(); // values={} → draft 无 g01/g02 键
    await flushFetch();
    const dG02 = document.body.querySelector<HTMLInputElement>('[data-testid="d-g02"]')!;
    // 空串 + placeholder（不预填 '0'，空 = 继承同 0）
    expect(dG02.value).toBe('');
    expect(dG02.placeholder).toBe(`d≤${MAX_OVERLAP_MM}`);
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

describe('PerTypeOverridesModal 布局设置分区', () => {
  it('分区渲染：标题「布局设置」+ 勾选「开启腰头成带」+ 子标题「腰头编号」+ 下拉', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const band = document.body.querySelector('[data-testid="per-type-band"]')!;
    expect(band).not.toBeNull();
    expect(band.querySelector('.per-type-band-title')!.textContent).toBe('布局设置');
    expect(band.querySelector('.per-type-band-check')!.textContent).toContain('开启腰头成带');
    expect(band.querySelector('.per-type-band-subhead')!.textContent).toBe('腰头编号');
    expect(document.body.querySelector('[data-testid="band-label-select"]')).not.toBeNull();
  });

  it('裁片设置分区标题（2026-08-22）：裁片表格上方「裁片设置」，与「布局设置」同款类名', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const title = document.body.querySelector('[data-testid="per-type-table-title"]')!;
    expect(title).not.toBeNull();
    // 同款 .per-type-band-title（12px + #2ea06c 左缘竖条），视觉与「布局设置」一致
    expect(title.className).toContain('per-type-band-title');
    expect(title.textContent).toBe('裁片设置');
    // 位于 band 分区之后、表格容器之前（DOM 顺序断言）
    const band = document.body.querySelector('[data-testid="per-type-band"]')!;
    const tableWrap = document.body.querySelector('.per-type-table-wrap')!;
    expect(band.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(title.compareDocumentPosition(tableWrap) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('未勾选时下拉 disabled；band 草稿初值从 props 读入（勾选+label 预选）', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, {
      band: { enabled: true, label: 'g01' },
    });
    const select = document.body.querySelector<HTMLSelectElement>('[data-testid="band-label-select"]')!;
    // props band.enabled=true → 下拉启用且初值 = props label
    expect(select.disabled).toBe(false);
    expect(select.value).toBe('g01');
    expect(
      document.body.querySelector<HTMLInputElement>('[data-testid="band-enabled"]')!.checked,
    ).toBe(true);
    // 反向：默认（未勾选）→ disabled（见下一用例路径）
  });

  it('未勾选（默认）→ 下拉 disabled；勾选后启用', async () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const select = document.body.querySelector<HTMLSelectElement>('[data-testid="band-label-select"]')!;
    expect(select.disabled).toBe(true);
    await flushFetch();
    // 勾选 → 下拉启用
    const check = document.body.querySelector<HTMLInputElement>('[data-testid="band-enabled"]')!;
    act(() => check.click());
    expect(select.disabled).toBe(false);
  });

  it('下拉值域 = reps 键动态（fetch 失败降级 values 键纯文字列表不阻塞）', async () => {
    // fetch 失败路径：reps 空 → 值域退回 values 已配置键（纯文字 option，无缩略图）
    fetchSpy!.mockImplementation((_input: unknown) => Promise.reject(new Error('network')));
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g05: { d: '1', tol: '1' } });
    await flushFetch();
    // 勾选后下拉可用（fetch 失败不阻塞选择）
    const check = document.body.querySelector<HTMLInputElement>('[data-testid="band-enabled"]')!;
    act(() => check.click());
    const select = document.body.querySelector<HTMLSelectElement>('[data-testid="band-label-select"]')!;
    expect(select.disabled).toBe(false);
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toEqual(['', 'g05']);   // '' = 请选择… 占位；值域 = values 已配置键
    // reps 成功路径（另行断言，见下用例）值域 = reps ∪ values
  });

  it('confirm 同时回写 per_type + band；遮罩关闭同样回写 band 草稿（关闭即保存）', async () => {
    const onChange = vi.fn();
    const onBandChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g01: { d: '0', tol: '0' } }, onChange, { onBandChange });
    enableAndSelect('g01');
    const confirm = document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!;
    act(() => confirm.click());
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onBandChange).toHaveBeenCalledTimes(1);
    expect(onBandChange).toHaveBeenCalledWith({ enabled: true, label: 'g01' });
    expect(useControlPanelStore.getState().modal).toBeNull();

    // 遮罩路径：重新打开 → 勾选并选码 → 遮罩 mousedown → band 草稿同样回写
    // （values 带 g02 键保证下拉 option 在场）。
    const onBandChange2 = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g02: { d: '0', tol: '0' } }, () => {}, { onBandChange: onBandChange2 });
    await flushFetch();
    enableAndSelect('g02');
    const overlay = document.body.querySelector('.per-type-overlay') as HTMLDivElement;
    act(() => {
      overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(onBandChange2).toHaveBeenCalledWith({ enabled: true, label: 'g02' });
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('取消丢弃 band 草稿（onBandChange 不调用）', () => {
    const onBandChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, { onBandChange });
    enableAndSelect('g01');
    const cancel = document.body.querySelector<HTMLButtonElement>('.per-type-btn-cancel')!;
    act(() => cancel.click());
    expect(onBandChange).not.toHaveBeenCalled();
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('选中 g 码 → 成带预览缩略（POST /api/band-preview payload 同源）+ 徽章，点击开 band-zoom（第三层）', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    // 未选 → 无缩略图
    expect(document.body.querySelector('.per-type-band-thumb')).toBeNull();
    enableAndSelect('g01');
    // loading 占位先渲染（POST 发出）
    expect(document.body.querySelector('[data-testid="band-thumb-loading"]')).not.toBeNull();
    await flushFetch();
    const thumb = document.body.querySelector<HTMLButtonElement>('[data-testid="band-thumb-g01"]')!;
    expect(thumb).not.toBeNull();
    // 2026-08-24：成带形态预览（BandPreviewSVG 尺码着色）替换原始裁片 PiecePreviewSVG
    expect(thumb.querySelector('svg.band-preview-svg')).not.toBeNull();
    expect(thumb.querySelector('[data-role="band-member"]')).not.toBeNull();
    expect(thumb.querySelector('.qty-label-badge')!.textContent).toBe('g01');
    expect(thumb.title).toBe('g01-成带预览放大');
    // POST payload 与 WS StartPayload 同源字段（band/sizes/gate_mm）
    const call = fetchSpy!.mock.calls.find((c) => String(c[0]).includes('/api/band-preview'))!;
    const init = call[1] as RequestInit;
    expect(init.method).toBe('POST');
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.band).toEqual({ enabled: true, label: 'g01' });
    expect(body.sizes).toEqual([28, 29]);
    expect(body.gate_mm).toBe(1980);
    // 点击 → band-zoom 第三层放大（previewLabel 不动 —— 原始裁片放大已被替换）
    act(() => thumb.click());
    expect(document.body.querySelector('[data-testid="band-zoom-overlay"]')).not.toBeNull();
    expect(useControlPanelStore.getState().previewLabel).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');   // 底层保留
    // 放大层含统计行（填充率 / 带宽×高 / 片数）+ 尺码标注
    const zoomBody = document.body.querySelector('.band-zoom-body')!;
    expect(zoomBody.querySelector('[data-role="band-size-label"]')).not.toBeNull();
    expect(document.body.querySelector('.band-zoom-stats')!.textContent).toContain('78.5');
    // ✕ 关闭放大层，底层高级配置保留
    act(() =>
      (document.body.querySelector('[data-testid="band-zoom-close"]') as HTMLButtonElement).click(),
    );
    expect(document.body.querySelector('[data-testid="band-zoom-overlay"]')).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');
  });

  it('band-zoom ESC 只关放大层（第三层独立，不关底层高级配置）', async () => {
    useControlPanelStore.getState().openModal('per_type');
    // values 带 g01 键保证下拉 option 在场（受控 select 值需有 option 可选）
    renderModal({ g01: { d: '0', tol: '0' } });
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    act(() =>
      (document.body.querySelector('[data-testid="band-thumb-g01"]') as HTMLButtonElement).click(),
    );
    expect(document.body.querySelector('[data-testid="band-zoom-overlay"]')).not.toBeNull();
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(document.body.querySelector('[data-testid="band-zoom-overlay"]')).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');   // ESC 未级联关闭底层
  });

  it('成带预览失败 → 可读错误文案（成带失败前置到选码时刻，无缩略可点）', async () => {
    mockBandPreview = { ok: false, error: '成带失败: 带内填充率 13.0% < 下限 45.0%（g01 不适合成带或解散落）' };
    useControlPanelStore.getState().openModal('per_type');
    // values 带 g01/g02 键保证下拉 option 在场（g02 供网络错误分支切换）
    renderModal({ g01: { d: '0', tol: '0' }, g02: { d: '0', tol: '0' } });
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    const err = document.body.querySelector<HTMLElement>('[data-testid="band-thumb-error"]')!;
    expect(err).not.toBeNull();
    expect(err.textContent).toContain('填充率 13.0%');
    expect(document.body.querySelector('[data-testid="band-thumb-g01"]')).toBeNull();
    // fetch reject（网络错误）同走错误分支（复用同断言路径）
    fetchSpy!.mockImplementation((_input: unknown) => Promise.reject(new Error('network')));
    selectLabel('g02');
    await flushFetch();
    expect(document.body.querySelector('[data-testid="band-thumb-error"]')!.textContent)
      .toContain('成带预览不可用');
  });
});

// ---------------------------------------------------------------- US-004 prefix
// 「布局设置」第二行：起始端成套前后幅（勾选 + 前幅/后幅下拉 + 2026-08-25 起
// 组合形态预览缩略（POST /api/prefix-preview，替换两张单片原始缩略）+ 默认预选
// 面积最大两片 + 2+2 资格码本地预检警示 + draft/confirm 语义）。
describe('PerTypeOverridesModal 布局设置 prefix 分区 (US-004)', () => {
  /** 3 个 g 码代表裁片（front/back 下拉值域 + 缩略图数据源）。 */
  const THREE_REPS: PtypesResponse = {
    representatives: {
      g01: { label: 'g01', polygon: [[0, 0], [100, 0], [100, 60], [0, 60]] },
      g02: { label: 'g02', polygon: [[0, 0], [80, 0], [80, 80], [0, 80]] },
      g03: { label: 'g03', polygon: [[0, 0], [90, 0], [90, 70], [0, 70]] },
    },
  };

  /** 矩形片 helper（shoelace 面积 = w*h；默认预选的面积排名依据）。 */
  function areaPiece(label: string, w: number, h: number): ParsedPiece {
    return {
      label,
      polygon: [[0, 0], [w, 0], [w, h], [0, h]],
      internal_lines: [],
      notches: [],
      net_polygon: [],
      grain_line: null,
    };
  }

  /** 设置 uploadStore doc（面积 g02 > g03 > g01 的母版，供默认预选）。 */
  function setupDoc(): void {
    const doc: ParsedDoc = {
      doc_id: 'prefix-test',
      filename: '5336.dxf',
      sizes: [{
        size: 28,
        pieces: [areaPiece('g02', 120, 100), areaPiece('g03', 110, 90), areaPiece('g01', 60, 40)],
      }],
    };
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
  }

  /** 数量矩阵 hydrate（默认全 1）+ 指定 label 行整行设值。 */
  function setupQty(rows: Record<string, number>, sizes: number[] = [28, 29]): void {
    const labels = Object.keys(rows);
    useQtyStore.getState().hydrate(
      labels.flatMap((label) => sizes.map((size) => ({ label, size }))),
    );
    for (const [label, v] of Object.entries(rows)) {
      useQtyStore.getState().setRowAll(label, sizes, v);
    }
  }

  /** 仅切换 prefix 下拉（已勾选场景）。 */
  function selectPrefix(front: string, back: string): void {
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!;
    const frontSel = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-front-select"]')!;
    act(() => {
      setter.call(frontSel, front);
      frontSel.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const backSel = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-back-select"]')!;
    act(() => {
      setter.call(backSel, back);
      backSel.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  /** 勾选 prefix（+ 可选选码）。 */
  function enablePrefix(front = '', back = ''): void {
    const check = document.body.querySelector<HTMLInputElement>('[data-testid="prefix-enabled"]')!;
    act(() => check.click());
    if (front !== '' || back !== '') selectPrefix(front, back);
  }

  it('分区渲染：第二行「起始端成套前后幅」+ 前幅/后幅两下拉 + 说明文案常驻', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const row = document.body.querySelector('[data-testid="per-type-prefix-row"]')!;
    expect(row).not.toBeNull();
    expect(row.querySelector('.per-type-band-check')!.textContent).toContain('起始端成套前后幅');
    // 前幅/后幅两下拉在场，aria 报位
    const front = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-front-select"]')!;
    const back = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-back-select"]')!;
    expect(front.getAttribute('aria-label')).toBe('前幅 g 码');
    expect(back.getAttribute('aria-label')).toBe('后幅 g 码');
    // 说明文案常驻（资格码自动选取说明，决策②）
    const note = document.body.querySelector('[data-testid="per-type-prefix-note"]')!;
    expect(note.textContent).toContain('满足 2+2 的尺码将自动选取');
    // 无警示（未勾选不触发预检）
    expect(document.body.querySelector('[data-testid="per-type-prefix-warn"]')).toBeNull();
    // 位于 band 行之后（DOM 顺序：布局设置内 band 两键之后追加）
    const bandRow = document.body.querySelector('.per-type-band-row')!;
    expect(
      bandRow.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('未勾选（默认）→ 两下拉 disabled；勾选后启用', async () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const front = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-front-select"]')!;
    const back = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-back-select"]')!;
    expect(front.disabled).toBe(true);
    expect(back.disabled).toBe(true);
    await flushFetch();
    enablePrefix();
    expect(front.disabled).toBe(false);
    expect(back.disabled).toBe(false);
  });

  it('勾选且两码均空 → 默认预选 parse doc 面积最大两片（决策⑤；g02/g03）', () => {
    setupDoc(); // g02=12000 > g03=9900 > g01=2400
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, { prefix: { enabled: false, front: '', back: '' } });
    enablePrefix();
    const front = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-front-select"]')!;
    const back = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-back-select"]')!;
    expect(front.value).toBe('g02');
    expect(back.value).toBe('g03');
  });

  it('props 已带 front/back（上次确认值）→ 草稿初值读入、勾选切换不覆盖', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, {
      prefix: { enabled: false, front: 'g01', back: 'g02' },
    });
    const front = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-front-select"]')!;
    const back = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-back-select"]')!;
    expect(front.value).toBe('g01');
    expect(back.value).toBe('g02');
    // 关→开（front/back 非空）：启发式不覆盖已有选择
    setupDoc();
    enablePrefix();
    expect(front.value).toBe('g01');
    expect(back.value).toBe('g02');
  });

  it('doc=null（未解析母版）→ 勾选不预选（两下拉留空，不崩溃）', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    enablePrefix();
    const front = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-front-select"]')!;
    expect(front.value).toBe('');
  });

  it('选完前/后幅 → 组合形态预览缩略（POST /api/prefix-preview payload 同源）+ 徽章，点击开 prefix-zoom（第三层）', async () => {
    mockReps = THREE_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    // 未选 → 无缩略图/预览（单片原始缩略已随 renderPrefixThumb 删除）
    expect(document.body.querySelector('[data-testid^="prefix-thumb-"]')).toBeNull();
    enablePrefix('g02', 'g03');
    // loading 占位先渲染（POST 发出）
    expect(document.body.querySelector('[data-testid="prefix-thumb-loading"]')).not.toBeNull();
    await flushFetch();
    const thumb = document.body.querySelector<HTMLButtonElement>('[data-testid="prefix-thumb-g02+g03"]')!;
    expect(thumb).not.toBeNull();
    // 2026-08-25：组合形态预览（BandPreviewSVG 4 成员竖排）替换两张单片 PiecePreviewSVG
    expect(thumb.querySelector('svg.band-preview-svg')).not.toBeNull();
    expect(thumb.querySelectorAll('[data-role="band-member"]')).toHaveLength(4);
    expect(thumb.querySelector('.qty-label-badge')!.textContent).toBe('g02+g03');
    expect(thumb.title).toBe('g02+g03-前缀组合预览放大');
    // POST payload 与 WS StartPayload 同源字段（prefix/sizes/gate_mm）
    const call = fetchSpy!.mock.calls.find((c) => String(c[0]).includes('/api/prefix-preview'))!;
    const init = call[1] as RequestInit;
    expect(init.method).toBe('POST');
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.prefix).toEqual({ enabled: true, front: 'g02', back: 'g03' });
    expect(body.sizes).toEqual([28, 29]);
    expect(body.gate_mm).toBe(1980);
    // 点击 → prefix-zoom 第三层放大（previewLabel 不动，底层高级配置保留）
    act(() => thumb.click());
    expect(document.body.querySelector('[data-testid="prefix-zoom-overlay"]')).not.toBeNull();
    expect(useControlPanelStore.getState().previewLabel).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');   // 底层保留
    // 放大层统计行（填充率 / 宽×高 / 片数 / 码）+ 成员 g 码标注（tag，前/后幅区分）
    const zoomBody = document.body.querySelector('.band-zoom-body')!;
    const labels = zoomBody.querySelectorAll('[data-role="band-size-label"]');
    expect(labels).toHaveLength(4);
    expect(Array.from(labels).map((l) => l.textContent).sort())
      .toEqual(['g02', 'g02', 'g03', 'g03']);
    const stats = document.body.querySelector('.band-zoom-stats')!.textContent;
    expect(stats).toContain('83.3');
    expect(stats).toContain('码 28');
    // ✕ 关闭放大层，底层高级配置保留
    act(() =>
      (document.body.querySelector('[data-testid="prefix-zoom-close"]') as HTMLButtonElement).click(),
    );
    expect(document.body.querySelector('[data-testid="prefix-zoom-overlay"]')).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');
    // 重开 → ESC 只关放大层（第三层独立，不级联关闭底层高级配置）
    act(() => thumb.click());
    expect(document.body.querySelector('[data-testid="prefix-zoom-overlay"]')).not.toBeNull();
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(document.body.querySelector('[data-testid="prefix-zoom-overlay"]')).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');
  });

  it('前缀预览失败 → 可读错误文案（构造失败前置到选码时刻），下拉仍可选（不阻塞）', async () => {
    mockPrefixPreview = {
      ok: false,
      error: '前缀构造失败: 无 2+2 资格码（front=g02, back=g03）',
    };
    useControlPanelStore.getState().openModal('per_type');
    // values 带 g02/g03 键保证下拉 option 在场（fetch 失败降级路径）
    renderModal({ g02: { d: '0', tol: '0' }, g03: { d: '0', tol: '0' } });
    await flushFetch();
    enablePrefix('g02', 'g03');
    await flushFetch();
    const err = document.body.querySelector<HTMLElement>('[data-testid="prefix-thumb-error"]')!;
    expect(err).not.toBeNull();
    expect(err.textContent).toContain('前缀构造失败');
    expect(document.body.querySelector('[data-testid="prefix-thumb-g02+g03"]')).toBeNull();
    // fetch reject（网络错误）同走 catch 分支（切换任一下拉重触发 POST）
    fetchSpy!.mockImplementation((_input: unknown) => Promise.reject(new Error('network')));
    selectPrefix('g03', 'g02');
    await flushFetch();
    expect(document.body.querySelector('[data-testid="prefix-thumb-error"]')!.textContent)
      .toContain('前缀预览不可用');
    // 错误不阻塞配置：下拉仍可选且值正确
    const front = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-front-select"]')!;
    expect(front.disabled).toBe(false);
    expect(front.value).toBe('g03');
  });

  it('front==back → 警示「前幅与后幅须为不同 g 码」', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g02: { d: '0', tol: '0' } });
    enablePrefix('g02', 'g02');
    const warn = document.body.querySelector<HTMLElement>('[data-testid="per-type-prefix-warn"]')!;
    expect(warn).not.toBeNull();
    expect(warn.textContent).toContain('前幅与后幅须为不同 g 码');
  });

  it('无 2+2 资格码（hydrate 全 1）→ 警示「当前数量无 2+2 资格码」', () => {
    setupQty({ g02: 1, g03: 1 }); // 全 1 → 无资格（quantities=null 全 demand=1 同判）
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g02: { d: '0', tol: '0' }, g03: { d: '0', tol: '0' } });
    enablePrefix('g02', 'g03');
    const warn = document.body.querySelector<HTMLElement>('[data-testid="per-type-prefix-warn"]')!;
    expect(warn).not.toBeNull();
    expect(warn.textContent).toContain('当前数量无 2+2 资格码');
    expect(warn.textContent).toContain('2+2');
  });

  it('有资格码（2+2）→ 无警示；数量编辑响应式（改 1 → 警示出现）', () => {
    setupQty({ g02: 2, g03: 2 });
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g02: { d: '0', tol: '0' }, g03: { d: '0', tol: '0' } });
    enablePrefix('g02', 'g03');
    expect(document.body.querySelector('[data-testid="per-type-prefix-warn"]')).toBeNull();
    // 数量矩阵把 g02 两码全改 1 → 无任何码两码双双 ==2 → 警示出现（qtyStore 响应式订阅）
    act(() => {
      useQtyStore.getState().setPiecePerSize('g02', 28, 1);
      useQtyStore.getState().setPiecePerSize('g02', 29, 1);
    });
    const warn = document.body.querySelector<HTMLElement>('[data-testid="per-type-prefix-warn"]')!;
    expect(warn).not.toBeNull();
  });

  it('confirm 回写 onPrefixChange（与 band 同一 saveAndClose 通道）；取消丢弃', () => {
    const onPrefixChange = vi.fn();
    const onBandChange = vi.fn();
    setupDoc();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, { onPrefixChange, onBandChange });
    enablePrefix(); // 勾选 → 默认预选 g02/g03
    const confirm = document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!;
    act(() => confirm.click());
    expect(onPrefixChange).toHaveBeenCalledTimes(1);
    expect(onPrefixChange).toHaveBeenCalledWith({ enabled: true, front: 'g02', back: 'g03' });
    // band 同通道回写（未勾选 → 原样保留）
    expect(onBandChange).toHaveBeenCalledWith({ enabled: false, label: '' });
    expect(useControlPanelStore.getState().modal).toBeNull();

    // 取消路径：重新打开 → 勾选 → 取消 → onPrefixChange 不调用（草稿丢弃）
    const onPrefixChange2 = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, { onPrefixChange: onPrefixChange2 });
    enablePrefix();
    const cancel = document.body.querySelector<HTMLButtonElement>('.per-type-btn-cancel')!;
    act(() => cancel.click());
    expect(onPrefixChange2).not.toHaveBeenCalled();
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('prefix 区在场不阻塞 band 使用（独立分组，band 下拉/预览互不影响）', async () => {
    mockReps = THREE_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    // band 控件照常在场且可用
    const bandCheck = document.body.querySelector<HTMLInputElement>('[data-testid="band-enabled"]')!;
    act(() => bandCheck.click());
    const bandSelect = document.body.querySelector<HTMLSelectElement>('[data-testid="band-label-select"]')!;
    expect(bandSelect.disabled).toBe(false);
    // prefix 勾选不改变 band 下拉状态
    enablePrefix('g02', 'g03');
    expect(bandSelect.disabled).toBe(false);
  });
});
