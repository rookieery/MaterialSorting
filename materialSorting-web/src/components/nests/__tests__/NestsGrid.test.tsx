// US-005 NestsGrid 单测：
//   1) seeds=[] → 空容器（仅 #nests，无 .nest-card）
//   2) seeds 长度 N → 渲染 N 个 .nest-card；runRegistry 缺失对应 record → 跳过
//   3) 渲染顺序与 seeds 一致（base, base+1, ...）；key=seed 稳定
//   4) 重新渲染（seeds 不变）→ 不重复挂载（key=seed 稳定）
//   5) lastFrame 存在 → NestLabel 追加用布长度（% · 长度 X.XX cm，width_mm/10 两位小数）
//   6) 用时段（用时 N 秒）：运行中动态（同 tick create→render 恒 0 秒）；done 定格
//      finalElapsed 服务器终值；stopped（无 final）定格 endedAt-startedAt；合成 run
//      未传终值（差值 <1s）→ 整段省略

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { NestsGrid } from "../NestsGrid";
import { markRunDone, runRegistry } from "../../../store/runRegistry";

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

function renderGrid(seeds: number[]) {
  act(() => {
    root!.render(
      <StrictMode>
        <NestsGrid seeds={seeds} />
      </StrictMode>,
    );
  });
}

describe("NestsGrid (US-005)", () => {
  it("seeds=[] → 空容器，无 .nest-card", () => {
    renderGrid([]);
    const nests = container!.querySelector("#nests")!;
    expect(nests).toBeTruthy();
    expect(nests.querySelectorAll(".nest-card")).toHaveLength(0);
  });

  it("seeds 长度 N + registry 有对应 record → 渲染 N 个 .nest-card", () => {
    runRegistry.create(0);
    runRegistry.create(1);
    runRegistry.create(2);
    renderGrid([0, 1, 2]);
    const cards = container!.querySelectorAll(".nest-card");
    expect(cards).toHaveLength(3);
  });

  it("registry 缺失对应 record → 该 seed 不渲染（留 null）", () => {
    runRegistry.create(0);
    // 故意不 create(1)
    renderGrid([0, 1]);
    const cards = container!.querySelectorAll(".nest-card");
    expect(cards).toHaveLength(1);
  });

  it("渲染顺序与 seeds 数组一致（base, base+1, ...）", () => {
    // 用 manifest 区分各 card 的 seed（NestLabel 显示 seed N · …）
    const rec5 = runRegistry.create(5);
    const rec6 = runRegistry.create(6);
    const rec7 = runRegistry.create(7);
    rec5.manifest = { type: "manifest", gate_mm: 1980, total_area_mm2: 1, n_eroded: 0, pieces: [] };
    rec6.manifest = { type: "manifest", gate_mm: 1980, total_area_mm2: 1, n_eroded: 0, pieces: [] };
    rec7.manifest = { type: "manifest", gate_mm: 1980, total_area_mm2: 1, n_eroded: 0, pieces: [] };
    renderGrid([5, 6, 7]);
    const labels = Array.from(container!.querySelectorAll(".nest-label")).map((el) => el.textContent);
    expect(labels).toEqual([
      "seed 5 · 0 片 · 用时 0 秒",
      "seed 6 · 0 片 · 用时 0 秒",
      "seed 7 · 0 片 · 用时 0 秒",
    ]);
  });

  it("lastFrame 存在 → label 追加用布长度（宽度 mm → cm 2 位小数，版师 2026-08-28 口径）+ 运行中用时", () => {
    const rec = runRegistry.create(0);
    rec.manifest = { type: "manifest", gate_mm: 1980, total_area_mm2: 1, n_eroded: 0, pieces: [] };
    rec.lastFrame = {
      type: "frame", index: 0, elapsed: 1, phase: "Placing",
      density: 0.8754, density_sparrow: 0.9, width_mm: 11550, placed_items: [],
    };
    renderGrid([0]);
    const label = container!.querySelector(".nest-label")!.textContent;
    // 未 done → 动态用时段（同 tick create→render，performance.now 差 <1s → 0 秒）。
    expect(label).toBe("seed 0 · 87.54% · 长度 1155.00 cm · 用时 0 秒");
  });

  it("done + finalElapsed → 用时定格服务器终值（N 秒；不随 renderTick 增长）", () => {
    const rec = runRegistry.create(0);
    rec.manifest = { type: "manifest", gate_mm: 1980, total_area_mm2: 1, n_eroded: 0, pieces: [] };
    rec.lastFrame = {
      type: "frame", index: 3, elapsed: 91, phase: "Final",
      density: 0.8754, density_sparrow: 0.9, width_mm: 11550, placed_items: [],
    };
    rec.finalElapsed = 92;
    markRunDone(rec);
    renderGrid([0]);
    const label = container!.querySelector(".nest-label")!.textContent;
    expect(label).toBe("seed 0 · 87.54% · 长度 1155.00 cm · 用时 92 秒");
    // done 后再 bump（重新 render）→ 定格值不变（finalElapsed 优先于墙钟差）。
    rec.endedAt = performance.now() + 60000; // 即便墙钟差变大也不动定格值
    renderGrid([0]);
    expect(container!.querySelector(".nest-label")!.textContent).toBe(label);
  });

  it("stopped（done 无 final）→ 用时定格 endedAt-startedAt 墙钟差", () => {
    const rec = runRegistry.create(0);
    rec.manifest = { type: "manifest", gate_mm: 1980, total_area_mm2: 1, n_eroded: 0, pieces: [] };
    rec.lastFrame = {
      type: "frame", index: 1, elapsed: 60, phase: "Placing",
      density: 0.8, density_sparrow: 0.82, width_mm: 12000, placed_items: [],
    };
    rec.stopped = true;
    rec.startedAt = performance.now() - 65000;
    markRunDone(rec); // endedAt = now → 差 65s
    renderGrid([0]);
    const label = container!.querySelector(".nest-label")!.textContent;
    expect(label).toBe("seed 0 · 80.00% · 长度 1200.00 cm · 用时 65 秒");
  });

  it("合成 run 未传终值（done 且墙钟差 <1s）→ 用时段整体省略（旧格式零变化）", () => {
    const rec = runRegistry.create(0);
    rec.manifest = { type: "manifest", gate_mm: 1980, total_area_mm2: 1, n_eroded: 0, pieces: [] };
    rec.lastFrame = {
      type: "frame", index: 0, elapsed: 31, phase: "final",
      density: 0.8838, density_sparrow: 0.9, width_mm: 11000, placed_items: [],
    };
    markRunDone(rec); // 同 tick create→done，差值 <1s，finalElapsed=null
    renderGrid([0]);
    const label = container!.querySelector(".nest-label")!.textContent;
    expect(label).toBe("seed 0 · 88.38% · 长度 1100.00 cm");
  });

  it("重新渲染（seeds 不变）→ 不重复挂载（key=seed 稳定）", () => {
    runRegistry.create(0);
    runRegistry.create(1);
    renderGrid([0, 1]);
    expect(container!.querySelectorAll(".nest-card")).toHaveLength(2);

    // 重新 render 同样 seeds
    act(() => {
      root!.render(
        <StrictMode>
          <NestsGrid seeds={[0, 1]} />
        </StrictMode>,
      );
    });
    expect(container!.querySelectorAll(".nest-card")).toHaveLength(2);
  });

  it("seeds 变化（增加 / 减少）→ 卡片数量跟着变", () => {
    runRegistry.create(0);
    runRegistry.create(1);
    runRegistry.create(2);
    renderGrid([0, 1]);
    expect(container!.querySelectorAll(".nest-card")).toHaveLength(2);

    act(() => {
      root!.render(
        <StrictMode>
          <NestsGrid seeds={[0, 1, 2]} />
        </StrictMode>,
      );
    });
    expect(container!.querySelectorAll(".nest-card")).toHaveLength(3);

    act(() => {
      root!.render(
        <StrictMode>
          <NestsGrid seeds={[0]} />
        </StrictMode>,
      );
    });
    expect(container!.querySelectorAll(".nest-card")).toHaveLength(1);
  });
});
