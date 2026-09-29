---
name: start-keyserver
description: 启动（或重启）keyserver Key 授权服务（:8110）。支持 dev（MS_KEY_DEV=1 免 token，默认）/ prod（双 token 生产姿态）两档；起后 curl /api/key/health 验证并汇报管理后台入口 http://127.0.0.1:8110/admin。
allowed-tools: Bash
---

# Start / Restart keyserver Skill

## 上下文
- 项目根：`D:/code/MaterialSorting`；服务 = `keyserver/` 包（prd-key-authorization-system），editable 安装在 repo 根 `.venv`。
- 可执行：`D:/code/MaterialSorting/.venv/Scripts/ms-keyserver.exe`（等价 `python -m keyserver.app`；裸 `python` 撞 Store 别名勿用）。
- 缺省监听 `127.0.0.1:8110`（`MS_KEY_PORT` / `MS_KEY_HOST` 可覆盖）；SQLite 账本缺省 `keyserver/data/keys.db`（启动幂等建表，`MS_KEY_DB` 可覆盖）。
- 路由速查：`GET /api/key/health`（免鉴权探活）、`GET /admin`（管理后台单页，公开壳）、`/api/admin/*`（X-Admin-Token）、`/api/key/{bind,merge,info,validate}`（X-Client-Token，MS 工作台 keygate 消费）。
- 详尽契约：`keyserver/AGENTS.md` + `.docs/technical/本地部署构建与发版手册.md` §7。

## 解析意图（从用户消息 / args）
- 动作：`start`（默认）/ `restart`（先停再起）。
- 姿态：`dev`（默认）/ `prod`。
- 可选覆盖：端口（`port=8120` 之类）/ DB 路径（`db=<路径>`）。

## 执行步骤

### 0. 探活，决定是否先停
```bash
curl -s -m 3 http://127.0.0.1:8110/api/key/health || echo __NOT_RUNNING__
```
- 已在运行且动作 = `start` → **不重启**，直接汇报「已在运行」+ health 返回的 DB 路径。
- 已在运行且动作 = `restart` → 先按 `/stop-keyserver` 的 kill 逻辑停掉再起。
- 自定义端口时把 8110 换成对应值。

### 1. 组装环境变量
- **dev（默认）**：`MS_KEY_DEV=1` —— 双 token 免设即放行，管理台免登录直进主界面；**仅本地调试**。
- **prod**：必须向用户要 `MS_KEY_ADMIN_TOKEN` + `MS_KEY_CLIENT_TOKEN` 两个口令（消息里给了就直接用；没给就先问，不要自造秘密）；`MS_KEY_DEV` 绝不设。prod 起法：
  ```bash
  MS_KEY_ADMIN_TOKEN=<管理口令> MS_KEY_CLIENT_TOKEN=<消费口令> \
    MS_KEY_PORT=8110 MS_KEY_DB=D:/code/MaterialSorting/keyserver/data/keys.db \
    "D:/code/MaterialSorting/.venv/Scripts/ms-keyserver.exe"
  ```
- DB 缺省路径无需显式设（editable 安装落 `keyserver/data/keys.db`）；用户点名别的路径才加 `MS_KEY_DB`。

### 2. 后台启动
uvicorn 前台阻塞，**必须**用 Bash 工具 `run_in_background: true`：
```bash
MS_KEY_DEV=1 MS_KEY_PORT=8110 "D:/code/MaterialSorting/.venv/Scripts/ms-keyserver.exe"
```

### 3. 轮询验证
```bash
for i in $(seq 1 10); do
  curl -s -m 3 http://127.0.0.1:8110/api/key/health && break; sleep 1
done
```
- 期望 `{"ok":true,"service":"keyserver","db":...}`；10s 没起来 → 读后台任务输出报错（多半端口被占 / venv 里 keyserver 未 `pip install -e keyserver`）。
- 顺手验一嘴管理台：`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8110/admin` → 200。

### 4. 汇报
```
✅ keyserver 已启动（dev）
  监听   127.0.0.1:8110
  DB     keyserver/data/keys.db（新建/沿用）
  管理后台 → http://127.0.0.1:8110/admin   （dev 免 token 直进；prod 登录框输 MS_KEY_ADMIN_TOKEN）
```
prod 多报一行「双 token 已生效；MS 工作台客户机需配同值 MS_KEY_CLIENT_TOKEN / key_client_token.txt」。

## 注意事项
- 后台进程随当前 Claude 会话存活；要脱离会话长驻（frp 现场）请用户外起，别用本 skill。
- prod 姿态下双 token 任一未设且无 DEV → 对应端点族 403「未配置」，管理台首查会渲染配置指引 —— 这不是 bug，是提示 token 没带上。
- 重启 = 数据不丢（SQLite 落盘），只是进程换新；勿顺手删 `keys.db`。
