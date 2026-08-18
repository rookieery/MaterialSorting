# PRD: 裁片编号化重构（g 码全链路主键化 + 镜像/internal 概念删除）

## 概述 (Overview)

把裁片 g 码（g01+，每码内独立编号）从「显示标识」升级为**全链路唯一主键**：程序中一切用裁片种类中文名（前片/后片/腰/…）做匹配、键控、显示、落盘的逻辑全部换成 g 码；同时**彻底删除镜像（paired/L/R 展开）与 internal（内片）概念**——排料引擎语义收敛为「母版几何 × 用户数量」，不再合成任何几何、不再按名称集合做任何行为判断。

依据：[裁片编号化重构_方案.md](../.docs/business/裁片编号化重构_方案.md)（v5 终版，全部决策已落定）。动因：① 名称表（GROUP_NAMES）不全面且解析偶发出错，现状无映射组在 commit 时**直接丢片**（实测最新母版 block 名几乎全是空格/数字，名称启发式名存实亡）；② 生产排料文件本就单侧，镜像合成不是排料环节的事实需求，且 paired 布尔锁死 L≡R 表达不了不对等排料，数量矩阵天然表达一切组合。

## 目标 (Goals)

- 上传**任何**母版（未录入名称、无名 block 的新款）→ 全部轮廓有 g 码、不丢片、不合成、可排料（现状会丢片）。
- 全链路键统一 `(label, sizeKey)`：parse 响应 / intermediate / WS `quantities`+`per_type` / 前端 store / 导出。
- 界面（tooltip/弹窗/矩阵/预览）与导出（PNG 图例/SVG/DXF TEXT）**零中文片型名**。
- 高级配置改 (g 码, 码号) 逐片 d/tol 矩阵，端到端生效。
- 代码中 `GROUP_NAMES` / `PAIR_TYPES` / `INTERNAL_TYPES` / `ALL_TYPES` 常量与全部镜像展开分支删除（文档保留历史口径）。
- 重构不降低利用率：新基线（当前母版重 commit，110 片）同 seed 密度对拍一致。

## 用户故事 (User Stories)

### US-001: 后端数据模型 + commit 管线去名称化（label 先行、零合成）
- **Description**: As a developer, I want the commit pipeline re-ordered so g-code assignment (`assign_codes`) runs first and drives everything（`labeling.py` 签名精简 + T4 排序键、`export_dxf.py` 删 `GROUP_NAMES`/`assign_group_no`、`load_pieces.py` 删 `PAIR_TYPES`/`ALL_TYPES`/镜像分支改 manifest 驱动、NestPiece/intermediate schema v2、`server.py` commit/parse/ptypes 三管线重排）so that any master DXF commits without dropping pieces and no name-based behavior remains.
- **Acceptance Criteria**:
  1. `labeling.py`：`assign_codes`/`collect_master_codes` 签名删 `gmap`/`group_names` 参数，「有效片」= 全部 `size≠None` 片（不再要求 GROUP_NAMES 映射）；`compute_size_ptype_labels` 整体删除；顺序赋码排序键前置 `group_key`（block 名派生，名称无关）保证跨码同号（T4）。
  2. `export_dxf.py`：`GROUP_NAMES` 与 `assign_group_no` 删除，仅保留 `write_piece_dxf`；`server.py` 不再 import 两者。
  3. `load_pieces.py`：`PAIR_TYPES`/`ALL_TYPES` 删除；`load_nest_pieces` 改 **manifest 驱动**（读 `pieces_manifest.json` sidecar：`[{file,label,size}]`），每文件布纹对齐 + 归一化，**无镜像展开分支**（`_apply_layer_transforms` 的 mirror 路径一并删）；`NestPiece` 删 `ptype`/`side` 字段，`pid = f'{label}_{size}'`。
  4. commit 管线：`collect → assign_codes → write_piece_dxf({label}_{size}.dxf) + pieces_manifest.json → load_nest_pieces(manifest) → intermediate v2`（每母版轮廓恰一条，删 ptype/side/paired/internal；顶层 `ptype_representatives` → `label_representatives`）；**无映射组不再 skip**。
  5. `/api/parse-dxf` 响应 pieces 删 `name`/`ptype`/`paired`（保留 `label` + 5 层字段）；`/api/ptypes` 响应键 ptype→label；两响应字段与 `types/parsed.ts` 新契约一致（前端 US-003 消费）。
  6. 中间态兼容垫片：`solver.py`/`export.py` 对 intermediate 新 schema 的 `p['ptype']` 直接下标访问改 `.get()` 兜底（颜色/图例暂降级默认值，US-002 全量重做）——本 Story 结束时 `/ws/solve`、`/export` 在 v2 intermediate 上仍可跑通不崩。
  7. 后端测试改写全绿：合成「未录入名称」母版（伪造 block 名）commit 不丢片、全片有码；重 commit 当前母版后 intermediate 条数 = 母版轮廓数（110），label 与 parse 响应逐片对齐（AC#5：同一 `(block_name, size, piece_index)` 同码）。
  8. Python 模块可通过 `python -m materialsorting.web.server` / `python -m materialsorting.nesting_bounds.load_pieces` 等跑通、分层依赖未反向。
- **Priority**: 1

### US-002: 求解 + 导出 + CLI 引擎去名称化（LABEL_COLORS + 数量直译）
- **Description**: As a developer, I want the solve/export/CLI layers fully keyed by label（`solver.py` demand 直译 + per_type(label,size) + 删 internal 判断、`sparrow_baseline.py` PTYPE_COLORS→LABEL_COLORS + SVG 图例、`export.py` 删 TYPE_ACI/TYPE_ORDER + 图例 label 化、`constraints.py` 删 PAIR_TYPES 与成对齐套校验、`sparrow_experiments.py` 内片集合改 `--internal` 命令行参数）so that colors, legends and per-piece overrides follow g codes with zero Chinese names in any output.
- **Acceptance Criteria**:
  1. `solver.py`：demand 按 `(label, sizeKey)` 直译（0 跳过不变，demand 多副本不变量——同 pid N 条 placed_items——保持）；`per_type` 改 `per_type[label][sizeKey]` 命中即覆盖 d/tol（全局上限 `MAX_OVERLAP_MM=10`/`MAX_ROTATION_TOL_DEG=45` 收边不变）；删 `internal = ptype in INTERNAL_TYPES` 判断与 internal 相关分支；WS start 消息不再接收/透传 paired/internal。
  2. `sparrow_baseline.py` 共享层：删 `PTYPE_COLORS`，新增 `LABEL_COLORS` 单一真相源（16 色 d3 系循环表，`label_color(label) = PALETTE[(code-1) % 16]`，同码同色）；SVG 图例条目/聚合键 ptype→label，按 `code_sort_key` 数值序，图例标题「片型」→「裁片」。
  3. `export.py`：删 `TYPE_ACI`/`TYPE_ORDER`；PNG 图例条目 = 本次 placed 的 label 并集（文本 g 码）；DXF ACI = `((code-1) % 24) + 1`；placed pid 直查 intermediate（零重放）；PNG 质心文字/DXF TEXT 层 `g01-30` 叠印口径与 PLT 零文字口径不变。
  4. `constraints.py`：删 `PAIR_TYPES` 常量与成对齐套校验（L 数=R 数，服务于已删除的合成模型）；其余校验（重合/旋转全局上限、位图腐蚀）不动。
  5. `sparrow_experiments.py`：删 `INTERNAL_TYPES`；内片集合改命令行参数 `--internal g04,g07`（intermediate 已无该字段）；`ms-sparrow-exp` 入口随动重测。
  6. 验证：同 seed 同几何集（110 片、全 demand=1）求解密度与重构前同几何子集一致；PNG/SVG 图例全 g 码；导出三格式（PNG/DXF/PLT）零中文片型名。
  7. Python 模块可通过 `python -m materialsorting.nesting_engine.sparrow_baseline` / `python -m materialsorting.web.export` 等跑通、分层依赖未反向。
- **Priority**: 2

### US-003: 前端契约与显示层去名称化（types/tooltip/矩阵/预览）
- **Description**: As a 版师, I want the frontend to consume the new label-only contract（`types/parsed.ts`/`types/piece.ts`/`types/ptype.ts`/`types/v03.ts` 契约更新、NestSVG tooltip、QtyMatrix 删 paired ×2、SizePicker 物理片数口径、PieceZoomModal/PtypePreviewModal 显 g 码、`constants/v03.ts` 删 V03_PTYPES、store/hooks/tour 文案）so that every screen shows g codes only and piece counts equal Σ quantities.
- **Acceptance Criteria**:
  1. 契约类型随 US-001/002 新 schema 更新（parse piece 无 name/ptype/paired；manifest piece 无 ptype；`/api/ptypes` 键 label）；`useSolveRun`/`uploadStore`/`qtyStore` 消费链路同步，`grep -r "paired" src/` 生产代码 0 命中。
  2. `NestSVG.tsx` tooltip 改 `g03 · 码28`，命中判定 `dataset.ptype`→`dataset.label`。
  3. `QtyMatrix.tsx`：列头缩略图 title/aria = label（删 `rep.piece.name`）；**删 paired ×2 逻辑**，每码小计/每裁片合计/工具条总片数 = Σ perSize 数量；总片数悬浮提示口径文案更新（不再提「配对片型每份左右 2 物理片」）。
  4. `SizePicker.tsx` 物理片数 = Σ 数量（删 paired ×2 与 parse paired 消费）；`PieceZoomModal`/`PtypePreviewModal` 名称位显 g 码（`previewPtype`→`previewLabel`）。
  5. `constants/v03.ts` 删 `V03_PTYPES`（MAX_*_MM 保留）；tour 文案「片型」→「裁片 g 码」口径。
  6. 相关前端测试改写全绿（QtyMatrix 物理片数用例改 Σ 口径、paired 相关用例删除）；`npm run build` + `npx vitest run` 通过；通过浏览器验证：上传母版 → 矩阵/tooltip/放大预览全显 g 码、总片数 = Σ 数量、求解渲染正常（裁片布局/利用率）。
- **Priority**: 3

### US-004: 高级配置弹窗矩阵化（(g 码, 码号) 逐片 d/tol）
- **Description**: As a 版师, I want the advanced config modal rebuilt as a label × size matrix（`PerTypeOverridesModal.tsx` 矩阵化：行=码号、列=当前母版 g 码并集、每格 d/tol 双输入；`lib/params.ts` per_type 输出 `{label:{sizeKey:{d?,tol?}}}` + URL 分享格式随动）so that I can tune overlap/rotation tolerance per (g-code, size) pair instead of per Chinese piece name.
- **Acceptance Criteria**:
  1. 弹窗结构与数量矩阵同构（复用 QtyMatrix 交互范式与样式）：列 = parse 响应 label 并集（`compareByLabel` 数值序，列头缩略图取 `/api/ptypes` label 键 + g 码徽章 + ≡ 整列设值）；行 = 参与排料码号；格 = d/tol 两个小输入，空 = 继承全局默认（0/0）。
  2. 草稿 + 确定、ESC/遮罩关闭、双层 modal 独立 ESC 既有约定保留；`collectParams` 输出 `{label: {sizeKey: {d?, tol?}}}`（空串剔除，整体空 → null）；URL 分享参数 `per_type` 新格式（旧键忽略）。
  3. 端到端：弹窗配 `g03@28 d=1.5` → WS start payload `per_type.g03['28'].d === 1.5` → 求解生效（US-002 后端命中覆盖）。
  4. `PerTypeOverridesModal.test.tsx` 重写（矩阵结构/草稿确认/整列设值/序列化）+ `params.test.ts` 新格式用例；`npm run build` + `npx vitest run` 通过；通过浏览器验证弹窗矩阵渲染与操作。
- **Priority**: 4

### US-005: 测试收口 + 文档同步 + 新基线对拍
- **Description**: As a maintainer, I want all docs, tests and the density baseline updated to the new label-only reality（grep 验收、CLAUDE.md/3×AGENTS.md/排料规则_详细版/agent-api-reference/agent-component-map/business-overview、当前母版重 commit 建新基线）so that the codebase and documentation agree and the refactor provably didn't regress utilization.
- **Acceptance Criteria**:
  1. `grep` 十个中文片型名（前片/后片/腰/前袋/后袋/机头/单排/双排/短双排/火机袋/裤耳）在后端+前端**非测试、非注释、非 explore.py** 代码 0 命中。
  2. 文档同步：`CLAUDE.md`（数据流主线 + labeling 单一真相源描述）、3×`AGENTS.md`（各层文件表）、`.docs/business/排料规则_详细版.md`（§1.1 增补「引擎不合成镜像」口径、§2.3 成对镜像条款改口径）、`.docs/technical/agent-api-reference.md`（parse/commit/ptypes/WS 契约）、`agent-component-map.md`、`business-overview.md`（镜像展开→数量即一切、176→110）。
  3. 新基线：当前母版重 commit（intermediate 110 片、全 demand=1）→ 同 seed 求解，real density 记录归档为对拍基线；旧基线（176 片含合成镜像）归档不再对拍。
  4. 全量 `pytest` + `npx vitest run` + `npm run build` + `npm run typecheck` 全绿（3 个 test_ws_stop 既有失败除外）；pyproject 4 个 CLI 入口（`ms-*`）逐个跑通。
- **Priority**: 5

## 功能需求 (Functional Requirements)

- FR-1: g 码主键 — 全链路（parse → commit → intermediate → WS → 前端 → 导出）键统一 `(label, sizeKey)`；g 码每码内独立零填充（g01…），零填充不可去（字典序=数值序）。
- FR-2: 母版码复用 — 母版 block 名自带 `g/G/#`+1-3 位数字且每码内唯一时 all-or-nothing 复用；任一缺失/冲突整体回退顺序赋码（既有规则不动）。
- FR-3: 数量即一切 — 母版 N 个轮廓 → intermediate N 条；每片排几份由 `quantities[label][sizeKey]` 决定（0=跳过）；任意不对等组合可表达。
- FR-4: 零合成零丢片 — 程序不合成镜像、无映射组不再 skip；marker = 母版轮廓 × 数量（WYSIWYG）。
- FR-5: manifest 驱动加载 — 切片目录 `{label}_{size}.dxf` + `pieces_manifest.json` sidecar；文件名仅人读，语义全在 manifest。
- FR-6: 颜色随 g 码 — `LABEL_COLORS` 16 色循环单一真相源（共享层），同码同色；DXF ACI `((code-1)%24)+1`；图例条目 = placed label 并集按数值序。
- FR-7: 高级配置逐片 — per_type 键 `(label, sizeKey)`，命中即覆盖 d/tol，全局上限收边（10mm / 45°）不变。
- FR-8: 界面/导出零中文名 — tooltip/弹窗/矩阵/预览/图例/DXF TEXT 全 g 码；PLT 永不加文字（不变）。
- FR-9: 旧数据不双读 — 旧 intermediate/旧切片目录明确报错「请重新 commit」（不静默兼容）。

## 非目标 (Non-Goals)

- **打板/母版侧任何改动**：母版维持单侧现状（生产排料文件本就单侧），无需重出。
- **排料算法/利用率优化**：90% 攻坚不在本次范围；本次以「同 seed 密度不降」为验收。
- **旧数据迁移/双读**：不写 schema 兼容层，重新 commit 即迁移。
- `dxf_parser/explore.py` 阶段 1 离线分析工具不动（中文名输出是它的用途本身）。
- **不重写 sparrow**：仍作 pip 包（spyrrow）外层包装；`solve_with_callback_proc` 多进程架构、WS stop 协议、phase 状态机、多 seed 并发全部不动。
- PLT 导出链路（HPGL 封装、1910 可写幅宽、PD 分块）零改动（本就零文字）。

## 设计考虑 (Design Considerations)

- 高级配置弹窗与数量矩阵同构（行=码号 × 列=g 码并集、列头缩略图+徽章+≡ 整列设值、格内双输入），复用 QtyMatrix 交互范式与 `style.css` 既有样式段，不引入 CSS 框架。
- 图例规模：placed label 并集 ≤20 条（每码独立编号），按 `code_sort_key` 数值序排列，同码同色降低视觉噪音。
- QtyMatrix 列头缩略图 title 从「中文名 · 放大预览」改「g01 · 放大预览」；aria-label 同步（测试断言随动）。
- 前端 `scale(1,-1)` 坐标翻转、命令式 SVG 渲染逃逸 React reconciliation 的既有架构不动。

## 技术考虑 (Technical Considerations)

- **AC#5 对齐不变量简化**：parse 与 commit 各自对同一母版跑 `assign_codes`（同 collect、同排序键、同母版码规则）→ 同一 `(block_name, size, piece_index)` 必得同码，不再经 (size, ptype) 中转——这是 demand 键对齐的根基，US-001 验收覆盖。
- **demand 多副本不变量保持**：`Item(demand=N)` → sparrow 同 pid 发 N 条 placed_items；前端建 N 副本、密度按原面积×demand 口径，与现状一致（删镜像不影响该不变量）。
- **迭代中间态**（连续实施时仅存在于迭代间隙）：US-001 后前端旧契约消费降级（弹窗缩略图空/图例暂默认色）；US-002 后 per_type 旧 ptype 键被后端忽略为 no-op，US-004 落地前端新格式后闭环。
- **门幅三常量不动**：`GATE_MM=1980`/`PLOT_SAFE_MAX_Y_MM=1910`/`NEST_GATE_MM` 单一事实源在 `load_pieces.py`，本次重构保持原值原语义。
- **R12 + POLYLINE 导出、ezdxf recover + GBK 读取等既有决策不动**。
- 环境注意：后端 venv=`.venv/Scripts/python.exe`；改 `server.py` 后 verify-api hook 报端点 404 属已知误报；console 中文输出用 `-X utf8` 防 GBK 乱码。

## 成功指标 (Success Metrics)

- [ ] `grep` 中文片型名在非测试/非注释/非 explore.py 代码 0 命中；`GROUP_NAMES`/`PAIR_TYPES`/`INTERNAL_TYPES`/`ALL_TYPES` 程序内 0 定义。
- [ ] 合成无名 block 母版 commit：0 丢片、100% 有 g 码（现状会丢片）。
- [ ] 当前母版重 commit → intermediate 110 条 = 母版轮廓数，parse↔intermediate label 逐片一致。
- [ ] 界面与 PNG/SVG/DXF 导出零中文片型名；PLT 零文字。
- [ ] per_type (g 码, 码号) 配置端到端生效（WS payload → 求解结果差异可复现）。
- [ ] 新基线（110 片全 demand=1）同 seed real density 对拍一致；`pytest` + `vitest` + `build` + `typecheck` 全绿。

## 待确认问题 (Open Questions)

- 无阻塞项（方案 v5 全部决策已落定：D1-D5 / T1-T7 / T3′ 镜像全删 / R1 internal 移除 / 母版维持单侧）。
- 备注：US-001 是最重的一个迭代（4 个后端文件 + 管线重排 + 测试）；如需拆分只能拆「labeling+export_dxf+load_pieces」与「server.py 管线」两步，代价是中间存在非绿状态，默认不拆。
