"""初始布局 web 侧 warm 载荷装载点 + 热启动能力探测端点测试（US-001，prd-initial-layout）。

夹具全合成（2 片矩形，与 conftest/test_warmstart_chain 同构），能力探测经
monkeypatch ``warmstart.warm_start_supported`` 打桩（initial_layout 按调用时模块
属性取函数 → 桩生效），PyPI 0.9.0 / ms0 装载态同样全绿。

覆盖：
1. ``build_warm_payload`` 装载点：plain round-trip 精确结构（多副本/int→float/
   顺序保持/JSON 可序列化/gate_mm 在场不入载荷 = 契约两键哨兵）；strip_width 与
   ``build_pid_meta → _raw_polygon_map → _physical_width_mm`` 权威链对拍；demand
   投影与 worker 实例宇宙同口径（sizes 过滤 / quantities demand=0 出局）；降级
   矩阵（mirror / 条数≠demand / pid 需求映射外前置复检 / placed 空·非列表 /
   无母版 / 脏 pieces 不抛 / demand_map 非 dict / unsupported 判定序首位脏输入
   不抛）；组合宇宙 demand_map 直用（pid_meta 投影未被采用 + WB_ 原样进载荷）+
   组合条目不计包络（measurable-only 政策锁）；
2. ``warm_capability``：形态 ``{supported: bool, version: str}`` / 版本串
   monkeypatch 多态 / 包缺失哨兵 ``'(未安装)'`` 恒不抛；
3. ``GET /api/warm-capability``（TestClient）：恒 200 / 无会话闸门（bogus sid
   同样 200 —— 能力是进程级属性）/ 能力态透传（monkeypatch 生效）；
4. 分层纯度（AST 守卫，镜像 test_web_edit_hold 套路）：仅 stdlib + web 兄弟
   solver + nesting_engine.warmstart，禁 import server/cli（含函数内延迟）；
5. 冒烟 ``main`` exit 0（``python -m`` 同一代码路径）。
"""
from __future__ import annotations

import ast
import importlib.metadata
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from materialsorting.nesting_engine import warmstart
from materialsorting.web import initial_layout
from materialsorting.web.initial_layout import build_warm_payload, warm_capability
from materialsorting.web.server import app
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
