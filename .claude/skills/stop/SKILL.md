---
name: stop
description: 停止 MaterialSorting 运行中的服务：后端 ms-web (:8000) 与/或 前端 Vite dev (:5173)。按端口探测 PID 后 taskkill，不依赖记忆 PID。
allowed-tools: Bash
---

# Stop Skill

## 上下文
- 后端监听 :8000（`ms-web`，python/uvicorn 进程）；前端 dev 监听 :5173（Vite node 进程）。
- **prod 模式无独立前端进程**（前端由后端静态 serve），停后端即等于全停；停 all 时 :5173 显示「未运行」属正常。
- 服务可能由 `/start` 后台起，也可能由用户外部起；**一律按端口现探 PID**，不依赖上次记忆的 PID（skill 无状态）。

## 端口 → PID 探测（Windows Git Bash）
```bash
netstat -ano | grep -E ":<PORT>[[:space:]]" | grep -i LISTENING | awk '{print $NF}' | sort -u
```

## 解析意图（从用户消息 / args）
- 目标端：`backend` / `frontend` / `all`（默认 `all`）
- backend → PORT=8000；frontend → PORT=5173

## 执行步骤
1. 对每个目标端口取监听 PID 并 `taskkill`（杀进程树，覆盖 `npm run dev` → vite 父子）：
   ```bash
   # 以 backend (:8000) 为例；前端把 8000 换成 5173
   pids=$(netstat -ano | grep -E ":8000[[:space:]]" | grep -i LISTENING | awk '{print $NF}' | sort -u)
   if [ -n "$pids" ]; then
     for pid in $pids; do MSYS_NO_PATHCONV=1 taskkill //PID $pid //F //T 2>/dev/null && echo "killed $pid"; done
   else
     echo "(后端未运行)"
   fi
   ```
2. 复探端口确认无 LISTENING 残留：
   ```bash
   netstat -ano | grep -E ":8000[[:space:]]" | grep -qi LISTENING && echo "STILL_UP" || echo "CLEAN"
   ```
   `STILL_UP` → 再 kill 一次；仍杀不掉就照实报权限错误。
3. 汇报：
   ```
   🛑 已停止
     后端  :8000   killed PID ...      （或：未运行）
     前端  :5173   killed PID ...      （或：未运行）
   ```

## 何时自动触发（Claude 自调用，无需用户输入）
- 长跑的后台求解/WS 任务占着 :8000 需要释放时。
- 配合 `/start restart`：restart 的「停」这一半复用本 skill 逻辑（实际由 start skill 内联执行，不必先调本 skill 再调 start）。

## 注意事项
- **`MSYS_NO_PATHCONV=1` + `//PID //F //T`**：Git Bash 会把 `/PID` 当 POSIX 路径吞掉导致参数丢失，必须双斜杠 `//PID` 或前置该 env。`//F` 强制结束、`//T` 连子进程一起杀。
- 杀不掉（权限不足 / PID 已退出）时 `taskkill` 会报错，**照实报给用户**，不要假装成功。
- 不要碰非 8000/5173 的端口；只杀这两个端口的监听进程。
