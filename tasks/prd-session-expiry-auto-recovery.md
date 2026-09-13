# PRD: 会话过期自动恢复（服务端 checkpoint，刷新触发）

## 概述 (Overview)

多会话工作台的 10 分钟空闲过期目前是「阻断弹窗 + 强制刷新 + 全部数据丢失」的最差体验：后端会话 doc（5 层几何）与前端 form/quantities/run（含排料布局）两半同时死亡。本功能复用刚落地的状态文件管线（`web/statefile.py` 的 build/serialize/parse/守恒校验 + 前端 `applyRestorePayload` 全量重建编排），新增**服务端内存 checkpoint**：工作台状态变更时自动打快照（peek 口径不刷活性），**会话过期后用户刷新页面时**在启动期恢复到过期前状态；无 checkpoint 可恢复时静默开新会话 + toast。**恢复只由用户刷新触发，页面停留期间绝不自动恢复**——自动恢复会变相保活会话、浪费资源，违背空闲回收语义（用户定案）。求解/编辑/策略长跑由既有钉住机制（WS pin / edit_hold / alive hook）保证不触发过期，不在本功能范围。

## 目标 (Goals)

- 会话过期（10 分钟空闲）后，**用户点击刷新（F5 / 弹窗刷新按钮）即回到过期前工作状态**：母版 doc + 数量矩阵 + 表单 + 求解结果布局（run done 态）全部恢复——无需重新上传母版、重配数量、重求解。
- 页面停留期间（过期后不刷新）不自动恢复、不自动新建会话：401 只弹「引导刷新」弹窗（文案承诺刷新后恢复），空闲回收与 `MS_SESSION_MAX` 容量回收语义零影响。
- 无 checkpoint 可恢复（从未上传过 / 快照超 TTL / 服务重启丢内存）时，兜底为刷新后**静默开新会话 + toast**。
- F5（会话存活时）行为不变 = 干净重置；429 session_limit 弹窗保留。

## 用户故事 (User Stories)

### US-001: 后端 checkpoint 内存存储 + 写入/清除端点 + 重建段抽取
- **Description**: As a 排料工程师, I want 服务端按 sid 维护一份工作台状态的内存快照（复用 .msn 序列化管线），so that 会话过期后状态有恢复来源；同时把 `statefile.state_restore` 内联的会话重建段（statefile.py:565-611）抽取为共享函数供恢复端点复用（行为零变更重构）。
- **Acceptance Criteria**:
  1. 新模块 `materialSorting-server/src/materialsorting/web/checkpoint.py`：`_CheckpointStore`（`OrderedDict[sid → {data: gzip bytes, ts}]` + `threading.Lock` + 惰性 TTL 清理 + FIFO 容量上限；时钟可注入测试）；env `MS_CHECKPOINT_TTL_SEC`（缺省 7200，对齐恢复窗 = 墓碑 1h + 会话 TTL 10min + 余量——超窗 checkpoint 无消费方，纯内存浪费）/ `MS_CHECKPOINT_MAX`（缺省 16），`_env_int/_env_float` 容错回退（sessions.py 同款）。
  2. `POST /api/state-checkpoint`（`X-Session-Id`；body = state-save 同形 `{form, quantities, quantities_base?, run?}`，`save_as` 键容忍忽略）：经 `registry.peek(sid)` 读会话快照（**绝不 resolve —— 不刷 last_active、不建会话**，注入假时钟断言 peek 后 `last_active` 不变）；会话空（无 doc/pieces）→ `200 {stored:false, reason:'empty'}`；run 守恒校验失败（`check_placed_conservation` 复用）→ `200 {stored:false, reason:'conservation'}` 且**先前好快照字节不变**（last-good）；成功 → `build_state_document + serialize_state` 入库 → `200 {stored:true}`。
  3. `DELETE /api/state-checkpoint`（同 sid）：幂等清除（条目不存在也 200 `{ok:true}`）。
  4. `statefile.py` 抽取共享重建函数（如 `rebuild_session_from_document(document, sid, *, filename_fallback='') -> dict`：doc_id 铸新 + `_state_from_doc` + sid/default 双分支写入 + `build_pid_meta` manifest 重算（`_form_gate_mm` 口径）+ `_DocPieceView` parse 载荷 + `edit_hold.refresh` + 响应组装）；`state_restore` 改调它，既有 `tests/test_web_statefile.py` 全绿 + 成功响应逐字段对拍零变更。
  5. `register_checkpoint_routes(app)` 于 server.py 文件尾注册（statefile/strategy 同模式）；模块禁 import server（AST 守卫进 `tests/test_web_checkpoint.py`）；`tests/test_web_checkpoint.py` 覆盖：写入/empty/conservation last-good/TTL 惰性清理/FIFO 逐出/DELETE 幂等/peek 不刷活性/不建会话名额。
  6. Python 模块可通过 `python -m materialsorting.web.checkpoint` 跑通（合成夹具自检：写入→读回 gunzip 对拍 + 生命周期全路径）、分层依赖未反向。
- **Priority**: 1

### US-002: 后端恢复端点 POST /api/state-recover
- **Description**: As a 排料工程师, I want 刷新后启动期用新 sid + 旧 sid 引用把 checkpoint 恢复成当前会话，so that 前端一次请求拿到与 `/api/state-restore` 同形的响应、直接复用 `applyRestorePayload` 全量重建 UI。
- **Acceptance Criteria**:
  1. `POST /api/state-recover`：`X-Session-Id` = **新 sid**（前端铸新后携带）；body `{from_sid: 旧sid}`；`from_sid` 过 `SID_RE` 校验（非法 400）。
  2. checkpoint 不在 / 超 TTL → `404 {code:'checkpoint_not_found', error:...}` 结构化 JSON（前端据此走静默兜底）；**解析在会话 resolve 之前**（`run_in_threadpool(parse_state_document)`，坏数据不占名额，state_restore 同序）；校验链失败 → 400/413 同 state_restore 契约。
  3. `registry.resolve(new_sid, create=True)`（commit 先例）；429 session_limit 结构化透传（前端回退阻断弹窗）；成功走 US-001 共享重建函数 + `edit_hold.refresh(new_sid)`，响应 = state-restore 成功响应同形（`{doc_id, filename, parse, manifest, final, placed, run, quantities_base, form, quantities}`）+ additive `recovered_from: from_sid` 键（冒烟断言锚点）。
  4. 恢复成功即删该 checkpoint 条目（single-use：旧 sid 已入墓碑永不复用，删除防多 Tab 反复恢复放大名额占用）。
  5. pytest 全链（TestClient）：真实 commit 会话 → checkpoint → 会话过期逐出 → 新 sid recover → 新会话 pieces/manifest 与快照逐字段一致 + 守恒通过 + `recovered_from` 回显 + checkpoint 已删；404 / 429 / 坏 from_sid / 双次恢复（第二次 404）四路。
  6. Python 模块可通过 `python -m materialsorting.web.checkpoint` 跑通、分层依赖未反向。
- **Priority**: 2

### US-003: 前端启动期恢复（刷新触发）+ 停留期引导刷新弹窗
- **Description**: As a 排料工程师, I want 会话过期后刷新页面时，启动探测走恢复流程回到过期前状态；过期后不刷新只交互时，弹窗告诉我「刷新后将恢复」，so that 恢复由我主动触发，页面停留期间不自动恢复、不自动新建会话、不浪费资源。
- **Acceptance Criteria**:
  1. 启动期恢复（挂接 `ensureSession` once-probe / App `probeSession` 的 401 分支，天然 single-flight）：401 session_expired → 捕获旧 sid（session.ts 需**非铸造读取**——现 `getSessionId` 会 lazy mint，须加只读 localStorage 的辅助）→ `clearPersistedSessionId()` → 铸新 sid → **裸 fetch** POST `/api/state-recover` `{from_sid}`（ensureSession 先例，绕 apiFetch 防递归）。
  2. recover 200：`applyRestorePayload(res)`（stateFile.ts 既有编排零改动）+ toast「工作状态已恢复」→ 用新 sid 重试 probe（200）→ ensureSession 放行，原请求带新 sid 正常发出（请求在 probe 门后从未发出，**无需重放机制**）。
  3. recover 404 / 网络失败：静默（新会话已就绪）+ toast「上次会话已过期，已开启新会话」→ probe 重试放行；recover 429：既有阻断弹窗（文案不变）。
  4. **停留期 401（apiFetch / useSolveRun WS error 帧 code=session_expired）：不自动恢复、不再 `clearPersistedSessionId()`**（旧 sid 留给刷新后启动期恢复作 from_sid）→ 阻断弹窗保留但文案改为「会话已过期，刷新页面后将恢复工作状态」（按钮 `location.reload()` 不变）；session_limit 分支文案与保 sid 语义不变。
  5. 启动恢复期间「正在恢复工作状态…」轻加载态（恢复 <2s，防空白闪屏）；恢复成功后新 sid 正常进入自动 checkpoint 调度。
  6. `npm run build` 通过 + vitest 全绿：启动 401 三分支（200 恢复 / 404 兜底 / 429 弹窗）/ 旧 sid 非铸造捕获时序 / 停留期不清 sid / 弹窗文案分流 / once-probe 并发收敛。
- **Priority**: 3

### US-004: 前端自动 checkpoint 调度 + 启动清理
- **Description**: As a 排料工程师, I want 前端在工作台状态变更时自动打 checkpoint（无需手动保存），so that 过期时刻的快照足够新（丢失窗口 ≤ 去抖时长）；会话存活时 F5 仍是干净重置。
- **Acceptance Criteria**:
  1. 自动触发点：`formStore`/`qtyStore` 变更订阅 + `runRegistry` bestRun 达 done（求解完成即立即 checkpoint——价值最高时刻）+ `editStore.save`（编辑保存后），统一经 `buildSavePayload()`（不带 save_as）POST `/api/state-checkpoint`，去抖 ~3s（常量可调）；`visibilitychange → hidden` 立即 flush 清空去抖；`pagehide` best-effort（keepalive fetch）。
  2. 未 commit（无 doc）时调度静默跳过（后端 empty 响应容忍，不报错不重试风暴）；调度请求一律走 peek 口径端点，**不刷新会话活性**。
  3. App 启动 `probeSession` 探测会话**存活** → `DELETE /api/state-checkpoint`（F5 = 干净重置：旧 checkpoint 不残留，防「稍后再过期恢复出 F5 前旧状态」的幽灵回潮）；探测 401 则不清（留给启动期恢复流程消费）。
  4. 通过浏览器验证：上传母版 → 改数量 → 触发 checkpoint（网络面板断言 POST 200 stored:true）→ F5 刷新 → 断言页面干净重置 + DELETE 已发 → 数量矩阵为默认值（非恢复态）。
  5. `npm run build` 通过 + vitest 全绿（去抖合并多次变更 / hidden 立即 flush / doc 空跳过 / 存活清理时序）。
- **Priority**: 4

### US-005: 端到端集成验收 + 文档闭环
- **Description**: As a 项目维护者, I want UI 冒烟脚本覆盖「过期 → 刷新 → 启动期恢复」全链路并把三端点契约/环境变量写入文档，so that 回归有守卫、运维可查。
- **Acceptance Criteria**:
  1. 冒烟脚本 `materialSorting-web/scripts/smoke_session_recovery.mjs`（playwright 套路同 smoke_state_file.mjs）：极短 `MS_SESSION_TTL_SEC` env 起 dev → 上传母版 → 改数量矩阵 → 短求解 done → 等 TTL 过期 → **停留期交互路径**：触发任一 API 请求 → 断言引导刷新弹窗（新文案）且未自动恢复 → 点弹窗刷新按钮 → 启动期恢复 → 数量矩阵/表单/布局与过期前对拍 + toast 在场。
  2. 冒烟续段：**直接 F5 路径**（过期后 page.reload() → 无弹窗直接恢复）；**F5 存活清理路径**（未过期刷新 → 干净重置 + checkpoint DELETE）；**无 checkpoint 兜底路径**（DELETE 后再过期 → 刷新 → 静默新会话 + toast、无弹窗）；429 路径弹窗仍在（可借 MS_SESSION_MAX=1 双客户端模拟，允许标记 skip-if-flaky）。
  3. 文档：`.docs/technical/agent-api-reference.md` 增 `POST /api/state-checkpoint` / `DELETE /api/state-checkpoint` / `POST /api/state-recover` 专节（错误码表 + 生命周期语义 + 与 state-save/restore 的复用关系 + 恢复窗口 = 过期后墓碑 1h 内说明）；README「多会话机制」+ `web/AGENTS.md` 补 `MS_CHECKPOINT_TTL_SEC`/`MS_CHECKPOINT_MAX` 环境变量；`agent-file-map.md` 补 checkpoint.py 行。
  4. 全量回归：后端 pytest 全绿（含既有 statefile/sessions/edit_hold 用例零回归）、前端 vitest 全绿、`npm run build` 通过。
  5. Python 模块可通过 `python -m materialsorting.web.checkpoint` 跑通、分层依赖未反向。
- **Priority**: 5

## 功能需求 (Functional Requirements)

- FR-1: checkpoint 写入端点经 `peek` 读会话，**不刷新 last_active、不建会话名额**——否则常开 Tab 永不过期，破坏 MS_SESSION_MAX 容量回收。
- FR-2: last-good 语义：自动 checkpoint 守恒校验失败（如改数量未重解的中间态）不覆盖上一份好快照，返回 `stored:false` 而非报错（自动后台任务不打扰用户）。
- FR-3: **恢复仅发生在页面启动期、由用户刷新触发**；停留期间 401 只弹引导刷新弹窗，绝不自动恢复、不自动新建会话、不发请求风暴（用户定案：自动恢复变相保活会话、浪费资源）。
- FR-4: 恢复响应与 `/api/state-restore` 成功响应同形（+additive `recovered_from`），前端 `applyRestorePayload` 零改动直接消费。
- FR-5: 无 checkpoint 可恢复（从未上传 / 超 TTL / 服务重启）→ 刷新后静默开新会话 + toast；不再出现「强制刷新 = 全部丢失」的旧体验。
- FR-6: 429 session_limit 保留现有阻断弹窗与「保 sid」语义。
- FR-7: 启动探测会话存活 → DELETE checkpoint：F5 = 干净重置（用户拍板：会话存活时刷新不恢复）。
- FR-8: 自动 checkpoint 触发点 = store 变更去抖 ~3s + visibilitychange hidden 立即 + run done 立即 + pagehide best-effort。
- FR-9: checkpoint 生命周期参数 env 可调：`MS_CHECKPOINT_TTL_SEC`（缺省 7200——对齐恢复窗：过期后墓碑 1h + 会话 TTL 10min + 余量，超窗无消费方）/ `MS_CHECKPOINT_MAX`（缺省 16，FIFO）。
- FR-10: 全部新端点错误响应为结构化 JSON（404/429 带 `code`），路由 fail-fast 先于业务逻辑。
- FR-11: 恢复成功即删 checkpoint（single-use）；恢复用新 sid（旧 sid 墓碑 1h 拒绝重建，必须在清 sid 前捕获）。
- FR-12: checkpoint 纯内存不落盘（服务重启 = 丢快照 = FR-5 兜底路径，可接受）；单条 ≈ gzip 后 100–200KB，16 条上限 ≈ 3MB 内存，可忽略。
- FR-13: 停留期 session_expired **不清除 `ms_sid`**（留给刷新后启动期恢复作 from_sid）；恢复窗口 = 过期后墓碑 1h 内，超窗刷新走 probe 200 新会话 = 干净重置（与现状一致的优雅降级，文档注明）。

## 非目标 (Non-Goals)

- **页面停留期间的自动恢复（401 即恢复 + 原请求重放）**——用户定案：恢复仅由用户刷新触发，自动恢复会变相保活会话、浪费资源。
- 手动 F5（会话存活时）恢复旧状态——用户明确拍板 F5 = 干净重置。
- 浏览器侧快照（IndexedDB/localStorage）——服务端内存单一真相源。
- 求解中 / 编辑中 / 策略运行中的过期恢复——既有钉住机制（WS pin / edit_hold 2h / alive hook + 终态宽限窗）保证这些场景不触发过期。
- 多 Tab 同 sid 的恢复协调（BroadcastChannel 等）——non-goal，多 Tab 各自刷新恢复或走兜底。
- checkpoint 落盘持久化（跨服务重启保快照）。
- 429 场景的自动重试 / 排队机制。
- WS error 帧恢复后的自动重连续跑求解（刷新恢复后停在结果态，用户重新发起）。

## 设计考虑 (Design Considerations)

- 停留期引导刷新弹窗：沿用现有 `SessionExpiredModal` 阻断式（会话已死、请求全 401，阻断合理），文案从「请刷新页面（数据丢失暗示）」改为「刷新页面后将恢复工作状态」——给用户恢复预期；按钮仍 `location.reload()`。
- 启动恢复期间轻加载态（「正在恢复工作状态…」，<2s）；恢复成功 toast「工作状态已恢复」/ 兜底 toast「上次会话已过期，已开启新会话」——沿用前端既有 toast/提示机制，若无则新增 uiStore 轻 toast（不引组件库）。
- 恢复后留在超排 Tab（applyRestorePayload 有 run 时 `setTab('nesting')` 既有行为）；纯配置档（无 run）留在预览页——与 .msn 恢复一致。
- 恢复窗口边界（墓碑 1h）在弹窗/文档中不做显式倒计时——超窗刷新 = 干净重置已是现状体验，无新伤害。

## 技术考虑 (Technical Considerations)

- **分层**：`web/checkpoint.py` 为 web 层兄弟模块，仅 import `statefile`（共享重建函数）/`sessions`/`edit_hold`，禁 import server（AST 守卫，sessions.py 同款先例）；`register_checkpoint_routes(app)` server.py 文件尾注册。
- **peek vs resolve**：checkpoint 读会话必须 `peek`（不抛不过期检查不刷活性）；recover 建新会话用 `resolve(create=True)`（commit 先例，合法未注册 sid 可直接建）。
- **解析先于会话 resolve**：recover 与 state_restore 同序——坏 checkpoint 不新建会话名额。
- **前端裸 fetch**：恢复请求必须绕过 `apiFetch`（否则 probe 401 → 恢复 → apiFetch 递归）；`ensureSession` 已有裸 fetch 先例。
- **旧 sid 捕获时序**：启动期须**非铸造读取** localStorage `ms_sid`（现 `getSessionId` lazy mint 会直接铸新丢旧值）→ 再 clear → 再铸新；停留期 401 分支**不清 sid**（FR-13，与现行 `triggerSessionBlock` 清 sid 行为相反——本次改造点）。
- **single-flight 落点**：恢复逻辑嵌在 `ensureSession` once-promise 的 401 分支内，天然单飞；App `probeSession` 与 apiFetch 首请求共享同一 probe，无并发双跑。
- **守恒复用**：checkpoint 写入与 state-save 复用同一 `check_placed_conservation`（改数量未重解的中间态被 last-good 拦截）。
- **信任模型**：与 .msn 上传相同（无鉴权 LAN 工具）——LAN 内任何人可持他人 from_sid 恢复其状态，接受；对外暴露走 frp 时 18000 端口不用时关（既有运维建议）。
- **新鲜度窗口**：去抖 ~3s + hidden flush ⇒ 丢失窗口 ≤ 3s（页面直接关闭且 pagehide 失败的极端情形）；run done 立即 checkpoint 覆盖最高价值时刻。
- **既有行为零回归面**：state_save/state_restore 逐字节语义不变（重构仅抽函数）；default 会话（无 sid 旧客户端）不触发任何新路径。

## 成功指标 (Success Metrics)

- [ ] 会话过期后用户刷新页面（F5 / 弹窗按钮），页面回到过期前状态（含数量矩阵 / 表单 / done 态布局）——无需重新上传母版、重配数量、重求解（UI 冒烟断言）。
- [ ] 过期后**停留期间**交互：只弹引导刷新弹窗（新文案），无自动恢复、无自动新建会话、无请求风暴（UI 冒烟断言）。
- [ ] 无 checkpoint 场景（从未上传 / 超 TTL / 服务重启）过期后刷新 = 静默新会话 + toast，无「数据全丢」旧弹窗文案。
- [ ] F5（会话存活）仍为干净重置，旧 checkpoint 被清除（幽灵回潮不可复现）。
- [ ] 求解 / 编辑 / 策略长跑期间不触发过期与恢复（既有钉住机制零回归，pytest + 冒烟）。
- [ ] checkpoint 写入不刷会话活性（假时钟单测断言）；恢复后新会话不额外占第 7 个名额以外容量（净零）。
- [ ] 后端 pytest 全绿 + AST 守卫 + `python -m materialsorting.web.checkpoint` 冒烟；前端 vitest 全绿 + `npm run build` 通过；UI 冒烟脚本全绿。

## 待确认问题 (Open Questions)

（2026-09-13 用户定案，全部关闭：）
- ~~去抖窗口 3s 是否合适？~~ → **定案：暂定 3s**（常量化可调，验收期可观察调整）。
- ~~toast / 弹窗文案定稿~~ → **定案：按设计考虑节建议稿执行**（toast「工作状态已恢复」/「上次会话已过期，已开启新会话」；弹窗「会话已过期，刷新页面后将恢复工作状态」）。
- ~~`MS_CHECKPOINT_TTL_SEC` 缺省 7200 是否合适~~ → **定案：7200 可以**；墓碑窗 `TOMBSTONE_TTL_SEC=3600` 不动（恢复窗 = 过期后 1h，超窗刷新 = 干净重置）。
