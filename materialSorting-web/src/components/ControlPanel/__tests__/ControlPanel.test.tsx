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
//
// 2026-08-27 重传联动 additions:
//   - doc_id 变化（重传）→ form 整体回 DEFAULT_FORM（码号清空 / band·prefix 关 /
//     per_type 清空 / 幅宽 175.00 / 时长 120；经 start payload 公共契约断言）
//   - doc_id 不变（切 activeSize）→ 不触发重置（用户编辑保留）
//   - 首次上传（null→doc_id）→ 同样回默认（effect 挂点统一，无特殊分支）

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { ControlPanel, type ControlPanelStartPayload } from "../ControlPanel";
import { SIZES } from "../../../constants/sizes";
import { useControlPanelStore } from "../../../store/controlPanelStore";
// 初始布局 US-004：入口按钮置灰判定订阅 supported（无母版 / 不支持两路径）。
import { __resetInitialLayoutStoreForTest, initialLayoutFingerprint, useInitialLayoutStore } from "../../../store/initialLayoutStore";
import { useFormStore } from "../../../store/formStore";
import { collectStartContext } from "../../../lib/params";
import { __resetKeyStoreForTest } from "../../../store/keyStore";
// key 授权 US-007：预检失败经 toastStore 弹中文（lib/keyGate 内出口）——断言其落队。
import { __resetToastsForTest, useToastStore } from "../../../store/toastStore";
import { runRegistry } from "../../../store/runRegistry";
import { useQtyStore } from "../../../store/qtyStore";
import { usePtypeStore } from "../../../store/ptypeStore";
import { useUploadStore } from "../../../store/uploadStore";
import type { ParsedDoc } from "../../../types/parsed";
import type { ManifestMsg } from "../../../types/ws";
import type { CompositePlacedItem } from "../../../lib/initialLayout";
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
  // ptypeStore 会话缓存同款重置（已 ready 时 modal 不再 fetch，mockReps 失效）。
  usePtypeStore.getState().reset();
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

/** key 授权 US-007 + 2026-10-05 普通运行弹窗：#start 点击只开 NormalRunModal
 * （需求 2），Portal 到 document.body 的确认键才进 handleStart → key 预检
 * （POST /api/key/precheck 网络往返）→ onStart 在微任务链末尾发出。两段各自独立
 * act（弹窗挂载在首个 act 退出时才 flush，同一 act 内确认键查无）+ 各补一次宏任务
 * 边界（setTimeout 0）排干在飞链（断言零改动；#start 置灰时弹窗不开 → confirm
 * 查无 → ?.click() 静默 no-op，不启动语义保持）。 */
async function clickStartFlush(btn: HTMLButtonElement): Promise<void> {
  await act(async () => {
    btn.click();
    await new Promise((r) => setTimeout(r, 0));
  });
  await act(async () => {
    const confirm = document.body.querySelector<HTMLButtonElement>(
      '[data-testid="normal-run-confirm"]',
    );
    confirm?.click();
    await new Promise((r) => setTimeout(r, 0));
  });
}

/** 2026-10-05 同步拦截类用例（全 0 拦截 / 预检在飞防连击）：开弹窗 + 点确认两段
 * act —— 同一 act 内 setState 未 flush、确认键尚未挂载，须分段；handleStart 的
 * 同步早退路径在第二段 act 内即完成（异步排干版 = clickStartFlush）。 */
function startViaModalSync(btn: HTMLButtonElement): void {
  act(() => btn.click());
  act(() => {
    document.body.querySelector<HTMLButtonElement>('[data-testid="normal-run-confirm"]')!.click();
  });
}

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

  it("AC#2 defaults match legacy index.html (time=120)；2026-08-22 seed UI 隐藏 + 2026-10-05 时长入弹窗/满核开关入面板", () => {
    renderPanel();
    // US-019：d_ext/d_int/tol_ext/tol_int 主面板输入已删除，不应在 DOM 中
    expect(container!.querySelector("#d_ext")).toBeNull();
    expect(container!.querySelector("#d_int")).toBeNull();
    expect(container!.querySelector("#tol_ext")).toBeNull();
    expect(container!.querySelector("#tol_int")).toBeNull();
    // 2026-10-05 需求 2：#time 移入普通运行弹窗（Portal 到 body），面板容器内
    // 不再渲染；默认值口径不变（formStore.form.time='120'，弹窗预填同源）。
    expect(container!.querySelector("#time")).toBeNull();
    expect(useFormStore.getState().form.time).toBe("120");
    // 2026-10-05 需求 1：满核开关移入面板通用配置（幅宽下方 .panel-switch-field），
    // 文案「满核运行」（去「是否」前缀），默认关。
    const switchField = container!.querySelector(".panel-switch-field")!;
    expect(switchField).not.toBeNull();
    expect(switchField.textContent).toContain("满核运行");
    expect(switchField.textContent).not.toContain("是否");
    expect(
      container!.querySelector<HTMLInputElement>(".panel-switch-field input[type=checkbox]")!
        .checked,
    ).toBe(false);
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

// ============================================================
// 2026-10-05 超排交互优化：#start 先经 NormalRunModal 确认时长（需求 2 —— 输入框
// #time 自 ParamForm 移入弹窗、id 保留冒烟脚本零改动）+ 满核开关入面板通用配置
// 幅宽下方（需求 1 —— 三族运行同源，高级/极限弹窗内开关已删）。
// ============================================================
describe("ControlPanel 普通运行弹窗 + 满核开关（2026-10-05）", () => {
  function checkFirstSize(): void {
    const checkbox = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]")[0]!;
    act(() => checkbox.click());
  }

  it("#start 点击只开弹窗不启动：Portal 到 body、#time 预填 form.time、确认前 onStart 不发", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    checkFirstSize();
    act(() => {
      container!.querySelector<HTMLButtonElement>("#start")!.click();
    });
    // 弹窗经 Portal 挂 document.body（面板容器内查无）
    expect(container!.querySelector('[data-testid="normal-run-overlay"]')).toBeNull();
    const overlay = document.body.querySelector('[data-testid="normal-run-overlay"]')!;
    expect(overlay).not.toBeNull();
    expect((document.body.querySelector("#time") as HTMLInputElement).value).toBe("120");
    expect(document.body.querySelector('[data-testid="normal-run-confirm"]')).not.toBeNull();
    expect(overlay.textContent).toContain("排料参数取当前面板");
    expect(onStart).not.toHaveBeenCalled();
  });

  it("弹窗改时长 60 → 确认 → 弹窗关 + formStore 回写 + onStart 载荷 time=60（预检链排干）", async () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    checkFirstSize();
    act(() => {
      container!.querySelector<HTMLButtonElement>("#start")!.click();
    });
    const input = document.body.querySelector<HTMLInputElement>("#time")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => {
      setter.call(input, "60");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      document.body.querySelector<HTMLButtonElement>('[data-testid="normal-run-confirm"]')!.click();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(document.body.querySelector('[data-testid="normal-run-overlay"]')).toBeNull();
    expect(useFormStore.getState().form.time).toBe("60");
    expect(onStart).toHaveBeenCalledTimes(1);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.time).toBe(60);
  });

  it("取消 / ESC / ✕ 只关不跑：form.time 不变、onStart 不发", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    checkFirstSize();
    // 取消按钮
    act(() => container!.querySelector<HTMLButtonElement>("#start")!.click());
    act(() => document.body.querySelector<HTMLButtonElement>('[data-testid="normal-run-cancel"]')!.click());
    expect(document.body.querySelector('[data-testid="normal-run-overlay"]')).toBeNull();
    // ESC
    act(() => container!.querySelector<HTMLButtonElement>("#start")!.click());
    act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
    expect(document.body.querySelector('[data-testid="normal-run-overlay"]')).toBeNull();
    // ✕
    act(() => container!.querySelector<HTMLButtonElement>("#start")!.click());
    act(() => document.body.querySelector<HTMLButtonElement>('[data-testid="normal-run-close"]')!.click());
    expect(document.body.querySelector('[data-testid="normal-run-overlay"]')).toBeNull();
    expect(onStart).not.toHaveBeenCalled();
    expect(useFormStore.getState().form.time).toBe("120");
  });

  it("码号空 → #start 置灰不开弹窗；弹窗开着时码号清空 → 确认键同源置灰（双保险）", async () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // 码号空：#start disabled → click 无效 → 弹窗不开（clickStartFlush 的 ?. 守卫路径）
    expect(container!.querySelector<HTMLButtonElement>("#start")!.disabled).toBe(true);
    await clickStartFlush(container!.querySelector<HTMLButtonElement>("#start")!);
    expect(document.body.querySelector('[data-testid="normal-run-overlay"]')).toBeNull();
    expect(onStart).not.toHaveBeenCalled();
    // 勾码号开弹窗 → 弹窗开着时清码号（面板在遮罩下仍在 DOM）→ 确认键置灰
    checkFirstSize();
    act(() => container!.querySelector<HTMLButtonElement>("#start")!.click());
    act(() => container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]")[0]!.click());
    expect(
      document.body.querySelector<HTMLButtonElement>('[data-testid="normal-run-confirm"]')!.disabled,
    ).toBe(true);
  });

  it("满核开关（需求 1）：默认关 → 载荷 full_cores=false；开 → true（WS 附键在 useSolveRun 层）", async () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    checkFirstSize();
    const switchInput = container!.querySelector<HTMLInputElement>(
      ".panel-switch-field input[type=checkbox]",
    )!;
    await clickStartFlush(container!.querySelector<HTMLButtonElement>("#start")!);
    let cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.full_cores).toBe(false);
    // 开满核 → 再跑 → 载荷 true
    act(() => switchInput.click());
    expect(switchInput.checked).toBe(true);
    await clickStartFlush(container!.querySelector<HTMLButtonElement>("#start")!);
    cfg = onStart.mock.calls[1][0] as ControlPanelStartPayload;
    expect(cfg.full_cores).toBe(true);
  });
});

describe("ControlPanel per_type (US-018 button trigger)", () => {
  it("AC#4 renders 设置算法参数 button (replaces old <details>); no .per_type .pt-row rows", () => {
    renderPanel();
    const btn = container!.querySelector<HTMLButtonElement>(".per-type-btn");
    expect(btn).not.toBeNull();
    // 2026-10-05 文案精简：按钮只显「设置算法参数」，分组语义由 .entry-group-label
    // 「高级配置」标题承担（与「设置初始布局」同行 .adv-entry-row）。
    expect(btn!.textContent).toBe("设置算法参数");
    expect(container!.querySelector(".entry-group-label")!.textContent).toBe("高级配置");
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
  it("AC#6 select-all-sizes + default form click Start -> onStart fires; payload matches collectParams", async () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // US-017：DEFAULT_FORM.sizes = [] → 先全选 fallback SIZES chips
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => {
      for (const c of checkboxes) c.click();
    });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
    expect(onStart).toHaveBeenCalledTimes(1);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.sizes).toEqual([...SIZES]);
    expect(cfg.time).toBe(120);
    expect(cfg.seed).toBe(0);
    expect(cfg.seed_count).toBe(1); // multi_seed 默认 false → 1
    expect(cfg.params).toEqual({ d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 });
    expect(cfg.per_type).toBeNull();
  });

  it("AC#7 0 sizes (US-017 default) -> 「普通运行」按钮置灰（disabled）+ onStart NOT called", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // US-017：默认 sizes=[] → 普通运行按钮置灰（前置 UI 反馈，替代旧的点击后 onStatus 报错）
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

  it("AC#6 select 30+31 then Start -> sizes matches checked order (US-017: no re-sort)", async () => {
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
    await clickStartFlush(btn);
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
    await clickStartFlush(btn);
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
    // 参数编辑控件全部 disabled（与原 StartButton disabled 同套机制；seed 控件 2026-08-22 已隐藏；
    // 2026-10-05 起 #time 已入弹窗 → 幅宽 #gate + 满核开关承载冻结断言）
    expect(container!.querySelector<HTMLInputElement>("#gate")!.disabled).toBe(true);
    expect(
      container!.querySelector<HTMLInputElement>(".panel-switch-field input[type=checkbox]")!
        .disabled,
    ).toBe(true);
    expect(container!.querySelector<HTMLButtonElement>(".per-type-btn")!.disabled).toBe(true);
  });

  it("US-028 phase=stopped -> 「普通运行」按钮（#restart）+ 中间方案导出提示", () => {
    renderPanel(() => {}, { phase: "stopped" });
    const restartBtn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(restartBtn).not.toBeNull();
    expect(restartBtn.textContent).toBe("普通运行");
    expect(restartBtn.getAttribute("aria-label")).toBe("普通运行");
    // #start / #stop 不存在
    expect(container!.querySelector("#start")).toBeNull();
    expect(container!.querySelector("#stop")).toBeNull();
    // 参数编辑控件解冻（stopped 态可改参数后重新开始；2026-10-05 #time 已入弹窗
    // → 幅宽 #gate + 满核开关承载解冻断言）
    expect(container!.querySelector<HTMLInputElement>("#gate")!.disabled).toBe(false);
    expect(
      container!.querySelector<HTMLInputElement>(".panel-switch-field input[type=checkbox]")!
        .disabled,
    ).toBe(false);
  });

  it("US-028 phase=done -> 「普通运行」按钮（#restart，文案与 stopped 统一）", () => {
    renderPanel(() => {}, { phase: "done" });
    const restartBtn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(restartBtn).not.toBeNull();
    expect(restartBtn.textContent).toBe("普通运行");
    expect(restartBtn.getAttribute("aria-label")).toBe("普通运行");
  });

  it("US-028 phase=error -> 「普通运行」按钮（与 stopped 同文案）", () => {
    renderPanel(() => {}, { phase: "error" });
    const restartBtn = container!.querySelector<HTMLButtonElement>("#restart")!;
    expect(restartBtn).not.toBeNull();
    expect(restartBtn.textContent).toBe("普通运行");
  });
});

describe("ControlPanel seed UI 隐藏（2026-08-22 单 seed 模式）", () => {
  it("不渲染 seed 输入框 / multi_seed 开关 / seed_count 输入框（MultiSeedControls 已删）", () => {
    renderPanel();
    expect(container!.querySelector("#seed")).toBeNull();
    expect(container!.querySelector("#multi_seed")).toBeNull();
    expect(container!.querySelector("#seed_count")).toBeNull();
  });

  it("Start 载荷恒单 seed：seed=0 / seed_count=1（form 字段恒默认，parseSeedCount 恒 1）", async () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    // US-017：先勾选一个码号让 Start 校验通过
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
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
    useAppStore.setState({ renderTick: 0 });
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

    // 2026-09-12 文件名需求 1：DXF/PNG 直通格式点导出先开「文件名」弹窗（不直接 fetch）
    let exportBody: unknown = null;
    fetchSpy.mockImplementation(((input: unknown, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/export") && init?.body) {
        exportBody = JSON.parse(String(init.body));
      }
      return Promise.resolve(
        new Response(new Blob([new Uint8Array([1])], { type: "image/png" }), {
          status: 200, headers: { "Content-Disposition": 'attachment; filename="x.png"' },
        }),
      );
    }) as unknown as (...args: unknown[]) => Promise<Response>);
    await act(async () => {
      container!.querySelector<HTMLButtonElement>(".export-btns button.export")!.click();
      await Promise.resolve();
    });
    // 不直接 POST /export（策略/极限入口的 mount 轮询照常，与导出无关）
    expect(fetchSpy.mock.calls.some((c) => String(c[0]).includes("/export"))).toBe(false);
    const nameModal = document.querySelector('[data-testid="save-name-overlay"]');
    expect(nameModal).not.toBeNull();
    // 确认（预填合成默认名，无扩展名）→ POST /export 载荷带 save_as（名称主体回传）
    await act(async () => {
      nameModal!.querySelector<HTMLButtonElement>('[data-testid="save-name-confirm"]')!.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(onStatus).toHaveBeenCalledWith("正在生成 PNG …");
    expect(fetchSpy).toHaveBeenCalled();
    expect(exportBody).toMatchObject({ fmt: "png" });
    expect((exportBody as { save_as?: string } | null)?.save_as)
      .toMatch(/^排料_码all_50\.00pct_seed0$/);
    fetchSpy.mockRestore();
    vi.unstubAllGlobals();
    runRegistry.clear();
  });

  it("PLT 毛版分流（2026-08-31）：选 PLT（毛版）→ 点导出先开弹窗（毛版文案），confirm 后 POST /export fmt='plt-clean'", async () => {
    const { runRegistry } = await import("../../../store/runRegistry");
    const { useAppStore } = await import("../../../store/appStore");
    const { markSessionProbedForTest, resetSessionForTest } = await import("../../../lib/api");
    markSessionProbedForTest();
    useAppStore.setState({ renderTick: 0 });
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

    const exportBodies: unknown[] = [];
    fetchSpy!.mockImplementation(((input: unknown, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/export")) {
        exportBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
        return Promise.resolve(
          new Response(new Blob([new Uint8Array([1])], { type: "application/plt" }), {
            status: 200, headers: { "Content-Disposition": 'attachment; filename="x_clean.plt"' },
          }),
        );
      }
      // /api/plt-table-preview → rows 缺失（降级形态；confirm 照常导出）
      return Promise.resolve(new Response(JSON.stringify({}), {
        status: 200, headers: { "Content-Type": "application/json" },
      }));
    }) as unknown as (...args: unknown[]) => Promise<Response>);
    vi.stubGlobal("URL", {
      ...(globalThis.URL as object),
      createObjectURL: vi.fn(() => "blob:fake://1"),
      revokeObjectURL: vi.fn(),
    });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    renderPanel(() => {});
    act(() => useAppStore.getState().bumpRenderTick());

    // 切下拉到 PLT（毛版，亦为默认格式）→ 点导出：不直接 POST /export，先开 export_info 弹窗
    const select = container!.querySelector<HTMLSelectElement>(".export-btns select")!;
    act(() => {
      select.value = "plt-clean";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => {
      container!.querySelector<HTMLButtonElement>(".export-btns button.export")!.click();
      await Promise.resolve();
    });
    expect(exportBodies).toHaveLength(0);
    const modal = document.querySelector(".strategy-modal")!;
    expect(modal).not.toBeNull();
    expect(modal.querySelector(".strategy-title")!.textContent).toContain("毛版");

    // 弹窗确认（手输字段留默认）→ POST /export 载荷 fmt='plt-clean'
    await act(async () => {
      modal.querySelector<HTMLButtonElement>('[data-testid="export-info-confirm"]')!.click();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(exportBodies).toHaveLength(1);
    expect(exportBodies[0]).toMatchObject({ fmt: "plt-clean" });
    expect(fetchSpy).toHaveBeenCalled();

    clickSpy.mockRestore();
    vi.unstubAllGlobals();
    resetSessionForTest();
    runRegistry.clear();
  });

  it("全量 PLT 分流回归锁：选 PLT → 点导出同样先开弹窗（无毛版文案）", async () => {
    const { runRegistry } = await import("../../../store/runRegistry");
    const { useAppStore } = await import("../../../store/appStore");
    useAppStore.setState({ renderTick: 0 });
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

    renderPanel(() => {});
    act(() => useAppStore.getState().bumpRenderTick());
    // 2026-08-31 起 DEFAULT_EXPORT_FMT='plt-clean'（毛版）—— 全量版需显式切回 plt
    act(() => {
      const select = container!.querySelector<HTMLSelectElement>(".export-btns select")!;
      select.value = "plt";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => {
      container!.querySelector<HTMLButtonElement>(".export-btns button.export")!.click();
      await Promise.resolve();
    });
    const modal = document.querySelector(".strategy-modal")!;
    expect(modal).not.toBeNull();
    expect(modal.querySelector(".strategy-title")!.textContent).not.toContain("毛版");
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

  it("AC#3 doc 非空 → SizePicker 渲染 doc.sizes 数字码（不是 fallback SIZES；null 通用码不渲染）", () => {
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
    // doc.sizes 数字码 2 个（不是 SIZES 的 8）；null 通用码不渲染 chip
    //（2026-08-31 起：通用片不参与求解，提示走解析完成 toast，排查在预览页「通用」行）
    expect(chips).toHaveLength(2);
    expect(container!.querySelector("#sz_null")).toBeNull();
    const labels = Array.from(container!.querySelectorAll<HTMLLabelElement>(".sizes .chip label")).map(
      (l) => l.textContent ?? "",
    );
    expect(labels).toEqual(["28", "30"]);
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
    // 2026-10-05：#start 先开弹窗，拦截断言须穿弹窗确认（同步早退路径）
    startViaModalSync(btn);
    // 全 0 拦截：不发 WS start（onStart 零调用），状态行提示
    expect(onStart).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledTimes(1);
    expect(onStatus.mock.calls[0][0]).toContain("有效裁片数为 0");
  });

  it("仅勾选数量全 0 的码 → 同样拦截（所选码口径，非全表）", async () => {
    const onStart = vi.fn();
    const onStatus = vi.fn();
    setupDocWithPieces();
    // A@28=0 但 A@30=1：仅勾 28 → 该码有效片数 0 → 拦截
    useQtyStore.getState().setPiecePerSize("g01", 28, 0);
    renderPanel(onStart, { onStatus });
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click()); // 28
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    startViaModalSync(btn);
    expect(onStart).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledTimes(1);
    // 再勾 30（A@30=1 有效）→ 通过拦截正常启动
    act(() => checkboxes[1].click()); // 30
    await clickStartFlush(btn);
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("数量有效（默认 hydrate 1）→ onStart 正常发（回归：不误拦）", async () => {
    const onStart = vi.fn();
    setupDocWithPieces();
    renderPanel(onStart);
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("doc=null（fallback SIZES 开发模式）→ computeTotalCutPieces=null 不拦截", async () => {
    const onStart = vi.fn();
    renderPanel(onStart); // doc=null，未 hydrate
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => {
      for (const c of checkboxes) c.click();
    });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("线格式回归：矩阵改 A@28=2 → start payload quantities.g01['28']===2", async () => {
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
    await clickStartFlush(btn);
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
// band 段文案）/ 策略入口不互斥（2026-08-22 解除，band 随 start 载荷透传）/
// start payload band 生效。
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
    await clickStartFlush(btn);
    expect(onStart).toHaveBeenCalledTimes(1);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.band).toEqual({ enabled: true, label: "g01" });
  });

  it("band 开启 → strategy-btn 仍可用（2026-08-22 解除互斥，band 随 start 载荷透传）", async () => {
    setupBandDoc();
    renderPanel(() => {});
    // band 关闭：doc 非空 + 非 solving → 可用，无 title
    const strategyBtn = container!.querySelector<HTMLButtonElement>('[data-testid="strategy-btn"]')!;
    expect(strategyBtn.disabled).toBe(false);
    expect(strategyBtn.getAttribute("title")).toBeNull();
    // band 开启：不再互斥 —— 入口保持可用、无互斥 title
    await enableBandViaModal("g01");
    expect(strategyBtn.disabled).toBe(false);
    expect(strategyBtn.getAttribute("title")).toBeNull();
  });

  it("band 关闭（默认）→ strategy-btn 维持既有置灰口径（doc=null 仍置灰、无 title）", () => {
    renderPanel(() => {});   // doc=null
    const strategyBtn = container!.querySelector<HTMLButtonElement>('[data-testid="strategy-btn"]')!;
    expect(strategyBtn.disabled).toBe(true);   // doc===null 置灰（既有口径）
    expect(strategyBtn.getAttribute("title")).toBeNull();   // band 互斥 title 不出现
  });
});

// ---------------------------------------------------------------- US-004 prefix
// 布局设置第二行接线：弹窗勾选/下拉/确定写回 form.prefix_* → 启动闸门（置灰 +
// StatusLine prefix 段文案）/ 策略入口不互斥（2026-08-25 解除，prefix 随 start
// 载荷透传）/ start payload prefix 生效 / band+prefix 可同开。
describe("ControlPanel prefix 接线 (US-004)", () => {
  /** 2 码母版（28: g01；30: g01+g02）—— polygon 空 → 默认预选不触发（面积无源）。 */
  function setupPrefixDoc(): void {
    const doc: ParsedDoc = {
      doc_id: "prefix-test",
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

  /** 经弹窗写回 prefix 草稿（勾选 [+ 选 front/back] → 确定）；'' = 仅勾选不选。 */
  async function enablePrefixViaModal(front: string, back: string): Promise<void> {
    mockReps = TWO_G_REPS;
    const perTypeBtn = container!.querySelector<HTMLButtonElement>(".per-type-btn")!;
    act(() => perTypeBtn.click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    const check = document.body.querySelector<HTMLInputElement>('[data-testid="prefix-enabled"]')!;
    act(() => check.click());
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
    for (const [tid, v] of [["prefix-front-select", front], ["prefix-back-select", back]] as const) {
      if (v === "") continue;
      const select = document.body.querySelector<HTMLSelectElement>(`[data-testid="${tid}"]`)!;
      act(() => {
        setter.call(select, v);
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

  it("prefix 开启未选前/后幅 → #start 置灰 + StatusLine prefix 段文案（防御点击不发）", async () => {
    const onStart = vi.fn();
    const onStatus = vi.fn();
    setupPrefixDoc();
    renderPanel(onStart, { onStatus });
    selectAllSizes();
    await enablePrefixViaModal("", "");
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn.disabled).toBe(true);
    const status = container!.querySelector("#status")!;
    expect(status.textContent).toContain("已开启起始端成套前后幅，请先选择前幅/后幅");
    act(() => btn.click());
    expect(onStart).not.toHaveBeenCalled();
  });

  it("prefix front==back → #start 置灰 + StatusLine 提示（后端「须为不同 g 码」前置）", async () => {
    const onStart = vi.fn();
    setupPrefixDoc();
    renderPanel(onStart);
    selectAllSizes();
    await enablePrefixViaModal("g01", "g01");
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn.disabled).toBe(true);
    const status = container!.querySelector("#status")!;
    expect(status.textContent).toContain("起始端成套前后幅须为不同 g 码");
    act(() => btn.click());
    expect(onStart).not.toHaveBeenCalled();
  });

  it("prefix 确定写回 form.prefix_* → start payload prefix = {enabled,front,back}（无资格码不置灰）", async () => {
    const onStart = vi.fn();
    setupPrefixDoc();
    renderPanel(onStart);
    selectAllSizes();
    // 数量矩阵默认全 1 → 无 2+2 资格码：前端不置灰（后端 _parse_prefix 权威拦截）
    await enablePrefixViaModal("g01", "g02");
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn.disabled).toBe(false);
    await clickStartFlush(btn);
    expect(onStart).toHaveBeenCalledTimes(1);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.prefix).toEqual({ enabled: true, front: "g01", back: "g02" });
  });

  it("prefix 开启 → strategy-btn 仍可用（2026-08-25 解除互斥，prefix 随 start 载荷透传）", async () => {
    setupPrefixDoc();
    renderPanel(() => {});
    const strategyBtn = container!.querySelector<HTMLButtonElement>('[data-testid="strategy-btn"]')!;
    // 关闭（默认）：doc 非空 + 非 solving → 可用，无 title
    expect(strategyBtn.disabled).toBe(false);
    expect(strategyBtn.getAttribute("title")).toBeNull();
    // 开启：不再互斥 —— 入口保持可用、无互斥 title（prefix 随 /api/strategy/start
    // 写进 9 键 config，后端 _parse_prefix 同一校验点）
    await enablePrefixViaModal("g01", "g02");
    expect(strategyBtn.disabled).toBe(false);
    expect(strategyBtn.getAttribute("title")).toBeNull();
  });

  it("band+prefix 双开 → start payload 两键各自生效（可同开，无额外控件）", async () => {
    const onStart = vi.fn();
    setupPrefixDoc();
    renderPanel(onStart);
    selectAllSizes();
    mockReps = TWO_G_REPS;
    // 同一弹窗内先配 band 再配 prefix → 确定
    const perTypeBtn = container!.querySelector<HTMLButtonElement>(".per-type-btn")!;
    act(() => perTypeBtn.click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    const bandCheck = document.body.querySelector<HTMLInputElement>('[data-testid="band-enabled"]')!;
    act(() => bandCheck.click());
    const bandSelect = document.body.querySelector<HTMLSelectElement>('[data-testid="band-label-select"]')!;
    const bandSetter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
    act(() => {
      bandSetter.call(bandSelect, "g01");
      bandSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const prefixCheck = document.body.querySelector<HTMLInputElement>('[data-testid="prefix-enabled"]')!;
    act(() => prefixCheck.click());
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
    const frontSel = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-front-select"]')!;
    act(() => {
      setter.call(frontSel, "g01");
      frontSel.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const backSel = document.body.querySelector<HTMLSelectElement>('[data-testid="prefix-back-select"]')!;
    act(() => {
      setter.call(backSel, "g02");
      backSel.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const confirm = document.body.querySelector<HTMLButtonElement>(".per-type-btn-confirm")!;
    act(() => confirm.click());
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    expect(btn.disabled).toBe(false);
    await clickStartFlush(btn);
    expect(onStart).toHaveBeenCalledTimes(1);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.band).toEqual({ enabled: true, label: "g01" });
    expect(cfg.prefix).toEqual({ enabled: true, front: "g01", back: "g02" });
  });

  it("prefix 关闭（默认）→ start payload prefix = null + strategy-btn 无互斥 title", async () => {
    const onStart = vi.fn();
    setupPrefixDoc();
    renderPanel(onStart);
    selectAllSizes();
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.prefix).toBeNull();
    const strategyBtn = container!.querySelector<HTMLButtonElement>('[data-testid="strategy-btn"]')!;
    expect(strategyBtn.disabled).toBe(false);
    expect(strategyBtn.getAttribute("title")).toBeNull();
  });
});

// ---------------------------------------------------------------- 2026-08-27 重传联动
// doc_id 变化（重传新母版 / 首次上传）→ ControlPanel form 整体回 DEFAULT_FORM
// （与 US-014 数量矩阵「重传清零」同口径）：旧母版的码号 / band / prefix / per_type /
// 幅宽时长残留会让 band·prefix 旧 g 码看似合法（后端 error 才暴露）、per_type 旧键
// 混进新母版表格列集。doc_id 不变（切 activeSize 等）不触发。
describe("ControlPanel 重传联动：doc_id 变化重置 form (2026-08-27)", () => {
  /** 构造 2 码母版并 hydrate（与 setupBandDoc 同款；doc_id 可指定模拟重传）。 */
  function setupDoc(docId: string): void {
    const doc: ParsedDoc = {
      doc_id: docId,
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

  /** 经弹窗写回 band 草稿（勾选 + 选 g01 → 确定；复用 US-013 同款交互）。 */
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

  it("重传（doc_id 变化）→ form 回 DEFAULT_FORM：码号清空 + #start 置灰 + 幅宽/时长回默认 + band 关闭", async () => {
    const onStart = vi.fn();
    setupDoc("master-a");
    renderPanel(onStart);
    // 旧母版下编辑 form：勾码号 + 开 band 选 g01 + 改幅宽/时长
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => {
      for (const c of checkboxes) c.click();
    });
    const gateInput = container!.querySelector<HTMLInputElement>("#gate")!;
    const numSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => {
      numSetter.call(gateInput, "180");
      gateInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    // 2026-10-05：#time 已移入普通运行弹窗（弹窗路径专测见下方 describe）——此处
    // 直写 formStore 模拟改时长；顺带开满核（重置面覆盖新键 full_cores）。
    act(() => {
      useFormStore.getState().patch({ time: "60", full_cores: true });
    });
    await enableBandViaModal("g01");
    expect(container!.querySelector<HTMLInputElement>("#gate")!.value).toBe("180");
    expect(useFormStore.getState().form.time).toBe("60");
    expect(useFormStore.getState().form.full_cores).toBe(true);
    // —— 重传新母版（doc_id 变化；hydrate 由 PreviewPage 负责，此处直写 store 模拟
    //     useParseDxf 成功后的 uploadStore 状态）——
    act(() => {
      setupDoc("master-b");
    });
    // 码号全清 → #start 置灰（DEFAULT_FORM.sizes=[]）
    const checkboxesAfter = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    for (const c of checkboxesAfter) expect(c.checked).toBe(false);
    expect(container!.querySelector<HTMLButtonElement>("#start")!.disabled).toBe(true);
    // 幅宽/时长/满核回默认（用户决策：全部重置，含机器参数；幅宽 2026-08-28 起两位
    // 小数口径；满核 2026-10-05 起随母版重置 —— FormState 归 DEFAULT_FORM）
    expect(container!.querySelector<HTMLInputElement>("#gate")!.value).toBe("175.00");
    expect(useFormStore.getState().form.time).toBe("120");
    expect(useFormStore.getState().form.full_cores).toBe(false);
    expect(
      container!.querySelector<HTMLInputElement>(".panel-switch-field input[type=checkbox]")!
        .checked,
    ).toBe(false);
    // StatusLine 无 band 闸门文案（band_enabled 已回 false）
    expect(container!.querySelector("#status")!.textContent).not.toContain("腰头成带");
  });

  it("重传后重新配置求解 → start payload 无旧母版残留（band/per_type null + 幅宽 1750）", async () => {
    const onStart = vi.fn();
    setupDoc("master-a");
    renderPanel(onStart);
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => {
      for (const c of checkboxes) c.click();
    });
    await enableBandViaModal("g01");
    act(() => {
      setupDoc("master-b");
    });
    // 新母版下重新勾码号 → 启动 → 载荷无 band（旧 g 码选择已清）、无 per_type、幅宽回 1750
    const checkboxesAfter = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => {
      for (const c of checkboxesAfter) c.click();
    });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
    expect(onStart).toHaveBeenCalledTimes(1);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.band).toBeNull();
    expect(cfg.prefix).toBeNull();
    expect(cfg.per_type).toBeNull();
    expect(cfg.gate_mm).toBe(1750);
  });

  it("doc_id 不变（切 activeSize / doc 引用不变）→ 不触发重置（编辑保留）", () => {
    setupDoc("master-a");
    renderPanel();
    const checkbox = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]")[0]!;
    act(() => checkbox.click());
    // 2026-10-05：#time 已入弹窗 —— 直写 formStore 模拟改时长（弹窗确认路径同patch）
    act(() => {
      useFormStore.getState().patch({ time: "60" });
    });
    // 切 activeSize（doc 对象引用不变、doc_id 不变）→ form 编辑保留
    act(() => {
      useUploadStore.setState({ activeSize: 30 });
    });
    expect(container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]")[0]!.checked).toBe(true);
    expect(useFormStore.getState().form.time).toBe("60");
  });

  it("首次上传（doc_id: undefined → id）→ form 同样回默认（挂点统一无特殊分支）", () => {
    renderPanel(); // doc=null（fallback SIZES chips）
    const checkbox = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]")[0]!;
    act(() => checkbox.click());
    expect(checkbox.checked).toBe(true);
    act(() => {
      setupDoc("first-upload");
    });
    // doc_id 从 undefined → 'first-upload'：effect 触发，码号回未勾
    expect(container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]")[0]!.checked).toBe(false);
  });
});

// ============================================================
// 状态文件：保存入口（2026-09-11 US-003 落地为导出格式下拉第 5 项 'state' 分支；
// 2026-09-12 入口改判拆出为独立区块 SaveStateControls —— 「编辑排料」与
// 「导出最优方案」之间，标题「保存当前方案状态（.msn）」+ 单「保存」按钮，
// 按钮状态与导出按钮同公式同数据源严格一致）。点「保存」→ useExport.saveState
//（POST /api/state-save，body=buildSavePayload），不进 /export、不弹
// ExportInfoModal；StatusLine 三态与 PNG/DXF/PLT 走同一 onStatus；exporting
// 单一防连击旗互斥。组件行为细节（结构/disabled 口径/双层防御）在
// SaveStateControls.test。
// ============================================================
describe("ControlPanel 状态文件保存入口（US-003 + 2026-09-12 入口改判）", () => {
  beforeEach(() => {
    runRegistry.clear();
  });
  afterEach(() => {
    runRegistry.clear();
  });

  /** done 态 run + fetch mock（state-save 捕获 body 到 bodies）+ URL/anchor stub。
   *  调用方需先 useAppStore.setState({ renderTick: 0 })。 */
  function setupForStateExport(bodies: unknown[]): void {
    const rec = runRegistry.create(0);
    rec.manifest = {
      type: "manifest", gate_mm: 1980, total_area_mm2: 100000, n_eroded: 0, pieces: [],
    };
    rec.frames.push({
      type: "frame", index: 0, elapsed: 1, phase: "final",
      density: 0.5, density_sparrow: 0.5, width_mm: 1000,
      placed_items: [{ id: "g01_28", rotation: 0, translation: [1, 2] }],
    });
    rec.lastFrame = rec.frames[0];
    rec.finalDensity = 0.5;
    rec.done = true;
    fetchSpy!.mockImplementation(((input: unknown, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/state-save")) {
        if (init?.body) bodies.push(JSON.parse(String(init.body)));
        return Promise.resolve(
          new Response(new Blob([new Uint8Array([1])], { type: "application/gzip" }), {
            status: 200,
            headers: { "Content-Disposition": 'attachment; filename="x_state_1.msn"' },
          }),
        );
      }
      // 其余（/api/ptypes 等）兜底 reps JSON
      return Promise.resolve(new Response(JSON.stringify(mockReps), {
        status: 200, headers: { "Content-Type": "application/json" },
      }));
    }) as unknown as (...args: unknown[]) => Promise<Response>);
    vi.stubGlobal("URL", {
      ...(globalThis.URL as object),
      createObjectURL: vi.fn(() => "blob:fake://1"),
      revokeObjectURL: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  }

  it("点「保存」按钮 → POST /api/state-save（body=buildSavePayload），不走 /export、不弹 ExportInfoModal", async () => {
    const { markSessionProbedForTest, resetSessionForTest } = await import("../../../lib/api");
    const { useAppStore } = await import("../../../store/appStore");
    markSessionProbedForTest();
    const bodies: unknown[] = [];
    useAppStore.setState({ renderTick: 0 });
    setupForStateExport(bodies);
    const onStatus = vi.fn();

    renderPanel(() => {}, { onStatus });
    act(() => useAppStore.getState().bumpRenderTick());
    // 2026-09-12 文件名需求 1：点保存先开「文件名」弹窗（预填合成默认名），确认才发请求
    await act(async () => {
      container!.querySelector<HTMLButtonElement>('[data-testid="save-state-btn"]')!.click();
      await Promise.resolve();
    });
    expect(document.querySelector('[data-testid="save-name-overlay"]')).not.toBeNull();
    const prefill = document.querySelector<HTMLInputElement>('[data-testid="save-name-input"]')!;
    expect(prefill.value).toMatch(/^排料_状态_\d{8}-\d{6}$/);
    await act(async () => {
      document.querySelector<HTMLButtonElement>('[data-testid="save-name-confirm"]')!.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    // 路由定论：/api/state-save（独立端点），无 /export 调用、无 export_info 弹窗
    const urls = fetchSpy!.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("/api/state-save"))).toBe(true);
    expect(urls.some((u) => u.includes("/export"))).toBe(false);
    expect(document.querySelector(".strategy-modal")).toBeNull();
    // body = buildSavePayload：form（DEFAULT_FORM 全量）+ quantities + run（placed 原序）
    //        + save_as（弹窗确认的整名 = 预填默认名，2026-09-12）
    expect(bodies).toHaveLength(1);
    const body = bodies[0] as {
      form: { gate: string }; quantities: Record<string, Record<string, number>> | null;
      run: { placed: { id: string }[] }; save_as?: string;
    };
    expect(body.form.gate).toBe("175.00");
    expect(body.quantities).toBeNull();
    expect(body.run.placed.map((it) => it.id)).toEqual(["g01_28"]);
    expect(body.save_as).toBe(prefill.value);

    // StatusLine 三态（useExport 同一 onStatus）
    expect(onStatus).toHaveBeenCalledWith("正在生成 状态文件 …");
    expect(onStatus).toHaveBeenCalledWith("已导出 x_state_1.msn");

    vi.unstubAllGlobals();
    resetSessionForTest();
  });

  it("state-save 失败 → StatusLine 导出失败：后端结构化 error 文案", async () => {
    const { markSessionProbedForTest, resetSessionForTest } = await import("../../../lib/api");
    const { useAppStore } = await import("../../../store/appStore");
    markSessionProbedForTest();
    useAppStore.setState({ renderTick: 0 });
    const rec = runRegistry.create(0);
    rec.manifest = { type: "manifest", gate_mm: 1980, total_area_mm2: 100000, n_eroded: 0, pieces: [] };
    rec.frames.push({
      type: "frame", index: 0, elapsed: 1, phase: "final",
      density: 0.5, density_sparrow: 0.5, width_mm: 1000, placed_items: [],
    });
    rec.lastFrame = rec.frames[0];
    rec.finalDensity = 0.5;
    rec.done = true;
    vi.spyOn(globalThis, "fetch").mockImplementation(((input: unknown) => {
      const url = String(input);
      if (url.includes("/api/state-save")) {
        return Promise.resolve(new Response(JSON.stringify({ error: "数量矩阵/尺码选择与当前结果不一致" }), {
          status: 400, headers: { "Content-Type": "application/json" },
        })) as unknown as Promise<Response>;
      }
      return Promise.resolve(new Response(JSON.stringify(mockReps), { status: 200 })) as unknown as Promise<Response>;
    }) as unknown as (...args: unknown[]) => Promise<Response>);
    const onStatus = vi.fn();
    renderPanel(() => {}, { onStatus });
    act(() => useAppStore.getState().bumpRenderTick());
    await act(async () => {
      container!.querySelector<HTMLButtonElement>('[data-testid="save-state-btn"]')!.click();
      await Promise.resolve();
    });
    // 2026-09-12：过「文件名」弹窗确认
    await act(async () => {
      document.querySelector<HTMLButtonElement>('[data-testid="save-name-confirm"]')!.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(onStatus).toHaveBeenCalledWith("导出失败：数量矩阵/尺码选择与当前结果不一致");
    resetSessionForTest();
  });

  it("保存期间 exporting 互斥：state 在飞时点 PNG 不发第二个请求（单一防连击旗）", async () => {
    const { markSessionProbedForTest, resetSessionForTest } = await import("../../../lib/api");
    markSessionProbedForTest();
    const { useAppStore } = await import("../../../store/appStore");
    useAppStore.setState({ renderTick: 0 });
    const rec = runRegistry.create(0);
    rec.manifest = { type: "manifest", gate_mm: 1980, total_area_mm2: 100000, n_eroded: 0, pieces: [] };
    rec.frames.push({
      type: "frame", index: 0, elapsed: 1, phase: "final",
      density: 0.5, density_sparrow: 0.5, width_mm: 1000, placed_items: [],
    });
    rec.lastFrame = rec.frames[0];
    rec.finalDensity = 0.5;
    rec.done = true;
    const urls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(((input: unknown) => {
      const url = String(input);
      urls.push(url);
      if (url.includes("/api/state-save")) {
        // 永不 resolve —— 保持 exporting 中
        return new Promise<Response>(() => {}) as unknown as Promise<Response>;
      }
      return Promise.resolve(new Response(JSON.stringify(mockReps), { status: 200 })) as unknown as Promise<Response>;
    }) as unknown as (...args: unknown[]) => Promise<Response>);
    vi.stubGlobal("URL", {
      ...(globalThis.URL as object),
      createObjectURL: vi.fn(() => "blob:fake://1"),
      revokeObjectURL: vi.fn(),
    });
    renderPanel(() => {});
    act(() => useAppStore.getState().bumpRenderTick());
    const select = () => container!.querySelector<HTMLSelectElement>(".export-btns select")!;
    const exportBtn = () => container!.querySelector<HTMLButtonElement>(".export-btns button.export")!;
    const saveBtn = () => container!.querySelector<HTMLButtonElement>('[data-testid="save-state-btn"]')!;
    await act(async () => {
      saveBtn().click();
      await Promise.resolve();
    });
    // 2026-09-12：过「文件名」弹窗确认 → state-save 才发出（pending promise 保持 exporting）
    await act(async () => {
      document.querySelector<HTMLButtonElement>('[data-testid="save-name-confirm"]')!.click();
      await Promise.resolve();
    });
    // state-save 发出后两按钮因共享 exporting 置灰（保存⇄导出双向联动）；
    // 防御：直接再切 PNG 点击也不发 /export、保存按钮旁路再点也不发第二个 state-save
    expect(saveBtn().disabled).toBe(true);
    expect(exportBtn().disabled).toBe(true);
    act(() => {
      select().value = "png";
      select().dispatchEvent(new Event("change", { bubbles: true }));
    });
    act(() => exportBtn().click());
    act(() => saveBtn().click());
    expect(urls.some((u) => u.includes("/export"))).toBe(false);
    expect(urls.filter((u) => u.includes("/api/state-save"))).toHaveLength(1);
    vi.unstubAllGlobals();
    resetSessionForTest();
  });
});

// ============================================================
// 编辑排料 US-004：「编辑排料」区块插入位置（StatusLine 与 ExportButtons 之间，
// 「导出最优方案」上方）—— 组件行为细节在 EditLayoutControls.test。
// ============================================================

describe("ControlPanel 编辑排料区块位置 (US-004)", () => {
  beforeEach(() => {
    runRegistry.clear();
  });
  afterEach(() => {
    runRegistry.clear();
  });

  it(".edit-controls 位于 StatusLine(.status) 之后、ExportButtons(.export-group) 之前", () => {
    renderPanel();
    const panel = container!.querySelector("aside.panel")!;
    const status = panel.querySelector(".status")!;
    const editControls = panel.querySelector(".edit-controls")!;
    const exportGroup = panel.querySelector(".export-group")!;
    expect(editControls).not.toBeNull();
    // DOM 序断言：status < edit-controls < export-group（compareDocumentPosition
    // 4 = FOLLOWING，即 a 在 b 前）
    expect(status.compareDocumentPosition(editControls) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(editControls.compareDocumentPosition(exportGroup) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(editControls.querySelector(".field-label")!.textContent).toBe("编辑排料");
  });
});

// ============================================================
// key 授权 US-006：「系统key」入口区块（ExportButtons 正下方）——
// 点击 openModal('key_info') 挂 KeyInfoModal（组件细节在 KeyInfoModal.test）。
// ============================================================

describe("ControlPanel key 属性入口 (US-006)", () => {
  beforeEach(() => {
    localStorage.clear();
    __resetKeyStoreForTest();
    useControlPanelStore.getState().closeModal();
  });
  afterEach(() => {
    // 弹窗若仍开着，store 复位会触发订阅更新 —— 包 act 防警告（root 卸载在
    // 文件级 afterEach，晚于此处）。
    act(() => {
      useControlPanelStore.getState().closeModal();
      __resetKeyStoreForTest();
      localStorage.clear();
    });
  });

  it(".key-entry-group 位于 .export-group 之后；field-label「系统key」", () => {
    renderPanel();
    const panel = container!.querySelector("aside.panel")!;
    const exportGroup = panel.querySelector(".export-group")!;
    const keyEntry = panel.querySelector(".key-entry-group")!;
    expect(keyEntry).not.toBeNull();
    expect(
      exportGroup.compareDocumentPosition(keyEntry) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(keyEntry.querySelector(".field-label")!.textContent).toBe("系统key");
  });

  it("点击入口按钮 → KeyInfoModal 打开（controlPanelStore.modal === 'key_info'）", async () => {
    renderPanel();
    const btn = container!.querySelector<HTMLButtonElement>('[data-testid="key-entry-btn"]')!;
    expect(btn).not.toBeNull();
    act(() => btn.click());
    expect(useControlPanelStore.getState().modal).toBe("key_info");
    // 弹窗 Portal 到 body（KeyInfoModal 渲染 + mount 即对账 /api/key/state；
    // apiFetch 未预置探测 → 会话先行也在这几拍内落定）
    await act(async () => {
      for (let i = 0; i < 6; i++) await Promise.resolve();
    });
    expect(document.querySelector('[data-testid="key-info-overlay"]')).not.toBeNull();
    expect(document.querySelector(".strategy-modal.key-modal")).not.toBeNull();
  });
});

// key 授权 US-007：普通运行前置 key 预检（POST /api/key/precheck）—— 拦截 / 放行 /
// 本地校验早退零网络 / 在飞窗口防连击。
describe("ControlPanel key 预检（key 授权 US-007）", () => {
  /** 最小母版（28 码 1 片）—— 全 0 拦截零网络用例的数据源。 */
  function setupOnePieceDoc(): void {
    const doc: ParsedDoc = {
      doc_id: "us007-guard",
      filename: "M1787.dxf",
      sizes: [
        {
          size: 28,
          pieces: [
            { label: "g01", polygon: [], internal_lines: [], notches: [], net_polygon: [], grain_line: null },
          ],
        },
      ],
    };
    act(() => {
      useUploadStore.setState({ doc, status: "done" });
    });
    // hydrate 数量默认 1（PreviewPage 同口径），全 0 用例自行清零
  }

  /** precheck 回包覆写 mock（其余 URL 走 mockReps 兜底）。 */
  function mockPrecheck(payload: unknown): void {
    fetchSpy!.mockImplementation(((input: unknown) => {
      const url = String(input);
      if (url.includes("/api/key/precheck")) {
        return Promise.resolve(
          new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(mockReps), { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    }) as unknown as (...args: unknown[]) => Promise<Response>);
  }

  function precheckFetchCount(): number {
    return fetchSpy!.mock.calls.filter((c: unknown[]) => String(c[0]).includes("/api/key/precheck")).length;
  }

  beforeEach(() => {
    __resetToastsForTest();
  });

  afterEach(() => {
    __resetToastsForTest();
  });

  it("precheck 拦截 → 不进 WS 连接（onStart 零调用）+ StatusLine 中文 + Toast", async () => {
    const onStart = vi.fn();
    const onStatus = vi.fn();
    mockPrecheck({ ok: false, message: "授权次数已用完，请续期或更换 key" });
    renderPanel(onStart, { onStatus });
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
    expect(precheckFetchCount()).toBe(1);
    expect(onStart).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledWith("授权次数已用完，请续期或更换 key");
    expect(useToastStore.getState().toasts.map((t) => t.message)).toContain("授权次数已用完，请续期或更换 key");
  });

  it("precheck 放行（{ok:true}）→ onStart 正常发（载荷同源不变）", async () => {
    const onStart = vi.fn();
    mockPrecheck({ ok: true });
    renderPanel(onStart);
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
    expect(onStart).toHaveBeenCalledTimes(1);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.sizes).toEqual([checkboxes[0].value].map((v) => parseInt(v, 10)));
    expect(cfg.time).toBe(120);
    expect(useToastStore.getState().toasts).toEqual([]);
  });

  it("本地校验早退（全 0 拦截）→ 零 precheck fetch（无效输入路径零网络）", () => {
    const onStart = vi.fn();
    const onStatus = vi.fn();
    setupOnePieceDoc();
    act(() => {
      useQtyStore.getState().setRowAll("g01", [28], 0);
    });
    renderPanel(onStart, { onStatus });
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click()); // 28
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    startViaModalSync(btn);
    // 同步拦截即得反馈（不经 precheck 网络往返）
    expect(onStart).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledTimes(1);
    expect(onStatus.mock.calls[0][0]).toContain("有效裁片数为 0");
    expect(precheckFetchCount()).toBe(0);
  });

  it("预检在飞窗口内双击 → 恰一次 onStart（gateInFlightRef 防连击）", async () => {
    const onStart = vi.fn();
    let release!: (v: Response) => void;
    fetchSpy!.mockImplementation(((input: unknown) => {
      const url = String(input);
      if (url.includes("/api/key/precheck")) {
        return new Promise<Response>((res) => {
          release = res;
        });
      }
      return Promise.resolve(
        new Response(JSON.stringify(mockReps), { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    }) as unknown as (...args: unknown[]) => Promise<Response>);
    renderPanel(onStart);
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click());
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    // 2026-10-05：防连击路径穿弹窗 —— 确认 1 进预检（pending，gateInFlight=true），
    // 重开弹窗确认 2 → 在飞早退（gateInFlightRef 在 handleStart 内同步置位）。
    startViaModalSync(btn); // 确认 1 → 进入预检（pending）
    startViaModalSync(btn); // 确认 2 → 在飞 → 早退
    await act(async () => {
      release(new Response(JSON.stringify({ ok: true }), { status: 200 }));
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(precheckFetchCount()).toBe(1);
    expect(onStart).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// 初始布局 US-004（prd-initial-layout）：「高级配置：设置初始布局」入口按钮。
// 置灰两条路径（PRD 验收：无母版态 + supported=false mock 态；浏览器同判据复验）
// + 点击 openModal('initial_layout') 接线（弹窗本体 US-006 落地）。

describe("ControlPanel initial layout entry (US-004)", () => {
  beforeEach(() => {
    __resetInitialLayoutStoreForTest();
  });
  afterEach(() => {
    __resetInitialLayoutStoreForTest();
    useControlPanelStore.getState().closeModal();
  });

  function initialBtn(): HTMLButtonElement {
    return container!.querySelector<HTMLButtonElement>('[data-testid="initial-layout-btn"]')!;
  }

  it("渲染在「设置算法参数」按钮同行右侧（2026-10-05 起两键一行）；文案 + per-type-btn 同款样式", () => {
    renderPanel();
    const btns = container!.querySelectorAll<HTMLButtonElement>(".per-type-btn");
    expect(btns.length).toBeGreaterThanOrEqual(2);
    expect(btns[0].textContent).toContain("设置算法参数");
    expect(btns[btns.length - 1].textContent).toBe("设置初始布局");
    expect(initialBtn()).toBe(btns[btns.length - 1]);
  });

  it("无母版态（doc=null）：置灰 + title「请先上传母版」；supported=null 不额外置灰", () => {
    renderPanel();
    const btn = initialBtn();
    expect(btn.disabled).toBe(true);
    expect(btn.title).toBe("请先上传母版");
  });

  it("无母版 + supported=false：无母版优先（title 仍指上传）", () => {
    useInitialLayoutStore.setState({ supported: false });
    renderPanel();
    const btn = initialBtn();
    expect(btn.disabled).toBe(true);
    expect(btn.title).toBe("请先上传母版");
  });

  it("有母版 + supported=false（mock 态）：置灰 + title「当前 spyrrow 版本不支持热启动」", () => {
    useUploadStore.setState({
      status: "done",
      doc: { doc_id: "il-test", filename: "M5336.dxf", sizes: [{ size: 28, pieces: [] }] },
    });
    useInitialLayoutStore.setState({ supported: false });
    renderPanel();
    const btn = initialBtn();
    expect(btn.disabled).toBe(true);
    expect(btn.title).toBe("当前 spyrrow 版本不支持热启动");
  });

  it("有母版 + supported=true：可点击 → openModal('initial_layout')", () => {
    useUploadStore.setState({
      status: "done",
      doc: { doc_id: "il-test", filename: "M5336.dxf", sizes: [{ size: 28, pieces: [] }] },
    });
    useInitialLayoutStore.setState({ supported: true });
    renderPanel();
    const btn = initialBtn();
    expect(btn.disabled).toBe(false);
    expect(btn.title).toBe("");
    act(() => btn.click());
    expect(useControlPanelStore.getState().modal).toBe("initial_layout");
  });

  it("有母版 + supported=null（探测失败/未探知）：不置灰（未知不放大利害）", () => {
    useUploadStore.setState({
      status: "done",
      doc: { doc_id: "il-test", filename: "M5336.dxf", sizes: [{ size: 28, pieces: [] }] },
    });
    renderPanel();
    expect(initialBtn().disabled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// prd-initial-layout US-007：普通运行接线 —— saved 且指纹新鲜 → onStart 载荷
// 附 initial（saved.warmPlaced + demandMap 非空才带 demand_map）；stale / 无 /
// 已清除 → null（运行照常发起不拦截）。chip 三态派生 + ×清除接线同覆。
// 指纹用 initialLayoutFingerprint(collectStartContext(form, quantities)) 与
// 生产同源构造（保存侧 US-006 同口径），不复制序列化逻辑。

describe("ControlPanel initial payload wiring (US-007)", () => {
  const MINIFEST: ManifestMsg = {
    type: "manifest",
    gate_mm: 1750,
    total_area_mm2: 1000,
    n_eroded: 0,
    pieces: [],
  };

  /** 单片母版（28 码 g01）+ 勾选 28 → form.sizes=[28]；返回现算指纹。 */
  function setupCheckedDoc(): string {
    const doc: ParsedDoc = {
      doc_id: "us007-warm",
      filename: "M5336.dxf",
      sizes: [
        {
          size: 28,
          pieces: [
            { label: "g01", polygon: [], internal_lines: [], notches: [], net_polygon: [], grain_line: null },
          ],
        },
      ],
    };
    act(() => {
      useUploadStore.setState({ doc, status: "done" });
    });
    renderPanel();
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => checkboxes[0].click()); // 28
    // 现算指纹（与 ControlPanel.initialChipState / buildInitialPayload 同源）
    return initialLayoutFingerprint(
      collectStartContext(useFormStore.getState().form, useQtyStore.getState().quantities),
    );
  }

  /** precheck 放行 mock（其余 URL 走 mockReps 兜底；handleStart 经 key 预检后 onStart）。 */
  function mockPrecheckOk(): void {
    fetchSpy!.mockImplementation(((input: unknown) => {
      const url = String(input);
      if (url.includes("/api/key/precheck")) {
        return Promise.resolve(
          new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "Content-Type": "application/json" } }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(mockReps), { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    }) as unknown as (...args: unknown[]) => Promise<Response>);
  }

  beforeEach(() => {
    __resetInitialLayoutStoreForTest();
    __resetToastsForTest();
    mockPrecheckOk();
  });
  afterEach(() => {
    __resetInitialLayoutStoreForTest();
    __resetToastsForTest();
  });

  it("saved 新鲜（指纹匹配）→ onStart 载荷 initial = {placed: warmPlaced, demand_map}", async () => {
    const fp = setupCheckedDoc();
    const warmPlaced: CompositePlacedItem[] = [
      { id: "WB_g05_34", rotation: 0, translation: [10, 20] },
      { id: "g01_28", rotation: 180, translation: [30, 40] },
    ];
    act(() => {
      useInitialLayoutStore.getState().setSaved({
      displayPlaced: [],
      warmPlaced,
      demandMap: { WB_g05_34: 1, g01_28: 1 },
      fingerprint: fp,
      widthMm: 1200,
      bandUsed: true,
      prefixUsed: false,
      manifest: MINIFEST,
        prefixMemberPids: [],
      });
    });
    // chip 三态派生：fresh
    expect(container!.querySelector('[data-testid="initial-chip"]')).not.toBeNull();
    const onStart = vi.fn();
    renderPanel(onStart);
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
    expect(onStart).toHaveBeenCalledTimes(1);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.initial).toEqual({ placed: warmPlaced, demand_map: { WB_g05_34: 1, g01_28: 1 } });
  });

  it("saved 新鲜但 demandMap=null（plain 形态）→ initial 仅 placed 无 demand_map 键", async () => {
    const fp = setupCheckedDoc();
    const warmPlaced: CompositePlacedItem[] = [{ id: "g01_28", rotation: 0, translation: [5, 5] }];
    act(() => {
      useInitialLayoutStore.getState().setSaved({
      displayPlaced: [],
      warmPlaced,
      demandMap: null,
      fingerprint: fp,
      widthMm: 900,
      bandUsed: false,
      prefixUsed: false,
      manifest: MINIFEST,
        prefixMemberPids: [],
      });
    });
    const onStart = vi.fn();
    renderPanel(onStart);
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.initial).toEqual({ placed: warmPlaced });
    expect("demand_map" in (cfg.initial ?? {})).toBe(false);
  });

  it("saved 已失效（数量漂移 → 指纹不匹配）→ initial=null + 运行照常发起（不拦截）+ chip stale", async () => {
    const fp = setupCheckedDoc();
    act(() => {
      useInitialLayoutStore.getState().setSaved({
      displayPlaced: [],
      warmPlaced: [],
      demandMap: null,
      fingerprint: fp,
      widthMm: 0,
      bandUsed: false,
      prefixUsed: false,
      manifest: MINIFEST,
        prefixMemberPids: [],
      });
    });
    // 数量漂移（指纹组件 quantities 变化 → isStale）
    act(() => {
      useQtyStore.getState().setRowAll("g01", [28], 3);
    });
    expect(container!.querySelector('[data-testid="initial-chip-stale"]')).not.toBeNull();
    const onStart = vi.fn();
    renderPanel(onStart);
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
    expect(onStart).toHaveBeenCalledTimes(1);
    expect((onStart.mock.calls[0][0] as ControlPanelStartPayload).initial).toBeNull();
  });

  it("无 saved → initial=null + 无 chip（默认零变化）", async () => {
    setupCheckedDoc();
    expect(container!.querySelector('[data-testid="initial-chip"]')).toBeNull();
    expect(container!.querySelector('[data-testid="initial-chip-stale"]')).toBeNull();
    expect(container!.querySelector('[data-testid="initial-chip-note"]')).toBeNull();
    const onStart = vi.fn();
    renderPanel(onStart);
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    await clickStartFlush(btn);
    expect((onStart.mock.calls[0][0] as ControlPanelStartPayload).initial).toBeNull();
  });

  it("fresh chip ×清除 → initialLayoutStore.saved 清空 + chip 退场", () => {
    const fp = setupCheckedDoc();
    act(() => {
      useInitialLayoutStore.getState().setSaved({
      displayPlaced: [],
      warmPlaced: [],
      demandMap: null,
      fingerprint: fp,
      widthMm: 0,
      bandUsed: false,
      prefixUsed: false,
      manifest: MINIFEST,
        prefixMemberPids: [],
      });
    });
    expect(container!.querySelector('[data-testid="initial-chip"]')).not.toBeNull();
    act(() => container!.querySelector<HTMLButtonElement>('[data-testid="initial-chip-clear"]')!.click());
    expect(useInitialLayoutStore.getState().saved).toBeNull();
    expect(container!.querySelector('[data-testid="initial-chip"]')).toBeNull();
  });

  it("running 态无 chip（fresh saved 在场也不渲染增益提示）", () => {
    const fp = setupCheckedDoc();
    act(() => {
      useInitialLayoutStore.getState().setSaved({
      displayPlaced: [],
      warmPlaced: [],
      demandMap: null,
      fingerprint: fp,
      widthMm: 0,
      bandUsed: false,
      prefixUsed: false,
      manifest: MINIFEST,
        prefixMemberPids: [],
      });
    });
    renderPanel(() => {}, { phase: "running" });
    expect(container!.querySelector('[data-testid="initial-chip"]')).toBeNull();
    expect(container!.querySelector("#stop")).not.toBeNull();
  });
});
