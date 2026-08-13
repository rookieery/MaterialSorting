// previewTour —— 上传预览 Tab 的 5 步操作指引（US-030）。
//
// 流程：upload（上传母版）→ parsed（查看解析结果）→ set-qty（设置裁片数量）→
//      committed（已应用至超排）→ goto-nesting（进入超排）。
//
// 推进模型（advance-on-ready，详见 useTour.ts 注释）：
//   - 告知型步（upload / set-qty，无 ready）：用户读气泡 → 点「下一步」直接推进。
//   - 联动型步（parsed / committed / goto-nesting，有 ready）：进入该步时 ready()===false
//     → 切等待态（气泡显示 readyHint + 下一步 disabled）+ 200ms 轮询；ready() 翻 true 后
//     自动推进（最后一步 goto-nesting 为自动完成：markSeen('preview') + close）。
//
// ready 谓词口径（读 store 快照，不持本地状态）：
//   - parsed       uploadStore.status==='done' && doc!==null（解析完成）
//   - committed    uploadStore.commitStatus==='done'（自动 commit 完成）
//   - goto-nesting uiStore.activeTab==='nesting'（用户自己点超排 Tab，教学而非代办）
//
// 锚点用 data-tour 解耦 CSS 类名重构（querySelector 命中首个即可）：
//   - upload       [data-tour="drop-zone"]       （UploadPanel.tsx 拖拽落区）
//   - parsed       [data-tour="size-tabs"]       （SizeTabs.tsx 容器；未解析时不渲染 → 零尺寸回退居中）
//   - set-qty      [data-tour="piece-card-head"] （ParsedPiecesView.tsx 首个裁片卡片头）
//   - committed    [data-testid="commit-status"] （UploadPanel.tsx commit 状态行）
//   - goto-nesting [data-tour="tab-nesting"]     （TabBar.tsx 超排按钮）
//
// before 副作用：前 4 步确保 activeTab==='preview'（用户从超排 Tab 用菜单「重看上传预览指引」
// 触发时需切回 preview；defensive + 幂等）。第 5 步 goto-nesting 不切回（其语义就是等待用户
// 离开 preview 进入 nesting），故无 before。

import type { TourDef } from '../types';
import { useUploadStore } from '../../store/uploadStore';
import { useUiStore } from '../../store/uiStore';

/** 若不在 preview Tab 则切回（before 副作用，幂等）。goto-nesting 步不调用。 */
function ensurePreviewTab(): void {
  if (useUiStore.getState().activeTab !== 'preview') {
    useUiStore.getState().setTab('preview');
  }
}

export const previewTour: TourDef = {
  tabId: 'preview',
  steps: [
    {
      id: 'upload',
      selector: '[data-tour="drop-zone"]',
      title: '上传 DXF 母版',
      body: '把母版 DXF 文件拖到左侧上传区，或点击选择文件。解析后按码号查看每码全部裁片（毛版 / 净版 / 内部线 / 刀口 / 布纹线 + A/B/C 标注）。',
      placement: 'bottom',
      before: ensurePreviewTab,
    },
    {
      id: 'parsed',
      selector: '[data-tour="size-tabs"]',
      title: '查看解析结果',
      body: '解析完成后，按尺码切换查看每码全部裁片。点击裁片图形区可放大预览。',
      placement: 'bottom',
      before: ensurePreviewTab,
      ready: () =>
        useUploadStore.getState().status === 'done' &&
        useUploadStore.getState().doc !== null,
      readyHint: '请先上传 DXF 母版，解析完成后自动进入下一步',
    },
    {
      id: 'set-qty',
      selector: '[data-tour="piece-card-head"]',
      title: '设置裁片数量',
      body: '点击数量徽章（如 1片）设置每码排料份数（demand，0 = 该码跳过）。数量跨码匹配同一片型，这是求解前的必要一步。',
      placement: 'bottom',
      before: ensurePreviewTab,
    },
    {
      id: 'committed',
      selector: '[data-testid="commit-status"]',
      title: '已应用至超排',
      body: '解析结果会自动 commit 到超排（切单裁片 + 镜像 L/R），完成后此处显示「已应用至超排：N 裁片，M 码」，并解锁上方「超排」Tab。',
      placement: 'bottom',
      before: ensurePreviewTab,
      ready: () => useUploadStore.getState().commitStatus === 'done',
      readyHint: '等待解析结果自动应用至超排（commit）完成…',
    },
    {
      id: 'goto-nesting',
      selector: '[data-tour="tab-nesting"]',
      title: '进入超排',
      body: '点击上方「超排」Tab 进入排料页面，设置参数并开始求解。',
      placement: 'bottom',
      // 无 before：本步语义是等待用户离开 preview 进入 nesting，不能强制切回 preview。
      ready: () => useUiStore.getState().activeTab === 'nesting',
      readyHint: '请点击上方「超排」Tab 进入排料页面',
    },
  ],
};
