// 编辑排料 US-002 EditLayoutModal 单测 + US-003 状态条实时刷新：
//   1) 声明式受控：modal!==null 不渲染；openModal('edit_layout') → Portal 挂 body
//   2) mount 自 bestRun() 快照基线 → 状态条初值 = 主视图利用率/料长（同一真相源），
//      Δ 初值 = +0.00pt（working = 基线）
//   3) 唯一关闭路径：右上 ✕ 与右下保存；**ESC keydown 与遮罩 mousedown 均不关闭**
//      （dispatch 断言弹窗仍在 —— 与全站弹窗惯例的有意偏离）
//   4) 保存 → editStore.save()（US-002 布局未动 ⇒ 幂等同值写回：savedDirty=true、
//      lastFrame 数值不变）+ 关窗
//   5) 形态 select：完整版 → 毛板 → 画布 4 层工艺隐藏（即时切换可恢复）
//   6) 无 bestRun → 空态提示（edit-layout-empty）
//   US-003：7) 拖片右移超界 → 料长增/利用率降/Δ 负；左移腾空尾部 → 料长缩/利用率升
//           （computeLayoutStats 与保存同公式同真相源 —— pointer 拖动直接驱动）
//
// 套路同 ExportInfoModal 既有用例：createRoot + act + data-testid；不包 StrictMode。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditLayoutModal } from '../EditLayoutModal';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import { useEditStore } from '../../../store/editStore';
import { runRegistry, type RunRecord } from '../../../store/runRegistry';
import type { FrameMsg, ManifestMsg } from '../../../types/ws';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  runRegistry.clear();
  useEditStore.getState().invalidate();
  useControlPanelStore.getState().closeModal();
  (window as unknown as { PointerEvent?: unknown }).PointerEvent =
    class extends MouseEvent {};
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
});

// ---- fixture：gate 1000 · a/b 两 500×500 方 @ [0,0] / [600,0] → 包络 1100；
// total_area 500000 → density = 500000/(1100×1000) = 0.454545…（45.45%）----

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
        polygon: [
          [0, 0], [500, 0], [500, 500], [0, 500],
        ],
        net_polygon: [
          [50, 50], [450, 50], [450, 450], [50, 450],
        ],
      },
      {
        id: 'b_30',
        label: 'g02',
        size: 30,
        color: '#00ff00',
        area_mm2: 250000,
        polygon: [
          [0, 0], [500, 0], [500, 500], [0, 500],
        ],
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

function renderModal(): void {
  act(() => {
    root!.render(<EditLayoutModal />);
  });
}

function openEditLayout(run: RunRecord | null): void {
  if (run) seedBestRun();
  renderModal();
  act(() => {
    useControlPanelStore.getState().openModal('edit_layout');
  });
}

function overlay(): HTMLElement | null {
  return document.querySelector('[data-testid="edit-layout-overlay"]');
}

describe('EditLayoutModal 声明式受控 (US-002)', () => {
  it('modal=null 不渲染（默认关闭）', () => {
    seedBestRun();
    renderModal();
    expect(overlay()).toBeNull();
  });

  it("openModal('edit_layout') → Portal 挂 body；closeModal 后移除", () => {
    seedBestRun();
    renderModal();
    act(() => {
      useControlPanelStore.getState().openModal('edit_layout');
    });
    expect(overlay()).not.toBeNull();
    act(() => {
      useControlPanelStore.getState().closeModal();
    });
    expect(overlay()).toBeNull();
  });

  it('无 bestRun → 空态提示（不渲染画布）', () => {
    openEditLayout(null);
    expect(overlay()).not.toBeNull();
    expect(
      document.querySelector('[data-testid="edit-layout-empty"]'),
    ).not.toBeNull();
    expect(document.querySelector('svg.edit-layout-svg')).toBeNull();
  });
});

describe('EditLayoutModal 状态条与结构 (US-002)', () => {
  it('初值 = 主视图利用率与料长（computeLayoutStats 同真相源）；Δ 基线 = +0.00pt', () => {
    openEditLayout(seedBestRun());
    expect(
      document.querySelector('[data-testid="edit-layout-width"]')!.textContent,
    ).toContain('1100');
    const densityText = document.querySelector(
      '[data-testid="edit-layout-density"]',
    )!.textContent!;
    expect(densityText).toContain('45.45');
    // frame.density = computeLayoutStats 同值（主视图口径）
    expect(
      document.querySelector('[data-testid="edit-layout-delta"]')!.textContent,
    ).toContain('+0.00pt');
  });

  it('Δ 基线 = computeLayoutStats 口径（非裸 frame.density）—— solver 小数 width 不产生取整伪影', () => {
    // 复刻真实 case：solver 原始 width_mm = 6148.38 小数、density 按小数宽算 —— 弹窗
    // 状态条按 ceil(包络) 口径，若 Δ 基线取裸 frame.density 则未编辑就是 −0.01pt。
    // 本测把伪影放大到肉眼级：frame.density = 0.99（与包络口径 0.4545 完全脱钩），
    // Δ 仍须 = +0.00（基线 = computeLayoutStats(基线 placements)，只度量编辑效果）。
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const frame: FrameMsg = {
      type: 'frame',
      index: 0,
      elapsed: 1,
      phase: 'final',
      density: 0.99, // 刻意脱钩（放大伪影）
      density_sparrow: 0.99,
      width_mm: 1100.5, // 小数宽（solver 真实形态）
      placed_items: [
        { id: 'a_28', rotation: 0, translation: [0, 0] },
        { id: 'b_30', rotation: 0, translation: [600, 0] },
      ],
    };
    run.frames.push(frame);
    run.lastFrame = frame;
    run.finalDensity = 0.99;
    openEditLayout(run);
    // 料长 = ceil(包络 1100) = 1100（非 1100.5、非 ceil(1100.5)=1101）
    expect(
      document.querySelector('[data-testid="edit-layout-width"]')!.textContent,
    ).toContain('1100');
    // 利用率 = 500000/(1100×1000) = 45.45%（ceil 口径，非 frame.density 99%）
    expect(
      document.querySelector('[data-testid="edit-layout-density"]')!.textContent,
    ).toContain('45.45');
    // Δ = stats − baselineStats（同口径）= 0（不是 45.45−99 = −53.55）
    expect(
      document.querySelector('[data-testid="edit-layout-delta"]')!.textContent,
    ).toContain('+0.00pt');
  });

  it('中心画布渲染 5 层（与主视图同构：毛版 + 净版可见）+ 底部形态 select + 保存按钮', () => {
    openEditLayout(seedBestRun());
    const svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
    expect(svg).not.toBeNull();
    const g = svg.childNodes[2] as SVGGElement;
    // a_28（毛版+净版）2 节点 + b_30（毛版）1 节点
    expect(g.childNodes.length).toBe(3);
    const net = g.childNodes[1] as SVGPolygonElement;
    expect(net.getAttribute('stroke')).toBe('#33cc33');
    expect(net.style.display).toBe('');
    expect(
      document.querySelector('[data-testid="edit-layout-mode"]'),
    ).not.toBeNull();
    expect(
      document.querySelector('[data-testid="edit-layout-save"]')!.textContent,
    ).toContain('保存当前布局');
    // 取消按钮已废弃 —— footer 只有 select 与保存
    const footBtns = Array.from(
      document.querySelectorAll('.edit-layout-foot button'),
    );
    expect(footBtns.length).toBe(1);
  });

  it('形态 select 切毛板 → 画布 4 层工艺隐藏；切回完整版恢复', () => {
    openEditLayout(seedBestRun());
    const svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
    const g = svg.childNodes[2] as SVGGElement;
    const net = g.childNodes[1] as SVGPolygonElement;
    const sel = document.querySelector(
      '[data-testid="edit-layout-mode"]',
    ) as HTMLSelectElement;
    act(() => {
      sel.value = 'rough';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(net.style.display).toBe('none');
    const rough = g.childNodes[0] as SVGPolygonElement;
    expect(rough.style.display).toBe('');
    act(() => {
      sel.value = 'full';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(net.style.display).toBe('');
  });
});

describe('EditLayoutModal 关闭路径 (US-002)', () => {
  it('ESC keydown 不关闭（与全站弹窗惯例的有意偏离）', () => {
    openEditLayout(seedBestRun());
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(overlay()).not.toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('edit_layout');
  });

  it('遮罩 mousedown 不关闭（编辑草稿不可误触丢弃）', () => {
    openEditLayout(seedBestRun());
    act(() => {
      overlay()!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(overlay()).not.toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('edit_layout');
  });

  it('右上 ✕ 关闭（唯一关闭路径之一）', () => {
    openEditLayout(seedBestRun());
    act(() => {
      (
        document.querySelector('[data-testid="edit-layout-close"]') as HTMLButtonElement
      ).click();
    });
    expect(overlay()).toBeNull();
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('保存 → editStore.save()（幂等同值写回）+ 关窗（唯一关闭路径之二）', () => {
    const run = seedBestRun();
    openEditLayout(run);
    const densityBefore = run.lastFrame!.density;
    act(() => {
      (
        document.querySelector('[data-testid="edit-layout-save"]') as HTMLButtonElement
      ).click();
    });
    expect(overlay()).toBeNull();
    expect(useControlPanelStore.getState().modal).toBeNull();
    // save 落笔：savedDirty 置位；布局未动 → 数值幂等（placed/width/density 不变）
    expect(useEditStore.getState().savedDirty).toBe(true);
    expect(run.lastFrame!.width_mm).toBe(1100);
    expect(run.lastFrame!.density).toBeCloseTo(densityBefore, 12);
    expect(run.lastFrame!.placed_items.length).toBe(2);
  });
});

// ============================================================
// 状态条实时刷新（US-003）：拖动直接驱动，与保存同公式同真相源
// ============================================================

function mockRect(svg: SVGSVGElement, width: number, height: number): void {
  (svg as unknown as { getBoundingClientRect: () => DOMRect }).getBoundingClientRect = () =>
    ({ width, height, x: 0, y: 0, top: 0, left: 0, right: width, bottom: height }) as DOMRect;
}

function firePointer(
  el: Element,
  type: 'pointerdown' | 'pointermove' | 'pointerup',
  clientX: number,
  clientY: number,
): void {
  el.dispatchEvent(
    new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: 1, clientX, clientY }),
  );
}

/** 画布内 b 片毛版（stroke 尺码色 #00ff00）。 */
function roughB(svg: SVGSVGElement): SVGPolygonElement {
  return svg.querySelector(':scope g > polygon[stroke="#00ff00"]') as SVGPolygonElement;
}

describe('EditLayoutModal 状态条实时刷新 (US-003)', () => {
  it('拖片右移超界 → 料长增 / 利用率降 / Δ 转负（未保存前 lastFrame 不动）', () => {
    const run = seedBestRun();
    openEditLayout(run);
    const svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
    mockRect(svg, 550, 500); // meet s = 0.5 px/mm
    const b = roughB(svg);
    act(() => {
      firePointer(b, 'pointerdown', 100, 100);
      firePointer(b, 'pointermove', 400, 100); // dx=300px → +600mm → b@[1200,0]
      firePointer(b, 'pointerup', 400, 100);
    });
    // 包络 maxX = 1700 → 料长 1700；利用率 500000/(1700×1000) = 29.41%
    expect(
      document.querySelector('[data-testid="edit-layout-width"]')!.textContent,
    ).toContain('1700');
    expect(
      document.querySelector('[data-testid="edit-layout-density"]')!.textContent,
    ).toContain('29.41');
    // Δ = 29.4118 − 45.4545 = −16.04pt
    expect(
      document.querySelector('[data-testid="edit-layout-delta"]')!.textContent,
    ).toContain('-16.04pt');
    // 未保存：lastFrame 仍是算法基线（编辑态与保存解耦）
    expect(run.lastFrame!.width_mm).toBe(1100);
    expect(run.lastFrame!.placed_items[1].translation).toEqual([600, 0]);
    expect(useEditStore.getState().working[1].translation[0]).toBeCloseTo(1200, 10);
  });

  it('拖片左移腾空尾部 → 料长缩 / 利用率升 / Δ 正', () => {
    seedBestRun();
    openEditLayout(null);
    const svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
    mockRect(svg, 550, 500);
    const b = roughB(svg);
    act(() => {
      firePointer(b, 'pointerdown', 100, 100);
      firePointer(b, 'pointermove', 0, 100); // dx=-100px → -200mm → b@[400,0]
      firePointer(b, 'pointerup', 0, 100);
    });
    // 包络 maxX = max(a 500, b 900) = 900 → 料长 900；利用率 55.56%；Δ +10.10pt
    expect(
      document.querySelector('[data-testid="edit-layout-width"]')!.textContent,
    ).toContain('900');
    expect(
      document.querySelector('[data-testid="edit-layout-density"]')!.textContent,
    ).toContain('55.56');
    expect(
      document.querySelector('[data-testid="edit-layout-delta"]')!.textContent,
    ).toContain('+10.10pt');
  });

  it('编辑后保存 → lastFrame 继承编辑值（同一真相源落地）', () => {
    const run = seedBestRun();
    openEditLayout(run);
    const svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
    mockRect(svg, 550, 500);
    const b = roughB(svg);
    act(() => {
      firePointer(b, 'pointerdown', 100, 100);
      firePointer(b, 'pointermove', 400, 100);
      firePointer(b, 'pointerup', 400, 100);
    });
    act(() => {
      (
        document.querySelector('[data-testid="edit-layout-save"]') as HTMLButtonElement
      ).click();
    });
    expect(run.lastFrame!.width_mm).toBe(1700);
    expect(run.lastFrame!.placed_items[1].translation).toEqual([1200, 0]);
    expect(run.lastFrame!.density).toBeCloseTo(500000 / (1700 * 1000), 12);
  });
});

// ============================================================
// US-004：✕ 关闭 dirty 二次确认（working ≠ 已保存布局，itemsEqual ε=1e-9）
// ============================================================

describe('EditLayoutModal ✕ dirty 确认 (US-004)', () => {
  it('未编辑 ✕ → 直接关（无确认层）', () => {
    openEditLayout(seedBestRun());
    act(() => {
      (
        document.querySelector('[data-testid="edit-layout-close"]') as HTMLButtonElement
      ).click();
    });
    expect(document.querySelector('[data-testid="edit-confirm-overlay"]')).toBeNull();
    expect(overlay()).toBeNull();
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('拖动后（dirty）✕ → 确认层「放弃未保存的修改？」；取消 → 留在弹窗', () => {
    const run = seedBestRun();
    openEditLayout(run);
    const svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
    mockRect(svg, 550, 500);
    const b = roughB(svg);
    act(() => {
      firePointer(b, 'pointerdown', 100, 100);
      firePointer(b, 'pointermove', 400, 100); // b@[1200,0] → dirty
      firePointer(b, 'pointerup', 400, 100);
    });
    act(() => {
      (
        document.querySelector('[data-testid="edit-layout-close"]') as HTMLButtonElement
      ).click();
    });
    // 弹窗仍在 + 确认层出现（文案）
    expect(overlay()).not.toBeNull();
    const confirm = document.querySelector('[data-testid="edit-confirm-overlay"]');
    expect(confirm).not.toBeNull();
    expect(
      document.querySelector('[data-testid="edit-confirm-message"]')!.textContent,
    ).toBe('放弃未保存的修改？');
    act(() => {
      (
        document.querySelector('[data-testid="edit-confirm-cancel"]') as HTMLButtonElement
      ).click();
    });
    // 取消 → 确认层消失、弹窗仍在（草稿保真，可继续编辑/保存）
    expect(document.querySelector('[data-testid="edit-confirm-overlay"]')).toBeNull();
    expect(overlay()).not.toBeNull();
    expect(run.lastFrame!.placed_items[1].translation).toEqual([600, 0]); // 未写回
  });

  it('dirty ✕ 确认 → 弃稿关窗（lastFrame 不动、未保存丢弃）', () => {
    const run = seedBestRun();
    openEditLayout(run);
    const svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
    mockRect(svg, 550, 500);
    const b = roughB(svg);
    act(() => {
      firePointer(b, 'pointerdown', 100, 100);
      firePointer(b, 'pointermove', 400, 100);
      firePointer(b, 'pointerup', 400, 100);
    });
    act(() => {
      (
        document.querySelector('[data-testid="edit-layout-close"]') as HTMLButtonElement
      ).click();
    });
    act(() => {
      (
        document.querySelector('[data-testid="edit-confirm-ok"]') as HTMLButtonElement
      ).click();
    });
    expect(overlay()).toBeNull();
    expect(useControlPanelStore.getState().modal).toBeNull();
    // 弃稿：lastFrame 保持算法基线（编辑未写回）
    expect(run.lastFrame!.placed_items[1].translation).toEqual([600, 0]);
    expect(run.lastFrame!.width_mm).toBe(1100);
    expect(useEditStore.getState().savedDirty).toBe(false);
  });

  it('保存后 ✕ → 直接关（save 写回后 working 与 lastFrame 逐项相等 → 非 dirty）', () => {
    const run = seedBestRun();
    // 第一轮：拖动 + 保存（关窗）
    openEditLayout(run);
    let svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
    mockRect(svg, 550, 500);
    let b = roughB(svg);
    act(() => {
      firePointer(b, 'pointerdown', 100, 100);
      firePointer(b, 'pointermove', 400, 100);
      firePointer(b, 'pointerup', 400, 100);
    });
    act(() => {
      (
        document.querySelector('[data-testid="edit-layout-save"]') as HTMLButtonElement
      ).click();
    });
    expect(overlay()).toBeNull();
    // 第二轮：重开（快照 = 已保存布局）→ 未再编辑 ✕ 直接关，无确认层
    openEditLayout(null);
    act(() => {
      (
        document.querySelector('[data-testid="edit-layout-close"]') as HTMLButtonElement
      ).click();
    });
    expect(document.querySelector('[data-testid="edit-confirm-overlay"]')).toBeNull();
    expect(overlay()).toBeNull();
  });

  it('保存后继续拖动再 ✕ → dirty 复现（working ≠ 已保存布局）', () => {
    const run = seedBestRun();
    openEditLayout(run);
    const svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
    mockRect(svg, 550, 500);
    const b = roughB(svg);
    act(() => {
      firePointer(b, 'pointerdown', 100, 100);
      firePointer(b, 'pointermove', 400, 100);
      firePointer(b, 'pointerup', 400, 100);
    });
    // 保存（写回 + 关窗）→ 重开 → 再拖一段
    act(() => {
      (
        document.querySelector('[data-testid="edit-layout-save"]') as HTMLButtonElement
      ).click();
    });
    openEditLayout(null);
    const svg2 = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
    mockRect(svg2, 550, 500);
    const b2 = roughB(svg2);
    act(() => {
      firePointer(b2, 'pointerdown', 100, 100);
      firePointer(b2, 'pointermove', 0, 100); // 左移 -200mm
      firePointer(b2, 'pointerup', 0, 100);
    });
    act(() => {
      (
        document.querySelector('[data-testid="edit-layout-close"]') as HTMLButtonElement
      ).click();
    });
    expect(document.querySelector('[data-testid="edit-confirm-overlay"]')).not.toBeNull();
    expect(overlay()).not.toBeNull();
  });

  it('确认层显隐期间 ESC 与遮罩 mousedown 仍不关弹窗（双重禁关闭叠加）', () => {
    seedBestRun();
    openEditLayout(null);
    const svg = document.querySelector('svg.edit-layout-svg') as SVGSVGElement;
    mockRect(svg, 550, 500);
    const b = roughB(svg);
    act(() => {
      firePointer(b, 'pointerdown', 100, 100);
      firePointer(b, 'pointermove', 400, 100);
      firePointer(b, 'pointerup', 400, 100);
    });
    act(() => {
      (
        document.querySelector('[data-testid="edit-layout-close"]') as HTMLButtonElement
      ).click();
    });
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      overlay()!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(overlay()).not.toBeNull();
    expect(document.querySelector('[data-testid="edit-confirm-overlay"]')).not.toBeNull();
  });
});
