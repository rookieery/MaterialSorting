// SaveStateControls 单测（主面板「保存当前方案状态（.msn）」区块，2026-09-12
// 状态文件入口改判：从导出格式下拉第 5 项拆出为独立区块）：
//   1) 结构：.save-state-group + 标题「保存当前方案状态（.msn）」+ 单「保存」按钮
//      （无说明行 —— 用户定案，原下拉选中时的保存范围文案随之删除）
//   2) 按钮状态与导出按钮严格一致（用户需求）：同公式
//      disabled = solving || exporting || !hasLastFrame —— 无结果 / 求解中 /
//      导出（保存）中三态置灰；hasLastFrame 判式与 ExportButtons 同源（含
//      stopped best-so-far 与合成 record）
//   3) renderTick 订阅：registry 置帧后 bump → disabled 解除（ExportButtons 同款）
//   4) 双层防御：native disabled（一层）+ onClick guard（二层，删属性旁路点击
//      仍不触发 onSave；useExport.saveState 的 exportingRef 是第三层防连击）

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { SaveStateControls } from '../SaveStateControls';
import { useAppStore } from '../../../store/appStore';
import { runRegistry, type RunRecord } from '../../../store/runRegistry';
import type { FrameMsg, ManifestMsg } from '../../../types/ws';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  runRegistry.clear();
  useAppStore.setState({ renderTick: 0, seekTime: -1 });
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
});

function makeRunWithFrame(seed: number): RunRecord {
  const rec = runRegistry.create(seed);
  rec.manifest = {
    type: 'manifest', gate_mm: 1980, total_area_mm2: 100000, n_eroded: 0, pieces: [],
  } satisfies ManifestMsg;
  const f: FrameMsg = {
    type: 'frame', index: 0, elapsed: 1, phase: 'final',
    density: 0.5, density_sparrow: 0.5, width_mm: 1000, placed_items: [],
  };
  rec.frames.push(f);
  rec.lastFrame = f;
  rec.finalDensity = 0.5;
  rec.done = true;
  return rec;
}

function renderBlock(
  props: Partial<React.ComponentProps<typeof SaveStateControls>> = {},
): () => void {
  const onSave = props.onSave ?? vi.fn();
  act(() => {
    root!.render(
      <SaveStateControls
        solving={props.solving ?? false}
        exporting={props.exporting ?? false}
        onSave={onSave}
      />,
    );
  });
  return onSave;
}

function saveBtn(): HTMLButtonElement {
  return document.querySelector('[data-testid="save-state-btn"]') as HTMLButtonElement;
}

describe('SaveStateControls 结构（2026-09-12 入口改判）', () => {
  it('结构：标题「保存当前方案状态（.msn）」+ 单「保存」按钮 + 无说明行', () => {
    renderBlock();
    const block = document.querySelector('.save-state-group') as HTMLElement;
    expect(block).not.toBeNull();
    expect(block.querySelector('.field-label')!.textContent).toBe('保存当前方案状态（.msn）');
    expect(saveBtn().textContent).toBe('保存');
    // 用户定案：纯标题栏 + 按钮，不放说明行（原保存范围文案随下拉项移除而删）
    expect(block.querySelector('.dim')).toBeNull();
  });
});

describe('SaveStateControls 按钮状态与导出按钮严格一致', () => {
  it('无结果（registry 空 / 无 lastFrame）→ disabled（同导出口径）', () => {
    runRegistry.create(0); // 有 run 但无 lastFrame —— 同导出按钮置灰
    renderBlock();
    expect(saveBtn().disabled).toBe(true);
  });

  it('有结果 + 非 solving + 非 exporting → 可点（stopped best-so-far / 合成 record 同命中）', () => {
    makeRunWithFrame(0); // done=true 的 record（合成 record 同形态：激活口径只认 lastFrame）
    renderBlock();
    expect(saveBtn().disabled).toBe(false);
  });

  it('solving=true（有结果仍）→ disabled', () => {
    makeRunWithFrame(0);
    renderBlock({ solving: true });
    expect(saveBtn().disabled).toBe(true);
  });

  it('exporting=true（导出/保存在飞，单一防连击旗）→ disabled', () => {
    makeRunWithFrame(0);
    renderBlock({ exporting: true });
    expect(saveBtn().disabled).toBe(true);
  });

  it('renderTick 订阅：置帧后 bump → disabled 解除（ExportButtons 同款）', () => {
    renderBlock();
    expect(saveBtn().disabled).toBe(true);
    makeRunWithFrame(0);
    act(() => {
      useAppStore.getState().bumpRenderTick();
    });
    expect(saveBtn().disabled).toBe(false);
  });
});

describe('SaveStateControls 点击与双层防御', () => {
  it('可点时点击 → onSave 触发（ControlPanel 接 useExport.saveState）', () => {
    makeRunWithFrame(0);
    const onSave = renderBlock({ onSave: vi.fn() });
    act(() => {
      saveBtn().click();
    });
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it('二层防御：disabled 时删 native 属性旁路点击仍 no-op（onClick guard）', () => {
    const onSave = renderBlock({ onSave: vi.fn() }); // 无结果 → disabled
    // devtools 删 disabled 属性的旁路：onClick 内 guard 拦截
    saveBtn().disabled = false;
    act(() => {
      saveBtn().click();
    });
    expect(onSave).not.toHaveBeenCalled();
  });
});
