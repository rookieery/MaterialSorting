// US-006（策略 se/race）NestingPage.applyStrategyResult 集成测试 —— 全链路渲染
// <NestingPage />（ControlPanel → StrategyRunButton → StrategyRunModal portal），经弹窗
// 结果态「应用到主画布」按钮点击触发，验证：
//   1. apply → runRegistry.list() 恰 1 条（清掉旧对比 run）且字段齐全：
//      manifest（build_pid_meta 快照口径 + demand 副本）/ frames=[合成帧]（FrameMsg 同形）/
//      lastFrame/finalDensity 双口径/viewBoxMaxW/done/ws=null/stopped=false
//   2. apply → phase==='done'：状态行「策略 run 已应用：seed N · X.XX%」+
//      SolveControls 渲染 #restart（开始求解）+ PlaybackBar seekbar 解禁
//   3. apply → ExportButtons 非 disabled + NestSVG 渲染多副本（demand=2 → 2 个可见 polygon）
//   4. apply → 点导出（显式选 PLT 全量分流 ExportInfoModal）→ 确认 → POST /export 载荷 =
//      合成帧（bestRun() 零改动选中；placed 含 demand 多副本 N 条 placement；pid
//      `{label}_{size}` 与后端 placed_to_world 同规则）+ table 6 手输字段
//   5. 未 apply（仅 done 态弹窗开着）→ registry 不变（显式按钮不自动应用）

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react';
import { NestingPage } from '../NestingPage';
import { runRegistry, type RunRecord } from '../../store/runRegistry';
import { useEditStore } from '../../store/editStore';
import { useAppStore } from '../../store/appStore';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { useStrategyStore } from '../../store/strategyStore';
import type { StrategyResult, StrategyStatus } from '../../types/strategy';
import type { FrameMsg } from '../../types/ws';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
let exportBodies: unknown[] = [];

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

/** result 端点 fixture：g01_30 demand=2（多副本）+ best 帧两条 placement。 */
const APPLY_RESULT: StrategyResult = {
  state: 'done',
  mode: 'race',
  run_dir: 'out/config_runs/web_race_x_1',
  manifest: {
    gate_mm: 1980,
    total_area_mm2: 1000000,
    n_eroded: 1,
    pieces: [
      {
        id: 'g01_30',
        label: 'g01',
        size: 30,
        color: '#2ea06c',
        area_mm2: 6000,
        polygon: [
          [0, 0],
          [100, 0],
          [100, 60],
          [0, 60],
        ],
        demand: 2,
        net_polygon: [],
        internal_lines: [],
        notches: [],
        grain_line: null,
      },
    ],
  },
  best: {
    seed: 3,
    frame_index: 5,
    elapsed: 120.5,
    density: 0.8838,
    density_sparrow: 0.9,
    width_mm: 7100.5,
    placed_items: [
      { id: 'g01_30', rotation: 0, translation: [0, 0] },
      { id: 'g01_30', rotation: 180, translation: [500, 300] },
    ],
  },
  summary: { per_seed: [], mode: 'race' },
};

const DONE_STATUS: StrategyStatus = {
  state: 'done',
  mode: 'race',
  elapsed_sec: 605,
  incumbent: { density: 0.8838, width_mm: 7100.5, seed: 3, frame_index: 5, elapsed: 120.5 },
};

beforeEach(() => {
  useControlPanelStore.getState().closeModal();
  useStrategyStore.getState().reset();
  useAppStore.setState({ renderTick: 0, seekTime: -1 });
  runRegistry.clear();
  exportBodies = [];
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/api/strategy/status')) return Promise.resolve(json({ state: 'idle' }));
    if (url.includes('/api/strategy/result')) return Promise.resolve(json(APPLY_RESULT));
    if (url.includes('/export')) {
      exportBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      return Promise.resolve(
        new Response(new Blob([new Uint8Array([1])], { type: 'image/png' }), {
          status: 200,
          headers: { 'Content-Disposition': 'attachment; filename="x.png"' },
        }),
      );
    }
    return Promise.resolve(json({}));
  }) as (...args: unknown[]) => Promise<Response>);
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
  container = null;
  document.body.innerHTML = '';
  useControlPanelStore.getState().closeModal();
  useStrategyStore.getState().reset();
  runRegistry.clear();
  fetchSpy?.mockRestore();
  fetchSpy = null;
});

function renderPage(): void {
  act(() => {
    root!.render(<NestingPage />);
  });
}

/** 打开弹窗 + 置 done 结果态（模拟 useStrategyPoll refresh 拉到的 status/result）。 */
function openResultState(): void {
  act(() => {
    useControlPanelStore.getState().openModal('strategy_run');
  });
  act(() => {
    useStrategyStore.setState({ phase: 'done', status: DONE_STATUS, result: APPLY_RESULT });
  });
}

function clickApply(): void {
  act(() => {
    (document.body.querySelector('[data-testid="strategy-apply-btn"]') as HTMLButtonElement).click();
  });
}

describe('NestingPage.applyStrategyResult (US-006)', () => {
  it('apply → runRegistry 恰 1 条（清掉旧对比 run）且字段齐全（manifest/frames/finalDensity/viewBoxMaxW/done）', () => {
    // 预置一条主画布旧 run（模拟现有对比 run —— apply 语义 = 显式清场置换）
    const stale = runRegistry.create(9);
    stale.done = true;
    stale.finalDensity = 0.8;
    const staleFrame: FrameMsg = {
      type: 'frame', index: 0, elapsed: 1, phase: 'final',
      density: 0.8, density_sparrow: 0.82, width_mm: 8000, placed_items: [],
    };
    stale.frames.push(staleFrame);
    stale.lastFrame = staleFrame;

    renderPage();
    openResultState();
    const applyBtn = document.body.querySelector('[data-testid="strategy-apply-btn"]') as HTMLButtonElement;
    expect(applyBtn.disabled).toBe(false); // NestingPage 已接线 onApplyStrategy
    clickApply();

    // 恰 1 条（旧 run 被清）
    const runs = runRegistry.list();
    expect(runs).toHaveLength(1);
    const rec = runs[0];
    expect(rec.seed).toBe(3);

    // manifest：build_pid_meta 快照口径（demand 已含，多副本池数据源）
    expect(rec.manifest).not.toBeNull();
    expect(rec.manifest!.type).toBe('manifest');
    expect(rec.manifest!.gate_mm).toBe(1980);
    expect(rec.manifest!.total_area_mm2).toBe(1000000);
    expect(rec.manifest!.n_eroded).toBe(1);
    expect(rec.manifest!.pieces).toHaveLength(1);
    expect(rec.manifest!.pieces[0].id).toBe('g01_30');
    expect(rec.manifest!.pieces[0].demand).toBe(2);

    // frames = [合成帧]（FrameMsg 同形）+ lastFrame 同帧
    expect(rec.frames).toHaveLength(1);
    const f = rec.frames[0];
    expect(f).toMatchObject({
      type: 'frame',
      index: 5,
      elapsed: 120.5,
      phase: 'final',
      density: 0.8838,
      density_sparrow: 0.9,
      width_mm: 7100.5,
    });
    expect(f.placed_items).toHaveLength(2); // demand 多副本 N 条 placement
    expect(rec.lastFrame).toBe(f);

    // 双口径密度 / viewBox / 终态标志
    expect(rec.finalDensity).toBe(0.8838);
    expect(rec.finalDensitySparrow).toBe(0.9);
    expect(rec.viewBoxMaxW).toBe(7100.5);
    expect(rec.done).toBe(true);
    expect(rec.stopped).toBe(false);
    expect(rec.error).toBeNull();
    expect(rec.ws).toBeNull();
  });

  it("apply → phase==='done'：状态行「策略 run 已应用」+ #restart 按钮 + seekbar 解禁", () => {
    renderPage();
    openResultState();
    clickApply();

    // 状态行文案（ControlPanel StatusLine；doc=null 时后缀「请先在上传预览页解析母版」与本断言无关）
    const status = container!.querySelector('#status')!;
    expect(status.textContent).toContain('策略 run 已应用：seed 3 · 88.38%');
    // phase=done → SolveControls 渲染 #restart（开始求解），非 #stop
    expect(container!.querySelector('#restart')).not.toBeNull();
    expect(container!.querySelector('#stop')).toBeNull();
    // PlaybackBar：全部 done → seekbar 解禁（max = ceil(120.5) = 121）
    const seek = container!.querySelector<HTMLInputElement>('#seek')!;
    expect(seek.disabled).toBe(false);
    expect(parseInt(seek.max, 10)).toBe(121);
  });

  it('apply → ExportButtons 非 disabled + NestSVG 多副本渲染（demand=2 → 2 个可见 polygon）', () => {
    renderPage();
    openResultState();
    // apply 前导出禁用（无 lastFrame run）
    expect(container!.querySelector<HTMLButtonElement>('.export-btns button.export')!.disabled).toBe(true);
    clickApply();

    // NestCard 挂载（seeds=[3]）
    expect(container!.querySelector('.nest-card')).not.toBeNull();
    // NestSVG 命令式渲染：g01_30 demand=2 → 2 个副本 polygon，两条 placement 各承一处（均可见）
    const polygons = Array.from(container!.querySelectorAll<SVGPolygonElement>('.nest-card svg polygon'));
    expect(polygons).toHaveLength(2);
    const visible = polygons.filter((p) => p.style.display !== 'none');
    expect(visible).toHaveLength(2);
    // 两条 placement 不同 translation → points 不同（后不覆盖前）
    expect(visible[0].getAttribute('points')).not.toBe(visible[1].getAttribute('points'));

    // ExportButtons 解禁（bestRun() 选中合成 record → 有 lastFrame）
    expect(container!.querySelector<HTMLButtonElement>('.export-btns button.export')!.disabled).toBe(false);
  });

  it('apply 后点导出（PLT 分流弹窗确认）→ POST /export 载荷 = 合成帧 + table 手输字段', async () => {
    vi.stubGlobal('URL', {
      ...(globalThis.URL as object),
      createObjectURL: vi.fn(() => 'blob:fake://1'),
      revokeObjectURL: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    renderPage();
    openResultState();
    clickApply();

    // 显式切回全量 PLT（2026-08-31 起默认已是 PLT 毛版）→ ControlPanel 分流打开
    // ExportInfoModal（portal 到 body），不直接 POST
    act(() => {
      const select = container!.querySelector<HTMLSelectElement>('.export-btns select')!;
      select.value = 'plt';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await act(async () => {
      container!.querySelector<HTMLButtonElement>('.export-btns button.export')!.click();
      await Promise.resolve();
    });
    expect(exportBodies).toHaveLength(0);
    const confirmBtn = document.querySelector<HTMLButtonElement>(
      '[data-testid=export-info-confirm]',
    );
    expect(confirmBtn).not.toBeNull();
    await act(async () => {
      confirmBtn!.click();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(exportBodies).toHaveLength(1);
    const body = exportBodies[0] as {
      fmt: string; seed: number; gate_mm: number; width_mm: number;
      density: number; placed: { id: string; rotation: number; translation: number[] }[];
      table: Record<string, string>;
    };
    expect(body.fmt).toBe('plt');
    expect(body.seed).toBe(3);
    expect(body.gate_mm).toBe(1980);
    expect(body.width_mm).toBe(7100.5);
    expect(body.density).toBe(0.8838);
    expect(body.placed).toEqual([
      { id: 'g01_30', rotation: 0, translation: [0, 0] },
      { id: 'g01_30', rotation: 180, translation: [500, 300] },
    ]);
    // table 6 手输字段随载荷下发（默认 A料/0.0%/0.0%/空/noname/空）
    expect(body.table).toEqual({
      bed_no: 'A料', warp_shrink: '0.0%', weft_shrink: '0.0%',
      planner: '', style_no: 'noname', remark: '',
    });
    // 状态行汇报导出完成（useExport → onStatus）
    expect(container!.querySelector('#status')!.textContent).toContain('已导出');
    vi.unstubAllGlobals();
  });

  it('done 态弹窗开着但不点 apply → registry 不变（显式按钮不自动应用）', () => {
    const stale = runRegistry.create(9);
    stale.done = true;
    renderPage();
    openResultState();
    // 弹窗结果态在场（应用按钮可点）但未点击
    expect(document.body.querySelector('[data-testid="strategy-apply-btn"]')).not.toBeNull();
    expect(runRegistry.list()).toHaveLength(1);
    expect(runRegistry.list()[0].seed).toBe(9); // 旧 run 原样保留
    // 主画布 phase 仍 idle（#start 按钮在场，非 done 的 #restart）
    expect(container!.querySelector('#start')).not.toBeNull();
    expect(container!.querySelector('#restart')).toBeNull();
  });
});

// ============================================================
// 编辑排料 US-004：handleStart / applyStrategyResult 双挂点 invalidate
// （编辑态对重解与策略应用的结果不再有效 —— 陈旧 run 的 save/reset 已被
// registry 校验拒绝，此处断言编辑态被同步清空不残留）。
// ============================================================

describe('NestingPage 编辑排料 invalidate 挂点 (US-004)', () => {
  // handleStart 会 new WebSocket —— 本 describe 局部 stub（App.test 同款）。
  class MockWS {
    url: string;
    constructor(url: string) {
      this.url = url;
    }
    close() {}
  }
  let realWS: typeof WebSocket | undefined;

  beforeEach(() => {
    useEditStore.getState().invalidate();
    realWS = globalThis.WebSocket;
    (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket =
      MockWS as unknown as typeof WebSocket;
  });

  afterEach(() => {
    (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket = realWS!;
    useEditStore.getState().invalidate();
  });

  /** 造一个可编辑 run 并 open 快照（编辑态在场：run/baseline/working 非空）。 */
  function seedEditSession(): RunRecord {
    const run = runRegistry.create(0);
    run.manifest = {
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
        },
      ],
    };
    const frame: FrameMsg = {
      type: 'frame',
      index: 0,
      elapsed: 1,
      phase: 'final',
      density: 0.5,
      density_sparrow: 0.5,
      width_mm: 500,
      placed_items: [{ id: 'a_28', rotation: 0, translation: [0, 0] }],
    };
    run.frames.push(frame);
    run.lastFrame = frame;
    run.finalDensity = 0.5;
    expect(useEditStore.getState().open(run)).toBe(true);
    return run;
  }

  it('handleStart（点开始求解）→ 编辑态失效（run/baseline/working 清空）', () => {
    const run = seedEditSession();
    expect(useEditStore.getState().run).not.toBeNull();
    renderPage();
    // 选一个码号（doc=null → SizePicker fallback SIZES）+ 点开始求解
    act(() => {
      (document.querySelector('#sz_28') as HTMLInputElement).click();
    });
    act(() => {
      (document.querySelector('#start') as HTMLButtonElement).click();
    });
    const st = useEditStore.getState();
    expect(st.run).toBeNull();
    expect(st.baseline).toBeNull();
    expect(st.working).toEqual([]);
    expect(st.savedDirty).toBe(false);
    // 旧 run 已被 clear（旧引用不再 registry —— 陈旧保存防御同源）
    expect(runRegistry.list().includes(run)).toBe(false);
  });

  it('handleStart 无编辑会话 → invalidate 幂等（不炸、状态保持空）', () => {
    renderPage();
    act(() => {
      (document.querySelector('#sz_28') as HTMLInputElement).click();
    });
    act(() => {
      (document.querySelector('#start') as HTMLButtonElement).click();
    });
    const st = useEditStore.getState();
    expect(st.run).toBeNull();
    expect(st.baseline).toBeNull();
  });

  it('applyStrategyResult（应用到主画布）→ 编辑态失效', () => {
    seedEditSession();
    renderPage();
    openResultState();
    clickApply();
    const st = useEditStore.getState();
    expect(st.run).toBeNull();
    expect(st.baseline).toBeNull();
    expect(st.working).toEqual([]);
    expect(st.savedDirty).toBe(false);
    // 应用后的合成 record 是新会话对象（重开编辑弹窗重新快照，不残留旧基线）
    expect(runRegistry.list().length).toBe(1);
    expect(runRegistry.list()[0].lastFrame).not.toBeNull();
  });
});
