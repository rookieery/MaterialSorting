# 极限运行 A/B 验收报告（US-004）

> 2026-08-29 启动，2026-08-30 终稿。母版 5336 生产口径（`data/configs/5336_coded_really.json`：119 片、门幅 1980mm、sizes 31–38）。离线回放验收器 `scripts/extreme_ab_replay.py`（数字引自 `materialSorting-server/out/config_runs/_probes/extreme_ab_replay.json`，generated_at 2026-08-29T17:43:51）；三臂端到端真跑为 CLI 实跑，数字引自各 run_dir 的 `result.json` / `strategy.json` / `kill_decisions.jsonl`。密度一律 **real_density（原面积口径）**。
>
> **结论：accept** —— 判据「extreme 臂 best ≥ race 臂 best」通过：**91.7107% ≥ 91.3114%（+0.40pt）**（§1）；离线回放佐证见 §2；split24（91.8177%）为三臂最高，但与 extreme 统计打平、增益归因见 §1.1。

## 0. 验收口径声明

| # | 事项 | 口径 |
|---|---|---|
| 1 | 三臂定义 | **extreme** = `--extreme`（展开为 race 门杀 × budget 600s × gate τ=0.5 × p070/et0/nw4）；**race_default** = `--strategy race`（budget 180s、gate τ=0.5、缺省 solver opts p080/et1）；**split24** = 等分均拆（`us004_split24_5336.json`：time=600、seeds=0..23、无门杀、缺省 opts）|
| 2 | 总预算 | 三臂同为 T=14400s（4h）名义求解预算；race 门杀名义记账 `race_plan`（182.5/92.5s 每轮）、extreme（602.5/302.5s 每轮）|
| 3 | **串行执行** | 三臂必须串行真跑。并行试跑已被否决：3 臂并行时 solver 帧数 −8%、确定性 seed0 密度 −0.52pt（墙钟预算被 CPU 争用截断），实测记录见 §5.2 |
| 4 | 回放口径 | 无放回 bootstrap（置换式，池耗尽重洗）对齐《极限运行功能方案_race门杀》§2.5 E[max] 表；**右尾受池上界约束**（25 池最大 91.774pt，不外推）|
| 5 | 池与真跑参数差异 | 主表回放用 p070/et0 池（25 seed、600s、离线曲线）；副表用 p080/et1 池（5 seed）。真跑 race/split 臂走缺省 opts（p080/et1），extreme 臂 p070/et0 —— 回放表按「同策略机制 + 同池」呈现，跨参数比较只看差值方向 |

## 1. 三臂端到端真跑（4h）

| 臂 | 命令 | 轮数（seed 流） | 门杀 | 墙钟 | best real_density | best seed |
|---|---|---|---|---|---|---|
| race_default | `ms-run-config 5336_coded_really.json --strategy race --time 14400` | 147（0..146） | 139 杀 / 7 活 {0,1,2,3,16,27,61} | 17:46:58→21:38:12（3h51m14s） | **91.3114%**（w 7167.3mm） | 61（frame 2652，176.9s） |
| extreme | `ms-run-config 5336_coded_really.json --extreme --time 14400` | 42（0..41） | 37 杀 / 5 活 {0,1,3,4,23} | 21:38:15→01:34:14（3h55m59s） | **91.7107%**（w 7136.1mm） | 23（frame 2311，597.4s） |
| split24 | `ms-run-config us004_split24_5336.json`（time=600×24） | 24（0..23） | 无门杀 | 01:34:14→04:32:36（2h58m22s，et 提前收敛，求解净 10692s） | **91.8177%**（w 7127.8mm） | 23（frame 2336，593.4s） |

**判定（extreme ≥ race）：通过 —— 91.7107% ≥ 91.3114%（+0.40pt）。**

race_default 真跑注释：门杀 139/146（95.2%），单轮墙钟均值 94.1s（被杀 ~92.5s、存活 ~182.5s），与 `race_plan` 名义记账吻合；存活 7 seed 中 4 个进 top5（61→91.31、27→91.12、16→91.07、94→90.93 被杀轮内帧），门杀机制把预算集中在正确 seed 上。

### 1.1 split24 反超 extreme（+0.11pt）归因

- **统计打平**：回放主表 E[best] extreme 91.774 vs split24 91.763（+0.011pt，20000 次 bootstrap）；真跑 split 高 0.107pt，落在 §3 实测的跨会话 seed 级波动带内（常态 ±0.2pt、尾部 ±2pt+），单次真跑不足以分辨两者优劣。
- **+0.40pt 的真实来源是 600s 长 budget**：race_default 短板在 180s 单 seed 上尾不足（§2），extreme/split24 同为 600s 档就同时越过它——增益来自 budget，不来自门杀。
- **门杀本轮未兑现增量**：门杀的价值 = 同预算多探索 seed（42 轮 vs 24 轮），仅当高分 seed 出现在第 24 名之后才兑现；本轮两臂 best 恰都出自 seed 23，extreme 多跑的 18 个 seed（24..41）无一人超过 incumbent。
- **split 臂还省了预算**：early_termination 缺省开，部分 seed 提前收敛（单轮最短 263s），求解净 10692s / 名义 14400s（74%），墙钟 2h58m，仍拿三臂最高——4h 总预算下 600s/seed 档已近饱和，门杀省预算的边际价值有限。
- **建议**：维持现状——`--extreme` 保留为 power-user 入口（回放 E[best] 不劣 + 免人工选 budget/参数 + 长预算下多 seed 探索是对分布右尾的保险），race 默认档继续作现行缺省，不强推 extreme 为缺省。

## 2. 离线回放（scripts/extreme_ab_replay.py）

主表（p070/et0 池 n=25，T=14400s，20000 次 bootstrap，RNG seed 20260829）：

| 臂 | E[best] pt | best pt | P(≥90.5) | P(≥91.0) | P(≥91.5) | E[轮数] | E[存活] | E[被杀] |
|---|---|---|---|---|---|---|---|---|
| extreme | **91.774** | 91.774 | 1.000 | 1.000 | 1.000 | 43.2 | 3.8 | 39.4 |
| race_default | 90.898 | 91.544 | 1.000 | 0.067 | 0.067 | 151.2 | 3.8 | 147.4 |
| split24 | 91.763 | 91.774 | 1.000 | 1.000 | 1.000 | 24.0 | 24.0 | 0 |

副表（p080/et1 池 n=5，真跑 race/split 同参数方向；池上界 90.422，右尾受池约束仅作方向参考）：

| 臂 | E[best] pt | best pt | E[轮数] | E[存活] |
|---|---|---|---|---|
| race_default | 90.422 | 90.422 | 152.7 | 2.3 |
| split24 | 90.422 | 90.422 | 24.0 | 24.0 |

锚点（确定性有序回放，池 seed 升序 25 轮）：best=91.774（= 池最大，seed 23），名义耗时 9362.5s / 14400s，门杀 19/25，存活 {1,3,5,10,17,24} 位。真跑 extreme 臂 seed 流为 0..N 连续，前 25 轮即池内 seed 0..24（见 §3 确定性交叉验证）。

回放解读：同池同预算下 **extreme ≈ split24 > race_default**（+0.87pt，P(≥91.5) 1.000 vs 0.067）——600s 长 budget + p070/et0 参数抬高了单 seed 分布上尾，门杀再把 43 轮预算聚焦到 4 个存活 seed 上取最大；race_default 的 180s 短 budget 单 seed 上尾不足，门杀只能防呆不能凭空造高分。

## 3. 确定性交叉验证（extreme 臂 × 池 finals）

口径：extreme 真跑前 25 轮（seed 0..24，与池同参数 p070/et0/nw4/600s）逐 seed 对照池；存活 seed 比终值（vs 池 finals_pt），被杀 seed 比 kill 时刻值（vs 池曲线同时刻可行 incumbent，`feasible_at` 口径）。

| 分组 | n | 平均 Δ（真跑 − 池） | 范围 | 备注 |
|---|---|---|---|---|
| 存活 seed（600s 终值） | 5 | +0.88pt | −0.54 ~ +2.35 | seed 0 = −0.54pt（§5.2 并行争用窗口）；seed 1/3 = +2.09/+2.35pt |
| 被杀 seed（~300s 门时刻值） | 20 | +0.01pt | −5.03 ~ +2.94 | seed 13 = −5.03pt（异常弱轮）；seed 10 = +2.94pt |

- **判定点几乎重合**：best 所在 seed 23，真跑终值 91.708% vs 池 finals 91.774%（Δ **−0.07pt**）；聚合量同样吻合——轮数 42 vs 回放 E[轮数] 43.2、存活 5 vs E[存活] 3.8、best 91.711 vs 锚点 91.774。
- **逐 seed 确定性在跨会话条件下不成立**：偏差双向（有正有负），非纯 CPU 争用（争用只会变差）——机制 = 墙钟预算 + 4-worker 并行搜索对机器状态/批调度敏感（本机「同 seed 同预算背靠背重放逐帧确定」仅在相同条件下成立，池为 2026-08-28 白天/夜间生成、真跑为 08-29 深夜，条件不同）。存活集亦与锚点预测漂移：真跑 {0,1,3,4,23} vs 锚点 {1,3,5,10,17,24} 位。
- **结论**：§2 回放表作**机制级**佐证（分布形状、轮数/存活/best 聚合量全部对上），不作逐 seed 数值预测；验收判定以 §1 真跑为准。

## 4. 入口冒烟（两入口各至少成功启动一次）

| 入口 | 证据 |
|---|---|
| CLI `--extreme` | 本报告 §1 extreme 臂即真跑实启动：run_dir `us004_extreme4h_20260829-213815`（命令行带 `--extreme --time 14400`，托管见 `out/us004_ab/followup_runner.ps1`；strategy.json 记展开态 mode=race / budget 600s / gate 300s，rounds solver_opts p070/et0/nw4）|
| Web `/api/extreme/start` | 2026-08-29 16:58 冒烟：POST /api/session → /api/parse-dxf → /api/commit-to-nesting → /api/extreme/start（time_total_s=905 起）→ 202 running → /api/extreme/stop → stopped → result mode=extreme；run_dir `web_extreme_f793e2_20260829-165812` |

## 5. 附录

### 5.1 复现

```bash
# 离线回放（秒级）
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/extreme_ab_replay.py
# 三臂真跑（必须串行，4h × 3）
PYTHONUTF8=1 .venv/Scripts/python.exe -m materialsorting.cli.run_config data/configs/5336_coded_really.json --extreme --time 14400 --name us004_extreme4h
PYTHONUTF8=1 .venv/Scripts/python.exe -m materialsorting.cli.run_config data/configs/5336_coded_really.json --strategy race --time 14400 --name us004_race4h
PYTHONUTF8=1 .venv/Scripts/python.exe -m materialsorting.cli.run_config data/configs/us004_split24_5336.json --name us004_split4h
```

### 5.2 执行事故记录（影响面评估）

1. **并行失真（已否决）**：首次以 3 臂并行启动真跑，负载 76–84%，extreme seed0 = 89.0407%（对照池确定性 89.562%，−0.52pt）、帧数 2650 vs 2890（−8%）。全部终止并删除污染 run_dir，改串行。结论：**墙钟预算型求解禁止与其它 solver 进程并行**，已写入 `materialSorting-web/AGENTS.md` 速查。
2. **双 runner 误重叠（已修正，影响 <0.1pt）**：串行执行曾用 PowerShell 后台脚本托管；旧脚本（`serial_runner.ps1`，BOM-less 中文注释被 PS 5.1 按 GBK 误析吞掉 extreme 行）与修正脚本（`followup_runner.ps1`）在 race 结束时同时触发，split 臂 21:38:12 与 extreme 臂 21:38:15 短暂并行 ~6.5 分钟。处置：杀 split 树、删污染 run_dir、extreme 臂保留（争用窗口只覆盖 seed 0 前半程，§3 交叉验证单独标注）。教训：PowerShell 5.1 托管脚本中文注释必须 ASCII 化。
