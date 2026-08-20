// ControlPanelState —— 高级配置弹窗 + 裁片放大预览的显隐状态（US-018；裁片编号化重构
// US-003 起预览目标字段改名 previewLabel，键 = 裁片 g 码）。
//
// 两个独立显隐字段，对应两层模态：
//   modal         'per_type' | 'strategy_run' | null —— 高级配置弹窗 / 高级运行弹窗
//   previewLabel  label(如 'g03') | null —— 裁片放大预览（点击弹窗表头缩略图触发）
//
// 两层模态可同时存在（previewLabel 叠在 modal 之上，z-index 更高）；
// 关闭 previewLabel 时 modal 草稿保留（关自身不关底层）。
//
// 与 uiStore.nestingEnabled / uploadStore.zoom 同设计：声明式受控 Portal
// 订阅本 store 自显隐；PerTypeOverrides 按钮 / PerTypeOverridesModal 表头缩略图 /
// PtypePreviewModal ✕ / 遮罩 / ESC 是统一入口，调用本 store action。
//
// 关键约定（AC#10）：两层 modal 各自独立 ESC —— ESC 时若 previewLabel !== null
// 仅关 previewLabel；否则关 modal。由各 modal 的 keydown listener 互查 state 实现
// （PerTypeOverridesModal listener 内判 previewLabel===null 才关，避免双层关闭）。

import { create } from 'zustand';

/** 当前激活的模态（US-005 起 'per_type' | 'strategy_run'；预留扩展用联合类型）。 */
export type ControlPanelModalId = 'per_type' | 'strategy_run';

export interface ControlPanelState {
  /** 高级配置弹窗显隐；null = 关闭。 */
  modal: ControlPanelModalId | null;
  /** 裁片放大预览目标（g 码 label）；null = 关闭。 */
  previewLabel: string | null;
  /** 打开高级配置弹窗。 */
  openModal: (id: ControlPanelModalId) => void;
  /** 关闭高级配置弹窗（保留 previewLabel 状态不变）。 */
  closeModal: () => void;
  /** 打开裁片放大预览。 */
  openPreviewLabel: (label: string) => void;
  /** 关闭裁片放大预览（不影响 modal 显隐）。 */
  closePreviewLabel: () => void;
}

export const useControlPanelStore = create<ControlPanelState>((set) => ({
  modal: null,
  previewLabel: null,
  openModal: (id) => set({ modal: id }),
  closeModal: () => set({ modal: null }),
  openPreviewLabel: (label) => set({ previewLabel: label }),
  closePreviewLabel: () => set({ previewLabel: null }),
}));
