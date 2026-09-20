// US-005 StrategyRunModal 集成测试（范本 PerTypeOverridesModal.test.tsx）：
//   - modal=null 不渲染 / open 渲染 overlay+modal+role=dialog
//   - 配置态：时长+模式下拉、模式说明随切换、10min 常驻提示、执行按钮
//   - 执行 disabled 条件（主画布 solving / sizes 空）
//   - 执行 click → POST /api/strategy/start 载荷与 buildStartContext 同源
//   - ESC / 遮罩 / ✕ 关闭均不触发 stop（关弹窗不终止运行）+ running 态文案
//   - 进度态五件套（标题/大数字/预算条/阶段行/seed chips+事件行）
//   - race 门杀瞬间 chip ✕门杀 / SE 延长中阶段行 + 两段式 chips
//   - 结果态 done/stopped（最优+seed+用布+模式汇总+应用按钮 disabled；2026-08-22
//     起不再展示服务器 run_dir 路径）
//   - error 态错误 + 重试（原载荷重发）/ orphan 态清理（stop 路由）

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react';
import { StrategyRunModal } from '../StrategyRunModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { useStrategyStore } from '../../../store/strategyStore';
import type { StartContext } from '../../../lib/params';
import type { StrategyResult, StrategyStatus } from '../../../types/strategy';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
let startBodies: unknown[] = [];
let stopCalls = 0;
let statusPayload: unknown = { state: 'idle' };
let resultPayload: unknown = null;

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

const CTX: StartContext = {
  sizes: [30, 32],
  gate_mm: 1980,
  seed: 5,
  time: 120,
  params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
  per_type: null,
  quantities: { g01: { '30': 2, '32': 1 } },
  // 2026-08-22 解除互斥：band 随 handleExec 透传到 /api/strategy/start（ctx.band
  // 开启 → 载荷带 band；null → 显式 null 键，后端 _parse_band 关闭不写 config）。
  band: null,
  // 2026-08-25 解除互斥（band 同款）：prefix 同样随 handleExec 透传；null →
  // 显式 null 键，后端 _parse_prefix 关闭不写 config。
  prefix: null,
};

const EMPTY_CTX: StartContext = { ...CTX, sizes: [], quantities: null };

beforeEach(() => {
  useControlPanelStore.getState().closeModal();
  useStrategyStore.getState().reset();
  startBodies = [];
  stopCalls = 0;
  statusPayload = { state: 'idle' };
  resultPayload = null;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/api/strategy/start')) {
      startBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      return Promise.resolve(json({ started: true, pid: 1, mode: 'race', minutes: 20, run_name: 'w' }, 202));
    }
    if (url.includes('/api/strategy/stop')) {
      stopCalls += 1;
      return Promise.resolve(json({ stopped: true, pid: 1 }));
    }
    if (url.includes('/api/strategy/status')) return Promise.resolve(json(statusPayload));
    if (url.includes('/api/strategy/result')) {
      return Promise.resolve(resultPayload === null ? json({}, 404) : json(resultPayload));
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
  fetchSpy?.mockRestore();
  fetchSpy = null;
});

function renderModal(
  solving = false,
  ctx: StartContext = CTX,
): void {
  act(() => {
    root!.render(<StrategyRunModal solving={solving} buildStartContext={() => ctx} />);
  });
}

function openModal(): void {
  act(() => {
    useControlPanelStore.getState().openModal('strategy_run');
  });
}

function setPhase(partial: { phase: StrategyStatus['state']; status?: StrategyStatus | null }): void {
  act(() => {
    useStrategyStore.setState(partial);
  });
}

/** race 运行中 fixture：seed0 完成、seed1 门杀瞬间、seed2 当前求解。 */
const RACE_RUNNING: StrategyStatus = {
  state: 'running',
  mode: 'race',
  total_budget_sec: 600,
  elapsed_sec: 125.4,
  run_dir: 'out/config_runs/web_race_x_1',
  plan: { planned_seeds: [0, 1, 2, 3, 4], gate_seconds: 90 },
  incumbent: { density: 0.8632, width_mm: 7100, seed: 0, frame_index: 5, elapsed: 120 },
  current: { seed: 2, density: 0.851, density_sparrow: 0.88, ext: false },
  per_seed: [{ seed: 0, killed: false, kill_reason: null, best_density: 0.8632, elapsed: 180, phase: 'race' }],
  events: [{ kind: 'gate', seed: 1, t: 91, d: 0.851, bar: 0.8632, would_kill: true }],
  error: null,
  exit_code: null,
};

/** SE 延长中 fixture：1 筛完成 + 冠军 seed0 延长进行。 */
const SE_EXT: StrategyStatus = {
  state: 'running',
  mode: 'se',
  total_budget_sec: 600,
  elapsed_sec: 300,
  plan: { planned_seeds: [0, 1], k_screens: 2, screen_s: 90, ext_s: 180 },
  incumbent: { density: 0.86, width_mm: 7100, seed: 1, frame_index: 4, elapsed: 90 },
  current: { seed: 1, density: 0.87, density_sparrow: 0.89, ext: true },
  per_seed: [{ seed: 0, killed: false, kill_reason: null, best_density: 0.85, elapsed: 91, phase: 'screen' }],
  events: [{ kind: 'extension', seed: 1 }],
  error: null,
  exit_code: null,
};

const DONE_RESULT: StrategyResult = {
  state: 'done',
  mode: 'race',
  run_dir: 'out/config_runs/web_race_x_1',
  manifest: { gate_mm: 1980, total_area_mm2: 1e6, n_eroded: 0, pieces: [] },
  best: { seed: 3, frame_index: 5, elapsed: 120, density: 0.8838, density_sparrow: 0.9, width_mm: 7100.5, placed_items: [] },
  summary: {
    per_seed: [
      { seed: 0, killed: false, kill_reason: null, best_density: 0.86, elapsed: 180, phase: 'race' },
      { seed: 1, killed: true, kill_reason: 'R5_race_gate', best_density: 0.85, elapsed: 92, phase: 'race' },
      { seed: 2, killed: true, kill_reason: 'R5_race_gate', best_density: 0.84, elapsed: 93, phase: 'race' },
      { seed: 3, killed: false, kill_reason: null, best_density: 0.8838, elapsed: 181, phase: 'race' },
    ],
    mode: 'race',
    race: { gate_seconds: 90, kept_seeds: [0, 3], gated_seeds: [1, 2] },
  },
};

function setSelectValue(sel: HTMLSelectElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!;
  setter.call(sel, value);
  sel.dispatchEvent(new Event('change', { bubbles: true }));
}

describe('StrategyRunModal (US-005)', () => {
  it('modal=null 不渲染（无 portal DOM）', () => {
    renderModal();
    expect(document.body.querySelector('.strategy-overlay')).toBeNull();
  });

  it('open 渲染 overlay + modal + role=dialog；配置态时长/模式下拉 + 10min 提示在场', () => {
    openModal();
    renderModal();
    expect(document.body.querySelector('.strategy-overlay')).not.toBeNull();
    const modal = document.body.querySelector('.strategy-modal')!;
    expect(modal.getAttribute('role')).toBe('dialog');
    expect(document.body.querySelector('[data-testid="strategy-minutes"]')).not.toBeNull();
    expect(document.body.querySelector('[data-testid="strategy-mode"]')).not.toBeNull();
    expect(document.body.querySelector('[data-testid="strategy-min-hint"]')!.textContent)
      .toContain('10 分钟档两模式与均分打平，20 分钟起有增益');
    // 常驻提示：排料参数取当前面板
    const hints = Array.from(document.body.querySelectorAll('.strategy-hint')).map((h) => h.textContent);
    expect(hints.some((t) => t!.includes('排料参数取当前面板'))).toBe(true);
    // 不暴露 --se-screen 等 4 个策略参数（无额外输入框）
    expect(document.body.querySelectorAll('.strategy-modal input').length).toBe(0);
  });

  it('模式说明行随切换（race → SE）', () => {
    openModal();
    renderModal();
    const desc = document.body.querySelector('[data-testid="strategy-mode-desc"]')!;
    expect(desc.textContent).toContain('90s 门处严格破纪录才续跑');
    act(() => {
      setSelectValue(document.body.querySelector<HTMLSelectElement>('[data-testid="strategy-mode"]')!, 'se');
    });
    expect(document.body.querySelector('[data-testid="strategy-mode-desc"]')!.textContent)
      .toContain('多轮短筛选后冠军 seed 加时长再战');
  });

  it('执行 disabled 条件：solving=true 或 sizes 空 → disabled；正常 → enabled', () => {
    openModal();
    renderModal(true, CTX);
    expect((document.body.querySelector('[data-testid="strategy-exec-btn"]') as HTMLButtonElement).disabled).toBe(true);

    act(() => {
      root!.render(<StrategyRunModal solving={false} buildStartContext={() => EMPTY_CTX} />);
    });
    expect((document.body.querySelector('[data-testid="strategy-exec-btn"]') as HTMLButtonElement).disabled).toBe(true);

    act(() => {
      root!.render(<StrategyRunModal solving={false} buildStartContext={() => CTX} />);
    });
    expect((document.body.querySelector('[data-testid="strategy-exec-btn"]') as HTMLButtonElement).disabled).toBe(false);
  });

  it('执行 click → POST /api/strategy/start（载荷 = 下拉选择 + buildStartContext 同源字段）', async () => {
    openModal();
    renderModal();
    act(() => {
      setSelectValue(document.body.querySelector<HTMLSelectElement>('[data-testid="strategy-minutes"]')!, '30');
      setSelectValue(document.body.querySelector<HTMLSelectElement>('[data-testid="strategy-mode"]')!, 'se');
    });
    act(() => {
      (document.body.querySelector('[data-testid="strategy-exec-btn"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(startBodies).toHaveLength(1);
    expect(startBodies[0]).toEqual({
      mode: 'se',
      minutes: 30,
      seed: CTX.seed,
      gate_mm: CTX.gate_mm,
      sizes: CTX.sizes,
      per_type: CTX.per_type,
      quantities: CTX.quantities,
      band: null,
      prefix: null,
    });
  });

  it('band 开启 → start 载荷带 band（ctx.band 同源透传，2026-08-22 解除互斥）', async () => {
    openModal();
    const bandedCtx: StartContext = {
      ...CTX,
      band: { enabled: true, label: 'g05' },
    };
    renderModal(false, bandedCtx);
    act(() => {
      (document.body.querySelector('[data-testid="strategy-exec-btn"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(startBodies).toHaveLength(1);
    expect(startBodies[0]).toMatchObject({
      mode: 'race',
      minutes: 20,
      band: { enabled: true, label: 'g05' },
    });
  });

  it('prefix 开启 → start 载荷带 prefix（ctx.prefix 同源透传，2026-08-25 解除互斥）', async () => {
    openModal();
    const prefixedCtx: StartContext = {
      ...CTX,
      prefix: { enabled: true, front: 'g02', back: 'g03' },
    };
    renderModal(false, prefixedCtx);
    act(() => {
      (document.body.querySelector('[data-testid="strategy-exec-btn"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(startBodies).toHaveLength(1);
    expect(startBodies[0]).toMatchObject({
      mode: 'race',
      minutes: 20,
      prefix: { enabled: true, front: 'g02', back: 'g03' },
    });
  });

  it('ESC / 遮罩 / ✕ 关闭均不触发 stop（关弹窗不终止运行）', () => {
    openModal();
    renderModal();
    setPhase({ phase: 'running', status: RACE_RUNNING });
    // running 态文案明示
    expect(document.body.querySelector('[data-testid="strategy-close-hint"]')!.textContent)
      .toContain('关闭弹窗不会终止运行');

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(stopCalls).toBe(0);

    openModal();
    act(() => {
      (document.body.querySelector('.strategy-overlay') as HTMLDivElement)
        .dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(stopCalls).toBe(0);

    openModal();
    act(() => {
      (document.body.querySelector('[data-testid="strategy-close"]') as HTMLButtonElement).click();
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(stopCalls).toBe(0);
    expect(startBodies).toHaveLength(0);
  });

  it('进度态五件套：标题/大数字/预算条/阶段行/chips+事件行；终止按钮触发 stop', async () => {
    openModal();
    renderModal();
    setPhase({ phase: 'running', status: RACE_RUNNING });
    expect(document.body.querySelector('[data-testid="strategy-progress-title"]')!.textContent)
      .toContain('race 门杀 · 总预算 10 分 · 已跑 2 分 5 秒');
    expect(document.body.querySelector('[data-testid="strategy-big-density"]')!.textContent).toBe('86.32%');
    const fill = document.body.querySelector('.strategy-budget-fill') as HTMLDivElement;
    expect(fill.style.width).toBe('20.9%');
    expect(document.body.querySelector('[data-testid="strategy-budget-label"]')!.textContent).toContain('≈125s / 600s');
    expect(document.body.querySelector('[data-testid="strategy-stage"]')!.textContent)
      .toContain('第 2/5 轮 · seed 2 · 求解中');
    const chips = Array.from(document.body.querySelectorAll('[data-testid="strategy-seed-chips"] .strategy-chip'))
      .map((c) => ({ text: c.textContent!, cls: c.className }));
    // seed0 完成 ✓密度 / seed1 门杀瞬间 ✕门杀 / seed2 running ● / seed3-4 未启动灰
    expect(chips[0]).toMatchObject({ text: '0 ✓ 86.32%', cls: 'strategy-chip done' });
    expect(chips[1]).toMatchObject({ text: '1 ✕门杀', cls: 'strategy-chip killed' });
    expect(chips[2]).toMatchObject({ text: '2 ● 85.10%', cls: 'strategy-chip running' });
    expect(chips[3].cls).toContain('pending');
    expect(document.body.querySelector('[data-testid="strategy-event"]')!.textContent)
      .toContain('✕ seed 1 门杀（85.10% ≤ 门值 86.32%）');

    act(() => {
      (document.body.querySelector('[data-testid="strategy-stop-btn"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(stopCalls).toBe(1);
  });

  it('SE 延长中：阶段行切「延长中 · 冠军 seed 1」+ chips 两段式（k 筛 + → + 延长条目）', () => {
    openModal();
    renderModal();
    setPhase({ phase: 'running', status: SE_EXT });
    expect(document.body.querySelector('[data-testid="strategy-stage"]')!.textContent)
      .toBe('延长中 · 冠军 seed 1');
    const chips = Array.from(document.body.querySelectorAll('[data-testid="strategy-seed-chips"] .strategy-chip'))
      .map((c) => c.textContent!);
    expect(chips).toEqual(['0 ✓ 85.00%', '1 ● 87.00%', '→', '1 延 ● 87.00%']);
    expect(document.body.querySelector('[data-testid="strategy-event"]')!.textContent)
      .toContain('冠军 seed 1 进入延长');
  });

  it('SE 延长中事件被尾窗裁掉（k≥20 事故）：current.ext 第三源兜底，延长条目仍 ● 不「待定」', () => {
    // 2026-09-20 2h 极限 SE 档事故回归锁：extension 事件被后端尾窗裁掉
    // （events 只剩 seed_done）+ per_seed 无 extension 入账 —— 冠军推导落到
    // current.ext 第三源，延长 chip 照常「延 ●」。
    openModal();
    renderModal();
    setPhase({
      phase: 'running',
      status: { ...SE_EXT, events: [{ kind: 'seed_done', seed: 0, phase: 'screen', best_density: 0.85, killed: false }] },
    });
    const chips = Array.from(document.body.querySelectorAll('[data-testid="strategy-seed-chips"] .strategy-chip'))
      .map((c) => c.textContent!);
    expect(chips[chips.length - 1]).toBe('1 延 ● 87.00%');
    expect(document.body.querySelector('[data-testid="strategy-stage"]')!.textContent)
      .toContain('延长中 · 冠军 seed 1');
  });

  it('SE 延长静默心跳：阶段行带静默时长 + ≥60s 显示「属正常/存活」说明行；未达阈值不显示', () => {
    openModal();
    renderModal();
    setPhase({
      phase: 'running',
      status: { ...SE_EXT, last_frame_age_sec: 90, worker_alive: true },
    });
    expect(document.body.querySelector('[data-testid="strategy-stage"]')!.textContent)
      .toBe('延长中 · 冠军 seed 1 · 静默 1 分 30 秒');
    const hint = document.body.querySelector('[data-testid="strategy-ext-silence"]')!;
    expect(hint.textContent).toContain('1 分 30 秒 无新帧属正常');
    expect(hint.textContent).toContain('求解子进程存活 ✓');
    // 阈值以下（30s）不显示说明行，阶段行仍带静默时长。
    setPhase({
      phase: 'running',
      status: { ...SE_EXT, last_frame_age_sec: 30, worker_alive: true },
    });
    expect(document.body.querySelector('[data-testid="strategy-ext-silence"]')).toBeNull();
    expect(document.body.querySelector('[data-testid="strategy-stage"]')!.textContent)
      .toBe('延长中 · 冠军 seed 1 · 静默 30 秒');
    // 子进程退出（worker_alive=false）→ 说明行转警示。
    setPhase({
      phase: 'running',
      status: { ...SE_EXT, last_frame_age_sec: 120, worker_alive: false },
    });
    expect(document.body.querySelector('[data-testid="strategy-ext-silence"]')!.textContent)
      .toContain('求解子进程已退出 ⚠');
  });

  it('结果态 done：完成·最优 + seed/用布 + race 模式汇总 + 不展示 run_dir + 应用按钮 disabled（US-006 接线前）', async () => {
    resultPayload = DONE_RESULT;
    openModal();
    renderModal();
    setPhase({
      phase: 'done',
      status: { ...RACE_RUNNING, state: 'done', elapsed_sec: 605 },
    });
    act(() => {
      useStrategyStore.setState({ result: DONE_RESULT });
    });
    expect(document.body.querySelector('[data-testid="strategy-result-head"]')!.textContent)
      .toBe('完成 · 最优 88.38%');
    expect(document.body.querySelector('[data-testid="strategy-result-detail"]')!.textContent)
      .toContain('seed 3 · 用布 710.05 cm');
    expect(document.body.querySelector('[data-testid="strategy-mode-summary"]')!.textContent)
      .toContain('race：4 轮中 2 轮门杀 · 全程 10 分 5 秒');
    // 2026-08-22：服务器 run_dir 路径不再上屏（含复制按钮）。
    expect(document.body.querySelector('[data-testid="strategy-run-dir"]')).toBeNull();
    expect(document.body.querySelector('[data-testid="strategy-copy-btn"]')).toBeNull();
    const apply = document.body.querySelector('[data-testid="strategy-apply-btn"]') as HTMLButtonElement;
    expect(apply.disabled).toBe(true); // US-006 接线前 disabled
  });

  it('结果态 stopped：已终止 · 保留终止前最优（应用按钮同样在场）', () => {
    openModal();
    renderModal();
    setPhase({ phase: 'stopped', status: { ...RACE_RUNNING, state: 'stopped', elapsed_sec: 300 } });
    act(() => {
      useStrategyStore.setState({ result: DONE_RESULT });
    });
    expect(document.body.querySelector('[data-testid="strategy-result-head"]')!.textContent)
      .toBe('已终止 · 保留终止前最优 88.38%');
    expect(document.body.querySelector('[data-testid="strategy-apply-btn"]')).not.toBeNull();
  });

  it('结果态 warning（母版漂移）展示', () => {
    openModal();
    renderModal();
    setPhase({ phase: 'done', status: { ...RACE_RUNNING, state: 'done' } });
    act(() => {
      useStrategyStore.setState({ result: { ...DONE_RESULT, warning: '母版已变更，应用结果可能与当前画布不一致' } });
    });
    expect(document.body.querySelector('[data-testid="strategy-warning"]')!.textContent)
      .toContain('母版已变更');
  });

  it('error 态：错误信息 + 重试（lastStart 原载荷重发）', async () => {
    openModal();
    renderModal();
    // 先走一次 start（202）建立 lastStart。
    act(() => {
      (document.body.querySelector('[data-testid="strategy-exec-btn"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(startBodies).toHaveLength(1);
    // 切 error 态（模拟第二次 start 被拒）。
    act(() => {
      useStrategyStore.setState({ phase: 'error', errorMessage: '已有进行中的策略运行' });
    });
    expect(document.body.querySelector('[data-testid="strategy-error"]')!.textContent)
      .toContain('已有进行中的策略运行');
    act(() => {
      (document.body.querySelector('[data-testid="strategy-retry-btn"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(startBodies).toHaveLength(2); // 原载荷重发
    expect(startBodies[1]).toEqual(startBodies[0]);
  });

  it('orphan 态：检测到遗留运行 + 清理按钮触发 stop 路由', async () => {
    openModal();
    renderModal();
    setPhase({
      phase: 'orphan',
      status: { state: 'orphan', alive: true, pid: 4321, mode: 'race', run_dir: 'out/config_runs/old', elapsed_sec: 10 },
    });
    expect(document.body.querySelector('[data-testid="strategy-orphan-head"]')!.textContent)
      .toContain('检测到遗留运行');
    expect(document.body.querySelector('[data-testid="strategy-orphan-detail"]')!.textContent)
      .toContain('pid 4321');
    act(() => {
      (document.body.querySelector('[data-testid="strategy-cleanup-btn"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(stopCalls).toBe(1);
  });

  // ------------------------------------------- SE 延长轮 warm 状态（2026-09-19）
  // 二期（2026-09-19）band/prefix warm 解禁：配置态互斥预告块已删
  // （strategy-se-warm-blocked 不再存在），此处锁「SE + band 开也无预告」。

  it('配置态：SE + band/prefix 开 → 无互斥预告（二期解禁，warm 可同开）', () => {
    // SE + band 开 → 无预告（一期为 band_prefix_on 必回退预告，已删）。
    openModal();
    renderModal(false, { ...CTX, band: { enabled: true, label: 'g05' } });
    act(() => {
      setSelectValue(document.body.querySelector<HTMLSelectElement>('[data-testid="strategy-mode"]')!, 'se');
    });
    expect(document.body.querySelector('[data-testid="strategy-se-warm-blocked"]')).toBeNull();

    // SE + prefix 开 → 同无预告。
    act(() => {
      root!.render(
        <StrategyRunModal
          solving={false}
          buildStartContext={() => ({ ...CTX, prefix: { enabled: true, front: 'g02', back: 'g03' } })}
        />,
      );
    });
    expect(document.body.querySelector('[data-testid="strategy-se-warm-blocked"]')).toBeNull();
  });

  it('进度态：SE plan.warm=false → ⚠ 回退警告常显（带原因）；plan.warm=true 延长中 → 真顺延标注', () => {
    openModal();
    renderModal();
    // 回退：no_composite_view（二期装载点原因）→ ⚠ 行（warning 样式）。
    setPhase({
      phase: 'running',
      status: { ...SE_EXT, plan: { ...SE_EXT.plan!, warm: false, warm_reason: 'no_composite_view' } },
    });
    const note = document.body.querySelector('[data-testid="strategy-warm-note"]')!;
    expect(note.textContent).toContain('延长轮回退重放');
    expect(note.textContent).toContain('缺组合视角段');
    expect(note.className).toContain('strategy-warning');

    // 真顺延：延长阶段 → 正向标注（hint 样式，不警示）。
    setPhase({
      phase: 'running',
      status: { ...SE_EXT, plan: { ...SE_EXT.plan!, warm: true } },
    });
    const ok = document.body.querySelector('[data-testid="strategy-warm-note"]')!;
    expect(ok.textContent).toContain('真顺延');
    expect(ok.className).toContain('strategy-hint');

    // 真顺延但仍在筛选期 → 不占版面（无 warm 行）。
    setPhase({
      phase: 'running',
      status: {
        ...SE_EXT,
        plan: { ...SE_EXT.plan!, warm: true },
        current: { seed: 1, density: 0.85, density_sparrow: 0.87, ext: false },
        events: [],
      },
    });
    expect(document.body.querySelector('[data-testid="strategy-warm-note"]')).toBeNull();
  });

  it('结果态：SE summary.warm=false → 汇总行带回退原因；warm=true → 真顺延', () => {
    openModal();
    renderModal();
    setPhase({ phase: 'done', status: { ...SE_EXT, state: 'done' } });
    act(() => {
      useStrategyStore.setState({
        result: {
          ...DONE_RESULT,
          mode: 'se',
          summary: {
            per_seed: DONE_RESULT.summary.per_seed,
            mode: 'se',
            se: { k_screens: 4, screen_s: 90, ext_s: 180, champion: 1 },
            warm: false,
            warm_reason: 'instance_mismatch',
          },
        },
      });
    });
    expect(document.body.querySelector('[data-testid="strategy-mode-summary"]')!.textContent)
      .toContain('warm 回退（热启动载荷与重建实例不匹配');

    act(() => {
      useStrategyStore.setState({
        result: {
          ...DONE_RESULT,
          mode: 'se',
          summary: {
            per_seed: DONE_RESULT.summary.per_seed,
            mode: 'se',
            se: { k_screens: 4, screen_s: 90, ext_s: 180, champion: 1 },
            warm: true,
          },
        },
      });
    });
    expect(document.body.querySelector('[data-testid="strategy-mode-summary"]')!.textContent)
      .toContain('warm 真顺延');
  });
});
