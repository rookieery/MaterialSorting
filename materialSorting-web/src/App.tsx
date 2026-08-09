// App —— 顶层三段（panel + main + bottom）。
//
// US-004：ControlPanel 接管参数输入。App 负责：
//   1. 持有 solving / status（同步 useSolveRun 各回调）。
//   2. 持有已 start 的 seed 列表（仅触发首次挂载 NestCard）。
//   3. useRafThrottle(seeds.length > 0) 跑节流闸。
//   4. ControlPanel.onStart(cfg) → runRegistry.clear + setSeeds([seed]) + start(cfg)。
//
// 数据流（与旧 app.js startSolve / connectRun 等价）：
//   ControlPanel collectParams → onStart(cfg) → useSolveRun.start → runRegistry.create + WS
//   → onmessage 推 manifest/frame/final → useRafThrottle bump renderTick → NestSVG 重绘。

import { useState } from 'react';
import { ControlPanel } from './components/ControlPanel/ControlPanel';
import { NestCard } from './components/nests/NestCard';
import { useRafThrottle } from './hooks/useRafThrottle';
import { useSolveRun } from './hooks/useSolveRun';
import { runRegistry } from './store/runRegistry';

export function App() {
  /** 已 start 的 seed 列表（仅用于触发首次挂载 NestCard）。 */
  const [seeds, setSeeds] = useState<number[]>([]);
  /** 求解中 flag —— 驱动 useRafThrottle + 禁用 StartButton。 */
  const [solving, setSolving] = useState(false);
  /** 状态行文案（ControlPanel / useSolveRun 回调都能写）。 */
  const [status, setStatus] = useState('就绪');

  const { start } = useSolveRun({
    onDone: (rec) => {
      // 单 seed 模式（US-005 起多 seed 会汇总在 checkAllDone）
      setSolving(false);
      if (rec.error) {
        setStatus(`seed ${rec.seed} 错误：${rec.error}`);
      } else if (rec.finalDensity > 0) {
        const pct = (rec.finalDensity * 100).toFixed(2);
        setStatus(`完成：seed ${rec.seed} · ${pct}%`);
      } else {
        setStatus(`seed ${rec.seed} 已结束`);
      }
    },
  });

  // 全局 ~10fps 节流闸 —— 求解中持续 bump renderTick，NestSVG 订阅后 imperative 重绘。
  useRafThrottle(seeds.length > 0);

  function handleStart(cfg: {
    sizes: number[];
    time: number;
    seed: number;
    params: import('./types/v03').SolveParams;
    per_type: import('./types/v03').PerTypeOverrides | null;
  }) {
    if (solving) return;
    // 清旧 run（关 WS + 清数组）—— 与旧 app.js startSolve 等价
    runRegistry.clear();
    setSeeds([cfg.seed]);
    setSolving(true);
    setStatus('连接中…');
    start({
      sizes: cfg.sizes,
      time: cfg.time,
      seed: cfg.seed,
      params: cfg.params,
      per_type: cfg.per_type,
    });
  }

  return (
    <div className="app">
      <ControlPanel onStart={handleStart} solving={solving} status={status} onStatus={setStatus} />

      <main className="main">
        <div className="nest-wrap">
          <div id="nests" className="nests">
            {seeds.map((seed) => {
              // runRegistry.list() 不订阅，但 seeds 变化触发的重渲染会重新读；renderTick 也驱动 NestLabel 重渲染。
              const rec = runRegistry.list().find((r) => r.seed === seed);
              return rec ? <NestCard key={seed} run={rec} /> : null;
            })}
          </div>
        </div>

        <div className="bottom">
          <div className="curve-wrap">
            <svg id="curve" xmlns="http://www.w3.org/2000/svg" />
          </div>
          <div className="playback">
            <div className="field-label">回放</div>
            <input id="seek" type="range" min={0} max={0} value={0} disabled />
            <div id="seek-readout">—</div>
          </div>
        </div>
      </main>
    </div>
  );
}
