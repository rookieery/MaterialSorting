// WS 消息契约（与后端 server.py / solver.py 字段名严格一致）。
// client → server: ClientMsg = StartPayload | StopPayload
// server → client: ServerMsg = ManifestMsg | FrameMsg | FinalMsg | ErrorMsg | StoppedMsg | StageMsg（判别联合，按 type 区分）
//
// 密度双口径：
//   density         —— 原面积·输入门幅口径（= total_area / (width * gate_mm)），
//                      版师 / 90% 生死线以此为准（2026-08-28 起输入幅宽=实际幅宽单一口径）
//   density_sparrow —— sparrow 自报（erode 后面积），仅作参考

import type { PieceInfo, PlacedItem } from './piece';
import type { PerTypeOverrides, SolveParams } from './v03';

/**
 * US-012（FR-1）腰头成带配置：选中 g 码先在带内独立聚排成组合片（WB_ pid 在
 * solve_worker 帧前展开回成员 placement，前端只见成员 pid）。
 *
 * StartPayload 的 ``band`` 键：缺省 / null / enabled falsy = 关闭（旧行为逐字节不变）；
 * 开启时后端 ``routes_ws._parse_band`` 服务端校验（label ``^g\d+$`` / 存在于母版 /
 * 该 g 码 quantities>0）。不适合成带的 g 码由 waist_band.FILL_FLOOR_PCT 灾难守卫
 * 在带构造期拦截（结构化 error）。
 */
export interface BandConfig {
  enabled: boolean;
  /** 腰头 g 码（如 'g05'；跨母版漂移 —— 由用户在高级配置弹窗指认，US-013）。 */
  label: string;
}

/**
 * US-004（prefix FR-1）起始端成套前后幅配置：用户指认前/后幅 g 码后，系统在所排
 * 尺码中自动选取满足 2+2 的资格码（后端近满幅几何搜索确定性选码，**无 size 键**
 * —— 决策②；2026-09-02 起取代 seeded 随机），4 片构造性竖排 + 可行时顶部补 1 片
 * 异码近满幅成 `PS_*` 组合片进主解，解后 min_x>6mm 时钉位置换。
 *
 * StartPayload 的 ``prefix`` 键：缺省 / null / enabled falsy = 关闭（旧行为逐字节不变）；
 * 开启时后端 ``routes_ws._parse_prefix`` 服务端校验（front/back ``^g\d+$`` / 存在于
 * 母版 / front≠back / ≥1 资格码 —— 两码 demand==2 的码，无资格码 = 结构化 error
 * 早退 + 显式 close，文案指路数量矩阵）。
 */
export interface PrefixConfig {
  enabled: boolean;
  /** 前幅 g 码（如 'g02'；默认预选母版面积最大片，用户可改 —— 决策⑤）。 */
  front: string;
  /** 后幅 g 码（如 'g03'；须 front≠back，各码 2+2 恰用尽 demand）。 */
  back: string;
}

/**
 * 初始布局热启动载荷（prd-initial-layout US-007，2026-10-04）：「设置初始布局」
 * 弹窗保存的布局随普通运行附带（**仅普通运行** —— 高级/极限运行走 HTTP config
 * 不带此键）。后端 `routes_ws` prefix 解析后经 `initial_layout.build_warm_payload`
 * 装载（全降级不炸轮），final 以 `warm_state` 回显实际灌入态。
 *
 * `placed`：**组合宇宙口径**条目 —— band/prefix 开 = WB_/PS_ 组合 pid 在场的
 * 生成响应 composite 段 + 组位移记账（`saved.warmPlaced`）；plain = 展开视图全
 * 条目三键形态（后端 pid_meta 投影宇宙，pid 逐位一致）。`demand_map`：band/prefix
 * 开时必供（组合 pid 主进程不可推导）；plain 时后端忽略（前端也不发）。
 */
export interface WarmInitialPayload {
  /** 保存布局条目（三键形态；永无 mirror —— allowMirror=false 编辑不可能引入）。 */
  placed: PlacedItem[];
  /** 组合宇宙需求映射 {pid: N}（仅 band/prefix 开时随载荷在场）。 */
  demand_map?: Record<string, number>;
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
  /**
   * US-004（prefix FR-1）起始端成套前后幅：缺省 / null / enabled falsy = 关闭
   * （旧行为不变）；开且有效 → ``{enabled:true,front,back}``（collectPrefix 三态解析，
   * 与 band 可同开 —— 双开时带位只记录不置换，后端 US-003 行为）。**无 size 键**。
   */
  prefix?: PrefixConfig | null;
  /**
   * 初始布局热启动（prd-initial-layout US-007）：保存的初始布局随普通运行附带。
   * **键缺席 = 旧行为**（useSolveRun 对缺省/ null 不写键 —— JSON 序列化后线格式
   * 与旧前端逐字节一致）；stale / 未保存 / 已清除 → 不附带不拦截（普通求解照常）。
   */
  initial?: WarmInitialPayload | null;
  /**
   * 满核运行（2026-10-05 由高级/极限运行弹窗移入通用配置，三族运行同享）：
   * **键缺席 / false = 旧行为**（useSolveRun 仅 === true 附键 —— JSON 序列化后
   * 线格式与旧前端逐字节一致）；后端 routes_ws 严格 bool 校验，true → 附
   * solver_opts.num_workers = max(1, 逻辑核数−1)（CLI --full-cores 同式）。
   */
  full_cores?: true;
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

/** sparrow 求解阶段（与 rtype.phase_name() 对应；曲线配色已随曲线功能移除，类型保留供帧字段）。 */
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
  /**
   * prefix 统计段（起始端成套开启时后端 additive 附带；键缺席 = prefix 关闭，旧消息
   * 逐字段不变）。前端原只透传展示，2026-09-05 edit-polish US-003 起作为微调
   * exclude 组装的 best-effort 数据源 —— pid/extra 解析成员 pid 集合（成套起始端
   * 微调永不动）。applyFinal 落 RunRecord.prefix。
   */
  prefix?: FinalPrefixStats;
  /**
   * 初始布局热启动实际灌入态（prd-initial-layout US-003 起 additive；**StartPayload
   * 带 initial 键时才出现**）。US-007 前端消费：engaged=false → toast 中文 reason
   * 映射（lib/initialLayout.warmStateReasonText）；engaged=true → 状态行轻提示
   * 「已从初始布局热启动」。applyFinal 落 RunRecord.warmState。
   */
  warm_state?: FinalWarmState;
}

/**
 * final 附带的热启动灌入态（后端两数据源择一：worker final `{engaged, reason}`
 * 原样转发，或 routes_ws 侧预丢弃时合成 engaged=false + 中文 reason）。
 * reason：token（'worker_unsupported' / 'worker_serialize_failed' /
 * 'instance_mismatch'）或装载点中文文案（不支持热启动 / 校验矩阵 / 需求映射外）。
 */
export interface FinalWarmState {
  engaged: boolean;
  reason?: string | null;
}

/**
 * final 附带的 prefix 统计段（后端 solve_worker _prefix_record 子集：size/pid/
 * extra/residual_mm/fallback + 工件级 pin/band_pos —— 前端不消费，unknown 透传）。
 */
export interface FinalPrefixStats {
  /** 选中的资格码（如 34）。 */
  size: number | null;
  /** 组合片 pid（如 'PS_g02+g03@34+g02@32'；PS_ 永不泄漏进 placed_items）。 */
  pid: string;
  /** 顶部异码补片回显（兜底 4 片形态 = null）。 */
  extra: { pid: string; label: string | null; size: number | null; rotation: number } | null;
  /** pin 置换统计（工件级）。 */
  pin?: unknown;
  /** 双开带位记录（工件级）。 */
  band_pos?: unknown;
  residual_mm?: number | null;
  fallback?: boolean;
}

/** error：构造 / 求解失败。 */
export interface ErrorMsg {
  type: 'error';
  message: string;
  /**
   * US-005：会话类错误码（'session_expired' | 'session_limit'，后端 routes_ws 对
   * SessionError 的 additive 键 —— 有 code 才发，旧后端/业务错误无此键）。
   * useSolveRun 见此键 → lib/api.triggerSessionBlock 全局阻断弹窗（与 HTTP 同出口）。
   */
  code?: string;
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
 *
 * US-004 扩展：``stage:'prefix'``（起始端成套构造完成统计，双开时 band→prefix 序、
 * 各自 manifest 前唯一一次）—— ``size`` 回显后端选中的资格码（近满幅几何搜索
 * 确定性选定，前端无法预知，决策②），状态行「起始端成套构造中（尺码 {size}…）…」；
 * 2026-09-02 异码补片 additive：``extra_label``/``extra_size`` 仅补片在案时非
 * null（兜底 4 片 / 无补片 = null），状态行双形态「尺码 A＋{extra_label}@{extra_size}」。
 */
export interface StageMsg {
  type: 'stage';
  /** 阶段名（'band' | 'prefix'）。 */
  stage: string;
  /** 带内填充率（erode 前 union 面积 / 带板 bbox）。 */
  fill_pct?: number | null;
  /** 带板实际占用 bbox（裁剪后）。 */
  bbox?: { width_mm: number; height_mm: number } | null;
  /** 兜底标记（band 恒 false；prefix true = 无可行 5 片组合 → 兜底 4 片构造）。 */
  fallback: boolean;
  /** 带内聚排耗时 s。 */
  elapsed?: number | null;
  /** prefix 专属：选中的资格码（stage='prefix' 时回显，如 34）。 */
  size?: number | null;
  /** prefix 专属：组合片封闭腔数（interleave 序 0 腔；2026-09-03 paired 定案实测 3 腔死区，如实报告不设闸）。 */
  holes?: number | null;
  /**
   * prefix 专属（2026-09-02 异码补片 additive）：顶部异码补片 g 码（如 'g02'）。
   * 仅补片在案时非 null（兜底 / 无补片 = null）；旧后端无此键 → undefined 与
   * null 同走无补片文案分支（协议向后兼容，文案回落现行形态）。
   */
  extra_label?: string | null;
  /** prefix 专属：补片尺码（extra_label 在案时非 null）。 */
  extra_size?: number | null;
  /** prefix 专属：gate − 组合片高（近满幅残余缝隙，round 3；兜底路径同样回显）。 */
  residual_mm?: number | null;
}

/** server → client 判别联合（按 type 字段区分）。 */
export type ServerMsg =
  | ManifestMsg
  | FrameMsg
  | FinalMsg
  | ErrorMsg
  | StoppedMsg
  | StageMsg;
