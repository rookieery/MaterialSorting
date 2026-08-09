// US-003 NestSVG 单测：
//   1) manifest 到达 → 翻转组 transform（setAttribute，非 JSX）
//   2) 每个 piece 创建 polygon，fill / data-* 与旧 app.js 一致；初始 display:none
//   3) lastFrame 到达 + renderTick bump → placed polygon setAttribute points + display；
//      未 placed 的 display:none
//   4) viewBox 用历史最大 width（稳定锚）；React 只渲染空骨架

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StrictMode, type MutableRefObject } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { NestSVG } from "../NestSVG";
import { useAppStore } from "../../../store/appStore";
import { runRegistry, type RunRecord } from "../../../store/runRegistry";
import type { ManifestMsg, FrameMsg } from "../../../types/ws";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  runRegistry.clear();
  useAppStore.setState({ renderTick: 0 });
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

function makeManifest(): ManifestMsg {
  return {
    type: "manifest",
    gate_mm: 1980,
    total_area_mm2: 100000,
    n_eroded: 0,
    pieces: [
      {
        id: "p1",
        ptype: "Front",
        size: 30,
        color: "#ff0000",
        area_mm2: 12345,
        polygon: [[0, 0], [10, 0], [10, 10], [0, 10]],
      },
      {
        id: "p2",
        ptype: "Back",
        size: 32,
        color: "#00ff00",
        area_mm2: 23456,
        polygon: [[0, 0], [20, 0], [20, 20], [0, 20]],
      },
    ],
  };
}

function makeFrame(placedIds: string[], width = 800): FrameMsg {
  return {
    type: "frame",
    index: 0,
    elapsed: 0.5,
    phase: "exploring",
    density: 0.5,
    density_sparrow: 0.55,
    width_mm: width,
    placed_items: placedIds.map((id, i) => ({
      id,
      rotation: 0,
      translation: [i * 100, i * 50],
    })),
  };
}

function mountNestSVG(run: RunRecord): MutableRefObject<SVGSVGElement | null> {
  const ref: MutableRefObject<SVGSVGElement | null> = { current: null };
  function Probe() {
    return (
      <div ref={(el) => { ref.current = el?.querySelector("svg") ?? null; }}>
        <NestSVG run={run} />
      </div>
    );
  }
  act(() => {
    root!.render(
      <StrictMode>
        <Probe />
      </StrictMode>,
    );
  });
  return ref;
}

describe("NestSVG (US-003)", () => {
  it("React 只渲染空骨架（<svg>，无子节点）—— manifest 到达前", () => {
    const run = runRegistry.create(0);
    const ref = mountNestSVG(run);
    const svg = ref.current;
    expect(svg).not.toBeNull();
    expect(svg!.childNodes.length).toBe(0);
  });

  it("manifest 到达（mount 时已就绪）→ 翻转组 / bg / fab / polygon 全部 imperative 建好", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const ref = mountNestSVG(run);

    const svg = ref.current!;
    expect(svg.childNodes.length).toBe(3);

    const bg = svg.childNodes[0] as SVGRectElement;
    const fab = svg.childNodes[1] as SVGRectElement;
    const g = svg.childNodes[2] as SVGGElement;

    expect(bg.tagName).toBe("rect");
    expect(bg.getAttribute("fill")).toBe("#eef0f3");

    expect(fab.tagName).toBe("rect");
    expect(fab.getAttribute("fill")).toBe("#fff");
    expect(fab.getAttribute("fill-opacity")).toBe("0.55");
    expect(fab.getAttribute("stroke")).toBe("#8a8a8a");
    expect(fab.getAttribute("stroke-dasharray")).toBe("8 5");
    expect(fab.getAttribute("stroke-width")).toBe("1.5");

    expect(g.tagName).toBe("g");
    expect(g.getAttribute("transform")).toBe("translate(0 1980) scale(1 -1)");

    expect(g.childNodes.length).toBe(2);
    const poly1 = g.childNodes[0] as SVGPolygonElement;
    const poly2 = g.childNodes[1] as SVGPolygonElement;

    expect(poly1.tagName).toBe("polygon");
    expect(poly1.getAttribute("fill")).toBe("#ff0000");
    expect(poly1.getAttribute("fill-opacity")).toBe("0.55");
    expect(poly1.getAttribute("stroke")).toBe("#ff0000");
    expect(poly1.getAttribute("stroke-width")).toBe("1.2");
    expect(poly1.dataset.ptype).toBe("Front");
    expect(poly1.dataset.size).toBe("30");
    expect(poly1.dataset.area).toBe("12345");
    expect(poly1.style.display).toBe("none");

    expect(poly2.dataset.ptype).toBe("Back");
    expect(poly2.dataset.size).toBe("32");
  });

  it("renderTick 多次 bump 不重建 DOM（flipRef 幂等保护）", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const ref = mountNestSVG(run);
    const svgBefore = ref.current!;
    const polyCountBefore = svgBefore.querySelectorAll("polygon").length;

    act(() => {
      useAppStore.getState().bumpRenderTick();
      useAppStore.getState().bumpRenderTick();
    });

    const svgAfter = ref.current!;
    expect(svgAfter.querySelectorAll("polygon").length).toBe(polyCountBefore);
    expect(svgAfter.childNodes.length).toBe(3);
  });

  it("lastFrame 到达 + tick → placed polygon 写 points + display；未 placed 隐藏", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const ref = mountNestSVG(run);
    const svg = ref.current!;
    const g = svg.childNodes[2] as SVGGElement;
    const poly1 = g.childNodes[0] as SVGPolygonElement;
    const poly2 = g.childNodes[1] as SVGPolygonElement;

    const frame = makeFrame(["p1"], 800);
    run.frames.push(frame);
    run.lastFrame = frame;
    run.viewBoxMaxW = 900;

    act(() => useAppStore.getState().bumpRenderTick());

    expect(svg.getAttribute("viewBox")).toBe("0 0 900 1980");
    expect(svg.getAttribute("preserveAspectRatio")).toBe("xMinYMid meet");

    const bg = svg.childNodes[0] as SVGRectElement;
    const fab = svg.childNodes[1] as SVGRectElement;
    expect(bg.getAttribute("width")).toBe("900");
    expect(bg.getAttribute("height")).toBe("1980");
    expect(fab.getAttribute("width")).toBe("800");
    expect(fab.getAttribute("height")).toBe("1980");

    expect(poly1.style.display).toBe("");
    expect(poly1.getAttribute("points")).not.toBe("");
    expect(poly2.style.display).toBe("none");
    expect(poly2.getAttribute("points")).toBeNull();
  });

  it("pointsStr 写入的 points 字符串与 lib/geometry 直算一致（旋转 90°）", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const ref = mountNestSVG(run);
    const g = ref.current!.childNodes[2] as SVGGElement;
    const poly1 = g.childNodes[0] as SVGPolygonElement;

    const frame: FrameMsg = {
      type: "frame",
      index: 0,
      elapsed: 0.5,
      phase: "exploring",
      density: 0.5,
      density_sparrow: 0.5,
      width_mm: 1000,
      placed_items: [{ id: "p1", rotation: 90, translation: [50, 70] }],
    };
    run.frames.push(frame);
    run.lastFrame = frame;
    act(() => useAppStore.getState().bumpRenderTick());

    // rotation 90° + translation (50, 70)
    // poly1.polygon = [[0,0],[10,0],[10,10],[0,10]]
    // (0,0) → (0,0)+(50,70) = (50,70)
    // (10,0) → (0,10)+(50,70) = (50,80)
    // (10,10) → (-10,10)+(50,70) = (40,80)
    // (0,10) → (-10,0)+(50,70) = (40,70)
    expect(poly1.getAttribute("points")).toBe("50,70 50,80 40,80 40,70");
  });

  it("未 placed → placed 切换：display 跟着翻", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const ref = mountNestSVG(run);
    const g = ref.current!.childNodes[2] as SVGGElement;
    const poly1 = g.childNodes[0] as SVGPolygonElement;
    const poly2 = g.childNodes[1] as SVGPolygonElement;

    const f1 = makeFrame(["p1"], 800);
    run.frames.push(f1);
    run.lastFrame = f1;
    act(() => useAppStore.getState().bumpRenderTick());
    expect(poly1.style.display).toBe("");
    expect(poly2.style.display).toBe("none");

    const f2 = makeFrame(["p2"], 850);
    run.frames.push(f2);
    run.lastFrame = f2;
    act(() => useAppStore.getState().bumpRenderTick());
    expect(poly1.style.display).toBe("none");
    expect(poly2.style.display).toBe("");
  });

  it("manifest 到达但无 frame：polygon 仍 display:none，viewBox 不写", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const ref = mountNestSVG(run);
    const svg = ref.current!;
    const g = svg.childNodes[2] as SVGGElement;
    const poly1 = g.childNodes[0] as SVGPolygonElement;

    expect(poly1.style.display).toBe("none");
    expect(svg.getAttribute("viewBox")).toBeNull();
  });

  it("后挂载（manifest 在 mount 之后到达）也能建 DOM（订阅 renderTick 生效）", () => {
    const run = runRegistry.create(0);
    const ref = mountNestSVG(run);
    expect(ref.current!.childNodes.length).toBe(0);

    run.manifest = makeManifest();
    act(() => useAppStore.getState().bumpRenderTick());

    const svg = ref.current!;
    expect(svg.childNodes.length).toBe(3);
    expect((svg.childNodes[2] as SVGGElement).getAttribute("transform")).toBe(
      "translate(0 1980) scale(1 -1)",
    );
    expect(svg.querySelectorAll("polygon").length).toBe(2);
  });
});
