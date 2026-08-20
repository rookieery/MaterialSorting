// useStrategyPoll —— 策略运行活性轮询闸（US-005）。
//
// 挂载点：StrategyRunButton（常驻，弹窗开闭都活着 —— 关弹窗也要维持入口徽标）。
// 单实例单 setInterval：StrategyRunModal 不再挂本 hook，避免双重轮询。
//
// 节奏（AC）：
//   - mount / open 翻转 → 立即 refresh 一次（status 无状态：页面刷新 / 重开弹窗
//     即恢复进度 —— orphan/running 均在这一次被发现）。
//   - 活性态（starting/running）：弹窗开 2s / 关 15s setInterval 调 refresh
//     （开弹窗看细粒度进度；关弹窗低频维持入口「运行中」徽标）。
//   - 终态（idle/done/stopped/error/orphan）停轮询 —— 后端产物不再变化，
//     状态只经用户动作（start/stop/reset）或下一次 mount refresh 改变。
//
// phase 从 strategyStore 订阅：状态切换 → effect 重跑重建 interval（周期随
// open 翻转同步切换）；refresh 本身幂等（后端无状态现读产物）。

import { useEffect } from 'react';
import { useStrategyStore } from '../store/strategyStore';

/** 弹窗开 / 关轮询周期（毫秒）。 */
export const STRATEGY_POLL_OPEN_MS = 2000;
export const STRATEGY_POLL_CLOSED_MS = 15000;

/** 活性态 = 需要持续轮询的 phase（终态 idle/done/stopped/error/orphan 停）。 */
export function isStrategyActive(phase: string): boolean {
  return phase === 'starting' || phase === 'running';
}

/**
 * 策略运行轮询闸。
 * @param open 弹窗是否打开（true → 2s 细粒度；false → 15s 低频维持徽标）。
 */
export function useStrategyPoll(open: boolean): void {
  const phase = useStrategyStore((s) => s.phase);

  // mount / open 翻转 → 立即对齐一次（恢复进度的唯一入口）。
  useEffect(() => {
    void useStrategyStore.getState().refresh();
  }, [open]);

  // 活性态 interval（终态不建；phase/open 变化 → cleanup 重建切周期）。
  useEffect(() => {
    if (!isStrategyActive(phase)) return;
    const period = open ? STRATEGY_POLL_OPEN_MS : STRATEGY_POLL_CLOSED_MS;
    const id = setInterval(() => {
      void useStrategyStore.getState().refresh();
    }, period);
    return () => clearInterval(id);
  }, [phase, open]);
}
