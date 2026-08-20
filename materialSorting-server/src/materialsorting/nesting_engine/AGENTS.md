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
| `constraints.py` | 重合/旋转**全局**上限（2026-08-17 起：`MAX_OVERLAP_MM=10.0` / `MAX_ROTATION_TOL_DEG=45.0`，每片型钳制表已删，版师按片型的工艺参考值在 `.docs/business/排料规则_详细版.md` §3.2/§4）+ 位图腐蚀 + 合法性校验（US-002 起 `PAIR_TYPES` 与成对齐套校验已删 —— 服务于已删除的合成镜像模型） |
| `sparrow_baseline.py` | 基线求解 CLI + ★共享层（`SIZE_PALETTE`/`size_color`（2026-08-20 起**尺码** → 16 色循环表单一真相源，锚点 `SIZE_ANCHOR=DEFAULT_SIZES[0]=28` 稳定绝对映射、同码同色跨片型；US-002~2026-08-19 为 g 码键 `label_color`，更早 `PTYPE_COLORS` US-002 已删）/ `_clean_polygon` / `solve_with_progress`，被 experiments/export/solver 复用；SVG 图例按尺码数值序、标题「尺码」） |
| `sparrow_experiments.py` | 旋转/重合公差实验 CLI（US-002 起 `INTERNAL_TYPES` 已删，内片集合改 `--internal g04,g07` 命令行参数显式给出）；`erode_polygon` 被 solver 复用 |
| `labeling.py` | 裁片 g 码编号**单一真相源**（US-001 v2：label 先行、名称无关）：`label_for(idx)` / `code_sort_key(code)` / `master_code_from_block_name(name)` / `centroid` / `size_sort_key` / `parse_member_sort_key(p)`（码内成员稳定排序键）/ `sequential_sort_key(p)`（**T4：group_key 前置**，同一 block 模板跨码同号）/ `collect_master_codes(pieces)`（all-or-nothing，有效片=全部 size≠None）/ `assign_codes(pieces)`（签名无 gmap/group_names；`compute_size_ptype_labels` 已删除） |

## labeling 关键约定（原 US-022 立；US-001 v2 起为 g 码单一真相源现行口径）

- **`labeling.py` 是 parse/commit 两处赋码的单一真相源**（US-001 v2）：`assign_codes(pieces)` 无 gmap/group_names 参数，「有效片」= 全部 `size≠None` 片（无名称映射判断、未录入名称不丢片）；顺序模式排序键 `sequential_sort_key = (group_key, -centroid_y, centroid_x, -area_mm2, block_name, piece_index)`（group_key 前置保证跨码同号）+ `label_for(idx)`（0→g01, 1→g02 ...）。
- **依赖方向合规**：本模块仅 import 标准库 + duck-typed PieceOutline 属性，不依赖任何兄弟包。`web/server.py` 可直接 import。
- **AC#5 对齐不变量（v2 简化）**：parse 与 commit 各自对同一母版跑 `assign_codes`（同 collect、同排序键、同母版码规则）→ 同一 `(block_name, size, piece_index)` 必得同 g 码，**不再经 (size, ptype) 中转**（M1787 验证 11 码 × g01..g10 逐片对齐）。
