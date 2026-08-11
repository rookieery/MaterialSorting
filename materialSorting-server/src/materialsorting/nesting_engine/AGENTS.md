# nesting_engine — Agent 速查

> sparrow 求解封装层。可 import `nesting_bounds` + `dxf_parser` + `paths`；**禁 import `web`**（上层）。`sparrow` 作为 pip 包（`spyrrow`）引用，不改源码。
> 改前先看 `.docs/technical/agent-file-map.md` 的 `nesting_engine/` 章节。

## 启动 / 校验

```bash
python -c "from materialsorting.nesting_engine import pieces_export, labeling, constraints, sparrow_baseline"
python -m materialsorting.nesting_engine.pieces_export    # 生成 intermediate JSON（排料前必跑）
```

## 文件分工

| 文件 | 角色 |
| --- | --- |
| `constraints.py` | v0.3 约束常量（`MAX_OVERLAP` / `ROTATION_TOL` / `INTERNAL_TYPES`）+ 位图腐蚀 + 合法性校验 |
| `sparrow_baseline.py` | 基线求解 CLI + ★共享层（`PTYPE_COLORS` / `_clean_polygon` / `solve_with_progress`，被 experiments/export/solver 复用） |
| `sparrow_experiments.py` | 旋转/重合公差实验 CLI；`erode_polygon` + `INTERNAL_TYPES` 被 solver 复用 |
| `labeling.py` | US-022 共享 A/B/C 标注：`label_for(idx)` / `centroid(poly)` / `size_sort_key(size)` / `compute_size_ptype_labels(pieces, gmap, group_names)` |
| `pieces_export.py` | NestPiece → `pieces_intermediate.json`（事实源）；US-022 起解析母版标 label；US-024 起每片加 `net_polygon`/`internal_lines`/`notches`/`grain_line` 4 字段（与 NestPiece 同名透传，旧 intermediate 无字段时 `.get()` 默认空/None 向后兼容） |

## US-022 关键约定（labeling）

- **`labeling.py` 是 parse/commit/pieces_export 三处标注的单一真相源**：排序键 `(-centroid_y, centroid_x, -area_mm2, block_name, piece_index)` + `label_for(idx)`（0→A, 1→B ...）。
- **依赖方向合规**：本模块仅 import 标准库 + duck-typed PieceOutline 属性，不依赖任何兄弟包。`web/server.py` 与本层 `pieces_export.py` 均可 import。
- **label 对齐不变量**：`compute_size_ptype_labels` 对 `explore.collect_pieces` 原始 pieces 排序标注 → `{(size, ptype): label}`，L/R 同 ptype 共享 label。M1787 验证 10/10 ptype 按 (size, ptype) 与 parse 响应对齐。
- **pieces_export baseline 路径**：`paths.MASTER_DXF_GLOB` 母版缺失时 label=null（向后兼容；build_instance 回退 demand=1）。
