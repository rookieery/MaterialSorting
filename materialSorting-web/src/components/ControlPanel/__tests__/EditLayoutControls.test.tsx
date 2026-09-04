// 编辑排料 US-004 EditLayoutControls 单测（主面板「编辑排料」区块）：
//   1) 结构：.field-label 标题「编辑排料」+ 编辑/重置两按钮
//   2) 激活口径与导出按钮一致：registry 存在 lastFrame run（含 stopped best-so-far
//      与策略/极限合成 record —— 均 lastFrame 非空零改动命中）&& phase!=='running'；
//      无结果 / running 态两按钮 disabled
//   3) renderTick 订阅：registry 置帧后 bump → disabled 解除（ExportButtons 同款）
//   4) 三层 disabled 防御：native disabled（一层）+ onClick guard（二层，删属性旁路
//      点击仍 no-op）+ store 自守卫（三层：open 无 lastFrame 返回 false / reset 无
//      baseline 或陈旧 run 返回 false 幂等）
//   5) 编辑 → openModal('edit_layout')
//   6) 重置 → EditConfirmLayer（文案 PRD 原文）→ 确认 editStore.reset() 恢复基线全套；
//      取消无动作；无编辑会话（baseline null）幂等

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditLayoutControls } from '../EditLayoutControls';
import { useAppStore } from '../../../store/appStore';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { useEditStore } from '../../../store/editStore';
import { runRegistry, type RunRecord } from '../../../store/runRegistry';
import type { SolvePhase } from '../../../types/solvePhase';
import type { FrameMsg, ManifestMsg } from '../../../types/ws';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  runRegistry.clear();
  useEditStore.getState().invalidate();
  useControlPanelStore.getState().closeModal();
  useAppStore.setState({ renderTick: 0 });
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
  document.body.innerHTML = '';
  runRegistry.clear();
  useEditStore.getState().invalidate();
  useControlPanelStore.getState().closeModal();
});

// ---- fixture：gate 1000 · 两 500×500 方 @ [0,0]/[600,0] → 包络 1100（与
// EditLayoutModal.test 同款，reset 恢复断言可直接手算）----

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

function seedRun(): RunRecord {
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
  run.viewBoxMaxW = 1100; // 画布宽锚（useSolveRun 逐帧观察 max —— fixture 直接置终值）
  run.done = true;
  // ws=null / done=true = 策略/极限合成 record 同形态（applyStrategyResult 置换单条
  // RunRecord；激活口径只认 lastFrame 非空，零改动命中）。
  return run;
}

function renderBlock(phase: SolvePhase = 'idle'): void {
  act(() => {
    root!.render(<EditLayoutControls phase={phase} />);
  });
}

function editBtn(): HTMLButtonElement {
  return document.querySelector('[data-testid="edit-controls-edit"]') as HTMLButtonElement;
}
function resetBtn(): HTMLButtonElement {
  return document.querySelector('[data-testid="edit-controls-reset"]') as HTMLButtonElement;
}
function confirmOverlay(): HTMLElement | null {
  return document.querySelector('[data-testid="edit-confirm-overlay"]');
}

describe('EditLayoutControls 结构与激活口径 (US-004)', () => {
  it('结构：标题「编辑排料」+ 编辑/重置两按钮', () => {
    renderBlock('idle');
    const block = document.querySelector('.edit-controls') as HTMLElement;
    expect(block).not.toBeNull();
    expect(block.querySelector('.field-label')!.textContent).toBe('编辑排料');
    expect(editBtn().textContent).toBe('编辑');
    expect(resetBtn().textContent).toBe('重置');
  });

  it('无结果（registry 空 / 无 lastFrame）→ 两按钮 disabled', () => {
    runRegistry.create(0); // 有 run 但无 lastFrame（manifest 未到）—— 同导出口径置灰
    renderBlock('idle');
    expect(editBtn().disabled).toBe(true);
    expect(resetBtn().disabled).toBe(true);
  });

  it('有结果 + 非 running（idle/stopped/done/error）→ 可点；stopped best-so-far 与合成 record 同命中', () => {
    const run = seedRun();
    run.stopped = true; // stopped best-so-far（有帧）
    renderBlock('stopped');
    expect(editBtn().disabled).toBe(false);
    expect(resetBtn().disabled).toBe(false);
    for (const phase of ['idle', 'done', 'error'] as SolvePhase[]) {
      renderBlock(phase);
      expect(editBtn().disabled).toBe(false);
      expect(resetBtn().disabled).toBe(false);
    }
  });

  it('running 态（有结果仍）置灰', () => {
    seedRun();
    renderBlock('running');
    expect(editBtn().disabled).toBe(true);
    expect(resetBtn().disabled).toBe(true);
  });

  it('renderTick 订阅：置帧后 bump → disabled 解除（ExportButtons 同款）', () => {
    renderBlock('idle');
    expect(editBtn().disabled).toBe(true);
    seedRun();
    act(() => {
      useAppStore.getState().bumpRenderTick();
    });
    expect(editBtn().disabled).toBe(false);
    expect(resetBtn().disabled).toBe(false);
  });
});

describe('EditLayoutControls 编辑入口与三层防御 (US-004)', () => {
  it('编辑 → openModal 打开 edit_layout（EditLayoutModal 受控自显）', () => {
    seedRun();
    renderBlock('done');
    act(() => {
      editBtn().click();
    });
    expect(useControlPanelStore.getState().modal).toBe('edit_layout');
  });

  it('二层防御：disabled 时删 native 属性旁路点击仍 no-op（onClick guard）', () => {
    renderBlock('idle'); // 无结果 → disabled
    // devtools 删 disabled 属性的旁路：onClick 内 guard 拦截
    editBtn().disabled = false;
    resetBtn().disabled = false;
    act(() => {
      editBtn().click();
      resetBtn().click();
    });
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(confirmOverlay()).toBeNull(); // 重置未进 confirm
  });

  it('三层防御（store 层）：open 无 lastFrame 返回 false（直调 store 不炸不弹）', () => {
    const empty = runRegistry.create(0);
    expect(useEditStore.getState().open(empty)).toBe(false);
    expect(useEditStore.getState().run).toBeNull();
  });
});

describe('EditLayoutControls 重置 confirm (US-004)', () => {
  it('重置 → confirm 层（PRD 原文文案）；取消 → 无动作（lastFrame 不动、层消失）', () => {
    seedRun();
    renderBlock('done');
    act(() => {
      resetBtn().click();
    });
    expect(confirmOverlay()).not.toBeNull();
    expect(
      document.querySelector('[data-testid="edit-confirm-message"]')!.textContent,
    ).toBe('确认将当前更新后的排料布局重置回初始布局');
    act(() => {
      (
        document.querySelector('[data-testid="edit-confirm-cancel"]') as HTMLButtonElement
      ).click();
    });
    expect(confirmOverlay()).toBeNull();
    // 未确认 → 未调 reset（编辑态原样）
    expect(useEditStore.getState().savedDirty).toBe(false);
  });

  it('确认 → editStore.reset() 恢复基线全套（placed/width/density/viewBoxMaxW）', () => {
    const run = seedRun();
    // 建立编辑会话：open 快照基线 → 拖片 b 右移 600 → save 写回（主面板重置的对象）
    useEditStore.getState().open(run);
    useEditStore.getState().setWorkingItem(1, { translation: [1200, 0] });
    expect(useEditStore.getState().save()).toBe(true);
    expect(run.lastFrame!.width_mm).toBe(1700);
    expect(run.lastFrame!.placed_items[1].translation).toEqual([1200, 0]);
    renderBlock('done');
    act(() => {
      resetBtn().click();
    });
    act(() => {
      (
        document.querySelector('[data-testid="edit-confirm-ok"]') as HTMLButtonElement
      ).click();
    });
    // 基线全套恢复：b 回 [600,0]、料长/密度/画布锚回算法值；savedDirty 清位
    expect(run.lastFrame!.placed_items[1].translation).toEqual([600, 0]);
    expect(run.lastFrame!.width_mm).toBe(1100);
    expect(run.lastFrame!.density).toBeCloseTo(500000 / (1100 * 1000), 12);
    expect(run.finalDensity).toBeCloseTo(500000 / (1100 * 1000), 12);
    expect(run.viewBoxMaxW).toBe(1100);
    expect(useEditStore.getState().savedDirty).toBe(false);
    expect(confirmOverlay()).toBeNull();
  });

  it('无编辑会话（baseline null，如刷新后未开过弹窗）→ 确认幂等（lastFrame 不动）', () => {
    const run = seedRun();
    // 手改 lastFrame 模拟「已有保存态编辑但编辑会话不在」（刷新后 run 重建场景的同构防御）
    run.lastFrame!.placed_items[1] = { id: 'b_30', rotation: 90, translation: [1200, 300] };
    renderBlock('done');
    act(() => {
      resetBtn().click();
    });
    act(() => {
      (
        document.querySelector('[data-testid="edit-confirm-ok"]') as HTMLButtonElement
      ).click();
    });
    expect(run.lastFrame!.placed_items[1].rotation).toBe(90);
    expect(run.lastFrame!.placed_items[1].translation).toEqual([1200, 300]);
  });
});
