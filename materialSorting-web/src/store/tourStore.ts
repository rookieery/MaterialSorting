// TourState —— 操作指引状态中心（US-029）。
//
// 持三个语义字段 + localStorage 持久化（seen）+ 版本号强制重看机制：
//   activeTour   当前激活的 tour（TabId）；null = 无 tour 运行。start(tabId) 置非空，close() 置 null。
//   stepIndex    当前步骤序号（0-based）。next() 递增、prev() 递减（floor 0）。
//   seen         Record<TabId, boolean>；true = 该 Tab 的 tour 已看过（不再自动触发）。
//
// localStorage 持久化（key 语义）：
//   ms.tour.seen.<tabId> = "1"   —— 该 Tab tour 已看过（markSeen 写、init 读）。
//   ms.tour.version = "<TOUR_VERSION>" —— 上次看 tour 时的版本号；init 比对常量 TOUR_VERSION，
//                                        不一致则清空全部 seen（强制重看，适配步骤重大变更）。
//
// 不引入 zustand persist 中间件（显式读/写 localStorage，便于测试 + 版本号逻辑集中）。
//
// 设计原则（CLAUDE.md / AGENTS.md）：单字段 store，actions 直 set。
// activeTour/stepIndex 不持久化（刷新后 tour 不恢复，用户需手动触发）；仅 seen 持久化。
// tourStore 是纯状态层：不知道 TourDef / steps（步骤定义在 src/tour/steps/），上层 useTour
// 负责读步骤定义、before/ready 推进逻辑。next() 仅 floor clamp（stepIndex >= 0），ceiling
// clamp（不超最后一步）由 useTour 知道 steps.length 后兜底（最后一步 next → close + markSeen）。

import { create } from 'zustand';
import type { TabId } from './uiStore';
import { TOUR_VERSION } from '../tour/steps';

/** localStorage key 前缀（seen 按 tabId 分键，version 单独一个 key）。 */
const SEEN_KEY_PREFIX = 'ms.tour.seen.';
const VERSION_KEY = 'ms.tour.version';

/** 从 localStorage hydrate seen（按 tabId 逐键读 "1"）。 */
function hydrateSeen(): Record<TabId, boolean> {
  const seen: Record<TabId, boolean> = { preview: false, nesting: false };
  try {
    if (typeof localStorage === 'undefined') return seen;
    // 版本号比对：不一致则清空 seen（强制重看）
    const storedVersion = localStorage.getItem(VERSION_KEY);
    if (storedVersion !== TOUR_VERSION) {
      // 清掉所有 seen key（遍历全部 tabId，不依赖当前 TabId 列表）
      (Object.keys(seen) as TabId[]).forEach((tab) =>
        localStorage.removeItem(SEEN_KEY_PREFIX + tab),
      );
      localStorage.setItem(VERSION_KEY, TOUR_VERSION);
      return seen; // 全 false
    }
    (Object.keys(seen) as TabId[]).forEach((tab) => {
      seen[tab] = localStorage.getItem(SEEN_KEY_PREFIX + tab) === '1';
    });
  } catch {
    // localStorage 不可用（隐私模式 / SSR）→ 默认全 false，不崩
  }
  return seen;
}

export interface TourState {
  /** 当前激活的 tour；null = 无 tour 运行。 */
  activeTour: TabId | null;
  /** 当前步骤序号（0-based）。 */
  stepIndex: number;
  /** 各 Tab 的 tour 是否已看过（持久化到 localStorage）。 */
  seen: Record<TabId, boolean>;
  /** 启动指定 Tab 的 tour（置 activeTour + stepIndex=0）。 */
  start: (tabId: TabId) => void;
  /** 推进到下一步（stepIndex+1；ceiling clamp 由 useTour 兜底）。 */
  next: () => void;
  /** 回退到上一步（stepIndex-1，floor 0）。 */
  prev: () => void;
  /** 关闭 tour（activeTour=null；不改 stepIndex，下次 start 会重置）。 */
  close: () => void;
  /** 标记指定 Tab 的 tour 已看过（写 localStorage 同步持久化）。 */
  markSeen: (tabId: TabId) => void;
  /** 重置全部 seen（清 localStorage 全部 ms.tour.seen.*；下次进 Tab 自动触发）。 */
  resetSeen: () => void;
}

export const useTourStore = create<TourState>((set, get) => ({
  activeTour: null,
  stepIndex: 0,
  seen: hydrateSeen(),
  start: (tabId) => set({ activeTour: tabId, stepIndex: 0 }),
  next: () => set((s) => ({ stepIndex: s.stepIndex + 1 })),
  prev: () => set((s) => ({ stepIndex: Math.max(0, s.stepIndex - 1) })),
  close: () => set({ activeTour: null }),
  markSeen: (tabId) => {
    if (get().seen[tabId]) return; // 已 seen，no-op（避免无谓 setState + localStorage 写）
    try {
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(SEEN_KEY_PREFIX + tabId, '1');
        // 确保 version key 同步写：防 localStorage 部分清除后 re-hydrate 误判版本不一致清 seen。
        // markSeen 语义 = 用户已看当前版本 tour → version key 应 = TOUR_VERSION。
        if (localStorage.getItem(VERSION_KEY) !== TOUR_VERSION) {
          localStorage.setItem(VERSION_KEY, TOUR_VERSION);
        }
      }
    } catch {
      // localStorage 不可用 → 内存态仍更新（功能不崩，持久化降级）
    }
    set((s) => ({ seen: { ...s.seen, [tabId]: true } }));
  },
  resetSeen: () => {
    try {
      if (typeof localStorage !== 'undefined') {
        (['preview', 'nesting'] as TabId[]).forEach((tab) =>
          localStorage.removeItem(SEEN_KEY_PREFIX + tab),
        );
      }
    } catch {
      // 同上
    }
    set({ seen: { preview: false, nesting: false } });
  },
}));
