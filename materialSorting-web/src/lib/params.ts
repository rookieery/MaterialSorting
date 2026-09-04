// ControlPanel 表单状态 + collectParams 纯函数。
//
// US-019（主面板精简）：删除 d_ext/d_int/tol_ext/tol_int 四档主面板输入，全交高级配置弹窗
// （per_type 显式覆盖 + 后端全局上限兜底 min(d, MAX_OVERLAP_MM=10)/min(tol,
// MAX_ROTATION_TOL_DEG=45)，2026-08-17 起不再按片型钳制）。collectParams 现在 params
// 永远返回全 0，per_type 解析逻辑保留不变（与旧 vanilla 实现 inp.value.trim() !== '' 一致）。
//
// 不变量：后端 build_instance 入参契约不变（params 仍传，只是全 0；per_type 仍传）。
// 2026-08-18 回退 US-004 矩阵化：per_type 维持单级 {g 码: {d, tol}}（不按码号细分），
// 与后端 build_instance 的 label 级命中同步（US-004 曾改两级 {label:{sizeKey:...}}）。
//
// 字段都按字符串存储（对应 input.value），collectParams 做解析；这样「空串 vs "0"」可区分
// （per_type 必须：空 = 继承，"0" = 显式 0）。

import type { PerTypeOverrides, PerTypeOverride, SolveParams } from '../types/v03';
import type { PieceQuantityMap } from '../types/qty';
import type { ParsedDoc, ParsedPt } from '../types/parsed';
import type { BandConfig, PrefixConfig } from '../types/ws';

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
  /**
   * base seed 字符串。**2026-08-22 seed UI 隐藏后恒 '0'**（ParamForm 删 seed 输入行，
   * 无写入方；parseSeed 恒 0，WS StartPayload.seed=0 契约不变）。
   */
  seed: string;
  /**
   * 多 seed 对比开关（旧 index.html `#multi_seed` checkbox）。**2026-08-22 UI 隐藏后
   * 恒 false**（MultiSeedControls 组件已删，无写入方 → parseSeedCount 恒 1）。
   */
  multi_seed: boolean;
  /**
   * 多 seed 数量字符串（旧 index.html `#seed_count`，默认 "3"，clamp [2,6]）。
   * **2026-08-22 UI 隐藏后恒 '3'**（multi_seed 恒 false，该值不再被消费）。
   */
  seed_count: string;
  /**
   * 每裁片高级覆盖（键 = g01+ 裁片码，d/tol 各一字符串；动态来自高级配置弹窗，
   * 列集 = 当前母版 g 码并集 —— V03_PTYPES 固定清单已删）。空对象 = 全部继承默认 0。
   * US-019 起：内外两档全局输入删除，per_type 是唯一的 d/tol 覆盖入口（高级配置弹窗）。
   */
  per_type: Record<string, PerTypeFormValue>;
  /**
   * US-012 腰头成带开关（高级配置弹窗「布局设置」分区写回，US-013 接入 UI；
   * 本 story 仅参数链路）。false = 关（默认，WS band 键恒 null）。
   */
  band_enabled: boolean;
  /**
   * US-012 腰头 g 码（如 'g05'；空串 = 已勾选但未选编号 —— collectStartContext
   * 三态解析为 null，US-013 前端闸门兜底前的最后防线）。
   */
  band_label: string;
  /**
   * US-004 起始端成套前后幅开关（高级配置弹窗「布局设置」分区写回）。false = 关
   * （默认，WS prefix 键恒 null）；与 band 可同开（双开时带位只记录不置换）。
   */
  prefix_enabled: boolean;
  /**
   * US-004 前幅 g 码（如 'g02'；空串 = 已勾选但未选 —— collectPrefix 三态解析为
   * null，ControlPanel 前端闸门兜底前的最后防线）。默认预选母版面积最大片（决策⑤）。
   */
  prefix_front: string;
  /**
   * US-004 后幅 g 码（如 'g03'；须 front≠back）。默认预选母版面积第二大片。
   */
  prefix_back: string;
}

/**
 * 默认值（US-017 起 sizes 默认空数组，强制用户勾选；gate=175.00cm（=GATE_MM 1750mm，
 * 2026-09-04 起默认 175cm，版师要求两位小数口径），time=120，seed=0；multi_seed 关闭，seed_count=3；per_type
 * 空对象 = 无任何覆盖 = 继承 v0.3 默认 0 —— 裁片键动态出现，仅在弹窗确定后写入）。
 */
export const DEFAULT_FORM: FormState = {
  sizes: [],
  gate: '175.00',
  time: '120',
  seed: '0',
  multi_seed: false,
  seed_count: '3',
  per_type: {},
  band_enabled: false,
  band_label: '',
  prefix_enabled: false,
  prefix_front: '',
  prefix_back: '',
};

/** collectParams 输出（与旧 vanilla 实现 collectParams 返回值结构一致）。 */
export interface CollectedParams {
  params: SolveParams;
  /** 空 → null（与旧 vanilla 实现 Object.keys(per_type).length ? per_type : null 一致）。 */
  per_type: PerTypeOverrides | null;
}

/**
 * 把 per_type 草稿字符串表解析为 WS payload 结构（2026-08-24 自 collectParams 提取：
 * collectStartContext 与成带预览 POST /api/band-preview 两处共用同一解析 —— 预览与
 * solve 的 d_g 同源，WYSIWYG）。
 *
 * 仅当某 label 的 d 或 tol 至少一档非空时才创建 entry；d / tol 各自仅当
 * trim() !== '' 时写入；整体为空 → null。整体 trim 在单字段层做（与旧 vanilla
 * 实现 inp.value.trim() !== '' 一致）。
 */
export function collectPerType(
  values: Record<string, PerTypeFormValue>,
): PerTypeOverrides | null {
  const per_type: PerTypeOverrides = {};
  for (const label of Object.keys(values)) {
    const vals = values[label];
    if (!vals) continue;
    const dStr = vals.d.trim();
    const tStr = vals.tol.trim();
    if (dStr !== '' || tStr !== '') {
      const entry: PerTypeOverride = {};
      if (dStr !== '') entry.d = parseFloat(dStr);
      if (tStr !== '') entry.tol = parseFloat(tStr);
      per_type[label] = entry;
    }
  }
  return Object.keys(per_type).length ? per_type : null;
}

/**
 * 把 FormState 解析为 { params, per_type }。
 *
 * 不变量：
 *   - params：US-019 起永远返回全 0（主面板内外两档输入删除，v0.3 上限交给 per_type 显式
 *     覆盖 + 后端全局上限兜底，2026-08-17 起 min(d,10)/min(tol,45) 不再按片型）。
 *   - per_type：collectPerType(form.per_type)（单一实现）。
 */
export function collectParams(form: FormState): CollectedParams {
  const params: SolveParams = {
    d_ext: 0,
    d_int: 0,
    tol_ext: 0,
    tol_int: 0,
  };
  return { params, per_type: collectPerType(form.per_type) };
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
 * 解析幅宽 mm（cm 字符串 ×10）：失败/空/非正 → 1750（=175cm，与 nesting_bounds.GATE_MM 一致）。
 * 输入框 cm 口径（版师习惯，2026-08-28 起两位小数 = 0.1mm 分辨率，parseFloat 不截断小数），
 * 后端 / sparrow 一律 mm，故此处统一换算。
 */
export function parseGate(form: FormState): number {
  const v = parseFloat(form.gate);
  return Number.isNaN(v) || v <= 0 ? 1750 : v * 10;
}

/**
 * 幅宽输入失焦归一化（cm 字符串）：非法/空/非正 → '175.00'；合法 → 钳制 [50, 400]
 * （与输入框 min/max 同界）后格式化两位小数。parseGate 不钳制（求解语义不变），
 * 钳制只作为输入 UX 在失焦时兜底。
 */
export function normalizeGate(v: string): string {
  const n = parseFloat(v);
  if (Number.isNaN(n) || n <= 0) return '175.00';
  return Math.min(400, Math.max(50, n)).toFixed(2);
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

// ------------------------------------------------- US-012 腰头成带 band 参数

/** g 码模式（后端 routes_ws._BAND_LABEL_RE `^g\d+$` 的前端镜像）。 */
export const BAND_LABEL_RE = /^g\d+$/;

/**
 * US-012 band 三态解析（FR-1）：FormState.band_* → WS StartPayload.band 值。
 *
 *   1. band 关（band_enabled=false）              → null；
 *   2. 开但未选编号 / label 非 g 码（含空白）      → null（「开且未选」不冒充有效配置 ——
 *      后端对空 label 会回结构化 error，此处静默降级为关；US-013 前端闸门在先，
 *      这里是兜底防线）；
 *   3. 开且有效（`^g\d+$`）                        → {enabled:true, label}。
 *
 * label 是否存在于当前母版 / 该 g 码 quantities>0 由后端 ``_parse_band`` 权威校验
 * （前端 store 无母版全集，不预判存在性）。
 */
export function collectBand(form: FormState): BandConfig | null {
  if (!form.band_enabled) return null;
  const label = form.band_label.trim();
  if (!BAND_LABEL_RE.test(label)) return null;
  return { enabled: true, label };
}

/**
 * US-012 band 成员数校验函数：该 g 码在当前表单 / 数量状态下进入带内的成员副本总数
 * （US-013 启动闸门消费：= 0 → 「选中 g 码数量全 0」置灰拦截）。
 *
 * 逐码三态解析，与后端 demand 判定（build_pid_meta / routes_ws._band_demand）口径对齐：
 *   1. **missing→1**：该 (label, 码) 在数量矩阵无记录（label 行缺或 sizeKey 缺）→ 按默认
 *      1 计 —— 与后端「空 quantities 回退 demand=1」向后兼容口径 + SizePicker.effectiveDemand
 *      同约定（未 hydrate 不误拦「数量全 0」；label 行整缺时对每个选中码各计 1 片）；
 *   2. **显式 0** → 0（该码显式排除，后端 demand=0 跳过同口径）；
 *   3. **未选码过滤** → 不计（码号未勾选 → serializeQuantities 丢弃该键 + 后端
 *      build_pid_meta sizes 过滤，该码裁片不进求解）。
 *
 * 注：'null' 通用码不计 —— 后端 sizes 过滤（`p['size'] in want`，want=数字集）下
 * null 码裁片本就不进求解（form.sizes 过滤 null 与既有下游契约一致）。
 */
export function bandMemberCount(
  form: FormState,
  quantities: PieceQuantityMap,
  label: string,
): number {
  const selected = form.sizes.filter(
    (s: number | null): s is number => s !== null,
  );
  const row = quantities[label];
  let count = 0;
  for (const size of selected) {
    const v = row?.perSize[String(size)];
    count += v === undefined ? 1 : v;
  }
  return count;
}

// ------------------------------------------------- US-004 prefix 起始端成套参数

/**
 * US-004 prefix 三态解析（FR-1）：FormState.prefix_* → WS StartPayload.prefix 值。
 *
 *   1. prefix 关（prefix_enabled=false）                        → null；
 *   2. 开但前/后幅未选 / 非 g 码（含空白）/ front==back          → null（「开且未选」
 *      不冒充有效配置 —— 后端对无效 front/back 会回结构化 error，此处静默降级为关；
 *      ControlPanel 前置闸门在先，这里是兜底防线）；
 *   3. 开且有效（两码均 ``^g\d+$`` 且互异）                      → {enabled:true,front,back}。
 *
 * g 码是否存在于母版 / 资格码 ≥1 由后端 ``_parse_prefix`` 权威校验（前端弹窗有本地
 * 预检提示，但不阻塞 —— 后端结构化 error 是唯一权威拦截）。
 */
export function collectPrefix(form: FormState): PrefixConfig | null {
  if (!form.prefix_enabled) return null;
  const front = form.prefix_front.trim();
  const back = form.prefix_back.trim();
  if (!BAND_LABEL_RE.test(front) || !BAND_LABEL_RE.test(back)) return null;
  if (front === back) return null;
  return { enabled: true, front, back };
}

/**
 * US-004 资格码存在性本地预检（与后端 ``nesting_engine.prefix.eligible_sizes`` /
 * ``routes_ws._parse_prefix`` 同口径）：在用户所排尺码（sizes 过滤）中，front 与
 * back 两码 demand 均 ==2 的码集合（2+2 恰用尽 demand —— 版师 P2「总量 2 或 6 片
 * 的码不行」；0/1/3/缺码均不合格）。
 *
 * 口径对齐要点（与 bandMemberCount 的 missing→1 **不同**）：
 *   - demand 取 qtyStore perSize 值，缺码 → 0（资格要求恰 ==2，缺 0 与显 0 同判
 *     不合格 —— 后端 ``_demand_of`` ``qmap.get(sk, 0)`` 同口径；quantities=null
 *     全 demand=1 场景本函数返回空 = 后端 FR-9 结构化 error 同条件）；
 *   - 'null' 通用码无资格概念（后端 ``int(sk)`` 跳过）；
 *   - 未勾选码过滤（资格码必须真实进主解实例 —— 后端 sizes 过滤同款）。
 *
 * @returns 升序资格码列表（空 = 无资格，调用方提示「当前数量无 2+2 资格码」）。
 */
export function prefixEligibleSizes(
  sizes: number[],
  quantities: PieceQuantityMap | null,
  front: string,
  back: string,
): number[] {
  const qf = quantities?.[front]?.perSize ?? {};
  const qb = quantities?.[back]?.perSize ?? {};
  const want = new Set(sizes.map((s) => String(s)));
  const out: number[] = [];
  for (const sk of new Set([...Object.keys(qf), ...Object.keys(qb)])) {
    const si = parseInt(sk, 10);
    if (Number.isNaN(si)) continue; // 'null' 通用码非数字码，无资格概念
    if (!want.has(sk)) continue; // 未勾选码不进主解，无资格
    if ((qf[sk] ?? 0) === 2 && (qb[sk] ?? 0) === 2) out.push(si);
  }
  return out.sort((a, b) => a - b);
}

/**
 * Shoelace 多边形有向面积（母版 polygon 闭合无重复起点，abs/2 即面积 mm²）。
 * 前端无 shapely，预选启发式只需相对序，不自交假设与母版实际一致。
 */
function polygonArea(poly: ParsedPt[]): number {
  let s = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    s += x1 * y2 - x2 * y1;
  }
  return Math.abs(s) / 2;
}

/**
 * US-004 决策⑤默认预选：parse doc 中**面积最大两片**（5336 = g02 前幅 441k mm² /
 * g03 后幅 350k mm²，次大 g05 腰头 94k —— 前后幅显著大，启发式稳）。
 *
 * 口径：每 label 取其全部码片 polygon 面积的最大值（跨码并集取 max —— 片型工艺
 * 属性与码号无关，最大码面积代表该 g 码量级）；按面积降序、平手按 g 码字典序，
 * 取前二（front = 最大，back = 第二）。不足两 label / doc=null → null（下拉留空）。
 * 启发式只是缺省值建议，非识别功能 —— 用户可改（PRD 非目标第 5 条）。
 */
export function defaultPrefixLabels(
  doc: ParsedDoc | null,
): { front: string; back: string } | null {
  if (!doc) return null;
  const maxArea = new Map<string, number>();
  for (const s of doc.sizes) {
    for (const p of s.pieces) {
      if (!p.polygon || p.polygon.length < 3) continue;
      const a = polygonArea(p.polygon);
      const prev = maxArea.get(p.label);
      if (prev === undefined || a > prev) maxArea.set(p.label, a);
    }
  }
  const ranked = Array.from(maxArea.entries())
    .sort((a, b) => (b[1] - a[1]) !== 0 ? b[1] - a[1] : (a[0] < b[0] ? -1 : 1))
    .map(([label]) => label);
  if (ranked.length < 2) return null;
  return { front: ranked[0], back: ranked[1] };
}



/**
 * ControlPanel.handleStart 与 StrategyRunModal「执行」共用的 start 上下文
 * （US-005 提取：主画布 WS start 与策略 run POST /api/strategy/start 的排料参数
 * 构造**同源**，不复制逻辑 —— 码号过滤 null / 幅宽 / seed / params / per_type /
 * quantities 逐字段同一实现）。
 *
 * quantities 入参传 ``useQtyStore.getState().quantities``（调用时快照，保持
 * params.ts 纯函数 —— 不 import store）。
 */
export interface StartContext {
  /** 已过滤 null 的码号（下游 WS / export / strategy start 契约都是 number[]）。 */
  sizes: number[];
  /** 幅宽 mm（parseGate：cm ×10，非法回退 1750）。 */
  gate_mm: number;
  /** base seed（parseSeed）。 */
  seed: number;
  /** 时长秒（parseTime；策略模式不使用 —— 总预算由弹窗时长档决定）。 */
  time: number;
  /** collectParams：US-019 起恒全 0（per_type 是唯一 d/tol 覆盖入口）。 */
  params: SolveParams;
  /** collectParams：空 → null。 */
  per_type: PerTypeOverrides | null;
  /** serializeQuantities：空 / 全未选 → null（后端全片 demand=1）。 */
  quantities: Record<string, Record<string, number>> | null;
  /**
   * US-012 collectBand 三态解析：关 / 开未选 → null；开且有效 → {enabled:true,label}。
   * 主画布 WS start 与策略 run（StrategyRunModal.handleExec）同源透传
   * （2026-08-22 解除互斥：band 进 /api/strategy/start → 9 键 config → CLI
   * solve_worker 进程内成带 + 展开）。
   */
  band: BandConfig | null;
  /**
   * US-004 collectPrefix 三态解析：关 / 开未选或无效 → null；开且有效 →
   * {enabled:true,front,back}。主画布 WS start 与策略 run 同源透传
   * （2026-08-25 解除互斥，band 同款：prefix 进 /api/strategy/start → 9 键
   * config → CLI solve_worker 进程内构造 + 展开，资格码 seeded 选取）。
   */
  prefix: PrefixConfig | null;
}

/** 把 FormState + 数量快照解析为 StartContext（handleStart / strategy start 同源）。 */
export function collectStartContext(
  form: FormState,
  quantities: PieceQuantityMap,
): StartContext {
  const { params, per_type } = collectParams(form);
  const sizes: number[] = form.sizes.filter(
    (s: number | null): s is number => s !== null,
  );
  return {
    sizes,
    gate_mm: parseGate(form),
    time: parseTime(form),
    seed: parseSeed(form),
    params,
    per_type,
    quantities: serializeQuantities(quantities, sizes),
    band: collectBand(form),
    prefix: collectPrefix(form),
  };
}
