// editPolish.ts —— 编辑排料「智能微调」前端接线库（prd-edit-polish US-003，2026-09-05；
// US-005 补 compact 压缩回收档载荷键；edit-keyboard US-003 补 placed 项 mirror 键）。
//
// 职责（纯数据组装 + 单一请求出口，几何真相源留在 Python）：
//   1. buildPolishPayload：当前 working placements + run.manifest.gate_mm + exclude
//      best-effort 组装（布局态后端不存、随 body 带上 = /export 同模式）：
//        - run 带 band 配置（enabled 且 label 在案）→ exclude.labels = [label]
//          （带形态区域 = 腰头 g 码全部成员，微调永不动，引擎按 label 命中）；
//        - final 带 prefix 统计段（RunRecord.prefix）→ exclude.pids = 组合片 pid
//          解析出的成员 pid 集合（成套起始端 4+1 片，微调永不动）；
//        - 两者皆无（含策略合成 run —— 无 WS final.prefix 记录）→ 载荷省略 exclude
//          键（best-effort，over-conservative 可接受：同 pid 其他副本一并跳过）；
//        - compact（US-005 压缩回收档）：勾选时 compact:true 随下次微调请求发出，
//          未勾选省略键（服务端缺省 false，additive）。
//   2. postEditPolish：apiFetch POST /api/edit-polish（会话族端点 US-002 成品），
//      失败抛 Error（message 中文可直显进对比卡：网络错 / 4xx error 文案透传）；
//      401 session code 由 apiFetch 拦截触发全局阻断弹窗（fail-fast 正确行为），
//      本函数照常抛错落卡内文案（弹窗遮罩下不可见，无害）。
//
// 口径注记（PRD FR-2 / 对比卡脚注同文）：polish 报告七指标全部按**物理毛版轮廓**
// 口径（会话 pieces_by_id 原始 polygon，与 /export 同源）；编辑画布红字告警按
// erode 后轮廓口径 —— 数值可能偏小，差异属预期非 bug。

import { apiFetch } from './api';
import type { PlacedItem } from '../types/piece';
import type { RunRecord } from '../store/runRegistry';

/** polish 前后对比指标段（引擎 _diagnose 七指标，前后同形）。 */
export interface PolishMetrics {
  overlap_pairs: number;
  max_penetration_mm: number;
  total_overlap_area_mm2: number;
  rotated_pieces: number;
  rotation_dev_sum_deg: number;
  width_mm: number;
  /** real 口径密度百分数（0..100，引擎 ×100 后 round 3）。 */
  density: number;
}

/** polish 报告（引擎 polish_layout report 段，moves/residual 明细前端只透传展示）。 */
export interface PolishReport {
  before: PolishMetrics;
  after: PolishMetrics;
  moves: unknown[];
  residual: unknown[];
  excluded: number[];
  elapsed_sec: number;
}

/** POST /api/edit-polish 请求载荷。 */
export interface PolishPayload {
  /**
   * placed 项 mirror（edit-keyboard US-003，omit-when-false）：镜像片带 mirror:true，
   * 无镜像项不带键（后端按镜像几何微调并透传回响应）。
   */
  placed: { id: string; rotation: number; translation: [number, number]; mirror?: boolean }[];
  gate_mm: number;
  exclude?: { labels?: string[]; pids?: string[] };
  /** US-005 压缩回收档（false 省略键 = 服务端缺省同值，additive）。 */
  compact?: boolean;
}

/** POST /api/edit-polish 成功响应（ok 键已校验剥离）。 */
export interface PolishResult {
  placed: PlacedItem[];
  report: PolishReport;
}

/**
 * 解析 prefix 组合片 pid → 成员 pid 集合（pid = f'{label}_{size}' 全链路主键，
 * load_pieces.py 权威式；组合片形如 'PS_g02+g03@34+g02@32' —— **首段 front 是裸
 * label 无 @size**（PS_{front}+{back}@{size} 权威式，前后幅同套装码），size 取
 * stats.size 补全；后续段 'label@size'。extra.pid 为真实 pid 直收）。解析失败段
 * 静默跳过（best-effort，与引擎 exclude over-conservative 口径一致）。
 */
export function parsePrefixMemberPids(
  pid: string,
  size: number | null,
  extra: { pid?: string } | null | undefined,
): string[] {
  const out: string[] = [];
  if (typeof pid === 'string' && pid.startsWith('PS_')) {
    const szStr = size != null ? String(size) : null;
    for (const raw of pid.slice(3).split('+')) {
      const seg = raw.trim();
      if (!seg) continue;
      const at = seg.lastIndexOf('@');
      if (at >= 0) {
        // label@size 形态：两端任一为空 = 畸形段，跳过（best-effort 不猜）
        const label = seg.slice(0, at).trim();
        const s = seg.slice(at + 1).trim();
        if (label && s && !out.includes(`${label}_${s}`)) out.push(`${label}_${s}`);
      } else {
        // 裸 label（front 段）：size 取 stats.size 补全；无从补全则跳过
        if (szStr && !out.includes(`${seg}_${szStr}`)) out.push(`${seg}_${szStr}`);
      }
    }
  }
  const ep = typeof extra?.pid === 'string' ? extra.pid : '';
  if (ep && !out.includes(ep)) out.push(ep);
  return out;
}

/**
 * exclude best-effort 组装（详见文件头）：band → labels 键；final.prefix → pids 键；
 * 两者皆无 → undefined（载荷省略 exclude 键）。
 */
export function buildExclude(
  run: RunRecord | null,
): { labels?: string[]; pids?: string[] } | undefined {
  const labels: string[] = [];
  const pids: string[] = [];
  if (run?.band && run.band.enabled && run.band.label) labels.push(run.band.label);
  const pf = run?.prefix ?? null;
  if (pf && typeof pf.pid === 'string' && pf.pid) {
    pids.push(...parsePrefixMemberPids(pf.pid, pf.size ?? null, pf.extra ?? null));
  }
  if (!labels.length && !pids.length) return undefined;
  const out: { labels?: string[]; pids?: string[] } = {};
  if (labels.length) out.labels = labels;
  if (pids.length) out.pids = pids;
  return out;
}

/**
 * 组装微调载荷（working placements + manifest.gate_mm + exclude + compact）。
 * @param compact US-005 压缩回收档（缺省 false = 省略键，服务端缺省同值 additive）。
 * @returns null = run 无 manifest / working 空（不可微调，调用方不应发请求）。
 */
export function buildPolishPayload(
  working: readonly PlacedItem[],
  run: RunRecord | null,
  compact = false,
): PolishPayload | null {
  const manifest = run?.manifest ?? null;
  if (!manifest || working.length === 0) return null;
  const payload: PolishPayload = {
    // mirror omit-when-false 透传（edit-keyboard US-003）：恒发 mirror:false 会红掉
    // EditLayoutModal.polish 精确锁键集用例 —— 「有镜像才带键」。
    placed: working.map((it) => ({
      id: it.id,
      rotation: it.rotation,
      translation: [it.translation[0], it.translation[1]],
      ...(it.mirror === true ? { mirror: true } : {}),
    })),
    gate_mm: manifest.gate_mm,
  };
  const exclude = buildExclude(run);
  if (exclude) payload.exclude = exclude;
  if (compact) payload.compact = true;
  return payload;
}

/** POST /api/edit-polish（失败抛 Error，message 中文可直显对比卡）。 */
export async function postEditPolish(payload: PolishPayload): Promise<PolishResult> {
  const res = await apiFetch('/api/edit-polish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let msg = `微调失败（HTTP ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: unknown } | null;
      if (data && typeof data.error === 'string' && data.error) msg = `微调失败：${data.error}`;
    } catch {
      /* 非 JSON 错误体 → 保留状态码文案 */
    }
    throw new Error(msg);
  }
  let data: unknown;
  try {
    data = await res.json();
  } catch {
    throw new Error('微调失败：响应不是有效 JSON');
  }
  const d = data as { ok?: unknown; placed?: unknown; report?: unknown } | null;
  if (!d || d.ok !== true || !Array.isArray(d.placed) || !d.report) {
    throw new Error('微调失败：响应形态异常');
  }
  return { placed: d.placed as PlacedItem[], report: d.report as PolishReport };
}
