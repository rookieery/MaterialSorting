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

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { ControlPanel, type ControlPanelStartPayload } from "../ControlPanel";
import { SIZES } from "../../../constants/sizes";
import { V03_PTYPES, V03_TABLE } from "../../../constants/v03";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
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
  it("AC#1 SizePicker renders 8 size chips, all default-checked", () => {
    renderPanel();
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    expect(checkboxes).toHaveLength(SIZES.length);
    const values = Array.from(checkboxes).map((c) => parseInt(c.value, 10));
    expect(values).toEqual([...SIZES]);
    for (const c of checkboxes) expect(c.checked).toBe(true);
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

describe("ControlPanel per_type (US-004)", () => {
  it("AC#4 renders V03_TABLE 10 rows; internal ptypes badged", () => {
    renderPanel();
    const rowEls = container!.querySelectorAll<HTMLDivElement>(".per_type .pt-row");
    expect(rowEls).toHaveLength(V03_PTYPES.length);

    // ptype names order matches V03_PTYPES (badge text excluded)
    const names = Array.from(rowEls).map((r) => {
      const node = r.querySelector(".pt-name")!;
      const clone = node.cloneNode(true) as HTMLElement;
      const i = clone.querySelector("i");
      if (i) i.remove();
      return clone.textContent!;
    });
    expect(names).toEqual(V03_PTYPES);

    // Each ptype internal flag matches <i> presence
    for (const pt of V03_PTYPES) {
      const row = rowEls[V03_PTYPES.indexOf(pt)];
      const hasBadge = !!row.querySelector(".pt-name i");
      expect(hasBadge).toBe(V03_TABLE[pt].internal);
    }
  });

  it("AC#4 placeholders hint d<=X / t<=Y from V03_TABLE", () => {
    renderPanel();
    const rowEls = container!.querySelectorAll<HTMLDivElement>(".per_type .pt-row");
    const LE = String.fromCharCode(0x2264);
    for (const pt of V03_PTYPES) {
      const row = rowEls[V03_PTYPES.indexOf(pt)];
      const inputs = row.querySelectorAll<HTMLInputElement>("input[type=number]");
      expect(inputs[0].placeholder).toBe("d" + LE + V03_TABLE[pt].d);
      expect(inputs[1].placeholder).toBe("t" + LE + V03_TABLE[pt].tol);
    }
  });
});

describe("ControlPanel start flow (US-004)", () => {
  it("AC#6 default form click Start -> onStart fires; payload matches collectParams", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
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

  it("AC#7 0 sizes -> onStatus error + onStart NOT called", () => {
    const onStart = vi.fn();
    const onStatus = vi.fn();
    renderPanel(onStart, { onStatus });

    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    act(() => {
      for (const c of checkboxes) c.click();
    });

    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());

    expect(onStart).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalled();
  });

  it("AC#6 toggle sizes then Start -> sizes matches checked (numeric ascending)", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    const checkboxes = container!.querySelectorAll<HTMLInputElement>(".sizes input[type=checkbox]");
    // Keep only 30 and 31 (32 is not in SIZES — M1787 skips 32 between 31 and 33)
    act(() => {
      for (const c of checkboxes) {
        const v = parseInt(c.value, 10);
        if (v !== 30 && v !== 31) c.click();
      }
    });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.sizes).toEqual([30, 31]);
  });

  it("AC#6 fill per_type input -> payload.per_type non-null with the edited entry", () => {
    const onStart = vi.fn();
    renderPanel(onStart);
    const rowEls = container!.querySelectorAll<HTMLDivElement>(".per_type .pt-row");
    const frontRow = rowEls[0]; // V03_PTYPES[0]
    const inputs = frontRow.querySelectorAll<HTMLInputElement>("input[type=number]");
    // React 18 + jsdom: must use native value setter (from HTMLInputElement.prototype)
    // so React's internal value tracker detects the change before dispatching 'input'.
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => {
      setter.call(inputs[0], "1");
      inputs[0].dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => {
      setter.call(inputs[1], "1");
      inputs[1].dispatchEvent(new Event("input", { bubbles: true }));
    });
    const btn = container!.querySelector<HTMLButtonElement>("#start")!;
    act(() => btn.click());
    const cfg = onStart.mock.calls[0][0] as ControlPanelStartPayload;
    expect(cfg.per_type).not.toBeNull();
    const keys = Object.keys(cfg.per_type!);
    expect(keys.length).toBe(1);
    expect(cfg.per_type![keys[0]]).toEqual({ d: 1, tol: 1 });
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
