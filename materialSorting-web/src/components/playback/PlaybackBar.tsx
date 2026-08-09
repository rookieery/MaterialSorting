// PlaybackBar —— 回放面板容器（US-006 AC#1..#3）。
//
// 与旧 legacy/index.html `<div class="playback">` + 旧 app.js checkAllDone 启用 seekbar 等价。
//   - 求解中 / 未启动：disabled，max=0
//   - 全部 run 完成：max = ceil(maxElapsed)（PlaybackBar 计算），Seekbar 默认 value=末尾
//   - SeekReadout：见组件注释
//
// 启用判定：runs.length > 0 && runs.every(done)（与旧 app.js `if (!runs.every(r=>r.done)) return` 一致）。
//
// 订阅 renderTick 用于在 done 状态切换时（frame 推送 / final）重渲染。

import { useAppStore } from '../../store/appStore';
import { runRegistry } from '../../store/runRegistry';
import { maxElapsed } from '../../lib/seek';
import { Seekbar } from './Seekbar';
import { SeekReadout } from './SeekReadout';

export function PlaybackBar(): React.JSX.Element {
  const renderTick = useAppStore((s) => s.renderTick);
  void renderTick; // 订阅 tick：frame push 后重算 allDone / max

  const runs = runRegistry.list();
  const allDone = runs.length > 0 && runs.every((r) => r.done);
  const max = allDone ? Math.ceil(maxElapsed(runs)) : 0;

  return (
    <div className="playback">
      <div className="field-label">回放</div>
      <Seekbar max={max} disabled={!allDone} />
      <SeekReadout />
    </div>
  );
}
