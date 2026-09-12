// 状态文件（.msn）保存/恢复的前端契约类型（状态文件 US-003）。
//
// 与后端 `web/statefile.py`（/api/state-save、/api/state-restore）及设计
// `.docs/business/状态文件保存恢复_落地方案.md` §四 schema v1 对齐：
//   - form 块 = FormState 全量原样入文件（lib/params 同构）；
//   - quantities = {label:{sizeKey:N}} 原生扁平形态（qtyStore 序列化口径）；
//   - quantities_base = {label:N} 整列设值基准（qtyStore baseValue；省键式：
//     只存 ≠1 的行，缺席 = 全 1 默认 = 旧文件口径，additive 不 bump v1，
//     2026-09-12）；
//   - run 块仅 done 态入文件（缺席 = 纯配置档，端点容忍但 UI 经 lastFrame
//     门槛不可达 —— 契约注记见 agent-api-reference）；
//   - placed 同 pid 多副本 = 数组多条（绝不 pid 去重）；mirror omit-when-false
//     （editStore.deepCopyItems 同口径）。
//
// form 用 type-only import 引 lib/params（编译期擦除 —— types 层零运行时依赖）。

import type { FormState } from '../lib/params';
import type { ParsedDoc } from './parsed';
import type { PlacedItem } from './piece';
import type { ManifestMsg } from './ws';

/** provenance.kind 四值枚举（后端 statefile._PROVENANCE_KINDS 同源）。 */
export type RunProvenanceKind = 'solve' | 'strategy_se' | 'strategy_race' | 'extreme';

/**
 * 结果来源（展示级冗余，不承重）：run.provenance 与 RunRecord.origin 同形。
 * config 形态宽松（strategy 族 {minutes} / extreme 族 {time_total_s}），仅来源
 * 小字回显（US-004 `run-provenance`），可被手改不影响任何计算/导出。
 */
export interface RunProvenance {
  kind: RunProvenanceKind;
  config?: Record<string, unknown>;
}

/**
 * RunRecord.origin 的类型别名：恢复/保存两端 provenance 的取数中转。
 * WS 普通求解不设（undefined = 'solve'，保存端不写 provenance 键）；
 * US-004 起 applyStrategyResult / applyRestorePayload 写入。
 */
export type RunOrigin = RunProvenance;

/** run.final 摘要（保存时从 RunRecord 派生；恢复端只读展示，编辑后由前端重算）。 */
export interface StateRunFinal {
  /** 原面积口径 total_area/(width×gate)（编辑保存后由 applyToRun 同口径更新）。 */
  density: number;
  /** erode 后 sparrow 自报密度（参考）。 */
  density_sparrow: number;
  width_mm: number;
  /** 求解耗时 s（lastFrame.elapsed）。 */
  elapsed: number;
  n_frames: number;
  n_eroded: number;
}

/** 状态文件 run 块（schema §四；restore 响应 additive 整块透传）。 */
export interface StateSaveRun {
  seed: number;
  /** 缺省 = 'solve'（v1 内可省键，向后兼容手改文件）。 */
  provenance?: RunProvenance;
  final: StateRunFinal;
  placed: PlacedItem[];
}

/** POST /api/state-save 请求体（lib/stateFile.buildSavePayload 产物）。 */
export interface StateSavePayload {
  /** FormState 全量原样（formStore 当前值）。 */
  form: FormState;
  /** qtyStore 扁平化 {label:{sizeKey:N}}；空矩阵 → null（后端 demand 全 1 口径）。 */
  quantities: Record<string, Record<string, number>> | null;
  /** qtyStore baseValue 收集 {label:N}（省键式：只收 ≠1 的行，全 1 → 整键缺席）。 */
  quantities_base?: Record<string, number>;
  /** 仅 done 态 bestRun 入；无 run 时整键缺席（纯配置档）。 */
  run?: StateSaveRun;
}

/**
 * POST /api/state-restore 响应（US-004 applyRestorePayload 消费；本 story 声明
 * 契约 + .msn 上传分流最小处理，恢复编排接线属下一 Story）。
 * final/placed = run 块摘出（无 run 纯配置档均 null）；run 块 additive 整块
 * 透传（seed/provenance 供前端恢复写回来源）。
 */
export interface StateRestoreResponse {
  doc_id: string;
  filename: string;
  parse: ParsedDoc;
  /** build_pid_meta 确定性重算（on_manifest 同形，无 type 判别键）。 */
  manifest: Omit<ManifestMsg, 'type'>;
  final: StateRunFinal | null;
  placed: PlacedItem[] | null;
  run: StateSaveRun | null;
  form: FormState;
  quantities: Record<string, Record<string, number>> | null;
  /** 整列设值基准回传（省键式文件缺席 → null → hydrateFlat no-op 保持默认 1）。 */
  quantities_base: Record<string, number> | null;
}
