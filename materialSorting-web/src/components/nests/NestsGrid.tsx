// NestsGrid —— 排料卡片网格容器（旧 vanilla 实现 `#nests` 容器 + makeRun 创建 .nest-card 序列）。
//
// 与旧 vanilla 实现 startSolve 内 `for (let i=0; i<n; i++) runs.push(makeRun(baseSeed+i))` 等价：
//   App 持有 seeds 列表（base+i 序列），NestsGrid 根据 seeds 在 runRegistry 里查 RunRecord，
//   找到则挂载 NestCard（key=seed，稳定）。挂载/卸载只发生在 seeds 列表变化时；
//   NestSVG 内部已通过订阅 renderTick 做命令式更新，无需 NestsGrid 介入。
//
// 注：runRegistry 是 mutable 不订阅，但 seeds 列表来自 App state，变化触发 NestsGrid 重渲染，
// 重新 list().find(seed) 拿到最新 RunRecord（start() 调用早于本次重渲染，故 find 必中）。

import { runRegistry, type RunRecord } from '../../store/runRegistry';
import { NestCard } from './NestCard';

export interface NestsGridProps {
  /** 已 start 的 seed 列表（base+i, i=0..N-1）。每个 seed 对应一张 NestCard。 */
  seeds: number[];
}

export function NestsGrid({ seeds }: NestsGridProps) {
  return (
    <div id="nests" className="nests">
      {seeds.map((seed) => {
        const rec: RunRecord | undefined = runRegistry.list().find((r) => r.seed === seed);
        return rec ? <NestCard key={seed} run={rec} /> : null;
      })}
    </div>
  );
}
