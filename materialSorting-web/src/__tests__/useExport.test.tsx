// US-007 useExport hook unit tests.
// AC#1..#6 coverage; uses Probe component to capture hook return value.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { useExport } from "../hooks/useExport";
import { runRegistry, type RunRecord } from "../store/runRegistry";
import type { FrameMsg, ManifestMsg } from "../types/ws";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let captured: ReturnType<typeof useExport> | null = null;
function Probe({ onStatus }: { onStatus?: (t: string) => void }) {
  captured = useExport({ onStatus });
  return null;
}

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  runRegistry.clear();
  captured = null;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  // jsdom 不实现 URL.createObjectURL / revokeObjectURL；统一 stub（downloadBlob 会调）
  vi.stubGlobal("URL", {
    ...(globalThis.URL as object),
    createObjectURL: vi.fn(() => "blob:fake://1"),
    revokeObjectURL: vi.fn(),
  });
  // jsdom <a>.click() 触发 navigation 警告 —— stub 到 no-op（downloadBlob 会调）
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
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
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function makeManifest(gate = 1980): ManifestMsg {
  return { type: "manifest", gate_mm: gate, total_area_mm2: 100000, n_eroded: 0, pieces: [] };
}

function makeDoneRun(seed: number, density: number, width_mm = 1500, gate = 1980, placed: { id: string; rotation: number; translation: [number, number] }[] = []): RunRecord {
  const rec = runRegistry.create(seed);
  rec.manifest = makeManifest(gate);
  const f: FrameMsg = {
    type: "frame", index: 0, elapsed: 5, phase: "final",
    density, density_sparrow: density, width_mm, placed_items: placed,
  };
  rec.frames.push(f);
  rec.lastFrame = f;
  rec.finalDensity = density;
  rec.done = true;
  return rec;
}

function renderProbe(onStatus?: (t: string) => void) {
  act(() => {
    root!.render(<StrictMode><Probe onStatus={onStatus} /></StrictMode>);
  });
}

function makeResponse(body: Blob = new Blob([new Uint8Array([1, 2, 3])], { type: "image/png" }), init: { ok?: boolean; status?: number; statusText?: string; cd?: string; json?: unknown } = {}): Response {
  // 用纯对象存 header（key 已小写），get 时也小写查询 —— 模拟 Fetch Headers 大小写不敏感语义。
  const headers: Record<string, string> = {};
  if (init.cd !== undefined) headers["content-disposition"] = init.cd;
  const r = {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? "OK",
    headers: { get: (n: string) => headers[n.toLowerCase()] ?? null },
    blob: vi.fn(async () => body),
    json: vi.fn(async () => init.json ?? { error: "mock-error" }),
  };
  return r as unknown as Response;
}

describe("useExport (US-007)", () => {
  it("AC#1 + AC#6 no lastFrame -> onStatus hint + no fetch", async () => {
    const onStatus = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse());
    renderProbe(onStatus);
    expect(captured).not.toBeNull();
    await act(async () => { await captured!.exportAs("png", [28, 30]); });
    expect(onStatus).toHaveBeenCalledWith("无可导出的方案（请先求解）");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(captured!.exporting).toBe(false);
  });

  it("AC#1 bestRun multi-run picks highest finalDensity", async () => {
    makeDoneRun(0, 0.6);
    makeDoneRun(1, 0.85);
    makeDoneRun(2, 0.72);
    const onStatus = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse(undefined, { cd: "attachment; filename=x.png" }));
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("png", [28]); });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const arg = fetchSpy.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(arg.body as string) as { seed: number; density: number };
    expect(body.seed).toBe(1);
    expect(body.density).toBeCloseTo(0.85, 5);
  });

  it("AC#2 ExportPayload fields match vanilla 前身", async () => {
    const placed = [
      { id: "p1", rotation: 90, translation: [100, 200] as [number, number] },
      { id: "p2", rotation: 0, translation: [0, 0] as [number, number] },
    ];
    makeDoneRun(7, 0.8842, 3200, 1980, placed);
    const onStatus = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse(undefined, { cd: "attachment; filename=x.png" }));
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("png", [28, 30, 32]); });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    const body = JSON.parse(init.body as string) as {
      fmt: string; sizes: number[]; seed: number; gate_mm: number; width_mm: number; density: number;
      placed: typeof placed;
    };
    expect(body).toEqual({ fmt: "png", sizes: [28, 30, 32], seed: 7, gate_mm: 1980, width_mm: 3200, density: 0.8842, placed });
  });

  it("AC#3 fetch URL = /export (relative)", async () => {
    makeDoneRun(0, 0.5);
    const onStatus = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse());
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("png", [28]); });
    expect(fetchSpy.mock.calls[0][0]).toBe("/export");
  });

  it("AC#6 exporting=true toggles + onStatus writing", async () => {
    makeDoneRun(0, 0.5);
    const onStatus = vi.fn();
    let resolveRes!: (r: Response) => void;
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise<Response>((res) => { resolveRes = res; }));
    renderProbe(onStatus);
    let p!: Promise<void>;
    act(() => { p = captured!.exportAs("png", [28]); });
    expect(onStatus).toHaveBeenCalledWith("正在生成 PNG …");
    await act(async () => { await Promise.resolve(); });
    expect(captured!.exporting).toBe(true);
    await act(async () => { resolveRes(makeResponse()); await p; });
    expect(captured!.exporting).toBe(false);
    expect(onStatus).toHaveBeenLastCalledWith(expect.stringContaining("已导出"));
  });

  it("AC#6 DXF fmt -> onStatus writing DXF", async () => {
    makeDoneRun(0, 0.5);
    const onStatus = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse());
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("dxf", [28]); });
    expect(onStatus).toHaveBeenCalledWith("正在生成 DXF …");
  });
  it("AC#4 CN filename decoded from Content-Disposition (AC#5)", async () => {
    makeDoneRun(0, 0.8842, 3200);
    const onStatus = vi.fn();
    const encoded = "%E6%8E%92%E6%96%99_%E7%A0%8128-30-32_88.42pct_seed0.png";
    const cd = "attachment; filename=\"nesting.png\"; filename*=UTF-8''" + encoded;
    vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse(undefined, { cd }));
    // URL.createObjectURL + <a>.click() stub 已在 beforeEach 全局设置
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("png", [28]); });
    expect(onStatus).toHaveBeenLastCalledWith("已导出 排料_码28-30-32_88.42pct_seed0.png");
  });


  it("res.ok=false -> onStatus error field from json body", async () => {
    makeDoneRun(0, 0.5);
    const onStatus = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse(undefined, {
      ok: false, status: 400, statusText: "Bad Request",
      json: { error: "无可导出的方案（width=0 或无裁片）" },
    }));
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("png", [28]); });
    expect(onStatus).toHaveBeenLastCalledWith("导出失败：无可导出的方案（width=0 或无裁片）");
    expect(captured!.exporting).toBe(false);
  });

  it("res.ok=false + json throws -> statusText fallback", async () => {
    makeDoneRun(0, 0.5);
    const onStatus = vi.fn();
    const res = makeResponse(undefined, { ok: false, status: 500, statusText: "Internal Server Error" });
    (res as unknown as { json: () => Promise<never> }).json = async () => {
      throw new SyntaxError("not JSON");
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(res);
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("png", [28]); });
    expect(onStatus).toHaveBeenLastCalledWith("导出失败：Internal Server Error");
  });

  it("fetch network error -> onStatus error.message", async () => {
    makeDoneRun(0, 0.5);
    const onStatus = vi.fn();
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("png", [28]); });
    expect(onStatus).toHaveBeenLastCalledWith("导出失败：Failed to fetch");
    expect(captured!.exporting).toBe(false);
  });

  it("fetch rejects non-Error -> onStatus String(e)", async () => {
    makeDoneRun(0, 0.5);
    const onStatus = vi.fn();
    vi.spyOn(globalThis, "fetch").mockRejectedValue("network down");
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("png", [28]); });
    expect(onStatus).toHaveBeenLastCalledWith("导出失败：network down");
  });

  it("debounce: second call while exporting ignored", async () => {
    makeDoneRun(0, 0.5);
    const onStatus = vi.fn();
    let resolveRes!: (r: Response) => void;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise<Response>((res) => { resolveRes = res; }));
    renderProbe(onStatus);
    let p1!: Promise<void>;
    let p2!: Promise<void>;
    act(() => {
      p1 = captured!.exportAs("png", [28]);
      p2 = captured!.exportAs("png", [28]);
    });
    await act(async () => { await Promise.resolve(); });
    let p2done = false;
    p2.then(() => { p2done = true; });
    await act(async () => { await Promise.resolve(); });
    expect(p2done).toBe(true);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    await act(async () => { resolveRes(makeResponse()); await p1; });
    expect(captured!.exporting).toBe(false);
  });

  it("sizes passed through to payload", async () => {
    makeDoneRun(0, 0.5);
    const onStatus = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse());
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("dxf", [28, 30, 32]); });
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string) as { sizes: number[]; fmt: string };
    expect(body.sizes).toEqual([28, 30, 32]);
    expect(body.fmt).toBe("dxf");
  });

  it("gate_mm comes from run.manifest.gate_mm", async () => {
    makeDoneRun(0, 0.5, 1500, 1800);
    const onStatus = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse());
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("png", [28]); });
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string) as { gate_mm: number };
    expect(body.gate_mm).toBe(1800);
  });

  it("bestRun finalDensity tie -> first one wins", async () => {
    makeDoneRun(0, 0.5);
    makeDoneRun(1, 0.5);
    const onStatus = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse());
    renderProbe(onStatus);
    await act(async () => { await captured!.exportAs("png", [28]); });
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string) as { seed: number };
    expect(body.seed).toBe(0);
  });
});
