# -*- coding: utf-8 -*-
"""spyrrow 双源切换助手（US-004，prd-warm-start-phase1）。

本机在「PyPI spyrrow 0.9.0 ↔ spyrrow-ms 私有 wheel（0.9.0+msN）」之间一条
命令切换 + 现场诊断（当前安装源 / 版本 / warm 能力探测 / rev 钉板一致性）。
日常开发生产零影响：切换只动本仓 ``.venv`` 的 spyrrow 一个发行版，ms1 交付
前的默认态（0.9.0+ms0）行为与 PyPI 0.9.0 逐字节全等（0a 对拍已归档，
``.docs/technical/0a行为全等对拍_spyrrow私有wheel_2026-09.md``）。

用法（repo 根直跑，``.venv`` 解释器）::

    python scripts/spyrrow_wheel.py status              # 现场诊断（缺省命令）
    python scripts/spyrrow_wheel.py use-pypi            # 回 PyPI 线上版
    python scripts/spyrrow_wheel.py use-local <wheel>   # 装私有 wheel

设计口径：

- **pip 永远走 ``sys.executable -m pip``**（不假设 PATH 里有 pip；脚本被哪个
  解释器跑，就切哪个环境 —— ``status`` 首行打印解释器路径自证）。
- **rev 钉板**：``materialSorting-server/spyrrow_build.json`` 四字段
  ``{spyrrow_ms_commit, sparrow_rev, wheel_version, built_at}`` 的单一
  真相源在 **spyrrow-ms 侧**（每次出 wheel 交付 MS 时同步写入，规格 §4）；
  MS 侧 ``use-local`` 装入版本与钉板不一致时**提示更新**而非自动改写 ——
  ``spyrrow_ms_commit``/``sparrow_rev``/``built_at`` 三字段 MS 侧无从得知，
  半自动拼装会造出无法审计的假钉板。
- **use-local 加 ``--no-deps``**：只换 spyrrow 一个发行版，不连带重装
  shapely 等依赖（依赖版本由本仓 ``.venv`` 锁定，``--force-reinstall`` 全量
  重装依赖既慢又可能漂移版本）；use-pypi 按需从索引解析依赖（PRD 原文口径）。
- 装后读回验证走 ``importlib.invalidate_caches()`` + ``importlib.metadata``
  （同进程内 pip 改了 site-packages，元数据查找有缓存必须先失效）。

构建工具链 / 源码获取 / 构建命令本体在 spyrrow-ms 侧文档
（``D:/code/spyrrow-ms/.docs/technical/toolchain-setup_2026-09.md`` /
``0a-exit-gate_2026-09.md``），MS 侧消费与切换见
``.docs/technical/spyrrow私有wheel构建与升级手册.md``。本仓**不入库任何
Rust 构建产物**（wheel 只安装不落 repo）。

仅标准库（argparse/importlib.metadata/json/re/subprocess/sys/pathlib），
无新依赖；``status`` 对「包未安装」等异常态照常工作（诊断不炸）。
"""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import re
import subprocess
import sys
from pathlib import Path

# sys.path 自引导（对齐 scripts/ 既有惯例，见 embed_piece_codes.py /
# smoke_plt_clean.py）：repo 根直跑也能 import 本仓包（warm 能力探测）。
REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVER_SRC = REPO_ROOT / 'materialSorting-server' / 'src'
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

# rev 钉板（四字段单一真相源在 spyrrow-ms 侧，本脚本只读 + 漂移提示）。
PIN_PATH = REPO_ROOT / 'materialSorting-server' / 'spyrrow_build.json'

# 回线上目标版本（跨项目契约：私有 fork 的上游锚 = PyPI 0.9.0 = sparrow
# rev 881cdcbd 全等算法，规格 §2.2；升 0.2.0 是独立后续项，届时改这里）。
PYPI_VERSION = '0.9.0'

# 私有 wheel local tag（PEP 440 ``+ms<N>``；与 nesting_engine/warmstart.py
# 同款正则 —— warm 能力判定 N≥1，此处 N≥0 即「私有源」）。
_LOCAL_TAG_RE = re.compile(r'\+ms(\d+)')


def _reconfigure_stdio() -> None:
    """Windows 控制台默认 GBK，中文消息统一按 UTF-8 输出（best-effort）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:                      # noqa: BLE001 诊断输出不炸
            pass


def _installed_version() -> str | None:
    """当前解释器环境里已装 spyrrow 版本（未安装 → None，不抛）。"""
    try:
        return importlib.metadata.version('spyrrow')
    except Exception:                          # noqa: BLE001 status 诊断不炸
        return None


def _classify(version: str | None) -> tuple[str, str | None]:
    """版本串 → (源描述, local tag N)。``0.9.0+ms0`` → 私有 wheel / 0。"""
    if version is None:
        return ('未安装', None)
    m = _LOCAL_TAG_RE.search(version)
    if m:
        return (f'私有 wheel（local tag +ms{m.group(1)}）', m.group(1))
    return ('PyPI 线上版（无 local tag）', None)


def _load_pin() -> dict | None:
    """读 rev 钉板（缺失/损坏 → None，调用方降级提示）。"""
    try:
        with open(PIN_PATH, encoding='utf-8') as f:
            pin = json.load(f)
    except (OSError, ValueError):
        return None
    return pin if isinstance(pin, dict) else None


def _warm_probe() -> bool | None:
    """warm_start_supported() 探测（异常 → None，不炸 status）。"""
    try:
        from materialsorting.nesting_engine.warmstart import warm_start_supported
        return warm_start_supported()
    except Exception:                          # noqa: BLE001 诊断不炸
        return None


def _print_header(title: str) -> None:
    print(f'== {title} ==')
    print(f'  解释器：{sys.executable}（pip = sys.executable -m pip）')


def _print_pin_drift(version: str | None, *, prompt_marker: str | None) -> None:
    """打印钉板与一致性判读；prompt_marker 在「需提示更新」时输出该标记行。"""
    pin = _load_pin()
    if pin is None:
        print(f'  钉板：{PIN_PATH.name} 读取失败/缺失（跨项目审计点，'
              '请按 spyrrow-ms 侧台账恢复）')
        return
    print('  钉板 spyrrow_build.json：')
    for key in ('spyrrow_ms_commit', 'sparrow_rev', 'wheel_version', 'built_at'):
        print(f'    {key}: {pin.get(key)!r}')
    pinned = pin.get('wheel_version')
    if version is None:
        print('  一致性：spyrrow 未安装，与钉板无从对齐')
        return
    if version == pinned:
        print('  一致性：已装版本 == 钉板 wheel_version，一致')
        return
    _src, tag = _classify(version)
    if tag is not None:
        print(f'  一致性：已装私有 wheel {version} ≠ 钉板 {pinned} —— 钉板落后，'
              '需按 spyrrow-ms 侧交付台账更新四字段')
        if prompt_marker:
            print(prompt_marker)
    else:
        print(f'  一致性：当前为 {_src}（临时回线上态），钉板 {pinned} 记录'
              '私有 wheel 交付谱系，属正常组合')


def cmd_status() -> int:
    """现场诊断：安装源 / 版本 / warm 能力 / 钉板一致性。恒 exit 0。"""
    _reconfigure_stdio()
    _print_header('spyrrow 双源状态')
    version = _installed_version()
    source, _tag = _classify(version)
    print(f'  已装版本：{version if version is not None else "(未安装)"}')
    print(f'  安装源：{source}')
    warm = _warm_probe()
    warm_desc = {True: '支持（+ms<N≥1> 私有 wheel）',
                 False: '不支持（se warm 将回退 unsupported，属预期）'}.get(warm)
    print(f'  warm_start_supported()：'
          f'{warm if warm is not None else "(探测异常)"}'
          + (f' —— {warm_desc}' if warm_desc else ''))
    _print_pin_drift(version, prompt_marker=None)
    return 0


def _run_pip(*pip_args: str) -> int:
    """sys.executable -m pip 子进程（输出直通终端），返回 pip 退出码。"""
    cmd = [sys.executable, '-m', 'pip', *pip_args]
    print(f'  $ {" ".join(cmd)}')
    return subprocess.run(cmd, check=False).returncode


def _post_install_report() -> str | None:
    """装后读回：invalidate 缓存 → 实装版本（未装/异常 → None）。"""
    importlib.invalidate_caches()
    return _installed_version()


def _pin_update_prompt(new_version: str) -> None:
    print('')
    print('  [提示更新钉板] 本次装入版本与 spyrrow_build.json 不一致。四字段'
          '单一真相源在 spyrrow-ms 侧交付台账（.docs/technical/'
          '0a-exit-gate_2026-09.md），请按其同步（MS 侧不自动拼装 —— '
          'commit/rev/built_at 无从得知，半自动写入会造假钉板）：')
    print('    materialSorting-server/spyrrow_build.json')
    print('    {')
    print('      "spyrrow_ms_commit": "<spyrrow-ms 仓 commit>",')
    print('      "sparrow_rev": "<sparrow-ms 仓 rev>",')
    print(f'      "wheel_version": "{new_version}",')
    print('      "built_at": "<ISO8601 构建时间>"')
    print('    }')


def cmd_use_pypi() -> int:
    """``pip install --force-reinstall spyrrow==0.9.0`` 回线上版。"""
    _reconfigure_stdio()
    _print_header(f'切换到 PyPI 线上版 spyrrow=={PYPI_VERSION}')
    rc = _run_pip('install', '--force-reinstall', f'spyrrow=={PYPI_VERSION}')
    if rc != 0:
        print(f'  pip 失败（exit {rc}），环境未确认变更，可重试或查镜像源配置',
              file=sys.stderr)
        return rc
    version = _post_install_report()
    print(f'  读回版本：{version if version is not None else "(未安装？)"}')
    if version != PYPI_VERSION:
        print(f'  [警告] 读回版本 != {PYPI_VERSION}，请人工复核')
    warm = _warm_probe()
    if warm:
        print('  [警告] warm 仍报支持 —— 与线上版预期不符，请复核')
    else:
        print(f'  warm_start_supported() = {warm}：se 延长轮 warm 将回退'
              ' unsupported（不炸轮，属预期）')
    print('  钉板不动（spyrrow_build.json 记录私有 wheel 交付谱系；回线上'
          '是临时态，status 可随时判读）')
    return 0


def _parse_wheel_version(filename: str) -> str | None:
    """wheel 文件名 → 版本串。

    wheel 命名规范 ``{distribution}-{version}(-{build})?-{python}-{abi}
    -{platform}.whl``：取第二段（例 ``spyrrow-0.9.0+ms1-cp311-...whl`` →
    ``0.9.0+ms1``）；形态不合 → None（调用方只作读回对照，不因此拒装）。
    """
    if not filename.endswith('.whl'):
        return None
    parts = filename[:-len('.whl')].split('-')
    if len(parts) < 5 or parts[0] != 'spyrrow':
        return None
    return parts[1]


def cmd_use_local(wheel: str) -> int:
    """``pip install --force-reinstall --no-deps <wheel>`` 装私有 wheel。"""
    _reconfigure_stdio()
    _print_header('切换到 spyrrow-ms 私有 wheel')
    path = Path(wheel).expanduser()
    if not path.is_absolute():
        # 相对路径按 CWD 解析后取绝对，pip 子进程视角与诊断输出统一。
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        print(f'  [错误] wheel 路径不存在：{path}', file=sys.stderr)
        print('  用法：python scripts/spyrrow_wheel.py use-local '
              '<wheel 绝对或相对路径>（例 D:/code/spyrrow-ms/target/wheels/'
              'spyrrow-0.9.0+ms1-cp311-cp311-win_amd64.whl）', file=sys.stderr)
        return 1
    if not path.is_file() or not path.name.endswith('.whl'):
        print(f'  [错误] 不是 wheel 文件（须 .whl）：{path}', file=sys.stderr)
        return 1
    if not path.name.startswith('spyrrow-'):
        print(f'  [错误] 不是 spyrrow 发行版的 wheel（文件名须 spyrrow- 开头）：'
              f'{path.name} —— --force-reinstall 装错发行版会破坏 .venv',
              file=sys.stderr)
        return 1
    wheel_version = _parse_wheel_version(path.name)
    print(f'  目标 wheel：{path.name}'
          + (f'（文件名版本 {wheel_version}）' if wheel_version
             else '（文件名形态非标准，跳过版本预读）'))

    rc = _run_pip('install', '--force-reinstall', '--no-deps', str(path))
    if rc != 0:
        print(f'  pip 失败（exit {rc}），环境未确认变更，可重试',
              file=sys.stderr)
        return rc
    version = _post_install_report()
    print(f'  读回版本：{version if version is not None else "(未安装？)"}')
    if wheel_version is not None and version != wheel_version:
        print(f'  [警告] 实装版本 {version} ≠ 文件名版本 {wheel_version}，'
              '请人工复核')
    warm = _warm_probe()
    print(f'  warm_start_supported() = {warm}'
          + ('：se 延长轮 warm 真顺延已可用' if warm
             else '：当前 wheel 无 initial_solution（+ms0 纯重建态属预期）'))
    pin = _load_pin()
    pinned = pin.get('wheel_version') if pin else None
    if version is not None and version != pinned:
        _pin_update_prompt(version)
    else:
        print('  钉板 spyrrow_build.json 与已装版本一致，无需更新')
    return 0


def main(argv=None) -> int:
    """CLI 入口（无子命令缺省 ``status`` —— 探测是最高频动作且恒安全）。"""
    # 必须先于 parse_args：--help 的中文/特殊字符也要能落 GBK 控制台。
    _reconfigure_stdio()
    parser = argparse.ArgumentParser(
        prog='spyrrow_wheel.py',
        description='spyrrow 双源切换助手（PyPI 0.9.0 与 spyrrow-ms 私有 wheel '
                    '之间一条命令切换），详见 '
                    '.docs/technical/spyrrow私有wheel构建与升级手册.md')
    sub = parser.add_subparsers(dest='command')

    p_status = sub.add_parser(
        'status', help='现场诊断：安装源/版本/warm 能力/钉板一致性')
    p_status.set_defaults(func=cmd_status)

    p_pypi = sub.add_parser(
        'use-pypi', help=f'回 PyPI 线上版 spyrrow=={PYPI_VERSION}')
    p_pypi.set_defaults(func=cmd_use_pypi)

    p_local = sub.add_parser(
        'use-local',
        help='装 spyrrow-ms 私有 wheel（路径不存在/非 wheel 清晰报错）')
    p_local.add_argument('wheel', help='wheel 文件路径（绝对或相对 CWD）')
    p_local.set_defaults(func=lambda: cmd_use_local(args.wheel))

    args = parser.parse_args(argv)
    if getattr(args, 'func', None) is None:
        return cmd_status()
    return args.func()


if __name__ == '__main__':
    raise SystemExit(main())
