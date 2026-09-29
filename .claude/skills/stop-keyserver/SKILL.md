---
name: stop-keyserver
description: 停止 keyserver Key 授权服务（:8110）。按端口 netstat 现探 PID 后 taskkill /F /T 杀真实服务进程，Get-Process ms-keyserver 兜底覆盖自定义端口；curl 复探确认停透，不依赖记忆 PID。
allowed-tools: Bash
---

# Stop keyserver Skill

## 上下文
- keyserver 监听 `127.0.0.1:8110`（`MS_KEY_PORT` 可改），进程名 `ms-keyserver.exe`（uvicorn 单 worker，无子进程树负担但照杀树无害）。
- 服务可能由 `/start-keyserver` 后台起，也可能用户外部起；**一律现探 PID**，不依赖上次记忆（skill 无状态）。
- **bash 后台 `$!` 是包装进程不是服务本体**（keyserver/AGENTS.md 坑位留档）—— 杀 netstat 探到的监听 PID 才是真身。

## 端口 → PID 探测（Windows Git Bash）
```bash
netstat -ano | grep -E ":8110[[:space:]]" | grep -i LISTENING | awk '{print $NF}' | sort -u
```

## 执行步骤
1. 按端口杀监听进程（杀进程树）：
   ```bash
   pids=$(netstat -ano | grep -E ":8110[[:space:]]" | grep -i LISTENING | awk '{print $NF}' | sort -u)
   if [ -n "$pids" ]; then
     for pid in $pids; do MSYS_NO_PATHCONV=1 taskkill /PID $pid /F /T 2>/dev/null && echo "killed $pid"; done
   else
     echo "(8110 无监听)"
   fi
   ```
2. **进程名兜底**（覆盖 `MS_KEY_PORT` 改过端口的实例；`tasklist //FI` 常空不可用，用 PowerShell）：
   ```bash
   for pid in $(powershell -NoProfile -Command "Get-Process ms-keyserver -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"); do
     MSYS_NO_PATHCONV=1 taskkill /PID $pid /F /T 2>/dev/null && echo "killed $pid"
   done
   ```
3. curl 复探确认停透：
   ```bash
   curl -s -m 3 http://127.0.0.1:8110/api/key/health && echo STILL_UP || echo CLEAN
   ```
   `STILL_UP` → 再 kill 一轮；仍杀不掉照实报权限错误。
4. 汇报：
   ```
   🛑 keyserver 已停止
     :8110   killed PID ...        （或：未运行）
   ```
   若进程名兜底杀到了非 8110 端口的实例，逐 PID 列出说明（自定义端口实例）。

## 注意事项
- **taskkill 斜杠写法二选一**：`MSYS_NO_PATHCONV=1` + 单斜杠 `/PID /F /T`，**或**双斜杠 `//PID //F //T`；**两者同用会打架**（env 禁转换后 `//PID` 被判非法参数静默失败）。本 skill 片段用前者。
- 杀不掉（权限不足 / PID 已退出）时 taskkill 报错，**照实报给用户**，不要假装成功。
- 只碰 keyserver（8110 监听者 + 名叫 ms-keyserver 的进程）；不要顺手杀 8010/5173（那是 `/stop` 管的 MaterialSorting 本体）。
- 停服不动 `keys.db`（SQLite 账本落盘，重启数据还在）。
