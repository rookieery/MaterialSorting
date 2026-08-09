// NestSVG —— 排料图 SVG（命令式渲染，逃逸 React reconciliation）。
//
// 与旧 app.js `onManifest` + `renderFrame` 等价。React 只渲染一次空骨架 `<svg ref/>`，
// 之后所有更新（翻转组 transform / polygon points / viewBox / 用布矩形 / 背景矩形）都走
// `setAttribute` —— 即使 100ms bump 一次 renderTick，也只触发 imperative DOM 写入，
// 不触发 React diff。
//
// 关键不变量（与 AGENTS.md #2 / #3 一致）：
//   1. 翻转组 transform = `translate(0 ${gate_mm}) scale(1 -1)` —— sparrow Y 向上 → SVG Y 向下。
//      用 setAttribute 写，不走 JSX prop（否则 React reconciliation 会按 vdom 覆盖回旧值）。
//   2. manifest 到达后建一次 DOM（bg / fab / flipGroup + N 个 polygon）；后续只改 points/display。
//   3. pointsStr(poly, rot, tr) 输出与旧 app.js 字节级一致（lib/geometry.ts 单测覆盖）。
//   4. 未 placed 的 polygon display:none；placed 的 display:''（与旧 app.js 一致）。

import { useEffect, useRef } from 'react';
import { useAppStore } from '../../store/appStore';
import type { RunRecord } from '../../store/runRegistry';
import type { PieceInfo, Polygon } from '../../types/piece';
import { pointsStr } from '../../lib/geometry';

const SVGNS = 'http://www.w3.org/2000/svg';

/** 单个裁片的引用持有（base 多边形 + DOM 节点）。 */
interface PieceEntry {
  el: SVGPolygonElement;
  piece: PieceInfo;
}

export interface NestSVGProps {
  run: RunRecord;
}

export function NestSVG({ run }: NestSVGProps) {
  // React 只持有空骨架 `<svg>` 一次；其余节点全部 imperative。
  const svgRef = useRef<SVGSVGElement>(null);
  const flipRef = useRef<SVGGElement | null>(null);
  const bgRef = useRef<SVGRectElement | null>(null);
  const fabRef = useRef<SVGRectElement | null>(null);
  /** id → { el, piece }，manifest 到达后填充。 */
  const piecesRef = useRef<Map<string, PieceEntry>>(new Map());

  // 订阅 renderTick —— bump 触发 effect 重跑（imperative 更新 DOM）。
  const renderTick = useAppStore((s) => s.renderTick);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    // 1) manifest 到达 → 一次性建立骨架（bg + 用布矩形 + 翻转组 + N polygon）。
    //    幂等保护：flipRef 已存在则跳过（防 React 18 StrictMode 双 mount 重建）。
    if (run.manifest && !flipRef.current) {
      const bg = document.createElementNS(SVGNS, 'rect');
      bg.setAttribute('fill', '#eef0f3');

      const fab = document.createElementNS(SVGNS, 'rect');
      fab.setAttribute('fill', '#fff');
      fab.setAttribute('fill-opacity', '0.55');
      fab.setAttribute('stroke', '#8a8a8a');
      fab.setAttribute('stroke-dasharray', '8 5');
      fab.setAttribute('stroke-width', '1.5');

      // 翻转组：translate(0 gate) scale(1 -1) —— sparrow Y 向上 → SVG Y 向下，与 PNG/R12-DXF 一致。
      // setAttribute 写 transform（避免 React reconciliation 按 vdom 覆盖）。
      const g = document.createElementNS(SVGNS, 'g');
      g.setAttribute('transform', `translate(0 ${run.manifest.gate_mm}) scale(1 -1)`);

      svg.appendChild(bg);
      svg.appendChild(fab);
      svg.appendChild(g);

      bgRef.current = bg;
      fabRef.current = fab;
      flipRef.current = g;

      for (const p of run.manifest.pieces) {
        const poly = document.createElementNS(SVGNS, 'polygon');
        poly.setAttribute('fill', p.color);
        poly.setAttribute('fill-opacity', '0.55');
        poly.setAttribute('stroke', p.color);
        poly.setAttribute('stroke-width', '1.2');
        poly.style.display = 'none';
        poly.dataset.ptype = p.ptype;
        poly.dataset.size = String(p.size);
        poly.dataset.area = String(p.area_mm2);
        g.appendChild(poly);
        piecesRef.current.set(p.id, { el: poly, piece: p });
      }
    }

    // 2) 渲染最新一帧（imperative setAttribute —— 不触发 React reconciliation）。
    const flip = flipRef.current;
    const bg = bgRef.current;
    const fab = fabRef.current;
    if (!flip || !bg || !fab) return;
    if (!run.manifest || !run.lastFrame) return;

    const f = run.lastFrame;
    const gate = run.manifest.gate_mm;
    // viewBox 用历史最大 width 作稳定锚（避免收缩抖动），与旧 app.js 一致。
    const W = Math.max(run.viewBoxMaxW, f.width_mm, 1);

    svg.setAttribute('viewBox', `0 0 ${W} ${gate}`);
    svg.setAttribute('preserveAspectRatio', 'xMinYMid meet');
    bg.setAttribute('x', '0');
    bg.setAttribute('y', '0');
    bg.setAttribute('width', String(W));
    bg.setAttribute('height', String(gate));
    fab.setAttribute('x', '0');
    fab.setAttribute('y', '0');
    fab.setAttribute('width', String(f.width_mm));
    fab.setAttribute('height', String(gate));

    // placed → 显示 + 写 points；未 placed → display:none
    const placed = new Set<string>();
    for (const it of f.placed_items) {
      const entry = piecesRef.current.get(it.id);
      if (!entry) continue;
      placed.add(it.id);
      entry.el.setAttribute('points', pointsStr(entry.piece.polygon, it.rotation, it.translation));
      entry.el.style.display = '';
    }
    for (const [id, entry] of piecesRef.current) {
      if (!placed.has(id)) entry.el.style.display = 'none';
    }
  }, [renderTick, run]);

  return <svg ref={svgRef} xmlns={SVGNS} />;
}

/** 暴露给单测 / 调试用（提取翻转后的 polygon，仅作内部辅助）。 */
export function _rotatedPolygon(poly: Polygon, rot: number, tr: [number, number]): string {
  return pointsStr(poly, rot, tr);
}
