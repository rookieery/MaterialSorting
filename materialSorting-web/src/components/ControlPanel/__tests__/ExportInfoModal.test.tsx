// ExportInfoModal v3（2026-08-31 全 14 字段预览）测试：
//   1. mount → POST /api/plt-table-preview 载荷 = bestRun 几何子集（与 useExport
//      POST /export 同源字段：gate_mm/width_mm/density/placed）
//   2. 预览就绪 → 14 行按服务端返回列序（= 最终表格列序）交错渲染：自动字段
//      只读行展示成品串；手输槽位渲染输入框且值取**本地草稿**（非服务端 value）
//   3. 手输可编辑 → confirm 回调携带编辑后的完整 ExportTableFields
//   4. 预览失败（网络错 / rows 缺失）→ 降级 v2 形态（6 手输 + 提示行），
//      confirm 照常导出、无未处理 rejection
//   5. 无 bestRun → 不发预览请求，降级形态照常可确认
//
// 套路同 NestingPage/ExportButtons 既有用例：createRoot + act + data-testid；
// 不包 StrictMode（mount effect 只跑一次，fetch 计数确定）；
// markSessionProbedForTest 跳过 apiFetch 会话先行探测（不发 /api/session）。

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ExportInfoModal } from '../ExportInfoModal';
import { markSessionProbedForTest, resetSessionForTest } from '../../../lib/api';
import {
  EXPORT_TABLE_STORAGE_KEY,
  type ExportTableFields,
  type PltPreviewRow,
} from '../../../lib/exportTable';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { runRegistry, type RunRecord } from '../../../store/runRegistry';
import type { FrameMsg, ManifestMsg } from '../../../types/ws';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
let previewBodies: unknown[] = [];

/** 预览端点行为（每测可重设：默认成功返 PREVIEW_ROWS）。 */
let previewImpl: () => Response | Promise<Response> = () => json({ rows: PREVIEW_ROWS });

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

/** 14 行 fixture：与后端 _row_texts 列序同构（手输/自动交错）。 */
const PREVIEW_ROWS: PltPreviewRow[] = [
  { key: 'plan_name', label: '方案名称', value: '(30+34+35)+(31+32+33)*1.5+(36)*0.5=8套', manual: false },
  { key: 'bed_no', label: '床次', value: 'A料', manual: true },
  { key: 'warp_shrink', label: '经纱缩水', value: '0.0%', manual: true },
  { key: 'weft_shrink', label: '纬纱缩水', value: '0.0%', manual: true },
  { key: 'utilization', label: '利用率', value: '84.86%', manual: false },
  { key: 'gate', label: '幅宽', value: '1.980m', manual: false },
  { key: 'fabric_len', label: '料长', value: '7.101m', manual: false },
  { key: 'sets', label: '本床包含套数', value: '8', manual: false },
  { key: 'per_set', label: '每套用料', value: '0.888m', manual: false },
  { key: 'pieces', label: '片数', value: '160', manual: false },
  { key: 'planner', label: '排料师', value: '', manual: true },
  { key: 'draw_time', label: '绘图时间', value: '2026-08-31 15:02', manual: false },
  { key: 'style_no', label: '样板号', value: 'noname', manual: true },
  { key: 'remark', label: '备注', value: '', manual: true },
];

beforeEach(() => {
  runRegistry.clear();
  useControlPanelStore.getState().closeModal();
  markSessionProbedForTest();
  localStorage.removeItem(EXPORT_TABLE_STORAGE_KEY);
  previewBodies = [];
  previewImpl = () => json({ rows: PREVIEW_ROWS });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/api/plt-table-preview')) {
      previewBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      return Promise.resolve(previewImpl());
    }
    return Promise.resolve(json({}));
  }) as (...args: unknown[]) => Promise<Response>);
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
  fetchSpy?.mockRestore();
  resetSessionForTest();
  runRegistry.clear();
  useControlPanelStore.getState().closeModal();
});

/** 造一条有解 run（manifest gate 1980 + 最终帧 width 7100.5 / 2 placement / density 0.8838）。 */
function seedBestRun(): RunRecord {
  const rec = runRegistry.create(3);
  const manifest: ManifestMsg = {
    type: 'manifest', gate_mm: 1980, total_area_mm2: 1000000, n_eroded: 0, pieces: [],
  };
  const frame: FrameMsg = {
    type: 'frame', index: 5, elapsed: 120.5, phase: 'final',
    density: 0.8838, density_sparrow: 0.9, width_mm: 7100.5,
    placed_items: [
      { id: 'g01_30', rotation: 0, translation: [0, 0] },
      { id: 'g01_30', rotation: 180, translation: [500, 300] },
    ],
  };
  rec.manifest = manifest;
  rec.frames.push(frame);
  rec.lastFrame = frame;
  rec.finalDensity = 0.8838;
  rec.done = true;
  return rec;
}

function renderModal(
  onConfirm: (f: ExportTableFields) => void = vi.fn(),
  variant?: 'plt' | 'plt-clean',
): void {
  act(() => {
    root!.render(<ExportInfoModal exporting={false} onConfirm={onConfirm} variant={variant} />);
  });
}

function openModal(): void {
  act(() => {
    useControlPanelStore.getState().openModal('export_info');
  });
}

async function flush(times = 3): Promise<void> {
  for (let i = 0; i < times; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

/** 模拟用户输入（React 受控 input：原生 value setter + input 事件防值追踪吞改）。 */
function setInputValue(input: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const proto = input instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

function modal(): HTMLElement {
  return document.querySelector('.strategy-modal')!;
}

/** 弹窗体内 14 槽位 DOM 序（手输 → input/textarea id；自动 → export-info-auto-<key>）。 */
function rowOrder(): string[] {
  const els = modal().querySelectorAll(
    'input[id^="export-info-"], textarea[id^="export-info-"], .export-ro-row',
  );
  return Array.from(els).map((el) => {
    if (el instanceof HTMLElement && el.classList.contains('export-ro-row')) {
      return `auto:${el.dataset.testid}`;
    }
    return (el as HTMLElement).id;
  });
}

describe('ExportInfoModal v3 全 14 字段预览', () => {
  it('mount → POST /api/plt-table-preview 载荷 = bestRun 几何子集', async () => {
    seedBestRun();
    renderModal();
    openModal();
    await flush();
    expect(previewBodies).toHaveLength(1);
    expect(previewBodies[0]).toEqual({
      gate_mm: 1980,
      width_mm: 7100.5,
      density: 0.8838,
      placed: [
        { id: 'g01_30', rotation: 0, translation: [0, 0] },
        { id: 'g01_30', rotation: 180, translation: [500, 300] },
      ],
    });
  });

  it('预览就绪 → 14 行按服务端列序交错；自动字段只读成品串、手输取本地草稿', async () => {
    seedBestRun();
    // 本地草稿记忆：排料师 张三 —— 手输槽位渲染草稿而非服务端 value（''）
    localStorage.setItem(
      EXPORT_TABLE_STORAGE_KEY,
      JSON.stringify({ planner: '张三' }),
    );
    renderModal();
    openModal();
    await flush();
    // 14 槽 DOM 序 = fixture 列序（手输/自动交错，排料师在片数与绘图时间之间）
    expect(rowOrder()).toEqual([
      'auto:export-info-auto-plan_name',
      'export-info-bed-no',
      'export-info-warp-shrink',
      'export-info-weft-shrink',
      'auto:export-info-auto-utilization',
      'auto:export-info-auto-gate',
      'auto:export-info-auto-fabric_len',
      'auto:export-info-auto-sets',
      'auto:export-info-auto-per_set',
      'auto:export-info-auto-pieces',
      'export-info-planner',
      'auto:export-info-auto-draw_time',
      'export-info-style-no',
      'export-info-remark',
    ]);
    // 只读行展示成品串（非输入框，不可编辑）
    const plan = modal().querySelector('[data-testid="export-info-auto-plan_name"]')!;
    expect(plan.querySelector('.export-ro-value')!.textContent)
      .toBe('(30+34+35)+(31+32+33)*1.5+(36)*0.5=8套');
    expect(plan.querySelector('input')).toBeNull();
    expect(
      modal().querySelector('[data-testid="export-info-auto-utilization"] .export-ro-value')!
        .textContent,
    ).toBe('84.86%');
    // 手输槽位 = 本地草稿（localStorage 记忆张三），不取服务端 value
    const planner = modal().querySelector<HTMLInputElement>('#export-info-planner')!;
    expect(planner.value).toBe('张三');
  });

  it('手输可编辑 → confirm 携带编辑后完整草稿（预览不阻塞提交）', async () => {
    seedBestRun();
    const onConfirm = vi.fn();
    renderModal(onConfirm);
    openModal();
    await flush();
    setInputValue(
      modal().querySelector<HTMLInputElement>('#export-info-bed-no')!,
      '153',
    );
    await act(async () => {
      modal().querySelector<HTMLButtonElement>('[data-testid="export-info-confirm"]')!.click();
      await Promise.resolve();
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][0]).toEqual({
      bedNo: '153',
      warpShrink: '0.0%',
      weftShrink: '0.0%',
      planner: '',
      styleNo: 'noname',
      remark: '',
    });
  });

  it.each([
    ['网络错', () => Promise.reject(new Error('boom'))],
    ['rows 缺失', () => Promise.resolve(json({}))],
  ])('预览失败（%s）→ 降级 v2 形态（6 手输 + 提示行），confirm 照常', async (_name, impl) => {
    seedBestRun();
    previewImpl = impl;
    const onConfirm = vi.fn();
    renderModal(onConfirm);
    openModal();
    await flush();
    // v2 形态：6 手输在场、无只读行、提示行说明导出时自动计算
    expect(modal().querySelectorAll('input[id^="export-info-"], textarea[id^="export-info-"]'))
      .toHaveLength(6);
    expect(modal().querySelector('.export-ro-row')).toBeNull();
    const hint = modal().querySelector('[data-testid="export-info-auto-hint"]')!;
    expect(hint.textContent).toContain('自动计算');
    expect(hint.textContent).toContain('不可用');
    await act(async () => {
      modal().querySelector<HTMLButtonElement>('[data-testid="export-info-confirm"]')!.click();
      await Promise.resolve();
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('无 bestRun → 不发预览请求，降级形态照常可确认', async () => {
    // runRegistry 空（未求解）—— 导出按钮本就 disabled，纯防御路径
    const onConfirm = vi.fn();
    renderModal(onConfirm);
    openModal();
    await flush();
    expect(previewBodies).toHaveLength(0);
    expect(modal().querySelectorAll('input[id^="export-info-"], textarea[id^="export-info-"]'))
      .toHaveLength(6);
    await act(async () => {
      modal().querySelector<HTMLButtonElement>('[data-testid="export-info-confirm"]')!.click();
      await Promise.resolve();
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('弹窗先关 → 迟到预览响应被丢弃（不复活弹窗 / 无告警）', async () => {
    seedBestRun();
    let late: ((r: Response) => void) | null = null;
    previewImpl = () => new Promise<Response>((resolve) => {
      late = resolve;
    });
    renderModal();
    openModal();
    await flush();
    act(() => {
      useControlPanelStore.getState().closeModal();
    });
    expect(document.querySelector('.strategy-modal')).toBeNull();
    // 迟到响应到达 —— 弹窗不复活
    await act(async () => {
      late!(json({ rows: PREVIEW_ROWS }));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(document.querySelector('.strategy-modal')).toBeNull();
  });
});

describe('ExportInfoModal 毛版变体 variant（2026-08-31；当日由「净版」更名）', () => {
  it("variant='plt-clean' → 标题/aria/确认按钮带毛版文案；14 字段流程与全量版共用", async () => {
    seedBestRun();
    const onConfirm = vi.fn();
    renderModal(onConfirm, 'plt-clean');
    openModal();
    await flush();
    expect(modal().querySelector('.strategy-title')!.textContent).toContain('导出 PLT（毛版）');
    expect(modal().getAttribute('aria-label')).toBe('导出 PLT（毛版）唛架信息表格');
    const btn = modal().querySelector<HTMLButtonElement>('[data-testid="export-info-confirm"]')!;
    expect(btn.textContent).toContain('导出 PLT（毛版）');
    // 字段流程共用：14 行预览照常按服务端列序交错（手输草稿 + 只读行）
    expect(rowOrder()).toHaveLength(14);
    // 提示行说明毛版双表形态
    expect(modal().textContent).toContain('左右两端');
    await act(async () => {
      btn.click();
      await Promise.resolve();
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('缺省 variant（全量）→ 文案无毛版字样（回归锁）', async () => {
    seedBestRun();
    renderModal();
    openModal();
    await flush();
    expect(modal().querySelector('.strategy-title')!.textContent).not.toContain('毛版');
    expect(modal().querySelector('[data-testid="export-info-confirm"]')!.textContent)
      .not.toContain('毛版');
    expect(modal().textContent).not.toContain('左右两端');
  });
});
