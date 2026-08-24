// ExportButtons —— 导出格式下拉框 + 单导出按钮（原 US-007 双按钮重构）。
//
// 演进：旧版为「导出 PNG」「导出 DXF」两个并排按钮；现为「格式下拉框（默认 PLT，2026-08-24 起）+ 单导出按钮」，
// 格式可扩展（新增格式只需扩 download.ts 的 EXPORT_FORMATS + ExportFmt + 后端 /export 路由），
// 导出按钮交互逻辑与旧双按钮完全一致。
//
// 与旧 legacy/index.html `<div class="export-group">` 语义对齐：
//   - 求解中（solving=true）→ 导出按钮 disabled
//   - registry 无 lastFrame run（未求解 / 求解未完成）→ 导出按钮 disabled
//   - 导出中（exporting=true）→ 导出按钮 disabled（防连击）
//   - 格式下拉框始终可选（求解中改选格式无害）
//
// AC#6 字面：求解未完成或无 lastFrame 时导出按钮 disabled；导出中 disabled + StatusLine
// 显示 正在生成 PNG/DXF…（StatusLine 文案由 useExport 写 onStatus）。
//
// DOM 沿用旧 style.css `.export-group` / `.export-btns` / `button.export`，新增 `select.export-fmt`。
//
// 订阅 renderTick：lastFrame 是 mutable push 到 registry 不进 React state；求解 final 到达后
// 靠 useRafThrottle bump renderTick 触发本组件 reconciliation，重算 hasLastFrame。
//
// US-028：新增 `partial` prop —— stopped/error（有帧）态导出时显示「中间方案」警示文案
// （AC#3：明确告知用户导出的是停止/出错时刻的中间方案，非最终最优解）。
// 文件名仍按当前 density 命名（真实口径，反映该中间方案利用率），不加 _partial 后缀。

import { useState } from 'react';
import { useAppStore } from '../../store/appStore';
import { runRegistry } from '../../store/runRegistry';
import { EXPORT_FORMATS, DEFAULT_EXPORT_FMT, type ExportFmt } from '../../lib/download';

export interface ExportButtonsProps {
  /** 求解中（导出按钮 disabled）。来自 ControlPanel phase==='running' 派生。 */
  solving: boolean;
  /** 导出中（导出按钮 disabled，防连击）。来自 ControlPanel.useExport.exporting。 */
  exporting: boolean;
  /** 点击导出（父级 ControlPanel 已把 form.sizes 透传给 useExport.exportAs）。 */
  onExport: (fmt: ExportFmt) => void;
  /** US-028 stopped/error（有帧）态：显示「中间方案」警示（取代默认「最优方案」提示）。 */
  partial?: boolean;
}

export function ExportButtons({ solving, exporting, onExport, partial = false }: ExportButtonsProps) {
  // 订阅 renderTick：求解结束 / final 到达后 bump → 重算 hasLastFrame（AC#6 disabled 联动）。
  // void 表达式显式标注「订阅仅为触发 reconciliation」，避免 noUnusedLocals 报错。
  const renderTick = useAppStore((s) => s.renderTick);
  void renderTick;

  // 当前选中的导出格式（组件内 state，默认 PLT——见 download.ts DEFAULT_EXPORT_FMT）。
  // 与 exporting 同为组件内轻量 state，不上推 store。
  const [fmt, setFmt] = useState<ExportFmt>(DEFAULT_EXPORT_FMT);

  // hasLastFrame = registry 至少有一个 run 推过 frame（与旧 vanilla 实现 updateExportButtons
  // `runs.some(r => r.lastFrame)` 一致）。bestRun() 也按 lastFrame 过滤，但这里用 some() 显式
  // 表达「只要存在 lastFrame 即可点」（与旧版同语义；bestRun 留给 useExport 内做最终选择）。
  const hasLastFrame = runRegistry.list().some((r) => r.lastFrame !== null);
  const disabled = solving || exporting || !hasLastFrame;

  return (
    <div className="export-group" data-tour="export-group">
      <div className="field-label">导出最优方案</div>
      <div className="export-btns">
        <select
          className="export-fmt"
          value={fmt}
          onChange={(e) => setFmt(e.target.value as ExportFmt)}
          aria-label="导出格式"
        >
          {EXPORT_FORMATS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
        <button type="button" className="export" disabled={disabled} onClick={() => onExport(fmt)}>
          导出
        </button>
      </div>
      {partial ? (
        <div className="dim small warn">
          导出的是停止 / 出错时刻的中间方案，非最终最优解。
        </div>
      ) : (
        <div className="dim small">默认导出利用率最高的 seed 的最终方案。</div>
      )}
    </div>
  );
}
