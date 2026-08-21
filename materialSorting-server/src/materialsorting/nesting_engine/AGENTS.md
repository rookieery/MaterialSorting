# nesting_engine — Agent 速查

> sparrow 求解封装层。可 import `nesting_bounds` + `dxf_parser` + `paths`；**禁 import `web`**（上层）。`sparrow` 作为 pip 包（`spyrrow`）引用，不改源码。
> 改前先看 `.docs/technical/agent-file-map.md` 的 `nesting_engine/` 章节。

## 启动 / 校验

```bash
python -c "from materialsorting.nesting_engine import labeling, constraints, sparrow_baseline, waist_band, waist_band_gate"
```

## 文件分工

| 文件 | 角色 |
| --- | --- |
| `constraints.py` | 重合/旋转**全局**上限（2026-08-17 起：`MAX_OVERLAP_MM=10.0` / `MAX_ROTATION_TOL_DEG=45.0`，每片型钳制表已删，版师按片型的工艺参考值在 `.docs/business/排料规则_详细版.md` §3.2/§4）+ 旋转公差离散化 `discretize_orientations`（**US-009 起**自 `web/solver.py` 移入真相源 —— 本包 `waist_band` 同口径消费但分层禁 import web；solver re-export 旧路径零改动）+ 位图腐蚀 + 合法性校验（US-002 起 `PAIR_TYPES` 与成对齐套校验已删 —— 服务于已删除的合成镜像模型） |
| `sparrow_baseline.py` | 基线求解 CLI + ★共享层（`SIZE_PALETTE`/`size_color`（2026-08-20 起**尺码** → 16 色循环表单一真相源，锚点 `SIZE_ANCHOR=DEFAULT_SIZES[0]=28` 稳定绝对映射、同码同色跨片型；US-002~2026-08-19 为 g 码键 `label_color`，更早 `PTYPE_COLORS` US-002 已删）/ `_clean_polygon` / `_transform_polygon` / `solve_with_progress`，被 experiments/export/solver/waist_band 复用；SVG 图例按尺码数值序、标题「尺码」） |
| `sparrow_experiments.py` | 旋转/重合公差实验 CLI（US-002 起 `INTERNAL_TYPES` 已删，内片集合改 `--internal g04,g07` 命令行参数显式给出）；`erode_polygon` 被 solver/waist_band 复用 |
| `labeling.py` | 裁片 g 码编号**单一真相源**（US-001 v2：label 先行、名称无关）：`label_for(idx)` / `code_sort_key(code)` / `master_code_from_block_name(name)` / `centroid` / `size_sort_key` / `parse_member_sort_key(p)`（码内成员稳定排序键）/ `sequential_sort_key(p)`（**T4：group_key 前置**，同一 block 模板跨码同号）/ `collect_master_codes(pieces)`（all-or-nothing，有效片=全部 size≠None）/ `assign_codes(pieces)`（签名无 gmap/group_names；`compute_size_ptype_labels` 已删除） |
| `waist_band.py` | **US-009 腰头成带核心**（依据 `.docs/business/腰头成带_落地方案.md` §2；**v2 2026-08-21 构造性链构造重写**替换 v1 spyrrow 带内子求解）：`build_band_plan(pid_meta, pieces_by_id, *, label, seed, ...)` —— 版师形态「**N 条单副本异码链**」（`chain_k`=每码第 k 副本一条链，链内 size **降序**）：`_chain_nest` 构造性滑移贴靠贪心（首片锚定原点，后续 rot{0,180}×5 y 对齐 × `_slide_touch` 右起 20mm 粗扫+40 次二分到贴触，取 union bbox 增长最小；shapely-only、无 RNG、毫秒级）→ `_flip_chain` 整链点对称翻转（成员 rot+180/tr 取负，合法布纹旋转无镜像）⇒ **开口朝左+最大码在最右**（用户建议1 定稿形态）→ 形态自检：`_chain_gap` ≤ `CHAIN_GAP_EPS_MM`=1.0（**贴触口径 = 版师验收**，非 bbox fill —— 新月片 bbox 空隙是构造性的）+ `_opening_side` ∈ {left,flat}（质心偏移反侧判据，已校准）+ 最大码质心 x 最大（程序断言自校验）→ `_stack_chains` 多链堆叠（**不翻链**保开口方向）+ 带高守卫 ≤ `min(gate_nest, PLOT_SAFE_MAX_Y_MM)`（链构造无 strip 约束，显式校验）→ 成员**原始轮廓** union → closing 焊接连通 → `erode(d_g)` → clean → 平移归一化，产 `BandChunk`（`WB_*` pid + offset + 逐副本成员带内位）；`expand_placements` 展开权威式（**offset 减号**，黄金单测锁死）；`band_seed_for=zlib.crc32` 派生（身份标识）；异常 `DegenerateBand`/`BandQualityError`（fill<45% 降为灾难形态守卫）。`time_budget`/`fill_floor`/`PAIR_ADJ_EPS_MM`/`DEFAULT_BAND_TIME_BUDGET_S` **deprecated 保留**（solve_worker/routes_band/band_accept import 兼容）。**禁 import web**（AST 守卫在 tests/test_waist_band.py）；真实 DXF 自交轮廓经 `buffer(0)` 修复（`_valid_geometry`）。v1 的 spyrrow StripPacking 求解 + US-014 成对重试（`_pairs_complete`/`_slot_fallback`/`BAND_MAX_TRIES`/`BAND_NUM_WORKERS`）已删 —— 根因：strip 目标是最短用布 X 而非贴触，产出 48.2% 对角阶梯坏带形反噬主解 -3.81pt；v2 实测（5336 g05）：6 码×1 单链 fill 71.8%（537×1326）**链内缝隙 0.00mm**、P0 14 副本 79.5%（1153×1271）、端到端 A/B **ON 88.35% vs OFF 86.08%（+2.27pt）**、同 seed 两跑 to_dict JSON 相等。**US-015（2026-08-21）v1.1 填料混带**：`fillers`（任意 g 码 ≤3、≠主码，护栏在 `routes_ws._parse_band`，本层兜底 0 副本/同主码 ValueError）全部副本在链堆叠后经 `_fill_gaps` 贪心塞带内空隙 —— 每副本 y 候选 = 已排 bbox 棱边 ∪ 各已放几何 bbox 棱边（对齐填料底/顶边）× rot{0,180} × 双滑向（`from_left` 到达朝左凹口），代价 = `_bbox_area`（bbox 并集解析式，免 unary_union）；`prep()` 预处理几何 bbox 预筛 + `FILLER_BISECT_ITERS=24` 降二分精度（g07+g08 填充 28s→4.9s）；混带下带内碰撞多边形补腐蚀到 `BAND_INNER_D_MM=2.0`（版师口径 2~4mm 保守端：肋间切口端部开到小件可入宽度；组合片外轮廓 erode 仍 d_g、**纯腰路径逐字节不变**）；`BandChunk.fillers` 进 to_dict（band_runs 工件回放）；5336 实测：g05+g07 混带 fill 79.5%→**86.5%**（bbox 1153→1097 收窄）、A/B 3 seed 均值劣化 **−0.534pt**（两 seed 改善）verdict=accept、浏览器终值对拍 87.77%==87.766% |
| `waist_band_gate.py` | **US-010 go/no-go 试点闸门**（决策实验，不改产品代码）：`python -m materialsorting.nesting_engine.waist_band_gate [--quick]` 三组实验 —— ① 密度 A/B（5336 P0 同配置 120s × seeds 0/1/2 band off vs on，接受线 = seed 均值劣化 ≤1.0pt）；② NFP 吞吐微基准（主实例 ± comb 组合片同预算帧率对比，劣化 >30% 判不过）；③ 带内 fill-预算曲线（{5,10,15,30,60}s 扫描 + 饱和点标注）。结论三选一 `decide()`：go / go-with-chunks（仅 NFP 挂）/ no-go（密度硬闸门挂 → 转 US-015 混填料）。**2026-08-21 实测结论 no-go**（A/B 劣化 1.204pt：seed2 off 90.0% 波动拖垮均值；NFP 劣化 35%；报告 `out/config_runs/_probes/band_gate_report.json`）。**禁 import web/cli**：`build_probe_pid_meta` 是 `web.solver.build_pid_meta` 的探针同构镜像（两 arm 共享 = 同源同构，AST 守卫在 tests/test_waist_band_gate.py）；**只读** intermediate、产物只落 `out/config_runs/_probes/` |

## labeling 关键约定（原 US-022 立；US-001 v2 起为 g 码单一真相源现行口径）

- **`labeling.py` 是 parse/commit 两处赋码的单一真相源**（US-001 v2）：`assign_codes(pieces)` 无 gmap/group_names 参数，「有效片」= 全部 `size≠None` 片（无名称映射判断、未录入名称不丢片）；顺序模式排序键 `sequential_sort_key = (group_key, -centroid_y, centroid_x, -area_mm2, block_name, piece_index)`（group_key 前置保证跨码同号）+ `label_for(idx)`（0→g01, 1→g02 ...）。
- **依赖方向合规**：本模块仅 import 标准库 + duck-typed PieceOutline 属性，不依赖任何兄弟包。`web/server.py` 可直接 import。
- **AC#5 对齐不变量（v2 简化）**：parse 与 commit 各自对同一母版跑 `assign_codes`（同 collect、同排序键、同母版码规则）→ 同一 `(block_name, size, piece_index)` 必得同 g 码，**不再经 (size, ptype) 中转**（M1787 验证 11 码 × g01..g10 逐片对齐）。
