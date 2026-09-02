"""US-003 起始端成套前后幅 WS 编排接线测试（TestClient 套路，镜像 test_waist_band_ws）。

覆盖（tasks/prd-prefix-head-set.md US-003 验收标准）：
1. prefix 缺省/null/{}/非 dict/enabled falsy = 关闭：直接 manifest（无 stage），旧行为；
2. prefix 开启：WS 依序 stage('prefix', size 回显) → manifest（无 PS_）→ frames/final
   （placed 无 PS_、4 成员 pid 各 2 条；同码其他码照排 = pid 级扣减语义）；
3. manifest 一致性：prefix on/off 的 total_area 与 pieces 列表逐字段一致；
4. 服务端校验 _parse_prefix：front/back 格式 / 不存在 / front==back / 无资格码
   （demand 1、demand 3、quantities=null 全 demand=1）→ 结构化 error 早退；
5. 双开（band+prefix）：stage 两条（band→prefix→manifest）互不干扰，final 统计段
   带位记录（WB 世界 bbox + 距布尾）在案、布局不动（不置换）；单开各自行为与无
   对方时完全一致（band 单开无 prefix 键、prefix 单开 band_pos=None）；
6. final 置换挂钩 + prefix_runs 工件（solve_with_callback_proc 进程级：无 PS_ 泄漏、
   pin stats 结构、工件落 MS_OUT_DIR 隔离目录、stage size == final size == 工件 size）；
7. build_instance exclude_pids 只跳 Item 层（pid_meta/total_area 不动，一致性单测）；
8. 2026-09-02 异码补片（US-002 接线）：exclude_pids Mapping 双形态单测（部分扣减 /
   过量扣减 / Counter≡集合等价）；兜底 4 片形态 stage/final 新键（fallback=True、
   extra_label=None）；5 片形态全链路（gate 2100 下确定性选码 A=28+顶部 g03_29，
   stage 新键透传、placed 守恒 = 全量 Σdemand、PS_ 哨兵、工件 5 成员回显）。

合成数据结构同 5336（前后幅 g 码 + 2+2 数量矩阵）：g02/g03 两码 28/29 均 2+2
（资格码 {28,29}）、g01 普通大片、g05 腰片（双开用例的 band 主角，60x300 矩形）。
矩形竖排高手算：4 片基座 = 400+420+400+420 = 1640mm —— gate 1980 下任何 5 片
组合（≥1640+400）竖排超高 ⇒ 必兜底；gate 2100 下最大 H = 1640+420(g03) = 2060
⇒ 确定性选定 套装@28 + 顶部 g03_29（residual 40mm）。
"""
from __future__ import annotations

import json
import time

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


def _prefix_pieces(with_band: bool = False):
    """合成母版：g02/g03 前后幅两码（2+2 资格码 {28,29}）、g01 普通大片、g05 腰片。"""
    pieces = [
        _piece('g02_28', 'g02', 28, 300.0, 400.0),
        _piece('g03_28', 'g03', 28, 320.0, 420.0),
        _piece('g02_29', 'g02', 29, 300.0, 400.0),
        _piece('g03_29', 'g03', 29, 320.0, 420.0),
        _piece('g01_28', 'g01', 28, 400.0, 500.0),
    ]
    if with_band:
        pieces += [_piece('g05_28', 'g05', 28, 60.0, 300.0),
                   _piece('g05_29', 'g05', 29, 60.0, 300.0)]
    return pieces


# 数量矩阵：28/29 两码 2+2（资格码集合恰 {28,29}）；g01 单片；g05 双开时 2+2。
_QTY = {'g02': {'28': 2, '29': 2}, 'g03': {'28': 2, '29': 2}, 'g01': {'28': 1}}
_QTY_BAND = {**_QTY, 'g05': {'28': 2, '29': 2}}


def _start(prefix=None, band=None, quantities=_QTY, time_budget=60, seed=1):
    """最小合法 start payload（prefix=None 时整个键缺席 = 旧前端行为）。"""
    payload = {
        'action': 'start', 'sizes': [], 'time': time_budget, 'seed': seed,
        'params': {'d_ext': 0, 'd_int': 0, 'tol_ext': 0, 'tol_int': 0},
        'per_type': None, 'quantities': quantities,
    }
    if prefix is not None:
        payload['prefix'] = prefix
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
def prefix_client(monkeypatch):
    """注入合成 pieces state（_PIECES_STATE 是 runtime 单例 dict —— 原位
    clear+update，teardown 恢复真实 state（test_ws_stop 等兄弟用例依赖真实
    intermediate）。"""
    pieces = _prefix_pieces()
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update({
        'doc': {'source': 'synthetic_prefix.dxf'},
        'gate_mm': 1980.0,
        'pieces': pieces,
        'pieces_by_id': {p['pid']: p for p in pieces},
    })
    with TestClient(app) as client:
        yield client
    state.clear()
    state.update(saved)


# --------------------------------------------- AC#1 prefix 关闭 = 旧行为


@pytest.mark.parametrize('prefix', [None, {}, 'notadict', {'enabled': False, 'front': 'g02'}])
def test_prefix_disabled_variants_receive_manifest_directly(prefix_client, prefix):
    """缺省/null-ish/{}/非 dict/enabled falsy -> 关闭：首条即 manifest（无 stage 无 error）。"""
    with prefix_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(prefix=prefix, time_budget=60))
        m = ws.receive_json()
        assert m['type'] == 'manifest', f'prefix={prefix!r} 应视为关闭，收到 {m}'
        assert len(m['pieces']) == 5
        ws.send_json({'action': 'stop'})
        _drain_until_stopped(ws)


def test_final_message_has_no_prefix_key_when_off(prefix_client):
    """prefix 关闭：final 消息无 prefix 键（旧契约逐字段不变；manifest 后即 stop 提速）。"""
    with prefix_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(prefix=None, time_budget=60))
        assert ws.receive_json()['type'] == 'manifest'
        ws.send_json({'action': 'stop'})
        seen = _drain_until_stopped(ws)
    assert all('prefix' not in m for m in seen if m.get('type') == 'final')


# --------------------------------------------- AC#2 prefix 开启全链路


def test_prefix_on_stage_manifest_final_conservation(prefix_client):
    """prefix 开启：stage('prefix', size 回显) -> manifest（无 PS_）-> frames/final。

    守恒（pid 级扣减语义）：选取码两 pid 由组合片展开恰各 2 条；同码其他码
    （29）照排各 2 条；g01 单条 —— 与选取哪个资格码无关。"""
    with prefix_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(prefix={'enabled': True, 'front': 'g02', 'back': 'g03'},
                            time_budget=2))

        # 1) stage 在 manifest 前（FIFO 保证），size 回显选中资格码（FR-2）
        stage = ws.receive_json()
        assert stage['type'] == 'stage' and stage['stage'] == 'prefix'
        assert stage['size'] in (28, 29)
        assert stage['fill_pct'] > 0
        assert stage['bbox']['width_mm'] > 0 and stage['bbox']['height_mm'] > 0
        assert stage['holes'] >= 0 and stage['elapsed'] >= 0

        # 2) manifest：无 PS_ 泄漏；g02/g03 demand 透传（Item 层扣减不动 manifest）
        manifest = ws.receive_json()
        assert manifest['type'] == 'manifest'
        pids = [p['id'] for p in manifest['pieces']]
        assert not any(str(pid).startswith('PS_') for pid in pids)
        demand = {p['id']: p['demand'] for p in manifest['pieces']}
        assert demand['g02_28'] == 2 and demand['g03_28'] == 2
        assert demand['g02_29'] == 2 and demand['g03_29'] == 2

        # 3) frames + final：无 PS_；末帧副本守恒；final 统计段 size 与 stage 一致
        final = None
        last_frame = None
        deadline = time.time() + 40.0
        while time.time() < deadline:
            m = ws.receive_json()
            if m['type'] == 'frame':
                assert not any(pi['id'].startswith('PS_') for pi in m['placed_items'])
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
            assert not pi['id'].startswith('PS_')
            counts[pi['id']] = counts.get(pi['id'], 0) + 1
        assert counts == {'g02_28': 2, 'g03_28': 2, 'g02_29': 2, 'g03_29': 2,
                          'g01_28': 1}
        # final 统计段（US-003）：size 回显 + pin stats + band_pos（单开 = None）
        assert final['prefix']['size'] == stage['size']
        assert 'skipped' in final['prefix']['pin']
        assert final['prefix']['band_pos'] is None


# --------------------------------------------- AC#1 manifest 一致性（on vs off）


def test_manifest_consistency_prefix_on_vs_off(prefix_client):
    """prefix on/off：manifest total_area 与 pieces 列表逐字段一致（exclude_pids 只跳
    Item 层，pid_meta/total_area 原样 —— AC#1 一致性单测）。"""
    manifests = {}
    for key, prefix in (('off', None), ('on', {'enabled': True, 'front': 'g02',
                                               'back': 'g03'})):
        with prefix_client.websocket_connect('/ws/solve') as ws:
            ws.send_json(_start(prefix=prefix, time_budget=60))
            if key == 'on':
                assert ws.receive_json()['type'] == 'stage'
            m = ws.receive_json()
            assert m['type'] == 'manifest'
            manifests[key] = m
            ws.send_json({'action': 'stop'})
            _drain_until_stopped(ws)
    assert manifests['off']['total_area_mm2'] == manifests['on']['total_area_mm2']
    assert manifests['off']['pieces'] == manifests['on']['pieces']   # dict list 深比较 = 逐字段
    # 2026-08-28 起 gate_nest_mm 字段已删（输入幅宽 = 实际幅宽单一口径）
    assert 'gate_nest_mm' not in manifests['off']
    assert 'gate_nest_mm' not in manifests['on']


# --------------------------------------------- AC#3 服务端校验早退


@pytest.mark.parametrize('prefix,quantities,frag', [
    ({'enabled': True, 'front': 'x2', 'back': 'g03'}, None, '须为 g 码'),
    ({'enabled': True, 'front': 'g02', 'back': 5}, None, '须为 g 码'),
    ({'enabled': True, 'front': 'g99', 'back': 'g03'}, None, '不存在于当前母版'),
    ({'enabled': True, 'front': 'g02', 'back': 'g02'}, None, '不同 g 码'),
    # demand 1（前幅全码单片）-> 无资格码
    ({'enabled': True, 'front': 'g02', 'back': 'g03'},
     {'g02': {'28': 1, '29': 1}, 'g03': {'28': 2, '29': 2}}, '2+2 资格码'),
    # demand 3（后幅全码 3 片，版师 P2「总量 6 片的码不行」）-> 无资格码
    ({'enabled': True, 'front': 'g02', 'back': 'g03'},
     {'g02': {'28': 2, '29': 2}, 'g03': {'28': 3, '29': 3}}, '2+2 资格码'),
    # quantities=null 全 demand=1 -> 无任何 2+2 资格码（FR-9：非静默关闭）
    ({'enabled': True, 'front': 'g02', 'back': 'g03'}, None, '2+2 资格码'),
])
def test_prefix_validation_structured_error_early_exit(prefix_client, prefix, quantities,
                                                       frag):
    """非法 prefix -> 结构化 error 早退（无 manifest / 无 stage / WS 关闭）。"""
    with prefix_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(prefix=prefix, quantities=quantities, time_budget=60))
        msg = ws.receive_json()
        assert msg['type'] == 'error', f'expected error, got {msg}'
        assert frag in msg['message']
        with pytest.raises((WebSocketDisconnect, Exception)):
            ws.receive_json()


def test_parse_prefix_returns_front_back_only():
    """合法 prefix -> {'front','back'}（无 size 键 —— 资格码后端选取；多余键如
    size 静默忽略、不报错）；关闭变体 -> None。"""
    from materialsorting.web.routes_ws import _parse_prefix

    pieces = _prefix_pieces()
    quantities = _QTY
    cfg = _parse_prefix({'enabled': True, 'front': 'g02', 'back': 'g03',
                         'size': 28, 'time_budget': 2}, pieces, quantities)
    assert cfg == {'front': 'g02', 'back': 'g03'}
    assert _parse_prefix(None, pieces, None) is None
    assert _parse_prefix({}, pieces, None) is None
    assert _parse_prefix({'enabled': False, 'front': 'g02', 'back': 'g03'},
                         pieces, quantities) is None


def test_parse_prefix_eligibility_respects_sizes_filter():
    """资格码口径含 sizes 过滤（用户所排尺码）：唯一资格码被 sizes 滤掉 ->
    结构化 error（资格码必须真实进主解实例，eligible_sizes 同口径）。"""
    from materialsorting.web.routes_ws import _parse_prefix

    pieces = _prefix_pieces()
    quantities = {'g02': {'28': 2}, 'g03': {'28': 2}}     # 唯一资格码 28
    assert _parse_prefix({'enabled': True, 'front': 'g02', 'back': 'g03'},
                         pieces, quantities, sizes=[28]) == {'front': 'g02', 'back': 'g03'}
    with pytest.raises(ValueError, match=r'2\+2 资格码'):
        _parse_prefix({'enabled': True, 'front': 'g02', 'back': 'g03'},
                      pieces, quantities, sizes=[29])


def test_prefix_sizes_filtered_no_eligible_early_exit(prefix_client):
    """sizes=[29] 排掉唯一资格码 28 -> 服务端资格码校验早退（worker 第二道网
    之前的结构化 error，无 manifest）。"""
    with prefix_client.websocket_connect('/ws/solve') as ws:
        payload = _start(prefix={'enabled': True, 'front': 'g02', 'back': 'g03'},
                         quantities={'g02': {'28': 2}, 'g03': {'28': 2}})
        payload['sizes'] = [29]
        ws.send_json(payload)
        msg = ws.receive_json()
        assert msg['type'] == 'error', f'expected error, got {msg}'
        assert '2+2 资格码' in msg['message']


def test_prefix_worker_error_no_manifest(prefix_client):
    """worker 前缀构造失败 -> 只投 error 不投 manifest（band 同契约，AC#4）。

    触发（服务端校验与构造期的事实源差异）：quantities 声明 g02/g03 码 30 为
    2+2 资格（服务端 eligible_sizes 只看数量矩阵 -> 放行），但母版无 g02_30/
    g03_30 裁片（pid_meta 无条目）-> build_prefix_plan 副本不齐 PrefixError，
    worker 早退「前缀构造失败」error，无 stage 后续、无 manifest。"""
    with prefix_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(
            prefix={'enabled': True, 'front': 'g02', 'back': 'g03'},
            quantities={'g02': {'28': 1, '30': 2}, 'g03': {'28': 1, '30': 2},
                        'g01': {'28': 1}},
            time_budget=60))
        msg = ws.receive_json()
        assert msg['type'] == 'error', f'expected error, got {msg}'
        assert '前缀构造失败' in msg['message']
        assert '2+2' in msg['message']

# --------------------------------------------- AC#5 双开带位记录（FR-8）


def test_dual_open_band_prefix_stages_and_band_pos(prefix_client):
    """双开：stage band -> stage prefix -> manifest（无 WB_/PS_）；final 带位记录在案。

    决策④（2026-08-25 拍板）：WB 世界 bbox（min_x/max_x/距布尾）只记录不置换，
    布局不动；单开变体见下方两条用例。"""
    pieces = _prefix_pieces(with_band=True)
    state = server_mod._PIECES_STATE          # prefix_client 已存快照，teardown 恢复
    state['pieces'] = pieces
    state['pieces_by_id'] = {p['pid']: p for p in pieces}

    with prefix_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(prefix={'enabled': True, 'front': 'g02', 'back': 'g03'},
                            band={'enabled': True, 'label': 'g05'},
                            quantities=_QTY_BAND, time_budget=2))
        # 双开 stage 序：band -> prefix（manifest 前各唯一一次）
        s1 = ws.receive_json()
        assert s1['type'] == 'stage' and s1['stage'] == 'band'
        s2 = ws.receive_json()
        assert s2['type'] == 'stage' and s2['stage'] == 'prefix'
        assert s2['size'] in (28, 29)
        # manifest：WB_/PS_ 互不干扰（双组合片各自展开，双双零泄漏）
        manifest = ws.receive_json()
        assert manifest['type'] == 'manifest'
        pids = [p['id'] for p in manifest['pieces']]
        assert not any(str(pid).startswith(('WB_', 'PS_')) for pid in pids)

        final = None
        deadline = time.time() + 40.0
        while time.time() < deadline:
            m = ws.receive_json()
            if m['type'] == 'final':
                final = m
                break
            if m['type'] == 'error':
                pytest.fail(f'unexpected error: {m}')
            if m['type'] == 'frame':
                assert not any(pi['id'].startswith(('WB_', 'PS_'))
                               for pi in m['placed_items'])
        assert final is not None
        # 带位记录（FR-8）：双开时在案；pid/区间/距布尾结构齐全
        bp = final['prefix']['band_pos']
        assert bp is not None, '双开时 final 统计段应记录带位'
        assert bp['pid'].startswith('WB_')
        assert bp['min_x'] <= bp['max_x']
        assert bp['dist_to_tail_mm'] >= -1.0     # 距布尾 = width - max_x（容差兜底）


def test_band_solo_final_has_no_prefix_section(prefix_client):
    """band 单开：final 无 prefix 键（与无 prefix 时行为完全一致）。"""
    pieces = _prefix_pieces(with_band=True)
    state = server_mod._PIECES_STATE
    state['pieces'] = pieces
    state['pieces_by_id'] = {p['pid']: p for p in pieces}
    with prefix_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(band={'enabled': True, 'label': 'g05'},
                            quantities=_QTY_BAND, time_budget=2))
        assert ws.receive_json()['type'] == 'stage'      # band stage
        assert ws.receive_json()['type'] == 'manifest'
        final = None
        deadline = time.time() + 40.0
        while time.time() < deadline:
            m = ws.receive_json()
            if m['type'] == 'final':
                final = m
                break
            if m['type'] == 'error':
                pytest.fail(f'unexpected error: {m}')
        assert final is not None
        assert 'prefix' not in final


def test_prefix_solo_band_pos_is_none(prefix_client):
    """prefix 单开：final 统计段 band_pos=None（无 band 时无带位可记）。"""
    with prefix_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(prefix={'enabled': True, 'front': 'g02', 'back': 'g03'},
                            time_budget=2))
        assert ws.receive_json()['type'] == 'stage'
        assert ws.receive_json()['type'] == 'manifest'
        final = None
        deadline = time.time() + 40.0
        while time.time() < deadline:
            m = ws.receive_json()
            if m['type'] == 'final':
                final = m
                break
            if m['type'] == 'error':
                pytest.fail(f'unexpected error: {m}')
        assert final is not None
        assert final['prefix']['band_pos'] is None


# --------------------------------------------- AC#1 exclude_pids 单元口径


def test_build_instance_exclude_pids_item_layer_only():
    """exclude_pids 只跳 spyrrow Item：pid_meta / total_area 与不 exclude 逐字段一致
    （pid 级语义：同 label 其他码照排；对照 exclude_labels 会连整码全丢）。"""
    from materialsorting.web.solver import build_instance

    pieces = _prefix_pieces()
    quantities = _QTY
    args = dict(time_budget=1, seed=0, quantities=quantities)
    _i1, _c1, meta1, area1, _n1 = build_instance(pieces, 1980.0, **args)
    _i2, _c2, meta2, area2, _n2 = build_instance(
        pieces, 1980.0, exclude_pids={'g02_28', 'g03_28'}, **args)

    ids1 = {it.id for it in _i1.items}
    ids2 = {it.id for it in _i2.items}
    assert {'g02_28', 'g03_28'} <= ids1
    assert not ids2 & {'g02_28', 'g03_28'}
    # pid 级关键口径：同 g 码其他码（29）照排（label 级会连 g02_29/g03_29 一起丢）
    assert {'g02_29', 'g03_29', 'g01_28'} <= ids2
    # manifest 数据源（pid_meta/total_area）与 off 完全一致
    assert meta1 == meta2
    assert area1 == area2


# -------------------------- AC#4 final 置换挂钩 + prefix_runs 工件（进程级）


def test_proc_prefix_final_no_leak_pin_stats_and_artifact(tmp_path, monkeypatch):
    """solve_with_callback_proc 进程级：final placed_items 无 PS_、4 成员 2+2；
    pin stats 在案（未跳过未回退 => 前缀成员 min_x <= 6mm）；prefix_runs 工件落
    MS_OUT_DIR 隔离目录，stage size == final size == 工件 size 同跑一致。"""
    from materialsorting.web.solver import solve_with_callback_proc

    # 工件隔离：子进程 spawn 继承 env -> paths.OUT_DIR/PREFIX_RUNS_DIR 落 tmp
    monkeypatch.setenv('MS_OUT_DIR', str(tmp_path))
    pieces = _prefix_pieces()

    stages = []
    proc, final, elapsed, err = solve_with_callback_proc(
        pieces, 1980.0,
        {'time_budget': 2, 'seed': 0, 'quantities': _QTY},
        on_manifest=lambda m: None, on_report=lambda r: None,
        on_stage=stages.append,
        prefix={'front': 'g02', 'back': 'g03'},
    )
    assert err is None, f'unexpected error: {err}'
    assert final is not None

    # stage：prefix 唯一一次，size 回显
    assert len(stages) == 1 and stages[0]['stage'] == 'prefix'
    size = stages[0]['size']

    # final：无 PS_；选取码 4 成员（2+2 同码）；同码其他码照排
    ids = [pi['id'] for pi in final['placed_items']]
    assert not any(str(i).startswith('PS_') for i in ids)
    counts = {}
    for i in ids:
        counts[i] = counts.get(i, 0) + 1
    assert counts == {'g02_28': 2, 'g03_28': 2, 'g02_29': 2, 'g03_29': 2, 'g01_28': 1}

    # final 统计段：size 与 stage 一致；pin stats 结构（skip/回退二态语义字段在案）
    assert final['prefix']['size'] == size
    pin = final['prefix']['pin']
    assert isinstance(pin['skipped'], bool)
    assert isinstance(pin['rolled_back'], bool)

    # 置换挂钩守卫（FR-7）：未跳过且未回退 => 前缀成员 min_x <= 6mm
    if not pin['skipped'] and not pin['rolled_back']:
        from materialsorting.nesting_engine.sparrow_baseline import _transform_polygon
        members = [pi for pi in final['placed_items']
                   if pi['id'] in (f'g02_{size}', f'g03_{size}')]
        assert len(members) == 4
        poly_by_pid = {p['pid']: p['polygon'] for p in pieces}
        min_x = min(min(x for x, _y in _transform_polygon(
            poly_by_pid[pi['id']], pi['rotation'], pi['translation']))
            for pi in members)
        assert min_x <= 6.5, f'置换后前缀成员 min_x={min_x:.2f}mm > 6mm'

    # prefix_runs 工件（US-005 回放对拍数据源）：落盘在案 + size/构造全量一致
    run_dir = tmp_path / 'prefix_runs'
    files = list(run_dir.glob('*.json')) if run_dir.exists() else []
    assert files, f'prefix_runs 工件应写入 {run_dir}'
    art = json.loads(files[0].read_text(encoding='utf-8'))
    assert art['size'] == size
    assert art['pid'].startswith('PS_')
    assert len(art['chunk']['members']) == 4
    assert 'pin' in art and art['band_pos'] is None
    assert art['chunk']['members'][0]['pid'] == f'g02_{size}'


# --------------------- 2026-09-02 异码补片（US-002 demand 部分扣减 + 接线）


def test_build_instance_exclude_pids_mapping_partial_deduction():
    """exclude_pids Mapping 形态：每 pid 扣 n 份（Item demand = demand−n，≤0 跳过）；
    pid_meta/total_area 与不扣减逐字段一致（manifest 口径事故防线）；4 片 Counter
    （2+2 全扣）与现行集合跳过等价（US-002 验收第 2 条前半）。"""
    from collections import Counter

    from materialsorting.web.solver import build_instance

    pieces = _prefix_pieces()
    args = dict(time_budget=1, seed=0, quantities=_QTY)
    _i0, _c0, meta0, area0, _n0 = build_instance(pieces, 1980.0, **args)

    # Mapping：g02_28 扣 1（demand 2→1 余量照排）、g03_28 扣 2（→0 跳过）
    _i1, _c1, meta1, area1, _n1 = build_instance(
        pieces, 1980.0, exclude_pids={'g02_28': 1, 'g03_28': 2}, **args)
    dem = {it.id: it.demand for it in _i1.items}
    assert dem['g02_28'] == 1
    assert 'g03_28' not in dem
    assert dem['g02_29'] == 2 and dem['g03_29'] == 2 and dem['g01_28'] == 1
    # manifest 数据源（pid_meta/total_area）与不扣减逐字段一致
    assert meta1 == meta0
    assert area1 == area0

    # 过量扣减（n > demand）→ demand−n ≤ 0 跳过（不 clamp 出负 demand）
    _i2, _c2, meta2, area2, _n2 = build_instance(
        pieces, 1980.0, exclude_pids={'g02_28': 5}, **args)
    assert 'g02_28' not in {it.id for it in _i2.items}
    assert meta2 == meta0 and area2 == area0

    # 4 牔 Counter（成员计数全扣）与现行集合跳过等价：Item (id, demand) 全等
    _i3, _c3, _m3, _a3, _n3 = build_instance(
        pieces, 1980.0, exclude_pids=Counter({'g02_28': 2, 'g03_28': 2}), **args)
    _i4, _c4, _m4, _a4, _n4 = build_instance(
        pieces, 1980.0, exclude_pids={'g02_28', 'g03_28'}, **args)
    assert {it.id: it.demand for it in _i3.items} == \
        {it.id: it.demand for it in _i4.items}


def test_prefix_fallback_stage_and_final_new_keys(prefix_client):
    """兜底 4 片形态（gate 1980 下任一 5 片组合竖排超高）：stage/final additive
    新键在案 —— fallback=True、extra_label/extra_size=None、residual_mm =
    gate − 基座高（1980−1640=340）。"""
    with prefix_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(prefix={'enabled': True, 'front': 'g02', 'back': 'g03'},
                            time_budget=2))
        stage = ws.receive_json()
        assert stage['type'] == 'stage' and stage['stage'] == 'prefix'
        assert stage['fallback'] is True
        assert stage['extra_label'] is None and stage['extra_size'] is None
        assert stage['residual_mm'] == pytest.approx(340.0, abs=1.0)
        assert ws.receive_json()['type'] == 'manifest'

        final = None
        deadline = time.time() + 40.0
        while time.time() < deadline:
            m = ws.receive_json()
            if m['type'] == 'final':
                final = m
                break
            if m['type'] == 'error':
                pytest.fail(f'unexpected error: {m}')
        assert final is not None
        assert final['prefix']['fallback'] is True
        assert final['prefix']['extra'] is None
        assert final['prefix']['residual_mm'] == pytest.approx(340.0, abs=1.0)


def test_prefix_extra_piece_stage_final_conservation(prefix_client, monkeypatch,
                                                      tmp_path):
    """5 片组合片全链路（gate 2100 使异码补片可行）：stage 回显选定组合
    （fallback=False、extra_label/extra_size/residual_mm）、placed 守恒 = 全量
    Σdemand（异码 pid 扣 1 份余量照排：g03_29 = 主解 1 + 组合片展开 1）、
    manifest/frame/final 无 PS_（哨兵）、prefix_runs 工件 5 成员 + 组合三键回显。"""
    monkeypatch.setenv('MS_OUT_DIR', str(tmp_path))   # 工件隔离（spawn 子进程继承 env）
    state = server_mod._PIECES_STATE
    state['gate_mm'] = 2100.0     # 1640(基座)+420(g03 补片)=2060 ≤ 2100；1980 下必兜底
    try:
        with prefix_client.websocket_connect('/ws/solve') as ws:
            ws.send_json(_start(prefix={'enabled': True, 'front': 'g02', 'back': 'g03'},
                                time_budget=2))
            # stage：确定性选码（搜索无 RNG、与 seed 无关）—— 套装@28 + 顶部
            # g03_29（H=2060 为全部 8 组合中最大），residual = 2100−2060 = 40
            stage = ws.receive_json()
            assert stage['type'] == 'stage' and stage['stage'] == 'prefix'
            assert stage['size'] == 28
            assert stage['fallback'] is False
            assert stage['extra_label'] == 'g03' and stage['extra_size'] == 29
            assert stage['residual_mm'] == pytest.approx(40.0, abs=1.0)

            # manifest：无 PS_ 泄漏；demand 全量透传（Item 层扣减不动 manifest）
            manifest = ws.receive_json()
            assert manifest['type'] == 'manifest'
            assert not any(str(p['id']).startswith('PS_') for p in manifest['pieces'])
            demand = {p['id']: p['demand'] for p in manifest['pieces']}
            assert demand == {'g02_28': 2, 'g03_28': 2, 'g02_29': 2, 'g03_29': 2,
                              'g01_28': 1}

            final = None
            last_frame = None
            deadline = time.time() + 40.0
            while time.time() < deadline:
                m = ws.receive_json()
                if m['type'] == 'frame':
                    assert not any(pi['id'].startswith('PS_') for pi in m['placed_items'])
                    last_frame = m
                elif m['type'] == 'final':
                    final = m
                    break
                elif m['type'] == 'error':
                    pytest.fail(f'unexpected error: {m}')
            assert final is not None and last_frame is not None

            # placed 守恒 = 全量 Σdemand（9 条，末帧口径 —— WS final 消息不带
            # placed_items）：基座两 pid demand 2−2=0 全由组合片承载；异码
            # g03_29 主解排 2−1=1 + 组合片展开 1
            placed = last_frame['placed_items']
            assert not any(pi['id'].startswith('PS_') for pi in placed)
            counts = {}
            for pi in placed:
                counts[pi['id']] = counts.get(pi['id'], 0) + 1
            assert counts == {'g02_28': 2, 'g03_28': 2, 'g02_29': 2,
                              'g03_29': 2, 'g01_28': 1}
            assert len(placed) == sum(demand.values()) == 9

            # final 统计段回显选定组合（extra dict + residual_mm + fallback）
            fp = final['prefix']
            assert fp['size'] == 28 and fp['fallback'] is False
            assert fp['pid'].startswith('PS_') and '+g03@29' in fp['pid']
            assert fp['extra']['pid'] == 'g03_29'
            assert fp['extra']['label'] == 'g03' and fp['extra']['size'] == 29
            assert fp['residual_mm'] == pytest.approx(40.0, abs=1.0)

        # prefix_runs 工件（US-005 回放数据源）：5 成员 + 组合三键回显
        run_dir = tmp_path / 'prefix_runs'
        files = list(run_dir.glob('*.json')) if run_dir.exists() else []
        assert files, f'prefix_runs 工件应写入 {run_dir}'
        art = json.loads(files[0].read_text(encoding='utf-8'))
        assert len(art['chunk']['members']) == 5
        assert art['size'] == 28
        assert art['fallback'] is False and art['extra']['pid'] == 'g03_29'
        assert art['residual_mm'] == pytest.approx(40.0, abs=1.0)
    finally:
        state['gate_mm'] = 1980.0   # fixture teardown 亦恢复；防御性双保险


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
