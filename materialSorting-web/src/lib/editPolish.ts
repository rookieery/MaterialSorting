// editPolish.ts —— 编辑排料「智能微调」前端接线库（prd-edit-polish US-003，2026-09-05；
// US-005 补 compact 压缩回收档载荷键；edit-keyboard US-003 补 placed 项 mirror 键；
// 2026-10-06 压线收敛批次：exclude 恢复态回退 form（C）+ per_type 载荷键（B2））。
//
// 职责（纯数据组装 + 单一请求出口，几何真相源留在 Python）：
//   1. buildPolishPayload：当前 working placements + run.manifest.gate_mm + exclude
//      best-effort 组装（布局态后端不存、随 body 带上 = /export 同模式）：
//        - run 带 band 配置（enabled 且 label 在案）→ exclude.labels = [label]
//          （带形态区域 = 腰头 g 码全部成员，微调永不动，引擎按 label 命中）；
//        - 2026-10-06 C：run.band 缺席（恢复态/策略合成 run —— RunRecord.band 恒
//          null）回退 formStore.form（恢复会话已水合 band_enabled/band_label）；
//          prefix 同理回退 form 的 front/back 整 label 排除（成员级精确排除仅活
//          run 的 final.prefix 可解析，恢复态无从得知 → over-conservative，与
//          既有备案口径一致）。882 恢复态实勘：无此回退时微调拆开带链对齐。
//        - final 带 prefix 统计段（RunRecord.prefix）→ exclude.pids = 组合片 pid
//          解析出的成员 pid 集合（成套起始端 4+1 片，微调永不动）；
//        - 两者皆无 → 载荷省略 exclude 键；
//        - compact（US-005 压缩回收档）：勾选时 compact:true 随下次微调请求发出，
//          未勾选省略键（服务端缺省 false，additive）；
//        - per_type（2026-10-06 B2）：collectPerType(form.per_type) 非空时随载荷
//          发出（omit-when-empty：空配置省略键 = 服务端走旧毛版口径，线格式
//          零回归）—— 后端经 build_pid_meta 同一管线转碰撞轮廓，守卫③按
//          「d 预算内保留压线不误杀」的碰撞口径裁决。
//   2. postEditPolish：apiFetch POST /api/edit-polish（会话族端点 US-002 成品），
//      失败抛 Error（message 中文可直显进对比卡：网络错 / 4xx error 文案透传）；
//      401 session code 由 apiFetch 拦截触发全局阻断弹窗（fail-fast 正确行为），
//      本函数照常抛错落卡内文案（弹窗遮罩下不可见，无害）。
//
// 口径注记（PRD FR-2 / 对比卡脚注同文）：polish 报告七指标全部按**物理毛版轮廓**
// 口径（会话 pieces_by_id 原始 polygon，与 /export 同源）；编辑画布红字告警按
// erode 后轮廓口径 —— 数值可能偏小，差异属预期非 bug。

import { apiFetch } from './api';
import { collectPerType } from './params';
import { useFormStore } from '../store/formStore';
import type { FormState } from './params';
import type { PerTypeOverrides } from '../types/v03';
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
  /** 贴附 pass move 计数（2026-10-05 attach 默认启用，additive）。 */
  attach_moves: number;
  /** 逃逸兜底 move 计数（2026-10-06 derotate/separate-escape，additive）。 */
  escape_moves: number;
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
  /**
   * per_type 高级配置（2026-10-06 B2 压线收敛，omit-when-empty）：collectPerType
   * 清洗后的 {g码: {d, tol}} —— 后端转 per-pid 碰撞轮廓，微调守卫按碰撞口径
   * （d 预算内保留压线不误杀候选）裁决；空配置省略键 = 旧毛版口径零回归。
   */
  per_type?: PerTypeOverrides;
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
 * 2026-10-06 C：run 记录缺席（恢复态/策略合成 run，RunRecord.band 恒 null）回退
 * form（band_enabled/band_label 已随恢复水合；prefix 回退 front/back 整 label
 * 排除 —— 成员级精确解析仅活 run 的 final.prefix 可得，over-conservative 与
 * 既有备案口径一致）；两者皆无 → undefined（载荷省略 exclude 键）。
 */
export function buildExclude(
  run: RunRecord | null,
  form?: FormState,
): { labels?: string[]; pids?: string[] } | undefined {
  const labels: string[] = [];
  const pids: string[] = [];
  const f = form ?? null;
  const runBand = run?.band?.enabled && run.band.label ? run.band.label : null;
  const formBand = f && f.band_enabled && f.band_label.trim() ? f.band_label.trim() : null;
  const bandLabel = runBand ?? formBand;
  if (bandLabel) labels.push(bandLabel);
  const pf = run?.prefix ?? null;
  if (pf && typeof pf.pid === 'string' && pf.pid) {
    pids.push(...parsePrefixMemberPids(pf.pid, pf.size ?? null, pf.extra ?? null));
  } else if (f && f.prefix_enabled && f.prefix_front.trim() && f.prefix_back.trim()) {
    for (const lab of [f.prefix_front.trim(), f.prefix_back.trim()]) {
      if (!labels.includes(lab)) labels.push(lab);
    }
  }
  if (!labels.length && !pids.length) return undefined;
  const out: { labels?: string[]; pids?: string[] } = {};
  if (labels.length) out.labels = labels;
  if (pids.length) out.pids = pids;
  return out;
}

/**
 * 组装微调载荷（working placements + manifest.gate_mm + exclude + compact +
 * per_type）。
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
  const exclude = buildExclude(run, useFormStore.getState().form);
  if (exclude) payload.exclude = exclude;
  if (compact) payload.compact = true;
  const perType = collectPerType(useFormStore.getState().form.per_type);
  if (perType) payload.per_type = perType;
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
