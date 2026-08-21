# 腰头成带 A/B 验收报告（US-014）

> 2026-08-21。母版 5336#老六订单14%7%围加9_coded.dxf（真腰 g05，7 码 14 条）。验收器 `materialSorting.web.band_accept`（`run_all`）单命令跑完全部四判据并落盘报告 `out/config_runs/_probes/band_accept_report.json`；本报告数字全部引自该 JSON（generated_at 2026-08-21T15:05:24）。
>
> **结论：accept** —— 判据①密度 / ②形态 / ③确定性 / ④导出 全 PASS。

## 0. 验收口径（与生产基线的三点差异声明）

| # | 差异 | 原因 |
|---|---|---|
| 1 | **源**：uploads 母版解析链（`/api/parse-dxf` → commit 切单）而非生产 0.9063 用的 intermediate 快照 | US-011 起带内求解依赖 per-label 几何与 quantities 链路，验收走「上传→排料」完整真实路径（浏览器终验同源） |
| 2 | **间隙口径**：web 默认 d=0.0（P0 表全 0），生产 0.9063 跑的是 d=0.4/tol=3° per_type | 同源同构 A/B 对照（off 臂与 on 臂同参数），结论只看**差值**不看绝对值；0.9063 基线不同构（间隙+帧前展开前口径），不直接可比 |
| 3 | **对照臂**：band off（同代码 `exclude_labels` 空置）而非「git checkout HEAD~ 无 band 代码」 | off 臂就是 HEAD 主路径加空带 —— 带代码存在但未激活，等价于无带行为（US-011 契约：无 band 键时管线逐字节不变） |

两臂共同配置：sizes 31/32/33/34/35/36/38（P0 表），quantities 31→1、36→3、其余双份 g 码整列 2，main 120s，band 15s，seed ∈ {0,1,2}，d_ext=d_int=tol_ext=tol_int=0.0。

## 1. 判据① 密度 A/B（接受线：劣化 ≤1.0pt）

| seed | off（无带） | on（成带） | 劣化 pt | 带内填充 | 带组合片 bbox | 带耗时 |
|---|---|---|---|---|---|---|
| 0 | 85.69% (w 7917.5) | **87.531%** (w 7750.9) | **−1.842（提升）** | 63.67% | 1208×1515mm | 2.54s |
| 1 | 86.16% (w 7874.3) | **86.868%** (w 7810.1) | **−0.708（提升）** | 65.64% | 1183×1500mm | 3.11s |
| 2 | 87.86% (w 7722.2) | 87.148% (w 7785.0) | +0.708 | 66.84% | 1178×1479mm | 8.06s |
| **均值** | 86.57% | **87.18%** | **−0.614** | 65.4% | — | — |

**PASS**。三 seed 两升一降，均值反而提升 0.61pt（形态约束没有吃掉密度：有机紧排解 + 组合片进入主解后作为整片参与 NFP，主解获得了重新安排其余 105 片的自由度）。最差 seed2 +0.71pt 亦在 1.0pt 线内。这与《腰头成带_落地方案》§0 的预期一致：不承诺提升，只守「不显著劣化」——实测超预期。

## 2. 判据② 形态（成对相邻率 = 100% + span 有界 + 目测）

**判据口径（边距，非中心距）**：`pair_adjacency` 用 shapely `Polygon.distance` ≤ `PAIR_ADJ_EPS_MM=10mm`（单一真相源 `waist_band.PAIR_ADJ_EPS_MM`）。PRD「中心距 ≤ (w_i+w_j)/2+ε」只是轴对齐并排特例：FR-8 朝向集 {0°,180°} 下合法成对形态是**头尾翻转相接**（实测 g05_34 对：物理边距 1.5mm、中心距 713mm）——中心距口径会把 100% 合法解误判为散落，故以边距为权威、中心距仅作对照字段。容差 10mm 与 spyrrow 紧排实际缝隙（0.01~10mm）同量级。

| seed | 成对率（on 臂） | 最差边距 | 对照：off 臂同码成对率 | 带 span | span 判定 |
|---|---|---|---|---|---|
| 0 | **100%**（13/13 多副本） | 0.76mm | 15.38% | 1208×1515mm，14 条全在内 | OK |
| 1 | **100%**（13/13） | 0.26mm | 30.77% | 1183×1500mm | OK |
| 2 | **100%**（13/13） | 0.2mm | 38.46% | 1178×1479mm | OK |

13 = 14 条减去 demand=1 的 31 码（无成对义务）。off 臂对照证明成对**不是**自然涌现（15~38%）：形态收益完全来自成带机制。目测证据：

- `us014_band_stage.png` —— 前端 stage「腰头成带中」（带内预演完成、主解未开始的中间态）
- `us014_band_final_seed0.png` —— seed0 终局全图：14 条腰头聚成右侧一簇两两相贴，与主料分离
- `us014_band_export_on_seed0.png` —— on 臂导出 PNG（同一布局的出图口径）

**达成机制的修订**（否决了一个方案）：spyrrow 不按喂入序聚排，「输入 size-major 序 ⇒ 同码相邻」假设被实测否定（2/3 seed 同码对散落 400mm+）。US-014 定稿为**成对形态重试选解**：固定派生 seed 序列（`crc32(band_seed|try{k})`）重试 ≤6 次取首个「同码全成对」解（实测出现率 ~50%/次，全败概率 ~1.6%），6 败走确定性槽位兜底 `_slot_fallback`。曾试「分码分块拼接」：成对率也 100%，但宽 1818×1271 的块状组合片主解难包，均值密度劣化 3.75pt —— **形态与密度需同时达标**，已否决（详见 web/AGENTS.md US-014 节）。

## 3. 判据③ 确定性（同 seed 重跑对拍）

seed0 on 臂重跑三件套：**frames_equal / final_equal / artifact_replay_equal 全 True**（本次两跑帧数恰同为 2008 帧逐帧相等；final 密度/宽/placements 逐字段相等；`band_runs/band_g05_seed0_*.json` 工件重放逐字节相等，band_elapsed 除外——墙钟字段不入判据）。

帧列比较规则为「核心轨迹 + 尾帧容差」：主解按 wall-clock 预算截断，机器负载可让截止快照漂移 1~3 帧（US-014 实测 2005 vs 2008、1167 vs 1166 两种形态，均为前 min(n)−1 帧全等、final 相等、分歧只在短列末帧）。`frame_series_equal` 判定 = 核心前缀逐帧相等 + 帧数差 ≤ `FRAME_TAIL_TOLERANCE=8`；核心帧分歧或大面积漂移即 FAIL（单测 `test_frame_series_equal_tail_cutoff_rule` 三态锁死）。浏览器终验交叉印证：UI 同配置同 seed 出 87.51%，与 A/B on 臂 seed0 87.531% 差 0.021pt ≤ 0.05pt 对拍线。

## 4. 判据④ 导出（三格式 + WB_ 泄漏哨兵）

| 臂 | PNG | DXF（R12 POLYLINE） | PLT | WB_ 泄漏 |
|---|---|---|---|---|
| on | 805,761B | 2,376,310B | 396,111B | 无（placed/DXF/PLT 字节三重 grep 空） |
| off | 788,908B | 2,378,530B | 399,307B | 无 |

`WB_` 组合片 PID 永不出 worker 进程（`solve_worker._emit_placed` 单点展开，US-011 架构），验收器对导出产物做字节级三重哨兵。浏览器链路另验证：UI 导出三格式经真实 HTTP `/export` 下载成功（`out/us014_verify/ui_export_seed0.{png,dxf,plt}`），前端 WS 全部 1987 条消息 grep `WB_` 零命中，**服务端日志「导出跳过：pid」零出现**（band-off 与带代码路径导出一致性）。

## 5. 复现

```bash
# 后端验收器（~16min：3 seed × (off 120s + on 120s) + 重跑 120s + 导出）
cd materialSorting-server && ../.venv/Scripts/python.exe -m materialsorting.web.band_accept
# 浏览器终验（需 ms-web :8000 + web build；截图落 .docs/business/）
node scripts/us014_verify.mjs
# 测试
cd materialSorting-server && ../.venv/Scripts/python.exe -m pytest -q   # 395 passed
```

工件：`out/config_runs/_probes/band_accept_report.json`（机器可读全量）、`band_accept_export_{on,off}_seed0.*`、`out/band_runs/band_g05_seed*.json`（可重放）。
