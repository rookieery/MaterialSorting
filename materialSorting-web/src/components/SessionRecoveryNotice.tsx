// SessionRecoveryNotice —— 启动期会话恢复轻加载态（US-003）。
//
// 与 SessionExpiredModal（阻断式）相对：恢复是**预期内的短过渡**（<2s）——
// 非阻断（pointer-events:none，无遮罩无按钮），仅顶部居中一条状态告知，防
// 「刷新后白屏一瞬」的茫然。恢复落定（成功 toast / 兜底 toast / 阻断弹窗）
// 后 uiStore.sessionRecovering 复位，本组件自然消失。
//
// 订阅方式：uiStore.sessionRecovering（lib/sessionRecovery 起止置位）；空态
// 渲染 null（零开销）。z-index 1400 —— 低于 toast(1500)（恢复 toast 是恢复
// 流程的「结论」，结论落在告知之上）。
//
// 挂载：App 顶层单例（与 Toast / SessionExpiredModal 同模式）。

import type { JSX } from 'react';
import { useUiStore } from '../store/uiStore';

/** 恢复中轻加载态单例（未恢复时渲染 null）。 */
export function SessionRecoveryNotice(): JSX.Element | null {
  const recovering = useUiStore((s) => s.sessionRecovering);
  if (!recovering) return null;
  return (
    <div className="session-recovery-notice" role="status" aria-live="polite">
      正在恢复工作状态…
    </div>
  );
}
