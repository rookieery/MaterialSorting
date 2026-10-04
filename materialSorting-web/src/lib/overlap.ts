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
// 几何口径（2026-09-06 统一）：本计算器一律按**物理毛版轮廓**（physicalPolygon =
// raw_polygon，与 /export PLT/PNG/DXF、polish 报告同源）计算 —— 画布红字数值 =
// 导出真相，所见即所得。erode 后 polygon（solver 碰撞口径）降级为画布虚线参考线，
// 不再进任何数值口径；老后端无 raw_polygon 时 physicalPolygon 回退 polygon
// （d=0 时代两者等价）。相邻两片「压线额度」= d_i + d_j（两片 per_type 腐蚀距离
// 之和），穿透 ≤ 额度 = 设计允许的压线重合。
//
// 判红口径（2026-10-04 修订）：红/琥珀判定改按**碰撞轮廓**（manifest polygon =
// erode 后轮廓，sparrow 排料用的同一几何）相交 —— collideAreaMm2 > 阈值 = 红，
// 物理相交但碰撞不相交 = 琥珀（设计允许的压线）。动因：d>0 时 sparrow 贴触排料
// 的合法解（erode 轮廓零重叠，实测 d=2/4/8 全零）物理穿透 ≈ d_i+d_j + 正向噪声
// （shapely 腐蚀圆弧弦内接 ~0.02d/侧 + sparrow 位置 f32 量化 + 顶点抽稀，实测
// 超出额度 0.01~2.4mm 随 d 增大），旧判据「物理穿透 > d_i+d_j + 1e-9」对系统性
// 正偏差零容忍 → 初始布局生成即全片假阳性锁死保存闸（用户 2026-10-04 报障）。
// 物理口径的显示数值（面积/穿透/额度）不变 —— 红字数值仍是导出真相，只有
// 着色与闸门判定切换到排料约束口径。

import * as polygonClipping from 'polygon-clipping';
import { polygonArea as shoelaceArea } from './params';
import { bboxIntersect, bboxOf, penetrationDepth, transformPolygon } from './editGeometry';
import { physicalPolygon } from './geometry';
import type { BBox } from './editGeometry';
import type { PlacedItem, Polygon, Pt } from '../types/piece';
import type { FrameMsg, ManifestMsg } from '../types/ws';

/**
 * polygon-clipping 双产物互操作解析（US-003 起随 EditCanvas 进生产包发现）：
 * ESM dist（vite build/rollup 解析）**只导出 default**（default.intersection），
 * CJS/UMD（vitest deps 预打包解析）具名导出 —— 具名 import 在 rollup 下直接
 * 构建报错「"intersection" is not exported」。namespace 导入 + default 优先回退，
 * 两种解析形态都拿到 intersection；类型取 .d.ts 具名声明（三方一致）。
 */
const intersection: typeof polygonClipping.intersection = (
  (polygonClipping as unknown as { default?: typeof polygonClipping }).default ?? polygonClipping
).intersection;

/**
 * 碰撞轮廓（manifest polygon = erode 后轮廓）交集面积的判红阈值（mm²，2026-10-04
 * 判红口径切换）：低于此值视为数值噪声不算红。覆盖三层正噪声 —— d=0 时 _clean_polygon
 * 顶点抽稀与 raw 的偏差、d>0 时 shapely 腐蚀圆弧弦内接残差（~0.02d/侧）、sparrow
 * f32 位置量化；实测 solver 贴触解碰撞交恒 <1e-6mm²（远低于阈值），手拖深重叠
 * （mm 级）远高于阈值 —— 两端都有量级裕度。
 */
export const COLLIDE_NOISE_AREA_MM2 = 0.05;

/** 展开后的可编辑裁片（世界坐标快照 + 预筛盒）。 */
export interface EditPiece {
  /** placed_items 数组下标（编辑 key —— 多副本按出现序第 k 份，保存按下标保序写回）。 */
  key: number;
  /** pid（manifest.pieces[].id；多副本同 pid 不同 key）。 */
  pid: string;
  rot: number;
  tr: Pt;
  /**
   * 局部 x 翻转（水平镜像；edit-keyboard US-001 起）。内部计算池用明确 boolean
   * （PlacedItem.mirror 的 omit-when-false 只约束 wire/store 键集，不约束本结构）；
   * 源头 `it.mirror === true` 判定 → undefined/false 同义无镜像。
   */
  mirror: boolean;
  /** base 多边形（物理毛版 = physicalPolygon(piece)，共享引用不拷贝 —— 只读）。 */
  basePolygon: Polygon;
  /** 该片 per_type 腐蚀距离 mm（压线额度 = 相邻两片 dMm 之和；缺省 0）。 */
  dMm: number;
  /** rot+tr（+mirror）变换后的世界坐标多边形（全精度）。 */
  worldPolygon: Polygon;
  /** worldPolygon 的包围盒（bbox 预筛）。 */
  bbox: BBox;
  /**
   * 局部坐标碰撞轮廓（manifest polygon = erode 后轮廓原样，共享引用不拷贝 —— 只读；
   * 老后端/缺字段回退 basePolygon 自身）。红/琥珀判定数据源（2026-10-04 判红口径，
   * 见模块头注）—— sparrow 排料用的同一几何，显示数值仍走 worldPolygon 物理口径。
   */
  collideBasePolygon: Polygon;
  /** 碰撞轮廓世界坐标（collideBasePolygon 经同一 rot+tr+mirror 变换）。 */
  collidePolygon: Polygon;
  /** collidePolygon 的包围盒（碰撞交预筛）。 */
  collideBBox: BBox;
}

/**
 * 全部 placed 片按 placed_items 数组下标展开（弹窗打开时一次，O(Σ顶点)）。
 *
 * 防御：placed id 不在 manifest.pieces（不应发生）→ 跳过该项（后续下标保持原数组下标，
 * 与 placed_items 保序写回口径一致）。
 */
export function precomputeEditPieces(manifest: ManifestMsg, frame: FrameMsg): EditPiece[] {
  return precomputeEditPiecesFromItems(manifest, frame.placed_items);
}

/**
 * precomputeEditPieces 的 PlacedItem[] 直入口（US-003 编辑画布消费）。
 *
 * 编辑画布的池源 = editStore.working（编辑草稿，非 lastFrame —— 保存前两者可有偏差）；
 * 展开语义 / 防御与 precomputeEditPieces 完全一致（frame 版仅薄委托）。
 */
export function precomputeEditPiecesFromItems(
  manifest: ManifestMsg,
  items: readonly PlacedItem[],
): EditPiece[] {
  const byId = new Map<string, (typeof manifest.pieces)[number]>();
  for (const p of manifest.pieces) byId.set(p.id, p);
  const out: EditPiece[] = [];
  items.forEach((it: PlacedItem, idx: number) => {
    const info = byId.get(it.id);
    if (!info) return;
    const mirror = it.mirror === true;
    // 物理口径：raw_polygon（与 /export 同源）；老后端回退 erode polygon。
    const base = physicalPolygon(info);
    const world = transformPolygon(base, it.rotation, it.translation, mirror);
    // 碰撞口径：manifest polygon（erode 后，sparrow 排料同源）；缺字段/老后端回退
    // base 自身（d=0 时代 polygon ≈ raw，两口径合一）。
    const collideBase = info.polygon ?? base;
    const collide = transformPolygon(collideBase, it.rotation, it.translation, mirror);
    out.push({
      key: idx,
      pid: it.id,
      rot: it.rotation,
      tr: [it.translation[0], it.translation[1]],
      mirror,
      basePolygon: base,
      dMm: info.d_mm ?? 0,
      worldPolygon: world,
      bbox: bboxOf(world),
      collideBasePolygon: collideBase,
      collidePolygon: collide,
      collideBBox: bboxOf(collide),
    });
  });
  return out;
}

/**
 * 非法（红色）重叠片清单（onIllegalOverlapCountChange / 初始布局重叠序号快照共
 * 用数据源，2026-10-04 自 EditCanvas countIllegalOverlaps 迁入并升级为返回下标
 * 列表 —— 计数口径不变：调用方取 .length）：全 working 展开池逐片按指标面板同
 * 口径判红 —— collideAreaMm2 > COLLIDE_NOISE_AREA_MM2（碰撞轮廓 = erode 后
 * manifest polygon 相交 = 违反排料约束；物理相交而碰撞交噪声级 = 琥珀压线不计
 * —— d>0 时 solver 贴触解物理穿透 ≈ d_i+d_j+腐蚀/量化正噪声，旧「穿透 > 额度
 * + 1e-9」判据必假阳性锁死保存闸，见模块头注）；布尔交异常降级 bbox 近似回退旧
 * 穿透口径（penetrationDepth 纯函数 + bbox 相交邻居 d_i+d_j 最大值，保守兜底）。
 * 返回 = 红色片的 placed_items 数组下标升序列表（一对非法重合两侧各计一项 ——
 * 编辑链路下标寻址稳定，快照冻结后跨编辑依然有效）。
 *
 * pieceGroup（US-007 2026-10-04）：同组（band/prefix 刚性组）成员互不计 —— 组内
 * 几何是带构造的既成事实（链间滑移贴触 + 展开归一化的亚微米浮点缝隙），求解口径
 * 只对组合片 union 负责；且组内单片不可编辑（US-005），计入即不可解除的死锁。
 * 组对组外片照常计。缺省（编辑弹窗不传）→ 组判定恒 false，行为逐字节不变。
 */
export function findIllegalOverlapPieces(
  manifest: ManifestMsg,
  items: readonly PlacedItem[],
  pieceGroup?: (pid: string) => string | null,
): number[] {
  const pool = precomputeEditPiecesFromItems(manifest, items);
  // 组 id 按 pool 下标对齐（key = placed_items 下标 = pool 序；pieceGroup 缺席恒 null）。
  const gids = pool.map((ep) => (pieceGroup ? pieceGroup(ep.pid) : null));
  const sameGroup = (i: number, j: number): boolean => gids[i] != null && gids[i] === gids[j];
  const red: number[] = [];
  for (const ep of pool) {
    // bbox 预筛：无任何相交邻居（同组邻居不算）直接非红（省布尔交调用）。
    let touches = false;
    for (const o of pool) {
      if (o.key !== ep.key && !sameGroup(ep.key, o.key) && bboxIntersect(ep.bbox, o.bbox)) {
        touches = true;
        break;
      }
    }
    if (!touches) continue;
    try {
      const res = computeOverlap(ep, pool.filter((o) => !sameGroup(ep.key, o.key)));
      if (res.collideAreaMm2 > COLLIDE_NOISE_AREA_MM2) red.push(ep.key);
    } catch {
      let pen = 0;
      let allowance = 0;
      for (const o of pool) {
        if (o.key === ep.key) continue;
        if (sameGroup(ep.key, o.key)) continue;
        if (!bboxIntersect(ep.bbox, o.bbox)) continue;
        pen = Math.max(pen, penetrationDepth(ep.worldPolygon, o.worldPolygon));
        allowance = Math.max(allowance, ep.dMm + o.dMm);
      }
      if (pen > allowance + 1e-9) red.push(ep.key);
    }
  }
  return red;
}

/**
 * 池内单片**原地**增量更新（US-003 拖动/旋转帧专用 —— 其余片零成本保持）。
 *
 * 拖动帧只重算被拖片一项：worldPolygon / bbox / rot / tr / mirror 覆写为最新值后即可直接
 * computeOverlap（PRD「预计算 bbox 增量更新被拖片一项」口径）。调用方保证 ep 来自
 * precomputeEditPieces* 展开池（basePolygon 引用 manifest 只读共享）。
 *
 * mirror（edit-keyboard US-001 起，缺省 false）：调用方（拖动/键盘变换帧）把 working 项
 * 的镜像标志一并传入，避免镜像片在拖动/变换帧静默丢镜像。
 */
export function applyEditPlacement(ep: EditPiece, rot: number, tr: Pt, mirror = false): void {
  ep.rot = rot;
  ep.tr = [tr[0], tr[1]];
  ep.mirror = mirror;
  ep.worldPolygon = transformPolygon(ep.basePolygon, rot, tr, mirror);
  ep.bbox = bboxOf(ep.worldPolygon);
  ep.collidePolygon = transformPolygon(ep.collideBasePolygon, rot, tr, mirror);
  ep.collideBBox = bboxOf(ep.collidePolygon);
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
  /**
   * 压线额度 mm = 实际相交邻居中 max(d_i + d_j)（两片 per_type 腐蚀距离之和）。
   * 显示参考值（2026-10-04 起红/琥珀判定不再按它 —— 见 collideAreaMm2）。
   * 无相交邻居 / 老后端无 d_mm → 0。
   */
  allowanceMm: number;
  /**
   * 碰撞轮廓（erode 后 manifest polygon）交集总面积 mm²（2026-10-04 判红口径）：
   * > COLLIDE_NOISE_AREA_MM2 = 红（违反排料碰撞约束 = sparrow restore 后的碰撞态）；
   * 物理相交而碰撞交为噪声级 = 琥珀（设计允许的压线，含腐蚀近似的微超额度）。
   * 只在物理相交邻居上累加（碰撞轮廓 ⊆ 物理轮廓，物理交为零时碰撞交必为零）。
   */
  collideAreaMm2: number;
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
  const result: OverlapResult = {
    neighborCount: 0,
    intersections: [],
    areaMm2: 0,
    penetrationMm: 0,
    allowanceMm: 0,
    collideAreaMm2: 0,
  };
  for (const o of others) {
    if (o.key === dragged.key) continue;
    if (!bboxIntersect(dragged.bbox, o.bbox)) continue;
    result.neighborCount += 1;
    const mp = intersection([dragged.worldPolygon], [o.worldPolygon]);
    let areaNeighbor = 0;
    for (const poly of mp) {
      if (poly.length === 0) continue;
      const outer = openRing(poly[0]);
      const holes: Polygon[] = [];
      for (let h = 1; h < poly.length; h++) holes.push(openRing(poly[h]));
      result.intersections.push(outer);
      areaNeighbor += polyArea(outer, holes);
    }
    result.areaMm2 += areaNeighbor;
    // 实际相交的邻居才计入压线额度（d_i + d_j；bbox 相交但轮廓不相交者不算）。
    if (areaNeighbor > 1e-9) {
      result.allowanceMm = Math.max(result.allowanceMm, dragged.dMm + o.dMm);
      // 碰撞轮廓交（2026-10-04 判红口径）：erode ⊆ 物理，物理交为零时碰撞交必为零
      // —— 只在物理相交邻居上计算，平均省一半布尔交调用。
      if (bboxIntersect(dragged.collideBBox, o.collideBBox)) {
        const cpm = intersection([dragged.collidePolygon], [o.collidePolygon]);
        for (const poly of cpm) {
          if (poly.length === 0) continue;
          result.collideAreaMm2 += polyArea(openRing(poly[0]), poly.slice(1).map(openRing));
        }
      }
    }
    result.penetrationMm = Math.max(
      result.penetrationMm,
      penetrationDepth(dragged.worldPolygon, o.worldPolygon),
    );
  }
  if (result.areaMm2 < 0 && result.areaMm2 > -1e-6) result.areaMm2 = 0;
  return result;
}
