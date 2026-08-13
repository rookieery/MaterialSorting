// US-007 ExportButtons integration tests（下拉框 + 单导出按钮 版）:
//   结构：.export-btns 下为 1 个 select.export-fmt + 1 个 button.export
//   AC#6 disabled 条件（只对 button；select 始终可选）:
//     - 无 lastFrame run（未求解 / 求解未完成）→ button disabled
//     - solving=true → button disabled
//     - exporting=true → button disabled（防连击）
//   AC#6 enabled: 至少一个 run 有 lastFrame + 非 solving + 非 exporting
//   格式选择：select 默认 DXF；切 PNG 后点导出 → onExport('png')；默认点导出 → onExport('dxf')
//   renderTick 订阅：lastFrame 到达后（bumpRenderTick）→ button 启用

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
          partial={props.partial}
        />
      </StrictMode>,
    );
  });
  return { onExport };
}

/** 模拟用户切换下拉框：设 value + 派发 change（React onChange 监听冒泡 change）。 */
function selectFmt(value: string): void {
  const select = container!.querySelector<HTMLSelectElement>(".export-btns select")!;
  act(() => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function exportButton(): HTMLButtonElement {
  return container!.querySelector<HTMLButtonElement>(".export-btns button.export")!;
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

describe("ExportButtons (US-007 下拉框 + 单按钮)", () => {
  it("renders .export-group container with field-label, 1 select and 1 button", () => {
    renderBtns();
    expect(container!.querySelector(".export-group")).not.toBeNull();
    expect(container!.querySelector(".export-group .field-label")!.textContent).toBe("导出最优方案");
    expect(container!.querySelectorAll(".export-btns select.export-fmt").length).toBe(1);
    expect(container!.querySelectorAll(".export-btns button.export").length).toBe(1);
  });

  it("select has 2 options (DXF/PNG) and defaults to DXF", () => {
    renderBtns();
    const select = container!.querySelector<HTMLSelectElement>(".export-btns select")!;
    const opts = Array.from(select.options).map((o) => o.value);
    expect(opts).toEqual(["dxf", "png"]);
    expect(select.value).toBe("dxf");
  });

  it("button label is 导出", () => {
    renderBtns();
    expect(exportButton().textContent).toBe("导出");
  });

  it("hint text 默认导出利用率最高的 seed 的最终方案", () => {
    renderBtns();
    const hint = container!.querySelector(".export-group .dim.small")!.textContent;
    expect(hint).toContain("默认导出利用率最高的 seed 的最终方案");
  });

  it("US-028 partial=true 显示中间方案警示文案", () => {
    renderBtns({ partial: true });
    const hint = container!.querySelector(".export-group .dim.small.warn")!.textContent;
    expect(hint).toContain("导出的是停止 / 出错时刻的中间方案");
  });

  it("AC#6 no lastFrame run -> button disabled（select 仍可选）", () => {
    renderBtns();
    expect(exportButton().disabled).toBe(true);
    expect(container!.querySelector<HTMLSelectElement>(".export-btns select")!.disabled).toBe(false);
  });

  it("AC#6 solving=true -> button disabled (even with lastFrame)", () => {
    makeRunWithFrame(0);
    renderBtns({ solving: true });
    expect(exportButton().disabled).toBe(true);
  });

  it("AC#6 exporting=true -> button disabled (防连击)", () => {
    makeRunWithFrame(0);
    renderBtns({ exporting: true });
    expect(exportButton().disabled).toBe(true);
  });

  it("AC#6 has lastFrame + not solving + not exporting -> button enabled", () => {
    makeRunWithFrame(0);
    renderBtns();
    expect(exportButton().disabled).toBe(false);
  });

  it("click 导出 (默认 DXF) -> onExport(dxf)", () => {
    makeRunWithFrame(0);
    const onExport = vi.fn();
    renderBtns({ onExport });
    act(() => exportButton().click());
    expect(onExport).toHaveBeenCalledTimes(1);
    expect(onExport).toHaveBeenCalledWith("dxf");
  });

  it("switch select to PNG then click -> onExport(png)", () => {
    makeRunWithFrame(0);
    const onExport = vi.fn();
    renderBtns({ onExport });
    selectFmt("png");
    act(() => exportButton().click());
    expect(onExport).toHaveBeenCalledTimes(1);
    expect(onExport).toHaveBeenCalledWith("png");
  });

  it("disabled 时点导出按钮不触发 onExport", () => {
    renderBtns(); // 无 lastFrame → disabled
    const onExport = vi.fn();
    renderBtns({ onExport }); // 仍无 lastFrame
    act(() => exportButton().click());
    expect(onExport).not.toHaveBeenCalled();
  });

  it("renderTick subscription: lastFrame arrived via bump -> button enabled", () => {
    // 先渲染（无 lastFrame，按钮 disabled）
    renderBtns();
    expect(exportButton().disabled).toBe(true);
    // 推入 lastFrame + bump renderTick（模拟 useRafThrottle + useSolveRun 的组合）
    makeRunWithFrame(0);
    act(() => useAppStore.getState().bumpRenderTick());
    expect(exportButton().disabled).toBe(false);
  });

  it("runRegistry.clear() + bump -> button disabled again（新 start 清空）", () => {
    makeRunWithFrame(0);
    renderBtns();
    expect(exportButton().disabled).toBe(false);
    act(() => {
      runRegistry.clear();
      useAppStore.getState().bumpRenderTick();
    });
    expect(exportButton().disabled).toBe(true);
  });

  it("multi-run with lastFrame -> enabled（bestRun 留给 useExport 选）", () => {
    makeRunWithFrame(0);
    makeRunWithFrame(1);
    makeRunWithFrame(2);
    renderBtns();
    expect(exportButton().disabled).toBe(false);
  });

  it("run without lastFrame (frames 空数组) -> 视为无 lastFrame -> disabled", () => {
    const rec = runRegistry.create(0);
    rec.manifest = makeManifest();
    rec.done = false; // 求解中，frames 空
    renderBtns();
    expect(exportButton().disabled).toBe(true);
  });
});
