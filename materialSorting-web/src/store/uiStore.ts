// UiState —— 顶部 Tab 切换（US-001）+ 超排 Tab 解锁闸（US-015）。
//
// 持三个语义字段：
//   activeTab       'nesting'（超排页）/ 'preview'（上传预览页），默认 'preview'。
//                   业务流程先上传母版解析、再进超排，首页落在上传预览 Tab。
//   nestingEnabled  超排 Tab 是否可进入，默认 false。
//                   由 PreviewPage 联动 setNestingEnabled(true)（US-016）——
//                   用户上传解析成功后解锁；reset/error/重传重锁。
//   sessionRecovering 会话过期自动恢复（US-003）启动期恢复进行中，默认 false。
//                   lib/sessionRecovery 恢复流程起止置位/复位 —— App 顶层
//                   SessionRecoveryNotice 订阅渲染「正在恢复工作状态…」轻加载
//                   态（非阻断 pointer-events:none，恢复 <2s 防空白闪屏）。
//   panelWidth     左侧面板宽度 px（2026-10-05 伸缩分隔条），默认 248、范围
//                   [200,300]，localStorage(ms_panel_w) 跨刷新记忆。两页
//                   （UploadPanel / ControlPanel）共享同值，PanelSplitter 拖写。
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

/** 左侧面板宽度可调范围与默认值（2026-10-05 面板伸缩分隔条）：
 *  上传预览 UploadPanel 与超排 ControlPanel 共用 `.panel` 布局，宽度统一由
 *  uiStore.panelWidth 单一真相源驱动（两页共享同值 —— 切 Tab 不跳变；渲染 =
 *  面板 aside inline width）。248 = 原 `.panel` 固定宽（style.css 时代历史值，
 *  保持默认不变首屏观感）；200/300 由用户需求定案（PanelSplitter 拖拽 clamp）。 */
export const PANEL_W_MIN = 200;
export const PANEL_W_MAX = 300;
export const PANEL_W_DEFAULT = 248;

/** localStorage 键：面板宽度跨刷新记忆（与 ms_sid / ms_export_table 同惯例）。 */
const PANEL_W_LS_KEY = 'ms_panel_w';

/** clamp 到 [MIN, MAX] 并取整（拖拽 delta 累计出小数时保持 px 整数；非有限数回默认）。 */
export function clampPanelWidth(n: number): number {
  if (!Number.isFinite(n)) return PANEL_W_DEFAULT;
  return Math.min(PANEL_W_MAX, Math.max(PANEL_W_MIN, Math.round(n)));
}

/** 启动期读 localStorage（脏值 / 越界 / 异常一律 clamp 或回默认；隐私模式安全）。 */
function loadPanelWidth(): number {
  try {
    const raw = localStorage.getItem(PANEL_W_LS_KEY);
    if (raw == null) return PANEL_W_DEFAULT;
    return clampPanelWidth(Number(raw));
  } catch {
    return PANEL_W_DEFAULT;
  }
}

export interface UiState {
  /** 当前激活的 Tab，默认 'preview'（首页落上传预览）。 */
  activeTab: TabId;
  /** 超排 Tab 是否可进入；默认 false，由 PreviewPage 联动 setNestingEnabled（US-016）。 */
  nestingEnabled: boolean;
  /** 启动期会话恢复进行中（US-003）；lib/sessionRecovery 起止置位/复位。 */
  sessionRecovering: boolean;
  /** 左侧面板宽度（px，两页共享；启动期 loadPanelWidth，双击分隔条重置回默认）。 */
  panelWidth: number;
  /** 切换 Tab；nestingEnabled===false 时 setTab('nesting') 静默不切（关键不变量）。 */
  setTab: (tab: TabId) => void;
  /** 解锁/锁定超排 Tab；PreviewPage 监听 uploadStore.status 调用（US-016）。 */
  setNestingEnabled: (b: boolean) => void;
  /** 启动期恢复轻加载态起止（US-003）；SessionRecoveryNotice 订阅渲染。 */
  setSessionRecovering: (b: boolean) => void;
  /** 设面板宽度（clamp 后 set；拖拽高频路径，不写 localStorage）。 */
  setPanelWidth: (n: number) => void;
  /** 面板宽度落 localStorage（拖拽 pointerup / 重置时调一次，高频路径不碰 IO）。 */
  persistPanelWidth: () => void;
  /** 双击分隔条重置默认宽（VS Code sash 同款行为）。 */
  resetPanelWidth: () => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  activeTab: 'preview',
  nestingEnabled: false,
  sessionRecovering: false,
  panelWidth: loadPanelWidth(),
  setTab: (tab) => {
    // 关键不变量：nestingEnabled===false 时 setTab('nesting') 静默不切（US-015）。
    // preview Tab 永远允许（用户随时可回上传预览页，不受解锁闸影响）。
    if (tab === 'nesting' && !get().nestingEnabled) return;
    set({ activeTab: tab });
  },
  setNestingEnabled: (b) => set({ nestingEnabled: b }),
  setSessionRecovering: (b) => set({ sessionRecovering: b }),
  setPanelWidth: (n) => set({ panelWidth: clampPanelWidth(n) }),
  persistPanelWidth: () => {
    try {
      localStorage.setItem(PANEL_W_LS_KEY, String(get().panelWidth));
    } catch {
      /* 隐私模式 / 存储禁用写失败不打扰 */
    }
  },
  resetPanelWidth: () => {
    set({ panelWidth: PANEL_W_DEFAULT });
    get().persistPanelWidth();
  },
}));
