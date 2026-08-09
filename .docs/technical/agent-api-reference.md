# Agent API 参考 — 排料可视化工作台后端

> 后端 HTTP / WebSocket 契约文档。改 `web/server.py` / `web/solver.py` / `web/export.py` 任一处先看这里，并同步本文件。
> 入口：`ms-web`（console_script）→ `materialsorting.web.server:main` → uvicorn `127.0.0.1:8000`。

## 状态

单页工作台后端，3 个 HTTP 端点 + 1 条 WS。求解用 `ThreadPoolExecutor(max_workers=6)` 把同步 sparrow 子线程桥到 asyncio 事件循环（多 seed 最多 6 路并发，seed 间同等 CPU 竞争 → 排名仍公平）。**`server.py` 在模块顶层 `load_pieces()` 读 intermediate**，故 `ms-web` 首次启动前**必须**先 `ms-pieces-export` 生成 `pieces_intermediate.json`。

## 启动约束（重要）

1. `server.py` 顶层执行 `_DOC, GATE_MM, PIECES = load_pieces()` —— import 时就读 intermediate。文件缺失 → import 即崩。
2. `app.mount('/static', ...)` 指向 `materialSorting-web/static/`（前端构建产物）。
   - **prod**：先 `cd materialSorting-web && npm run build` 生成 `static/`；
   - **dev**：`npm run dev` 起 Vite :5173，经 proxy 打 :8000（仍建议先 build 一次让 `static/` 存在，避免 mount 空目录报错）。

## HTTP 路由

| 方法 | 路径 | 说明 | 实现 |
|------|------|------|------|
| GET | `/` | 返回 `static/index.html`（prod 入口） | `server.index` → `FileResponse` |
| mount | `/static/*` | 前端构建产物（JS/CSS/资源） | `StaticFiles(directory=paths.STATIC_DIR)` |
| POST | `/export` | 导出最优 run → PNG / R12-DXF 附件下载 | `server.export` |
| WS | `/ws/solve` | 排料求解流（manifest → frames → final） | `server.ws_solve` |

> 无 `/docs` OpenAPI（未显式启用），路由全在上表。

## POST /export — 导出

前端把**最优 run 的最终帧 `placed_items`** 回传，服务端用**原始母版轮廓**（`pieces_intermediate.json` 的原始 polygon，**非 eroded**）放到排料变换位，保证 PNG 与 DXF 几何一致、可直接裁剪。

### 请求 payload

```jsonc
{
  "fmt": "png" | "dxf",          // 必填
  "sizes": [28, 30, 32],          // 码号列表（文件名用，排序后 '-' 拼接；空 → "all"）
  "seed": 0,                      // 文件名标注用
  "gate_mm": 1980,                // run.manifest.gate_mm（多 run 共享）
  "width_mm": 7058.0,             // run.lastFrame.width_mm（用布长度 mm）
  "density": 0.8983,              // run.finalDensity（原面积口径，0..1）
  "placed": [                     // run.lastFrame.placed_items
    {"id": "...", "rotation": 0.0, "translation": [x, y]},
    ...
  ]
}
```

### 响应

- 成功：文件字节流，`Content-Disposition: attachment; filename="<ascii>"; filename*=UTF-8''<quoted-cn>`
  - ascii 名：`nesting_<sizes>_<pct>.2fpct_seed<seed>.<ext>`
  - 中文名：`排料_码<sizes>_<pct>.2fpct_seed<seed>.<ext>`（走 RFC 5987 `filename*=UTF-8''` + `urllib.parse.quote`；**文件名用 `pct` 不用 `%`**）
  - PNG：`media_type=image/png`，`render_png`（matplotlib Agg，标题 + 类型图例）
  - DXF：`media_type=application/dxf`，`write_marker_dxf`（R12 + POLYLINE，ACI 上色 + ASCII 标题）
- 400：`width_mm<=0` 或 `placed` 空 → `{"error":"无可导出的方案（width=0 或无裁片）"}`；`placed` 的 pid 全匹配不到 → `{"error":"导出失败：placed 的 pid 均未匹配到原始轮廓"}`；未知 fmt → `{"error":"未知格式 <fmt>"}`。

### 导出关键函数（`web/export.py`）

| 函数 | 签名 | 说明 |
|------|------|------|
| `apply_transform` | `(polygon, rotation_deg: float, translation) → [(x,y)...]` | `world = R(θ)·(x,y)+(tx,ty)`，与前端 `pointsStr` 同公式 |
| `placed_to_world` | `(placed, pieces_by_id) → [{pid,ptype,size,polygon,color,area_mm2}]` | pid 查 `PIECES_BY_ID` 取**原始** polygon → 世界坐标；查不到的跳过并 warning |
| `render_png` | `(world_pieces, *, width_mm, gate_mm, title) → bytes` | matplotlib Agg，dpi=200，类型配色复用 `PTYPE_COLORS`，图例仅画出现过的片型 |
| `write_marker_dxf` | `(world_pieces, *, width_mm, gate_mm, title) → bytes` | ezdxf R12 + 闭合 POLYLINE（首尾补点），ACI 色号见 `TYPE_ACI`，ASCII 标题；**不用 LWPOLYLINE**（ET2008 轮廓消失坑） |

`TYPE_ACI`：前片=1 / 后片=2 / 腰=3 / 前袋=4 / 后袋=5 / 机头=6 / 单排=7 / 双排=8 / 火机袋=9 / 裤耳=10。

## WebSocket /ws/solve — 求解流

单条长连接，生命周期：**client 发 start → server 推 1×manifest → N×frame → 1×final（或 error）**。

### 1. 握手（client → server，**首条且仅一条**）

```jsonc
{
  "action": "start",              // 必须为 "start"，否则 server 直接 error 并关闭
  "sizes": [28, 29, 30, 31, 33, 34, 35, 36],  // 码号；空 = 全部 128 片
  "time": 120,                    // 求解时间预算（秒），默认 120
  "seed": 0,                      // sparrow 随机种子，默认 0
  "params": {"d_ext":0, "d_int":10, "tol_ext":0, "tol_int":0},  // 内/外两档；全 0 = baseline
  "per_type": {"单排": {"d": 8, "tol": 15}}   // 可选，每片型高级覆盖；缺维度回退两档
}
```

`params` / `per_type` 缺省 = baseline（无 erode、严格布纹线 `{0°,180°}`）。

### 2. server → manifest（**一次**，握手后立即发）

```jsonc
{
  "type": "manifest",
  "gate_mm": 1980,
  "total_area_mm2": <原面积之和，含缝份>,
  "n_eroded": <被 erode 的片数>,
  "pieces": [
    {"id": "<pid>", "ptype": "前片", "size": 30, "color": "#...", "area_mm2": <int>, "polygon": [[x,y]...]},
    ...
  ]
}
```

`polygon` 是 **erode 后**的 base 多边形（与后续 placement 一致）。前端据此一次性建 SVG 骨架 + N 个 `<polygon>`。

### 3. server → frame（**每个中间解**，~5fps 由 `drain_interval=0.2` 决定）

```jsonc
{
  "type": "frame",
  "index": 0,                     // server 侧递增序号（counter['n']）
  "elapsed": 0.123,               // 秒，自 solve 开始
  "phase": "exploring",           // spyrrow rtype.phase_name()：exploring / compressing / final
  "density": 0.8983,              // ★ 原面积口径 real = total_area/(width*gate)（与 90% 生死线一致）
  "density_sparrow": 0.8809,      // spyrrow 自报（erode 后面积口径，偏低，仅参考）
  "width_mm": 7058.0,             // 当前用布长度
  "placed_items": [               // 完整布局（每帧全量）
    {"id": "<pid>", "rotation": 0.0, "translation": [x, y]},
    ...
  ]
}
```

> **density 双口径**（关键不变量）：sparrow 子线程吐出的 `density` 是 erode 后面积口径；server 侧 `on_report` 把原值存为 `density_sparrow`，再用 `total_area/(w*GATE_MM)` 重算 `density`。前端**任何决策/显示都优先 `density`**。

### 4. server → final（**一次**，求解结束）

```jsonc
{
  "type": "final",
  "density": <real>,              // 原面积口径
  "density_sparrow": <sparrow>,   // spyrrow 自报
  "width_mm": <最终用布长度>,
  "elapsed": <总秒数，round 2>,
  "n_frames": <发出的 frame 总数>,
  "n_eroded": <被 erode 的片数>
}
```

### 5. server → error（异常时）

```jsonc
{"type": "error", "message": "<原因>"}
```

触发：首条非 start、`build_instance` 抛错、求解线程抛错。客户端中途断开被 server 静默忽略（求解线程仍跑完收尾）。

## 求解桥接（`web/solver.py`）

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_pieces` | `(intermediate_path=paths.INTERMEDIATE) → (doc, gate_mm, pieces)` | 读 `pieces_intermediate.json` |
| `discretize_orientations` | `(tol: float) → list[float]` | v0.3 连续旋转公差 → spyrrow 离散角度集。`tol=0→[0,180]`；`tol≤5` 步进 1°；否则 5°。归一化到 [0,360) |
| `build_instance` | `(pieces, gate_mm, *, time_budget, seed, sizes=None, params=None, per_type=None) → (instance, config, pid_meta, total_area, n_eroded)` | 按 sizes 过滤 → 每片 `erode=min(申请d, MAX_OVERLAP[ptype])`、`tol=min(申请tol, ROTATION_TOL[ptype])` → erode+clean → 构造 `spyrrow.Item` + `StripPackingInstance` + `StripPackingConfig` |
| `solve_with_callback` | `(instance, config, on_report, *, drain_interval=0.2) → (final_sol, elapsed_sec, err)` | 子线程 `instance.solve(config, progress=queue)`，主线程 `queue.drain()` 每 0.2s 取中间解 → `on_report({type:frame,...})` |

### 求解线程 ↔ 事件循环桥（`server.ws_solve`）

```
build_instance()                                    # 主线程，同步
  ↓
manifest → ws.send_json                             # 主线程
  ↓
ThreadPoolExecutor(max_workers=6).submit(run_solve) # 求解进子线程
  on_report(report):                                # 子线程回调
    report['density_sparrow'] = report['density']
    report['density'] = total_area/(w*gate)         # 重算原面积口径
    loop.call_soon_threadsafe(queue.put_nowait, report)
  ↓
async 协程: while (item=await queue.get()) ≠ SENTINEL: ws.send_json(item)
```

`SENTINEL` 对象由 `run_solve` 末尾投递，协程收到即结束循环。

## 坐标系（贯穿 PNG / DXF / 前端 SVG）

- **sparrow 世界坐标**：X = 用布长度（0..width），Y = 门幅（0..gate），**Y 向上**。
- **前端 SVG**：`scale(1,-1)` 翻转后与 PNG 一致（Y 向下）。
- **DXF 导出**：同世界坐标（Y 向上），R12 POLYLINE。
- 三者几何口径一致，导出文件可直接对应屏幕观感。

## 关键不变量（改后端勿破坏）

1. **density 双口径**：frame/final 的 `density` 必须是原面积口径（`total_area/(width*gate)`），`density_sparrow` 才是 spyrrow 自报。前端 90% 生死线判定用 `density`。
2. **导出用原始轮廓非 eroded**：`PIECES_BY_ID` 持有原始 polygon；`placed_to_world` 用它变换。eroded 多边形只用于求解/屏幕。
3. **DXF 走 R12 + POLYLINE**（非 LWPOLYLINE）：ET2008 读 LWPOLYLINE 轮廓消失。单裁片与 marker 导出均如此。
4. **`server.py` 顶层 `load_pieces()`**：import 时读 intermediate。改启动顺序须保证 intermediate 已生成。
5. **WS 首条必须是 `{action:'start'}`**：否则 error 并关闭。
6. **导出文件名 `pct` 而非 `%`**：`排料_码28-30-32_88.42pct_seed0.png`。改格式需同步前端 `useExport.test.tsx` CN decode 用例。
7. **多 seed 并发靠 ThreadPoolExecutor(6)**：seed 间同等 CPU 竞争，排名公平。改 worker 数影响多 seed 对比语义。

## 入口（`pyproject.toml` `[project.scripts]`）

| 命令 | 模块 | 作用 |
|------|------|------|
| `ms-web` | `materialsorting.web.server:main` | 启动排料工作台（uvicorn :8000） |

> 其它 `ms-*` 入口（解析/导出 intermediate/实验）见 [agent-file-map.md](agent-file-map.md)。
