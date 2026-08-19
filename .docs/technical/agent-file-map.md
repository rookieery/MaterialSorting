# Agent 文件地图 — 后端

> 后端 Python 包逐文件索引。改任何 `.py` 先看这里定位职责与下游影响，并同步本文件。
> 前端文件地图见 [agent-component-map.md](agent-component-map.md)；HTTP/WS 契约见 [agent-api-reference.md](agent-api-reference.md)。

## 分层架构（依赖单向，禁反向）

```
cli  →  web  →  nesting_engine  →  nesting_bounds  →  dxf_parser
       (sparrow_experiments → sparrow_baseline)
```

每层只依赖下层；下层不得 import 上层。`paths.py` 是所有层的公共路径常量来源。

## 目录树

```
materialSorting-server/
├── pyproject.toml                     包定义 + 6 个 ms-* console_scripts + [web] 可选依赖（fastapi/uvicorn/matplotlib/python-multipart）
└── src/materialsorting/
    ├── paths.py                       集中路径常量（优先环境变量，禁止硬编码 ..）
    ├── dxf_parser/                    底层 DXF 读写（仅 stdlib + ezdxf）
    │   ├── collect.py                 US-003 母版深度解析（collect_pieces_with_details + LAYER_MAPPING）
    │   ├── reader.py                  ezdxf recover + GBK 块名 + R12 POLYLINE 读取
    │   ├── geometry.py                纯几何算子（无 ezdxf，可单测）
    │   ├── model.py                   PieceOutline dataclass（解析期唯一 IR；US-002 扩 internal/notches/net_polygon）
    │   ├── explore.py                 母版全裁片探索 CLI（SVG/JSON/CSV）
    │   └── export_dxf.py              PieceOutline → 单裁片 R12 DXF
    ├── nesting_bounds/
    │   └── load_pieces.py             单裁片（pieces_manifest.json 驱动）→ 布纹对齐 → 归一化（US-001 v2：无镜像展开）；定义 NestPiece（pid={label}_{size}）+ 门幅双口径常量（GATE_MM=1980 显示 / PLOT_SAFE_MAX_Y_MM=1910 绘图仪可写 / NEST_GATE_MM=min 求解约束带）
    ├── nesting_engine/
    │   ├── constraints.py             v0.3 约束常量 + 位图腐蚀 + 合法性校验
    │   ├── sparrow_baseline.py        基线求解 + ★共享层（被 experiments/export/solver 复用）
    │   ├── sparrow_experiments.py     旋转/重合公差实验
    │   └── labeling.py                g01+ 编号单一真相源（assign_codes；parse/commit 两管线共用）
    ├── web/                           FastAPI + WS 工作台（详见 agent-api-reference.md）
        ├── server.py                  app + 路由（GET /、/static、POST /export、POST /api/parse-dxf、POST /api/commit-to-nesting、GET /api/ptypes、WS /ws/solve）+ 求解线程桥 + US-020 _PIECES_STATE 可 reload（threading.Lock immutable snapshot）+ US-004 上传解析 + US-010 commit-to-intermediate（commit 后 reload）+ US-022 intermediate 加 label + WS quantities 入参
        ├── solver.py                  build_instance（US-022 quantities→demand，0 跳过；US-002 per_type[label][sizeKey] 命中即覆盖 + internal 删 + color=label_color；strip_height=min(gate,PLOT_SAFE_MAX_Y_MM) 求解钳绘图仪可写幅宽）+ solve_with_callback（threading 旧版，保留）+ solve_with_callback_proc（US-025 多进程版，返回 process 句柄可 terminate）
        ├── solve_worker.py             US-025 子进程入口（顶层 solve_worker，spawn 可 pickle；子进程内 build_instance + solve，仅 JSON 数据跨进程）
        └── export.py                  PNG(matplotlib) + R12-DXF marker + HPGL/PLT 文本 导出（US-002 起颜色/图例/ACI 全 g 码键：label_color 16 色循环 + label_aci=((code-1)%24)+1 + 图例=placed label 并集；PLT：内容压进 Y≤1910 可写幅宽 + PD 分块 ≤10点/≤110B + 走纸引导）
    └── cli/                           配置驱动求解 CLI（PRD config-driven-solve-cli；最上层编排，绝不 import web.server，产物只落 out/config_runs/）
        ├── config.py                  US-001 load_config：7 键 JSON 配置严格校验（ConfigError(ValueError) 中文报错含字段名；seeds 非负整数列表取代旧 seed 三键；master_dxf 相对路径 CWD→仓库根两候选解析；quantities 码号键数字字符串或 'null'、数量 JSON 数字；per_type g 码键 + d/tol，超 MAX_OVERLAP_MM/MAX_ROTATION_TOL_DEG 上限 warn 钳制提示）→ NestRunConfig dataclass；模块级仅标准库（paths/constraints 走函数内延迟 import 保持单一真相源）
        └── pipeline.py                US-002 commit_from_config(cfg, run_dir)：镜像 web/server._commit_to_nesting_sync 编排（collect → assign_codes → write_piece_dxf {label}_{size}.dxf + pieces_manifest.json → load_nest_pieces → intermediate 落 run_dir/pieces_intermediate.json），piece 条目与 web 逐字段一致（含 rounding 位数）、顶层省略 label_representatives、不写 .bak、gate_mm 写 cfg.gate_mm（配置驱动）；new_run_dir(run_name) 时间戳目录 <name>_<YYYYMMDD-HHMMSS>；只写 paths.CONFIG_RUNS_DIR 物理隔离 web 事实源
```

## paths.py — 路径常量（30 行）

所有数据/产物/前端目录的唯一来源。**禁止在代码里硬编码 `..` 上溯或绝对路径**，一律 `from .. import paths` 后用 `paths.XXX`。

| 常量 | 值（默认） | 环境变量 |
|------|-----------|---------|
| `DATA_DIR` | `<repo>/data` | `MS_DATA_DIR` |
| `OUT_DIR` | `<server>/out` | `MS_OUT_DIR` |
| `SPARROW_DIR` | `OUT_DIR/sparrow_baseline` | — |
| `INTERMEDIATE` | `SPARROW_DIR/pieces_intermediate.json` | — |
| `CONFIG_RUNS_DIR` | `OUT_DIR/config_runs`（US-002 起，CLI 专属产物根：cli 子包唯一可写目录，禁写 INTERMEDIATE/uploads） | — |
| `MASTER_DXF_GLOB` | `DATA_DIR/M1787*(2).dxf` | — |
| `STATIC_DIR` | `<repo>/materialSorting-web/static` | `MS_STATIC_DIR` |

## dxf_parser/ — 底层 DXF 读写

仅依赖标准库 + ezdxf，不依赖任何兄弟包。

### `reader.py`（101 行）— ezdxf 读底层

抗住母版 DXF 的 3 个怪癖：① `ezdxf.recover.readfile` 返回 `(doc, errors)` 元组需解包；② `$DWGCODEPAGE` 标 ANSI_1252 但块名实为 GBK；③ `$INSUNITS` 不可信（实测 6），统一按 mm 解释。

| 函数 | 签名 | 说明 |
|------|------|------|
| `decode_str` | `(s: str) → str` | GBK 解码块名/文本，失败回退原值 |
| `load_doc` | `(path: str)` | 读 DXF，优先 `ezdxf.recover.readfile`，回退 `readfile` |
| `parse_size` | `(block_name: str) → int \| None` | 从块名尾提取码号；失败 None |
| `strip_size` | `(block_name: str) → str` | 去码号 → "类型"部分（分组键） |
| `polyline_points` | `(entity) → list[(x,y)] \| None` | R12 POLYLINE 顶点；非 POLYLINE 返 None；不做抽稀 |
| `is_polyline_closed` | `(entity) → bool` | POLYLINE 闭合标志（优先属性，回退 `flags & 1`） |
| `iter_block_entities` | `(block, layers: set[str] \| None = None) → iterator` | US-002：按可选 layer 白名单迭代 block 内实体（不指定 layer 返全部）；供 US-003 深度解析统一提取入口 |

私有：`_SIZE_RE = re.compile(r"[._](\d+)$")` —— 只匹块名**尾**的 `.<数字>` 或 `_<数字>`，避免误匹 `M1787#28-32小33-38大码`。

### `geometry.py`（85 行）— 纯几何算子

操作 `list[(x,y)]` 多边形，**不依赖 ezdxf**，可独立单测。顶点原样保留。

| 函数 | 签名 | 说明 |
|------|------|------|
| `polygon_perimeter` | `(pts) → float` | 闭合周长（自动首尾相连） |
| `polygon_area` | `(pts) → float` | 鞋带公式面积，绝对值 mm² |
| `bbox_of` | `(pts) → (minx,miny,maxx,maxy)` | 外接框 |
| `point_in_polygon` | `(pt, poly) → bool` | 射线法点在多边形内 |
| `line_midpoint` | `(p1,p2) → (x,y)` | 线段中点 |
| `line_angle_deg` | `(p1,p2) → float` | 线段对水平角（度） |
| `match_grain` | `(grain_lines, polygons) → [line\|None]` | 每条布纹线配中点所在多边形；一对一，首中即取；返回与 `polygons` 平行 |

### `model.py`（39 行）— PieceOutline dataclass

解析期唯一 IR，一条 layer1 POLYLINE 对应一个。**刻意不携带 `piece_type`** —— 语义类型识别留给独立程序。

| 字段 | 类型 | 含义 |
|------|------|------|
| `source_file` | `str` | 母版文件名 |
| `block_name_raw` / `block_name` | `str` | 原始 / GBK 解码后块名 |
| `size` | `int\|None` | 块名尾码号，解析失败 None |
| `piece_index` | `int` | 该块内第几个 layer1（0 基） |
| `group_key` | `str` | `f"{group_base}#{idx}"` |
| `polygon_mm` | `list[(x,y)]` | layer1 轮廓顶点（mm，原样） |
| `is_closed` | `bool` | POLYLINE 闭合标志 |
| `vertex_count` | `int` | 顶点数 |
| `perimeter_mm` / `area_mm2` | `float` | 周长 / 鞋带面积 |
| `bbox_mm` | `(minx,miny,maxx,maxy)` | 外接框 |
| `grain_line` | `(x1,y1,x2,y2)\|None` | 匹配的布纹线 |
| `grain_angle_deg` | `float\|None` | 布纹线对水平角 |
| `grain_orientation` | `str` | `'horizontal'\|'vertical'\|'unknown'`（排料侧旋向依据） |
| `internal_lines` | `list`（默认 `[]`） | US-002：layer8 POLYLINE 内部线 `[[ (x,y), ...], ...]`，由 US-003 填充 |
| `notches` | `list`（默认 `[]`） | US-002：layer4 POINT 刀口 `[(x,y,nx,ny), ...]`（点 + 单位法向量），由 US-003 填充 |
| `net_polygon` | `list`（默认 `[]`） | US-002：layer14 POLYLINE 净版轮廓 `[(x,y), ...]`，由 US-003 填充 |

方法：`to_dict()` → `asdict(self)`（新字段自动序列化；既有调用方 `sparrow_baseline`/`explore.collect_pieces` 默认空 list 零改动可用）。

### `collect.py`（294 行）— US-003 母版深度解析

`collect_pieces_with_details(path)` 还原单片全部信息：复用 `explore.collect_pieces` 拿 layer1 毛版外轮廓 + layer7 布纹线（`match_grain`），二次扫描 layer14/layer8/layer4 实体后按几何归属到 outline。

**layer 映射集中在 `LAYER_MAPPING`** 常量（版师 2026-08-10 确认；5156 与 M1787 一致）：

| 语义 | layer | 实体 | 字段 |
|------|-------|------|------|
| 毛版 outline | `"1"` | POLYLINE | `polygon_mm` |
| 净版 net | `"14"` | POLYLINE | `net_polygon` `[(x,y),...]` |
| 内部线 internal | `"8"` | POLYLINE | `internal_lines` `[[(x,y),...], ...]` |
| 布纹线 grain | `"7"` | LINE | `grain_line` `(x1,y1,x2,y2)` |
| 刀口 notch | `"4"` | POINT | `notches` `[(x,y,nx,ny), ...]` |

> layer 2/3/13 不提取（参考点 / 轮廓密点 / 未定语义，**非刀口**）。

| 函数 | 签名 | 说明 |
|------|------|------|
| `collect_pieces_with_details` | `(path: str\|Path) → list[PieceOutline]` | 主流程：先调 `explore.collect_pieces` 拿 outline+grain，再二次扫描每 block 的 layer14/8/4，按质心/最近边几何归属到 outline |
| `_signed_area` | `(poly) → float` | Shoelace 带符号面积（>0 = CCW） |
| `_nearest_edge_with_normal` | `(pt, poly, signed_area) → (idx, dist, nx, ny)` | 找最近边 + 单位外法线（CCW 取 `(dy,-dx)/len`，CW 取反） |
| `_centroid` | `(pts) → (x, y)` | 顶点算术质心（net/internal POLYLINE 归属用） |
| `_assign_notch` | `(pt, outlines) → (pi, nx, ny)\|None` | Pass 1 严格 point-in-polygon；Pass 2 回退所有 outline 最近边 |
| `main()` | — | CLI 冒烟：`python -m materialsorting.dxf_parser.collect <dxf> [-v]` 打印每码片数 + internal/notch/net 计数 |

**归属策略**：
- layer14 净版：质心 `point_in_polygon` 命中即归属；1:1，每片最多 1 条（多条取首条）。
- layer8 内部线：质心命中归属；多线/片。
- layer4 刀口：先严格 `point_in_polygon`，全部 outline 都不包含则取最近边所属片（边界 / 外贴边点兜底）。

**实测分布（M1787 与 5156 一致）**：110 outline = 110 net = 110 grain（1:1:1）；286/297 internal、704 notch（545 严格 in-polygon + 159 边界点回退最近边）。

### `export_dxf.py`（143 行）— 单裁片 R12 DXF 导出（5 层，US-024）

每个裁片导出为 `<类型>_<码号>.dxf`：layer 1 = 毛版轮廓（闭合 POLYLINE），layer 14 = 净版（闭合 POLYLINE），layer 8 = 内部线（多条 POLYLINE），layer 4 = 刺口（POINT 位置，法线不存盘），layer 7 = 布纹线（LINE）。Richway/ET 兼容。

- **import 时副作用**：`logging.getLogger("ezdxf").setLevel(ERROR)` —— 静默 R12 `$INSUNITS` warning（R12 规范不导出单位变量，单位 mm 隐式）。
- （US-001 v2 已删）`GROUP_NAMES` / `assign_group_no` —— 名称识别整体退场；本模块仅剩 `write_piece_dxf`（文件名 `{label}_{size}.dxf`，g 码由调用方 `labeling.assign_codes` 决定）。
- `write_piece_dxf(piece, out_path)` —— 写单裁片 5 层 DXF。US-024：若 PieceOutline 携带 `net_polygon` / `internal_lines` / `notches`（来自 `collect_pieces_with_details`），同时写 layer14/8/4；notch 仅存 POINT 位置，法线 (nx, ny) 丢弃（读时由 `load_pieces._read_piece_full` 按 outline 最近边重算）。库函数，由 `web/server._commit_to_nesting_sync` 调用切单裁片到 `out/uploads/<doc_id>_pieces/`（原 `ms-export-dxf` CLI 已移除）。

### `explore.py`（335 行）— 母版全裁片探索

遍历每个 block，提取每条 layer1 闭合 POLYLINE 为一个 `PieceOutline`，按 `group_key` 分组，产出分组目录（SVG + JSON）+ 全量 CSV + 总览 SVG。

| 函数 | 签名 | 说明 |
|------|------|------|
| `collect_pieces` | `(path) → list[PieceOutline]` | 核心抽取：跳匿名块（`*`）、滤 layer `"1"` 的 POLYLINE（≥3 点）、配 layer `"7"` 布纹线、算周长/面积/bbox/布纹朝向 |
| `sanitize` | `(s) → str` | 块名 → 合法目录名片段 |
| `group_label` | `(group_base) → str` | 主块 → `"main"`；否则去 `noname.` 前缀 + `sanitize` |
| `group_sort_key` | `(members)` | 主块组优先；再按块名 + piece_index |
| `piece_svg` | `(p, w=520, h=680) → str` | 单片 SVG（翻转 y，虚线红布纹线） |
| `overview_svg` | `(pieces, w=1700, h=1200, pad=50) → str` | 总览 SVG + 分组色例 |
| `write_outputs` | `(pieces, outdir) → [(group_no,label,sample,n)]` | 分组目录 + `pieces.json` + `_all_pieces.csv` + `_overview.svg` |
| `write_csv` | `(path, rows)` | UTF-8-BOM CSV，17 列 |
| `resolve_dxf` | `(arg) → Path\|None` | 路径/glob → 首个存在匹配 |
| `main()` | — | CLI，默认 `--dxf paths.MASTER_DXF_GLOB`，`--out paths.SPARROW_DIR` |

私有：`_flip`、`_color_for`（基于 md5 的稳定 HSL 色，抗 `PYTHONHASHSEED`）。

## nesting_bounds/ — 裁片加载

### `load_pieces.py`（312 行）— 单裁片 → NestPiece（5 层透传，US-024）

读 `pieces_manifest.json`（US-001 v2 manifest 驱动，`[{file,label,size}]`；无 sidecar 明确报错「请重新 commit」）→ 逐文件读单裁片 DXF → 布纹对齐到水平 → 归一化到原点（**无镜像展开**：镜像/`side` 概念已删，每文件恰一条 NestPiece，`pid=f'{label}_{size}'`）。布纹仅用于读取期水平对齐，之后无旋转约束。`_read_piece` 读 5 层（layer1+layer14+layer8+layer4+layer7），notch 法线按 outline 最近边重算（与 `collect._nearest_edge_with_normal` 同算法）；5 层经 `_apply_layer_transforms` 与 polygon 共享 rotate→normalize transform 链。

**模块级常量：**

| 常量 | 值 |
|------|-----|
| `GATE_MM` | `1980.0`（门幅：布幅**显示**口径 —— UI / 密度分母 / PNG·DXF·PLT 外框，不减布边） |
| `PLOT_SAFE_MAX_Y_MM` | `1910.0`（绘图仪 Y 可写幅宽，LIKE + WT「高速网口输出中心 V8.8」现场口径；2026-08 撞机根因 = 旧导出门幅框画到 1980、顶部刺口伸 1983.9mm，Y 超程小车撞导轨硬限位） |
| `NEST_GATE_MM` | `min(GATE_MM, PLOT_SAFE_MAX_Y_MM)`（**求解约束带** strip 高度上限；web/solver 与 CLI 引擎同源引用；换机器/换布幅只改上面两个常量，此处自动跟随） |
| （US-001 v2 已删）`PAIR_TYPES` / `ALL_TYPES` —— 镜像展开与片型集合退场 |
| `ALL_TYPES` | `['前片','后片','腰','前袋','后袋','机头','单排','双排','火机袋','裤耳']`（10 类规范序） |
| `DEFAULT_SIZES` | `[28,29,30,31,33,34,35,36]`（8 码，**跳 32**） |

**`NestPiece` dataclass（US-001 v2 label 主键 + US-024 扩 5 层字段；无 ptype/side）：**

| 字段 | 类型 | 含义 |
|------|------|------|
| `pid` | `str` | 唯一 ID = `f'{label}_{size}'`，如 `'g03_28'` |
| `label` | `str` | 裁片 g 码（全链路主键） |
| `size` | `int` | 码号 |
| `polygon` | `list[(x,y)]` | 毛版顶点，bbox 左下归一到原点 |
| `bbox` | `(minx,miny,maxx,maxy)` | 外接框 |
| `area_mm2` | `float` | 多边形面积 |
| `source` | `str` | 源 DXF 文件名 |
| `net_polygon` | `list[(x,y)]`（默认 `[]`） | US-024 净版（layer14） |
| `internal_lines` | `list[list[(x,y)]]`（默认 `[]`） | US-024 内部线（layer8） |
| `notches` | `list[(x,y,nx,ny)]`（默认 `[]`） | US-024 刺口（layer4；法线按 outline 最近边重算） |
| `grain_line` | `(x1,y1,x2,y2) \| None`（默认 `None`） | US-024 布纹线（layer7） |

属性：`width = bbox[2]-bbox[0]`，`height = bbox[3]-bbox[1]`。

私有：`_rotate`（绕原点旋）、`_normalize`（bbox 左下平移到原点）、`_read_piece`（读全 5 层 → `(polygon, grain_deg, net, internal, notches, grain_line)`）、`_align_grain_horizontal`（竖布纹 ±90° → 水平；水平不变）、`_rotate_normal(nx, ny, deg)`（US-024 法线随片旋转）、`_grain_rotation_deg(grain_deg)`（US-024 把 grain_deg 映到 transform 旋角，与 `_align_grain_horizontal` 同语义）、`_apply_layer_transforms(...)`（把 5 层原始数据按 rotate→normalize 链统一变换，US-001 v2 起 **mirror 参数已删**；**notch 点必须随片旋转**——旧实现只转法线不转点，竖直布纹片 rot=±90 时刺口飞出轮廓 3m+（腰/后袋），PLT 导出 600 越界点、PNG/DXF 同源污染，已修复并有 `tests/test_load_pieces_notches.py` 回归）。（US-001 v2 已删：`_mirror_x` / `_read_piece_full` 旧别名 / 镜像分支。）

入口：`load_nest_pieces(data_dir) → list[NestPiece]`（US-001 v2：读 `pieces_manifest.json` 驱动，每条目恰一片；无 sidecar / 旧版目录 → RuntimeError「请重新 commit」）。

## nesting_engine/ — sparrow 求解 + v0.3 约束

### `constraints.py` — v0.3 约束层

重合/旋转**全局**上限（2026-08-17 起，不再按片型钳制）、求解后 `validate`（数量 / 门幅 / 用料长）。版师确认的每片型工艺上限（外片 0.4–2mm / 前袋旋转 30° 等）保留在 `business/排料规则_详细版.md` §3.2/§4 作参考，由用户在高级配置弹窗按片型显式填值控制，默认 0。

**模块级常量：**

```
MAX_OVERLAP_MM       = 10.0   # 全局最大重合深度（mm；UI 高级配置重合输入 max 同值）
MAX_ROTATION_TOL_DEG = 45.0   # 全局最大旋转公差（°，绕 {0°,180°}；旋转输入 max 同值）
# US-001 v2 已删：GROUP_NAMES / PAIR_TYPES / ALL_TYPES（名称识别与镜像展开退场）
# US-002 已删：PAIR_TYPES + 成对齐套校验（L 数=R 数，服务于已删除的合成镜像模型）
```

> 旧 `MAX_OVERLAP`/`ROTATION_TOL` 每片型字典 + `overlap_dpix` 已删（`web/solver.build_instance` 的钳制改 `min(申请值, 全局上限)`）。

| 函数 | 签名 | 说明 |
|------|------|------|
| `erode_bitmap` | `(bm, d_pix) → bm` | 4 邻域形态学腐蚀 `d_pix` 次；`d_pix<=0` 原样返回 |
| `validate` | `(placed_world, pieces, used, gate, res) → (ok, issues)` | 校验数量、x∈[0,gate]、used>0（US-002 起不再读 ptype/side —— 成对齐套校验已删） |

### `sparrow_baseline.py` — 基线 + ★共享层

Stage 2 §6：把 intermediate 全片喂给 spyrrow（无服装约束的纯几何）求几何上界。产出 `result_*.json` / `*.svg` / `*_curve.json` / `*_curve.png`。**同时是共享层**：`label_color` / `_clean_polygon` / `_write_svg` / `_plot_curve` / `solve_with_progress` 被 experiments/export/solver 复用。

**模块级常量（US-002 起 g 码配色单一真相源）：**

```
LABEL_PALETTE = ('#1f77b4','#ff7f0e','#2ca02c','#d62728','#9467bd','#8c564b','#e377c2',
                 '#7f7f7f','#bcbd22','#17becf','#aec7e8','#ffbb78','#98df8a','#ff9896',
                 '#c5b0d5','#c49c94')   # 16 色 d3 系循环表（tableau10 + 6 pastel）
DEFAULT_COLOR = '#bbbbbb'               # 非 g 码 / None 兜底
# label_color(label) = LABEL_PALETTE[(code_sort_key(label)-1) % 16]；同码同色，g17 循环回表头。
# 旧 PTYPE_COLORS（中文名 → 色值）US-002 已删；solver manifest / PNG / CLI SVG 三处同源取色。
```

| 函数 | 签名 | 说明 |
|------|------|------|
| `solve_with_progress` | `(instance, config) → (sol, curve, elapsed_sec)` | daemon 线程跑 `instance.solve(config, progress=ProgressQueue)`，主线程 drain 收 anytime 曲线；curve 项 `{elapsed,phase,report,density,width_mm}`；30s 心跳 log。**被 baseline + experiments 共用** |
| `main()` | — | CLI：`--sizes`/`--time`(600)/`--seed`/`--no-svg`/`--no-curve`；读 `INTERMEDIATE`，构 `spyrrow.Item(allowed_orientations=[0,180])` + `StripPackingInstance(strip_height=min(gate, PLOT_SAFE_MAX_Y_MM))`（与 web/solver 同口径钳绘图仪可写幅宽；密度/理论用布仍按 gate）+ `StripPackingConfig(time,seed,num_workers=4)` |

私有：`_clean_polygon(poly,eps=0.01)`（去连续重复点 + 闭合重复点；spyrrow 自身也去重，此为多一层保险，**不**处理非连续重复/自交）、`_transform_polygon`（绕原点旋 + 平移，与 `PlacedItem` 语义一致）、`_fmt`、`_write_svg`（viewBox = used×gate mm，`<g transform="translate(0,H) scale(1,-1)">` 翻 y）、`_plot_curve`（matplotlib anytime 收敛图 + 阶段着色 + best-so-far 包络 + 90% 参考线；无 matplotlib 优雅降级）。

> `num_workers=4`：spyrrow 0.9.0 修了 `num_wokers` 拼写错；**>4 反而质量更差（issue #113）**。

### `sparrow_experiments.py` — 旋转/重合公差实验

实验 ②③ 量化旋转公差与重合公差上界。基线 = 实验 ① 600s `{0,180}` 无 erode = **85.79%**（`result_{tag}_t600.json`）。spyrrow 参考数：TROUSERS 92.6% / SHIRTS 90.9%（arxiv 2509.13329）。

**复用共享层：** `from .sparrow_baseline import _clean_polygon, _write_svg, _plot_curve, solve_with_progress`

**模块级常量：** `STEM_ALL = '28_29_30_31_33_34_35_36'`、`OUT = paths.SPARROW_DIR`、`INTERMEDIATE = paths.INTERMEDIATE`（US-002 起 `INTERNAL_TYPES` 已删 —— intermediate 无片型字段，内片 g 码集合改 `--internal g04,g07` 命令行参数显式给出）。

| 函数 | 签名 | 说明 |
|------|------|------|
| `erode_polygon` | `(poly, d) → poly` | shapely 向内 buffer `d` mm → 外环坐标；失败/空回退原 poly；Multi 取最大 |
| `build_pieces` | `(doc, exp, erode_d, internal_labels=frozenset()) → (items_meta, total_orig_area, n_internal_eroded)` | 4 模式：`free_rot`（全自由旋）/`v0_rot`（内片自由 + 外片 `{0,180}`）/`erode`（仅内片 erode，朝向仍 `{0,180}`）/`erode_rot`（内片 erode+自由旋，外片 `{0,180}`）；内片判定 = `p.get('label') in internal_labels`，items_meta 条目含 `label` 键（无 ptype） |
| `run_one` | `(doc, gate, exp, erode_d, time_budget, seed, internal_labels=frozenset())` | 跑一次；`strip_height=min(gate, PLOT_SAFE_MAX_Y_MM)`（与 web/solver 同口径；密度仍按 gate）；同时报 `real_density`（原面积分母）+ `sparrow_density`（erode 后自报）；写 `result_{stem}.json`/`{stem}_curve.json`/`{stem}.svg`/`{stem}_curve.png`，stem = `exp_{tag}_t{T}_s{seed}` |
| `main()` | — | CLI：`--exp {free_rot\|v0_rot\|erode\|erode_rot\|all}`(默认 all)/`--d`(5)/`--time`(600)/`--seed`(0)/`--internal`(csv g 码集合)/`--seeds`(csv→多种子方差汇总)；写 `experiments_summary_t{T}.json`（含 `internal_labels`）或 `multiseed_{exp}_d{d}_t{T}.json` |

### `labeling.py` — g01+ 编号单一真相源（US-001 v2 label 先行）

parse-dxf 响应（`web/server.py._build_parse_payload`）与 intermediate（`web/server.py._commit_to_nesting_sync`）的**单一真相源** —— 保证两条管线对同一母版产出的 label 按 `(block_name, size, piece_index)` 逐片同码（AC#5；否则 qtyStore 按 label 编辑的数量会配错裁片）。

| 函数 | 说明 |
|------|------|
| `label_for(idx)` | 0→g01, 1→g02, ..., 98→g99（g + 两位零填充，字典序=数值序） |
| `code_sort_key(code)` | g 码 → 数值序键（'g02'→2；非 g 码兜底 0）；US-002 起图例排序 / `label_color` / `label_aci` 共用 |
| `master_code_from_block_name(name)` | 母版 block 名显式编号尾缀（`前片g03.30`/`腰G3`/`袋#7`）→ 规范化 `gNN`；纯数字尾缀不识别 |
| `centroid(poly)` | 顶点算术质心（稳定排序键 + 导出 g 码叠印定位共用） |
| `size_sort_key(size)` | 码号排序：None 殿后，其余升序 |
| `parse_member_sort_key(p)` | **码内稳定排序键单一真相源** `(-centroid_y, centroid_x, -area_mm2, block_name, piece_index)`（2026-08-17 收敛；parse 赋号 / label 对齐 / label 代表裁片三处共用，改一处自动三处同步） |
| `sequential_sort_key(p)` | US-001 v2（替代已删 `compute_size_ptype_labels`）：`assign_codes` 顺序赋码排序键 `(group_key,) + parse_member_sort_key(p)` —— T4 group_key 前置保证同一 block 模板跨码同号 |
| `collect_master_codes(pieces)` / `assign_codes(pieces)` | 母版编号 all-or-nothing 收集 / 每码排序 + g 码分配（顺序模式 + 母版复用模式），详见 `nesting_engine/AGENTS.md` |

## web/ — FastAPI + WebSocket 工作台

详见 [agent-api-reference.md](agent-api-reference.md)。此处仅文件级速查：

| 文件 | 行 | 职责 |
|------|----|------|
| `server.py` | 795 | FastAPI app；**启动期 `_reload_pieces_state()`**（US-020 替代旧顶层 `load_pieces()`，allow-empty 不再让 import 崩）；路由 GET `/`、mount `/static`、POST `/export`（文件名前缀取 payload `filename` 上传母版名去 .dxf，缺省回退「排料」/nesting）、POST `/api/parse-dxf`（US-004 上传解析；**US-001 v2 起响应仅 `label` + 5 层字段，`name`/`ptype`/`paired` 删除** —— `_build_parse_payload` 入口先跑 `labeling.assign_codes(pieces)`（无名称参数）g 码先行）、POST `/api/commit-to-nesting`（US-010 + US-020 commit 后 reload `_PIECES_STATE` + US-022 intermediate 加 label）、GET `/api/ptypes`（US-020 裁片代表 D10/D11；**US-001 v2 键 = g 码 label**，`_LABEL_REPRESENTATIVE_FIELDS` 白名单，优先 intermediate `label_representatives`）、WS `/ws/solve`（accept 阶段 `_get_pieces_state()` 快照 + US-022 quantities 入参；**US-026 进程化**：`solve_with_callback_proc` 替代旧 threading 桥，write loop 内联 drain queue + read loop 后台 task 收 `{action:'stop'}` → terminate process → 发 `{type:'stopped'}` → 关闭 WS；客户端断开 → terminate+join 防孤儿）；`_terminate_solve_process(state_box)` 幂等 terminate+join+kill 兜底；`_state_lock=threading.Lock()` 保护 immutable snapshot；`ThreadPoolExecutor(max_workers=6)` 跑 `run_solve`（US-004 解析 / US-010 commit 也复用此池）；上传常量 `UPLOAD_MAX_BYTES=20MB` / `UPLOADS_DIR=paths.OUT_DIR/uploads` / `_DOC_ID_RE`；`_build_parse_payload` 按码分组 + `assign_codes` g01+ 赋号（T4 group_key 前置排序）；`_commit_to_nesting_sync` Path A 全管线（assign_codes 最先 → `{label}_{size}.dxf` + `pieces_manifest.json` → manifest 驱动加载 → intermediate v2 + `label_representatives`）；`_LABEL_REPRESENTATIVE_FIELDS` 透传白名单 |
| `solver.py` | 398 | `load_pieces` / `discretize_orientations` / `build_instance`（**erode=min(申, MAX_OVERLAP_MM=10)，tol=min(申, MAX_ROTATION_TOL_DEG=45)，2026-08-17 起全局上限不再按片型**；US-022 quantities→demand，0 跳过；**US-002**：`per_type[label][sizeKey]` 命中即覆盖 d/tol（未命中/旧 ptype 键 no-op）、internal 概念删（`d_int`/`tol_int` 无消费方）、pid_meta 无 ptype 键且 `color=label_color(label)`；**strip_height=min(gate_mm, PLOT_SAFE_MAX_Y_MM)** —— gate_mm 是显示口径，求解约束带钳绘图仪可写幅宽 1910，密度/导出/前端仍用 gate_mm 原值；US-024 pid_meta 加 5 层字段 `.get()` 向后兼容）/ `solve_with_callback`（**旧** threading 版，保留不删）/ `solve_with_callback_proc`（**US-025** multiprocessing 版 + **US-026 `on_process` 回调**：子进程 `start()` 后回调一次交出 `Process` 句柄供 WS stop/断开 terminate；density 双口径换算在主进程做；terminate 后 `cancel_join_thread + 限时 drain(≤50ms) + join(timeout=5)` 防死锁）+ `_apply_density_dual` 私有换算helper |
| `solve_worker.py` | 141 | US-025 **新增**。顶层 `solve_worker(pieces_snapshot, gate_mm, solve_params, result_queue)` —— Windows spawn 可 pickle（无闭包、参数全 JSON）。子进程内 `build_instance(...) → 投 {kind:manifest}` → `instance.solve(config, progress=ProgressQueue)` → drain 出中间解投 `{kind:frame,report}` → 末尾投 `{kind:final,final}` 或 `{kind:error,message}`。所有投递纯 JSON，spyrrow 对象绝不跨进程。延迟 import build_instance 避免主进程 `from solve_worker import` 时强制拉 sparrow_baseline |
| `export.py` | 614 | `apply_transform` / `placed_to_world`（用**原始**非 eroded 轮廓，pid 直查 intermediate 零重放；US-024 起 5 层一并变换，notch 点按点变换 + 法线按向量旋转；**US-002**：输出无 ptype 键、`color=label_color(label)`、`label_aci()` 取 ACI）/ `render_png`（matplotlib Agg；US-024 起 5 层叠加：net 绿虚线 / internal 橙 / notch 黄短线段 / grain 红虚线；**US-002**：图例条目 = placed 的 g 码并集按 `code_sort_key` 数值序，标题「裁片」，零中文名）/ `write_marker_dxf`（R12 POLYLINE + ACI 色 + ASCII 标题；**US-002**：ACI = `((code-1)%24)+1`，旧 `TYPE_ACI`/`TYPE_ORDER` 已删；US-024 起多 layer：outline layer1 / net layer14 / internal layer8 / notch layer4 POINT / grain layer7 LINE，各自独立 entity）/ `write_marker_plt`（US-033 HPGL/HP-GL 纯文本，**封装口径对齐生产 PLT** `data/PC-20250508NJIF*.plt`：头部 `IN;PS<纸长>;SP1;PW0.08;` + `SP1-5;` PU/PD + 尾部 `PU;PG;`，CRLF 行尾，无 VS/LB 指令；坐标=mm×40 round；5 层笔号 SP1=outline/SP2=net/SP3=internal/SP4=notch/SP5=grain + 门幅框并入 SP1；空层跳过；纯 ASCII bytes，无临时文件、无新依赖；**2026-08 现场撞机修正**：① 安全幅面 —— 内容按 y ≤ PLOT_SAFE_MAX_Y_MM 半平面裁剪（削平不缩放）、门幅框上沿压进可写幅宽（Y 内缩 PLOT_BORDER_MARGIN_Y_MM=5）、越界裁片记 warning（二道防线，兜旧 intermediate/求解 bug；求解已由 NEST_GATE_MM 一道钳制）；② PD 分块 —— `_plt_polyline` 单条 PD ≤10 点且整行 ≤110B 续画（对齐 ET 生产 ≤11点/≤118B，防国产 HP-GL 解释器行缓冲溢出坐标错位小车乱走）；③ 走纸引导 —— 全体 X + PLOT_LEAD_X_MM=20（贴 0 起画无定位余量），PS 纸长 = 引导 + max(用布长, 内容最大X) + 尾余量 PLOT_TAIL_X_MM=10）/ `_plt_frame_stats`（越界防御 + PS 纸长取值：全层顶点 + notch 点须在门幅框内，非 0 记 warning；notch 法线端点外伸只计入 max_x 不告警） |

US-004 起 `web/server.py` 直接 import `dxf_parser.collect.collect_pieces_with_details`（web → dxf_parser 跨层依赖，合规：web 是上层）。US-010 起新增 import `dxf_parser.explore` / `dxf_parser.export_dxf` / `nesting_bounds.load_pieces`（web → nesting_bounds → dxf_parser 单向，合规）。上传 multipart 依赖 `python-multipart`（已在 `[web]` extra）。

## cli/ — 配置驱动求解 CLI（PRD config-driven-solve-cli，US-001 起）

最上层编排者（`cli → web → nesting_engine → nesting_bounds → dxf_parser`）：读 `data/configs/` 下 7 键 JSON 配置跑「parse → commit → solve」全管线，**绝不 import `web.server`**（可 import `web.solver` 等纯求解封装）；产物只落 `out/config_runs/<run_name>_<时间戳>/`，物理隔离 web 事实源（`out/sparrow_baseline/` 与 `out/uploads/` 零触碰）。

| 文件 | 职责 |
|------|------|
| `config.py` | US-001 `load_config(path)` 严格校验 7 键 schema（`master_dxf/sizes/gate_mm/time/seeds/per_type/quantities`）→ `NestRunConfig` frozen dataclass；`ConfigError(ValueError)` 中文报错含字段名（未知顶层键含旧 `seed`/`multi_seed`/`seed_count` → 提示已被 `seeds` 列表取代；`master_dxf` 相对路径 CWD→`paths.REPO_DIR` 两候选解析、失败列两个绝对路径；quantities 码号键须数字字符串或 `'null'`、数量须 JSON 数字 ≥0；per_type 键 `^g\d{1,3}$`、值仅 `d`/`tol` ≥0，超 `MAX_OVERLAP_MM=10`/`MAX_ROTATION_TOL_DEG=45` 不报错但 UserWarning 钳制提示）。**模块级 import 仅标准库**（paths/constraints 走函数内延迟 import 单一真相源），`python -m materialsorting.cli.config` 零副作用 |
| `pipeline.py` | US-002 `commit_from_config(cfg, run_dir)` 独立 commit 管线：镜像 `web/server._commit_to_nesting_sync` 同一编排链（`collect_pieces_with_details` → `assign_codes` → `write_piece_dxf` 切 `{label}_{size}.dxf` + `pieces_manifest.json` 到 `run_dir/pieces/` → `load_nest_pieces` → intermediate 落 `run_dir/pieces_intermediate.json`，schema v2 与 web `web.solver.load_pieces` 互读）。**与 web commit 的刻意差异**：不写 `.bak`（时间戳 run_dir 天然全新）、顶层省略 `label_representatives`（web 专属缩略图）、`gate_mm` 写 `cfg.gate_mm`（配置驱动 = 该 run 密度分母；web 固定 `GATE_MM=1980`）；piece 条目经 `_piece_record` 与 server 逐字段一致（含 rounding 位数：点 3 位/法线 4 位/bbox 2 位/area 1 位）—— server schema 变更须同步镜像（web 零改动约束下无法抽共享函数）。`new_run_dir(run_name)` 创建 `CONFIG_RUNS_DIR/<name>_<YYYYMMDD-HHMMSS>` 时间戳目录（保留历史互不覆盖；run_name 清洗归 `run_config`）。commit 只消费 `cfg.master_dxf`/`cfg.gate_mm`（sizes/quantities/per_type 是求解期参数，commit 不过滤全量切片） |

## 数据流主线

```
用户上传母版 DXF
  │ collect.collect_pieces_with_details（5 层 IR）
  ▼ /api/parse-dxf（预览）→ /api/commit-to-nesting
out/uploads/<doc_id>_pieces/{label}_{size}.dxf（如 g03_28.dxf；每片 layer1+14+8+4+7 五层，由 write_piece_dxf 切出）
  │ load_pieces.load_nest_pieces（pieces_manifest.json 驱动；_read_piece 读 5 层 + notch 法线按最近边重算 + _apply_layer_transforms 共享 transform 链 + 布纹对齐 + 归一化；US-001 v2 无镜像）
  ▼
NestPiece（母版全码，每片持 polygon + net_polygon + internal_lines + notches + grain_line 5 层）
  │ _commit_to_nesting_sync（labeling.assign_codes 最先赋 g 码，零丢片零合成，写 intermediate v2 + label_representatives）
  ▼
out/sparrow_baseline/pieces_intermediate.json   ← 全流程事实源（每片 5 层字段）
  │
  ├─ sparrow_baseline.main / sparrow_experiments.main（求解 → result/svg/curve；仅 polygon 参与 NFP，4 层忽略）
  └─ web（server 启动期 _PIECES_STATE 读取 + commit 后 reload + 可视化 + 导出 PNG/R12-DXF 5 层，US-020 + US-024）
```

逐跳函数链：

| hop | 函数（文件） | 输入 → 输出 |
|-----|------------|-----------|
| 母版 → IR 列表 | `explore.collect_pieces` | `Path` → `list[PieceOutline]`（layer1 毛版 + layer7 布纹线） |
| 母版 → 深度 IR 列表 | `collect.collect_pieces_with_details`（US-003） | `str\|Path` → `list[PieceOutline]`（layer1+7+14 净版+8 内部线+4 刀口，按 `LAYER_MAPPING`） |
| 上传母版 → 解析 JSON | `web/server.parse_dxf`（US-004） | `multipart file` → 落盘 `uploads/<uuid>.dxf` + `collect_pieces_with_details` → 按码分组 + `labeling.assign_codes` g 码赋号 JSON（`doc_id` 供 US-010 commit 引用） |
| 上传母版 → intermediate | `web/server.commit_to_nesting` + `_commit_to_nesting_sync`（US-010 Path A） | `{doc_id, filename?}` → `uploads/<doc_id>_pieces/` + `load_nest_pieces(pieces_dir)`（manifest 驱动） → 覆盖 `INTERMEDIATE`（先备份 `.bak`） |
| IR → 单裁片 DXF | `export_dxf.write_piece_dxf` | `PieceOutline` → `out/uploads/<doc_id>_pieces/{label}_{size}.dxf`（`_commit_to_nesting_sync` 调用） |
| IR → 探索产物 | `explore.write_outputs` | `list[PieceOutline]` → 分组目录 + CSV + 总览 SVG |
| 单裁片 DXF → NestPiece | `load_pieces.load_nest_pieces` | `uploads/<doc_id>_pieces/` → `list[NestPiece]`（manifest 驱动、零合成） |
| NestPiece → intermediate | `web/server._commit_to_nesting_sync`（US-010） | → `INTERMEDIATE`（`{source,gate_mm,n_pieces,total_area_mm2,pieces:[…]}`；写回前 `shutil.copy2(.json, .bak)`） |
| intermediate → baseline 解 | `sparrow_baseline.main` | → `result_{tag}_t{T}.json`/`svg`/`curve.json`/`curve.png` |
| intermediate → 实验解 | `sparrow_experiments.main` | → `result_exp_{tag}_t{T}_s{seed}.*` + 汇总 |

## 入口（`pyproject.toml` `[project.scripts]`）

| 命令 | 模块 | 作用 |
|------|------|------|
| `ms-explore` | `dxf_parser.explore:main` | 母版全裁片探索（分组 SVG/JSON + CSV + 总览） |
| `python -m materialsorting.dxf_parser.collect` | `dxf_parser.collect:main`（US-003） | 母版深度解析 CLI 冒烟（每码片数 + internal/notch/net 计数） |
| `ms-sparrow-baseline` | `nesting_engine.sparrow_baseline:main` | sparrow 基线求解（`{0,180}`，无 erode） |
| `ms-sparrow-exp` | `nesting_engine.sparrow_experiments:main` | 旋转/重合公差/组合实验 |
| `ms-web` | `web.server:main` | 可视化工作台（uvicorn :8000） |

也可 `python -m materialsorting.<sub>.<module>`。`spyrrow` 非 PyPI 主流包，装不上需手动处理；`[web]` extra 拉 `fastapi`/`uvicorn`/`matplotlib`/`python-multipart`（US-004 上传解析需要 multipart）。

## 关键不变量（改后端勿破坏）

1. **分层单向**：`web → engine → bounds → parser`，下层禁 import 上层。
2. **路径走 `paths.py`**：禁硬编码 `..` / 绝对路径。
3. **DXF 走 R12 + POLYLINE**（非 LWPOLYLINE）：ET2008 读 LWPOLYLINE 轮廓消失。单裁片与 marker 导出均如此。
4. **sparrow 不改源码**：作为 `spyrrow` pip 包引用，v0.3 约束在外层 `constraints.py` + `solver.build_instance` 包装实现。
5. **density 双口径**：`real_density = total_area/(width*gate)`（90% 生死线口径，导出为 `density`）；`density_sparrow`（erode 后 sparrow 自报，仅参考）。
6. **坐标系**：spyrrow X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上；前端 SVG `scale(1,-1)` 翻转后与 PNG / R12-DXF 一致。
7. **导出用原始轮廓非 eroded**：`_PIECES_STATE['pieces_by_id']`（US-020 替代旧 `PIECES_BY_ID`）持原始 polygon，`placed_to_world` 用它变换；eroded 仅用于求解/屏幕。
8. **`server.py` 启动期 `_reload_pieces_state()`**（US-020）：import 时读 intermediate 填 `_PIECES_STATE`；allow-empty 不再让 import 崩；commit 成功后立即 reload，前端无需重启 ms-web。`_state_lock=threading.Lock()` 保护 immutable snapshot 模式（整体替换 dict 内容）。
9. **5 层中 4 层仅渲染透传（US-024）**：`polygon`（layer1 毛版外轮廓，erode 后）是唯一参与 sparrow NFP 碰撞的几何；`net_polygon` / `internal_lines` / `notches` / `grain_line` 4 层仅渲染与 PNG/DXF/PLT 导出透传，不影响求解结果或利用率。改任一层定义需同步 collect.LAYER_MAPPING + export_dxf.write_piece_dxf + load_pieces._read_piece_full + web/server._commit_to_nesting_sync + solver.pid_meta + web/export.py + NestSVG。
10. **notch 法线读时重算（US-024）**：DXF POINT 仅存位置，无法线字段；`_read_piece_full` 读时调 `_collect._nearest_edge_with_normal` 按 outline 最近边重算（与 `collect._assign_notch` 同算法）。退化边（连续重复点）返 (0,0) 法线 → NestSVG / PNG 渲染为 0 长度线段兜底。
11. **求解进程化（US-025 + US-026 接线）**：`solve_with_callback_proc` 是 `solve_with_callback`（threading）的多进程替代 —— spyrrow Rust .pyd 无 cancel/abort/stop API，唯有 `Process.terminate()`（Windows 调 TerminateProcess）可可靠终止原生阻塞 solve；spyrrow 对象不可 pickle，故 `build_instance` 必须在子进程内执行（`solve_worker` 顶层函数 + 参数全 JSON 可序列化），只把 pid_meta/frame/final/error 经 `multiprocessing.Queue` 传回主进程。**US-026 已切换 `ws_solve`**：write loop 内联 + read loop 后台 task 双向并发；`on_process` 回调把 Process 句柄交给 ws_solve；stop/断开 → terminate+join 防孤儿。旧 `solve_with_callback` 保留不删。终止安全：`terminate() → cancel_join_thread() → 限时 drain(≤50ms) → join(timeout=5)`，绝不阻塞。
12. **门幅双口径解耦（2026-08-16 绘图仪撞机修正，1aedc10）**：`GATE_MM=1980` 是布幅**显示**口径（UI / 密度分母 / 导出外框 / WS manifest gate_mm），`PLOT_SAFE_MAX_Y_MM=1910` 是绘图仪 Y 可写幅宽，`NEST_GATE_MM=min(两者)` 是**求解约束带** —— 三常量单一事实源在 `nesting_bounds/load_pieces.py`，`web/solver.build_instance`、`sparrow_baseline.main`、`sparrow_experiments.run_one` 同源引用（1980−1910=70mm 内部差求解时直接不排，marker 顶部不再落进行程外撞导轨）。密度/理论用布仍按 gate 显示口径计算。PLT 导出内容再按 y≤1910 裁剪属二道防线（削平不缩放）。换机器/换布幅只改 nesting_bounds 一处常量，全部口径自动跟随。

## 已知问题（迁移中未修，勿在文档/迁移中扩大）

1. **`sparrow_baseline.py` 职责混合**：既是 CLI 入口又是共享层（导出 4 个 `_` 前缀私有名给 experiments），未拆 `engine_core.py`。
2. **跨 module 用 `_` 前缀名**：`sparrow_experiments` import `sparrow_baseline` 的 `_clean_polygon` 等 4 个下划线名，违反 Python 约定（应提为公共 API 或合并模块）。
3. **旋转公差未主动实施**：`constraints.MAX_ROTATION_TOL_DEG`（2026-08-17 起全局上限）仅作钳制上界，baseline solver 仍 `{0,180}`；多姿态搜索是后续利用率提升点。
4. **`sparrow_baseline.py:110-112` 占位死代码**：`<text>` 元素 append 后过滤，"占位，避免 linter"。
