// NestingPage —— 排料工作台页（US-001 把原 App.tsx 排料逻辑外提）。
//
// 职责：持有 solving / status / seeds 状态 + doneCountRef/totalSeedsRef，挂载
//   ControlPanel + NestsGrid + ConvergenceCurve + PlaybackBar，跑 useRafThrottle 节流闸。
// 与原 App.tsx（US-005 多 seed + US-006 seek/tooltip + US-007 导出）逻辑字节级一致，
//   仅容器由 `<div className="app">` 改为 `<div className="page nesting-page">`，
//   由父 App 据 uiStore.activeTab 切 display:none（AC#4 不卸载、求解/WS/seek 全保留）。
//
// Tooltip 仍由父 App 渲染（全局单例，不能多挂）；本页只渲染业务区，不挂 Tooltip。

import { useRef, useState } from 'react';
import { ConvergenceCurve } from './curve/ConvergenceCurve';
import { ControlPanel, type ControlPanelStartPayload } from './ControlPanel/ControlPanel';
import { NestsGrid } from './nests/NestsGrid';
import { PlaybackBar } from './playback/PlaybackBar';
import { clearHovered, hideTooltip } from './Tooltip';
import { useRafThrottle } from '../hooks/useRafThrottle';
import { useSolveRun } from '../hooks/useSolveRun';
import { maxElapsed } from '../lib/seek';
import { useAppStore } from '../store/appStore';
import { runRegistry } from '../store/runRegistry';

export function NestingPage(): React.JSX.Element {
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
    <>
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
    </>
  );
}
