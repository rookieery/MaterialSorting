// NestSVG —— 排料图 SVG（命令式渲染，逃逸 React reconciliation）。
//
// 与旧 vanilla 实现 `onManifest` + `renderFrame` + `setupHover` 等价。React 只渲染一次空骨架 `<svg ref/>`，
// 之后所有更新（翻转组 transform / polygon points / viewBox / 用布矩形 / 背景矩形）都走
// `setAttribute` —— 即使 100ms bump 一次 renderTick，也只触发 imperative DOM 写入，
// 不触发 React diff。
//
// 关键不变量（与 AGENTS.md #2 / #3 一致）：
//   1. 翻转组 transform = `translate(0 ${gate_mm}) scale(1 -1)` —— sparrow Y 向上 → SVG Y 向下。
//      用 setAttribute 写，不走 JSX prop（否则 React reconciliation 会按 vdom 覆盖回旧值）。
//   2. manifest 到达后建一次 DOM（bg / fab / 实际排料边界红虚线 / flipGroup + N 个 polygon）；
//      后续只改 points/display（边界线只改 x2/y）。
//   3. pointsStr(poly, rot, tr) 输出与旧 vanilla 实现 字节级一致（lib/geometry.ts 单测覆盖）。
//   4. 未 placed 的 polygon display:none；placed 的 display:''（与旧 vanilla 实现 一致）。
//
// US-006 增量：
//   5. 回放感知：seekTime >= 0 时改用 frameAtTime(run, seekTime)（二分，lib/seek.ts）；
//      seekTime = -1 时维持 live（lastFrame）。effect deps 加 seekTime，拖动时立即重绘。
//   6. flipGroup 上事件委托 mousemove + mouseleave（AC#4）：e.target.closest('polygon') +
//      dataset.label（裁片 g 码，US-003 起 manifest 唯一标识）→ Tooltip 显示
//      `g03 · 码28` + 面积(cm²)；切换 polygon 时旧高亮 class 自动移除（AC#6）。
//      高频 mousemove 直接 mutate Tooltip DOM（imperative，不进 React state）。
//
// US-024 增量（5 层渲染）：
//   7. 毛版 polygon（既有）之上叠加 net_polygon（绿 dashed polygon）+ internal_lines（橙 polyline）+
//      notches（黄 line 短线段）+ grain_line（红 dashed line）。配色复用 PiecePreviewSVG 的
//      constants/colors.ts LAYER5_COLORS（视觉一致）。所有 5 层都在翻转组内（scale(1,-1)），
//      共用 placement transform（rotation + translation）。
//   8. 性能保护：5 层节点只在 manifest 到达时建一次（与 polygon 同位置），frame 切换只
//      setAttribute('display'/'points'/'x1'/'y1'/'x2'/'y2'/'transform')，不重建 DOM；128 片 ×
//      5 节点 ~10fps 可承受（AC#5）。
//   9. 关键不变量：求解碰撞仍只用毛版 polygon（sparrow NFP，已 erode）；其余 4 层仅渲染透传。

import { useEffect, useRef } from 'react';
import { useAppStore } from '../../store/appStore';
import type { RunRecord } from '../../store/runRegistry';
import type { Notch, Polygon } from '../../types/piece';
import type { FrameMsg, ManifestMsg } from '../../types/ws';
import { pointsStr } from '../../lib/geometry';
import { frameAtTime } from '../../lib/seek';
import { clearHovered, hideTooltip, setHovered, showTooltip } from '../Tooltip';
import { NOTCH_LEN_MM } from '../../constants/colors';
// 编辑排料 US-002：5 层节点构建（SVGNS / PieceEntry / createPieceEntry）机械提取到
// pieceDom.ts（与 edit/EditCanvas 共用 —— 弹窗与主视图同构同观感的地基），纯搬移零行为变化。
import { createPieceEntry, SVGNS, type PieceEntry } from './pieceDom';

export interface NestSVGProps {
  run: RunRecord;
}

export function NestSVG({ run }: NestSVGProps) {
  // React 只持有空骨架 `<svg>` 一次；其余节点全部 imperative。
  const svgRef = useRef<SVGSVGElement>(null);
  const flipRef = useRef<SVGGElement | null>(null);
  const bgRef = useRef<SVGRectElement | null>(null);
  const fabRef = useRef<SVGRectElement | null>(null);
  /**
   * id → 该 pid 的 DOM 副本数组（每副本 = 毛版 polygon + 4 层工艺节点），manifest 到达后填充。
   * 长度 = piece.demand（缺省 1）。demand>1 时 solver 给同一 pid 发 N 条 placed_items（同 id、
   * 不同 translation），必须 N 个独立 DOM 副本各承一处 placement —— 否则 N 条共用同一 polygon、
   * 后覆盖前，只剩 1/N 可见（视觉稀疏但密度数字正确，极隐蔽）。
   */
  const piecesRef = useRef<Map<string, PieceEntry[]>>(new Map());
  /**
   * 当前已建骨架对应的 manifest 引用（重解检测）。run.manifest 引用变化 → 全量重建骨架 +
   * 副本池；同一引用（含 React 18 StrictMode 双 mount）保持幂等不重建。
   *
   * 旧实现用 ``!flipRef.current`` 单次保护 —— 重解（同 seed 复用 NestSVG）时 run.manifest 已是
   * 新对象，但 flipRef 仍指旧 DOM → copies 池不重建 → demand 变化后多副本 placement 被丢弃
   * （只显 1/N，视觉缺片但密度数正确，极隐蔽）。改以 manifest 身份变化为重建信号根除之。
   */
  const manifestRef = useRef<ManifestMsg | null>(null);

  // 订阅 renderTick —— bump 触发 effect 重跑（imperative 更新 DOM）。
  const renderTick = useAppStore((s) => s.renderTick);
  // US-006：订阅 seekTime，拖动时立即切到 frameAtTime(run, seekTime)。
  const seekTime = useAppStore((s) => s.seekTime);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    // 1) manifest 到达 / 变化（新 run、重解）→ 建立（或重建）骨架（bg + 用布矩形 + 翻转组 +
    //    N × 5 层 polygon/polyline/line）+ demand 副本池。
    //    以 manifest 引用变化为重建信号（非旧 ``!flipRef.current`` 单次保护）：重解时 run.manifest
    //    已是新对象，旧实现因 flipRef 仍指旧 DOM 而跳过重建 → copies 池停留旧 demand → 多副本
    //    placement 被丢弃（只显 1/N，视觉缺片但密度数正确，极隐蔽）。
    //    幂等：同一 manifest 引用（含 React 18 StrictMode 双 mount）不重建。
    if (run.manifest && run.manifest !== manifestRef.current) {
      // 重解（旧骨架仍在）→ 先拆除 bg/fab/flipGroup + 清空副本池，再重建，避免残留 / 副本数陈旧。
      if (flipRef.current) {
        bgRef.current?.remove();
        fabRef.current?.remove();
        flipRef.current.remove();
        bgRef.current = null;
        fabRef.current = null;
        flipRef.current = null;
        piecesRef.current.clear();
      }
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
        // demand 副本：demand>1 时 solver 给同一 pid 发 N 条 placement（同 id 不同 translation），
        // 需 N 个独立 DOM 副本各承一处；缺省 demand=1（旧 manifest 无此字段 → 单副本，行为不变）。
        const demand = Math.max(1, Math.floor(p.demand ?? 1));
        const copies: PieceEntry[] = [];
        for (let k = 0; k < demand; k++) copies.push(createPieceEntry(p, g));
        piecesRef.current.set(p.id, copies);
      }

      // US-006 AC#4..#6：flipGroup 上事件委托 mousemove + mouseleave。
      // 与旧 vanilla 实现 setupHover 等价（旧版绑 svg，AC 要求 flipGroup；多边形均在 flipGroup 内，
      // 行为一致：mousemove 落在 polygon → 显 tooltip + 高亮；其他 / mouseleave → 隐 + 移除高亮）。
      // US-024：4 层工艺节点 pointerEvents='none'，事件委托只触发于毛版 polygon（dataset.label 必有）。
      g.addEventListener('mousemove', handleHover);
      g.addEventListener('mouseleave', handleHoverEnd);

      manifestRef.current = run.manifest;
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
    // viewBox 用历史最大 width 作稳定锚（避免收缩抖动），与旧 vanilla 实现 一致。
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

    // placed → 显示 + 写 points；未 placed → display:none。
    // demand>1 时同一 pid 在 placed_items 出现 N 次（每副本一条）。piecesRef[pid] 是该 pid 的
    // DOM 副本池（长度 = demand）；按「出现序」把第 k 次出现渲染到副本池第 k 个节点 ——
    // 否则 N 条 placement 共用同一 polygon、后覆盖前，只剩 1/N 可见。
    const reached = new Map<string, number>();   // pid → 本帧已渲染副本数
    for (const it of f.placed_items) {
      const copies = piecesRef.current.get(it.id);
      if (!copies || copies.length === 0) continue;
      const k = reached.get(it.id) ?? 0;
      reached.set(it.id, k + 1);
      if (k >= copies.length) continue;          // 防御：solver 放置数 > demand（不应发生）
      const entry = copies[k];
      const rot = it.rotation;
      const tr = it.translation;
      // layer1 毛版 polygon
      entry.el.setAttribute('points', pointsStr(entry.piece.polygon, rot, tr));
      entry.el.style.display = '';
      // US-024 layer14 净版 polygon
      if (entry.netEl && entry.piece.net_polygon) {
        entry.netEl.setAttribute('points', pointsStr(entry.piece.net_polygon, rot, tr));
        entry.netEl.style.display = '';
      }
      // US-024 layer8 内部线 polyline 列表
      const internalLines = entry.piece.internal_lines ?? [];
      for (let i = 0; i < entry.internalEls.length; i++) {
        const lineEl = entry.internalEls[i];
        const line = internalLines[i];
        if (!line) continue;
        lineEl.setAttribute('points', pointsStr(line, rot, tr));
        lineEl.style.display = '';
      }
      // US-024 layer4 刺口 line（沿法线 NOTCH_LEN_MM/2 两端）
      const notches = entry.piece.notches ?? [];
      const half = NOTCH_LEN_MM / 2;
      for (let i = 0; i < entry.notchEls.length; i++) {
        const notchEl = entry.notchEls[i];
        const n: Notch | undefined = notches[i];
        if (!n) continue;
        // 毛版 polygon 用 pointsStr 整体旋转；notch 端点需独立旋转 + 平移（双端点不一致平移）
        // 简化：把 (x±nx*half, y±ny*half) 视作两个点，各按 rot+tr 变换
        const [px, py, nx, ny] = n;
        const a = transformPt([px - nx * half, py - ny * half], rot, tr);
        const b = transformPt([px + nx * half, py + ny * half], rot, tr);
        notchEl.setAttribute('x1', String(a[0]));
        notchEl.setAttribute('y1', String(a[1]));
        notchEl.setAttribute('x2', String(b[0]));
        notchEl.setAttribute('y2', String(b[1]));
        notchEl.style.display = '';
      }
      // US-024 layer7 布纹线 line
      if (entry.grainEl && entry.piece.grain_line) {
        const [x1, y1, x2, y2] = entry.piece.grain_line;
        const a = transformPt([x1, y1], rot, tr);
        const b = transformPt([x2, y2], rot, tr);
        entry.grainEl.setAttribute('x1', String(a[0]));
        entry.grainEl.setAttribute('y1', String(a[1]));
        entry.grainEl.setAttribute('x2', String(b[0]));
        entry.grainEl.setAttribute('y2', String(b[1]));
        entry.grainEl.style.display = '';
      }
    }
    // 未 reached 的副本（整 pid 未 placed、或 demand 内仅部分出现）→ 隐藏全部 5 层。
    for (const [id, copies] of piecesRef.current) {
      const used = reached.get(id) ?? 0;
      for (let k = used; k < copies.length; k++) {
        const entry = copies[k];
        entry.el.style.display = 'none';
        if (entry.netEl) entry.netEl.style.display = 'none';
        for (const ie of entry.internalEls) ie.style.display = 'none';
        for (const ne of entry.notchEls) ne.style.display = 'none';
        if (entry.grainEl) entry.grainEl.style.display = 'none';
      }
    }
  }, [renderTick, seekTime, run]);

  return <svg ref={svgRef} xmlns={SVGNS} />;
}

/**
 * 单点 rotation + translation 变换（与 lib/geometry.ts pointsStr 同公式，输出 [x,y]）。
 *
 * 用于刺口 line 端点 / 布纹线端点 —— pointsStr 一次性输出整段字符串适用于多边形/polyline；
 * 单点变换用于 line 元素的 x1/y1/x2/y2 独立属性写入。
 */
function transformPt(pt: [number, number], rot: number, tr: [number, number]): [number, number] {
  const r = (rot * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  const x = pt[0];
  const y = pt[1];
  // r2 截断与 lib/geometry.ts r2 一致（pointsStr 输出字节级一致性的保证）
  const rx = Math.round((x * c - y * s + tr[0]) * 100) / 100;
  const ry = Math.round((x * s + y * c + tr[1]) * 100) / 100;
  return [rx, ry];
}

/**
 * mousemove 事件委托处理器（绑在 flipGroup 上）。
 *
 * 与旧 vanilla 实现 setupHover 内 mousemove 一致：
 *   - poly = e.target.closest('polygon')（事件委托，e.target 可能是 polygon 本身或其子节点）
 *   - poly && poly.dataset.label → setHovered + showTooltip（`g03 · 码28` + 面积 cm²；
 *     US-003 起命中判定走 dataset.label —— v2 manifest 唯一标识 = 裁片 g 码）
 *   - 否则 → clearHovered + hideTooltip
 *
 * 面积换算：dataset.area 单位 mm²，÷100 → cm²（与旧 vanilla 实现 `parseFloat/100` 一致）。
 */
function handleHover(e: MouseEvent): void {
  const target = e.target as Element | null;
  const poly = target?.closest('polygon') as SVGPolygonElement | null;
  if (poly && poly.dataset.label) {
    setHovered(poly);
    const area_cm2 = (parseFloat(poly.dataset.area || '0') / 100).toFixed(1);
    showTooltip(
      e.clientX,
      e.clientY,
      `${poly.dataset.label} · 码${poly.dataset.size}<br>面积 ${area_cm2} cm²`,
    );
  } else {
    clearHovered();
    hideTooltip();
  }
}

/** mouseleave 处理器：移除高亮 + 隐 tooltip（与旧 vanilla 实现 setupHover mouseleave 一致）。 */
function handleHoverEnd(): void {
  clearHovered();
  hideTooltip();
}

/** 暴露给单测 / 调试用（提取翻转后的 polygon，仅作内部辅助）。 */
export function _rotatedPolygon(poly: Polygon, rot: number, tr: [number, number]): string {
  return pointsStr(poly, rot, tr);
}
