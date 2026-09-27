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
  tests/scripts 泄漏零命中 + exe --check frozen/warm/version/static/fonts）。
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
  `materialSorting-server/tests/test_build_freeze.py`（35 例纯函数级，真跑 Nuitka
  不进套件）。验收自动化（隔离用户目录/单实例/端口回退专项）= US-004
  smoke_freeze.mjs（后续故事，不在本文件范围）。
