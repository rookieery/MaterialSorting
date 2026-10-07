"""WS /ws/solve polish 智能微调接线测试（2026-10-07，满核运行下方通用配置）。

镜像 test_web_ws_full_cores 套路：monkeypatch ``routes_ws.solve_with_callback_proc``
注入伪 proc（final 布局可控），不跑真求解；polish 引擎走真实现（合成矩形布局
确定性可判）。

覆盖（四路验收口径）：
1. **透传**：``polish=true`` → final 投递前自动微调 —— 有缝布局 west 贴附收缝
   （width 缩小 / density 重算 / placed pid 多重集守恒）+ final 消息 additive
   ``polish`` 摘要段（improved=True）；无 move 布局 → improved=False 且 placed
   不变（引擎返回输入原对象不变量）；
2. **严格 bool**：``1`` / ``'on'`` → 结构化 error 帧早退 + 显式 close，不建子进程；
3. **缺省零回归**：无键 / 显式 ``false`` → final 键集无 ``polish``、placed 逐字节
   不变；
4. **降级**：placed pid 不在会话 pieces_by_id（PolishError）→ warn + 投递未微调
   final（无 polish 键、布局原样，不炸轮）。

另含 ``_polish_exclude`` 纯函数单测（band labels / prefix 成员 pids / 双开合并 /
皆无 → None）。
"""
from __future__ import annotations

import time

import pytest
from starlette.testclient import TestClient

import materialsorting.web.routes_ws as routes_ws_mod
from materialsorting.web import server as server_mod
from materialsorting.web.server import app


# ------------------------------------------------------------- 合成夹具（自足）


def _pieces() -> list[dict]:
    """2 片合成矩形裁片（schema v2 子集，与 test_web_ws_full_cores 同构）。"""
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


_ABSENT = object()

# 有缝布局：g01 @x[0,500]，g02 @x[700,1000] —— west 贴附把 g02 滑到 x=500 贴触，
# 物理包络 1000 → 800（密度 520000/(800×1980)）。
_PLACED_GAP = [
    {'id': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]},
    {'id': 'g02_28', 'rotation': 0.0, 'translation': [700.0, 0.0]},
]
# 无缝布局：两片已贴触 + 贴地，零 move（引擎返回输入原对象）。
_PLACED_SNUG = [
    {'id': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]},
    {'id': 'g02_28', 'rotation': 0.0, 'translation': [500.0, 0.0]},
]
# 宇宙外 pid（降级路径）。
_PLACED_GHOST = [
    {'id': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]},
    {'id': 'g99_28', 'rotation': 0.0, 'translation': [700.0, 0.0]},
]


def _start(polish=_ABSENT, **extra):
    """最小合法 start payload（polish 缺席 = 旧前端行为）。"""
    payload = {'action': 'start', 'sizes': [], 'time': 60, 'seed': 1,
               'params': None, 'per_type': None, 'quantities': None}
    if polish is not _ABSENT:
        payload['polish'] = polish
    payload.update(extra)
    return payload


class _FakeProc:
    pid = 9999

    def is_alive(self):
        return False

    def terminate(self):
        pass

    def join(self, timeout=None):
        pass

    def kill(self):
        pass


def _install_fake_proc(monkeypatch, placed):
    """伪 solve_with_callback_proc：manifest（total_area=520000）+ 单帧 + final
    （placed_items 由用例给定）。"""

    def fake(pieces, gate_mm, solve_params, *, on_manifest=None,
             on_report=None, on_process=None, on_stage=None, band=None,
             prefix=None, initial_solution=None, record_composite=False):
        if on_process is not None:
            on_process(_FakeProc())
        if on_manifest is not None:
            on_manifest({'pid_meta': {}, 'total_area': 520000.0,
                         'n_eroded': 0, 'gate_mm': float(gate_mm)})
        if on_report is not None:
            on_report({'type': 'frame', 'elapsed': 0.1, 'phase': 'exploring',
                       'density': 0.5, 'density_sparrow': 0.55,
                       'width_mm': 1100.0, 'placed_items': []})
        final = {'type': 'final', 'density': 0.5, 'density_sparrow': 0.55,
                 'width_mm': 1100.0, 'elapsed': 0.3,
                 'placed_items': [dict(p) for p in placed]}
        return object(), final, 0.3, None

    monkeypatch.setattr(routes_ws_mod, 'solve_with_callback_proc', fake)
    return fake


@pytest.fixture
def ws_client():
    """注入合成 pieces state（原位 clear+update，teardown 恢复真实 state）。"""
    pieces = _pieces()
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update({
        'doc': {'source': 'synthetic_ws_polish.dxf'},
        'gate_mm': 1980.0,
        'pieces': pieces,
        'pieces_by_id': {p['pid']: p for p in pieces},
    })
    with TestClient(app) as client:
        yield client
    state.clear()
    state.update(saved)


def _drain_until_final(ws, timeout=10.0):
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        m = ws.receive_json()
        seen.append(m)
        if m.get('type') == 'final':
            return m, seen
    pytest.fail('final not received within deadline')


# ------------------------------------------------------- AC#1 透传（微调生效）


def test_polish_true_final_polished(ws_client, monkeypatch):
    """polish=true → 有缝布局 west 贴附收缝：width 1000→800、density 物理口径
    重算、placed pid 多重集守恒、final 附 polish 摘要段（improved=True）。"""
    _install_fake_proc(monkeypatch, _PLACED_GAP)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(polish=True))
        final, seen = _drain_until_final(ws)
    assert [m['type'] for m in seen] == ['manifest', 'frame', 'final']
    # 改进布局随 final 补发（前端 applyFinal 覆写 lastFrame 的数据源）：
    # g02 被滑贴到 x=500（与 g01 贴触）；pid 多重集守恒。
    assert sorted(p['id'] for p in final['placed_items']) == ['g01_28', 'g02_28']
    g02 = next(p for p in final['placed_items'] if p['id'] == 'g02_28')
    assert g02['translation'][0] == pytest.approx(500.0, abs=0.01)
    # 口径重算：物理包络 = 800 + 贴附 1nm 微抬 → ceil 801 × gate 1980、分子
    # manifest total_area 520000（引擎 report 的 width_mm round3 ≈ 800.0）。
    assert final['width_mm'] == 801
    assert final['density'] == pytest.approx(520000.0 / (801.0 * 1980.0))
    # 摘要段：improved + 前后密度（引擎 report 百分数口径）+ 轮数 ≥1。
    sec = final['polish']
    assert sec['improved'] is True
    assert sec['before']['width_mm'] == pytest.approx(1000.0, abs=0.01)
    assert sec['after']['width_mm'] == pytest.approx(800.0, abs=0.01)
    assert sec['after']['density'] > sec['before']['density']
    assert sec['rounds'] >= 1 and sec['moves'] >= 1


def test_polish_true_no_move_layout_unchanged(ws_client, monkeypatch):
    """polish=true 但布局已 snug（零 move）→ improved=False、不补发 placed_items
    （前端末帧原样）、polish 段仍在场（如实记尝试态）。"""
    _install_fake_proc(monkeypatch, _PLACED_SNUG)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(polish=True))
        final, _seen = _drain_until_final(ws)
    assert 'placed_items' not in final        # 无改进 → 不补发（末帧即终态）
    assert final['polish']['improved'] is False
    assert final['polish']['moves'] == 0


# --------------------------------------------------------------- AC#2 严格 bool


@pytest.mark.parametrize('bad', [1, 0, 'on', 'true'])
def test_polish_non_bool_rejected(ws_client, monkeypatch, bad):
    """非 bool（int/字符串，含真值形态）→ 结构化 error 帧早退 + 显式 close，
    不发 manifest、不建求解子进程。"""
    _install_fake_proc(monkeypatch, _PLACED_SNUG)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(polish=bad))
        m = ws.receive_json()
    assert m['type'] == 'error'
    assert 'polish 须为布尔值' in m['message']


# --------------------------------------------------------------- AC#3 缺省零回归


@pytest.mark.parametrize('raw', [_ABSENT, False], ids=['absent', 'explicit-false'])
def test_polish_absent_final_unchanged(ws_client, monkeypatch, raw):
    """无键 / 显式 false → final 键集无 polish 无 placed_items（线格式零回归，
    前端末帧原样 = 旧行为逐字节一致）。"""
    _install_fake_proc(monkeypatch, _PLACED_GAP)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(polish=raw))
        final, _seen = _drain_until_final(ws)
    assert 'polish' not in final
    assert 'placed_items' not in final
    assert final['width_mm'] == 1100.0 and final['density'] == 0.5


# ------------------------------------------------------- AC#4 降级（不炸轮）


def test_polish_engine_failure_degrades(ws_client, monkeypatch):
    """placed pid 不在会话 pieces_by_id（PolishError）→ warn + 投递未微调
    final（无 polish 键无 placed_items，布局原样），不炸轮。"""
    _install_fake_proc(monkeypatch, _PLACED_GHOST)
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start(polish=True))
        final, _seen = _drain_until_final(ws)
    assert 'polish' not in final
    assert 'placed_items' not in final


# ------------------------------------------------- _polish_exclude 纯函数单测


def test_polish_exclude_band_only():
    out = routes_ws_mod._polish_exclude({'label': 'g05'}, None, None)
    assert out == {'labels': ['g05']}


def test_polish_exclude_prefix_members():
    """prefix 成员 pid：front/back 取 prefix_cfg、size/extra 取 final 统计段
    （统计段真实形态无 front/back 键 —— solve_worker final['prefix'] 子集）。"""
    cfg = {'front': 'g02', 'back': 'g03'}
    stats = {'size': 34, 'pid': 'PS_g02+g03@34', 'pin': None, 'band_pos': None,
             'extra': None, 'residual_mm': 5.2, 'fallback': False}
    assert routes_ws_mod._polish_exclude(None, cfg, stats) == \
        {'pids': ['g02_34', 'g03_34']}


def test_polish_exclude_prefix_with_extra():
    cfg = {'front': 'g02', 'back': 'g03'}
    stats = {'size': 34, 'pid': 'PS_g02+g03@34+g09@31',
             'extra': {'pid': 'g09_31', 'label': 'g09', 'size': 31,
                       'rotation': 180.0}}
    assert routes_ws_mod._polish_exclude(None, cfg, stats) == \
        {'pids': ['g02_34', 'g03_34', 'g09_31']}


def test_polish_exclude_both_merged():
    cfg = {'front': 'g02', 'back': 'g03'}
    stats = {'size': 30, 'pid': 'PS_g02+g03@30', 'extra': None}
    out = routes_ws_mod._polish_exclude({'label': 'g05'}, cfg, stats)
    assert out == {'labels': ['g05'], 'pids': ['g02_30', 'g03_30']}


def test_polish_exclude_none():
    assert routes_ws_mod._polish_exclude(None, None, None) is None
    assert routes_ws_mod._polish_exclude({}, {}, {}) is None
    # prefix 统计段缺席（final 无 prefix 键）→ 无从定 size → 不产 pids。
    assert routes_ws_mod._polish_exclude(None, {'front': 'g02',
                                                'back': 'g03'}, None) is None
    # 统计段缺 size（畸形防御）→ 不产 pids。
    assert routes_ws_mod._polish_exclude(None, {'front': 'g02',
                                                'back': 'g03'}, {}) is None
