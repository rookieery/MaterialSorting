// 纯几何算子（与后端 _transform_polygon / 旧 vanilla 实现 pointsStr 一致）。
//
// 坐标系约定（CLAUDE.md）：
//   sparrow 世界坐标 X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上；
//   SVG 用 scale(1,-1) 翻转后与 PNG / R12-DXF 导出口径一致。
//
// pointsStr 输出与旧 vanilla 前身 字节级一致（单测对比同输入）；任何修改需同步后端 _transform_polygon。

import type { Polygon, Pt } from '../types/piece';

/** 四舍五入到 2 位小数（与旧 vanilla 实现 `r2` 一致）。 */
export function r2(x: number): number {
  return Math.round(x * 100) / 100;
}

/**
 * 将裁片 base 多边形按 rotation(°) + translation[tx,ty] 变换为 SVG `points` 字符串。
 *
 * 与旧 vanilla 实现 / 后端 _transform_polygon 字节级一致：
 *   rad = rot * π/180; c = cos(rad); s = sin(rad)
 *   x' = x*c − y*s + tx
 *   y' = x*s + y*c + ty
 *
 * mirror=true（edit-keyboard US-001 起，缺省 false 零回归）：局部坐标系 x 翻转
 * （`world = R·diag(−1,1)·p + t`），等价于旋转前对顶点 x 取负：
 *   x' = −x*c − y*s + tx
 *   y' = −x*s + y*c + ty
 * —— 即 `pointsStr(poly, rot, tr, true)` 与 `pointsStr(x 取负后的 poly, rot, tr)`
 * 逐字节相同。缺省 false / 显式 false 路径与旧实现逐字节一致。
 *
 * 输出格式：`r2(x1),r2(y1) r2(x2),r2(y2) ...`（点间空格，无尾随空格）。
 *
 * @param poly   base 多边形顶点（与 manifest.pieces[].polygon 同口径）
 * @param rot    旋转角度（°；与 frame.placed_items[].rotation 一致）
 * @param tr     平移 [tx, ty]（与 frame.placed_items[].translation 一致）
 * @param mirror true = 局部 x 翻转（水平镜像；PlacedItem.mirror，缺省 false）
 */
export function pointsStr(poly: Polygon, rot: number, tr: Pt, mirror = false): string {
  const r = (rot * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  const tx = tr[0];
  const ty = tr[1];
  let out = '';
  for (let i = 0; i < poly.length; i++) {
    const x = mirror ? -poly[i][0] : poly[i][0];
    const y = poly[i][1];
    out += (i ? ' ' : '') + r2(x * c - y * s + tx) + ',' + r2(x * s + y * c + ty);
  }
  return out;
}
