// US-006 NestSVG seek + hover integration tests.
//   AC#2 seekTime >= 0 -> NestSVG uses frameAtTime(run, seekTime); seekTime=-1 keeps lastFrame
//   AC#4 mousemove on flipGroup -> closest("polygon") + dataset.ptype -> Tooltip
//   AC#6 switching hover polygon removes old class; mouseleave hides tooltip

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StrictMode, type MutableRefObject } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { NestSVG } from "../NestSVG";
import { Tooltip, hideTooltip, clearHovered } from "../../Tooltip";
import { useAppStore } from "../../../store/appStore";
import { runRegistry, type RunRecord } from "../../../store/runRegistry";
import type { FrameMsg, ManifestMsg } from "../../../types/ws";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  runRegistry.clear();
  useAppStore.setState({ renderTick: 0, seekTime: -1 });
  for (const el of Array.from(document.body.querySelectorAll(".tooltip"))) el.remove();
  clearHovered();
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
  clearHovered();
  hideTooltip();
  for (const el of Array.from(document.body.querySelectorAll(".tooltip"))) el.remove();
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
        ptype: "前片",
        size: 30,
        color: "#ff0000",
        area_mm2: 12345,
        polygon: [[0, 0], [100, 0], [100, 100], [0, 100]],
      },
      {
        id: "p2",
        ptype: "后片",
        size: 32,
        color: "#00ff00",
        area_mm2: 23456,
        polygon: [[0, 0], [200, 0], [200, 200], [0, 200]],
      },
    ],
  };
}

function makeFrame(placedIds: string[], width = 800, density = 0.5, elapsed = 0.5): FrameMsg {
  return {
    type: "frame",
    index: 0,
    elapsed,
    phase: "exploring",
    density,
    density_sparrow: density,
    width_mm: width,
    placed_items: placedIds.map((id, i) => ({
      id,
      rotation: 0,
      translation: [i * 100, i * 50],
    })),
  };
}

function mountNestAndTooltip(run: RunRecord): MutableRefObject<SVGSVGElement | null> {
  const ref: MutableRefObject<SVGSVGElement | null> = { current: null };
  function Probe() {
    return (
      <>
        <Tooltip />
        <div ref={(el) => { ref.current = el?.querySelector("svg") ?? null; }}>
          <NestSVG run={run} />
        </div>
      </>
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

function dispatchMouseMove(target: Element, x = 100, y = 100): void {
  target.dispatchEvent(
    new MouseEvent("mousemove", {
      bubbles: true,
      clientX: x,
      clientY: y,
      relatedTarget: target,
    }),
  );
}

describe("NestSVG seek (US-006 AC#2)", () => {
  it("seekTime=-1 uses lastFrame (live)", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const f1 = makeFrame(["p1"], 800, 0.5, 1);
    run.frames.push(f1);
    run.lastFrame = f1;
    const ref = mountNestAndTooltip(run);
    const svg = ref.current!;
    act(() => useAppStore.getState().bumpRenderTick());
    const fab = svg.childNodes[1] as SVGRectElement;
    expect(fab.getAttribute("width")).toBe("800");
  });

  it("seekTime >= 0 switches to frameAtTime(run, seekTime)", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    for (let i = 0; i < 5; i++) {
      const f = makeFrame(["p1"], 800 + i * 50, 0.5 + i * 0.01, i + 1);
      run.frames.push(f);
      run.lastFrame = f;
    }
    const ref = mountNestAndTooltip(run);
    const svg = ref.current!;

    act(() => useAppStore.getState().bumpRenderTick());
    const fab = svg.childNodes[1] as SVGRectElement;
    expect(fab.getAttribute("width")).toBe("1000");

    act(() => useAppStore.getState().setSeekTime(2));
    expect(fab.getAttribute("width")).toBe("850");

    act(() => useAppStore.getState().setSeekTime(4));
    expect(fab.getAttribute("width")).toBe("950");
  });

  it("seekTime=0 returns first frame", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    for (let i = 0; i < 3; i++) {
      const f = makeFrame(["p1"], 800 + i * 100, 0.5, i + 1);
      run.frames.push(f);
      run.lastFrame = f;
    }
    const ref = mountNestAndTooltip(run);
    const svg = ref.current!;
    act(() => useAppStore.getState().setSeekTime(0));
    const fab = svg.childNodes[1] as SVGRectElement;
    expect(fab.getAttribute("width")).toBe("800");
  });

  it("seekTime past last frame returns last frame", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    for (let i = 0; i < 3; i++) {
      const f = makeFrame(["p1"], 800 + i * 100, 0.5, i + 1);
      run.frames.push(f);
      run.lastFrame = f;
    }
    const ref = mountNestAndTooltip(run);
    const svg = ref.current!;
    act(() => useAppStore.getState().setSeekTime(9999));
    const fab = svg.childNodes[1] as SVGRectElement;
    expect(fab.getAttribute("width")).toBe("1000");
  });

  it("seekTime=-1 with no lastFrame does not render viewBox", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const ref = mountNestAndTooltip(run);
    act(() => useAppStore.getState().bumpRenderTick());
    expect(ref.current!.getAttribute("viewBox")).toBeNull();
  });
});

describe("NestSVG hover (US-006 AC#4..#6)", () => {
  it("AC#4 mousemove on polygon shows tooltip + adds hover class", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const f = makeFrame(["p1", "p2"], 1000);
    run.frames.push(f);
    run.lastFrame = f;
    const ref = mountNestAndTooltip(run);
    act(() => useAppStore.getState().bumpRenderTick());

    const flipGroup = ref.current!.childNodes[2] as SVGGElement;
    const poly1 = flipGroup.childNodes[0] as SVGPolygonElement;

    dispatchMouseMove(poly1, 200, 300);

    const tooltip = document.body.querySelector(".tooltip") as HTMLDivElement;
    expect(tooltip.style.display).toBe("block");
    expect(tooltip.style.left).toBe("214px");
    expect(tooltip.style.top).toBe("314px");
    expect(tooltip.innerHTML).toBe("前片 · 码30<br>面积 123.5 cm²");
    expect(poly1.classList.contains("hover")).toBe(true);
  });

  it("AC#4 mousemove on non-polygon target hides tooltip", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const f = makeFrame(["p1"], 1000);
    run.frames.push(f);
    run.lastFrame = f;
    const ref = mountNestAndTooltip(run);
    act(() => useAppStore.getState().bumpRenderTick());

    const flipGroup = ref.current!.childNodes[2] as SVGGElement;
    const poly = flipGroup.childNodes[0] as SVGPolygonElement;
    dispatchMouseMove(poly, 50, 50);
    expect((document.body.querySelector(".tooltip") as HTMLDivElement).style.display).toBe("block");

    dispatchMouseMove(flipGroup, 60, 60);
    expect((document.body.querySelector(".tooltip") as HTMLDivElement).style.display).toBe("none");
    expect(poly.classList.contains("hover")).toBe(false);
  });

  it("AC#6 switching hover polygon removes old class, adds new", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const f = makeFrame(["p1", "p2"], 1000);
    run.frames.push(f);
    run.lastFrame = f;
    const ref = mountNestAndTooltip(run);
    act(() => useAppStore.getState().bumpRenderTick());

    const flipGroup = ref.current!.childNodes[2] as SVGGElement;
    const poly1 = flipGroup.childNodes[0] as SVGPolygonElement;
    const poly2 = flipGroup.childNodes[1] as SVGPolygonElement;

    dispatchMouseMove(poly1, 10, 10);
    expect(poly1.classList.contains("hover")).toBe(true);
    expect(poly2.classList.contains("hover")).toBe(false);

    dispatchMouseMove(poly2, 20, 20);
    expect(poly1.classList.contains("hover")).toBe(false);
    expect(poly2.classList.contains("hover")).toBe(true);

    const tooltip = document.body.querySelector(".tooltip") as HTMLDivElement;
    expect(tooltip.innerHTML).toContain("后片");
    expect(tooltip.innerHTML).toContain("码32");
  });

  it("AC#4 area conversion mm^2 -> cm^2 (divide 100)", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const f = makeFrame(["p2"], 1000);
    run.frames.push(f);
    run.lastFrame = f;
    const ref = mountNestAndTooltip(run);
    act(() => useAppStore.getState().bumpRenderTick());

    const flipGroup = ref.current!.childNodes[2] as SVGGElement;
    const poly2 = flipGroup.childNodes[1] as SVGPolygonElement;
    dispatchMouseMove(poly2, 0, 0);

    const tooltip = document.body.querySelector(".tooltip") as HTMLDivElement;
    expect(tooltip.innerHTML).toBe("后片 · 码32<br>面积 234.6 cm²");
  });

  it("AC#6 mouseleave flipGroup hides tooltip + removes highlight", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const f = makeFrame(["p1"], 1000);
    run.frames.push(f);
    run.lastFrame = f;
    const ref = mountNestAndTooltip(run);
    act(() => useAppStore.getState().bumpRenderTick());

    const flipGroup = ref.current!.childNodes[2] as SVGGElement;
    const poly1 = flipGroup.childNodes[0] as SVGPolygonElement;
    dispatchMouseMove(poly1, 5, 5);
    expect(poly1.classList.contains("hover")).toBe(true);
    expect((document.body.querySelector(".tooltip") as HTMLDivElement).style.display).toBe("block");

    flipGroup.dispatchEvent(new MouseEvent("mouseleave", { bubbles: false }));

    expect(poly1.classList.contains("hover")).toBe(false);
    expect((document.body.querySelector(".tooltip") as HTMLDivElement).style.display).toBe("none");
  });

  it("seekTime changes do not lose hover handler", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    for (let i = 0; i < 3; i++) {
      const f = makeFrame(["p1"], 800 + i * 50, 0.5, i + 1);
      run.frames.push(f);
      run.lastFrame = f;
    }
    const ref = mountNestAndTooltip(run);

    act(() => useAppStore.getState().setSeekTime(1));
    act(() => useAppStore.getState().setSeekTime(2));
    act(() => useAppStore.getState().setSeekTime(0));

    const flipGroup = ref.current!.childNodes[2] as SVGGElement;
    const poly1 = flipGroup.childNodes[0] as SVGPolygonElement;
    dispatchMouseMove(poly1, 50, 50);
    expect(poly1.classList.contains("hover")).toBe(true);
  });
});
