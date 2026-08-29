// StrategyStore —— 策略运行（US-004 四路由 / US-005 弹窗）的前端状态中心。
// US-003（极限运行）起泛化为**族参数化工厂** createRunStore<P>(spec)：strategy /
// extreme 两族各自持一个 store 实例（useStrategyStore / useExtremeStore），端点与
// mode 采纳白名单由 spec 决定 —— 状态机 / 代际号 / result 恰一次拉取等逻辑单一
// 实现不复制。
//
// 状态机（phase 与 status.state 字符串一一对应，两族同构）：
//   idle ──start──▶ starting ──run_dir 发现──▶ running ──▶ done | stopped | error
//   （server 重启后遗留 run：status 返回 orphan —— 清理动作 = stop 路由）
//
// 关键约定：
//   - status 无状态（后端每次现读 run_dir 产物）→ refresh 是唯一真相入口；
//     页面刷新 / 重开弹窗后一次 refresh 即恢复进度。
//   - **族过滤（US-003）**：后端两族共用每会话状态槽 —— 对方族的 run 经本族
//     status 端点同样可见（mode 透传对方值）。refresh 只采纳本族 mode 的 status
//     （idle 恒采纳 —— 槽空是恢复出口，见 spec.ownsMode）；对方 run 不进本族
//     phase ⇒ 本族入口徽标不误亮、弹窗停留配置态，用户发起时由后端 409 互斥
//     文案区分对方（「已有进行中的极限运行/策略运行…请先停止/清理」）。
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
import { apiFetch } from '../lib/api';
import type {
  StrategyPhase,
  StrategyResult,
  StrategyStartPayload,
  StrategyStatus,
} from '../types/strategy';
import type { ExtremeStartPayload } from '../types/strategy';

/**
 * 族规格：端点前缀 + status.mode 采纳白名单 + start 网络错文案。
 * 极限 mode 白名单只认 'extreme'（旧无 mode 的 marker/mark 是策略族存量）。
 */
interface RunFamilySpec {
  /** 四路由前缀（'/api/strategy' | '/api/extreme'）。 */
  base: string;
  /** status.mode 归属判定（idle 态恒采纳，不进本函数）。 */
  ownsMode: (mode: unknown) => boolean;
  netError: string;
}

const STRATEGY_SPEC: RunFamilySpec = {
  base: '/api/strategy',
  ownsMode: (m) => m === undefined || m === null || m === 'se' || m === 'race',
  netError: '网络错误：无法启动策略运行',
};

const EXTREME_SPEC: RunFamilySpec = {
  base: '/api/extreme',
  ownsMode: (m) => m === 'extreme',
  netError: '网络错误：无法启动极限运行',
};

/** 状态形状（P = 本族 start 载荷；两族仅载荷类型不同，字段同构）。 */
export interface RunState<P> {
  /** 状态机七态（idle 默认）。 */
  phase: StrategyPhase;
  /** 最近一次 status 响应（progress 态渲染数据源；idle 时 null）。 */
  status: StrategyStatus | null;
  /** done/stopped 后 result 端点响应（常驻到下一次 start/reset；US-006 应用数据源）。 */
  result: StrategyResult | null;
  /** start 被拒（400/409/422/网络错）时的本地错误文案（与 status.error 区分来源）。 */
  errorMessage: string | null;
  /** 上一次 start 载荷（error 态「重试」复用；idle 清空）。 */
  lastStart: P | null;
  /** POST <base>/start（202 → starting + 立即 refresh；被拒 → error）。 */
  start: (payload: P) => Promise<void>;
  /** POST <base>/stop（终止 active run / 清理 orphan marker）+ refresh。 */
  stop: () => Promise<void>;
  /** GET <base>/status（活性轮询唯一入口；done/stopped 顺手拉 result 一次）。 */
  refresh: () => Promise<void>;
  /** 全清回 idle（测试 / 用户显式重置用；正常流转不需要）。 */
  reset: () => void;
}

/** status.state 非法 / 缺失时不动 phase（mock fetch / 半截响应容错）。 */
function isStrategyState(v: unknown): v is StrategyPhase {
  return (
    v === 'idle' || v === 'starting' || v === 'running' ||
    v === 'done' || v === 'stopped' || v === 'error' || v === 'orphan'
  );
}

function createRunStore<P>(spec: RunFamilySpec) {
  return create<RunState<P>>((set, get) => {
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
      const r = await apiFetch(`${spec.base}/start`, {
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
      if (g === gen) set({ phase: 'error', errorMessage: spec.netError });
    }
  },

  stop: async () => {
    try {
      await apiFetch(`${spec.base}/stop`, { method: 'POST' });
    } catch {
      /* 网络错也继续 refresh（本地状态可能与后端不一致，以 refresh 收敛） */
    }
    await get().refresh();
  },

  refresh: async () => {
    const g = gen;
    try {
      const r = await apiFetch(`${spec.base}/status`);
      if (g !== gen) return; // 在飞期间 start/reset 已接管 → 丢弃过期响应
      if (!r.ok) return;
      const st = (await r.json()) as StrategyStatus | null;
      if (g !== gen) return;
      if (!st || !isStrategyState(st.state)) return;
      // 族过滤（US-003）：对方族 run（后端同槽可见）不进本族 phase；idle 恒采纳
      // （server 重启槽空后，stuck starting 态的唯一恢复出口）。
      if (st.state !== 'idle' && !spec.ownsMode(st.mode)) return;
      set({ status: st, phase: st.state });
      // done/stopped → 拉 result 一次（每 run 恰一次：result 非 null 跳过；
      // result 拉取失败保持 null，下一次 refresh 重试）。
      if ((st.state === 'done' || st.state === 'stopped') && get().result === null) {
        try {
          const rr = await apiFetch(`${spec.base}/result`);
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
}

/** 策略运行（高级运行）store —— /api/strategy/* 四路由。 */
export const useStrategyStore = createRunStore<StrategyStartPayload>(STRATEGY_SPEC);

/** 极限运行 store（US-003）—— /api/extreme/* 四路由（与策略同槽，族过滤见上）。 */
export const useExtremeStore = createRunStore<ExtremeStartPayload>(EXTREME_SPEC);
