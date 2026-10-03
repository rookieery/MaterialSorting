// initialLayout.ts —— 初始布局（warm 热启动，prd-initial-layout）前端 API 封装
// （US-004，2026-10-03；US-006 补保存组装纯函数 assembleWarmPlaced/plainWarmPlaced）。
//
// 职责（请求出口 + 响应形状守卫 + 保存组装纯函数；生成/保存**编排**留在 US-006 弹窗）：
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

// ------------------------------------------------ US-006 保存组装（纯函数）
//
// 「保存当前布局」的 warmPlaced 组装：编辑画布操作的是**展开视图**（working，
// 永无 WB_/PS_），而 band/prefix 开启时 WS initial 载荷需要**组合宇宙**条目
// （WB_/PS_ 组合片只存活在生成响应 composite / worker 实例内，展开后几何不可
// 重建 —— 后端 build_warm_payload 对组合 pid 无原始轮廓）。桥接口径 = 组位移
// 记账：组合片随整组刚性平移（EditCanvas US-005 组拖语义，组内单片不可编辑），
// 故组合条目 translation += 组 delta（= 组内任一成员当前位移相对生成基线；
// 基线 = editStore.open 伪 run 时快照 —— 生成 placed 或续编 saved.displayPlaced）；
// 非成员条目展开视图与组合视图同 pid 同几何，直接取当前 working 最新编辑值。

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

/** US-006 组成员判定上下文：band 开 = 腰头 g 码 label；prefix 开 = 组合片成员
 * pid 集（parsePrefixMemberPids 产物，含异码补片）。两者均空 = plain（无组）。 */
export interface WarmGroupContext {
  bandLabel: string | null;
  prefixPids: readonly string[];
}

/** pid 是否 band 组成员（`{label}_` 前缀 —— 尾下划线防 g05/g051 前缀误吞；
 * band 组 = 该 g 码**全部副本**，与 EditCanvas 组拖「含同 pid 全部副本」同口径）。 */
function isBandMemberPid(pid: string, label: string): boolean {
  return pid.startsWith(`${label}_`);
}

/**
 * 组位移 delta（US-006 记账基元）：组内**首个** working 成员相对基线同下标成员
 * 的平移差。整组只可刚性平移（EditCanvas US-005：组内单片不可编辑）⇒ 任一成员
 * 同值；无成员（理论不达 —— 展开视图必含组成员）/ 下标 id 错位 → null（调用方
 * 按零位移处理，宁可保基线位置也不丢条目 —— 守恒优先）。
 */
function groupDelta(
  working: readonly PlacedItem[],
  baseline: readonly PlacedItem[],
  isMember: (pid: string) => boolean,
): Pt | null {
  for (let i = 0; i < working.length && i < baseline.length; i++) {
    if (!isMember(working[i].id)) continue;
    if (baseline[i].id !== working[i].id) return null;
    return [
      working[i].translation[0] - baseline[i].translation[0],
      working[i].translation[1] - baseline[i].translation[1],
    ];
  }
  return null;
}

/**
 * band/prefix 开启时的 warmPlaced 组装（US-006 保存闸单一实现）：
 *   - 组合基线（生成响应 composite.placed_items / 续编 saved.warmPlaced）中
 *     `WB_` 条目 += band delta、`PS_` 条目 += prefix delta（双开两组独立记账），
 *     非组组合条目**跳过**（由当前 working 非成员条目承接最新编辑值）；
 *   - 当前 working 的非成员条目按三键形态（mirror 剥离 —— 生成产物无镜像，
 *     allowMirror=false 编辑不可能引入，防御性丢弃）拼接在末尾。
 * 守恒口径：|out| = |组合基线| = |working| = Σ demand（组展开副本数与组合条目
 * 数互补，见 PRD US-006 vitest 条目）。
 */
export function assembleWarmPlaced(
  working: readonly PlacedItem[],
  baseline: readonly PlacedItem[],
  composite: readonly CompositePlacedItem[],
  groups: WarmGroupContext,
): CompositePlacedItem[] {
  const ZERO: Pt = [0, 0];
  const bandD =
    groups.bandLabel != null
      ? (groupDelta(working, baseline, (pid) =>
          isBandMemberPid(pid, groups.bandLabel!),
        ) ?? ZERO)
      : ZERO;
  const prefixD =
    groups.prefixPids.length > 0
      ? (groupDelta(working, baseline, (pid) =>
          groups.prefixPids.includes(pid),
        ) ?? ZERO)
      : ZERO;
  const out: CompositePlacedItem[] = [];
  for (const it of composite) {
    if (it.id.startsWith('WB_')) {
      out.push({
        id: it.id,
        rotation: it.rotation,
        translation: [it.translation[0] + bandD[0], it.translation[1] + bandD[1]],
      });
      continue;
    }
    if (it.id.startsWith('PS_')) {
      out.push({
        id: it.id,
        rotation: it.rotation,
        translation: [it.translation[0] + prefixD[0], it.translation[1] + prefixD[1]],
      });
    }
    // 非组组合条目：跳过 —— 下方由当前 working 非成员条目拼接（最新编辑值）。
  }
  for (const it of working) {
    const member =
      (groups.bandLabel != null && isBandMemberPid(it.id, groups.bandLabel)) ||
      groups.prefixPids.includes(it.id);
    if (member) continue;
    out.push({
      id: it.id,
      rotation: it.rotation,
      translation: [it.translation[0], it.translation[1]],
    });
  }
  return out;
}

/**
 * plain（band/prefix 关）warmPlaced 组装：working 全条目三键形态（后端
 * build_pid_meta 投影宇宙，pid 逐位一致）。mirror 剥离同 assembleWarmPlaced。
 */
export function plainWarmPlaced(working: readonly PlacedItem[]): CompositePlacedItem[] {
  return working.map((it) => ({
    id: it.id,
    rotation: it.rotation,
    translation: [it.translation[0], it.translation[1]],
  }));
}
