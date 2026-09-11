// SynthRunStore —— 合成 run 信号 + applySyntheticRun 共享落笔（状态文件 US-004）。
//
// 背景：applyStrategyResult（策略/极限「应用到主画布」，NestingPage）与
// applyRestorePayload（状态文件恢复编排，lib/stateFile）两条路径都要「显式清场 +
// 合成单条 done RunRecord + 主画布切 done 态」。RunRecord 落笔是纯模块级操作
// （runRegistry / editStore / appStore 均可 getState 直达），但 seeds / phase /
// status 是 NestingPage 本地 React state —— 跨模块不可直接 set。故拆两层：
//   1. applySyntheticRun（本文件导出）：清场 + registry 落笔 + seek 回 live +
//      bump 信号 —— 不依赖任何组件挂载（单测可直跑；恢复路径在上传回调里也能
//      完整落笔，NestingPage 未挂载时只是信号无人消费）；
//   2. NestingPage useEffect([token])：消费信号 → setSeeds([seed]) /
//      setPhase('done') / setStatus(note) / doneCount·totalSeeds ref 重置 /
//      provenance 小字记录。信号只载 UI 参数（seed/note/origin），几何真相在
//      runRegistry（本 store 零几何持有）。
//
// 共享口径（对齐旧 NestingPage.applyStrategyResult 行为 + 深拷贝强化）：
//   - runRegistry.clear()（关旧 WS —— 主画布现有对比 run 被清掉，破坏性操作由
//     用户显式触发）+ editStore.invalidate()（旧编辑会话对合成 record 的基线
//     无意义）；editStore.save/reset 的 registry 校验防陈旧写回；
//   - frames = [合成帧]、lastFrame = 同帧 —— placed_items **深拷贝**（translation
//     数组逐项拷断，mirror 按 omit-when-false 只在 true 时带键，editStore
//     .deepCopyItems 同口径）：源数组（strategyStore.result.best.placed_items /
//     恢复响应 res.placed）不被 editStore.applyToRun 的原地写回穿透 mutate ——
//     修复旧 applyStrategyResult 直接共享 result 数组导致编辑保存污染策略 store
//     结果的别名问题（重新应用同一 result 现恒回 pristine 布局）；
//   - finalDensity/finalDensitySparrow ← 帧 density 双口径、viewBoxMaxW ← 帧
//     width_mm、done=true / error=null / stopped=false —— NestSVG /
//     ConvergenceCurve / PlaybackBar / ExportButtons / bestRun() 零改动兼容；
//   - origin（RunRecord additive 可选字段）：WS 普通求解不设（undefined = 'solve'，
//     保存端 buildSavePayload 不写 provenance 键 —— 老文件零惩罚）；策略/极限应用
//     从 StrategyResult.mode + 本族 lastStart 记入（NestingPage.originOfStrategyResult）；
//     恢复端从 run.provenance 透传（缺省 {kind:'solve'}）。纯展示级 ——
//     run-provenance 来源小字消费，渲染/导出零消费。

import { create } from 'zustand';
import { useAppStore } from './appStore';
import { useEditStore } from './editStore';
import { runRegistry, type RunRecord } from './runRegistry';
import type { Pt, PlacedItem } from '../types/piece';
import type { RunOrigin } from '../types/stateFile';
import type { FrameMsg, ManifestMsg } from '../types/ws';

export interface SynthRunSignalState {
  /** 信号令牌（0 = 尚未发出；每次 applySyntheticRun 递增 —— NestingPage 以 token 变化为消费触发）。 */
  token: number;
  /** 合成 run 的 seed（NestingPage setSeeds([seed]) 消费）。 */
  seed: number;
  /** StatusLine 文案（调用方组装，如「策略 run 已应用：seed 3 · 88.38%」/「状态文件已恢复：…」）。 */
  note: string;
  /** 结果来源（run-provenance 小字数据源；undefined = 不展示（WS 普通求解口径））。 */
  origin: RunOrigin | undefined;
  /** 发信号（applySyntheticRun 内部调用；组件不直接消费）。 */
  signal: (seed: number, note: string, origin: RunOrigin | undefined) => void;
}

export const useSynthRunStore = create<SynthRunSignalState>((set) => ({
  token: 0,
  seed: 0,
  note: '',
  origin: undefined,
  signal: (seed, note, origin) =>
    set((s) => ({ token: s.token + 1, seed, note, origin })),
}));

/**
 * PlacedItem 深拷贝（translation 是数组引用，必须逐项拷断与源数组的耦合；保序 =
 * placed_items 数组原序）。mirror omit-when-false 透传：`mirror === true` 才带键
 * —— 与 editStore.deepCopyItems / lib/stateFile 保存侧同口径（键集与 wire 契约一致）。
 * 状态文件 US-004 起导出共享（保存侧 buildSavePayload 同一实现，不再各持一份拷贝）。
 */
export function deepCopyPlaced(items: readonly PlacedItem[]): PlacedItem[] {
  return items.map((it) => ({
    id: it.id,
    rotation: it.rotation,
    translation: [it.translation[0], it.translation[1]] as Pt,
    ...(it.mirror === true ? { mirror: true } : {}),
  }));
}

/**
 * 合成单条 done RunRecord 并发信号（策略/极限应用 + 状态文件恢复共用）。
 *
 * 清场语义与 handleStart 同口径（关旧 WS + 清 registry + 编辑态失效）；本函数不设
 * 防连击 / running 守卫 —— 调用方自理（applyStrategyResult 有 phase 守卫；恢复 =
 * 显式覆盖当前工作台，等同再上传母版 commit，求解中恢复即中止当前求解）。
 *
 * @param manifest  manifest（StrategyManifest 加 type 键 / 恢复响应 manifest 重算结果）。
 * @param frameLike 合成终局帧（FrameMsg 同形；phase='final' 与求解收尾帧口径一致；
 *                  placed_items 由本函数深拷贝，调用方可传共享引用）。
 * @param seed      合成 run 的 seed。
 * @param origin    结果来源（缺省不设 = 'solve' 口径，保存端不写 provenance 键）。
 * @param note      StatusLine 文案（空串 = 不改状态行 —— NestingPage 消费端空 note
 *                  跳过 setStatus，保留现场文案）。
 * @returns 置换后的 RunRecord 引用（ws=null 无 WS 可关；导出链路 bestRun() 直接选中）。
 */
export function applySyntheticRun(
  manifest: ManifestMsg,
  frameLike: FrameMsg,
  seed: number,
  origin?: RunOrigin,
  note = '',
): RunRecord {
  // 1) 清场：关旧 WS + 清 registry + 编辑态失效 + seek 回 live（NestSVG 显示 lastFrame）。
  runRegistry.clear();
  useEditStore.getState().invalidate();
  useAppStore.getState().setSeekTime(-1);

  // 2) 深拷贝 placed（见文件头共享口径 —— 源数组不被 applyToRun 写回穿透）。
  const frame: FrameMsg = {
    ...frameLike,
    placed_items: deepCopyPlaced(frameLike.placed_items),
  };

  // 3) 置换单条 RunRecord。
  const rec = runRegistry.create(seed);
  rec.manifest = manifest;
  rec.frames.push(frame);
  rec.lastFrame = frame;
  rec.finalDensity = frame.density;
  rec.finalDensitySparrow = frame.density_sparrow;
  rec.viewBoxMaxW = frame.width_mm;
  rec.done = true;
  rec.error = null;
  rec.stopped = false;
  if (origin !== undefined) rec.origin = origin;

  // 4) 信号 → NestingPage 消费（setSeeds/setPhase('done')/setStatus/ref 重置/provenance）。
  useSynthRunStore.getState().signal(seed, note, origin);
  return rec;
}

/** provenance.kind → 展示文案（四值枚举逐一覆盖）。 */
const KIND_TEXT: Record<RunOrigin['kind'], string> = {
  solve: '普通求解',
  strategy_se: '策略运行·SE',
  strategy_race: '策略运行·race',
  extreme: '极限运行',
};

/**
 * 来源小字文案（run-provenance 消费）：如「来源：极限运行(600s) · seed 0」。
 * config 形态宽松（手改文件容错）：仅识别 extreme 族 time_total_s / strategy 族
 * minutes 两个已知键，其余（含缺席）不渲染括号段 —— 展示级冗余不承重。
 */
export function provenanceText(origin: RunOrigin, seed: number): string {
  const c = origin.config ?? {};
  let cfg = '';
  if (typeof c.time_total_s === 'number') cfg = `(${c.time_total_s}s)`;
  else if (typeof c.minutes === 'number') cfg = `(${c.minutes}min)`;
  return `来源：${KIND_TEXT[origin.kind]}${cfg} · seed ${seed}`;
}
