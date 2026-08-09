// WS 消息契约（与后端 server.py / solver.py 字段名严格一致）。
// client → server: StartPayload
// server → client: ServerMsg = ManifestMsg | FrameMsg | FinalMsg | ErrorMsg（判别联合，按 type 区分）
//
// 密度双口径：
//   density         —— 原面积口径（= total_area / (width*gate)），版师 / 90% 生死线以此为准
//   density_sparrow —— sparrow 自报（erode 后面积），仅作参考

import type { PieceInfo, PlacedItem } from './piece';
import type { PerTypeOverrides, SolveParams } from './v03';

/** client → server 唯一消息。per_type 空时序列化为 null（同旧 app.js collectParams）。 */
export interface StartPayload {
  action: 'start';
  sizes: number[];
  time: number;
  seed: number;
  params: SolveParams;
  per_type: PerTypeOverrides | null;
}

/** sparrow 求解阶段（与 rtype.phase_name() 对应；旧 app.js PHASE_COLORS keys）。 */
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

/** server → client 判别联合（按 type 字段区分）。 */
export type ServerMsg = ManifestMsg | FrameMsg | FinalMsg | ErrorMsg;
