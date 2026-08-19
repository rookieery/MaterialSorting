# PRD: 串行 Seed Portfolio 排料求解优化 v2（CLI 控制器 + 标定 + LNS 后处理）

> v2（2026-08-19）：基于近期两大改动重构 —— ① 裁片编号重构（per_type/quantities 全 g 码口径 g01~g10，pid=`{label}_{size}`，无镜像展开）；② `ms-run-config` 配置驱动通道落地（7 键 JSON + 串行多 seed + best 汇总已存在）。v1 的「前端控制器」方案废弃，**控制器全部落 cli 包**（用户已确认：CLI 优先 / 参数走 CLI 旗标+标定文件 / 暂不做 CLI 导出 / 标定基实例 = `5336_coded_really.json` 生产真实配置 + 订单微调变体集）。

## 概述 (Overview)

生产服务器只能满血运行单个求解 seed，而单 seed 收敛密度具有强随机性（85%~90%，常落 ~86%）。本 PRD 在 **`ms-run-config` CLI 通道**上构建 racing 控制器：串行 seed 队列 + 逐帧 incumbent banking（任何中断都有全局最优交付物）+ 必死 seed 提前淘汰（R1~R3 kill 规则 + θ 自适应衰减，shadow mode 默认只记不杀）+ 达标即停，目标从「最大密度」升级为「最小期望达标时间（ETT）」。配套：标定管线（生产真实配置跑批 + 订单微调变体集 + 包络分析 + ETT 离线仿真，基实例 = `data/configs/5336_coded_really.json`）、solver_opts 配置轮换、LNS 波段重排后处理、run 统计库与 θ₀ 校准。**web 前端与 WS 协议本期零改动；config.json 7 键 schema 不动**（portfolio 参数一律 CLI 旗标）。

## 目标 (Goals)

- 同总预算下，达标（real 口径 density ≥ target）期望时间相对「单 seed 跑满」下降 ≥ 40%（以 PC-005 离线仿真报告为准，标定曲线来自 5336 实例）。
- 90 不可达实例优雅退化：portfolio 交付密度 ≥ 单 seed 全预算收敛值 − 0.2pt（incumbent 保底，不全军截断）。
- 任何时刻（kill / Ctrl-C / 队列耗尽）run_dir 内持有已见最优解（best 帧 + placed_items 落盘，incumbent banking 不变量）。
- kill 误杀率（shadow 回测）：被杀 seed 中「跑完本可达标」占比 < 5%。
- 零回归：`ms-run-config` 不带新旗标运行，result.json 结构与输出汇总与现状等价；分层依赖（cli → web → engine → bounds → parser）与 7 键 config schema 不破坏。

## 用户故事 (User Stories)

> 编号 PC-###（Portfolio CLI）。执行顺序 = Priority 顺序。P0'（PC-001~003）→ P1.5（PC-004~005）→ P1（PC-006）→ P2（PC-007~008）→ P3（PC-009）；PC-004 依赖 PC-001，PC-006~009 可与 P1.5 并行。

### PC-001: solve_pieces 进程化 + 曲线/best 帧落盘 + should_stop 中止能力
- **Description**: As a 算法工程师, I want 单 seed 求解可被中途终止、且逐帧轨迹落盘 so that kill/达标即停有执行手段、标定有数据。改造 `cli/pipeline.py solve_pieces`：求解从 threading 版 `solve_with_callback` 切换到 **`solve_with_callback_proc` 多进程版**（terminate 链路 `terminate → cancel_join_thread → drain ≤50ms → join(5)` 已在 US-025/026 验证）——主进程仍先 `build_instance` 取 meta（demand_sum 校验、total_area、pid_meta），子进程内重建 instance 是 proc 设计固有成本（秒级）。新增可选参数 `should_stop(frame) -> bool`：每帧回调，True → 走 terminate 链路终止子进程、以该 seed 的 **best-so-far 帧**作为结果返回（`killed=True` + reason）。落盘新增（run_dir 内）：`curve_s{seed}.json`（每帧 `{elapsed, phase, density, density_sparrow, width_mm}`，**不含 placed_items** 控体积）+ `best_frame_s{seed}.json`（该 seed 最优帧完整 placed_items，严格大于才覆盖写）。
- **Acceptance Criteria**:
  1. 行为零回归：`ms-run-config data/configs/5336_coded_really.json --time 5` 冒烟通过（真实公差路径含 erode），result.json `solve` 数组字段结构与现版一致（seed/n_items/n_eroded/total_area_mm2/width_mm/real_density/density_sparrow/placed_items/elapsed），`placed == Σdemand` 校验仍生效；stdout 汇总行格式不变。
  2. `should_stop` 恒 False 时与不传等价；返回 True 时子进程确被终止（无孤儿进程，单测以 `on_process` 句柄 join 断言）、返回记录 `killed=True` 且 density = 终止前 best-so-far 帧的 real 口径 density。
  3. `curve_s{seed}.json` 帧数 ≥1 且 elapsed 单调不减；`best_frame_s{seed}.json` 的 density = 曲线内最大帧 density（fake solve 单测）。
  4. Ctrl-C（KeyboardInterrupt）中断多 seed 循环时，已完成 seed 的 curve/best_frame/result 均已落盘（逐 seed 写，不攒内存）。
  5. 密度口径不变：curve 与 best 帧的 `density` 均为原面积口径（`total_area/(width*gate_mm)`，复用 `_apply_density_dual`）；`python -m materialsorting.cli.pipeline` 导入冒烟 + pytest 全绿 + 分层未反向。
- **Priority**: 1

### PC-002: portfolio 调度器 + incumbent banking + result.json portfolio 段
- **Description**: As a 生产环境受限的排料工程师, I want 跑完 seeds 队列的过程中全局最优帧被持续入账并最终交付 so that 交付物永远是过程中的最好解。新建 `cli/portfolio.py` 控制器（纯 Python 状态机，被 `run_config.main` 消费）：逐 seed 串行调 `solve_pieces`（串行循环已存在，改为经控制器转发）；每帧 `density > I` 则更新 incumbent（I=全局最优密度，来源 seed/frame_index/elapsed/width_mm 一并记录）。规则：**R0** 任一帧 `density ≥ --target` → 对当前 seed 触发 should_stop、终止剩余队列；**R4** 队列耗尽 → 正常结束。CLI 新旗标（config 7 键不动）：`--target <0..1>`（缺省不启用 R0）、`--params <controller_params.json>`（可选，标定参数覆盖默认阈值，PC-004 产物）。result.json 新增 `portfolio` 段：`{target, incumbent: {density, width_mm, seed, frame_index, elapsed, placed_items}, per_seed: [{seed, killed, kill_reason, best_density, elapsed}], theta_history}`；`best` 语义升级为 **incumbent（帧级全局最优）**，`solve` 数组保留不变。
- **Acceptance Criteria**:
  1. incumbent 单测（fake solve 注入帧序列）：3 seed 交错轨迹下 incumbent = 全局最大帧 density、来源字段正确；被 kill/中途停止的 seed 的最优帧参与全局最优（修复「best 只看 per-seed 终值」的盲区）。
  2. R0：mock seed2 中途达标 → seed2 被 stop、seed3 不再启动、`portfolio.per_seed[2]` 无记录或标 skipped、退出码 0；无 `--target` 时行为与现版一致（跑满全队列）。
  3. `best` 与 `portfolio.incumbent` 一致且含完整 placed_items；不带 `--target` 的单 seed 运行 result.json 含空 portfolio 段、`best` 与旧语义兼容（无旗标冒烟对拍）。
  4. 进度输出沿用「新最优才打 + 30s 心跳」模式，新增 per-seed 轮次头与 incumbent 行（`--quiet` 全抑制）。
  5. `python -m materialsorting.cli.run_config --help` 含新旗标；pytest 全绿；分层未反向。
- **Priority**: 2

### PC-003: kill 规则引擎 R1/R2/R3 + seed1 锚定 + shadow mode（默认只记不杀）
- **Description**: As a 追求最短达标时间的排料工程师, I want 必死 seed 被提前淘汰省出预算 so that 单位时间有效样本数与质量同升。`cli/portfolio.py` 扩展 kill 引擎（纯函数 + 控制器状态：θ、kill_streak）。逐帧评估（τ=elapsed/time、d=该 seed best-so-far、I=incumbent、θ 初值=target）：**R1 包络 kill**（seed 序号 >1 且 τ>τ0 且 `d < S(τ) − m` 持续 W 秒；S 来自标定参数，**无标定时 R1 整体禁用**）；**R2 压缩期判决**（首帧 `phase=='compressing'` 时 `d + uplift_q95 < max(θ, I+ε)` → kill）；**R3 θ 衰减**（kill_streak ≥ m_streak → `θ := I + δ`，只降 kill 门槛，**R0 恒用真 target**）；**seed 1 永不 kill**（锚定交付下限 + 校准样本）。CLI 旗标 `--kill shadow|off|on`（默认 **shadow**，仅当 `--target` 给定时引擎激活）：shadow 只写 `run_dir/kill_decisions.jsonl`（`{t, seed, rule, d, τ, S(τ), θ, I, would_kill}`）；`on` 才真正触发 should_stop，且**要求标定参数就绪**（`calibrated: true`，否则降级 shadow 并 warn）。保守默认：τ0=0.3、W=10s、m=0.5pt、ε=0.1pt、δ=0.3pt、m_streak=3（`--params` 可覆盖）。
- **Acceptance Criteria**:
  1. 纯函数引擎单测 ≥ 12 项：seed1 豁免 / R0 不受 θ 衰减影响 / R2 压缩首帧判决 / R3 连杀触发衰减且只影响后续 kill 判据 / W 秒迟滞（瞬时下探不杀）/ 无标定参数时 R1 禁用、`--kill on` 无标定自动降级 shadow。
  2. shadow 模式绝不终止求解（fake solve 断言 should_stop 仅由 R0 触发），kill_decisions.jsonl 条目字段完整。
  3. 被 kill 的 seed 记录 `killed=True + kill_reason`，其 best 帧仍入 incumbent（与 PC-002 联动单测）。
  4. 端到端小冒烟：`--time 5 --target 0.5`（低门槛必触发 R0）跑通全链路，portfolio 段与 kill 日志符合预期。
  5. `python -m materialsorting.cli.run_config --help` 跑通；pytest 全绿；分层未反向。
- **Priority**: 3

### PC-004: 标定管线（生产真实配置跑批 + 订单微调变体集 + analyze 包络/uplift/误杀回测）
- **Description**: As a 算法工程师, I want 用**生产真实配置及其订单邻域变体**跑批标定 controller 参数 so that kill 规则既有本实例的精确包络、又不过拟合单一订单。新建 `cli/calibration.py`（`python -m materialsorting.cli.calibration`），三个子命令：
  - **`batch`**：输入一份 7 键 config —— 标定基实例 = **`data/configs/5336_coded_really.json`**（生产实际数据：真实 per_type 公差（g06 d=10/tol=45 等）+ 真实订单配比 quantities（14%7%围加9 混码）+ 7 码子集 [31~36,38]；**不用** `5336_coded_sizes32-38.json` 退化样例——per_type 全 0 / 数量全 1，密度分布与收敛动态对生产完全失真）+ `--short-seeds 20 --short-time 90 --full-seeds 8`（全预算组用 config 的 time=300），复用 `commit_from_config` 一次 + 逐 seed 串行 `solve_pieces`（曲线/best 帧落盘 `out/portfolio_calibration/<tag>/base/`），Ctrl-C 中断安全；
  - **`variants`**：确定性变体生成器（seeded RNG，可复现）——**只抖动订单维度**：quantities 每 (g 码, 码∈sizes) 条目 `n' = max(1, n + δ)`、δ∈{-1,0,+1} 等概率（保底 1 片防整 g 码消失；sizes 子集外的惰性条目不动）；**工艺维度逐字段固定**（per_type / gate_mm / master_dxf / sizes 不随订单漂移、不随机）。产出 `variant_{i}.json`（i=0..N-1，RNG seed=i）→ 逐变体串行跑 6 seed × 90s + 1 × 300s 全预算对照，曲线落 `<tag>/variant_i/`；
  - **`analyze`**：聚合 base 曲线 → `summary.json`（每 seed 终值/best 帧 density/time-to-best/收敛平台、mean/σ/P(≥target)）+ 成功包络 `S(τ)`（达标 seed best-so-far 轨迹低位分位数，τ 网格 0.05~1.0 步长 0.05）+ compression uplift 分布（q50/q95）+ 短时/全时秩相关 + **train/test 误杀回测** → 写 `controller_params.json`（`calibrated: true` + τ0/W/m/ε/δ/m_streak 推荐值；样本 < 10 seed 拒绝下发 `calibrated: false`）；聚合变体曲线 → **泛化报告**（base 包络套用到各变体的误杀率/包络可迁移性判定，防过拟合基实例）。
- **Acceptance Criteria**:
  1. batch/variants 串行不变量：任一时刻至多 1 个求解子进程；base 28 seed + 4 变体 × 7 seed 的曲线与 best 帧全部落盘、目录结构稳定（单测以 fake solve 驱动编排）。
  2. 变体生成器单测：确定性（同参数两次生成逐字节一致）；抖动只作用于 sizes 内条目、`max(1, n±1)` 约束正确；per_type/gate_mm/master_dxf/sizes 与基配置逐字段相同；生成物通过 `load_config` 校验（合法 7 键）。
  3. analyze 对注入 fake 曲线集的单测：包络单调性、uplift 分位数、达标/失败轨迹分离度、train/test 误杀率计算正确；小样本拒绝下发；泛化报告含「base 包络 × 变体」误杀率字段。
  4. 产物只落 `out/portfolio_calibration/`（gitignore 区），不触碰 `out/config_runs/` 与 web 数据目录。
  5. 真实跑批执行记录：base 20×90s + 8×300s + 4 变体 ×（6×90s + 1×300s）≈ 2 小时机器时间（可由用户/代理会话内执行，产物路径写入 story 交付说明）。
  6. `python -m materialsorting.cli.calibration batch/variants/analyze --help` 跑通；pytest 全绿；分层未反向。
- **Priority**: 4

### PC-005: ETT 离线仿真器（策略网格回放 → 推荐参数档）
- **Description**: As a 算法工程师, I want 用历史轨迹离线回放比较不同 (k, kill 参数, δ, m) 策略的 ETT 与保底终值 so that 参数选型零真实求解成本。`cli/calibration.py` 加 `simulate` 子命令：输入曲线集（batch 产物）+ 策略网格（单 seed 基线 / 均匀 best-of-k / kill 各档 / θ 衰减各档），回放仿真输出 `simulation_report.json` + 控制台表格：每策略 ETT（达标用时期望）、P(达标|预算内)、不可达场景 incumbent 终值（截断轨迹用「kill 时刻 best + 条件期望增量」插值，**物理有界：不低于 kill 时刻 best-so-far**）；**变体曲线作 held-out**——策略网格在变体上的 ETT/误杀率一并输出，推荐档须 base 与变体双达标。同时消费 shadow 日志：`--shadow-log <kill_decisions.jsonl>` 统计真实 would-kill 决策的假阳性。
- **Acceptance Criteria**:
  1. 合成曲线（已知分布）下 ETT 排序符合理论：best-of-k < 单 seed；分离度大时激进 kill < 保守 kill —— 单测固化。
  2. 截断插值下界单测：kill 时刻的 incumbent 估计 ≥ 该时刻 best-so-far。
  3. 报告含推荐参数档（base 与变体集上 ETT 均不劣于单 seed 基线、两者误杀率 < 5%），字段可直接抄进 controller_params.json。
  4. `python -m materialsorting.cli.calibration simulate --help` 跑通；单测 ≥ 8 项；分层未反向。
- **Priority**: 5

### PC-006: solver_opts 透传 + 配置轮换（exploration 切分 / quadtree / workers）
- **Description**: As a 算法工程师, I want spyrrow config 旋钮（`exploration_time`/`compression_time` 切分、`quadtree_depth`、`num_workers`）可透传并在 seed 间轮换 so that 样本去相关、上尾更易被摸到。`web/solver.py build_instance` 加可选参数 `solver_opts: dict | None`（additive；`exploration_pct` 0.1~0.95 换算为两段 int 秒且**与 total_computation_time 互斥**、`quadtree_depth` 3/4/5、`num_workers` 默认 4；非法值 clamp）；`cli/pipeline.py solve_pieces` 加同形参数并入 solve_params（全 JSON，spawn 安全）。CLI 旗标：`--solver-opts '{"exploration_pct":0.7}'`（全 seed 生效）+ `--rotate-opts`（默认 OFF；开启后按内置轮换池 `pool[seed_index % len]` 取档，池内含空档=默认行为；`--solver-opts` 与 `--rotate-opts` 互斥报错）。不传任何旗标 = 现行行为不变（WS 协议本期不加字段）。
- **Acceptance Criteria**:
  1. `build_instance` 单测：不传 solver_opts 时 config 字段与现状一致；exploration_pct=0.6 → 两段 int 秒、和 ≈ time_budget；越界 clamp；quadtree_depth/num_workers 透传。
  2. solve_pieces/solve_worker 透传链单测（fake config 断言子进程收到的 solve_params 含 solver_opts）。
  3. 轮换单测：k=5、池 4 档时第 5 个 seed 回到 pool[0]；`--rotate-opts` 与 `--solver-opts` 同给报配置错误（退出码 1）。
  4. 无旗标冒烟：`ms-run-config <5336 config> --time 5` 行为与 PC-001 基线一致（对拍 real_density 结构性字段，不要求逐位一致——num_workers=4 并行探索本就不保证可复现）。
  5. `python -m materialsorting.web.solver` 导入冒烟 + pytest 全绿 + 分层未反向（cli → web 单向）。
- **Priority**: 6

### PC-007: LNS 波段重排核心模块（对 incumbent 布局局部改进）
- **Description**: As a 算法工程师, I want 对 portfolio 最优布局做波段级 ruin-and-recreate so that 突破单 seed 收敛分布的上限。新建 `cli/lns.py`（`python -m materialsorting.cli.lns --run-dir <dir> --time 30 --rounds 5 [--band-width mm]`；cli → web.solver/engine 合规向下依赖）。输入 run_dir 的 `result.json`（incumbent placed_items）+ `pieces_intermediate.json`，算法：① 按 x 切竖直波段（默认段宽 1.5×NEST_GATE_MM）；② 每段局部密度 = 段内片面积和/（段宽×NEST_GATE_MM），取最差段；③ 段内裁片构造**同口径**子实例（`web.solver.build_instance`，per_type/quantities 按 **g 码**键透传；demand>1 的 pid 全部副本整段进波段重排，禁止拆分）；④ 新段宽 < 原段宽 − ε → 接受：后续波段左移 splice、总宽缩短；否则拒绝（幂等安全）；⑤ 循环 rounds 直到无段可改进或预算耗尽；结束 `constraints.validate` 全版复检 + y ≤ PLOT_SAFE_MAX_Y_MM 越界复检。输出 `result_lns.json`（新 placed_items + 前后 density/width 对比）+ 前后对比 SVG。
- **Acceptance Criteria**:
  1. 构造带人工空洞的 fixture 布局单测：一轮后总宽缩短 ≥ 空洞宽 50%，全片在场（数量 = Σdemand，含 demand>1 副本数不变）。
  2. 子实例同口径单测：erode/tol/orientations/strip_height 钳制与母实例一致（g 码 per_type 命中）。
  3. 拒绝路径：子解不优于原段 → 输入布局逐字节不变。
  4. 复检双通过：`constraints.validate` ok + y 越界 0 片。
  5. `python -m materialsorting.cli.lns --help` 跑通；单测 ≥ 10 项；分层未反向。
- **Priority**: 7

### PC-008: LNS 接入 portfolio 编排（--lns 后处理步）
- **Description**: As a 排料工程师, I want portfolio 跑完后自动对最优解做 LNS 后处理 so that 最后 0.5~1 个点的缺口在产线内补齐、无需手工二次命令。`run_config` 加旗标 `--lns [--lns-time 30] [--lns-rounds 5]`：portfolio 结束后对 incumbent 跑 PC-007 核心循环，**严格更优才回写** result.json（`portfolio.incumbent` 更新 + 新增 `lns` 段记录前后对比与轮次明细），不优则 result.json 不变（LNS 明细仍写 `result_lns.json`）。stdout 汇总加 LNS 前后两行。
- **Acceptance Criteria**:
  1. 改进路径单测：LNS 更优 → incumbent 的 density/width_mm/placed_items 更新、`lns` 段含 before/after；不优 → result.json 与无 `--lns` 运行逐字节一致。
  2. `--lns` 与 `--target` 组合：R0 提前停后同样执行后处理（对达标解也可再压宽度）。
  3. LNS 中断安全：Ctrl-C 时已完成轮次写入 result_lns.json，主 result.json 不半写。
  4. 端到端冒烟：`ms-run-config <5336 config> --time 5 --target 0.5 --lns --lns-time 5` 全链路跑通。
  5. `python -m materialsorting.cli.run_config --help` 跑通；pytest 全绿；分层未反向。
- **Priority**: 8

### PC-009: run 统计库 + θ₀ 按实例类校准
- **Description**: As a 算法工程师, I want 每次 run 的结果自动沉淀为按实例类的统计 so that θ 初值按可达性校准（历史最高 89.6% 的组合不再从 90 起跑）、分布越测越准。`run_config` 结束时（含 R0 提前停/kill 路径）追加一行 JSONL 到 `out/run_stats.jsonl`：`{ts, source, sizes, class_key, seeds, target, best_density, n_killed, elapsed_total, config: {time, per_type, quantities}}`（`class_key = sha1(source + sizes + quantities + per_type)` 短哈希）；写盘失败 try/except 不阻塞主流程。`cli/portfolio.py` 启动时读该文件：当前 class_key 命中且 ≥ 5 条记录 → θ 初值 = `min(target, 历史最大 best_density + 0.003)` 并打一行说明，否则 θ = target。
- **Acceptance Criteria**:
  1. 连跑 2 次 → JSONL 恰 2 行、字段完整（fake solve 单测）；R0 提前停路径也落盘。
  2. θ₀ 单测：命中且 ≥5 条 → min(target, max+0.003)；不足 5 条 → target；不同 class_key 互不污染；**θ₀ 只影响 kill 门槛，R0 停止条件恒用 --target**（回归断言）。
  3. 写盘失败（模拟只读目录）不抛出、run 正常完成（warning log）。
  4. `python -m materialsorting.cli.run_config` 冒烟 + pytest 全绿；分层未反向。
- **Priority**: 9

## 功能需求 (Functional Requirements)

- FR-1: portfolio 编排全部在 cli 包（`ms-run-config` 通道）：串行 seed 队列、每 seed 独立子进程满血求解（任一时刻至多 1 个求解进程）。
- FR-2: incumbent banking 不变量：每帧 real 口径 density 严格大于全局最优即入账；`best`/`portfolio.incumbent` 交付帧级全局最优（含被 kill seed 的最优帧）。
- FR-3: R0~R4 控制规则：达标即停（恒用 `--target` 真值）/ R1 包络 kill（seed1 锚定豁免）/ R2 压缩期判决 / R3 θ 衰减（只影响 kill 不影响停止）/ 队列耗尽交付 incumbent。
- FR-4: kill 默认 shadow（只记 `kill_decisions.jsonl` 不杀）；`--kill on` 需标定参数 `calibrated: true`，否则自动降级 shadow。
- FR-5: 标定管线（batch/variants/analyze/simulate）与生产严格同口径：基实例 = 生产真实 config（`5336_coded_really.json`），变体 = 订单维度微调（quantities ±1，工艺维度 per_type/gate/master 固定）；同一 `commit_from_config` + `solve_pieces` 链路；产物只落 `out/portfolio_calibration/`。
- FR-6: solver_opts 透传（exploration_pct/quadtree_depth/num_workers）+ `--rotate-opts` 轮换；不传旗标行为不变，WS 协议与 7 键 config schema 零改动。
- FR-7: LNS 波段重排走同口径子实例 + `constraints.validate` + y≤1910 复检，拒绝不劣化，严格更优才回写 result.json。
- FR-8: 所有密度决策/统计用原面积口径 `density`（复用 `_apply_density_dual`，不在 CLI 侧复制公式）；sparrow 口径仅记录。
- FR-9: g 码口径贯穿：per_type/quantities 键 g01~g10、pid=`{label}_{size}`、demand 按 `(label, str(size))` 查询（多副本不变量：placed == Σdemand）。

## 非目标 (Non-Goals)

- **web 前端与 WS 协议零改动**：前端并发 multi_seed 维持现状（交互探索用途）；controller 的 web 版（串行调度 + HUD）留待生产验证后另立 PRD。
- **CLI 不做 PNG/DXF/PLT 导出**（用户已确认暂缓）：交付物 = result.json + best 帧布局 JSON，导出仍走 web 工作台。
- **config.json 7 键 schema 不动**：portfolio 参数一律 CLI 旗标 + `--params` 标定文件（用户已确认）。
- 不改 spyrrow 源码、不做 warm-start/断点续跑（无该 API，架构约定禁改）。
- 不做后端无人值守 job runner / 多机分布式调度。
- 小件预合成（裤耳组合多边形）实验不在本 PRD。
- 不重构 `sparrow_baseline.py` 职责混合问题（已知问题，不在本 PRD 扩大改动）。

## 设计考虑 (Design Considerations)

- CLI 输出克制：沿用「原面积口径新最优才打 + 30s 心跳」模式；portfolio 增加轮次头 / incumbent 行 / kill 决策一行流（shadow 条目带「未执行」标注），`--quiet` 全抑制。
- curve 文件不含 placed_items（1500 帧 × 300s 会爆体积）；布局只在 best 帧文件与 incumbent 中落盘。
- kill 决策 JSONL 与 run_dir 同居，PC-005 `--shadow-log` 直接消费，形成「shadow 攒数据 → 仿真回测 → 启用真杀」闭环。
- θ 衰减/θ₀ 校准的用户可见性：stdout 打一行（`θ 衰减至 88.1%（连杀 3 轮）`），不静默改判据。

## 技术考虑 (Technical Considerations)

- **kill 必须进程化**：spyrrow Rust solve 无 stop API，threading 版不可中断 —— `solve_with_callback_proc` 的 terminate 链路（`terminate → cancel_join_thread → drain ≤50ms → join(5)`）是唯一可靠中止手段，已由 US-025/026 验证；主进程额外一次 `build_instance` 取 meta（demand_sum/total_area）是可接受的秒级成本，避免在 CLI 复制 demand 查询逻辑（单一真相源）。
- `solve_params` 全 JSON 可序列化（Windows spawn 安全），`solver_opts` 走同通道；子进程内重建 instance 是 proc 设计固有行为。
- 中断安全：逐 seed 落盘（curve/best_frame/kill_decisions 增量写），Ctrl-C 不丢已完成 seed 的产物；result.json 在 portfolio 末尾原子写。
- LNS 波段归属按 **pid 聚合**（demand>1 全副本整段进波段，禁止拆分）；子实例 erode/tol 按 g 码 per_type 命中，strip_height 钳 NEST_GATE_MM 与母实例同口径。
- 标定产物目录 `out/portfolio_calibration/`（gitignore 区），`controller_params.json` 缺失/损坏 → 引擎用保守默认 + R1 禁用，不崩。
- **标定数据来源（非凭空随机生成）**：以生产真实配置为中心的订单邻域采样——base 实例给精确包络/uplift（repeat 订单 class_key 命中即用，PC-009），变体集只抖订单维度（quantities ±1）做泛化验证；采样自真实订单漂移空间而非均匀随机实例空间，工艺维度（per_type/gate/master）按款固定不抖。
- ETT 仿真的截断插值必须物理有界（不低于 kill 时刻 best-so-far）。
- `early_termination`（spyrrow config 字段）语义在 PC-004 真实跑批时顺带实测记录一次（影响重启动节奏，不阻塞任何 story）。
- 密度/门幅双口径不变量沿用：决策用 real 口径与 gate_mm 显示口径；求解约束带 NEST_GATE_MM=1910。

## 成功指标 (Success Metrics)

- [ ] PC-005 仿真报告（5336 标定曲线）：portfolio + kill 相对单 seed 同预算达标时间下降 ≥ 40%。
- [ ] shadow 回测误杀率 < 5%（PC-004 train/test + PC-005 shadow-log 统计），且 base 包络套用到变体集误杀率 < 5%（泛化报告）。
- [ ] 不可达场景仿真：incumbent 终值 ≥ 单 seed 全预算收敛值 − 0.2pt。
- [ ] 真杀启用后（shadow ≥ 2 周或 ≥ 50 run 之后）：生产达标 run 平均耗时相对基线下降 ≥ 30%。
- [ ] 零回归：无旗标 `ms-run-config` 行为/输出/result.json 结构与现版等价；全部 pytest 通过；`python -m` 各入口冒烟通过；分层依赖未反向。

## 待确认问题 (Open Questions)

- shadow 攒数据周期与真 kill 启用时点（建议：≥ 2 周生产轨迹或 ≥ 50 run，以 PC-005 回测误杀率 < 5% 为闸）。
- R2 无标定时的默认 uplift 0.005 是否过保守（PC-004 出数后复核）。
- LNS 波段宽默认 1.5×NEST_GATE_MM 是否合适（PC-007 实验后定，`--band-width` 可调）。
- θ₀ 自动校准对「新款首次排料」的回退语义（无历史 class_key → θ=target，PC-009 已含，需确认产品语义）。
- 5336 真实跑批的机器时间窗口（≈2 小时：base 70min + 变体 56min；PC-001~003 落地后即可执行，由用户安排或代理会话内执行）。
- ~~变体数量与抖动幅度~~（已确认 2026-08-19：v1 按默认执行——4 变体、quantities ±1 保底 1 片、**不抖 sizes**；首批跑批后按泛化报告的包络可迁移性复核，仅在失真时调整）。
- web 端 controller（串行调度 + incumbent HUD + kill 面板）何时立项（本期明确不做，生产验证后另立 PRD）。
