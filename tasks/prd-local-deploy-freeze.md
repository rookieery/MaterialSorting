# PRD: 客户本地部署 —— 源码保护冻结打包与一步运行

## 概述 (Overview)

当前排料引擎跑在我们自己的服务器上：算力受单机 CPU 限制、存在多实例互杀与公网隧道暴露面、客户母版数据出厂。本 PRD 把项目改造为可交付客户本地电脑运行的形态：**源码以 Nuitka 真编译为机器码冻结分发（需求1：客户不可见源码）**，配合 **launcher 一键启动 + Inno Setup 安装包（需求2：双击图标即用，无需 Python/admin）**，求解算力直接消耗客户自己的 CPU。

实勘结论（[客户本地部署_打包与运行方案_2026-09.md](../.docs/business/客户本地部署_打包与运行方案_2026-09.md) §一）：本项目对冻结打包异常友好——路径全环境变量化（[paths.py](../materialSorting-server/src/materialsorting/paths.py)）、求解子进程为顶层函数 + 全 JSON 参数（spawn 天然兼容冻结）、全 src 零动态 import。**唯一硬代码改动 = 子进程 spawn 适配（2 个落点）+ 新增 launcher 入口**，其余全部是构建脚本与验收编排。

**已定案的设计决策（源自方案文档，随本 PRD 一并确认）**：
① 打包工具 = **Nuitka standalone onedir**（真编译机器码；坚决不用 onefile——解压慢 + 杀软误报率高 + 多进程敏感）；Plan B = PyInstaller+PyArmor 仅作不可解依赖坑时回退，不在本 PRD 范围。
② v1 壳形态 = **控制台窗口 + 自动开默认浏览器**（日志可见、关窗即停、实现最简）；pywebview 原生窗口壳留 v2。
③ 分发形态 = **Inno Setup 中文安装包 + 绿色 zip 随首版一起交付**（同一 dist 双形态；安装包 per-user 免 UAC、桌面图标、卸载保留用户数据）。
④ frozen 时数据目录重定向 `%LOCALAPPDATA%\MaterialSorting\out`（安装目录只读安全）；**dev 模式（未冻结）路径与现状逐字节一致**。
⑤ **升级 = 手动覆盖安装**（2026-09-27 定案）：程序与用户数据物理分离（安装目录 vs `%LOCALAPPDATA%`）⇒ 覆盖安装 / zip 解压覆盖均天然保数据；程序内自更新不在本线（骨架备案见 Non-Goals）。
⑥ machine API 本地版**默认开**（随包即用，`MS_MACHINE_TOKEN` 认证闸照常；商业侧由 token 发放控制）。
⑦ 代码签名证书**不采购**（2026-09-27 定案；signtool 钩子保留，杀软误报走发版手册申诉指引兜底）。

**贯穿全程的回归红线**：
- 未冻结路径零变化：dev `ms-web` / `ms-run-config` / 全量 pytest / 既有 UI 冒烟，spawn cmd 未冻结分支与现产物**逐字节一致**（既有 `cmd == [sys.executable, '-m', ...]` 断言原样保留）。
- `paths.py` / `server.py` / `solver.py` 等既有模块**零改动**（env 覆盖机制现状已足够）；全部新代码进新文件（launcher、spawn helper、构建/验收脚本）。
- 分层红线延续：launcher 顶层模块**模块级仅标准库**（env 先于任何业务 import 的顺序红线，AST 守卫）；spawn helper 禁 import cli（web 层既有惯例）。
- 杀软误报治理：exe 带完整版本资源（company/product/version）；**不引入**任何加壳/混淆器（Nuitka 已是真编译）。
- 构建资源安全（2026-09-27 事故定案）：裸跑全核 Nuitka 视为事故级违规——build_freeze 必须限 jobs + 低优先级 + 孤儿 fail-fast（详见 US-003 AC8）；运维面构建前停 ms-web/长跑 solver 等常驻负载。

## 目标 (Goals)

- 冻结产物内**零 `.py`/`.pyc`/`.docs`/`tests`/`scripts` 泄漏**（grep 验收），后端源码以机器码 `.pyd` 形态交付，保护强度 ≈ C++ 商用软件。
- 客户动线两步：安装一次 → 双击图标 → 默认浏览器自动打开工作台（冷启动 ≤5s 量级）；无需 Python、无需 admin、磁盘 ~500MB。
- 冻结产物功能全等：普通求解（WS 帧）/ 导出 PLT-clean·DXF·PNG / **高级与极限运行（冻结 spawn 链路）** / 状态保存恢复 / SE 延长轮 warm 生效（spyrrow 元数据捆绑红线）全部可用。
- 用户数据（上传母版 / config_runs / run_stats.jsonl）落 `%LOCALAPPDATA%`，覆盖安装升级不丢。
- 构建流水线一键化：`scripts/build_freeze.py` 从源码到 dist（含安装包）单命令产出，版本号与 git tag 绑定。

## 用户故事 (User Stories)

### US-001: launcher 桌面入口模块（launcher.py）
- **Description**: As a 本地部署用户, I want 一个双击即起的入口——自动定位资源目录、探测空闲端口、启动服务并打开浏览器, so that 我不需要懂 Python/端口/环境变量，装完就能用；同时它承接冻结形态下 CLI 子进程的子命令分发（`--cli`）。
- **Acceptance Criteria**:
  1. 新模块 `src/materialsorting/launcher.py` + pyproject console_script `ms-desktop = materialsorting.launcher:main`。`main()` 第一行 `multiprocessing.freeze_support()`（PyInstaller 必须 / Nuitka 无害）；**模块级仅 import 标准库**（AST 守卫锁死——`web.server` 等业务 import 全部函数内延迟，保障「env 先于 paths.py import 期固化」顺序红线）。
  2. 子命令分发：`ms-desktop --cli <args...>` → `materialsorting.cli.run_config.main(args)`（延迟 import；退出码透传）；其余 argv → 桌面启动路径。
  3. frozen 环境重定向（仅 `getattr(sys, 'frozen', False)` 为真时，全部 `setdefault` 不覆盖显式 env）：`MS_STATIC_DIR = <exe 所在目录>/static`、`MS_OUT_DIR = %LOCALAPPDATA%/MaterialSorting/out`（目录不存在则 mkdir parents）；**未冻结（dev）路径零重定向**——`python -m materialsorting.launcher` 行为 = 原 `ms-web`（8010、repo 路径）。
  4. 端口探测：`MS_WEB_PORT` 显式给出则直接用；否则自 8010 起逐 +1 探测空闲（上限 +9），实际端口写 env 后再启动 server；把实际端口写入 `<OUT_DIR>/web_port.txt`（二次启动单实例判据）。
  5. 单实例：启动前读 `web_port.txt` 健康探测（GET `/` 2s 超时）命中 → 只开浏览器指向该端口、exit 0 不重复起服务；未命中/无文件 → 正常启动。
  6. 启动编排：主线程跑 uvicorn（复用 `web.server.main()` 的启动语义或直接调用其内部逻辑，不复制粘贴端口逻辑）；watcher 线程健康探测就绪后 `webbrowser.open(f'http://127.0.0.1:{port}')`（浏览器不早于服务就绪打开）。
  7. `--check` 自检子命令：打印 frozen 态 / 版本串（`importlib.metadata.version('materialsorting')`，US-003 捆绑本包元数据使其在冻结态同样可读——售后识别用户在跑哪个版本） / 解析后 env / `paths` 各常量落点 / 探测端口 / `warm_start_supported()` 结果，exit 0 —— 供冻结验收脚本（US-004）消费，无任何副作用（不起服务不开浏览器）。
  8. 测试（新增 `tests/test_launcher.py`）：AST 守卫（模块级 import 白名单 = 标准库）；env 重定向矩阵（frozen 真/假 × 显式 env 给/不给 四象限，断言 `paths.*` 常量落点——**在子进程或 importlib reload 隔离下测**，不污染测试进程全局 paths）；端口探测（8010 被占 socket 预占 → 选 8011）；单实例判据（假 web_port.txt + 假健康探测 stub）；`--cli` 分发（透传 argv 与退出码）；`--check` 输出含各键。
  9. `python -m materialsorting.launcher --check` 与 `python -m materialsorting.launcher --help` 跑通（help 打印子命令用法）；分层依赖未反向。
- **Priority**: 1

### US-002: CLI 子进程 spawn 冻结适配（strategy.py / machine.py）
- **Description**: As a 冻结形态的 web 服务, I want 高级/极限/机器对接运行派生 CLI 子进程时能感知冻结态改用 `exe --cli` 前缀, so that 策略长跑在客户机上照常工作；未冻结路径逐字节不变。
- **Acceptance Criteria**:
  1. 新增共享 helper（`materialsorting/web/_frozen_spawn.py` 或等价小模块）：`cli_spawn_prefix() -> list[str]`——`sys.frozen` 真时返回 `[sys.executable, '--cli']`，否则返回 `[sys.executable, '-m', 'materialsorting.cli.run_config']`；模块禁 import cli/server（AST 守卫或按 web 层惯例测试锁定）。
  2. 两处调用点改造：[strategy.py](../materialSorting-server/src/materialsorting/web/strategy.py) `_start_run` 的 cmd 构造、[machine.py](../materialSorting-server/src/materialsorting/web/machine.py) spawn cmd 构造——`cmd = cli_spawn_prefix() + [str(cfg_path), ...]`，**后续参数拼接与 `_spawn_run_process` / marker / run_dir 认领 / taskkill `/T` 树杀零改动**。
  3. 契约对拍单测：`cli_spawn_prefix()` frozen 分支产物与 launcher `--cli` 分发约定一致（两边同源常量或互引测试锁死，防一边改另一边漂移）。
  4. 回归锁：既有断言 `cmd == [sys.executable, '-m', 'materialsorting.cli.run_config', ...]`（test_web_strategy / test_web_machine / test_web_extreme）**原样通过**（未冻结分支逐字节一致）；新增 frozen 假标志单测（monkeypatch `sys.frozen` + fake `sys.executable`，断言前缀切换、其余参数不变）。
  5. Python 模块导入检查通过（`materialsorting.web._frozen_spawn`、`materialsorting.web.strategy`、`materialsorting.web.machine`），分层依赖未反向。
- **Priority**: 2

### US-003: Nuitka 冻结构建脚本（scripts/build_freeze.py）
- **Description**: As a 发版维护者, I want 一条命令从源码产出可分发 onedir 目录, so that 发版可重复、依赖闭包与数据文件全部显式声明，不依赖手工记忆。
- **Acceptance Criteria**:
  1. 新增 `scripts/build_freeze.py`（venv python 直跑，仅标准库 + subprocess 调用外部工具）：步骤 = ①前端 static 存在性检查（缺则提示先 `npm run build`，`--skip-frontend-check` 跳过）；②环境自检（nuitka/zstandard 缺则给出 pip 命令；C 编译器缺失时提示 Nuitka 自动下载 MinGW64 或装 MSVC Build Tools，两者皆备优先 MSVC）；③spyrrow 版本检查——`spyrrow_build.json` 钉板与已装版本一致性 + `+ms<N>` tag 校验，不满足则**退出 1**（防打包锁错 wheel 静默失去 warm，A2 红线）；④Nuitka 编译；⑤dist 自检（见 AC4）。
  2. Nuitka 命令组装（脚本内常量段，逐旗标注释）：`--standalone --onedir`；入口 = `materialsorting/launcher.py`；`--include-package=materialsorting`；matplotlib/numpy/shapely 按插件/数据需要显式启用（`--enable-plugin=...` / `--include-package-data=...`，以实际调通为准并注释原因）；**`--include-distribution-metadata=spyrrow` 红线旗标**（warmstart 探测依赖）+ `--include-distribution-metadata=materialsorting`（运行期版本串显示依赖，见 US-001 `--check`）；`--include-data-dir=<static>=static`（前端产物）；版本资源 `--company-name/--product-name/--file-version/--file-description`（版本号 = pyproject version + git describe 短串，取不到 git 则纯版本号）；`--windows-console-mode=force`（保留控制台）；`--output-dir=dist`；`--jobs=N`（**资源红线**，取值规则见 AC8，绝不落回 Nuitka 缺省=全核并发）。
  3. 构建幂等：dist 目录先清后建；任何步骤失败退出非 0 并打印失败步骤名。
  4. dist 自检（脚本内置，构建尾部自动跑）：dist 内 grep `.py`/`.pyc`/`.docs`/`tests`/`scripts` 零命中（源码泄漏红线）；`MaterialSorting.exe --check` 跑通且输出 `frozen: True`、`warm: True`（**spyrrow 元数据捆绑的判据**）、static/fonts 路径存在。
  5. 本机端到端冒烟（AC 判据，人工/脚本拉起 dist 实例）：上传母版 → parse → 短预算求解（WS 帧回来）→ 导出 PLT-clean / DXF / **PNG（matplotlib 路径）**；高级运行 `--strategy race` 短预算跑通（冻结 spawn `exe --cli` 链路 + run_dir 产物落 LOCALAPPDATA）；SE 延长轮 warm 生效签名（ext 首帧即冠军密度）。
  6. 脚本支持 `--launch` 直接拉起 dist 冒烟实例（打印 URL，Ctrl-C 退出）；文档化注释头写明构建机一次性准备（MSVC 或让 Nuitka 下 MinGW、node、Inno 可选）。
  7. Python 模块/脚本入口检查通过（`python scripts/build_freeze.py --help`）；脚本不改任何既有 src 文件。
  8. **资源安全三重防护（2026-09-27 整机假死事故复盘，红线）**：①Nuitka 命令必含 `--jobs=N` 显式上限——默认 `min(8, max(2, os.cpu_count() // 4))`，再按可用物理内存钳制（ctypes `GlobalMemoryStatusEx` 仅标准库，每 job 预留 ≥3GB，不足降 jobs 下限 2 并打印推导；`--jobs` 参数 / `MS_FREEZE_JOBS` env 可覆盖），**绝不落回 Nuitka 缺省（= 逻辑核数全核并发）**——事故机理：本机 32 并发 cl.exe 编大 TU 单进程峰值 1~3GB，提交需求远超物理 31.7G（页面文件仅 ~2G 零余量）⇒ 缺页风暴 + 全核满载锁死 UI/系统进程，硬重启收场（Kernel-Power 41/6008 @2026-09-27 12:23、clcache 仅 44 obj/1224 .c）；②编译子进程树低优先级启动：`subprocess.Popen(creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)`（非 Windows 平台 `getattr` 缺省 0 优雅降级）——满载时 UI 仍可响应、保留抢回控制权能力；③孤儿 fail-fast：构建前扫描存活 nuitka/cl.exe/ccache/clcache/scons 编译进程（硬重启残留叠加 = 双倍风暴），发现即 exit 1 打印进程名+PID，`--force` 才放行。启动时打印核数/可用内存/jobs 数/预估时长（30~90min）。
  9. `--dry-run`：打印完整 Nuitka 命令行 + 环境自检 + jobs 推导，不执行编译（快速验证与回归断言入口）；验收断言输出含 `--jobs=` 且本机 32 核上值 ≤8 ≠32（防回归到全核缺省）。
- **Priority**: 3

### US-004: 冻结验收自动化（scripts/smoke_freeze.mjs + 验收清单）
- **Description**: As a 发版维护者, I want 把冻结版验收固化成可重复脚本——隔离用户目录、全功能冒烟、单实例/端口回退/数据落点专项, so that 每次发版同口径过闸，不靠手工点验；真实虚拟机/杀软观察作为人工运营步骤在文档留 checklist。
- **Acceptance Criteria**:
  1. 新增 `scripts/smoke_freeze.mjs`（Node，playwright Edge 通道，沿用既有 smoke 套路）：编排 = 临时 `MS_OUT_DIR`（模拟 LOCALAPPDATA 隔离）→ 拉 dist exe（环境注入 OUT_DIR 覆盖）→ 等健康 → 依序跑核心动线：上传母版 → parse 数量矩阵 → 短预算求解 → 导出三格式落盘校验 → 状态保存 `.msn` 下载；既有 smoke 族（smoke_prefix_extra / smoke_state_file / smoke_edit_polish）可经 base-url 参数指向冻结实例复跑（脚本若硬编码 8010 则做最小 additive 参数化，默认值不变）。
  2. 专项断言：①端口回退（预占 8010 再启动 → 实际用 8011，`web_port.txt` 内容一致）；②单实例（二次启动 exit 0、进程数不增、浏览器 URL 指向既有端口）；③数据落点（产物全部出现在临时 OUT_DIR，dist 安装目录 mtime/内容零变化——只读安全）；④高级运行产物 `config_runs/web_*` 落临时 OUT_DIR。
  3. 退出码语义：全部检查过 = 0；任一失败 = 非 0 并逐条打印失败项；输出含通过项计数（对齐既有 smoke 脚本「N/N」惯例）。
  4. 人工运营 checklist 落文档（US-005 发版手册内）：无 Python 全新 Windows 虚拟机安装运行、360/火绒/Defender 三杀软默认配置观察、CPU 配置基线话术（4 核 8G 起步 / 8 核 16G 推荐、求解时长与单核性能线性相关）——标注为**运营步骤**非本故事自动判据。
  5. 本机跑通：dev（未冻结 exe 缺失时明确报错指路 build_freeze）+ 冻结产物双形态各全绿一次。
- **Priority**: 4

### US-005: Inno Setup 安装包与发版手册
- **Description**: As a 本地部署交付者, I want dist 打成中文安装包（桌面图标/per-user 免 UAC/卸载保留用户数据）并沉淀发版手册, so that 客户拿到的是单个 setup.exe、装完桌面即见图标，我们自己发版有章可循。
- **Acceptance Criteria**:
  1. 新增 `scripts/installer/materialsorting.iss`（Inno Setup）：中文向导（DefaultDirName={localappdata}\Programs\MaterialSorting per-user 免 UAC）、桌面图标任务、卸载**不删** `%LOCALAPPDATA%\MaterialSorting`（用户数据/上传母版保留）、安装前检测运行中进程提示关闭（[Setup] AppMutex 或等价）、`Uninstallable` 默认、版本号经 ISCC `/D` 参数注入（与 build_freeze 同源版本串）。
  2. `build_freeze.py` 增 `--installer` 步骤：PATH 找 `ISCC.exe` → 编译 iss → `dist/MaterialSorting-Setup-<版本>.exe`；ISCC 不存在 → 打印安装指引（含官网/中文语言包）并**跳过不失败**（exit 0，其余产物完整）；signtool 钩子：env `MS_SIGNING_PFX`/`MS_SIGNING_TS` 在场才调用（证书采购为运营事项，代码路径预留）。
  3. 发版手册 `.docs/technical/本地部署构建与发版手册.md`：构建机一次性准备（MSVC/MinGW、node、Inno）、日常发版三步（tag → build_freeze --installer → 归档）、验收 checklist 引用（US-004 自动 + 人工运营项）、**升级动线**（安装包 = 双击覆盖安装；zip = 解压覆盖原目录——两种形态用户数据均在 `%LOCALAPPDATA%` 不受触碰；版本识别 = exe 属性页 / `--check` 版本串）、杀软误报申诉指引（微软/360/火绒提交入口）。
  4. 绿色 zip 副产品：`--installer` 同步产出 `MaterialSorting-portable-<版本>.zip`（dist 压缩，解压即用；zip 内附一行启动说明 txt）。
  5. 装有 Inno 的机器上 ISCC 编译成功且 setup.exe 安装/卸载/重装一轮人工验证过（手册记录实测日期）；无 Inno 机器 `--installer` 跳过路径验证。
- **Priority**: 5

## 功能需求 (Functional Requirements)

- FR-1: 冻结保护口径：交付物 = Nuitka standalone onedir，后端源码全部机器码化；dist 内不得存在 `.py`/`.pyc` 及 `.docs`/`tests`/`scripts` 内容（构建自检 grep 红线）；`.venv`/`node_modules`/`out/` 永不进包。
- FR-2: 一步运行动线：安装（一次）→ 双击图标 → 控制台窗口 + 默认浏览器自动打开 `http://127.0.0.1:<port>`；关窗 = 服务停止；二次双击不重复起服务只开浏览器。
- FR-3: 端口策略：`MS_WEB_PORT` 显式优先；缺省自 8010 探测空闲（+1 递增至多 +9），实际端口写 `<OUT_DIR>/web_port.txt`；服务恒绑 `127.0.0.1`（现状不动）——不触发防火墙弹窗、不暴露局域网。
- FR-4: 数据目录（仅 frozen 重定向，全部 setdefault）：`MS_OUT_DIR=%LOCALAPPDATA%\MaterialSorting\out`、`MS_STATIC_DIR=<安装根>\static`；`MS_FONT_DIR` 走缺省包内路径（Nuitka 数据捆绑保持包结构）；dev 模式零重定向。
- FR-5: CLI spawn：冻结态前缀 `[exe, '--cli']`，未冻结 `[python, '-m', 'materialsorting.cli.run_config']`（逐字节 = 现状）；单源 helper + launcher 分发契约对拍锁。
- FR-6: spyrrow 私有 wheel `+ms<N>` 与发行版元数据必须随包（构建期强校验 + `--check`/冒烟运行期验证 `warm_start_supported()` 为 True）。
- FR-7: 构建一键化与版本化：`scripts/build_freeze.py` 单命令产出 dist（+安装包/zip 双形态）；版本资源 = pyproject version + git describe；构建参数全显式、幂等可重入。
- FR-8: 升级动线（v1 = 手动覆盖安装）：程序与用户数据物理分离（安装目录 vs `%LOCALAPPDATA%\MaterialSorting\out`），覆盖安装 / zip 解压覆盖均不触碰用户数据；安装器检测运行中进程提示关闭；运行期版本串可查（`--check`）用于售后识别用户版本。

## 非目标 (Non-Goals)

- **需求 3 key 授权**（时限/次数/服务器签发）——单独 PRD，不阻塞本线。
- pywebview 原生窗口壳、系统托盘、开机自启（v2 形态升级项）。
- **程序内自更新**（检查更新/下载/自动重启安装，2026-09-27 定案不做）——v1 = 手动分发 setup.exe/zip 覆盖安装。若后续发版频繁再立项，已备案骨架：公网静态版本清单 JSON（版本+下载 URL+SHA256+更新说明，分发端可复用 frp 公网机或对象存储）+ 前端「检查更新」**显式触发**（工厂环境不做后台静默）+ 下载安装包哈希校验后拉起 Inno 安装器；差分下载/静默热更新明确不做。
- macOS / Linux 交付（客户场景 Windows x64；launcher 的非 Windows 分支仅保证 dev 可跑不做交付验收）。
- 代码签名证书采购与真实签名（2026-09-27 定案不采购；代码仅预留 signtool 钩子，误报走申诉指引）。
- uvicorn[standard] 瘦身（watchfiles/httptools 替换为标准版）、matplotlib 替换（体积优化收益小风险大）。
- machine API（YL 对接）是否对客户启用——商业决策，技术随包可用不在本线改动。
- launcher 滚动日志文件（v1.1 可选；v1 控制台窗口即日志）。

## 设计考虑 (Design Considerations)

- **import 顺序红线**：`paths.py` import 期固化路径常量、`server.py` import 期 mount static + 读 intermediate——launcher 必须「设 env → 再延迟 import 业务」，AST 守卫 + 子进程隔离单测双锁；这是全链最易踩的静默错误（不报错但写错目录）。
- 控制台窗口是特性不是妥协：现场排障第一现场就是黑窗日志；关窗 = 进程树根终止，与现有 kill 语义一致。浏览器就绪探测后再 `webbrowser.open`，避免首开白页。
- onedir 而非 onefile 是杀软/启动速度/多进程三重权衡的定案；Inno 压缩（LZMA）已把分发体积降到 ~120-200MB 级。
- 安装包 per-user（LOCALAPPDATA）优先：工厂机器常见无 admin 场景；`Program Files` 只读风险由 OUT_DIR 重定向根治，双保险。

## 技术考虑 (Technical Considerations)

- Nuitka 依赖闭包要点：pydantic-core/spyrrow 为 pyo3 Rust 扩展（随 DLL 依赖自动收）；shapely 的 GEOS ctypes DLL、matplotlib 自带数据是两个已知试错点（US-003 预留弹性）；uvicorn[standard] 的 websockets 必须在闭包内（WS 冒烟覆盖）。
- `multiprocessing.freeze_support()` 必须是 main() 第一行；Nuitka 对 spawn 子进程有内建处理，调用无害——双保险写法。
- 树杀兼容性：`taskkill /T /F` 与 marker/run_dir 认领逻辑对「exe --cli 子进程」行为与 python 子进程一致（同为真 OS 子进程），strategy/machine 该层零改动。
- `web_port.txt` 单实例方案的竞态边界：多用户快速切换场景可能双起（健康探测兜底指向先起者），接受；命名互斥体（ctypes）为 v2 加固项不进 v1。
- spyrrow 构建锁：打包前 `scripts/spyrrow_wheel.py status` 校验安装态 = 钉板，防止「PyPI 0.9.0 无 warm」的静默降级版本被冻进包。
- 体积预算：onedir 250-400MB（matplotlib ~60MB 大头）、安装包 120-200MB、冷启动 2-5s（Python 运行时 + import 链初始化）。

## 成功指标 (Success Metrics)

- [ ] dist 源码泄漏 grep 零命中（.py/.pyc/.docs/tests/scripts）——需求 1 达成的直接判据。
- [ ] 冻结实例端到端全绿：上传→parse→求解→导出三格式→高级运行→状态保存恢复（smoke_freeze + 既有 smoke 族复跑）。
- [ ] 冻结态 `warm_start_supported() == True` 且 SE 延长轮 warm 生效签名可见。
- [ ] 端口回退/单实例/数据落 LOCALAPPDATA 三专项断言通过；dev 路径全量 pytest 零回归。
- [ ] 装有 Inno 的机器产出 setup.exe 并完成安装/卸载/覆盖升级一轮实测；版本资源完整（文件属性页可见公司/产品/版本）。
- [ ] 双击图标 → 浏览器就绪 ≤5s（本机 SSD 实测量级）。

## 待确认问题 (Open Questions)

- 构建机环境由谁/何时准备（MSVC Build Tools 或 Nuitka 自动 MinGW、Inno Setup、node 已有）——影响 US-003 首跑时间。

（已定案 2026-09-27：签名不采购 / 绿色 zip 随首版交付 / 安装目录 per-user LOCALAPPDATA / machine API 默认开 / 升级 = 手动覆盖安装、程序内自更新不做——详见概述「已定案的设计决策」③⑤⑥⑦与 Non-Goals。）
