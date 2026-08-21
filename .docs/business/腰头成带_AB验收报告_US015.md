# 腰头成带 A/B 验收报告（US-015：v1.1 填料混带）

> 2026-08-21。母版 5336#老六订单14%7%围加9_coded.dxf（真腰 g05，7 码 14 条；填料 g07，7 码 ×1）。验收器 `scripts/us015_band_ab.py`（复用 `materialSorting.web.band_accept` 探针套件：uploads 源 / P0 需求表 / 120s / seeds {0,1,2}，与 US-014 报告同口径）；报告数字全部引自 `out/config_runs/_probes/us015_ab_report.json`（ts 2026-08-21 23:07:07）。
>
> **结论：accept** —— 判据①混带 fill ≥ break-even 62.4% / ②全局密度均值劣化 ≤1.0pt / ③守恒（placed 计数 vs P0 demand + 无 WB_ 泄漏）全 PASS；浏览器终验 17/17 PASS。

## 0. 验收口径（同 US-014 三点差异声明 + 混带增量）

同 US-014 报告 §0：uploads 母版解析链（非生产 intermediate 快照）、web 默认 d=0.0、off 臂 = 同代码空带。增量：on 臂 `band = {enabled:true, label:'g05', ack:true, fillers:['g07']}` —— off/on 两臂唯一差异是 band 键；填料选择依据见 §4（g06 长条触发灾难守卫、g07 实测最优）。

## 1. 判据① 混带 fill ≥ break-even 62.4%（AC-b 前半）

| 指标 | 纯腰 v2（对照） | g05+g07 混带 |
|---|---|---|
| 带内 fill | 79.5%（1153×1271） | **86.52%**（1097.3×1333.0） |
| bbox 宽度变化 | — | **−55mm**（收窄，填料塞进肋间空隙而非扩带） |

**PASS**（86.52% ≥ 62.4%；三 seed stage_bbox 逐字节一致 —— 链构造 + `_fill_gaps` 无 RNG，带形态只依赖 seed 派生与几何，跨 seed 完全确定）。

## 2. 判据② 全局密度 A/B（接受线：均值劣化 ≤1.0pt，AC-b 后半）

| seed | off（无带） | on（混带） | 劣化 pt | 用布宽 |
|---|---|---|---|---|
| 0 | 85.704% | **87.766%** | **−2.062（提升）** | 7730.2 |
| 1 | 86.164% | **86.628%** | **−0.464（提升）** | 7831.7 |
| 2 | 87.856% | 86.933% | +0.923 | 7804.2 |
| **均值** | 86.575% | **87.109%** | **−0.534（提升）** | — |

**PASS**（均值 −0.534pt ≤ 1.0pt；三 seed 两升一降，最差 seed2 +0.92pt 亦在线内）。对比纯腰 v2（US-014 复测口径 +2.27pt 均值提升）：混带把带内 fill 从 79.5% 抬到 86.5% 后，全局仍保住均值提升 —— 填料副本从「主解散排」转为「带内塞隙」，是双赢而非搬运。

## 3. 判据③ 守恒 + 泄漏（AC-a：扣减后与 off 口径一致）

- **副本守恒**：三 seed `conservation_ok=true`（末帧 placed 计数 vs P0 需求表逐码对拍：g05=14 腰 + g07=7 填料，浏览器终验同数字）；
- **manifest 一致性**：`test_manifest_consistency_mixed_band_on_vs_off` —— 混带 on/off 的 total_area/pieces 列表逐字段一致（`exclude_labels={g05, g07}` 只跳 spyrrow Item 层，与 US-011 纯腰同一不变量扩到填料）；
- **无 WB_ 泄漏**：前端 WS 全消息 grep（2171 条消息 / 2168 帧）零命中；后端单测哨兵同口径。

## 4. 填料选择依据（g07，非 g06/g08）

- **g06**（711×30 长条）：单码混带 fill 44.4% < FILL_FLOOR_PCT=45 → `BandQualityError` 灾难守卫触发（预演 200 `{ok:false}` 如实回显，不阻塞改选）—— 长条填带内肋间空隙形态不成立；
- **g07**（216×67 中片）：**实测最优**（fill 86.52%、bbox 收窄 55mm）；
- **g08**：可混（多选上限 3 内），组合实测次优。
- 版师口径：无白名单约束（任意 g 码多选 ≤3、≠主码），UI 候选 = 腰头编号下拉同源缩略图列。

## 5. 浏览器终验（17/17 PASS，`scripts/us015_verify.mjs`）

链路：上传 5336 → QtyMatrix P0 需求表 → 高级配置成带 g05 + ack → 纯腰预演 79.5% → **填料多选 g07**（.on + aria-pressed、预演 86.5% == A/B on 臂 86.52%、body `{"enabled":true,"label":"g05","ack":true,"fillers":["g07"]}`）→ 满 3 置灰/反选恢复 → 确认求解 → stage「腰头成带中」→ 终值 **87.77% == A/B on 臂 seed0 87.766%**（同配置同 seed 确定性对拍）→ 末帧守恒 g05=14/g07=7 → 全消息无 WB_。截图：`us015_filler_multiselect.png` / `us015_mixed_band_stage.png` / `us015_mixed_band_final_seed0.png`。

## 6. 复现

```bash
# 后端 A/B（~25min：3 seed × (off 120s + on 120s)）
cd materialSorting-server && py -3.11 ../scripts/us015_band_ab.py --fillers g07 --seeds 0,1,2 --time 120

# 浏览器终验（需 ms-web :8000 + web build；截图落 .docs/business/）
node ../scripts/us015_verify.mjs

# 测试（全量零回归：后端 416 / 前端 684 + build）
py -3.11 -m pytest tests/ -q && cd ../materialSorting-web && npx vitest run && npm run build
```
