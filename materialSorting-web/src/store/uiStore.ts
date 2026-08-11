// UiState —— 顶部 Tab 切换（US-001）+ 超排 Tab 解锁闸（US-015）。
//
// 持两个语义字段：
//   activeTab       'nesting'（超排页）/ 'preview'（上传预览页），默认 'preview'。
//                   业务流程先上传母版解析、再进超排，首页落在上传预览 Tab。
//   nestingEnabled  超排 Tab 是否可进入，默认 false。
//                   由 PreviewPage 联动 setNestingEnabled(true)（US-016）——
//                   用户上传解析成功后解锁；reset/error/重传重锁。
// 切页不卸载组件（display:none 由 App 的 .hidden class 控制），所以这里只关心
// 当前激活 Tab；求解 / WS / seek 等业务状态仍在各 page 内自行管理，互不干扰。
//
// 关键不变量（US-015 AC#4）：
//   setTab('nesting') 在 nestingEnabled===false 时**静默不切**——
//   store 层兜底，与 TabBar 的 native disabled + 运行时判 disabled 形成双重防御。
//   setTab('preview') 永远允许（用户随时可回上传预览页）。
//
// 设计与 appStore 一致：单字段 store，actions 直 set，避免 React 化复杂状态机。

import { create } from 'zustand';

export type TabId = 'nesting' | 'preview';

export interface UiState {
  /** 当前激活的 Tab，默认 'preview'（首页落上传预览）。 */
  activeTab: TabId;
  /** 超排 Tab 是否可进入；默认 false，由 PreviewPage 联动 setNestingEnabled（US-016）。 */
  nestingEnabled: boolean;
  /** 切换 Tab；nestingEnabled===false 时 setTab('nesting') 静默不切（关键不变量）。 */
  setTab: (tab: TabId) => void;
  /** 解锁/锁定超排 Tab；PreviewPage 监听 uploadStore.status 调用（US-016）。 */
  setNestingEnabled: (b: boolean) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  activeTab: 'preview',
  nestingEnabled: false,
  setTab: (tab) => {
    // 关键不变量：nestingEnabled===false 时 setTab('nesting') 静默不切（US-015）。
    // preview Tab 永远允许（用户随时可回上传预览页，不受解锁闸影响）。
    if (tab === 'nesting' && !get().nestingEnabled) return;
    set({ activeTab: tab });
  },
  setNestingEnabled: (b) => set({ nestingEnabled: b }),
}));
