// sessionRecovery —— 会话过期启动期自动恢复（prd-session-expiry-auto-recovery
// US-003 前端侧）。
//
// 触发面：ensureSession once-probe 吃 401 ``session_expired``（= 页面加载/刷新时
// 旧会话已过期）。恢复**只**发生在启动期 —— 用户定案：停留期自动恢复 = 变相保
// 活会话、浪费资源；页面停留期间过期走 SessionExpiredModal 引导刷新（「刷新页面
// 后将恢复工作状态」），刷新动作本身才是恢复入口。
//
// 流程（recoverExpiredSession，经 registerStartupSessionRecovery 注入 api.ts 的
// 探测 401 分支；恢复全程在 once-promise 内 = 天然 single-flight，不发请求风暴）：
//   1. peekPersistedSessionId() 非铸造捕获旧 sid（直接调 getSessionId 会 lazy-mint
//      新 sid 丢旧值 —— 时序红线：先 peek 再 clear 再铸新）；
//   2. clearPersistedSessionId() + getSessionId() 铸新 sid（旧 sid 已入后端墓碑
//      1h 拒重建，重探必须换新）；
//   3. 裸 fetch POST /api/state-recover {from_sid}（X-Session-Id = 新 sid；绕
//      apiFetch 防递归 —— 探测先例）三分支：
//      - 200 → applyRestorePayload(res)（lib/stateFile 既有编排零改动：母版/
//        数量矩阵/布局回显 + 切超排 Tab）+ toast「工作状态已恢复」；
//      - 404（快照不在/已消费/超 TTL）/ 400 / 网络失败 → 静默兜底（新 sid 已就绪，
//        探测重试即建新会话）+ toast「上次会话已过期，已开启新会话」；
//      - 429（满员）→ triggerSessionBlock('session_limit') 既有阻断弹窗（文案
//        不变）；checkpoint 后端不删，名额腾出后用户刷新可再恢复。
//   4. 恢复期间 uiStore.sessionRecovering 置位 —— App 顶层 SessionRecoveryNotice
//      渲染「正在恢复工作状态…」轻加载态（非阻断；恢复 <2s 防空白闪屏）。
//
// 依赖方向：lib → store 是 stateFile.ts 既有先例（applyRestorePayload 直碰五
// store）；api.ts 经钩子槽保持 store 零依赖（依赖倒置，见 api.ts 文件头）。本
// 模块由 App.tsx 静态 import —— 模块求值序（注册）结构性先于任何 effect 发请求。

import {
  SESSION_HEADER,
  registerStartupSessionRecovery,
  triggerSessionBlock,
} from './api';
import {
  clearPersistedSessionId,
  getSessionId,
  peekPersistedSessionId,
} from './session';
import { applyRestorePayload } from './stateFile';
import { useToastStore } from '../store/toastStore';
import { useUiStore } from '../store/uiStore';
import type { StateRestoreResponse } from '../types/stateFile';

/** 恢复成功 toast（PRD US-003 指定文案；toastStore 同文案去重防叠条）。 */
export const TOAST_RECOVERED = '工作状态已恢复';
/** 无可恢复快照兜底 toast（PRD US-003 指定文案）。 */
export const TOAST_NEW_SESSION = '上次会话已过期，已开启新会话';

function pushToast(message: string): void {
  useToastStore.getState().pushToast(message);
}

/** 恢复流程内核（sessionRecovering 置位由外层 recoverExpiredSession 兜底复位）。 */
async function runRecovery(): Promise<void> {
  // 1) 非铸造捕获旧 sid → 清旧 → 铸新（时序红线：peek 必须先于 clear）。
  const oldSid = peekPersistedSessionId();
  clearPersistedSessionId();
  const newSid = getSessionId();

  useUiStore.getState().setSessionRecovering(true);
  let res: Response;
  try {
    // 2) 裸 fetch 恢复（绕 apiFetch 防递归；探测先例）。oldSid null（极端：
    // localStorage 不可用且缓存空）→ 空 from_sid → 后端 400 → 兜底分支。
    res = await fetch('/api/state-recover', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', [SESSION_HEADER]: newSid },
      body: JSON.stringify(oldSid ? { from_sid: oldSid } : {}),
    });
  } catch {
    // 网络失败 —— 新会话已就绪（探测重试建会话），静默兜底。
    pushToast(TOAST_NEW_SESSION);
    return;
  }

  if (res.status === 429) {
    // 满员：新会话不可建 → 既有阻断弹窗（session_limit 文案不变）。
    triggerSessionBlock('session_limit');
    return;
  }

  if (res.ok) {
    let data: unknown = null;
    try {
      data = await res.json();
    } catch {
      data = null; // 坏 JSON —— 落兜底分支
    }
    if (data && typeof data === 'object') {
      // 3) 恢复编排单一实现复用（母版/数量矩阵/布局回显 + 切超排 Tab）。
      applyRestorePayload(data as StateRestoreResponse);
      pushToast(TOAST_RECOVERED);
      return;
    }
  }

  // 404 快照不在 / 400 坏载荷 —— 静默兜底新会话。
  pushToast(TOAST_NEW_SESSION);
}

/**
 * 启动期恢复入口（api.ts 探测 401 分支调用；**永不 reject** —— 防御兜底 toast，
 * 探测 promise 语义 = 永不 reject；finally 保证 sessionRecovering 起止恒成对）。
 */
export async function recoverExpiredSession(): Promise<void> {
  try {
    await runRecovery();
  } catch {
    // 编排内部异常（applyRestorePayload 理论不抛）—— 兜底告知，不阻断探测。
    pushToast(TOAST_NEW_SESSION);
  } finally {
    useUiStore.getState().setSessionRecovering(false);
  }
}

// 模块装载即注册（App.tsx 静态 import 本模块；见文件头「依赖方向」）。
registerStartupSessionRecovery(recoverExpiredSession);
