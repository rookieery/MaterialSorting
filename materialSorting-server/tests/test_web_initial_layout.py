"""初始布局 web 侧 warm 载荷装载点 + 能力探测 + 生成端点测试（prd-initial-layout）。

夹具全合成（2 片矩形，与 conftest/test_warmstart_chain 同构），能力探测经
monkeypatch ``warmstart.warm_start_supported`` 打桩（initial_layout 按调用时模块
属性取函数 → 桩生效），PyPI 0.9.0 / ms0 装载态同样全绿；US-002 生成端点经
monkeypatch ``web.solver.solve_with_callback_proc``（generate_initial_layout 函数内
延迟 import = 调用时取属性 → 桩生效）注入合成 manifest/帧，无真实 solve 依赖。

覆盖：
1. ``build_warm_payload`` 装载点（US-001）：plain round-trip 精确结构（多副本/
   int→float/顺序保持/JSON 可序列化/gate_mm 在场不入载荷 = 契约两键哨兵）；
   strip_width 与 ``build_pid_meta → _raw_polygon_map → _physical_width_mm``
   权威链对拍；demand 投影与 worker 实例宇宙同口径（sizes 过滤 / quantities
   demand=0 出局）；降级矩阵（mirror / 条数≠demand / pid 需求映射外前置复检 /
   placed 空·非列表 / 无母版 / 脏 pieces 不抛 / demand_map 非 dict /
   unsupported 判定序首位脏输入不抛）；组合宇宙 demand_map 直用（pid_meta 投影
   未被采用 + WB_ 原样进载荷）+ 组合条目不计包络（measurable-only 政策锁）；
2. ``warm_capability``（US-001）：形态 ``{supported: bool, version: str}`` /
   版本串 monkeypatch 多态 / 包缺失哨兵 ``'(未安装)'`` 恒不抛；
3. ``GET /api/warm-capability``（US-001，TestClient）：恒 200 / 无会话闸门
   （bogus sid 同样 200 —— 能力是进程级属性）/ 能力态透传（monkeypatch 生效）；
4. ``POST /api/initial-layout/generate``（US-002，TestClient + fake proc）：
   happy path 响应形态（manifest = WS 前端契约同形 / placed = 密度最大可行帧
   展开视图永无 WB_/PS_ / width_mm·density 同帧）+ proc 调用形态（time_budget
   = ``INITIAL_LAYOUT_GEN_TIME_S``=10 / sizes·params·per_type·quantities·seed
   透传 / band·prefix worker 形态 / **record_composite=True 透传断言**）+ gate_mm
   覆盖；band/prefix 同开 composite+prefix 段在场与 plain 缺席；错误矩阵（会话
   401/400 / body·seed 400 / 无母版 400 / band·prefix 非法 400 / 求解错误与无
   manifest·无可行帧 502）+ per-session 单飞 409（阻塞 fake 双线程并发，跨会话
   放开）+ 成功顺手 ``edit_hold.refresh``（default 豁免 / 失败不续期）；
5. 分层纯度（AST 守卫，镜像 test_web_edit_hold 套路）：仅 stdlib + web 兄弟
   solver/routes_ws + nesting_engine.warmstart，禁 import server/cli（含函数内
   延迟）；
6. 冒烟 ``main`` exit 0（``python -m`` 同一代码路径）。
"""
from __future__ import annotations

import ast
import importlib.metadata
import json
import threading
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import materialsorting.web.solver as web_solver
from materialsorting.nesting_engine import warmstart
from materialsorting.web import (
    edit_hold,
    initial_layout,
    routes_views as routes_views_mod,
    server as server_mod,
    sessions,
)
from materialsorting.web.initial_layout import (
    INITIAL_LAYOUT_GEN_TIME_S,
    build_warm_payload,
    warm_capability,
)
from materialsorting.web.server import app
from materialsorting.web.sessions import _FakeClock
from materialsorting.web.solver import (
    _physical_width_mm,
    _raw_polygon_map,
    build_pid_meta,
)


# ------------------------------------------------------------- 合成夹具（自足）


def _pieces() -> list[dict]:
    """2 片合成矩形裁片（schema v2 子集，与 conftest synthetic 同构）。"""
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


def _pl(pid, rot=0.0, tr=None, **extra):
    it = {'id': pid, 'rotation': rot,
          'translation': [0.0, 0.0] if tr is None else tr}
    it.update(extra)
    return it


def _set_warm(monkeypatch, value: bool) -> None:
    """假能力探测（initial_layout 经 warmstart 模块属性调用 → 桩生效）。"""
    monkeypatch.setattr(warmstart, 'warm_start_supported', lambda: value)


def _set_version(monkeypatch, version=None, exc=None):
    """monkeypatch importlib.metadata.version → 固定串 / 固定异常。"""
    def fake(name):
        if exc is not None:
            raise exc
        assert name == 'spyrrow'
        return version
    monkeypatch.setattr(importlib.metadata, 'version', fake)


# quantities 上下文：g01×2 + g02×1（多副本 + demand 全在场；单测可覆写）。
_QTY = {'g01': {'28': 2}, 'g02': {'28': 1}}


def _ctx(**over):
    ctx = dict(gate_mm=1980.0, sizes=None, per_type=None,
               quantities=_QTY, params=None)
    ctx.update(over)
    return ctx


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------- AC#1 装载点：happy path

def test_valid_round_trip_exact_shape(monkeypatch):
    """合法构造：多副本 + int 归一 float + 顺序保持；契约恰两键（gate_mm 在场
    但不入载荷）；JSON 可序列化（Windows spawn pickle 安全面的前置）。"""
    _set_warm(monkeypatch, True)
    placed = [
        {'id': 'g01_28', 'rotation': 0, 'translation': [0, 0]},
        {'id': 'g01_28', 'rotation': 90, 'translation': [1000, 500]},
        {'id': 'g02_28', 'rotation': 180, 'translation': [600, 100]},
    ]
    payload, reason = build_warm_payload(_pieces(), placed, **_ctx())
    assert reason is None and payload is not None
    assert set(payload) == {'strip_width', 'placed_items'}      # 契约两键哨兵
    assert payload['placed_items'] == [
        {'id': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]},
        {'id': 'g01_28', 'rotation': 90.0, 'translation': [1000.0, 500.0]},
        {'id': 'g02_28', 'rotation': 180.0, 'translation': [600.0, 100.0]},
    ]
    assert json.loads(json.dumps(payload)) == payload


def test_strip_width_matches_authoritative_formula(monkeypatch):
    """strip_width 与 solver 权威链对拍：build_pid_meta → _raw_polygon_map →
    _physical_width_mm（同一 placed 逐位相等 —— 前后端物理包络口径单一公式锁）。"""
    _set_warm(monkeypatch, True)
    placed = [
        _pl('g01_28', 0.0, [0.0, 0.0]),
        _pl('g01_28', 90.0, [1000.0, 500.0]),
        _pl('g02_28', 180.0, [600.0, 100.0]),
    ]
    payload, reason = build_warm_payload(_pieces(), placed, **_ctx())
    assert reason is None
    pid_meta, _a, _n = build_pid_meta(_pieces(), quantities=_QTY)
    expect = _physical_width_mm(placed, _raw_polygon_map(pid_meta))
    assert payload['strip_width'] == float(expect)


def test_demand_projection_matches_worker_universe(monkeypatch):
    """demand 投影 = build_pid_meta 同口径（与 worker build_instance 宇宙一致，
    防 instance_mismatch）：quantities demand=0 出局（g02 排除后 2×g01 即完整解）；
    sizes 过滤把宇宙清空 → 前置复检降级（pid 需求映射外）。"""
    _set_warm(monkeypatch, True)
    payload, reason = build_warm_payload(
        _pieces(), [_pl('g01_28'), _pl('g01_28', 180.0, [600.0, 0.0])],
        **_ctx(quantities={'g01': {'28': 2}, 'g02': {'28': 0}}))
    assert reason is None
    assert [it['id'] for it in payload['placed_items']] == ['g01_28', 'g01_28']
    payload2, reason2 = build_warm_payload(
        _pieces(), [_pl('g01_28'), _pl('g01_28', 180.0, [600.0, 0.0])],
        **_ctx(sizes=[30]))
    assert payload2 is None and '需求映射外' in reason2


# --------------------------------------------------- AC#1 装载点：降级矩阵

def test_mirror_rejected_reason(monkeypatch):
    """mirror 片拒绝（warmstart 校验矩阵中文 reason 透传；条目 @tx=600 保证包络
    为正 —— 隔离 strip_width 降级分支）。"""
    _set_warm(monkeypatch, True)
    payload, reason = build_warm_payload(
        _pieces(), [_pl('g01_28', 0.0, [0.0, 0.0]),
                    _pl('g01_28', 0.0, [600.0, 0.0], mirror=True)],
        **_ctx())
    assert payload is None and '含镜像片，无法热启动' in reason


def test_count_mismatch_reason(monkeypatch):
    """每 pid 条数 != demand（完整解硬约束 F2）→ warmstart 中文 reason 透传。"""
    _set_warm(monkeypatch, True)
    payload, reason = build_warm_payload(
        _pieces(), [_pl('g01_28'), _pl('g02_28')], **_ctx())   # g01 demand=2 缺 1
    assert payload is None
    assert '不是完整解' in reason and 'g01_28' in reason and '2' in reason


def test_pid_outside_demand_map_precheck_reason(monkeypatch):
    """pid 不在需求映射 → 前置复检先行（人话 reason 带 pid 与「已变更」提示），
    不让宽度量取炸出含糊文案（保存态/运行态参数漂移 = 最常见失效形态）。"""
    _set_warm(monkeypatch, True)
    payload, reason = build_warm_payload(
        _pieces(), [_pl('g99_28')], **_ctx())
    assert payload is None
    assert '需求映射外' in reason and 'g99_28' in reason


def test_empty_or_malformed_placed_reason(monkeypatch):
    """placed 空列表 / 非列表形态 → 降级不抛（reason 中文）。"""
    _set_warm(monkeypatch, True)
    for bad in ([], 'garbage', {'id': 'g01_28'}, None):
        payload, reason = build_warm_payload(_pieces(), bad, **_ctx())
        assert payload is None and '初始布局为空或形态非法' in reason


def test_no_pieces_reason(monkeypatch):
    """无母版（pieces 空）→ 中文 reason（US-003 WS 侧 400 同源文案）。"""
    _set_warm(monkeypatch, True)
    payload, reason = build_warm_payload(
        [], [_pl('g01_28'), _pl('g01_28', 180.0, [600.0, 0.0]), _pl('g02_28')],
        **_ctx())
    assert payload is None and '请先上传母版' in reason


def test_malformed_pieces_degrade_no_raise(monkeypatch):
    """脏 pieces（缺 polygon/size 等键）→ 裁片实例构造失败降级，绝不抛。"""
    _set_warm(monkeypatch, True)
    payload, reason = build_warm_payload(
        [{'pid': 'broken'}], [_pl('broken')], **_ctx())
    assert payload is None and '裁片实例构造失败' in reason


def test_demand_map_not_dict_degrades(monkeypatch):
    """显式 demand_map 非 dict → warmstart 校验矩阵 reason（需求映射应为字典）。"""
    _set_warm(monkeypatch, True)
    payload, reason = build_warm_payload(
        _pieces(), [_pl('g01_28'), _pl('g02_28')], **_ctx(),
        demand_map=['g01_28'])
    assert payload is None and '需求映射' in reason


def test_unsupported_degrades_first_no_raise(monkeypatch):
    """unsupported 判定序首位：能力探测 False 时脏输入（placed 非列表 / pieces
    垃圾）同样不抛 —— 装载点全降级红线。"""
    _set_warm(monkeypatch, False)
    for pieces, placed in ((None, 'garbage'), ([{'x': 1}], [1, 2, 3])):
        payload, reason = build_warm_payload(pieces, placed, **_ctx())
        assert payload is None
        assert '不支持热启动' in reason


# ------------------------------------- AC#1 装载点：组合宇宙（band/prefix 口径）

def test_composite_demand_map_used_directly(monkeypatch):
    """组合 demand_map 直用：pid_meta 投影未被采用（g01_28 demand=2 的 plain
    投影会让本载荷「不完整」，直接采用组合宇宙 {WB_g01: 1, g02_28: 1} 即合法）；
    WB_ 条目原样进 placed_items（组合视角 = worker 重建实例宇宙）。"""
    _set_warm(monkeypatch, True)
    comp_placed = [
        _pl('WB_g01', 0.0, [0.0, 0.0]),
        _pl('g02_28', 180.0, [600.0, 100.0]),
    ]
    payload, reason = build_warm_payload(
        _pieces(), comp_placed, **_ctx(),
        demand_map={'WB_g01': 1, 'g02_28': 1})
    assert reason is None and payload is not None
    assert payload['placed_items'] == [
        {'id': 'WB_g01', 'rotation': 0.0, 'translation': [0.0, 0.0]},
        {'id': 'g02_28', 'rotation': 180.0, 'translation': [600.0, 100.0]},
    ]


def test_composite_entries_excluded_from_envelope(monkeypatch):
    """组合条目不计包络（measurable-only 政策锁）：WB_g01 @tx=700 不进包络，
    strip_width = g02_28 @tx=600 rot180 的包络 600 —— 组合片轮廓只在 worker
    实例内，主进程 pid_raw 无此 pid。"""
    _set_warm(monkeypatch, True)
    comp_placed = [
        _pl('WB_g01', 0.0, [700.0, 0.0]),
        _pl('g02_28', 180.0, [600.0, 100.0]),
    ]
    payload, reason = build_warm_payload(
        _pieces(), comp_placed, **_ctx(),
        demand_map={'WB_g01': 1, 'g02_28': 1})
    assert reason is None
    assert payload['strip_width'] == 600.0


def test_all_composite_universe_degrades(monkeypatch):
    """全组合条目宇宙（无可测量轮廓）→ 降级 reason（不抛；理论退化形态）。"""
    _set_warm(monkeypatch, True)
    payload, reason = build_warm_payload(
        _pieces(), [_pl('WB_g01', 0.0, [700.0, 0.0])], **_ctx(),
        demand_map={'WB_g01': 1})
    assert payload is None and '无可测量裁片轮廓' in reason


# ------------------------------------------------------- AC#2 warm_capability

@pytest.mark.parametrize('version,supported,expect_supported', [
    ('0.9.0+ms1', True, True),
    ('0.9.0+ms3', True, True),
    ('0.9.0+ms0', False, False),
    ('0.9.0', False, False),
])
def test_warm_capability_matrix(monkeypatch, version, supported,
                                expect_supported):
    """能力 dict = {supported: warm_start_supported(), version: 实装版本串}。"""
    _set_warm(monkeypatch, supported)
    _set_version(monkeypatch, version=version)
    assert warm_capability() == {'supported': expect_supported,
                                 'version': version}


def test_warm_capability_package_missing(monkeypatch):
    """spyrrow 未安装（version 抛 PackageNotFoundError 等）→ 哨兵 '(未安装)'，
   探测恒不抛（进程级属性探测不得成为 5xx 面）。"""
    _set_warm(monkeypatch, False)
    _set_version(monkeypatch, exc=importlib.metadata.PackageNotFoundError('x'))
    cap = warm_capability()
    assert cap == {'supported': False, 'version': '(未安装)'}


# ------------------------------------------- AC#2 GET /api/warm-capability 端点

def test_endpoint_always_200_no_session_gate(client):
    """恒 200 + 两键形态；无会话闸门（bogus X-Session-Id 同样 200 —— 能力是
    进程级属性，与 GET /api/samples 同类，不进 SessionError 早退路径）。"""
    for headers in ({}, {'X-Session-Id': 'nonsense!'},
                    {'X-Session-Id': 'deadbeefdeadbeef'}):
        r = client.get('/api/warm-capability', headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {'supported', 'version'}
        assert isinstance(body['supported'], bool)
        assert isinstance(body['version'], str)


def test_endpoint_reflects_capability_state(client, monkeypatch):
    """端点透传 warm_capability() 单一数据源（monkeypatch 生效 = 无旁路缓存）。"""
    _set_warm(monkeypatch, True)
    _set_version(monkeypatch, version='9.9.9+ms5')
    assert client.get('/api/warm-capability').json() == {
        'supported': True, 'version': '9.9.9+ms5'}
    _set_warm(monkeypatch, False)
    _set_version(monkeypatch, exc=RuntimeError('boom'))
    assert client.get('/api/warm-capability').json() == {
        'supported': False, 'version': '(未安装)'}


# ------------------------------------------- AC#3/AC#5 分层纯度（AST 守卫）+ 冒烟

def test_initial_layout_module_layering_purity():
    """initial_layout 仅 stdlib + web 兄弟 solver + nesting_engine.warmstart，
    禁 import server/cli（套路镜像 test_web_edit_hold 同名守卫）。"""
    src = Path(initial_layout.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'importlib', 'json', 'sys', 'materialsorting'}
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert not mod.startswith('materialsorting.web.server'), \
                'initial_layout 禁 import server（依赖方向 server → initial_layout）'
            assert not mod.startswith('materialsorting.cli'), \
                'initial_layout 禁 import cli（web 禁反向依赖上层）'
            if node.level:                      # 相对 import 解析到本包/下层
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


def test_smoke_main_pass(capsys):
    """`python -m` 冒烟同一代码路径：合成夹具自检全过 exit 0。"""
    assert initial_layout.main([]) == 0
    out = capsys.readouterr().out
    assert 'PASS' in out
    assert 'FAIL' not in out


# ================================ US-002 POST /api/initial-layout/generate 生成端点

_GEN_URL = '/api/initial-layout/generate'

_G01_POLY = [[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]]
_G02_POLY = [[0.0, 0.0], [300.0, 0.0], [300.0, 400.0], [0.0, 400.0]]


def _pid_meta() -> dict:
    """合成 worker manifest pid_meta（build_pid_meta 产物同形子集，demand g01=2）。"""
    return {
        'g01_28': {'size': 28, 'color': '#c62828', 'polygon': _G01_POLY,
                   'raw_polygon': _G01_POLY, 'd_mm': 0.0, 'label': 'g01',
                   'demand': 2, 'area_mm2': 400000.0, 'net_polygon': [],
                   'internal_lines': [], 'notches': [], 'grain_line': None},
        'g02_28': {'size': 28, 'color': '#c62828', 'polygon': _G02_POLY,
                   'raw_polygon': _G02_POLY, 'd_mm': 0.0, 'label': 'g02',
                   'demand': 1, 'area_mm2': 120000.0, 'net_polygon': [],
                   'internal_lines': [], 'notches': [], 'grain_line': None},
    }


def _worker_manifest() -> dict:
    return {'pid_meta': _pid_meta(), 'total_area': 520000.0, 'n_eroded': 0,
            'gate_mm': 1980.0}


def _expected_manifest(gate_mm=1980.0) -> dict:
    """WS 前端契约同形 manifest（_build_manifest_msg 白名单投影手排期望）。"""
    pieces = []
    for pid, meta in _pid_meta().items():
        pieces.append({
            'id': pid, 'size': meta['size'], 'color': meta['color'],
            'area_mm2': meta['area_mm2'], 'polygon': meta['polygon'],
            'raw_polygon': meta['raw_polygon'], 'd_mm': meta['d_mm'],
            'label': meta['label'], 'demand': meta['demand'],
            'net_polygon': meta['net_polygon'],
            'internal_lines': meta['internal_lines'],
            'notches': meta['notches'], 'grain_line': meta['grain_line'],
        })
    return {'type': 'manifest', 'gate_mm': gate_mm, 'total_area_mm2': 520000.0,
            'n_eroded': 0, 'pieces': pieces}


def _frames(composite_on_best: bool = False) -> list[dict]:
    """两帧（0.55 / 0.62）—— best=帧 2；composite_on_best 时帧 2 附组合段。"""
    best = {
        'type': 'frame', 'elapsed': 2.0, 'phase': 'exploring',
        'density': 0.62, 'density_sparrow': 0.64, 'width_mm': 1100.0,
        'placed_items': [
            _pl('g01_28', 0.0, [0.0, 0.0]),
            _pl('g01_28', 0.0, [500.0, 800.0]),
            _pl('g02_28', 90.0, [700.0, 900.0]),
        ],
    }
    if composite_on_best:
        best['composite'] = {
            'placed_items': [
                _pl('WB_g01', 0.0, [0.0, 0.0]),
                _pl('g02_28', 90.0, [700.0, 900.0]),
            ],
            'demand_map': {'WB_g01': 1, 'g01_28': 0, 'g02_28': 1},
        }
    return [
        {'type': 'frame', 'elapsed': 1.0, 'phase': 'exploring',
         'density': 0.55, 'density_sparrow': 0.57, 'width_mm': 1200.0,
         'placed_items': [
             _pl('g01_28', 0.0, [0.0, 0.0]),
             _pl('g01_28', 180.0, [700.0, 0.0]),
             _pl('g02_28', 0.0, [400.0, 1000.0]),
         ]},
        best,
    ]


def _final(with_prefix: bool = False) -> dict:
    out = {'type': 'final', 'density': 0.62, 'density_sparrow': 0.64,
           'width_mm': 1100.0, 'elapsed': 2.2,
           'placed_items': _frames()[-1]['placed_items']}
    if with_prefix:
        out['prefix'] = {'size': 28, 'pid': 'PS_g01+g02@28', 'pin': {},
                         'band_pos': {}, 'extra': None, 'residual_mm': 3.2,
                         'fallback': False}
    return out


def _install_fake_proc(monkeypatch, *, frames, final=None, err=None,
                       manifest=None, capture=None, started=None,
                       gate_evt=None):
    """伪 ``solve_with_callback_proc``（monkeypatch web_solver 属性 = 调用时生效）。

    同步 on_manifest + 逐帧 on_report 后返回 ``(proc, final, elapsed, err)``
    （run_arm 假形态）；``capture`` dict 收调用形态；``started``/``gate_evt``
    单飞并发测试用 —— **仅第 1 次调用**在投完帧后阻塞等 gate（第 2+ 次直接
    返回，供「跨会话放开」对照请求跑通）。
    """
    man = _worker_manifest() if manifest is None else manifest
    calls = {'n': 0}

    def _impl(pieces, gate_mm, solve_params, *, on_manifest, on_report,
              on_process=None, on_stage=None, band=None, prefix=None,
              initial_solution=None, record_composite=False):
        calls['n'] += 1
        if capture is not None:
            capture.update(pieces=list(pieces), gate_mm=gate_mm,
                           solve_params=dict(solve_params), band=band,
                           prefix=prefix, record_composite=record_composite,
                           n_calls=calls['n'])
        on_manifest(man)
        for fr in frames:
            on_report(fr)
        if calls['n'] == 1 and started is not None and gate_evt is not None:
            started.set()
            gate_evt.wait(timeout=10)
        return object(), final, 0.5, err

    monkeypatch.setattr(web_solver, 'solve_with_callback_proc', _impl)
    return _impl


def _gen_state(gate_mm=1980.0) -> dict:
    pieces = _pieces()
    return {'doc': {'source': 'synthetic_gen.dxf'}, 'gate_mm': gate_mm,
            'pieces': pieces, 'pieces_by_id': {p['pid']: p for p in pieces}}


@pytest.fixture
def gen_client():
    """default 会话注入合成 state + registry/编辑钉住/单飞锁隔离（polish 套路）。"""
    reg = sessions.registry
    reg.stop_scanner()
    reg.reset()
    edit_hold._HOLDS.clear()
    routes_views_mod._INITIAL_LAYOUT_BUSY.clear()
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update(_gen_state())
    with TestClient(app) as client:
        yield client
    state.clear()
    state.update(saved)
    routes_views_mod._INITIAL_LAYOUT_BUSY.clear()
    edit_hold._HOLDS.clear()
    reg.reset()


# ------------------------------------------------------------- happy path

def test_generate_happy_path_plain(gen_client, monkeypatch):
    """AC：plain 200 —— 键恰 {ok,manifest,placed,width_mm,density}（无 composite/
    prefix）；manifest = WS 前端契约同形；placed = 密度最大可行帧展开视图逐条透传
    （永无 WB_/PS_）；proc 调用形态 time_budget=10 + 全缺省透传 + record_composite
    =True；成功后单飞锁清空。"""
    assert INITIAL_LAYOUT_GEN_TIME_S == 10
    cap: dict = {}
    _install_fake_proc(monkeypatch, frames=_frames(), final=_final(),
                       capture=cap)
    r = gen_client.post(_GEN_URL, json={})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {'ok', 'manifest', 'placed', 'width_mm', 'density'}
    assert body['ok'] is True
    assert body['manifest'] == _expected_manifest(1980.0)
    best = _frames()[-1]
    assert body['placed'] == best['placed_items']
    assert all(it['id'].startswith('g') for it in body['placed'])
    assert not any(it['id'].startswith(('WB_', 'PS_')) for it in body['placed'])
    assert body['width_mm'] == best['width_mm'] == 1100.0
    assert body['density'] == best['density'] == 0.62
    # proc 调用形态（record_composite 透传断言 + WS start 同形缺省）
    assert cap['record_composite'] is True
    assert cap['solve_params'] == {'time_budget': 10, 'seed': 0, 'sizes': [],
                                   'params': None, 'per_type': None,
                                   'quantities': None}
    assert cap['band'] is None and cap['prefix'] is None
    assert cap['gate_mm'] == 1980.0
    assert cap['pieces'] == _pieces()
    assert routes_views_mod._INITIAL_LAYOUT_BUSY == {}


def test_generate_body_context_passthrough_and_gate_override(
        gen_client, monkeypatch):
    """body 与 WS start 同形子集逐键透传（sizes/params/per_type/quantities/seed）+
    gate_mm 正值覆盖（manifest 与 proc 实参同步换 1500）。"""
    cap: dict = {}
    _install_fake_proc(monkeypatch, frames=_frames(), final=_final(),
                       capture=cap)
    body = {'sizes': [28], 'seed': 7, 'gate_mm': 1500,
            'params': {'d_ext': 1.0, 'd_int': 0.0, 'tol_ext': 0.0,
                       'tol_int': 0.0},
            'per_type': {'g01': {'d': 2.0, 'tol': 0.0}},
            'quantities': {'g01': {'28': 2}, 'g02': {'28': 1}}}
    r = gen_client.post(_GEN_URL, json=body)
    assert r.status_code == 200
    assert cap['solve_params'] == {
        'time_budget': 10, 'seed': 7, 'sizes': [28],
        'params': body['params'], 'per_type': body['per_type'],
        'quantities': body['quantities']}
    assert cap['gate_mm'] == 1500.0
    assert r.json()['manifest']['gate_mm'] == 1500.0


def test_generate_band_prefix_composite_section(gen_client, monkeypatch):
    """band/prefix 同开：composite 段（展开前组合视角 + demand_map）与 prefix 统计段
    在场，顶层 placed 仍展开视图；band/prefix 以 worker 形态（_parse_* 产物）透传。"""
    cap: dict = {}
    _install_fake_proc(monkeypatch, frames=_frames(composite_on_best=True),
                       final=_final(with_prefix=True), capture=cap)
    body = {'quantities': {'g01': {'28': 2}, 'g02': {'28': 2}},
            'band': {'enabled': True, 'label': 'g01'},
            'prefix': {'enabled': True, 'front': 'g01', 'back': 'g02'}}
    r = gen_client.post(_GEN_URL, json=body)
    assert r.status_code == 200
    resp = r.json()
    assert set(resp) == {'ok', 'manifest', 'placed', 'width_mm', 'density',
                         'composite', 'prefix'}
    best = _frames(composite_on_best=True)[-1]
    assert resp['composite'] == best['composite']
    assert any(it['id'].startswith('WB_')
               for it in resp['composite']['placed_items'])
    assert resp['prefix'] == _final(with_prefix=True)['prefix']
    assert not any(it['id'].startswith(('WB_', 'PS_'))
                   for it in resp['placed'])
    assert cap['band'] == {'label': 'g01'}
    assert cap['prefix'] == {'front': 'g01', 'back': 'g02'}
    assert cap['record_composite'] is True


# ------------------------------------------------------------ 会话/载荷错误矩阵

def test_generate_no_master_400(monkeypatch):
    """会话空/无母版（pieces 空 / gate_mm=0）→ 400「请先上传母版」，不起求解。"""
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update({'doc': None, 'gate_mm': 0.0, 'pieces': [],
                  'pieces_by_id': {}})
    cap: dict = {}
    _install_fake_proc(monkeypatch, frames=_frames(), final=_final(),
                       capture=cap)
    try:
        with TestClient(app) as client:
            r = client.post(_GEN_URL, json={})
            assert r.status_code == 400
            assert '请先上传母版' in r.json()['error']
    finally:
        state.clear()
        state.update(saved)
    assert cap == {}


def test_generate_sid_gate_401_400(gen_client, monkeypatch):
    """sid 过期（FakeClock 惰性逐出）→ 401 {code}；非法 sid → 400（edit-polish 同款）。"""
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    sid = 'abcd0001'
    gen_client.post('/api/session', headers={'X-Session-Id': sid})
    clk.advance(sessions.registry.ttl_sec + 1)
    r = gen_client.post(_GEN_URL, headers={'X-Session-Id': sid}, json={})
    assert r.status_code == 401
    assert r.json()['code'] == 'session_expired'
    r = gen_client.post(_GEN_URL, headers={'X-Session-Id': 'bad-sid!'}, json={})
    assert r.status_code == 400
    assert r.json() == {'error': 'sid 非法'}


def test_generate_band_prefix_invalid_400(gen_client, monkeypatch):
    """band/prefix 非法 → 400（routes_ws 单一校验点文案原样），不起求解。"""
    cap: dict = {}
    _install_fake_proc(monkeypatch, frames=_frames(), final=_final(),
                       capture=cap)
    for body, needle in (
            ({'band': {'enabled': True, 'label': 'g99'}}, '不存在于当前母版'),
            ({'band': {'enabled': True, 'label': 'bad!'}}, 'band.label'),
            ({'prefix': {'enabled': True, 'front': 'g01', 'back': 'g02'}},
             '资格码'),
            ({'prefix': {'enabled': True, 'front': 'g01', 'back': 'g01'}},
             '不同 g 码')):
        r = gen_client.post(_GEN_URL, json=body)
        assert r.status_code == 400, body
        assert needle in r.json()['error'], (body, r.json()['error'])
    assert cap == {}


def test_generate_body_errors_400(gen_client, monkeypatch):
    """body 非 JSON / 非 JSON 对象 / seed 非法 → 400（不起求解）。"""
    cap: dict = {}
    _install_fake_proc(monkeypatch, frames=_frames(), final=_final(),
                       capture=cap)
    r = gen_client.post(_GEN_URL, content=b'not-json',
                        headers={'Content-Type': 'application/json'})
    assert r.status_code == 400
    assert 'JSON' in r.json()['error']
    r = gen_client.post(_GEN_URL, json=[1, 2])
    assert r.status_code == 400
    assert 'JSON 对象' in r.json()['error']
    r = gen_client.post(_GEN_URL, json={'seed': 'abc'})
    assert r.status_code == 400
    assert 'seed' in r.json()['error']
    assert cap == {}


# ---------------------------------------------------------------- 求解失败 502

def test_generate_solve_failure_502(gen_client, monkeypatch):
    """求解失败（worker error / 意外退出）→ 502 {error: 中文}，单飞锁照常释放。"""
    _install_fake_proc(monkeypatch, frames=_frames(), final=None,
                       err='worker process exited unexpectedly (code=1)')
    r = gen_client.post(_GEN_URL, json={})
    assert r.status_code == 502
    assert '求解失败' in r.json()['error']
    assert 'code=1' in r.json()['error']
    assert routes_views_mod._INITIAL_LAYOUT_BUSY == {}


def test_generate_no_frames_or_manifest_502(gen_client, monkeypatch):
    """无任何可行帧 / manifest 缺席（理论退化形态）→ 502 中文，不 500。"""
    _install_fake_proc(monkeypatch, frames=[], final=_final())
    r = gen_client.post(_GEN_URL, json={})
    assert r.status_code == 502
    assert '未产生任何可行帧' in r.json()['error']

    def _no_manifest(pieces, gate_mm, solve_params, *, on_manifest,
                     on_report, **kw):
        on_report(_frames()[-1])
        return object(), _final(), 0.5, None
    monkeypatch.setattr(web_solver, 'solve_with_callback_proc', _no_manifest)
    r = gen_client.post(_GEN_URL, json={})
    assert r.status_code == 502
    assert 'manifest' in r.json()['error']


# --------------------------------------------------------------- 单飞 409

def test_generate_single_flight_409_cross_session_open(gen_client, monkeypatch):
    """同会话生成中再请求 → 409；跨会话并发放开（per-session 单飞）；完成后锁清空。"""
    sid1, sid2 = 'abcd0001', 'abcd0002'
    gen_client.post('/api/session', headers={'X-Session-Id': sid1})
    gen_client.post('/api/session', headers={'X-Session-Id': sid2})
    # 新注册 sid 会话 state 为空（commit 才有母版快照）→ 原位注入合成 state
    # （edit-polish sid 隔离测试同法 peek(sid).state.update）。
    sessions.registry.peek(sid1).state.update(_gen_state())
    sessions.registry.peek(sid2).state.update(_gen_state())
    started, gate_evt = threading.Event(), threading.Event()
    _install_fake_proc(monkeypatch, frames=_frames(), final=_final(),
                       started=started, gate_evt=gate_evt)
    results: dict = {}

    def _first():
        with TestClient(app) as c:
            results['first'] = c.post(_GEN_URL,
                                      headers={'X-Session-Id': sid1}, json={})

    th = threading.Thread(target=_first)
    th.start()
    try:
        assert started.wait(timeout=10)               # 第 1 请求已进求解（阻塞）
        r = gen_client.post(_GEN_URL, headers={'X-Session-Id': sid1}, json={})
        assert r.status_code == 409
        assert '生成中' in r.json()['error']
        assert routes_views_mod._INITIAL_LAYOUT_BUSY.get(sid1) is True
        # 跨会话：sid2 不受 sid1 单飞锁影响（fake 第 2 次调用不阻塞 → 直接 200）
        r2 = gen_client.post(_GEN_URL, headers={'X-Session-Id': sid2}, json={})
        assert r2.status_code == 200
        assert r2.json()['ok'] is True
        assert routes_views_mod._INITIAL_LAYOUT_BUSY.get(sid2) is None
    finally:
        gate_evt.set()
        th.join(timeout=10)
    assert results['first'].status_code == 200
    assert routes_views_mod._INITIAL_LAYOUT_BUSY == {}


# --------------------------------------------------------- edit_hold 顺手续期

def test_generate_edit_hold_refresh_on_success(gen_client, monkeypatch):
    """成功顺手 edit_hold.refresh(sid)（带 sid 续期 / default 豁免 / 502 失败不续期）。"""
    _install_fake_proc(monkeypatch, frames=_frames(), final=_final())
    sid = 'abcd0001'
    gen_client.post('/api/session', headers={'X-Session-Id': sid})
    sessions.registry.peek(sid).state.update(_gen_state())
    assert edit_hold.hold_until(sid) is None
    r = gen_client.post(_GEN_URL, headers={'X-Session-Id': sid}, json={})
    assert r.status_code == 200
    assert edit_hold.hold_until(sid) is not None

    # default（无 sid）不进钉住表
    r = gen_client.post(_GEN_URL, json={})
    assert r.status_code == 200
    assert edit_hold.hold_until('default') is None

    # 求解失败（502）不续期
    sid2 = 'abcd0002'
    gen_client.post('/api/session', headers={'X-Session-Id': sid2})
    sessions.registry.peek(sid2).state.update(_gen_state())
    _install_fake_proc(monkeypatch, frames=_frames(), final=None, err='boom')
    r = gen_client.post(_GEN_URL, headers={'X-Session-Id': sid2}, json={})
    assert r.status_code == 502
    assert edit_hold.hold_until(sid2) is None
