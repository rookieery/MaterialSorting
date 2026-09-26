// NestLabel —— 排料卡片顶部标签（seed N · X.XX% · 长度 X.XX cm · 用时 N 秒 / 错误 / 等待）。
//
// 与旧 vanilla 实现 `run.label.textContent` 等价。订阅 renderTick，每次 bump 重读 mutable run 状态。
// 不直接订阅 run.frames / run.lastFrame —— 那是 mutable 引用，React 检测不到变化。
//
// 注：NestLabel 本身仍走 React reconciliation，但因为只是文本节点、且 ~10fps 重渲染，开销可忽略。

import { useMemo } from 'react';
import { useAppStore } from '../../store/appStore';
import type { RunRecord } from '../../store/runRegistry';

export interface NestLabelProps {
  run: RunRecord;
}

/** 秒 → 「N 秒」整数秒（用户 2026-09-26 定案：直接以秒计，不做分:秒进制）。 */
function fmtSeconds(sec: number): string {
  return `${Math.max(0, Math.floor(sec))} 秒`;
}

/**
 * 「用时」段（曲线/回放 2026-09-12 移除后普通求解唯一的时间观测面）：
 *   - 运行中：前端墙钟动态走表（performance.now() - startedAt，覆盖首帧到达前的
 *     连接/spawn/band·prefix 构造盲窗），随 renderTick ~10fps 刷新 —— 无需新 timer；
 *   - done：finalElapsed（服务器墙钟终值）优先定格；stopped/异常（无 final）回退
 *     endedAt-startedAt 定格 —— renderTick 在 done 后仍持续 bump，但读的是定格值不再增长；
 *   - error：不显示（错误文案优先）；合成 run 未传终值（差值 <1s，真实求解不可能）
 *     → 无意义的 00:00 不显示（恢复兜底路径 / status null 极端时序）。
 */
function elapsedSuffix(run: RunRecord): string {
  if (run.error) return '';
  let sec: number;
  if (!run.done) {
    sec = (performance.now() - run.startedAt) / 1000;
  } else if (run.finalElapsed !== null && run.finalElapsed > 0) {
    sec = run.finalElapsed;
  } else if (run.endedAt - run.startedAt >= 1000) {
    sec = (run.endedAt - run.startedAt) / 1000;
  } else {
    return '';
  }
  return ` · 用时 ${fmtSeconds(sec)}`;
}

export function NestLabel({ run }: NestLabelProps) {
  // 订阅 renderTick —— bump 时组件重渲染，从而重读 mutable run.lastFrame。
  const renderTick = useAppStore((s) => s.renderTick);
  const text = useMemo(() => {
    void renderTick; // 显式声明依赖（与 dep array 配合，便于 lint / 阅读）
    if (run.error) return `seed ${run.seed} 错误：${run.error}`;
    if (run.lastFrame) {
      const pct = (run.lastFrame.density * 100).toFixed(2);
      // 用布长度（cm，两位小数，版师 2026-08-28 要求）：与导出标题 L=xx.xxcm 同口径（width_mm/10）。
      // 门幅/总面积固定时利用率↑ ⇔ 长度↓，随 renderTick 跟 lastFrame.density 同步刷新。
      const cm = (run.lastFrame.width_mm / 10).toFixed(2);
      return `seed ${run.seed} · ${pct}% · 长度 ${cm} cm${elapsedSuffix(run)}`;
    }
    if (run.manifest) return `seed ${run.seed} · ${run.manifest.pieces.length} 片${elapsedSuffix(run)}`;
    return `seed ${run.seed} …${elapsedSuffix(run)}`;
  }, [renderTick, run]);

  return <div className="nest-label">{text}</div>;
}
