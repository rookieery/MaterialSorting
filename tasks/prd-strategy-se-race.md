# PRD: 求解策略双模式（SE 筛延 / race 门杀）+ web 高级运行弹窗

## 概述 (Overview)

把「给定总预算拿更高利用率」落地为 `ms-run-config` 的策略双模式：**方案 B（race 门杀，默认）**——每 seed 带 180s 预算启动、90s 门处严格破纪录才续跑（真 terminate + best-so-far 交付）；**方案 A（SE 筛延）**——k×90s 串行筛选 + 冠军 seed 全新 180s run。两模式四重证据下期望等价（离线同 fork / 跨 fork 诚实 / 冠军 fork 探针 / 现场对跑 88.38%=88.38% 精确平），且同预算确定性重放（同 seed+同 time_budget 逐帧一致）从机制上保证等价：SE 的延长 = 冠军 180s 潜力的零方差求值。20min 起两模式比均分 90s 稳定 +0.2pt 量级（30min/1h 达宇宙天花板）。

在此之上，把双模式能力接入 **web 超排界面「高级运行」弹窗**：版师无需命令行，选时长（10/20/30/60min）+ 模式（SE顺延/race门杀）即可后台跑策略 run，弹窗展示利用率进度（不渲染排料过程），终局展示最优方案并一键**应用到主画布**（复用现有 PNG/DXF/PLT 导出链路）。桥接方式 = web 后端 spawn `ms-run-config --strategy` 子进程 + HTTP 轮询 run_dir 产物（分层零违规：进程边界而非 import 边界；判据逻辑单一真相源留在 cli，零漂移）。

## 目标 (Goals)

- `--strategy` 一旗双模式：默认 race（方案 B）、`--strategy se` 选方案 A；20min+ 预算交付期望 ≥ 均分 k×90s +0.15pt（fixture 回放回归固化）
- 决策全程可审计：race 门杀逐笔落 `kill_decisions.jsonl`（rule=R5_race_gate）；SE 两段结构（筛选明细 + 冠军 + 延长）落 result.json
- 零回归：无 `--strategy` 旗标时行为与 result.json 逐字节一致；simulate 网格纳入双档，换实例类可离线重标
- web 高级运行端到端：弹窗选时长/模式 → spawn 子进程跑策略 → HTTP 轮询展示进度五件套 → 最优结果展示 + 应用到主画布 → 现有导出链路零改动可用；**`/ws/solve` 协议与普通求解流程零改动**

## 数据依据（2026-08-20 四重证据链，均 5336 实例）

**离线对决（跨 fork 诚实口径：筛选读 90s 预算曲线、延长/续跑读 300s 预算曲线 180s 帧，8 配对 seed、bootstrap 3000）：**

| 档位 | 均分 k×90s | 方案A: SE延180 | 方案B: race180（破纪录门） |
|---|---|---|---|
| 10min | 86.32% | 86.33% | 86.40% |
| 20min | 86.80% | 87.01% | 87.05% |
| 30min | 86.94% | 87.18% | 87.16% |
| 1h | 87.00% | 87.22% | 87.22% |

10min 档三法打平（噪声内），20min+ 双模式 +0.2pt 量级 → 不设 auto 阈值，四档全支持两模式。

**现场对跑（live_duel_ab，共享 fresh seed 序列 Random(2026)、同一 commit、各 1200s 名义预算）：A=B=88.38% 精确平**（冠军 seed221：A 筛选 87.63 → 延长 88.38；B 门值 87.99 → 续跑 88.38，后续 11 seed 全部门杀且事后全部正确）。最优帧 88.41%（172s 处，两臂相同）。

**确定性重放（关键机制事实）**：同 seed + 同 time_budget 重跑逐帧一致（seed221 两次 180s run 2177 帧零分叉、布局 sha1 相同；seed2×3 六位小数全同）。此前「fork 分叉 30-60s / ρ=0.67」实为**跨预算调度差异**（90s vs 300s 预算的搜索日程不同）。推论：① 同预算重跑同一 seed 零信息增益（种子流禁重复）；② SE 冠军延长用**不同预算**（180 vs 筛选 90）才产生新信息——这正是 SE 有效的原因；③ race「免重掷优势」不存在，两模式交付同值有机制保证。

**延长 180s 的依据**：冠军类曲线 120~180s 进平台（求解器均值 ~185s 收敛；180s 预算 run 与 300s 预算曲线 180s 帧差仅 ~0.03pt）；再砍到 120s 开始亏（冠军 120→180 仍有真实爬升）。

## 用户故事 (User Stories)

### US-001: 策略判据纯函数、种子流与曲线回放回归
- **Description**: As a 排料引擎开发者, I want 策略模式判据以纯函数族实现并用配对曲线集固化回放结果, so that 双模式行为可单测、离线收益有回归护栏。
- **Acceptance Criteria**:
  1. `materialSorting-server/src/materialsorting/cli/portfolio.py` 新增纯函数族（无 I/O、无进程）：`R5_REASON='R5_race_gate'`；`RACE_BUDGET_S=180` / `RACE_GATE_TAU=0.5` / `SE_SCREEN_S=90` / `SE_EXT_S=180` / `SEED_UNIT_S=92.5` / `FULL_UNIT_S=182.5` 常量；`strategy_seed_stream(cfg_seeds, n)` 种子流（先消费 config seeds，不足按 max+1 递增补齐，**保证无重复**——同预算重跑同 seed 是纯浪费）；`race_gate_seconds(budget, tau)`；`decide_race_kill(best_so_far, elapsed, state)` 门帧（首帧 elapsed ≥ gate_seconds）处 `best_so_far <= bar` 即判杀（**严格破纪录才续跑**，首 seed 无条件豁免），bar = 历史所有 seed 门值最大值（含被杀者）；`se_plan(total_budget, screen_s, ext_s)` → `(k, ext_s)`，k=max(1, (T−FULL_UNIT)//SEED_UNIT)，T < FULL_UNIT+SEED_UNIT 视为预算不足。返回决策 dict 与 kill_decisions 行同构。
  2. 新增 `materialSorting-server/tests/fixtures/strategy_curves_8.json`：8 配对 seed 降采样曲线（b90s/b180f 按实测嵌入：84.27/84.39、83.78/83.82、86.35/86.90、83.52/83.81、87.00/87.22、84.00/85.72、83.74/84.84、83.57/84.26——**筛选与延长是不同 fork**，如实保留跨 fork 结构）。
  3. 新增 `materialSorting-server/tests/test_cli_strategy.py` 判据部分单测 ≥ 14 例：门帧边界（首帧恰 ≥ / < gate_seconds）、`<=` 判杀边界（等于 bar 杀、破纪录放行）、首 seed 豁免、bar 含被杀者门值、门后不再判（每 seed 至多一笔）、种子流补齐与无重复、se_plan 算术与预算不足分支、race 重放中同 seed 永不二次续跑（确定性重放 + 严格破纪录的联合性质）。
  4. 回放回归（同文件）：fixture + 固定 bootstrap seed 重放 uniform90 / SE / race，断言 T=1200 与 T=3600 两模式 − uniform90 ≥ +0.1pt、T=3600 漏 max 率 ≤ 5%（漏 max = 交付 < 采样 seed 全程 max 占比）；回放器放测试内或 portfolio 纯函数，不依赖 out/ 标定产物。
  5. `python -m materialsorting.cli.portfolio` 导入冒烟零副作用 + pytest 全绿 + 分层未反向。
- **Priority**: 1

### US-002: 双模式接线、CLI 旗标与真实冒烟
- **Description**: As a 生产使用者, I want `ms-run-config --strategy` 一条命令按总预算跑双模式, so that 20 分钟以上预算自动拿到比均分更高的利用率。
- **Acceptance Criteria**:
  1. `materialSorting-server/src/materialsorting/cli/run_config.py` 新旗标：`--strategy [se|race]`（nargs='?' const='race' default=None；**裸旗标 = race = 方案 B（默认）**，`--strategy se` = 方案 A，choices 外退出 1）；`--time N` 在策略模式 = **总预算秒数且必填**（缺省退出 1，错误信息明示「策略模式需 --time 总预算」）；`--se-screen N`（默认 90）、`--se-extend N`（默认 180）、`--race-budget N`（默认 180）、`--race-gate TAU`（默认 0.5，(0,1) 开区间）。
  2. `materialSorting-server/src/materialsorting/cli/portfolio.py`：`PortfolioController` 加 mode（'legacy'|'race'|'se'）。策略模式下：R1/R2 不评估、θ 不维护；种子流 = `strategy_seed_stream(cfg.seeds, ...)`；名义预算记账 92.5/182.5，start 条件 spent+92.5 ≤ T。**race**：每 seed `solve_pieces(time_budget=race_budget)` + `make_should_stop` 接 US-001 判据（判杀返回 R5_REASON，走既有 terminate 链路交付 best-so-far），门杀行 `--quiet` 也打；**se**：阶段 1 k×`--se-screen` 串行求解，阶段 2 冠军（argmax real_density）以 `--se-extend` 预算再跑一轮，延长轮产物写 `curve_s{seed}_ext.json` / `best_frame_s{seed}_ext.json`（防覆盖筛选产物），solve 数组延长条目加 `phase:'extension'`。两模式被杀/被筛 seed 最优帧照常入 incumbent。
  3. 互斥与共存：`--strategy` 与 `--kill` 显式同给 → 退出 1；与 `--target` 共存（R0 达标即停仍生效，优先于模式继续）；与 `--lns` / `--solver-opts` / `--rotate-opts` 兼容透传。race 决策逐条写 `run_dir/kill_decisions.jsonl`（复用 schema，`S_tau` 填 bar 参照值、`theta` 填 null，README 注明重载）。预算不足（T < 最小配置）退出 1。
  4. result.json：`portfolio` 段新增 `mode` 字段 + 模式子段：race `{gate_seconds, kept_seeds, gated_seeds}` / se `{k_screens, screen_s, ext_s, champion}`；无 `--strategy` 时与现版输出逐字节一致（对拍单测）。
  5. **R1 增量（US-004 web 桥接前置）**：策略模式下，`run_config.py` 在 commit 完成后、首轮求解开始前向 run_dir 写 `strategy.json`：`{mode, total_budget, planned_seeds:[...], race:{gate_seconds} | se:{k_screens, screen_s, ext_s}, started_at}`——run 一启动即暴露模式/计划轮数/种子流（result.json 要等首个 seed 完成才首次落盘，race 默认下前 ~180s 无信息）。
  6. 真实冒烟（~10min 机时）：`--strategy --time 240 --race-budget 60 --race-gate 0.5` → ≥1 seed 于 ~30s 被门杀（kill_reason=R5_race_gate、决策行在场、被杀 best 入 incumbent）rc=0；`--strategy se --time 300 --se-screen 30 --se-extend 60` → 阶段 1 k 个 30s 筛选 + 1 个 60s 延长（`_ext` 产物在场、incumbent ≥ max 筛选值）rc=0。
  7. `python -m materialsorting.cli.run_config --help` 含新旗标 + pytest 全绿 + AST 分层零反向。
- **Priority**: 2

### US-003: simulate 双档扩展与文档同步
- **Description**: As a 参数调优者, I want ETT 仿真器支持双策略档, so that 换实例类时能离线重标收益与门槛，不烧真实机时。
- **Acceptance Criteria**:
  1. `materialSorting-server/src/materialsorting/cli/calibration.py` simulate 策略网格新增 `se180` 与 `race180` 档（跨 fork 诚实口径：筛选读 short 曲线终值、延长/续跑读 full 曲线 180s 帧，同总预算口径），`simulation_report.json` strategies 增对应行（E[max 口径 delivered 与漏 max 率一并输出）；双档纳入推荐候选（判据同现有）。
  2. 单测 ≥ 6 例：合成池上双模式行为（se 筛+延结构、race 门杀省时再投资、首 seed 参照、同 seed 不二次续跑）、报告字段、与 US-001 fixture 回放器共享判据逻辑（DRY 断言）。
  3. 文档同步：README「配置驱动求解」新增策略双模式块（词汇表 + 用法示例 + 四档速查表 + 现场对跑 88.38 平局与确定性重放结论）、CLAUDE.md 运行方式条目、`.docs/technical/agent-file-map.md`、`materialSorting-server/tests/AGENTS.md`。
  4. 冒烟：若 `out/portfolio_calibration/5336_coded_really/` 存在则 `simulate --tag 5336_coded_really --target 0.85` 输出含双档行（运营产物非测试依赖）；pytest 全绿。
- **Priority**: 3

### US-004: web 后端策略桥接（strategy.py 四路由 + doc_id + build_pid_meta）
- **Description**: As a 前端开发者, I want web 后端提供策略 run 的 start/status/stop/result HTTP 接口（spawn `ms-run-config --strategy` 子进程并轮询 run_dir 产物）, so that 弹窗无需 WS 即可驱动双模式长跑，刷新页面也能恢复进度。
- **Acceptance Criteria**:
  1. `materialSorting-server/src/materialsorting/web/server.py`：`_commit_to_nesting_sync` 的 doc dict 增加 `'doc_id': doc_id` 键（母版原件在 `out/uploads/<doc_id>.dxf`，parse-dxf 已持久保存）；旧 intermediate 无此键 → 策略 start 返回 422「母版信息缺少 doc_id，请重新上传并 commit」；commit 响应体不变。
  2. `materialSorting-server/src/materialsorting/web/solver.py` 提取 `build_pid_meta(pieces, *, sizes=None, per_type=None, quantities=None) -> tuple[dict, float, int]`（demand 判定 → per_type 覆盖 → erode/清洗 → pid_meta 构造 → total_area 累计），`build_instance` 改为调用它；对拍单测保证提取前后 `build_instance` 输出不变（pid_meta/total_area/n_eroded 逐字段一致）。
  3. 新文件 `materialSorting-server/src/materialsorting/web/strategy.py`（`register_strategy_routes(app)` 由 server.py 尾部注册）：
     - `POST /api/strategy/start`：校验进程级单例（进行中 → 409）/ `_PIECES_STATE` 非空且 doc 含 doc_id（422）/ mode ∈ {se,race} / minutes ∈ {10,20,30,60}；写 7 键 config JSON 到 `out/uploads/strategy_cfg_<stamp>.json`（master_dxf 绝对路径、gate_mm=请求值回退 state、sizes/per_type/quantities 透传、seeds=[请求 seed]）；spawn `[sys.executable, '-m', 'materialsorting.cli.run_config', cfg, '--name', f'web_{mode}_{rand6}', '--strategy', mode, '--time', str(minutes*60), '--quiet']`（stdout=DEVNULL、stderr=临时文件）；快照 `out/config_runs/` 目录 → 写 marker `out/config_runs/.web_strategy_active.json`（{pid, run_dir, doc_id, mode, started_at}）→ 202。
     - `GET /api/strategy/status`（无状态，惰性轮询）：① 内存态空 + marker 在 → orphan 分支（pid 存活探测 + 清理动作）② `proc.poll()` 判活；run_dir 快照 diff 发现（忽略 marker 文件；>30s 未发现且进程死 → error + stderr 尾部）③ 组装：`{state: idle|starting|running|done|stopped|error|orphan, mode, total_budget_sec, elapsed_sec(墙钟), run_dir, plan(strategy.json: planned_seeds + race.gate_seconds | se.k_screens/screen_s/ext_s), incumbent(density/width_mm/seed/elapsed，无 placed_items 控载荷), current(最新 mtime best_frame_s*.json 的 seed+density+ext 位), per_seed[], events[](kill_decisions.jsonl R5 事件 + seed_done + extension，只保留尾部窗口), error, exit_code}`；缺文件降级 null；终态清 marker。
     - `POST /api/strategy/stop`：树杀（Windows `taskkill /PID <pid> /T /F`、POSIX `os.killpg`）+ 置 stopped + 清 marker。
     - `GET /api/strategy/result`（done/stopped）：读 result.json portfolio.incumbent（完整 placed_items；stopped 态 incumbent 缺失时回落各 best_frame 取最大）+ `build_pid_meta`（start 时快照口径）组装 manifest（与 /ws/solve manifest.pieces 同形：id/size/color/area_mm2/polygon(net/internal/notches/grain 5 层)/label/demand）+ best{seed,frame_index,elapsed,density,density_sparrow,width_mm,placed_items} + summary{per_seed, mode 段}；marker.doc_id ≠ 当前 state doc_id → 附 warning「母版已变更，应用结果可能与当前画布不一致」。
     - start 时 sizes/per_type/quantities/seed/gate_mm 快照存模块级 `_STRATEGY_STATE`（result 生成 manifest 用同口径，不依赖前端二次回传）。
  4. `curve_s{seed}.json` 运行中非合法 JSON（缺右括号）不读；进度源只用 strategy.json / result.json / best_frame_s*.json / kill_decisions.jsonl（均运行中合法可读）。
  5. 新增 `materialSorting-server/tests/test_web_strategy.py` ≥ 12 例：start 校验（409/422/非法 mode/minutes、config JSON 落盘对拍 7 键与绝对路径）；run_dir 发现（快照 diff + 30s 超时 error 带 stderr 尾部）；status 解析（伪造 fixture run_dir 断言各字段与缺文件降级）；stop（mock subprocess.run 断言 taskkill 参数 + marker 清理）；orphan（marker 在 + 内存空）；result（incumbent→manifest 与 build_instance pid_meta 对拍——提取回归护栏；doc_id 漂移 warning）；**AST 守卫：`web/strategy.py` 全模块不得 import `..cli.*`**（镜像 test_cli_portfolio.py AST 写法）。
  6. `python -c "import materialsorting.web.strategy"` 冒烟零副作用 + ms-web 启动四路由在场（TestClient 探测）+ pytest 全绿 + 既有分层守卫零回归。
- **Priority**: 4

### US-005: 前端「高级运行」弹窗（三态进度 UI）
- **Description**: As a 排料版师, I want 超排界面「高级运行」弹窗选择时长与模式并看到利用率进度, so that 不用命令行也能跑 20 分钟以上的高质量排料。
- **Acceptance Criteria**:
  1. 新建 `materialSorting-web/src/types/strategy.ts`（US-004 schema 的 TS 镜像）+ `src/store/strategyStore.ts`（zustand：`phase: idle|starting|running|done|stopped|error|orphan` + status/result；actions start/stop/refresh/reset）+ `src/hooks/useStrategyPoll.ts`（活性态 setInterval 调 refresh；**弹窗开 2s / 关 15s** 维持入口徽标；终态停轮询）。
  2. `src/store/controlPanelStore.ts` `ControlPanelModalId` 联合类型加 `'strategy_run'`；新建 `src/components/ControlPanel/StrategyRunButton.tsx`（入口按钮，`disabled = solving || 未 commit`；running 时徽标「运行中」；内挂 Modal 单例，范本 PerTypeOverrides.tsx）+ `StrategyRunModal.tsx`（范本 PerTypeOverridesModal.tsx：声明式显隐 + Portal body + ✕/遮罩/ESC 四通道 + role="dialog"；**ESC/遮罩/✕ 关闭均不终止运行**，running 态文案明示「关闭弹窗不会终止运行」）。
  3. 弹窗三态渲染：
     - **配置态**：时长下拉（10 分钟/20 分钟/30 分钟/1 小时）+ 模式下拉（race 门杀/SE 顺延）+ 执行按钮；模式说明行随切换（race：每 3 分钟一轮，90s 门处严格破纪录才续跑，弱 seed 提前淘汰省出预算；SE：多轮短筛选后冠军 seed 加时长再战）；常驻提示「10 分钟档两模式与均分打平，20 分钟起有增益」+「排料参数取当前面板：码号/高级配置/数量矩阵」；不暴露 --se-screen 等 4 参数。
     - **进度态五件套**：① 标题行（模式 · 总预算 · 已跑 X 分 X 秒）② 当前全局最优利用率大数字（= max(result.incumbent.density, 当前 seed best_frame density)）③ 预算进度条（elapsed/total 墙钟口径，标注「≈」）④ 阶段行（第 n/N 轮 · seed X · 求解中；race 被门杀瞬间 chip 变 ✕门杀；SE 检测 `best_frame_s{seed}_ext.json` 出现即切「延长中 · 冠军 seed X」）⑤ seed chips 列表（race = done ✓密度/killed ✕/running ●/未启动灰；SE = k 筛 + 分隔 + 冠军延长条目）+ 最近 1 条事件行 + 终止按钮。
     - **结果态**：完成 · 最优 X.XX%（seed N · 用布 X.XXm）+ 模式汇总（race：M 轮中 K 轮门杀 · 全程 X 分 X 秒）+ 运行目录（可复制）+ [应用到主画布]（US-006）；stopped 态「已终止 · 保留终止前最优 X%」同样给应用按钮；error 态显示错误 + 重试；orphan 态「检测到遗留运行」+ 清理按钮。
  4. `src/components/ControlPanel/ControlPanel.tsx`：PerTypeOverrides 之后渲染 StrategyRunButton（透传 phase/onApplyStrategy）；start 载荷构造与 handleStart 同源——提取 `collectStartContext(form)` 共用（sizesNum/serializeQuantities/collectParams），不复制逻辑。
  5. `src/style.css` 新类 `strategy-*` 族（overlay/modal 复用 per-type 暗底 #26282e + #2ea06c 同色系、z-index 1100；btn/big-density/budget-bar/seed-chips/event-line），不引入 CSS 框架。
  6. vitest 新增 ≥ 8 例（范本 PerTypeOverridesModal.test.tsx / useSolveRun.test.tsx）：store 状态机 + 轮询频率（fake fetch/timers，开 2s/关 15s/终态停、done 后拉 result 一次）；modal 三态渲染 / 执行按钮 disabled 条件 / ESC 遮罩关闭不触发 stop / 终止按钮触发 stop / 10min 提示文案；`npm run build`（tsc --noEmit）通过；**浏览器验证弹窗三态布局与暗色主题一致**（dev 模式 + US-004 接口联调）。
- **Priority**: 5

### US-006: 应用到主画布与导出闭环
- **Description**: As a 排料版师, I want 一键把策略 run 最优方案应用到主画布并导出 PNG/DXF, so that 拿到可直接下料的 marker。
- **Acceptance Criteria**:
  1. `materialSorting-web/src/components/NestingPage.tsx` 新增 `applyStrategyResult(result)`（prop 链 ControlPanel → StrategyRunModal「应用到主画布」按钮，**显式按钮不自动应用**——会清掉主画布现有对比 run，破坏性操作需用户确认；结果态常驻 store，关弹窗后再开仍可应用）：
     - `runRegistry.clear()`（关旧 WS）+ 计数 ref 重置；
     - `runRegistry.create(result.best.seed)` 合成 RunRecord：`manifest = result.manifest`（US-004 build_pid_meta 产物——erode 后几何与 placed_items 对齐、demand 已含，NestSVG 副本池按 demand 建 N 份承接多副本 placement）；`frames = [合成帧]`、`lastFrame = 同帧`（FrameMsg 形状：type/index/elapsed/phase:'final'/density 双口径/width_mm/placed_items）；`finalDensity/finalDensitySparrow = best 双口径`、`viewBoxMaxW = best.width_mm`、`done = true`、`ws = null`、`stopped = false`；
     - `setSeeds([best.seed])` + `setPhase('done')` + `setSeekTime(-1)` + `setStatus('策略 run 已应用：seed N · X.XX%')`。
  2. **导出零改动可用**：既有 ExportButtons/useExport/bestRun() 选中该 record → POST /export placed → 后端 `placed_to_world(placed, _PIECES_STATE.pieces_by_id)`（pid `{label}_{size}` 两边同规则）；导出文件内容与 incumbent 布局一致（含 demand 多副本 N 条 placement）。
  3. 母版变更场景：result 端点 warning 在弹窗结果态展示；应用后导出 pid 失配走既有 400 兜底。
  4. vitest 集成测试 ≥ 3 例：apply 后 `runRegistry.list()` 恰 1 条且字段齐全（manifest/frames/finalDensity/viewBoxMaxW/done）、`phase==='done'`、ExportButtons 非 disabled；`npm run build` 通过；**浏览器视觉验证：应用后 NestSVG 正常渲染（含多副本）、PNG/DXF 导出与弹窗结果一致**。
- **Priority**: 6

## 功能需求 (Functional Requirements)

- FR-1: `--strategy [se|race]`（裸旗标默认 race）+ `--time`（策略模式 = 总预算，必填）+ 4 个参数旗标（--se-screen/--se-extend/--race-budget/--race-gate，默认值全部来自实测）。
- FR-2: race 判据 = 门帧严格破纪录才续跑（`best_so_far > bar`），首 seed 豁免，bar 含被杀者；SE = k 筛选 + 冠军延长（不同预算产生新信息，确定性重放保证零方差）。
- FR-3: 种子流无重复（config seeds 优先、max+1 补齐）；两模式四档全支持，不设 auto 阈值。
- FR-4: 与 `--kill` 互斥（退出 1）、与 `--target` 共存（R0 优先）；策略模式下 R1/R2/θ 不评估；决策落 `kill_decisions.jsonl`（R5_race_gate，S_tau 重载）。
- FR-5: 全员最优帧入 incumbent；result.json portfolio 段含 mode + 模式子段；延长产物 `_ext` 后缀；策略模式启动即写 `strategy.json`（R1）；无旗标零回归。
- FR-6: simulate 网格含 se180/race180 双档并可进推荐。
- FR-7: web 后端 spawn `ms-run-config --strategy` 子进程跑双模式（**进程边界，`web/strategy.py` 不得 import cli，AST 守卫**）；进度经 HTTP 轮询四接口（start/status/stop/result），不开新 WS；`/ws/solve` 协议与普通求解流程零改动。
- FR-8: 策略 run 进程级全局单例（重入 409）；`out/config_runs/.web_strategy_active.json` marker + orphan 态 + 清理动作兜底服务器重启；终止 = 树杀（taskkill /T /F 或 killpg，防孙进程白烧 CPU）；关弹窗不终止运行（仅显式「终止运行」）。
- FR-9: 弹窗时长 4 档映射 `--time` 600/1200/1800/3600；模式 2 选 1 映射 `--strategy`；4 个策略参数旗标用 PRD 默认值不暴露 UI（PRD 数据表默认值即实测最优）；排料参数（码号/高级配置/数量矩阵）取当前面板同源构造。
- FR-10: status 无状态（产物文件 + pid 推导），页面刷新/重开弹窗即恢复进度；进度五件套（大数字最优利用率/预算进度条/阶段行/seed chips/最近事件行），弹窗内不渲染排料过程。
- FR-11: 终局最优结果可应用到主画布（合成单条 RunRecord 置换 registry），现有 ExportButtons/useExport//export 导出链路零改动可用。

## 非目标 (Non-Goals)

- 不做 warm-start（确定性重放下延长已是零方差，warm-start 只省算力不提质量，且 spyrrow 无接口）。
- 不做并行多 seed / 运行中动态预算再分配器（race 省时由串行队列自然吸收）。
- 不做 90% 攻坚（LNS 压宽 / 公差余量利用——另一维度另行规划；fresh 宇宙 88.38 已示上限卡在 seed 抽样，Gumbel 大样本外推是另一个杠杆）。
- 不改 7 键 config schema、不改 `/ws/solve` WS 协议与普通求解流程（web 面走新增 HTTP 接口，原求解链路零改动）。
- τ_gate / 延长时长不进 `--params` 标定体系（实测最简规则即最优；换实例类用 simulate 重标）。
- web 弹窗不暴露 `--se-screen/--se-extend/--race-budget/--race-gate` 与 `--target/--kill/--lns/--solver-opts/--rotate-opts`（高级编排仍走 CLI）；弹窗内不渲染排料过程（布局渲染仍在主画布，应用后可见）。

## 设计考虑 (Design Considerations)

- 默认 = 方案 B（race）体现为 `--strategy` 的缺省值（裸旗标即 race）；**无旗标 = 现行串行**，零回归红线不被默认值穿透。
- 两模式期望等价是实证结论而非设计目标差异：现场对跑精确平 + 确定性重放机制保证；保留双模式供生产对照与未来实例类分岔时切换。
- 决策不静默：race 门杀行、预算不足报错、`--quiet` 口径与既有 R0/R3 一致。
- 10min 档三法打平属预期（延长占预算比过高、筛选票过少），速查表注明而非用 auto 分支处理；弹窗常驻提示但不禁用（用户显式选择）。
- **桥接 = 子进程而非进程内编排**：web 禁 import cli 是 import 边界（AST 守卫只查 Import/ImportFrom 节点，subprocess 不触发）；判据逻辑单一真相源在 cli，web 侧零重复实现零漂移。
- **HTTP 轮询而非 WS**：前端 WS 无重连（onclose 即 finish），1h 长跑刷新即永久丢观测；status 无状态（文件+pid 推导），刷新页面重开弹窗即恢复；弹窗不需要逐帧粒度，2s/15s 轮询足够。
- 进度 UI 克制五件套：大数字 = 用户唯一最关心的数（全局最优利用率）；seed chips 表达两模式不同结构（race 长队列逐轮淘汰 / SE 两段式）；不做滚动日志流。
- 「应用到主画布」保留为显式按钮（会清掉主画布现有对比 run，破坏性操作需用户确认）；前端互斥入口（主画布 running 禁「执行」）防 CPU 竞争扭曲 race 门时刻判据，后端软允许并行（保留运维自由度）。

## 技术考虑 (Technical Considerations)

- 真延续依赖 PC-001 的 `should_stop`（OS 级 terminate + best-so-far 帧交付）；SE 延长是**同 seed 换预算**的新轨迹（非同预算重跑——那只是确定性重放）。
- 名义预算记账 92.5/182.5（含 ~2.5s 启动开销，与离线对决同口径）；solver 收敛早退时按名义记账（两臂对称，实测影响可忽略）；web 弹窗 elapsed 用墙钟口径标「≈」。
- 8 配对曲线小宇宙 ±0.15pt 误差棒；结论方向跨档一致且经现场对跑锚定；换实例类先跑 US-003 simulate 重标（零机时）。
- `kill_decisions.jsonl` 字段重载（S_tau=bar 参照、theta=null）在 README 注明，`--shadow-log` 统计需容忍新 rule 值。
- fixture 曲线降采样单调包络（每秒 ≤1 帧），跨 fork 配对结构如实保留。
- **进度轮询源**（运行中均合法 JSON）：`result.json`（每 seed 完成整体重写，portfolio.incumbent 含完整布局）、`best_frame_s{seed}.json`（新最优覆盖写，mtime 最新 = 当前 seed live best，`_ext` 后缀 = SE 延长进行）、`kill_decisions.jsonl`（append+flush，与 `--quiet` 无关）；`curve_s{seed}.json` 运行中缺右括号**不读**。
- `build_pid_meta` 提取是单一真相源关键：result 端点 manifest 必须经它产出（erode 后几何与 placed_items 对齐、demand 副本数、label_color、5 层透传，与 /ws/solve manifest 同构），对拍单测钉死。
- 子进程 run_dir 定位不用 stdout（DEVNULL 防管道缓冲阻塞）：`--name web_{mode}_{rand6}` 预命名 + spawn 前后目录快照 diff（秒级时间戳目录）；单例 + 随机后缀排除同秒撞名。
- runRegistry 是全局单例且 handleStart 前 clear()：策略结果先存活在 strategyStore，应用时才置换 registry（应用语义 = 显式清场）；合成 RunRecord 的 manifest/frames 与 WS 消息同形（CLI incumbent 同样产自 solve_with_callback_proc 帧回调），NestSVG/ConvergenceCurve/PlaybackBar 零改动兼容。
- 树杀从 Python 调 `taskkill /T /F` 无 Git Bash MSYS 路径转换问题；杀后再探测一次 pid 防漏。

## 成功指标 (Success Metrics)

- [ ] 回归固化：fixture 回放 T=1200/T=3600 双模式 − uniform90 ≥ +0.1pt、T=3600 漏 max ≤5%（固定 bootstrap seed，CI 可复现）
- [ ] 真实冒烟：race ≥1 seed 门杀于 ~τ×budget 且决策行完整；se 两段结构 + `_ext` 产物在场；incumbent 含全部最优帧
- [ ] 零回归：无 `--strategy` 时 result.json 与现版逐字节一致
- [ ] pytest 全绿（现有 257 例零失败 + 新增 ≥30 例，含 test_web_strategy ≥12）
- [ ] web 端到端（race 10min 真跑）：弹窗进度五件套含 ≥1 次门杀事件 → 结果态 → 应用到主画布（含 demand 多副本渲染）→ 导出 DXF/PNG 与 incumbent 布局一致；`/ws/solve` 普通求解回归不受影响
- [ ] 刷新页面重开弹窗，进度从产物恢复（status 无状态）
- [ ] （运营步骤）生产首月按 run_stats.jsonl 复核两模式实测差与速查表一致性

## 待确认问题 (Open Questions)

- ~~race 是否需要 shadow 先行~~（不需要：现场对跑 11 杀全部正确 + 决策全落盘可审计）。
- ~~auto 阈值~~（已定：不设，四档全支持；10min 打平属预期）。
- 生产默认口径后续若需切换（race ↔ se），只改 `--strategy` 缺省值一处，README 速查表同步——等 run_stats.jsonl 攒出两模式真实对照数据后再议。
- web 策略 run 与主画布普通求解的后端互斥：当前仅前端入口禁用（后端软允许并行）；是否需要后端硬互斥，等生产跑一个月看 CPU 竞争对 race 门时刻的实际影响再议。
