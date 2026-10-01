"""机器对接浏览器直连 Origin 白名单 machine_cors（US-001）+ CORS/PNA 中间件
（US-002）测试。

US-001 覆盖：
1. AST 守卫：模块级仅标准库 + ``..paths``（镜像 test_web_keygate 先例），
   禁 import server（依赖方向 server → machine_cors 单向无环）/ 禁 import
   cli 子包（web 禁反向依赖上层）；
2. 三档优先序：env（逗号/分号多值解析）→ sidecar（frozen = exe 旁优先 →
   LICENSE_DIR 回落 / dev = LICENSE_DIR）→ 皆无 ``None``；
3. 多值解析：env 混合分隔符 / sidecar 多行 strip 空行 / set 去重；
4. 空文件回落：某位置文件存在但全空行 = 该位未配置，继续向后回落；
5. frozen 双位置对拍（keygate 冒烟 keygate.py:498-523 先例写法：
   ``sys.frozen=True`` + 临时 exe 路径 monkeypatch）；
6. 请求时读取（非 import 期绑定）+ ``paths.LICENSE_DIR`` 调用时取值；
7. ``describe_machine_allowed_origins`` 三档来源标注；
8. ``python -m materialsorting.web.machine_cors`` 子进程冒烟 exit 0
   （输出含来源标注）。

US-002 覆盖（中间件测试组，照 test_web_machine.py:1336-1377 token 测试骨架 +
machine_env 精简镜像 fixture，经真实 ``server.app`` 端到端）：
9. server.py 装配序 AST 断言：``register_machine_cors`` 在
   ``register_machine_routes`` 之后（镜像 test_server_registers_machine_
   after_strategy，不破坏既有断言）；
10. 预检自答：白名单内 Origin OPTIONS → 200 五头精确值（ACAO 回显具体值
    禁 ``*`` / Methods / Headers / PNA true / Max-Age 86400）；
11. 实际响应 ACAO 回显：401（token 闸）与 404（未知任务）错误体浏览器可读；
12. 白名单外 Origin → 403 服务端主动拒（拦在路由前，无落盘无 spawn —— 防
    CSRF 型 simple request 触发任务），不带任何 CORS 头；
13. 无 Origin 头（服务端/工具直调）→ 路由照常不加头（loopback 现状零变化）；
14. 前缀外路径零扰动：外域 Origin 打 GET / 仍 200 无 CORS 头（挂入零扰动）；
15. 未配置白名单（三档皆无）→ 逐字节现状零回归：GET / 200 no-cache、
    OPTIONS /api/machine/solve 落 405、带 Origin 实调不 403 不加头。
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.web import machine_cors
from materialsorting.web import server as server_mod


# ----------------------------------------------------------------- fixtures

@pytest.fixture
def license_dir(tmp_path, monkeypatch):
    """LICENSE_DIR 重定向到 tmp（machine_cors 调用时取 ``paths.LICENSE_DIR``
    模块属性）。"""
    target = tmp_path / 'license'
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(target))
    return target


@pytest.fixture
def no_origins(tmp_path, monkeypatch):
    """白名单链归零：无 env、未冻结、LICENSE_DIR 指空 tmp（防真实
    out/license/ 漏读串档，keygate no_server_url 同款）。"""
    monkeypatch.delenv(machine_cors.MACHINE_ORIGINS_ENV, raising=False)
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(tmp_path / 'license'))


# ------------------------------------------------------------- AST 守卫（分层）

def test_machine_cors_module_layering_purity():
    """machine_cors 模块级仅标准库 + ``..paths``；禁 import server（依赖方向
    server → machine_cors 单向无环）/ 禁 import cli 子包（镜像 keygate 守卫）。"""
    src = Path(machine_cors.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'os', 'sys', 'pathlib', 'materialsorting'}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue          # 函数/类体内延迟 import（_smoke 的 tempfile）不受顶层约束
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                names = {a.name.split('.')[0] for a in sub.names}
            elif isinstance(sub, ast.ImportFrom):
                mod = sub.module or ''
                assert not mod.startswith('materialsorting.web.server'), \
                    'machine_cors 禁 import server（依赖方向 server → machine_cors）'
                assert not mod.startswith('materialsorting.cli'), \
                    'machine_cors 禁 import cli（web 禁反向依赖上层）'
                if sub.level:                 # 相对 import 解析到上层 paths
                    names = {'materialsorting'}
                else:
                    names = {mod.split('.')[0]}
            else:
                continue
            assert names <= allowed, sorted(names - allowed)
    # 相对 import 白名单（任意位置）：仅顶层 ``..paths``
    for sub in ast.walk(tree):
        if isinstance(sub, ast.ImportFrom) and sub.level:
            # ``from .. import paths``（module=None）与 ``from ..paths import X`` 两形态
            ok = sub.level == 2 and sub.module in (None, 'paths')
            assert ok, f'相对 import 仅 ..paths 允许：{sub.module}'
    # 源级哨兵：任何 server / cli 引用（含函数内延迟 import）都不允许
    assert 'materialsorting.web.server' not in src
    assert 'materialsorting.cli' not in src
    assert 'from .server' not in src


def test_env_names_locked():
    """env 变量名 / sidecar 文件名契约锁定（US-004 交付链与 YL 文档消费）。"""
    assert machine_cors.MACHINE_ORIGINS_ENV == 'MS_MACHINE_ALLOWED_ORIGINS'
    assert machine_cors.MACHINE_ORIGINS_FILE_NAME == 'machine_allowed_origins.txt'


# ------------------------------------------------------------- 档一 env

def test_env_single_value(no_origins, monkeypatch):
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://yl.example.com')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://yl.example.com'}


def test_env_multi_value_comma_and_semicolon(no_origins, monkeypatch):
    """env 多值：逗号/分号混合分隔 + 逐项 strip。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://a.example.com, https://b.example.com;'
                       '  https://c.example.com  ')
    assert machine_cors.resolve_machine_allowed_origins() == {
        'https://a.example.com', 'https://b.example.com',
        'https://c.example.com'}


def test_env_duplicates_deduped(no_origins, monkeypatch):
    """重复 Origin 去重（set 口径）。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://a.example.com,https://a.example.com')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://a.example.com'}


def test_env_blank_is_absent(no_origins, monkeypatch):
    """空白串 env 视为未配置（不与 sidecar 抢档）。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV, '   ')
    assert machine_cors.resolve_machine_allowed_origins() is None


def test_env_beats_sidecar(no_origins, license_dir, monkeypatch):
    """档序锁定：env 优先于 sidecar（两档并存取 env）。"""
    license_dir.mkdir(parents=True, exist_ok=True)
    (license_dir / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://lic.example.com', encoding='utf-8')
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://env.example.com')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://env.example.com'}


def test_env_unset_falls_to_absent(no_origins):
    """无 env 无 sidecar → None（零回归现状档）。"""
    assert machine_cors.resolve_machine_allowed_origins() is None


def test_resolve_request_time_not_import_bound(no_origins, monkeypatch):
    """env 请求时读取（非 import 期绑定）：同一进程改 env 即改解析结果。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://a.example.com')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://a.example.com'}
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://b.example.com')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://b.example.com'}


# ------------------------------------------------------------- 档二 sidecar

def test_frozen_exe_sidecar_multiline(no_origins, tmp_path, monkeypatch):
    """frozen exe 旁 sidecar 多行列表：空行剔除 + 行内 strip + 去重。"""
    exe = tmp_path / 'app.exe'
    exe.write_bytes(b'MZ')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(exe))
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://exe.example.com\n'
        '\n'
        '  https://exe2.example.com  \n'
        'https://exe.example.com\n'
        '\n', encoding='utf-8')
    assert machine_cors.resolve_machine_allowed_origins() == {
        'https://exe.example.com', 'https://exe2.example.com'}


def test_frozen_sidecar_blank_file_falls_back_to_license(no_origins, tmp_path,
                                                         monkeypatch):
    """exe 旁文件存在但全空行 = 该位未配置 → 继续 license/ 回落查找。"""
    lic = tmp_path / 'license'
    lic.mkdir(parents=True)
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(lic))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        '  \n \n', encoding='utf-8')
    assert machine_cors.resolve_machine_allowed_origins() is None
    (lic / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://lic.example.com\n', encoding='utf-8')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://lic.example.com'}


def test_frozen_dual_position_exe_wins(no_origins, tmp_path, monkeypatch):
    """frozen 双位置并存：exe 旁优先（交付契约），license/ 仅回落。"""
    lic = tmp_path / 'license'
    lic.mkdir(parents=True)
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(lic))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://exe.example.com', encoding='utf-8')
    (lic / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://lic.example.com', encoding='utf-8')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://exe.example.com'}


def test_frozen_missing_everywhere_none(no_origins, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    assert machine_cors.resolve_machine_allowed_origins() is None


def test_dev_sidecar_license_dir(no_origins, license_dir):
    """dev（未冻结）读 LICENSE_DIR 下 sidecar（out/license/）。"""
    license_dir.mkdir(parents=True, exist_ok=True)
    (license_dir / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://dev.example.com\nhttps://dev2.example.com\n',
        encoding='utf-8')
    assert machine_cors.resolve_machine_allowed_origins() == {
        'https://dev.example.com', 'https://dev2.example.com'}


def test_dev_ignores_exe_side(no_origins, tmp_path, monkeypatch):
    """dev 态不读 exe 旁 sidecar（exe 旁 = frozen 专属交付契约）。"""
    assert not hasattr(sys, 'frozen') or not sys.frozen
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://exe.example.com', encoding='utf-8')
    monkeypatch.setattr(sys, 'executable', 'C:/nowhere/python.exe')
    assert machine_cors.resolve_machine_allowed_origins() is None


def test_license_dir_read_at_call_time(no_origins, tmp_path, monkeypatch):
    """``paths.LICENSE_DIR`` 调用时取模块属性（monkeypatch 直接生效，
    keygate ``_reload_pieces_state`` 缺省参数坑的同款防御）。"""
    lic = tmp_path / 'lic2'
    lic.mkdir()
    (lic / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://x.example.com', encoding='utf-8')
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(lic))
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://x.example.com'}


# ------------------------------------------------- describe（来源标注）

def test_describe_env_tier(no_origins, monkeypatch):
    """env 档描述：值 + 来源标注 + 条数。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://yl.example.com')
    text = machine_cors.describe_machine_allowed_origins()
    assert 'https://yl.example.com' in text
    assert f'{machine_cors.MACHINE_ORIGINS_ENV} env' in text
    assert '共 1 条' in text


def test_describe_sidecar_tiers(no_origins, tmp_path, monkeypatch):
    """sidecar 档来源标注跟随实际命中文件：exe 旁 / license/ 回落档 /
    dev out/license/ 三标签可区分（--check 售后定位）。"""
    # frozen exe 旁档
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://exe.example.com', encoding='utf-8')
    text = machine_cors.describe_machine_allowed_origins()
    assert 'https://exe.example.com' in text and 'exe 旁' in text
    # frozen license/ 回落档（exe 旁缺失）
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).unlink()
    lic = tmp_path / 'license'
    lic.mkdir(parents=True)
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(lic))
    (lic / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://lic.example.com', encoding='utf-8')
    text = machine_cors.describe_machine_allowed_origins()
    assert 'https://lic.example.com' in text and '回落' in text
    # dev out/license/ 档
    monkeypatch.delattr(sys, 'frozen', raising=False)
    text = machine_cors.describe_machine_allowed_origins()
    assert 'https://lic.example.com' in text and 'out/license/' in text


def test_describe_unconfigured(no_origins):
    """皆无档描述：未配置 + 零回归语义 + 两条配置路径指引。"""
    text = machine_cors.describe_machine_allowed_origins()
    assert '未配置' in text
    assert machine_cors.MACHINE_ORIGINS_ENV in text
    assert machine_cors.MACHINE_ORIGINS_FILE_NAME in text
    assert '不发 CORS 头' in text


# ------------------------------------------------------------- 子进程冒烟

def test_module_smoke_subprocess():
    """AC：``python -m materialsorting.web.machine_cors`` 合成夹具冒烟 exit 0，
    输出含来源标注（env 档注入使「当前解析结果」行确定性）。"""
    env = {**os.environ, 'PYTHONPATH': str(_SRC)}
    env['PYTHONIOENCODING'] = 'utf-8'   # 子进程管道输出恒 UTF-8（Windows 管道缺省 locale/GBK）
    env[machine_cors.MACHINE_ORIGINS_ENV] = 'https://yl-smoke.example.com'
    result = subprocess.run(
        [sys.executable, '-m', 'materialsorting.web.machine_cors'],
        capture_output=True, env=env, timeout=120,
        cwd=str(_SRC.parent))
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout.decode('utf-8', 'replace')
    assert 'FAIL' not in out
    assert 'PASS' in out and '冒烟' in out
    assert 'https://yl-smoke.example.com' in out
    assert f'{machine_cors.MACHINE_ORIGINS_ENV} env' in out, '输出须含来源标注'


# ============================================================= US-002 中间件

_YL_ORIGIN = 'https://yl.example.com'
_EVIL_ORIGIN = 'https://evil.example.com'


@pytest.fixture
def machine_api_env(tmp_path, monkeypatch, no_origins):
    """中间件测试基座：白名单链归零（``no_origins``）+ server 落盘四路重定向
    （``machine_env`` 精简镜像 —— 中间件 403 拦在路由前、错误路径只读，本组
    无 spawn 无落盘，隔离为防御性：未知任务 404 读 marker 亦不触真实
    out/config_runs/）。"""
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', uploads)
    monkeypatch.setattr(paths_mod, 'OUT_DIR', str(tmp_path / 'out'))
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(tmp_path / 'config_runs'))
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE',
                        str(tmp_path / 'mirror_intermediate.json'))
    return uploads


def test_server_registers_machine_cors_after_machine_routes():
    """server.py 文件尾在 register_machine_routes 之后调用 register_machine_cors
    （AST 顺序，镜像 test_server_registers_machine_after_strategy 断言写法；
    用户中间件栈请求期构建且整体包住路由，锁序为装配区可读性约定）。"""
    src = Path(server_mod.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    calls: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id in (
                    'register_strategy_routes', 'register_machine_routes',
                    'register_machine_cors'):
                calls.append(func.id)
    assert 'register_machine_routes' in calls, 'server.py 未调用 register_machine_routes'
    assert 'register_machine_cors' in calls, 'server.py 未调用 register_machine_cors'
    assert calls.index('register_machine_cors') > calls.index('register_machine_routes')


def test_preflight_whitelisted_five_headers_exact(machine_api_env, monkeypatch):
    """预检自答：白名单内 Origin OPTIONS → 200，五头精确匹配（ACAO 回显具体
    值禁 ``*`` / Methods / Headers / PNA true / Max-Age 86400）+ Vary: Origin。
    两个机器族路径各验一次（solve 提交面 + DELETE 清理面 = 前缀全族生效）。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV, _YL_ORIGIN)
    c = TestClient(server_mod.app)
    for path, method in (('/api/machine/solve', 'POST'),
                         ('/api/machine/solve/m2021cors00', 'DELETE')):
        r = c.options(path, headers={
            'Origin': _YL_ORIGIN,
            'Access-Control-Request-Method': method,
            'Access-Control-Request-Private-Network': 'true'})
        assert r.status_code == 200, (path, r.status_code)
        assert r.headers['access-control-allow-origin'] == _YL_ORIGIN
        assert r.headers['access-control-allow-methods'] == 'GET, POST, DELETE'
        assert r.headers['access-control-allow-headers'] \
            == 'x-machine-token, content-type'
        assert r.headers['access-control-allow-private-network'] == 'true'
        assert r.headers['access-control-max-age'] == '86400'
        assert r.headers['vary'] == 'Origin'


def test_preflight_foreign_origin_rejected_no_cors_headers(machine_api_env,
                                                           monkeypatch):
    """白名单外 Origin 预检 → 403 不带任何 CORS 头（浏览器报跨域失败即预期，
    服务端纵深防御 —— Starlette 中间件先于路由，预检与 simple request 同闸）。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV, _YL_ORIGIN)
    c = TestClient(server_mod.app)
    r = c.options('/api/machine/solve', headers={
        'Origin': _EVIL_ORIGIN, 'Access-Control-Request-Method': 'POST'})
    assert r.status_code == 403
    assert 'access-control-allow-origin' not in r.headers
    assert '白名单' in r.json()['error']


def test_actual_error_responses_carry_acao(machine_api_env, monkeypatch):
    """白名单内 Origin 实际请求：401（token 闸）与 404（未知任务）错误响应均
    带 ACAO 回显（+ Vary: Origin）—— 浏览器直连时可读到错误体（联调关键）。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV, _YL_ORIGIN)
    monkeypatch.setenv('MS_MACHINE_TOKEN', 'sekret-token')
    c = TestClient(server_mod.app)
    r = c.get('/api/machine/solve/m2021cors00/status',
              headers={'Origin': _YL_ORIGIN})
    assert r.status_code == 401                      # token 闸先行
    assert r.headers['access-control-allow-origin'] == _YL_ORIGIN
    assert r.headers['vary'] == 'Origin'
    # 未知任务 404（token 对头放行后落 task_id 闸）同样带 ACAO。
    r2 = c.get('/api/machine/solve/m2021cors00/status',
               headers={'Origin': _YL_ORIGIN,
                        'x-machine-token': 'sekret-token'})
    assert r2.status_code == 404
    assert r2.headers['access-control-allow-origin'] == _YL_ORIGIN


def test_actual_foreign_origin_403_pre_routing(machine_api_env, monkeypatch):
    """白名单外 Origin 实际请求 → 403 拦在路由前：不落 uploads、不进任务闸
    （CSRF 型 simple request 打不到任务端点）；任意机器族路径（含不存在的
    /api/machine/xxx）都被前缀闸拦下。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV, _YL_ORIGIN)
    c = TestClient(server_mod.app)
    r = c.post('/api/machine/solve', headers={'Origin': _EVIL_ORIGIN},
               files={'file': ('nest.dxf', b'MZ-fake',
                               'application/octet-stream')},
               data={'config': '{"gate_mm": 1750}'})
    assert r.status_code == 403 and '白名单' in r.json()['error']
    assert 'access-control-allow-origin' not in r.headers
    assert not list(machine_api_env.iterdir())        # 无任何上传/落盘
    r2 = c.get('/api/machine/solve/m2021cors00/status',
               headers={'Origin': _EVIL_ORIGIN})
    r3 = c.get('/api/machine/never-exists', headers={'Origin': _EVIL_ORIGIN})
    assert r2.status_code == r3.status_code == 403


def test_no_origin_header_passes_untouched(machine_api_env, monkeypatch):
    """无 Origin 头（YL 服务端中转 / curl / loopback 同机）→ 路由照常、不附
    任何 CORS 头 —— 白名单配置与否都不影响非浏览器调用方（现状零变化）。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV, _YL_ORIGIN)
    c = TestClient(server_mod.app)
    r = c.get('/api/machine/solve/m2021cors00/status')
    assert r.status_code == 404                      # 未知任务照常 404
    assert 'access-control-allow-origin' not in r.headers


def test_non_machine_prefix_zero_disturbance(machine_api_env, monkeypatch):
    """挂入零扰动：白名单外 Origin 打前缀外路径（GET / 工作台首页）→ 仍 200
    + Cache-Control no-cache，不 403、不附 CORS 头（前缀闸只管 /api/machine/*）。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV, _YL_ORIGIN)
    c = TestClient(server_mod.app)
    r = c.get('/', headers={'Origin': _EVIL_ORIGIN})
    assert r.status_code == 200
    assert r.headers['cache-control'] == 'no-cache'
    assert 'access-control-allow-origin' not in r.headers


def test_unconfigured_zero_regression(machine_api_env):
    """未配置白名单（三档皆无）→ 逐字节现状零回归：GET / 200 no-cache、
    OPTIONS /api/machine/solve 落 405、带 Origin 的实调不 403 也不加头（与
    未挂中间件行为一致 —— YL 服务端中转形态不受部署白名单与否影响）。"""
    assert machine_cors.resolve_machine_allowed_origins() is None
    c = TestClient(server_mod.app)
    r0 = c.get('/')
    assert r0.status_code == 200 and r0.headers['cache-control'] == 'no-cache'
    assert 'access-control-allow-origin' not in r0.headers
    ro = c.options('/api/machine/solve', headers={
        'Origin': _YL_ORIGIN, 'Access-Control-Request-Method': 'POST'})
    assert ro.status_code == 405                     # 路由层现状（不自答）
    assert 'access-control-allow-origin' not in ro.headers
    rs = c.get('/api/machine/solve/m2021cors00/status',
               headers={'Origin': _EVIL_ORIGIN})
    assert rs.status_code == 404                     # 不校验 Origin：照常 404
    assert 'access-control-allow-origin' not in rs.headers
