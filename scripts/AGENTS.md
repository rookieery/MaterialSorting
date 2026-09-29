# scripts/ — repo 根维护与实验脚本

> 非包内代码（不属 `materialsorting` 分层），仓库根 `scripts/` 下的一次性探针、
> 实验、A/B 回放器与维护工具。**改 `.py` 前先看 `AGENTS.md`（各目录）与
> `.docs/technical/agent-file-map.md` repo 根脚本节。**

## 惯例

- **sys.path 自引导**（脚本要 import 本仓包时，对齐既有形态三选一）：
  - `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'materialSorting-server' / 'src'))`（embed_piece_codes.py / smoke_plt_clean.py / **spyrrow_wheel.py**）；
  - `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'materialSorting-server', 'src'))`（extreme_ab_replay.py `_SERVER_SRC`）；
  - 兄弟脚本互 import（depth_ab_analyze.py 复用 pctgrid_analyze 的常量）则插 scripts 自身目录。
- 产物只落 `out/` 下（`config_runs/` / `_probes/` 等），不碰 web 事实源。
- Windows 控制台默认 GBK：面向用户的 CLI 输出中文/特殊字符前 best-effort
  `sys.stdout.reconfigure(encoding='utf-8')`（且要早于 argparse `--help`）。

## spyrrow_wheel.py（US-004，prd-warm-start-phase1）

spyrrow 双源切换助手（PyPI 0.9.0 ↔ spyrrow-ms 私有 wheel `0.9.0+msN`）：
`status`（缺省命令：安装源/版本/warm 探测/钉板一致性，恒 exit 0）/ `use-pypi`
/ `use-local <wheel>`（错误路径 exit 1 绝不触 pip）。pip 永远
`sys.executable -m pip`；use-local 带 `--no-deps` 只换 spyrrow 一个发行版；
装后 `importlib.invalidate_caches()` 读回验证。rev 钉板
`materialSorting-server/spyrrow_build.json` 只读 + 漂移提示（四字段单一真相源
在 spyrrow-ms 侧）。用法手册 = `.docs/technical/spyrrow私有wheel构建与升级手册.md`；
护栏测试 = `materialSorting-server/tests/test_spyrrow_wheel.py`（纯桩不真跑 pip）。

## build_freeze.py + freeze_entry.py（US-003，prd-local-deploy-freeze）

**Nuitka 冻结构建一条命令**：`.venv/Scripts/python.exe scripts/build_freeze.py`（必须
venv python 直跑——nuitka/spyrrow/materialsorting 都在 venv）→
`dist/MaterialSorting.dist/MaterialSorting.exe`（standalone onedir 真编译机器码；
**不用 onefile** = PRD 定案：解压慢/杀软误报/多进程敏感）。

- `freeze_entry.py` = Nuitka 入口适配层：launcher.py 相对 import 的包模块不能直接
  当脚本编译，本文件 sys.path 自引导 + 绝对 import；**并在 import launcher 前桥接
  `sys.frozen = True`**（仅 `'__compiled__' in globals()` 真编译态守卫——Nuitka
  不设 sys.frozen 而官方口径是模块级 `__compiled__`，不桥接则 launcher env 重定向
  与 web/_frozen_spawn 的 exe --cli 前缀永远走 dev 分支；dev 直跑本文件零变化）。
  桥接顺序由 tests/test_build_freeze.py AST 断言锁死。
- build_freeze 六步：①前端 static 检查（--skip-frontend-check 跳）②环境自检
  （nuitka 版本/zstandard/ordered-set；**验证基线 Nuitka 4.3rc3**，4.2.2 优化器
  对本闭包偶发 mergeBranches 内部 TypeError、缺 ordered-set 退回纯 Python
  fallback 同样偶发崩）③spyrrow 钉板校验（wheel_version 一致 + `+ms<N>` N≥1 +
  dev 态 warm_start_supported() 预探测，不满足 exit 1）④孤儿编译进程 fail-fast
  （--force 放行）⑤Nuitka 编译（**--mingw64 强制**：MSVC cl 14.3 编巨型 TU 两轮
  不同模块本体崩溃 C1001/0xC0000005；双元数据红线
  `--include-distribution-metadata=spyrrow` + `=materialsorting`；ASCII 版本资源
  ——中文进 .rc 被 cl 按代码页 936 误读 C2001）⑥dist 自检（.py/.pyc/.docs/
  tests/scripts 泄漏零命中 + exe --check frozen/warm/version/static/fonts/**data**）。
- **样例母版捆绑（2026-09-29「exe 无可用样例」bug 修复）**：repo `data/` 顶层
  `.dxf` 逐文件 `--include-data-file=<abs>=data/<name>` 捆到 exe 同级 `data/`
  （**必须逐文件**——`.plt` 参考件与 `configs/` 实验配置是内部资产不进客户包；
  文件名含 `=` fail-fast 防参数解析错位）；frozen 态 `MS_DATA_DIR` 由
  `launcher.apply_frozen_env` setdefault 指向该目录（`/api/samples` 列表与 key
  闸门样例豁免 sha256 对拍共用，此前两处都悬空 → 下拉恒空）；双重自检 = 构建期
  `step_static_check` 样例预检（data/ 空 fail）+ `step_dist_check` data 落点
  硬校验。
- **资源红线（2026-09-27 整机假死事故复盘）**：`--jobs` 推导
  `min(8, max(2, 核数//4))` 再按可用物理内存钳制（每 job ≥3GB、下限 2，
  `--jobs`/`MS_FREEZE_JOBS` 覆盖仍打警示）/ Nuitka 子进程
  BELOW_NORMAL_PRIORITY_CLASS / 孤儿 fail-fast；启动横幅打印推导过程。
- `--dry-run` 打印完整命令行 + 自检 + jobs 推导不编译（回归断言入口，须见
  `--jobs=` ≤8 ≠全核）；`--launch` 直接拉起 dist 冒烟（Ctrl-C 退出）。
- 运维坑留档（脚本头注记）：硬重启会留零填充 clcache 对象（NTFS 已分配未刷盘），
  下轮链接期 `CVTRES CVT1107 xx.obj 已损坏` → 删
  `%LOCALAPPDATA%/Nuitka/Nuitka/Cache/clcache` 全量重编。
- 产物 `dist/` 已 gitignore（根 .gitignore）；护栏测试 =
  `materialSorting-server/tests/test_build_freeze.py`（55 例纯函数级，真跑 Nuitka
  不进套件）。验收自动化（隔离用户目录/单实例/端口回退专项）= US-004
  smoke_freeze.mjs；发版全流程 = US-005 `.docs/technical/本地部署构建与发版手册.md`。

## installer/materialsorting.iss + ChineseSimplified.isl（US-005，prd-local-deploy-freeze）

**Inno Setup 中文安装包 + 绿色 zip**（第 7 步，`build_freeze.py --installer` /
`--installer-only` 补打包调用）：

- **iss 要点**：per-user 免 UAC（`PrivilegesRequired=lowest` +
  `{localappdata}\Programs\MaterialSorting`）/ 固定 AppId 同 ID 覆盖安装 = 升级 /
  单一中文语言（`ShowLanguageDialog=no`，语言包 vendor 进仓免二次下载）/ 桌面图标
  task 默认勾选 / 卸载保留用户数据（无 `[UninstallDelete]`，数据在
  `%LOCALAPPDATA%\MaterialSorting` 不受触碰）/ 版本 `/D` 三 define 注入
  （`MyAppVersion`=display、`MyAppVersionNumber`=数字四段、`MyAppVersionFS`=文件名
  安全串，iss 头 `#ifndef` 占位可手工裸编）。
- **运行中检测（实勘坑，必守）**：app 未做命名互斥体 → `[Code]` tasklist 查镜像名
  等价实现；**MB_RETRYCANCEL 不受 `/SUPPRESSMSGBOXES` 抑制** —— 静默安装/卸载必须
  判 `WizardSilent()`/`UninstallSilent()` 直接中止（exit 1），否则无头部署挂死在
  看不见的弹窗（2026-09-27 实测，测试已锁定）。
- **build_freeze 侧**：ISCC 定位 PATH → `%LOCALAPPDATA%\Programs\Inno Setup 6`
  （winget --scope user）→ Program Files 兜底；缺席打印指引**跳过不失败**；signtool
  钩子 env `MS_SIGNING_PFX`+`MS_SIGNING_TS` 同在场才调用；绿色 zip 恒产（单一顶层
  `MaterialSorting/` + 一行启动说明.txt）。`fs_version()`（空白折叠 `-`）是
  setup.exe/zip 命名单一真相源。
- 实测记录（2026-09-27：ISCC 编译/静默安装/运行检测中止/卸载数据幸存/重装全绿）
  与日常发版三步、升级动线、杀软申诉 = `.docs/technical/本地部署构建与发版手册.md`。

## smoke_freeze.mjs（US-004，prd-local-deploy-freeze）

**冻结验收自动化一条命令**：`node scripts/smoke_freeze.mjs [--exe <path>] [--keep]
[--rerun-family]`。前置 = dist 已构建 + 8010/8011 空闲（有 dev ms-web 先停）；
报告 `out/smoke_freeze/report.json`，退出码 0=全过 / 1=任一失败（逐条打印）/
2=dist 缺失（dev 形态明确报错指路 build_freeze，AC5 判据）。

- 六相位：P0 `exe --check`（frozen/warm/version/OUT_DIR env 注入）→ P1 端口回退
  （临时 `MS_OUT_DIR` 模拟 LOCALAPPDATA 隔离 + Node net.Server 预占 8010 → 断言
  实际用 8011 + web_port.txt 一致）→ P2 核心动线（playwright Edge 通道：上传 →
  parse 数量矩阵 → 12s 求解 final → PLT-clean/DXF-R12/PNG 三格式落盘探针 →
  .msn 下载 gunzip schema）→ P3 高级运行（strategy race → run_dir 落临时 OUT_DIR
  `config_runs/web_*` + best_frame + 运行中 exe 进程数 ≥2 → stop 收敛）→
  P4 `--rerun-family` 既有 smoke 族经 `SMOKE_BASE_URL` 指向 :8011 复跑 → P5 单实例
  （二次启动 exit 0/URL 指向既有端口/进程数不增）→ P6 数据落点（产物全落临时
  OUT_DIR + dist 安装目录 stat 快照 + exe sha256 前后零变化，只读安全）。
- **实勘坑（首轮红）**：超排 Tab 解锁联动 parse done 而 commit 后台仍在跑 ——
  `#start` 抢跑会被 WS 以「排料数据为空」error 帧拒（无 worker 无帧）；commit-done
  判据 = ptypes 代表裁片**轮询**非空（smoke_edit_polish 同款；
  smoke-extreme-run.mjs 注记的 `[data-testid=commit-status].done` 等价口径）。
- **--rerun-family 首轮两红（2026-09-27，均已修）**：① prefix_extra 5g 门幅常量
  1980 漏随 580eb78（幅宽默认 198→175cm）锁步 → 对冻结与 dev 同样误红，修 = 1750
  （DOM 列高 1739.7 与构造 H=1750−10.388 全等证非冻结侧）；② 全族背靠背复跑在
  TTL 600s 内累积 >6 会话 → 第 7 个 `POST /api/session` 429（edit_polish 超排 Tab
  永不解锁即此因），修 = `--rerun-family` 时对 exe 注入 `MS_SESSION_MAX=16`
  （上限行为由 test_web_sessions 锁定，非被测面）。
- **浏览器 URL 取证**：spawn exe 注入 `BROWSER=cmd /c echo %s>><log>`（webbrowser
  退 GenericBrowser 走 `'%s'` shlex.split 分支）→ webbrowser.open 实参追加进日志，
  不起真浏览器；首启 watcher 与单实例二次启动的 URL 都可确定性断言（比 US-003
  E2E 的 `BROWSER=findstr` 只抑制更进一步）。路径必须正斜杠（shlex 不吃反斜杠）。
- 临时 OUT_DIR 失败保留诊断（`--keep` 恒保留；成功自动删）；playwright 借
  `materialSorting-web` 的 node_modules 安装（repo 根无，smoke_edit_layout 同款
  createRequire 锚 package.json）。
- 人工运营 checklist（无 Python 虚拟机安装 / 360·火绒·Defender 观察 / CPU 基线
  话术 4 核 8G 起步 8 核 16G 推荐）= US-005 发版手册**运营步骤**，非本脚本自动判据。

## make_app_icon.py（2026-09-27，VB超排 更名定稿）

应用图标生成器（Pillow + Windows 系统字体纯本地渲染，1024 超采样出 512）。
候选期共产出 12 稿（`out/icon_candidates/`，preview.html 浏览器挑选），用户定稿
**02「嵌套裁片·冰蓝」**（浅蓝圆角方 + 白色唛架条带 + 三块丹宁蓝裁片）。定稿资产
入库 `scripts/installer/app.ico`（多尺寸 16~256）+ `app.png`（512），重生成：

    .venv/Scripts/python.exe scripts/make_app_icon.py --index 2 --ico scripts/installer/app.ico
    .venv/Scripts/python.exe scripts/make_app_icon.py --index 2 --outdir scripts/installer
    （重命名 02_c02.png → app.png）

消费点：`build_freeze.py` Nuitka `--windows-icon-from-ico`（exe 图标）+
`materialsorting.iss` `SetupIconFile`（安装器图标）+ 前端 `public/favicon.png`。
改设计改对应候选函数重跑即可；`--index`/`--ico` 见模块 docstring。
