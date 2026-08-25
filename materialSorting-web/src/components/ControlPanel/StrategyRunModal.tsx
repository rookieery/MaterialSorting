// StrategyRunModal —— 「高级运行」弹窗（US-005 三态进度 UI；范本 PerTypeOverridesModal）。
//
// 声明式受控 Portal：订阅 controlPanelStore.modal === 'strategy_run' 自显隐
// （null 不挂 DOM）；Portal 到 document.body（不被 .page 裁切）；role="dialog"。
// 关闭四通道（✕ / 遮罩 mousedown / ESC）**均不终止运行** —— 关闭只调
// closeModal（run 在后端子进程继续跑，入口按钮徽标 + 关弹窗 15s 轮询维持观测）；
// 终止唯一入口是进度态「终止运行」按钮（strategyStore.stop → 树杀 + 清 marker）。
// running 态常驻文案「关闭弹窗不会终止运行」明示这一点。
//
// 三态渲染（phase 订阅 strategyStore）：
//   配置态 idle     时长下拉（10/20/30/60min → --time 600/1200/1800/3600）+ 模式
//                  下拉（race 门杀默认 / SE 顺延）+ 模式说明行随切换 + 执行按钮
//                  （disabled = 主画布 solving || 未选码号 —— 前端互斥防 CPU 竞争
//                  扭曲门时刻判据）。不暴露 --se-screen 等 4 个策略参数（PRD 实测
//                  默认值即最优）。排料参数（码号/高级配置/数量矩阵）经
//                  buildStartContext 与 handleStart 同源（collectStartContext）。
//   进度态 starting/running   五件套（克制 —— 弹窗不渲染排料过程）：
//                  ① 标题行：模式 · 总预算 · 已跑 X 分 X 秒（墙钟）
//                  ② 当前全局最优利用率大数字 = max(incumbent.density, 当前 seed
//                     best_frame density)（原面积口径，版师唯一最关心的数）
//                  ③ 预算进度条 elapsed/total（墙钟口径标「≈」）
//                  ④ 阶段行：第 n/N 轮 · seed X · 求解中；race 门杀瞬间 chip 变
//                     ✕门杀（kill_decisions R5 事件逐条 flush）；SE 检测
//                     best_frame_s{seed}_ext（current.ext）即切「延长中 · 冠军 seed X」
//                  ⑤ seed chips（race = done✓密度/killed✕/running●/未启动灰，长队
//                     列逐轮淘汰；SE = k 筛 + 分隔 + 冠军延长条目，两段式结构）
//                     + 最近 1 条事件行 + 终止按钮
//   结果态 done/stopped/error/orphan
//                  done：完成 · 最优 X.XX%（seed N · 用布 X.XXm）+ 模式汇总（race：
//                  M 轮中 K 轮门杀 · 全程 X 分 X 秒 / SE：k 筛 + 冠军延长）+
//                  [应用到主画布]（US-006 已接线 —— NestingPage
//                  applyStrategyResult 经 ControlPanel 透传；未传回调时 disabled）。
//                  2026-08-22 起不展示服务器 run_dir 路径（浏览器端无法使用、泄露
//                  服务器目录结构；产物由后端在下一次 start 时自动清理）。
//                  stopped：已终止 · 保留终止前最优 X%（同样给应用按钮）。
//                  error：错误信息 + 重试（lastStart 在场 → 原载荷重启；否则回配置态）。
//                  orphan：检测到遗留运行（server 重启后 marker 残留）+ pid/存活 +
//                  清理按钮（stop 路由 orphan 分支：杀 pid + 清 marker）。
//                  母版漂移 warning（result 端点附带）在结果态展示（US-006 场景）。
//
// 结果常驻 strategyStore（关弹窗再开仍可应用 / 导出）；「再次运行」链接按钮
// reset() 回配置态开新 run（start 会清旧 result）。

import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import type { StartContext } from '../../lib/params';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { useStrategyStore } from '../../store/strategyStore';
import type {
  StrategyEvent,
  StrategyMinutes,
  StrategyMode,
  StrategyResult,
  StrategyStatus,
} from '../../types/strategy';

/** 时长四档（分钟 → --time 秒 = minutes × 60）。 */
const MINUTES_OPTIONS: { value: StrategyMinutes; label: string }[] = [
  { value: 10, label: '10 分钟' },
  { value: 20, label: '20 分钟' },
  { value: 30, label: '30 分钟' },
  { value: 60, label: '1 小时' },
];

const MODE_OPTIONS: { value: StrategyMode; label: string; desc: string }[] = [
  {
    value: 'race',
    label: 'race 门杀（默认）',
    desc: '每 3 分钟一轮，90s 门处严格破纪录才续跑，弱 seed 提前淘汰省出预算',
  },
  {
    value: 'se',
    label: 'SE 顺延',
    desc: '多轮短筛选后冠军 seed 加时长再战',
  },
];

// ------------------------------------------------------------- 纯格式化助手

/** 密度（0..1）→ 百分比文案（原面积口径，两位小数；null → '—'）。 */
export function fmtDensity(d: number | null | undefined): string {
  return d === null || d === undefined ? '—' : `${(d * 100).toFixed(2)}%`;
}

/** 秒 → 「X 分 X 秒」（<1 分省略分位）。 */
export function fmtElapsed(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return '—';
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m} 分 ${r} 秒` : `${r} 秒`;
}

/** 总预算秒 → 「20 分」/「1 小时」。 */
export function fmtBudget(sec: number | null | undefined): string {
  if (sec === null || sec === undefined || sec <= 0) return '—';
  if (sec >= 3600 && sec % 3600 === 0) return `${sec / 3600} 小时`;
  return `${Math.round(sec / 60)} 分`;
}

/** 用布长度 mm → m（两位小数）。 */
function fmtWidthM(mm: number | null | undefined): string {
  return mm === null || mm === undefined ? '—' : `${(mm / 1000).toFixed(2)}m`;
}

// ------------------------------------------------------------- seed chips 派生

export type SeedChipState = 'done' | 'killed' | 'running' | 'pending';

export interface SeedChip {
  /** 延长条目可为 null（冠军未定）→ 用 label 呈现。 */
  seed: number | null;
  label: string;
  state: SeedChipState;
}

/** 该 seed 是否已有 R5 门杀决策（would_kill 且尚未入 per_seed —— 「瞬间 ✕门杀」）。 */
function gateKilledSeeds(events: StrategyEvent[]): Set<number> {
  const out = new Set<number>();
  for (const e of events) {
    if (e.kind === 'gate' && e.would_kill === true && typeof e.seed === 'number') {
      out.add(e.seed);
    }
  }
  return out;
}

function chipForSeed(
  seed: number,
  perSeed: NonNullable<StrategyStatus['per_seed']>,
  current: StrategyStatus['current'] | null | undefined,
  gateKilled: Set<number>,
): SeedChip {
  const entry = perSeed.find((e) => e.seed === seed);
  if (entry) {
    return entry.killed
      ? { seed, label: `✕ ${fmtDensity(entry.best_density)}`, state: 'killed' }
      : { seed, label: `✓ ${fmtDensity(entry.best_density)}`, state: 'done' };
  }
  if (gateKilled.has(seed)) {
    return { seed, label: '✕门杀', state: 'killed' };
  }
  if (current && current.seed === seed) {
    return { seed, label: `● ${fmtDensity(current.density)}`, state: 'running' };
  }
  return { seed, label: '—（未启动）', state: 'pending' };
}

/** race chips：计划种子队列逐轮淘汰（done✓密度 / killed✕ / running● / 未启动灰）。 */
export function raceChips(status: StrategyStatus | null): SeedChip[] {
  if (!status) return [];
  const planned = status.plan?.planned_seeds ?? [];
  if (planned.length === 0) return [];
  const gateKilled = gateKilledSeeds(status.events ?? []);
  return planned.map((s) =>
    chipForSeed(s, status.per_seed ?? [], status.current, gateKilled),
  );
}

/**
 * SE chips：k 筛 + 分隔 + 冠军延长条目（两段式结构）。
 * 冠军 seed 来源：extension 事件 / current.ext；延长条目状态：进行中 ● / 完成 ✓ /
 * 未定灰。
 */
export function seChips(status: StrategyStatus | null): SeedChip[] {
  if (!status) return [];
  const planned = status.plan?.planned_seeds ?? [];
  if (planned.length === 0) return [];
  const gateKilled = gateKilledSeeds(status.events ?? []);
  const screens = planned.map((s) =>
    chipForSeed(s, status.per_seed ?? [], status.current, gateKilled),
  );
  // 冠军延长条目：per_seed 里 phase==='extension' 的入账（完成）优先，
  // 否则 extension 事件 / current.ext（进行中），都无 → 待定灰。
  const perSeed = status.per_seed ?? [];
  const extEntry = perSeed.find((e) => e.phase === 'extension');
  let champion: number | null = extEntry ? extEntry.seed : null;
  if (champion === null) {
    const extEvent = (status.events ?? []).find((e) => e.kind === 'extension');
    if (extEvent) champion = extEvent.seed;
  }
  const extRunning =
    status.current !== null &&
    status.current !== undefined &&
    status.current.ext &&
    status.current.seed === champion;
  let extChip: SeedChip;
  if (extEntry) {
    extChip = {
      seed: extEntry.seed,
      label: `延 ✓ ${fmtDensity(extEntry.best_density)}`,
      state: extEntry.killed ? 'killed' : 'done',
    };
  } else if (extRunning) {
    extChip = {
      seed: champion,
      label: `延 ● ${fmtDensity(status.current?.density)}`,
      state: 'running',
    };
  } else {
    extChip = { seed: champion, label: '延长 · 待定', state: 'pending' };
  }
  return [...screens, { seed: null, label: '→', state: 'pending' }, extChip];
}

/** 最近 1 条事件行文案。 */
export function fmtLastEvent(ev: StrategyEvent | undefined): string {
  if (!ev) return '暂无事件';
  if (ev.kind === 'gate') {
    if (ev.would_kill) {
      return `✕ seed ${ev.seed} 门杀（${fmtDensity(ev.d)} ≤ 门值 ${fmtDensity(ev.bar)}）`;
    }
    if (ev.bar === null || ev.bar === undefined) {
      return `seed ${ev.seed} 首轮豁免（${fmtDensity(ev.d)}）`;
    }
    return `seed ${ev.seed} 过门（${fmtDensity(ev.d)} > 门值 ${fmtDensity(ev.bar)}）`;
  }
  if (ev.kind === 'extension') return `冠军 seed ${ev.seed} 进入延长`;
  return `seed ${ev.seed} ${ev.killed ? '被淘汰' : '完成'} · ${fmtDensity(ev.best_density)}`;
}

// ------------------------------------------------------------- 组件

export interface StrategyRunModalProps {
  /** 主画布是否求解中（执行按钮互斥 —— 防 CPU 竞争扭曲 race 门时刻判据）。 */
  solving: boolean;
  /** handleStart 同源 start 上下文构造器（collectStartContext 共用，不复制逻辑）。 */
  buildStartContext: () => StartContext;
  /** US-006 应用到主画布回调（未传 → 应用按钮 disabled）。 */
  onApplyStrategy?: (result: StrategyResult) => void;
}

export function StrategyRunModal(props: StrategyRunModalProps): JSX.Element | null {
  const modal = useControlPanelStore((s) => s.modal);
  if (modal !== 'strategy_run') return null;
  return <StrategyRunModalInner key="strategy-run-modal" {...props} />;
}

function StrategyRunModalInner({
  solving,
  buildStartContext,
  onApplyStrategy,
}: StrategyRunModalProps): JSX.Element {
  const closeModal = useControlPanelStore((s) => s.closeModal);
  const phase = useStrategyStore((s) => s.phase);
  const status = useStrategyStore((s) => s.status);
  const result = useStrategyStore((s) => s.result);
  const errorMessage = useStrategyStore((s) => s.errorMessage);
  const lastStart = useStrategyStore((s) => s.lastStart);
  const start = useStrategyStore((s) => s.start);
  const stop = useStrategyStore((s) => s.stop);
  const reset = useStrategyStore((s) => s.reset);

  // 配置态本地草稿（mount 时初始化；race 默认 = 方案 B，20 分钟 = 增益起点）。
  const [minutes, setMinutes] = useState<StrategyMinutes>(20);
  const [mode, setMode] = useState<StrategyMode>('race');

  // ESC 关闭（仅关弹窗，绝不 stop）。
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      closeModal();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [closeModal]);

  /** 执行：排料参数与 handleStart 同源；sizes 空（后端 400）由 disabled 兜底。
   * band 透传（2026-08-22 解除互斥）：ctx.band 开启时进 /api/strategy/start，
   * 后端 _parse_band 同一校验点 → 9 键 config → CLI worker 进程内成带。
   * prefix 透传（2026-08-25 解除互斥，band 同款）：ctx.prefix 开启时同入载荷
   * （_parse_prefix 同一校验点，含 2+2 资格码 start 期拦截）。 */
  function handleExec(): void {
    const ctx = buildStartContext();
    void start({
      mode,
      minutes,
      seed: ctx.seed,
      gate_mm: ctx.gate_mm,
      sizes: ctx.sizes,
      per_type: ctx.per_type,
      quantities: ctx.quantities,
      band: ctx.band,
      prefix: ctx.prefix,
    });
  }

  /** 重试：start 被拒（lastStart 在场）→ 原载荷重启；run 中途失败 → 回配置态。 */
  function handleRetry(): void {
    if (lastStart !== null) void start(lastStart);
    else reset();
  }

  function handleOverlayMouseDown(e: React.MouseEvent): void {
    // 仅当 mousedown 落在 overlay 自身（非冒泡子元素）时关闭；关闭不终止运行。
    if (e.target === e.currentTarget) closeModal();
  }

  function handleModalMouseDown(e: React.MouseEvent): void {
    e.stopPropagation();
  }

  return createPortal(
    <div
      className="strategy-overlay"
      onMouseDown={handleOverlayMouseDown}
      data-testid="strategy-overlay"
    >
      <div
        className="strategy-modal"
        role="dialog"
        aria-modal="true"
        aria-label="高级运行"
        onMouseDown={handleModalMouseDown}
      >
        <div className="strategy-head">
          <span className="strategy-title">高级运行</span>
          <button
            type="button"
            className="strategy-close"
            aria-label="关闭"
            onClick={closeModal}
            data-testid="strategy-close"
          >
            ✕
          </button>
        </div>

        {phase === 'idle' && (
          <ConfigState
            minutes={minutes}
            mode={mode}
            solving={solving}
            buildStartContext={buildStartContext}
            onMinutes={setMinutes}
            onMode={setMode}
            onExec={handleExec}
          />
        )}

        {(phase === 'starting' || phase === 'running') && (
          <ProgressState status={status} onStop={() => void stop()} />
        )}

        {(phase === 'done' || phase === 'stopped') && (
          <ResultState
            phase={phase}
            status={status}
            result={result}
            onApplyStrategy={onApplyStrategy}
            onAgain={reset}
          />
        )}

        {phase === 'error' && (
          <ErrorState
            message={errorMessage ?? status?.error ?? '未知错误'}
            onRetry={handleRetry}
          />
        )}

        {phase === 'orphan' && (
          <OrphanState status={status} onCleanup={() => void stop()} />
        )}
      </div>
    </div>,
    document.body,
  );
}

// ------------------------------------------------------------- 配置态

interface ConfigStateProps {
  minutes: StrategyMinutes;
  mode: StrategyMode;
  solving: boolean;
  buildStartContext: () => StartContext;
  onMinutes: (m: StrategyMinutes) => void;
  onMode: (m: StrategyMode) => void;
  onExec: () => void;
}

function ConfigState({
  minutes,
  mode,
  solving,
  buildStartContext,
  onMinutes,
  onMode,
  onExec,
}: ConfigStateProps): JSX.Element {
  const desc = MODE_OPTIONS.find((o) => o.value === mode)?.desc ?? '';
  // 未选码号（与 handleStart sizes 非空校验同源）—— 后端对空 sizes 400，前置禁用。
  const sizesEmpty = buildStartContext().sizes.length === 0;
  const execDisabled = solving || sizesEmpty;
  return (
    <>
      <div className="strategy-field">
        <label htmlFor="strategy-minutes">总预算时长</label>
        <select
          id="strategy-minutes"
          className="strategy-select"
          data-testid="strategy-minutes"
          value={minutes}
          onChange={(e) => onMinutes(Number(e.target.value) as StrategyMinutes)}
        >
          {MINUTES_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div className="strategy-field">
        <label htmlFor="strategy-mode">模式</label>
        <select
          id="strategy-mode"
          className="strategy-select"
          data-testid="strategy-mode"
          value={mode}
          onChange={(e) => onMode(e.target.value as StrategyMode)}
        >
          {MODE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div className="strategy-mode-desc" data-testid="strategy-mode-desc">
        {desc}
      </div>
      <div className="strategy-hint" data-testid="strategy-min-hint">
        10 分钟档两模式与均分打平，20 分钟起有增益
      </div>
      <div className="strategy-hint">排料参数取当前面板：码号 / 高级配置 / 数量矩阵</div>
      <div className="strategy-actions">
        <button
          type="button"
          className="strategy-btn-exec"
          data-testid="strategy-exec-btn"
          disabled={execDisabled}
          onClick={onExec}
          title={sizesEmpty ? '请先在面板勾选码号' : undefined}
        >
          执行
        </button>
      </div>
    </>
  );
}

// ------------------------------------------------------------- 进度态（五件套）

interface ProgressStateProps {
  status: StrategyStatus | null;
  onStop: () => void;
}

function ProgressState({ status, onStop }: ProgressStateProps): JSX.Element {
  const modeLabel =
    status?.mode === 'se' ? 'SE 顺延' : status?.mode === 'race' ? 'race 门杀' : '策略运行';
  const total = status?.total_budget_sec ?? null;
  const elapsed = status?.elapsed_sec ?? null;
  // ② 大数字 = max(incumbent.density, 当前 seed best_frame density)（全局最优）。
  const inc = status?.incumbent?.density ?? null;
  const cur = status?.current?.density ?? null;
  const best = inc === null && cur === null ? null : Math.max(inc ?? -1, cur ?? -1);
  // ③ 预算进度条（墙钟口径，标「≈」）。
  const pctWidth =
    total !== null && total > 0 && elapsed !== null
      ? `${Math.min(100, Math.max(0, (elapsed / total) * 100)).toFixed(1)}%`
      : '0%';
  // ④ 阶段行：SE 延长检测（best_frame_s{seed}_ext 出现 → current.ext）优先。
  const perSeed = status?.per_seed ?? [];
  const plannedLen = status?.plan?.planned_seeds?.length ?? 0;
  const stageText =
    status?.mode === 'se' && status?.current?.ext && status.current.seed !== null
      ? `延长中 · 冠军 seed ${status.current.seed}`
      : plannedLen > 0
        ? `第 ${Math.min(perSeed.length + 1, plannedLen)}/${plannedLen} 轮 · seed ${
            status?.current?.seed ?? '—'
          } · 求解中`
        : '启动中 · 定位 run 目录…';
  // ⑤ seed chips（两模式不同结构）+ 最近 1 条事件行。
  const chips = status?.mode === 'se' ? seChips(status) : raceChips(status);
  const events = status?.events ?? [];
  return (
    <>
      <div className="strategy-title-line" data-testid="strategy-progress-title">
        {modeLabel} · 总预算 {fmtBudget(total)} · 已跑 {fmtElapsed(elapsed)}
      </div>
      <div className="strategy-big-wrap">
        <div className="strategy-big-density" data-testid="strategy-big-density">
          {fmtDensity(best)}
        </div>
        <div className="strategy-big-density-label">当前全局最优利用率（原面积口径）</div>
      </div>
      <div>
        <div className="strategy-budget-bar" data-testid="strategy-budget-bar">
          <div className="strategy-budget-fill" style={{ width: pctWidth }} />
        </div>
        <div className="strategy-budget-label" data-testid="strategy-budget-label">
          ≈{elapsed === null ? '—' : `${Math.floor(elapsed)}s`} /{' '}
          {total === null ? '—' : `${total}s`}（墙钟口径）
        </div>
      </div>
      <div className="strategy-stage-line" data-testid="strategy-stage">
        {stageText}
      </div>
      <div className="strategy-seed-chips" data-testid="strategy-seed-chips">
        {chips.length === 0 ? (
          <span className="strategy-chip pending">seed 队列待 plan…</span>
        ) : (
          chips.map((c, i) => (
            <span key={`${c.seed ?? 'x'}-${i}`} className={`strategy-chip ${c.state}`}>
              {c.seed === null ? c.label : `${c.seed} ${c.label}`}
            </span>
          ))
        )}
      </div>
      <div className="strategy-event-line" data-testid="strategy-event">
        {fmtLastEvent(events[events.length - 1])}
      </div>
      <div className="strategy-hint" data-testid="strategy-close-hint">
        关闭弹窗不会终止运行（后台继续跑，重新打开可看进度）
      </div>
      <div className="strategy-actions">
        <button
          type="button"
          className="strategy-stop-btn"
          data-testid="strategy-stop-btn"
          onClick={onStop}
        >
          终止运行
        </button>
      </div>
    </>
  );
}

// ------------------------------------------------------------- 结果态

interface ResultStateProps {
  phase: 'done' | 'stopped';
  status: StrategyStatus | null;
  result: StrategyResult | null;
  onApplyStrategy?: (result: StrategyResult) => void;
  onAgain: () => void;
}

function ResultState({
  phase,
  status,
  result,
  onApplyStrategy,
  onAgain,
}: ResultStateProps): JSX.Element {
  // result 尚未拉到（refresh 网络错重试窗口）→ 降级占位。
  if (result === null) {
    return (
      <div className="strategy-result-detail" data-testid="strategy-result-loading">
        正在读取运行结果…
      </div>
    );
  }
  const best = result.best;
  // 模式汇总：race = M 轮中 K 轮门杀 · 全程 X 分 X 秒（墙钟 elapsed_sec）；
  // se = k 轮筛选 + 冠军 seed 延长。
  const perSeed = result.summary.per_seed ?? [];
  let modeSummary: string;
  if (result.summary.race) {
    const kills = result.summary.race.gated_seeds.length;
    modeSummary = `race：${perSeed.length} 轮中 ${kills} 轮门杀 · 全程 ${fmtElapsed(
      status?.elapsed_sec,
    )}`;
  } else if (result.summary.se) {
    modeSummary = `SE：${result.summary.se.k_screens} 轮筛选 + 冠军 seed ${
      result.summary.se.champion ?? '—'
    } 延长 ${Math.round(result.summary.se.ext_s)}s`;
  } else {
    modeSummary = `共 ${perSeed.length} 轮`;
  }
  return (
    <>
      <div
        className={`strategy-result-head${phase === 'stopped' ? ' stopped' : ''}`}
        data-testid="strategy-result-head"
      >
        {phase === 'done'
          ? `完成 · 最优 ${fmtDensity(best.density)}`
          : `已终止 · 保留终止前最优 ${fmtDensity(best.density)}`}
      </div>
      <div className="strategy-result-detail" data-testid="strategy-result-detail">
        seed {best.seed ?? '—'} · 用布 {fmtWidthM(best.width_mm)}
      </div>
      <div className="strategy-result-detail" data-testid="strategy-mode-summary">
        {modeSummary}
      </div>
      {result.warning !== undefined && (
        <div className="strategy-warning" data-testid="strategy-warning">
          ⚠ {result.warning}
        </div>
      )}
      <div className="strategy-actions">
        <button
          type="button"
          className="strategy-btn-again"
          data-testid="strategy-again-btn"
          onClick={onAgain}
        >
          再次运行
        </button>
        <button
          type="button"
          className="strategy-btn-apply"
          data-testid="strategy-apply-btn"
          disabled={onApplyStrategy === undefined}
          title={
            onApplyStrategy === undefined
              ? '应用回调未接线'
              : '应用到主画布（会替换当前画布的排料方案）'
          }
          onClick={() => onApplyStrategy?.(result)}
        >
          应用到主画布
        </button>
      </div>
    </>
  );
}

// ------------------------------------------------------------- error / orphan

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }): JSX.Element {
  return (
    <>
      <div className="strategy-result-head error" data-testid="strategy-error-head">
        运行失败
      </div>
      <div className="strategy-error-detail" data-testid="strategy-error">
        {message}
      </div>
      <div className="strategy-actions">
        <button
          type="button"
          className="strategy-btn-exec"
          data-testid="strategy-retry-btn"
          onClick={onRetry}
        >
          重试
        </button>
      </div>
    </>
  );
}

function OrphanState({
  status,
  onCleanup,
}: {
  status: StrategyStatus | null;
  onCleanup: () => void;
}): JSX.Element {
  return (
    <>
      <div className="strategy-result-head stopped" data-testid="strategy-orphan-head">
        检测到遗留运行
      </div>
      <div className="strategy-result-detail" data-testid="strategy-orphan-detail">
        pid {status?.pid ?? '—'}（进程{status?.alive ? '仍在运行' : '已退出'}）
        {status?.mode ? ` · 模式 ${status.mode}` : ''}
        {' · '}服务器重启后遗留，可清理后重新启动
      </div>
      <div className="strategy-actions">
        <button
          type="button"
          className="strategy-stop-btn"
          data-testid="strategy-cleanup-btn"
          onClick={onCleanup}
        >
          清理
        </button>
      </div>
    </>
  );
}
