// NestCard —— 单 run 卡片（顶部 NestLabel + 主体 NestSVG + 尺码图例 overlay）。
//
// 与旧 vanilla 实现 `makeRun` 创建的 .nest-card 等价：纵向布局，label 在上、svg 占满剩余高度。
// CSS（.nest-card / .nest-label / .nest-card svg）已在 style.css 定义，沿用 legacy。
// 2026-08-20：配色换键为尺码后，右上角新增 SizeLegend（HTML overlay，manifest 缺席不渲染）。

import type { RunRecord } from '../../store/runRegistry';
import { NestLabel } from './NestLabel';
import { NestSVG } from './NestSVG';
import { SizeLegend } from './SizeLegend';

export interface NestCardProps {
  run: RunRecord;
}

export function NestCard({ run }: NestCardProps) {
  return (
    <div className="nest-card">
      <NestLabel run={run} />
      <NestSVG run={run} />
      <SizeLegend run={run} />
    </div>
  );
}
