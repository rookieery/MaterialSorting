# web — Agent 速查

> FastAPI + WebSocket 工作台（最上层）。可 import 全部下层（dxf_parser / nesting_bounds / nesting_engine）+ `paths`；下层**禁** import 本包。
> 改前先看 `.docs/technical/agent-api-reference.md`（HTTP/WS 契约）+ `.docs/technical/agent-file-map.md` web 章节。

## 启动 / 校验

```bash
python -c "from materialsorting.web.server import app"                # 导入冒烟（含路由表打印）
ms-web                                                                 # 启动 uvicorn :8000（console_script）
python -m materialsorting.web.server                                   # 等价（无 console_script 也能跑）
curl -X POST http://127.0.0.1:8000/api/parse-dxf -F "file=@<dxf>"      # US-004 上传解析
curl http://127.0.0.1:8000/api/ptypes                                  # US-020 片型代表裁片
```

> **intermediate 由 Web 上传母版 commit 生成**（`server.py` 启动期 `_reload_pieces_state()` 在 import 时读 `pieces_intermediate.json`；缺失不崩但 `_PIECES_STATE` 为空 dict，`/ws/solve` 报「排料数据为空」、`/api/ptypes` 返回 `{representatives:{}}`，前端上传母版 commit 成功后自动 reload 填入）。`materialSorting-web/static/` 也需 `npm run build` 一次让 mount 不空（dev 模式 Vite proxy 不依赖 build 产物，但 FastAPI mount 空目录会报错）。

## 文件分工

| 文件 | 角色 |
| --- | --- |
| `server.py` | FastAPI app；路由 `GET /`、`mount /static`、`POST /export`、`POST /api/parse-dxf`（US-004）、`POST /api/commit-to-nesting`（US-010）、`GET /api/ptypes`（US-020）、`WS /ws/solve`；US-020 可 reload `_PIECES_STATE`（threading.Lock 保护）；`ThreadPoolExecutor(max_workers=6)` 求解桥 + 上传解析/commit 复用 |
| `solver.py` | `load_pieces` / `discretize_orientations` / `build_instance`（v0.3 erode+tol 包装，US-024 pid_meta 加 5 层字段 `.get()` 兼容）/ `solve_with_callback`（**旧** threading 版 spyrrow ProgressQueue + 0.2s drain，US-025 起保留不删）/ `solve_with_callback_proc`（**US-025** multiprocessing 版，spawn 子进程跑 `solve_worker`，主进程 drain `multiprocessing.Queue`，返回 `process` 句柄可 `terminate()`；density 双口径换算在主进程处理 frame 时做）+ `_apply_density_dual` 私有 helper |
| `solve_worker.py` | **US-025 新增**。顶层 `solve_worker(pieces_snapshot, gate_mm, solve_params, result_queue)` —— Windows spawn 可 pickle（无闭包、参数全 JSON）。子进程内 `build_instance(...) → 投 {kind:manifest}` → `instance.solve(config, progress=ProgressQueue)` → drain 出中间解投 `{kind:frame,report}` → 末尾投 `{kind:final,final}` 或 `{kind:error,message}`。所有投递纯 JSON，spyrrow 对象绝不跨进程 |
| `export.py` | `apply_transform` / `placed_to_world`（用**原始**非 eroded 轮廓；US-024 起 5 层一并变换，notch 点按点变换 + 法线按向量旋转）/ `render_png`（matplotlib Agg；US-024 起 5 层叠加 net 绿虚线 / internal 橙 / notch 黄短线段 / grain 红虚线）/ `write_marker_dxf`（R12 POLYLINE + ACI 色；US-024 起多 layer outline1/14/8/4/7 各自独立 entity） |

## US-004 /api/parse-dxf 关键约定（实现方/调用方必读）

- **multipart 依赖 `python-multipart`**：已在 `[web]` extra（`pyproject.toml`）。否则 FastAPI `UploadFile = File(...)` 启动即报 `AssertionError`。
- **落盘路径**：`paths.OUT_DIR/uploads/<doc_id>.dxf`（`doc_id = uuid.uuid4().hex`，32 字符无横杠）。**禁硬编码** —— 用模块级常量 `UPLOADS_DIR = Path(paths.OUT_DIR) / 'uploads'`。
- **CPU 解析走 executor**：`loop.run_in_executor(_executor, _parse_dxf_sync, str(dest))` 复用 6-worker 线程池（与 `/ws/solve` 同池）。母版深度解析 ~1-2s，不阻塞事件循环。
- **错误码口径**：扩展名非 `.dxf`→400；超 `UPLOAD_MAX_BYTES=20MB`→413；ezdxf/collect 异常→422（中文错误信息）。**200 / 400 / 413 / 422 全部走 JSONResponse**（与 `/export` 一致），不抛 `HTTPException`。
- **响应字段**（US-005 前端契约，不能改）：`{doc_id, filename, sizes:[{size, pieces:[{label,name,polygon,internal_lines,notches,net_polygon,grain_line}]}]}`。polygon=`[[x,y],...]`；internal_lines=`[[[x,y],...],...]`；notches=`[[x,y,nx,ny],...]`；net_polygon=`[[x,y],...]`；grain_line=`[x1,y1,x2,y2]` 或 `null`。
- **A/B/C 标注口径**：每码内独立编号（不跨码续编）。排序键 `(-centroid_y, centroid_x, -area_mm2, block_name, piece_index)` → 上方/左/大片优先。码号分组排序：数值升序，`null` 殿后。`_label_for` 支持 26+ 自动 AA/AB（实测每码 ≤10 片，AA+ 仅兜底）。
- **doc_id 是 US-010 入参**：`POST /api/commit-to-nesting {doc_id}` 会读 `uploads/<doc_id>.dxf`。**doc_id 必须可定位落盘文件**，故成功响应才返回 doc_id（422 时文件保留但响应不带 doc_id）。

## US-010 /api/commit-to-nesting 关键约定（Path A 全管线）

- **请求体**：JSON `{doc_id, filename?}`。`doc_id` 必填，仅匹配 `_DOC_ID_RE = ^[0-9A-Za-z]{1,128}$`（防路径逃逸，`uuid.uuid4().hex` 自然命中）；`filename` 可选，缺省用 `<doc_id>.dxf`，作为新 intermediate 的 `source` 字段。
- **管线（`_commit_to_nesting_sync` 跑在 executor）**：`explore.collect_pieces` → `assign_group_no` + `GROUP_NAMES` 定 ptype → `write_piece_dxf` 切单裁片到 `uploads/<doc_id>_pieces/` → `load_nest_pieces(pieces_dir, sizes=母版全码)` → 写回 `paths.INTERMEDIATE`。
- **全码**：sizes 取母版实际全码 `sorted({p.size for p in pieces if p.size is not None})`，**不沿用 `DEFAULT_SIZES`** 8 码。M1787 实测 11 码 [28-38] → 176 NestPiece。
- **临时单裁片目录**：`UPLOADS_DIR / f'{doc_id}_pieces'`。每次 commit 先 `shutil.rmtree` 再重写（**idempotent**）。v1 不自动清理（open question），同 doc_id 重跑覆盖。
- **备份**：写回前 `shutil.copy2(paths.INTERMEDIATE, paths.INTERMEDIATE.with_suffix('.bak'))`（首次 commit 无原文件则跳过）。`.bak` 只保留一份（再 commit 覆盖）。
- **错误码**：请求体非 JSON / 缺 doc_id / 类型错 / `_DOC_ID_RE` 不中 → **400**；`uploads/<doc_id>.dxf` 不存在 → **404**；管线异常（collect 空 / write 全跳过 / load_nest_pieces 空 / 写盘失败）→ **422**。全部 JSONResponse。
- **`GATE_MM` 别名导入**：`from ..nesting_bounds.load_pieces import GATE_MM as NEST_GATE_MM`（写回新 intermediate 用源常量 1980，避免与既有 intermediate 的可能脏值扩散）。
- **commit 后 reload（US-020）**：`_commit_to_nesting_sync` 成功后立即调 `_reload_pieces_state()`，下一次 `/ws/solve` / `/export` / `/api/ptypes` 即看到新裁片（前端无需重启 ms-web）。返回 payload 加 `reloaded: true`；reload 异常（罕见 I/O 竞态）降级为 `reloaded: false` + `reload_error` 字段，保留旧 state 不半切。
- **回归等价（历史口径）**：对 M1787，commit 产物的 `pid` 集合 / `total_area_mm2` 与历史「全码 CLI 管线」（`load_nest_pieces(<pieces_dir>, sizes=[28..38])`，CLI 已移除）完全等价（实测 176/176 片、PID 集合相同、零面积 diff）。

## US-020 关键约定（_PIECES_STATE reload + GET /api/ptypes）

- **可 reload 状态**：`_PIECES_STATE: dict = {doc, gate_mm, pieces, pieces_by_id}`（替代旧顶层 `PIECES / GATE_MM / PIECES_BY_ID` 三个常量）；`_state_lock = threading.Lock()` 保护读写原子。
- **immutable snapshot 模式**：`_reload_pieces_state()` 在锁内整体 `clear()+update()` `_PIECES_STATE` 引用内容，读者始终拿到完整一致快照（不会读到半状态）。`_get_pieces_state()` 锁内返回当前 state 引用，调用方拿到后整连接复用（一次 ws 连接内 pieces 不变，避免求解中途数据切）。
- **启动期 allow-empty**：import 时 `try: _reload_pieces_state() except: pass` —— intermediate 缺失不再让 `import materialsorting.web.server` 直接崩；`_PIECES_STATE={}` 时 `/api/ptypes` 返 `{representatives:{}}`、`/ws/solve` 报「排料数据为空」、`/export` 报「placed 的 pid 均未匹配」（400）。commit 成功后 `_reload_pieces_state()` 真正填入。
- **`/ws/solve` 快照口径（关键不变量 AC#5）**：accept 阶段 `state = _get_pieces_state()` 取一次快照，整连接内 `pieces/gate_mm` 不变（避免求解中途 reload 切数据）；`build_instance` 用快照 pieces，density 换算用快照 gate_mm。
- **`/export` 快照口径**：每次请求 `_get_pieces_state()` 拿当前 state（请求粒度快照足够；导出是短操作）。
- **GET /api/ptypes（D10）**：从 `_PIECES_STATE.pieces` 按 ptype 分组、各取首个 piece 作代表；返回 `{representatives: Record<ptype, {polygon, net_polygon?, internal_lines?, notches?, grain_line?}>}`。字段白名单 `_PTYPE_REPRESENTATIVE_FIELDS` 透传 intermediate 已有字段 —— **layer-aware（D11）**：v1 仅 polygon，US-024 扩 intermediate 为 5 层后自动带 net/internal/notches/grain，前端代码无需改。空 state 返 `{representatives: {}}`。
- **curl 验证 M1787**：commit 后 `/api/ptypes` 返 10 ptype 代表裁片（前片/后片/腰/前袋/后袋/机头/单排/双排/火机袋/裤耳），每个仅 `polygon` 字段。

## US-022 关键约定（求解输入数量 demand per-size）

- **intermediate 加 label 字段**：`_commit_to_nesting_sync` 调 `nesting_engine.labeling.compute_size_ptype_labels(pieces, gmap, GROUP_NAMES)` → `{(size, ptype): label}` 写入每片的 `label`。L/R 同 ptype 共享 label。
- **label 对齐不变量（AC#5）**：commit 走 NestPiece（归一化+镜像），parse 走 PieceOutline（原始坐标），坐标系不同不能直接排序对齐；但两者均源自同一母版的 `explore.collect_pieces`，对原始 pieces 施行与 `_build_parse_payload` 完全一致的排序键 `(-centroid_y, centroid_x, -area_mm2, block_name, piece_index)` + `label_for(idx)` 标注，再经 gmap/GROUP_NAMES 关联 ptype → label 按 (size, ptype) 严格对齐（M1787 验证 10/10 对齐）。
- **共享 labeling 模块**：`nesting_engine/labeling.py` 是 parse/commit 两处标注的单一真相源；`server.py._label_for/_centroid/_size_sort_key` 转发到此。依赖方向合规（web → nesting_engine）。
- **WS /ws/solve 入参增 quantities**：`{label: {sizeKey(str): N}}` | None。`build_instance` 按 `(piece.label, str(piece.size))` 查 N → `spyrrow.Item(demand=N)`；**demand=0 跳过该 piece（D2）**；piece 缺 label 或 quantities=None → demand=1（向后兼容旧 intermediate / 旧前端）。
- **sizeKey 口径**：`str(size)`（number→String）；`null`→`'null'`（与前端 qtyStore `sizeKey` 一致）。

## 已踩坑 / 注意事项

- **顶层 `_reload_pieces_state()` 在 import 时执行（allow-empty）**：intermediate 缺失 → `_PIECES_STATE={}` 但 import 不崩。改启动顺序需同步更新 `.docs/technical/agent-file-map.md` 关键不变量 #8。
- **`_executor` 是全局共享池**：求解（`/ws/solve`）+ 上传解析（`/api/parse-dxf`）+ commit（`/api/commit-to-nesting`）共 6 worker。解析/commit 快（~1-2s）+ 求解长（120s+），实测不互相阻塞；如需隔离请改两池。
- **UploadFile 读取**：`await file.read()` 一次性读全到内存（20MB 上限内可接受）。流式校验需自写 chunk loop，当前实现选简单。
- **响应 filename 字段**：透传客户端 `file.filename`（中文文件名浏览器走 UTF-8 正常；curl 命令行可能用本地 codepage → 终端显示乱码，但 JSON 内部仍是原 bytes）。前端 US-006 显示文件名用此字段。
- **frontend dev proxy `/api`**：`vite.config.ts` 已配 `server.proxy`（US-009），dev 模式经 Vite proxy 命中后端 :8000；`/export`、`/ws`、`/api` 同 proxy 配置。

## US-025 关键约定（求解进程化 solve_worker + solve_with_callback_proc）

- **背景**：sparrow 编译为 Rust `.pyd`，`instance.solve()` 是原生阻塞调用；全包 grep `cancel|abort|stop|pause|kill|terminate` = 0 匹配，`ProgressQueue` 仅只读 `drain()`，无任何中断 API；`threading.Thread` 无法安全终止原生代码线程；唯有 `Process.terminate()`（Windows 调 `TerminateProcess`）可靠。
- **spyrrow 对象不可 pickle** → `build_instance` 必须在**子进程内**执行（`solve_worker` 顶层函数 + 参数全 JSON 可序列化），只把 pid_meta/frame/final/error 经 `multiprocessing.Queue` 传回主进程。
- **`solve_worker` 必须 pickle-safe**：顶层函数、无闭包、参数全部 JSON（list/dict/float/int/str）。延迟 `from .solver import build_instance` 放函数内（避免主进程 `from .solve_worker import solve_worker` 时强制 import sparrow_baseline）。
- **density 双口径换算位置**（关键不变量 #1）：**主进程**在收到 frame 时执行 `density_sparrow ← density; density ← total_area/(width*gate_mm)`；`total_area` 由 manifest 投递带入主进程。不在子进程做。换算逻辑与公式同旧 threading 版，仅执行位置迁。
- **终止安全（防死锁，风险 R1）**：`process.terminate()` 后必走 `result_queue.cancel_join_thread()`（停 background feeder thread）+ 限时 drain（循环 `get_nowait()` 累计 ≤50ms 或 Empty 即 break）+ `process.join(timeout=5)`；join 超时再 `kill()` 兜底。**绝不**无限阻塞 join。
- **循环退出条件**：`while True: get(timeout=drain_interval if alive else 0.05)`，`queue.Empty` 且 `not alive` 时才 break —— 子进程死后继续 drain 完 queue 残余（避免漏 final）。
- **子进程异常 3 类**：①`build_instance` 抛错 → 子进程投 `{kind:error,message}` 后正常退出（exitcode=0），父进程收到 error 退出；②`solve` 崩溃 → 同理；③子进程被外部 kill / 崩溃未投 error → 父进程 `process.is_alive()=False` 后 drain 完 queue 退出，`err='worker process exited unexpectedly (code=<exitcode>)'`。
- **旧 `solve_with_callback` 保留不删**（过渡期），US-026 已切换 `ws_solve` 调用方到 `solve_with_callback_proc`。
- **测试**：`materialSorting-server/tests/test_solve_proc.py` ≥4 项（正常求解 / terminate 5s 内返回 / build_instance 抛错 / 外部 kill 不 hang + solve_worker 可 pickle）。Windows multiprocessing：测试不创建模块级 Process；conftest 加 sys.path 让 `from materialsorting...` 在未 `pip install -e .` 时也能跑。

## US-026 关键约定（WS /ws/solve 支持 stop + 进程终止 + 协议扩展）

- **ws_solve 双向并发**：write loop 内联（主流程）drain asyncio queue → `ws.send_json`（manifest/frame/final/error）；read loop 后台 task 持续 `await ws.receive_json()` 收 `{action:'stop'}` / WebSocketDisconnect。
- **stop 处理**：read loop 收 `{action:'stop'}` → `state_box['stopped']=True` → `_terminate_solve_process(state_box)` → `await ws.send_json({type:'stopped'})` 直发 → `queue.put_nowait(_SENTINEL)` → return。stopped 是客户端收到的最后一条业务消息（write loop 在 `stopped` 标志置 True 后丢弃残余 frame）。
- **客户端断开清理（修旧 bug）**：read loop 捕获 `WebSocketDisconnect` → `stopped=True` → `_terminate_solve_process(state_box)`（terminate+join 5s）；旧版 `except:pass` 静默忽略断开 → 求解线程跑满预算（120s+）占用线程池。
- **`_terminate_solve_process(state_box)` 幂等封装**：alive → `terminate()` → `join(timeout=5)` → 仍活 `kill()` → `join(timeout=1)`。read_loop（stop/断开）、write_loop send 失败、finally 兜底三处调用。
- **`on_process` 回调（US-026 新增）**：`solve_with_callback_proc` 新增可选 `on_process` 参数 —— 子进程 `start()` 后立即回调，把 `Process` 句柄交给 `ws_solve` 存入 `state_box['process']`，供 stop/断开时 terminate。旧调用方不传则不回调（向后兼容）。
- **finally 显式 `ws.close()`**：write loop break 后 finally 块 cancel read_task + `await ws.close()` + terminate process。`ws.close()` 在 TestClient 下必须显式调（Starlette 不会在 endpoint 返回后自动关 WS 到 client 端 receive_json 抛 disconnect 的程度）；uvicorn 下也安全（幂等）。
- **不 await read_task**：TestClient（anyio portal）下 `ws.receive_json()` 阻塞在线程安全队列上，`task.cancel()` 的 CancelledError 无法投递；`await read_task` / `wait_for(read_task)` 会永久挂起。uvicorn 生产环境 cancel 正常生效，ws_solve 返回后 FastAPI 关 WS 让 read_loop 自然退出。
- **协议扩展（types/ws.ts）**：新增 `StopPayload={action:'stop'}`；`ClientMsg=StartPayload|StopPayload` 联合；新增 `StoppedMsg={type:'stopped',reason:'user_requested'}`；`ServerMsg` 联合增 `StoppedMsg`。向后兼容（旧前端不发 stop，后端不发 stopped）。
- **测试**：`tests/test_ws_stop.py` 3 项（start→frame→stop→stopped+WS 关闭 / start 后直接断连→进程数回落 / 不发 stop 正常求解收 final）。用 `starlette.testclient.TestClient`（需 `pip install httpx`）。小问题（16 片）exploring 阶段每 ~3ms 吐帧 → 3s 预算积攒 ~800+ frame，测试用 deadline 循环非固定计数。
