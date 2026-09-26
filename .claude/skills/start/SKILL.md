---
name: start
description: 启动（或重启）MaterialSorting 项目：后端 ms-web (:8010) + 前端 Vite dev (:5173)。支持 dev/prod 模式、单端启动、重启。改后端 Python 后可自动触发重启；dev 启动时自动检测并重建过期的 static/（用户常用 :8010 生产包入口）。
allowed-tools: Bash
---

# Start / Restart Skill

## 上下文
- 项目根：`d:/code/MaterialSorting`
- 后端：`ms-web`（console script → `materialsorting.web.server:main` → uvicorn `127.0.0.1:8010`）。路由：`GET /` 出 `static/index.html`、`POST /export`、`WS /ws/solve`、`/static/*`。**cwd 无关**（`paths.py` 按包位置自定位，不要 cd）。**未开 `--reload`**，改 Python 代码后必须重启才生效。
- 前端 dev：`cd materialSorting-web && npm run dev`（Vite `:5173` strictPort，proxy `/export` + `/ws` → :8010，自带 HMR）。
- 前端 prod：`cd materialSorting-web && npm run build` → `static/`，由后端 `/` 与 `/static` 同源 serve（无独立前端进程）。
- 启动顺序：dev/prod 都需 `pieces_intermediate.json` 存在（server.py 模块顶层读）；dev 模式前端需后端 :8010 先起。

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
- `pieces_intermediate.json` 建议存在（缺失时 server.py 启动 allow-empty，`_PIECES_STATE={}` 不崩，但 `/api/ptypes` 返空、`/ws/solve` 报「排料数据为空」）：
  ```bash
  test -f d:/code/MaterialSorting/materialSorting-server/out/sparrow_baseline/pieces_intermediate.json && echo OK || echo MISSING
  ```
  MISSING → 提示用户 intermediate 由 Web 上传母版 commit 生成（启动后在前端上传一次母版即可），**不阻塞后端启动**。
- prod 模式且目标含 frontend：先 `cd d:/code/MaterialSorting/materialSorting-web && npm run build`。build 失败（tsc 报错）→ 报错给用户，**不启后端**。
- **dev 模式也做 static/ 过期检测并按需 rebuild**（用户浏览器日常入口常是 :8010 生产包，Vite HMR 只覆盖 :5173；static/ 是 gitignored 构建产物，**永不自动刷新** —— 2026-09-26「用时显示」功能在 :5173 验证全绿但用户 :8010 看不到，即此坑）：
  ```bash
  cd d:/code/MaterialSorting/materialSorting-web
  if [ ! -f static/index.html ] || [ -n "$(find src -newer static/index.html -print -quit 2>/dev/null)" ]; then
    npm run build
  fi
  ```
  static/ 缺失或 src/ 有更新文件 → rebuild（~几秒）；build 失败**不阻塞** dev 启动（:5173 入口不依赖 static/），但步骤 4 汇报必须注明「:8010 仍是旧包」。

### 1. 探测现状，决定是否先停
```bash
netstat -ano | grep -E ":8010[[:space:]]" | grep -qi LISTENING && echo BE_UP || echo BE_DOWN
netstat -ano | grep -E ":5173[[:space:]]" | grep -qi LISTENING && echo FE_UP || echo FE_DOWN
```
- 动作 = `restart`：把目标端中 UP 的全部杀掉（用下方 kill 命令），再进入步骤 2/3。
- 动作 = `start`（默认）：**不杀**。目标端 UP 的跳过（仅报「已在运行」），只启动 DOWN 的端口。避免误杀用户外部起的服务。

kill 单端口（按需，PORT ∈ {8010, 5173}）：
```bash
for pid in $(netstat -ano | grep -E ":PORT[[:space:]]" | grep -i LISTENING | awk '{print $NF}' | sort -u); do
  MSYS_NO_PATHCONV=1 taskkill /PID $pid /F /T 2>/dev/null && echo "killed $pid"
done
```

### 2. 启动后端（dev/prod 都要；目标含 backend 时）
- `ms-web` 前台阻塞，**必须**用 Bash 工具 `run_in_background: true` 起：
  ```bash
  ms-web
  ```
  （若 `ms-web` 不在 PATH，退回 `d:/code/MaterialSorting/.venv/Scripts/python.exe -m materialsorting.web.server`；裸 `python` 撞 Store 别名勿用）
- 轮询确认起来：
  ```bash
  for i in $(seq 1 15); do netstat -ano | grep -E ":8010[[:space:]]" | grep -q LISTENING && { echo "backend up"; break; }; sleep 1; done
  ```
  15s 内没起来 → 读后台任务输出报错（多半是 intermediate 缺失 / 端口占用 / 依赖未装 `[web]`）。

### 3. 启动前端（**仅 dev 模式**且目标含 frontend 时）
- Vite 前台阻塞，`run_in_background: true` 起：
  ```bash
  cd d:/code/MaterialSorting/materialSorting-web && npm run dev
  ```
- 轮询 `:5173` LISTENING（同上，把 8010 换 5173）。prod 模式跳过此步。

### 4. 汇报
```
✅ 项目已启动（dev）
  后端 ms-web      :8010   http://127.0.0.1:8010/   (PID ...)
  前端 Vite dev    :5173   http://localhost:5173/    (PID ...)
  static/          已重建，:8010 入口同步最新        ← 或「无需重建（src 无新改动）」/「重建失败，:8010 仍是旧包」
  打开 → http://localhost:5173/   （:8010 入口亦可，两者均为最新代码）
```
prod 模式只报后端行与 static/ 行，`打开 → http://127.0.0.1:8010/`。PID 用步骤 2/3 起来后复探 netstat 取。

## 何时自动触发（Claude 自调用，无需用户输入）
- 改了后端 Python 代码后（uvicorn 无 `--reload`）→ 自动 `/start restart backend` 让改动生效。
- 改前端代码**不需要**重启 Vite（HMR 自动热更），但 **HMR 只覆盖 :5173 —— 用户浏览器常用入口是 :8010 的生产包（static/ 构建产物，gitignored，永不自动刷新）**。前端改动收尾时（或用户反馈「界面上没变化」时，第一 suspects 就是 static/ 旧包）：
  1. `cd materialSorting-web && npm run build` 重建 static/；
  2. `curl -s http://localhost:8010/ | grep -o 'index-[^"]*\.js'` 拿新 bundle 名后 `curl -s http://localhost:8010/static/assets/<bundle>.js | grep "<本次新增文案>"` 验证生产包已含新代码；
  3. 提醒用户强刷（Ctrl+Shift+R）。
- 仅当改 `vite.config.ts` / 装新依赖后才 `/start restart frontend`。

## 注意事项
- 后台进程随当前 Claude 会话存活（Bash 后台任务）；关掉 Claude 即停。要脱离会话长驻请用户外起。
- 一律 `run_in_background: true`，**绝不**前台跑 `ms-web` / `npm run dev`（会阻塞会话）。
- Vite strictPort：5173 已被占时第二次起会直接失败 → 所以「已在运行就跳过」很重要。
- prod 模式 `npm run build` 产出 `materialSorting-web/static/`；后端 `MS_STATIC_DIR` 默认就指这里，无需额外环境变量。
