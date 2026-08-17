# PRD: 串行 Seed Portfolio 排料求解优化（racing controller + 标定 + LNS 后处理）

## 概述 (Overview)

生产服务器只能满血运行单个求解 seed，而单 seed 收敛密度具有强随机性（典型区间 85%~90%，单次抽样常落在 ~86%）。本 PRD 把「并行多 seed 赌运气」改造为**串行 seed portfolio + racing 控制器**：顺序发起 seed、逐帧入账全局最优（incumbent banking）、对必死 seed 提前淘汰（kill 规则 + θ 自适应衰减）、达标即停，目标从「最大密度」升级为「**最小期望达标时间（ETT）**，且任何时刻中断都有最优交付物」。配套：标定实验管线（分布测量 / 包络标定 / ETT 离线仿真）、config 轮换、LNS 波段重排后处理（突破单 seed 分布上限）、生产统计库。

## 目标 (Goals)

- 同总预算下，达标（density ≥ 90%，real 口径）期望时间相对「单 seed 跑满」下降 ≥ 40%（以 P1.5 离线仿真报告为准）。
- 90 不可达实例优雅退化：portfolio 交付密度 ≥ 单 seed 全预算收敛值 − 0.2pt（有保底，不全军截断）。
- 任何时刻（kill / 手动停止 / 预算耗尽）持有全局最优解并可导出（incumbent banking 不变量）。
- kill 规则误杀率（shadow 回测）：被杀 seed 中「跑完本可达标」的占比 < 5%。
- 不改 spyrrow 源码、不破坏分层依赖（web → engine → bounds → parser）与现有 WS/导出契约（additive 扩展）。

## 用户故事 (User Stories)

> 编号 PS-###（Portfolio Serial），避免与历史 US-001~US-034 混淆。执行顺序 = Priority 顺序；P0'（PS-001~004）与 P1.5（PS-005~007）两条链可并行推进。

### PS-001: portfolioStore + incumbent banking（跨 run 最优席位）
- **Description**: As a 排料工程师, I want 每个 frame 的最优解被全局记录（density + placed_items + 来源 run/frame）so that 任何时刻中断都持有已见最优方案可导出。新建 Zustand store `src/store/portfolioStore.ts`：`incumbent: { density, width_mm, placed_items, seed, runIndex, frameIndex, elapsed } | null` + `bank(frame, rec)` 入账 action（density 严格大于才覆盖）+ `reset()`；NestingPage/`useSolveRun.onFrame` 逐帧调 `bank`。修复现状缺陷：`runRegistry.bestRun()` 按 `finalDensity` 选优，被 kill/停止的 run `finalDensity=0`、其最优帧不参与导出——incumbent 按帧密度入账后此问题消失。
- **Acceptance Criteria**:
  1. `bank` 仅在 `frame.density > incumbent.density`（首个 frame 恒入账）时覆盖；同 run 内 best-so-far 与跨 run 最优均正确（单测：3 个 fake run 交错 frame 序列，incumbent 终值 = 全局最大帧密度，来源字段正确）。
  2. incumbent 使用 frame 的**原面积口径 `density`**（`density_sparrow` 不参与决策，关键不变量延续）。
  3. `reset()` 在 handleStart 开头调用（与 runRegistry.clear 同步）；单测覆盖。
  4. placed_items 为该帧完整引用（demand>1 时含同 pid 多条 placement，多副本不变量不破坏）。
  5. `npm run typecheck && npm run test && npm run build` 通过；新增 `portfolioStore.test.ts` ≥ 6 项。
- **Priority**: 1

### PS-002: 串行 portfolio 调度器（顺序发起 + R0 达标全停 + R4 预算耗尽）
- **Description**: As a 生产环境受限的排料工程师, I want 多 seed 从并发抢 CPU 改为**顺序满血执行** so that 每个 seed 真正收敛且统计上等价于并行 best-of-k。改造 `NestingPage.handleStart`：`multi_seed` 勾选时不再 for 循环并发 start，而是维护 seed 队列（base..base+k−1，k=parseSeedCount），在当前 run `onDone` 后发起下一个；portfolio 全程 outer phase 保持 running。R0：任一 frame `density ≥ target`（target 默认 0.90，可配）→ stop 当前 run、终止队列、phase=done；R4：队列耗尽 → phase=done。用户 handleStop 停止当前 run **并取消剩余队列**（phase=stopped 语义不变）。后端零改动（`/ws/solve` 单 seed 单连接协议原样）。
- **Acceptance Criteria**:
  1. 串行不变量：任一时刻至多 1 个 OPEN WS（单测断言：fake WS 记录 open 时机，run2 的 connect 不早于 run1 的 onDone）；现有 `stop()`（对所有 OPEN WS 发 stop）天然只命中当前 run，复用不改。
  2. R0 达标即停：mock 第 2 个 run 某 frame density ≥ 0.90 → 队列不再发起 run3，最终 phase=done（单测）。
  3. 全队列完成 / 用户停止 / 某 run error 三路径 phase 转换正确（沿用 US-027 五态：error 单 run → 整 portfolio 停止并入 error 态）。
  4. NestsGrid/ConvergenceCurve 对多 run 的既有渲染不回归（run 逐个 append，key=seed 稳定）。
  5. `npm run typecheck && npm run test && npm run build` 通过；新增调度器单测 ≥ 8 项（含并发多 seed 旧路径删除断言）。
- **Priority**: 2

### PS-003: kill 规则引擎 R1/R2/R3 + seed1 锚定 + shadow mode（默认只记不杀）
- **Description**: As a 追求最短达标时间的排料工程师, I want 必死 seed 被提前淘汰省出预算 so that 单位时间有效样本数与样本质量同时提升。新建 `src/lib/killRules.ts` 纯函数引擎 + portfolioStore 扩展（θ、killStreak、决策日志）。逐 frame 评估（τ=elapsed/time_budget，d=该 run best-so-far，I=incumbent.density，θ=kill 阈值初值=target）：
  - **R1 包络 kill**：seed 序号 > 1 且 τ > τ0 且 `d < S(τ) − m` 持续 W 秒 → kill（S=成功包络，来自标定参数；**无标定参数时 R1 整体禁用**）。
  - **R2 压缩期判决**：首帧 `phase === 'compressing'` 时 `d + uplift_q95 < max(θ, I + ε)` → kill（uplift 来自标定；无标定时用保守默认 0.005 且仅当 θ=90 一侧 binding）。
  - **R3 θ 衰减**：killStreak ≥ m_streak → `θ := I + δ`（只降 kill 门槛，**不改 R0 停止条件**——R0 恒用真 target 90%）。
  - **Seed 1 永不 kill**（锚定：保证交付下限 ≥ 现单 seed 模式 + 提供校准样本）。
  - **shadow mode 默认 ON**：决策只入日志（`{t, run, rule, d, τ, S(τ), θ, I, wouldKill}`）不发 stop；真 kill 由配置开关启用（默认 OFF，待 shadow 回测后打开）。
  - 保守默认：τ0=0.3、W=10s、m_margin=0.5pt、ε=0.1pt、δ=0.3pt、m_streak=3；参数可被 PS-006 的远端参数覆盖。
  - kill 动作 = 对当前 run 发既有 `{action:'stop'}`（后端零改动）。
- **Acceptance Criteria**:
  1. 纯函数引擎单测 ≥ 12 项：seed1 豁免 / R0 不受 θ 衰减影响 / R2 在压缩首帧判决 / R3 连杀触发衰减且只影响后续 kill 判据 / W 秒迟滞（瞬时下探不杀）/ 无标定参数时 R1 禁用。
  2. shadow 模式下不产生任何 `{action:'stop'}` 发送（fake WS 断言 send 调用为 0），日志条目完整。
  3. portfolioStore 新字段（θ/killStreak/log）随 reset 清零。
  4. 被 kill 的 run 仍走 US-027 `stopped` 路径：lastFrame 保留、incumbent 已入账的帧不丢（与 PS-001 联动单测）。
  5. `npm run typecheck && npm run test && npm run build` 通过。
- **Priority**: 3

### PS-004: incumbent 导出 + Portfolio HUD（最优徽章 / kill 日志 / shadow 下载）
- **Description**: As a 版师, I want 界面常驻显示全局最优密度与来源、并能导出该最优方案 so that kill/停止后拿到的永远是过程中的最好解。改造 `useExport`：导出优先 `portfolioStore.incumbent`（payload 的 `width_mm/density/placed` 取自 incumbent 帧与所属 run 的 `manifest.gate_mm`，`seed` 用 incumbent 来源 run），无 incumbent 时回退现行 `bestRun()` 路径（向后兼容单 seed）。新增 Portfolio HUD（ControlPanel 内克制区块）：incumbent 徽章（`最优 88.42% · seed 3`）+ portfolio 进度（`run 2/5`）+ kill 决策折叠列表 + shadow 日志一键下载 JSON（供 PS-007 回测校验误杀率）。
- **Acceptance Criteria**:
  1. 导出 payload 逐字段单测：incumbent 存在时 `placed = incumbent.placed_items`、`density = incumbent.density`、`width_mm = incumbent.width_mm`；被 kill run 的最优帧可导出（修复 finalDensity=0 盲区）。
  2. incumbent 为 null（未求解）时导出路径与现状字节级一致（回归 `useExport.test.tsx` 既有 15 项）。
  3. HUD 三态渲染：idle 隐藏 / running 显示进度与徽章 / done 显示终值；kill 日志按时间序列出（rule/时刻/当时 d 与阈值），shadow 条目带「未执行」标记。
  4. 通过浏览器验证排料渲染与导出（CDP 流程同 US-028：start → 中途 stop → 导出 PNG/DXF 成功且密度 = incumbent 而非 0）。
  5. `npm run typecheck && npm run test && npm run build` 通过。
- **Priority**: 4

### PS-005: 标定跑批 CLI（N seed × 短预算串行分布测量）
- **Description**: As as 算法工程师, I want 用生产同口径实例串行跑 N 个 seed 采集收敛轨迹 so that 经验分布/包络/ETT 决策不再拍脑袋。新建 `materialSorting-server/src/materialsorting/web/portfolio_calibration.py`（放 web 层：必须复用 `solver.build_instance` 保证与生产实例**同口径**——erode/tol/demand/strip_height 钳制全一致；复用 `sparrow_baseline.solve_with_progress` 采曲线）。CLI：`python -m materialsorting.web.portfolio_calibration --seeds 20 --time 60 --sizes 28,30 --out-tag m1787`。逐 seed 串行求解（单进程满血，绝不并发），产出 `out/portfolio_calibration/<tag>/`：`result_s{seed}.json`（含 placed_items）、`curve_s{seed}.json`（elapsed/phase/density/width 逐报告）、`summary.json`（每 seed 终值 density、best-frame density、time-to-best、收敛平台时刻、mean/σ/P(≥0.90)）。
- **Acceptance Criteria**:
  1. 串行执行（无任何时刻存在 2 个 solve 进程）；每 seed 的 instance 构造走 `build_instance`（允许 per_type/quantities 透传 CLI 参数）。
  2. summary.json 统计正确（对注入的 fake curve 单测：mean/σ/分位数/收敛时刻判定）。
  3. density 双口径：决策统计用 real 口径（`total_area/(width*gate)`），sparrow 口径仅记录。
  4. 中断安全：Ctrl-C 后已完成 seed 的产物落盘（逐 seed 写文件，不攒内存）。
  5. `python -m materialsorting.web.portfolio_calibration --help` 跑通；分层依赖未反向（web → engine 合规）；模块单测 ≥ 6 项。
- **Priority**: 5

### PS-006: 包络/uplift/秩相关标定 + controller_params 端点
- **Description**: As a 算法工程师, I want 从跑批曲线标定 controller 参数并下发给前端 so that kill 规则有数据依据。`portfolio_calibration.py` 加 `analyze` 子命令：读 `<tag>/curve_s*.json` → 计算成功包络 `S(τ)`（达标 seed 的 best-so-far 轨迹低位分位数，τ 网格 0.05~1.0 步长 0.05）、compression uplift 分布（`final − 探索末 best` 的 q50/q95）、短时/全时秩相关、train/test 划分误杀率回测 → 写 `out/portfolio_calibration/controller_params.json`（含 `calibrated: true` + τ0/W/margin/ε/δ/m_streak 推荐值）。后端新增 `GET /api/portfolio-params`：读该 JSON 返回（文件缺失/损坏 → 保守默认值 + `calibrated: false`，不 4xx）。前端新增 `usePortfolioParams` hook：mount fetch 一次 + 失败静默回退默认常量；PS-003 引擎参数改为「远端覆盖本地默认」。
- **Acceptance Criteria**:
  1. analyze 对 fake 曲线集的单测：包络单调性、uplift 分位数、达标/失败轨迹分离度（envelope gap）计算正确。
  2. train/test 回测输出误杀率字段（被杀 seed 中跑完可达标比例）；样本 < 10 条 seed 时 `calibrated: false` 拒绝下发（防小样本过拟合）。
  3. `curl /api/portfolio-params`：有标定文件返回完整 JSON；无文件返回默认值 + `calibrated:false`（两路径单测/路由测试）。
  4. 前端 hook 单测：成功覆盖默认 / fetch 失败回退 / 不阻塞渲染。
  5. `python -m materialsorting.web.portfolio_calibration analyze ...` 跑通；`npm run typecheck && npm run test && npm run build` 通过。
- **Priority**: 6

### PS-007: ETT 离线仿真器（策略网格回放 → 推荐参数档）
- **Description**: As a 算法工程师, I want 用历史轨迹离线回放比较不同 (B, k, kill 参数, δ, m) 策略的 ETT 与保底终值 so that controller 参数选型零真实求解成本。`portfolio_calibration.py` 加 `simulate` 子命令：输入曲线集 + 策略网格（单 seed 基线 / 均匀 best-of-k / kill 各档 / θ 衰减各档），回放仿真输出报告 `simulation_report.json` + 控制台表格：每策略 ETT（达标用时期望）、P(达标|预算内)、不可达场景 I 终值（截断轨迹用「kill 时刻 best + 条件期望增量」插值，增量分布来自全量曲线）。**同时消费 PS-004 的 shadow 日志**（`--shadow-log` 入参）：统计真实 would-kill 决策的假阳性。
- **Acceptance Criteria**:
  1. 仿真器对合成曲线（已知分布）输出的 ETT 排序符合理论（best-of-k < 单 seed；激进 kill < 保守 kill 当分离度大时）——单测固化。
  2. 截断插值有界：kill 时刻的 I 终值估计不低于该时刻 best-so-far（物理下界），单测覆盖。
  3. 报告含推荐参数档（ETT 最优且误杀率 < 5% 的策略），可被人工抄进 controller_params.json。
  4. `python -m ... portfolio_calibration simulate --help` 跑通；单测 ≥ 8 项。
- **Priority**: 7

### PS-008: 后端 solver_opts（exploration/compression 切分 + quadtree + workers 可配）
- **Description**: As a 算法工程师, I want spyrrow 的求解 config 旋钮（`exploration_time`/`compression_time` 切分、`quadtree_depth`、`num_workers`）可经 WS 透传 so that 重启动之间可做 config 轮换去相关。`build_instance` 加可选参数 `solver_opts: dict | None`：`exploration_pct`（0.1~0.95，换算 `total_computation_time` 为 exploration_time/compression_time 两段 int 秒，**与 total_computation_time 互斥传入 spyrrow**）、`quadtree_depth`（3/4/5）、`num_workers`（默认仍 4）；非法值 clamp + 忽略。`server.py ws_solve` 的 start 消息新增可选 `solver_opts` 字段 → `solve_params` 透传 → `solve_worker` → `build_instance`（全 JSON 可序列化，spawn 安全）。默认不传 = 现行行为字节级不变。
- **Acceptance Criteria**:
  1. `build_instance` 单测：不传 solver_opts 时 config 字段与现状一致；exploration_pct=0.6 → `exploration_time/compression_time` 换算正确（int 秒、和 ≈ time_budget）；越界值 clamp；quadtree_depth/num_workers 透传。
  2. WS 协议 additive：旧前端不传 `solver_opts` 行为不变；`agent-api-reference.md` 同步新增字段说明（文档同步 AC）。
  3. verify-api hook 对 server.py 的既有 404 误报按记忆忽略，以路由单测为准。
  4. `python -m materialsorting.web.server` 可启动、`python -c "from materialsorting.web.solver import build_instance"` 导入通过；分层未反向。
- **Priority**: 8

### PS-009: 前端 config 轮换接入 portfolio
- **Description**: As a 排料工程师, I want 串行 portfolio 的每次重启动自动轮换求解配置（seed × config 双维度）so that 样本去相关、上尾更易被摸到。`src/constants/portfolio.ts` 定义默认轮换池（如 `[{exploration_pct:0.8}, {exploration_pct:0.7}, {exploration_pct:0.9, quadtree_depth:3}, {}]`，默认档在列保证兼容）；PS-002 调度器发起 run i 时附 `solver_opts = pool[i % pool.length]`；ControlPanel 加「配置轮换」开关（默认 ON，OFF = 全部用默认档）。收敛曲线/图例沿用 run 序号着色（SEED_COLORS），HUD 的 run 行标注当前档位名。
- **Acceptance Criteria**:
  1. 单测：k=5、pool=4 时 run0..4 的 start payload `solver_opts` 序列 = pool[0..3]+pool[0]；开关 OFF 时全部 `{}`（即不传字段）。
  2. kill 规则与轮换正交：R1/R2 判据不依赖 config 档位（τ/d 量纲不变），既有 kill 单测全绿。
  3. ControlPanel 冻结语义：running 态轮换开关 disabled（沿用 US-027 disabled 透传模式）。
  4. `npm run typecheck && npm run test && npm run build` 通过。
- **Priority**: 9

### PS-010: LNS 波段重排核心模块（CLI 版，收敛解局部改进）
- **Description**: As a 算法工程师, I want 对 portfolio 最优布局做波段级 ruin-and-recreate so that 突破单 seed 收敛分布的上限。新建 `materialSorting-server/src/materialsorting/web/lns.py`（web 层：需 import `solver.build_instance` 构造**同口径**子实例 + `constraints.validate` 复检 + `sparrow_baseline._transform_polygon`；分层合规）。输入最优 run 的 result JSON（placed_items + pid_meta），算法：
  1. 按 x 轴切竖直波段（默认段宽 = 1.5 × gate，`--band-width` 可调）；
  2. 每段局部密度 = 段内片面积和 /（段宽 × NEST_GATE_MM），升序取最差段（可 `--band-idx` 指定）；
  3. 段内裁片（pid+完整 demand，多副本不变量：同 pid 全部副本一起重排）构造子实例，`solve_with_callback` 同款 ProgressQueue 短预算重解（`--time 30`）；
  4. 新段宽 < 原段宽 − ε → 接受：后续波段整体左移（splice），总宽缩短；否则拒绝；
  5. 循环 `--rounds N` 直到无段可改进或预算耗尽；结束 `constraints.validate` 全版复检 + 越界（y ≤ 1910）复检。
  CLI：`python -m materialsorting.web.lns --result out/.../result_s3.json --time 30 --rounds 5` → 输出 `*_lns.json` + 前后对比 SVG。
- **Acceptance Criteria**:
  1. 构造带人工空洞的 fixture 布局（单测）：LNS 一轮后总宽缩短 ≥ 空洞宽的 50%，全片仍在场（数量/demand 校验通过）。
  2. 子实例与母实例同口径：erode/tol/orientations/strip_height 钳制一致（单测断言子 `build_instance` 产出的 items 属性）；demand>1 的 pid 重排后副本数不变。
  3. 拒绝路径：子解不优于原段 → 布局逐字节不变（幂等安全）。
  4. `constraints.validate` 复检通过 + y 越界 0 片（防绘图仪撞机口径，PLOT_SAFE_MAX_Y_MM）。
  5. `python -m materialsorting.web.lns --help` 跑通；分层未反向（web → engine 单向）；单测 ≥ 10 项。
- **Priority**: 10

### PS-011: LNS 接入 WS + 前端后处理阶段 + 导出贯通
- **Description**: As a 版师, I want 求解完成后一键对最优方案跑 LNS 后处理并看到进度 so that 最后 0.5~1 个点的利用率缺口在产线内补齐。新增 WS 端点 `/ws/lns`（复用 US-025/026 进程化骨架：`solve_with_callback_proc` 跑波段循环，manifest→frame(每轮一段)→final；stop/断开 terminate 防孤儿）。前端：SolveControls done 态新增「优化布局」按钮 → 把 incumbent 的 placed_items POST/WS 给后端 → 进度帧驱动 NestSVG 更新 → 完成后 incumbent 被 LNS 结果入账（若更优）→ 导出自动使用。LNS 前后 density 对比展示在 HUD。
- **Acceptance Criteria**:
  1. `/ws/lns` 协议单测：start（含 placed + time + rounds）→ manifest → N×frame → final（或 error）；stop → `{type:'stopped'}` 终止子进程（沿用 read_loop/write_loop 模式，无孤儿）。
  2. LNS 不改进时 incumbent 不变（入账仍是严格大于才覆盖）；改进时 HUD/导出切换到新方案。
  3. 浏览器验证（CDP）：求解完成 → 点「优化布局」→ 布局帧更新 → 导出 DXF/PNG 为 LNS 后几何（抽查 placed 数与总宽）。
  4. `agent-api-reference.md` 新增端点文档；`ms-web` 启动冒烟通过。
  5. `npm run typecheck && npm run test && npm run build` 通过。
- **Priority**: 11

### PS-012: 生产 run 统计库 + θ₀ 按实例类校准
- **Description**: As a 算法工程师, I want 每次生产/实验 run 的结果自动沉淀为按实例类的统计 so that θ 初值按可达性校准（历史最高 89.6% 的组合不再从 90 起跑）、分布越测越准。后端：`ws_solve` 的 final/stopped 路径追加 JSONL `out/run_stats.jsonl`（`{ts, source, sizes, quantities_hash, params_hash, seed, solver_opts, final_density, best_frame_density, killed, elapsed, target_hit}`）；`/api/portfolio-params` 增强：按请求的实例类键（source+sizes+quantities_hash）查历史 → 有 ≥ 5 条记录时返回 `theta0 = min(0.90, 历史最大 best_frame_density + 0.003)`，否则 0.90。前端 PS-003 引擎的 θ 初值改读该字段。
- **Acceptance Criteria**:
  1. 连跑 2 次求解 → JSONL 恰好 2 行、字段完整（单测 fake final 路径）；stopped/kill 路径也落盘（killed 标记来自后端不可知 → 前端经 `stop` 后回传？**决策：v1 后端只记 stopped 原因，killed 归类由前端 HUD 下载的 shadow 日志承担，JSONL 不含 killed**——避免前后端状态穿透）。
  2. θ₀ 查询单测：类键命中且 ≥5 条 → theta0 = min(0.90, max+0.003)；样本不足 → 0.90；不同 sizes/quantities 类键隔离。
  3. 写盘失败不阻塞 WS 主流程（try/except + warning log）。
  4. `python -m materialsorting.web.server` 启动冒烟 + 路由单测通过。
- **Priority**: 12

## 功能需求 (Functional Requirements)

- FR-1: 串行 portfolio 模式取代并发 multi_seed（同一时刻至多 1 个求解进程满血运行）。
- FR-2: incumbent banking 不变量：每帧密度严格大于当前最优即入账；导出优先 incumbent。
- FR-3: R0~R4 控制规则：达标全停（恒用真 target）/ 双边包络 kill（含 seed1 锚定豁免）/ 压缩期判决 / θ 衰减（只影响 kill 不影响停止）/ 预算耗尽交付 incumbent。
- FR-4: kill 默认 shadow mode（只记不杀）；真 kill 需显式开关 + 标定参数就绪（`calibrated: true`）。
- FR-5: 标定管线三件套（batch/analyze/simulate）与生产实例严格同口径（build_instance 构造）。
- FR-6: solver_opts 透传（exploration_pct/quadtree_depth/num_workers），默认不传行为不变。
- FR-7: LNS 波段重排走同口径子实例 + constraints.validate + y≤1910 复检，拒绝不劣化。
- FR-8: 所有密度决策/显示用原面积口径 `density`（90% 生死线口径）；sparrow 口径仅参考。

## 非目标 (Non-Goals)

- 不改 spyrrow 源码、不做 warm-start/断点续跑（spyrrow 无该 API，架构约定禁改）。
- 不做后端无人值守 job runner / 多机分布式调度（v1 controller 在前端；后端化留待生产验证后）。
- 小件预合成（裤耳组合多边形）实验不在本 PRD（另立实验任务）。
- 不重构 `sparrow_baseline.py` 职责混合问题（已知问题 #1，不在本 PRD 扩大改动）。
- 并发 multi_seed 旧模式不保留切换开关（直接被串行取代；如需对比走 CLI）。

## 设计考虑 (Design Considerations)

- 版师向 UI 克制：Portfolio HUD 是折叠小区块；文案用「淘汰 / 保底最优」，不用 racing/kill 术语。
- incumbent 徽章常驻可见（运行中实时跳动），kill 日志默认折叠。
- LNS 进度复用 NestSVG 帧渲染，不新增画布。
- 串行模式下 NestsGrid 逐 run append，视觉与并发模式一致（用户无感知差异，仅时序不同）。

## 技术考虑 (Technical Considerations)

- 前端 kill = 复用既有 `{action:'stop'}` + US-026 terminate 链路，后端 P0' 阶段零改动。
- `solve_params` 全 JSON 可序列化（multiprocessing spawn 安全），`solver_opts` 走同通道。
- 标定/LNS 模块放 `web/` 层（需 import `solver.build_instance` 保生产同口径），分层 web → engine 单向合规。
- 子实例 demand 多副本不变量：同 pid 的 N 条 placement 必须整段进入同一波段重排（按 pid 聚合归属波段，禁止拆分副本）。
- 包络 S(τ) 等标定产物只存 `out/portfolio_calibration/`（gitignore），端点带保守默认值兜底，缺文件不崩。
- `early_termination`（spyrrow config）语义在本机用 PS-005 曲线实测一次并记录（影响重启动节奏，不阻塞任何 story）。
- ETT 仿真的截断插值必须物理有界（不低于 kill 时刻 best-so-far）。

## 成功指标 (Success Metrics)

- [ ] ETT 仿真报告：串行 portfolio + kill 相对单 seed 同预算达标时间下降 ≥ 40%。
- [ ] Shadow 回测误杀率 < 5%（PS-006 train/test + PS-007 shadow-log 统计）。
- [ ] 不可达场景仿真：I 终值 ≥ 单 seed 全预算收敛值 − 0.2pt。
- [ ] 真实 kill 启用后（shadow ≥ 2 周或 ≥ 50 run 之后）：生产达标 run 的平均耗时相对基线下降 ≥ 30%。
- [ ] 全部单测/typecheck/build 通过；后端模块 `python -m` 入口冒烟通过；分层依赖未反向。

## 待确认问题 (Open Questions)

- shadow mode 攒数据周期与真 kill 启用时点（建议：≥ 2 周生产轨迹或 ≥ 50 run，以 PS-007 回测误杀率 < 5% 为闸）。
- 真kill 开关位置：URL 参数 / ControlPanel 隐藏设置 / 构建常量（建议 ControlPanel 折叠高级项）。
- θ₀ 自动校准是否对「新款首次排料」禁用（无历史类键时回退 0.90，PS-012 已含，需确认产品语义）。
- LNS 波段宽默认 1.5×gate 是否合适（PS-010 实验后定，`--band-width` 可调）。
- R2 无标定时的默认 uplift 0.005 是否过保守（PS-006 出数后复核）。
