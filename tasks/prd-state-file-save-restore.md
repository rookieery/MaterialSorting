# PRD: 排料工作台运行状态文件保存/恢复（.msn）

> 设计依据（已定稿，含行号级证据与全部拍板记录）：[.docs/business/状态文件保存恢复_落地方案.md](../.docs/business/状态文件保存恢复_落地方案.md)
> 后端根 = `materialSorting-server/src/materialsorting/`，前端根 = `materialSorting-web/src/`。

## 概述 (Overview)

版师把「上传预览 + 超排」两 Tab 的完整运行状态（裁片轮廓/数量矩阵/高级配置/求解结果/编辑结果/策略来源）保存为一个可传递的 `.msn` 文件（版本化 JSON + gzip），自己或他人上传该文件即一键还原为**完整可用的工作台**（可继续查看、编辑、重新求解、导出、接力再保存）。参考 ET 软件 .pla 的用途，但不造闭源二进制格式。

## 目标 (Goals)

- 5336 量级（110 片）状态文件 gzip 后 ≤ 300KB（估 ~150KB），恢复后两 Tab + 编辑 + 重解 + 导出全链路可用
- `.msn` 链式传递无限代（A 恢复→改→存→B 恢复→…），逐字段 round-trip 零漂移
- placed 副本守恒（=Σdemand）在保存、恢复校验、导出三处成立
- 既有 pytest + vitest 全量零回归，tsc/build 干净

## 用户故事 (User Stories)

### US-001: 状态文件序列化模块 + 保存端点（后端）
- **Description**: As a 版师, I want 把当前工作台状态存成 .msn 文件 so that 工作可以传递到其他机器。涉及 `web/statefile.py`（新：常量/build_state_document/serialize_state/校验函数/`__main__` 自检）+ `web/server.py` 注册 + `web/runtime.py` 提取 `_state_from_doc`。
- **Acceptance Criteria**:
  1. `POST /api/state-save` 带合法 sid + JSON body `{form, quantities, run?}` 返回 200 附件（gzip JSON，Content-Disposition 中文/ASCII 双名，扩展名 .msn，文件名 `<母版名去.dxf>_状态_<yyyymmdd-HHMMSS>.msn`）。
  2. 响应体 gunzip 后顶层含 schema_version=1/doc/form/quantities；doc.pieces 与会话 intermediate 逐字段一致（含 5 层）；body 无 run 时文件无 run 键。
  3. **保存期守恒校验**：body 带 run 时 placed pid 全命中会话 pieces 且 `Counter(placed) == demand(form.sizes × quantities)`，违者 400「数量矩阵/尺码选择与当前结果不一致，请先重新求解或改回数量再保存」（与恢复期终检同一校验函数）。
  4. sid 过期/非法 → 401/400 结构化 JSON（非文件流）；会话空（无 doc）→ 422。
  5. pytest 新增往返/空态/401/保存期不守恒用例全绿，既有 pytest 全量通过。
  6. `python -m materialsorting.web.statefile` 合成夹具自检（build→serialize→parse round-trip）跑通、分层依赖未反向（web 层模块，无兄弟层反向 import）。
- **Priority**: 1

### US-002: 恢复端点 + 会话重建 + manifest 重算（后端）
- **Description**: As a 版师, I want 上传 .msn 恢复完整会话 so that 另一台机器能继续我的工作。涉及 `web/statefile.py` restore handler（复用 `parse_payload._build_parse_payload`、`solver.build_pid_meta`、`sessions.registry`、`edit_hold.refresh`）。
- **Acceptance Criteria**:
  1. `POST /api/state-restore` multipart .msn → 200 `{doc_id, filename, parse, manifest, final, placed, form, quantities}`；manifest 与原解 manifest 逐字段一致（同 form 经 `build_pid_meta` 确定性重算，含 raw_polygon/d_mm 物理毛版口径）。
  2. 校验链全 fail-fast：坏 gzip/坏 JSON → 400「状态文件损坏」；>20MB → 413；schema_version 缺失/非 int/过新 → 400 文案含双版本号；doc 块逐片形态（polygon ≥3 顶点且数值有限）；placed pid 越界 → 400；副本数 ≠ demand → 400；provenance.kind 非法枚举 → 400；解析在 threadpool 执行不阻塞事件循环。
  3. 恢复写入当前 sid 会话（`resolve(create=True)`，等价再 commit 的覆盖语义，不占 MS_SESSION_MAX 名额）；doc_id 铸新 uuid；**纯内存重建**：default 会话恢复后 `out/sparrow_baseline/pieces_intermediate.json` 与 `out/uploads/` 字节不变（pytest 断言不落盘）。
  4. 恢复后该 sid 的 `/api/ptypes`、`/export`、`/api/edit-polish` 立即可用（pytest 端到端断言 placed 守恒）；成功响应顺手 `edit_hold.refresh(sid)`。
  5. gzip/纯 JSON 双嗅探均接受；既有 pytest 全量通过。
  6. `python -m materialsorting.web.statefile` 自检含 restore 路径、分层依赖未反向。
- **Priority**: 2

### US-003: 前端 formStore 重构 + 导出弹窗「状态文件」分支 + 上传分流（前端）
- **Description**: As a 版师, I want 在导出下拉里选「状态文件」一键保存工作台、在上传控件直接选 .msn 恢复 so that 操作复用既有习惯路径。涉及 `store/formStore.ts`（新）、`components/ControlPanel/ControlPanel.tsx`（局部 state 迁移 + handleExport 分支）、`lib/download.ts`（EXPORT_FORMATS/ExportFmt 扩项 + 注释例外标注）、`hooks/useExport.ts`（saveState 方法）、`components/ControlPanel/ExportButtons.tsx`（说明行文案分支）、`hooks/useParseDxf.ts`（扩展名分流）、`lib/stateFile.ts`（buildSavePayload）、`types/stateFile.ts`（契约类型）。
- **Acceptance Criteria**:
  1. ControlPanel 表单行为（含 docId 变更重置 DEFAULT_FORM）与重构前一致——既有 vitest 全绿 + 手动回归。
  2. 格式下拉含「状态文件（.msn）」排 PNG 后、默认值不动（仍 'plt-clean'）；选中时**不弹** ExportInfoModal，底部说明行切换为「保存母版快照+全部配置+当前最优方案（含编辑），可在其他电脑恢复继续；不含导出表格手输字段（本机记忆）」。
  3. 有 lastFrame 时点「导出」POST /api/state-save（body=buildSavePayload：form ← formStore、quantities ← qtyStore、run ← bestRun() 仅 done、mirror 按 omit-when-false、origin 映射 provenance）下载 .msn；求解中/无 lastFrame 导出按钮 disabled 与其他格式同口径（共用 hasLastFrame + exporting 防连击）；StatusLine 显示生成/完成/失败文案；`parseContentDisposition` fallback 扩展名 'state' 映射 .msn。
  4. 上传控件 accept 增 .msn、文案「上传母版 (.dxf) 或状态文件 (.msn)」；选 .dxf 走原 parse/commit 路径零变化；选 .msn POST /api/state-restore（走 lib/api.ts apiFetch，不经 parse-dxf）。
  5. 通过浏览器验证导出弹窗格式分支与上传分流交互（含 .dxf 原路径回归）。
  6. `npm run build` 无错误、vitest 全量通过。
- **Priority**: 3

### US-004: 恢复编排 + 端到端冒烟（前端 + 联调）
- **Description**: As a 版师, I want 恢复后两个 Tab 与编辑能力无缝可用 so that 接着上次的活干。涉及 `lib/stateFile.ts` applyRestorePayload、`components/NestingPage.tsx` 抽取 `applySyntheticRun`（自 applyStrategyResult :211-272 核心）+ `run-provenance` 来源小字、`RunRecord` additive `origin?` 字段、`scripts/smoke_state_file.mjs`（新）。
- **Acceptance Criteria**:
  1. 恢复后：uploadStore doc 就绪 → 预览 Tab 片列表/数量矩阵（qtyStore.hydrate）与保存时一致；formStore.hydrate(token=新 docId) 表单字段（sizes/gate/time/seed/per_type/band/prefix）一致；ptypeStore 失效标记（commit-done 口径）；有 run 块时 activeTab 切超排。
  2. run 合成：`applySyntheticRun(manifest, frameLike, seed)` 产 RunRecord done 态（placed_items 原序深拷贝含 mirror，phase='final' 单帧）+ origin 写回；超排 Tab 布局 DOM 片数 = placed 条数、密度/料长/seed 回显、`run-provenance` 小字正确（data-testid=`run-provenance`，如「来源：极限运行(600s) · seed 0」）；普通求解不设 origin（缺省 'solve' 不写 provenance 键）。
  3. 恢复后打开编辑弹窗基线 = 恢复布局（拖动一片保存 → 指标联动既有逻辑）；`bestRun()` 可导出（/export 成功）；重解一次得到新 final（既有 WS 链路零回归）。
  4. `smoke_state_file.mjs` 全绿（沿用 smoke_*.mjs 套路：Edge 通道 + addInitScript 防 tour 拦截）：上传 5336 → 短时求解 → 编辑一片保存 → 导出下拉选「状态文件」下载 .msn → **全新 context（新 sid）**上传 .msn → 断言预览/表单/布局/密度/provenance/编辑弹窗已编辑态 → 导出 PLT 后端 placed 守恒对拍 → 恢复后重解正常 final。
  5. 文档同步：agent-api-reference.md 增 /api/state-save、/api/state-restore 专节（含「端点容忍无 run 但 UI 不可达」注记）、web/AGENTS.md 路由清单 + .msn 说明、根 CLAUDE.md web 段一句。
  6. `npm run build`、pytest、vitest 全量通过。
- **Priority**: 4

### US-005: CLI intermediate 入口 + 恢复会话策略/极限重跑（后端）
- **Description**: As a 版师, I want 在恢复的会话上直接重新发起策略/极限运行 so that 不必重传母版也能继续算法调优。涉及 `cli/config.py`（第 10 键 intermediate，与 master_dxf 二选一）、`cli/pipeline.py`（commit_from_config 短路分支）、`web/strategy.py`（start 时母版缺盘但会话有 doc → 落 doc 到 run_dir 产物区、config 写 intermediate 键）。
- **Acceptance Criteria**:
  1. config 带 `intermediate`（无 master_dxf）跑通策略/极限全管线，run_dir 产物结构与 master_dxf 路径同构（result.json/strategy.json/best_frame 等）；master_dxf 与 intermediate 都给或都不给 → ConfigError（消息含两键名）；intermediate 相对路径解析同 master_dxf 双候选口径。
  2. `commit_from_config` 短路：跳过 `collect_pieces_with_details` parse/切片，把源 intermediate 校验后落 `run_dir/pieces_intermediate.json`；commit 摘要 source 取 doc.source；solve/LNS 段零改动（本就读 run_dir intermediate）；`pieces/` 目录下游消费面实施期核验，无消费者则不生成。
  3. 恢复会话（无 `out/uploads/<doc_id>.dxf`）经 `/api/strategy/start`（及 /api/extreme/start）发起 run → 200 正常执行至 done、结果可应用回主画布；正常 commit 会话（有母版在盘）路径零回归（仍走 master_dxf）；run_stats.jsonl 的 class_key 口径与母版路径跑法一致（source 字符串同源）。
  4. pytest：手写 intermediate config 短路用例、恢复会话发起策略 run 端到端、双键冲突/双缺 ConfigError、既有 CLI/策略用例零回归。
  5. `ms-run-config` 带 intermediate 配置可跑通（`python -m materialsorting.cli.run_config` 链路）、分层依赖未反向。
- **Priority**: 5

## 功能需求 (Functional Requirements)

- FR-1: `.msn` 文件 = 版本化 JSON（顶层 `schema_version=1`）+ gzip 恒开 + 自定义扩展名；恢复端按 gzip 魔数 `1f 8b` 嗅探、纯 JSON 也接受；四块结构 doc/form/quantities/run（run 缺席 = 纯配置档）。
- FR-2: `POST /api/state-save`：doc 块取后端会话 state 原样、form/quantities/run 由前端回传；保存期守恒校验 fail-fast；文件名 `<母版名>_状态_<时间戳>.msn`。
- FR-3: `POST /api/state-restore`：multipart 上传 → 校验链（魔数/20MB 上限/JSON 容错/版本门/逐片形态/pid 全匹配/副本守恒/provenance 枚举）→ 纯内存重建会话写当前 sid → 返回 parse+manifest+final+placed+form+quantities 组合载荷。
- FR-4: manifest 不入文件，恢复期 `build_pid_meta` 确定性重算（含 raw_polygon/d_mm 物理毛版口径），文件只存一份几何。
- FR-5: 上传控件按扩展名分流：`.msn` → state-restore、`.dxf` → 原 parse/commit 路径零变化。
- FR-6: ControlPanel 表单迁 Zustand formStore（hydrate/resetForDoc），恢复注表单与保存读表单的共同地基。
- FR-7: 导出弹窗格式下拉新增「状态文件（.msn）」：不弹 ExportInfoModal、说明行切换保存范围提示、与 PNG/DXF/PLT 共用 exporting 防连击与 StatusLine、沿用 hasLastFrame disabled 联动。
- FR-8: 恢复编排 applyRestorePayload + applySyntheticRun：两 Tab 填充 + run 合成 done 态 + 编辑基线重锚至恢复布局。
- FR-9: provenance 来源链：RunRecord additive `origin?:{kind,config?}`（solve/strategy_se/strategy_race/extreme 四值），applyStrategyResult 记入、恢复写回、结果区常驻小字展示。
- FR-10: CLI 第 10 键 `intermediate` + commit 短路 + strategy start 分支：恢复会话无需母版即可重跑策略/极限。
- FR-11: 链式传递：restore 产物可再 save，无限代 round-trip；恢复后重解（改数量/码选）→ 新结果可导出/可再保存。

## 非目标 (Non-Goals)

- 不内嵌原始母版 DXF（仅 doc.source 文件名备查）；恢复会话上策略/极限重跑经 US-005 打通，但重新 parse 母版仍需重传
- 不保存帧历史/回放轨迹、编辑撤销栈（下标 diff 脱离基线无意义，恢复后 open 重锚基线）
- 不迁移策略/极限 run_dir、轮询状态机、逐 seed 历史（只存最终采纳结果 + provenance；strategyStore 伪造 done 态会被无状态 refresh 打回 idle，架构上不做）
- 不保存导出表格 6 手输字段（操作者本机 localStorage 属性，跨机不泄漏）
- 不做跨大版本永久兼容（版本门 fail-fast + 破坏性变更时就地迁移函数）
- 不做恢复会话与现有会话的「合并」（仅覆盖语义 + v1 轻量确认弹窗）
- 「纯配置档」（无 run）不提供 UI 入口（端点层容忍，契约差写进 API 文档）

## 设计考虑 (Design Considerations)

- 保存入口 = 导出弹窗格式下拉（与 PLT/PNG/DXF 并列），复用用户既有习惯路径；不设顶栏按钮
- 恢复入口 = 上传控件同入口分流（拖拽/点击直觉一致），文案「上传母版 (.dxf) 或状态文件 (.msn)」
- 来源小字 `run-provenance` 常驻结果区（非 StatusLine 瞬态文案），data-testid 供冒烟断言
- 选中「状态文件」时 ExportInfoModal（14 字段表格）根本不打开——对状态文件无意义，由底部说明行替代说明保存范围
- 恢复写入当前 sid 前若检测到已有 doc，弹轻量确认（v1 不做合并）

## 技术考虑 (Technical Considerations)

- **混合取数结构是代码必然**：几何真相在后端会话（state['doc']，前端无全量轮廓）、配置与编辑结果真相在前端（随 WS start 下发/lastFrame）——保存 = 后端聚合 doc + 前端回传 form/quantities/run
- **恢复会话等价性已实证**：/export 走会话内存态 pieces_by_id（routes_views.py:359/369）、solve_worker 几何经 pickle 传参 pieces_snapshot 不读盘（solve_worker.py:51-58）——纯内存会话对导出/重解均等价正常 commit 会话
- **placed 多副本不变量**：同 pid N 条数组项，绝不 pid 去重；mirror 按 omit-when-false（editStore.ts:132-139 同口径）；save 深拷贝原序、restore 原序回填、守恒终检三道锁
- **密度口径**：run.final.density 为 real 口径 `total_area/(width×gate)`（solver._apply_density_dual 单一换算点）；恢复展示用存值，编辑后前端 computeLayoutStats 同口径重算（raw 物理口径包络）
- **安全**：恢复解析视为不可信输入——20MB 上限、深嵌套 RecursionError 捕获为 400、threadpool 解析、fail-fast 结构化 JSON 错误（复用 edit-polish 语义）
- **版本策略**：老系统读新文件 → 400 带双版本号不猜测；新系统读老文件 → v1 内未知键忽略、可选块缺席容忍；破坏性变更 bump schema_version + 迁移函数
- **web/statefile.py 分层**：web 层新模块（strategy.py 同模式路由注册），不引入兄弟层反向依赖

## 成功指标 (Success Metrics)

- [ ] 5336 规模：保存产出 ~150KB .msn，另一机器（全新浏览器会话）上传后两 Tab + 编辑 + 重解 + 导出全链路可用
- [ ] 链式传递 round-trip（A 恢复→改→存→B 恢复）pytest 逐字段对拍全等
- [ ] placed 副本守恒（=Σdemand）在保存、恢复校验、导出三处成立
- [ ] 恶意/损坏/过新版本文件全部结构化 400/413，不崩服务
- [ ] 恢复会话上策略/极限 run 无需母版正常执行至 done（US-005）
- [ ] 既有 pytest + vitest 全量零回归，tsc/build 干净

## 待确认问题 (Open Questions)

- 恢复覆盖当前会话的确认弹窗触发粒度：每次恢复都确认，还是仅当前会话已有 doc 时确认？（v1 倾向后者）
- `.msn` 扩展名命名是否满意（可实施期改，如 .msjob/.msstate）
- provenance 小字文案格式（当前定「来源：极限运行(600s) · seed 0」样式，实施期可微调）
