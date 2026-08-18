// nestingTour —— 超排 Tab 的 5 步操作指引（US-031）。
//
// 流程：doc-banner（选码号 / 看当前文件）→ params（设置参数）→ solve（开始求解）→
//      result（查看排料结果）→ export（导出最优方案）。
//
// 推进模型（advance-on-ready，详见 useTour.ts 注释）：
//   - 告知型步（doc-banner / params / solve，无 ready）：用户读气泡 → 点「下一步」直接推进。
//   - 联动型步（result / export，有 ready）：进入该步时 ready()===false → 切等待态
//     （气泡显示 readyHint + 下一步按钮 disabled）+ 200ms 轮询；ready() 翻 true 后自动推进
//     （result 推进到 export；export 作为最后一步完成即 markSeen('nesting') + close）。
//   - result 与 previewTour 的 parsed 步同构：中间联动闸门（有结果 / 已解析才放行）。
//
// ready 谓词口径（读 runRegistry 模块级单例快照，不读局部 SolvePhase）：
//   NestingPage 的 SolvePhase 是 useState，tour 模块无法外部读取；
//   runRegistry 是模块级 mutable 单例（store/runRegistry.ts），所有 useSolveRun 实例共享，
//   start() 时 create(seed) push 进数组、WS 推 frame 时 push 到 rec.frames + 更新 lastFrame。
//   故 `runRegistry.list().some(r => r.lastFrame !== null)` 等价于「至少一个 seed 已产出帧」，
//   即用户已真实点「开始求解」并收到至少一帧（求解已启动且产出方案）。
//   - result    至少一个 run 有 lastFrame（有结果可看才放行到 export）
//   - export    至少一个 run 有 lastFrame（有方案才允许导出，与 ExportButtons disabled 逻辑同源）
//
// 锚点用 data-tour 解耦 CSS 类名重构（querySelector 命中首个即可）：
//   - doc-banner  [data-tour="doc-banner"]   （ControlPanel.tsx 当前文件上下文条）
//   - params      [data-tour="param-form"]   （ControlPanel.tsx 参数区包裹层：ParamForm + MultiSeedControls + PerTypeOverrides）
//   - solve       [data-tour="start-btn"]    （ControlPanel.tsx SolveControls 父容器）
//   - result      [data-tour="nest-wrap"]    （NestingPage.tsx 排料卡片网格容器）
//   - export      [data-tour="export-group"] （ExportButtons.tsx 导出区根）
//
// before 副作用：5 步均 ensureNestingTab（用户从 preview Tab 用菜单「查看超排指引」
// 触发时需切回 nesting；defensive + 幂等）。
//
// 收敛曲线并入 result 步气泡附带提及（不单独高亮、不单独锚点）。
// 回放（PlaybackBar）非主流程不单独成步。

import type { TourDef } from '../types';
import { useUiStore } from '../../store/uiStore';
import { runRegistry } from '../../store/runRegistry';

/** 若不在 nesting Tab 则切回（before 副作用，幂等）。5 步均调用。 */
function ensureNestingTab(): void {
  if (useUiStore.getState().activeTab !== 'nesting') {
    useUiStore.getState().setTab('nesting');
  }
}

/** 至少一个 run 已产出帧（用户已点开始求解并收到至少一帧）。 */
function hasProducedFrame(): boolean {
  return runRegistry.list().some((r) => r.lastFrame !== null);
}

export const nestingTour: TourDef = {
  tabId: 'nesting',
  steps: [
    {
      id: 'doc-banner',
      selector: '[data-tour="doc-banner"]',
      title: '当前文件',
      body: '此处显示已解析的母版文件名。若显示「尚未解析母版」，请先回到「上传预览」Tab 上传 DXF 母版并等待解析完成、应用至超排。',
      placement: 'bottom',
      before: ensureNestingTab,
    },
    {
      id: 'params',
      selector: '[data-tour="param-form"]',
      title: '设置参数',
      body: '在「幅宽 / 时长 / seed」调整求解参数；开启 multi_seed 可并行对比多个 seed 的方案；点「高级配置」可在 码号 × 裁片 g 码 矩阵中逐格覆盖重合 / 旋转公差（空格 = 继承默认，「≡」整列设值）。上方码号（多选）勾选要参与排料的尺码。',
      placement: 'bottom',
      before: ensureNestingTab,
    },
    {
      id: 'solve',
      selector: '[data-tour="start-btn"]',
      title: '开始求解',
      body: '确认码号与参数后，点击「开始求解」启动排料引擎。求解过程中右侧排料区以 ~10fps 实时刷新中间方案，可在求解途中点「停止」保留当前最优中间方案。',
      placement: 'bottom',
      before: ensureNestingTab,
    },
    {
      id: 'result',
      selector: '[data-tour="nest-wrap"]',
      title: '查看排料结果',
      body: '求解启动后，右侧排料卡片实时显示每个 seed 的排料方案与利用率。右上角收敛曲线展示求解过程利用率爬升。下方播放条可在求解结束后拖动回放中间帧。',
      placement: 'right',
      before: ensureNestingTab,
      ready: hasProducedFrame,
      readyHint: '请先点击「开始求解」启动引擎，右侧产出排料方案后自动进入下一步…',
    },
    {
      id: 'export',
      selector: '[data-tour="export-group"]',
      title: '导出最优方案',
      body: '求解产出方案后，选择格式（DXF / PNG）点「导出」。默认导出利用率最高的 seed 的最终方案；DXF 走 R12 + POLYLINE（ET2008 兼容），可直接用于裁床。',
      placement: 'top',
      before: ensureNestingTab,
      ready: hasProducedFrame,
      readyHint: '等待求解产出方案后即可导出…',
    },
  ],
};
