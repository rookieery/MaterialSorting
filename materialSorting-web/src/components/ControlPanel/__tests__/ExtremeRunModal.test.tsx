// US-003 ExtremeRunModal 集成测试（范本 StrategyRunModal.test.tsx）：
//   - modal=null 不渲染 / open 渲染 overlay+dialog（aria-label=极限运行）
//   - 配置态：四档预设 + 默认 120 分钟选中 + 预计轮数随预设实时更新（公式对拍）
//   - 自定义分钟：16~720 整数（15 / 721 / 非整数置灰 + 轮数行提示）
//   - 极限参数完全隐藏：弹窗全文不出现四个参数名字样；无模式选择
//   - band/prefix 透传（2026-08-30 解除拦截）：开启 → 执行可点 + 只读状态行回显
//     + 载荷带键；关闭 → 载荷写 null（与高级运行弹窗同款）
//   - 执行 → POST /api/extreme/start（time_total_s = 分钟×60；collectStartContext 同源）
//   - 进度态：标题「极限运行」+ 门杀 chips / 大数字 / 预算条
//   - 结果态：应用按钮 + 「已固化实验参数」提示；再次运行回配置态
//   - error 态 409 互斥文案透传 + 重试原载荷；orphan 态清理（stop 路由）
//   - ESC / 遮罩 / ✕ 关闭均不触发 stop

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react';
import { ExtremeRunModal, estimateExtremeRounds, parseCustomMinutes } from '../ExtremeRunModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { useExtremeStore } from '../../../store/strategyStore';
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
let startStatus = 202;

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
  // band/prefix 2026-08-30 起透传（null = 高级配置未开启，载荷仍写 null 键）。
  band: null,
  prefix: null,
};

const EMPTY_CTX: StartContext = { ...CTX, sizes: [], quantities: null };
const BAND_PREFIX_CTX: StartContext = {
  ...CTX,
  band: { enabled: true, label: 'g05' },
  prefix: { enabled: true, front: 'g01', back: 'g02' },
};

beforeEach(() => {
  useControlPanelStore.getState().closeModal();
  useExtremeStore.getState().reset();
  startBodies = [];
  stopCalls = 0;
  statusPayload = { state: 'idle' };
  resultPayload = null;
  startStatus = 202;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/api/extreme/start')) {
      startBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      if (startStatus !== 202) {
        return Promise.resolve(json({ error: '已有进行中的策略运行（或检测到遗留 marker），请先停止/清理' }, startStatus));
      }
      return Promise.resolve(json({ started: true, pid: 9, mode: 'extreme', run_name: 'w', time_total_s: 7200 }, 202));
    }
    if (url.includes('/api/extreme/stop')) {
      stopCalls += 1;
      return Promise.resolve(json({ stopped: true, pid: 9 }));
    }
    if (url.includes('/api/extreme/status')) return Promise.resolve(json(statusPayload));
    if (url.includes('/api/extreme/result')) {
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
  useExtremeStore.getState().reset();
  fetchSpy?.mockRestore();
  fetchSpy = null;
});

function renderModal(solving = false, ctx: StartContext = CTX): void {
  act(() => {
    root!.render(<ExtremeRunModal solving={solving} buildStartContext={() => ctx} />);
  });
}

function openModal(): void {
  act(() => {
    useControlPanelStore.getState().openModal('extreme_run');
  });
}

function setPhase(partial: {
  phase: StrategyStatus['state'];
  status?: StrategyStatus | null;
  result?: StrategyResult | null;
}): void {
  act(() => {
    useExtremeStore.setState(partial);
  });
}

/** 极限运行中 fixture（race 展开：seed0 完成、seed1 门杀、seed2 当前）。 */
const EXTREME_RUNNING: StrategyStatus = {
  state: 'running',
  mode: 'extreme',
  total_budget_sec: 7200,
  elapsed_sec: 625.4,
  run_dir: 'out/config_runs/web_extreme_x_1',
  plan: { planned_seeds: [0, 1, 2, 3, 4], gate_seconds: 300 },
  incumbent: { density: 0.8632, width_mm: 7100, seed: 0, frame_index: 5, elapsed: 590 },
  current: { seed: 2, density: 0.851, density_sparrow: 0.88, ext: false },
  per_seed: [{ seed: 0, killed: false, kill_reason: null, best_density: 0.8632, elapsed: 580, phase: 'race' }],
  events: [{ kind: 'gate', seed: 1, t: 301, d: 0.851, bar: 0.8632, would_kill: true }],
  error: null,
  exit_code: null,
};

const EXTREME_RESULT: StrategyResult = {
  state: 'done',
  mode: 'extreme',
  run_dir: 'out/config_runs/web_extreme_x_1',
  manifest: { gate_mm: 1980, total_area_mm2: 1e6, n_eroded: 0, pieces: [] },
  best: { seed: 3, frame_index: 5, elapsed: 590, density: 0.8838, density_sparrow: 0.9, width_mm: 7100.5, placed_items: [] },
  summary: {
    per_seed: [
      { seed: 0, killed: false, kill_reason: null, best_density: 0.86, elapsed: 580, phase: 'race' },
      { seed: 1, killed: true, kill_reason: 'R5_race_gate', best_density: 0.85, elapsed: 302, phase: 'race' },
    ],
    mode: 'race',
    race: { gate_seconds: 300, kept_seeds: [0, 3], gated_seeds: [1, 2] },
  },
};

function setInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

describe('ExtremeRunModal 纯函数 (US-003)', () => {
  it('estimateExtremeRounds 公式对拍：N = 1 + floor((T - 602.5) / 347.5)', () => {
    expect(estimateExtremeRounds(905)).toBe(1);
    expect(estimateExtremeRounds(960)).toBe(2);    // 自定义下限 16min
    expect(estimateExtremeRounds(3600)).toBe(9);   // 60min
    expect(estimateExtremeRounds(7200)).toBe(19);  // 120min（默认档）
    expect(estimateExtremeRounds(14400)).toBe(40); // 240min
    expect(estimateExtremeRounds(28800)).toBe(82); // 480min
    expect(estimateExtremeRounds(43200)).toBe(123); // 720min 上限
  });

  it('parseCustomMinutes：16~720 整数；越界 / 非整 / 空串 → null', () => {
    expect(parseCustomMinutes('16')).toBe(16);
    expect(parseCustomMinutes('720')).toBe(720);
    expect(parseCustomMinutes('15')).toBeNull();
    expect(parseCustomMinutes('721')).toBeNull();
    expect(parseCustomMinutes('12.5')).toBeNull();
    expect(parseCustomMinutes('abc')).toBeNull();
    expect(parseCustomMinutes('')).toBeNull();
  });
});

describe('ExtremeRunModal (US-003)', () => {
  it('modal=null 不渲染（无 portal DOM）', () => {
    renderModal();
    expect(document.body.querySelector('[data-testid="extreme-overlay"]')).toBeNull();
  });

  it('open 渲染 overlay + dialog（aria-label=极限运行）+ 四档预设 + 默认 120 分钟 + 轮数 19', () => {
    openModal();
    renderModal();
    const modal = document.body.querySelector('.strategy-modal')!;
    expect(modal.getAttribute('role')).toBe('dialog');
    expect(modal.getAttribute('aria-label')).toBe('极限运行');
    for (const m of [60, 120, 240, 480]) {
      expect(document.body.querySelector(`[data-testid="extreme-preset-${m}"]`)).not.toBeNull();
    }
    const active = document.body.querySelector('[data-testid="extreme-preset-120"]')!;
    expect(active.className).toContain('active');
    const rounds = document.body.querySelector('[data-testid="extreme-rounds"]')!.textContent!;
    expect(rounds).toContain('预计 19 轮');
    expect(rounds).toContain('实际轮数 ≥ 预测');
  });

  it('预设切换 → 预计轮数实时更新（60→9 / 240→40 / 480→82）', () => {
    openModal();
    renderModal();
    const rounds = () => document.body.querySelector('[data-testid="extreme-rounds"]')!.textContent!;
    act(() => {
      (document.body.querySelector('[data-testid="extreme-preset-60"]') as HTMLButtonElement).click();
    });
    expect(rounds()).toContain('预计 9 轮');
    act(() => {
      (document.body.querySelector('[data-testid="extreme-preset-240"]') as HTMLButtonElement).click();
    });
    expect(rounds()).toContain('预计 40 轮');
    act(() => {
      (document.body.querySelector('[data-testid="extreme-preset-480"]') as HTMLButtonElement).click();
    });
    expect(rounds()).toContain('预计 82 轮');
  });

  it('自定义：切自定义显输入框；16 → 2 轮可执行；15 / 721 → 置灰 + 提示', () => {
    openModal();
    renderModal();
    act(() => {
      (document.body.querySelector('[data-testid="extreme-preset-custom"]') as HTMLButtonElement).click();
    });
    const input = document.body.querySelector('[data-testid="extreme-custom-input"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    const exec = () => document.body.querySelector('[data-testid="extreme-exec-btn"]') as HTMLButtonElement;
    const rounds = () => document.body.querySelector('[data-testid="extreme-rounds"]')!.textContent!;

    act(() => { setInputValue(input, '16'); });
    expect(rounds()).toContain('预计 2 轮');
    expect(exec().disabled).toBe(false);

    act(() => { setInputValue(input, '15'); });
    expect(exec().disabled).toBe(true);
    expect(rounds()).toContain('16~720');

    act(() => { setInputValue(input, '721'); });
    expect(exec().disabled).toBe(true);
  });

  it('极限参数完全隐藏：弹窗全文不出现四个参数名字样；无模式选择下拉', () => {
    openModal();
    renderModal();
    const text = document.body.querySelector('.strategy-modal')!.textContent ?? '';
    expect(text).not.toContain('exploration_pct');
    expect(text).not.toContain('early_termination');
    expect(text).not.toContain('num_workers');
    expect(text).not.toContain('quadtree_depth');
    expect(document.body.querySelector('[data-testid="strategy-mode"]')).toBeNull();
  });

  it('band/prefix 开启（2026-08-30 透传）→ 执行可点 + 只读状态行回显；关闭后状态行消失', () => {
    openModal();
    renderModal(false, BAND_PREFIX_CTX);
    const exec = document.body.querySelector('[data-testid="extreme-exec-btn"]') as HTMLButtonElement;
    expect(exec.disabled).toBe(false);
    const hint = document.body.querySelector('[data-testid="extreme-layout-hint"]')!;
    expect(hint.textContent).toContain('将随排料参数生效');
    expect(hint.textContent).toContain('腰头成带 g05');
    expect(hint.textContent).toContain('起始端成套 g01/g02');
    renderModal(false, CTX);
    expect((document.body.querySelector('[data-testid="extreme-exec-btn"]') as HTMLButtonElement).disabled).toBe(false);
    expect(document.body.querySelector('[data-testid="extreme-layout-hint"]')).toBeNull();
  });

  it('执行 click → POST /api/extreme/start：time_total_s = 分钟×60 + collectStartContext 同源字段（band/prefix null 透传）', async () => {
    openModal();
    renderModal();
    act(() => {
      (document.body.querySelector('[data-testid="extreme-preset-240"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      (document.body.querySelector('[data-testid="extreme-exec-btn"]') as HTMLButtonElement).click();
    });
    expect(startBodies).toHaveLength(1);
    expect(startBodies[0]).toEqual({
      time_total_s: 14400,
      seed: 5,
      gate_mm: 1980,
      sizes: [30, 32],
      per_type: null,
      quantities: { g01: { '30': 2, '32': 1 } },
      band: null,
      prefix: null,
    });
  });

  it('band/prefix 开启时执行 → 载荷带 ctx.band / ctx.prefix 原形态（默认 120 分钟档）', async () => {
    openModal();
    renderModal(false, BAND_PREFIX_CTX);
    await act(async () => {
      (document.body.querySelector('[data-testid="extreme-exec-btn"]') as HTMLButtonElement).click();
    });
    expect(startBodies).toHaveLength(1);
    expect(startBodies[0]).toEqual({
      time_total_s: 7200,
      seed: 5,
      gate_mm: 1980,
      sizes: [30, 32],
      per_type: null,
      quantities: { g01: { '30': 2, '32': 1 } },
      band: { enabled: true, label: 'g05' },
      prefix: { enabled: true, front: 'g01', back: 'g02' },
    });
  });

  it('执行 disabled：solving / sizes 空', () => {
    openModal();
    renderModal(true, CTX);
    expect((document.body.querySelector('[data-testid="extreme-exec-btn"]') as HTMLButtonElement).disabled).toBe(true);
    renderModal(false, EMPTY_CTX);
    expect((document.body.querySelector('[data-testid="extreme-exec-btn"]') as HTMLButtonElement).disabled).toBe(true);
  });

  it('进度态：标题「极限运行」+ 大数字 + 预算条 + 门杀 chip + 事件行 + 终止按钮', () => {
    openModal();
    renderModal();
    setPhase({ phase: 'running', status: EXTREME_RUNNING });
    expect(document.body.querySelector('[data-testid="strategy-progress-title"]')!.textContent)
      .toContain('极限运行');
    expect(document.body.querySelector('[data-testid="strategy-big-density"]')!.textContent).toBe('86.32%');
    expect(document.body.querySelector('[data-testid="strategy-budget-bar"]')).not.toBeNull();
    const chips = Array.from(document.body.querySelectorAll('[data-testid="strategy-seed-chips"] .strategy-chip'));
    expect(chips.some((c) => c.className.includes('killed'))).toBe(true);
    expect(document.body.querySelector('[data-testid="strategy-event"]')!.textContent).toContain('门杀');
    expect(document.body.querySelector('[data-testid="strategy-stop-btn"]')).not.toBeNull();
  });

  it('终止按钮 → POST /api/extreme/stop', async () => {
    openModal();
    renderModal();
    setPhase({ phase: 'running', status: EXTREME_RUNNING });
    await act(async () => {
      (document.body.querySelector('[data-testid="strategy-stop-btn"]') as HTMLButtonElement).click();
    });
    expect(stopCalls).toBe(1);
  });

  it('结果态：完成 + 应用按钮 + 「已固化实验参数」提示；再次运行回配置态', () => {
    openModal();
    renderModal();
    setPhase({ phase: 'done', status: { state: 'done', mode: 'extreme' } as StrategyStatus, result: EXTREME_RESULT });
    expect(document.body.querySelector('[data-testid="strategy-result-head"]')!.textContent)
      .toContain('完成 · 最优 88.38%');
    expect(document.body.querySelector('[data-testid="strategy-apply-btn"]')).not.toBeNull();
    expect(document.body.querySelector('[data-testid="strategy-result-extra-hint"]')!.textContent)
      .toContain('已固化实验参数');
    act(() => {
      (document.body.querySelector('[data-testid="strategy-again-btn"]') as HTMLButtonElement).click();
    });
    expect(document.body.querySelector('[data-testid="extreme-presets"]')).not.toBeNull();
  });

  it('结果态应用按钮 → onApplyExtreme 回调透传 result', () => {
    const calls: StrategyResult[] = [];
    act(() => {
      root!.render(
        <ExtremeRunModal solving={false} buildStartContext={() => CTX} onApplyExtreme={(r) => calls.push(r)} />,
      );
    });
    openModal();
    setPhase({ phase: 'done', status: { state: 'done', mode: 'extreme' } as StrategyStatus, result: EXTREME_RESULT });
    act(() => {
      (document.body.querySelector('[data-testid="strategy-apply-btn"]') as HTMLButtonElement).click();
    });
    expect(calls).toEqual([EXTREME_RESULT]);
  });

  it('error 态：409 互斥文案透传（区分对方 = 策略运行）+ 重试原载荷', async () => {
    openModal();
    renderModal();
    await act(async () => {
      await useExtremeStore.getState().start({ time_total_s: 3600, seed: 5, gate_mm: 1980, sizes: [30] });
    });
    startStatus = 409;
    statusPayload = { state: 'idle' };
    // 上一次 start 已 202 + refresh(idle) → phase idle；409 重发走 error 态
    //（error/orphan 复用 StrategyRunModal 导出组件 → testid 仍 strategy-*）。
    await act(async () => {
      await useExtremeStore.getState().start({ time_total_s: 3600, seed: 5, gate_mm: 1980, sizes: [30] });
    });
    expect(document.body.querySelector('[data-testid="strategy-error"]')!.textContent)
      .toContain('已有进行中的策略运行');
    startStatus = 202;
    statusPayload = { state: 'running', mode: 'extreme' };
    await act(async () => {
      (document.body.querySelector('[data-testid="strategy-retry-btn"]') as HTMLButtonElement).click();
    });
    expect(startBodies).toHaveLength(3);
    expect((startBodies[2] as Record<string, unknown>).time_total_s).toBe(3600);
  });

  it('orphan 态：清理按钮 → POST /api/extreme/stop', async () => {
    openModal();
    renderModal();
    setPhase({ phase: 'orphan', status: { state: 'orphan', alive: true, pid: 77, mode: 'extreme' } as StrategyStatus });
    expect(document.body.querySelector('[data-testid="strategy-orphan-head"]')).not.toBeNull();
    await act(async () => {
      (document.body.querySelector('[data-testid="strategy-cleanup-btn"]') as HTMLButtonElement).click();
    });
    expect(stopCalls).toBe(1);
  });

  it('ESC / 遮罩 / ✕ 关闭均不触发 stop（关弹窗不终止运行）', () => {
    openModal();
    renderModal();
    setPhase({ phase: 'running', status: EXTREME_RUNNING });
    act(() => {
      (document.body.querySelector('[data-testid="extreme-close"]') as HTMLButtonElement).click();
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(stopCalls).toBe(0);

    openModal();
    act(() => {
      const overlay = document.body.querySelector('[data-testid="extreme-overlay"]') as HTMLDivElement;
      overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(stopCalls).toBe(0);

    openModal();
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(stopCalls).toBe(0);
  });
});
