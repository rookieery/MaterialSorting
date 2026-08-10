// UploadState —— DXF 上传预览页的状态中心（US-005）。
//
// 状态机：idle → uploading → done | error（任一终态可 reset 回 idle）。
// doc / activeSize / error 全部进 React state（与 runRegistry 那种高频 mutable 不同 ——
// 解析结果低频，进 store 触发 reconciliation 反而便于 UI 同步）。
//
// 字段口径：
//   status     'idle'（默认） / 'uploading'（fetch 进行中） / 'done'（200，doc 已写入） /
//              'error'（网络错或非 200，error 字段填中文消息）
//   doc        最近一次成功解析的响应（done 时才有效；其它状态保留旧值或 null ——
//              由 reset 清零，hook 内不主动清，避免切 uploading 时 UI 闪烁）
//   activeSize 当前选中的码号（number | null）；done 时默认 = sizes[0]?.size ?? null
//              （后端按数值升序、null 殿后，故 sizes[0] 是最小码）
//   error      error 状态下的中文消息（HTTP 400/413/422 / 网络错）
//   qtyDialog  数量编辑弹窗的目标（label + size）；null 表示弹窗关闭。
//              US-012 PieceQtyDialog 订阅此字段自显隐；openQtyDialog/closeQtyDialog
//              是 ParsedPiecesView 卡片头点击 / 取消 / 遮罩 / ESC 的统一入口。
//   zoom      放大预览模态的目标（label + size）；null 表示模态关闭。
//             US-013 PieceZoomModal 订阅此字段自显隐（声明式受控 Portal，
//             区别于排料页 Tooltip 的命令式单例）；openZoom/closeZoom 是
//             ParsedPiecesView 卡片图形区点击 / ✕ / 遮罩 / ESC 的统一入口。
//
// actions：
//   reset()              回到 idle，清空 doc / activeSize / error / qtyDialog / zoom ——
//                         用户主动重传时调（重传成功后 US-014 集成 qtyStore.resetQuantities）
//   setSize(s)           切 activeSize（SizeTabs 点击时调；s = number | null）
//   openQtyDialog(l, s)  打开数量编辑弹窗（点卡片头 数量(片) button 时调）
//   closeQtyDialog()     关闭数量编辑弹窗（取消 / 遮罩 / ESC / 确定后调）
//   openZoom(l, s)       打开放大预览模态（点卡片图形区 body 时调）
//   closeZoom()          关闭放大预览模态（✕ / 遮罩 / ESC 时调）
//
// hook 内部的状态过渡（uploading → done | error）由 useParseDxf 直接
// `useUploadStore.setState({...})` 写入，不暴露成 store 公开 action，避免业务组件
// 误触发状态跳变。store 公开 API 只含调用方语义动作（reset / setSize /
// openQtyDialog / closeQtyDialog / openZoom / closeZoom）。

import { create } from 'zustand';
import type { ParsedDoc } from '../types/parsed';

export type UploadStatus = 'idle' | 'uploading' | 'done' | 'error';

/** 数量编辑弹窗目标（label + size；US-012 PieceQtyDialog 订阅此字段自显隐）。 */
export interface QtyDialogTarget {
  /** 弹窗编辑的片型 label（A/B/C...，跨码匹配同一片型）。 */
  label: string;
  /** 弹窗编辑的码号（SizeTabs 当前 activeSize；null = 通用码）。 */
  size: number | null;
}

/** 放大预览模态目标（label + size；US-013 PieceZoomModal 订阅此字段自显隐）。 */
export interface ZoomTarget {
  /** 模态预览的片型 label（A/B/C...，跨码匹配同一片型）。 */
  label: string;
  /** 模态预览的码号（点击卡片所属 activeSize；null = 通用码）。 */
  size: number | null;
}

export interface UploadState {
  /** 当前状态机位置。 */
  status: UploadStatus;
  /** 最近一次成功解析的响应（done 时才有效；其它状态保留旧值或 null）。 */
  doc: ParsedDoc | null;
  /** 当前查看的码号；done 时默认 = sizes[0]?.size ?? null，setSize 切换。 */
  activeSize: number | null;
  /** error 状态下的中文消息（后端 JSONResponse.error 或网络错 message）。 */
  error: string | null;
  /** 数量编辑弹窗目标（label + size）；null 表示弹窗关闭。 */
  qtyDialog: QtyDialogTarget | null;
  /** 放大预览模态目标（label + size）；null 表示模态关闭。 */
  zoom: ZoomTarget | null;
  /** 重置到 idle，清空 doc / activeSize / error / qtyDialog / zoom。 */
  reset: () => void;
  /** 切换当前查看的码号（SizeTabs 调用）。 */
  setSize: (size: number | null) => void;
  /** 打开数量编辑弹窗（点卡片头 数量(片) button 时调）。 */
  openQtyDialog: (label: string, size: number | null) => void;
  /** 关闭数量编辑弹窗（取消 / 遮罩 / ESC / 确定后调）。 */
  closeQtyDialog: () => void;
  /** 打开放大预览模态（点卡片图形区 body 时调）。 */
  openZoom: (label: string, size: number | null) => void;
  /** 关闭放大预览模态（✕ / 遮罩 / ESC 时调）。 */
  closeZoom: () => void;
}

export const useUploadStore = create<UploadState>((set) => ({
  status: 'idle',
  doc: null,
  activeSize: null,
  error: null,
  qtyDialog: null,
  zoom: null,
  reset: () =>
    set({ status: 'idle', doc: null, activeSize: null, error: null, qtyDialog: null, zoom: null }),
  setSize: (size) => set({ activeSize: size }),
  openQtyDialog: (label, size) => set({ qtyDialog: { label, size } }),
  closeQtyDialog: () => set({ qtyDialog: null }),
  openZoom: (label, size) => set({ zoom: { label, size } }),
  closeZoom: () => set({ zoom: null }),
}));
