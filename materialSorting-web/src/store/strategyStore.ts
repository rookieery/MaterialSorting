// StrategyStore —— 策略运行（US-004 四路由 / US-005 弹窗）的前端状态中心。
//
// 状态机（phase 与 status.state 字符串一一对应）：
//   idle ──start──▶ starting ──run_dir 发现──▶ running ──▶ done | stopped | error
//   （server 重启后遗留 run：status 返回 orphan —— 清理动作 = stop 路由）
//
// 关键约定：
//   - status 无状态（后端每次现读 run_dir 产物）→ refresh 是唯一真相入口；
//     页面刷新 / 重开弹窗后一次 refresh 即恢复进度。
//   - done/stopped 时 refresh 顺手拉一次 result（result === null 才拉 —— 每 run
//     恰一次；start 覆写清 result）。
//   - 关弹窗**不**终止运行（关闭只调 controlPanelStore.closeModal）；终止/清理
//     唯一入口是显式 stop()（active 态树杀 / orphan 态清 marker + 杀 pid）。
//   - error 双来源：后端 status.error（子进程异常退出）与 start 被拒（409/422/400，
//     本地写 errorMessage）。start 被拒时无新 run —— phase 停留 error 展示 + 重试。
//   - result 常驻（done/stopped 后不清）：关弹窗再开仍可应用（US-006）；
//     下一次 start / reset 才清。
//   - fetch 失败静默保留上一状态（网络抖动不炸 UI；jsdom 无后端时同理安全）。

import { create } from 'zustand';
import type {
  StrategyPhase,
  StrategyResult,
  StrategyStartPayload,
  StrategyStatus,
} from '../types/strategy';

export interface StrategyState {
  /** 状态机七态（idle 默认）。 */
  phase: StrategyPhase;
  /** 最近一次 status 响应（progress 态渲染数据源；idle 时 null）。 */
  status: StrategyStatus | null;
  /** done/stopped 后 result 端点响应（常驻到下一次 start/reset；US-006 应用数据源）。 */
  result: StrategyResult | null;
  /** start 被拒（400/409/422/网络错）时的本地错误文案（与 status.error 区分来源）。 */
  errorMessage: string | null;
  /** 上一次 start 载荷（error 态「重试」复用；idle 清空）。 */
  lastStart: StrategyStartPayload | null;
  /** POST /api/strategy/start（202 → starting + 立即 refresh；被拒 → error）。 */
  start: (payload: StrategyStartPayload) => Promise<void>;
  /** POST /api/strategy/stop（终止 active run / 清理 orphan marker）+ refresh。 */
  stop: () => Promise<void>;
  /** GET /api/strategy/status（活性轮询唯一入口；done/stopped 顺手拉 result 一次）。 */
  refresh: () => Promise<void>;
  /** 全清回 idle（测试 / 用户显式重置用；正常流转不需要）。 */
  reset: () => void;
}

/** status.state 非法 / 缺失时不动 phase（mock fetch / 半截响应容错）。 */
function isStrategyState(v: unknown): v is StrategyPhase {
  return (
    v === 'idle' || v === 'starting' || v === 'running' || v === 'done' ||
    v === 'stopped' || v === 'error' || v === 'orphan'
  );
}

export const useStrategyStore = create<StrategyState>((set, get) => {
  // 请求代际号：start/reset 时 bump —— 在飞的 refresh 响应落地前若代际已变则丢弃
  // （否则「再次运行」reset 后，open 切换触发的在飞 refresh 携 done 态回写会把
  // 弹窗从配置态拽回结果态 —— reset 必须是终审）。
  let gen = 0;
  return {
  phase: 'idle',
  status: null,
  result: null,
  errorMessage: null,
  lastStart: null,

  start: async (payload) => {
    gen += 1;
    const g = gen;
    // 新 run：清上一 run 的 result / 错误（result 常驻仅到下一次 start）。
    set({ result: null, errorMessage: null, lastStart: payload });
    try {
      const r = await fetch('/api/strategy/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (g !== gen) return; // 等待期间 reset/新 start 已接管
      if (r.status === 202) {
        set({ phase: 'starting', status: null });
        await get().refresh();
        return;
      }
      let msg = `启动失败（HTTP ${r.status}）`;
      try {
        const data = (await r.json()) as { error?: string } | null;
        if (data && typeof data.error === 'string') msg = data.error;
      } catch {
        /* 非 JSON 错误体 → 保留 HTTP 状态文案 */
      }
      set({ phase: 'error', errorMessage: msg });
    } catch {
      if (g === gen) set({ phase: 'error', errorMessage: '网络错误：无法启动策略运行' });
    }
  },

  stop: async () => {
    try {
      await fetch('/api/strategy/stop', { method: 'POST' });
    } catch {
      /* 网络错也继续 refresh（本地状态可能与后端不一致，以 refresh 收敛） */
    }
    await get().refresh();
  },

  refresh: async () => {
    const g = gen;
    try {
      const r = await fetch('/api/strategy/status');
      if (g !== gen) return; // 在飞期间 start/reset 已接管 → 丢弃过期响应
      if (!r.ok) return;
      const st = (await r.json()) as StrategyStatus | null;
      if (g !== gen) return;
      if (!st || !isStrategyState(st.state)) return;
      set({ status: st, phase: st.state });
      // done/stopped → 拉 result 一次（每 run 恰一次：result 非 null 跳过；
      // result 拉取失败保持 null，下一次 refresh 重试）。
      if ((st.state === 'done' || st.state === 'stopped') && get().result === null) {
        try {
          const rr = await fetch('/api/strategy/result');
          if (g !== gen) return;
          if (rr.ok) {
            set({ result: (await rr.json()) as StrategyResult });
          }
        } catch {
          /* result 网络错 → 下一次 refresh 重试 */
        }
      }
    } catch {
      /* 网络抖动 → 保留上一状态 */
    }
  },

  reset: () => {
    gen += 1;
    set({ phase: 'idle', status: null, result: null, errorMessage: null, lastStart: null });
  },
  };
});
