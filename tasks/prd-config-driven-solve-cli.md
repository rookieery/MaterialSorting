# PRD: 配置文件驱动的排料求解 CLI（ms-run-config）

## 概述 (Overview)

打通「JSON 配置文件 → 完整排料管线 → 利用率结果」的纯后端通道：读取 `data/configs/` 下的 7 键配置文件（schema 已定稿，示例 `data/configs/5336_coded_sizes32-38.json`），新增 `cli` 子包复用现有底层原语跑通 parse → commit → intermediate → build_instance → solve 全管线，无需打开浏览器即可批量评估排料配置。**最高优先级硬约束：现有 web 界面交互流程（server.py / solver.py / solve_worker.py / export.py）零改动、行为零变化。**

## 目标 (Goals)

- 一条命令 `ms-run-config <config.json>` 跑完「母版解析 → 切片 → intermediate → 求解」，输出**原面积口径利用率** `real_density = total_area/(width_mm × gate_mm)`（90% 生死线口径）与用布长度 `width_mm`。
- 与 web 求解**同代码路径**：复用 `build_instance`（sizes 过滤 / quantities→demand / per_type 覆盖 / NEST_GATE_MM 钳制全部继承），CLI 与 web 对同一配置产出的密度可互相对拍。
- web 目录四文件（server/solver/solve_worker/export）`git diff` 为空；CLI 产物全部落在独立目录 `out/config_runs/<run_name>_<时间戳>/`（重跑保留历史），物理上不可能写 web 事实源（`out/sparrow_baseline/pieces_intermediate.json` 与 `out/uploads/`）。
- 配置错误（拼写 / 类型 / 路径 / 非字符串 sizeKey）在管线启动前被中文报错拦下，报错含字段路径。

## 用户故事 (User Stories)

### US-001: 配置加载与校验模块（cli/config.py）
- **Description**: As a 算法调参用户, I want 一份 JSON 配置被严格加载校验, so that 拼写/类型/路径错误在管线启动前就被中文报错拦下。主要文件：`materialSorting-server/src/materialsorting/cli/__init__.py`（新建）、`cli/config.py`（新建）、`materialSorting-server/tests/test_cli_config.py`（新建）。
- **Acceptance Criteria**:
  1. `load_config(Path('data/configs/5336_coded_sizes32-38.json'))` 成功：`sizes=[32..38]`、`gate_mm=1980`、`seeds=[0]`、`quantities` 键类型 `dict[str, dict[str, int]]`（sizeKey 全字符串）、`master_dxf` 解析为存在的绝对路径。
  2. 下列配置各自抛 `ConfigError` 且异常消息含出错字段名：未知顶层键（防 `multiSeed` 手误；旧 `seed` / `multi_seed` / `seed_count` 三键同按未知键报错）；`master_dxf` 指向不存在文件（消息列出 CWD / REPO_DIR 两个候选绝对路径）；`sizes` 含字符串元素；`seeds` 空列表 / 含负数或非整数 / 含重复项；`per_type` 含非 `g\d+` 键；`quantities` 值为字符串 `"1"`（提示 JSON 应写数字）；`gate_mm<=0`。
  3. `per_type` 的 `d>10` 或 `tol>45` 不抛错但产生警告（引用 `MAX_OVERLAP_MM` / `MAX_ROTATION_TOL_DEG`，说明将被全局上限钳制）。
  4. `.venv/Scripts/python.exe -m pytest materialSorting-server/tests/test_cli_config.py` 通过；`python -m materialsorting.cli.config` 导入无副作用、分层依赖未反向（仅标准库，无兄弟包 import）。
- **Priority**: 1

### US-002: commit 管线编排（paths 常量 + cli/pipeline.py 的 commit_from_config）
- **Description**: As a 后端开发者, I want 配置驱动的独立 commit 管线产出切片与 intermediate, so that 不触碰 web 事实源也能拿到与 web 同口径的排料输入。主要文件：`materialsorting/paths.py`（+1 常量 `CONFIG_RUNS_DIR`）、`cli/pipeline.py`（新建）。
- **Acceptance Criteria**:
  1. 对示例母版运行 `commit_from_config` 后，`out/config_runs/<run_name>_<YYYYMMDD-HHMMSS>/pieces/` 内切片 DXF 数 + `pieces_manifest.json` 条目数 = 母版 size≠None 轮廓数（示例配置预期 110），`out/config_runs/<run_name>_<YYYYMMDD-HHMMSS>/pieces_intermediate.json` 生成且 `gate_mm=1980`、piece 字段（pid/label/size/polygon/bbox/area_mm2/n_verts/allowed_angles + 5 层 + rounding 位数）与 `server._commit_to_nesting_sync` 产物逐字段一致（顶层省略 web 专属 `label_representatives`）。
  2. `web.solver.load_pieces(run_dir/'pieces_intermediate.json')` 可正常读回，pieces 数与 manifest 一致（schema v2 兼容自证）。
  3. 运行前后 `out/sparrow_baseline/pieces_intermediate.json` 与 `out/uploads/` 内容和 mtime 不变（web 事实源未被触碰）。
  4. 与 web commit 同母版产物对拍：pid 集合相等、`total_area_mm2` 相等、任取同 pid 片 polygon 逐点相等。
  5. `python -m materialsorting.cli.pipeline` 导入冒烟通过（无副作用）、分层依赖未反向（cli → web/dxf_parser/nesting_* 单向）。
- **Priority**: 2

### US-003: 求解封装 + CLI 入口 + console_script 注册
- **Description**: As a 算法调参用户, I want `ms-run-config <config>` 一条命令跑完管线并输出利用率, so that 无需浏览器即可批量评估配置。主要文件：`cli/pipeline.py`（`solve_pieces`）、`cli/run_config.py`（新建）、`materialSorting-server/pyproject.toml`（+1 script `ms-run-config`）。
- **Acceptance Criteria**:
  1. `solve_pieces` 复用 `build_instance` + `solve_with_callback`（threading 版进程内直跑）：示例配置下 `n_items=70`（10 g 码 × sizes 32-38）、`n_eroded=0`（per_type 全 0）、`len(placed_items)==Σdemand==70`。
  2. 冒烟 `ms-run-config data/configs/5336_coded_sizes32-38.json --time 5`（或 `python -m materialsorting.cli.run_config` 等价形态，pyproject 改后需 `pip install -e materialSorting-server --no-deps` 刷新入口）：退出码 0，`real_density ∈ (0,1)`、`width_mm > 0`，stdout 末行含「real_density（原面积口径）+ 用布长度 + 片数 + 耗时 + 本次 run_dir 完整路径」人类可读汇总。
  3. `out/config_runs/<run_name>_<YYYYMMDD-HHMMSS>/result.json` 落盘：config 回显 + commit 摘要（n_pieces/total_area）+ solve 指标（seed/width_mm/real_density/density_sparrow/elapsed）。
  4. 进度输出不刷屏：仅打印「原面积口径新最优」帧 + 30s 心跳；Windows 控制台 UTF-8 reconfigure（中文不乱码）。
  5. `git diff -- materialSorting-server/src/materialsorting/web/` 为空；`python -m materialsorting.cli.run_config --help` 输出用法（config / --name / --time / --quiet），分层依赖未反向。
- **Priority**: 3

### US-004: 多 seed 串行多轮与 best 汇总（可延后，不阻塞交付）
- **Description**: As a 算法调参用户, I want `seeds` 列表含多个种子时自动串行逐个求解并汇总最优, so that 消除单 seed 随机性对配置评估的干扰。主要文件：`cli/run_config.py`。
- **Acceptance Criteria**:
  1. `seeds=[0,1,2,3,4]` 时顺序执行 5 轮（每轮 = 同一份 commit 产物 + 以该 seed 构造 build_instance 求解，不重复 parse/commit）；种子不要求连续（如 `[0,42]` 合法，供复现历史 seed 对比）。
  2. `--time 5` 冒烟：result.json 的 solve 数组长度 = len(seeds)，best 取 real_density 最大者且 seed 字段正确；多 seed 启动时打印预计总时长（len(seeds) × time）。
  3. `seeds=[0]`（含缺省默认）行为与 US-003 完全一致（单 seed，回归）。
  4. `python -m materialsorting.cli.run_config` 冒烟通过、分层依赖未反向。
- **Priority**: 4

### US-005: web 回归验证 + 文档同步
- **Description**: As a 项目维护者, I want 全量 web 回归证据与文档更新, so that 新通道合入后工作台零回归成为可审计事实。主要文件：`README.md`、`CLAUDE.md`（运行方式段）、`.docs/`（agent-file-map.md 增补 cli 子包）。
- **Acceptance Criteria**:
  1. web E2E 手测记录：`ms-web` 启动 → 上传母版 → parse 预览 g 码 → commit → WS 求解（time 调小）→ 导出 PNG/DXF，行为与改动前一致。
  2. 并行无干扰记录：web 求解进行中同时跑 CLI 冒烟，结束后 `out/sparrow_baseline/pieces_intermediate.json` mtime 与内容未变、`out/uploads/` 无新目录。
  3. README/CLAUDE.md 含 CLI 用法、7 键配置 schema 说明（含 `seeds` 列表串行语义）、`out/config_runs/` 产物说明与「不触碰 web 数据」声明。
  4. 全部 cli 模块 `python -m` 导入冒烟 + compileall 通过，分层依赖未反向。
- **Priority**: 5

## 功能需求 (Functional Requirements)

- FR-1: 配置 schema 7 键（`master_dxf / sizes / gate_mm / time / seeds / per_type / quantities`）：`seeds` 为**串行批次维度**（非负整数列表，缺省 `[0]`；列表每项 = 一次以该 seed 发起的求解；**取代**旧 `seed/multi_seed/seed_count` 三字段——串行决议后无模式开关、无 clamp [2,6] 语义，支持非连续种子），其余 6 键与 WS StartPayload 契约字段名 1:1；未知顶层键报错（旧 seed 三键按未知键报错）。
- FR-2: `master_dxf` 路径解析：绝对路径直用；相对路径先试 CWD 再试 REPO_DIR，均失败报错并列出两个候选绝对路径。
- FR-3: `quantities` 校验强制 sizeKey 为数字字符串或 `'null'`（后端按 `str(size)` 查 demand，JSON 数字键查不到）；值须 JSON 数字且 ≥0。
- FR-4: `commit_from_config` 编排顺序与 `server._commit_to_nesting_sync` 一致：`collect_pieces_with_details` → `labeling.assign_codes` → 在 `run_dir/pieces/` 下 `write_piece_dxf` + `pieces_manifest.json`（run_dir 带时间戳天然全新，无需清理旧产物）→ `load_nest_pieces` → intermediate 落盘；不写 `.bak`（隔离目录无历史）。
- FR-5: CLI 代码**不出现任何对 `paths.INTERMEDIATE` / `out/uploads/` 的写操作**；产物只落 `out/config_runs/<run_name>_<YYYYMMDD-HHMMSS>/`（`paths.CONFIG_RUNS_DIR`；run_name 默认 = 配置文件 stem，`--name` 覆盖，非法字符清洗；**时间戳后缀保留历史**——重跑生成新目录互不覆盖，本地时间秒级精度，文档注明避免同秒同名并发）。
- FR-6: 求解走 `build_instance` + `solve_with_callback`（不新写 solve 循环、不用多进程版——terminate 能力是 WS stop 场景专用）；`real_density = total_area/(width × gate_mm)` 与 web `_apply_density_dual` 同公式。
- FR-7: CLI 入口 argparse：`config` 位置参数 + `--name` + `--time N`（覆盖配置时长，冒烟用）+ `--quiet`；退出码 0=成功 / 1=配置或管线失败 / 2=求解失败。
- FR-8: `result.json` 含 config 回显、commit 摘要、solve 数组（单 seed 1 条）、best；stdout 末行人类可读汇总。
- FR-9: quantities 不对称语义在 CLI 汇总中如实转述不改语义：label 在 quantities 中但 sizeKey 缺失 → demand=0 跳过；label 不在 quantities → demand=1。

## 非目标 (Non-Goals)

- **不做任何前端改动**：不新增 HTTP/WS 端点，不改 React 代码与交互。
- **不做 server.py 共享函数重构**（planner 方案 A）：commit 编排在 cli/pipeline.py 镜像实现，server.py 一行不动。
- **不做多 seed 并行**（ThreadPoolExecutor 6 路并发是 web 场景）：CLI **确定只做串行**（2026-08-19 决议：总时长 = len(seeds) × time，如 5 seed × 300s ≈ 25min 可接受），不做并行。
- **不做导出**（PNG/R12-DXF/PLT）：本期只要利用率结果，导出仍走 web。
- **不做批量多配置调度**（一次跑一目录多份配置出对比表）：本期单命令单配置；**后续可能需要**（result.json 机器可读即为此预留），引入时另立 PRD。
- **不做配置文件生成器 / 模板工具**：配置手写，schema 见示例。

## 设计考虑 (Design Considerations)

- CLI 输出双形态：stdout 人类可读（进度新最优帧 + 30s 心跳 + 末行汇总），`result.json` 机器可读（供后续批量评估脚本消费）。
- 报错全部中文 + 含字段路径（如 `quantities.g01."32"`），与 web 端点报错风格一致。
- run_dir 命名 = `<run_name>_<YYYYMMDD-HHMMSS>`（本地时间秒级）：**重跑保留历史、互不覆盖**（2026-08-19 决议）；stdout 末行打印本次 run_dir（含 result.json）完整路径方便回溯；同秒同名并发会撞目录，文档注明避免。

## 技术考虑 (Technical Considerations)

- **分层**：新增 `cli` 子包位于 web 之上（`cli → web → nesting_engine → nesting_bounds → dxf_parser`）；cli 只 import `web.solver`，**绝不 import `web.server`**（其模块顶层有 load_pieces + mount static 副作用）。
- **密度双口径**：输出 `real_density`（原面积口径，90% 生死线）为主，`density_sparrow`（erode 后自报）附带参考；分母用 `gate_mm=1980` 显示口径，求解约束带钳 1910 由 `build_instance` 内部处理，配置方无感。
- **quantities sizeKey 字符串**是硬约束（FR-3）；sizes 过滤先于 demand 查表（`build_instance` 既有语义）。
- **Windows 控制台 GBK**：`main()` 首行 `sys.stdout/stderr.reconfigure(encoding='utf-8')`（项目既有模式）。
- **入口刷新**：pyproject 增 script 后需 `.venv/Scripts/python.exe -m pip install -e materialSorting-server --no-deps`（清华源）；刷新前 `python -m materialsorting.cli.run_config` 等价可用。
- **Ctrl+C**：threading daemon 模型下直接终止、无孤儿进程（这正是选进程内求解的原因之一）。
- **num_workers=4 不动**（spyrrow issue #113：>4 质量反降）。

## 成功指标 (Success Metrics)

- [ ] `ms-run-config data/configs/5336_coded_sizes32-38.json` 全量 300s 跑通：70 片进求解（10 g 码 × 32-38）、`n_eroded=0`、输出 `real_density` 与 `width_mm`，result.json 字段完整，退出码 0。
- [ ] 非法配置（未知键 / 坏路径 / 坏类型 / 非字符串 sizeKey）均中文报错含字段名、退出码非 0。
- [ ] `git diff` 证明 web/ 四文件零改动；`paths.py` diff 仅 1 行新增常量、pyproject diff 仅 1 行新增 script。
- [ ] web 全链路（上传→parse→commit→WS 求解→导出）手测行为不变；web 求解与 CLI 并行互不干扰（intermediate mtime/内容不变）。
- [ ] 对拍：CLI intermediate 与 web commit 同母版产物 pid 集合 / total_area / 同 pid polygon 逐点一致。
- [ ] `ms-run-config` 与 `python -m materialsorting.cli.run_config` 双入口可用。

## 待确认问题 (Open Questions)

（无新增。本轮问题已于 2026-08-19 决议并入正文：① multi_seed 只做串行，总时长 = len(seeds) × time 可接受 → 非目标；② run_dir 加时间戳后缀保留历史、重跑不覆盖 → FR-5 / 设计考虑；③ 批量多配置评估本期不做、后续可能需要（result.json 机器可读已预留）→ 非目标；④ seed 相关三字段（seed/multi_seed/seed_count）收敛为单字段 `seeds` 列表 = 串行批次维度，无模式开关、无 clamp [2,6]、支持非连续种子 → FR-1 / US-001 / US-004。）
