// editHold.ts —— 编辑排料会话钉住心跳（2026-09-04）。
//
// 问题：编辑排料弹窗纯前端（拖动/旋转/保存全部只写内存 store，不发任何请求），
// 求解已结束、无轮询 —— 后端视角会话完全空闲。MS_SESSION_TTL_SEC（缺省 10min）
// 空闲过期会在长编辑（30min+）中途逐出会话 → 保存后导出 401 全局阻断弹窗 →
// 刷新丢全部编辑成果（编辑态不持久化）。
//
// 方案：弹窗打开期间滚动 POST /api/edit-hold（后端 edit_hold 钉住表
// hold_until = now + MS_EDIT_HOLD_SEC 缺省 2h，镜像高级运行终态宽限语义）。
// 任意 2h 窗内一次成功心跳即续命（容忍网络抖动/编辑中睡眠 ≤2h 唤醒恢复）；
// 关窗后自然留 2h 宽限（保存后挂机回来导出不丢）。
//
// 失败静默：会话真死（服务重启等）时 401 拦截已触发全局阻断弹窗（fail-fast
// 优于白编 30min）；网络抖动由滚动窗兜底。

import { apiFetch } from './api';

/** 心跳间隔：4min（钉住窗 2h 的 1/30 —— 单次/多次丢包零影响）。 */
export const EDIT_HOLD_INTERVAL_MS = 4 * 60 * 1000;

/** 续期编辑钉住（静默失败，详见文件头）。 */
export async function refreshEditHold(): Promise<void> {
  try {
    await apiFetch('/api/edit-hold', { method: 'POST' });
  } catch {
    // SessionBlockedError（阻断弹窗已弹，请求未发出）/ 网络错（滚动窗兜底）—— 均静默
  }
}
