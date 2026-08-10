// US-005 useParseDxf hook unit tests.
// Mirrors useExport.test.tsx pattern: Probe component captures hook return.
//
// AC#1 fetch URL=/api/parse-dxf (relative) + method POST + body=FormData(file)
// AC#2 200 -> status=done / doc written / activeSize = sizes[0].size (smallest)
// AC#2 empty sizes -> activeSize=null ; single null group -> activeSize=null
// AC#3 400/413/422 -> status=error / error=backend JSON.error (CN msg)
// AC#3 non-JSON error -> statusText fallback ; network error -> Error.message
// AC#4 anti-double-click: 2nd upload() during uploading silently ignored
// AC#4 uploadingRef resets after success/failure (next upload works)

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { useParseDxf } from "../useParseDxf";
import { useUploadStore } from "../../store/uploadStore";
import type { ParsedDoc } from "../../types/parsed";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let captured: ReturnType<typeof useParseDxf> | null = null;
function Probe() {
  captured = useParseDxf();
  return null;
}

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  useUploadStore.getState().reset();
  captured = null;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) {
    const r = root;
    act(() => { r.unmount(); });
    root = null;
  }
  container?.remove();
  container = null;
  useUploadStore.getState().reset();
  vi.restoreAllMocks();
});

function renderProbe() {
  act(() => {
    root!.render(
      <StrictMode>
        <Probe />
      </StrictMode>,
    );
  });
}

function makeDoc(sizes: { size: number | null; pieces: unknown[] }[] = [{ size: 28, pieces: [] }]): ParsedDoc {
  return {
    doc_id: "deadbeef",
    filename: "M1787.dxf",
    sizes: sizes as ParsedDoc["sizes"],
  };
}

interface ResInit {
  ok?: boolean;
  status?: number;
  statusText?: string;
  json?: unknown;
}

function makeResponse(init: ResInit = {}): Response {
  const r = {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? "OK",
    json: vi.fn(async () => init.json ?? makeDoc()),
  };
  return r as unknown as Response;
}

function makeFile(name = "M1787.dxf"): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: "application/dxf" });
}

describe("useParseDxf (US-005)", () => {
  it("AC#1 fetch URL = /api/parse-dxf (relative) + method POST", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse());
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/parse-dxf");
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
  });

  it("AC#1 body is FormData with file field (no manual Content-Type)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse());
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile("foo.dxf"));
    });
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    const fd = init.body as FormData;
    const file = fd.get("file");
    expect(file).toBeInstanceOf(File);
    expect((file as File).name).toBe("foo.dxf");
    // Content-Type must NOT be set manually - browser needs to add boundary
    const headers = (init.headers ?? {}) as Record<string, string>;
    expect(headers["Content-Type"] ?? headers["content-type"]).toBeUndefined();
  });

  it("AC#2 200 -> status=done / doc written / activeSize=sizes[0].size", async () => {
    const doc = makeDoc([
      { size: 28, pieces: [] },
      { size: 30, pieces: [] },
      { size: 32, pieces: [] },
    ]);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse({ json: doc }));
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    const s = useUploadStore.getState();
    expect(s.status).toBe("done");
    expect(s.doc).toEqual(doc);
    // backend sorts numerically ascending; sizes[0]=28 is the smallest size
    expect(s.activeSize).toBe(28);
    expect(s.error).toBeNull();
  });

  it("AC#2 empty sizes (anomaly but valid) -> activeSize=null", async () => {
    const doc = makeDoc([]);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse({ json: doc }));
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    const s = useUploadStore.getState();
    expect(s.status).toBe("done");
    expect(s.doc).toEqual(doc);
    expect(s.activeSize).toBeNull();
  });

  it("AC#2 single null size group -> activeSize=null", async () => {
    const doc = makeDoc([{ size: null, pieces: [] }]);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse({ json: doc }));
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(useUploadStore.getState().activeSize).toBeNull();
  });

  it("AC#3 400 -> status=error / error=backend JSON.error (.dxf-only msg)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeResponse({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        json: { error: "仅支持 .dxf 文件" },
      }),
    );
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile("foo.txt"));
    });
    const s = useUploadStore.getState();
    expect(s.status).toBe("error");
    expect(s.error).toBe("仅支持 .dxf 文件");
    expect(s.doc).toBeNull();
  });

  it("AC#3 413 -> status=error / error=oversize msg", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeResponse({
        ok: false,
        status: 413,
        statusText: "Payload Too Large",
        json: { error: "文件大小超过上限 20MB" },
      }),
    );
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(useUploadStore.getState().status).toBe("error");
    expect(useUploadStore.getState().error).toBe("文件大小超过上限 20MB");
  });

  it("AC#3 422 -> status=error / error=parse failure msg", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeResponse({
        ok: false,
        status: 422,
        statusText: "Unprocessable Entity",
        json: { error: "DXF 解析失败：缺少 ENTITIES 段" },
      }),
    );
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(useUploadStore.getState().status).toBe("error");
    expect(useUploadStore.getState().error).toBe("DXF 解析失败：缺少 ENTITIES 段");
  });

  it("AC#3 non-JSON error response -> statusText fallback", async () => {
    const res = makeResponse({ ok: false, status: 500, statusText: "Internal Server Error" });
    (res as unknown as { json: () => Promise<never> }).json = async () => {
      throw new SyntaxError("not JSON");
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(res);
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(useUploadStore.getState().status).toBe("error");
    expect(useUploadStore.getState().error).toBe("Internal Server Error");
  });

  it("AC#3 network error (fetch reject) -> status=error / error=Error.message", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(useUploadStore.getState().status).toBe("error");
    expect(useUploadStore.getState().error).toBe("Failed to fetch");
  });

  it("AC#3 fetch reject non-Error -> error=String(e)", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue("network down");
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(useUploadStore.getState().status).toBe("error");
    expect(useUploadStore.getState().error).toBe("network down");
  });

  it("AC#4 anti-double-click: 2nd upload() during uploading silently ignored (fetch once)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockReturnValue(
      new Promise<Response>((res) => {
        // Never resolves proactively - keeps status=uploading
        setTimeout(() => res(makeResponse()), 100000);
      }),
    );
    renderProbe();
    let p2done = false;
    act(() => {
      void captured!.upload(makeFile());
      const p2 = captured!.upload(makeFile());
      p2.then(() => { p2done = true; });
    });
    // Flush microtasks so the 2nd upload hits the ref guard
    await act(async () => {
      await Promise.resolve();
    });
    expect(p2done).toBe(true);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("AC#4 uploadingRef reset after success (next upload works)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeResponse());
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(useUploadStore.getState().status).toBe("done");
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("AC#4 uploadingRef reset after failure (next upload works)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeResponse({ ok: false, status: 400, json: { error: "bad" } }),
    );
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(useUploadStore.getState().status).toBe("error");
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("AC#4 entering uploading clears stale error (no UI red-text residue)", async () => {
    // First call: fails leaving an error
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      makeResponse({ ok: false, status: 400, json: { error: "first fail" } }),
    );
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    expect(useUploadStore.getState().error).toBe("first fail");
    // Second call: error should be cleared when entering uploading
    let resolveRes!: (r: Response) => void;
    vi.spyOn(globalThis, "fetch").mockReturnValue(
      new Promise<Response>((res) => {
        resolveRes = res;
      }),
    );
    act(() => {
      void captured!.upload(makeFile());
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(useUploadStore.getState().status).toBe("uploading");
    expect(useUploadStore.getState().error).toBeNull();
    // Resolve the pending request so afterEach doesn't see a hanging promise
    await act(async () => {
      resolveRes(makeResponse());
      await Promise.resolve();
    });
  });
});
