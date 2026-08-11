// US-004 ControlPanel integration tests:
//   AC#1 SizePicker renders 8 size chips, all default-checked
//   AC#2 defaults match legacy index.html (d_int=10, others 0; time=60, seed=0; multi_seed=false, seed_count=3)
//   AC#3 PresetButtons one-click fill 120 / 600
//   AC#4 PerTypeOverrides renders V03_TABLE 10 rows, internal ptypes badged
//   AC#6 click Start -> onStart fires; payload fields match collectParams
//   AC#7 0 sizes -> onStatus error + onStart NOT called
//
// US-005 additions:
//   AC#1 multi_seed checkbox + seed_count input render with legacy defaults
//   AC#1 toggle multi_seed + edit seed_count -> onStart.seed_count matches parseSeedCount

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { ControlPanel, type ControlPanelStartPayload } from "../ControlPanel";
import { SIZES } from "../../../constants/sizes";
import { V03_PTYPES } from "../../../constants/v03";
import { useUploadStore } from "../../../store/uploadStore";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
// US-018：ControlPanel 内 PtypePreviewModal 会 fetch /api/ptypes；stub 防止 act warning。
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  // US-017：uploadStore 是模块级单例，ControlPanel 现在 subscribe doc；
  // beforeEach 重置到默认 idle/doc=null 保证各用例隔离。
  useUploadStore.getState().reset();
  fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((_input: unknown) =>
    Promise.resolve(
      new Response(JSON.stringify({ representatives: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  ) as unknown as MockInstance<(...args: unknown[]) => Promise<Response>>;
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
  useUploadStore.getState().reset();
  if (fetchSpy) {
    fetchSpy.mockRestore();
    fetchSpy = null;
  }
});

function renderPanel(
  onStart: (cfg: ControlPanelStartPayload) => void = () => {},
  opts: { solving?: boolean; status?: string; onStatus?: (t: string) => void } = {},
) {
  const onStatus = opts.onStatus ?? (() => {});
  act(() => {
    root!.render(
      <StrictMode>
        <ControlPanel
          onStart={onStart}
          solving={opts.solving ?? false}
          status={opts.status ?? "READY"}
          onStatus={onStatus}
        />
      </StrictMode>,
    );
  });
}

describe("ControlPanel (US-004)", () => {
  it("AC#1 SizePicker renders 8 fallback chips (doc=null → SIZES); US-017 default NONE checked", () => {
    renderPanel();
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    expect(checkboxes).toHaveLength(SIZES.length);
    const values = Array.from(checkboxes).map((c) => parseInt(c.value, 10));
    expect(values).toEqual([...SIZES]);
    // US-017：DEFAULT_FORM.sizes = [] → 默认全未勾选
    for (const c of checkboxes) expect(c.checked).toBe(false);
  });

  it("AC#2 defaults match legacy index.html (d_int=10, others 0; time=60; seed=0; multi_seed=false; seed_count=3)", () => {
    renderPanel();
    const get = (id: string) => container!.querySelector<HTMLInputElement>("#" + id)!;
    expect(get("d_ext").value).toBe("0");
    expect(get("d_int").value).toBe("10");
    expect(get("tol_ext").value).toBe("0");
    expect(get("tol_int").value).toBe("0");
    expect(get("time").value).toBe("60");
    expect(get("seed").value).toBe("0");
    // US-005: multi_seed / seed_count defaults
    expect(get("multi_seed").checked).toBe(false);
    expect(get("seed_count").value).toBe("3");
  });

  it("AC#3 PresetButtons one-click fill 120 / 600", () => {
    renderPanel();
    const buttons = container!.querySelectorAll<HTMLButtonElement>("button.preset");
    expect(buttons).toHaveLength(2);
    act(() => buttons[0].click());
    expect(container!.querySelector<HTMLInputElement>("#time")!.value).toBe("120");
    act(() => buttons[1].click());
    expect(container!.querySelector<HTMLInputElement>("#time")!.value).toBe("600");
  });
});

describe("ControlPanel per_type (US-018 button trigger)", () => {
  it("AC#4 renders 高级配置 button (replaces old <details>); no .per_type .pt-row rows", () => {
    renderPanel();
    const btn = container!.querySelector<HTMLButtonElement>(".per-type-btn");
    expect(btn).not.toBeNull();
    expect(btn!.textContent).toContain("高级配置");
    // US-018：不再渲染旧 details 折叠 + 10 行 pt-row
    expect(container!.querySelectorAll(".per_type .pt-row")).toHaveLength(0);
    expect(container!.querySelector("details.advanced")).toBeNull();
  });

  it("AC#4 click button opens PerTypeOverridesModal (overlay+modal rendered)", () => {
    renderPanel();
    const btn = container!.querySelector<HTMLButtonElement>(".per-type-btn")!;
    act(() => btn.click());
    const overlay = document.body.querySelector(".per-type-overlay");
    expect(overlay).not.toBeNull();
    // 表头 10 列 + 1 行头列
    const heads = overlay!.querySelectorAll("thead .ptype-col");
    expect(heads).toHaveLength(V03_PTYPES.length);
    // tbody 2 行（重合 + 旋转）
    const rows = overlay!.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
  });
});

describe("ControlPanel start flow (US-004)", () => {
  it("AC#6 select-all-sizes + default form click Start -> onStart fires; payload matches collectParams", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // US-017：DEFAULT_FORM.sizes = [] → 先全选 fallback SIZES chips
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => {
      for (const c of checkboxes) c.click();
    });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    expect(onStart).toHaveBeenCalledTimes(1);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.sizes).toEqual([...SIZES]);
    expect(cfg.time).toBe(60);
    expect(cfg.seed).toBe(0);
    expect(cfg.seed_count).toBe(1); // multi_seed 默认 false → 1
    expect(cfg.params).toEqual({ d_ext: 0, d_int: 10, tol_ext: 0, tol_int: 0 });
    expect(cfg.per_type).toBeNull();
  });

  it("AC#7 0 sizes (US-017 default) -> onStatus error + onStart NOT called", () => {
    const onStart = vi.fn();
    const onStatus = vi.fn();
    renderPanel(onStart, { onStatus });

    // US-017：默认 sizes=[]，无需取消勾选
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());

    expect(onStart).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalled();
  });

  it("AC#6 select 30+31 then Start -> sizes matches checked order (US-017: no re-sort)", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    // US-017：默认未勾选 → 仅勾选 30 和 31（32 is not in SIZES — M1787 skips 32）
    act(() => {
      for (const c of checkboxes) {
        const v = parseInt(c.value, 10);
        if (v === 30 || v === 31) c.click();
      }
    });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.sizes).toEqual([30, 31]);
  });

  it("AC#6 fill per_type via modal -> payload.per_type non-null with the edited entry", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // US-017：先勾选至少一个码号，否则 Start 校验失败
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    // US-018：点击「高级配置」按钮打开 modal
    const perTypeBtn = container!.querySelector<HTMLButtonElement>(".per-type-btn")!;
    act(() => perTypeBtn.click());
    // 在 modal 内修改第一列（V03_PTYPES[0]）的两个 input
    const overlay = document.body.querySelector(".per-type-overlay")!;
    const ptype = V03_PTYPES[0];
    const dInput = overlay.querySelector<HTMLInputElement>(
      `[data-testid="d-${ptype}"]`,
    )!;
    const tolInput = overlay.querySelector<HTMLInputElement>(
      `[data-testid="tol-${ptype}"]`,
    )!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => {
      setter.call(dInput, "1");
      dInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => {
      setter.call(tolInput, "1");
      tolInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    // 点确定 -> 写回 form.per_type + 关闭 modal
    const confirm = overlay.querySelector<HTMLButtonElement>(".per-type-btn-confirm")!;
    act(() => confirm.click());
    expect(document.body.querySelector(".per-type-overlay")).toBeNull();
    // Start -> per_type 含该片型的 {d:1, tol:1}
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.per_type).not.toBeNull();
    expect(cfg.per_type![ptype]).toEqual({ d: 1, tol: 1 });
  });

  it("AC#6 solving=true -> Start disabled", () => {
    renderPanel(() => {}, { solving: true });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn.disabled).toBe(true);
  });
});

describe("ControlPanel multi-seed (US-005)", () => {
  it("AC#1 renders #multi_seed checkbox + #seed_count input (legacy defaults)", () => {
    renderPanel();
    const multi = container!.querySelector<HTMLInputElement>("#multi_seed")!;
    const count = container!.querySelector<HTMLInputElement>("#seed_count")!;
    expect(multi.type).toBe("checkbox");
    expect(multi.checked).toBe(false);
    expect(count.type).toBe("number");
    expect(count.value).toBe("3");
    expect(parseInt(count.min, 10)).toBe(2);
    expect(parseInt(count.max, 10)).toBe(6);
  });

  it("AC#1 toggle multi_seed + Start -> onStart.seed_count follows parseSeedCount", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // US-017：先勾选一个码号让 Start 校验通过
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    const multi = container!.querySelector<HTMLInputElement>("#multi_seed")!;
    act(() => multi.click());
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    // multi=true, count=default "3" → 3
    expect(cfg.seed_count).toBe(3);
  });

  it("AC#1 multi_seed=true + seed_count='10' -> clamp to 6", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // US-017：先勾选一个码号
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    const multi = container!.querySelector<HTMLInputElement>("#multi_seed")!;
    const count = container!.querySelector<HTMLInputElement>("#seed_count")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => {
      setter.call(count, "10");
      count.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => multi.click());
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.seed_count).toBe(6);
  });

  it("AC#1 multi_seed=true + seed_count empty -> fallback 3", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // US-017：先勾选一个码号
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    const multi = container!.querySelector<HTMLInputElement>("#multi_seed")!;
    const count = container!.querySelector<HTMLInputElement>("#seed_count")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => {
      setter.call(count, "");
      count.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => multi.click());
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.seed_count).toBe(3);
  });

  it("AC#1 multi_seed stays false -> seed_count changes ignored (returns 1)", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // US-017：先勾选一个码号
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    const count = container!.querySelector<HTMLInputElement>("#seed_count")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => {
      setter.call(count, "5");
      count.dispatchEvent(new Event("input", { bubbles: true }));
    });
    // multi_seed NOT toggled → still false
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.seed_count).toBe(1);
  });
});

describe("ControlPanel export wiring (US-007)", () => {
  it("renders ExportButtons group inside panel (after StatusLine)", () => {
    renderPanel();
    const group = container!.querySelector(".export-group");
    expect(group).not.toBeNull();
    // 顺序：StatusLine 在前，ExportButtons 后（同 legacy index.html）
    const status = container!.querySelector("#status")!;
    expect(status.compareDocumentPosition(group!)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("no run / no lastFrame -> export buttons disabled", () => {
    renderPanel();
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(true);
    expect(container!.querySelector<HTMLInputElement>("#export_dxf")!.disabled).toBe(true);
  });

  it("solving=true -> export buttons disabled (传透 props.solving)", () => {
    renderPanel(() => {}, { solving: true });
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(true);
    expect(container!.querySelector<HTMLInputElement>("#export_dxf")!.disabled).toBe(true);
  });

  it("click 导出 PNG → onStatus 收到「正在生成 PNG …」（hook 调用）", async () => {
    // 准备：一个已 done 的 run + fetch mock
    const { runRegistry } = await import("../../../store/runRegistry");
    const { useAppStore } = await import("../../../store/appStore");
    useAppStore.setState({ renderTick: 0, seekTime: -1 });
    const rec = runRegistry.create(0);
    rec.manifest = {
      type: "manifest", gate_mm: 1980, total_area_mm2: 100000, n_eroded: 0, pieces: [],
    };
    rec.frames.push({
      type: "frame", index: 0, elapsed: 1, phase: "final",
      density: 0.5, density_sparrow: 0.5, width_mm: 1000, placed_items: [],
    });
    rec.lastFrame = rec.frames[0];
    rec.finalDensity = 0.5;
    rec.done = true;

    const onStatus = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Blob([new Uint8Array([1])], { type: "image/png" }), {
        status: 200, headers: { "Content-Disposition": 'attachment; filename="x.png"' },
      }),
    );
    vi.stubGlobal("URL", {
      ...(globalThis.URL as object),
      createObjectURL: vi.fn(() => "blob:fake://1"),
      revokeObjectURL: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    renderPanel(() => {}, { onStatus });
    // bump tick → buttons enabled
    act(() => useAppStore.getState().bumpRenderTick());
    expect(container!.querySelector<HTMLInputElement>("#export_png")!.disabled).toBe(false);

    await act(async () => {
      container!.querySelector<HTMLButtonElement>("#export_png")!.click();
      // 让 fetch + microtasks 跑完
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(onStatus).toHaveBeenCalledWith("正在生成 PNG …");
    expect(fetchSpy).toHaveBeenCalled();
    fetchSpy.mockRestore();
    vi.unstubAllGlobals();
    runRegistry.clear();
  });
});

describe("ControlPanel StatusLine hint (US-017)", () => {
  it("AC#3 doc=null → StatusLine 增提示「请先在上传预览页解析母版」", () => {
    renderPanel(() => {}, { status: "READY" });
    const status = container!.querySelector("#status")!;
    expect(status.textContent).toContain("请先在上传预览页解析母版");
    expect(status.textContent).toContain("READY");
  });

  it("AC#3 doc 非空 → StatusLine 不带提示（仅原始 status）", () => {
    // 构造 doc 非空状态
    useUploadStore.setState({
      status: "done",
      doc: {
        doc_id: "hint-test",
        filename: "M1787.dxf",
        sizes: [{ size: 28, pieces: [] }],
      },
    });
    renderPanel(() => {}, { status: "READY" });
    const status = container!.querySelector("#status")!;
    expect(status.textContent).toBe("READY");
    expect(status.textContent).not.toContain("请先在上传预览页解析母版");
  });

  it("AC#3 doc=null → SizePicker 渲染 fallback SIZES（不是 doc.sizes）", () => {
    renderPanel();
    const chips = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    expect(chips).toHaveLength(SIZES.length);
  });

  it("AC#3 doc 非空 → SizePicker 渲染 doc.sizes（不是 fallback SIZES）", () => {
    useUploadStore.setState({
      status: "done",
      doc: {
        doc_id: "dynamic-test",
        filename: "M1787.dxf",
        sizes: [
          { size: 28, pieces: [] },
          { size: 30, pieces: [] },
          { size: null, pieces: [] },
        ],
      },
    });
    renderPanel();
    const chips = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    // doc.sizes 长度=3（不是 SIZES 的 8）
    expect(chips).toHaveLength(3);
    // null 码 chip 存在
    expect(container!.querySelector("#sz_null")).not.toBeNull();
    // 通用 文案在末尾
    const labels = Array.from(container!.querySelectorAll<HTMLLabelElement>(".sizes .chip label")).map(
      (l) => l.textContent ?? "",
    );
    expect(labels[labels.length - 1]).toBe("通用");
  });
});
