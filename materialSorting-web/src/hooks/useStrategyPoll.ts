// useStrategyPoll —— 策略运行活性轮询闸（US-005；US-003 起族参数化）。
//
// 挂载点：StrategyRunButton / ExtremeRunButton（各自常驻，弹窗开闭都活着 ——
// 关弹窗也要维持入口徽标）。单族单实例单 setInterval：每族恰一个挂载点、各轮询
// 各自端点（/api/strategy/status 与 /api/extreme/status 互不重叠 ⇒ 无双跑轮询）；
// Modal 不挂本 hook，避免双重轮询。idle 态轻量：仅 mount/open 翻转各 refresh 一次
// （无 interval —— 后端两族共用单飞槽，idle 探测一次足矣）。
//
// 节奏（AC）：
//   - mount / open 翻转 → 立即 refresh 一次（status 无状态：页面刷新 / 重开弹窗
//     即恢复进度 —— orphan/running 均在这一次被发现）。
//   - 活性态（starting/running）：弹窗开 2s / 关 15s setInterval 调 refresh
//     （开弹窗看细粒度进度；关弹窗低频维持入口「运行中」徽标）。
//   - 终态（idle/done/stopped/error/orphan）停轮询 —— 后端产物不再变化，
//     状态只经用户动作（start/stop/reset）或下一次 mount refresh 改变。
//
// phase 从 store 订阅：状态切换 → effect 重跑重建 interval（周期随
// open 翻转同步切换）；refresh 本身幂等（后端无状态现读产物）。

import { useEffect } from 'react';
import { useStrategyStore } from '../store/strategyStore';
import type { StrategyPhase } from '../types/strategy';

/** 弹窗开 / 关轮询周期（毫秒）。 */
export const STRATEGY_POLL_OPEN_MS = 2000;
export const STRATEGY_POLL_CLOSED_MS = 15000;

/** 活性态 = 需要持续轮询的 phase（终态 idle/done/stopped/error/orphan 停）。 */
export function isStrategyActive(phase: string): boolean {
  return phase === 'starting' || phase === 'running';
}

/** 轮询闸可接受的 store 形状（zustand hook + getState；两族 store 均结构满足）。 */
interface PollableRunStore {
  (selector: (s: { phase: StrategyPhase }) => StrategyPhase): StrategyPhase;
  getState: () => { refresh: () => Promise<void> };
}

/**
 * 运行轮询闸（strategy / extreme 两族共用实现）。
 * @param open 弹窗是否打开（true → 2s 细粒度；false → 15s 低频维持徽标）。
 * @param store 目标族 store（缺省策略族 —— 既有调用点签名不变）。
 */
export function useStrategyPoll(
  open: boolean,
  store: PollableRunStore = useStrategyStore as PollableRunStore,
): void {
  const phase = store((s) => s.phase);

  // mount / open 翻转 → 立即对齐一次（恢复进度的唯一入口）。
  useEffect(() => {
    void store.getState().refresh();
  }, [open, store]);

  // 活性态 interval（终态不建；phase/open 变化 → cleanup 重建切周期）。
  useEffect(() => {
    if (!isStrategyActive(phase)) return;
    const period = open ? STRATEGY_POLL_OPEN_MS : STRATEGY_POLL_CLOSED_MS;
    const id = setInterval(() => {
      void store.getState().refresh();
    }, period);
    return () => clearInterval(id);
  }, [phase, open, store]);
}
