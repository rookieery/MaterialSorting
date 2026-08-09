// US-005 ConvergenceCurve tests:
//   AC#3 single seed: scatter colored by PHASE_COLORS + cumulative-best line (blue)
//   AC#3 multi seed: each run gets SEED_COLORS[i] line + endpoint circle + seed label
//   AC#4 always draw 90% death line (dashed + text)
//   AC#5 multi seed legend (one row per seed); single seed phase legend
//   AC#6 frames > 400 sampled by step = max(1, floor(n/400)); last frame forced
//   AC#7 imperative DOM (subscribes to renderTick; React only renders empty skeleton)
//   sampleFrames / renderCurveInto pure function coverage

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { ConvergenceCurve, renderCurveInto, sampleFrames } from "../ConvergenceCurve";
import { useAppStore } from "../../../store/appStore";
import { runRegistry, type RunRecord } from "../../../store/runRegistry";
import { PHASE_COLORS, SEED_COLORS } from "../../../constants/colors";
import type { FrameMsg } from "../../../types/ws";

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

function makeFrames(
  seed: number,
  count: number,
  opts: { startEl?: number; densityStart?: number; phase?: FrameMsg["phase"] } = {},
): FrameMsg[] {
  const startEl = opts.startEl ?? 0;
  const densityStart = opts.densityStart ?? 0.5;
  const phase = opts.phase ?? "exploring";
  const out: FrameMsg[] = [];
  for (let i = 0; i < count; i++) {
    out.push({
      type: "frame",
      index: i,
      elapsed: startEl + i * 0.1,
      phase,
      density: densityStart + i * 0.001,
      density_sparrow: densityStart + i * 0.001,
      width_mm: 1000,
      placed_items: [{ id: "p" + seed + "_" + i, rotation: 0, translation: [0, 0] }],
    });
  }
  return out;
}

function pushFrames(rec: RunRecord, frames: FrameMsg[]) {
  for (const f of frames) {
    rec.frames.push(f);
    rec.lastFrame = f;
  }
}

function mountCurve(): SVGSVGElement {
  let svg: SVGSVGElement | null = null;
  act(() => {
    root!.render(
      <StrictMode>
        <div ref={(el) => { svg = el?.querySelector("svg") ?? null; }}>
          <ConvergenceCurve />
        </div>
      </StrictMode>,
    );
  });
  return svg!;
}

describe("sampleFrames (US-005)", () => {
  it("AC#6 empty frames -> []", () => {
    expect(sampleFrames([])).toEqual([]);
  });

  it("AC#6 frames <= 400 -> all retained (step=1)", () => {
    const frames = makeFrames(0, 10);
    expect(sampleFrames(frames)).toHaveLength(10);
  });

  it("AC#6 frames > 400 -> step = floor(n/400); last frame forced in", () => {
    const frames = makeFrames(0, 1000);
    const sampled = sampleFrames(frames);
    expect(sampled.length).toBeLessThan(frames.length);
    expect(sampled.length).toBeGreaterThan(400);
    expect(sampled[sampled.length - 1]).toBe(frames[frames.length - 1]);
  });

  it("AC#6 step evenly divides -> last frame still forced in", () => {
    const frames = makeFrames(0, 800);
    const sampled = sampleFrames(frames);
    expect(sampled[sampled.length - 1]).toBe(frames[799]);
  });
});

describe("ConvergenceCurve rendering (US-005)", () => {
  it("AC#7 React only renders empty skeleton (no children when no frames)", () => {
    runRegistry.create(0);
    const svg = mountCurve();
    expect(svg.tagName).toBe("svg");
    expect(svg.innerHTML).toBe("");
  });

  it("AC#4 single seed: always draws 90% death line (dashed + text)", () => {
    const rec = runRegistry.create(0);
    pushFrames(rec, makeFrames(0, 10));
    const svg = mountCurve();
    act(() => useAppStore.getState().bumpRenderTick());

    const deathLine = Array.from(svg.querySelectorAll("line")).find((l) =>
      l.getAttribute("stroke-dasharray")?.includes("5"),
    );
    expect(deathLine).toBeTruthy();
    const text = Array.from(svg.querySelectorAll("text")).find((t) =>
      t.textContent?.includes("90%"),
    );
    expect(text).toBeTruthy();
  });

  it("AC#3 single seed: scatter colored by PHASE_COLORS (exploring blue)", () => {
    const rec = runRegistry.create(0);
    pushFrames(rec, makeFrames(0, 10, { phase: "exploring" }));
    const svg = mountCurve();
    act(() => useAppStore.getState().bumpRenderTick());

    const scatter = Array.from(svg.querySelectorAll("circle")).filter(
      (c) => c.getAttribute("r") === "2",
    );
    expect(scatter.length).toBeGreaterThan(0);
    for (const c of scatter) {
      expect(c.getAttribute("fill")).toBe(PHASE_COLORS.exploring);
    }
  });

  it("AC#3 single seed: cumulative-best line default blue + endpoint r=3 circle", () => {
    const rec = runRegistry.create(0);
    pushFrames(rec, makeFrames(0, 5));
    const svg = mountCurve();
    act(() => useAppStore.getState().bumpRenderTick());

    const path = svg.querySelector("path");
    expect(path).toBeTruthy();
    expect(path!.getAttribute("stroke")).toBe("#1f77b4");

    const endDot = Array.from(svg.querySelectorAll("circle")).find(
      (c) => c.getAttribute("r") === "3",
    );
    expect(endDot).toBeTruthy();
    expect(endDot!.getAttribute("fill")).toBe("#1f77b4");
  });
});

describe("ConvergenceCurve multi-seed + legend (US-005)", () => {
  it("AC#3 multi seed: each run gets SEED_COLORS[i] line + endpoint s-seed label", () => {
    const r0 = runRegistry.create(0);
    const r1 = runRegistry.create(1);
    pushFrames(r0, makeFrames(0, 5));
    pushFrames(r1, makeFrames(1, 5));
    const svg = mountCurve();
    act(() => useAppStore.getState().bumpRenderTick());

    const paths = svg.querySelectorAll("path");
    expect(paths.length).toBe(2);
    const strokeColors = new Set(Array.from(paths).map((p) => p.getAttribute("stroke")));
    expect(strokeColors.has(SEED_COLORS[0])).toBe(true);
    expect(strokeColors.has(SEED_COLORS[1])).toBe(true);

    const labels = Array.from(svg.querySelectorAll("text"))
      .map((t) => t.textContent ?? "")
      .filter((s) => /^s\d+$/.test(s));
    expect(labels.sort()).toEqual(["s0", "s1"]);
  });

  it("AC#5 multi seed: legend contains 'seed N' one row per run (rect + text)", () => {
    const r0 = runRegistry.create(0);
    const r1 = runRegistry.create(1);
    pushFrames(r0, makeFrames(0, 5));
    pushFrames(r1, makeFrames(1, 5));
    const svg = mountCurve();
    act(() => useAppStore.getState().bumpRenderTick());

    const legend = svg.querySelector("g.legend");
    expect(legend).toBeTruthy();
    const legendTexts = Array.from(legend!.querySelectorAll("text")).map((t) => t.textContent ?? "");
    expect(legendTexts).toContain("seed 0");
    expect(legendTexts).toContain("seed 1");
  });

  it("AC#5 single seed: legend contains three phase names", () => {
    const rec = runRegistry.create(0);
    pushFrames(rec, makeFrames(0, 5));
    const svg = mountCurve();
    act(() => useAppStore.getState().bumpRenderTick());

    const legend = svg.querySelector("g.legend");
    expect(legend).toBeTruthy();
    const legendTexts = Array.from(legend!.querySelectorAll("text")).map((t) => t.textContent ?? "");
    for (const ph of Object.keys(PHASE_COLORS)) {
      expect(legendTexts).toContain(ph);
    }
  });
});

describe("ConvergenceCurve imperative DOM (US-005)", () => {
  it("AC#7 subscribes to renderTick - bump rewrites innerHTML (scatter grows with frames)", () => {
    const rec = runRegistry.create(0);
    pushFrames(rec, makeFrames(0, 5));
    const svg = mountCurve();
    act(() => useAppStore.getState().bumpRenderTick());
    const scatterBefore = svg.querySelectorAll('circle[r="2"]').length;
    expect(scatterBefore).toBe(5);

    pushFrames(rec, makeFrames(0, 5, { startEl: 0.5 }));
    act(() => useAppStore.getState().bumpRenderTick());
    const scatterAfter = svg.querySelectorAll('circle[r="2"]').length;
    expect(scatterAfter).toBe(10);
  });

  it("AC#7 multiple bumps do not recreate svg (id stable; children rewritten)", () => {
    const rec = runRegistry.create(0);
    pushFrames(rec, makeFrames(0, 3));
    const svg = mountCurve();
    act(() => useAppStore.getState().bumpRenderTick());
    const vb1 = svg.getAttribute("viewBox");

    act(() => {
      useAppStore.getState().bumpRenderTick();
      useAppStore.getState().bumpRenderTick();
    });
    const vb2 = svg.getAttribute("viewBox");
    expect(vb1).toBe(vb2);
    expect(svg.querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("renderCurveInto pure function: svg can be rendered directly without React", () => {
    const rec = runRegistry.create(0);
    pushFrames(rec, makeFrames(0, 5));
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    document.body.appendChild(svg);
    renderCurveInto(svg);
    expect(svg.querySelectorAll("line").length).toBeGreaterThan(0);
    expect(svg.querySelectorAll("path").length).toBe(1);
    svg.remove();
  });
});
