# nesting_engine — Agent 速查

> sparrow 求解封装层。可 import `nesting_bounds` + `dxf_parser` + `paths`；**禁 import `web`**（上层）。`sparrow` 作为 pip 包（`spyrrow`）引用，不改源码。
> 改前先看 `.docs/technical/agent-file-map.md` 的 `nesting_engine/` 章节。

## 启动 / 校验

```bash
python -c "from materialsorting.nesting_engine import labeling, constraints, sparrow_baseline"
```

## 文件分工

| 文件 | 角色 |
| --- | --- |
| `constraints.py` | 重合/旋转**全局**上限（2026-08-17 起：`MAX_OVERLAP_MM=10.0` / `MAX_ROTATION_TOL_DEG=45.0`，每片型钳制表已删，版师 per-ptype 参考值在 `.docs/business/排料规则_详细版.md` §3.2/§4）+ `PAIR_TYPES` + 位图腐蚀 + 合法性校验 |
| `sparrow_baseline.py` | 基线求解 CLI + ★共享层（`PTYPE_COLORS` / `_clean_polygon` / `solve_with_progress`，被 experiments/export/solver 复用） |
| `sparrow_experiments.py` | 旋转/重合公差实验 CLI；`erode_polygon` + `INTERNAL_TYPES` 被 solver 复用 |
| `labeling.py` | US-022 共享 A/B/C 标注：`label_for(idx)` / `centroid(poly)` / `size_sort_key(size)` / `parse_member_sort_key(p)`（码内排序键单一真相源，2026-08-17 起 parse 赋号 / intermediate 标注 / web ptype 代表裁片三处共用）/ `compute_size_ptype_labels(pieces, gmap, group_names)` |

## US-022 关键约定（labeling）

- **`labeling.py` 是 parse/commit 两处标注的单一真相源**：排序键 `(-centroid_y, centroid_x, -area_mm2, block_name, piece_index)` + `label_for(idx)`（0→A, 1→B ...）。
- **依赖方向合规**：本模块仅 import 标准库 + duck-typed PieceOutline 属性，不依赖任何兄弟包。`web/server.py` 可直接 import。
- **label 对齐不变量**：`compute_size_ptype_labels` 对 `explore.collect_pieces` 原始 pieces 排序标注 → `{(size, ptype): label}`，L/R 同 ptype 共享 label。M1787 验证 10/10 ptype 按 (size, ptype) 与 parse 响应对齐。
