"""机器对接排料 API 测试（/api/machine/*，prd-machine-nesting-api）。

US-001（本故事）覆盖骨架三面：
  - AST 守卫：machine.py 全模块禁 import ..cli.*（复刻 test_web_strategy.py 守卫
    写法 —— spawn 子进程是进程边界而非 import 边界，判据逻辑单一真相源留 cli）；
  - 防环守卫：machine.py 对 server 的依赖必须**函数内延迟 import**（server 文件
    尾 import 本模块，模块级互相 import 成环；strategy.py 先例）—— 顶层语句不
    得出现任何形态的 server import；
  - 路由注册冒烟：register_machine_routes(fresh app) include_router 接线可用
    （探针端点经 TestClient 可达，US-002 起真端点挂上即被 server 装配）；server.py
    文件尾在 strategy 注册**之后**调用（AST 顺序断言）；server app 装配后 GET /
    仍 200 + Cache-Control: no-cache（机器骨架对既有工作台零扰动）。

US-002 起补：solve 提交端点错误矩阵 + 三模式 spawn 金标、status/stop/result 三
端点行为、export 会话无关导出、幂等/清理/token。端口可配（MS_WEB_PORT）由
server.main() 冒烟与部署文档覆盖（uvicorn 层，TestClient 不经端口）。
"""
from __future__ import annotations

import ast
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRouter
from starlette.testclient import TestClient

from materialsorting.web import machine as machine_mod
from materialsorting.web import server as server_mod


# ------------------------------------------------------------- AST 守卫（分层红线）


def test_machine_module_no_cli_import():
    """AST 守卫：machine.py 全模块禁 import ..cli.*（镜像 test_web_strategy.py）。

    spawn ``python -m materialsorting.cli.run_config`` 是**进程边界**，不触发本
    守卫；import 边界才触发。判据逻辑（race 门杀 / se 筛延 / 极限档）单一真相源
    留在 cli，web 层零漂移。
    """
    src = Path(machine_mod.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parts = [p for p in (node.module or '').split('.') if p]
            assert 'cli' not in parts, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert 'cli' not in alias.name.split('.'), alias.name


def test_machine_server_import_lazy_not_module_level():
    """防环守卫：machine.py 顶层禁 import server（依赖须函数内延迟 import）。

    server.py 文件尾 ``from .machine import register_machine_routes`` —— 若本
    模块顶层再 import server，「先 import machine」路径直接成环。函数内延迟
    import（strategy.py ``_get_pieces_state`` 先例）合法，故只扫顶层语句。
    """
    src = Path(machine_mod.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ''
            parts = [p for p in module.split('.') if p]
            assert parts != ['server'], f'顶层 from {module!r} import ...（须函数内延迟）'
            assert not module.endswith('.server'), f'顶层 from {module!r} import ...（须函数内延迟）'
            for alias in node.names:
                assert alias.name != 'server', f'顶层 from {module!r} import server（须函数内延迟）'
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split('.')
                assert 'server' not in parts, f'顶层 import {alias.name}（须函数内延迟）'


# ------------------------------------------------------------- 路由注册冒烟


def test_register_machine_routes_include_wiring():
    """注册接线冒烟：register_machine_routes(fresh app) 把本模块 router 挂进 app。

    骨架期 router 为空（无可探测路径），在**裸 router 副本**上挂探针端点验证
    include_router 机制 —— US-002 起真端点挂到同一 router 即被 server 装配。
    """
    assert isinstance(machine_mod.router, APIRouter)
    fresh = FastAPI()

    @machine_mod.router.get('/api/machine/__probe__')
    def _probe():
        return {'ok': True}

    try:
        machine_mod.register_machine_routes(fresh)
        with TestClient(fresh) as client:
            r = client.get('/api/machine/__probe__')
            assert r.status_code == 200
            assert r.json() == {'ok': True}
    finally:
        machine_mod.router.routes[:] = [
            route for route in machine_mod.router.routes
            if getattr(route, 'path', '') != '/api/machine/__probe__'
        ]


def test_server_registers_machine_after_strategy():
    """server.py 文件尾在 strategy 注册之后调用 register_machine_routes（AST 顺序）。

    strategy 家族注册顺序有语义（machine 复用 strategy 的 spawn/marker/钉住
    hook 骨架，US-002 起接线；注册点晚于 strategy 是既定约定）。
    """
    src = Path(server_mod.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    calls: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name):
                if func.id in ('register_strategy_routes', 'register_machine_routes'):
                    calls.append(func.id)
    assert 'register_strategy_routes' in calls, 'server.py 未调用 register_strategy_routes'
    assert 'register_machine_routes' in calls, 'server.py 未调用 register_machine_routes'
    assert calls.index('register_machine_routes') > calls.index('register_strategy_routes')


def test_server_app_healthy_with_machine_router():
    """server app 装配含 machine 骨架后工作台零扰动：GET / 200 + no-cache。"""
    with TestClient(server_mod.app) as client:
        r = client.get('/')
        assert r.status_code == 200
        assert r.headers.get('Cache-Control') == 'no-cache'
    # 机器骨架不占既有路由命名空间（US-002 前无 /api/machine/* 真端点注册进 server）
    machine_paths = {getattr(route, 'path', '') for route in machine_mod.router.routes}
    assert not any(p.startswith('/api/machine/') for p in machine_paths), \
        f'US-001 骨架期应为空 router，实际挂了端点：{machine_paths}'
