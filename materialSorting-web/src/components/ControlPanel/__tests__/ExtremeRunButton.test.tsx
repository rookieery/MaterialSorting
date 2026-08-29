// US-003 ExtremeRunButton 单测（范本 StrategyRunButton.test.tsx）：
//   - 入口 disabled 透传 / 点击开 'extreme_run' 弹窗（modal 单例互斥）
//   - 极限运行中徽标（useExtremeStore starting/running）
//   - 常驻 useStrategyPoll(modalOpen, useExtremeStore)：mount refresh 打
//     /api/extreme/status（族端点 —— 与 /api/strategy/status 不重叠）

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react';
import { ExtremeRunButton } from '../ExtremeRunButton';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { useExtremeStore } from '../../../store/strategyStore';
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
  band: null,
  prefix: null,
};

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;

beforeEach(() => {
  useControlPanelStore.getState().closeModal();
  useExtremeStore.getState().reset();
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
  useExtremeStore.getState().reset();
  fetchSpy?.mockRestore();
  fetchSpy = null;
});

function renderButton(disabled = false): void {
  act(() => {
    root!.render(
      <ExtremeRunButton solving={false} buildStartContext={() => CTX} disabled={disabled} />,
    );
  });
}

describe('ExtremeRunButton (US-003)', () => {
  it('disabled prop 透传', () => {
    renderButton(true);
    expect((document.body.querySelector('[data-testid="extreme-btn"]') as HTMLButtonElement).disabled).toBe(true);
    renderButton(false);
    expect((document.body.querySelector('[data-testid="extreme-btn"]') as HTMLButtonElement).disabled).toBe(false);
  });

  it('点击 → openModal(extreme_run)（modal 单例值，与 strategy_run 互斥）', () => {
    renderButton();
    act(() => {
      (document.body.querySelector('[data-testid="extreme-btn"]') as HTMLButtonElement).click();
    });
    expect(useControlPanelStore.getState().modal).toBe('extreme_run');
  });

  it('极限运行中（starting/running）→ 入口徽标「运行中」；idle 无徽标', () => {
    renderButton();
    expect(document.body.querySelector('[data-testid="extreme-badge"]')).toBeNull();
    act(() => {
      useExtremeStore.setState({ phase: 'running' });
    });
    expect(document.body.querySelector('[data-testid="extreme-badge"]')!.textContent).toContain('运行中');
    act(() => {
      useExtremeStore.setState({ phase: 'idle' });
    });
    expect(document.body.querySelector('[data-testid="extreme-badge"]')).toBeNull();
  });

  it('常驻轮询 mount refresh 打 /api/extreme/status（族端点，不打 /api/strategy/status）', () => {
    renderButton();
    const urls = fetchSpy!.mock.calls.map((c: unknown[]) => String(c[0]));
    expect(urls.some((u) => u.includes('/api/extreme/status'))).toBe(true);
    expect(urls.some((u) => u.includes('/api/strategy/status'))).toBe(false);
  });
});
