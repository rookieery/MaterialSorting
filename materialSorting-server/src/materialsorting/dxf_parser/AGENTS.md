# dxf_parser — Agent 速查

> 底层 DXF 读写包。仅 stdlib + ezdxf，**禁 import 兄弟包**（nesting_bounds / nesting_engine / web）。`paths` 是包级共享模块（`from .. import paths`），不算兄弟包。
> 改前先看 `.docs/technical/agent-file-map.md` 的 `dxf_parser/` 章节。

## 启动 / 校验

```bash
python -c "from materialsorting.dxf_parser import collect, explore, reader, geometry, model, export_dxf"
python -m materialsorting.dxf_parser.collect    "../data/M1787#....dxf"      # US-003 深度解析 CLI 冒烟
python -m materialsorting.dxf_parser.explore    --dxf "../data/M1787#....dxf"  # 母版探索
```

## 文件分工

| 文件 | 角色 |
| --- | --- |
| `reader.py` | ezdxf recover + GBK 块名解码 + R12 POLYLINE 读取 + `iter_block_entities(block, layers)` US-002 layer 白名单工具 |
| `geometry.py` | 纯几何算子（无 ezdxf，可单测）：周长 / 面积 / bbox / point_in_polygon / match_grain |
| `model.py` | `PieceOutline` dataclass（解析期唯一 IR；US-002 扩 `internal_lines`/`notches`/`net_polygon` 默认空 list 向后兼容） |
| `explore.py` | 母版全裁片探索 CLI：`collect_pieces(path) → list[PieceOutline]`（layer1 毛版 + layer7 布纹线）+ SVG/CSV/JSON 输出 |
| `collect.py` | **US-003 母版深度解析**：`collect_pieces_with_details(path)` 还原 layer14 净版 + layer8 内部线 + layer4 刀口 + layer7 布纹线 |
| `export_dxf.py` | `PieceOutline` → 单裁片 R12 DXF（**5 层**：layer1 毛版 + layer14 净版 + layer8 内部线 + layer4 刺口 POINT + layer7 布纹线；US-024 起用 `collect_pieces_with_details` 拿全 5 层 IR；ET2008 兼容）。US-001 起 `GROUP_NAMES` / `assign_group_no` **已删除**（名称识别整体退场），文件名 `{label}_{size}.dxf` 的 g 码由调用方（`web/server.py` 经 `labeling.assign_codes`）决定，本模块零名称逻辑 |

## layer 映射（`collect.py:LAYER_MAPPING`，版师 2026-08-10 确认；5156 与 M1787 一致）

| 语义 | layer id | 实体 | PieceOutline 字段 |
| --- | --- | --- | --- |
| 毛版 outline | `"1"` | POLYLINE | `polygon_mm` |
| 净版 net | `"14"` | POLYLINE | `net_polygon` `[(x,y), ...]` |
| 内部线 internal | `"8"` | POLYLINE | `internal_lines` `[[(x,y), ...], ...]` |
| 布纹线 grain | `"7"` | LINE | `grain_line` `(x1,y1,x2,y2)` |
| 刀口 notch | `"4"` | POINT | `notches` `[(x,y,nx,ny), ...]`（点 + 单位外法线） |

**不提取**：layer 2/3/13（参考点 / 轮廓密点 / 未定语义，**非刀口**；版师 2026-08-10 确认）。

## US-003 关键约定（collect_pieces_with_details 调用方必读）

- **复用 explore.collect_pieces**：layer1 毛版外轮廓 + layer7 布纹线（`match_grain` 中点配对）。`collect_pieces_with_details` 返回顺序与 `collect_pieces` 一致，新字段写回原 `PieceOutline` 实例（不创建新对象，旧调用方零改动）。
- **layer14 净版归属**：质心 `point_in_polygon` 命中即归属；**1:1**（实测 M1787/5156 都是 110 outline = 110 net），每片最多 1 条净版，多条时取首条。`net_polygon` 字段是 `[(x,y), ...]` 平铺顶点列表（无则空 list）。
- **layer8 内部线归属**：质心命中归属；多线/片（M1787=286 / 5156=297 分布在 110 outline 上）。
- **layer4 刀口归属两步走**：
  1. **Pass 1 严格 point_in_polygon**：545/704 命中（M1787/5156 一致）。
  2. **Pass 2 最近边兜底**：剩余 159/704 是边界 / 外贴边点（`point_in_polygon` 严格返回 False，但最近边距离=0），取所有 outline 中最近边所属片。
- **法线方向**：CCW 多边形（`_signed_area > 0`）外法线 = `(dy, -dx)/len`；CW 取反。退化边（零长度）返回 `(0, 0)` 法线。渲染时画 8mm 短线段（长度待版师确认）。
- **刀口存储 `[(x, y, nx, ny)]`**：`(x, y)` 是原始 POINT 坐标，`(nx, ny)` 是所属 outline 最近边的**单位外法线**；前端 `PiecePreviewSVG`（US-007）从 `(x, y)` 沿 `(nx, ny)` 画定长线段。
- **不进 intermediate**：`net_polygon` / `internal_lines` / `notches` 仅服务预览（US-007 `PiecePreviewSVG`）；`nesting_bounds.load_pieces` 只读 layer1 毛版 polygon（US-010 Path A 转换时这些细节丢弃）。**US-024 起此条作废**：`_read_piece_full` 读 5 层 + notch 法线按 outline 最近边重算，与 polygon 共享 transform 链后透传到 intermediate / manifest / NestSVG / 导出 PNG+R12-DXF；4 层仅渲染/导出透传，仍不参与 sparrow NFP 碰撞（求解仅用 polygon）。

## 已踩坑 / 注意事项

- **R12 POLYLINE 顶点在 `e.vertices`**（不是 LWPOLYLINE 的 `.vertices` 属性）—— `reader.polyline_points` 已封装；新增提取代码统一走它，不要直接读 LWPOLYLINE。
- **ezdxf recover 读 R12 母版** 必须用 `reader.load_doc` 解 `(doc, errors)` 元组；直接 `ezdxf.readfile` 在损坏文件会抛。
- **块名 GBK 解码**：母版 `$DWGCODEPAGE` 标 ANSI_1252 但实际 GBK，`reader.decode_str` 走 `latin-1 → gbk`；新增代码处理 block 名一律先 `decode_str`。
- **码号正则 `[._](\d+)$`**（`reader._SIZE_RE`）：M1787 块名 `noname..28` 命中（`.` 前缀）；5156 块名 `腰-28` 用 `-` 前缀**不命中**，size 解析返回 None。这是 `collect_pieces` 既有行为，US-003 不修——AC 要求「片数与 `collect_pieces` 一致」而非码号解析成功。
- **`paths` 是包级 module 不是兄弟包**：`from .. import paths` 合规；US-003 `collect.py` 进一步解耦为 path 参数（不依赖 `paths`），便于 US-004 web 层调用。
- **layer id 字符串比较**：与 `collect_pieces` 同口径用 `str(e.dxf.layer) == "1"`（不是 int）。`iter_block_entities` 已封装 set 白名单。
