// BandPreviewSVG —— 腰头成带形态预览（2026-08-24 布局设置缩略图换带预览）。
//
// 数据源 POST /api/band-preview（后端 build_band_plan 同一真相源：v2 链构造无 RNG、
// seed 不影响几何 ⇒ 预览 = 求解时带的精确形态）。成员 polygon 已是带内归一坐标
// （后端减 chunk.offset），前端零变换直接渲染。
//
// 渲染分层（尺码着色 + 组合片包络，与排料画布 NestSVG 口径一致）：
//   - 成员毛版：fill = size_color（同码同色，半透明）+ 同色实线边 —— 「码序降序 +
//     大码锚定链端」一眼可辨（弧形腰头最右 / 横向弯腰头最底；版师形态判据的
//     视觉验证入口，族形态 v3 起由后端分派自适应）；
//   - 组合片外轮廓（outline，erode d_g 后）：浅色虚线叠加 —— 「主解看到的形状」；
//   - 尺码文字标注（showLabels，仅放大模式）：每成员 bbox 中心叠印码号，屏幕坐标
//     定位（翻转组外，避免镜像）。
//
// 命令式渲染范式（与 PiecePreviewSVG 同）：React 仅渲染空骨架 `<svg ref/>`；
// useEffect 内 imperative 建翻转组 + 各层节点；数据切换整组重建。翻转组
// transform = translate(0 minY+maxY) scale(1 -1)（sparrow Y-up → SVG Y-down，
// 与 PNG / R12-DXF / NestSVG / PiecePreviewSVG 一致）。

import { useEffect, useRef } from 'react';
import type { JSX } from 'react';
import type { BandPreviewMember } from '../../types/band';
import type { Polygon } from '../../types/piece';

const SVGNS = 'http://www.w3.org/2000/svg';

/** 组合片外轮廓虚线颜色（浅中性 —— 与成员尺码色都不冲突）。 */
const COLOR_OUTLINE = '#e8e8e8';
/** 尺码标注文字颜色（暗底亮字，与 g 码标注同口径）。 */
const COLOR_SIZE_LABEL = '#e6e6e6';

/** 默认内边距（mm）。 */
const DEFAULT_PAD = 14;
/** 成员填充不透明度（相邻同码成员靠实线边区分）。 */
const MEMBER_FILL_OPACITY = 0.55;

/** 四舍五入到 2 位小数。 */
function r2(x: number): number {
  return Math.round(x * 100) / 100;
}

/** 顶点列表 → SVG points 属性串（x1,y1 x2,y2 ...）。 */
function pointsToAttr(pts: Polygon): string {
  let out = '';
  for (let i = 0; i < pts.length; i++) {
    const [x, y] = pts[i];
    out += (i ? ' ' : '') + r2(x) + ',' + r2(y);
  }
  return out;
}

/** 轴对齐包围盒（带内归一坐标系，Y-up）。 */
export interface BandBBox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/** 成员 + 组合片轮廓合并 bbox（空数据返回 null）。导出供单测。 */
export function bandBBox(members: BandPreviewMember[], outline?: Polygon | null): BandBBox | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let got = false;
  const absorb = (pts: Polygon): void => {
    for (const [x, y] of pts) {
      got = true;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  };
  for (const m of members) absorb(m.polygon);
  if (outline && outline.length > 0) absorb(outline);
  return got ? { minX, minY, maxX, maxY } : null;
}

export interface BandPreviewSVGProps {
  /** 带内成员（原始轮廓@带内归一位；后端已变换，前端不再 rot/translate）。 */
  members: BandPreviewMember[];
  /** erode 后组合片外轮廓（虚线叠加；缺席 = 只画成员）。 */
  outline?: Polygon | null;
  /** viewBox 内边距（mm），默认 14。 */
  pad?: number;
  /** 尺码文字标注（放大模式 true；缩略 compact 模式 false 默认）。 */
  showLabels?: boolean;
}

/**
 * 成带形态预览 SVG（缩略 / 放大共用：showLabels + pad 差异）。
 * 空数据（members 空且无 outline）→ 清空不画（调用方负责占位文案）。
 */
export function BandPreviewSVG({
  members,
  outline,
  pad = DEFAULT_PAD,
  showLabels = false,
}: BandPreviewSVGProps): JSX.Element {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    // 清空旧内容（数据切换 / StrictMode 双 mount 都安全 —— PiecePreviewSVG 同法）
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    const bb = bandBBox(members, outline);
    if (!bb) return;

    const w = bb.maxX - bb.minX + 2 * pad;
    const h = bb.maxY - bb.minY + 2 * pad;
    svg.setAttribute(
      'viewBox',
      r2(bb.minX - pad) + ' ' + r2(bb.minY - pad) + ' ' + r2(w) + ' ' + r2(h),
    );
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.setAttribute('class', 'band-preview-svg');

    // 1) 翻转组：scale(1,-1) 与 PNG / R12-DXF / NestSVG / PiecePreviewSVG 一致
    const flip = document.createElementNS(SVGNS, 'g');
    flip.setAttribute('transform', 'translate(0 ' + r2(bb.minY + bb.maxY) + ') scale(1 -1)');
    flip.setAttribute('data-role', 'flip');
    svg.appendChild(flip);

    // 2) 成员毛版：尺码色半透明实心 + 同色实线边（同码同色，码序可辨）
    for (const m of members) {
      if (m.polygon.length < 3) continue;
      const poly = document.createElementNS(SVGNS, 'polygon');
      poly.setAttribute('points', pointsToAttr(m.polygon));
      poly.setAttribute('fill', m.color);
      poly.setAttribute('fill-opacity', String(MEMBER_FILL_OPACITY));
      poly.setAttribute('stroke', m.color);
      poly.setAttribute('stroke-width', '1.5');
      poly.setAttribute('stroke-linejoin', 'round');
      poly.setAttribute('data-role', 'band-member');
      poly.setAttribute('data-size', String(m.size));
      flip.appendChild(poly);
    }

    // 3) 组合片外轮廓：浅色虚线（erode d_g 后「主解看到的形状」）
    if (outline && outline.length >= 3) {
      const env = document.createElementNS(SVGNS, 'polygon');
      env.setAttribute('points', pointsToAttr(outline));
      env.setAttribute('fill', 'none');
      env.setAttribute('stroke', COLOR_OUTLINE);
      env.setAttribute('stroke-width', '1.2');
      env.setAttribute('stroke-dasharray', '6 3');
      env.setAttribute('stroke-linejoin', 'round');
      env.setAttribute('data-role', 'band-outline');
      flip.appendChild(env);
    }

    // 4) 成员标注（屏幕坐标，翻转组外避免镜像；锚点 = 成员 bbox 中心，翻转后
    //    屏幕 Y = (minY+maxY) − 世界 Y）。字号随带高自适应（mm 用户单位）。
    //    文本 = tag ?? 尺码（band 预览标尺码；prefix 预览 4 成员同码，tag =
    //    成员 g 码区分前/后幅）。
    if (showLabels) {
      const bandH = Math.max(bb.maxY - bb.minY, 1);
      const fontSize = Math.min(Math.max(bandH * 0.12, 8), 60);
      for (const m of members) {
        if (m.polygon.length < 3) continue;
        let mnX = Infinity;
        let mnY = Infinity;
        let mxX = -Infinity;
        let mxY = -Infinity;
        for (const [x, y] of m.polygon) {
          if (x < mnX) mnX = x;
          if (y < mnY) mnY = y;
          if (x > mxX) mxX = x;
          if (y > mxY) mxY = y;
        }
        const text = document.createElementNS(SVGNS, 'text');
        text.setAttribute('x', String(r2((mnX + mxX) / 2)));
        text.setAttribute('y', String(r2(bb.minY + bb.maxY - (mnY + mxY) / 2)));
        text.setAttribute('fill', COLOR_SIZE_LABEL);
        text.setAttribute('font-size', String(r2(fontSize)));
        text.setAttribute('font-family', 'system-ui, "Microsoft YaHei", sans-serif');
        text.setAttribute('font-weight', '600');
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('dominant-baseline', 'middle');
        text.setAttribute('data-role', 'band-size-label');
        text.textContent = m.tag ?? String(m.size);
        svg.appendChild(text);
      }
    }
  }, [members, outline, pad, showLabels]);

  return <svg ref={svgRef} xmlns={SVGNS} />;
}
