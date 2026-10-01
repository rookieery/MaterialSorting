# keyserver/ — Key 授权后台管理系统（AGENTS 速查）

> prd-key-authorization-system 服务端。**独立系统：禁 import materialsorting**
> （AST 守卫 `tests/test_repo.py::test_keyserver_never_imports_materialsorting`
> + 行为锁 `tests/test_app.py::test_module_import_does_not_pull_materialsorting`
> 子进程双验）。与消费端只经 HTTP 通信（US-004 起 `web/keygate.py` 是唯一客户端）。

## 开发与测试

```bash
# 安装（与 materialsorting 共用 repo 根 .venv 开发，但零 import 依赖）
.venv/Scripts/python.exe -m pip install -e keyserver

# 跑 keyserver 自有 pytest（188 例；勿在部署目录留真实 data/keys.db —— conftest
# 每用例把 MS_KEY_DB 指到 tmp_path）
cd keyserver && ../.venv/Scripts/python.exe -m pytest

# 起服务（等价：ms-keyserver / python -m keyserver.app）
MS_KEY_PORT=8110 MS_KEY_DB=<路径> .venv/Scripts/ms-keyserver.exe
curl http://127.0.0.1:8110/api/key/health   # → {"ok":true,"service":"keyserver","db":...}
# 管理后台单页（US-008）：浏览器开 http://127.0.0.1:8110/admin（登录框输 MS_KEY_ADMIN_TOKEN）
```

## 环境变量

| 变量 | 缺省 | 说明 |
|------|------|------|
| `MS_KEY_DB` | `<keyserver/>/data/keys.db` | SQLite 账本路径（部署目录 = 包上溯两级；US-008 修正 parents 错位 —— 原实现实际落 repo 根撞 materialsorting data/；**非 editable 安装形态必须显式设**） |
| `MS_KEY_HOST` | `127.0.0.1` | frp 同机部署形态 frpc 打 127.0.0.1，不裸露 LAN |
| `MS_KEY_PORT` | `8110` | 监听端口 |
| `MS_KEY_ADMIN_TOKEN` / `MS_KEY_CLIENT_TOKEN` / `MS_KEY_DEV` | 未设 | 双 token 鉴权 + 本地开发逃生（均已生效：ADMIN US-002 / CLIENT US-003）。任一未设置且无 DEV=1 → 对应端点族 403；已设置缺失/错 → 401；双 token 各管各族（admin token 打不开 consumer 五接口）。**无 loopback 放行**（frp 同机形态来源 IP 恒 127.0.0.1，兜底 = 公网裸奔） |

## 模块职责与约定（US-001 起）

- `models.derive_status(row, now)` = **六态状态机单一真相源**（merged →
  exhausted → unbound → unactivated → expired → active，优先级即语义）。
  管理台属性列 / 消费端校验**共用**，别处禁另写状态 if 链。
- 到期/记账时间一律 `models.now()`（**keyserver 服务器时钟**，消费端时钟不可信）；
  落库格式 `TS_FORMAT = '%Y-%m-%d %H:%M:%S'`，自然日粒度 `ymd_of()`。
- `repo.py` 只做四表读写（业务规则在路由/service 层）；`update_key` 列白名单
  `UPDATABLE_COLUMNS`，key_plaintext/key_type/created_at 不可改。
- 写操作自带 commit；**并发扣次只走 `repo.atomic_deduct_once`**（单条原子
  UPDATE `used_uses=used_uses+1 WHERE key_type='count' AND used_uses<total_uses`，
  rowcount 即判据），禁读-改-写（US-003 并发测试锁：20 线程 total=5 恰 5 成功）。
- `service.py`（US-003）= 消费端业务规则单一真相源（bind/merge/info/validate +
  list（US-011：`list_for_machine` 本机绑定行经 `derive_status == active` 六态过滤
  + key 明文 —— 消费端「系统可使用的key」表格数据源，只读不动账））；
  `routes_consumer.py` 只做入参形状校验 + `require_client_token`（镜像 admin
  姿态）。**`MSG_*` 中文文案被 US-004 keygate 原样透传给排料用户，改字即破坏
  消费端契约**（测试逐字锁定）。
- bind 语义：绑定即 `bound_system_name` 快照 + 备注缺省=系统名 + **duration 型
  立刻激活起算**；已绑本机幂等 200（不动库不重复审计）。merge 语义：前置
  （全 duration + 全绑本机 + 全有效 + target 不在 sources）**全过才动账**，
  source 去重保序防双计，秒级转移后置 merged_into_id 保留不物理删除。
- `TS_FORMAT` 落库秒级截断（无亚秒）→ 涉及「转移/激活时刻」的测试断言要留
  ≤1s 容差（test_service 秒级精确断言的区间写法）。
- key 明文 `MS-XXXXX-XXXXX-XXXXX`（字母表 30 字符去 I/L/O/U/0/1，secrets 随机，
  库内明文存储 —— 哈希化二期备案）；`create_key` UNIQUE 冲突自动重试。
- `key_daily_usage`（PRIMARY KEY (key_id, ymd)）是使用统计唯一数据源；
  `usage_stats` 平均口径 = 总次数 ÷ 开通以来自然日数（含首日，FR-14）。
- **业务错误一律 `errors.ApiError` → `{"error": 中文"}`**（US-002 起）：禁用
  FastAPI HTTPException（`{"detail":...}` 形状与 US-004 keygate 透传契约不符）；
  入参校验用 `dict = Body(...)` 手工校验（pydantic 自动 422 是英文+detail 形状）。
- 管理端接口（`routes_admin.py`，US-002 五接口 + 系统级两接口 2026-09-29）：
  `require_admin_token` 请求时读 env（`secrets.compare_digest` 常量时间）；
  `_positive_int` 显式排 bool（bool 是 int 子类会伪装 1）；delete 的 op_log 在
  物理删除**后**落账（repo.delete_key 先清既有日志，先写即被抹）；`?force=true`
  只认字面 true（1/yes/True 仍 409）；delete 尾部级联 `delete_system_if_orphaned`
  （该系统名下 key 全删 → bound_systems 行含备注连带清理）。
- **绑定系统名列表改版（2026-09-29）**：备注名 key 级 → **系统级**（`bound_systems`
  表只挂靠备注，行由 keys 按 `bound_system_name` 分组派生——派生行不落库）；
  `GET /api/admin/systems` 返回 `{system_name, remark, key_count, usage_stats}`
  （usage_stats = 名下全部未删除 key 逐日使用**合并日序列**同日相加后按 FR-14
  公式算，`_stats_from_daily` 与单 key 统计单一真相源；成员含已合并/已过期/已用完，
  未绑定不参与，不同机器同名合并一行）；`PUT /api/admin/systems/{name}` 改系统备注
  （系统名下无 key → 404；op_log=`edit_system_remark` key_id 悬空）。管理台新建
  表单不收备注名、key 表六列、key 弹窗只留续期；`POST keys` 可选 `remark` 与
  `PUT keys/{id}` 改备注接口**兼容保留**（UI 已不调用）；存量 keys.remark 不迁移。
- 管理台响应 `_summarize`：status=六态中文标签、detail=count `N/M` /
  duration 未激活 `N天` / 已激活 `起 ~ 止`、last_used_at=最近一条
  `validate_deduct` op_log 的 ts（2026-10-01「最新使用时间」列，`repo.last_used_at`
  零 schema 迁移读 op_log，从未使用 → null）；US-008 admin.html 直接渲染。

## 管理后台单页（US-008 + 绑定系统名列表改版）

- `src/keyserver/static/admin.html` = **公开壳**（GET /admin 无鉴权直出；不含任何
  敏感数据）：token 由登录框输入存 `sessionStorage['ms_admin_token']`，全部数据经
  `/api/admin/*` 携 `X-Admin-Token` 获取 —— 同源零跨域，不进 materialSorting-web
  Vite 构建链。**不进 Vite ≠ 不做 UI 验证**：浏览器验证脚本
  `materialSorting-web/scripts/us008_admin_verify.mjs`（模板 us007；起 双实例 ——
  主实例 ADMIN token+DEV（**勿设 MS_KEY_CLIENT_TOKEN**，DEV 免消费 token 供脚本
  bind/validate 造态仅在其未设时生效）、裸实例无 token 无 DEV —— 56/56 相位见
  脚本头注）。
- 页面结构（2026-09-29 改版；2026-10-01 key 表加「最新使用时间」列）：新建表单 =
  类型+数量（无备注名）；key 表**七列**
  （名称/绑定系统名/类型/详细信息/属性/最新使用时间/操作，行操作=续期+删除；
  最新使用时间 = 属性下一列，mono 渲染 last_used_at、从未使用显 —）；**绑定系统名列表
  表五列**（绑定系统名/备注名/key 数/使用统计/编辑）在 key 表下方；key 弹窗只留
  续期；系统备注独立小弹窗（系统名只读）。数据加载 `loadData()` 并行拉
  `/api/admin/keys` + `/api/admin/systems` 双表同刷（**改任一数据流都要走
  loadData，勿新起单表刷新** —— 遗留 loadKeys 引用曾致删除成功但行不消失）。
- 无 token 启动先**无凭探测**：403 且 error 含「未配置」→ 配置指引卡（双 token
  必设文案）；401 → 登录框；200（DEV）→ 直进主界面。登录后 401 同样**清
  sessionStorage 回登录框**（错 token 不留存）。
- `avg_daily` JSON 数字丢尾零（2.0 → 2）→ 页面 `Number(x).toFixed(1)` 恒显
  1 位小数（AC 口径「均 X.X/日」）。
- 删除流：行状态非「正在使用」**直删无弹窗**；正在使用 → 二段确认弹窗
  （`?force=true`）；竞态（加载后变 active）由后端 409 兜底转弹窗。删除成功后
  服务端级联清理无 key 系统行，UI 双表刷新自动消失。
- pyproject `[tool.setuptools.package-data]` 含 `static/*.html`（非 editable
  安装形态 GET /admin 也能出页）。

## 坑位留档

- git bash 的 `cd` 跨命令持久化：跑 keyserver 测试用
  `cd keyserver && ../.venv/.../pytest` 单命令完成，或绝对路径。
- Windows 下 `taskkill /F /T /PID` 杀 ms-keyserver 时要杀 exe 真实 PID
  （bash 后台 `$!` 是包装进程，不是服务进程；用 `Get-Process ms-keyserver` 反查）。
