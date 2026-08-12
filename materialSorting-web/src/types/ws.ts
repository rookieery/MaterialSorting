// WS 消息契约（与后端 server.py / solver.py 字段名严格一致）。
// client → server: ClientMsg = StartPayload | StopPayload
// server → client: ServerMsg = ManifestMsg | FrameMsg | FinalMsg | ErrorMsg | StoppedMsg（判别联合，按 type 区分）
//
// 密度双口径：
//   density         —— 原面积口径（= total_area / (width*gate)），版师 / 90% 生死线以此为准
//   density_sparrow —— sparrow 自报（erode 后面积），仅作参考

import type { PieceInfo, PlacedItem } from './piece';
import type { PerTypeOverrides, SolveParams } from './v03';

/**
 * client → server：启动求解（首条消息，必须 action:'start'）。
 * per_type 空时序列化为 null（同旧 vanilla 实现 collectParams）。
 */
export interface StartPayload {
  action: 'start';
  sizes: number[];
  time: number;
  seed: number;
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
