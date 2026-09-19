# PRD: warm-start 一期 · se 真顺延 + spyrrow 双源适配（MS 侧）

## 概述 (Overview)

依据 [sparrow源码定制fork立项盘点_2026-09.md](../.docs/business/sparrow源码定制fork立项盘点_2026-09.md) §2.A（需求 A）：sparrow lib 层 `optimize(..., initial_solution: Option<&SPSolution>)` 早已存在（现行 881cdcbd 与 0.2.0 双版本核查），spyrrow 0.9.0 只是 pyo3 绑定未暴露。本 PRD 落地 warm-start 一期核心闭环 —— **se 策略真顺延**（延长段灌入冠军解续跑，取代现状「同 seed 全新重放 180s、前 ~90s 白跑已知结果」），并为后续「录入初始布局（人机协同）/ D 原生微调 / B frozen 预放置」解锁通道。

**跨项目拆分（用户定案 2026-09-07）**：本仓库（MaterialSorting）只做**整体规划 + MS 侧需求**；spyrrow 侧改动（阶段 0a 私有 wheel 构建流水线 + 阶段 A1 pyo3 暴露 `initial_solution`）以需求规格文档交付 —— [.docs/business/spyrrow-ms侧需求规格_warm-start暴露_2026-09.md](../.docs/business/spyrrow-ms侧需求规格_warm-start暴露_2026-09.md)，由用户在 `D:\code\spyrrow-ms` 项目（待建）自行实现。本 PRD 的 US-005（集成验收）依赖该侧 wheel 交付，其余 US 在 PyPI spyrrow 0.9.0 装载态即可完整开发与测试。

**贯穿全程的回归红线**：不传 `initial_solution` 时一切行为逐字节不变；PyPI 0.9.0 装载态全功能可用（warm 特性自动降级为现状重放 + warn）。

## 目标 (Goals)

- se 延长轮去掉重放浪费：灌入冠军 best 帧真顺延，同总预算 se 密度均值 ≥ 重放基线 − 0.1pt 才保 `--se-warm` 默认 on（否则翻默认 off 保留旗标）。
- MS 侧全链路在 PyPI 0.9.0 态零回归：不传即不变（pytest/vitest 全量 + 既有验收复跑），双源（PyPI wheel ↔ 本地私有 wheel）一条 pip 命令可切换。
- spyrrow 侧需求以规格文档完整交付（接口契约 / 校验语义 / 验收判据 / 止损点），跨项目协作边界清晰、不阻塞本侧开发。

## 用户故事 (User Stories)

### US-001: warmstart 引擎模块（校验 + 序列化 + 能力探测）
- **Description**: As a 排料引擎开发者, I want 一个引擎层的 warm 载荷构造模块（`nesting_engine/warmstart.py`）, so that 任何调用方（se 延长轮 / 二期编辑器入口）都能把全链路统一的 placed 列表安全转换为 spyrrow `initial_solution` JSON，且脏数据在 Python 层 fail-fast 而不是进 Rust panic。
- **Acceptance Criteria**:
  1. `build_initial_solution(placed, demand_map, strip_width_mm) -> dict`：placed = 全链路统一格式 `{id, rotation(度), translation:[x,y]}`（solver 帧 / `best_frame_s{seed}.json` 边车 / 编辑器同构）；输出 `{"strip_width": float, "placed_items": [{id, rotation, translation}]}`（接口契约见 spyrrow-ms 侧规格文档 §3.2，字符串 pid、jagua 内部不外漏）。
  2. 校验矩阵全部 fail-fast `ValueError`（中文消息面向用户）：条目形态非法（缺键/类型错/translation 非 2 元数值）；pid 不在 demand_map；**每 pid 条数 ≠ demand**（完整解硬约束：sparrow `restore()` 不补放新片，剩余片永远不会被放上）；**含 `mirror: true` 条目拒绝**（编辑器镜像片 sparrow 无法表达，提示「含镜像片，无法热启动」）。
  3. `warm_start_supported() -> bool`：`importlib.metadata.version('spyrrow')` 含 `+ms` local tag → True；任何异常（包不存在等）→ False，绝不抛出。
  4. demand 多副本：同 pid N 条（N == demand）合法通过；部分解（少于 demand）拒绝 —— 与「demand>1 时 sparrow 给同一 pid 发 N 条 placed_items」的既有不变量对齐。
  5. 模块**禁 import web/cli**（AST 守卫随 `tests/test_warmstart.py`，对齐 `tests/test_polish.py` 先例）；测试覆盖：畸形输入矩阵 / 多副本 / 部分解拒绝 / 未知 pid / mirror 拒绝 / 合法 round-trip / `warm_start_supported` 两种态（monkeypatch version 字符串）。
  6. `python -m materialsorting.nesting_engine.warmstart` 冒烟跑通（合成夹具自检 + 退出码 0，无 spyrrow 依赖）；分层依赖未反向。

- **Priority**: 1

### US-002: initial_solution 求解链透传（pipeline → solver → solve_worker）
- **Description**: As a 排料引擎开发者, I want `initial_solution` 以 band/prefix 同款五步链模板穿透求解编排层（`cli/pipeline.py` → `web/solver.py` → `web/solve_worker.py`）, so that warm 载荷能到达子进程内的 `instance.solve()`，且缺省 None 时全链行为逐字节不变。
- **Acceptance Criteria**:
  1. `pipeline.solve_pieces` 新 kwarg `initial_solution: dict | None = None`；`solver.solve_with_callback_proc` 新同名 kwarg；`Process args` 元组追加第 7 位（`solver.py` Process 构造点 + `solve_worker` 签名同步，**直接调 solve_worker 的既有测试桩全部同步**）。
  2. `solve_worker` 消费：载荷在场时 `json.dumps` 后传 `instance.solve(config, progress=..., initial_solution=...)`（dict 纯 JSON 可序列化，Windows spawn pickle 安全；json.dumps 只在最终消费点做）。
  3. 防御闸门（双保险之二）：solve_worker 侧 `warm_start_supported()` 为 False 而载荷在场 → **丢弃载荷 + warn 降级为普通重放**（不重跑、不炸轮，探测在 solve 之前）；band/prefix 与 initial_solution 同传 → 投 `{kind:error}`「band/prefix 与初始布局暂不支持同开」（防御性，正常编排层已拦）。
  4. 缺省 `initial_solution=None` 路径与现行完全一致（不碰现有分支）；pytest 既有求解链测试（`test_solve_proc.py` / `test_cli_solve_pieces_proc.py` 等）全绿零改动（args 元组长度变化的桩同步除外）。
  5. 新增桩测试（PyPI 0.9.0 态可跑，monkeypatch 假 spyrrow 模块）：载荷透传到位（worker 收到 json 字符串并传入 solve）/ 不支持时丢弃降级（solve 收到 initial_solution=None）/ band 同传防御 error / None 缺省零变化。
  6. `python -m` 入口与分层依赖检查通过（web/cli 层不改 import 方向）。

- **Priority**: 2

### US-003: se 延长轮真顺延接线（portfolio + CLI 旗标）
- **Description**: As a 排料策略使用者, I want se 策略的冠军延长段灌入筛选轮冠军解真顺延（`--se-warm`，默认 on）, so that 延长段 180s 全部花在增量搜索上而不是重放已知结果；warm 不可用时自动回退现状重放，绝不炸轮。
- **Acceptance Criteria**:
  1. `cli/portfolio.py` 延长轮编排：se 冠军（argmax real_density）确定后读 `run_dir/best_frame_s{champ}.json`（含 placed_items + width_mm，band/prefix 已展开成员级）→ 在 `pipeline.solve_pieces` 语境内（有 run_dir 与 pid_meta/demand_map）经 `warmstart.build_initial_solution(placed, demand_map, width_mm)` 构造载荷下传（装载与校验放 solve_pieces 内、portfolio 传策略标志，具体分工实现时定，单一装载点即可）。
  2. **回退矩阵**（任一命中 → 回退现状重放 + warn 一行，不静默不炸轮）：`--se-warm off`；`warm_start_supported()` False（PyPI 0.9.0 装载态）；best_frame 边车缺失/损坏/校验失败；cfg.band 或 cfg.prefix 开（warm 输入是成员级 placed，与 band/prefix 改写后的实例组成不匹配 —— 组合片展开条目 pid 集合 ≠ 扣减后实例，硬互斥）。
  3. `--se-warm {on,off}` CLI 旗标（默认 on，值域外退出 1，new_run_dir 前拦下）；无 `--strategy se` 时给出即从属旗标笔误退出 1；无旗标时 CLI/控制器/result.json 调用形逐字节零回归。
  4. 可观测：`strategy.json` se 段与 ext 轮 result.json config 段 additive 记 `warm: true/false` + 回退原因（如 `warm_reason: 'unsupported'|'no_best_frame'|'band_prefix_on'|...`）；run_stats 行 config 段 additive 同键（class_key 不变，与历史 run 可比）。
  5. 测试（`tests/test_cli_strategy_wiring.py` 扩展，桩 solve）：warm on 透传到 solve 调用形 / 四类回退各独立用例 / off 显式回退 / 零回归哨兵（无旗标输出逐字节对拍）。
  6. `python -m materialsorting.cli.run_config --help` 展示新旗标；模块导入检查通过。

- **Priority**: 3

### US-004: spyrrow 双源切换助手 + rev 钉板 + 构建手册
- **Description**: As a 本项目维护者, I want 一个双源切换脚本（`scripts/spyrrow_wheel.py`）与 rev 钉板记录（`materialSorting-server/spyrrow_build.json`）+ 构建手册文档, so that 本机在「PyPI 0.9.0 ↔ spyrrow-ms 私有 wheel」之间一条命令切换、构建可复现可审计，spyrrow-ms 未交付前日常开发生产零影响。
- **Acceptance Criteria**:
  1. `python scripts/spyrrow_wheel.py status`：打印当前安装源（PyPI/本地 tag）、版本号、`warm_start_supported()` 探测结果；`use-pypi`：`pip install --force-reinstall spyrrow==0.9.0` 回线上版；`use-local <wheel路径>`：`pip install --force-reinstall <wheel>`；全部走 `.venv` 的 pip（sys.executable 定位，不假设 PATH）。
  2. `materialSorting-server/spyrrow_build.json`：`{spyrrow_ms_commit, sparrow_rev, wheel_version, built_at}` 钉板字段（use-local 成功后提示更新/自动更新）；文件入库（轻量、无构建产物）。
  3. 新写 `.docs/technical/spyrrow私有wheel构建与升级手册.md`：双源切换用法、升 rev 流程（0.2.0 步骤预留）、troubleshooting；工具链/源码获取/构建命令本体在 spyrrow-ms 侧规格文档（本手册只写 MS 侧视角的消费与切换）。
  4. status 在当前 PyPI 态即正确工作（本 US 不依赖 spyrrow-ms 交付）；use-local 对不存在的 wheel 路径给出清晰报错。
  5. 脚本自检：`python scripts/spyrrow_wheel.py status` 退出码 0（repo 根直跑，sys.path 自引导对齐既有 scripts/ 惯例）；不引入新依赖。

- **Priority**: 4

### US-005: 集成验收与文档收官（依赖 spyrrow-ms wheel 交付）
- **Description**: As a 排料策略维护者, I want 在 spyrrow-ms 私有 wheel（0.9.0+ms0，按规格文档构建）装入 .venv 后做行为全等对拍 + se A/B 实测 + 全量回归 + 文档收官, so that warm 真顺延有实测数据背书、默认 on/off 有判据裁决、跨项目链路（MS 调用 ↔ spyrrow-ms 暴露）端到端闭环。
- **Acceptance Criteria**:
  1. **前置 gate（0a 行为全等，MS 侧执行者）**：本地 wheel 不传 initial_solution 与 PyPI 0.9.0 同 seed 同短预算对拍（5336 `--time 30 --seeds 0`），best density 一致（同 rev 同算法；帧级允许既有 num_workers=4 漂移口径）+ 背靠背自身逐帧确定。
  2. **warm 端到端**：真 wheel 下 se 延长轮灌入成功（strategy.json `warm: true`），末帧 placed 条数守恒 == Σdemand，首帧宽度 ≈ 灌入 strip_width（续跑语义）±1mm。
  3. **se A/B 判据**：5336 同总预算 `--strategy se --time 600` warm on vs off 各 ≥3 次取均值，warm ≥ replay − 0.1pt 才保默认 on，否则翻默认 off 保留旗标（结论入档）；背靠背确定性双跑（同 warm 输入 ⇒ restore 后轨迹确定，逐帧一致）。
  4. **既有验收复跑**：`python -m materialsorting.web.prefix_accept --seeds 0,1 --time 30` accept 不劣化；pytest 全量 + vitest 全量全绿（本轮 web 前端零改动，vitest 预期不动）。
  5. **文档收官**：`CLAUDE.md`「关键技术决策」sparrow 条目改「spyrrow-ms 私有 fork 单一真相源（起步锚 881cdcbd，双源安装态切换，0.2.0 升级独立后续项）」+ solver/pipeline 段注记 initial_solution 通道；盘点文档 §2.A 增一期落地状态注记；`.docs/technical/agent-file-map.md` 增 warmstart.py 行 + portfolio/pipeline/solve_worker 行注记；spyrrow-ms 侧规格文档补「MS 侧已对接」状态。
  6. 全部验证命令记入本 PRD 附带的验证速查（对齐既有 PRD 惯例），模块导入/入口检查通过。

- **Priority**: 5

## 功能需求 (Functional Requirements)

- FR-1: `warmstart.build_initial_solution(placed, demand_map, strip_width_mm)` —— 校验矩阵（形态 / pid 全匹配 / 每 pid 条数 == demand 完整解硬约束 / mirror 拒绝）全部 fail-fast `ValueError`，输出 spyrrow `initial_solution` JSON dict（字符串 pid 接口，契约 = spyrrow-ms 侧规格文档 §3.2）。
- FR-2: `warmstart.warm_start_supported()` —— `importlib.metadata` 版本串含 `+ms` local tag 判定，异常安全恒不抛。
- FR-3: `initial_solution` 五步链透传（portfolio/pipeline → `solve_with_callback_proc` kwarg → `Process args` 第 7 位 → `solve_worker` 消费 → `instance.solve(initial_solution=...)`），**缺省 None 行为逐字节不变**。
- FR-4: 防御闸门双保险 —— 编排层（portfolio 回退矩阵）+ worker 层（不支持降级重放 / band·prefix 同传 error）。
- FR-5: `--se-warm {on,off}` 默认 on + additive 可观测键（strategy.json / result.json config 段 / run_stats 行，class_key 不变）。
- FR-6: `scripts/spyrrow_wheel.py` status/use-pypi/use-local + `spyrrow_build.json` rev 钉板；MS 仓库不引入任何 Rust 构建产物（构建只在 spyrrow-ms 项目）。
- FR-7: 跨进程形态约束：initial_solution 全程纯 JSON dict（Windows spawn pickle 安全），`json.dumps` 只在 worker 最终消费点做。

## 非目标 (Non-Goals)

- **A4 编辑器「从此布局继续优化」入口**（WS `initial_placed` 载荷 + 前端按钮 + 冒烟）—— 二期另立 PRD（mirror 拒绝分支已为其预埋校验）。
- **spyrrow 侧实现**（0a 工具链/源码/构建 + A1 Rust 暴露）—— 不在本仓库做，规格文档交付到 `D:\code\spyrrow-ms`。
- **0.2.0 基线升级**（jagua-rs 0.8.1 + #149）—— 独立后续项（升级即重标确定性基线）。
- D 原生微调 / B frozen 预放置 / LNS warm 通道 / race 门杀 warm —— 均为 A 落地后的后续消费方，本 PRD 不接线。
- 前端与 WS 协议任何改动（本轮 `X-Session-Id`/StartPayload 零变化）。

## 设计考虑 (Design Considerations)

- 本轮无 UI：全部为 CLI/引擎内部链路；可观测性靠一行 warn + additive 记录键，回退**绝不静默**（每类回退原因落 `warm_reason`）。
- warm 输入源单一化：v1 只吃 `best_frame_s{champ}.json`（筛选轮冠军 best 帧，band/prefix 已展开成员级）；编辑器/历史唛架导入留给二期 A4。
- 降级语义统一：「回退现状重放」是唯一降级动作 —— se 行为回到本 PRD 之前的确定性基线，不引入第三种模式。

## 技术考虑 (Technical Considerations)

- **完整解硬约束（F2）**：sparrow `SPProblem::restore()` 只按 placed 扣减 demand、不补放新片（exploration/compression 只有 move/shrink）⇒ 初始解必须每 pid 条数 == demand，校验必须在 Python 层前置（Rust 侧 release 无 validate）。
- **strip_width 续跑语义（F3）**：restore 直接采纳灌入宽度、exploration 从该宽度收缩（不走 LBF 重铺）⇒ `strip_width` 取冠军帧 `width_mm`；端到端断言「首帧宽度 ≈ 灌入值」。
- **band/prefix 硬互斥（F8）**：band/prefix 改写实例组成（exclude_labels / exclude_pids 扣减 / WB_·PS_ 组合片 extra_items），warm 输入是展开后的成员级 placed，pid 集合与改写后实例不匹配 —— 双闸门拦截，不做转换适配（v1）。
- **f32 精度**：jagua `ExtTransformation` 为 f32，translation mm 级精度 1e-4，f64→f32 收窄安全（宽度 <1e-3 判等口径）。
- **确定性**：同 warm 输入 + 同 seed ⇒ restore 后轨迹确定（背靠背逐帧一致是 A/B 判据之一）；跨会话漂移沿用既有 num_workers=4 口径备案。
- **桩测试策略**：US-002/003 在 PyPI 0.9.0 态用 monkeypatch 假 spyrrow 模块覆盖透传/降级分支；真 wheel 端到端全部集中在 US-005。

## 成功指标 (Success Metrics)

- [ ] pytest 全量全绿（新增 test_warmstart.py + strategy wiring/proc 桩扩展），vitest 全量全绿（零改动预期）。
- [ ] PyPI 0.9.0 装载态：`--strategy se` 全流程与现状行为一致（warm 自动回退 + warn，策略可正常跑完）。
- [ ] 本地 wheel 态（US-005）：se 同总预算 A/B 均值 warm ≥ replay − 0.1pt（保默认 on）或有翻默认 off 的数据结论入档。
- [ ] 不传 initial_solution 的所有既有路径（WS 求解 / CLI 单轮 / race / extreme / prefix_accept）回归零差异。
- [ ] spyrrow-ms 侧规格文档完整交付（接口契约可照做、验收判据可照跑）。

## 待确认问题 (Open Questions)

- se A/B 判据线 −0.1pt 是否合适？（US-005 实测后裁决；过松/过紧可在此调）
- US-005 时序：spyrrow-ms 侧 wheel 何时交付由用户排期 —— US-001~004 不被阻塞，先行合入；US-005 作为独立验收迭代挂起等待。
- warm 默认 on 若 A/B 不达标翻 off 后，是否保留「每 N 版复测」的复查机制？（暂不定，验收时看漂移幅度）
