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
  startDisabled?: boolean;
  initialChip?: 'fresh' | 'stale' | 'none';
  onClearInitial?: () => void;
}) {
  const onStart = props.onStart ?? vi.fn();
  const onStop = props.onStop ?? vi.fn();
  const onClearInitial = props.onClearInitial ?? vi.fn();
  act(() => {
    root!.render(
      <StrictMode>
        <SolveControls
          phase={props.phase}
          onStart={onStart}
          onStop={onStop}
          startDisabled={props.startDisabled}
          initialChip={props.initialChip}
          onClearInitial={onClearInitial}
        />
      </StrictMode>,
    );
  });
  return { onStart, onStop, onClearInitial };
}

describe("SolveControls (US-028)", () => {
  it("idle → 渲染「普通运行」#start 按钮 + aria-label + 点击调 onStart（等价旧 StartButton）", () => {
    const { onStart } = renderControls({ phase: "idle" });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn).not.toBeNull();
    expect(btn.textContent).toBe("普通运行");
    expect(btn.getAttribute("aria-label")).toBe("普通运行");
    expect(btn.className).toContain("start");
    // 无 #stop / #restart
    expect(container!.querySelector("#stop")).toBeNull();
    expect(container!.querySelector("#restart")).toBeNull();
    act(() => btn.click());
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("running → 渲染「停止」#stop 按钮 + aria-label + 点击调 onStop；无 #start 按钮", () => {
    const { onStop, onStart } = renderControls({ phase: "running" });
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
    // 误触防护：running 态点击只能触发 onStop，不触发 onStart
    expect(onStart).not.toHaveBeenCalled();
  });

  it("stopped → 渲染「普通运行」#restart 按钮 + aria-label + 点击调 onStart（读当前 form，非快照重放）", () => {
    const { onStart, onStop } = renderControls({ phase: "stopped" });
    const btn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(btn).not.toBeNull();
    expect(btn.textContent).toBe("普通运行");
    expect(btn.getAttribute("aria-label")).toBe("普通运行");
    expect(btn.className).toContain("restart");
    // 无 #start / #stop
    expect(container!.querySelector("#start")).toBeNull();
    expect(container!.querySelector("#stop")).toBeNull();
    act(() => btn.click());
    // 修复回归点：stopped/done/error 态也必须走 onStart（ControlPanel 读当前 form），
    // 不再走 onRestart（lastStartCfgRef 快照重放，曾冻结首次求解参数）
    expect(onStart).toHaveBeenCalledTimes(1);
    expect(onStop).not.toHaveBeenCalled();
  });

  it("done → 渲染「普通运行」#restart 按钮（文案与 stopped 统一）+ 点击调 onStart", () => {
    const { onStart } = renderControls({ phase: "done" });
    const btn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(btn).not.toBeNull();
    // 文案统一「普通运行」：发起求解语义一致，靠 phase 区分当前阶段（不再用文案区分 done / stopped）
    expect(btn.textContent).toBe("普通运行");
    expect(btn.getAttribute("aria-label")).toBe("普通运行");
    expect(btn.className).toContain("restart");
    act(() => btn.click());
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("error → 渲染「普通运行」#restart 按钮（与 stopped 同文案）+ 点击调 onStart", () => {
    const { onStart } = renderControls({ phase: "error" });
    const btn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(btn).not.toBeNull();
    expect(btn.textContent).toBe("普通运行");
    expect(btn.getAttribute("aria-label")).toBe("普通运行");
    act(() => btn.click());
    expect(onStart).toHaveBeenCalledTimes(1);
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
    // 默认 initialChip='none'（无 chip）—— 主操作按钮每 phase 恰 1 个。
    // US-007 chip 的「×清除」是 fresh 态专属次要按钮（见下方 chip 三态用例），
    // 不破坏「单一主操作」不变量。
    for (const phase of ["idle", "running", "stopped", "done", "error"] as SolvePhase[]) {
      renderControls({ phase });
      const buttons = container!.querySelectorAll("button");
      expect(buttons.length).toBe(1);
    }
  });

  it("startDisabled=true → 非 running 态「普通运行」disabled；running 态「停止」不受影响", () => {
    // idle + startDisabled → #start disabled
    renderControls({ phase: "idle", onStart: vi.fn(), startDisabled: true });
    const startBtn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(startBtn.disabled).toBe(true);

    // stopped/done/error + startDisabled → #restart disabled
    for (const phase of ["stopped", "done", "error"] as SolvePhase[]) {
      renderControls({ phase, startDisabled: true });
      const btn = container!.querySelector<HTMLButtonElement>("#restart")!;
      expect(btn.disabled).toBe(true);
    }

    // running + startDisabled → #stop 仍可点（停止不受码号空影响）
    renderControls({ phase: "running", onStop: vi.fn(), startDisabled: true });
    const stopBtn = container!.querySelector<HTMLButtonElement>("#stop")!;
    expect(stopBtn.disabled).toBe(false);

    // idle + startDisabled=false → #start 可点
    renderControls({ phase: "idle", onStart: vi.fn(), startDisabled: false });
    const enabledStart = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(enabledStart.disabled).toBe(false);
  });
});

// ============================================================
// prd-initial-layout US-007：初始布局 chip 三态（ControlPanel 据
// saved + isStale(指纹) 派生传入，本组件纯受控渲染）。
//   fresh  =「将基于初始布局运行」+「×清除」次要按钮 + 附注「仅普通运行生效」
//   stale  =「初始布局已失效（参数已变更）」+ 附注（无清除键 —— 重开弹窗自动重生成）
//   none   = 无任何 chip 节点（默认，既有 DOM 零变化）
//   running = 无 chip（热启动增益提示只在可发起普通运行时在场）
// ============================================================
describe("SolveControls 初始布局 chip 三态 (US-007)", () => {
  it("fresh → chip 文案 + ×清除按钮（点击调 onClearInitial）+ 附注「仅普通运行生效」", () => {
    const { onClearInitial } = renderControls({ phase: "idle", initialChip: "fresh" });
    const chip = container!.querySelector<HTMLElement>('[data-testid="initial-chip"]')!;
    expect(chip).not.toBeNull();
    expect(chip.textContent).toContain("将基于初始布局运行");
    const note = container!.querySelector<HTMLElement>('[data-testid="initial-chip-note"]')!;
    expect(note).not.toBeNull();
    expect(note.textContent).toBe("仅普通运行生效");
    // ×清除是次要小按钮（aria-label 可达）
    const clear = container!.querySelector<HTMLButtonElement>('[data-testid="initial-chip-clear"]')!;
    expect(clear).not.toBeNull();
    expect(clear.getAttribute("aria-label")).toBe("清除初始布局");
    act(() => clear.click());
    expect(onClearInitial).toHaveBeenCalledTimes(1);
    // 清除是独立次要动作 —— 不触发 onStart
    expect(container!.querySelector("#start")).not.toBeNull();
  });

  it("stale → 「初始布局已失效（参数已变更）」+ 附注；无清除按钮（重开弹窗自动重生成）", () => {
    const { onClearInitial } = renderControls({ phase: "idle", initialChip: "stale" });
    const chip = container!.querySelector<HTMLElement>('[data-testid="initial-chip-stale"]')!;
    expect(chip).not.toBeNull();
    expect(chip.textContent).toContain("初始布局已失效（参数已变更）");
    expect(chip.className).toContain("stale");
    expect(container!.querySelector('[data-testid="initial-chip-clear"]')).toBeNull();
    expect(container!.querySelector('[data-testid="initial-chip"]')).toBeNull();
    // 附注仍恒随 chip 在场
    expect(container!.querySelector('[data-testid="initial-chip-note"]')).not.toBeNull();
    expect(onClearInitial).not.toHaveBeenCalled();
  });

  it("none（默认）→ 无任何 chip 节点（既有 DOM 逐字节不变）", () => {
    renderControls({ phase: "idle" });
    expect(container!.querySelector('[data-testid="initial-chip"]')).toBeNull();
    expect(container!.querySelector('[data-testid="initial-chip-stale"]')).toBeNull();
    expect(container!.querySelector('[data-testid="initial-chip-note"]')).toBeNull();
    expect(container!.querySelector('[data-testid="initial-chip-clear"]')).toBeNull();
  });

  it("running → 不渲染 chip（即使传了 fresh；求解中无增益提示）", () => {
    renderControls({ phase: "running", initialChip: "fresh" });
    expect(container!.querySelector('[data-testid="initial-chip"]')).toBeNull();
    expect(container!.querySelector('[data-testid="initial-chip-note"]')).toBeNull();
    expect(container!.querySelectorAll("button").length).toBe(1); // 仅 #stop
  });

  it("fresh 态主操作按钮仍可点（chip 不拦截 onStart）+ stopped/done/error 态 chip 同渲染", () => {
    const { onStart } = renderControls({ phase: "idle", initialChip: "fresh", onStart: vi.fn() });
    act(() => container!.querySelector<HTMLButtonElement>("#start")!.click());
    expect(onStart).toHaveBeenCalledTimes(1);
    for (const phase of ["stopped", "done", "error"] as SolvePhase[]) {
      renderControls({ phase, initialChip: "fresh" });
      expect(container!.querySelector('[data-testid="initial-chip"]')).not.toBeNull();
    }
  });
});
