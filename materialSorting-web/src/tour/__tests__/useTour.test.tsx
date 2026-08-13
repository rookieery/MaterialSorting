// US-030/US-032 useTour 单测（advance-on-ready 完整模型 + skip）：
//   1. 告知型步点下一步直接推进
//   2. advance-on-ready 等待态：ready=false 不推进 + 等待态文案 + 下一步 disabled
//   3. 轮询检测 ready 翻 true 后自动推进 + 停轮询
//   4. before 副作用执行
//   5. close 后无残留定时器
//   6. US-032 skip：markSeen(activeTour) + close（视为已读不再自动触发）
//
// 测试用 vi.mock 注入可控 tour（3 步：informational / ready-gated / informational），
// 隔离 previewTour 的真实 store 耦合，专注验证 useTour 的 advance-on-ready 推进逻辑。
// vi.hoisted 确保 spy 在 vi.mock factory 执行前创建，factory 与测试用同一引用。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { JSX } from 'react';
import { useTour, type UseTourReturn } from '../useTour';
import { useTourStore } from '../../store/tourStore';
import { useUploadStore } from '../../store/uploadStore';
import { useUiStore } from '../../store/uiStore';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// vi.hoisted：spy 在 mock factory 执行前创建，factory 与测试共享同一 spy 引用。
const mocks = vi.hoisted(() => ({
  readySpy1: vi.fn(() => false),
  beforeSpy0: vi.fn(),
  beforeSpy1: vi.fn(),
}));

// 注入 3 步可控 tour：s0 告知型 / s1 ready-gated / s2 告知型。
vi.mock('../steps', () => ({
  TOURS: {
    preview: {
      tabId: 'preview',
      steps: [
        { id: 's0', selector: '[data-mock="a"]', title: 'T0', body: 'B0', before: mocks.beforeSpy0 },
        {
          id: 's1',
          selector: '[data-mock="b"]',
          title: 'T1',
          body: 'B1',
          ready: mocks.readySpy1,
          readyHint: 'mock-hint',
          before: mocks.beforeSpy1,
        },
        { id: 's2', selector: '[data-mock="c"]', title: 'T2', body: 'B2' },
      ],
    },
  },
  TOUR_VERSION: '1',
}));

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let returned: UseTourReturn | null = null;

/** 测试 harness：调用 useTour 并把返回值塞到外部变量供断言。 */
function Harness(): JSX.Element {
  returned = useTour();
  return <></>;
}

beforeEach(() => {
  localStorage.clear();
  useTourStore.setState({
    activeTour: null,
    stepIndex: 0,
    seen: { preview: true, nesting: true },
  });
  useUploadStore.getState().reset();
  useUiStore.getState().setTab('preview');
  mocks.readySpy1.mockReset();
  mocks.readySpy1.mockReturnValue(false);
  mocks.beforeSpy0.mockClear();
  mocks.beforeSpy1.mockClear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  returned = null;
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
  returned = null;
});

function mountHarness(): void {
  act(() => {
    root!.render(<Harness />);
  });
}

describe('useTour advance-on-ready (US-030)', () => {
  it('1. 告知型步点下一步直接推进', () => {
    mountHarness();
    act(() => {
      useTourStore.getState().start('preview');
    });
    // step0 (s0) 告知型：点 next 直接推进到 step1
    expect(useTourStore.getState().stepIndex).toBe(0);
    act(() => {
      returned!.next();
    });
    expect(useTourStore.getState().stepIndex).toBe(1);
  });

  it('2. advance-on-ready 等待态：ready=false 不推进 + 等待态文案 + 下一步 disabled', () => {
    mocks.readySpy1.mockReturnValue(false);
    mountHarness();
    act(() => {
      useTourStore.getState().start('preview');
    });
    // 推进到 step1（ready-gated，ready=false）
    act(() => {
      returned!.next();
    });
    expect(useTourStore.getState().stepIndex).toBe(1); // 推进到 step1
    // step1 等待态：waiting + readyHint
    expect(returned!.waiting).toBe(true);
    expect(returned!.readyHint).toBe('mock-hint');
    expect(returned!.currentStep?.id).toBe('s1');
    // 下一步 disabled（defensive：waiting 时 next() no-op，不继续推进）
    act(() => {
      returned!.next();
    });
    expect(useTourStore.getState().stepIndex).toBe(1); // 仍停在 step1，不推进
  });

  it('3. 轮询检测 ready 翻 true 后自动推进 + 停轮询', () => {
    vi.useFakeTimers();
    mocks.readySpy1.mockReturnValue(false);
    mountHarness();
    act(() => {
      useTourStore.getState().start('preview');
    });
    act(() => {
      returned!.next();
    }); // -> step1, waiting, 轮询启动
    expect(useTourStore.getState().stepIndex).toBe(1);
    expect(returned!.waiting).toBe(true);

    // ready 翻 true
    mocks.readySpy1.mockReturnValue(true);
    // 推进 200ms -> 轮询检测 ready=true -> 自动推进
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(useTourStore.getState().stepIndex).toBe(2); // 自动推进到 step2
    expect(returned!.waiting).toBe(false);
    // 停轮询：再推 1000ms 无变化（已停轮询；step2 告知型无 ready 无轮询）
    const spy = vi.spyOn(window, 'clearInterval');
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(useTourStore.getState().stepIndex).toBe(2); // 无额外推进
    spy.mockRestore();
    vi.useRealTimers();
  });

  it('4. before 副作用执行（进入步骧时调 before）', () => {
    mountHarness();
    act(() => {
      useTourStore.getState().start('preview');
    });
    // 进入 step0 -> beforeSpy0 调用
    expect(mocks.beforeSpy0).toHaveBeenCalled();
    // 推进到 step1 -> beforeSpy1 调用
    mocks.readySpy1.mockReturnValue(true); // ready=true 让推进不等待
    act(() => {
      returned!.next();
    });
    expect(mocks.beforeSpy1).toHaveBeenCalled();
  });

  it('5. close 后无残留定时器', () => {
    vi.useFakeTimers();
    mocks.readySpy1.mockReturnValue(false);
    mountHarness();
    act(() => {
      useTourStore.getState().start('preview');
    });
    act(() => {
      returned!.next();
    }); // -> step1, waiting, 轮询启动
    expect(returned!.waiting).toBe(true);

    // close -> 清轮询 + activeTour=null
    act(() => {
      returned!.close();
    });
    expect(useTourStore.getState().activeTour).toBeNull();

    // 推进 1000ms：无残留定时器 -> 不应有任何状态变化（activeTour 仍 null）
    const stepBefore = useTourStore.getState().stepIndex;
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(useTourStore.getState().stepIndex).toBe(stepBefore); // 无自动推进
    expect(useTourStore.getState().activeTour).toBeNull(); // 仍关闭

    vi.useRealTimers();
  });
});

describe('useTour US-032 skip', () => {
  it('6. skip：markSeen(activeTour) + close', () => {
    // seen 初始 false（确保 skip 能写 true）
    useTourStore.setState({ seen: { preview: false, nesting: false } });
    mountHarness();
    act(() => {
      useTourStore.getState().start('preview');
    });
    expect(useTourStore.getState().activeTour).toBe('preview');
    expect(useTourStore.getState().seen.preview).toBe(false);

    // skip → markSeen('preview') + close
    act(() => {
      returned!.skip();
    });

    // markSeen 持久化
    expect(useTourStore.getState().seen.preview).toBe(true);
    expect(localStorage.getItem('ms.tour.seen.preview')).toBe('1');
    // close（activeTour=null）
    expect(useTourStore.getState().activeTour).toBeNull();
  });

  it('7. skip 在等待态时清轮询 + markSeen + close（无残留定时器）', () => {
    vi.useFakeTimers();
    mocks.readySpy1.mockReturnValue(false);
    mountHarness();
    act(() => {
      useTourStore.getState().start('preview');
    });
    // 推进到 step1（ready-gated，waiting=true，轮询启动）
    act(() => {
      returned!.next();
    });
    expect(returned!.waiting).toBe(true);

    // skip 从等待态调用
    act(() => {
      returned!.skip();
    });

    expect(useTourStore.getState().activeTour).toBeNull();
    expect(useTourStore.getState().seen.preview).toBe(true);

    // 推进 1000ms：无残留定时器 → 无状态变化
    const stepBefore = useTourStore.getState().stepIndex;
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(useTourStore.getState().stepIndex).toBe(stepBefore);
    expect(useTourStore.getState().activeTour).toBeNull();

    vi.useRealTimers();
  });
});
