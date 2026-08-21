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
//   - 互斥：band 开启时「高级运行」入口 disabled + title 说明原因（FR-6 v1 互斥 ——
//     strategy_start 只拷白名单键，band 不进 CLI config，前端禁入口是唯一防线）；
//   - PerTypeOverrides 透传 band/onBandChange/buildStartContext（弹窗布局设置分区 +
//     预演 /api/band/preview）；
//   - form.band_* → bandStore 单向镜像（useEffect 同步）—— QtyMatrix（上传预览页）跨页
//     读该镜像做「该码不成对」奇数数量警告，props 无通路。
// US-015（v1.1 填料混带）：form.band_fillers（弹窗填料行多选）随 band 透传 WS
//   ``band.fillers``；启动闸门对填料同口径 —— 任一填料所选码数量全 0 → 「开始求解」
//   置灰 + StatusLine 报首个冒犯 g 码（与后端 _parse_band quantities>0 校验对齐）。

import { useCallback, useEffect, useState } from 'react';
import { useExport } from '../../hooks/useExport';
import type { ExportFmt } from '../../lib/download';
import { useUploadStore } from '../../store/uploadStore';
import { useQtyStore } from '../../store/qtyStore';
import { useBandStore } from '../../store/bandStore';
import { ExportButtons } from './ExportButtons';
import { MultiSeedControls } from './MultiSeedControls';
import { ParamForm } from './ParamForm';
import { PerTypeOverrides } from './PerTypeOverrides';
import { SizePicker, computeTotalCutPieces } from './SizePicker';
import { SolveControls } from './SolveControls';
import { StatusLine } from './StatusLine';
import { StrategyRunButton } from './StrategyRunButton';
import {
  bandMemberCount,
  collectStartContext,
  DEFAULT_FORM,
  parseSeedCount,
  type FormState,
} from '../../lib/params';
import type { PerTypeOverrides as PerTypeOverridesValue, SolveParams } from '../../types/v03';
import type { StrategyResult } from '../../types/strategy';
import type { SolvePhase } from '../../types/solvePhase';
import type { BandConfig } from '../../types/ws';

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
   */
  onApplyStrategy?: (result: StrategyResult) => void;
}

export function ControlPanel({ onStart, phase, status, onStatus, onStop, onApplyStrategy }: ControlPanelProps) {
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  // US-017：订阅 uploadStore.doc 判断是否已解析母版（doc=null → StatusLine 增提示）。
  const doc = useUploadStore((s) => s.doc);
  // US-013：订阅 quantities —— band 启动闸门（选中 g 码数量全 0 → 置灰）需要对数量
  // 矩阵编辑**响应式**（handleStart 内仍 getState() 现取快照，口径同源）。
  const quantities = useQtyStore((s) => s.quantities);

  // US-028：从 phase 派生 solving（running 态冻结参数编辑 + 禁用 ExportButtons）。
  // stopped/done/error 态可编辑参数（用户改参数后点「开始求解」→ handleStart 即用新值）。
  const solving = phase === 'running';

  // US-013：form.band_* → bandStore 单向镜像（QtyMatrix「该码不成对」警告的跨页数据源；
  // form 仍是 WS 载荷单一真相源，store 仅派生镜像）。
  const setBandMirror = useBandStore((s) => s.setBand);
  useEffect(() => {
    setBandMirror(form.band_enabled, form.band_label);
  }, [form.band_enabled, form.band_label, setBandMirror]);

  // US-007：useExport 挂在 ControlPanel 内（form.sizes 与 exportAs 同处）。
  // onStatus 透传到 NestingPage.setStatus → StatusLine（导出中 / 完成 / 失败文案由 useExport 写）。
  const { exportAs, exporting } = useExport({ onStatus });

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
  // US-015：填料同闸门口径（首个数量全 0 的填料报具体 g 码 —— 后端 _parse_band 对
  // 填料 quantities>0 同校验，此处前置）。
  const bandMissingLabel =
    form.band_enabled && form.band_label.trim() === '';
  const bandZeroQty =
    form.band_enabled &&
    form.band_label.trim() !== '' &&
    bandMemberCount(form, quantities, form.band_label.trim()) === 0;
  const bandFillerZeroLabel = form.band_enabled
    ? form.band_fillers.find(
        (f) => f.trim() !== '' && bandMemberCount(form, quantities, f.trim()) === 0,
      )
    : undefined;

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
    if (bandFillerZeroLabel !== undefined) {
      onStatus(
        `填料 ${bandFillerZeroLabel} 所选码数量全 0，请先在上传预览页数量矩阵设置数量`,
      );
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

  /** 导出按钮回调 —— 透传 form.sizes（过滤 null）给 useExport.exportAs（与旧 vanilla 实现 `sizes: selectedSizes()` 一致）。 */
  function handleExport(fmt: ExportFmt): void {
    const sizesNum: number[] = form.sizes.filter(
      (s: number | null): s is number => s !== null,
    );
    void exportAs(fmt, sizesNum, doc?.filename);
  }

  // US-017：doc=null 时 StatusLine 增提示「请先在上传预览页解析母版」（AC#3）；
  // US-013：band 闸门态追加 band 段具体文案（与 startDisabled 同源派生）；
  // US-015：填料数量全 0 同报（首个冒犯 g 码）。
  const bandHint = bandMissingLabel
    ? '已开启腰头成带，请先选择腰头编号（高级配置 → 布局设置）'
    : bandZeroQty
      ? `腰头 ${form.band_label.trim()} 所选码数量全 0，请先在上传预览页数量矩阵设置数量`
      : bandFillerZeroLabel !== undefined
        ? `填料 ${bandFillerZeroLabel} 所选码数量全 0，请先在上传预览页数量矩阵设置数量`
        : '';
  const visibleStatus = [status, doc === null ? '请先在上传预览页解析母版' : '', bandHint]
    .filter(Boolean)
    .join(' — ');

  // US-028：stopped/error（有帧）态导出时明确标注「中间方案」（AC#3）。
  //   - stopped 总是有帧（停止前至少推过一帧或收到过 manifest；若无帧 ExportButtons 自身 disabled 兜底）。
  //   - error 可能在收到帧前发生（构造失败）→ 此时 ExportButtons 也 disabled，partial flag 仅作 UI 提示触发条件。
  const partial = phase === 'stopped' || phase === 'error';

  // 码号未选时「开始求解」按钮置灰（与 handleStart 内 sizes 非空校验同源；前置 UI 反馈，AC#7）；
  // US-013：band 闸门（未选编号 / 数量全 0）同置灰（SolveControls 应用到所有非 running 态按钮）；
  // US-015：填料数量全 0 同置灰。
  const startDisabled =
    form.sizes.length === 0 ||
    bandMissingLabel ||
    bandZeroQty ||
    bandFillerZeroLabel !== undefined;

  // US-013（FR-6）：band 开启时「高级运行」互斥置灰 + title 说明原因（既有 solving /
  // 未 commit 置灰不加说明 —— title 仅 band 互斥时给，避免与旧语义混淆）。
  const strategyBandLocked = form.band_enabled && !solving && doc !== null;

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
      {/* US-031 params 步锚点：包裹幅宽/时长/seed（ParamForm）+ multi_seed（MultiSeedControls）
          + 高级配置（PerTypeOverrides）整个「求解参数」区。码号多选（SizePicker）在其上独立成区不纳入。 */}
      <div data-tour="param-form">
        <ParamForm
          gate={form.gate}
          time={form.time}
          seed={form.seed}
          onGate={(gate) => patch({ gate })}
          onTime={(time) => patch({ time })}
          onSeed={(seed) => patch({ seed })}
          disabled={solving}
        />
        <MultiSeedControls
          multi_seed={form.multi_seed}
          seed_count={form.seed_count}
          onMulti={(multi_seed) => patch({ multi_seed })}
          onCount={(seed_count) => patch({ seed_count })}
          disabled={solving}
        />
        <PerTypeOverrides
          values={form.per_type}
          onChange={(per_type) => patch({ per_type })}
          band={{
            enabled: form.band_enabled,
            label: form.band_label,
            ack: form.band_ack,
            fillers: form.band_fillers,
          }}
          onBandChange={(band) =>
            patch({
              band_enabled: band.enabled,
              band_label: band.label,
              band_ack: band.ack,
              band_fillers: band.fillers,
            })
          }
          buildStartContext={buildStartContext}
          disabled={solving}
        />
        {/* US-005 高级运行入口（策略 run 10/20/30/60min + race/se 双模式）：disabled =
            solving（互斥防 CPU 竞争）|| doc===null（未 commit 无排料数据）
            || US-013 band 开启（FR-6 与腰头成带互斥，title 说明原因）。 */}
        <StrategyRunButton
          solving={solving}
          buildStartContext={buildStartContext}
          onApplyStrategy={onApplyStrategy}
          disabled={solving || doc === null || form.band_enabled}
          title={
            strategyBandLocked
              ? '腰头成带与策略运行互斥：请先在高级配置 → 布局设置中关闭腰头成带'
              : undefined
          }
        />
      </div>
      {/* US-031：data-tour="start-btn" 锚定 SolveControls 父容器（nestingTour step3 高亮目标）。 */}
      <div data-tour="start-btn">
        <SolveControls phase={phase} onStart={handleStart} onStop={onStop} startDisabled={startDisabled} />
      </div>
      <StatusLine text={visibleStatus} />
      <ExportButtons solving={solving} exporting={exporting} onExport={handleExport} partial={partial} />
    </aside>
  );
}
