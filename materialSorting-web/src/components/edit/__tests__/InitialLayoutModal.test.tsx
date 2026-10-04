// InitialLayoutModal 单测（prd-initial-layout US-006）：
//   1) 声明式受控：modal !== 'initial_layout' 不渲染；openModal → Portal 挂 body；
//   2) 打开编排：无 saved → 自动生成（POST /api/initial-layout/generate，seed =
//      genSeed；busy 浮层 + ✕/刷新/保存全禁）；saved 指纹新鲜 → 续编（不发请求，
//      working = displayPlaced）；saved 指纹失效 → 重生成；
//   3) 生成失败 → 红字 + 空态文案（「布局刷新」即重试入口）；
//   4) 保存闸：红色重叠计数 >0 → 保存 disabled + 数量提示（琥珀压线不限）；
//   5) 保存组装（plain）：displayPlaced = working 最新值 / warmPlaced 三键全量 /
//      demandMap null / fingerprint / widthMm / manifest / prefixMemberPids +
//      registry 伪卡片（INITIAL_LAYOUT_SEED 哨兵、finalDensity 0、bestRun 跳过）
//      + 关窗；
//   6) 保存组装（band 组）：pieceGroup 标记 + WB_ 组条目位移记账（组 delta 叠加）；
//   7) 布局刷新：无编辑直刷（bumpGenSeed 换 seed）；有编辑 → 确认层「将丢弃当前
//      编辑」→ 取消保持 / 确认重生成（working 换新基线）；
//   8) ✕ dirty 确认层（放弃未保存的修改？→ 取消保持 / 确认关窗）；
//   9) edit_hold 心跳：mount 即 POST /api/edit-hold；
//  10) 重叠序号定位（2026-10-04）：chips 渲染在提示上方 + 点击高亮/再点取消 +
//      编号 mousedown 冻结（键盘路径不刷、画布 pointerdown 刷）+ 实时计数归零
//      chips 行与高亮同帧撤销。
//  11) 批量框选接线（2026-10-04 用户需求）：EditCanvas marqueeSelect 透传 → 画布
//      工具区「区域选择」按钮在场（交互细节单测在 EditCanvas.marquee.test）。
//
// 套路同 EditLayoutModal 既有用例：createRoot + act + data-testid；不包 StrictMode
//（StrictMode 双 mount 由组件内 bootRef 防双请求，见组件头注）。lib/api 整体 mock
//（apiFetch 路由表 —— generate / edit-hold 共用出口，hold.test 同款 importOriginal）。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { InitialLayoutModal } from '../InitialLayoutModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { useEditStore } from '../../../store/editStore';
import { INITIAL_LAYOUT_SEED, runRegistry } from '../../../store/runRegistry';
import {
  __resetInitialLayoutStoreForTest,
  initialLayoutFingerprint,
  useInitialLayoutStore,
  type SavedInitialLayout,
} from '../../../store/initialLayoutStore';
import { useFormStore } from '../../../store/formStore';
import { useQtyStore } from '../../../store/qtyStore';
import { collectStartContext } from '../../../lib/params';
import type { PlacedItem, Polygon, Pt } from '../../../types/piece';
import type { ManifestMsg } from '../../../types/ws';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---- lib/api mock（apiFetch 路由表：未命中 → 200 {ok:true}（edit-hold 等）；值
// 为 Response 实例则原样返回（状态码控制），否则 JSON 包装）----
const { apiCalls, apiRoutes } = vi.hoisted(() => ({
  apiCalls: [] as { url: string; init?: RequestInit }[],
  apiRoutes: {} as Record<string, () => unknown>,
}));
vi.mock('../../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  apiFetch: vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    apiCalls.push({ url: u, init });
    const hit = apiRoutes[u];
    const r = hit ? await hit() : { ok: true };
    if (r instanceof Response) return r;
    return new Response(JSON.stringify(r), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }),
}));

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  apiCalls.length = 0;
  for (const k of Object.keys(apiRoutes)) delete apiRoutes[k];
  runRegistry.clear();
  useEditStore.getState().invalidate();
  useControlPanelStore.getState().closeModal();
  __resetInitialLayoutStoreForTest();
  useFormStore.getState().reset();
  useQtyStore.getState().resetQuantities();
  (window as unknown as { PointerEvent?: unknown }).PointerEvent =
    class extends MouseEvent {};
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
  __resetInitialLayoutStoreForTest();
});

// ---- fixture：gate 1000 · a/b 两 500×500 方 @ [0,0] / [600,0] → 包络 1100；
// total_area 500000 → density = 500000/(1100×1000)（45.45%）----

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
        polygon: [
          [0, 0], [500, 0], [500, 500], [0, 500],
        ],
        net_polygon: [
          [50, 50], [450, 50], [450, 450], [50, 450],
        ],
      },
      {
        id: 'b_30',
        label: 'g02',
        size: 30,
        color: '#00ff00',
        area_mm2: 250000,
        polygon: [
          [0, 0], [500, 0], [500, 500], [0, 500],
        ],
      },
    ],
  };
}

/** 展开 placed：两方分离（合法基线）。 */
const PLACED_OK: PlacedItem[] = [
  { id: 'a_28', rotation: 0, translation: [0, 0] as Pt },
  { id: 'b_30', rotation: 0, translation: [600, 0] as Pt },
];
const DENSITY_OK = 500000 / (1100 * 1000);

/** 生成响应（plain / 带 composite 可选）。 */
function genBody(
  opts?: { placed?: PlacedItem[]; composite?: unknown; manifest?: ManifestMsg },
): unknown {
  return {
    ok: true,
    manifest: opts?.manifest ?? makeManifest(),
    placed: opts?.placed ?? PLACED_OK,
    width_mm: 1100,
    density: DENSITY_OK,
    ...(opts?.composite !== undefined ? { composite: opts.composite } : {}),
  };
}

/** 当前表单/数量状态下应得的指纹（与组件内 collectStartContext 同源）。 */
function expectedFingerprint(): string {
  const ctx = collectStartContext(
    useFormStore.getState().form,
    useQtyStore.getState().quantities,
  );
  return initialLayoutFingerprint({
    sizes: ctx.sizes,
    per_type: ctx.per_type,
    quantities: ctx.quantities,
    params: ctx.params,
    gate_mm: ctx.gate_mm,
    band: ctx.band,
    prefix: ctx.prefix,
  });
}

/** 续编用 saved 记录（新鲜指纹）。 */
function makeSaved(overrides?: Partial<SavedInitialLayout>): SavedInitialLayout {
  return {
    displayPlaced: PLACED_OK.map((it) => ({ ...it, translation: [...it.translation] as Pt })),
    warmPlaced: PLACED_OK.map((it) => ({
      id: it.id,
      rotation: it.rotation,
      translation: [...it.translation] as Pt,
    })),
    demandMap: null,
    fingerprint: expectedFingerprint(),
    widthMm: 1100,
    bandUsed: false,
    prefixUsed: false,
    manifest: makeManifest(),
    prefixMemberPids: [],
    ...overrides,
  };
}

function renderModal(): void {
  act(() => {
    root!.render(<InitialLayoutModal />);
  });
}

/** 打开弹窗（默认路由 = 生成成功 plain）。 */
async function openModalFresh(): Promise<void> {
  apiRoutes['/api/initial-layout/generate'] = () => genBody();
  renderModal();
  act(() => {
    useControlPanelStore.getState().openModal('initial_layout');
  });
  await act(async () => {}); // flush 生成 promise
}

function overlay(): HTMLElement | null {
  return document.querySelector('[data-testid="initial-layout-overlay"]');
}

function q(tid: string): HTMLElement | null {
  return document.querySelector(`[data-testid="${tid}"]`);
}

function click(el: Element | null): void {
  act(() => {
    (el as unknown as HTMLButtonElement).click();
  });
}

function genCalls(): { url: string; init?: RequestInit }[] {
  return apiCalls.filter((c) => c.url === '/api/initial-layout/generate');
}

describe('InitialLayoutModal 声明式受控 + 打开编排 (US-006)', () => {
  it('modal=null 不渲染（默认关闭）', () => {
    renderModal();
    expect(overlay()).toBeNull();
  });

  it("openModal('initial_layout') → Portal 挂 body；closeModal 后移除", async () => {
    await openModalFresh();
    expect(overlay()).not.toBeNull();
    act(() => {
      useControlPanelStore.getState().closeModal();
    });
    expect(overlay()).toBeNull();
  });

  it('无 saved → 自动生成（POST generate，seed=genSeed=0 + 同源上下文键）+ 心跳 hold', async () => {
    await openModalFresh();
    const calls = genCalls();
    expect(calls).toHaveLength(1);
    const body = JSON.parse(String(calls[0].init!.body)) as Record<string, unknown>;
    expect(body.seed).toBe(0);
    expect(body.gate_mm).toBe(1750); // 默认表单 gate 175cm ×10
    // 生成成功 → 画布（EditCanvas svg）+ 状态条初值（同一真相源）
    expect(q('initial-layout-overlay')!.querySelector('svg')).not.toBeNull();
    expect(q('initial-layout-width')!.textContent).toContain('1100');
    expect(q('initial-layout-density')!.textContent).toContain('45.45');
    // 无 Δ 行（初始布局无「相对基线」语义）
    expect(q('edit-layout-delta')).toBeNull();
    // edit_hold 心跳：mount 即 POST /api/edit-hold（失败静默，200 路由）
    expect(apiCalls.some((c) => c.url === '/api/edit-hold')).toBe(true);
  });

  it('生成在飞 = busy 态：浮层 + ✕/布局刷新/保存 全禁', async () => {
    // 永不 resolve 的生成请求（挂起态观察）
    apiRoutes['/api/initial-layout/generate'] = () => new Promise(() => {});
    renderModal();
    act(() => {
      useControlPanelStore.getState().openModal('initial_layout');
    });
    await act(async () => {});
    expect(q('initial-layout-generating')).not.toBeNull();
    expect((q('initial-layout-close') as HTMLButtonElement).disabled).toBe(true);
    expect((q('initial-layout-refresh') as HTMLButtonElement).disabled).toBe(true);
    expect((q('initial-layout-save') as HTMLButtonElement).disabled).toBe(true);
  });

  it('画布工具区含「区域选择」批量框选按钮（marqueeSelect 接线，2026-10-04）', async () => {
    await openModalFresh();
    const btn = q('edit-marquee-toggle');
    expect(btn).not.toBeNull();
    expect(btn!.textContent).toContain('区域选择');
    expect(btn!.closest('.edit-layout-canvas-tools')).not.toBeNull(); // 形态 select 同排
  });

  it('saved 指纹新鲜 → 载入续编（零请求，working = displayPlaced，状态条回显）', async () => {
    useInitialLayoutStore.getState().setSaved(makeSaved());
    renderModal();
    act(() => {
      useControlPanelStore.getState().openModal('initial_layout');
    });
    await act(async () => {});
    expect(genCalls()).toHaveLength(0); // 不生成
    expect(useEditStore.getState().working).toEqual(PLACED_OK);
    expect(q('initial-layout-width')!.textContent).toContain('1100');
    // 续编不占 busy 态
    expect(q('initial-layout-generating')).toBeNull();
  });

  it('saved 指纹失效（stale）→ 忽略续编自动重生成', async () => {
    useInitialLayoutStore.getState().setSaved(makeSaved({ fingerprint: 'stale-fp' }));
    apiRoutes['/api/initial-layout/generate'] = () => genBody();
    renderModal();
    act(() => {
      useControlPanelStore.getState().openModal('initial_layout');
    });
    await act(async () => {});
    expect(genCalls()).toHaveLength(1);
    expect(useEditStore.getState().working).toEqual(PLACED_OK);
  });

  it('生成失败（502 error 透传）→ footer 红字 + 空态文案 + 保存禁用；刷新可重试', async () => {
    apiRoutes['/api/initial-layout/generate'] = () =>
      new Response(JSON.stringify({ error: '求解失败: worker exited (code=1)' }), {
        status: 502,
        headers: { 'Content-Type': 'application/json' },
      });
    renderModal();
    act(() => {
      useControlPanelStore.getState().openModal('initial_layout');
    });
    await act(async () => {});
    expect(q('initial-layout-error')!.textContent).toContain(
      '初始布局生成失败：求解失败: worker exited (code=1)',
    );
    expect(q('initial-layout-empty')!.textContent).toContain('初始布局生成失败');
    expect((q('initial-layout-save') as HTMLButtonElement).disabled).toBe(true);
    // 「布局刷新」即重试入口：路由修复后刷新 → 成功落画布
    apiRoutes['/api/initial-layout/generate'] = () => genBody();
    click(q('initial-layout-refresh'));
    await act(async () => {});
    expect(q('initial-layout-error')).toBeNull();
    expect(q('initial-layout-overlay')!.querySelector('svg')).not.toBeNull();
  });
});

describe('保存闸 + 保存组装 (US-006)', () => {
  it('红色重叠计数 >0 → 保存 disabled + 数量提示（交叠双方各计 1）', async () => {
    // a@[0,0] b@[400,50] 交 100×450：顶点采样 pen 50 > 额度 0 → 红（完全同位是
    // 边对齐退化口径 pen=0 —— EditCanvas.initial 同款已知近似，故用错位交叠）。
    apiRoutes['/api/initial-layout/generate'] = () =>
      genBody({
        placed: [
          { id: 'a_28', rotation: 0, translation: [0, 0] as Pt },
          { id: 'b_30', rotation: 0, translation: [400, 50] as Pt },
        ],
      });
    renderModal();
    act(() => {
      useControlPanelStore.getState().openModal('initial_layout');
    });
    await act(async () => {});
    const save = q('initial-layout-save') as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(q('initial-layout-save-hint')!.textContent).toMatch(/存在 \d+ 片非法（红色）重叠/);
  });

  it('solver 贴解压线形态（穿透微超额度、碰撞轮廓不相交）不锁保存闸 —— 2026-10-04 判红口径回归锁', async () => {
    // 双片 raw 500² / erode 实际内缩 27.5、声明 d=5（额度 10）：a@[0,0]/
    // b@[489.6,50] raw 交 10.4×450、pen 10.4 > 额度 —— 旧「穿透 > 额度」判据下
    // 生成即锁保存闸（用户报障形态：高级配置设重合 d 后初始布局无法保存）；
    // 碰撞轮廓 erode a x[27.5,472.5] / b x[517.1,...] 不相交 → 琥珀，保存可点。
    const inset: Polygon = [
      [27.5, 27.5],
      [472.5, 27.5],
      [472.5, 472.5],
      [27.5, 472.5],
    ];
    const raw: Polygon = [
      [0, 0],
      [500, 0],
      [500, 500],
      [0, 500],
    ];
    const manifest: ManifestMsg = {
      ...makeManifest(),
      pieces: [
        {
          id: 'a_28',
          label: 'g01',
          size: 28,
          color: '#ff0000',
          area_mm2: 250000,
          polygon: inset,
          raw_polygon: raw,
          d_mm: 5,
        },
        {
          id: 'b_30',
          label: 'g02',
          size: 30,
          color: '#00ff00',
          area_mm2: 250000,
          polygon: inset,
          raw_polygon: raw,
          d_mm: 5,
        },
      ],
    };
    apiRoutes['/api/initial-layout/generate'] = () =>
      genBody({
        manifest,
        placed: [
          { id: 'a_28', rotation: 0, translation: [0, 0] as Pt },
          { id: 'b_30', rotation: 0, translation: [489.6, 50] as Pt },
        ],
      });
    renderModal();
    act(() => {
      useControlPanelStore.getState().openModal('initial_layout');
    });
    await act(async () => {});
    const save = q('initial-layout-save') as HTMLButtonElement;
    expect(save.disabled).toBe(false);
    expect(q('initial-layout-save-hint')).toBeNull();
  });

  it('plain 保存：saved 全字段形态 + registry 伪卡片 + bestRun 跳过 + 关窗', async () => {
    await openModalFresh();
    // 编辑一片（保存前 working 最新值进 displayPlaced —— 组装数据源验证）
    act(() => {
      useEditStore.getState().setWorkingItem(0, { translation: [10, 10] });
    });
    const save = q('initial-layout-save') as HTMLButtonElement;
    expect(save.disabled).toBe(false);
    click(save);
    await act(async () => {});

    const saved = useInitialLayoutStore.getState().saved;
    expect(saved).not.toBeNull();
    expect(saved!.displayPlaced).toEqual([
      { id: 'a_28', rotation: 0, translation: [10, 10] },
      { id: 'b_30', rotation: 0, translation: [600, 0] },
    ]);
    // plain：warmPlaced = working 全条目三键形态（与 displayPlaced 同值）
    expect(saved!.warmPlaced).toEqual(saved!.displayPlaced);
    for (const it of saved!.warmPlaced) {
      expect(Object.keys(it).sort()).toEqual(['id', 'rotation', 'translation']);
    }
    expect(saved!.demandMap).toBeNull();
    expect(saved!.fingerprint).toBe(expectedFingerprint());
    expect(saved!.widthMm).toBe(1100);
    expect(saved!.bandUsed).toBe(false);
    expect(saved!.prefixUsed).toBe(false);
    expect(saved!.manifest).toEqual(makeManifest());
    expect(saved!.prefixMemberPids).toEqual([]);

    // registry 伪卡片：哨兵 seed + lastFrame 回显 + finalDensity 恒 0 + done + bestRun 跳过
    const runs = runRegistry.list();
    expect(runs).toHaveLength(1);
    expect(runs[0].seed).toBe(INITIAL_LAYOUT_SEED);
    expect(runs[0].finalDensity).toBe(0);
    expect(runs[0].done).toBe(true);
    expect(runs[0].lastFrame!.placed_items).toEqual(saved!.displayPlaced);
    expect(runs[0].lastFrame!.width_mm).toBe(1100);
    expect(runRegistry.bestRun()).toBeNull(); // 未求解布局不进导出/编辑选源

    // 关窗
    expect(overlay()).toBeNull();
  });

  it('重复保存伪卡片去重（恒至多一张）', async () => {
    await openModalFresh();
    click(q('initial-layout-save'));
    await act(async () => {});
    // 重开（saved 新鲜 → 续编零请求）→ 再保存
    act(() => {
      useControlPanelStore.getState().openModal('initial_layout');
    });
    await act(async () => {});
    click(q('initial-layout-save'));
    await act(async () => {});
    const sentinelRuns = runRegistry.list().filter((r) => r.seed === INITIAL_LAYOUT_SEED);
    expect(sentinelRuns).toHaveLength(1);
  });

  it('band 组保存：pieceGroup 标记 + WB_ 组条目位移记账 + demandMap 透传', async () => {
    // band 开（label 'g01' 须过 ^g\d+$ —— 用 g01_28 片名的 band 变体夹具）
    const manifestG = makeManifest();
    manifestG.pieces[0] = { ...manifestG.pieces[0], id: 'g01_28' };
    useFormStore.getState().patch({ band_enabled: true, band_label: 'g01' });
    apiRoutes['/api/initial-layout/generate'] = () => ({
      ok: true,
      manifest: manifestG,
      placed: [
        { id: 'g01_28', rotation: 0, translation: [0, 0] },
        { id: 'b_30', rotation: 0, translation: [600, 0] },
      ],
      width_mm: 1100,
      density: DENSITY_OK,
      composite: {
        placed_items: [
          { id: 'WB_g01', rotation: 0, translation: [0, 100] }, // 组合腰头条
          { id: 'b_30', rotation: 0, translation: [600, 0] }, // 非组组合条目（组装时跳过）
        ],
        demand_map: { WB_g01: 1, b_30: 1 },
      },
    });
    renderModal();
    act(() => {
      useControlPanelStore.getState().openModal('initial_layout');
    });
    await act(async () => {});
    // pieceGroup 标记：g01_28 带组描边标记（EditCanvas US-005）
    expect(
      q('initial-layout-overlay')!.querySelector('[data-edit-group="band"]'),
    ).not.toBeNull();
    // 整组拖动语义：band 成员 g01_28 平移 +[30,10]（组 delta 记账源）
    act(() => {
      useEditStore.getState().setWorkingItem(0, { translation: [30, 10] });
    });
    click(q('initial-layout-save'));
    await act(async () => {});

    const saved = useInitialLayoutStore.getState().saved!;
    expect(saved.bandUsed).toBe(true);
    expect(saved.demandMap).toEqual({ WB_g01: 1, b_30: 1 });
    // warmPlaced = 组合宇宙：WB_g01 += 组 delta [30,10]；b_30 取当前 working 值
    expect(saved.warmPlaced).toEqual([
      { id: 'WB_g01', rotation: 0, translation: [30, 110] },
      { id: 'b_30', rotation: 0, translation: [600, 0] },
    ]);
    // 守恒：|warmPlaced| = Σ demand
    expect(saved.warmPlaced.length).toBe(2);
  });
});

describe('布局刷新 + ✕ dirty 确认 (US-006)', () => {
  it('无编辑 → 布局刷新直刷（bumpGenSeed 换 seed 重新生成）', async () => {
    await openModalFresh();
    expect(genCalls()).toHaveLength(1);
    click(q('initial-layout-refresh'));
    await act(async () => {});
    const calls = genCalls();
    expect(calls).toHaveLength(2);
    expect((JSON.parse(String(calls[1].init!.body)) as Record<string, unknown>).seed).toBe(1);
    expect(useInitialLayoutStore.getState().genSeed).toBe(1);
    // 无确认层（未编辑）
    expect(q('edit-confirm-overlay')).toBeNull();
    // 刷新后 working = 新生成基线（delta 记账基线同步重置）
    expect(useEditStore.getState().working).toEqual(PLACED_OK);
  });

  it('有编辑 → 确认层「将丢弃当前编辑」：取消保持；确认丢弃并重生成', async () => {
    await openModalFresh();
    act(() => {
      useEditStore.getState().setWorkingItem(0, { translation: [10, 10] });
    });
    click(q('initial-layout-refresh'));
    await act(async () => {});
    // 确认层出现，文案含「将丢弃当前编辑」
    const msg = q('edit-confirm-message')!;
    expect(msg.textContent).toContain('将丢弃当前编辑');
    // 取消：无第二次生成、编辑保留、确认层消失
    click(q('edit-confirm-cancel'));
    await act(async () => {});
    expect(genCalls()).toHaveLength(1);
    expect(q('edit-confirm-overlay')).toBeNull();
    expect(useEditStore.getState().working[0].translation).toEqual([10, 10]);
    // 再刷新 → 确认 → 丢弃并重生成（seed 换代 + working 重置为新生成布局）
    click(q('initial-layout-refresh'));
    await act(async () => {});
    click(q('edit-confirm-ok'));
    await act(async () => {});
    const calls = genCalls();
    expect(calls).toHaveLength(2);
    expect((JSON.parse(String(calls[1].init!.body)) as Record<string, unknown>).seed).toBe(1);
    expect(useEditStore.getState().working[0].translation).toEqual([0, 0]); // 编辑被丢弃
  });

  it('✕ dirty：确认层「放弃未保存的修改？」取消保持 / 确认关窗', async () => {
    await openModalFresh();
    act(() => {
      useEditStore.getState().setWorkingItem(0, { translation: [10, 10] });
    });
    click(q('initial-layout-close'));
    await act(async () => {});
    expect(q('edit-confirm-message')!.textContent).toContain('放弃未保存的修改');
    click(q('edit-confirm-cancel'));
    await act(async () => {});
    expect(overlay()).not.toBeNull(); // 仍在
    click(q('initial-layout-close'));
    await act(async () => {});
    click(q('edit-confirm-ok'));
    await act(async () => {});
    expect(overlay()).toBeNull(); // 弃稿关窗
  });

  it('✕ 非编辑态直接关（无确认层）', async () => {
    await openModalFresh();
    click(q('initial-layout-close'));
    await act(async () => {});
    expect(q('edit-confirm-overlay')).toBeNull();
    expect(overlay()).toBeNull();
  });
});

// ============================================================
// 重叠序号定位（2026-10-04）：保存闸提示只报数量 → footer 提示上方序号 chips
// （编号 = 红色片快照序，mousedown 冻结）→ 点击定位高亮（EditCanvas
// focusHighlightIndex）。三片夹具让「快照冻结 vs 刷新」可观测：a/b 红对 →
// 键盘把 b 挪到 c 旁 → 红对换位 b/c，编号须等画布 pointerdown 才刷新。
// ============================================================
describe('重叠序号定位 (2026-10-04)', () => {
  /** 三片夹具：a/b/c 三 500² 方（a∩b 红对起手，c 远端）。 */
  function makeManifest3(): ManifestMsg {
    const m = makeManifest();
    return {
      ...m,
      total_area_mm2: 750000,
      pieces: [
        ...m.pieces,
        {
          id: 'c_32',
          label: 'g03',
          size: 32,
          color: '#0000ff',
          area_mm2: 250000,
          polygon: [
            [0, 0], [500, 0], [500, 500], [0, 500],
          ] as Polygon,
        },
      ],
    };
  }

  const PLACED3: PlacedItem[] = [
    { id: 'a_28', rotation: 0, translation: [0, 0] as Pt },
    { id: 'b_30', rotation: 0, translation: [400, 50] as Pt }, // a∩b 交 100×450 → 红对
    { id: 'c_32', rotation: 0, translation: [2000, 0] as Pt }, // 远端
  ];

  async function openWith3(): Promise<void> {
    apiRoutes['/api/initial-layout/generate'] = () =>
      genBody({ manifest: makeManifest3(), placed: PLACED3 });
    renderModal();
    act(() => {
      useControlPanelStore.getState().openModal('initial_layout');
    });
    await act(async () => {});
  }

  function chips(): HTMLElement[] {
    return [
      ...document.querySelectorAll('[data-testid="initial-layout-overlap-chip"]'),
    ] as HTMLElement[];
  }

  it('非法重叠在场 → 序号 chips 渲染在提示上方（按片编号）；点击 → 画布定位高亮、再点取消', async () => {
    await openWith3();
    const hint = q('initial-layout-save-hint')!;
    expect(hint.textContent).toContain('2 片');
    const cs = chips();
    expect(cs).toHaveLength(2);
    expect(cs[0].textContent).toBe('1');
    expect(cs[0].dataset.pieceIndex).toBe('0');
    // chips 行在提示文案上方（DOM 顺序在前）
    expect(
      cs[0].compareDocumentPosition(hint) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // 点击序号 1 → 红圈定位标记（a@[0,0] 500² bbox 中心 250,250）+ 交集区
    click(cs[0]);
    const ring = document.querySelector(
      '[data-testid="edit-focus-piece"]',
    ) as unknown as SVGCircleElement;
    expect(ring).not.toBeNull();
    expect(ring.getAttribute('stroke')).toBe('#e03131');
    expect(parseFloat(ring.getAttribute('cx')!)).toBeCloseTo(250, 6);
    expect(parseFloat(ring.getAttribute('cy')!)).toBeCloseTo(250, 6);
    expect(
      document.querySelectorAll('[data-testid="edit-focus-intersection"]').length,
    ).toBeGreaterThanOrEqual(1);
    expect(cs[0].classList.contains('is-active')).toBe(true);
    // 再点同号 → 取消高亮
    click(chips()[0]);
    expect(document.querySelector('[data-testid="edit-focus-piece"]')).toBeNull();
  });

  it('编号 mousedown 冻结：键盘路径换红对 → 编号不动；画布 pointerdown → 快照刷新', async () => {
    await openWith3();
    // 键盘直写 working（无 pointerdown）：b → [1800,50] 与 c 交 300×450 → 红对 b/c
    act(() => {
      useEditStore.getState().setWorkingItem(1, { translation: [1800, 50] });
    });
    expect(q('initial-layout-save-hint')!.textContent).toContain('2 片'); // 实时计数照常
    // 编号冻结：仍指旧快照 a,b（0,1）
    expect(chips().map((c) => c.dataset.pieceIndex)).toEqual(['0', '1']);
    // 画布 mousedown → 快照刷新为新红对 b,c（1,2）
    const svg = q('initial-layout-overlay')!.querySelector('svg')!;
    act(() => {
      svg.dispatchEvent(
        new PointerEvent('pointerdown', {
          bubbles: true,
          cancelable: true,
          pointerId: 1,
          clientX: 10,
          clientY: 10,
          button: 0,
        }),
      );
    });
    expect(chips().map((c) => c.dataset.pieceIndex)).toEqual(['1', '2']);
  });

  it('实时计数归零（重叠全解除）→ chips 行与提示同帧隐藏、定位高亮撤销', async () => {
    await openWith3();
    click(chips()[0]);
    expect(document.querySelector('[data-testid="edit-focus-piece"]')).not.toBeNull();
    // b → [600,50]：与 a、c 均分离 → 全图无红
    act(() => {
      useEditStore.getState().setWorkingItem(1, { translation: [600, 50] });
    });
    expect(q('initial-layout-save-hint')).toBeNull();
    expect(chips()).toHaveLength(0);
    expect(document.querySelector('[data-testid="edit-focus-piece"]')).toBeNull();
  });

  it('合法布局（无红）→ 无 chips 行（缺省形态不受扰）', async () => {
    await openModalFresh(); // PLACED_OK 分离布局
    expect(q('initial-layout-overlap-chips')).toBeNull();
    expect(chips()).toHaveLength(0);
  });
});
