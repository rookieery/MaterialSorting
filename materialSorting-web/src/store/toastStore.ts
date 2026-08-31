// ToastState —— 全局轻提示（非阻断）队列。
//
// 定位：与 SessionExpiredModal 的阻断语义相对 —— toast 只**告知**不拦截：
//   - 不挡交互（pointer-events 仅落在自身卡片上，遮罩无）；
//   - **不自动消失**（2026-08-31 修订：数据异常告知不能被错过 —— 唯一出口 =
//     ✕ 手动关；因此同文案去重是必须的，防反复触发（如重传同一坏母版）叠条
//     且永不消散）；
//   - 无定时器，组件零清理逻辑（App 生命周期单例，整页刷新队列自然湮灭）。
//
// 首个消费方：useParseDxf 解析成功且 doc.sizes 含 null 码（块名末尾带不出
// 码号的裁片）时提示用户检查母版命名（超排页码号区已不再渲染该组 chip）。
//
// 设计与 uiStore 一致：zustand + 直 set。

import { create } from 'zustand';

/** 自增 id（模块级计数器即可，无需 uuid）。 */
let nextId = 1;

export interface ToastItem {
  id: number;
  /** 提示正文（完整一句话，调用方负责文案语义自洽）。 */
  message: string;
}

export interface ToastState {
  /** 当前展示中的 toast（先进先出，底部追加；同文案只保留一条）。 */
  toasts: ToastItem[];
  /** 推入一条提示；同文案已在展示中则跳过（返回已有条目 id，不叠条）。 */
  pushToast: (message: string) => number;
  /** 移除一条（✕ 点击唯一出口 —— 不自动消失）。 */
  dismissToast: (id: number) => void;
}

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  pushToast: (message) => {
    const existing = get().toasts.find((t) => t.message === message);
    if (existing) return existing.id; // 同文案去重：不自动消失的提示重复触发不叠条
    const id = nextId++;
    set((s) => ({ toasts: [...s.toasts, { id, message }] }));
    return id;
  },
  dismissToast: (id) => {
    set((s) =>
      s.toasts.some((x) => x.id === id) ? { toasts: s.toasts.filter((x) => x.id !== id) } : s,
    );
  },
}));

/** 测试辅助：清空队列 + 复位计数器（vitest beforeEach 用；生产代码勿调）。 */
export function __resetToastsForTest(): void {
  nextId = 1;
  useToastStore.setState({ toasts: [] });
}
