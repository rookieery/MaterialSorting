// PtypeRepresentative —— GET /api/ptypes 代表裁片契约（US-020 后端 → US-018 前端）。
//
// 与后端 web/server.py `_PTYPE_REPRESENTATIVE_FIELDS` 字段一致：
//   { representatives: Record<ptype, { label?, polygon, net_polygon?, internal_lines?,
//                                     notches?, grain_line? }> }
//
// v1 intermediate 仅 polygon → 仅 polygon 字段；US-024 intermediate 扩 5 层后
// 自动带 net_polygon/internal_lines/notches/grain_line（前端 layer-aware 渲染，D11）。
//
// 与 types/parsed.ts ParsedPiece 同源（裁片几何），但**无 name 字段** —— 代表裁片是
// 「该 ptype 最小码内首个出现的 piece」（选取口径与 parse 赋号同键同序）。label =
// 该片在上传预览里的 A/B/C 编号（2026-08-17 起），高级配置弹窗列头 / 放大预览头
// 显示该编号徽章；旧 intermediate 无该字段 → 前端兜底显示片型名。
// 故本类型独立定义；PiecePreviewSVG compact 模式不渲染 label，正好契合。
//
// 坐标口径：所有顶点 = sparrow 世界坐标 (X=用布长度 mm, Y=门幅 mm，Y 向上)。
//   - polygon / net_polygon: [[x, y], ...]（R12 POLYLINE 闭合，无重复起点）
//   - internal_lines: [[[x, y], ...], ...]（layer8 多条内部辅助线）
//   - notches: [[x, y, nx, ny], ...]（layer4 刀口点 + 单位法向量）
//   - grain_line: [x1, y1, x2, y2] 或 null（layer7 布纹线两端点；无则 null）

import type { ParsedGrainLine, ParsedNotch, ParsedPt } from './parsed';

/** GET /api/ptypes representatives[ptype] 单条代表裁片（layer-aware：v1 仅 polygon，v2 5 层）。 */
export interface PtypeRepresentative {
  /** 代表裁片在上传预览里的 A/B/C 编号（与 parse 赋号同口径）；旧数据 absent → 兜底片型名。 */
  label?: string;
  /** 毛版外轮廓（layer1 POLYLINE），闭合无重复起点。 */
  polygon: ParsedPt[];
  /** 净版轮廓 (layer14)，可能 absent（v1）或为空数组（部分片无净版）。 */
  net_polygon?: ParsedPt[];
  /** 内部辅助线 (layer8)，每条是顶点数组；absent 表示无（v1）。 */
  internal_lines?: ParsedPt[][];
  /** 刀口列表 (layer4 POINT + #N)；absent 表示无（v1）。 */
  notches?: ParsedNotch[];
  /** 布纹线 (layer7) 两端点；absent 或 null 表示无（v1）。 */
  grain_line?: ParsedGrainLine | null;
}

/** GET /api/ptypes 200 响应整体。空 state（未 commit）= `{ representatives: {} }`。 */
export interface PtypesResponse {
  representatives: Record<string, PtypeRepresentative>;
}
