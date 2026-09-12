// nestingTour —— 超排 Tab 的 7 步操作指引（US-031；2026-09-12 扩为 7 步）。
//
// 流程：doc-banner（选码号 / 看当前文件）→ params（设置参数）→ solve（开始求解）→
//      result（查看排料结果）→ edit（编辑排料）→ save（保存当前方案）→ export（导出最优方案）。
//      edit/save 两步插在 result 与 export 之间，与 ControlPanel 区块物理顺序一致
//      （编辑排料 L498 → 保存当前方案 L503 → 导出 L508），引导叙事「拿到解 → 微调 → 存档 → 导出」。
//
// 推进模型（advance-on-ready，详见 useTour.ts 注释）：
//   - 告知型步（doc-banner / params / solve，无 ready）：用户读气泡 → 点「下一步」直接推进。
//   - 联动型步（result / edit / save / export，有 ready）：进入该步时 ready()===false → 切等待态
//     （气泡显示 readyHint + 下一步按钮 disabled）+ 200ms 轮询；ready() 翻 true 后自动推进
//     （result 推进到 edit…export 作为最后一步完成即 markSeen('nesting') + close）。
//   - result 与 previewTour 的 parsed 步同构：中间联动闸门（有结果 / 已解析才放行）。
//   - edit / save 与 ExportButtons/EditLayoutControls/SaveStateControls 的按钮激活口径同源
//     （有 lastFrame 的 run 即可用）—— 首跑自动触发场景下 result 步已闸过一次，其后四步
//     ready 立即为 true 顺序放行；手动重放（无解状态）时四步同闸防指引用户点灰按钮。
//
// ready 谓词口径（读 runRegistry 模块级单例快照，不读局部 SolvePhase）：
//   NestingPage 的 SolvePhase 是 useState，tour 模块无法外部读取；
//   runRegistry 是模块级 mutable 单例（store/runRegistry.ts），所有 useSolveRun 实例共享，
//   start() 时 create(seed) push 进数组、WS 推 frame 时 push 到 rec.frames + 更新 lastFrame。
//   故 `runRegistry.list().some(r => r.lastFrame !== null)` 等价「至少一个 seed 已产出帧」，
//   即用户已真实点「开始求解」并收到至少一帧（求解已启动且产出方案）。
//   - result    至少一个 run 有 lastFrame（有结果可看才放行到 edit）
//   - edit      至少一个 run 有 lastFrame（编辑按钮的激活判式同源）
//   - save      至少一个 run 有 lastFrame（保存按钮的激活判式同源）
//   - export    至少一个 run 有 lastFrame（有方案才允许导出，与 ExportButtons disabled 逻辑同源）
//
// 锚点用 data-tour 解耦 CSS 类名重构（querySelector 命中首个即可）：
//   - doc-banner  [data-tour="doc-banner"]   （ControlPanel.tsx 当前文件上下文条）
//   - params      [data-tour="param-form"]   （ControlPanel.tsx 参数区包裹层：ParamForm + PerTypeOverrides；2026-08-22 起 seed/multi_seed 控件已隐藏）
//   - solve       [data-tour="start-btn"]    （ControlPanel.tsx SolveControls 父容器）
//   - result      [data-tour="nest-wrap"]    （NestingPage.tsx 排料卡片网格容器）
//   - edit        [data-tour="edit-controls"]  （EditLayoutControls.tsx 编辑排料区块；锚点 2026-09-05 随组件落地预埋，2026-09-12 起被本步引用）
//   - save        [data-tour="save-state-group"]（SaveStateControls.tsx 保存当前方案区块；锚点 2026-09-12 随独立区块落地预埋，同日起被本步引用）
//   - export      [data-tour="export-group"] （ExportButtons.tsx 导出区根）
//
// before 副作用：7 步均 ensureNestingTab（用户从 preview Tab 用菜单「查看超排指引」
// 触发时需切回 nesting；defensive + 幂等）。
//
// （收敛曲线 / 回放条已于 2026-09-12 移除 —— result 步气泡文案同步去掉相关提及。）

import type { TourDef } from '../types';
import { useUiStore } from '../../store/uiStore';
import { runRegistry } from '../../store/runRegistry';

/** 若不在 nesting Tab 则切回（before 副作用，幂等）。7 步均调用。 */
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
      body: '在「幅宽 / 时长」调整求解参数；点「高级配置」可设置布局与算法参数（腰头成带 / 按裁片 g 码覆盖重合 / 旋转公差）。上方码号（多选）勾选要参与排料的尺码。',
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
      body: '求解启动后，右侧排料卡片实时显示每个 seed 的排料方案与利用率，实时跟随求解过程刷新至最终最优方案。',
      placement: 'right',
      before: ensureNestingTab,
      ready: hasProducedFrame,
      readyHint: '请先点击「开始求解」启动引擎，右侧产出排料方案后自动进入下一步…',
    },
    {
      id: 'edit',
      selector: '[data-tour="edit-controls"]',
      title: '编辑排料',
      body: '想人工微调结果时点「编辑」打开排料画布：左键拖动裁片、拖旋转手柄转角；右键拖动松手后自动吸附贴靠邻片（左键拖动不吸附）；空格循环镜像姿态、L / K 键逐度旋转。「智能微调」一键清理重合与歪斜（可撤销，不自动保存），改完点「保存当前布局」写回主界面；「重置」可放弃全部编辑恢复初始布局。',
      placement: 'right',
      before: ensureNestingTab,
      ready: hasProducedFrame,
      readyHint: '编辑排料需要先有方案 —— 请先完成一次求解（或停止保留中间方案）…',
    },
    {
      id: 'save',
      selector: '[data-tour="save-state-group"]',
      title: '保存当前方案',
      body: '点「保存」把当前工作台完整存档为 .msn 状态文件（母版数据、参数、码数数量与当前排料布局）。在任意电脑的「上传预览」页上传该文件，即可恢复到此刻的全部状态 —— 换机继续或交接他人都用它。',
      placement: 'right',
      before: ensureNestingTab,
      ready: hasProducedFrame,
      readyHint: '保存方案需要先有排料结果 —— 请先完成一次求解（或停止保留中间方案）…',
    },
    {
      id: 'export',
      selector: '[data-tour="export-group"]',
      title: '导出最优方案',
      body: '求解产出方案后，选择格式（DXF / PLT / PLT毛版 / PNG，默认 PLT 毛版）点「导出」，确认文件名后下载。默认导出利用率最高 seed 的最终方案；PLT 可直接送绘图仪切绘，DXF 走 R12 + POLYLINE（ET2008 兼容）。',
      placement: 'top',
      before: ensureNestingTab,
      ready: hasProducedFrame,
      readyHint: '等待求解产出方案后即可导出…',
    },
  ],
};
