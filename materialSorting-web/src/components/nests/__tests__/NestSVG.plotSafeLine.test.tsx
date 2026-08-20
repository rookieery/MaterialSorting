// 实际排料边界红虚线（实际幅宽口径，2026-08-20）单测：
// manifest 带 gate_nest_mm 且 < gate_mm（门幅被绘图仪可写幅宽 1910 钳制）时，
// NestSVG 建第 4 个骨架节点 <line>（红 #e53e3e、dasharray 8 5、顶层 + pointer-events
// none、根坐标不进翻转组），逐帧定位 y = gate_mm − gate_nest_mm、x2 = viewBox 锚宽 W；
// 缺字段（旧后端）/ 未钳制 → 不建；重解换 manifest 随骨架拆除无残留。

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StrictMode, type MutableRefObject } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { NestSVG } from "../NestSVG";
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
    act(() => {
      r.unmount();
    });
    root = null;
  }
  container?.remove();
  container = null;
  runRegistry.clear();
});

/** 带（或不带）gate_nest_mm 的单裁片 manifest（实际排料边界线测试用）。 */
function makeManifestNestGate(gateNest?: number): ManifestMsg {
  return {
    type: "manifest",
    gate_mm: 1980,
    gate_nest_mm: gateNest,
    total_area_mm2: 100000,
    n_eroded: 0,
    pieces: [
      {
        id: "p1",
        label: "g01",
        size: 30,
        color: "#ff0000",
        area_mm2: 12345,
        polygon: [[0, 0], [10, 0], [10, 10], [0, 10]],
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

describe("NestSVG 实际排料边界线（gate_nest_mm）", () => {
  it("manifest 带 gate_nest_mm=1910 → 顶层红虚线；frame 后 y=1980-1910=70、x2=viewBox 锚宽", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifestNestGate(1910);
    const ref = mountNestSVG(run);
    const svg = ref.current!;
    // bg + fab + g + 边界线（append 在翻转组之后 = 最顶层）
    expect(svg.childNodes.length).toBe(4);
    const line = svg.childNodes[3] as SVGLineElement;
    expect(line.tagName).toBe("line");
    expect(line.getAttribute("stroke")).toBe("#e53e3e");
    expect(line.getAttribute("stroke-width")).toBe("1.5");
    expect(line.getAttribute("stroke-dasharray")).toBe("8 5");
    expect(line.style.pointerEvents).toBe("none");
    // 不在翻转组内（根坐标，不随 scale(1,-1) 翻转）
    expect(line.parentNode).toBe(svg);

    // frame 到达 + tick → 定位：y = gate − gateNest = 70；x2 = W = max(viewBoxMaxW, width)
    const frame = makeFrame(["p1"], 800);
    run.frames.push(frame);
    run.lastFrame = frame;
    run.viewBoxMaxW = 900;
    act(() => useAppStore.getState().bumpRenderTick());
    expect(line.getAttribute("x1")).toBe("0");
    expect(line.getAttribute("x2")).toBe("900");
    expect(line.getAttribute("y1")).toBe("70");
    expect(line.getAttribute("y2")).toBe("70");
  });

  it("manifest 缺 gate_nest_mm（旧后端）→ 不画线（svg 子节点仍 3 个）", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifestNestGate(undefined);
    const ref = mountNestSVG(run);
    const svg = ref.current!;
    expect(svg.childNodes.length).toBe(3);
    expect(svg.querySelectorAll("line").length).toBe(0);
  });

  it("gate_nest_mm ≥ gate_mm（门幅未被钳制）→ 不画线", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifestNestGate(1980);   // = gate_mm，无内部差
    const ref = mountNestSVG(run);
    expect(ref.current!.childNodes.length).toBe(3);
    expect(ref.current!.querySelectorAll("line").length).toBe(0);
  });

  it("重解换成无 gate_nest_mm 的 manifest → 旧边界线随骨架拆除（无残留）", () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifestNestGate(1910);
    const ref = mountNestSVG(run);
    expect(ref.current!.querySelectorAll("line").length).toBe(1);

    run.manifest = makeManifestNestGate(undefined);   // 新对象 → 触发重建
    act(() => useAppStore.getState().bumpRenderTick());
    expect(ref.current!.querySelectorAll("line").length).toBe(0);
    expect(ref.current!.childNodes.length).toBe(3);
  });
});
