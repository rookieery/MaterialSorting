// US-013 PieceZoomModal integration tests (>=9 cases):
//   AC: zoom=null does not render DOM (no portal content)
//   AC: zoom!==null + doc renders overlay + modal
//   AC: head contains label badge + qty(份) + sizeLabel + name
//   AC: body contains PiecePreviewSVG (svg.piece-preview-svg)
//   AC: close button click calls closeZoom
//   AC: overlay click closes; modal inner click does NOT close (stopPropagation)
//   AC: ESC closes
//   AC: Portal target = document.body (root not inside container)
//   AC: doc=null does not render even if zoom!==null
//   AC: label not found in size -> no render (defensive)

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { PieceZoomModal } from "../PieceZoomModal";
import { useUploadStore } from "../../../store/uploadStore";
import { useQtyStore } from "../../../store/qtyStore";
import type { ParsedDoc, ParsedPiece } from "../../../types/parsed";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

function makePiece(label: string, name: string): ParsedPiece {
  return {
    label,
    name,
    polygon: [
      [0, 0],
      [100, 0],
      [100, 60],
      [0, 60],
    ],
    internal_lines: [],
    notches: [],
    net_polygon: [],
    grain_line: null,
  };
}

const sampleDoc: ParsedDoc = {
  doc_id: "abc123",
  filename: "M1787.dxf",
  sizes: [
    { size: 28, pieces: [makePiece("A", "front..28"), makePiece("B", "back..28")] },
    { size: 30, pieces: [makePiece("A", "front..30"), makePiece("B", "back..30")] },
    { size: null, pieces: [makePiece("C", "universal")] },
  ],
};

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

function renderModal(): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <PieceZoomModal />
      </StrictMode>,
    );
  });
  return container!;
}

describe("PieceZoomModal (US-013)", () => {
  it("zoom=null does not render (no DOM mounted)", () => {
    useUploadStore.setState({ doc: sampleDoc });
    renderModal();
    expect(document.body.querySelector(".piece-zoom-overlay")).toBeNull();
  });

  it("doc=null does not render even if zoom!==null", () => {
    useUploadStore.getState().openZoom("A", 30);
    renderModal();
    expect(document.body.querySelector(".piece-zoom-overlay")).toBeNull();
  });

  it("opening renders overlay + modal with aria-label", () => {
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("A", 30);
    renderModal();
    const overlay = document.body.querySelector(".piece-zoom-overlay");
    const modal = document.body.querySelector(".piece-zoom-modal");
    expect(overlay).not.toBeNull();
    expect(modal).not.toBeNull();
    expect(modal!.getAttribute("aria-label")).toContain("A");
    expect(modal!.getAttribute("aria-label")).toContain("30");
  });

  it("head contains label badge + qty(份) + sizeLabel + name", () => {
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("B", 30);
    renderModal();
    const head = document.body.querySelector(".piece-zoom-head");
    expect(head).not.toBeNull();
    const badge = head!.querySelector(".piece-card-label");
    expect(badge!.textContent).toBe("B");
    const qty = head!.querySelector(".piece-zoom-qty");
    expect(qty!.textContent).toBe("0份");
    const meta = head!.querySelector(".piece-zoom-meta");
    expect(meta!.textContent).toContain("30");
    const name = head!.querySelector(".piece-zoom-name");
    expect(name!.textContent).toContain("back..30");
  });

  it("head shows qty from qtyStore getPieceDisplay", () => {
    useQtyStore.getState().setPiecePerSize("A", 28, 7);
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("A", 28);
    renderModal();
    const qty = document.body.querySelector(".piece-zoom-qty");
    expect(qty!.textContent).toBe("7份");
  });

  it("sizeLabel shows tong-yong (universal) for null size", () => {
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("C", null);
    renderModal();
    const meta = document.body.querySelector(".piece-zoom-meta");
    // 通用 = universal in CN
    expect(meta!.textContent).toContain("通用");
  });

  it("body contains svg.piece-preview-svg (PiecePreviewSVG reused)", () => {
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("A", 30);
    renderModal();
    const body = document.body.querySelector(".piece-zoom-body");
    expect(body).not.toBeNull();
    const svg = body!.querySelector("svg.piece-preview-svg");
    expect(svg).not.toBeNull();
  });

  it("close button click calls closeZoom", () => {
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("A", 30);
    renderModal();
    const closeBtn = document.body.querySelector(".piece-zoom-close") as HTMLButtonElement;
    expect(useUploadStore.getState().zoom).not.toBeNull();
    act(() => {
      closeBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(useUploadStore.getState().zoom).toBeNull();
  });

  it("overlay click closes modal", () => {
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("A", 30);
    renderModal();
    const overlay = document.body.querySelector(".piece-zoom-overlay") as HTMLDivElement;
    act(() => {
      overlay.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(useUploadStore.getState().zoom).toBeNull();
  });

  it("modal inner click does NOT close (stopPropagation)", () => {
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("A", 30);
    renderModal();
    const modal = document.body.querySelector(".piece-zoom-modal") as HTMLDivElement;
    act(() => {
      modal.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(useUploadStore.getState().zoom).not.toBeNull();
  });

  it("ESC closes modal", () => {
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("A", 30);
    renderModal();
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(useUploadStore.getState().zoom).toBeNull();
  });

  it("Portal target = document.body (root not inside container)", () => {
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("A", 30);
    renderModal();
    const overlay = document.body.querySelector(".piece-zoom-overlay");
    expect(overlay).not.toBeNull();
    expect(container!.contains(overlay)).toBe(false);
    expect(document.body.contains(overlay)).toBe(true);
  });

  it("label not found in size -> no render (defensive)", () => {
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("Z", 30);
    renderModal();
    expect(document.body.querySelector(".piece-zoom-overlay")).toBeNull();
  });

  it("size not found in doc -> no render (defensive)", () => {
    useUploadStore.setState({ doc: sampleDoc });
    useUploadStore.getState().openZoom("A", 99);
    renderModal();
    expect(document.body.querySelector(".piece-zoom-overlay")).toBeNull();
  });
});
