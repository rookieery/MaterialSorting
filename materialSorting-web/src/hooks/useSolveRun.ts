// useSolveRun —— 单 run 求解生命周期 hook（WS 连接 + 消息分发 → Registry）。
//
// 设计要点（与旧 vanilla 实现 connectRun 等价）：
//   1. start(cfg) 显式 new WebSocket（**不在 useEffect 里自动连**）→ React StrictMode 双 mount 不会触发两次连接。
//   2. WS URL 走 lib/ws.solveWsUrl()（相对 host，dev/prod 自适配）。
//   3. onmessage 按 type 字段判别分发：manifest / frame / final / stopped / error。
//   4. frames 直接 push 进 RunRecord（mutable，**不进 React state**），高频渲染由 US-003 renderTick 闸驱动。
//   5. onclose / onerror → onDone（done flag 防重复）；不重连。
//
// US-002 仅交付契约 + Registry 落盘；ControlPanel / NestSVG 在 US-003..007 拼装。

import { useCallback, useRef, useState } from 'react';
import type {
  ErrorMsg,
  FinalMsg,
  FrameMsg,
  ManifestMsg,
  ServerMsg,
  StartPayload,
} from '../types/ws';
import type { PerTypeOverrides, SolveParams } from '../types/v03';
import { solveWsUrl } from '../lib/ws';
import { applyFinal, runRegistry, type RunRecord } from '../store/runRegistry';

/** start(cfg) 入参（外部传纯数据；hook 内部补 action/per_type 默认）。 */
export interface StartConfig {
  sizes: number[];
  time: number;
  seed: number;
  /** 幅宽（mm）= sparrow strip_height / 排料边框宽度（前端 cm ×10；透传 WS StartPayload.gate_mm）。 */
  gate_mm: number;
  params: SolveParams;
  /** per_type 空 / 不传 → 序列化为 null（同旧 vanilla 实现）。 */
  per_type?: PerTypeOverrides | null;
  /**
   * US-022 per-size demand：label → sizeKey → 数量（null → 后端 demand=1 向后兼容）。
   * 由调用方（NestingPage）经 serializeQuantities(qtyStore.quantities, sizes) 序列化。
   */
  quantities?: Record<string, Record<string, number>> | null;
}

/** 各类消息的可选回调（订阅层按需注册；不抛错，无返回）。 */
export interface UseSolveRunCallbacks {
  onManifest?: (m: ManifestMsg, run: RunRecord) => void;
  onFrame?: (f: FrameMsg, run: RunRecord) => void;
  onFinal?: (f: FinalMsg, run: RunRecord) => void;
  onError?: (e: ErrorMsg, run: RunRecord) => void;
  /** run 结束（final / error / onclose 任一）时调一次。 */
  onDone?: (run: RunRecord) => void;
}

/**
 * 单 run 求解 hook。
 * @returns start(cfg) 显式启动；stop() 对所有 open WS 发 {action:'stop'}；
 *          isStarted 反映是否已至少 start 过一次。
 */
export function useSolveRun(cb: UseSolveRunCallbacks = {}): {
  start: (cfg: StartConfig) => void;
  /** US-027：对所有 readyState===OPEN 的 run WS 发 {action:'stop'}（后端 terminate 后回 stopped）。 */
  stop: () => void;
  isStarted: boolean;
} {
  // 用 ref 持有最新回调，避免 callback 闭包陈旧，又不必让 start 重新创建。
  const cbRef = useRef(cb);
  cbRef.current = cb;

  const [isStarted, setStarted] = useState(false);

  const start = useCallback((cfg: StartConfig) => {
    // 1) Registry 创建 record
    const rec = runRegistry.create(cfg.seed);

    // 2) 显式 new WebSocket（不在 effect 里）
    const ws = new WebSocket(solveWsUrl());
    rec.ws = ws;

    // 3) onopen → 发 StartPayload
    const payload: StartPayload = {
      action: 'start',
      sizes: cfg.sizes,
      time: cfg.time,
      seed: cfg.seed,
      gate_mm: cfg.gate_mm,
      params: cfg.params,
      per_type: cfg.per_type ?? null,
      // US-022：quantities 缺省 → null（后端 build_instance 回退全片 demand=1）。
      quantities: cfg.quantities ?? null,
    };
    ws.onopen = () => {
      ws.send(JSON.stringify(payload));
    };

    // 4) onmessage → 按 type 分发
    ws.onmessage = (ev: MessageEvent) => {
      let msg: ServerMsg;
      try {
        msg = JSON.parse(typeof ev.data === 'string' ? ev.data : '') as ServerMsg;
      } catch {
        return; // 非 JSON / 解析失败 —— 静默丢弃
      }
      switch (msg.type) {
        case 'manifest':
          rec.manifest = msg;
          cbRef.current.onManifest?.(msg, rec);
          break;
        case 'frame':
          rec.frames.push(msg);
          rec.lastFrame = msg;
          if (msg.width_mm > rec.viewBoxMaxW) rec.viewBoxMaxW = msg.width_mm;
          cbRef.current.onFrame?.(msg, rec);
          break;
        case 'final':
          applyFinal(rec, msg);
          cbRef.current.onFinal?.(msg, rec);
          finish();
          break;
        case 'stopped':
          // US-027：后端 terminate 子进程后直发 stopped → 标记 rec.stopped + finish（触发 onDone）。
          // 不重算 finalDensity（无 final 消息）；lastFrame 保留停止时刻最新帧供导出中间方案。
          rec.stopped = true;
          finish();
          break;
        case 'error':
          rec.error = msg.message;
          cbRef.current.onError?.(msg, rec);
          finish();
          break;
        default:
          break;
      }
    };

    // 5) onclose / onerror → onDone（done flag 防重复触发；不重连）
    function finish() {
      if (rec.done) return;
      rec.done = true;
      cbRef.current.onDone?.(rec);
    }
    ws.onclose = () => finish();
    ws.onerror = () => {
      // 浏览器通常会在 onerror 后跟一个 onclose；这里不重复触发，留给 onclose 收尾。
    };

    setStarted(true);
  }, []);

  // US-027：stop() 遍历 registry，对每个 OPEN 的 WS 发 {action:'stop'}。
  // 后端收到后 terminate 子进程 → 直发 {type:'stopped'} → onmessage case 'stopped' → finish → onDone。
  // 对非 OPEN（connecting/closing/closed）的 WS 跳过（发也会 throw / 无意义）。
  const stop = useCallback(() => {
    for (const rec of runRegistry.list()) {
      const ws = rec.ws;
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ action: 'stop' }));
        } catch {
          // send 异常（连接刚关闭等）—— 忽略；onclose 兜底触发 finish。
        }
      }
    }
  }, []);

  return { start, stop, isStarted };
}
