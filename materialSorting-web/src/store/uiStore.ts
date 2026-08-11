// UiState —— 顶部 Tab 切换（US-001）。
//
// 仅持 activeTab 一个语义字段：'nesting'（超排页）/ 'preview'（上传预览页）。
// 默认 'preview'：业务流程先上传母版解析、再进超排，首页落在上传预览 Tab。
// 切页不卸载组件（display:none 由 App 的 .hidden class 控制），所以这里只关心
// 当前激活 Tab；求解 / WS / seek 等业务状态仍在各 page 内自行管理，互不干扰。
//
// 设计与 appStore 一致：单字段 store，actions 直 set，避免 React 化复杂状态机。

import { create } from 'zustand';

export type TabId = 'nesting' | 'preview';

export interface UiState {
  /** 当前激活的 Tab，默认 'preview'（首页落上传预览）。 */
  activeTab: TabId;
  /** 切换 Tab；与旧 vanilla 无对应，纯 US-001 新增。 */
  setTab: (tab: TabId) => void;
}

export const useUiStore = create<UiState>((set) => ({
  activeTab: 'preview',
  setTab: (tab) => set({ activeTab: tab }),
}));
