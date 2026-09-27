"""US-002 CLI spawn 冻结适配测试（web/_frozen_spawn.py 单元 + 契约 + AST 守卫）。

覆盖（prd-local-deploy-freeze US-002 AC1/AC3/AC4）：
  - AST 守卫：``_frozen_spawn.py`` 模块级仅标准库 import（``sys``）+ 全模块禁
    import 任何 materialsorting 业务模块 / 相对 import（cli/server/strategy/
    launcher 均不得牵入 —— spawn 前缀 helper 不反向依赖任何层）；
  - 前缀双分支：dev 缺省 = ``[sys.executable, '-m', 'materialsorting.cli.
    run_config]``（红线：未冻结分支与既有 cmd 构造逐字节一致）；``sys.frozen``
    真 + 假 executable → ``[exe, '--cli']``（exe --cli 子进程同为真 OS 子进程，
    taskkill /T 树杀语义不变）；显式 ``sys.frozen=False`` 同 dev（口径与
    launcher.apply_frozen_env 的 ``getattr(sys, 'frozen', False)`` 一致）；
  - 契约对拍（AC3）：``CLI_FLAG`` 与 ``launcher.CLI_FLAG`` 同串锁死 + frozen
    前缀 = ``[exe, launcher.CLI_FLAG]``（launcher ``--cli`` 分发对端，防一边改
    另一边漂移；launcher 侧 argv 分发行为由 tests/test_launcher.py 存量例覆盖）；
  - 返回新列表：两次调用互不影响（调用方 ``+=`` 拼接不污染常量）。

E2E 冻结态 spawn cmd（前缀切换 + 余下参数不变）由 test_web_strategy /
test_web_extreme / test_web_machine 各自的 frozen 用例覆盖（同款假标志口径）。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

from materialsorting import launcher as launcher_mod
from materialsorting.web import _frozen_spawn as fs_mod


# ------------------------------------------------------------- AST 守卫


def test_ast_guard_frozen_spawn_stdlib_only():
    """分层守卫：模块级 import 白名单 = 标准库（sys/__future__），全模块禁
    import materialsorting 业务模块与相对 import（镜像 test_launcher.py /
    test_web_strategy.py 守卫写法）。"""
    src = Path(fs_mod.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    # 全模块（含函数体）禁 import cli/server 等任何业务模块（绝对 + 相对形态）。
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, '禁相对 import（不得牵入 web 包内任何模块）'
            root = (node.module or '').split('.')[0]
            assert root != 'materialsorting', node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split('.')[0] != 'materialsorting', alias.name
    # 模块级顶层仅标准库白名单（函数内无任何 import 已由上面的全模块扫描覆盖）。
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or '')
    assert names, '守卫防空转：_frozen_spawn.py 应有模块级标准库 import'
    bad = [n for n in names if n.split('.')[0] not in {'sys', '__future__'}]
    assert not bad, f'_frozen_spawn.py 模块级出现非白名单 import：{bad}'


# ------------------------------------------------------------- 前缀双分支


def test_prefix_dev_default_matches_legacy_bytes():
    """dev 缺省分支 = 既有 cmd 前缀逐字节（红线：未冻结分支不变；回归锁另有
    test_web_strategy / test_web_machine / test_web_extreme 的 cmd 金标断言）。"""
    assert fs_mod.cli_spawn_prefix() == [
        sys.executable, '-m', 'materialsorting.cli.run_config']


def test_prefix_frozen_switch(monkeypatch):
    """sys.frozen 真 + 假 executable → [exe, '--cli']（真 OS 子进程，树杀语义
    不变；monkeypatch raising=False 兼容属性本不存在的 dev 解释器）。"""
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    fake_exe = r'C:\dist\MaterialSorting\MaterialSorting.exe'
    monkeypatch.setattr(sys, 'executable', fake_exe)
    assert fs_mod.cli_spawn_prefix() == [fake_exe, '--cli']


def test_prefix_frozen_false_explicit_is_dev(monkeypatch):
    """显式 sys.frozen=False 同 dev（与 launcher.apply_frozen_env 同口径：
    getattr 真值判定，非「属性在场」判定）。"""
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    assert fs_mod.cli_spawn_prefix() == [
        sys.executable, '-m', 'materialsorting.cli.run_config']


def test_prefix_returns_fresh_list():
    """每次调用返回新列表：调用方 += 拼接余下参数不漂移污染后续 spawn。"""
    a = fs_mod.cli_spawn_prefix()
    a.append('--mutation')
    assert '--mutation' not in fs_mod.cli_spawn_prefix()


# ------------------------------------------------------------- 契约对拍（AC3）


def test_contract_launcher_cli_flag_lock(monkeypatch):
    """契约对拍：CLI_FLAG 两边同串 + frozen 前缀旗标位 = launcher.CLI_FLAG ——
    launcher ``--cli`` 把余下 argv 原样分发给 cli.run_config.main（对端行为由
    test_launcher.py 存量分发/退出码透传例覆盖），本例锁死两边旗标不漂移。"""
    assert fs_mod.CLI_FLAG == launcher_mod.CLI_FLAG == '--cli'
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    fake_exe = r'C:\dist\MaterialSorting\MaterialSorting.exe'
    monkeypatch.setattr(sys, 'executable', fake_exe)
    assert fs_mod.cli_spawn_prefix() == [fake_exe, launcher_mod.CLI_FLAG]
