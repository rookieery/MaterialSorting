"""US-002 CLI 子进程 spawn 冻结适配 —— spawn argv 前缀单一真相源。

高级/极限运行（``strategy.py`` ``_start_run``）与机器对接（``machine.py`` solve
spawn）派生 CLI 子进程时的 argv 前缀：

  - dev（未冻结）：``[sys.executable, '-m', 'materialsorting.cli.run_config']``
    —— 与既有 cmd 构造**逐字节一致**（红线：未冻结分支不变，回归锁 = 既有
    test_web_strategy / test_web_machine / test_web_extreme cmd 金标断言）；
  - frozen（Nuitka standalone，``sys.frozen`` 真 + ``sys.executable`` = 冻结
    exe）：``[sys.executable, CLI_FLAG]`` —— launcher ``--cli`` 子命令把余下
    argv 原样分发给 ``materialsorting.cli.run_config.main``（分发对端，退出码
    透传），策略长跑在客户机照常工作。

spawn 是**进程边界**而非 import 边界：本模块只产 argv 前缀，真 spawn 仍走
``strategy._spawn_run_process``（Windows taskkill ``/T`` 树杀零变化 ——
``exe --cli`` 子进程同为真 OS 子进程，run_config 再派生的 solve 孙进程同样
整树可见）。**模块级仅 import 标准库**（``sys``）：禁 import cli/server 等
任何业务模块（AST 守卫见 tests/test_web_frozen_spawn.py）；``CLI_FLAG`` 与
``launcher.CLI_FLAG`` 同串镜像，互引契约测试锁死（防一边改另一边漂移）。
"""
from __future__ import annotations

import sys

__all__ = ['CLI_FLAG', 'cli_spawn_prefix']

# launcher ``--cli`` 子命令旗标（镜像 ``launcher.CLI_FLAG``；两边同串由
# tests/test_web_frozen_spawn.py 契约对拍锁死，改动须两处同步）。
CLI_FLAG = '--cli'
# dev 态模块形式 = 既有 spawn cmd 前缀（未冻结分支逐字节不变口径的落点）。
_DEV_MODULE_ARGS = ['-m', 'materialsorting.cli.run_config']


def cli_spawn_prefix() -> list[str]:
    """CLI 子进程 argv 前缀（frozen → ``[exe, '--cli']``，否则 ``[python, -m, ...]``）。

    每次调用返回**新列表**，调用方自由 ``+=`` 拼接不污染后续 spawn。运行期现读
    ``sys.frozen`` / ``sys.executable``（非 import 期固化）—— 测试可 monkeypatch
    假标志切换分支；frozen 判据与 ``launcher.apply_frozen_env`` 同口径
    ``getattr(sys, 'frozen', False)``（属性缺失 = dev，PyInstaller/Nuitka 才设）。
    """
    if getattr(sys, 'frozen', False):
        return [sys.executable, CLI_FLAG]
    return [sys.executable, *_DEV_MODULE_ARGS]
