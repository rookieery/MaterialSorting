---
name: start
description: 启动（或重启）MaterialSorting 项目：后端 ms-web (:8000) + 前端 Vite dev (:5173)。支持 dev/prod 模式、单端启动、重启。改后端 Python 后可自动触发重启。
allowed-tools: Bash
---

# Start / Restart Skill

## 上下文
- 项目根：`d:/code/MaterialSorting`
- 后端：`ms-web`（console script → `materialsorting.web.server:main` → uvicorn `127.0.0.1:8000`）。路由：`GET /` 出 `static/index.html`、`POST /export`、`WS /ws/solve`、`/static/*`。**cwd 无关**（`paths.py` 按包位置自定位，不要 cd）。**未开 `--reload`**，改 Python 代码后必须重启才生效。
- 前端 dev：`cd materialSorting-web && npm run dev`（Vite `:5173` strictPort，proxy `/export` + `/ws` → :8000，自带 HMR）。
- 前端 prod：`cd materialSorting-web && npm run build` → `static/`，由后端 `/` 与 `/static` 同源 serve（无独立前端进程）。
- 启动顺序：dev/prod 都需 `pieces_intermediate.json` 存在（server.py 模块顶层读）；dev 模式前端需后端 :8000 先起。

## 端口 → PID 探测（Windows Git Bash）
```bash
# 返回监听 <PORT> 的 PID（IPv4 127.0.0.1:PORT / IPv6 [::1]:PORT 都能命中；可能多行或空）
netstat -ano | grep -E ":<PORT>[[:space:]]" | grep -i LISTENING | awk '{print $NF}' | sort -u
```

## 解析意图（从用户消息 / args）
- 目标端：`backend` / `frontend` / `all`（默认 `all`）
- 模式：`dev`（默认）/ `prod`
- 动作：`start`（默认）/ `restart`（= 先停目标端再起）

## 执行步骤

### 0. 前置检查
- `pieces_intermediate.json` 必须存在（否则 server.py 顶层 `load_pieces()` 直接抛错）：
  ```bash
  test -f d:/code/MaterialSorting/materialSorting-server/out/sparrow_baseline/pieces_intermediate.json && echo OK || echo MISSING
  ```
  MISSING → 提示用户先 `ms-pieces-export`，**不要继续启动后端**。
- prod 模式且目标含 frontend：先 `cd d:/code/MaterialSorting/materialSorting-web && npm run build`。build 失败（tsc 报错）→ 报错给用户，**不启后端**。

### 1. 探测现状，决定是否先停
```bash
netstat -ano | grep -E ":8000[[:space:]]" | grep -qi LISTENING && echo BE_UP || echo BE_DOWN
netstat -ano | grep -E ":5173[[:space:]]" | grep -qi LISTENING && echo FE_UP || echo FE_DOWN
```
- 动作 = `restart`：把目标端中 UP 的全部杀掉（用下方 kill 命令），再进入步骤 2/3。
- 动作 = `start`（默认）：**不杀**。目标端 UP 的跳过（仅报「已在运行」），只启动 DOWN 的端口。避免误杀用户外部起的服务。

kill 单端口（按需，PORT ∈ {8000, 5173}）：
```bash
for pid in $(netstat -ano | grep -E ":PORT[[:space:]]" | grep -i LISTENING | awk '{print $NF}' | sort -u); do
  MSYS_NO_PATHCONV=1 taskkill //PID $pid //F //T 2>/dev/null && echo "killed $pid"
done
```

### 2. 启动后端（dev/prod 都要；目标含 backend 时）
- `ms-web` 前台阻塞，**必须**用 Bash 工具 `run_in_background: true` 起：
  ```bash
  ms-web
  ```
  （若 `ms-web` 不在 PATH，退回 `python -m materialsorting.web.server`）
- 轮询确认起来：
  ```bash
  for i in $(seq 1 15); do netstat -ano | grep -E ":8000[[:space:]]" | grep -q LISTENING && { echo "backend up"; break; }; sleep 1; done
  ```
  15s 内没起来 → 读后台任务输出报错（多半是 intermediate 缺失 / 端口占用 / 依赖未装 `[web]`）。

### 3. 启动前端（**仅 dev 模式**且目标含 frontend 时）
- Vite 前台阻塞，`run_in_background: true` 起：
  ```bash
  cd d:/code/MaterialSorting/materialSorting-web && npm run dev
  ```
- 轮询 `:5173` LISTENING（同上，把 8000 换 5173）。prod 模式跳过此步。

### 4. 汇报
```
✅ 项目已启动（dev）
  后端 ms-web      :8000   http://127.0.0.1:8000/   (PID ...)
  前端 Vite dev    :5173   http://localhost:5173/    (PID ...)
  打开 → http://localhost:5173/
```
prod 模式只报后端行，`打开 → http://127.0.0.1:8000/`。PID 用步骤 2/3 起来后复探 netstat 取。

## 何时自动触发（Claude 自调用，无需用户输入）
- 改了后端 Python 代码后（uvicorn 无 `--reload`）→ 自动 `/start restart backend` 让改动生效。
- 改前端代码**不需要**重启（Vite HMR 自动热更）；仅当改 `vite.config.ts` / 装新依赖后才 `/start restart frontend`。

## 注意事项
- 后台进程随当前 Claude 会话存活（Bash 后台任务）；关掉 Claude 即停。要脱离会话长驻请用户外起。
- 一律 `run_in_background: true`，**绝不**前台跑 `ms-web` / `npm run dev`（会阻塞会话）。
- Vite strictPort：5173 已被占时第二次起会直接失败 → 所以「已在运行就跳过」很重要。
- prod 模式 `npm run build` 产出 `materialSorting-web/static/`；后端 `MS_STATIC_DIR` 默认就指这里，无需额外环境变量。
