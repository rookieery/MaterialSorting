// 编辑排料「智能微调」组件级单测（edit-polish US-003，2026-09-05）：
//   1) 点击微调 → POST /api/edit-polish 载荷形态正确（placed/gate_mm/exclude
//      best-effort：band → labels / final.prefix → pids / 皆无省略键）→ 成功后
//      working 替换 + 画布数据源更新（polygon points 跟随）+ 对比卡六指标渲染；
//   2) loading 态期间按钮禁用、重复点击零新增请求；
//   3) 一级撤销：恢复快照 working；再次微调覆盖快照；关闭后快照清空（重开撤销
//      按钮消失）；微调使 working 偏离 lastFrame → 关闭走 dirty 确认（不自动保存）；
//   4) 接口失败（网络 / 4xx error 文案 / placed 错位）→ 错误文案进卡、working
//      逐字段不变、编辑态不炸。
//
// 只 mock lib/api 的 apiFetch（真实 postEditPolish + 真实 modal state 机走通）；
// fixture 同 EditLayoutModal.hold.test（gate 1000 · a/b 两 500×500 方）。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditLayoutModal } from '../EditLayoutModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { useEditStore } from '../../../store/editStore';
import { runRegistry, type RunRecord } from '../../../store/runRegistry';
import type { FrameMsg, ManifestMsg } from '../../../types/ws';

vi.mock('../../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  apiFetch: vi.fn(),
}));

import { apiFetch } from '../../../lib/api';

const apiFetchMock = vi.mocked(apiFetch);

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

// ---- fixture：gate 1000 · a/b 两 500×500 方 @ [0,0] / [600,0] ----

function makeManifest(): ManifestMsg {
  return {
    type: 'manifest',
    gate_mm: 1000,
    total_area_mm2: 500000,
    n_eroded: 0,
    pieces: [
      {
        id: 'a_28',
        label: 'g01',
        size: 28,
        color: '#ff0000',
        area_mm2: 250000,
        polygon: [[0, 0], [500, 0], [500, 500], [0, 500]],
        net_polygon: [[50, 50], [450, 50], [450, 450], [50, 450]],
      },
      {
        id: 'b_30',
        label: 'g02',
        size: 30,
        color: '#00ff00',
        area_mm2: 250000,
        polygon: [[0, 0], [500, 0], [500, 500], [0, 500]],
      },
    ],
  };
}

function seedBestRun(): RunRecord {
  const run = runRegistry.create(0);
  run.manifest = makeManifest();
  const density = 500000 / (1100 * 1000);
  const frame: FrameMsg = {
    type: 'frame',
    index: 0,
    elapsed: 1,
    phase: 'final',
    density,
    density_sparrow: 0.5,
    width_mm: 1100,
    placed_items: [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [600, 0] },
    ],
  };
  run.frames.push(frame);
  run.lastFrame = frame;
  run.finalDensity = density;
  run.done = true;
  return run;
}

/** 微调成功响应（b_30 平移到 bx；report 七指标前后对照）。 */
function polishResponse(bx: number): Response {
  const body = {
    ok: true,
    placed: [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [bx, 0] },
    ],
    report: {
      before: {
        overlap_pairs: 1,
        max_penetration_mm: 4.2,
        total_overlap_area_mm2: 500.5,
        rotated_pieces: 1,
        rotation_dev_sum_deg: 25.0,
        width_mm: 1100,
        density: 45.455,
      },
      after: {
        overlap_pairs: 0,
        max_penetration_mm: 0,
        total_overlap_area_mm2: 0,
        rotated_pieces: 0,
        rotation_dev_sum_deg: 0,
        width_mm: 1100,
        density: 45.455,
      },
      moves: [{ index: 1, pid: 'b_30', kind: 'separate', from: [600, 0], to: [bx, 0] }],
      residual: [],
      excluded: [],
      elapsed_sec: 0.01,
    },
  };
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}

/** 到 /api/edit-polish 的 apiFetch 调用（心跳 /api/edit-hold 除外）。 */
function polishCalls(): Array<[string, RequestInit | undefined]> {
  return apiFetchMock.mock.calls.filter(([url]) => url === '/api/edit-polish') as Array<
    [string, RequestInit | undefined]
  >;
}

function polishBtn(): HTMLButtonElement {
  return document.querySelector('[data-testid="edit-polish-btn"]') as HTMLButtonElement;
}

async function openEditLayout(): Promise<void> {
  seedBestRun();
  await act(async () => {
    root!.render(<EditLayoutModal />);
    useControlPanelStore.getState().openModal('edit_layout');
  });
}

/** 点微调并等响应落定（mock 已预置）。 */
async function clickPolish(): Promise<void> {
  await act(async () => {
    polishBtn().click();
  });
}

/** 画布内 b 片毛版（stroke 尺码色 #00ff00）。 */
function roughB(): SVGPolygonElement {
  const svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
  return svg.querySelector(':scope g > polygon[stroke="#00ff00"]') as SVGPolygonElement;
}

function workingSnapshot(): string {
  return JSON.stringify(useEditStore.getState().working);
}

beforeEach(() => {
  apiFetchMock.mockReset().mockResolvedValue(undefined as unknown as Response);
  runRegistry.clear();
  useEditStore.getState().invalidate();
  useControlPanelStore.getState().closeModal();
  (window as unknown as { PointerEvent?: unknown }).PointerEvent = class extends MouseEvent {};
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
  runRegistry.clear();
  useEditStore.getState().invalidate();
  useControlPanelStore.getState().closeModal();
});

// ============================================================
// AC1：载荷形态 / working 替换 / 画布数据源 / loading 禁重复
// ============================================================

describe('EditLayoutModal 智能微调 (edit-polish US-003)', () => {
  it('点击微调 → POST /api/edit-polish 载荷正确（placed/gate_mm、无 band/prefix 记录省略 exclude 键）', async () => {
    apiFetchMock.mockImplementation(async (url) =>
      url === '/api/edit-polish' ? polishResponse(660) : (undefined as unknown as Response),
    );
    await openEditLayout();
    await clickPolish();
    const calls = polishCalls();
    expect(calls.length).toBe(1);
    const [url, init] = calls[0];
    expect(url).toBe('/api/edit-polish');
    expect(init?.method).toBe('POST');
    const body = JSON.parse((init?.body as string) ?? '{}');
    expect(body.gate_mm).toBe(1000);
    expect(body.placed).toEqual([
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [600, 0] },
    ]);
    expect('exclude' in body).toBe(false);
  });

  it('run 带 band 配置 → 载荷 exclude.labels 命中', async () => {
    seedBestRun().band = { enabled: true, label: 'g05' };
    apiFetchMock.mockImplementation(async (url) =>
      url === '/api/edit-polish' ? polishResponse(660) : (undefined as unknown as Response),
    );
    await openEditLayout();
    await clickPolish();
    const body = JSON.parse((polishCalls()[0][1]?.body as string) ?? '{}');
    expect(body.exclude).toEqual({ labels: ['g05'] });
  });

  it('final 带 prefix 统计段 → 载荷 exclude.pids 命中成员 pid（front/back/extra）', async () => {
    const run = seedBestRun();
    run.prefix = {
      size: 34,
      pid: 'PS_g02+g03@34+g02@32',
      extra: { pid: 'g02_32', label: 'g02', size: 32, rotation: 180 },
      residual_mm: 3.2,
      fallback: false,
    };
    apiFetchMock.mockImplementation(async (url) =>
      url === '/api/edit-polish' ? polishResponse(660) : (undefined as unknown as Response),
    );
    await openEditLayout();
    await clickPolish();
    const body = JSON.parse((polishCalls()[0][1]?.body as string) ?? '{}');
    expect(body.exclude).toEqual({ pids: ['g02_34', 'g03_34', 'g02_32'] });
  });

  it('成功后 working 替换 + 画布数据源更新 + 对比卡六指标/撤销按钮渲染（口径注记在按钮 title）', async () => {
    const run = seedBestRun();
    apiFetchMock.mockImplementation(async (url) =>
      url === '/api/edit-polish' ? polishResponse(660) : (undefined as unknown as Response),
    );
    await openEditLayout();
    await clickPolish();
    // working 替换（b 平移 600→660；未保存：lastFrame 不动）
    expect(useEditStore.getState().working[1].translation).toEqual([660, 0]);
    expect(run.lastFrame!.placed_items[1].translation).toEqual([600, 0]);
    // 画布数据源更新（命令式 polygon points 跟随）
    expect(roughB().getAttribute('points')!.startsWith('660,0')).toBe(true);
    // 对比卡：六指标 + 撤销按钮（口径注记 2026-09-05 三轮迭代起在按钮 title 悬浮，
    // 卡内可见脚注已移除）
    const card = document.querySelector('[data-testid="edit-polish-card"]');
    expect(card).not.toBeNull();
    expect(
      document.querySelector('[data-testid="edit-polish-overlap"]')!.textContent,
    ).toContain('1 → 0');
    expect(
      document.querySelector('[data-testid="edit-polish-depth"]')!.textContent,
    ).toContain('4.20 → 0.00 mm');
    expect(document.querySelector('[data-testid="edit-polish-rot"]')!.textContent).toContain(
      '1 → 0',
    );
    expect(
      document.querySelector('[data-testid="edit-polish-rotsum"]')!.textContent,
    ).toContain('25.0 → 0.0');
    expect(
      document.querySelector('[data-testid="edit-polish-width"]')!.textContent,
    ).toContain('1100.0 → 1100.0 mm');
    expect(
      document.querySelector('[data-testid="edit-polish-density"]')!.textContent,
    ).toContain('45.45 → 45.45 %');
    expect(card!.textContent).not.toContain('物理毛版轮廓口径'); // 可见脚注已移除（不占卡内空间）
    const polishBtnTitle =
      document.querySelector('[data-testid="edit-polish-btn"]')?.getAttribute('title') ?? '';
    expect(polishBtnTitle).toContain('物理毛版轮廓口径');
    expect(polishBtnTitle).toContain('腐蚀后轮廓口径');
    expect(
      document.querySelector('[data-testid="edit-polish-undo"]')!.textContent,
    ).toContain('撤销微调');
    // 状态条同真相源跟随（b@660 → 包络 1160）
    expect(
      document.querySelector('[data-testid="edit-layout-width"]')!.textContent,
    ).toContain('1160');
  });

  it('loading 态期间按钮禁用、重复点击零新增请求', async () => {
    let resolvePolish: ((r: Response) => void) | null = null;
    apiFetchMock.mockImplementation(async (url) => {
      if (url === '/api/edit-polish') {
        return new Promise<Response>((res) => {
          resolvePolish = res;
        });
      }
      return undefined as unknown as Response;
    });
    await openEditLayout();
    await clickPolish();
    const btn = polishBtn();
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain('微调中');
    // 禁用态下再点（防御：直接调 click 也不发新请求）
    await act(async () => {
      btn.click();
      btn.click();
    });
    expect(polishCalls().length).toBe(1);
    // 响应落定 → 恢复可点
    await act(async () => {
      resolvePolish!(polishResponse(660));
    });
    expect(polishBtn().disabled).toBe(false);
    expect(polishBtn().textContent).toContain('智能微调');
  });

  // ============================================================
  // US-005：compact 压缩回收档 checkbox（对比卡内，默认不勾、随下次请求发出）
  // ============================================================

  it('US-005 compact checkbox 随对比卡渲染且默认不勾 → 载荷省略 compact 键', async () => {
    apiFetchMock.mockImplementation(async (url) =>
      url === '/api/edit-polish' ? polishResponse(660) : (undefined as unknown as Response),
    );
    await openEditLayout();
    // 微调前卡未渲染 → checkbox 不在
    expect(document.querySelector('[data-testid="edit-polish-compact"]')).toBeNull();
    await clickPolish();
    const body = JSON.parse((polishCalls()[0][1]?.body as string) ?? '{}');
    expect('compact' in body).toBe(false);
    const cb = document.querySelector(
      '[data-testid="edit-polish-compact"]',
    ) as HTMLInputElement;
    expect(cb).not.toBeNull();
    expect(cb.checked).toBe(false);
    expect(cb.closest('.edit-polish-card')).not.toBeNull();   // 卡内（PRD：报告卡内）
  });

  it('US-005 勾选 compact → 下次微调请求 compact:true；撤销卡清空后 checkbox 消失、勾选态受控保持', async () => {
    apiFetchMock.mockImplementation(async (url) =>
      url === '/api/edit-polish' ? polishResponse(660) : (undefined as unknown as Response),
    );
    await openEditLayout();
    await clickPolish();                                        // 首次：无 compact 键
    await act(async () => {
      (
        document.querySelector('[data-testid="edit-polish-compact"]') as HTMLInputElement
      ).click();
    });
    await clickPolish();                                        // 第二次：compact:true
    const calls = polishCalls();
    const body0 = JSON.parse((calls[0][1]?.body as string) ?? '{}');
    const body1 = JSON.parse((calls[1][1]?.body as string) ?? '{}');
    expect('compact' in body0).toBe(false);
    expect(body1.compact).toBe(true);
    // 受控勾选态跨次微调保持（卡随新报告重渲染不丢）
    expect(
      (document.querySelector('[data-testid="edit-polish-compact"]') as HTMLInputElement)
        .checked,
    ).toBe(true);
    // 撤销 → 卡整体清空 → checkbox 随之消失
    await act(async () => {
      (document.querySelector('[data-testid="edit-polish-undo"]') as HTMLButtonElement).click();
    });
    expect(document.querySelector('[data-testid="edit-polish-compact"]')).toBeNull();
  });

  // ============================================================
  // AC2：一级撤销 / 快照覆盖 / 关闭清空
  // ============================================================

  it('撤销微调恢复快照 working，卡清空、撤销按钮消失', async () => {
    apiFetchMock.mockImplementation(async (url) =>
      url === '/api/edit-polish' ? polishResponse(660) : (undefined as unknown as Response),
    );
    await openEditLayout();
    await clickPolish();
    expect(useEditStore.getState().working[1].translation).toEqual([660, 0]);
    await act(async () => {
      (document.querySelector('[data-testid="edit-polish-undo"]') as HTMLButtonElement).click();
    });
    // 快照恢复 = 微调前 working（b@600）；卡/按钮清空
    expect(useEditStore.getState().working[1].translation).toEqual([600, 0]);
    expect(document.querySelector('[data-testid="edit-polish-card"]')).toBeNull();
    expect(document.querySelector('[data-testid="edit-polish-undo"]')).toBeNull();
    expect(roughB().getAttribute('points')!.startsWith('600,0')).toBe(true);
  });

  it('再次微调覆盖快照（撤销回到上一次微调前，非最初）', async () => {
    let bx = 660;
    apiFetchMock.mockImplementation(async (url) =>
      url === '/api/edit-polish' ? polishResponse(bx) : (undefined as unknown as Response),
    );
    await openEditLayout();
    await clickPolish(); // 第一次：b@660，快照 = b@600
    bx = 720;
    await clickPolish(); // 第二次：b@720，快照覆盖 = b@660
    expect(useEditStore.getState().working[1].translation).toEqual([720, 0]);
    await act(async () => {
      (document.querySelector('[data-testid="edit-polish-undo"]') as HTMLButtonElement).click();
    });
    // 撤销回到第二次微调前（b@660），不是最初基线（b@600）
    expect(useEditStore.getState().working[1].translation).toEqual([660, 0]);
  });

  it('微调后关闭（dirty 确认弃稿）→ 重开快照清空：撤销按钮/对比卡消失', async () => {
    apiFetchMock.mockImplementation(async (url) =>
      url === '/api/edit-polish' ? polishResponse(660) : (undefined as unknown as Response),
    );
    await openEditLayout();
    await clickPolish();
    expect(document.querySelector('[data-testid="edit-polish-undo"]')).not.toBeNull();
    // 微调写 working 未保存 → dirty → 关闭弹确认（不自动保存语义）
    await act(async () => {
      (document.querySelector('[data-testid="edit-layout-close"]') as HTMLButtonElement).click();
    });
    expect(document.querySelector('[data-testid="edit-confirm-overlay"]')).not.toBeNull();
    await act(async () => {
      (document.querySelector('[data-testid="edit-confirm-ok"]') as HTMLButtonElement).click();
    });
    // 重开（Inner 卸载重挂 → polish state 机清零）
    await act(async () => {
      useControlPanelStore.getState().openModal('edit_layout');
    });
    expect(document.querySelector('[data-testid="edit-polish-undo"]')).toBeNull();
    expect(document.querySelector('[data-testid="edit-polish-card"]')).toBeNull();
    // working 从 lastFrame 重新快照 = 算法基线（弃稿语义）
    expect(useEditStore.getState().working[1].translation).toEqual([600, 0]);
  });

  // ============================================================
  // AC3：失败 → 错误文案进卡、working 逐字段不变
  // ============================================================

  it('接口 4xx → 卡内错误文案（服务端 error 透传）、working 逐字段不变、撤销按钮不出现', async () => {
    apiFetchMock.mockImplementation(async (url) => {
      if (url === '/api/edit-polish') {
        return {
          ok: false,
          status: 400,
          json: async () => ({
            error: "pid 'zz_9' 不在会话 pieces_by_id（母版已变更？请重新求解/上传）",
          }),
        } as unknown as Response;
      }
      return undefined as unknown as Response;
    });
    await openEditLayout();
    const before = workingSnapshot();
    await clickPolish();
    const err = document.querySelector('[data-testid="edit-polish-error"]');
    expect(err).not.toBeNull();
    expect(err!.textContent).toContain('微调失败');
    expect(err!.textContent).toContain('母版已变更');
    // working 逐字段不变（快照字符串全等）
    expect(workingSnapshot()).toBe(before);
    expect(useEditStore.getState().working[1].translation).toEqual([600, 0]);
    expect(document.querySelector('[data-testid="edit-polish-undo"]')).toBeNull();
    expect(document.querySelector('[data-testid="edit-polish-card"]')).not.toBeNull();
  });

  it('网络错 → 错误文案进卡（message 直显）、working 不变、编辑态不炸', async () => {
    apiFetchMock.mockImplementation(async (url) => {
      if (url === '/api/edit-polish') throw new Error('网络中断');
      return undefined as unknown as Response;
    });
    await openEditLayout();
    const before = workingSnapshot();
    await clickPolish();
    expect(
      document.querySelector('[data-testid="edit-polish-error"]')!.textContent,
    ).toContain('网络中断');
    expect(workingSnapshot()).toBe(before);
    // 编辑态不炸：弹窗仍在、按钮恢复可点
    expect(document.querySelector('[data-testid="edit-layout-overlay"]')).not.toBeNull();
    expect(polishBtn().disabled).toBe(false);
    expect(polishBtn().textContent).toContain('智能微调');
  });

  it('响应 placed 与 working 条数错位 → 按失败处理（错误文案、working 不变）', async () => {
    apiFetchMock.mockImplementation(async (url) => {
      if (url === '/api/edit-polish') {
        const r = polishResponse(660);
        const orig = r.json;
        // 篡改 placed 只剩一条（模拟异常响应 —— replaceWorking 条数闸拒绝）
        return {
          ok: true,
          status: 200,
          json: async () => {
            const d = (await orig()) as { placed: unknown[]; [k: string]: unknown };
            return { ...d, placed: d.placed.slice(0, 1) };
          },
        } as unknown as Response;
      }
      return undefined as unknown as Response;
    });
    await openEditLayout();
    const before = workingSnapshot();
    await clickPolish();
    expect(document.querySelector('[data-testid="edit-polish-error"]')).not.toBeNull();
    expect(workingSnapshot()).toBe(before);
    expect(document.querySelector('[data-testid="edit-polish-undo"]')).toBeNull();
  });
});
