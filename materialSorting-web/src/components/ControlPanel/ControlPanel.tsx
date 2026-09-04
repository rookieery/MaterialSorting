// ControlPanel —— 左侧参数面板（与旧 index.html `<aside class="panel">` 等价）。
//
// 表单状态由本组件持有（DEFAULT_FORM 初值），各子组件受控。
// 点击 SolveControls「开始求解」时（所有非 running 态；running 态按钮为「停止」不进此路径）：
//   1. 校验 sizes 非空 —— 空 → onStatus('请至少选一个码号') + 不启动（AC#7）。
//   2. collectParams → { params, per_type }；parseTime / parseSeed / parseSeedCount 解析。
//   3. onStart({ sizes, time, seed, seed_count, params, per_type }) 透传到 NestingPage
//      （AC#6 触发 useSolveRun.start × N，N = seed_count）。
//
// phase / status 来自 NestingPage：phase 驱动 SolveControls 按钮组渲染；
// phase==='running' 禁用参数编辑 + ExportButtons（ stopped/done/error 可导出）。
// US-005 落地 multi_seed 开关 + seed_count；US-007 接管 ExportButtons（useExport 也住这里，
// 因为 sizes 在本组件 form 里 —— 旧 vanilla 实现 exportAs 内 `sizes: selectedSizes()` 同源）。
// US-017 起 SizePicker 从 uploadStore.doc 动态读码号（doc=null fallback SIZES），
// DEFAULT_FORM.sizes 改空数组强制用户选；form.sizes 可能含 null（通用码），handleStart /
// handleExport 过滤 null 保持下游 WS/export 契约；doc=null 时 StatusLine 增「请先在上传预览页解析母版」提示。
// US-019 删除主面板内外两档全局重合/旋转输入（d_ext/d_int/tol_ext/tol_int），全交高级配置弹窗
// （PerTypeOverrides 按钮 → PerTypeOverridesModal）；collectParams params 永远全 0。
// US-028：StartButton 删除，SolveControls 按 phase 渲染按钮组（idle/running/stopped/done/error）；
//   ExportButtons 收 phase==='running' 禁用 + partial flag（stopped/error 有帧时标注中间方案提示）。
//   所有非 running 态「开始求解」统一走本组件 handleStart（读当前 form）—— 无参数快照重放路径
//   （曾有的 onRestart/lastStartCfgRef 双路径会冻结首次参数，已删除）。
// 矩阵化重构 US-003：handleStart 增「全 0 拦截」—— 复用 SizePicker.computeTotalCutPieces 判
//   所选码有效片数为 0（数量全 0）时不启动求解并 onStatus 提示（现状会把空 items 实例交给
//   spyrrow，密度分母 0 风险）；doc=null（后端开发模式 fallback SIZES）时 computeTotalCutPieces
//   返回 null，不拦截。
// US-005：PerTypeOverrides 之后渲染 StrategyRunButton（高级运行入口；透传 solving/
//   buildStartContext/onApplyStrategy）。start 载荷构造与 handleStart 同源 —— 提取
//   collectStartContext(form, quantities) 共用（sizesNum / serializeQuantities /
//   collectParams 逐字段同一实现，不复制逻辑）；buildStartContext 闭包在 Modal 执行时
//   现取（数量矩阵编辑后即时生效）。
// US-013（腰头成带布局设置接线）：
//   - 启动闸门：band 开未选编号 / 选中 g 码数量全 0（bandMemberCount 三态，后端 demand
//     口径对齐）→ 「开始求解」置灰 + StatusLine band 段具体文案 + handleStart 运行时兜底
//     （与 sizes 空校验同源双保险）；
//   - 互斥（已解除）：2026-08-22 起 band 开启可进「高级运行」—— band 随
//     /api/strategy/start 写进 9 键 config（后端 _parse_band 同一校验点，
//     CLI solve_worker 进程内成带 + 展开，v2 确定性兼容多 seed 策略）；
//   - PerTypeOverrides 透传 band/onBandChange（弹窗布局设置分区：开关 + g 码下拉）。
// US-004（起始端成套前后幅接线）：
//   - 启动闸门：prefix 开未选前/后幅 / front==back → 「开始求解」置灰 + StatusLine
//     prefix 段具体文案 + handleStart 运行时兜底（band 同款双保险；**无资格码不置灰** ——
//     弹窗勾选区本地预检提示，开始求解交后端 _parse_prefix 权威校验拦截）；
//   - prefix 与 band 可同开（双开带位只记录是 US-003 后端行为，前端无额外控件）；
//   - 与「高级运行」策略入口的 v1 互斥已于 2026-08-25 解除（band 先例）：prefix
//     随 /api/strategy/start 写进 9 键 config（后端 _parse_prefix 同一校验点 +
//     2+2 资格码 start 期拦截，CLI worker 进程内构造）。
// 2026-08-22 seed UI 隐藏（界面只支持单 seed 模式）：ParamForm 删 seed 输入行、
//   MultiSeedControls 不再渲染（组件已删）。form.seed/multi_seed/seed_count 保留恒默认
//   （'0'/false/'3'）→ onStart 载荷 seed=0 / seed_count=1 不变；底层多 run 能力不动
//   （useSolveRun / runRegistry / NestsGrid），恢复 UI 即回多 seed；多种子探索由
//   「高级运行」（race/SE 后端策略编排）承接。
// 2026-08-27 重传联动：doc_id 变化（重传新母版 / 首次上传 / reset）→ form 整体回
//   DEFAULT_FORM（码号清空、band/prefix 关闭、per_type 清空、幅宽 175.00 / 时长 120）。
//   与 US-014 数量矩阵「重传清零」同口径 —— 旧母版选择残留会使 band/prefix 旧 g 码
//   在弹窗下拉兜底下看似合法（后端结构化 error 兜底才暴露）、per_type 旧键混进新
//   母版高级配置表格列集。实现见组件内 useEffect([docId])（form 是本地 state，
//   状态所有者是唯一挂点；NestingPage 双页常驻不卸载，无此 effect 则必残留）。

import { useCallback, useEffect, useState } from 'react';
import { useExport } from '../../hooks/useExport';
import type { ExportFmt } from '../../lib/download';
import type { ExportTableFields } from '../../lib/exportTable';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { useUploadStore } from '../../store/uploadStore';
import { useQtyStore } from '../../store/qtyStore';
import { ExportButtons } from './ExportButtons';
import { ExportInfoModal } from './ExportInfoModal';
// 编辑排料 US-002：编辑弹窗单例（订阅 controlPanelStore 自显隐；Portal 到 body）。
// 打开入口 = US-004 主界面「编辑排料」区块（本 story store 驱动 + 单测直开）。
import { EditLayoutModal } from '../edit/EditLayoutModal';
import { ParamForm } from './ParamForm';
import { PerTypeOverrides } from './PerTypeOverrides';
import { SizePicker, computeTotalCutPieces } from './SizePicker';
import { SolveControls } from './SolveControls';
import { StatusLine } from './StatusLine';
import { StrategyRunButton } from './StrategyRunButton';
import { ExtremeRunButton } from './ExtremeRunButton';
import {
  bandMemberCount,
  collectStartContext,
  DEFAULT_FORM,
  parseGate,
  parseSeedCount,
  type FormState,
} from '../../lib/params';
import type { PerTypeOverrides as PerTypeOverridesValue, SolveParams } from '../../types/v03';
import type { StrategyResult } from '../../types/strategy';
import type { SolvePhase } from '../../types/solvePhase';
import type { BandConfig, PrefixConfig } from '../../types/ws';

/** onStart 透传给 App 的载荷（直接喂给 useSolveRun.start 的 StartConfig 子集）。 */
export interface ControlPanelStartPayload {
  sizes: number[];
  time: number;
  /** 幅宽（mm）= parseGate(form)（cm×10）；透传 useSolveRun.start → WS StartPayload.gate_mm。 */
  gate_mm: number;
  /** base seed（seed = base+i, i=0..N-1）。 */
  seed: number;
  /** 实际并行启动的 seed 数量（multi_seed=false → 1；true → clamp(seed_count,2,6)）。 */
  seed_count: number;
  params: SolveParams;
  per_type: PerTypeOverridesValue | null;
  /**
   * US-022 per-size demand：label → sizeKey → 数量（null → 后端 demand=1 向后兼容）。
   * ControlPanel.handleStart 内经 serializeQuantities(qtyStore.quantities, sizes) 序列化。
   */
  quantities: Record<string, Record<string, number>> | null;
  /**
   * US-012 腰头成带：collectStartContext 三态解析（关 / 开未选 → null；开且有效 →
   * {enabled:true,label}）。随 handleStart 的 ctx spread 自动透传，NestingPage 转发到
   * useSolveRun.start → WS StartPayload.band。
   */
  band: BandConfig | null;
  /**
   * US-004 起始端成套前后幅：collectPrefix 三态解析（关 / 开未选或无效 → null；
   * 开且有效 → {enabled:true,front,back}）。同随 ctx spread 透传到
   * useSolveRun.start → WS StartPayload.prefix（无 size 键，资格码后端选取）。
   */
  prefix: PrefixConfig | null;
}

export interface ControlPanelProps {
  /** 点击启动（已通过码号非空校验）。 */
  onStart: (cfg: ControlPanelStartPayload) => void;
  /** US-027/028 求解状态机五态（驱动 SolveControls 按钮组渲染 + running 态冻结参数编辑 + ExportButtons 禁用）。 */
  phase: SolvePhase;
  /** 状态行文案（来自 NestingPage；组装：就绪/连接中/完成/错误）。 */
  status: string;
  /** 写状态行（用于码号校验失败时把错误塞进 StatusLine）。 */
  onStatus: (text: string) => void;
  /** US-027 停止求解回调（US-028 由 SolveControls 停止按钮接线）。 */
  onStop: () => void;
  /**
   * US-006 策略 run 应用到主画布回调（StrategyRunModal 结果态按钮）。
   * US-005 仅透传链路（未传 → 应用按钮 disabled）；NestingPage 接线在 US-006。
   * US-003 起同一回调也透传 ExtremeRunButton（极限运行结果态「应用到主画布」——
   * result 同形，applyStrategyResult 合成 RunRecord 单一实现复用）。
   */
  onApplyStrategy?: (result: StrategyResult) => void;
}

export function ControlPanel({ onStart, phase, status, onStatus, onStop, onApplyStrategy }: ControlPanelProps) {
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  // US-017：订阅 uploadStore.doc 判断是否已解析母版（doc=null → StatusLine 增提示）。
  const doc = useUploadStore((s) => s.doc);

  // 重传联动（2026-08-27，与 PreviewPage quantities hydrate 同口径）：doc_id 变化
  // （首次上传 / 重传 / reset）→ form 整体回 DEFAULT_FORM（「新母版 = 全新表单」，
  // 含幅宽 175.00 / 时长 120）。旧母版的码号 / band / prefix / per_type 对新母版可能
  // 非法 —— band/prefix 旧 g 码在弹窗下拉兜底下仍显示为合法选中项（点开始才被
  // 后端结构化 error 拦截）、per_type 旧键会混进新母版高级配置表格列集
  // （orderedLabels = reps ∪ 已配置键）、旧码号残留在 form.sizes。App 双页常驻
  // DOM 不卸载，form 是本地 state 无 store 归宿，此处（状态所有者）是唯一挂点。
  // 细节：mount 时 doc=null → docId=undefined，effect 首跑 setForm(DEFAULT_FORM)
  // 为 no-op；doc 对象因切 activeSize 等换引用但 doc_id 不变时不触发（dep 字符串）；
  // DEFAULT_FORM 是模块常量且 patch 恒建新对象不原地改，共享引用安全；求解中重置
  // 无风险（求解用 start 载荷快照不回读 form，running 态输入本就 disabled）。
  const docId = doc?.doc_id;
  useEffect(() => {
    setForm(DEFAULT_FORM);
  }, [docId]);
  // US-013：订阅 quantities —— band 启动闸门（选中 g 码数量全 0 → 置灰）需要对数量
  // 矩阵编辑**响应式**（handleStart 内仍 getState() 现取快照，口径同源）。
  const quantities = useQtyStore((s) => s.quantities);

  // US-028：从 phase 派生 solving（running 态冻结参数编辑 + 禁用 ExportButtons）。
  // stopped/done/error 态可编辑参数（用户改参数后点「开始求解」→ handleStart 即用新值）。
  const solving = phase === 'running';

  // US-007：useExport 挂在 ControlPanel 内（form.sizes 与 exportAs 同处）。
  // onStatus 透传到 NestingPage.setStatus → StatusLine（导出中 / 完成 / 失败文案由 useExport 写）。
  const { exportAs, exporting } = useExport({ onStatus });

  // 2026-08-30：PLT 导出信息表格弹窗（ExportInfoModal 订阅 controlPanelStore 自显隐；
  // 打开入口在 handleExport 的 fmt==='plt' 分流）。
  const openModal = useControlPanelStore((s) => s.openModal);

  // 2026-08-31：弹窗打开时的 PLT 变体（'plt' 全量 / 'plt-clean' 毛版）—— handleExport
  // 分流时记下，handlePltConfirm 按它调 exportAs；默认 'plt'（弹窗永不因非导出路径打开）。
  const [pendingPltFmt, setPendingPltFmt] = useState<'plt' | 'plt-clean'>('plt');

  /** 通用 patch 更新（部分字段）。 */
  function patch(p: Partial<FormState>) {
    setForm((prev) => ({ ...prev, ...p }));
  }

  /**
   * US-005：handleStart 与 StrategyRunModal「执行」共用的 start 上下文构造器
   * （collectStartContext 单一实现 —— 码号过滤 / 幅宽 / seed / params / per_type /
   * quantities 逐字段同源，不复制逻辑）。getState() 取调用时刻数量快照（不订阅）。
   */
  const buildStartContext = useCallback(
    () => collectStartContext(form, useQtyStore.getState().quantities),
    [form],
  );

  // US-013 band 启动闸门（AC#3）：勾选未选编号 / 选中 g 码数量全 0（bandMemberCount
  // 三态：missing→1 / 显 0 / 未选码过滤，后端 _band_demand 口径对齐 —— 后端同条件
  // 会回结构化 error，这里是前置 UI 闸门）。startDisabled 消费 + handleStart 兜底。
  const bandMissingLabel =
    form.band_enabled && form.band_label.trim() === '';
  const bandZeroQty =
    form.band_enabled &&
    form.band_label.trim() !== '' &&
    bandMemberCount(form, quantities, form.band_label.trim()) === 0;

  // US-004 prefix 启动闸门（AC#3）：勾选未选前/后幅 → 置灰 + 具体文案；front==back
  // 拦截（后端 _parse_prefix「须为不同 g 码」同条件前置）。无资格码**不置灰** ——
  // 弹窗勾选区已有本地预检提示，权威拦截在后端（结构化 error 早退）。
  const prefixMissingLabel =
    form.prefix_enabled &&
    (form.prefix_front.trim() === '' || form.prefix_back.trim() === '');
  const prefixSameLabel =
    form.prefix_enabled &&
    !prefixMissingLabel &&
    form.prefix_front.trim() === form.prefix_back.trim();

  function handleStart() {
    if (solving) return;
    if (form.sizes.length === 0) {
      onStatus('请至少选一个码号');
      return;
    }
    // US-013：band 闸门运行时兜底（按钮已置灰；防御与 sizes 校验同源双保险）。
    if (bandMissingLabel) {
      onStatus('已开启腰头成带，请先选择腰头编号（高级配置 → 布局设置）');
      return;
    }
    if (bandZeroQty) {
      onStatus(
        `腰头 ${form.band_label.trim()} 所选码数量全 0，请先在上传预览页数量矩阵设置数量`,
      );
      return;
    }
    // US-004：prefix 闸门运行时兜底（按钮已置灰；防御与 band 闸门同源双保险）。
    if (prefixMissingLabel) {
      onStatus('已开启起始端成套前后幅，请先选择前幅/后幅 g 码（高级配置 → 布局设置）');
      return;
    }
    if (prefixSameLabel) {
      onStatus('起始端成套前后幅须为不同 g 码（前/后幅各一），请重新选择');
      return;
    }
    // 矩阵化重构 US-003 全 0 拦截：所选码有效片数 = Σ demand（doc=null 开发模式 fallback
    // 返回 null 不拦截）；为 0（数量全 0）时不发 WS start，状态行提示去预览页改数量。
    const totalCut = computeTotalCutPieces(
      doc,
      form.sizes,
      useQtyStore.getState().quantities,
    );
    if (totalCut === 0) {
      onStatus('所选码号有效裁片数为 0，请先在上传预览页数量矩阵中设置数量');
      return;
    }
    // US-005：载荷构造与策略 run「执行」同源（collectStartContext）；seed_count 是
    // 主画布 multi_seed 专属，仅本路径附加。
    const ctx = buildStartContext();
    onStart({ ...ctx, seed_count: parseSeedCount(form) });
  }

  /** form.sizes 过滤 null（通用码）—— handleExport / handlePltConfirm 同源复用。 */
  const filterSizes = useCallback(
    (): number[] => form.sizes.filter((s: number | null): s is number => s !== null),
    [form.sizes],
  );

  /** 导出按钮回调 —— 透传 form.sizes（过滤 null）给 useExport.exportAs（与旧 vanilla
   *  实现 `sizes: selectedSizes()` 一致）。PLT 两变体分流到信息表格弹窗（2026-08-30：
   *  先填床次/层数等 6 手输字段再导出，生产 PLT 同款表格附在唛架末端；2026-08-31 起
   *  'plt-clean' 毛版同款分流（默认导出格式），两变体共用一份表格字段）；PNG/DXF 直通。 */
  function handleExport(fmt: ExportFmt): void {
    if (fmt === 'plt' || fmt === 'plt-clean') {
      setPendingPltFmt(fmt);
      openModal('export_info');
      return;
    }
    void exportAs(fmt, filterSizes(), doc?.filename);
  }

  /** PLT 信息表格弹窗确认 —— 携手输字段按打开时的变体导出（唯一提交路径，
   *  ExportInfoModal 内已落盘记忆；pendingPltFmt 由 handleExport 分流时写入）。 */
  function handlePltConfirm(fields: ExportTableFields): void {
    void exportAs(pendingPltFmt, filterSizes(), doc?.filename, fields);
  }

  // US-017：doc=null 时 StatusLine 增提示「请先在上传预览页解析母版」（AC#3）；
  // US-013：band 闸门态追加 band 段具体文案（与 startDisabled 同源派生）；
  // US-004：prefix 闸门态同追加（band 段之后）。
  const bandHint = bandMissingLabel
    ? '已开启腰头成带，请先选择腰头编号（高级配置 → 布局设置）'
    : bandZeroQty
      ? `腰头 ${form.band_label.trim()} 所选码数量全 0，请先在上传预览页数量矩阵设置数量`
      : '';
  const prefixHint = prefixMissingLabel
    ? '已开启起始端成套前后幅，请先选择前幅/后幅 g 码（高级配置 → 布局设置）'
    : prefixSameLabel
      ? '起始端成套前后幅须为不同 g 码（前/后幅各一），请重新选择'
      : '';
  const visibleStatus = [
    status,
    doc === null ? '请先在上传预览页解析母版' : '',
    bandHint,
    prefixHint,
  ]
    .filter(Boolean)
    .join(' — ');

  // US-028：stopped/error（有帧）态导出时明确标注「中间方案」（AC#3）。
  //   - stopped 总是有帧（停止前至少推过一帧或收到过 manifest；若无帧 ExportButtons 自身 disabled 兜底）。
  //   - error 可能在收到帧前发生（构造失败）→ 此时 ExportButtons 也 disabled，partial flag 仅作 UI 提示触发条件。
  const partial = phase === 'stopped' || phase === 'error';

  // 码号未选时「开始求解」按钮置灰（与 handleStart 内 sizes 非空校验同源；前置 UI 反馈，AC#7）；
  // US-013：band 闸门（未选编号 / 数量全 0）同置灰（SolveControls 应用到所有非 running 态按钮）；
  // US-004：prefix 闸门（未选前/后幅 / front==back）同置灰（无资格码不置灰 —— 后端权威拦截）。
  const startDisabled =
    form.sizes.length === 0 ||
    bandMissingLabel ||
    bandZeroQty ||
    prefixMissingLabel ||
    prefixSameLabel;

  // US-013（FR-6 v1 互斥已于 2026-08-22 解除）：band 开启可进「高级运行」——
  // band 随 /api/strategy/start 写进 9 键 config（cli 9 键 schema + solve_pieces
  // 透传 solve_worker 进程内成带，v2 构造性链构造确定性兼容多 seed 策略）。
  // US-004 同款（2026-08-25 解除）：prefix 开启也可进「高级运行」—— prefix 同入
  // config（_parse_prefix 校验 + 资格码 seeded 选取确定性兼容多 seed）。
  // 既有 solving / 未 commit 置灰语义不变。

  return (
    <aside className="panel">
      {/* 当前排料文件名上下文条：doc?.filename 直接来自上传解析响应（与 SizePicker 同源订阅 uploadStore.doc）。
          doc=null（未解析母版）时灰字占位「尚未解析母版」，与下方 StatusLine 的「请先解析母版」提示同源（US-017）。
          文件名长时 ellipsis 截断，title 兜底悬停看全名；分隔线把文件名条与「求解控制」功能标题分层。 */}
      <div className="doc-banner" data-tour="doc-banner">
        <span className="doc-banner-label">当前文件</span>
        <span
          className={`doc-banner-name${doc ? '' : ' empty'}`}
          title={doc?.filename ?? ''}
        >
          {doc?.filename ?? '尚未解析母版'}
        </span>
      </div>
      <h2>求解控制</h2>
      <SizePicker selected={form.sizes} onChange={(sizes) => patch({ sizes })} disabled={solving} />
      {/* US-031 params 步锚点：包裹幅宽/时长（ParamForm）+ 高级配置（PerTypeOverrides）
          整个「求解参数」区（2026-08-22 起 seed/multi_seed 控件已隐藏）。码号多选（SizePicker）
          在其上独立成区不纳入。 */}
      <div data-tour="param-form">
        <ParamForm
          gate={form.gate}
          time={form.time}
          onGate={(gate) => patch({ gate })}
          onTime={(time) => patch({ time })}
          disabled={solving}
        />
        {/* 2026-08-22 seed UI 隐藏（单 seed 模式）：MultiSeedControls（多 seed 对比 + 数量）
            不再渲染、组件文件已删；form.seed/multi_seed/seed_count 字段保留恒默认值
            （'0'/false/'3'）→ parseSeed 恒 0 / parseSeedCount 恒 1 → NestingPage
            seed_count 循环自然退化为单 run。底层多 run 能力（useSolveRun / runRegistry /
            NestsGrid / WS 多连接）不动，恢复 UI 即回多 seed。多 seed 探索需求由
            「高级运行」（race/SE 后端策略编排）承接。 */}
        <PerTypeOverrides
          values={form.per_type}
          onChange={(per_type) => patch({ per_type })}
          band={{
            enabled: form.band_enabled,
            label: form.band_label,
          }}
          onBandChange={(band) =>
            patch({
              band_enabled: band.enabled,
              band_label: band.label,
            })
          }
          prefix={{
            enabled: form.prefix_enabled,
            front: form.prefix_front,
            back: form.prefix_back,
          }}
          onPrefixChange={(prefix) =>
            patch({
              prefix_enabled: prefix.enabled,
              prefix_front: prefix.front,
              prefix_back: prefix.back,
            })
          }
          sizes={form.sizes.filter(
            (s: number | null): s is number => s !== null,
          )}
          gateMm={parseGate(form)}
          disabled={solving}
        />
        {/* US-005 高级运行入口（策略 run 10/20/30/60min + race/se 双模式）：disabled =
            solving（互斥防 CPU 竞争）|| doc===null（未 commit 无排料数据）。
            2026-08-22 起 band 开启不再互斥（band 随 start 载荷进 config）；
            2026-08-25 起 prefix 开启同样不再互斥（prefix 同入 config）。
            US-003 极限运行入口（.strategy-entry-row 并排同级）：60/120/240/480min
            预设 + 自定义，参数全隐藏；band/prefix 开启由弹窗执行按钮置灰前置拦截
            （后端 /api/extreme/start 按键判在场即 400「暂不支持」）；同会话与高级
            运行单飞互斥由后端 409 兜底（文案区分对方）。两族轮询各自单实例
            （/api/strategy/status 与 /api/extreme/status 互不重叠）。 */}
        <div className="strategy-entry-row">
          <StrategyRunButton
            solving={solving}
            buildStartContext={buildStartContext}
            onApplyStrategy={onApplyStrategy}
            disabled={solving || doc === null}
          />
          <ExtremeRunButton
            solving={solving}
            buildStartContext={buildStartContext}
            onApplyExtreme={onApplyStrategy}
            disabled={solving || doc === null}
          />
        </div>
      </div>
      {/* US-031：data-tour="start-btn" 锚定 SolveControls 父容器（nestingTour step3 高亮目标）。 */}
      <div data-tour="start-btn">
        <SolveControls phase={phase} onStart={handleStart} onStop={onStop} startDisabled={startDisabled} />
      </div>
      <StatusLine text={visibleStatus} />
      <ExportButtons solving={solving} exporting={exporting} onExport={handleExport} partial={partial} />
      {/* PLT 导出信息表格弹窗单例（订阅 controlPanelStore 自显隐；Portal 到 body）。 */}
      <ExportInfoModal exporting={exporting} onConfirm={handlePltConfirm} variant={pendingPltFmt} />
      {/* 编辑排料弹窗单例（US-002；打开入口在 US-004 EditLayoutControls）。 */}
      <EditLayoutModal />
    </aside>
  );
}
