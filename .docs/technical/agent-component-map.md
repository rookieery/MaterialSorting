# 前端组件 / 模块地图（materialSorting-web/）

> 由 `/sync-docs` 维护。改前端先看这里。当前覆盖 US-001 Tab 框架 + US-002 WS 契约 + US-003 NestSVG + US-004 ControlPanel + US-005 多 seed/收敛曲线 + US-006 回放 seekbar + 片 hover tooltip + US-007 导出 PNG/DXF + DXF 上传预览 US-001 Tab 骨架 + 上传预览 US-005 类型/store/hook + 上传预览 US-006 UploadPanel 组件 + 上传预览 US-007 PiecePreviewSVG 命令式渲染 + 上传预览 US-008 SizeTabs/ParsedPiecesView/PreviewPage 容器集成 + 上传预览 US-011 qtyStore 数量状态（per-size/global 双模式）+ 上传预览 US-012 PieceQtyDialog/Switch（数量编辑弹窗 + 受控开关）+ 上传预览 US-013 PieceZoomModal（放大预览模态）+ 上传预览 US-014 ParsedPiecesView 卡片头改造 + 双模态集成（seq(qty) 替裁片名 + qty/zoom 双入口 + reset 联动）+ US-015 uiStore 扩 nestingEnabled + TabBar 置灰（超排 Tab 解锁闸）+ US-016 PreviewPage 联动 setNestingEnabled（subscribe uploadStore → uiStore 解锁/锁定超排 Tab）+ US-018 PerTypeOverridesModal/PtypePreviewModal（高级配置弹窗 + 片型缩略图 + 放大预览，双层独立 ESC）+ US-021 useCommitToNesting（解析成功自动 commit + D1 闭环 setNestingEnabled+setTab）+ US-022 求解输入数量 demand per-size（qtyStore.hydrateDefaults + serializeQuantities + StartPayload.quantities）+ US-024 NestSVG 5 层渲染 + 共享 LAYER5_COLORS（毛版+净版+内部线+刺口+布纹线，仅渲染透传不参与 NFP 碰撞）。

## 顶层结构

```
materialSorting-web/
├── index.html              # Vite 入口（dev: /, prod: 被 build 覆写到 static/index.html）
├── package.json            # scripts: dev / build / preview / typecheck / test
├── vite.config.ts          # base 切换（dev '/' / build '/static/'）+ proxy /export /api /ws（US-009 加 /api）
├── vitest.config.ts        # US-002 起：jsdom + globals，独立于 vite.config.ts
├── tsconfig.json           # src/ strict TS（target ES2020, jsx react-jsx）
├── tsconfig.node.json      # vite.config.ts 单独编译（composite）
├── src/                    # 源码（US-008 起：legacy/ 已删除，src/ 是唯一真相源）
│   ├── main.tsx            # createRoot(<StrictMode><App/></StrictMode>)
│   ├── App.tsx             # US-001 Tab 骨架：TabBar + 双 .page 容器（display:none 切换）+ Tooltip 单例
│   ├── style.css           # 由 vanilla 前身 1:1 迁入；US-001 加 .tabbar/.tab/.page/.hidden/.preview-empty；US-006 加 .upload-panel/.drop-zone/.upload-status；US-007 加 .piece-preview-svg；US-008 加 .preview-page/.preview-main/.size-tabs/.size-chip/.parsed-pieces-view/.piece-grid/.piece-card*；上传预览 US-012 加 .piece-qty-dialog-overlay/.piece-qty-dialog-modal/.qty-input-group/.qty-step/.qty-input/.switch/.switch-track/.switch-label-*/.switch-thumb/.qty-btn/.qty-confirm；上传预览 US-013 加 .piece-zoom-overlay/.piece-zoom-modal/.piece-zoom-head/.piece-zoom-seq/.piece-zoom-meta/.piece-zoom-name/.piece-zoom-close/.piece-zoom-body；上传预览 US-014 改 .piece-card-name→.piece-card-qty(+.disabled) + .piece-card-body 加 cursor:zoom-in；US-018 加 .per-type-wrapper/.per-type-btn/.per-type-overlay(z=1100)/.per-type-modal/.per-type-head/.per-type-close/.per-type-table-wrap/.per-type-table/.per-type-rowhead(sticky)/.ptype-col/.ptype-thumb(64×64 zoom-in)/.ptype-name/.per-type-hint/.per-type-actions/.per-type-btn-cancel/.per-type-btn-confirm + .ptype-preview-overlay(z=1200)/.ptype-preview-modal/.ptype-preview-head/.ptype-preview-name/.ptype-preview-close/.ptype-preview-body/.ptype-preview-empty
│   ├── vite-env.d.ts        # vite/client 类型引用
│   ├── types/              # US-002：纯数据契约（与 server.py 字段名 1:1）；上传预览 US-005：parsed.ts；上传预览 US-011：qty.ts；US-018：ptype.ts（PtypeRepresentative + PtypesResponse，GET /api/ptypes 契约）
│   ├── constants/          # US-004：SIZES / PHASE_COLORS / SEED_COLORS / V03_TABLE
│   ├── lib/                # US-002 起：纯函数工具（ws / geometry / params）；US-007 download
│   ├── store/              # US-002 RunRegistry + US-003 appStore + US-001 uiStore（US-015 扩 nestingEnabled + setNestingEnabled + setTab guard）；上传预览 US-005 uploadStore（US-021 扩 commitStatus/commitError/commitSummary）；上传预览 US-011 qtyStore（+clampQty+getPieceDisplay 纯函数；US-022 加 hydrateDefaults sizes×labels 交叉积版）；US-018 controlPanelStore（modal + previewPtype 双显隐字段，两层独立）
│   ├── hooks/              # US-002 起：useSolveRun（US-022 StartConfig 加 quantities 透传）/ useRafThrottle；US-007 useExport；上传预览 US-005 useParseDxf（US-021 解析成功自动 void commit）；上传预览 US-021 useCommitToNesting（POST /api/commit-to-nesting + D1 闭环 setNestingEnabled，不自动切 Tab）
│   ├── components/
│   │   ├── TabBar.tsx       # US-001 顶部 Tab（排料/上传预览）；订阅 uiStore.activeTab；US-015 超排 button 在 nestingEnabled===false 时 disabled+.disabled class + aria-disabled
│   │   ├── NestingPage.tsx  # US-001 排料页（原 App.tsx 业务逻辑外提；持 solving/seeds/useSolveRun）
│   │   ├── preview/         # US-001 起：上传预览页（US-006 UploadPanel；US-007 PiecePreviewSVG；US-008 落地 SizeTabs/ParsedPiecesView/PreviewPage 容器集成）
│   │   │   ├── PreviewPage.tsx  # US-008 容器：左 UploadPanel + 右（SizeTabs+ParsedPiecesView）；status=done+doc 时挂主体，否则 .preview-empty 空态；US-014 顶层挂 PieceQtyDialog+PieceZoomModal 单例 + useEffect subscribe 监听 doc_id 变化联动 qtyStore.resetQuantities（重传清零）；US-016 加 useEffect subscribe uploadStore.status 按 `status==='done' && doc!==null` 联动 uiStore.setNestingEnabled（Tab 解锁闸，mount 即对齐）
│   │   │   ├── UploadPanel.tsx  # US-006 左侧上传面板（点击+拖拽+客户端预校验+status 反馈）；US-021 加 commit 状态行（committing→「应用中…」/ done→「已应用至超排：N 裁片，M 码」/ error→「应用失败：msg」）
│   │   │   ├── SizeTabs.tsx  # US-008 尺码切换条：读 uploadStore.doc/activeSize/setSize；chip 行 + active 高亮；null 码→「通用」
│   │   │   ├── ParsedPiecesView.tsx # US-008 当前 activeSize 下裁片 grid；US-014 改造卡片头为 [A徽章]+序号(数量)（editable=button→openQtyDialog / global非source=span.disabled+title）；.piece-card-body onClick→openZoom + role=button + tabIndex + Enter/Space；序号=pieces index+1；数量从 qtyStore.getPieceDisplay 读
│   │   │   ├── PiecePreviewSVG.tsx  # US-007 单片（或多片）母版预览 SVG（命令式渲染 + scale(1,-1) 翻转 + 5 层分层 + A/B/C 标注翻转组外）
│   │   │   ├── Switch.tsx  # US-012 受控开关（role=switch + aria-checked；PieceQtyDialog 内「仅当前尺码/全部尺码」用）
│   │   │   ├── PieceQtyDialog.tsx  # US-012 数量编辑弹窗（草稿+确定模式；Portal 到 body；ESC/遮罩/取消丢弃草稿；确定调 setPieceGlobal/setPiecePerSize）
│   │   │   ├── PieceZoomModal.tsx  # US-013 放大预览模态（声明式受控 Portal；订阅 uploadStore.zoom+doc；✕/遮罩/ESC 关闭；复用 PiecePreviewSVG pad=20）
│   │   │   └── __tests__/
│   │   │       ├── UploadPanel.test.tsx      # US-006 集成测试（25 项）；US-021 更新 2 项 fetch 计数（parse+commit=2）+ beforeEach/afterEach 加 uiStore reset
│   │   │       ├── PiecePreviewSVG.test.tsx  # US-007 单测（33 项：bbox 5 + 命令式 2 + 5 层 11 + 翻转/标注 9 + 单片/多片/空片 4 + 切片重建 3）
│   │   │       ├── SizeTabs.test.tsx         # US-008 单测（8 项：chip 列表 + null→通用 + role=tablist + active 高亮 + 点击 setSize + null 码 + activeSize=null 防御）
│   │   │       ├── ParsedPiecesView.test.tsx # US-008 单测（8 项基础：grid 渲染 + 每片含 A/B/C+序号(数量)+svg + key label-name + 切码刷新 + activeSize 不在 doc + 空码空态）+ US-014 增 11 项（序号 index+1 / qty 默认 0 / qty 从 qtyStore / editable button openQtyDialog / global非source span.disabled+title / global source 仍 button / body onClick openZoom / role+tabIndex / Enter / Space / qty stopPropagation）
│   │   │       ├── PreviewPage.test.tsx      # US-008 集成（9 项基础：左 panel+右 main 布局 + 4 空态分支 + 已解析挂主体 + SizeTabs 列码 + 切码刷新 grid + 端到端 chip 点击）+ US-014 增 7 项（默认模态不渲染 / qtyDialog 自显隐 / zoom 自显隐 / reset 联动清 / 重传清 / 切码保留 / 端到端切码→qty→global→切回→置灰 title）+ US-016 增 8 项（mount idle→false / done→true / error→false / reset→false / 重传 doc_id 变化短暂 false 后 true / 关键不变量 setNestingEnabled(false) 不强制切 Tab / uploading→false / 状态机循环 done→uploading→error→done）
│   │   │       ├── Switch.test.tsx           # US-012 单测（5 项：role+aria-checked / 点击 onChange true/false / labelOn/labelOff 文案 / disabled 不触发 / .on class）
│   │   │       ├── PieceQtyDialog.test.tsx   # US-012 集成（15 项：null 不渲染 / 标题含 label+size / 初值 per-size/global / [+][-] 改 draftQty / Switch 切 / 确定 per-size/global / 取消 / 遮罩 / ESC / modal 不冒泡 / blur clamp）
│   │   │       └── PieceZoomModal.test.tsx   # US-013 集成（14 项：zoom=null 不渲染 / doc=null 不渲染 / 渲染 overlay+modal+aria / 头部 label+seq(qty)+size+name / qty 从 qtyStore / null 码「通用」/ body svg.piece-preview-svg / ✕ closeZoom / 遮罩 closeZoom / modal 内不冒泡 / ESC closeZoom / Portal body / label 不存在兜底 / size 不存在兜底）
│   │   ├── nests/          # US-003 NestSVG/NestCard/NestLabel + US-005 NestsGrid；US-006 NestSVG 加 seek+hover
│   │   ├── ControlPanel/   # US-004 8 子组件 + US-005 MultiSeedControls；US-007 ExportButtons；US-018 PerTypeOverrides 改按钮 + PerTypeOverridesModal/PtypePreviewModal（高级配置弹窗 + 片型缩略图 + 放大预览）
│   │   ├── curve/          # US-005 ConvergenceCurve（命令式 innerHTML）
│   │   ├── playback/       # US-006 PlaybackBar/Seekbar/SeekReadout
│   │   └── Tooltip.tsx     # US-006 片 hover tooltip（Portal 到 body）
│   └── __tests__/          # US-002 起：vitest 单测；US-001 加 App 集成 smoke + TabBar/uiStore 单测
└── static/                 # npm run build 产物（US-008 起 gitignore；被 FastAPI mount 到 /static）
    ├── index.html
    └── assets/index-[hash].{js,css}
```

## dev / prod 双路径

| | dev | prod |
| --- | --- | --- |
| 入口 | `npm run dev` → `localhost:5173` | `npm run build` 后由 `ms-web` (:8000) serve |
| base | `/`（Vite 默认） | `/static/`（FastAPI mount 路径） |
| 前端如何打后端 | 相对路径 `/export` `/api/*` `/ws/solve`，由 Vite proxy → `127.0.0.1:8000` | 同源 `127.0.0.1:8000/export` `/api/*` `/ws/solve`（无需 proxy） |
| 验证命令 | `curl localhost:5173/`、Python websockets 连 `ws://localhost:5173/ws/solve` | `curl 127.0.0.1:8000/`、`curl -I 127.0.0.1:8000/static/assets/index-*.js` |

## vite.config.ts 关键点

- `base` 由 `command` 决定：`build` → `/static/`，否则 `/`。**勿改成静态值**，否则 dev 或 prod 之一会断。
- `build.outDir = 'static'`、`emptyOutDir = true` —— 每次构建清空 `static/` 后重写。
- `server.proxy['/ws'] = { target, ws: true, changeOrigin: true }` —— **`ws: true` 必填**，否则 WS 升级请求会被 Vite 当普通 HTTP 处理返回 404。
- `server.proxy['/api'] = { target, changeOrigin: true }`（US-009）—— dev 下转发 `/api/parse-dxf` 等到后端 :8000；prod 同源无需 proxy。
- `server.strictPort = true` —— 锁死 :5173，便于后端 / 文档稳定引用。

## tsconfig 两文件分工

- `tsconfig.json`（include `src`）：app 代码 strict 模式，`noEmit` + `moduleResolution: bundler`，`jsx: react-jsx`（不需要 `import React`）。**`noUnusedLocals` / `noUnusedParameters` 都开**，未用的 import / 形参会直接报错 —— 测试文件同样受此约束。
- `tsconfig.node.json`（include `vite.config.ts`，`composite: true`）：被 `tsconfig.json` 通过 `references` 引用，独立检查配置文件。

## US-001 落地：顶部 Tab 框架 + NestingPage 外提

| 文件 | 角色 |
| --- | --- |
| `src/store/uiStore.ts` | Zustand 双字段 store：`activeTab: 'nesting' \| 'preview'`（默认 `'preview'`）+ `nestingEnabled: boolean`（默认 `false`，US-015）；actions `setTab(tab)`（**nestingEnabled===false 时 setTab('nesting') 静默不切**）+ `setNestingEnabled(b)`。求解/WS/seek 等业务状态仍在各 page 内 |
| `src/components/TabBar.tsx` | 顶部 Tab 切换：`<nav class="tabbar">` + 两 `<button class="tab">`（超排 / 上传预览）；点击 setTab；active 项加 `.active` class + `aria-pressed=true`。**US-015**：超排 button 在 `nestingEnabled===false` 时 native `disabled` + `.disabled` class + `aria-disabled=true`；onClick 运行时再判一次（双重防御） |
| `src/components/NestingPage.tsx` | 排料工作台页（原 App.tsx 业务逻辑外提）：持 `seeds/solving/status/doneCountRef/totalSeedsRef` + `useSolveRun({onDone})` + `useRafThrottle(seeds.length>0)`；渲染 `<ControlPanel>` + `<main class="main">`；不挂 Tooltip（Tooltip 由父 App 渲染）；US-022 handleStart 透传 cfg.quantities 到 start()（N seed 共用） |
| `src/components/preview/PreviewPage.tsx` | 上传预览页（**US-008 落地**）：左 UploadPanel + 右（SizeTabs+ParsedPiecesView）双栏；`hasParsed = status==='done' && doc!==null` 决定挂主体 or `.preview-empty` 空态 |
| `src/App.tsx` | 顶层骨架：渲染 `<TabBar>` + `<div class="tab-content">` 双 `.page` 容器（display:none 切换）+ `<Tooltip>`（单例，Portal 到 body） |
| `src/style.css` | 增 `.app{flex-direction:column}` + `.tabbar/.tab/.tab.active` + `.tab-content/.page/.page.hidden` + `.preview-empty/.preview-empty-card`（暗色与 ControlPanel 同色系）；**US-015** 加 `.tab.disabled` + `.tab.disabled:hover`（#555 灰字 + not-allowed） |
| `src/store/__tests__/uiStore.test.ts` | 9 项单测：US-001 基础 4（默认 preview / setTab 切换 / 切回 / 订阅者通知）+ US-015 新增 5（默认 nestingEnabled=false / setNestingEnabled 切换 / 订阅者通知 / **setTab('nesting') 在 false 时静默不切**（关键不变量）/ setTab('preview') 在 false 时仍可切） |
| `src/components/__tests__/TabBar.test.tsx` | 9 项单测：US-001 基础 5（DOM 结构 nav+2button / 默认 active / 点击切 store / 切回 / 顺序固定）+ US-015 新增 4（disabled 点击不调 setTab / disabled 视觉 .disabled+aria-disabled+native disabled / 启用后正常切换 / nestingEnabled 切换时 TabBar 重渲染） |
| `src/__tests__/App.test.tsx` | 7 项集成 smoke：tabbar+2tab / 默认 nesting 页可见含 ControlPanel+main / 切 preview nesting 加 .hidden 但 DOM 仍在（不卸载）/ 切回对称 / Tooltip 单例仍 Portal body / 点击 tab 端到端；US-015 beforeEach 加 `setNestingEnabled(true)` 兜底 store guard；**US-016** beforeEach 加 `useUploadStore.setState({status:'done', doc:makeParsedDoc()})` 让 PreviewPage mount 时的 US-016 联动 effect 把 nestingEnabled 对齐到 true（否则 PreviewPage 一 mount 就会 idle→false 把 beforeEach 的解锁覆盖回 false），afterEach 同步 reset uploadStore + uiStore；「默认 preview」测试用例显式 reset uploadStore 到 idle 验证 `.preview-empty`，「切到 preview」测试用例把断言从 `.preview-empty` 改为 `.preview-page`（已上传状态下不再走空态分支） |

### 关键不变量（US-001 立，后续故事不得破坏；US-015 扩 #2 #5；US-016 扩 #2 #5 #8）

1. **双页面常驻 DOM，display:none 切换** —— `.page.hidden { display: none }` 而非条件渲染 / 路由卸载。切回排料页时 NestingPage 内 `useState/useRef/runRegistry` 全部保真，进行中的求解 / WS 连接 / 播放 seek 不中断。改 `display:none` 策略为「条件渲染」会破坏此保证。
2. **uiStore 双字段（US-015 扩）** —— `activeTab: 'nesting' \| 'preview'`（默认 `'preview'`）+ `nestingEnabled: boolean`（默认 `false`，**US-016 由 PreviewPage subscribe uploadStore 联动**：`status==='done' && doc!==null` → true，其它 → false）；不混入 solving/seeds/seek 等业务状态（业务状态由 NestingPage 自治）。改 store 形状需同步 9 项 uiStore.test.ts。**关键不变量（US-015）**：`setTab('nesting')` 在 `nestingEnabled===false` 时**静默不切**（store 层兜底）；`setTab('preview')` 永远允许（用户随时可回上传预览页）。
3. **TabBar 只切 store，不直接切 DOM** —— `<button onClick=setTab>`；显隐由 App 订阅 `activeTab` 后切 `.hidden` class。解耦：未来加 URL hash 同步只需改 App 一处。
4. **Tooltip 单例仍挂 App** —— US-006 关键约定 #3 不破：Tooltip 是模块级单例，App 内只能挂一个；NestingPage 不挂 Tooltip。
5. **Tab 顺序固定：超排在前、上传预览在后**（默认入口是 `'preview'`，US-015/016 前提下未上传解析时无法点入超排），TABS 数组顺序不可改。
6. **TabBar 视觉沿用 style.css** —— 不引入 CSS 框架；`.tabbar/.tab` 暗色（`#26282e`）与 ControlPanel 同色系；active 项用绿色 `#2ea06c` border-bottom 强调（与 StartButton `#2ea06c` 同色）。**US-015**：`.tab.disabled` 用 `#555` 灰字 + `cursor:not-allowed`（含 `:hover` 同色防 hover 提亮）。
7. **NestingPage 用 Fragment** —— 直接把 ControlPanel + main 作为 `.page` flex 子元素，不再包一层 `.app`（避免冗余 DOM + flex 嵌套层）。
8. **超排 Tab 解锁闸双重防御（US-015）** —— TabBar `disabled` 属性（native）兜底 a11y / 键盘 tab 序列；运行时 `if (disabled) return`（JS）兜底合成事件 / devtools 旁路；store `setTab` guard 第三层兜底直调 store 的 JS 旁路。三层任一生效即可保证不可点。**US-016 加业务层联动**：PreviewPage subscribe uploadStore.status → setNestingEnabled(`done && doc`)，让「未上传母版」时超排 Tab 自然锁定（业务语义闸）。四层共同保证「未上传不可点 + 已上传自动解锁」。

## US-015 落地：uiStore 扩 nestingEnabled + TabBar disabled 态（超排 Tab 解锁闸）

| 文件 | 角色 |
| --- | --- |
| `src/store/uiStore.ts` | **扩字段** `nestingEnabled: boolean`（默认 `false`）+ action `setNestingEnabled(b)`；`setTab` 内加 guard：`tab==='nesting' && !get().nestingEnabled` 时 `return`（静默不切）。`create<UiState>((set, get) => ({...}))` 引入 `get` 读 nestingEnabled |
| `src/components/TabBar.tsx` | 超排 button 在 `nestingEnabled===false` 时：`className` 加 `disabled` + native `disabled={true}` + `aria-disabled={true`；onClick 内 `if (disabled) return`（双重防御）。上传预览 button 不受影响（永远可点） |
| `src/style.css` | 加 `.tab.disabled { color:#555; cursor:not-allowed; }` + `.tab.disabled:hover { color:#555; }`（暗色系 #555 灰字，与 ControlPanel 同色系不冲突；防 hover 提亮） |
| `src/store/__tests__/uiStore.test.ts` | 新增 5 项：默认 nestingEnabled=false / setNestingEnabled(true/false) 切换 / 订阅者收到 nestingEnabled 变化 / **setTab('nesting') 在 false 时静默不切**（关键不变量，含「解锁后才生效」分支）/ setTab('preview') 在 false 时仍可切（不锁定退出） |
| `src/components/__tests__/TabBar.test.tsx` | 新增 4 项：disabled 点击不调 setTab（关键不变量）/ disabled 视觉有 `.disabled` + `aria-disabled=true` + native `disabled=true` / 启用后正常切换（点击切 activeTab=nesting）/ nestingEnabled 切换时 TabBar 重渲染（false→true 移除 disabled，true→false 加回） |
| `src/__tests__/App.test.tsx` | beforeEach 加 `setNestingEnabled(true)` 后再 `setTab('nesting')`（绕过 store guard 保持原测试意图）。**US-016 后**：beforeEach 还需 `useUploadStore.setState({status:'done', doc})` 让 PreviewPage mount 时的联动 effect 不把 nestingEnabled 对齐回 false（详见 US-016 段） |

### 关键不变量（US-015 立，后续故事不得破坏）

1. **`setTab('nesting')` 在 `nestingEnabled===false` 时静默不切（关键不变量）** —— store 层 guard 兜底所有 JS 调用方（TabBar / PreviewPage 集成 / 未来 URL hash 同步）。`setTab('preview')` 永远允许（用户随时可回上传预览页，不强制留在 nesting）。改 guard 需同步 uiStore.test.ts 「setTab(nesting) 在 false 时静默不切」+「setTab(preview) 在 false 时仍可切」两项。
2. **三层双重防御**：TabBar `disabled` 属性（native，a11y / 键盘 tab 序列）→ TabBar `onClick` 内 `if (disabled) return`（合成事件 / devtools 旁路）→ store `setTab` guard（直调 store 的 JS 旁路）。任一层失效不影响整体不可点保证。
3. **`nestingEnabled` 默认 `false`，由 PreviewPage 联动 setNestingEnabled(true)（US-016）** —— store 默认锁定，业务层（PreviewPage useEffect subscribe uploadStore.status）负责解锁。改默认值会破坏「未上传母版时超排 Tab 不可点」语义。
4. **上传预览 Tab 永远可点** —— 用户随时可回上传预览页（reset / 重传 / 切码），不被锁定。TabBar 渲染时 `disabled = t.id === 'nesting' && !nestingEnabled`（preview 永远 false）。
5. **`aria-disabled` + native `disabled` 同步** —— 屏幕阅读器 + 键盘序列双重 a11y。改其中一项需同步另一项（避免分裂）。
6. **不引入 CSS 框架** —— `.tab.disabled` / `.tab.disabled:hover` 沿用 style.css 命令式 className；与 ControlPanel / TabBar active 同色系（暗背景 `#26282e` + `#555` 灰字），不引入 CSS 框架。

## US-016 落地：PreviewPage 联动 setNestingEnabled（subscribe uploadStore → uiStore 解锁闸）

| 文件 | 角色 |
| --- | --- |
| `src/components/preview/PreviewPage.tsx` | **新增 useEffect**：subscribe `useUploadStore`，按 `status==='done' && doc!==null` 调 `useUiStore.getState().setNestingEnabled(next)`；mount 时立即对齐初值（idle → false）。覆盖路径：idle/uploading（false）/ done+doc（true）/ error（false）/ reset（doc→null false）/ 重传（status=uploading 短暂 false，done 后切回 true）。调用前先判 `get().nestingEnabled !== next` 避免无谓 setState。与 US-014 qtyStore 联动 effect 同模式（subscribe + mount 即对齐 + 卸载 unsub），两 effect 独立、互不干扰 |
| `src/components/preview/__tests__/PreviewPage.test.tsx` | **新增 8 项**：mount idle→false（污染 true 验证对齐）/ done+doc→true / error（done 后切 error）→false / uploadStore.reset()→false / 重传 doc_id 变化（done→uploading→done with new doc_id）短暂 false 后 true / 关键不变量：setNestingEnabled(false) 不强制切 Tab（用户在 nesting Tab 时 reset，activeTab 仍是 nesting）/ uploading→false（mount 即对齐）/ 状态机循环 done→uploading→error→done。beforeEach 加 `useUiStore.setNestingEnabled(false) + setTab('preview')`，afterEach 同步重置（避免残留） |
| `src/__tests__/App.test.tsx` | **beforeEach 改造**：除原 `setNestingEnabled(true) + setTab('nesting')` 外，加 `useUploadStore.setState({status:'done', doc:makeParsedDoc()})` 让 PreviewPage mount 时的 US-016 联动 effect 不把 nestingEnabled 对齐回 false（否则 beforeEach 设的 true 会被 PreviewPage mount 立即覆盖回 false，导致 `setTab('nesting')` 失效）。**afterEach 新增**：reset uploadStore + setNestingEnabled(false) + setTab('preview') 兜底无残留。「默认 activeTab=preview」测试用例显式 reset uploadStore 到 idle 验证 `.preview-empty`；「切到 preview」测试用例把 `.preview-empty` 断言改为 `.preview-page`（已上传状态下不再走空态分支） |

### 关键不变量（US-016 立，后续故事不得破坏）

1. **联动公式 `next = status==='done' && doc!==null`** —— 严格反映「有可用解析数据」语义。idle/uploading/error/reset 都返回 false，只有 done 且 doc 非空才解锁。改公式需同步 PreviewPage.test.tsx 8 项 US-016 用例。
2. **mount 即对齐** —— PreviewPage mount 时立即按当前 uploadStore.status 计算 next 调 setNestingEnabled（迟到挂载 / 刷新恢复兜底；App.test.tsx beforeEach 必须 set uploadStore done+doc 同步，否则 PreviewPage mount 会把 beforeEach 设的 true 覆盖回 false）。
3. **关键不变量（AC#3）：setNestingEnabled 仅控 Tab「能否进入」，不强制切 Tab** —— `uiStore.setNestingEnabled(b)` 实现仅 `set({ nestingEnabled: b })`，不触碰 activeTab。故用户已在 nesting Tab 时 reset（doc→null → setNestingEnabled(false)），activeTab 仍是 nesting，preview Tab 仍可点回（preview 永远可点）但**不强制切回**，避免丢失求解状态。改 setNestingEnabled 副作用（如加 setTab('preview')）会破坏此不变量。
4. **uiStore 与 uploadStore 解耦（与 qtyStore 同设计原则）** —— uploadStore 不知道 uiStore 存在；uiStore 不知道 uploadStore 存在。PreviewPage 作为集成层用 subscribe 绑定（与 US-014 qtyStore 联动同模式）。改耦合（如把 setNestingEnabled 调用挪到 uploadStore 内）会破坏 store 解耦原则。
5. **subscribe + mount 即对齐 + 卸载 unsub（与 US-014 qtyStore 联动 effect 同模式）** —— subscribe 捕获所有 state 变化（包括不触发 re-render 的 setState）；mount 时立即读 getState() 对齐初值；unmount 时 unsub 无残留。PreviewPage 现有两份 useEffect（qtyStore 联动 / uiStore 联动）独立、互不干扰。改 effect 结构需同步 PreviewPage.test.tsx。
6. **调用前先判 `get().nestingEnabled !== next`** —— 避免无变化时无谓 setState 触发订阅者通知（zustand 内部 Object.is 也会兜底，但显式判断更省一次 set 调度）。改判断逻辑需同步 8 项 US-016 用例（不直接断言 call count，但通过「关键不变量」用例间接验证）。
7. **App.test.tsx beforeEach 必须 set uploadStore done+doc** —— App mount 会触发 PreviewPage mount，PreviewPage 的 US-016 effect 会按当前 uploadStore.status 对齐 nestingEnabled。若 uploadStore=idle，beforeEach 设的 nestingEnabled=true 会被覆盖回 false，导致 `setTab('nesting')` 失效。改 beforeEach 需同步 App.test.tsx 7 项集成用例。
8. **未做浏览器验证** —— 本故事无 SVG/坐标变换（仅 store 联动 + setState），AC 仅要求 typecheck + 单测，故跳过 chrome-devtools-mcp；浏览器视觉回归（disabled 灰字 + cursor:not-allowed 随 status 切换）留作 US-021 自动 commit 集成时统一核对（届时 done→commit→解锁 nesting Tab 端到端联调）。

## US-018 落地：PerTypeOverridesModal + PtypePreviewModal（高级配置弹窗 + 片型缩略图 + 放大预览）

把旧版 PerTypeOverrides 的 `<details>` 折叠面板（10 行 d/tol input + 内/外徽章）改造为「按钮 → 弹窗 table + 片型缩略图 + 放大预览」两层模态。表头列=片型缩略图（compact 渲染）+ 片型名（不含内外徽章 —— US-019 移除内外区分），两行=重合/旋转；缩略图点击触发放大预览（PtypePreviewModal 叠在 PerTypeOverridesModal 之上）。缩略图数据源 = `GET /api/ptypes`（US-020），fetch 失败降级为片型名文字（不阻塞配置）。

### 新增 / 改造文件

| 文件 | 角色 |
| --- | --- |
| `src/store/controlPanelStore.ts` | **新建** Zustand store：`modal: 'per_type' \| null` + `previewPtype: string \| null` + actions（openModal/closeModal/openPreviewPtype/closePreviewPtype）。两层 state 独立（closeModal 不影响 previewPtype / closePreviewPtype 不影响 modal）；订阅 modal/previewPtype 自显隐 |
| `src/types/ptype.ts` | **新建** `PtypeRepresentative` + `PtypesResponse` 类型（与后端 `_PTYPE_REPRESENTATIVE_FIELDS` 字段一致）。v1 仅 polygon 字段必填；US-024 后 intermediate 扩 5 层 → representatives 自动带 net_polygon/internal_lines/notches/grain_line（前端 layer-aware 渲染） |
| `src/components/ControlPanel/PerTypeOverrides.tsx` | **改造**：旧 `<details>` 折叠 10 行 d/tol input → 单行 `<button class="per-type-btn">` 触发器。保留 values/onChange 契约（透传给 PerTypeOverridesModal）；内部挂 PerTypeOverridesModal + PtypePreviewModal（声明式受控 Portal 订阅 controlPanelStore） |
| `src/components/ControlPanel/PerTypeOverridesModal.tsx` | **新建** 高级配置弹窗（声明式受控 Portal → document.body；订阅 controlPanelStore.modal）。结构：head(标题+✕) + table-wrap(overflow-x:auto) + actions(取消/确定)。表格 thead 10 列（缩略图 64×64 + 片型名）+ tbody 2 行（重合 input + 旋转 input）。挂载时 fetch GET /api/ptypes（mockImplementation 模式，StrictMode 双 mount 安全）。草稿+确定（D7 预填：INTERNAL_TYPES=10/0，其余 0/0）。缩略图点击 openPreviewPtype(ptype)。双层 ESC 独立（previewPtype!==null 时本组件 ESC 不关） |
| `src/components/ControlPanel/PtypePreviewModal.tsx` | **新建** 片型放大预览模态（订阅 controlPanelStore.previewPtype）。常驻 ControlPanel 顶层，fetch /api/ptypes 一次缓存。previewPtype !== null 时显示 overlay+modal（aria-modal）； PiecePreviewSVG pad=20 全量渲染（layer-aware）；ESC 始终只关 previewPtype（独立于 PerTypeOverridesModal）；representative 缺失渲染降级空态 |
| `src/components/preview/PiecePreviewSVG.tsx` | **新增 `compact?: boolean` prop**：compact=true 时跳过 renderLabel（A/B/C 标注）+ 默认 pad 改为 COMPACT_PAD(2)（fit-to-cell）；显式 pad 仍优先。layer-aware 渲染不变（数据带几层画几层）；非 compact 行为不变（向后兼容 PieceZoomModal pad=20） |
| `src/style.css` | **新增样式段**：`.per-type-wrapper/.per-type-btn`(蓝色按钮 #2c5d8f) + `.per-type-overlay/.per-type-modal/.per-type-head/.per-type-close/.per-type-table-wrap/.per-type-table/.per-type-rowhead(sticky)/.ptype-col/.ptype-thumb(64×64 zoom-in)/.ptype-thumb-placeholder/.ptype-name/.per-type-table input/.per-type-hint/.per-type-actions/.per-type-btn-cancel/.per-type-btn-confirm` + `.ptype-preview-overlay/.ptype-preview-modal/.per-type-preview-head/.ptype-preview-name/.ptype-preview-close/.ptype-preview-body/.ptype-preview-empty`（z-index 1100 per-type / 1200 ptype-preview，暗背景 #26282e + #2ea06c 同色系，与 PieceQtyDialog/PieceZoomModal 一致） |
| `src/store/__tests__/controlPanelStore.test.ts` | **新建** 7 项单测：默认 null / openModal-closeModal / openPreviewPtype-closePreviewPtype / 订阅者收到 modal 变化 / 订阅者收到 previewPtype 变化 / 两层 state 独立（closeModal 不影响 previewPtype）/ 两层 state 独立（closePreviewPtype 不影响 modal） |
| `src/components/ControlPanel/__tests__/PerTypeOverridesModal.test.tsx` | **新建** 19 项集成测试：modal=null 不渲染 / modal=per_type 渲染 overlay+modal+aria-label / thead 10 列片型名（无内外徽章）/ tbody 2 行（重合+旋转）/ 挂载 fetch /api/ptypes / fetch 失败降级片型名 / fetch 成功渲染 2 个 compact svg（前片+后片）/ 初值 D7 预填（单排=10/0，前片=0/0）/ 初值保留 form.per_type 非空值 / 编辑 draft 不立即回写 / 确定回写+关闭 / 取消丢弃 / 遮罩关闭 / ESC 关闭（previewPtype=null 时）/ ESC 不双层关闭（previewPtype!==null 时只关预览，底层 modal 保留）/ ✕ 关闭 / 点击缩略图 openPreviewPtype / placeholder 提示 d≤X/t≤Y / modal 内 mousedown 不冒泡 |
| `src/components/ControlPanel/__tests__/PtypePreviewModal.test.tsx` | **新建** 7 项集成测试：previewPtype=null 不渲染 / previewPtype + fetch 成功渲染 overlay+modal+svg / ✕ 关闭 / 遮罩关闭 / ESC 关闭（独立于底层 modal）/ 叠层场景（与 PerTypeOverridesModal 同挂）ESC 只关预览 + 底层 modal+草稿保留 / representative 缺失渲染降级空态 |
| `src/components/preview/__tests__/PiecePreviewSVG.test.tsx` | **新增「compact 模式」5 项**：compact=true 跳过 A/B/C 标注 / compact=true pad=COMPACT_PAD(2) viewBox 紧贴 / compact=true layer-aware 渲染不变（数据带 5 层仍渲染 5 层）/ 默认（compact=false）A/B/C 标注正常（向后兼容）/ compact=true + 显式 pad 优先 |
| `src/components/ControlPanel/__tests__/ControlPanel.test.tsx` | **改造**：原 US-004 「`.per_type .pt-row` 10 行 + 内外徽章」用例 → US-018 「`.per-type-btn` 按钮 + 点开 modal 表头 10 列无徽章」用例；原「fill per_type input」用例 → 「open modal + 编辑 input + 确定 + Start」端到端；beforeEach/afterEach 加 fetch /api/ptypes stub（防 PtypePreviewModal mount 时 act 警告） |

### 关键不变量（US-018 立，后续故事不得破坏）

1. **PerTypeOverrides values/onChange 契约不变** —— ControlPanel 仍 `<PerTypeOverrides values={form.per_type} onChange={(per_type)=>patch({per_type})} />`；US-018 仅把渲染从 `<details>` 改为按钮 + 弹窗，ControlPanel.tsx 无需改动。
2. **PerTypeOverridesModal 草稿 + 确定（与 PieceQtyDialog 同模式）** —— 打开时从 form.per_type + D7 预填初始化 draft（key 强制每次 open 重建）；编辑仅改 draft；确定调 onChange + 关闭；取消/遮罩/ESC 仅关闭、draft 丢弃。改即时回写会破坏 AC#5 草稿语义。
3. **D7 预填：INTERNAL_TYPES 重合=10、旋转=0；其余 0/0** —— 与旧版 DEFAULT_FORM.d_int='10' 行为一致（v1 兜底）；US-019 删两档后 per_type 是唯一源，D7 预填保证开箱密度不暴跌。
4. **缩略图 layer-aware 渲染（D11）** —— v1 representatives 仅 polygon → 缩略图只画外轮廓；US-024 intermediate 扩 5 层后 representatives 自动带 5 层字段，缩略图自动画 5 层（PiecePreviewSVG compact 模式按数据有无渲染，无需改动本组件）。
5. **fetch /api/ptypes 失败降级** —— 表头仍渲染 10 列片型名文字，缩略图按钮 disabled；不阻塞重合/旋转配置。改降级为「整体弹窗关闭」会破坏 AC#4「fetch 失败不阻塞」语义。
6. **两层 modal ESC 独立（AC#10）** —— PerTypeOverridesModal listener 内判 `useControlPanelStore.getState().previewPtype === null` 才关；PtypePreviewModal listener 始终只关 previewPtype。改双层同时关会破坏「放大预览打开时 ESC 只关预览」语义。
7. **z-index 层级：tooltip(100) < piece-qty/piece-zoom(1000) < per-type(1100) < ptype-preview(1200)** —— PtypePreviewModal 叠在 PerTypeOverridesModal 之上；改层级会破坏叠层视觉。
8. **fetch mockImplementation 而非 mockResolvedValue** —— StrictMode 双 mount 会调 2 次 fetch；mockResolvedValue 共享同一 Response 会被首次 .json() 消费完，第二次报 "body stream already read"。测试用 `vi.spyOn(globalThis, 'fetch').mockImplementation(...)` 每次创建新 Response。改 mockResolvedValue 会触发 StrictMode 假失败。
9. **PiecePreviewSVG compact 模式不影响非 compact 调用方** —— PieceZoomModal 仍传 pad=20 默认 compact=false（5 层 + A/B/C 标注正常渲染）；PerTypeOverridesModal 传 compact（无标注、pad 默认 2）；PtypePreviewModal 传 pad=20 默认 compact=false（5 层渲染但无 A/B/C 标注，因 representative 无 label 字段，renderLabel 内 `if (!piece.label) return` 兜底）。改 compact 默认值或副作用会破坏向后兼容。

## 上传预览 US-005 落地：ParsedDoc 类型 + uploadStore + useParseDxf hook

| 文件 | 角色 |
| --- | --- |
| `src/types/parsed.ts` | 上传解析响应契约：`ParsedDoc` / `ParsedSize` / `ParsedPiece` + `ParsedPt` / `ParsedNotch` / `ParsedGrainLine`。与 `web/server.py _build_parse_payload()` 字段名严格一致：`{doc_id, filename, sizes:[{size, pieces:[{label, name, polygon, internal_lines, notches, net_polygon, grain_line}]}]}` |
| `src/store/uploadStore.ts` | Zustand store：`status: 'idle'\|'uploading'\|'done'\|'error'`、`doc: ParsedDoc\|null`、`activeSize: number\|null`、`error: string\|null`、`qtyDialog: {label,size}\|null`（US-012）、`zoom: {label,size}\|null`（US-013）+ actions `reset()` / `setSize(s)` / `openQtyDialog(label,size)`（US-012）/ `closeQtyDialog()`（US-012）/ `openZoom(label,size)`（US-013）/ `closeZoom()`（US-013）。状态过渡（uploading→done\|error）由 hook 直接 `useUploadStore.setState({...})` 写入，不暴露成公开 action |
| `src/hooks/useParseDxf.ts` | 上传 hook：`upload(file)` → POST `/api/parse-dxf` (multipart FormData) → 写 uploadStore。**防连击**：uploadingRef + status==='uploading' 双重防护；成功后默认 activeSize = `doc.sizes[0]?.size ?? null`；不抛错（错误统一进 store.error） |
| `src/store/__tests__/uploadStore.test.ts` | 20 项单测：US-005 基础 7（默认 idle / reset() 从 done+error 回 idle / setSize(number\|null) / 订阅者收到 status & activeSize 变化）+ US-012 qtyDialog 6（默认 null / open 写入 / open null 码 / close 清回 / reset 同步清 / 订阅者通知）+ US-013 zoom 7（默认 null / open 写入 number / open null 码 / close 清回 / reset 同步清 / 订阅者通知 / zoom 与 qtyDialog 字段独立） |
| `src/hooks/__tests__/useParseDxf.test.tsx` | 15 项单测：AC#1 fetch URL=相对+POST+FormData(file)+不手设 Content-Type；AC#2 200→done+doc+activeSize=sizes[0].size / 空 sizes / null 码组；AC#3 400/413/422→error+CN msg / 非 JSON→statusText / 网络错→Error.message / 非 Error→String(e)；AC#4 防连击 fetch 仅一次 / 成功+失败后 uploadingRef 复位 / 进入 uploading 清旧 error |

### 关键不变量（上传预览 US-005 立，后续故事不得破坏）

1. **状态机：idle → uploading → done \| error** —— status 是 UploadPanel 渲染分支的唯一驱动。改状态名 / 增状态需同步 uploadStore.test.ts 7 项 + useParseDxf.test.tsx 15 项。
2. **uploadStore 是单一真相源** —— 与 runRegistry（高频 mutable，不进 state）相反，uploadStore 把 doc/activeSize/error 全部进 React state。解析结果低频，进 store 触发 reconciliation 反而便于 UI 同步。新增字段需在 uploadStore + reset() + useParseDxf setState 三处同步。
3. **状态过渡由 useParseDxf 直接 `useUploadStore.setState({...})`**，不暴露成 store 公开 action。store 公开 API 只含调用方语义动作（reset / setSize），避免业务组件误触发状态跳变。
4. **防连击：uploadingRef + status==='uploading' 双重防护** —— ref 立即生效（async 函数体同步段执行），setState 异步生效，第二次连击会在 setState 调度前进 hook body。两者任一为 uploading 即忽略。改单重防护会回归「连击两次同时 fetch → 后写入者覆盖前者 doc」问题。
5. **FormData 不手设 Content-Type** —— fetch 自动加 `multipart/form-data; boundary=...`；手设会丢 boundary → 后端 python-multipart 解析失败。useParseDxf.test.tsx AC#1 有断言。
6. **响应契约字段名严格与 server.py `_build_parse_payload` 一致** —— 改任一字段需同步后端 server.py + types/parsed.ts + useParseDxf.test.tsx AC#2。
7. **activeSize 默认 = `doc.sizes[0].size ?? null`** —— 后端按数值升序、null 殿后，sizes[0] 是最小码。空 sizes 兜底 null。改默认需同步 useParseDxf.test.tsx 3 项 activeSize 用例。
8. **错误不抛、不 rethrow** —— useParseDxf 内 try/catch 兜底，所有错误（网络错 / JSON 解析错 / 4xx/5xx）统一进 uploadStore.error，UI 自取。返回 Promise\<void\> 仅为调用方可选 await。
9. **doc / activeSize 在失败时不主动清** —— uploading 时清 error 但保留 doc/activeSize（避免切 uploading 时 UI 闪烁）；error 时也只写 status/error。reset() 才彻底清零。

## 上传预览 US-006 落地：UploadPanel 组件（点击 + 拖拽 + 客户端预校验）

| 文件 | 角色 |
| --- | --- |
| `src/components/preview/UploadPanel.tsx` | 左侧上传面板（`.panel.upload-panel`，沿用 ControlPanel 同色系，width:248px）：渲染拖拽落区（`.drop-zone`，全 panel DnD，dragCounter 防抖）+ 隐藏 `<input type=file accept=".dxf">` + 显式按钮（`.upload-btn`）+ 状态反馈块（`.upload-status.{loading,done,error}`）。订阅 uploadStore.status/doc/error；本地 `localError` 持有客户端校验失败消息（与 store.error 互斥展示，本地优先） |
| `src/components/preview/__tests__/UploadPanel.test.tsx` | 25 项集成测试：DOM 结构 / AC#1 点击 drop-zone + upload-btn + Enter/Space 键盘触发 input.click() / uploading 时禁点击；AC#2 非 .dxf / 多文件 / 超 20MB 三种客户端拒绝 + .DXF 大写后缀通过 / 单文件触发 fetch POST /api/parse-dxf / 校验通过清旧 localError / input.value 重置；AC#1 DnD dragenter/dragleave counter / .dragover 切换 / drop 后清除 / 文案切换；AC#3 status 三态 UI + localError 优先 + 端到端成功/失败路径 |

### 关键不变量（上传预览 US-006 立，后续故事不得破坏）

1. **整个 `<aside>` 是拖拽落区，点击触发限定在 drop-zone / button 上** —— dragenter/dragover/dragleave/drop 挂在根元素（用户可落在 panel 任何子元素上松手），但点击触发文件选择只绑定 drop-zone 和 upload-btn（避免点状态文本误触）。改挂载点会破坏 AC#1 panel-wide DnD 语义。
2. **dragCounter 防子元素 dragleave 抖动** —— 浏览器在 panel 子元素间移动会反复触发 dragenter/dragleave，用 ref 计数器保证只在真正离开 panel（counter=0）时清 `.dragover`。直接 toggle boolean 会因抖动出现 `.dragover` 闪烁。
3. **客户端预校验三件套：.dxf 后缀（MIME 容错）+ 单文件 + 20MB** —— 后缀判定用 `name.toLowerCase().endsWith('.dxf')`（不看 file.type，因 Windows 下 MIME 五花八门）；多文件 / 超大直接拦不发请求；20MB 与后端 `server.py UPLOAD_MAX_BYTES` 一致（双校验，前端先拦 + 后端兜底）。改任一项需同步 UploadPanel.test.tsx 3 项 reject 用例。
4. **`localError` 与 `store.error` 互斥展示（本地优先）** —— 客户端校验失败消息进本组件 `useState`，不污染 uploadStore 状态机（hook 仅在 HTTP 流程内切 status）；UI 渲染分支 `displayError = localError ?? (status==='error' ? store.error : null)`。改优先级会破坏 AC#3 错误展示口径。
5. **`e.target.value = ''` 重置 input value** —— 否则选同一文件不触发 change（input value 去重机制），用户重试同一文件会哑火。UploadPanel.test.tsx AC#2 有断言。
6. **状态驱动 UI 分支：status 是唯一驱动** —— uploading 显示 `.upload-status.loading` + 按钮文案 "重新上传" 变 "选择 DXF 文件" + disabled；done 显示文件名 + "已解析 N 码 / M 裁片"（N=doc.sizes.length，M=sum(pieces.length)）；error 显示红字（来自 store.error 或 localError）；idle 不渲染 status 块。改分支需同步 UploadPanel.test.tsx AC#3 9 项用例。
7. **drop-zone + upload-btn 双入口触发同一 handlePickClick** —— 不直接绑到 input.change，而是 click → inputRef.click() → input.change，便于 DnD 与点击共享校验/上传路径（drop 直接进 handleFiles 跳过 input click）。改单一入口会破坏 AC#1 双交互模式。
8. **不引入 CSS 框架** —— `.upload-panel` / `.drop-zone` / `.upload-btn` / `.upload-status` 全部沿用 style.css 命令式 className，与 ControlPanel 暗背景 `#26282e` + 绿色 `#2ea06c` 强调同色系；新增 `.drop-zone.dragover` 用绿色边框高亮，与 StartButton 同色。

## 上传预览 US-007 落地：PiecePreviewSVG 命令式渲染（5 层分层 + scale(1,-1) 翻转 + A/B/C 不镜像）

| 文件 | 角色 |
| --- | --- |
| `src/components/preview/PiecePreviewSVG.tsx` | 单片（或多片，AC#4）母版预览 SVG。命令式渲染范式（参考 NestSVG）：React 仅渲染 `<svg ref/>`；useEffect 内 imperative 建翻转组 `<g>` + 各层节点（polygon / polyline / line / text）。**5 层分层**：layer1 毛版半透明蓝实心 + `#3f7fbf` 实线边（闭合 polygon）；layer14 净版绿虚线 `#33cc33` `dasharray=6 3`（闭合 polygon，fill=none）；layer8 内部线橙实线 `#ff8c1a`（polyline 不闭合，line.length<2 跳过）；layer4 刀口黄短线段 `#ffd700`（line，端点 `P ± 4*unit_normal`，`NOTCH_LEN_MM=8`）；layer7 布纹线红虚线 `#e53e3e` `dasharray=5 3`（line，grain_line=null 跳过）。**US-024 起 5 层配色 + NOTCH_LEN_MM 改从 `constants/colors.ts LAYER5_COLORS / NOTCH_LEN_MM` import**（与 NestSVG 共享单一真相源）。**翻转组 transform = `translate(0 minY+maxY) scale(1 -1)`**（NestSVG `translate(0 gate)` 是 minY=0/maxY=gate 的特例）；**A/B/C 文字标注在翻转组外**（屏幕坐标，避免镜像），锚点 = bbox 左上角上方 LABEL_Y_OFFSET=3（baseline 在 minY - 3），font-size=11。**viewBox = bbox + pad**（默认 14，最小 4 clamp）。**piece(s) 切换整组重建**（useEffect 头部 `while removeChild` 清空）。导出 `pieceBBox` / `piecesBBox` / `BBox` 便于单测 |
| `src/components/preview/__tests__/PiecePreviewSVG.test.tsx` | 33 项单测：bbox 纯函数 5（合并所有层顶点 / 空片 null / 无 grain 跳过 / 多片合并 / 全空片 null）；AC#1 命令式 2（React 仅 `<svg ref/>` + 子节点 imperative / StrictMode 双 mount 不残留）；AC#2 渲染分层 11（5 层颜色/线型/数据 + layer1 points 字符串 + internal line<2 跳过 + 刀口端点 P±4*normal 横/斜向 + grain null 跳过 + 全 5 层同框节点数）；AC#3 翻转+标注 9（flip transform 单片/多片合并 bbox / viewBox 默认+自定义+clamp / 标注在翻转组外 / 标注屏幕坐标 / label 空串跳过 / 多片各自标注）；AC#4 单片/多片/空片容错 4（单片 1 rough 1 label / 多片 rough=label=pieces.length / 空片啥都不画 / polygon<3 跳过 rough）；AC#5 切片重建 3（切 piece 清旧 + viewBox 重算 / 切到空片清空 / pad 变化触发 viewBox 重算 dep） |
| `src/style.css` | 加 `.piece-preview-svg { display:block; width:100%; height:100%; min-height:0; background:#eef0f3 }`（与 `.nest-card svg` 同口径，背景与排料图同色） |

### 关键不变量（上传预览 US-007 立，后续故事不得破坏）

1. **命令式渲染范式（参考 NestSVG.tsx）** —— React 仅渲染 `<svg ref/>`；useEffect 内 imperative 建 flipGroup `<g>` + 各层节点（polygon / polyline / line / text），用 `setAttribute` 写 transform / points / stroke / ...，**逃逸 React reconciliation**。改任何 attr 走 JSX prop 会被 React 用 vdom 覆盖回旧值（同 NestSVG 关键约定 #2）。React 18 StrictMode 双 mount 也安全（useEffect 头部清空 + 重建）。
2. **翻转组 transform = `translate(0 minY+maxY) scale(1 -1)`** —— sparrow Y-up → SVG Y-down（与 PNG / R12-DXF / NestSVG 一致）。`minY+maxY` 是 bbox 的 Y 对称轴，翻转后 bbox 内几何视觉与 sparrow 视图一致（不上下颠倒）。NestSVG 是其特例（minY=0, maxY=gate → `translate(0 gate) scale(1 -1)`）。改字面量需同步 PiecePreviewSVG.test.tsx AC#3 「翻转组 transform」单片 + 多片两组用例。
3. **A/B/C 文字标注放在翻转组 `<g>` 之外（AC#3 不镜像）** —— 用屏幕坐标（SVG Y-down）直接定位；锚点 = piece bbox 左上角上方 `LABEL_Y_OFFSET=3`（baseline 在 `minY - 3`），`font-size=11` / `dominant-baseline=alphabetic` / `text-anchor=start`。改位置 / 字号需同步 PiecePreviewSVG.test.tsx 「A/B/C 标注用屏幕坐标」用例。**多片同框时每片各自 bbox 锚点独立渲染**（不合并）。
4. **viewBox = bbox + pad**（默认 `DEFAULT_PAD=14`，最小 `MIN_PAD=4` clamp）—— pad 容纳 8mm 刀口半段（4mm）+ 标注文本（~10mm cap 高度，cap 顶 ≈ minY - 3 - 0.8*size = minY - 11.8，刚好在 pad=14 内）。改 pad 默认需同步 PiecePreviewSVG.test.tsx 「viewBox」用例（默认 + 自定义 + clamp 三组）。
5. **5 层渲染分层（颜色 / 线型严格固定，改需同步测试 + 版师确认）** —— layer1 毛版半透明蓝实心 `rgba(80,140,200,0.22)` + `#3f7fbf` 实线边（闭合 polygon，stroke-width=1.5）；layer14 净版绿虚线 `#33cc33` `stroke-dasharray=6 3`（闭合 polygon，fill=none，stroke-width=1.2）；layer8 内部线橙实线 `#ff8c1a`（polyline 不闭合，line.length<2 跳过，stroke-width=1）；layer4 刀口黄短线段 `#ffd700`（line，端点 `P ± 4*unit_normal`，长度 `NOTCH_LEN_MM=8`，**待版师预览时确认调整**，stroke-width=1.4）；layer7 布纹线红虚线 `#e53e3e` `stroke-dasharray=5 3`（line，grain_line=null 跳过，stroke-width=1.2）。配色口径与 `scripts/preview/*.svg` 已版师确认的方案一致。
6. **刀口端点 = `P ± 4 * unit_normal`**（unit_normal 来自后端 `notch[2..3]`）—— 法线为单位向量（后端 collect.py `_nearest_edge_with_normal` 计算），half=NOTCH_LEN_MM/2=4，端点 `(x∓4*nx, y∓4*ny)`，r2 截断。法线为零向量（退化边）→ 0 长度线段（点）兜底，不渲染异常。改 NOTCH_LEN_MM 需同步 PiecePreviewSVG.test.tsx 2 项刀口用例（横/斜向 normal）+ 版师确认。
7. **piece(s) 切换整组重建（不同于 NestSVG flipRef 幂等）** —— useEffect 头部 `while (svg.firstChild) svg.removeChild(svg.firstChild)` 清空旧内容后重建。NestSVG 同 run 内 N 帧复用 DOM（高频，renderTick ~10fps 节流），PiecePreviewSVG 切片是低频 UI 操作（用户点选某片），重建简洁且开销可接受。StrictMode 双 mount 同样安全（清空再建）。
8. **AC#4 多片同框** —— prop 接受 `ParsedPiece | ParsedPiece[]`，归一化为数组；多片时合并 bbox 计算 viewBox（`piecesBBox`），每片独立渲染 5 层 + 各自 A/B/C 标注。US-008 ParsedPiecesView 用单片卡片，多片能力留作未来扩展（不刻意避免重叠，由调用方决定是否同框）。
9. **空片容错（polygon=[] 或全无数据）** —— `piecesBBox` 返回 null → svg 清空后啥都不画（无 viewBox / 无 flipGroup / 无标注），不留残影。polygon.length<3 跳过 rough 层；net_polygon.length<3 跳过 net 层；internal line.length<2 跳过该条；其他层照常渲染。改兜底需同步 PiecePreviewSVG.test.tsx「空片」「polygon<3 跳过 rough」用例。
10. **pad prop 最小 4 clamp** —— `safePad = Math.max(MIN_PAD, pad)`，防 8mm 刀口半段被裁。负数 / NaN（NaN 经 max 比较返回另一侧）兜底为 4。
11. **导出 `pieceBBox` / `piecesBBox` / `BBox` 便于测试** —— 纯函数 / 类型导出，单测直接调；不改 React 渲染。5 项 bbox 用例覆盖（合并所有层顶点 / 空片 null / 无 grain 跳过 / 多片合并 / 全空片 null）。
12. **不引入 CSS 框架** —— `.piece-preview-svg`（display:block + width:100% + height:100% + bg `#eef0f3`，与排料图同色）由 imperative `setAttribute('class', ...)` 写入，沿用 style.css；与 `.nest-card svg` 同口径。改 CSS 需同步 `.piece-preview-svg` 规则（US-008 ParsedPiecesView 卡片复用）。

## 上传预览 US-008 落地：SizeTabs + ParsedPiecesView + PreviewPage 容器集成（Tab 打通）

| 文件 | 角色 |
| --- | --- |
| `src/components/preview/SizeTabs.tsx` | 尺码切换条。订阅 uploadStore `doc`/`activeSize`/`setSize`；渲染 `<div class="size-tabs" role="tablist">` + 每 chip `<button class="size-chip" role="tab" aria-selected>`；chip 顺序 = doc.sizes 顺序（后端按数值升序、null 殿后）；**null 码 → 「通用」文案**（`NULL_SIZE_LABEL`）；activeSize 匹配项加 `.active`；点击 → `setSize(s.size)`；**doc=null 时返回空 Fragment**（PreviewPage 兜底，双重防御） |
| `src/components/preview/ParsedPiecesView.tsx` | 当前 activeSize 下裁片 grid。订阅 uploadStore `doc`/`activeSize`；`doc.sizes.find(s => s.size === activeSize)` 过滤当前码（防御性兜底找不到 → pieces=[]）；grid 用 CSS Grid `auto-fill + minmax(220px, 1fr)`；每片 `<div class="piece-card">` 含 `.piece-card-head`（label 徽章 + name）+ `.piece-card-body`（PiecePreviewSVG 单片模式）；`key=${label}-${name}` 跨码安全；pieces=[] 时 `.parsed-pieces-empty` 「该尺码无裁片」 |
| `src/components/preview/PreviewPage.tsx` | 容器组件。订阅 uploadStore `status`/`doc`；**`hasParsed = status === 'done' && doc !== null`** 决定分支：true → `<SizeTabs/> + <ParsedPiecesView/>`；false → `.preview-empty` 空态卡片（沿用 US-001 className）；布局 `<div class="preview-page"><UploadPanel/><section class="preview-main">…</section></div>`（左 panel 固定 248px + 右 main flex:1） |
| `src/style.css` | 加 `.preview-page{flex;display}` + `.preview-main{flex-col;overflow:auto}` + `.size-tabs{flex-wrap;gap 6}` + `.size-chip{border-radius:14; #34363d bg}` + `.size-chip.active{#2ea06c bg #fff}` + `.parsed-pieces-view{padding 12;overflow:auto}` + `.piece-grid{grid auto-fill minmax(220px,1fr) gap 10}` + `.piece-card{#2a2c32 bg;radius 4;min-height 180}` + `.piece-card-head{#1c1d22 bg}` + `.piece-card-label{#2ea06c 徽章 18×18 radius 9 #fff 600}` + `.piece-card-name{#cdd word-break}` + `.piece-card-body{flex padding 6}` + `.parsed-pieces-empty{center 32 #888}` |
| `src/components/preview/__tests__/SizeTabs.test.tsx` | 8 项单测：AC#1 渲染 doc.sizes 全部 chip（按后端顺序）+ null→「通用」+ role=tablist/tab + activeSize=null 防御；AC#1 active 高亮 + aria-selected + 点击 setSize(number\|null) 切换 + .active 转移 |
| `src/components/preview/__tests__/ParsedPiecesView.test.tsx` | 8 项单测：AC#2 doc=null 空 + 渲染当前码 pieces + 每片含 label+name+svg + .piece-grid 容器 + key label-name 安全；切 activeSize grid 刷新 + activeSize 不在 doc 防御 + 空码空态 |
| `src/components/preview/__tests__/PreviewPage.test.tsx` | 9 项集成：AC#3 左 panel+右 main 结构 + 4 空态分支（idle/uploading/error/默认）；AC#3 done+doc 挂主体 + SizeTabs 列码 + ParsedPiecesView 当前码片数 + 切 activeSize→刷新 + 端到端 chip 点击切 grid |

### 关键不变量（上传预览 US-008 立，后续故事不得破坏）

1. **三个新组件都从 uploadStore 读、不持本地状态** —— SizeTabs 读 `doc`/`activeSize`/`setSize`；ParsedPiecesView 读 `doc`/`activeSize`；PreviewPage 读 `status`/`doc`。store 是单一真相源（US-005 关键约定），**切 Tab 后状态保留 = store 模块级单例 + App display:none 不卸载**（AC#5 由 store 持久性保证，组件本身无需任何持久化逻辑）。改状态来源会破坏 AC#5。
2. **PreviewPage 空态分支用 `hasParsed = status === 'done' && doc !== null`** —— 双重条件防御（done 理论必有 doc，但 TS 类型上 doc nullable）。uploading/error 时仍显示空态卡片（不显示「上传中…」之类的状态行 —— 那是 UploadPanel 的事），保持右侧稳定布局。改分支需同步 PreviewPage.test.tsx 4 项空态用例。
3. **SizeTabs chip 顺序 = doc.sizes 顺序**（后端按数值升序、null 殿后，`_size_sort_key`）—— **前端不二次排序**，保证 UI 顺序与后端语义一致。改排序需同步后端 `_build_parse_payload` + SizeTabs.test.tsx 「渲染 doc.sizes 全部」用例。
4. **null 码 chip 显示「通用」**（`NULL_SIZE_LABEL`）—— 母版里极少出现的「不分码」片（统计上代表通用码），用人读文案代替空字符串/「null」。改文案需同步 SizeTabs.test.tsx 「null 码渲染为通用」用例。
5. **SizeTabs doc=null 时返回空 Fragment**（`return <></>`）—— 双重防御（PreviewPage 在 doc=null 时不挂载 SizeTabs，组件本身也兜底）。改返回值需同步 SizeTabs.test.tsx 「doc=null」用例。
6. **ParsedPiecesView 用 `doc.sizes.find(s => s.size === activeSize)` 过滤当前码** —— 理论必命中（SizeTabs 只能切到 doc.sizes 里的码），防御性兜底 `matched=undefined` → pieces=[] → 显示「该尺码无裁片」空态。改过滤逻辑需同步 ParsedPiecesView.test.tsx 「activeSize 不在 doc.sizes」用例。
7. **piece key 用 `${label}-${name}`** —— label 在码内唯一（A/B/C/...，后端 `_label_for` 已保证），name 是母版 block 名（GBK 解码后中文），两者拼合跨码安全。同码内可能多片同名（label 不同）或同 label 不同名 —— key 拼合兜底所有场景。改 key 需同步 ParsedPiecesView.test.tsx 「key 用 label-name」用例。
8. **每片卡片用 PiecePreviewSVG 单片模式**（不传数组，US-007 AC#4 多片能力留作未来扩展）—— grid 是「每片独立预览」语义，单片卡片视觉清晰。改多片模式需先与版师确认 grid 单卡承载多片的 UX 必要性。
9. **piece-card 视觉沿用 .nest-card 同口径** —— 暗背景 `#2a2c32` + 圆角 + 上方 `.piece-card-head`（label 徽章 + 裁片名）+ 下方 `.piece-card-body`（SVG 自适应）；与排料页 NestCard 视觉一致。label 徽章 `.piece-card-label` 用绿色 `#2ea06c` 圆形 + 白字，与 StartButton / TabBar active / size-chip active 同色系。
10. **grid 用 CSS Grid `auto-fill + minmax(220px, 1fr)`** —— 浏览器宽度自适应列数（窗口缩小时单卡不被压扁，最小 220px 保证 SVG 不退化成窄条）。改 minmax 需视觉回归核对（M1787 每码 ~10 片 × ~180px 高度 ≈ 一屏）。
11. **不引入 CSS 框架** —— `.preview-page` / `.preview-main` / `.size-tabs` / `.size-chip` / `.parsed-pieces-view` / `.piece-grid` / `.piece-card*` 全部沿用 style.css 命令式 className，与 ControlPanel / NestCard 暗背景 `#26282e/#2a2c32` + 绿色 `#2ea06c` 强调同色系。
12. **AC#5 切 Tab 后状态保留验证（App.test.tsx）** —— App.test.tsx 切到 preview Tab 后断言 `.preview-empty` 仍在（doc=null 默认状态走空态分支，与 US-001 占位的 className 一致 —— 复用 `.preview-empty`/`.preview-empty-card`，不破坏 US-001 App 集成 smoke 测试）。改 PreviewPage 空态 className 需同步 App.test.tsx 第 101 行断言。

## 上传预览 US-011 落地：qtyStore 数量状态（per-size/global 双模式 + 跨码联动置灰）

| 文件 | 角色 |
| --- | --- |
| `src/types/qty.ts` | 数量类型契约：`QtyMode = 'per-size' \| 'global'`；`PieceQuantity { mode; perSize: Record<string,number>; globalValue: number; globalSource: number\|null }`；`PieceQuantityMap = Record<string /*label*/, PieceQuantity>`。**label 跨码匹配同一片型**（A/B/C 次序在码间稳定，依赖后端几何排序），与 uploadStore 完全解耦 |
| `src/store/qtyStore.ts` | Zustand store + 2 个纯函数导出。state `quantities: PieceQuantityMap`（默认 `{}`）；actions：`setPiecePerSize(label, size, value)`（per-size 写入；若当前 global 则先切回 per-size：globalValue 继承到 `perSize[sizeKey(globalSource)]`、清空 global 字段、再写新值）、`setPieceGlobal(label, sourceSize, value)`（切 global：mode/globalValue/globalSource 三字段写）、`resetQuantities()`（清 `{}`）。**导出纯函数 `clampQty(v)=Math.max(0,Math.min(99,Math.trunc(Number(v)\|\|0)))`**（整数 [0,99]）+ **纯函数 selector `getPieceDisplay(map,label,size) -> {qty,editable,reason}`**（四分支：未配置 / per-size / global+source / global+非source）。`sizeKey(number)=String(size)` / `sizeKey(null)='null'`；`sizeLabel(null)='通用'` 否则 `String(size)`（与 SizeTabs `NULL_SIZE_LABEL` 同语义），均 store 内私有 |
| `src/store/__tests__/qtyStore.test.ts` | 24 项单测：clampQty 6（负数/小数/NaN/超99/字符串/正常）；getPieceDisplay 9（label 未配置 / per-size / per-size 未设 / global+source / global+非source reason 含来源码 / null 码 sizeKey per-size / null 码 sizeLabel global-source=28 / source=null 访问 null editable / source=null 访问 number reason 含「通用」）；setPiecePerSize 4（写入值 / 从 global 切回继承 / 跨码独立 / clampQty）；setPieceGlobal 2（切模式非 source editable=false / 二次切覆盖）；resetQuantities 1；store 独立性 2（与 uploadStore 字段不重叠 / 双向 reset 互不影响） |

### 关键不变量（上传预览 US-011 立，后续故事不得破坏）

1. **qtyStore 与 uploadStore 完全解耦** —— qtyStore 只持 `quantities` + 3 actions（setPiecePerSize/setPieceGlobal/resetQuantities），不读 doc/activeSize；uploadStore 不持 quantities。改字段需同步 qtyStore.test.ts 「store 独立性」2 项用例。US-014 集成时 uploadStore.reset 联动 `resetQuantities()`（重传清零）。
2. **label 跨码匹配同一片型** —— 数量 map 以 label（A/B/C）为 key，跨码语义同片型。依赖后端 `_label_for` 的几何排序 `(-centroid_y, centroid_x, -area_mm2, ...)` 在码间稳定（M1787 结构款成立；新款母版需版师确认）。改 key 口径需同步 US-014 ParsedPiecesView 集成。
3. **`getPieceDisplay` 四分支严格固定** —— （a）label 未在 map → `{qty:0, editable:true, reason:null}`；（b）mode per-size → qty=`perSize[sizeKey(size)] ?? 0`、editable=true；（c）mode global 且 `globalSource===size` → qty=globalValue、editable=true；（d）mode global 且 `globalSource!==size` → qty=globalValue、editable=false、reason=`'该数值已在「<sizeLabel(globalSource)>」处使用全局数量'`。改任一分支需同步 qtyStore.test.ts 9 项 getPieceDisplay 用例。
4. **`clampQty` 是数量值唯一规整入口** —— `Math.max(0, Math.min(99, Math.trunc(Number(v) || 0)))`：负数/NaN/非数字→0；小数→截断（非四舍五入）；>99→99；字符串数字→对应整数。setPiecePerSize / setPieceGlobal 内部统一走 clampQty，调用方传入原值即可。改公式需同步 qtyStore.test.ts 6 项 clampQty 用例 + 4 项 setPiecePerSize「value 经 clampQty」用例。
5. **从 global 切回 per-size 时 globalValue 继承到 source 码** —— `setPiecePerSize(label, size, value)` 内部检测 `prev.mode==='global'`，先把 `prev.globalValue` 写到 `perSize[sizeKey(prev.globalSource)]`（globalSource=null 时 sizeKey='null' 兜底），再写新值到 `perSize[sizeKey(size)]`，最后 mode='per-size' + 清 globalValue/globalSource。改继承逻辑需同步 qtyStore.test.ts「从 global 切回时 globalValue 继承到 source 码」用例。
6. **null 码 sizeKey/sizeLabel 双口径** —— `sizeKey(null)='null'`（perSize key 空间，与 number 区分）；`sizeLabel(null)='通用'`（人读文案，与 SizeTabs NULL_SIZE_LABEL 同语义）。globalSource=null 表示用户在「通用」码切 global，访问 null 码 editable=true（source 匹配），访问 number 码 reason 含「通用」。改文案需同步 qtyStore.test.ts null 码 3 项用例 + SizeTabs.test.ts「null 码渲染为通用」用例（同语义）。
7. **`getPieceDisplay` 是 UI 消费的唯一入口** —— 卡片头（US-014 ParsedPiecesView）、数量弹窗（US-012 PieceQtyDialog）、放大模态（US-013 PieceZoomModal）都调 `getPieceDisplay(quantities, label, size)`，不直接读 quantities[label]。改 selector 签名需同步 US-012/013/014 调用方。
8. **qtyStore reset 不影响 uploadStore，反之亦然** —— 双向独立性由 store 模块级隔离保证。改 reset 行为需同步 qtyStore.test.ts「store 独立性」2 项用例。
9. **不进 commit / 排料** —— US-011 仅前端 UI，数量存 store 不序列化到 intermediate。后端接环（数量→每片复制份数）是后续 Story，不在本故事范围。

## 上传预览 US-012 落地：PieceQtyDialog 数量编辑弹窗 + Switch 受控开关（草稿 + 确定模式）

| 文件 | 角色 |
| --- | --- |
| `src/store/uploadStore.ts` | 增量：新增 `qtyDialog: { label: string; size: number \| null } \| null`（默认 null）+ actions `openQtyDialog(label, size)` / `closeQtyDialog()`；`reset()` 同步清 `qtyDialog=null`。store 公开 API 扩到 4 个（reset/setSize/openQtyDialog/closeQtyDialog）；hook useParseDxf 的 setState 流程**不写 qtyDialog**（弹窗显隐仅由 UI 触发，与上传解析无关） |
| `src/components/preview/Switch.tsx` | 受控 toggle。props `{ checked: boolean; onChange: (v:boolean)=>void; labelOn: string; labelOff: string; disabled?: boolean; 'data-testid'?: string }`；`<button role="switch" aria-checked={checked}>` + CSS `.switch-track`/`.switch-label-off`/`.switch-label-on`/`.switch-thumb`（暗底 `#34363d` + 绿 active `#2ea06c`，与 size-chip.active 同色系）；点击 -> `onChange(!checked)`；`disabled=true` 走原生 button disabled（不响应点击 + 不参与 tab 序列） |
| `src/components/preview/PieceQtyDialog.tsx` | 数量编辑弹窗。订阅 uploadStore.qtyDialog；`null` 时 `return null`（不挂 DOM）。打开时渲染 `PieceQtyDialogInner`（key=`${label}-${size??'null'}` 强制 target 切换时重建，从 store 重新读初值）。Inner：useState 草稿（draftQty/draftGlobal）从 `getPieceDisplay(quantities, label, size)` 读初值（draftQty=qty、draftGlobal = mode==='global' && globalSource===size）；`useEffect` 挂 ESC `window.keydown`（关闭时卸载，无残留）。结构：`.piece-qty-dialog-overlay`（fixed 全屏 + 遮罩 + flex 居中，onMouseDown 落在 overlay 自身才关）+ `.piece-qty-dialog-modal`（role=dialog + aria-modal）+ `.piece-qty-dialog-title`（裁片 {label} · 码 {sizeLabel(size)}）+ `.qty-input-group`（[-] input [+]；input 实时 onChange + blur clamp）+ `.qty-switch`（Switch labelOff=仅当前尺码 / labelOn=全部尺码）+ `.piece-qty-dialog-actions`（取消/确定）。确定逻辑：`draftGlobal=true -> setPieceGlobal(label,size,draftQty)` / `false -> setPiecePerSize(label,size,draftQty)` 后 `closeQtyDialog()`。**Portal 到 document.body**（与 Tooltip 同口径）。 |
| `src/style.css` | 加 `.piece-qty-dialog-overlay`（fixed inset:0 + rgba(0,0,0,0.6) + flex 居中 + z-index:1000 高于 .tooltip）+ `.piece-qty-dialog-modal`（`#26282e` 暗底 + radius 8 + min-width 320 + flex-col gap 16）+ `.piece-qty-dialog-title`（14px 600 + bottom-border）+ `.qty-input-group`（flex + gap 8）+ `.qty-step`（32×32 + `#34363d` + hover `#2ea06c` border + disabled `#555`）+ `.qty-input`（64×32 + center + monospace + 隐藏 number spinner）+ `.switch`（inline-flex + relative）+ `.switch-track`（180×28 + `#34363d` + radius 14 + overflow hidden）+ `.switch-label-off/on`（flex:1 + center + pointer-events:none）+ `.switch-thumb`（86×22 absolute + `#2ea06c` + transition transform 0.18s；.on 时 translateX(90px)）+ `.piece-qty-dialog-actions`（flex + right + gap 10）+ `.qty-btn`/`.qty-confirm`（暗底 / 绿底 `#2ea06c` 600） |
| `src/store/__tests__/uploadStore.test.ts` | 增量：新增 6 项 qtyDialog 用例（默认 null / open 写入 / open null 码 / close 清回 / reset 同步清 / 订阅者通知）。原 7 项 uploadStore 用例不变 |
| `src/components/preview/__tests__/Switch.test.tsx` | 5 项单测：role=switch + aria-checked 跟随 checked / 点击 onChange(true)/(false) / labelOn/labelOff 文案 / disabled 不触发 / `.on` class 跟随 checked（CSS 滑块平移依赖） |
| `src/components/preview/__tests__/PieceQtyDialog.test.tsx` | 15 项集成：qtyDialog=null 不渲染 DOM / 标题含 label+通用文案 / 标题含数字码 / 初值 per-size draftQty / 初值 global source draftQty+draftGlobal / [+][-] 改 draftQty + [-]@0 disabled / input 实时跟 + 非数字兜底 0 / Switch 切 draftGlobal / 确定 per-size 调 setPiecePerSize + close / 确定 global 调 setPieceGlobal + close / 取消不写 store / 遮罩点击关闭不写 store / ESC 关闭不写 store / modal 内 mousedown 不冒泡关闭 / blur clamp 兜底 |

### 关键不变量（上传预览 US-012 立，后续故事不得破坏）

1. **草稿 + 确定模式（非即时生效）** —— PieceQtyDialogInner 用 useState 持 `draftQty`/`draftGlobal`；用户编辑仅改草稿；点确定才写 qtyStore；点取消 / 遮罩 / ESC 仅 `closeQtyDialog()`，草稿丢弃。**目的**：切 global 瞬间会把其它码同 label 置灰（editable=false），草稿模式让用户在确定前可以回滚（避免误操作锁定其它码）。改即时生效会破坏此体验。
2. **key 强制重建 PieceQtyDialogInner** —— `key={`${label}-${size ?? 'null'}`}`；target 切换时（点卡片头切到另一片）Inner 重建，useState 重新从 store 读初值，避免 StrictMode 双 mount / 同 label 二次 open 时草稿残留。改 key 拼合需同步 5 项「初值」用例。
3. **`PieceQtyDialog` 默认 return null** —— `qtyDialog === null` 时返回 `null`（不挂 DOM）；打开时 Portal 到 document.body（与 Tooltip 同口径）。改 Portal 目标（如挂到 .tab-content 内）会破坏 z-index 与定位（被父级 transform / overflow 影响）。US-013 PieceZoomModal、US-014 集成也用 Portal 同口径。
4. **初值严格走 `getPieceDisplay` selector** —— draftQty 初值 = `getPieceDisplay(quantities, label, size).qty`；draftGlobal 初值 = `quantities[label]?.mode === 'global' && quantities[label]?.globalSource === size`（不能仅靠 `getPieceDisplay.editable`，因为 label 未配置时 editable=true 但 draftGlobal 必须 false）。改初值口径需同步「初值 per-size / 初值 global source」2 项用例。
5. **ESC 监听在 Inner 组件挂/卸载** —— Inner 用 `useEffect` 在 mount 时 `window.addEventListener('keydown', onKey)`、unmount 时 `removeEventListener`。dialog 关闭（target 切 null）时 Inner 卸载 → listener 自动清理，无残留。改监听位置（如挂到 uploadStore subscription）会破坏生命周期同步。
6. **遮罩 mousedown 用 `e.target === e.currentTarget`** —— 只在 mousedown 落在 overlay 自身（不是冒泡上来的子元素）时 onClose；modal 内任何点击不关闭。改判定需同步「modal 内 mousedown 不冒泡关闭」用例。用 mousedown（不是 click）防止用户在 modal 内拖选文本时误关。
7. **input blur 时 clamp 兜底** —— `handleInputBlur` 调 `clampQty(e.target.value)`；type=number input 上下箭头 / 字符串粘贴可能写入超 99 / 非数字值，blur 时统一规整到 [0,99] 整数。改兜底需同步「blur clamp 兜底（超 99）」用例。
8. **`[-]` 在 draftQty <= 0 时 disabled** —— 原生 button disabled（不响应点击 + 不参与 tab 序列），与 qtyQty clampQty 下界 0 一致；`[+]` 不 disabled（clampQty 兜底 99）。改判定需同步「`[+]`/`[-]` 改 draftQty；`[-]`@0 disabled」用例。
9. **Switch 用原生 `<button disabled>` 兜底** —— Switch props.disabled=true 时 button 自带 `disabled` 属性（不响应点击 + 不参与 tab 序列），`handleClick` 内 `if (disabled) return` 是双重防御；改任一层需同步 Switch.test.tsx「disabled 不触发 onChange」用例。
10. **不引入 CSS 框架** —— `.piece-qty-dialog-*` / `.qty-input-group` / `.qty-step` / `.qty-input` / `.switch` / `.switch-track` / `.switch-label-*` / `.switch-thumb` / `.qty-btn` / `.qty-confirm` 全部沿用 style.css 命令式 className，与 ControlPanel / SizeTabs / piece-card 暗背景 `#26282e/#34363d` + 绿色 `#2ea06c` 强调同色系。改 className 需同步组件 + 测试。
11. **uploadStore.reset 联动 qtyStore.resetQuantities 留到 US-014** —— 本故事只扩 uploadStore.reset 清 qtyDialog（同 store 内）；qtyStore 独立 store 的 resetQuantities 联动（重传清零数量）由 US-014 ParsedPiecesView 集成时挂入。本故事范围仅弹窗 + Switch 组件 + 单测，不集成到 PreviewPage。

## 上传预览 US-013 落地：PieceZoomModal 放大预览模态（声明式受控 Portal + ✕/遮罩/ESC 关闭）

| 文件 | 角色 |
| --- | --- |
| `src/store/uploadStore.ts` | 增量：新增 `zoom: { label: string; size: number \| null } \| null`（默认 null）+ actions `openZoom(label, size)` / `closeZoom()`；`reset()` 同步清 `zoom=null`。store 公开 API 扩到 6 个（reset/setSize/openQtyDialog/closeQtyDialog/openZoom/closeZoom）；hook useParseDxf 的 setState 流程**不写 zoom**（模态显隐仅由 UI 触发，与上传解析无关） |
| `src/components/preview/PieceZoomModal.tsx` | 放大预览模态。订阅 uploadStore `zoom` + `doc`；`zoom===null \|\| doc===null` 时 `return null`（不挂 DOM）。打开时调 `locatePiece(doc, label, size)` 定位 ParsedPiece + 序号（pieces.findIndex+1）；**防御性兜底**：找不到码 / 找不到 label → 渲染 null（理论不会发生，因 openZoom 由 ParsedPiecesView 在已挂载卡片上调）。`useEffect` 在 `zoom!==null` 时挂 ESC `window.keydown`（关闭时 effect cleanup 自动卸载，无残留）。结构：`.piece-zoom-overlay`（fixed 全屏 + 遮罩 + flex 居中，onClick 落在 overlay 自身才关）+ `.piece-zoom-modal`（role=dialog + aria-modal + aria-label；onClick stopPropagation 防 modal 内点击冒泡）+ `.piece-zoom-close`（右上角绝对定位，✕；aria-label=关闭）+ `.piece-zoom-head`（label 徽章 + `序号(qty)` + ` · 码 {sizeLabel(size)} · ` + name；qty 从 `getPieceDisplay(quantities, label, size).qty` 读，seq 从 `locatePiece` 读）+ `.piece-zoom-body`（`<PiecePreviewSVG piece={p} pad={20}/>`，pad 加大留白；5 层渲染 + A/B/C 标注全部复用）。**Portal 到 document.body**（与 Tooltip / PieceQtyDialog 同口径） |
| `src/style.css` | 加 `.piece-zoom-overlay`（fixed inset:0 + rgba(0,0,0,0.6) + flex 居中 + z-index:1000 与 .piece-qty-dialog-overlay 同层，高于 .tooltip 100）+ `.piece-zoom-modal`（`#2a2c32` 暗底 + radius 8 + max-width/height 90vw/90vh + overflow:auto + 相对定位承载关闭按钮 + flex-col gap 12）+ `.piece-zoom-head`（flex + gap 6 + padding-right 28 留位 ✕ + flex-shrink 0）+ `.piece-zoom-seq`（monospace + 600）+ `.piece-zoom-meta`（`#9aa`）+ `.piece-zoom-name`（`#cdd` + word-break）+ `.piece-zoom-close`（absolute top 8 right 10 + 28×28 + transparent bg + `#cdd` 字 + hover bg `#3f424a` + `#2ea06c` 字 + focus-visible outline）+ `.piece-zoom-body`（flex 1 + min-height 320 + min-width 0 + flex）+ `.piece-zoom-body svg`（flex 1 + min-height 320） |
| `src/store/__tests__/uploadStore.test.ts` | 增量：新增 7 项 zoom 用例（默认 null / open 写入 number / open null 码 / close 清回 / reset 同步清 / 订阅者通知 / zoom 与 qtyDialog 字段独立）。原 13 项（US-005 基础 7 + US-012 qtyDialog 6）不变 |
| `src/components/preview/__tests__/PieceZoomModal.test.tsx` | 14 项集成：zoom=null 不渲染 / doc=null 不渲染 / 渲染 overlay+modal+aria-label / 头部含 label 徽章+seq(qty)+size+name / 头部 qty 从 qtyStore per-size 读 / null 码 sizeLabel「通用」/ body svg.piece-preview-svg / ✕ closeZoom / 遮罩 closeZoom / modal 内不冒泡 / ESC closeZoom / Portal body（根不在 container 内）/ label 不存在兜底不渲染 / size 不存在兜底不渲染 |

### 关键不变量（上传预览 US-013 立，后续故事不得破坏）

1. **声明式受控 Portal（区别于 Tooltip 命令式单例）** —— PieceZoomModal 订阅 `uploadStore.zoom + doc`；`zoom===null \|\| doc===null` 时 `return null`（不挂 DOM）；打开时 Portal 到 document.body（与 PieceQtyDialog / Tooltip 同 Portal 目标）。改 Portal 目标（如挂到 .tab-content 内）会破坏 z-index 与定位（被父级 transform / overflow 影响）。**区别于排料页 Tooltip 的命令式单例**（Tooltip 用模块顶层 `_el/_hovered` + showTooltip/hideTooltip 命令式 API；模态低频声明式更合适）。
2. **ESC 监听在 zoom 切换时挂/卸载** —— `useEffect` dep `[zoom, closeZoom]`；`zoom===null` 时 effect 早 return（不挂 listener）；`zoom!==null` 时挂 window.keydown，cleanup 函数卸载 listener。zoom 切 null（关闭）时 effect 重跑 → cleanup → 自动卸载，无残留。改监听位置（如挂在 modal 自身）会破坏「ESC 全局触发」语义。**hook 必须无条件调（不能在条件分支里）**，故 zoom!==null 判定在 effect 内部。
3. **遮罩 onClick 用 `e.target === e.currentTarget`** —— 只在 click 落在 overlay 自身（不是冒泡上来的子元素）时 closeZoom；modal 用 `onClick stopPropagation` 双重防御（即使冒泡到 overlay 也已被 stop）。用 click（不是 mousedown）—— 与 PieceQtyDialog 用 mousedown 不同；本模态无可拖选文本场景，click 语义更直观。改判定需同步「遮罩 closeZoom / modal 内不冒泡」2 项用例。
4. **`locatePiece` 防御性兜底渲染 null** —— `doc.sizes.find(s=>s.size===size)` 找不到 → null；`pieces.findIndex(p=>p.label===label) < 0` → null。理论不会发生（openZoom 由 ParsedPiecesView 在已挂载卡片上调，必然能定位），但兜底防御 doc 切换 race / 异常 store state。改兜底需同步「label 不存在 / size 不存在」2 项用例。
5. **序号 = pieces 数组 index+1（与卡片头序号同口径，US-014 集成时复用）** —— `locatePiece` 返回 `{piece, seq: idx+1}`；与 label 字母次序一致（A=1, B=2, ...，依赖后端 `_label_for` 几何排序 `(-centroid_y, ...)`）。**详情模态头部同时显示 label 徽章 + 序号(数量)**：徽章给版师字母习惯，序号给数量定位（D1 决策信息冗余但语义一致）。改 seq 口径需同步 US-014 ParsedPiecesView 卡片头 seq（届时可考虑提取公用 `findPieceIndex` 函数；本故事先内联）。
6. **数量从 `getPieceDisplay` 读（与卡片头/PieceQtyDialog 同 selector）** —— 头部 `seq(display.qty)` 中 `display = getPieceDisplay(quantities, label, size)`，**不直接读 `quantities[label]`**（区分 per-size / global-source / global-非source 四分支）。改 selector 来源会破坏「global 模式非 source 码显示全局值」语义（US-014 集成时卡片头置灰联动也复用此 selector）。
7. **PiecePreviewSVG pad=20（比卡片默认 pad=14 加大留白）** —— 放大显示更多内边距视觉更舒适；pad 经 PiecePreviewSVG 内 `safePad = Math.max(MIN_PAD=4, pad)` clamp，20 安全。改 pad 需视觉回归核对（M1787 每片放大模态显示宽度 ≈ 90vw，pad 影响 SVG 内容缩放比）。
8. **复用 PiecePreviewSVG 5 层渲染 + scale(1,-1) + A/B/C 标注** —— 本模态只换 pad 与外壳，不动 PiecePreviewSVG 内部；US-007 关键约定（flip transform / viewBox / 5 层配色 / 标注屏幕坐标）全部保留。改 PiecePreviewSVG 需同步本模态视觉回归（放大显示更容易暴露配色 / 标注问题）。
9. **头部 padding-right 28 给 ✕ 按钮留位** —— ✕ 按钮绝对定位 `top:8 right:10 + 28×28`；头部 `padding-right: 28` 防长 name 被按钮遮挡。改 ✕ 位置 / 头部 padding 需同步视觉回归。
10. **uploadStore.reset 联动 zoom 清零** —— 本故事只扩 uploadStore.reset 同步清 `zoom=null`（同 store 内）；qtyStore 独立 store 的 resetQuantities 联动（重传清零数量）仍由 US-014 集成时挂入。本故事范围仅模态组件 + store 字段 + 单测，**不集成到 PreviewPage**（PreviewPage 顶层挂 PieceZoomModal 单例是 US-014 任务）。
11. **不引入 CSS 框架** —— `.piece-zoom-overlay` / `.piece-zoom-modal` / `.piece-zoom-head` / `.piece-zoom-seq` / `.piece-zoom-meta` / `.piece-zoom-name` / `.piece-zoom-close` / `.piece-zoom-body` 全部沿用 style.css 命令式 className，与 piece-card / piece-qty-dialog 暗背景 `#2a2c32/#26282e` + 绿色 `#2ea06c` 强调同色系。改 className 需同步组件 + 测试。

## 上传预览 US-014 落地：ParsedPiecesView 卡片头改造 + 双模态集成（seq(qty) + qty/zoom 双入口 + reset 联动）

| 文件 | 角色 |
| --- | --- |
| `src/components/preview/ParsedPiecesView.tsx` | 改造：卡片头由 `[.piece-card-label] + [.piece-card-name]` 改为 `[.piece-card-label] + [.piece-card-qty]`。序号 = pieces 数组 index+1（A=1, B=2, ...，与 label 字母次序一致；与 PieceZoomModal `locatePiece.seq` 同口径）。数量 + 可编辑性 从 `useQtyStore(s=>s.quantities)` + `getPieceDisplay(quantities, p.label, activeSize)` 读：editable=true 渲染 `<button class="piece-card-qty" onClick={openQtyDialog+stopPropagation}>{seq}({qty})</button>`；editable=false（global 非 source）渲染 `<span class="piece-card-qty disabled" title={reason}>{seq}({qty})</span>`（native title 提供 hover 提示）。`.piece-card-body` 包裹层加 onClick→openZoom + role=button + tabIndex=0 + aria-label + onKeyDown(Enter/Space→openZoom)。key 保留 `${label}-${name}` 跨码安全。订阅 4 个 uploadStore selector（doc/activeSize/openQtyDialog/openZoom）+ 1 个 qtyStore selector（quantities） |
| `src/components/preview/PreviewPage.tsx` | 集成：顶层挂 `<PieceQtyDialog/>` + `<PieceZoomModal/>` 单例（与 SizeTabs/ParsedPiecesView 同级；Portal 到 body，结构位置不影响 DOM）。**重传清零**：useEffect 内 `useUploadStore.subscribe` 监听 state，对比 prev/next `doc?.doc_id`，不同则调 `useQtyStore.getState().resetQuantities()`。覆盖三路径：首次上传（no-op，quantities 已空）、重传（核心场景，旧数量清零避免残留到新母版）、reset()（doc→null）。subscribe 闭包内 `let prevDocId` mutable；unmount 时 unsub（无残留） |
| `src/style.css` | 删 `.piece-card-name`；加 `.piece-card-qty`（background:transparent + border:0 + `#cdd` 字 + monospace + 600 + cursor:pointer + hover `#2ea06c` + focus-visible outline）+ `.piece-card-qty.disabled`（`#666` 灰字 + cursor:not-allowed + hover 不高亮）；`.piece-card-body` 加 `cursor:zoom-in` + `:focus-visible` outline |
| `src/components/preview/__tests__/ParsedPiecesView.test.tsx` | 增量：原 8 项改造（「每片含 A/B/C+名+svg」→「每片含 label 徽章+序号(数量)+svg，无裁片名残留」；切码刷新断 `1(0)` 序号而非裁片名）+ 新增 11 项（序号 index+1 A=1/B=2/C=3 / qty 默认 0 渲染 1(0) / qty 从 qtyStore getPieceDisplay 读 per-size 5 / editable button 点击 openQtyDialog / global非source span.disabled+title 含「30」 / global source 仍为 button 可编辑 / body onClick openZoom / body role=button+tabIndex=0 / Enter 触发 openZoom / Space 触发 openZoom / qty stopPropagation 不冒泡到 body 触发 zoom） |
| `src/components/preview/__tests__/PreviewPage.test.tsx` | 增量：原 9 项改造（切码 30 的 names→qtyTexts 断 `1(0)/2(0)`）+ 新增 7 项（顶层默认不渲染两个模态 overlay / qtyDialog 写入自显隐 / zoom 写入自显隐 / uploadStore.reset() 联动清 quantities / 重传 doc_id 变化联动清 / 切 activeSize 数量保留 / 端到端：切码→点 qty→切 global+确定→切回原码→span.disabled+title 含「30」） |

### 关键不变量（上传预览 US-014 立，后续故事不得破坏）

1. **卡片头双模态入口严格分离** —— `.piece-card-qty`（在 head）点击 → openQtyDialog；`.piece-card-body`（SVG 包裹层）点击 → openZoom。两个交互入口由位置分离（head vs body 平级）+ stopPropagation 双重防御（qty button onClick 调 `e.stopPropagation()`，即使未来 qty 移到 body 内也不会冒泡触发 zoom）。改分离逻辑需同步 ParsedPiecesView.test.tsx「qty 不冒泡到 body」用例。
2. **.piece-card-qty 双形态渲染（button vs span.disabled）** —— editable=true（label 未配置 / per-size 模式 / global source 码）渲染 `<button>`，点击可编辑；editable=false（global 非 source 码）渲染 `<span class="disabled">`，不可点击 + native title 提供 hover 提示文案（reason=`'该数值已在「<sizeLabel(globalSource)>」处使用全局数量'`）。qty=0 正常显示 `序号(0)`（默认态，不特殊处理）。改双形态分支需同步「editable button / global非source span.disabled / global source button」3 项用例。
3. **序号 = pieces 数组 index+1（与 PieceZoomModal locatePiece.seq 同口径）** —— ParsedPiecesView 用 `pieces.map((p, idx) => seq = idx+1)`；PieceZoomModal 用 `locatePiece` 内 `pieces.findIndex+1`。两者口径一致（A=1, B=2, ...），依赖后端 `_label_for` 几何排序在码间稳定。改 seq 口径需同步两个组件 + 11 项 ParsedPiecesView 用例 + 14 项 PieceZoomModal 用例。
4. **.piece-card-body a11y：role=button + tabIndex=0 + aria-label + onKeyDown(Enter/Space)** —— 与 UploadPanel drop-zone 同模式（键盘用户可用 Tab 聚焦 + Enter/Space 触发 openZoom）。改 a11y 属性需同步「role+tabIndex / Enter / Space」3 项用例。aria-label=`放大预览裁片 ${label}` 给屏幕阅读器识别（与 PieceZoomModal aria-label 互补）。
5. **重传清零用 useUploadStore.subscribe（非 useEffect+ref 对比）** —— PreviewPage useEffect 内 `let prevDocId = getState().doc?.doc_id` + `subscribe((state) => { if (state.doc?.doc_id !== prevDocId) { prevDocId = ...; resetQuantities(); } })`。**subscribe 捕获所有 state 变化**（包括不触发 re-render 的 setState），比 useEffect+ref 对比 doc 更可靠（避免批处理跳过）。subscribe 在 unmount 时 unsub（无残留）。改实现需同步「reset 联动 / 重传清 / 切码保留」3 项用例。
6. **qtyStore 与 uploadStore 解耦（reset 联动在 PreviewPage 集成层）** —— uploadStore 不知道 qtyStore 存在（reset 仅清自身字段）；qtyStore 不知道 uploadStore 存在（resetQuantities 是独立 action）。**PreviewPage 作为集成层**用 subscribe 绑定两者。改耦合（如把 resetQuantities 调用挪到 uploadStore.reset 内）会破坏 store 解耦原则。
7. **uploadStore reset / 重传 / 切码三路径区分** —— reset（doc→null）+ 重传（doc_id 变化）触发 resetQuantities；切 activeSize（doc_id 不变）**不触发**（保留数量）。改分支需同步「reset 联动 / 重传清 / 切码保留」3 项用例。
8. **顶层模态单例（声明式受控 Portal）** —— PreviewPage 顶层挂 `<PieceQtyDialog/>` + `<PieceZoomModal/>` 各一个；两者默认 return null（qtyDialog=null / zoom=null），store 写入目标时自显隐。改挂载位置（如挪到 ParsedPiecesView 内）会破坏「单例」语义（每片卡片各挂一个会多实例 clobber）。Portal 到 document.body，DOM 位置与 React 树位置无关。
9. **不引入 CSS 框架** —— `.piece-card-qty` / `.piece-card-qty.disabled` / `.piece-card-body cursor:zoom-in` 全部沿用 style.css 命令式 className，与 piece-card / piece-qty-dialog / piece-zoom-modal 暗背景 + 绿色 `#2ea06c` 强调同色系。`.piece-card-name` 已删除（不再使用）。改 className 需同步组件 + 测试。
10. **未做浏览器验证（无 SVG/坐标变换）** —— 本故事无 SVG 渲染、坐标变换、可视化逻辑改动（仅卡片头 DOM 结构 + 模态挂载 + 点击处理 + CSS），AC 仅要求 typecheck + 单测 + build；浏览器验证留作整体回归（含放大模态显隐 / ✕/遮罩/ESC / 头部信息 / 卡片头序号(数量) / 置灰联动）。

## US-021 落地：useCommitToNesting（解析成功自动 commit + D1 闭环）

解析成功后系统自动把母版应用到超排（POST /api/commit-to-nesting → 后端 reload intermediate）并解锁超排 Tab，无需手动点「应用」（D1 一条龙）。commit 作为解析成功的副作用（void commit），不阻塞预览渲染（doc/status 先进 store → UI 先渲染 → commit 后台跑 → commit done 自动 setNestingEnabled，不自动切 Tab，由用户点击进入）。

### 新增 / 改造文件

| 文件 | 角色 |
| --- | --- |
| `src/hooks/useCommitToNesting.ts` | **新建** hook：`commit(doc_id, filename?) → Promise<{ok, summary?, error?}>`。fetch POST /api/commit-to-nesting JSON body。防连击（committingRef + commitStatus==='committing' 双重防护）。错误进 store 不抛。commit done → setNestingEnabled(true)（D1 闭环，解锁超排 Tab，**不自动切**）。commit fail → commitStatus='error' 不切 Tab（D5） |
| `src/hooks/useParseDxf.ts` | **改造**：解析成功（setState status='done'）后 `void commit(doc.doc_id, doc.filename)` 自动触发（D1 副作用，不阻塞预览）。进入 uploading 时同步清 commitStatus/commitError/commitSummary（重传清旧 commit 状态）。upload useCallback dep 加 `[commit]` |
| `src/store/uploadStore.ts` | **扩字段**：`commitStatus: 'idle' \| 'committing' \| 'done' \| 'error'`（默认 idle）+ `commitError: string \| null` + `commitSummary: { sizes: number[]; n_pieces: number; total_area_mm2: number } \| null`。`reset()` 同步清三个字段。CommitStatus + CommitSummary 类型导出 |
| `src/components/preview/UploadPanel.tsx` | **加 commit 状态行**：订阅 commitStatus/commitError/commitSummary。committing→`.upload-status.loading`「应用中…」；done+summary→`.upload-status.done`「已应用至超排：{n_pieces} 裁片，{sizes.length} 码」；error+commitError→`.upload-status.error`「应用失败：{msg}」。commit 行独立于 parse status 行（两行可同时显示：parse done + commit committing/done/error） |
| `src/hooks/__tests__/useCommitToNesting.test.tsx` | **新建** 15 项单测：fetch URL+method+body+Content-Type / 200→commitSummary+commitStatus=done / filename optional / 422→commitError / 404→commitError / 400→commitError / non-JSON error→statusText / 防连击仅一次 / committingRef reset after success / network error / commitStatus transition idle→committing→done / idle→committing→error / commit done→setNestingEnabled(true) 不自动切 Tab D1 / commit fail→不切 Tab D5 / entering committing clears stale error |
| `src/hooks/__tests__/useParseDxf.test.tsx` | **改造 + 新增**：原 15 项更新 fetch 计数（成功路径 +1 commit fetch，parse+commit=2 / 两次成功 upload=4）+ beforeEach/afterEach 加 uiStore reset（防 commit D1 副作用跨测试污染）。**新增 7 项 US-021 集成**：parse done→auto-trigger commit（验证 calls[1] body doc_id+filename）/ commit done→不自动切 Tab（D1，activeTab 仍 preview）/ commit done→nestingEnabled=true / commit fail→不切 Tab（D5）/ commit fail→commitError 显示 / commit done→commitSummary 渲染（n_pieces+sizes.length）/ parse fail→commit 不触发（fetch 仅 1 次） |
| `src/store/__tests__/uploadStore.test.ts` | **新增 5 项 commit 字段**：默认 idle/null/null / reset() 清 done 态 / reset() 清 error 态 / 订阅者收到 commitStatus 变化 / commitStatus 与 status 字段独立 |
| `src/components/preview/__tests__/UploadPanel.test.tsx` | **更新 2 项 fetch 计数**（parse+commit=2）+ beforeEach/afterEach 加 uiStore reset |

### 关键不变量（上传预览 US-021 立，后续故事不得破坏）

1. **自动 commit 是解析成功的副作用，不阻塞预览** —— useParseDxf 在 setState({status:'done', doc}) 后用 `void commit(doc.doc_id, doc.filename)`（不 await），让 doc/status 先进 store、UI 先渲染预览，commit 后台跑更新 commitStatus。改 `await commit(...)` 会阻塞 upload 返回、延迟预览上屏。
2. **commitStatus 与 parse status 分离（独立字段）** —— uploadStore 持两套状态机：`status`（parse: idle→uploading→done|error）+ `commitStatus`（commit: idle→committing→done|error），互不干扰。parse done 可以无 commit（parse fail 时）；commit done 必在 parse done 之后（commit 仅由 parse done 触发）。改合并状态会破坏「commit fail 不影响 parse done 预览可用」语义。
3. **D1 闭环：commit done → setNestingEnabled(true)（不自动切 Tab）** —— useCommitToNesting 在 commit 成功后显式调 setNestingEnabled(true)（与 PreviewPage subscribe parse done 重复但幂等），解锁超排 Tab；**不再 setTab('nesting')**——解析成功只解锁，由用户主动点击进入超排，避免劫持预览浏览。commit fail 不切 Tab（D5）。
4. **D5：commit fail 不切 Tab（Tab 仍解锁，用户可重试或用旧数据）** —— commit fail 时 commitStatus='error' + commitError 显示，但 activeTab 不被切到 nesting（用户留在 preview 看到错误）。nestingEnabled 仍为 true（parse done 已解锁），用户可手动点超排 Tab 用旧 intermediate 数据进入。
5. **防连击：committingRef + commitStatus==='committing' 双重防护** —— ref 立即生效（async 函数体同步段执行）；setState 异步生效，第二次连击会在 setState 调度前进 hook body。两者任一为 committing 即忽略（返回 {ok:false, error}，不抛错）。与 useParseDxf uploadingRef 同模式。
6. **fetch 用 JSON body（非 FormData）+ 手设 Content-Type** —— 与 useParseDxf（FormData + 不手设 Content-Type）不同：commit 传 doc_id/filename 引用（无文件数据），用 `JSON.stringify({doc_id, filename})` + `headers: {'Content-Type':'application/json'}`。改 body 格式需同步后端 server.py commit_to_nesting + useCommitToNesting.test.tsx AC#7 URL+method+body 用例。
7. **uploadStore reset 同步清 commit 字段** —— `reset()` 把 commitStatus='idle'/commitError=null/commitSummary=null（与 status/doc/error/qtyDialog/zoom 同步清）。useParseDxf 进入 uploading 时也清 commit 字段（重传时旧 commit 摘要不再适用）。改 reset 需同步 uploadStore.test.ts 25 项用例。
8. **不引入 CSS 框架** —— commit 状态行复用 `.upload-status.loading/.done/.error` 同三套 className（暗绿底/暗绿底/红字），与 parse status 行视觉一致；不新增 CSS 类。data-testid="commit-status" 区分 commit 行（parse 行 data-testid="upload-status"）。
9. **未做浏览器验证** —— 本故事无 SVG/坐标变换（仅 store 字段扩展 + hook + UploadPanel 状态行 DOM），AC 仅要求 typecheck + 单测 + build。浏览器视觉回归（「应用中…」loading + 「已应用至超排」摘要 + Tab 解锁（不自动切）+ commit fail 红字）留作整体回归。

## US-024 落地：NestSVG 5 层渲染 + 共享 LAYER5_COLORS（毛版 + 净版 + 内部线 + 刺口 + 布纹线）

NestSVG 在毛版 polygon（layer1）之上叠加 4 层工艺节点：净版（layer14 绿 dashed polygon）+ 内部线（layer8 橙 polyline 列表）+ 刺口（layer4 黄 line 短线段沿法线 NOTCH_LEN_MM）+ 布纹线（layer7 红 dashed line）。所有 5 层都在翻转组内（scale(1,-1)），共用 placement transform（rotation + translation）。求解碰撞仍只用毛版 polygon（sparrow NFP，已 erode），4 层仅渲染透传。PiecePreviewSVG 5 层配色提取到 `constants/colors.ts LAYER5_COLORS` 共享，与 NestSVG 视觉一致；导出 PNG/DXF 在后端 `web/export.py` 用相同配色（`LAYER5_COLOR_*` 字面量）。

### 新增 / 改造文件

| 文件 | 角色 |
| --- | --- |
| `src/types/piece.ts` | **扩 PieceInfo**：增可选 `net_polygon?: Polygon` / `internal_lines?: Polygon[]` / `notches?: Notch[]` / `grain_line?: GrainLine \| null`。**新增** `Notch = [number, number, number, number]`（x, y, nx, ny）+ `GrainLine = [number, number, number, number]`（x1, y1, x2, y2）类型。4 字段均可选 → 旧 manifest（无 5 层）仍类型兼容 |
| `src/constants/colors.ts` | **新增** `LAYER5_COLORS` 共享常量（`ROUGH_FILL: 'rgba(80,140,200,0.22)'` / `ROUGH_STROKE: '#3f7fbf'` / `NET: '#33cc33'` / `INTERNAL: '#ff8c1a'` / `NOTCH: '#ffd700'` / `GRAIN: '#e53e3e'`）+ 导出 `NOTCH_LEN_MM = 8`。被 PiecePreviewSVG + NestSVG 共用（视觉一致） |
| `src/components/preview/PiecePreviewSVG.tsx` | **改造**：5 层颜色字面量（`rgba(80,140,200,0.22)` / `#3f7fbf` / `#33cc33` / `#ff8c1a` / `#ffd700` / `#e53e3e`）→ `LAYER5_COLORS.*` import；`NOTCH_LEN_MM = 8` 字面量 → import。行为不变（仅配色来源统一） |
| `src/components/nests/NestSVG.tsx` | **扩 5 层渲染**：PieceEntry 增 `netEl: SVGPolygonElement \| null` / `internalEls: SVGPolylineElement[]` / `notchEls: SVGLineElement[]` / `grainEl: SVGLineElement \| null`。manifest 到达时按数据有无创建对应节点（pointerEvents='none'，不干扰毛版 polygon mousemove tooltip）。frame 渲染：placed → 5 层 setAttribute('points'/'x1'/'y1'/'x2'/'y2') + display=''；unplaced → 5 层 display='none'。notch 端点 = `P ± NOTCH_LEN_MM/2 * unit_normal` 各按 transformPt 变换；grain 端点按 transformPt 变换。新增 `transformPt(pt, rot, tr)` 辅助（与 lib/geometry pointsStr 同公式，单点版本） |
| `src/components/nests/__tests__/NestSVG.test.tsx` | **新增 8 项**：net polygon 渲染绿 dashed / internal 多条 polyline 渲染 / notch line 短线段渲染 / grain line 渲染 / 节点数 = 毛版 + 5 层总和 / frame setAttribute 写入 5 层 / unplaced 5 层 display:none / rotation≠0 时 transform 正确（transformPt 与 pointsStr 一致） |
| `src/__tests__/useSolveRun.test.tsx` | **新增 1 项**：manifest 含 5 层字段 → runRegistry 落盘保真（net_polygon/internal_lines/notches/grain_line 字段不丢失；p2 缺字段 → undefined 兼容） |

### 关键不变量（US-024 立，后续故事不得破坏）

1. **求解碰撞仅用毛版 polygon** —— `polygon` 是 erode 后的 base 多边形，与 sparrow NFP 一致；`net_polygon` / `internal_lines` / `notches` / `grain_line` 4 层**仅渲染/导出透传**，不影响求解结果或利用率。改任一层语义需同步 collect.LAYER_MAPPING + export_dxf + load_pieces + pieces_export + solver.pid_meta + web/export.py + NestSVG。
2. **5 层节点只在 manifest 到达时建一次** —— frame 切换只 setAttribute（points/x1y1x2y2/display），不重建 DOM；128 片 × 5 节点 ~10fps 可承受。改创建时机（如每帧重建）会破坏性能保护（AC#5）。
3. **4 层节点 pointerEvents='none'** —— 事件委托只触发于毛版 polygon（dataset.ptype 必有）；4 层工艺节点不参与 mousemove tooltip 联动。改 pointerEvents 会破坏 US-006 hover 语义。
4. **5 层都在翻转组内（scale(1,-1)）** —— 共用 `<g transform="translate(0 gate) scale(1 -1)">`，与 US-003 关键约定 #1 一致。改其中一层挪出翻转组会破坏视觉一致性（上下颠倒）。
5. **notch 端点变换：点按 point 变换 + 法线按 vector 旋转** —— notch 数据模型 `(x, y, nx, ny)`，端点 = `(x ± half*nx, y ± half*ny)` 各按 rot+tr 变换（同 pointsStr 公式，单点版本 transformPt）。half = NOTCH_LEN_MM/2 = 4。法线为零向量（退化边）→ 0 长度线段兜底，不渲染异常。
6. **LAYER5_COLORS 是 NestSVG + PiecePreviewSVG 视觉一致的单一真相源** —— 后端 `web/export.py LAYER5_COLOR_*` 字面量需与此同步（绿 `#33cc33` / 橙 `#ff8c1a` / 黄 `#ffd700` / 红 `#e53e3e`）。改任一层配色需同步两处。
7. **layer-aware 缺字段跳过** —— 旧 intermediate（无 5 层字段）的 piece → netEl/internalEls/notchEls/grainEl 为 null/空，渲染时跳过；新 intermediate（含 5 层）自动多画 4 层。前后端均用 `.get()` / `?? []` / `if (p.net_polygon && len>=3)` 兜底，向后兼容。
8. **manifest 字段保真（runRegistry 落盘无丢失）** —— useSolveRun onManifest 把 ServerMsg 直接写 runRegistry；TS 类型 `ManifestMsg.pieces: PieceInfo[]` 已扩 5 层字段，JSON.stringify 保真。
9. **ET2008 兼容性硬验收（D4）** —— marker DXF 多 layer（outline layer1 + net layer14 + internal layer8 + notch layer4 + grain layer7）各自独立 POLYLINE/POINT/LINE entity（R12 + POLYLINE 非 LWPOLYLINE）。若 ET2008 误读则回退为 "DXF 仅外轮廓、PNG 含 5 层"（D4 应急回退）。改 entity 类型需同步 ET2008 兼容性测试。

## US-002 落地：WS 契约 + RunRegistry + useSolveRun

| 文件 | 角色 |
| --- | --- |
| `src/types/v03.ts` | `SolveParams`（d_ext/d_int/tol_ext/tol_int）+ `PerTypeOverride` / `PerTypeOverrides` |
| `src/types/ws.ts` | `StartPayload`（US-022 扩 `quantities: Record<string, Record<string, number>> \| null`）+ `ServerMsg = ManifestMsg \| FrameMsg \| FinalMsg \| ErrorMsg` 判别联合（density/density_sparrow 双口径都在 FrameMsg/FinalMsg） |
| `src/lib/ws.ts` | `solveWsUrl()` —— `${proto}://${location.host}/ws/solve`（dev/prod 自适配，**不要写死 :8000/:5173**） |
| `src/store/runRegistry.ts` | 模块级 mutable 数组持有 RunRecord（frames/lastFrame 不进 React state）；提供 `create / clear / list / bestRun` |
| `src/hooks/useSolveRun.ts` | 单 run 生命周期：`start(cfg)` 显式 `new WebSocket` → onmessage 分发 manifest/frame/final/error → Registry 落盘 + 回调；onclose/onerror → onDone（done flag 防重复），**不重连** |
| `src/__tests__/useSolveRun.test.tsx` | 8 项单测：StrictMode 双 mount 0 连接 / StartPayload 字段逐项（含 US-022 quantities=null）/ manifest+frame+final 分发 + Registry 落盘 / error 分支 / URL 相对 host / per_type 透传 / US-022 quantities 非空透传 / US-022 quantities 缺省→null |

## US-003 落地：NestSVG 命令式渲染 + 节流闸（单 seed 可视化）

| 文件 | 角色 |
| --- | --- |
| `src/lib/geometry.ts` | `r2(x)` 四舍五入 2 位 + `pointsStr(poly, rot, tr)` —— 与旧 vanilla 实现 / 后端 `_transform_polygon` 字节级一致 |
| `src/store/appStore.ts` | Zustand 单字段 store：仅持 `renderTick`（+ `bumpRenderTick` action）；高频 frames 落 runRegistry 不进 React state |
| `src/hooks/useRafThrottle.ts` | `useRafThrottle(active)` —— active=true 时 rAF + 100ms 时间戳闸 bump renderTick；隐藏标签页自动暂停 |
| `src/components/nests/NestSVG.tsx` | 命令式 SVG：JSX 仅 `<svg ref/>`；manifest 到达后 imperative 建 bg/fab/flipGroup + N polygon；订阅 renderTick setAttribute('points'/'display') |
| `src/components/nests/NestLabel.tsx` | 顶部标签：`seed N · X.XX%`；订阅 renderTick 重渲染（轻量文本，可走 reconciliation） |
| `src/components/nests/NestCard.tsx` | 单 run 卡片容器（NestLabel + NestSVG） |
| `src/App.tsx` | US-003 拼装：硬编码 sizes=[30,32]/time=30/seed=0/baseline；按钮触发 useSolveRun.start + useRafThrottle(seeds.length>0) |
| `src/lib/__tests__/geometry.test.ts` | 5 项：r2 截断 / pointsStr 与旧 vanilla 实现 字节级一致（9 组对比）/ 0°/90° 可视化 sanity / 输出无尾随空格 |
| `src/components/nests/__tests__/NestSVG.test.tsx` | 8 项：空骨架 / manifest 建全 DOM（含 transform）/ 重复 bump 不重建 / frame 写 points + display / 旋转 90° 输出 / placed↔未 placed 切换 / 无 frame 不写 viewBox / 后到 manifest 路径 |

## US-004 落地：v0.3 参数面板（ControlPanel）

| 文件 | 角色 |
| --- | --- |
| `src/constants/sizes.ts` | `SIZES = [28,29,30,31,33,34,35,36]`（M1787 8 码跳 32；与后端 `nesting_bounds.DEFAULT_SIZES` 一致） |
| `src/constants/colors.ts` | `PHASE_COLORS`（exploring/compressing/final）+ `SEED_COLORS`（6 seed；US-005 ConvergenceCurve 消费） |
| `src/constants/v03.ts` | `V03_TABLE` 全 10 片型工艺上限（d / tol / internal；与后端 `constraints.py MAX_OVERLAP / ROTATION_TOL` 1:1）+ `V03_PTYPES` 顺序 |
| `src/lib/params.ts` | `FormState`（US-019 起：删 d_ext/d_int/tol_ext/tol_int 字段，per_type 是唯一 d/tol 入口）+ `DEFAULT_FORM` + `collectParams(form)` 纯函数（US-019 起 params 永远全 0，per_type 解析逻辑保留）+ `parseSeed / parseTime / parseSeedCount` + US-022 `serializeQuantities(qtyMap, sizes)` 纯函数（qtyStore.quantities → WS payload label→sizeKey→demand；per-size 取 perSize，global 展开 globalValue） |
| `src/components/ControlPanel/ControlPanel.tsx` | 顶层面板：持 form state；StartButton 触发校验 + collectParams + onStart(cfg) 透传到 App（cfg 含 seed_count）；US-017 订阅 uploadStore.doc，doc=null 时 StatusLine 增「请先在上传预览页解析母版」提示，handleStart/handleExport 过滤 form.sizes 中的 null（保持下游 WS/export 的 number[] 契约）；US-019 删除 ErodeInputs/ToleranceInputs 渲染，主面板不再有内外两档输入；US-022 handleStart 调 serializeQuantities(qtyStore.quantities, sizesNum) 填 cfg.quantities（getState 不订阅，避免数量编辑频繁重渲染） |
| `src/components/ControlPanel/SizePicker.tsx` | US-017：码号 chip 复选（受控）。订阅 `useUploadStore(s=>s.doc)` 动态读码号：doc 非空 → `doc.sizes.map(s=>s.size)`（不二次排序）；doc=null → fallback `constants/sizes.ts:SIZES`。null 码 chip 显示「通用」（与 SizeTabs NULL_SIZE_LABEL 同语义）；selected/onChange 类型 `(number\|null)[]` |
| `src/components/ControlPanel/ParamForm.tsx` | 时长 / base seed 输入（min/max 与旧 index.html 一致） |
| `src/components/ControlPanel/MultiSeedControls.tsx` | US-005：多 seed 对比 checkbox `#multi_seed` + 数量 input `#seed_count`（min=2 max=6 default 3） |
| `src/components/ControlPanel/PresetButtons.tsx` | 预览 120s / 精排 600s 一键填 |
| `src/components/ControlPanel/PerTypeOverrides.tsx` | 渲染 V03_PTYPES 10 行；internal=true 加 `<i>内</i>` 徽章；placeholder 提示 d≤/t≤ 上限 |
| `src/components/ControlPanel/StartButton.tsx` | 启动按钮（id="start"，沿用 legacy CSS 选择器） |
| `src/components/ControlPanel/StatusLine.tsx` | 状态行（id="status"，沿用 legacy CSS） |
| `src/components/nests/NestsGrid.tsx` | US-005：seeds → runRegistry.list().find(seed) → NestCard 列表；key=seed 稳定 |
| `src/components/curve/ConvergenceCurve.tsx` | US-005：命令式 SVG（React 仅 `<svg ref/>`；子节点 innerHTML 写入）。订阅 renderTick；导出 sampleFrames / renderCurveInto 纯函数 |
| `src/App.tsx` | US-005：handleStart 启 N 个 WS（seed=base+i）；doneCountRef/totalSeedsRef all-done 检测；多 seed setStatus summary+best |
| `src/lib/__tests__/params.test.ts` | US-019 重写：默认 params 全 0 + per_type=null / params 永远全 0（4 组 form 对比）/ FormState 无 d_ext/d_int/tol_ext/tol_int 字段断言 / per_type 单档非空 entry / 全空白 → null / 多片型混合 / 显式 "0" 区分空 / 全 10 ptype 填 / parseSeedCount 7 组（单 seed → 1 / multi + 默认 3 / clamp 2,6 / fallback 3） |
| `src/components/ControlPanel/__tests__/ControlPanel.test.tsx` | 24 项：AC#1..#7 集成（US-017 起默认 sizes=[] 全未勾选；US-019 起主面板不再渲染 d_ext/d_int/tol_ext/tol_int 输入 + 新增「不再渲染两档」断言）+ US-005 multi_seed/seed_count 5 项 + US-007 export wiring 4 项 + US-017 StatusLine hint 4 项 |
| `src/components/ControlPanel/__tests__/SizePicker.test.tsx` | US-017 8 项：doc=null fallback SIZES / doc 11 码渲染全 11 / null 通用码 / 切 doc 自动重渲染 / toggle 数字 chip / toggle null chip / selected 含 null / key-id 唯一 |
| `src/components/nests/__tests__/NestsGrid.test.tsx` | US-005 6 项：空容器 / N 卡渲染 / registry 缺失跳过 / 顺序与 seeds 一致 / seeds 不变不重复挂载 / seeds 增减跟着变 |
| `src/components/curve/__tests__/ConvergenceCurve.test.tsx` | US-005 14 项：sampleFrames 4（空 / ≤400 / >400 / 整除）+ 渲染 10（90% 线 / 单 seed 散点+折线+末点 / 多 seed 折线+标签 / 单/多 seed 图例 / renderTick 订阅 / 多次 bump 不重建 / renderCurveInto 纯函数） |

## US-006 落地：回放 seekbar + 片 hover tooltip

| 文件 | 角色 |
| --- | --- |
| `src/lib/seek.ts` | 纯函数 `maxElapsed(runs)` + `frameAtTime(container, t)` 二分查找（与旧 vanilla 实现 `maxElapsed` / `frameAtTime` 字节级一致）；FrameContainer 最小接口解耦 RunRecord |
| `src/store/appStore.ts` | 加 `seekTime: number`（默认 -1 = live）+ `setSeekTime(t)`；renderTick/seekTime 共用同一 zustand store |
| `src/components/Tooltip.tsx` | React Portal 到 body 的单例浮层；模块级 `_el` / `_hovered` 单例 + `showTooltip / hideTooltip / setHovered / clearHovered` 命令式 API（高频 mousemove 不进 React state） |
| `src/components/playback/Seekbar.tsx` | 受控 `<input id="seek" type="range">`；disabled 时 max=0 value=0；启用时 max=ceil(maxElapsed)，value=seekTime（或末尾 fallback） |
| `src/components/playback/SeekReadout.tsx` | `t=X.Xs \| sN yy.yy% \| sM zz.zz%` 文本；未全完成显示 "—"；订阅 renderTick+seekTime |
| `src/components/playback/PlaybackBar.tsx` | `.playback` 容器（field-label + Seekbar + SeekReadout）；订阅 renderTick 算 allDone/max |
| `src/components/nests/NestSVG.tsx` | 增量：useEffect 加 `seekTime` dep，`f = seekTime>=0 ? frameAtTime(run,seekTime) : run.lastFrame`；flipGroup 上事件委托 mousemove+mouseleave（AC#4..#6） |
| `src/App.tsx` | 增量：全完成时 `setSeekTime(ceil(maxElapsed))`；handleStart 内 `setSeekTime(-1) + clearHovered + hideTooltip`；挂一个 `<Tooltip/>` |
| `src/lib/__tests__/seek.test.ts` | 16 项：frameAtTime 9（空 / 单 / 边界 / 等价线性 / 10/1000 帧 stress / duplicate elapsed）+ maxElapsed 6（空 / 多空 / 单 / 多 / 混合 / RunRecord 兼容） |
| `src/components/__tests__/Tooltip.test.tsx` | 11 项：Portal 到 body + 初始 display:none / showTooltip +14 偏移 / hideTooltip / setHovered 加 class / 同一 polygon 幂等 / 切换 polygon 移除旧 / setHovered(null) / clearHovered / no-op 兜底 |
| `src/components/playback/__tests__/PlaybackBar.test.tsx` | 9 项：无 run disabled / 求解中 disabled / 全完成启用 / ceil 非整数 / readout 单 seed / readout 多 seed / 拖动 setSeekTime / seekTime=-1 fallback 末尾 / disabled max=0 value=0 |
| `src/components/nests/__tests__/NestSVG.seek.test.tsx` | 11 项：seek 5（live / 切 frameAtTime / 边界 / 超末帧 / 无 frame）+ hover 6（mousemove 显 tooltip+加 class / 非 polygon 隐 / 切换 polygon 移除旧 / 面积换算 / mouseleave / seekTime 切换不丢 listener） |

## US-007 落地：导出 PNG / DXF

| 文件 | 角色 |
| --- | --- |
| `src/lib/download.ts` | `parseContentDisposition(cd, fmt)` —— RFC 5987 `filename*=UTF-8''xxx` → decodeURIComponent；fallback `filename="xxx"` / `filename=xxx` / `nesting.<fmt>`；`downloadBlob(blob, name)` —— `<a download>` + `URL.createObjectURL` + 10s revoke（与旧 vanilla 实现 exportAs 字节级一致） |
| `src/hooks/useExport.ts` | `useExport({ onStatus }) → { exportAs, exporting }`。exportAs(fmt, sizes)：bestRun（registry.bestRun()）→ POST `/export` {fmt, sizes, seed, gate_mm, width_mm: lastFrame.width_mm, density: run.finalDensity, placed: lastFrame.placed_items}（AC#2 逐字段对齐旧 vanilla 实现）→ blob → parseContentDisposition → downloadBlob。防连击：exportingRef + state 同步；exporting=true 时再次调用静默忽略。错误：res.ok=false 读 json.error / fetch throw → onStatus(`导出失败：…`) |
| `src/components/ControlPanel/ExportButtons.tsx` | `<ExportButtons solving exporting onExport/>` —— `.export-group` 容器 + 2 个 `button.export`（id `export_png`/`export_dxf` 沿用 legacy CSS）。disabled = solving \|\| exporting \|\| !hasLastFrame；订阅 renderTick（lastFrame 到达后 bump → 重算 hasLastFrame = `registry.list().some(r => r.lastFrame)`，与旧 vanilla 实现 updateExportButtons 一致） |
| `src/components/ControlPanel/ControlPanel.tsx` | 持 useExport({ onStatus })；handleExport(fmt) → exportAs(fmt, form.sizes)（sizes 来自本组件 form，与旧 vanilla 实现 `selectedSizes()` 同源）；JSX 把 `<ExportButtons>` 挂在 `<StatusLine>` 后（与 legacy index.html 顺序一致） |
| `src/lib/__tests__/download.test.ts` | 13 项：parseContentDisposition 10（RFC 5987 中文 / RFC 5987 ASCII / filename="xxx" / filename=xxx / 空 CD / 无 filename / malformed URI 落 fallback / filename* 空 / filename* 优先 / 大小写不敏感）+ downloadBlob 3（appendChild+click+remove+10s revoke / download 属性 = filename / href = ObjectURL） |
| `src/__tests__/useExport.test.tsx` | 15 项：无 lastFrame onStatus + 不发 fetch / bestRun 多 run 取最高密度 / ExportPayload 逐字段对齐旧 vanilla 实现 / fetch URL = `/export` / exporting 状态切换 + onStatus 正在生成 / DXF fmt 文案 / CN 文件名 decode（AC#5）/ res.ok=false 用 json.error / json 抛错用 statusText / fetch reject 用 error.message / 非 Error 用 String / 防连击仅发一次 / sizes 透传 / gate_mm 来自 manifest / 并列密度取首个 |
| `src/components/ControlPanel/__tests__/ExportButtons.test.tsx` | 14 项：DOM 结构（export-group / 2 button / id / 标签 / hint）/ disabled 条件 4（无 lastFrame / solving / exporting / 全满足启用）/ onExport(png) / onExport(dxf) / renderTick 订阅 lastFrame 启用 / clear + bump 禁用 / 多 run / 无 lastFrame run |

### 关键不变量（US-007 立，后续故事不得破坏）

1. **ExportPayload 七字段与旧 vanilla 实现 exportAs 字节级一致** —— `{ fmt, sizes, seed, gate_mm, width_mm, density, placed }`，其中 `width_mm = run.lastFrame.width_mm`、`density = run.finalDensity`、`placed = run.lastFrame.placed_items`、`gate_mm = run.manifest.gate_mm`（多 run 共享，与旧 vanilla 实现 全局 `gateH` 同源）。改任一字段需同步 `useExport.test.tsx` 的 AC#2 用例 + `__tests__/ExportButtons.test.tsx`。
2. **bestRun = lastFrame 存在且 finalDensity 最高** —— runRegistry.bestRun() 已封装该逻辑（`for r of list: if !r.lastFrame continue; if r.finalDensity > best.finalDensity: best = r`）。并列密度取首个创建的 run。修改算法必须同步 `useExport.test.tsx` 的 bestRun 用例。
3. **parseContentDisposition 优先级** —— `filename*=UTF-8''xxx` > `filename="xxx"`/`filename=xxx` > `nesting.<fmt>`。decodeURIComponent 抛 URIError → 落到下一优先级（不能让导出整体失败）。改顺序必须同步 `download.test.ts` 10 个 parseContentDisposition 用例。
4. **downloadBlob 必须appendChild → click → remove → setTimeout(revoke, 10000)** —— 与旧 vanilla 实现 字面量一致（10s revoke 给浏览器下载请求足够时间）。jsdom 测试需 stub `URL.createObjectURL` + `HTMLAnchorElement.prototype.click`（jsdom click 触发 navigation 警告 + URL.createObjectURL 未实现）。
5. **ExportButtons 订阅 renderTick 而非 runRegistry** —— lastFrame 是 mutable push 不进 React state；通过 `useAppStore(s => s.renderTick)` + `void renderTick` 触发 reconciliation 后重算 `hasLastFrame = runRegistry.list().some(r => r.lastFrame !== null)`。改订阅源会破坏「求解 final 后按钮启用」联动。
6. **防连击 useExport 必须用 ref + state 双重防护** —— `exportingRef.current` 立即生效（async 流程内读到最新值）；`exporting` state 触发 UI disabled。仅靠 state 会有 race（state 异步生效，连击第二次在 setExporting(true) 调度前已进入 async body）。
7. **DOM id `export_png` / `export_dxf` 沿用 legacy CSS 选择器** —— style.css `button.export` 不依赖 id，但保留 id 便于测试 + 未来 US-008 去 id 时一并清理。改 id 需同步 `__tests__/ExportButtons.test.tsx` 14 项 + `__tests__/ControlPanel.test.tsx` 4 项 US-007 集成。
8. **onStatus 由 useExport 透传到 ControlPanel → App.setStatus → StatusLine** —— 「正在生成 PNG/DXF…」「已导出 …」「导出失败：…」「无可导出的方案（请先求解）」四类文案由 useExport 写，ControlPanel 不参与组装。改文案需同步 `useExport.test.tsx` 4 个 onStatus 断言。
9. **服务端文件名 `pct` 而非 `%`** —— `server.py export` 路由拼 `fname_cn = 排料_码{sizes_str}_{pct:.2f}pct_seed{seed}.{ext}`（不是 `88.42%`）。AC#5 字面写 `%` 是文档误差；实际下载文件名是 `排料_码28-30-32_88.42pct_seed0.png`。改文件名格式需同步后端 server.py + useExport.test.tsx 的 CN decode 用例。

### 关键不变量（US-006 立，后续故事不得破坏）

1. **`seekTime = -1` 是 live 标志，不是合法时间** —— NestSVG / SeekReadout 必须先判 `seekTime >= 0` 再走 frameAtTime 分支；负值回退 lastFrame（live）。改默认值需同步 `PlaybackBar.test.tsx` + `NestSVG.seek.test.tsx`。
2. **App 全完成时 setSeekTime(me)，新 start 时 setSeekTime(-1)** —— `me = Math.ceil(maxElapsed(runRegistry.list()))`，与旧 vanilla 实现 `$('seek').value = me` 一致；handleStart 内必须同时 clearHovered + hideTooltip（防 DOM 残留）。
3. **Tooltip 是模块级单例** —— `_el` / `_hovered` 是模块顶层的 let 变量；Tooltip 组件 mount 时 registerTooltipEl，NestSVG mousemove 处理器调 showTooltip/hideTooltip/setHovered。**App 内只能挂一个 `<Tooltip/>`**（多挂会互相 clobber）。
4. **Tooltip style 只能由 imperative 写** —— Tooltip 组件 JSX 不带 `style` prop（仅 className）；display/left/top/innerHTML 由 showTooltip/hideTooltip 直接 mutate。React reconciliation 不会覆盖。修改时不要在 JSX 加 style，否则重渲染会 reset display:none。
5. **frameAtTime 二分必须与旧 vanilla 实现 字节级一致** —— `lo=0, hi=n-1, ans=0; while (lo<=hi) { mid=(lo+hi)>>1; if (frames[mid].elapsed<=t) {ans=mid; lo=mid+1} else hi=mid-1 }`；返回 frames[ans]。改算法必须同步 `seek.test.ts` 9 个 frameAtTime 用例（含 1000 帧 stress）。
6. **flipGroup 上事件委托 mousemove + mouseleave（不是 svg）** —— AC#4 明确要求；与旧 vanilla 实现 setupHover(svg) 行为等价（多边形均在 flipGroup 内）。listener 在 `if (run.manifest && !flipRef.current)` 块内 attach，幂等保护防止 StrictMode 双 mount 双注册。
7. **面积换算 `mm² → cm²` 用 `÷100`** —— `parseFloat(dataset.area)/100`，与旧 vanilla 实现 一致；toFixed(1)。改单位 / 精度需同步 `NestSVG.seek.test.tsx` AC#4 用例。

### 关键不变量（US-005 立，后续故事不得破坏）

1. **`ControlPanelStartPayload.seed_count` 是已 clamp 的最终值** —— `parseSeedCount(form)` 返回 1（multi_seed=false）或 clamp(parseInt||3, 2, 6)；App.handleStart 直接 `for (let i=0; i<seed_count; i++) start({...cfg, seed: base+i})`，不做边界检查。修改默认 / clamp 边界需同步 `params.test.ts` 7 个 parseSeedCount 用例 + `ControlPanel.test.tsx` 5 个 multi-seed 用例。
2. **ConvergenceCurve 命令式 innerHTML** —— React 仅渲染 `<svg ref/>`；子节点（line/text/circle/path/g.legend）通过 `svg.innerHTML = out` 一次性写入。**不要改成 JSX**（每帧 diff 开销爆炸）。采样 / 配色 / 字面量与旧 vanilla 实现 drawCurve 字节级一致；`sampleFrames` / `renderCurveInto` 导出便于纯函数测试。
3. **采样算法** —— `step = max(1, floor(n/400))`；`pts = frames[0::step]`；`if (pts[last] !== frames[last]) pts.push(frames[last])`（末帧强制纳入）。改算法必须同步 `__tests__/ConvergenceCurve.test.tsx` 4 个采样用例。
4. **App all-done 检测用 ref 不用 state** —— `doneCountRef.current += 1; if (< totalSeedsRef.current) return;`；每次 handleStart 重置两个 ref。多 seed 收尾 setStatus 含 summary + best（`runs.reduce((a,r) => r.finalDensity > a.finalDensity ? r : a)`）。
5. **配色：单 seed 走 PHASE_COLORS[phase]（散点）+ 默认蓝 `#1f77b4`（折线/末点）；多 seed 走 SEED_COLORS[ri]（折线/末点/标签/图例）**。`multi = runs.length > 1`（不是 multi_seed 表单值）。
6. **useRafThrottle(seeds.length>0) 不在 solving=false 时停** —— 求解结束后曲线 / NestLabel 仍需 bump 重绘最终态；下次 start() 才会 `runRegistry.clear + setSeeds([])` 间接停掉。
7. **NestsGrid 只在 seeds 变化时挂载/卸载** —— `<NestCard key={seed} run={rec}/>` 稳定 key；NestSVG 内部已订阅 renderTick 自更新，NestsGrid 不参与高频重绘。

### 关键不变量（US-004 立，后续故事不得破坏）

1. **表单字段全字符串存储** —— `FormState` 所有 number 字段（time/seed/seed_count）以及 `per_type[pt].d/tol` 都按 `input.value` 字符串持有；`collectParams / parseTime / parseSeed` 做解析。理由：per_type 必须「空串 = 继承」与「"0" = 显式 0」可区分。（US-005 加 multi_seed: boolean / seed_count: string 同样按字符串存。）US-019 删 d_ext/d_int/tol_ext/tol_int 字段后，主面板只有 time/seed 字段是 number 字符串；d/tol 全交 per_type。
2. **collectParams 不变量（US-019 修订）** —— params 永远全 0（主面板内外两档输入已删，v0.3 上限交给 per_type 显式覆盖 + constraints.MAX_OVERLAP/ROTATION_TOL 兜底）；per_type 解析逻辑保留：仅 `trim() !== ''` 时写入；最终 per_type 整体空 → null（Python 侧 `or None` 接住）。修改必须同步 `lib/__tests__/params.test.ts`。
3. **DEFAULT_FORM（US-019 修订）** —— time="60"、seed="0"；multi_seed=false / seed_count="3"；sizes=[]（US-017 强制用户选）；per_type 全空 = 继承 v0.3 默认。修改任一字段需同步更新 AC#2。
4. **ControlPanel 不调 useSolveRun** —— 仅通过 `onStart(cfg)` 把载荷交给 App（解耦：未来多 seed / 重连逻辑由 App 决定）。`onStatus` 用于码号校验失败回写状态行。
5. **DOM id / className 沿用 legacy** —— `id="start" / id="status" / id="time" / id="seed"` 等保留（CSS 选择器依赖）；`.sizes / .per_type / .pt-row / .chip / .preset / .pt-name i` 等 className 1:1。US-005 新增 `id="multi_seed" / id="seed_count"` + `.cb / .seed-count` 同样沿用 legacy。US-019 删除 `id="d_ext" / id="d_int" / id="tol_ext" / id="tol_int"`（旧 ErodeInputs/ToleranceInputs 文件移除；CSS 规则保留向后兼容）。US-008 清理 CSS 时再统一去 id。
6. **PerTypeOverrides 行序 = V03_PTYPES 顺序** —— 不可重排（影响测试 placeholder / 徽章断言）；`<i>内</i>` 仅 internal=true 的 4 片型（单排/双排/火机袋/裤耳）。

### 关键不变量（US-003 立，后续故事不得破坏）

1. **React 只渲染空 `<svg>` 一次** —— NestSVG 所有子节点（bg rect / 用布 rect / 翻转组 `<g>` / N 个 `<polygon>`）必须 imperative 创建，用 `useRef` 持有；任何 JSX prop 写入都会被 reconciliation 覆盖。
2. **翻转组 transform 必须用 `setAttribute` 写** —— `translate(0 ${gate_mm}) scale(1 -1)`，对应 sparrow Y 向上 → SVG Y 向下（与 PNG / R12-DXF 导出一致）。
3. **renderTick 单字段节流** —— `appStore` 只持 `renderTick` 一个字段；frames / lastFrame 仍 mutable 在 runRegistry 里；高频渲染通过订阅 renderTick → useEffect 重跑 → setAttribute。
4. **pointsStr 字节级对齐** —— `rad=rot*π/180; c=cos; s=sin; x'=x*c−y*s+tx; y'=x*s+y*c+ty`，每点 `r2(x),r2(y)` 空格分隔，无尾随空格。修改必须同步 `lib/__tests__/geometry.test.ts` 与后端 `_transform_polygon`。
5. **flipRef 幂等保护** —— effect 用 `if (run.manifest && !flipRef.current)` 防 StrictMode 双 mount / 多次 tick 重建 DOM。
6. **viewBox 用历史最大 width 作稳定锚** —— `W = max(run.viewBoxMaxW, lastFrame.width_mm, 1)`，与旧 vanilla 实现 一致，避免收缩抖动。

### 关键不变量（US-002 立，后续故事不得破坏）

1. **WS 连接只在 `start()` 显式开** —— 不在 useEffect 里 auto-connect，否则 React 18 StrictMode 双 mount 会双连。
2. **frames 是 mutable 引用** —— `runRegistry.list()` 返回的元素本身可被 hook 直接 push，不触发任何 React 调度；高频渲染由 US-003 的 `renderTick` 单字段节流。
3. **per_type 空 → 序列化为 null** —— 与旧 vanilla 实现 `collectParams` 一致（Python 侧 `or None` 接住）。
4. **`density` vs `density_sparrow` 双口径** —— `density` 是原面积口径（= `total_area / (width*gate)`，与 90% 生死线一致），`density_sparrow` 是 erode 后 sparrow 自报（参考）。前端**任何决策 / 显示都优先 density**。
5. **测试需设 `IS_REACT_ACT_ENVIRONMENT = true`** —— 否则 `act()` 会警告（但仍能跑）。Mock WebSocket 用 ctor 返回 mock 实例的方式（`new WebSocket(url)` 拿到的是 mock）。

## 与旧 vanilla 的对应（迁移基线）

| 旧（vanilla 前身） | 新位置（计划） | 故事 | 状态 |
| --- | --- | --- | --- |
| `SIZES` `PHASE_COLORS` `SEED_COLORS` `V03` 常量 | `src/constants/*.ts` | US-004 | **已落地** |
| `WebSocket` + `onmessage` dispatch | `src/lib/ws.ts` + `src/hooks/useSolveRun.ts` | US-002 | **已落地** |
| `makeRun`/`renderFrame`/`pointsStr` 命令式 SVG | `src/components/nests/NestSVG.tsx` + `src/lib/geometry.ts` + `src/components/nests/NestCard.tsx` + `src/components/nests/NestLabel.tsx` | US-003 | **已落地** |
| 全局节流闸（`globalLastDraw` + `RENDER_INTERVAL_MS`） | `src/store/appStore.ts`（renderTick 单字段）+ `src/hooks/useRafThrottle.ts` | US-003 | **已落地** |
| `collectParams` + `per_type` 面板 | `src/lib/params.ts` + `src/components/ControlPanel/*` | US-004 | **已落地** |
| `multi_seed` / `seed_count` + makeRun 多 seed | `src/components/ControlPanel/MultiSeedControls.tsx` + `src/lib/params.ts parseSeedCount` + `src/App.tsx handleStart` | US-005 | **已落地** |
| `drawCurve` 收敛曲线 | `src/components/curve/ConvergenceCurve.tsx` | US-005 | **已落地** |
| `#nests` 多 seed 容器 | `src/components/nests/NestsGrid.tsx` | US-005 | **已落地** |
| `seek` `frameAtTime` 回放 + tooltip | `src/components/playback/*` + `src/lib/seek.ts` + `src/components/Tooltip.tsx` + `src/components/nests/NestSVG.tsx`（seek+hover） | US-006 | **已落地** |
| `exportAs(fmt)` | `src/hooks/useExport.ts` + `src/components/ControlPanel/ExportButtons.tsx` + `src/lib/download.ts` | US-007 | **已落地** |
| SizePicker 动态读码号 + DEFAULT_FORM.sizes=[] | `src/components/ControlPanel/SizePicker.tsx`（subscribe uploadStore.doc）+ `src/lib/params.ts`（FormState.sizes `(number\|null)[]` / DEFAULT_FORM.sizes=[]）+ `src/components/ControlPanel/ControlPanel.tsx`（doc=null hint + filter null） | US-017 | **已落地** |
| run 状态（frames 数组 / lastFrame / finalDensity） | `src/store/runRegistry.ts` | US-002 | **已落地** |

## 已知差异（脚手架阶段）

- `src/App.tsx` US-001 起只保留 Tab 骨架（TabBar + 双 `.page` 容器 + Tooltip 单例）；原 US-005 多 seed / US-006 seek 状态机全部下移到 `src/components/NestingPage.tsx`（行为字节级保留，仅容器由 `<div className="app">` 改为 Fragment 直挂 `.page` flex）。
- `src/style.css` 由 vanilla 前身 1:1 迁入，未做 React 化拆分（沿用命令式 + 类名约定，CSS 框架不引入）。US-001 加 `.tabbar/.tab/.tab-content/.page/.page.hidden/.preview-empty` 暗色样式（与 ControlPanel 同色系）。
- `static/` US-008 起已加入 `.gitignore`（构建产物不入库）；prod 模式前必须 `npm run build` 生成。
- 导出（US-007）已落地：ControlPanel 持 useExport，ExportButtons 渲染 PNG/DXF 按钮（disabled 联动 solving/exporting/无 lastFrame）。详见 US-007 章节。
- ControlPanel DOM 沿用 vanilla 前身 id（`start / status / time / seed / multi_seed / seed_count / export_png / export_dxf` 等）以复用 CSS。US-019 删除 `id="d_ext" / id="d_int" / id="tol_ext" / id="tol_int"`（主面板内外两档输入移除）。
- 上传预览页（PreviewPage）US-001 仅占位（提示卡片），待 US-008 落地 SizeTabs + ParsedPiecesView + 容器布局（左 UploadPanel + 右切码 + 裁片 grid）。US-006 UploadPanel + US-007 PiecePreviewSVG 已落地，等 US-008 拼装。
