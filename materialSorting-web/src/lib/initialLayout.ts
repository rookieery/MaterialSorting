// initialLayout.ts —— 初始布局（warm 热启动，prd-initial-layout）前端 API 封装
// （US-004，2026-10-03）。
//
// 职责（纯请求出口 + 响应形状守卫，生成/保存编排留在 US-006 弹窗）：
//   1. fetchWarmCapability：GET /api/warm-capability（US-001 成品，无会话依赖
//      —— 热启动能力是 spyrrow 装载态的进程级属性）。恒 200 {supported, version}；
//      探测失败抛 Error（message 中文）—— 调用方（initialLayoutStore.
//      probeCapability）catch 后保持 supported=null（未知 = 不置灰不拦截）。
//   2. generateInitialLayout：POST /api/initial-layout/generate（US-002 成品，
//      会话族端点），apiFetch POST JSON（样板 = editPolish.postEditPolish）。
//      body = WS StartPayload 同形子集 {sizes?, per_type?, quantities?, params?,
//      gate_mm?, band?, prefix?, seed?}；响应 = {ok, manifest, placed, width_mm,
//      density, composite?, prefix?}：
//        - manifest 与 WS 前端契约同形（_build_manifest_msg 单一真相源）；
//        - placed = 密度最大可行帧**展开视图**三键条目（永无 WB_/PS_）；
//        - composite 段仅 band/prefix 开时在场 —— {placed_items(展开前组合宇宙，
//          含 WB_/PS_), demand_map}（US-006 保存 warm 组合载荷的数据源）；
//        - prefix 段 = worker final 统计段（prefix 开时在场）。
//      失败抛 Error（message 中文可直显弹窗红字：网络错 / 4xx·409·502 error
//      文案透传 / 形态异常）；401 session code 由 apiFetch 拦截触发全局阻断
//      弹窗（fail-fast 正确行为），本函数照常抛错（遮罩下不可见，无害）。

import { apiFetch } from './api';
import type { PlacedItem, Pt } from '../types/piece';
import type {
  BandConfig,
  FinalPrefixStats,
  ManifestMsg,
  PrefixConfig,
} from '../types/ws';
import type { PerTypeOverrides, SolveParams } from '../types/v03';

/** GET /api/warm-capability 响应（恒 200：supported = spyrrow 是否支持
 *  initial_solution 热启动；version = 实装版本串，包缺失 → '(未安装)'）。 */
export interface WarmCapability {
  supported: boolean;
  version: string;
}

/** GET /api/warm-capability（失败抛 Error，message 中文；调用方 catch 静默降级）。 */
export async function fetchWarmCapability(): Promise<WarmCapability> {
  const res = await apiFetch('/api/warm-capability');
  if (!res.ok) {
    throw new Error(`热启动能力探测失败（HTTP ${res.status}）`);
  }
  let data: unknown;
  try {
    data = await res.json();
  } catch {
    throw new Error('热启动能力探测失败：响应不是有效 JSON');
  }
  const d = data as { supported?: unknown; version?: unknown } | null;
  if (
    !d ||
    typeof d !== 'object' ||
    typeof d.supported !== 'boolean' ||
    typeof d.version !== 'string'
  ) {
    throw new Error('热启动能力探测失败：响应形态异常');
  }
  return { supported: d.supported, version: d.version };
}

/** POST /api/initial-layout/generate 请求载荷（WS StartPayload 同形子集；全部
 * 可缺省 —— 缺省沿用会话 / 求解缺省值，gate_mm 正值覆盖 intermediate 门幅）。 */
export interface GenerateInitialLayoutBody {
  sizes?: number[];
  per_type?: PerTypeOverrides | null;
  quantities?: Record<string, Record<string, number>> | null;
  params?: SolveParams;
  gate_mm?: number;
  band?: BandConfig | null;
  prefix?: PrefixConfig | null;
  seed?: number;
}

/** composite 段条目（展开前 solver 原始三键条目，**含 WB_/PS_ 组合 pid** ——
 * 仅存活在生成响应 / warm 载荷内，永不经 WS 帧下发）。 */
export interface CompositePlacedItem {
  id: string;
  rotation: number;
  translation: Pt;
}

/** composite 段（仅 band/prefix 开时在场；US-006 保存 warm 组合载荷的数据源：
 * placed_items = 展开前组合宇宙，demand_map = worker 实例宇宙 {pid: demand}）。 */
export interface CompositeLayout {
  placed_items: CompositePlacedItem[];
  demand_map: Record<string, number>;
}

/** POST /api/initial-layout/generate 成功响应（ok 键已校验剥离）。 */
export interface InitialLayoutResult {
  /** WS 前端契约同形（US-006 合成伪 RunRecord 直用）。 */
  manifest: ManifestMsg;
  /** 密度最大可行帧展开视图全条目（永无 WB_/PS_）。 */
  placed: PlacedItem[];
  /** 该帧物理包络料长 mm（US-006 保存 widthMm）。 */
  width_mm: number;
  /** 原面积口径密度（0..100）。 */
  density: number;
  /** 仅 band/prefix 开时在场（形状守卫滤过畸形段）。 */
  composite?: CompositeLayout;
  /** prefix 开时在场（worker final 统计段）。 */
  prefix?: FinalPrefixStats;
}

/** composite 段形状守卫（半截/畸形段 → 视为缺席，调用方按 plain 降级）。 */
function isCompositeLayout(v: unknown): v is CompositeLayout {
  if (typeof v !== 'object' || v === null) return false;
  const d = v as Record<string, unknown>;
  return Array.isArray(d.placed_items) && typeof d.demand_map === 'object' && d.demand_map !== null;
}

/** prefix 统计段形状守卫（best-effort：pid 字符串即可，明细字段前端只透传展示）。 */
function isPrefixStats(v: unknown): v is FinalPrefixStats {
  if (typeof v !== 'object' || v === null) return false;
  return typeof (v as Record<string, unknown>).pid === 'string';
}

/** POST /api/initial-layout/generate（失败抛 Error，message 中文可直显弹窗红字）。 */
export async function generateInitialLayout(
  body: GenerateInitialLayoutBody,
): Promise<InitialLayoutResult> {
  const res = await apiFetch('/api/initial-layout/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `初始布局生成失败（HTTP ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: unknown } | null;
      if (data && typeof data.error === 'string' && data.error) {
        msg = `初始布局生成失败：${data.error}`;
      }
    } catch {
      /* 非 JSON 错误体 → 保留状态码文案 */
    }
    throw new Error(msg);
  }
  let data: unknown;
  try {
    data = await res.json();
  } catch {
    throw new Error('初始布局生成失败：响应不是有效 JSON');
  }
  const d = data as {
    ok?: unknown;
    manifest?: unknown;
    placed?: unknown;
    width_mm?: unknown;
    density?: unknown;
    composite?: unknown;
    prefix?: unknown;
  } | null;
  if (!d || d.ok !== true || !d.manifest || !Array.isArray(d.placed)) {
    throw new Error('初始布局生成失败：响应形态异常');
  }
  return {
    manifest: d.manifest as ManifestMsg,
    placed: d.placed as PlacedItem[],
    width_mm: d.width_mm as number,
    density: d.density as number,
    ...(isCompositeLayout(d.composite) ? { composite: d.composite } : {}),
    ...(isPrefixStats(d.prefix) ? { prefix: d.prefix } : {}),
  };
}
