// 编辑排料 US-001 —— 重合计算器（拖动帧指标的地基，纯函数）。
//
// 两段式：
//   precomputeEditPieces —— 弹窗打开时把 lastFrame.placed_items 全量展开为世界坐标
//     （base 变换 + bbox 预筛盒），拖动帧只增量变换被拖片一项（US-003 消费）；
//   computeOverlap      —— 被拖片 vs 其余片：bbox 预筛（只对相交邻居）→ polygon-clipping
//     布尔交 → 交集外环（渲染红色高亮用）+ 面积（shoelace，外环 − 孔）+ 最大穿透深度。
//
// 多副本寻址（PRD 技术考虑）：编辑 key = placed_items 数组下标（同 pid 第 k 次出现 =
// 第 k 副本，与 NestSVG「出现序」副本池同语义）；保存原地保序写回 ⇒ 副本映射稳定。
//
// 几何口径：manifest.pieces[].polygon = erode 后几何 = 与 solver 碰撞判定同口径；
// 物理毛版重合比显示值最多大 ~2·d_g（弹窗脚注注明）。

import { intersection } from 'polygon-clipping';
import { polygonArea as shoelaceArea } from './params';
import { bboxIntersect, bboxOf, penetrationDepth, transformPolygon } from './editGeometry';
import type { BBox } from './editGeometry';
import type { PlacedItem, Polygon, Pt } from '../types/piece';
import type { FrameMsg, ManifestMsg } from '../types/ws';

/** 展开后的可编辑裁片（世界坐标快照 + 预筛盒）。 */
export interface EditPiece {
  /** placed_items 数组下标（编辑 key —— 多副本按出现序第 k 份，保存按下标保序写回）。 */
  key: number;
  /** pid（manifest.pieces[].id；多副本同 pid 不同 key）。 */
  pid: string;
  rot: number;
  tr: Pt;
  /** base 多边形（manifest erode 几何，共享引用不拷贝 —— 只读）。 */
  basePolygon: Polygon;
  /** rot+tr 变换后的世界坐标多边形（全精度）。 */
  worldPolygon: Polygon;
  /** worldPolygon 的包围盒（bbox 预筛）。 */
  bbox: BBox;
}

/**
 * 全部 placed 片按 placed_items 数组下标展开（弹窗打开时一次，O(Σ顶点)）。
 *
 * 防御：placed id 不在 manifest.pieces（不应发生）→ 跳过该项（后续下标保持原数组下标，
 * 与 placed_items 保序写回口径一致）。
 */
export function precomputeEditPieces(manifest: ManifestMsg, frame: FrameMsg): EditPiece[] {
  const byId = new Map<string, (typeof manifest.pieces)[number]>();
  for (const p of manifest.pieces) byId.set(p.id, p);
  const out: EditPiece[] = [];
  frame.placed_items.forEach((it: PlacedItem, idx: number) => {
    const info = byId.get(it.id);
    if (!info) return;
    const world = transformPolygon(info.polygon, it.rotation, it.translation);
    out.push({
      key: idx,
      pid: it.id,
      rot: it.rotation,
      tr: [it.translation[0], it.translation[1]],
      basePolygon: info.polygon,
      worldPolygon: world,
      bbox: bboxOf(world),
    });
  });
  return out;
}

/** computeOverlap 结果（渲染 + 三指标数据源）。 */
export interface OverlapResult {
  /** bbox 预筛后实际参与布尔交的邻居数（others 中 bbox 相交者；调试 / 单测预筛行为）。 */
  neighborCount: number;
  /** 交集外环列表（世界坐标，红色半透明高亮渲染用；一个邻居可贡献多个离散环）。 */
  intersections: Polygon[];
  /** 交并总面积 mm²（polygon-clipping MultiPolygon 各 poly 外环 − 孔求和）。 */
  areaMm2: number;
  /** 最大穿透深度 mm（被拖片 vs 各相交邻居的顶点采样最大值）。 */
  penetrationMm: number;
}

/** polygon-clipping 输出 ring（首点重复闭合）→ 项目 Polygon 口径（无重复起点）。 */
function openRing(ring: number[][]): Polygon {
  const n = ring.length;
  if (n > 1 && ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1]) {
    return ring.slice(0, n - 1) as Polygon;
  }
  return ring as Polygon;
}

/** 单个 polygon-clipping poly（[外环, ...孔]）的面积 = |外环| − Σ|孔|。 */
function polyArea(outer: Polygon, holes: Polygon[]): number {
  let a = shoelaceArea(outer);
  for (const h of holes) a -= shoelaceArea(h);
  return a;
}

/**
 * 被拖片 vs 其余片的重合计算。
 *
 * 流程：bbox 预筛（不相交的邻居零成本跳过）→ polygon-clipping intersection 取交集
 * MultiPolygon → 外环收集（渲染）+ 面积累加（外环 − 孔）+ 穿透深度取最大。布尔交异常
 * 直接上抛（调用方 US-003 降级为 bbox 估算，本纯函数不吞错）。
 *
 * @param dragged 被拖片（worldPolygon / bbox 须为最新拖动帧值）
 * @param others  其余全部片（含被拖片自身时按 key 跳过）
 */
export function computeOverlap(dragged: EditPiece, others: readonly EditPiece[]): OverlapResult {
  const result: OverlapResult = { neighborCount: 0, intersections: [], areaMm2: 0, penetrationMm: 0 };
  for (const o of others) {
    if (o.key === dragged.key) continue;
    if (!bboxIntersect(dragged.bbox, o.bbox)) continue;
    result.neighborCount += 1;
    const mp = intersection([dragged.worldPolygon], [o.worldPolygon]);
    for (const poly of mp) {
      if (poly.length === 0) continue;
      const outer = openRing(poly[0]);
      const holes: Polygon[] = [];
      for (let h = 1; h < poly.length; h++) holes.push(openRing(poly[h]));
      result.intersections.push(outer);
      result.areaMm2 += polyArea(outer, holes);
    }
    result.penetrationMm = Math.max(
      result.penetrationMm,
      penetrationDepth(dragged.worldPolygon, o.worldPolygon),
    );
  }
  if (result.areaMm2 < 0 && result.areaMm2 > -1e-6) result.areaMm2 = 0;
  return result;
}
