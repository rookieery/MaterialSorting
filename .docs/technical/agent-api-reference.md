# Agent API 参考 — 排料可视化工作台后端

> 后端 HTTP / WebSocket 契约文档。改 `web/server.py` / `web/solver.py` / `web/export.py` 任一处先看这里，并同步本文件。
> 入口：`ms-web`（console_script）→ `materialsorting.web.server:main` → uvicorn `127.0.0.1:8000`。

## 状态

单页工作台后端，5 个 HTTP 端点 + 1 条 WS。**US-026 起求解用 `solve_with_callback_proc`（多进程版）**：`ThreadPoolExecutor(max_workers=6)` 跑 `run_solve` → `solve_with_callback_proc` spawn 子进程执行 sparrow solve，主进程 drain `multiprocessing.Queue` 分发 manifest/frame/final（多 seed 最多 6 路并发，seed 间同等 CPU 竞争 → 排名仍公平）。WS 双向并发：write loop drain queue → `ws.send_json`；read loop 持续读客户端消息（`{action:'stop'}` → terminate 子进程 → 发 stopped → 关闭 WS）。**`server.py` 启动期 `_reload_pieces_state()` 读 intermediate 填入 `_PIECES_STATE`**（US-020：commit 后可 reload，allow-empty 不再让 import 崩）。US-004 起 `/api/parse-dxf` 上传解析也复用这个 6-worker 线程池跑 CPU 密集的 DXF 深度解析（`collect_pieces_with_details`）。

## 启动约束（重要）

1. `server.py` 顶层执行 `_reload_pieces_state()` —— import 时读 intermediate 填入 `_PIECES_STATE`（US-020）。intermediate 缺失**不再让 import 崩**：`_PIECES_STATE={}` 时 `/api/ptypes` 返 `{representatives:{}}`、`/ws/solve` 报「排料数据为空」、`/export` 报「placed 的 pid 均未匹配」。intermediate 由 Web commit（`/api/commit-to-nesting`）生成，首次启动空 state 正常，前端上传母版后自动 reload 填入。
2. `app.mount('/static', ...)` 指向 `materialSorting-web/static/`（前端构建产物）。
   - **prod**：先 `cd materialSorting-web && npm run build` 生成 `static/`；
   - **dev**：`npm run dev` 起 Vite :5173，经 proxy 打 :8000（仍建议先 build 一次让 `static/` 存在，避免 mount 空目录报错）。
3. US-004 上传依赖 `python-multipart`（已在 `[web]` extra），落盘目录 `paths.OUT_DIR/uploads/`（启动时按需 `mkdir`）。

## HTTP 路由

| 方法 | 路径 | 说明 | 实现 |
|------|------|------|------|
| GET | `/` | 返回 `static/index.html`（prod 入口） | `server.index` → `FileResponse` |
| mount | `/static/*` | 前端构建产物（JS/CSS/资源） | `StaticFiles(directory=paths.STATIC_DIR)` |
| POST | `/export` | 导出最优 run → PNG / R12-DXF 附件下载 | `server.export` |
| POST | `/api/parse-dxf` | US-004：multipart 上传母版 DXF → 深度解析 + A/B/C 标注 JSON | `server.parse_dxf` |
| POST | `/api/commit-to-nesting` | US-010：把上传母版转排料 intermediate（Path A 全管线，覆盖写回 + .bak）+ US-020 commit 后 reload `_PIECES_STATE` | `server.commit_to_nesting` |
| GET | `/api/ptypes` | US-020 D10：返回当前 `_PIECES_STATE` 下每个 ptype 的代表裁片（首个出现），供前端高级配置弹窗缩略图/放大预览（D11 layer-aware，v1 仅 polygon） | `server.get_ptypes` |
| WS | `/ws/solve` | 排料求解流（manifest → frames → final） | `server.ws_solve` |

> FastAPI 自动暴露 `/docs` `/openapi.json` 等 OpenAPI 路由；业务路由全在上表。

## POST /export — 导出

前端把**最优 run 的最终帧 `placed_items`** 回传，服务端用**原始母版轮廓**（`pieces_intermediate.json` 的原始 polygon，**非 eroded**）放到排料变换位，保证 PNG / DXF / PLT 三格式几何一致、可直接裁剪 / 绘图。

### 请求 payload

```jsonc
{
  "fmt": "png" | "dxf" | "plt",  // 必填（US-033 新增 plt）
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
  - PLT：`media_type=application/plt`，`write_marker_plt`（US-033；HPGL/HP-GL 文本，5 层 SP1-SP5 笔号 + SP6 门幅框，ASCII LB 标题；喂 WT V8.8 + LIKE 绘图仪原生 PLT 链路）
- 400：`width_mm<=0` 或 `placed` 空 → `{"error":"无可导出的方案（width=0 或无裁片）"}`；`placed` 的 pid 全匹配不到 → `{"error":"导出失败：placed 的 pid 均未匹配到原始轮廓"}`；未知 fmt → `{"error":"未知格式 <fmt>"}`。

### 导出关键函数（`web/export.py`）

| 函数 | 签名 | 说明 |
|------|------|------|
| `apply_transform` | `(polygon, rotation_deg: float, translation) → [(x,y)...]` | `world = R(θ)·(x,y)+(tx,ty)`，与前端 `pointsStr` 同公式 |
| `placed_to_world` | `(placed, pieces_by_id) → [{pid,ptype,size,polygon,color,area_mm2}]` | pid 查 `_get_pieces_state()['pieces_by_id']`（US-020）取**原始** polygon → 世界坐标；查不到的跳过并 warning |
| `render_png` | `(world_pieces, *, width_mm, gate_mm, title) → bytes` | matplotlib Agg，dpi=200，类型配色复用 `PTYPE_COLORS`，图例仅画出现过的片型 |
| `write_marker_dxf` | `(world_pieces, *, width_mm, gate_mm, title) → bytes` | ezdxf R12 + 闭合 POLYLINE（首尾补点），ACI 色号见 `TYPE_ACI`，ASCII 标题；**不用 LWPOLYLINE**（ET2008 轮廓消失坑） |
| `write_marker_plt` | `(world_pieces, *, width_mm, gate_mm, title) → bytes` | US-033 HPGL/HP-GL 纯文本（`IN;`/`VS80;`/`SP1-6;`/`PU;`/`PD;`/`LB<chr(3)>`），坐标=mm×40 round 取整，5 层笔号 SP1=outline/SP2=net/SP3=internal/SP4=notch/SP5=grain/SP6=border；空层跳过；纯 ASCII bytes（无临时文件，无新 pip 依赖）；与 DXF 同闭合策略 + 同 ASCII title |

`TYPE_ACI`：前片=1 / 后片=2 / 腰=3 / 前袋=4 / 后袋=5 / 机头=6 / 单排=7 / 双排=8 / 火机袋=9 / 裤耳=10。

## POST /api/parse-dxf — US-004 母版上传解析

`multipart/form-data` 上传单个 `.dxf` 母版 → 服务端落盘 + 调 `dxf_parser.collect.collect_pieces_with_details` 深度解析 → 按码号分组 + 几何稳定排序 + A/B/C 标注的 JSON。CPU 密集解析走 `loop.run_in_executor(_executor, ...)` 复用 6-worker 线程池（与 `/ws/solve` 同池，防阻塞 WS 事件循环）。前端 US-005 `useParseDxf` 经相对路径 fetch（dev 走 Vite proxy `/api`，prod 同源）。

### 请求

`multipart/form-data` 单字段 `file`（`UploadFile`），文件名扩展名必须 `.dxf`（不区分大小写）。`Content-Length` 不强制（服务端 `await file.read()` 后用 `UPLOAD_MAX_BYTES=20MB` 判定）。

```bash
curl -X POST http://127.0.0.1:8000/api/parse-dxf \
  -F "file=@data/M1787#....dxf"
```

### 响应（200）

```jsonc
{
  "doc_id": "d484858d185a4936a1108fbb8951b6f2",   // uuid4 hex，落盘文件名（无扩展名）；供 US-010 /api/commit-to-nesting 引用
  "filename": "M1787#....dxf",                    // 客户端上传的原文件名
  "sizes": [
    {
      "size": 28,                                 // 块名尾码号；解析失败为 null
      "pieces": [
        {
          "label": "A",                           // 0→A, 1→B, ..., 25→Z, 26→AA ...
          "name": "noname..28",                   // 解码后的 block_name（GBK→UTF-8）
          "polygon": [[x, y], ...],               // layer1 毛版外轮廓
          "internal_lines": [[[x, y], ...], ...], // layer8 POLYLINE 内部线（多条）
          "notches": [[x, y, nx, ny], ...],       // layer4 POINT 刀口：点 + 单位外法线（沿法线画 8mm 短线段）
          "net_polygon": [[x, y], ...],           // layer14 POLYLINE 净版轮廓；无则 []
          "grain_line": [x1, y1, x2, y2]          // layer7 LINE 布纹线；无则 null
        },
        // ...B/C/.../J（每码 10 片）
      ]
    },
    // ...29-38 共 11 码
  ]
}
```

**全码一次返回**（M1787 实测 ~680KB JSON / 110 片 / 11 码，远低于 1-3MB 上限）；前端按 `activeSize` 本地切片，不做按码懒加载。

### 排序 + 标注

每码内裁片按以下键稳定排序后赋 A/B/C...：

```
key = (-centroid_y, centroid_x, -area_mm2, block_name, piece_index)
```

→ DXXF 数学系（Y 向上）下质心 Y 大者（视觉上方）优先、X 小者（视觉左）优先、面积大者优先；同质心/面积按 `block_name` 字典序 + `piece_index` 兜底。码号分组排序：`size` 升序，`null` 殿后。

### 错误响应

| HTTP | 触发 | body |
|------|------|------|
| 400 | 文件名扩展名非 `.dxf`（大小写不敏感） | `{"error":"仅支持 .dxf 文件"}` |
| 413 | 字节数 > `UPLOAD_MAX_BYTES`（20MB） | `{"error":"文件大小超过上限 20MB"}` |
| 422 | ezdxf/collect 解析抛任何异常（损坏 / 非 DXF 内容 / R12 recover 失败） | `{"error":"DXF 解析失败：<异常>"}` |

### 落盘

- 路径：`paths.OUT_DIR/uploads/<doc_id>.dxf`（`doc_id = uuid.uuid4().hex`，32 字符无横杠）。`uploads/` 目录首调按需 `mkdir(parents=True, exist_ok=True)`。
- 文件名是 server 生成的 uuid，**不**沿用客户端原文件名（避免中文/路径注入）；客户端原文件名仅在响应 `filename` 字段回显。
- 解析失败（422）时落盘文件**保留**（用于排查），不自动清理；目录在 `out/`（已 gitignore）。

### 关键不变量

1. **doc_id 是 US-010 commit 入参**：`POST /api/commit-to-nesting {doc_id}` 会读 `uploads/<doc_id>.dxf`，故 doc_id 必须可定位文件。
2. **A/B/C 在每码内独立编号**：码 A 与码 B 各自从 A 起算（不跨码续编）。
3. **`polygon` 是原始毛版几何**（未归一化 / 未对齐布纹 / 未镜像），与 intermediate 的 NestPiece polygon（归一化 + 镜像后）不同；US-007 `PiecePreviewSVG` 直接渲染此字段。
4. **`grain_line` 与原始 DXF 同坐标系**（Y 向上），前端 SVG `scale(1,-1)` 翻转后与 PNG/R12 导出一致。
5. **响应大小 ≤ 20MB 解析后压缩**：实测 M1787 ~680KB JSON，前端 `useParseDxf` 一次拿到全码缓存到 Zustand。
6. **上传预览 US-005 前端契约**：响应字段名（`doc_id` / `filename` / `sizes[].size` / `sizes[].pieces[].{label,name,polygon,internal_lines,notches,net_polygon,grain_line}`）被 `materialSorting-web/src/types/parsed.ts` 严格镜像；改任一字段需同步 `types/parsed.ts` + `useParseDxf.test.tsx` AC#2。前端 hook `useParseDxf` 用 `FormData('file', file)` 发请求，**不手设 Content-Type**（让浏览器自动加 boundary）；成功后默认选中 `sizes[0].size`（最小码）。错误（400/413/422/网络错）统一进 `uploadStore.error`，UI 自取渲染。

## POST /api/commit-to-nesting — US-010 上传母版转 intermediate（Path A）

把 US-004 落盘的母版 DXF 转成排料 intermediate（覆盖 `pieces_intermediate.json`），复用 `export_dxf` + `load_nest_pieces` 全管线。**Path A 实现**：服务端跑 `explore.collect_pieces` → `export_dxf.assign_group_no` + `GROUP_NAMES` 定片型 → `write_piece_dxf` 切单裁片到 `paths.OUT_DIR/uploads/<doc_id>_pieces/` → `load_nest_pieces(pieces_dir, sizes=母版全码)` → 写回 `paths.INTERMEDIATE`。CPU 密集管线跑在 `loop.run_in_executor(_executor, ...)` 复用 6-worker 线程池（与 `/ws/solve`、`/api/parse-dxf` 同池，防阻塞 WS）。

### 请求

`application/json`：

```jsonc
{
  "doc_id": "02a4d4e4f40e423196f026d291a94ea2",  // 必填，US-004 落盘的 uuid（无扩展名）
  "filename": "M1787(1)(2).dxf"                  // 可选，覆盖 intermediate source 字段；缺省用 <doc_id>.dxf
}
```

`doc_id` 仅允许 `[0-9A-Za-z]{1,128}`（regex `_DOC_ID_RE`），防路径逃逸；`uuid.uuid4().hex`（32 位 hex）自然命中。

```bash
curl -X POST http://127.0.0.1:8000/api/commit-to-nesting \
  -H "Content-Type: application/json" \
  -d '{"doc_id":"02a4d4e4f40e423196f026d291a94ea2","filename":"M1787(1)(2).dxf"}'
```

### 响应（200）

```jsonc
{
  "doc_id": "02a4d4e4f40e423196f026d291a94ea2",
  "source": "M1787(1)(2).dxf",         // 写入 intermediate 的 source 字段
  "sizes": [28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38],  // 母版实际全码（非 DEFAULT_SIZES 8 码）
  "n_pieces": 176,                      // NestPiece 总数（含 L/R 镜像展开）
  "total_area_mm2": 17650482.2,         // 所有 NestPiece 面积之和（mm²）
  "n_written_dxf": 110,                 // 切出的单裁片 DXF 数（写入 uploads/<doc_id>_pieces/）
  "n_skipped": 0,                       // 未切出的裁片数（GROUP_NAMES 映射缺失 / size=None）
  "skipped": [],                        // 截断的前 10 条跳过原因（排查用）
  "bak": "D:\\code\\...\\pieces_intermediate.bak",  // 原 intermediate 备份路径
  "reloaded": true                      // US-020：commit 后 _reload_pieces_state() 是否成功（罕见 I/O 竞态时 false + reload_error 字段）
}
```

### 错误响应

| HTTP | 触发 | body |
|------|------|------|
| 400 | 请求体非 JSON / 缺 `doc_id` / 类型错 / `doc_id` 不匹配 `_DOC_ID_RE` | `{"error":"请求体须为 JSON"}` / `{"error":"缺少 doc_id 或类型错误"}` / `{"error":"doc_id 非法（仅允许字母数字，1-128 字符）"}` |
| 404 | `uploads/<doc_id>.dxf` 不存在 | `{"error":"未找到上传文件: <doc_id>"}` |
| 422 | 全管线抛异常（collect_pieces 空 / write_piece_dxf 全跳过 / load_nest_pieces 空 / JSON 写盘失败） | `{"error":"commit 失败：<异常>"}` |

### 副作用 + 写盘

1. **临时单裁片目录**：`paths.OUT_DIR/uploads/<doc_id>_pieces/`（~110 个 DXF，每次 commit 先 `shutil.rmtree` 再重写，**idempotent**）。v1 不自动清理（open question），同 `doc_id` 重跑会覆盖。
2. **intermediate 备份**：写回前 `shutil.copy2(paths.INTERMEDIATE, paths.INTERMEDIATE.with_suffix('.bak'))`。`pieces_intermediate.bak` 是上一次写回前的快照（首次 commit 无原文件则跳过备份）。**只保留一份**（再 commit 会覆盖 `.bak`）。
3. **intermediate schema 与历史 CLI 产物一致**：`{source, gate_mm, n_pieces, total_area_mm2, pieces[]}`；pieces 字段 `{pid, ptype, size, side, label(US-022), polygon, bbox, area_mm2, n_verts, allowed_angles, net_polygon(US-024), internal_lines(US-024), notches(US-024), grain_line(US-024)}`。`gate_mm=1980`（`nesting_bounds.load_pieces.GATE_MM`）、`allowed_angles=[0,180]`（v0.3 布纹线）。`label` 由 `compute_size_ptype_labels` 按 parse 同排序同标注生成，L/R 同 ptype 共享 label（AC#5 关键不变量）。US-024 起每片多 4 个 5 层字段（default_factory=[] / None 向后兼容旧 intermediate），由 `load_pieces.load_nest_pieces` 经 `_read_piece_full` + `_apply_layer_transforms` 与 polygon 共享 rotate→mirror→normalize transform 链后透传。
4. **commit 后 reload（US-020）**：`_commit_to_nesting_sync` 成功 → 立即调 `_reload_pieces_state()` 重读 intermediate 填入 `_PIECES_STATE`（threading.Lock 保护，原子替换）。下一次 `/ws/solve` / `/export` / `/api/ptypes` 即看到新裁片，**前端无需重启 ms-web**。reload 异常（罕见 I/O 竞态）降级为 `reloaded: false` + `reload_error` 字段，保留旧 state 不半切。

### 关键不变量

1. **全码**：`load_nest_pieces` 的 sizes 取自母版实际全码（`sorted({p.size for p in pieces if p.size is not None})`），**不沿用 `DEFAULT_SIZES`**（8 码跳 32）。M1787 实测 11 码 [28-38] → 176 NestPiece（vs 8 码 128 片）。
2. **片型映射复用 `export_dxf.GROUP_NAMES`**（g00→后片 … g09→腰，M1787 结构款 SVG 人工确认）。新款母版须版师重新确认 group→ptype 映射。
3. **NestPiece 仅含 polygon（毛版 layer1）**：grain/internal/notch 不进 intermediate（排料只需 polygon）；L/R 镜像由 `load_nest_pieces` 的 `PAIR_TYPES` 处理。
4. **回归等价（历史口径）**：对 M1787，commit 产物的 `pid` 集合 / `total_area_mm2` 与历史「全码 CLI 管线」（`load_nest_pieces(<pieces_dir>, sizes=[28..38])`，CLI 已移除）等价（实测 176/176 片、PID 集合相同、零面积 diff）。
5. **路径一律走 `paths`**：`paths.OUT_DIR/uploads/`、`paths.INTERMEDIATE`、`paths.INTERMEDIATE.with_suffix('.bak')`；不硬编码 `..` 上溯。

## GET /api/ptypes — US-020 片型代表裁片（D10/D11）

返回当前 `_PIECES_STATE` 下每个 ptype 的代表裁片（首个出现），供前端高级配置弹窗表头缩略图 + 点击放大预览（US-018）。

### 请求

无入参，GET。响应直接读 `_get_pieces_state()` 内存常量，**不走文件 I/O**（μs 级响应）。

```bash
curl http://127.0.0.1:8000/api/ptypes
```

### 响应（200）

```jsonc
{
  "representatives": {
    "前片":   {"polygon": [[x,y], ...]},     // v1 仅 polygon 字段
    "后片":   {"polygon": [[x,y], ...]},
    "腰":     {"polygon": [[x,y], ...]},
    "前袋":   {"polygon": [[x,y], ...]},
    "后袋":   {"polygon": [[x,y], ...]},
    "机头":   {"polygon": [[x,y], ...]},
    "单排":   {"polygon": [[x,y], ...]},
    "双排":   {"polygon": [[x,y], ...]},
    "火机袋": {"polygon": [[x,y], ...]},
    "裤耳":   {"polygon": [[x,y], ...]}
    // US-024 后每个代表裁片自动带 net_polygon / internal_lines / notches / grain_line（前端 layer-aware 渲染，本端点无需改）
  }
}
```

### 字段透传白名单（`_PTYPE_REPRESENTATIVE_FIELDS`）

`('polygon', 'net_polygon', 'internal_lines', 'notches', 'grain_line')` —— **layer-aware（D11）**：v1 intermediate 只有 polygon → 仅返 polygon；US-024 intermediate 扩 5 层后自动带后 4 个字段，**本端点代码无需改**，前端按数据有无自适应渲染。

### 关键不变量

1. **空 state（首次启动未 commit / intermediate 缺失）**：返回 `{representatives: {}}`，不阻塞前端配置弹窗降级为片型名文字。
2. **ptype 首个出现作代表**：按 `_PIECES_STATE.pieces` 数组顺序遍历，每个 ptype 第一次出现时记录；不区分 L/R、不区分码号（同 ptype 几何归一化后等价）。
3. **M1787 验证**：commit 后返 10 个 ptype（前片/后片/腰/前袋/后袋/机头/单排/双排/火机袋/裤耳）。
4. **响应字段不含 pid / size / area**：仅几何数据；片型名是 key。前端只需 polygon 画缩略图。

## WebSocket /ws/solve — 求解流

单条长连接，生命周期：**client 发 start（首条必须）→ server 推 1×manifest → N×frame → 1×final（或 error）；client 可在任意时刻发 stop → server 推 1×stopped → 关闭 WS**。

> US-020：accept 阶段 `state = _get_pieces_state()` 拿一次快照，整连接内 `pieces / gate_mm` 不变（避免求解中途 reload 切数据）。state 空时（首次启动未 commit / intermediate 缺失）直接发 error「排料数据为空」并关闭。
>
> US-026：ws_solve 改为 `solve_with_callback_proc` 进程化求解（build_instance 移入子进程）。write loop 内联 drain asyncio queue → ws.send_json；read loop 后台 task 持续读客户端消息。收到 `{action:'stop'}` → `process.terminate()+join(timeout=5)` → 直发 `{type:'stopped'}` → 关闭 WS。客户端断开（WebSocketDisconnect）→ 同样 terminate+join 防孤儿进程（**修复旧 bug**：旧版 `except:pass` 静默忽略断开，求解线程跑满预算）。

### 1. 握手（client → server，**首条必须 action:'start'**；后续可发 action:'stop'）

```jsonc
// 首条消息 —— 启动求解
{
  "action": "start",              // 必须为 "start"，否则 server 直接 error 并关闭
  "sizes": [28, 29, 30, 31, 33, 34, 35, 36],  // 码号；空 = 全部 128 片
  "time": 120,                    // 求解时间预算（秒），默认 120
  "seed": 0,                      // sparrow 随机种子，默认 0
  "params": {"d_ext":0, "d_int":0, "tol_ext":0, "tol_int":0},  // US-019 起前端永远传全 0；主面板内外两档输入已删，d/tol 覆盖全交 per_type
  "per_type": {"单排": {"d": 8, "tol": 15}},  // 可选，每片型高级覆盖；缺维度回退两档
  "quantities": {"A": {"28": 2, "30": 0}, "B": {"28": 1}}  // US-022 可选，label→sizeKey→demand；0=该 piece 该码不排；缺省=null→全片 demand=1
}
```

```jsonc
// 后续消息（US-026，可选）—— 停止求解
{"action": "stop"}
```

`params` / `per_type` 缺省 = baseline（无 erode、严格布纹线 `{0°,180°}`）。`quantities` 缺省 / `null` = 全片 `demand=1`（向后兼容旧前端 / 旧 intermediate 无 label）。US-022 起 `build_instance` 按 `(piece.label, str(piece.size))` 查 `quantities` → `spyrrow.Item(demand=N)`；demand=0 跳过（D2）；piece 缺 label 回退 demand=1。

### 2. server → manifest（**一次**，握手后立即发）

```jsonc
{
  "type": "manifest",
  "gate_mm": 1980,
  "total_area_mm2": <原面积之和，含缝份>,
  "n_eroded": <被 erode 的片数>,
  "pieces": [
    {
      "id": "<pid>", "ptype": "前片", "size": 30, "color": "#...", "area_mm2": <int>,
      "polygon": [[x,y]...],          // 毛版外轮廓（erode 后，参与 sparrow NFP 碰撞）
      "net_polygon": [[x,y]...],      // US-024 净版（仅渲染透传，不参与碰撞；缺省 []）
      "internal_lines": [[[x,y],...]],// US-024 内部线多条（缺省 []）
      "notches": [[x,y,nx,ny],...],   // US-024 刺口点 + 单位法线（缺省 []）
      "grain_line": [x1,y1,x2,y2]     // US-024 布纹线（缺省 null）
    },
    ...
  ]
}
```

`polygon` 是 **erode 后**的 base 多边形（与后续 placement 一致，**唯一参与 sparrow NFP 碰撞**）。前端据此一次性建 SVG 骨架 + N 个 `<polygon>`。US-024 新增 4 层（net_polygon/internal_lines/notches/grain_line）**仅渲染/导出透传**，不进碰撞；后端 pid_meta / intermediate / manifest 同字段名透传，前端 layer-aware 渲染（缺字段跳过该层，向后兼容旧 intermediate）。

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

触发：首条非 start、`build_instance` 抛错、求解进程抛错 / crash。**US-026 起：客户端断开不再静默忽略** —— read loop 捕获 `WebSocketDisconnect` → `process.terminate()+join(timeout=5)` 防孤儿进程。

### 6. server → stopped（US-026，客户端发 stop 后）

```jsonc
{"type": "stopped", "reason": "user_requested"}
```

客户端发 `{action:'stop'}` 后，后端 read loop `process.terminate()+join(timeout=5)` → 直发此消息 → 关闭 WS。`stopped` 是客户端收到的最后一条消息（write loop 在 `stopped` 标志置 True 后丢弃残余 frame）。WS 关闭后客户端不再收 final / error。

## 求解桥接（`web/solver.py` + `web/solve_worker.py`）

## 求解桥接（`web/solver.py` + `web/solve_worker.py`）

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_pieces` | `(intermediate_path=paths.INTERMEDIATE) → (doc, gate_mm, pieces)` | 读 `pieces_intermediate.json` |
| `discretize_orientations` | `(tol: float) → list[float]` | v0.3 连续旋转公差 → spyrrow 离散角度集。`tol=0→[0,180]`；`tol≤5` 步进 1°；否则 5°。归一化到 [0,360) |
| `build_instance` | `(pieces, gate_mm, *, time_budget, seed, sizes=None, params=None, per_type=None, quantities=None) → (instance, config, pid_meta, total_area, n_eroded)` | 按 sizes 过滤 → US-022 按 `(label, sizeKey)` 查 quantities 定 demand（0 跳过；缺 label → 1） → 每片 `erode=min(申请d, MAX_OVERLAP[ptype])`、`tol=min(申请tol, ROTATION_TOL[ptype])` → erode+clean → 构造 `spyrrow.Item` + `StripPackingInstance` + `StripPackingConfig`；pid_meta 含 US-024 5 层字段（`.get()` 向后兼容） |
| `solve_with_callback` | `(instance, config, on_report, *, drain_interval=0.2) → (final_sol, elapsed_sec, err)` | **旧 threading 版（保留）**。子线程 `instance.solve(config, progress=queue)`，主线程 `queue.drain()` 每 0.2s 取中间解 → `on_report({type:frame,...})`。US-026 起 `ws_solve` 切换到 `solve_with_callback_proc`，本函数不删（过渡期） |
| `solve_with_callback_proc` | `(pieces_snapshot, gate_mm, solve_params, *, on_manifest, on_report, on_process=None, drain_interval=0.2) → (process, final_data, elapsed, err)` | **US-025 多进程版**。spawn 子进程跑 `solve_worker`（在子进程内 `build_instance + solve`，spyrrow 对象不可 pickle 故不跨进程），主进程 drain `multiprocessing.Queue` 分发：manifest → `on_manifest`、frame → `on_report`（density 双口径换算在主进程做）、final/error 记录。**US-026 新增 `on_process` 回调**：子进程 `start()` 后立即回调一次，把 `Process` 句柄交给调用方供 WS stop / 断开时 `terminate()`。返回 `process` 句柄可 `terminate()`；terminate 后 `cancel_join_thread + 限时 drain(≤50ms) + join(timeout=5)` 防死锁；子进程 crash 未投 error 时 `err='worker process exited unexpectedly (code=<exitcode>)'` |

### `web/solve_worker.py`（US-025 新增）

| 函数 | 签名 | 说明 |
|------|------|------|
| `solve_worker` | `(pieces_snapshot, gate_mm, solve_params, result_queue)` | **子进程入口（顶层函数，Windows spawn 可 pickle）**。子进程内 `build_instance(pieces_snapshot, gate_mm, **solve_params)` → 投递 `{kind:manifest, pid_meta, total_area, n_eroded, gate_mm}` → `instance.solve(config, progress=ProgressQueue)` → drain 出的中间解投递 `{kind:frame, report}` → 末尾投递 `{kind:final, final}` 或 `{kind:error, message}`。所有投递纯 JSON 可序列化，spyrrow 对象绝不跨进程 |

### 求解进程 ↔ 事件循环桥（`server.ws_solve`，US-026 进程化版）

```
accept → receive_json() → {action:start}            # 主协程，读首条消息
  ↓
solve_with_callback_proc(pieces_snapshot, ...)       # executor 线程，阻塞跑
  on_process(proc): state_box['process'] = proc      # 子进程 start 后回调，存句柄
  on_manifest(m): → queue.put(manifest_msg)          # 子进程 → 主进程回调
  on_report(r): r['index']=N; → queue.put(r)         # density 双口径已在 proc 版换算
  → return (process, final_data, elapsed, err)
  ↓
run_solve 末尾: queue.put(final|error) + queue.put(SENTINEL)

write loop (内联主流程):                              # drain queue → ws.send_json
  while (item=await queue.get()) ≠ SENTINEL:
    if state_box['stopped']: continue               # stop 后丢弃残余 frame
    ws.send_json(item)
  break → finally: ws.close() + terminate process

read loop (后台 task):                               # 持续读客户端消息
  while True: cmsg = await ws.receive_json()
    if cmsg.action == 'stop':
      stopped=True → terminate+join → ws.send_json(stopped) → queue.put(SENTINEL) → return
  except WebSocketDisconnect: stopped=True → terminate+join
```

`SENTINEL` 由 `run_solve`（自然完成）或 `read_loop`（stop）投递，write loop 收到即 break → finally 显式 `ws.close()` + cancel read_task + terminate process 兜底。

## 坐标系（贯穿 PNG / DXF / 前端 SVG）

- **sparrow 世界坐标**：X = 用布长度（0..width），Y = 门幅（0..gate），**Y 向上**。
- **前端 SVG**：`scale(1,-1)` 翻转后与 PNG 一致（Y 向下）。
- **DXF 导出**：同世界坐标（Y 向上），R12 POLYLINE。
- 三者几何口径一致，导出文件可直接对应屏幕观感。

## 关键不变量（改后端勿破坏）

1. **density 双口径**：frame/final 的 `density` 必须是原面积口径（`total_area/(width*gate)`），`density_sparrow` 才是 spyrrow 自报。前端 90% 生死线判定用 `density`。
2. **导出用原始轮廓非 eroded**：`_PIECES_STATE['pieces_by_id']`（US-020 替代旧 `PIECES_BY_ID`）持有原始 polygon；`placed_to_world` 用它变换。eroded 多边形只用于求解/屏幕。
3. **DXF 走 R12 + POLYLINE**（非 LWPOLYLINE）：ET2008 读 LWPOLYLINE 轮廓消失。单裁片与 marker 导出均如此。
4. **`server.py` 启动期 `_reload_pieces_state()`**（US-020）：import 时读 intermediate 填 `_PIECES_STATE`；缺失不再让 import 崩（allow-empty）。改启动顺序需保证调用顺序在 `app` 定义前。
5. **WS 首条必须是 `{action:'start'}`**：否则 error 并关闭。accept 阶段 `_get_pieces_state()` 快照一次，整连接 pieces 不变（US-020 关键不变量 AC#5）。**US-026：首条后续可发 `{action:'stop'}`** 终止求解 → server 发 `{type:'stopped'}` → 关闭 WS；客户端断开 → `process.terminate()+join` 防孤儿（不再静默忽略）。
6. **导出文件名 `pct` 而非 `%`**：`排料_码28-30-32_88.42pct_seed0.png`。改格式需同步前端 `useExport.test.tsx` CN decode 用例。
7. **多 seed 并发靠 ThreadPoolExecutor(6)**：seed 间同等 CPU 竞争，排名公平。改 worker 数影响多 seed 对比语义。每个 seed 独立子进程（US-025 进程化），互不干扰。
8. **`_PIECES_STATE` 改写只能走 `_reload_pieces_state()`**：threading.Lock 保护，immutable snapshot 模式（整体 `clear()+update()`）。任何路由读 pieces 都走 `_get_pieces_state()`，**不再直接引用旧顶层常量 `PIECES / GATE_MM / PIECES_BY_ID`**（已删除）。

## 入口（`pyproject.toml` `[project.scripts]`）

| 命令 | 模块 | 作用 |
|------|------|------|
| `ms-web` | `materialsorting.web.server:main` | 启动排料工作台（uvicorn :8000） |

> 其它 `ms-*` 入口（解析/导出 intermediate/实验）见 [agent-file-map.md](agent-file-map.md)。
