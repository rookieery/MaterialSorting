# materialSorting-web — Agent 速查

> React 18 + TypeScript 5 + Vite 5 前端。改这里之前先看 `.docs/technical/agent-component-map.md`。

## 启动 / 构建 / 校验

```bash
npm install                # 首次装依赖
npm run dev                # :5173（strictPort 锁死）；需后端 ms-web 在 :8000 同步跑
npm run build              # tsc --noEmit && vite build → static/
npm run typecheck          # 仅类型检查
npm run test               # vitest run（US-002 起会有用例）
```

## dev/prod 路径

| | dev | prod |
| --- | --- | --- |
| 入口 URL | http://localhost:5173/ | http://127.0.0.1:8000/ |
| base | `/` | `/static/` |
| 后端调用 | 相对路径 `/export`、`/api/*`、`ws://${location.host}/ws/solve` → Vite proxy → :8000 | 同源直连 :8000 |
| 触发 WS 升级 | Vite proxy `ws: true`（**必填**） | 浏览器原生 |

## 关键约束（CLAUDE.md 引用）

1. **不引入 CSS 框架**：`style.css` 由 vanilla 前身迁入，沿用命令式 + 类名约定。
2. **坐标系 `scale(1,-1)`**：sparrow Y 向上 → SVG Y 向下，flipGroup 用 setAttribute 写 transform（避免 React reconciliation 覆盖）。US-003 落地。
3. **命令式 polygon 更新**：每帧 setAttribute('points' / 'display')，由 Zustand renderTick 单字段 ~10fps 节流，**逃逸 React reconciliation**。US-003 落地。
4. **`static/` 是构建产物**（US-008 起入库 gitignore）：`npm run build` 生成，**不要手改**；旧 vanilla 三件套（`legacy/`）已删除，React 应用是唯一真相源。

## 文件分工（US-001 Tab 框架 + US-002~US-008 全部落地；上传预览 US-005 状态层 + US-006 UploadPanel + US-007 PiecePreviewSVG + US-008 SizeTabs/ParsedPiecesView/PreviewPage 容器集成 + 上传预览 US-011 qtyStore 数量状态 + 上传预览 US-012 PieceQtyDialog/Switch 数量弹窗 + 上传预览 US-013 PieceZoomModal 放大预览模态 + 上传预览 US-014 ParsedPiecesView 卡片头改造+双模态集成 + US-015 uiStore 扩 nestingEnabled + TabBar 置灰 + US-016 PreviewPage 联动 setNestingEnabled + US-017 SizePicker 动态读码号 + DEFAULT_FORM.sizes=[] + US-018 PerTypeOverridesModal/PtypePreviewModal 高级配置弹窗+片型缩略图+放大预览 + US-021 useCommitToNesting 解析成功自动 commit+D1 闭环）

```
src/
├── main.tsx               # US-001：createRoot + StrictMode
├── App.tsx                # US-001 ✅ Tab 骨架：TabBar + 双 .page 容器（display:none 切换）+ Tooltip 单例
├── style.css              # 由 vanilla 前身 1:1 迁入；US-001 加 .tabbar/.tab/.page/.hidden/.preview-empty；上传预览 US-006 加 .upload-panel/.drop-zone/.upload-btn/.upload-status；US-007 加 .piece-preview-svg；US-008 加 .preview-page/.preview-main/.size-tabs/.size-chip/.parsed-pieces-view/.piece-grid/.piece-card*；上传预览 US-012 加 .piece-qty-dialog-overlay/.piece-qty-dialog-modal/.qty-input-group/.qty-step/.qty-input/.switch/.switch-track/.switch-label-*/.switch-thumb/.qty-btn/.qty-confirm；上传预览 US-013 加 .piece-zoom-overlay/.piece-zoom-modal/.piece-zoom-head/.piece-zoom-seq/.piece-zoom-meta/.piece-zoom-name/.piece-zoom-close/.piece-zoom-body；上传预览 US-014 改 .piece-card-name→.piece-card-qty(+.disabled) + .piece-card-body 加 cursor:zoom-in；US-015 加 .tab.disabled(+hover)（#555 灰字 + not-allowed）；US-018 加 .per-type-wrapper/.per-type-btn/.per-type-overlay(z=1100)/.per-type-modal/.per-type-head/.per-type-close/.per-type-table-wrap/.per-type-table/.per-type-rowhead(sticky)/.ptype-col/.ptype-thumb(64×64 zoom-in)/.ptype-name/.per-type-hint/.per-type-actions/.per-type-btn-cancel/.per-type-btn-confirm + .ptype-preview-overlay(z=1200)/.ptype-preview-modal/.ptype-preview-head/.ptype-preview-name/.ptype-preview-close/.ptype-preview-body/.ptype-preview-empty
├── vite-env.d.ts          # vite/client 类型
├── types/                 # US-002 ✅：ws.ts / piece.ts / v03.ts；上传预览 US-005 ✅ parsed.ts（US-004 响应契约）；上传预览 US-011 ✅ qty.ts（PieceQuantity/PieceQuantityMap）
├── lib/                   # US-002 ✅ ws.ts；US-003 ✅ geometry.ts；US-004 ✅ params.ts；US-006 ✅ seek.ts；US-007 ✅ download.ts
├── store/                 # US-002 ✅ runRegistry.ts；US-003 ✅ appStore.ts；US-001 ✅ uiStore.ts（US-015 ✅ 扩 nestingEnabled + setNestingEnabled + setTab guard）；上传预览 US-005 ✅ uploadStore.ts（US-012 扩 qtyDialog + open/close；US-013 扩 zoom + open/close；US-021 扩 commitStatus/commitError/commitSummary + reset 同步清）；上传预览 US-011 ✅ qtyStore.ts（+clampQty+getPieceDisplay 纯函数）
├── hooks/                 # US-002 ✅ useSolveRun.ts；US-003 ✅ useRafThrottle.ts；US-007 ✅ useExport.ts；上传预览 US-005 ✅ useParseDxf.ts（US-021 ✅ 解析成功自动 void commit）；上传预览 US-021 ✅ useCommitToNesting.ts（POST /api/commit-to-nesting + D1 闭环 setNestingEnabled+setTab）
├── constants/             # US-004 ✅：sizes.ts / colors.ts / v03.ts
├── __tests__/             # US-002 ✅ useSolveRun；US-003 ✅ 各模块单测；US-007 ✅ useExport；US-001 ✅ App 集成 smoke（US-015 beforeEach 加 setNestingEnabled(true) 兜底 store guard）
└── components/
    ├── TabBar.tsx         # US-001 ✅ 顶部 Tab（超排/上传预览），订阅 uiStore.activeTab；US-015 ✅ 超排 button disabled 闸（nestingEnabled===false 时 native disabled + .disabled class + aria-disabled + onClick 运行时判）
    ├── NestingPage.tsx    # US-001 ✅ 排料页（原 App 业务逻辑外提；持 solving/seeds/useSolveRun）
    ├── preview/           # US-001 起：上传预览页
    │   ├── PreviewPage.tsx # US-008 ✅ 容器（左 UploadPanel + 右 SizeTabs+ParsedPiecesView；未解析空态）；US-014 ✅ 顶层挂 PieceQtyDialog+PieceZoomModal 单例 + useEffect subscribe 联动 qtyStore.resetQuantities（重传清零）；US-016 ✅ 加 useEffect subscribe uploadStore.status 联动 uiStore.setNestingEnabled（`status==='done' && doc!==null` → true，否则 false；mount 即对齐）
    │   ├── UploadPanel.tsx # 上传预览 US-006 ✅ 左侧上传面板（点击+拖拽+客户端预校验+status 反馈）；US-021 ✅ 加 commit 状态行（committing→应用中… / done→已应用至超排：N 裁片 M 码 / error→应用失败：msg）
    │   ├── SizeTabs.tsx    # 上传预览 US-008 ✅ 尺码切换条（订阅 uploadStore.doc/activeSize；点击 setSize）
    │   ├── ParsedPiecesView.tsx # 上传预览 US-008 ✅ 当前 activeSize 下裁片 grid；US-014 ✅ 卡片头改造为 [A徽章]+序号(数量)（editable=button→openQtyDialog / global非source=span.disabled+title）+ .piece-card-body onClick→openZoom + role=button+tabIndex+Enter/Space
    │   ├── PiecePreviewSVG.tsx # 上传预览 US-007 ✅ 单片（或多片）母版预览 SVG（命令式渲染 + scale(1,-1) 翻转）
    │   ├── Switch.tsx          # 上传预览 US-012 ✅ 受控开关（role=switch + aria-checked；PieceQtyDialog 内「仅当前尺码/全部尺码」用）
    │   ├── PieceQtyDialog.tsx  # 上传预览 US-012 ✅ 数量编辑弹窗（草稿+确定；Portal 到 body；ESC/遮罩/取消丢弃草稿）
    │   ├── PieceZoomModal.tsx  # 上传预览 US-013 ✅ 放大预览模态（声明式受控 Portal；订阅 uploadStore.zoom+doc；✕/遮罩/ESC 关闭；复用 PiecePreviewSVG pad=20）
    │   └── __tests__/
    │       ├── UploadPanel.test.tsx      # 上传预览 US-006 ✅ 25 项集成测试（US-021 更新 2 项 fetch 计数 + beforeEach/afterEach 加 uiStore reset）
    │       ├── PiecePreviewSVG.test.tsx  # 上传预览 US-007 ✅ 33 项单测（bbox 纯函数 + 5 层渲染 + 翻转 + 标注 + 切片重建）
    │       ├── SizeTabs.test.tsx         # 上传预览 US-008 ✅ 8 项单测（chip 列表 + active 高亮 + 点击 setSize + null 通用码）
    │       ├── ParsedPiecesView.test.tsx # 上传预览 US-008 ✅ 8 项基础 + US-014 ✅ 11 项新增（序号 index+1 / qty 默认 0 / editable button openQtyDialog / global非source span.disabled+title / body onClick openZoom / Enter/Space / qty stopPropagation）
    │       ├── PreviewPage.test.tsx      # 上传预览 US-008 ✅ 9 项基础 + US-014 ✅ 7 项新增（默认模态不渲染 / qtyDialog+zoom 自显隐 / reset 联动清 / 重传清 / 切码保留 / 端到端切码→qty→global→置灰 title）
    │       ├── Switch.test.tsx           # 上传预览 US-012 ✅ 5 项单测（role+aria-checked / onChange / label 文案 / disabled / .on class）
    │       ├── PieceQtyDialog.test.tsx   # 上传预览 US-012 ✅ 15 项集成（null 不渲染 / 标题 / 初值 per-size+global / [+][-] / Switch / 确定 per-size+global / 取消 / 遮罩 / ESC / blur clamp）
    │       └── PieceZoomModal.test.tsx   # 上传预览 US-013 ✅ 14 项集成（null 不渲染 / doc=null 不渲染 / overlay+modal+aria / 头部 label+seq(qty)+size+name / qty 从 qtyStore / null 码「通用」/ body svg.piece-preview-svg / ✕ closeZoom / 遮罩 closeZoom / modal 不冒泡 / ESC closeZoom / Portal body / label 不存在兜底 / size 不存在兜底）+ US-016 ✅ PreviewPage.test.tsx 增 8 项（mount idle→false / done→true / error→false / reset→false / 重传 doc_id 变化短暂 false 后 true / 关键不变量 setNestingEnabled(false) 不强制切 Tab / uploading→false / 状态机循环 done→uploading→error→done）
    ├── nests/             # US-003 ✅ NestSVG / NestCard / NestLabel；US-005 ✅ NestsGrid；US-006 ✅ NestSVG seek+hover
    ├── ControlPanel/      # US-004 ✅ 8 子组件；US-005 ✅ MultiSeedControls；US-007 ✅ ExportButtons；US-018 ✅ PerTypeOverrides 改按钮触发 + PerTypeOverridesModal（高级配置弹窗 + 片型缩略图 + D7 预填 + 草稿确定）+ PtypePreviewModal（片型放大预览，双层独立 ESC）
    ├── curve/             # US-005 ✅ ConvergenceCurve
    ├── playback/          # US-006 ✅ PlaybackBar / Seekbar / SeekReadout
    └── Tooltip.tsx        # US-006 ✅ Portal 单例 + showTooltip/hideTooltip/setHovered/clearHovered
```

## 上传预览 US-011 关键约定（qtyStore 数量状态 调用方必读）

- **qtyStore 与 uploadStore 完全解耦**：qtyStore 只持 `quantities: PieceQuantityMap` + 3 actions（setPiecePerSize / setPieceGlobal / resetQuantities），不读 doc/activeSize；uploadStore 不持 quantities。US-014 集成时 uploadStore.reset 联动 `useQtyStore.getState().resetQuantities()`（重传清零）。
- **label 跨码匹配同一片型**：数量 map 以 label（A/B/C...）为 key，跨码语义同片型。依赖后端 `_label_for` 几何排序 `(-centroid_y, centroid_x, -area_mm2, ...)` 在码间稳定（M1787 结构款成立）。name 含码号后缀（如 `noname..28`）跨码不同，故不用 name 做 key。
- **`getPieceDisplay` 是 UI 消费的唯一入口**：四分支严格固定 —— （a）label 未在 map → `{qty:0, editable:true, reason:null}`；（b）mode per-size → qty=`perSize[sizeKey(size)] ?? 0`、editable=true；（c）mode global 且 `globalSource===size` → qty=globalValue、editable=true；（d）mode global 且 `globalSource!==size` → qty=globalValue、editable=false、reason=`'该数值已在「<sizeLabel(globalSource)>」处使用全局数量'`。US-012/013/014 都调此 selector，不直接读 quantities[label]。
- **`clampQty` 是数量值唯一规整入口**：`Math.max(0, Math.min(99, Math.trunc(Number(v) || 0)))`。负数/NaN/非数字→0；小数→截断（非四舍五入）；>99→99；字符串数字→对应整数。setPiecePerSize / setPieceGlobal 内部统一走 clampQty，调用方传入原值即可。
- **从 global 切回 per-size 时 globalValue 继承到 source 码**：`setPiecePerSize(label, size, value)` 内部检测 `prev.mode==='global'`，先把 `prev.globalValue` 写到 `perSize[sizeKey(prev.globalSource)]`（globalSource=null 时 sizeKey='null' 兜底），再写新值到 `perSize[sizeKey(size)]`，最后 mode='per-size' + 清 globalValue/globalSource。改继承逻辑需同步 qtyStore.test.ts「从 global 切回时 globalValue 继承到 source 码」用例。
- **null 码 sizeKey/sizeLabel 双口径**：`sizeKey(null)='null'`（perSize key 空间，与 number 区分）；`sizeLabel(null)='通用'`（人读文案，与 SizeTabs `NULL_SIZE_LABEL` 同语义）。globalSource=null 表示用户在「通用」码切 global，访问 null 码 editable=true（source 匹配），访问 number 码 reason 含「通用」。
- **纯函数 + Zustand 便于测试**：clampQty / getPieceDisplay 是纯函数导出，单测直接调；store 通过 `useQtyStore.getState()` / `setState()` 同步可读可写，无需 React 渲染。24 项单测全部纯函数/store 级，不挂组件。
- **不进 commit / 排料**：US-011 仅前端 UI，数量存 store 不序列化到 intermediate。后端接环（数量→每片复制份数）是后续 Story。

## 上传预览 US-012 关键约定（PieceQtyDialog 数量弹窗 + Switch 调用方必读）

- **草稿 + 确定模式（非即时生效）**：PieceQtyDialogInner 用 useState 持 `draftQty`/`draftGlobal`；用户编辑仅改草稿；点确定才写 qtyStore；点取消 / 遮罩 / ESC 仅 `closeQtyDialog()`，草稿丢弃。**目的**：切 global 瞬间会把其它码同 label 置灰（editable=false），草稿模式让用户在确定前可以回滚（避免误操作锁定其它码）。改即时生效会破坏此体验。
- **key 强制重建 PieceQtyDialogInner**：`key={`${label}-${size ?? 'null'}`}`；target 切换时（点卡片头切到另一片）Inner 重建，useState 重新从 store 读初值，避免 StrictMode 双 mount / 同 label 二次 open 时草稿残留。改 key 拼合需同步 5 项「初值」用例。
- **`PieceQtyDialog` 默认 return null**：`qtyDialog === null` 时返回 `null`（不挂 DOM）；打开时 Portal 到 document.body（与 Tooltip 同口径，不被父级 transform / overflow 影响）。改 Portal 目标会破坏 z-index 与定位。
- **初值严格走 `getPieceDisplay` selector**：draftQty 初值 = `getPieceDisplay(quantities, label, size).qty`；draftGlobal 初值 = `quantities[label]?.mode === 'global' && quantities[label]?.globalSource === size`（不能仅靠 `getPieceDisplay.editable`，因为 label 未配置时 editable=true 但 draftGlobal 必须 false）。
- **ESC 监听在 Inner 组件挂/卸载**：Inner 用 `useEffect` 在 mount 时 `window.addEventListener('keydown', onKey)`、unmount 时 `removeEventListener`。dialog 关闭（target 切 null）时 Inner 卸载 → listener 自动清理，无残留。改监听位置会破坏生命周期同步。
- **遮罩 mousedown 用 `e.target === e.currentTarget`**：只在 mousedown 落在 overlay 自身（不是冒泡上来的子元素）时 onClose；modal 内任何点击不关闭。用 mousedown（不是 click）防止用户在 modal 内拖选文本时误关。
- **input blur 时 clamp 兜底**：`handleInputBlur` 调 `clampQty(e.target.value)`；type=number input 上下箭头 / 字符串粘贴可能写入超 99 / 非数字值，blur 时统一规整到 [0,99] 整数。
- **`[-]` 在 draftQty <= 0 时 disabled**：原生 button disabled（不响应点击 + 不参与 tab 序列），与 clampQty 下界 0 一致；`[+]` 不 disabled（clampQty 兜底 99）。
- **Switch 用原生 `<button disabled>` 兜底**：Switch props.disabled=true 时 button 自带 disabled 属性（不响应点击 + 不参与 tab 序列），`handleClick` 内 `if (disabled) return` 是双重防御。
- **uploadStore 扩 qtyDialog + open/close**：新增字段 `qtyDialog: {label:string; size:number|null} | null`（默认 null）+ actions `openQtyDialog(label, size)` / `closeQtyDialog()`；`reset()` 同步清 `qtyDialog=null`。store 公开 API 扩到 4 个（reset/setSize/openQtyDialog/closeQtyDialog）；hook useParseDxf 的 setState 流程**不写 qtyDialog**（弹窗显隐仅由 UI 触发）。
- **uploadStore.reset 联动 qtyStore.resetQuantities 留到 US-014**：本故事只扩 uploadStore.reset 清 qtyDialog（同 store 内）；qtyStore 独立 store 的 resetQuantities 联动（重传清零数量）由 US-014 ParsedPiecesView 集成时挂入。

## 上传预览 US-013 关键约定（PieceZoomModal 放大预览模态 调用方必读）

- **声明式受控 Portal（区别于 Tooltip 命令式单例）**：PieceZoomModal 订阅 `uploadStore.zoom + doc`；`zoom===null || doc===null` 时 `return null`（不挂 DOM）；打开时 Portal 到 document.body（与 PieceQtyDialog / Tooltip 同 Portal 目标，不被父级 transform / overflow / display:none 影响）。改 Portal 目标会破坏 z-index 与定位。区别于排料页 Tooltip 的命令式单例（Tooltip 用模块顶层 `_el/_hovered` + showTooltip/hideTooltip；模态低频声明式更合适）。
- **uploadStore 扩 zoom + open/close**：新增字段 `zoom: {label:string; size:number|null} | null`（默认 null）+ actions `openZoom(label, size)` / `closeZoom()`；`reset()` 同步清 `zoom=null`。store 公开 API 扩到 6 个（reset/setSize/openQtyDialog/closeQtyDialog/openZoom/closeZoom）；hook useParseDxf 的 setState 流程**不写 zoom**（模态显隐仅由 UI 触发，与上传解析无关）。
- **ESC 监听在 zoom 切换时挂/卸载**：`useEffect` dep `[zoom, closeZoom]`；`zoom===null` 时 effect 早 return（不挂 listener）；`zoom!==null` 时挂 window.keydown，cleanup 函数卸载 listener。zoom 切 null（关闭）时 effect 重跑 → cleanup → 自动卸载，无残留。**hook 必须无条件调（不能在条件分支里）**，故 zoom!==null 判定在 effect 内部（与 PieceQtyDialog 把 ESC 挂在 Inner 子组件不同：PieceQtyDialog 用 key 重建 Inner，本模态无 Inner 子组件故直接在主组件判 zoom）。
- **遮罩 onClick 用 `e.target === e.currentTarget` + modal stopPropagation 双重防御**：只在 click 落在 overlay 自身（不是冒泡上来的子元素）时 closeZoom；modal 用 `onClick stopPropagation` 双重防御（即使冒泡到 overlay 也已被 stop）。用 click（不是 mousedown）—— 与 PieceQtyDialog 用 mousedown 不同；本模态无可拖选文本场景，click 语义更直观。
- **`locatePiece` 防御性兜底渲染 null**：`doc.sizes.find(s=>s.size===size)` 找不到 → null；`pieces.findIndex(p=>p.label===label) < 0` → null。理论不会发生（openZoom 由 ParsedPiecesView 在已挂载卡片上调，必然能定位），但兜底防御 doc 切换 race / 异常 store state。
- **序号 = pieces 数组 index+1（与卡片头序号同口径，US-014 集成时复用）**：`locatePiece` 返回 `{piece, seq: idx+1}`；与 label 字母次序一致（A=1, B=2, ...，依赖后端 `_label_for` 几何排序）。**详情模态头部同时显示 label 徽章 + 序号(数量)**：徽章给版师字母习惯，序号给数量定位（D1 决策信息冗余但语义一致）。
- **数量从 `getPieceDisplay` 读（与卡片头/PieceQtyDialog 同 selector）**：头部 `seq(display.qty)` 中 `display = getPieceDisplay(quantities, label, size)`，**不直接读 `quantities[label]`**（区分 per-size / global-source / global-非source 四分支）。改 selector 来源会破坏「global 模式非 source 码显示全局值」语义。
- **PiecePreviewSVG pad=20（比卡片默认 pad=14 加大留白）**：放大显示更多内边距视觉更舒适；pad 经 PiecePreviewSVG 内 `safePad = Math.max(MIN_PAD=4, pad)` clamp，20 安全。改 pad 需视觉回归核对（M1787 每片放大模态显示宽度 ≈ 90vw）。
- **头部 padding-right 28 给 ✕ 按钮留位**：✕ 按钮绝对定位 `top:8 right:10 + 28×28`；头部 `padding-right: 28` 防长 name 被按钮遮挡。改 ✕ 位置 / 头部 padding 需同步视觉回归。
- **uploadStore.reset 联动 zoom 清零（不联动 qtyStore.resetQuantities）**：本故事只扩 uploadStore.reset 同步清 `zoom=null`（同 store 内）；qtyStore 独立 store 的 resetQuantities 联动（重传清零数量）仍由 US-014 集成时挂入。本故事范围仅模态组件 + store 字段 + 单测，**不集成到 PreviewPage**（PreviewPage 顶层挂 PieceZoomModal 单例是 US-014 任务）。
- **不引入 CSS 框架**：`.piece-zoom-overlay` / `.piece-zoom-modal` / `.piece-zoom-head` / `.piece-zoom-seq` / `.piece-zoom-meta` / `.piece-zoom-name` / `.piece-zoom-close` / `.piece-zoom-body` 全部沿用 style.css 命令式 className，与 piece-card / piece-qty-dialog 暗背景 `#2a2c32/#26282e` + 绿色 `#2ea06c` 强调同色系。
- **未做浏览器验证**：本故事无 SVG/坐标变换改动（仅复用 PiecePreviewSVG 加大 pad，DOM 弹窗外壳），AC 仅要求 typecheck + 单测，故跳过 chrome-devtools-mcp；US-014 集成时再统一浏览器回归（含放大模态显隐 / ✕/遮罩/ESC / 头部信息）。

## 上传预览 US-014 关键约定（ParsedPiecesView 卡片头改造 + 双模态集成 调用方必读）

- **卡片头双模态入口严格分离**：`.piece-card-qty`（在 head）点击 → openQtyDialog；`.piece-card-body`（SVG 包裹层）点击 → openZoom。两个交互入口由位置分离（head vs body 平级）+ stopPropagation 双重防御（qty button onClick 调 `e.stopPropagation()`，即使未来 qty 移到 body 内也不会冒泡触发 zoom）。改分离逻辑需同步 ParsedPiecesView.test.tsx「qty 不冒泡到 body」用例。
- **.piece-card-qty 双形态渲染**：editable=true（label 未配置 / per-size 模式 / global source 码）渲染 `<button class="piece-card-qty">`，点击 openQtyDialog；editable=false（global 非 source 码）渲染 `<span class="piece-card-qty disabled">`，不可点击 + native title 提供 hover 提示文案（reason=`'该数值已在「<sizeLabel(globalSource)>」处使用全局数量'`）。qty=0 正常显示 `序号(0)`（默认态）。改双形态分支需同步「editable button / global非source span.disabled / global source button」3 项用例。
- **序号 = pieces 数组 index+1（与 PieceZoomModal locatePiece.seq 同口径）**：ParsedPiecesView 用 `pieces.map((p, idx) => seq = idx+1)`；PieceZoomModal 用 `locatePiece` 内 `pieces.findIndex+1`。两者口径一致（A=1, B=2, ...），依赖后端 `_label_for` 几何排序在码间稳定。改 seq 口径需同步两个组件 + ParsedPiecesView 11 项用例 + PieceZoomModal 14 项用例。
- **.piece-card-body a11y 完整**：role=button + tabIndex=0 + aria-label=`放大预览裁片 ${label}` + onKeyDown(Enter/Space→openZoom)。与 UploadPanel drop-zone 同模式（键盘用户可用 Tab 聚焦 + Enter/Space 触发）。改 a11y 属性需同步「role+tabIndex / Enter / Space」3 项用例。
- **重传清零用 useUploadStore.subscribe（非 useEffect+ref 对比）**：PreviewPage useEffect 内 `let prevDocId = getState().doc?.doc_id` + `subscribe((state) => { if (state.doc?.doc_id !== prevDocId) { prevDocId = ...; resetQuantities(); } })`。**subscribe 捕获所有 state 变化**（包括不触发 re-render 的 setState），比 useEffect+ref 对比 doc 更可靠。subscribe 在 unmount 时 unsub（无残留）。改实现需同步「reset 联动 / 重传清 / 切码保留」3 项用例。
- **qtyStore 与 uploadStore 解耦（reset 联动在 PreviewPage 集成层）**：uploadStore 不知道 qtyStore 存在（reset 仅清自身字段 qtyDialog/zoom 等）；qtyStore 不知道 uploadStore 存在（resetQuantities 是独立 action）。**PreviewPage 作为集成层**用 subscribe 绑定两者。改耦合（如把 resetQuantities 调用挪到 uploadStore.reset 内）会破坏 store 解耦原则。
- **三路径区分**：reset（doc→null）+ 重传（doc_id 变化）触发 resetQuantities；切 activeSize（doc_id 不变）**不触发**（保留数量）。改分支需同步「reset 联动 / 重传清 / 切码保留」3 项用例。
- **顶层模态单例（声明式受控 Portal）**：PreviewPage 顶层挂 `<PieceQtyDialog/>` + `<PieceZoomModal/>` 各一个；两者默认 return null（qtyDialog=null / zoom=null），store 写入目标时自显隐。改挂载位置（如挪到 ParsedPiecesView 内）会破坏「单例」语义（每片卡片各挂一个会多实例 clobber）。Portal 到 document.body，DOM 位置与 React 树位置无关。
- **不引入 CSS 框架**：`.piece-card-qty`（透明底 + monospace + hover `#2ea06c`）+ `.piece-card-qty.disabled`（`#666` 灰字 + cursor:not-allowed）+ `.piece-card-body cursor:zoom-in` 全部沿用 style.css 命令式 className。`.piece-card-name` 已删除（不再使用）。改 className 需同步组件 + 测试。
- **未做浏览器验证（无 SVG/坐标变换）**：本故事无 SVG 渲染、坐标变换、可视化逻辑改动（仅卡片头 DOM 结构 + 模态挂载 + 点击处理 + CSS），AC 仅要求 typecheck + 单测 + build；浏览器验证留作整体回归。

## US-005 关键约定（上传预览状态层 调用方必读）

- **状态机：idle → uploading → done | error（任一终态可 reset 回 idle）**。status 是 UploadPanel 渲染分支的唯一驱动：uploading 显示加载态、error 显示红字、done 显示文件名 + 码数概览。改状态名 / 增状态需同步 uploadStore.test.ts 7 项 + useParseDxf.test.tsx 15 项。
- **uploadStore 是单一真相源**：与 runRegistry（高频 mutable，不进 state）相反，uploadStore 把 doc/activeSize/error 全部进 React state —— 解析结果低频，进 store 触发 reconciliation 反而便于 UI 同步。新增字段需在 uploadStore + reset() + useParseDxf setState 三处同步。
- **状态过渡（uploading → done | error）由 useParseDxf 直接 `useUploadStore.setState({...})` 写入，不暴露成 store 公开 action**。store 公开 API 只含调用方语义动作（reset / setSize），避免业务组件误触发状态跳变。
- **防连击：uploadingRef + status==='uploading' 双重防护**。ref 立即生效（async 函数体同步段执行）；setState 异步生效，第二次连击会在 setState 调度前进 hook body。两者任一为 uploading 即忽略。改单重防护会回归「连击两次同时 fetch → 后写入者覆盖前者 doc」问题。
- **FormData 不手设 Content-Type**：fetch 自动加 `multipart/form-data; boundary=...`，手设会丢 boundary → 后端 python-multipart 解析失败。useParseDxf.test.tsx AC#1 有断言。
- **响应契约字段名严格与 server.py `_build_parse_payload` 一致**：`{doc_id, filename, sizes:[{size, pieces:[{label, name, polygon, internal_lines, notches, net_polygon, grain_line}]}]}`。改任一字段需同步后端 server.py + types/parsed.ts + useParseDxf.test.tsx AC#2。
- **activeSize 默认 = doc.sizes[0].size ?? null**：后端按数值升序、null 殿后，sizes[0] 是最小码。空 sizes 兜底 null，UI 自然显示空态。改默认需同步 useParseDxf.test.tsx 3 项 activeSize 用例。
- **错误不抛、不 rethrow**：useParseDxf 内 try/catch 兜底，所有错误（网络错 / JSON 解析错 / 4xx/5xx）统一进 uploadStore.error，UI 自取。返回 Promise<void> 仅为调用方可选 await（如「上传完成后再切 Tab」）。
- **doc / activeSize 在失败时不主动清**：uploading 时清 error 但保留 doc/activeSize（避免切 uploading 时 UI 闪烁）；error 时也只写 status/error，让用户能看到上一次成功的预览（可选 UX，由 UI 决定是否隐藏）。reset() 才彻底清零。
- **fetch URL 是相对路径 `/api/parse-dxf`**：dev 由 Vite proxy 转 :8000，prod 同源；与 useExport fetch('/export') 同口径，前端代码 dev/prod 完全一致。

## 上传预览 US-006 关键约定（UploadPanel 调用方必读）

- **整个 `<aside>` 是拖拽落区，点击触发限定在 drop-zone / button 上**：dragenter/dragover/dragleave/drop 挂在根元素（用户可落在 panel 任何子元素上松手），但点击触发文件选择只绑 drop-zone 和 upload-btn（避免点状态文本误触）。改挂载点会破坏 panel-wide DnD 语义。
- **dragCounter 防子元素 dragleave 抖动**：浏览器在 panel 子元素间移动会反复触发 dragenter/dragleave，用 ref 计数器保证只在真正离开 panel（counter=0）时清 `.dragover`。直接 toggle boolean 会因抖动出现 `.dragover` 闪烁。改实现需同步 UploadPanel.test.tsx 4 项 DnD 用例。
- **客户端预校验三件套：.dxf 后缀（MIME 容错）+ 单文件 + 20MB**：后缀判定用 `name.toLowerCase().endsWith('.dxf')`（不看 file.type，Windows 下 MIME 五花八门）；多文件 / 超大直接拦不发请求；20MB 与后端 `server.py UPLOAD_MAX_BYTES` 一致（前端先拦 + 后端兜底）。改任一项需同步 UploadPanel.test.tsx 4 项 reject / 通过用例。
- **`localError` 与 `store.error` 互斥展示（本地优先）**：客户端校验失败消息进本组件 `useState`，不污染 uploadStore 状态机（hook 仅在 HTTP 流程内切 status）；UI 渲染分支 `displayError = localError ?? (status==='error' ? store.error : null)`。改优先级会破坏错误展示口径。
- **`e.target.value = ''` 重置 input value**：否则选同一文件不触发 change（input value 去重机制），用户重试同一文件会哑火。UploadPanel.test.tsx AC#2 有断言。
- **状态驱动 UI 分支**：uploading 显示 `.upload-status.loading` + 按钮文案切「重新上传」+ disabled；done 显示文件名 + 「已解析 N 码 / M 裁片」（N=doc.sizes.length，M=sum(pieces.length)）；error 显示红字（来自 store.error 或 localError）；idle 不渲染 status 块。改分支需同步 UploadPanel.test.tsx AC#3 9 项用例。
- **drop-zone + upload-btn 双入口触发同一 handlePickClick**：不直接绑到 input.change，而是 click → inputRef.click() → input.change，便于 DnD 与点击共享校验/上传路径（drop 直接进 handleFiles 跳过 input click）。改单一入口会破坏双交互模式。
- **不引入 CSS 框架**：`.upload-panel` / `.drop-zone` / `.upload-btn` / `.upload-status` 全部沿用 style.css 命令式 className，与 ControlPanel 暗背景 `#26282e` + 绿色 `#2ea06c` 强调同色系；新增 `.drop-zone.dragover` 用绿色边框高亮。
- **jsdom 缺 DragEvent / DataTransfer，需手动 polyfill**：见 UploadPanel.test.tsx 的 `makeDropEvent` / `makeDragEvent` helper —— 构造原生 Event 并 `Object.defineProperty(ev, 'dataTransfer', ...)` 挂上 stub。jsdom 后续若支持可去掉。

## 上传预览 US-007 关键约定（PiecePreviewSVG 调用方必读）

- **命令式渲染范式（参考 NestSVG.tsx）**：React 仅渲染 `<svg ref/>` 空骨架；useEffect 内 imperative 建 flipGroup `<g>` + 各层节点（polygon / polyline / line / text），用 `setAttribute` 写 transform / points / stroke / ...，**逃逸 React reconciliation**。改任何 attr 走 JSX prop 会被 React 用 vdom 覆盖回旧值（同 NestSVG 关键约定 #2）。
- **翻转组 transform = `translate(0 ${minY+maxY}) scale(1 -1)`**：sparrow Y-up → SVG Y-down（与 PNG / R12-DXF / NestSVG 一致）。`minY+maxY` 是 bbox 的 Y 对称轴，翻转后 bbox 内几何视觉与 sparrow 视图一致（不上下颠倒）。NestSVG 是其特例（minY=0, maxY=gate → `translate(0 gate) scale(1 -1)`）。改字面量需同步 PiecePreviewSVG.test.tsx AC#3 用例。
- **A/B/C 文字标注放在翻转组 `<g>` 之外**（AC#3 不镜像）：用屏幕坐标（SVG Y-down）直接定位 —— 锚点 = piece bbox 左上角上方 `LABEL_Y_OFFSET=3`（baseline 在 `minY - 3`），`font-size=11` / `dominant-baseline=alphabetic`。改位置 / 字号需同步 PiecePreviewSVG.test.tsx 「A/B/C 标注用屏幕坐标」用例。
- **viewBox = bbox + pad**（默认 `DEFAULT_PAD=14`，最小 `MIN_PAD=4` clamp）：pad 容纳 8mm 刀口半段（4mm）+ 标注文本（~10mm cap 高度）。改 pad 默认需同步「viewBox = bbox + pad」用例（默认 + 自定义 + clamp 三组）。
- **5 层渲染分层（颜色 / 线型严格固定，改需同步测试 + 版师确认）**：layer1 毛版半透明蓝实心 `rgba(80,140,200,0.22)` + `#3f7fbf` 实线边（闭合 polygon）；layer14 净版绿虚线 `#33cc33` `stroke-dasharray=6 3`（闭合 polygon，fill=none）；layer8 内部线橙实线 `#ff8c1a`（polyline 不闭合，line.length<2 跳过）；layer4 刀口黄短线段 `#ffd700`（line，端点 `P ± 4*unit_normal`，长度 `NOTCH_LEN_MM=8`，**待版师确认**）；layer7 布纹线红虚线 `#e53e3e` `stroke-dasharray=5 3`（line，grain_line=null 跳过）。
- **刀口端点 = `P ± 4 * unit_normal`**（unit_normal 来自后端 `notch[2..3]`）：法线为单位向量，half=4，端点 `(x∓4nx, y∓4ny)`，r2 截断。法线为零向量（退化边）→ 0 长度线段（点）兜底。改 NOTCH_LEN_MM 需同步 PiecePreviewSVG.test.tsx 2 项刀口用例 + 版师确认。
- **piece(s) 切换整组重建（不同于 NestSVG flipRef 幂等）**：useEffect 头部 `while (svg.firstChild) svg.removeChild(svg.firstChild)` 清空旧内容后重建。NestSVG 同 run 内 N 帧复用 DOM（高频），PiecePreviewSVG 切片是低频 UI 操作，重建简洁且开销可接受。StrictMode 双 mount 同样安全（清空再建）。
- **AC#4 多片同框**：prop 接受 `ParsedPiece | ParsedPiece[]`，归一化为数组；多片时合并 bbox 计算 viewBox（`piecesBBox`），每片独立渲染 5 层 + 各自 A/B/C 标注。US-008 ParsedPiecesView 用单片卡片，多片能力留作未来扩展（不刻意避免重叠，由调用方决定）。
- **空片容错（polygon=[] 或全无数据）**：`piecesBBox` 返回 null → svg 清空后啥都不画（无 viewBox / 无 flipGroup / 无标注），不留残影。polygon.length<3 跳过 rough 层；其他层照常渲染。改兜底需同步「空片」「polygon<3 跳过 rough」用例。
- **pad prop 最小 4 clamp**：`safePad = Math.max(MIN_PAD, pad)`，防 8mm 刀口半段被裁。负数 / NaN（NaN 经 max 比较返回另一侧）兜底为 4。
- **导出辅助 `pieceBBox` / `piecesBBox` / `BBox` 便于测试**：纯函数 / 类型导出，单测直接调；不改 React 渲染。PiecePreviewSVG.test.tsx 5 项 bbox 用例覆盖（合并所有层顶点 / 空片 null / 无 grain 跳过 / 多片合并 / 全空片 null）。
- **不引入 CSS 框架**：`.piece-preview-svg`（display:block + width:100% + height:100% + bg `#eef0f3`，与排料图同色）由 imperative setAttribute('class', ...) 写入，沿用 style.css；与 `.nest-card svg` 同口径。

## 上传预览 US-008 关键约定（SizeTabs / ParsedPiecesView / PreviewPage 调用方必读）

- **三个新组件都从 uploadStore 读、不持本地状态**：SizeTabs 读 `doc`/`activeSize`/`setSize`；ParsedPiecesView 读 `doc`/`activeSize`；PreviewPage 读 `status`/`doc`。store 是单一真相源（US-005 关键约定），切 Tab 后状态保留 = store 是模块级 + display:none 不卸载（AC#5 由 store 持久性保证，组件本身无需任何持久化逻辑）。
- **PreviewPage 空态分支用 `hasParsed = status === 'done' && doc !== null`**：双重条件防御（done 理论必有 doc，但 TS 类型上 doc nullable）。uploading / error 时仍显示空态卡片（不显示「上传中…」之类的状态行 —— 那是 UploadPanel 的事），保持右侧稳定布局。改分支需同步 PreviewPage.test.tsx 4 项空态用例。
- **SizeTabs 的 chip 顺序 = doc.sizes 顺序**（后端按数值升序、null 殿后），**前端不二次排序**：保证 UI 顺序与后端语义一致。改排序需同步后端 `_build_parse_payload` + SizeTabs.test.tsx「渲染 doc.sizes 全部」用例。
- **null 码 chip 显示「通用」**（`NULL_SIZE_LABEL`）：母版里极少出现的「不分码」片（统计上代表通用码），用人读文案代替空字符串/「null」。改文案需同步 SizeTabs.test.tsx 「null 码渲染为通用」用例。
- **SizeTabs doc=null 时返回空 Fragment**（`return <></>`）：双重防御（PreviewPage 在 doc=null 时不挂载 SizeTabs，但组件本身也兜底）。改返回值需同步 SizeTabs.test.tsx 「doc=null」用例。
- **ParsedPiecesView 用 `doc.sizes.find(s => s.size === activeSize)` 过滤当前码**：理论必命中（SizeTabs 只能切到 doc.sizes 里的码），防御性兜底 `matched=undefined` → pieces=[] → 显示「该尺码无裁片」空态。改过滤逻辑需同步 ParsedPiecesView.test.tsx 「activeSize 不在 doc.sizes」用例。
- **piece key 用 `${label}-${name}`**：label 在码内唯一（A/B/C/...，后端 _label_for 已保证），name 是母版 block 名（GBK 解码后中文），两者拼合跨码安全。同码内可能多片同名（label 不同）或同 label 不同名 —— key 拼合兜底所有场景。改 key 需同步 ParsedPiecesView.test.tsx 「key 用 label-name」用例。
- **每片卡片用 PiecePreviewSVG 单片模式**（不传数组，US-007 AC#4 多片能力留作未来扩展）：grid 是「每片独立预览」语义，单片卡片视觉清晰。改多片模式需先与版师确认 grid 单卡承载多片的 UX 必要性。
- **piece-card 视觉沿用 .nest-card 同口径**：暗背景 `#2a2c32` + 圆角 + 上方 `.piece-card-head`（label 徽章 + 裁片名）+ 下方 `.piece-card-body`（SVG 自适应）；与排料页 NestCard 视觉一致。label 徽章用 `.piece-card-label`（绿色 `#2ea06c` 圆形 + 白字，与 StartButton / TabBar active / size-chip active 同色系）。
- **grid 用 CSS Grid `auto-fill + minmax(220px, 1fr)`**：浏览器宽度自适应列数（窗口缩小时单卡不被压扁，最小 220px 保证 SVG 不退化成窄条）。改 minmax 需视觉回归核对（M1787 每码 ~10 片 × ~180px 高度 ≈ 一屏）。
- **不引入 CSS 框架**：`.preview-page` / `.preview-main` / `.size-tabs` / `.size-chip` / `.parsed-pieces-view` / `.piece-grid` / `.piece-card*` 全部沿用 style.css 命令式 className，与 ControlPanel / NestCard 暗背景 `#26282e/#2a2c32` + 绿色 `#2ea06c` 强调同色系。
- **AC#5 切 Tab 后状态保留**：uploadStore 是模块级单例 + App 用 display:none 切页（不卸载），切回时 activeSize/doc 全部保真。**PreviewPage 不持任何本地状态**（不需要 useState 缓存 activeSize 之类的反模式），改状态来源会破坏 AC#5。
- **空态分支组件结构**：未解析时 PreviewPage 渲染 `<div class="preview-empty"><div class="preview-empty-card">…</div></div>`（沿用 US-001 占位的 className，CSS 已存在无需新增）；已解析时渲染 `<SizeTabs/> + <ParsedPiecesView/>`。改结构需同步 App.test.tsx 第 101 行的 `.preview-empty` 断言（切到 preview Tab + doc=null 时仍要找到 `.preview-empty`）。

## US-015 关键约定（uiStore 扩 nestingEnabled + TabBar 置灰 调用方必读）

- **`setTab('nesting')` 在 `nestingEnabled===false` 时静默不切（关键不变量）**：store 层 guard 兜底所有 JS 调用方（TabBar / PreviewPage / 未来 URL hash 同步）。`setTab('preview')` 永远允许（用户随时可回上传预览页，不强制留在 nesting）。改 guard 需同步 uiStore.test.ts「setTab(nesting) 在 false 时静默不切」+「setTab(preview) 在 false 时仍可切」两项。
- **三层双重防御**：TabBar `disabled` 属性（native，a11y / 键盘 tab 序列不响应）→ TabBar `onClick` 内 `if (disabled) return`（合成事件 / devtools 旁路）→ store `setTab` guard（直调 store 的 JS 旁路）。任一层失效不影响整体不可点保证。
- **`nestingEnabled` 默认 `false`，由 PreviewPage 联动 setNestingEnabled(true)（US-016）**：store 默认锁定，业务层负责解锁。改默认值会破坏「未上传母版时超排 Tab 不可点」语义。
- **上传预览 Tab 永远可点**：用户随时可回上传预览页（reset / 重传 / 切码），不被锁定。TabBar 渲染时 `disabled = t.id === 'nesting' && !nestingEnabled`（preview 永远 false）。
- **`aria-disabled` + native `disabled` 同步**：屏幕阅读器 + 键盘序列双重 a11y。`aria-disabled={disabled}`（false 时 React 渲染为 `aria-disabled="false"` 字符串，与 `aria-pressed` 同口径）。改其中一项需同步另一项。
- **不引入 CSS 框架**：`.tab.disabled` + `.tab.disabled:hover` 沿用 style.css 命令式 className；`#555` 灰字 + `cursor:not-allowed`（含 `:hover` 同色防 hover 提亮）；与 ControlPanel / TabBar active 同色系。
- **测试 beforeEach 必须重置 nestingEnabled**：`useUiStore.getState().setNestingEnabled(false)` 加到 beforeEach（与 `setTab('preview')` 同位），避免前一个测试 setNestingEnabled(true) 残留。需要切 nesting 的测试先调 setNestingEnabled(true)；App.test.tsx beforeEach 也加 setNestingEnabled(true) 绕过 store guard 测原有 nesting 渲染。
- **未做浏览器验证**：本故事无 SVG/坐标变换（仅 button disabled 态 + CSS），AC 仅要求 typecheck + 单测 + build，故跳过 chrome-devtools-mcp；浏览器视觉回归留作 US-016 集成时统一核对（disabled 灰字 + cursor:not-allowed）。

## US-016 关键约定（PreviewPage 联动 setNestingEnabled 调用方必读）

- **联动公式严格固定 `next = status==='done' && doc!==null`**：`status` 非 done 或 doc=null 都 → false；只有 done 且 doc 非空才 → true。覆盖所有路径：idle/uploading（false）/ done+doc（true）/ error（false）/ reset（doc→null false）/ 重传（status=uploading 短暂 false，done 后切回 true）。改公式需同步 PreviewPage.test.tsx 8 项 US-016 用例。
- **PreviewPage 是集成层，subscribe + mount 即对齐 + 卸载 unsub（与 US-014 qtyStore 联动同模式）**：useEffect 内 `useUploadStore.subscribe((state) => syncTab(state.status, state.doc))`；mount 时立即按 `useUploadStore.getState()` 对齐初值；unmount 时返回的 unsub 函数被 React 调用清理。uiStore 与 uploadStore 解耦（与 qtyStore 同设计原则）：uploadStore 不知道 uiStore 存在，uiStore 不知道 uploadStore 存在。改耦合（如把 setNestingEnabled 调用挪到 uploadStore.reset 内）会破坏 store 解耦原则。
- **关键不变量（AC#3）：setNestingEnabled 仅控 Tab「能否进入」，不强制切 Tab**：`uiStore.setNestingEnabled(b)` 实现仅 `set({ nestingEnabled: b })`，**不触碰 activeTab**。故用户已在 nesting Tab 时调 reset（doc→null → setNestingEnabled(false)），activeTab 仍是 nesting，preview Tab 永远可点回但**不强制切回**，避免丢失求解状态。改 setNestingEnabled 副作用（如加 setTab('preview')）会破坏此不变量。
- **调用前先判 `get().nestingEnabled !== next`**：避免无变化时无谓 setState 触发订阅者通知（zustand 内部 Object.is 也会兜底，但显式判断更省一次 set 调度）。改判断逻辑需同步 8 项 US-016 用例（不直接断言 call count，但通过「关键不变量」用例间接验证）。
- **App.test.tsx beforeEach 必须 set uploadStore done+doc**：App mount 会触发 PreviewPage mount，PreviewPage 的 US-016 effect 会按当前 uploadStore.status 对齐 nestingEnabled。若 uploadStore=idle，beforeEach 设的 nestingEnabled=true 会被覆盖回 false，导致 `setTab('nesting')` 失效。改 beforeEach 需同步 App.test.tsx 7 项集成用例。「默认 activeTab=preview」测试用例显式 reset uploadStore 到 idle 验证 `.preview-empty`；「切到 preview」测试用例把 `.preview-empty` 断言改为 `.preview-page`（已上传状态下不再走空态分支）。
- **PreviewPage 现有两份 useEffect（qtyStore 联动 + uiStore 联动）独立**：US-014 qtyStore 联动 effect 监听 `doc?.doc_id` 变化；US-016 uiStore 联动 effect 监听 `status + doc` 变化。两 effect 各自独立闭包、互不干扰，挂载/卸载时各自挂载/清理 subscribe。改 effect 结构（如合并）需同步两套用例（US-014 7 项 + US-016 8 项）。
- **未做浏览器验证**：本故事无 SVG/坐标变换（仅 store 联动 + setState），AC 仅要求 typecheck + 单测，故跳过 chrome-devtools-mcp；浏览器视觉回归（disabled 灰字 + cursor:not-allowed 随 status 切换）留作 US-021 自动 commit 集成时统一核对（届时 done→commit→切 nesting 端到端联调）。

## US-017 关键约定（SizePicker 动态读码号 + DEFAULT_FORM.sizes=[] 调用方必读）

- **SizePicker 订阅 uploadStore.doc，不再硬编码 SIZES**：`doc !== null` → chip 列表 = `doc.sizes.map(s=>s.size)`（后端已按 `_size_sort_key` 排序，**前端不二次排序**）；`doc === null` → fallback `constants/sizes.ts:SIZES`（保后端开发模式下排料页可用）。改订阅源会破坏「切款母版 → 码号区自动同步」语义。
- **DEFAULT_FORM.sizes = [] 强制用户选**（旧 `[...SIZES]` 全选废除）：用户必须主动勾选码号；ControlPanel「请至少选一个码号」校验保留兜底。改默认值需同步 `params.test.ts` 「DEFAULT_FORM.sizes 默认空数组」用例 + `ControlPanel.test.tsx` AC#1 / AC#7 默认态断言。
- **FormState.sizes 类型扩 `(number|null)[]`**：doc.sizes 可能含 null（通用码），selected/onChange 也扩为 `(number|null)[]`。null 用 Set 的 `===` 比较自然去重 / 命中。
- **null 码 chip 文案「通用」**（与 SizeTabs NULL_SIZE_LABEL 同语义）：`sizeLabel(null)='通用'`、`sizeKey(null)='null'`（DOM id `sz_null` / value `'null'`）。改文案需同步 SizePicker.test.tsx 「null 码 chip 显示通用」+ ControlPanel.test.tsx US-017 StatusLine hint 用例。
- **下游 WS / export 契约仍是 `number[]`**：ControlPanel.handleStart / handleExport 用类型守卫 `(s): s is number => s !== null` 过滤 null 后再透传（StartConfig.sizes / useExport.exportAs 签名不变）。M1787 实际母版无 null 码；含 null 母版的完整端到端支持留给 US-022（数量 demand 按 (label, sizeKey) 查表，sizeKey 已支持 null）。
- **ControlPanel 订阅 uploadStore.doc 用于 StatusLine 提示**：doc=null 时 `visibleStatus = ${status} — 请先在上传预览页解析母版`；doc 非空时 `visibleStatus = status`（无后缀）。StatusLine 组件本身不动（仅渲染 text）。改提示文案需同步 ControlPanel.test.tsx US-017 「doc=null StatusLine 增提示 / doc 非空无提示」2 项。
- **不引入 CSS 框架**：`.sizes` / `.chip` / `.chip input` / `.field-label` 全部沿用 style.css（与旧 vanilla SizePicker 同 className）。新增 `sz_null` DOM id（与 `sz_28` 等同形）。
- **测试隔离：ControlPanel.test.tsx beforeEach/afterEach 必须 reset uploadStore**：uploadStore 是模块级单例，US-017 起 ControlPanel subscribe doc；不 reset 会让前一个测试残留的 doc 影响后续测试的 SizePicker 渲染。改 beforeEach 需同步 ControlPanel.test.tsx 23 项用例。
- **未做浏览器验证**：本故事无 SVG/坐标变换（仅 chip 渲染 + StatusLine 文案），AC 仅要求 typecheck + 单测 + build，故跳过 chrome-devtools-mcp；浏览器视觉回归（chip 渲染 / 通用 文案 / doc 切换重渲染）留作 US-021 自动 commit 集成时统一核对（届时 done→commit→切 nesting 端到端联调）。

## US-021 关键约定（useCommitToNesting 自动 commit + D1 闭环 调用方必读）

- **自动 commit 是解析成功的副作用（void commit），不阻塞预览渲染**：useParseDxf 在 `setState({status:'done', doc})` 后用 `void commit(doc.doc_id, doc.filename)`（不 await），让 doc/status 先进 store、UI 先渲染预览，commit 后台跑更新 commitStatus。改 `await commit(...)` 会阻塞 upload 返回、延迟预览上屏（破坏 AC#6 关键不变量）。
- **commitStatus 与 parse status 分离（独立字段）**：uploadStore 持两套状态机 —— `status`（parse: idle→uploading→done|error）+ `commitStatus`（commit: idle→committing→done|error），互不干扰。parse done 可以无 commit（parse fail 时 commit 不触发）；commit done 必在 parse done 之后。改合并状态会破坏「commit fail 不影响 parse done 预览可用」语义（D5 基础）。
- **D1 闭环：commit done → setNestingEnabled(true) + setTab('nesting')**：useCommitToNesting 在 commit 成功后显式调 `useUiStore.getState().setNestingEnabled(true)`（与 PreviewPage subscribe parse done 重复但幂等，显式调保证 commit 链路自闭环）+ `useUiStore.getState().setTab('nesting')`（自动切入超排页）。**顺序不能反**：setTab('nesting') 在 nestingEnabled===false 时静默不切（US-015 store guard），故必须先 setNestingEnabled(true) 再 setTab。commit fail 不调 setTab（D5）。
- **D5：commit fail 不切 Tab（Tab 仍解锁，用户可重试或用旧数据）**：commit fail 时 commitStatus='error' + commitError 显示，但 activeTab 不被切到 nesting（用户留在 preview 看到错误）。nestingEnabled 仍为 true（parse done 已解锁），用户可手动点超排 Tab 用旧 intermediate 数据进入。
- **防连击：committingRef + commitStatus==='committing' 双重防护**：ref 立即生效（async 函数体同步段执行）；setState 异步生效，第二次连击会在 setState 调度前进 hook body。两者任一为 committing 即忽略（返回 `{ok:false, error:'commit already in progress'}`，不抛错）。与 useParseDxf uploadingRef 同模式。
- **fetch 用 JSON body（非 FormData）+ 手设 Content-Type**：与 useParseDxf（FormData + 不手设 Content-Type）不同 —— commit 传 doc_id/filename 引用（无文件数据），用 `JSON.stringify({doc_id, filename})` + `headers: {'Content-Type':'application/json'}`。改 body 格式需同步后端 `server.py commit_to_nesting` + useCommitToNesting.test.tsx AC#7 URL+method+body 用例。
- **uploadStore reset 同步清 commit 字段**：`reset()` 把 `commitStatus='idle'/commitError=null/commitSummary=null`（与 status/doc/error/qtyDialog/zoom 同步清）。useParseDxf 进入 uploading 时也清 commit 字段（重传时旧 commit 摘要不再适用，UI 不残留误导）。
- **commitSummary 防御性构造**：后端 commit 响应字段缺失时用空数组/0 兜底（`Array.isArray(data.sizes) ? data.sizes : []`、`typeof data.n_pieces === 'number' ? data.n_pieces : 0`），不阻塞 commit done 状态切换。改兜底逻辑需同步 useCommitToNesting.test.tsx commitSummary 断言。
- **UploadPanel commit 状态行独立于 parse status 行**：两行可同时显示（parse done 行 + commit committing/done/error 行）。commit 行复用 `.upload-status.loading/.done/.error` 同三套 className（暗绿底/暗绿底/红字），`data-testid="commit-status"` 区分（parse 行 data-testid="upload-status"）。不新增 CSS 类。
- **测试隔离：useParseDxf.test.tsx / UploadPanel.test.tsx beforeEach/afterEach 加 uiStore reset**：commit D1 副作用调 setTab/setNestingEnabled，不 reset 会跨测试污染（前一个测试的 commit resolve 把 activeTab 切到 nesting，影响下一个测试初始态）。useCommitToNesting.test.tsx 也同步 reset。
- **mockImplementation 路由 fetch（非 mockResolvedValue）**：US-021 集成测试中 parse-dxf 和 commit-to-nesting 两个 endpoint 共享同一 fetch spy，需 `mockImplementation` 按 URL 路由返回不同 Response（parse→ParsedDoc、commit→commit summary）。mockResolvedValue 共享同一 Response 对象会导致 `.json()` 二次消费 body 报错（与 US-018 PerTypeOverridesModal fetch mock 同模式）。
- **未做浏览器验证**：本故事无 SVG/坐标变换（仅 store 字段扩展 + hook + UploadPanel 状态行 DOM），AC 仅要求 typecheck + 单测 + build。浏览器视觉回归（「应用中…」loading + 「已应用至超排」摘要 + 自动切 Tab + commit fail 红字）留作整体回归。

## US-018 关键约定（PerTypeOverridesModal/PtypePreviewModal 高级配置弹窗 调用方必读）

- **按钮触发替代旧 `<details>` 折叠**：PerTypeOverrides 从「10 行 pt-row 折叠面板」改为「单个 `.per-type-btn` 按钮 → modal」模式（D5 决策：母版 10 片型 20 input 常驻 ControlPanel 视觉噪声过大；收进 modal 后 ControlPanel 更简洁）。按钮 onClick 调 `useControlPanelStore.openModal('per_type')`；modal 订阅 `modal==='per_type'` 自显隐。改回折叠面板需同步 ControlPanel.test.tsx US-018 「button trigger」2 项用例。
- **controlPanelStore 是两模态的唯一真相源**：`modal: 'per_type' | null` + `previewPtype: string | null` 两个独立字段 + 4 个 actions（openModal/closeModal/openPreviewPtype/closePreviewPtype）。** closeModal 不影响 previewPtype，closePreviewPtype 不影响 modal**（双层独立 ESC 的基础）。改字段拆分 / 耦合需同步 controlPanelStore.test.ts 7 项用例。
- **双层独立 ESC（AC#10 关键不变量）**：PerTypeOverridesModal 的 ESC listener 在触发前判 `useControlPanelStore.getState().previewPtype !== null` → return（让 PtypePreviewModal 优先处理）；PtypePreviewModal 的 ESC listener 仅判自身 `previewPtype !== null`。当放大预览打开时 ESC 只关放大预览，底层 modal + 草稿保真；再次 ESC 才关底层 modal。改任一层 ESC 逻辑需同步 PerTypeOverridesModal.test.tsx「ESC 不关底层 / 双层独立 ESC」+ PtypePreviewModal.test.tsx「ESC closes」+「stacked close preview keeps 底层」3 项。
- **D7 预填（internal=10/0, external=0/0）**：initializeDraft 对 form.per_type 中**未填（空串 / undefined）**的 ptype 预填 —— INTERNAL_PTYPES={'单排','双排','火机袋','裤耳'} → {d:'10', tol:'0'}，其它 → {d:'0', tol:'0'}；**非空值原样保留**（用户已编辑过的 ptype 不覆盖）。改预填逻辑需同步 PerTypeOverridesModal.test.tsx「D7 预填 internal/external」+「preserves form.per_type non-empty」2 项。
- **草稿 + 确定模式（非即时生效）**：PerTypeOverridesModalInner 用 useState 持 `draft: Record<string, {d, tol}>`；用户编辑仅改草稿；点确定才 onChange + closeModal；点取消 / 遮罩 / ESC 仅 closeModal，草稿丢弃。**目的**：modal 内 20 个 input 即时写 form 会让 ControlPanel 频繁重渲染 + 用户误关时无法回滚。改即时生效会破坏此体验（同 PieceQtyDialog 草稿模式）。
- **`key="per-type-modal"` 强制 PerTypeOverridesModalInner 重建**：每次 modal 显隐切换时 Inner 组件重建，useState 从 form.per_type 重新初始化 draft（避免上次草稿残留 / StrictMode 双 mount 时旧 draft 污染）。改 key 需同步「initial draft reads D7 prefill」+「preserves form.per_type non-empty」用例。
- **片型缩略图来自 GET /api/ptypes（US-020 契约）**：PerTypeOverridesModal mount 时 fetch `/api/ptypes` → `PtypesResponse.representatives[ptype]`；rep 存在 → `<button class="ptype-thumb">` 内渲染 PiecePreviewSVG compact（64×64，无 label，pad=2）；rep 不存在 / fetch 失败 → button disabled + 显示 ptype 名首字兜底。**fetch 用 cancelled flag 防 StrictMode 双 mount race**（mount→cleanup→mount，第一次 fetch 的 setState 被 cancelled 跳过）。改 fetch 逻辑需同步「mount triggers fetch」+「fetch failure degrades」+「fetch success renders compact svg」3 项。
- **PiecePreviewSVG `compact` prop**：compact=true 时（1）pad 默认 `COMPACT_PAD=2`（不是 DEFAULT_PAD=14）；（2）跳过 `renderLabel`（不渲染 A/B/C 文本）；（3）其它 5 层渲染（polygon / net_polygon / internal_lines / notches / grain_line）layer-aware 不变。改 compact 分支需同步 PiecePreviewSVG.test.tsx 5 项 compact 用例。
- **点击缩略图 → PtypePreviewModal 放大预览**：`.ptype-thumb` onClick 调 `openPreviewPtype(ptype)`；PtypePreviewModal 订阅 `previewPtype` 自显隐，渲染同 rep 的 PiecePreviewSVG（pad=20，非 compact）。**PtypePreviewModal 一次 mount fetch /api/ptypes 缓存**（不像 PerTypeOverridesModal 每次打开都 fetch），避免连点多个缩略图时重复网络请求。改 click 行为需同步 PerTypeOverridesModal.test.tsx「clicking thumbnail opens PtypePreviewModal」用例。
- **rep→Piece piece 转换**：`repToPiece(ptype, rep)` 把 PtypeRepresentative 扩展为 ParsedPiece（label='', name=ptype），其余 5 层字段原样透传。PiecePreviewSVG layer-aware 渲染按字段存在性决定（polygon 缺失跳过 rough 层、net_polygon 缺失跳过 net 层等），无需 compact 分支特判。
- **z-index 三层**：tooltip(100) < piece-qty/zoom(1000) < per-type(1100) < ptype-preview(1200)。放大预览覆盖在高级配置 modal 之上，高级配置 modal 覆盖在 ControlPanel 之上，ControlPanel 在 Tooltip 之上（但 Tooltip 是 Portal 单例，z-index 由其自身 style 写）。改 z-index 需同步视觉回归。
- **fetch mock 必须用 mockImplementation（不是 mockResolvedValue）**：StrictMode dev 双 mount 会调 2 次 fetch；mockResolvedValue 共享同一 Response 对象，首次 `.json()` 消费完 body 后第二次调用报 "body stream already read"。测试中统一用 `vi.spyOn(globalThis, 'fetch').mockImplementation((_input) => Promise.resolve(new Response(...)))` 每次创建新 Response。改 mock 方式会让所有 fetch 测试失败（见 PerTypeOverridesModal.test.tsx / PtypePreviewModal.test.tsx / ControlPanel.test.tsx / App.test.tsx 4 处 beforeEach）。
- **App.test.tsx 也需 fetch stub**：App → ControlPanel → PerTypeOverrides（内挂 PtypePreviewModal）会在 mount 时 fetch /api/ptypes；若不 stub 会出现 act warning（fetch promise 在 act() 外 resolve）。改 beforeEach 需同步 App.test.tsx 7 项集成用例。
- **不引入 CSS 框架**：`.per-type-wrapper/.per-type-btn`（#2c5d8f 蓝）+ `.per-type-overlay/.per-type-modal`（#26282e 暗底）+ `.per-type-table-wrap`（overflow-x:auto）+ `.per-type-table`（table-layout:fixed）+ `.per-type-rowhead`（sticky left）+ `.ptype-col`（80px 宽）+ `.ptype-thumb`（64×64 cursor:zoom-in）+ `.ptype-name` + `.per-type-actions/.per-type-btn-cancel/.per-type-btn-confirm`（#2ea06c 绿）+ `.ptype-preview-*`（z=1200）全部沿用 style.css 命令式 className，与 ControlPanel / piece-zoom-modal 暗背景同色系。
- **未做浏览器验证**：本故事无新 SVG / 坐标变换（PiecePreviewSVG compact 仅复用现有 5 层渲染 + 跳过 label + pad=2），AC 仅要求 typecheck + 单测 + build，故跳过 chrome-devtools-mcp；浏览器视觉回归（缩略图 64×64 显示 + 放大预览 + 双层 ESC + D7 预填）留作 US-021 自动 commit 集成时统一核对。

## US-001 关键约定（Tab 框架调用方必读，US-015 已扩）

- **双页面常驻 DOM，display:none 切换**：`.page.hidden { display: none }`（不是条件渲染）。切回排料页时 NestingPage 内 useState/useRef/runRegistry 全部保真，进行中求解 / WS / seek 不中断。改策略需同步 6 项 App.test.tsx。
- **uiStore 双字段（US-015 扩，US-016 联动）**：`activeTab: 'nesting' | 'preview'`（默认 `'preview'`）+ `nestingEnabled: boolean`（默认 `false`，**US-016 由 PreviewPage subscribe uploadStore 联动 setNestingEnabled**）。求解/WS/seek 等业务状态由 NestingPage 自治，不混入 uiStore。**关键不变量**：`setTab('nesting')` 在 `nestingEnabled===false` 时静默不切（见 US-015 关键约定）；setNestingEnabled(b) 不强制切 Tab（见 US-016 关键约定）。
- **TabBar 只切 store**：`<button onClick=setTab>`；显隐由 App 订阅 activeTab 后切 `.hidden` class（解耦：未来 URL hash 同步只需改 App）。US-015 加 disabled 闸（超排 button native disabled + .disabled class + 运行时 onClick 判）。
- **Tab 顺序固定**：超排在前、上传预览在后；TABS 数组顺序不可改。
- **TabBar 视觉沿用 style.css**：暗色 `#26282e` 与 ControlPanel 同色系；active 用绿色 `#2ea06c` border-bottom（与 StartButton 同色）。US-015 加 `.tab.disabled`（`#555` 灰字 + not-allowed）。不引入 CSS 框架。
- **NestingPage 用 Fragment**：ControlPanel + main 直接作为 `.page` flex 子元素，不再包 `.app`（避免冗余 DOM + flex 嵌套层）。
- **Tooltip 仍由 App 渲染**：US-006 关键约定 #3（模块级单例）不破；NestingPage 不挂 Tooltip。

## US-007 关键约定（导出 PNG/DXF 调用方必读）

- **useExport 挂在 ControlPanel 内**：因为 sizes 在 ControlPanel form 里（与旧 vanilla 实现 `sizes: selectedSizes()` 同源）。App 不持有 useExport；onStatus 由 useExport → ControlPanel props.onStatus → App.setStatus → StatusLine 透传。
- **ExportPayload 七字段与旧 vanilla 实现 字节级一致**：`{ fmt, sizes, seed, gate_mm, width_mm, density, placed }`。其中 `width_mm = run.lastFrame.width_mm`、`density = run.finalDensity`、`placed = run.lastFrame.placed_items`、`gate_mm = run.manifest.gate_mm`。改任一字段必须同步 `__tests__/useExport.test.tsx` AC#2 用例。
- **bestRun = runRegistry.bestRun()**：已封装「lastFrame 存在且 finalDensity 最高」逻辑（并列取首个）。ExportButtons 的 disabled 用更宽条件 `some(r => r.lastFrame)`，不用 bestRun（bestRun 留给 useExport 内做最终选择）。
- **parseContentDisposition 优先级**：`filename*=UTF-8''xxx` > `filename="xxx"`/`filename=xxx` > `nesting.<fmt>`。decodeURIComponent 抛 URIError → 落下一级（不让导出整体失败）。改顺序同步 `download.test.ts`。
- **防连击用 ref + state 双重防护**：`exportingRef.current` 立即生效；`exporting` state 触发 UI disabled。仅 state 有 race（连击第二次在 setExporting 调度前进入 async body）。
- **ExportButtons 订阅 renderTick**：lastFrame 是 mutable push 不进 React state；通过 `useAppStore(s => s.renderTick)` + `void renderTick` 触发 reconciliation 后重算 hasLastFrame。改订阅源会破坏 final 后启用联动。
- **DOM id `export_png`/`export_dxf` 沿用 legacy CSS 选择器**：保留便于测试 + US-008 清理时一并去除。改 id 同步 `ExportButtons.test.tsx` + `ControlPanel.test.tsx` US-007 用例。
- **服务端文件名 `pct` 而非 `%`**：`server.py export` 拼 `排料_码{sizes_str}_{pct:.2f}pct_seed{seed}.{ext}`（不是 `88.42%`）。AC#5 字面写 `%` 是文档误差；实际下载 `排料_码28-30-32_88.42pct_seed0.png`。改格式需同步 server.py + useExport.test.tsx CN decode 用例。
- **jsdom 测试需 stub URL.createObjectURL + <a>.click()**：jsdom 不实现 `URL.createObjectURL`、`<a>.click()` 触发 navigation 警告。在 beforeEach 全局 stub，afterEach 调 `vi.unstubAllGlobals()` 还原（见 `__tests__/useExport.test.tsx`）。

## US-006 关键约定（回放 seek / Tooltip 调用方必读）

- **`seekTime = -1` 是 live 标志**：appStore.seekTime 默认 -1 表示「跟随 lastFrame」；`>=0` 才走 frameAtTime 分支。NestSVG / SeekReadout 都按此分支。改默认值需同步 9 项 PlaybackBar + 11 项 NestSVG.seek 单测。
- **App.onDone 全完成时 setSeekTime(me)**：`me = Math.ceil(maxElapsed(runRegistry.list()))`，与旧 vanilla 实现 `$('seek').value = me` 一致 —— 默认拖到末尾。handleStart 内必须 setSeekTime(-1) + clearHovered + hideTooltip（防 DOM 残留）。
- **Tooltip 是模块级单例**：Tooltip.tsx 用模块顶层 `let _el / let _hovered`；App 内**只能挂一个 `<Tooltip/>`**（多挂互相 clobber）。NestSVG mousemove 处理器调 `showTooltip / hideTooltip / setHovered / clearHovered` —— 高频 mousemove 不进 React state，直接 mutate style/innerHTML/classList。
- **Tooltip style 只能由 imperative 写**：Tooltip 组件 JSX **不带 style prop**（仅 className），否则 React reconciliation 重渲染时会把 display 重置为初始值，覆盖 showTooltip 写的 'block'。初始 display:none 在 useEffect 内通过 `el.style.display = 'none'` 设。
- **frameAtTime 二分与旧 vanilla 实现 字节级一致**：`lo=0, hi=n-1, ans=0; while (lo<=hi) { mid=(lo+hi)>>1; if (frames[mid].elapsed<=t) {ans=mid; lo=mid+1} else hi=mid-1 }`；返回 frames[ans]。改算法必须同步 `lib/__tests__/seek.test.ts` 9 个 frameAtTime 用例（含 1000 帧 stress 等价线性参考）。
- **flipGroup 上事件委托 mousemove + mouseleave（不是 svg）**：AC#4 明确要求；多边形均在 flipGroup 内，行为与旧 vanilla 实现 setupHover(svg) 等价。listener 在 `if (run.manifest && !flipRef.current)` 块内 attach —— 幂等保护防 StrictMode 双 mount / 多次 bump tick 双注册。
- **面积换算 mm² → cm² 用 `÷100`**：`parseFloat(dataset.area)/100` 与旧 vanilla 实现 一致；`.toFixed(1)`。改单位 / 精度需同步 `NestSVG.seek.test.tsx` 的 4 项 innerHTML 断言。
- **PlaybackBar 节流订阅**：PlaybackBar / SeekReadout 都订阅 renderTick（不是 seekTime 单独）—— frame push 后通过 tick 重算 allDone/max/readout。Seekbar 额外订阅 seekTime（受控 value 跟随）。

## US-005 关键约定（多 seed / 收敛曲线 调用方必读）

- **`ControlPanelStartPayload.seed_count` 是已 clamp 的最终值**：`parseSeedCount(form)` 返回 1（multi_seed=false）或 clamp(parseInt||3, 2, 6)。App.handleStart 直接 `for (let i=0; i<seed_count; i++) start({...cfg, seed: base+i})`，不再做边界检查。
- **App all-done 检测用 ref 不用 state**：`doneCountRef.current += 1; if (< totalSeedsRef.current) return;` —— 闭包陈旧风险靠 ref 规避。每次 handleStart 重置 `doneCountRef.current = 0` + `totalSeedsRef.current = cfg.seed_count`。
- **ConvergenceCurve 命令式 innerHTML**：React 仅 `<svg ref/>`；子节点（line/text/circle/path/g.legend）通过 `svg.innerHTML = out` 一次性写入，**不要改成 JSX**（每帧 diff 开销爆炸）。`sampleFrames` / `renderCurveInto` 导出便于纯函数测试。
- **采样算法与旧 vanilla 实现 drawCurve 字节级一致**：`step = max(1, floor(n/400))`；`pts = frames[0::step]`；`if (pts[last] !== frames[last]) pts.push(frames[last])`（末帧强制纳入）。改算法必须同步 `__tests__/ConvergenceCurve.test.tsx` 4 个采样用例。
- **配色：单 seed 走 PHASE_COLORS[phase]（散点）+ 默认蓝 `#1f77b4`（折线 / 末点）；多 seed 走 SEED_COLORS[ri]（折线 / 末点 / 标签 / 图例）**。`multi = runs.length > 1`（不是 multi_seed 表单值）。
- **useRafThrottle(seeds.length>0) 不在 solving=false 时停**：求解结束后曲线 / NestLabel 仍需 bump 重绘最终态；下次 start() 才会 runRegistry.clear + setSeeds([]) 间接停掉。
- **NestsGrid 只在 seeds 变化时挂载/卸载**：`<NestCard key={seed} run={rec}/>` 稳定 key；NestSVG 内部已订阅 renderTick 自更新，不需要 NestsGrid 介入高频重绘。

## US-004 关键约定（ControlPanel 调用方 / 改动方必读）

- **表单字段全字符串存储**：`FormState`（lib/params.ts）的 number 字段（time/seed/d_*/tol_*）+ per_type[pt].d/tol 都按 input.value 字符串持有。理由：per_type 必须「空串 = 继承两档」与「"0" = 显式 0」可区分（旧 vanilla 实现 inp.value.trim() !== '' 同口径）。
- **collectParams(form) 纯函数与旧 vanilla 实现 字段级一致**：params 四档空 → 0 默认；per_type 仅 trim() !== '' 写入；整体空 → null。任何修改必须同步 `lib/__tests__/params.test.ts` 11 组对比 + AC#2 默认值断言。
- **DEFAULT_FORM 与旧 index.html 默认 1:1**：d_int="10"、其余 0；time="60"、seed="0"；per_type 全空。**US-017 起 sizes 默认 `[]`（不再是 `[...SIZES]` 全选）**，强制用户选；SizePicker chip 列表来自 uploadStore.doc 动态渲染。改默认值需同步 AC#2 + params.test.ts + SizePicker.test.tsx。
- **ControlPanel 不调 useSolveRun**：仅 onStart(cfg) 透传到 App，App 决定是否调 useSolveRun.start（解耦多 seed / 重连 / clear 时机）。
- **DOM id / className 沿用 legacy**：`id="start" / id="status" / id="d_ext" / id="time" / id="seed"` 等保留（CSS 选择器依赖）；`.sizes / .per_type / .pt-row / .chip / .preset / .pt-name i` 等 className 1:1。US-008 清理 CSS 时再统一去 id。
- **PerTypeOverrides 行序 = V03_PTYPES 顺序**：不可重排（影响测试 placeholder / 徽章断言）；`<i>内</i>` 仅 internal=true 的 4 片型（单排/双排/火机袋/裤耳）。
- **React 18 + jsdom 单测输入模拟**：number input 必须用 `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set` native setter 设值后再 dispatch `input` event，否则 React 的 value tracker 检测不到变化（见 ControlPanel.test.tsx AC#6 fill per_type 用例）。

## US-002 关键约定（hook / Registry 调用方必读）

- **WS 连接只在 `start(cfg)` 显式 new**：不要在 useEffect 里 auto-connect，React 18 StrictMode 双 mount 会双连。
- **frames 是 mutable 引用**：`runRegistry.list()` 返回的 RunRecord 本身可被 push，**不进 React state**；高频重绘由 US-003 renderTick 单字段节流。
- **per_type 空 → 序列化为 null**（与旧 vanilla 实现 collectParams 一致；Python `or None` 接住）。
- **density 双口径**：`FrameMsg.density` 是原面积口径（90% 生死线以此为准），`density_sparrow` 是 erode 后 sparrow 自报（参考）。任何决策 / 显示优先 density。
- **不重连**：onclose / onerror 触发 `onDone`（done flag 防重复），交由调用层决定是否重启。
- **测试**：`npx vitest run`，需 `(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;` 才能 avoid act warning；Mock WebSocket 用 ctor 返回 mock 实例的方式（`new WebSocket(url)` 直接拿到 mock）。

## US-003 关键约定（NestSVG / 节流闸 调用方必读）

- **React 只渲染空骨架一次**：`NestSVG` JSX 仅返回 `<svg ref={svgRef}/>`；所有子节点（bg / 用布矩形 / 翻换组 `<g>` / N 个 `<polygon>`）全部 imperative 创建，由 `useRef` 持有。
- **翻转组 transform 必须用 setAttribute 写**：`translate(0 ${gate_mm}) scale(1 -1)`，**不走 JSX prop**，否则 React reconciliation 会用 vdom 覆盖回旧值。
- **renderTick 单字段节流**：`useAppStore` 只持 `renderTick` 一个字段；`useRafThrottle(active)` 在 active=true 时每 100ms bump 一次；NestSVG / NestLabel 通过 `useAppStore(s => s.renderTick)` 订阅 → useEffect 重跑 → setAttribute imperative 更新。frames 仍 mutable push 到 runRegistry。
- **pointsStr(poly, rot, tr) 字节级对齐旧 vanilla 实现**：rad=rot*π/180，c=cos, s=sin，`x'=x*c−y*s+tx`，`y'=x*s+y*c+ty`，每点 `r2(x),r2(y)`，空格分隔。改这个函数必须同步后端 `_transform_polygon` 和 `lib/__tests__/geometry.test.ts`。
- **flipRef 幂等保护**：建 DOM 的 effect 用 `if (run.manifest && !flipRef.current)` 防御 React 18 StrictMode 双 mount / 多次 bump tick 重复建。清空只在 unmount 时发生（React 自动 GC svg 子树）。
- **viewBox 用历史最大 width 作稳定锚**：`W = max(run.viewBoxMaxW, lastFrame.width_mm, 1)`，避免收缩抖动；用布矩形按当前帧 `width_mm` 收缩（直观看到省布过程）。
- **manifest 到达后 DOM 才建**：mount 早于 manifest 时 effect 早 return；manifest 到达后下一次 renderTick bump 才建。后到 manifest 测试覆盖此路径。

## 已踩坑 / 注意事项

- `npm run dev` 启动后 Vite 监听 `localhost:5173`，**curl 必须用 `localhost`**（不是 `127.0.0.1`），Windows 下后者可能 connection refused。
- `tsconfig.node.json` 必须 `composite: true`，否则 `tsconfig.json` 的 references 报错。
- `@types/node` 是 vite.config.ts 隐含依赖，不能省。
- 修改 `vite.config.ts` 后必须重启 `npm run dev`（Vite 自身配置不热重载）。
- `static/` 是构建产物 —— **不要手改**，改了也会被下次 `npm run build` 覆盖。
- **不要在 useEffect dep 里直接列 mutable run**：run 引用不变（registry 持有），effect 实际靠 renderTick 触发；写 `[renderTick, run]` 即可（run 只是稳定引用）。
- **写文件含 Chinese 字符 + bash heredoc 易踩坑**：用 `cat << 'EOF' > file` 单引号 heredoc 时，bash 仍可能因内部 `''`/`\'` 解析失败；安全做法是分多段 append（`cat >> file <<'TESTEND'` 多次），或用 Python heredoc 套外层（注意 `r'''...'''` 与 bash 单引号的冲突）。
- **多 seed all-done 检测不能用 `useState(doneCount)`**：每次 start 闭包值不同，onDone 内读到的是旧值；改用 `useRef` + 手动重置（US-005 落地）。
