"""WS /ws/solve initial 键热启动接线测试（prd-initial-layout US-003，TestClient）。

镜像 test_web_key_routes WS 闸门套路：monkeypatch ``routes_ws.solve_with_callback_proc``
（模块级 from-import 绑定 = 调用点名字）注入伪 proc 收调用形态（**initial_solution
kwargs 透传断言**），不跑真求解；能力探测经 monkeypatch ``warmstart.
warm_start_supported`` 打桩（build_warm_payload 调用时取模块属性 → 桩生效），
PyPI 0.9.0 / ms0 装载态同样全绿。

覆盖（三路验收口径）：
1. **透传**：plain happy path（initial_solution == build_warm_payload 载荷形态，
   strip_width/顺序/条目锁）+ plain 时载荷 demand_map 被忽略（pid_meta 投影才是
   宇宙 —— 若采用会在装载点 count mismatch 降级，成功即证明忽略）+ band 开组合
   宇宙 demand_map 直用（WB_ 原样进载荷 = 投影未被采用）+ worker final warm_state
   原样转发（engaged True / worker 降级 token 两种）；
2. **降级**：unsupported / 完整解硬约束 / pid 需求映射外 / initial 非对象 /
   placed 非列表 / band 开缺 demand_map（WB_ 落 plain 投影外）→ initial_solution
   恒 None + 照常起普通求解（manifest→frame→final 无 error 帧，se 一期回退语义）
   + final 合成 ``{'engaged': False, 'reason': 中文}``；
3. **缺省零回归**：无 initial 键 / initial=null → initial_solution is None 且
   final 键集恰现行 7 键（逐字节不变锁：无 warm_state 键）。
"""
from __future__ import annotations

import time

import pytest
from starlette.testclient import TestClient

import materialsorting.web.routes_ws as routes_ws_mod
from materialsorting.nesting_engine import warmstart
from materialsorting.web import server as server_mod
from materialsorting.web.server import app


# ------------------------------------------------------------- 合成夹具（自足）


def _pieces() -> list[dict]:
    """2 片合成矩形裁片（schema v2 子集，与 test_web_initial_layout 同构）。"""
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


# quantities 上下文：g01×2 + g02×1（plain 宇宙 = 3 条完整解）。
_QTY = {'g01': {'28': 2}, 'g02': {'28': 1}}

_ABSENT = object()


def _pl(pid, rot=0.0, tr=None):
    return {'id': pid, 'rotation': rot,
            'translation': [0.0, 0.0] if tr is None else tr}


def _plain_placed() -> list[dict]:
    """plain 完整解 3 条（g01×2 + g02×1；strip_width 包络 = 1000）。"""
    return [
        _pl('g01_28', 0.0, [0.0, 0.0]),
        _pl('g01_28', 90.0, [1000.0, 500.0]),
        _pl('g02_28', 180.0, [600.0, 100.0]),
    ]


def _set_warm(monkeypatch, value: bool) -> None:
    """假能力探测（initial_layout 经 warmstart 模块属性调用 → 桩生效）。"""
    monkeypatch.setattr(warmstart, 'warm_start_supported', lambda: value)


def _start(initial=_ABSENT, quantities=_QTY, band=None, prefix=None):
    """最小合法 start payload（initial 缺席 = 旧前端行为；可显式传 None 验等价）。"""
    payload = {'action': 'start', 'sizes': [], 'time': 60, 'seed': 1,
               'params': None, 'per_type': None, 'quantities': quantities}
    if band is not None:
        payload['band'] = band
    if prefix is not None:
        payload['prefix'] = prefix
    if initial is not _ABSENT:
        payload['initial'] = initial
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


def _install_fake_proc(monkeypatch, calls, *, final_warm_state=_ABSENT):
    """伪 solve_with_callback_proc（monkeypatch routes_ws 模块属性 = 调用点生效）。

    同步 on_manifest + 单帧 on_report 后返回 worker 形态 final（density 双键/宽度/
    placed_items）；``final_warm_state`` 在场（含显式 None）时 final 附 ``warm_state``
    键（worker 只在 initial_solution 非 None 才附 —— 透传/合成两分支的对照数据源）。
    """

    def fake(pieces, gate_mm, solve_params, *, on_manifest=None,
             on_report=None, on_process=None, on_stage=None, band=None,
             prefix=None, initial_solution=None, record_composite=False):
        calls.append({'initial_solution': initial_solution, 'band': band,
                      'prefix': prefix, 'gate_mm': gate_mm,
                      'solve_params': dict(solve_params)})
        if on_process is not None:
            on_process(_FakeProc())
        if on_manifest is not None:
            on_manifest({'pid_meta': {}, 'total_area': 520000.0,
                         'n_eroded': 0, 'gate_mm': float(gate_mm)})
        if on_report is not None:
            on_report({'type': 'frame', 'elapsed': 0.1, 'phase': 'exploring',
                       'density': 0.5, 'density_sparrow': 0.55,
                       'width_mm': 1100.0, 'placed_items': _plain_placed()})
        final = {'type': 'final', 'density': 0.5, 'density_sparrow': 0.55,
                 'width_mm': 1100.0, 'elapsed': 0.3,
                 'placed_items': _plain_placed()}
        if final_warm_state is not _ABSENT:
            final['warm_state'] = final_warm_state
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
        'doc': {'source': 'synthetic_ws_initial.dxf'},
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


# ----------------------------------------------- AC#1 透传：plain happy path


def test_initial_plain_passthrough_payload_shape(ws_client, monkeypatch):
    """plain 透传：initial_solution == build_warm_payload 载荷（恰两键
    strip_width/placed_items、顺序保持、float 归一）；strip_width = 物理包络
    1000（g01@rot90 tx=1000 主导）。"""
    _set_warm(monkeypatch, True)
    calls: list = []
    _install_fake_proc(monkeypatch, calls,
                       final_warm_state={'engaged': True, 'reason': None})
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(initial={'placed': _plain_placed()}))
        final, seen = _drain_until_final(ws)
    assert len(calls) == 1
    payload = calls[0]['initial_solution']
    assert payload is not None
    assert set(payload) == {'strip_width', 'placed_items'}
    assert payload['strip_width'] == 1000.0
    assert [it['id'] for it in payload['placed_items']] == \
        ['g01_28', 'g01_28', 'g02_28']
    assert payload['placed_items'] == [
        {'id': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]},
        {'id': 'g01_28', 'rotation': 90.0, 'translation': [1000.0, 500.0]},
        {'id': 'g02_28', 'rotation': 180.0, 'translation': [600.0, 100.0]},
    ]
    # worker final warm_state 原样转发（装载成功 + worker 灌入成功）
    assert final['warm_state'] == {'engaged': True, 'reason': None}
    # 消息流不受影响：manifest → frame → final，无 error 帧
    assert [m['type'] for m in seen] == ['manifest', 'frame', 'final']


def test_initial_plain_ignores_payload_demand_map(ws_client, monkeypatch):
    """plain 时载荷自带 demand_map 被忽略（pid_meta 投影才是宇宙）：demand_map
    声明 g01=1 若被采用会在装载点 count mismatch 降级 —— 装载成功即证明忽略。"""
    _set_warm(monkeypatch, True)
    calls: list = []
    _install_fake_proc(monkeypatch, calls)
    initial = {'placed': _plain_placed(),
               'demand_map': {'g01_28': 1, 'g02_28': 1}}
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(initial=initial))
        _drain_until_final(ws)
    payload = calls[0]['initial_solution']
    assert payload is not None
    assert [it['id'] for it in payload['placed_items']] == \
        ['g01_28', 'g01_28', 'g02_28']


def test_initial_band_composite_demand_map_passthrough(ws_client, monkeypatch):
    """band 开：载荷 demand_map 直用（组合宇宙）—— WB_g01 原样进载荷（pid_meta
    投影下 WB_ 落映射外必降级，成功即证明直用）；组合条目不计包络（量 g02 得
    600 非 WB@700）；band cfg 照常透传。"""
    _set_warm(monkeypatch, True)
    calls: list = []
    _install_fake_proc(monkeypatch, calls,
                       final_warm_state={'engaged': True, 'reason': None})
    initial = {
        'placed': [_pl('WB_g01', 0.0, [700.0, 0.0]),
                   _pl('g02_28', 180.0, [600.0, 100.0])],
        'demand_map': {'WB_g01': 1, 'g02_28': 1},
    }
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(initial=initial,
                            band={'enabled': True, 'label': 'g01'}))
        final, _seen = _drain_until_final(ws)
    assert calls[0]['band'] == {'label': 'g01'}
    payload = calls[0]['initial_solution']
    assert payload is not None
    assert [it['id'] for it in payload['placed_items']] == ['WB_g01', 'g02_28']
    assert payload['strip_width'] == 600.0
    assert final['warm_state'] == {'engaged': True, 'reason': None}


def test_worker_degraded_warm_state_forwarded_verbatim(ws_client, monkeypatch):
    """worker 闸门降级（如宇宙复检 instance_mismatch）：final warm_state 原样
    转发（token reason 不被 routes_ws 重写/合成覆盖 —— 实际灌入态以 worker 为准）。"""
    _set_warm(monkeypatch, True)
    calls: list = []
    _install_fake_proc(monkeypatch, calls,
                       final_warm_state={'engaged': False,
                                         'reason': 'instance_mismatch'})
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(initial={'placed': _plain_placed()}))
        final, _seen = _drain_until_final(ws)
    assert calls[0]['initial_solution'] is not None
    assert final['warm_state'] == {'engaged': False, 'reason': 'instance_mismatch'}


# ------------------------------------------------- AC#2 降级：照常普通求解


def _assert_degraded(ws_client, monkeypatch, initial, reason_frag,
                     warm=True, **start_kw):
    """降级三断言共用：initial_solution=None / manifest→frame→final 无 error 帧 /
    final 合成 engaged=False + reason 含 reason_frag。"""
    _set_warm(monkeypatch, warm)
    calls: list = []
    _install_fake_proc(monkeypatch, calls)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(initial=initial, **start_kw))
        final, seen = _drain_until_final(ws)
    assert len(calls) == 1
    assert calls[0]['initial_solution'] is None
    assert [m['type'] for m in seen] == ['manifest', 'frame', 'final']
    assert final['warm_state']['engaged'] is False
    assert reason_frag in final['warm_state']['reason']
    return final


def test_initial_unsupported_degrades(ws_client, monkeypatch):
    """能力探测 False（PyPI 0.9.0 / ms0 实况）→ 降级普通求解 + 中文 reason。"""
    _assert_degraded(ws_client, monkeypatch, {'placed': _plain_placed()},
                     '不支持热启动', warm=False)


def test_initial_count_mismatch_degrades(ws_client, monkeypatch):
    """完整解硬约束（g01 demand=2 只 1 条）→ warmstart 校验矩阵 reason 透传合成。"""
    _assert_degraded(ws_client, monkeypatch,
                     {'placed': [_pl('g01_28'), _pl('g02_28')]}, '不是完整解')


def test_initial_unknown_pid_degrades(ws_client, monkeypatch):
    """pid 需求映射外（母版/数量已变更形态）→ 前置复检人话 reason。"""
    _assert_degraded(ws_client, monkeypatch, {'placed': [_pl('g99_28')]},
                     '需求映射外')


def test_initial_non_dict_key_degrades(ws_client, monkeypatch):
    """initial 键非对象（字符串/列表/数）→ 形态非法降级（不炸轮、不发 error 帧）。"""
    for bad in ('garbage', [1, 2], 42):
        _assert_degraded(ws_client, monkeypatch, bad, '形态非法')


def test_initial_malformed_placed_degrades(ws_client, monkeypatch):
    """placed 非列表/空/对象 → 装载点形态降级（reason 中文，照常普通求解）。"""
    for bad_placed in ('garbage', [], {'id': 'g01_28'}):
        _assert_degraded(ws_client, monkeypatch, {'placed': bad_placed},
                         '初始布局为空或形态非法')


def test_initial_band_without_demand_map_degrades(ws_client, monkeypatch):
    """band 开但载荷缺 demand_map → 落回 plain 投影，WB_ 在映射外 → 前置复检
    人话降级（组合宇宙数据源缺席不硬造）。"""
    _assert_degraded(ws_client, monkeypatch,
                     {'placed': [_pl('WB_g01', 0.0, [700.0, 0.0]),
                                 _pl('g02_28', 180.0, [600.0, 100.0])]},
                     '需求映射外', band={'enabled': True, 'label': 'g01'})


# --------------------------------------------- AC#3 缺省零回归（逐字节锁）


def test_no_initial_key_final_keyset_unchanged(ws_client, monkeypatch):
    """无 initial 键（旧前端）：initial_solution is None + final 键集恰现行 7 键
    （无 warm_state 键 = 消息流与现行逐字节一致的键级锁）。"""
    _set_warm(monkeypatch, True)      # 能力态无关：initial 缺席根本不进装载点
    calls: list = []
    _install_fake_proc(monkeypatch, calls)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start())
        final, seen = _drain_until_final(ws)
    assert len(calls) == 1
    assert calls[0]['initial_solution'] is None
    assert [m['type'] for m in seen] == ['manifest', 'frame', 'final']
    assert set(final) == {'type', 'density', 'density_sparrow', 'width_mm',
                          'elapsed', 'n_frames', 'n_eroded'}
    assert 'warm_state' not in final and 'prefix' not in final


def test_no_initial_key_call_form_unchanged_legacy_stub(ws_client, monkeypatch):
    """缺省路径调用形零变化锁：不接受 initial_solution kwarg 的旧桩
    （test_web_key_routes._fake_solve_factory 形态）照常工作 —— warm 载荷
    「在场才传」约定（solve_worker._solve 同款；run_solve 在 executor 线程抛
    TypeError 会吞 SENTINEL → write loop 永久挂起，调用形兼容是硬约束）。"""

    def legacy_fake(pieces, gate_mm, solve_params, *, on_manifest=None,
                    on_report=None, on_process=None, on_stage=None,
                    band=None, prefix=None):
        if on_process is not None:
            on_process(_FakeProc())
        if on_manifest is not None:
            on_manifest({'pid_meta': {}, 'total_area': 520000.0,
                         'n_eroded': 0, 'gate_mm': float(gate_mm)})
        if on_report is not None:
            on_report({'type': 'frame', 'elapsed': 0.1, 'phase': 'exploring',
                       'density': 0.5, 'density_sparrow': 0.55,
                       'width_mm': 1100.0, 'placed_items': _plain_placed()})
        return (object(), {'type': 'final', 'density': 0.5,
                           'density_sparrow': 0.55, 'width_mm': 1100.0,
                           'elapsed': 0.3,
                           'placed_items': _plain_placed()}, 0.3, None)

    monkeypatch.setattr(routes_ws_mod, 'solve_with_callback_proc', legacy_fake)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start())
        final, seen = _drain_until_final(ws)
    assert [m['type'] for m in seen] == ['manifest', 'frame', 'final']
    assert 'warm_state' not in final


def test_initial_null_key_same_as_absent(ws_client, monkeypatch):
    """initial=null ≡ 缺席（band null-ish 关闭同款语义）：恒 None 零降级路径，
    final 无 warm_state 键。"""
    _set_warm(monkeypatch, False)     # 探测 False 下 null 键也不触发降级合成
    calls: list = []
    _install_fake_proc(monkeypatch, calls)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(initial=None))
        final, _seen = _drain_until_final(ws)
    assert calls[0]['initial_solution'] is None
    assert 'warm_state' not in final


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
