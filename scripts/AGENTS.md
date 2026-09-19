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
