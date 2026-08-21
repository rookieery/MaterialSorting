// RunRegistry —— 排料 run 的 mutable 存储（**不进 React state**）。
//
// 每个 run 对应一次 WS 连接 + 一组 WS 推送的 frames。frames 是高频数据（每帧 ~100B、单 run 可达数千帧），
// 进 React state 会引发 reconciliation 风暴；故此 Registry 用纯模块级数组持有，hook 通过引用读写，
// React 仅订阅高层的 status / renderTick（见 US-003 appStore）。
//
// 生命周期：useSolveRun.start(seed) → create(seed) → WS onmessage 推 frame → push(frame)。
// 新一次 start / cleanup → clear() 关闭所有 WS 并清空。

import type { FinalMsg, FrameMsg, ManifestMsg, StageMsg } from '../types/ws';

/** 单个 run 的全部上下文（高频字段 frames/lastFrame 直接 mutate）。 */
export interface RunRecord {
  seed: number;
  /** 当前 run 的 WS（仅 start() 创建时持有引用；onclose 后置 null 释放）。 */
  ws: WebSocket | null;
  /** manifest 一次性引用（含 gate_mm / pieces 元信息）。 */
  manifest: ManifestMsg | null;
  /**
   * US-012 band 带内聚排 stage 统计（manifest 前唯一一次；band 关闭 → 恒 null）。
   * 仅信息记录（状态行「腰头成带中…」由 onStage 回调驱动），不影响 phase / done。
   */
  stage: StageMsg | null;
  /** 所有中间解帧（mutable 数组，hook 直接 push）。 */
  frames: FrameMsg[];
  /** 最新一帧（= frames[frames.length-1]，缓存便于渲染层 O(1) 取）。 */
  lastFrame: FrameMsg | null;
  /** final.density（原面积口径），完成后填入。 */
  finalDensity: number;
  /** final.density_sparrow（参考）。 */
  finalDensitySparrow: number;
  /** 已结束（final / error / onclose 任一到达）。 */
  done: boolean;
  /** 错误信息（error 消息原文）。 */
  error: string | null;
  /** 已观察到的最大 width_mm（用于 SVG viewBox 动态扩展）。 */
  viewBoxMaxW: number;
  /** US-027：用户 stop 触发的结束（收到 {type:'stopped'} 置 true；用于 phase 状态机区分 stopped/done/error）。 */
  stopped: boolean;
}

/** 模块级 mutable 数组 —— 跨 hook 实例共享。 */
const _runs: RunRecord[] = [];

export const runRegistry = {
  /** 创建一个新 run（push 进数组，返回引用以便 hook mutate）。 */
  create(seed: number): RunRecord {
    const rec: RunRecord = {
      seed,
      ws: null,
      manifest: null,
      stage: null,
      frames: [],
      lastFrame: null,
      finalDensity: 0,
      finalDensitySparrow: 0,
      done: false,
      error: null,
      viewBoxMaxW: 0,
      stopped: false,
    };
    _runs.push(rec);
    return rec;
  },

  /** 关闭所有 WS 并清空（start 前重置 / unmount 时调用）。 */
  clear(): void {
    for (const r of _runs) {
      const ws = r.ws;
      r.ws = null;
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onclose = null;
        ws.onerror = null;
        try {
          ws.close();
        } catch {
          /* 已经关闭 / 连接中 —— 忽略 */
        }
      }
    }
    _runs.length = 0;
  },

  /** 只读视图（订阅层用；返回的元素本身仍 mutable）。 */
  list(): readonly RunRecord[] {
    return _runs;
  },

  /** 按 final.density 选最优 run（无 lastFrame 的不参与）。 */
  bestRun(): RunRecord | null {
    let best: RunRecord | null = null;
    for (const r of _runs) {
      if (!r.lastFrame) continue;
      if (best === null || r.finalDensity > best.finalDensity) best = r;
    }
    return best;
  },
};

/** 在 final 到达后更新 record（density 双口径）。 */
export function applyFinal(rec: RunRecord, m: FinalMsg): void {
  rec.finalDensity = m.density;
  rec.finalDensitySparrow = m.density_sparrow;
  if (rec.frames.length > 0) rec.lastFrame = rec.frames[rec.frames.length - 1];
}
