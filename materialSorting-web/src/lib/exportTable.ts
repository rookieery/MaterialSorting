// exportTable.ts —— PLT 导出「唛架信息表格」的手输字段（2026-08-30 v2 重写）。
//
// 生产环境新代软件的 PLT 信息表共 14 字段（横排竖直堆叠、排料图外围）；其中
// 6 个手输（床次/经纱缩水/纬纱缩水/排料师/样板号/备注）系统里没有，由导出弹窗
// （ExportInfoModal）填写，其余 8 个（方案名称/套数/利用率/幅宽/料长/每套用料/
// 片数/绘图时间）由后端按当前方案自动计算（web/plt_table.py 口径 —— 方案名称
// 由勾选尺码的面积最大裁片数量÷2 算系数求和）。
//
// 字段持久化：localStorage 键 ``ms_export_table``（排料师名/床次等跨导出记忆，
// 参照 lib/session.ts 的 try/catch 降级模式）。刻意**不进 FormState** ——
// ControlPanel 的 form 在 doc_id 变化时整体重置回 DEFAULT_FORM，生产信息与
// 具体母版无关，放表单会被连带清空。
//
// 后端契约：POST /export payload 的可选 table 对象（snake_case，缺省不带表格，
// 旧后端忽略未知键）；v2 起全字段自由字符串（默认 A料/0.0%/0.0%/空/noname/空），
// 无格式校验，超长由后端截断 + warn。

/** 手输字段草稿（全字符串持有 —— 输入框受控值，提交时 trim）。 */
export interface ExportTableFields {
  bedNo: string;
  warpShrink: string;
  weftShrink: string;
  planner: string;
  styleNo: string;
  remark: string;
}

/** 约定默认值（2026-08-30 用户确认：A料 / 0.0% / 0.0% / 空 / noname / 空）。 */
export const DEFAULT_EXPORT_TABLE: ExportTableFields = {
  bedNo: 'A料',
  warpShrink: '0.0%',
  weftShrink: '0.0%',
  planner: '',
  styleNo: 'noname',
  remark: '',
};

/** localStorage 键名。 */
export const EXPORT_TABLE_STORAGE_KEY = 'ms_export_table';

/** 读取记忆值：损坏 / 缺字段 → 与默认值 merge（缺什么补什么，不整体丢弃；v1 存量键 plyCount/layMethod 自然忽略）。 */
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

/** /export payload 的 table 对象（snake_case；由 useExport.exportAs 透传）。 */
export interface ExportTablePayload {
  bed_no: string;
  warp_shrink: string;
  weft_shrink: string;
  planner: string;
  style_no: string;
  remark: string;
}

/** 草稿 → payload（全字符串直传 trim，无格式转换）。 */
export function toExportTablePayload(fields: ExportTableFields): ExportTablePayload {
  return {
    bed_no: fields.bedNo.trim(),
    warp_shrink: fields.warpShrink.trim(),
    weft_shrink: fields.weftShrink.trim(),
    planner: fields.planner.trim(),
    style_no: fields.styleNo.trim(),
    remark: fields.remark.trim(),
  };
}
