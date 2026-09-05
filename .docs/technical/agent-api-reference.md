# Agent API 参考 — 排料可视化工作台后端

> 后端 HTTP / WebSocket 契约文档。改 `web/server.py`（含 2026-08-20 拆出的 `runtime.py`/`parse_payload.py`/`routes_views.py`/`routes_ws.py`）/ `web/solver.py` / `web/export.py`（含拆出的 `export_geometry/png/dxf/plt`）任一处先看这里，并同步本文件。
> 入口：`ms-web`（console_script）→ `materialsorting.web.server:main` → uvicorn `127.0.0.1:8000`。

## 状态

单页工作台后端，15 个 API 端点（另含 `GET /` 与 `/static` mount）+ 1 条 WS。**US-026 起求解用 `solve_with_callback_proc`（多进程版）**：`ThreadPoolExecutor(max_workers=6)` 跑 `run_solve` → `solve_with_callback_proc` spawn 子进程执行 sparrow solve，主进程 drain `multiprocessing.Queue` 分发 manifest/frame/final（多 seed 最多 6 路并发，seed 间同等 CPU 竞争 → 排名仍公平）。WS 双向并发：write loop drain queue → `ws.send_json`；read loop 持续读客户端消息（`{action:'stop'}` → terminate 子进程 → 发 stopped → 关闭 WS）。**`server.py` 启动期 `_reload_pieces_state()` 读 intermediate 填入 `_PIECES_STATE`**（US-020：commit 后可 reload，allow-empty 不再让 import 崩）。US-004 起 `/api/parse-dxf` 上传解析也复用这个 6-worker 线程池跑 CPU 密集的 DXF 深度解析（`collect_pieces_with_details`）。strategy PRD US-004 起 `/api/strategy/*` 四路由（`web/strategy.py`）spawn `ms-run-config --strategy` 子进程跑双模式长跑（HTTP 轮询 run_dir 产物，无 WS），见下「策略桥接」；extreme PRD US-002 起 `/api/extreme/*` 四路由（同 `web/strategy.py` 内 mode='extreme' 分支）spawn `ms-run-config --extreme` 极限长跑，与策略路由**共用每会话状态槽**（同会话 409 单飞互斥、跨会话独立），见下「极限运行桥接」。

## 启动约束（重要）

1. `server.py` 顶层执行 `_reload_pieces_state()` —— import 时读 intermediate 填入 `_PIECES_STATE`（US-020；2026-08-20 拆分后该逻辑在 `runtime.py`，server.py 首个 import 即触发，顺序与拆分前一致）。intermediate 缺失**不再让 import 崩**：`_PIECES_STATE={}` 时 `/api/ptypes` 返 `{representatives:{}}`、`/ws/solve` 报「排料数据为空」、`/export` 报「placed 的 pid 均未匹配」。intermediate 由 Web commit（`/api/commit-to-nesting`）生成，首次启动空 state 正常，前端上传母版后自动 reload 填入。
2. `app.mount('/static', ...)` 指向 `materialSorting-web/static/`（前端构建产物）。
   - **prod**：先 `cd materialSorting-web && npm run build` 生成 `static/`；
   - **dev**：`npm run dev` 起 Vite :5173，经 proxy 打 :8000（仍建议先 build 一次让 `static/` 存在，避免 mount 空目录报错）。
3. US-004 上传依赖 `python-multipart`（已在 `[web]` extra），落盘目录 `paths.OUT_DIR/uploads/`（启动时按需 `mkdir`）。

## HTTP 路由

| 方法 | 路径 | 说明 | 实现 |
|------|------|------|------|
| GET | `/` | 返回 `static/index.html`（prod 入口）；**多会话 US-003 起响应头带 `Cache-Control: no-cache`**（防部署新 bundle 后旧 index 引用已删 hash 资源、旧前端滞留 default 语义的迁移窗口；FastAPI `FileResponse` 缺省不发缓存头） | `server.index` → `FileResponse` |
| POST | `/api/session` | 多会话 US-001：会话注册 / 幂等刷活性（读 `X-Session-Id` Header；容量上限 / 空闲过期墓碑判定的唯一注册入口），见下专节 | `server.create_session` → `sessions.registry.resolve(create=True)` |
| mount | `/static/*` | 前端构建产物（JS/CSS/资源） | `StaticFiles(directory=paths.STATIC_DIR)` |
| POST | `/export` | 导出最优 run → PNG / R12-DXF 附件下载；**多会话 US-003**：`X-Session-Id` → 该会话 `pieces_by_id`（缺省 → default） | `server.export` |
| POST | `/api/parse-dxf` | US-004：multipart 上传母版 DXF → 深度解析 + g 码赋号 JSON | `server.parse_dxf` |
| POST | `/api/commit-to-nesting` | US-010：把上传母版转排料 intermediate（Path A 全管线，覆盖写回 + .bak）+ US-020 commit 后 reload `_PIECES_STATE` + US-002 多会话：`X-Session-Id` 双写 per-doc intermediate + 会话快照绑定 | `server.commit_to_nesting` |
| GET | `/api/ptypes` | US-020 D10（US-001 v2：键 = g 码 label）：返回每个 g 码的代表裁片（最小码内 parse 同序首个，含 `label` 编号），供前端高级配置弹窗缩略图/放大预览（D11 layer-aware）；**多会话 US-003**：`X-Session-Id` → 该会话快照（缺省 → default `_PIECES_STATE`） | `server.get_ptypes` |
| POST | `/api/band-preview` | 2026-08-24 成带形态预览（高级配置弹窗「布局设置」band 行缩略图数据源）：主进程同步 `build_band_plan`，响应无 `WB_`，见下专节；**多会话 US-003**：`X-Session-Id` → 该会话快照 | `routes_views.band_preview` |
| POST | `/api/prefix-preview` | 2026-08-25 前缀组合形态预览（「布局设置」prefix 行缩略图数据源）：**2026-09-02 US-003 起选码换 `select_prefix_plan` 真相源**（与 solve_worker `_build_prefix` 同函数，4 片兜底或 5 片顶部异码补片；构造段 `run_in_threadpool` 线程池化），成员带 `tag`=g 码，响应 additive `extra`/`residual_mm`/`gate_mm`/`fallback`，无 `PS_`，见下专节；**多会话 US-003**：`X-Session-Id` → 该会话快照 | `routes_views.prefix_preview` |
| POST | `/api/plt-table-preview` | 2026-08-31 导出弹窗唛架表格 14 字段预览（ExportInfoModal 全字段展示数据源）：`build_info_table` + `preview_rows` 同一真相源返 14 行（列序 = 最终表格列序、带 `manual` 标记），见下专节；**多会话 US-003**：`X-Session-Id` → 该会话快照 | `routes_views.plt_table_preview` |
| POST | `/api/edit-hold` | **2026-09-04 编辑排料会话钉住心跳**：编辑弹窗纯前端无请求，长编辑中途空闲过期会被逐出 → 保存后导出 401 丢成果；`resolve()` 闸门（过期 401 不给死会话续命）+ `edit_hold.refresh` 滚动续期（`MS_EDIT_HOLD_SEC` 缺省 2h）；无 sid（default）→ 200 no-op；**多会话**：`X-Session-Id` → 该会话 | `server.post_edit_hold` |
| POST | `/api/edit-polish` | **prd-edit-polish US-002（2026-09-05）编辑排料「智能微调」**：POST 当前编辑 placements（布局态后端不存、随 body = /export 同模式）→ 确定性后处理 `polish_layout` 结果 + 前后对比报告；pid 全匹配才跑（否则 400「母版已变更」）、`run_in_threadpool` 执行 + 顺手 `edit_hold.refresh`，见下专节；**多会话**：`X-Session-Id` → 该会话 `pieces_by_id` | `server.post_edit_polish` |
| POST | `/api/strategy/start` | strategy US-004：spawn `ms-run-config --strategy` 子进程启动双模式长跑（202）；**2026-08-22 起载荷可带 band**（经 `_parse_band` 同一校验点写进 config，成带与策略模式兼容）；**2026-08-25 起载荷可带 prefix**（经 `_parse_prefix` 同一校验点含 2+2 资格码，非法 → 400 早退，写进 9 键 config）；**多会话 US-004（2026-08-27）：读 `X-Session-Id`**（缺省 default）—— 每会话 409 单飞、跨会话并发放开、数据源 = 会话快照 | `strategy.strategy_start` |
| GET | `/api/strategy/status` | strategy US-004：无状态惰性轮询 run_dir 产物组装进度；**多会话 US-004：读 `X-Session-Id`**（status 轮询即活性，长跑会话不被扫描误杀） | `strategy.strategy_status` |
| POST | `/api/strategy/stop` | strategy US-004：树杀子进程（taskkill /T /F / killpg）+ 清本会话 marker；**多会话 US-004：读 `X-Session-Id`**（只树杀本会话 pid） | `strategy.strategy_stop` |
| GET | `/api/strategy/result` | strategy US-004：done/stopped run → best + manifest（应用到主画布数据源）；**多会话 US-004：读 `X-Session-Id`**（只读本会话 run_dir） | `strategy.strategy_result` |
| POST | `/api/extreme/start` | extreme US-002：spawn `ms-run-config --extreme` 子进程启动极限长跑（202）；载荷 `{time_total_s, seed?, gate_mm?, sizes?, per_type?, quantities?}`（**无 band/prefix** —— 在场即 400）；**与 /api/strategy/start 同会话状态槽单飞互斥（409 双向）、跨会话独立** | `strategy.extreme_start` |
| GET | `/api/extreme/status` | extreme US-002：与 /api/strategy/status 同构（同槽轮询，mode 透传 'extreme'；进度源白名单不含 curve_s*.json） | `strategy.extreme_status` |
| POST | `/api/extreme/stop` | extreme US-002：与 /api/strategy/stop 同构（树杀本会话槽内 in-flight run + 清本会话 marker） | `strategy.extreme_stop` |
| GET | `/api/extreme/result` | extreme US-002：与 /api/strategy/result 同构（best + manifest + 母版漂移 warning；mode 透传 'extreme'） | `strategy.extreme_result` |
| WS | `/ws/solve` | 排料求解流（manifest → frames → final）；**多会话 US-003**：`?sid=` query（浏览器 WS 不能自定义 Header；缺省 → default 会话），连接钉住 + 回调刷活性，见下专节 | `server.ws_solve` |

> （已删 2026-08-22）`POST /api/band/preview`（US-013 成带预演回显）与 `routes_band.py` 整体移除 —— 预演 / ack 硬警告 / go-no-go 闸门等成带旁路功能退场，band 收敛为「WS StartPayload band = 勾选 + 选 g 码」极简主流程。

> FastAPI 自动暴露 `/docs` `/openapi.json` 等 OpenAPI 路由；业务路由全在上表。

## POST /export — 导出

前端把**最优 run 的最终帧 `placed_items`** 回传，服务端用**原始母版轮廓**（`pieces_intermediate.json` 的原始 polygon，**非 eroded**）放到排料变换位，保证 PNG / DXF / PLT 三格式几何一致、可直接裁剪 / 绘图。

**多会话 US-003**：可选 **`X-Session-Id` HTTP Header** —— 带 sid → `pieces_by_id` 取该会话 commit（US-002）注册的 per-doc 快照（A 的 placed 匹配 A 的原始轮廓）；缺省 → default 会话（`_PIECES_STATE`，旧行为）。会话解析先于一切导出逻辑（fail-fast）：过期/未注册 sid → `401 {"code":"session_expired",...}`（**JSON 响应非文件流**）、非法 sid → `400 {"error":"sid 非法"}`、超限 → `429 {"code":"session_limit",...}`（HTTP 层 SessionError 统一映射）。

### 请求 payload

```jsonc
{
  "fmt": "png" | "dxf" | "plt" | "plt-clean",  // 必填（US-033 新增 plt；2026-08-31 新增 'plt-clean' 毛版变体——当日由「净版」更名、与裁片 layer1「毛版轮廓」命名统一，见响应节）
  "sizes": [28, 30, 32],          // 码号列表（文件名用，排序后 '-' 拼接；空 → "all"）
  "seed": 0,                      // 文件名标注用
  "gate_mm": 1750,                // run.manifest.gate_mm（多 run 共享）
  "width_mm": 7058.0,             // run.lastFrame.width_mm（用布长度 mm）
  "density": 0.8983,              // run.finalDensity（原面积口径，0..1）
  "placed": [                     // run.lastFrame.placed_items
    {"id": "...", "rotation": 0.0, "translation": [x, y]},
    ...                           // 可选 "mirror": true（edit-keyboard US-004，2026-09-05）：
                                  //   镜像片标志 —— 局部 x 翻转 world=R(rot)·diag(−1,1)·p+t，
                                  //   placed_to_world 5 层几何（毛版/净版/内部线/刺口点+法线/
                                  //   布纹线）全部按镜像变换；omit-when-false —— 前端编辑保存
                                  //   只在 true 时带键，solver 原生帧永无此键 → 缺省路径逐字节
                                  //   不变（路由零改动，placed 键直通）。
                                  //   **edit-keyboard US-007（2026-09-05）端到端几何对拍**：
                                  //   smoke_edit_polish.mjs S8 段锁「正文几何随 mirror 键翻转」
                                  //   —— 期望 = R(θ₁)·M·R(−θ₀)·(镜像前 DXF layer1 顶点−t₀)+t₁
                                  //   （θ/t 取两次导出 POST placed[k]），PLT ≤2 HPGL unit /
                                  //   DXF ≤0.05mm，非镜像反事实 ≥40unit/≥1mm（反证键真实
                                  //   驱动几何）；导出 placed 恰一项 mirror:true 且其余 29 项
                                  //   与镜像前逐位全等。改 apply_transform mirror 分支即红。
  ],
  "filename": "M1787.dxf",        // 可选：上传母版名（uploadStore.doc.filename 前端透传），
                                  //   作导出文件名前缀（去 .dxf）；缺省回退「排料」/nesting
  "table": {                      // 可选（2026-08-30，仅 fmt='plt'/'plt-clean' 消费，PNG/DXF 忽略）：
                                  //   唛架信息表格手输字段，带此键 → PLT 排料图外围附
                                  //   14 字段 key/value 两行网格（v5：key 行带靠唛架/
                                  //   value 行带在外；表格外框左缘与唛架右边框共线
                                  //   （gap=0）、列 0 自右下顶点垂直向上 3cm（y=30mm）
                                  //   起自适应排开、单元格内容居中（10mm 内衬）、
                                  //   单线矢量字（汉字笔画中线 + Hershey ASCII，
                                  //   Noto 轮廓回退）；生产视图里呈水平两行表；不占
                                  //   排料区不计入用料，PS 纸长 =(width+66)×40 覆盖
                                  //   表格区）；缺省不带表格（输出与旧版逐字节一致）
    "bed_no": "153",              // 床次（默认 A料，≤20 字符，超长截断 + warn）
    "warp_shrink": "1.5%",        // 经纱缩水（默认 0.0%，≤12 字符）
    "weft_shrink": "2.0%",        // 纬纱缩水（默认 0.0%，≤12 字符）
    "planner": "张三",             // 排料师（默认空，≤20 字符）
    "style_no": "FC721200B00NIF", // 样板号（默认 noname，≤30 字符）
    "remark": ""                  // 备注（默认空，≤60 字符）
  }                               // v2 起全字段自由字符串（数字宽容转 str、null → 空、
                                  //   非字符串标量/数组/布尔 → 400）；其余 8 字段后端
                                  //   自动算（web/plt_table.py）：方案名称（勾选尺码按
                                  //   系数分组，每码系数 = 面积最大裁片 pid 计数÷2）/
                                  //   本床包含套数/利用率/幅宽(m)/料长(m，不含表格)/
                                  //   每套用料(m)/片数/绘图时间（YYYY-MM-DD HH:MM）
}
```

### 响应

- 成功：文件字节流，`Content-Disposition: attachment; filename="<ascii>"; filename*=UTF-8''<quoted-cn>`
  - 文件名前缀 = payload `filename` 去扩展名（多个款号同时排料导出凭前缀区分）；缺省回退 `排料`（中文）/`nesting`（ascii）。ascii fallback 前缀仅在前缀纯 ASCII 时用，含中文回退 `nesting`
  - ascii 名：`<prefix_ascii>_<sizes>_<pct>.2fpct_seed<seed>.<ext>`（前缀缺省 `nesting`）
  - 中文名：`<prefix_cn>_码<sizes>_<pct>.2fpct_seed<seed>.<ext>`（前缀缺省 `排料`；走 RFC 5987 `filename*=UTF-8''` + `urllib.parse.quote`；**文件名用 `pct` 不用 `%`**）
  - PNG：`media_type=image/png`，`render_png`（matplotlib Agg，标题 + 类型图例）
  - DXF：`media_type=application/dxf`，`write_marker_dxf`（R12 + POLYLINE，ACI 上色 + ASCII 标题）
  - PLT：`media_type=application/plt`，`write_marker_plt`（US-033；HPGL/HP-GL 文本，封装口径对齐生产 PLT `data/PC-20250508NJIF*.plt`：头部 `IN;PS<纸长>;SP1;PW0.08;` + 5 层 SP1-SP5 笔号（门幅框并入 SP1）+ 尾部 `PU;PG;`，CRLF 行尾，无 VS/LB；喂 WT V8.8 + LIKE 绘图仪原生 PLT 链路；**2026-08 现场撞机修正**：门幅框满幅 [0, gate]/内容按输入 gate_mm 裁剪（2026-08-28 起单一幅宽口径；2026-08-31 撤销框 Y 双边内缩 5mm——贴边裁片穿框被切割软件读作越界布料；越界裁片记 warning 兜布局/变换 bug）、PD 分块 ≤10 点/行 ≤110B、全体 X 加走纸引导 `PLOT_LEAD_X_MM=20`、全体 Y 加绘制平移 `PLOT_LEAD_Y_MM=TABLE_W_MM=36`（2026-08-31 用户定案：整张图纸一起离图纸原点 36mm=表格宽、框线左侧留等宽空纸边，首版 5mm 被反馈太短；纯绘制层位移不动求解带/裁剪界/密度口径），详见下表）
  - PLT（毛版）：`fmt='plt-clean'`（2026-08-31；当日由「净版」更名，协议值不变）→ `write_marker_plt(..., clean=True)`，形态对齐生产参考件 `data/PC-20250508NJIF_5028-1#_29223513.plt`：① 带表格时唛架**左右各一份同内容表格**（右表原位不动；左表 = 同一 `info_table_polylines` 以 `table_x0=-(TABLE_GAP_MM+TABLE_W_MM)` 再画一份，key 带落小 x 侧与右表阅读方向一致、无镜像文字，value 带外缘与门幅左边框共线），X 走纸引导随之扩为 `PLOT_LEAD_X_MM+TABLE_GAP_MM+TABLE_W_MM=56mm`（左表世界 x∈[−36,0] → 绘制 x≥20），PS 纸长按扩后 lead 计算；② 正文每片**只画毛版轮廓（polygon）+ 尺码\*数量标注**（标注几何/字高 10mm/字库与全量版全同，仅去杆+箭羽），net_polygon/internal_lines/notches/布纹杆羽全部不画。文件名后缀 `_clean`（ascii）/`_毛版`（中文，更名前一日为 `_净版`）；`clean=False` 输出与旧版逐字节一致（零回归红线）。
- 400：`width_mm<=0` 或 `placed` 空 → `{"error":"无可导出的方案（width=0 或无裁片）"}`；`placed` 的 pid 全匹配不到 → `{"error":"导出失败：placed 的 pid 均未匹配到原始轮廓"}`；未知 fmt → `{"error":"未知格式 <fmt>"}`；`table` 非对象或字段值非字符串标量（数组/对象/布尔）→ `{"error":"信息表格字段非法：<原因>"}`（2026-08-30，`plt_table.parse_table_payload` / `TablePayloadError`；v1 的 `ply_count` 整数校验已随字段集更换删除）。

### 导出关键函数（`web/export.py` 门面；2026-08-20 拆分后实现在 `export_geometry/png/dxf/plt` 四模块，门面 re-export 全部旧符号，import 路径不变）

| 函数 | 签名 | 说明 |
|------|------|------|
| `apply_transform` | `(polygon, rotation_deg: float, translation, mirror: bool = False) → [(x,y)...]` | `world = R(θ)·(x,y)+(tx,ty)`，与前端 `pointsStr` 同公式；**2026-09-05 edit-keyboard US-004 加 `mirror` 缺省 False 第 4 参**：局部 x 先取负再旋转 `world = R(θ)·diag(−1,1)·(x,y)+t`（展开 `x'=−x·c−y·s+tx / y'=−x·s+y·c+ty`，与前端 `editGeometry.transformPolygon` mirror 分支同输入输出逐点相等，单测对拍锁死）；缺省/显式 False 与旧实现逐字节一致（零回归红线） |
| `_transform_normal` | `(nx, ny, rotation_deg, mirror: bool = False) → (nx', ny')` | notch 法线旋转变换（无平移）；**US-004 mirror**：法线是**向量**，反射下 x 分量先取负再旋转（`R(θ)·diag(−1,1)·n`）；缺省逐字节不变 |
| `placed_to_world` | `(placed, pieces_by_id) → [{pid,size,polygon,color,area_mm2,label,...}]` | pid 查 `_get_pieces_state()['pieces_by_id']`（US-020）取**原始** polygon → 世界坐标（直查 intermediate，零重放）；查不到的跳过并 warning。US-002：输出无 `ptype` 键，`color = size_color(size)`（尺码 16 色循环表，2026-08-20 起同码同色跨片型，与求解屏幕同色）。**US-004（2026-09-05）**：读 `it.get('mirror') is True` 贯穿全部 5 层（毛版/净版/内部线点变换 + notch 点按点变换·法线按向量镜像 + 布纹线两端点），`/export` 路由零改动（placed 键直通） |
| `render_png` | `(world_pieces, *, width_mm, gate_mm, title) → bytes` | matplotlib Agg，dpi=200，配色 `size_color`（尺码 16 色循环表），图例条目 = 本次 placed 的尺码并集（数值序），标题「尺码」 |
| `write_marker_dxf` | `(world_pieces, *, width_mm, gate_mm, title) → bytes` | ezdxf R12 + 闭合 POLYLINE（首尾补点），ACI = `size_aci(size)` = `((size - 28) % 24) + 1`（非数字兜底 7），ASCII 标题；**不用 LWPOLYLINE**（ET2008 轮廓消失坑） |
| `write_marker_plt` | `(world_pieces, *, width_mm, gate_mm, title, info_table: InfoTable \| None = None, clean: bool = False) → bytes` | US-033 HPGL/HP-GL 纯文本，**封装口径对齐生产 PLT**（`data/PC-20250508NJIF*.plt`）：头部 `IN;PS<纸长>;SP1;PW0.08;`（PS 纸长 = 走纸引导 + max(用布长度, 内容最大X 含刺口延伸) + 尾余量，×40；无 PS 时 WT 按默认 A0/A3 页幅裁切 7m+ marker）→ 逐片 SP1-SP5 → 尾部 `PU;PG;` 出纸；**CRLF 行尾**；**无 VS/LB 指令**（`title` 仅保签名不输出）；坐标=mm×40 round 取整，5 层笔号 SP1=outline+门幅框/SP2=net/SP3=internal/SP4=notch/SP5=grain；空层跳过；纯 ASCII bytes（无临时文件，无新 pip 依赖）；与 DXF 同闭合策略。**2026-08 现场撞机修正（对照生产 PLT 逐项核出的设备级差异；幅宽口径 2026-08-28 版师定案后收敛单一）**：① 安全幅面 —— 门幅框按输入 `gate_mm` 满幅画 `[0, gate]`（**2026-08-31 撤销 Y 双边内缩 5mm**：旧内缩抄的是生产件「外框下沿 5.1mm」框位置而未抄其「内容不越框」规则，贴边裁片穿框 5mm 被切割软件当布料范围读作越界布料；常量 `PLOT_BORDER_MARGIN_Y_MM` 已删，需物理留边由用户输更小门幅）、内容按 `y ≤ gate_mm` 半平面裁剪（**削平不缩放**，绝不变形），越界裁片记 warning（兜旧 intermediate/求解/变换 bug；撞机根因确认系当时那台机器无法处理 1980 幅宽，旧 `PLOT_SAFE_MAX_Y_MM=1910` 钳制与「二道防线」已随单一口径整体移除，幅宽受限设备由用户输入更小门幅）；② PD 分块 —— `_plt_polyline` 单条 PD ≤10 点（`_PLT_PD_MAX_PTS`）且整行 ≤110B（`_PLT_LINE_MAX_BYTES`）续画（对齐 ET 生产 ≤11 点/≤118B；国产 HP-GL 解释器行缓冲仅百余字节，超长单条溢出后坐标流错位 → 小车乱走须急停）；③ 走纸引导 —— 全体 X + `PLOT_LEAD_X_MM=20`（生产 PLT 内容 24mm 起画，贴 0 起画无定位余量），Y 不平移；HPGL 坐标非负整数，clamp 兜底取整负值。**2026-08-30 唛架信息表格（additive，v5 定稿）**：`info_table` 非 None → 表格画在边框**右侧外围**（`table_x0 = width+TABLE_GAP_MM=0` **共线**（外框左缘与唛架右边框共用一条线）、宽 `TABLE_W_MM=36` = key/value 两条 18mm 行带），**边框恒到 width_mm 不延伸**、料长不含表格，PS 纸长覆盖表格区（`(引导+width+0+36+尾)×40=(width+66)×40`）、SP1 层桶追加表格折线（`plt_table.info_table_polylines`：闭合外框 [x0,x0+36]×[30,30+Σ列宽] + 1 条沿 y key\|value 行分隔线 + 13 条沿 x 列分隔线 + 14 列文字**自唛架右下顶点垂直向上 3cm（y=30mm）**起沿 +y 排开、基线沿 +y 字顶朝 −x（基 `u=(0,1)/w=(-1,0)` 右手系直接生成，生产排料视图里水平正立、key 上 value 下，已与生产件并排对拍验证）、key 行带最靠唛架、全字段统一 12mm 字高、单元格内容居中（列宽 = max(key,value)+2×10mm 内衬）、表长 = Σ列宽 ≤ gate−20−30 超限先缩字高下限 7mm 再等比压列宽）；表格笔画**不走 y≤gate 裁剪**（文件级元数据）；`info_table=None`（不带 `table` 键）输出与旧版**逐字节一致**（零回归红线，测试锁死；2026-08-31 门幅框满幅化 + Y 平移两改后逐字节基线以当日最终版为界）；坐标映射全体 X +`PLOT_LEAD_X_MM=20`、Y +`PLOT_LEAD_Y_MM=TABLE_W_MM=36`（`_plt_pt` 单点，绘制层整体平移=表格宽）。**2026-08-31 毛版变体 `clean=True`（fmt='plt-clean'，additive；当日由「净版」更名——与裁片「毛版轮廓」命名统一，协议值/ascii 后缀 `_clean` 不变）**：`_plt_pt/_plt_polyline` 的 lead_x 参数化（模块内私有无外部调用者），带表格时 X 引导扩 `PLOT_LEAD_X_MM+TABLE_GAP_MM+TABLE_W_MM=56` → 左表 `info_table_polylines(info_table, table_x0=-(gap+36))` 画在世界 x∈[−36,0]（key 带小 x 侧、value 带外缘与门幅左边框共线，与右表同构无镜像）；逐片只画 polygon（SP1，照旧 `_clip_closed_y`）+ 尺码\*数量标注（`_label_strokes`，自 `_grain_annotation_strokes` 拆出的纯文字笔画，几何/字高与全量版全同）进 `_LAYER_GRAIN` 桶，跳过 net/internal/notch/grain 杆羽；`clean=False`（含缺省）逐字节不变 |
| `_plt_frame_stats` | `(world_pieces, *, width_mm, gate_mm) → (n_out, max_x)` | 越界防御 + PS 纸长取值：全层顶点 + notch 点须在门幅框内（容差 0.5mm），非 0 记 warning（曾因 notch 未随片旋转产生 600 越界点把 WT 预览拉变形）；notch 沿法线 ±`NOTCH_LEN_MM/2` 端点外伸属工艺正常，只计入 max_x（PS 取值）不告警 |

`size_aci(size)`（2026-08-20 起尺码键，取代 US-002 的 `label_aci` g 码公式；更早的 `TYPE_ACI` 中文名色表 US-002 已删）：尺码 → ACI 色号 `((size - SIZE_ANCHOR) % 24) + 1`（28→1、51→24、52→1 循环；非数字/None 兜底 7）。配色单一真相源 `sparrow_baseline.size_color`（`SIZE_PALETTE` 16 色 d3 系循环表，`size_color(size) = PALETTE[(size - SIZE_ANCHOR) % 16]`，锚点 `SIZE_ANCHOR=DEFAULT_SIZES[0]=28` 稳定绝对映射、同码同色跨片型），solver manifest / PNG / DXF ACI / CLI SVG 四处同源取色。PNG/DXF 每片 g 码文字叠印不变（颜色=尺码、文字=片型互补编码）。

**2026-08-30 新模块（PLT 表格支线，`web/export.py` 门面 re-export `InfoTable`/`build_info_table`/`parse_table_payload`/`TABLE_GAP_MM`/`TABLE_W_MM`）**：`web/plt_text.py` 矢量文本引擎（**v5 起单线字默认路径**：`load_stroke_font` 汉字笔画中线 `hanzi_medians.txt`（hanzi-writer-data 9574 字，Arphic PL；**文件保留 MMaH y 向下源坐标、加载期镜像翻 y** + 仿射归一 [0.06,0.94]em 盒——不翻则汉字逐字上下镜像，v5 上线首日用户报告即此因已修，test_plt_text 语义探针回归锁）+ ASCII `hershey_rowmans.txt`（Hershey Roman Simplex 92 字符；**JHF y 自字顶向下增长，加载期以 'H' 竖笔底为基线整体翻 y**——不翻则 ASCII 逐字垂直镜像，v5 目检对拍发现已修）；`normalize_text` NFKC 全角→半角 + —·。、→ASCII 在 width/strokes 入口统一；两库未覆盖字符回退 Noto 轮廓（fontTools `BasePen` 子类展平 CFF 三次/TTF 二次贝塞尔 → 折线，De Casteljau 递归、容差 2 字体单位；cmap 未命中豆腐框 + warn）+ 每字符一次 warn；`(u,w)` 基变换强制右手系 det>0 否则 raise 防镜像文字；shrink-to-fit 后 advance 尾截断；单线笔画开放 closed=False / 轮廓回退 closed=True；缺资源降级空表 + warn 回退 Noto 不硬炸导出；字体 = 仓库捆绑 `resources/fonts/`（Noto Sans SC Regular OFL + 两单线库 + 双许可证，`paths.FONT_DIR`，环境变量 `MS_FONT_DIR` 重定位，pip 依赖显式加 `fonttools>=4.40`））；`web/plt_table.py` 表格构建 v5（`parse_table_payload` 载荷校验 → `TablePayloadError` → 路由 400；`_plan_name_and_sets` 方案名称（每码系数 = 面积最大裁片 pid 计数÷2，同系数全局分组、组间按最小码升序）；`build_info_table` 补自动 8 字段（料长(m)=width/1000 不含表格/幅宽(m)=gate/1000/利用率=real_density/套数/每套用料=料长÷套数/片数/绘图时间无秒）；`info_table_polylines` → (closed, points) 折线（v5 = v4 key/value 两行网格 + 共线边框 gap=0 + 列 0 自右下顶点垂直向上 3cm（y=30mm）起 + 单元格居中 10mm 内衬 + 单线矢量字：闭合外框 [x0,x0+36]×[30,30+Σ列宽] + 1 条沿 y key\|value 行分隔线 + 13 条沿 x 列分隔线 + 14 列沿 +y 自适应排开、文字基线沿 +y 字顶朝 −x——基 u=(0,1)/w=(-1,0) 右手系**直接生成**（v2 的 post-flip 已删）；表宽 36mm 与门幅无关，门幅只限表长（30+Σ列宽 ≤ gate−20，超限先缩字高 12→7mm 下限再等比压列宽 + 单元格尾截断兜底）））。表格文字是 PU/PD 笔画（v5 单线），「PLT 无 LB/VS 指令」口径不变；历史「PLT 永不加文字」指 g 码不进 PLT，表格是文件级元数据，与此不冲突。

## POST /api/plt-table-preview — 导出弹窗唛架表格 14 字段预览（2026-08-31）

ExportInfoModal v3「按最终表格列序展示全部 14 字段（8 自动只读 + 6 手输可编辑）」的数据源。**列序/格式权威在后端**：`build_info_table` → `_row_texts` → `preview_rows`（`_ROW_META` 槽位元数据与 `_row_texts` 渲序一一对齐、长度 assert + 测试标签对齐双锁），前端零公式镜像（方案名称系数/demand 多副本计数/`'--'` 回退不在 TS 复刻），后端改列序弹窗自动跟。**零回归红线不动**：`/export` 载荷与 PLT 字节完全不受影响（纯 additive 端点）。

### 请求（`application/json`；= `/export` 的几何子集，前端 mount 时取 `runRegistry.bestRun()`）

```jsonc
{
  "gate_mm": 1750,     // 缺省 0 → 回退会话 state['gate_mm']（与 /export 同口径）
  "width_mm": 5157.57, // <=0 → 400
  "density": 0.8808,   // real_density（原面积·输入幅宽口径）
  "placed": [...]      // lastFrame.placed_items；空 → 400
}
```

### 响应（200）

```jsonc
{ "rows": [ { "key": "plan_name", "label": "方案名称", "value": "(29+30)*0.5=1套", "manual": false }, /* …14 行，列序 = _row_texts（方案名称/床次/经纱缩水/纬纱缩水/利用率/幅宽/料长/本床包含套数/每套用料/片数/排料师/绘图时间/样板号/备注），manual=true 恰 6 行 */ ] }
```

- `manual=true` 行的 `value` = 手输**默认值**（端点用 `parse_table_payload({})`，弹窗手输由前端本地草稿渲染输入框，不消费该 value）。
- **绘图时间口径**：预览 = 请求时刻；最终 PLT = 导出点击时刻重算（分钟精度通常一致）。
- 400（`width_mm<=0` 或 `placed` 空 / pid 全不匹配）：`{"error": "无可预览的方案（width=0 或无裁片）"}` / `{"error": "预览失败：placed 的 pid 均未匹配到原始轮廓"}`；前端对任何失败**静默降级** v2 形态（6 手输 + 提示行），确认导出永不被预览阻塞。

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

把 US-004 落盘的母版 DXF 转成排料 intermediate（覆盖 `pieces_intermediate.json`），复用 `export_dxf` + `load_nest_pieces` 全管线。**Path A 实现（US-001 v2 重排：g 码先行、零丢片、零合成）**：服务端跑 `collect_pieces_with_details` → `labeling.assign_codes(pieces)`（最先执行、无名称映射参数）→ 逐片 `write_piece_dxf({label}_{size}.dxf)` + 写 `pieces_manifest.json` sidecar（`[{file,label,size}]`；仅 `size=None` 片跳过，无映射组不再 skip）→ `load_nest_pieces(pieces_dir)`（**manifest 驱动**）→ **US-002 双写**：主写 per-doc `uploads/<doc_id>_pieces/pieces_intermediate.json` + 镜像写 `paths.INTERMEDIATE`（schema v2：每母版 size≠None 轮廓恰一条；同一 doc dict 两个文件，先 per-doc 后镜像，镜像失败仅 warn）。CPU 密集管线跑在 `loop.run_in_executor(_executor, ...)` 复用 6-worker 线程池（与 `/ws/solve`、`/api/parse-dxf` 同池，防阻塞 WS）。

### 请求

`application/json`（+ 可选 `X-Session-Id` Header，US-002 多会话绑定）：

```jsonc
{
  "doc_id": "02a4d4e4f40e423196f026d291a94ea2",  // 必填，US-004 落盘的 uuid（无扩展名）
  "filename": "M1787(1)(2).dxf"                  // 可选，覆盖 intermediate source 字段；缺省用 <doc_id>.dxf
}
```

**`X-Session-Id`（US-002）**：带 sid → commit 产物（per-doc 文件 + 会话快照）只归属该会话，**不触碰 default 内存**（别人 commit 不会覆盖我的数据）；无 sid → default 会话（现行为，`tests/test_commit_pipeline.py` 零改动回归）。会话解析在 CPU 管线**之前**（fail-fast：过期/超限/非法 sid 不跑管线不落盘）。
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
  "bak": "D:\\code\\...\\pieces_intermediate.bak",  // 原 intermediate 备份路径（镜像侧）
  "reloaded": true,                     // US-020/US-002：快照注册是否成功（带 sid=会话快照，无 sid=default reload；罕见 I/O 竞态时 false + reload_error 字段）
  "mirror_error": "..."                 // 仅镜像写失败时出现（per-doc 已落盘、会话不受影响，additive）
}
```

### 错误响应

| HTTP | 触发 | body |
|------|------|------|
| 400 | 请求体非 JSON / 缺 `doc_id` / 类型错 / `doc_id` 不匹配 `_DOC_ID_RE` | `{"error":"请求体须为 JSON"}` / `{"error":"缺少 doc_id 或类型错误"}` / `{"error":"doc_id 非法（仅允许字母数字，1-128 字符）"}` |
| 400 | `X-Session-Id` 不匹配 `SID_RE`（US-002） | `{"error":"sid 非法"}` |
| 401 | sid 命中墓碑 / 惰性超时（US-002，管线不跑不落盘） | `{"code":"session_expired","error":"会话已过期（10 分钟无操作），请刷新页面"}` |
| 429 | 活跃会话数满且 sid 未注册（US-002） | `{"code":"session_limit","error":"当前使用用户过多（最多 4 人同时在线），请稍后尝试"}` |
| 404 | `uploads/<doc_id>.dxf` 不存在 | `{"error":"未找到上传文件: <doc_id>"}` |
| 422 | 全管线抛异常（collect_pieces 空 / write_piece_dxf 全跳过 / load_nest_pieces 空 / JSON 写盘失败） | `{"error":"commit 失败：<异常>"}` |

### 副作用 + 写盘

1. **临时单裁片目录**：`paths.OUT_DIR/uploads/<doc_id>_pieces/`（`{label}_{size}.dxf` × N + `pieces_manifest.json` sidecar + **US-002 起加 `pieces_intermediate.json`（per-doc intermediate 主写点）**，每次 commit 先 `shutil.rmtree` 再重写，**idempotent**，同 `doc_id` 重跑会覆盖）。文件名仅人读，语义（label/size）全在 manifest —— 旧版目录（无 sidecar）被 `load_nest_pieces` 明确报错「请重新 commit」（FR-9 不静默兼容）。
2. **US-002 双写**：同一 doc dict 写两文件，**顺序先 per-doc 后镜像** —— 主写 `uploads/<doc_id>_pieces/pieces_intermediate.json`（会话快照的数据源，多会话互不覆盖的磁盘锚点），镜像写全局 `paths.INTERMEDIATE`（单文档时代行为的兼容面：无 sid 启动 reload / CLI 工具链 / 人工排查；**带 sid commit 也刷镜像但不刷 default 内存** —— default = 最后无 sid commit 者，镜像 = 最后 commit 者，允许漂移）。镜像写失败仅 warn（stderr + 响应 `mirror_error` 键），不影响 per-doc 落盘与 200 响应。
3. **intermediate 备份**：写回前 `shutil.copy2(paths.INTERMEDIATE, paths.INTERMEDIATE.with_suffix('.bak'))`（**备份行为保留在镜像侧**，per-doc 不做 .bak —— per-doc 目录本身随 commit 整体重写，天然 idempotent）。`pieces_intermediate.bak` 是上一次写回前的快照（首次 commit 无原文件则跳过备份）。**只保留一份**（再 commit 会覆盖 `.bak`）。
4. **intermediate schema v2（US-001）**：`{doc_id(strategy US-004), source, gate_mm, n_pieces, total_area_mm2, pieces[], label_representatives}`；pieces 字段 `{pid, label, size, polygon, bbox, area_mm2, n_verts, allowed_angles, net_polygon(US-024), internal_lines(US-024), notches(US-024), grain_line(US-024)}` —— **无 `ptype`/`side`**（镜像/名称概念删除），`pid = f'{label}_{size}'`。`gate_mm=1750`（`nesting_bounds.load_pieces.GATE_MM`，2026-09-04 起默认 175cm；旧 intermediate 为 1980，重传 commit 后更新）、`allowed_angles=[0,180]`（v0.3 布纹线）。5 层字段由 `load_nest_pieces` 经 `_read_piece` + `_apply_layer_transforms` 与 polygon 共享 rotate→normalize transform 链后透传。顶层 `label_representatives`（原 `ptype_representatives`）：每 g 码 RAW 代表裁片（原始坐标，与上传预览同朝向）。`doc_id`（strategy US-004 新增）：commit 的母版原件定位键（`uploads/<doc_id>.dxf`，策略 start 的 config `master_dxf` 来源）；**旧 intermediate 无此键 → `/api/strategy/start` 422「母版信息缺少 doc_id，请重新上传并 commit」**。旧 v1 intermediate 被 `solver.load_pieces` 明确拒绝（「intermediate 为旧版 schema v1（含 ptype/side），请重新 commit 母版生成新数据」）。
5. **commit 后快照注册（US-020 + US-002 会话绑定）**：`_commit_to_nesting_sync` 成功 → **带 sid**：`_build_pieces_state(per-doc 路径)` 构建快照挂到该会话（`st.state = 快照`、`st.doc_id = doc_id`，default 内存不动）；**无 sid**：`_reload_pieces_state(paths.INTERMEDIATE)` 重读镜像填入 `_PIECES_STATE`（threading.Lock 保护，原子 clear+update；default 会话 state 即同一 dict，自动跟随 —— 路由显式传 `paths.INTERMEDIATE` 是因为 `_reload_pieces_state` 缺省参数在 import 时绑定，裸调读不到 monkeypatch 后的路径）。下一次 `/ws/solve` / `/export` / `/api/ptypes` 即看到新裁片，**前端无需重启 ms-web**（读路由按 sid 取会话快照为 US-003 范围）。快照构建异常（罕见 I/O 竞态）降级为 `reloaded: false` + `reload_error` 字段，保留旧 state 不半切。
6. **commit 成功后触发 uploads TTL 清理（US-006）**：路由尾 `run_in_executor(diskclean.trigger_cleanup, str(UPLOADS_DIR))` —— best-effort（异常仅 warn，响应体无新键）；显式传模块常量 `UPLOADS_DIR`，测试 monkeypatch 后清理范围自动跟随 tmp。本轮 commit 的母版/切片天然不被清（mtime 新 + 会话 doc_id 在保护集）。

### 关键不变量

1. **全码**：manifest 覆盖母版实际全码（`sorted({p.size for p in pieces if p.size is not None})`），**不沿用 `DEFAULT_SIZES`**（8 码跳 32）。M1787 实测 11 码 [28-38] → 110 NestPiece（US-001 v2：= 母版轮廓数；旧 176 为镜像 L/R 合成口径，已删）。
2. **零丢片零合成（US-001 v2）**：无 GROUP_NAMES 映射组不再 skip（名称识别整体退场，未录入名称/无名 block 的新款母版全片有 g 码）；程序不合成镜像，marker = 母版轮廓 × 用户数量（WYSIWYG）。
3. **NestPiece 5 层全透传**：毛版/净版/内部线/刺口/布纹随 polygon 共享 rotate→normalize 变换链（无 mirror 分支）。
4. **回归等价（历史口径，v1 时代）**：旧版 commit 产物与历史全码 CLI 管线等价（实测 176/176、零面积 diff）；v2 起验收口径改为「intermediate 条数 = 母版 size≠None 轮廓数 + parse↔intermediate 逐片 label 对齐（AC#5）」，`tests/test_commit_pipeline.py` 覆盖。
5. **路径一律走 `paths`**：`paths.OUT_DIR/uploads/`、`paths.INTERMEDIATE`、`paths.INTERMEDIATE.with_suffix('.bak')`；不硬编码 `..` 上溯。

## POST /api/session — 多会话 US-001：会话注册 / 幂等刷活性（`sessions.py`）

ms-web 多端串台治理的第一块：后端按 sid 维护独立会话（容量上限 4、10 分钟空闲过期、过期墓碑可判）。本路由是唯一注册入口；sid 校验/归属/过期/超限全部收敛在 `sessions.SessionRegistry.resolve()`（单一解析函数，后续 US-002~004 各端点复用）。

### 请求

无请求体。sid 走 **`X-Session-Id` HTTP Header**（浏览器 fetch 可自定义 Header；WS 因不可自定义 Header 走 `?sid=` query，见 US-003）。

```bash
curl -X POST http://127.0.0.1:8000/api/session -H "X-Session-Id: 3f2a...hex"
```

- sid 合法字符集 = `SID_RE`（`^[0-9A-Za-z]{1,128}$`，与 doc_id 同规则；单一真相源在 `sessions.py`，`server._DOC_ID_RE` re-export 同一编译对象）。
- **缺省 Header**（旧前端 / curl / 现有 pytest）→ `default` 会话：豁免容量上限与空闲过期、不占 `MS_SESSION_MAX` 名额、不参与墓碑；其 pieces 快照 = `runtime._PIECES_STATE` **同一 dict 对象**（行为与单文档时代逐字节一致）。

### 响应

| 场景 | 状态 | 响应体 |
|------|------|--------|
| 合法 sid 建会话 / 已存在幂等刷活性 | 200 | `{"ok": true, "sid": "<sid>"}` |
| 无 Header（→ default 会话） | 200 | `{"ok": true, "sid": "default"}` |
| 活跃会话数已满（`MS_SESSION_MAX`，缺省 4） | 429 | `{"code": "session_limit", "error": "当前使用用户过多（最多 4 人同时在线），请稍后尝试"}` |
| sid 命中墓碑 / 惰性检查发现已超时 | 401 | `{"code": "session_expired", "error": "会话已过期（10 分钟无操作），请刷新页面"}` |
| sid 格式非法 | 400 | `{"error": "sid 非法"}`（无 code 键） |

### 生命周期语义（`sessions.SessionRegistry`，全内存无磁盘态）

1. **容量闸门**：`MS_SESSION_MAX`（env，缺省 4）仅计活跃会话（default 不占额）；已有会话重复 POST 幂等、不受闸门影响。
2. **空闲过期**：`MS_SESSION_TTL_SEC`（env，缺省 600）双路径检查 —— 请求时惰性检查 + 30s daemon 扫描线程（`ws_open>0` 的会话跳过：WS 连接钉住不误杀；扫描是惰性检查的兜底，已死会话不再发请求，名额只能由扫描回收）。**alive hook 豁免（2026-08-30）**：`_is_expired` 三段短路（WS 钉住 → TTL 未超 → `_pinned_by_hook`），hook 只在本来就要过期时才被问（新鲜会话零开销）；strategy.py 注册 `_run_alive_hook` —— 策略/极限 run 存活期间（滚动钉住 `clock()+90s`，须 > 2× 扫描周期）与终态后宽限窗 `MS_RESULT_GRACE_SEC`（env，缺省 7200）内不逐出（睡眠唤醒/关页/跑完挂机等轮询中断场景不丢结果；宽限窗内任何操作恢复正常空闲语义；被钉住的会话仍占容量名额）；hook 在持 registry 锁上下文内执行 —— 只许纯内存 dict 读写 + 非阻塞 `poll()`，异常吞掉当 None，宽限窗外逐出照旧走墓碑。
3. **墓碑**：超时逐出丢全部状态只留 `{sid, ts}`（FIFO ≤128、存活 1h）；墓碑命中 → 401 不静默重建（防过期 sid 被当新会话）；墓碑 1h 过期或 FIFO 淘汰后该 sid 视为全新可正常新建。
4. **合法但未注册 sid 的读路径**（`resolve(create=False)`，服务重启丢内存场景）同过期语义 401；**写路径（US-002 commit）走 `resolve(create=True)`** —— 数据自带（上传母版），合法未注册 sid 可直接 commit 建会话，过期/墓碑/超限仍 401/429。
5. **会话状态结构**：`SessionState = {sid, state(pieces 快照 dict), doc_id, last_active, ws_open}`；`state` 由 US-002 commit 填 per-doc 快照（`_build_pieces_state(per-doc 路径)`，`doc_id` 同步绑定）；WS 钉住 API = `ws_acquire/ws_release`（计数），活性刷新 = `touch(sid)`（GIL-safe float 写）。长跑豁免不经由 SessionState 字段（原 `strategy_busy` 占位已删）—— 由 registry 的 alive hook（strategy.py 注册）在 TTL 命中时询问，单一真相。
6. **读端点接入（US-003 已落地）**：HTTP 读路由（`/api/ptypes` / `/api/band-preview` / `/api/prefix-preview` / `/api/plt-table-preview` / `/export`）经 `routes_views._resolve_session_state`（读路径 `create=False`）从 registry 取快照；WS `/ws/solve` 读 `?sid=` query 经 `ws_acquire`/`ws_release` 钉住 + `on_manifest`/`on_report` 回调 `touch` 刷活性（求解期间客户端不发消息也不被扫描误杀）。超限（429 session_limit）只可能出现在 create 路径（POST /api/session / commit）；读路径对未知 sid 一律 401 session_expired（不静默重建、不占新名额）—— WS error 帧格式对 `session_limit` code 通用（白盒锁定），实际把关在 HTTP 层。
7. **策略四路由接入（US-004 已落地，2026-08-27）**：`/api/strategy/start·status·stop·result` 经 `strategy._session_gate`（读路径 `create=False` + 刷 `last_active` —— **status 轮询即活性**，策略长跑中的会话不被扫描误杀；**轮询中断（睡眠/关页/跑完挂机）由 `_run_alive_hook` 钉住兜底（2026-08-30）**：run 存活滚动钉住 + 终态 `terminal_ts`（set-once，轮询不续期）起 `MS_RESULT_GRACE_SEC` 宽限窗，进程死由 daemon 扫描 `poll()` 探测记 `proc_dead_ts`）解析；状态/产物/停止按 sid 隔离（详见上「策略桥接」多会话小节）。会话过期后策略状态槽与 marker 均按 sid 留存（不随逐出清理）—— 同 sid 过墓碑期回来仍能发现/清理自己的遗留 run；宽限窗外逐出照旧走墓碑。
8. **前端接入（US-005 已落地，2026-08-27）**：前端 `lib/session.ts` 管 sid（localStorage `ms_sid`，uuid4 hex 32，刷新不变）；`lib/api.ts` `apiFetch` 是**全站唯一裸 fetch 出口**（注入 `X-Session-Id` + 会话先行门：首次调用前置一次 POST /api/session once-promise，防子组件 mount 早于 App 探测的 401 误弹）；本路由 429/401 的 `code` 错误体（或 WS error 帧 `code`）触发前端全局阻断弹窗（阻断式全屏，唯一出口 = 刷新页面，阻断期间后续请求前端拦截不发）；**session_expired 时前端顺手丢弃 ms_sid**（墓碑 1h 拒重建旧 sid —— 刷新必须铸新 sid 才能真正重来），session_limit 保 sid。App 挂载即探测 —— 第 5 个窗口页面加载即弹「用户过多」，无需先上传。
9. **uploads 磁盘 TTL 清理（US-006 已落地，2026-08-27，`web/diskclean.py`）**：多会话下 `out/uploads/` 只进不出，按 `MS_UPLOAD_TTL_DAYS`（env，缺省 14 天，按 mtime）自动清理 —— 删超龄 `<doc_id>.dxf` + `<doc_id>_pieces/` **成对**目录（混龄对整对保留：commit 重写 pieces 目录但不刷新 dxf 的 mtime）+ 孤儿单边 + 超龄 `strategy_cfg_*.json`；**保护集** = 活跃会话 doc_id（`registry.active_doc_ids()`：`st.doc_id` ∪ 快照 `state['doc']['doc_id']`）∪ `out/config_runs/.web_strategy_active*.json` marker 内 doc_id（**会话已过期但策略 run 仍在跑 → master 不误删**）∪ mtime 未超龄者；非 web 命名文件一律不动。触发 = 进程启动（`server.main()` 起 `start_startup_cleaner` daemon 线程，TestClient 导入 app 不触发）+ 每次 commit 成功后（`trigger_cleanup`，executor 里跑、吞一切异常仅 warn，不影响响应）。冒烟：`python -m materialsorting.web.diskclean`（临时目录场景自检 13 项 + 真实 out **dry-run** 打印将删清单）。

### 多会话 sid 传递与错误码速查（US-007 汇总，2026-08-27）

各端点 sid 通道（缺省一律 → default 会话，行为与单文档时代一致）：

| 端点 | sid 通道 | 会话语义 |
|------|----------|----------|
| `POST /api/session` | `X-Session-Id` Header | **唯一注册入口**（`resolve(create=True)`：建会话/幂等刷活性；超限在此把关） |
| `POST /api/commit-to-nesting` | `X-Session-Id` Header | 写路径 `create=True`（合法未注册 sid 可直接 commit 建会话）；成功后 per-doc 快照挂会话 |
| `GET /api/ptypes` / `POST /api/band-preview` / `POST /api/prefix-preview` / `POST /api/plt-table-preview` / `POST /export` | `X-Session-Id` Header | 读路径 `create=False`（`routes_views._resolve_session_state` 单一解析点） |
| `POST /api/edit-hold` / `POST /api/edit-polish` | `X-Session-Id` Header | 读路径 `create=False`（server.py 直连 `session_registry.resolve`）；edit-hold 无 sid default → 200 no-op；edit-polish 成功顺手 `edit_hold.refresh(sid)` 编辑钉住（default 不进钉住表） |
| `/api/strategy/start·status·stop·result`、`/api/extreme/start·status·stop·result` | `X-Session-Id` Header | `strategy._session_gate`（读路径 `create=False` + 刷 `last_active`，轮询即活性；run 存活/终态宽限窗由 alive hook 钉住兜底） |
| `WS /ws/solve` | **`?sid=` query**（浏览器 WS 不能自定义 Header） | `ws_acquire` 钉住 + 回调 `touch` + finally `ws_release` |
| `GET /` | 无（静态入口） | 响应头 `Cache-Control: no-cache`（防旧 index.html 缓存滞留 default 语义） |

结构化错误码（`SessionError` 族 → `JSONResponse(e.payload(), e.status)` 一行映射；**400 无 `code` 键，401/429 带 `code`**，additive 旧前端可忽略）：

| HTTP | `code` | `error` 文案 | 触发 |
|------|--------|--------------|------|
| 400 | （无） | `sid 非法` | sid 不匹配 `SID_RE`（`^[0-9A-Za-z]{1,128}$`） |
| 401 | `session_expired` | `会话已过期（10 分钟无操作），请刷新页面` | 墓碑命中 / 惰性超时 / 合法但未注册 sid 的读路径（`create=False`，如服务重启丢内存） |
| 429 | `session_limit` | `当前使用用户过多（最多 4 人同时在线），请稍后尝试`（随 `MS_SESSION_MAX` 插值） | 活跃会话满且 sid 未注册（create 路径） |

WS 侧同语义走 **error 帧**：`{"type":"error","code":"session_expired","message":...}` 后显式 close（`code` 键 additive；`session_limit` 帧格式通用但容量闸门实际由 HTTP 层把关）。前端 `lib/api.ts` / `useSolveRun` 读 `code` 触发全局阻断弹窗（`session_expired` 弃 sid / `session_limit` 保 sid）。

磁盘布局与产物命名（多会话相关）：per-doc intermediate 主写 `out/uploads/<doc_id>_pieces/pieces_intermediate.json`（+ 镜像写全局 `paths.INTERMEDIATE`）；策略 marker `out/config_runs/.web_strategy_active.json`（default）/ `.web_strategy_active_<sid>.json`（sid 会话）；run_name `web_[<sid6>_]<mode>_<rand6>`、cfg `out/uploads/strategy_cfg_[<sid6>_]<stamp>.json`。uploads 磁盘 TTL 清理见生命周期第 9 条（US-006）。

### 关键不变量

1. `sessions.registry.resolve(None).state is runtime._PIECES_STATE`（is 判等单测锁死 —— default 会话自动跟随 commit 的 clear+update reload）。
2. `'default'` 含非 hex 字符，与 uuid4 hex sid（仅 0-9a-f）结构性不可碰撞。
3. `sessions.py` 仅标准库 + 同包 `runtime`，不 import `server.py`（server → sessions 单向无环，AST 守卫在 `tests/test_web_sessions.py`）。
4. 冒烟：`python -m materialsorting.web.sessions`（打印配置 + 私有 registry 模拟建会话/过期/超限/墓碑/ws 钉住全生命周期）。

## POST /api/edit-polish — 编辑排料「智能微调」（prd-edit-polish US-002，2026-09-05）

> ⚠️ **口径差异（红字注记，US-004 立档）**：**编辑画布 = erode 后轮廓、polish 报告 = 物理毛版**。
> 编辑弹窗画布的重合红字/三指标（editGeometry overlap 池）按 per_type d **腐蚀后**轮廓计算
> （碰撞可行性口径）；polish 报告七指标与守卫全部按**物理毛版轮廓**（会话 `pieces_by_id`
> 原始 polygon，与 `/export` 导出真相同源）。同一布局两套数值并存是**设计非 bug**：
> 腐蚀口径数值恒 ≤ 物理口径（d 内缩），版师看到对比卡与画布红字不一致时以本注记为
> 解释锚点（前端对比卡脚注同文案）。本期不切换画布口径（PRD 非目标）。

编辑弹窗「智能微调」按钮的数据源：前端把**当前编辑 placements 随 body 带上**（后端不存布局态，唯一存储在前端 runRegistry —— `/export` routes_views.py 同模式），后端跑引擎层确定性后处理 `nesting_engine/polish_layout`（US-001）返回微调后 placements + 前后对比报告。几何真相源留在 Python：**物理毛版轮廓口径**（会话 `pieces_by_id` 原始 polygon，与 `/export placed_to_world` 同源、非 eroded —— 编辑画布红字告警是腐蚀后口径，数值可能偏小，口径差是文档级约定）。端到端回归冒烟 `materialSorting-web/scripts/smoke_edit_polish.mjs`（US-004 24 检查 + US-005 S7 compact 档 5 检查 + edit-keyboard US-007 S8 键盘/镜像段 17 检查 = 46：微调四守恒/撤销/确定性双跑/PLT+DXF 导出 placed 守恒/band exclude 抽验/compact:true 载荷+width ≤ 非 compact 档+守恒不等式/O 镜像→导出 placed mirror:true + 正文几何镜像坐标对拍/mirror 逐位透传/R 键重置回基线）。

### 请求（`application/json`）

```json
{
  "placed":  [{"id": "g01_30", "rotation": 25.0, "translation": [50.0, 50.0], "mirror": true}, ...],
  "gate_mm": 1750.0,
  "exclude": {"labels": ["g01"], "pids": ["PS_xxx"]},
  "compact": false
}
```

- `placed`（必填，空/缺/非列表 → 400）：同 pid 多副本按**数组下标**逐实例寻址（绝不 pid 去重，与前端 editStore 同口径）；条目缺 `id` / `translation` 非 2 元 → 400。
- `mirror`（可选，omit-when-false 布尔键，**edit-keyboard US-004 2026-09-05**）：条目级镜像片标志（局部 x 翻转 `world = R(rot)·diag(−1,1)·p + t`，与前端 `PlacedItem.mirror` / `/export` placed 同一约定）—— 键直通引擎按**镜像几何**微调：`_world_geom` 与 derotate 共用「local = [(-x, y)] 预处理 + 标准变换」（c_local 用镜像后多边形质心，t' 质心补偿公式不变），诊断/pass ③分离/pass ④compact 全部基于正确镜像几何；响应 placed 同口径 omit-when-false 透传（无改进返回输入 list 原对象亦含该键；恒发 `mirror:false` 会红掉前端精确锁键集用例）。校验逻辑宽松（键直通，路由无代码改动）；缺省/无键 = 非镜像，既有路径逐字节不变（745 pytest 全绿零回归）。**edit-keyboard US-007（2026-09-05）端到端透传锁**：smoke_edit_polish.mjs S8p 段实证 O 键镜像片随本请求发出 → 请求/响应恰一项 `mirror:true` 同下标同 pid、其余 29 项无 mirror 键（请求项与响应项逐位 byteEqual）—— 改 buildPolishPayload / 引擎透传任一处即红。
- `gate_mm`（可选）：优先求解口径（前端 `run.manifest.gate_mm`）；缺省/非法回退会话 `state['gate_mm']`（与 `/export`、`/api/plt-table-preview` 同法）；两处皆无 → 400 fail-fast（守卫 y∈[0,gate] 无从谈起）。
- `exclude`（可选，缺省 None 透传引擎）：`{labels?: [g码], pids?: [pid]}` 双键 —— 命中实例永不被移动仍作障碍（v1 over-conservative 同 pid 全副本，FR-8；band 成员 g 码 / prefix 成员 pid 由前端 best-effort 组装）。非 dict → 400。
- `compact`（可选，缺省 false）：US-005 压缩回收档（2026-09-05 落地）—— true 时引擎追加 pass ④：自布头方向逐片 −x 滑贴收空隙进料长（20mm 粗扫+二分贴触、级联左片先贴），每 move 走同款五道守卫（kind=compact）+ pass 级「全图 maxX 严格变小否则整体回滚」；无空隙可收时输出与 compact=false 逐元素相同（additive）。前端入口 = 对比卡内「回收空隙缩短料长」checkbox（默认不勾，随下次微调请求发出）。

### 响应（200）

```json
{"ok": true, "placed": [...同输入形态...], "report": {...}}
```

- `placed`：条数与 pid 多重集与输入相等（引擎出口 Counter 终检 + 路由入口 pid 全匹配双保险）；无任何 move 时引擎返回输入 list 原对象（逐字节不变量）。
- `report`：`{before, after, moves, residual, excluded, elapsed_sec}` —— before/after 各七指标（`overlap_pairs` / `max_penetration_mm` / `total_overlap_area_mm2` / `rotated_pieces` / `rotation_dev_sum_deg` / `width_mm` / `density`，density = real 口径 `Σ(原面积×副本数)/(width×gate)` 百分数）+ `moves` 逐条明细（index/pid/kind `derotate|separate|compact`/from/to/detail）+ `residual`（终态重合对 + 旋转残留如实上报，不硬凑零）。

### 错误响应（结构化 JSON）

| 场景 | 状态 | 说明 |
|------|------|------|
| sid 过期/墓碑/合法未注册 | 401 | `{"code": "session_expired", ...}`（`resolve(create=False)` 闸门先行，同会话族速查表） |
| sid 格式非法 | 400 | `{"error": "sid 非法"}` |
| `placed` 空/缺/非列表/条目形态非法 | 400 | fail-fast，不跑引擎 |
| 任一 pid 未匹配会话 `pieces_by_id` | 400 | `pid 全匹配才跑`（不做部分降级），文案含「母版已变更？请重新求解/上传」 |
| `gate_mm` 非法 / 两处皆无 | 400 | fail-fast |
| `exclude` 非 dict | 400 | fail-fast |
| 引擎 `PolishError` / 数值字段非法 | 400 | `{"error": "微调失败：..."}`（不炸 500） |

### 关键不变量

1. polish 构造段经 `run_in_threadpool` 执行（prefix-preview 先例，防阻塞事件循环；测试 = 线程级断言：引擎执行线程 ≠ 事件循环线程）。
2. 成功请求顺手 `edit_hold.refresh(sid)`（编辑钉住与 `/api/edit-hold` 心跳同语义；default 不进钉住表；失败请求不续期）。
3. 布局态零落盘：请求/响应全走 body，无新会话状态、无新磁盘产物。
4. 测试：`tests/test_web_edit_polish.py`（20 例：200 全链路守恒/会话隔离/sid 闸门/载荷校验/gate 回退/exclude·compact 透传/线程池执行/钉住续期/US-005 compact=True 全链路回收 + US-004 mirror no-op 逐位透传/镜像几何判别夹具/export 侧 `apply_transform`·`_transform_normal`·`placed_to_world` mirror 对拍 4 例）。

## GET /api/ptypes — US-020 裁片 g 码代表（D10/D11；US-001 v2：键 = label）

返回当前会话下每个 g 码（label）的代表裁片，供前端高级配置弹窗表头缩略图 + 点击放大预览（US-018）。

### 请求

无入参，GET；可选 **`X-Session-Id` HTTP Header**（多会话 US-003）—— 带 sid → 该会话 commit（US-002）注册的 per-doc 快照的 `label_representatives`；缺省/空串 → default 会话（`runtime._PIECES_STATE` 同一 dict，无 sid 行为逐字节不变）。会话解析失败（过期 401 / 非法 400）返回结构化 JSON，不再返回 representatives。响应直接读内存快照，**不走文件 I/O**（μs 级响应）。

```bash
curl http://127.0.0.1:8000/api/ptypes -H "X-Session-Id: <sid>"
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

## POST /api/band-preview + POST /api/prefix-preview — 布局设置形态预览（`routes_views.py`）

「高级配置 → 布局设置」两行（band 2026-08-24 / prefix 2026-08-25）的缩略图数据源。共同思路：选中 g 码后不展示原始代表裁片缩略（与下方裁片设置表格同源同图，纯冗余），改展示**最终组合形态**（带 = WB_ 组合片形态 / 前缀 = 4 片同码 interleave 竖排 = PS_ 组合片精确形态），并把构造失败（fill 守卫 / 无资格码 / 竖排超高 / 贴触失败等）从 solve 报错**前置到选码时刻**。

### 请求（`application/json`；与 WS StartPayload 同源字段子集）

```jsonc
// /api/band-preview
{"band": {"enabled": true, "label": "g05"},
 "sizes": [28, 30], "quantities": {...}, "per_type": {...}, "params": {...}, "gate_mm": 1750}

// /api/prefix-preview（多一个可选 seed）
{"prefix": {"enabled": true, "front": "g02", "back": "g03"},
 "sizes": [28, 30], "quantities": {...}, "per_type": {...}, "params": {...},
 "gate_mm": 1750, "seed": 0}
```

- band/prefix 校验**复用 WS 同一校验点**（`routes_ws._parse_band` / `_parse_prefix`）—— WS / 策略 start / 预览三处口径恒一。
- **多会话 US-003**：可选 `X-Session-Id` Header → 该会话的 `pieces` / `pieces_by_id`（A/B 会话各成各带互不串台）；缺省 → default。sid 过期/非法 → 401/400 结构化 JSON，早于业务校验（`_resolve_session_state` 单一解析点，`/api/ptypes` 同款）。
- `gate_mm` 优先求解口径（前端 parseGate），缺省/非法回退 intermediate（与 `/export` 同法）；构造约束带即 `gate_mm` 原样（2026-08-28 起单一幅宽口径）与求解同口径。
- prefix `seed` 缺省 0：**选码确定性化（2026-09-02 `select_prefix_plan` 近满幅几何搜索，无 RNG）后预览不再依赖 seed 对齐** —— 搜索路径与 seed 无关恒与求解同选；seed 仅兜底 4 片路径的 `pick_prefix_size` 消费（缺省 0 = 与求解同参同选）。

### 响应（失败也 200、`ok:false` 包络 —— 选错 g 码是预期内常态而非异常）

```jsonc
// /api/band-preview 成功
{"ok": true, "label": "g05", "fill_pct": 78.19,
 "bbox": {"width_mm": 60.0, "height_mm": 1534.6}, "n_members": 6,
 "members": [{"pid": "g05_38", "size": 38, "color": "#...", "polygon": [[x,y],...]}],
 "outline": [[x,y],...]}

// /api/prefix-preview 成功（成员多一个 tag = g 码，前/后幅区分标注；顶层多 front/back/size；
// 2026-09-02 US-003 起 additive：n_members=4（兜底）或 5（顶部异码补片）+ 四个新键）
{"ok": true, "front": "g02", "back": "g03", "size": 38, "fill_pct": 82.0,
 "bbox": {"width_mm": 1175.0, "height_mm": 1978.4}, "n_members": 5,
 "members": [{"pid": "g02_38", "size": 38, "color": "#...", "tag": "g02", "polygon": [[x,y],...]}],
 "extra": {"label": "g02", "size": 32},   // 补片在案时非 null（兜底 4 片 = null）
 "residual_mm": 1.55,                      // gate_mm − 组合片高（近满幅残余缝隙）
 "gate_mm": 1750.0,                        // 实际参与构造的门幅（payload > intermediate 回退）
 "fallback": false,                        // true = 无可行 5 片组合 → 兜底 4 片 seeded
 "outline": [[x,y],...]}
```

构造执行模型：band = 主进程同步 `build_pid_meta + build_band_plan`（v2 链构造无 RNG、毫秒级，spyrrow 不参与）；prefix（2026-09-02 US-003 起）= `build_pid_meta → select_prefix_plan`（与 `solve_worker._build_prefix` 同一真相源、同参同选；`d_g = max(d_front, d_back)` 同式）**构造段整体经 `run_in_threadpool` 在工作线程执行** —— 选码搜索秒级（5336 规模 ~120 组合实测 ~4.45s < 5s 红线），防阻塞事件循环（多会话并发下主进程卡顿）；会话解析/校验仍主线程先行（401/400 早退语义不变）。

### 关键不变量

1. **成员 polygon 是组合片归一坐标**（原始轮廓@带内/组合片位 − `chunk.offset`；原始轮廓缺席回退 erode 后轮廓，与 union 口径一致）—— 前端零变换直接渲染（`BandPreviewSVG`）。颜色 = `pid_meta['color']`（`size_color` 单一真相源，与 manifest/NestSVG 同口径）。
2. **不返回组合片 pid**（哨兵约定：`WB_` / `PS_` 永不出现在前端/manifest/导出）；`outline` 是 erode 后组合片外轮廓（前端虚线叠加显示「主解看到的形状」）；prefix 的 `extra` 只带 `label`/`size`（补片真实 pid 在 `members` 里自然可见，组合片 `PS_` pid 永不出前端契约）。
3. **失败也 200**：空 state / 校验失败 / 构造异常统一 `{"ok": false, "error": "<可读文案>"}`，前端单条路径渲染错误文案（不区分网络/业务错误）。
4. 预览与求解**同真相源**：band 链构造无 RNG（seed 只进 chunk.seed 记录，几何无关）⇒ 预览 = 求解时带的精确形态；prefix 走 `select_prefix_plan` 同函数同参（搜索路径无 RNG）⇒ 同 payload 恒与求解同选（A/片型/B/rot；`tests/test_prefix_preview_api.py` 直调对拍锁定；US-005 冒烟实测预览↔求解同选 @38+g02@32 residual 1.55mm，`scripts/smoke_prefix_extra.mjs`）。

## 策略桥接（strategy PRD US-004）— `/api/strategy/*` 四路由（`web/strategy.py`）

桥接方式 = **spawn `python -m materialsorting.cli.run_config <cfg> --name web_[<sid6>_]<mode>_<rand6> --strategy <mode> --time <minutes*60> --quiet` 子进程 + HTTP 轮询 run_dir 产物**（分层零违规：进程边界而非 import 边界 —— `strategy.py` 全模块禁 import `..cli.*`，AST 守卫 `tests/test_web_strategy.py`；判据逻辑单一真相源留在 `cli.portfolio`）。子进程经 env 继承拿到与 ms-web 相同的 `paths`（`MS_OUT_DIR` 等环境变量父子同源）。前端消费方 = 策略 PRD US-005 弹窗（`strategyStore` + `useStrategyPoll`，详见 `agent-component-map.md` US-005 专节）：GET status 轮询双档 **弹窗开 2s / 关 15s**（关弹窗由入口徽标维持观测），terminal 态停表；start 载荷 = 面板排料参数 + `{mode, minutes}`；**关闭弹窗（ESC/遮罩/✕）不调 stop** —— 终止唯一入口 = 显式终止/清理按钮。

**多会话 US-004（2026-08-27）：四路由全部读 `X-Session-Id` Header（缺省/空串 → default 会话）**，策略状态/产物/停止按会话隔离：

- **每会话一份状态**：模块级 `_STRATEGY_STATES[sid]`（default 会话 = 旧名 `_STRATEGY_STATE` 同一对象，零 sid 路径行为不变）；会话过期/逐出**不清理**本表 —— 同 sid 回来（墓碑 1h 过龄后可重建）仍能经内存态（本进程未重启）或本 sid marker（重启后 orphan 路径）发现/清理自己的遗留 run。
- **会话闸门**（`_session_gate`）：非 default sid 走 `resolve(create=False)` —— 未知/过期 → 401 `session_expired`、非法 → 400，先于 409/422/一切校验；顺手刷 `last_active`（**status 轮询即活性**，长跑会话不被扫描线程误杀）。default 豁免（零 sid 行为不变）。
- **每会话 409 单飞**：同 sid 内存态非终态或本会话 marker 在 → 409；**跨会话完全并发放开**（接受 CPU 争抢，不加全局闸门）。
- **marker 文件**：default → 旧名 `out/config_runs/.web_strategy_active.json`（路径兼容）；sid 会话 → `.web_strategy_active_<sid>.json`（orphan 检测/清理按会话隔离）。恰 5 键 `{pid, run_dir, doc_id, mode, started_at}` 不变。
- **run_name / 产物命名**：`web_[<sid6>_]<mode>_<rand6>`（sid6 = sid 前 6 位；default 无 sid 段沿用旧名）；cfg = `out/uploads/strategy_cfg_[<sid6>_]<stamp>.json`；stderr 临时文件前缀 `web_strategy_err_[<sid6>]_`。
- **run_dir 认领 = 确定性前缀 glob**（`<run_name>_*`）—— run_name 嵌本会话唯一 rand6，完全并发下只可能命中自己 spawn 的 run（旧「目录快照 diff + mtime 最新」在多会话并发 starting 下必互相认错，此为必修 bug 修正；快照 diff 保留为存量内存态回退路径，且回退排除其他会话的 run_name 前缀与已认领 run_dir）。
- **产物清理按会话**：`_cleanup_stale_web_artifacts(sid)` —— sid 会话只清 `web_<sid6>_*` / `strategy_cfg_<sid6>_*` / `web_strategy_err_<sid6>_*`；default 沿用清全部 `web_*` 但跳过其他会话（`_STRATEGY_STATES` 在册 sid ∪ 磁盘 `.web_strategy_active_*.json` marker sid）的前缀产物。

状态机：`idle → starting →（run_dir 前缀 glob 发现）running → done | stopped | error`；内存态空 + 本会话 marker 在 → `orphan`。终态清本会话 marker、内存态保留供 status/result 续读（下一次 start 覆写）。

### POST /api/strategy/start — 启动策略 run

请求 `{mode: 'se'|'race', minutes: 10|20|30|60, seed?, gate_mm?, sizes?, per_type?, quantities?, band?}`（sizes/per_type/quantities 与 WS StartPayload 同语义 —— 前端「排料参数取当前面板」；**band 与 WS StartPayload.band 同形**，2026-08-22 解除与策略运行的互斥 —— `collectStartContext` 同源产物直传）。可选 **`X-Session-Id` HTTP Header**（多会话 US-004）：带 sid → 会话闸门（未知/过期 → 401 `session_expired`、非法 → 400）+ 排料数据取**该会话 commit 的快照**；缺省 → default 会话（`_pieces_state()`，行为不变）。

- 401/400（sid 会话）：会话解析 fail-fast，先于下列一切校验（不 spawn）
- 409：**本会话**已有进行中 run（内存态非终态）或本会话 marker 在（含 orphan 遗留，先停止/清理）；跨会话不 409
- 422：会话 pieces 快照空；intermediate doc 缺 `doc_id`（旧 intermediate → 「母版信息缺少 doc_id，请重新上传并 commit」）；`uploads/<doc_id>.dxf` 丢失
- 400：mode 非法 / minutes 非法（含字符串）/ seed 非整数 / **band 非法**（复用 `routes_ws._parse_band` 单一校验点：label ^g\d+$ / 存在于当前母版 / 该 g 码 quantities>0；null / enabled falsy → 不写键旧行为）
- 202：清理本会话前缀上一轮产物 → 写 **8 键** config JSON 到 `out/uploads/strategy_cfg_[<sid6>_]<stamp>.json`（`master_dxf` = 母版原件**绝对路径**；`gate_mm` 请求值回退 state；`seeds=[seed]`；band 合法开启 → `{'enabled':true,'label':g码}` 写进 config；可选键 truthy 才写）→ spawn（stdout=DEVNULL、stderr=临时文件前缀 `web_strategy_err_[<sid6>]_`）→ 快照 `out/config_runs/`（**先于 spawn**，回退发现路径防 diff 扑空；主认领路径 = 前缀 glob 不依赖快照）→ 写本会话 marker → `{started, pid, mode, minutes, run_name}`（run_name = `web_[<sid6>_]<mode>_<rand6>`）。band on 的策略 run 在 CLI 侧 worker 进程内成带（`--lns` 自动 warn 跳过）

### GET /api/strategy/status — 无状态惰性轮询

可选 `X-Session-Id`（多会话 US-004；sid 过期/未知 → 401、非法 → 400）。每次现读**本会话**产物组装（不缓存中间态）；resolve 顺手刷 `last_active`（轮询即活性）；进度源白名单 `strategy.json` / `result.json` / `best_frame_s*.json` / `kill_decisions.jsonl` —— **绝不读 `curve_s*.json`**（运行中缺右括号非法 JSON）。响应 `{state, mode, total_budget_sec, elapsed_sec(墙钟), run_dir, plan, incumbent, current, per_seed, events, error, exit_code}`：

- `plan`：strategy.json → `{planned_seeds, gate_seconds}`（race）| `{planned_seeds, k_screens, screen_s, ext_s}`（se）
- `incumbent`：result.json portfolio.incumbent 摘要 `{density, width_mm, seed, frame_index, elapsed}`（**无 placed_items** 控载荷）
- `current`：最新 mtime `best_frame_s*.json` → `{seed, density, density_sparrow, ext}`（`_ext` 后缀 → ext=true，SE 延长检测）
- `per_seed`：result.json portfolio.per_seed 透传（含 `phase`: race/screen/extension、`killed`）
- `events`：kill_decisions R5_race_gate 行（`S_tau` 重载为 bar 参照值）+ extension（`best_frame_s{seed}_ext.json` 在场）+ seed_done（per_seed），只保留尾部 20 条
- 缺文件一律降级 null / `[]`；run_dir（前缀 glob）未发现 + 进程死 + >30s 宽限 → `error`（附 stderr 尾部 2000 字符）；终态顺手清**本会话** marker 并把 state 写回内存态

### POST /api/strategy/stop — 树杀

可选 `X-Session-Id`（多会话 US-004；sid 过期/未知 → 401）。Windows `taskkill /PID <pid> /T /F`（`/T` 整树 —— run_config 会 spawn 多进程 solve 孙进程，单杀父进程留孙进程白烧 CPU）；POSIX spawn 带 `start_new_session=True` + `os.killpg`。**只树杀本会话 pid**，其他会话的 run 不受影响。进行中 → 置 stopped + 清本会话 marker；orphan（内存空 + 本会话 marker 在）→ pid 存活则树杀 + 清 marker；本会话无活动 → 400（他会有 run 也 400）。

### GET /api/strategy/result — 最优方案 + manifest（US-006 应用到主画布数据源）

可选 `X-Session-Id`（多会话 US-004；sid 过期/未知 → 401）。本会话 done/stopped 可读（running → 409「尚未结束」；idle → 404）。响应 `{state, mode, run_dir, manifest, best, summary, warning?}`（run_dir / manifest / best 全部来自**本会话**状态槽）：

- `best`：result.json `portfolio.incumbent`（完整 `placed_items`；**无 `density_sparrow`** —— 从 `best_frame_s{seed}.json` 边车补，缺则 null）；stopped 无 result.json → 回落各 `best_frame_s*.json` 取 density 最大
- `manifest`：`build_pid_meta(start 时快照 pieces, sizes/per_type/quantities 同口径)` → `{gate_mm, total_area_mm2, n_eroded, pieces:[{id,size,color,area_mm2,polygon(erode 后),label,demand,net_polygon,internal_lines,notches,grain_line}]}`（与 /ws/solve manifest.pieces 同形；erode 后几何与 placed_items 对齐、demand 已含 —— 前端 NestSVG 副本池按 demand 建 N 份承接多副本 placement；旧 `gate_nest_mm` 键 2026-08-28 起已删）
- `summary`：`{per_seed, mode, race?|se?}`（result.json portfolio 模式段透传）
- `warning`：start 快照 `doc_id` ≠ **本会话当前画布** `doc_id` → 「母版已变更，应用结果可能与当前画布不一致」（导出 pid 失配走既有 400 兜底；default → `_pieces_state()`，sid → 会话快照）

### 关键不变量

1. **server.py 文件尾** `from .strategy import register_strategy_routes` 注册路由；`strategy.py` 对 server 的依赖走**函数内延迟 import**（`_pieces_state()`）—— 任意 import 顺序不成环。
2. start 时 `sizes/per_type/quantities/seed/gate_mm/pieces` 快照存**本会话**状态槽（`_STRATEGY_STATES[sid]`；default = 旧名 `_STRATEGY_STATE` 同一对象）—— result 组装 manifest 用同口径，不依赖前端二次回传。
3. `_status_from_active` 把解析出的 state **写回** `st['state']`（否则「跑完后从未轮询」内存态永远停在 running，start 单例检查失效）。
4. orphan `_pid_alive`：Windows `ctypes kernel32.OpenProcess(0x1000)` 句柄探测（非本进程孩子无法 poll）；报 `state:'orphan' + alive` 由前端提供清理动作，不自动接管。orphan 判定按**本会话 marker**（内存态空 + 本 sid marker 在），他会有遗留 run 不串台。
5. run_dir 认领主路径 = `<run_name>_*` 前缀 glob（run_name 嵌本会话唯一 rand6）；回退路径（存量内存态）排除其他会话 run_name 前缀与已认领 run_dir —— 完全并发下互不认领。
6. 产物清理按 sid 前缀互斥（sid 会话只清 `web_<sid6>_*`；default 清全部 `web_*` 但保护其他会话前缀）—— 跨会话并发放开后清理不再有删除竞争。

## 极限运行桥接（extreme PRD US-002）— `/api/extreme/*` 四路由（`web/strategy.py` 内 mode='extreme' 分支）

**设计原则 = 泛化优先于复制**：四路由与策略路由同居 `strategy.py`，start 走 `_start_run(req, family)` 家族参数化、status/stop/result 走 `_status_common` / `_stop_common(req, label)` / `_result_common(req, label)` 公共实现 —— **共用每会话状态槽 `_STRATEGY_STATES[sid]`、marker `.web_strategy_active[_<sid>].json`、`_cleanup_stale_web_artifacts`、`_discover_run_dir`、`_spawn_run_process`、`_kill_tree` 全部骨架**（mode 字段 `se|race` vs `extreme` 区分）⇒ **同会话「极限运行 ↔ 高级运行」409 单飞互斥零额外代码**（防双长跑拖垮服务器 CPU），跨会话完全独立（多会话 US-004 语义不变）。spawn 命令 = `python -m materialsorting.cli.run_config <cfg> --name web_[<sid6>_]extreme_<rand6> --extreme --time <T> --quiet`（进程边界，分层 AST 守卫同策略）。

### POST /api/extreme/start — 启动极限 run

请求 `{time_total_s, seed?, gate_mm?, sizes?, per_type?, quantities?, band?, prefix?}`（可选 `X-Session-Id`，sid 语义与 strategy 四路由一致：过期/未知 → 401 `session_expired`、非法 → 400、闸门先于一切）。

- 409：**本会话**已有进行中 run（内存态非终态）或本会话 marker 在 —— 无论对方是高级运行还是极限运行（文案带在跑的 mode：「已有进行中的策略运行/极限运行（或检测到遗留 marker），请先停止/清理」）；跨会话不 409
- 422：会话 pieces 快照空 / doc 缺 `doc_id` / `uploads/<doc_id>.dxf` 丢失（同策略）
- 400：`time_total_s` 缺省 / 非整数（字符串、非整浮点、bool） / `<905`（race 门杀 600s 档最低总预算 602.5+302.5，与 `cli.portfolio.race_plan` 同口径提前拦） / `>43200`（12h 防呆）；seed 非整数 / sizes·per_type·quantities 类型错（同策略）；**band/prefix 非法 → 400 同策略文案**（2026-08-30 起 `_parse_band`/`_parse_prefix` 同一校验点透传：坏 g 码 / 不存在于母版 / 数量全 0 / front==back / 无 2+2 资格码；此前「键在场即 400 暂不支持」已废止；null / enabled falsy 视同关闭不写键）
- 202：清理本会话前缀上一轮产物（`web_<sid6>_*` 天然含 `web_<sid6>_extreme_*`；default `web_*` 含 `web_extreme_*`）→ 写 config JSON（`strategy_cfg_[<sid6>_]<stamp>.json`；键 = `master_dxf` 绝对路径 + `gate_mm` + `time=T` + `seeds=[seed]` + 可选 sizes/per_type/quantities/**band/prefix（开启时写键，随 config JSON 走不进命令行）**）→ spawn（stdout=DEVNULL、stderr 临时文件）→ 写本会话 marker（5 键，mode='extreme'）→ `{started, pid, mode:'extreme', run_name, time_total_s}`（run_name = `web_[<sid6>_]extreme_<rand6>`）

常量 `EXTREME_MIN_TIME_S=905` / `EXTREME_MAX_TIME_S=43200` 镜像 `cli.run_config` 极限语义但**不 import**（web 禁 import ..cli.*；数字改动须两处同步）。

### GET /api/extreme/status / POST /api/extreme/stop / GET /api/extreme/result — 与策略三路由同构

- **status**：无状态惰性轮询同槽产物；`mode` 透传 `'extreme'`、`total_budget_sec=T`。`--extreme` 内部展开 race 门杀 ⇒ strategy.json 是 race 档（`plan.gate_seconds`）、kill_decisions R5 门杀事件行、per_seed `killed` 天然可读；进度源白名单同策略（**绝不读 `curve_s*.json`**）。轮询即活性（刷 `last_active`）。
- **stop**：树杀本会话槽内 in-flight run（`taskkill /PID /T /F` / killpg；只杀本会话 pid）+ 置 stopped + 清本会话 marker；orphan 同策略；本会话无活动 → 400「没有进行中的极限运行」。
- **result**：done/stopped → `{state, mode:'extreme', run_dir, manifest, best, summary, warning?}` —— best（incumbent 完整 placed_items + density_sparrow 边车补 / stopped 回落 best_frame 最大）、manifest（start 快照口径 `build_pid_meta`）、母版漂移 warning 全同策略组装；running → 409「极限运行尚未结束」、idle → 404「暂无已完成的极限运行结果」。

### 关键不变量

1. 同会话极限 ↔ 高级互斥 = 共享状态槽的自然结果（单飞闸门查 `st['state']` 非终态 ∨ marker 在，与家族无关）；任一入口的 stop 都能清理本会话槽内 in-flight run（单飞保证同时只有一族）。
2. 极限 run 的 run_dir 认领 / marker 回写 / 终态清理 / orphan 检测全部走策略既有路径（run_name 前缀 glob，rand6 唯一）。
3. 前端 US-003 消费方：轮询与结果应用复用策略 PRD US-005 弹窗机制（mode 字段区分入口）。
4. 验收（US-004）：同总预算 4h 三臂对拍报告 [.docs/business/极限运行_AB验收报告.md](../business/极限运行_AB验收报告.md)；单飞互斥的物理根据 = 三臂并行实测 solver 帧数 −8%、密度 −0.5pt（墙钟预算被 CPU 争用截断，长跑必须串行/单飞）。

## WebSocket /ws/solve — 求解流

单条长连接，生命周期：**client 发 start（首条必须）→ server 推 1×manifest → N×frame → 1×final（或 error）；client 可在任意时刻发 stop → server 推 1×stopped → 关闭 WS**。**US-011 band 开启时在 manifest 前多推 1×stage**（腰头成带带内聚排完成统计）；**US-003 prefix 开启时再多推 1×stage('prefix')**（双开序 = band → prefix → manifest）。

**多会话 US-003：`?sid=` query 参数**（浏览器 WS 不能自定义 Header，故 sid 走 query 而非 `X-Session-Id`）：

```bash
ws://127.0.0.1:8000/ws/solve?sid=<sid>     # 缺省/空串 → default 会话（旧行为不变）
```

- **连接钉住**：accept 后立即 `ws_acquire(sid)`（resolve 语义 + `ws_open += 1`）—— 扫描线程对 `ws_open>0` 的会话跳过逐出（求解 10-60 分钟不被误杀）；任何退出路径（final/error/stop/断开）在 finally `ws_release` 减回（断开后归零）。
- **快照口径**：accept 阶段 state 快照来自**会话**（带 sid = commit 注册的 per-doc 快照；缺省 = default 会话，其 state 即 `runtime._PIECES_STATE` 同一 dict）。会话 state 从不原位 mutate（commit 整体 rebind `st.state`）→ 「整连接一次快照」不变量保持。
- **活性刷新**：`on_manifest` / `on_report` 回调内 `registry.touch(sid)`（求解期间客户端不发消息，靠回调刷 `last_active`；GIL-safe 单 float 写不加锁）。
- **会话错误帧**：过期（墓碑/惰性超时/未注册合法 sid）→ 发 `{"type":"error","code":"session_expired","message":"会话已过期（10 分钟无操作），请刷新页面"}` 后**显式 close**（不发 manifest）；非法 sid → `{"type":"error","message":"sid 非法"}`（无 code 键）。`code` 键为 additive —— 旧前端忽略、US-005 前端据此弹阻断弹窗。`session_limit` code 帧格式同样支持（容量闸门实际由 HTTP 层 POST /api/session 把关，读路径 create=False 不触达 429）。
- **前端侧（US-005 已落地）**：`lib/ws.ts` `solveWsUrl()` 自动拼 `?sid=`；`useSolveRun` case 'error' 读 `msg.code`（session_expired/session_limit）→ 与 HTTP 同一全局阻断弹窗入口 `triggerSessionBlock`。

> US-020：accept 阶段 `state = _get_pieces_state()` 拿一次快照，整连接内 `pieces / gate_mm` 不变（避免求解中途 reload 切数据）。state 空时（首次启动未 commit / intermediate 缺失）直接发 error「排料数据为空」并关闭。**US-003（多会话）后该快照经会话解析取得**（default 会话 state 即 `_PIECES_STATE`，无 sid 行为不变）。
>
> US-026：ws_solve 改为 `solve_with_callback_proc` 进程化求解（build_instance 移入子进程）。write loop 内联 drain asyncio queue → ws.send_json；read loop 后台 task 持续读客户端消息。收到 `{action:'stop'}` → `process.terminate()+join(timeout=5)` → 直发 `{type:'stopped'}` → 关闭 WS。客户端断开（WebSocketDisconnect）→ 同样 terminate+join 防孤儿进程（**修复旧 bug**：旧版 `except:pass` 静默忽略断开，求解线程跑满预算）。
>
> US-011（腰头成带）：StartPayload 可缺省 `band` 键。开启时 `solve_worker` 先在**本进程内**跑带内聚排（不 spawn 孙进程 —— terminate 即整进程回收），成功投 stage（见 1.5）+ 落 `out/band_runs/*.json` 工件；主实例以 `exclude_labels={label}` 跳过 band 成员（pid_meta/total_area/manifest 逐字段不变）并把组合片（`WB_*` pid）经 `extra_items` 构造期进 items；帧/final 发射经 `_emit_placed` 单点展开回成员 placement —— **WB_ 永不出现在 manifest/frame/final**。成带失败（0 副本/总副本 1/fill 下限等）只投 error 不投 manifest（与 build 失败同契约）。**2026-08-22 简化**：band 契约收敛为 `{enabled, label}` 两键（ack 硬警告 / fillers 填料混带已删，fill<45% 是唯一守门人）。
>
> US-003（起始端成套前后幅）：StartPayload 可缺省 `prefix` 键 `{enabled, front, back}`（**无 size** —— 选码后端确定，不出 UI）。开启时 `solve_worker` 在本进程内同步构造（`_build_prefix`：**2026-09-02 起 `select_prefix_plan` 单一真相源** —— 近满幅几何搜索产 5 片组合片（4 同码基座 + 顶部异码补片，无 RNG），全无可行组合兜底 `pick_prefix_size` seeded 选码 + 4 片构造（旧行为，`fallback=True`；seed 仅此路径消费）），成功投 stage('prefix')（见 1.5）+ 落 `paths.PREFIX_RUNS_DIR/*.json` 工件（构造/pin/带位完整回放，US-005 A/B 数据源；写失败仅 warn）；主实例以 `exclude_pids=Counter(成员 pid 计数)` **pid 级扣减**（4 片时 {front:2,back:2} 与整 pid 跳过等价；5 片时异码 pid 扣 1 份余量照排 ⇒ placed 守恒 = 全量 Σdemand；与 exclude_labels 并存互不干扰；pid_meta/total_area/manifest 逐字段不变）并把组合片（`PS_{front}+{back}@{size}`，5 片形态 pid 追加 `+{label}@{B}`；orientations=`PREFIX_ORIENTATIONS=(0,180)`）经 `extra_items` 构造期进 items；帧发射经 `_emit_placed` 展开（PS_ 永不出现在 manifest/frame/final）；**final 单独置换挂钩** `_finalize_prefix`：组合片 min_x≤6mm 已锚定跳过（P0 常态）、>6mm → `pin_prefix_layout` 置换+复检失败回退（帧不置换）；final 消息带 `prefix: {size, pid, pin, band_pos, extra, residual_mm, fallback}`。前缀构造失败只投 error 不投 manifest。

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
  "quantities": {"g01": {"28": 2, "30": 0}, "g02": {"28": 1}},  // US-022 可选，label→sizeKey→demand；0=该 piece 该码不排；缺省=null→全片 demand=1
  "band": {"enabled": true, "label": "g05"},  // US-011 可选腰头成带（2026-08-22 简化后仅 enabled+label 两键）；缺省/null/{}/非 dict/enabled falsy = 关闭（旧行为逐字段不变）
  "prefix": {"enabled": true, "front": "g02", "back": "g03"}  // US-003 可选起始端成套前后幅（无 size —— 资格码中 seeded 随机选码）；缺省/null/{}/非 dict/enabled falsy = 关闭（旧行为逐字段不变）；与 band 可同时开（双开）
}
```

```jsonc
// 后续消息（US-026，可选）—— 停止求解
{"action": "stop"}
```

`params` / `per_type` 缺省 = baseline（无 erode、严格布纹线 `{0°,180°}`）。`quantities` 缺省 / `null` = 全片 `demand=1`（向后兼容旧前端 / 旧 intermediate 无 label）。US-022 起 `build_instance` 按 `(piece.label, str(piece.size))` 查 `quantities` → `spyrrow.Item(demand=N)`；demand=0 跳过（D2）；piece 缺 label 回退 demand=1。

**US-011 `band` 服务端校验**（`routes_ws._parse_band`，quantities 解析后；非法 = `{type:error}` 早退 + 显式关 WS，不发 manifest；**2026-08-22 起 WS 与 `/api/strategy/start` 共用同一校验点**）：

- 非 dict / 无 `enabled` / `enabled` falsy → 关闭（不校验其余键）；
- `label` 须匹配 `^g\d+$` 且存在于当前母版，且该 g 码在 quantities 口径下至少一个码 demand>0（missing→1 同 `build_pid_meta` 口径）；
- 返回 `{'label': str}` 传 `solve_worker`。（已删：硬警告 ack 护栏（`BandAckRequired`）与 US-015 fillers 护栏 —— 2026-08-22 随成带旁路功能整体退场。）

**US-003 `prefix` 服务端校验**（`routes_ws._parse_prefix`，band 之后同模式；非法 = `{type:error}` 早退 + 显式关 WS，不发 manifest）：

- 非 dict / 无 `enabled` / `enabled` falsy → 关闭（不校验其余键）；
- `front`/`back` 各须匹配 `^g\d+$` 且存在于当前母版，且 **front ≠ back**（须为不同 g 码，前/后幅各一）；
- `eligible_sizes(quantities, front, back, sizes=sizes)` 须 ≥1 资格码（front 与 back 同码 demand==2 恰好 2+2）；无资格码 → error「当前数量无 2+2 资格码（front/back 各码 demand 须恰为 2）—— 请在数量矩阵把所选码前后幅配成 2+2」；
- 返回 `{'front': str, 'back': str}` 传 `solve_worker`（载荷多余键如 `size` 静默忽略）。

> **US-004 前端侧（2026-08-25）**：`lib/params.ts collectPrefix` 三态解析（关 / 开未选或 front==back 或非 `^g\d+$` → null；开且有效 → `{enabled:true,front,back}`）；弹窗勾选区有 `prefixEligibleSizes` 本地预检提示（同口径 missing→0、'null' 跳过、sizes 过滤），**只是提示不拦截** —— 上表服务端校验是唯一权威。

### 1.5 server → stage（band / prefix 开启时 manifest 前**各恰一次**）

```jsonc
{
  "type": "stage",
  "stage": "band",               // 'band'（带内聚排完成）或 'prefix'（前缀构造完成）
  "fill_pct": 78.19,             // 带内填充率（%，成员原面积和 / 实际占用 bbox 面积）；prefix = 组合片填充率
  "bbox": {"width_mm": 60.0, "height_mm": 1534.6},  // 实际占用 bbox（非全幅）
  "fallback": false,             // band v1 构造恒 false；prefix 2026-09-02 起回显兜底形态（True = 4 片 seeded 兜底、无补片）
  "elapsed": 15.3,               // 构造 wall-clock 秒
  "size": 38,                    // prefix 专属：选定的套装码 A；band stage 无此键
  "holes": 0,                    // prefix 专属：封闭腔数（interleave 定稿 0）；band stage 无此键
  "extra_label": "g02",          // prefix 专属（2026-09-02 异码补片）：顶部补片 g 码；无补片（兜底）= null；band stage 无此键
  "extra_size": 31,              // prefix 专属（2026-09-02）：顶部补片尺码 B（≠A）；无补片 = null；band stage 无此键
  "residual_mm": 1189.4          // prefix 专属（2026-09-02）：gate − 组合片高（近满幅判据）；band stage 无此键
}
```

仅对应 StartPayload 开关开启时出现，在 manifest 前各发一次（双开序 = band → prefix → manifest）。`on_stage` 回调泛化为键白名单转发（fill_pct/bbox/fallback/elapsed/size/holes/extra_label/extra_size/residual_mm）。旧前端 default:break 静默忽略（前向兼容）；前端 US-012 起在状态行呈现「腰头成带中…」（秒级提示，不进 phase 五态状态机）；**起始端成套补片 US-004（2026-09-02）起 prefix stage 状态行双形态**——extra 在案 →「起始端成套构造中（尺码 A＋g@B）…」，兜底/旧后端回落现行形态（`/api/prefix-preview` 的 `extra`/`residual_mm` 同日入前端类型，放大层 hint 追加「＋ 顶部 g@B 异码片 · 余 Xmm 近满幅」）。**US-005 端到端验收（2026-09-02 收官）**：UI 冒烟 `materialSorting-web/scripts/smoke_prefix_extra.mjs` 29/29 覆盖本节全部消息形态（stage 双形态/final prefix 段/末帧 placed 守恒/`PS_` 零泄漏），业务定案见 `.docs/business/起始端成套前后幅_版师确认清单.md` §9。

### 2. server → manifest（**一次**，握手后立即发）

```jsonc
{
  "type": "manifest",
  "gate_mm": 1750,
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
  "density": 0.8983,              // ★ 原面积·实际幅宽口径 real = total_area/(width*gate)（与 90% 生死线一致；2026-08-28 起单一幅宽口径）
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
  "n_eroded": <被 erode 的片数>,
  "prefix": {                     // US-003：仅 StartPayload prefix.enabled 时出现
    "size": 38,                   // 选定的套装码 A
    "pid": "PS_g02+g03@38",       // 组合片 pid（不与 placed 混排，成员已展开）；5 片形态追加 +{label}@{B}（如 PS_g02+g03@38+g02@31）
    "pin": {"skipped": true, ...},// US-002 pin_prefix_layout stats（skipped/rolled_back/…）
    "band_pos": {                 // 双开（band+prefix）时 WB 组合片世界 bbox 带位记录；否则 null
      "pid": "WB_g05", "min_x": <mm>, "max_x": <mm>,
      "min_y": <mm>, "max_y": <mm>, "dist_to_tail_mm": <width−max_x>
    },
    "extra": {                    // 2026-09-02 异码补片：选定顶部补片（与 stage 同源）；兜底 4 片 = null
      "pid": "g02_31", "label": "g02", "size": 31, "rotation": 0.0
    },
    "residual_mm": 1189.4,        // 2026-09-02：gate − 组合片高（与 stage 同值）
    "fallback": false             // 2026-09-02：True = 全无可行组合退回 4 片 seeded 兜底
  }
}
```

prefix 关闭时 final **无 `prefix` 键**（逐字段零回归）；`width_mm` 口径：pin skipped/回退 = solver 原值，置换成功 = 原始轮廓世界几何重算。2026-09-02 起 `extra`/`residual_mm`/`fallback` 三键 additive（旧前端忽略不炸；`prefix_runs` 工件同三键回显，US-005 回放对拍数据源）。

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

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_pieces` | `(intermediate_path=paths.INTERMEDIATE) → (doc, gate_mm, pieces)` | 读 `pieces_intermediate.json` |
| `build_pid_meta` | `(pieces, *, sizes=None, per_type=None, quantities=None, params=None) → (pid_meta, total_area, n_eroded)` | **strategy US-004 自 `build_instance` 提取**的裁片级流水线（**不 import spyrrow、不构造求解对象** —— `/api/strategy/result` 组装 manifest 直接用）：sizes 过滤 → demand 判定（quantities 按 `(label, str(size))` 查 N，0=跳过；缺 label→1）→ per_type 覆盖 + 全局上限钳制（`_resolve_d_tol` 单一真相源，与 `build_instance` 的 Item orientations 同口径）→ erode/清洗（<3 顶点跳过）→ pid_meta 条目（US-024 5 层 + label/color/demand）→ `total_area=Σ(area×demand)`。对拍单测（`test_web_strategy.py`）保证提取前后 `build_instance` 输出逐字段一致 |
| `discretize_orientations` | `(tol: float) → list[float]` | v0.3 连续旋转公差 → spyrrow 离散角度集。`tol=0→[0,180]`；`tol≤5` 步进 1°；否则 5°。归一化到 [0,360) |
| `build_instance` | `(pieces, gate_mm, *, time_budget, seed, sizes=None, params=None, per_type=None, quantities=None, solver_opts=None, exclude_labels=None, exclude_pids=None, extra_items=None) → (instance, config, pid_meta, total_area, n_eroded)` | strategy US-004 起裁片级流水线（sizes/demand/per_type/erode/pid_meta/total_area）**委托 `build_pid_meta`**（单一真相源），本函数补 spyrrow 侧构造：`Item`（shape 用 pid_meta 的 erode 后 polygon、orientations 用同口径 `_resolve_d_tol` 的 tol 离散化）。按 sizes 过滤 → US-022 按 `(label, sizeKey)` 查 quantities 定 demand（0 跳过；缺 label → 1） → US-002 起 `per_type[label]` 命中即覆盖 d/tol（2026-08-18 回退 US-004 后 label 单级，命中即对该 g 码全部码号生效；未命中/缺维度回退 `params.d_ext/tol_ext`；旧 ptype / 旧两级键 no-op；internal 概念已删，`d_int`/`tol_int` 仍被接受但无消费方） → 每片 `erode=min(申请d, MAX_OVERLAP_MM=10)`、`tol=min(申请tol, MAX_ROTATION_TOL_DEG=45)`（**2026-08-17 起全局上限，不再按片型**） → erode+clean → 构造 `spyrrow.Item` + `StripPackingInstance(strip_height=gate_mm)` + `StripPackingConfig`；pid_meta 含 US-024 5 层字段 + `label`/`color=size_color(size)`（2026-08-20 尺码键）/`demand`（`.get()` 向后兼容）。**求解约束带 = 输入门幅原样**（2026-08-28 版师定案起单一幅宽口径：旧 min(gate_mm, 1910) 钳制已删，manifest 的 gate_mm / 密度分母 / 导出外框 / 求解带全部同门幅）。**US-006（PC-006）`solver_opts`**（additive 白名单 exploration_pct/quadtree_depth/num_workers/**early_termination** 四键，越界 clamp、非数值/未知键忽略、不传=现行行为；`early_termination` 仅接受严格 bool、2026-08-29 入白名单并显式透传 spyrrow（缺省 True 行为不变；`--extreme` 用它固定 false 吃满各段预算，见极限利用率实验报告））：`exploration_pct∈[0.1,0.95]` 把 time_budget 换算为 exploration_time/compression_time 两段 int 秒（各 ≥1s、和≈budget，**与 total_computation_time 互斥** —— spyrrow 的 total 键缺省 600 非 None，两段模式必须显式传 total_computation_time=None，否则 not-all-3 ValueError）；quadtree_depth∈[3,5]（缺省 4）、num_workers≥1（缺省 4）。清洗单一真相源 `_normalize_solver_opts`。**US-011 `exclude_labels`**（iterable[str]）：该 label 集合只在 **Item 构造层**跳过（pid_meta/total_area/manifest 逐字段不变 —— band on/off manifest 一致性由此保证；**禁** quantities=0 移除：连 pid_meta/total_area 一起抹掉，密度掉 ~12pt）；**US-003 `exclude_pids`（2026-09-02 双形态）**：pid 级 Item 层扣减，**与 exclude_labels 并存互不干扰**（双开时两参同传；pid_meta/total_area/manifest 逐字段不变，prefix on/off 一致性由此保证）—— iterable[str] = 整 pid 跳过（US-003 原语义逐字节不变）；`Mapping[str,int]`（如 `Counter`，`solve_worker` 按 PS_ 成员计数传入）= 每 pid 扣 n 份（`Item.demand = meta['demand'] − n`，≤0 才跳过 —— 5 片组合片下异码补片 pid 扣 1 份余量照排主解，placed 守恒 = 全量 Σdemand）；**US-011 `extra_items`**（list[{id,polygon,demand=1,orientations}]）：构造期追加进 items 的补充 Item（成带组合片 WB_ pid / 前缀组合片 PS_ pid）—— **必须构造期传入**，spyrrow `instance.items` 是 Rust 侧暴露的副本 list，构造后 append 不生效（实测组合片整解缺席） |
| `solve_with_callback` | `(instance, config, on_report, *, drain_interval=0.2) → (final_sol, elapsed_sec, err)` | **旧 threading 版（保留）**。子线程 `instance.solve(config, progress=queue)`，主线程 `queue.drain()` 每 0.2s 取中间解 → `on_report({type:frame,...})`。US-026 起 `ws_solve` 切换到 `solve_with_callback_proc`，本函数不删（过渡期） |
| `solve_with_callback_proc` | `(pieces_snapshot, gate_mm, solve_params, *, on_manifest, on_report, on_process=None, on_stage=None, drain_interval=0.2, band=None, prefix=None) → (process, final_data, elapsed, err)` | **US-025 多进程版**。spawn 子进程跑 `solve_worker`（在子进程内 `build_instance + solve`，spyrrow 对象不可 pickle 故不跨进程），主进程 drain `multiprocessing.Queue` 分发：manifest → `on_manifest`、frame → `on_report`（density 双口径换算在主进程做）、final/error 记录。**US-026 新增 `on_process` 回调**：子进程 `start()` 后立即回调一次，把 `Process` 句柄交给调用方供 WS stop / 断开时 `terminate()`。**US-011 新增 `on_stage` 回调 + `band` 透传**：drain 循环显式转发 `{kind:stage}`（此前未知 kind 静默丢弃；`on_stage=None` = 丢弃 = CLI 路径旧行为）；`band` 原样带给 `solve_worker`（BandChunk 不跨进程）。**US-003 `prefix` 同透传**（worker 形态 `{'front','back'}`）。返回 `process` 句柄可 `terminate()`；terminate 后 `cancel_join_thread + 限时 drain(≤50ms) + join(timeout=5)` 防死锁；子进程 crash 未投 error 时 `err='worker process exited unexpectedly (code=<exitcode>)'` |

### `web/solve_worker.py`（US-025 新增）

| 函数 | 签名 | 说明 |
|------|------|------|
| `solve_worker` | `(pieces_snapshot, gate_mm, solve_params, result_queue, band=None, prefix=None)` | **子进程入口（顶层函数，Windows spawn 可 pickle）**。子进程内 `build_instance(pieces_snapshot, gate_mm, **solve_params)` → 投递 `{kind:manifest, pid_meta, total_area, n_eroded, gate_mm}` → `instance.solve(config, progress=ProgressQueue)` → drain 出的中间解投递 `{kind:frame, report}` → 末尾投递 `{kind:final, final}` 或 `{kind:error, message}`。所有投递纯 JSON 可序列化，spyrrow 对象绝不跨进程。**US-011 `band`**（worker 形态 `{'label': g码}`，2026-08-22 简化后单键）：先 `_build_band`（本进程内同步 `build_band_plan`，d_g/tol_g 与主实例同源 `_resolve_d_tol`、带内 gate=gate_mm 原样（2026-08-28 起单一口径））→ 成功投 `{kind:stage}`（manifest 前一次）→ 主实例 `exclude_labels={label}` + 组合片 `extra_items`（demand=1、orientations=[0,180] FR-8）→ 帧/final 经 `_emit_placed(sol.placed_items, band_chunk)` **单点展开** WB_ 条目回成员 placement（`expand_placements` 权威式）；失败（BandError/ValueError/几何异常）投 `{kind:error,'成带失败: …'}` 只投 error 不投 manifest。**US-003 `prefix`**（worker 形态 `{'front':g码,'back':g码}`）：`_build_prefix`（本进程内同步构造，**2026-09-02 起 `select_prefix_plan` 单一真相源**：`eligible_sizes`（尊重 solve_params.sizes）→ 近满幅组合搜索（4 同码基座 + 顶部异码补片，无 RNG）→ `build_prefix_plan`（d_g=max(d_front,d_back) 经 `_resolve_d_tol`、gate_nest=gate_mm 原样（2026-08-28 起单一口径））；全无可行组合兜底 seeded `pick_prefix_size` + 4 片构造（旧行为，seed 仅此路径消费））→ 成功投 `{kind:stage,stage:'prefix',size,fill_pct,bbox,holes,fallback,extra_label,extra_size,residual_mm,elapsed}`（manifest 前一次，band 之后）+ `_write_prefix_artifact` 落 `paths.PREFIX_RUNS_DIR/<ts>_<pid>.json`（chunk.to_dict() 完整回放 + pin stats + band_pos + extra/residual_mm/fallback，写失败仅 warn）→ 主实例 `exclude_pids=Counter(PS 成员 pid 计数)`（Mapping 部分扣减）+ PS_ 组合片 `extra_items`（demand=1、orientations=`PREFIX_ORIENTATIONS`）→ final 前 `_finalize_prefix` 置换挂钩（pin_prefix_layout；帧不置换；长度无关，5 片形态同路径）→ 帧/final 经 `_emit_placed(…, band, prefix)` 同单点展开；失败（PrefixError/ValueError/几何异常）投 `{kind:error,'前缀构造失败: …'}` 只投 error 不投 manifest |
| `_build_band` | `(pieces_snapshot, gate_mm, solve_params, band, result_queue) → BandChunk \| None` | **进程内**带内聚排编排（不 spawn 孙进程 —— terminate 即随本进程回收，band 阶段 stop 无孤儿）；`build_pid_meta` 建成员 meta、`_resolve_d_tol` 裁定 d_g/tol_g、`build_band_plan` 构造性链构造 |
| `_build_prefix` | `(pieces_snapshot, gate_mm, solve_params, prefix, result_queue) → dict \| None` | **进程内**前缀构造编排（同 `_build_band` 进程模型）：资格码 → seeded 选码 → `build_prefix_plan`；返回 ctx（chunk/front/back/size/gaps/holes/d_g/elapsed），失败投 error 后返回 None |
| `_finalize_prefix` | `(sol, prefix_ctx, band_chunk, pid_meta, pieces_snapshot, gate_mm) → (placed_final, width_final, prefix_record)` | final 置换挂钩：base = `_emit_placed(其余 placed)`（**含 WB_ 展开** —— 双开时漏展开即 KeyError 'WB_*'，已修+锁死）；`pin_prefix_layout`（min_x≤6mm skip / 失败回退 rolled_back）；width 口径 skip/回退=solver 原值、置换成功=原始轮廓世界重算；band_pos（双开）= WB chunk @ 主解位世界 bbox |
| `_write_prefix_artifact` | `(record)` | `paths.PREFIX_RUNS_DIR/<yyyymmddTHHMMSS>_<pid>.json`（构造/pin/带位完整回放 + `chunk.to_dict()`；US-005 A/B 回放对拍数据源）；写失败仅 warn 不影响求解交付；PREFIX_RUNS_DIR 经 `MS_OUT_DIR` env 随 spawn 传递，测试可隔离 |
| `_emit_placed` | `(placed_items, band=None, prefix=None) → list[{id,rotation,translation}]` | 序列化器 + **US-011/US-003 展开单点**：`band` 非 None 时 WB_ 条目、`prefix` 非 None 时 PS_ 条目替换为 `expand_placements` 产物（帧与 final 发射点共享；**PS_/WB_ 永不跨进程**） |

### 求解进程 ↔ 事件循环桥（`server.ws_solve`，US-026 进程化版）

```
accept → receive_json() → {action:start}            # 主协程，读首条消息
  ↓
_parse_band(msg.band, pieces, quantities)            # US-011 服务端校验；非法 → error 早退 + ws.close()
  ↓
solve_with_callback_proc(pieces_snapshot, ..., band=band_cfg)  # executor 线程，阻塞跑
  on_process(proc): state_box['process'] = proc      # 子进程 start 后回调，存句柄
  on_stage(m): → queue.put(stage_msg)                # US-011 band / US-003 prefix 开启时 manifest 前各一次（键白名单含 2026-09-02 extra_label/extra_size/residual_mm）
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

1. **density 双口径**：frame/final 的 `density` 必须是原面积·实际幅宽口径（`total_area/(width*gate_mm)`，2026-08-28 起输入幅宽 = 实际幅宽单一口径；旧 `gate_nest_mm` 字段与前端红虚线已随 70mm 钳制整体删除），`density_sparrow` 才是 spyrrow 自报。前端 90% 生死线判定用 `density`。
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
