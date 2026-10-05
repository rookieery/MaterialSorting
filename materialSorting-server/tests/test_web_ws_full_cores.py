"""WS /ws/solve full_cores 满核运行接线测试（2026-10-05 通用配置移入，TestClient）。

镜像 test_web_ws_initial 套路：monkeypatch ``routes_ws.solve_with_callback_proc``
（模块级 from-import 绑定 = 调用点名字）注入伪 proc 收 solve_params 形态，不跑真求解。

覆盖（三路验收口径）：
1. **透传**：``full_cores=true`` → ``solve_params['solver_opts']`` 恰
   ``{'num_workers': max(1, 逻辑核数−1)}``（CLI ``--full-cores`` 同式，
   run_config.py 单一公式镜像）；消息流 manifest → frame → final 不受影响；
2. **严格 bool**：``1`` / ``'on'``（int / 字符串）→ 结构化 error 帧早退 +
   显式 close，不发 manifest、不建求解子进程（与 /api/strategy/start 400 同口径）；
3. **缺省零回归**：无键 / 显式 ``false`` → solve_params **无 ``solver_opts`` 键**
   （与旧前端逐字段一致 —— build_instance 走默认 num_workers=4 路径）。
"""
from __future__ import annotations

import time

import pytest
from starlette.testclient import TestClient

import materialsorting.web.routes_ws as routes_ws_mod
from materialsorting.web import server as server_mod
from materialsorting.web.server import app


# ------------------------------------------------------------- 合成夹具（自足）


def _pieces() -> list[dict]:
    """2 片合成矩形裁片（schema v2 子集，与 test_web_ws_initial 同构）。"""
    return [
        {'pid': 'g01_28', 'label': 'g01', 'size': 28,
         'polygon': [[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]],
         'bbox': [0.0, 0.0, 500.0, 800.0], 'area_mm2': 400000.0, 'n_verts': 4,
         'allowed_angles': [0, 180], 'net_polygon': [], 'internal_lines': [],
         'notches': [], 'grain_line': None},
        {'pid': 'g02_28', 'label': 'g02', 'size': 28,
         'polygon': [[0.0, 0.0], [300.0, 0.0], [300.0, 400.0], [0.0, 400.0]],
         'bbox': [0.0, 0.0, 300.0, 400.0], 'area_mm2': 120000.0, 'n_verts': 4,
         'allowed_angles': [0, 180], 'net_polygon': [], 'internal_lines': [],
         'notches': [], 'grain_line': None},
    ]


_ABSENT = object()


def _start(full_cores=_ABSENT):
    """最小合法 start payload（full_cores 缺席 = 旧前端行为；可显式传 None 验等价）。"""
    payload = {'action': 'start', 'sizes': [], 'time': 60, 'seed': 1,
               'params': None, 'per_type': None, 'quantities': None}
    if full_cores is not _ABSENT:
        payload['full_cores'] = full_cores
    return payload


class _FakeProc:
    """terminate 兼容假 proc（is_alive 恒 False → finally terminate no-op）。"""
    pid = 9999

    def is_alive(self):
        return False

    def terminate(self):
        pass

    def join(self, timeout=None):
        pass

    def kill(self):
        pass


def _install_fake_proc(monkeypatch, calls):
    """伪 solve_with_callback_proc（monkeypatch routes_ws 模块属性 = 调用点生效）。

    同步 on_manifest + 单帧 on_report 后返回 worker 形态 final（density 双键/宽度/
    placed_items）；只收 solve_params 形态，不跑真求解。
    """

    def fake(pieces, gate_mm, solve_params, *, on_manifest=None,
             on_report=None, on_process=None, on_stage=None, band=None,
             prefix=None, initial_solution=None, record_composite=False):
        calls.append({'solve_params': dict(solve_params), 'gate_mm': gate_mm})
        if on_process is not None:
            on_process(_FakeProc())
        if on_manifest is not None:
            on_manifest({'pid_meta': {}, 'total_area': 520000.0,
                         'n_eroded': 0, 'gate_mm': float(gate_mm)})
        if on_report is not None:
            on_report({'type': 'frame', 'elapsed': 0.1, 'phase': 'exploring',
                       'density': 0.5, 'density_sparrow': 0.55,
                       'width_mm': 1100.0, 'placed_items': []})
        final = {'type': 'final', 'density': 0.5, 'density_sparrow': 0.55,
                 'width_mm': 1100.0, 'elapsed': 0.3, 'placed_items': []}
        return object(), final, 0.3, None

    monkeypatch.setattr(routes_ws_mod, 'solve_with_callback_proc', fake)
    return fake


@pytest.fixture
def ws_client():
    """注入合成 pieces state（_PIECES_STATE 是 runtime 单例 dict —— 原位
    clear+update，teardown 恢复真实 state（test_ws_stop 等兄弟用例依赖真实
    intermediate）。"""
    pieces = _pieces()
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update({
        'doc': {'source': 'synthetic_ws_full_cores.dxf'},
        'gate_mm': 1980.0,
        'pieces': pieces,
        'pieces_by_id': {p['pid']: p for p in pieces},
    })
    with TestClient(app) as client:
        yield client
    state.clear()
    state.update(saved)


def _drain_until_final(ws, timeout=10.0):
    """drain 消息直到 final；返回 (final, 全部消息) —— 供无 error 帧断言。"""
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        m = ws.receive_json()
        seen.append(m)
        if m.get('type') == 'final':
            return m, seen
    pytest.fail('final not received within deadline')


# --------------------------------------------------------------- AC#1 透传


def test_full_cores_true_solver_opts(ws_client, monkeypatch):
    """full_cores=true → solve_params['solver_opts'] 恰 {'num_workers': 核数−1}；
    manifest → frame → final 消息流不受影响。"""
    calls: list = []
    _install_fake_proc(monkeypatch, calls)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(full_cores=True))
        _final, seen = _drain_until_final(ws)
    assert len(calls) == 1
    import os
    expect_workers = max(1, (os.cpu_count() or 4) - 1)
    assert calls[0]['solve_params']['solver_opts'] == \
        {'num_workers': expect_workers}
    assert [m['type'] for m in seen] == ['manifest', 'frame', 'final']


# --------------------------------------------------------------- AC#2 严格 bool


@pytest.mark.parametrize('bad', [1, 0, 'on', 'true'])
def test_full_cores_non_bool_rejected(ws_client, monkeypatch, bad):
    """非 bool（int/字符串，含真值形态）→ 结构化 error 帧早退 + 显式 close，
    不发 manifest、不建求解子进程（与 /api/strategy/start 400 同口径）。"""
    calls: list = []
    _install_fake_proc(monkeypatch, calls)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(full_cores=bad))
        m = ws.receive_json()
    assert m['type'] == 'error'
    assert 'full_cores 须为布尔值' in m['message']
    assert calls == []


# --------------------------------------------------------------- AC#3 缺省零回归


@pytest.mark.parametrize('raw', [_ABSENT, False], ids=['absent', 'explicit-false'])
def test_full_cores_absent_no_solver_opts(ws_client, monkeypatch, raw):
    """无键 / 显式 false → solve_params 无 solver_opts 键（与旧前端逐字段一致，
    build_instance 走默认 num_workers=4 路径）。"""
    calls: list = []
    _install_fake_proc(monkeypatch, calls)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(full_cores=raw))
        _drain_until_final(ws)
    assert len(calls) == 1
    assert 'solver_opts' not in calls[0]['solve_params']
    # solve_params 其余六键与旧版逐字段一致（零回归锁）。
    assert set(calls[0]['solve_params']) == {
        'time_budget', 'seed', 'sizes', 'params', 'per_type', 'quantities'}
