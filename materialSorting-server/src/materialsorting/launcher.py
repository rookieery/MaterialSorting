"""桌面 launcher 入口（prd-local-deploy-freeze US-001：客户本地部署冻结形态）。

双击即起的统一入口（``ms-desktop`` / 冻结后 ``MaterialSorting.exe``），一条
``main()`` 承三个角色：

  1. 桌面启动（无参数默认）：frozen 态环境重定向 → 单实例判据 → 空闲端口探测
     → 实际端口写 env + ``<OUT_DIR>/web_port.txt`` → 主线程 uvicorn（直接复用
     ``web.server.main()`` 启动语义，端口经 ``MS_WEB_PORT`` 传递，不复制粘贴端口
     逻辑）→ watcher 线程健康就绪后 ``webbrowser.open``（浏览器不早于服务就绪
     打开，避免首开白页）；
  2. ``--cli <args...>``：冻结形态 CLI 子进程分发 —— US-002 起 web 层 spawn
     前缀在 frozen 态变为 ``[exe, CLI_FLAG]``，本入口把余下 argv 原样交给
     ``materialsorting.cli.run_config.main``（延迟 import，退出码透传）；dev
     态 ``python -m materialsorting.launcher --cli`` 与直接跑 ms-run-config 等价；
  3. ``--check``：自检（frozen 态 / 版本串 / env / paths 落点 / 探测端口 /
     warm 支持性 / key 授权配置 / 机器直连 Origin 白名单），exit 0 无副作用
     —— 冻结验收脚本（US-004）与售后识别用户版本消费。

import 顺序红线（AST 守卫见 tests/test_launcher.py，全链最易踩的静默错误）：
  - **模块级仅 import 标准库**。``paths.py`` 在 import 期读 ``os.environ`` 固化
    全部路径常量、``web/server.py`` import 期 mount static + 读 intermediate ——
    launcher 必须「先设 env → 再延迟 import 业务」；模块级混入任何业务 import
    会在 env 设置前固化错误路径，且**不报错只写错目录**。
  - 未冻结（dev）零重定向：``python -m materialsorting.launcher`` 行为 = 原
    ``ms-web``（8010 基准端口、repo 路径）—— 环境重定向全部 gated 在
    ``getattr(sys, 'frozen', False)``，dev 工作流零变化。

frozen 态数据目录口径（PRD 定案④ / FR-4，全部 setdefault 不覆盖显式 env）：
安装目录只读安全，用户数据（上传母版 / config_runs / run_stats.jsonl）重定向
``%LOCALAPPDATA%\\MaterialSorting\\out`` —— 覆盖安装 / zip 解压升级均不触碰。
"""
from __future__ import annotations

import multiprocessing
import os
import socket
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

# US-002 契约锚点：web/_frozen_spawn.py frozen 态前缀 [exe, CLI_FLAG] 的分发
# 对端（两边同源常量或互引测试锁死，防一边改另一边漂移 —— 见其 AC3）。
CLI_FLAG = '--cli'
CHECK_FLAG = '--check'

BASE_PORT = 8010                  # 与 web/server.py 缺省同源（2026-09-21 8000→8010）
PORT_PROBE_MAX_OFFSET = 9         # FR-3：8010 起逐 +1，候选共 10 个
APP_DIR_NAME = 'MaterialSorting'  # %LOCALAPPDATA% 下应用数据根（用户数据保留口径）
_HEALTH_TIMEOUT_S = 2.0           # AC5 单实例健康探测超时
_READY_POLL_INTERVAL_S = 0.2      # watcher 就绪轮询间隔
_READY_MAX_WAIT_S = 60.0          # watcher 放弃上限（服务启动失败时进程随主线程退出）


# ------------------------------------------------------------- frozen 环境重定向

def apply_frozen_env() -> None:
    """frozen 态环境重定向（AC3）：仅 ``sys.frozen`` 为真时动作，全部 setdefault
    不覆盖显式 env；未冻结（dev）零动作零重定向。

    - ``MS_STATIC_DIR = <exe 所在目录>/static``（安装目录内前端构建产物，
      build_freeze ``--include-data-dir`` 捆绑）；
    - ``MS_DATA_DIR = <exe 所在目录>/data``（安装目录内样例母版目录，
      build_freeze 逐文件捆绑顶层 ``.dxf`` —— ``/api/samples`` 列表与 key 闸门
      样例豁免 sha256 对拍共用此目录；2026-09-29 无样例 bug 修复：此前缺省
      paths 上溯推导在客户机指向不存在路径，「样例」下拉恒空）；
    - ``MS_OUT_DIR = %LOCALAPPDATA%/MaterialSorting/out``（仅对**我们设置**的
      缺省值 mkdir parents —— 显式 env 覆盖时不碰他方目录）；
    - ``MS_FONT_DIR`` 走缺省包内路径（Nuitka 数据捆绑保持包结构，不重定向）。
    """
    if not getattr(sys, 'frozen', False):
        return
    exe_dir = Path(sys.executable).resolve().parent
    os.environ.setdefault('MS_STATIC_DIR', str(exe_dir / 'static'))
    os.environ.setdefault('MS_DATA_DIR', str(exe_dir / 'data'))
    if 'MS_OUT_DIR' not in os.environ:
        local_root = os.environ.get('LOCALAPPDATA') or str(
            Path.home() / 'AppData' / 'Local')
        out_dir = Path(local_root) / APP_DIR_NAME / 'out'
        out_dir.mkdir(parents=True, exist_ok=True)
        os.environ['MS_OUT_DIR'] = str(out_dir)


# ------------------------------------------------------------- 端口探测（AC4）

def _port_free(port: int) -> bool:
    """端口空闲探测：能绑定 127.0.0.1 即空闲（服务恒绑回环，FR-3）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def resolve_port() -> int:
    """端口解析：``MS_WEB_PORT`` 显式给出直接用；否则自 ``BASE_PORT`` 起逐 +1
    探测空闲（上限 ``PORT_PROBE_MAX_OFFSET``），全部被占则报错退出。"""
    explicit = os.environ.get('MS_WEB_PORT')
    if explicit:
        try:
            return int(explicit)
        except ValueError:
            raise SystemExit(f'MS_WEB_PORT 非法：{explicit!r}（须为整数端口号）')
    for offset in range(PORT_PROBE_MAX_OFFSET + 1):
        port = BASE_PORT + offset
        if _port_free(port):
            return port
    raise SystemExit(
        f'端口 {BASE_PORT}..{BASE_PORT + PORT_PROBE_MAX_OFFSET} 全部被占，'
        f'请关闭占用程序或用 MS_WEB_PORT 显式指定端口。')


# ------------------------------------------------------- 单实例判据（AC5）

def _http_ok(port: int, timeout: float = _HEALTH_TIMEOUT_S) -> bool:
    """健康探测：GET ``http://127.0.0.1:<port>/``（服务就绪判据）；任何异常
    （连接拒绝 / 超时 / 非 2xx）都视为未就绪，恒不抛。"""
    try:
        with urllib.request.urlopen(
                f'http://127.0.0.1:{port}/', timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _web_port_file() -> Path:
    """``<OUT_DIR>/web_port.txt`` 路径。paths 函数内延迟 import —— 顺序红线：
    调用方须已跑 ``apply_frozen_env()``，paths 才能落到重定向后的 OUT_DIR。"""
    from . import paths   # 延迟 import（env 先于 paths 固化）
    return Path(paths.OUT_DIR) / 'web_port.txt'


def _read_web_port_file() -> int | None:
    """读既有 web_port.txt 端口（无文件 / 脏内容 → None，恒不抛）。"""
    try:
        return int(_web_port_file().read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        return None


def _existing_instance_port() -> int | None:
    """单实例判据：web_port.txt 在场且其端口 GET / 健康命中 → 返回该端口
    （调用方只开浏览器不重复起服务）；无文件 / 脏内容 / 不健康 → None 正常启动。

    竞态边界（PRD 技术考虑定案）：多用户快速切换可能双起，健康探测兜底指向
    先起者，接受；命名互斥体为 v2 加固项不进 v1。
    """
    prev = _read_web_port_file()
    if prev is None:
        return None
    return prev if _http_ok(prev) else None


# ------------------------------------------------------- 桌面启动编排（AC4~6）

def start_desktop() -> int:
    """桌面启动编排：env 重定向 → 单实例判据 → 端口探测 → 写 env/port 文件 →
    watcher 线程 + 主线程 uvicorn（``web.server.main()``，端口经 MS_WEB_PORT）。"""
    apply_frozen_env()

    # 单实例（AC5）：既有健康实例在场 → 只开浏览器指向该端口，exit 0。
    prev = _existing_instance_port()
    if prev is not None:
        url = f'http://127.0.0.1:{prev}'
        print(f'检测到已在运行的实例（{url}），直接打开浏览器，不再重复启动服务。')
        webbrowser.open(url)
        return 0

    # 端口探测（AC4）：实际端口写 env 后再启动 server（server.py 读同一变量），
    # 并写 <OUT_DIR>/web_port.txt（二次启动单实例判据；服务起失败时为陈旧文件，
    # 下次启动健康探测不命中自动按无实例处理，自愈）。
    port = resolve_port()
    os.environ['MS_WEB_PORT'] = str(port)
    port_file = _web_port_file()
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(str(port), encoding='utf-8')
    url = f'http://127.0.0.1:{port}'
    print(f'排料工作台启动中 → {url}（关闭本窗口即停止服务）')

    import threading   # 标准库，函数内 import 保持模块级最小面

    from .web import server as server_mod   # 延迟 import：env 已就位才固化 paths

    def _watch_and_open() -> None:
        """就绪 watcher：健康探测命中后才开浏览器（不早于服务就绪，防首开白页）。"""
        deadline = time.monotonic() + _READY_MAX_WAIT_S
        while time.monotonic() < deadline:
            if _http_ok(port, timeout=1.0):
                webbrowser.open(url)
                return
            time.sleep(_READY_POLL_INTERVAL_S)
        print(f'警告：服务 {url} {_READY_MAX_WAIT_S:.0f}s 内未就绪，未自动打开'
              f'浏览器（可手动访问）。', file=sys.stderr)

    threading.Thread(target=_watch_and_open, name='browser-watcher',
                     daemon=True).start()
    server_mod.main()   # 主线程 uvicorn（复用 ms-web 启动语义；Ctrl-C/关窗即停）
    return 0


# ------------------------------------------------------------- 子命令（AC2/7）

def _dispatch_cli(rest: list[str]) -> int:
    """``--cli <args...>`` → ``materialsorting.cli.run_config.main(rest)``。

    延迟 import（AC2）+ 退出码透传。走 ``from .cli.run_config import main``
    子模块形态（进程边界另一侧 = US-002 spawn 前缀 ``[exe, CLI_FLAG]``）。
    """
    from .cli.run_config import main as cli_main
    return int(cli_main(rest))


def run_check() -> int:
    """``--check`` 自检（AC7）：打印 frozen 态 / 版本串（``importlib.metadata``，
    US-003 冻结打包捆绑本包元数据使其在 frozen 态同样可读）/ 解析后 env /
    paths 各常量落点 / 探测端口 / ``warm_start_supported()`` 结果；exit 0，
    无副作用（不起服务不开浏览器；仅 apply_frozen_env 的缺省 OUT_DIR mkdir）。

    key 授权配置回显（key 授权 PRD US-009）：``env MS_KEY_MODE`` / ``key_server_url``
    （三档解析链结果 + 来源，经 ``keygate.describe_key_server_url``）/
    ``key_client_token``（配置态 + 来源，**不回显值**，``describe_client_token``）/
    ``machine_guid``（注册表只读探测，不铸兜底文件）/ ``key_state``（落点 +
    绑定态）—— 售后定位现场 key 配置问题一条命令自诊。

    机器直连 Origin 白名单回显（浏览器直连 PRD US-004）：
    ``machine_allowed_origins`` = 三档来源（env / sidecar 位置）+ 条数，经
    ``machine_cors.describe_machine_allowed_origins``（describe 仅供诊断，
    业务路径不消费；Origin 值非秘密可回显）—— 随包交付的
    ``machine_allowed_origins.txt``（US-004 交付链）命中即「exe 旁」档。
    """
    apply_frozen_env()
    import importlib.metadata

    frozen = bool(getattr(sys, 'frozen', False))
    try:
        version = importlib.metadata.version('materialsorting')
    except Exception:
        version = '(未知：未安装或元数据缺失)'

    from . import paths
    from .nesting_engine.warmstart import warm_start_supported
    from .web import keygate   # 延迟 import：模块级仅标准库红线（keygate 带 ..paths）
    from .web import machine_cors   # 同红线（浏览器直连白名单 describe，US-004）

    def _env(name: str) -> str:
        return os.environ.get(name) or '(未设，走缺省)'

    key_mode = os.environ.get('MS_KEY_MODE') or '(未设)'
    state = keygate.load_key_state()
    bound_key = state.get('key') if isinstance(state, dict) else None
    bound = (f'已绑定 {bound_key}' if isinstance(bound_key, str) and bound_key.strip()
             else '未绑定')
    print(f'frozen: {frozen}')
    print(f'version: {version}')
    print(f'python: {sys.version.split()[0]}')
    print(f'executable: {sys.executable}')
    print(f'env MS_WEB_PORT: {_env("MS_WEB_PORT")}')
    print(f'env MS_DATA_DIR: {_env("MS_DATA_DIR")}')
    print(f'env MS_OUT_DIR: {_env("MS_OUT_DIR")}')
    print(f'env MS_STATIC_DIR: {_env("MS_STATIC_DIR")}')
    print(f'env MS_FONT_DIR: {_env("MS_FONT_DIR")}')
    print(f'env MS_KEY_MODE: {key_mode}（off 仅 dev 生效，frozen 恒不可绕）')
    print(f'key_server_url: {keygate.describe_key_server_url()}')
    print(f'key_client_token: {keygate.describe_client_token()}')
    print(f'machine_guid: {keygate.describe_machine_guid()}')
    print(f'key_state: {keygate.key_state_path()}（{bound}）')
    print(f'machine_allowed_origins: '
          f'{machine_cors.describe_machine_allowed_origins()}')
    print(f'paths.DATA_DIR: {paths.DATA_DIR}')
    print(f'paths.OUT_DIR: {paths.OUT_DIR}')
    print(f'paths.INTERMEDIATE: {paths.INTERMEDIATE}')
    print(f'paths.CONFIG_RUNS_DIR: {paths.CONFIG_RUNS_DIR}')
    print(f'paths.STATIC_DIR: {paths.STATIC_DIR}')
    print(f'paths.FONT_DIR: {paths.FONT_DIR}')
    print(f'port: {resolve_port()}')
    print(f'warm_start_supported: {warm_start_supported()}')
    return 0


def _print_help() -> None:
    print(
        'MaterialSorting 排料工作台 · 桌面入口'
        '（ms-desktop / python -m materialsorting.launcher）\n'
        '\n'
        '用法：\n'
        '  ms-desktop                   桌面启动：单实例判据 → 空闲端口探测'
        f'（{BASE_PORT} 起，\n'
        '                               至多 +9）→ 启动服务 → 就绪后自动打开'
        '默认浏览器\n'
        f'  ms-desktop {CLI_FLAG} <args...>   CLI 子命令分发：余下参数原样交给'
        ' ms-run-config\n'
        '                               （冻结形态 spawn 子进程入口，US-002 契约）\n'
        f'  ms-desktop {CHECK_FLAG}           自检：frozen 态/版本/env/paths 落点/'
        '探测端口/\n'
        '                               warm 支持性/key 授权配置（URL 链/机 ID/'
        '绑定态）/机器\n'
        '                               直连 Origin 白名单（来源+条数）；'
        '无副作用，不起服务不开浏览器\n'
        '  ms-desktop -h | --help       本帮助\n'
        '\n'
        '环境变量（均可显式覆盖；frozen 态才设缺省重定向，dev 零重定向）：\n'
        '  MS_WEB_PORT     服务端口（缺省自 8010 探测空闲）\n'
        '  MS_OUT_DIR      产物目录（frozen 缺省 '
        f'%LOCALAPPDATA%\\{APP_DIR_NAME}\\out）\n'
        '  MS_STATIC_DIR   前端静态目录（frozen 缺省 <exe 所在目录>\\static）\n'
        '  MS_DATA_DIR     样例母版目录（frozen 缺省 <exe 所在目录>\\data，'
        'build_freeze 捆绑\n'
        '                  顶层 .dxf；/api/samples 列表 + key 闸门样例豁免\n'
        '                  sha256 对拍共用）\n'
        '  MS_KEY_SERVER_URL  key 授权服务器基址（frozen 亦可 sidecar '
        'key_server_url.txt：\n'
        '                     exe 旁优先，缺则回落 license/ 目录，2026-09-29）\n'
        '  MS_KEY_CLIENT_TOKEN  keyserver 消费端共享 token（frozen 亦可 sidecar '
        'key_client_token.txt，\n'
        '                     位置同上两档；未配置且 keyserver 已设 → 消费请求 401）\n'
        '  MS_MACHINE_ALLOWED_ORIGINS  机器对接（/api/machine/*）浏览器跨源直连\n'
        '                     Origin 白名单，逗号/分号分隔多值（亦可 sidecar\n'
        '                     machine_allowed_origins.txt 每行一个：frozen exe 旁\n'
        '                     优先、回落 license/ 目录；未配置 = 不发 CORS 头不校验\n'
        '                     Origin，零回归现状）\n'
        '  MS_KEY_MODE     off = 关闭 key 闸门（仅 dev 生效，frozen exe 恒不可绕）')


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()   # 必须首行（PyInstaller 必须 / Nuitka 无害）
    # 防乱码：Windows 管道/重定向默认 GBK，强制 UTF-8（--check 供构建/验收脚本
    # 消费，须确定性可读）；真实控制台走 WindowsConsoleIO 本就 UTF-8，无副作用。
    # 非常规流（pytest capture）无 reconfigure 能力，跳过不阻断（run_config 同款）。
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError, OSError):
        pass
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == CLI_FLAG:
        return _dispatch_cli(args[1:])
    if args and args[0] == CHECK_FLAG:
        return run_check()
    if args and args[0] in ('-h', '--help'):
        _print_help()
        return 0
    if args:
        print(f'未知参数：{" ".join(args)}', file=sys.stderr)
        _print_help()
        return 2
    return start_desktop()


if __name__ == '__main__':
    raise SystemExit(main())
