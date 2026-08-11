# PRD: 上传预览 Tab 与超排 Tab 联动（自动 commit + 码号承接 + 高级配置弹窗 + 新版裁片数据）

## 概述 (Overview)

在已落地的 DXF 上传预览页（US-001~US-014）与排料工作台（US-001~US-008）基础上，把两个 Tab 打通成一条业务流水线：**上传解析 → 自动 commit 母版到 intermediate 并 reload → 解锁并切入超排 Tab → 超排页动态承接上传码号 → 重合/旋转配置改为「高级配置弹窗」按片型覆盖 → 求解输入切换为用户上传数据（尺码/数量/片型覆盖）→ 展示与导出均使用新版裁片（含缝线/刀口/净版/布纹线 5 层）**。

本次为**前后端联动**改造（上一阶段 US-011~014 是纯前端），涉及：前端 Tab 状态机、ControlPanel 三件套重构、后端 `PIECES` 内存常量改可变状态、solver `build_instance` 输入维度扩展、export 多层输出。

## 目标 (Goals)

- **Tab 联动**：默认「超排」Tab 置灰不可点；上传预览解析成功后自动把母版 commit 到 intermediate 并 reload，Tab 解锁、自动切入超排页，用户无感一条龙。
- **码号承接**：超排页码号区直接全量展示上传母版解析出的所有码号，不再锁死 M1787 的 8 码。
- **配置重构**：删除主面板上的重合/旋转内外两档全局配置 + 裁片名称 + 内部/外部区分；改为一个「高级配置：每片型覆盖」按钮 → 弹窗 table（表头列=片型缩略图+片型名、点击缩略图放大预览，两行=重合/旋转）。
- **数据切换**：求解输入使用用户上传的尺码、每片每码数量、片型覆盖；展示与导出的裁片几何切换为新版（毛版 + 净版 + 内部线 + 刺口 + 布纹线）。
- 沿用现有不变量：不引入 CSS 框架、命令式 SVG 渲染与 `scale(1,-1)` 翻转、`paths.py` 集中路径、分层依赖不反向、DXF 导出走 R12+POLYLINE。

## 前置决策（已与用户确认，闭环）

| # | 决策点 | 选定方案 |
|---|---|---|
| D1 | 解析成功后数据如何进超排 | **解析成功自动推送**：`useParseDxf` 解析完成（status=done）即自动调 `/api/commit-to-nesting` → 后端 reload intermediate → 前端 setNestingEnabled(true) + setTab('nesting')。无显式「应用」按钮，UX 一条龙。commit 期间显示「应用中…」态，失败不切 Tab 并报错。 |
| D2 | 数量缺省（用户未填）语义 | **per-size 粒度，缺省=0 跳过**：`quantities` 结构为 `Record<label, Record<sizeKey, number>>`；某片在某码数量为 0（含未填且未 hydrate 的情形）则该片在该码不参与排料（`demand=0` 跳过）。支持「某码只要部分裁片」场景。 |
| D3 | 数量默认 hydrate 值 | **解析成功后默认每片每码 hydrate=1**：避免解析后全 0 导致啥都不排；用户改 0 才排除。hydrate 在 qtyStore 加 `hydrateDefaults(sizes, labels)` action，per-size 模式下每个 (label,size)=1。 |
| D4 | 导出是否含缝线/刀口 | **PNG 与 R12-DXF 都含**：NestSVG 展示 5 层；`web/export.py` 的 PNG 叠加 5 层、R12-DXF 输出多 layer（外轮廓 + 净版 + 内部线 + 刺口，各自独立 POLYLINE entity）。**ET2008 兼容性为 US-024 硬验收项**（实装后真机/ET2008 验证附加 layer 不被误读为裁切轮廓）。 |
| D5 | Tab 解锁信号 | **解析成功（uploadStore.status==='done'）即解锁**，严格对应用户原始需求；commit 是解析成功的自动副作用，commit 失败时 Tab 仍解锁（解析已成功）但显示错误，用户可重试 commit 或用旧数据。 |
| D6 | 片型列表来源 | **固定 V03_PTYPES（10 个）**：与后端 `constraints.py` 的 `MAX_OVERLAP/ROTATION_TOL` 上限表 1:1，避免改后端 parse 响应。 |
| D7 | 高级配置弹窗默认值 | **预填保留旧默认行为**：内部片型（`solver.INTERNAL_TYPES`）重合预填 10、旋转 0；外部片型重合 0、旋转 0。开箱即用与现状一致，用户可改。 |
| D8 | commit/reload 机制 | **模块级可变 state + 互斥锁**：`_PIECES_STATE` 全局字典 + `_state_lock`；ws/solve 在 accept 阶段拿一次快照，连接内 pieces 不变。不采用进程重启或每次重读文件。 |
| D9 | 实施顺序 | **US-020（后端 reload）提前到 US-016 之后**：reload 是 US-021/022/024 共同瓶颈，提前做避免 US-021 自动 commit 落地后卡住。 |
| D10 | 高级配置弹窗表头 | **每片型列表头显示该片型缩略图 + 片型名**（缩略图来自 `GET /api/ptypes` 的代表裁片，仅外轮廓）；**点击缩略图弹出片型放大预览**（无尺码维度，复用 PiecePreviewSVG）。ptype→geometry 映射只能后端给（前端 ParsedDoc 无 ptype 字段），故 US-020 新增 `/api/ptypes` 端点暴露代表裁片。 |
| D11 | 片型放大预览层级（v1/v2） | **v1 仅外轮廓，v2 自动升级 5 层**：v1 intermediate 只有 polygon → 代表裁片只带外轮廓，放大预览画外轮廓；US-024（v2）扩 intermediate 为 5 层后，代表裁片自动带 5 层，**US-018 渲染代码按数据有无自适应（layer-aware），无需改动**。不把 US-024 后端提前到 v1。 |

## 用户故事 (User Stories)

### US-015: uiStore 扩 nestingEnabled + TabBar disabled 态
- **Description**: As a 版师, I want 默认状态下「超排」Tab 置灰不可点，只有上传预览解析成功后才可点, so that 我不会在没上传母版时点进空排料页。
- **Acceptance Criteria**:
  1. `materialSorting-web/src/store/uiStore.ts` 扩字段 `nestingEnabled: boolean`（默认 `false`）+ action `setNestingEnabled(b: boolean)`；保留现有 `activeTab/setTab`，向后兼容（不破坏 `uiStore.test.ts` 现有 4 项）。
  2. `materialSorting-web/src/components/TabBar.tsx`：「超排」button 加 `disabled={!nestingEnabled}` + `className` 含 `disabled`（当锁定）；disabled 时 `onClick` 不调 `setTab`（双重防御：既靠 native disabled 又靠运行时判断）；保留 `aria-disabled` a11y。
  3. `materialSorting-web/src/style.css` 新增 `.tab.disabled { color:#555; cursor:not-allowed; }` 与 `.tab.disabled:hover { color:#555; }`（沿用暗色系，不引入 CSS 框架）。
  4. `materialSorting-web/src/store/__tests__/uiStore.test.ts` 新增 ≥4 项：默认 `nestingEnabled===false` / `setNestingEnabled(true)` 切换 / 订阅者收到变化 / `setTab('nesting')` 在 `nestingEnabled===false` 时**静默不切**（关键不变量）。
  5. `materialSorting-web/src/components/__tests__/TabBar.test.tsx`（若无可新建）新增 ≥3 项：disabled 时点击不调 setTab / disabled 视觉有 `.disabled` class / 启用后正常切换。
  6. `cd materialSorting-web && npm run typecheck` 通过、`npm run test` 全绿、`npm run build` 无报错。
- **Priority**: 1

### US-016: PreviewPage 联动 setNestingEnabled（锁/解锁）
- **Description**: As a 集成层, I want PreviewPage 监听 uploadStore.status，解析成功时解锁超排 Tab，重传/reset/出错时重新锁定, so that Tab 可点状态严格反映「是否有可用解析数据」。
- **Acceptance Criteria**:
  1. `materialSorting-web/src/components/preview/PreviewPage.tsx` 新增 useEffect：subscribe `useUploadStore`，按 `status==='done' && doc!==null` 调 `useUiStore.getState().setNestingEnabled(...)`；mount 时立即对齐初值（`status` 初值为 idle → false）。
  2. `setNestingEnabled(false)` 路径覆盖：`uploadStore.reset()`、重传（doc_id 变化时短暂 false 直到新 doc done）、`status==='error'`。
  3. **关键不变量**：setNestingEnabled 仅控制 Tab「能否进入」，不强制切 Tab —— 若用户当前已在 nesting Tab 且 setNestingEnabled(false)（如点了 reset），不强制切回 preview，避免丢失求解状态；超排 Tab 仅「锁住进入」不「强制退出」。
  4. `materialSorting-web/src/components/preview/__tests__/PreviewPage.test.tsx` 新增 ≥5 项：默认 setNestingEnabled(false) / done 时切 true / error 时切 false / reset 时切 false / 重传中 doc_id 变化短暂 false 然后 true。
  5. `npm run typecheck` 通过、`npm run test` 全绿。
- **Priority**: 2
- **依赖**: US-015

### US-020: 后端 PIECES reload 机制（commit 后内存常量更新）⚠️ 已提前
- **Description**: As a 后端, I want commit 成功后 PIECES 模块常量立即更新，前端 ws/solve 直接吃到新裁片, so that 用户上传新母版后无需重启 ms-web 即可立即排料。
- **Acceptance Criteria**:
  1. `materialSorting-server/src/materialsorting/web/server.py` 新增模块级 `_state_lock = threading.Lock()` + 全局 `_PIECES_STATE: dict`（持有 `{doc, gate_mm, pieces, pieces_by_id}`）；首次 `load_pieces()` 结果填入（替换现有顶层 `PIECES, GATE_MM = load_pieces()` 与 `PIECES_BY_ID`）。
  2. 新增 helper `_reload_pieces_state()`：锁内重读 `paths.INTERMEDIATE` → 更新 `_PIECES_STATE` → 返回新 state。
  3. 新增 helper `_get_pieces_state()`：锁内返回当前 `_PIECES_STATE` 只读快照；`/ws/solve` 与 `/export` 路由中所有 `PIECES/GATE_MM/PIECES_BY_ID` 引用改走此 helper。
  4. `commit_to_nesting` 路由在 `_commit_to_nesting_sync` 成功后调 `_reload_pieces_state()`；返回 payload 增加 `reloaded: true` 字段（删除现有「TODO: PIECES 不会 reload」注释）。
  5. **线程安全不变量**：锁内读-写原子；并发 ws/solve 期间 reload 不会读到半状态；`/ws/solve` 在 accept 阶段调 `_get_pieces_state()` 拿快照，后续 build_instance 用快照（一次 ws 连接内 pieces 不变，避免求解中途数据切）。
  6. 集成验证（人工 curl + WS）：`curl -F file=@<M1787> /api/parse-dxf` → `POST /api/commit-to-nesting` → 立即 `ws/solve` 收到 manifest（pid 数 = 新 intermediate n_pieces）；**不需重启 ms-web**。
  7. `python -c "from materialsorting.web.server import app"` 导入无异常；分层依赖未反向。
  8. **新增 `GET /api/ptypes` 端点（D10）**：从当前 `_PIECES_STATE` 按 ptype 分组、各取一个代表裁片（首个出现），返回 `{representatives: Record<ptype, {polygon, net_polygon?, internal_lines?, notches?, grain_line?}>}`。v1 intermediate 只有 polygon → 字段仅 `polygon`；US-024 扩 intermediate 后自动带 5 层字段（前端 layer-aware 渲染，D11）。空 state（未 commit）返回 `{representatives: {}}`。`curl /api/ptypes` 对 M1787 返回 10 个 ptype 的代表裁片。
- **Priority**: 3
- **依赖**: 无（独立后端改造；被 US-018 消费）

### US-017: SizePicker 从 uploadStore.doc 动态读码号
- **Description**: As a 版师, I want 超排页码号区直接显示上传母版解析出的全部码号, so that 切换新款母版时码号区自动同步，不再锁死 M1787 的 8 码。
- **Acceptance Criteria**:
  1. `materialSorting-web/src/components/ControlPanel/SizePicker.tsx` 改为订阅 `useUploadStore(s=>s.doc)`：doc 非空时 chip 列表 = `doc.sizes.map(s=>s.size)`（后端已按 `_size_sort_key` 排序，前端不二次排序）；doc=null 时 fallback 到 `constants/sizes.ts:SIZES`（保后端开发模式下排料页可用）。
  2. `materialSorting-web/src/lib/params.ts` `DEFAULT_FORM.sizes` 改为 `[]`（空数组，强制用户选；doc=null 时仍可手动 fallback 选 SIZES）；同步 `params.test.ts`。
  3. null 码 chip 显示「通用」（与 SizeTabs `NULL_SIZE_LABEL` 同语义）；`ControlPanel.tsx` 「请至少选一个码号」校验保留，doc=null 时 StatusLine 增提示「请先在上传预览页解析母版」。
  4. `materialSorting-web/src/components/ControlPanel/__tests__/ControlPanel.test.tsx`（或 SizePicker 单测）新增 ≥4 项：doc=null fallback SIZES / doc 有 11 码渲染全 11 / null 码显示「通用」/ 切 doc 自动重渲染。
  5. `npm run typecheck` 通过、`npm run test` 全绿、`npm run build` 无报错。
- **Priority**: 4
- **依赖**: US-015（Tab 解锁后才有意义）

### US-018: PerTypeOverridesModal（按钮 → 弹窗 → table + 片型缩略图 + 放大预览）
- **Description**: As a 版师, I want 把现有 `<details>` 折叠的「每片型覆盖」改成「按钮 → 弹窗 → 表格」，表头列=片型缩略图（点击放大预览）、两行=重合/旋转, so that 配置体验清晰、不挤占主面板，且我能直观看到每个片型长什么样再设它的重合/旋转。
- **Acceptance Criteria**:
  1. 新建 `materialSorting-web/src/components/ControlPanel/PerTypeOverridesModal.tsx`：声明式受控 Portal（参考 `PieceQtyDialog.tsx`/`PieceZoomModal.tsx` 同模式），订阅 `controlPanelStore.modal: 'per_type' | null`（在 `controlPanelStore` 或 `uiStore` 加字段 + open/close action）。
  2. Modal 结构：`.per-type-overlay` + `.per-type-modal`（`role=dialog` + `aria-modal`）+ `.per-type-head`（标题「高级配置：每片型覆盖」+ ✕）+ `.per-type-table`（table/thead/tbody）。
  3. **表格布局（D10）**：**thead 列 = V03_PTYPES 10 个片型，每列表头 = 该片型缩略图（compact 渲染，仅外轮廓）+ 片型名文字**（不含内部/外部徽章——US-019 移除内外区分）；**tbody 行 = 2 行**：「重合」行 input + 「旋转」行 input；空值 placeholder 提示 v0.3 上限（`d≤V03_TABLE[pt].d, t≤V03_TABLE[pt].tol`）。
  4. **缩略图数据源（D10）**：弹窗挂载时 `fetch('/api/ptypes')`（US-020）取 `representatives`，存组件本地 state；loading 时表头显示片型名占位（无图）；fetch 失败降级为仅片型名文字（不阻塞重合/旋转配置）。缩略图用 PiecePreviewSVG compact 模式（AC#9）渲染 `representatives[ptype]`，**layer-aware（D11）**：v1 仅画 polygon，US-024 后数据带 5 层则画 5 层。
  5. 草稿 + 确定模式（参考 PieceQtyDialog）：打开时从 `form.per_type` 读初值进本地 draft（**D7 预填**：INTERNAL_TYPES 重合=10/旋转=0，其余 0/0，保留旧默认行为）；编辑仅改 draft；点确定回写 `form.per_type` + 关闭；取消/遮罩/ESC 仅关 modal、草稿丢弃。
  6. `materialSorting-web/src/components/ControlPanel/PerTypeOverrides.tsx` 改造为按钮触发器：`<button class="per-type-btn" onClick={()=>openModal('per_type')}>高级配置：每片型覆盖</button>`；不再渲染 `<details>` 折叠面板；保留与 ControlPanel 的 `values/onChange` 契约（modal 回写时仍调 onChange）。
  7. **片型放大预览（D10/D11）**：新建 `materialSorting-web/src/components/ControlPanel/PtypePreviewModal.tsx`，点击 thead 缩略图触发（controlPanelStore 加 `previewPtype: ptype|null` + openPreviewPtype/closePreviewPtype）；ptype-keyed **无尺码维度**，从 `/api/ptypes` representatives 取该 ptype 代表裁片，复用 PiecePreviewSVG 全量渲染（layer-aware：v1 外轮廓，v2 5 层）。关闭方式 ✕/遮罩/ESC（参考 PieceZoomModal）；PtypePreviewModal 叠在 PerTypeOverridesModal 之上（z-index 更高，关闭时仅关自身、底层高级配置弹窗保留草稿）。
  8. `materialSorting-web/src/style.css` 加 `.per-type-overlay/.per-type-modal/.per-type-table/.per-type-btn/.ptype-thumb/.ptype-preview-overlay/.ptype-preview-modal` 全套样式（暗背景 `#26282e` + `#2ea06c` 强调，与 PieceQtyDialog 同色系）；表格 `overflow-x:auto`（10 列窄屏溢出）；缩略图 cell 固定尺寸（如 64×64）居中、`cursor:zoom-in`。
  9. **PiecePreviewSVG compact 模式**：`materialSorting-web/src/components/preview/PiecePreviewSVG.tsx` 加 `compact?: boolean` prop（或新建 ThumbPreviewSVG）—— compact 时仅按数据画轮廓（layer-aware）、关 A/B/C 标注、小尺寸 fit-to-cell；非 compact 行为不变（向后兼容上传预览页 PieceZoomModal 调用）。
  10. ESC 监听 + 遮罩 mousedown 自身判定（参考 PieceQtyDialog US-012 关键约定 #6）；两层 modal 各自独立 ESC 处理（放大预览打开时 ESC 只关放大预览，不关底层高级配置）。
  11. 新建 `materialSorting-web/src/components/ControlPanel/__tests__/PerTypeOverridesModal.test.tsx` ≥14 项：modal=null 不渲染 / 渲染 overlay+modal+aria / 表头 10 片型（无内外徽章）/ 重合旋转两行 / 挂载 fetch /api/ptypes / fetch 失败降级片型名 / 缩略图 compact 渲染 representative / 初值从 form.per_type 读（D7 预填）/ 编辑改 draft 不立即回写 / 确定回写 form / 取消丢弃 / 遮罩关闭 / ESC 关闭 / ✕ 关闭 / 点击缩略图打开 PtypePreviewModal。新建 `__tests__/PtypePreviewModal.test.tsx` ≥6 项：previewPtype=null 不渲染 / 渲染代表裁片 PiecePreviewSVG / ✕ 关闭 / 遮罩关闭 / ESC 关闭 / 与 PerTypeOverridesModal 叠层（关放大预览后底层草稿保留）。
  12. `npm run typecheck` 通过、`npm run test` 全绿、`npm run build` 无报错。
- **Priority**: 5
- **依赖**: US-020（`GET /api/ptypes` 提供代表裁片数据）

### US-019: ControlPanel 主面板精简（删内外两档 + 片名/内外徽章）
- **Description**: As a 版师, I want ControlPanel 主面板只保留求解时长/seed/多 seed/码号/启动按钮，重合旋转全交给高级配置弹窗, so that 主面板简洁聚焦核心参数。
- **Acceptance Criteria**:
  1. `materialSorting-web/src/components/ControlPanel/ControlPanel.tsx` 删除 `<ErodeInputs>` + `<ToleranceInputs>` 渲染；保留 `<PerTypeOverrides>`（US-018 改造为按钮）+ `<ParamForm>` + `<MultiSeedControls>` + `<SizePicker>` + `<PresetButtons>` + `<StartButton>` + `<StatusLine>` + `<ExportButtons>`。
  2. `materialSorting-web/src/lib/params.ts` `collectParams` 改为：`params = {d_ext:0, d_int:0, tol_ext:0, tol_int:0}`（**默认全 0，不再从 form 读两档**）—— v0.3 兜底交给 per_type 显式覆盖（D7 预填）+ `MAX_OVERLAP/ROTATION_TOL` 上限；`per_type` 解析逻辑保留不变。
  3. `materialSorting-web/src/lib/params.ts` `FormState` 字段精简：删除 `d_ext/d_int/tol_ext/tol_int`；`DEFAULT_FORM` 同步删；保留 `sizes/time/seed/multi_seed/seed_count/per_type`。
  4. `materialSorting-web/src/components/ControlPanel/ErodeInputs.tsx` + `ToleranceInputs.tsx`（含 `__tests__`）**文件删除**；CSS 规则保留不删（向后兼容）。
  5. `materialSorting-web/src/lib/__tests__/params.test.ts` 同步改造：原对比用例改为「params 永远全 0 / per_type 解析逻辑不变」。
  6. `materialSorting-web/src/components/ControlPanel/__tests__/ControlPanel.test.tsx` 同步删 ErodeInputs/ToleranceInputs 相关用例，新增「主面板不再渲染 d_ext/d_int 输入」断言。
  7. **关键不变量**：后端 `build_instance` 入参契约不变（params 仍传，只是全 0；per_type 仍传），后端无需改动。
  8. `npm run typecheck` 通过、`npm run test` 全绿、`npm run build` 无报错。
- **Priority**: 6
- **依赖**: US-018（PerTypeOverrides 已改造为按钮）

### US-021: useParseDxf done 回调自动 commit + 自动切超排（D1）
- **Description**: As a 版师, I want 上传解析成功后系统自动把母版应用到超排（commit + reload）并切入超排页, so that 上传→排料是一条无缝流水线，无需我手动点「应用」。
- **Acceptance Criteria**:
  1. 新建 `materialSorting-web/src/hooks/useCommitToNesting.ts`：`commit(doc_id, filename?) → Promise<{ok, summary?, error?}>`；fetch POST `/api/commit-to-nesting` JSON body `{doc_id, filename}`；防连击（committingRef + store flag）；错误进 store 不抛。
  2. `materialSorting-web/src/store/uploadStore.ts` 扩字段：`commitStatus: 'idle'|'committing'|'done'|'error'`、`commitError: string|null`、`commitSummary: {sizes, n_pieces, total_area_mm2} | null`；`reset()` 同步清；hook 内部 `setState` 切 commitStatus（与 `status` 状态机分离，独立字段）。
  3. `materialSorting-web/src/hooks/useParseDxf.ts` 在解析成功（`setState({status:'done', doc, ...})`）后**自动触发** commit（D1）：调 `useCommitToNesting().commit(doc.doc_id, doc.filename)`；commit 期间 `commitStatus='committing'` 显示「应用中…」loading 遮罩/提示。
  4. commit done → `_reload_pieces_state`（US-020）生效 → 前端 `setNestingEnabled(true)`（US-015/016）+ `useUiStore.setTab('nesting')` 自动切入超排页；commitSummary 显示在 UploadPanel（如「已应用至超排：{n_pieces} 裁片，{sizes.length} 码」）。
  5. commit fail → `commitStatus='error'` + `commitError` 显示；**不切 Tab**（让用户看到错误）；Tab 解锁状态遵循 D5（解析已成功 → Tab 仍解锁，用户可重试 commit 或用旧数据进入）。
  6. **关键不变量**：自动 commit 是解析成功的副作用，不阻塞解析预览（预览页先渲染，commit 后台跑）；commit 未完成时用户若手动点超排 Tab，进入后看到的是 US-020 快照机制保证的一致数据（可能旧 intermediate），可接受。
  7. `materialSorting-web/src/hooks/__tests__/useCommitToNesting.test.tsx` ≥10 项：fetch URL/method/body / 200→commitSummary+commitStatus=done / 422→commitError / 防连击仅一次 / doc_id 缺省兜底 / commitStatus 切换路径。
  8. `materialSorting-web/src/components/preview/__tests__/PreviewPage.test.tsx` 或 useParseDxf 单测新增 ≥6 项：解析 done 自动触发 commit / commit done 切 nesting Tab / commit done setNestingEnabled(true) / commit 失败不切 Tab / commit 失败显示 error / 摘要渲染。
  9. `npm run typecheck` 通过、`npm run test` 全绿、`npm run build` 无报错。
- **Priority**: 7
- **依赖**: US-015 + US-016 + US-020

### US-022: 求解输入数量 demand 联动 qtyStore（D2 + D3）
- **Description**: As a 版师, I want 我在上传预览页编辑的每片每码数量真正参与排料（每片每码 demand=N 复制 N 份排，0 则排除）, so that「某码只要部分裁片」「2 套前片 + 1 套后片」等混合配比能直接出方案。
- **Acceptance Criteria**:
  1. `materialSorting-web/src/store/qtyStore.ts` 新增 action `hydrateDefaults(sizes: (number|null)[], labels: string[])`：per-size 模式下为每个 (label, sizeKey) 填 `1`（D3）；在 `useParseDxf` 解析成功（doc 到达，已知 sizes + labels）时调用，替代当前「全 0」默认；`resetQuantities()` 仍清空。
  2. `materialSorting-web/src/hooks/useSolveRun.ts`（或 `lib/ws.ts`）WS start payload 新增 `quantities: Record<string, Record<string, number>>`（label → sizeKey → 数量），从 `qtyStore.quantities` 序列化扁平化（per-size 模式取 perSize，global 模式取 globalValue 展开到所有码）；`StartPayload` 类型扩。
  3. **后端 intermediate 扩 label 字段**：`web/server.py _commit_to_nesting_sync` 写 intermediate 时每 piece 加 `label`（沿用 `_label_for(idx)`，与 ParsedDoc 同排序同标注）；`nesting_engine/pieces_export.py` 同步。
  4. `web/server.py` `/ws/solve` 入参增 `quantities: dict | None`；`web/solver.py build_instance` 在 sizes 过滤 + per-piece 迭代时查 `(label, sizeKey)` 命中 quantities → `spyrrow.Item(demand=N)`；**demand=0 跳过该 piece（D2）**；缺 label 字段回退 `demand=1`（向后兼容旧 intermediate）。
  5. **关键不变量 / 已知风险**：label→pid 映射稳定性 —— commit 流程走 NestPiece（已归一化+镜像），parse 流程走 PieceOutline（原始坐标），两者排序键 `(-centroid_y, centroid_x, -area_mm2, ...)` 必须一致，否则 label 错位导致数量配错片型。AC：对 M1787 验证 commit 后 intermediate 的 label 与 parse-dxf 响应的 label **按 (name,size) 对齐一致**（若不一致，qtyStore 改用 `(name,size)` 为 key —— 备选方案，在 Story 内决策）。
  6. `materialSorting-web/src/hooks/__tests__/useSolveRun.test.tsx` 新增 quantities 字段断言。
  7. 后端人工 curl + WS 验证：上传→hydrateDefaults 填 1→改某片某码为 0→commit→ws/solve→manifest 中该片该码 pid 不出现（demand=0 跳过）。
  8. `npm run typecheck` 通过；`python -c "from materialsorting.web.server import app"` 导入通过。
- **Priority**: 8
- **依赖**: US-020（reload 后新 intermediate 含 label）+ US-021（自动 commit 链路）

### US-023: 后端 PTYPE_COLORS 清理遗留 6 片型（消除屏幕灰色）
- **Description**: As a 版师, I want 超排页和导出中裁片颜色正确反映 v0.3 实际 10 片型, so that 我能凭颜色快速区分前片/后片/腰/袋等。
- **Acceptance Criteria**:
  1. `materialSorting-server/src/materialsorting/nesting_engine/sparrow_baseline.py` `PTYPE_COLORS` 改为 v0.3 实际 10 片型（删 门头/门里/拉链/表袋/双袋/侧袋，加 单排/双排/火机袋/裤耳）；4 个新片型色值用与前片/后片同饱和度的协调色（参考 d3 category10：单排=#e377c2、双排=#ff1493、火机袋=#8c564b、裤耳=#17becf —— **待版师屏幕定色**，开 Story 时附色样对比图）。
  2. **关键不变量**：现有 PTYPE_COLORS 调用方（`web/solver.py`、`web/export.py`、`sparrow_baseline.py` 内部）签名不变；`DEFAULT_COLOR='#bbbbbb'` 保留兜底。
  3. `CLAUDE.md`「已知问题」段第 1 条（PTYPE_COLORS 遗留）删除；`.docs/technical/agent-file-map.md` 同步更新 PTYPE_COLORS 内容描述。
  4. 人工验证：跑 ms-web → 上传 M1787 → commit → 求解 → 屏幕所有 v0.3 片型彩色正确（无灰色 fallback）。
  5. `python -c "from materialsorting.web.server import app"` 导入通过。
- **Priority**: 9
- **依赖**: 无（独立清理，可与 v2 并行）

### US-024: 展示层 + 导出层切换新版裁片（5 层：毛版/净版/内部线/刺口/布纹线）（D4）
- **Description**: As a 版师, I want 超排页排料图与最终导出（PNG/R12-DXF）的每片裁片都展示毛版 + 净版 + 内部线 + 刺口 + 布纹线 5 层（与上传预览页同口径）, so that 排料结果视觉与工艺信息完整（求解仍用外轮廓做碰撞）。
- **Acceptance Criteria**:
  1. **后端 intermediate 扩字段**：`web/server.py _commit_to_nesting_sync` 写 intermediate 时每 piece 增加 `net_polygon/internal_lines/notches/grain_line`（从 PieceOutline 透传，US-003 已解析）；`nesting_engine/pieces_export.py` 同步。**副作用（D11）**：`GET /api/ptypes`（US-020）的代表裁片随之带 5 层字段 → US-018 缩略图与放大预览自动从 v1 外轮廓升级为 5 层渲染，US-018 代码无需改动（layer-aware）。
  2. **后端 manifest 扩字段**：`web/solver.py build_instance` 在 `pid_meta[pid]` 增加这 4 字段；`/ws/solve` 的 manifest 中每 piece 增加；前端 `materialSorting-web/src/types/ws.ts` `ManifestMsg.pieces` 同步扩。
  3. **关键不变量**：求解用 polygon（毛版外轮廓，已 erode）不变；net_polygon/internal_lines/notches/grain_line 仅渲染/导出透传，**不参与 sparrow NFP 碰撞**。
  4. **前端 NestSVG 5 层渲染**：`materialSorting-web/src/components/nests/NestSVG.tsx` 在现有 polygon 渲染基础上，每片按 manifest 增加净版虚线（绿 dashed）+ 内部线（橙）+ 刺口短线段（黄）+ 布纹线（红 dashed）；复用 `PiecePreviewSVG.tsx` 的 5 层配色常量（提取到 `constants/colors.ts` 共享）。
  5. **性能保护**：5 层只在 manifest 到达时建一次（与现有 polygon 建节点同位置），frame 切换时只 setAttribute('display'/'points'/'transform')，不重建 DOM；erode 后 polygon 仍是 collision 依据；**翻转组不变量保留**：`scale(1,-1) + translate(0 gate)` 不变，5 层均在翻转组内。
  6. **导出层 5 层（D4）**：`web/export.py` PNG 导出叠加 5 层（与 NestSVG 视觉一致）；R12-DXF 导出多 layer —— 外轮廓（现有）+ 净版（layer14）+ 内部线（layer8）+ 刺口（layer4 POINT 或短 POLYLINE）+ 布纹线（layer7），各自独立 POLYLINE/POINT entity。
  7. **ET2008 兼容性硬验收（D4）**：实装后用 ET2008 真机读 R12-DXF，确认附加 layer 不被误读为裁切轮廓（裁床只切外轮廓 layer1）；若 ET2008 误读，回退为「DXF 仅外轮廓，PNG 含 5 层」并升级到用户决策。
  8. `materialSorting-web/src/components/nests/__tests__/NestSVG.test.tsx` 新增 5 层渲染断言（manifest 含 net → 渲染 net polygon 节点 / 不含则不渲染 / dashed style 正确 / 5 层节点数）；`types/ws.ts` 扩字段 + 同步 `useSolveRun.test.tsx` manifest 分发用例。
  9. 人工浏览器验证：超排页 NestSVG 每片含 5 层（与 PreviewPage PiecePreviewSVG 视觉一致）；导出 PNG 含 5 层、DXF 多 layer。
  10. `npm run typecheck` 通过、`npm run test` 全绿；`python -c "from materialsorting.web.server import app"` 导入通过。
- **Priority**: 10
- **依赖**: US-020 + US-022（intermediate 扩字段在 commit 时写入）

## 功能需求 (Functional Requirements)

- **FR-1（Tab 联动）**：默认「超排」Tab 置灰不可点；解析成功（status=done）解锁；reset/error 重锁。
- **FR-2（自动 commit）**：解析成功自动调 `/api/commit-to-nesting`，后端 reload intermediate，前端自动切入超排 Tab；commit 中显示「应用中…」，失败报错不切 Tab。
- **FR-3（码号承接）**：超排页码号区 = 上传母版解析出的全部码号（含 null「通用」码）；doc=null 时 fallback 硬编码 SIZES。
- **FR-4（高级配置弹窗）**：主面板「高级配置：每片型覆盖」按钮 → 弹窗 table（表头列=V03_PTYPES 10 片型缩略图+片型名，两行=重合/旋转）；草稿+确定；D7 预填保留旧默认。
- **FR-8（片型缩略图+放大预览）**：弹窗表头缩略图来自 `GET /api/ptypes` 代表裁片（compact 外轮廓）；点击缩略图弹出该片型的放大预览（无尺码维度，复用 PiecePreviewSVG）；v1 仅外轮廓，v2（US-024）自动升级 5 层。
- **FR-5（主面板精简）**：删除内外两档全局重合/旋转输入 + 片名 + 内外徽章；主面板仅核心参数 + 高级配置按钮。
- **FR-6（数量 demand）**：每片每码数量进 sparrow `Item.demand`；0 则该片该码不排；解析后默认 hydrate=1。
- **FR-7（5 层展示+导出）**：NestSVG 与 PNG/R12-DXF 导出均含毛版+净版+内部线+刺口+布纹线 5 层；求解碰撞仍只用外轮廓。

## 非目标 (Non-Goals)

- **不**让缝线/刀口参与 sparrow NFP 碰撞（业内排料只用外轮廓；刀口计入碰撞需另立 Story 改 erode/mask）。
- **不**改 `/api/parse-dxf` 响应结构（US-004 已稳定）。
- **不**改 `paths.py` 路径约定或分层依赖方向。
- **不**做数量/片型配置的持久化（刷新/重传即丢，纯内存 store）。
- **不**引入 CSS 框架（弹窗/table/按钮全 style.css 自绘）。
- **不**改 PiecePreviewSVG 的 5 层渲染逻辑（仅提取配色常量共享）。
- **不**重构 `sparrow_baseline.py` 为 `engine_core.py`（CLAUDE.md 已知问题第 2 条，另立 Story）。
- **不**做 `PTYPE_COLORS` 之外的片型语义清理（仅颜色）。

## 设计考虑 (Design Considerations)

- **Tab 解锁 vs commit 完成（D1/D5）**：解锁信号是「解析成功」（D5，贴合用户原话），commit 是自动副作用。若 commit 失败，Tab 仍解锁（解析已成功），用户可重试或用旧数据——这比「commit 成功才解锁」更宽容，避免 commit 抖动锁死入口。自动切 Tab 才严格等 commit done。
- **数量 per-size 粒度（D2）**：结构 `Record<label, Record<sizeKey, number>>` 而非扁平 `Record<label, number>`，因为存在「某码只要部分裁片」场景。0=排除是显式语义，用户改 0 才排除，配合 D3 默认填 1 保证开箱可用。
- **高级配置预填（D7）**：弹窗预填内部片型重合=10（旧 d_int 默认），保留开箱密度行为；用户改 0 = 该片型不允许重合。避免「弹窗全空 → 全片 erode=0 → 密度暴跌」的陷阱。
- **reload 用锁+快照（D8）**：避免进程重启（体验差）和每次重读文件（IO+缓存复杂）；ws/solve accept 拿快照保证一次连接内 pieces 不变。
- **label 对齐风险**：commit（NestPiece）与 parse（PieceOutline）排序键必须一致，否则数量配错片型。备选：qtyStore 改用 `(name,size)` 为 key（name=母版 block 名，跨流程稳定）。Story 内验证后决策。
- **5 层导出 ET2008 风险（D4）**：R12-DXF 多 layer 是为 ET2008 设计的格式，但附加 layer（净版/刀口）可能被裁床误读。硬验收用真机确认；不通过则视觉/工艺分离（PNG 5 层、DXF 仅外轮廓）。

## 技术考虑 (Technical Considerations)

- **后端线程安全**：`_state_lock` 互斥；`_get_pieces_state()` 返回快照；`/ws/solve` accept 阶段拿一次，build_instance 用快照。并发 commit 与 solve 隔离。
- **label→pid 映射**：intermediate 加 `label` 字段（commit 时 `_label_for(idx)`），build_instance 按 `(label, sizeKey)` 查 quantities。向后兼容：旧 intermediate 无 label → demand=1。
- **5 层性能**：NestSVG 每片从 1 polygon → 5 节点，仅 manifest 建一次；frame 切换 setAttribute 不重建。128 片 × 5 = 640 节点，实测 ~10fps 可承受。
- **配色常量提取**：`PiecePreviewSVG` 的 5 层配色抽到 `constants/colors.ts`，NestSVG 与 export 共用，保证预览/排料/导出视觉一致。
- **后端契约最小改动**：US-019 删前端两档输入但 `params` 仍传（全 0），`build_instance` 签名不变；US-022/024 是 additive 扩展（quantities/5 层字段），旧调用方兼容。
- **ET2008 DXF 多 layer**：沿用 R12+POLYLINE；附加 layer 用独立 entity，layer 名沿用 LAYER_MAPPING（净版=14/内部线=8/刺口=4/布纹线=7）。

## 数据流（目标态）

```
[用户] 上传 M1787.dxf
   ↓
[前端 useParseDxf] fetch /api/parse-dxf → status=done, doc
   ├─ [US-016] setNestingEnabled(true)  ← Tab 解锁（D5）
   ├─ [US-022] qtyStore.hydrateDefaults(sizes, labels)  ← 每片每码=1（D3）
   └─ [US-021] 自动 commit(doc_id, filename)  ← D1 副作用
        ↓ POST /api/commit-to-nesting
[后端 _commit_to_nesting_sync]
   → collect_pieces → assign ptype → write_piece_dxf → load_nest_pieces
   → NestPiece[] + 扩 label(US-022)/net/internal/notches/grain(US-024)
   → 备份 .bak → 写 paths.INTERMEDIATE
   → [US-020] _reload_pieces_state()  ← 更新 _PIECES_STATE
   → 返回 {doc_id, sizes, n_pieces, reloaded:true}
        ↓
[前端 commit done]
   → setTab('nesting') 自动切入超排  ← [US-021]
[超排页]
   → [US-017] SizePicker 读 doc.sizes 全量码号
   → [US-019] 主面板精简（无两档输入）
   → [US-018] 「高级配置」按钮 → 弹窗 table 设每片型重合/旋转（D7 预填）
        ├─ 挂载 fetch GET /api/ptypes（US-020）→ 表头渲染片型缩略图（compact 外轮廓，D10）
        └─ 点击缩略图 → PtypePreviewModal 放大预览（v1 外轮廓，D11）
        ↓ [用户点 Start]
[前端 useSolveRun] WS payload {action:start, sizes, time, seed, params:全0, per_type, quantities(US-022)}
        ↓
[后端 /ws/solve]
   → accept: _get_pieces_state() 拿快照（US-020）
   → build_instance(snapshot, sizes, params, per_type, quantities)
       • 按 sizes 过滤
       • erode = min(per_type[ptype].d ?? 0, MAX_OVERLAP[ptype])
       • tol = min(per_type[ptype].tol ?? 0, ROTATION_TOL[ptype])
       • demand = quantities[label][sizeKey] ?? 1；0 跳过（US-022/D2）
       • pid_meta 含 net/internal/notches/grain（US-024）
   → spyrrow.solve（外轮廓 NFP 碰撞）
        ↓ manifest + frames
[前端 NestSVG] 5 层渲染（US-024）：毛版+净版+内部+刺口+布纹
        ↓ [用户点导出]
[后端 /export] placed_to_world 用 _PIECES_STATE.pieces_by_id
   → PNG 5 层 + R12-DXF 多 layer（US-024/D4，ET2008 真机验收）
```

## v1 / v2 切分

- **v1（主链路，~2 周）**：US-015 → US-016 → **US-020**（含 `/api/ptypes`）→ US-017 → US-018（弹窗 + 片型缩略图 + 放大预览，**外轮廓**）→ US-019 → US-021。打通「上传→解锁→码号承接→commit reload→自动切超排→高级配置弹窗（含缩略图/放大）」全链路；求解输入仍是外轮廓 + per_type 覆盖；缩略图/放大预览因 intermediate 仅 polygon 而只画外轮廓。
- **v2（数据维度，~1-2 周）**：US-022（数量 demand）+ US-023（颜色清理）+ US-024（5 层展示+导出，**顺带把 US-018 缩略图/放大预览自动升级为 5 层**）。US-023 可与 v2 并行。
