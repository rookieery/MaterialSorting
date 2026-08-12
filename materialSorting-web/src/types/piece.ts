// 裁片几何 / 位置 类型。
// 与后端 server.py / solver.py 字段名一致（id / ptype / size / color / area_mm2 / polygon / rotation / translation）。
//
// US-024 起 PieceInfo 扩 5 层字段（net_polygon / internal_lines / notches / grain_line），
// 与后端 manifest 同口径；字段 optional → 缺失时各层视为空/不渲染（前端 layer-aware）。

/** 多边形顶点 [x_mm, y_mm]（与 sparrow 世界坐标一致：X=用布长度，Y=门幅向上）。 */
export type Pt = [number, number];

/** 多边形 = 顶点数组（R12 POLYLINE 闭合，无重复起点）。 */
export type Polygon = Pt[];

/** 刺口：[x, y, nx, ny] —— 点位 + 沿所属轮廓边的单位法向量（与 ParsedNotch 同结构）。 */
export type Notch = [number, number, number, number];

/** 布纹线两端点 [x1, y1, x2, y2]（与 ParsedGrainLine 同结构）。 */
export type GrainLine = [number, number, number, number];

/** manifest 推送的单片几何 + 元信息（erode 后的 base 多边形）。 */
export interface PieceInfo {
  id: string;
  ptype: string;
  size: number;
  color: string;
  area_mm2: number;
  polygon: Polygon;
  /**
   * 该 pid 进 sparrow 的**副本数**（= quantities[label][sizeKey]；缺省/未分发 → 1）。
   *
   * demand>1 时 solver 给同一 pid 发 N 条 placed_items（同 id、不同 translation）。
   * 前端 NestSVG 按 demand 预建 N 个 DOM 副本，按「出现序」把第 k 条 placement 渲染到第 k 个
   * 副本节点 —— 否则 N 条 placement 共用同一个 polygon、后覆盖前，只剩 1/N 可见
   * （视觉稀疏，但密度数字仍正确，极隐蔽）。
   */
  demand?: number;
  /**
   * US-024 5 层（仅渲染/导出透传，**不参与 sparrow NFP 碰撞**）。字段 optional → 旧后端
   * 不分发时各层视为空/不渲染。与 types/parsed.ts ParsedPiece 同 schema。
   */
  net_polygon?: Polygon;
  internal_lines?: Polygon[];
  notches?: Notch[];
  grain_line?: GrainLine | null;
}

/** frame.placed_items[] —— 已放置裁片的变换（与后端 solver._emit placed 一致）。 */
export interface PlacedItem {
  id: string;
  rotation: number;
  translation: Pt;
}
