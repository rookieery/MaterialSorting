# PRD: Web 多会话隔离（会话 token + 容量上限 + 空闲过期）

## 概述 (Overview)

当前 ms-web 后端是「单文档单例」架构：`_PIECES_STATE` 进程级全局一份、intermediate 落盘全局唯一（`out/sparrow_baseline/pieces_intermediate.json`）、策略长跑进程级单例。多个入口（本地 :5173 dev / 对外隧道 8081）指向同一后端进程时，任一客户端 commit 即覆盖所有人的「当前文档」，其余端静默串台（页面未刷新时展示与服务端数据失配）。

本 PRD 引入**会话 token（sid）机制**：每浏览器一个 sid，后端按 sid 维护独立的工作区状态（pieces 快照 + 策略运行态）；intermediate 改为按 doc 落盘互不覆盖；并叠加两项容量治理机制——**同时最多 4 个活跃会话**（超出提示用户过多）与 **5 分钟无请求即过期清除**（过期后前端弹窗要求刷新页面）。

已定决策（2026-08-27 与用户确认入档）：
1. 两入口（5173 / 8081）确认转发到**同一** ms-web 进程 —— 进程内注册表即可，无需磁盘注册。
2. 策略长跑**完全并发放开**（多会话可同时长跑，接受 CPU 争抢），单飞闸门收窄为「每会话单飞」。
3. 磁盘 uploads 目录**一并加 TTL 清理**（存量无限累积问题，默认 14 天）。
4. 过期 = 彻底清除（不做 doc_id 自动恢复 / 重启自动挂回 —— 与过期语义冲突，明确放弃）；墓碑机制确认接受；过期后刷新需重新上传母版确认接受。
5. 起始参数定值：上限 4 会话 / TTL 5 分钟 / 磁盘 14 天（env 可调，真实使用观测后调整）；过期弹窗**不显示**「上次活动时间」，仅说明 5 分钟无操作。
6. default 会话唯一性：固定常量键 + 服务端单点判别 + 前端单一出口强制带 sid + index.html `no-cache` 收敛迁移窗口（详见技术考虑）。

## 目标 (Goals)

- 多端各自上传母版后，ptypes / 求解 / 导出 / 高级运行**全链路互不串台**：A 会话 commit 不影响 B 会话已持有的数据与正在跑的求解。
- 会话容量有界：同时最多 4 个活跃会话（`MS_SESSION_MAX` 可调），第 5 个新会话在页面加载即被拦下并明确提示。
- 会话生命周期有界：5 分钟无请求（`MS_SESSION_TTL_SEC` 可调）即过期清除；过期后任何请求得到结构化错误，前端阻断式弹窗要求刷新。
- 无 sid 的旧请求（旧前端 / curl / 现有 pytest）落 **default 会话**，行为与现状逐字节一致（测试零改动回归）。
- 磁盘 `out/uploads/` 不再无限累积（14 天 TTL + 活跃保护集）。

## 用户故事 (User Stories)

### US-001: 后端会话注册表与生命周期（sessions.py + POST /api/session）
- **Description**: As a 排料工程师, I want 后端按 sid 维护独立会话（容量上限 4、5 分钟空闲过期、过期墓碑可判） so that 多端同时使用同一服务器互不干扰且资源占用有界。
  新增 `materialSorting-server/src/materialsorting/web/sessions.py`：`SessionRegistry`（`OrderedDict[sid → SessionState]`，`SessionState = {doc_id, pieces 快照, gate_mm, strategy 状态位, last_active, ws_open}`）+ `POST /api/session`（建会话 / 刷活性）。sid 校验复用 `server._DOC_ID_RE`（`[0-9A-Za-z]{1,128}`）。过期采用**墓碑机制**：逐出时丢状态只留 `{sid, ts}`（FIFO ≤128，存活 1h），墓碑命中 → `401 {code:'session_expired'}`，避免「过期后被当作新 sid 静默重建」。default 会话（无 sid）豁免上限与过期，其 state 即 `runtime._PIECES_STATE` 同一 dict 对象（tests 兼容）。
- **Acceptance Criteria**:
  1. `POST /api/session` 带合法 `X-Session-Id` → `200 {ok:true, sid}`；重复调用幂等（仅刷新 `last_active`）。
  2. 已有 4 个活跃会话时第 5 个新 sid → `429 {code:'session_limit', error:'当前使用用户过多（最多 4 人同时在线），请稍后尝试'}`；default 会话不受限、不占额度。
  3. `MS_SESSION_TTL_SEC` 生效（测试设短值）：超时后带 sid 请求 → `401 {code:'session_expired', error:'会话已过期（5 分钟无操作），请刷新页面'}`，且不再命中重建；墓碑 1h 后或容量 FIFO 淘汰后 sid 视为全新（可正常新建）。
  4. 后台扫描线程（30s 周期，daemon）逐出 `ws_open==0` 且超时的会话为墓碑；`ws_open>0`（WS 连接钉住）不逐出；逐出路径释放策略运行态之外的内存负载。
  5. sid 格式非法 → `400 {error:'sid 非法'}`。
  6. 新增 `tests/test_web_sessions.py` 覆盖上述各条（TestClient，`MS_OUT_DIR` 隔离）；`python -m materialsorting.web.sessions` 冒烟（打印配置 + 模拟建会话/过期/超限生命周期）跑通；`sessions.py` 仅 import 标准库与同包模块，不 import `server.py`（无环）。
- **Priority**: 1

### US-002: commit 双写与会话绑定（per-doc intermediate）
- **Description**: As a 排料工程师, I want 我 commit 的母版写到自己文档的 intermediate 文件并挂到我的会话 so that 别人上传母版不会在磁盘或内存覆盖我的数据。
  改 `server.py`：`_commit_to_nesting_sync` intermediate **主写** `out/uploads/<doc_id>_pieces/pieces_intermediate.json`（schema 不变），全局 `paths.INTERMEDIATE` 保留**镜像写**（最后 commit 者胜出，`.bak` 备份行为保留，CLI `ms-sparrow-*` 读全局文件零影响）；`commit_to_nesting` 路由按 `X-Session-Id` 把 `_build_pieces_state(per_doc路径)` 构建的快照注册进该会话（复用 `runtime._build_pieces_state` 已参数化的路径签名）。带 sid 的 commit **不**改 default 会话内存（default 只在无 sid commit 时更新 = 现行为）。
- **Acceptance Criteria**:
  1. 带_sid commit 成功后：`out/uploads/<doc_id>_pieces/pieces_intermediate.json` 存在且与全局镜像内容逐字段一致（同一份 `doc` dict 双写）。
  2. 会话 A、B 先后 commit 不同 doc：A 会话 state（pieces/pieces_by_id/gate_mm）保持自己的 doc，B 的 commit 不影响 A；两份 per-doc 文件并存。
  3. 无 sid commit → default 会话更新 + 全局镜像更新（现行为）：`tests/test_commit_pipeline.py` 及现有 commit 相关测试**零改动全绿**。
  4. `runtime._PIECES_STATE` 与 default 会话 state 是同一 dict 对象（`is` 判等单测锁死；`server_mod._PIECES_STATE` 读者兼容）。
  5. pytest 新增双会话 commit 隔离用例；`python -m materialsorting.web.server` import 链无环、分层依赖未反向。
- **Priority**: 2

### US-003: 读路由与 WS 接入会话
- **Description**: As a 排料工程师, I want 所有读数据端点按我的 sid 取我的会话快照 so that 求解 / 预览 / 导出全部对着我自己上传的母版。
  改 `routes_views.py`（`/api/ptypes`、`/api/band-preview`、`/api/prefix-preview`、`/export` 加 `x-session-id` Header 参数，缺省 default）与 `routes_ws.py`（`/ws/solve?sid=` query 解析——浏览器 WS 不能自定义 Header；连接期 `ws_open` 钉住会话，finally 减回；`on_manifest`/`on_report` 回调顺手刷新 `last_active`——求解期间客户端不发消息也不误杀）。会话过期/超限的结构化响应：HTTP `401/429 + {code}`；WS 发 `{'type':'error','code':'session_expired'|'session_limit','message'}` 错误帧后关闭（`code` 键为 additive，旧前端忽略）。
- **Acceptance Criteria**:
  1. A/B 两会话 commit 不同 doc 后：`/api/ptypes` 各返自己的 representatives；`/api/band-preview`、`/api/prefix-preview`、`/export` 各取各的 `pieces_by_id`（对拍 A 的导出 placed 匹配 A 的轮廓）。
  2. `/export` 带过期 sid → `401 {code:'session_expired'}`（JSON，非文件流）。
  3. WS：合法 sid 求解全流程正常（manifest→frames→final）；过期/超限 sid → 带 `code` 的 error 帧 + close；求解进行中（WS 开着）该会话不被扫描线程逐出；断开后计数归零。
  4. 无 sid（Header/query 缺省）→ default 会话：现有 `tests/test_web_routes.py`、WS 协议测试**零改动全绿**。
  5. 既有不变量保持：WS accept 阶段一次快照整连接不变、density 双口径、导出用原始轮廓非 eroded、stop/断开 terminate 子进程。
  6. `GET /` 响应头含 `Cache-Control: no-cache`（防部署后旧 bundle 滞留 default 会话的迁移窗口）。
- **Priority**: 3

### US-004: 策略长跑会话化（完全并发放开）
- **Description**: As a 排料工程师, I want 我的高级运行（10-60 分钟策略长跑）状态/结果/停止只属于我的会话 so that 多人同时长跑互不覆盖、互不误删产物。
  改 `strategy.py`：`_STRATEGY_STATE` 单例 → `dict[sid, state]`（default 会话沿用无 sid 键）；marker 文件改 `.web_strategy_active_<sid>.json`；run_name 嵌 sid 短缀 `web_<sid6>_<mode>_<rand6>`；**run_dir 认领从「目录快照 diff + mtime 最新」改为确定性前缀 glob**（`web_<sid6>_<mode>_<rand6>_*` —— 完全并发下 mtime diff 必然互相认错，此为必修 bug 修正）；`_cleanup_stale_web_artifacts` 只清本 sid 前缀产物；409 单飞闸门收窄为每会话；orphan 检测按本 sid marker（用户过期后同 sid 回来仍能发现/清理自己的遗留 run）。
- **Acceptance Criteria**:
  1. A、B 两会话先后 `/api/strategy/start` → 均 202；各自 status 轮询互不串台（run_dir、incumbent、events 各归各）。
  2. 并发 start 场景：两会话的 run_dir 认领各自正确（前缀 glob 对拍，不再依赖 mtime）。
  3. B start 不删除 A 的 `web_<A_sid6>_*` run 目录（清理范围单测：造两个前缀目录，B 清理后 A 的仍在）。
  4. A `/api/strategy/stop` 只树杀 A 的 pid，B 的 run 不受影响；A result 只读 A 的 run_dir。
  5. 同 sid 二次 start（前一场未终态）→ 409（每会话单飞）；跨会话不 409。
  6. `tests/test_web_strategy.py` 现有回归零改动全绿（无 sid → default），新增双会话并发用例；`strategy.py` 仍禁 import `..cli.*`（AST 守卫不变）。
- **Priority**: 4

### US-005: 前端会话接入与全局弹窗
- **Description**: As a 排料工程师, I want 我的浏览器自动携带会话标识并在会话过期/超限时得到明确阻断提示 so than 我知道何时需要刷新重来，不会在不知情下用错数据。
  新增 `materialSorting-web/src/lib/session.ts`（sid get-or-create：localStorage `ms_sid`，UUID hex，刷新不变）与 `lib/api.ts`（`apiFetch()` 统一注入 `X-Session-Id`，替换现有 8 处裸 fetch：useParseDxf / useCommitToNesting / useExport / ptypeStore / strategyStore×3 / PerTypeOverridesModal×2）；`lib/ws.ts` 拼 `?sid=`；App 挂载时 `POST /api/session` 探测。新增 `SessionExpiredModal`（阻断式全屏模态，不可点遮罩关闭）：`session_expired` → 「会话已过期（5 分钟无操作），请刷新页面」；`session_limit` → 「当前使用用户过多（最多 4 人同时在线），请稍后尝试」；均带「刷新页面」按钮（`location.reload()`）。`apiFetch` 拦截 `code` 统一弹窗并拦截弹窗期间的后续请求；WS error 帧带 `code` 走同一弹窗。
- **Acceptance Criteria**:
  1. 刷新页面 sid 不变（localStorage）；所有 HTTP 请求带 `X-Session-Id`、WS URL 带 `?sid=`（DevTools 网络面板核验）；代码中**不存在裸 fetch**（grep `fetch(` 仅命中 `lib/api.ts` 单一出口——保证真实用户请求结构性必带 sid，不落 default）。
  2. 会话过期后任一操作 → 阻断弹窗 +「刷新页面」按钮可重载；弹窗期间后续 fetch 被拦截不发。
  3. 第 5 个浏览器窗口页面加载即弹「用户过多」（无需先上传）；关闭一个窗口待其过期后刷新可进入。
  4. vitest 现有用例（mock fetch）适配 Header 后全绿；新增 session.ts / apiFetch 拦截单测。
  5. 通过浏览器双窗口实测互不串台（上传预览 / 求解 / 导出各归各，UI 状态一致）。
- **Priority**: 5

### US-006: uploads 磁盘 TTL 清理
- **Description**: As a 运维者, I want 上传目录按 TTL 自动清理且绝不误删在用文档 so that 磁盘占用有界、多会话场景下目录不再无限累积。
  新增 `materialSorting-server/src/materialsorting/web/diskclean.py`：扫 `out/uploads/` 删超龄（`MS_UPLOAD_TTL_DAYS` 缺省 14 天，按目录 mtime）的 `<doc_id>.dxf` + `<doc_id>_pieces/` **成对**目录与超龄 `strategy_cfg_*.json`。保护集 = 注册表活跃会话 doc_id ∪ 全部 `.web_strategy_active_<sid>.json` marker 内 doc_id（进行中策略 run 的 master_dxf）∪ mtime 未超龄者。触发：进程启动 + 每次 commit 成功后 best-effort（异常仅 warn 不阻塞主流程）。
- **Acceptance Criteria**:
  1. 临时目录（`MS_OUT_DIR` 隔离）造新旧混合文件：超龄对被删、未超龄与保护集内（活跃会话 / marker 引用）不删；孤儿单边（只有 dxf 无 pieces 目录或反之）也按同 TTL 清理。
  2. 会话 A 活跃 + 会话 B 已过期但 B 的策略 run 仍在跑（marker 在）：B 的 master doc 不被删。
  3. 清理失败（目录被占用等）只 warn，commit 响应不受影响。
  4. `python -m materialsorting.web.diskclean` 冒烟（dry-run 打印将删清单）+ `tests/test_web_diskclean.py` 通过；分层依赖未反向。
- **Priority**: 6

### US-007: 端到端集成验收与文档同步
- **Description**: As a 项目维护者, I want 多端全链路对拍验收与契约文档同步 so that 特性合入后行为可查、后续开发不踩坑。
- **Acceptance Criteria**:
  1. 双浏览器（普通 + 隐身窗口模拟两设备）全链路对拍：各自上传不同母版 → ptypes/求解/停止/导出/高级运行全程互不串台；一端 commit 时另一端正在跑的求解不中断且结果仍属原母版。
  2. 生命周期对拍：空闲 >TTL → 操作弹「已过期」→ 刷新 → 干净新会话；求解中 / 高级运行轮询中的会话不被误杀。
  3. `.docs/technical/agent-api-reference.md` 同步：`POST /api/session` 契约、各端点 sid 传递方式（Header / query）、`401/429 + code` 错误码表、WS error 帧 `code` 键、per-doc intermediate 落盘布局、marker 文件改名。
  4. `README.md` / `web/AGENTS.md` 相关段同步（会话机制 + 环境变量 `MS_SESSION_MAX` / `MS_SESSION_TTL_SEC` / `MS_UPLOAD_TTL_DAYS`）。
  5. 全量 pytest + vitest 绿；`ms-web` 启动冒烟无回归（default 会话行为同旧版）。
- **Priority**: 7

## 功能需求 (Functional Requirements)

- **FR-1（sid 协议）**：前端每浏览器持有一个 sid（localStorage `ms_sid`，UUID hex，命中 `[0-9A-Za-z]{1,128}`）；HTTP 经 `X-Session-Id` Header、WS 经 `/ws/solve?sid=` query 携带；`POST /api/parse-dxf` 无状态不强制 sid（带 sid 则刷新活性）。
- **FR-2（会话端点）**：`POST /api/session` 建会话 / 幂等刷新活性，页面加载时探测；`200 {ok,sid}` / `429 session_limit` / `401 session_expired` / `400 sid 非法`。
- **FR-3（容量上限）**：同时最多 4 个活跃会话（`MS_SESSION_MAX`，default 豁免不占额）；超出在会话建立时即拦（页面加载即弹窗，不等上传失败）；槽位随过期释放；超限响应 `429 {code:'session_limit'}`。
- **FR-4（空闲过期）**：5 分钟（`MS_SESSION_TTL_SEC`）无该 sid 的请求即过期，状态清除（墓碑仅留 sid 供 401 判定，1h / FIFO≤128 有界）；活性口径 = 该 sid 的任何 HTTP 请求 + WS 连接钉住（`ws_open>0` 不逐出）+ 求解帧回调刷新 `last_active` + 高级运行轮询（既有 2s/15s HTTP）；过期响应 `401 {code:'session_expired'}`；**不做前端保活 ping**（严格空闲语义，标签页开着不看也算闲置）。
- **FR-5（per-doc 落盘）**：intermediate 主写 `out/uploads/<doc_id>_pieces/pieces_intermediate.json`，全局 `paths.INTERMEDIATE` 镜像同步写（CLI/旧链路兼容，`.bak` 保留）；会话快照从 per-doc 文件构建。
- **FR-6（读路由会话化）**：`/api/ptypes`、`/api/band-preview`、`/api/prefix-preview`、`/export`、`/ws/solve`、`/api/strategy/*` 全部按 sid 解析会话；缺省 sid → default 会话（现行为）。
- **FR-7（策略会话化）**：策略状态 / marker / run_name / 产物清理 / 单飞闸门 / orphan 检测全部按 sid 分键；run_dir 认领用确定性前缀 glob；跨会话完全并发（CPU 争抢已接受，不加全局闸门）。
- **FR-8（前端拦截与弹窗）**：`apiFetch` 统一注入 sid 并拦截 `code` → 阻断式全局弹窗（过期 / 超限两态文案）+「刷新页面」按钮；弹窗期间拦截后续请求；WS error 帧 `code` 同弹窗。
- **FR-9（磁盘清理）**：`out/uploads/` 按 14 天（`MS_UPLOAD_TTL_DAYS`）TTL 成对清理，保护集 = 活跃会话 ∪ marker 引用 ∪ 未超龄；启动 + commit 后 best-effort 触发。
- **FR-10（兼容性）**：无 sid 请求全链路等同现行为（default 会话）；现有 pytest / vitest 套件零语义改动通过。

## 非目标 (Non-Goals)

- **鉴权 / 权限**：sid 只做隔离不做安全边界（能摸到端口者可伪造 sid）；不引入登录、密码、用户体系。
- **同浏览器多标签页隔离**：localStorage 共享 → 同浏览器多标签 = 同一会话（同一工作区语义）；不引入 per-tab sessionStorage。
- **会话数据持久化 / 恢复**：过期即清除、服务重启即全部丢失；不做 doc_id 自动挂回（与过期语义冲突，已明确放弃）；磁盘 doc 文件仅等 TTL 清理，不承诺恢复。
- **前端保活 ping / 自动重连复活**：严格 5 分钟空闲过期；不做后台心跳让标签页永生。
- **超限排队 / 等候名单**：第 5 会话直接 429 弹窗，不排队、不自动重试。
- **求解并发限流**：多会话同时 `/ws/solve` 维持现状允许（既有 6-worker 池 + 每连接子进程），不加全局求解闸门。
- **uploads 历史存量的一次性清盘**：只上 TTL 机制自然消化，不写一次性迁移脚本。

## 设计考虑 (Design Considerations)

- **弹窗为阻断式模态**：不可点遮罩/ESC 关闭，唯一出口 =「刷新页面」按钮；过期与超限文案区分（过期 → 刷新后开新会话；超限 → 提示稍后再试，刷新仅在槽位释放后有效）。
- **第 5 个用户的拦截时机在页面加载**（`POST /api/session` 探测），不是上传 3MB 后才失败——错误前置。
- **隔离粒度 = 每浏览器**：与「每个使用者一个工作区」的直觉一致；两设备访问同一地址自然是两会话。
- **会话过期后的体验预期**（需向用户宣导）：盯着结果看超 5 分钟不做任何触发请求的操作 → 下次操作弹过期；刷新后需重新上传母版。求解中 / 高级运行轮询中不会误杀。
- **WS `?sid=` 而非首条消息带 sid**：校验发生在读首条消息之前，且不改变「首条必须 action:start」的既有协议语义。

## 技术考虑 (Technical Considerations)

- **`SessionRegistry` 并发安全**：全表操作持锁；`last_active`/`ws_open` 的简单数值写读在 GIL 下无撕裂（与 `routes_ws.state_box` 同模式）。扫描线程 daemon、30s 周期，跳过 `ws_open>0`。
- **墓碑（tombstone）机制**：过期逐出时丢状态只留 `{sid, ts}`，保证「过期后下一请求得到 401 而非静默新建」；墓碑 1h 过期或 FIFO≤128 封顶，防 sid 喷射膨胀。
- **default 会话兼容层**：default 会话的 state 与 `runtime._PIECES_STATE` 是**同一 dict 对象**（沿用 clear+update 快照模式）——tests 直读 `server_mod._PIECES_STATE`、`strategy.py` 延迟 import `_get_pieces_state()` 全部不改即兼容；带 sid 的 commit 不触碰 default 内存（default 只被无 sid commit 更新），default 内存与全局镜像文件允许漂移（镜像 = 最后 commit 者，default = 最后无 sid commit 者）。
- **default 会话的唯一性与判别单点**：default 不是被「创建」的会话，而是注册表固定常量键 `DEFAULT_SID='default'`（进程启动即存在，不占 4 个名额、永不过期、不参与墓碑）；会话解析收敛到 registry 单一 resolve 函数——请求带合法 sid → 按 sid 归属，不带 → 全部落同一常量键，**结构上不可能出现第二个 default**。防碰撞为结构性：前端 sid 是 `uuid4().hex`（仅 `0-9a-f`），与含非 hex 字符的 `'default'` 不可碰撞。无 sid 请求只有三类刻意兼容来源：旧缓存 bundle / 手工 curl / 测试套件。
- **旧 bundle 迁移窗口**：`GET /` 返回的 index.html 补 `Cache-Control: no-cache`（FastAPI FileResponse 缺省不发缓存头，浏览器启发式缓存会让部署后的老用户继续跑不带 sid 的旧 bundle 落 default，两会话退化为升级前共享现状）；刷新即取新 bundle，窗口自愈。
- **run_dir 认领改前缀 glob 是并发正确性修复**：现「快照 diff + mtime 最新」在两会话同时 spawn 时必然互相认领；`web_<sid6>_<mode>_<rand6>` 前缀确定性归属（sid6 = sid 前 6 字符，rand6 保同会话同 mode 二跑唯一）。
- **marker per sid**：`.web_strategy_active_<sid>.json`（default 会话用旧名 `.web_strategy_active.json` 或 `<default>` 后缀，保持旧测试路径兼容——实现取「default 无后缀」方案）。
- **镜像写盘的原子性**：per-doc 与全局镜像为同一 `doc` dict 双写两文件；顺序 = 先 per-doc 后镜像（镜像失败仅 warn，会话仍以 per-doc 为准）。
- **环境变量**：`MS_SESSION_MAX=4`、`MS_SESSION_TTL_SEC=300`、`MS_UPLOAD_TTL_DAYS=14`（均启动读取，运行期不变）。
- **测试隔离**：沿用 `MS_OUT_DIR` 环境变量隔离产物目录；会话测试用 TestClient + 短 TTL 值；不依赖真实墙钟长等待（TTL 用可注入时钟或极短值）。
- **分层**：`sessions.py` / `diskclean.py` 均为 web 包内模块，仅标准库 + 同包依赖，不 import `server.py`（无环）、不 import `..cli.*`（AST 守卫不变）。

## 成功指标 (Success Metrics)

- [ ] 双浏览器各传各的母版：ptypes / 求解 / 导出 / 高级运行全链路互不串台；A commit 时 B 正在跑的求解不中断、结果仍属 B 的母版。
- [ ] 第 5 个并发会话在页面加载即得 `429 session_limit` 弹窗；槽位释放后可进入。
- [ ] 空闲 >5 分钟 → 任一操作 `401 session_expired` → 阻断弹窗 → 刷新后干净新会话；求解中 / 策略轮询中的会话不被误杀。
- [ ] A、B 同时高级运行：status/result/stop 各归各，A 的 start 不删 B 的 run 目录，run_dir 认领零错配。
- [ ] 现有 pytest + vitest 套件零语义改动全绿（default 会话回归）。
- [ ] 磁盘清理：超龄目录被删，活跃会话与进行中策略 run 的母版不被误删。
- [ ] 单用户旧流程（单窗口上传 → 求解 → 导出）行为与现版无感知差异。

## 待确认问题 (Open Questions)

（无 —— 2026-08-27 二轮确认全部收口：墓碑机制 / 过期重传 / 起始参数定值 / 弹窗文案不显示上次活动时间 / default 会话唯一性判别均已入档「已定决策」。运营参数（4 会话 / 5 分钟 / 14 天）留 env，观测后再调。）
