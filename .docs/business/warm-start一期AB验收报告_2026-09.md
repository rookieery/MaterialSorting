# warm-start 一期 A/B 验收报告（MS 侧 US-005 集成验收，2026-09-19）

- **关联**：`tasks/prd-warm-start-phase1.md` US-005 验收标准 1~4；契约 = [sparrow-ms侧需求规格_warm-start暴露_2026-09.md](sparrow-ms侧需求规格_warm-start暴露_2026-09.md)（真相源本档同目录）；spyrrow-ms 侧交付台账 = 该仓 `.docs/technical/0a-exit-gate_2026-09.md` §7。
- **装载态**：MS `.venv` = `spyrrow 0.9.0+ms1`（commit `aaebfe8f2c41`，钉板 `materialSorting-server/spyrrow_build.json` 同步一致，`warm_start_supported() = True`）。
- **数据**：5336 `data/configs/5336_coded_really.json`（7 码 / gate 1980 / per_type 真实档 / 119 片）。

## 1. 前置 gate（验收标准 1）：引用 0a 归档 + ms1 双保险

- **0a 行为全等对拍已先行执行并归档 PASS**（2026-09-19 spyrrow-ms US-003 关账：PyPI 0.9.0 基线 / ms0 背靠背 ×2 三跑 best 五字段全等 0.880385 + curve 152 帧语义轨迹逐帧全等；MS 侧记录 `.docs/technical/0a行为全等对拍_spyrrow私有wheel_2026-09.md`）—— 按验收标准 1「已归档则直接引用结论」引用。
- **ms1 None 路径双保险**：spyrrow-ms 仓 golden 对拍 = ms1 不传 initial_solution 与 ms0 行为**逐字节全等**（width 3.99959659576416 / density 0.8746508955955505 / placed 多重集全等，`tests/test_warmstart.py::test_none_path_matches_0a_baseline` 锁死）+ 上游 13 测试零改动全绿。

## 2. warm 端到端（验收标准 2）：真灌入实证

最小预算轮 `--strategy se --time 275 --se-warm on`（1×90s 筛选 + 1×180s 延长，run `warm_e2e_20260919-114604`）：

| 检查点 | 结果 |
|----|----|
| strategy.json se 段（计划态） | `warm: true` ✓ |
| result.json config.strategy（实际灌入态） | `warm: true`（无 warm_reason = 无回退）✓ |
| 延长轮首帧宽度 vs 灌入 strip_width | **7370.440 == 7370.440，delta = 0.0000mm**（判据 ±1mm）✓ |
| 延长轮首帧 density | == 冠军帧 0.887953（restore 起点即冠军解）✓ |
| 末帧 placed 条数 | 119 == Σdemand（best_frame_s0_ext / result solve 记录双源）✓ |
| run_stats 行 additive | config 段含 `warm` 键（无 warm_reason）✓ |
| 延长增益 | 88.795% → 89.618%（+0.82pt，warm 增量搜索） |

## 3. se A/B 判据（验收标准 3）：**PASS —— 保默认 on**

命令：`ms-run-config data/configs/5336_coded_really.json --strategy se --time 600 --se-warm {on,off} --quiet`（k=4 筛选 [0,1,2,3] + 冠军 180s 延长；champion 恒 seed 3）。

**执行记录**：目标 6 轮（on/off ×3 交替）；会话切换杀掉外层编排但求解进程存活，恢复脚本接力 + 原脚本实际未死，实际产出 **11 轮 = on 臂 5 轮 / off 臂 6 轮**（on_1 独跑窗口，其余每轮恰 1 个并发伙伴、on/off 混配对称；各轮耗时 7.9~8.8min 与独跑一致，工作站核余量下争抢影响弱；超计划的重复轮是同命令独立窗口样本，只增统计量）。

| 臂 | n | best real_density（原面积口径） | 均值 |
|----|---|----|----|
| warm on | 5 | **90.4784% ×5（零方差）** | **90.4784%** |
| warm off（现状重放） | 6 | 90.4360% ×3 / 90.4009% ×3 | 90.4185% |

- **判据：warm − replay = +0.0599pt ≥ −0.1pt → PASS，`--se-warm` 默认 on 维持**（且逐对比较 on 90.4784 严格 > off 最大值 90.436，符号稳健零翻转）。
- 机理：warm 灌入冠军解后延长轮 180s 全花增量搜索，稳定到达 90.4784 不动点；重放臂从头跑有时收敛不到同水位（90.436/90.4009 双吸引子）。
- **背靠背确定性双跑（同 warm 输入 ⇒ restore 后轨迹确定）**：三对 on 轮（含独跑 vs 并发窗口）延长轮 `curve_s3_ext.json` **5 帧语义轨迹（phase/density/width）逐帧全等**；warm 输入源冠军帧 `best_frame_s3.json` 六跑全等（0.904009 / 7239.53mm / 119 片）。

## 4. 既有验收复跑（验收标准 4）：全绿

| 项 | 结果 |
|----|----|
| `python -m materialsorting.web.prefix_accept --seeds 0,1 --time 30 --intermediate <5336 run_dir>` | **accept**：①on/off 均值 −0.026pt ≤1.0pt、形态 2/2、双开 −0.313pt、③确定性 frames 132==132 逐帧全等 + 工件回放全等、④导出无泄漏（web 事实源 intermediate 为他母版，改用 run_dir 5336 intermediate，链路同源） |
| pytest 全量（materialSorting-server） | **1056 passed**（含 tests/test_warmstart.py 18 例 + tests/test_spyrrow_wheel.py 27 例；本次修复 2 例环境耦合误报 —— 钉板 ms0 时代写死、钉板同步 ms1 后暴露，加 `_pin` 临时钉板 mock 隔离） |
| vitest 全量（materialSorting-web） | **71 files / 1217 tests passed**（本轮前端零改动，符合预期） |

## 5. 结论

- 六项验收标准全部满足（标准 5/6 文档收官与验证速查见 `tasks/prd-warm-start-phase1.md` 末节）。
- warm-start 一期全链闭环：spyrrow-ms `0.9.0+ms1`（A1 暴露 + 直调测试）→ MS 载荷构造/透传/装载点 → se 延长轮真顺延，**默认 on 有 +0.06pt 实测背书**。
- 残留观察（不阻塞）：off 臂双吸引子（90.436/90.4009）属重放轮固有方差；「每 N 版复测」复查机制暂不建（Open Questions 维持暂不定，漂移幅度 <0.04pt 远离判据线）。
