// ExportButtons —— 导出 PNG / DXF 按钮组（US-007 AC#6）。
//
// 与旧 legacy/index.html `<div class="export-group">` + 旧 vanilla 实现 updateExportButtons 等价：
//   - 求解中（solving=true）→ disabled
//   - registry 无 lastFrame run（未求解 / 求解未完成）→ disabled
//   - 导出中（exporting=true）→ disabled（双按钮同步禁用，与旧 vanilla 实现 同时设 export_png/dxf 一致）
//
// AC#6 字面：求解未完成或无 lastFrame 时按钮 disabled；导出中按钮 disabled + StatusLine
// 显示 正在生成 PNG/DXF…（StatusLine 文案由 useExport 写 onStatus）。
//
// DOM 沿用旧 style.css `.export-group` / `.export-btns` / `button.export`（US-008 前 CSS 不动）；
// id 保留 export_png / export_dxf（旧 CSS 选择器依赖；US-008 清理时去 id）。
//
// 订阅 renderTick：lastFrame 是 mutable push 到 registry 不进 React state；求解 final 到达后
// 靠 useRafThrottle bump renderTick 触发本组件 reconciliation，重算 hasLastFrame。
//
// US-028：新增 `partial` prop —— stopped/error（有帧）态导出时显示「中间方案」警示文案
// （AC#3：明确告知用户导出的是停止/出错时刻的中间方案，非最终最优解）。
// 文件名仍按当前 density 命名（真实口径，反映该中间方案利用率），不加 _partial 后缀。

import { useAppStore } from '../../store/appStore';
import { runRegistry } from '../../store/runRegistry';
import type { ExportFmt } from '../../lib/download';

export interface ExportButtonsProps {
  /** 求解中（按钮 disabled）。来自 ControlPanel phase==='running' 派生。 */
  solving: boolean;
  /** 导出中（按钮 disabled，双按钮同步）。来自 ControlPanel.useExport.exporting。 */
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

  // hasLastFrame = registry 至少有一个 run 推过 frame（与旧 vanilla 实现 updateExportButtons
  // `runs.some(r => r.lastFrame)` 一致）。bestRun() 也按 lastFrame 过滤，但这里用 some() 显式
  // 表达「只要存在 lastFrame 即可点」（与旧版同语义；bestRun 留给 useExport 内做最终选择）。
  const hasLastFrame = runRegistry.list().some((r) => r.lastFrame !== null);
  const disabled = solving || exporting || !hasLastFrame;

  return (
    <div className="export-group">
      <div className="field-label">导出最优方案</div>
      <div className="export-btns">
        <button
          id="export_png"
          type="button"
          className="export"
          disabled={disabled}
          onClick={() => onExport('png')}
        >
          导出 PNG
        </button>
        <button
          id="export_dxf"
          type="button"
          className="export"
          disabled={disabled}
          onClick={() => onExport('dxf')}
        >
          导出 DXF
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
