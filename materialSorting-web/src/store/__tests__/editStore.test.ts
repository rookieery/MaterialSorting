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
//   - mirror 贯穿（edit-keyboard US-002）：open/save/setWorkingItem/replaceWorking/
//     reset/itemsEqual/computeLayoutStats 七消费路径 omit-when-false 透传 + 布尔差异
//   - resetItem（edit-keyboard US-002）：片级重置只写 working；越界 / id 错位 /
//     baseline 缺席三态守卫

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { computeLayoutStats, itemsEqual, useEditStore } from '../editStore';
import { runRegistry } from '../runRegistry';
import { useAppStore } from '../appStore';
import type { RunRecord } from '../runRegistry';
import type { ManifestMsg, FrameMsg } from '../../types/ws';
import type { PlacedItem, Polygon, Pt } from '../../types/piece';

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

// ============================================================
// US-004：基线锚定口径 —— 同一 run 重复 open 不换锚（保存后重开，重置恒回
// 算法初始布局；US-005 冒烟「两轮 拖→存 后重置 placed/density diff 回零」的地基）。
// ============================================================

describe('open 基线锚定（US-004）', () => {
  it('保存后重开：基线不换锚（仍算法布局）、working 承接已保存编辑、savedDirty 保持 true', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(1, { translation: [1200, 0] });
    useEditStore.getState().save();
    expect(rec.lastFrame!.placed_items[1].translation).toEqual([1200, 0]);
    // 重开（同 run）：基线仍 = 算法布局快照（b@[600,0] / width 1100）
    useEditStore.getState().open(rec);
    const s = useEditStore.getState();
    expect(s.baseline!.placedItems[1]).toEqual(item('b_28', 0, 600, 0));
    expect(s.baseline!.widthMm).toBe(1100);
    // working 从当前 lastFrame 深拷贝（承接已保存编辑继续微调）
    expect(s.working[1]).toEqual(item('b_28', 0, 1200, 0));
    expect(s.savedDirty).toBe(true);
  });

  it('两轮 拖→存 后重置 → 回算法初始布局（非第一轮保存态）', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    // 第一轮：右移扩长 + 保存
    useEditStore.getState().setWorkingItem(1, { translation: [1200, 0] });
    useEditStore.getState().save();
    // 第二轮：重开（不换锚）+ 再编辑 + 保存
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(0, { translation: [0, 500] });
    useEditStore.getState().save();
    expect(rec.lastFrame!.placed_items[0].translation).toEqual([0, 500]);
    // 重置 → 算法初始布局（两轮编辑全部回滚）
    useEditStore.getState().reset();
    expect(rec.lastFrame!.placed_items).toEqual([item('a_28', 0, 0, 0), item('b_28', 0, 600, 0)]);
    expect(rec.lastFrame!.width_mm).toBe(1100);
    expect(rec.lastFrame!.density).toBeCloseTo(500_000 / (1100 * 1000), 12);
    expect(rec.finalDensity).toBeCloseTo(500_000 / (1100 * 1000), 12);
    expect(rec.viewBoxMaxW).toBe(1100);
    expect(useEditStore.getState().savedDirty).toBe(false);
  });

  it('重置后重开：savedDirty false、Δ 基线一致（幂等续会话）', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(1, { translation: [1200, 0] });
    useEditStore.getState().save();
    useEditStore.getState().reset();
    useEditStore.getState().open(rec);
    const s = useEditStore.getState();
    expect(s.savedDirty).toBe(false);
    expect(s.working).toEqual([item('a_28', 0, 0, 0), item('b_28', 0, 600, 0)]);
    expect(s.baseline!.placedItems[1]).toEqual(item('b_28', 0, 600, 0));
  });

  it('换 run / invalidate 后 open → 全新锚定（旧基线不跨 run）', () => {
    const rec1 = mkRun();
    useEditStore.getState().open(rec1);
    useEditStore.getState().setWorkingItem(1, { translation: [1200, 0] });
    useEditStore.getState().save();
    // invalidate（重解/策略应用挂点同款）→ 新 run 全新快照
    useEditStore.getState().invalidate();
    const rec2 = mkRun();
    useEditStore.getState().open(rec2);
    const s = useEditStore.getState();
    expect(s.run).toBe(rec2);
    expect(s.baseline!.placedItems[1]).toEqual(item('b_28', 0, 600, 0));
    expect(s.savedDirty).toBe(false);
  });

  it('itemsEqual：长度/旋转/平移逐项 ε=1e-9 比较（sub-nm 残差不算修改）', () => {
    const a = [item('a', 0, 0, 0), item('b', 90, 100, 200)];
    expect(itemsEqual(a, [item('a', 0, 0, 0), item('b', 90, 100, 200)])).toBe(true);
    // 拖回原位 ~1e-13 残差 → 仍相等
    expect(
      itemsEqual(a, [
        item('a', 0, 1e-13, 0),
        item('b', 90.0000000000001, 100, 200 + 1e-13),
      ]),
    ).toBe(true);
    expect(itemsEqual(a, [item('a', 0, 0, 0)])).toBe(false); // 长度
    expect(itemsEqual(a, [item('a', 0, 0, 0), item('c', 90, 100, 200)])).toBe(false); // id
    expect(itemsEqual(a, [item('a', 45, 0, 0), item('b', 90, 100, 200)])).toBe(false); // rot
    expect(itemsEqual(a, [item('a', 0, 0.5, 0), item('b', 90, 100, 200)])).toBe(false); // tx
  });
});

// ============================================================
// edit-keyboard US-002：mirror 贯穿（五处显式字段 map，omit-when-false）
// + resetItem 片级重置（只写 working，下标 + id 对齐双守卫）。
// ============================================================

/** 直角三角形毛版（不对称 —— mirror 改变包络 maxX，供 computeLayoutStats 传参验证）。 */
const TRIANGLE: Polygon = [
  [0, 0],
  [300, 0],
  [0, 400],
];

const TRI_MANIFEST: ManifestMsg = {
  type: 'manifest',
  gate_mm: 1000,
  total_area_mm2: 60_000,
  n_eroded: 0,
  pieces: [{ id: 't_28', size: 28, color: '#111111', area_mm2: 60_000, polygon: TRIANGLE }],
};

/** 算法帧本身带 mirror:true 项的 run（a 镜像 + b 常规）。 */
function mkMirrorRun(): RunRecord {
  const rec = runRegistry.create(4);
  rec.manifest = MANIFEST;
  const frame: FrameMsg = {
    type: 'frame',
    index: 7,
    elapsed: 10,
    phase: 'final',
    density: 500_000 / (1100 * 1000),
    density_sparrow: 0.51,
    width_mm: 1100,
    placed_items: [
      { id: 'a_28', rotation: 0, translation: [0, 0], mirror: true },
      item('b_28', 0, 600, 0),
    ],
  };
  rec.frames.push(frame);
  rec.lastFrame = frame;
  rec.finalDensity = frame.density;
  rec.viewBoxMaxW = 1100;
  return rec;
}

describe('mirror 贯穿（US-002：五处字段 map，omit-when-false）', () => {
  it('open 快照（deepCopyItems）：基线与 working 均透传 mirror:true；缺省项不带键', () => {
    const rec = mkMirrorRun();
    useEditStore.getState().open(rec);
    const s = useEditStore.getState();
    expect(s.baseline!.placedItems[0].mirror).toBe(true);
    expect(s.working[0].mirror).toBe(true);
    expect('mirror' in s.baseline!.placedItems[1]).toBe(false);
    expect('mirror' in s.working[1]).toBe(false);
    // 深拷贝解耦：working 镜像项与 lastFrame 项是独立对象
    expect(s.working[0]).not.toBe(rec.lastFrame!.placed_items[0]);
  });

  it('save 写回（applyToRun）：mirror:true → lastFrame.placed_items[i].mirror === true；无镜像项写回仍无该键', () => {
    const rec = mkMirrorRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(1, { rotation: 30, translation: [700, 10] });
    expect(useEditStore.getState().save()).toBe(true);
    const items = rec.lastFrame!.placed_items;
    expect(items[0]).toEqual({ id: 'a_28', rotation: 0, translation: [0, 0], mirror: true });
    expect(items[0].mirror).toBe(true);
    expect(items[1]).toEqual(item('b_28', 30, 700, 10));
    expect('mirror' in items[1]).toBe(false);
  });

  it('save 落盘清键：working 项 mirror 缺省（如 replaceWorking 关镜像后）写回不残留 mirror 键', () => {
    const rec = mkMirrorRun();
    useEditStore.getState().open(rec);
    expect(
      useEditStore.getState().replaceWorking([item('a_28', 0, 0, 0), item('b_28', 0, 600, 0)]),
    ).toBe(true);
    expect(useEditStore.getState().save()).toBe(true);
    expect('mirror' in rec.lastFrame!.placed_items[0]).toBe(false);
  });

  it('setWorkingItem 透传 mirror：rotation/translation 增量更新不掉镜像标志；无镜像项更新后仍不带键', () => {
    const rec = mkMirrorRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(0, { rotation: 90, translation: [10, 20] });
    useEditStore.getState().setWorkingItem(1, { rotation: 45 });
    const w = useEditStore.getState().working;
    expect(w[0]).toEqual({ id: 'a_28', rotation: 90, translation: [10, 20], mirror: true });
    expect('mirror' in w[1]).toBe(false);
  });

  it('setWorkingItem patch.mirror（edit-keyboard US-005 键盘 O/I）：显式 true 带键 / 显式 false 键消失 / 缺省保持现值', () => {
    const rec = mkMirrorRun();
    useEditStore.getState().open(rec);
    // 显式 true：无镜像项开镜像（O/I 翻转「开」侧）。
    useEditStore.getState().setWorkingItem(1, { mirror: true, rotation: 15 });
    expect(useEditStore.getState().working[1]).toEqual({
      id: 'b_28',
      rotation: 15,
      translation: [600, 0],
      mirror: true,
    });
    // 显式 false：镜像项关镜像 —— 键按 omit-when-false 消失（O/I 翻转「关」侧）。
    useEditStore.getState().setWorkingItem(0, { mirror: false });
    expect(useEditStore.getState().working[0]).toEqual({
      id: 'a_28',
      rotation: 0,
      translation: [0, 0],
    });
    expect('mirror' in useEditStore.getState().working[0]).toBe(false);
    // 缺省不传 = 保持现值（指针拖动会话内恒定不传的既有口径零回归）。
    useEditStore.getState().setWorkingItem(1, { rotation: 45 });
    expect(useEditStore.getState().working[1].mirror).toBe(true);
    useEditStore.getState().setWorkingItem(0, { translation: [9, 9] });
    expect('mirror' in useEditStore.getState().working[0]).toBe(false);
  });

  it('replaceWorking（deepCopyItems 路径）透传 mirror：true 项带键 / 缺省项不带键', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    expect(
      useEditStore.getState().replaceWorking([
        { id: 'a_28', rotation: 10, translation: [1, 2], mirror: true },
        item('b_28', 5, 3, 4),
      ]),
    ).toBe(true);
    const w = useEditStore.getState().working;
    expect(w[0].mirror).toBe(true);
    expect('mirror' in w[1]).toBe(false);
  });

  it('reset 全局重置写回基线：基线 mirror 项同样 omit-when-false 落盘', () => {
    const rec = mkMirrorRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(0, { rotation: 90 });
    useEditStore.getState().save();
    expect(useEditStore.getState().reset()).toBe(true);
    expect(rec.lastFrame!.placed_items[0].mirror).toBe(true);
    expect('mirror' in rec.lastFrame!.placed_items[1]).toBe(false);
  });

  it('itemsEqual：mirror 布尔差异 → false（undefined 与 false 同义，只看归一布尔）', () => {
    const noKey = [item('a', 0, 0, 0)];
    const mirrored = [{ id: 'a', rotation: 0, translation: [0, 0] as Pt, mirror: true }];
    expect(itemsEqual(noKey, [{ id: 'a', rotation: 0, translation: [0, 0], mirror: false }])).toBe(
      true,
    ); // 缺省 vs 显式 false 同义
    expect(itemsEqual(noKey, mirrored)).toBe(false); // 布尔差异
    expect(itemsEqual(mirrored, mirrored)).toBe(true);
    expect(itemsEqual(mirrored, noKey)).toBe(false); // 对称
  });

  it('computeLayoutStats 传 mirror：镜像改变包络 maxX（三角形 x 取负手算对拍）', () => {
    // TRIANGLE x∈{0,300}，tr=[500,0]：无镜像 x' = 500+x → maxX 800
    const no = computeLayoutStats([item('t_28', 0, 500, 0)], TRI_MANIFEST);
    expect(no.widthMm).toBe(800);
    // 镜像 x' = 500−x → {500,200,500} → maxX 500（若 store 漏传 mirror 会仍得 800）
    const mi = computeLayoutStats(
      [{ id: 't_28', rotation: 0, translation: [500, 0], mirror: true }],
      TRI_MANIFEST,
    );
    expect(mi.widthMm).toBe(500);
  });
});

describe('resetItem（US-002：片级重置，只写 working）', () => {
  it('正常恢复：working[index] 回基线深拷贝，其余项 / baseline / lastFrame 均不动', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(0, { rotation: 90, translation: [123, 456] });
    useEditStore.getState().setWorkingItem(1, { translation: [900, 10] });
    expect(useEditStore.getState().resetItem(0)).toBe(true);
    const s = useEditStore.getState();
    expect(s.working[0]).toEqual(item('a_28', 0, 0, 0));
    expect(s.working[1]).toEqual(item('b_28', 0, 900, 10)); // 其余片不动
    expect(s.baseline!.placedItems).toEqual([item('a_28', 0, 0, 0), item('b_28', 0, 600, 0)]);
    // 只写 working 草稿不写 run（保存才落盘）
    expect(rec.lastFrame!.placed_items).toEqual([item('a_28', 0, 0, 0), item('b_28', 0, 600, 0)]);
    // 深拷贝：与基线项引用解耦（后续编辑不穿基线）
    expect(s.working[0].translation).not.toBe(s.baseline!.placedItems[0].translation);
  });

  it('镜像标志随基线恢复：working 置 mirror:true → 回基线无键；基线镜像项 → 恢复带键', () => {
    // ① 基线无镜像（算法原始布局），working 被置镜像 → 重置后 mirror 清零
    const rec = mkRun();
    useEditStore.getState().open(rec);
    expect(
      useEditStore.getState().replaceWorking([
        { id: 'a_28', rotation: 30, translation: [5, 5], mirror: true },
        item('b_28', 0, 600, 0),
      ]),
    ).toBe(true);
    expect(useEditStore.getState().resetItem(0)).toBe(true);
    expect(useEditStore.getState().working[0]).toEqual(item('a_28', 0, 0, 0));
    expect('mirror' in useEditStore.getState().working[0]).toBe(false);
    // ② 基线本身带 mirror（算法帧镜像项），编辑后重置 → mirror 回填 true
    const rec2 = mkMirrorRun();
    useEditStore.getState().open(rec2);
    useEditStore.getState().setWorkingItem(0, { rotation: 45, translation: [9, 9] });
    expect(useEditStore.getState().resetItem(0)).toBe(true);
    expect(useEditStore.getState().working[0]).toEqual({
      id: 'a_28',
      rotation: 0,
      translation: [0, 0],
      mirror: true,
    });
  });

  it('越界拒绝：负下标 / 超界（working 侧或 baseline 侧）→ false 且 working 原样', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().setWorkingItem(1, { translation: [900, 0] });
    const before = useEditStore.getState().working;
    expect(useEditStore.getState().resetItem(-1)).toBe(false);
    expect(useEditStore.getState().resetItem(2)).toBe(false);
    // baseline 侧越界：人为构造 working 比 baseline 长（防御病态草稿）
    useEditStore.setState({ working: [...before, item('c_28', 0, 0, 0)] });
    expect(useEditStore.getState().resetItem(2)).toBe(false);
    expect(useEditStore.getState().working).toEqual([...before, item('c_28', 0, 0, 0)]);
  });

  it('id 错位拒绝：working 与 baseline 同下标 id 不齐 → false 且 working 原样（不按 pid 寻址）', () => {
    const rec = mkRun();
    useEditStore.getState().open(rec);
    // 人为构造错位草稿（同 pid 多副本场景下错位 = 绝不能静默按 pid 找同名项重置）
    const swapped = [item('b_28', 0, 1, 1), item('a_28', 0, 2, 2)];
    useEditStore.setState({ working: swapped });
    expect(useEditStore.getState().resetItem(0)).toBe(false);
    expect(useEditStore.getState().resetItem(1)).toBe(false);
    expect(useEditStore.getState().working).toEqual(swapped);
  });

  it('baseline 缺席拒绝：未打开 / invalidate 后 → false 不炸、working 原样', () => {
    expect(useEditStore.getState().resetItem(0)).toBe(false);
    const rec = mkRun();
    useEditStore.getState().open(rec);
    useEditStore.getState().invalidate();
    expect(useEditStore.getState().resetItem(0)).toBe(false);
    expect(useEditStore.getState().working).toEqual([]);
  });
});
