// ControlPanel —— 左侧参数面板（与旧 index.html `<aside class="panel">` 等价）。
//
// 表单状态由本组件持有（DEFAULT_FORM 初值），各子组件受控。
// 点击 SolveControls「普通运行」时（所有非 running 态；running 态按钮为「停止」不进此路径）：
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
//   所有非 running 态「普通运行」统一走本组件 handleStart（读当前 form）—— 无参数快照重放路径
//   （曾有的 onRestart/lastStartCfgRef 双路径会冻结首次参数，已删除）。
// key 授权 US-007：handleStart async 化 —— 本地校验全过后、onStart 前先
//   await ensureRunAllowed()（POST /api/key/precheck；失败 onStatus 中文文案 +
//   keyGate 内 Toast，不进 WS 连接）。三入口闸门详见 lib/keyGate.ts 文件头。
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
//     口径对齐）→ 「普通运行」置灰 + StatusLine band 段具体文案 + handleStart 运行时兜底
//     （与 sizes 空校验同源双保险）；
//   - 互斥（已解除）：2026-08-22 起 band 开启可进「高级运行」—— band 随
//     /api/strategy/start 写进 9 键 config（后端 _parse_band 同一校验点，
//     CLI solve_worker 进程内成带 + 展开，v2 确定性兼容多 seed 策略）；
//   - PerTypeOverrides 透传 band/onBandChange（弹窗布局设置分区：开关 + g 码下拉）。
// US-004（起始端成套前后幅接线）：
//   - 启动闸门：prefix 开未选前/后幅 / front==back → 「普通运行」置灰 + StatusLine
//     prefix 段具体文案 + handleStart 运行时兜底（band 同款双保险；**无资格码不置灰** ——
//     弹窗勾选区本地预检提示，普通运行交后端 _parse_prefix 权威校验拦截）；
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
// 状态文件 US-003：form 自本地 useState 上提 formStore（保存读 form / 恢复注 form
//   的跨模块地基），useEffect([docId]) 挂点改为 formStore.resetForDoc —— 「有本
//   docId 的水合载荷 → 保留，否则 DEFAULT_FORM」，docId 变更重置语义与本地 state
//   时代完全一致（行为不变是硬红线；水合载荷 US-004 恢复编排才写入）。保存入口
//   2026-09-12 改判（用户要求）：从导出格式下拉第 5 项拆出为独立区块
//   SaveStateControls（「编辑排料」与「导出最优方案」之间，标题「保存当前方案
//   状态（.msn）」+ 单「保存」按钮，按钮状态与导出按钮同公式同数据源严格一致；
//   原下拉选中时的保存范围说明行随之删除）。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useExport } from '../../hooks/useExport';
// key 授权 US-007：普通运行前置 key 预检（POST /api/key/precheck，与后端 WS 闸门
// 同判定序不扣次；三入口共用 lib/keyGate 单一实现）。
import { ensureRunAllowed, type RunGateResult } from '../../lib/keyGate';
import { defaultExportFilename, defaultStateFilename, type ExportFmt } from '../../lib/download';
import type { ExportTableFields } from '../../lib/exportTable';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { useFormStore } from '../../store/formStore';
// 初始布局 US-004：热启动能力订阅（入口按钮置灰判定；App 启动探测，此处仅读）。
// US-007：saved + isStale 订阅（普通运行附带 initial + SolveControls chip 三态）。
import { initialLayoutFingerprint, useInitialLayoutStore } from '../../store/initialLayoutStore';
import { runRegistry } from '../../store/runRegistry';
import { useUploadStore } from '../../store/uploadStore';
import { useQtyStore } from '../../store/qtyStore';
import { ExportButtons } from './ExportButtons';
import { ExportInfoModal } from './ExportInfoModal';
// 2026-09-12 文件名需求 1：保存 / DXF·PNG 导出的「文件名」确认弹窗（本地条件渲染，
// 不进 controlPanelStore —— 打开时刻面板被遮罩挡住，不可能与其他 store 弹窗共存）。
import { FileNameModal } from './FileNameModal';
// 编辑排料 US-002：编辑弹窗单例（订阅 controlPanelStore 自显隐；Portal 到 body）。
// 打开入口 = US-004 主界面「编辑排料」区块（EditLayoutControls）。
import { EditLayoutModal } from '../edit/EditLayoutModal';
import { InitialLayoutModal } from '../edit/InitialLayoutModal';
// key 授权 US-006：「系统key」弹窗单例（keyStore 数据源，/api/key/*）。
import { KeyInfoModal } from './KeyInfoModal';
// 编辑排料 US-004：主面板「编辑排料」区块（编辑入口 + 重置 confirm），插在
// StatusLine 与 ExportButtons 之间（「导出最优方案」上方）—— 激活口径与导出一致。
import { EditLayoutControls } from './EditLayoutControls';
// 状态文件 2026-09-12 入口改判：保存入口独立区块（「编辑排料」与「导出最优方案」
// 之间）—— saveState 直连（不再经导出格式下拉 state 项）；按钮状态与导出按钮
// 同公式同数据源严格一致（exporting 共享单一防连击旗）。
import { SaveStateControls } from './SaveStateControls';
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
  parseGate,
  parseSeedCount,
  type FormState,
} from '../../lib/params';
import type { PerTypeOverrides as PerTypeOverridesValue, SolveParams } from '../../types/v03';
import type { StrategyResult } from '../../types/strategy';
import type { SolvePhase } from '../../types/solvePhase';
import type { BandConfig, PrefixConfig, WarmInitialPayload } from '../../types/ws';

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
  /**
   * 初始布局热启动（US-007）：saved 且指纹未失效 → {placed: saved.warmPlaced,
   * demand_map?}（saved.demandMap 非空才带键 —— plain 时后端忽略投影）；stale /
   * 无 / 已清除 → null（useSolveRun 对 null 不写 initial 键，运行照常不拦截）。
   */
  initial: WarmInitialPayload | null;
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
  /**
   * 结果来源小字文案（状态文件 US-004）：合成 run（策略/极限应用 / 状态文件恢复）
   * 的 provenance 展示（如「来源：极限运行(600s) · seed 0」），NestingPage 经
   * provenanceText 组装传入；undefined（WS 普通求解 / 无 run）→ 不渲染该行。
   */
  runProvenance?: string;
}

export function ControlPanel({ onStart, phase, status, onStatus, onStop, onApplyStrategy, runProvenance }: ControlPanelProps) {
  // 状态文件 US-003：form 由 formStore 持有（原本地 useState；行为等价迁移）。
  const form = useFormStore((s) => s.form);
  // US-017：订阅 uploadStore.doc 判断是否已解析母版（doc=null → StatusLine 增提示）。
  const doc = useUploadStore((s) => s.doc);
  // 初始布局 US-004：热启动能力（App 启动 probeCapability 拉一次；此处订阅
  // supported === false → 入口按钮置灰 + title 中文提示；null = 未探知不置灰）。
  const warmSupported = useInitialLayoutStore((s) => s.supported);
  // US-007：已保存初始布局 + 清除动作（chip「×清除」消费 —— 只清 saved，
  // genSeed 保留单调递增，下次弹窗刷新换代续接）。
  const savedInitial = useInitialLayoutStore((s) => s.saved);
  const clearInitial = useInitialLayoutStore((s) => s.clear);

  // 重传联动（2026-08-27，与 PreviewPage quantities hydrate 同口径）：doc_id 变化
  // （首次上传 / 重传 / reset）→ form 整体回 DEFAULT_FORM（「新母版 = 全新表单」，
  // 含幅宽 175.00 / 时长 120）。旧母版的码号 / band / prefix / per_type 对新母版可能
  // 非法 —— band/prefix 旧 g 码在弹窗下拉兜底下仍显示为合法选中项（点开始才被
  // 后端结构化 error 拦截）、per_type 旧键会混进新母版高级配置表格列集
  // （orderedLabels = reps ∪ 已配置键）、旧码号残留在 form.sizes。App 双页常驻
  // DOM 不卸载，此处（状态所有者）是唯一挂点 —— US-003 起状态归宿是 formStore，
  // effect 内改调 resetForDoc（无水合载荷 → DEFAULT_FORM，语义与 setForm 等价）。
  // 细节：mount 时 doc=null → docId=undefined，effect 首跑 resetForDoc(undefined)
  // = 回 DEFAULT_FORM（幂等 no-op）；doc 对象因切 activeSize 等换引用但 doc_id
  // 不变时不触发（dep 字符串）；DEFAULT_FORM 是模块常量且 patch 恒建新对象不
  // 原地改，共享引用安全；求解中重置无风险（求解用 start 载荷快照不回读 form，
  // running 态输入本就 disabled）。
  const docId = doc?.doc_id;
  useEffect(() => {
    useFormStore.getState().resetForDoc(docId);
  }, [docId]);
  // US-013：订阅 quantities —— band 启动闸门（选中 g 码数量全 0 → 置灰）需要对数量
  // 矩阵编辑**响应式**（handleStart 内仍 getState() 现取快照，口径同源）。
  const quantities = useQtyStore((s) => s.quantities);

  // US-028：从 phase 派生 solving（running 态冻结参数编辑 + 禁用 ExportButtons）。
  // stopped/done/error 态可编辑参数（用户改参数后点「普通运行」→ handleStart 即用新值）。
  const solving = phase === 'running';

  // US-007：useExport 挂在 ControlPanel 内（form.sizes 与 exportAs 同处）。
  // onStatus 透传到 NestingPage.setStatus → StatusLine（导出中 / 完成 / 失败文案由 useExport 写）。
  // 状态文件：saveState（SaveStateControls 保存按钮消费，2026-09-12 前为导出下拉
  // state 项分支）与 exportAs 共用 exporting 防连击旗。
  const { exportAs, saveState, exporting } = useExport({ onStatus });

  // 2026-08-30：PLT 导出信息表格弹窗（ExportInfoModal 订阅 controlPanelStore 自显隐；
  // 打开入口在 handleExport 的 fmt==='plt' 分流）。
  const openModal = useControlPanelStore((s) => s.openModal);

  // 2026-08-31：弹窗打开时的 PLT 变体（'plt' 全量 / 'plt-clean' 毛版）—— handleExport
  // 分流时记下，handlePltConfirm 按它调 exportAs；默认 'plt'（弹窗永不因非导出路径打开）。
  const [pendingPltFmt, setPendingPltFmt] = useState<'plt' | 'plt-clean'>('plt');

  // 2026-09-12 文件名弹窗（需求 1）：pending 目标 —— 保存（.msn）与导出 DXF/PNG
  // （无自有弹窗的直通格式）点击后先经 FileNameModal 确认文件名；null = 关闭。
  // PLT 两变体不经此（需求 2：文件名区嵌在 ExportInfoModal 顶部）。
  const [pendingNameTarget, setPendingNameTarget] = useState<
    { kind: 'export'; fmt: 'dxf' | 'png' } | { kind: 'state' } | null
  >(null);

  /** 通用 patch 更新（部分字段）—— formStore.patch（浅合并建新对象，同旧 setForm 语义）。 */
  function patch(p: Partial<FormState>) {
    useFormStore.getState().patch(p);
  }

  // key 授权 US-007：普通运行 key 预检在飞旗（async 化引入的往返窗口内防连击 ——
  // 本地校验同步早退无此窗口；finally 复位，拦截后可立刻重试）。
  const gateInFlightRef = useRef(false);

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

  // 初始布局 US-007：chip 三态（SolveControls 消费）—— 'fresh' = saved 在场且
  // 指纹新鲜（普通运行将附带 initial），'stale' = saved 在场但七组件上下文已漂移
  // （数量/参数/门幅/band/prefix 任一变更），'none' = 无 saved。与 handleStart 附带
  // 判定同一真相源（initialLayoutFingerprint + isStale），数量矩阵编辑响应式更新
  // （quantities 已订阅）。useMemo 挡无关渲染的指纹重算（JSON 序列化数量矩阵）。
  const initialChipState = useMemo<'fresh' | 'stale' | 'none'>(() => {
    if (savedInitial === null) return 'none';
    const fp = initialLayoutFingerprint(collectStartContext(form, quantities));
    return useInitialLayoutStore.getState().isStale(fp) ? 'stale' : 'fresh';
  }, [savedInitial, form, quantities]);

  /**
   * US-007：saved 且未失效 → 组装 initial 载荷（warmPlaced 组合宇宙条目 +
   * demandMap 非空才带 demand_map 键 —— plain 时后端忽略投影）；否则 null。
   * stale 布局对当前 pid 宇宙必然降级（instance_mismatch），前端先判不带 ——
   * 与弹窗打开编排（stale 不续编）同口径。
   */
  function buildInitialPayload(): WarmInitialPayload | null {
    const il = useInitialLayoutStore.getState();
    if (il.saved === null) return null;
    if (il.isStale(initialLayoutFingerprint(buildStartContext()))) return null;
    return {
      placed: il.saved.warmPlaced,
      ...(il.saved.demandMap != null ? { demand_map: il.saved.demandMap } : {}),
    };
  }

  async function handleStart() {
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
    // key 授权 US-007：运行前 key 预检 —— 放本地校验之后、onStart 之前（与后端
    // 闸门同序：/ws/solve 也是 pieces/gate_mm 校验后才 ensure_run_allowed；无效
    // 输入路径零网络零时序变化，precheck 仅在即将真跑时发起）。失败：Toast（keyGate
    // 内已弹）+ StatusLine（onStatus）中文文案，不进 WS 连接（无 onStart 调用）；
    // 文案三入口一致（后端 precheck 映射，前端不自行判断网络）。
    if (gateInFlightRef.current) return;
    gateInFlightRef.current = true;
    let gate: RunGateResult;
    try {
      gate = await ensureRunAllowed();
    } finally {
      gateInFlightRef.current = false;
    }
    if (!gate.ok) {
      onStatus(gate.message);
      return;
    }
    // US-005：载荷构造与策略 run「执行」同源（collectStartContext）；seed_count 是
    // 主画布 multi_seed 专属，仅本路径附加。US-007：saved 且指纹未失效 → 附带
    // initial（普通运行热启动）；stale / 无 → null（不附带、不拦截运行）。
    const ctx = buildStartContext();
    onStart({ ...ctx, seed_count: parseSeedCount(form), initial: buildInitialPayload() });
  }

  /** form.sizes 过滤 null（通用码）—— handleExport / handlePltConfirm 同源复用。 */
  const filterSizes = useCallback(
    (): number[] => form.sizes.filter((s: number | null): s is number => s !== null),
    [form.sizes],
  );

  /** 导出按钮回调 —— 透传 form.sizes（过滤 null）给 useExport.exportAs（与旧 vanilla
   *  实现 `sizes: selectedSizes()` 一致）。PLT 两变体分流到信息表格弹窗（2026-08-30：
   *  先填床次/层数等 6 手输字段再导出，生产 PLT 同款表格附在唛架末端；2026-08-31 起
   *  'plt-clean' 毛版同款分流（默认导出格式），两变体共用一份表格字段；2026-09-12 起
   *  弹窗顶部兼收文件名）；PNG/DXF 2026-09-12 起先经 FileNameModal 确认文件名。
   *  （状态文件 .msn 不经此路径 —— 保存入口独立为 SaveStateControls。） */
  function handleExport(fmt: ExportFmt): void {
    if (fmt === 'plt' || fmt === 'plt-clean') {
      setPendingPltFmt(fmt);
      openModal('export_info');
      return;
    }
    // DXF/PNG：无自有弹窗 → FileNameModal（预填合成默认名；确认才导出）。
    // 'state' 已不入下拉（2026-09-12 入口改判），类型上仍可能 → 防御性忽略。
    // bestRun 防御性判空（导出按钮 hasLastFrame 门槛已拦截，双保险同 ExportInfoModal）。
    if (fmt !== 'dxf' && fmt !== 'png') return;
    if (!runRegistry.bestRun()?.lastFrame) return;
    setPendingNameTarget({ kind: 'export', fmt });
  }

  /** 保存按钮回调 —— 2026-09-12 起先经 FileNameModal 确认文件名（预填名称主体
   *  <母版名去.dxf>_状态_<时间戳>，无扩展名、后端补 .msn）再 saveState；
   *  SaveStateControls 仍纯 onSave。 */
  function handleSaveState(): void {
    setPendingNameTarget({ kind: 'state' });
  }

  /** FileNameModal 确认 —— 按 pending 目标分发（保存 / DXF·PNG 导出），
   *  saveAs = 用户确认的名称主体（无扩展名；后端清洗 + 按格式补后缀后覆盖合成名）。 */
  function handleSaveNameConfirm(name: string): void {
    const target = pendingNameTarget;
    setPendingNameTarget(null);
    if (!target) return;
    if (target.kind === 'state') {
      void saveState(name);
    } else {
      void exportAs(target.fmt, filterSizes(), doc?.filename, undefined, name);
    }
  }

  /** PLT 信息表格弹窗确认 —— 携手输字段 + 文件名按打开时的变体导出（唯一提交
   *  路径，ExportInfoModal 内已落盘表格记忆；pendingPltFmt 由 handleExport 分流时
   *  写入；saveAs = 弹窗顶部文件名区确认值，2026-09-12）。 */
  function handlePltConfirm(fields: ExportTableFields, saveAs: string): void {
    void exportAs(pendingPltFmt, filterSizes(), doc?.filename, fields, saveAs);
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

  // 码号未选时「普通运行」按钮置灰（与 handleStart 内 sizes 非空校验同源；前置 UI 反馈，AC#7）；
  // US-013：band 闸门（未选编号 / 数量全 0）同置灰（SolveControls 应用到所有非 running 态按钮）；
  // US-004：prefix 闸门（未选前/后幅 / front==back）同置灰（无资格码不置灰 —— 后端权威拦截）。
  const startDisabled =
    form.sizes.length === 0 ||
    bandMissingLabel ||
    bandZeroQty ||
    prefixMissingLabel ||
    prefixSameLabel;

  // 初始布局 US-004：入口按钮置灰 = 无母版 || 能力探测不支持（supported === false；
  // null = 未探知不置灰 —— 探测失败不放大利害，弹窗内生成另有后端权威降级）。
  // title 悬停中文提示（无母版优先 —— 上传是任何流程的第一步）。
  const initialLayoutDisabled = doc === null || warmSupported === false;
  const initialLayoutTitle =
    doc === null
      ? '请先上传母版'
      : warmSupported === false
        ? '当前 spyrrow 版本不支持热启动'
        : '';

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
        {/* 初始布局 US-004：「高级配置：设置初始布局」入口（「设置算法参数」按钮
            正下方，per-type-wrapper 同款间距语义）。点击 openModal('initial_layout')
            —— 弹窗本体 US-006 落地（InitialLayoutModal 单例挂载在 ControlPanel），
            未挂载前点击无视觉效果（store action 已可用）。置灰两条路径见
            initialLayoutDisabled 派生（无母版 / supported === false），title 悬停
            中文提示；热启动是「普通运行」专属增益（US-007 接线），故不随 solving
            置灰（PRD 口径：disabled = 无母版 || 不支持）。 */}
        <div className="per-type-wrapper">
          <button
            type="button"
            className="per-type-btn"
            disabled={initialLayoutDisabled}
            onClick={() => openModal('initial_layout')}
            title={initialLayoutTitle}
            data-testid="initial-layout-btn"
          >
            高级配置：设置初始布局
          </button>
        </div>
        {/* 2026-09-14 运行族三级入口排序改判（用户要求）：「普通运行」（SolveControls，
            即原「普通运行」）挪到「高级运行 / 极限运行」上方 —— 三键自上而下按
            投入强度排列（普通 → 高级 → 极限），配色同日统一为绿 / 紫 / 琥珀
            （style.css .strategy-btn 注释），#2c5d8f 蓝 exclusive 归工具按钮
            （本文件两个高级配置按钮 = 树莓紫红 .per-type-btn，2026-10-05）。 */}
      </div>
      {/* US-031：data-tour="start-btn" 锚定 SolveControls 父容器（nestingTour step3 高亮目标）。 */}
      <div data-tour="start-btn">
        <SolveControls
          phase={phase}
          onStart={handleStart}
          onStop={onStop}
          startDisabled={startDisabled}
          initialChip={initialChipState}
          onClearInitial={clearInitial}
        />
      </div>
      {/* US-005 高级运行入口（策略 run 10/20/30/60min + race/se 双模式）：disabled =
          solving（互斥防 CPU 竞争）|| doc===null（未 commit 无排料数据）。
          2026-08-22 起 band 开启不再互斥（band 随 start 载荷进 config）；
          2026-08-25 起 prefix 开启同样不再互斥（prefix 同入 config）。
          US-003 极限运行入口（.strategy-entry-row 并排同级）：60/120/240/480min
          预设 + 自定义，参数全隐藏；band/prefix 开启由弹窗执行按钮置灰前置拦截
          （后端 /api/extreme/start 按键判在场即 400「暂不支持」）；同会话与高级
          运行单飞互斥由后端 409 兜底（文案区分对方）。两族轮询各自单实例
          （/api/strategy/status 与 /api/extreme/status 互不重叠）。
          2026-09-14 起从 param-form 包裹层移出、排在「普通运行」之下（运行族排序）。 */}
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
      <StatusLine text={visibleStatus} />
      {/* 状态文件 US-004：结果来源小字（合成 run 的 provenance 常驻回显 —— 区别于
          StatusLine 瞬态文案；WS 普通求解 / 无 run 时不渲染）。 */}
      {runProvenance !== undefined && (
        <div className="dim small run-provenance" data-testid="run-provenance">
          {runProvenance}
        </div>
      )}
      {/* 编辑排料 US-004：主界面入口区块（StatusLine 与导出之间 ——「导出最优方案」上方；
          编辑 = 打开 EditLayoutModal，重置 = confirm 后 editStore.reset() 回算法基线）。 */}
      <EditLayoutControls phase={phase} />
      {/* 状态文件 2026-09-12 入口改判：保存工作台状态（.msn）独立区块（「编辑排料」与
          「导出最优方案」之间）；按钮状态与导出按钮同公式同数据源（solving/exporting/
          hasLastFrame；exporting 为 saveState/exportAs 共享防连击旗 → 双向联动）。
          同日起点击先经 FileNameModal 确认文件名（handleSaveState）。 */}
      <SaveStateControls
        solving={solving}
        exporting={exporting}
        onSave={handleSaveState}
      />
      <ExportButtons solving={solving} exporting={exporting} onExport={handleExport} partial={partial} />
      {/* key 授权 US-006：「导出最优方案」区块正下方的入口 —— 打开 KeyInfoModal
          （正在使用的key 输入/替换 + 被合并 key 批量添加 + 属性展示；keyStore 经
          /api/key/state|save|merge 对账，以后端 key_state.json 为准）。 */}
      <div className="key-entry-group" data-testid="key-entry-group">
        <div className="field-label">系统key</div>
        <div className="key-entry-btns">
          <button
            type="button"
            className="key-entry-btn"
            onClick={() => openModal('key_info')}
            data-testid="key-entry-btn"
          >
            查看 / 管理
          </button>
        </div>
      </div>
      {/* 2026-09-12 需求 1：保存 / DXF·PNG 文件名确认弹窗（pendingNameTarget 非空时
          挂载；默认名在此刻合成 —— 打开时 bestRun/表单快照即预填值所见）。 */}
      {pendingNameTarget !== null && (
        <FileNameModal
          defaultName={
            pendingNameTarget.kind === 'state'
              ? defaultStateFilename(doc?.filename)
              : defaultExportFilename(
                  doc?.filename,
                  pendingNameTarget.fmt,
                  filterSizes(),
                  runRegistry.bestRun()?.finalDensity ?? 0,
                  runRegistry.bestRun()?.seed ?? 0,
                )
          }
          exporting={exporting}
          onConfirm={handleSaveNameConfirm}
          onCancel={() => setPendingNameTarget(null)}
        />
      )}
      {/* PLT 导出信息表格弹窗单例（订阅 controlPanelStore 自显隐；Portal 到 body；
          defaultName = 打开时刻合成的预填文件名（需求 2，2026-09-12）—— ControlPanel
          订阅 openModal，openModal('export_info') 触发重渲染时现算，弹窗 mount 固化）。 */}
      <ExportInfoModal
        exporting={exporting}
        onConfirm={handlePltConfirm}
        variant={pendingPltFmt}
        defaultName={defaultExportFilename(
          doc?.filename,
          pendingPltFmt,
          filterSizes(),
          runRegistry.bestRun()?.finalDensity ?? 0,
          runRegistry.bestRun()?.seed ?? 0,
        )}
      />
      {/* 编辑排料弹窗单例（US-002；打开入口在 US-004 EditLayoutControls）。 */}
      <EditLayoutModal />
      {/* 初始布局弹窗单例（prd-initial-layout US-006；订阅 controlPanelStore
          modal==='initial_layout' 自显隐；打开入口在「高级配置」区块
          initial-layout-btn）。 */}
      <InitialLayoutModal />
      {/* key 授权弹窗单例（US-006；订阅 controlPanelStore 自显隐；Portal 到 body；
          打开入口在上方「系统key」入口按钮）。 */}
      <KeyInfoModal />
    </aside>
  );
}
