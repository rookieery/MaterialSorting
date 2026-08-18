// US-004 PerTypeOverridesModal 矩阵化集成测试（行=码号 × 列=g 码、格=(g 码,码号)
// d/tol 双输入、per_type 两级嵌套 {label:{sizeKey:{d,tol}}}）：
//   AC: modal=null does not render DOM (no portal content)
//   AC: modal='per_type' renders overlay + modal + aria-label
//   AC: 行 = doc.sizes（升序、null 通用殿后）；doc=null → SIZES fallback 8 行
//   AC: values 已配置但不在行集的 sizeKey 追加为行（旧配置不静默丢）
//   AC: thead 列 = reps 键（g 码徽章 + ≡ 整列设值 icon）；reps 空 + values 空 → 仅行头列
//   AC: fetch failure degrades (列集退回 values 键，不阻塞)
//   AC: fetch success renders representatives[label] via PiecePreviewSVG compact
//   AC: 列序 = compareByLabel 数值序（g99<g100，长度优先防字典序倒挂）
//   AC: 格 = d/tol 双输入（data-testid d-{label}-{sk} / tol-{label}-{sk}；空串+placeholder=继承）
//   AC: doc 中该 g 码无此码号 → .per-type-cell.missing「—」；label 不在 doc → 可编辑
//   AC: initial draft 读 form.per_type 非空值；不预填 '0'（空 = 继承）
//   AC: editing draft does NOT call onChange immediately
//   AC: confirm 回写两级嵌套（剔除全空格子）+ 关闭
//   AC: cancel / overlay / ESC / ✕ 丢弃草稿（onChange 不调用）
//   AC: ESC 不关 modal 当 previewLabel open（双层独立）
//   AC: ESC 只关整列设值弹层（fill open 时 modal 保留）
//   AC: clicking thumbnail opens PtypePreviewModal (previewLabel set)
//   AC: inputs carry global caps d≤10 / t≤45；aria 报 (g 码, 码号)
//   AC: blur clamps draft into [0, max]
//   AC: ≡ 整列设值 → 应用写该列全部行（留空侧 = 继承默认）
//   AC: 整列设值弹层取消 / 遮罩 mousedown 不写 draft
//   AC: mousedown inside modal does NOT bubble-close

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PerTypeOverridesModal } from '../PerTypeOverridesModal';
import { PtypePreviewModal } from '../PtypePreviewModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { useUploadStore } from '../../../store/uploadStore';
import { SIZES } from '../../../constants/sizes';
import type { ParsedDoc, ParsedPiece } from '../../../types/parsed';
import type { PtypesResponse } from '../../../types/ptype';
import type { PerTypeFormMap } from '../../../lib/params';
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

/** 构造最小 ParsedPiece（polygon 足够 PiecePreviewSVG/缺片判定用）。 */
function piece(label: string): ParsedPiece {
  return {
    label,
    polygon: [
      [0, 0],
      [100, 0],
      [100, 60],
      [0, 60],
    ],
    internal_lines: [],
    notches: [],
    net_polygon: [],
    grain_line: null,
  };
}

/**
 * 测试母版：28 码 g01+g02；30 码仅 g01；null 通用码 g01。
 * 覆盖：正常格 / 缺片格（g02@30 缺）/ 通用码行。
 */
const TEST_DOC: ParsedDoc = {
  doc_id: 'modal-test',
  filename: 'M1787.dxf',
  sizes: [
    { size: 28, pieces: [piece('g01'), piece('g02')] },
    { size: 30, pieces: [piece('g01')] },
    { size: null, pieces: [piece('g01')] },
  ],
};

beforeEach(() => {
  useControlPanelStore.getState().closeModal();
  useControlPanelStore.getState().closePreviewLabel();
  useUploadStore.getState().reset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  mockReps = { representatives: {} };
  // 用 mockImplementation 每次 fetch 创建新 Response（StrictMode 双 mount 会调 2 次 fetch；
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
  useUploadStore.getState().reset();
  if (fetchSpy) {
    fetchSpy.mockRestore();
    fetchSpy = null;
  }
});

function renderModal(
  values: PerTypeFormMap = {},
  onChange: (next: PerTypeFormMap) => void = () => {},
): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <PerTypeOverridesModal values={values} onChange={onChange} />
      </StrictMode>,
    );
  });
  return container!;
}

/** 写入 uploadStore.doc（rows = doc.sizes 路径）。 */
function setDoc(doc: ParsedDoc | null): void {
  if (doc) {
    useUploadStore.setState({ status: 'done', doc, activeSize: doc.sizes[0]?.size ?? null });
  } else {
    useUploadStore.getState().reset();
  }
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

/** tbody 行头文本（码号人读：number→String；null→通用）。 */
function rowHeadTexts(): string[] {
  return Array.from(document.body.querySelectorAll('tbody .per-type-rowhead')).map(
    (h) => h.textContent ?? '',
  );
}

/** thead 列徽章文本（g 码，compareByLabel 序）。 */
function colBadges(): string[] {
  return Array.from(document.body.querySelectorAll('thead .qty-label-badge')).map(
    (b) => b.textContent ?? '',
  );
}

describe('PerTypeOverridesModal (US-004 矩阵化：行=码号 × 列=g 码)', () => {
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

  it('行 = doc.sizes（升序，null 通用殿后）', async () => {
    setDoc(TEST_DOC);
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    expect(rowHeadTexts()).toEqual(['28', '30', '通用']);
    // thead 行头列标题 = 码号
    expect(document.body.querySelector('thead .per-type-rowhead')!.textContent).toBe('码号');
  });

  it('doc=null → SIZES fallback 8 行（与 SizePicker chip 同源）', async () => {
    setDoc(null);
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    expect(rowHeadTexts()).toEqual(SIZES.map(String));
  });

  it('values 已配置但不在行集的 sizeKey 追加为行（旧配置不静默丢）', async () => {
    setDoc(TEST_DOC); // 行集 28/30/null
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    const values: PerTypeFormMap = { g01: { '33': { d: '1', tol: '' } } };
    renderModal(values);
    await flushFetch();
    expect(rowHeadTexts()).toEqual(['28', '30', '通用', '33']);
  });

  it('thead 列 = reps 键（g 码徽章 + ≡ 整列设值 icon；无 .ptype-name）', async () => {
    setDoc(TEST_DOC);
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const heads = document.body.querySelectorAll('thead .ptype-col');
    expect(heads).toHaveLength(2);
    expect(colBadges()).toEqual(['g01', 'g02']);
    // 每列常驻「≡」整列设值 icon（QtyMatrix 同款）
    expect(document.body.querySelectorAll('thead .qty-rowfill-btn')).toHaveLength(2);
    expect(document.body.querySelector('[data-testid="per-type-fill-btn-g01"]')).not.toBeNull();
    // 旧中文片型名列头类名零残留
    expect(document.body.querySelector('.ptype-name')).toBeNull();
  });

  it('reps 空 + values 空 → 仅行头列（0 数据列，不阻塞）', async () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    expect(document.body.querySelectorAll('thead .ptype-col')).toHaveLength(0);
    expect(document.body.querySelector('thead .per-type-rowhead')!.textContent).toBe('码号');
    // SIZES fallback 行仍在（doc=null）
    expect(document.body.querySelectorAll('tbody tr')).toHaveLength(SIZES.length);
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
    const values: PerTypeFormMap = { g05: { '28': { d: '2', tol: '3' } } };
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
    setDoc(TEST_DOC);
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
    expect(colBadges()).toEqual(['g02', 'g99', 'g100']);
    // 列头与格子对齐：首行（28 码）首列（g02）d 输入 = d-g02-28
    const firstRowD = document.body.querySelector<HTMLInputElement>('tbody tr input')!;
    expect(firstRowD.getAttribute('data-testid')).toBe('d-g02-28');
  });

  it('格 = d/tol 双输入（空串 + placeholder = 继承默认；aria 报 (g 码, 码号)）', async () => {
    setDoc(TEST_DOC);
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const LE = '≤';
    const d = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-28"]')!;
    const tol = document.body.querySelector<HTMLInputElement>('[data-testid="tol-g01-28"]')!;
    // 未配置格渲染空串（= 继承默认 0/0），placeholder 提示上限
    expect(d.value).toBe('');
    expect(tol.value).toBe('');
    expect(d.placeholder).toBe(`d${LE}${MAX_OVERLAP_MM}`);
    expect(tol.placeholder).toBe(`t${LE}${MAX_ROTATION_TOL_DEG}`);
    expect(d.max).toBe(String(MAX_OVERLAP_MM));
    expect(tol.max).toBe(String(MAX_ROTATION_TOL_DEG));
    expect(d.getAttribute('aria-label')).toBe('裁片 g01 码 28 重合');
    expect(tol.getAttribute('aria-label')).toBe('裁片 g01 码 28 旋转');
    // 通用码行（null sizeKey）testid 用 'null'
    expect(
      document.body.querySelector('[data-testid="d-g01-null"]'),
    ).not.toBeNull();
  });

  it('doc 中该 g 码无此码号 → missing 格「—」；label 完全不在 doc → 可编辑', async () => {
    setDoc(TEST_DOC); // g02 仅 28 码；g03 不在 doc
    mockReps = {
      representatives: {
        ...TWO_REPS.representatives,
        g03: { label: 'g03', polygon: [[0, 0], [50, 0], [50, 50], [0, 50]] },
      },
    };
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const row30 = Array.from(document.body.querySelectorAll('tbody tr')).find(
      (tr) => tr.querySelector('.per-type-rowhead')!.textContent === '30',
    )!;
    const cells = Array.from(row30.querySelectorAll('td'));
    // 列序 g01/g02/g03：g01@30 正常、g02@30 missing、g03@30（不在 doc）可编辑
    expect(cells[0].classList.contains('missing')).toBe(false);
    expect(cells[1].classList.contains('missing')).toBe(true);
    expect(cells[1].querySelector('.per-type-missing')!.textContent).toBe('—');
    expect(cells[1].querySelector('input')).toBeNull();
    expect(cells[2].classList.contains('missing')).toBe(false);
    expect(cells[2].querySelectorAll('input').length).toBe(2);
  });

  it('thumbnail hover/aria =「g 码-放大预览」不含任何中文片型名', async () => {
    setDoc(TEST_DOC);
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const thumb = document.body.querySelector<HTMLButtonElement>('[data-testid="ptype-thumb-g01"]')!;
    expect(thumb.title).toBe('g01-放大预览');
    expect(thumb.getAttribute('aria-label')).toBe('g01-放大预览');
    expect(thumb.title).not.toContain('前片');
  });

  it('initial draft preserves form.per_type 非空值；不预填 0（空 = 继承）', () => {
    setDoc(TEST_DOC);
    useControlPanelStore.getState().openModal('per_type');
    const values: PerTypeFormMap = {
      g01: { '28': { d: '1.5', tol: '2' }, '30': { d: '', tol: '' } },
    };
    renderModal(values);
    const d28 = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-28"]');
    const tol28 = document.body.querySelector<HTMLInputElement>('[data-testid="tol-g01-28"]');
    const d30 = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-30"]');
    expect(d28!.value).toBe('1.5');
    expect(tol28!.value).toBe('2');
    // values 里全空的 ('30') 格子不预填 '0'：空串 = 继承默认
    expect(d30!.value).toBe('');
  });

  it('editing draft does NOT call onChange immediately', () => {
    const onChange = vi.fn();
    setDoc(TEST_DOC);
    useControlPanelStore.getState().openModal('per_type');
    const values: PerTypeFormMap = { g01: { '28': { d: '', tol: '' } } };
    renderModal(values, onChange);
    const dInput = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-28"]')!;
    act(() => {
      setInputValue(dInput, '2');
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('confirm：onChange 输出两级嵌套（含 g01@28 d=1.5）+ 剔除全空格子 + closes', () => {
    const onChange = vi.fn();
    setDoc(TEST_DOC);
    useControlPanelStore.getState().openModal('per_type');
    const values: PerTypeFormMap = { g01: { '28': { d: '', tol: '' }, '30': { d: '', tol: '' } } };
    renderModal(values, onChange);
    const d28 = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-28"]')!;
    const tol28 = document.body.querySelector<HTMLInputElement>('[data-testid="tol-g01-28"]')!;
    act(() => {
      setInputValue(d28, '1.5');
      setInputValue(tol28, '3');
    });
    // 另一格只填 tol（d 留空 = 继承）
    const d30 = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-30"]')!;
    act(() => {
      setInputValue(d30, '');
    });
    const tol30 = document.body.querySelector<HTMLInputElement>('[data-testid="tol-g01-30"]')!;
    act(() => {
      setInputValue(tol30, '45');
    });
    const confirm = document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!;
    act(() => confirm.click());
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as PerTypeFormMap;
    // 两级嵌套：{g01: {'28': {d:'1.5', tol:'3'}, '30': {d:'', tol:'45'}}}
    expect(next).toEqual({
      g01: {
        '28': { d: '1.5', tol: '3' },
        '30': { d: '', tol: '45' },
      },
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('confirm 剔除双侧全空的 (label,sizeKey) 与全空 label', () => {
    const onChange = vi.fn();
    setDoc(TEST_DOC);
    useControlPanelStore.getState().openModal('per_type');
    const values: PerTypeFormMap = {
      g01: { '28': { d: '', tol: '' } }, // 全空格
      g02: { '28': { d: '1', tol: '' } },
    };
    renderModal(values, onChange);
    // 把 g02@28 清空 → 两个 label 全空 → per_type 回写 {}
    const dG02 = document.body.querySelector<HTMLInputElement>('[data-testid="d-g02-28"]')!;
    act(() => {
      setInputValue(dG02, '');
    });
    const confirm = document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!;
    act(() => confirm.click());
    expect(onChange).toHaveBeenCalledWith({});
  });

  it('cancel does not call onChange (draft discarded)', () => {
    const onChange = vi.fn();
    setDoc(TEST_DOC);
    useControlPanelStore.getState().openModal('per_type');
    const values: PerTypeFormMap = { g01: { '28': { d: '', tol: '' } } };
    renderModal(values, onChange);
    const dInput = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-28"]')!;
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

  it('ESC closes (draft discarded) when previewLabel is null and fill closed', () => {
    const onChange = vi.fn();
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, onChange);
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('ESC does NOT close modal when previewLabel is open (双层独立)', () => {
    // 同时挂 PtypePreviewModal 模拟双层场景（生产时两者同挂于 ControlPanel）
    useControlPanelStore.getState().openModal('per_type');
    useControlPanelStore.getState().openPreviewLabel('g01');
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
    expect(useControlPanelStore.getState().previewLabel).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');
  });

  it('ESC 只关整列设值弹层（fill open 时 modal 保留）', async () => {
    setDoc(TEST_DOC);
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const fillBtn = document.body.querySelector<HTMLButtonElement>(
      '[data-testid="per-type-fill-btn-g01"]',
    )!;
    act(() => fillBtn.click());
    expect(document.body.querySelector('.qty-fill-popover')).not.toBeNull();
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    // 弹层关闭，modal 保留（三层独立 ESC）
    expect(document.body.querySelector('.qty-fill-popover')).toBeNull();
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

  it('blur clamps draft into [0, max] (d→10, tol→0)', async () => {
    setDoc(TEST_DOC);
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const dInput = document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-28"]')!;
    const tolInput = document.body.querySelector<HTMLInputElement>('[data-testid="tol-g01-28"]')!;
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

  it('mousedown inside modal does NOT bubble-close (modal self-click safe)', () => {
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    const modal = document.body.querySelector('.per-type-modal') as HTMLDivElement;
    act(() => {
      modal.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(useControlPanelStore.getState().modal).toBe('per_type');
  });

  // ------------------------------------------------------- ≡ 整列设值（US-004）
  it('≡ 整列设值：d=1 应用 → 该列全部行 d=1（确认输出断言）；留空侧继承', async () => {
    const onChange = vi.fn();
    setDoc(TEST_DOC); // 行 28/30/null
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal({}, onChange);
    await flushFetch();
    const fillBtn = document.body.querySelector<HTMLButtonElement>(
      '[data-testid="per-type-fill-btn-g01"]',
    )!;
    act(() => fillBtn.click());
    const popover = document.body.querySelector('.qty-fill-popover')!;
    expect(popover.getAttribute('aria-label')).toBe('裁片 g01 整列设值');
    const dFill = document.body.querySelector<HTMLInputElement>('[data-testid="per-type-fill-d"]')!;
    act(() => {
      setInputValue(dFill, '1');
    });
    act(() => {
      popover.querySelector<HTMLButtonElement>('.qty-fill-apply')!.click();
    });
    // 弹层关闭；格内即时生效（d=1、tol 空串 = 继承）
    expect(document.body.querySelector('.qty-fill-popover')).toBeNull();
    expect(
      document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-28"]')!.value,
    ).toBe('1');
    expect(
      document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-null"]')!.value,
    ).toBe('1');
    expect(
      document.body.querySelector<HTMLInputElement>('[data-testid="tol-g01-28"]')!.value,
    ).toBe('');
    // 确认输出：g01 列全部行（含通用 null 行）
    act(() => {
      document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!.click();
    });
    expect(onChange).toHaveBeenCalledWith({
      g01: {
        '28': { d: '1', tol: '' },
        '30': { d: '1', tol: '' },
        null: { d: '1', tol: '' },
      },
    });
  });

  it('≡ 整列设值：超限收边（d=99→10）；再全空应用 = 清空整列', async () => {
    const onChange = vi.fn();
    setDoc(TEST_DOC);
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal({ g01: { '28': { d: '5', tol: '' } } }, onChange);
    await flushFetch();
    const fillBtn = document.body.querySelector<HTMLButtonElement>(
      '[data-testid="per-type-fill-btn-g01"]',
    )!;
    act(() => fillBtn.click());
    const dFill = document.body.querySelector<HTMLInputElement>('[data-testid="per-type-fill-d"]')!;
    const tolFill = document.body.querySelector<HTMLInputElement>(
      '[data-testid="per-type-fill-tol"]',
    )!;
    act(() => {
      setInputValue(dFill, '99');
      setInputValue(tolFill, '12');
    });
    act(() => {
      document.body.querySelector<HTMLButtonElement>('.qty-fill-apply')!.click();
    });
    expect(
      document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-28"]')!.value,
    ).toBe('10');
    expect(
      document.body.querySelector<HTMLInputElement>('[data-testid="tol-g01-28"]')!.value,
    ).toBe('12');
    // 再全空应用 → 整列清空（= 继承默认），确认输出不含 g01
    act(() => fillBtn.click());
    const dFill2 = document.body.querySelector<HTMLInputElement>('[data-testid="per-type-fill-d"]')!;
    const tolFill2 = document.body.querySelector<HTMLInputElement>(
      '[data-testid="per-type-fill-tol"]',
    )!;
    act(() => {
      setInputValue(dFill2, '');
      setInputValue(tolFill2, '');
    });
    act(() => {
      document.body.querySelector<HTMLButtonElement>('.qty-fill-apply')!.click();
    });
    act(() => {
      document.body.querySelector<HTMLButtonElement>('.per-type-btn-confirm')!.click();
    });
    expect(onChange).toHaveBeenCalledWith({});
  });

  it('≡ 整列设值：取消 / 遮罩 mousedown 不写；Enter 快捷应用写入', async () => {
    setDoc(TEST_DOC);
    mockReps = TWO_REPS;
    useControlPanelStore.getState().openModal('per_type');
    renderModal();
    await flushFetch();
    const fillBtn = document.body.querySelector<HTMLButtonElement>(
      '[data-testid="per-type-fill-btn-g01"]',
    )!;
    // 取消：不写
    act(() => fillBtn.click());
    act(() => {
      setInputValue(
        document.body.querySelector<HTMLInputElement>('[data-testid="per-type-fill-d"]')!,
        '2',
      );
    });
    act(() => {
      document.body
        .querySelector('.qty-fill-popover')!
        .querySelector<HTMLButtonElement>('.qty-fill-cancel')!
        .click();
    });
    expect(document.body.querySelector('.qty-fill-popover')).toBeNull();
    expect(
      document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-28"]')!.value,
    ).toBe('');
    // 遮罩 mousedown：不写
    act(() => fillBtn.click());
    const backdrop = document.body.querySelector('[data-testid="per-type-fill-backdrop"]')!;
    act(() => {
      backdrop.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(document.body.querySelector('.qty-fill-popover')).toBeNull();
    expect(
      document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-28"]')!.value,
    ).toBe('');
    // Enter 快捷应用：写
    act(() => fillBtn.click());
    const dFill = document.body.querySelector<HTMLInputElement>('[data-testid="per-type-fill-d"]')!;
    act(() => {
      setInputValue(dFill, '3');
      dFill.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
    expect(
      document.body.querySelector<HTMLInputElement>('[data-testid="d-g01-28"]')!.value,
    ).toBe('3');
  });
});
