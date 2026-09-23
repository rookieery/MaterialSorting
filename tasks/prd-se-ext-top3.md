# PRD: SE 顺延多候选优化 —— 筛选近并列 seed top-3 串行顺延

## 概述 (Overview)

现行 SE 筛延（高级运行 `--strategy se` 与极限运行 SE 顺延臂共用同一条延长段）只取筛选密度**单冠军**顺延，而筛选名次对延长终值的相关性不完美（90s→180s 实测 ρ=0.786；1200s 档真冠军在筛选时只排第 3/15，见 [极限运行功能方案](../.docs/business/极限运行功能方案_race门杀.md) §2.3），近并列 seed 的延长后排序近乎抛硬币（uplift σ≈0.78pt，落后 0.3~0.5pt 的 seed 反超概率仍有 ~30%）。本 PRD 把延长段从单冠军升级为**近并列多候选**：筛选密度与冠军相差 ≤0.5pt 的 seed 一并顺延（至多 top-3，串行），用有界的额外时间买「真冠军被漏掉」的保险；最坏额外成本 = +2 轮延长（top-3 封顶恒定），UI 开跑前/筛选后两级提示额外时长。

**已定案的设计决策（2026-09-23 会话确认）**：① 阈值 0.5pt（密度 0.005，绝对百分点，对冠军度量，≤ 含等号）；② 超支设计——`se_plan`/k 筛选轮数不变，额外延长轮使总墙钟超出 `--time` 名义值，上限 2×(se_ext+2.5)s；③ schema 全 additive（`portfolio.se.champion` 保留、warm 单键语义保持冠军轮）；④ CLI 逃生口 `--se-ext-top N`（默认 3，`--se-ext-top 1` = 现行为，用于 A/B 哨兵）。

**贯穿全程的回归红线**：race / legacy 路径与无旗标 CLI 输出**逐字节不变**；R0 达标即停优先于延长段；warm 装载/回退矩阵零改动（多候选天然复用按 seed 参数化的装载点）；class_key 组成不变。

## 目标 (Goals)

- 覆盖已备案的冠军选中偏差：0.3~0.5pt 带内候选（按模型占全部「选错」事件约 1/3；1200s 档 rank-3 真冠军、600 档实测 #2/#3 落后 0.369/0.466pt 均在此带）全部纳入顺延。
- 成本有界且可预期：最坏 +2 轮延长（默认档 ~+6min / 极限 600 档 ~+20min / 1200 档 ~+40min），期望成本默认档 ~+66s（5336 分布模拟 0.36 轮）；UI 开跑前告知最坏、筛选后告知实际。
- 交付单调不降：多候选轮集合 ⊇ 单候选（冠军轮与旧行为逐字段一致）⇒ best 恒 ≥ 现行为，无需密度 A/B 门槛。
- 可观测先行：run_stats 沉淀 `se_ext` 段（候选数 / 逐 seed 筛选密度与间隔），作为未来阈值校准（收窄/放宽）的唯一数据面。

## 用户故事 (User Stories)

### US-001: 引擎层候选选择与多轮串行延长编排（portfolio.py）
- **Description**: As a 排料策略开发者, I want se 延长段从单冠军升级为「近并列候选串行逐个延长」的引擎编排（候选判据纯函数 + 常量 + 延长循环）, so that 筛选近并列的 seed 都获得完整延长预算，交付物自动取全局最优，且 race/legacy 与确定性语义零变化。
- **Acceptance Criteria**:
  1. 新常量 `SE_EXT_BAND = 0.005`（0.5pt，绝对百分点）/ `SE_EXT_TOP_N = 3`；新纯函数 `se_extension_candidates(solves, band, top_n) -> list[int]`：冠军 = solve 记录 `real_density` argmax（并列取先执行者，与现行口径连续）；候选 = 满足「冠军密度 − 该 seed 密度 ≤ band」的 seed，按密度降序稳定排序（并列按筛选执行序）取前 `top_n`；≥4 个落在带内时取最靠近的前 3（成本承诺不被击穿）；`top_n=1` 时恒返回 `[冠军]`。无 I/O 无 RNG。
  2. `run_serial_portfolio` 延长段改循环：候选按名次序**串行**逐个跑完整 `se_ext` 预算延长轮（队列序 = `len(seeds)+1` 起递增，`round_budget`/`make_progress` 既有 `i > se_k` 判定自然覆盖多轮）；每轮 warm 前置判定一次（`se_warm_plan`，cfg 级结论对全部候选一致），`warm_best_frame=True` 逐轮传递——装载点按 seed 参数化读各自 `best_frame_s{seed}.json`，**装载/校验/回退矩阵零改动**；回退 notify 逐轮各打一行。
  3. 控制器归档 additive：`se_champion`（argmax，语义不变）+ 新 `se_ext_seeds: list[int]`（实际顺延的候选全集，含冠军）+ `se_warm_states: list[dict]`（逐延长轮 `{seed, warm, reason}`；被中断轮无条目）；`portfolio_section()` se 段 additive 加 `ext_seeds`（`champion` 键保留）；`run_serial_portfolio` 返回值/`PortfolioRun` 结构不变。
  4. 中断/R0 语义不变：R0（`queue_stopped`）不进延长段；延长轮 Ctrl-C → `interrupted=True`、后续候选不再启动、已完成轮已入账 incumbent；每轮完成照常经 `on_seed_done` 回调（run_config 逐轮 flush result.json）。
  5. 测试（`tests/test_cli_strategy_wiring.py` 扩展，fake solve 注入）：候选判据矩阵（典型 3 候选 / 恰 2 候选 / 4+ 候选取前 3 / 全远超带 → 单冠军 / 密度并列含等号边界 0.005 / `top_n=1` 恒单冠军）；多轮串行序与预算（每候选各得 se_ext、队列序递增）；逐轮 warm 回退独立（一轮 no_best_frame 不影响他轮）；中断停在当前候选；race/legacy fake 注入路径与现测试逐字节一致（零回归哨兵）。
  6. Python 模块导入检查通过（`materialsorting.cli.portfolio`），分层依赖未反向（portfolio 不 import web）。
- **Priority**: 1

### US-002: CLI 旗标 + strategy.json / result / run_stats 可观测（run_config.py）
- **Description**: As a CLI 策略使用者, I want `--se-ext-top` 旗标与开跑即知的计划/实际可观测键, so that 我能预知最坏额外时长、事后能从产物审计候选集合与逐轮 warm 状态，且 `--se-ext-top 1` 可精确退回旧行为做 A/B。
- **Acceptance Criteria**:
  1. `--se-ext-top N`（int ≥1，默认 3）：须与 `--strategy se` 同给（单独给出 = 笔误退出 1，值域外退出 1，均在 `new_run_dir` 前拦下）；与 `--extreme` 显式同给退出 1（糖衣互斥——极限 SE 臂继承默认 3，展开处不写该旗标）；旗标缺省时 se 调用形与 US-001 默认行为一致。
  2. 启动行（`--quiet` 也打，同策略模式口径）：se 段附「筛选密度与冠军相差 ≤0.5pt 的 seed 一并顺延（至多 top N 个），最多多花 2×{se_ext}s」；延长轮头按候选序打印 `── 延长轮（seed=X·筛选冠军）── / ── 延长轮（seed=Y·候选 2/3）── …`。
  3. `strategy.json` se 段 additive：开跑即写计划态 `ext_top_n` / `ext_band`（0.005）；**首个延长轮启动时**（`on_seed_start` 检测 se 延长轮）单写者补写实际态 `ext_seeds`（候选全集）+ `extra_rounds`（m−1）——不进延长（R0/中断）不补写，文件保持计划态；`_parse_plan` 读侧每次轮询重读，additive 键无兼容问题。
  4. result.json：`portfolio.se.ext_seeds`（US-001）+ config `strategy` 段 additive `ext_top_n` 与 `ext_warm_rounds: [{seed, warm, reason}]`（逐延长轮）；既有 `warm` / `warm_reason` 键语义 = 冠军轮（第 1 延长轮）实际灌入态，历史语义连续（m=1 时两键即全量信息）。
  5. run_stats 行 config 段 additive `se_ext` 段（自包含校准数据面）：`{'top_n', 'band', 'candidates': [{'seed', 'screen_density', 'gap_pt'}]}`；class_key 组成不变；race/legacy 行零新增键。
  6. 测试（`tests/test_cli_strategy.py` / `test_cli_run_config.py` 扩展）：旗标裁决矩阵（从属/值域/糖衣互斥）；`--se-ext-top 1` 与旧行为输出对拍哨兵；strategy.json 计划态/补写时机；result/run_stats additive 键形态；无旗标 se 与 race 的行结构对拍零回归。
  7. `ms-run-config --help` 展示新旗标；Python 模块导入检查通过。
- **Priority**: 2

### US-003: web 状态面透传（strategy.py）
- **Description**: As a 前端进度面, I want `/api/strategy/status` 与 `/api/extreme/status` 透传多候选计划/实际态, so that 前端能展示实际候选数、额外时长与多条延长事件，旧 run（无新键）渲染零变化。
- **Acceptance Criteria**:
  1. `_parse_plan` additive 透传 strategy.json se 段新键（`ext_top_n` / `ext_band` / `ext_seeds` / `extra_rounds`，在场才加键）；status 载荷随 plan 摘要透传，前端可用 `ext_s` × `extra_rounds` 计算实际额外秒数。
  2. `_parse_events` 多延长事件核验：多候选产物 `best_frame_s{seed}_ext.json` 按 seed 天然多文件，既有 glob + 尾窗豁免逻辑产出多条 extension 事件（顺序稳定）；补测试锁定 3 候选场景的事件序列与豁免行为。
  3. status 响应结构 additive（新键在场才加），race / 旧 se run / legacy 读路径零变化；机器对接三端点（`gate=False` 家族）经同一 `_status_common` 参数化自动继承，零额外改动。
  4. 测试（`tests/test_web_strategy.py` 扩展）：带 `ext_seeds` 的 strategy.json 解析 / 多 `_ext` 边车事件序列 / 无新键旧产物结构不变。
  5. Python 模块导入检查通过（`materialsorting.web.strategy`），分层依赖未反向（对 server 依赖函数内延迟 import 惯例保持）。
- **Priority**: 3

### US-004: 前端提示与多候选进度（types + 双 Modal）
- **Description**: As a 工作台用户, I want 高级运行 / 极限运行弹窗在开跑前告知多候选顺延的最坏额外时长、跑动中展示实际候选数与逐候选延长进度, so that 我对「会多出多少时间」有明确预期，并能看清每个近并列 seed 的延长表现。
- **Acceptance Criteria**:
  1. `types/strategy.ts` additive：`StrategyPlan` 加 `ext_top_n?` / `ext_band?` / `ext_seeds?` / `extra_rounds?`（可空，旧 run 缺键隐藏相关 UI）。
  2. 提交前文案：StrategyRunModal（se 模式）与 ExtremeRunModal（SE 顺延臂）的描述行/参数区加一句：「筛选密度与冠军相差 ≤0.5pt 的 seed 会一并顺延（至多 3 个），最多多花 2×延长时长（高级运行 ~6 分钟 / 极限 600 档 ~20 分钟 / 1200 档 ~40 分钟）」——具体分钟数按当前档位动态计算，不写死文案。
  3. 进度面：SE chips 从单条延长条目扩展为 m 条（「延长·冠军 seed X」「延长·候选 2」「延长·候选 3」，进行中 ● / 完成 ✓ / 待定，候选 seed 来自 `ext_seeds` + extension 事件 + `current.ext` 既有三源）；阶段行在延长期显示「延长中 · 候选 i/m（seed X）」；`extra_rounds` 在场时阶段区附「预计多花 ~N 分钟」实际值行。
  4. vitest：`__tests__/StrategyRunModal.test.tsx` / `ExtremeRunModal.test.tsx` 扩展——mock status 带 `ext_seeds`/多条 extension 事件的 chips 与阶段行断言、无新键旧载荷回归、提交前文案断言（含按档位动态分钟数）。
  5. 浏览器验证（dev 模式真页面）：se 弹窗文案可见 + 短预算 se 真跑（后端起真求解）延长阶段渲染正常；`npm run build` 通过。
- **Priority**: 4

### US-005: 端到端验收与文档收官
- **Description**: As a 排料策略维护者, I want 真跑证明多候选触发与产物正确性、`--se-ext-top 1` 哨兵锁定旧行为、全量回归与文档收官, so that 合入有实测背书、阈值 0.5pt 的实际触发率进入 se_ext 观测面供后续校准。
- **Acceptance Criteria**:
  1. 多候选真跑：5336 同款配置 `--strategy se --time 600`（或 web_e791f2 同源 intermediate）真跑出 m≥2 的一单——验证候选串行执行（延长轮头/strategy.json `ext_seeds`）、各候选 `curve_s{seed}_ext.json` / `best_frame_s{seed}_ext.json` 独立成对、best = 全部延长轮帧级最大（`portfolio.incumbent.seed` ∈ 候选集）、run_stats 行 `se_ext` 段与 result 逐键一致；若该单未触发（m=1），换 seeds/intermediate 直至触发至少一单（近并列在 5336 族实测可复现：web_e791f2 差 0.237/0.251pt）。
  2. 哨兵对拍：同配置 `--se-ext-top 1` 与合入前代码背靠背（或 stash 对照）输出/产物结构一致（既有 num_workers=4 帧漂移口径豁免；`ext_top_n: 1` additive 键允许差异）。
  3. 极限 SE 臂冒烟：`--extreme --extreme-strategy se --time 960` 最小档跑通（继承默认 top-3；warm 组合视角/band·prefix 场景任选其一覆盖）；UI 冒烟脚本 `materialSorting-web/scripts/smoke-extreme-run.mjs` 复跑通过（若其断言涉及 se 阶段行/文案则同步更新）。
  4. 全量回归：pytest 全量 + vitest 全量全绿；`--strategy race` / 无旗标 CLI 冒烟输出逐字节对拍。
  5. 文档收官：`CLAUDE.md` 运行方式 se 段 + `README.md`「配置驱动求解」se 段补多候选语义与 `--se-ext-top`；`.docs/technical/agent-file-map.md` portfolio/run_config/strategy 行注记；`.docs/technical/agent-api-reference.md` strategy status 键表补 additive 新键；极限方案文档 v1.2 §6 增补多候选注记（标注 2026-09-23 定案：0.5pt/top-3/超支设计）。
  6. 验证命令与实测数据（触发单的 m、间隔、是否反超）记入本 PRD 附带验证速查表（对齐 warm-start PRD 惯例）；模块导入/入口检查通过。
- **Priority**: 5

## 功能需求 (Functional Requirements)

- FR-1: 候选判据（单一真相源 = `se_extension_candidates` 纯函数）：冠军 = solve 记录 `real_density`（物理口径）argmax；候选 = 冠军密度 − seed 密度 ≤ `SE_EXT_BAND`(0.005)，密度降序稳定排序（并列按筛选执行序）取前 `SE_EXT_TOP_N`(3)；`top_n=1` 恒单冠军。
- FR-2: 延长执行：候选按名次序串行，每候选独立完整 `se_ext` 预算延长轮；warm 逐轮各自加载自己 `best_frame_s{seed}.json`（装载点零改动），回退矩阵逐轮独立生效；产物 `*_ext` 按 seed 无冲突。
- FR-3: 预算语义 = 超支设计：`se_plan` / k 筛选轮数 / `--time` 规划锚全不变；实际总时长 = 名义 + (m−1)×(`se_ext`+2.5)s，上限 +2 轮；UI 两级提示（开跑前最坏 / 筛选后实际）。
- FR-4: `--se-ext-top N`（默认 3，int ≥1，须与 `--strategy se` 同给，与 `--extreme` 互斥）；web start 载荷不加开关（默认即新行为）。
- FR-5: additive 可观测：strategy.json（计划态 `ext_top_n`/`ext_band` + 延长启动补写 `ext_seeds`/`extra_rounds`，单写者）、result.json（`portfolio.se.ext_seeds` + config.strategy `ext_top_n`/`ext_warm_rounds`，`warm`/`warm_reason` 保持冠军轮语义）、run_stats（config 段 `se_ext` = `{top_n, band, candidates:[{seed, screen_density, gap_pt}]}` 自包含校准数据面）；class_key 不变。
- FR-6: 交付语义：best/incumbent = 全部延长轮帧级全局最优（既有 incumbent banking 零新逻辑）；多候选轮集合 ⊇ 单候选 ⇒ best 单调不降。
- FR-7: 回归红线：race / legacy 路径与无旗标 CLI/result/run_stats 逐字节不变；R0 达标即停优先（不进延长）；Ctrl-C 交付已完成轮、后续候选不启动；band/prefix warm 组合视角机制与 WS 求解路径零改动。

## 非目标 (Non-Goals)

- 并行延长（串行定案——三臂并行 CPU 争抢截断墙钟预算的前车之鉴；单机任一时刻至多 1 个求解进程的既有约束保持）。
- band 阈值旗标化（`SE_EXT_BAND` 常量；重标定走 se_ext 观测数据 + 改常量一行，不进 CLI/web 面）。
- 预留式预算（用减少筛选轮换额外延长——k 不变，保「右尾靠加 seed 挖」）。
- 延长轮中途早停优化（某候选已反超即跳过后续——不做了，跑满 m 个使时间承诺确定、行为可预期）。
- warm 装载/校验/回退矩阵本身任何改动；race 门杀 / kill 引擎 / LNS 任何改动。
- web `/api/strategy/start`·`/api/extreme/start` 载荷新增开关或参数。

## 设计考虑 (Design Considerations)

- UI 提示数值按档位动态计算（ext_s × 2 / 60 分钟化），禁止三处硬编码文案漂移；旧 run（strategy.json 无新键）前端相关 UI 自然隐藏。
- 候选 chips 与「候选 i/m」阶段行复用既有三源（ext_seeds / extension 事件 / current.ext）推导冠军的既有模式，multi 只是条目数泛化。
- 观测先行：se_ext 段设计为自包含（不带 per_seed join 也能算间隔分布），是 0.5pt 阈值下一轮校准的唯一依据。
- 阈值依据与诚实声明入档：0.3→0.5 的调整基于 5336 族数据（模型反超概率 0.3~0.5pt 带 ~30-35%、三真实 run 间隔实测、1200s 档 rank-3 真冠军），样本量有限（配对 n=8、真 SE run 各 1 例），极端密集实例上 0.5pt 可能常态触发满额（+20/40min）——靠 se_ext 观测 1~2 周后回看裁决是否收窄。

## 技术考虑 (Technical Considerations)

- 候选数据源口径 = solve 记录 `real_density`（与现行冠军 argmax 同口径连续；跑满筛选轮终解 = solver incumbent，与帧级 best 实践一致）。
- 确定性：稳定排序 + 名次序延长，全程无 RNG；跨会话 num_workers=4 并行 merge 帧漂移沿用既有备案口径（构造层恒确定）。
- warm 逐轮独立性：`_load_warm_payload` 按 seed 参数化（读该 seed 自己的边车）、worker 宇宙复检按轮独立——一个候选边车损坏只降级该轮。
- 事件面兼容：`_parse_events` 已按 glob 多文件解析 `best_frame_s*_ext.json` 且延长事件豁免尾窗裁剪，多候选零结构变更（补测试锁定即可）。
- strategy.json 单写者中途补写：同一 run_config 进程在首个延长轮 `on_seed_start` 时重写（plan 键原样保留 + additive 实际态键），读侧 `_parse_plan` 每次轮询重读，无并发写。
- 单调性论证（免 A/B 门槛的依据）：候选[0] ≡ 现行冠军（同 seed/预算/warm 输入），后续候选只向 incumbent 增加帧来源 ⇒ best ≥ 现行为恒成立；质量面唯一成本是时间。
- Windows spawn：无新跨进程形态（无新 Process 参数）。

## 成功指标 (Success Metrics)

- [ ] pytest 全量全绿（test_cli_strategy_wiring / test_cli_strategy / test_cli_run_config / test_web_strategy 扩展），vitest 全量全绿（双 Modal 测试扩展）。
- [ ] 至少一单真跑 m≥2：候选串行延长、产物独立成对、best = 全局最大、run_stats `se_ext` 段正确落档。
- [ ] `--se-ext-top 1` 哨兵：与旧行为输出/产物对拍一致（num_workers=4 漂移口径豁免）。
- [ ] race / legacy / 无旗标 CLI 输出与 result/run_stats 行结构逐字节零回归。
- [ ] 高级运行 + 极限 SE 臂两场景：开跑前最坏额外提示与筛选后实际候选展示在浏览器可见。

## 待确认问题 (Open Questions)

- 0.5pt 在极端密集实例的常态触发成本（极限档 +20/40min 高频出现）是否可接受？——**已决议（2026-09-23 用户确认）：可接受，按现方案合入**；se_ext 观测积累 1~2 周后回看，必要时收窄 band（改常量 + 更新 UI 文案数字）。

## 已决议事项（2026-09-23 用户确认）

- `se_ext.candidates` **不带**「该候选延长终值/是否反超」冗余字段——由 per_seed `phase='extension'` + `incumbent.seed` join 得出，保持自包含到「筛选密度 + 间隔」深度为止。
- UI 冒烟**不新增专项脚本**——复用 `smoke-extreme-run.mjs` 扩展断言（US-005 执行时视脚本结构落地）。

---

## 验证速查（US-005 端到端验收执行记录，2026-09-23）

> 环境：`py -3`（Python 3.11）= spyrrow `0.9.0+ms1`（warm 支持开）；对拍旧代码 = `git worktree` @ `5328293`（合入前最后一版）+ `PYTHONPATH` 指向 worktree src；对拍配置 `data/configs/5336_qty1_gate1750.json`（5336 coded 母版、码 30-40 ×1、gate 1750、seeds [0]→种子流 [0,1,2,3]，复刻 web_2538fb 同款 = US-004 浏览器验证触发单）。
> 归一化豁免口径：run_dir 绝对路径/时间戳、末行耗时小数、逐帧 elapsed 墙钟小数（密度与宽度逐帧不变）；se 启动行多候选附注（US-002 additive 呈现层）。

| # | 验证项 | 命令 | 判据 / 结果 |
|---|--------|------|------------|
| 1 | 多候选真跑 m≥2 | `ms-run-config data/configs/5336_qty1_gate1750.json --strategy se --time 600 --name us005_se_top3_e2e` | **m=2 触发**：筛选 88.525(seed1 冠军)/88.421(seed2)/87.775/84.74 —— seed2 间隔 **0.104pt** ≤0.5pt 入带（seed0 0.75pt 出带）；延长轮头「筛选冠军」「候选 2/2」各一行、strategy.json `ext_seeds:[1,2]`/`extra_rounds:1`；`curve/best_frame_s{1,2}_ext.json` 独立成对；best = seed1 frame13 **88.7211%** = 两延长曲线帧级最大（seed2 ext 峰 88.7080%，**未反超**、差 0.013pt），`incumbent.seed=1 ∈ [1,2]`；warm 两轮真顺延（`ext_warm_rounds` 全 true、零回退行）；run_stats 行 `se_ext={top_n:3,band:0.005,candidates:[{1,0.88525,0.0},{2,0.884207,0.104}]}` 与 result 逐键一致；elapsed 606.8s（延长轮早停收敛，未超名义）✓ |
| 2 | `--se-ext-top 1` 哨兵（新代码） | 同配置 `--se-ext-top 1 --name us005_sentinel_top1` | **m=1**：`ext_seeds:[1]`/`extra_rounds:0`（seed2 0.104pt 入带仍不延长）；best 88.7211% seed1 frame13 与多候选单**全等**（单调不降实证）✓ |
| 3 | 哨兵背靠背（vs 合入前 5328293） | worktree 同配置 `--strategy se --time 600 --name us005_sentinel_old` | stdout 681 行归一化**逐字节全等**（本对零帧漂移 —— 密度/宽度逐帧相同，无需动用 num_workers 豁免）；strategy.json 旧键（mode/total_budget/planned_seeds/se 四键）全等 + 新键 4 additive（ext_top_n/ext_band/ext_seeds/extra_rounds）；result.solve 五轮（4 筛+1 延）seed/密度/片数/宽度全等、best 四元组全等、portfolio 顶层零新键、portfolio.se 旧键全等 + `ext_seeds:[1]` additive、config.strategy 旧键全等 + `ext_top_n`/`ext_warm_rounds` additive；旧代码 run_stats 行零 se_ext ✓ |
| 4 | 极限 SE 臂（band 组合视角 warm 场景） | `ms-run-config data/configs/5336_band_g05_gate1750.json --extreme --extreme-strategy se --time 960 --name us005_extreme_se_band` | 糖衣展开 `--strategy se --se-screen 300 --se-extend 600` + EXTREME_SOLVER_OPTS（p0.7/et0/w4 回显）；strategy.json 计划态 `ext_top_n:3`/`ext_band:0.005`（**默认 top-3 继承**）→ 延长启动补写 `ext_seeds:[0]`/`extra_rounds:0`（k=1 恒单冠军）；band g05 开 → 延长轮 warm 走组合视角边车（`ext_warm_rounds:[{0,warm:true}]`、零回退行）；best 89.22%（seed0 frame159、110 片、6733mm）；run_stats 行 `extreme:{budget:600,strategy:'se'}` + `se_ext` 落键 + warm:true，elapsed 909.2s；exit 0 ✓ |
| 5 | UI 冒烟复跑 | `materialSorting-web/scripts/smoke-extreme-run.mjs`（ms-web :8010 prod static） | 断言不涉 se 阶段行/文案（默认 race 臂）→ **零改动直接复跑**；1 commit ok（110 裁片）/2 预设轮数 19·9·40 全对拍/3 极限运行标题+徽标/4 首帧 80.39% → stopped 终态保留最优，SMOKE DONE ✓ |
| 6 | pytest 全量 | `cd materialSorting-server && py -3 -m pytest -q` | **1156 passed**（首轮 1154+2 = test_cli_strategy replay 两例负载敏感 flake，progress §57 已备案同款 —— 隔离重跑 21/21 绿 + 全量二轮全绿 141s，代码零改动非本 Story 引入）✓ |
| 7 | vitest 全量 | `cd materialSorting-web && npx vitest run` | **1236 passed**（71 files，10s）零回归 ✓ |
| 8 | race / 无旗标 CLI 对拍 | 无旗标 `--time 5` + `--strategy --time 13 --race-budget 5`，新旧背靠背 | 无旗标：stdout 148 行归一化**逐字节全等**（全帧密度/宽度零差异）；race：末行汇总/best 86.29%/用布 7584mm/片数/kill 判定 2 条全等，seed1 门段 3 行帧漂移（num_workers 并行 merge 序豁免口径，终值不受扰）；run_stats 四行（无旗标+race × 新旧）键集与 config 键集**逐字节同构**（零 se_ext / 零新键）、best 0.862949 四行全等 ✓ |
| 9 | 模块导入/入口 | `py -3 -c "import materialsorting"` / `python -m materialsorting.cli.run_config --help`（含 `--se-ext-top`） | ✓ |

- 观测面首批数据：m=2 触发单的 se_ext 段已落 `out/run_stats.jsonl`（class_key `45581e6772`）；5336 族 90s 筛选 top-2 间隔实测 0.104pt（本单）/0.237·0.251pt（web_e791f2 族 1200 档），0.5pt 带内触发属常态预期。
