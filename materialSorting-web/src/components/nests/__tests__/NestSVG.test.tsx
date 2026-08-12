// US-003 NestSVG 单测：
//   1) manifest 到达 → 翻转组 transform（setAttribute，非 JSX）
//   2) 每个 piece 创建 polygon，fill / data-* 与旧 vanilla 实现 一致；初始 display:none
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

// ============================================================
// US-024 5 层渲染（毛版 polygon + 净版 net_polygon + 内部线 internal_lines +
// 刺口 notches + 布纹线 grain_line）。AC#8：≥5 层渲染断言。
// - manifest 含 net → 渲染 net polygon 节点；不含则不渲染
// - dashed style 正确（net 6 3 / grain 5 3）
// - 5 层节点数（每片 1 毛版 + 1 净版 + N 内部 + M 刺口 + 1 布纹）
// - frame 切换时 5 层 setAttribute 都更新（不重建 DOM）
// - 未 placed 的 5 层都 display:none
// ============================================================

/** 构造含全 5 层的 manifest（US-024 测试用）。 */
function makeManifest5Layers(): ManifestMsg {
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
        polygon: [
          [0, 0], [10, 0], [10, 10], [0, 10],
        ],
        net_polygon: [
          [1, 1], [9, 1], [9, 9], [1, 9],
        ],
        internal_lines: [
          [[2, 2], [8, 8]],
          [[2, 8], [8, 2]],
        ],
        notches: [
          [5, 0, 0, -1],
          [0, 5, -1, 0],
        ],
        grain_line: [3, 5, 7, 5],
      },
      // p2 仅毛版 polygon（验证无 5 层字段时不渲染额外节点）
      {
        id: "p2",
        ptype: "Back",
        size: 32,
        color: "#00ff00",
        area_mm2: 23456,
        polygon: [
          [0, 0], [20, 0], [20, 20], [0, 20],
        ],
      },
    ],
  };
}

describe("NestSVG US-024 (5 层渲染)", () => {
  it("manifest 含 net_polygon → 渲染 net polygon 节点（绿 dashed）；不含则不渲染", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest5Layers();
    const ref = mountNestSVG(run);
    const svg = ref.current!;
    const g = svg.childNodes[2] as SVGGElement;

    // p1（含 5 层）的子节点：1 毛版 + 1 net + 2 internal + 2 notch + 1 grain = 7
    // p2（仅 polygon）的子节点：1 毛版 = 1
    // 但 g 的 childNodes 是扁平的全部节点。改用 querySelectorAll 计数。
    const allPolygons = g.querySelectorAll("polygon");
    // 毛版 2 个 + net 1 个（p2 无 net） = 3
    expect(allPolygons.length).toBe(3);

    // net polygon 配色与 dashed style（与 PiecePreviewSVG LAYER5_COLORS.NET 一致）
    const netPoly = Array.from(allPolygons).find(
      (p) => p.getAttribute("stroke") === "#33cc33",
    ) as SVGPolygonElement | undefined;
    expect(netPoly).toBeDefined();
    expect(netPoly!.getAttribute("fill")).toBe("none");
    expect(netPoly!.getAttribute("stroke-dasharray")).toBe("6 3");
    expect(netPoly!.getAttribute("stroke-linejoin")).toBe("round");
    expect(netPoly!.style.display).toBe("none"); // 初始未 placed
    expect(netPoly!.style.pointerEvents).toBe("none");
  });

  it("manifest 含 internal_lines → 渲染对应数量的橙色 polyline", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest5Layers();
    const ref = mountNestSVG(run);
    const g = ref.current!.childNodes[2] as SVGGElement;
    const polylines = Array.from(g.querySelectorAll("polyline"));
    // p1 有 2 条 internal_lines → 2 polyline；p2 无 → 0
    expect(polylines.length).toBe(2);
    for (const pl of polylines) {
      expect(pl.getAttribute("stroke")).toBe("#ff8c1a");
      expect(pl.getAttribute("fill")).toBe("none");
      expect(pl.getAttribute("stroke-linejoin")).toBe("round");
      expect(pl.getAttribute("stroke-linecap")).toBe("round");
      expect(pl.style.display).toBe("none"); // 初始未 placed
      expect(pl.style.pointerEvents).toBe("none");
    }
  });

  it("manifest 含 notches → 渲染对应数量的黄色 line 短线段", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest5Layers();
    const ref = mountNestSVG(run);
    const g = ref.current!.childNodes[2] as SVGGElement;
    // 选择 g 下所有 line —— SVGLineElement tagName === 'line'
    const lines = Array.from(g.querySelectorAll("line"));
    // p1 有 2 个 notches → 2 notch line；1 个 grain → 1 grain line；合计 3
    expect(lines.length).toBe(3);
    const notchLines = lines.filter((l) => l.getAttribute("stroke") === "#ffd700");
    expect(notchLines.length).toBe(2);
    for (const nl of notchLines) {
      expect(nl.getAttribute("stroke-width")).toBe("1.4");
      expect(nl.getAttribute("stroke-linecap")).toBe("round");
      expect(nl.style.display).toBe("none");
      expect(nl.style.pointerEvents).toBe("none");
    }
  });

  it("manifest 含 grain_line → 渲染红 dashed line；不含则不渲染", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest5Layers();
    const ref = mountNestSVG(run);
    const g = ref.current!.childNodes[2] as SVGGElement;
    const lines = Array.from(g.querySelectorAll("line"));
    const grainLines = lines.filter((l) => l.getAttribute("stroke") === "#e53e3e");
    // p1 有 grain → 1；p2 无 → 0
    expect(grainLines.length).toBe(1);
    const gl = grainLines[0];
    expect(gl.getAttribute("stroke-dasharray")).toBe("5 3");
    expect(gl.getAttribute("stroke-width")).toBe("1.2");
    expect(gl.style.display).toBe("none");
    expect(gl.style.pointerEvents).toBe("none");
  });

  it("5 层节点数：每片按数据条数渲染（p1=1+1+2+2+1=7，p2=1+0+0+0+0=1）", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest5Layers();
    const ref = mountNestSVG(run);
    const g = ref.current!.childNodes[2] as SVGGElement;
    // g.childNodes 包含所有裁片的所有层节点（毛版+net+internal+notch+grain）
    // p1: 1 polygon(rough) + 1 polygon(net) + 2 polyline(internal) + 2 line(notch) + 1 line(grain) = 7
    // p2: 1 polygon(rough) = 1
    // 共 8 个子节点（不包含 g 自己）
    expect(g.childNodes.length).toBe(8);
  });

  it("frame 切换：5 层 setAttribute 都更新（points / x1y1x2y2 / display）；不重建 DOM", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest5Layers();
    const ref = mountNestSVG(run);
    const g = ref.current!.childNodes[2] as SVGGElement;

    const polyNodesBefore = g.querySelectorAll("polygon").length;
    const polylineNodesBefore = g.querySelectorAll("polyline").length;
    const lineNodesBefore = g.querySelectorAll("line").length;

    // 第 1 帧：仅 p1 placed（rotation 0、translation 0,0）
    const f1: FrameMsg = {
      type: "frame",
      index: 0,
      elapsed: 0.1,
      phase: "exploring",
      density: 0.4,
      density_sparrow: 0.45,
      width_mm: 800,
      placed_items: [{ id: "p1", rotation: 0, translation: [0, 0] }],
    };
    run.frames.push(f1);
    run.lastFrame = f1;
    act(() => useAppStore.getState().bumpRenderTick());

    // 节点数不变（不重建 DOM）
    expect(g.querySelectorAll("polygon").length).toBe(polyNodesBefore);
    expect(g.querySelectorAll("polyline").length).toBe(polylineNodesBefore);
    expect(g.querySelectorAll("line").length).toBe(lineNodesBefore);

    // p1 毛版 polygon 写了 points 且 display=''
    const roughP1 = g.childNodes[0] as SVGPolygonElement; // p1 毛版（首先 append）
    expect(roughP1.style.display).toBe("");
    expect(roughP1.getAttribute("points")).not.toBe("");

    // p1 net polygon 写了 points 且 display=''
    const netP1 = g.childNodes[1] as SVGPolygonElement;
    expect(netP1.style.display).toBe("");
    expect(netP1.getAttribute("points")).not.toBe("");
    // rotation=0, translation=0,0 → points = 原始 net 坐标 r2
    // net_polygon = [[1,1],[9,1],[9,9],[1,9]] → "1,1 9,1 9,9 1,9"
    expect(netP1.getAttribute("points")).toBe("1,1 9,1 9,9 1,9");

    // p1 internal polyline（2 条）写了 points
    const internal1 = g.childNodes[2] as SVGPolylineElement;
    const internal2 = g.childNodes[3] as SVGPolylineElement;
    expect(internal1.style.display).toBe("");
    expect(internal1.getAttribute("points")).toBe("2,2 8,8");
    expect(internal2.style.display).toBe("");
    expect(internal2.getAttribute("points")).toBe("2,8 8,2");

    // p1 notch line（2 条）写了 x1/y1/x2/y2；沿法线 ±4 (NOTCH_LEN_MM/2=4)
    // notch[0] = (5, 0, 0, -1) → 端点 (5, 0-(-1)*4=4) 与 (5, 0+(-1)*4=-4)
    const notch1 = g.childNodes[4] as SVGLineElement;
    const notch2 = g.childNodes[5] as SVGLineElement;
    expect(notch1.style.display).toBe("");
    expect(notch1.getAttribute("x1")).toBe("5");
    expect(notch1.getAttribute("y1")).toBe("4");
    expect(notch1.getAttribute("x2")).toBe("5");
    expect(notch1.getAttribute("y2")).toBe("-4");
    // notch[1] = (0, 5, -1, 0) → 端点 (0-(-1)*4=4, 5) 与 (0+(-1)*4=-4, 5)
    expect(notch2.getAttribute("x1")).toBe("4");
    expect(notch2.getAttribute("y1")).toBe("5");
    expect(notch2.getAttribute("x2")).toBe("-4");
    expect(notch2.getAttribute("y2")).toBe("5");

    // p1 grain line 写了 x1/y1/x2/y2
    // grain_line = [3, 5, 7, 5]，rotation=0, tr=0,0 → 端点不变
    const grain = g.childNodes[6] as SVGLineElement;
    expect(grain.style.display).toBe("");
    expect(grain.getAttribute("x1")).toBe("3");
    expect(grain.getAttribute("y1")).toBe("5");
    expect(grain.getAttribute("x2")).toBe("7");
    expect(grain.getAttribute("y2")).toBe("5");

    // p2 毛版仍 display='none'（未 placed）
    const roughP2 = g.childNodes[7] as SVGPolygonElement;
    expect(roughP2.style.display).toBe("none");
  });

  it("frame 切换：未 placed 的全部 5 层都 display='none'", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest5Layers();
    const ref = mountNestSVG(run);
    const g = ref.current!.childNodes[2] as SVGGElement;

    // 仅 p2 placed（p1 未 placed）
    const f1: FrameMsg = {
      type: "frame",
      index: 0,
      elapsed: 0.1,
      phase: "exploring",
      density: 0.4,
      density_sparrow: 0.45,
      width_mm: 800,
      placed_items: [{ id: "p2", rotation: 0, translation: [0, 0] }],
    };
    run.frames.push(f1);
    run.lastFrame = f1;
    act(() => useAppStore.getState().bumpRenderTick());

    // p1 所有 7 个节点都 display='none'
    for (let i = 0; i < 7; i++) {
      const node = g.childNodes[i] as Element;
      expect((node as HTMLElement & { style: CSSStyleDeclaration }).style.display).toBe("none");
    }
    // p2 唯一节点（毛版 polygon）display=''
    const roughP2 = g.childNodes[7] as SVGPolygonElement;
    expect(roughP2.style.display).toBe("");
  });

  it("frame 切换：rotation≠0 + translation≠0 时 5 层都正确变换", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest5Layers();
    const ref = mountNestSVG(run);
    const g = ref.current!.childNodes[2] as SVGGElement;

    // rotation 90° + translation (50, 70)
    const f1: FrameMsg = {
      type: "frame",
      index: 0,
      elapsed: 0.1,
      phase: "exploring",
      density: 0.4,
      density_sparrow: 0.45,
      width_mm: 1000,
      placed_items: [{ id: "p1", rotation: 90, translation: [50, 70] }],
    };
    run.frames.push(f1);
    run.lastFrame = f1;
    act(() => useAppStore.getState().bumpRenderTick());

    // 毛版 polygon 旋转 90° + 平移 (50, 70)（与 lib/geometry pointsStr 一致）
    const roughP1 = g.childNodes[0] as SVGPolygonElement;
    // (0,0)→(0,0)+(50,70)=(50,70); (10,0)→(0,10)+(50,70)=(50,80);
    // (10,10)→(-10,10)+(50,70)=(40,80); (0,10)→(-10,0)+(50,70)=(40,70)
    expect(roughP1.getAttribute("points")).toBe("50,70 50,80 40,80 40,70");

    // net polygon = [[1,1],[9,1],[9,9],[1,9]] 旋转 90° + (50,70)
    // (1,1)→(-1,1)+(50,70)=(49,71); (9,1)→(-1,9)+(50,70)=(49,79);
    // (9,9)→(-9,9)+(50,70)=(41,79); (1,9)→(-9,1)+(50,70)=(41,71)
    const netP1 = g.childNodes[1] as SVGPolygonElement;
    expect(netP1.getAttribute("points")).toBe("49,71 49,79 41,79 41,71");

    // grain line [3,5,7,5] 旋转 90° + (50,70)
    // (3,5)→(-5,3)+(50,70)=(45,73); (7,5)→(-5,7)+(50,70)=(45,77)
    const grain = g.childNodes[6] as SVGLineElement;
    expect(grain.getAttribute("x1")).toBe("45");
    expect(grain.getAttribute("y1")).toBe("73");
    expect(grain.getAttribute("x2")).toBe("45");
    expect(grain.getAttribute("y2")).toBe("77");
  });
});

// ============================================================
// demand>1 多副本渲染（US-022 demand 系统）。
// demand>1 时 solver 给同一 pid 发 N 条 placed_items（同 id、不同 translation）。
// NestSVG 必须为该 pid 建 N 个 DOM 副本、各承一处 placement —— 否则 N 条共用同一 polygon、
// 后覆盖前，只剩 1/N 可见（视觉稀疏，但密度数字仍正确：极隐蔽的 bug）。
// ============================================================

/** 单片 demand=2 的 manifest（多副本渲染测试用）。 */
function makeManifestDemand(): ManifestMsg {
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
        demand: 2,
      },
    ],
  };
}

describe("NestSVG demand>1 (多副本渲染)", () => {
  it("manifest demand=2 → 该 pid 建 2 个毛版 polygon 副本（初始都 display:none）", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifestDemand();
    const ref = mountNestSVG(run);
    const svg = ref.current!;
    expect(svg.childNodes.length).toBe(3);   // bg + fab + g

    const g = svg.childNodes[2] as SVGGElement;
    const polys = Array.from(g.querySelectorAll("polygon"));
    expect(polys.length).toBe(2);            // demand=2 → 2 副本（修复前只有 1）
    for (const p of polys) {
      expect(p.getAttribute("fill")).toBe("#ff0000");
      expect(p.dataset.ptype).toBe("Front");
      expect(p.dataset.size).toBe("30");
      expect(p.style.display).toBe("none");  // 初始未 placed
    }
  });

  it("frame 含 2 条同 id placement → 2 副本各承一处（都可见、points 不同、不互相覆盖）", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifestDemand();
    const ref = mountNestSVG(run);
    const g = ref.current!.childNodes[2] as SVGGElement;
    const polys = Array.from(g.querySelectorAll("polygon"));

    const frame: FrameMsg = {
      type: "frame",
      index: 0,
      elapsed: 0.5,
      phase: "exploring",
      density: 0.8,
      density_sparrow: 0.82,
      width_mm: 1000,
      placed_items: [
        { id: "p1", rotation: 0, translation: [0, 0] },
        { id: "p1", rotation: 0, translation: [100, 200] },
      ],
    };
    run.frames.push(frame);
    run.lastFrame = frame;
    act(() => useAppStore.getState().bumpRenderTick());

    // 两个副本都可见（修复前：第 2 条覆盖第 1 条 → 只剩 1 个可见）
    expect(polys[0].style.display).toBe("");
    expect(polys[1].style.display).toBe("");
    // 副本0 ← 第 1 处 placement（tr 0,0）：polygon 平移后不变
    expect(polys[0].getAttribute("points")).toBe("0,0 10,0 10,10 0,10");
    // 副本1 ← 第 2 处 placement（tr 100,200）：每点 +（100,200）
    expect(polys[1].getAttribute("points")).toBe("100,200 110,200 110,210 100,210");
  });

  it("demand 缺省（旧 manifest 无此字段）→ 单副本（向后兼容）", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();   // 无 demand 字段
    const ref = mountNestSVG(run);
    const g = ref.current!.childNodes[2] as SVGGElement;
    expect(g.querySelectorAll("polygon").length).toBe(2);   // 2 pieces × 1 副本
  });
});
