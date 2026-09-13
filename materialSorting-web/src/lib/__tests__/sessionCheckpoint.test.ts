// 会话过期自动恢复 US-004 单测：自动 checkpoint 调度（去抖合并 / hidden 立即 /
// doc 空跳过 / 求解完成立即 / 编辑保存立即 / pagehide keepalive / 阻断吞错）+
// 启动清理时序（存活 DELETE / 401 恢复不清 / 阻断不清）。
//
// 本文件 import '../sessionCheckpoint' 即完成接线（生产 = App.tsx 静态 import，
// 同一装载副作用）；import '../sessionRecovery' 注册恢复钩子（401 时序用例走真实
// ensureSession 分支）。监听器是模块单例 —— resetCheckpointForTest 清定时器与
// 串行链（置于 store 复位**之后**：qtyStore.resetQuantities 换 quantities 引用会
// 触发一次调度，须清掉防跨用例污染）。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SESSION_HEADER,
  probeSession,
  resetSessionForTest,
  markSessionProbedForTest,
  triggerSessionBlock,
} from '../api';
import { resetSessionIdForTest } from '../session';
import '../sessionRecovery';
import {
  CHECKPOINT_DEBOUNCE_MS,
  clearCheckpointAfterProbe,
  resetCheckpointForTest,
} from '../sessionCheckpoint';
import { useEditStore } from '../../store/editStore';
import { useFormStore } from '../../store/formStore';
import { useQtyStore } from '../../store/qtyStore';
import { markRunDone, runRegistry, type RunRecord } from '../../store/runRegistry';
import { useExtremeStore, useStrategyStore } from '../../store/strategyStore';
import { useUploadStore } from '../../store/uploadStore';
import type { ParsedDoc } from '../../types/parsed';
import type { FrameMsg, ManifestMsg } from '../../types/ws';

const URL_CP = '/api/state-checkpoint';

/** 过期旧 sid（合法 32-hex，预置 localStorage 模拟「刷新前已持有」）。 */
const OLD_SID = '0123456789abcdef0123456789abcdef';

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

/** 已解析 doc 夹具（上传完成口径：doc 非空 = 有可 checkpoint 的工作台）。 */
function makeDoc(): ParsedDoc {
  return {
    doc_id: 'cp-test-doc',
    filename: 'M1787.dxf',
    sizes: [
      {
        size: 30,
        pieces: [
          { label: 'g01', polygon: [], internal_lines: [], notches: [], net_polygon: [], grain_line: null },
        ],
      },
    ],
  };
}

function setDoc(): void {
  useUploadStore.setState({ status: 'done', doc: makeDoc(), activeSize: 30 });
}

/** 造一条带终局帧的 RunRecord（不置 done —— 由用例 markRunDone 驱动观察者）。 */
function makeRun(seed: number, density: number): RunRecord {
  const rec = runRegistry.create(seed);
  rec.manifest = {
    type: 'manifest',
    gate_mm: 1750,
    total_area_mm2: 500000,
    n_eroded: 0,
    pieces: [],
  } as ManifestMsg;
  const frame: FrameMsg = {
    type: 'frame',
    index: 0,
    elapsed: 1,
    phase: 'final',
    density,
    density_sparrow: density,
    width_mm: 1000,
    placed_items: [{ id: 'g01_30', rotation: 0, translation: [1, 2] }],
  };
  rec.frames.push(frame);
  rec.lastFrame = frame;
  rec.finalDensity = density;
  rec.finalDensitySparrow = density;
  rec.viewBoxMaxW = frame.width_mm;
  return rec;
}

/** 真实定时器下的微任务排空（立即 flush 断言用：一个宏任务足够 drain promise 链）。 */
function tick(): Promise<void> {
  return new Promise((r) => setTimeout(r, 0));
}

/** 恢复响应夹具（含 run 块 → applyRestorePayload 合成 done run → 触发 checkpoint）。 */
function makeRestoreBody() {
  const piece = {
    label: 'g01',
    polygon: [],
    internal_lines: [],
    notches: [],
    net_polygon: [],
    grain_line: null,
  };
  const fin = {
    density: 0.7,
    density_sparrow: 0.68,
    width_mm: 5000,
    elapsed: 10,
    n_frames: 1,
    n_eroded: 0,
  };
  const placed = [{ id: 'g01_30', rotation: 0, translation: [10, 20] }];
  return {
    doc_id: 'recovered-doc-1',
    filename: 'M1787.dxf',
    parse: { doc_id: 'recovered-doc-1', filename: 'M1787.dxf', sizes: [{ size: 30, pieces: [piece] }] },
    manifest: { gate_mm: 1750, total_area_mm2: 500000, n_eroded: 0, pieces: [] },
    final: fin,
    placed,
    run: { seed: 7, final: fin, placed },
    form: { sizes: [30], gate: '175.00' },
    quantities: { g01: { '30': 3 } },
    quantities_base: null,
  };
}

interface RouteOpts {
  probeOld?: () => Response;
  recover?: () => Response;
}

/** URL 路由 mock：/api/session 旧 sid 401（可选）/ recover（可选）/ 其余 200。 */
function mockRoute(opts: RouteOpts = {}) {
  return vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation((((input: unknown, init?: RequestInit) => {
      const url = String(input);
      const headers = (init?.headers ?? {}) as Record<string, string>;
      const sid = headers[SESSION_HEADER] ?? headers['x-session-id'] ?? '';
      if (url.includes('/api/state-recover')) {
        return Promise.resolve(opts.recover ? opts.recover() : json(makeRestoreBody()));
      }
      if (url.includes('/api/session')) {
        if (opts.probeOld && sid === OLD_SID) return Promise.resolve(opts.probeOld());
        return Promise.resolve(json({ ok: true }));
      }
      return Promise.resolve(json({ stored: true }));
    }) as unknown as typeof fetch));
}

function cpPosts(calls: unknown[][]): unknown[][] {
  return calls.filter((c) => String(c[0]) === URL_CP && ((c[1] as RequestInit)?.method ?? '') !== 'DELETE');
}
function cpDeletes(calls: unknown[][]): unknown[][] {
  return calls.filter((c) => String(c[0]) === URL_CP && (c[1] as RequestInit)?.method === 'DELETE');
}

beforeEach(() => {
  localStorage.clear();
  resetSessionIdForTest();
  resetSessionForTest();
  markSessionProbedForTest(); // 默认跳过探测（仅启动清理时序用例真实探测）
  useFormStore.getState().reset();
  useQtyStore.getState().resetQuantities();
  runRegistry.clear();
  useUploadStore.getState().reset();
  useEditStore.getState().invalidate();
  useStrategyStore.getState().reset();
  useExtremeStore.getState().reset();
  // store 复位触发的调度（resetQuantities 换引用）在此清掉 —— 防跨用例定时器污染。
  resetCheckpointForTest();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
  resetCheckpointForTest();
  localStorage.clear();
  resetSessionIdForTest();
  resetSessionForTest();
});

describe('去抖调度（formStore / qtyStore 变更订阅）', () => {
  it('窗口内多次变更合并为一发；载荷 = 发送时刻最新状态且不带 save_as', async () => {
    vi.useFakeTimers();
    const spy = mockRoute();
    setDoc();

    useQtyStore.getState().setPiecePerSize('g01', 30, 2);
    useQtyStore.getState().setPiecePerSize('g01', 30, 5);
    useFormStore.getState().patch({ gate: '176.00' });
    useQtyStore.getState().setPiecePerSize('g01', 30, 7);

    await vi.advanceTimersByTimeAsync(CHECKPOINT_DEBOUNCE_MS - 1);
    expect(cpPosts(spy.mock.calls).length).toBe(0); // 窗口内未发（合并中）

    await vi.advanceTimersByTimeAsync(1);
    const posts = cpPosts(spy.mock.calls);
    expect(posts.length).toBe(1); // 4 次变更 → 恰 1 发
    const init = posts[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    const body = JSON.parse(String(init.body));
    expect(body.quantities.g01['30']).toBe(7); // 最新值（非中间值）
    expect(body.form.gate).toBe('176.00');
    expect('save_as' in body).toBe(false); // 不带 save_as（PRD 指定）
  });

  it('重排窗口：上一发之后再变更 → 第二发（去抖可再触发）', async () => {
    vi.useFakeTimers();
    const spy = mockRoute();
    setDoc();

    useQtyStore.getState().setPiecePerSize('g01', 30, 2);
    await vi.advanceTimersByTimeAsync(CHECKPOINT_DEBOUNCE_MS + 10);
    expect(cpPosts(spy.mock.calls).length).toBe(1);

    useQtyStore.getState().setPiecePerSize('g01', 30, 9);
    await vi.advanceTimersByTimeAsync(CHECKPOINT_DEBOUNCE_MS + 10);
    expect(cpPosts(spy.mock.calls).length).toBe(2);
  });

  it('后端 empty 响应容忍：200 {stored:false} 不报错不重试', async () => {
    vi.useFakeTimers();
    const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
      Promise.resolve(json({ stored: false, reason: 'empty' })),
    );
    setDoc();
    useQtyStore.getState().setPiecePerSize('g01', 30, 2);
    await vi.advanceTimersByTimeAsync(CHECKPOINT_DEBOUNCE_MS + 10);
    expect(cpPosts(spy.mock.calls).length).toBe(1); // 发出且不抛
    await vi.advanceTimersByTimeAsync(10_000); // 无新变更 → 无重试风暴
    expect(cpPosts(spy.mock.calls).length).toBe(1);
  });
});

describe('doc 空跳过（未 commit 无工作台）', () => {
  it('无 doc：变更 + 去抖到期 + hidden → 全程零请求', async () => {
    vi.useFakeTimers();
    const spy = mockRoute();
    // 不 setDoc（uploadStore 处于 idle / doc=null）。
    useQtyStore.getState().setPiecePerSize('g01', 30, 2);
    await vi.advanceTimersByTimeAsync(CHECKPOINT_DEBOUNCE_MS + 10);
    expect(spy.mock.calls.length).toBe(0);
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(10);
    expect(spy.mock.calls.length).toBe(0);
  });
});

describe('hidden 立即 flush 清空去抖', () => {
  it('visibilitychange hidden → 立即一发（不待去抖到期）且去抖已清（不再补发）', async () => {
    vi.useFakeTimers();
    const spy = mockRoute();
    setDoc();
    useQtyStore.getState().setPiecePerSize('g01', 30, 2);

    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0); // 只排微任务，不推进去抖时钟

    expect(cpPosts(spy.mock.calls).length).toBe(1); // 立即落
    await vi.advanceTimersByTimeAsync(CHECKPOINT_DEBOUNCE_MS + 10);
    expect(cpPosts(spy.mock.calls).length).toBe(1); // 旧去抖已清，不补发
  });

  it('visible 不触发（仅 hidden 落）', async () => {
    vi.useFakeTimers();
    const spy = mockRoute();
    setDoc();
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(10);
    expect(spy.mock.calls.length).toBe(0);
  });
});

describe('求解完成立即 checkpoint（markRunDone 观察者）', () => {
  it('bestRun 达 done → 立即一发（不等去抖）；载荷含 run 块', async () => {
    const spy = mockRoute();
    setDoc();
    const rec = makeRun(42, 0.8);
    markRunDone(rec);
    await tick();
    const posts = cpPosts(spy.mock.calls);
    expect(posts.length).toBe(1);
    const body = JSON.parse(String((posts[0][1] as RequestInit).body));
    expect(body.run.seed).toBe(42);
    expect(body.run.placed[0].id).toBe('g01_30');
  });

  it('晚到的非 best run → 跳过（内容无增量）；更优 run → 再发', async () => {
    const spy = mockRoute();
    setDoc();
    markRunDone(makeRun(1, 0.8));
    await tick();
    expect(cpPosts(spy.mock.calls).length).toBe(1);

    markRunDone(makeRun(2, 0.5)); // 更差 —— 不发
    await tick();
    expect(cpPosts(spy.mock.calls).length).toBe(1);

    markRunDone(makeRun(3, 0.9)); // 更优 —— 发
    await tick();
    expect(cpPosts(spy.mock.calls).length).toBe(2);
  });

  it('error/onclose 无帧 run → 不发（无新价值）', async () => {
    const spy = mockRoute();
    setDoc();
    const rec = runRegistry.create(9); // 无 lastFrame（error 直收）
    rec.error = 'boom';
    markRunDone(rec);
    await tick();
    expect(cpPosts(spy.mock.calls).length).toBe(0);
  });
});

describe('编辑保存立即 checkpoint（editStore.save 写序识别）', () => {
  it('open → 改草稿 → save() → 立即一发；拖草稿 / 重开不误触', async () => {
    const spy = mockRoute();
    setDoc();
    const rec = makeRun(7, 0.8);
    markRunDone(rec);
    await tick();
    expect(cpPosts(spy.mock.calls).length).toBe(1); // 求解完成那一发

    expect(useEditStore.getState().open(rec)).toBe(true);
    useEditStore.getState().setWorkingItem(0, { translation: [50, 60] });
    await tick();
    expect(cpPosts(spy.mock.calls).length).toBe(1); // 拖草稿不发（保存才落）

    expect(useEditStore.getState().save()).toBe(true);
    await tick();
    expect(cpPosts(spy.mock.calls).length).toBe(2); // save 落定 → 立即
    const body = JSON.parse(String((cpPosts(spy.mock.calls)[1][1] as RequestInit).body));
    expect(body.run.placed[0].translation).toEqual([50, 60]); // 编辑后布局入快照

    // 重开同一 run（savedDirty 已 true）—— 不误触。
    expect(useEditStore.getState().open(rec)).toBe(true);
    await tick();
    expect(cpPosts(spy.mock.calls).length).toBe(2);
  });
});

describe('pagehide best-effort（keepalive）', () => {
  it('卸载 → 同步发起 keepalive POST（载荷在场）', async () => {
    const spy = mockRoute();
    setDoc();
    useQtyStore.getState().setPiecePerSize('g01', 30, 3);
    window.dispatchEvent(new Event('pagehide'));
    const posts = cpPosts(spy.mock.calls);
    expect(posts.length).toBe(1);
    const init = posts[0][1] as RequestInit & { keepalive?: boolean };
    expect(init.keepalive).toBe(true);
    expect(JSON.parse(String(init.body)).quantities.g01['30']).toBe(3);
  });

  it('阻断期卸载 → 不发（blocked 闸）', async () => {
    const spy = mockRoute();
    setDoc();
    triggerSessionBlock('session_limit');
    window.dispatchEvent(new Event('pagehide'));
    expect(cpPosts(spy.mock.calls).length).toBe(0);
  });
});

describe('阻断吞错（停留期过期后调度静默）', () => {
  it('blocked + 变更 + 去抖到期 → 零请求（apiFetch 同步拦截、无未处理拒绝）', async () => {
    vi.useFakeTimers();
    const spy = mockRoute();
    setDoc();
    triggerSessionBlock('session_limit');
    useQtyStore.getState().setPiecePerSize('g01', 30, 2);
    await vi.advanceTimersByTimeAsync(CHECKPOINT_DEBOUNCE_MS + 10);
    expect(spy.mock.calls.length).toBe(0); // 请求不发出
  });
});

describe('策略/极限 done 结果落定与应用立即 checkpoint（US-002 pending 槽）', () => {
  /** done result 夹具（strategy 族 race）。 */
  function pendingResult() {
    return {
      state: 'done' as const,
      mode: 'race' as const,
      run_dir: 'out/config_runs/web_race_x_1',
      manifest: { gate_mm: 1750, total_area_mm2: 500000, n_eroded: 0, pieces: [] },
      best: {
        seed: 7, frame_index: 42, elapsed: 311.2, density: 0.861,
        density_sparrow: 0.843, width_mm: 7310.5,
        placed_items: [{ id: 'g01_30', rotation: 0, translation: [10, 20] as [number, number] }],
      },
      summary: { per_seed: [], mode: 'race' as const },
    };
  }

  it('done 结果拉取落定（result null→非空）→ 立即一发且载荷含 pending_strategy_result', async () => {
    const spy = mockRoute();
    setDoc();

    // refresh 内部 set({result}) 同构：null→非空即价值最高时刻
    useStrategyStore.setState({ phase: 'done', result: pendingResult(), resultApplied: false });
    await tick();

    const posts = cpPosts(spy.mock.calls);
    expect(posts.length).toBe(1); // 立即（不等去抖 —— 无变更无定时器）
    const body = JSON.parse(String((posts[0][1] as RequestInit).body));
    expect(body.pending_strategy_result.mode).toBe('race');
    expect(body.pending_strategy_result.best.placed_items[0].id).toBe('g01_30');
    expect(body.pending_strategy_result.best.placed_items[0].translation).toEqual([10, 20]);
  });

  it('应用落定（resultApplied false→true）→ 立即一发且载荷不含该槽（已应用由 run 块承载）', async () => {
    const spy = mockRoute();
    setDoc();
    useStrategyStore.setState({ phase: 'done', result: pendingResult(), resultApplied: false });
    await tick(); // 落定那一发
    expect(cpPosts(spy.mock.calls).length).toBe(1);

    useStrategyStore.getState().markResultApplied();
    await tick();
    const posts = cpPosts(spy.mock.calls);
    expect(posts.length).toBe(2);
    const body = JSON.parse(String((posts[1][1] as RequestInit).body));
    expect('pending_strategy_result' in body).toBe(false);
  });

  it('应用全链合并：markRunDone + markResultApplied 同任务 → 恰一发（sendQueued 合并语义）', async () => {
    const spy = mockRoute();
    setDoc();
    useStrategyStore.setState({ phase: 'done', result: pendingResult(), resultApplied: false });

    // applyStrategyResult 内部时序同构：applySyntheticRun（→markRunDone）后置位
    const rec = makeRun(7, 0.861);
    markRunDone(rec);
    useStrategyStore.getState().markResultApplied();
    await tick();

    const posts = cpPosts(spy.mock.calls);
    expect(posts.length).toBe(1); // 两个触发面合并为一发
    const body = JSON.parse(String((posts[0][1] as RequestInit).body));
    expect('pending_strategy_result' in body).toBe(false); // 载荷发送时刻现取：槽已退
    expect(body.run.seed).toBe(7); // run 块已入
  });

  it('无 result 的既有口径对拍：变更去抖载荷无该键（旧文件零迁移）', async () => {
    vi.useFakeTimers();
    const spy = mockRoute();
    setDoc();
    useQtyStore.getState().setPiecePerSize('g01', 30, 2);
    await vi.advanceTimersByTimeAsync(CHECKPOINT_DEBOUNCE_MS + 10);
    const posts = cpPosts(spy.mock.calls);
    expect(posts.length).toBe(1);
    expect('pending_strategy_result' in JSON.parse(String((posts[0][1] as RequestInit).body))).toBe(false);
  });

  it('start/reset 清 result（非空→null）不触发；极限族 result 同触发', async () => {
    const spy = mockRoute();
    setDoc();

    useExtremeStore.setState({ phase: 'done', result: { ...pendingResult(), mode: 'extreme' }, resultApplied: false });
    await tick();
    expect(cpPosts(spy.mock.calls).length).toBe(1); // 极限族落定同发

    useExtremeStore.getState().reset(); // result 清（不触发）
    await tick();
    expect(cpPosts(spy.mock.calls).length).toBe(1);
  });
});

describe('启动清理时序（clearCheckpointAfterProbe，US-004 AC）', () => {
  it('会话存活 → DELETE 已发（F5 = 干净重置）', async () => {
    resetSessionForTest(); // 撤销 markSessionProbedForTest —— 真实探测
    const spy = mockRoute();
    await probeSession();
    await clearCheckpointAfterProbe();
    const dels = cpDeletes(spy.mock.calls);
    expect(dels.length).toBe(1);
    expect((dels[0][1] as RequestInit).method).toBe('DELETE');
  });

  it('探测 401 → 恢复分支跑过 → 不清（留给恢复消费）+ 恢复态重落 checkpoint', async () => {
    resetSessionForTest();
    localStorage.setItem('ms_sid', OLD_SID);
    resetSessionIdForTest();
    const spy = mockRoute({
      probeOld: () => json({ code: 'session_expired', error: '会话已过期' }, 401),
    });

    await probeSession();
    await clearCheckpointAfterProbe();
    await tick(); // 排队中的恢复态 checkpoint（applySyntheticRun → markRunDone）落地

    expect(cpDeletes(spy.mock.calls).length).toBe(0); // 不清 —— 快照留给恢复
    // 恢复完成即在新会话重落快照（合成 run 达 done → 立即 checkpoint）。
    const posts = cpPosts(spy.mock.calls);
    expect(posts.length).toBe(1);
    const body = JSON.parse(String((posts[0][1] as RequestInit).body));
    expect(body.run.seed).toBe(7);
  });

  it('已阻断（429 满员）→ 不清（名额腾出后刷新可再恢复）', async () => {
    markSessionProbedForTest();
    triggerSessionBlock('session_limit');
    const spy = mockRoute();
    await clearCheckpointAfterProbe();
    expect(spy.mock.calls.length).toBe(0);
  });
});
