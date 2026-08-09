// App —— US-003 单 seed 可视化拼装（panel + main + bottom 三段）。
//
// 现阶段（US-003）控制面板仅"开始求解"按钮 + 状态行；硬编码 sizes=[30,32] / time=30 / seed=0
// 满足 AC#7（实时帧刷新 + final 后停止）。US-004 起 ControlPanel 会接管参数输入。
//
// 数据流：
//   start(cfg) → useSolveRun → runRegistry.create + WS → onmessage 推 manifest/frame/final
//   useRafThrottle(true) → 100ms bump renderTick → NestSVG effect 走 setAttribute imperative 渲染。
//
// 这里 seeds 状态只为触发首次挂载 NestCard；之后 NestCard 内部完全由 renderTick 驱动。

import { useState } from 'react';
import { NestCard } from './components/nests/NestCard';
import { useRafThrottle } from './hooks/useRafThrottle';
import { useSolveRun } from './hooks/useSolveRun';
import { runRegistry } from './store/runRegistry';
import type { SolveParams } from './types/v03';

// US-003 验证参数（AC#7）：码号 30/32，30s 单 seed=0，v0.3 baseline（无 erode / 无旋转公差）。
const HARDCODED_SIZES = [30, 32];
const HARDCODED_TIME = 30;
const HARDCODED_SEED = 0;
const HARDCODED_PARAMS: SolveParams = { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 };

export function App() {
  /** 已 start 的 seed 列表（仅用于触发首次挂载 NestCard）。 */
  const [seeds, setSeeds] = useState<number[]>([]);
  /** 求解中 flag —— 驱动 useRafThrottle + 禁用按钮。 */
  const [solving, setSolving] = useState(false);
  /** 状态行文案。 */
  const [status, setStatus] = useState('就绪');

  const { start } = useSolveRun({
    onDone: (rec) => {
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

  function handleStart() {
    if (solving) return;
    // 清旧 run（关 WS + 清数组）—— 与旧 app.js startSolve 等价
    runRegistry.clear();
    setSeeds([HARDCODED_SEED]);
    setSolving(true);
    setStatus('连接中…');
    start({
      sizes: HARDCODED_SIZES,
      time: HARDCODED_TIME,
      seed: HARDCODED_SEED,
      params: HARDCODED_PARAMS,
    });
  }

  return (
    <div className="app">
      <aside className="panel">
        <h2>求解控制</h2>
        <div className="hint">
          US-003 单 seed 可视化：
          <br />
          硬编码 sizes=[30,32] / time=30s / seed=0 / baseline 参数。
        </div>
        <button id="start" type="button" onClick={handleStart} disabled={solving}>
          {solving ? '求解中…' : '开始求解'}
        </button>
        <div className="status" id="status">
          {status}
        </div>
      </aside>

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
