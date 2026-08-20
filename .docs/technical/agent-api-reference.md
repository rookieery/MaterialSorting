# Agent API 参考 — 排料可视化工作台后端

> 后端 HTTP / WebSocket 契约文档。改 `web/server.py`（含 2026-08-20 拆出的 `runtime.py`/`parse_payload.py`/`routes_views.py`/`routes_ws.py`）/ `web/solver.py` / `web/export.py`（含拆出的 `export_geometry/png/dxf/plt`）任一处先看这里，并同步本文件。
> 入口：`ms-web`（console_script）→ `materialsorting.web.server:main` → uvicorn `127.0.0.1:8000`。

## 状态

单页工作台后端，9 个 HTTP 端点 + 1 条 WS。**US-026 起求解用 `solve_with_callback_proc`（多进程版）**：`ThreadPoolExecutor(max_workers=6)` 跑 `run_solve` → `solve_with_callback_proc` spawn 子进程执行 sparrow solve，主进程 drain `multiprocessing.Queue` 分发 manifest/frame/final（多 seed 最多 6 路并发，seed 间同等 CPU 竞争 → 排名仍公平）。WS 双向并发：write loop drain queue → `ws.send_json`；read loop 持续读客户端消息（`{action:'stop'}` → terminate 子进程 → 发 stopped → 关闭 WS）。**`server.py` 启动期 `_reload_pieces_state()` 读 intermediate 填入 `_PIECES_STATE`**（US-020：commit 后可 reload，allow-empty 不再让 import 崩）。US-004 起 `/api/parse-dxf` 上传解析也复用这个 6-worker 线程池跑 CPU 密集的 DXF 深度解析（`collect_pieces_with_details`）。strategy PRD US-004 起 `/api/strategy/*` 四路由（`web/strategy.py`）spawn `ms-run-config --strategy` 子进程跑双模式长跑（HTTP 轮询 run_dir 产物，无 WS），见下「策略桥接」。

## 启动约束（重要）

1. `server.py` 顶层执行 `_reload_pieces_state()` —— import 时读 intermediate 填入 `_PIECES_STATE`（US-020；2026-08-20 拆分后该逻辑在 `runtime.py`，server.py 首个 import 即触发，顺序与拆分前一致）。intermediate 缺失**不再让 import 崩**：`_PIECES_STATE={}` 时 `/api/ptypes` 返 `{representatives:{}}`、`/ws/solve` 报「排料数据为空」、`/export` 报「placed 的 pid 均未匹配」。intermediate 由 Web commit（`/api/commit-to-nesting`）生成，首次启动空 state 正常，前端上传母版后自动 reload 填入。
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
| POST | `/api/parse-dxf` | US-004：multipart 上传母版 DXF → 深度解析 + g 码赋号 JSON | `server.parse_dxf` |
| POST | `/api/commit-to-nesting` | US-010：把上传母版转排料 intermediate（Path A 全管线，覆盖写回 + .bak）+ US-020 commit 后 reload `_PIECES_STATE` | `server.commit_to_nesting` |
| GET | `/api/ptypes` | US-020 D10（US-001 v2：键 = g 码 label）：返回当前 `_PIECES_STATE` 下每个 g 码的代表裁片（最小码内 parse 同序首个，含 `label` 编号），供前端高级配置弹窗缩略图/放大预览（D11 layer-aware） | `server.get_ptypes` |
| POST | `/api/strategy/start` | strategy US-004：spawn `ms-run-config --strategy` 子进程启动双模式长跑（202） | `strategy.strategy_start` |
| GET | `/api/strategy/status` | strategy US-004：无状态惰性轮询 run_dir 产物组装进度 | `strategy.strategy_status` |
| POST | `/api/strategy/stop` | strategy US-004：树杀子进程（taskkill /T /F / killpg）+ 清 marker | `strategy.strategy_stop` |
| GET | `/api/strategy/result` | strategy US-004：done/stopped run → best + manifest（应用到主画布数据源） | `strategy.strategy_result` |
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
  ],
  "filename": "M1787.dxf"         // 可选：上传母版名（uploadStore.doc.filename 前端透传），
                                  //   作导出文件名前缀（去 .dxf）；缺省回退「排料」/nesting
}
```

### 响应

- 成功：文件字节流，`Content-Disposition: attachment; filename="<ascii>"; filename*=UTF-8''<quoted-cn>`
  - 文件名前缀 = payload `filename` 去扩展名（多个款号同时排料导出凭前缀区分）；缺省回退 `排料`（中文）/`nesting`（ascii）。ascii fallback 前缀仅在前缀纯 ASCII 时用，含中文回退 `nesting`
  - ascii 名：`<prefix_ascii>_<sizes>_<pct>.2fpct_seed<seed>.<ext>`（前缀缺省 `nesting`）
  - 中文名：`<prefix_cn>_码<sizes>_<pct>.2fpct_seed<seed>.<ext>`（前缀缺省 `排料`；走 RFC 5987 `filename*=UTF-8''` + `urllib.parse.quote`；**文件名用 `pct` 不用 `%`**）
  - PNG：`media_type=image/png`，`render_png`（matplotlib Agg，标题 + 类型图例）
  - DXF：`media_type=application/dxf`，`write_marker_dxf`（R12 + POLYLINE，ACI 上色 + ASCII 标题）
  - PLT：`media_type=application/plt`，`write_marker_plt`（US-033；HPGL/HP-GL 文本，封装口径对齐生产 PLT `data/PC-20250508NJIF*.plt`：头部 `IN;PS<纸长>;SP1;PW0.08;` + 5 层 SP1-SP5 笔号（门幅框并入 SP1）+ 尾部 `PU;PG;`，CRLF 行尾，无 VS/LB；喂 WT V8.8 + LIKE 绘图仪原生 PLT 链路；**2026-08 现场撞机修正**：内容压进绘图仪 Y 可写幅宽 `PLOT_SAFE_MAX_Y_MM=1910`（半平面裁剪削平不缩放，越界裁片记 warning）、PD 分块 ≤10 点/行 ≤110B、全体 X 加走纸引导 `PLOT_LEAD_X_MM=20`，详见下表）
- 400：`width_mm<=0` 或 `placed` 空 → `{"error":"无可导出的方案（width=0 或无裁片）"}`；`placed` 的 pid 全匹配不到 → `{"error":"导出失败：placed 的 pid 均未匹配到原始轮廓"}`；未知 fmt → `{"error":"未知格式 <fmt>"}`。

### 导出关键函数（`web/export.py` 门面；2026-08-20 拆分后实现在 `export_geometry/png/dxf/plt` 四模块，门面 re-export 全部旧符号，import 路径不变）

| 函数 | 签名 | 说明 |
|------|------|------|
| `apply_transform` | `(polygon, rotation_deg: float, translation) → [(x,y)...]` | `world = R(θ)·(x,y)+(tx,ty)`，与前端 `pointsStr` 同公式 |
| `placed_to_world` | `(placed, pieces_by_id) → [{pid,size,polygon,color,area_mm2,label,...}]` | pid 查 `_get_pieces_state()['pieces_by_id']`（US-020）取**原始** polygon → 世界坐标（直查 intermediate，零重放）；查不到的跳过并 warning。US-002：输出无 `ptype` 键，`color = size_color(size)`（尺码 16 色循环表，2026-08-20 起同码同色跨片型，与求解屏幕同色） |
| `render_png` | `(world_pieces, *, width_mm, gate_mm, title) → bytes` | matplotlib Agg，dpi=200，配色 `size_color`（尺码 16 色循环表），图例条目 = 本次 placed 的尺码并集（数值序），标题「尺码」 |
| `write_marker_dxf` | `(world_pieces, *, width_mm, gate_mm, title) → bytes` | ezdxf R12 + 闭合 POLYLINE（首尾补点），ACI = `size_aci(size)` = `((size - 28) % 24) + 1`（非数字兜底 7），ASCII 标题；**不用 LWPOLYLINE**（ET2008 轮廓消失坑） |
| `write_marker_plt` | `(world_pieces, *, width_mm, gate_mm, title) → bytes` | US-033 HPGL/HP-GL 纯文本，**封装口径对齐生产 PLT**（`data/PC-20250508NJIF*.plt`）：头部 `IN;PS<纸长>;SP1;PW0.08;`（PS 纸长 = 走纸引导 + max(用布长度, 内容最大X 含刺口延伸) + 尾余量，×40；无 PS 时 WT 按默认 A0/A3 页幅裁切 7m+ marker）→ 逐片 SP1-SP5 → 尾部 `PU;PG;` 出纸；**CRLF 行尾**；**无 VS/LB 指令**（`title` 仅保签名不输出）；坐标=mm×40 round 取整，5 层笔号 SP1=outline+门幅框/SP2=net/SP3=internal/SP4=notch/SP5=grain；空层跳过；纯 ASCII bytes（无临时文件，无新 pip 依赖）；与 DXF 同闭合策略。**2026-08 现场撞机修正（对照生产 PLT 逐项核出的设备级差异）**：① 安全幅面 —— 内容按 `y ≤ PLOT_SAFE_MAX_Y_MM=1910` 半平面裁剪（**削平不缩放**，绝不变形），门幅框上沿压进可写幅宽（Y 内缩 `PLOT_BORDER_MARGIN_Y_MM=5`），越界裁片记 warning；与求解约束带 `NEST_GATE_MM=min(门幅,1910)` 同一事实源（`nesting_bounds/load_pieces.py`），此处裁剪是二道防线；② PD 分块 —— `_plt_polyline` 单条 PD ≤10 点（`_PLT_PD_MAX_PTS`）且整行 ≤110B（`_PLT_LINE_MAX_BYTES`）续画（对齐 ET 生产 ≤11 点/≤118B；国产 HP-GL 解释器行缓冲仅百余字节，超长单条溢出后坐标流错位 → 小车乱走须急停）；③ 走纸引导 —— 全体 X + `PLOT_LEAD_X_MM=20`（生产 PLT 内容 24mm 起画，贴 0 起画无定位余量），Y 不平移；HPGL 坐标非负整数，clamp 兜底取整负值 |
| `_plt_frame_stats` | `(world_pieces, *, width_mm, gate_mm) → (n_out, max_x)` | 越界防御 + PS 纸长取值：全层顶点 + notch 点须在门幅框内（容差 0.5mm），非 0 记 warning（曾因 notch 未随片旋转产生 600 越界点把 WT 预览拉变形）；notch 沿法线 ±`NOTCH_LEN_MM/2` 端点外伸属工艺正常，只计入 max_x（PS 取值）不告警 |

`size_aci(size)`（2026-08-20 起尺码键，取代 US-002 的 `label_aci` g 码公式；更早的 `TYPE_ACI` 中文名色表 US-002 已删）：尺码 → ACI 色号 `((size - SIZE_ANCHOR) % 24) + 1`（28→1、51→24、52→1 循环；非数字/None 兜底 7）。配色单一真相源 `sparrow_baseline.size_color`（`SIZE_PALETTE` 16 色 d3 系循环表，`size_color(size) = PALETTE[(size - SIZE_ANCHOR) % 16]`，锚点 `SIZE_ANCHOR=DEFAULT_SIZES[0]=28` 稳定绝对映射、同码同色跨片型），solver manifest / PNG / DXF ACI / CLI SVG 四处同源取色。PNG/DXF 每片 g 码文字叠印不变（颜色=尺码、文字=片型互补编码）。

## POST /api/parse-dxf — US-004 母版上传解析

`multipart/form-data` 上传单个 `.dxf` 母版 → 服务端落盘 + 调 `dxf_parser.collect.collect_pieces_with_details` 深度解析 → 按码号分组 + 几何稳定排序 + `assign_codes` g 码赋号的 JSON。CPU 密集解析走 `loop.run_in_executor(_executor, ...)` 复用 6-worker 线程池（与 `/ws/solve` 同池，防阻塞 WS 事件循环）。前端 US-005 `useParseDxf` 经相对路径 fetch（dev 走 Vite proxy `/api`，prod 同源）。

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
          "label": "g01",                         // US-001 v2：g 码（0→g01, 1→g02 ... 零填充两位）；name/ptype/paired 已删除
          "polygon": [[x, y], ...],               // layer1 毛版外轮廓
          "internal_lines": [[[x, y], ...], ...], // layer8 POLYLINE 内部线（多条）
          "notches": [[x, y, nx, ny], ...],       // layer4 POINT 刀口：点 + 单位外法线（沿法线画 8mm 短线段）
          "net_polygon": [[x, y], ...],           // layer14 POLYLINE 净版轮廓；无则 []
          "grain_line": [x1, y1, x2, y2]          // layer7 LINE 布纹线；无则 null
        },
        // ...g02..g10（M1787 每码 10 片）
      ]
    },
    // ...29-38 共 11 码
  ]
}
```

**全码一次返回**（M1787 实测 ~680KB JSON / 110 片 / 11 码，远低于 1-3MB 上限）；前端按 `activeSize` 本地切片，不做按码懒加载。

### g 码编号（US-001 v2，名称字段全删）

每片 `label` = 该码内 `g01+` 零填充编号（单一真相源 `nesting_engine/labeling.py`）。**`name` / `ptype` / `paired` 已删除**：名称识别（GROUP_NAMES）与配对镜像（PAIR_TYPES）整体退场，排几份完全由前端 `quantities[label][sizeKey]` 表达（数量即一切，WYSIWYG：母版 N 个轮廓 → intermediate N 条）。前端已于 US-003 收口（全链路 g 码：types/parsed.ts 无 name/ptype/paired，QtyMatrix/高级配置/预览均显 g 码）。

### 排序 + 标注

每码内裁片按以下键稳定排序后赋 `g01+`（`labeling.assign_codes`，顺序模式）：

```
key = (group_key, -centroid_y, centroid_x, -area_mm2, block_name, piece_index)
```

→ **T4：`group_key` 前置**（block 名派生的组标识，名称无关）—— 同一 block 模板跨码同号；组内按质心 Y 大者（视觉上方）优先、X 小者（视觉左）优先、面积大者优先，同质心/面积按 `block_name` 字典序 + `piece_index` 兜底。母版 block 名自带显式编号且每码 all-or-nothing 命中 → 整体复用母版码（输出按码数值序）。码号分组排序：`size` 升序，`null` 殿后。

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
2. **g 码在每码内独立编号**（US-001 v2）：码 28 与码 29 各自从 g01 起算（不跨码续编）；跨码同号由 group_key 前置排序保证（T4）。
3. **`polygon` 是原始毛版几何**（未归一化 / 未对齐布纹 / 坐标系与母版 DXF 一致），与 intermediate 的 NestPiece polygon（布纹对齐 + 归一化后，US-001 v2 起无镜像变换）不同；US-007 `PiecePreviewSVG` 直接渲染此字段。
4. **`grain_line` 与原始 DXF 同坐标系**（Y 向上），前端 SVG `scale(1,-1)` 翻转后与 PNG/R12 导出一致。
5. **响应大小 ≤ 20MB 解析后压缩**：实测 M1787 ~680KB JSON，前端 `useParseDxf` 一次拿到全码缓存到 Zustand。
6. **上传预览前端契约**：响应字段名（`doc_id` / `filename` / `sizes[].size` / `sizes[].pieces[].{label,polygon,internal_lines,notches,net_polygon,grain_line}`）被 `materialSorting-web/src/types/parsed.ts` 严格镜像（US-001 v2 起 `name`/`ptype`/`paired` 删除，前端 US-003 随动）；改任一字段需同步 `types/parsed.ts` + `useParseDxf.test.tsx` AC#2。前端 hook `useParseDxf` 用 `FormData('file', file)` 发请求，**不手设 Content-Type**（让浏览器自动加 boundary）；成功后默认选中 `sizes[0].size`（最小码）。错误（400/413/422/网络错）统一进 `uploadStore.error`，UI 自取渲染。

## POST /api/commit-to-nesting — US-010 上传母版转 intermediate（Path A）

把 US-004 落盘的母版 DXF 转成排料 intermediate（覆盖 `pieces_intermediate.json`），复用 `export_dxf` + `load_nest_pieces` 全管线。**Path A 实现（US-001 v2 重排：g 码先行、零丢片、零合成）**：服务端跑 `collect_pieces_with_details` → `labeling.assign_codes(pieces)`（最先执行、无名称映射参数）→ 逐片 `write_piece_dxf({label}_{size}.dxf)` + 写 `pieces_manifest.json` sidecar（`[{file,label,size}]`；仅 `size=None` 片跳过，无映射组不再 skip）→ `load_nest_pieces(pieces_dir)`（**manifest 驱动**）→ 写回 `paths.INTERMEDIATE`（schema v2：每母版 size≠None 轮廓恰一条）。CPU 密集管线跑在 `loop.run_in_executor(_executor, ...)` 复用 6-worker 线程池（与 `/ws/solve`、`/api/parse-dxf` 同池，防阻塞 WS）。

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
  "n_pieces": 110,                      // NestPiece 总数（US-001 v2：= 母版 size≠None 轮廓数，无镜像展开）
  "total_area_mm2": 9251644.5,          // 所有 NestPiece 面积之和（mm²）
  "n_written_dxf": 110,                 // 切出的单裁片 DXF 数（{label}_{size}.dxf，写入 uploads/<doc_id>_pieces/）
  "n_skipped": 0,                       // 跳过片数（US-001 v2 仅 size=None 会跳过；无映射组不再 skip）
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

1. **临时单裁片目录**：`paths.OUT_DIR/uploads/<doc_id>_pieces/`（`{label}_{size}.dxf` × N + `pieces_manifest.json` sidecar，每次 commit 先 `shutil.rmtree` 再重写，**idempotent**，同 `doc_id` 重跑会覆盖）。文件名仅人读，语义（label/size）全在 manifest —— 旧版目录（无 sidecar）被 `load_nest_pieces` 明确报错「请重新 commit」（FR-9 不静默兼容）。
2. **intermediate 备份**：写回前 `shutil.copy2(paths.INTERMEDIATE, paths.INTERMEDIATE.with_suffix('.bak'))`。`pieces_intermediate.bak` 是上一次写回前的快照（首次 commit 无原文件则跳过备份）。**只保留一份**（再 commit 会覆盖 `.bak`）。
3. **intermediate schema v2（US-001）**：`{doc_id(strategy US-004), source, gate_mm, n_pieces, total_area_mm2, pieces[], label_representatives}`；pieces 字段 `{pid, label, size, polygon, bbox, area_mm2, n_verts, allowed_angles, net_polygon(US-024), internal_lines(US-024), notches(US-024), grain_line(US-024)}` —— **无 `ptype`/`side`**（镜像/名称概念删除），`pid = f'{label}_{size}'`。`gate_mm=1980`（`nesting_bounds.load_pieces.GATE_MM`）、`allowed_angles=[0,180]`（v0.3 布纹线）。5 层字段由 `load_nest_pieces` 经 `_read_piece` + `_apply_layer_transforms` 与 polygon 共享 rotate→normalize transform 链后透传。顶层 `label_representatives`（原 `ptype_representatives`）：每 g 码 RAW 代表裁片（原始坐标，与上传预览同朝向）。`doc_id`（strategy US-004 新增）：commit 的母版原件定位键（`uploads/<doc_id>.dxf`，策略 start 的 config `master_dxf` 来源）；**旧 intermediate 无此键 → `/api/strategy/start` 422「母版信息缺少 doc_id，请重新上传并 commit」**。旧 v1 intermediate 被 `solver.load_pieces` 明确拒绝（「intermediate 为旧版 schema v1（含 ptype/side），请重新 commit 母版生成新数据」）。
4. **commit 后 reload（US-020）**：`_commit_to_nesting_sync` 成功 → 立即调 `_reload_pieces_state()` 重读 intermediate 填入 `_PIECES_STATE`（threading.Lock 保护，原子替换）。下一次 `/ws/solve` / `/export` / `/api/ptypes` 即看到新裁片，**前端无需重启 ms-web**。reload 异常（罕见 I/O 竞态）降级为 `reloaded: false` + `reload_error` 字段，保留旧 state 不半切。

### 关键不变量

1. **全码**：manifest 覆盖母版实际全码（`sorted({p.size for p in pieces if p.size is not None})`），**不沿用 `DEFAULT_SIZES`**（8 码跳 32）。M1787 实测 11 码 [28-38] → 110 NestPiece（US-001 v2：= 母版轮廓数；旧 176 为镜像 L/R 合成口径，已删）。
2. **零丢片零合成（US-001 v2）**：无 GROUP_NAMES 映射组不再 skip（名称识别整体退场，未录入名称/无名 block 的新款母版全片有 g 码）；程序不合成镜像，marker = 母版轮廓 × 用户数量（WYSIWYG）。
3. **NestPiece 5 层全透传**：毛版/净版/内部线/刺口/布纹随 polygon 共享 rotate→normalize 变换链（无 mirror 分支）。
4. **回归等价（历史口径，v1 时代）**：旧版 commit 产物与历史全码 CLI 管线等价（实测 176/176、零面积 diff）；v2 起验收口径改为「intermediate 条数 = 母版 size≠None 轮廓数 + parse↔intermediate 逐片 label 对齐（AC#5）」，`tests/test_commit_pipeline.py` 覆盖。
5. **路径一律走 `paths`**：`paths.OUT_DIR/uploads/`、`paths.INTERMEDIATE`、`paths.INTERMEDIATE.with_suffix('.bak')`；不硬编码 `..` 上溯。

## GET /api/ptypes — US-020 裁片 g 码代表（D10/D11；US-001 v2：键 = label）

返回当前 `_PIECES_STATE` 下每个 g 码（label）的代表裁片，供前端高级配置弹窗表头缩略图 + 点击放大预览（US-018）。

### 请求

无入参，GET。响应直接读 `_get_pieces_state()` 内存常量，**不走文件 I/O**（μs 级响应）。

```bash
curl http://127.0.0.1:8000/api/ptypes
```

### 响应（200）

```jsonc
{
  "representatives": {
    "g01": {"label": "g01", "polygon": [[x,y], ...]},
    "g02": {"label": "g02", "polygon": [[x,y], ...]},
    // ... g03..g10（US-001 v2：键 = g 码；每个代表自动带 net_polygon / internal_lines / notches / grain_line 5 层）
  }
}
```

### 字段透传白名单（`_LABEL_REPRESENTATIVE_FIELDS`）

`('label', 'polygon', 'net_polygon', 'internal_lines', 'notches', 'grain_line')` —— **layer-aware（D11）**：intermediate 5 层自动带后 4 个字段；`label` = 代表裁片在上传预览里的 g 码编号，前端按数据有无自适应渲染。

### 关键不变量

1. **空 state（首次启动未 commit / intermediate 缺失）**：返回 `{representatives: {}}`，不阻塞前端 —— 高级配置弹窗列集退化（rep 缺失的 g 码缩略图 button disabled + 显示 g 码首字占位，loading 态「…」），矩阵仍可配置（后端命不中为 no-op）。
2. **代表选取 + 编号与上传预览同口径（US-001 v2）**：优先取 intermediate `label_representatives`（RAW 原始坐标；键 = g 码，选取 = 按码升序 + 码内 `parse_member_sort_key` 稳定排序，每 label 取**最小码内首个** size≠None 片，与 `/api/parse-dxf` 赋号同键同序 —— 高级配置弹窗编号徽章与上传预览 QtyMatrix 列头指同一片，有 `tests/test_label_representatives.py` 回归）。旧 v1 intermediate 无该字段 → 回退 `pieces` 按 label 分组取首个代表，re-commit 后自动切 RAW 口径。
3. **M1787 验证**：commit 后返 10 个 g 码（`g01`..`g10`，各 5 层字段全带）。
4. **响应字段不含 pid / size / area**：仅几何 + label；g 码是 key。前端 polygon 画缩略图、label 画编号徽章。

## 策略桥接（strategy PRD US-004）— `/api/strategy/*` 四路由（`web/strategy.py`）

桥接方式 = **spawn `python -m materialsorting.cli.run_config <cfg> --name web_<mode>_<rand6> --strategy <mode> --time <minutes*60> --quiet` 子进程 + HTTP 轮询 run_dir 产物**（分层零违规：进程边界而非 import 边界 —— `strategy.py` 全模块禁 import `..cli.*`，AST 守卫 `tests/test_web_strategy.py`；判据逻辑单一真相源留在 `cli.portfolio`）。子进程经 env 继承拿到与 ms-web 相同的 `paths`（`MS_OUT_DIR` 等环境变量父子同源）。前端消费方 = 策略 PRD US-005 弹窗（`strategyStore` + `useStrategyPoll`，详见 `agent-component-map.md` US-005 专节）：GET status 轮询双档 **弹窗开 2s / 关 15s**（关弹窗由入口徽标维持观测），terminal 态停表；start 载荷 = 面板排料参数 + `{mode, minutes}`；**关闭弹窗（ESC/遮罩/✕）不调 stop** —— 终止唯一入口 = 显式终止/清理按钮。

状态机：`idle → starting →（run_dir 快照 diff 发现）running → done | stopped | error`；内存态空 + marker 在 → `orphan`。marker = `out/config_runs/.web_strategy_active.json` 恰 5 键 `{pid, run_dir, doc_id, mode, started_at}`（run_dir 初始 null、发现后回写；终态清 marker、内存态 `_STRATEGY_STATE` 保留供 status/result 续读）。

### POST /api/strategy/start — 启动策略 run

请求 `{mode: 'se'|'race', minutes: 10|20|30|60, seed?, gate_mm?, sizes?, per_type?, quantities?}`（sizes/per_type/quantities 与 WS StartPayload 同语义 —— 前端「排料参数取当前面板」）。

- 409：已有进行中 run（内存态非终态）或 marker 在（含 orphan 遗留，先停止/清理）
- 422：`_PIECES_STATE` 空；intermediate doc 缺 `doc_id`（旧 intermediate → 「母版信息缺少 doc_id，请重新上传并 commit」）；`uploads/<doc_id>.dxf` 丢失
- 400：mode 非法 / minutes 非法（含字符串）/ seed 非整数
- 202：写 7 键 config JSON 到 `out/uploads/strategy_cfg_<stamp>.json`（`master_dxf` = 母版原件**绝对路径**；`gate_mm` 请求值回退 state；`seeds=[seed]`；可选键 truthy 才写）→ spawn（stdout=DEVNULL、stderr=临时文件）→ 快照 `out/config_runs/`（**先于 spawn**，防 CLI 抢先建目录 diff 扑空）→ 写 marker → `{started, pid, mode, minutes, run_name}`

### GET /api/strategy/status — 无状态惰性轮询

每次现读产物组装（不缓存中间态）；进度源白名单 `strategy.json` / `result.json` / `best_frame_s*.json` / `kill_decisions.jsonl` —— **绝不读 `curve_s*.json`**（运行中缺右括号非法 JSON）。响应 `{state, mode, total_budget_sec, elapsed_sec(墙钟), run_dir, plan, incumbent, current, per_seed, events, error, exit_code}`：

- `plan`：strategy.json → `{planned_seeds, gate_seconds}`（race）| `{planned_seeds, k_screens, screen_s, ext_s}`（se）
- `incumbent`：result.json portfolio.incumbent 摘要 `{density, width_mm, seed, frame_index, elapsed}`（**无 placed_items** 控载荷）
- `current`：最新 mtime `best_frame_s*.json` → `{seed, density, density_sparrow, ext}`（`_ext` 后缀 → ext=true，SE 延长检测）
- `per_seed`：result.json portfolio.per_seed 透传（含 `phase`: race/screen/extension、`killed`）
- `events`：kill_decisions R5_race_gate 行（`S_tau` 重载为 bar 参照值）+ extension（`best_frame_s{seed}_ext.json` 在场）+ seed_done（per_seed），只保留尾部 20 条
- 缺文件一律降级 null / `[]`；run_dir 未发现 + 进程死 + >30s 宽限 → `error`（附 stderr 尾部 2000 字符）；终态顺手清 marker 并把 state 写回内存态

### POST /api/strategy/stop — 树杀

Windows `taskkill /PID <pid> /T /F`（`/T` 整树 —— run_config 会 spawn 多进程 solve 孙进程，单杀父进程留孙进程白烧 CPU）；POSIX spawn 带 `start_new_session=True` + `os.killpg`。进行中 → 置 stopped + 清 marker；orphan（内存空 + marker 在）→ pid 存活则树杀 + 清 marker；无活动 → 400。

### GET /api/strategy/result — 最优方案 + manifest（US-006 应用到主画布数据源）

done/stopped 可读（running → 409「尚未结束」；idle → 404）。响应 `{state, mode, run_dir, manifest, best, summary, warning?}`：

- `best`：result.json `portfolio.incumbent`（完整 `placed_items`；**无 `density_sparrow`** —— 从 `best_frame_s{seed}.json` 边车补，缺则 null）；stopped 无 result.json → 回落各 `best_frame_s*.json` 取 density 最大
- `manifest`：`build_pid_meta(start 时快照 pieces, sizes/per_type/quantities 同口径)` → `{gate_mm, gate_nest_mm, total_area_mm2, n_eroded, pieces:[{id,size,color,area_mm2,polygon(erode 后),label,demand,net_polygon,internal_lines,notches,grain_line}]}`（与 /ws/solve manifest.pieces 同形；erode 后几何与 placed_items 对齐、demand 已含 —— 前端 NestSVG 副本池按 demand 建 N 份承接多副本 placement）
- `summary`：`{per_seed, mode, race?|se?}`（result.json portfolio 模式段透传）
- `warning`：start 快照 `doc_id` ≠ 当前画布 `doc_id` → 「母版已变更，应用结果可能与当前画布不一致」（导出 pid 失配走既有 400 兜底）

### 关键不变量

1. **server.py 文件尾** `from .strategy import register_strategy_routes` 注册路由；`strategy.py` 对 server 的依赖走**函数内延迟 import**（`_pieces_state()`）—— 任意 import 顺序不成环。
2. start 时 `sizes/per_type/quantities/seed/gate_mm/pieces` 快照存模块级 `_STRATEGY_STATE` —— result 组装 manifest 用同口径，不依赖前端二次回传。
3. `_status_from_active` 把解析出的 state **写回** `st['state']`（否则「跑完后从未轮询」内存态永远停在 running，start 单例检查失效）。
4. orphan `_pid_alive`：Windows `ctypes kernel32.OpenProcess(0x1000)` 句柄探测（非本进程孩子无法 poll）；报 `state:'orphan' + alive` 由前端提供清理动作，不自动接管。

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
  "sizes": [28, 29, 30, 31, 33, 34, 35, 36],  // 码号；空 = 全部片（intermediate 全量，M1787 = 110 片全 demand=1）
  "time": 120,                    // 求解时间预算（秒），默认 120
  "seed": 0,                      // sparrow 随机种子，默认 0
  "params": {"d_ext":0, "d_int":0, "tol_ext":0, "tol_int":0},  // US-019 起前端永远传全 0；主面板内外两档输入已删，d/tol 覆盖全交 per_type
  "per_type": {"g03": {"d": 1.5}},  // 可选，逐片高级覆盖（US-002 起 label 键；2026-08-18 回退 US-004 矩阵化后单级，命中即对该 g 码全部码号生效；旧 ptype / 旧两级 (label,sizeKey) 键不命中为 no-op）
  "quantities": {"g01": {"28": 2, "30": 0}, "g02": {"28": 1}}  // US-022 可选，label→sizeKey→demand；0=该 piece 该码不排；缺省=null→全片 demand=1
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
      // US-002：全 label 键（无 ptype）；color = size_color(size)（2026-08-20 尺码键）
      "id": "g03_30", "label": "g03", "size": 30, "color": "#...", "area_mm2": <int>,
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
  "density": 0.8983,              // ★ 原面积·实际幅宽口径 real = total_area/(width*min(gate,1910))（与 90% 生死线一致）
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
| `build_pid_meta` | `(pieces, *, sizes=None, per_type=None, quantities=None, params=None) → (pid_meta, total_area, n_eroded)` | **strategy US-004 自 `build_instance` 提取**的裁片级流水线（**不 import spyrrow、不构造求解对象** —— `/api/strategy/result` 组装 manifest 直接用）：sizes 过滤 → demand 判定（quantities 按 `(label, str(size))` 查 N，0=跳过；缺 label→1）→ per_type 覆盖 + 全局上限钳制（`_resolve_d_tol` 单一真相源，与 `build_instance` 的 Item orientations 同口径）→ erode/清洗（<3 顶点跳过）→ pid_meta 条目（US-024 5 层 + label/color/demand）→ `total_area=Σ(area×demand)`。对拍单测（`test_web_strategy.py`）保证提取前后 `build_instance` 输出逐字段一致 |
| `discretize_orientations` | `(tol: float) → list[float]` | v0.3 连续旋转公差 → spyrrow 离散角度集。`tol=0→[0,180]`；`tol≤5` 步进 1°；否则 5°。归一化到 [0,360) |
| `build_instance` | `(pieces, gate_mm, *, time_budget, seed, sizes=None, params=None, per_type=None, quantities=None, solver_opts=None) → (instance, config, pid_meta, total_area, n_eroded)` | strategy US-004 起裁片级流水线（sizes/demand/per_type/erode/pid_meta/total_area）**委托 `build_pid_meta`**（单一真相源），本函数补 spyrrow 侧构造：`Item`（shape 用 pid_meta 的 erode 后 polygon、orientations 用同口径 `_resolve_d_tol` 的 tol 离散化）。按 sizes 过滤 → US-022 按 `(label, sizeKey)` 查 quantities 定 demand（0 跳过；缺 label → 1） → US-002 起 `per_type[label]` 命中即覆盖 d/tol（2026-08-18 回退 US-004 后 label 单级，命中即对该 g 码全部码号生效；未命中/缺维度回退 `params.d_ext/tol_ext`；旧 ptype / 旧两级键 no-op；internal 概念已删，`d_int`/`tol_int` 仍被接受但无消费方） → 每片 `erode=min(申请d, MAX_OVERLAP_MM=10)`、`tol=min(申请tol, MAX_ROTATION_TOL_DEG=45)`（**2026-08-17 起全局上限，不再按片型**） → erode+clean → 构造 `spyrrow.Item` + `StripPackingInstance(strip_height=min(gate_mm, PLOT_SAFE_MAX_Y_MM))` + `StripPackingConfig`；pid_meta 含 US-024 5 层字段 + `label`/`color=size_color(size)`（2026-08-20 尺码键）/`demand`（`.get()` 向后兼容）。**求解约束带钳绘图仪可写幅宽 1910**（gate_mm 1980 是显示口径，manifest 推给前端的 gate_mm / 密度分母 / 导出外框均不受影响；常量单一事实源 `nesting_bounds/load_pieces.py`）。**US-006（PC-006）`solver_opts`**（additive 白名单 exploration_pct/quadtree_depth/num_workers 三键，越界 clamp、非数值/未知键忽略、不传=现行行为）：`exploration_pct∈[0.1,0.95]` 把 time_budget 换算为 exploration_time/compression_time 两段 int 秒（各 ≥1s、和≈budget，**与 total_computation_time 互斥** —— spyrrow 的 total 键缺省 600 非 None，两段模式必须显式传 total_computation_time=None，否则 not-all-3 ValueError）；quadtree_depth∈[3,5]（缺省 4）、num_workers≥1（缺省 4）。清洗单一真相源 `_normalize_solver_opts`。WS 协议本期不加字段（web 前端零改动），消费方仅 CLI --solver-opts/--rotate-opts |
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

1. **density 双口径**：frame/final 的 `density` 必须是原面积·实际幅宽口径（`total_area/(width*min(gate_mm, PLOT_SAFE_MAX_Y_MM))`，2026-08-20 起与求解约束带同口径；manifest 另带 `gate_nest_mm` 供前端画实际排料边界红虚线），`density_sparrow` 才是 spyrrow 自报。前端 90% 生死线判定用 `density`。
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
