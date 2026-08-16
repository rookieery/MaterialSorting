# PRD: 上传预览裁片数量编辑交互重构（裁片 × 尺码矩阵）

## 概述 (Overview)

把上传预览页「按尺码分 tab + 逐片弹窗改数量（仅当前尺码/全部尺码）」的交互重构为「裁片 × 尺码」数量矩阵：每行一个裁片、每列一个尺码，格内直接编辑，一次看全全部码的数量分布；配合「整行填充默认值 + 个别格子改特例 + 特例高亮」的批量操作模式。解决版师反馈的核心痛点：同一裁片在不同尺码数量不同（部分码 2 片、部分码 1 片）时，现状需逐 tab 切换逐个改（11 码 = 完整重复 11 次），且「全部尺码」global 模式会把其它码锁死，无法表达「默认 1、个别码 2」。

依据：所有尺码内部裁片种类完全一致（每码同一批 A–J 约 10 片型，仅数量分布不同），矩阵约 10 行 × 11 列规模可控。**WS `quantities` 线格式（`{label: {sizeKey: N}}`）与后端主管线（parse/commit/solve/镜像/demand 多副本）完全不变**，改动集中在前端预览页 + qtyStore。

## 目标 (Goals)

- 跨码设置一个数量特例（如裁片 A 在 28/29 码 2 份、其余码 1 份）的交互成本从「2×N 次完整弹窗流程」降为「1 次整行填充 + K 次格内编辑」（K=特例码数）。
- 全部尺码 × 全部裁片的数量分布一屏可见，特例格子视觉上直接可辨（高亮）。
- 提供「整行设默认值」批量操作（吸收"默认数量+覆盖"操作思想，但不重写数据模型）。
- 每码小计 / 每行合计 / 总片数即时反馈；全 0 时求解启动拦截（现状会把空实例交给 spyrrow）。
- WS 线格式逐字节不变，后端主管线零改动（唯一后端改动 = parse 响应 additive 透传 `ptype`/`paired`，US-004 本轮实施）。

## 用户故事 (User Stories)

### US-001: qtyStore 数据层简化 + 整行填充 action
- **Description**: As a developer, I want to simplify the quantity data model in `materialSorting-web/src/types/qty.ts` + `src/store/qtyStore.ts` + `src/lib/params.ts`（drop global 模式，`PieceQuantity` 改 `{ perSize, baseValue }`，新增 `setRowAll`）so that the matrix UI can batch-fill rows while the WS wire format stays byte-identical.
- **Acceptance Criteria**:
  1. `PieceQuantity = { perSize: Record<string, number>; baseValue: number }`；`QtyMode/globalValue/globalSource` 与 `setPieceGlobal` 删除，`grep setPieceGlobal src/` 为 0 且无残留引用；`hydrateDefault`/`hydrateDefaults` 双入口合并为单一 hydrate（以 grep 生产调用方为准），hydrate 时每 (label, size) 默认 1 且 `baseValue: 1`。
  2. `setRowAll(label, sizes, value)`：整行写入 `perSize`（value 经 `clampQty`）并把 `baseValue` 置为 value；`setPiecePerSize` 保留 perSize 写入、删 global 回切逻辑；`getPieceDisplay` 简化为 `{qty, editable}`（editable 仅在"该码无此裁片"时 false）；`clampQty` 公式不变（[0,99] 整数，NaN→0）。
  3. `serializeQuantities` 删 global 分支后输出结构 `Record<label, Record<sizeKey, number>>` 与旧版 per-size 路径逐字段一致（显式 0 保留、未勾选码过滤、`sizeKey(null)='null'` 兜底）。
  4. `qtyStore.test.ts`（删 global 相关约半数用例，新增 setRowAll/hydrate baseValue 用例）与 `params.test.ts` 改写后全绿；`npm run build` + `npm run typecheck` 通过。
- **Priority**: 1

### US-002: QtyMatrix 矩阵组件（格内编辑 + 整行填充 + 特例高亮 + 小计）
- **Description**: As a 版师, I want a piece-by-size matrix component (`materialSorting-web/src/components/preview/QtyMatrix.tsx` + `style.css` 样式段) where each row is a piece and each column a size, with in-cell editing, row fill, override highlight and subtotals, so that I can see and edit all quantities in one screen.
- **Acceptance Criteria**:
  1. 行 = 全码 label 并集（行头：A 徽章 + 裁片名 + 缩略图，缩略图点击 `openZoom` 复用 PieceZoomModal）；列 = `doc.sizes` 全码（null 码列尾「通用」，无 null 码不渲染该列）；列头为 button，点击 `setSize(该码)` 驱动下方图形预览区，当前预览码列头高亮。
  2. 格子为内联 number input（Enter/Tab 跳下一格、blur 提交、值一律过 `clampQty`），写入 qtyStore；数量 0 格子有显著暗色样式（语义=该码不排此片，tooltip 说明）；某码缺该 label 的格子渲染为 disabled「—」（区别于 0）。
  3. 行头「填充」popover：输入 X 应用 → `setRowAll`，即"默认值"；特例高亮 = 格子值 ≠ 该行 `baseValue` 且整行非全同时加高亮类名（整行同值不高亮，避免噪点）。
  4. 每行合计列 = Σ 该行各码 demand；底部每码小计行 = Σ 该码各 label demand；工具条显示总片数（本 Story 先用 Σdemand 口径，US-004 升级物理片数口径）+ 全 0 红色警示 + 「重置为默认 1」（全行 `setRowAll(label, sizes, 1)`）。
  5. 布局：矩阵区 `max-height: 45vh` 内部滚动，sticky 表头 + sticky 首列（行头），窄屏（≤1366）横向滚动；不引入 CSS 框架，暗底 `#26282e` + `#2ea06c` 同色系。
  6. 新增 `QtyMatrix.test.tsx` 覆盖以上可断言项（列头点击 setSize / 格子写 store / setRowAll 整行更新 + baseValue / 特例与 0 格子类名 / 缺片格 disabled / 小计与总片数数值）；`npm run build` + `npx vitest run` 全绿；通过浏览器验证矩阵渲染（11 码横排或横滚、sticky 生效、编辑与填充操作可用）。
- **Priority**: 2

### US-003: 拆除旧交互（SizeTabs/弹窗/Switch）+ 预览页集成 + 全 0 拦截
- **Description**: As a 版师, I want SizeTabs / PieceQtyDialog / Switch removed and QtyMatrix integrated into `PreviewPage.tsx`（ParsedPiecesView 保留为按码图形预览，卡片头数量改只读）so that tab-switching friction disappears without losing piece preview/zoom capability.
- **Acceptance Criteria**:
  1. `SizeTabs.tsx` / `PieceQtyDialog.tsx` / `Switch.tsx` 及其测试文件删除；`uploadStore` 删 `qtyDialog/openQtyDialog/closeQtyDialog`（`zoom/activeSize/setSize` 保留，`reset()` 同步清理）；`grep openQtyDialog src/` 为 0。
  2. `ParsedPiecesView` 卡片头数量改只读 span（值 = `getPieceDisplay().qty` + 单位「份」）；区标题显示「图形预览 · 码 X」；点卡片体仍 `openZoom`；`activeSize` 不在 doc.sizes 的防御空态保留。
  3. `PreviewPage` 挂 `<QtyMatrix/>` 替换 `<SizeTabs/>`，删 `<PieceQtyDialog/>` 单例（PieceZoomModal 保留）；doc_id 变化联动 `resetQuantities` 与 US-016 `setNestingEnabled` 联动两条 effect 不动。
  4. `ControlPanel.handleStart` 增加校验：所选码有效片数为 0 时不启动并 `onStatus` 提示（复用 `computeTotalCutPieces` 判 0）。
  5. `SizePicker.test.tsx` 中依赖 global 模式的用例改写（effectiveDemand 删 global 分支）；`PreviewPage.test.tsx` / `ParsedPiecesView.test.tsx` / `uploadStore.test.ts` 改写后全绿；端到端用例：矩阵改 A@28=2 → 求解 start payload `quantities.A['28'] === 2`；全 0 时开始求解被拦截。
  6. 通过浏览器验证端到端：上传母版 → 矩阵整行填充 → 个别格子改特例（高亮）→ 列头切码看图形预览 → 超排页求解正常接收 quantities；`npm run build` + `npx vitest run` 全绿。
- **Priority**: 3

### US-004: parse 响应透传 ptype/paired + 物理片数口径
- **Description**: As a 版师, I want `/api/parse-dxf` pieces to carry `ptype` 与 `paired`（`materialSorting-server/src/materialsorting/web/server.py` `_build_parse_payload`，additive 字段）so that the matrix and SizePicker can show real physical piece counts（配对片 ×2）instead of label 份数，修正现状「总裁片数量」少算配对片的语义偏差。
- **Acceptance Criteria**:
  1. `_build_parse_payload` 经 `assign_group_no` + `GROUP_NAMES` 链路为每片附加 `ptype`，`paired = ptype ∈ PAIR_TYPES`；additive 字段，旧前端忽略无害；parse 响应其余字段与排序不变（A/B/C 标注链路不动）。
  2. 前端 `types/parsed.ts` 加可选字段 `ptype?: string` / `paired?: boolean`；矩阵行头显示配对徽章（如「×2」）；每码小计与工具条总片数 = Σ demand × (paired ? 2 : 1)；`SizePicker.computeTotalCutPieces` 同口径修正（缺字段向后兼容按 1 计）。
  3. 后端现有 parse/commit 测试不受影响（响应仅增字段）；`curl POST /api/parse-dxf` 验证响应含两字段；前端相关测试改写全绿。
  4. 后端 Python 模块可通过 `python -m materialsorting.web.server` 导入跑通、分层依赖未反向（web 仅调用 dxf_parser 既有函数，无新跨层依赖）。
- **Priority**: 4

### US-005: tour 锚点/文案更新 + 文档同步
- **Description**: As a new user, I want the preview tour (`materialSorting-web/src/tour/steps/previewTour.ts`) and project docs to describe matrix-based quantity editing so that onboarding matches the new UI.
- **Acceptance Criteria**:
  1. previewTour 第 2/3 步锚点从 `[data-tour="size-tabs"]` / `[data-tour="piece-card-head"]` 改为矩阵（如 `[data-tour="qty-matrix"]` / 行头或列头），`QtyMatrix.tsx` 落地对应 `data-tour` 属性；文案描述列头切码预览 / 格内编辑 / 整行填充；锚点属重大变更，`TOUR_VERSION` bump 强制重看；tour 相关测试同步改写全绿。
  2. `.docs/technical/agent-component-map.md`（US-008/011/012/014/022 相关段落加重构后说明：QtyMatrix 替代 SizeTabs/弹窗，qtyStore 单模式）与 `.docs/business/business-overview.md`「工作台交互」第 2 条、`CLAUDE.md` 数据流主线一句同步更新。
  3. `npx vitest run` 全量通过 + `npm run build` 通过。
- **Priority**: 5

## 功能需求 (Functional Requirements)

- FR-1: 矩阵行列 — 行 = 全码 label 并集（保序：按最小码 pieces 顺序），列 = `doc.sizes` 全码（升序、null 殿后「通用」列）。
- FR-2: 格内编辑 — 点击直接键入；Enter/Tab 提交并移到下一格；blur 提交；一律 `clampQty`（[0,99] 整数）。
- FR-3: 整行填充 — 行头 popover 输入默认值 → `setRowAll`，同时更新 `baseValue`（特例高亮基准，不参与序列化）。
- FR-4: 特例高亮 — 格子值 ≠ `baseValue` 且整行非全同 → 高亮样式；整行同值不高亮。
- FR-5: 小计反馈 — 每行合计列、每码小计行、工具条总片数（US-004 前按 Σdemand、后按物理片数口径）；全 0 红色警示。
- FR-6: 图形预览入口 — 列头点击 `setSize(该码)`，下方 ParsedPiecesView + PieceZoomModal 按该码展示（保留"查看某尺码裁片"能力，tab 的原始职责）。
- FR-7: 0 与缺片语义区分 — 数量 0 = 该裁片该码不排（build_instance 显式跳过，现状不变）；某码无此 label = disabled「—」不可编辑。
- FR-8: 全 0 拦截 — `ControlPanel.handleStart` 在所选码有效片数为 0 时拒绝启动并提示。
- FR-9: 数量单位语义 — UI 文案统一「份」（配对片 1 份 = L+R 2 物理片；US-004 后以徽章说明实际片数）。

## 非目标 (Non-Goals)

- 不改 WS `/ws/solve` 契约、`build_instance` demand 语义、镜像 L/R 展开、demand 多副本机制（同 pid N 条 placed_items / 密度×demand / 前端 N 副本全部保持）。
- 不做数据模型 sparse 重写（`{default, overrides}` 方案否决——迁移成本高、与后端全量 per-size 线格式不对称性大）。
- 不改 `/api/commit-to-nesting`（数量与 commit 本就解耦）。
- 不做响应式两段式降级布局（窄屏只走 sticky + 横滚）。
- 不迁移/持久化 qtyStore（内存 store 刷新回默认 1，与现状一致）。
- L/R 不拆两行展示（保持"该裁片几份"用户语义，避免 ×2 心算）。

## 设计考虑 (Design Considerations)

- **布局**：`.preview-main` 纵向 = QtyMatrix（`max-height: 45vh` 内滚 + sticky 表头/首列）+ ParsedPiecesView（语义改为「图形预览 · 码 X」，卡片 grid 保留）。
- **视觉**：沿用 `style.css` 暗底（`#26282e`/`#2a2c32`）+ `#2ea06c` 强调色系，不引入 CSS 框架；特例高亮与 0 格用可断言的区分类名（`.qty-cell.override` / `.qty-cell.zero`）。
- **宽度**：M1787 实际 11 码（28–38，非 DEFAULT_SIZES 8 码），矩阵须按动态 `doc.sizes` 设计（约 10 行 × 11 列）；1920 桌面横排可容，≤1366 走横滚。
- **列宽基准**：格子约 64px + 行头约 200px + 合计列；列头同时承担"图形预览码切换"职责，当前码高亮。
- **tour**：锚点从 SizeTabs/卡片头迁到矩阵后属重大变更，`TOUR_VERSION` bump。

## 技术考虑 (Technical Considerations)

- **线格式不变是硬约束**：`serializeQuantities` 删 global 分支后，per-size 路径输出（显式 0 保留、未勾选码过滤、'null' 兜底）必须与旧版逐字段一致——这是后端主管线零改动的唯一依据。
- **数量语义**（以现有代码为准）：demand=N 施加在 (label, size) 的**每条** NestPiece 上 → 配对片型（PAIR_TYPES 6 类）实际排 2N 物理片，内片 N 片；`demand=0` 跳过；缺 quantities → 全片 demand=1。
- **`getPieceDisplay` 是 UI 消费唯一入口**的现状保持：简化后仍由 QtyMatrix / ParsedPiecesView / PieceZoomModal 统一消费，不直接读 `quantities[label]`。
- **hydrate 双入口合并**：qtyStore 现有 `hydrateDefault`/`hydrateDefaults` 双入口已现漂移风险，US-001 合并为单一入口并补 `baseValue: 1`；PreviewPage doc_id 变化联动 effect 不动。
- **后端增强 additive**：`_build_parse_payload` 加 `ptype/paired` 复用 commit 同链路（`assign_group_no` + `GROUP_NAMES`），改响应字段需同步 `types/parsed.ts`（可选字段向后兼容）；`labeling.compute_size_ptype_labels` 保证 parse 与 intermediate label 对齐的不变量不动。
- **测试面**：删除面集中在 global 模式（qtyStore 约半数用例、PieceQtyDialog 15 项、Switch 5 项、SizeTabs 8 项、params/serialize global 分支、PreviewPage/ParsedPiecesView 相关断言），属机械性改写。

## 成功指标 (Success Metrics)

- [ ] 跨码设一个特例（部分码 2、其余 1）= 1 次整行填充 + 特例码数次格内编辑（现状为 2×11 次弹窗流程）。
- [ ] 全部码 × 全部裁片数量分布一屏可见，特例高亮可辨。
- [ ] WS start payload `quantities` 结构与重构前逐字段一致（回归用例全绿）。
- [ ] 全 0 求解被前端拦截，不再把空实例交给 spyrrow。
- [ ] `npm run build` + `npx vitest run` 全量通过（前端）；US-004 后 `python -m materialsorting.web.server` 导入正常（后端）。

## 已确认决策（2026-08-16 版师/开发确认）

1. **US-004 本轮一并实施**：物理片数口径（配对片 ×2）随本次重构落地，不做延后。
2. **矩阵高度上限 45vh** 定稿（内部滚动 + sticky，下方图形预览区随列头切换）。
3. **整表「重置为默认 1」按钮保留**（工具条低频兜底操作）。
4. **未填充时 `baseValue` 默认 1 作高亮基准** 定稿（hydrate 写 1；纯逐格手改场景高亮以 1 为基准）。
