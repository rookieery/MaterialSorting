// EditCanvas —— 编辑排料弹窗中心画布（US-002 全量渲染 + 缩放平移查看；
// US-003 拖动/旋转 + 重合指标实时面板）。
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
//     涵盖 letterbox + Y 翻转）、按住空白处拖动平移、「全览」按钮复位到初始适配视图；
//     bg 跟随 viewBox（无限画布感），fab（用布矩形）世界锚定（宽 = computeLayoutStats
//     料长，与状态条同一真相源）；
//   - 毛板模式（mode='rough'）：4 层工艺节点 display:none，毛版 polygon + 尺码色保留。
//
// 2026-09-05 UI 优化（用户验收后迭代）：± 放缩按钮删除（滚轮唯一缩放入口）；
// 「重置视图」改名「全览」（只复位缩放/平移，不还原编辑草稿 —— 与主面板「重置」
// = editStore.reset() 回算法基线的语义彻底区分）；形态 select 自 footer 移入左上
// 工具区（state 仍在 EditLayoutModal，经 onModeChange 受控）；右下新增「操作指南」
// 卡片（.edit-guide，同 .edit-metrics 悬浮卡模式 pointer-events:none 不挡画布）。
// 同日二轮 UI 迭代：左上工具区竖排改横排（全览/形态/智能微调一行）；微调对比卡自
// 右下卡栈迁画布左下（.edit-br-stack 拆除、.edit-guide 锚点下放回自身右下）—— 右下
// 双卡叠置挡排料尾部主视图，迁后四角各一元素（左上工具/右上指标/左下对比卡/右下
// 指南）与指南卡水平对称；testid/DOM containment 不变，单测与冒烟零改动。
// 同日三轮：对比卡口径脚注（物理毛版 vs 画布红字腐蚀口径）自卡内可见行移除（用户
// 定案太占空间）—— 解释锚点收进「智能微调」按钮 title 悬浮（卡体整体
// pointer-events:none，native title 在其上不触发，锚点必须在可悬停的按钮上），
// .edit-polish-foot 删除，单测/冒烟改锁按钮 title 文案。
// 同日四轮：①形态 select 的「形态」标题文案删除（select 裸留，label 容器与
// testid/DOM containment 不变）；②操作指南删「形态」「保存」两行（七行减五 ——
// 形态即眼前 select 自明、保存是 footer 按钮非画布交互，指南只留画布手势）。
//
// US-003 交互（pointer effect 内闭包 —— 监听器只挂一次，状态一律走 ref /
// editStore.getState()，不闭包 props/state）：
//   - 拖动：毛版 polygon pointerdown（选中 + 提层置顶）→ pointermove 经 rAF 节流成帧
//     （多 move 事件合一帧）→ 帧内只 setAttribute 被拖片 5 层 + setWorkingItem 更新
//     working 下标项（顶部状态条 / fab / 保存同真相源同帧刷新）；Y 硬钳制 [0,gate]
//     （按被拖片 bbox）、x<0 钳 0、右界自由拖（保存时 width_mm 双向伸缩）。
//   - 旋转：选中片质心上方常显旋转手柄；拖柄 = 绕**质心**自由转角（不做 0°/180° 吸附），
//     translation 按质心 pivot 公式随动（片原地转不漂移），布纹线随 5 层同步旋转。
//   - 重合指标：rAF 帧内消费 lib/overlap（precomputeEditPiecesFromItems 一次展开 +
//     applyEditPlacement 增量覆写被拖片一项 → computeOverlap bbox 预筛 + 布尔交）；
//     交集红色半透明高亮层 + 画布右上固定指标面板（面积 mm²/cm² + 最大穿透 + 旋转
//     偏离角，阈值着色 ≤10mm 琥珀 / >10mm 红 / >45° 红）；布尔交异常降级 bbox 交
//     高亮 + 面积按 bbox 估算（不阻塞拖动）。
//   - 空白 pointerdown 仍为平移；空白**点击**（位移 <3px 的 down-up）= 取消选中。
//
// edit-keyboard US-003（2026-09-05）mirror 渲染贯穿：working 项 mirror === true →
// applyPlacement 5 层（pointsStr/transformPt 第 4 参 x 取负）+ placementSig 加 mirror
// 段（同 rot/tr 翻转镜像必须重写 5 层）+ clampPlacement mirror 参（按镜像 bbox 钳制）；
// 拖动/旋转会话起手快照 mirror0（setWorkingItem 不改 mirror ⇒ 会话内恒定），帧内
// commitDragPlacement 透传 DOM 5 层 + applyEditPlacement 池增量（US-001 覆写语义：
// 镜像片增量必须显式传标志，缺省覆回 false）。
//
// edit-keyboard US-005（2026-09-05）键盘变换：window keydown（挂在指针交互同一
// effect 内 —— 复用 commitDragPlacement/refreshMetrics/updateHandle 闭包助手）。
// 守卫链：interactionEnabled=false（EditLayoutModal 确认层打开）→ 表单控件聚焦
// （INPUT/SELECT/TEXTAREA/BUTTON/contentEditable —— 键盘归控件）→ 无选中片，任一
// 命中零变换。键分发（选中片）：L=+1° / K=−1°（Shift ±10°，e.repeat 放行 = 按住
// auto-repeat 连转）、空格=rot+180（preventDefault 防 body 滚动；幂等键忽略
// e.repeat 防抖动）、O=toggle mirror（rot 不变）、I=toggle mirror+rot+180
// （diag(1,−1)=R(180°)·diag(−1,1) 复合律，共用单 mirror 标志）。
// 变换一律质心锚定不漂移：t' = c_world − R(rot')·M(m')·c_local（c_local/c_world =
// base/当前世界多边形顶点均值，M=diag(−1,1) when mirror），随后 clampPlacement
// （带 mirror 参）Y∈[0,gate] 与 minX<0 钳制（与拖动同口径，右界永不钳）。
//
// edit-keyboard US-006（2026-09-05）R 键片级重置：幂等键（忽略 e.repeat），守卫链
// 与 US-005 六键同链（总闸/表单控件/无选中任一命中无效）。R = editStore
// resetItem(selRef 下标)（恢复算法基线 —— 同 pid 多副本按下标寻址绝不按 pid；
// store 层 baseline/越界/id 错位三守卫，返回 false 静默不动）。成功后重读草稿项按
// 基线值走 refreshPieceView 单点刷新（DOM 5 层 + 池增量 + 指标/手柄同帧 —— store
// 写入已由 resetItem 承担，不重复 setWorkingItem；refreshPieceView 与
// commitDragPlacement 共用同一条「同帧刷新」路径）。

import { useEffect, useRef, useState } from 'react';
import {
  clientToWorld,
  bboxIntersect,
  bboxOf,
  penetrationDepth,
  transformPolygon,
} from '../../lib/editGeometry';
import {
  applyEditPlacement,
  computeOverlap,
  precomputeEditPiecesFromItems,
  type EditPiece,
} from '../../lib/overlap';
import { pointsStr } from '../../lib/geometry';
import { computeLayoutStats, useEditStore } from '../../store/editStore';
import type { PolishReport } from '../../lib/editPolish';
import { createPieceEntry, SVGNS, type PieceEntry } from '../nests/pieceDom';
import { MAX_OVERLAP_MM, MAX_ROTATION_TOL_DEG } from '../../constants/v03';
import { NOTCH_LEN_MM } from '../../constants/colors';
import type { Notch, PlacedItem, Polygon, Pt } from '../../types/piece';
import type { ManifestMsg } from '../../types/ws';

/** 画布形态：'full' 完整版（5 层全量）/ 'rough' 毛板（仅毛版轮廓 + 尺码色）。 */
export type EditViewMode = 'full' | 'rough';

/** 滚轮 / ± 按钮每档缩放倍率（deltaY<0 / ＋ 放大 → 宽 × 1/STEP）。 */
const ZOOM_STEP = 1.25;
/** viewBox 宽度界（mm）：最深 20mm（刀口级细节）→ 最广 = 当前视图宽 × 40。 */
const MIN_VB_W = 20;
const MAX_VB_SCALE = 40;

/** 空白 down→up 判定为「点击」（取消选中）的屏幕位移阈值（px）。 */
const CLICK_SLOP_PX = 3;
/** 旋转手柄世界半径（mm，随视图宽比例 + 钳制；柄心 = 质心上方 r×3）。 */
const HANDLE_R_MIN = 4;
const HANDLE_R_MAX = 30;

/** viewBox（SVG 用户空间 = 翻转组变换之外的 viewBox 坐标系）。 */
interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** 拖动会话（pointerdown 起至 pointerup/cancel；move/rotate 两模式互斥）。 */
interface MoveDrag {
  mode: 'move';
  pointerId: number;
  /** 被拖片 working 下标。 */
  index: number;
  /** pointerdown 客户端坐标（viewScale 差分锚 —— letterbox 偏移在差分中抵消）。 */
  startClient: Pt;
  rot0: number;
  tr0: Pt;
  /** 起手镜像标志（edit-keyboard US-003）：setWorkingItem 不改 mirror ⇒ 会话内恒定。 */
  mirror0: boolean;
}
interface RotateDrag {
  mode: 'rotate';
  pointerId: number;
  index: number;
  /** 旋转 pivot = 起手时被选片世界多边形质心（顶点均值；绕质心转片不漂移）。 */
  pivot: Pt;
  /** pointerdown 时指针绕 pivot 的方位角（°）。 */
  ang0: number;
  rot0: number;
  tr0: Pt;
  /** 起手镜像标志（edit-keyboard US-003）：会话内恒定（同 MoveDrag 注记）。 */
  mirror0: boolean;
}
type DragState = MoveDrag | RotateDrag;

/** 重合指标面板数据（refreshMetrics 单一产出口）。 */
interface EditMetrics {
  /** 交并总面积 mm²（degraded 时为 bbox 交面积估算）。 */
  areaMm2: number;
  /** 最大穿透深度 mm（顶点采样口径，与 overlap.ts 同源）。 */
  penetrationMm: number;
  /** 旋转偏离角 °（相对 {0°,180°} 最小偏差）。 */
  rotDevDeg: number;
  /** 布尔交异常降级（bbox 估算口径）。 */
  degraded: boolean;
}

export interface EditCanvasProps {
  /** 渲染形态（完整版/毛板，即时切换可恢复）。 */
  mode: EditViewMode;
  /**
   * 键盘/指针交互总闸（edit-keyboard US-005，缺省 true）：false = 键盘变换全键禁用
   * （EditLayoutModal ✕ dirty 确认层打开时传 !confirmDiscard —— 确认层的按钮/回车
   * 不被画布键劫持）。指针交互不受影响（确认层 overlay 已挡住画布 pointer 命中区）。
   */
  interactionEnabled?: boolean;
  /** 形态 select 变更回调（select 渲染在画布左上工具区，state 属 EditLayoutModal；
   *  直挂 EditCanvas 的单测不传 → no-op）。 */
  onModeChange?: (mode: EditViewMode) => void;
  /**
   * 智能微调 UI 受控接口（edit-polish US-003，2026-09-05）：按钮渲染在左上工具区、
   * 前后对比卡在画布左下（同日二轮迭代自右下卡栈迁入，与右下指南卡对称）。state 属
   * EditLayoutModal；直挂 EditCanvas 的单测不传 → 按钮/卡不渲染（零改动兼容）。
   */
  polish?: EditPolishUi;
}

/** 智能微调受控接口（EditLayoutModal → EditCanvas；字段语义见 EditLayoutModal 注释）。 */
export interface EditPolishUi {
  /** 请求在飞（按钮 loading 态，禁重复点击）。 */
  busy: boolean;
  /** 最近一次失败文案（卡内显示；null = 无）。 */
  error: string | null;
  /** 最近一次成功的前后对比报告（卡数据源；null = 未成功过）。 */
  report: PolishReport | null;
  /** 快照在案（「撤销微调」按钮显隐）。 */
  canUndo: boolean;
  /** US-005 压缩回收档勾选态（对比卡内 checkbox，随下次微调请求发出）。 */
  compact: boolean;
  onPolish: () => void;
  onUndo: () => void;
  /** compact 勾选态变更回调（state 属 EditLayoutModal 受控下发）。 */
  onCompactChange: (v: boolean) => void;
}

export function EditCanvas({ mode, interactionEnabled, onModeChange, polish }: EditCanvasProps) {
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
  /** 平移拖拽态（pointerId + 起点客户端坐标 + 点击判定 + 起点 viewBox 快照）。 */
  const panRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    moved: boolean;
    vb: ViewBox;
  } | null>(null);

  // ---- US-003：选中 / 拖动 / 重合指标态（sel/metrics 用 state 驱动 React 指标
  // 面板；其余全 ref —— pointer 监听器只挂一次，不闭包 props/state）----
  const modeRef = useRef<EditViewMode>(mode);
  modeRef.current = mode;
  /** 键盘交互总闸 ref（edit-keyboard US-005）：keydown 监听器只挂一次，prop 经
   *  ref 读现值 —— 确认层开关即时生效无需重挂监听。 */
  const interactionRef = useRef(true);
  interactionRef.current = interactionEnabled !== false;
  const selRef = useRef<number | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [metrics, setMetrics] = useState<EditMetrics | null>(null);
  /** 重合计算池（选中时自 working 全量展开一次；拖动帧只增量覆写被拖片一项）。 */
  const poolRef = useRef<EditPiece[] | null>(null);
  /** UI 覆盖层（翻转组内世界坐标）：交集高亮 g + 旋转手柄 g，置顶于全部裁片。 */
  const uiLayerRef = useRef<SVGGElement | null>(null);
  const overlapGRef = useRef<SVGGElement | null>(null);
  const handleGRef = useRef<SVGGElement | null>(null);
  const handleLineRef = useRef<SVGLineElement | null>(null);
  const handleCircleRef = useRef<SVGCircleElement | null>(null);
  /** 每下标已应用的放置签名（mode|rot|tr）—— working 变化只碰签名变了的片 5 层。 */
  const lastSigRef = useRef<string[]>([]);
  const dragRef = useRef<DragState | null>(null);
  const rafRef = useRef<number | null>(null);
  const pendingMoveRef = useRef<Pt | null>(null);

  const run = useEditStore((s) => s.run);
  const working = useEditStore((s) => s.working);

  /**
   * 主渲染 effect：manifest/pid 序列变化 → 重建骨架（bg + fab + 翻转组 + N×5 层 +
   * 清选中/池/UI 层）；working / mode 变化 → 签名跳过式 setAttribute（拖动帧外只有
   * 被改片签名变化 → 只碰该片 5 层；mode 前缀使形态切换全量重应用显隐）。
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
      // US-003：骨架重建 → 选中/池/UI 覆盖层/签名全部作废（UI 层随翻转组拆除）。
      selRef.current = null;
      setSel(null);
      setMetrics(null);
      poolRef.current = null;
      uiLayerRef.current = null;
      overlapGRef.current = null;
      handleGRef.current = null;
      handleLineRef.current = null;
      handleCircleRef.current = null;
      lastSigRef.current = [];

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

    // 5 层按 working 更新（mode 决定 4 层工艺显隐；毛版恒显）—— 签名跳过：
    // 拖动帧内已即时应用的片签名相同 → 零 setAttribute；reset 等全量变化自然全应用。
    // mirror 进签名（edit-keyboard US-003）：同 rot/tr 翻转镜像改变世界几何 → 必须重写。
    working.forEach((it, i) => {
      const entry = entriesRef.current[i];
      if (!entry || entry.piece.id !== it.id) return; // 防御：池与 working 错位
      const mirror = it.mirror === true; // omit-when-false：undefined/false 同义无镜像
      const sig = placementSig(mode, it.rotation, it.translation, mirror);
      if (lastSigRef.current[i] === sig) return;
      lastSigRef.current[i] = sig;
      applyPlacement(entry, it.rotation, it.translation, mode, mirror);
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
   * 指针交互（US-002 平移 + US-003 拖动/旋转/选中，单一 effect 内分层分发；edit-keyboard
   * US-005 起同 effect 兼挂 window keydown —— 键盘变换落笔复用本闭包的
   * commitDragPlacement/refreshMetrics/updateHandle，见组件头注 US-005 段）：
   *   pointerdown target ∈ 旋转手柄 → 绕质心旋转拖柄；
   *   pointerdown target ∈ 毛版 polygon → 选中 + 提层 + 平移拖片；
   *   空白（svg/bg/fab）→ 平移（位移 <3px 的 down-up = 点击取消选中）。
   *
   * 拖动帧 rAF 节流：pointermove 只记最新坐标 + 调度一帧；帧内算钳制后放置 →
   * 只 setAttribute 被拖片 5 层 + setWorkingItem（状态条同帧刷新）+ 池内增量覆写
   * 被拖片 + 重合指标/手柄刷新。pointerup 先同步落帧（悬空 rAF 不丢尾帧）。
   */
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    // 非空别名（function 声明有提升，捕获变量不保留 const 收窄 → 显式别名定宽）。
    const svgEl: SVGSVGElement = svg;

    // ---- 选中 / UI 覆盖层 / 指标（闭包内定义，仅经 refs/store 读写状态）----

    /** 建（或复用）UI 覆盖层：交集高亮 g（pointer-events:none）+ 旋转手柄 g。 */
    function ensureUiLayers(): void {
      const g = flipRef.current;
      if (!g) return;
      if (uiLayerRef.current) {
        if (handleGRef.current) handleGRef.current.style.display = '';
        return;
      }
      const layer = document.createElementNS(SVGNS, 'g');
      const overlapG = document.createElementNS(SVGNS, 'g');
      overlapG.style.pointerEvents = 'none';
      const handleG = document.createElementNS(SVGNS, 'g');
      // 手柄 = 质心→柄心连线（不可抓）+ 实心圆（可抓，rotate 拖柄目标）。
      const line = document.createElementNS(SVGNS, 'line');
      line.setAttribute('stroke', '#2ea06c');
      line.setAttribute('stroke-width', '1.5');
      line.setAttribute('stroke-dasharray', '4 3');
      line.style.pointerEvents = 'none';
      const circle = document.createElementNS(SVGNS, 'circle');
      circle.setAttribute('fill', '#2ea06c');
      circle.setAttribute('fill-opacity', '0.9');
      circle.setAttribute('stroke', '#fff');
      circle.setAttribute('stroke-width', '1');
      circle.setAttribute('data-edit-role', 'rotate'); // 行为锚（pointerdown 分发用）
      circle.setAttribute('data-testid', 'edit-rotate-handle');
      circle.classList.add('edit-rotate-handle');
      handleG.appendChild(line);
      handleG.appendChild(circle);
      layer.appendChild(overlapG);
      layer.appendChild(handleG);
      g.appendChild(layer);
      uiLayerRef.current = layer;
      overlapGRef.current = overlapG;
      handleGRef.current = handleG;
      handleLineRef.current = line;
      handleCircleRef.current = circle;
    }

    /** 被选中/被拖片 5 层节点移动到全部裁片之上（UI 覆盖层之下）。 */
    function raiseEntry(entry: PieceEntry): void {
      const g = flipRef.current;
      if (!g) return;
      const anchor = uiLayerRef.current;
      const nodes: SVGElement[] = [entry.el];
      if (entry.netEl) nodes.push(entry.netEl);
      nodes.push(...entry.internalEls, ...entry.notchEls);
      if (entry.grainEl) nodes.push(entry.grainEl);
      for (const n of nodes) g.insertBefore(n, anchor); // anchor null → 追加到末尾
    }

    /** 自 working 全量展开重合池（选中时一次；拖动帧不再全量重算）。 */
    function ensurePool(): void {
      const manifest = manifestRef.current;
      if (!manifest) return;
      poolRef.current = precomputeEditPiecesFromItems(
        manifest,
        useEditStore.getState().working as readonly PlacedItem[],
      );
    }

    /** 世界多边形质心（顶点均值 —— 手柄/pivot 的 UI 近似，非度量口径）。 */
    function centroidOf(poly: readonly Pt[]): Pt {
      let x = 0;
      let y = 0;
      for (const p of poly) {
        x += p[0];
        y += p[1];
      }
      const n = Math.max(1, poly.length);
      return [x / n, y / n];
    }

    /** 旋转手柄位置/尺寸刷新（世界坐标；尺寸随视图宽比例，钳制到 mm 级可抓）。 */
    function updateHandle(index: number): void {
      const ep = poolRef.current?.find((p) => p.key === index);
      const line = handleLineRef.current;
      const circle = handleCircleRef.current;
      if (!ep || !line || !circle) return;
      const c = centroidOf(ep.worldPolygon);
      const vb = vbRef.current;
      const r = vb ? Math.min(HANDLE_R_MAX, Math.max(HANDLE_R_MIN, vb.w * 0.015)) : 12;
      const off = r * 3; // 质心上方（世界 +Y = 翻转组内屏幕上方）
      line.setAttribute('x1', String(r6(c[0])));
      line.setAttribute('y1', String(r6(c[1])));
      line.setAttribute('x2', String(r6(c[0])));
      line.setAttribute('y2', String(r6(c[1] + off)));
      circle.setAttribute('cx', String(r6(c[0])));
      circle.setAttribute('cy', String(r6(c[1] + off)));
      circle.setAttribute('r', String(r6(r)));
    }

    /** 交集高亮层清空。 */
    function clearHighlight(): void {
      const g = overlapGRef.current;
      if (!g) return;
      while (g.firstChild) g.removeChild(g.firstChild);
    }

    /** 高亮层加一个红色半透明多边形（世界坐标 ring）。 */
    function appendHighlight(ring: Polygon): void {
      const g = overlapGRef.current;
      if (!g) return;
      const poly = document.createElementNS(SVGNS, 'polygon');
      poly.setAttribute('fill', 'rgba(255, 64, 64, 0.42)');
      poly.setAttribute('stroke', '#ff4040');
      poly.setAttribute('stroke-width', '1');
      poly.setAttribute('points', pointsStr(ring, 0, [0, 0]));
      g.appendChild(poly);
    }

    /** 重合指标计算 + 高亮渲染 + 面板数据（选中与拖动帧的唯一产出口）。 */
    function refreshMetrics(index: number): void {
      const pool = poolRef.current;
      if (!pool) return;
      const dragged = pool.find((p) => p.key === index);
      if (!dragged) return;
      clearHighlight();
      let m: EditMetrics;
      try {
        const res = computeOverlap(dragged, pool);
        for (const ring of res.intersections) appendHighlight(ring);
        m = {
          areaMm2: res.areaMm2,
          penetrationMm: res.penetrationMm,
          rotDevDeg: rotationDeviationDeg(dragged.rot),
          degraded: false,
        };
      } catch {
        // 布尔交异常降级（PRD 口径）：bbox 交高亮 + 面积按 bbox 估算，不阻塞拖动。
        // 穿透深度是独立纯函数（顶点采样，无布尔交）—— 继续如实计算。
        let area = 0;
        let pen = 0;
        for (const o of pool) {
          if (o.key === index) continue;
          if (!bboxIntersect(dragged.bbox, o.bbox)) continue;
          const minX = Math.max(dragged.bbox.minX, o.bbox.minX);
          const minY = Math.max(dragged.bbox.minY, o.bbox.minY);
          const maxX = Math.min(dragged.bbox.maxX, o.bbox.maxX);
          const maxY = Math.min(dragged.bbox.maxY, o.bbox.maxY);
          if (maxX <= minX || maxY <= minY) continue;
          area += (maxX - minX) * (maxY - minY);
          appendHighlight([
            [minX, minY],
            [maxX, minY],
            [maxX, maxY],
            [minX, maxY],
          ]);
          pen = Math.max(pen, penetrationDepth(dragged.worldPolygon, o.worldPolygon));
        }
        m = {
          areaMm2: area,
          penetrationMm: pen,
          rotDevDeg: rotationDeviationDeg(dragged.rot),
          degraded: true,
        };
      }
      setMetrics(m);
    }

    /** 选中片（pointerdown on 毛版）：UI 层 + 提层 + 建池 + 指标 + 手柄。 */
    function selectPiece(index: number): void {
      const entry = entriesRef.current[index];
      if (!entry) return;
      selRef.current = index;
      setSel(index);
      ensureUiLayers();
      raiseEntry(entry);
      ensurePool();
      refreshMetrics(index);
      updateHandle(index);
    }

    /** 取消选中（空白点击）：清池/高亮/手柄；指标面板随 sel=null 卸下。 */
    function deselect(): void {
      selRef.current = null;
      setSel(null);
      setMetrics(null);
      poolRef.current = null;
      clearHighlight();
      if (handleGRef.current) handleGRef.current.style.display = 'none';
    }

    /** 帧内落笔单片放置：5 层 setAttribute + 签名登记（主渲染 effect 同帧跳过该片）。 */
    function applyEntryPlacement(
      index: number,
      entry: PieceEntry,
      rot: number,
      tr: Pt,
      mirror: boolean,
    ): void {
      applyPlacement(entry, rot, tr, modeRef.current, mirror);
      lastSigRef.current[index] = placementSig(modeRef.current, rot, tr, mirror);
    }

    /**
     * 帧内视图落笔单片（不含 store 写入）：DOM 5 层 + 预计算池增量 + 指标 + 手柄。
     * edit-keyboard US-006：R 键片级重置复用 —— store 写入由 resetItem 承担（reset 后
     * 不重复 setWorkingItem），视图侧与拖动帧共用同一条「同帧刷新」路径。
     * mirror 显式透传（edit-keyboard US-003）：applyEditPlacement 是覆写语义（US-001），
     * 缺省 false 会把池内镜像片静默覆回非镜像 → 重合指标按错几何算。
     */
    function refreshPieceView(
      index: number,
      entry: PieceEntry,
      rot: number,
      tr: Pt,
      mirror: boolean,
    ): void {
      applyEntryPlacement(index, entry, rot, tr, mirror);
      const ep = poolRef.current?.find((p) => p.key === index);
      if (ep) applyEditPlacement(ep, rot, tr, mirror); // 预计算池增量：只重算单片一项
      refreshMetrics(index);
      updateHandle(index);
    }

    /**
     * 拖动帧共同落笔：working（真相源，setWorkingItem）+ refreshPieceView（DOM 5 层 +
     * 池增量 + 指标 + 手柄）。
     * mirrorPatch（edit-keyboard US-005，缺省 undefined = 不改 mirror —— 指针拖动会话
     * 内 mirror 恒定走缺省）：键盘 O/I 翻转镜像时显式传目标值（store patch.mirror）。
     */
    function commitDragPlacement(
      index: number,
      entry: PieceEntry,
      rot: number,
      tr: Pt,
      mirror: boolean,
      mirrorPatch?: boolean,
    ): void {
      const patch: { rotation: number; translation: Pt; mirror?: boolean } = {
        rotation: rot,
        translation: tr,
      };
      if (mirrorPatch !== undefined) patch.mirror = mirrorPatch;
      useEditStore.getState().setWorkingItem(index, patch);
      refreshPieceView(index, entry, rot, tr, mirror);
    }

    /**
     * 键盘变换统一出口（edit-keyboard US-005；L/K/Shift/空格/O/I 共用）：按目标
     * (rot', m') 质心锚定算 translation —— t' = c_world − R(rot')·M(m')·c_local
     * （c_local/c_world = base/当前世界多边形顶点均值；质心是仿射量 ⇒ 零平移变换
     * 后的质心恰 = R(rot')·M(m')·c_local，片原地变换不漂移）—— 再 clampPlacement
     * （Y∈[0,gate] / minX≥0，右界不钳，与拖动同口径）+ commitDragPlacement 泛化
     * 路径（DOM 5 层 + working（含 mirror patch）+ 池增量 + 指标/手柄，O(单片)）。
     */
    function applyKeyTransform(index: number, rot: number, mirror: boolean): void {
      const manifest = manifestRef.current;
      const entry = entriesRef.current[index];
      if (!manifest || !entry) return;
      const it = useEditStore.getState().working[index];
      if (!it) return; // 防御：选中下标与 working 错位（骨架重建清选中，理论不达）
      const base = entry.piece.polygon;
      const curMirror = it.mirror === true;
      const cWorld = centroidOf(transformPolygon(base, it.rotation, it.translation, curMirror));
      const cLocalNew = centroidOf(transformPolygon(base, rot, [0, 0], mirror));
      const tr = clampPlacement(
        base,
        rot,
        [cWorld[0] - cLocalNew[0], cWorld[1] - cLocalNew[1]],
        manifest.gate_mm,
        mirror,
      );
      commitDragPlacement(index, entry, rot, tr, mirror, mirror);
    }

    /** 平移拖片帧（viewScale 差分 → 起始 tr + 位移 → 钳制 → 落笔）。 */
    function applyMoveFrame(st: MoveDrag, clientX: number, clientY: number): void {
      const manifest = manifestRef.current;
      const entry = entriesRef.current[st.index];
      const vb = vbRef.current;
      if (!manifest || !entry || !vb) return;
      const s = viewScale(svgEl, vb);
      if (s <= 0) return; // 未布局（零尺寸 rect）→ 本帧丢弃
      // 屏幕位移 → 世界位移（meet 等比 s = px/mm；翻转组 scale(1,-1) → dy 取反；
      // letterbox 偏移在差分中抵消，与空白平移同款口径）。
      const dx = (clientX - st.startClient[0]) / s;
      const dy = -(clientY - st.startClient[1]) / s;
      const tr = clampPlacement(
        entry.piece.polygon,
        st.rot0,
        [st.tr0[0] + dx, st.tr0[1] + dy],
        manifest.gate_mm,
        st.mirror0,
      );
      commitDragPlacement(st.index, entry, st.rot0, tr, st.mirror0);
    }

    /** 旋转拖柄帧（指针绕 pivot 方位角差 → 自由转角；pivot 公式随动 translation）。 */
    function applyRotateFrame(st: RotateDrag, clientX: number, clientY: number): void {
      const manifest = manifestRef.current;
      const flip = flipRef.current;
      const entry = entriesRef.current[st.index];
      if (!manifest || !flip || !entry) return;
      const w = clientToWorld(svgEl, flip, clientX, clientY);
      if (!w) return; // CTM 不可得 → 旋转无意义（起手即校验，此为防御）
      const ang = (Math.atan2(w[1] - st.pivot[1], w[0] - st.pivot[0]) * 180) / Math.PI;
      const dAng = wrapDeg180(ang - st.ang0);
      const rot = st.rot0 + dAng; // 自由角度，无 0°/180° 吸附（2026-09-04 定案）
      const tr = clampPlacement(
        entry.piece.polygon,
        rot,
        pivotTranslate(st.pivot, dAng, st.tr0),
        manifest.gate_mm,
        st.mirror0,
      );
      commitDragPlacement(st.index, entry, rot, tr, st.mirror0);
    }

    function applyDragFrame(clientX: number, clientY: number): void {
      const st = dragRef.current;
      if (!st) return;
      if (st.mode === 'move') applyMoveFrame(st, clientX, clientY);
      else applyRotateFrame(st, clientX, clientY);
    }

    /** rAF 节流：多个 pointermove 合一帧（rAF 缺席的降级环境同步直跑）。 */
    function scheduleFrame(): void {
      if (rafRef.current != null) return;
      const run = (): void => {
        rafRef.current = null;
        const p = pendingMoveRef.current;
        pendingMoveRef.current = null;
        if (p && dragRef.current) applyDragFrame(p[0], p[1]);
      };
      if (typeof requestAnimationFrame === 'function') {
        rafRef.current = requestAnimationFrame(run);
      } else {
        run();
      }
    }

    /** 同步落帧（pointerup 先于 rAF 触发时保尾帧；测试确定性路径）。 */
    function flushFrame(): void {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      const p = pendingMoveRef.current;
      pendingMoveRef.current = null;
      if (p && dragRef.current) applyDragFrame(p[0], p[1]);
    }

    // ---- 事件分发 ----

    const onPointerDown = (e: PointerEvent): void => {
      const target = e.target as Element | null;
      // 1) 旋转手柄（选中片常显）→ 绕质心旋转拖柄。
      if (target?.closest?.('[data-edit-role="rotate"]')) {
        const index = selRef.current;
        const flip = flipRef.current;
        const entry = index != null ? entriesRef.current[index] : null;
        if (index == null || !flip || !entry) return;
        const ep = poolRef.current?.find((p) => p.key === index);
        const w = ep ? clientToWorld(svg, flip, e.clientX, e.clientY) : null;
        if (!ep || !w) return; // CTM 不可得 → 不起旋转（世界方位角无从计算）
        const pivot = centroidOf(ep.worldPolygon);
        const it = useEditStore.getState().working[index];
        dragRef.current = {
          mode: 'rotate',
          pointerId: e.pointerId,
          index,
          pivot,
          ang0: (Math.atan2(w[1] - pivot[1], w[0] - pivot[0]) * 180) / Math.PI,
          rot0: it.rotation,
          tr0: [it.translation[0], it.translation[1]],
          mirror0: it.mirror === true,
        };
        try {
          handleCircleRef.current?.setPointerCapture?.(e.pointerId);
        } catch {
          /* 捕获失败不影响旋转 —— move/up 监听挂 svg 自身 */
        }
        svg.style.cursor = 'grabbing';
        return;
      }
      // 2) 毛版 polygon → 选中 + 提层 + 平移拖片（4 层工艺 / 交集高亮层均
      //    pointer-events:none，不会成为 target）。
      const poly = target?.closest?.('polygon');
      if (poly) {
        const index = entriesRef.current.findIndex((en) => en != null && en.el === poly);
        if (index < 0) return; // 非裁片毛版 polygon（防御）
        selectPiece(index);
        const it = useEditStore.getState().working[index];
        dragRef.current = {
          mode: 'move',
          pointerId: e.pointerId,
          index,
          startClient: [e.clientX, e.clientY],
          rot0: it.rotation,
          tr0: [it.translation[0], it.translation[1]],
          mirror0: it.mirror === true,
        };
        try {
          (poly as SVGPolygonElement).setPointerCapture?.(e.pointerId);
        } catch {
          /* 捕获失败不影响拖动 —— move/up 监听挂 svg 自身 */
        }
        svg.style.cursor = 'move';
        return;
      }
      // 3) 空白（svg/bg/fab）→ 平移（位移 <3px 的 down-up = 点击取消选中）。
      const vb = vbRef.current;
      if (!vb) return;
      try {
        svg.setPointerCapture?.(e.pointerId); // jsdom 未实现/未知指针 id 抛错 → 忽略
      } catch {
        /* 捕获失败不影响平移 —— move/up 监听本就挂 svg 自身 */
      }
      panRef.current = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        moved: false,
        vb: { ...vb },
      };
      svg.style.cursor = 'grabbing';
    };

    const onPointerMove = (e: PointerEvent): void => {
      const d = dragRef.current;
      if (d && e.pointerId === d.pointerId) {
        pendingMoveRef.current = [e.clientX, e.clientY];
        scheduleFrame();
        return;
      }
      const p = panRef.current;
      if (!p || e.pointerId !== p.pointerId) return;
      if (!p.moved && Math.hypot(e.clientX - p.startX, e.clientY - p.startY) > CLICK_SLOP_PX) {
        p.moved = true;
      }
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

    const endDrag = (e: PointerEvent): void => {
      const d = dragRef.current;
      if (!d || e.pointerId !== d.pointerId) return;
      flushFrame(); // 悬空 rAF 落帧（move 后立即 up 不丢尾帧）
      dragRef.current = null;
      svg.style.cursor = '';
    };

    const endPan = (e: PointerEvent): void => {
      const p = panRef.current;
      if (!p || e.pointerId !== p.pointerId) return;
      panRef.current = null;
      svg.style.cursor = '';
      if (!p.moved && selRef.current != null) deselect(); // 空白点击 = 取消选中
    };

    const onPointerUp = (e: PointerEvent): void => {
      endDrag(e);
      endPan(e);
    };

    const onPointerCancel = (e: PointerEvent): void => {
      // 手势中止：丢弃未落帧的 pending（已落帧的 working 保留 —— 草稿不回滚），态复位。
      const d = dragRef.current;
      if (d && e.pointerId === d.pointerId) {
        if (rafRef.current != null) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = null;
        }
        pendingMoveRef.current = null;
        dragRef.current = null;
        svg.style.cursor = '';
        return;
      }
      endPan(e);
    };

    /**
     * 键盘变换（edit-keyboard US-005 + US-006 R 键；window keydown —— 画布无
     * tabIndex 不抢焦点，target = body/最近聚焦元素）。守卫链任一命中零变换：
     * ①interactionEnabled=false（确认层打开）②表单控件聚焦
     * （INPUT/SELECT/TEXTAREA/BUTTON/contentEditable —— 键盘归控件，含画布左上形态
     * select）③无选中片。分发见组件头注 US-005/US-006 段。
     */
    const onKeyDown = (e: KeyboardEvent): void => {
      if (!interactionRef.current) return; // 守卫①：确认层打开 → 全键禁用
      const t = e.target as Element | null; // 守卫②：表单控件聚焦
      if (t) {
        const tag = typeof t.tagName === 'string' ? t.tagName.toUpperCase() : '';
        if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || tag === 'BUTTON') {
          return;
        }
        if ((t as HTMLElement).isContentEditable) return;
      }
      const index = selRef.current; // 守卫③：无选中片
      if (index == null) return;
      const it = useEditStore.getState().working[index];
      if (!it) return;
      // 单字符键统一小写（Shift+L 的 e.key='L'，CapsLock 布局同样命中）。
      const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      const curMirror = it.mirror === true;
      if (k === 'l' || k === 'k') {
        // L/K 放行 e.repeat（浏览器 auto-repeat = 按住连转）；Shift 步长 ±10°。
        const step = (e.shiftKey ? 10 : 1) * (k === 'l' ? 1 : -1);
        applyKeyTransform(index, it.rotation + step, curMirror);
        return;
      }
      // 幂等键（空格/O/I/R）忽略 e.repeat：一次 keydown 一次变换，按住不抖动。
      if (e.repeat) return;
      if (k === 'r') {
        // R 片级重置（US-006）：恢复算法基线 = editStore.resetItem（按下标寻址 ——
        // 同 pid 多副本绝不按 pid；store 层 baseline/越界/id 错位三守卫，返回 false =
        // 守卫命中 → 静默不动不炸）。成功后重读草稿项按基线值单点刷新视图（store
        // 写入已由 resetItem 承担，不重复 setWorkingItem）。
        if (!useEditStore.getState().resetItem(index)) return;
        const rst = useEditStore.getState().working[index];
        const entry = entriesRef.current[index];
        if (rst && entry) {
          refreshPieceView(index, entry, rst.rotation, rst.translation, rst.mirror === true);
        }
        return;
      }
      if (k === ' ') {
        e.preventDefault(); // 防 body 滚动（聚焦按钮激活已被守卫②排除）
        applyKeyTransform(index, it.rotation + 180, curMirror);
        return;
      }
      if (k === 'o') {
        // 水平镜像 = toggle mirror（rot 不变）。
        applyKeyTransform(index, it.rotation, !curMirror);
        return;
      }
      if (k === 'i') {
        // 垂直镜像 = toggle mirror + rot+180（diag(1,−1)=R(180°)·diag(−1,1)，共用单标志）。
        applyKeyTransform(index, it.rotation + 180, !curMirror);
      }
    };

    svg.addEventListener('pointerdown', onPointerDown);
    svg.addEventListener('pointermove', onPointerMove);
    svg.addEventListener('pointerup', onPointerUp);
    svg.addEventListener('pointercancel', onPointerCancel);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      svg.removeEventListener('pointerdown', onPointerDown);
      svg.removeEventListener('pointermove', onPointerMove);
      svg.removeEventListener('pointerup', onPointerUp);
      svg.removeEventListener('pointercancel', onPointerCancel);
      window.removeEventListener('keydown', onKeyDown);
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      pendingMoveRef.current = null;
      dragRef.current = null;
      panRef.current = null;
    };
  }, []);

  /** 「全览」：缩放/平移一步复位到初始适配视图（vb0）—— 不还原已编辑布局。 */
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
      {/* 视图工具（左上横排，2026-09-05 二轮迭代竖改横）：全览按钮 + 形态 select
          （2026-09-05 自 footer 移入；同日四轮「形态」标题文案删除 —— select 裸留）
          + 智能微调按钮（edit-polish US-003）。右上留给 US-003 指标面板、左下微调
          对比卡、右下指南卡 —— 均悬浮不挡画布。 */}
      <div className="edit-layout-canvas-tools">
        <button
          type="button"
          className="edit-layout-tool edit-layout-tool-reset"
          onClick={handleResetView}
          title="缩放与平移复位到全布局（不还原已编辑布局）"
          data-testid="edit-zoom-reset"
        >
          全览
        </button>
        <label className="edit-layout-mode">
          <select
            value={mode}
            onChange={(e) => onModeChange?.(e.target.value as EditViewMode)}
            data-testid="edit-layout-mode"
          >
            <option value="full">完整版</option>
            <option value="rough">毛板</option>
          </select>
        </label>
        {polish && (
          <button
            type="button"
            className="edit-layout-tool edit-polish-btn"
            onClick={polish.onPolish}
            disabled={polish.busy}
            title="自动清理可解的重合与可回正的旋转（报告为物理毛版轮廓口径、与导出一致，画布红字为腐蚀后轮廓口径数值可能偏小；料长不增、密度不降；应用后不自动保存，可撤销）"
            data-testid="edit-polish-btn"
          >
            {polish.busy ? '微调中…' : '智能微调'}
          </button>
        )}
      </div>
      {/* 智能微调对比卡（edit-polish US-003；2026-09-05 二轮迭代自右下卡栈迁画布左下、
          与右下指南卡水平对称 —— 原右下双卡叠置挡排料尾部主视图）。卡体
          pointer-events:none，仅撤销按钮 + compact checkbox 行 auto（可交互不挡画布
          拖动热区）。 */}
      {polish && (polish.report || polish.error) && (
        <div className="edit-polish-card" data-testid="edit-polish-card">
          <div className="edit-metrics-title">智能微调（前 → 后）</div>
          {polish.error && (
            <div className="edit-polish-error" data-testid="edit-polish-error">
              {polish.error}
            </div>
          )}
          {polish.report && (
            <>
              <div className="edit-polish-row">
                <span className="edit-metrics-label">重叠对数</span>
                <span className="edit-polish-val" data-testid="edit-polish-overlap">
                  {polish.report.before.overlap_pairs} → {polish.report.after.overlap_pairs}
                </span>
              </div>
              <div className="edit-polish-row">
                <span className="edit-metrics-label">最大穿透</span>
                <span className="edit-polish-val" data-testid="edit-polish-depth">
                  {fmt(polish.report.before.max_penetration_mm, 2)} →{' '}
                  {fmt(polish.report.after.max_penetration_mm, 2)} mm
                </span>
              </div>
              <div className="edit-polish-row">
                <span className="edit-metrics-label">旋转偏差片</span>
                <span className="edit-polish-val" data-testid="edit-polish-rot">
                  {polish.report.before.rotated_pieces} → {polish.report.after.rotated_pieces}
                </span>
              </div>
              <div className="edit-polish-row">
                <span className="edit-metrics-label">Σ旋转偏差</span>
                <span className="edit-polish-val" data-testid="edit-polish-rotsum">
                  {fmt(polish.report.before.rotation_dev_sum_deg, 1)} →{' '}
                  {fmt(polish.report.after.rotation_dev_sum_deg, 1)}°
                </span>
              </div>
              <div className="edit-polish-row">
                <span className="edit-metrics-label">料长</span>
                <span className="edit-polish-val" data-testid="edit-polish-width">
                  {fmt(polish.report.before.width_mm, 1)} → {fmt(polish.report.after.width_mm, 1)}{' '}
                  mm
                </span>
              </div>
              <div className="edit-polish-row">
                <span className="edit-metrics-label">密度</span>
                <span className="edit-polish-val" data-testid="edit-polish-density">
                  {fmt(polish.report.before.density, 2)} → {fmt(polish.report.after.density, 2)} %
                </span>
              </div>
              {/* US-005 压缩回收档：默认不勾，勾选后随下次微调请求发出
                  （compact:true → 引擎 pass ④ 自布头滑贴收空隙）。 */}
              <label
                className="edit-polish-opt"
                title="勾选后下次微调附带压缩回收：去旋/分离释放的空隙自布头滑贴收进料长（包络严格变小且零新重合才接受，可撤销）"
              >
                <input
                  type="checkbox"
                  checked={polish.compact}
                  onChange={(e) => polish.onCompactChange(e.target.checked)}
                  data-testid="edit-polish-compact"
                />
                回收空隙缩短料长（下次微调生效）
              </label>
            </>
          )}
          {polish.canUndo && (
            <button
              type="button"
              className="edit-polish-undo"
              onClick={polish.onUndo}
              data-testid="edit-polish-undo"
            >
              撤销微调
            </button>
          )}
        </div>
      )}
      {/* 操作指南（画布右下、保存按钮上方；与指标面板同款悬浮卡不挡交互）。
          行式 = 左对齐自然换行（.edit-guide-row），非指标面板的两端对齐 nowrap。
          2026-09-05 四轮：删「形态」「保存」两行（七减五）—— 形态即眼前 select
          自明、保存是 footer 按钮非画布手势，指南只留画布内交互；edit-keyboard
          US-005 同日补键盘行（键盘也是画布内交互，六键语义一行）。 */}
      <div className="edit-guide" data-testid="edit-guide">
      <div className="edit-metrics-title">操作指南</div>
      <div className="edit-guide-row">
        <span className="edit-metrics-label">拖动裁片：</span>按住裁片拖动（自动选中置顶）
      </div>
      <div className="edit-guide-row">
        <span className="edit-metrics-label">旋转：</span>拖动选中片上方绿色圆点，绕中心自由旋转
      </div>
      <div className="edit-guide-row">
        <span className="edit-metrics-label">缩放：</span>鼠标滚轮（以指针为中心）
      </div>
      <div className="edit-guide-row">
        <span className="edit-metrics-label">平移：</span>按住空白处拖动
      </div>
      <div className="edit-guide-row">
        <span className="edit-metrics-label">取消选中：</span>单击空白处
      </div>
      {/* edit-keyboard US-005：六键语义一行（Shift+L/K ±10° 略 —— 微转步长属于
          进阶细节，按钮区已有 title 悬浮惯例可后续补；文案不得含「形态」「保存」
          （EditCanvas.test 反向锁）。 */}
      <div className="edit-guide-row">
        <span className="edit-metrics-label">键盘：</span>L/K 微转 · 空格 180° · O 水平镜像 · I 垂直镜像 · R 重置此片
      </div>
      <div className="edit-guide-foot">拖动自动限制在门幅内（上下不出布边）</div>
      </div>
      {/* 选中片重合指标面板（画布右上固定；未选中不渲染）。 */}
      {sel !== null && metrics !== null && (
        <div
          className="edit-metrics"
          data-testid="edit-metrics"
          data-degraded={metrics.degraded ? '1' : '0'}
        >
          <div className="edit-metrics-title">重合指标（选中片）</div>
          <div className="edit-metrics-row">
            <span className="edit-metrics-label">重合面积</span>
            <span className="edit-metrics-val" data-testid="edit-metrics-area">
              {metrics.areaMm2.toFixed(1)} mm²（{(metrics.areaMm2 / 100).toFixed(2)} cm²）
              {metrics.degraded ? ' · bbox 估算' : ''}
            </span>
          </div>
          <div className="edit-metrics-row">
            <span className="edit-metrics-label">最大穿透</span>
            <span
              className={
                metrics.penetrationMm > MAX_OVERLAP_MM
                  ? 'edit-metrics-val edit-metrics-val--danger'
                  : metrics.penetrationMm > 0
                    ? 'edit-metrics-val edit-metrics-val--warn'
                    : 'edit-metrics-val'
              }
              data-testid="edit-metrics-depth"
            >
              {metrics.penetrationMm.toFixed(1)} mm
            </span>
          </div>
          <div className="edit-metrics-row">
            <span className="edit-metrics-label">旋转偏离</span>
            <span
              className={
                metrics.rotDevDeg > MAX_ROTATION_TOL_DEG
                  ? 'edit-metrics-val edit-metrics-val--danger'
                  : 'edit-metrics-val'
              }
              data-testid="edit-metrics-rot"
            >
              {metrics.rotDevDeg.toFixed(1)}°
            </span>
          </div>
          <div className="edit-metrics-foot">按算法碰撞口径</div>
        </div>
      )}
    </div>
  );
}

/**
 * 放置签名（mode|rot|tr|mirror）—— 主渲染 effect「该片是否需要重写 5 层」的判据。
 * mirror 段（edit-keyboard US-003）：镜像翻转改变世界几何（x 取负），同 rot/tr 不同
 * mirror 是不同放置 —— 签名缺席会把 replaceWorking 翻转镜像误判为无变化 → 画布陈旧。
 */
function placementSig(mode: EditViewMode, rot: number, tr: Pt, mirror: boolean): string {
  return `${mode}|${rot}|${tr[0]}|${tr[1]}|${mirror ? 1 : 0}`;
}

/** 数值定长显示（对比卡前后值；NaN/缺键防御显示 '—'）。 */
function fmt(v: number | undefined, digits: number): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—';
}

/**
 * 旋转偏离角（°）= 相对 {0°,180°} 的最小偏差 min(|rot|,|rot−180|,|rot−360|)。
 * 先归一到 [0,360)（负角 / >360° 输入等价处理），PRD US-003 口径。
 */
function rotationDeviationDeg(rot: number): number {
  const r = ((rot % 360) + 360) % 360;
  return Math.min(Math.abs(r), Math.abs(r - 180), Math.abs(r - 360));
}

/** 角度差归一到 (−180,180]（旋转拖柄自由转角差；跨 ±180 边界连续）。 */
function wrapDeg180(d: number): number {
  return ((d + 180) % 360 + 360) % 360 - 180;
}

/**
 * 放置钳制（US-003 口径）：按被操作片世界 bbox —— minY<0 上抬 / maxY>gate 下压
 * （高于门幅的片后置 minY 生效 = 贴底）、minX<0 右推；x 右界**不钳**（拖出原布局
 * 右界自由，保存时 width_mm = ceil(包络) 双向伸缩）。gate = manifest.gate_mm。
 *
 * mirror（edit-keyboard US-003 起，缺省 false 零回归）：镜像片世界 bbox 与非镜像不同
 * （x 取负），钳制必须按镜像几何算；US-005 键盘变换路径同参复用。
 */
function clampPlacement(basePoly: Polygon, rot: number, tr: Pt, gate: number, mirror = false): Pt {
  const world = transformPolygon(basePoly, rot, tr, mirror);
  const b = bboxOf(world);
  let tx = tr[0];
  let ty = tr[1];
  if (b.minX < 0) tx += -b.minX;
  if (b.maxY > gate) ty -= b.maxY - gate;
  if (b.minY < 0) ty += -b.minY;
  return [tx, ty];
}

/**
 * 绕 pivot 旋转 dAng 后的等价 placement translation（片原地转不漂移）：
 *   q = R(θ)p + t → q' = pivot + R(dθ)(q − pivot) = R(θ+dθ)p + [pivot + R(dθ)(t − pivot)]
 */
function pivotTranslate(pivot: Pt, dAngDeg: number, tr: Pt): Pt {
  const r = (dAngDeg * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  const dx = tr[0] - pivot[0];
  const dy = tr[1] - pivot[1];
  return [pivot[0] + dx * c - dy * s, pivot[1] + dx * s + dy * c];
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
 * 单片 5 层按 rot/tr/mirror 更新（与 NestSVG frame 渲染逐属性同款；mode 决定 4 层工艺
 * 显隐）。mirror（edit-keyboard US-003）：5 层 points/端点全部 x 取负（pointsStr/
 * transformPt 第 4 参 —— 局部 x 翻转 → 旋转 → 平移）。
 */
function applyPlacement(
  entry: PieceEntry,
  rot: number,
  tr: Pt,
  mode: EditViewMode,
  mirror: boolean,
): void {
  const showCraft = mode === 'full';
  // layer1 毛版 polygon（恒显 —— 毛板模式唯一可见层）
  entry.el.setAttribute('points', pointsStr(entry.piece.polygon, rot, tr, mirror));
  entry.el.style.display = '';
  // layer14 净版 polygon
  if (entry.netEl && entry.piece.net_polygon) {
    entry.netEl.setAttribute('points', pointsStr(entry.piece.net_polygon, rot, tr, mirror));
    entry.netEl.style.display = showCraft ? '' : 'none';
  }
  // layer8 内部线 polyline 列表
  const internalLines = entry.piece.internal_lines ?? [];
  for (let i = 0; i < entry.internalEls.length; i++) {
    const lineEl = entry.internalEls[i];
    const line = internalLines[i];
    if (!line) continue;
    lineEl.setAttribute('points', pointsStr(line, rot, tr, mirror));
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
    const a = transformPt([px - nx * half, py - ny * half], rot, tr, mirror);
    const b = transformPt([px + nx * half, py + ny * half], rot, tr, mirror);
    notchEl.setAttribute('x1', String(a[0]));
    notchEl.setAttribute('y1', String(a[1]));
    notchEl.setAttribute('x2', String(b[0]));
    notchEl.setAttribute('y2', String(b[1]));
    notchEl.style.display = showCraft ? '' : 'none';
  }
  // layer7 布纹线 line（随片同步旋转 —— 旋转偏离角指标的物理依据）
  if (entry.grainEl && entry.piece.grain_line) {
    const [x1, y1, x2, y2] = entry.piece.grain_line;
    const a = transformPt([x1, y1], rot, tr, mirror);
    const b = transformPt([x2, y2], rot, tr, mirror);
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
 * mirror=true（edit-keyboard US-003 起，缺省 false 零回归）：旋转前一行式 x 取负，
 * 与 pointsStr mirror 分支同公式。
 */
function transformPt(
  pt: [number, number],
  rot: number,
  tr: [number, number],
  mirror = false,
): [number, number] {
  const r = (rot * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  const x = mirror ? -pt[0] : pt[0];
  const y = pt[1];
  const rx = Math.round((x * c - y * s + tr[0]) * 100) / 100;
  const ry = Math.round((x * s + y * c + tr[1]) * 100) / 100;
  return [rx, ry];
}
