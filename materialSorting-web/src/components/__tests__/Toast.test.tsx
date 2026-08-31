// Toast 组件单测：空队列渲染 null / 有队列渲染 .toast-stack + role=status + 文案 /
// 多条并列 / ✕ 点击 dismissToast。

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { Toast } from "../Toast";
import { __resetToastsForTest, useToastStore } from "../../store/toastStore";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  __resetToastsForTest();
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
  __resetToastsForTest();
});

function renderToast() {
  act(() => {
    root!.render(
      <StrictMode>
        <Toast />
      </StrictMode>,
    );
  });
}

function getItems(): HTMLElement[] {
  return Array.from(container!.querySelectorAll<HTMLElement>(".toast-item"));
}

describe("Toast", () => {
  it("空队列 → 渲染 null（无 .toast-stack）", () => {
    renderToast();
    expect(container!.querySelector(".toast-stack")).toBeNull();
    expect(container!.childElementCount).toBe(0);
  });

  it("pushToast → 渲染 .toast-stack（role=status aria-live=polite）+ 文案", () => {
    renderToast();
    act(() => {
      useToastStore.getState().pushToast("当前 DXF 文件存在一批块名末尾带不出码号的裁片");
    });
    const stack = container!.querySelector<HTMLElement>(".toast-stack");
    expect(stack).not.toBeNull();
    expect(stack!.getAttribute("role")).toBe("status");
    expect(stack!.getAttribute("aria-live")).toBe("polite");
    const items = getItems();
    expect(items).toHaveLength(1);
    expect(items[0].textContent).toContain("带不出码号");
  });

  it("多条 → 并列渲染（顺序 = push 顺序）", () => {
    renderToast();
    act(() => {
      useToastStore.getState().pushToast("第一条");
      useToastStore.getState().pushToast("第二条");
    });
    const items = getItems();
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("第一条");
    expect(items[1].textContent).toContain("第二条");
  });

  it("✕ 点击 → dismissToast 移除该条（其余保留）", () => {
    renderToast();
    let id1 = 0;
    act(() => {
      id1 = useToastStore.getState().pushToast("第一条");
      useToastStore.getState().pushToast("第二条");
    });
    expect(getItems()).toHaveLength(2);
    const closeBtn = getItems()[0].querySelector<HTMLButtonElement>(".toast-close");
    expect(closeBtn).not.toBeNull();
    expect(closeBtn!.getAttribute("aria-label")).toBe("关闭提示");
    act(() => {
      closeBtn!.click();
    });
    // dismiss 走 store（按 id），第一条消失、第二条保留
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].id).not.toBe(id1);
    expect(getItems()).toHaveLength(1);
    expect(getItems()[0].textContent).toContain("第二条");
  });
});
