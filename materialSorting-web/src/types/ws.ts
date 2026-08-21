// WS 消息契约（与后端 server.py / solver.py 字段名严格一致）。
// client → server: ClientMsg = StartPayload | StopPayload
// server → client: ServerMsg = ManifestMsg | FrameMsg | FinalMsg | ErrorMsg | StoppedMsg | StageMsg（判别联合，按 type 区分）
//
// 密度双口径：
//   density         —— 原面积·实际幅宽口径（= total_area / (width * min(gate_mm, 1910))），
//                      版师 / 90% 生死线以此为准（2026-08-20 起分母与求解约束带同口径）
//   density_sparrow —— sparrow 自报（erode 后面积），仅作参考

import type { PieceInfo, PlacedItem } from './piece';
import type { PerTypeOverrides, SolveParams } from './v03';

/**
 * US-012（FR-1）腰头成带配置：选中 g 码先在带内独立聚排成组合片（WB_ pid 在
 * solve_worker 帧前展开回成员 placement，前端只见成员 pid）。
 *
 * StartPayload 的 ``band`` 键：缺省 / null / enabled falsy = 关闭（旧行为逐字节不变）；
 * 开启时后端 ``routes_ws._parse_band`` 服务端校验（label ``^g\d+$`` / 存在于母版 /
 * 该 g 码 quantities>0 / 硬警告形态需显式 ack）。
 */
export interface BandConfig {
  enabled: boolean;
  /** 腰头 g 码（如 'g05'；跨母版漂移 —— 由用户在高级配置弹窗指认，US-013）。 */
  label: string;
  /**
   * 硬警告形态（成员最小边 <60mm 或长宽比 >6）显式确认位；仅确认弹窗（US-013）
   * 置 true，缺省不随带。后端校验失败回结构化 error 早退。
   */
  ack?: boolean;
}

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
  /**
   * US-012（FR-1）腰头成带：缺省 / null / enabled falsy = 关闭（旧行为不变）；
   * 开且有效 → ``{enabled:true,label}``（collectStartContext 三态解析，见 lib/params.ts）。
   */
  band?: BandConfig | null;
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

/**
 * US-012（FR-2）stage：band 带内聚排完成统计，仅 band 开启时在 manifest 前发一次
 * （solve_worker `_build_band` → routes_ws `on_stage` 转发）。旧前端 default:break
 * 静默忽略，前向兼容；前端收到后状态行提示「腰头成带中…」，**run 不 finish**
 * （不进 phase 五态状态机，秒级提示）。
 */
export interface StageMsg {
  type: 'stage';
  /** 阶段名（目前恒 'band'）。 */
  stage: string;
  /** 带内填充率（erode 前 union 面积 / 带板 bbox）。 */
  fill_pct?: number | null;
  /** 带板实际占用 bbox（裁剪后）。 */
  bbox?: { width_mm: number; height_mm: number } | null;
  /** 兜底标记（当前恒 false；保留协议位）。 */
  fallback: boolean;
  /** 带内聚排耗时 s。 */
  elapsed?: number | null;
}

/** server → client 判别联合（按 type 字段区分）。 */
export type ServerMsg =
  | ManifestMsg
  | FrameMsg
  | FinalMsg
  | ErrorMsg
  | StoppedMsg
  | StageMsg;

/**
 * US-013（FR-7）POST /api/band/preview 响应（后端 web/routes_band.py；band 契约
 * 集中在本文件）。executor 线程跑 5s 预算 build_band_plan：
 *   - 成功 ``{ok:true, fill_pct, bbox, elapsed, break_even}``（break_even 盈亏参考线
 *     随响应回传，前端展示同源不双写）；
 *   - 几何失败也回 200 ``{ok:false, error}`` —— 预演失败是结果数据，前端降级提示
 *     **不阻塞确认**；结构错误（400/409/422）同 ``{error}`` 形状，其中硬警告形态的
 *     422 附 ``hard_warning:true``（前端渲染二次确认勾选框，勾选后带 ack:true 重试）。
 */
export interface BandPreviewResponse {
  ok: boolean;
  /** 带内填充率（%，实际占用 bbox 口径；成功时存在）。 */
  fill_pct?: number;
  /** 带板实际占用 bbox（成功时存在）。 */
  bbox?: { width_mm: number; height_mm: number };
  /** 预演耗时 s（成功时存在）。 */
  elapsed?: number;
  /** 盈亏参考线 [62.4, 63.6]（成功时存在）。 */
  break_even?: [number, number];
  /** 失败原因（ok:false / 结构错误时存在）。 */
  error?: string;
  /** 硬警告形态（422 需 ack）标记 —— 前端据此渲染二次确认勾选框。 */
  hard_warning?: boolean;
}
