// US-005 StrategyRunButton 单测：入口 disabled / 运行中徽标 / 点击开弹窗 /
// 常驻 useStrategyPoll mount refresh（恢复进度入口，不炸 jsdom）。

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react';
import { StrategyRunButton } from '../StrategyRunButton';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { useStrategyStore } from '../../../store/strategyStore';
import type { StartContext } from '../../../lib/params';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const CTX: StartContext = {
  sizes: [30],
  gate_mm: 1980,
  seed: 0,
  time: 120,
  params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 },
  per_type: null,
  quantities: null,
};

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;

beforeEach(() => {
  useControlPanelStore.getState().closeModal();
  useStrategyStore.getState().reset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
    Promise.resolve(new Response(JSON.stringify({ representatives: {} }), { status: 200 })),
  ) as unknown as MockInstance<(...args: unknown[]) => Promise<Response>>;
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

function renderButton(disabled = false): void {
  act(() => {
    root!.render(
      <StrategyRunButton solving={false} buildStartContext={() => CTX} disabled={disabled} />,
    );
  });
}

describe('StrategyRunButton (US-005)', () => {
  it('disabled prop 透传（未 commit / solving 时由 ControlPanel 计算传入）', () => {
    renderButton(true);
    expect((document.body.querySelector('[data-testid="strategy-btn"]') as HTMLButtonElement).disabled).toBe(true);
    renderButton(false);
    expect((document.body.querySelector('[data-testid="strategy-btn"]') as HTMLButtonElement).disabled).toBe(false);
  });

  it('点击 → openModal("strategy_run")；Modal 挂载（配置态在场）', () => {
    renderButton();
    act(() => {
      (document.body.querySelector('[data-testid="strategy-btn"]') as HTMLButtonElement).click();
    });
    expect(useControlPanelStore.getState().modal).toBe('strategy_run');
    expect(document.body.querySelector('.strategy-overlay')).not.toBeNull();
    expect(document.body.querySelector('[data-testid="strategy-exec-btn"]')).not.toBeNull();
  });

  it('策略运行中（starting/running）→ 徽标「运行中」；idle 无徽标', () => {
    renderButton();
    expect(document.body.querySelector('[data-testid="strategy-badge"]')).toBeNull();
    act(() => {
      useStrategyStore.setState({ phase: 'running' });
    });
    expect(document.body.querySelector('[data-testid="strategy-badge"]')!.textContent).toBe('运行中');
    act(() => {
      useStrategyStore.setState({ phase: 'idle' });
    });
    expect(document.body.querySelector('[data-testid="strategy-badge"]')).toBeNull();
  });

  it('mount 触发一次 /api/strategy/status（useStrategyPoll 常驻恢复进度）', async () => {
    renderButton();
    await act(async () => {
      await Promise.resolve();
    });
    const calls = fetchSpy!.mock.calls.map((c: unknown[]) => String(c[0]));
    expect(calls.some((u) => u.includes('/api/strategy/status'))).toBe(true);
  });
});
