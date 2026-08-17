// ControlPanel 表单状态 + collectParams 纯函数。
//
// US-019（主面板精简）：删除 d_ext/d_int/tol_ext/tol_int 四档主面板输入，全交高级配置弹窗
// （per_type 显式覆盖 + 后端全局上限兜底 min(d, MAX_OVERLAP_MM=10)/min(tol,
// MAX_ROTATION_TOL_DEG=45)，2026-08-17 起不再按片型钳制）。collectParams 现在 params
// 永远返回全 0，per_type 解析逻辑保留不变（与旧 vanilla 实现 inp.value.trim() !== '' 一致）。
//
// 不变量：后端 build_instance 入参契约不变（params 仍传，只是全 0；per_type 仍传）。
//
// 字段都按字符串存储（对应 input.value），collectParams 做解析；这样「空串 vs "0"」可区分
// （per_type 必须：空 = 继承，"0" = 显式 0）。

import { V03_PTYPES } from '../constants/v03';
import type { PerTypeOverrides, PerTypeOverride, SolveParams } from '../types/v03';
import type { PieceQuantityMap } from '../types/qty';

/** 单片型的两条高级覆盖输入（d / tol 各一字符串，空串 = 继承 v0.3 默认）。 */
export interface PerTypeFormValue {
  d: string;
  tol: string;
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
   * 每片型高级覆盖（V03_PTYPES 全量 key，d/tol 各一字符串）。
   * US-019 起：内外两档全局输入删除，per_type 是唯一的 d/tol 覆盖入口（高级配置弹窗）。
   */
  per_type: Record<string, PerTypeFormValue>;
}

/**
 * 默认值（US-017 起 sizes 默认空数组，强制用户勾选；gate=198cm（=GATE_MM 1980mm），
 * time=120，seed=0；multi_seed 关闭，seed_count=3；per_type 全空 = 继承 v0.3 默认）。
 */
export const DEFAULT_FORM: FormState = {
  sizes: [],
  gate: '198',
  time: '120',
  seed: '0',
  multi_seed: false,
  seed_count: '3',
  per_type: Object.fromEntries(V03_PTYPES.map((pt) => [pt, { d: '', tol: '' }])),
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
 *   - per_type：仅当某 ptype 的 d 或 tol 至少一档非空时才创建 entry；
 *     d / tol 各自仅当 trim() !== '' 时写入；最终若 per_type 整体为空 → null。
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
  for (const pt of V03_PTYPES) {
    const vals = form.per_type[pt];
    if (!vals) continue;
    const dStr = vals.d.trim();
    const tStr = vals.tol.trim();
    if (dStr !== '' || tStr !== '') {
      const entry: PerTypeOverride = {};
      if (dStr !== '') entry.d = parseFloat(dStr);
      if (tStr !== '') entry.tol = parseFloat(tStr);
      per_type[pt] = entry;
    }
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

/** sizeKey 口径与 qtyStore 一致：number->String(number)；null->'null'。 */
function sizeKey(size: number | null): string {
  return size === null ? 'null' : String(size);
}

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

  const sizeKeys = sizes.map((s) => sizeKey(s));
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
