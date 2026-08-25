// PtypeState —— /api/ptypes 代表裁片的会话级缓存（2026-08-25 引入）。
//
// 背景：representatives（键 = 裁片 g 码，值 = 5 层几何代表裁片）在后端属于
// `_PIECES_STATE`，**只在 /api/commit-to-nesting（上传母版 commit）时变化**，
// 之后完全静态。旧实现 PerTypeOverridesModal / PtypePreviewModal 各自「每次挂载
// 都 fetch」—— 每次打开高级配置弹窗全部缩略图闪「…」占位、数百 KB 几何 JSON
// 反复传输 + 解析 + PiecePreviewSVG 重算，纯浪费。
//
// 但「每次都拉」不是无脑设计：2026-08-17 修过「应用加载时 fetch 一次」的永久
// 缓存 bug（重传母版后两弹窗缩略图新旧不一致）。问题不在缓存而在**没有失效
// 机制** —— 故本 store 的失效挂点是 commit done（useCommitToNesting 成功分支，
// 后端 state 唯一变化点），语义精确到「数据真正会变的时刻」。
//
// 状态机：
//   idle     初始 / 已失效（invalidate 后）—— ensureLoaded 会发起 fetch
//   loading  fetch 进行中（防重入：StrictMode 双 mount / 两弹窗同时打开只发一次）
//   ready    缓存就绪 —— ensureLoaded 直接跳过（开关弹窗零请求零闪烁）
//   error    fetch 失败 —— **effect 不自动重试**（防失败→重试死循环）；重新打开
//            弹窗（组件 mount effect）或 invalidate（commit done）即重试
//
// representatives 在 loading / error / invalidate 期间**保留旧值不清空**：
//   - loading 保留 → 开弹窗不闪占位（旧图平滑过渡到新图）；
//   - error 保留 → 后端临时不可用时弹窗仍显示上次缓存图（降级优于空白）；
//   - invalidate 保留 → commit 完成瞬间弹窗若开着，缩略图无感更新。
//
// 消费方（两弹窗共享同一份缓存 —— 数据一致性比旧「各自每次拉」更强）：
//   - PerTypeOverridesModal（高级配置：裁片设置表头缩略图）
//   - PtypePreviewModal（裁片放大预览）
// 加载触发约定（防 error 死循环）：组件 mount effect 无条件 ensureLoaded
// （ready/loading 内部跳过，error 态重开弹窗即重试）；status 订阅 effect 仅在
// === 'idle' 时 ensureLoaded —— 覆盖「弹窗开着时 commit done invalidate」的
// 无感刷新路径。

import { create } from 'zustand';
import type { PtypeRepresentative, PtypesResponse } from '../types/ptype';

/** /api/ptypes 端点（dev 由 Vite proxy 转 :8000；prod 同源）。 */
const PTYPES_URL = '/api/ptypes';

export type PtypeCacheStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface PtypeState {
  /** 代表裁片缓存（键 = g 码）；loading/error/idle 期间保留旧值（见文件头）。 */
  representatives: Record<string, PtypeRepresentative>;
  /** 缓存状态机位置（见文件头）。 */
  status: PtypeCacheStatus;
  /** 幂等加载：ready/loading 跳过；idle/error 发起 fetch。 */
  ensureLoaded: () => void;
  /** 失效（commit done 挂点）：置回 idle，representatives 保留（无感刷新）。 */
  invalidate: () => void;
  /** 全量重置（测试隔离用：跨用例清缓存，防 mock 数据串台）。 */
  reset: () => void;
}

export const usePtypeStore = create<PtypeState>((set, get) => ({
  representatives: {},
  status: 'idle',
  ensureLoaded: () => {
    const { status } = get();
    if (status === 'ready' || status === 'loading') return;
    set({ status: 'loading' });
    fetch(PTYPES_URL)
      .then((r) => r.json() as Promise<PtypesResponse>)
      .then((data) => {
        set({ representatives: data.representatives ?? {}, status: 'ready' });
      })
      .catch(() => {
        // 失败保留旧 representatives（降级显示），status 置 error —— 不自动重试
        //（防失败循环；重开弹窗 / 下次 commit invalidate 即重试）。
        set({ status: 'error' });
      });
  },
  invalidate: () => {
    // 仅 ready/error → idle 才触发订阅方 effect（同态 set 不产生通知）。
    if (get().status !== 'idle') set({ status: 'idle' });
  },
  reset: () => set({ representatives: {}, status: 'idle' }),
}));
