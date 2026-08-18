// ControlPanel 表单状态 + collectParams 纯函数。
//
// US-019（主面板精简）：删除 d_ext/d_int/tol_ext/tol_int 四档主面板输入，全交高级配置弹窗
// （per_type 显式覆盖 + 后端全局上限兜底 min(d, MAX_OVERLAP_MM=10)/min(tol,
// MAX_ROTATION_TOL_DEG=45)，2026-08-17 起不再按片型钳制）。collectParams 现在 params
// 永远返回全 0，per_type 解析逻辑保留不变（与旧 vanilla 实现 inp.value.trim() !== '' 一致）。
//
// US-004（矩阵化）：per_type 键从「label 单级」改「(label, sizeKey) 两级嵌套」——
// FormState.per_type = { label: { sizeKey: {d, tol} } }，与高级配置弹窗
// 行（码号）× 列（g 码）矩阵一一对应；collectParams / URL 分享格式随动（旧 label 单级
// 键不再产出，解码侧遇到不匹配条目直接忽略）。
//
// 不变量：后端 build_instance 入参契约不变（params 仍传，只是全 0；per_type 仍传）。
//
// 字段都按字符串存储（对应 input.value），collectParams 做解析；这样「空串 vs "0"」可区分
// （per_type 必须：空 = 继承，"0" = 显式 0）。

import type { PerTypeOverrides, PerTypeOverride, SolveParams } from '../types/v03';
import type { PieceQuantityMap } from '../types/qty';

/** 单 (g 码, 码号) 的两条高级覆盖输入（d / tol 各一字符串，空串 = 继承全局默认 0/0）。 */
export interface PerTypeFormValue {
  d: string;
  tol: string;
}

/** FormState.per_type 类型别名：label(g 码) → sizeKey(码号键) → d/tol 输入字符串。 */
export type PerTypeFormMap = Record<string, Record<string, PerTypeFormValue>>;

/** sizeKey 口径与 qtyStore / serializeQuantities 一致：number→String(size)；null→'null'。 */
export function perTypeSizeKey(size: number | null): string {
  return size === null ? 'null' : String(size);
}

/** ControlPanel 表单全量状态（字段都按 input.value 字符串存）。 */
export interface FormState {
  /**
   * 已勾选码号（US-017：动态来自 uploadStore.doc.sizes 或 SIZES fallback，可能含 null）。
   * 默认 `[]`（强制用户选；AC#3 校验「请至少选一个码号」）。
   */
  sizes: (number | null)[];
  /**
   * 幅宽（cm）字符串。×10 转 mm 喂后端 gate_mm（= sparrow strip_height / 排料边框宽度）。
   * 与 time 同样按字符串持有（对应 input.value），交由 parseGate 解析。
   */
  gate: string;
  /** 时长（秒）字符串。 */
  time: string;
  /** base seed 字符串。 */
  seed: string;
  /** 多 seed 对比开关（旧 index.html `#multi_seed` checkbox）。 */
  multi_seed: boolean;
  /** 多 seed 数量字符串（旧 index.html `#seed_count`，默认 "3"，clamp [2,6]）。 */
  seed_count: string;
  /**
   * 每裁片高级覆盖（US-004 矩阵化：两级嵌套 {label: {sizeKey: {d, tol}}}，全部字符串；
   * 来自高级配置弹窗 行(码号)×列(g 码) 矩阵的确定回写）。行集 = doc.sizes（无 doc 时
   * SIZES fallback），列集 = /api/ptypes g 码并集，均动态。空对象 = 全部继承默认 0/0。
   * US-019 起：内外两档全局输入删除，per_type 是唯一的 d/tol 覆盖入口（高级配置弹窗）。
   */
  per_type: PerTypeFormMap;
}

/**
 * 默认值（US-017 起 sizes 默认空数组，强制用户勾选；gate=198cm（=GATE_MM 1980mm），
 * time=120，seed=0；multi_seed 关闭，seed_count=3；per_type 空对象 = 无任何覆盖 =
 * 继承 v0.3 默认 0 —— 裁片键动态出现，仅在弹窗确定后写入）。
 */
export const DEFAULT_FORM: FormState = {
  sizes: [],
  gate: '198',
  time: '120',
  seed: '0',
  multi_seed: false,
  seed_count: '3',
  per_type: {},
};

/** collectParams 输出（与旧 vanilla 实现 collectParams 返回值结构一致）。 */
export interface CollectedParams {
  params: SolveParams;
  /** 空 → null（与旧 vanilla 实现 Object.keys(per_type).length ? per_type : null 一致）。 */
  per_type: PerTypeOverrides | null;
}

/**
 * 把 FormState 解析为 { params, per_type }。
 *
 * 不变量：
 *   - params：US-019 起永远返回全 0（主面板内外两档输入删除，v0.3 上限交给 per_type 显式
 *     覆盖 + 后端全局上限兜底，2026-08-17 起 min(d,10)/min(tol,45) 不再按片型）。
 *   - per_type：US-004 起两级嵌套 {label: {sizeKey: {d?, tol?}}}（与后端 build_instance
 *     的 (label, sizeKey) 命中口径一致）；仅当某 (label, sizeKey) 的 d 或 tol 至少一档
 *     非空时才创建该 sizeKey entry，d/tol 各自仅当 trim() !== '' 时写入；
 *     全空的 label 映射整体剔除；最终 per_type 整体为空 → null。
 *   - 整体 trim 在 d/tol 单字段层做（与旧 vanilla 实现 inp.value.trim() !== '' 一致）。
 */
export function collectParams(form: FormState): CollectedParams {
  const params: SolveParams = {
    d_ext: 0,
    d_int: 0,
    tol_ext: 0,
    tol_int: 0,
  };

  const per_type: PerTypeOverrides = {};
  for (const label of Object.keys(form.per_type)) {
    const sizeMap = form.per_type[label];
    if (!sizeMap) continue;
    const outSizes: Record<string, PerTypeOverride> = {};
    for (const sk of Object.keys(sizeMap)) {
      const vals = sizeMap[sk];
      if (!vals) continue;
      const dStr = vals.d.trim();
      const tStr = vals.tol.trim();
      if (dStr !== '' || tStr !== '') {
        const entry: PerTypeOverride = {};
        if (dStr !== '') entry.d = parseFloat(dStr);
        if (tStr !== '') entry.tol = parseFloat(tStr);
        outSizes[sk] = entry;
      }
    }
    if (Object.keys(outSizes).length > 0) per_type[label] = outSizes;
  }
  return {
    params,
    per_type: Object.keys(per_type).length ? per_type : null,
  };
}

/** 解析 base seed（旧 vanilla 实现 `parseInt($('seed').value, 10) || 0`）：失败/空 → 0。 */
export function parseSeed(form: FormState): number {
  const v = parseInt(form.seed, 10);
  return Number.isNaN(v) ? 0 : v;
}

/** 解析时长秒数（旧 vanilla 实现 `parseInt($('time').value, 10) || 120`）：失败/空 → 120。 */
export function parseTime(form: FormState): number {
  const v = parseInt(form.time, 10);
  return Number.isNaN(v) ? 120 : v;
}

/**
 * 解析幅宽 mm（cm 字符串 ×10）：失败/空/非正 → 1980（=198cm，与 nesting_bounds.GATE_MM 一致）。
 * 输入框 cm 口径（版师习惯），后端 / sparrow 一律 mm，故此处统一换算。
 */
export function parseGate(form: FormState): number {
  const v = parseInt(form.gate, 10);
  return Number.isNaN(v) || v <= 0 ? 1980 : v * 10;
}

/**
 * 解析需要并行启动的 seed 数量（旧 vanilla 实现 startSolve 内：
 *   `multi ? Math.min(Math.max(parseInt($('seed_count').value, 10) || 3, 2), 6) : 1`）。
 *
 * 不变量：
 *   - multi_seed=false → 1（单 seed 模式）。
 *   - multi_seed=true → clamp(parseInt(seed_count) || 3, 2, 6)。
 */
export function parseSeedCount(form: FormState): number {
  if (!form.multi_seed) return 1;
  const v = parseInt(form.seed_count, 10);
  const n = Number.isNaN(v) ? 3 : v;
  return Math.min(Math.max(n, 2), 6);
}

// ---------------------------------------------------------------- US-022 quantities 序列化

// sizeKey 口径统一用上方 perTypeSizeKey（number→String；null→'null'）。

/**
 * US-022：把 ``qtyStore.quantities`` 扁平化为 WS payload 的 quantities 结构。
 * （矩阵化重构 US-001 删 global 分支，per-size 路径逻辑逐字段不变 —— 线格式不变是
 * 后端主管线零改动的唯一依据。）
 *
 * 输出：``Record<label, Record<sizeKey, number>>``。
 *   - 直接取 perSize（已是 sizeKey→number）。
 *   - 数量 0 保留在输出里（后端 build_instance 见 0 跳过该 piece；前端不抹零以保持
 *     「显式 0 = 排除」语义可追溯）。
 *   - quantities 为空 {} / sizes 为空 [] → 返回 null（后端回退全片 demand=1）。
 *
 * sizes 入参：当前勾选参与排料的码号列表（已过滤 null → number[]）。perSize 自带
 * key 空间，sizes 仅用于过滤未勾选码。
 */
export function serializeQuantities(
  quantities: PieceQuantityMap,
  sizes: number[],
): Record<string, Record<string, number>> | null {
  const labels = Object.keys(quantities);
  if (labels.length === 0) return null;

  const sizeKeys = sizes.map((s) => perTypeSizeKey(s));
  const out: Record<string, Record<string, number>> = {};
  for (const label of labels) {
    const q = quantities[label];
    if (!q) continue;
    // perSize 已是 sizeKey → number（可能含用户未编辑的码，值为 1 来自 hydrate）。
    // 只保留当前选中码（用户取消勾选某码 → 该码 demand 不发，后端自然不排该码）。
    // 兜底保留 'null' sizeKey（通用码；M1787 无此场景，但含 null 母版需要）。
    const flat: Record<string, number> = { ...q.perSize };
    const filtered: Record<string, number> = {};
    for (const sk of sizeKeys) {
      if (sk in flat) filtered[sk] = flat[sk];
    }
    if ('null' in flat && !('null' in filtered)) {
      filtered['null'] = flat['null'];
    }
    if (Object.keys(filtered).length > 0) out[label] = filtered;
  }
  return Object.keys(out).length > 0 ? out : null;
}

// ---------------------------------------------------------------- US-004 per_type URL 分享格式
//
// 把 form.per_type 压成可放进 URL query 的紧凑字符串（供分享/回放参数随动；应用侧
// 当前不主动读写地址栏，此处提供纯函数单一真相源）。格式：
//
//   entry := label '@' sizeKey '=' d ',' tol      // d/tol 任一侧可空，两侧全空的格子不产出
//   param := entry (';' entry)*                    // 空配置 → ''（调用方据此省略参数）
//
// 例：`g03@28=1.5,;g02@30=,45`（g03@28 d=1.5 tol 继承；g02@30 d 继承 tol=45）。
//
// 解码侧（perTypeFromUrlParam）宽松容错：不匹配 `g 码@码号键=d,tol` 语法的条目
// （旧 label 单级格式 / 旧中文片型键 / 手拼错段）一律跳过，不抛错（AC：旧 ptype 键忽略）。

/** URL 分享条目语法：g 码（g+1..4 位数字）@ 码号键（数字或 'null'）= d,tol。 */
const PER_TYPE_URL_ENTRY_RE = /^(g\d{1,4})@(null|\d{1,4})=([^;,]*),([^;]*)$/;

/**
 * FormState.per_type → URL 分享字符串。仅产出至少一档非空的 (label, sizeKey) 格子
 * （与 collectParams 的空串剔除口径一致）；全空 → ''。
 */
export function perTypeToUrlParam(form: FormState): string {
  const parts: string[] = [];
  for (const label of Object.keys(form.per_type)) {
    const sizeMap = form.per_type[label];
    if (!sizeMap) continue;
    for (const sk of Object.keys(sizeMap)) {
      const v = sizeMap[sk];
      if (!v) continue;
      if (v.d.trim() === '' && v.tol.trim() === '') continue;
      parts.push(`${label}@${sk}=${v.d.trim()},${v.tol.trim()}`);
    }
  }
  return parts.join(';');
}

/**
 * URL 分享字符串 → FormState.per_type（新格式）。语法不符的条目（含旧 ptype 键 /
 * 旧 label 单级格式）静默跳过；d/tol 解析为 NaN 的条目同样跳过（不抛错）。
 */
export function perTypeFromUrlParam(raw: string | null | undefined): PerTypeFormMap {
  const out: PerTypeFormMap = {};
  if (!raw) return out;
  for (const part of raw.split(';')) {
    const entry = part.trim();
    if (entry === '') continue;
    const m = PER_TYPE_URL_ENTRY_RE.exec(entry);
    if (!m) continue;
    const [, label, sk, dStr, tolStr] = m;
    if (dStr !== '' && Number.isNaN(parseFloat(dStr))) continue;
    if (tolStr !== '' && Number.isNaN(parseFloat(tolStr))) continue;
    const sizeMap = out[label] ?? (out[label] = {});
    sizeMap[sk] = { d: dStr, tol: tolStr };
  }
  return out;
}
