// US-007 ExportButtons integration tests:
//   AC#6 disabled conditions:
//     - 无 lastFrame run（未求解 / 求解未完成）→ disabled
//     - solving=true → disabled
//     - exporting=true → disabled（双按钮同步禁用）
//   AC#6 enabled: 至少一个 run 有 lastFrame + 非 solving + 非 exporting
//   onExport(fmt) 回调：PNG / DXF 按钮分别触发对应 fmt
//   renderTick 订阅：lastFrame 到达后（bumpRenderTick）→ 按钮启用

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { ExportButtons } from "../ExportButtons";
import { useAppStore } from "../../../store/appStore";
import { runRegistry, type RunRecord } from "../../../store/runRegistry";
import type { FrameMsg, ManifestMsg } from "../../../types/ws";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  runRegistry.clear();
  useAppStore.setState({ renderTick: 0, seekTime: -1 });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) {
    const r = root;
    act(() => { r.unmount(); });
    root = null;
  }
  container?.remove();
  container = null;
  runRegistry.clear();
});

function renderBtns(props: Partial<React.ComponentProps<typeof ExportButtons>> = {}) {
  const onExport = props.onExport ?? vi.fn();
  act(() => {
    root!.render(
      <StrictMode>
        <ExportButtons
          solving={props.solving ?? false}
          exporting={props.exporting ?? false}
          onExport={onExport}
        />
      </StrictMode>,
    );
  });
  return { onExport };
}

function makeManifest(gate = 1980): ManifestMsg {
  return { type: "manifest", gate_mm: gate, total_area_mm2: 100000, n_eroded: 0, pieces: [] };
}

function makeRunWithFrame(seed: number): RunRecord {
  const rec = runRegistry.create(seed);
  rec.manifest = makeManifest();
  const f: FrameMsg = {
    type: "frame", index: 0, elapsed: 1, phase: "final",
    density: 0.5, density_sparrow: 0.5, width_mm: 1000, placed_items: [],
  };
  rec.frames.push(f);
  rec.lastFrame = f;
  rec.finalDensity = 0.5;
  rec.done = true;
  return rec;
}

describe("ExportButtons (US-007 AC#6)", () => {
  it("renders .export-group container with field-label and 2 buttons", () => {
    renderBtns();
    expect(container!.querySelector(".export-group")).not.toBeNull();
    expect(container!.querySelector(".export-group .field-label")!.textContent).toBe("导出最优方案");
    expect(container!.querySelectorAll(".export-btns button.export").length).toBe(2);
  });

  it("button ids preserved: export_png / export_dxf (legacy CSS selector)", () => {
    renderBtns();
    expect(container!.querySelector("#export_png")).not.toBeNull();
    expect(container!.querySelector("#export_dxf")).not.toBeNull();
  });

  it("button labels: 导出 PNG / 导出 DXF", () => {
    renderBtns();
    expect(container!.querySelector("#export_png")!.textContent).toBe("导出 PNG");
    expect(container!.querySelector("#export_dxf")!.textContent).toBe("导出 DXF");
  });

  it("hint text 默认导出利用率最高的 seed 的最终方案", () => {
    renderBtns();
    const hint = container!.querySelector(".export-group .dim.small")!.textContent;
    expect(hint).toContain("默认导出利用率最高的 seed 的最终方案");
  });

  it("AC#6 no lastFrame run -> both buttons disabled", () => {
    renderBtns();
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(true);
    expect(container!.querySelector<HTMLInputElement>("#export_dxf")!.disabled).toBe(true);
  });

  it("AC#6 solving=true -> both disabled (even with lastFrame)", () => {
    makeRunWithFrame(0);
    renderBtns({ solving: true });
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(true);
    expect(container!.querySelector<HTMLInputElement>("#export_dxf")!.disabled).toBe(true);
  });

  it("AC#6 exporting=true -> both disabled (防双击同步禁用)", () => {
    makeRunWithFrame(0);
    renderBtns({ exporting: true });
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(true);
    expect(container!.querySelector<HTMLInputElement>("#export_dxf")!.disabled).toBe(true);
  });

  it("AC#6 has lastFrame + not solving + not exporting -> both enabled", () => {
    makeRunWithFrame(0);
    renderBtns();
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(false);
    expect(container!.querySelector<HTMLInputElement>("#export_dxf")!.disabled).toBe(false);
  });

  it("click PNG -> onExport(png)", () => {
    makeRunWithFrame(0);
    const onExport = vi.fn();
    renderBtns({ onExport });
    act(() => container!.querySelector<HTMLButtonElement>("#export_png")!.click());
    expect(onExport).toHaveBeenCalledTimes(1);
    expect(onExport).toHaveBeenCalledWith("png");
  });

  it("click DXF -> onExport(dxf)", () => {
    makeRunWithFrame(0);
    const onExport = vi.fn();
    renderBtns({ onExport });
    act(() => container!.querySelector<HTMLButtonElement>("#export_dxf")!.click());
    expect(onExport).toHaveBeenCalledTimes(1);
    expect(onExport).toHaveBeenCalledWith("dxf");
  });

  it("renderTick subscription: lastFrame arrived via bump -> buttons enabled", () => {
    // 先渲染（无 lastFrame，按钮 disabled）
    renderBtns();
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(true);
    // 推入 lastFrame + bump renderTick（模拟 useRafThrottle + useSolveRun 的组合）
    makeRunWithFrame(0);
    act(() => useAppStore.getState().bumpRenderTick());
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(false);
    expect(container!.querySelector<HTMLInputElement>("#export_dxf")!.disabled).toBe(false);
  });

  it("runRegistry.clear() + bump -> buttons disabled again（新 start 清空）", () => {
    makeRunWithFrame(0);
    renderBtns();
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(false);
    act(() => {
      runRegistry.clear();
      useAppStore.getState().bumpRenderTick();
    });
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(true);
  });

  it("multi-run with lastFrame -> enabled（bestRun 留给 useExport 选）", () => {
    makeRunWithFrame(0);
    makeRunWithFrame(1);
    makeRunWithFrame(2);
    renderBtns();
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(false);
  });

  it("run without lastFrame (frames 空数组) -> 视为无 lastFrame -> disabled", () => {
    const rec = runRegistry.create(0);
    rec.manifest = makeManifest();
    rec.done = false; // 求解中，frames 空
    renderBtns();
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(true);
  });
});
