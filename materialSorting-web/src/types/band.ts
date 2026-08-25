// BandPreview —— POST /api/band-preview 成带预览 + POST /api/prefix-preview 前缀
// 组合形态预览契约（2026-08-24 布局设置缩略图换成带形态预览；原始代表裁片图与
// 下方裁片设置表格同源同图，纯冗余已删。2026-08-25 prefix 行同款换组合片预览，
// 成员形状 BandPreviewMember 两端点共用 —— prefix 成员带 tag 覆盖标注）。
//
// 与后端 web/routes_views.py band_preview 响应字段严格一致；失败也 200（ok:false
// 包络 —— 选错 g 码是预期内常态，前端单条路径渲染错误文案，不区分网络/业务错误）。
//
// 几何口径：members[].polygon 与 outline 均为**带内归一坐标**（后端已减 chunk.offset，
// min≈0）—— 前端零变换直接渲染；颜色 = size_color 单一真相源（同码同色跨片型，
// 与 manifest/NestSVG 同口径），「码序降序 + 最大码在最右」一眼可辨。
// 组合片 WB_ pid 按哨兵约定不返回（WB_ 永不出现在前端）。

import type { Polygon } from './piece';

/** 预览载荷（WS StartPayload 同源字段子集；band 校验后端复用 _parse_band 单一校验点）。 */
export interface BandPreviewPayload {
  band: { enabled: true; label: string };
  /** 当前勾选码号（过滤 null 后的 number[]，与 StartPayload.sizes 同口径）。 */
  sizes: number[];
  /** serializeQuantities 产物（label → sizeKey → N）；空对象 → 后端全片 demand=1。 */
  quantities: Record<string, Record<string, number>> | null;
  /** collectPerType 产物（label → {d?, tol?}）；后端只用 band label 键裁 d_g。 */
  per_type: Record<string, { d?: number; tol?: number }> | null;
  /** 幅宽 mm（parseGate；缺省回退 intermediate gate —— 与 /export 同法）。 */
  gate_mm: number;
}

/** 带内单成员（原始轮廓@带内归一位，已变换 —— 前端不重复做 rot/translate）。 */
export interface BandPreviewMember {
  /** 成员 pid（`{label}_{size}`，非 WB_ 组合片）。 */
  pid: string;
  /** 尺码（着色键 = size_color；显示码序用）。 */
  size: number;
  /** size_color(size)（后端同源；同码同色）。 */
  color: string;
  /** 原始轮廓顶点 [[x, y], ...]（带内归一坐标，2 位小数）。 */
  polygon: Polygon;
  /** 显示标注覆盖（prefix 预览 = 成员 g 码，前/后幅区分；缺席 = 标注尺码）。 */
  tag?: string;
}

/** POST /api/band-preview 200 响应整体。 */
export interface BandPreviewResponse {
  ok: boolean;
  /** ok:false 时的可读错误（「成带失败: …」/ 校验文案 / 「排料数据为空」）。 */
  error?: string;
  label?: string;
  /** 带内填充率 %。 */
  fill_pct?: number;
  /** 带实际占用 bbox（mm）。 */
  bbox?: { width_mm: number; height_mm: number };
  /** 成员副本总数（= Σ demand，副本守恒口径）。 */
  n_members?: number;
  members?: BandPreviewMember[];
  /** erode 后组合片外轮廓（虚线叠加显示「主解看到的形状」）。 */
  outline?: Polygon;
}

/** POST /api/prefix-preview 载荷（前缀组合形态预览，2026-08-25；prefix 校验复用 _parse_prefix）。 */
export interface PrefixPreviewPayload {
  prefix: { enabled: true; front: string; back: string };
  /** 当前勾选码号（过滤 null 后的 number[]，与 StartPayload.sizes 同口径）。 */
  sizes: number[];
  /** serializeQuantities 产物（label → sizeKey → N）；资格码 2+2 判定用。 */
  quantities: Record<string, Record<string, number>> | null;
  /** collectPerType 产物；后端只用 front/back 键裁 d_g（取 max，与求解同式）。 */
  per_type: Record<string, { d?: number; tol?: number }> | null;
  /** 幅宽 mm（parseGate；竖排高守卫与 solve 同口径）。 */
  gate_mm: number;
  /** 资格码选取 seed（缺省 0 —— 界面恒单 seed=0 ⇒ 预览与求解同码）。 */
  seed?: number;
}

/** POST /api/prefix-preview 200 响应整体（失败也 200、ok:false 包络，band 同约定）。 */
export interface PrefixPreviewResponse {
  ok: boolean;
  /** ok:false 时的可读错误（「前缀构造失败: …」/ 校验文案 / 「排料数据为空」）。 */
  error?: string;
  front?: string;
  back?: string;
  /** 资格码中 seeded 随机选中的尺码（4 成员同码）。 */
  size?: number;
  /** 组合片 bbox 填充率 %。 */
  fill_pct?: number;
  /** 组合片实际占用 bbox（mm）。 */
  bbox?: { width_mm: number; height_mm: number };
  /** 成员数（恒 4 = 前×2 + 后×2）。 */
  n_members?: number;
  members?: BandPreviewMember[];
  /** erode 后组合片外轮廓（虚线叠加显示「主解看到的形状」；PS_ pid 不返回）。 */
  outline?: Polygon;
}
