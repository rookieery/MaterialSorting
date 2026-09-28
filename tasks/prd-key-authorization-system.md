# PRD: Key 授权管理系统（消费端授权闸门 + Key 后台管理系统）

## 概述 (Overview)

为 VB 超排（MaterialSorting，本地部署 exe 交付）构建商业授权体系，包含两个系统：① 全新 **Key 后台管理系统**（本仓新增顶层 `keyserver/`，FastAPI + SQLite，独立进程部署，经 frp 内网穿透暴露公网），负责 key 全生命周期（生成/绑定/合并/校验/续期/删除）与可视化管理；② **消费端改造** —— web 工作台在「导出最优方案」区新增「当前系统 key 属性」弹窗（当前 key 绑定 / 被合并 key 批量合并 / 属性展示），并在**普通运行（WS）、高级运行、极限运行**三入口建立「前端预检（只读）+ 后端二次校验（权威扣次）」双层闸门。样例执行与 `/api/machine/*` 外部系统调用两类豁免。断网 fail-closed。

全部 15 项设计决策已于 2026-09-28 会话定案（见 FR 逐条与「技术考虑」决策台账），无遗留待确认问题。

## 目标 (Goals)

- 未绑定有效 key 的系统**无法通过 web 三入口运行算法**：前端拦截给即时中文反馈，后端闸门防绕过（前端被绕过时算法仍无法启动）
- key 账务**全部服务端权威**（keyserver SQLite 唯一账本），次数扣减并发零超扣（20 线程对拍验证）
- key 管理员可视化发卡/续期/删除/统计（`/admin` 单页），无需命令行
- 冻结 exe（Nuitka）生产行为验证通过（winreg / key_server_url.txt / LOCALAPPDATA 落盘 / dev 逃生失效）
- 既有功能**零回归**：pytest 全量 + 既有 UI 冒烟全绿，无 key 相关改动对旧路径逐字节不变

## 用户故事 (User Stories)

### US-001: keyserver 骨架与数据层
- **Description**: As a 后端开发者, I want keyserver 项目骨架（FastAPI + SQLite）+ 三表数据模型 + 状态推导与 key 生成 so that 全部授权业务有单一数据地基。主要文件：`keyserver/pyproject.toml`（独立包，console_scripts `ms-keyserver`，deps 仅 fastapi + uvicorn[standard]，sqlite3 标准库）、`keyserver/src/keyserver/{app,db,models,keygen,repo}.py`、`keyserver/tests/`。keyserver **不依赖 materialsorting 包**（独立系统，禁 import）。
- **Acceptance Criteria**:
  1. `python -m keyserver.app`（或 `ms-keyserver`）启动后 `GET /api/key/health` 返回 200；DB 路径经 env `MS_KEY_DB` 重定位（缺省 `<部署目录>/data/keys.db`，`ensure_schema` 自动迁移建表）
  2. 三表 schema 落地：`keys`（id PK、key_plaintext TEXT UNIQUE NOT NULL、key_type ∈ 'count'|'duration'、total_uses INT、used_uses INT DEFAULT 0、duration_days INT、activated_at TEXT NULL、expires_at TEXT NULL、bound_machine_guid TEXT NULL、bound_system_name TEXT NULL、remark TEXT NULL、merged_into_id INT NULL、created_at/updated_at TEXT）+ `key_daily_usage`（PRIMARY KEY (key_id, ymd 'YYYY-MM-DD')、count）+ `key_op_log`（id、key_id、op、detail TEXT JSON、ts）
  3. `new_key_plaintext()` 输出匹配 `^MS-[A-Z2-9]{5}-[A-Z2-9]{5}-[A-Z2-9]{5}$`（字母表 `ABCDEFGHJKMNPQRSTVWXYZ23456789`，去 I/L/O/U/0/1），1000 次生成无重复
  4. `derive_status(row, now)` 纯函数六态矩阵单测全过：merged_into_id 非空 → `merged`（已合并）；count 型 used≥total → `exhausted`（已用完）；未绑定 → `unbound`；duration 已绑定未激活 → `unactivated`；duration 已激活 now>expires_at → `expired`；其余已绑定 → `active`（正在使用）
  5. SQLite `journal_mode=WAL` + `busy_timeout=5000`；keyserver 自有 pytest 全绿
- **Priority**: 1

### US-002: keyserver 管理端五接口 + 双 token 鉴权
- **Description**: As a key 管理员, I want 经 `X-Admin-Token` 调 list/create/renew/edit/delete 五接口 so that 不开 UI 也能完成 key 全生命周期管理。主要文件：`keyserver/src/keyserver/routes_admin.py`。
- **Acceptance Criteria**:
  1. token 姿态（frp 修正版）：`MS_KEY_ADMIN_TOKEN` **未设置**且无 `MS_KEY_DEV=1` → 管理端点族 403「管理 token 未配置，请设置 MS_KEY_ADMIN_TOKEN」（**不做 loopback 放行兜底** —— frpc 与 keyserver 同机时公网流量来源 IP 恒为 127.0.0.1，loopback 兜底等于公网裸奔）；已设置时缺失/错误 → 401（`secrets.compare_digest` 常量时间比较）
  2. `GET /api/admin/keys` → `{keys:[{id, key_plaintext, key_type, detail, status, bound_system_name, remark, usage_stats, created_at}]}`；`usage_stats = {total, max_daily, avg_daily, first_used}`（口径见 FR-15，无使用记录 → null）
  3. `POST /api/admin/keys` 新建：`{key_type:'count', total_uses:N}` 或 `{key_type:'duration', duration_days:N}`，可选 remark → 201 返回明文（此刻生成）
  4. `POST /api/admin/keys/{id}/renew` 续期：count → `total_uses += add_uses`；duration 未激活 → `duration_days += add_days`；已激活 → `expires_at += add_days` 天；add 非正整数 → 400 中文
  5. `PUT /api/admin/keys/{id}` 改备注名 `{remark}`（保存即生效）
  6. `DELETE /api/admin/keys/{id}`：非 active 态直接 200；active 且无 `?force=true` → 409 `{"error":"该 key 正在使用，确认删除请再次确认"}`；带 force → 200
  7. 每操作写 `key_op_log`（create/renew/edit/delete）；keyserver pytest 全绿（token/force/续期三态矩阵）
- **Priority**: 2

### US-003: keyserver 消费端四接口 + 并发扣次
- **Description**: As a 消费端系统, I want bind/merge/info/validate 四接口 so that 绑定、合并、展示与校验扣次全部服务端权威完成。主要文件：`keyserver/src/keyserver/{routes_consumer,service}.py`。
- **Acceptance Criteria**:
  1. `POST /api/key/bind {key, machine_guid, system_name}`：key 未绑 → 绑定（`bound_system_name` = system_name 快照；remark 缺省 = system_name）且 **duration 型同时激活**（`activated_at=now, expires_at=now+duration_days 天`）；已绑本机 → 幂等 200；已绑他机 → 409「该 key 已绑定其他系统，无法绑定到本机」；不存在 → 404「key 不存在：请检查输入是否正确」；已用完/已过期/已合并 → 409 对应中文
  2. `POST /api/key/merge {target_key, source_keys:[...], machine_guid}`：要求全 source 为 duration 型 + 全部绑定本机 + target ∉ sources + target/source 均有效；逐个把 source 剩余时长**秒级精确转移**（`target.expires_at += (src.expires_at − now)`），source 置 `merged_into_id` **保留不物理删除**；违反规则 → 400 对应中文（「仅时长型 key 可合并：`<key>` 为次数型」/「`<key>` 未绑定当前系统，无法合并」/「`<key>` 已失效（过期/已合并），无法合并」）
  3. `POST /api/key/info {key, machine_guid}`：只读不动账；count → `{type, total_uses, used_uses, remaining_uses, status,...}`；duration → `{type, activated_at, expires_at, remaining_days, status,...}`；附 `bound_system_name/remark`；绑定他机 → 403「该 key 绑定在其他系统，无法查看」
  4. `POST /api/key/validate {key, machine_guid, deduct:bool}`：通过条件 = 存在 + 绑定本机 + 状态有效（count 未用完 / duration 未过期）；`deduct:true` → count 型原子扣 1 + `key_daily_usage` 当日 upsert +1（duration 型仅记日）；失败 → 403 中文（「授权已过期（截止 YYYY-MM-DD HH:MM）」/「授权次数已用完（共 N 次）」/「该 key 未绑定当前系统」/「该 key 尚未绑定任何系统」）；`deduct:false` 不动任何账（前端预检专用）
  5. **并发零超扣**：单条原子 SQL `UPDATE keys SET used_uses=used_uses+1 WHERE id=? AND key_type='count' AND used_uses<total_uses`，rowcount=0 → 403；pytest 20 线程对 total=5 并发 validate → 恰 5×200 + 15×403，`used_uses` 终值 = 5
  6. `X-Client-Token`：env `MS_KEY_CLIENT_TOKEN` 已设时消费端四接口强制（缺失/错 401）；`MS_KEY_DEV=1` 时放行（本地开发逃生）
  7. 到期判定一律用 **keyserver 服务器时钟**（消费端时钟不可信）；op_log 记 bind/merge_source/merge_target/validate_deduct；keyserver pytest 全绿
- **Priority**: 3

### US-004: 消费端 keygate 模块与本地状态
- **Description**: As a 消费端后端, I want `web/keygate.py` 客户端模块 + 本地 `key_state.json` + MachineGuid 读取 so that 消费端能以机器身份与 keyserver 通信并持久保存当前 key。主要文件：`materialSorting-server/src/materialsorting/web/keygate.py`（新增）、`paths.py`（加 `LICENSE_DIR`）、`tests/test_web_keygate.py`。模块级仅标准库 + `..paths`，**禁 import `..cli.*` 与 server**（AST 守卫，镜像 `edit_hold.py` 先例）；HTTP 用 `urllib.request`（冻结面零新增依赖）。
- **Acceptance Criteria**:
  1. `paths.LICENSE_DIR = OUT_DIR/'license'`（frozen 态经 `MS_OUT_DIR` 落 `%LOCALAPPDATA%/MaterialSorting/out/license/`）；`key_state.json` 原子写（tmp+rename）、重启可读
  2. `machine_guid()`：`winreg` 读 `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid`；读失败 → `LICENSE_DIR/machine_id.txt` 铸 uuid4 持久化兜底（稳定）+ stderr warn
  3. keyserver URL 解析链：env `MS_KEY_SERVER_URL` → frozen exe 旁 `key_server_url.txt`（现场免设环境变量）→ 皆无 → fail-closed 返回「授权服务器未配置」
  4. `ensure_run_allowed(doc_source) -> (ok, message)`：样例豁免（延迟 `from .routes_views import _sample_dxf_names` 判 `doc_source ∈ 白名单` → `(True,'sample')`）→ 本地无 key → `(False,'未绑定授权 key：请在「当前系统 key 属性」中输入并保存')` → `_key_post('/api/key/validate', {key, machine_guid, deduct:true})`
  5. 错误映射：超时（5s）/URLError → 「无法连接授权服务器，请检查网络后重试」（fail-closed）；keyserver 4xx 的中文 error 透传；**无自动重试**（deduct=true 响应丢失时服务端可能已扣次，重试会双扣）
  6. `MS_KEY_MODE=off` **仅在 `not getattr(sys,'frozen',False)` 时生效**（冻结生产 exe 不可绕；保既有测试零漂移）
  7. AST 守卫测试 + `python -m materialsorting.web.keygate` 合成夹具冒烟 exit 0 + 全量 pytest 回归通过
- **Priority**: 4

### US-005: 三入口后端闸门 + 双豁免
- **Description**: As a 排料系统所有者, I want WS start 与 strategy/extreme start 在真正运行算法前向 keyserver 二次校验（样例与 machine 豁免） so that 前端被绕过时算法仍无法运行。主要文件：`web/routes_ws.py`、`web/strategy.py`、`web/routes_key.py`（新增）、`web/server.py`（文件尾注册）。
- **Acceptance Criteria**:
  1. `routes_key.py` 四端点（注册于 server.py 文件尾 checkpoint 之后）：`GET /api/key/state`（本地 key + info 只读现查，keyserver 查询失败也 200 带 error 字段供弹窗展示）、`POST /api/key/save {key}`（bind → 成功落 key_state.json）、`POST /api/key/merge {source_keys:[...]}`（target = 本地当前 key）、`POST /api/key/precheck`（validate deduct=false）；key 状态是**机器级全局**，不加会话闸门（文档注明与 /api/edit-hold 的差异）；阻塞调用走 `asyncio.to_thread`
  2. WS 闸门：`routes_ws.py` ws_solve 在 pieces 校验后、band/prefix 解析前，`await asyncio.to_thread(keygate.ensure_run_allowed, state['doc']['source'])`；拒绝 → `{'type':'error','code':'key_blocked','message':...}` 帧 + 显式 close（既有 band 早退样板），不建求解子进程
  3. strategy/extreme 闸门：`strategy.py _start_run` 在**全部载荷校验后、`_cleanup_stale_web_artifacts`（strategy.py:951）之前**插入同款校验（一处插入双族生效）；拒绝 → `JSONResponse({'error': msg}, status_code=403)`；pytest 断言被拒 start **不清理上一轮 run 产物、不 spawn、不写 cfg**
  4. 绑定有效 key：三入口正常跑通（既有语义零漂移），keyserver `used_uses` 每 start 恰 +1（高级运行多 seed/多轮单次扣 —— 扣次唯一锚点 = MS 后端 start）
  5. 样例母版会话（`doc.source` 命中白名单）：三入口全部免闸跑通
  6. `/api/machine/*` 六端点**零改动** + 豁免回归锁：monkeypatch keygate 抛异常时 machine_solve 仍正常 202
  7. 全量 pytest 通过（既有用例经 monkeypatch `ensure_run_allowed → (True,'')` 或 `MS_KEY_MODE=off` 零改动零漂移）
- **Priority**: 5

### US-006: Key 属性弹窗与入口按钮
- **Description**: As a 排料软件用户, I want「导出最优方案」区最下的「当前系统 key 属性」按钮与弹窗（当前 key 输入替换 / 被合并 key 批量添加 / 属性展示） so that 我能自助管理本机授权。主要文件：`materialSorting-web/src/components/ControlPanel/KeyInfoModal.tsx`（新建）、`ControlPanel.tsx:513`（ExportButtons 之后挂入口按钮）、`store/controlPanelStore.ts:28`（`ControlPanelModalId` 加 `'key_info'`，additive）、`store/keyStore.ts`（新建，zustand）、`style.css`（`.key-*` 前缀，无 CSS 框架）。
- **Acceptance Criteria**:
  1. 入口按钮位于 ExportButtons 区块正下方；弹窗骨架镜像 ExportInfoModal（Portal + ESC/遮罩关闭 + `apiFetch`），单例互斥不与既有 modal 冲突
  2. 三区块齐备：① 当前 key 输入/替换 + 「保存」（POST /api/key/save，失败中文红字透传）；② 被合并 key textarea 批量添加（每行一个）+「合并」（POST /api/key/merge，结果明细 = 每个 key 成功天数或失败原因）；③ 属性展示（次数型 总数/剩余；时长型 生效/截止）+ 状态徽标
  3. localStorage 镜像 `ms_key`：弹窗打开**先用 localStorage 即时预填**（不等网络往返）→ `GET /api/key/state` 对账**以后端为准**（绑定/合并都发生在后端）；保存成功双写（后端 key_state.json + localStorage）；清缓存/换浏览器不丢 key（后端文件权威）
  4. 默认未绑定态显示空输入 + 引导文案；全部请求走 `apiFetch`（X-Session-Id 体系照常）
  5. vitest 组件测试通过 + `npm run build` 无错误 + **通过浏览器验证弹窗渲染与三区块交互**
- **Priority**: 6

### US-007: 三入口前端拦截
- **Description**: As a 排料软件用户, I want 点击普通/高级/极限运行时先校验 key so that key 失效时得到即时中文反馈而非跑一半失败。主要文件：`materialSorting-web/src/lib/keyGate.ts`（新建 `ensureRunAllowed(): Promise<{ok:true}|{ok:false,message}>` = POST /api/key/precheck）、`ControlPanel.tsx:256 handleStart`（async 化顶部拦截）、`store/strategyStore.ts:109 createRunStore`（工厂内 `start()` 的 `apiFetch /start` 之前拦截 —— **一处插入高级+极限双族生效**）。
- **Acceptance Criteria**:
  1. precheck 失败：普通运行不进入 WS 连接（无 onStart 调用）且 Toast/StatusLine 显示中文错误；高级/极限不发 `/start` 请求（fetch 计数断言）且弹窗 `errorMessage` 既有渲染位展示
  2. precheck 通过：三入口交互与现状**逐字节一致**（既有测试零改动通过）
  3. 断网文案「无法连接授权服务器，请检查网络后重试」三入口一致（后端 precheck 映射，前端不自行判断网络）
  4. vitest 通过 + `npm run build` 无错误 + 通过浏览器验证三入口拦截与放行
- **Priority**: 7

### US-008: keyserver 管理后台可视化单页
- **Description**: As a key 管理员, I want `/admin` 单页表格（新建/编辑续期/删除确认/使用统计） so that 无命令行也能日常发卡续卡。主要文件：`keyserver/src/keyserver/static/admin.html`（原生 HTML + fetch + 内联 CSS，**不进 materialSorting-web Vite 构建链**）、`app.py` 挂载 `/admin`。
- **Acceptance Criteria**:
  1. 表格八列按需求列序：名称（= key 明文）｜绑定系统名（只读）｜备注名｜类型（次数/时长）｜详细信息（次数 N/M 或时长 起~止）｜属性（六态：正在使用/已过期/已用完/未绑定/未激活/已合并）｜使用统计（一格三行：`均 X.X/日 ｜ 峰 N ｜ 共 M`，无记录 `—`）｜操作（编辑/删除）
  2. 新建表单：时长型（生效时长，默认单位天）/ 次数型（单位次），创建后即时出现在表格
  3. 编辑弹窗：修改备注名 + 续期（次数型加次数 / 时长型加天数），保存后表格即时生效（remaining/截止时间变化可见）
  4. 删除：已过期/已用完直接删；正在使用出二段确认弹窗，确认（force）后才删
  5. token 登录框存 sessionStorage 附 `X-Admin-Token` 请求头；未设 token 的部署显示配置指引文案
  6. keyserver pytest 全绿 + 通过浏览器验证（本机或 frp URL 均同源无跨域）
- **Priority**: 8

### US-009: 契约文档与冻结部署验证
- **Description**: As a 运维/对接方, I want agent-api-reference 专节 + AGENTS/README + frp 部署手册 + frozen exe 验证 so that 现场部署与后续对接可直接照文档操作。主要文件：`.docs/technical/agent-api-reference.md`（专节，参照机器对接专节写法）、`web/AGENTS.md`（新节「key 授权闸门关键约定」）、`README.md`、`.docs/technical/本地部署构建与发版手册.md`（frp runbook）、`launcher.py`（`--check` 回显 key 配置）。
- **Acceptance Criteria**:
  1. 专节含：四 MS 端点字段表/错误码矩阵/三入口双闸时序图/两类豁免口径/keyserver URL 配置链/`MS_KEY_MODE` 说明/keyserver 四+五接口契约摘要
  2. frp runbook：frpc 配置样例、**双 token 必设**（`MS_KEY_ADMIN_TOKEN` + `MS_KEY_CLIENT_TOKEN`；说明 loopback 兜底在 frp 同机部署下失效的原因）、HTTP 明文残余风险备案（嗅探可 see key 但绑定 MachineGuid 后他机不可用，TLS 二期）
  3. frozen exe（Nuitka 产物）实测：`key_server_url.txt` exe 旁置生效、`launcher --check` 回显 key 配置、`key_state.json` 落 `%LOCALAPPDATA%\MaterialSorting\out\license\`、winreg 读取成功、`MS_KEY_MODE=off` 在 frozen 态无效（实测）
  4. 全量 pytest 通过
- **Priority**: 9

### US-010: 端到端冒烟与验收报告
- **Description**: As a 发布负责人, I want `smoke_key_gate.mjs` 全链路冒烟 + 验收报告 so that 按仓库惯例交付证据。主要文件：`materialSorting-web/scripts/smoke_key_gate.mjs`（Edge 通道 + addInitScript 防 tour-overlay，模板 `smoke_sample_picker.mjs`/`smoke_prefix_extra.mjs`）、`.docs/business/Key授权_验收报告.md`。
- **Acceptance Criteria**:
  1. 冒烟全链路：起 keyserver + ms-web → 样例载入免闸跑通 → 未绑 key 三入口均报错 → 假 key 保存报错 → 真 key 绑定 + 批量合并 + 运行跑通 → keyserver 侧扣次（used_uses 恰 +1）与使用统计（daily_usage +1）断言
  2. `npm run build` 后 **:8010 生产 bundle 含新代码**（用户入口是生产构建，dev:5173 通过不算数）
  3. 验收报告按 `.docs/business/` 惯例落盘（含 15 项决策台账与四开放决策切换成本备案表）
  4. 全量 pytest 通过
- **Priority**: 10

## 功能需求 (Functional Requirements)

- **FR-1 key 类型**：次数型（`total_uses` 总次数 / `used_uses` 已用）与时长型（`duration_days` 购买天数 / `activated_at` / `expires_at`）。时长型**首次绑定系统时激活**起算（`activated_at=绑定时刻, expires_at=now+N 天`），后台创建不计时。
- **FR-2 key 明文格式**：`MS-XXXXX-XXXXX-XXXXX`，字母表 `ABCDEFGHJKMNPQRSTVWXYZ23456789`（≈74 bit 熵）；UNIQUE 索引 + 冲突重试。**库内明文存储**（需求「名称列=明文」决定必须可还原；泄露由管理端删除/止损，哈希化二期备案）。
- **FR-3 绑定规则**：以 MachineGuid 判别系统；**一个系统可绑定多个 key，一个 key 只能绑定一个系统**；绑定系统名 = 绑定时 `socket.gethostname()` 快照（只读），备注名缺省 = 系统名、管理端可改；重复绑本机幂等 200。
- **FR-4 合并规则**：仅**时长型**、仅**绑定同一系统**的不同 key 可合并；被合并 key 的剩余时长**秒级精确**（`expires_at − now`）转移到当前 key；被合并 key 置 `merged_into_id` 标记「已合并」**保留在表格**（审计可追），不物理删除。
- **FR-5 校验与扣次**：**扣次唯一锚点 = MS 后端 start 时刻**（前端预检恒 `deduct:false` 只读）；普通/高级/极限每次启动各扣 1 次，高级运行内多 seed/多轮/race 门杀/LNS 不重复扣；预扣不退；原子 SQL 防并发超扣；每次校验通过记 `key_daily_usage` 当日 +1；到期判定用 keyserver 服务器时钟。
- **FR-6 状态机六态**：正在使用（active）/已过期（expired）/已用完（exhausted）/未绑定（unbound）/未激活（unactivated，绑定即激活默认下不出现，留作计时起点切换桩）/已合并（merged）——表格「属性」列与校验共用 `derive_status` 单一真相源。
- **FR-7 消费端 Key 属性弹窗**：三区块（当前 key 输入/替换保存、被合并 key 批量添加合并、属性展示）；key **双层持久化** —— 后端 `out/license/key_state.json` 权威（机器级、重启不丢、后端闸门自用）+ 前端 localStorage `ms_key` 镜像（打开即时预填，以后端对账为准）。
- **FR-8 三入口双闸**：前端点击普通/高级/极限运行先 `POST /api/key/precheck`（不扣），失败弹窗/Toast 中文报错不发起运行；后端在算法真正运行前再向 keyserver `validate deduct=true`（WS start 处 + strategy/extreme `_start_run` 处），失败拒绝运行。
- **FR-9 双豁免**：样例执行（会话 `doc.source` 命中 `routes_views._sample_dxf_names()` 实时白名单，服务端推导前端零改动；已知边界：用户自传同名文件同被豁免，接受并记录文档）；`/api/machine/*` 六端点族不插闸门（豁免 = 不做，回归测试锁定）。
- **FR-10 断网 fail-closed**：keyserver 不可达/超时（5s）→ 拒绝运行，报「无法连接授权服务器，请检查网络后重试」；**禁止自动重试**（防 deduct 双扣）；URL 未配置 → 「授权服务器未配置」。
- **FR-11 URL 配置链**：env `MS_KEY_SERVER_URL` → frozen exe 旁 `key_server_url.txt` → 皆无 fail-closed；keyserver URL 永不出现在浏览器（前端只与同源 MS 后端通信，全链路无跨域）。
- **FR-12 token 鉴权（frp 修正）**：管理端 `X-Admin-Token`（`MS_KEY_ADMIN_TOKEN` 未设且无 `MS_KEY_DEV=1` → 403 拒绝服务，**无 loopback 兜底**）；消费端 `X-Client-Token`（`MS_KEY_CLIENT_TOKEN` 已设时强制）；`MS_KEY_DEV=1` 仅本机开发逃生。
- **FR-13 管理台操作**：新建（时长默认单位天/次数单位次）；编辑 = 改备注名 + 续期（次数加次数/时长加天数，保存即生效 —— 未激活加 `duration_days`、已激活直接延长 `expires_at`）；删除 = 过期/用完直接删、正在使用二段确认（force）。
- **FR-14 使用统计三指标**（管理台「使用统计」列，替换原「每日使用次数」单值）：**总使用次数** = SUM(每日次数)；**单日最高** = MAX(每日次数)；**平均每日** = 总次数 ÷ **开通以来自然日数**（自首次使用起至今天数，含首日，新 key 当天分母 = 1，保留 1 位小数）；数据全部由 `key_daily_usage` 全量历史聚合，无记录显示 `—`。
- **FR-15 CLI 豁免**：`ms-run-config` 直跑不闸（只管 web 三入口；web 的高级/极限正是 spawn CLI 跑，闸 CLI 会二次扣费；客户绕过风险靠发版不暴露 CLI 用法缓解，二期可补 `cli/run_config.py` 层闸门）。
- **FR-16 操作审计**：`key_op_log` 记录 create/bind/merge_source/merge_target/validate_deduct/renew/edit/delete 全操作轨迹。

## 非目标 (Non-Goals)

- HTTPS/TLS（frp 明文 HTTP 部署，残余风险备案，二期升级）
- keyserver 响应 HMAC 签名（防本地假服务器，二期）
- key 哈希化存储（仅创建时展示一次 + 库存 SHA-256，二期，切换成本已备案）
- CLI 层 key 闸门（二期，keygate 插入点已预留）
- 断网本地缓存宽限（需响应签名防伪造，二期）
- key 改绑功能（重装系统 MachineGuid 重铸的解法暂 = 删旧 key 重建，二期做管理端改绑）
- MySQL / 多实例部署（SQLite 单机足够，切换成本已备案：只换 `db.py`/`repo.py` 方言）
- 使用历史曲线可视化（`key_daily_usage` 已留全量数据，本期只展示三指标）
- 防二进制 patch 摘除闸门（本地 exe 无根除手段，不做）

## 设计考虑 (Design Considerations)

- 前端弹窗走 `controlPanelStore` 单例 modal 族（`'key_info'` additive，既有五值不变）；骨架镜像 ExportInfoModal（Portal + ESC/遮罩关闭）；样式沿用 `style.css` 新增 `.key-*` 前缀，**不引入 CSS 框架**；HTTP 一律走 `lib/api.ts apiFetch`（X-Session-Id + 会话先行门）。
- 弹窗短交互不需要 editHold 心跳（非编辑排料 30min 场景）。
- 管理台 `admin.html` 原生单页 + fetch + 内联 CSS，独立于 materialSorting-web Vite 链；token 登录框存 sessionStorage；`/admin` 页与 keyserver 同源无跨域。
- 错误文案全部中文、面向用户（「该 key 已绑定其他系统，无法绑定到本机」等），前端透传不自行翻译。
- 使用统计一格三行紧凑呈现（`均 3.2/日 ｜ 峰 12 ｜ 共 45`）。

## 技术考虑 (Technical Considerations)

- **分层红线**：`web/keygate.py`/`web/routes_key.py` 禁 import `..cli.*` 与顶层 server（AST 守卫，镜像 `edit_hold.py`/`machine.py` 先例）；keyserver 是独立系统不依赖 materialsorting 包；对 `routes_views._sample_dxf_names` 走函数内延迟 import。
- **最高风险点**：strategy/extreme 闸门必须插在 `_cleanup_stale_web_artifacts`（strategy.py:951）**之前**——否则被拒 start 会先误删上一轮 run 产物；pytest 显式断言「被拒 start 不删旧产物不 spawn」。
- **strategyStore 是两族共用工厂**（createRunStore :109，strategy :211 / extreme :214）——前端拦截一处插入双族生效，勿重复插。
- **冻结面**：keygate 仅标准库（urllib/winreg）零新增 pip 依赖；frozen 环境经 launcher `apply_frozen_env` 注入；Nuitka 下 winreg/urllib 行为需 US-009 实测。
- **并发**：SQLite WAL + busy_timeout=5000，uvicorn 单 worker（规模 = 客户机数）；扣次单条原子 SQL 不依赖读-改-写。
- **既有测试零漂移**：`MS_KEY_MODE=off`（仅非 frozen）或 conftest monkeypatch `ensure_run_allowed → (True,'')`。
- **决策台账（2026-09-28 定案）**：FastAPI+SQLite 同仓 keyserver/ ｜ 启动即扣预扣不退 ｜ 绑定激活计时 ｜ fail-closed ｜ 合并标记保留 ｜ 六态上屏 ｜ 系统名=hostname ｜ CLI 豁免 ｜ MS-XXXXX 格式 ｜ 明文入库 ｜ frp 双 token 强制（loopback 兜底失效修正）｜ 超时 5s 禁重试 ｜ 统计三指标（平均 ÷ 开通以来天数）｜ localStorage 镜像 + 后端权威 ｜ 全链路无跨域。
- keyserver 部署：frp 内网穿透暴露公网（frpc 与 keyserver 同机），SQLite 文件 + 定期快照备份进 runbook。

## 成功指标 (Success Metrics)

- [ ] 未绑 key 时三入口（普通/高级/极限）全部被拒且中文报错，被拒 start 不删旧产物不 spawn（pytest 断言）
- [ ] 20 线程并发 validate 对 total=5 恰 5 过 15 拒，`used_uses` 终值 5（零超扣）
- [ ] 样例载入三入口免闸跑通；`/api/machine/solve` 在 keygate 异常时仍 202（豁免回归锁）
- [ ] 合并后 target 截止时间增量 = source 剩余时长（秒级对拍），source 状态 = 已合并保留
- [ ] frozen exe 实测全过：key_server_url.txt 生效 / LOCALAPPDATA 落盘 / winreg 成功 / MS_KEY_MODE=off 失效
- [ ] `smoke_key_gate.mjs` 全链路绿 + `npm run build` 后 :8010 生产 bundle 含新代码
- [ ] 全量 pytest 回归零漂移；keyserver 自有 pytest 全绿

## 待确认问题 (Open Questions)

无 —— 全部决策已于 2026-09-28 会话闭环（见「技术考虑」决策台账）；二期候补项见「非目标」。
