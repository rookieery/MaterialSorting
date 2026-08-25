// PerTypeOverridesModal —— 高级配置：设置算法参数弹窗（标题 2026-08-22 前为「每裁片覆盖」；
// US-018；裁片编号化重构
// US-003 起 V03_PTYPES 固定 10 中文列删除，列集 = /api/ptypes representatives 键
// —— 裁片 g 码，动态随当前母版。2026-08-18 回退 US-004 矩阵化（行=码号 × 列=g 码
// 逐格 d/tol）：重合/旋转是片型工艺属性、与码号无关，按码号细分无业务差异，
// 收敛回 per_type 单级 {g 码: {d, tol}}，与后端 build_instance 同步回单级命中）。
//
// 「布局设置」分区（表格上方独立分区，draft+confirm 同表格语义）：
//   - 子标题「开启腰头成带」+ 勾选框；右侧子标题「腰头编号」+ 下拉框（值域 = 表格
//     同源 orderedLabels = /api/ptypes reps ∪ values 已配置键；fetch 失败降级纯文字
//     列表 —— select option 本就是文字，缩略图缺席不阻塞选择）；
//   - 选中 g 码后右侧挂**成带形态预览**缩略图（2026-08-24：原「原始代表裁片」
//     缩略图与下方裁片设置表格同源同图，纯冗余已删）—— POST /api/band-preview
//     （后端 build_band_plan 同一真相源，v2 链构造无 RNG ⇒ 预览 = 求解时带的精确
//     形态）；三态：loading 占位 / ok → BandPreviewSVG 尺码着色缩略 / error →
//     可读错误文案（成带失败前置到选码时刻，如「填充率 13% < 下限」）。点击放大
//     开**第三层** band-zoom modal（showLabels 尺码标注 + 统计行，本地 state 控制，
//     ESC 独立消费 —— 与 previewLabel 双层约定同款双守卫）；
//   - 未勾选时下拉 disabled；确定/遮罩/ESC/✕ 写回 form.band_*（2026-08-22 起
//     关闭即保存，见下），「取消」丢弃 band 草稿（与 per_type 同一约定）；
//   - US-004 第二行「起始端成套前后幅」：勾选 + 前幅/后幅两 g 码下拉（band 下拉
//     同模式）；2026-08-25 起两下拉后的展示与 band 行同款换成**组合形态预览**
//     （POST /api/prefix-preview：前×2 + 后×2 同码 interleave 竖排贴靠 = 求解时
//     PS_ 组合片的精确形态）—— 原「两码各一张 80×80 原始裁片缩略」与下方裁片
//     设置表格同源同图，纯冗余已删；勾选且两码均空时**默认预选 parse doc 面积
//     最大两片**（决策⑤，5336 = g02/g03，用户可改；defaultPrefixLabels shoelace
//     口径）；说明文案「满足 2+2 的尺码将自动选取」（资格码后端 seeded 随机选取、
//     不出 UI —— 决策②）；无任何资格码时警示「当前数量无 2+2 资格码」
//     （prefixEligibleSizes 与后端 _parse_prefix 同口径本地预检，不阻塞 band
//     使用，权威拦截在后端）；front==back 时同位警示。
//     确定写回 form.prefix_*，与 band 草稿同一 saveAndClose 通道。
//
// 声明式受控 Portal（参考 PieceZoomModal）：
//   - 订阅 controlPanelStore.modal === 'per_type' 自显隐；null 时不挂 DOM。
//   - Portal 到 document.body（不被 .page overflow/display:none 裁切）。
//   - 关闭交互（AC#10）：确定 / 取消 / ✕ 按钮 / 遮罩 mousedown / ESC。
//     2026-08-22 起**关闭即保存**：确定/遮罩/ESC/✕ 四通道统一「clamp 全格 → 回写
//     per_type + band → 关闭」（saveAndClose 单点）；唯一丢弃通道是显式「取消」
//     —— 避免误触空白丢工作，也避免「点 ✕ 丢、点空白留」的不对称语义。
//
// 表格布局（D10 / AC#3；2026-08-17 编号化 + 全局上限改造）：
//   - thead 列 = 当前母版 g 码并集（/api/ptypes 键 ∪ form.per_type 已配置键），按
//     compareByLabel 数值序（与上传预览 QtyMatrix 列序一致口径）。每列缩略图 64×64 +
//     g 码徽章 —— 复用上传预览 QtyMatrix 的 .qty-label-badge。
//   - tbody 行 = 2 行：重合 input（0–10mm）+ 旋转 input（0–45°）；全局上限不按片型；
//     blur 规整到 [0, max]。
//   - hover / aria 只报 g 码：`${g码}-放大预览`。
//   - 表格 overflow-x:auto（多列窄屏溢出）。reps 未到位（loading / 未 commit / fetch
//     失败）→ 列集退回 values 已配置键（可能为空 → 仅行头，不阻塞）。
//
// 缩略图数据源（D10 / AC#4）：挂载时 fetch GET /api/ptypes（US-020）取 representatives
// （键 = g 码），存本地 state；loading 占位「…」；fetch 失败降级为空 reps（不阻塞）。
// 缩略图用 PiecePreviewSVG compact 模式渲染 representatives[label]，layer-aware（D11）。
//
// 草稿 + 确定模式（AC#5）：打开时从 form.per_type 读初值进本地 draft（已配置键保留，
// 空值预填 '0'/'0'）；fetch 到位的 g 码未配置格渲染空串（= 继承默认 0，placeholder 提示）；
// 编辑仅改 draft；关闭即保存（2026-08-22）：确定/遮罩/ESC/✕ 回写前对全格 clamp
// （mousedown 先于焦点转移，正在编辑 input 的 onBlur 规整未必已触发），「取消」
// 仅关 modal、草稿丢弃。
//
// 裁片放大预览（AC#7）：点击 thead 缩略图触发 openPreviewLabel(label)；
// PtypePreviewModal 叠在本模态之上（z-index 更高）；关闭预览时本模态草稿保留。
//
// 关键不变量（AC#10）：两层 modal 各自独立 ESC ——
//   - 本组件 ESC listener 内判 previewLabel===null 且未被消费才关闭，避免预览打开
//     时双层同时关闭（预览 listener 消费 ESC 时 stopImmediatePropagation，防监听
//     注册顺序翻转后 previewLabel 已被置 null 的窗口）。
//   - PtypePreviewModal 自己的 ESC listener 始终只关 previewLabel。
//
// 不引入 CSS 框架；.per-type-overlay / .per-type-modal / .per-type-table / .ptype-thumb
// / .per-type-band 分区全部沿用 style.css 暗背景 #26282e + #2ea06c 同色系（与
// PieceZoomModal 一致）。

import { useEffect, useMemo, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { MAX_OVERLAP_MM, MAX_ROTATION_TOL_DEG } from '../../constants/v03';
import {
  collectPerType,
  defaultPrefixLabels,
  prefixEligibleSizes,
  serializeQuantities,
  type PerTypeFormValue,
} from '../../lib/params';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { useQtyStore } from '../../store/qtyStore';
import { useUploadStore } from '../../store/uploadStore';
import type {
  BandPreviewPayload,
  BandPreviewResponse,
  PrefixPreviewPayload,
  PrefixPreviewResponse,
} from '../../types/band';
import type { ParsedPiece } from '../../types/parsed';
import type { PtypeRepresentative, PtypesResponse } from '../../types/ptype';
import { BandPreviewSVG } from './BandPreviewSVG';
import { PiecePreviewSVG } from '../preview/PiecePreviewSVG';

/** ≤ 字符（U+2264）—— 输入框 placeholder 上限提示。 */
const LE = '≤';

/**
 * g 码比较器（g01<g02<…<g99<g100：先长度再字典序）。g 码两位零填充下
 * 「先长度再字典序」= 数值序（g100 三位自然排后），**勿去零填充**（'g10'<'g9' 字典序
 * 会错）。列序与 QtyMatrix 列头（最小码 pieces 顺序）口径一致。
 */
function compareByLabel(a: string, b: string): number {
  if (a.length !== b.length) return a.length - b.length;
  return a < b ? -1 : a > b ? 1 : 0;
}

/** 把草稿字符串规整到 [0, max]：负值/超限收边；空串保留（= 继承两档，语义同 0）。 */
function clampDraft(v: string, max: number): string {
  const t = v.trim();
  if (t === '') return v;
  const n = parseFloat(t);
  if (Number.isNaN(n)) return v;
  return String(Math.min(Math.max(n, 0), max));
}

/**
 * 把 form.per_type 已配置键展开为 draft（PerTypeFormValue）。
 * 空值（d/tol 全空串）→ 预填 '0'/'0'（统一默认 0）；非空 → 保留用户已填值。
 * reps 到位后新增的 g 码不在 draft（渲染层兜底空串 = 继承默认 0，placeholder 提示）。
 */
function initializeDraft(values: Record<string, PerTypeFormValue>): Record<string, PerTypeFormValue> {
  const draft: Record<string, PerTypeFormValue> = {};
  for (const label of Object.keys(values)) {
    const v = values[label];
    if (v && (v.d.trim() !== '' || v.tol.trim() !== '')) {
      draft[label] = { d: v.d, tol: v.tol };
    } else {
      draft[label] = { d: '0', tol: '0' };
    }
  }
  return draft;
}

/** 把 PtypeRepresentative 扩展为 PiecePreviewSVG 接受的 ParsedPiece 形状（compact 不渲染 label）。 */
function repToPiece(rep: PtypeRepresentative): ParsedPiece {
  return {
    label: '', // compact 模式不渲染 label，空串安全
    polygon: rep.polygon,
    internal_lines: rep.internal_lines ?? [],
    notches: rep.notches ?? [],
    net_polygon: rep.net_polygon ?? [],
    grain_line: rep.grain_line ?? null,
  };
}

/** 「布局设置」分区草稿/回写形状（= form.band_* 组）。 */
export interface BandFormValue {
  enabled: boolean;
  label: string;
}

/** US-004「布局设置」prefix 组草稿/回写形状（= form.prefix_* 组）。 */
export interface PrefixFormValue {
  enabled: boolean;
  front: string;
  back: string;
}

export interface PerTypeOverridesModalProps {
  /** 每裁片（g 码）的 d/tol 输入字符串（来自 ControlPanel form.per_type）。 */
  values: Record<string, PerTypeFormValue>;
  /** 确定时回写 ControlPanel form.per_type。 */
  onChange: (next: Record<string, PerTypeFormValue>) => void;
  /** 布局设置初值（form.band_*；mount 时读入草稿）。 */
  band: BandFormValue;
  /** 关闭即保存时回写 ControlPanel form.band_*（确定/遮罩/ESC/✕；「取消」丢弃）。 */
  onBandChange: (next: BandFormValue) => void;
  /** US-004 布局设置初值（form.prefix_*；mount 时读入草稿）。 */
  prefix: PrefixFormValue;
  /** US-004 关闭即保存时回写 ControlPanel form.prefix_*（与 band 同一通道）。 */
  onPrefixChange: (next: PrefixFormValue) => void;
  /** 当前勾选码号（过滤 null；成带预览 payload sizes —— 与 StartPayload 同口径）。 */
  sizes: number[];
  /** 幅宽 mm（parseGate；成带预览带高守卫与 solve 同口径）。 */
  gateMm: number;
}

export function PerTypeOverridesModal({
  values,
  onChange,
  band,
  onBandChange,
  prefix,
  onPrefixChange,
  sizes,
  gateMm,
}: PerTypeOverridesModalProps): JSX.Element | null {
  const modal = useControlPanelStore((s) => s.modal);
  const closeModal = useControlPanelStore((s) => s.closeModal);
  const openPreviewLabel = useControlPanelStore((s) => s.openPreviewLabel);

  if (modal !== 'per_type') return null;

  return (
    <PerTypeOverridesModalInner
      key="per-type-modal"
      values={values}
      onChange={onChange}
      band={band}
      onBandChange={onBandChange}
      prefix={prefix}
      onPrefixChange={onPrefixChange}
      sizes={sizes}
      gateMm={gateMm}
      onClose={closeModal}
      onOpenPreviewLabel={openPreviewLabel}
    />
  );
}

interface InnerProps {
  values: Record<string, PerTypeFormValue>;
  onChange: (next: Record<string, PerTypeFormValue>) => void;
  band: BandFormValue;
  onBandChange: (next: BandFormValue) => void;
  prefix: PrefixFormValue;
  onPrefixChange: (next: PrefixFormValue) => void;
  sizes: number[];
  gateMm: number;
  onClose: () => void;
  onOpenPreviewLabel: (label: string) => void;
}

function PerTypeOverridesModalInner({
  values,
  onChange,
  band,
  onBandChange,
  prefix,
  onPrefixChange,
  sizes,
  gateMm,
  onClose,
  onOpenPreviewLabel,
}: InnerProps): JSX.Element {
  // 草稿：mount 时从 values 已配置键初始化。key 强制每次 open 重建（避免残留）。
  const [draft, setDraft] = useState<Record<string, PerTypeFormValue>>(() => initializeDraft(values));

  // 布局设置草稿（同一 mount 生命周期，saveAndClose 是唯一回写路径）。
  const [bandEnabled, setBandEnabled] = useState<boolean>(band.enabled);
  const [bandLabel, setBandLabel] = useState<string>(band.label);

  // US-004 prefix 草稿（band 同一 mount 生命周期 + saveAndClose 通道）。
  const [prefixEnabled, setPrefixEnabled] = useState<boolean>(prefix.enabled);
  const [prefixFront, setPrefixFront] = useState<string>(prefix.front);
  const [prefixBack, setPrefixBack] = useState<string>(prefix.back);

  // 成带形态预览（2026-08-24）：bandLabel 变化（含 mount）时 POST /api/band-preview。
  // 三态：loading / {ok:true,...} / {ok:false,error}（失败也 200 —— 选错 g 码是预期内
  // 常态，单条路径渲染错误文案）。quantities/sizes 取 fetch 时刻快照（modal 遮罩挡住
  // 其他 UI，打开期间不会变）；per_type 用本弹窗草稿（collectPerType 与 solve 同源
  // —— 预览的 d_g 与求解一致，WYSIWYG）。d/tol 编辑**不**触发重取（erode 深度
  // 0.4mm 级视觉差异，重取噪音大于价值）。
  const [bandPreview, setBandPreview] = useState<BandPreviewResponse | null>(null);
  const [bandPreviewLoading, setBandPreviewLoading] = useState<boolean>(false);
  // 成带放大层（第三层 modal，本地 state —— 不动 controlPanelStore 契约；
  // 叠序：per_type(1100) < ptype-preview(1200) < band-zoom(1300)，三者互斥打开）。
  const [bandZoomOpen, setBandZoomOpen] = useState<boolean>(false);

  // 前缀组合形态预览（2026-08-25，band 预览同款）：front/back 变化（含 mount）时
  // POST /api/prefix-preview。三态同 band（loading / ok / error 文案）；两码缺一
  // 或相同（本地已另有警示）→ 清空不发。quantities/sizes/draft 取 fetch 时刻
  // 快照（同 band 口径，d/tol 编辑不触发重取）。
  const [prefixPreview, setPrefixPreview] = useState<PrefixPreviewResponse | null>(null);
  const [prefixPreviewLoading, setPrefixPreviewLoading] = useState<boolean>(false);
  // 前缀放大层（与 band-zoom 同层互斥 —— 打开一个关另一个，单顶层约定）。
  const [prefixZoomOpen, setPrefixZoomOpen] = useState<boolean>(false);

  useEffect(() => {
    if (bandLabel === '') {
      setBandPreview(null);
      setBandPreviewLoading(false);
      setBandZoomOpen(false);
      return;
    }
    let cancelled = false;
    setBandPreviewLoading(true);
    const payload: BandPreviewPayload = {
      band: { enabled: true, label: bandLabel },
      sizes,
      quantities: serializeQuantities(useQtyStore.getState().quantities, sizes),
      per_type: collectPerType(draft),
      gate_mm: gateMm,
    };
    fetch('/api/band-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json() as Promise<BandPreviewResponse>)
      .then((data) => {
        if (cancelled) return;
        setBandPreview(data);
        setBandPreviewLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setBandPreview({ ok: false, error: '成带预览不可用（网络错误）' });
        setBandPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // 仅 bandLabel 触发重取：draft/sizes/gateMm/quantities 均取 fetch 时刻快照
    //（见上注释；显式 omit 避免 exhaustive-deps 逼出重取噪音）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bandLabel]);

  // 前缀组合形态预览（band 预览同款三态；两码缺一/相同 → 清空不发）。
  useEffect(() => {
    setPrefixZoomOpen(false);
    if (prefixFront === '' || prefixBack === '' || prefixFront === prefixBack) {
      setPrefixPreview(null);
      setPrefixPreviewLoading(false);
      return;
    }
    let cancelled = false;
    setPrefixPreviewLoading(true);
    const payload: PrefixPreviewPayload = {
      prefix: { enabled: true, front: prefixFront, back: prefixBack },
      sizes,
      quantities: serializeQuantities(useQtyStore.getState().quantities, sizes),
      per_type: collectPerType(draft),
      gate_mm: gateMm,
    };
    fetch('/api/prefix-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json() as Promise<PrefixPreviewResponse>)
      .then((data) => {
        if (cancelled) return;
        setPrefixPreview(data);
        setPrefixPreviewLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setPrefixPreview({ ok: false, error: '前缀预览不可用（网络错误）' });
        setPrefixPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // 仅 front/back 触发重取（band 同款快照口径 + eslint omit）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefixFront, prefixBack]);

  // 放大层 ESC（band-zoom / prefix-zoom 共用，独立于 per_type / previewLabel 两层）：
  // 本层打开时消费 ESC 并 stopImmediatePropagation（顶层消费信号，与
  // PtypePreviewModal 同款双守卫的另一半 —— 底层 listener 另有 zoom 闭包早退，
  // 两道防线不依赖注册顺序）。两放大层互斥打开（打开一个关另一个），双关无歧义。
  useEffect(() => {
    if (!bandZoomOpen && !prefixZoomOpen) return;
    function onZoomKey(e: KeyboardEvent): void {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopImmediatePropagation();
      setBandZoomOpen(false);
      setPrefixZoomOpen(false);
    }
    window.addEventListener('keydown', onZoomKey);
    return () => window.removeEventListener('keydown', onZoomKey);
  }, [bandZoomOpen, prefixZoomOpen]);

  // 缩略图数据：mount 时 fetch GET /api/ptypes（键 = g 码）；loading / error 三态。
  // fetch 失败降级为 {} → 列集退回 values 已配置键（不阻塞重合/旋转配置，AC#4）。
  const [representatives, setRepresentatives] = useState<Record<string, PtypeRepresentative>>({});
  const [loadingReps, setLoadingReps] = useState<boolean>(true);

  // 列集 = reps 键（当前母版 g 码并集）∪ values 已配置键（fetch 失败时保留已配置项），
  // 按 compareByLabel 数值序。reps 未到位时先渲染 values 键，fetch 成功后扩列。
  const orderedLabels: string[] = useMemo(() => {
    const keys = new Set<string>(Object.keys(representatives));
    for (const k of Object.keys(values)) keys.add(k);
    return Array.from(keys).sort(compareByLabel);
  }, [representatives, values]);

  useEffect(() => {
    let cancelled = false;
    setLoadingReps(true);
    fetch('/api/ptypes')
      .then((r) => r.json() as Promise<PtypesResponse>)
      .then((data) => {
        if (cancelled) return;
        setRepresentatives(data.representatives ?? {});
        setLoadingReps(false);
      })
      .catch(() => {
        if (cancelled) return;
        // 降级：空 representatives，列集退回 values 键（不阻塞重合/旋转配置）
        setRepresentatives({});
        setLoadingReps(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 下拉值域：表格同源 orderedLabels ∪ 当前选中 g 码 —— 已确认过的 label 在
  // reps/values 均缺席（fetch 失败 / values 未配置）时仍显示为选中项（受控 select 的
  // value 缺 option 会显示空白，band 状态不可见）。
  const bandOptions = useMemo(() => {
    if (bandLabel !== '' && !orderedLabels.includes(bandLabel)) {
      return [...orderedLabels, bandLabel].sort(compareByLabel);
    }
    return orderedLabels;
  }, [orderedLabels, bandLabel]);

  // US-004 prefix 前幅/后幅下拉值域（band 同款：orderedLabels ∪ 当前选中项）。
  const prefixFrontOptions = useMemo(() => {
    if (prefixFront !== '' && !orderedLabels.includes(prefixFront)) {
      return [...orderedLabels, prefixFront].sort(compareByLabel);
    }
    return orderedLabels;
  }, [orderedLabels, prefixFront]);
  const prefixBackOptions = useMemo(() => {
    if (prefixBack !== '' && !orderedLabels.includes(prefixBack)) {
      return [...orderedLabels, prefixBack].sort(compareByLabel);
    }
    return orderedLabels;
  }, [orderedLabels, prefixBack]);

  // US-004 资格码本地预检（qtyStore 响应式订阅 —— 数量矩阵在弹窗遮罩下不会变，
  // 但 hydrate 时序可能后于弹窗打开；与后端 _parse_prefix 同口径）：
  // front==back 优先警示（后端「须为不同 g 码」前置），否则无资格码警示（不阻塞
  // band 使用 / 不阻塞确定 —— 权威拦截在后端结构化 error）。
  const quantities = useQtyStore((s) => s.quantities);
  const prefixSame = prefixEnabled && prefixFront !== '' && prefixBack !== '' && prefixFront === prefixBack;
  const prefixNoEligible =
    prefixEnabled &&
    prefixFront !== '' &&
    prefixBack !== '' &&
    !prefixSame &&
    prefixEligibleSizes(sizes, quantities, prefixFront, prefixBack).length === 0;

  /** US-004 勾选切换：勾上且前/后幅均空时默认预选 parse doc 面积最大两片（决策⑤）。
   * 已有选择（用户改过 / 上次确认值）不覆盖 —— 启发式只是缺省建议。 */
  function handlePrefixToggle(next: boolean): void {
    setPrefixEnabled(next);
    if (next && prefixFront === '' && prefixBack === '') {
      const def = defaultPrefixLabels(useUploadStore.getState().doc);
      if (def) {
        setPrefixFront(def.front);
        setPrefixBack(def.back);
      }
    }
  }

  // ESC 监听（AC#10）：previewLabel !== null 时由 PtypePreviewModal 处理 ESC、
  // bandZoomOpen / prefixZoomOpen 时由放大层处理（三层独立）。本 listener 仅在
  // 两层放大均关闭时保存并关 modal，避免多层同时关闭。
  // 双守卫防监听顺序翻转（本组件重渲染会把 listener 挪到注册队尾，放大层的
  // listener 可能先执行）：① 顺序在放大层前 → zoom/previewLabel 仍在场，
  // 早退；② 顺序在放大层后 → 放大层 listener 已 stopImmediatePropagation（顶层
  // 消费信号），本 listener 不再收到；defaultPrevented 早退为兜底。
  // （listener 每次渲染重注册无 deps —— zoom 闭包恒为最新值。）
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key !== 'Escape') return;
      // 多层 modal：放大层打开时 ESC 只关放大层，不关底层高级配置（AC#10 关键约定）
      if (bandZoomOpen || prefixZoomOpen) return;
      if (useControlPanelStore.getState().previewLabel !== null) return;
      if (e.defaultPrevented) return;
      e.preventDefault();
      saveAndClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  function updateDraft(label: string, key: 'd' | 'tol', v: string): void {
    setDraft((prev) => ({
      ...prev,
      [label]: { d: prev[label]?.d ?? '', tol: prev[label]?.tol ?? '', [key]: v },
    }));
  }

  /** 保存草稿并关闭（确定 / 遮罩 / ESC / ✕ 四通道共用 —— 关闭即保存）。
   * 回写前对全格 clamp：遮罩 mousedown 与 ESC 都可能先于正在编辑 input 的
   * onBlur 规整发生（mousedown 事件先于焦点转移，ESC 不转移焦点），不 clamp
   * 会把 '99' 这类未规整值写回 —— 等价于替未触发的 blur 补一次规整。 */
  function saveAndClose(): void {
    const clamped: Record<string, PerTypeFormValue> = {};
    for (const [label, v] of Object.entries(draft)) {
      clamped[label] = {
        d: clampDraft(v.d, MAX_OVERLAP_MM),
        tol: clampDraft(v.tol, MAX_ROTATION_TOL_DEG),
      };
    }
    onChange(clamped);
    // band 草稿一并回写（未勾选时 label 原样保留 —— collectBand 对 enabled=false
    // 恒 null，重新勾选时上次选择不丢）。
    onBandChange({ enabled: bandEnabled, label: bandLabel });
    // prefix 草稿同通道回写（未勾选时 front/back 原样保留 —— collectPrefix 对
    // enabled=false 恒 null，重新勾选时上次选择不丢）。
    onPrefixChange({ enabled: prefixEnabled, front: prefixFront, back: prefixBack });
    onClose();
  }

  function handleOverlayMouseDown(e: React.MouseEvent): void {
    // 仅当 mousedown 落在 overlay 自身（不是冒泡上来的子元素）时保存并关闭
    if (e.target === e.currentTarget) saveAndClose();
  }

  function handleModalMouseDown(e: React.MouseEvent): void {
    // modal 内 mousedown 不冒泡到 overlay 触发关闭
    e.stopPropagation();
  }

  function handleThumbClick(label: string): void {
    onOpenPreviewLabel(label);
  }

  function handleZoomOverlayMouseDown(e: React.MouseEvent): void {
    if (e.target === e.currentTarget) {
      setBandZoomOpen(false);
      setPrefixZoomOpen(false);
    }
  }

  function handleZoomModalMouseDown(e: React.MouseEvent): void {
    e.stopPropagation();
  }

  return (
    <>
      {createPortal(
      <div
        className="per-type-overlay"
        onMouseDown={handleOverlayMouseDown}
        data-testid="per-type-overlay"
      >
      <div
        className="per-type-modal"
        role="dialog"
        aria-modal="true"
        aria-label="高级配置：设置算法参数"
        onMouseDown={handleModalMouseDown}
      >
        <div className="per-type-head">
          <span className="per-type-title">高级配置：设置算法参数</span>
          <button
            type="button"
            className="per-type-close"
            aria-label="关闭"
            onClick={saveAndClose}
            data-testid="per-type-close"
          >
            ✕
          </button>
        </div>

        {/* 布局设置分区：表格上方独立分区（draft + 关闭即保存同表格语义，仅「取消」
            丢弃 band 草稿）。值域 = 表格同源 orderedLabels（reps ∪ values 键，
            fetch 失败降级纯文字 option 列表不阻塞）；未勾选禁用下拉。 */}
        <div className="per-type-band" data-testid="per-type-band">
          <div className="per-type-band-title">布局设置</div>
          <div className="per-type-band-row">
            <label className="per-type-band-check">
              <input
                type="checkbox"
                checked={bandEnabled}
                onChange={(e) => setBandEnabled(e.target.checked)}
                data-testid="band-enabled"
              />
              <span>开启腰头成带</span>
            </label>
            <div className="per-type-band-select-wrap">
              <span className="per-type-band-subhead">腰头编号</span>
              <select
                className="per-type-band-select"
                value={bandLabel}
                onChange={(e) => setBandLabel(e.target.value)}
                disabled={!bandEnabled}
                data-testid="band-label-select"
                aria-label="腰头编号"
              >
                <option value="">请选择…</option>
                {bandOptions.map((label) => (
                  <option key={label} value={label}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            {/* 成带形态预览（2026-08-24 替换原「原始代表裁片」缩略图 —— 与下方裁片
                设置表格同源同图，纯冗余）。三态：loading 占位 / ok → 尺码着色缩略
                （点击开 band-zoom 放大层）/ error → 可读错误文案（成带失败前置）。
                宽幅带形 → 宽缩略（.per-type-band-thumb--band 200×80）。 */}
            {bandLabel !== '' && bandPreviewLoading ? (
              <div
                className="per-type-band-thumb per-type-band-thumb-empty"
                data-testid="band-thumb-loading"
              >
                成带预览…
              </div>
            ) : bandLabel !== '' && bandPreview?.ok ? (
              <button
                type="button"
                className="per-type-band-thumb per-type-band-thumb--band"
                onClick={() => {
                  setPrefixZoomOpen(false);
                  setBandZoomOpen(true);
                }}
                aria-label={`${bandLabel}-成带预览放大`}
                title={`${bandLabel}-成带预览放大`}
                data-testid={`band-thumb-${bandLabel}`}
              >
                <BandPreviewSVG
                  members={bandPreview.members ?? []}
                  outline={bandPreview.outline ?? null}
                  pad={8}
                />
                <span className="qty-label-badge">{bandLabel}</span>
              </button>
            ) : bandLabel !== '' ? (
              <div
                className="per-type-band-error"
                data-testid="band-thumb-error"
                title={bandPreview?.error ?? ''}
              >
                {bandPreview?.error ?? '成带预览不可用'}
              </div>
            ) : null}
          </div>

          {/* US-004「起始端成套前后幅」第二行：band 两键之后追加（band 下拉同模式：
              勾选 + 前幅/后幅两下拉）。2026-08-25 起两下拉后不再挂单片原始缩略
              （与裁片设置表格同源同图，纯冗余），改挂**组合形态预览**（POST
              /api/prefix-preview，求解时 PS_ 组合片精确形态，band 预览同款三态 +
              点击开 prefix-zoom 放大层）。勾上且两码均空时默认预选 parse doc 面积
              最大两片（handlePrefixToggle）；未勾选两下拉 disabled。
              说明文案「满足 2+2 的尺码将自动选取」（资格码后端 seeded 随机，决策②）。 */}
          <div className="per-type-band-row" data-testid="per-type-prefix-row">
            <label className="per-type-band-check">
              <input
                type="checkbox"
                checked={prefixEnabled}
                onChange={(e) => handlePrefixToggle(e.target.checked)}
                data-testid="prefix-enabled"
              />
              <span>起始端成套前后幅</span>
            </label>
            <div className="per-type-band-select-wrap">
              <span className="per-type-band-subhead">前幅</span>
              <select
                className="per-type-band-select"
                value={prefixFront}
                onChange={(e) => setPrefixFront(e.target.value)}
                disabled={!prefixEnabled}
                data-testid="prefix-front-select"
                aria-label="前幅 g 码"
              >
                <option value="">请选择…</option>
                {prefixFrontOptions.map((label) => (
                  <option key={label} value={label}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div className="per-type-band-select-wrap">
              <span className="per-type-band-subhead">后幅</span>
              <select
                className="per-type-band-select"
                value={prefixBack}
                onChange={(e) => setPrefixBack(e.target.value)}
                disabled={!prefixEnabled}
                data-testid="prefix-back-select"
                aria-label="后幅 g 码"
              >
                <option value="">请选择…</option>
                {prefixBackOptions.map((label) => (
                  <option key={label} value={label}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            {/* 组合形态预览（2026-08-25 替换前/后幅两张单片缩略 —— band 预览同款
                三态：loading 占位 / ok → BandPreviewSVG 组合形态（点击开 prefix-zoom
                放大层）/ error → 可读错误文案（构造失败前置到选码时刻）。竖排簇 →
                高缩略（.per-type-band-thumb--prefix）。两码缺一/相同时不渲染。 */}
            {prefixFront !== '' && prefixBack !== '' && prefixFront !== prefixBack && prefixPreviewLoading ? (
              <div
                className="per-type-band-thumb per-type-band-thumb-empty per-type-band-thumb-empty--prefix"
                data-testid="prefix-thumb-loading"
              >
                组合预览…
              </div>
            ) : prefixFront !== '' && prefixBack !== '' && prefixFront !== prefixBack && prefixPreview?.ok ? (
              <button
                type="button"
                className="per-type-band-thumb per-type-band-thumb--prefix"
                onClick={() => {
                  setBandZoomOpen(false);
                  setPrefixZoomOpen(true);
                }}
                aria-label={`${prefixFront}+${prefixBack}-前缀组合预览放大`}
                title={`${prefixFront}+${prefixBack}-前缀组合预览放大`}
                data-testid={`prefix-thumb-${prefixFront}+${prefixBack}`}
              >
                <BandPreviewSVG
                  members={prefixPreview.members ?? []}
                  outline={prefixPreview.outline ?? null}
                  pad={8}
                />
                <span className="qty-label-badge">{prefixFront}+{prefixBack}</span>
              </button>
            ) : prefixFront !== '' && prefixBack !== '' && prefixFront !== prefixBack ? (
              <div
                className="per-type-band-error"
                data-testid="prefix-thumb-error"
                title={prefixPreview?.error ?? ''}
              >
                {prefixPreview?.error ?? '前缀预览不可用'}
              </div>
            ) : null}
          </div>
          <div className="per-type-prefix-note" data-testid="per-type-prefix-note">
            满足 2+2 的尺码将自动选取（该码前幅 ×2 + 后幅 ×2 竖排贴靠布头第一列）
          </div>
          {/* 本地预检警示（不阻塞确定 —— 权威拦截在后端 _parse_prefix 结构化 error）：
              front==back 优先，其次无资格码（指路数量矩阵，与后端文案同向）。 */}
          {prefixSame ? (
            <div className="per-type-prefix-warn" data-testid="per-type-prefix-warn">
              前幅与后幅须为不同 g 码（前/后幅各一），请重新选择
            </div>
          ) : prefixNoEligible ? (
            <div className="per-type-prefix-warn" data-testid="per-type-prefix-warn">
              当前数量无 2+2 资格码 —— 请在数量矩阵把所选码前后幅配成 2+2
            </div>
          ) : null}
        </div>

        {/* 裁片设置分区标题（2026-08-22）：与上方「布局设置」同款 .per-type-band-title
            （12px + #2ea06c 左缘竖条）；modal 是 flex column + gap:12px，独立标题自动
            获得与 band 分区的间距，零新 CSS。 */}
        <div className="per-type-band-title" data-testid="per-type-table-title">
          裁片设置
        </div>
        <div className="per-type-table-wrap">
          <table className="per-type-table">
            <thead>
              <tr>
                <th className="per-type-rowhead" scope="col">
                  裁片
                </th>
                {orderedLabels.map((label) => {
                  const rep = representatives[label];
                  return (
                    <th key={label} scope="col" className="ptype-col">
                      <button
                        type="button"
                        className="ptype-thumb"
                        onClick={() => handleThumbClick(label)}
                        aria-label={`${label}-放大预览`}
                        title={`${label}-放大预览`}
                        data-testid={`ptype-thumb-${label}`}
                        disabled={!rep}
                      >
                        {rep ? (
                          <PiecePreviewSVG piece={repToPiece(rep)} compact />
                        ) : (
                          <span className="ptype-thumb-placeholder" aria-hidden="true">
                            {loadingReps ? '…' : label.slice(0, 1)}
                          </span>
                        )}
                      </button>
                      {/* g 码徽章与上传预览 QtyMatrix 列头同款同口径（键即 g 码） */}
                      <span className="qty-label-badge">{label}</span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th className="per-type-rowhead" scope="row">
                  重合
                </th>
                {orderedLabels.map((label) => {
                  const v = draft[label] ?? { d: '', tol: '' };
                  return (
                    <td key={label}>
                      <input
                        type="number"
                        min={0}
                        max={MAX_OVERLAP_MM}
                        step={0.5}
                        placeholder={`d${LE}${MAX_OVERLAP_MM}`}
                        value={v.d}
                        onChange={(e) => updateDraft(label, 'd', e.target.value)}
                        onBlur={(e) => updateDraft(label, 'd', clampDraft(e.target.value, MAX_OVERLAP_MM))}
                        data-testid={`d-${label}`}
                        aria-label={`裁片 ${label} 重合`}
                      />
                    </td>
                  );
                })}
              </tr>
              <tr>
                <th className="per-type-rowhead" scope="row">
                  旋转
                </th>
                {orderedLabels.map((label) => {
                  const v = draft[label] ?? { d: '', tol: '' };
                  return (
                    <td key={label}>
                      <input
                        type="number"
                        min={0}
                        max={MAX_ROTATION_TOL_DEG}
                        step={1}
                        placeholder={`t${LE}${MAX_ROTATION_TOL_DEG}`}
                        value={v.tol}
                        onChange={(e) => updateDraft(label, 'tol', e.target.value)}
                        onBlur={(e) => updateDraft(label, 'tol', clampDraft(e.target.value, MAX_ROTATION_TOL_DEG))}
                        data-testid={`tol-${label}`}
                        aria-label={`裁片 ${label} 旋转`}
                      />
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
        </div>

        <div className="per-type-hint dim small">
          重合 0–{MAX_OVERLAP_MM}mm、旋转 0–{MAX_ROTATION_TOL_DEG}°（全局上限）；默认 0 =
          不重合 / 锁布纹线。空值 = 继承（同 0）。
        </div>
        <div className="per-type-hint dim small" data-testid="per-type-save-hint">
          点空白处 / ESC / ✕ 关闭即保存更改；「取消」丢弃更改。
        </div>

        <div className="per-type-actions">
          <button
            type="button"
            className="per-type-btn-cancel"
            onClick={onClose}
            data-testid="per-type-cancel"
          >
            取消
          </button>
          <button
            type="button"
            className="per-type-btn-confirm"
            onClick={saveAndClose}
            data-testid="per-type-confirm"
          >
            确定
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )}
      {/* 成带放大层（第三层 modal，z-index 1300 叠在 ptype-preview 1200 之上；
          打开条件 = bandZoomOpen 且预览数据 ok —— error 态无放大可开）。 */}
      {bandZoomOpen && bandPreview?.ok
        ? createPortal(
            <div
              className="band-zoom-overlay"
              onMouseDown={handleZoomOverlayMouseDown}
              data-testid="band-zoom-overlay"
            >
              <div
                className="band-zoom-modal"
                role="dialog"
                aria-modal="true"
                aria-label={`${bandLabel}-成带预览放大`}
                onMouseDown={handleZoomModalMouseDown}
              >
                <button
                  type="button"
                  className="ptype-preview-close"
                  aria-label="关闭"
                  onClick={() => setBandZoomOpen(false)}
                  data-testid="band-zoom-close"
                >
                  ✕
                </button>
                <div
                  className="band-zoom-head"
                  title={`${bandLabel}-成带预览放大`}
                >
                  <span className="piece-card-label">{bandLabel}</span>
                  <span className="band-zoom-stats dim small">
                    填充率 {bandPreview.fill_pct ?? '—'}% · 带{' '}
                    {bandPreview.bbox?.width_mm ?? '—'}×
                    {bandPreview.bbox?.height_mm ?? '—'} mm ·{' '}
                    {bandPreview.n_members ?? '—'} 片
                  </span>
                </div>
                <div className="band-zoom-body">
                  <BandPreviewSVG
                    members={bandPreview.members ?? []}
                    outline={bandPreview.outline ?? null}
                    showLabels
                    pad={20}
                  />
                </div>
                <div className="band-zoom-hint dim small">
                  预览 = 求解时带的精确形态（链内贴触 · 码序降序 · 开口朝左 · 最大码在最右）；
                  虚线 = 组合片外轮廓（主解看到的形状）。
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
      {/* 前缀组合放大层（与 band-zoom 同层 1300、互斥打开；打开条件 =
          prefixZoomOpen 且预览数据 ok —— error 态无放大可开）。 */}
      {prefixZoomOpen && prefixPreview?.ok
        ? createPortal(
            <div
              className="band-zoom-overlay"
              onMouseDown={handleZoomOverlayMouseDown}
              data-testid="prefix-zoom-overlay"
            >
              <div
                className="band-zoom-modal"
                role="dialog"
                aria-modal="true"
                aria-label={`${prefixFront}+${prefixBack}-前缀组合预览放大`}
                onMouseDown={handleZoomModalMouseDown}
              >
                <button
                  type="button"
                  className="ptype-preview-close"
                  aria-label="关闭"
                  onClick={() => setPrefixZoomOpen(false)}
                  data-testid="prefix-zoom-close"
                >
                  ✕
                </button>
                <div
                  className="band-zoom-head"
                  title={`${prefixFront}+${prefixBack}-前缀组合预览放大`}
                >
                  <span className="piece-card-label">{prefixFront}+{prefixBack}</span>
                  <span className="band-zoom-stats dim small">
                    填充率 {prefixPreview.fill_pct ?? '—'}% ·{' '}
                    {prefixPreview.bbox?.width_mm ?? '—'}×
                    {prefixPreview.bbox?.height_mm ?? '—'} mm ·{' '}
                    {prefixPreview.n_members ?? '—'} 片 · 码 {prefixPreview.size ?? '—'}
                  </span>
                </div>
                <div className="band-zoom-body">
                  <BandPreviewSVG
                    members={prefixPreview.members ?? []}
                    outline={prefixPreview.outline ?? null}
                    showLabels
                    pad={20}
                  />
                </div>
                <div className="band-zoom-hint dim small">
                  预览 = 求解时前缀组合片的精确形态（4 片同码 interleave 竖排贴靠 ·
                  头尾相对 180°；标注 = 成员 g 码）；虚线 = 组合片外轮廓（主解看到
                  的形状）。尺码自 2+2 资格码自动选取（seed=0，与求解一致）。
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
