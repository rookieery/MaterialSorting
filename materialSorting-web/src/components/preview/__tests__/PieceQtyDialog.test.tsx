// US-012 PieceQtyDialog integration tests（US-001 删「全部尺码」global 开关后改写）:
//   AC: qtyDialog=null does not render DOM; opening renders title with label+sizeLabel
//   AC: initial draftQty from qtyStore getPieceDisplay
//   AC: [+][-] / input change draftQty; [-]@0 disabled
//   AC: confirm calls setPiecePerSize (per-size only) + close
//   AC: cancel does not write store; overlay click closes; ESC closes

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { PieceQtyDialog } from "../PieceQtyDialog";
import { useUploadStore } from "../../../store/uploadStore";
import { useQtyStore } from "../../../store/qtyStore";
import type { PieceQuantityMap } from "../../../types/qty";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  useUploadStore.getState().reset();
  useQtyStore.getState().resetQuantities();
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
  document.body.innerHTML = "";
  useUploadStore.getState().reset();
  useQtyStore.getState().resetQuantities();
});

function renderDialog(): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <PieceQtyDialog />
      </StrictMode>,
    );
  });
  return container!;
}

function setNativeInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("PieceQtyDialog (US-012)", () => {
  it("qtyDialog=null renders empty (no DOM mounted)", () => {
    const el = renderDialog();
    expect(el.querySelector(".piece-qty-dialog-overlay")).toBeNull();
    expect(document.body.querySelector(".piece-qty-dialog-overlay")).toBeNull();
  });

  it("opening renders title with label + sizeLabel (null=universal)", () => {
    useUploadStore.getState().openQtyDialog("A", null);
    renderDialog();
    const title = document.body.querySelector(".piece-qty-dialog-title");
    expect(title).not.toBeNull();
    expect(title!.textContent).toContain("A");
    expect(title!.textContent).toContain("通用");
  });

  it("opening renders title with numeric size label", () => {
    useUploadStore.getState().openQtyDialog("B", 30);
    renderDialog();
    const title = document.body.querySelector(".piece-qty-dialog-title");
    expect(title!.textContent).toContain("B");
    expect(title!.textContent).toContain("30");
  });

  it("initial draftQty from getPieceDisplay (perSize[sizeKey])", () => {
    const map: PieceQuantityMap = {
      A: { perSize: { "30": 5 }, baseValue: 1 },
    };
    useQtyStore.setState({ quantities: map });
    useUploadStore.getState().openQtyDialog("A", 30);
    renderDialog();
    const input = document.body.querySelector(".qty-input") as HTMLInputElement;
    expect(input.value).toBe("5");
  });

  it("[+] [-] buttons change draftQty; [-]@0 disabled", () => {
    useUploadStore.getState().openQtyDialog("A", 30);
    renderDialog();
    const inc = document.body.querySelector(".qty-inc") as HTMLButtonElement;
    const dec = document.body.querySelector(".qty-dec") as HTMLButtonElement;
    const input = document.body.querySelector(".qty-input") as HTMLInputElement;
    expect(dec.disabled).toBe(true);
    act(() => {
      inc.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(input.value).toBe("1");
    expect(dec.disabled).toBe(false);
    act(() => {
      dec.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(input.value).toBe("0");
    expect(dec.disabled).toBe(true);
  });

  it("input change updates draftQty (non-number falls back to 0)", () => {
    useUploadStore.getState().openQtyDialog("A", 30);
    renderDialog();
    const input = document.body.querySelector(".qty-input") as HTMLInputElement;
    act(() => {
      setNativeInputValue(input, "8");
    });
    expect(input.value).toBe("8");
    act(() => {
      setNativeInputValue(input, "abc");
    });
    expect(input.value).toBe("0");
  });

  it("confirm calls setPiecePerSize (仅当前码) + close", () => {
    useUploadStore.getState().openQtyDialog("A", 30);
    renderDialog();
    const inc = document.body.querySelector(".qty-inc") as HTMLButtonElement;
    act(() => {
      inc.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    act(() => {
      inc.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    act(() => {
      inc.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const confirm = document.body.querySelector(".qty-confirm") as HTMLButtonElement;
    act(() => {
      confirm.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const q = useQtyStore.getState().quantities.A;
    expect(q.perSize["30"]).toBe(3);
    expect(useUploadStore.getState().qtyDialog).toBeNull();
  });

  it("cancel button does not write store, only close", () => {
    useQtyStore.getState().setPiecePerSize("A", 30, 5);
    useUploadStore.getState().openQtyDialog("A", 30);
    renderDialog();
    const inc = document.body.querySelector(".qty-inc") as HTMLButtonElement;
    act(() => {
      inc.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const cancel = document.body.querySelector(".qty-cancel") as HTMLButtonElement;
    act(() => {
      cancel.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(useQtyStore.getState().quantities.A.perSize["30"]).toBe(5);
    expect(useUploadStore.getState().qtyDialog).toBeNull();
  });

  it("overlay click closes (draft discarded)", () => {
    useQtyStore.getState().setPiecePerSize("A", 30, 2);
    useUploadStore.getState().openQtyDialog("A", 30);
    renderDialog();
    const overlay = document.body.querySelector(".piece-qty-dialog-overlay") as HTMLDivElement;
    const inc = document.body.querySelector(".qty-inc") as HTMLButtonElement;
    act(() => {
      inc.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    act(() => {
      overlay.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(useUploadStore.getState().qtyDialog).toBeNull();
    expect(useQtyStore.getState().quantities.A.perSize["30"]).toBe(2);
  });

  it("ESC closes dialog (draft discarded)", () => {
    useQtyStore.getState().setPiecePerSize("A", 30, 4);
    useUploadStore.getState().openQtyDialog("A", 30);
    renderDialog();
    const inc = document.body.querySelector(".qty-inc") as HTMLButtonElement;
    act(() => {
      inc.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(useUploadStore.getState().qtyDialog).toBeNull();
    expect(useQtyStore.getState().quantities.A.perSize["30"]).toBe(4);
  });

  it("mousedown inside modal does not bubble-close (modal self-click safe)", () => {
    useUploadStore.getState().openQtyDialog("A", 30);
    renderDialog();
    const modal = document.body.querySelector(".piece-qty-dialog-modal") as HTMLDivElement;
    act(() => {
      modal.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(useUploadStore.getState().qtyDialog).not.toBeNull();
  });

  it("blur clamps draftQty (over 99 -> 99)", () => {
    useUploadStore.getState().openQtyDialog("A", 30);
    renderDialog();
    const input = document.body.querySelector(".qty-input") as HTMLInputElement;
    act(() => {
      setNativeInputValue(input, "150");
    });
    act(() => {
      input.dispatchEvent(new FocusEvent("blur"));
    });
    expect(input.value).toBe("99");
  });
});
