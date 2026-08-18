// PtypeRepresentative —— GET /api/ptypes 代表裁片契约（US-020 后端 → US-018 前端；
// 裁片编号化重构 US-003 起 representatives 键 = 裁片 g 码 label，v2 无 ptype 键）。
//
// 与后端 web/server.py `_LABEL_REPRESENTATIVE_FIELDS` 字段一致：
//   { representatives: Record<label, { label, polygon, net_polygon?, internal_lines?,
//                                     notches?, grain_line? }> }
//
// v1 intermediate 仅 polygon → 仅 polygon 字段；US-024 intermediate 扩 5 层后
// 自动带 net_polygon/internal_lines/notches/grain_line（前端 layer-aware 渲染，D11）。
//
// 与 types/parsed.ts ParsedPiece 同源（裁片几何）。代表裁片是「该 g 码最小码内首个出现
// 的 piece」（选取口径与 parse 赋号同源同序，_build_label_representatives）。
// Record 键 = rep.label = 裁片 g 码（g01+ 零填充，字典序=数值序），高级配置弹窗列头 /
// 放大预览头显示该编号徽章。故本类型独立定义；PiecePreviewSVG compact 模式不渲染
// label，正好契合。
//
// 坐标口径：所有顶点 = sparrow 世界坐标 (X=用布长度 mm, Y=门幅 mm，Y 向上)。
//   - polygon / net_polygon: [[x, y], ...]（R12 POLYLINE 闭合，无重复起点）
//   - internal_lines: [[[x, y], ...], ...]（layer8 多条内部辅助线）
//   - notches: [[x, y, nx, ny], ...]（layer4 刀口点 + 单位法向量）
//   - grain_line: [x1, y1, x2, y2] 或 null（layer7 布纹线两端点；无则 null）

import type { ParsedGrainLine, ParsedNotch, ParsedPt } from './parsed';

/** GET /api/ptypes representatives[label] 单条代表裁片（layer-aware：v1 仅 polygon，v2 5 层）。 */
export interface PtypeRepresentative {
  /** 代表裁片的 g01+ 裁片码（与 Record 键同值；旧数据 absent → 前端用键本身兜底显示）。 */
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
