// ControlPanel —— 左侧参数面板（与旧 index.html `<aside class="panel">` 等价）。
//
// 表单状态由本组件持有（DEFAULT_FORM 初值），各子组件受控。
// 点击 SolveControls「开始求解」时（idle 态）：
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

import { useState } from 'react';
import { useExport } from '../../hooks/useExport';
import type { ExportFmt } from '../../lib/download';
import { useUploadStore } from '../../store/uploadStore';
import { useQtyStore } from '../../store/qtyStore';
import { ExportButtons } from './ExportButtons';
import { MultiSeedControls } from './MultiSeedControls';
import { ParamForm } from './ParamForm';
import { PerTypeOverrides } from './PerTypeOverrides';
import { SizePicker } from './SizePicker';
import { SolveControls } from './SolveControls';
import { StatusLine } from './StatusLine';
import {
  collectParams,
  DEFAULT_FORM,
  parseGate,
  parseSeed,
  parseSeedCount,
  parseTime,
  serializeQuantities,
  type FormState,
} from '../../lib/params';
import type { PerTypeOverrides as PerTypeOverridesValue, SolveParams } from '../../types/v03';
import type { SolvePhase } from '../../types/solvePhase';

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
  /** US-027 重新开始回调（US-028 由 SolveControls 重新开始/再次求解按钮接线）。 */
  onRestart: () => void;
}

export function ControlPanel({ onStart, phase, status, onStatus, onStop, onRestart }: ControlPanelProps) {
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  // US-017：订阅 uploadStore.doc 判断是否已解析母版（doc=null → StatusLine 增提示）。
  const doc = useUploadStore((s) => s.doc);

  // US-028：从 phase 派生 solving（running 态冻结参数编辑 + 禁用 ExportButtons）。
  // stopped/done/error 态可编辑参数（用户改参数后走 onStart → handleStart 用新值，覆盖 lastStartCfgRef）。
  const solving = phase === 'running';

  // US-007：useExport 挂在 ControlPanel 内（form.sizes 与 exportAs 同处）。
  // onStatus 透传到 NestingPage.setStatus → StatusLine（导出中 / 完成 / 失败文案由 useExport 写）。
  const { exportAs, exporting } = useExport({ onStatus });

  /** 通用 patch 更新（部分字段）。 */
  function patch(p: Partial<FormState>) {
    setForm((prev) => ({ ...prev, ...p }));
  }

  function handleStart() {
    if (solving) return;
    if (form.sizes.length === 0) {
      onStatus('请至少选一个码号');
      return;
    }
    const { params, per_type } = collectParams(form);
    // US-017：form.sizes 可能含 null（通用码），下游 WS / export 契约仍是 number[]，
    // 此处过滤 null（M1787 实际母版无 null 码；含 null 母版的完整支持见 US-022）。
    const sizesNum: number[] = form.sizes.filter(
      (s: number | null): s is number => s !== null,
    );
    // US-022：从 qtyStore.quantities 序列化扁平化为 label→sizeKey→demand。
    //   - getState() 读快照（不订阅，避免 ControlPanel 因数量编辑频繁重渲染）。
    //   - sizesNum 已过滤 null；global 模式展开依赖此列表枚举 sizeKey。
    const quantities = serializeQuantities(
      useQtyStore.getState().quantities,
      sizesNum,
    );
    onStart({
      sizes: sizesNum,
      gate_mm: parseGate(form),
      time: parseTime(form),
      seed: parseSeed(form),
      seed_count: parseSeedCount(form),
      params,
      per_type,
      quantities,
    });
  }

  /** 导出按钮回调 —— 透传 form.sizes（过滤 null）给 useExport.exportAs（与旧 vanilla 实现 `sizes: selectedSizes()` 一致）。 */
  function handleExport(fmt: ExportFmt): void {
    const sizesNum: number[] = form.sizes.filter(
      (s: number | null): s is number => s !== null,
    );
    void exportAs(fmt, sizesNum);
  }

  // US-017：doc=null 时 StatusLine 增提示「请先在上传预览页解析母版」（AC#3）。
  const visibleStatus =
    doc === null ? `${status} — 请先在上传预览页解析母版` : status;

  // US-028：stopped/error（有帧）态导出时明确标注「中间方案」（AC#3）。
  //   - stopped 总是有帧（停止前至少推过一帧或收到过 manifest；若无帧 ExportButtons 自身 disabled 兜底）。
  //   - error 可能在收到帧前发生（构造失败）→ 此时 ExportButtons 也 disabled，partial flag 仅作 UI 提示触发条件。
  const partial = phase === 'stopped' || phase === 'error';

  // 码号未选时「开始求解」按钮置灰（与 handleStart 内 sizes 非空校验同源；前置 UI 反馈，AC#7）。
  // SolveControls 把 startDisabled 应用到所有非 running 态的「开始求解」按钮。
  const startDisabled = form.sizes.length === 0;

  return (
    <aside className="panel">
      <h2>求解控制</h2>
      <SizePicker selected={form.sizes} onChange={(sizes) => patch({ sizes })} disabled={solving} />
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
      <PerTypeOverrides values={form.per_type} onChange={(per_type) => patch({ per_type })} disabled={solving} />
      <SolveControls phase={phase} onStart={handleStart} onStop={onStop} onRestart={onRestart} startDisabled={startDisabled} />
      <StatusLine text={visibleStatus} />
      <ExportButtons solving={solving} exporting={exporting} onExport={handleExport} partial={partial} />
      <div className="hint">
        density = 原面积口径（与 90% 生死线一致）；sparrow 口径见状态行。
        <br />
        重合 erode / 旋转公差按每片型 v0.3 上限覆盖 —— 见「高级配置」弹窗。
        <br />
        实时图 ~10fps 重绘，全量中间帧存档，结束后可拖回放。
      </div>
    </aside>
  );
}
