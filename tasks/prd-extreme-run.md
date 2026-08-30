# PRD: 极限运行（race 门杀 × 极限参数）

## 概述 (Overview)

把实验验证的极限利用率路径（p0.70/et0/600s seed 预算 + race 门杀，终局 92.005%）工程化为「极限运行」功能：CLI `--extreme` 糖衣旗标 + web 独立按钮（与高级运行同级）。目标从高级运行的「期望最优」换为「best-of-k 右尾最优」，同预算下交付更高 best 密度。

数据依据（全部实测，零外推）：[极限运行功能方案_race门杀.md](../.docs/business/极限运行功能方案_race门杀.md)（v1.1，核心决策已确认）+ [极限利用率实验报告_5336_pct与早终止.md](../.docs/business/极限利用率实验报告_5336_pct与早终止.md)。

## 目标 (Goals)

- 同总预算（4h）下，极限运行交付的 best real_density ≥ 现行高级运行 race 默认档（验收对拍判定，见 US-004）。
- 极限参数（exploration_pct=0.7 / early_termination=false / num_workers=4 / quadtree_depth 缺省 4）对用户完全隐藏、不可从任何入口改写。
- 门杀语义与现行 race 逐字一致（复用 `decide_race_kill`/`race_plan`，seed 预算 600s、τ=0.5、门位 300s）。
- web 端独立入口与高级运行同会话互斥（409）、跨会话独立，多会话 US-004 语义零回退。

## 用户故事 (User Stories)

### US-001: CLI `--extreme` 糖衣旗标（ms-run-config）
- **Description**: As a 排料工程师, I want `ms-run-config <cfg> --extreme [--time T] [--extreme-budget 600|1200]` 一条命令跑「极限参数 + race 门杀」长跑, so that 无需手敲 --strategy/--race-budget/--solver-opts 三件套也不会敲错参数。
  实现：`cli/run_config.py` 加 `--extreme`（store_true）+ `--extreme-budget`（int，缺省 600）。展开为内部等价于 `strategy='race' + race_budget=<extreme-budget> + race_gate_tau=0.5 + fixed solver_opts={'exploration_pct': 0.7, 'early_termination': False, 'num_workers': 4}`（quadtree_depth 不写 = 缺省 4，方案 §2.6 已验证调优不成立）。复用现行 `solver_opts_for` fixed 路径与 `race_plan`/`decide_race_kill` 零改动。`out/run_stats.jsonl` 追加行的 config 段 additive 加 `"extreme": {"budget": <B>}`（class_key 口径不变）。
- **Acceptance Criteria**:
  1. `--extreme` 与 `--strategy` / `--kill` / `--solver-opts` / `--rotate-opts` / `--se-screen` / `--se-extend` / `--race-budget` / `--race-gate` 任一显式同给 → 退出码 1 + 中文报错（糖衣旗标独占策略与旋钮）。
  2. `--extreme-budget` 仅收 600 / 1200 两档，其他值 → 退出码 1（2400s+ 是门杀失效硬边界，方案 §2.3）；缺省 600。
  3. 单测锁死展开等价性：`--extreme` 解析后内部参数（strategy mode / race_budget / race_gate_tau / fixed solver_opts dict）与手敲三件套组合逐字段一致；quadtree_depth 键不在 opts 中。
  4. 总预算 T < 905（600 档最低 = 602.5 + 302.5）→ 沿用 `race_plan` 现行 `StrategyBudgetError` 报错路径，退出码 1。
  5. 最小真跑冒烟（`--extreme --time 905`，约 15 分钟，一次）：result.json 各 seed `solver_opts` = 三键极限参数、`kill_decisions.jsonl` 出现 R5_race_gate 判定行、strategy.json mode=race、`out/run_stats.jsonl` 末行 config 段含 `extreme` 键。
  6. 无 `--extreme` 的全部既有路径行为零回归（现有 pytest 套件全绿，含 CLI/portfolio/strategy 测试）。
  7. Python 模块可通过 `python -m materialsorting.cli.run_config --help` 跑通、分层依赖未反向（不新增 import web）。
- **Priority**: 1

### US-002: web 后端 `/api/extreme/*` 四路由（strategy 运行时骨架复用）
- **Description**: As a web 用户, I want 后端提供 `/api/extreme/start|status|stop|result` 四路由（spawn `ms-run-config --extreme` 子进程 + HTTP 轮询）, so that 极限运行成为与高级运行同级的独立入口且共享同会话单飞槽（防双长跑互相拖垮）。
  实现：`web/strategy.py` 内扩展（或同构新模块导入其 helpers）——复用 `_session_gate`/`_STRATEGY_STATES`/marker/`_cleanup_stale_web_artifacts`/`_discover_run_dir`/`_spawn_run_process`/`_kill_tree` 骨架；状态槽**与 strategy 共享同一 `_STRATEGY_STATES[sid]`**（mode='extreme'）⇒ 同会话二者互斥 409 天然成立；run_name `web_[<sid6>_]extreme_<rand6>`；spawn cmd 尾部 `--extreme --time <T> --quiet`（依赖 US-001）。
- **Acceptance Criteria**:
  1. `POST /api/extreme/start {time_total_s}` 通过校验后 202 + `{started, pid, mode:'extreme', run_name}`；spawn 命令含 `--extreme --time <T>`；写 9 键 config（`master_dxf` 绝对路径 / `gate_mm` / `time=T` / `seeds=[seed]` / 可选 sizes·per_type·quantities）。
  2. `time_total_s` 校验：缺省 / 非整数 / < 905 / > 43200（12h 防呆上限）→ 400 中文报错。
  3. 载荷带 `band` 或 `prefix` → 400「极限运行暂不支持腰头成带 / 起始端成套」（方案 §5：极限参数迁移性未验证，v1 明确不支持）。**【2026-08-30 废止**：band/prefix 起与策略族同路径透传（`_parse_band`/`_parse_prefix` 同一校验点），见 `agent-component-map.md`「极限运行 band/prefix 透传」专节**】**
  4. 单飞互斥双向：本会话 strategy starting/running（或其 marker 在）→ extreme start 409；反向 extreme → strategy start 409；**跨会话互不 409**（多会话 US-004 语义不变）。
  5. status / stop / result 与 strategy 四路由同构：无状态惰性轮询（进度源白名单不含 curve_s*.json）、树杀只杀本会话 pid、orphan marker 检测、result 组装 manifest（start 快照口径 `build_pid_meta`）+ best + 母版漂移 warning；mode 字段透传 'extreme'。
  6. sid 会话语义同 strategy：非 default sid 过期/未知 → 401 `session_expired`、非法 → 400、status 轮询刷活性。
  7. 产物清理按会话前缀隔离（`web_<sid6>_extreme_*` 归本会话清理，不误删他会有 run）；pytest 覆盖 1~6 且现有 strategy 测试零回退。
  8. `strategy.py` AST 守卫（禁 import `..cli.*`）仍通过；spawn 进程边界不触发 import 边界；`python -m materialsorting.web.strategy` 导入检查跑通、分层依赖未反向。
- **Priority**: 2

### US-003: 前端「极限运行」独立按钮与弹窗（与高级运行同级）
- **Description**: As a 版师, I want 主界面独立「极限运行」按钮 + 弹窗（总时长预设 + 预计轮数展示，参数全隐藏）, so that 一键发起极限长跑并实时看到进度/门杀事件/结果应用。
  实现：`materialSorting-web/src` 新增 ExtremeRunButton/ExtremeRunModal（与 StrategyRunButton 并排，controlPanelStore modal 单例互斥加 `'extreme_run'`）；时长预设 60/120（默认）/240/480 分钟 + 自定义（16~720 分钟，16min=960s ≥ 905 下限）；预计轮数 `N = 1 + floor((T − 602.5) / 347.5)` 实时显示（方案 §2.5 口径）；轮询/停止/结果态/应用主画布复用 strategy 模式（优先泛化 `useStrategyPoll`/`strategyStore` 加 mode 参数，不复制逻辑、不破坏「useStrategyPoll 全应用恰一实例」不变量）。
- **Acceptance Criteria**:
  1. 独立按钮与「高级运行」并排同级（不进高级运行 race/se 模式选择）；弹窗含四档预设 + 自定义输入，默认选中 120 分钟。
  2. 预计轮数随时长实时更新（对拍公式：120min → ~20 轮、60min → ~10 轮、240min → ~39 轮）。
  3. 弹窗 UI 与提示文案中不出现 exploration_pct / early_termination / num_workers / quadtree_depth 字样（极限参数完全隐藏，已确认决策②）。
  4. 同会话高级运行进行中点极限运行 → 展示 409 互斥文案（反向亦然）；跨会话不受影响。
  5. 轮询三态进度（per_seed chips / 门杀 events / incumbent 大数字）与结果态「应用到主画布」可用（复用 applyStrategyResult 合成 RunRecord 模式，导出三格式正常）；结果态含一句「已固化实验参数」只读提示（不列参数值，2026-08-29 确认）。
  6. HTTP 一律走 `lib/api.ts` apiFetch（X-Session-Id 注入 + 会话先行门），无裸 fetch；`npm run build` 通过、既有前端测试零回退。
  7. 通过浏览器验证极限运行入口（Playwright 冒烟：上传母版 → 打开弹窗 → 预设/轮数对拍 → 发起 → 轮询出现 starting/running → 停止；模板参考 `scripts/smoke-band-preview.mjs`）。
- **Priority**: 3

### US-004: 4h 三臂对拍验收 + 文档收尾
- **Description**: As a 项目负责人, I want 同总预算 4h 三臂对拍（`--extreme` vs 现行 race 默认档 vs 均分 600s×N seeds）+ 验收报告, so that 极限运行的增益主张有端到端实证入档。
  实现：先做曲线库离线回放（三臂 E[best]，脚本可复用 `scripts/depth_ab_analyze.py` 的回放口径）；再各跑一晚端到端（5336 生产配置 `data/configs/5336_coded_really.json` 口径）；报告落 `.docs/business/极限运行_AB验收报告.md`；README「配置驱动求解」节 + `web/AGENTS.md` 补极限运行入口速查。
- **Acceptance Criteria**:
  1. 离线回放表：三臂 E[best] + P(≥91.5pt) 入报告（曲线库 = 既有 25-seed 池 + race 回放语义）。
  2. 端到端三臂各 4h 真跑完成（extreme 臂走 web 入口或 CLI `--extreme`，两入口至少各验一次成功启动）；三臂 best real_density 对比表入报告（原面积口径）。
  3. 判定：extreme 臂 best ≥ race 默认臂 best（若未达标，差距归因分析入报告并回滚默认档建议）。
  4. README + `web/AGENTS.md` 更新（`--extreme` 用法 / `/api/extreme/*` 契约 / 单飞互斥语义）；`agent-api-reference.md` 同步四路由。
  5. Python 模块可通过 `python -m materialsorting.cli.run_config --help` 跑通、分层依赖未反向。
- **Priority**: 4

## 功能需求 (Functional Requirements)

- FR-1: `--extreme` 展开的极限参数四元组（pct 0.7 / et false / workers 4 / depth 缺省 4）在 CLI 与 web 两入口恒一，无任何用户可改入口。
- FR-2: seed 预算固定 600s、τ=0.5（门位 300s）；`--extreme-budget 1200` 保留但 web UI 不暴露（1200 档门判别力 0.896 仍可用，成本 ×2）。
- FR-3: 总时长：web 预设 60/120（默认）/240/480 分钟 + 自定义 16~720 分钟；后端校验 905 ≤ T ≤ 43200 秒。
- FR-4: 同会话「极限运行 ↔ 高级运行」共享单飞槽（409 双向）；跨会话完全独立。
- FR-5: `/api/extreme/*` 四路由的 sid 会话语义（401/400/活性刷新/orphan/产物按 sid 前缀隔离）与 `/api/strategy/*` 完全同构。
- FR-6: 极限运行不支持 band / prefix（start 载荷带了 → 400 明确文案）；`--lns` 沿用 race 语义自动 warn 跳过。
- FR-7: `out/run_stats.jsonl` config 段 additive `"extreme": {"budget": B}`；class_key 组成不变（与历史 run 可比）。
- FR-8: 产物结构（run_dir / result.json / strategy.json / curve / best_frame / kill_decisions.jsonl）沿用现行 strategy race 模式，零新键（除 FR-7）。

## 非目标 (Non-Goals)

- se 延长臂 / 2400s+ 冠军冲刺（门杀失效边界，方案 §2.3；未来走 se 冠军延长思路另立项）。
- band / prefix on 的极限参数迁移性（实验未覆盖，开启后结论需复验）。
- quadtree_depth 调优（已 A/B 关闭，方案 §2.6：d5 冠军回放被误杀、交付垫底）。
- num_workers 调优（部署约束维持 4；换值 = 全部 race 标定重测，本机结论不可迁移）。
- web UI 暴露极限参数或 seed 预算档（已确认决策②：参数是实验结论不是可调项）。

## 设计考虑 (Design Considerations)

- 弹窗信息架构：时长选择（四预设 + 自定义）→ 预计轮数（实时）→ 发起；进度态复用高级运行三态布局（per_seed chips 含 killed 配色、门杀 events 行、incumbent 大数字 + 预算条）；结果态「应用到主画布」+ 导出走既有闭环。
- 「预计 ~N 轮」标注为期望口径（门杀省时红利），提示文案「实际轮数 ≥ 预测（省出预算自动多跑）」。
- 409 互斥文案需指明对方是谁（「高级运行进行中」/「极限运行进行中」），引导先停止/清理。
- 极限运行按钮视觉与高级运行区分（如主色按钮 vs 次级按钮），但同级并排、不折叠进高级运行弹窗。

## 技术考虑 (Technical Considerations)

- CLI：`--extreme` 走 `solver_opts_for` 的 fixed 路径（`run_config.py:364` 现成回调机制）；从属旗标互斥检查扩展（`run_config.py:388` 现有「无 --strategy 给从属旗标」守卫处加 --extreme 分支）。
- web：优先在 `strategy.py` 内加 mode='extreme' 分支而非复制文件——状态槽/marker/清理/发现逻辑天然共享，单飞互斥零额外代码；spawn cmd 差异仅在 `--strategy <mode>` → `--extreme` 与校验域（minutes → time_total_s）。
- 前端：泛化优先于复制——`useStrategyPoll`/`strategyStore`/`types/strategy.ts` 加 mode 维度（或参数化 hook），守住「useStrategyPoll 全应用恰一实例」「start 载荷与主画布 handleStart 同源（collectStartContext）」两条既有不变量。
- run_stats 追加点在 portfolio/run_config 现有 PC-009 路径上 additive，勿动 class_key 组成。
- 冒烟注意：`--extreme` 最小真跑 905s（约 15 分钟），CI 单测只测展开等价与互斥，真跑放本地一次性验证。

## 成功指标 (Success Metrics)

- [ ] 4h 对拍：extreme 臂 best real_density ≥ race 默认臂（离线回放 E[best] 同向）。
- [ ] 2h 默认档（≈20 轮期望）实测落在 E[max] 91.7pt ± 0.3pt 邻域（5336 口径）。
- [ ] 极限参数在两入口（CLI/web）均无用户可改路径（代码审查 + UI 检查）。
- [ ] 既有 strategy/race/多会话 pytest 全绿（零回归）。
- [ ] web 双入口（高级运行/极限运行）同会话互斥、跨会话并发验证通过（pytest + Playwright）。

## 待确认问题 (Open Questions)

（无 —— 两项已于 2026-08-29 确认：① 总时长防呆上限 **12h 暂定**（43200s，若挂夜需求更大可后续放宽，轮数收益曲线 25 轮后无法外推）；② 结果态**要**「已固化实验参数」只读提示（一句话、不列参数值，已入 US-003 AC#5）。）
