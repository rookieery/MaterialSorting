"""US-011 腰头成带 WS 编排接线测试（TestClient 套路，镜像 test_ws_stop）。

覆盖（tasks/prd-waist-band.md US-011 验收标准）：
1. band 缺省/null/{}/非 dict/enabled falsy = 关闭：直接 manifest（无 stage），旧行为；
2. band 开启：WS 依序 stage → manifest（无 WB_）→ frames/final（placed 无 WB_、
   成员 pid 按 demand 出现 N 次 —— 副本守恒不变量）；
3. manifest 一致性：band on/off 的 total_area 与 pieces 列表逐字段一致；
4. 服务端校验：label 格式 / 不存在 / 数量全 0 / 硬警告形态无 ack → 结构化 error 早退；
   ack:true 放行；总副本 1 → worker 成带失败只投 error 不投 manifest；
5. band 阶段 stop：无存活 python 子进程（进程内线程化模型 —— terminate 不级联孙进程）；
6. build_instance exclude_labels 只跳 Item 层（pid_meta/total_area 不动，一致性单测）。

合成数据结构同 5336 g05（多码 × demand 2 矩形腰片）+ 硬警告形态 g06（30×559 裤耳类）。
band_runs 工件经 MS_OUT_DIR 随 spawn 传给子进程，落 tmp 可断言（US-014 回放对拍数据源）。
"""
from __future__ import annotations

import json
import multiprocessing
import os
import time
import zlib
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from materialsorting.web import server as server_mod
from materialsorting.web.server import app


def _piece(pid, label, size, w, h):
    """合成 v2 schema 裁片（矩形原轮廓，与 conftest _synthetic_pieces 同构）。"""
    return {
        'pid': pid, 'label': label, 'size': size,
        'polygon': [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]],
        'bbox': [0.0, 0.0, float(w), float(h)], 'area_mm2': float(w) * float(h),
        'n_verts': 4, 'allowed_angles': [0, 180],
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
    }


def _band_pieces():
    """合成母版：g05 两码 60×300 腰片（成带主角，最小边 60 / 长宽比 5 —— 无需 ack）、
    g01 普通大片、g06 30×559 裤耳类（最小边 30 < 60 → 硬警告形态）。"""
    return [
        _piece('g05_28', 'g05', 28, 60.0, 300.0),
        _piece('g05_29', 'g05', 29, 60.0, 300.0),
        _piece('g01_28', 'g01', 28, 400.0, 500.0),
        _piece('g06_28', 'g06', 28, 30.0, 559.0),
    ]


def _start(band=None, quantities=None, time_budget=60, seed=1):
    """最小合法 start payload（band=None 时整个键缺席 = 旧前端行为）。"""
    payload = {
        'action': 'start', 'sizes': [], 'time': time_budget, 'seed': seed,
        'params': {'d_ext': 0, 'd_int': 0, 'tol_ext': 0, 'tol_int': 0},
        'per_type': None, 'quantities': quantities,
    }
    if band is not None:
        payload['band'] = band
    return payload


def _drain_until_stopped(ws, timeout=15.0):
    """drain 消息直到 stopped（stop 后残余 frame 丢弃语义下 stopped 是最后一条）。"""
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        m = ws.receive_json()
        seen.append(m)
        if m.get('type') == 'stopped':
            return seen
    pytest.fail('stopped not received within deadline')


@pytest.fixture
def band_client(monkeypatch, tmp_path):
    """注入合成 pieces state + MS_OUT_DIR 隔离（子进程 band_runs 落 tmp，不污染 out/）。

    _PIECES_STATE 是 runtime 单例 dict —— 原位 clear+update（快照语义与 _reload 一致），
    teardown 恢复真实 state（test_ws_stop 等兄弟用例依赖真实 intermediate）。
    """
    monkeypatch.setenv('MS_OUT_DIR', str(tmp_path))
    pieces = _band_pieces()
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update({
        'doc': {'source': 'synthetic_band.dxf'},
        'gate_mm': 1980.0,
        'pieces': pieces,
        'pieces_by_id': {p['pid']: p for p in pieces},
    })
    with TestClient(app) as client:
        yield client
    state.clear()
    state.update(saved)


# --------------------------------------------- AC#1 band 关闭 = 旧行为


@pytest.mark.parametrize('band', [None, {}, 'notadict', {'enabled': False, 'label': 'g05'}])
def test_band_disabled_variants_receive_manifest_directly(band_client, band):
    """缺省/null-ish/{}/非 dict/enabled falsy → 关闭：首条即 manifest（无 stage 无 error）。"""
    with band_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(band=band, time_budget=60))
        m = ws.receive_json()
        assert m['type'] == 'manifest', f'band={band!r} 应视为关闭，收到 {m}'
        assert len(m['pieces']) == 4
        ws.send_json({'action': 'stop'})
        _drain_until_stopped(ws)


# --------------------------------------------- AC#2 band 开启全链路


def test_band_on_stage_manifest_final_conservation(band_client):
    """band 开启：stage → manifest（无 WB_）→ frames/final；成员 pid 按 demand 出现 N 次。"""
    with band_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(
            band={'enabled': True, 'label': 'g05', 'time_budget': 2},
            quantities={'g05': {'28': 2, '29': 2}}, time_budget=2))

        # 1) stage 在 manifest 前（FIFO 保证），字段齐全（FR-2）
        stage = ws.receive_json()
        assert stage['type'] == 'stage' and stage['stage'] == 'band'
        assert stage['fill_pct'] > 45.0
        assert stage['bbox']['width_mm'] > 0 and stage['bbox']['height_mm'] > 0
        assert stage['fallback'] is False and stage['elapsed'] >= 0

        # 2) manifest：无 WB_ 泄漏；g05 demand 透传
        manifest = ws.receive_json()
        assert manifest['type'] == 'manifest'
        pids = [p['id'] for p in manifest['pieces']]
        assert not any(str(pid).startswith('WB_') for pid in pids)
        demand = {p['id']: p['demand'] for p in manifest['pieces']}
        assert demand['g05_28'] == 2 and demand['g05_29'] == 2

        # 3) frames + final：无 WB_；末帧副本守恒（成员 pid 按 demand 出现 N 次）。
        #    WS final 消息契约不含 placed_items（前端以末帧为准，见 routes_ws.run_solve）。
        final = None
        last_frame = None
        deadline = time.time() + 40.0
        while time.time() < deadline:
            m = ws.receive_json()
            if m['type'] == 'frame':
                assert not any(pi['id'].startswith('WB_') for pi in m['placed_items'])
                last_frame = m
            elif m['type'] == 'final':
                final = m
                break
            elif m['type'] == 'error':
                pytest.fail(f'unexpected error: {m}')
        assert final is not None, 'final should arrive within deadline'
        assert last_frame is not None
        counts = {}
        for pi in last_frame['placed_items']:
            assert not pi['id'].startswith('WB_')
            counts[pi['id']] = counts.get(pi['id'], 0) + 1
        assert counts == {'g05_28': 2, 'g05_29': 2, 'g01_28': 1, 'g06_28': 1}

    # 4) band_runs 工件（US-014 回放对拍数据源；MS_OUT_DIR 随 spawn 传给子进程）
    band_dir = Path(os.environ['MS_OUT_DIR']) / 'band_runs'
    files = sorted(band_dir.glob('band_g05_seed1_*.json'))
    assert files, f'band artifact not written under {band_dir}'
    doc = json.loads(files[-1].read_text(encoding='utf-8'))
    assert doc['pid'] == 'WB_g05' and doc['label'] == 'g05'
    assert doc['main_seed'] == 1
    assert doc['seed'] == zlib.crc32(b'1|g05')     # crc32 派生（确定性回放口径）
    assert len(doc['members']) == 4                 # 成员带内位：2 码 × 2 副本
    assert doc['fill_pct'] > 45.0 and doc['band_elapsed'] > 0
    assert len(doc['polygon']) >= 3                 # 分块轮廓


# --------------------------------------------- AC#1 manifest 一致性（on vs off）


def test_manifest_consistency_band_on_vs_off(band_client):
    """band on/off：manifest total_area 与 pieces 列表逐字段一致（exclude_labels 只跳
    Item 层，pid_meta/total_area 原样 —— AC#1 一致性单测；manifest 后即 stop 提速）。"""
    manifests = {}
    for key, band in (('off', None),
                      ('on', {'enabled': True, 'label': 'g05', 'time_budget': 2})):
        with band_client.websocket_connect('/ws/solve') as ws:
            ws.send_json(_start(band=band,
                                quantities={'g05': {'28': 2, '29': 2}}, time_budget=60))
            if key == 'on':
                assert ws.receive_json()['type'] == 'stage'
            m = ws.receive_json()
            assert m['type'] == 'manifest'
            manifests[key] = m
            ws.send_json({'action': 'stop'})
            _drain_until_stopped(ws)
    assert manifests['off']['total_area_mm2'] == manifests['on']['total_area_mm2']
    assert manifests['off']['pieces'] == manifests['on']['pieces']   # dict list 深比较 = 逐字段
    assert manifests['off']['gate_nest_mm'] == manifests['on']['gate_nest_mm']


# --------------------------------------------- AC#3 服务端校验早退


@pytest.mark.parametrize('band,quantities,frag', [
    ({'enabled': True, 'label': 'x5'}, None, '须为 g 码'),
    ({'enabled': True, 'label': 5}, None, '须为 g 码'),
    ({'enabled': True, 'label': 'g99'}, None, '不存在于当前母版'),
    ({'enabled': True, 'label': 'g05'}, {'g05': {'28': 0, '29': 0}}, '数量全为 0'),
    ({'enabled': True, 'label': 'g06'}, {'g06': {'28': 2}}, 'ack'),
])
def test_band_validation_structured_error_early_exit(band_client, band, quantities, frag):
    """非法 band → 结构化 error 早退（无 manifest / 无 stage / WS 关闭）。"""
    with band_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(band=band, quantities=quantities, time_budget=60))
        msg = ws.receive_json()
        assert msg['type'] == 'error', f'expected error, got {msg}'
        assert frag in msg['message']
        with pytest.raises((WebSocketDisconnect, Exception)):
            ws.receive_json()


def test_band_ack_true_passes_hard_warning(band_client):
    """硬警告形态（g06 最小边 30<60）+ 显式 ack:true → 放行成带（stage 正常到达）。"""
    with band_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(
            band={'enabled': True, 'label': 'g06', 'ack': True, 'time_budget': 1},
            quantities={'g06': {'28': 2}}, time_budget=60))
        stage = ws.receive_json()
        assert stage['type'] == 'stage' and stage['stage'] == 'band'
        ws.send_json({'action': 'stop'})
        _drain_until_stopped(ws)


def test_band_degenerate_single_copy_worker_error(band_client):
    """总副本 1（DegenerateBand）→ worker 成带失败：只投 error 不投 manifest
    （与 build_instance 抛错同契约，test_solve_proc.py「manifest must NOT be sent」口径）。"""
    with band_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(
            band={'enabled': True, 'label': 'g06', 'ack': True},
            quantities={'g06': {'28': 1}}, time_budget=60))
        msg = ws.receive_json()
        assert msg['type'] == 'error', f'expected error, got {msg}'
        assert '成带失败' in msg['message'] and '总副本 1' in msg['message']


# --------------------------------------------- AC#4 band 阶段 stop 无孤儿


def _slow_arc_piece(pid, label, size, r_in=1550.0, thick=68.0, half_deg=19.0, n=24):
    """7 码 × 8 副本弧形腰片（5336 g05 真实几何族参数，凸侧 −X）—— v2 构造性
    链构造对 56 片 ~2s，给 stop 用例撑出确定性 terminate-during-band 窗口
    （紧凑版，完整口径见 test_waist_band._arc_piece）。"""
    import math

    r_out = r_in + thick
    pts = []
    for i in range(n + 1):          # 外弧（凸侧）180−half → 180+half
        a = math.radians(180.0 - half_deg + 2.0 * half_deg * i / n)
        pts.append([r_out * math.cos(a), r_out * math.sin(a)])
    for i in range(n + 1):          # 内弧（凹侧）180+half → 180−half
        a = math.radians(180.0 + half_deg - 2.0 * half_deg * i / n)
        pts.append([r_in * math.cos(a), r_in * math.sin(a)])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {
        'pid': pid, 'label': label, 'size': size, 'polygon': pts,
        'bbox': [min(xs), min(ys), max(xs), max(ys)],
        'area_mm2': 0.5 * abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                                  - pts[(i + 1) % len(pts)][0] * pts[i][1]
                                  for i in range(len(pts)))),
        'n_verts': len(pts), 'allowed_angles': [0, 180],
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
    }


def test_stop_during_band_stage_no_live_child(band_client):
    """band 阶段 stop：stopped 直达（无 manifest），无存活 python 子进程。

    v2 构造性链构造毫秒级（两码矩形 ~50ms，固定 sleep 停不进 band 窗口）——
    本用例换 7 码 × 8 副本弧形腰片撑出 ~2s band 构造窗口，stop 落在带构造
    中段。band 跑在 worker 进程内（同步调用，不 spawn 孙进程）—— terminate
    即随进程整体回收；若误用孙进程模型，本用例的子进程回收断言将留孤儿。
    """
    sizes = (28, 29, 30, 31, 33, 34, 35)
    arcs = [_slow_arc_piece(f'g05_{s}', 'g05', s) for s in sizes]
    state = server_mod._PIECES_STATE          # band_client 已存快照，teardown 恢复
    state['pieces'] = arcs
    state['pieces_by_id'] = {p['pid']: p for p in arcs}

    before = len(multiprocessing.active_children())
    with band_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(
            band={'enabled': True, 'label': 'g05', 'ack': True},   # 弧片长宽比 6.9>6 硬警告形态
            quantities={'g05': {str(s): 8 for s in sizes}}, time_budget=60))
        # worker spawn+import ≈0.6s、band 构造 ≈2s → 1.3s 落在带构造中段（±0.7s 余量）
        time.sleep(1.3)
        ws.send_json({'action': 'stop'})
        seen = _drain_until_stopped(ws)
        assert all(m.get('type') != 'manifest' for m in seen), (
            'band 阶段被 terminate，不应有 manifest 泄出')

    deadline = time.time() + 8.0
    while time.time() < deadline and len(multiprocessing.active_children()) > before:
        time.sleep(0.2)
    assert len(multiprocessing.active_children()) <= before, (
        f'band 阶段 stop 后仍有存活 python 子进程: '
        f'before={before}, after={len(multiprocessing.active_children())}')


# --------------------------------------------- AC#1 exclude_labels 单元口径


def test_build_instance_exclude_labels_item_layer_only():
    """exclude_labels 只跳 spyrrow Item：pid_meta / total_area 与不 exclude 逐字段一致
    （禁 quantities=0 移除 —— 那会连 pid_meta/total_area/manifest 一起抹掉）。"""
    from materialsorting.web.solver import build_instance

    pieces = _band_pieces()
    quantities = {'g05': {'28': 2, '29': 2}}
    args = dict(time_budget=1, seed=0, quantities=quantities)
    _i1, _c1, meta1, area1, _n1 = build_instance(pieces, 1980.0, **args)
    _i2, _c2, meta2, area2, _n2 = build_instance(
        pieces, 1980.0, exclude_labels={'g05'}, **args)

    ids1 = {it.id for it in _i1.items}
    ids2 = {it.id for it in _i2.items}
    assert {'g05_28', 'g05_29'} <= ids1
    assert not ids2 & {'g05_28', 'g05_29'}
    assert {'g01_28', 'g06_28'} <= ids2
    # 关键口径：pid_meta 与 total_area（= manifest 数据源）与 off 完全一致
    assert meta1 == meta2
    assert area1 == area2


def test_parse_band_time_budget_internal_knob():
    """_parse_band 内部旋钮：time_budget 非法值静默回退 None（= 默认 15s），不报错。"""
    from materialsorting.web.routes_ws import _parse_band

    pieces = _band_pieces()
    quantities = {'g05': {'28': 2, '29': 2}}
    cfg = _parse_band({'enabled': True, 'label': 'g05', 'time_budget': 'x'},
                      pieces, quantities)
    assert cfg == {'label': 'g05', 'time_budget': None}
    cfg2 = _parse_band({'enabled': True, 'label': 'g05', 'time_budget': 2},
                       pieces, quantities)
    assert cfg2 == {'label': 'g05', 'time_budget': 2}
    assert _parse_band(None, pieces, None) is None


# --------------------------------------------- US-013 POST /api/band/preview


def test_band_preview_ok(band_client):
    """US-013 AC#2 预演成功：200 {ok:true, fill_pct, bbox, elapsed, break_even}。"""
    r = band_client.post('/api/band/preview', json={
        'band': {'enabled': True, 'label': 'g05', 'time_budget': 2},
        'sizes': [], 'seed': 1,
        'quantities': {'g05': {'28': 2, '29': 2}}})
    assert r.status_code == 200
    data = r.json()
    assert data['ok'] is True
    assert data['fill_pct'] > 45.0
    assert data['bbox']['width_mm'] > 0 and data['bbox']['height_mm'] > 0
    # break-even 参考线随响应回传（前端对照展示同源，不前端硬编码两份）
    assert data['break_even'] == [62.4, 63.6]
    assert data['elapsed'] > 0


def test_band_preview_geometry_failure_ok_false(band_client):
    """几何失败（总副本 1 DegenerateBand）→ 200 {ok:false, error} —— 预演失败是
    结果数据（该 g 码不适合成带的量化证据），前端降级提示不阻塞确认（FR-7）。"""
    r = band_client.post('/api/band/preview', json={
        'band': {'enabled': True, 'label': 'g06', 'ack': True, 'time_budget': 1},
        'quantities': {'g06': {'28': 1}}})
    assert r.status_code == 200
    data = r.json()
    assert data['ok'] is False
    assert '总副本 1' in data['error']


@pytest.mark.parametrize('body,status,frag', [
    ({}, 400, 'band'),                                            # band 键缺席
    ({'band': {'enabled': False, 'label': 'g05'}}, 400, 'band'),  # enabled falsy
    ({'band': {'enabled': True, 'label': 'g99'}}, 422, '不存在于当前母版'),
    ({'band': {'enabled': True, 'label': 'g05'},
      'quantities': {'g05': {'28': 0, '29': 0}}}, 422, '数量全为 0'),
    ({'band': {'enabled': True, 'label': 'g06'},
      'quantities': {'g06': {'28': 2}}}, 422, 'ack'),             # 硬警告形态无 ack
])
def test_band_preview_structural_errors(band_client, body, status, frag):
    """结构错误：band 非法 → 400；校验失败（不存在 / 数量 0 / 需 ack）→ 422 {error}。"""
    r = band_client.post('/api/band/preview', json=body)
    assert r.status_code == status
    assert frag in r.json()['error']


def test_band_preview_hard_warning_structured_flag(band_client):
    """US-013 硬警告形态 422 附 ``hard_warning:true`` 结构化标记（区别于其它 422）——
    前端弹窗据此渲染二次确认勾选框；带 ``ack:true`` 重试即放行（成带预演成功口径）。"""
    r = band_client.post('/api/band/preview', json={
        'band': {'enabled': True, 'label': 'g06'},
        'quantities': {'g06': {'28': 2}}})
    assert r.status_code == 422
    data = r.json()
    assert data['hard_warning'] is True
    assert 'ack' in data['error']
    # 对照：其它 422（如 label 不存在）不带 hard_warning（形状键缺席，前端不误渲染勾选框）
    r2 = band_client.post('/api/band/preview', json={
        'band': {'enabled': True, 'label': 'g99'}})
    assert r2.status_code == 422
    assert 'hard_warning' not in r2.json()
    # ack 后重试放行（g06 最小边 30 硬警告 + ack → 预演走几何路径）
    r3 = band_client.post('/api/band/preview', json={
        'band': {'enabled': True, 'label': 'g06', 'ack': True, 'time_budget': 2},
        'quantities': {'g06': {'28': 4}}})
    assert r3.status_code == 200
    assert r3.json()['ok'] is True


def test_band_preview_empty_state_409(band_client):
    """pieces state 空（首次启动未 commit）→ 409（与 /ws/solve 空态报错同语义）。"""
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update({'doc': None, 'gate_mm': 0.0, 'pieces': [], 'pieces_by_id': {}})
    try:
        r = band_client.post('/api/band/preview', json={
            'band': {'enabled': True, 'label': 'g05'}})
        assert r.status_code == 409
        assert '排料数据为空' in r.json()['error']
    finally:
        state.clear()
        state.update(saved)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))

