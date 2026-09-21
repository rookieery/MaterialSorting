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

US-002 覆盖 solve 提交端点：
  - 三模式 spawn 命令金标（normal=plain --time 180 / advanced=--strategy race
    --time 1200 / extreme=--extreme --time 7200，逐参数断言含 sys.executable 与
    -m materialsorting.cli.run_config）+ cfg 落盘对拍（time/seeds 烘焙、
    master_dxf 绝对路径）+ marker 恰 5 键 mode='machine' + 状态槽/会话快照；
  - 错误矩阵：缺 file→400 / >20MB→413 / gate_mm 缺失·非正·非整→400 / 坏 DXF→
    422 中文 / run_mode 值域外→400 / time·seeds·band·prefix 在场→400 / 坏
    JSON·非对象→400 / sizes·per_type·quantities·client_ref 形状→400；
  - 同 client_ref 在飞→409 返回既有 task_id（不二次 spawn）；终态后同 ref 放行；
  - default 会话不受扰：runtime._PIECES_STATE 的 doc_id 在 solve 前后不变（对拍）。

US-003（本故事）覆盖 status/stop/result 三端点：
  - status 载荷金标：normal 档 running 期 incumbent 走 best_frame 边车回落
    （plain run portfolio.incumbent 恒 null，US-002 实测）+ 运行中 curve 非法
    JSON 在场仍 200（绝不读 curve）+ 恰 10 键无 placed_items；race（advanced）
    / extreme 档各一状态金标（portfolio.incumbent 优先 + run_mode/total_budget
    透传）；error 态 stderr 尾；未知/非法/外族 task_id 400·404；
  - 轮询刷活性：solve 后会话被逐出（registry 清空模拟 TTL 过窗）status 仍 200
    （_STRATEGY_STATES 内存态路径，machine 不走会话闸门）；solve 全流程
    starting→running→done 状态推进；
  - orphan：pid 存活 → orphan（alive/pid 附加键）可 stop；pid 死 + 30s 宽限 →
    error；run_mode/total_budget 经 machine_cfg 反查恢复；
  - stop：taskkill /PID /T /F 树杀 + run_dir 保留 + stopped 后 result 仍可读
    （best_frame density 最大回落）；
  - result：running→409；done plain 档 manifest.pieces 键集含 raw_polygon/
    d_mm/demand/color + demand>1 的 g 码 placed_items 发 N 条绝不按 pid 去重；
    终态后 stop→400。

US-004（本故事）覆盖 export 会话无关导出：
  - 默认档金标：done 任务 POST {task_id} → 200 PLT = 门面直算（placed_to_world +
    parse_table_payload({}) + build_info_table + write_marker_plt(clean=True)）
    逐字节一致 —— 表格区在场、6 手输字段默认值（A料/0.0%/0.0%/空/noname/空）、
    8 项自动计算字段全算非空；Content-Disposition 中文/ASCII 双写（_clean 后缀）；
  - 会话过期对拍：registry.reset() 显式逐出后导出仍 200 且逐字节一致（pieces
    直载 run_dir pieces_intermediate.json 路径）；
  - fmt='plt' 全量版（clean=False + 表格在场）与显式 table（经 parse_table_payload
    合法值对拍）/非法 table → 400 中文；placed 显式子集对拍 + 全未命中 → 400
    既有兜底 + 非法形状 → 400；
  - pieces 兜底链：run_dir 无 intermediate → 会话快照 → 状态槽 pieces_snapshot；
    三源全空 → 409；task_id 闸矩阵（非格式 400 / 未知 404 / 外族 404）、fmt 值域
    400、非 JSON body 400、无 run_dir 409、无布局帧 409。

US-005 起补：幂等/清理/token。
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
import uuid
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED
from fastapi import FastAPI
from fastapi.routing import APIRouter
from starlette.testclient import TestClient
from urllib.parse import quote

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
    # US-002 起真端点挂上本 router（solve 先行；US-003 status/stop/result；
    # US-004 export；DELETE 自 US-005 起补充 —— 本断言随之扩集）。
    machine_paths = {getattr(route, 'path', '') for route in machine_mod.router.routes}
    assert '/api/machine/solve' in machine_paths
    assert '/api/machine/solve/{task_id}/status' in machine_paths
    assert '/api/machine/solve/{task_id}/stop' in machine_paths
    assert '/api/machine/solve/{task_id}/result' in machine_paths
    assert '/api/machine/export' in machine_paths


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


# ============================================================= US-003 status/stop/result

# status 契约恰 10 键（orphan 态 additive alive/pid 两诊断键在外）。
_STATUS_KEYS = {'state', 'mode', 'run_mode', 'total_budget_sec', 'elapsed_sec',
                'incumbent', 'current', 'per_seed', 'error', 'exit_code'}


def _synth_pieces() -> list[dict]:
    """合成 3 片（g01_28 / g02_28 / g01_30，schema v2）—— build_pid_meta /
    result manifest 组装用（demand 判定按 label×sizeKey 查 quantities）。"""
    return [
        {'pid': 'g01_28', 'label': 'g01', 'size': 28,
         'polygon': [[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]],
         'bbox': [0.0, 0.0, 500.0, 800.0], 'area_mm2': 400000.0, 'n_verts': 4,
         'allowed_angles': [0, 180],
         'net_polygon': [], 'internal_lines': [], 'notches': [],
         'grain_line': None},
        {'pid': 'g02_28', 'label': 'g02', 'size': 28,
         'polygon': [[0.0, 0.0], [300.0, 0.0], [300.0, 400.0], [0.0, 400.0]],
         'bbox': [0.0, 0.0, 300.0, 400.0], 'area_mm2': 120000.0, 'n_verts': 4,
         'allowed_angles': [0, 180],
         'net_polygon': [], 'internal_lines': [], 'notches': [],
         'grain_line': None},
        {'pid': 'g01_30', 'label': 'g01', 'size': 30,
         'polygon': [[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]],
         'bbox': [0.0, 0.0, 500.0, 800.0], 'area_mm2': 400000.0, 'n_verts': 4,
         'allowed_angles': [0, 180],
         'net_polygon': [], 'internal_lines': [], 'notches': [],
         'grain_line': None},
    ]


# Σdemand 基准载荷：g01@28 两份 + g02@28 一份（g01@30 demand=0 不入 manifest）。
_QTY_G01_28_X2 = {'g01': {'28': 2}}
_PLACED_3 = [
    {'id': 'g01_28', 'rotation': 0.0, 'translation': [10.0, 20.0]},
    {'id': 'g01_28', 'rotation': 180.0, 'translation': [600.0, 20.0]},
    {'id': 'g02_28', 'rotation': 0.0, 'translation': [1200.0, 30.0]},
]


def _machine_sid() -> str:
    """合法机器任务 sid（'m'+时间戳+rand8，满足 sessions.SID_RE）。"""
    return 'm' + time.strftime('%Y%m%d%H%M%S') + uuid.uuid4().hex[:8]


def _install_machine_state(tmp_path: Path, *, run_dir=None, rc=None,
                           run_mode='normal', pid=8431,
                           stderr_text='配置错误: master_dxf 不存在 boom\n',
                           quantities=None) -> tuple[str, dict]:
    """直装 machine 内存态（status/stop/result 解析用，不走 solve 全流程）。"""
    sid = _machine_sid()
    stderr_path = tmp_path / 'tmp' / f'machine_err_{sid[:6]}_t.log'
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.write_text(stderr_text, encoding='utf-8')
    st = strategy_mod._states(sid, create=True)
    st.clear()
    st.update({
        'sid': sid, 'state': 'starting', 'proc': FakeProc(pid=pid, rc=rc),
        'pid': pid, 'mode': strategy_mod.MACHINE_MODE,
        'run_mode': run_mode, 'client_ref': None,
        'strategy': None, 'minutes': None,
        'total_budget_sec': machine_mod.RUN_MODE_SPECS[run_mode]['time'],
        'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'started_ts': time.time(), 'run_dir': run_dir, 'snapshot': set(),
        'stderr_path': str(stderr_path), 'doc_id': 'deadbeef01',
        'pieces_snapshot': _synth_pieces(), 'sizes': None, 'per_type': None,
        'quantities': quantities, 'gate_mm': 1750.0, 'seed': 0,
        'cfg_path': 'cfg.json', 'run_name': f'machine_{sid[:6]}_abc123',
        'stopped': False, 'exit_code': None, 'error': None,
    })
    return sid, st


def _write_best_frame(run_dir: Path, seed: int, density: float, *,
                      ext=False, placed=None, frame_index=3) -> None:
    name = f'best_frame_s{seed}{"_ext" if ext else ""}.json'
    (run_dir / name).write_text(json.dumps({
        'seed': seed, 'frame_index': frame_index, 'elapsed': 30.0,
        'phase': 'compression', 'density': density,
        'density_sparrow': density + 0.02, 'width_mm': 7000.0,
        'n_placed': len(placed or []), 'placed_items': placed or [],
    }), encoding='utf-8')


def _write_plain_result(run_dir: Path, *, per_seed=None, incumbent=None,
                        portfolio_mode=None) -> None:
    """plain（normal 档）形态 result.json：portfolio 引擎未激活 → incumbent
    null + per_seed 空（US-002 实测；race/extreme 档可传值覆盖）。"""
    portfolio = {'target': None, 'incumbent': incumbent,
                 'per_seed': per_seed if per_seed is not None else [],
                 'theta_history': [], 'kill_mode': 'off'}
    if portfolio_mode is not None:
        portfolio['mode'] = portfolio_mode
    (run_dir / 'result.json').write_text(json.dumps({
        'config': {'gate_mm': 1750.0, 'time': 180, 'seeds': [0]},
        'solve': [{'seed': 0, 'real_density': 0.5788, 'placed_items': 3}],
        'best': {'seed': 0, 'real_density': 0.5788, 'placed_items': 3},
        'portfolio': portfolio,
    }), encoding='utf-8')


# ------------------------------------------------------------- status


def test_status_normal_running_golden(machine_env):
    """normal 档 running 金标：恰 10 键无 placed_items；incumbent 走 best_frame
    边车回落（plain run portfolio.incumbent 恒 null）+ 运行中 curve 非法 JSON
    在场仍 200（status 绝不读 curve_s*.json）。"""
    run_dir = Path(paths_mod.CONFIG_RUNS_DIR) / 'machine_m2026_abc123_20260921-000000'
    run_dir.mkdir(parents=True)
    _write_best_frame(run_dir, 0, 0.5788, placed=_PLACED_3, frame_index=7)
    # 运行中的 curve 逐帧 append 非合法 JSON —— 在场即证明 status 不读它。
    (run_dir / 'curve_s0.json').write_text(
        '[{"elapsed": 1.0, "density": 0.1', encoding='utf-8')
    sid, st = _install_machine_state(machine_env, run_dir=str(run_dir), rc=None)
    strategy_mod._write_marker(
        {'pid': st['pid'], 'run_dir': None, 'doc_id': 'deadbeef01',
         'mode': strategy_mod.MACHINE_MODE,
         'started_at': st['started_at']}, sid)

    r = TestClient(server_mod.app).get(f'/api/machine/solve/{sid}/status')
    assert r.status_code == 200, r.text
    payload = r.json()
    assert set(payload) == _STATUS_KEYS
    assert payload['state'] == 'running'
    assert payload['mode'] == 'machine'
    assert payload['run_mode'] == 'normal'
    assert payload['total_budget_sec'] == 180          # RUN_MODE_SPECS 烘焙
    assert payload['elapsed_sec'] >= 0.0
    # incumbent = best_frame 边车 density 最大帧四键（无 placed_items 控载荷）。
    assert payload['incumbent'] == {'density': 0.5788, 'width_mm': 7000.0,
                                    'seed': 0, 'frame_index': 7}
    assert payload['current'] == {'seed': 0, 'density': 0.5788, 'ext': False}
    assert payload['per_seed'] == []                    # plain run portfolio 空
    assert payload['error'] is None and payload['exit_code'] is None
    # running 非终态：marker 保留（orphan 恢复面）。
    assert strategy_mod._read_marker(sid) is not None


def test_status_race_mode_golden(machine_env):
    """advanced（race）档状态金标：portfolio.incumbent 优先于 best_frame 边车
    （0.88 > 边车 0.86 证来源）+ done 态推进 + run_mode/total_budget 透传。"""
    run_dir = Path(paths_mod.CONFIG_RUNS_DIR) / 'machine_m2026_race1_20260921-010000'
    run_dir.mkdir(parents=True)
    _write_plain_result(
        run_dir,
        incumbent={'density': 0.88, 'width_mm': 7100.5, 'seed': 0,
                   'frame_index': 5, 'elapsed': 118.0, 'placed_items': _PLACED_3},
        per_seed=[{'seed': 0, 'best_density': 0.88, 'phase': 'race',
                   'killed': False, 'elapsed': 118.0}],
        portfolio_mode='race')
    _write_best_frame(run_dir, 0, 0.86, placed=_PLACED_3, frame_index=4)
    sid, st = _install_machine_state(machine_env, run_dir=str(run_dir), rc=0,
                                     run_mode='advanced')
    payload = TestClient(server_mod.app).get(f'/api/machine/solve/{sid}/status').json()
    assert payload['state'] == 'done' and payload['exit_code'] == 0
    assert payload['run_mode'] == 'advanced'
    assert payload['total_budget_sec'] == 1200
    # incumbent 取 portfolio.incumbent（非边车 0.86）→ 恰四键。
    assert payload['incumbent'] == {'density': 0.88, 'width_mm': 7100.5,
                                    'seed': 0, 'frame_index': 5}
    assert payload['per_seed'] == [{'seed': 0, 'best_density': 0.88,
                                    'phase': 'race', 'killed': False,
                                    'elapsed': 118.0}]
    # done 终态：状态写回内存 + 清 marker（同 strategy 口径）。
    assert st['state'] == 'done'
    assert strategy_mod._read_marker(sid) is None


def test_status_extreme_mode_golden(machine_env):
    """extreme 档状态金标：run_mode='extreme' + total_budget_sec 7200 + done。"""
    run_dir = Path(paths_mod.CONFIG_RUNS_DIR) / 'machine_m2026_ext1_20260921-020000'
    run_dir.mkdir(parents=True)
    _write_plain_result(
        run_dir,
        incumbent={'density': 0.917, 'width_mm': 6900.0, 'seed': 0,
                   'frame_index': 9, 'elapsed': 7000.0, 'placed_items': _PLACED_3},
        per_seed=[{'seed': 0, 'best_density': 0.917, 'killed': False}],
        portfolio_mode='race')       # extreme 默认 race 臂 → portfolio.mode='race'
    sid, st = _install_machine_state(machine_env, run_dir=str(run_dir), rc=0,
                                     run_mode='extreme')
    payload = TestClient(server_mod.app).get(f'/api/machine/solve/{sid}/status').json()
    assert payload['state'] == 'done'
    assert payload['run_mode'] == 'extreme'
    assert payload['total_budget_sec'] == 7200
    assert payload['incumbent']['density'] == 0.917
    assert payload['error'] is None


def test_status_error_state_stderr_tail(machine_env):
    """error 态（进程死 + run_dir 未发现超 30s 宽限）→ error + stderr 尾 +
    exit_code；状态写回 + 清 marker。"""
    sid, st = _install_machine_state(machine_env, run_dir=None, rc=1)
    st['started_ts'] = time.time() - 40.0
    strategy_mod._write_marker(
        {'pid': st['pid'], 'run_dir': None, 'doc_id': 'deadbeef01',
         'mode': strategy_mod.MACHINE_MODE, 'started_at': st['started_at']}, sid)
    payload = TestClient(server_mod.app).get(f'/api/machine/solve/{sid}/status').json()
    assert payload['state'] == 'error'
    assert 'run 目录' in payload['error'] and 'boom' in payload['error']
    assert payload['exit_code'] == 1
    assert payload['incumbent'] is None and payload['current'] is None
    assert st['state'] == 'error'
    assert strategy_mod._read_marker(sid) is None


def test_status_stop_result_task_id_gate(machine_env):
    """task_id 三端点公共闸：格式非法（含 '.'，不满足 SID_RE）→ 400；未知任务 →
    404；外族状态槽（浏览器会话的 strategy run）不冒认 → 404。"""
    c = TestClient(server_mod.app)
    for path, method in (('status', 'get'), ('stop', 'post'), ('result', 'get')):
        r = getattr(c, method)(f'/api/machine/solve/bad.id/{path}')
        assert r.status_code == 400 and 'task_id 非法' in r.json()['error'], path
        r2 = getattr(c, method)(f'/api/machine/solve/{_machine_sid()}/{path}')
        assert r2.status_code == 404 and '未知任务' in r2.json()['error'], path
    # 外族槽：strategy 家族（mode='race'）sid 拿到机器端点也不可读。
    foreign = 'aaaa1111'
    st = strategy_mod._states(foreign, create=True)
    st.update({'sid': foreign, 'state': 'running', 'mode': 'race', 'pid': 1})
    assert c.get(f'/api/machine/solve/{foreign}/status').status_code == 404


def test_solve_then_status_lifecycle_and_evicted_session(machine_env, monkeypatch):
    """solve 全流程状态推进（starting→running→done）+ 轮询刷活性：会话被逐出
    （registry 清空模拟 TTL+宽限过窗）后 status 仍 200（内存态路径不走会话闸门）。"""
    _spawn_capture(monkeypatch, pids=(991,))
    c = TestClient(server_mod.app)
    r = _solve(c, _yl_master_bytes(), {'gate_mm': 1750})
    assert r.status_code == 202
    task_id = r.json()['task_id']
    run_name = r.json()['run_name']
    assert sessions_mod.registry.resolve(task_id).doc_id   # 会话已注册

    # starting → CLI 建 run_dir → 前缀 glob 发现 → running + incumbent（边车回落）。
    run_dir = Path(paths_mod.CONFIG_RUNS_DIR) / f'{run_name}_20260921-030000'
    run_dir.mkdir(parents=True)
    _write_best_frame(run_dir, 0, 0.4233, placed=_PLACED_3, frame_index=2)
    payload = c.get(f'/api/machine/solve/{task_id}/status').json()
    assert payload['state'] == 'running'
    assert payload['incumbent']['density'] == 0.4233
    assert strategy_mod._STRATEGY_STATES[task_id]['run_dir'] == str(run_dir)

    # 会话被逐出（无人轮询超 TTL+宽限）→ status 仍 200（内存态路径）。
    sessions_mod.registry.reset()
    payload2 = c.get(f'/api/machine/solve/{task_id}/status')
    assert payload2.status_code == 200
    assert payload2.json()['state'] == 'running'
    assert payload2.json()['run_mode'] == 'normal'

    # 进程自然结束 + result.json → done（解析态写回内存态）。
    strategy_mod._STRATEGY_STATES[task_id]['proc'] = FakeProc(pid=991, rc=0)
    _write_plain_result(run_dir)
    payload3 = c.get(f'/api/machine/solve/{task_id}/status').json()
    assert payload3['state'] == 'done' and payload3['exit_code'] == 0


def test_status_orphan_paths(machine_env, monkeypatch):
    """orphan（内存态空 + marker 在，模拟 MS 重启）：pid 存活 → orphan 可 stop；
    pid 死 + 超 30s 宽限 → error；run_mode/total_budget 经 machine_cfg 反查恢复。"""
    sid = _machine_sid()
    marker = {'pid': 777, 'run_dir': None, 'doc_id': 'x',
              'mode': strategy_mod.MACHINE_MODE,
              'started_at': time.strftime('%Y-%m-%dT%H:%M:%S')}
    c = TestClient(server_mod.app)

    # pid 存活 → orphan + 附加 alive/pid 诊断键；cfg 反查恢复 extreme 档。
    monkeypatch.setattr(strategy_mod, '_pid_alive', lambda pid: True)
    strategy_mod._write_marker(marker, sid)
    (machine_env / 'uploads' / f'machine_cfg_{sid}_20260921-000000.json').write_text(
        json.dumps({'gate_mm': 1750.0, 'time': 7200, 'seeds': [0],
                    'master_dxf': 'x.dxf'}), encoding='utf-8')
    payload = c.get(f'/api/machine/solve/{sid}/status').json()
    assert payload['state'] == 'orphan'
    assert payload['alive'] is True and payload['pid'] == 777
    assert payload['run_mode'] == 'extreme'           # cfg time 反查 RUN_MODE_SPECS
    assert payload['total_budget_sec'] == 7200
    # orphan 可 stop（pid 存活 → 树杀路径 + 清 marker）。
    r = c.post(f'/api/machine/solve/{sid}/stop')
    assert r.status_code == 200 and r.json() == {'stopped': True, 'pid': 777,
                                                 'orphan': True}
    assert strategy_mod._read_marker(sid) is None

    # pid 死 + 超 30s 宽限 → error（elapsed 由 marker.started_at 推出）。
    sid2 = _machine_sid()
    strategy_mod._write_marker({**marker, 'pid': 778,
                                'started_at': '2020-01-01T00:00:00'}, sid2)
    monkeypatch.setattr(strategy_mod, '_pid_alive', lambda pid: False)
    payload2 = c.get(f'/api/machine/solve/{sid2}/status').json()
    assert payload2['state'] == 'error'
    assert '宽限' in payload2['error'] and '778' in payload2['error']
    assert payload2['run_mode'] is None               # 无 cfg 可反查 → 降级 None


# ------------------------------------------------------------- stop / result


def test_stop_tree_kill_and_result_after_stop(machine_env, monkeypatch):
    """stop：Windows taskkill /PID /T /F 树杀 + run_dir 保留；stopped 后
    result 仍可读（best_frame 边车 density 最大回落）。"""
    run_dir = Path(paths_mod.CONFIG_RUNS_DIR) / 'machine_m2026_stop1_20260921-040000'
    run_dir.mkdir(parents=True)
    _write_best_frame(run_dir, 0, 0.5, placed=_PLACED_3[:2])
    _write_best_frame(run_dir, 1, 0.62, placed=_PLACED_3)   # 最大者
    sid, st = _install_machine_state(machine_env, run_dir=str(run_dir), rc=None,
                                     quantities=_QTY_G01_28_X2)
    strategy_mod._write_marker(
        {'pid': st['pid'], 'run_dir': str(run_dir), 'doc_id': 'deadbeef01',
         'mode': strategy_mod.MACHINE_MODE, 'started_at': st['started_at']}, sid)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))

    monkeypatch.setattr(strategy_mod.subprocess, 'run', fake_run)
    c = TestClient(server_mod.app)
    r = c.post(f'/api/machine/solve/{sid}/stop')
    assert r.status_code == 200
    assert r.json() == {'stopped': True, 'pid': st['pid']}
    if sys.platform == 'win32':
        assert calls == [['taskkill', '/PID', str(st['pid']), '/T', '/F']]
    assert st['state'] == 'stopped'
    assert strategy_mod._read_marker(sid) is None
    assert run_dir.is_dir()                            # run_dir 保留

    # stopped 后 status 稳定 + result 仍可读：无 result.json → best_frame 回落。
    assert c.get(f'/api/machine/solve/{sid}/status').json()['state'] == 'stopped'
    r2 = c.get(f'/api/machine/solve/{sid}/result')
    assert r2.status_code == 200
    best = r2.json()['best']
    assert best['seed'] == 1 and best['density'] == 0.62
    assert best['density_sparrow'] == 0.64             # 边车同帧补 erode 参考口径


def test_result_done_manifest_and_multi_copy(machine_env):
    """done（plain normal 档）result：{manifest, best, summary} 恰三键；manifest
    .pieces 键集含 raw_polygon/d_mm/demand/color；demand>1 的 g 码 placed_items
    发 N 条绝不按 pid 去重（Σdemand 守恒）。"""
    run_dir = Path(paths_mod.CONFIG_RUNS_DIR) / 'machine_m2026_res1_20260921-050000'
    run_dir.mkdir(parents=True)
    _write_plain_result(run_dir)     # plain：portfolio.incumbent null → 边车回落
    _write_best_frame(run_dir, 0, 0.5788, placed=_PLACED_3, frame_index=7)
    sid, st = _install_machine_state(machine_env, run_dir=str(run_dir), rc=0,
                                     quantities=_QTY_G01_28_X2)

    c = TestClient(server_mod.app)
    assert c.get(f'/api/machine/solve/{sid}/status').json()['state'] == 'done'
    r = c.get(f'/api/machine/solve/{sid}/result')
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {'manifest', 'best', 'summary'}

    manifest = body['manifest']
    assert manifest['gate_mm'] == 1750.0
    by_pid = {p['id']: p for p in manifest['pieces']}
    assert set(by_pid) == {'g01_28', 'g02_28'}         # g01_30 demand=0 不入
    for piece in manifest['pieces']:
        assert {'id', 'size', 'color', 'area_mm2', 'polygon', 'raw_polygon',
                'd_mm', 'label', 'demand'} <= set(piece)
    assert by_pid['g01_28']['demand'] == 2 and by_pid['g02_28']['demand'] == 1
    assert by_pid['g01_28']['color'] is not None       # 尺码配色单一真相源

    # best：plain 档 portfolio.incumbent null → best_frame 边车 density 最大回落；
    # placed_items 条数 = Σdemand（g01_28×2 + g02_28×1），绝不按 pid 去重。
    best = body['best']
    assert best['density'] == 0.5788 and best['seed'] == 0
    assert [it['id'] for it in best['placed_items']] == [
        'g01_28', 'g01_28', 'g02_28']
    assert len(best['placed_items']) == 3              # = Σdemand
    # summary：plain run portfolio 段空 → per_seed [] + mode None。
    assert body['summary'] == {'per_seed': [], 'mode': None}


def test_result_rejects_running_and_terminal_stop_400(machine_env):
    """running → result 409（尚未结束）；终态任务 stop → 400（无在飞）。"""
    run_dir = Path(paths_mod.CONFIG_RUNS_DIR) / 'machine_m2026_rej1_20260921-060000'
    run_dir.mkdir(parents=True)
    _write_best_frame(run_dir, 0, 0.5, placed=_PLACED_3)
    sid, st = _install_machine_state(machine_env, run_dir=str(run_dir), rc=None)
    c = TestClient(server_mod.app)
    r = c.get(f'/api/machine/solve/{sid}/result')
    assert r.status_code == 409 and '尚未结束' in r.json()['error']

    # 推进到 done（进程死 + result.json 在场）→ result 可读；stop 无在飞 → 400。
    strategy_mod._STRATEGY_STATES[sid]['proc'] = FakeProc(pid=st['pid'], rc=0)
    _write_plain_result(run_dir)
    assert c.get(f'/api/machine/solve/{sid}/status').json()['state'] == 'done'
    assert c.get(f'/api/machine/solve/{sid}/result').status_code == 200
    r2 = c.post(f'/api/machine/solve/{sid}/stop')
    assert r2.status_code == 400 and '没有进行中的机器排料任务' in r2.json()['error']


# ============================================================= US-004 export

from datetime import datetime as _dtmod_datetime  # noqa: E402（US-004 段内就近）

from materialsorting.web import plt_table as plt_table_mod  # noqa: E402
from materialsorting.web.export import (  # noqa: E402
    build_info_table,
    parse_table_payload,
    placed_to_world,
    write_marker_plt,
)


class _FrozenDT:
    """绘图时间冻结替身（build_info_table 的 ``datetime.now()`` 单一取用点 ——
    逐字节金标跨分钟边界确定性）。"""

    @staticmethod
    def now(tz=None):
        return _dtmod_datetime(2026, 9, 21, 12, 34)


def _synth_doc() -> dict:
    """run_dir pieces_intermediate.json 载荷（schema v2，synth 3 片全量）。"""
    return {'source': 'nest.dxf', 'gate_mm': 1750.0, 'pieces': _synth_pieces()}


def _pid_map() -> dict:
    return {p['pid']: p for p in _synth_pieces()}


def _expected_plt(placed, table_raw=None, *, clean=True, density=0.5788,
                  width_mm=7000.0, gate_mm=1750.0):
    """与端点同源的门面直算金标 → ``(bytes, world, info_table)``（对拍单一真相源）。"""
    world = placed_to_world(placed, _pid_map())
    table_in = parse_table_payload(table_raw if table_raw is not None else {})
    info = build_info_table(world, width_mm=width_mm, gate_mm=gate_mm,
                            density=density, table_in=table_in)
    data = write_marker_plt(world, width_mm=width_mm, gate_mm=gate_mm,
                            title='golden', info_table=info, clean=clean)
    return data, world, info


def _export_setup(machine_env, monkeypatch, *, with_intermediate=True,
                  incumbent=None, quantities=None):
    """US-004 导出测试基座：done 任务（plain 档边车回落形态）+ run_dir 三产物 +
    会话注册 + 绘图时间冻结 → ``(client, sid, run_dir, st)``。"""
    monkeypatch.setattr(plt_table_mod, 'datetime', _FrozenDT)
    run_dir = (Path(paths_mod.CONFIG_RUNS_DIR)
               / f'machine_m2026_exp1_{uuid.uuid4().hex[:8]}')
    run_dir.mkdir(parents=True)
    _write_plain_result(run_dir, incumbent=incumbent)
    _write_best_frame(run_dir, 0, 0.5788, placed=_PLACED_3, frame_index=7)
    if with_intermediate:
        (run_dir / 'pieces_intermediate.json').write_text(
            json.dumps(_synth_doc()), encoding='utf-8')
    sid, st = _install_machine_state(machine_env, run_dir=str(run_dir), rc=0,
                                     quantities=quantities)
    sess = sessions_mod.registry.resolve(sid, create=True)
    sess.state = runtime_mod._state_from_doc(_synth_doc())
    return TestClient(server_mod.app), sid, run_dir, st


def test_export_default_golden_and_session_evicted_identical(
        machine_env, monkeypatch):
    """默认档金标 + 会话过期对拍：done 任务 POST {task_id} → 200 PLT（plt-clean
    毛版+表格）与门面直算逐字节一致；registry 显式逐出后仍 200 且逐字节一致
    （pieces 直载 run_dir intermediate 路径，与 run 存活期导出对拍）。"""
    c, sid, run_dir, st = _export_setup(machine_env, monkeypatch)

    r1 = c.post('/api/machine/export', json={'task_id': sid})
    assert r1.status_code == 200, r1.text
    assert r1.headers['content-type'].startswith('application/plt')
    cd = r1.headers['content-disposition']
    # 中文/ASCII 双写（/export 约定）：run_name 前缀 + all（无 sizes）+ 毛版后缀。
    assert f'filename="machine_{sid[:6]}_' in cd
    assert '_all_57.88pct_seed0_clean.plt' in cd
    assert "filename*=UTF-8''" in cd and quote('毛版') in cd

    # 默认档金标：端点输出 == 门面直算（表格区在场 = info_table 非 None 路径）。
    expected, _world, info = _expected_plt(_PLACED_3)
    assert r1.content == expected
    # 6 手输字段默认值 + 8 项自动计算字段全算非空（plt_table 既有管线的产物）。
    assert (info.bed_no, info.warp_shrink, info.weft_shrink, info.planner,
            info.style_no, info.remark) == ('A料', '0.0%', '0.0%', '', 'noname', '')
    assert info.plan_name == '(28)=1套' and info.sets_count == 1.0
    assert info.utilization_pct == pytest.approx(57.88)
    assert info.gate_m == pytest.approx(1.75)
    assert info.fabric_len_m == pytest.approx(7.0)
    assert info.per_set_m == pytest.approx(7.0)
    assert info.total_pieces == 3
    assert info.draw_time_str == '2026-09-21 12:34'    # 冻结替身生效证明
    # 表格区确在字节流里（info_table=None 的无表格版 != 默认档）。
    bare = write_marker_plt(placed_to_world(_PLACED_3, _pid_map()),
                            width_mm=7000.0, gate_mm=1750.0, title='golden',
                            info_table=None, clean=True)
    assert r1.content != bare

    # 会话被逐出（模拟 TTL+宽限过窗）→ 仍 200 且逐字节一致。
    sessions_mod.registry.reset()
    assert sessions_mod.registry.peek(sid) is None
    r2 = c.post('/api/machine/export', json={'task_id': sid})
    assert r2.status_code == 200, r2.text
    assert r2.content == r1.content


def test_export_fmt_plt_full_and_explicit_table(machine_env, monkeypatch):
    """fmt='plt' 全量版（clean=False + 表格在场）对拍；显式 table 合法值经
    parse_table_payload 对拍；非法 table → 400 中文。"""
    c, sid, run_dir, st = _export_setup(machine_env, monkeypatch)

    r_full = c.post('/api/machine/export', json={'task_id': sid, 'fmt': 'plt'})
    assert r_full.status_code == 200
    expected_full, _, _ = _expected_plt(_PLACED_3, clean=False)
    assert r_full.content == expected_full
    assert '_clean' not in r_full.headers['content-disposition']
    r_clean = c.post('/api/machine/export', json={'task_id': sid})
    assert r_full.content != r_clean.content    # 毛版/全量两版式确不同

    table = {'bed_no': 'B料', 'planner': '小王', 'warp_shrink': '1.5%'}
    r_t = c.post('/api/machine/export',
                 json={'task_id': sid, 'table': table})
    assert r_t.status_code == 200
    expected_t, _, info_t = _expected_plt(_PLACED_3, table_raw=table)
    assert r_t.content == expected_t
    assert info_t.bed_no == 'B料' and info_t.planner == '小王'
    assert info_t.warp_shrink == '1.5%'

    # 非法 table（非对象 / 字段类型错）→ 400 中文（parse_table_payload 透传）。
    r_bad = c.post('/api/machine/export',
                   json={'task_id': sid, 'table': 'x'})
    assert r_bad.status_code == 400 and '信息表格' in r_bad.json()['error']
    r_bad2 = c.post('/api/machine/export',
                    json={'task_id': sid, 'table': {'bed_no': ['x']}})
    assert r_bad2.status_code == 400 and 'bed_no' in r_bad2.json()['error']


def test_export_placed_explicit_variants(machine_env, monkeypatch):
    """placed 显式传入：合法子集对拍（片数随之变）；全未命中 → 400 既有兜底；
    非法形状（非列表/元素非对象）→ 400。"""
    c, sid, run_dir, st = _export_setup(machine_env, monkeypatch)

    placed2 = _PLACED_3[:2]                      # g01_28 ×2（g02_28 不出）
    r = c.post('/api/machine/export', json={'task_id': sid, 'placed': placed2})
    assert r.status_code == 200, r.text
    expected, _, info = _expected_plt(placed2)
    assert r.content == expected
    assert info.total_pieces == 2                # 表格片数字段随 placed 变

    r_miss = c.post('/api/machine/export', json={'task_id': sid, 'placed': [
        {'id': 'zz_99', 'rotation': 0, 'translation': [0.0, 0.0]}]})
    assert r_miss.status_code == 400
    assert '均未匹配' in r_miss.json()['error']
    for bad in ('x', [1], 42):
        r_shape = c.post('/api/machine/export',
                         json={'task_id': sid, 'placed': bad})
        assert r_shape.status_code == 400 and 'placed' in r_shape.json()['error'], bad


def test_export_pieces_fallback_chain(machine_env, monkeypatch):
    """pieces 兜底链：run_dir 无 intermediate → 会话快照 → 状态槽 pieces_snapshot；
    三源全空 → 409（会话逐出 + 快照清空 + intermediate 缺失）。"""
    c, sid, run_dir, st = _export_setup(machine_env, monkeypatch,
                                        with_intermediate=False)
    expected, _, _ = _expected_plt(_PLACED_3)

    # 会话快照兜底（run_dir 无 intermediate）→ 200 且与直载路径逐字节一致。
    r1 = c.post('/api/machine/export', json={'task_id': sid})
    assert r1.status_code == 200, r1.text
    assert r1.content == expected

    # 会话逐出 → 状态槽 start 快照（pieces_snapshot）兜底，仍逐字节一致。
    sessions_mod.registry.reset()
    r2 = c.post('/api/machine/export', json={'task_id': sid})
    assert r2.status_code == 200
    assert r2.content == expected

    # 三源全空 → 409。
    st['pieces_snapshot'] = []
    r3 = c.post('/api/machine/export', json={'task_id': sid})
    assert r3.status_code == 409 and '裁片轮廓' in r3.json()['error']


def test_export_gate_matrix(machine_env, monkeypatch):
    """export 闸矩阵：task_id 非格式 400 / 未知 404 / 外族槽 404；fmt 值域外 400；
    非 JSON body·数组 body·缺 task_id 400；无 run_dir（starting）409；run_dir 无
    布局帧 409。"""
    c, sid, run_dir, st = _export_setup(machine_env, monkeypatch)

    r = c.post('/api/machine/export', json={'task_id': 'bad.id'})
    assert r.status_code == 400 and 'task_id 非法' in r.json()['error']
    r = c.post('/api/machine/export', json={'task_id': _machine_sid()})
    assert r.status_code == 404 and '未知任务' in r.json()['error']
    foreign = 'aaaa1111'
    fst = strategy_mod._states(foreign, create=True)
    fst.update({'sid': foreign, 'state': 'running', 'mode': 'race', 'pid': 1})
    assert c.post('/api/machine/export',
                  json={'task_id': foreign}).status_code == 404

    r = c.post('/api/machine/export', json={'task_id': sid, 'fmt': 'png'})
    assert r.status_code == 400 and 'fmt' in r.json()['error']
    r = c.post('/api/machine/export', content='not-json',
               headers={'Content-Type': 'application/json'})
    assert r.status_code == 400
    r = c.post('/api/machine/export', json=[1, 2])
    assert r.status_code == 400
    r = c.post('/api/machine/export', json={})
    assert r.status_code == 400 and 'task_id' in r.json()['error']

    # starting（进程存活 + run_dir 未发现）→ 409。
    sid2, _st2 = _install_machine_state(machine_env, run_dir=None, rc=None)
    r = c.post('/api/machine/export', json={'task_id': sid2})
    assert r.status_code == 409 and 'run 目录' in r.json()['error']

    # run_dir 在但无任何布局帧（无 result.json incumbent / best_frame）→ 409。
    sid3, _st3 = _install_machine_state(machine_env, run_dir=None, rc=None)
    empty_dir = Path(paths_mod.CONFIG_RUNS_DIR) / f'machine_{sid3[:6]}_empty'
    empty_dir.mkdir(parents=True)
    strategy_mod._STRATEGY_STATES[sid3]['run_dir'] = str(empty_dir)
    r = c.post('/api/machine/export', json={'task_id': sid3})
    assert r.status_code == 409 and '未产出任何布局' in r.json()['error']
