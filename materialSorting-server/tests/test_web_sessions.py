"""US-001 web 会话注册表与生命周期测试（SessionRegistry + POST /api/session）。

覆盖（PRD web 多会话 US-001 验收）：
1. POST /api/session 合法 sid 200 且幂等（重复仅刷 last_active）；
2. 容量闸门：4 活跃 + 第 5 个新 sid → 429 session_limit；default 豁免不占额；
3. TTL（注入 ``_FakeClock``，不依赖真实墙钟）：超时 → 401 session_expired 且不静默
   重建；墓碑 1h 过期 / FIFO 淘汰后该 sid 可正常新建；
4. 扫描：``ws_open==0`` 超时逐出为墓碑、``ws_open>0`` 不逐出；daemon 线程路径冒烟；
5. sid 格式非法 → 400 {error:'sid 非法'}；
6. default 会话 state 与 ``runtime._PIECES_STATE`` 同一 dict 对象（is 锁死）+ 豁免
   上限/过期/墓碑；
7. sessions 模块仅标准库 + 同包依赖、不 import server（分层无环，AST 守卫）。

会话路由不读写磁盘（TTL/墓碑全内存），天然与 out/ 数据隔离，无需 MS_OUT_DIR。
"""
from __future__ import annotations

import ast
import time as time_mod
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from materialsorting.web import runtime as runtime_mod
from materialsorting.web import server as server_mod
from materialsorting.web import sessions
from materialsorting.web.sessions import _FakeClock
from materialsorting.web.server import app


@pytest.fixture(autouse=True)
def _isolated_registry():
    """单例注册表隔离：停 daemon 扫描（防真实线程在 monkeypatch 时钟窗口内并发
    逐出造成 flaky）+ 每测前后清空会话/墓碑。"""
    reg = sessions.registry
    reg.stop_scanner()
    reg.reset()
    yield reg
    reg.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _fake_clock(monkeypatch) -> _FakeClock:
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    return clk


# ---------------------------------------------------------------- AC1 注册 / 幂等

def test_session_register_ok_and_idempotent(client):
    r = client.post('/api/session', headers={'X-Session-Id': 'abc123'})
    assert r.status_code == 200
    assert r.json() == {'ok': True, 'sid': 'abc123'}
    # 幂等：重复 POST 同 sid 仍 200（仅刷活性，不新建条目）
    r2 = client.post('/api/session', headers={'X-Session-Id': 'abc123'})
    assert r2.status_code == 200
    assert r2.json() == {'ok': True, 'sid': 'abc123'}
    assert sessions.registry.active_count == 1


def test_session_register_refreshes_last_active(monkeypatch):
    clk = _fake_clock(monkeypatch)
    reg = sessions.registry
    reg.resolve('sid1aaaa', create=True)
    assert reg.peek('sid1aaaa').last_active == clk.now
    clk.advance(120.0)
    reg.resolve('sid1aaaa')            # 惰性检查通过 + 刷活性
    assert reg.peek('sid1aaaa').last_active == clk.now
    clk.advance(reg.ttl_sec - 1)       # 距上次活性 < TTL → 仍存活
    assert reg.resolve('sid1aaaa').sid == 'sid1aaaa'
    clk.advance(reg.ttl_sec + 1)       # 距上次活性 > TTL → 惰性过期
    with pytest.raises(sessions.SessionExpiredError):
        reg.resolve('sid1aaaa')


def test_session_register_no_header_defaults(client):
    """无 X-Session-Id → default 会话（200；不占 MS_SESSION_MAX 名额）。"""
    r = client.post('/api/session')
    assert r.status_code == 200
    assert r.json() == {'ok': True, 'sid': 'default'}
    assert sessions.registry.active_count == 0


# ---------------------------------------------------------------- AC2 容量闸门

def test_session_limit_fifth_sid_429(client):
    max_n = sessions.registry.max_sessions
    for i in range(max_n):
        r = client.post('/api/session', headers={'X-Session-Id': f'user{i}zz'})
        assert r.status_code == 200, i
    assert sessions.registry.active_count == max_n
    r5 = client.post('/api/session', headers={'X-Session-Id': 'user4zz'})
    assert r5.status_code == 429
    body = r5.json()
    assert body['code'] == 'session_limit'
    assert body['error'] == f'当前使用用户过多（最多 {max_n} 人同时在线），请稍后尝试'
    # default 豁免：满员时无 header 请求仍 200 且不占名额
    rd = client.post('/api/session')
    assert rd.status_code == 200 and rd.json()['sid'] == 'default'
    assert sessions.registry.active_count == max_n
    # 已有会话重复注册不受容量闸门影响（幂等，非新建）
    r0 = client.post('/api/session', headers={'X-Session-Id': 'user0zz'})
    assert r0.status_code == 200


def test_session_limit_slot_freed_after_expiry(client, monkeypatch):
    """会话过期腾出名额后，新 sid 可正常注册。"""
    clk = _fake_clock(monkeypatch)
    reg = sessions.registry
    max_n = reg.max_sessions
    for i in range(max_n):
        client.post('/api/session', headers={'X-Session-Id': f'user{i}zz'})
    r5 = client.post('/api/session', headers={'X-Session-Id': 'user4zz'})
    assert r5.status_code == 429
    clk.advance(reg.ttl_sec + 1)
    with pytest.raises(sessions.SessionExpiredError):
        reg.resolve('user0zz')          # 惰性逐出 user0zz → 腾 1 名额
    r_new = client.post('/api/session', headers={'X-Session-Id': 'user4zz'})
    assert r_new.status_code == 200


# ---------------------------------------------------------------- AC3 TTL / 墓碑

def test_session_expired_401_and_no_silent_rebuild(client, monkeypatch):
    clk = _fake_clock(monkeypatch)
    reg = sessions.registry
    assert client.post(
        '/api/session', headers={'X-Session-Id': 'aaaabbbb'}).status_code == 200
    clk.advance(reg.ttl_sec + 1)
    r = client.post('/api/session', headers={'X-Session-Id': 'aaaabbbb'})
    assert r.status_code == 401
    body = r.json()
    assert body['code'] == 'session_expired'
    assert body['error'] == '会话已过期（10 分钟无操作），请刷新页面'
    # 不静默重建：状态已丢、只留墓碑
    assert reg.peek('aaaabbbb') is None
    assert reg.tombstoned('aaaabbbb')
    assert any(t['sid'] == 'aaaabbbb' for t in reg.tombstones())


def test_tombstone_ttl_expiry_allows_rebuild(monkeypatch):
    """墓碑存活 1h：超龄清除后该 sid 视为全新（可正常新建）。"""
    reg = sessions.registry
    clk = _fake_clock(monkeypatch)
    reg.resolve('aaaabbbb', create=True)
    clk.advance(reg.ttl_sec + 1)
    with pytest.raises(sessions.SessionExpiredError):
        reg.resolve('aaaabbbb')
    assert reg.tombstoned('aaaabbbb')
    clk.advance(reg.tombstone_ttl_sec + 1)      # 墓碑超 1h 龄 → purge
    st = reg.resolve('aaaabbbb', create=True)
    assert st.sid == 'aaaabbbb'
    assert not reg.tombstoned('aaaabbbb')


def test_tombstone_fifo_eviction_allows_rebuild():
    """墓碑 FIFO ≤N：容量淘汰后最旧 sid 可重建，仍在墓碑内的不可。"""
    clk = _FakeClock()
    reg = sessions.SessionRegistry(
        max_sessions=10, ttl_sec=5.0, tombstone_max=2, clock=clk)
    for sid in ('s1aaaaaa', 's2aaaaaa', 's3aaaaaa'):
        reg.resolve(sid, create=True)
    clk.advance(6.0)                            # 全部超时
    for sid in ('s1aaaaaa', 's2aaaaaa', 's3aaaaaa'):
        with pytest.raises(sessions.SessionExpiredError):
            reg.resolve(sid)                    # 惰性逐出 → 逐个落墓碑（FIFO=2）
    assert not reg.tombstoned('s1aaaaaa')       # 最旧被 FIFO 淘汰
    assert reg.tombstoned('s2aaaaaa') and reg.tombstoned('s3aaaaaa')
    assert reg.resolve('s1aaaaaa', create=True).sid == 's1aaaaaa'   # 可重建
    with pytest.raises(sessions.SessionExpiredError):
        reg.resolve('s2aaaaaa', create=True)    # 墓碑仍在 → 401


def test_resolve_unknown_valid_sid_no_create_raises():
    """合法但从未注册的 sid（服务重启丢内存场景）读路径同过期语义 401。"""
    with pytest.raises(sessions.SessionExpiredError):
        sessions.registry.resolve('neverseen')


# ---------------------------------------------------------------- AC4 扫描线程

def test_scan_evicts_idle_but_not_ws_pinned(monkeypatch):
    reg = sessions.registry
    clk = _fake_clock(monkeypatch)
    reg.resolve('idleraaa', create=True)
    reg.resolve('pinnedaa', create=True)
    reg.ws_acquire('pinnedaa')                  # WS 连接钉住
    clk.advance(reg.ttl_sec + 10)
    evicted = reg.scan_once()
    assert evicted == ['idleraaa']              # ws_open==0 的超时会话 → 墓碑
    assert reg.tombstoned('idleraaa')
    st = reg.peek('pinnedaa')
    assert st is not None and st.ws_open == 1   # ws_open>0 不逐出
    reg.ws_release('pinnedaa')
    assert reg.scan_once() == ['pinnedaa']      # 归零后下轮逐出
    assert reg.peek('pinnedaa') is None


def test_ws_acquire_expired_raises_and_release_noop(monkeypatch):
    reg = sessions.registry
    clk = _fake_clock(monkeypatch)
    reg.resolve('goneaaaa', create=True)
    clk.advance(reg.ttl_sec + 1)
    with pytest.raises(sessions.SessionExpiredError):
        reg.ws_acquire('goneaaaa')              # 过期 sid 钉不住（401 语义）
    reg.ws_release('goneaaaa')                  # 已不在 → no-op 不抛
    reg.ws_release('unknownsid')                # 从未存在 → no-op 不抛


def test_scanner_thread_evicts_over_interval(monkeypatch):
    """daemon 扫描线程路径冒烟：极短周期 + 假时钟，真实线程在期限内完成逐出。"""
    reg = sessions.registry
    clk = _fake_clock(monkeypatch)
    monkeypatch.setattr(reg, 'scan_interval_sec', 0.02)
    reg.resolve('threadsaa', create=True)
    clk.advance(reg.ttl_sec + 1)
    reg.start_scanner()
    try:
        deadline = time_mod.monotonic() + 5.0
        while time_mod.monotonic() < deadline and reg.peek('threadsaa') is not None:
            time_mod.sleep(0.02)
        assert reg.peek('threadsaa') is None
        assert reg.tombstoned('threadsaa')
    finally:
        reg.stop_scanner()


# ---------------------------------------------------------------- AC5 sid 格式

def test_invalid_sid_400(client):
    for bad in ('bad-sid!', 'a' * 129, 'cafe!x', 'sid with space', 'sid/../../etc'):
        r = client.post('/api/session', headers={'X-Session-Id': bad})
        assert r.status_code == 400, bad
        assert r.json() == {'error': 'sid 非法'}


# ---------------------------------------------------------------- AC6 default 会话

def test_default_session_state_is_runtime_pieces_state():
    """default 会话 state 与 runtime._PIECES_STATE 是同一 dict 对象（is 锁死）——
    runtime clear+update 快照模式下 default 自动跟随 commit reload（US-002 依赖）。"""
    st = sessions.registry.resolve(None)
    assert st.sid == sessions.DEFAULT_SID
    assert st.state is runtime_mod._PIECES_STATE
    assert sessions.registry.resolve('default').state is runtime_mod._PIECES_STATE
    assert server_mod._PIECES_STATE is runtime_mod._PIECES_STATE   # re-export 同对象


def test_default_exempt_from_ttl_limit_and_tombstone(monkeypatch):
    reg = sessions.registry
    clk = _fake_clock(monkeypatch)
    clk.advance(10_000_000.0)                   # 时钟远超 TTL
    assert reg.scan_once() == []                # default 永不被扫描逐出
    assert reg.resolve(None).sid == 'default'
    assert reg.active_count == 0                # default 不占 MS_SESSION_MAX 名额
    assert reg.tombstones() == []               # default 不参与墓碑


# ---------------------------------------------------------------- 分层纯度（AST 守卫）

def test_sessions_module_layering_purity():
    """sessions 仅标准库 + 同包 runtime，禁 import server（server → sessions 单向无环；
    套路同 test_waist_band.test_module_layering_purity）。"""
    src = Path(sessions.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'os', 're', 'sys', 'threading', 'time',
               'collections', 'dataclasses', 'typing', 'materialsorting'}
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert not mod.startswith('materialsorting.web.server'), \
                'sessions 禁 import server（依赖方向 server → sessions）'
            if node.level:                      # 相对 import 解析到本包兄弟（runtime）
                names = {'materialsorting'}
            else:
                names = {mod.split('.')[0]}
        else:
            continue
        assert names <= allowed, sorted(names - allowed)
    # 源级哨兵：任何 server 引用（含函数内延迟 import）都不允许
    assert 'materialsorting.web.server' not in src
    assert 'from .server' not in src and 'from ..web' not in src
