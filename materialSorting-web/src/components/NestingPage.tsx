// NestingPage —— 排料工作台页（US-001 把原 App.tsx 排料逻辑外提）。
//
// 职责：持有 phase / status / seeds 状态 + doneCountRef/totalSeedsRef，挂载
//   ControlPanel + NestsGrid，跑 useRafThrottle 节流闸。
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
//   核心已抽成共享 applySyntheticRun（store/synthRunStore，状态文件 US-004）：
//   runRegistry.clear() 清场后合成单条 RunRecord（manifest = result 端点 build_pid_meta 快照
//   口径，与 /ws/solve manifest 同形；frames = [best 帧]，FrameMsg 字段同形），NestSVG /
//   ExportButtons 零改动兼容。应用是显式按钮（弹窗结果态），
//   不自动应用 —— 会清掉主画布现有对比 run；result 常驻 strategyStore，关弹窗再开仍可应用。
//   状态文件 US-004：应用时经 originOfStrategyResult 记 RunRecord.origin（provenance 取数
//   中转 —— mode 定族/kind、本族 lastStart 补 config），主画布 run-provenance 来源小字常驻
//   回显；同一 applySyntheticRun 也被 lib/stateFile.applyRestorePayload（恢复编排）消费。
//
// US-012（腰头成带）：handleStart 透传 cfg.band → useSolveRun.start → WS StartPayload.band；
//   onStage 回调（band 带内聚排统计，manifest 前唯一一次）→ 状态行「腰头成带中：带内聚排…」
//   秒级提示（**不进 phase 五态状态机**，run 不 finish；后续 manifest/frames 正常流转）。
// US-004（起始端成套前后幅）：handleStart 透传 cfg.prefix（与 band 可同开）；onStage 分支
//   stage='prefix' → 状态行「起始端成套构造中（尺码 {size}）…」（size 回显后端近满幅
//   几何搜索选中的资格码，不进 phase 五态状态机；2026-09-02 异码补片双形态 ——
//   extra 在案 →「尺码 {size}＋{extra_label}@{extra_size}」）。
//
// Tooltip 仍由父 App 渲染（全局单例，不能多挂）；本页只渲染业务区，不挂 Tooltip。

import { useEffect, useRef, useState } from 'react';
import { ControlPanel, type ControlPanelStartPayload } from './ControlPanel/ControlPanel';
import { NestsGrid } from './nests/NestsGrid';
import { clearHovered, hideTooltip } from './Tooltip';
import { useRafThrottle } from '../hooks/useRafThrottle';
import { useSolveRun } from '../hooks/useSolveRun';
import { useEditStore } from '../store/editStore';
import { runRegistry } from '../store/runRegistry';
import {
  applySyntheticRun,
  provenanceText,
  useSynthRunStore,
} from '../store/synthRunStore';
import { useExtremeStore, useStrategyStore } from '../store/strategyStore';
import type { RunOrigin } from '../types/stateFile';
import type { StrategyResult } from '../types/strategy';
import type { SolvePhase } from '../types/solvePhase';
import type { FrameMsg, ManifestMsg } from '../types/ws';

/**
 * StrategyResult → RunOrigin（provenance 写回，US-004）：
 * - mode 定族定 kind（'extreme' → extreme 族；'se'/'race' → strategy 族）；
 * - config 从**本族** strategyStore.lastStart 补（策略族 minutes / 极限族
 *   time_total_s —— start 载荷快照；页面刷新后 store 重置 lastStart=null →
 *   origin 无 config 段，来源小字不渲染括号段 = 可接受的降级）；
 * - mode 缺席（null，旧后端）→ undefined（= 'solve' 口径，保存端不写 provenance 键）。
 */
function originOfStrategyResult(result: StrategyResult): RunOrigin | undefined {
  if (result.mode === 'extreme') {
    const t = useExtremeStore.getState().lastStart?.time_total_s;
    return {
      kind: 'extreme',
      ...(typeof t === 'number' ? { config: { time_total_s: t } } : {}),
    };
  }
  if (result.mode === 'se' || result.mode === 'race') {
    const m = useStrategyStore.getState().lastStart?.minutes;
    return {
      kind: result.mode === 'se' ? 'strategy_se' : 'strategy_race',
      ...(typeof m === 'number' ? { config: { minutes: m } } : {}),
    };
  }
  return undefined;
}

export function NestingPage(): React.JSX.Element {
  /** 已 start 的 seed 列表（base+i, i=0..N-1）。仅用于触发首次挂载 NestsGrid 内 NestCard。 */
  const [seeds, setSeeds] = useState<number[]>([]);
  /** US-027 求解状态机（idle/running/stopped/done/error）—— 驱动 useRafThrottle + 禁用参数编辑。 */
  const [phase, setPhase] = useState<SolvePhase>('idle');
  /** 状态行文案（ControlPanel / useSolveRun 回调都能写）。 */
  const [status, setStatus] = useState('就绪');
  /**
   * 结果来源小字（US-004 run-provenance）：合成 run（策略/极限应用 / 状态文件恢复）
   * 信号携带的 origin + seed；WS 普通求解恒 null（handleStart 清场）。纯展示级 ——
   * 渲染为 ControlPanel StatusLine 下方一行 dim 小字（provenanceText 组装文案）。
   */
  const [provenance, setProvenance] = useState<{ origin: RunOrigin; seed: number } | null>(null);

  /** 已 done 的 run 计数（ref 避免闭包陈旧；与 totalSeedsRef 配合判定 all-done）。 */
  const doneCountRef = useRef(0);
  /** 本次 start 期望的 run 总数（同 seeds.length，但在 cb 闭包里读 ref 才拿得到当前值）。 */
  const totalSeedsRef = useRef(0);

  const { start, stop } = useSolveRun({
    // US-012 band stage：带内聚排完成统计（manifest 前唯一一次）→ 状态行秒级提示。
    // **不进 phase 五态状态机**（run 不 finish；后续 manifest/frames/final 正常流转，
    // 全部 done 后 onDone 统一切 phase）。旧后端不发 stage → 回调不触发，安全。
    // US-004 prefix stage：构造完成统计 →「起始端成套构造中（尺码 {size}）…」
    // （size 由 stage 消息回显后端选中的资格码 —— 近满幅几何搜索确定性选定，
    // 前端无法预知，决策②）。2026-09-02 异码补片双形态：extra_label/extra_size
    // 在案 →「尺码 {size}＋{extra_label}@{extra_size}」（＋号全角与文案风格一致）；
    // 兜底 / 无补片 / 旧后端（键缺席）→ 现行形态（null 与 undefined 同判）。
    onStage: (m) => {
      if (m.stage === 'prefix') {
        if (m.extra_label != null && m.extra_size != null) {
          setStatus(
            `起始端成套构造中（尺码 ${m.size ?? '—'}＋${m.extra_label}@${m.extra_size}）…`,
          );
        } else {
          setStatus(`起始端成套构造中（尺码 ${m.size ?? '—'}）…`);
        }
      } else {
        setStatus('腰头成带中：带内聚排…');
      }
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

      // US-006 AC#1（2026-09-12 曲线/回放功能移除）：setSeekTime 到末帧的逻辑随回放 UI
      // 一并删除 —— live 画布本就显示 lastFrame（= 末帧），行为无差异。

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
  // NestSVG / NestLabel 订阅后 imperative 重绘。
  // 注：求解结束后仍持续 bump（seeds 不清空），让 NestLabel 显示最终态。
  useRafThrottle(seeds.length > 0);

  // 合成 run 信号消费（US-004）：applySyntheticRun（策略/极限应用 / 状态文件恢复，
  // registry 已在信号发出前落笔）→ 本 effect 把页面本地状态对齐到合成 done 态 ——
  // seeds 挂 NestCard、phase 切 done（导出解禁）、状态行汇报、计数 ref 重置（防残留
  // onDone 闭包误判）、清 tooltip/hover 残留（旧 applyStrategyResult 的收尾动作随核心
  // 一并下沉至此，两条路径同口径）、provenance 记录（origin 缺席 = WS 口径 → 清空）。
  // lastTokenRef 只消费**挂载后新到**的信号：重挂载（测试隔离 / 未来路由恢复）不重放
  // 历史信号（registry 可能已被后续 start 清场，旧 seed 无对应 record）。
  // 幂等：React 18 StrictMode 双跑 effect 时 ref 已对齐 → 第二跳直接跳过。
  const synthToken = useSynthRunStore((s) => s.token);
  const lastSynthTokenRef = useRef(synthToken);
  useEffect(() => {
    if (synthToken === lastSynthTokenRef.current) return; // 无新信号（含挂载初跑）
    lastSynthTokenRef.current = synthToken;
    const { seed, note, origin } = useSynthRunStore.getState();
    doneCountRef.current = 0;
    totalSeedsRef.current = 1;
    clearHovered();
    hideTooltip();
    setSeeds([seed]);
    setPhase('done');
    if (note !== '') setStatus(note);
    setProvenance(origin !== undefined ? { origin, seed } : null);
  }, [synthToken]);

  function handleStart(cfg: ControlPanelStartPayload) {
    if (phase === 'running') return;
    // 清旧 run（关 WS + 清数组）—— 与旧 vanilla 实现 startSolve 内 runs=[] 等价
    runRegistry.clear();
    // 编辑排料 US-004：重解清场 → 编辑态失效（save/reset 的 registry 校验已拒陈旧
    // run，此处同步清 working/baseline —— 编辑弹窗开着时全屏 overlay 阻断主界面，
    // registry 无人写、下标安全；挂点防御「下次求解前旧编辑会话残留」）。
    useEditStore.getState().invalidate();
    doneCountRef.current = 0;
    totalSeedsRef.current = cfg.seed_count;
    // US-004：新一次 WS 求解 = 全新结果（origin 不设口径），来源小字随清场退场。
    setProvenance(null);

    // 清 tooltip / hover 残留（与旧 vanilla 实现 startSolve 内 `hoveredEl=null;
    // tooltipEl.style.display='none'` 等价；seekbar 重置随回放功能一并移除）。
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
        // US-004：起始端成套前后幅透传（与 band 可同开 —— 双开时带位只记录不置换；
        // 资格码后端近满幅几何搜索确定性选定（全 run 同选，2026-09-02 起取代
        // seeded 随机），可行时顶部补 1 片异码近满幅，seed 仅兜底路径消费）。
        prefix: cfg.prefix,
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
   * 应用语义 = 显式清场 + 合成单条 RunRecord —— 核心（清场/registry 落笔/seek 回 live/
   * placed 深拷贝/信号）已抽成共享 applySyntheticRun（store/synthRunStore，US-004），
   * 本函数只组装 result → manifest/帧/origin/note 后委托；页面状态对齐（setSeeds/
   * setPhase('done')/setStatus/计数 ref/provenance）由 NestingPage 的信号 effect 统一
   * 消费（恢复路径同款）。manifest = result.manifest（build_pid_meta 快照口径 —— erode
   * 后几何与 placed_items 对齐、demand 已含，NestSVG 副本池按 demand 建 N 份承接多副本
   * placement）；frames = [合成帧]（FrameMsg 形状）—— 与 WS 帧同形，NestSVG /
   * ExportButtons/useExport/bestRun() 零改动兼容。
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

    // 1) 合成 manifest（result 端点 StrategyManifest → WS ManifestMsg 同形，补 type 判别键）。
    const manifest: ManifestMsg = {
      type: 'manifest',
      gate_mm: result.manifest.gate_mm,
      total_area_mm2: result.manifest.total_area_mm2,
      n_eroded: result.manifest.n_eroded,
      pieces: result.manifest.pieces,
    };
    // 2) 合成终局帧（FrameMsg 同形；phase='final' 与求解收尾帧口径一致；placed 深拷贝
    //    在 applySyntheticRun 内统一 —— 源 result.best.placed_items 不被后续编辑写回穿透）。
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

    // 3) 委托共享落笔 + 信号（US-004 origin 记入；状态行区分来源 —— US-003 极限运行
    //    result.mode='extreme' 同一 applyStrategyResult 复用，summary.mode 仍是 'race'
    //    不作判据）。
    applySyntheticRun(
      manifest,
      frame,
      seed,
      originOfStrategyResult(result),
      `${result.mode === 'extreme' ? '极限' : '策略'} run 已应用：seed ${seed} · ${(
        density * 100
      ).toFixed(2)}%`,
    );
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
        runProvenance={
          provenance !== null ? provenanceText(provenance.origin, provenance.seed) : undefined
        }
      />

      <main className="main">
        <div className="nest-wrap" data-tour="nest-wrap">
          <NestsGrid seeds={seeds} />
        </div>
      </main>
    </>
  );
}
