// US-005 策略运行 HTTP 契约 —— `web/strategy.py`（US-004 四路由）响应/请求体的 TS 镜像。
// US-003 起同文件再镜像**极限运行四路由** `/api/extreme/*`（US-002 后端，与策略
// 同槽同构 —— status/result 载荷复用下述类型，mode 字段扩 'extreme'；start 载荷
// 独立 `ExtremeStartPayload`：time_total_s 秒 + 无 band/prefix）。
//
// 四路由（前端只走相对路径，dev 经 Vite proxy 转 :8000）：
//   POST /api/strategy/start   StrategyStartPayload → 202 {started,pid,mode,minutes,run_name}
//                              | 400 参数错 | 409 已有进行中运行 | 422 排料数据未 commit
//   GET  /api/strategy/status  StrategyStatus（无状态惰性轮询：每次现读 run_dir 产物）
//   POST /api/strategy/stop    {stopped:true,pid,orphan?} | 400 无进行中运行
//                              （orphan marker 清理也走此路由）
//   GET  /api/strategy/result  StrategyResult（仅 done/stopped；404 无结果 / 409 运行中）
//
// status 无状态（产物文件 + pid 推导）→ 页面刷新/重开弹窗即恢复进度；
// orphan = 内存态空 + marker 在（server 重启后的遗留 run），带 alive/pid/doc_id
// 三键（active 态不带），由前端提供清理动作（调 stop）。

import type { PerTypeOverrides } from './v03';
import type { PieceInfo, PlacedItem } from './piece';
import type { BandConfig, PrefixConfig } from './ws';

/** 策略模式（与 CLI `--strategy` 一致；race = 方案 B 门杀（默认），se = 方案 A 筛延）。 */
export type StrategyMode = 'se' | 'race';

/**
 * 运行族（US-003 极限运行前端）：strategy = 高级运行（/api/strategy/*，
 * se/race 双模式）；extreme = 极限运行（/api/extreme/*，US-002 后端四路由）。
 * 后端两族共用每会话状态槽 —— 同族/跨族 status 语义见 strategyStore ownsMode。
 */
export type RunFamily = 'strategy' | 'extreme';

/** 弹窗时长四档（分钟）→ 后端 `--time` 秒数 = minutes * 60。 */
export type StrategyMinutes = 10 | 20 | 30 | 60;

/** 状态机七态（与 status.state 字符串一一对应；orphan 仅 status 出现）。 */
export type StrategyPhase =
  | 'idle'
  | 'starting'
  | 'running'
  | 'done'
  | 'stopped'
  | 'error'
  | 'orphan';

/** start 请求体（排料参数与主画布 handleStart 同源 —— collectStartContext 共用）。 */
export interface StrategyStartPayload {
  mode: StrategyMode;
  minutes: StrategyMinutes;
  /** base seed（CLI 种子流从它起 max+1 补齐）。 */
  seed: number;
  /** 幅宽 mm（>0 覆盖后端 state；与 WS StartPayload.gate_mm 同口径）。 */
  gate_mm: number;
  /** 码号列表（空列表会被后端 400 —— 前端执行按钮已按 sizes 空禁用兜底）。 */
  sizes?: number[];
  /** 每裁片（g 码）d/tol 覆盖；null = 不写键（后端全片默认 0）。 */
  per_type?: PerTypeOverrides | null;
  /** per-size demand（label → sizeKey → 数量）；null = 后端全片 demand=1。 */
  quantities?: Record<string, Record<string, number>> | null;
  /**
   * 腰头成带（2026-08-22 解除与策略运行互斥）：与 WS StartPayload.band 同形，
   * collectStartContext 同源产物直传；null / enabled falsy = 不写进 config
   * （后端 _parse_band 同一校验点，非法 → 400 结构化 error）。
   */
  band?: BandConfig | null;
  /**
   * 起始端成套前后幅（2026-08-25 解除与策略运行互斥，band 同款）：与 WS
   * StartPayload.prefix 同形，collectStartContext 同源产物直传；null /
   * enabled falsy = 不写进 config（后端 _parse_prefix 同一校验点 —— 含 2+2
   * 资格码 start 期拦截，非法 → 400 结构化 error）。
   */
  prefix?: PrefixConfig | null;
}

/**
 * POST /api/extreme/start 请求体（US-002；US-003 前端接入）。
 * time_total_s = 总预算秒（整数，后端值域 905~43200 —— 前端预设 60/120/240/480
 * 分钟 + 自定义 16~720 分钟恒在值域内）；**无 band/prefix 键**（后端按键判在场即
 * 400「暂不支持」—— 前端执行按钮对 band/prefix 开启直接置灰前置拦截）。排料
 * 参数（seed/gate_mm/sizes/per_type/quantities）与 StrategyStartPayload 同源 ——
 * collectStartContext 单一实现共用。
 */
export interface ExtremeStartPayload {
  /** 总预算秒（minutes × 60）。 */
  time_total_s: number;
  seed: number;
  gate_mm: number;
  sizes?: number[];
  per_type?: PerTypeOverrides | null;
  quantities?: Record<string, Record<string, number>> | null;
}

/** strategy.json → plan 摘要（race 带 gate_seconds；se 带 k_screens/screen_s/ext_s）。 */
export interface StrategyPlan {
  planned_seeds?: number[] | null;
  /** race：门时刻（秒，= race_budget × gate_tau，默认 180×0.5=90）。 */
  gate_seconds?: number | null;
  /** se：筛选轮数 / 单轮筛选秒 / 冠军延长秒。 */
  k_screens?: number | null;
  screen_s?: number | null;
  ext_s?: number | null;
}

/** result.json portfolio.incumbent 摘要（status 控载荷，无 placed_items）。 */
export interface StrategyIncumbentSummary {
  density: number;
  width_mm: number;
  seed: number;
  frame_index: number;
  elapsed: number;
}

/** 最新 mtime best_frame_s*.json（当前 seed 的 live best；ext = SE 延长进行中）。 */
export interface StrategyCurrentSeed {
  seed: number | null;
  density: number | null;
  density_sparrow: number | null;
  ext: boolean;
}

/** result.json portfolio.per_seed 条目（逐 seed 收尾入账）。 */
export interface StrategyPerSeedEntry {
  seed: number;
  killed: boolean;
  kill_reason: string | null;
  best_density: number | null;
  elapsed: number | null;
  /** 策略模式附带：race / screen / extension。 */
  phase?: string | null;
}

/** 事件流（status 只保留尾部窗口；门杀/延长/seed 收尾三类）。 */
export type StrategyEvent =
  | {
      kind: 'gate';
      seed: number | null;
      t: number | null;
      d: number | null;
      /** S_tau 重载 = race 门值 bar 参照（首 seed 豁免时 null）。 */
      bar: number | null;
      would_kill: boolean | null;
    }
  | { kind: 'extension'; seed: number }
  | {
      kind: 'seed_done';
      seed: number | null;
      phase: string | null;
      best_density: number | null;
      killed: boolean;
    };

/** GET /api/strategy/status 响应（idle 只带 state；orphan 另带 alive/pid/doc_id）。 */
export interface StrategyStatus {
  state: StrategyPhase;
  /** 极限运行（US-002 起）status.mode = 'extreme'（状态槽 mode 透传）。 */
  mode?: StrategyMode | 'extreme' | null;
  total_budget_sec?: number | null;
  /** 墙钟口径（≈，含启动开销），秒。 */
  elapsed_sec?: number | null;
  run_dir?: string | null;
  plan?: StrategyPlan | null;
  incumbent?: StrategyIncumbentSummary | null;
  current?: StrategyCurrentSeed | null;
  per_seed?: StrategyPerSeedEntry[];
  events?: StrategyEvent[];
  error?: string | null;
  exit_code?: number | null;
  /** 以下三键仅 orphan 态。 */
  alive?: boolean | null;
  pid?: number | null;
  doc_id?: string | null;
}

/** result 端点 best（incumbent 全量 / stopped 回落 best_frame 最大者）。 */
export interface StrategyBest {
  seed: number | null;
  frame_index: number | null;
  elapsed: number | null;
  /** 原面积口径（版师生死线口径）。 */
  density: number | null;
  density_sparrow: number | null;
  width_mm: number | null;
  placed_items: PlacedItem[];
}

/** result.json portfolio.race 子段。 */
export interface StrategyRaceSummary {
  gate_seconds: number;
  kept_seeds: number[];
  gated_seeds: number[];
}

/** result.json portfolio.se 子段。 */
export interface StrategySeSummary {
  k_screens: number;
  screen_s: number;
  ext_s: number;
  champion: number | null;
}

/** result.json portfolio 段摘要（per_seed + mode + 模式子段）。 */
export interface StrategySummary {
  per_seed: StrategyPerSeedEntry[];
  mode: StrategyMode | null;
  race?: StrategyRaceSummary;
  se?: StrategySeSummary;
}

/** result 端点 manifest（与 /ws/solve manifest 同构：start 时快照口径 build_pid_meta）。 */
export interface StrategyManifest {
  gate_mm: number;
  total_area_mm2: number;
  n_eroded: number;
  pieces: PieceInfo[];
}

/**
 * GET /api/strategy/result 响应（US-006 应用到主画布的数据源）。
 * best 含完整 placed_items（incumbent 帧级全局最优；stopped 回落 best_frame 最大者）。
 */
export interface StrategyResult {
  state: 'done' | 'stopped';
  /** 极限运行 result.mode = 'extreme'（状态槽透传；summary.mode 仍是 'race'）。 */
  mode: StrategyMode | 'extreme' | null;
  run_dir: string | null;
  manifest: StrategyManifest;
  best: StrategyBest;
  summary: StrategySummary;
  /** 母版漂移（start 快照 doc_id ≠ 当前画布）时后端附带。 */
  warning?: string;
}
