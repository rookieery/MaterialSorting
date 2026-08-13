// useTour —— tour 控制器 hook（US-029 基础设施 / US-030 完整 advance-on-ready + 自动触发 / US-032 skip）。
//
// 职责（App 生命周期内 TourOverlay 单例调用一次）：
//   1. 订阅 tourStore.activeTour/stepIndex，从 TOURS 读 currentStep（派生）。
//   2. 步骤切换 effect（dep=[activeTour, stepIndex]）：
//      - 清旧轮询 + 调 currentStep.before()（副作用）。
//      - advance-on-ready（统一轮询）：当前步有 ready 谓词且 ready()===false -> 切等待态
//        （waiting=true + 显示 readyHint + 下一步按钮 disabled）+ 启动 200ms 轮询调 ready()
//        （读 uploadStore.getState()/uiStore.getState() 快照）；ready()===true 时停轮询 +
//        自动推进（最后一步 = markSeen + close，非最后 = storeNext）。
//      - 告知型步（无 ready）或 ready 已 true -> 不等待，下一步按钮可点。
//   3. next()：最后一步 -> markSeen + close；否则 storeNext（新步的 ready 由 effect 处理）。
//      waiting 时按钮 disabled（defensive guard：waiting 时 next() 直接 return）。
//   4. prev() / close()：清轮询 + storePrev / storeClose。
//   5. skip()（US-032）：markSeen(activeTour) + close —— 视为已读不再自动触发。
//      区别于 close()：close 仅关闭（不 markSeen，下次进 Tab 可再自动触发）；
//      skip 是用户显式「跳过」-> markSeen 持久化，不再自动触发。
//
// advance-on-ready 模型（US-030，检查当前步语义）：
//   - 告知型步（无 ready）：用户读气泡 -> 点下一步直接推进（教学后用户自行操作）。
//   - 联动型步（有 ready）：进入该步时 ready()===false -> 等待态 + 轮询；ready 翻 true 后
//     自动推进。故解析完成 / commit 完成 / 切到超排 Tab 均自动推进，无需手动点下一步
//     （AC：step2 解析 / step4 commit 在完成后自动推进，step5 切 Tab 后自动完成）。
//   - before() 在进入该步时调（切 Tab / 滚动等副作用），需幂等（StrictMode 双 mount）。
//
// useTourAutoTrigger（US-030 首次进入 Tab 自动触发，独立 hook，App 调用一次）：
//   - subscribe uiStore.activeTab；tab 变化且 !seen[tab] && TOURS[tab] 存在 && 无 tour 运行
//     -> 延迟 300ms（等目标 DOM 稳定）后 start(tab)。
//   - App 首次 mount 即对齐当前 activeTab（迟到挂载 / 刷新恢复兜底）。
//   - 独立于 useTour（TourOverlay 测试不触发自动启动，保持隔离）。
//
// 关键不变量：
//   - 轮询定时器用 useRef 持有，close/unmount/stepIndex 变化时 clearInterval（无泄漏）。
//   - before() 在 useEffect dep=[activeTour, stepIndex] 内调（StrictMode 双 mount 会调两次，
//     before 需幂等；US-032 打磨 StrictMode 幂等）。
//   - start(tabId) 转发 tourStore.start；TabBar 可直接调 useTourStore.getState().start。

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTourStore } from '../store/tourStore';
import { useUiStore, type TabId } from '../store/uiStore';
import type { TourDef, TourStep } from './types';
import { TOURS } from './steps';

/** advance-on-ready 轮询间隔（ms）；ready()===false 时每 200ms 重试。 */
const READY_POLL_INTERVAL_MS = 200;
/** 自动触发延迟（ms）；tab 切换后等目标 DOM 稳定再 start。 */
const AUTO_TRIGGER_DELAY_MS = 300;

/** 当前激活的 TourDef（查 TOURS 注册表；无则 null）。 */
function getActiveTour(activeTour: TabId | null): TourDef | null {
  if (!activeTour) return null;
  return TOURS[activeTour] ?? null;
}

export interface UseTourReturn {
  /** 当前激活的 Tab（null = 无 tour 运行）。 */
  activeTour: TabId | null;
  /** 当前步骤序号。 */
  stepIndex: number;
  /** 当前步骤定义（null = 无 tour 或越界）。 */
  currentStep: TourStep | null;
  /** 当前 tour 定义（null = 无 tour）。 */
  tour: TourDef | null;
  /** 等待态：目标步 ready()===false，下一步 disabled + 轮询中。 */
  waiting: boolean;
  /** 等待态提示文案（来自目标步 readyHint）；非等待态为 undefined。 */
  readyHint: string | undefined;
  /** 是否最后一步（next → close + markSeen）。 */
  isLastStep: boolean;
  /** 是否第一步（prev 按钮 disabled）。 */
  isFirstStep: boolean;
  /** 推进下一步（含 advance-on-ready 逻辑）。 */
  next: () => void;
  /** 回退上一步（清等待态 + floor clamp）。 */
  prev: () => void;
  /** 关闭 tour（清等待态 + 轮询 + activeTour=null；不 markSeen，可再自动触发）。 */
  close: () => void;
  /** 跳过 tour（markSeen + close；视为已读不再自动触发）。US-032。 */
  skip: () => void;
  /** 启动 tour（转发 tourStore.start）。 */
  start: (tabId: TabId) => void;
}

export function useTour(): UseTourReturn {
  const activeTour = useTourStore((s) => s.activeTour);
  const stepIndex = useTourStore((s) => s.stepIndex);
  const storeNext = useTourStore((s) => s.next);
  const storePrev = useTourStore((s) => s.prev);
  const storeClose = useTourStore((s) => s.close);
  const markSeen = useTourStore((s) => s.markSeen);
  const startStore = useTourStore((s) => s.start);

  const [waiting, setWaiting] = useState(false);
  const [readyHint, setReadyHint] = useState<string | undefined>(undefined);
  const pollRef = useRef<number | null>(null);

  const tour = getActiveTour(activeTour);
  const steps = tour?.steps ?? [];
  const currentStep: TourStep | null =
    tour && stepIndex >= 0 && stepIndex < steps.length ? steps[stepIndex] : null;
  const isLastStep = steps.length > 0 && stepIndex >= steps.length - 1;
  const isFirstStep = stepIndex <= 0;

  /** 清轮询定时器 + 重置等待态（stepIndex 变化 / close / unmount 时调）。 */
  const clearPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setWaiting(false);
    setReadyHint(undefined);
  }, []);

  // 步骤切换 / tour 切换时：清旧轮询 + 调 before() + 联动步启动 advance-on-ready 轮询。
  // cleanup 兜底清轮询（StrictMode 双 mount / unmount / stepIndex 变化）。
  useEffect(() => {
    clearPolling();
    if (currentStep?.before) {
      currentStep.before();
    }
    // advance-on-ready：当前步有 ready 且 ready()===false -> 等待态 + 轮询。
    if (currentStep?.ready && !currentStep.ready()) {
      setWaiting(true);
      setReadyHint(currentStep.readyHint);
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
      }
      pollRef.current = window.setInterval(() => {
        if (currentStep.ready && currentStep.ready()) {
          if (pollRef.current !== null) {
            window.clearInterval(pollRef.current);
            pollRef.current = null;
          }
          setWaiting(false);
          setReadyHint(undefined);
          // 最后一步自动完成；否则自动推进到下一步
          if (isLastStep) {
            markSeen(activeTour!);
            storeClose();
          } else {
            storeNext();
          }
        }
      }, READY_POLL_INTERVAL_MS);
    }
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
    // dep 仅 activeTour/stepIndex（currentStep/isLastStep 是派生值；store actions 稳定引用）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTour, stepIndex]);

  const next = useCallback(() => {
    if (!tour || !currentStep) return;
    if (waiting) return; // defensive：等待态时按钮 disabled，不应进入
    // 最后一步 -> close + markSeen
    if (isLastStep) {
      clearPolling();
      markSeen(activeTour!);
      storeClose();
      return;
    }
    // 告知型 / ready=true -> 直接推进（新步的 ready 由 step-change effect 处理）
    clearPolling();
    storeNext();
  }, [tour, currentStep, waiting, isLastStep, activeTour, markSeen, storeClose, storeNext, clearPolling]);

  const prev = useCallback(() => {
    clearPolling();
    storePrev();
  }, [clearPolling, storePrev]);

  const close = useCallback(() => {
    clearPolling();
    storeClose();
  }, [clearPolling, storeClose]);

  // skip（US-032）：markSeen + close —— 用户显式跳过，视为已读不再自动触发。
  // markSeen 幂等（store 层已防重复写 localStorage）；close 清轮询 + activeTour=null。
  const skip = useCallback(() => {
    if (activeTour) {
      markSeen(activeTour);
    }
    clearPolling();
    storeClose();
  }, [activeTour, markSeen, clearPolling, storeClose]);

  const start = useCallback(
    (tabId: TabId) => {
      startStore(tabId);
    },
    [startStore],
  );

  return {
    activeTour,
    stepIndex,
    currentStep,
    tour,
    waiting,
    readyHint,
    isLastStep,
    isFirstStep,
    next,
    prev,
    close,
    skip,
    start,
  };
}

/**
 * useTourAutoTrigger —— 首次进入 Tab 自动启动 tour（US-030）。
 *
 * App 顶层调用一次。subscribe uiStore.activeTab：tab 变化且 !seen[tab] && TOURS[tab] 存在
 * && 无 tour 运行 -> 延迟 300ms（等目标 DOM 稳定）后 start(tab)。mount 即对齐当前 activeTab
 * （App 首次 mount / 刷新恢复兜底）。
 *
 * 独立于 useTour（TourOverlay 测试不渲染 App -> 不触发自动启动，保持单元测试隔离）。
 */
export function useTourAutoTrigger(): void {
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    const arm = (tab: TabId): void => {
      const { seen, activeTour } = useTourStore.getState();
      // 已看过 / 正在跑 tour / 该 Tab 无指引 -> 不触发
      if (seen[tab]) return;
      if (activeTour !== null) return;
      if (!TOURS[tab]) return;
      // 延迟 300ms 等目标 DOM 稳定（display:none 取消后布局才就绪）
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        // re-check：延迟期间用户可能已手动启动 / markSeen
        const s = useTourStore.getState();
        if (!s.seen[tab] && s.activeTour === null) {
          s.start(tab);
        }
      }, AUTO_TRIGGER_DELAY_MS);
    };

    // mount 即对齐当前 activeTab（App 首次 mount / 刷新恢复）
    arm(useUiStore.getState().activeTab);

    // subscribe tab 变化（prevState 对比，仅切 Tab 时 arm）
    const unsub = useUiStore.subscribe((state, prevState) => {
      if (state.activeTab !== prevState.activeTab) {
        arm(state.activeTab);
      }
    });
    return () => {
      unsub();
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);
}
