# web — Agent 速查

> FastAPI + WebSocket 工作台（最上层）。可 import 全部下层（dxf_parser / nesting_bounds / nesting_engine）+ `paths`；下层**禁** import 本包。
> 改前先看 `.docs/technical/agent-api-reference.md`（HTTP/WS 契约）+ `.docs/technical/agent-file-map.md` web 章节。

## 启动 / 校验

```bash
python -c "from materialsorting.web.server import app"                # 导入冒烟（含路由表打印）
ms-web                                                                 # 启动 uvicorn :8000（console_script）
python -m materialsorting.web.server                                   # 等价（无 console_script 也能跑）
curl -X POST http://127.0.0.1:8000/api/parse-dxf -F "file=@<dxf>"      # US-004 上传解析
```

> **首次启动前必须**先 `ms-pieces-export` 生成 `pieces_intermediate.json`（`server.py` 顶层 `load_pieces()` 在 import 时读它）。`materialSorting-web/static/` 也需 `npm run build` 一次让 mount 不空（dev 模式 Vite proxy 不依赖 build 产物，但 FastAPI mount 空目录会报错）。

## 文件分工

| 文件 | 角色 |
| --- | --- |
| `server.py` | FastAPI app；路由 `GET /`、`mount /static`、`POST /export`、`POST /api/parse-dxf`（US-004）、`WS /ws/solve`；`ThreadPoolExecutor(max_workers=6)` 求解桥 + 上传解析复用 |
| `solver.py` | `load_pieces` / `discretize_orientations` / `build_instance`（v0.3 erode+tol 包装）/ `solve_with_callback`（spyrrow ProgressQueue + threading，0.2s drain） |
| `export.py` | `apply_transform` / `placed_to_world`（用**原始**非 eroded 轮廓）/ `render_png`（matplotlib Agg）/ `write_marker_dxf`（R12 POLYLINE + ACI 色 + ASCII 标题） |

## US-004 /api/parse-dxf 关键约定（实现方/调用方必读）

- **multipart 依赖 `python-multipart`**：已在 `[web]` extra（`pyproject.toml`）。否则 FastAPI `UploadFile = File(...)` 启动即报 `AssertionError`。
- **落盘路径**：`paths.OUT_DIR/uploads/<doc_id>.dxf`（`doc_id = uuid.uuid4().hex`，32 字符无横杠）。**禁硬编码** —— 用模块级常量 `UPLOADS_DIR = Path(paths.OUT_DIR) / 'uploads'`。
- **CPU 解析走 executor**：`loop.run_in_executor(_executor, _parse_dxf_sync, str(dest))` 复用 6-worker 线程池（与 `/ws/solve` 同池）。母版深度解析 ~1-2s，不阻塞事件循环。
- **错误码口径**：扩展名非 `.dxf`→400；超 `UPLOAD_MAX_BYTES=20MB`→413；ezdxf/collect 异常→422（中文错误信息）。**200 / 400 / 413 / 422 全部走 JSONResponse**（与 `/export` 一致），不抛 `HTTPException`。
- **响应字段**（US-005 前端契约，不能改）：`{doc_id, filename, sizes:[{size, pieces:[{label,name,polygon,internal_lines,notches,net_polygon,grain_line}]}]}`。polygon=`[[x,y],...]`；internal_lines=`[[[x,y],...],...]`；notches=`[[x,y,nx,ny],...]`；net_polygon=`[[x,y],...]`；grain_line=`[x1,y1,x2,y2]` 或 `null`。
- **A/B/C 标注口径**：每码内独立编号（不跨码续编）。排序键 `(-centroid_y, centroid_x, -area_mm2, block_name, piece_index)` → 上方/左/大片优先。码号分组排序：数值升序，`null` 殿后。`_label_for` 支持 26+ 自动 AA/AB（实测每码 ≤10 片，AA+ 仅兜底）。
- **doc_id 是 US-010 入参**：`POST /api/commit-to-nesting {doc_id}`（待 US-010 实现）会读 `uploads/<doc_id>.dxf`。**doc_id 必须可定位落盘文件**，故成功响应才返回 doc_id（422 时文件保留但响应不带 doc_id）。

## 已踩坑 / 注意事项

- **顶层 `load_pieces()` 在 import 时执行**：intermediate 缺失 → `import materialsorting.web.server` 直接崩。改启动顺序（如延迟加载）需同步更新 `.docs/technical/agent-file-map.md` 关键不变量 #8。
- **`_executor` 是全局共享池**：求解（`/ws/solve`）+ 上传解析（`/api/parse-dxf`）共 6 worker。解析快（~1-2s）+ 求解长（120s+），实测不互相阻塞；如需隔离请改两池。
- **UploadFile 读取**：`await file.read()` 一次性读全到内存（20MB 上限内可接受）。流式校验需自写 chunk loop，当前实现选简单。
- **响应 filename 字段**：透传客户端 `file.filename`（中文文件名浏览器走 UTF-8 正常；curl 命令行可能用本地 codepage → 终端显示乱码，但 JSON 内部仍是原 bytes）。前端 US-006 显示文件名用此字段。
- **frontend dev proxy `/api`**：US-009 待加 `vite.config.ts` 的 `server.proxy`，目前 dev 模式直连 :8000 才能命中 `/api/parse-dxf`。`/export`、`/ws` 已有 proxy，`/api` 与之并列。
