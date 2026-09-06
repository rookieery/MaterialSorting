// edit-drag-snap US-002 —— 松手吸附引擎纯函数（P0 retreat 回退 + P1 attract 吸拢）。
//
// 职责边界（PRD 定案）：本引擎只做「给定落点 → 纠正后的 translation」的单次求解，
// 触发与否（右键 snap 会话 vs 左键自由拖动）是调用方（US-003 EditCanvas）职责，
// 引擎不感知按键 / DOM / 事件。全程序确定（无 RNG、固定枚举序），任何内部异常
// fail-open 返回 raw（调用方拿到的最坏结果 = 与不吸附一致，绝不卡死拖动出口）。
//
// 两级策略（沿拖动路径 lastSafeTr → rawTr 的线段参数化，t 单位 mm）：
//   P0 retreat —— 落点违谓词（全邻居总重叠 > 起手基线 + eps）时：20mm 粗扫括出
//     「首个穿越小段」（凹形使自由区间不连通，朴素二分会跳过窄障碍隧道穿越 ——
//     后端 polish.py _slide_west_touch 同款机器）→ 该小段内二分 ≤14 轮 → 自由侧
//     再退 1nm（SEP_NUDGE_MM，终态布尔交面积精确 0）。
//   P1 attract —— 落点合谓词时：沿末帧拖动位移方向（零位移帧退化质心连线）用
//     US-001 firstContactDistance 解析取首触距离 t，t ≤ 10mm 则吸到触点 −1nm；
//     多邻居取 t 最小者、平手取 EditPiece.key 小者（placed_items 数组下标）。
//
// 谓词 oracle：复用 overlap.ts computeOverlap 的 areaMm2（bbox 预筛 + polygon-clipping
// 布尔交），「安全」= 总重叠面积 ≤ sess.startOverlapMm2 + COLLIDE_AREA_EPS_MM2 ——
// 起手存量重叠（solver 全局容差 MAX_OVERLAP_MM=10 构造的布局）不恶化、不误清。
//
// 邻居寻址（仓库红线）：全程 EditPiece.key（placed_items 数组下标）逐个枚举，
// 绝不按 pid 建 Map 去重 —— 同 pid 多副本是独立邻居（单测加锁）。
//
// 常量口径：SEP_NUDGE_MM / COLLIDE_AREA_EPS_MM2 与后端 polish.py 同名常量一致
// （1nm 防贴死 / 1e-9 mm² 碰撞判定）；CLAMP_EPS_MM 同 polish.py GATE_EPS_MM
// （clamp 不变量浮点噪声容差）。

import { bboxOf, firstContactDistance, transformPolygon } from './editGeometry';
import { computeOverlap, type EditPiece } from './overlap';
import type { Pt } from '../types/piece';

/** attract 吸拢间隙上限（mm）：首触距离 ≤ 此值才吸（2026-09-06 定案）。 */
export const ATTRACT_MAX_GAP_MM = 10;

/** retreat 粗扫步长（mm）：沿拖动路径括出首个穿越小段（防窄障碍隧道穿越）。 */
const COARSE_SCAN_STEP_MM = 20;

/** retreat 二分轮数上限（14 轮 ⇒ 括出段 ≤20mm 收敛到 ~0.0013mm，满足 0.01mm 对拍容差）。 */
const BISECT_ITERS = 14;

/** 分离二分后防贴死微退 / 微抬（mm，1nm —— 后端 polish.py SEP_NUDGE_MM 同口径）。 */
const SEP_NUDGE_MM = 1e-9;

/** 「碰撞」判定面积阈值（mm² —— 后端 polish.py COLLIDE_AREA_EPS_MM2 同名同口径）。
 *  导出供 US-003 EditCanvas 的 lastSafeTr 跟踪谓词同口径消费（两处判定必须同 eps，
 *  否则跟踪位可能落在引擎谓词的违例侧 → 引擎防御性 fail-open 白白退化吸附效果）。 */
export const COLLIDE_AREA_EPS_MM2 = 1e-9;

/** clamp 不变量浮点容差（mm —— 后端 polish.py GATE_EPS_MM 同口径，吸变换噪声 ~1e-13 级）。 */
const CLAMP_EPS_MM = 1e-6;

/** 末帧位移视为零的阈值（mm）：小于 1nm 的位移按零位移帧退化质心连线。 */
const ZERO_DISP_EPS_MM = 1e-9;

/** 右键贴附会话态（US-003 由 EditCanvas 维护：pointerdown 起、refreshMetrics 顺带更新）。 */
export interface SnapSession {
  /** 会话内最后一个「安全」位（谓词成立）；null = 尚无安全帧（retreat 无锚点 → fail-open raw）。 */
  lastSafeTr: Pt | null;
  /** 起手基线：拖动开始时被拖片 vs 全邻居总重叠面积 mm²（存量重叠不恶化、不误清）。 */
  startOverlapMm2: number;
}

/** 引擎选项。 */
export interface SnapOptions {
  /** 门幅（mm）：clamp 不变量 y∈[0,gate] 的上界（manifest.gate_mm）。 */
  gate: number;
}

/** 吸附结果形态。 */
export type SnapKind = 'free' | 'retreat' | 'attract';

export interface SnapResult {
  /** 纠正后的 translation（fail-open / 无吸附 = rawTr 拷贝）。只改 translation，永不动 rot/mirror。 */
  tr: Pt;
  /** free = 未施加纠正；retreat = 回退到首个安全界；attract = 吸拢到触点 −1nm。 */
  kind: SnapKind;
  /** 伙伴片 EditPiece.key（retreat = 边界碰撞主导邻居 / attract = 吸拢目标）；free = null。 */
  partnerKey: number | null;
}

/** 被拖片放到指定位（纯函数：新对象，不修改入参 dragged）。 */
function pieceAt(dragged: EditPiece, tr: Pt): EditPiece {
  const world = transformPolygon(dragged.basePolygon, dragged.rot, tr, dragged.mirror);
  return { ...dragged, tr: [tr[0], tr[1]], worldPolygon: world, bbox: bboxOf(world) };
}

/** 被拖片在指定位是否满足 clamp 不变量（y∈[0,gate]、minX≥0；x 右界不钳 —— US-003 同口径）。 */
function withinClamp(dragged: EditPiece, tr: Pt, gate: number): boolean {
  const b = bboxOf(transformPolygon(dragged.basePolygon, dragged.rot, tr, dragged.mirror));
  return b.minX >= -CLAMP_EPS_MM && b.minY >= -CLAMP_EPS_MM && b.maxY <= gate + CLAMP_EPS_MM;
}

/** 向量归一为单位向量；零向量 / NaN 安全返回 null。 */
function unit(v: Pt): Pt | null {
  const len = Math.hypot(v[0], v[1]);
  if (!(len > 0)) return null;
  return [v[0] / len, v[1] / len];
}

/** 多边形质心（顶点等权均值；空多边形防御返回 [0,0]）。 */
function centroidOf(poly: readonly Pt[]): Pt {
  let x = 0;
  let y = 0;
  for (const p of poly) {
    x += p[0];
    y += p[1];
  }
  const n = poly.length || 1;
  return [x / n, y / n];
}

/**
 * retreat 边界伙伴归属：边界位（二分的碰撞侧 b）逐邻居算重叠面积，取最大者
 * （平手取 key 小 —— 与数组顺序无关的确定性）；全部 ≤ 阈值（防御，不应发生）→ null。
 */
function boundaryPartner(
  dragged: EditPiece,
  trBoundary: Pt,
  others: readonly EditPiece[],
): number | null {
  const ep = pieceAt(dragged, trBoundary);
  let bestKey: number | null = null;
  let bestArea = -1;
  for (const o of others) {
    if (o.key === dragged.key) continue;
    const area = computeOverlap(ep, [o]).areaMm2;
    if (area > bestArea || (area === bestArea && bestKey !== null && o.key < bestKey)) {
      bestArea = area;
      bestKey = o.key;
    }
  }
  return bestArea > COLLIDE_AREA_EPS_MM2 ? bestKey : null;
}

/**
 * 松手吸附单次求解（纯函数、全程序确定、fail-open）。
 *
 * @param dragged 被拖片（basePolygon/rot/mirror 为重放变换源；worldPolygon 不被本引擎消费）
 * @param rawTr   松手原始落点（调用方已 clamp；引擎不重钳 —— 违不变量的候选弃用回落 raw）
 * @param sess    会话态（lastSafeTr 锚点 + 起手基线重叠）
 * @param others  其余全部片（含被拖片自身时按 key 跳过；同 pid 多副本逐一参与，绝不去重）
 * @param opts    gate（clamp 上界）
 */
export function computeSnapCorrection(
  dragged: EditPiece,
  rawTr: Pt,
  sess: SnapSession,
  others: readonly EditPiece[],
  opts: SnapOptions,
): SnapResult {
  const raw: SnapResult = { tr: [rawTr[0], rawTr[1]], kind: 'free', partnerKey: null };
  try {
    if (others.length === 0) return raw;
    const baseline = sess.startOverlapMm2;
    const safeAt = (tr: Pt): boolean =>
      computeOverlap(pieceAt(dragged, tr), others).areaMm2 <= baseline + COLLIDE_AREA_EPS_MM2;
    if (!safeAt(rawTr)) {
      // ---- P0 retreat：粗扫括段 + 二分 + 1nm 微退（后端 _slide_west_touch 同款机器） ----
      const anchor = sess.lastSafeTr;
      if (!anchor) return raw; // 无安全锚点 → fail-open
      const dx = rawTr[0] - anchor[0];
      const dy = rawTr[1] - anchor[1];
      const len = Math.hypot(dx, dy);
      if (!(len > 0) || !safeAt(anchor)) return raw; // 零长路径 / 陈旧锚点（防御）
      const ux = dx / len;
      const uy = dy / len;
      const trAt = (t: number): Pt => [anchor[0] + ux * t, anchor[1] + uy * t];
      const collides = (t: number): boolean => !safeAt(trAt(t));
      let tFree = 0;
      let tHit: number | null = null;
      let t = 0;
      while (t < len) {
        const tn = Math.min(t + COARSE_SCAN_STEP_MM, len);
        if (collides(tn)) {
          tHit = tn;
          break;
        }
        tFree = tn;
        t = tn;
      }
      if (tHit === null) return raw; // 落点已违谓词 ⇒ 不可达（防御）
      let a = tFree; // a 恒自由 / b 恒碰撞（首个碰撞界）
      let b = tHit;
      for (let i = 0; i < BISECT_ITERS; i++) {
        const mid = (a + b) / 2;
        if (collides(mid)) b = mid;
        else a = mid;
      }
      const tStar = Math.max(a - SEP_NUDGE_MM, 0); // 自由侧再退 1nm（防贴死）
      const cand = trAt(tStar);
      if (safeAt(cand) && withinClamp(dragged, cand, opts.gate)) {
        return { tr: cand, kind: 'retreat', partnerKey: boundaryPartner(dragged, trAt(b), others) };
      }
      return raw;
    }
    // ---- P1 attract：解析首触距离吸拢（落点已合谓词） ----
    const ep = pieceAt(dragged, rawTr);
    let dragDir: Pt | null = null;
    if (sess.lastSafeTr) {
      const ddx = rawTr[0] - sess.lastSafeTr[0];
      const ddy = rawTr[1] - sess.lastSafeTr[1];
      if (Math.hypot(ddx, ddy) >= ZERO_DISP_EPS_MM) dragDir = unit([ddx, ddy]);
    }
    const dragCentroid = centroidOf(ep.worldPolygon);
    let best: { tr: Pt; t: number; key: number } | null = null;
    for (const o of others) {
      if (o.key === dragged.key) continue;
      // 末帧拖动位移方向；零位移帧退化为该邻居质心连线方向
      const oc = centroidOf(o.worldPolygon);
      const dir = dragDir ?? unit([oc[0] - dragCentroid[0], oc[1] - dragCentroid[1]]);
      if (!dir) continue; // 质心重合的零向量（防御）
      const t = firstContactDistance(ep.worldPolygon, o.worldPolygon, dir);
      if (t === null || t <= SEP_NUDGE_MM || t > ATTRACT_MAX_GAP_MM) continue;
      const cand: Pt = [
        rawTr[0] + (t - SEP_NUDGE_MM) * dir[0],
        rawTr[1] + (t - SEP_NUDGE_MM) * dir[1],
      ];
      if (!safeAt(cand) || !withinClamp(dragged, cand, opts.gate)) continue;
      if (best === null || t < best.t || (t === best.t && o.key < best.key)) {
        best = { tr: cand, t, key: o.key }; // 平手取 key（数组下标）小者
      }
    }
    if (best) return { tr: best.tr, kind: 'attract', partnerKey: best.key };
    return raw;
  } catch {
    return raw; // fail-open：内部异常（布尔交炸 / 病态几何）回落 raw
  }
}
