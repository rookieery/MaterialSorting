// toastStore 单测：push 追加 / 同文案去重（不自动消失的必要配套）/ dismiss 移除 /
// 不自动消失（fake timers 推进任意时长仍在）/ reset 辅助。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { __resetToastsForTest, useToastStore } from "../toastStore";

beforeEach(() => {
  __resetToastsForTest();
});

afterEach(() => {
  __resetToastsForTest();
  vi.useRealTimers();
});

describe("toastStore", () => {
  it("pushToast → 追加一条（message 原样）+ 返回自增 id", () => {
    const id1 = useToastStore.getState().pushToast("提示甲");
    const id2 = useToastStore.getState().pushToast("提示乙");
    expect(id2).toBeGreaterThan(id1);
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(2);
    expect(toasts[0]).toEqual({ id: id1, message: "提示甲" });
    expect(toasts[1]).toEqual({ id: id2, message: "提示乙" });
  });

  it("同文案去重：重复 push 不叠条（返回已有条目 id）", () => {
    const id1 = useToastStore.getState().pushToast("提示甲");
    const idAgain = useToastStore.getState().pushToast("提示甲");
    expect(idAgain).toBe(id1);
    expect(useToastStore.getState().toasts).toHaveLength(1);
    // 不同文案不受影响
    useToastStore.getState().pushToast("提示乙");
    expect(useToastStore.getState().toasts).toHaveLength(2);
  });

  it("关闭后同文案可再次推入（去重只对展示中的条目）", () => {
    const id1 = useToastStore.getState().pushToast("提示甲");
    useToastStore.getState().dismissToast(id1);
    const id2 = useToastStore.getState().pushToast("提示甲");
    expect(id2).not.toBe(id1);
    expect(useToastStore.getState().toasts).toHaveLength(1);
  });

  it("dismissToast → 立即移除该条", () => {
    const id1 = useToastStore.getState().pushToast("提示甲");
    const id2 = useToastStore.getState().pushToast("提示乙");
    useToastStore.getState().dismissToast(id1);
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].id).toBe(id2);
  });

  it("不自动消失：推进任意时长后仍在（唯一出口 = dismissToast）", () => {
    vi.useFakeTimers();
    useToastStore.getState().pushToast("不会自己走");
    vi.advanceTimersByTime(3600_000);
    expect(useToastStore.getState().toasts).toHaveLength(1);
    useToastStore.getState().dismissToast(useToastStore.getState().toasts[0].id);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("dismiss 不存在的 id → no-op（不抛错不动队列）", () => {
    useToastStore.getState().pushToast("存在的一条");
    useToastStore.getState().dismissToast(99999);
    expect(useToastStore.getState().toasts).toHaveLength(1);
  });

  it("__resetToastsForTest → 清空队列 + 复位计数器", () => {
    useToastStore.getState().pushToast("一条");
    __resetToastsForTest();
    expect(useToastStore.getState().toasts).toHaveLength(0);
    // 计数器复位：下一个 id 从 1 重新开始
    expect(useToastStore.getState().pushToast("新的")).toBe(1);
  });
});
