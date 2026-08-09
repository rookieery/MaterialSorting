// NestLabel —— 排料卡片顶部标签（seed N · X.XX% / 错误 / 等待）。
//
// 与旧 app.js `run.label.textContent` 等价。订阅 renderTick，每次 bump 重读 mutable run 状态。
// 不直接订阅 run.frames / run.lastFrame —— 那是 mutable 引用，React 检测不到变化。
//
// 注：NestLabel 本身仍走 React reconciliation，但因为只是文本节点、且 ~10fps 重渲染，开销可忽略。

import { useMemo } from 'react';
import { useAppStore } from '../../store/appStore';
import type { RunRecord } from '../../store/runRegistry';

export interface NestLabelProps {
  run: RunRecord;
}

export function NestLabel({ run }: NestLabelProps) {
  // 订阅 renderTick —— bump 时组件重渲染，从而重读 mutable run.lastFrame。
  const renderTick = useAppStore((s) => s.renderTick);
  const text = useMemo(() => {
    void renderTick; // 显式声明依赖（与 dep array 配合，便于 lint / 阅读）
    if (run.error) return `seed ${run.seed} 错误：${run.error}`;
    if (run.lastFrame) {
      const pct = (run.lastFrame.density * 100).toFixed(2);
      return `seed ${run.seed} · ${pct}%`;
    }
    if (run.manifest) return `seed ${run.seed} · ${run.manifest.pieces.length} 片`;
    return `seed ${run.seed} …`;
  }, [renderTick, run]);

  return <div className="nest-label">{text}</div>;
}
