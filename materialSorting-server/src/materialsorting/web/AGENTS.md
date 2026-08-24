# web — Agent 速查

> FastAPI + WebSocket 工作台（最上层）。可 import 全部下层（dxf_parser / nesting_bounds / nesting_engine）+ `paths`；下层**禁** import 本包。
> 改前先看 `.docs/technical/agent-api-reference.md`（HTTP/WS 契约）+ `.docs/technical/agent-file-map.md` web 章节。

## 启动 / 校验

```bash
python -c "from materialsorting.web.server import app"                # 导入冒烟（含路由表打印）
ms-web                                                                 # 启动 uvicorn :8000（console_script）
python -m materialsorting.web.server                                   # 等价（无 console_script 也能跑）
curl -X POST http://127.0.0.1:8000/api/parse-dxf -F "file=@<dxf>"      # US-004 上传解析
curl http://127.0.0.1:8000/api/ptypes                                  # US-020 裁片 g 码代表（US-001 v2 键 = label）
```

> **intermediate 由 Web 上传母版 commit 生成**（`server.py` 启动期 `_reload_pieces_state()` 在 import 时读 `pieces_intermediate.json`；缺失不崩但 `_PIECES_STATE` 为空 dict，`/ws/solve` 报「排料数据为空」、`/api/ptypes` 返回 `{representatives:{}}`，前端上传母版 commit 成功后自动 reload 填入）。`materialSorting-web/static/` 也需 `npm run build` 一次让 mount 不空（dev 模式 Vite proxy 不依赖 build 产物，但 FastAPI mount 空目录会报错）。

## 文件分工

| 文件 | 角色 |
| --- | --- |
| `server.py` | FastAPI app；路由 `GET /`、`mount /static`、`POST /export`、`POST /api/parse-dxf`（US-004）、`POST /api/commit-to-nesting`（US-010）、`GET /api/ptypes`（US-020）、`WS /ws/solve`；US-020 可 reload `_PIECES_STATE`（threading.Lock 保护）；`ThreadPoolExecutor(max_workers=6)` 求解桥 + 上传解析/commit 复用；**文件尾** `from .strategy import register_strategy_routes` 注册策略四路由（US-004，见下）；commit 落盘 doc dict 带 `doc_id` 键（策略 start 定位母版原件）。**2026-08-20 拆分**（600 行硬限制，783→329）：state/线程池搬 `runtime.py`、parse 响应构造搬 `parse_payload.py`、WS solve 搬 `routes_ws.py`、`/`·ptypes·`/export` 搬 `routes_views.py`（APIRouter include，注册顺序不变）；**`_commit_to_nesting_sync` + 上传路由留守**（测试 monkeypatch `server_mod.UPLOADS_DIR` 依赖 server 命名空间 `__globals__`）；拆出符号全部 re-export |
| `runtime.py` | **2026-08-20 自 server.py 拆出**。共享运行时单例：`_PIECES_STATE` 快照机制（`_state_lock`/`_build_pieces_state`/`_reload_pieces_state`/`_get_pieces_state`）+ 启动期 reload + 共享 `_executor`（ThreadPoolExecutor 6 workers）。**import 即副作用且先于 server.py 创建 app**（与拆分前顺序一致）；strategy.py 函数内延迟 `from .server import _get_pieces_state` 经 re-export 满足 |
| `parse_payload.py` | **2026-08-20 自 server.py 拆出**。纯函数：`_size_sort_key` / `_build_parse_payload` / `_build_label_representatives` |
| `routes_views.py` | **2026-08-20 自 server.py 拆出**。APIRouter：`GET /`、`GET /api/ptypes`、`POST /export`；从 runtime 取共享 state |
| `routes_ws.py` | **2026-08-20 自 server.py 拆出**。APIRouter：`WS /ws/solve` + `_terminate_solve_process` + `_SENTINEL`；从 runtime 取共享 executor/state；**US-011** `_parse_band` band 服务端校验（label `^g\d+$` / 存在母版 / quantities>0；返回恰 `{'label': str}`，多余键静默忽略 —— **2026-08-22 简化**：ack 硬警告与 US-015 fillers 护栏已删，形态守卫唯一入口是 `waist_band.FILL_FLOOR_PCT`；非法=结构化 error 早退 + **显式 ws.close()**——TestClient 下早退 return 不关 WS 则 client receive 永不抛 disconnect）+ `on_stage` 回调投 `{type:stage,stage:band}` |
| `solver.py` | `load_pieces` / `discretize_orientations`（**US-009 起真相源在 `nesting_engine/constraints.py`，此处 re-export 保旧 import 路径零改动**） / `build_pid_meta`（**US-004 自 build_instance 提取**：sizes 过滤 → demand → per_type 覆盖（`_resolve_d_tol` 单一真相源，与 Item orientations 同口径）→ erode/清洗 → pid_meta → `total_area=Σ(area×demand)`；**不 import spyrrow**，web 策略 result 组装 manifest 直接用）/ `build_instance`（v0.3 erode+tol 包装，US-024 pid_meta 加 5 层字段 `.get()` 兼容；**US-002**：demand 按 `(label,sizeKey)` 直译 + `per_type[label]` 命中即覆盖（2026-08-18 回退 US-004 矩阵化后 label 单级，命中即对该 g 码全部码号生效）+ internal 概念删（`d_int`/`tol_int` 无消费方）+ `color=size_color(size)`（2026-08-20 尺码键，同码同色跨片型；此前 label 键）、pid_meta 无 ptype 键；US-004 起裁片级流水线委托 `build_pid_meta`，本函数补 spyrrow Item/Instance 构造，对拍单测保证提取前后输出逐字段一致）/ `solve_with_callback`（**旧** threading 版 spyrrow ProgressQueue + 0.2s drain，US-025 起保留不删）/ `solve_with_callback_proc`（**US-025** multiprocessing 版，spawn 子进程跑 `solve_worker`，主进程 drain `multiprocessing.Queue`，返回 `process` 句柄可 `terminate()`；density 双口径换算在主进程处理 frame 时做）+ `_apply_density_dual` 私有 helper；**US-006** `build_instance` 加可选 `solver_opts`（白名单 `exploration_pct`/`quadtree_depth`/`num_workers`，清洗单一真相源 `_normalize_solver_opts`：越界 clamp、非数值/未知键忽略；`exploration_pct` 换算两段 int 秒时**必须显式传 `total_computation_time=None`** —— spyrrow 该键缺省 600 非 None，不传即 not-all-3 ValueError；不传 solver_opts = 现行行为）；**US-011** `exclude_labels`（只跳 spyrrow Item 层，pid_meta/total_area/manifest 逐字段不变——band on/off 一致性关键）+ `extra_items`（**构造期**注入组合片：spyrrow `instance.items` 是 Rust 侧副本 list，构造后 append 静默失效）+ `solve_with_callback_proc` 加 `on_stage` 回调 / `band` 参数透传 worker |
| `strategy.py` | **US-004 新增**。策略桥接四路由 `POST /api/strategy/start·/status·/stop` + `GET /api/strategy/result`（`register_strategy_routes(app)`）；spawn `python -m materialsorting.cli.run_config <cfg> --strategy <mode> --time <sec> --quiet` 子进程 + 无状态惰性轮询 run_dir 产物；**禁 import `..cli.*`**（AST 守卫，进程边界而非 import 边界）。详见下「US-004 策略桥接关键约定」 |
| `solve_worker.py` | **US-025 新增**。顶层 `solve_worker(pieces_snapshot, gate_mm, solve_params, result_queue)` —— Windows spawn 可 pickle（无闭包、参数全 JSON）。子进程内 `build_instance(...) → 投 {kind:manifest}` → `instance.solve(config, progress=ProgressQueue)` → drain 出中间解投 `{kind:frame,report}` → 末尾投 `{kind:final,final}` 或 `{kind:error,message}`。所有投递纯 JSON，spyrrow 对象绝不跨进程；**US-011** `band` 参数 → `_build_band`（**进程内**同步跑 `waist_band.build_band_plan`，不 spawn 孙进程；失败=「成带失败」error 不投 manifest）+ `_emit_placed` 展开单点（WB_ 组合片条目展开回成员 placement，三处帧/final 发射共享；**2026-08-22 简化**：`_write_band_artifact` band_runs 工件与 fillers 透传已删） |
| `export.py` | `apply_transform` / `placed_to_world`（用**原始**非 eroded 轮廓，pid 直查 intermediate 零重放；US-024 起 5 层一并变换，notch 点按点变换 + 法线按向量旋转；US-002 起输出无 ptype 键、`color=size_color(size)`（2026-08-20 尺码键））/ `render_png`（matplotlib Agg；US-024 起 5 层叠加 net 绿虚线 / internal 橙 / notch 黄短线段 / grain 红虚线；图例条目 = placed 的尺码并集数值序、标题「尺码」）/ `write_marker_dxf`（R12 POLYLINE + ACI 色；US-024 起多 layer outline1/14/8/4/7 各自独立 entity；ACI = `size_aci(size)` = `((size-28)%24)+1`（2026-08-20 尺码键））/ `write_marker_plt`（US-033 HPGL/HP-GL 文本 `IN;PS;SP1;PU/PD/PG`，无 VS/LB；坐标=mm×40 round；**全程单笔 SP1**——2026-08-24 统一颜色，生产 PLT 同款；层序与 DXF layer 序一致；空层跳过；纯 ASCII bytes，无临时文件、无新依赖）。**2026-08-20 拆分**（600 行硬限制，658→47 门面 + 四模块）：`export_geometry.py`（placed_to_world/apply_transform/size_aci/LAYER5 常量共享层）/ `export_png.py`（render_png，Agg+CJK rcParams 副作用保留）/ `export_dxf.py`（write_marker_dxf，ezdxf 警告抑制保留）/ `export_plt.py`（write_marker_plt + 全部 PLT 算子常量）；export.py 门面 re-export 全部旧公共符号（含 `_plt_frame_stats`/`_PLT_PD_MAX_PTS`），消费方 import 路径零改动 |
| `export_geometry.py` | **2026-08-20 自 export.py 拆出**。导出共享层：`placed_to_world` / `apply_transform` / `size_aci` + `LAYER5_COLOR_*` / `NOTCH_LEN_MM`；依赖 `sparrow_baseline`（size_color/SIZE_ANCHOR），被 png/dxf/plt 三模块单向依赖，零 web 反向 import |
| `export_png.py` | **2026-08-20 自 export.py 拆出**。`render_png`（matplotlib Agg）；模块级 `matplotlib.use('Agg')` + CJK rcParams 副作用原样保留 |
| `export_dxf.py` | **2026-08-20 自 export.py 拆出**。`write_marker_dxf` + `_DXF_LAYER_*`；模块级 ezdxf 警告抑制副作用原样保留；R12 + POLYLINE 写法不动（ET2008 兼容） |
| `export_plt.py` | **2026-08-20 自 export.py 拆出**。`write_marker_plt` / `_plt_frame_stats` / `_plt_pt` / `_plt_polyline` / `_clip_closed_y` / `_clip_open_y` / `_y_clip_point` + 全部 PLT 常量（2026-08 撞机修正注释块整段搬移）；import `nesting_bounds.load_pieces.PLOT_SAFE_MAX_Y_MM` |

## US-004 /api/parse-dxf 关键约定（实现方/调用方必读）

- **multipart 依赖 `python-multipart`**：已在 `[web]` extra（`pyproject.toml`）。否则 FastAPI `UploadFile = File(...)` 启动即报 `AssertionError`。
- **落盘路径**：`paths.OUT_DIR/uploads/<doc_id>.dxf`（`doc_id = uuid.uuid4().hex`，32 字符无横杠）。**禁硬编码** —— 用模块级常量 `UPLOADS_DIR = Path(paths.OUT_DIR) / 'uploads'`。
- **CPU 解析走 executor**：`loop.run_in_executor(_executor, _parse_dxf_sync, str(dest))` 复用 6-worker 线程池（与 `/ws/solve` 同池）。母版深度解析 ~1-2s，不阻塞事件循环。
- **错误码口径**：扩展名非 `.dxf`→400；超 `UPLOAD_MAX_BYTES=20MB`→413；ezdxf/collect 异常→422（中文错误信息）。**200 / 400 / 413 / 422 全部走 JSONResponse**（与 `/export` 一致），不抛 `HTTPException`。
- **响应字段**（US-001 v2 契约，名称字段全删）：`{doc_id, filename, sizes:[{size, pieces:[{label,polygon,internal_lines,notches,net_polygon,grain_line}]}]}`。polygon=`[[x,y],...]`；internal_lines=`[[[x,y],...],...]`；notches=`[[x,y,nx,ny],...]`；net_polygon=`[[x,y],...]`；grain_line=`[x1,y1,x2,y2]` 或 `null`。**`name`/`ptype`/`paired` 已删除**（名称识别整体退场；配对镜像概念删除，需求侧一律走前端 `quantities[label][sizeKey]`，US-003 前端随动）。
- **g 码赋号口径（US-001 v2）**：每码内独立 `g01+` 零填充编号（不跨码续编，字典序=数值序）。顺序赋码排序键 `sequential_sort_key = (group_key, -centroid_y, centroid_x, -area_mm2, block_name, piece_index)`（**T4：group_key 前置**，同一 block 模板跨码同号；码内成员按上方/左/大片优先）。母版 block 名带显式编号且 all-or-nothing 命中 → 整体复用母版码。码号分组排序：数值升序，`null` 殿后。单一真相源 `nesting_engine/labeling.py`。
- **doc_id 是 US-010 入参**：`POST /api/commit-to-nesting {doc_id}` 会读 `uploads/<doc_id>.dxf`。**doc_id 必须可定位落盘文件**，故成功响应才返回 doc_id（422 时文件保留但响应不带 doc_id）。

## US-010 /api/commit-to-nesting 关键约定（Path A 全管线）

- **请求体**：JSON `{doc_id, filename?}`。`doc_id` 必填，仅匹配 `_DOC_ID_RE = ^[0-9A-Za-z]{1,128}$`（防路径逃逸，`uuid.uuid4().hex` 自然命中）；`filename` 可选，缺省用 `<doc_id>.dxf`，作为新 intermediate 的 `source` 字段。
- **管线（`_commit_to_nesting_sync` 跑在 executor，US-001 v2 重排：g 码先行、零丢片、零合成）**：`collect_pieces_with_details` → `labeling.assign_codes(pieces)`（最先执行、无 gmap/group_names 参数）→ 逐片 `write_piece_dxf({label}_{size}.dxf)` + 写 `pieces_manifest.json` sidecar（`[{file,label,size}]`；仅 `size=None` 片跳过并计入 `skipped`，**无映射组不再 skip**）→ `load_nest_pieces(pieces_dir)`（**manifest 驱动**，文件名仅人读）→ 写回 `paths.INTERMEDIATE`（schema v2：每母版轮廓恰一条，无 ptype/side/paired；顶层 `label_representatives`）。
- **全码**：sizes 取母版实际全码 `sorted({p.size for p in pieces if p.size is not None})`，**不沿用 `DEFAULT_SIZES`** 8 码。M1787 实测 11 码 [28-38] → 110 NestPiece（US-001 v2：= 母版 size≠None 轮廓数；旧 176 是镜像 L/R 合成口径，已删）。
- **临时单裁片目录**：`UPLOADS_DIR / f'{doc_id}_pieces'` = `{label}_{size}.dxf` × N + `pieces_manifest.json`。每次 commit 先 `shutil.rmtree` 再重写（**idempotent**，同 doc_id 重跑覆盖）。旧版切片目录（无 manifest sidecar）被 `load_nest_pieces` 明确报错「请重新 commit」（FR-9 不静默兼容）。
- **备份**：写回前 `shutil.copy2(paths.INTERMEDIATE, paths.INTERMEDIATE.with_suffix('.bak'))`（首次 commit 无原文件则跳过）。`.bak` 只保留一份（再 commit 覆盖）。
- **错误码**：请求体非 JSON / 缺 doc_id / 类型错 / `_DOC_ID_RE` 不中 → **400**；`uploads/<doc_id>.dxf` 不存在 → **404**；管线异常（collect 空 / write 全跳过 / load_nest_pieces 空 / 写盘失败）→ **422**。全部 JSONResponse。
- **`GATE_MM` 别名导入**：`from ..nesting_bounds.load_pieces import GATE_MM as NEST_GATE_MM`（写回新 intermediate 用源常量 1980，避免与既有 intermediate 的可能脏值扩散）。
- **commit 后 reload（US-020）**：`_commit_to_nesting_sync` 成功后立即调 `_reload_pieces_state()`，下一次 `/ws/solve` / `/export` / `/api/ptypes` 即看到新裁片（前端无需重启 ms-web）。返回 payload 加 `reloaded: true`；reload 异常（罕见 I/O 竞态）降级为 `reloaded: false` + `reload_error` 字段，保留旧 state 不半切。
- **回归等价（历史口径，v1 时代）**：旧版（176 片镜像合成）commit 产物与历史 CLI 管线完全等价（实测 176/176、零面积 diff）。US-001 v2 起口径改为「intermediate 条数 = 母版 size≠None 轮廓数」（M1787 = 110），同 doc_id 重跑 idempotent（`total_area_mm2` 稳定）。

## US-020 关键约定（_PIECES_STATE reload + GET /api/ptypes；US-001 v2：键 = g 码）

- **可 reload 状态**：`_PIECES_STATE: dict = {doc, gate_mm, pieces, pieces_by_id}`（替代旧顶层 `PIECES / GATE_MM / PIECES_BY_ID` 三个常量）；`_state_lock = threading.Lock()` 保护读写原子。
- **immutable snapshot 模式**：`_reload_pieces_state()` 在锁内整体 `clear()+update()` `_PIECES_STATE` 引用内容，读者始终拿到完整一致快照（不会读到半状态）。`_get_pieces_state()` 锁内返回当前 state 引用，调用方拿到后整连接复用（一次 ws 连接内 pieces 不变，避免求解中途数据切）。
- **启动期 allow-empty**：import 时 `try: _reload_pieces_state() except: pass` —— intermediate 缺失不再让 `import materialsorting.web.server` 直接崩；`_PIECES_STATE={}` 时 `/api/ptypes` 返 `{representatives:{}}`、`/ws/solve` 报「排料数据为空」、`/export` 报「placed 的 pid 均未匹配」（400）。commit 成功后 `_reload_pieces_state()` 真正填入。
- **`/ws/solve` 快照口径（关键不变量 AC#5）**：accept 阶段 `state = _get_pieces_state()` 取一次快照，整连接内 `pieces/gate_mm` 不变（避免求解中途 reload 切数据）；`build_instance` 用快照 pieces，density 换算用快照 gate_mm。
- **`/export` 快照口径**：每次请求 `_get_pieces_state()` 拿当前 state（请求粒度快照足够；导出是短操作）。
- **GET /api/ptypes（D10，US-001 v2：键 = g 码 label）**：优先返 intermediate 顶层 `label_representatives`（RAW 原始坐标，与上传预览同朝向；键 g01+）；无该字段（v1 旧档）回退从 `_PIECES_STATE.pieces` 按 label 分组取首个代表。返回 `{representatives: Record<label, {label, polygon, net_polygon?, internal_lines?, notches?, grain_line?}>}`。字段白名单 `_LABEL_REPRESENTATIVE_FIELDS` 透传 —— **layer-aware（D11）**：5 层自动带 net/internal/notches/grain。空 state 返 `{representatives: {}}`。
- **curl 验证 M1787**：commit 后 `/api/ptypes` 返 10 个 g 码代表裁片（键 `g01`..`g10`，每个 5 层字段全带）。

## US-022 关键约定（求解输入数量 demand per-size；US-001 v2 改写 + US-002 label 键收口）

- **intermediate label 字段（v2）**：`_commit_to_nesting_sync` 直接以 `assign_codes` 产出的 g 码为每片主键（`pid = f'{label}_{size}'`；`compute_size_ptype_labels` 已删除，无 (size, ptype) 中转、无 L/R 镜像共享 label 概念）。
- **label 对齐不变量（AC#5，v2 简化）**：parse 与 commit 各自对同一母版跑 `assign_codes`（同 collect、同排序键、同母版码规则）→ 同一 `(block_name, size, piece_index)` 必得同 g 码；坐标系差异（NestPiece 归一化 vs PieceOutline 原始）不再影响对齐（M1787 实测 11 码 × g01..g10 逐片对齐，`tests/test_commit_pipeline.py` 覆盖）。
- **共享 labeling 模块**：`nesting_engine/labeling.py` 是 parse/commit 两处标注的单一真相源；`server.py._label_for/_centroid/_size_sort_key` 转发到此。依赖方向合规（web → nesting_engine）。
- **WS /ws/solve 入参增 quantities**：`{label: {sizeKey(str): N}}` | None。`build_instance` 按 `(piece.label, str(piece.size))` 查 N → `spyrrow.Item(demand=N)`；**demand=0 跳过该 piece（D2）**；piece 缺 label 或 quantities=None → demand=1（向后兼容旧 intermediate / 旧前端）。
- **sizeKey 口径**：`str(size)`（number→String）；`null`→`'null'`（与前端 qtyStore `sizeKey` 一致）。
- **US-002 per_type（label 逐片覆盖；2026-08-18 回退 US-004 矩阵化后单级）**：`per_type = {label: {d?, tol?}}` 命中即对该 g 码**全部码号**覆盖（重合/旋转是片型工艺属性、与码号无关；缺维度回退全局档 `params.d_ext`/`tol_ext`）；未命中 / 旧 ptype 键 / 旧两级 `{label:{sizeKey:…}}` 键为 no-op；全局上限收边 `erode=min(d, MAX_OVERLAP_MM=10)`、`tol=min(tol, MAX_ROTATION_TOL_DEG=45)`。**internal 概念已删**：`params.d_int`/`tol_int` 仍被接受但无消费方（R1：生产链路 params 恒 0）。WS start 不再接收/透传 paired/internal。
- **US-002 manifest 全 label 键**：pieces 条目无 `ptype` 键；`color = size_color(size)`（`sparrow_baseline.SIZE_PALETTE` 16 色循环表单一真相源，`size_color(size)=PALETTE[(size-SIZE_ANCHOR)%16]`（锚点 28），2026-08-20 起同码同色跨片型，与 PNG/DXF/CLI SVG 同源；前端画布图例 SizeLegend.tsx 消费同一 color 字段）。对照实验复现：`per_type={'g01':{'28':{'d':1.5}}}` → `n_eroded=1`（仅 g01_28 被腐蚀），对照组 `n_eroded=0`（`tests/test_solver_label.py` 覆盖）。

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
- **density 双口径换算位置**（关键不变量 #1）：**主进程**在收到 frame 时执行 `density_sparrow ← density; density ← total_area/(width*min(gate_mm, PLOT_SAFE_MAX_Y_MM))`（实际幅宽口径，2026-08-20 起分母与求解约束带同口径；钳制在 `_apply_density_dual` 函数内 = web/CLI 所有调用方自动一致）；`total_area` 由 manifest 投递带入主进程。不在子进程做。换算逻辑与公式同旧 threading 版（仅分母口径更新），执行位置不变。
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

## US-011 关键约定（腰头成带 WS 编排接线：exclude_labels + 帧前展开 + stage）

- **StartPayload 新增可缺省 `band` 键**：`{enabled, label}` 恰两键（**2026-08-22 简化**：ack/fillers/time_budget 已删，`_parse_band` 对多余键静默忽略）；缺省/null/{}/非 dict/enabled falsy = 关闭（旧行为逐字段不变，`test_solve_proc.py`/`test_ws_stop.py` 零改动全绿）。
- **`_parse_band` 服务端校验（routes_ws，单一校验点）**：enabled 时 label 须匹配 `^g\d+$` + 存在于当前母版 + 该 g 码 quantities>0（demand 口径镜像 `build_pid_meta`：missing→1、显 0→0、sizeKey=`str(size)`/null→`'null'`）。非法抛 `ValueError` → ws_solve 发 `{type:error}` 早退（**不发 manifest**，与 build 失败同契约）+ **显式 `await ws.close()`**（TestClient 下早退 return 不关 WS 则后续 client receive_json 永不抛 disconnect → 测试挂死）。不合适 g 码（如皮带袢长条）由 `waist_band.FILL_FLOOR_PCT=45` 灾难守卫兜底 → 「成带失败：带内填充率…」error。
- **band 开启消息序**：`stage → manifest → frame* → final`。stage = `{type:'stage',stage:'band',fill_pct,bbox:{width_mm,height_mm},fallback:false,elapsed}`（manifest 前 FIFO 保证唯一一次）；旧前端 switch default 静默忽略，前向兼容。
- **manifest 一致性不变量（AC#1）**：band on/off 的 manifest `total_area_mm2` + `pieces` 列表**逐字段一致** —— `exclude_labels={label}` 只跳 spyrrow Item 层，`pid_meta`/`total_area` 原样（禁用「quantities=0 式移除」——那会连 manifest 一起抹掉）。
- **组合片必须构造期注入**：`build_instance(..., extra_items=[...])` 把 WB_ 组合片（demand=1、朝向 `COMPOSITE_ORIENTATIONS`）在 `StripPackingInstance(...)` 构造时进 items —— **spyrrow `instance.items` 是 Rust 侧副本 list，构造后 `.append()` 静默失效**（实测组合片整解缺席，帧里永远查无 WB_）。
- **进程模型（AC#4）**：band 构造跑在 `solve_worker` 进程内（`_build_band` 同步调用 `build_band_plan`，**不 spawn 孙进程**——`_terminate_solve_process` 的 terminate 不级联孙进程）；stop/断开随 worker 进程 OS 级整体回收，无存活 python 子进程。band 失败（`BandError`/`ValueError`/几何异常）= 只投 `{kind:error,'成带失败:…'}` 不投 manifest（test_solve_proc.py:155 契约）。
- **帧前展开单点 `_emit_placed(placed_items, band)`**：组合片条目（`pi.id == band.pid`）经 `expand_placements`（权威式 `rot_f=m.rot+c.rot; tr_f=R(c.rot)·(m.tr−offset)+c.tr`）展开回成员 placement —— 帧与 final 三处发射点共享该序列化器，**WB_ pid 永不跨进程/永不入 manifest/frame/final**；成员 pid 按 demand 出现 N 次（副本守恒）。
- **测试**：`tests/test_waist_band_ws.py` 8 项（band 关闭四变体直收 manifest / 开启全链路 stage→manifest→末帧副本守恒 / on-off manifest 逐字段一致 / 校验三参数 error 早退（label 格式 / 不存在 / 数量全 0）/ `_parse_band` 纯单元（返回恰 `{'label'}`，多余键静默忽略；`band=None` → None）/ DegenerateBand worker error / band 阶段 stop 无存活子进程（**v2 成带毫秒级，stop 用例换 7 码×8 副本弧形腰片撑 ~2s 构造窗口**）/ `exclude_labels` Item 层单元）。

## 腰头成带旁路功能删除记录（2026-08-22）

> **US-013 预演路由（`routes_band.py` POST /api/band/preview）/ US-014 A/B 验收闭环（`band_accept.py`）/ US-015 填料混带（`band.fillers`）已整体删除**：band 主流程收敛为「WS start `band={enabled,label}` → `_build_band` v2 构造性链 → 组合片进主解 → `_emit_placed` 展开」极简链路；不合适 g 码的守卫唯一入口 = `waist_band.FILL_FLOOR_PCT=45`（带内填充率不足 → 「成带失败」error 早退）。v2 链构造机制与实测数据详见 `nesting_engine/AGENTS.md` waist_band.py 行；US-011 关键约定节即现行全部 WS 编排契约。

## US-033 关键约定（PLT 导出 调用方必读）

- **背景**：现有 DXF 导出在 WT「高速绘图 V8.8 网络版」+ LIKE 绘图仪上**实测无法正常打印**；该软件原生吃 PLT/HPGL（与 ET 排料软件同口径），故新增 PLT 导出链路。MVP 不做物理设备验收（现场由用户落地后反馈）。
- **`write_marker_plt(world_pieces, *, width_mm, gate_mm, title) -> bytes`**（`web/export.py`，签名与 `write_marker_dxf` 对齐；`title` 仅保签名，不输出）：
  - HPGL 常量：`_PLT_SCALE=40`（1mm=40 plotter unit ≈ 0.025mm）、`_PLT_PEN_WIDTH_MM=0.08`、`_PLT_PEN=1`（**全文件唯一笔号**，2026-08-24 用户要求统一颜色=门幅框蓝色，WT 预览按笔号着色、首版按层分 SP1-SP5 五笔预览呈多色已废弃；生产 PLT 实测同样全程仅 SP1 一笔、0 处 PC，勿回退多笔）；`_LAYER_OUTLINE/NET/INTERNAL/NOTCH/GRAIN` 为层收集桶（输出层序，不对应笔号）。
  - 指令序列（**封装口径对齐生产 PLT** `data/PC-20250508NJIF*.plt`）：`IN;PS<纸长>;SP1;PW0.08;` 头部一行（纸长 = max(用布长度, 内容最大X)×40，含刺口±4mm 延伸；无 PS 时 WT 按默认 A0/A3 页幅裁切 7m+ marker）→ **全程单笔 SP1**：门幅框（闭合 PU+PD 4 角）+ 逐片 5 层按层序平铺（轮廓→净版→内部线→刺口→布纹，无 SP 切换）→ `PU;` → `PG;`（出纸收尾）。**CRLF 行尾**；**无 VS/LB 指令**（生产文件均无）。
  - **越界防御** `_plt_frame_stats`：全层顶点 + notch 点须在门幅框内（容差 0.5mm），非 0 记 warning（曾因 notch 未随片旋转产生 600 越界点把 WT 预览拉变形，见 `nesting_bounds/load_pieces.py` 修复）；notch 沿法线 ±4mm 端点外伸门幅属工艺正常，只计入 PS 取值不告警。
  - 坐标：世界坐标(mm) × 40 `round` 取整 → 非负整数（`max(0, ...)` 兜底极小负值）。
  - **闭合策略**：`_plt_polyline(closed=True)` 在 PD 末尾追加首点（物理闭合，与 `write_marker_dxf` POLYLINE 首尾补点策略一致）；内部线/布纹线/刺口 `closed=False`。
  - **空层跳过**：`net_polygon`/`internal_lines`/`notches`/`grain_line` 空则该层无笔画（门幅框 + outline 恒出现）。
  - **布纹箭头线 + 尺码×数量标注（2026-08-24）**：布纹层升级为**单头箭头线**（指向原始画向 B 端：grain_line A→B 端点顺序全程保序 = 母版 layer7 画向；头部对称双羽各 30mm/15°，短杆按 45% 杆长收缩；首版双端形态经用户纠正改单头）+「尺码*数量」**矢量笔画标注**（生产 PLT 逆向：全程无 LB，文字即 PU/PD 笔画；沿画向 u=A→B 阅读、字顶朝 w=(-uy,ux)（画向**左**法线；(u,w) 必须右手系 det>0，否则字形映射整体镜像——首版 w=(uy,-ux) 左手系即"所有文字不分画向全反"bug，2026-08-24 用户截图纠正）、基线离杆 10mm、中心锚 0.85·L；正向(+X)片字顶朝上标注在杆视觉上方、180° 片随片倒置翻到杆视觉下方（用户口径：文字恒在箭头上方，反向片视觉在下是因为片自身倒了 180°）；数量 = 同 pid 副本数（demand>1 → world_pieces 同 pid N 行）；内置数字 0-9+'*' 单笔字库，字库外字符整段跳过 all-or-nothing；几何规则单一真相源 `_grain_annotation_strokes`）。
  - **坐标系**：spyrrow 世界坐标 X=用布长度 Y=门幅 Y 向上，与绘图仪走纸/幅宽天然一致；**绝不带前端 SVG `scale(1,-1)` 翻转**（docstring 显式约束）。
  - 纯标准库字符串拼接，`'\r\n'.join(cmds).encode('ascii')`；**无临时文件**（比 DXF 的 ezdxf 写盘读字节更简单）；**无新 pip 依赖**；全 ASCII，`.decode('ascii')` 不抛异常。
- **`server.py /export` 路由**：`elif fmt == 'plt':` 分支插在 `dxf` 之后、`else` 之前；title 复用 DXF 同款 ASCII（`M1787 util=<pct>% L=<L>cm gate=<gate> seed=<seed>`）；`media, ext = 'application/plt', 'plt'`；文件名拼接走现有 `ext` 变量自动命中（`排料_码<sizes>_<pct>pct_seed<seed>.plt`）。PNG/DXF 行为零回归；未知 fmt 仍返 400 `{error:'未知格式 <fmt>'}`。
- **测试**：`tests/test_export_plt.py` + `tests/test_load_pieces_notches.py`（PLT 封装对齐生产口径：头部 IN;PS;SP1;PW0.08 / CRLF / 尾部 PU;PG / 无 VS/LB / PS 覆盖刺口延伸 / 越界统计 `_plt_frame_stats` / 原有结构断言；notch 随片旋转回归）。合成裁片（5 层全有 + 仅毛版）测试，不依赖 intermediate / sparrow 求解结果。

## US-004 策略桥接关键约定（strategy.py 四路由；web → cli 走进程边界）

- **分层红线**：`strategy.py` 全模块（含函数内）**禁 import `..cli.*`** —— `tests/test_web_strategy.py::test_ast_guard_strategy_no_cli_import` AST 守卫（镜像 test_cli_portfolio 写法）。spawn 子进程是**进程边界**不触发守卫；race 门杀 / se 筛延判据单一真相源留在 `cli.portfolio`，零漂移。CLI 模块名只出现在 spawn cmd 字符串里。
- **对 `server` 的依赖走函数内延迟 import**（`_pieces_state()` → `from .server import _get_pieces_state`）：`server.py` 在**文件尾**才 import 本模块注册路由，若模块级 import server 则「先 import strategy」路径成环；路由被调用时 server 必已完整初始化，函数内 import 任意顺序安全。
- **start**（202）：校验序 = 409（内存态非终态 **或** marker 在）→ 422（state 空 / doc 缺 `doc_id`——旧 intermediate 须重新 commit / `uploads/<doc_id>.dxf` 丢失）→ 400（mode ∉ {se,race}、minutes ∉ {10,20,30,60}、seed 非整数）。config 写 `out/uploads/strategy_cfg_<stamp>.json`（7 键；可选键 `sizes`/`per_type`/`quantities` **仅 truthy 才写**——None 会被 `cli.config.load_config` 按类型错误拒）；`master_dxf` 必为 `resolve()` 绝对路径；`gate_mm` 请求值优先回退 state。
- **快照先于 spawn**：run_dir 基线 = spawn 决策前的 `out/config_runs/` 目录集；CLI 建 run_dir（`new_run_dir` 时间戳不可预知）只能事后 diff 发现（status 每轮重试，发现后写回 `_STRATEGY_STATE` + marker）。若快照晚于 spawn，CLI 抢先建目录会让 diff 扑空（已修，勿回退）。
- **marker** `out/config_runs/.web_strategy_active.json` 恰 5 键 `{pid, run_dir, doc_id, mode, started_at}`（run_dir 初始 null，发现后回写）；终态清 marker、**内存态保留**（status/result 续读，下次 start 覆写）。`_status_from_active` 每次把解析出的 state **写回** `st['state']`（否则「跑完后从未轮询」的内存态永远停在 running，start 单例检查失效）。
- **status 进度源白名单**：`strategy.json`（plan）/ `result.json`（incumbent 摘要**无 placed_items** + per_seed）/ `best_frame_s*.json`（current = 最新 mtime，`_ext` 后缀 → ext 位）/ `kill_decisions.jsonl`（R5_race_gate 行 → gate 事件，非 R5 滤掉）。**绝不读 `curve_s*.json`** —— 运行中是缺右括号的非法 JSON（增量 append，seed 结束才补收口）。
- **stop 树杀**：Windows `taskkill /PID <pid> /T /F`（`/T` 整树——run_config 会 spawn 多进程 solve 孙进程，单杀父进程留孙进程白烧 CPU）；POSIX spawn 带 `start_new_session=True` + `os.killpg`。orphan（内存空 + marker 在）的 stop = pid 存活则树杀 + 清 marker。
- **orphan 分支**：`_pid_alive` Windows 走 `ctypes.windll.kernel32.OpenProcess(0x1000)` 句柄探测（不是本进程 Popen 的孩子，无法 poll）；报 `state:'orphan'` + `alive` 位，前端提供清理动作，不自动接管。
- **result**（done/stopped）：best = result.json `portfolio.incumbent`（完整 placed_items；incumbent **无 `density_sparrow`**——帧入账只存原面积口径，从 `best_frame_s{seed}.json` 边车补，缺则 null）；stopped 无 result.json → 回落各 `best_frame_s*.json` 取 density 最大。manifest = `build_pid_meta(start 时快照, sizes/per_type/quantities 同口径)`（erode 后几何与 placed_items 对齐、demand 已含），pieces 形状与 /ws/solve manifest.pieces 一致。`_STRATEGY_STATE.doc_id ≠ 当前画布 doc_id` → 附 `warning`（母版漂移，导出 pid 失配走既有 400 兜底）。
- **MS_OUT_DIR/env 一致性**：子进程经 env 继承拿到与 ms-web 相同的 `paths.CONFIG_RUNS_DIR`（spawn 不带 cwd/env 覆盖）——测试隔离时**必须用 `MS_OUT_DIR` 环境变量**而不是只 monkeypatch 父进程 `paths`（否则子进程把 run_dir 建到真实 out/，父进程在 tmp 里 diff 扑空）。
