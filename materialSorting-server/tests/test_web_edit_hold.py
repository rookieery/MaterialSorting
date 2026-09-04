"""编辑排料会话钉住（web/edit_hold + POST /api/edit-hold）测试（2026-09-04）。

背景：编辑排料纯前端无请求，``MS_SESSION_TTL_SEC``（缺省 600s）空闲过期会在长编辑
中途逐出会话 → 保存后导出 401 全丢。edit_hold 提供滚动钉住（缺省
``MS_EDIT_HOLD_SEC`` 2h，镜像策略 run 终态宽限）+ alive hook 组合注册。

覆盖：
1. 钉住语义（私有注册表 + FakeClock）：refresh 后 TTL 远超（30min）不逐出；
   hold 过期后照旧逐出走墓碑；
2. ``install`` 组合：既有 hook（strategy run 钉住模拟）+ 编辑钉住并存 —— 任一豁免
   即钉住 / 都无豁免照逐出 / 都给出取 max；幂等（重复 install 不二次包装）；
3. refresh 清扫过期条目（不泄漏）+ default 永不钉；
4. 路由：合法 sid 200 + 钉住生效（30min 扫描存活）；无 sid（default）200 no-op；
   过期 sid 401 ``{code:'session_expired'}``（不给死会话续命）；非法 sid 400；
5. server 接线哨兵：单例 hook 已被组合（install 在 strategy 注册之后 —— 顺序反了
   编辑豁免会被覆写丢失）；
6. edit_hold 仅依赖同包 sessions，禁 import server/cli（分层无环，AST 守卫）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from materialsorting.web import edit_hold, sessions, strategy as strategy_mod
from materialsorting.web.sessions import _FakeClock
from materialsorting.web.server import app


@pytest.fixture(autouse=True)
def _isolated():
    """单例注册表 + 钉住表隔离：停 daemon 扫描 + 每测前后清空（套路同
    test_web_sessions；``_HOLDS`` 模块级单表非会话状态，须一并清）。"""
    reg = sessions.registry
    reg.stop_scanner()
    reg.reset()
    edit_hold._HOLDS.clear()
    yield reg
    edit_hold._HOLDS.clear()
    reg.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _fake_clock(monkeypatch) -> _FakeClock:
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    return clk


def _private_registry(clk: _FakeClock) -> sessions.SessionRegistry:
    """隔离的私有注册表（不动单例与其生产组合 hook，测试完即弃）。"""
    return sessions.SessionRegistry(ttl_sec=5.0, tombstone_ttl_sec=3600.0, clock=clk)


# ---------------------------------------------------------------- 钉住语义

def test_refresh_pins_session_beyond_ttl(monkeypatch):
    """refresh 后 TTL 远超（30min = 版师长编辑场景）→ 惰性/扫描两路径都不逐出。"""
    monkeypatch.setattr(edit_hold, '_installed', False)   # 私有表上独立接线
    clk = _FakeClock()
    reg = _private_registry(clk)
    reg.resolve('editaaaa', create=True)
    edit_hold.install(reg)
    edit_hold.refresh('editaaaa', clk.now)
    clk.advance(30 * 60.0)
    assert reg.scan_once() == []                       # 扫描路径：超 TTL 但被钉住
    assert reg.peek('editaaaa') is not None
    assert reg.resolve('editaaaa').sid == 'editaaaa'   # 惰性路径同豁免


def test_hold_expiry_evicts_with_tombstone(monkeypatch):
    """hold 过期（> MS_EDIT_HOLD_SEC）后照旧逐出走墓碑（钉住不改变过期本质），
    且同测其他无钉 sid 正常逐出（钉住是 per-sid 的）。"""
    monkeypatch.setattr(edit_hold, '_installed', False)
    monkeypatch.setattr(edit_hold, 'EDIT_HOLD_SEC', 100.0)
    clk = _FakeClock()
    reg = _private_registry(clk)
    reg.resolve('editbbbb', create=True)
    reg.resolve('plainccc', create=True)
    edit_hold.install(reg)
    edit_hold.refresh('editbbbb', clk.now)
    clk.advance(reg.ttl_sec + 10)
    assert reg.scan_once() == ['plainccc']             # 窗内：钉住活、无钉逐出
    clk.advance(100.0)                                 # 越过 hold_until
    assert reg.scan_once() == ['editbbbb']
    assert reg.tombstoned('editbbbb')


def test_refresh_prunes_stale_entries():
    """refresh 顺带清扫过期条目：逐出/关窗后的残留不泄漏（表有界）。"""
    clk = _FakeClock()
    edit_hold.refresh('goneaaaa', clk.now)
    clk.advance(edit_hold.EDIT_HOLD_SEC + 1)
    edit_hold.refresh('livebbbb', clk.now)             # 清扫时机 = 任意下次 refresh
    assert edit_hold.hold_until('goneaaaa') is None
    assert edit_hold.hold_until('livebbbb') == pytest.approx(clk.now + edit_hold.EDIT_HOLD_SEC)


def test_hook_default_sid_returns_none():
    """default 会话豁免一切永不被问，hook 防御性返 None（不进钉住表）。"""
    assert edit_hold._edit_hold_hook(sessions.DEFAULT_SID) is None


# ---------------------------------------------------------------- install 组合

def test_install_composes_with_existing_hook(monkeypatch):
    """组合语义：既有 hook（strategy run 钉住模拟）与编辑钉住并存 —— 任一豁免即
    钉住、都无豁免照逐出、都给出取 max（past + future → future 仍钉住）。"""
    monkeypatch.setattr(edit_hold, '_installed', False)
    clk = _FakeClock()
    reg = _private_registry(clk)
    reg.resolve('run1dddd', create=True)     # 仅「run」豁免（strategy 模拟）
    reg.resolve('edit1eee', create=True)     # 仅编辑豁免
    reg.resolve('both1fff', create=True)     # 双豁免（strategy 侧已过期窗 + 编辑未来窗）
    reg.resolve('none1ggg', create=True)     # 无豁免
    run_hold = clk.now + 50.0                # 固定时间戳（闭包捕获；滚动式永不失效）
    reg.register_alive_hook(
        lambda sid: {'run1dddd': run_hold,
                     'both1fff': clk.now - 1.0}.get(sid))
    edit_hold.install(reg)
    edit_hold.refresh('edit1eee', clk.now)
    edit_hold.refresh('both1fff', clk.now)
    clk.advance(reg.ttl_sec + 10)
    assert reg.scan_once() == ['none1ggg']   # 前三者钉住（edit1eee/both1fff 经编辑源）
    assert reg.peek('run1dddd') is not None  # run1dddd 经既有 hook 源（委托保留）
    clk.advance(60.0)                         # run 短窗过期；edit 窗（EDIT_HOLD_SEC）仍在
    assert reg.scan_once() == ['run1dddd']
    assert reg.peek('both1fff') is not None  # max 语义：编辑未来窗接管


def test_install_idempotent(monkeypatch):
    """重复 install 不二次包装（幂等哨兵置位）。"""
    monkeypatch.setattr(edit_hold, '_installed', False)
    clk = _FakeClock()
    reg = _private_registry(clk)
    reg.register_alive_hook(lambda sid: None)
    edit_hold.install(reg)
    hook_after = reg._alive_hook
    edit_hold.install(reg)
    assert reg._alive_hook is hook_after


# ---------------------------------------------------------------- 路由

def test_edit_hold_route_pins_session(client, monkeypatch):
    """/api/edit-hold 200 后 30min 扫描存活 —— 端到端：路由续期 → 单例组合 hook
    豁免（server 接线真实生效，非仅私有表行为）。"""
    clk = _fake_clock(monkeypatch)
    sid = 'holdddddd'
    assert client.post('/api/session', headers={'X-Session-Id': sid}).status_code == 200
    r = client.post('/api/edit-hold', headers={'X-Session-Id': sid})
    assert r.status_code == 200 and r.json() == {'ok': True}
    assert edit_hold.hold_until(sid) == pytest.approx(clk.now + edit_hold.EDIT_HOLD_SEC)
    clk.advance(30 * 60.0)
    assert sessions.registry.scan_once() == []
    assert sessions.registry.peek(sid) is not None


def test_edit_hold_route_default_noop(client):
    """无 sid（default 会话）→ 200 no-op：default 豁免一切过期，不进钉住表。"""
    r = client.post('/api/edit-hold')
    assert r.status_code == 200 and r.json() == {'ok': True}
    assert edit_hold.hold_until(sessions.DEFAULT_SID) is None


def test_edit_hold_route_expired_sid_401(client, monkeypatch):
    """过期 sid → 401 {code:'session_expired'}：resolve 闸门先行，不给死会话续命。"""
    clk = _fake_clock(monkeypatch)
    sid = 'deadeeeeee'
    client.post('/api/session', headers={'X-Session-Id': sid})
    clk.advance(sessions.registry.ttl_sec + 1)
    r = client.post('/api/edit-hold', headers={'X-Session-Id': sid})
    assert r.status_code == 401
    assert r.json() == {'code': 'session_expired', 'error': r.json()['error']}
    assert edit_hold.hold_until(sid) is None


def test_edit_hold_route_invalid_sid_400(client):
    r = client.post('/api/edit-hold', headers={'X-Session-Id': 'bad-sid!'})
    assert r.status_code == 400
    assert r.json() == {'error': 'sid 非法'}


def test_singleton_hook_is_composed():
    """server 接线哨兵：单例 hook 已被 install 组合（≠ strategy 原始 hook）——
    install 若早于 strategy 注册会被覆写丢编辑豁免，本测锁死文件尾顺序。"""
    assert sessions.registry._alive_hook is not strategy_mod._run_alive_hook


# ---------------------------------------------------------------- 分层纯度（AST 守卫）

def test_edit_hold_module_layering_purity():
    """edit_hold 仅标准库 + 同包 sessions，禁 import server / cli（套路同
    test_web_sessions.test_sessions_module_layering_purity）。"""
    src = Path(edit_hold.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'typing', 'materialsorting'}
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert not mod.startswith('materialsorting.web.server'), \
                'edit_hold 禁 import server（依赖方向 server → edit_hold）'
            assert not mod.startswith('materialsorting.cli'), \
                'edit_hold 禁 import cli（web 禁反向依赖上层）'
            if node.level:                      # 相对 import 解析到本包兄弟（sessions）
                names = {'materialsorting'}
            else:
                names = {mod.split('.')[0]}
        else:
            continue
        assert names <= allowed, sorted(names - allowed)
    # 源级哨兵：任何 server/cli 引用（含函数内延迟 import）都不允许
    assert 'materialsorting.web.server' not in src
    assert 'materialsorting.cli' not in src
    assert 'from .server' not in src
