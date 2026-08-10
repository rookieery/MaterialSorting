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
//
// actions：
//   reset()    回到 idle，清空 doc / activeSize / error —— 用户主动重传时调
//   setSize(s) 切 activeSize（SizeTabs 点击时调；s = number | null）
//
// hook 内部的状态过渡（uploading → done | error）由 useParseDxf 直接
// `useUploadStore.setState({...})` 写入，不暴露成 store 公开 action，避免业务组件
// 误触发状态跳变。store 公开 API 只含调用方语义动作（reset / setSize）。

import { create } from 'zustand';
import type { ParsedDoc } from '../types/parsed';

export type UploadStatus = 'idle' | 'uploading' | 'done' | 'error';

export interface UploadState {
  /** 当前状态机位置。 */
  status: UploadStatus;
  /** 最近一次成功解析的响应（done 时才有效；其它状态保留旧值或 null）。 */
  doc: ParsedDoc | null;
  /** 当前查看的码号；done 时默认 = sizes[0]?.size ?? null，setSize 切换。 */
  activeSize: number | null;
  /** error 状态下的中文消息（后端 JSONResponse.error 或网络错 message）。 */
  error: string | null;
  /** 重置到 idle，清空 doc / activeSize / error。 */
  reset: () => void;
  /** 切换当前查看的码号（SizeTabs 调用）。 */
  setSize: (size: number | null) => void;
}

export const useUploadStore = create<UploadState>((set) => ({
  status: 'idle',
  doc: null,
  activeSize: null,
  error: null,
  reset: () => set({ status: 'idle', doc: null, activeSize: null, error: null }),
  setSize: (size) => set({ activeSize: size }),
}));
