// ConvergenceCurve —— 多 run 叠加收敛曲线（命令式 DOM，逃逸 React reconciliation）。
//
// 与旧 vanilla 实现 drawCurve() 等价：
//   1. 始终绘制 90% 生死线（虚线 + 「90% 生死线」文字）。
//   2. 单 seed（runs.length === 1）：散点按 PHASE_COLORS[phase] 着色 + cumulative-best 折线（默认蓝）。
//   3. 多 seed（runs.length > 1）：每 run 一条 SEED_COLORS[i] 折线 + 末点 circle + seed 标签。
//   4. 图例：多 seed → seed 列表（每行一个色块 + 「seed N」）；单 seed → phase 列表（exploring/compressing/final）。
//   5. 帧数 > 400 时按 step = max(1, floor(n/400)) 采样，末帧强制纳入（与旧 vanilla 实现 一致）。
//
// 命令式：React 仅渲染空骨架 `<svg ref/>`；子节点通过 svg.innerHTML = ... 写入（与旧 vanilla 实现 一致），
// 不参与 React 每帧 diff。节流：订阅 renderTick —— bump 时 effect 重跑 → 重读 runRegistry → 重写 innerHTML。

import { useEffect, useRef } from 'react';
import { useAppStore } from '../../store/appStore';
import { runRegistry } from '../../store/runRegistry';
import { PHASE_COLORS, SEED_COLORS } from '../../constants/colors';
import { r2 } from '../../lib/geometry';
import type { FrameMsg } from '../../types/ws';

/** 90% 生死线（行业 / 版师口径，原面积密度）。 */
const DEATH_LINE_PCT = 90;
/** 单 run 采样上限（与旧 vanilla 实现 drawCurve 字面量一致）。 */
const MAX_POINTS = 400;
/** 收敛曲线画布尺寸 / 内边距（与旧 vanilla 实现 drawCurve 字面量一致）。 */
const W = 1000;
const H = 220;
const PAD_L = 46;
const PAD_R = 14;
const PAD_T = 12;
const PAD_B = 26;

/**
 * 帧采样（旧 vanilla 实现 drawCurve 内部逻辑）：
 *   step = max(1, floor(n/400))；i=0,step,2*step,...；末帧强制纳入。
 */
export function sampleFrames(frames: readonly FrameMsg[]): FrameMsg[] {
  if (frames.length === 0) return [];
  const step = Math.max(1, Math.floor(frames.length / MAX_POINTS));
  const pts: FrameMsg[] = [];
  for (let i = 0; i < frames.length; i += step) pts.push(frames[i]);
  const last = frames[frames.length - 1];
  if (pts[pts.length - 1] !== last) pts.push(last);
  return pts;
}

/** 按 phase 取色（PHASE_COLORS 缺失 → 灰色兜底，与旧 vanilla 实现 `|| '#888'` 一致）。 */
function phaseColor(phase: string): string {
  return PHASE_COLORS[phase as keyof typeof PHASE_COLORS] || '#888';
}

/**
 * 渲染收敛曲线到 svg（命令式 innerHTML；与旧 vanilla 实现 drawCurve 输出字节级一致）。
 *
 * 早返回：runs 为空 / 全部无帧时不绘制（保留 svg 现有内容；旧 vanilla 实现 同行为）。
 */
export function renderCurveInto(svg: SVGSVGElement): void {
  const runs = runRegistry.list();
  if (runs.length === 0 || runs.every((r) => r.frames.length === 0)) return;
  const multi = runs.length > 1;

  // 坐标域：x = elapsed(s)，y = density*100(%)。
  let maxT = 1;
  let yMin = Infinity;
  let yMax = -Infinity;
  for (const r of runs) {
    for (const f of r.frames) {
      if (f.elapsed > maxT) maxT = f.elapsed;
      const d = f.density * 100;
      if (d < yMin) yMin = d;
      if (d > yMax) yMax = d;
    }
  }
  yMin = Math.max(0, yMin - 3);
  yMax = Math.max(93, yMax + 2);
  const sx = (t: number) => PAD_L + (t / maxT) * (W - PAD_L - PAD_R);
  const sy = (d: number) => H - PAD_B - ((d - yMin) / (yMax - yMin)) * (H - PAD_T - PAD_B);

  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'xMinYMid meet');

  let out = '';
  // 90% 生死线（始终绘制）
  out += `<line x1="${PAD_L}" y1="${sy(DEATH_LINE_PCT)}" x2="${W - PAD_R}" y2="${sy(DEATH_LINE_PCT)}" stroke="#444" stroke-dasharray="5 4"/>`;
  out += `<text x="${PAD_L + 4}" y="${sy(DEATH_LINE_PCT) - 4}" font-size="11" fill="#444">90% 生死线</text>`;

  runs.forEach((r, ri) => {
    if (r.frames.length === 0) return;
    const col = multi ? SEED_COLORS[ri % SEED_COLORS.length] : '#1f77b4';
    const pts = sampleFrames(r.frames);
    const last = r.frames[r.frames.length - 1];

    if (!multi) {
      // 单 seed：散点按 phase 着色
      for (const f of pts) {
        out += `<circle cx="${sx(f.elapsed)}" cy="${sy(f.density * 100)}" r="2" fill="${phaseColor(f.phase)}" opacity="0.55"/>`;
      }
    }
    // cumulative-best 折线（runs 都画，单 seed 蓝 / 多 seed 各色）
    let best = -1;
    let path = '';
    for (const f of pts) {
      best = Math.max(best, f.density * 100);
      path += (path ? 'L' : 'M') + r2(sx(f.elapsed)) + ' ' + r2(sy(best));
    }
    out += `<path d="${path}" fill="none" stroke="${col}" stroke-width="2"/>`;
    // 末点 circle（始终画）
    out += `<circle cx="${sx(last.elapsed)}" cy="${sy(last.density * 100)}" r="3" fill="${col}"/>`;
    // 多 seed：末点旁标 s${seed}
    if (multi) {
      out += `<text x="${sx(last.elapsed) - 5}" y="${sy(last.density * 100) - 6}" font-size="10" fill="${col}" text-anchor="end">s${r.seed}</text>`;
    }
  });

  // 图例（多 seed → seed 列表；单 seed → phase 列表）
  out += '<g class="legend">';
  if (multi) {
    runs.forEach((r, ri) => {
      const col = SEED_COLORS[ri % SEED_COLORS.length];
      const y = PAD_T + ri * 15 + 4;
      out += `<rect x="${PAD_L + 8}" y="${y - 3}" width="12" height="3" fill="${col}"/>`;
      out += `<text x="${PAD_L + 24}" y="${y}" font-size="10" fill="#ccd">seed ${r.seed}</text>`;
    });
  } else {
    let y = PAD_T + 8;
    for (const [ph, col] of Object.entries(PHASE_COLORS)) {
      out += `<circle cx="${PAD_L + 14}" cy="${y}" r="3" fill="${col}" opacity="0.75"/>`;
      out += `<text x="${PAD_L + 22}" y="${y + 3}" font-size="10" fill="#ccd">${ph}</text>`;
      y += 15;
    }
  }
  out += '</g>';

  // x 轴两端时间标签
  out += `<text x="${PAD_L}" y="${H - 8}" font-size="10" fill="#888">0s</text>`;
  out += `<text x="${W - PAD_R - 34}" y="${H - 8}" font-size="10" fill="#888">${maxT.toFixed(0)}s</text>`;

  svg.innerHTML = out;
}

export function ConvergenceCurve() {
  // React 只持有空骨架 `<svg>`；子节点全部 imperative innerHTML 写入。
  const svgRef = useRef<SVGSVGElement>(null);
  // 订阅 renderTick —— bump 触发 effect 重跑（重写 innerHTML）。
  const renderTick = useAppStore((s) => s.renderTick);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    renderCurveInto(svg);
  }, [renderTick]);

  return <svg id="curve" ref={svgRef} xmlns="http://www.w3.org/2000/svg" />;
}
