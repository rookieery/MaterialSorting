// sessionCheckpoint —— 工作台状态自动 checkpoint 调度 + 启动清理（会话过期自动
// 恢复 US-004 前端侧）。
//
// 价值：会话过期后的「快照新鲜度」取决于最后一次 checkpoint —— 自动调度让用户
// 无需手动「保存当前方案」，过期时刻快照足够新（丢失窗口 ≤ 3s 去抖；求解完成 /
// 编辑保存等价值最高时刻立即落，不等去抖）。
//
// 触发面（模块装载即接线，App.tsx 静态 import —— sessionRecovery 同款先例）：
//   1. formStore / qtyStore 变更订阅 → 去抖 CHECKPOINT_DEBOUNCE_MS（默认 3s，
//      2026-09-13 定案暂定；常量可调）—— 数量矩阵/表单是纯前端状态（不发请求），
//      自动 checkpoint 是它们唯一的服务端投影时机；
//   2. runRegistry bestRun 达 done（markRunDone 观察者）→ 立即 flush（求解完成
//      = 价值最高时刻，不等去抖；非 best 的晚到 run 跳过 —— 内容与上次快照一致）；
//   3. editStore.save 落定（savedDirty false→true 且 working 引用未换 = save 专属
//      写序，open 重开不误触）→ 立即 flush；
//   4. visibilitychange → hidden 立即 flush 并清空去抖（切 Tab / 最小化 = 用户
//      可能一去不回，快照尽量新）；
//   5. pagehide → best-effort keepalive fetch（卸载后请求仍送达；不等 sendChain
//      串行 —— 微任务在卸载期不可靠，直接同步发起）。
//
// 发送统一：POST /api/state-checkpoint，body = buildSavePayload()（不带 save_as，
// lib/stateFile 单一实现）。**一律走 apiFetch**（统一出口：sid 注入 + 阻断拦截）；
// 端点本身 peek 口径（US-001 后端保证：不刷 last_active、不建会话名额）—— 自动
// 调度不构成会话保活，过期时序不受影响。
//
// 静默容忍（后台任务不打扰用户）：
//   - 未 commit（uploadStore.doc 为空）→ 调度静默跳过（后端 200 empty 容忍，
//     前端更直接不发）；
//   - 停留期过期 401 → apiFetch 照常触发阻断弹窗（用户刚改过东西 = 在场），
//     本调度 catch 吞 SessionBlockedError / 网络错，**不重试**（下次变更自然再排，
//     无重试风暴）；
//   - 200 {stored:false, reason:empty|conservation} → 后端语义（会话空 / 守恒
//     fail-fast + last-good），前端零处理。
//
// 发送串行 + 合并：sendChain promise 链保证 POST 依序完成（防慢 POST1 先发后到
// 覆盖新 POST2 的乱序回写）；载荷在**发送时刻**经 buildSavePayload 现取（非入队
// 时刻）—— 已有一枚排队中 send 时新 flush 直接跳过（合并语义：排队的 send 开跑
// 时自然带上最新状态）。
//
// 启动清理（clearCheckpointAfterProbe，App 挂载 probeSession().then 消费）：
// F5 = 干净重置 —— 会话存活的刷新把旧 checkpoint DELETE 掉，防「稍后再过期恢复
// 出 F5 前旧状态」幽灵回潮；探测 401（wasStartupProbeExpired）则**不清**（快照留
// 给启动期恢复消费，恢复成功时后端 single-use 已删；恢复兜底新会话时残留在后端
// TTL（MS_CHECKPOINT_TTL_SEC 缺省 7200s）自然过期）；阻断（429 满员）也不清
// （名额腾出后用户刷新可再恢复，
// US-002 语义）。与 pagehide keepalive POST 的理论乱序竞态（POST 晚于 DELETE 落
// 地）接受为 best-effort：同源 LAN 下 keepalive 请求先于下一页探测完成。
//
// 依赖方向：lib → store（stateFile/sessionRecovery 既有先例）；App.tsx 静态
// import 完成接线（模块求值序结构性先于任何 effect）。

import { apiFetch, getSessionBlock, wasStartupProbeExpired } from './api';
import { buildSavePayload } from './stateFile';
import { useEditStore } from '../store/editStore';
import { useFormStore } from '../store/formStore';
import { useQtyStore } from '../store/qtyStore';
import { runRegistry, subscribeRunDone } from '../store/runRegistry';
import { useUploadStore } from '../store/uploadStore';

/** 去抖窗口（ms，2026-09-13 定案暂定 3s；常量可调）。 */
export const CHECKPOINT_DEBOUNCE_MS = 3000;

/** 去抖定时器（null = 无待发调度）。 */
let debounceTimer: ReturnType<typeof setTimeout> | null = null;
/** 发送串行链（POST 依序完成；初值已落定空 promise）。 */
let sendChain: Promise<void> = Promise.resolve();
/** 已有一枚 send 排队未开跑（flush 合并口径：载荷发送时刻现取，跳过重复入队）。 */
let sendQueued = false;

/** 有无可 checkpoint 的工作台（未 commit 无 doc → 调度静默跳过）。 */
function hasWorkbenchDoc(): boolean {
  return useUploadStore.getState().doc !== null;
}

/** 实际发送一枚 checkpoint（载荷此刻现取；全部异常静默吞 —— 不重试不弹错）。 */
async function sendCheckpoint(): Promise<void> {
  if (!hasWorkbenchDoc()) return;
  try {
    await apiFetch('/api/state-checkpoint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildSavePayload()),
    });
    // 200 stored:true/false（empty/conservation 后端语义）与非 2xx 均容忍 —— 零处理。
  } catch {
    // SessionBlockedError（阻断弹窗已由 apiFetch 触发）/ 网络错 —— 静默。
  }
}

/**
 * 立即落一枚 checkpoint：清去抖 + 入串行链（排队中则合并跳过）。触发面 =
 * 求解完成 / 编辑保存 / hidden 可见性 / 去抖到期。
 */
function flushCheckpoint(): Promise<void> {
  if (debounceTimer !== null) {
    clearTimeout(debounceTimer);
    debounceTimer = null;
  }
  if (!hasWorkbenchDoc()) return sendChain;
  if (sendQueued) return sendChain;
  sendQueued = true;
  sendChain = sendChain.then(() => {
    sendQueued = false;
    return sendCheckpoint();
  });
  return sendChain;
}

/** 排一次去抖调度（formStore/qtyStore 变更消费；窗口内重复变更合并为一发）。 */
function scheduleCheckpoint(): void {
  if (debounceTimer !== null) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    debounceTimer = null;
    void flushCheckpoint();
  }, CHECKPOINT_DEBOUNCE_MS);
}

/**
 * pagehide best-effort：keepalive fetch 同步发起（不走 sendChain —— 卸载期微任务
 * 不可靠；与在途 POST 的乱序竞态接受为 best-effort，见文件头）。
 */
function sendCheckpointKeepalive(): void {
  if (!hasWorkbenchDoc()) return;
  if (debounceTimer !== null) {
    clearTimeout(debounceTimer);
    debounceTimer = null;
  }
  if (getSessionBlock()) return;
  try {
    void apiFetch('/api/state-checkpoint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildSavePayload()),
      keepalive: true,
    }).catch(() => {
      // 卸载期异常 —— 静默。
    });
  } catch {
    // 同步异常（理论上不至）—— 静默。
  }
}

/**
 * 启动清理（App 挂载 probeSession 落定后消费）：会话存活 → DELETE 旧 checkpoint
 * （F5 = 干净重置）；探测 401 / 已阻断 → 不清（见文件头「启动清理」）。
 */
export async function clearCheckpointAfterProbe(): Promise<void> {
  if (getSessionBlock()) return;
  if (wasStartupProbeExpired()) return;
  try {
    await apiFetch('/api/state-checkpoint', { method: 'DELETE' });
  } catch {
    // SessionBlockedError / 网络错 —— 静默（清理是幂等 best-effort）。
  }
}

// ---------------------------------------------------------------- 装载接线（单例）

/** 接线守卫（模块求值一次；测试重复 import 天然幂等）。 */
let wired = false;

function wireSessionCheckpoint(): void {
  if (wired) return;
  wired = true;

  // 1) formStore / qtyStore 变更 → 去抖（引用比较：hydrate/patch/setPiece 均建新对象）。
  useFormStore.subscribe((state, prev) => {
    if (state.form !== prev.form) scheduleCheckpoint();
  });
  useQtyStore.subscribe((state, prev) => {
    if (state.quantities !== prev.quantities) scheduleCheckpoint();
  });

  // 2) run 达 done 且为 bestRun → 立即（价值最高时刻，不等去抖）。
  subscribeRunDone((run) => {
    if (!run.lastFrame) return; // error/onclose 无帧 —— 无新价值
    if (runRegistry.bestRun() !== run) return; // 非 best 的晚到 run —— 内容无增量
    void flushCheckpoint();
  });

  // 3) editStore.save 落定 → 立即。save 专属写序识别：savedDirty false→true 且
  //    working 引用未换（save 只 set savedDirty；open 必换 working 新数组 —— 重开
  //    已保存 run 不误触）。
  useEditStore.subscribe((state, prev) => {
    if (!prev.savedDirty && state.savedDirty && prev.working === state.working) {
      void flushCheckpoint();
    }
  });

  // 4) 切后台/最小化 → 立即 flush 清空去抖。
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void flushCheckpoint();
  });

  // 5) 卸载/导航 → best-effort keepalive。
  window.addEventListener('pagehide', sendCheckpointKeepalive);
}

wireSessionCheckpoint();

// ---------------------------------------------------------------- 测试隔离

/** 测试隔离：清去抖定时器 + 复位串行链（监听器为模块单例保留 —— 与生产同构）。 */
export function resetCheckpointForTest(): void {
  if (debounceTimer !== null) {
    clearTimeout(debounceTimer);
    debounceTimer = null;
  }
  sendChain = Promise.resolve();
  sendQueued = false;
}
