// US-004 ControlPanel integration tests:
//   AC#1 SizePicker renders 8 size chips, all default-checked
//   AC#2 defaults match legacy index.html (time=60, seed=0; multi_seed=false, seed_count=3)
//     ※ 2026-08-22 seed UI 隐藏：#seed/#multi_seed/#seed_count 不再渲染（原 US-005 断言改写）
//   AC#4 PerTypeOverrides（高级配置按钮）→ modal 列 = /api/ptypes reps 键（g 码，
//       US-003 起 V03_PTYPES 固定 10 中文列已删）
//   AC#6 click Start -> onStart fires; payload fields match collectParams
//   AC#7 0 sizes -> onStatus error + onStart NOT called
//
// US-005 additions:
//   AC#1 multi_seed checkbox + seed_count input render with legacy defaults
//   AC#1 toggle multi_seed + edit seed_count -> onStart.seed_count matches parseSeedCount
//     ※ 2026-08-22 seed UI 隐藏：以上用例改写为「不渲染 + 载荷恒单 seed」describe
//
// US-019 additions:
//   - 主面板不再渲染 d_ext/d_int/tol_ext/tol_int 输入（内外两档全交高级配置弹窗）。
//   - cfg.params 永远全 0（collectParams 主面板输入删除后兜底）。
//
// 矩阵化重构 US-003 additions:
//   - 全 0 拦截：doc 非空 + 所选码有效片数 0（数量全 0）→ onStart 不发 + onStatus 提示
//   - 线格式回归：矩阵改 A@28=2 → start payload quantities.g01['28']===2
//   - doc=null（fallback SIZES 开发模式）→ computeTotalCutPieces=null 不拦截（Start 正常发）

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { ControlPanel, type ControlPanelStartPayload } from "../ControlPanel";
import { SIZES } from "../../../constants/sizes";
import { useQtyStore } from "../../../store/qtyStore";
import { useUploadStore } from "../../../store/uploadStore";
import type { ParsedDoc } from "../../../types/parsed";
import type { SolvePhase } from "../../../types/solvePhase";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
// US-018：ControlPanel 内 PtypePreviewModal / PerTypeOverridesModal 会 fetch /api/ptypes；
// stub 防止 act warning。US-003 起 reps 键 = 裁片 g 码。
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
/** 当前 mock 返回的 representatives（每次 fetch 创建新 Response，避免 body 复用问题）。 */
let mockReps: { representatives: Record<string, unknown> } = { representatives: {} };
/** 两个 g 码代表裁片（modal 列集来源）。 */
const TWO_G_REPS = {
  representatives: {
    g01: { label: "g01", polygon: [[0, 0], [100, 0], [100, 60], [0, 60]] },
    g02: { label: "g02", polygon: [[0, 0], [80, 0], [80, 80], [0, 80]] },
  },
};

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  // US-017：uploadStore 是模块级单例，ControlPanel 现在 subscribe doc；
  // beforeEach 重置到默认 idle/doc=null 保证各用例隔离。
  useUploadStore.getState().reset();
  useQtyStore.getState().resetQuantities();
  mockReps = { representatives: {} };
  fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((_input: unknown) =>
    Promise.resolve(
      new Response(JSON.stringify(mockReps), {
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
  useQtyStore.getState().resetQuantities();
  if (fetchSpy) {
    fetchSpy.mockRestore();
    fetchSpy = null;
  }
});

function renderPanel(
  onStart: (cfg: ControlPanelStartPayload) => void = () => {},
  opts: { phase?: SolvePhase; status?: string; onStatus?: (t: string) => void } = {},
) {
  const onStatus = opts.onStatus ?? (() => {});
  act(() => {
    root!.render(
      <StrictMode>
        <ControlPanel
          onStart={onStart}
          phase={opts.phase ?? "idle"}
          status={opts.status ?? "READY"}
          onStatus={onStatus}
          onStop={() => {}}
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

  it("AC#2 defaults match legacy index.html (time=120)；2026-08-22 seed UI 隐藏（#seed/#multi_seed/#seed_count 不渲染）", () => {
    renderPanel();
    const get = (id: string) => container!.querySelector<HTMLInputElement>("#" + id)!;
    // US-019：d_ext/d_int/tol_ext/tol_int 主面板输入已删除，不应在 DOM 中
    expect(container!.querySelector("#d_ext")).toBeNull();
    expect(container!.querySelector("#d_int")).toBeNull();
    expect(container!.querySelector("#tol_ext")).toBeNull();
    expect(container!.querySelector("#tol_int")).toBeNull();
    expect(get("time").value).toBe("120");
    // 2026-08-22 seed UI 隐藏：seed 输入框 / 多 seed 对比开关 / 数量输入框均不渲染
    // （form.seed/multi_seed/seed_count 恒默认 → onStart 载荷 seed=0 / seed_count=1 不变）
    expect(container!.querySelector("#seed")).toBeNull();
    expect(container!.querySelector("#multi_seed")).toBeNull();
    expect(container!.querySelector("#seed_count")).toBeNull();
  });

  it("US-019 AC#6 主面板不再渲染内外两档输入（d_ext/d_int/tol_ext/tol_int）", () => {
    renderPanel();
    // 主面板精简：内外两档全局重合/旋转输入删除，全交高级配置弹窗
    expect(container!.querySelector("#d_ext")).toBeNull();
    expect(container!.querySelector("#d_int")).toBeNull();
    expect(container!.querySelector("#tol_ext")).toBeNull();
    expect(container!.querySelector("#tol_int")).toBeNull();
    // 也不再渲染 ErodeInputs / ToleranceInputs 的字段（label 文案「重合 erode」「旋转公差」）
    expect(container!.textContent).not.toContain("内/外两档");
    // PerTypeOverrides 按钮仍在（高级配置入口）
    expect(container!.querySelector(".per-type-btn")).not.toBeNull();
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

  it("AC#4 click button opens PerTypeOverridesModal (overlay+modal rendered)", async () => {
    // US-003：列 = /api/ptypes reps 键（g 码）；mock 返 2 个 g 码 → 2 列
    mockReps = TWO_G_REPS;
    renderPanel();
    const btn = container!.querySelector<HTMLButtonElement>(".per-type-btn")!;
    act(() => btn.click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    const overlay = document.body.querySelector(".per-type-overlay");
    expect(overlay).not.toBeNull();
    // 表头 2 列（g01/g02）+ 1 行头列
    const heads = overlay!.querySelectorAll("thead .ptype-col");
    expect(heads).toHaveLength(2);
    const badges = Array.from(heads).map((h) => h.querySelector(".qty-label-badge")!.textContent);
    expect(badges).toEqual(["g01", "g02"]);
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
    expect(cfg.time).toBe(120);
    expect(cfg.seed).toBe(0);
    expect(cfg.seed_count).toBe(1); // multi_seed 默认 false → 1
    expect(cfg.params).toEqual({ d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 });
    expect(cfg.per_type).toBeNull();
  });

  it("AC#7 0 sizes (US-017 default) -> 「开始求解」按钮置灰（disabled）+ onStart NOT called", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // US-017：默认 sizes=[] → 开始求解按钮置灰（前置 UI 反馈，替代旧的点击后 onStatus 报错）
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn.disabled).toBe(true);
    act(() => btn.click());
    expect(onStart).not.toHaveBeenCalled();
  });

  it("码号空 → #start disabled；勾选码号 → #start 解灰", () => {
    renderPanel();
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn.disabled).toBe(true);
    const checkbox = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]")[0]!;
    act(() => checkbox.click());
    expect(btn.disabled).toBe(false);
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

  it("AC#6 fill per_type via modal -> payload.per_type non-null with the edited entry", async () => {
    const onStart = vi.fn();
    // US-003：列集来自 /api/ptypes reps 键 → mock 返 g01/g02 两列
    mockReps = TWO_G_REPS;
    renderPanel(onStart);
    // US-017：先勾选至少一个码号，否则 Start 校验失败
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    // US-018：点击「高级配置」按钮打开 modal（fetch reps 后列集到位）
    const perTypeBtn = container!.querySelector<HTMLButtonElement>(".per-type-btn")!;
    act(() => perTypeBtn.click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    const overlay = document.body.querySelector(".per-type-overlay")!;
    // 在 modal 内修改 g01 列的两个 input（键 = 裁片 g 码）
    const dInput = overlay.querySelector<HTMLInputElement>(`[data-testid="d-g01"]`)!;
    const tolInput = overlay.querySelector<HTMLInputElement>(`[data-testid="tol-g01"]`)!;
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
    // Start -> per_type 含该 g 码的 {d:1, tol:1}
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.per_type).not.toBeNull();
    expect(cfg.per_type!["g01"]).toEqual({ d: 1, tol: 1 });
  });

  it("US-028 phase=running -> 无 #start 按钮（SolveControls 渲染 #stop）；参数编辑冻结", () => {
    renderPanel(() => {}, { phase: "running" });
    // running 态 SolveControls 渲染「停止」按钮（#stop），不渲染 #start
    expect(container!.querySelector("#start")).toBeNull();
    const stopBtn = container!.querySelector<HTMLButtonElement>("#stop")!;
    expect(stopBtn).not.toBeNull();
    expect(stopBtn.disabled).toBe(false);
    expect(stopBtn.getAttribute("aria-label")).toBe("停止求解");
    // 参数编辑控件全部 disabled（与原 StartButton disabled 同套机制；seed 控件 2026-08-22 已隐藏）
    expect(container!.querySelector<HTMLInputElement>("#time")!.disabled).toBe(true);
    expect(container!.querySelector<HTMLButtonElement>(".per-type-btn")!.disabled).toBe(true);
  });

  it("US-028 phase=stopped -> 「开始求解」按钮（#restart）+ 中间方案导出提示", () => {
    renderPanel(() => {}, { phase: "stopped" });
    const restartBtn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(restartBtn).not.toBeNull();
    expect(restartBtn.textContent).toBe("开始求解");
    expect(restartBtn.getAttribute("aria-label")).toBe("开始求解");
    // #start / #stop 不存在
    expect(container!.querySelector("#start")).toBeNull();
    expect(container!.querySelector("#stop")).toBeNull();
    // 参数编辑控件解冻（stopped 态可改参数后重新开始）
    expect(container!.querySelector<HTMLInputElement>("#time")!.disabled).toBe(false);
  });

  it("US-028 phase=done -> 「开始求解」按钮（#restart，文案与 stopped 统一）", () => {
    renderPanel(() => {}, { phase: "done" });
    const restartBtn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(restartBtn).not.toBeNull();
    expect(restartBtn.textContent).toBe("开始求解");
    expect(restartBtn.getAttribute("aria-label")).toBe("开始求解");
  });

  it("US-028 phase=error -> 「开始求解」按钮（与 stopped 同文案）", () => {
    renderPanel(() => {}, { phase: "error" });
    const restartBtn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(restartBtn).not.toBeNull();
    expect(restartBtn.textContent).toBe("开始求解");
  });
});

describe("ControlPanel seed UI 隐藏（2026-08-22 单 seed 模式）", () => {
  it("不渲染 seed 输入框 / multi_seed 开关 / seed_count 输入框（MultiSeedControls 已删）", () => {
    renderPanel();
    expect(container!.querySelector("#seed")).toBeNull();
    expect(container!.querySelector("#multi_seed")).toBeNull();
    expect(container!.querySelector("#seed_count")).toBeNull();
  });

  it("Start 载荷恒单 seed：seed=0 / seed_count=1（form 字段恒默认，parseSeedCount 恒 1）", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // US-017：先勾选一个码号让 Start 校验通过
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.seed).toBe(0);
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

  it("no run / no lastFrame -> export button disabled", () => {
    renderPanel();
    expect(container!.querySelector<HTMLButtonElement>(".export-btns button.export")!.disabled).toBe(true);
  });

  it("US-028 phase=running -> export button disabled (solving=phase==='running')", () => {
    renderPanel(() => {}, { phase: "running" });
    expect(container!.querySelector<HTMLButtonElement>(".export-btns button.export")!.disabled).toBe(true);
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
    // bump tick → export button enabled
    act(() => useAppStore.getState().bumpRenderTick());
    expect(container!.querySelector<HTMLButtonElement>(".export-btns button.export")!.disabled).toBe(false);

    // 切下拉框到 PNG（默认 DXF）后点导出
    const select = container!.querySelector<HTMLSelectElement>(".export-btns select")!;
    act(() => {
      select.value = "png";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });

    await act(async () => {
      container!.querySelector<HTMLButtonElement>(".export-btns button.export")!.click();
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

describe("ControlPanel doc-banner (当前文件名展示)", () => {
  it("doc=null → .doc-banner-name 灰字占位「尚未解析母版」+ .empty class", () => {
    renderPanel();
    const name = container!.querySelector(".doc-banner-name")!;
    expect(name.textContent).toBe("尚未解析母版");
    expect(name.classList.contains("empty")).toBe(true);
    // title 为空（占位态不提供悬停全名）
    expect(name.getAttribute("title")).toBe("");
  });

  it("doc 非空 → .doc-banner-name 渲染 doc.filename（含扩展名）+ title 兜底 + 无 .empty", () => {
    useUploadStore.setState({
      status: "done",
      doc: {
        doc_id: "banner-test",
        filename: "M1787_直筒_母版.dxf",
        sizes: [{ size: 30, pieces: [] }],
      },
    });
    renderPanel();
    const name = container!.querySelector(".doc-banner-name")!;
    expect(name.textContent).toBe("M1787_直筒_母版.dxf");
    expect(name.getAttribute("title")).toBe("M1787_直筒_母版.dxf");
    expect(name.classList.contains("empty")).toBe(false);
  });

  it("「当前文件」上下文条 + 「求解控制」功能标题并存，且文件名条在 h2 之前", () => {
    renderPanel();
    // 「当前文件」label
    const bannerLabel = container!.querySelector(".doc-banner .doc-banner-label")!;
    expect(bannerLabel.textContent).toBe("当前文件");
    // 「求解控制」h2 仍保留（功能标题不丢）
    const h2 = container!.querySelector(".panel h2")!;
    expect(h2.textContent).toBe("求解控制");
    // 顺序：banner 在 h2 前（h2 相对 banner 处于 FOLLOWING 位）
    const banner = container!.querySelector(".doc-banner")!;
    expect(h2.compareDocumentPosition(banner)).toBe(Node.DOCUMENT_POSITION_PRECEDING);
  });
});

// 矩阵化重构 US-003：handleStart 全 0 拦截 + quantities 线格式回归
describe("ControlPanel start guard (US-003 全 0 拦截)", () => {
  /** 构造 2 码母版（28: A；30: A+B），并按 PreviewPage 同口径 hydrate（默认 1）。 */
  function setupDocWithPieces(): void {
    const doc: ParsedDoc = {
      doc_id: "guard-test",
      filename: "M1787.dxf",
      sizes: [
        {
          size: 28,
          pieces: [
            {
              label: "g01",
              polygon: [],
              internal_lines: [],
              notches: [],
              net_polygon: [],
              grain_line: null,
            },
          ],
        },
        {
          size: 30,
          pieces: [
            {
              label: "g01",
              polygon: [],
              internal_lines: [],
              notches: [],
              net_polygon: [],
              grain_line: null,
            },
            {
              label: "g02",
              polygon: [],
              internal_lines: [],
              notches: [],
              net_polygon: [],
              grain_line: null,
            },
          ],
        },
      ],
    };
    useUploadStore.setState({ status: "done", doc, activeSize: 28 });
    useQtyStore.getState().hydrate(
      doc.sizes.flatMap((s) => s.pieces.map((p) => ({ label: p.label, size: s.size }))),
    );
  }

  it("doc 非空 + 所选码有效片数为 0（数量全 0）→ onStart 不发 + onStatus 提示", () => {
    const onStart = vi.fn();
    const onStatus = vi.fn();
    setupDocWithPieces();
    // 全部数量归 0（整行填充 0）
    useQtyStore.getState().setRowAll("g01", [28, 30], 0);
    useQtyStore.getState().setRowAll("g02", [30], 0);
    renderPanel(onStart, { onStatus });
    // 勾选 28 + 30（doc 动态码号 chip）
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => {
      for (const c of checkboxes) c.click();
    });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    // 全 0 拦截：不发 WS start（onStart 零调用），状态行提示
    expect(onStart).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledTimes(1);
    expect(onStatus.mock.calls[0][0]).toContain("有效裁片数为 0");
  });

  it("仅勾选数量全 0 的码 → 同样拦截（所选码口径，非全表）", () => {
    const onStart = vi.fn();
    const onStatus = vi.fn();
    setupDocWithPieces();
    // A@28=0 但 A@30=1：仅勾 28 → 该码有效片数 0 → 拦截
    useQtyStore.getState().setPiecePerSize("g01", 28, 0);
    renderPanel(onStart, { onStatus });
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click()); // 28
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    expect(onStart).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledTimes(1);
    // 再勾 30（A@30=1 有效）→ 通过拦截正常启动
    act(() => checkboxes[1].click()); // 30
    act(() => btn.click());
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("数量有效（默认 hydrate 1）→ onStart 正常发（回归：不误拦）", () => {
    const onStart = vi.fn();
    setupDocWithPieces();
    renderPanel(onStart);
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("doc=null（fallback SIZES 开发模式）→ computeTotalCutPieces=null 不拦截", () => {
    const onStart = vi.fn();
    renderPanel(onStart); // doc=null，未 hydrate
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => {
      for (const c of checkboxes) c.click();
    });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("线格式回归：矩阵改 A@28=2 → start payload quantities.g01['28']===2", () => {
    const onStart = vi.fn();
    setupDocWithPieces();
    // 模拟矩阵格内编辑：A@28=2（特例），其余保持 hydrate 默认 1
    useQtyStore.getState().setPiecePerSize("g01", 28, 2);
    renderPanel(onStart);
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => {
      for (const c of checkboxes) c.click(); // 28 + 30
    });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    expect(onStart).toHaveBeenCalledTimes(1);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.quantities).not.toBeNull();
    expect(cfg.quantities!.g01["28"]).toBe(2);
    expect(cfg.quantities!.g01["30"]).toBe(1);
    expect(cfg.quantities!.g02["30"]).toBe(1);
    // 未勾选码过滤：B 仅 30 码存在，无 28 键
    expect("28" in cfg.quantities!.g02).toBe(false);
  });
});

// ---------------------------------------------------------------- US-013 band
// 布局设置接线：弹窗勾选/下拉/确定写回 form.band_* → 启动闸门（置灰 + StatusLine
// band 段文案）/ 策略互斥（strategy-btn disabled + title）/ start payload band 生效。
describe("ControlPanel band 接线 (US-013)", () => {
  /** 2 码母版（28: g01；30: g01+g02），hydrate 默认 1（bandMemberCount 口径对齐）。 */
  function setupBandDoc(): void {
    const doc: ParsedDoc = {
      doc_id: "band-test",
      filename: "M1787.dxf",
      sizes: [
        {
          size: 28,
          pieces: [
            { label: "g01", polygon: [], internal_lines: [], notches: [], net_polygon: [], grain_line: null },
          ],
        },
        {
          size: 30,
          pieces: [
            { label: "g01", polygon: [], internal_lines: [], notches: [], net_polygon: [], grain_line: null },
            { label: "g02", polygon: [], internal_lines: [], notches: [], net_polygon: [], grain_line: null },
          ],
        },
      ],
    };
    useUploadStore.setState({ status: "done", doc, activeSize: 28 });
    useQtyStore.getState().hydrate(
      doc.sizes.flatMap((s) => s.pieces.map((p) => ({ label: p.label, size: s.size }))),
    );
  }

  /** 经弹窗写回 band 草稿（勾选 [+ 选 g01] → 确定）；label='' 仅勾选不选。 */
  async function enableBandViaModal(label: string): Promise<void> {
    mockReps = TWO_G_REPS;
    const perTypeBtn = container!.querySelector<HTMLButtonElement>(".per-type-btn")!;
    act(() => perTypeBtn.click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    const check = document.body.querySelector<HTMLInputElement>('[data-testid="band-enabled"]')!;
    act(() => check.click());
    if (label !== "") {
      const select = document.body.querySelector<HTMLSelectElement>('[data-testid="band-label-select"]')!;
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
      act(() => {
        setter.call(select, label);
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
    }
    const confirm = document.body.querySelector<HTMLButtonElement>(".per-type-btn-confirm")!;
    act(() => confirm.click());
  }

  /** 勾选全部码号（doc 动态码号 chips）。 */
  function selectAllSizes(): void {
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => {
      for (const c of checkboxes) c.click();
    });
  }

  it("band 开启未选编号 → #start 置灰 + StatusLine band 段文案；选中编号后解灰", async () => {
    const onStart = vi.fn();
    const onStatus = vi.fn();
    setupBandDoc();
    renderPanel(onStart, { onStatus });
    selectAllSizes();
    await enableBandViaModal("");
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn.disabled).toBe(true);
    const status = container!.querySelector("#status")!;
    expect(status.textContent).toContain("已开启腰头成带，请先选择腰头编号");
    // 置灰下点击不触发（防御）
    act(() => btn.click());
    expect(onStart).not.toHaveBeenCalled();
  });

  it("band 选中 g 码数量全 0 → #start 置灰 + StatusLine 提示；恢复数量解灰", async () => {
    const onStart = vi.fn();
    setupBandDoc();
    renderPanel(onStart);
    selectAllSizes();
    // g01 两码数量全 0（bandMemberCount=0 → 后端「数量全为 0」同条件前置闸门）
    act(() => {
      useQtyStore.getState().setRowAll("g01", [28, 30], 0);
    });
    await enableBandViaModal("g01");
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn.disabled).toBe(true);
    const status = container!.querySelector("#status")!;
    expect(status.textContent).toContain("腰头 g01 所选码数量全 0");
    // 恢复数量（28=2 偶数、30=2）→ 解灰
    act(() => {
      useQtyStore.getState().setRowAll("g01", [28, 30], 2);
    });
    expect(btn.disabled).toBe(false);
  });

  it("band 确定写回 form.band_* → start payload band = {enabled,label}（全链路写回生效）", async () => {
    const onStart = vi.fn();
    setupBandDoc();
    renderPanel(onStart);
    selectAllSizes();
    await enableBandViaModal("g01");
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn.disabled).toBe(false);
    act(() => btn.click());
    expect(onStart).toHaveBeenCalledTimes(1);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.band).toEqual({ enabled: true, label: "g01" });
  });

  it("band 开启 → strategy-btn 置灰 + title 互斥说明；band 关闭恢复可用", async () => {
    setupBandDoc();
    renderPanel(() => {});
    // band 关闭：doc 非空 + 非 solving → 可用，无 title
    const strategyBtn = container!.querySelector<HTMLButtonElement>('[data-testid="strategy-btn"]')!;
    expect(strategyBtn.disabled).toBe(false);
    expect(strategyBtn.getAttribute("title")).toBeNull();
    await enableBandViaModal("g01");
    expect(strategyBtn.disabled).toBe(true);
    expect(strategyBtn.getAttribute("title")).toContain("腰头成带与策略运行互斥");
    // 再经弹窗取消勾选 → 恢复
    const perTypeBtn = container!.querySelector<HTMLButtonElement>(".per-type-btn")!;
    act(() => perTypeBtn.click());
    const check = document.body.querySelector<HTMLInputElement>('[data-testid="band-enabled"]')!;
    act(() => check.click());   // 取消勾选（草稿 enabled=false）
    const confirm = document.body.querySelector<HTMLButtonElement>(".per-type-btn-confirm")!;
    act(() => confirm.click());
    expect(strategyBtn.disabled).toBe(false);
  });

  it("band 关闭（默认）→ strategy-btn 维持既有置灰口径（doc=null 仍置灰、无 title）", () => {
    renderPanel(() => {});   // doc=null
    const strategyBtn = container!.querySelector<HTMLButtonElement>('[data-testid="strategy-btn"]')!;
    expect(strategyBtn.disabled).toBe(true);   // doc===null 置灰（既有口径）
    expect(strategyBtn.getAttribute("title")).toBeNull();   // band 互斥 title 不出现
  });
});
