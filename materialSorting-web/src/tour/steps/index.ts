// Tour 步骤注册表 + 版本号（US-029 基础设施 / US-030 previewTour / US-031 nestingTour）。
//
// 导出：
//   TOUR_VERSION — tour 内容版本号。tourStore init 比对 localStorage 中 ms.tour.version；
//                  不一致则清空全部 seen（强制重看）。仅步骤内容重大变更时 bump（小改不改版本）。
//   TOURS        — Partial<Record<TabId, TourDef>>，按 TabId 注册该 Tab 的指引序列。
//                  useTour.getActiveTour 读 TOURS[activeTour]，auto-trigger 读 TOURS[tab]
//                  判断该 Tab 是否有指引（无则跳过自动触发）。
//
// 版本号 bump 触发条件（写注释提醒未来维护者）：
//   - 仅步骤内容重大变更（增删步骤、改 ready 语义、改锚点导致旧 seen 语义失效）时 bump；
//   - 文案小改、微调 placement 不 bump（老用户无需重看）。
//   bump 后 tourStore init 自动清 seen（US-029 已实现），用户下次进 Tab 自动触发新版。
//
// 版本历史：
//   '1' → '2'（矩阵化重构 US-005）：previewTour parsed/set-qty 两步锚点从旧 SizeTabs/
//         piece-card-head 迁到 QtyMatrix 矩阵（qty-matrix / qty-rowhead）+ 文案改矩阵
//         操作描述 —— 锚点重大变更，老用户 seen 强制清空重看。
//
// Partial 而非完整 Record<TabId, TourDef>：保留未来新增 Tab 时不必同步补 tour 的灵活性；
// auto-trigger 对无指引的 Tab（TOURS[tab]===undefined）直接跳过，不报错。

import type { TabId } from '../../store/uiStore';
import type { TourDef } from '../types';
import { nestingTour } from './nestingTour';
import { previewTour } from './previewTour';

/** Tour 内容版本号。bump 触发条件：仅步骤内容重大变更时 bump（强制老用户重看）。版本历史见文件头注释。 */
export const TOUR_VERSION = '2';

/**
 * 按 TabId 注册的指引序列。
 * preview：5 步上传预览指引（US-030）。
 * nesting：5 步超排指引（US-031，result/export 步用 runRegistry 帧快照联动推进）。
 */
export const TOURS: Partial<Record<TabId, TourDef>> = {
  preview: previewTour,
  nesting: nestingTour,
};
