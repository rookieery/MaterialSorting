// 编辑排料会话钉住心跳单测（2026-09-04）：编辑弹窗纯前端无任何请求，后端
// MS_SESSION_TTL_SEC（缺省 10min）空闲过期会在长编辑中逐出会话 → 保存后导出
// 401 全局阻断 → 刷新丢全部编辑成果。弹窗打开期间须滚动续期 POST /api/edit-hold
// （4min 间隔；后端 2h 钉住 + 关窗后自然宽限，镜像高级运行语义）：
//   1) mount 立即一次 + 每 4min 滚动续期（8min = 累计 3 次）；
//   2) 关窗（closeModal）→ interval 清理，不再发请求；
//   3) 失败静默：网络错不炸 UI、后续心跳照常（lib/editHold catch 契约）。
//
// 只 mock lib/api 的 apiFetch（真实 refreshEditHold + 真实 modal effect 走通）；
// fake timers 驱动 setInterval，不依赖真实墙钟。fixture 同 EditLayoutModal.test。

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditLayoutModal } from '../EditLayoutModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { useEditStore } from '../../../store/editStore';
import { runRegistry, type RunRecord } from '../../../store/runRegistry';
import type { FrameMsg, ManifestMsg } from '../../../types/ws';

vi.mock('../../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  apiFetch: vi.fn(),
}));

import { apiFetch } from '../../../lib/api';

const apiFetchMock = vi.mocked(apiFetch);

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

// ---- fixture：同 EditLayoutModal.test（gate 1000 · a/b 两 500×500 方）----

function makeManifest(): ManifestMsg {
  return {
    type: 'manifest',
    gate_mm: 1000,
    total_area_mm2: 500000,
    n_eroded: 0,
    pieces: [
      {
        id: 'a_28',
        label: 'g01',
        size: 28,
        color: '#ff0000',
        area_mm2: 250000,
        polygon: [[0, 0], [500, 0], [500, 500], [0, 500]],
        net_polygon: [[50, 50], [450, 50], [450, 450], [50, 450]],
      },
      {
        id: 'b_30',
        label: 'g02',
        size: 30,
        color: '#00ff00',
        area_mm2: 250000,
        polygon: [[0, 0], [500, 0], [500, 500], [0, 500]],
      },
    ],
  };
}

function seedBestRun(): RunRecord {
  const run = runRegistry.create(0);
  run.manifest = makeManifest();
  const density = 500000 / (1100 * 1000);
  const frame: FrameMsg = {
    type: 'frame',
    index: 0,
    elapsed: 1,
    phase: 'final',
    density,
    density_sparrow: 0.5,
    width_mm: 1100,
    placed_items: [
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 0, translation: [600, 0] },
    ],
  };
  run.frames.push(frame);
  run.lastFrame = frame;
  run.finalDensity = density;
  run.done = true;
  return run;
}

/** 开编辑弹窗（渲染 + openModal，async act 冲微任务）。 */
async function openEditLayout(): Promise<void> {
  seedBestRun();
  await act(async () => {
    root!.render(<EditLayoutModal />);
    useControlPanelStore.getState().openModal('edit_layout');
  });
}

/** 到 /api/edit-hold 的调用次数（本组件树唯一 apiFetch 消费点）。 */
function holdCalls(): number {
  return apiFetchMock.mock.calls.filter(([url]) => url === '/api/edit-hold').length;
}

function overlay(): HTMLElement | null {
  return document.querySelector('[data-testid="edit-layout-overlay"]');
}

beforeEach(() => {
  vi.useFakeTimers();
  apiFetchMock.mockReset().mockResolvedValue(undefined as unknown as Response);
  runRegistry.clear();
  useEditStore.getState().invalidate();
  useControlPanelStore.getState().closeModal();
  (window as unknown as { PointerEvent?: unknown }).PointerEvent = class extends MouseEvent {};
  container = document.createElement('div');
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
  runRegistry.clear();
  useEditStore.getState().invalidate();
  useControlPanelStore.getState().closeModal();
  vi.useRealTimers();
});

describe('EditLayoutModal 会话钉住心跳 (2026-09-04)', () => {
  it('mount 立即续期一次，之后每 4min 滚动续期（POST /api/edit-hold）', async () => {
    await openEditLayout();
    expect(holdCalls()).toBe(1);
    expect(apiFetchMock.mock.calls[0][1]).toEqual({ method: 'POST' });
    await act(async () => {
      vi.advanceTimersByTime(4 * 60 * 1000);
    });
    expect(holdCalls()).toBe(2);
    await act(async () => {
      vi.advanceTimersByTime(8 * 60 * 1000); // 再过 8min = 2 个 tick
    });
    expect(holdCalls()).toBe(4);
    expect(overlay()).not.toBeNull(); // 弹窗仍在（心跳不打扰 UI）
  });

  it('关窗（closeModal）→ interval 清理，此后不再续期', async () => {
    await openEditLayout();
    expect(holdCalls()).toBe(1);
    await act(async () => {
      useControlPanelStore.getState().closeModal();
    });
    await act(async () => {
      vi.advanceTimersByTime(20 * 60 * 1000);
    });
    expect(holdCalls()).toBe(1); // 关窗后零新增（残留最后一次心跳的 2h 宽限 = 后端语义）
  });

  it('失败静默：apiFetch 抛错不炸 UI，后续心跳照常', async () => {
    apiFetchMock.mockRejectedValueOnce(new Error('网络抖动'));
    await openEditLayout();
    expect(overlay()).not.toBeNull(); // catch 契约：无未处理拒绝、弹窗正常
    await act(async () => {
      vi.advanceTimersByTime(4 * 60 * 1000);
    });
    expect(holdCalls()).toBe(2); // 上一拍失败不中断后续续期
  });
});
