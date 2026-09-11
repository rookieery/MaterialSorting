"""POST /api/state-save 状态文件保存端点测试（prd 状态文件 US-001）。

覆盖（AC 四项 + runtime 提取回归 + 守恒函数单元）：
1. 200 往返：default 会话合成 state（5 层全量 doc）→ 响应 gzip JSON 附件（魔数
   1f 8b、.msn、Content-Disposition 中文/ASCII 双名、media_type application/gzip）
   → gunzip 后顶层 schema_version=1/doc/form/quantities，doc.pieces 与会话
   intermediate 逐字段一致（含 5 层）+ run.placed 原序深拷贝；body 无 run →
   文件无 run 键（纯配置档契约）；
2. 会话空（无 doc）→ 422；sid 过期（FakeClock 惰性逐出）→ 401
   {code:'session_expired'} 结构化 JSON 非文件流；非法 sid → 400；
3. 保存期守恒 fail-fast：body 带 run 且改 quantities 未重解（demand≠placed 副本
   多重集）→ 400 指路文案「数量矩阵/尺码选择与当前结果不一致，请先重新求解或
   改回数量再保存」；placed 引用会话外 pid（母版已变更场景）→ 同 400；
   码选过滤（sizes 不含该片 size → demand 无该 pid）→ 同 400；
4. 载荷校验：body 非 JSON 对象 / form 缺失 / run.placed 条目缺 id → 400；
5. ``runtime._state_from_doc`` 提取回归：与 ``_build_pieces_state`` 对同一
   intermediate 文件产物逐键全等（行为零变化）；
6. ``check_placed_conservation`` 单元（保存/恢复共用函数）：quantities=None →
   demand 全 1；多副本同 pid 计数守恒通过；unknown_pid / count_mismatch 两 kind。

会话快照直接注入（registry/`_PIECES_STATE` 原位套路同 test_read_routes_sessions），
不走 commit 全管线（US-002 已覆盖落盘链路）。
"""
from __future__ import annotations

import gzip
import json
import re
from urllib.parse import quote, unquote

import pytest
from starlette.testclient import TestClient

from materialsorting.web import server as server_mod
from materialsorting.web import sessions
from materialsorting.web.runtime import _build_pieces_state, _state_from_doc
from materialsorting.web.server import app
from materialsorting.web.sessions import _FakeClock
from materialsorting.web.statefile import (
    StateConservationError,
    build_state_document,
    check_placed_conservation,
    serialize_state,
)

CONSERVATION_MSG = '数量矩阵/尺码选择与当前结果不一致，请先重新求解或改回数量再保存'


# ---------------------------------------------------------------- 合成数据

def _piece(pid, w, h, label):
    """合成 v2 schema 矩形裁片（5 层全量字段，守恒/往返断言载体）。"""
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
    """与 _quantities demand 守恒（g01_30×2 多副本 + g02_30×1），原序即求解序。"""
    return [
        {'id': 'g01_30', 'rotation': 0.0, 'translation': [0.0, 0.0]},
        {'id': 'g01_30', 'rotation': 180.0, 'translation': [500.0, 10.0]},
        {'id': 'g02_30', 'rotation': 0.0, 'translation': [260.0, 0.0],
         'mirror': True},
    ]


def _run(placed=None):
    return {'seed': 0, 'final': {'density': 0.84, 'density_sparrow': 0.82,
                                 'width_mm': 7523.0, 'elapsed': 121.4,
                                 'n_frames': 87, 'n_eroded': 0},
            'placed': _placed() if placed is None else placed}


# ---------------------------------------------------------------- fixture

@pytest.fixture(autouse=True)
def _isolated_registry():
    """单例注册表隔离（套路同 tests/test_read_routes_sessions.py）。"""
    reg = sessions.registry
    reg.stop_scanner()
    reg.reset()
    yield reg
    reg.reset()


@pytest.fixture
def client():
    """default 会话注入合成 state（原位 clear+update，teardown 恢复真实 state）。"""
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update(_state())
    with TestClient(app) as c:
        yield c
    state.clear()
    state.update(saved)


# ---------------------------------------------------------------- AC1 200 往返

def test_save_200_round_trip(client):
    """AC#1：合法载荷 → 200 附件（gzip、.msn、双名 CD）；gunzip 后 doc/form/
    quantities/run 逐字段一致（doc.pieces 5 层原样、placed 原序含 mirror）。"""
    form, quantities, run = _form(), _quantities(), _run()
    r = client.post('/api/state-save',
                    json={'form': form, 'quantities': quantities, 'run': run})
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('application/gzip')
    body = r.content
    assert body[:2] == b'\x1f\x8b'                       # gzip 魔数
    doc = json.loads(gzip.decompress(body))

    assert doc['schema_version'] == 1
    assert doc['app'] == 'materialsorting'
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', doc['saved_at'])
    # doc 块 = 会话 intermediate 原样（含 5 层 + label_representatives）
    assert doc['doc'] == _doc()
    assert doc['form'] == form
    assert doc['quantities'] == quantities
    assert doc['run'] == run
    # 保存深拷贝：改文件 dict 不反写会话（placed 原序 + mirror omit-when-false 透传）
    assert doc['run']['placed'] == _placed()


def test_save_filename_dual_content_disposition(client):
    """AC#1：文件名 <source 去 .dxf>_状态_<yyyymmdd-HHMMSS>.msn，中文/ASCII 双写
    （含中文 source → ASCII 侧回退 nesting，/export 同法）。"""
    r = client.post('/api/state-save',
                    json={'form': _form(), 'quantities': _quantities()})
    assert r.status_code == 200
    cd = r.headers['content-disposition']
    assert cd.startswith('attachment; ')
    m_ascii = re.search(r'filename="([^"]+)"', cd)
    m_cn = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    assert m_ascii and m_cn
    assert re.fullmatch(r'nesting_state_\d{8}-\d{6}\.msn', m_ascii.group(1))
    cn = unquote(m_cn.group(1))
    assert re.fullmatch(r'5336测试母版_状态_\d{8}-\d{6}\.msn', cn)
    # 中文侧确经 RFC5987 percent-encode（fallback 双名同 ts）
    assert quote(cn) == m_cn.group(1)
    assert m_ascii.group(1)[len('nesting_state_'):] == cn[len('5336测试母版_状态_'):]


def test_save_without_run_omits_run_key(client):
    """AC#1：body 无 run → 文件无 run 键（纯配置档：端点容忍；run:{} 空对象同
    缺席语义）。"""
    r = client.post('/api/state-save',
                    json={'form': _form(), 'quantities': _quantities()})
    assert r.status_code == 200
    doc = json.loads(gzip.decompress(r.content))
    assert 'run' not in doc
    assert set(doc) == {'schema_version', 'app', 'saved_at', 'doc',
                        'form', 'quantities'}
    r2 = client.post('/api/state-save',
                     json={'form': _form(), 'quantities': _quantities(),
                           'run': {}})
    assert r2.status_code == 200
    assert 'run' not in json.loads(gzip.decompress(r2.content))


def test_save_ascii_source_uses_stem_in_both_names(client):
    """ASCII source → 双名同前缀（无中文回退）。"""
    d = _doc()
    d['source'] = 'plain_master.DXF'
    state = server_mod._PIECES_STATE
    state.update(_state(d))
    r = client.post('/api/state-save',
                    json={'form': _form(), 'quantities': _quantities()})
    assert r.status_code == 200
    cd = r.headers['content-disposition']
    assert re.search(r'filename="plain_master_state_\d{8}-\d{6}\.msn"', cd)
    assert unquote(re.search(r"filename\*=UTF-8''([^;]+)", cd).group(1)) \
        .startswith('plain_master_状态_')


# ---------------------------------------------------------------- AC3 会话闸门/空态

def test_save_empty_session_422():
    """AC#3：会话空（无 doc）→ 422（default 启动未 commit 形态）。"""
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    try:
        with TestClient(app) as c:
            r = c.post('/api/state-save',
                       json={'form': _form(), 'quantities': _quantities()})
        assert r.status_code == 422
        assert '排料数据为空' in r.json()['error']
    finally:
        state.clear()
        state.update(saved)


def test_save_expired_sid_401_json_not_file(client, monkeypatch):
    """AC#3：过期 sid → 401 {code:'session_expired'} 结构化 JSON（非文件流）。
    （FakeClock 先装再建会话 —— 建完才换钟会得负龄，套路同 test_web_edit_polish。）"""
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    sid = 'stfile001'
    client.post('/api/session', headers={'X-Session-Id': sid})
    clk.advance(sessions.registry.ttl_sec + 1.0)
    r = client.post('/api/state-save', headers={'X-Session-Id': sid},
                    json={'form': _form(), 'quantities': _quantities()})
    assert r.status_code == 401
    assert r.headers['content-type'].startswith('application/json')
    assert r.json() == {'code': 'session_expired', 'error': '会话已过期（10 分钟无操作），请刷新页面'}


def test_save_invalid_sid_400(client):
    """AC#3：非法 sid → 400 {error:'sid 非法'}。"""
    r = client.post('/api/state-save', headers={'X-Session-Id': 'bad-sid!'},
                    json={'form': _form(), 'quantities': _quantities()})
    assert r.status_code == 400
    assert r.json() == {'error': 'sid 非法'}


def test_save_sid_session_state(client):
    """带 sid 会话快照 → 保存该会话 doc（多会话隔离，与读路由同语义）。"""
    sid = 'stfile002'
    st = sessions.registry.resolve(sid, create=True)
    d = _doc()
    d['source'] = 'sidmaster.dxf'
    st.state = _state(d)
    r = client.post('/api/state-save', headers={'X-Session-Id': sid},
                    json={'form': _form(), 'quantities': _quantities(), 'run': _run()})
    assert r.status_code == 200
    doc = json.loads(gzip.decompress(r.content))
    assert doc['doc']['source'] == 'sidmaster.dxf'


# ---------------------------------------------------------------- AC2 保存期守恒

def test_save_conservation_quantity_changed_400(client):
    """AC#2：改数量未重解（g01 demand 3 ≠ placed 2）→ 400 指路文案。"""
    r = client.post('/api/state-save', json={
        'form': _form(),
        'quantities': {'g01': {'30': 3}, 'g02': {'30': 1}},   # placed 是 2+1
        'run': _run()})
    assert r.status_code == 400
    assert r.json()['error'] == CONSERVATION_MSG


def test_save_conservation_size_filtered_400(client):
    """AC#2：码选未含该片 size（sizes=[32] → demand 全空）→ 同 400。"""
    form = _form()
    form['sizes'] = [32]
    r = client.post('/api/state-save', json={
        'form': form, 'quantities': _quantities(), 'run': _run()})
    assert r.status_code == 400
    assert r.json()['error'] == CONSERVATION_MSG


def test_save_conservation_unknown_pid_400(client):
    """AC#2：placed 引用会话外 pid（母版已变更场景）→ 同 400。"""
    placed = [dict(p) for p in _placed()]
    placed[1]['id'] = 'zz_99'
    r = client.post('/api/state-save', json={
        'form': _form(), 'quantities': _quantities(), 'run': _run(placed)})
    assert r.status_code == 400
    assert r.json()['error'] == CONSERVATION_MSG


def test_save_conservation_multi_copy_exact_pass(client):
    """守恒精确通过：同 pid 多副本 2 条 == demand 2（多副本不变量三道锁之一）。"""
    r = client.post('/api/state-save', json={
        'form': _form(), 'quantities': _quantities(), 'run': _run()})
    assert r.status_code == 200
    assert len(json.loads(gzip.decompress(r.content))['run']['placed']) == 3


# ---------------------------------------------------------------- AC4 载荷校验

@pytest.mark.parametrize('payload, want', [
    ({'quantities': {}}, '缺少 form'),
    ({'form': _form(), 'quantities': []}, 'quantities 须为'),
    ({'form': _form(), 'quantities': {}, 'run': []}, 'run 须为对象'),
    ({'form': _form(), 'quantities': {}, 'run': {'placed': []}}, 'run.placed 不能为空'),
    ({'form': _form(), 'quantities': {}, 'run': {'placed': [{'rotation': 0}]}},
     '形态非法'),
])
def test_save_payload_shape_400(client, payload, want):
    """AC#4：载荷形态非法 → 400 fail-fast。"""
    r = client.post('/api/state-save', json=payload)
    assert r.status_code == 400
    assert want in r.json()['error']


def test_save_non_json_body_400(client):
    """AC#4：body 非 JSON → 400。"""
    r = client.post('/api/state-save', content=b'not-json',
                    headers={'Content-Type': 'application/json'})
    assert r.status_code == 400
    assert 'JSON' in r.json()['error']


def test_save_route_registered():
    """路由在场（register_statefile_routes 接线白盒）。"""
    assert '/api/state-save' in [getattr(rt, 'path', '') for rt in app.routes]


# ---------------------------------------------------------------- runtime 提取回归

def test_state_from_doc_matches_build_pieces_state(tmp_path):
    """US-001 任务 2：_state_from_doc 与 _build_pieces_state 对同一 intermediate
    产物逐键全等（路径读取与 dict 构建解耦，行为零变化）。"""
    doc = _doc()
    p = tmp_path / 'pieces_intermediate.json'
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    from_path = _build_pieces_state(str(p))
    from_dict = _state_from_doc(doc)
    assert from_path == from_dict
    assert from_path['doc'] is doc or from_path['doc'] == doc   # 同内容
    assert from_path['pieces_by_id'].keys() == {'g01_30', 'g02_30'}
    assert from_path['gate_mm'] == 1750.0
    assert from_path['gate_mm'] == from_dict['gate_mm']


# ---------------------------------------------------------------- 守恒函数单元

def test_conservation_quantities_none_demand_one():
    """quantities=None → demand 全 1（旧语义，build_pid_meta 缺省口径：单片 doc
    placed 恰 1 条通过、2 条 count_mismatch）。"""
    pieces = [_piece('g01_30', 200, 150, 'g01')]
    placed = [{'id': 'g01_30', 'rotation': 0.0, 'translation': [0.0, 0.0]}]
    check_placed_conservation(placed, pieces)                    # 不抛 = 通过
    with pytest.raises(StateConservationError) as ei:
        check_placed_conservation(placed + [dict(placed[0])], pieces)
    assert ei.value.kind == 'count_mismatch'                     # demand=1 ≠ 2


def test_conservation_kinds():
    """unknown_pid / count_mismatch 两 kind + detail 可读（恢复端 US-002 复用）。"""
    pieces = _doc()['pieces']
    quantities = _quantities()
    sizes = [30]
    with pytest.raises(StateConservationError) as ei:
        check_placed_conservation(
            [{'id': 'zz_99', 'rotation': 0.0, 'translation': [0, 0]}],
            pieces, sizes=sizes, quantities=quantities)
    assert ei.value.kind == 'unknown_pid'
    assert 'zz_99' in ei.value.detail
    with pytest.raises(StateConservationError) as ei:
        check_placed_conservation(
            _placed()[:2], pieces, sizes=sizes, quantities=quantities)   # 漏 g02
    assert ei.value.kind == 'count_mismatch'
    assert 'g02_30' in ei.value.detail


def test_build_state_document_run_omitted_when_falsy():
    """run=None/{} → 文件无 run 键；quantities=None 原样入文件。"""
    doc = build_state_document(_state(), _form(), None, None)
    assert 'run' not in doc and doc['quantities'] is None
    assert 'run' not in build_state_document(_state(), _form(), {}, {})
    assert serialize_state(doc)[:2] == b'\x1f\x8b'
