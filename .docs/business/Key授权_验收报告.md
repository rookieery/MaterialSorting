# Key 授权系统 验收报告（prd-key-authorization-system US-010 收官）

> 2026-09-28 终稿。验收对象 = prd-key-authorization-system 全十故事（US-001 keyserver 骨架与发卡 / US-002 管理端 / US-003 消费端 / US-004 消费端闸门 / US-005 三入口后端闸门与双豁免 / US-006 Key 属性弹窗 / US-007 三入口前端拦截 / US-008 管理后台单页 / US-009 契约文档与冻结部署 / US-010 端到端冒烟与本报告）。
>
> **结论：accept** —— 四条验收标准全过：端到端冒烟 smoke_key_gate.mjs **48/48 PASS**（双 token 生产姿态 + :8010 生产 bundle，从用户主链路走完免闸→拦截→假 key→真 key→合并→运行→扣次→统计全相位，§1）；生产 bundle 含新代码且**全链路无跨域**（§1.1 A 相位）；本报告落盘含 **15 项决策台账**（§2）与**四开放决策切换成本备案表**（§3）；全量 pytest 通过（materialsorting **1326** + keyserver **158** + vitest **1289**，§4）。

## 0. 验收口径声明

| # | 事项 | 口径 |
|---|---|---|
| 1 | 入口姿态 | **用户入口 = :8010 生产构建**（materialSorting-web/static/ 为 npm run build 产物，bundle /static/assets/index-7EXlsdai.js）；dev:5173 通过不算数（US-010 AC#2 明文） |
| 2 | keyserver 姿态 | **双 token 生产姿态**：MS_KEY_ADMIN_TOKEN + MS_KEY_CLIENT_TOKEN 均设、无 MS_KEY_DEV 逃生（冒烟专用端口 :8130，避开缺省 8110 与常驻服务） |
| 3 | 环境隔离 | ms-web 以 MS_OUT_DIR 临时目录起服（隔离真实 out/ 事实源与 license/，env 值一律正斜杠）；keyserver SQLite 落同临时目录**每次重铸**（断言确定性：key_state/账本/上传产物每跑从零开始） |
| 4 | 扣次口径 | **扣次唯一锚点 = MS 后端 start 时刻**（validate deduct=true）；前端预检 / /api/key/precheck 恒 deduct=false 不动账。冒烟全程（建 4 key → 样例三入口 → 拦截三入口 → 假 key → 绑定 ×4 → 合并 → 换绑）只允许恰 1 次扣次（G 相位唯一真跑） |
| 5 | 密度口径 | 本报告不涉求解密度对比；key 相位断言全部针对授权状态机（六态/扣次/统计/账本），与业务求解正交 |

## 1. 端到端冒烟（materialSorting-web/scripts/smoke_key_gate.mjs，48/48 PASS）

运行时刻 2026-09-28 23:43:01（本地）。脚本自举双服务（keyserver :8130 + ms-web :8010 生产 bundle），Playwright Edge 通道 + addInitScript 预置 ms.tour.*（防 tour-overlay 拦截）+ fetch 包装日志（URL 计数断言 /start 零发出、precheck 回包捕获对拍豁免 reason）。前置自检：static/index.html 存在（build 产物）、:8010/:8130 空闲；退出码 0 = 全过。

### 1.1 相位证据表

| 相位 | 场景 | 检查数 | 关键证据 |
|---|---|---|---|
| T0 | 双 token 生产姿态 | 4 | 管理端无 token **401**（MS_KEY_ADMIN_TOKEN 强制）；消费端无 X-Client-Token **401**；带 token 过鉴权（404 key 不存在 = 已过 401 层）；count key 初始 **0/30 未绑定** |
| A | 生产 bundle 含新代码 | 4 | 首页引用生产 bundle（/static/assets/index-7EXlsdai.js）；bundle 含 /api/key/precheck（三入口预检）；含 key-info-*（Key 属性弹窗）；**不含** keyserver 端点/URL（MS_KEY_SERVER_URL、/api/key/bind、/api/key/validate 均缺席 —— keyserver 永不出现在浏览器，FR-11） |
| B | 样例载入免闸（三入口，全程未绑 key） | 10 | 样例应用 commit 完成（3069 生产样例）；B1 普通：#start → #stop 在场（进 WS running）→ 停止回非 running；B2 高级：202 起 worker + /api/strategy/start 恰 1 发 + 停止后结果态可读；B3 极限：同款 + /api/extreme/start 恰 1 发；**precheck 回包 reason=sample**（豁免判定序穿透预检，非仅行为放行） |
| C | 真实母版 + 未绑 key → 三入口全拦 | 10 | 样例字节改名上传（工单-US010-冒烟.dxf，basename 脱离 data/ 白名单 → 无样例豁免）；C1 普通：StatusLine + Toast 中文「未绑定授权 key…」+ #start 仍在场（**不进 WS**）；C2 高级 / C3 极限：弹窗红字 + **/start 零新发**（fetch 计数不变）；precheck 回包 ok:false 三入口文案逐字一致；precheck 计数恰 **+3** |
| D | 假 key 保存 | 1 | 输入 MS-FAKE-NOPE 保存 → 中文红字「**key 不存在：请检查输入是否正确**」（keyserver 404 透传，不落盘） |
| E | 真 key 绑定（时长型）+ 批量合并 | 10 | 两 source 预绑本机成功；时长 key 绑定**即激活**（生效时间在案 + 剩余 10 天）+「正在使用」徽标；批量合并明细两行（每 key 转移天数）+ 共转移 ~7 天 + **截止时间随合并延长**；keyserver 侧两 source 置「已合并」**保留不物理删除** + target「正在使用」 |
| F | 换绑次数型 key | 3 | 属性 总数/已用/剩余 = **30/0/30**；「正在使用」徽标；**localStorage ms_key 镜像双写**（值 === count key） |
| G | 绑定有效 key 后运行跑通 | 2 | 真实母版普通运行放行（#stop 在场 = 进 WS running）→ 停止回非 running |
| H | keyserver 侧断言（管理端 API） | 4 | count key 扣次**恰 +1**（used **1/30**，op_log 全程唯一一笔 validate_deduct）；状态「正在使用」；**使用统计 daily +1**（total=1 峰=1 均=1.0，first_used=2026-09-28）；时长 key 统计零记录（绑定/合并不动账） |

### 1.2 keyserver 账本对拍（冒烟临时 keys.db 直读）

| key | 类型 | 状态 | 账本字段 |
|---|---|---|---|
| MS-B5GH6-B6NQX-TESE9（source-a） | duration 3 天 | 已合并 | merged_into_id=3；merge_source remaining_seconds=259199.6（≈3 天） |
| MS-DQRQT-3TMDT-58CQ8（source-b） | duration 4 天 | 已合并 | merged_into_id=3；merge_source remaining_seconds=345599.6（≈4 天） |
| MS-5AH3K-SQ4HF-SH3VN（target） | duration 10 天 | 正在使用 | activated_at=2026-09-28 23:43:01（绑定即激活）；合并后 expires_at=2026-10-15 23:43:00（= 原 10 天 + 转移 604799.3s ≈ 7 天，merge_target op_log 在案） |
| MS-3GYQ8-97Q3F-9AR4Y（count） | count 30 次 | 正在使用 | used_uses=1（恰 +1）；bound_system_name=WIN-IFK0NK94CF8（hostname 快照）；key_daily_usage = {ymd:2026-09-28, count:1} |

### 1.3 冒烟脚本设计要点（后续维护者注）

- **停止时机等首帧**：高级/极限相位等待 strategy-big-density 出现 %（首帧 best_frame_s*.json 边车落盘）再点停止 —— starting 期停止无 run_dir，result 端点 409「运行未产出 run 目录」→ 前端结果态只剩常驻「正在读取运行结果…」占位（无「再次运行」出口），后续相位弹窗无法回配置态（首轮实勘）；有帧后停止 → result 回落 best_frame 边车，结果态完整可读。
- 样例豁免穿透用**样例字节改名上传**构造反例（basename 判定豁免，同名字节即无豁免 —— FR-9 已知边界：用户自传与样例同名文件同被豁免，接受并记录）。
- 服务树杀用 taskkill /F /T /PID（Node spawn 传参不受 Git Bash 路径改写影响；Bash 工具直呼 taskkill 会被 Git Bash 把 /F 改写成 F:/，须 cmd /c 包裹）。

## 2. 15 项决策台账（2026-09-28 会话定案，逐项落地证据）

| # | 决策 | 定案内容 | 落地位置 | 验收证据 |
|---|---|---|---|---|
| 1 | **FastAPI+SQLite 同仓 keyserver/** | 独立顶层系统（不依赖 materialsorting 包）：FastAPI + SQLite（WAL + busy_timeout 5s）、uvicorn 单 worker（规模 = 客户机数） | keyserver/src/keyserver/{app,db,repo,routes_admin,routes_consumer,models,errors}.py | 冒烟双服务自举（/api/key/health 探活）；keyserver pytest 158 |
| 2 | **启动即扣、预扣不退** | 扣次唯一锚点 = MS 后端 start 时刻（validate deduct=true）；前端预检恒 false；高级运行内多 seed/多轮/race 门杀/LNS 不重复扣；原子单条 SQL 防并发超扣 | web/keygate.py ensure_run_allowed ④；routes_ws.ws_solve / strategy._start_run 插入点 | 冒烟 H：全程恰 1 笔 validate_deduct（B/C 预检与拦截零扣次，F 换绑后 0/30 → G 真跑后 1/30）；pytest「20 线程并发 total=5 恰 5 过 15 拒」零超扣 |
| 3 | **绑定激活计时** | 时长型首次绑定系统时激活起算（activated_at=绑定时刻, expires_at=now+N 天）；后台创建不计时 | keyserver routes_consumer.bind | 冒烟 E：绑定即激活（生效时间在案 + 剩余 10 天）；账本 activated_at=23:43:01 |
| 4 | **fail-closed** | keyserver 不可达/超时/URL 未配置 → 一律拒绝运行（中文指路），绝不放行 | keygate MSG_NO_SERVER/MSG_UNREACHABLE + ensure_run_allowed | pytest test_web_keygate 两分支；us007 MODE=down 三入口断网文案逐字一致 |
| 5 | **合并标记保留** | 被合并 key 置 merged_into_id「已合并」保留在表格（审计可追），不物理删除 | keyserver repo.merge + 管理台列表 | 冒烟 E：两 source 已合并保留（账本 merged_into_id=3） |
| 6 | **六态上屏** | 正在使用/已过期/已用完/未绑定/未激活/已合并；derive_status 单一真相源，表格「属性」列与校验共用 | keyserver models.derive_status + static/admin.html BADGE_CLASSES | 冒烟四态实勘：未绑定（T0）/正在使用（E/F/H）/已合并（E）；管理台验证 40/40 |
| 7 | **系统名=hostname** | 绑定时 socket.gethostname() 快照（只读展示），备注名缺省 = 系统名、管理端可改 | keyserver routes_consumer.bind | 冒烟账本四 key bound_system_name=WIN-IFK0NK94CF8 |
| 8 | **CLI 豁免** | ms-run-config 直跑不闸（只管 web 三入口；web 的高级/极限正是 spawn CLI 跑，闸 CLI 会二次扣费） | keygate 不接入 cli 层；AST 守卫反向锁定（web/keygate.py 禁 import ..cli.*） | pytest AST 守卫；FR-15 二期可补 CLI 层闸门（见 §3 注） |
| 9 | **MS-XXXXX 格式** | MS-XXXXX-XXXXX-XXXXX，字母表 32 字符（去 I/L/O/U/0/1），约 74 bit 熵；UNIQUE 索引 + 冲突重试 | keyserver models 生成器 | 冒烟建 4 key 全部命中格式（MS-B5GH6-B6NQX-TESE9 等） |
| 10 | **明文入库** | key_plaintext 明文存储（需求「名称列=明文」必须可还原）；泄露止损 = 管理端删除 | keyserver db.keys.key_plaintext | 冒烟管理端 API 全程以明文寻址（建/查/合并/扣次断言） |
| 11 | **frp 双 token 强制** | 管理端 X-Admin-Token + 消费端 X-Client-Token 两族；未配置且无 MS_KEY_DEV=1 → 403 拒绝服务，**无 loopback 兜底**（frp 同机部署来源恒 127.0.0.1，放行 = 公网裸奔） | keyserver 鉴权层（secrets.compare_digest 常量时间）+ MS 侧 keygate 自动附头 | 冒烟 T0 三连；US-009 冻结实测 T0/T1 |
| 12 | **超时 5s 禁重试** | 单请求 5s 超时（KEY_HTTP_TIMEOUT_S=5.0）；无自动重试 —— deduct 响应丢失时服务端可能已扣次，重试会双扣 | keygate._key_post | pytest「无自动重试（恰 1 次请求）」+ keygate 冒烟 18 项 |
| 13 | **统计三指标（平均 ÷ 开通以来天数）** | 总次数 = SUM(每日)；单日最高 = MAX(每日)；平均每日 = 总次数 ÷ 开通以来自然日数（自首次使用起含首日，1 位小数；无记录 —） | keyserver repo.usage_stats + 管理台「使用统计」一格三行 | 冒烟 H：total=1 峰=1 均=1.0（当日开通分母 = 1）；us008 均 2.0/日·峰 2·共 2 对拍 |
| 14 | **localStorage 镜像 + 后端权威** | 后端 out/license/key_state.json 权威（机器级、原子写、重启不丢、后端闸门自用）+ 前端 localStorage ms_key 镜像预填（以后端对账为准） | keygate.save_key_state（tmp+os.replace 原子写）+ KeyInfoModal/keyStore | 冒烟 F：ms_key === count key；冒烟 ms_out/license/key_state.json 落盘在案 |
| 15 | **全链路无跨域** | keyserver URL 永不出现在浏览器（前端只与同源 MS 后端通信，keygate 服务端代理） | 前端零 keyserver 端点 + keygate._key_post 唯一 HTTP 出口 | 冒烟 A：bundle 三锚点缺席（MS_KEY_SERVER_URL / /api/key/bind / /api/key/validate） |

## 3. 四开放决策切换成本备案表（二期候补，本期非目标）

| # | 开放决策 | 现状与残余风险 | 切换成本备案 |
|---|---|---|---|
| 1 | **HTTPS/TLS** | frp 明文 HTTP 部署：公网嗅探可见 key 明文与流量；缓解 = key 绑 MachineGuid 后他机不可用 + 管理端删除止损（发版手册 §7.5 备案） | keyserver 侧换 TLS（frps transport.tlsServerName 或前置 caddy/nginx 终结）；**MS 侧零代码** —— key_server_url.txt 换 https:// 即可（urllib 原生支持，keygate 冻结面不动） |
| 2 | **keyserver 响应 HMAC 签名（防本地假服务器）+ 断网本地缓存宽限** | 本地 hosts 劫持 + 假 keyserver（需同时掌握 URL 与 client token）可伪造放行 | keyserver 响应加 HMAC 签名（共享密钥随部署下发）+ keygate 验签（hmac 为标准库，冻结面纯标准库红线不破）；断网宽限 = 验签通过的最后成功状态本地缓存 + 宽限窗口（依赖签名防伪造，二者捆绑交付） |
| 3 | **key 哈希化存储** | 库文件泄露即 key 明文泄露；现状止损 = 管理端删除 | keys 表加 SHA-256 列 + 创建时仅展示一次；keyserver 内部 bind/validate/info 改哈希索引查找（MS 侧 keygate 透传契约不变）；**管理列表「名称列=明文」需求冲突需产品决策**；存量明文迁移脚本一次性跑 |
| 4 | **MySQL / 多实例部署** | SQLite 单机（客户机数规模足够）；多实例/高可用不在本期 | 只换 keyserver db.py/repo.py 方言（SQL 参数风格 + 连接池）；扣次原子 SQL「UPDATE keys SET used_uses=used_uses+1 WHERE id=? AND used_uses<total_uses」在 MySQL 同语义；schema DDL 平移 |

> 注：另有二期候补 **CLI 层 key 闸门**（keygate 插入点已预留于 cli/run_config.py 层；本期靠发版不暴露 CLI 用法缓解）与 **key 改绑功能**（现阶段解法 = 删旧 key 重建，二期做管理端改绑），见 PRD「非目标」。

## 4. 测试与验证总表（全部 2026-09-28 执行）

| 套件 / 验证 | 结果 | 说明 |
|---|---|---|
| materialSorting-server pytest | **1326 passed** | 全量回归（含 keygate / routes_key / 三入口闸门「被拒不删旧产物不 spawn」/ 样例与 machine 族豁免回归锁 / AST 分层守卫） |
| keyserver pytest | **158 passed** | 发卡/绑定/合并/校验/扣次并发/统计/管理五接口/admin 单页 |
| materialSorting-web vitest | **1289 passed**（74 文件） | keyStore / keyGate / ControlPanel 拦截 / strategy·extreme store 拦截零 /start 等 |
| US-009 冻结部署验证（Nuitka frozen exe，双 token 生产姿态） | **19/19** | sidecar 双文件生效 / launcher --check 五行回显 / key_state 落 LOCALAPPDATA / winreg 真值 / **MS_KEY_MODE=off frozen 无效** |
| US-006 浏览器验证（us006_key_modal_verify.mjs） | **22/22** | Key 属性弹窗三区块 / 镜像对账 / 合并明细 |
| US-007 浏览器验证（us007_key_gate_verify.mjs） | **24/24**（+ MODE=down） | 三入口前端拦截 + 放行 + 断网文案一致 |
| US-008 浏览器验证（us008_admin_verify.mjs） | **40/40** | 管理后台单页全操作流 + keyserver 侧对拍 |
| US-010 端到端冒烟（本报告 §1） | **48/48** | 双 token 生产姿态 + :8010 生产 bundle 全链路 |

> 环境注记：US-010 验证期全量 pytest 曾间歇性段错误（不同测试轮换失败、隔离单跑恒绿、代码零改动）。排查锁定两残留 ms-web 进程（前故事验证遗留，非本故事产物）为环境干扰源，taskkill /F /T 清理后全量 **1326 一次性全绿**。

## 5. 复现命令与工件清单

```bash
# 前置：npm run build（生产 bundle）+ .venv 已装 keyserver 与 materialsorting（editable）
cd materialSorting-web && npm run build && cd ..
# 端到端冒烟（自举 keyserver :8130 双 token + ms-web :8010 生产构建，退出码 0 = 全过）
node materialSorting-web/scripts/smoke_key_gate.mjs
# 测试三套
cd materialSorting-server && ../.venv/Scripts/python.exe -m pytest -q        # 1326 passed
cd ../keyserver && ../.venv/Scripts/python.exe -m pytest -q                  # 158 passed
cd ../materialSorting-web && npx vitest run                                  # 1289 passed
```

冒烟工件（out/smoke_key_gate/，gitignore 区，验收时点留存）：

| 文件 | 内容 |
|---|---|
| report.txt / report.json | 48 项检查逐条 PASS 清单 + 运行元数据（时刻/端口/姿态） |
| 01-sample-run.png … 07-run-allowed.png | 各相位浏览器截图（样例免闸运行 / 三入口拦截 ×2 / 假 key 红字 / 合并结果 / 次数属性 / 放行运行） |
| keys.db | keyserver 冒烟账本（§1.2 对拍数据源：4 key + op_log 12 笔 + key_daily_usage 1 行） |
| ms_out/ | ms-web 临时 OUT_DIR（license/key_state.json 后端权威文件在案；跑完即证据，不触碰真实 out/） |
