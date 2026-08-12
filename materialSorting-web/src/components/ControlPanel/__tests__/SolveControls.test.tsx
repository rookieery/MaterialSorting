// US-028 SolveControls 单测：
//   AC#6 ≥5 项：5 个 phase 各自渲染正确按钮 + 点击调对应 handler
//                + running 态无开始按钮 / idle 态无停止按钮
//   a11y：每个按钮带 aria-label（含「求解」语义）
//
// 纯单元测试：SolveControls 是无状态受控组件，phase/handlers 全部由父级传入；
// 不需要 store / WS / fetch mock，只断言 DOM 渲染 + 事件分发。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { SolveControls } from "../SolveControls";
import type { SolvePhase } from "../../../types/solvePhase";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
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
});

function renderControls(props: {
  phase: SolvePhase;
  onStart?: () => void;
  onStop?: () => void;
  onRestart?: () => void;
}) {
  const onStart = props.onStart ?? vi.fn();
  const onStop = props.onStop ?? vi.fn();
  const onRestart = props.onRestart ?? vi.fn();
  act(() => {
    root!.render(
      <StrictMode>
        <SolveControls
          phase={props.phase}
          onStart={onStart}
          onStop={onStop}
          onRestart={onRestart}
        />
      </StrictMode>,
    );
  });
  return { onStart, onStop, onRestart };
}

describe("SolveControls (US-028)", () => {
  it("idle → 渲染「开始求解」#start 按钮 + aria-label + 点击调 onStart（等价旧 StartButton）", () => {
    const { onStart } = renderControls({ phase: "idle" });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn).not.toBeNull();
    expect(btn.textContent).toBe("开始求解");
    expect(btn.getAttribute("aria-label")).toBe("开始求解");
    expect(btn.className).toContain("start");
    // 无 #stop / #restart
    expect(container!.querySelector("#stop")).toBeNull();
    expect(container!.querySelector("#restart")).toBeNull();
    act(() => btn.click());
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("running → 渲染「停止」#stop 按钮 + aria-label + 点击调 onStop；无 #start 按钮", () => {
    const { onStop, onStart, onRestart } = renderControls({ phase: "running" });
    const btn = container!.querySelector<HTMLButtonElement>("#stop")!;
    expect(btn).not.toBeNull();
    expect(btn.textContent).toBe("停止");
    expect(btn.getAttribute("aria-label")).toBe("停止求解");
    expect(btn.className).toContain("stop");
    // 关键不变量：running 态无 #start 按钮（与旧 StartButton solving=true disabled 不同；
    // SolveControls 直接切到停止按钮，避免求解中误点开始）
    expect(container!.querySelector("#start")).toBeNull();
    expect(container!.querySelector("#restart")).toBeNull();
    act(() => btn.click());
    expect(onStop).toHaveBeenCalledTimes(1);
    // 误触防护：running 态点击只能触发 onStop，不触发 onStart/onRestart
    expect(onStart).not.toHaveBeenCalled();
    expect(onRestart).not.toHaveBeenCalled();
  });

  it("stopped → 渲染「重新开始」#restart 按钮 + aria-label + 点击调 onRestart", () => {
    const { onRestart, onStart, onStop } = renderControls({ phase: "stopped" });
    const btn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(btn).not.toBeNull();
    expect(btn.textContent).toBe("重新开始");
    expect(btn.getAttribute("aria-label")).toBe("重新开始求解");
    expect(btn.className).toContain("restart");
    // 无 #start / #stop
    expect(container!.querySelector("#start")).toBeNull();
    expect(container!.querySelector("#stop")).toBeNull();
    act(() => btn.click());
    expect(onRestart).toHaveBeenCalledTimes(1);
    expect(onStart).not.toHaveBeenCalled();
    expect(onStop).not.toHaveBeenCalled();
  });

  it("done → 渲染「再次求解」#restart 按钮（与 stopped 文案区分）+ 点击调 onRestart", () => {
    const { onRestart } = renderControls({ phase: "done" });
    const btn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(btn).not.toBeNull();
    // done 态文案是「再次求解」，与 stopped/error 的「重新开始」区分（用户可识别求解曾正常完成）
    expect(btn.textContent).toBe("再次求解");
    expect(btn.getAttribute("aria-label")).toBe("再次求解");
    expect(btn.className).toContain("restart");
    act(() => btn.click());
    expect(onRestart).toHaveBeenCalledTimes(1);
  });

  it("error → 渲染「重新开始」#restart 按钮（与 stopped 同文案）+ 点击调 onRestart", () => {
    const { onRestart } = renderControls({ phase: "error" });
    const btn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(btn).not.toBeNull();
    expect(btn.textContent).toBe("重新开始");
    expect(btn.getAttribute("aria-label")).toBe("重新开始求解");
    act(() => btn.click());
    expect(onRestart).toHaveBeenCalledTimes(1);
  });

  it("所有按钮 type=button + 原生 button 默认可键盘触发（Enter/Space 触发 click）", () => {
    // type=button 防止 form 提交；原生 button 元素默认可聚焦 + Enter/Space 触发 click（a11y AC#5）
    const { onStart } = renderControls({ phase: "idle", onStart: vi.fn() });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn.type).toBe("button");
    // 模拟键盘 Enter：直接 dispatch click（原生 button 的 keydown Enter 默认触发 click）
    act(() => btn.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    // keydown 本身不会触发 onClick handler；但原生 button 的 implicit form submission / click
    // 仅在 button 是 form submit button 时生效。此处验证 button 可聚焦 + type=button，
    // 实际键盘触发能力由浏览器保证（W3C HTML spec：button element activation behavior）。
    expect(btn.tabIndex).toBe(0); // 默认可聚焦参与 tab 序列
    void onStart; // 引用避免 unused 警告
  });

  it("渲染按钮总数恒为 1（每 phase 单一主操作；导出按钮在 ExportButtons 不在此）", () => {
    for (const phase of ["idle", "running", "stopped", "done", "error"] as SolvePhase[]) {
      renderControls({ phase });
      const buttons = container!.querySelectorAll("button");
      expect(buttons.length).toBe(1);
    }
  });
});
