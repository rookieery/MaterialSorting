// US-021 useCommitToNesting hook unit tests.
// Mirrors useParseDxf.test.tsx pattern: Probe component captures hook return.
//
// AC#7 >=10 tests:
//   - fetch URL=/api/commit-to-nesting (relative) + method POST + JSON body
//   - 200 -> commitSummary written + commitStatus=done
//   - 422 -> commitError written + commitStatus=error
//   - 404 -> commitError (file not found backend msg)
//   - 400 -> commitError (missing doc_id)
//   - anti-double-click: 2nd commit() during committing silently ignored (fetch once)
//   - doc_id passed through to body; filename optional
//   - commitStatus transition path: idle -> committing -> done
//   - commitStatus transition path: idle -> committing -> error
//   - commit done triggers setNestingEnabled(true) only (no auto setTab) (D1)
//   - network error -> commitStatus=error + commitError=Error.message

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { useCommitToNesting } from "../useCommitToNesting";
import { markSessionProbedForTest } from "../../lib/api";
import { usePtypeStore } from "../../store/ptypeStore";
import { useUploadStore } from "../../store/uploadStore";
import { useUiStore } from "../../store/uiStore";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let captured: ReturnType<typeof useCommitToNesting> | null = null;
function Probe() {
  captured = useCommitToNesting();
  return null;
}

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  // US-005：预置「会话已探测」—— apiFetch 不前置 POST /api/session，fetch
  // 计数 / 首调 URL 断言与本 story 前完全一致（会话门自身在 lib/api.test 覆盖）。
  markSessionProbedForTest();
  useUploadStore.getState().reset();
  usePtypeStore.getState().reset();
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

interface CommitJson {
  doc_id?: string;
  source?: string;
  sizes?: number[];
  n_pieces?: number;
  total_area_mm2?: number;
  reloaded?: boolean;
}

interface ResInit {
  ok?: boolean;
  status?: number;
  statusText?: string;
  json?: CommitJson | { error?: string };
}

function makeCommitResponse(init: ResInit = {}): Response {
  const defaultJson: CommitJson = {
    doc_id: "deadbeef",
    source: "M1787.dxf",
    sizes: [28, 30, 32],
    n_pieces: 128,
    total_area_mm2: 12345.6,
    reloaded: true,
  };
  const r = {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? "OK",
    json: vi.fn(async () => init.json ?? defaultJson),
  };
  return r as unknown as Response;
}

describe("useCommitToNesting (US-021)", () => {
  it("AC#7 fetch URL = /api/commit-to-nesting (relative) + method POST + JSON body", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeCommitResponse());
    renderProbe();
    await act(async () => {
      await captured!.commit("deadbeef", "M1787.dxf");
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/commit-to-nesting");
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string) as { doc_id: string; filename: string };
    expect(body.doc_id).toBe("deadbeef");
    expect(body.filename).toBe("M1787.dxf");
    const headers = (init.headers ?? {}) as Record<string, string>;
    expect(headers["Content-Type"] ?? headers["content-type"]).toBe("application/json");
  });

  it("AC#7 200 -> commitStatus=done + commitSummary written", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(makeCommitResponse());
    renderProbe();
    await act(async () => {
      await captured!.commit("deadbeef");
    });
    const s = useUploadStore.getState();
    expect(s.commitStatus).toBe("done");
    expect(s.commitError).toBeNull();
    expect(s.commitSummary).toEqual({
      sizes: [28, 30, 32],
      n_pieces: 128,
      total_area_mm2: 12345.6,
    });
  });

  it("AC#7 filename optional (body omits filename when undefined)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeCommitResponse());
    renderProbe();
    await act(async () => {
      await captured!.commit("deadbeef");
    });
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string) as { doc_id: string; filename?: string };
    expect(body.doc_id).toBe("deadbeef");
    expect(body.filename).toBeUndefined();
  });

  it("AC#7 422 -> commitStatus=error + commitError=backend msg", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeCommitResponse({
        ok: false,
        status: 422,
        statusText: "Unprocessable Entity",
        json: { error: "commit failed: no pieces" },
      }),
    );
    renderProbe();
    await act(async () => {
      await captured!.commit("deadbeef");
    });
    const s = useUploadStore.getState();
    expect(s.commitStatus).toBe("error");
    expect(s.commitError).toBe("commit failed: no pieces");
    expect(s.commitSummary).toBeNull();
  });

  it("AC#7 404 -> commitError (file not found backend msg)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeCommitResponse({
        ok: false,
        status: 404,
        statusText: "Not Found",
        json: { error: "file not found: deadbeef" },
      }),
    );
    renderProbe();
    await act(async () => {
      const r = await captured!.commit("deadbeef");
      expect(r.ok).toBe(false);
      expect(r.error).toBe("file not found: deadbeef");
    });
    expect(useUploadStore.getState().commitStatus).toBe("error");
  });

  it("AC#7 400 -> commitError (missing doc_id backend msg)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeCommitResponse({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        json: { error: "missing doc_id" },
      }),
    );
    renderProbe();
    await act(async () => {
      await captured!.commit("deadbeef");
    });
    expect(useUploadStore.getState().commitError).toBe("missing doc_id");
  });

  it("AC#7 non-JSON error -> statusText fallback", async () => {
    const res = makeCommitResponse({ ok: false, status: 500, statusText: "Internal Server Error" });
    (res as unknown as { json: () => Promise<never> }).json = async () => {
      throw new SyntaxError("not JSON");
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(res);
    renderProbe();
    await act(async () => {
      await captured!.commit("deadbeef");
    });
    expect(useUploadStore.getState().commitError).toBe("Internal Server Error");
  });

  it("AC#7 anti-double-click: 2nd commit() during committing silently ignored (fetch once)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockReturnValue(
      new Promise<Response>((res) => {
        setTimeout(() => res(makeCommitResponse()), 100000);
      }),
    );
    renderProbe();
    let p2done = false;
    let p2result: { ok: boolean; error?: string } | null = null;
    act(() => {
      void captured!.commit("deadbeef");
      const p2 = captured!.commit("deadbeef");
      p2.then((r) => {
        p2done = true;
        p2result = r;
      });
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(p2done).toBe(true);
    expect(p2result!.ok).toBe(false);
    expect(p2result!.error).toBeTruthy();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("AC#7 committingRef reset after success (next commit works)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(makeCommitResponse());
    renderProbe();
    await act(async () => {
      await captured!.commit("deadbeef");
    });
    expect(useUploadStore.getState().commitStatus).toBe("done");
    await act(async () => {
      await captured!.commit("deadbeef");
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("AC#7 network error (fetch reject) -> commitStatus=error + commitError=Error.message", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    renderProbe();
    await act(async () => {
      const r = await captured!.commit("deadbeef");
      expect(r.ok).toBe(false);
      expect(r.error).toBe("Failed to fetch");
    });
    const s = useUploadStore.getState();
    expect(s.commitStatus).toBe("error");
    expect(s.commitError).toBe("Failed to fetch");
  });

  it("AC#7 commitStatus transition path: idle -> committing -> done", async () => {
    let resolveFn!: (r: Response) => void;
    vi.spyOn(globalThis, "fetch").mockReturnValue(
      new Promise<Response>((res) => {
        resolveFn = res;
      }),
    );
    renderProbe();
    expect(useUploadStore.getState().commitStatus).toBe("idle");
    act(() => {
      void captured!.commit("deadbeef");
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(useUploadStore.getState().commitStatus).toBe("committing");
    await act(async () => {
      resolveFn(makeCommitResponse());
      await Promise.resolve();
    });
    expect(useUploadStore.getState().commitStatus).toBe("done");
  });

  it("AC#7 commitStatus transition path: idle -> committing -> error", async () => {
    let resolveFn!: (r: Response) => void;
    vi.spyOn(globalThis, "fetch").mockReturnValue(
      new Promise<Response>((res) => {
        resolveFn = res;
      }),
    );
    renderProbe();
    act(() => {
      void captured!.commit("deadbeef");
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(useUploadStore.getState().commitStatus).toBe("committing");
    await act(async () => {
      resolveFn(makeCommitResponse({ ok: false, status: 422, json: { error: "fail" } }));
      await Promise.resolve();
    });
    expect(useUploadStore.getState().commitStatus).toBe("error");
  });

  it("AC#7 commit done -> setNestingEnabled(true) but does NOT auto-switch tab (D1)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(makeCommitResponse());
    renderProbe();
    expect(useUiStore.getState().nestingEnabled).toBe(false);
    expect(useUiStore.getState().activeTab).toBe("preview");
    await act(async () => {
      await captured!.commit("deadbeef");
    });
    // commit done 解锁超排 Tab，但不自动切入（用户主动点击进入）
    expect(useUiStore.getState().nestingEnabled).toBe(true);
    expect(useUiStore.getState().activeTab).toBe("preview");
  });

  it("commit done -> ptypeStore invalidate；commit fail 不失效（后端 state 未变，2026-08-25）", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(makeCommitResponse());
    renderProbe();
    // 预置 ready 缓存（模拟弹窗已拉过代表裁片数据）
    usePtypeStore.setState({ status: "ready" });
    await act(async () => {
      await captured!.commit("deadbeef");
    });
    expect(usePtypeStore.getState().status).toBe("idle");
    // 失败路径：后端 _PIECES_STATE 未变 → 缓存保持 ready 不失效
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeCommitResponse({ ok: false, status: 422, json: { error: "commit fail" } }),
    );
    usePtypeStore.setState({ status: "ready" });
    await act(async () => {
      await captured!.commit("deadbeef");
    });
    expect(usePtypeStore.getState().status).toBe("ready");
  });

  it("AC#7 commit fail -> does NOT switch tab (D5: Tab stays, user sees error)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeCommitResponse({ ok: false, status: 422, json: { error: "commit fail" } }),
    );
    renderProbe();
    useUiStore.getState().setNestingEnabled(true);
    expect(useUiStore.getState().activeTab).toBe("preview");
    await act(async () => {
      await captured!.commit("deadbeef");
    });
    expect(useUiStore.getState().activeTab).toBe("preview");
    expect(useUiStore.getState().nestingEnabled).toBe(true);
    expect(useUploadStore.getState().commitStatus).toBe("error");
  });

  it("AC#7 entering committing clears stale commitError + commitSummary", async () => {
    useUploadStore.setState({
      commitStatus: "error",
      commitError: "old error",
      commitSummary: null,
    });
    let resolveFn!: (r: Response) => void;
    vi.spyOn(globalThis, "fetch").mockReturnValue(
      new Promise<Response>((res) => {
        resolveFn = res;
      }),
    );
    renderProbe();
    act(() => {
      void captured!.commit("deadbeef");
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(useUploadStore.getState().commitStatus).toBe("committing");
    expect(useUploadStore.getState().commitError).toBeNull();
    await act(async () => {
      resolveFn(makeCommitResponse());
      await Promise.resolve();
    });
    expect(useUploadStore.getState().commitStatus).toBe("done");
  });
});
