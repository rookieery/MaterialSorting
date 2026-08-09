// ControlPanel 表单状态 + collectParams 纯函数。
//
// 与旧 app.js collectParams() 字段级一致：
//   1. params 四档（d_ext/d_int/tol_ext/tol_int）空串 → 0 默认；非空 → parseFloat。
//   2. per_type 仅在 input.trim() !== '' 时写入；空 → 整个 per_type 序列化为 null。
//
// 字段都按字符串存储（对应 input.value），collectParams 做解析；这样「空串 vs "0"」可区分
// （per_type 必须：空 = 继承，"0" = 显式 0）。

import { SIZES } from '../constants/sizes';
import { V03_PTYPES } from '../constants/v03';
import type { PerTypeOverrides, PerTypeOverride, SolveParams } from '../types/v03';

/** 单片型的两条高级覆盖输入（d / tol 各一字符串，空串 = 继承两档）。 */
export interface PerTypeFormValue {
  d: string;
  tol: string;
}

/** ControlPanel 表单全量状态（字段都按 input.value 字符串存）。 */
export interface FormState {
  /** 已勾选码号（SIZES 子集）。 */
  sizes: number[];
  /** 时长（秒）字符串。 */
  time: string;
  /** base seed 字符串。 */
  seed: string;
  /** 外片重合 mm。 */
  d_ext: string;
  /** 内片重合 mm。 */
  d_int: string;
  /** 外片旋转公差 °。 */
  tol_ext: string;
  /** 内片旋转公差 °。 */
  tol_int: string;
  /** 每片型高级覆盖（V03_PTYPES 全量 key，d/tol 各一字符串）。 */
  per_type: Record<string, PerTypeFormValue>;
}

/** 旧 index.html 默认值 1:1（d_int=10，其余 0；time=60，seed=0；sizes 全选）。 */
export const DEFAULT_FORM: FormState = {
  sizes: [...SIZES],
  time: '60',
  seed: '0',
  d_ext: '0',
  d_int: '10',
  tol_ext: '0',
  tol_int: '0',
  per_type: Object.fromEntries(V03_PTYPES.map((pt) => [pt, { d: '', tol: '' }])),
};

/**
 * 解析数字字符串：parseFloat 失败（NaN / 空白）→ def。与旧 app.js `num(id, def)` 一致。
 * 注：parseFloat('') === NaN；parseFloat('  ') === NaN；parseFloat('1abc') === 1（与旧版同行为）。
 */
function num(s: string, def: number): number {
  const v = parseFloat(s);
  return Number.isNaN(v) ? def : v;
}

/** collectParams 输出（与旧 app.js collectParams 返回值结构一致）。 */
export interface CollectedParams {
  params: SolveParams;
  /** 空 → null（与旧 app.js Object.keys(per_type).length ? per_type : null 一致）。 */
  per_type: PerTypeOverrides | null;
}

/**
 * 把 FormState 解析为 { params, per_type }（与旧 app.js collectParams 字段级一致）。
 *
 * 不变量：
 *   - params.d_ext/d_int/tol_ext/tol_int：空 → 0（与旧 app.js num(id, 0) 一致）。
 *   - per_type：仅当某 ptype 的 d 或 tol 至少一档非空时才创建 entry；
 *     d / tol 各自仅当 trim() !== '' 时写入；最终若 per_type 整体为空 → null。
 *   - 整体 trim 在 d/tol 单字段层做（与旧 app.js inp.value.trim() !== '' 一致）。
 */
export function collectParams(form: FormState): CollectedParams {
  const params: SolveParams = {
    d_ext: num(form.d_ext, 0),
    d_int: num(form.d_int, 0),
    tol_ext: num(form.tol_ext, 0),
    tol_int: num(form.tol_int, 0),
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

/** 解析 base seed（旧 app.js `parseInt($('seed').value, 10) || 0`）：失败/空 → 0。 */
export function parseSeed(form: FormState): number {
  const v = parseInt(form.seed, 10);
  return Number.isNaN(v) ? 0 : v;
}

/** 解析时长秒数（旧 app.js `parseInt($('time').value, 10) || 120`）：失败/空 → 120。 */
export function parseTime(form: FormState): number {
  const v = parseInt(form.time, 10);
  return Number.isNaN(v) ? 120 : v;
}
