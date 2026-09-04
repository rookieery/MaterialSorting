// EditCanvas —— 编辑排料弹窗中心画布（US-002：全量渲染 + 缩放平移查看；
// 拖动/旋转/重合指标在 US-003 叠加）。
//
// 命令式范式与 NestSVG 同款（AGENTS.md 关键约定 #2/#3）：
//   - React 只渲染骨架（svg + 视图工具按钮）；5 层裁片节点 / bg / fab / 翻转组全部
//     document.createElementNS + setAttribute，逃逸 React reconciliation；
//   - 翻转组 transform = translate(0 gate) scale(1 -1)（sparrow Y 向上 → SVG Y 向下，
//     与 PNG / R12-DXF / 主视图一致），setAttribute 写（不走 JSX prop）；
//   - 5 层节点构建复用 nests/pieceDom createPieceEntry —— 与主视图同构同观感
//     （尺码色 + 工艺色逐属性一致）；
//   - 多副本按「出现序」：working 数组下标 = placed_items 数组下标（editStore 寻址
//     口径），同 pid 第 k 次出现渲染到第 k 个 DOM 副本（与 NestSVG.tsx reached
//     计数器同语义）—— 编辑画布每 working 下标恰建一份节点，天然满足。
//
// 与 NestSVG 的差异（编辑画布特有）：
//   - 数据源 = editStore.working（编辑草稿），非 run.frames / renderTick —— working
//     引用变化（setWorkingItem / reset）即重渲染；
//   - viewBox 可变（缩放平移）：滚轮以指针为锚缩放（clientToWorld CTM 矩阵通路，
//     涵盖 letterbox + Y 翻转）、按住空白处拖动平移、重置视图/± 按钮；bg 跟随
//     viewBox（无限画布感），fab（用布矩形）世界锚定（宽 = computeLayoutStats 料长，
//     与状态条同一真相源）；
//   - 毛板模式（mode='rough'）：4 层工艺节点 display:none，毛版 polygon + 尺码色保留。

import { useEffect, useRef } from 'react';
import { clientToWorld } from '../../lib/editGeometry';
import { pointsStr } from '../../lib/geometry';
import { computeLayoutStats, useEditStore } from '../../store/editStore';
import { createPieceEntry, SVGNS, type PieceEntry } from '../nests/pieceDom';
import { NOTCH_LEN_MM } from '../../constants/colors';
import type { Notch, Pt } from '../../types/piece';
import type { ManifestMsg } from '../../types/ws';

/** 画布形态：'full' 完整版（5 层全量）/ 'rough' 毛板（仅毛版轮廓 + 尺码色）。 */
export type EditViewMode = 'full' | 'rough';

/** 滚轮 / ± 按钮每档缩放倍率（deltaY<0 / ＋ 放大 → 宽 × 1/STEP）。 */
const ZOOM_STEP = 1.25;
/** viewBox 宽度界（mm）：最深 20mm（刀口级细节）→ 最广 = 当前视图宽 × 40。 */
const MIN_VB_W = 20;
const MAX_VB_SCALE = 40;

/** viewBox（SVG 用户空间 = 翻转组变换之外的 viewBox 坐标系）。 */
interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface EditCanvasProps {
  /** 渲染形态（完整版/毛板，即时切换可恢复）。 */
  mode: EditViewMode;
}

export function EditCanvas({ mode }: EditCanvasProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const flipRef = useRef<SVGGElement | null>(null);
  const bgRef = useRef<SVGRectElement | null>(null);
  /** 5 层节点池（下标对齐 working；manifest 缺片防御 null 占位保下标稳定）。 */
  const entriesRef = useRef<(PieceEntry | null)[]>([]);
  const manifestRef = useRef<ManifestMsg | null>(null);
  /** working 的 pid 序列指纹（manifest 同引用但 working 结构变化时重建节点池）。 */
  const pidSeqRef = useRef<string>('');
  const vbRef = useRef<ViewBox | null>(null);
  /** 初始视图（重置视图锚点）。 */
  const vb0Ref = useRef<ViewBox | null>(null);
  /** 平移拖拽态（pointerId + 起点客户端坐标 + 起点 viewBox 快照）。 */
  const panRef = useRef<{ pointerId: number; startX: number; startY: number; vb: ViewBox } | null>(null);

  const run = useEditStore((s) => s.run);
  const working = useEditStore((s) => s.working);

  /**
   * 主渲染 effect：manifest/pid 序列变化 → 重建骨架（bg + fab + 翻转组 + N×5 层）；
   * working / mode 变化 → setAttribute 更新（不重建 DOM，与 NestSVG 性能保护同款）。
   */
  useEffect(() => {
    const svg = svgRef.current;
    const manifest = run?.manifest ?? null;
    if (!svg || !manifest || working.length === 0) return;

    const pidSeq = working.map((it) => it.id).join(' ');
    if (manifest !== manifestRef.current || pidSeq !== pidSeqRef.current) {
      // 重解 / 布局结构变化 → 拆旧骨架重建（避免残留 / 副本数陈旧）。
      if (flipRef.current) {
        bgRef.current?.remove();
        flipRef.current.remove();
        bgRef.current = null;
        flipRef.current = null;
        entriesRef.current = [];
      }

      const bg = document.createElementNS(SVGNS, 'rect');
      bg.setAttribute('fill', '#eef0f3');

      const fab = document.createElementNS(SVGNS, 'rect');
      fab.setAttribute('fill', '#fff');
      fab.setAttribute('fill-opacity', '0.55');
      fab.setAttribute('stroke', '#8a8a8a');
      fab.setAttribute('stroke-dasharray', '8 5');
      fab.setAttribute('stroke-width', '1.5');

      // 翻转组：translate(0 gate) scale(1 -1) —— sparrow Y 向上 → SVG Y 向下。
      const g = document.createElementNS(SVGNS, 'g');
      g.setAttribute('transform', `translate(0 ${manifest.gate_mm}) scale(1 -1)`);

      svg.appendChild(bg);
      svg.appendChild(fab);
      svg.appendChild(g);
      bgRef.current = bg;
      flipRef.current = g;

      // 5 层节点池：每 working 下标恰一份（k 次出现同 pid = 第 k 副本，出现序语义）。
      const byId = new Map(manifest.pieces.map((p) => [p.id, p]));
      entriesRef.current = working.map((it) => {
        const info = byId.get(it.id);
        return info ? createPieceEntry(info, g) : null;
      });

      manifestRef.current = manifest;
      pidSeqRef.current = pidSeq;
      vbRef.current = null; // 骨架重建 → 视图回初始
    }

    // 统计与视图（fab 宽 = 包络料长，与状态条同一真相源 computeLayoutStats）。
    const stats = computeLayoutStats(working, manifest);
    const gate = manifest.gate_mm;
    if (!vbRef.current) {
      const vb0: ViewBox = { x: 0, y: 0, w: Math.max(1, stats.widthMm), h: gate };
      vbRef.current = vb0;
      vb0Ref.current = vb0;
    }
    applyView(svg, vbRef.current, stats.widthMm, gate);

    // 5 层按 working 更新（mode 决定 4 层工艺显隐；毛版恒显）。
    working.forEach((it, i) => {
      const entry = entriesRef.current[i];
      if (!entry || entry.piece.id !== it.id) return; // 防御：池与 working 错位
      applyPlacement(entry, it.rotation, it.translation, mode);
    });
  }, [run, working, mode]);

  /**
   * 滚轮缩放（native listener + passive:false —— React 合成 wheel 挂根节点为
   * passive，preventDefault 会告警失效）。指针锚：clientToWorld（CTM 矩阵通路）
   * 取指针下世界点，缩放前后保持不动；CTM 不可得（未渲染/测试未 mock）→ 退化为
   * 视图中心锚。
   */
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent): void => {
      e.preventDefault();
      const vb = vbRef.current;
      const flip = flipRef.current;
      if (!vb) return;
      // 锚点取 **用户空间**（viewBox 坐标系，翻转组变换之前）—— clientToWorld 返回
      // 世界坐标（Y 向上），须经翻转组 translate(0 gate) scale(1 -1) 换算：
      // userX = worldX；userY = gate − worldY。直接拿 worldY 当锚会把缩放中心
      // 上下镜像（Y 翻转坐标系陷阱，单测锁死）。
      let anchor: Pt;
      const world = flip ? clientToWorld(svg, flip, e.clientX, e.clientY) : null;
      if (world) {
        const gate = manifestRef.current?.gate_mm ?? 0;
        anchor = [world[0], gate - world[1]];
      } else {
        anchor = [vb.x + vb.w / 2, vb.y + vb.h / 2];
      }
      zoomBy(svg, vbRef, e.deltaY > 0 ? ZOOM_STEP : 1 / ZOOM_STEP, anchor);
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, []);

  /**
   * 空白处拖动平移：pointerdown 落在裁片 polygon 上（毛版 = 未来 US-003 拖动目标；
   * 4 层工艺节点 pointer-events:none 不会成为 target）→ 不起平移；空白（svg 自身 /
   * bg / fab）→ setPointerCapture 后拖动平移 viewBox。
   */
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onPointerDown = (e: PointerEvent): void => {
      const target = e.target as Element | null;
      if (target?.closest?.('polygon')) return; // 裁片上不起平移（US-003 拖动接管）
      const vb = vbRef.current;
      if (!vb) return;
      try {
        svg.setPointerCapture?.(e.pointerId); // jsdom 未实现/未知指针 id 抛错 → 忽略
      } catch {
        /* 捕获失败不影响平移 —— move/up 监听本就挂 svg 自身 */
      }
      panRef.current = { pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, vb: { ...vb } };
      svg.style.cursor = 'grabbing';
    };
    const onPointerMove = (e: PointerEvent): void => {
      const p = panRef.current;
      if (!p || e.pointerId !== p.pointerId) return;
      const s = viewScale(svg, p.vb);
      if (s <= 0) return; // 未布局（零尺寸 rect）→ 不平移
      const cur = vbRef.current;
      if (!cur) return;
      // 屏幕位移 → 用户空间位移（s = px/mm；meet letterbox 取 min 比）。
      // 拖动 = 内容跟随指针：viewBox 原点反向移动（x/y 同式；翻转在组内不受影响）。
      vbRef.current = {
        ...cur,
        x: p.vb.x - (e.clientX - p.startX) / s,
        y: p.vb.y - (e.clientY - p.startY) / s,
      };
      writeViewBox(svg, vbRef.current);
    };
    const endPan = (e: PointerEvent): void => {
      if (panRef.current && e.pointerId === panRef.current.pointerId) {
        panRef.current = null;
        svg.style.cursor = '';
      }
    };
    svg.addEventListener('pointerdown', onPointerDown);
    svg.addEventListener('pointermove', onPointerMove);
    svg.addEventListener('pointerup', endPan);
    svg.addEventListener('pointercancel', endPan);
    return () => {
      svg.removeEventListener('pointerdown', onPointerDown);
      svg.removeEventListener('pointermove', onPointerMove);
      svg.removeEventListener('pointerup', endPan);
      svg.removeEventListener('pointercancel', endPan);
    };
  }, []);

  /** 视图工具按钮（React 受控；画布右上留给 US-003 指标面板，工具置左上）。 */
  function handleZoomIn(): void {
    const vb = vbRef.current;
    const svg = svgRef.current;
    if (!vb || !svg) return;
    zoomBy(svg, vbRef, 1 / ZOOM_STEP, [vb.x + vb.w / 2, vb.y + vb.h / 2]);
  }

  function handleZoomOut(): void {
    const vb = vbRef.current;
    const svg = svgRef.current;
    if (!vb || !svg) return;
    zoomBy(svg, vbRef, ZOOM_STEP, [vb.x + vb.w / 2, vb.y + vb.h / 2]);
  }

  function handleResetView(): void {
    const svg = svgRef.current;
    if (!svg || !vb0Ref.current) return;
    vbRef.current = { ...vb0Ref.current };
    writeViewBox(svg, vbRef.current);
  }

  return (
    <div className="edit-layout-canvas-wrap">
      {/* 骨架 svg：preserveAspectRatio 静态属性走 JSX；viewBox/子节点全部 imperative。 */}
      <svg ref={svgRef} xmlns={SVGNS} className="edit-layout-svg" preserveAspectRatio="xMinYMid meet" />
      <div className="edit-layout-canvas-tools">
        <button
          type="button"
          className="edit-layout-tool"
          onClick={handleZoomIn}
          title="放大"
          aria-label="放大"
          data-testid="edit-zoom-in"
        >
          ＋
        </button>
        <button
          type="button"
          className="edit-layout-tool"
          onClick={handleZoomOut}
          title="缩小"
          aria-label="缩小"
          data-testid="edit-zoom-out"
        >
          －
        </button>
        <button
          type="button"
          className="edit-layout-tool edit-layout-tool-reset"
          onClick={handleResetView}
          data-testid="edit-zoom-reset"
        >
          重置视图
        </button>
      </div>
    </div>
  );
}

/**
 * 以 anchor（用户空间）为锚把 viewBox 宽缩放 ratio 倍（含 MIN/MAX 钳制），写回
 * vbRef + svg.viewBox + bg（bg 跟随 viewBox 铺满可视区；fab 世界锚定不动）。
 *
 * 锚点不动式：新原点 = anchor − (anchor − 原点) × k（k = 新宽/旧宽；meet 等比 →
 * 高同 k，letterbox 偏移在等比缩放下不变，锚点屏幕位置自然保持）。
 * **必须回写 vbRef**：滚轮/按钮连续缩放都从 vbRef 取当前视图 —— 漏写回会把第二档
 * 起的重算锚在陈旧视图上（缩放一步后再无效果）。
 */
function zoomBy(
  svg: SVGSVGElement,
  vbRef: { current: ViewBox | null },
  ratio: number,
  anchor: Pt,
): void {
  const vb = vbRef.current;
  if (!vb) return;
  const nw = Math.max(MIN_VB_W, Math.min(vb.w * MAX_VB_SCALE, vb.w * ratio));
  const k = nw / vb.w;
  const nvb: ViewBox = {
    x: anchor[0] - (anchor[0] - vb.x) * k,
    y: anchor[1] - (anchor[1] - vb.y) * k,
    w: nw,
    h: vb.h * k,
  };
  vbRef.current = nvb;
  writeViewBox(svg, nvb);
}

/**
 * viewBox attr + bg 写入（平移/缩放/重置路径 —— fab 世界锚定不动）。
 *
 * 显示值 r6 截断（1e-6 mm = 纳米级，视觉无损）：CTM 反变换（clientToWorld）带
 * float 噪声（~1e-13），不截断会把 viewBox attr 写成 "88.00000000000003" 级长串；
 * 数学连续性不受影响（vbRef 保留全精度，仅 attr 显示截断）。
 */
function writeViewBox(svg: SVGSVGElement, vb: ViewBox): void {
  svg.setAttribute('viewBox', `${r6(vb.x)} ${r6(vb.y)} ${r6(vb.w)} ${r6(vb.h)}`);
  const rects = svg.querySelectorAll(':scope > rect');
  if (rects.length >= 1) {
    const bg = rects[0] as SVGRectElement;
    bg.setAttribute('x', String(r6(vb.x)));
    bg.setAttribute('y', String(r6(vb.y)));
    bg.setAttribute('width', String(r6(vb.w)));
    bg.setAttribute('height', String(r6(vb.h)));
  }
}

/** 1e-6 mm 截断（String(−0)='0' 自动归一化负零）。 */
function r6(v: number): number {
  return Math.round(v * 1e6) / 1e6;
}

/** viewBox + bg + fab 全量写（主渲染 effect 用；fab = 用布矩形，世界锚定）。 */
function applyView(svg: SVGSVGElement, vb: ViewBox, fabW: number, gate: number): void {
  writeViewBox(svg, vb);
  const rects = svg.querySelectorAll(':scope > rect');
  if (rects.length >= 2) {
    const fab = rects[1] as SVGRectElement;
    fab.setAttribute('x', '0');
    fab.setAttribute('y', '0');
    fab.setAttribute('width', String(fabW));
    fab.setAttribute('height', String(gate));
  }
}

/**
 * px→mm 比尺（preserveAspectRatio="xMinYMid meet" → min(宽比, 高比)）。
 * 平移只用比尺（letterbox 偏移在位移差分中抵消），无需 CTM；rect 零尺寸（未布局）→ 0。
 */
function viewScale(svg: SVGSVGElement, vb: ViewBox): number {
  const r = svg.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0 || vb.w <= 0 || vb.h <= 0) return 0;
  return Math.min(r.width / vb.w, r.height / vb.h);
}

/**
 * 单片 5 层按 rot/tr 更新（与 NestSVG frame 渲染逐属性同款；mode 决定 4 层工艺显隐）。
 */
function applyPlacement(entry: PieceEntry, rot: number, tr: Pt, mode: EditViewMode): void {
  const showCraft = mode === 'full';
  // layer1 毛版 polygon（恒显 —— 毛板模式唯一可见层）
  entry.el.setAttribute('points', pointsStr(entry.piece.polygon, rot, tr));
  entry.el.style.display = '';
  // layer14 净版 polygon
  if (entry.netEl && entry.piece.net_polygon) {
    entry.netEl.setAttribute('points', pointsStr(entry.piece.net_polygon, rot, tr));
    entry.netEl.style.display = showCraft ? '' : 'none';
  }
  // layer8 内部线 polyline 列表
  const internalLines = entry.piece.internal_lines ?? [];
  for (let i = 0; i < entry.internalEls.length; i++) {
    const lineEl = entry.internalEls[i];
    const line = internalLines[i];
    if (!line) continue;
    lineEl.setAttribute('points', pointsStr(line, rot, tr));
    lineEl.style.display = showCraft ? '' : 'none';
  }
  // layer4 刺口 line（沿法线 NOTCH_LEN_MM/2 两端，端点独立变换）
  const notches = entry.piece.notches ?? [];
  const half = NOTCH_LEN_MM / 2;
  for (let i = 0; i < entry.notchEls.length; i++) {
    const notchEl = entry.notchEls[i];
    const n: Notch | undefined = notches[i];
    if (!n) continue;
    const [px, py, nx, ny] = n;
    const a = transformPt([px - nx * half, py - ny * half], rot, tr);
    const b = transformPt([px + nx * half, py + ny * half], rot, tr);
    notchEl.setAttribute('x1', String(a[0]));
    notchEl.setAttribute('y1', String(a[1]));
    notchEl.setAttribute('x2', String(b[0]));
    notchEl.setAttribute('y2', String(b[1]));
    notchEl.style.display = showCraft ? '' : 'none';
  }
  // layer7 布纹线 line
  if (entry.grainEl && entry.piece.grain_line) {
    const [x1, y1, x2, y2] = entry.piece.grain_line;
    const a = transformPt([x1, y1], rot, tr);
    const b = transformPt([x2, y2], rot, tr);
    entry.grainEl.setAttribute('x1', String(a[0]));
    entry.grainEl.setAttribute('y1', String(a[1]));
    entry.grainEl.setAttribute('x2', String(b[0]));
    entry.grainEl.setAttribute('y2', String(b[1]));
    entry.grainEl.style.display = showCraft ? '' : 'none';
  }
}

/**
 * 单点 rotation + translation 变换（与 NestSVG.transformPt / lib/geometry.ts pointsStr
 * 同公式 + r2 截断 —— line 元素 x1/y1/x2/y2 独立属性写入需要单点版）。
 */
function transformPt(pt: [number, number], rot: number, tr: [number, number]): [number, number] {
  const r = (rot * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  const x = pt[0];
  const y = pt[1];
  const rx = Math.round((x * c - y * s + tr[0]) * 100) / 100;
  const ry = Math.round((x * s + y * c + tr[1]) * 100) / 100;
  return [rx, ry];
}
