"""POST /api/state-save / POST /api/state-restore 状态文件端点测试（US-001/US-002）。

US-001（保存端）覆盖（AC 四项 + runtime 提取回归 + 守恒函数单元）：
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

US-002（恢复端）覆盖：
7. 200 完整载荷：{doc_id(铸新)/filename/parse/manifest/final/placed/run/form/
   quantities}；manifest 与 build_pid_meta 同 form 重算逐字段一致（含 per_type
   erode 的 raw_polygon/d_mm 物理毛版口径）；parse 载荷 label 与 doc 同源、
   5 层透传；纯 JSON（无 gzip）/无 run 纯配置档同通过；
8. 校验链全 fail-fast 400/413：坏 gzip/坏 JSON/schema_version 缺失·非 int·过新
   （文案含双版本号）/解压后与裸上传双超限/doc 块逐片形态（polygon 顶点/NaN/
   gate/pid 重复/label 非法）/run.placed 条目形态（含 mirror 非布尔）/placed
   pid 越界/副本数≠demand/provenance.kind 非法枚举；解析在 threadpool 执行；
9. 会话语义：恢复写入当前 sid（覆盖语义、不占 MS_SESSION_MAX 名额、过期 401、
   非法 400、sid 隔离）；default 恢复走 runtime 原子重绑且**不落盘**
   （INTERMEDIATE/uploads 字节不变断言）；
10. 端到端：恢复后该 sid 的 /api/ptypes、/export、/api/edit-polish 立即可用
    （placed 守恒）；链式传递 save→restore→save→restore 二次往返逐字段一致。

会话快照直接注入（registry/`_PIECES_STATE` 原位套路同 test_read_routes_sessions），
不走 commit 全管线（US-002 已覆盖落盘链路）。
"""
from __future__ import annotations

import gzip
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import quote, unquote

import pytest
from starlette.testclient import TestClient

from materialsorting.web import server as server_mod
from materialsorting.web import sessions
from materialsorting.web.runtime import _build_pieces_state, _state_from_doc
from materialsorting.web.server import app
from materialsorting.web.sessions import _FakeClock
from materialsorting.web.solver import build_pid_meta
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
    reps = {}
    for p in pieces:   # /api/ptypes 同源代表裁片（RAW 坐标，US-002 恢复后立即可用断言）
        reps[p['label']] = {k: p[k] for k in ('label', 'polygon', 'net_polygon',
                                              'internal_lines', 'notches', 'grain_line')}
    return {
        'doc_id': 'docabc01', 'source': '5336测试母版.dxf', 'gate_mm': 1750.0,
        'n_pieces': len(pieces), 'total_area_mm2': 51600.0, 'pieces': pieces,
        'label_representatives': reps,
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


# ================================================================ US-002 恢复端

def _save_msn(client, headers=None, with_run=True):
    """default（或指定 sid）会话 → .msn 字节（守恒通过的合法文件）。"""
    body = {'form': _form(), 'quantities': _quantities()}
    if with_run:
        body['run'] = _run()
    r = client.post('/api/state-save', headers=headers or {}, json=body)
    assert r.status_code == 200, r.text
    return r.content


def _restore(client, data, name='work.msn', headers=None):
    return client.post('/api/state-restore', headers=headers or {},
                       files={'file': (name, data, 'application/octet-stream')})


def _edit_msn(data, fn):
    """解包→改 document→重打包（手改文件场景构造器）。"""
    d = json.loads(gzip.decompress(data))
    fn(d)
    return gzip.compress(json.dumps(d, ensure_ascii=False).encode('utf-8'))


# ---------------------------------------------------------------- AC1 200 完整载荷

def test_restore_200_full_payload(client):
    """AC#1：multipart .msn → 200 {doc_id, filename, parse, manifest, final,
    placed, run, form, quantities}；doc_id 铸新（≠文件内原 id）；final/placed/
    form/quantities/run 原样往返（placed 原序含 mirror）；parse 载荷 label 与
    doc 同源（数量矩阵键一致）+ 5 层透传。"""
    msn = _save_msn(client)
    r = _restore(client, msn)
    assert r.status_code == 200, r.text
    res = r.json()
    assert set(res) >= {'doc_id', 'filename', 'parse', 'manifest', 'final',
                        'placed', 'run', 'form', 'quantities'}
    assert res['doc_id'] != 'docabc01' and re.fullmatch(r'[0-9a-f]{32}', res['doc_id'])
    assert res['filename'] == '5336测试母版.dxf'
    assert res['form'] == _form()
    assert res['quantities'] == _quantities()
    assert res['final'] == _run()['final']
    assert res['placed'] == _placed()
    assert res['run'] == _run()

    parse = res['parse']
    assert parse['doc_id'] == res['doc_id']
    assert parse['filename'] == '5336测试母版.dxf'
    assert [s['size'] for s in parse['sizes']] == [30]
    by_label = {pc['label']: pc for pc in parse['sizes'][0]['pieces']}
    assert sorted(by_label) == ['g01', 'g02']
    p0 = _doc()['pieces'][0]
    assert by_label['g01']['polygon'] == p0['polygon']
    assert by_label['g01']['net_polygon'] == p0['net_polygon']
    assert by_label['g01']['internal_lines'] == p0['internal_lines']
    assert by_label['g01']['notches'] == p0['notches']
    assert by_label['g01']['grain_line'] == p0['grain_line']


def test_restore_manifest_recompute_matches_build_pid_meta(client):
    """AC#1：manifest 与 build_pid_meta 同 form 重算逐字段一致（id/size/color/
    area/polygon/raw_polygon/d_mm/label/demand/5 层 + gate/total_area/n_eroded）。"""
    msn = _save_msn(client)
    r = _restore(client, msn)
    assert r.status_code == 200
    res = r.json()
    pid_meta, total_area, n_eroded = build_pid_meta(
        _doc()['pieces'], sizes=_form()['sizes'], per_type=_form()['per_type'],
        quantities=_quantities())
    man = res['manifest']
    assert man['gate_mm'] == 1750.0
    assert man['total_area_mm2'] == total_area == 2 * 200 * 150 + 1 * 180 * 120
    assert man['n_eroded'] == n_eroded == 0
    assert {p['id'] for p in man['pieces']} == set(pid_meta)
    for piece in man['pieces']:
        meta = pid_meta[piece['id']]
        assert piece['size'] == meta['size']
        assert piece['color'] == meta['color']
        assert piece['area_mm2'] == meta['area_mm2']
        assert piece['polygon'] == meta['polygon']
        assert piece['raw_polygon'] == meta['raw_polygon'] == \
            _state()['pieces_by_id'][piece['id']]['polygon']
        assert piece['d_mm'] == meta['d_mm'] == 0.0
        assert piece['label'] == meta['label']
        assert piece['demand'] == meta['demand']
        for k in ('net_polygon', 'internal_lines', 'notches', 'grain_line'):
            assert piece[k] == meta[k]


def test_restore_manifest_per_type_erode_raw_polygon(client):
    """AC#1：per_type d=2 → manifest.polygon 为 erode 后碰撞轮廓、raw_polygon
    原始毛版原样、d_mm=2（2026-09-06 物理毛版口径 round-trip）。"""
    msn = _save_msn(client)
    big = _edit_msn(msn, lambda d: d['form'].__setitem__(
        'per_type', {'g01': {'d': 2}}))
    r = _restore(client, big)
    assert r.status_code == 200
    man = r.json()['manifest']
    mp = {p['id']: p for p in man['pieces']}
    raw = {p['pid']: p['polygon'] for p in _doc()['pieces']}
    assert mp['g01_30']['d_mm'] == 2.0
    assert mp['g01_30']['raw_polygon'] == raw['g01_30']
    assert mp['g01_30']['polygon'] != raw['g01_30']
    assert mp['g02_30']['d_mm'] == 0.0
    assert mp['g02_30']['raw_polygon'] == raw['g02_30']
    assert man['n_eroded'] == 1


def test_restore_plain_json_and_pure_config(client):
    """AC#1：纯 JSON（无 gzip、.json 扩展名）同通过；无 run 纯配置档 → final/
    placed/run 均为 None、manifest 照常重算。"""
    msn = _save_msn(client, with_run=False)
    plain = json.dumps(json.loads(gzip.decompress(msn)),
                       ensure_ascii=False).encode('utf-8')
    r = _restore(client, plain, name='work.json')
    assert r.status_code == 200
    res = r.json()
    assert res['final'] is None and res['placed'] is None and res['run'] is None
    assert {p['id'] for p in res['manifest']['pieces']} == {'g01_30', 'g02_30'}


# ---------------------------------------------------------------- AC2 校验链

def test_restore_bad_gzip_400(client):
    """坏 gzip（魔数在身、正文损坏）→ 400 状态文件损坏。"""
    r = _restore(client, b'\x1f\x8b' + b'garbage-not-gzip')
    assert r.status_code == 400
    assert '状态文件损坏' in r.json()['error']


def test_restore_bad_json_400(client):
    """非 JSON 正文 → 400 状态文件损坏。"""
    r = _restore(client, b'not-json-at-all', name='bad.msn')
    assert r.status_code == 400
    assert '状态文件损坏' in r.json()['error']


@pytest.mark.parametrize('fn, want', [
    (lambda d: d.pop('schema_version'), 'schema_version'),
    (lambda d: d.__setitem__('schema_version', '1'), 'schema_version'),
    (lambda d: d.__setitem__('schema_version', True), 'schema_version'),
    (lambda d: d.__setitem__('schema_version', 99), '版本过新'),
    (lambda d: d.pop('form'), '缺少 form'),
    (lambda d: d.__setitem__('quantities', []), 'quantities 须为'),
])
def test_restore_schema_and_blocks_400(client, fn, want):
    """schema_version 缺失/非 int/过新 + form/quantities 块缺失 → 400。"""
    msn = _save_msn(client)
    r = _restore(client, _edit_msn(msn, fn))
    assert r.status_code == 400
    assert want in r.json()['error']


def test_restore_version_too_new_dual_numbers(client):
    """版本门 v99 → 400 文案含双版本号（v99 + 本程序支持至 v1）。"""
    msn = _save_msn(client)
    r = _restore(client, _edit_msn(msn, lambda d: d.__setitem__('schema_version', 99)))
    assert r.status_code == 400
    err = r.json()['error']
    assert 'v99' in err and 'v1' in err


def test_restore_decompressed_over_limit_413(client):
    """gzip 炸弹防线：压缩体很小、解压后 >20MB → 413。"""
    msn = _save_msn(client)
    big = _edit_msn(msn, lambda d: d.__setitem__('padding', ' ' * (21 * 1024 * 1024)))
    assert len(big) < 1024 * 1024
    r = _restore(client, big)
    assert r.status_code == 413
    assert '解压后超过上限' in r.json()['error']


def test_restore_raw_upload_over_limit_413(client):
    """裸上传 >20MB → 413（未解压先拦，同 /api/parse-dxf 口径）。"""
    r = _restore(client, b'x' * (20 * 1024 * 1024 + 1), name='big.msn')
    assert r.status_code == 413


def test_restore_placed_pid_outside_400(client):
    """placed pid 越界（母版外）→ 400「placed 引用母版外裁片」。"""
    msn = _save_msn(client)
    bad = _edit_msn(msn, lambda d: d['run']['placed'][2].__setitem__('id', 'zz_99'))
    r = _restore(client, bad)
    assert r.status_code == 400
    assert 'placed 引用母版外裁片' in r.json()['error']


def test_restore_count_mismatch_400(client):
    """副本数 ≠ demand（手改 quantities）→ 400「副本数与数量矩阵不符」。"""
    msn = _save_msn(client)
    bad = _edit_msn(msn, lambda d: d['quantities']['g01'].__setitem__('30', 5))
    r = _restore(client, bad)
    assert r.status_code == 400
    err = r.json()['error']
    assert '副本数与数量矩阵不符' in err and 'g01_30' in err


def test_restore_conservation_size_filtered_400(client):
    """码选过滤（sizes=[32] → 重算 demand 无任何 pid）→ 同 400 内部不一致。"""
    msn = _save_msn(client)
    bad = _edit_msn(msn, lambda d: d['form'].__setitem__('sizes', [32]))
    r = _restore(client, bad)
    assert r.status_code == 400
    assert 'placed 引用母版外裁片' in r.json()['error']   # 未排料 = 未命中 demand


def test_restore_provenance_kind_invalid_400(client):
    """provenance.kind 非四值枚举 → 400；合法枚举 + config 宽松 → 200。"""
    msn = _save_msn(client)
    bad = _edit_msn(msn, lambda d: d['run'].__setitem__(
        'provenance', {'kind': 'magic', 'config': {'x': 1}}))
    r = _restore(client, bad)
    assert r.status_code == 400
    assert 'provenance.kind 非法' in r.json()['error']
    for kind in ('solve', 'strategy_se', 'strategy_race', 'extreme'):
        ok = _edit_msn(msn, lambda d, k=kind: d['run'].__setitem__(
            'provenance', {'kind': k, 'config': {'time_total_s': 600}}))
        rr = _restore(client, ok)
        assert rr.status_code == 200, (kind, rr.text)
        assert rr.json()['run']['provenance']['kind'] == kind


@pytest.mark.parametrize('fn, want', [
    (lambda d: d['doc'].pop('gate_mm'), 'gate_mm'),
    (lambda d: d['doc'].__setitem__('gate_mm', 0), 'gate_mm'),
    (lambda d: d['doc'].__setitem__('pieces', []), 'pieces 不能为空'),
    (lambda d: d.pop('doc', None), '缺少 doc'),
    (lambda d: d['doc']['pieces'][0].__setitem__('polygon', [[0, 0], [1, 1]]),
     'polygon'),
    (lambda d: d['doc']['pieces'][0]['polygon'][0].__setitem__(0, float('nan')),
     'polygon'),
    (lambda d: d['doc']['pieces'][1].__setitem__('pid', 'g01_30'), 'pid 重复'),
    (lambda d: d['doc']['pieces'][0].__setitem__('label', 'qianpian'), 'label'),
    (lambda d: d['doc']['pieces'][0].__setitem__('size', '30'), 'size'),
    (lambda d: d['doc']['pieces'][0].__setitem__('bbox', [0, 0, 1]), 'bbox'),
    (lambda d: d['doc']['pieces'][0].__setitem__('area_mm2', None), 'area_mm2'),
])
def test_restore_doc_block_garbage_400(client, fn, want):
    """doc 块逐片形态校验（gate/pieces/polygon 顶点数/NaN/pid 重复/label/size/
    bbox/area）→ 400 状态文件损坏。"""
    msn = _save_msn(client)
    r = _restore(client, _edit_msn(msn, fn))
    assert r.status_code == 400
    assert want in r.json()['error']


@pytest.mark.parametrize('fn, want', [
    (lambda d: d['run'].pop('placed'), 'placed 不能为空'),
    (lambda d: d['run']['placed'][0].pop('id'), 'id'),
    (lambda d: d['run']['placed'][0].__setitem__('rotation', 'flat'),
     'rotation 须为数值'),
    (lambda d: d['run']['placed'][0].__setitem__('translation', [1]),
     'translation'),
    (lambda d: d['run']['placed'][0].__setitem__('mirror', 'yes'), 'mirror'),
    (lambda d: d['run'].__setitem__('final', 3), 'final 须为对象'),
    (lambda d: d['run'].__setitem__('provenance', 'extreme'), 'provenance 须为对象'),
])
def test_restore_run_block_garbage_400(client, fn, want):
    """run 块逐条形态（placed 条目/rotation/translation/mirror/final/provenance）
    → 400 状态文件损坏。"""
    msn = _save_msn(client)
    r = _restore(client, _edit_msn(msn, fn))
    assert r.status_code == 400
    assert want in r.json()['error']


def test_restore_parse_runs_in_threadpool(client, monkeypatch):
    """AC#2：解析经 run_in_threadpool（不阻塞事件循环；白盒 spy）。"""
    import materialsorting.web.statefile as statefile_mod
    calls: list[str] = []
    orig = statefile_mod.run_in_threadpool

    async def _spy(func, *args, **kwargs):
        calls.append(getattr(func, '__name__', str(func)))
        return await orig(func, *args, **kwargs)

    monkeypatch.setattr(statefile_mod, 'run_in_threadpool', _spy)
    msn = _save_msn(client)
    r = _restore(client, msn)
    assert r.status_code == 200
    assert calls == ['parse_state_document']


def test_restore_extension_rejected_400(client):
    """扩展名 .dxf/.txt → 400「仅支持 .msn / .json」。"""
    msn = _save_msn(client)
    for name in ('master.dxf', 'state.txt'):
        r = _restore(client, msn, name=name)
        assert r.status_code == 400
        assert '仅支持' in r.json()['error']


# ---------------------------------------------------------------- AC3 会话语义

def test_restore_default_rebinds_runtime_no_disk_write(client):
    """AC#3：default 会话恢复 → runtime._PIECES_STATE 锁内原子重绑为新内容，
    且不镜像写 INTERMEDIATE、不落盘 uploads（字节不变断言）。"""
    from materialsorting import paths
    inter = Path(paths.INTERMEDIATE)
    uploads = Path(paths.OUT_DIR) / 'uploads'

    def _snap(root: Path) -> dict:
        if not root.exists():
            return {}
        return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
                for p in root.rglob('*') if p.is_file()}

    before_inter = inter.read_bytes() if inter.exists() else None
    before_uploads = _snap(uploads)
    msn = _save_msn(client)
    r = _restore(client, msn)
    assert r.status_code == 200
    assert (inter.read_bytes() if inter.exists() else None) == before_inter
    assert _snap(uploads) == before_uploads
    # 内存确实切换（default 会话 state 即 runtime._PIECES_STATE 同一 dict）
    st = sessions.registry.resolve(None)
    assert st.state is server_mod._PIECES_STATE
    assert st.state['doc']['doc_id'] == r.json()['doc_id']
    assert st.state['pieces_by_id'].keys() == {'g01_30', 'g02_30'}
    assert st.state['gate_mm'] == 1750.0


def test_restore_writes_current_sid_no_extra_slot(client):
    """AC#3：恢复写入当前 sid（覆盖旧 state/doc_id）；满员（MS_SESSION_MAX=4）
    时不占新名额 → 200 非 429（等价再 commit 语义）。"""
    reg = sessions.registry
    sids = [f'rstfull0{i}' for i in range(reg.max_sessions)]
    for s in sids:
        client.post('/api/session', headers={'X-Session-Id': s})
    r_new = client.post('/api/session', headers={'X-Session-Id': 'rstoverflow'})
    assert r_new.status_code == 429                # 名额已满：新 sid 被拒
    msn = _save_msn(client)
    r = _restore(client, msn, headers={'X-Session-Id': sids[0]})
    assert r.status_code == 200, r.text
    st = reg.peek(sids[0])
    assert st.state['doc']['doc_id'] == r.json()['doc_id']
    assert st.doc_id == r.json()['doc_id']
    assert st.state['pieces_by_id'].keys() == {'g01_30', 'g02_30'}


def test_restore_expired_sid_401(client, monkeypatch):
    """AC#3：过期 sid → 401 {code:'session_expired'}（FakeClock 惰性逐出；文件
    解析在前不建会话）。"""
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    sid = 'rstexp001'
    client.post('/api/session', headers={'X-Session-Id': sid})
    clk.advance(sessions.registry.ttl_sec + 1.0)
    msn = _save_msn(client)
    r = _restore(client, msn, headers={'X-Session-Id': sid})
    assert r.status_code == 401
    assert r.json()['code'] == 'session_expired'


def test_restore_invalid_sid_400(client):
    """AC#3：非法 sid → 400 {error:'sid 非法'}。"""
    msn = _save_msn(client)
    r = _restore(client, msn, headers={'X-Session-Id': 'bad-sid!'})
    assert r.status_code == 400
    assert r.json() == {'error': 'sid 非法'}


def test_restore_sid_isolation(client):
    """A 恢复不动 B：B 会话保持空（save 422）且 ptypes 降级空 representatives。"""
    sid_a, sid_b = 'rstisoA1', 'rstisoB1'
    for s in (sid_a, sid_b):
        client.post('/api/session', headers={'X-Session-Id': s})
    msn = _save_msn(client)
    r = _restore(client, msn, headers={'X-Session-Id': sid_a})
    assert r.status_code == 200
    r_b = client.post('/api/state-save', headers={'X-Session-Id': sid_b},
                      json={'form': _form(), 'quantities': _quantities()})
    assert r_b.status_code == 422                  # B 仍空会话
    rb = client.get('/api/ptypes', headers={'X-Session-Id': sid_b})
    assert rb.status_code == 200
    assert rb.json()['representatives'] == {}


# ---------------------------------------------------------------- AC3 端到端可用

def test_restore_then_ptypes_export_polish_e2e(client):
    """AC#3：恢复后该 sid 的 /api/ptypes、/export、/api/edit-polish 立即可用
    （label_representatives 透传、placed 守恒）。"""
    sid = 'rste2e001'
    client.post('/api/session', headers={'X-Session-Id': sid})
    msn = _save_msn(client)
    r = _restore(client, msn, headers={'X-Session-Id': sid})
    assert r.status_code == 200
    placed = r.json()['placed']

    rp = client.get('/api/ptypes', headers={'X-Session-Id': sid})
    assert rp.status_code == 200
    assert rp.json()['representatives'] == _doc()['label_representatives']

    re_ = client.post('/export', headers={'X-Session-Id': sid}, json={
        'fmt': 'dxf', 'sizes': [30], 'seed': 0, 'gate_mm': 1750.0,
        'width_mm': 2000.0, 'density': 0.5, 'placed': placed,
        'filename': '5336测试母版.dxf'})
    assert re_.status_code == 200, re_.text
    assert re_.headers['content-type'].startswith('application/dxf')

    rpol = client.post('/api/edit-polish', headers={'X-Session-Id': sid},
                       json={'placed': placed})
    assert rpol.status_code == 200, rpol.text
    body = rpol.json()
    assert body['ok'] is True
    assert Counter(p['id'] for p in body['placed']) == \
        Counter(p['id'] for p in placed)       # polish 出口守恒


# ---------------------------------------------------------------- AC4 链式传递

def test_restore_chain_second_round_identical(client):
    """AC#4：save→restore→save→restore 二次往返逐字段一致（模拟 A 改完传 B；
    doc_id 每次铸新、saved_at 时间戳不计）。"""
    msn1 = _save_msn(client)
    r1 = _restore(client, msn1)
    assert r1.status_code == 200
    msn2 = _save_msn(client)                   # 恢复会话上再保存
    r2 = _restore(client, msn2)
    assert r2.status_code == 200

    d1 = json.loads(gzip.decompress(msn1))
    d2 = json.loads(gzip.decompress(msn2))
    for k in ('form', 'quantities', 'run'):
        assert d1[k] == d2[k], k
    e1, e2 = dict(d1['doc']), dict(d2['doc'])
    assert e1.pop('doc_id') != e2.pop('doc_id')   # 每次恢复铸新文档身份
    assert e1 == e2                               # 几何/5 层逐字段一致
    j1, j2 = r1.json(), r2.json()
    assert j1['manifest'] == j2['manifest']
    assert j1['placed'] == j2['placed']
    assert j1['final'] == j2['final']
    p1, p2 = dict(j1['parse']), dict(j2['parse'])
    assert p1.pop('doc_id') != p2.pop('doc_id')
    assert p1 == p2                               # parse 载荷确定性重算


def test_restore_route_registered():
    """路由在场（register_statefile_routes 接线白盒）。"""
    route_paths = [getattr(rt, 'path', '') for rt in app.routes]
    assert '/api/state-restore' in route_paths and '/api/state-save' in route_paths
