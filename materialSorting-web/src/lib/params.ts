// ControlPanel 表单状态 + collectParams 纯函数。
//
// US-019（主面板精简）：删除 d_ext/d_int/tol_ext/tol_int 四档主面板输入，全交高级配置弹窗
// （per_type 显式覆盖 + constraints.MAX_OVERLAP/ROTATION_TOL 兜底）。collectParams 现在 params
// 永远返回全 0，per_type 解析逻辑保留不变（与旧 vanilla 实现 inp.value.trim() !== '' 一致）。
//
// 不变量：后端 build_instance 入参契约不变（params 仍传，只是全 0；per_type 仍传）。
//
// 字段都按字符串存储（对应 input.value），collectParams 做解析；这样「空串 vs "0"」可区分
// （per_type 必须：空 = 继承，"0" = 显式 0）。

import { V03_PTYPES } from '../constants/v03';
import type { PerTypeOverrides, PerTypeOverride, SolveParams } from '../types/v03';

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
 * 默认值（US-017 起 sizes 默认空数组，强制用户勾选；time=60，seed=0；
 * multi_seed 关闭，seed_count=3；per_type 全空 = 继承 v0.3 默认）。
 */
export const DEFAULT_FORM: FormState = {
  sizes: [],
  time: '60',
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
 *     覆盖 + constraints.MAX_OVERLAP/ROTATION_TOL 兜底）。
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
