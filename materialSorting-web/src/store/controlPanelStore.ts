// ControlPanelState —— 高级配置弹窗 + 片型放大预览的显隐状态（US-018）。
//
// 两个独立显隐字段，对应两层模态：
//   modal         'per_type' | null  —— 高级配置：每片型覆盖表格弹窗
//   previewPtype  ptype(如 '前片') | null —— 片型放大预览（点击弹窗表头缩略图触发）
//
// 两层模态可同时存在（previewPtype 叠在 modal 之上，z-index 更高）；
// 关闭 previewPtype 时 modal 草稿保留（关自身不关底层）。
//
// 与 uiStore.nestingEnabled / uploadStore.qtyDialog 同设计：声明式受控 Portal
// 订阅本 store 自显隐；PerTypeOverrides 按钮 / PerTypeOverridesModal 表头缩略图 /
// PtypePreviewModal ✕ / 遮罩 / ESC 是统一入口，调用本 store action。
//
// 关键约定（AC#10）：两层 modal 各自独立 ESC —— ESC 时若 previewPtype !== null
// 仅关 previewPtype；否则关 modal。由各 modal 的 keydown listener 互查 state 实现
// （PerTypeOverridesModal listener 内判 previewPtype===null 才关，避免双层关闭）。

import { create } from 'zustand';

/** 当前激活的模态（仅 'per_type' 一种；预留扩展用联合类型）。 */
export type ControlPanelModalId = 'per_type';

export interface ControlPanelState {
  /** 高级配置弹窗显隐；null = 关闭。 */
  modal: ControlPanelModalId | null;
  /** 片型放大预览目标（ptype 名）；null = 关闭。 */
  previewPtype: string | null;
  /** 打开高级配置弹窗。 */
  openModal: (id: ControlPanelModalId) => void;
  /** 关闭高级配置弹窗（保留 previewPtype 状态不变）。 */
  closeModal: () => void;
  /** 打开片型放大预览。 */
  openPreviewPtype: (ptype: string) => void;
  /** 关闭片型放大预览（不影响 modal 显隐）。 */
  closePreviewPtype: () => void;
}

export const useControlPanelStore = create<ControlPanelState>((set) => ({
  modal: null,
  previewPtype: null,
  openModal: (id) => set({ modal: id }),
  closeModal: () => set({ modal: null }),
  openPreviewPtype: (ptype) => set({ previewPtype: ptype }),
  closePreviewPtype: () => set({ previewPtype: null }),
}));
