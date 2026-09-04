// pieceDom —— 裁片 5 层 DOM 节点构建（毛版 polygon / 净版 / 内部线 / 刺口 / 布纹线）。
//
// 编辑排料 US-002 自 NestSVG.tsx:273-347 机械提取（纯搬移零行为变化 —— 唯一动现有
// 渲染代码的点），供 NestSVG（主排料视图）与 edit/EditCanvas（编辑弹窗画布）共用，
// 保证两视图 5 层节点结构 / 配色 / dataset 逐属性一致（弹窗与主视图同构同观感的地基）。
//
// 关键约定（与 NestSVG / AGENTS.md US-024 一致）：
//   - layer1 毛版 polygon 用尺码配色（manifest p.color 透传后端 size_color，同码同色
//     跨片型）；tooltip / 命中判定走 dataset.label（g 码）。
//   - 其余 4 层用工艺色 constants/colors.ts LAYER5_COLORS，pointerEvents='none'
//     （事件只落在毛版 polygon 上）。
//   - 所有节点初始 display:none（等 frame / working 到达再显），layer-aware：
//     数据缺失的层不建节点（null / 空数组）。

import type { PieceInfo } from '../../types/piece';
import { LAYER5_COLORS } from '../../constants/colors';

export const SVGNS = 'http://www.w3.org/2000/svg';

/**
 * 单个裁片的引用持有（毛版 polygon + 4 层工艺 DOM 节点，US-024）。
 *
 * - el: 毛版 polygon（layer1）—— 尺码配色（size_color 单一真相源，同码同色跨片型），与 mousemove tooltip 联动。
 * - netEl / internalEls / notchEls / grainEl: 4 层工艺节点（layer14/8/4/7）—— 仅渲染透传。
 * - 所有节点在 manifest 到达时一次性创建，frame 切换只 setAttribute。
 */
export interface PieceEntry {
  /** 毛版 polygon（layer1）。 */
  el: SVGPolygonElement;
  /** 净版 polygon（layer14，绿虚线）；无数据时 null。 */
  netEl: SVGPolygonElement | null;
  /** 内部线 polyline 列表（layer8，橙实线）；无数据时空数组。 */
  internalEls: SVGPolylineElement[];
  /** 刺口 line 列表（layer4，黄短线段）；无数据时空数组。 */
  notchEls: SVGLineElement[];
  /** 布纹线 line（layer7，红虚线）；无数据时 null。 */
  grainEl: SVGLineElement | null;
  piece: PieceInfo;
}

/**
 * 为单片 PieceInfo 创建一组 5 层 DOM 节点（毛版 polygon + net/internal/notch/grain）并 append 到 g。
 * 返回 PieceEntry 持有这些节点引用。demand>1 时对本函数调用 N 次 → N 个独立副本（多副本渲染）。
 *
 * 与旧 vanilla 实现 onManifest 内单片建节点逻辑等价（layer1 尺码配色 + US-024 4 层）。
 * 所有节点初始 display:none（等 frame 到达再显）。纯提取，无行为变更。
 */
export function createPieceEntry(p: PieceInfo, g: SVGGElement): PieceEntry {
  // layer1 毛版 polygon（尺码配色，manifest p.color 透传后端 size_color）—— 与既有渲染一致（mouse 联动仅绑此层）
  const poly = document.createElementNS(SVGNS, 'polygon');
  poly.setAttribute('fill', p.color);
  poly.setAttribute('fill-opacity', '0.55');
  poly.setAttribute('stroke', p.color);
  poly.setAttribute('stroke-width', '1.2');
  poly.style.display = 'none';
  poly.dataset.size = String(p.size);
  poly.dataset.area = String(p.area_mm2);
  // g 码裁片标识（v2 manifest 必有；旧后端无 → undefined，tooltip 命中判定降级不显）
  if (p.label) poly.dataset.label = p.label;
  g.appendChild(poly);

  // US-024 layer14 净版（绿 dashed polygon，无填充）—— 数据缺失不渲染
  let netEl: SVGPolygonElement | null = null;
  if (p.net_polygon && p.net_polygon.length >= 3) {
    netEl = document.createElementNS(SVGNS, 'polygon');
    netEl.setAttribute('fill', 'none');
    netEl.setAttribute('stroke', LAYER5_COLORS.NET);
    netEl.setAttribute('stroke-width', '1.2');
    netEl.setAttribute('stroke-dasharray', '6 3');
    netEl.setAttribute('stroke-linejoin', 'round');
    netEl.style.display = 'none';
    netEl.style.pointerEvents = 'none';
    g.appendChild(netEl);
  }

  // US-024 layer8 内部线（橙实线 polyline 列表，不闭合）—— 数据缺失空数组
  const internalEls: SVGPolylineElement[] = [];
  if (p.internal_lines) {
    for (const line of p.internal_lines) {
      if (line.length < 2) continue;
      const el = document.createElementNS(SVGNS, 'polyline');
      el.setAttribute('fill', 'none');
      el.setAttribute('stroke', LAYER5_COLORS.INTERNAL);
      el.setAttribute('stroke-width', '1');
      el.setAttribute('stroke-linejoin', 'round');
      el.setAttribute('stroke-linecap', 'round');
      el.style.display = 'none';
      el.style.pointerEvents = 'none';
      g.appendChild(el);
      internalEls.push(el);
    }
  }

  // US-024 layer4 刺口（黄 line 短线段，沿法线 NOTCH_LEN_MM）—— 数据缺失空数组
  const notchEls: SVGLineElement[] = [];
  if (p.notches) {
    for (const _n of p.notches) {
      const el = document.createElementNS(SVGNS, 'line');
      el.setAttribute('stroke', LAYER5_COLORS.NOTCH);
      el.setAttribute('stroke-width', '1.4');
      el.setAttribute('stroke-linecap', 'round');
      el.style.display = 'none';
      el.style.pointerEvents = 'none';
      g.appendChild(el);
      notchEls.push(el);
    }
  }

  // US-024 layer7 布纹线（红 dashed line）—— 数据缺失/null 不渲染
  let grainEl: SVGLineElement | null = null;
  if (p.grain_line && p.grain_line.length === 4) {
    grainEl = document.createElementNS(SVGNS, 'line');
    grainEl.setAttribute('stroke', LAYER5_COLORS.GRAIN);
    grainEl.setAttribute('stroke-width', '1.2');
    grainEl.setAttribute('stroke-dasharray', '5 3');
    grainEl.style.display = 'none';
    grainEl.style.pointerEvents = 'none';
    g.appendChild(grainEl);
  }

  return { el: poly, netEl, internalEls, notchEls, grainEl, piece: p };
}
