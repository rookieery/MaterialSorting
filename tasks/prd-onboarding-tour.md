# PRD: 操作指引 / Onboarding Tour（新用户主流程引导）

## 概述 (Overview)

在已落地的排料工作台（US-001~US-028）基础上，为系统增加一套**新用户操作指引**功能：以「高亮目标元素 + 气泡 step-by-step」的 guided tour 形式，引导用户走完主流程（上传母版 → 解析预览 → **设置裁片数量** → 应用至超排 → 选码/参数 → 求解 → 查看结果 → 导出）。

触发方式：① 首次进入某 Tab 自动播放；② 右上角新增入口可手动重放。

**核心难点**：主流程步骤间存在真实状态依赖——必须先上传母版才能 commit、commit 后才能求解、求解出帧后才能看结果/导出。传统「一次性线性走完所有步骤」的 tour 会跑在数据前面（后置步骤的目标 DOM 尚未生成或无意义）。本 PRD 采用 **「按 Tab 拆分独立 tour + advance-on-ready（状态就绪自动推进）」** 模式解决：把 tour 嵌进用户真实操作流，前置步骤完成后自动推进到后置步骤。

> **纯前端功能，零后端改动、零新依赖**：不引入 CSS 框架 / guided tour 库（沿用项目「依赖最小化」既定哲学，`package.json` 仅 react/react-dom/zustand）；高亮引擎照搬现有 `Tooltip.tsx` 的命令式 Portal 单例范式自研。

## 目标 (Goals)

- **降低新用户上手成本**：新用户首次进入工作台即被引导走完主流程，无需阅读文档即可知道「下一步该做什么」。
- **适配状态依赖（核心）**：tour 步骤随真实业务状态推进——后置步骤在前置状态未就绪时进入「等待态」提示，状态就绪后自动推进，绝不展示无意义/未生成的目标。
- **可重放、可重置**：老用户可随时从右上角入口重放任一 Tab 的指引，或重置「已读」状态重新触发自动播放。
- **记住已读、不打扰**：某 Tab 的 tour 看过一次后不再自动触发；tour 内容有重大改版时通过版本号强制老用户重看。
- **沿用现有架构与不变量**：不破坏 Tab `display:none` 切换不卸载、`scale(1,-1)` 翻转、Portal 到 body 的 z-index 层级、Zustand store 解耦、命令式 SVG 渲染范式、不引入 CSS 框架、`SolvePhase` 仍是 NestingPage 局部 state（不为 tour 上提 store）。

## 前置调研结论（关键技术事实，已查证）

| # | 事实 | 证据 / 落点 |
|---|---|---|
| F1 | **`SolvePhase`（idle/running/stopped/done/error）是 `NestingPage` 的局部 `useState`**（US-027），不在任何 store，外部模块无法直接读 | `src/components/NestingPage.tsx`：`const [phase, setPhase] = useState<SolvePhase>('idle')` |
| F2 | **`runRegistry` 是模块级 mutable 单例**，`list(): RunRecord[]` 每条含 `lastFrame`/`done`/`finalDensity`/`frames`，可被任意模块 `import` 直接读快照 | `src/store/runRegistry.ts`：模块级 `runRegistry` + `list()`；`RunRecord.lastFrame` 非空 = 有排料帧 = 求解过/可导出。语义等价于「求解已产出结果」，**无需把 phase 上提 store** |
| F3 | **`scale(1,-1)` 翻转只在 SVG 内部**（flipGroup 上），HTML 容器层无坐标翻转 → `getBoundingClientRect()` 返回正确屏幕坐标，自研高亮无障碍 | `src/components/nests/NestSVG.tsx` 的 `translate(0 gate) scale(1 -1)` 在 SVG `<g>` 上；`Tooltip.tsx` 用 `position:fixed` + 客户端坐标同样不受影响 |
| F4 | **现有 `Tooltip.tsx` 已是成熟的命令式 Portal 单例范式**：模块级 `_el` 单例 + `registerTooltipEl` + imperative `style` 写入 + `createPortal(..., document.body)` + `position:fixed` | `src/components/Tooltip.tsx`：照搬即可得到风格一致的 tour 高亮层，零主题适配成本 |
| F5 | **现有模态遮罩范式**：`position:fixed; inset:0; rgba(0,0,0,0.6)` + Portal to body；z-index 层级链 `tooltip(100) < piece-qty/piece-zoom(1000) < per-type(1100) < ptype-preview(1200)` | `src/style.css`：`.piece-qty-dialog-overlay` / `.per-type-overlay` / `.ptype-preview-overlay`；**tour-overlay 取 z-index:2000 高于一切** |
| F6 | **Tab 切换靠 `.hidden { display:none }`，组件不卸载**（关键不变量 #1）→ 目标元素在隐藏页时 `getBoundingClientRect()` 全零 | `src/App.tsx`：双 `.page` 容器 display:none 切换；`src/store/uiStore.ts`：`setTab('nesting')` 在 `nestingEnabled===false` 时静默不切 |
| F7 | **项目零 localStorage / sessionStorage / onboarding 代码**（首个引入） | 全仓 grep `localStorage\|sessionStorage\|firstRun\|onboard\|tour\|guide\|hasSeen` = 0 匹配；干净起点，无冲突 |
| F8 | **可复用的 store 状态作就绪信号源** | `uiStore.nestingEnabled`（Tab 解锁闸）/ `uiStore.activeTab`（当前 Tab，goto-nesting 步推进依据）；`uploadStore.status==='done' && doc!==null`（已解析）；`uploadStore.commitStatus==='done'`（已应用至超排）；`runRegistry.list().some(r => r.lastFrame !== null)`（有排料帧） |
| F9 | **dev/prod 双路径**：dev Vite proxy `/api` `/ws`；prod 同源 :8000；tour 纯前端，不涉及网络，两路径零差异 | `src/components/` 速查；`vite.config.ts` |
| F10 | **测试栈**：vitest + jsdom（`vitest.config.ts`），每个组件配 `__tests__`；`tsconfig.json` 开 `noUnusedLocals`/`noUnusedParameters`（测试文件同样受约束）；React 18 StrictMode 双 mount 需幂等 | `src/**/__tests__/` |

## 核心难点方案：advance-on-ready（状态就绪自动推进）

每个 tour 步骤携带一个可选的就绪谓词 `ready?: () => boolean`（读 store / `runRegistry` 快照）。控制逻辑：

1. 用户点「下一步」→ 控制器检查**目标步**的 `ready` 谓词。
2. 目标步无 `ready` 谓词（告知型步）或 `ready()===true` → 正常推进、高亮目标步。
3. `ready()===false` → 气泡**不消失**，切换为「等待态」文案（步骤定义里的 `readyHint`，如「请先上传一个母版 DXF，解析完成后自动继续」），「下一步」按钮置 **disabled**（强制等待，避免用户误以为卡住），并启动 **200ms 轮询**检查 `ready()`。
4. 一旦 `ready()` 翻 `true` → 停止轮询、**自动推进**到目标步、按钮恢复。

**advance-on-ready 统一用轮询**（每 200ms 调一次目标步 `ready()` 读 store/`runRegistry` 快照）：store（`uploadStore`/`uiStore`）与 `runRegistry`（模块级单例无订阅能力，F2）走同一套逻辑，close 时清定时器即可，天然避免 subscribe/unsub 泄漏复杂度。

这是唯一「不跑在数据前面」的方案：把 tour 嵌进用户真实操作流。备选（禁用/跳过后置步 = 体验割裂；强制引导回上一步 = 与真实工作流纠缠）均否决。

> 每步还可带 `before?: () => void` 副作用（如确保 `activeTab` 对齐，避免高亮隐藏页内零尺寸元素）。

## 步骤分段（按 Tab 拆分两个独立 tour）

### preview tour（5 步）

| # | id | 锚点 | 就绪条件 `ready` | `readyHint` |
|---|---|---|---|---|
| 1 | `upload` | `[data-tour="drop-zone"]` | 告知型（无 ready） | — |
| 2 | `parsed` | `[data-tour="size-tabs"]` | `uploadStore.status==='done' && doc!==null` | 请先上传一个母版 DXF，解析完成后自动继续 |
| 3 | `set-qty` | `[data-tour="piece-card-head"]` | 告知型（无 ready） | — |
| 4 | `committed` | `[data-testid="commit-status"]` | `uploadStore.commitStatus==='done'` | 正在应用至超排，稍候自动继续… |
| 5 | `goto-nesting` | `[data-tour="tab-nesting"]` | `uiStore.activeTab==='nesting'` | 点击「超排」Tab 进入排料页，自动继续 |

> - **第 3 步（设置裁片数量）**：告知型——高亮首个裁片卡片头部，气泡说明「点击数量徽章设置每码排料份数（demand，0=该码跳过），这是求解前必要的一步」；用户点「下一步」即推进（**不强制检测是否真已设置**，因 `qtyStore` 有 `hydrateDefaults` 预填，无可靠的「用户已设完」信号）。
> - **第 5 步（进入超排）**：引导用户**自己点**「超排」Tab（教学而非代办）；`ready=activeTab==='nesting'`，用户点 Tab 切换后轮询检测到、自动推进，并因 `seen.nesting===false` 触发 nesting tour（进入超排页自动开始）。

### nesting tour（5 步）

| # | id | 锚点 | 就绪条件 `ready` | `readyHint` |
|---|---|---|---|---|
| 1 | `doc-banner` | `[data-tour="doc-banner"]`（+ SizePicker 区） | 告知型（无 ready） | — |
| 2 | `params` | `[data-tour="param-form"]` | 告知型（无 ready） | — |
| 3 | `solve` | `[data-tour="start-btn"]`（`button#start`） | 告知型（无 ready） | — |
| 4 | `result` | `[data-tour="nest-wrap"]` | `runRegistry.list().some(r => r.lastFrame!==null)` | 请先点「开始求解」，产出排料结果后自动继续 |
| 5 | `export` | `[data-tour="export-group"]` | 同 step4 | 同 step4 |

> - **回放（PlaybackBar/Seekbar）非主流程，不单独成步**；收敛曲线（ConvergenceCurve，求解利用率爬升）并入第 4 步「查看结果」气泡附带提及（如「右上角收敛曲线展示求解过程利用率爬升」），不单独高亮、不单独锚点。
> - 每步 `before` 确保 `activeTab==='nesting'`（防御 tour 在非超排页激活时高亮零尺寸元素）。

## 用户故事 (User Stories)

### US-029: Tour 基础设施（tourStore + 高亮引擎 + 控制器 + 右上角入口 + 持久化骨架）
- **Description**: As a 新用户, I want 一个能在任意 DOM 元素上显示「高亮聚光灯 + 气泡」的引导层载体 + 右上角可手动触发的入口, so that 后续 tour 步骤有统一载体、且我随时能主动呼出指引。
- **Acceptance Criteria**:
  1. 新建 `materialSorting-web/src/tour/types.ts`：导出 `Placement = 'top'|'bottom'|'left'|'right'|'center'`、`TourStep`（`id` / `selector` / `title` / `body: ReactNode` / `placement?` / `before?: () => void` / `ready?: () => boolean` / `readyHint?: string`）、`TourDef`（`tabId: TabId` / `steps: TourStep[]`）。`TabId` 从 `uiStore` 复用。
  2. 新建 `materialSorting-web/src/store/tourStore.ts`（Zustand）：state `activeTour: TabId|null`、`stepIndex: number`、`seen: Record<TabId, boolean>`；actions `start(tabId)`（置 activeTour + stepIndex=0）、`next()`/`prev()`（边界 clamp）、`close()`（activeTour=null）、`markSeen(tabId)`、`resetSeen()`。**init 时从 `localStorage` hydrate `seen`**（key `ms.tour.seen.<tabId>` = `"1"`）；`markSeen` 同步写 localStorage。**版本号 `ms.tour.version`**：init 时比对常量 `TOUR_VERSION`，不一致则清空全部 seen 并写新版本号（强制重看）。不引入 zustand persist 中间件（手写 3 行更轻、不污染既有 store）。
  3. 新建 `materialSorting-web/src/tour/TourOverlay.tsx`：订阅 `tourStore.activeTour/stepIndex`；`activeTour===null` 时 `return null`。激活时 `createPortal(..., document.body)` 渲染：①`.tour-overlay` 全屏遮罩（`position:fixed; inset:0; z-index:2000`，高于 ptype-preview 的 1200）；②`.tour-spotlight` 聚光灯——一个绝对定位 div 贴在 `document.querySelector(selector)` 的 `getBoundingClientRect()` 上，用 `box-shadow: 0 0 0 9999px rgba(0,0,0,0.6)` 制造全屏遮罩 + 镂空（天然圆角 `border-radius`）；③`.tour-bubble` 气泡按 `placement` 在聚光灯四周贴边，溢出视口自动翻向；④按钮组「上一步 / 下一步 / 跳过」。复用 `Tooltip.tsx` 命令式单例范式（参考 F4）。
  4. 新建 `materialSorting-web/src/tour/useTour.ts`：控制器 hook，暴露 `start/next/prev/close`；内部读当前步定义、调 `before` 副作用、按 `ready` 判断推进。**advance-on-ready 骨架（统一轮询）**：`next()` 检查目标步 `ready`——目标步无 `ready` 谓词（告知型）或 `ready()===true` 直接推进；`ready()===false` 时切「等待态」+「下一步」按钮 disabled + 启动 200ms 轮询调 `ready()`，true 时停轮询 + 自动推进（本 Story 仅接通骨架 + 一个无依赖假步，完整 advance-on-ready 在 US-030 落地）。close/stepIndex 变化时清轮询定时器（防泄漏）。
  5. **重算时机**：步骤切换、`window resize`、`scroll`、advance-on-ready 轮询推进/状态变化时重新读 `getBoundingClientRect()` 更新聚光灯位置（目标元素可能状态变化后才挂载）。
  6. `materialSorting-web/src/App.tsx`：在 `<Tooltip/>`（F4 单例）旁挂 `<TourOverlay/>` 单例（App 生命周期内一个，与 Tooltip 同层）。
  7. `materialSorting-web/src/components/TabBar.tsx`：在 `<nav class="tabbar">` 内追加右上角入口（`margin-left:auto`，`.tabbar` 右侧空位），native `<button>`「操作指引」+ 下拉菜单（本 Story 仅放「重置全部指引」一项触发 `start('preview')` 跑一个 2 步假 tour 验证链路；US-032 补全「重看 preview / 重看 nesting / 重置全部」三项）。沿用 `.tab` 暗色系 + `#2ea06c` 强调，a11y（aria-haspopup / aria-expanded）。
  8. `materialSorting-web/src/style.css` 末尾新增段：`.tour-overlay` / `.tour-spotlight` / `.tour-bubble` / `.tour-title` / `.tour-body` / `.tour-btn-*` / `.tour-menu*`（暗背景 `#26282e` + `#2ea06c` 同色系，z-index 2000；`.tour-menu` 下拉 z-index 1300，高于 tabbar 不挡 overlay）。
  9. **目标元素零尺寸兜底**（对应 F6）：query 到的元素 `getBoundingClientRect()` 全零（在 `.hidden` 页）时回退「居中气泡无高亮」，不报错。
  10. 新建 `materialSorting-web/src/store/__tests__/tourStore.test.ts`：≥6 项 — 默认 activeTour=null / start 置 activeTour+stepIndex=0 / next+prev 边界 clamp / close 清 activeTour / markSeen 写 localStorage + hydrate / TOUR_VERSION 不一致清 seen。
  11. 新建 `materialSorting-web/src/tour/__tests__/TourOverlay.test.tsx`：≥4 项 — activeTour=null 不渲染 / 激活渲染 overlay+spotlight+bubble / spotlight 贴目标 rect / 零尺寸回退居中。
  12. **通过浏览器验证**（UI Story 必备）：`npm run dev` + `ms-web` 启动后，点右上角「操作指引」→ 假 tour 2 步高亮正确、气泡定位不溢出视口、resize/scroll 聚光灯跟随、ESC/跳过关闭、刷新后 seen 状态保留。
  13. `cd materialSorting-web && npm run typecheck` 通过、`npm run test` 全绿、`npm run build` 无报错。
- **Priority**: 1
- **依赖**: 无（独立前端基础设施；US-030/031 消费）

### US-030: preview tour 全量 + advance-on-ready + 首次自动触发
- **Description**: As a 新用户, I want 首次进入上传预览页时自动播放 5 步指引，并在上传/解析/commit 完成后自动推进到后续步骤, so that 我知道如何上传母版、设置裁片数量并进入超排，且不会看到尚无意义的步骤。
- **Acceptance Criteria**:
  1. 新建 `materialSorting-web/src/tour/steps/previewTour.ts`：导出 `previewTour: TourDef`，含 5 步（`upload`/`parsed`/`set-qty`/`committed`/`goto-nesting`）。`parsed` 的 `ready` 读 `uploadStore.status+doc`；`committed` 读 `uploadStore.commitStatus`；`goto-nesting` 读 `uiStore.activeTab==='nesting'`；`upload`/`set-qty` 为告知型（无 `ready`）（见上文步骤分段表）。
  2. 新建 `materialSorting-web/src/tour/steps/index.ts`：汇总 `TOURS: Record<TabId, TourDef>` + 导出常量 `TOUR_VERSION`（初值 `"1"`）；**顶部注释写明 bump 触发条件**（仅步骤内容重大变更时 bump，强制老用户重看；小改不改版本）。
  3. `materialSorting-web/src/tour/useTour.ts` 落地完整 **advance-on-ready（统一轮询）**：`next()` 时若目标步有 `ready` 且 `ready()===false`，气泡切「等待态」显示 `readyHint` + 「下一步」按钮 **disabled**（强制等待，已与用户确认），启动 200ms 轮询调 `ready()`（读 `uploadStore.getState()` / `uiStore.getState()` 快照），true 时停轮询、自动 `next` 推进；告知型步（无 `ready`）点「下一步」直接推进。close 时清轮询定时器。
  4. **首次进入 Tab 自动触发**：`useTour`（或 App 层 effect）`subscribe` `uiStore.activeTab`；tab 变化且 `!seen[tab]` 时，延迟 ~300ms（等目标 DOM 稳定）调 `start(tab)`。App 首次 mount 时若 `activeTab` 对应 tour 未看过也触发。
  5. **锚点属性**：给 `materialSorting-web/src/components/preview/UploadPanel.tsx` 的 `.drop-zone` 加 `data-tour="drop-zone"`；`SizeTabs.tsx` 容器加 `data-tour="size-tabs"`；`ParsedPiecesView.tsx` 的裁片卡片头（`.piece-card-head`，querySelector 取首个）加 `data-tour="piece-card-head"`；`UploadPanel.tsx` 的 commit 状态行确认有 `[data-testid="commit-status"]`（无则补）；`TabBar.tsx` 超排按钮加 `data-tour="tab-nesting"`。优先用 `data-tour` 解耦 CSS 类名重构。
  6. **第 5 步（goto-nesting）引导用户自己点超排 Tab**（已与用户确认：教学而非代办）：该步 `ready = () => useUiStore.getState().activeTab === 'nesting'`（**不自动 setTab**）；气泡引导用户点击「超排」Tab。用户点 Tab 切换后，轮询检测到 `activeTab==='nesting'` → 自动推进并 `markSeen('preview')`；因 `seen.nesting===false`，进入超排页自动触发 nesting tour（US-031 接通后端到端；本 Story 验证用户点 Tab 后推进 + preview 标记 seen）。
  7. 新建 `materialSorting-web/src/tour/__tests__/useTour.test.tsx`：≥5 项 — 告知型步（无 ready）点下一步直接推进 / advance-on-ready 等待态（mock `ready=false` 后不推进 + 切等待态文案 + 下一步 disabled）/ 轮询检测 ready 翻 true 后自动推进 + 停轮询 / `before` 副作用执行 / close 后无残留定时器。
  8. 扩展 `materialSorting-web/src/tour/__tests__/TourOverlay.test.tsx`：等待态气泡渲染 `readyHint`。
  9. **通过浏览器验证**（UI Story 必备）：清 localStorage（或 `resetSeen`）后进入 preview → tour 自动起；上传真实 DXF 后 step2（解析）在解析完成、step4（commit）在 commit 完成后**自动推进**（无需手动点下一步）；step3（设数量）告知型点下一步过；step5 引导用户自己点「超排」Tab，点后自动推进并进入 nesting tour。
  10. `cd materialSorting-web && npm run typecheck` 通过、`npm run test` 全绿、`npm run build` 无报错。
- **Priority**: 2
- **依赖**: US-029（基础设施）

### US-031: nesting tour 全量（5 步 + 真实求解状态联动）
- **Description**: As a 用户, I want 首次进入超排页时播放 5 步指引，并在求解产出结果后自动推进到结果/导出步骤, so that 我知道如何选码、求解、看结果、导出。
- **Acceptance Criteria**:
  1. 新建 `materialSorting-web/src/tour/steps/nestingTour.ts`：导出 `nestingTour: TourDef`，含 5 步（`doc-banner`/`params`/`solve`/`result`/`export`）。`result`/`export` 的 `ready` 读 `runRegistry.list().some(r => r.lastFrame !== null)`（对应 F1/F2：不读局部 `SolvePhase`，用 `runRegistry` 快照绕开）；前 3 步为告知型（无 `ready`）；每步 `before` 确保 `activeTab==='nesting'`。第 4 步「查看结果」气泡附带提及收敛曲线（不单独成步）。
  2. 把 `nestingTour` 并入 `tour/steps/index.ts` 的 `TOURS`。
  3. **锚点属性**：给 `materialSorting-web/src/components/ControlPanel/ControlPanel.tsx` 的 `.doc-banner` 加 `data-tour="doc-banner"`；SizePicker 区容器加 `data-tour="param-form"`（或 ParamForm 区，按实际组件命名）；`SolveControls.tsx` 的 `button#start` 父容器加 `data-tour="start-btn"`；`NestsGrid`/`.nest-wrap` 加 `data-tour="nest-wrap"`；`ExportButtons.tsx` 的 `.export-group` 加 `data-tour="export-group"`。（收敛曲线 `#curve` 不单独加锚点，并入 result 步气泡文字提及；回放 `.playback` 非主流程不涉及。）
  4. **advance-on-ready 联动求解（轮询，已与用户确认）**：step3「开始求解」为告知型（点下一步直接推进，用户只是被告知按钮位置）；用户真实点「开始求解」跑出帧后，`runRegistry` 出现 `lastFrame!==null` 的记录，step4（result）/step5（export）的 `ready` 翻 true。因 `runRegistry` 是模块级 mutable 单例**无 store 订阅能力**（F2），advance-on-ready 统一用 200ms 轮询调 `ready()`（读 `runRegistry.list()` 快照），true 时自动推进；close 时停轮询。
  5. 进入 nesting tab（且 `!seen.nesting`）自动启动该 tour（US-030 的自动触发机制覆盖）。
  6. 新建 `materialSorting-web/src/tour/__tests__/nestingTour.test.ts`（或扩展 useTour 测试）：≥3 项 — `result`/`export` 步 `ready` 在 `runRegistry` 无帧时 false / 有帧时 true / 5 步 selector 全部能在已渲染的超排页 query 到（jsdom 挂载 NestingPage mock runRegistry）。
  7. **通过浏览器验证**（UI Story 必备）：完成一次完整「上传母版 → 设数量 → commit → 进超排 → tour 自动起 5 步 → 点开始求解 → step4/5 在产出帧后自动推进 → 导出」端到端联调。
  8. `cd materialSorting-web && npm run typecheck` 通过、`npm run test` 全绿、`npm run build` 无报错。
- **Priority**: 3
- **依赖**: US-030（advance-on-ready + 自动触发机制）

### US-032: 手动入口完善 + 打磨边界 + 完整单测
- **Description**: As a 老用户, I want 右上角入口能重放任一 Tab 的指引或重置全部，且 tour 在各种边界（ESC/遮罩/reduced-motion/StrictMode 双 mount）下行为正确, so that 我随时复习且无 buggy 体验。
- **Acceptance Criteria**:
  1. `materialSorting-web/src/components/TabBar.tsx` 右上角下拉菜单补全三项：①「重看上传预览指引」→ `tourStore.start('preview')`（强制重放，不检查 seen）②「重看超排指引」→ `start('nesting')` ③「重置全部指引」→ `resetSeen()`（清 localStorage 全部 `ms.tour.seen.*`，下次进 Tab 自动触发）。下拉点外部/ESC 关闭。
  2. **关闭交互完备**：ESC 键关闭 tour；遮罩点击关闭（仅落在 overlay 自身，参考 `.piece-qty-dialog-overlay` 的 `e.target===e.currentTarget` 模式）；「跳过」按钮关闭并 `markSeen(activeTab)`（视为已读不再自动触发）。
  3. **`prefers-reduced-motion`**：检测 `window.matchMedia('(prefers-reduced-motion: reduce)')`，为真时关闭聚光灯/气泡的过渡动画（直接定位）。
  4. **目标元素滚入视口**：高亮前 `element.scrollIntoView({block:'nearest'})`，避免目标在视口外时聚光灯贴到视口边缘外。
  5. **StrictMode 双 mount 幂等**：`<TourOverlay/>` 单例 + `tourStore` 模块级单例在 StrictMode 双 mount 下不重复启动 tour、订阅不翻倍（参考 `Tooltip.tsx` 的 `registerTooltipEl` 模式 + `NestSVG.tsx` 的 manifest 身份判等思路）。
  6. **版本号策略**：`TOUR_VERSION` 仅在步骤内容重大变更时 bump（小改不改版本，避免打扰老用户）；bump 后 init 强制清 seen（US-029 已实现，本 Story 补单测）。
  7. 补全单测：`tourStore` 版本号清 seen 用例；`useTour` 订阅泄漏（close 后无残留订阅）；`TourOverlay` ESC/遮罩/跳过关闭 + reduced-motion 跳过过渡；TabBar 下拉三项各自触发正确 action。
  8. **通过浏览器验证**（UI Story 必备）：重放 preview/nesting 各一次、重置后下次进 Tab 自动触发、ESC/遮罩/跳过三种关闭、窗口缩放聚光灯不漂移、目标在视口外滚入、StrictMode 下无重复。
  9. `cd materialSorting-web && npm run typecheck` 通过、`npm run test` 全绿、`npm run build` 产出 `static/`（prod 模式前必须 build，见 CLAUDE.md）。
- **Priority**: 4
- **依赖**: US-031（nesting tour 全量）

## 功能需求 (Functional Requirements)

- **FR-1**：两个独立 tour（preview 5 步 / nesting 5 步），各自首次进入对应 Tab 且未读时自动播放。
- **FR-2**：每步高亮目标 DOM 元素（聚光灯镂空遮罩）+ 气泡（标题 + 正文 + 上一步/下一步/跳过）。
- **FR-3**：advance-on-ready——目标步 `ready===false` 时气泡切等待态，状态就绪自动推进。
- **FR-4**：右上角「操作指引」入口，下拉含重看 preview / 重看 nesting / 重置全部。
- **FR-5**：localStorage 按维度记 `ms.tour.seen.<tabId>`；`ms.tour.version` 版本号变更强制重看。
- **FR-6**：关闭方式：ESC / 遮罩点击 / 跳过按钮；跳过视为已读。
- **FR-7**：目标元素零尺寸（隐藏页）回退居中气泡无高亮；目标在视口外滚入。
- **FR-8**：`prefers-reduced-motion` 关闭过渡动画。

## 非目标 (Non-Goals)

- **NG-1**：不引入 guided tour 第三方库（driver.js / react-joyride / shepherd.js / intro.js）——自研，保持依赖最小化。driver.js 仅作「自研高亮打磨成本失控时」的备选，不在本 PRD 范围。
- **NG-2**：不高亮命令式 SVG 内部节点（单个 `<polygon>` 裁片）——只高亮 HTML 容器（`.nest-card`/`.drop-zone`/`.panel`）。SVG 内部 `scale(1,-1)` 坐标反算复杂度高，v1 不做。
- **NG-3**：不把 `SolvePhase` 从 NestingPage 局部 state 上提到 store——tour 用 `runRegistry` 快照绕开（F1/F2）。phase 上提是独立重构，不在本 PRD。
- **NG-4**：不做后端改动、不新增 API/WS——纯前端功能。
- **NG-5**：不做多用户维度（按 user 存 seen）——本应用是单用户本地工作台，无登录态。
- **NG-6**：不做 tour 进度跨 Tab 连续（如 preview 最后一步进入 nesting 后不强制续播 nesting tour 的特定步——各自独立首次触发）。
- **NG-7**：不做 tour 步骤的 i18n / 多语言——文案中文硬编码（与现有 UI 一致）。

## 设计考虑 (Design Considerations)

- **视觉**：沿用 `style.css` 暗背景 `#26282e/#2a2c32` + 绿色 `#2ea06c` 强调同色系（与 ControlPanel / TabBar active / size-chip active / StartButton 一致），不引入 CSS 框架。
- **z-index 层级**：`tour-overlay` = 2000（高于 ptype-preview 1200 / per-type 1100 / 弹窗 1000 / tooltip 100）；`tour-menu` 下拉 = 1300（高于 tabbar，低于 overlay 以便 tour 激活时下拉不挡）。
- **气泡定位**：参考 `Tooltip.tsx` 的 `position:fixed` + 客户端坐标偏移；按 `placement` 在聚光灯四周贴边，溢出视口自动翻向。
- **聚光灯技巧**：单 div + `box-shadow: 0 0 0 9999px rgba(0,0,0,0.6)` 制造全屏遮罩 + 镂空，天然圆角（升级路径：需步骤间平滑过渡再换 SVG mask，v1 不必要）。
- **锚点解耦**：关键目标加 `data-tour="<id>"` 属性，避免依赖可能重构的 CSS 类名；对已有稳定语义锚点（`#start`、`.drop-zone`、`.export-group`）可直接用。
- **命令式 vs 声明式**：`TourOverlay` 可声明式渲染（React 控制 overlay/spotlight/bubble 的存在性），但聚光灯定位用 imperative `style` 写入 rect（参考 Tooltip），避免高频 rect 更新走 React reconciliation。

## 技术考虑 (Technical Considerations)

- **复用 Tooltip 命令式 Portal 单例范式**（F4）：`TourOverlay` Portal 到 `document.body` + `position:fixed`，与既有 Tooltip/弹窗同口径，不受父级 transform/overflow 影响。
- **store 解耦**：`tourStore` 不读 `uploadStore`/`uiStore`/`runRegistry`；就绪谓词 `ready` 在步骤定义里以闭包形式读各 store 快照（`useXxxStore.getState()`），与 `PreviewPage` 联动 `setNestingEnabled` 的 store 解耦原则一致（store 间不直接 import；tour 侧 `ready` 用闭包读快照、advance-on-ready 用轮询，**不用 subscribe**）。
- **`runRegistry` 无 store 订阅**（F2）：模块级 mutable 单例，advance-on-ready 若需响应其变化，用轮询（rAF/定时）而非 subscribe；close 时停轮询防泄漏。
- **Tab `display:none` 不卸载**（F6 / 关键不变量 #1）：tour 自动触发依赖 `uiStore.activeTab` 订阅，不依赖组件 mount/unmount；目标元素隐藏时 rect 全零需兜底（居中气泡）。
- **StrictMode 双 mount 幂等**（F10）：单例（store + overlay）初始化幂等，参考 `Tooltip.registerTooltipEl` + `NestSVG` manifest 身份判等。
- **`scale(1,-1)` 不受影响**（F3）：翻转在 SVG 内部，HTML 容器 rect 正常，自研高亮无坐标换算负担。
- **tsconfig 严格**（F10）：`noUnusedLocals`/`noUnusedParameters` 开，测试文件同样受约束；新增文件注意无未用导入。
- **路径**：前端无后端路径问题；新增文件均在 `materialSorting-web/src/` 下，遵循现有 `tour/` / `store/` 目录划分。

## 成功指标 (Success Metrics)

- [ ] 全新用户（清 localStorage）进入工作台，preview tour 自动触发并正确高亮 5 个锚点。
- [ ] 上传真实 DXF 后，preview tour 的 step2（解析）/step4（commit）在状态就绪后**自动推进**（无需手动点下一步）；step3（设数量）告知型点下一步过；step5（进超排）在用户点超排 Tab 后自动推进。
- [ ] 进入超排 Tab，nesting tour 自动触发，5 步跟随真实求解状态推进（点开始求解出帧后 step4/5 自动推进）。
- [ ] 右上角「操作指引」可随时重放任一 tour，「重置全部」清状态后下次进 Tab 自动触发。
- [ ] 高亮对 HTML 元素（`.drop-zone`）与含命令式 SVG 的 HTML 容器（`.nest-wrap`）均定位正确，resize/scroll 不漂移。
- [ ] ESC / 遮罩点击 / 跳过三种方式可关闭；关闭后不阻塞业务交互。
- [ ] `npm run typecheck` + `npm run test` 全绿，`npm run build` 产出 `static/`，**不新增运行时依赖**（`package.json` dependencies 不变）。
- [ ] 刷新后 seen 状态保留；bump `TOUR_VERSION` 后老用户重看。

## 待确认问题 (Open Questions)

> **全部决策已确认并落入正文**：
> - ① 等待态「下一步」按钮 **disabled** 强制等待；
> - ② advance-on-ready **统一 200ms 轮询**（store 与 `runRegistry` 同一套，close 清定时器）；
> - ③ preview tour 第 5 步**引导用户自己点超排 Tab**（`ready=activeTab==='nesting'`，不自动 setTab）；
> - ④ 「设置裁片数量」步**保持告知型**（点下一步即过，不检测用户实际操作，因 `qtyStore` 有 `hydrateDefaults` 预填、无可靠完成信号）；
> - ⑤ `TOUR_VERSION` bump 规范在 `tour/steps/index.ts` 顶部**注释写明**（仅步骤内容重大变更时 bump）；
> - ⑥ 右上角入口用**下拉菜单**（收纳「重看 preview / 重看 nesting / 重置全部」三项）。

**无未决问题，PRD 可转 prd.json 交付 Ralph 自动循环执行。**

---

## 依赖关系图

```
US-029 (基础设施: tourStore + TourOverlay + useTour骨架 + 右上角入口)
   │
   ▼
US-030 (preview tour + advance-on-ready + 自动触发)
   │
   ▼
US-031 (nesting tour + 求解状态联动)
   │
   ▼
US-032 (下拉菜单完善 + 打磨边界 + 完整单测)
```

4 个 Story 严格顺序依赖，无并行。每个 Story 一个 Ralph 迭代（单 context window 可完成），预计 4 次迭代。

> 生成完毕。可运行 `/ralph` 将本 PRD 转换为 `prd.json` 供 Ralph 自动循环消费。建议先解决「待确认问题」1-3（影响步骤定义与核心交互）再转 prd.json。
