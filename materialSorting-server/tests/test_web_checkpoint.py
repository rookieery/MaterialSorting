"""POST/DELETE /api/state-checkpoint 内存快照端点测试（prd 会话过期自动恢复
US-001）。

覆盖（AC 六项）：
1. peek 口径：POST 后会话 ``last_active`` 不变（FakeClock 断言）+ 不建会话名额
   （未知 sid 401 后 active_count 不变 / 已注册 sid POST 后不变）；
2. 写入 200 往返：``{stored:true}`` → ``store.get(sid)`` 为 gzip 字节 →
   ``parse_state_document`` 对拍 doc/form/quantities/run 逐字段；save_as 键容忍
   忽略；default 会话（无 sid 头）键 ``default``；
3. empty（未 commit 会话无 doc）→ ``200 {stored:false, reason:'empty'}``；
4. conservation last-good：改数量未重解 → ``200 {stored:false,
   reason:'conservation'}`` 且先前好快照字节不变；
5. ``_CheckpointStore`` 单元（FakeClock）：TTL 惰性清理 / FIFO 逐出 / 重复 put
   刷新新鲜度 / DELETE 幂等 / reset；
6. DELETE 路由幂等（条目不在也 ``200 {ok:true}``）+ 路由注册白盒 + env 容错
   回退（reload 口径）+ AST 分层守卫（禁 import server，sessions 同款）。

会话快照直接注入（registry.resolve + st.state = 合成 state，套路同
test_web_statefile）；另含 statefile ``rebuild_session_from_document`` 抽取的
直接单元（响应同形 / peek 复用），state_restore 零回归由既有
test_web_statefile.py 全绿保证。
"""
from __future__ import annotations

import ast
import importlib
import json
import gzip
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from materialsorting.web import checkpoint as checkpoint_mod
from materialsorting.web import server as server_mod
from materialsorting.web import sessions
from materialsorting.web.server import app
from materialsorting.web.sessions import _FakeClock
from materialsorting.web.statefile import parse_state_document


# ---------------------------------------------------------------- 合成数据（statefile 同款）

def _piece(pid, w, h, label):
    return {
        'pid': pid, 'label': label, 'size': 30,
        'polygon': [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]],
        'bbox': [0.0, 0.0, float(w), float(h)], 'area_mm2': float(w * h),
        'n_verts': 4, 'allowed_angles': [0, 180],
        'net_polygon': [[1.0, 1.0], [float(w) - 1, 1.0], [float(w) - 1, float(h) - 1]],
        'internal_lines': [[[0.0, float(h) / 2], [float(w), float(h) / 2]]],
        'notches': [[0.0, float(h) / 2, -1.0, 0.0]],
        'grain_line': [float(w) / 2, 0.0, float(w) / 2, float(h)],
    }


def _doc():
    pieces = [_piece('g01_30', 200, 150, 'g01'), _piece('g02_30', 180, 120, 'g02')]
    return {
        'doc_id': 'docabc01', 'source': '5336测试母版.dxf', 'gate_mm': 1750.0,
        'n_pieces': len(pieces), 'total_area_mm2': 51600.0, 'pieces': pieces,
        'label_representatives': {},
    }


def _state(doc=None):
    doc = doc or _doc()
    return {'doc': doc, 'gate_mm': doc['gate_mm'], 'pieces': doc['pieces'],
            'pieces_by_id': {p['pid']: p for p in doc['pieces']}}


def _form():
    return {'sizes': [30], 'gate': '175.00', 'time': '120', 'seed': '0',
            'multi_seed': False, 'seed_count': '3', 'per_type': {},
            'band_enabled': False, 'band_label': '', 'prefix_enabled': False,
            'prefix_front': '', 'prefix_back': ''}


def _quantities():
    return {'g01': {'30': 2}, 'g02': {'30': 1}}


def _placed():
    return [
        {'id': 'g01_30', 'rotation': 0.0, 'translation': [0.0, 0.0]},
        {'id': 'g01_30', 'rotation': 180.0, 'translation': [500.0, 10.0]},
        {'id': 'g02_30', 'rotation': 0.0, 'translation': [260.0, 0.0],
         'mirror': True},
    ]


def _run():
    return {'seed': 0, 'final': {'density': 0.84, 'density_sparrow': 0.82,
                                 'width_mm': 7523.0, 'elapsed': 121.4,
                                 'n_frames': 87, 'n_eroded': 0},
            'placed': _placed()}


def _sid_session(sid, doc=None):
    """注册 sid 会话并注入合成 state（测试便利：resolve + st.state 赋值）。"""
    st = sessions.registry.resolve(sid, create=True)
    st.state = _state(doc)
    return st


# ---------------------------------------------------------------- fixture

@pytest.fixture(autouse=True)
def _isolated():
    """单例注册表 + checkpoint 存储隔离（registry 套路同 test_web_statefile）。"""
    reg = sessions.registry
    reg.stop_scanner()
    reg.reset()
    checkpoint_mod.store.reset()
    yield reg
    checkpoint_mod.store.reset()
    reg.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------- AC5 store 单元（FakeClock）

def test_store_put_get_round_trip_bytes():
    clk = _FakeClock()
    cs = checkpoint_mod._CheckpointStore(ttl_sec=100.0, max_entries=4, clock=clk)
    cs.put('s1', b'alpha')
    cs.put('s2', b'beta')
    assert cs.get('s1') == b'alpha' and cs.get('s2') == b'beta'
    assert cs.get('ghost') is None and cs.size() == 2


def test_store_ttl_lazy_purge_on_put_and_get():
    """TTL 惰性清理：get / put 双入口都清超龄条目（无 daemon 线程）。"""
    clk = _FakeClock()
    cs = checkpoint_mod._CheckpointStore(ttl_sec=100.0, max_entries=8, clock=clk)
    cs.put('s1', b'a')
    clk.advance(99.0)                       # 未超龄
    assert cs.get('s1') == b'a'
    clk.advance(2.0)                        # 101 > 100 → 超龄
    assert cs.get('s1') is None             # get 惰性清除
    assert cs.size() == 0
    cs.put('s2', b'b')
    clk.advance(101.0)
    cs.put('s3', b'c')                      # put 入口同样清理 s2
    assert cs.get('s2') is None and cs.get('s3') == b'c'


def test_store_fifo_eviction_oldest_first():
    clk = _FakeClock()
    cs = checkpoint_mod._CheckpointStore(ttl_sec=1e9, max_entries=2, clock=clk)
    cs.put('s1', b'1')
    cs.put('s2', b'2')
    cs.put('s3', b'3')                      # 容量 2 → 最旧 s1 逐出
    assert cs.get('s1') is None and cs.size() == 2
    assert cs.get('s2') == b'2' and cs.get('s3') == b'3'


def test_store_repeated_put_refreshes_recency():
    """重复 put 同 sid：覆盖 + 移到 FIFO 尾（不被下一轮逐出）。"""
    clk = _FakeClock()
    cs = checkpoint_mod._CheckpointStore(ttl_sec=1e9, max_entries=2, clock=clk)
    cs.put('s1', b'1')
    cs.put('s2', b'2')
    cs.put('s1', b'1b')                     # s1 刷新新鲜度 → s2 成最旧
    cs.put('s3', b'3')                      # 逐出 s2（非 s1）
    assert cs.get('s1') == b'1b' and cs.get('s2') is None and cs.get('s3') == b'3'


def test_store_delete_idempotent_and_reset():
    clk = _FakeClock()
    cs = checkpoint_mod._CheckpointStore(ttl_sec=1e9, max_entries=8, clock=clk)
    assert cs.delete('ghost') is False      # 不在也 False，不抛
    cs.put('s1', b'1')
    assert cs.delete('s1') is True and cs.get('s1') is None
    assert cs.delete('s1') is False         # 再次删除幂等
    cs.put('s2', b'2')
    cs.reset()
    assert cs.size() == 0 and cs.get('s2') is None


def test_store_defaults_from_env_constants():
    """缺省构造取模块 env 常量（MS_CHECKPOINT_TTL_SEC/MS_CHECKPOINT_MAX）。"""
    cs = checkpoint_mod._CheckpointStore()
    assert cs.ttl_sec == checkpoint_mod.CHECKPOINT_TTL_SEC
    assert cs.max_entries == checkpoint_mod.CHECKPOINT_MAX


# ---------------------------------------------------------------- AC1 peek 口径

def test_checkpoint_post_does_not_touch_last_active(client, monkeypatch):
    """AC#1：写入 checkpoint 后会话 last_active 不变（FakeClock：若误走 resolve
    会刷成推进后的 clk.now）；也不新建会话（active_count 不变）。"""
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    sid = 'ckpt0001'
    st = _sid_session(sid)
    before = st.last_active
    n_active = sessions.registry.active_count
    clk.advance(123.0)                      # 推进后若 resolve 则 last_active 变晚
    r = client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                    json={'form': _form(), 'quantities': _quantities(),
                          'run': _run()})
    assert r.status_code == 200 and r.json() == {'stored': True}
    assert st.last_active == before         # peek 口径：不刷活性
    assert sessions.registry.active_count == n_active


def test_checkpoint_unknown_sid_401_no_slot_created(client):
    """AC#1：未知 sid（peek None）→ 401 {code:'session_expired'} 且不建会话名额。"""
    n_active = sessions.registry.active_count
    r = client.post('/api/state-checkpoint', headers={'X-Session-Id': 'ghostsid1'},
                    json={'form': _form(), 'quantities': _quantities()})
    assert r.status_code == 401
    assert r.json()['code'] == 'session_expired'
    assert sessions.registry.active_count == n_active
    assert sessions.registry.peek('ghostsid1') is None


def test_checkpoint_expired_session_still_snapshots_state(client, monkeypatch):
    """惰性逐出前（超龄但未被请求/扫描触发）peek 仍命中 → 照常快照（不刷活性、
    不触发逐出 —— checkpoint 绝不 resolve，FR-1）。"""
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    sid = 'ckpt0002'
    st = _sid_session(sid)
    clk.advance(sessions.registry.ttl_sec + 1.0)     # 逻辑过期（未惰性逐出）
    r = client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                    json={'form': _form(), 'quantities': _quantities()})
    assert r.status_code == 200 and r.json() == {'stored': True}
    assert checkpoint_mod.store.get(sid) is not None
    assert sessions.registry.peek(sid) is st         # 未被逐出（没走 resolve）


# ---------------------------------------------------------------- AC2 写入 200 往返

def test_checkpoint_post_stored_true_round_trip(client):
    """AC#2：stored:true → store 字节 gzip 魔数 + parse_state_document 逐字段对拍
    （doc = 会话 state 原样 / form / quantities / quantities_base / run.placed）。"""
    sid = 'ckpt0010'
    _sid_session(sid)
    form, quantities, run = _form(), _quantities(), _run()
    r = client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                    json={'form': form, 'quantities': quantities,
                          'quantities_base': {'g01': 2}, 'run': run})
    assert r.status_code == 200 and r.json() == {'stored': True}
    raw = checkpoint_mod.store.get(sid)
    assert raw[:2] == b'\x1f\x8b'
    doc = parse_state_document(raw)
    assert doc['doc'] == _doc()
    assert doc['form'] == form and doc['quantities'] == quantities
    assert doc['quantities_base'] == {'g01': 2}
    assert doc['run']['placed'] == _placed()


def test_checkpoint_without_run_stores_pure_config(client):
    """body 无 run → 快照无 run 键（纯配置档，state-save 同契约）。"""
    sid = 'ckpt0011'
    _sid_session(sid)
    r = client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                    json={'form': _form(), 'quantities': _quantities()})
    assert r.status_code == 200 and r.json() == {'stored': True}
    doc = parse_state_document(checkpoint_mod.store.get(sid))
    assert 'run' not in doc


def test_checkpoint_save_as_key_tolerated(client):
    """AC：save_as 键容忍忽略（照常 stored:true，快照键集不含 save_as）。"""
    sid = 'ckpt0012'
    _sid_session(sid)
    r = client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                    json={'form': _form(), 'quantities': _quantities(),
                          'save_as': 'auto-snapshot'})
    assert r.status_code == 200 and r.json() == {'stored': True}
    assert 'save_as' not in parse_state_document(
        checkpoint_mod.store.get(sid))


def test_checkpoint_default_session_no_header(client):
    """无 sid 头 → default 会话（runtime state）快照，存储键 'default'。"""
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update(_state())
    try:
        r = client.post('/api/state-checkpoint',
                        json={'form': _form(), 'quantities': _quantities()})
        assert r.status_code == 200 and r.json() == {'stored': True}
        raw = checkpoint_mod.store.get('default')
        assert raw is not None and raw[:2] == b'\x1f\x8b'
    finally:
        state.clear()
        state.update(saved)


def test_checkpoint_overwrite_updates_snapshot(client):
    """重复写入同 sid 覆盖旧快照（尾插刷新新鲜度，store 语义经端点验证）。"""
    sid = 'ckpt0013'
    _sid_session(sid)
    client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                json={'form': _form(), 'quantities': _quantities()})
    form2 = dict(_form(), time='60')
    client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                json={'form': form2, 'quantities': _quantities()})
    doc = parse_state_document(checkpoint_mod.store.get(sid))
    assert doc['form']['time'] == '60'
    assert checkpoint_mod.store.size() == 1


# ---------------------------------------------------------------- AC3 empty

def test_checkpoint_empty_session_reason_empty(client):
    """AC#3：会话空（注册未 commit，无 doc/pieces）→ 200 {stored:false,
    reason:'empty'}，不产生存储条目。"""
    sid = 'ckpt0020'
    sessions.registry.resolve(sid, create=True)      # 注册但 state 空 dict
    r = client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                    json={'form': _form(), 'quantities': _quantities()})
    assert r.status_code == 200
    assert r.json() == {'stored': False, 'reason': 'empty'}
    assert checkpoint_mod.store.get(sid) is None


# ---------------------------------------------------------------- AC4 conservation last-good

def test_checkpoint_conservation_last_good(client):
    """AC#4：守恒失败（改数量未重解）→ 200 {stored:false, reason:'conservation'}
    且先前好快照字节不变（last-good）。"""
    sid = 'ckpt0030'
    _sid_session(sid)
    r1 = client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                     json={'form': _form(), 'quantities': _quantities(),
                           'run': _run()})
    assert r1.status_code == 200 and r1.json() == {'stored': True}
    good = checkpoint_mod.store.get(sid)

    r2 = client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                     json={'form': _form(),
                           'quantities': {'g01': {'30': 5}, 'g02': {'30': 1}},
                           'run': _run()})
    assert r2.status_code == 200
    assert r2.json() == {'stored': False, 'reason': 'conservation'}
    assert checkpoint_mod.store.get(sid) == good          # 字节不变
    assert json.loads(gzip.decompress(good))['quantities'] == _quantities()


def test_checkpoint_conservation_first_failure_no_entry(client):
    """首写即守恒失败 → 无条目（从未 put）；随后合法载荷照常入库。"""
    sid = 'ckpt0031'
    _sid_session(sid)
    r = client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                    json={'form': _form(),
                          'quantities': {'g01': {'30': 9}, 'g02': {'30': 1}},
                          'run': _run()})
    assert r.status_code == 200
    assert r.json() == {'stored': False, 'reason': 'conservation'}
    assert checkpoint_mod.store.get(sid) is None
    r2 = client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                     json={'form': _form(), 'quantities': _quantities(),
                           'run': _run()})
    assert r2.json() == {'stored': True}


def test_checkpoint_conservation_without_run_passes(client):
    """body 无 run → 不做守恒校验（改数量的中间态纯配置档照常快照）。"""
    sid = 'ckpt0032'
    _sid_session(sid)
    r = client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                    json={'form': _form(),
                          'quantities': {'g01': {'30': 7}, 'g02': {'30': 1}}})
    assert r.status_code == 200 and r.json() == {'stored': True}


# ---------------------------------------------------------------- 载荷/会话闸门

def test_checkpoint_invalid_sid_400(client):
    r = client.post('/api/state-checkpoint', headers={'X-Session-Id': 'bad-sid!'},
                    json={'form': _form(), 'quantities': _quantities()})
    assert r.status_code == 400 and r.json() == {'error': 'sid 非法'}


def test_checkpoint_payload_shape_400(client):
    """载荷形态非法 → 400（与 state-save 同文案同判据）。"""
    sid = 'ckpt0040'
    _sid_session(sid)
    h = {'X-Session-Id': sid}
    r = client.post('/api/state-checkpoint', headers=h, content='not-json')
    assert r.status_code == 400 and 'JSON' in r.json()['error']
    r = client.post('/api/state-checkpoint', headers=h,
                    json={'quantities': _quantities()})
    assert r.status_code == 400 and 'form' in r.json()['error']
    r = client.post('/api/state-checkpoint', headers=h,
                    json={'form': _form(), 'quantities': [1, 2]})
    assert r.status_code == 400 and 'quantities' in r.json()['error']
    r = client.post('/api/state-checkpoint', headers=h,
                    json={'form': _form(), 'quantities': _quantities(),
                          'quantities_base': {'g01': 'x'}})
    assert r.status_code == 400 and 'quantities_base' in r.json()['error']
    r = client.post('/api/state-checkpoint', headers=h,
                    json={'form': _form(), 'quantities': _quantities(),
                          'run': {'placed': [{'rotation': 0}]}})     # id 缺失
    assert r.status_code == 400 and 'placed[0]' in r.json()['error']
    r = client.post('/api/state-checkpoint', headers=h,
                    json={'form': _form(), 'quantities': _quantities(),
                          'run': {'seed': 1}})                       # placed 缺失
    assert r.status_code == 400 and 'placed' in r.json()['error']
    assert checkpoint_mod.store.get(sid) is None     # 全程无条目入库


# ---------------------------------------------------------------- AC6 DELETE 端点

def test_checkpoint_delete_idempotent(client):
    """AC#6：DELETE 在场条目 → 200 {ok:true} + 读回 None；条目不存在同样
    200 {ok:true}（幂等，双次删除同响应）。"""
    sid = 'ckpt0050'
    _sid_session(sid)
    client.post('/api/state-checkpoint', headers={'X-Session-Id': sid},
                json={'form': _form(), 'quantities': _quantities()})
    assert checkpoint_mod.store.get(sid) is not None
    r1 = client.delete('/api/state-checkpoint', headers={'X-Session-Id': sid})
    assert r1.status_code == 200 and r1.json() == {'ok': True}
    assert checkpoint_mod.store.get(sid) is None
    r2 = client.delete('/api/state-checkpoint', headers={'X-Session-Id': sid})
    assert r2.status_code == 200 and r2.json() == {'ok': True}    # 幂等


def test_checkpoint_delete_never_stored_ok(client):
    """从未写入过（empty 会话）→ DELETE 同 200 {ok:true}。"""
    sid = 'ckpt0051'
    sessions.registry.resolve(sid, create=True)
    r = client.delete('/api/state-checkpoint', headers={'X-Session-Id': sid})
    assert r.status_code == 200 and r.json() == {'ok': True}


def test_checkpoint_delete_invalid_sid_400(client):
    r = client.delete('/api/state-checkpoint', headers={'X-Session-Id': 'bad!'})
    assert r.status_code == 400 and r.json() == {'error': 'sid 非法'}


def test_checkpoint_delete_does_not_touch_registry(client):
    """DELETE 不触碰会话注册表（活性/名额零影响；也不逐出也不报 401）。"""
    sid = 'ckpt0052'
    st = _sid_session(sid)
    before = st.last_active
    r = client.delete('/api/state-checkpoint', headers={'X-Session-Id': sid})
    assert r.status_code == 200
    assert sessions.registry.peek(sid) is st
    assert st.last_active == before


# ---------------------------------------------------------------- 路由接线 / env / AST

def test_checkpoint_routes_registered():
    """路由在场（register_checkpoint_routes 接线白盒：POST + DELETE 两方法）。"""
    hits = [rt for rt in server_mod.app.routes
            if getattr(rt, 'path', '') == '/api/state-checkpoint']
    methods = set().union(*(rt.methods for rt in hits)) if hits else set()
    assert methods == {'POST', 'DELETE'}


def test_checkpoint_env_constants_fallback(monkeypatch):
    """env 容错回退：合法值生效、非法/缺省回退 7200/16（reload 口径；结束复原）。"""
    monkeypatch.setenv('MS_CHECKPOINT_TTL_SEC', '300')
    monkeypatch.setenv('MS_CHECKPOINT_MAX', '4')
    mod = importlib.reload(checkpoint_mod)
    assert mod.CHECKPOINT_TTL_SEC == 300.0 and mod.CHECKPOINT_MAX == 4
    monkeypatch.setenv('MS_CHECKPOINT_TTL_SEC', 'not-a-number')
    monkeypatch.delenv('MS_CHECKPOINT_MAX')
    mod = importlib.reload(checkpoint_mod)
    assert mod.CHECKPOINT_TTL_SEC == 7200.0     # 非法回退缺省
    assert mod.CHECKPOINT_MAX == 16             # 缺省回退 16
    monkeypatch.delenv('MS_CHECKPOINT_TTL_SEC')
    importlib.reload(checkpoint_mod)            # 复原模块态（新建单例 store）


def test_checkpoint_module_layering_purity():
    """AC：AST 守卫 —— checkpoint 仅标准库 + fastapi + web 兄弟，全模块（含函数
    内 import）禁 import server（server → checkpoint 单向无环；ast.walk 覆盖
    延迟 import，strategy 禁 cli 同写法）。"""
    src = Path(checkpoint_mod.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'gzip', 'json', 'sys', 'threading', 'time',
               'collections', 'typing', 'fastapi', 'materialsorting'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split('.')
                assert parts[0] in allowed, alias.name
                assert 'server' not in parts, alias.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            parts = mod.split('.')
            assert 'server' not in parts, mod          # 相对/绝对都禁 server
            if not node.level:
                assert parts[0] in allowed, mod


# --------------------------------------- rebuild_session_from_document 直接单元

def test_rebuild_session_from_document_shape():
    """statefile 共享重建函数（US-001 抽取）：parse → rebuild 直调，响应键集 =
    state-restore 成功响应同形 + sid 会话覆盖写入 + doc_id 铸新。"""
    from materialsorting.web.statefile import (
        build_state_document, rebuild_session_from_document, serialize_state)

    sid = 'ckpt0060'
    st = _sid_session(sid)
    document = build_state_document(st.state, _form(), _quantities(), _run(),
                                    {'g01': 2})
    res = rebuild_session_from_document(
        parse_state_document(serialize_state(document)), sid)
    assert set(res) == {'doc_id', 'filename', 'parse', 'manifest', 'final',
                        'placed', 'run', 'quantities_base', 'form',
                        'quantities'}
    assert res['doc_id'] != 'docabc01' and len(res['doc_id']) == 32   # uuid 铸新
    assert res['filename'] == '5336测试母版.dxf'
    assert res['run']['placed'] == _placed()
    assert res['quantities_base'] == {'g01': 2}
    assert sessions.registry.peek(sid).state['doc']['doc_id'] == res['doc_id']
