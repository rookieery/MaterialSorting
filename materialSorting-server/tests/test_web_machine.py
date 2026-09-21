"""机器对接排料 API 测试（/api/machine/*，prd-machine-nesting-api）。

US-001 覆盖骨架三面：
  - AST 守卫：machine.py 全模块禁 import ..cli.*（复刻 test_web_strategy.py 守卫
    写法 —— spawn 子进程是进程边界而非 import 边界，判据逻辑单一真相源留 cli）；
  - 防环守卫：machine.py 对 server 的依赖必须**函数内延迟 import**（server 文件
    尾 import 本模块，模块级互相 import 成环；strategy.py 先例）—— 顶层语句不
    得出现任何形态的 server import；
  - 路由注册冒烟：register_machine_routes(fresh app) include_router 接线可用；
    server.py 文件尾在 strategy 注册**之后**调用（AST 顺序断言）；server app
    装配后 GET / 仍 200 + Cache-Control: no-cache（机器端点对工作台零扰动）。

US-002（本故事）覆盖 solve 提交端点：
  - 三模式 spawn 命令金标（normal=plain --time 180 / advanced=--strategy race
    --time 1200 / extreme=--extreme --time 7200，逐参数断言含 sys.executable 与
    -m materialsorting.cli.run_config）+ cfg 落盘对拍（time/seeds 烘焙、
    master_dxf 绝对路径）+ marker 恰 5 键 mode='machine' + 状态槽/会话快照；
  - 错误矩阵：缺 file→400 / >20MB→413 / gate_mm 缺失·非正·非整→400 / 坏 DXF→
    422 中文 / run_mode 值域外→400 / time·seeds·band·prefix 在场→400 / 坏
    JSON·非对象→400 / sizes·per_type·quantities·client_ref 形状→400；
  - 同 client_ref 在飞→409 返回既有 task_id（不二次 spawn）；终态后同 ref 放行；
  - default 会话不受扰：runtime._PIECES_STATE 的 doc_id 在 solve 前后不变（对拍）。

US-003 起补：status/stop/result 三端点行为、export 会话无关导出、幂等/清理/token。
端口可配（MS_WEB_PORT）由 server.main() 冒烟与部署文档覆盖（uvicorn 层，
TestClient 不经端口）。
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED
from fastapi import FastAPI
from fastapi.routing import APIRouter
from starlette.testclient import TestClient

from materialsorting import paths as paths_mod
from materialsorting.web import machine as machine_mod
from materialsorting.web import runtime as runtime_mod
from materialsorting.web import server as server_mod
from materialsorting.web import sessions as sessions_mod
from materialsorting.web import strategy as strategy_mod
from materialsorting.web.sessions import SID_RE


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
    """server app 装配含 machine 路由后工作台零扰动：GET / 200 + no-cache。"""
    with TestClient(server_mod.app) as client:
        r = client.get('/')
        assert r.status_code == 200
        assert r.headers.get('Cache-Control') == 'no-cache'
    # US-002 起真端点挂上本 router（solve 先行；status/stop/result/export/DELETE
    # 自 US-003 起逐故事补充 —— 本断言随之扩集）。
    machine_paths = {getattr(route, 'path', '') for route in machine_mod.router.routes}
    assert '/api/machine/solve' in machine_paths


# ============================================================= US-002 solve

# ------------------------------------------------------------- 测试基础设施


class FakeProc:
    """Popen 替身：poll() 返回预置 rc（None = 存活）。"""

    def __init__(self, pid: int = 4321, rc=None):
        self.pid = pid
        self._rc = rc

    def poll(self):
        return self._rc


@pytest.fixture
def machine_env(tmp_path, monkeypatch):
    """隔离环境：server.UPLOADS_DIR / paths.OUT_DIR·CONFIG_RUNS_DIR·INTERMEDIATE /
    tempfile.tempdir 指到 tmp_path + 状态槽清零 + 会话注册表隔离。

    machine solve 复用 server 的上传/commit 管线（延迟 import + 模块属性调用时
    取值），故四路 monkeypatch 缺一不可：UPLOADS_DIR 拦上传落盘与 per-doc
    intermediate、INTERMEDIATE 拦 commit 镜像双写、CONFIG_RUNS_DIR 拦 marker/
    run_dir、tempfile 拦 spawn stderr 临时文件。
    """
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', uploads)
    monkeypatch.setattr(paths_mod, 'OUT_DIR', str(tmp_path / 'out'))
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(tmp_path / 'config_runs'))
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE',
                        str(tmp_path / 'mirror_intermediate.json'))
    tmp_dir = tmp_path / 'tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(strategy_mod.tempfile, 'tempdir', str(tmp_dir))
    strategy_mod._STRATEGY_STATE.clear()
    strategy_mod._STRATEGY_STATES.clear()
    sessions_mod.registry.stop_scanner()
    sessions_mod.registry.reset()
    yield tmp_path
    strategy_mod._STRATEGY_STATE.clear()
    strategy_mod._STRATEGY_STATES.clear()
    sessions_mod.registry.reset()


_SYNTH_SHAPES = [('blk a', (0, 0, 400, 700)), ('blk b', (10, 10, 300, 500))]


def _yl_master_bytes(sizes=(28, 30)) -> bytes:
    """YL nest.dxf 风格合成母版（R12 + 带 POLYLINE layer1 + 布纹线 layer7，
    block 名 ``<名称>.<码号>``）—— 经 server parse+commit 真管线的合法载荷。"""
    doc = ezdxf.new('R12')
    for size in sizes:
        for name, (x, y, w, h) in _SYNTH_SHAPES:
            blk = doc.blocks.new(name=f'{name}.{size}')
            poly = blk.add_polyline2d(
                [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                dxfattribs={'layer': '1'})
            poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
            blk.add_line((x + 10, y + h / 2), (x + w - 10, y + h / 2),
                         dxfattribs={'layer': '7'})
    fd, path = tempfile.mkstemp(suffix='.dxf')
    os.close(fd)
    try:
        doc.saveas(path)
        with open(path, 'rb') as f:
            return f.read()
    finally:
        os.unlink(path)


def _spawn_capture(monkeypatch, pids=(4321,)):
    """打桩 spawn（strategy 单一生效点 = machine 模块属性访问处）：记录 cmd。"""
    calls = []
    pids_iter = iter(pids)

    def fake_spawn(cmd, stderr_path):
        calls.append({'cmd': list(cmd), 'stderr_path': stderr_path})
        return FakeProc(pid=next(pids_iter))

    monkeypatch.setattr(strategy_mod, '_spawn_run_process', fake_spawn)
    return calls


def _solve(client, master: bytes, config: dict, fname: str = 'nest.dxf'):
    return client.post('/api/machine/solve',
                       files={'file': (fname, master, 'application/octet-stream')},
                       data={'config': json.dumps(config)})


_FULL_CONFIG = {
    'gate_mm': 1750, 'sizes': [28, 30], 'run_mode': 'normal',
    'per_type': {'g01': {'d': 2.0}},
    'quantities': {'g01': {'28': 2}, 'g02': {'28': 1}},
}


def test_solve_three_modes_spawn_golden(machine_env, monkeypatch):
    """三模式 202 金标：spawn cmd 逐参数（策略段+烘焙时间）+ cfg 落盘（time/seeds
    烘焙、master_dxf 绝对路径）+ marker 恰 5 键 mode='machine' + 状态槽/会话快照。"""
    cases = [
        # (config 全量, spawn 策略段, cfg 期望键集)
        (dict(_FULL_CONFIG),
         [], {'master_dxf', 'gate_mm', 'time', 'seeds', 'sizes', 'per_type',
              'quantities'}),
        ({'gate_mm': 1750, 'run_mode': 'advanced'}, ['--strategy', 'race'],
         {'master_dxf', 'gate_mm', 'time', 'seeds'}),
        ({'gate_mm': 1750, 'run_mode': 'extreme'}, ['--extreme'],
         {'master_dxf', 'gate_mm', 'time', 'seeds'}),
    ]
    master = _yl_master_bytes()
    pids = (771, 772, 773)
    calls = _spawn_capture(monkeypatch, pids=pids)
    c = TestClient(server_mod.app)
    for i, (config, strat_args, cfg_keys) in enumerate(cases):
        r = _solve(c, master, config)
        assert r.status_code == 202, (i, r.text)
        body = r.json()
        assert set(body) == {'task_id', 'run_name', 'started_at'}, body
        task_id = body['task_id']
        assert task_id.startswith('m') and SID_RE.match(task_id)
        # run_name = machine_<task6>_<rand6>（run_dir 认领前缀 glob 无歧义口径）。
        parts = body['run_name'].split('_')
        assert len(parts) == 3 and parts[0] == 'machine'
        assert parts[1] == task_id[:6] and len(parts[2]) == 6

        # cfg 落盘对拍：machine_cfg_<sid>_<stamp>.json，time/seeds 烘焙进文件。
        cfg_files = sorted((machine_env / 'uploads').glob(f'machine_cfg_{task_id}_*.json'))
        assert len(cfg_files) == 1
        cfg = json.loads(cfg_files[0].read_text(encoding='utf-8'))
        assert set(cfg) == cfg_keys
        baked = {'normal': 180, 'advanced': 1200, 'extreme': 7200}[
            config.get('run_mode', 'normal')]
        assert cfg['time'] == baked and cfg['seeds'] == [0]
        assert cfg['gate_mm'] == 1750.0
        assert Path(cfg['master_dxf']).is_absolute()
        assert (machine_env / 'uploads' / Path(cfg['master_dxf']).name).exists()

        # spawn cmd 逐参数金标。
        cmd = calls[i]['cmd']
        assert cmd == [sys.executable, '-m', 'materialsorting.cli.run_config',
                       str(cfg_files[0]), '--name', body['run_name'],
                       *strat_args, '--time', str(baked), '--quiet']

        # marker 恰 5 键（mode='machine'；orphan 恢复路径同 strategy 口径）。
        marker = json.loads(
            strategy_mod._marker_path(task_id).read_text(encoding='utf-8'))
        assert set(marker) == {'pid', 'run_dir', 'doc_id', 'mode', 'started_at'}
        assert marker['mode'] == 'machine' and marker['pid'] == pids[i]
        assert marker['run_dir'] is None
        assert marker['started_at'] == body['started_at']

        # 状态槽：mode='machine' + run_mode/total_budget_sec（status US-003 消费）。
        st = strategy_mod._STRATEGY_STATES[task_id]
        assert st['state'] == 'starting' and st['mode'] == 'machine'
        assert st['run_mode'] == config.get('run_mode', 'normal')
        assert st['total_budget_sec'] == baked
        assert st['run_name'] == body['run_name']
        assert len(st['pieces_snapshot']) == 4   # 2 码（28/30）× 2 片全码

        # 会话快照已注册（只挂本任务 sid）。
        sess = sessions_mod.registry.resolve(task_id)
        assert sess.pieces and sess.doc_id == marker['doc_id']


def test_solve_default_pieces_state_untouched(machine_env, monkeypatch):
    """default 会话不受扰对拍：runtime._PIECES_STATE 的 doc_id 在 solve 前后不变
    （commit 只挂本任务 sid；镜像文件写盘 ≠ default 内存刷新）。"""
    sentinel = {'doc_id': 'defaultdoc0', 'source': 'keep.dxf'}
    monkeypatch.setitem(runtime_mod._PIECES_STATE, 'doc', sentinel)
    assert server_mod._PIECES_STATE is runtime_mod._PIECES_STATE   # 同一 dict 锁死
    _spawn_capture(monkeypatch, pids=(771,))
    r = _solve(TestClient(server_mod.app), _yl_master_bytes(),
               {'gate_mm': 1750})
    assert r.status_code == 202
    assert runtime_mod._PIECES_STATE['doc'] == sentinel
    # 镜像 intermediate 已写盘（commit 双写副作用），但 default 内存态未刷新。
    assert (machine_env / 'mirror_intermediate.json').exists()
    assert runtime_mod._PIECES_STATE['doc']['doc_id'] == 'defaultdoc0'


# ------------------------------------------------------------- 错误矩阵


def test_solve_missing_file_and_bad_extension_400(machine_env, monkeypatch):
    """缺 file 字段 / 非 .dxf 文件名 → 400；不 spawn 不落 cfg。"""
    calls = _spawn_capture(monkeypatch, pids=(771,))
    c = TestClient(server_mod.app)
    r = c.post('/api/machine/solve',
               data={'config': json.dumps({'gate_mm': 1750})})
    assert r.status_code == 400 and 'file' in r.json()['error']
    r2 = _solve(c, b'DXF', {'gate_mm': 1750}, fname='nest.txt')
    assert r2.status_code == 400 and '仅支持 .dxf' in r2.json()['error']
    assert not list((machine_env / 'uploads').glob('machine_cfg_*.json'))
    assert len(calls) == 0


def test_solve_oversize_413(machine_env, monkeypatch):
    """>20MB → 413（同 /api/parse-dxf 上限，读后才判）。"""
    _spawn_capture(monkeypatch, pids=(771,))
    big = b'x' * (server_mod.UPLOAD_MAX_BYTES + 1)
    r = _solve(TestClient(server_mod.app), big, {'gate_mm': 1750})
    assert r.status_code == 413
    assert '超过上限' in r.json()['error']


def test_solve_config_shape_errors_400(machine_env, monkeypatch):
    """config 缺字段 / 坏 JSON / 非对象 → 400。"""
    _spawn_capture(monkeypatch, pids=(771,))
    c = TestClient(server_mod.app)
    master = _yl_master_bytes()
    # 缺 config 字段。
    r = c.post('/api/machine/solve',
               files={'file': ('nest.dxf', master, 'application/octet-stream')})
    assert r.status_code == 400 and 'config' in r.json()['error']
    # 坏 JSON 字符串。
    r = c.post('/api/machine/solve',
               files={'file': ('nest.dxf', master, 'application/octet-stream')},
               data={'config': '{not-json'})
    assert r.status_code == 400 and 'JSON' in r.json()['error']
    # 非对象 JSON。
    r = c.post('/api/machine/solve',
               files={'file': ('nest.dxf', master, 'application/octet-stream')},
               data={'config': '[1,2]'})
    assert r.status_code == 400 and '对象' in r.json()['error']
    assert not list((machine_env / 'uploads').glob('machine_cfg_*.json'))


def test_solve_gate_mm_domain_400(machine_env, monkeypatch):
    """gate_mm 缺失 / 0 / 负 / 字符串 / bool / 非整浮点 → 400（全不落 cfg 不 spawn）。"""
    calls = _spawn_capture(monkeypatch, pids=(771,) * 6)
    c = TestClient(server_mod.app)
    master = _yl_master_bytes()
    for bad in ({}, {'gate_mm': 0}, {'gate_mm': -5}, {'gate_mm': '1750'},
                {'gate_mm': True}, {'gate_mm': 1750.5}):
        r = _solve(c, master, bad)
        assert r.status_code == 400, bad
        assert 'gate_mm' in r.json()['error'], bad
    assert not list((machine_env / 'uploads').glob('machine_cfg_*.json'))
    assert len(calls) == 0


def test_solve_run_mode_and_forbidden_keys_400(machine_env, monkeypatch):
    """run_mode 值域外 → 400；time/seeds/band/prefix 在场 → 400（全默认零暴露）。"""
    calls = _spawn_capture(monkeypatch, pids=(771,) * 5)
    c = TestClient(server_mod.app)
    master = _yl_master_bytes()
    r = _solve(c, master, {'gate_mm': 1750, 'run_mode': 'turbo'})
    assert r.status_code == 400 and 'run_mode' in r.json()['error']
    for key in ('time', 'seeds', 'band', 'prefix'):
        r = _solve(c, master, {'gate_mm': 1750, key: 999})
        assert r.status_code == 400, key
        assert key in r.json()['error'], key
    assert not list((machine_env / 'uploads').glob('machine_cfg_*.json'))
    assert len(calls) == 0


def test_solve_sizes_per_type_quantities_client_ref_shapes_400(
        machine_env, monkeypatch):
    """sizes 元素/空列表、per_type 负值/非对象、quantities 负值/非整数份数、
    client_ref 超长/非字符串 → 400 结构化早退。"""
    calls = _spawn_capture(monkeypatch, pids=(771,) * 8)
    c = TestClient(server_mod.app)
    master = _yl_master_bytes()
    bads = [
        {'gate_mm': 1750, 'sizes': [28, '30']},
        {'gate_mm': 1750, 'sizes': []},
        {'gate_mm': 1750, 'per_type': 'x'},
        {'gate_mm': 1750, 'per_type': {'g01': {'d': -1}}},
        {'gate_mm': 1750, 'quantities': {'g01': 'x'}},
        {'gate_mm': 1750, 'quantities': {'g01': {'28': -1}}},
        {'gate_mm': 1750, 'quantities': {'g01': {'28': 1.5}}},
        {'gate_mm': 1750, 'client_ref': 'r' * 129},
    ]
    for bad in bads:
        r = _solve(c, master, bad)
        assert r.status_code == 400, bad
    assert len(calls) == 0
    assert not list((machine_env / 'uploads').glob('machine_cfg_*.json'))


def test_solve_bad_dxf_422(machine_env, monkeypatch):
    """坏 DXF → 422 中文（parse+commit 管线异常结构化透出，不 500）。"""
    _spawn_capture(monkeypatch, pids=(771,))
    r = _solve(TestClient(server_mod.app), b'this is not a dxf at all',
               {'gate_mm': 1750})
    assert r.status_code == 422
    assert '解析失败' in r.json()['error']
    # 失败路径不写 marker / 不 spawn / 不占状态槽。
    assert not list((machine_env / 'config_runs').glob('.web_strategy_active_*'))
    assert not list((machine_env / 'uploads').glob('machine_cfg_*.json'))


# ------------------------------------------------------------- client_ref 幂等


def test_solve_client_ref_inflight_409_then_release(machine_env, monkeypatch):
    """同 client_ref 在飞 → 409 返回既有 task_id（不二次 spawn）；终态后放行。"""
    calls = _spawn_capture(monkeypatch, pids=(771, 772))
    c = TestClient(server_mod.app)
    master = _yl_master_bytes()
    config = {'gate_mm': 1750, 'client_ref': 'yl-ref-42'}
    r1 = _solve(c, master, config)
    assert r1.status_code == 202
    task1 = r1.json()['task_id']

    r2 = _solve(c, master, config)
    assert r2.status_code == 409
    assert r2.json()['task_id'] == task1
    assert len(calls) == 1                       # 409 路径不 spawn

    # 终态（done）后同 ref 放行新任务。
    strategy_mod._STRATEGY_STATES[task1]['state'] = 'done'
    r3 = _solve(c, master, config)
    assert r3.status_code == 202
    assert r3.json()['task_id'] != task1
    assert len(calls) == 2
