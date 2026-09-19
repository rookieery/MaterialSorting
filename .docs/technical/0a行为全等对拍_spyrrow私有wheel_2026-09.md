# 0a 行为全等对拍归档：PyPI spyrrow 0.9.0 ↔ 私有 wheel 0.9.0+ms0

- **日期**：2026-09-19
- **性质**：warm-start 一期 0a 阶段出口 gate（规格 §2.4）的 MS 侧执行记录；本仓 PRD [tasks/prd-warm-start-phase1.md](../../tasks/prd-warm-start-phase1.md) US-005 验收标准 1（前置 gate）的证据归档，spyrrow-ms 侧 US-003 据此关账（其台账 `.docs/technical/0a-exit-gate_2026-09.md` §5 同步）。
- **结论**：**PASS** —— 三跑 best 五字段全等 + 帧级语义轨迹逐帧全等（跨源亦全等，超出判据要求）；止损点维持「fork 立项成立」。

## 1. 判据（规格 §2.4-1）

1. 本地 wheel 不传 initial_solution，与 PyPI 0.9.0 同 seed 同短预算（5336 `--time 30 --seeds 0`）best density 一致；
2. 新 wheel 背靠背两次自身逐帧一致（帧级允许既有 num_workers=4 merge 序漂移口径）。

## 2. 环境

| 项 | 值 |
|----|----|
| 执行解释器 | `D:\code\MaterialSorting\.venv`（Python 3.11.6，与 8000 在线后端隔离——后端跑系统 Python 的 PyPI 0.9.0，.venv 级切换互不影响，无需停服务） |
| 对拍 wheel | `spyrrow-0.9.0+ms0-cp311-cp311-win_amd64.whl`（sha256 `0c8ac1a2…6b77d`，spyrrow-ms commit `1589839e`，sparrow rev `881cdcbd`，见 materialSorting-server/spyrrow_build.json） |
| 求解配置 | `data/configs/5336_coded_really.json`（7 码 [31,32,33,34,35,36,38]、gate 1980、真实 per_type 工艺参 d∈{0.4,2,5,10}、demand 2/1 混合）+ `--time 30` 覆盖，seeds [0] |
| 执行序列 | ms0 背靠背 A→B（中间零操作）→ 切 PyPI 0.9.0 跑 C 基线 → 切回 ms0（钉板态恢复，`spyrrow.__version__` 终态复核 = 0.9.0+ms0）；三跑同窗口连续执行（规避跨会话漂移 ±0.2~5pt 口径，不用历史 run_stats 当基线） |

## 3. 结果

| 指标 | A（ms0 ①） | B（ms0 ②背靠背） | C（PyPI 0.9.0 基线） |
|------|-----------|------------------|---------------------|
| best real_density | 0.880385 | 0.880385 | 0.880385 |
| best width_mm | 7433.8 | 7433.8 | 7433.8 |
| best placed 条数 | 119 | 119 | 119 |
| density_sparrow | 0.854823 | 0.854823 | 0.854823 |
| run_dir | `…/warm0a_ms0_a_20260919-094857` | `…/warm0a_ms0_b_20260919-094936` | `…/warm0a_pypi_20260919-095140` |

（run_dir 前缀 `materialSorting-server/out/config_runs/`）

**帧级**（curve_s0.json，各 152 帧；2026-09-16 帧发射层白名单口径，只含可行帧）：

- 语义轨迹（每帧 phase / density / width_mm 三元组序列）：**A==B==C 逐帧全等** —— 判据② PASS（且实测零 merge 漂移，未动用 num_workers=4 漂移豁免）；
- 跨源帧级（判据①只要求 best density）：亦逐帧全等，超出判据的强证据；
- best_frame_s0.json：frame_index 三跑均 150，`placed_items` 布局多重集（id+rotation+translation）**A==B==C 全等**；
- 唯一差异字段 = `elapsed`（wall-clock 计时，30.334 ↔ 30.337s），固有抖动非算法行为；**逐帧一致性判据必须按语义轨迹比对，逐字节哈希会因 elapsed 误报 FAIL**（本次实测证实）。

## 4. 裁决与后续

- 判据① PASS、判据② PASS ⇒ **0a gate 通过**，fork 立项维持；spyrrow-ms US-003 关账（2026-09-19）。
- 本仓 US-005 验收标准 1（前置 gate）直接引用本档结论，无需在 US-005 窗口重跑。
- .venv 终态 = 0.9.0+ms0（与钉板一致）；US-001 `warm_start_supported()` 采用 `+ms<N≥1>` 数值解析判定，ms0 纯重建态不会误报 warm 支持。
