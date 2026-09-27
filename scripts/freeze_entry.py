"""Nuitka 冻结入口适配器（US-003，prd-local-deploy-freeze）。

Nuitka 编译的入口是一个**脚本**（模块名 ``__main__``、无父包上下文），而
``materialsorting/launcher.py`` 全部用相对 import（``from . import paths``、
``from .web import server`` 等 —— 其 ``python -m materialsorting.launcher``
形态由 ``-m`` 提供包上下文）。直接把 launcher.py 当 Nuitka 入口会在首个
相对 import 处 ``ImportError``，且 launcher 属既有 src 文件零改动红线 ——
本文件是绝对 import 适配层：冻结产物 ``MaterialSorting.exe`` 的 argv
语义（无参桌面启动 / ``--cli`` 子进程分发 / ``--check`` 自检）与 ms-desktop
完全一致。

frozen 判据桥接（关键）：launcher 的 env 重定向与 web._frozen_spawn 的
``exe --cli`` 前缀都以 ``getattr(sys, 'frozen', False)`` 为判据（PyInstaller
惯例，PRD US-001/002 原文口径），而 **Nuitka 不设 ``sys.frozen``**（官方
探测口径 = 模块级 ``__compiled__`` 属性，其标准包配置 YAML 自己都在把
``getattr(sys, "frozen", False)`` 补丁成 ``or "__compiled__" in globals()``）。
不桥接 = 冻结产物永远走 dev 分支（OUT_DIR 不落 LOCALAPPDATA / spawn 仍拼
``python -m`` 必败）。本适配层在 import launcher **之前**设
``sys.frozen = True``（仅真编译态；dev 直跑本文件不设、行为零变化），
launcher / _frozen_spawn / --check 全部就地受益，src 两文件零改动。

sys.path 自引导对齐 scripts/ 既有惯例（spyrrow_wheel.py 同款）：dev 态直接
``python scripts/freeze_entry.py`` 也可跑；Nuitka 分析态则经 venv 的可编辑
安装解析到同一 src。
"""
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / 'materialSorting-server' / 'src'))

if '__compiled__' in globals():   # Nuitka 真编译态标记（dev 直跑 absent）
    sys.frozen = True             # 桥接 PyInstaller 惯例判据，见模块 docstring

from materialsorting.launcher import main   # noqa: E402（sys.path/桥接后置）

if __name__ == '__main__':
    raise SystemExit(main())
