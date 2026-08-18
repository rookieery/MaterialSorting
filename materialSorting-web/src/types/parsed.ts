// ParsedDoc / ParsedSize / ParsedPiece —— DXF 上传解析响应契约（US-004 后端 → US-005 前端；
// 裁片编号化重构 US-003 起随 v2 schema 去 name/ptype/配对字段，label-only）。
//
// 与后端 web/server.py `_build_parse_payload()` 字段严格一致：
//   { doc_id, filename, sizes: [{ size, pieces: [{ label, polygon, internal_lines,
//                                                  notches, net_polygon,
//                                                  grain_line }] }] }
//
// 坐标口径：所有顶点 = sparrow 世界坐标 (X=用布长度 mm, Y=门幅 mm，Y 向上)。
//   - polygon / net_polygon: [[x, y], ...]（R12 POLYLINE 闭合，无重复起点）
//   - internal_lines: [[[x, y], ...], ...]（layer8 多条内部辅助线）
//   - notches: [[x, y, nx, ny], ...]（layer4 刀口点 + 单位法向量）
//   - grain_line: [x1, y1, x2, y2] 或 null（layer7 布纹线两端点；无则 null）
//
// 注：[x, y] 结构上与 types/piece.ts 的 Pt 同型，但语义不同（Pt = sparrow base 几何；
//   此处 = 母版解析坐标）。故本文件独立定义类型，不与 piece.ts 共享 alias，避免概念混淆。

/** 顶点 [x_mm, y_mm]（与 US-004 后端 polygon / net_polygon / internal_lines 元素一致）。 */
export type ParsedPt = [number, number];

/** 刀口：[x, y, nx, ny] —— 点位 + 沿所属轮廓边的单位法向量（US-003 notch 模型）。 */
export type ParsedNotch = [number, number, number, number];

/** 布纹线两端点：[x1, y1, x2, y2]（与 US-004 `grain_line = [x1,y1,x2,y2]` 一致）。 */
export type ParsedGrainLine = [number, number, number, number];

/**
 * 单片解析结果（与 server.py `_build_parse_payload` 字段名严格一致）。
 * v2 契约：只有 g 码 label 一个标识字段（无 name/ptype/配对布尔 —— 中文名、片型与配对
 * 概念已从全链路删除，数量即一切，母版 N 个轮廓 × quantities 数量 = 排料件数）。
 */
export interface ParsedPiece {
  /** g01+ 裁片码（每码内独立零填充编号，字典序=数值序；实测每码 ≤10 片；母版自带编号时复用）。 */
  label: string;
  /** 毛版外轮廓 (layer1 POLYLINE)，闭合无重复起点。 */
  polygon: ParsedPt[];
  /** 内部辅助线 (layer8)，每条是顶点数组。 */
  internal_lines: ParsedPt[][];
  /** 刀口列表 (layer4 POINT + #N)。 */
  notches: ParsedNotch[];
  /** 净版轮廓 (layer14)，可能为空数组（部分片无净版）。 */
  net_polygon: ParsedPt[];
  /** 布纹线 (layer7) 两端点；无则 null。 */
  grain_line: ParsedGrainLine | null;
}

/** 单码结果：码号 + 该码全部裁片（已按裁片码排序：顺序模式=几何稳定序，母版复用=码序）。 */
export interface ParsedSize {
  /** 码号；后端按数值升序、null 殿后排序，前端展示时也按此序。 */
  size: number | null;
  pieces: ParsedPiece[];
}

/** 上传解析响应整体（POST /api/parse-dxf 200 JSON）。 */
export interface ParsedDoc {
  /** 落盘 uuid（无扩展名，32 字符），US-010 /api/commit-to-nesting 入参。 */
  doc_id: string;
  /** 客户端上传的原文件名（中文 UTF-8 正常）。 */
  filename: string;
  /** 全码一次返回（实测 ~1-3MB JSON 可接受，前端按 activeSize 本地切片）。 */
  sizes: ParsedSize[];
}
