// PiecePreviewSVG —— 单片（或一组）母版裁片预览（US-007）。
//
// 渲染分层（与版师认知 / scripts/preview/*.svg 配色口径一致）：
//   - layer1  毛版（polygon）：半透明蓝实心 + 实线边
//   - layer14 净版（polygon）：绿色虚线，无填充
//   - layer8  内部线（polyline[]）：橙色实线
//   - layer4  刀口（line[]）：黄色短线段，沿轮廓法线 8mm（暂定，待版师确认）
//   - layer7  布纹线（line）：红色虚线
//   - A/B/C 文字标注：暗底亮字（#e6e6e6），在翻转组外用屏幕坐标定位
//
// 命令式渲染范式（参考 NestSVG.tsx）：
//   - React 仅渲染空骨架 `<svg ref/>`；
//   - useEffect 内 imperative 建翻转组 `<g>` + 各层节点（setAttribute 写
//     transform / points / stroke / ...），逃逸 React reconciliation；
//   - 切换 piece(s) 时整组重建（while removeChild 清空，与 NestSVG flipRef 幂等保护不同 ——
//     NestSVG 同 run 内 N 帧复用 DOM，PiecePreviewSVG 每次切片都重建，简洁且切片是低频 UI 操作）。
//
// 关键不变量（写测试 + 后续故事必读）：
//   1. **翻转组 transform = translate(0 minY+maxY) scale(1 -1)** —— sparrow Y-up →
//      SVG Y-down（与 PNG / R12-DXF / NestSVG 一致）。minY+maxY 是 bbox 的 Y 对称轴，
//      翻转后 bbox 内几何视觉与 sparrow 视图一致（不上下颠倒）。NestSVG 是其特例
//      （minY=0, maxY=gate → translate(0 gate) scale(1 -1)）。
//   2. **A/B/C 文字标注放在翻转组 <g> 之外**（避免镜像），用屏幕坐标（SVG Y-down）
//      定位；标注锚点 = 该片 bbox 左上角上方 LABEL_Y_OFFSET（baseline 在 minY - offset），
//      font-size=LABEL_FONT_SIZE（cap 顶 ≈ minY - offset - 0.8*size，pad=14 时刚好在 viewBox 内）。
//   3. **viewBox = bbox + pad**（默认 14，足够容纳 8mm 刀口短线段的一半 4mm + 标注文本 ~10mm）。
//   4. **pad 最小 4**（防 8mm 刀口短线段一半被裁）。
//   5. **刀口端点 = P ± 4 * unit_normal**（unit_normal 来自后端 notch[2..3]），落在翻转组内
//      随几何共翻转。法线为零向量（退化边）时画 0 长度线段（点）兜底，不渲染异常。
//   6. **AC#4 多片同框**：prop 接受单 piece 或 piece[]；多片时合并 bbox 计算 viewBox，
//      每片独立渲染 5 层 + 各自 A/B/C 标注。同框不刻意避免重叠（多片本身可能共享边界，
//      由调用方决定是否同框 —— US-008 ParsedPiecesView 用单片卡片，多片能力留作未来扩展）。
//   7. **compact 模式（US-018 AC#9）**：prop `compact?: boolean` 关 A/B/C 标注 +
//      小 pad（COMPACT_PAD=2，fit-to-cell）；非 compact 行为不变（向后兼容 PieceZoomModal）。
//      用于 PerTypeOverridesModal 表头缩略图 / PtypePreviewModal 放大预览（layer-aware，
//      v1 仅外轮廓，US-024 后数据带 5 层则画 5 层，本组件无需改动）。

import { useEffect, useRef } from 'react';
import type { JSX } from 'react';
import type { ParsedPiece, ParsedPt } from '../../types/parsed';
import { LAYER5_COLORS, NOTCH_LEN_MM } from '../../constants/colors';

const SVGNS = 'http://www.w3.org/2000/svg';

// ---- 颜色常量（US-024 起从 constants/colors.ts 共享；与 NestSVG / web/export.py 同口径） ----
const COLOR_ROUGH_FILL = LAYER5_COLORS.ROUGH_FILL;
const COLOR_ROUGH_STROKE = LAYER5_COLORS.ROUGH_STROKE;
const COLOR_NET = LAYER5_COLORS.NET;
const COLOR_INTERNAL = LAYER5_COLORS.INTERNAL;
const COLOR_NOTCH = LAYER5_COLORS.NOTCH;
const COLOR_GRAIN = LAYER5_COLORS.GRAIN;
const COLOR_LABEL = '#e6e6e6'; // A/B/C 标注（暗底亮字，与 body color 同色）

// ---- 几何常量 ----
/** viewBox 默认内边距（mm）。14 容纳 4mm 刀口半段 + ~10mm 标注文本。 */
const DEFAULT_PAD = 14;
/** compact 模式（缩略图）内边距（mm）。无标注文本 → 小 pad 让几何填满 cell。 */
const COMPACT_PAD = 2;
/** pad 最小值（防刀口短线段被裁）。compact 模式不受此 clamp（缩略图刻意贴近边缘）。 */
const MIN_PAD = 4;
/** A/B/C 标注字体大小（用户单位 = mm）。 */
const LABEL_FONT_SIZE = 11;
/** A/B/C 标注 Y 偏移（baseline 距 bbox 顶部，单位 mm）。 */
const LABEL_Y_OFFSET = 3;

// ---- 类型 + 纯函数（导出便于单测） ----

/** 轴对齐包围盒（sparrow 世界坐标，Y-up）。 */
export interface BBox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/** 四舍五入到 2 位小数（与 lib/geometry.ts r2 字面量一致）。 */
function r2(x: number): number {
  return Math.round(x * 100) / 100;
}

/** 把顶点列表序列化为 SVG points 属性字符串（x1,y1 x2,y2 ...，r2 截断）。 */
function pointsToAttr(pts: ParsedPt[]): string {
  let out = '';
  for (let i = 0; i < pts.length; i++) {
    const [x, y] = pts[i];
    out += (i ? ' ' : '') + r2(x) + ',' + r2(y);
  }
  return out;
}
/**
 * 计算单片裁片所有层（polygon + net + internal + notch + grain）的合并包围盒。
 * 空片（全无数据）返回 null。
 */
export function pieceBBox(piece: ParsedPiece): BBox | null {
  const pts: ParsedPt[] = [];
  for (const [x, y] of piece.polygon) pts.push([x, y]);
  for (const [x, y] of piece.net_polygon) pts.push([x, y]);
  for (const line of piece.internal_lines) {
    for (const [x, y] of line) pts.push([x, y]);
  }
  for (const [x, y] of piece.notches) pts.push([x, y]);
  if (piece.grain_line) {
    const [x1, y1, x2, y2] = piece.grain_line;
    pts.push([x1, y1], [x2, y2]);
  }
  if (pts.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of pts) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return { minX, minY, maxX, maxY };
}

/**
 * 合并多个 piece 的 bbox（用于多片同框 viewBox 计算）。全部为空片返回 null。
 */
export function piecesBBox(pieces: ParsedPiece[]): BBox | null {
  let accMinX = Infinity;
  let accMinY = Infinity;
  let accMaxX = -Infinity;
  let accMaxY = -Infinity;
  let got = false;
  for (const p of pieces) {
    const bb = pieceBBox(p);
    if (!bb) continue;
    got = true;
    if (bb.minX < accMinX) accMinX = bb.minX;
    if (bb.minY < accMinY) accMinY = bb.minY;
    if (bb.maxX > accMaxX) accMaxX = bb.maxX;
    if (bb.maxY > accMaxY) accMaxY = bb.maxY;
  }
  if (!got) return null;
  return { minX: accMinX, minY: accMinY, maxX: accMaxX, maxY: accMaxY };
}

// ---- DOM 构造辅助 ----

/** 创建翻转组（所有几何共翻转；transform 用 setAttribute 写，避免 React 覆盖）。 */
function createFlipGroup(minY: number, maxY: number): SVGGElement {
  const g = document.createElementNS(SVGNS, 'g');
  g.setAttribute('transform', 'translate(0 ' + r2(minY + maxY) + ') scale(1 -1)');
  g.setAttribute('data-role', 'flip');
  return g;
}

/** 渲染单片的所有几何层到 flipGroup（顺序：rough → net → internal → notch → grain）。 */
function renderPieceLayers(flipGroup: SVGGElement, piece: ParsedPiece): void {
  // layer1 毛版（半透明蓝实心 + 实线边）—— 闭合 polygon
  if (piece.polygon.length >= 3) {
    const rough = document.createElementNS(SVGNS, 'polygon');
    rough.setAttribute('points', pointsToAttr(piece.polygon));
    rough.setAttribute('fill', COLOR_ROUGH_FILL);
    rough.setAttribute('stroke', COLOR_ROUGH_STROKE);
    rough.setAttribute('stroke-width', '1.5');
    rough.setAttribute('stroke-linejoin', 'round');
    rough.setAttribute('data-role', 'rough');
    flipGroup.appendChild(rough);
  }

  // layer14 净版（绿虚线，闭合 polygon，无填充）—— 后端闭合 POLYLINE 无重复起点
  if (piece.net_polygon.length >= 3) {
    const net = document.createElementNS(SVGNS, 'polygon');
    net.setAttribute('points', pointsToAttr(piece.net_polygon));
    net.setAttribute('fill', 'none');
    net.setAttribute('stroke', COLOR_NET);
    net.setAttribute('stroke-width', '1.2');
    net.setAttribute('stroke-dasharray', '6 3');
    net.setAttribute('stroke-linejoin', 'round');
    net.setAttribute('data-role', 'net');
    flipGroup.appendChild(net);
  }

  // layer8 内部线（橙实线 polyline，每条不闭合）
  for (const line of piece.internal_lines) {
    if (line.length < 2) continue;
    const internal = document.createElementNS(SVGNS, 'polyline');
    internal.setAttribute('points', pointsToAttr(line));
    internal.setAttribute('fill', 'none');
    internal.setAttribute('stroke', COLOR_INTERNAL);
    internal.setAttribute('stroke-width', '1');
    internal.setAttribute('stroke-linejoin', 'round');
    internal.setAttribute('stroke-linecap', 'round');
    internal.setAttribute('data-role', 'internal');
    flipGroup.appendChild(internal);
  }

  // layer4 刀口（沿轮廓法线 8mm 短线段；法线为零向量时退化为 0 长度线段）
  const half = NOTCH_LEN_MM / 2;
  for (const [x, y, nx, ny] of piece.notches) {
    const line = document.createElementNS(SVGNS, 'line');
    line.setAttribute('x1', String(r2(x - nx * half)));
    line.setAttribute('y1', String(r2(y - ny * half)));
    line.setAttribute('x2', String(r2(x + nx * half)));
    line.setAttribute('y2', String(r2(y + ny * half)));
    line.setAttribute('stroke', COLOR_NOTCH);
    line.setAttribute('stroke-width', '1.4');
    line.setAttribute('stroke-linecap', 'round');
    line.setAttribute('data-role', 'notch');
    flipGroup.appendChild(line);
  }

  // layer7 布纹线（红虚线，单条直线；后端 [x1,y1,x2,y2] 或 null）
  if (piece.grain_line) {
    const [x1, y1, x2, y2] = piece.grain_line;
    const grain = document.createElementNS(SVGNS, 'line');
    grain.setAttribute('x1', String(r2(x1)));
    grain.setAttribute('y1', String(r2(y1)));
    grain.setAttribute('x2', String(r2(x2)));
    grain.setAttribute('y2', String(r2(y2)));
    grain.setAttribute('stroke', COLOR_GRAIN);
    grain.setAttribute('stroke-width', '1.2');
    grain.setAttribute('stroke-dasharray', '5 3');
    grain.setAttribute('data-role', 'grain');
    flipGroup.appendChild(grain);
  }
}
/**
 * 在 svg 根（翻转组外）渲染 A/B/C 文字标注。屏幕坐标（SVG Y-down）定位 ——
 * 不进翻转组避免镜像；锚点 = piece bbox 左上角上方 LABEL_Y_OFFSET（baseline 在 minY - offset）。
 */
function renderLabel(svg: SVGSVGElement, piece: ParsedPiece): void {
  if (!piece.label) return;
  const bb = pieceBBox(piece);
  if (!bb) return;
  const text = document.createElementNS(SVGNS, 'text');
  text.setAttribute('x', String(r2(bb.minX)));
  // SVG Y-down：minY 是 bbox 顶部；baseline 距顶部 LABEL_Y_OFFSET（屏幕坐标，文字位于 bbox 上方）
  text.setAttribute('y', String(r2(bb.minY - LABEL_Y_OFFSET)));
  text.setAttribute('fill', COLOR_LABEL);
  text.setAttribute('font-size', String(LABEL_FONT_SIZE));
  // font-family 用 CSS 标准双引号包字体名（首尾单引号是 JS 字符串字面量）
  text.setAttribute('font-family', 'system-ui, "Microsoft YaHei", sans-serif');
  text.setAttribute('font-weight', '600');
  text.setAttribute('text-anchor', 'start');
  text.setAttribute('dominant-baseline', 'alphabetic');
  text.setAttribute('data-role', 'label');
  text.textContent = piece.label;
  svg.appendChild(text);
}

// ---- 主组件 ----

export interface PiecePreviewSVGProps {
  /** 单片或一组片（AC#4）；多片时合并 bbox 计算 viewBox，每片独立渲染分层 + 各自标注。 */
  piece: ParsedPiece | ParsedPiece[];
  /** viewBox 内边距（mm），默认 14（容纳 8mm 刀口 + 标注文本）；最小 4。 */
  pad?: number;
  /**
   * US-018 AC#9 compact 模式：关 A/B/C 标注 + 用 COMPACT_PAD(2) 默认 pad（fit-to-cell）。
   * 用于 PerTypeOverridesModal 表头缩略图（64×64 cell）。非 compact 行为不变（向后兼容）。
   */
  compact?: boolean;
}

/**
 * 单片母版预览 SVG。
 *
 * 命令式渲染：React 仅渲染 `<svg ref/>`；useEffect 内 imperative 建 flipGroup +
 * 各层节点 + 标注 text。piece 切换时整组重建（清空 svg 子节点后重画）。
 *
 * compact 模式（US-018）：跳过 renderLabel + 用 COMPACT_PAD；layer-aware 渲染不变
 * （数据有几层就画几层，v1 仅 polygon，US-024 后 5 层）。
 */
export function PiecePreviewSVG({
  piece,
  pad,
  compact = false,
}: PiecePreviewSVGProps): JSX.Element {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const pieces: ParsedPiece[] = Array.isArray(piece) ? piece : [piece];
    // compact 模式 pad 默认 COMPACT_PAD（2），非 compact 默认 DEFAULT_PAD（14）。
    // 显式传入 pad 仍生效（PieceZoomModal 用 pad=20）；compact 下显式 pad 亦受 MIN_PAD 保护。
    const effectivePad = pad ?? (compact ? COMPACT_PAD : DEFAULT_PAD);
    const safePad = compact ? effectivePad : Math.max(MIN_PAD, effectivePad);

    // 清空旧内容（piece 切换 / StrictMode 双 mount 都安全）
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    const bb = piecesBBox(pieces);
    if (!bb) return; // 全空片：清空后啥都不画（不留残影）

    // viewBox = bbox + pad（在 sparrow Y-up 坐标系下计算；flipGroup 内翻转后视觉一致）
    const w = bb.maxX - bb.minX + 2 * safePad;
    const h = bb.maxY - bb.minY + 2 * safePad;
    svg.setAttribute(
      'viewBox',
      r2(bb.minX - safePad) + ' ' + r2(bb.minY - safePad) + ' ' + r2(w) + ' ' + r2(h),
    );
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.setAttribute('class', 'piece-preview-svg');

    // 1) 翻转组：所有几何共翻转，scale(1,-1) 与 PNG / R12-DXF / NestSVG 一致
    const flip = createFlipGroup(bb.minY, bb.maxY);
    svg.appendChild(flip);
    for (const p of pieces) renderPieceLayers(flip, p);

    // 2) A/B/C 文字标注（屏幕坐标，翻转组外）—— compact 模式跳过（缩略图无标注）
    if (!compact) {
      for (const p of pieces) renderLabel(svg, p);
    }
  }, [piece, pad, compact]);

  return <svg ref={svgRef} xmlns={SVGNS} />;
}
