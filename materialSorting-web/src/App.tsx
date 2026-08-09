// App —— 顶层三段（panel + main + bottom）。
//
// US-005：ControlPanel 接管参数输入（含 multi_seed 开关 + seed_count）；App 负责：
//   1. 持有 solving / status / seeds（base+i, i=0..N-1）。
//   2. useRafThrottle(seeds.length > 0) 跑节流闸（结束求解后仍持续 bump，NestSVG/ConvergenceCurve 重绘）。
//   3. ControlPanel.onStart(cfg) → runRegistry.clear + setSeeds([base..base+N-1]) + 启动 N 个 useSolveRun.start。
//   4. 多 run 收尾：doneCountRef/totalSeedsRef 追踪完成数量；全部完成时 setStatus 汇总。
//
// US-006 增量：
//   5. 全部完成时 setSeekTime(ceil(maxElapsed)) —— AC#1 默认到末尾；NestSVG / SeekReadout 切到末帧。
//   6. handleStart 内 setSeekTime(-1) —— 重置回 live；同时 clearHovered + hideTooltip 防残留。
//   7. 顶层挂一个 <Tooltip/>（portal 到 body，整 App 生命周期单例）。
//
// 数据流（与旧 vanilla 实现 startSolve / connectRun / checkAllDone 等价）：
//   ControlPanel collectParams → onStart(cfg) → useSolveRun.start × N → 各 WS
//   → onmessage 推 manifest/frame/final → useRafThrottle bump renderTick
//   → NestSVG / ConvergenceCurve / NestLabel 订阅后 imperative 重绘。

import { useRef, useState } from 'react';
import { ConvergenceCurve } from './components/curve/ConvergenceCurve';
import { ControlPanel, type ControlPanelStartPayload } from './components/ControlPanel/ControlPanel';
import { NestsGrid } from './components/nests/NestsGrid';
import { PlaybackBar } from './components/playback/PlaybackBar';
import { Tooltip, clearHovered, hideTooltip } from './components/Tooltip';
import { useRafThrottle } from './hooks/useRafThrottle';
import { useSolveRun } from './hooks/useSolveRun';
import { maxElapsed } from './lib/seek';
import { useAppStore } from './store/appStore';
import { runRegistry } from './store/runRegistry';

export function App() {
  /** 已 start 的 seed 列表（base+i, i=0..N-1）。仅用于触发首次挂载 NestsGrid 内 NestCard。 */
  const [seeds, setSeeds] = useState<number[]>([]);
  /** 求解中 flag —— 驱动 useRafThrottle + 禁用 StartButton。 */
  const [solving, setSolving] = useState(false);
  /** 状态行文案（ControlPanel / useSolveRun 回调都能写）。 */
  const [status, setStatus] = useState('就绪');

  /** 已 done 的 run 计数（ref 避免闭包陈旧；与 totalSeedsRef 配合判定 all-done）。 */
  const doneCountRef = useRef(0);
  /** 本次 start 期望的 run 总数（同 seeds.length，但在 cb 闭包里读 ref 才拿得到当前值）。 */
  const totalSeedsRef = useRef(0);

  const { start } = useSolveRun({
    onDone: () => {
      doneCountRef.current += 1;
      if (doneCountRef.current < totalSeedsRef.current) return;
      // 全部完成 → 汇总状态行
      setSolving(false);
      const runs = runRegistry.list();
      if (runs.length === 0) return;

      // US-006 AC#1：全部完成时 seekbar 启用，value 默认到末尾 = ceil(maxElapsed)。
      // setSeekTime(me) 后 NestSVG 切到 frameAtTime(run, me)（= 末帧，与 lastFrame 等价），
      // Seekbar 受控 value 跟着到末尾，SeekReadout 显示末帧密度。
      const me = Math.ceil(maxElapsed(runs));
      useAppStore.getState().setSeekTime(me);

      const summary = runs
        .map((r) => `s${r.seed} ${(r.finalDensity * 100).toFixed(2)}%`)
        .join(' / ');
      if (runs.length === 1) {
        const rec = runs[0];
        if (rec.error) {
          setStatus(`seed ${rec.seed} 错误：${rec.error}`);
        } else if (rec.finalDensity > 0) {
          setStatus(`完成：seed ${rec.seed} · ${(rec.finalDensity * 100).toFixed(2)}%`);
        } else {
          setStatus(`seed ${rec.seed} 已结束`);
        }
        return;
      }
      // 多 seed：汇总 + best
      const best = runs.reduce((a, r) => (r.finalDensity > a.finalDensity ? r : a), runs[0]);
      setStatus(`完成 ${runs.length} seed：${summary} | best = s${best.seed} ${(best.finalDensity * 100).toFixed(2)}%`);
    },
  });

  // 全局 ~10fps 节流闸 —— seeds.length > 0 期间持续 bump renderTick，
  // NestSVG / NestLabel / ConvergenceCurve 订阅后 imperative 重绘。
  // 注：求解结束后仍持续 bump（seeds 不清空），让曲线 / NestLabel 显示最终态。
  useRafThrottle(seeds.length > 0);

  function handleStart(cfg: ControlPanelStartPayload) {
    if (solving) return;
    // 清旧 run（关 WS + 清数组）—— 与旧 vanilla 实现 startSolve 内 runs=[] 等价
    runRegistry.clear();
    doneCountRef.current = 0;
    totalSeedsRef.current = cfg.seed_count;

    // US-006：重置回 live（NestSVG 显示 lastFrame）；同时清 tooltip / hover 残留。
    // 与旧 vanilla 实现 startSolve 内 `$('seek').disabled=true; max=0; value=0; hoveredEl=null; tooltipEl.style.display='none'` 等价。
    useAppStore.getState().setSeekTime(-1);
    clearHovered();
    hideTooltip();

    // seed 列表 = base + i (i=0..N-1)（与旧 vanilla 实现 `for i: makeRun(baseSeed+i)` 一致）
    const newSeeds: number[] = [];
    for (let i = 0; i < cfg.seed_count; i++) newSeeds.push(cfg.seed + i);
    setSeeds(newSeeds);
    setSolving(true);
    setStatus(cfg.seed_count > 1 ? `启动 ${cfg.seed_count} 个 seed 对比…` : '连接中…');

    // 顺序 start N 个 run（每个独立 WS；useSolveRun.start 内 runRegistry.create + new WebSocket）。
    for (let i = 0; i < cfg.seed_count; i++) {
      start({
        sizes: cfg.sizes,
        time: cfg.time,
        seed: cfg.seed + i,
        params: cfg.params,
        per_type: cfg.per_type,
      });
    }
  }

  return (
    <div className="app">
      <ControlPanel onStart={handleStart} solving={solving} status={status} onStatus={setStatus} />

      <main className="main">
        <div className="nest-wrap">
          <NestsGrid seeds={seeds} />
        </div>

        <div className="bottom">
          <div className="curve-wrap">
            <ConvergenceCurve />
          </div>
          <PlaybackBar />
        </div>
      </main>

      {/* US-006 AC#5：Tooltip 用 React Portal 到 body，fixed 定位；app 生命周期内单例。 */}
      <Tooltip />
    </div>
  );
}
