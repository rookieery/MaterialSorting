# PRD: 上传预览页裁片交互优化（放大预览 + 序号(数量) + 全局数量联动）

## 概述 (Overview)

在已落地的 DXF 上传预览页（US-001~US-008）基础上做三项交互增强：① 单击裁片图形弹出大图预览模态；② 卡片头去掉裁片名、改为可点击的「序号(数量)」（序号=裁片在当前码的次序，数量默认 0）；③ 点击「序号(数量)」弹出数量编辑弹窗（数量输入 + 当前尺码/全部尺码 Switch），且支持全局数量联动——某片在某码设为全局后，其它码同序号片置灰只读并 hover 提示来源。本次为**纯前端**增强，数量仅存 Zustand store，不进 commit/排料 intermediate。

## 目标 (Goals)

- 版师可在裁片 grid 中**单击图形**放大查看单片 5 层细节（毛版/净版/内部线/刀口/布纹线），无需切码猜测。
- 卡片头信息从「A + 中文 block 名」收敛为「A + 序号(数量)」，数量成为一等公民，默认 0，可编辑。
- 数量支持**按码独立**与**全码共享（全局）**两种模式，全局模式自动联动置灰其它码同序号片，避免重复设置与口径冲突。
- 沿用现有不变量：不引入 CSS 框架、PiecePreviewSVG 命令式渲染与 `scale(1,-1)` 翻转、uploadStore 为预览页状态中心、Tab display:none 不卸载。

## 前置决策（已与用户确认，闭环）

| # | 决策点 | 选定方案 |
|---|---|---|
| D1 | 序号(数量) 与 A/B/C 徽章关系 | **保留 A/B/C 圆形徽章**，裁片名替换为「序号(数量)」。卡片头布局：`[A徽章] 序号(数量)` |
| D2 | 跨码"同一片型"识别 | **按 label（A/B/C 次序）跨码匹配**：同 label = 同片型。依赖后端几何排序 `(-centroid_y, centroid_x, -area_mm2, ...)` 在码间稳定（M1787 结构款成立）。name 含码号后缀（如 `noname..28`）跨码不同，故不用 name |
| D3 | 数量数据范围 | **纯前端 Zustand store**，本次只做交互预览，不进 commit/排料。后端接环（数量→intermediate 每片复制份数）作为后续 Story |
| D4 | 放大预览关闭方式 | **X 按钮 + 点击遮罩 + ESC** 三种都可关 |

## 用户故事 (User Stories)

### US-011: 数量状态 store（qtyStore）+ 类型 + selector + 单测
- **Description**: As a 前端开发者, I want 一个独立的数量状态 store 来管理每个片型(label)在 per-size/global 两种模式下的数量与联动判定, so that 卡片头、数量弹窗、置灰逻辑共享单一真相源且可纯函数测试。
- **Acceptance Criteria**:
  1. 新建 `materialSorting-web/src/types/qty.ts`：导出 `PieceQuantity`（`mode: 'per-size'|'global'`、`perSize: Record<string,number>`、`globalValue: number`、`globalSource: number|null`）与 `PieceQuantityMap`（`Record<string /*label*/, PieceQuantity>`）。
  2. 新建 `materialSorting-web/src/store/qtyStore.ts`（Zustand）：state `quantities: PieceQuantityMap`（默认 `{}`），actions：
     - `setPiecePerSize(label, size, value)` —— per-size 模式下设该 label 在该码的数量（value 经 `clampQty`：整数、min 0、max 99）；若该 label 当前是 global 模式则先切回 per-size（`globalValue` 继承到 `perSize[globalSource]`，清空 global 字段）再写入。
     - `setPieceGlobal(label, sourceSize, value)` —— 切到 global 模式：`mode='global'`、`globalValue=clampQty(value)`、`globalSource=sourceSize`。
     - `resetQuantities()` —— 清空为 `{}`（与 uploadStore.reset 联动，由 US-014 集成时在 reset 调用）。
  3. 导出**纯函数 selector** `getPieceDisplay(map, label, size)` → `{ qty: number; editable: boolean; reason: string | null }`：
     - label 不在 map（未配置）→ `{ qty: 0, editable: true, reason: null }`（默认 0 可编辑）。
     - `mode='per-size'` → `{ qty: perSize[sizeKey] ?? 0, editable: true, reason: null }`。
     - `mode='global'` 且 `globalSource === size` → `{ qty: globalValue, editable: true, reason: null }`。
     - `mode='global'` 且 `globalSource !== size` → `{ qty: globalValue, editable: false, reason: '该数值已在「' + sizeLabel(globalSource) + '」处使用全局数量' }`。
     - `sizeKey`：number→`String(size)`，null→`'null'`；`sizeLabel(null)`=`'通用'`，否则 `String(size)`。
  4. 导出纯函数 `clampQty(v)`：`Math.max(0, Math.min(99, Math.trunc(Number(v)||0)))`（整数、[0,99]）。
  5. 新建 `materialSorting-web/src/store/__tests__/qtyStore.test.ts` ≥ 12 项：默认空 map / `getPieceDisplay` 四分支（未配置/per-size/global-source/global-非source）/ null 码 sizeKey 与 sizeLabel / `setPiecePerSize` 写入 + 从 global 切回继承 / `setPieceGlobal` 切模式 + 其它码 editable=false / `clampQty`（负数/小数/NaN/超99/字符串）/ `resetQuantities` 清空 / 订阅者收到变化。
  6. `cd materialSorting-web && npm run typecheck` 通过、`npm run test -- qtyStore` 通过；不破坏既有 uploadStore.test.ts（store 独立、字段不重叠）。
- **Priority**: 1

### US-012: 数量编辑弹窗 PieceQtyDialog + Switch 组件 + dialog 状态 + 单测
- **Description**: As a 版师, I want 点击卡片头「序号(数量)」弹出一个弹窗，里面能改数量并用 Switch 切换当前尺码/全部尺码, so that 我能高效地为每片配置数量并决定是否全码共用。
- **Acceptance Criteria**:
  1. uploadStore 扩展（`materialSorting-web/src/store/uploadStore.ts`）：新增 `qtyDialog: { label: string; size: number|null } | null` + `openQtyDialog(label, size)` + `closeQtyDialog()`；`reset()` 同时清 `qtyDialog=null`。同步更新 `uploadStore.test.ts`（reset 清 qtyDialog / open+close / 订阅者通知）。
  2. 新建 `materialSorting-web/src/components/preview/Switch.tsx`：受控 toggle，props `{ checked: boolean; onChange: (v:boolean)=>void; labelOn: string; labelOff: string; 'data-testid'?: string }`。用 `<button role="switch" aria-checked>` + CSS 自绘滑块（不引入 CSS 框架），暗底（`#34363d`）+ 绿色 active（`#2ea06c`，与 size-chip.active 同色系）。
  3. 新建 `materialSorting-web/src/components/preview/PieceQtyDialog.tsx`：订阅 uploadStore `qtyDialog`；为 null 时渲染 null（不挂 DOM）。打开时从 qtyStore `getPieceDisplay` 读当前 `{qty, mode, isSource}` 初始化**草稿 state**（`draftQty: number`、`draftGlobal: boolean`，`draftGlobal` 初值 = `mode==='global' && globalSource===size`）。
  4. 弹窗内容（垂直布局）：① 标题行「裁片 {label} · 码 {sizeLabel}」；② 数量输入组：`[-]` 按钮 + `<input type=number min=0 max=99>` + `[+]` 按钮（step 1，`[-]` 在 0 时 disabled），输入实时写 `draftQty`（经 clampQty 上限提示但不强制截断，blur 时 clamp）；③ `<Switch>`：`labelOff="仅当前尺码"` / `labelOn="全部尺码"`，`checked=draftGlobal`；④ 底部「取消」「确定」两按钮。
  5. 确定逻辑（点「确定」）：`draftGlobal` 为 true → `setPieceGlobal(label, size, draftQty)`；false → `setPiecePerSize(label, size, draftQty)`；随后 `closeQtyDialog()`。取消/遮罩点击/ESC → 仅 `closeQtyDialog()`，**不写 store**（草稿丢弃）。ESC 监听在 dialog 打开时挂 `window.keydown`、关闭时卸载。
  6. 新建 `materialSorting-web/src/components/preview/__tests__/PieceQtyDialog.test.tsx` ≥ 11 项：qtyDialog=null 不渲染 / 打开渲染标题含 label+sizeLabel / 初始 draftQty=draftGlobal 来自 store / `[+]``[-]` 改 draftQty 且 `[-]`@0 disabled / input 改 draftQty / Switch 切 draftGlobal / 确定且 draftGlobal=true 调 setPieceGlobal + close / 确定且 draftGlobal=false 调 setPiecePerSize + close / 取消不写 store / 遮罩点击关闭 / ESC 关闭。
  7. 新建 `materialSorting-web/src/components/preview/__tests__/Switch.test.tsx` ≥ 5 项：role=switch+aria-checked / 点击调 onChange(true)/(false) / labelOn/labelOff 文案 / checked 切滑块 class / disabled 不触发。
  8. `npm run typecheck` 通过、`npm run test -- PieceQtyDialog Switch` 通过。
- **Priority**: 2

### US-013: 放大预览模态 PieceZoomModal + zoom 状态 + 单测
- **Description**: As a 版师, I want 单击裁片图形弹出该裁片的大图预览, so that 我能看清单片 5 层细节（毛版/净版/内部线/刀口/布纹线）再决定数量与排料策略。
- **Acceptance Criteria**:
  1. uploadStore 扩展：新增 `zoom: { label: string; size: number|null } | null` + `openZoom(label, size)` + `closeZoom()`；`reset()` 同时清 `zoom=null`。同步更新 `uploadStore.test.ts`。
  2. 新建 `materialSorting-web/src/components/preview/PieceZoomModal.tsx`：订阅 uploadStore `zoom` + `doc`；zoom=null 或 doc=null 时渲染 null。打开时按 `{label,size}` 从 `doc.sizes.find(s=>s.size===size).pieces.find(p=>p.label===label)` 定位 ParsedPiece（防御性兜底：找不到渲染 null）。
  3. 模态结构：React Portal 到 `document.body`（参考 Tooltip 的 Portal 模式，但 PieceZoomModal 是**声明式受控**，非命令式单例）；`<div class="piece-zoom-overlay">` 遮罩 + `<div class="piece-zoom-modal">` 居中卡；卡内：① 头部行「[label徽章] 序号(数量) · 码 {sizeLabel} · {name}」（数量从 qtyStore `getPieceDisplay` 读，name 这里显示，详情模态便于版师识别）；② 关闭按钮 `<button class="piece-zoom-close" aria-label="关闭">✕</button>` 右上角；③ body 复用 `<PiecePreviewSVG piece={piece} pad={20}/>`（放大显示，pad 加大留白）。
  4. 关闭交互（D4）：点击 `✕` 按钮 → closeZoom；点击遮罩（overlay）空白 → closeZoom（modal 内 stopPropagation）；ESC → closeZoom。ESC 监听在 zoom!==null 时挂 `window.keydown`、关闭时卸载。zoom 切到 null 时组件卸载、无残留 DOM。
  5. `materialSorting-web/src/style.css` 新增：`.piece-zoom-overlay`（fixed 全屏、`rgba(0,0,0,0.6)`、flex 居中、z-index 高于 .tooltip）、`.piece-zoom-modal`（暗底 `#2a2c32`、圆角、max-width/height 90vw/90vh、overflow:auto、相对定位承载关闭按钮）、`.piece-zoom-close`（绝对定位右上角、暗底亮字、hover 高亮）、`.piece-zoom-body`（SVG 容器，宽高自适应、min-height 保证可见）。沿用暗色 + `#2ea06c` 同色系，不引入 CSS 框架。
  6. 新建 `materialSorting-web/src/components/preview/__tests__/PieceZoomModal.test.tsx` ≥ 9 项：zoom=null 不渲染（不挂 DOM）/ 打开渲染 overlay+modal / 头部含 label 徽章+序号(数量)+sizeLabel+name / body 含 PiecePreviewSVG（`svg.piece-preview-svg`）/ ✕ 按钮点击 closeZoom / 遮罩点击 closeZoom / modal 内点击不关闭（stopPropagation）/ ESC 关闭 / Portal 到 document.body（根不在 .tab-content 内）。
  7. `npm run typecheck` 通过、`npm run test -- PieceZoomModal` 通过。
- **Priority**: 3

### US-014: ParsedPiecesView 卡片头改造 + 双模态集成 + CSS + 集成测试
- **Description**: As a 版师, I want 卡片头显示「A徽章 + 序号(数量)」、点击序号(数量)改数量、点击图形放大预览，且全局数量联动置灰, so that 预览页成为一个可配置每片数量并细看的完整工作面。
- **Acceptance Criteria**:
  1. 改造 `ParsedPiecesView.tsx` 卡片头：`.piece-card-head` 由 `[.piece-card-label(A/B/C)] + [.piece-card-name]` 改为 `[.piece-card-label] + [.piece-card-qty]`。序号 = 该 piece 在当前码 `pieces` 数组的 `index+1`（与 label 字母次序一致）；数量与可编辑性从 `useQtyStore` + `getPieceDisplay(quantities, p.label, activeSize)` 读。
  2. `.piece-card-qty` 渲染规则：`editable===true` → `<button class="piece-card-qty" onClick={openQtyDialog(label,size)}>{seq}({qty})</button>`；`editable===false`（global 非 source）→ `<span class="piece-card-qty disabled" title={reason}>{seq}({qty})</span>`（置灰、不可点击、native title 提供 hover 提示文案 `该数值已在「xx」处使用全局数量`）。qty=0 时正常显示 `序号(0)`（默认态）。
  3. 卡片图形区点击放大预览：`.piece-card-body` 包裹层加 `onClick={openZoom(label,size)}` + `cursor:zoom-in` + `role="button"` + `tabIndex={0}` + Enter/Space 键盘触发（a11y）。**点击区域严格区分**：点 `.piece-card-body`（SVG）→ openZoom；点 `.piece-card-qty`（序号数量按钮）→ openQtyDialog；两者 stopPropagation 互不干扰。
  4. `PreviewPage.tsx` 顶层挂 `<PieceQtyDialog/>` + `<PieceZoomModal/>`（单例，订阅 store 自显隐），与 SizeTabs/ParsedPiecesView 同级；uploadStore.reset 联动 `resetQuantities()`（在 UploadPanel 重传成功路径或 reset 调用处接入，确保重传后数量清零）。
  5. `materialSorting-web/src/style.css` 新增/调整：`.piece-card-qty`（按钮样式：透明底、`#cdd` 字色、hover `#2ea06c` 高亮、cursor:pointer）、`.piece-card-qty.disabled`（`#666` 灰字、cursor:not-allowed、hover 不高亮）、`.piece-card-body` 加 `cursor:zoom-in`。移除/保留 `.piece-card-name` 规则由实现决定（不再使用即可删）。不引入 CSS 框架。
  6. 更新 `ParsedPiecesView.test.tsx`：原 8 项中「每片含 label+name+svg」「key label-name」需改为「每片含 label 徽章 + 序号(数量) + svg」；新增 ≥ 4 项：序号=index+1 / qty 默认 0 渲染 `序号(0)` / editable 时 .piece-card-qty 为 button 且点击 openQtyDialog / global 非 source 时 .piece-card-qty.disabled 为 span 且 title 含来源码 / .piece-card-body 点击 openZoom。
  7. 更新 `PreviewPage.test.tsx`：确认挂载 `<PieceQtyDialog/>` + `<PieceZoomModal/>`（默认不渲染，store null）；端到端：解析成功 → 切码 → 点序号(数量) → 弹数量弹窗 → 切全局+确定 → 切另一码 → 对应片置灰 title 含来源码。
  8. 通过浏览器验证排料渲染（dev：`npm run dev` + 后端 ms-web :8000；上传 M1787 母版 → 预览页 → 点裁片放大 → 点序号(数量)改数量 → 切全局验证置灰联动 → hover 置灰项看提示）。
  9. `cd materialSorting-web && npm run typecheck` 通过、`npm run test` 全绿（含更新后的 ParsedPiecesView/PreviewPage 与新增 qtyStore/Switch/PieceQtyDialog/PieceZoomModal 用例）；`npm run build` 产出 `static/` 无报错（dev 模式不强制，但保 build 通过）。
- **Priority**: 4

## 功能需求 (Functional Requirements)

- **FR-1（卡片头）**：保留 A/B/C 圆形徽章；裁片名移除；新增「序号(数量)」可点击元素，序号=当前码内次序(1-based)，数量默认 0。
- **FR-2（数量弹窗）**：点击可编辑的「序号(数量)」→ 弹窗含数量输入([-][input][+]，整数 0..99) + Switch(仅当前尺码/全部尺码) + 取消/确定。
- **FR-3（全局联动）**：Switch 切「全部尺码」并确定 → 该 label 进 global 模式，sourceSize=当前码；其它码同 label 的「序号(数量)」置灰只读、显示同一全局值、hover native title 提示「该数值已在「{sourceSize}」处使用全局数量」。
- **FR-4（切回 per-size）**：global 模式下在 source 码打开弹窗切「仅当前尺码」并确定 → 回到 per-size，该码继承全局值，其它码恢复各自 per-size 值（默认 0）。
- **FR-5（放大预览）**：点击裁片图形(body) → Portal 模态放大显示该单片 PiecePreviewSVG（5 层）+ 头部信息（徽章/序号数量/码/name）；X/遮罩/ESC 关闭。
- **FR-6（点击区分）**：图形区点击=放大预览；序号(数量)点击=数量弹窗；二者独立、不互相触发。
- **FR-7（重传清零）**：UploadPanel 重传成功（uploadStore reset/done 路径）联动 qtyStore.resetQuantities()，避免旧数量残留到新母版。

## 非目标 (Non-Goals)

- **不**把数量传入 commit/排料 intermediate（D3：纯前端）。数量→每片复制份数的后端接环是后续 Story。
- **不**改后端 `/api/parse-dxf` / `/api/commit-to-nesting` 契约与字段。
- **不**改 PiecePreviewSVG 的 5 层渲染逻辑/配色/scale(1,-1) 翻转不变量（仅复用，US-013 传更大 pad）。
- **不**改 SizeTabs / UploadPanel 的既有行为（仅 uploadStore 加字段 + reset 联动）。
- **不**做数量的持久化（刷新/重传即丢，本次纯内存 store）。
- **不**做跨码 name 匹配（D2：仅按 label 次序匹配；name 跨码不同，不用）。
- **不**做数量批量编辑/导入导出（逐片手编即可）。
- **不**引入 CSS 框架（Switch/模态/按钮全部 style.css 自绘）。

## 设计考虑 (Design Considerations)

- **序号与 label 的关系**：序号取 `pieces` 数组 `index+1`，因后端已按 `(-centroid_y, centroid_x, -area_mm2, block_name, piece_index)` 稳定排序后赋 A/B/C，故 index+1 与 label 字母次序天然一致（A=1,B=2,…）。两者并存：徽章给版师字母习惯，序号给数量弹窗定位，**信息冗余但语义一致**（D1 用户选定）。
- **置灰项仍显示数值**：global 非 source 的卡片显示 `序号(globalValue)`（非空占位），让版师一眼看到全局值是多少，置灰 + title 说明来源，符合"该数值已在 xx 处使用全局数量"语义。
- **草稿+确定 vs 即时生效**：数量弹窗用草稿 state + 确定按钮（非即时生效），避免切 Switch 到 global 瞬间置灰其它码后无法取消回滚；取消/ESC/遮罩都丢弃草稿。
- **模态用声明式 Portal**：PieceZoomModal / PieceQtyDialog 都是声明式受控组件（订阅 store 自显隐），Portal 到 body 避免被 `.page` 的 `overflow:auto`/`display:none` 裁切；区别于 Tooltip 的命令式单例（高频 mousemove），模态低频声明式更合适。
- **点击区分靠 stopPropagation**：`.piece-card-qty`(button) 与 `.piece-card-body`(zoom 触发) 是兄弟节点，button onClick stopPropagation 防止冒泡到 body 触发 zoom；反之 body 点击不涉及 qty。
- **native title 做 hover 提示**：置灰项用 `<span title=...>` 的浏览器原生 tooltip，零依赖、够用；不为此复用排料页的命令式 Tooltip 单例（那是高频 mousemove 场景）。
- **放大预览头部显示 name**：详情模态显示裁片 block 名（中文）便于版师识别，与卡片头隐藏 name 不冲突（卡片头追求简洁，详情追求信息完整）。

## 技术考虑 (Technical Considerations)

- **qtyStore 独立于 uploadStore**：数量是独立关注点，单独 store 便于纯函数测试（selector/clamp 不依赖 React）。uploadStore 仅加 `qtyDialog`/`zoom` 两个 UI 模态字段 + 对应 open/close action。
- **label 作为数量 key**：因 D2 按 label 跨码匹配，`PieceQuantityMap` 以 label 为 key（非 label+size）。per-size 模式下各码数量存在 `perSize: Record<sizeKey, number>`，sizeKey 用字符串（null→`'null'`）。
- **selector 是纯函数**：`getPieceDisplay(map,label,size)` 不进 React state，组件用 `useQtyStore(s=>s.quantities)` 订阅 + 调纯函数派生 `{qty,editable,reason}`，便于单测与记忆化。
- **a11y**：Switch 用 `role="switch" aria-checked`；放大预览触发区用 `role="button" tabIndex={0}` + Enter/Space；模态 `aria-modal`/`aria-label` 关闭按钮；ESC 监听挂卸载成对。
- **不破坏既有不变量**：US-008 ParsedPiecesView 的 `key=${label}-${name}`、grid `minmax(220px,1fr)`、`.piece-card` 视觉口径保留；uploadStore 仍是预览页状态中心（数量 store 是补充）；Tab display:none 不卸载保证切 Tab 后数量/模态状态保留。
- **复用 PiecePreviewSVG**：放大预览直接 `<PiecePreviewSVG piece={p} pad={20}/>`，5 层渲染 + scale(1,-1) + A/B/C 标注全部复用，不重写。
- **构建检查**：全前端 Story，验收用 `npm run typecheck` + `npm run test`（vitest）+ `npm run build`；无 Python 模块变更。

## 成功指标 (Success Metrics)

- [ ] 卡片头展示 `[A徽章] 序号(数量)`，数量默认 0，无裁片名残留。
- [ ] 单击裁片图形弹出放大预览，X/遮罩/ESC 三方式可关，预览含单片 5 层 + 头部信息。
- [ ] 点击「序号(数量)」弹数量弹窗，数量可改(0..99 整数)、Switch 可切当前/全部。
- [ ] 某片切「全部尺码」并确定后，其它码同 label 卡片置灰只读、显示同一值、hover 提示来源码；在 source 码切回「仅当前尺码」后恢复可编辑。
- [ ] `npm run typecheck` + `npm run test`（含 ≥ 37 项新增/更新用例）全绿，`npm run build` 无报错。
- [ ] 既有 US-001~US-008 测试无回归（uploadStore/SizeTabs/PreviewPage 更新项除外）。

## 待确认问题 (Open Questions)

- **OQ-1（弹窗确认模式）**：本 PRD 定为「草稿+确定/取消」。若版师更习惯即时生效（改数量/切 Switch 立即写 store、无确定按钮），可在 US-012 实现时按反馈调整——但即时模式下切 global 后取消回滚需额外 undo 机制，倾向保留草稿模式。**默认草稿+确定。**
- **OQ-2（数量上限 99）**：`clampQty` 上限定 99（牛仔裤单片数量极少超此）。若版师有批量场景需放宽，改 `clampQty` 常量一处即可。**默认 99。**
- **OQ-3（label 跨码匹配稳健性）**：D2 依赖后端几何排序在码间一致。若新款母版出现同 label 跨码实为不同片（排序错位），全局联动会误置灰。v1 仅服务 M1787 结构款（与 US-010 片型映射同口径限制），新款需版师重新确认。**v1 接受此限制，记 TODO。**
- **OQ-4（重传清零时机）**：FR-7 要求重传成功联动 resetQuantities。具体在 uploadStore.reset（用户点重新上传）还是 useParseDxf 成功 setState 处接入，US-014 实现时定（倾向 reset 一处 + hook 成功路径双保险）。

## Story 依赖与执行顺序

```
US-011 (qtyStore 基础)  ──┬──> US-012 (数量弹窗, 依赖 selector+actions)
                          └──> US-014 (集成, 依赖 011/012/013)
US-013 (放大预览, 独立)  ─────────> US-014
```

- **Priority 顺序（= prd.json 数组序）**：US-011 → US-012 → US-013 → US-014。
- US-012 与 US-013 互不依赖（数量弹窗 vs 放大预览），可并行；US-014 集成三者。
- 共 **4 个 Story / 预计 4 次 Ralph 迭代**。
- id 沿用 PRD 编号（US-011~US-014，承接已归档的 US-001~US-010），便于交叉引用。
