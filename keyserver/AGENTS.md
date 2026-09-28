# keyserver/ — Key 授权后台管理系统（AGENTS 速查）

> prd-key-authorization-system 服务端。**独立系统：禁 import materialsorting**
> （AST 守卫 `tests/test_repo.py::test_keyserver_never_imports_materialsorting`
> + 行为锁 `tests/test_app.py::test_module_import_does_not_pull_materialsorting`
> 子进程双验）。与消费端只经 HTTP 通信（US-004 起 `web/keygate.py` 是唯一客户端）。

## 开发与测试

```bash
# 安装（与 materialsorting 共用 repo 根 .venv 开发，但零 import 依赖）
.venv/Scripts/python.exe -m pip install -e keyserver

# 跑 keyserver 自有 pytest（46 例；勿在部署目录留真实 data/keys.db —— conftest
# 每用例把 MS_KEY_DB 指到 tmp_path）
cd keyserver && ../.venv/Scripts/python.exe -m pytest

# 起服务（等价：ms-keyserver / python -m keyserver.app）
MS_KEY_PORT=8110 MS_KEY_DB=<路径> .venv/Scripts/ms-keyserver.exe
curl http://127.0.0.1:8110/api/key/health   # → {"ok":true,"service":"keyserver","db":...}
```

## 环境变量

| 变量 | 缺省 | 说明 |
|------|------|------|
| `MS_KEY_DB` | `<keyserver/>/data/keys.db` | SQLite 账本路径（部署目录 = 包上溯两级；**非 editable 安装形态必须显式设**） |
| `MS_KEY_HOST` | `127.0.0.1` | frp 同机部署形态 frpc 打 127.0.0.1，不裸露 LAN |
| `MS_KEY_PORT` | `8110` | 监听端口 |
| `MS_KEY_ADMIN_TOKEN` / `MS_KEY_CLIENT_TOKEN` / `MS_KEY_DEV` | 未设 | US-002/003 接线（双 token 鉴权 + 本地开发逃生） |

## 模块职责与约定（US-001 起）

- `models.derive_status(row, now)` = **六态状态机单一真相源**（merged →
  exhausted → unbound → unactivated → expired → active，优先级即语义）。
  管理台属性列 / 消费端校验**共用**，别处禁另写状态 if 链。
- 到期/记账时间一律 `models.now()`（**keyserver 服务器时钟**，消费端时钟不可信）；
  落库格式 `TS_FORMAT = '%Y-%m-%d %H:%M:%S'`，自然日粒度 `ymd_of()`。
- `repo.py` 只做三表读写（业务规则在路由/service 层）；`update_key` 列白名单
  `UPDATABLE_COLUMNS`，key_plaintext/key_type/created_at 不可改。
- 写操作自带 commit；并发扣次要走单条原子 SQL（US-003），不做读-改-写。
- key 明文 `MS-XXXXX-XXXXX-XXXXX`（字母表 30 字符去 I/L/O/U/0/1，secrets 随机，
  库内明文存储 —— 哈希化二期备案）；`create_key` UNIQUE 冲突自动重试。
- `key_daily_usage`（PRIMARY KEY (key_id, ymd)）是使用统计唯一数据源；
  `usage_stats` 平均口径 = 总次数 ÷ 开通以来自然日数（含首日，FR-14）。

## 坑位留档

- git bash 的 `cd` 跨命令持久化：跑 keyserver 测试用
  `cd keyserver && ../.venv/.../pytest` 单命令完成，或绝对路径。
- Windows 下 `taskkill /F /T /PID` 杀 ms-keyserver 时要杀 exe 真实 PID
  （bash 后台 `$!` 是包装进程，不是服务进程；用 `Get-Process ms-keyserver` 反查）。
