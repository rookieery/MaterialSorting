// Tour 类型定义（US-029 操作指引基础设施）。
//
// 定义操作指引（onboarding tour）的核心数据结构。Placement 描述气泡相对高亮目标的位置；
// TourStep 描述单步指引（selector 锚定 DOM、title/body 展示内容、before/ready 控制推进）；
// TourDef 描述一个 Tab 对应的完整指引序列。
//
// TabId 从 uiStore 复用（'nesting' | 'preview'），保证 tour 与 Tab 切换语义一致。
//
// advance-on-ready 模型（US-029 骨架 / US-030 完整落地）：
//   - 告知型步（无 ready 谓词）：用户点「下一步」直接推进（教学后用户自行操作）。
//   - 联动型步（有 ready 谓词）：ready()===true 才推进；false 时切等待态 + 下一步 disabled +
//     200ms 轮询调 ready()，true 时自动推进。readyHint 在等待态显示给用户（如「请先上传文件」）。
//   - before() 在进入该步时调（副作用：如切 Tab、滚动到目标）。
//
// 设计原则（CLAUDE.md）：业务逻辑集中在 tour 模块，前端只做渲染 + 状态联动。
// TourStep.body 用 ReactNode（支持富文本/强调，不只是 string）。

import type { ReactNode } from 'react';
import type { TabId } from '../store/uiStore';

/** 气泡相对高亮目标的位置；center = 视口居中（零尺寸兜底 / 无锚点）。 */
export type Placement = 'top' | 'bottom' | 'left' | 'right' | 'center';

/** 单步指引定义。 */
export interface TourStep {
  /** 步骤唯一 id（如 'upload'、'parsed'）。 */
  id: string;
  /** DOM 选择器锚定高亮目标（querySelector）；query 不到或零尺寸时回退居中。 */
  selector: string;
  /** 气泡标题。 */
  title: string;
  /** 气泡正文（支持 ReactNode 富文本）。 */
  body: ReactNode;
  /** 气泡相对目标的位置；默认 'bottom'。溢出视口自动翻向。 */
  placement?: Placement;
  /** 进入该步时调（副作用：如切 Tab、滚动）。 */
  before?: () => void;
  /** 推进就绪谓词；无 = 告知型（直接推进）；有 = 联动型（true 才推进，false 切等待态）。 */
  ready?: () => boolean;
  /** 等待态提示文案（ready()===false 时显示，引导用户完成前置操作）。 */
  readyHint?: string;
}

/** 一个 Tab 对应的完整指引序列。 */
export interface TourDef {
  /** 该指引归属的 Tab。 */
  tabId: TabId;
  /** 步骤序列（顺序执行）。 */
  steps: TourStep[];
}
