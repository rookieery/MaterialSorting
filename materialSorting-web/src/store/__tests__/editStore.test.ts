// 编辑排料 US-001 editStore 单测：
//   - open：快照不可变基线全套（placed_items 深拷贝 + frameIndex/widthMm/density/
//     finalDensity/viewBoxMaxW），working 与基线/lastFrame 深解耦；无 lastFrame 拒开
//   - computeLayoutStats：width = ceil(包络 maxX)（下限 1mm / 小数进位）+ density =
//     total_area/(width x gate)（real 口径）—— save 同真相源
//   - save：原地保序写回（placed_items 数组身份不变）+ 扩长密度降 / 缩短密度升双向 +
//     finalDensity/viewBoxMaxW 跟随 + savedDirty + bumpRenderTick；陈旧 run（registry
//     clear 后）拒绝写回
//   - reset：恢复基线全套（placed/width/density/finalDensity/viewBoxMaxW）+ working 回
//     基线 + savedDirty=false；无编辑时幂等
//   - invalidate：清态（run/baseline/working/savedDirty 全空）
//   - setWorkingItem：下标寻址更新（US-003 消费口径），越界 no-op

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { computeLayoutStats, useEditStore } from '../editStore';
import { runRegistry } from '../runRegistry';
import { useAppStore } from '../appStore';
import type { RunRecord } from '../runRegistry';
import type { ManifestMsg, FrameMsg } from '../../types/ws';
import type { PlacedItem, Polygon } from '../../types/piece';

/** 500x500 方形毛版。 */
const HALF_SQUARE: Polygon = [
  [0, 0],
  [500, 0],
  [500, 500],
  [0, 500],
];

const MANIFEST: ManifestMsg = {
  type: 'manifest',
  gate_mm: 1000,
  total_area_mm2: 500_000,
  n_eroded: 0,
  pieces: [
    { id: 'a_28', size: 28, color: '#111111', area_mm2: 250_000, polygon: HALF_SQUARE },
    { id: 'b_28', size: 28, color: '#222222', area_mm2: 250_000, polygon: HALF_SQUARE },
  ],
};

function item(id: string, rot: number, tx: number, ty: number): PlacedItem {
  return { id, rotation: rot, translation: [tx, ty] };
}

/** 标准 fixture：a@[0,0]（x 0..500）+ b@[600,0]（x 600..1100）-> 包络 maxX 1100。 */
function mkRun(): RunRecord {
  const rec = runRegistry.create(3);
  rec.manifest = MANIFEST;
  const frame: FrameMsg = {
    type: 'frame',
    index: 42,
    elapsed: 10,
    phase: 'final',
    density: 500_000 / (1100 * 1000),
    density_sparrow: 0.51,
    width_mm: 1100,
    placed_items: [item('a_28', 0, 0, 0), item('b_28', 0, 600, 0)],
  };
  rec.frames.push(frame);
  rec.lastFrame = frame;
  rec.finalDensity = frame.density;
  rec.viewBoxMaxW = 1100;
  return rec;
}

beforeEach(() => {
  runRegistry.clear();
  useEditStore.getState().invalidate();
});

afterEach(() => {
  runRegistry.clear();
});

describe('open（快照不可变基线全套）', () => {
  it('基线字段逐项快照 + working 初始 = 布局副本', () => {
    const rec = mkRun();
    expect(useEditStore.getState().open(rec)).toBe(true);
    const s = useEditStore.getState();
    expect(s.run).toBe(rec);
    expect(s.baseline).toEqual({
      placedItems: [item('a_28', 0, 0, 0), item('b_28', 0, 600, 0)],
      frameIndex: 42,
      widthMm: 1100,
      density: 500_000 / 1_100_000,
      finalDensity: 500_000 / 1_100_000,
      viewBoxMaxW: 1100,
    });
    expect(s.working).toEqual([item('a_28', 0, 0, 0), item('b_28', 0, 600, 0)]);
    expect(s.savedDirty).toBe(false);
  });

  it('深拷贝解耦：working 改动不碰基线、也不碰 lastFrame.placed_items', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(0, { rotation: 90, translation: [123, 456] });
    const s = useEditStore.getState();
    expect(s.working[0]).toEqual(item('a_28', 90, 123, 456));
    expect(s.baseline?.placedItems[0]).toEqual(item('a_28', 0, 0, 0));
    expect(rec.lastFrame?.placed_items[0]).toEqual(item('a_28', 0, 0, 0));
    // translation 数组引用独立（防 lastFrame 被别名写穿）
    expect(s.working[0].translation).not.toBe(rec.lastFrame?.placed_items[0].translation);
    expect(s.baseline?.placedItems[0].translation).not.toBe(rec.lastFrame?.placed_items[0].translation);
  });

  it('run 无 lastFrame -> false 且态保持清空', () => {
    const rec = runRegistry.create(9);
    rec.manifest = MANIFEST;
    expect(useEditStore.getState().open(rec)).toBe(false);
    const s = useEditStore.getState();
    expect(s.run).toBeNull();
    expect(s.baseline).toBeNull();
    expect(s.working).toEqual([]);
  });
});

describe('computeLayoutStats（保存与实时显示同一真相源）', () => {
  it('width = ceil(全布局包络 maxX)；density = total_area/(width x gate)（real 口径）', () => {
    // fixture：maxX 1100（整数）-> 1100；density = 500000/(1100x1000)
    const stats = computeLayoutStats([item('a_28', 0, 0, 0), item('b_28', 0, 600, 0)], MANIFEST);
    expect(stats.widthMm).toBe(1100);
    expect(stats.density).toBeCloseTo(500_000 / 1_100_000, 12);
  });

  it('小数包络向上取整（maxX 600.5 -> 601）', () => {
    const stats = computeLayoutStats([item('a_28', 0, 100.5, 0)], MANIFEST);
    expect(stats.widthMm).toBe(601);
  });

  it('旋转参与包络（rot 90 的方块横向占 500）', () => {
    const stats = computeLayoutStats([item('a_28', 90, 100, 0)], MANIFEST);
    // base [0,500]^2 旋转 90°：x 范围 [-500..0] + 100 -> maxX 100
    expect(stats.widthMm).toBe(100);
    const stats2 = computeLayoutStats([item('a_28', 0, 100, 0)], MANIFEST);
    expect(stats2.widthMm).toBe(600);
  });

  it('空布局防御下限 1mm（防 0 除）', () => {
    const stats = computeLayoutStats([], MANIFEST);
    expect(stats.widthMm).toBe(1);
    expect(stats.density).toBe(500_000 / 1000);
  });
});

describe('save（原地保序写回 + 密度族重算）', () => {
  it('扩长：b 右移超原界 -> width 扩 / 密度降；placed_items 数组身份不变（原地写回）', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    // b 600 -> 1500：b x[1500,2000]，包络 maxX 2000 -> 扩长；密度 500000/2e6 = 0.25
    useEditStore.getState().setWorkingItem(1, { translation: [1500, 0] });
    const tickBefore = useAppStore.getState().renderTick;
    const arrRef = rec.lastFrame!.placed_items;
    const frameRef = rec.frames[0];

    expect(useEditStore.getState().save()).toBe(true);

    // 原地保序：lastFrame（= frames[0]）仍是同一对象，placed_items 仍是同一数组
    expect(rec.lastFrame).toBe(frameRef);
    expect(rec.lastFrame!.placed_items).toBe(arrRef);
    expect(rec.lastFrame!.placed_items).toEqual([
      item('a_28', 0, 0, 0),
      item('b_28', 0, 1500, 0),
    ]);
    expect(rec.lastFrame!.width_mm).toBe(2000);
    expect(rec.lastFrame!.density).toBeCloseTo(0.25, 12);
    expect(rec.finalDensity).toBeCloseTo(0.25, 12);
    expect(rec.viewBoxMaxW).toBe(2000);
    // density_sparrow 不动（solver erode 参考值）
    expect(rec.lastFrame!.density_sparrow).toBe(0.51);
    expect(useEditStore.getState().savedDirty).toBe(true);
    expect(useAppStore.getState().renderTick).toBe(tickBefore + 1);
  });

  it('缩短：左移腾空尾部 -> width 缩 / 密度升', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    // b 600 -> 400：包络 = max(500, 400+500=900) = 900 -> 缩短；密度 500000/9e5
    useEditStore.getState().setWorkingItem(1, { translation: [400, 0] });
    expect(useEditStore.getState().save()).toBe(true);
    expect(rec.lastFrame!.width_mm).toBe(900);
    expect(rec.lastFrame!.density).toBeCloseTo(500_000 / 900_000, 12);
    expect(rec.finalDensity).toBeCloseTo(500_000 / 900_000, 12);
    expect(rec.viewBoxMaxW).toBe(900);
  });

  it('陈旧 run（registry 已 clear）拒绝写回', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(1, { translation: [1500, 0] });
    runRegistry.clear(); // 重解 / 策略应用清场（US-004 挂点后 save 必须拒绝）
    expect(useEditStore.getState().save()).toBe(false);
    expect(useEditStore.getState().savedDirty).toBe(false);
  });

  it('未打开（无基线）save no-op false', () => {
    expect(useEditStore.getState().save()).toBe(false);
  });
});

describe('reset（恢复基线全套）', () => {
  it('保存改写后 reset：placed/width/density/finalDensity/viewBoxMaxW 全回基线', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    // b 旋转 90° 平移 (1500,100)：占 x[1000,1500]，包络 maxX 1500 -> 扩长
    useEditStore.getState().setWorkingItem(1, { rotation: 90, translation: [1500, 100] });
    useEditStore.getState().save();
    expect(rec.lastFrame!.width_mm).toBe(1500);
    expect(rec.lastFrame!.density).toBeCloseTo(500_000 / 1_500_000, 12);

    const tickBefore = useAppStore.getState().renderTick;
    expect(useEditStore.getState().reset()).toBe(true);

    expect(rec.lastFrame!.placed_items).toEqual([item('a_28', 0, 0, 0), item('b_28', 0, 600, 0)]);
    expect(rec.lastFrame!.width_mm).toBe(1100);
    expect(rec.lastFrame!.density).toBeCloseTo(500_000 / 1_100_000, 12);
    expect(rec.finalDensity).toBeCloseTo(500_000 / 1_100_000, 12);
    expect(rec.viewBoxMaxW).toBe(1100);
    // working 回基线 + savedDirty 清
    expect(useEditStore.getState().working).toEqual([item('a_28', 0, 0, 0), item('b_28', 0, 600, 0)]);
    expect(useEditStore.getState().savedDirty).toBe(false);
    expect(useAppStore.getState().renderTick).toBe(tickBefore + 1);
  });

  it('无编辑时 reset 幂等（值不变，仍 bump）', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    const beforeFrame = { ...rec.lastFrame!, placed_items: [...rec.lastFrame!.placed_items] };
    const beforeMaxW = rec.viewBoxMaxW;
    const tickBefore = useAppStore.getState().renderTick;
    expect(useEditStore.getState().reset()).toBe(true);
    expect(rec.lastFrame!.placed_items).toEqual(beforeFrame.placed_items);
    expect(rec.lastFrame!.width_mm).toBe(beforeFrame.width_mm);
    expect(rec.lastFrame!.density).toBe(beforeFrame.density);
    expect(rec.finalDensity).toBeCloseTo(beforeFrame.density, 12);
    expect(rec.viewBoxMaxW).toBe(beforeMaxW);
    expect(useAppStore.getState().renderTick).toBe(tickBefore + 1);
  });

  it('陈旧 run（registry 已 clear）拒绝重置', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    runRegistry.clear();
    expect(useEditStore.getState().reset()).toBe(false);
  });

  it('未打开 reset no-op false', () => {
    expect(useEditStore.getState().reset()).toBe(false);
  });
});

describe('invalidate / setWorkingItem', () => {
  it('invalidate 清态：run/baseline/working/savedDirty 全空，幂等', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(0, { translation: [9, 9] });
    useEditStore.getState().invalidate();
    const s = useEditStore.getState();
    expect(s.run).toBeNull();
    expect(s.baseline).toBeNull();
    expect(s.working).toEqual([]);
    expect(s.savedDirty).toBe(false);
    expect(useEditStore.getState().invalidate()).toBeUndefined();
  });

  it('setWorkingItem 只更新指定下标（rotation / translation 单独或合并），越界 no-op', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(1, { rotation: 45 });
    expect(useEditStore.getState().working[1]).toEqual(item('b_28', 45, 600, 0));
    useEditStore.getState().setWorkingItem(1, { translation: [10, 20] });
    expect(useEditStore.getState().working[1]).toEqual(item('b_28', 45, 10, 20));
    useEditStore.getState().setWorkingItem(99, { rotation: 1 });
    useEditStore.getState().setWorkingItem(-1, { rotation: 1 });
    expect(useEditStore.getState().working).toHaveLength(2);
    // 未打开时 no-op 不炸
    useEditStore.getState().invalidate();
    useEditStore.getState().setWorkingItem(0, { rotation: 1 });
    expect(useEditStore.getState().working).toEqual([]);
  });
});
