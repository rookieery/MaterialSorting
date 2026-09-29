"""US-001 launcher 桌面入口测试（prd-local-deploy-freeze）。

覆盖（spec AC8）：
  - AST 守卫：launcher.py 模块级 import 白名单 = 标准库（「env 先于 paths.py
    import 期固化」顺序红线 —— 模块级混入业务 import 会在 env 设置前固化错误
    路径，且不报错只写错目录）；
  - env 重定向四象限矩阵（frozen 真/假 × 显式 env 给/不给）：子进程隔离
    （sys.frozen 假标志 + 干净 MS_* env + 假 LOCALAPPDATA），断言 paths.*
    常量落点与 mkdir 副作用，不污染测试进程全局 paths；
  - 端口探测：MS_WEB_PORT 显式直用 / base 被占选 +1 / 全占用报错 / 非法值拒绝；
  - 健康探测：真 HTTP 服务起/停（http.server 临时实例）；
  - 单实例判据：web_port.txt 在场 × 健康命中/未命中 / 无文件不做探测 / 脏内容；
  - start_desktop 编排（stub 化，不起真 uvicorn）：既有实例只开浏览器不起服务
    exit 0 / 新实例写 env + web_port.txt + 起服务（经 env 传端口）+ 就绪后开浏览器；
  - --cli 分发：argv 透传 + 退出码透传（fake run_config 模块注入 + 子进程真跑
    --help / 配置错误退出码）；
  - --check / --help / 未知参数：输出含各键、exit 码语义。
"""
from __future__ import annotations

import ast
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from materialsorting import launcher as launcher_mod

_SRC = Path(__file__).resolve().parents[1] / 'src'
_LAUNCHER_SRC = _SRC / 'materialsorting' / 'launcher.py'
# dev 缺省落点（paths.py 同款上溯口径独立复算，防测试进程 paths 被其它用例污染）
_DEV_OUT_DIR = _SRC.parent / 'out'
_DEV_STATIC_DIR = _SRC.parents[1] / 'materialSorting-web' / 'static'
_DEV_DATA_DIR = _SRC.parents[1] / 'data'
# 模块级 import 白名单 = 标准库（AST 守卫；新增顶层 import 须同步维护此表）
_STDLIB_WHITELIST = frozenset({
    '__future__', 'multiprocessing', 'os', 'socket', 'sys', 'time',
    'urllib', 'urllib.request', 'webbrowser', 'pathlib',
})


# ------------------------------------------------------------- 基础设施

def _module_level_imports(tree: ast.Module) -> list[ast.AST]:
    """收集模块级 import 节点：穿透 if/try 等顶层块，跳过函数/类体 —— 函数内
    延迟 import 正是顺序红线要求的写法（不算模块级）。"""
    found: list[ast.AST] = []
    todo = list(tree.body)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            continue
        else:
            todo.extend(ast.iter_child_nodes(node))
    return found


def _free_port() -> int:
    """取一个临时空闲端口（bind 0 后立即释放；探测测试用它做锚定 base）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return int(s.getsockname()[1])


class _FakeBrowser:
    """webbrowser.open 替身：记录 URL 不真开浏览器。"""

    def __init__(self):
        self.urls: list[str] = []

    def open(self, url):
        self.urls.append(url)


# ------------------------------------------------------------- AST 守卫（AC1）

def test_ast_guard_module_level_stdlib_only():
    """顺序红线：模块级 import 白名单 = 标准库 —— web.server/paths 等业务
    import 只能函数内延迟，保障「先设 env → 再固化 paths」。"""
    tree = ast.parse(_LAUNCHER_SRC.read_text(encoding='utf-8'))
    names: set[str] = set()
    for node in _module_level_imports(tree):
        if isinstance(node, ast.ImportFrom):
            names.add((node.module or '').split('.')[0])
        else:
            for alias in node.names:
                names.add(alias.name.split('.')[0])
    assert names, '守卫防空转：launcher.py 应有模块级标准库 import'
    non_stdlib = names - _STDLIB_WHITELIST
    assert not non_stdlib, (
        f'launcher.py 模块级出现非白名单 import（顺序红线，业务 import 须函数内'
        f'延迟）: {sorted(non_stdlib)}')


def test_apply_frozen_env_dev_noop(monkeypatch):
    """dev 态零重定向：sys.frozen 未设 → apply_frozen_env 全程不动 env。"""
    for key in ('MS_OUT_DIR', 'MS_STATIC_DIR', 'MS_DATA_DIR'):
        monkeypatch.delenv(key, raising=False)
    launcher_mod.apply_frozen_env()
    assert 'MS_OUT_DIR' not in os.environ
    assert 'MS_STATIC_DIR' not in os.environ
    assert 'MS_DATA_DIR' not in os.environ


# ------------------------------------------------- env 重定向四象限（AC3/AC8）

# 子进程探针：设假 sys.frozen → apply_frozen_env → import paths 后回读落点。
# 子进程隔离保证 paths 常量按探针 env 独立固化，不污染测试进程全局。
_QUADRANT_CODE = """
import json, os, sys
sys.frozen = __FROZEN__
import materialsorting.launcher as launcher
launcher.apply_frozen_env()
from materialsorting import paths
print(json.dumps({
    "env_out": os.environ.get("MS_OUT_DIR"),
    "env_static": os.environ.get("MS_STATIC_DIR"),
    "env_data": os.environ.get("MS_DATA_DIR"),
    "paths_out": paths.OUT_DIR,
    "paths_static": paths.STATIC_DIR,
    "paths_data": paths.DATA_DIR,
    "paths_font": paths.FONT_DIR,
}))
"""


def _probe_paths(frozen: bool, tmp_path, explicit: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith('MS_')}
    env['LOCALAPPDATA'] = str(tmp_path / 'la')
    env['PYTHONPATH'] = str(_SRC)
    env.update(explicit or {})
    code = _QUADRANT_CODE.replace('__FROZEN__', repr(frozen))
    proc = subprocess.run(
        [sys.executable, '-c', code], capture_output=True, text=True,
        encoding='utf-8', env=env, cwd=str(_SRC.parent))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_env_matrix_frozen_default_redirect(tmp_path):
    """象限①frozen×无显式 env：OUT_DIR 落 %LOCALAPPDATA% 且 mkdir parents；
    STATIC_DIR 落 <exe 目录>\\static；DATA_DIR 落 <exe 目录>\\data（2026-09-29
    无样例 bug 修复：样例母版捆绑目录，/api/samples 与 key 豁免对拍共用）；
    字体走包内缺省不重定向。"""
    r = _probe_paths(True, tmp_path)
    exe_dir = Path(sys.executable).resolve().parent
    expected_out = str(tmp_path / 'la' / 'MaterialSorting' / 'out')
    assert r['env_out'] == expected_out
    assert r['paths_out'] == expected_out
    assert (tmp_path / 'la' / 'MaterialSorting' / 'out').is_dir()
    expected_static = str(exe_dir / 'static')
    assert r['env_static'] == expected_static
    assert r['paths_static'] == expected_static
    expected_data = str(exe_dir / 'data')
    assert r['env_data'] == expected_data
    assert r['paths_data'] == expected_data
    assert 'resources' in Path(r['paths_font']).as_posix()


def test_env_matrix_frozen_explicit_env_wins(tmp_path):
    """象限②frozen×显式 env：setdefault 语义 —— 显式值原样透传，且不为缺省
    值 mkdir LOCALAPPDATA 目录。"""
    out = str(tmp_path / 'custom_out')
    static = str(tmp_path / 'custom_static')
    data = str(tmp_path / 'custom_data')
    r = _probe_paths(True, tmp_path, {'MS_OUT_DIR': out, 'MS_STATIC_DIR': static,
                                      'MS_DATA_DIR': data})
    assert r['env_out'] == out and r['paths_out'] == out
    assert r['env_static'] == static and r['paths_static'] == static
    assert r['env_data'] == data and r['paths_data'] == data
    assert not (tmp_path / 'la' / 'MaterialSorting').exists()


def test_env_matrix_dev_no_redirect(tmp_path):
    """象限③dev×无显式 env：零重定向 —— env 无 MS_OUT_DIR/MS_STATIC_DIR/
    MS_DATA_DIR，paths 落点与原 ms-web 逐字节一致（repo 路径红线），
    LOCALAPPDATA 零副作用。"""
    r = _probe_paths(False, tmp_path)
    assert r['env_out'] is None and r['env_static'] is None
    assert r['env_data'] is None
    assert r['paths_out'] == str(_DEV_OUT_DIR)
    assert r['paths_static'] == str(_DEV_STATIC_DIR)
    assert r['paths_data'] == str(_DEV_DATA_DIR)
    assert not (tmp_path / 'la').exists()


def test_env_matrix_dev_explicit_env_respected(tmp_path):
    """象限④dev×显式 env：dev 态不清不覆盖 —— 显式 env 由 paths 自然生效。"""
    out = str(tmp_path / 'dev_out')
    r = _probe_paths(False, tmp_path, {'MS_OUT_DIR': out})
    assert r['env_out'] == out and r['paths_out'] == out


# ------------------------------------------------------------- 端口探测（AC4）

def test_resolve_port_explicit_env(monkeypatch):
    monkeypatch.setenv('MS_WEB_PORT', '8123')
    assert launcher_mod.resolve_port() == 8123


def test_resolve_port_invalid_env(monkeypatch):
    monkeypatch.setenv('MS_WEB_PORT', 'abc')
    with pytest.raises(SystemExit):
        launcher_mod.resolve_port()


def test_resolve_port_probe_next_when_base_busy(monkeypatch):
    """base 被占（socket 预占）→ 自 +1 探测选下一个（AC8 端口探测判据）。"""
    monkeypatch.delenv('MS_WEB_PORT', raising=False)
    base = _free_port()
    monkeypatch.setattr(launcher_mod, 'BASE_PORT', base)
    hold = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    hold.bind(('127.0.0.1', base))
    hold.listen(1)
    try:
        assert launcher_mod.resolve_port() == base + 1
    finally:
        hold.close()


def test_resolve_port_all_busy_exits(monkeypatch):
    """候选 10 个全被占 → 报错退出（非静默回退到被占端口）。"""
    monkeypatch.delenv('MS_WEB_PORT', raising=False)
    base = _free_port()
    monkeypatch.setattr(launcher_mod, 'BASE_PORT', base)
    holders = []
    try:
        for offset in range(launcher_mod.PORT_PROBE_MAX_OFFSET + 1):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('127.0.0.1', base + offset))
            s.listen(1)
            holders.append(s)
        with pytest.raises(SystemExit):
            launcher_mod.resolve_port()
    finally:
        for s in holders:
            s.close()


# ------------------------------------------------------- 健康探测 + 单实例（AC5）

def test_http_ok_real_server_roundtrip():
    """_http_ok 对真 HTTP 服务：起 → True；停 → False（连接拒绝不抛）。"""

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')

        def log_message(self, *args):   # 静默测试日志
            pass

    srv = http.server.HTTPServer(('127.0.0.1', 0), _Handler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        assert launcher_mod._http_ok(port) is True
    finally:
        srv.shutdown()
        srv.server_close()
        th.join(timeout=2)
    assert launcher_mod._http_ok(port) is False


def test_existing_instance_port_hit(monkeypatch):
    """单实例判据命中：web_port.txt 在场 + 健康探测 True → 返回既有端口。"""
    monkeypatch.setattr(launcher_mod, '_read_web_port_file', lambda: 9021)
    monkeypatch.setattr(launcher_mod, '_http_ok', lambda p, timeout=2.0: True)
    assert launcher_mod._existing_instance_port() == 9021


def test_existing_instance_port_unhealthy(monkeypatch):
    """端口文件在场但服务不健康（连不上/非 2xx）→ None 正常启动。"""
    monkeypatch.setattr(launcher_mod, '_read_web_port_file', lambda: 9021)
    monkeypatch.setattr(launcher_mod, '_http_ok', lambda p, timeout=2.0: False)
    assert launcher_mod._existing_instance_port() is None


def test_existing_instance_port_no_file_skips_probe(monkeypatch):
    """无 port 文件 → 不做健康探测直接 None（不起 2s 等待）。"""

    def _boom(*args, **kwargs):
        raise AssertionError('无 web_port.txt 不应触发健康探测')

    monkeypatch.setattr(launcher_mod, '_read_web_port_file', lambda: None)
    monkeypatch.setattr(launcher_mod, '_http_ok', _boom)
    assert launcher_mod._existing_instance_port() is None


def test_read_web_port_file_clean_dirty_missing(monkeypatch, tmp_path):
    """port 文件读取三态：合法端口 / 脏内容 → None / 缺文件 → None（恒不抛）。"""
    from materialsorting import paths as paths_mod
    monkeypatch.setattr(paths_mod, 'OUT_DIR', str(tmp_path))
    f = tmp_path / 'web_port.txt'
    f.write_text('8010', encoding='utf-8')
    assert launcher_mod._read_web_port_file() == 8010
    f.write_text('not-a-port', encoding='utf-8')
    assert launcher_mod._read_web_port_file() is None
    f.unlink()
    assert launcher_mod._read_web_port_file() is None


# ------------------------------------------------------- start_desktop 编排（AC4~6）

def _install_fake_server(monkeypatch) -> list:
    """把 materialsorting.web.server 替成 fake（双保险：sys.modules + 包属性
    —— ``from .web import server`` 两路查找都命中 fake，不真起 uvicorn）。
    返回调用记录列表（fake main 每次 append 当时 env 的 MS_WEB_PORT）。"""
    import materialsorting.web as web_pkg
    calls: list = []
    fake_srv = types.ModuleType('materialsorting.web.server')

    def _fake_main():
        calls.append(os.environ.get('MS_WEB_PORT'))

    fake_srv.main = _fake_main
    monkeypatch.setitem(sys.modules, 'materialsorting.web.server', fake_srv)
    monkeypatch.setattr(web_pkg, 'server', fake_srv, raising=False)
    return calls


def test_start_desktop_existing_instance_only_opens_browser(
        monkeypatch, capsys):
    """单实例编排：既有健康实例 → 只开浏览器指向该端口、exit 0、不起服务。"""
    browser = _FakeBrowser()
    monkeypatch.setattr(
        launcher_mod, 'webbrowser', types.SimpleNamespace(open=browser.open))
    monkeypatch.setattr(launcher_mod, '_existing_instance_port', lambda: 9030)
    server_calls = _install_fake_server(monkeypatch)
    assert launcher_mod.start_desktop() == 0
    assert browser.urls == ['http://127.0.0.1:9030']
    assert server_calls == []                       # 不重复起服务
    assert '已在运行' in capsys.readouterr().out


def test_start_desktop_new_instance_full_flow(monkeypatch, tmp_path):
    """新实例编排：探测 base+1 → 写 env + web_port.txt → server.main（经 env
    拿到同端口）→ watcher 就绪后开浏览器。"""
    from materialsorting import paths as paths_mod
    monkeypatch.setattr(paths_mod, 'OUT_DIR', str(tmp_path))
    monkeypatch.setattr(launcher_mod, '_existing_instance_port', lambda: None)
    monkeypatch.setattr(
        launcher_mod, '_http_ok', lambda p, timeout=2.0: True)   # 立即就绪
    browser = _FakeBrowser()
    monkeypatch.setattr(
        launcher_mod, 'webbrowser', types.SimpleNamespace(open=browser.open))
    base = _free_port()
    monkeypatch.setattr(launcher_mod, 'BASE_PORT', base)
    hold = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    hold.bind(('127.0.0.1', base))
    hold.listen(1)                                  # base 被占 → 探测选 base+1
    server_calls = _install_fake_server(monkeypatch)
    saved_port_env = os.environ.get('MS_WEB_PORT')
    try:
        monkeypatch.delenv('MS_WEB_PORT', raising=False)
        assert launcher_mod.start_desktop() == 0
        port = base + 1
        assert os.environ['MS_WEB_PORT'] == str(port)        # 实际端口写 env
        assert (tmp_path / 'web_port.txt').read_text(encoding='utf-8') == str(port)
        assert server_calls == [str(port)]                   # server 经 env 同端口
        time.sleep(0.6)                                      # watcher 线程开浏览器
        assert f'http://127.0.0.1:{port}' in browser.urls
        assert launcher_mod._read_web_port_file() == port    # 文件可回读（自洽）
    finally:
        hold.close()
        if saved_port_env is None:
            os.environ.pop('MS_WEB_PORT', None)              # 不泄漏 env 给后续用例
        else:
            os.environ['MS_WEB_PORT'] = saved_port_env


# ------------------------------------------------------------- --cli 分发（AC2）

def test_cli_dispatch_argv_and_exit_code_passthrough(monkeypatch):
    """--cli：余下 argv 原样透传 + 退出码透传（fake run_config 模块注入 ——
    sys.modules 与包属性双保险，防全量套件运行顺序下真模块已缓存的干扰）。"""
    import materialsorting.cli as cli_pkg
    seen: list = []
    fake = types.ModuleType('materialsorting.cli.run_config')

    def _fake_main(rest):
        seen.append(list(rest))
        return 7

    fake.main = _fake_main
    monkeypatch.setitem(sys.modules, 'materialsorting.cli.run_config', fake)
    monkeypatch.setattr(cli_pkg, 'run_config', fake, raising=False)
    assert launcher_mod.main(['--cli', 'x.json', '--time', '5']) == 7
    assert seen == [['x.json', '--time', '5']]


def test_cli_subprocess_help_smoke():
    """--cli --help 子进程真跑：透传到 ms-run-config 的 argparse，exit 0。"""
    proc = subprocess.run(
        [sys.executable, '-m', 'materialsorting.launcher', '--cli', '--help'],
        capture_output=True, text=True, encoding='utf-8', cwd=str(_SRC.parent))
    assert proc.returncode == 0
    assert 'usage' in proc.stdout


def test_cli_subprocess_exit_code_passthrough(tmp_path):
    """--cli 配置错误：退出码 = run_config._EXIT_CONFIG_OR_COMMIT（透传不吞）。"""
    from materialsorting.cli.run_config import _EXIT_CONFIG_OR_COMMIT
    proc = subprocess.run(
        [sys.executable, '-m', 'materialsorting.launcher', '--cli',
         str(tmp_path / 'nope.json')],
        capture_output=True, text=True, encoding='utf-8', cwd=str(_SRC.parent))
    assert proc.returncode == _EXIT_CONFIG_OR_COMMIT
    assert '配置错误' in proc.stderr


# ------------------------------------------- --check / --help / 未知参数（AC7/9）

def test_help_prints_subcommands(capsys):
    assert launcher_mod.main(['--help']) == 0
    assert launcher_mod.main(['-h']) == 0
    out = capsys.readouterr().out
    for frag in ('--cli', '--check', '--help', '8010', 'MS_WEB_PORT'):
        assert frag in out


def test_unknown_args_exit_2(capsys):
    assert launcher_mod.main(['--bogus']) == 2
    captured = capsys.readouterr()
    assert '未知参数' in captured.err and '--bogus' in captured.err
    assert '--cli' in captured.out                    # 错误时也打印用法指路


def test_check_subprocess_output_keys(tmp_path):
    """python -m materialsorting.launcher --check 冒烟：各键在场 + dev 态
    frozen: False（AC9 跑通判据；key 授权配置四行 = US-009）。

    2026-09-29 dev sidecar 档起 hermetic：子进程 ``MS_OUT_DIR`` 指 tmp（隔离
    真实 out/license/ 下的部署 sidecar 与本机已绑定 key_state.json —— 缺省态
    断言「未配置/未绑定」不再依赖开发机状态）。"""
    env = dict(os.environ)
    env['MS_OUT_DIR'] = str(tmp_path / 'out')
    proc = subprocess.run(
        [sys.executable, '-m', 'materialsorting.launcher', '--check'],
        capture_output=True, text=True, encoding='utf-8', cwd=str(_SRC.parent),
        env=env)
    assert proc.returncode == 0
    for key in ('frozen:', 'version:', 'env MS_WEB_PORT:', 'env MS_OUT_DIR:',
                'env MS_STATIC_DIR:', 'env MS_DATA_DIR:', 'env MS_KEY_MODE:',
                'key_server_url:', 'key_client_token:', 'machine_guid:',
                'key_state:', 'paths.OUT_DIR:', 'paths.STATIC_DIR:',
                'paths.DATA_DIR:', 'paths.FONT_DIR:', 'port:',
                'warm_start_supported:'):
        assert key in proc.stdout, key
    assert 'frozen: False' in proc.stdout
    assert str(tmp_path / 'out') in proc.stdout     # OUT_DIR 落点 = env 重定向值
    assert str(_DEV_STATIC_DIR) in proc.stdout
    assert str(_DEV_DATA_DIR) in proc.stdout
    # key 配置缺省态（tmp 空 license：无 env 无 sidecar）：未配置 + 未绑定
    assert '未配置' in proc.stdout
    assert '未绑定' in proc.stdout


def test_check_key_config_env_echo(monkeypatch):
    """--check 回显 key 配置（US-009）：MS_KEY_SERVER_URL env → URL + 来源标注；
    MS_KEY_MODE=off → 回显该值（回显本身不构成放行，判定序在 keygate）。"""
    env = dict(os.environ)
    env.pop('MS_KEY_SERVER_URL', None)
    env['MS_KEY_SERVER_URL'] = 'http://127.0.0.1:8110'
    env['MS_KEY_MODE'] = 'off'
    proc = subprocess.run(
        [sys.executable, '-m', 'materialsorting.launcher', '--check'],
        capture_output=True, text=True, encoding='utf-8', cwd=str(_SRC.parent),
        env=env)
    assert proc.returncode == 0
    assert 'key_server_url: http://127.0.0.1:8110' in proc.stdout
    assert 'MS_KEY_SERVER_URL env' in proc.stdout
    assert 'env MS_KEY_MODE: off' in proc.stdout
    # key_state 落点 = OUT_DIR/license（与 paths.LICENSE_DIR 同口径）
    assert 'license' in proc.stdout and 'key_state.json' in proc.stdout


def test_check_client_token_configured_no_leak(monkeypatch):
    """--check 回显 client token 配置态（US-009）：已配置报来源，**值不回显**
    （共享秘密不进日志/截图）。"""
    env = dict(os.environ)
    env['MS_KEY_CLIENT_TOKEN'] = 'secret-tok-xyz'
    proc = subprocess.run(
        [sys.executable, '-m', 'materialsorting.launcher', '--check'],
        capture_output=True, text=True, encoding='utf-8', cwd=str(_SRC.parent),
        env=env)
    assert proc.returncode == 0
    assert 'key_client_token: 已配置' in proc.stdout
    assert 'MS_KEY_CLIENT_TOKEN env' in proc.stdout
    assert 'secret-tok-xyz' not in proc.stdout


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
