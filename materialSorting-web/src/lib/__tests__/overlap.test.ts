// 编辑排料 US-001 overlap 单测：
//   1) precomputeEditPieces：placed_items 数组下标展开（多副本同 pid 第 k 次 = 第 k 副本）、
//      worldPolygon 变换正确、bbox 正确、manifest 缺片防御跳过
//   2) computeOverlap：两矩形交面积精确值 / 凹形离散多 ring 交（3 环）/ bbox 预筛行为
//      （相离邻居零成本跳过、bbox 相交但几何不相交邻居计入）/ 穿透深度 / 自身跳过

import { describe, expect, it } from 'vitest';
import { computeOverlap, precomputeEditPieces, type EditPiece } from '../overlap';
import { bboxOf } from '../editGeometry';
import type { ManifestMsg, FrameMsg } from '../../types/ws';
import type { PlacedItem, Polygon } from '../../types/piece';

/** 100x100 方形毛版（base 坐标 [0,100]^2）。 */
const UNIT_SQUARE: Polygon = [
  [0, 0],
  [100, 0],
  [100, 100],
  [0, 100],
];

function mkManifest(): ManifestMsg {
  return {
    type: 'manifest',
    gate_mm: 1000,
    total_area_mm2: 30000,
    n_eroded: 0,
    pieces: [
      { id: 'a_28', size: 28, color: '#111111', area_mm2: 10000, polygon: UNIT_SQUARE },
      { id: 'b_28', size: 28, color: '#222222', area_mm2: 10000, polygon: UNIT_SQUARE },
    ],
  };
}

function mkFrame(items: PlacedItem[], widthMm: number): FrameMsg {
  return {
    type: 'frame',
    index: 7,
    elapsed: 1.5,
    phase: 'final',
    density: 0.5,
    density_sparrow: 0.55,
    width_mm: widthMm,
    placed_items: items,
  };
}

function item(id: string, rot: number, tx: number, ty: number): PlacedItem {
  return { id, rotation: rot, translation: [tx, ty] };
}

describe('precomputeEditPieces', () => {
  it('按 placed_items 数组下标展开：key=下标，多副本同 pid 各占一 key', () => {
    const frame = mkFrame(
      [item('a_28', 0, 0, 0), item('b_28', 90, 500, 200), item('a_28', 0, 900, 0)],
      1000,
    );
    const out = precomputeEditPieces(mkManifest(), frame);
    expect(out.map((e) => e.key)).toEqual([0, 1, 2]);
    expect(out.map((e) => e.pid)).toEqual(['a_28', 'b_28', 'a_28']);
  });

  it('worldPolygon = base 经 rot+tr 变换（旋转 90° 手算对拍）；bbox 同步', () => {
    const frame = mkFrame([item('a_28', 90, 500, 200)], 800);
    const [e] = precomputeEditPieces(mkManifest(), frame);
    // base [0,100]^2 旋转 90°（c=0,s=1）-> [0,-100]x... 再平移 (500,200)：
    // (0,0)->(500,200)；(100,0)->(500,300)；(100,100)->(400,300)；(0,100)->(400,200)
    expect(e.worldPolygon).toEqual([
      [500, 200],
      [500, 300],
      [400, 300],
      [400, 200],
    ]);
    expect(e.bbox).toEqual({ minX: 400, minY: 200, maxX: 500, maxY: 300 });
    expect(e.rot).toBe(90);
    expect(e.tr).toEqual([500, 200]);
    // basePolygon 共享引用只读（不拷贝）
    expect(e.basePolygon).toBe(UNIT_SQUARE);
  });

  it('manifest 缺片（id 不在 pieces）防御跳过，后续下标保持原数组下标', () => {
    const frame = mkFrame([item('a_28', 0, 0, 0), item('ghost_28', 0, 0, 0), item('b_28', 0, 0, 0)], 100);
    const out = precomputeEditPieces(mkManifest(), frame);
    expect(out.map((e) => [e.key, e.pid])).toEqual([[0, 'a_28'], [2, 'b_28']]);
  });
});

describe('computeOverlap', () => {
  /** 由 base 100x100 方 + 平移构造 EditPiece（无旋转场景的便捷夹具）。 */
  function pieceAt(key: number, tx: number, ty: number): EditPiece {
    const frame = mkFrame([item('a_28', 0, tx, ty)], tx + 100);
    const [e] = precomputeEditPieces(mkManifest(), frame);
    return { ...e, key };
  }

  it('两矩形交：面积精确值 + 单交集环 + 穿透深度', () => {
    // dragged [0,100]^2 vs 邻居 [95,195]x[30,130]：交 [95,100]x[30,100] = 5x70 = 350 mm^2；
    // 穿透：邻居顶点 (95,30) 落入 dragged（到 x=100 距 5）/ dragged 顶点 (100,100) 落入
    // 邻居（到 x=95 距 5）-> 5。
    const dragged = pieceAt(0, 0, 0);
    const other = pieceAt(1, 95, 30);
    const r = computeOverlap(dragged, [other]);
    expect(r.neighborCount).toBe(1);
    expect(r.intersections).toHaveLength(1);
    expect(r.areaMm2).toBeCloseTo(350, 10);
    expect(r.penetrationMm).toBeCloseTo(5, 10);
    // 交集外环 = 交矩形 [95,100]x[30,100]（4 顶点无重复起点；起点/绕向由实现定，
    // 以点数 + bbox 锁形状）
    expect(r.intersections[0]).toHaveLength(4);
    const ringBbox = bboxOf(r.intersections[0]);
    expect(ringBbox).toEqual({ minX: 95, minY: 30, maxX: 100, maxY: 100 });
  });

  it('bbox 预筛：相离邻居零成本跳过（neighborCount 不计、不产交集）', () => {
    const dragged = pieceAt(0, 0, 0);
    const far = pieceAt(1, 1000, 0);
    const far2 = pieceAt(2, 0, 800);
    const r = computeOverlap(dragged, [far, far2]);
    expect(r.neighborCount).toBe(0);
    expect(r.intersections).toHaveLength(0);
    expect(r.areaMm2).toBe(0);
    expect(r.penetrationMm).toBe(0);
  });

  it('bbox 预筛：bbox 接触但几何不相交（角碰）邻居计入 neighborCount、面积 0', () => {
    // dragged [0,100]^2 vs 邻居 [100,200]^2（右下角恰碰 (100,100)）—— bbox 接触 -> 预筛放行。
    const dragged = pieceAt(0, 0, 0);
    const touch = pieceAt(1, 100, 100);
    const r = computeOverlap(dragged, [touch]);
    expect(r.neighborCount).toBe(1);
    expect(r.areaMm2).toBe(0);
    expect(r.penetrationMm).toBe(0);
  });

  it('多邻居混合：只有 bbox 相交者贡献（相离者不拖累 neighborCount / 面积累加正确）', () => {
    const dragged = pieceAt(0, 0, 0);
    const n1 = pieceAt(1, 95, 30); // 交 [95,100]x[30,100] = 350
    const n2 = pieceAt(2, 95, 50); // 交 [95,100]x[50,100] = 5x50 = 250
    const far = pieceAt(3, 900, 900);
    const r = computeOverlap(dragged, [n1, n2, far]);
    expect(r.neighborCount).toBe(2);
    expect(r.intersections).toHaveLength(2);
    expect(r.areaMm2).toBeCloseTo(600, 10);
  });

  it('凹形离散多 ring 交：梳状 A x 矩形 B -> 3 个离散交环，面积 12，穿透 2', () => {
    // A = 左柱 x[0,6] 全高 + 三根右齿 x[6,10]（y[0,2]/[4,6]/[8,10]）；
    // B = [7,12]x[1,9]。交 = x[7,10] 的三段：3x1 + 3x2 + 3x1 = 12 mm^2，3 个离散环。
    // 穿透：B 顶点 (7,1)/(7,9) 落入 A 齿（到 y=0/y=2、y=8/y=10 距 1）；A 齿顶点
    // (10,2)/(10,8) 落入 B 距 1（y=1/y=9），(10,4)/(10,6) 落入 B 距 2（x=12）-> 2。
    const comb: Polygon = [
      [0, 0],
      [10, 0],
      [10, 2],
      [6, 2],
      [6, 4],
      [10, 4],
      [10, 6],
      [6, 6],
      [6, 8],
      [10, 8],
      [10, 10],
      [0, 10],
    ];
    const rect: Polygon = [
      [7, 1],
      [12, 1],
      [12, 9],
      [7, 9],
    ];
    const manifest: ManifestMsg = {
      type: 'manifest',
      gate_mm: 100,
      total_area_mm2: 0,
      n_eroded: 0,
      pieces: [
        { id: 'c_28', size: 28, color: '#333333', area_mm2: 0, polygon: comb },
        { id: 'd_28', size: 28, color: '#444444', area_mm2: 0, polygon: rect },
      ],
    };
    const frame = mkFrame([item('c_28', 0, 0, 0), item('d_28', 0, 0, 0)], 20);
    const [dragged, other] = precomputeEditPieces(manifest, frame);
    const r = computeOverlap(dragged, [other]);
    expect(r.neighborCount).toBe(1);
    expect(r.intersections).toHaveLength(3);
    expect(r.areaMm2).toBeCloseTo(12, 10);
    expect(r.penetrationMm).toBeCloseTo(2, 10);
  });

  it('others 含被拖片自身（同 key）时跳过', () => {
    const dragged = pieceAt(0, 0, 0);
    const r = computeOverlap(dragged, [dragged]);
    expect(r.neighborCount).toBe(0);
    expect(r.areaMm2).toBe(0);
  });
});
