# PRD: 机器对接排料 API（YL 排料对接二期 · MaterialSorting 侧）

> 配套 PRD：YLPatternMaking 侧见 `D:\code\YLPatternMaking\tasks\prd-ms-nesting-integration.md`（两仓各自 Ralph 消费，联调里程碑互认）。
> 需求定稿：本 PRD 源自 2026-09-21 两仓规划 + 三轮拍板（v3，15 项决策全定）。

## 概述 (Overview)

YLPatternMaking（YL 打版系统）经 HTTP 机器接口接入 MaterialSorting（MS）排料引擎：multipart 提交带编号母版 DXF + 配置 → 按运行模式求解（普通/高级/极限）→ HTTP 轮询实时利用率 → 终态取完整布局 → 会话无关导出 PLT。本 PRD 覆盖 MS 侧全部改造：`/api/machine/*` 端点族、运行模式三档映射、端口可配、幂等/清理/token。

## 目标 (Goals)

- YL 可提交 `multipart(file=母版DXF, config=JSON)` 换取 `task_id` 并启动求解，三档运行模式真实触发 MS 对应求解路径（plain 180s / `--strategy race` 1200s / `--extreme` 7200s），全默认参数零暴露
- 2s 级轮询拿到实时利用率（物理毛版包络口径）与阶段；终态 result 返回 manifest（含 color/raw_polygon/demand）+ 完整 placed_items
- 会话过期/延迟导出不失败：export 的 pieces 从 run_dir intermediate 直载，默认 `fmt='plt-clean'` + 服务端全算表格（6 手输默认值 + 8 自动计算字段）
- 机器任务与浏览器工作台互不干扰：独立会话（不碰 default）、marker+alive-hook 钉住长跑不被 TTL 误杀、client_ref 幂等防重复提交

## 用户故事 (User Stories)

### US-001: 服务端口可配 + machine 路由骨架
- **Description**: As a 部署者, I want MS web 端口可经环境变量配置且新增机器路由模块骨架注册进 app, so that 与 YL 后端（默认 8000）同机并存且后续端点有落点。文件：`web/server.py`（`main()` 读 `MS_WEB_PORT` 缺省 8000；文件尾 `register_machine_routes(app)`，排在 strategy 注册之后）、`web/machine.py`（新，APIRouter + 注册函数 + 模块 docstring）、`tests/test_web_machine.py`（新）。
- **Acceptance Criteria**:
  1. `MS_WEB_PORT=8010` 启动后 `GET /`（响应头 `Cache-Control: no-cache`）经 8010 可达；不设环境变量时 8000 行为逐字节不变。
  2. `machine.py` 无任何 `import ..cli` 语句（AST 断言，复刻 `tests/test_web_strategy.py` 守卫模式）；对 `server` 的依赖走函数内延迟 import（strategy.py 防环先例）。
  3. `pytest tests/test_web_machine.py tests/test_web_strategy.py tests/test_web_server.py` 全绿（零回归）。
- **Priority**: 1

### US-002: solve 提交端点（上传→commit→三模式 spawn）
- **Description**: As a 机器客户端（YL 后端）, I want 提交 multipart 母版 DXF + config 换取 task_id, so that MS 立即按所选运行模式开始求解。文件：`web/machine.py`（start 主逻辑）、`web/strategy.py`（`_spawn_run_process`/`_kill_tree`/`_discover_run_dir`/`_cleanup_stale_web_artifacts` 提升为模块内可复用，签名不变；`_STRATEGY_STATES` 值支持 mode='machine'）、`web/server.py`（parse/commit 管线延迟 import 点）。
- **Acceptance Criteria**:
  1. 合法载荷（YL nest.dxf 夹具 + `{gate_mm:1750, sizes:[…], run_mode:'normal', quantities:{…}}`）→ `202 {task_id, run_name, started_at}`；task_id 满足 `sessions.SID_RE`（`m`+时间戳+rand）；`out/config_runs/machine_<task6>_<rand6>_<时间戳>/` 出现且含 cfg 落盘产物。
  2. **三模式 spawn 命令金标**：normal = `[sys.executable, '-m', 'materialsorting.cli.run_config', cfg, '--name', run_name, '--time', '180', '--quiet']`；advanced 追加 `['--strategy', 'race', '--time', '1200']`（race 默认档 race-budget 180/race-gate 0.5 由 CLI 缺省）；extreme 追加 `['--extreme', '--time', '7200']`（不含 `--extreme-strategy` = 默认 race 臂；extreme-budget 缺省 600）。
  3. marker `.web_strategy_active_<sid>.json` 恰 5 键且 mode='machine'；config 写 run_mode 对应求解参数，**不含 time/seeds/band/prefix 键**（band/prefix 在场 → 400，同 extreme 路由先例）。
  4. 错误矩阵：缺 file → 400；>20MB → 413；`gate_mm` 缺失/非正 → 400；坏 DXF → 422 中文消息；同 `client_ref` 在飞 → 409 返回既有 task_id。
  5. commit 只挂本会话：default `_PIECES_STATE` 的 doc_id 不变（对拍断言）。
  6. `pytest tests/test_web_machine.py` 全绿 + 全量后端测试无回归。
- **Priority**: 2（依赖 US-001）

### US-003: status / stop / result 三端点
- **Description**: As a 机器客户端, I want 轮询任务状态、终态取最优解与 manifest、可中途停止, so that 展示实时利用率并拿到完整布局。文件：`web/machine.py`（复用 `_status_common`/`_stop_common`/`_result_common` 家族参数化）。
- **Acceptance Criteria**:
  1. running 期 status 含 `incumbent.density`（物理口径，与结束后 result.json 一致）与 `elapsed_sec`；**不读 `curve_s*.json`**（断言：运行中 curve 文件为非法 JSON 在场时 status 仍 200）；`total_budget_sec` 按模式 = 180/1200/7200，`run_mode` 透传。
  2. result 的 `best.placed_items` 条数 = Σdemand（demand>1 的 g 码断言多副本不合并）；`manifest.pieces` 键集含 `raw_polygon`/`d_mm`/`demand`/`color`。
  3. stop → 子进程树终止（孙进程无残留，复刻 strategy 树杀测试法）；stopped 后 result 仍可读（best_frame 边车回落路径）。
  4. 轮询刷活性：start 后不轮询 >`MS_SESSION_TTL_SEC`+宽限 → 会话逐出但 status 仍 200（`_STRATEGY_STATES` 内存态路径）；MS 进程重启后 → orphan 态可 stop/清理。
  5. race/extreme 档各至少一条状态金标（advanced: `--strategy race` run 的 status 含 per_seed；extreme: total=7200）。
  6. `pytest tests/test_web_machine.py` 全绿。
- **Priority**: 3（依赖 US-002）

### US-004: export 端点（会话无关导出 + 默认档全算）
- **Description**: As a 机器客户端, I want 用 task_id 直接导出 PLT, so that 会话过期或延迟导出不失败且无需传任何格式参数。文件：`web/machine.py`（run_dir `pieces_intermediate.json` 直载重建 `pieces_by_id`，兜底会话快照；复用 `web/export.py` 门面 + `parse_table_payload`/默认表格组装，门面零改动）。
- **Acceptance Criteria**:
  1. done 任务（显式使会话过期后）`POST {task_id}` → 200 PLT 字节流 = **默认 `fmt='plt-clean'`**（含表格区、8 项自动计算字段非空、6 手输字段为默认值），与 run 存活期导出逐字节一致。
  2. `fmt='plt'` 可选全量版；`clean=False` 逐字节红线（与 `/export` 旧输出一致）；`table` 显式传入时透传 `parse_table_payload`（非法 → 400 中文）。
  3. `placed` 显式传入全未命中 → 400（既有兜底）；缺省用状态槽 incumbent。
  4. `pytest tests/test_web_machine.py` 全绿。
- **Priority**: 4（依赖 US-003）

### US-005: 幂等 / 清理 / token / 契约文档
- **Description**: As a 运维者, I want client_ref 去重、machine_* 产物 7 天清理、可选 token 与契约文档落册, so that 对接可长期运维。文件：`web/machine.py`、`.docs/technical/agent-api-reference.md`（新专节）。
- **Acceptance Criteria**:
  1. 同 `client_ref` 二次 start 在飞 → 409 + 原 task_id；终态后同 ref → 新任务。
  2. `DELETE /api/machine/solve/{task_id}` 幂等清理 run_dir + 内存态（条目不在也 200；未知 task_id → 404）——YL 结果弹窗显式关闭的消费端。
  3. 伪造 mtime >7 天的 `machine_*` run_dir → 下次 start 被清；非 machine 前缀不动。
  4. `MS_MACHINE_TOKEN` 设置时缺失/错误 `X-Machine-Token` → 401（`secrets.compare_digest` 常量时间比较）；未设置放行（loopback 同机假设）。
  5. 契约文档新专节含：五端点请求/响应字段表、错误码、任务状态机、run_mode 映射表（180/1200/7200 + spawn 参数）、config 键表（per_type 全 0 = 缺省语义全等的注记）、密度物理口径警示（不可与历史 erode 口径混比）。
  6. `pytest tests/test_web_machine.py` 全绿 + 全量后端测试通过。
- **Priority**: 5（依赖 US-004；可与 YL 侧并行）

## 功能需求 (Functional Requirements)

- FR-1: `POST /api/machine/solve`：multipart `file`（母版 DXF 二进制 ≤20MB，同 `/api/parse-dxf` 上限）+ `config`（JSON 字符串：`gate_mm` 必填 int>0；`run_mode` ∈ `normal|advanced|extreme` 缺省 normal；`sizes` int[]；`per_type` {g码:{d?,tol?}}；`quantities` {g码:{码号字符串:int≥0}}；`client_ref` str≤128）。MS 内部填 `master_dxf` = 上传绝对路径；铸 sid → 保存上传（进 diskclean 保护集）→ parse + `_commit_to_nesting_sync`（sid 感知只挂本会话）→ 写 cfg → 按模式 spawn → marker → `202 {task_id, run_name, started_at}`。
- FR-2: 运行模式三档映射（时间烘焙 MS 侧单一真相源）：normal=plain `--time 180`（单 seed 0）；advanced=`--strategy race --time 1200`（race 默认档）；extreme=`--extreme --time 7200`（默认 race 臂 + EXTREME_SOLVER_OPTS 固定档 + extreme-budget 缺省 600）。config 不接受 time/seeds/band/prefix。
- FR-3: 任务状态机 `submitted → starting → running → done | stopped | error`；内存态空 + 本 sid marker 在 → `orphan`（pid 存活可 stop；进程死 + 30s 宽限 → error + stderr 尾 2000 字符）。状态推进复用 `_status_common`（解析态写回内存态）。
- FR-4: `GET /api/machine/solve/{task_id}/status`：`{state, mode:'machine', run_mode, total_budget_sec, elapsed_sec, incumbent:{density,width_mm,seed,frame_index}, current:{seed,density,ext}, per_seed[], error, exit_code}`——无 placed_items（控载荷）；只读 result.json/best_frame 边车 mtime。
- FR-5: `GET /api/machine/solve/{task_id}/result`：`{manifest, best, summary}`；running → 409；stopped → best_frame 边车 density 最大回落；`best.placed_items` demand>1 发 N 条绝不合并；`density` = 物理毛版包络口径。
- FR-6: `POST /api/machine/export`：`{task_id, fmt?, placed?, table?}` 最小请求 `{task_id}`；fmt 缺省 `'plt-clean'`、表格缺省服务端全算；pieces 从 run_dir `pieces_intermediate.json` 直载（兜底会话快照）——导出独立于会话 TTL；`Content-Disposition` 中文/ASCII 双写同 `/export`。
- FR-7: `POST /api/machine/solve/{task_id}/stop`：树杀（`taskkill /PID /T /F`），run_dir 保留（stopped 态 result 仍可读）。
- FR-8: `DELETE /api/machine/solve/{task_id}`：幂等清理（run_dir + `_STRATEGY_STATES` 条目）。
- FR-9: `client_ref` 幂等：同 ref 在飞 409 返回既有 task_id；终态后同 ref 允许新任务。
- FR-10: `X-Machine-Token`：env `MS_MACHINE_TOKEN` 设置时强制（常量时间比较，失败 401）；未设置放行。
- FR-11: `machine_*` run_dir mtime >7 天机会式清理（下次 start 触发）；uploads 侧沿用 diskclean 14 天。
- FR-12: `MS_WEB_PORT` 环境变量（缺省 8000 不变）。

## 非目标 (Non-Goals)

- WS 实时推送通道（三期只读 WS 可议；二期轮询已满足利用率回报目标）
- YLPatternMaking 侧任何改动（见配套 PRD）
- per_type 工艺预设档（YL 发全 0 结构预留，三期议「牛仔默认档」且需版师核 YL g 码与 5336 片型同义性）
- band/prefix 机器载荷（在场 400；腰头成带/起始端成套不经机器通道）
- 自定义 time/seeds/策略参数（race-gate/extreme-budget 等全部 MS 默认档）
- 机器专属并发限制（遵循 `MS_SESSION_MAX=6` 自然上限；YL 侧后续自行治理）
- 共享目录/路径引用式文件传输（multipart 唯一通道）

## 设计考虑 (Design Considerations)

- 机器任务 = strategy 家族第三成员（mode='machine'）：复用状态槽/marker/run_dir 发现/树杀/清理骨架，`_run_alive_hook` 天然钉住 in-flight 长跑（2h 极限档不被 TTL 误杀）；「轮询即活性」与既有 status 语义同源。
- 前端浏览器工作台零感知：机器会话独立 sid（`m` 前缀），commit 快照不碰 default `_PIECES_STATE`。
- 导出独立于会话生命周期是硬需求（YL 关页/挂机后下载不失败），pieces 直载 run_dir intermediate 是唯一可靠源。

## 技术考虑 (Technical Considerations)

- 分层红线：`web/machine.py` 禁 import `..cli.*`（AST 守卫）；与 CLI 的边界是**进程边界**（spawn `python -m materialsorting.cli.run_config`）；对 `server.py` 依赖走函数内延迟 import（防环，strategy 先例）。
- 密度口径：status/result 的 density 均为物理毛版包络口径（`_apply_density_dual` 单一权威）；契约文档警示不可与历史 erode 口径混比。
- 不可行进度帧已由 `_frame_allowed` 白名单过滤（2026-09-16），边车只含可行帧；契约注明「勿在下游重按帧密度取优」。
- Windows：树杀 `taskkill /T /F` 已验证；子进程 stderr 临时文件按 `PYTHONIOENCODING=utf-8` 处理（strategy 同款）。
- spyrrow PanicException 为 BaseException 子类——`solve_worker._solve` 已 `except BaseException` 透传（2026-09-02 修复），机器任务错误以 task error 呈现，无需动作。
- frp/公网暴露机器端点时 `MS_MACHINE_TOKEN` 必开（同机 loopback 可缺省关）。
- `run_stats.jsonl` 照常追加（PC-009 免费观测；class_key 不含 run_mode——机器任务与手跑同 class 可比）。

## 成功指标 (Success Metrics)

- [ ] curl 冒烟三模式全绿（YL 真实 `/api/nest` 产物夹具：普通档全流程；race/extreme 抽验启动+首帧+终止）
- [ ] 轮询期 incumbent.density 单调不降；result placed 条数 = Σdemand
- [ ] 会话过期后 status/result/export 三端点仍 200（M3 演练判据）
- [ ] M4 对拍：普通档与 MS 工作台手跑同 DXF 同参数密度差 ≤0.5pt（物理口径）；高级/极限各抽一单同模式对拍
- [ ] 全量后端测试零回归；`tests/test_web_machine.py` 全绿

## 待确认问题 (Open Questions)

- 无阻塞项（15 项决策 2026-09-21 全部拍板，见需求 v3）。执行层备注：extreme 档 extreme-budget 用 CLI 缺省 600 不暴露；run_mode 值域 `normal|advanced|extreme`（YL UX 视角命名，MS 内部映射 spawn 参数）。
