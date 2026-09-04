// 编辑排料 US-001 —— 编辑几何纯函数库（编辑弹窗的计算地基，零 DOM 依赖除 clientToWorld）。
//
// 与 lib/geometry.ts 的分工：
//   geometry.pointsStr —— 渲染出口（字符串 + r2 截断，与旧 vanilla / 后端 _transform_polygon 字节级一致）；
//   editGeometry      —— 计算出口（数组 + 全精度，供布尔交 / bbox / 穿透深度 / 密度重算消费）。
//   两者共用同一变换公式（单测对拍锁死）：rad = rot·π/180; c = cos(rad); s = sin(rad)
//     x' = x·c − y·s + tx；y' = x·s + y·c + ty
//
// 坐标系约定（CLAUDE.md / lib/geometry.ts 同款）：sparrow 世界坐标 X=用布长度(0..width)、
// Y=门幅(0..gate)、Y 向上；SVG 经 flipGroup translate(0 gate) scale(1 -1) 翻转后显示。
//
// 指标几何口径：manifest.pieces[].polygon = erode 后几何（与 solver 碰撞判定同口径）；
// 物理毛版重合比显示值最多大 ~2·d_g（per_type d≤10，默认 0~2mm），编辑弹窗脚注注明。

import { polygonArea as shoelaceArea } from './params';
import type { Polygon, Pt } from '../types/piece';

/** 轴对齐包围盒（世界坐标 mm）。 */
export interface BBox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/**
 * base 多边形按 rotation(°) + translation[tx,ty] 变换为世界坐标顶点数组。
 *
 * 与 lib/geometry.ts pointsStr **同公式逐点一致**（单测对拍：r2 截断后与 pointsStr 输出
 * 逐点相等），但保留全精度（不 r2）—— 布尔交 / bbox / 穿透深度对舍入敏感，渲染出口
 * 才截断。修改公式须与 pointsStr / 后端 _transform_polygon 三方锁步。
 *
 * @param poly base 多边形顶点（manifest.pieces[].polygon 同口径，闭合无重复起点）
 * @param rot  旋转角度（°；与 frame.placed_items[].rotation 一致）
 * @param tr   平移 [tx, ty]（与 frame.placed_items[].translation 一致）
 * @returns 新数组（顶点数与输入一致；不修改入参）
 */
export function transformPolygon(poly: readonly Pt[], rot: number, tr: Pt): Polygon {
  const r = (rot * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  const tx = tr[0];
  const ty = tr[1];
  const out: Polygon = new Array(poly.length);
  for (let i = 0; i < poly.length; i++) {
    const x = poly[i][0];
    const y = poly[i][1];
    out[i] = [x * c - y * s + tx, x * s + y * c + ty];
  }
  return out;
}

/**
 * 多 ring 面积求和（mm²）—— 各 ring 用 params.ts shoelace 单 ring 绝对值面积（私有实现
 * 导出复用）后求和。用于「多个独立 ring 的总面积」场景（如布尔交 MultiPolygon 全部外环）。
 *
 * 注意：带孔多边形面积 = 外环 − 孔（见 overlap.ts 的逐 poly 差集口径），本函数是
 * 纯求和（|ring| 累加），不做方向差集。
 */
export function polygonArea(rings: readonly Polygon[]): number {
  let sum = 0;
  for (const ring of rings) sum += shoelaceArea(ring);
  return sum;
}

/** 多边形包围盒（顶点 min/max；空数组防御返回全 0 退化盒）。 */
export function bboxOf(poly: readonly Pt[]): BBox {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of poly) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  if (minX === Infinity) return { minX: 0, minY: 0, maxX: 0, maxY: 0 };
  return { minX, minY, maxX, maxY };
}

/**
 * 两 bbox 是否相交（含边界接触 —— 预筛宁可多算不可漏算；预筛后再走精确布尔交）。
 */
export function bboxIntersect(a: BBox, b: BBox): boolean {
  return a.minX <= b.maxX && b.minX <= a.maxX && a.minY <= b.maxY && b.minY <= a.maxY;
}

/**
 * 点是否在多边形内（PNPOLY 偶奇射线法）。凹多边形正确；自交多边形未定义（母版无自交）。
 * 边界上的点返回真值不稳定（射线法固有），穿透深度采样按「严格落入」语义消费。
 */
export function pointInPolygon(pt: Pt, poly: readonly Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > pt[1] !== yj > pt[1] && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

/** 点到线段的最短距离（含端点钳制）。 */
function distPtSeg(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  let t = len2 === 0 ? 0 : ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  return Math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1]);
}

/** 点到多边形边界（各边取最近）的距离 = 该点陷入多边形的深度。 */
function distToBoundary(p: Pt, poly: readonly Pt[]): number {
  let d = Infinity;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const seg = distPtSeg(p, poly[j], poly[i]);
    if (seg < d) d = seg;
  }
  return d;
}

/**
 * 两多边形最大穿透深度（mm，顶点采样近似，PRD US-001 口径）：
 *
 *   取「A 顶点落入 B」与「B 顶点落入 A」的全部顶点，各自求到对方边界（各边最近距离）
 *   的深度，返回其**最大值**（最深陷入点）；无任何顶点落入对方 → 0。
 *
 * 已知近似边界（如实口径，PRD 认可）：交叉型重叠（边相交但顶点互不落入，如十字交叉）
 * 与对方顶点恰好压在我方边上的退化情形会低估 —— 顶点采样是 O(n+m) 毫秒级的代价下
 * 的合理近似，面积指标（布尔交精确值）与之互补。
 *
 * @param a 世界坐标多边形 A（如被拖片）
 * @param b 世界坐标多边形 B（如邻居片）
 */
export function penetrationDepth(a: readonly Pt[], b: readonly Pt[]): number {
  let depth = 0;
  for (const v of a) {
    if (pointInPolygon(v, b)) {
      const d = distToBoundary(v, b);
      if (d > depth) depth = d;
    }
  }
  for (const v of b) {
    if (pointInPolygon(v, a)) {
      const d = distToBoundary(v, a);
      if (d > depth) depth = d;
    }
  }
  return depth;
}

/**
 * 浏览器客户端坐标 → sparrow 世界坐标（mm）。
 *
 * 走 flipGroup.getScreenCTM().inverse() + svg.createSVGPoint() 的矩阵通路，自动涵盖
 * 两处坑：``preserveAspectRatio="xMinYMid meet"`` 的 letterbox 偏移、翻转组
 * ``translate(0 gate) scale(1 -1)`` 的 Y 翻转 —— 手写 ``gate − y`` 会漏 letterbox。
 *
 * @param svg       画布根 <svg>（createSVGPoint 工厂）
 * @param flipGroup 翻转组 <g>（CTM 携带 viewBox→client 全链变换）
 * @param clientX / clientY pointer event 的 client 坐标
 * @returns 世界坐标 [x, y]（Y 向上）；CTM 不可得（未渲染 / 测试环境未 mock）→ null
 */
export function clientToWorld(
  svg: SVGSVGElement,
  flipGroup: SVGGElement,
  clientX: number,
  clientY: number,
): Pt | null {
  const ctm = flipGroup.getScreenCTM();
  if (!ctm) return null;
  const pt = svg.createSVGPoint();
  pt.x = clientX;
  pt.y = clientY;
  const world = pt.matrixTransform(ctm.inverse());
  return [world.x, world.y];
}
