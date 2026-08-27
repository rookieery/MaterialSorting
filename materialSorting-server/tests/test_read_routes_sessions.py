"""US-003（web 多会话）读路由与 WS 接入会话测试。

覆盖（PRD web 多会话 US-003 验收）：
1. ``/api/ptypes`` / ``/api/band-preview`` / ``/api/prefix-preview`` / ``/export``
   按 ``X-Session-Id`` 取各会话快照：A/B 双会话互不串台（各返自己的
   representatives / pieces_by_id），缺省 → default 会话（``_PIECES_STATE`` 回归）；
2. ``/export`` 过期 sid → 401 ``{code:'session_expired'}``（JSON 响应非文件流）、
   未注册合法 sid → 401（不静默重建）、非法 sid → 400；
3. ``GET /`` 响应头 ``Cache-Control: no-cache``；
4. ``/ws/solve`` ``?sid=``：合法 sid 求解全流程（manifest→frames→final）用会话
   快照（manifest pids = 会话裁片）、连接期 ``ws_open==1`` 钉住（时钟超 TTL 扫描
   不逐出）、断开后归零；过期 sid → 带 ``code`` 的 error 帧 + close；超限 error 帧
   契约（帧携 ``session_limit`` code —— 容量闸门在 HTTP 层 POST /api/session 把关，
   白盒锁定帧格式供 US-005 前端统一弹窗消费）；无 sid → default（``_PIECES_STATE``）。

会话快照用直接注入（``registry.resolve(create=True).state = 合成 state``），不走
commit 全管线（US-002 已覆盖落盘链路）；default 注入走 ``_PIECES_STATE`` 原位
clear+update + teardown 恢复（套路同 test_band_preview_api）。单例注册表 autouse
隔离（套路同 tests/test_web_sessions.py）。
"""
from __future__ import annotations

import time

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from materialsorting.web import server as server_mod
from materialsorting.web import sessions
from materialsorting.web.server import app
from materialsorting.web.sessions import _FakeClock

_SID_A = 'sessaaaa'
_SID_B = 'sessbbbb'


# ---------------------------------------------------------------- 合成数据

def _piece(pid, label, size, w, h):
    """合成 v2 schema 裁片（矩形原轮廓，与 test_band_preview_api 同构）。"""
    return {
        'pid': pid, 'label': label, 'size': size,
        'polygon': [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]],
        'bbox': [0.0, 0.0, float(w), float(h)], 'area_mm2': float(w) * float(h),
        'n_verts': 4, 'allowed_angles': [0, 180],
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
    }


def _band_pieces(scale: float = 1.0):
    """g05 两码 60x300 腰片（band 主角）+ g01 大片 + g06 裤耳类；scale 区分 A/B 档。"""
    return [
        _piece('g05_28', 'g05', 28, 60.0 * scale, 300.0 * scale),
        _piece('g05_29', 'g05', 29, 60.0 * scale, 300.0 * scale),
        _piece('g01_28', 'g01', 28, 400.0 * scale, 500.0 * scale),
        _piece('g06_28', 'g06', 28, 30.0 * scale, 559.0 * scale),
    ]


def _prefix_pieces(scale: float = 1.0):
    """g02 前幅 300x350 / g03 后幅 320x330 各两码（2+2 资格）；scale 区分 A/B 档。"""
    return [
        _piece('g02_28', 'g02', 28, 300.0 * scale, 350.0 * scale),
        _piece('g02_29', 'g02', 29, 300.0 * scale, 350.0 * scale),
        _piece('g03_28', 'g03', 28, 320.0 * scale, 330.0 * scale),
        _piece('g03_29', 'g03', 29, 320.0 * scale, 330.0 * scale),
    ]


def _label_reps(pieces):
    """按 /api/ptypes 口径合成 label_representatives（每 label 首片代表）。"""
    reps = {}
    for p in pieces:
        reps.setdefault(p['label'], {
            'label': p['label'], 'polygon': p['polygon'], 'net_polygon': [],
            'internal_lines': [], 'notches': [], 'grain_line': None,
        })
    return reps


def _make_state(pieces, doc_id='synthetic'):
    return {
        'doc': {'doc_id': doc_id, 'label_representatives': _label_reps(pieces)},
        'gate_mm': 1980.0,
        'pieces': pieces,
        'pieces_by_id': {p['pid']: p for p in pieces},
    }


# ---------------------------------------------------------------- fixture

@pytest.fixture(autouse=True)
def _isolated_registry():
    """单例注册表隔离（套路同 tests/test_web_sessions.py）：停扫描 + 前后清零。"""
    reg = sessions.registry
    reg.stop_scanner()
    reg.reset()
    yield reg
    reg.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _inject_session(sid: str, pieces, doc_id='synthetic'):
    """会话快照直接注入（绕过 commit 全管线，US-002 已覆盖落盘链路）。"""
    st = sessions.registry.resolve(sid, create=True)
    st.state = _make_state(pieces, doc_id=doc_id)
    return st


def _inject_default(pieces):
    """default（_PIECES_STATE）原位注入，返回恢复闭包（套路同 test_band_preview_api）。"""
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update(_make_state(pieces, doc_id='defaultdoc'))

    def _restore():
        state.clear()
        state.update(saved)
    return _restore


# ---------------------------------------------------------------- AC1 读路由隔离

def test_ptypes_per_session(client):
    """A/B 双会话：/api/ptypes 各返自己的 representatives（互不串台）。"""
    _inject_session(_SID_A, _band_pieces(scale=1.0), doc_id='docA')
    _inject_session(_SID_B, _band_pieces(scale=1.4), doc_id='docB')
    reps_a = _label_reps(_band_pieces(1.0))
    reps_b = _label_reps(_band_pieces(1.4))

    ra = client.get('/api/ptypes', headers={'X-Session-Id': _SID_A})
    rb = client.get('/api/ptypes', headers={'X-Session-Id': _SID_B})
    assert ra.status_code == 200 and rb.status_code == 200
    assert ra.json()['representatives'] == reps_a        # A 的 RAW 原始坐标代表
    assert rb.json()['representatives'] == reps_b        # B 独立（几何 1.4x）


def test_no_sid_reads_default(client):
    """无 Header → default 会话（_PIECES_STATE）：注入 default 后各读路由吃到同一数据。"""
    restore = _inject_default(_band_pieces(scale=2.0))
    try:
        r = client.get('/api/ptypes')
        assert r.status_code == 200
        assert r.json()['representatives'] == _label_reps(_band_pieces(2.0))
        # export：placed 引用 default 注入的 pid → 200（state 源 = default）
        e = client.post('/export', json={
            'fmt': 'png', 'width_mm': 2000.0, 'density': 0.5, 'seed': 1, 'sizes': [28],
            'placed': [{'id': 'g05_28', 'rotation': 0, 'translation': [100, 100]}],
        })
        assert e.status_code == 200 and e.headers['content-type'].startswith('image/png')
    finally:
        restore()


def test_band_preview_per_session(client):
    """band-preview 按 sid 取 pieces_by_id：A/B 两档几何（1.0x / 1.4x）各自成带。"""
    _inject_session(_SID_A, _band_pieces(scale=1.0), doc_id='docA')
    _inject_session(_SID_B, _band_pieces(scale=1.4), doc_id='docB')
    payload = {'band': {'enabled': True, 'label': 'g05'},
               'quantities': {'g05': {'28': 2, '29': 2}}}

    ra = client.post('/api/band-preview', json=payload, headers={'X-Session-Id': _SID_A}).json()
    rb = client.post('/api/band-preview', json=payload, headers={'X-Session-Id': _SID_B}).json()
    assert ra['ok'] is True and rb['ok'] is True
    assert ra['bbox']['width_mm'] < rb['bbox']['width_mm']     # B 档几何整体 1.4x
    assert ra['bbox']['height_mm'] < rb['bbox']['height_mm']
    assert {m['pid'] for m in ra['members']} == {'g05_28', 'g05_29'}
    # 成员多边形 = 各会话自己的原始轮廓@带内位（单片宽 A 60 / B 84；带内链排不改单片宽）
    def _member_width(data):
        return max(max(x for x, _ in m['polygon']) - min(x for x, _ in m['polygon'])
                   for m in data['members'])
    assert abs(_member_width(ra) - 60.0) < 0.01
    assert abs(_member_width(rb) - 84.0) < 0.01


def test_prefix_preview_per_session(client):
    """prefix-preview 按 sid 取 pieces_by_id：A/B 两档（1.0x / 1.4x）各返自己的组合形态。"""
    _inject_session(_SID_A, _prefix_pieces(scale=1.0), doc_id='docA')
    _inject_session(_SID_B, _prefix_pieces(scale=1.4), doc_id='docB')
    payload = {'prefix': {'enabled': True, 'front': 'g02', 'back': 'g03'},
               'quantities': {'g02': {'28': 2, '29': 2}, 'g03': {'28': 2, '29': 2}}}

    ra = client.post('/api/prefix-preview', json=payload, headers={'X-Session-Id': _SID_A}).json()
    rb = client.post('/api/prefix-preview', json=payload, headers={'X-Session-Id': _SID_B}).json()
    assert ra['ok'] is True and rb['ok'] is True
    assert ra['bbox']['height_mm'] < rb['bbox']['height_mm']   # 竖排组合片整体 1.4x
    for data in (ra, rb):
        pids = [m['pid'] for m in data['members']]
        assert pids.count(f"g02_{data['size']}") == 2
        assert pids.count(f"g03_{data['size']}") == 2


def test_export_per_session(client):
    """export 按 sid 取 pieces_by_id：A 的 placed 匹配 A 的轮廓，B 侧同 pid 不同几何。"""
    _inject_session(_SID_A, _band_pieces(scale=1.0), doc_id='docA')
    _inject_session(_SID_B, _band_pieces(scale=1.4), doc_id='docB')
    body = {'fmt': 'png', 'width_mm': 2000.0, 'density': 0.5, 'seed': 1, 'sizes': [28],
            'placed': [{'id': 'g05_28', 'rotation': 0, 'translation': [100, 100]}]}

    ea = client.post('/export', json=body, headers={'X-Session-Id': _SID_A})
    eb = client.post('/export', json=body, headers={'X-Session-Id': _SID_B})
    assert ea.status_code == 200 and ea.headers['content-type'].startswith('image/png')
    assert eb.status_code == 200 and eb.headers['content-type'].startswith('image/png')
    assert len(ea.content) > 0 and ea.content != eb.content       # 两档渲染不同
    # pid 只存在于会话（default 无此 pid）→ 无 sid 导出 400「均未匹配」
    e0 = client.post('/export', json=body)
    assert e0.status_code == 400
    assert '均未匹配到原始轮廓' in e0.json()['error']


# ---------------------------------------------------------------- AC2 sid 错误分支

def test_export_expired_sid_401_json(client, monkeypatch):
    """过期 sid /export → 401 {code:'session_expired'}（JSON 响应非文件流）。"""
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    _inject_session(_SID_A, _band_pieces(), doc_id='docA')
    clk.advance(sessions.registry.ttl_sec + 1)

    r = client.post('/export', json={
        'fmt': 'png', 'width_mm': 2000.0, 'density': 0.5, 'seed': 1,
        'placed': [{'id': 'g05_28', 'rotation': 0, 'translation': [100, 100]}],
    }, headers={'X-Session-Id': _SID_A})
    assert r.status_code == 401
    assert r.headers['content-type'].startswith('application/json')
    assert r.json()['code'] == 'session_expired'


def test_read_routes_unregistered_and_invalid_sid(client):
    """未注册合法 sid（服务重启丢内存）→ 401 不静默重建；非法 sid → 400。"""
    for path, method in (('/api/ptypes', 'get'), ('/api/band-preview', 'post'),
                         ('/api/prefix-preview', 'post'), ('/export', 'post')):
        kwargs = {'json': {}} if method == 'post' else {}
        r401 = getattr(client, method)(path, **kwargs, headers={'X-Session-Id': 'ghostsid0'})
        assert r401.status_code == 401 and r401.json()['code'] == 'session_expired', path
        r400 = getattr(client, method)(path, **kwargs, headers={'X-Session-Id': 'bad-sid!'})
        assert r400.status_code == 400 and r400.json() == {'error': 'sid 非法'}, path


# ---------------------------------------------------------------- AC3 GET / no-cache

def test_index_no_cache_header(client):
    """GET / 响应头 Cache-Control: no-cache（防部署后旧 bundle 滞留迁移窗口）。"""
    r = client.get('/')
    assert r.status_code == 200
    assert r.headers['cache-control'] == 'no-cache'


# ---------------------------------------------------------------- AC4 WS 会话接入

def _start_payload(time_budget=2, seed=1, sizes=None):
    return {
        'action': 'start', 'sizes': sizes if sizes is not None else [], 'time': time_budget,
        'seed': seed, 'params': {'d_ext': 0, 'd_int': 0, 'tol_ext': 0, 'tol_int': 0},
        'per_type': None, 'quantities': None,
    }


def _wait_ws_open(sid, expected: int, timeout=5.0) -> int:
    """轮询会话 ws_open 至期望值（endpoint finally 与 client 上下文退出有微小时序差）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = sessions.registry.peek(sid)
        v = st.ws_open if st is not None else 0
        if v == expected:
            return v
        time.sleep(0.02)
    st = sessions.registry.peek(sid)
    return st.ws_open if st is not None else 0


def test_ws_valid_sid_full_flow_manifest_frames_final(client):
    """合法 sid 求解全流程：manifest（会话快照 pids）→ frames → final；ws_open 钉住/归零。"""
    _inject_session(_SID_A, _band_pieces(scale=1.0), doc_id='docA')
    final = last_frame = None
    with client.websocket_connect(f'/ws/solve?sid={_SID_A}') as ws:
        ws.send_json(_start_payload(time_budget=2, seed=1, sizes=[28]))
        manifest = ws.receive_json()
        assert manifest['type'] == 'manifest'
        assert {p['id'] for p in manifest['pieces']} == {'g05_28', 'g01_28', 'g06_28'}
        assert manifest['gate_mm'] == 1980.0
        assert sessions.registry.peek(_SID_A).ws_open == 1        # 连接钉住
        deadline = time.time() + 40.0
        while time.time() < deadline:
            m = ws.receive_json()
            if m['type'] == 'frame':
                last_frame = m
            elif m['type'] == 'final':
                final = m
                break
            elif m['type'] == 'error':
                pytest.fail(f'unexpected error: {m}')
    assert final is not None, 'final should arrive within deadline'
    assert last_frame is not None
    assert 'density' in last_frame and 'density_sparrow' in last_frame   # 双口径不变量
    assert _wait_ws_open(_SID_A, 0) == 0                            # 断开归零


def test_ws_no_sid_uses_default_state(client):
    """无 ?sid= → default 会话（_PIECES_STATE）：manifest 反映 default 注入快照。"""
    restore = _inject_default(_band_pieces(scale=1.0))
    try:
        with client.websocket_connect('/ws/solve') as ws:
            ws.send_json(_start_payload(time_budget=60, seed=1, sizes=[28]))
            m = ws.receive_json()
            assert m['type'] == 'manifest'
            assert {p['id'] for p in m['pieces']} == {'g05_28', 'g01_28', 'g06_28'}
            ws.send_json({'action': 'stop'})
            deadline = time.time() + 15.0
            while time.time() < deadline:
                if ws.receive_json().get('type') == 'stopped':
                    break
    finally:
        restore()


def test_ws_expired_sid_error_frame_then_close(client, monkeypatch):
    """过期 sid → {'type':'error','code':'session_expired'} 帧 + close（无 manifest）。"""
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    sessions.registry.resolve(_SID_A, create=True)
    clk.advance(sessions.registry.ttl_sec + 1)

    with client.websocket_connect(f'/ws/solve?sid={_SID_A}') as ws:
        msg = ws.receive_json()
        assert msg['type'] == 'error'
        assert msg['code'] == 'session_expired'
        assert msg['message']
        with pytest.raises((WebSocketDisconnect, Exception)):
            ws.receive_json()                       # error 帧后连接关闭


def test_ws_limit_error_frame_contract(client, monkeypatch):
    """超限 error 帧契约（白盒）：ws_acquire 抛 SessionLimitError → 帧 code=session_limit。

    容量闸门实际由 HTTP 层 POST /api/session（create=True）把关；WS 读路径
    create=False 不自然触达 429 —— 此处锁定帧格式（US-005 前端对任意 code 走
    同一弹窗的契约基础）。
    """
    from materialsorting.web.sessions import SessionLimitError

    def _raise_limit(sid):
        raise SessionLimitError(4)

    monkeypatch.setattr(sessions.registry, 'ws_acquire', _raise_limit)
    with client.websocket_connect(f'/ws/solve?sid={_SID_A}') as ws:
        msg = ws.receive_json()                     # error 帧在 accept 阶段先于任何消息
        assert msg['type'] == 'error'
        assert msg['code'] == 'session_limit'
        assert msg['message']
        with pytest.raises((WebSocketDisconnect, Exception)):
            ws.receive_json()


def test_ws_pinned_session_survives_scan(client, monkeypatch):
    """求解进行中（ws_open>0）不被扫描线程逐出；断开 ws_open 归零后才可被逐出。"""
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    _inject_session(_SID_A, _band_pieces(scale=1.0), doc_id='docA')

    with client.websocket_connect(f'/ws/solve?sid={_SID_A}') as ws:
        ws.send_json(_start_payload(time_budget=60, seed=1, sizes=[28]))
        assert ws.receive_json()['type'] == 'manifest'
        clk.advance(sessions.registry.ttl_sec + 1)          # 空闲远超 TTL
        evicted = sessions.registry.scan_once(clk.now)
        assert _SID_A not in evicted                        # WS 钉住：不逐出
        assert sessions.registry.peek(_SID_A) is not None
        ws.send_json({'action': 'stop'})
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if ws.receive_json().get('type') == 'stopped':
                break

    assert _wait_ws_open(_SID_A, 0) == 0                    # 断开后 ws_open 归零
    assert sessions.registry.scan_once(clk.now) == [_SID_A]  # 此后才可被逐出
