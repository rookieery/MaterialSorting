// NestingPage —— 排料工作台页（US-001 把原 App.tsx 排料逻辑外提）。
//
// 职责：持有 phase / status / seeds 状态 + doneCountRef/totalSeedsRef，挂载
//   ControlPanel + NestsGrid + ConvergenceCurve + PlaybackBar，跑 useRafThrottle 节流闸。
// 与原 App.tsx（US-005 多 seed + US-006 seek/tooltip + US-007 导出）逻辑字节级一致，
//   仅容器由 `<div className="app">` 改为 `<div className="page nesting-page">`，
//   由父 App 据 uiStore.activeTab 切 display:none（AC#4 不卸载、求解/WS/seek 全保留）。
//
// US-027：solving:boolean → phase:SolvePhase 五态状态机（idle/running/stopped/done/error）。
//   onDone 按 rec.stopped/rec.error 区分 phase；handleStop 调 useSolveRun.stop()；
//   handleRestart = clear + 用上次参数（lastStartCfgRef）handleStart。
// US-028：ControlPanel 收 phase（替代 solving）+ onStop/onRestart 接线 SolveControls 按钮组。
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
import type { SolvePhase } from '../types/solvePhase';

export function NestingPage(): React.JSX.Element {
  /** 已 start 的 seed 列表（base+i, i=0..N-1）。仅用于触发首次挂载 NestsGrid 内 NestCard。 */
  const [seeds, setSeeds] = useState<number[]>([]);
  /** US-027 求解状态机（idle/running/stopped/done/error）—— 驱动 useRafThrottle + 禁用参数编辑。 */
  const [phase, setPhase] = useState<SolvePhase>('idle');
  /** 状态行文案（ControlPanel / useSolveRun 回调都能写）。 */
  const [status, setStatus] = useState('就绪');

  /** 已 done 的 run 计数（ref 避免闭包陈旧；与 totalSeedsRef 配合判定 all-done）。 */
  const doneCountRef = useRef(0);
  /** 本次 start 期望的 run 总数（同 seeds.length，但在 cb 闭包里读 ref 才拿得到当前值）。 */
  const totalSeedsRef = useRef(0);
  /** US-027 上次 start 参数 —— handleRestart 复用（用户改参数后走 handleStart 用新值）。 */
  const lastStartCfgRef = useRef<ControlPanelStartPayload | null>(null);

  const { start, stop } = useSolveRun({
    onDone: () => {
      doneCountRef.current += 1;
      if (doneCountRef.current < totalSeedsRef.current) return;
      // 全部 run 的 onDone 到齐 → 统一切 phase + 汇总状态行
      const runs = runRegistry.list();
      if (runs.length === 0) {
        setPhase('done');
        return;
      }

      // US-027 phase 区分（优先级：全 stopped→stopped；有 error→error；否则 done）。
      // per-run stopped 与 error 互斥（useSolveRun case 分支不会同时置），故全 stopped 时无 error。
      const hasError = runs.some((r) => r.error !== null);
      const allStopped = runs.every((r) => r.stopped);
      if (allStopped) {
        setPhase('stopped');
      } else if (hasError) {
        setPhase('error');
      } else {
        setPhase('done');
      }

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
        } else if (rec.stopped) {
          setStatus(`已停止：seed ${rec.seed}（保留中间方案，可导出）`);
        } else if (rec.finalDensity > 0) {
          setStatus(`完成：seed ${rec.seed} · ${(rec.finalDensity * 100).toFixed(2)}%`);
        } else {
          setStatus(`seed ${rec.seed} 已结束`);
        }
        return;
      }
      // 多 seed：汇总 + best
      const best = runs.reduce((a, r) => (r.finalDensity > a.finalDensity ? r : a), runs[0]);
      if (allStopped) {
        setStatus(`已停止 ${runs.length} seed：${summary} | best = s${best.seed} ${(best.finalDensity * 100).toFixed(2)}%`);
      } else if (hasError) {
        setStatus(`完成（含错误）${runs.length} seed：${summary} | best = s${best.seed} ${(best.finalDensity * 100).toFixed(2)}%`);
      } else {
        setStatus(`完成 ${runs.length} seed：${summary} | best = s${best.seed} ${(best.finalDensity * 100).toFixed(2)}%`);
      }
    },
  });

  // 全局 ~10fps 节流闸 —— seeds.length > 0 期间持续 bump renderTick，
  // NestSVG / NestLabel / ConvergenceCurve 订阅后 imperative 重绘。
  // 注：求解结束后仍持续 bump（seeds 不清空），让曲线 / NestLabel 显示最终态。
  useRafThrottle(seeds.length > 0);

  function handleStart(cfg: ControlPanelStartPayload) {
    if (phase === 'running') return;
    // US-027：保存本次 start 参数，供 handleRestart 复用。
    lastStartCfgRef.current = cfg;
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
    setPhase('running');
    setStatus(cfg.seed_count > 1 ? `启动 ${cfg.seed_count} 个 seed 对比…` : '连接中…');

    // 顺序 start N 个 run（每个独立 WS；useSolveRun.start 内 runRegistry.create + new WebSocket）。
    for (let i = 0; i < cfg.seed_count; i++) {
      start({
        sizes: cfg.sizes,
        time: cfg.time,
        seed: cfg.seed + i,
        gate_mm: cfg.gate_mm,
        params: cfg.params,
        per_type: cfg.per_type,
        // US-022：per-size demand 透传（N 个 seed 共用同一份 quantities）。
        quantities: cfg.quantities,
      });
    }
  }

  /** US-027 停止求解：对所有 open WS 发 {action:'stop'}，后端 terminate 后回 stopped → onDone 切 phase。 */
  function handleStop() {
    stop();
    // 不立即 setPhase：等 server 回 {type:'stopped'} → onmessage case 'stopped' → finish → onDone 统一切。
  }

  /**
   * US-027 重新开始：用上次 start 参数（lastStartCfgRef）走 handleStart（内含 clear + reset + start）。
   * 用户在 stopped/error/done 态若改了参数 → ControlPanel 走 onStart → handleStart（新参数覆盖 ref）。
   */
  function handleRestart() {
    const last = lastStartCfgRef.current;
    if (!last) return;
    handleStart(last);
  }

  return (
    <>
      <ControlPanel
        onStart={handleStart}
        onStop={handleStop}
        onRestart={handleRestart}
        phase={phase}
        status={status}
        onStatus={setStatus}
      />

      <main className="main">
        <div className="nest-wrap" data-tour="nest-wrap">
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
