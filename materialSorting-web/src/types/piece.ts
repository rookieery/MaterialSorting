// 裁片几何 / 位置 类型。
// 与后端 server.py / solver.py 字段名一致（id / ptype / size / color / area_mm2 / polygon / rotation / translation）。

/** 多边形顶点 [x_mm, y_mm]（与 sparrow 世界坐标一致：X=用布长度，Y=门幅向上）。 */
export type Pt = [number, number];

/** 多边形 = 顶点数组（R12 POLYLINE 闭合，无重复起点）。 */
export type Polygon = Pt[];

/** manifest 推送的单片几何 + 元信息（erode 后的 base 多边形）。 */
export interface PieceInfo {
  id: string;
  ptype: string;
  size: number;
  color: string;
  area_mm2: number;
  polygon: Polygon;
}

/** frame.placed_items[] —— 已放置裁片的变换（与后端 solver._emit placed 一致）。 */
export interface PlacedItem {
  id: string;
  rotation: number;
  translation: Pt;
}
