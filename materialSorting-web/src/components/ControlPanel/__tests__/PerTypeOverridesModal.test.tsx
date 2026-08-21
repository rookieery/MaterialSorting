// US-018 PerTypeOverridesModal integration tests（裁片编号化重构 US-003 起改写：
// V03_PTYPES 固定 10 中文列已删，列集 = /api/ptypes representatives 键 ∪ values
// 已配置键 —— 全部为裁片 g 码，按 compareByLabel 数值序）：
//   AC: modal=null does not render DOM (no portal content)
//   AC: modal='per_type' renders overlay + modal + aria-label
//   AC: thead 列 = reps 键（g 码徽章）；reps 空 + values 空 → 仅行头列（0 数据列）
//   AC: tbody renders 2 rows (重合 + 旋转)
//   AC: mount triggers fetch('/api/ptypes')
//   AC: fetch failure degrades (no crash, 列集退回 values 键)
//   AC: fetch success renders representatives[label] via PiecePreviewSVG compact
//   AC: 列序 = compareByLabel 数值序（g01<g02<g99<g100，长度优先防字典序倒挂）
//   AC: values 已配置键与 reps 键并集（fetch 失败时已配置项仍可配）
//   AC: thumbnail hover/aria =「g 码-放大预览」不含任何中文片型名
//   AC: initial draft reads form.per_type（空值预填 '0'/'0'）
//   AC: editing draft does NOT call onChange immediately
//   AC: confirm calls onChange + onClose (modal closes)
//   AC: cancel does not call onChange (draft discarded)
//   AC: overlay mousedown closes (draft discarded)
//   AC: ESC closes when previewLabel null（双层独立 AC#10）
//   AC: ESC does NOT close modal when previewLabel open
//   AC: close button (✕) closes
//   AC: clicking thumbnail opens PtypePreviewModal (previewLabel set)
//   AC: inputs carry global caps d≤10 / t≤45
//   AC: blur clamps draft into [0, max]
//   AC: mousedown inside modal does NOT bubble-close
//
// US-013 布局设置分区 additions（band 草稿 + 下拉 + 预演）：
//   AC: 分区标题「布局设置」+ 勾选框「开启腰头成带」+ 子标题「腰头编号」渲染
//   AC: 未勾选时下拉 disabled；勾选启用；band 草稿初值从 props 读入
//   AC: 下拉值域 = reps 键动态（fetch 失败降级 values 键纯文字列表不阻塞）
//   AC: 选中 g 码有 rep → 80×80 缩略图 + 徽章（点击 openPreviewLabel 双层 modal）
//   AC: 选中有效 g 码 → POST /api/band/preview（body 带 ctx + band）→ 回显 fill 对照参考线
//   AC: 预演失败（ok:false / 网络错）→ 降级提示，confirm 仍写回（不阻塞确认）
//   AC: 硬警告形态（422 hard_warning）→ ack 二次确认勾选框；勾选带 ack:true 重试，
//       confirm 写回 ack:true；几何失败（无 hard_warning）不渲染勾选框
//   AC: 切换 g 码 → ack 草稿重置（形态确认 per-label，FR-1）
//   AC: confirm 同时回写 per_type + band；取消/遮罩/ESC 丢弃 band 草稿
//
// US-015 填料行 additions（v1.1 混带多选）：
//   AC: 未勾选成带填料行不渲染；勾选后候选 = orderedLabels - 主码
//   AC: 点击 chip 选中（.on + aria-pressed）→ 预演 body 带 band.fillers；再点取消
//   AC: 上限 3：满 3 后未选中 chip disabled；取消一个恢复
//   AC: 切换腰头编号 → 填料集合中与新主码相同的项剔除
//   AC: confirm 写回 fillers；取消丢弃；props 初值剔除 = 主码项

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PerTypeOverridesModal, type BandFormValue } from '../PerTypeOverridesModal';
import { PtypePreviewModal } from '../PtypePreviewModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import type { PtypesResponse } from '../../../types/ptype';
import type { PerTypeFormValue, StartContext } from '../../../lib/params';
import { MAX_OVERLAP_MM, MAX_ROTATION_TOL_DEG } from '../../../constants/v03';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
/** 当前 mock 返回的 representatives 数据（每次 fetch 创建新 Response，避免 body 被消费两次）。 */
let mockReps: PtypesResponse = { representatives: {} };
/** 当前 mock 对 POST /api/band/preview 的响应（null = 按调用的 body 动态构造成功响应）。 */
let mockPreview: Record<string, unknown> | null = null;
/** mockPreview 的 HTTP 状态码（422 = 硬警告形态 ack 校验；组件不查 r.ok 只读 body）。 */
let mockPreviewStatus = 200;

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

beforeEach(() => {
  useControlPanelStore.getState().closeModal();
  useControlPanelStore.getState().closePreviewLabel();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  mockReps = { representatives: {} };
  mockPreview = null;
  mockPreviewStatus = 200;
  // 用 mockImplementation 每次 fetch 创建新 Response（StrictMode 双 mount 会调 2 次 fetch；
  // mockResolvedValue 共享同一 Response 会被首次 .json() 消费完，第二次报 body 已读）。
  // US-013：按 URL 分流 —— /api/ptypes 返 reps；/api/band/preview 返 mockPreview
  //（缺省按请求 body 的 label 动态构造成功响应，便于断言 body 字段；状态码可配 ——
  // 422 = 硬警告 ack 校验路径，组件只读 body 不查 r.ok）。
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input: unknown, init?: unknown) => {
    const url = String(input);
    if (url.includes('/api/band/preview')) {
      const body = JSON.parse(String((init as RequestInit | undefined)?.body ?? '{}'));
      const data =
        mockPreview ??
        ({
          ok: true,
          fill_pct: 65.3,
          bbox: { width_mm: 1234.5, height_mm: 1980 },
          elapsed: 5.1,
          break_even: [62.4, 63.6],
          echo_label: body?.band?.label,
        } as Record<string, unknown>);
      return Promise.resolve(
        new Response(JSON.stringify(data), {
          status: mockPreviewStatus,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify(mockReps), {
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
    buildStartContext?: () => StartContext;
  } = {},
): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <PerTypeOverridesModal
          values={values}
          onChange={onChange}
          band={opts.band ?? { enabled: false, label: '', ack: false, fillers: [] }}
          onBandChange={opts.onBandChange ?? (() => {})}
          buildStartContext={
            opts.buildStartContext ??
            (() => ({
              sizes: [28, 30],
              gate_mm: 1980,
              seed: 0,
              time: 120,
              params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
              per_type: null,
              quantities: null,
              band: null,
            }))
          }
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

/** 勾选 band → 选 g 码（native setter + change；US-013/US-015 共用，模块级导出给两个 describe）。 */
function enableAndSelect(label: string): void {
  const check = document.body.querySelector<HTMLInputElement>('[data-testid="band-enabled"]')!;
  act(() => check.click());
  selectLabel(label);
}

/** 仅切换下拉 g 码（已勾选场景；切码重置 ack / US-015 剔除同码填料路径用）。 */
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
    expect(modal!.getAttribute('aria-label')).toContain('高级配置');
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

  it('mount triggers fetch("/api/ptypes")', async () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    expect(fetchSpy).toHaveBeenCalled();
    const urls = fetchSpy!.mock.calls.map((c: unknown[]) => c[0]);
    expect(urls.some((u: unknown) => String(u).includes('/api/ptypes'))).toBe(true);
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

  it('ESC closes (draft discarded) when previewLabel is null', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, onChange);
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
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
              band={{ enabled: false, label: '', ack: false, fillers: [] }}
              onBandChange={() => {}}
              buildStartContext={() => ({
                sizes: [], gate_mm: 1980, seed: 0, time: 120,
                params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
                per_type: null, quantities: null, band: null,
              })}
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

  it('close button (✕) closes', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const closeBtn = document.body.querySelector<HTMLButtonElement>('.per-type-close')!;
    act(() => closeBtn.click());
    expect(useControlPanelStore.getState().modal).toBeNull();
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

describe('PerTypeOverridesModal 布局设置分区 (US-013)', () => {
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

  it('未勾选时下拉 disabled；band 草稿初值从 props 读入（勾选+label 预选）', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, {
      band: { enabled: true, label: 'g01', ack: false, fillers: [] },
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

  it('未勾选（默认）→ 下拉 disabled + 无预演请求；勾选后启用', async () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const select = document.body.querySelector<HTMLSelectElement>('[data-testid="band-label-select"]')!;
    expect(select.disabled).toBe(true);
    await flushFetch();
    // 未勾选 → 不发预演请求
    expect(
      fetchSpy!.mock.calls.some((c: unknown[]) => String(c[0]).includes('/api/band/preview')),
    ).toBe(false);
    // 勾选（未选编号）→ 下拉启用但仍无预演（label 无效）
    const check = document.body.querySelector<HTMLInputElement>('[data-testid="band-enabled"]')!;
    act(() => check.click());
    expect(select.disabled).toBe(false);
    await flushFetch();
    expect(
      fetchSpy!.mock.calls.some((c: unknown[]) => String(c[0]).includes('/api/band/preview')),
    ).toBe(false);
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

  it('选中有效 g 码 → POST /api/band/preview（body = ctx + band）→ 回显 fill 对照参考线', async () => {
    mockReps = TWO_REPS;
    const ctx: StartContext = {
      sizes: [28, 30],
      gate_mm: 1980,
      seed: 7,
      time: 120,
      params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
      per_type: null,
      quantities: { g01: { '28': 2 } },
      band: null,
    };
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, { buildStartContext: () => ctx });
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    // 请求体：band 草稿 + ctx（sizes/seed/quantities 同源）
    const call = fetchSpy!.mock.calls.find((c: unknown[]) => String(c[0]).includes('/api/band/preview'))!;
    const body = JSON.parse(String((call[1] as RequestInit).body));
    expect(body.band).toEqual({ enabled: true, label: 'g01' });
    expect(body.sizes).toEqual([28, 30]);
    expect(body.seed).toBe(7);
    expect(body.quantities).toEqual({ g01: { '28': 2 } });
    // 回显：fill + bbox + 参考线对照
    const preview = document.body.querySelector('[data-testid="band-preview"]')!;
    expect(preview.textContent).toContain('65.3');
    expect(preview.textContent).toContain('1235×1980mm');   // Math.round
    expect(preview.textContent).toContain('达到盈亏参考线 62.4~63.6%');
  });

  it('fill 低于参考线 → 「低于盈亏参考线」措辞', async () => {
    mockPreview = {
      ok: true, fill_pct: 55.1, bbox: { width_mm: 800, height_mm: 1980 },
      elapsed: 5.0, break_even: [62.4, 63.6],
    };
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    const preview = document.body.querySelector('[data-testid="band-preview"]')!;
    expect(preview.textContent).toContain('低于盈亏参考线 62.4~63.6%');
  });

  it('预演失败（ok:false）→ 降级提示，confirm 仍写回 band（不阻塞确认）', async () => {
    mockPreview = { ok: false, error: '预演失败: 带内填充率 30.0% < 下限 45.0%' };
    mockReps = TWO_REPS;
    const onBandChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, { onBandChange });
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    const preview = document.body.querySelector('[data-testid="band-preview"]')!;
    expect(preview.textContent).toContain('带内预演失败（不影响确认）');
    expect(preview.textContent).toContain('填充率 30.0%');
    // 确定仍可点且写回 band 草稿
    const confirm = document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!;
    act(() => confirm.click());
    expect(onBandChange).toHaveBeenCalledWith({ enabled: true, label: 'g01', ack: false, fillers: [] });
  });

  it('硬警告形态（422 hard_warning）→ 失败提示 + ack 勾选框；勾选 → 带 ack 重试成功 → confirm 写回 ack:true', async () => {
    mockReps = TWO_REPS;
    const onBandChange = vi.fn();
    // 第一响应：422 硬警告（5336 g05 同类 —— 长宽比 >6 细长条）
    mockPreview = {
      ok: false,
      error: 'band g 码 g01 最小边 40mm（<60）或长宽比 6.9（>6），属硬警告形态，需显式确认（band.ack=true）才执行成带',
      hard_warning: true,
    };
    mockPreviewStatus = 422;
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, { onBandChange });
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    // 降级提示 + 二次确认勾选框出现；首次请求不带 ack
    const preview = document.body.querySelector('[data-testid="band-preview"]')!;
    expect(preview.textContent).toContain('带内预演失败（不影响确认）');
    expect(preview.textContent).toContain('长宽比 6.9');
    const ackWrap = document.body.querySelector('[data-testid="band-ack-wrap"]')!;
    expect(ackWrap).not.toBeNull();
    expect(ackWrap.textContent).toContain('仍要成带');
    const firstBody = JSON.parse(
      String((fetchSpy!.mock.calls.find((c: unknown[]) => String(c[0]).includes('/api/band/preview'))![1] as RequestInit).body),
    );
    expect(firstBody.band).toEqual({ enabled: true, label: 'g01' });
    // 勾选 ack → mock 切成功 → 重试请求带 ack:true → 回显 fill
    mockPreview = {
      ok: true, fill_pct: 71.2, bbox: { width_mm: 900, height_mm: 1980 },
      elapsed: 5.0, break_even: [62.4, 63.6],
    };
    mockPreviewStatus = 200;
    act(() => ackWrap.querySelector<HTMLInputElement>('[data-testid="band-ack"]')!.click());
    await flushFetch();
    expect(preview.textContent).toContain('71.2');
    expect(preview.textContent).toContain('达到盈亏参考线');
    // 勾选后 checkbox 保持可见（可反勾撤销）
    expect(document.body.querySelector('[data-testid="band-ack-wrap"]')).not.toBeNull();
    const calls = fetchSpy!.mock.calls.filter((c: unknown[]) => String(c[0]).includes('/api/band/preview'));
    const lastBody = JSON.parse(String((calls[calls.length - 1][1] as RequestInit).body));
    expect(lastBody.band).toEqual({ enabled: true, label: 'g01', ack: true });
    // confirm 写回 ack:true（此后 WS start band 带 ack，后端放行）
    act(() => document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!.click());
    expect(onBandChange).toHaveBeenCalledWith({ enabled: true, label: 'g01', ack: true, fillers: [] });
  });

  it('几何失败（无 hard_warning）→ 无 ack 勾选框（只有硬警告形态渲染二次确认）', async () => {
    mockPreview = { ok: false, error: '预演失败: 带内填充率 30.0% < 下限 45.0%' };
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    expect(document.body.querySelector('[data-testid="band-preview"]')!.textContent).toContain('带内预演失败');
    expect(document.body.querySelector('[data-testid="band-ack-wrap"]')).toBeNull();
  });

  it('切换 g 码 → ack 草稿重置（形态确认 per-label）', async () => {
    mockReps = TWO_REPS;
    mockPreview = {
      ok: false, error: '需显式确认（band.ack=true）', hard_warning: true,
    };
    mockPreviewStatus = 422;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    act(() => document.body.querySelector<HTMLInputElement>('[data-testid="band-ack"]')!.click());
    await flushFetch();
    // 切到 g02 → ack 重置（请求不带 ack，勾选框只在 422 后重新出现）
    selectLabel('g02');
    await flushFetch();
    const calls = fetchSpy!.mock.calls.filter((c: unknown[]) => String(c[0]).includes('/api/band/preview'));
    const lastBody = JSON.parse(String((calls[calls.length - 1][1] as RequestInit).body));
    expect(lastBody.band).toEqual({ enabled: true, label: 'g02' });
  });

  it('confirm 同时回写 per_type + band；取消/遮罩/ESC 丢弃 band 草稿', () => {
    const onChange = vi.fn();
    const onBandChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g01: { d: '0', tol: '0' } }, onChange, { onBandChange });
    enableAndSelect('g01');
    const confirm = document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!;
    act(() => confirm.click());
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onBandChange).toHaveBeenCalledTimes(1);
    expect(onBandChange).toHaveBeenCalledWith({ enabled: true, label: 'g01', ack: false, fillers: [] });
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

  it('选中 g 码有 rep → 80×80 缩略图 + 徽章，点击 openPreviewLabel（双层 modal）', async () => {
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    // 未选 → 无缩略图
    expect(document.body.querySelector('.per-type-band-thumb')).toBeNull();
    enableAndSelect('g01');
    const thumb = document.body.querySelector<HTMLButtonElement>('[data-testid="band-thumb-g01"]')!;
    expect(thumb).not.toBeNull();
    expect(thumb.querySelector('svg.piece-preview-svg')).not.toBeNull();
    expect(thumb.querySelector('.qty-label-badge')!.textContent).toBe('g01');
    expect(thumb.title).toBe('g01-放大预览');
    act(() => thumb.click());
    expect(useControlPanelStore.getState().previewLabel).toBe('g01');
    expect(useControlPanelStore.getState().modal).toBe('per_type');   // 底层保留
  });
});

describe('PerTypeOverridesModal 填料行 (US-015 v1.1 混带)', () => {
  /** 5 个 g 码（主码 g01 + 4 个填料候选 g02~g05，供上限 3 测试）。 */
  const FIVE_REPS: PtypesResponse = {
    representatives: {
      g01: { label: 'g01', polygon: [[0, 0], [100, 0], [100, 60], [0, 60]] },
      g02: { label: 'g02', polygon: [[0, 0], [80, 0], [80, 80], [0, 80]] },
      g03: { label: 'g03', polygon: [[0, 0], [70, 0], [70, 50], [0, 50]] },
      g04: { label: 'g04', polygon: [[0, 0], [60, 0], [60, 90], [0, 90]] },
      g05: { label: 'g05', polygon: [[0, 0], [90, 0], [90, 40], [0, 40]] },
    },
  };

  /** 点击填料 chip（受控 button，直接 click）。 */
  function clickFiller(label: string): void {
    const chip = document.body.querySelector<HTMLButtonElement>(`[data-testid="band-filler-${label}"]`)!;
    act(() => chip.click());
  }

  /** 当前预演请求 body（取最后一次 /api/band/preview 调用）。 */
  function lastPreviewBody(): Record<string, unknown> {
    const calls = fetchSpy!.mock.calls.filter((c: unknown[]) => String(c[0]).includes('/api/band/preview'));
    return JSON.parse(String((calls[calls.length - 1][1] as RequestInit).body));
  }

  it('未勾选成带 → 填料行不渲染；勾选后渲染（chip = 候选 g 码 - 主码）', async () => {
    mockReps = FIVE_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    expect(document.body.querySelector('[data-testid="band-fillers"]')).toBeNull();
    // 勾选 + 选主码 g01 → 填料行出现，候选 = g02~g05（主码不在候选集）
    enableAndSelect('g01');
    const row = document.body.querySelector('[data-testid="band-fillers"]')!;
    expect(row).not.toBeNull();
    const chips = Array.from(row.querySelectorAll('.per-type-filler-chip'));
    expect(chips.map((c) => c.querySelector('.qty-label-badge')!.textContent)).toEqual([
      'g02', 'g03', 'g04', 'g05',
    ]);
    // chip 有 rep → 缩略图 svg；hint 提示上限
    expect(row.querySelector('.per-type-filler-chip svg.piece-preview-svg')).not.toBeNull();
    expect(row.querySelector('.per-type-filler-hint')!.textContent).toContain('最多 3 个');
  });

  it('多选交互：点击选中（.on + aria-pressed）→ 预演 body 带 fillers → 再点取消', async () => {
    mockReps = FIVE_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    // 初始无 fillers 键（payload 形状与旧版一致）
    expect(lastPreviewBody().band).toEqual({ enabled: true, label: 'g01' });
    clickFiller('g02');
    await flushFetch();
    const chip = document.body.querySelector<HTMLButtonElement>('[data-testid="band-filler-g02"]')!;
    expect(chip.classList.contains('on')).toBe(true);
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    // 填料选择变化触发预演重跑，body 带 fillers（腰 + 填料同口径）
    expect(lastPreviewBody().band).toEqual({ enabled: true, label: 'g01', fillers: ['g02'] });
    // 再点取消 → 回到无 fillers
    clickFiller('g02');
    await flushFetch();
    expect(lastPreviewBody().band).toEqual({ enabled: true, label: 'g01' });
  });

  it('数量上限 3：满 3 后未选中 chip 置灰；取消一个恢复可选', async () => {
    mockReps = FIVE_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    clickFiller('g02');
    clickFiller('g03');
    clickFiller('g04');
    await flushFetch();
    expect(lastPreviewBody().band).toEqual({
      enabled: true, label: 'g01', fillers: ['g02', 'g03', 'g04'],
    });
    // g05 未选中且已满 → disabled
    const g05 = document.body.querySelector<HTMLButtonElement>('[data-testid="band-filler-g05"]')!;
    expect(g05.disabled).toBe(true);
    // 已选中的仍可取消
    const g02 = document.body.querySelector<HTMLButtonElement>('[data-testid="band-filler-g02"]')!;
    expect(g02.disabled).toBe(false);
    clickFiller('g02');
    await flushFetch();
    expect(lastPreviewBody().band).toEqual({ enabled: true, label: 'g01', fillers: ['g03', 'g04'] });
    expect(
      (document.body.querySelector<HTMLButtonElement>('[data-testid="band-filler-g05"]')!).disabled,
    ).toBe(false);
  });

  it('切换腰头编号 → 旧填料集合中与新主码相同的项被剔除', async () => {
    mockReps = FIVE_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    clickFiller('g02');
    await flushFetch();
    // 切主码到 g02 → 填料 g02 剔除（不可与主 g 码相同）
    selectLabel('g02');
    await flushFetch();
    expect(lastPreviewBody().band).toEqual({ enabled: true, label: 'g02' });
    // 候选集更新：主码 g02 缺席，g01 回到候选
    const badges = Array.from(
      document.body.querySelectorAll('[data-testid="band-fillers"] .qty-label-badge'),
    ).map((b) => b.textContent);
    expect(badges).toEqual(['g01', 'g03', 'g04', 'g05']);
  });

  it('confirm 写回 fillers；取消丢弃（form.band_fillers 草稿语义）', async () => {
    mockReps = FIVE_REPS;
    const onBandChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, { onBandChange });
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    clickFiller('g02');
    clickFiller('g03');
    await flushFetch();
    // 取消 → 草稿丢弃
    act(() => document.body.querySelector<HTMLButtonElement>('.per-type-btn-cancel')!.click());
    expect(onBandChange).not.toHaveBeenCalled();
    expect(useControlPanelStore.getState().modal).toBeNull();
    // 重开（同 props）→ 重新选 → 确定 → 写回 fillers
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, { onBandChange });
    await flushFetch();
    enableAndSelect('g01');
    await flushFetch();
    clickFiller('g02');
    clickFiller('g03');
    await flushFetch();
    act(() => document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!.click());
    expect(onBandChange).toHaveBeenCalledWith({
      enabled: true, label: 'g01', ack: false, fillers: ['g02', 'g03'],
    });
    await flushFetch();
  });

  it('props 初值带 fillers：草稿读入 + 与主码相同项剔除（≠主码不变量兜底）', async () => {
    mockReps = FIVE_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, () => {}, {
      band: { enabled: true, label: 'g01', ack: false, fillers: ['g01', 'g03'] },
    });
    await flushFetch();
    // g01（= 主码）被剔除，g03 保留选中
    const g01Chip = document.body.querySelector<HTMLButtonElement>('[data-testid="band-filler-g01"]');
    expect(g01Chip).toBeNull();   // 主码不在候选集
    const g03 = document.body.querySelector<HTMLButtonElement>('[data-testid="band-filler-g03"]')!;
    expect(g03.classList.contains('on')).toBe(true);
    await flushFetch();
    expect(lastPreviewBody().band).toEqual({ enabled: true, label: 'g01', fillers: ['g03'] });
  });
});
