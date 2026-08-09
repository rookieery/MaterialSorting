// SeekReadout —— 回放时间读数（US-006 AC#3）。
//
// 与旧 vanilla 前身 `renderAtTime` 内 `$('seek-readout').textContent = parts.join(' | ')` 等价。
// 格式：`t=X.Xs | sN yy.yy% | sM zz.zz%`
//   - t = seekTime（>=0 时）；toFixed(1) 与旧 vanilla 实现 一致
//   - 每 run 一段：s${seed} ${(frameAtTime(run,t).density*100).toFixed(2)}%
//
// 显示规则（与旧 vanilla 实现 一致）：
//   - 未全部完成 / 无 run → "—"
//   - 全部完成 → 上述格式
//
// id="seek-readout" 保留以复用 legacy CSS（monospace 字体 + 灰色）。
//
// 数据流：订阅 renderTick + seekTime → 重读 runRegistry mutable → 重渲染（轻量文本）。

import { useAppStore } from '../../store/appStore';
import { runRegistry } from '../../store/runRegistry';
import { frameAtTime } from '../../lib/seek';

export function SeekReadout(): React.JSX.Element {
  const renderTick = useAppStore((s) => s.renderTick);
  const seekTime = useAppStore((s) => s.seekTime);
  void renderTick; // 订阅 tick 以便 runRegistry push 后能重渲染

  const runs = runRegistry.list();
  const allDone = runs.length > 0 && runs.every((r) => r.done);
  if (!allDone) {
    return <div id="seek-readout">—</div>;
  }

  // 旧 vanilla 实现：t = parseInt($('seek').value, 10)；此处等价 —— 用 seekTime 或末尾。
  // 注：App.onDone 在全完成时 setSeekTime(me)，故 seekTime 通常 >= 0；防御性兜底取 maxElapsed。
  const t = seekTime >= 0 ? seekTime : 0;
  const parts: string[] = [`t=${t.toFixed(1)}s`];
  for (const r of runs) {
    const f = frameAtTime(r, t);
    if (f) parts.push(`s${r.seed} ${(f.density * 100).toFixed(2)}%`);
  }
  return <div id="seek-readout">{parts.join(' | ')}</div>;
}
