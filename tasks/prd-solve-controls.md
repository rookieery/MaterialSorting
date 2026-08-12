# PRD: 超排页面求解控制按钮增强（停止 / 重新开始）

## 概述 (Overview)

在已落地的排料工作台（US-001~US-008 + US-015~US-024）基础上，为目前只有「开始求解」单一按钮的超排页面增加**求解过程控制能力**：求解运行中可**停止**（终止当前求解）、停止/出错/完成后可**重新开始**（清空旧帧、用相同或新参数发起新一次求解）。

本次为**前后端联动**改造，核心难点在后端：当前求解跑在 `ThreadPoolExecutor` 的 daemon 子线程里，`instance.solve()` 是 spyrrow 编译的 Rust 原生阻塞调用，**无法从 Python 侧中断**（全包无 cancel/abort/stop/pause API）。因此「停止」必须把求解从**线程模型改为进程模型**，靠 `multiprocessing.Process.terminate()` 做 OS 级回收；「重新开始」= stop 语义的清理 + 现有 start 逻辑的全新求解。

> **「暂停」明确不在本次范围**：sparrow 无 checkpoint/resume 能力，真暂停技术上不可能；伪暂停（冻结前端显示但后端继续烧 CPU）有误导性，对版师无实际价值。详见非目标 NG-1。

## 目标 (Goals)

- **停止求解**：求解运行中点「停止」，后端求解进程在 2s 内被 OS 终止（任务管理器不再占 CPU），前端冻结在已收到的最后一帧，WS 关闭。
- **重新开始**：停止 / 出错 / 完成后，点「重新开始」清空旧帧、用上次参数（或用户改后的新参数）发起一次全新求解；语义上等价于 stop + start。
- **资源不泄漏**：反复 stop+restart 10 次不堆积进程/线程；WS 客户端意外断开时后端正确终止求解进程，不遗留孤儿进程。
- **保留中间方案可导出**：停止后已收帧保留，导出可用（导出的是停止时刻的最优中间方案，状态行明确提示）。
- **沿用现有不变量**：density 双口径（frame/final 的 `density` 仍是原面积口径，`density_sparrow` 为 spyrrow 自报）、多 seed 并发公平性（进程模型下 OS 调度仍同等竞争，排名仍公平）、`scale(1,-1)` 翻转、`paths.py` 集中路径、分层依赖不反向、导出走 R12+POLYLINE。

## 前置调研结论（关键技术事实，已查证）

| # | 事实 | 证据 |
|---|---|---|
| F1 | spyrrow 编译为 Rust `.pyd`，**无任何中断/暂停 API** | `.venv/Lib/site-packages/spyrrow/` 全目录 grep `cancel\|abort\|stop\|interrupt\|pause\|kill\|terminate` = 0 匹配；`__init__.pyi` 的 `solve(config, progress)` 无取消参数，`ProgressQueue` 仅只读 `drain()`，`StripPackingConfig` 无取消令牌（`early_termination` 仅指算法收敛后提前结束，非外部取消） |
| F2 | Python `threading.Thread` **无法安全终止**原生代码线程 | 当前 `solver.py:200` `threading.Thread(target=_solve, daemon=True)`；`daemon=True` 仅影响主进程退出时是否等待，不改变线程不可终止性；`PyThreadState_SetAsyncExc` 对持有 GIL 的 Rust 扩展不安全 |
| F3 | `Process.terminate()` 是终止原生求解器的**唯一可靠方式** | Windows 上调用 `TerminateProcess()`，OS 直接回收内存/CPU/句柄 |
| F4 | spyrrow 对象**不可 pickle** | `instance`/`config` 是 Rust 对象，无法跨进程传递 → `build_instance` 必须移入子进程内执行，只把 JSON 可序列化的 pid_meta / total_area / n_eroded / frame / final 传回主进程 |
| F5 | 当前 WS `/ws/solve` 是「client 发首条且仅一条 `{action:'start'}`，之后纯 server→client 单向推」 | `agent-api-reference.md` WS 章节 + `server.py` ws_solve 只在开头 `receive_json()` 一次 |
| F6 | 当前客户端断开被静默忽略，求解线程仍跑完 | `server.py` ws_solve 的 `except Exception: pass` 分支，求解占用线程池槽位直到 `total_computation_time` 跑完（默认 120s，最长 600s+） |

## 用户故事 (User Stories)

### US-025: 后端求解进程化（solve_worker + solve_with_callback_proc）
- **Description**: As a 后端开发者, I want 把求解从 daemon 线程模型改为 multiprocessing.Process 模型，让调用方拿到进程句柄可 `terminate()`, so that 后续 WS 才能真正停止一个运行中的求解而不是干等它跑完。
- **Acceptance Criteria**:
  1. 新建 `materialSorting-server/src/materialsorting/web/solve_worker.py`：顶层函数 `solve_worker(pieces_snapshot, gate_mm, solve_params, result_queue)`（**顶层、无闭包，Windows spawn 可 pickle**）。子进程内：调 `build_instance(pieces_snapshot, gate_mm, **solve_params)` 构造 spyrrow 对象 → 首条向 `result_queue` 投递 `{kind:'manifest', pid_meta, total_area, n_eroded, gate_mm}` → `instance.solve(config, progress=ProgressQueue)` → 每个 drain 出的中间报告投递 `{kind:'frame', report}` → 末尾投递 `{kind:'final', final}` 或 `{kind:'error', message}`。所有投递内容为纯 JSON 可序列化（dict/list/float/int/str），**spyrrow 对象绝不跨进程**。
  2. `materialSorting-server/src/materialsorting/web/solver.py` 新增 `solve_with_callback_proc(pieces_snapshot, gate_mm, solve_params, *, on_manifest, on_report, drain_interval=0.2)`：创建 `multiprocessing.Process(target=solve_worker, args=(...))` + `multiprocessing.Queue()`；父进程循环 `while process.is_alive(): result_queue.get(timeout=drain_interval)` 分发：`manifest`→`on_manifest(...)`、`frame`→`on_report(...)`、`final`/`error`→记录并退出；返回 `(process, final_data, elapsed, err)`，**调用方持有 `process` 句柄可随时 `terminate()`**。
  3. **density 双口径换算保持不变**（关键不变量 #1）：`on_report` 的等价换算逻辑（`report['density_sparrow']=report['density']; report['density']=total_area/(width*gate_mm)`）在主进程处理 frame 时执行（`total_area` 来自 manifest 数据），不在子进程做。AC 验证：返回的 frame 里 `density` 为原面积口径、`density_sparrow` 为 spyrrow 自报。
  4. **终止安全**（防死锁，对应风险 R1）：`process.terminate()` 后，父进程做 `result_queue.cancel_join_thread()` + 限时 drain（如循环 `get_nowait()` 直到 Empty 或累计 50ms）后 break，不阻塞 join 超时。验证：start → 等首帧 → `terminate()` → 父进程在 5s 内返回、无 hang。
  5. **子进程异常不 hang 父进程**：子进程内 `build_instance` 抛错或 solve 崩溃 → 子进程通过 `result_queue` 投递 `{kind:'error', message}` 后正常退出；父进程收到 error 退出循环。子进程意外 crash（未投 error）→ 父进程 `process.is_alive()` 转 False 后退出循环、err 记为 `'worker process exited unexpectedly (code=<exitcode>)'`。
  6. **旧 `solve_with_callback` 保留不删**（过渡期 US-026 才切换调用方），保证本次提交系统行为零变化；新函数有独立单测覆盖。
  7. 新建 `materialSorting-server/tests/test_solve_proc.py`：≥4 项 — ①正常求解收到 manifest+frame+final 且 density 双口径正确 ②start→terminate 后父进程 5s 内返回不 hang ③子进程 build_instance 抛错→父进程收到 error ④子进程被外部 kill（模拟 crash）→父进程不 hang。Windows multiprocessing 测试需 `if __name__=='__main__'` 守卫。
  8. `python -c "from materialsorting.web.solve_worker import solve_worker; from materialsorting.web.solver import solve_with_callback_proc"` 导入无异常；`python -m pytest materialSorting-server/tests/test_solve_proc.py` 全绿；分层依赖未反向（web 不被下层 import）。
- **Priority**: 1
- **依赖**: 无（独立后端改造；US-026 消费）

### US-026: WS /ws/solve 支持 stop 消息（持续读 + 进程终止 + 协议扩展）
- **Description**: As a 版师, I want 求解运行中能通过 WS 发一条「停止」指令让后端真正终止求解, so that 我不必等一个 120s 的求解跑完才能改参数重来。
- **Acceptance Criteria**:
  1. `materialSorting-server/src/materialsorting/web/server.py` 的 `ws_solve` 改造：①`build_instance` 调用从主进程移除（移入 US-025 的 `solve_worker` 子进程），主进程改调 `solve_with_callback_proc(pieces_snapshot, gate_mm, solve_params, on_manifest=..., on_report=...)` 拿到 `process` 句柄；②WS 从「只读一次 start」改为 `asyncio.gather(read_loop(), write_loop())` 并发：`write_loop` drain asyncio queue → `ws.send_json`（manifest/frame/final/error），`read_loop` 持续 `await ws.receive_json()` 接收后续 client 消息。
  2. **stop 处理**：`read_loop` 收到 `{action:'stop'}` → `process.terminate()` → `process.join(timeout=5)` → `ws.send_json({'type':'stopped','reason':'user_requested'})` → 关闭 WS（break 两个 loop）。`write_loop` 收到 `_SENTINEL` 或 `read_loop` 取消时退出。`asyncio.gather` 的异常处理：任一 loop 抛错需 `cancel()` 另一个并清理 process。
  3. **客户端断开清理**（修 F6）：`read_loop`/`write_loop` 捕获 `WebSocketDisconnect` / 连接异常 → `process.terminate()` + `process.join(timeout=5)`，**不留孤儿进程**。验证：start 求解后直接关 WS → 5s 内后端进程数回落到求解前水平。
  4. **WS accept 阶段 `_get_pieces_state()` 快照不变**（关键不变量）：连接内 pieces 不变；`pieces_snapshot`（纯 dict）传给 `solve_with_callback_proc`。空 state 仍直接发 error「排料数据为空」并关闭（行为不变）。
  5. **现有 start→manifest→frame→final 流程回归不破坏**：正常求解（不 stop）端到端跑通，frame/final 字段与 density 双口径与改造前一致；多 seed 并发（前端启 N 条 WS）每条各自独立子进程、互不干扰。
  6. `materialSorting-web/src/types/ws.ts` 协议扩展：①新增 `StopPayload = { action: 'stop' }`；②`ClientMsg = StartPayload | StopPayload`（原 StartPayload 的 `action:'start'` 不变）；③新增 `StoppedMsg = { type: 'stopped'; reason: string }`；④`ServerMsg` 联合增加 `StoppedMsg`。同步更新 `agent-api-reference.md` 的 WS 章节（握手改为「首条必须 start，后续可发 stop」+ 新增 stopped 消息说明）。
  7. `materialSorting-server/tests/test_ws_stop.py`（或扩展现有 ws 测试）：≥3 项 — ①发 start → 收到 frame 后发 stop → 收到 stopped 且 WS 关闭、进程终止 ②start 后直接断连 → 后端清理不泄漏 ③不发 stop 正常求解收 final（回归）。
  8. `python -c "from materialsorting.web.server import app"` 导入无异常；`ms-web` 启动无报错；`cd materialSorting-web && npm run typecheck` 通过、`npm run build` 无报错。
- **Priority**: 2
- **依赖**: US-025（进程化是 stop 的前提）

### US-027: 前端 stop() + 求解状态机（phase: idle/running/stopped/done/error）
- **Description**: As a 版师, I want 求解界面能反映「就绪/求解中/已停止/完成/出错」五种状态并据此启用不同操作, so that 我清楚当前求解处于什么阶段、能做什么。
- **Acceptance Criteria**:
  1. `materialSorting-web/src/hooks/useSolveRun.ts` 新增 `stop()` 方法：遍历 `runRegistry.list()`，对每个 `readyState===WebSocket.OPEN` 的 `rec.ws` 发 `JSON.stringify({action:'stop'})`；返回值从 `{start, isStarted}` 扩为 `{start, stop, isStarted}`（向后兼容，不破坏现有调用）。
  2. `useSolveRun.ts` 的 onmessage 新增 `case 'stopped'`：标记 `rec.stopped=true`，调 `finish()` 触发 `onDone` 回调（复用现有收尾路径）。`runRegistry` 的 RunRecord 类型加 `stopped?: boolean` 字段。
  3. `materialSorting-web/src/components/NestingPage.tsx` 状态扩展：`const [solving, setSolving] = useState(false)` → `const [phase, setPhase] = useState<SolvePhase>('idle')`，`type SolvePhase = 'idle'|'running'|'stopped'|'done'|'error'`（导出到 `types/` 供 US-028 复用）。`handleStart` 内 `setSolving(true)` → `setPhase('running')`。
  4. **onDone 回调按结果区分 phase**：检查 `rec.stopped`→`setPhase('stopped')`；`rec.error`（现有 error 路径）→`setPhase('error')`；否则→`setPhase('done')`。多 seed 场景沿用现有 `doneCountRef` 计数逻辑：所有 seed 的 onDone 都触发后才统一切 phase（全 stopped→stopped、混合或全 done→done）。
  5. 新增 `handleStop`：调 `useSolveRun.stop()`（不立即 setPhase，等 server 回 stopped 后由 onDone 切到 stopped）。新增 `handleRestart`：`runRegistry.clear()`（关闭旧 WS）+ 用**上次 start 参数**（存到 `useRef`）调 `handleStart`；若用户在 stopped/error/done 态改了参数则用新参数。
  6. **running 态冻结参数编辑**（防求解中改参数）：`phase==='running'` 时 SizePicker / 种子 / 时间 / 高级配置弹窗触发按钮等输入控件 `disabled`（与现有 StartButton 的 disabled 同套机制）。
  7. `materialSorting-web/src/__tests__/useSolveRun.stop.test.tsx`（或扩展现有）：≥3 项 — ①`stop()` 对 open WS 发 `{action:'stop'}` ②收到 `{type:'stopped'}` 后 finish 触发、`rec.stopped===true` ③NestingPage phase 转换：running→(stop)→stopped / running→(error)→error / running→(final)→done。
  8. `npm run typecheck` 通过、`npm run test` 全绿、`npm run build` 无报错。
- **Priority**: 3
- **依赖**: US-026（WS stop 协议）

### US-028: 按钮组组件 SolveControls + ControlPanel 接线
- **Description**: As a 版师, I want 根据当前 phase 看到 context 恰当的按钮（开始求解 / 停止 / 重新开始 / 再次求解），停止后能导出中间方案并看到提示, so that 操作直观、状态自解释。
- **Acceptance Criteria**:
  1. 新建 `materialSorting-web/src/components/ControlPanel/SolveControls.tsx`，**删除** `StartButton.tsx`（已确认：grep 确认无其它引用后删除；SolveControls 独立渲染按钮组，不复用 StartButton）。按 `phase` 渲染：

     | phase | 按钮组 | 说明 |
     |-------|--------|------|
     | idle | 「开始求解」 | 等价旧 StartButton |
     | running | 「停止」 | 调 onStop |
     | stopped | 「重新开始」+「导出」（状态行提示「已停止 — 导出的是停止时刻的最优中间方案」） | registry 保留帧 |
     | done | 「再次求解」+「导出」 | 正常完成 |
     | error | 「重新开始」+（若有帧）「导出」 | 出错可重试 |

  2. `materialSorting-web/src/components/ControlPanel/ControlPanel.tsx` 接线：`solving` prop → `phase` prop；`<StartButton>` → `<SolveControls onStart={...} onStop={...} onRestart={...} phase={phase} />`；`ExportButtons` 的 `solving` prop 改为 `phase==='running'`（stopped/done/error 可导出）。
  3. **中间方案导出提示**：`stopped`/`error`（有帧）态点导出，StatusLine 或导出按钮旁明确标注「导出的是停止/出错时刻的中间方案，非最终最优解」；导出文件名仍用当前 `density`（真实口径，反映该中间方案利用率），**不加** `_partial` 等后缀，与正常导出命名规则一致（仅靠 UI 提示区分）。
  4. **视觉一致**：沿用现有 `style.css` 暗色系按钮样式（不引入 CSS 框架）；按钮 disabled 态样式与现有 StartButton 一致；按钮组布局与 ControlPanel 现有节奏一致，不挤占参数区。
  5. **a11y**：按钮带 `aria-label`（如「停止求解」「重新开始求解」）；停止按钮可键盘触发。
  6. `materialSorting-web/src/components/ControlPanel/__tests__/SolveControls.test.tsx`：≥5 项 — 5 个 phase 各自渲染正确按钮 + 点击调对应 handler + running 态无开始按钮 / idle 态无停止按钮。
  7. **通过浏览器验证**（UI Story 必备）：`npm run dev` + `ms-web` 启动后，在超排页完整走一遍：idle 点开始→running 显示停止→点停止冻结画面且状态行提示→stopped 点重新开始清空重跑→正常完成 done→再次求解；多 seed 并行停止全部终止；反复 stop+restart 多次无异常。
  8. `npm run typecheck` 通过、`npm run test` 全绿、`npm run build` 无报错。
- **Priority**: 4
- **依赖**: US-027（phase 状态机）

## 功能需求 (Functional Requirements)

- **FR-1（停止）**：求解 running 时点「停止」→ 前端对所有 open WS 发 `{action:'stop'}` → 后端 `process.terminate()` + 回 `{type:'stopped'}` → 前端冻结末帧、phase→stopped。
- **FR-2（重新开始）**：stopped / error / done 时点「重新开始 / 再次求解」→ 清空 registry 旧帧 → 用当前参数（用户可先改）发起全新求解 → phase→running。
- **FR-3（状态机）**：phase ∈ {idle, running, stopped, done, error}，每个 phase 下按钮可用性 + 参数编辑可用性按上表锁定。
- **FR-4（中间方案导出）**：stopped / error（有帧）态导出可用，但显式提示导出的是中间方案。
- **FR-5（资源清理）**：stop / 断连 / WS 关闭 → 后端求解进程必被 terminate + join，不泄漏；反复操作不堆积。

## 非目标 (Non-Goals)

- **NG-1（暂停）**：**不做真暂停也不做伪暂停**。sparrow 无 checkpoint/resume，真暂停不可能；伪暂停（冻结前端显示、后端继续烧 CPU）误导用户、无业务价值。本次只做 stop（终止）+ restart（全新重来）。
- **NG-2（断点续跑）**：停止后不保留求解进度供「从断点继续」，restart 是从零开始的全新求解。
- **NG-3（单 seed 内的细粒度取消）**：不区分「停止当前 seed 但保留其它 seed」，stop 一刀切终止当前求解任务的所有 seed（与现状「一次 start 启动 N 个 seed」语义对齐）。
- **NG-4（求解历史/多版本对比管理）**：不引入 run 历史栈，registry 仍只保留当前一批 run。
- **NG-5（修改 spyrrow 源码）**：sparrow 不改源码的铁律不变，所有中断能力在外层进程管理实现。

## 设计考虑 (Design Considerations)

- **按钮极简优先**：版师真正需要的是「停止后改参数再跑」，而非暂停。UI 上 stop + restart 两步操作覆盖了 90% 真实诉求，不堆砌暂停/恢复按钮制造假象。
- **停止后的画面**：前端不清空 registry，NestSVG 停在最后一帧（版师能看到停止时刻的排料效果，判断要不要导出或改参数重来）。
- **状态行文案**：每个 phase 给明确中文状态（就绪 / 求解中… / 已停止 / 完成：seed X · YY.Y% / 错误：…），版师一眼知状态。
- **导出中间方案的诚实提示**：不把停止后的导出伪装成最终解，状态行明确「中间方案」，避免版师拿非最优解去裁剪。

## 技术考虑 (Technical Considerations)

- **进程模型替代线程模型**：`solve_with_callback`（threading）→ `solve_with_callback_proc`（multiprocessing）。spyrrow 对象不可 pickle，`build_instance` 必须在子进程内执行；主进程只收 JSON 可序列化的 manifest/frame/final/error。
- **Windows spawn 开销**（风险 R2）：Windows multiprocessing 走 spawn（重新 fork Python + import spyrrow），冷启动 ~200-500ms。MVP 用 `Process` 直起；若多 seed 并发延迟不可接受，后续可改预热 worker pool（但 stop 需杀单个进程而非整池，复杂度高，本次不做）。
- **multiprocessing.Queue 死锁防护**（风险 R1）：`Process.terminate()` 后 queue 可能残留半写入数据 → `cancel_join_thread()` + 限时 drain，绝不阻塞 join。
- **多 seed 公平性不变**（关键不变量 #7）：进程模型下每个 seed 一个子进程，OS 调度同等竞争 CPU，排名语义与线程版一致；不因进程化破坏多 seed 对比公平性。
- **density 双口径换算位置**：从「子线程 `on_report` 回调」迁移到「主进程处理子进程 frame 时换算」（`total_area` 由 manifest 数据带入主进程）。换算逻辑与公式不变，仅执行位置变。
- **导出与求解进程解耦**：`/export` 从 `_get_pieces_state()` 拿原始轮廓 + 前端 POST 的 `placed_items` 工作，与求解进程无关，进程化对导出零影响。
- **`_executor` 线程池职责收敛**：求解进程化后，`ThreadPoolExecutor(6)` 不再承载求解，仅保留给 DXF 解析（`/api/parse-dxf`）与 commit（`/api/commit-to-nesting`）。求解进程由 `ws_solve` 内直接 `multiprocessing.Process` 管理，不进 `_executor`。
- **协议契约变更需同步文档**：WS 从「client 仅首条 start」变为「首条 start + 后续可 stop」，`agent-api-reference.md` WS 章节须同步（US-026 AC#6）。

## 成功指标 (Success Metrics)

- [ ] 求解 running 时点「停止」，后端求解进程在 2s 内终止（任务管理器进程数回落、CPU 不再占用）。
- [ ] 停止后前端冻结末帧，phase→stopped，「重新开始」+「导出」可用且导出有中间方案提示。
- [ ] 「重新开始」清空旧帧、用相同/新参数跑通全新求解，phase 正确流转 idle/running/done。
- [ ] 多 seed 并行求解（如 3 seed）点停止，全部 N 个子进程终止。
- [ ] 反复 stop+restart 连续 10 次，后端进程/线程数不增长（无泄漏）。
- [ ] WS 客户端意外断开（关浏览器 tab），后端 5s 内清理求解进程，无孤儿进程。
- [ ] 现有求解回归不破坏：正常 start→manifest→frame→final 端到端跑通，density 双口径正确。
- [ ] `npm run typecheck` / `npm run test` / `npm run build` 全绿；后端 pytest 全绿；`python -c "from materialsorting.web.server import app"` 无异常。

## 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| R1 | `Process.terminate()` 后 `multiprocessing.Queue` 残留数据致 `get()` 死锁 | terminate 后 `cancel_join_thread()` + 限时 drain（累计 ≤50ms）后 break，不无限 join |
| R2 | Windows spawn 冷启动 ~200-500ms，多 seed 并发总开销 1-3s | MVP 接受；US-028 浏览器验证时观测实际延迟，超阈值再列入后续优化（预热 pool） |
| R3 | asyncio.gather(read_loop, write_loop) 任一抛错未正确取消另一个 → 句柄泄漏 | 用 try/finally + `task.cancel()` 双向清理；finally 里必 `process.terminate()+join(timeout=5)` |
| R4 | 停止后保留的中间方案被误当最终解导出裁剪 | UI 显式提示「中间方案」；导出文件名 density 反映真实利用率 |
| R5 | 多 seed 场景 stop 后 phase 切换时序混乱（部分 seed stopped / 部分 done） | onDone 沿用 doneCountRef 计数，全到齐再统一切 phase；混合结果取「最差」态（有 error→error，否则有 stopped→stopped，否则 done） |
| R6 | 进程化后 density 双口径换算位置迁移，漏算导致 90% 判定错 | US-025 AC#3 明确换算在主进程做；单测断言 frame.density 为原面积口径、frame.density_sparrow 为自报 |

## 待确认问题 (Open Questions)

- **OQ-1**：Windows spawn 冷启动延迟（R2）在版师实际机器上是否可接受？需 US-028 浏览器验证时实测；若 >1s 体感差，是否本期就上预热 worker pool？

> 其余决策已闭环：①停止后导出文件名**不加** `_partial` 后缀，仅靠 UI 提示区分；②`StartButton.tsx` 确认**删除**。
