// ControlPanel —— 左侧参数面板（与旧 index.html `<aside class="panel">` 等价）。
//
// 表单状态由本组件持有（DEFAULT_FORM 初值），各子组件受控。
// 点击 StartButton 时：
//   1. 校验 sizes 非空 —— 空 → onStatus('请至少选一个码号') + 不启动（AC#7）。
//   2. collectParams → { params, per_type }；parseTime / parseSeed / parseSeedCount 解析。
//   3. onStart({ sizes, time, seed, seed_count, params, per_type }) 透传到 App
//      （AC#6 触发 useSolveRun.start × N，N = seed_count）。
//
// solving / status 来自 App：solving=true 禁用 StartButton；status 由 StatusLine 直接渲染。
// US-005 落地 multi_seed 开关 + seed_count；US-007 接管 ExportButtons（useExport 也住这里，
// 因为 sizes 在本组件 form 里 —— 旧 vanilla 实现 exportAs 内 `sizes: selectedSizes()` 同源）。

import { useState } from 'react';
import { useExport } from '../../hooks/useExport';
import type { ExportFmt } from '../../lib/download';
import { ErodeInputs } from './ErodeInputs';
import { ExportButtons } from './ExportButtons';
import { MultiSeedControls } from './MultiSeedControls';
import { ParamForm } from './ParamForm';
import { PerTypeOverrides } from './PerTypeOverrides';
import { PresetButtons } from './PresetButtons';
import { SizePicker } from './SizePicker';
import { StartButton } from './StartButton';
import { StatusLine } from './StatusLine';
import { ToleranceInputs } from './ToleranceInputs';
import {
  collectParams,
  DEFAULT_FORM,
  parseSeed,
  parseSeedCount,
  parseTime,
  type FormState,
} from '../../lib/params';
import type { PerTypeOverrides as PerTypeOverridesValue, SolveParams } from '../../types/v03';

/** onStart 透传给 App 的载荷（直接喂给 useSolveRun.start 的 StartConfig 子集）。 */
export interface ControlPanelStartPayload {
  sizes: number[];
  time: number;
  /** base seed（seed = base+i, i=0..N-1）。 */
  seed: number;
  /** 实际并行启动的 seed 数量（multi_seed=false → 1；true → clamp(seed_count,2,6)）。 */
  seed_count: number;
  params: SolveParams;
  per_type: PerTypeOverridesValue | null;
}

export interface ControlPanelProps {
  /** 点击启动（已通过码号非空校验）。 */
  onStart: (cfg: ControlPanelStartPayload) => void;
  /** 求解中（禁用 StartButton）。 */
  solving: boolean;
  /** 状态行文案（来自 App；组装：就绪/连接中/完成/错误）。 */
  status: string;
  /** 写状态行（用于码号校验失败时把错误塞进 StatusLine）。 */
  onStatus: (text: string) => void;
}

export function ControlPanel({ onStart, solving, status, onStatus }: ControlPanelProps) {
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);

  // US-007：useExport 挂在 ControlPanel 内（form.sizes 与 exportAs 同处）。
  // onStatus 透传到 App.setStatus → StatusLine（导出中 / 完成 / 失败文案由 useExport 写）。
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
    onStart({
      sizes: form.sizes,
      time: parseTime(form),
      seed: parseSeed(form),
      seed_count: parseSeedCount(form),
      params,
      per_type,
    });
  }

  /** 导出按钮回调 —— 透传 form.sizes 给 useExport.exportAs（与旧 vanilla 实现 `sizes: selectedSizes()` 一致）。 */
  function handleExport(fmt: ExportFmt): void {
    void exportAs(fmt, form.sizes);
  }

  return (
    <aside className="panel">
      <h2>求解控制</h2>
      <SizePicker selected={form.sizes} onChange={(sizes) => patch({ sizes })} />
      <ParamForm time={form.time} seed={form.seed} onTime={(time) => patch({ time })} onSeed={(seed) => patch({ seed })} />
      <MultiSeedControls
        multi_seed={form.multi_seed}
        seed_count={form.seed_count}
        onMulti={(multi_seed) => patch({ multi_seed })}
        onCount={(seed_count) => patch({ seed_count })}
      />
      <ErodeInputs
        d_ext={form.d_ext}
        d_int={form.d_int}
        onDExt={(d_ext) => patch({ d_ext })}
        onDInt={(d_int) => patch({ d_int })}
      />
      <ToleranceInputs
        tol_ext={form.tol_ext}
        tol_int={form.tol_int}
        onTolExt={(tol_ext) => patch({ tol_ext })}
        onTolInt={(tol_int) => patch({ tol_int })}
      />
      <PresetButtons onPreset={(seconds) => patch({ time: String(seconds) })} />
      <PerTypeOverrides values={form.per_type} onChange={(per_type) => patch({ per_type })} />
      <StartButton solving={solving} onClick={handleStart} />
      <StatusLine text={status} />
      <ExportButtons solving={solving} exporting={exporting} onExport={handleExport} />
      <div className="hint">
        density = 原面积口径（与 90% 生死线一致）；sparrow 口径见状态行。
        <br />
        内部片 = 单排/双排/火机袋/裤耳；erode/旋转受 v0.3 每片型上限约束。
        <br />
        实时图 ~10fps 重绘，全量中间帧存档，结束后可拖回放。
      </div>
    </aside>
  );
}
