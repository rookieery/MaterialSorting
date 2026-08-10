# PRD: DXF 上传解析预览页

## 概述 (Overview)

在现有单页排料工作台之上新增一个并列的「DXF 上传预览」页，顶部 Tab 切换。版师/操作员上传生产母版 DXF（多码合一），服务端深度解析还原裁片全部信息——毛版外轮廓、净版轮廓、内部线条、刀口位置、布纹线方向——右侧按尺码切换预览，每码裁片按 A/B/C 顺序标注。预览解析结果可经后端端点转成排料 intermediate（**v1 后端就绪，前端 commit 入口随排料页改造补齐**），替代当前手动 CLI 管线。

## 目标 (Goals)

- **可视化还原**：在浏览器里完整呈现母版裁片的毛版/净版/内部线/刀口/布纹线，与版师认知一致（刀口为沿轮廓法线的短线段）。
- **尺码切片**：单文件多码（28-38 共 8-11 码）按尺码分组预览，A/B/C 标注，可即时切换。
- **零中断切换**：Tab 切换不卸载组件（`display:none`），切回排料页时进行中的求解与 WS 连接不中断。
- **闭环注入（v1 后端）**：后端端点把上传母版转成 `NestPiece[]` 覆盖 intermediate（**全码**），无需手动跑 `ms-export-dxf` + `ms-pieces-export`；排料页自动 reload 与前端 commit 入口随排料页改造补 TODO。
- **架构守纪**：全程不破坏分层依赖、不硬编码路径、复用现有 dxf_parser 与几何变换，新增仅「加法」不动现有 `/export` 与 `/ws/solve`。

## 用户故事 (User Stories)

### US-001: 前端 Tab 框架 + NestingPage 外提
- **Description**: As a 版师，我希望在顶部用 Tab 在「排料」与「上传预览」两个页面间切换，且切回排料页时求解/WS 不中断，so that 我可以一边排料一边上传新母版预览而不丢状态。
- **Acceptance Criteria**:
  1. 新建 `materialSorting-web/src/components/TabBar.tsx`，渲染两个 Tab（排料 / 上传预览），当前激活项高亮。
  2. 新建 `store/uiStore.ts`（Zustand），持有 `activeTab: 'nesting' | 'preview'` 及 `setTab()`。
  3. 将 `App.tsx` 中现有排料逻辑（ControlPanel + NestsGrid + PlaybackBar 等）外提到 `components/NestingPage.tsx`，App 仅保留 TabBar + 两个页面容器。
  4. 两个页面通过 `display:none` 切换而非卸载（非激活页 DOM 保留），切回时已有的求解状态、WS 连接、播放进度全部保留。
  5. 沿用 `style.css`，不引入 CSS 框架；TabBar 视觉与现有 ControlPanel 风格一致。
  6. 通过浏览器验证：在排料页发起求解→切到预览页→切回排料页，求解进度/WS 未中断（控制台无断连）。
  7. `cd materialSorting-web && npm run build` 通过，`npm run dev` 两个 Tab 均可切换。
- **Priority**: 5（前端基础，零后端依赖，可与 US-002~004 并行启动）

### US-002: PieceOutline 扩字段 + reader layer 过滤工具
- **Description**: As a 解析引擎，我希望 `PieceOutline` 能承载裁片全部细节（内部线/刀口/净版），并在 `reader.py` 提供按 layer 过滤实体的工具，so that 深度解析有统一的 IR 与提取手段。
- **Acceptance Criteria**:
  1. `dxf_parser/model.py` 的 `PieceOutline` 新增三字段（均带默认值保证向后兼容）：`internal_lines: list = field(default_factory=list)`、`notches: list = field(default_factory=list)`、`net_polygon: list = field(default_factory=list)`。
  2. `to_dict()` 继续用 `asdict(self)`，新字段自动序列化；既有调用方（`pieces_export`、`sparrow_baseline`）无需改动即可工作（默认空 list）。
  3. `dxf_parser/reader.py` 新增 `iter_block_entities(block, layers: set[str] | None = None)` —— 按可选 layer 白名单迭代 block 内实体；不指定 layer 时返回全部。仅标准库 + ezdxf。
  4. 不引入对兄弟包的依赖（dxf_parser 仍只依赖标准库 + ezdxf）。
  5. `python -c "from materialsorting.dxf_parser.model import PieceOutline; from materialsorting.dxf_parser.reader import iter_block_entities"` 导入通过、分层依赖未反向。
- **Priority**: 1（dxf_parser 基础，无依赖）

### US-003: collect_pieces_with_details() 深度解析
- **Description**: As a 解析引擎，我希望有一个 `collect_pieces_with_details()` 函数从母版 block 还原每片裁片的毛版/净版/内部线/刀口/布纹线，so that 预览与 intermediate 转换有完整数据。
- **Acceptance Criteria**:
  1. 在 `dxf_parser/explore.py`（或新建 `dxf_parser/collect.py`）新增 `collect_pieces_with_details(path) -> list[PieceOutline]`。
  2. 复用现有 `collect_pieces()` 提取 layer1 毛版外轮廓 + layer7 布纹线（match_grain）；新增二次扫描：layer14 POLYLINE→`net_polygon`、layer8 POLYLINE→`internal_lines`、layer4 POINT→`notches`。
  3. 刀口按"沿所属轮廓法线方向画短线段"模型：`notches` 存为 `[(x, y, nx, ny)]`（点 + 单位法向量），渲染时画定长（如 8mm）线段；刀口点用 point-in-polygon + 最近轮廓边匹配归属到具体 outline。
  4. layer 映射集中在常量 `LAYER_MAPPING`（毛版=1, 净版=14, 内部线=8, 布纹线=7, 刀口=4），其余 layer（2/3/13）不提取。
  5. 对 `data/` 下 5156 与 M1787 两个生产母版跑通，每码裁片数与现有 `collect_pieces()` 的 outline 数一致，且 internal/notch/net 非空（版师确认腰片等应有刀口）。
  6. `python -m materialsorting.dxf_parser.collect <dxf_path>` 可对任意母版打印每码裁片数 + 各字段计数（CLI 冒烟）。
  7. 模块可通过 `python -m materialsorting.dxf_parser.<module>` 跑通、分层依赖未反向（dxf_parser 不 import 兄弟包）。
- **Priority**: 2（dxf_parser，依赖 US-002）

### US-004: POST /api/parse-dxf 端点
- **Description**: As a 前端，我希望有一个上传端点接收 DXF 并返回按尺码分组、A/B/C 标注的解析结果，so that 用户上传后即可预览。
- **Acceptance Criteria**:
  1. `web/server.py` 新增 `POST /api/parse-dxf`，multipart 接收单文件，**不动**现有 `/`、`/static`、`/export`、`/ws/solve`。
  2. 落盘到 `paths.OUT_DIR / "uploads" / f"{uuid}.dxf"`（用 `from .. import paths`，不硬编码），CPU 密集解析走 `loop.run_in_executor(_executor, ...)` 复用现有 ThreadPoolExecutor，防阻塞事件循环。
  3. 解析调用 US-003 的 `collect_pieces_with_details()`；响应 JSON 结构：`{ doc_id, filename, sizes: [{size, pieces: [{label:'A'|'B'|..., name, polygon, internal_lines, notches, net_polygon, grain_line}]}] }`（**doc_id=落盘 uuid，供 US-010 commit 引用**），**全码一次返回**（实测 ~1-3MB JSON 可接受，前端按 activeSize 本地切片，不搞按码懒加载）；裁片在每码内按几何质心/面积稳定排序后赋 A/B/C… 标签。
  4. 文件扩展名非 `.dxf` → 400；ezdxf 解析异常 → 422（返回中文错误信息）；成功 → 200。
  5. 文件大小上限 20MB（实测生产母版 ~3MB，留足余量）超限 → 413。
  6. `python -c "from materialsorting.web.server import app"` 导入通过；用 `curl -F file=@<dxf> http://127.0.0.1:8000/api/parse-dxf` 对 M1787 返回各码裁片数 > 0、含刀口/internal 字段；分层依赖未反向。
- **Priority**: 3（web，依赖 US-003）

### US-005: 前端类型 + uploadStore + useParseDxf hook
- **Description**: As a 前端，我希望有 ParsedPiece 类型定义、上传状态 store 与带防连击的请求 hook，so that 上传与预览组件有统一数据源。
- **Acceptance Criteria**:
  1. 新建 `types/parsed.ts`：`ParsedPiece`、`ParsedSize`、`ParsedDoc`（与 US-004 响应结构一致）。
  2. 新建 `store/uploadStore.ts`（Zustand）：`status: 'idle'|'uploading'|'done'|'error'`、`doc: ParsedDoc|null`、`activeSize: string|null`、`error: string|null`、actions `reset()`/`setSize()`。
  3. 新建 `hooks/useParseDxf.ts`：封装 `fetch('/api/parse-dxf', {method, body: FormData})`，更新 uploadStore；**防连击**（上传中重复触发被忽略）；请求路径走相对路径（dev 经 Vite proxy，prod 经 FastAPI 同源）。
  4. 不引入新依赖（仅 React + Zustand + 现有 fetch）。
  5. `cd materialSorting-web && npm run build` 通过；`tsc --noEmit` 无类型错误。
- **Priority**: 6（前端，依赖 US-004 契约定类型）

### US-006: UploadPanel 组件（点击 + 拖拽）
- **Description**: As a 版师，我希望点击按钮或拖拽文件上传 DXF，并看到上传状态/错误反馈，so that 上传操作直观可靠。
- **Acceptance Criteria**:
  1. 新建 `components/preview/UploadPanel.tsx`：含点击上传按钮（触发隐藏 `<input type=file accept=".dxf">`）+ 拖拽落区（dragover/drop 事件）。
  2. 仅接受 `.dxf`（后缀校验 + MIME 容错）；非 .dxf 文件给出明确提示且不发请求；**单文件上传**，拖入多文件时拒绝并提示。
  3. 从 uploadStore 读 `status`/`error`：uploading 显示加载态、error 显示红字错误、done 显示文件名 + 解析出的码数概览（如「已解析 8 码 / 110 裁片」）。
  4. 沿用 `style.css`，与 ControlPanel 视觉风格一致；左侧固定宽度，右侧留给预览。
  5. 通过浏览器验证：分别用点击与拖拽上传 M1787，看到加载→完成态切换；拖入 .txt 看到 .dxf 校验拒绝提示。
  6. `cd materialSorting-web && npm run build` 通过。
- **Priority**: 7（前端，依赖 US-005；可与 US-007 并行）

### US-007: PiecePreviewSVG 命令式渲染
- **Description**: As a 版师，我希望在右侧看到单个裁片的完整还原——毛版实心轮廓、净版绿虚线、内部线橙色、刀口短线段、布纹线红虚线、A/B/C 标注，so that 我能核对母版信息是否被正确解析。
- **Acceptance Criteria**:
  1. 新建 `components/preview/PiecePreviewSVG.tsx`：参考现有 `NestSVG.tsx` 的命令式 SVG 范式（`useRef` + useEffect 直绘 path/circle/text，逃逸 React reconciliation）。
  2. 渲染分层：layer1 毛版轮廓=实心填充半透明蓝 + 实线边；layer14 净版=绿色虚线；layer8 内部线=橙色实线；刀口=沿法线的短线段（US-003 的 notch 模型，**长度暂定 8mm，待版师预览时确认调整**）；layer7 布纹线=红色虚线。
  3. **坐标系翻转 `scale(1,-1)` 必须保留**（与 PNG/R12-DXF 导出口径一致）；**A/B/C 文字标注放在翻转组 `<g>` 之外**（避免镜像），用屏幕坐标计算标注位置。
  4. 多片同框时按各自 bbox 计算 SVG viewBox，保证不重叠或可平移；支持传单片或一组片。
  5. 通过浏览器验证：上传 M1787→选某码→某片，肉眼核对毛版/净版/内部线/刀口短线段/布纹线/A/B/C 标注全部可见且文字未镜像。
  6. `cd materialSorting-web && npm run build` 通过。
- **Priority**: 8（前端，依赖 US-005；可与 US-006 并行）

### US-008: SizeTabs + ParsedPiecesView + PreviewPage 容器 + Tab 打通
- **Description**: As a 版师，我希望在预览页按尺码切换查看该码所有裁片（A/B/C 标注），并与排料页 Tab 打通，so that 我能逐码核对母版。
- **Acceptance Criteria**:
  1. 新建 `components/preview/SizeTabs.tsx`：从 uploadStore.doc 读码数列表（28-38），点击切换 `activeSize`，当前码高亮。
  2. 新建 `components/preview/ParsedPiecesView.tsx`：展示 `activeSize` 下所有裁片（grid 布局，每片一个 PiecePreviewSVG + A/B/C 标注 + 裁片名）。
  3. 新建 `components/preview/PreviewPage.tsx`：左 UploadPanel + 右（SizeTabs + ParsedPiecesView）布局容器，从 uploadStore 订阅状态，未上传时右侧显示空态提示。
  4. 在 `App.tsx` 把 PreviewPage 接入 US-001 的 Tab 容器，与 NestingPage 经 `display:none` 共存。
  5. 通过浏览器验证：上传→SizeTabs 列出各码→切换尺码右侧裁片组随之刷新→每片 A/B/C 与 5 类信息可见；切到排料 Tab 再切回，预览状态（已选码）保留。
  6. `cd materialSorting-web && npm run build` 通过；`vitest` 全 pass（新增/既有用例）。
- **Priority**: 9（前端集成，依赖 US-001/006/007）

### US-009: Vite proxy /api + 文档 layer3 勘误
- **Description**: As a 开发者，我希望 dev 模式下 `/api` 请求经 Vite proxy 转发后端，且旧文档里错误的 layer3 描述被修正，so that 前后端联调通畅、文档与实测一致。
- **Acceptance Criteria**:
  1. `materialSorting-web/vite.config.ts` 的 `server.proxy` 新增 `/api` → `http://127.0.0.1:8000`（`changeOrigin: true`），与现有 `/export`、`/ws` 并列。
  2. 修正 `.docs/business/排料DXF解析架构_方案.md` 第 2 节：删除/更正「layer3=剪口(POINT)」的过时描述，改为 layer4=刀口（POINT+#N 标签，版师 2026-08-10 确认）、layer3=轮廓密点（非刀口）、layer2=未定参考点、layer8=内部线、layer14=净版，并指向 `LAYER_MAPPING` 常量。
  3. dev 模式下 `npm run dev` + 后端 :8000 同启，前端 `fetch('/api/parse-dxf')` 能命中后端（proxy 日志可见转发）。
  4. 文档无残留「layer3=剪口」字样（全文搜索确认）。
  5. `cd materialSorting-web && npm run build` 通过（proxy 配置仅影响 dev server，不破坏 build）。
- **Priority**: 4（web/前端 infra + 文档，无功能依赖，建议早做以解封 dev 联调）

### US-010: 预览结果 → intermediate 转换（后端 · Path A 复用全管线）
- **Description**: As a 系统，我希望有一个后端端点把上传母版转成排料 intermediate（复用现有 `export_dxf` + `load_pieces` 全管线，全码），so that 上传的新母版产物可被排料消费，替代手动 CLI（`ms-export-dxf` + `ms-pieces-export`）。前端 commit 入口随排料页改造补齐（见 AC6 TODO）。
- **Acceptance Criteria**:
  1. 后端新增 `POST /api/commit-to-nesting`，入参 `{doc_id}`（引用 US-004 落盘的 `uploads/<uuid>.dxf`）。**Path A 实现**：服务端跑 `explore.collect_pieces` → `export_dxf.assign_group_no` + `GROUP_NAMES` 定片型 → `write_piece_dxf` 切单裁片到 `paths.OUT_DIR/uploads/<uuid>_pieces/` → `load_nest_pieces(pieces_dir, sizes=母版全码)` → 写回 `paths.INTERMEDIATE`。
  2. **全码**：`load_nest_pieces` 的 sizes 传母版实际全部码号（如 28-38），**不沿用 `DEFAULT_SIZES`**（8 码跳 32）；`export_dxf` 本身不过滤码号（已确认），全码单裁片天然可得。
  3. 片型映射复用 `export_dxf.GROUP_NAMES`（g00→后片…g09→腰，M1787 结构款经 SVG 人工确认；新款需版师重新确认 group→片型）。
  4. 写回前备份原 intermediate 为 `paths.INTERMEDIATE.with_suffix('.bak')`；写回 schema（source/gate_mm/n_pieces/total_area_mm2/pieces）与现有 `ms-pieces-export` 产物一致；`source` 字段改写为上传母版文件名。
  5. NestPiece 仅含 polygon（毛版轮廓 layer1），grain/internal/notch 不进 intermediate（排料只需 polygon）；L/R 镜像由 `load_nest_pieces` 的 `PAIR_TYPES` 处理。
  6. **TODO（v1 不做，随排料页改造一并处理）**：① commit 后排料页自动 reload 机制（`PIECES` 当前是 `server.py` 顶层 `load_pieces()` 内存常量，需新增 reload 端点或重启策略）；② 前端 commit 按钮 + `setTab('nesting')` 跳转 UX。**v1 仅后端 + curl 可测**：`POST /api/commit-to-nesting {doc_id}` 返回新 intermediate 摘要（码数/裁片数/总面积）。
  7. 回归校验：对 M1787 母版，Path A 产物的裁片数/码数与「全码 CLI 管线」（`ms-export-dxf` + `ms-pieces-export` 且 sizes=全码）等价——**注意不是当前 8 码 intermediate**（Q5=全码已改变码数集合）。
  8. `python -c "from materialsorting.web.server import app"` 导入通过；分层依赖未反向（web→nesting_bounds→dxf_parser 单向）；`curl POST /api/commit-to-nesting` 成功写回 intermediate + 生成 `.bak`。
- **Priority**: 10（后端集成，依赖 US-004 落盘的 doc_id；最高复杂度，但 Path A 全复用显著降低风险）

## 功能需求 (Functional Requirements)

- **FR-1**: 上传组件支持点击与拖拽两种方式，仅接受 `.dxf`，单文件。
- **FR-2**: 服务端解析须还原：毛版外轮廓(layer1)、净版(layer14)、内部线(layer8)、布纹线(layer7)、刀口(layer4 POINT+#N)。
- **FR-3**: 解析结果按 block 名末尾数字=码号分组，每码裁片按稳定顺序赋 A/B/C… 标签。
- **FR-4**: 预览按尺码切换，每码展示该码全部裁片。
- **FR-5**: 顶部 Tab 在「排料」「上传预览」间切换，`display:none` 不卸载，状态/WS 保留。
- **FR-6**: 一键 commit 把预览结果转 NestPiece 覆盖 intermediate，跳转排料页。
- **FR-7**: layer 映射集中在后端 `LAYER_MAPPING` 常量，跨款可移植（5156/M1787 已验证一致）。
- **FR-8**: 上传/解析/commit 全程按母版**全码**处理（不裁码、不沿用 `DEFAULT_SIZES` 8 码过滤）。
- **FR-9**: 单文件上传，体积上限 20MB。

## 非目标 (Non-Goals)

- 不做裁片的手动编辑/移动/旋转（排料动作仍在排料页）。
- 不做非母版（单裁片 DXF）上传——上传管线面向多码合一母版；单裁片流程仍走原 `ms-pieces-export`。
- 不引入 CSS 框架（沿用 `style.css`）；不引入新前端依赖。
- 不改动 spyrrow 求解器与 v0.3 约束逻辑。
- 不提取 layer 2/3/13（语义未定/非刀口密点），留待后续。
- 不在本次做上传历史/多文件管理（单文件即用即解析）。
- 不改既有 `/export`、`/ws/solve` 路由与 intermediate schema（US-010 写回须保持 schema 一致）。

## 设计考虑 (Design Considerations)

- **Tab 用 `display:none` 不卸载**：保证切回排料页时求解进度、WS、播放 seek 全部保留——这是选 `display:none` 而非条件渲染/路由卸载的唯一原因。
- **A/B/C 标注在 SVG 翻转组外**：`scale(1,-1)` 翻转组只放几何（轮廓/线/刀口），文字标注单独计算屏幕坐标渲染在翻转组外，否则文字会上下镜像。
- **刀口渲染=沿轮廓法线的短线段**：版师确认刀口是点位（layer4 POINT+#N 标签），按「点 + 所属轮廓边的法向量」画 8mm 短线段最符合版师认知（而非圆点）。
- **颜色口径与既有 SVG 预览探查脚本一致**：毛版蓝、净版绿虚、内部线橙、布纹线红虚、刀口黄（沿用 `scripts/preview/*.svg` 已经版师确认的配色）。
- **左侧 UploadPanel 固定宽、右侧预览自适应**：与现有 ControlPanel 左侧布局风格一致。

## 技术考虑 (Technical Considerations)

- **CPU 解析走 `run_in_executor`**：母版解析（5156 有 21000+ POINT）耗时，必须 `loop.run_in_executor(_executor, parse_fn, path)` 防阻塞 WS 求解事件循环（复用 `server.py` 现有 `ThreadPoolExecutor(max_workers=6)` 模式）。
- **路径一律 `from .. import paths`**：上传落盘 `paths.OUT_DIR/uploads/`、写回 `paths.INTERMEDIATE`，**禁止硬编码 `..` 上溯或绝对路径**（CLAUDE.md 强约束）。
- **R12 POLYLINE 兼容**：母版是 R12/AC1009 + POLYLINE，顶点在 `e.vertices`（非 LWPOLYLINE）；reader/collect 的提取逻辑须走 `polyline_points` 既定口径。
- **GBK 块名解码**：母版块名（如「腰-30」「前片.28」）被 ezdxf 误标 ANSI_1252，须 `decode_str`（latin-1→gbk）还原；码号解析复用 `parse_size`/`_SIZE_RE`。
- **NestPiece 仅含 polygon**：intermediate 是排料-focused 表示（pid/ptype/size/side/polygon/bbox/area），**不含** grain/internal/notch。US-010 转换时这些细节不进 intermediate——它们只服务预览。排料所需仅毛版轮廓 polygon。
- **【US-010 关键事实】片型(ptype)来自单裁片文件名，非 DXF 内部**：`load_nest_pieces` 按 `{ptype}_{size}.dxf` 找文件，ptype 由 `export_dxf.assign_group_no` + `GROUP_NAMES`（g00→后片…g09→腰，经 SVG 人工确认）在导出时赋值。故 US-010 走 **Path A**（服务端跑完整 `export_dxf`：切单裁片 + 定片型 → `load_nest_pieces` 对齐/归一化/镜像），**不能**直接「调 load_pieces 转上传母版」。GROUP_NAMES 为 M1787 结构款映射，新款需版师重新确认。
- **export_dxf 不过滤码号**（已核实源码 `export_dxf.py:82`）：遍历 `collect_pieces` 全部裁片，自然产出全码单裁片，Path A 全码可行，仅需给 `load_nest_pieces` 传 sizes=母版全码覆盖 DEFAULT_SIZES 默认。
- **同名碰撞隐患**：`write_piece_dxf` 输出 `{name}_{size}.dxf`，若母版一码内同片型有多片会「后写覆盖先写」——M1787 结构款假设一码一片型唯一，新款需核对。
- **intermediate 写回需备份**：覆盖 `pieces_intermediate.json` 前先备份原文件（`*.bak`），支持回滚。
- **schema 不变**：写回的 intermediate 字段必须与 `pieces_export` 产物一致，排料页/求解器零改动即可消费。

## 成功指标 (Success Metrics)

- [ ] 上传 M1787 或 5156 母版 → SizeTabs 列出全部码（28-38）→ 切换尺码显示该码所有裁片 → 每片可见毛版/净版/内部线/刀口短线段/布纹线 + A/B/C 标注（文字未镜像）。
- [ ] 排料页发起求解→切到预览页→切回，求解进度与 WS 连接不中断。
- [ ] 上传→预览→commit（v1 走 curl），Path A 产物的裁片数/码数与「全码 CLI 管线」（`ms-export-dxf` + `ms-pieces-export` 且 sizes=全码）等价（回归校验；排料页 reload 随改造补）。
- [ ] `npm run build` 通过、`vitest` 全 pass、后端 `pytest` 全 pass。
- [ ] 新增 layer 映射对 5156 与 M1787 两个生产母版均正确还原（同一 `LAYER_MAPPING` 常量）。
- [ ] 全程无硬编码 `..`/绝对路径（代码搜索 `from .. import paths` 覆盖所有路径访问）。

## 待确认问题 (Open Questions)

> **Q1-Q5 + US-010 机制/范围 已在 PRD 评审中全部闭环**，决议（已写入对应 Story）：
> - **Q1 片型映射** → 方案 A：复用 `export_dxf.GROUP_NAMES`，v1 限定 M1787 结构款。
> - **Q2 排料页 reload** → 延后：US-010 v1 只做后端，reload 机制 + 前端入口随排料页改造补 TODO。
> - **Q3 刀口归属** → 全码：每码刀口按 nearest outline edge 归属，全部保留不裁。
> - **Q4 文件上限** → 20MB（实测生产母版 ~3MB）。
> - **Q5 码数范围** → 全码进 intermediate，不沿用 DEFAULT_SIZES。
> - **US-010 机制** → Path A（复用 `export_dxf` + `load_nest_pieces` 全管线）；**US-010 范围** → v1 后端 only。

仍开放（**非阻塞**，实施中定）：
- **刀口短线段长度**：暂定 8mm，待版师在 US-007 预览时确认/调整。
- **临时单裁片清理**：`uploads/<uuid>_pieces/` 的 ~110 个单裁片文件清理策略（v1 可 commit 后即删或定期清）。
- **同名碰撞核对**：新款母版需确认一码内同片型唯一（见技术考虑同名碰撞隐患）。

## 依赖关系

```
US-002 (P1, dxf_parser 基础)
  └─ US-003 (P2, 深度解析)
       └─ US-004 (P3, /api/parse-dxf · 落盘 doc_id)
            ├─ US-005 (P6, 前端类型/store/hook)
            │    ├─ US-006 (P7, UploadPanel) ─┐
            │    └─ US-007 (P8, PreviewSVG) ──┤
            │                                 ├─ US-008 (P9, PreviewPage 集成) ◀ 前端预览闭环
            │                                 └─ US-001 (P5, Tab 框架, 零后端依赖, 可最先并行)
            └─ US-010 (P10, commit 注入·后端) ◀ 后端 commit 闭环（v1 仅后端, 独立于前端）

US-009 (P4, vite proxy + 文档勘误) —— 独立，建议早做解封 dev 联调
```

- **可并行**：US-001（前端 Tab 框架）与 US-002~004（后端解析）无依赖，可同时启动。
- **可并行**：US-006 与 US-007 均只依赖 US-005 的类型/store。
- **两条闭环独立**：前端预览闭环（002→003→004→005→008）；后端 commit 闭环（004→010）。US-010 不再阻塞前端。
- **US-010 已去风险**：Q1/Q2 拍板 + Path A 全复用后，US-010 降为纯后端复用 Story。
