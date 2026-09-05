"""POST /api/edit-polish 编辑排料「智能微调」会话族端点测试（prd-edit-polish US-002）。

覆盖（镜像 test_web_edit_hold 套路 + AC 六项）：
1. 200 全链路：default 会话合成 state（可分离重合对夹具，与 test_polish 同构）
   → ok:true、placed 守恒（条数 + pid 多重集 + 逐条下标序）、report 含
   before/after/moves/residual 四段 + 七指标、重合对 1→0（真引擎跑通非 mock）；
2. 401/400 sid 闸门：过期 sid（FakeClock 惰性逐出）→ 401 {code:'session_expired'}、
   非法 sid → 400（结构化 JSON，对齐 /api/edit-hold 用例）；
3. 400 载荷校验：placed 空/缺/非列表、条目形态缺字段、pid 未匹配（「母版已变更？
   请重新求解/上传」）、exclude 非 dict、gate_mm 非法/两处皆无、body 非 JSON 对象；
4. gate_mm 缺省回退会话 state（spy 捕获引擎实参）+ payload 优先；
5. exclude/compact 透传引擎（缺省 None/false）；
6. polish 在 run_in_threadpool 内执行（运行时线程级断言：引擎执行线程 ≠ 事件循环
   线程 + spy 目击调用经 server 命名空间 run_in_threadpool）；
7. sid 会话状态隔离（sid 的 pieces_by_id 与 default 互不串台）+ 成功请求顺手
   edit_hold.refresh（default 不进钉住表，/api/edit-hold 同口径）。

合成数据：g01_30/g02_30 各 200×150 矩形，叠 5mm 且上方有空位（test_polish
AC#2 同构夹具）→ polish 必产出 1 条 separate move，报告前后指标可硬断言。
"""
from __future__ import annotations

import threading
from collections import Counter

import pytest
from starlette.testclient import TestClient

from materialsorting.nesting_engine import polish as polish_mod
from materialsorting.web import edit_hold, server as server_mod, sessions
from materialsorting.web.sessions import _FakeClock
from materialsorting.web.server import app


def _piece(pid, w, h, label=None):
    """合成 schema v2 矩形裁片（test_polish 同构最小字段）。"""
    return {'pid': pid, 'label': label or pid.split('_')[0], 'size': 28,
            'polygon': [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)],
                        [0.0, float(h)]],
            'area_mm2': float(w * h), 'net_polygon': [], 'internal_lines': [],
            'notches': [], 'grain_line': None}


def _pieces():
    """g01_30 / g02_30 各 200×150（可分离重合对主角）。"""
    return [_piece('g01_30', 200, 150), _piece('g02_30', 200, 150, label='g02')]


def _state(gate_mm=1000.0):
    pieces = _pieces()
    return {'doc': {'source': 'synthetic_polish.dxf'}, 'gate_mm': gate_mm,
            'pieces': pieces, 'pieces_by_id': {p['pid']: p for p in pieces}}


def _overlap_placed():
    """叠 5mm 重合对（g02 上叠 g01，上方留空可分离）。"""
    return [
        {'id': 'g01_30', 'rotation': 0.0, 'translation': [100.0, 100.0]},
        {'id': 'g02_30', 'rotation': 0.0, 'translation': [100.0, 245.0]},
    ]


@pytest.fixture(autouse=True)
def _isolated():
    """单例注册表 + 钉住表隔离（套路同 test_web_edit_hold）。"""
    reg = sessions.registry
    reg.stop_scanner()
    reg.reset()
    edit_hold._HOLDS.clear()
    yield reg
    edit_hold._HOLDS.clear()
    reg.reset()


@pytest.fixture
def polish_client():
    """default 会话注入合成 state（原位 clear+update，teardown 恢复真实 state）。"""
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update(_state())
    with TestClient(app) as client:
        yield client
    state.clear()
    state.update(saved)


_REPORT_STUB = {'before': {}, 'after': {}, 'moves': [], 'residual': [],
                'excluded': [], 'elapsed_sec': 0.0}


# ---------------------------------------------------------------- 200 全链路

def test_edit_polish_200_full_chain(polish_client):
    """AC#1：default 会话 state → 200、placed 守恒（条数+pid 多重集+下标序）、
    report 四段齐全、重合对 1→0（真引擎，非 mock）；payload 不带 gate_mm 同时
    验证 state['gate_mm']=1000 回退（守卫 y∈[0,1000] 放行 +y 分离）。"""
    placed_in = _overlap_placed()
    r = polish_client.post('/api/edit-polish', json={'placed': placed_in})
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True

    out = body['placed']
    assert len(out) == len(placed_in) == 2
    assert Counter(p['id'] for p in out) == Counter(p['id'] for p in placed_in)
    assert [p['id'] for p in out] == [p['id'] for p in placed_in]   # 下标序守恒
    for p in out:
        assert set(p) == {'id', 'rotation', 'translation'}
        assert len(p['translation']) == 2

    rep = body['report']
    assert {'before', 'after', 'moves', 'residual'} <= set(rep)
    for seg in ('before', 'after'):
        assert {'overlap_pairs', 'max_penetration_mm', 'total_overlap_area_mm2',
                'rotated_pieces', 'rotation_dev_sum_deg', 'width_mm',
                'density'} <= set(rep[seg])
    assert rep['before']['overlap_pairs'] == 1
    assert rep['after']['overlap_pairs'] == 0
    assert rep['before']['max_penetration_mm'] == 5.0
    assert [m['kind'] for m in rep['moves']] == ['separate']
    assert rep['residual'] == []

    # 位移语义：恰一片被最小分离（沿 y ~5mm；mover 先试 (i,j) 下标序 → g01 −y），
    # 另一片原位逐字段不变
    dy0 = out[0]['translation'][1] - placed_in[0]['translation'][1]
    dy1 = out[1]['translation'][1] - placed_in[1]['translation'][1]
    moved = [d for d in (dy0, dy1) if abs(d) > 1e-6]
    assert len(moved) == 1 and abs(abs(moved[0]) - 5.0) < 0.01
    assert out[0]['rotation'] == 0.0 and out[1]['rotation'] == 0.0


def test_edit_polish_multi_copy_pid_multiset_conserved(polish_client):
    """多副本 pid 多重集守恒：g01×2 + g02×1（demand>1 同 pid 按下标寻址）。"""
    placed_in = _overlap_placed() + [
        {'id': 'g01_30', 'rotation': 0.0, 'translation': [500.0, 500.0]}]
    r = polish_client.post('/api/edit-polish', json={'placed': placed_in})
    assert r.status_code == 200
    out = r.json()['placed']
    assert len(out) == 3
    assert Counter(p['id'] for p in out) == {'g01_30': 2, 'g02_30': 1}


def test_edit_polish_default_no_hold_entry(polish_client):
    """default（无 sid）成功 → 200 但不进钉住表（default 豁免一切，/api/edit-hold
    同口径）；带 sid 成功 → 顺手 edit_hold.refresh 滚动续期。"""
    assert polish_client.post(
        '/api/edit-polish', json={'placed': _overlap_placed()}).status_code == 200
    assert edit_hold.hold_until(sessions.DEFAULT_SID) is None

    sid = 'polish111'
    assert polish_client.post('/api/session',
                              headers={'X-Session-Id': sid}).status_code == 200
    sessions.registry.peek(sid).state.update(_state())     # 会话快照 = 同款合成数据
    r = polish_client.post('/api/edit-polish', headers={'X-Session-Id': sid},
                           json={'placed': _overlap_placed()})
    assert r.status_code == 200
    assert edit_hold.hold_until(sid) == pytest.approx(
        sessions.registry.clock() + edit_hold.EDIT_HOLD_SEC)


def test_edit_polish_sid_state_isolation(polish_client):
    """sid 会话 state 与 default 互不串台：sid 只注册了 sx_30 → default 的
    g01_30 在 sid 下 400「母版已变更」，default（无 sid）下同载荷 200。"""
    sid = 'polish222'
    polish_client.post('/api/session', headers={'X-Session-Id': sid})
    sx = _piece('sx_30', 100, 100)
    sessions.registry.peek(sid).state.update(
        {'gate_mm': 1000.0, 'pieces': [sx], 'pieces_by_id': {'sx_30': sx}})

    r = polish_client.post('/api/edit-polish', headers={'X-Session-Id': sid},
                           json={'placed': _overlap_placed()})
    assert r.status_code == 400
    assert '母版已变更' in r.json()['error']
    assert polish_client.post(
        '/api/edit-polish', json={'placed': _overlap_placed()}).status_code == 200


# ---------------------------------------------------------------- sid 闸门

def test_edit_polish_expired_sid_401(polish_client, monkeypatch):
    """AC#2：过期 sid → 401 {code:'session_expired'}（resolve 闸门先行）。"""
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    sid = 'deadeeee1'
    polish_client.post('/api/session', headers={'X-Session-Id': sid})
    clk.advance(sessions.registry.ttl_sec + 1)
    r = polish_client.post('/api/edit-polish', headers={'X-Session-Id': sid},
                           json={'placed': _overlap_placed()})
    assert r.status_code == 401
    assert r.json()['code'] == 'session_expired'
    assert edit_hold.hold_until(sid) is None      # 失败请求不续期


def test_edit_polish_invalid_sid_400(polish_client):
    """AC#2：非法 sid → 400 {'error':'sid 非法'}（结构化 JSON）。"""
    r = polish_client.post('/api/edit-polish', headers={'X-Session-Id': 'bad-sid!'},
                           json={'placed': _overlap_placed()})
    assert r.status_code == 400
    assert r.json() == {'error': 'sid 非法'}


# ---------------------------------------------------------------- 400 载荷校验

def test_edit_polish_placed_empty_or_missing_400(polish_client):
    """AC#3：placed 空 / 缺 / 非列表 → 400。"""
    for payload in ({'placed': []}, {}, {'placed': 'x'}, {'placed': None}):
        r = polish_client.post('/api/edit-polish', json=payload)
        assert r.status_code == 400, payload
        assert 'placed' in r.json()['error']


def test_edit_polish_pid_unmatched_400(polish_client):
    """AC#3：pid 未匹配会话 pieces_by_id → 400（文案「母版已变更？请重新求解/上传」，
    不做部分降级 —— 全匹配才跑）。"""
    placed = _overlap_placed() + [
        {'id': 'zz_99', 'rotation': 0.0, 'translation': [800.0, 800.0]}]
    r = polish_client.post('/api/edit-polish', json={'placed': placed})
    assert r.status_code == 400
    err = r.json()['error']
    assert 'zz_99' in err and '母版已变更？请重新求解/上传' in err


def test_edit_polish_malformed_item_and_body_400(polish_client):
    """placed 条目缺 id/translation 形态非法、body 非 JSON / 非对象 → 400。"""
    bad_items = [
        {'rotation': 0.0, 'translation': [0, 0]},               # 缺 id
        {'id': 'g01_30', 'rotation': 0.0},                      # 缺 translation
        {'id': 'g01_30', 'rotation': 0.0, 'translation': [1]},  # translation 非 2 元
    ]
    for item in bad_items:
        r = polish_client.post('/api/edit-polish', json={'placed': [item]})
        assert r.status_code == 400, item
        assert '形态' in r.json()['error']

    r = polish_client.post('/api/edit-polish', content=b'not-json',
                           headers={'Content-Type': 'application/json'})
    assert r.status_code == 400
    r = polish_client.post('/api/edit-polish', json=[1, 2])     # 数组非对象
    assert r.status_code == 400
    assert 'JSON 对象' in r.json()['error']


def test_edit_polish_gate_invalid_or_missing_400(polish_client):
    """gate_mm 非法（字符串/NaN）→ 400；payload 与会话 state 均无 → 400 fail-fast；
    payload 显式给值则不依赖 state（同载荷恢复 200）。"""
    r = polish_client.post('/api/edit-polish',
                           json={'placed': _overlap_placed(), 'gate_mm': 'abc'})
    assert r.status_code == 400 and 'gate_mm' in r.json()['error']
    # NaN 走原始 JSON 字面量（httpx json= 序列化拒 NaN；json.loads 默认可解析）
    r = polish_client.post(
        '/api/edit-polish',
        content=b'{"placed": [{"id": "g01_30", "rotation": 0,'
                b' "translation": [100, 100]}], "gate_mm": NaN}',
        headers={'Content-Type': 'application/json'})
    assert r.status_code == 400 and 'gate_mm' in r.json()['error']

    state = server_mod._PIECES_STATE        # default state 即本 dict（fixture 注入）
    state.pop('gate_mm', None)
    r = polish_client.post('/api/edit-polish', json={'placed': _overlap_placed()})
    assert r.status_code == 400 and 'gate_mm' in r.json()['error']
    r = polish_client.post('/api/edit-polish',
                           json={'placed': _overlap_placed(), 'gate_mm': 1000.0})
    assert r.status_code == 200


def test_edit_polish_exclude_not_dict_400(polish_client):
    r = polish_client.post('/api/edit-polish',
                           json={'placed': _overlap_placed(), 'exclude': ['g01']})
    assert r.status_code == 400
    assert 'exclude' in r.json()['error']


# --------------------------------------------- gate 回退 / exclude·compact 透传

def test_edit_polish_gate_fallback_and_payload_priority(polish_client, monkeypatch):
    """AC#4：gate_mm 缺省回退会话 state['gate_mm']；payload 给值则优先（spy 捕获
    引擎实参 —— /export、/api/plt-table-preview 同法口径）。"""
    calls = []

    def fake_polish(placed, pieces_by_id, gate_mm, *, exclude=None, compact=False):
        calls.append(gate_mm)
        return placed, dict(_REPORT_STUB)

    monkeypatch.setattr(polish_mod, 'polish_layout', fake_polish)
    r = polish_client.post('/api/edit-polish', json={'placed': _overlap_placed()})
    assert r.status_code == 200
    assert calls[-1] == 1000.0                       # 回退 state
    r = polish_client.post('/api/edit-polish',
                           json={'placed': _overlap_placed(), 'gate_mm': 800.0})
    assert r.status_code == 200
    assert calls[-1] == 800.0                        # payload 优先


def test_edit_polish_exclude_compact_passthrough(polish_client, monkeypatch):
    """AC#4/US-005 键位：exclude（labels/pids 双键）原样透传引擎、缺省 None；
    compact 缺省 false。"""
    calls = []

    def fake_polish(placed, pieces_by_id, gate_mm, *, exclude=None, compact=False):
        calls.append((exclude, compact))
        return placed, dict(_REPORT_STUB)

    monkeypatch.setattr(polish_mod, 'polish_layout', fake_polish)
    r = polish_client.post('/api/edit-polish',
                           json={'placed': _overlap_placed(),
                                 'exclude': {'labels': ['g01'], 'pids': ['g02_30']}})
    assert r.status_code == 200
    assert calls[-1] == ({'labels': ['g01'], 'pids': ['g02_30']}, False)
    r = polish_client.post('/api/edit-polish',
                           json={'placed': _overlap_placed(), 'compact': True})
    assert r.status_code == 200
    assert calls[-1] == (None, True)
    r = polish_client.post('/api/edit-polish', json={'placed': _overlap_placed()})
    assert r.status_code == 200
    assert calls[-1] == (None, False)


# ---------------------------------------------------------------- 线程池执行

def test_edit_polish_runs_in_threadpool(polish_client, monkeypatch):
    """AC#5：polish 经 run_in_threadpool 执行 —— spy 包装 server 命名空间的
    ``run_in_threadpool``（记录事件循环线程）+ 引擎侧记录执行线程，断言两者非同
    一线程（防阻塞事件循环，prefix-preview 先例同形态）。"""
    threads = {}

    real_run = server_mod.run_in_threadpool

    async def spy_run(func, *args, **kwargs):
        threads['loop'] = threading.current_thread()
        return await real_run(func, *args, **kwargs)

    def fake_polish(placed, pieces_by_id, gate_mm, *, exclude=None, compact=False):
        threads['polish'] = threading.current_thread()
        return placed, dict(_REPORT_STUB)

    monkeypatch.setattr(server_mod, 'run_in_threadpool', spy_run)
    monkeypatch.setattr(polish_mod, 'polish_layout', fake_polish)
    r = polish_client.post('/api/edit-polish', json={'placed': _overlap_placed()})
    assert r.status_code == 200
    assert threads['polish'] is not threads['loop']     # 工作线程 ≠ 事件循环线程
