// SizeLegend —— 尺码 → 颜色图例（.nest-card 内右上角 HTML overlay）。
//
// 2026-08-20 配色换键为尺码（后端 size_color 单一真相源：同码同色跨片型一致）后新增：
// 画布 8~11 个尺码颜色肉眼难分，图例直接对照。此前画布无图例（只有导出 PNG / CLI
// SVG 有）。
// - 条目 = manifest.pieces 的 size→color 去重（数值序升序）；跨片型同码必然同色
//   （后端保证），去重取首个命中即可。
// - manifest 缺席（未求解）/ 无有效尺码 → 不渲染。
// - 纯 React 静态渲染：仅随 run.manifest 引用变化重渲，零帧级开销（与 NestSVG 的
//   命令式帧渲染无关）；pointer-events none 不挡裁片 hover/tooltip。

import type { RunRecord } from '../../store/runRegistry';

export interface SizeLegendProps {
  run: RunRecord;
}

export function SizeLegend({ run }: SizeLegendProps) {
  const pieces = run.manifest?.pieces;
  if (!pieces || pieces.length === 0) return null;

  const bySize = new Map<number, string>();
  for (const p of pieces) {
    if (p.size == null) continue;            // 防御：旧后端/异常数据 size 可空
    if (!bySize.has(p.size)) bySize.set(p.size, p.color);
  }
  const entries = [...bySize.entries()].sort((a, b) => a[0] - b[0]);
  if (entries.length === 0) return null;

  return (
    <div className="size-legend">
      <div className="size-legend-title">尺码</div>
      {entries.map(([size, color]) => (
        <div className="size-legend-row" key={size}>
          <span
            className="size-legend-swatch"
            style={{ background: color, borderColor: color }}
          />
          <span className="size-legend-label">{size}</span>
        </div>
      ))}
    </div>
  );
}
