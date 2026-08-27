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
//
// US-021：解析成功自动触发 commit（void commit(doc_id, filename)），成功路径的 fetch
// 调用次数翻倍（parse + commit），且 commit 会写 uiStore（setNestingEnabled，不自动切 Tab）。
// beforeEach/afterEach 加 uiStore reset 防 commit 副作用跨测试污染；fetch 计数断言同步更新。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { useParseDxf } from "../useParseDxf";
import { markSessionProbedForTest } from "../../lib/api";
import { useUploadStore } from "../../store/uploadStore";
import { useUiStore } from "../../store/uiStore";
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
  // US-005：预置「会话已探测」—— apiFetch 不前置 POST /api/session，fetch
  // 计数 / 首调 URL 断言与本 story 前完全一致（会话门自身在 lib/api.test 覆盖）。
  markSessionProbedForTest();
  useUploadStore.getState().reset();
  // US-021：commit 副作用会写 uiStore（setNestingEnabled+setTab），reset 防跨测试污染。
  useUiStore.getState().setNestingEnabled(false);
  useUiStore.getState().setTab("preview");
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
  // US-021：commit 异步 resolve 可能在 afterEach 触发 setTab，reset 防下一个测试污染。
  useUiStore.getState().setNestingEnabled(false);
  useUiStore.getState().setTab("preview");
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
    // US-021：解析成功后自动 commit 触发第二次 fetch（POST /api/commit-to-nesting）。
    expect(fetchSpy).toHaveBeenCalledTimes(2);
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
    // US-021：每次成功 upload 触发 parse + commit 两次 fetch，两次 upload 共 4 次。
    expect(fetchSpy).toHaveBeenCalledTimes(4);
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

// US-021：解析成功自动 commit 集成测试（useParseDxf done -> useCommitToNesting -> D1 闭环）。
// 验证 AC#8 ≥6 项：解析 done 自动触发 commit / commit done 解锁但不切 Tab /
// commit done setNestingEnabled(true) / commit 失败不切 Tab / commit 失败显示 error / 摘要渲染。
//
// fetch mock 用 mockImplementation 路由：parse-dxf 返回 ParsedDoc、commit-to-nesting 返回
// commit summary（或 error），避免 mockResolvedValue 共享 Response 导致 .json() 二次消费问题。
describe("useParseDxf (US-021) auto-commit integration", () => {
  /** 路由 fetch：parse-dxf 返回 ParsedDoc，commit-to-nesting 按 commitInit 返回。 */
  function mockParseAndCommit(
    doc: ParsedDoc = makeDoc(),
    commitInit: { ok?: boolean; status?: number; json?: unknown } = {},
  ): ReturnType<typeof vi.spyOn> {
    const commitJson = commitInit.json ?? {
      doc_id: "deadbeef",
      source: "M1787.dxf",
      sizes: [28, 30, 32],
      n_pieces: 128,
      total_area_mm2: 12345.6,
      reloaded: true,
    };
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (url: URL | string | Request) => {
      const u = typeof url === "string" ? url : url.toString();
      if (u.includes("/api/parse-dxf")) {
        return makeResponse({ json: doc });
      }
      if (u.includes("/api/commit-to-nesting")) {
        return makeResponse(commitInit);
      }
      return makeResponse({ json: commitJson });
    }) as unknown as ReturnType<typeof vi.spyOn>;
  }

  it("AC#8 parse done -> auto-triggers commit with doc.doc_id + doc.filename", async () => {
    const doc = makeDoc([
      { size: 28, pieces: [] },
      { size: 30, pieces: [] },
    ]);
    const fetchSpy = mockParseAndCommit(doc);
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    // Wait for auto-commit to resolve (void commit runs async after parse done)
    await act(async () => {
      await Promise.resolve();
    });
    // 2 fetches: parse-dxf + commit-to-nesting
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(fetchSpy.mock.calls[1][0]).toBe("/api/commit-to-nesting");
    const commitInit = fetchSpy.mock.calls[1][1] as RequestInit;
    const body = JSON.parse(commitInit.body as string) as { doc_id: string; filename: string };
    // doc_id + filename from parsed doc
    expect(body.doc_id).toBe(doc.doc_id);
    expect(body.filename).toBe(doc.filename);
  });

  it("AC#8 commit done -> unlocks nesting tab but does NOT auto-switch (D1)", async () => {
    mockParseAndCommit();
    renderProbe();
    expect(useUiStore.getState().activeTab).toBe("preview");
    await act(async () => {
      await captured!.upload(makeFile());
    });
    // Flush auto-commit async resolution
    await act(async () => {
      await Promise.resolve();
    });
    expect(useUploadStore.getState().status).toBe("done");
    expect(useUploadStore.getState().commitStatus).toBe("done");
    // D1: commit done 解锁超排 Tab，但不自动切入（用户留在预览页主动点击进入）
    expect(useUiStore.getState().nestingEnabled).toBe(true);
    expect(useUiStore.getState().activeTab).toBe("preview");
  });

  it("AC#8 commit done -> setNestingEnabled(true)", async () => {
    mockParseAndCommit();
    renderProbe();
    expect(useUiStore.getState().nestingEnabled).toBe(false);
    await act(async () => {
      await captured!.upload(makeFile());
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(useUiStore.getState().nestingEnabled).toBe(true);
  });

  it("AC#8 commit fail -> does NOT switch tab (user sees error on preview)", async () => {
    mockParseAndCommit(makeDoc(), {
      ok: false,
      status: 422,
      json: { error: "commit failed: no pieces" },
    });
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    await act(async () => {
      await Promise.resolve();
    });
    // Parse succeeded (status=done) but commit failed
    expect(useUploadStore.getState().status).toBe("done");
    expect(useUploadStore.getState().commitStatus).toBe("error");
    // D5: Tab NOT switched (user stays on preview to see commit error)
    expect(useUiStore.getState().activeTab).toBe("preview");
    // nestingEnabled stays true (parse done unlocked it via PreviewPage subscribe;
    // in test without PreviewPage, commit fail path doesn't set it, but D5 says Tab
    // stays unlocked so user can retry or use old data)
  });

  it("AC#8 commit fail -> commitError displayed in store", async () => {
    mockParseAndCommit(makeDoc(), {
      ok: false,
      status: 422,
      json: { error: "commit failed: no pieces" },
    });
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(useUploadStore.getState().commitStatus).toBe("error");
    expect(useUploadStore.getState().commitError).toBe("commit failed: no pieces");
  });

  it("AC#8 commit done -> commitSummary rendered in store (n_pieces + sizes.length)", async () => {
    mockParseAndCommit(makeDoc(), {
      json: {
        doc_id: "deadbeef",
        source: "M1787.dxf",
        sizes: [28, 30],
        n_pieces: 64,
        total_area_mm2: 9999.9,
        reloaded: true,
      },
    });
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    await act(async () => {
      await Promise.resolve();
    });
    const summary = useUploadStore.getState().commitSummary;
    expect(summary).not.toBeNull();
    expect(summary!.n_pieces).toBe(64);
    expect(summary!.sizes.length).toBe(2);
    expect(summary!.total_area_mm2).toBe(9999.9);
  });

  it("AC#8 parse fail -> commit NOT triggered (fetch only once for parse-dxf)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (url: URL | string | Request) => {
      const u = typeof url === "string" ? url : url.toString();
      if (u.includes("/api/parse-dxf")) {
        return makeResponse({ ok: false, status: 422, json: { error: "parse fail" } });
      }
      return makeResponse();
    });
    renderProbe();
    await act(async () => {
      await captured!.upload(makeFile());
    });
    await act(async () => {
      await Promise.resolve();
    });
    // Parse failed: only 1 fetch (parse-dxf), no commit triggered
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(useUploadStore.getState().status).toBe("error");
    expect(useUploadStore.getState().commitStatus).toBe("idle");
  });
});
