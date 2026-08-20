// WS 消息契约（与后端 server.py / solver.py 字段名严格一致）。
// client → server: ClientMsg = StartPayload | StopPayload
// server → client: ServerMsg = ManifestMsg | FrameMsg | FinalMsg | ErrorMsg | StoppedMsg（判别联合，按 type 区分）
//
// 密度双口径：
//   density         —— 原面积·实际幅宽口径（= total_area / (width * min(gate_mm, 1910))），
//                      版师 / 90% 生死线以此为准（2026-08-20 起分母与求解约束带同口径）
//   density_sparrow —— sparrow 自报（erode 后面积），仅作参考

import type { PieceInfo, PlacedItem } from './piece';
import type { PerTypeOverrides, SolveParams } from './v03';

/**
 * client → server：启动求解（首条消息，必须 action:'start'）。
 * per_type 空时序列化为 null（同旧 vanilla 实现 collectParams）；键 = 裁片 g 码
 * （裁片编号化重构 US-003 起；后端按 label 命中对该 g 码**全部码号**覆盖，2026-08-18
 * 回退 US-004 矩阵化（label×sizeKey 两级）后单级；旧 ptype / 两级键 no-op）。
 */
export interface StartPayload {
  action: 'start';
  sizes: number[];
  time: number;
  seed: number;
  /**
   * 幅宽（mm，= sparrow strip_height / 排料边框宽度）。前端 cm ×10 转 mm；
   * 后端用此值覆盖 intermediate 的 gate_mm，未传/非法 → 后端回退 intermediate gate。
   */
  gate_mm: number;
  params: SolveParams;
  per_type: PerTypeOverrides | null;
  /**
   * US-022 per-size demand：label → sizeKey → 数量。
   * sizeKey 口径与 qtyStore 一致（String(size) 或 'null'）；demand=0 → 该 piece 该码不排。
   * 缺省 / null → 后端全片 demand=1（向后兼容旧前端）。
   */
  quantities: Record<string, Record<string, number>> | null;
}

/**
 * US-026 client → server：停止求解（可在 start 后任意时刻发送）。
 * 后端收到后 terminate 求解子进程 → 直发 {type:'stopped'} → 关闭 WS。
 */
export interface StopPayload {
  action: 'stop';
}

/** client → server 判别联合（按 action 字段区分）。 */
export type ClientMsg = StartPayload | StopPayload;

/** sparrow 求解阶段（与 rtype.phase_name() 对应；旧 vanilla 实现 PHASE_COLORS keys）。 */
export type Phase = 'exploring' | 'compressing' | 'final';

/** manifest：base 几何（erode 后）+ 颜色，每个 run 仅推一次。 */
export interface ManifestMsg {
  type: 'manifest';
  gate_mm: number;
  /**
   * 实际排料幅宽 = min(gate_mm, 1910)（求解约束带 / density 分母口径）。
   * NestSVG 据此画红色虚线（实际范围边界）；缺省（旧后端）→ 不画线。
   * gate_mm 仍为显示口径（viewBox / 翻转 / 导出外框）。
   */
  gate_nest_mm?: number;
  total_area_mm2: number;
  n_eroded: number;
  pieces: PieceInfo[];
}

/** frame：每个中间解（density 经 server 重算为原面积口径）。 */
export interface FrameMsg {
  type: 'frame';
  /** 帧序号（server on_report 时附）。 */
  index: number;
  /** 求解已耗时 s。 */
  elapsed: number;
  phase: Phase | string;
  /** 原面积口径密度。 */
  density: number;
  /** erode 后 sparrow 自报密度（参考）。 */
  density_sparrow: number;
  width_mm: number;
  placed_items: PlacedItem[];
}

/** final：收尾（含最终密度 / 总帧数 / erode 计数）。 */
export interface FinalMsg {
  type: 'final';
  /** 原面积口径密度。 */
  density: number;
  /** erode 后 sparrow 自报密度。 */
  density_sparrow: number;
  width_mm: number;
  elapsed: number;
  n_frames: number;
  n_eroded: number;
}

/** error：构造 / 求解失败。 */
export interface ErrorMsg {
  type: 'error';
  message: string;
}

/**
 * US-026 stopped：客户端发 {action:'stop'} 后，后端 terminate 子进程 → 直发此消息 → 关闭 WS。
 * reason 目前固定 'user_requested'；未来可扩展（如超时等）。
 */
export interface StoppedMsg {
  type: 'stopped';
  reason: string;
}

/** server → client 判别联合（按 type 字段区分）。 */
export type ServerMsg = ManifestMsg | FrameMsg | FinalMsg | ErrorMsg | StoppedMsg;
