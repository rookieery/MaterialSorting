// NestingPage —— 排料工作台页（US-001 把原 App.tsx 排料逻辑外提）。
//
// 职责：持有 phase / status / seeds 状态 + doneCountRef/totalSeedsRef，挂载
//   ControlPanel + NestsGrid + ConvergenceCurve + PlaybackBar，跑 useRafThrottle 节流闸。
// 与原 App.tsx（US-005 多 seed + US-006 seek/tooltip + US-007 导出）逻辑字节级一致，
//   仅容器由 `<div className="app">` 改为 `<div className="page nesting-page">`，
//   由父 App 据 uiStore.activeTab 切 display:none（AC#4 不卸载、求解/WS/seek 全保留）。
//
// US-027：solving:boolean → phase:SolvePhase 五态状态机（idle/running/stopped/done/error）。
//   onDone 按 rec.stopped/rec.error 区分 phase；handleStop 调 useSolveRun.stop()。
// US-028：ControlPanel 收 phase（替代 solving）+ onStop 接线 SolveControls 按钮组；
//   所有非 running 态的「开始求解」都走 handleStart（读当前 form —— 曾有 lastStartCfgRef
//   快照重放路径导致改参数不生效，已删除，见 SolveControls 注释）。
//
// US-006（策略 se/race）：applyStrategyResult(result) 把策略 run 终局最优一键应用到主画布 ——
//   runRegistry.clear() 清场后合成单条 RunRecord（manifest = result 端点 build_pid_meta 快照
//   口径，与 /ws/solve manifest 同形；frames = [best 帧]，FrameMsg 字段同形），NestSVG /
//   ConvergenceCurve / PlaybackBar / ExportButtons 零改动兼容。应用是显式按钮（弹窗结果态），
//   不自动应用 —— 会清掉主画布现有对比 run；result 常驻 strategyStore，关弹窗再开仍可应用。
//
// US-012（腰头成带）：handleStart 透传 cfg.band → useSolveRun.start → WS StartPayload.band；
//   onStage 回调（band 带内聚排统计，manifest 前唯一一次）→ 状态行「腰头成带中：带内聚排…」
//   秒级提示（**不进 phase 五态状态机**，run 不 finish；后续 manifest/frames 正常流转）。
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
import type { StrategyResult } from '../types/strategy';
import type { SolvePhase } from '../types/solvePhase';
import type { FrameMsg, ManifestMsg } from '../types/ws';

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

  const { start, stop } = useSolveRun({
    // US-012 band stage：带内聚排完成统计（manifest 前唯一一次）→ 状态行秒级提示。
    // **不进 phase 五态状态机**（run 不 finish；后续 manifest/frames/final 正常流转，
    // 全部 done 后 onDone 统一切 phase）。旧后端不发 stage → 回调不触发，安全。
    onStage: () => {
      setStatus('腰头成带中：带内聚排…');
    },
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
        // US-012：腰头成带配置透传（N 个 seed 共用同一份 band；后端各 run 独立成带，
        // band seed 由 zlib.crc32(f'{seed}|{label}') 派生保证确定性）。
        band: cfg.band,
      });
    }
  }

  /** US-027 停止求解：对所有 open WS 发 {action:'stop'}，后端 terminate 后回 stopped → onDone 切 phase。 */
  function handleStop() {
    stop();
    // 不立即 setPhase：等 server 回 {type:'stopped'} → onmessage case 'stopped' → finish → onDone 统一切。
  }

  /**
   * US-006 策略 run 结果应用到主画布（弹窗结果态「应用到主画布」显式按钮触发，不自动应用）。
   *
   * 应用语义 = 显式清场 + 合成单条 RunRecord：
   *   - runRegistry.clear()（关旧 WS —— 主画布现有对比 run 被清掉，破坏性操作由用户点击确认）
   *     + 计数 ref 重置（totalSeeds=1，防残留 onDone 闭包误判）；
   *   - manifest = result.manifest（result 端点 build_pid_meta 快照口径 —— erode 后几何与
   *     placed_items 对齐、demand 已含，NestSVG 副本池按 demand 建 N 份承接多副本 placement）；
   *   - frames = [合成帧]、lastFrame = 同帧（FrameMsg 形状：type:'frame'/index=best.frame_index/
   *     elapsed/phase:'final'/density 双口径/width_mm/placed_items）—— 与 WS 帧同形，
   *     NestSVG / ConvergenceCurve / PlaybackBar / ExportButtons/useExport/bestRun() 零改动兼容；
   *   - 页面状态：setSeeds([best.seed]) + setPhase('done') + setSeekTime(-1)（回 live）+
   *     setStatus('策略 run 已应用：seed N · X.XX%')。
   *
   * result 常驻 strategyStore（关弹窗再开仍可应用）；母版变更场景导出 pid 失配走既有 400 兜底。
   */
  function applyStrategyResult(result: StrategyResult) {
    // 防御：主画布 running 禁应用（入口按钮本就互斥 disabled，此处兜底弹窗滞留的极端时序）。
    if (phase === 'running') return;
    const best = result.best;
    const seed = best.seed ?? 0;
    const density = best.density ?? 0;
    const densitySparrow = best.density_sparrow ?? 0;
    const widthMm = best.width_mm ?? 0;

    // 1) 清场（与 handleStart 同口径）：关旧 WS + 清 registry + 计数 ref 重置。
    runRegistry.clear();
    doneCountRef.current = 0;
    totalSeedsRef.current = 1;

    // 2) 合成 manifest（result 端点 StrategyManifest → WS ManifestMsg 同形，补 type 判别键）。
    const manifest: ManifestMsg = {
      type: 'manifest',
      gate_mm: result.manifest.gate_mm,
      gate_nest_mm: result.manifest.gate_nest_mm,
      total_area_mm2: result.manifest.total_area_mm2,
      n_eroded: result.manifest.n_eroded,
      pieces: result.manifest.pieces,
    };
    // 3) 合成终局帧（FrameMsg 同形；phase='final' 与求解收尾帧口径一致）。
    const frame: FrameMsg = {
      type: 'frame',
      index: best.frame_index ?? 0,
      elapsed: best.elapsed ?? 0,
      phase: 'final',
      density,
      density_sparrow: densitySparrow,
      width_mm: widthMm,
      placed_items: best.placed_items ?? [],
    };

    // 4) 置换单条 RunRecord（导出链路 bestRun() 直接选中；ws=null 无 WS 可关）。
    const rec = runRegistry.create(seed);
    rec.manifest = manifest;
    rec.frames.push(frame);
    rec.lastFrame = frame;
    rec.finalDensity = density;
    rec.finalDensitySparrow = densitySparrow;
    rec.viewBoxMaxW = widthMm;
    rec.done = true;
    rec.error = null;
    rec.stopped = false;

    // 5) 页面状态：seeds 挂 NestCard → done（导出解禁）+ seek 回 live + 状态行汇报。
    clearHovered();
    hideTooltip();
    useAppStore.getState().setSeekTime(-1);
    setSeeds([seed]);
    setPhase('done');
    setStatus(`策略 run 已应用：seed ${seed} · ${(density * 100).toFixed(2)}%`);
  }

  return (
    <>
      <ControlPanel
        onStart={handleStart}
        onStop={handleStop}
        phase={phase}
        status={status}
        onStatus={setStatus}
        onApplyStrategy={applyStrategyResult}
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
