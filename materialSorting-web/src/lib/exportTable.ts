// exportTable.ts —— PLT 导出「唛架信息表格」的手输字段（2026-08-30）。
//
// 生产 PLT（data/PC-20250508NJIF*.plt）在唛架末端带 12 字段文件信息表格；其中
// 6 个生产计划字段（床次/铺布层数/拉布方式/排料师/款式号/备注）系统里没有，
// 由导出弹窗（ExportInfoModal）填写，其余 6 个（用料/幅宽/利用率/单耗/件数/
// 日期时间）由后端按当前方案自动计算（web/plt_table.py 口径）。
//
// 字段持久化：localStorage 键 ``ms_export_table``（排料师名/床次等跨导出记忆，
// 参照 lib/session.ts 的 try/catch 降级模式）。刻意**不进 FormState** ——
// ControlPanel 的 form 在 doc_id 变化时整体重置回 DEFAULT_FORM，生产信息与
// 具体母版无关，放表单会被连带清空。
//
// 后端契约：POST /export payload 的可选 table 对象（snake_case，缺省不带表格，
// 旧后端忽略未知键）；ply_count 非法（非 1..999 整数）后端 400，前端
// validateExportTable 先拦（错误文案直接上按钮 title）。

/** 手输字段草稿（全字符串持有 —— 输入框受控值；plyCount 提交时统一 parse）。 */
export interface ExportTableFields {
  bedNo: string;
  plyCount: string;
  layMethod: string;
  planner: string;
  styleNo: string;
  remark: string;
}

/** 约定默认值（2026-08-30 用户确认：层数 1 / 单向 / noname，其余空）。 */
export const DEFAULT_EXPORT_TABLE: ExportTableFields = {
  bedNo: '',
  plyCount: '1',
  layMethod: '单向',
  planner: 'noname',
  styleNo: '',
  remark: '',
};

/** localStorage 键名。 */
export const EXPORT_TABLE_STORAGE_KEY = 'ms_export_table';

/** 铺布层数上限（与后端 plt_table._PLY_MAX 同口径）。 */
export const PLY_COUNT_MAX = 999;

/** 读取记忆值：损坏 / 缺字段 → 与默认值 merge（缺什么补什么，不整体丢弃）。 */
export function loadExportTable(): ExportTableFields {
  let raw: unknown = null;
  try {
    raw = JSON.parse(localStorage.getItem(EXPORT_TABLE_STORAGE_KEY) ?? 'null');
  } catch {
    raw = null; // localStorage 不可用 / 存量损坏 —— 静默走默认
  }
  if (typeof raw !== 'object' || raw === null) return { ...DEFAULT_EXPORT_TABLE };
  const rec = raw as Record<string, unknown>;
  const out = { ...DEFAULT_EXPORT_TABLE };
  for (const key of Object.keys(DEFAULT_EXPORT_TABLE) as Array<keyof ExportTableFields>) {
    if (typeof rec[key] === 'string') out[key] = rec[key] as string;
  }
  return out;
}

/** 落盘记忆值（失败静默 —— 仅损失记忆，不影响本次导出）。 */
export function saveExportTable(fields: ExportTableFields): void {
  try {
    localStorage.setItem(EXPORT_TABLE_STORAGE_KEY, JSON.stringify(fields));
  } catch {
    // localStorage 不可用 —— 忽略
  }
}

/** 校验：铺布层数须为 1..999 整数 → 错误文案 | null（通过）。 */
export function validateExportTable(fields: ExportTableFields): string | null {
  const t = fields.plyCount.trim();
  if (!/^\d+$/.test(t)) return '铺布层数须为整数';
  const n = Number(t);
  if (n < 1 || n > PLY_COUNT_MAX) return `铺布层数须在 1~${PLY_COUNT_MAX}`;
  return null;
}

/** /export payload 的 table 对象（snake_case；由 useExport.exportAs 透传）。 */
export interface ExportTablePayload {
  bed_no: string;
  ply_count: number;
  lay_method: string;
  planner: string;
  style_no: string;
  remark: string;
}

/** 草稿 → payload（plyCount 此处 parse —— 调用前已过 validate）。 */
export function toExportTablePayload(fields: ExportTableFields): ExportTablePayload {
  return {
    bed_no: fields.bedNo.trim(),
    ply_count: Number(fields.plyCount.trim()),
    lay_method: fields.layMethod.trim(),
    planner: fields.planner.trim(),
    style_no: fields.styleNo.trim(),
    remark: fields.remark.trim(),
  };
}
