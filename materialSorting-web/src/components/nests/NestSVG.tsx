// NestSVG —— 排料图 SVG（命令式渲染，逃逸 React reconciliation）。
//
// 与旧 app.js `onManifest` + `renderFrame` + `setupHover` 等价。React 只渲染一次空骨架 `<svg ref/>`，
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
//
// US-006 增量：
//   5. 回放感知：seekTime >= 0 时改用 frameAtTime(run, seekTime)（二分，lib/seek.ts）；
//      seekTime = -1 时维持 live（lastFrame）。effect deps 加 seekTime，拖动时立即重绘。
//   6. flipGroup 上事件委托 mousemove + mouseleave（AC#4）：e.target.closest('polygon') + dataset.ptype
//      → Tooltip 显示片型/码/面积(cm²)；切换 polygon 时旧高亮 class 自动移除（AC#6）。
//      高频 mousemove 直接 mutate Tooltip DOM（imperative，不进 React state）。

import { useEffect, useRef } from 'react';
import { useAppStore } from '../../store/appStore';
import type { RunRecord } from '../../store/runRegistry';
import type { PieceInfo, Polygon } from '../../types/piece';
import type { FrameMsg } from '../../types/ws';
import { pointsStr } from '../../lib/geometry';
import { frameAtTime } from '../../lib/seek';
import { clearHovered, hideTooltip, setHovered, showTooltip } from '../Tooltip';

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
  // US-006：订阅 seekTime，拖动时立即切到 frameAtTime(run, seekTime)。
  const seekTime = useAppStore((s) => s.seekTime);

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

      // US-006 AC#4..#6：flipGroup 上事件委托 mousemove + mouseleave。
      // 与旧 app.js setupHover 等价（旧版绑 svg，AC 要求 flipGroup；多边形均在 flipGroup 内，
      // 行为一致：mousemove 落在 polygon → 显 tooltip + 高亮；其他 / mouseleave → 隐 + 移除高亮）。
      g.addEventListener('mousemove', handleHover);
      g.addEventListener('mouseleave', handleHoverEnd);
    }

    // 2) 渲染当前帧（imperative setAttribute —— 不触发 React reconciliation）。
    //    US-006：seekTime >= 0 → frameAtTime(run, seekTime)；否则 lastFrame（live）。
    const flip = flipRef.current;
    const bg = bgRef.current;
    const fab = fabRef.current;
    if (!flip || !bg || !fab) return;
    if (!run.manifest) return;

    const f: FrameMsg | null = seekTime >= 0 ? frameAtTime(run, seekTime) : run.lastFrame;
    if (!f) return;

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
  }, [renderTick, seekTime, run]);

  return <svg ref={svgRef} xmlns={SVGNS} />;
}

/**
 * mousemove 事件委托处理器（绑在 flipGroup 上）。
 *
 * 与旧 app.js setupHover 内 mousemove 一致：
 *   - poly = e.target.closest('polygon')（事件委托，e.target 可能是 polygon 本身或其子节点）
 *   - poly && poly.dataset.ptype → setHovered + showTooltip（片型/码/面积 cm²）
 *   - 否则 → clearHovered + hideTooltip
 *
 * 面积换算：dataset.area 单位 mm²，÷100 → cm²（与旧 app.js `parseFloat/100` 一致）。
 */
function handleHover(e: MouseEvent): void {
  const target = e.target as Element | null;
  const poly = target?.closest('polygon') as SVGPolygonElement | null;
  if (poly && poly.dataset.ptype) {
    setHovered(poly);
    const area_cm2 = (parseFloat(poly.dataset.area || '0') / 100).toFixed(1);
    showTooltip(
      e.clientX,
      e.clientY,
      `${poly.dataset.ptype} · 码${poly.dataset.size}<br>面积 ${area_cm2} cm²`,
    );
  } else {
    clearHovered();
    hideTooltip();
  }
}

/** mouseleave 处理器：移除高亮 + 隐 tooltip（与旧 app.js setupHover mouseleave 一致）。 */
function handleHoverEnd(): void {
  clearHovered();
  hideTooltip();
}

/** 暴露给单测 / 调试用（提取翻转后的 polygon，仅作内部辅助）。 */
export function _rotatedPolygon(poly: Polygon, rot: number, tr: [number, number]): string {
  return pointsStr(poly, rot, tr);
}
