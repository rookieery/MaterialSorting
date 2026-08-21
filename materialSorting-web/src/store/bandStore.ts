// BandState —— 腰头成带选择的跨页共享镜像（US-013）。
//
// 单一真相源仍是 ControlPanel 的 ``form.band_enabled/band_label``（collectStartContext
// 从 form 解析 WS band 载荷）；本 store 是 form → 上传预览页 QtyMatrix 的**单向镜像**
// （ControlPanel 在 form.band_* 变化时 useEffect 同步 setBand），供「该码不成对」
// 奇数数量警告跨页可见 —— QtyMatrix 与 ControlPanel 分属两个 Tab，props 无通路。
//
// 与 controlPanelStore（弹窗显隐）/ qtyStore（数量）同设计：纯 Zustand、不依赖 React。

import { create } from 'zustand';

export interface BandState {
  /** 腰头成带开关镜像（= form.band_enabled）。 */
  enabled: boolean;
  /** 腰头 g 码镜像（= form.band_label；'' = 未选）。 */
  label: string;
  /** ControlPanel 同步入口（form.band_* → store 单向镜像）。 */
  setBand: (enabled: boolean, label: string) => void;
}

export const useBandStore = create<BandState>((set) => ({
  enabled: false,
  label: '',
  setBand: (enabled, label) => set({ enabled, label }),
}));
