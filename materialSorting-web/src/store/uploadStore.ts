// UploadState —— DXF 上传预览页的状态中心（US-005）。
//
// 状态机：idle → uploading → done | error（任一终态可 reset 回 idle）。
// doc / activeSize / error 全部进 React state（与 runRegistry 那种高频 mutable 不同 ——
// 解析结果低频，进 store 触发 reconciliation 反而便于 UI 同步）。
//
// US-021 自动 commit 副作用状态机（独立于 parse status）：
//   commitStatus    'idle'（默认） / 'committing'（commit fetch 进行中） /
//                   'done'（commit 成功，commitSummary 已写入） /
//                   'error'（commit 失败，commitError 填消息）。
//                   与 status 分离：parse done 触发 commit，commit 后台跑不阻塞预览。
//   commitError     error 状态下的中文消息（HTTP 422 / 网络错）。
//   commitSummary   done 时后端返回的摘要（码数 / 裁片数 / 总面积），UploadPanel 展示
//                   「已应用至超排：N 裁片，M 码」。
//
// 字段口径：
//   status     'idle'（默认） / 'uploading'（fetch 进行中） / 'done'（200，doc 已写入） /
//              'error'（网络错或非 200，error 字段填中文消息）
//   doc        最近一次成功解析的响应（done 时才有效；其它状态保留旧值或 null ——
//              由 reset 清零，hook 内不主动清，避免切 uploading 时 UI 闪烁）
//   activeSize 当前选中的码号（number | null）；done 时默认 = sizes[0]?.size ?? null
//              （后端按数值升序、null 殿后，故 sizes[0] 是最小码）。矩阵化重构 US-003 起
//              由 QtyMatrix 列头点击切换（决定行头缩略图优先显示哪个码的版本；原
//              ParsedPiecesView 图形预览区已拆除）。
//   error      error 状态下的中文消息（HTTP 400/413/422 / 网络错）
//   zoom      放大预览模态的目标（label + size）；null 表示模态关闭。
//             US-013 PieceZoomModal 订阅此字段自显隐（声明式受控 Portal，
//             区别于排料页 Tooltip 的命令式单例）；openZoom/closeZoom 是
//             QtyMatrix 行头缩略图点击（传 rep 自身的码，所见即所放大）/ ✕ / 遮罩 / ESC
//             的统一入口。（原 ParsedPiecesView 卡片点击入口随图形预览区拆除一并删除；
//             数量编辑弹窗 qtyDialog 已随矩阵化重构 US-003 拆除，数量改在 QtyMatrix
//             格内直接编辑。）
//
// actions：
//   reset()              回到 idle，清空 doc / activeSize / error / zoom /
//                         commitStatus / commitError / commitSummary ——
//                         用户主动重传时调（重传成功后 US-014 集成 qtyStore.resetQuantities）
//   setSize(s)           切 activeSize（QtyMatrix 列头点击时调；s = number | null）
//   openZoom(l, s)       打开放大预览模态（点 QtyMatrix 行头缩略图时调；s = 缩略图 rep
//                        自身的码而非 activeSize，所见即所放大）
//   closeZoom()          关闭放大预览模态（✕ / 遮罩 / ESC 时调）
//
// hook 内部的状态过渡（uploading → done | error）由 useParseDxf 直接
// `useUploadStore.setState({...})` 写入，不暴露成 store 公开 action，避免业务组件
// 误触发状态跳变。store 公开 API 只含调用方语义动作（reset / setSize /
// openZoom / closeZoom）。commit 状态过渡
//（idle → committing → done | error）同样由 useCommitToNesting 直接 setState 写入。

import { create } from 'zustand';
import type { ParsedDoc } from '../types/parsed';

export type UploadStatus = 'idle' | 'uploading' | 'done' | 'error';

/** US-021 自动 commit 副作用状态机（与 parse status 分离，独立字段）。 */
export type CommitStatus = 'idle' | 'committing' | 'done' | 'error';

/** US-021 commit 成功摘要（后端 commit-to-nesting 响应切片）。UploadPanel 展示用。 */
export interface CommitSummary {
  /** 后端返回的 sizes 数组（码号列表，number[]）。 */
  sizes: number[];
  /** 后端返回的 n_pieces（intermediate 裁片总数，含 L/R 镜像）。 */
  n_pieces: number;
  /** 后端返回的 total_area_mm2（裁片原面积总和，mm²）。 */
  total_area_mm2: number;
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
  /** 放大预览模态目标（label + size）；null 表示模态关闭。 */
  zoom: ZoomTarget | null;
  /** US-021 自动 commit 副作用状态机（与 parse status 分离）。 */
  commitStatus: CommitStatus;
  /** US-021 commit 失败消息（commitStatus='error' 时有效）。 */
  commitError: string | null;
  /** US-021 commit 成功摘要（commitStatus='done' 时有效）。 */
  commitSummary: CommitSummary | null;
  /** 重置到 idle，清空 doc / activeSize / error / zoom / commit*。 */
  reset: () => void;
  /** 切换当前查看的码号（QtyMatrix 列头调用）。 */
  setSize: (size: number | null) => void;
  /** 打开放大预览模态（点行头缩略图 / 卡片图形区 body 时调）。 */
  openZoom: (label: string, size: number | null) => void;
  /** 关闭放大预览模态（✕ / 遮罩 / ESC 时调）。 */
  closeZoom: () => void;
}

export const useUploadStore = create<UploadState>((set) => ({
  status: 'idle',
  doc: null,
  activeSize: null,
  error: null,
  zoom: null,
  commitStatus: 'idle',
  commitError: null,
  commitSummary: null,
  reset: () =>
    set({
      status: 'idle',
      doc: null,
      activeSize: null,
      error: null,
      zoom: null,
      commitStatus: 'idle',
      commitError: null,
      commitSummary: null,
    }),
  setSize: (size) => set({ activeSize: size }),
  openZoom: (label, size) => set({ zoom: { label, size } }),
  closeZoom: () => set({ zoom: null }),
}));
