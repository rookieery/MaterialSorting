// Tour 步骤注册表 + 版本号（US-029 基础设施）。
//
// 导出：
//   TOUR_VERSION  — tour 内容版本号。tourStore init 比对 localStorage 中 ms.tour.version；
//                   不一致则清空全部 seen（强制重看）。仅步骤内容重大变更时 bump（小改不改版本）。
//   DEMO_PREVIEW_TOUR — 2 步假 tour（验证整条链路：tourStore → useTour → TourOverlay）。
//
// US-030 将扩展本文件：汇总 TOURS: Record<TabId, TourDef>（previewTour / nestingTour），
// 替换 DEMO_PREVIEW_TOUR。版本号策略不变。
//
// 注意：TOUR_VERSION 由 tourStore init 读取（store 层依赖此常量），由 steps/index.ts 统一导出
// 保证版本号与步骤定义同源（改步骤时顺手 bump 版本号）。

import type { TourDef } from '../types';

/** Tour 内容版本号。bump 触发条件：仅步骤内容重大变更时 bump（强制老用户重看）。 */
export const TOUR_VERSION = '1';

/**
 * 2 步假 tour（US-029 验证整条链路用）。
 * 锚点选 App 常驻 DOM（.tabbar / .tab-content），保证任意 Tab 下都能 query 到。
 * US-030 替换为真实 previewTour 后删除。
 */
export const DEMO_PREVIEW_TOUR: TourDef = {
  tabId: 'preview',
  steps: [
    {
      id: 'demo-1',
      selector: '.tabbar',
      title: '欢迎使用操作指引',
      body: '这是一个操作指引演示。高亮区域是当前聚焦的界面元素，气泡会引导你完成操作。',
      placement: 'bottom',
    },
    {
      id: 'demo-2',
      selector: '.tab-content',
      title: '第二步',
      body: '指引会依次高亮关键区域。正式版本的指引将引导你完成「上传母版 → 解析 → 设数量 → 超排」全流程。',
      placement: 'top',
    },
  ],
};
