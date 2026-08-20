// SizeLegend（尺码 → 颜色图例，2026-08-20 配色换键为尺码后新增）单测：
//   1. 条目 = manifest.pieces 的 size→color 去重（跨片型同码同色 → 每码一条），数值序；
//   2. manifest 缺席（未求解）→ 不渲染；
//   3. 全部 size 缺席（异常数据）→ 不渲染。

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { SizeLegend } from "../SizeLegend";
import { runRegistry, type RunRecord } from "../../../store/runRegistry";
import type { ManifestMsg } from "../../../types/ws";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  runRegistry.clear();
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
  runRegistry.clear();
});

function makeRun(manifest: ManifestMsg | null): RunRecord {
  const run = runRegistry.create(1);
  run.manifest = manifest;
  return run;
}

function mountSizeLegend(run: RunRecord): HTMLDivElement | null {
  act(() => {
    root!.render(
      <StrictMode>
        <SizeLegend run={run} />
      </StrictMode>,
    );
  });
  return container?.querySelector(".size-legend") ?? null;
}

describe("SizeLegend（尺码图例）", () => {
  it("跨片型同码去重 → 每码一条，数值序渲染（色块 + 码号）", () => {
    const manifest: ManifestMsg = {
      type: "manifest",
      gate_mm: 1980,
      gate_nest_mm: 1910,
      total_area_mm2: 100000,
      n_eroded: 0,
      pieces: [
        // g01_36 先出现：36 应排在 28 之后（数值序，非出现序）
        { id: "g01_36", label: "g01", size: 36, color: "#c5b0d5", area_mm2: 1,
          polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] },
        { id: "g02_28", label: "g02", size: 28, color: "#1f77b4", area_mm2: 1,
          polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] },
        // g03_28 同码不同片型 → 同色（后端保证），图例只保留一条
        { id: "g03_28", label: "g03", size: 28, color: "#1f77b4", area_mm2: 1,
          polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] },
      ],
    };
    const el = mountSizeLegend(makeRun(manifest));
    expect(el).not.toBeNull();
    const labels = [...el!.querySelectorAll(".size-legend-label")].map((n) => n.textContent);
    expect(labels).toEqual(["28", "36"]);
    const swatches = [...el!.querySelectorAll(".size-legend-swatch")] as HTMLElement[];
    // jsdom 会把 hex 规范化成 rgb()，断言用规范化后的值
    expect(swatches[0].style.background).toBe("rgb(31, 119, 180)");   // #1f77b4
    expect(swatches[1].style.background).toBe("rgb(197, 176, 213)");  // #c5b0d5
  });

  it("manifest 缺席（未求解）→ 不渲染", () => {
    expect(mountSizeLegend(makeRun(null))).toBeNull();
  });

  it("全部 size 缺席（异常数据）→ 不渲染", () => {
    const manifest: ManifestMsg = {
      type: "manifest",
      gate_mm: 1980,
      total_area_mm2: 100000,
      n_eroded: 0,
      pieces: [
        { id: "p1", label: "g01", size: null as unknown as number, color: "#bbbbbb",
          area_mm2: 1, polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] },
      ],
    };
    expect(mountSizeLegend(makeRun(manifest))).toBeNull();
  });
});
