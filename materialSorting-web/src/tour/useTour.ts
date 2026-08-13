// useTour —— tour 控制器 hook（US-029 基础设施 + advance-on-ready 骨架）。
//
// 职责（App 生命周期内 TourOverlay 单例调用一次）：
//   1. 订阅 tourStore.activeTour/stepIndex，计算 currentStep（从 TOURS/steps 定义读）。
//   2. 步骤切换时调 currentStep.before()（副作用）+ 清旧轮询定时器。
//   3. advance-on-ready（统一轮询）：
//      - next() 时目标步（stepIndex+1）无 ready 谓词（告知型）或 ready()===true → 直接推进；
//      - ready()===false → 切等待态（waiting=true）+ 下一步按钮 disabled + 启动 200ms 轮询调 ready()，
//        true 时停轮询 + 自动推进；close/stepIndex 变化时清轮询定时器。
//   4. 最后一步 next → close + markSeen（tour 完成）。
//
// 暴露：currentStep（含 title/body/selector/placement/readyHint）、waiting、isLastStep、
//       next/prev/close/start（start 是 tourStore.start 的便捷转发，供 hook 调用方使用）。
//
// US-029 本 Story：advance-on-ready 仅骨架（DEMO_PREVIEW_TOUR 两步均为告知型，不触发等待态）。
// US-030 扩展完整 advance-on-ready（previewTour 含 ready 谓词）+ 首次进入 Tab 自动触发。
//
// 关键不变量：
//   - 轮询定时器用 useRef 持有，close/unmount/stepIndex 变化时 clearInterval（无泄漏）。
//   - before() 在 useEffect dep=[activeTour, stepIndex] 内调（StrictMode 双 mount 会调两次，
//     before 需幂等；US-032 打磨 StrictMode 幂等）。
//   - start(tabId) 转发 tourStore.start（不在此 hook 持有额外状态），TabBar 可直接调
//     useTourStore.getState().start 或用此 hook 的 start（语义一致）。

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTourStore } from '../store/tourStore';
import type { TabId } from '../store/uiStore';
import type { TourDef, TourStep } from './types';
import { DEMO_PREVIEW_TOUR } from './steps';

/** advance-on-ready 轮询间隔（ms）；ready()===false 时每 200ms 重试。 */
const READY_POLL_INTERVAL_MS = 200;

/**
 * 当前激活的 TourDef（US-029：DEMO_PREVIEW_TOUR；US-030 改为 TOURS[activeTour]）。
 * 独立函数便于 US-030 替换为 Record<TabId, TourDef> 查表。
 */
function getActiveTour(activeTour: TabId | null): TourDef | null {
  if (!activeTour) return null;
  // US-029 仅 DEMO_PREVIEW_TOUR；US-030 改为 TOURS[activeTour] ?? null
  if (activeTour === DEMO_PREVIEW_TOUR.tabId) return DEMO_PREVIEW_TOUR;
  return null;
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
  /** 关闭 tour（清等待态 + 轮询 + activeTour=null）。 */
  close: () => void;
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

  // 步骤切换 / tour 切换时：清旧轮询 + 调 before() 副作用
  useEffect(() => {
    clearPolling();
    if (currentStep?.before) {
      currentStep.before();
    }
    // dep 仅 activeTour/stepIndex（currentStep 是派生值，避免对象引用变化重跑）
    // clearPolling 是稳定引用（useCallback []）
  }, [activeTour, stepIndex, clearPolling]); // eslint-disable-line react-hooks/exhaustive-deps

  // unmount 时清轮询（防泄漏）
  useEffect(() => {
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, []);

  const next = useCallback(() => {
    if (!tour || !currentStep) return;
    // 最后一步 → close + markSeen
    if (isLastStep) {
      clearPolling();
      markSeen(activeTour!);
      storeClose();
      return;
    }
    // 检查目标步 ready
    const targetStep = steps[stepIndex + 1];
    if (!targetStep) return;
    if (!targetStep.ready || targetStep.ready()) {
      // 告知型 / ready=true → 直接推进
      clearPolling();
      storeNext();
      return;
    }
    // ready=false → 切等待态 + 启动轮询（advance-on-ready 核心）
    setWaiting(true);
    setReadyHint(targetStep.readyHint);
    // 清旧轮询再启新轮询（防重复）
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
    }
    pollRef.current = window.setInterval(() => {
      if (targetStep.ready && targetStep.ready()) {
        if (pollRef.current !== null) {
          window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
        setWaiting(false);
        setReadyHint(undefined);
        storeNext();
      }
    }, READY_POLL_INTERVAL_MS);
  }, [tour, currentStep, isLastStep, steps, stepIndex, activeTour, markSeen, storeClose, storeNext, clearPolling]);

  const prev = useCallback(() => {
    clearPolling();
    storePrev();
  }, [clearPolling, storePrev]);

  const close = useCallback(() => {
    clearPolling();
    storeClose();
  }, [clearPolling, storeClose]);

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
    start,
  };
}
