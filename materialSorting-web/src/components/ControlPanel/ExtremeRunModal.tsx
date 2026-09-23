// ExtremeRunModal —— 「极限运行」弹窗（US-003；范本 StrategyRunModal —— 三态
// 骨架 / 关闭四通道不终止 run / 结果常驻等约定见彼处，此处只记差异）。
//
// 声明式受控 Portal：订阅 controlPanelStore.modal === 'extreme_run' 自显隐
// （与 'strategy_run'/'per_type' 单例互斥）；状态机消费 useExtremeStore
// （/api/extreme/* 四路由，族过滤见 strategyStore）。
//
// 与高级运行弹窗的三处刻意差异：
//   1) 配置态 = 总时长（四档预设 60/120（默认）/240/480 分钟 + 自定义 16~720
//      分钟）+ 模式下拉（2026-09-20 起，镜像高级运行结构：race 门杀（默认）/
//      SE 顺延 —— se 臂 CLI 展开 = 300s×k 筛选 + 冠军 600s warm 顺延）；极限
//      参数完全隐藏（exploration_pct / early_termination / num_workers /
//      quadtree_depth 是实验结论不是可调项，弹窗 UI 与文案均不出现）。SE 顺延
//      臂附多候选顺延最坏额外时长提示行（US-004，600s 延长 → 约 20 分钟动态
//      计算）；进度面 se 形态多候选渲染同高级运行（共用 ProgressState）。
//      预计轮数随时长实时更新：race = N = 1 + floor((T - 602.5) / 347.5)（首轮
//      全程 + 后续每轮期望耗时，期望口径「实际轮数 >= 预测」）；se = k 轮筛选
//      + 1 轮延长（名义口径 k = floor((T - 602.5) / 302.5) 下限 1）。
//   2) band/prefix 随排料参数透传（2026-08-30 解除拦截，与高级运行同款）：高级
//      配置开启时载荷直接带 ctx.band/ctx.prefix（后端 _parse_* 同一校验点），
//      弹窗内以只读状态行回显当前生效项 —— 参数本体只在高级配置里配。
//   3) 结果态追加只读提示「已固化实验参数」（不列参数值，2026-08-29 确认）。
//
// 进度态 / 结果态 / error / orphan 复用 StrategyRunModal 导出的同构组件
// （泛化优先于复制）：进度标题行覆写「极限运行」，se 形态（chips/延长阶段行/
// warm 提示）经 effectiveStrategy(status) 按 status.strategy 解析；结果应用按钮
// 走同一 onApply 回调（NestingPage.applyStrategyResult 合成 RunRecord）。

import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import type { StartContext } from '../../lib/params';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { useExtremeStore } from '../../store/strategyStore';
import type { StrategyResult } from '../../types/strategy';
import {
  ErrorState,
  OrphanState,
  ProgressState,
  ResultState,
  seExtHint,
} from './StrategyRunModal';

// ------------------------------------------------------------- 时长预设与轮数估算

/** 时长四档预设（分钟；120 = 方案 §4 推荐默认档）。 */
export const EXTREME_PRESET_MINUTES: readonly number[] = [60, 120, 240, 480];

/** 自定义分钟值域（16 分钟 = 960s >= 后端下限 905s；720 分钟 = 43200s = 后端上限）。 */
export const EXTREME_CUSTOM_MIN_MINUTES = 16;
export const EXTREME_CUSTOM_MAX_MINUTES = 720;

/** 极限运行双模式（2026-09-20 起，镜像高级运行的模式下拉结构）。 */
export type ExtremeMode = 'race' | 'se';

export const EXTREME_MODE_OPTIONS: {
  value: ExtremeMode;
  label: string;
  desc: string;
}[] = [
  {
    value: 'race',
    label: 'race 门杀（默认）',
    desc: '每 seed 600s 预算，300s 门处严格破纪录才续跑，弱 seed 提前淘汰省出预算',
  },
  {
    value: 'se',
    label: 'SE 顺延',
    desc: '300s × k 轮筛选 + 冠军 seed 600s warm 顺延（自冠军解热启动，增量搜索）',
  },
];

/** 轮数期望口径（方案 §2.5）：首轮全程 602.5s + 后续每轮期望 ~347.5s。 */
export const EXTREME_FIRST_ROUND_S = 602.5;
export const EXTREME_PER_ROUND_S = 347.5;

/**
 * 预计轮数 N = 1 + floor((T - 602.5) / 347.5)（T = 总预算秒；下限钳 1）。
 * 期望口径：门杀省出的预算会自动多跑后续轮，故实际轮数 >= 预测。
 */
export function estimateExtremeRounds(totalSec: number): number {
  return Math.max(1, 1 + Math.floor((totalSec - EXTREME_FIRST_ROUND_S) / EXTREME_PER_ROUND_S));
}

/**
 * se 臂名义记账口径（与 se_plan 同式）：冠军全程 602.5s（600s 延长 + 2.5s 启动）
 * + 每轮筛选 302.5s（300s + 2.5s）—— 与 race 600 档最低总预算同界（905s）。
 */
export const EXTREME_SE_FULL_UNIT_S = 602.5;
export const EXTREME_SE_SCREEN_UNIT_S = 302.5;

/**
 * se 臂预计筛选轮数 k = max(1, floor((T - 602.5) / 302.5))（名义口径，非期望）。
 * 总轮数 = k 筛选 + 1 延长；轮数是计划值（与 race 的期望口径不同，se 恒跑满 k 轮）。
 */
export function estimateExtremeSeScreens(totalSec: number): number {
  return Math.max(
    1,
    Math.floor((totalSec - EXTREME_SE_FULL_UNIT_S) / EXTREME_SE_SCREEN_UNIT_S),
  );
}

/**
 * se 臂延长秒（US-004 多候选提示用）：CLI 展开 se_ext = extreme_budget，web
 * /api/extreme/start 不带 --extreme-budget → 恒默认 600（EXTREME_BUDGET_S 镜像；
 * 1200 档仅 CLI 手敲可达 → 最坏额外 2×600 = 约 20 分钟，动态计算不写死）。
 */
export const EXTREME_SE_EXT_S = 600;

/** 预设分钟 -> 按钮文案（整小时档用「N 小时」）。 */
function presetLabel(minutes: number): string {
  return minutes % 60 === 0 ? `${minutes / 60} 小时` : `${minutes} 分钟`;
}

/** 自定义分钟解析：正整数字符串且在 [16, 720] -> 数字；否则 null（执行按钮置灰）。 */
export function parseCustomMinutes(raw: string): number | null {
  const t = raw.trim();
  if (!/^\d+$/.test(t)) return null;
  const m = Number(t);
  if (m < EXTREME_CUSTOM_MIN_MINUTES || m > EXTREME_CUSTOM_MAX_MINUTES) return null;
  return m;
}

// ------------------------------------------------------------- 组件

export interface ExtremeRunModalProps {
  /** 主画布是否求解中（执行按钮互斥 —— 防 CPU 竞争拖慢长跑）。 */
  solving: boolean;
  /** handleStart 同源 start 上下文构造器（collectStartContext 单一实现，不复制逻辑）。 */
  buildStartContext: () => StartContext;
  /** 结果态「应用到主画布」回调（未传 -> 应用按钮 disabled）。 */
  onApplyExtreme?: (result: StrategyResult) => void;
}

export function ExtremeRunModal(props: ExtremeRunModalProps): JSX.Element | null {
  const modal = useControlPanelStore((s) => s.modal);
  if (modal !== 'extreme_run') return null;
  return <ExtremeRunModalInner key="extreme-run-modal" {...props} />;
}

function ExtremeRunModalInner({
  solving,
  buildStartContext,
  onApplyExtreme,
}: ExtremeRunModalProps): JSX.Element {
  const closeModal = useControlPanelStore((s) => s.closeModal);
  const phase = useExtremeStore((s) => s.phase);
  const status = useExtremeStore((s) => s.status);
  const result = useExtremeStore((s) => s.result);
  const errorMessage = useExtremeStore((s) => s.errorMessage);
  const lastStart = useExtremeStore((s) => s.lastStart);
  const start = useExtremeStore((s) => s.start);
  const stop = useExtremeStore((s) => s.stop);
  const reset = useExtremeStore((s) => s.reset);

  // 配置态本地草稿（mount 时初始化；默认 120 分钟 = 方案 §4 推荐档、race = 有
  // 完整验收背书的默认臂；se 为 2026-09-20 新增可选项）。
  const [presetMin, setPresetMin] = useState<number | 'custom'>(120);
  const [customText, setCustomText] = useState<string>(String(EXTREME_CUSTOM_MIN_MINUTES));
  const [mode, setMode] = useState<ExtremeMode>('race');

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

  /** collectStartContext 同源载荷公共段（seed/gate_mm/sizes/per_type/quantities
   * + band/prefix 透传 —— 与 StrategyRunModal.handleExec 同款，2026-08-30；
   * + strategy 模式透传 2026-09-20）。 */
  function startPayload(timeTotalS: number) {
    const ctx = buildStartContext();
    return {
      time_total_s: timeTotalS,
      strategy: mode,
      seed: ctx.seed,
      gate_mm: ctx.gate_mm,
      sizes: ctx.sizes,
      per_type: ctx.per_type,
      quantities: ctx.quantities,
      band: ctx.band,
      prefix: ctx.prefix,
    };
  }

  /** 执行：排料参数与 handleStart 同源（band/prefix 随高级配置透传）。 */
  function handleExec(): void {
    if (presetMin === 'custom') {
      const m = parseCustomMinutes(customText);
      if (m === null) return; // 非法自定义（按钮已置灰，兜底）
      void start(startPayload(m * 60));
      return;
    }
    void start(startPayload(presetMin * 60));
  }

  /** 重试：start 被拒（lastStart 在场）-> 原载荷重启；run 中途失败 -> 回配置态。 */
  function handleRetry(): void {
    if (lastStart !== null) void start(lastStart);
    else reset();
  }

  function handleOverlayMouseDown(e: React.MouseEvent): void {
    if (e.target === e.currentTarget) closeModal();
  }

  function handleModalMouseDown(e: React.MouseEvent): void {
    e.stopPropagation();
  }

  return createPortal(
    <div
      className="strategy-overlay"
      onMouseDown={handleOverlayMouseDown}
      data-testid="extreme-overlay"
    >
      <div
        className="strategy-modal"
        role="dialog"
        aria-modal="true"
        aria-label="极限运行"
        onMouseDown={handleModalMouseDown}
      >
        <div className="strategy-head">
          <span className="strategy-title">极限运行</span>
          <button
            type="button"
            className="strategy-close"
            aria-label="关闭"
            onClick={closeModal}
            data-testid="extreme-close"
          >
            ✕
          </button>
        </div>

        {phase === 'idle' && (
          <ExtremeConfigState
            presetMin={presetMin}
            customText={customText}
            mode={mode}
            solving={solving}
            buildStartContext={buildStartContext}
            onPreset={setPresetMin}
            onCustomText={setCustomText}
            onMode={setMode}
            onExec={handleExec}
          />
        )}

        {(phase === 'starting' || phase === 'running') && (
          <ProgressState status={status} onStop={() => void stop()} modeLabel="极限运行" />
        )}

        {(phase === 'done' || phase === 'stopped') && (
          <ResultState
            phase={phase}
            status={status}
            result={result}
            onApplyStrategy={onApplyExtreme}
            onAgain={reset}
            extraHint="已固化实验参数（按实验结论固定，不可调）"
          />
        )}

        {phase === 'error' && (
          <ErrorState
            message={errorMessage ?? status?.error ?? '未知错误'}
            onRetry={handleRetry}
          />
        )}

        {phase === 'orphan' && <OrphanState status={status} onCleanup={() => void stop()} />}
      </div>
    </div>,
    document.body,
  );
}

// ------------------------------------------------------------- 配置态

interface ExtremeConfigStateProps {
  presetMin: number | 'custom';
  customText: string;
  mode: ExtremeMode;
  solving: boolean;
  buildStartContext: () => StartContext;
  onPreset: (p: number | 'custom') => void;
  onCustomText: (t: string) => void;
  onMode: (m: ExtremeMode) => void;
  onExec: () => void;
}

function ExtremeConfigState({
  presetMin,
  customText,
  mode,
  solving,
  buildStartContext,
  onPreset,
  onCustomText,
  onMode,
  onExec,
}: ExtremeConfigStateProps): JSX.Element {
  const customMin = parseCustomMinutes(customText);
  const totalMin = presetMin === 'custom' ? customMin : presetMin;
  const modeDesc = EXTREME_MODE_OPTIONS.find((o) => o.value === mode)?.desc ?? '';
  // 预计轮数：race = 期望口径（实际 ≥ 预测）；se = 名义口径（k 筛选 + 1 延长）。
  const rounds =
    mode === 'race'
      ? totalMin === null
        ? null
        : estimateExtremeRounds(totalMin * 60)
      : null;
  const seScreens =
    mode === 'se' ? (totalMin === null ? null : estimateExtremeSeScreens(totalMin * 60)) : null;
  // 未选码号（与 handleStart sizes 非空校验同源 —— 后端对空 sizes 400）。
  const ctx = buildStartContext();
  const sizesEmpty = ctx.sizes.length === 0;
  // band/prefix 生效项回显（2026-08-30 起透传 —— 只读状态行，参数本体在高级
  // 配置里配，这里不置灰不拦截，与高级运行弹窗行为一致）。
  const layoutParts: string[] = [];
  if (ctx.band !== null) layoutParts.push(`腰头成带 ${ctx.band.label}`);
  if (ctx.prefix !== null) {
    layoutParts.push(`起始端成套 ${ctx.prefix.front}/${ctx.prefix.back}`);
  }
  const customInvalid = presetMin === 'custom' && customMin === null;
  const execDisabled = solving || sizesEmpty || customInvalid;
  return (
    <>
      <div className="strategy-field">
        <label>总时长</label>
        <div className="extreme-preset-row" data-testid="extreme-presets">
          {EXTREME_PRESET_MINUTES.map((m) => (
            <button
              key={m}
              type="button"
              className={`extreme-preset-btn${presetMin === m ? ' active' : ''}`}
              data-testid={`extreme-preset-${m}`}
              aria-pressed={presetMin === m}
              onClick={() => onPreset(m)}
            >
              {presetLabel(m)}
            </button>
          ))}
          <button
            type="button"
            className={`extreme-preset-btn${presetMin === 'custom' ? ' active' : ''}`}
            data-testid="extreme-preset-custom"
            aria-pressed={presetMin === 'custom'}
            onClick={() => onPreset('custom')}
          >
            自定义
          </button>
        </div>
        {presetMin === 'custom' && (
          <div className="extreme-custom-row">
            <input
              type="number"
              className="extreme-custom-input"
              data-testid="extreme-custom-input"
              inputMode="numeric"
              min={EXTREME_CUSTOM_MIN_MINUTES}
              max={EXTREME_CUSTOM_MAX_MINUTES}
              value={customText}
              onChange={(e) => onCustomText(e.target.value)}
              aria-label="自定义总时长（分钟）"
            />
            <span className="extreme-custom-unit">
              分钟（{EXTREME_CUSTOM_MIN_MINUTES}~{EXTREME_CUSTOM_MAX_MINUTES}）
            </span>
          </div>
        )}
      </div>
      <div className="strategy-field">
        <label htmlFor="extreme-mode">模式</label>
        <select
          id="extreme-mode"
          className="strategy-select"
          data-testid="extreme-mode"
          value={mode}
          onChange={(e) => onMode(e.target.value as ExtremeMode)}
        >
          {EXTREME_MODE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div className="strategy-mode-desc" data-testid="extreme-mode-desc">
        {modeDesc}
      </div>
      <div className="extreme-rounds" data-testid="extreme-rounds">
        {mode === 'race' ? (
          rounds === null ? (
            <>请输入 {EXTREME_CUSTOM_MIN_MINUTES}~{EXTREME_CUSTOM_MAX_MINUTES} 之间的整数分钟</>
          ) : (
            <>预计 {rounds} 轮 seed（实际轮数 ≥ 预测，省出预算自动多跑）</>
          )
        ) : seScreens === null ? (
          <>请输入 {EXTREME_CUSTOM_MIN_MINUTES}~{EXTREME_CUSTOM_MAX_MINUTES} 之间的整数分钟</>
        ) : (
          <>预计 {seScreens} 轮筛选 + 1 轮延长（warm 顺延）</>
        )}
      </div>
      {mode === 'se' && (
        // SE 顺延臂多候选提交前提示（US-004）：最坏额外时长按延长秒动态计算
        // （极限 se 臂 ext = 600s → 约 20 分钟；跑动中实际值见进度态 extra 行）。
        <div className="strategy-hint" data-testid="extreme-ext-hint">
          {seExtHint(EXTREME_SE_EXT_S)}
        </div>
      )}
      {layoutParts.length > 0 && (
        <div className="strategy-hint" data-testid="extreme-layout-hint">
          将随排料参数生效：{layoutParts.join(' · ')}
        </div>
      )}
      <div className="strategy-hint">排料参数取当前面板：码号 / 高级配置 / 数量矩阵</div>
      <div className="strategy-hint" data-testid="extreme-close-hint">
        关闭弹窗不会终止运行（后台继续跑，重新打开可看进度）
      </div>
      <div className="strategy-actions">
        <button
          type="button"
          className="strategy-btn-exec"
          data-testid="extreme-exec-btn"
          disabled={execDisabled}
          onClick={onExec}
          title={
            sizesEmpty
              ? '请先在面板勾选码号'
              : customInvalid
                ? `自定义分钟须为 ${EXTREME_CUSTOM_MIN_MINUTES}~${EXTREME_CUSTOM_MAX_MINUTES} 的整数`
                : undefined
          }
        >
          执行
        </button>
      </div>
    </>
  );
}
