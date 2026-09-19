"""warmstart 引擎层校验/序列化/能力探测单测（US-001，prd-warm-start-phase1）。

夹具全合成（字符串 pid + 正整数 demand，全链路统一 placed 条目形态），
无 spyrrow/shapely/intermediate 依赖；``warm_start_supported`` 多态经
monkeypatch ``importlib.metadata.version`` 锁定（含 ``+ms0`` 误报回归锁）。
"""
from __future__ import annotations

import ast
import copy
import importlib.metadata
import json
from pathlib import Path

import pytest

from materialsorting.nesting_engine import warmstart
from materialsorting.nesting_engine.warmstart import (
    build_initial_solution,
    warm_start_supported,
)


def _pl(pid, rot=0.0, tr=None, **extra):
    it = {'id': pid, 'rotation': rot,
          'translation': [0.0, 0.0] if tr is None else tr}
    it.update(extra)
    return it


def _set_version(monkeypatch, version=None, exc=None):
    """monkeypatch importlib.metadata.version → 固定串 / 固定异常。"""
    def fake(name):
        if exc is not None:
            raise exc
        assert name == 'spyrrow'
        return version
    monkeypatch.setattr(importlib.metadata, 'version', fake)


# ------------------------------------------------------- AC#1 合法 round-trip

def test_valid_round_trip_exact_shape():
    """合法构造：多副本 + 乱序 + int 归一 float + 顺序保持，输出结构逐键对拍。"""
    placed = [
        {'id': 'g02_30', 'rotation': 180, 'translation': [120.5, 0]},
        {'id': 'g01_28', 'rotation': 0.0, 'translation': [0, 0]},
        {'id': 'g01_28', 'rotation': 90, 'translation': [10, 300.25]},
    ]
    out = build_initial_solution(placed, {'g01_28': 2, 'g02_30': 1}, 1500)
    assert out == {
        'strip_width': 1500.0,
        'placed_items': [
            {'id': 'g02_30', 'rotation': 180.0,
             'translation': [120.5, 0.0]},
            {'id': 'g01_28', 'rotation': 0.0,
             'translation': [0.0, 0.0]},
            {'id': 'g01_28', 'rotation': 90.0,
             'translation': [10.0, 300.25]},
        ],                              # 顺序 = 输入顺序（restore 确定性前提）
    }
    # 纯 JSON dict（Windows spawn pickle / Rust serde 双安全）
    assert json.loads(json.dumps(out)) == out


def test_multicopy_same_pid_pass():
    """demand 多副本：同 pid N 条（N == demand）合法通过。"""
    placed = [_pl('g01_28', tr=[float(i), 0.0]) for i in range(3)]
    out = build_initial_solution(placed, {'g01_28': 3}, 900)
    assert len(out['placed_items']) == 3
    assert [p['translation'][0] for p in out['placed_items']] == [0.0, 1.0, 2.0]


def test_empty_solution_valid():
    """空解（demand 空 + placed 空）合法：Σdemand=0 守恒平凡成立。"""
    assert build_initial_solution([], {}, 800.0) == \
        {'strip_width': 800.0, 'placed_items': []}


def test_extra_keys_whitelisted_out():
    """多余键白名单丢弃：输出条目恒三键（mirror:False 等价缺席放行）。"""
    placed = [_pl('g01_28', mirror=False, source='editor', label='g01')]
    out = build_initial_solution(placed, {'g01_28': 1}, 500)
    assert set(out['placed_items'][0]) == {'id', 'rotation', 'translation'}
    assert 'mirror' not in out['placed_items'][0]


def test_input_never_mutated():
    """输入不被改动（快照对拍）——调用方持有的 placed/demand_map 原样。"""
    placed = [_pl('g01_28', rot=45, tx=1, ty=2, mirror=False)]
    demand = {'g01_28': 1}
    snap_placed = copy.deepcopy(placed)
    snap_demand = copy.deepcopy(demand)
    build_initial_solution(placed, demand, 640.0)
    assert placed == snap_placed and demand == snap_demand


# --------------------------------------------------- AC#2/4 完整解硬约束

def test_partial_solution_rejected():
    """部分解拒绝（F2：restore 不补放新片，缺的片永远不会被放上）。"""
    placed = [_pl('g01_28'), _pl('g02_30')]     # g03_28 demand=1 缺席
    with pytest.raises(ValueError, match='不是完整解'):
        build_initial_solution(placed,
                               {'g01_28': 1, 'g02_30': 1, 'g03_28': 1}, 700)


def test_undercount_same_pid_rejected():
    """同 pid 条数 < demand 拒绝（demand=2 只放 1 条）。"""
    with pytest.raises(ValueError, match='不是完整解'):
        build_initial_solution([_pl('g01_28')], {'g01_28': 2}, 700)


def test_overcount_rejected():
    """超量解拒绝（同 pid 条数 > demand 同样破坏实例组成）。"""
    placed = [_pl('g01_28', tr=[0.0, 0.0]), _pl('g01_28', tr=[50.0, 0.0])]
    with pytest.raises(ValueError, match='不是完整解'):
        build_initial_solution(placed, {'g01_28': 1}, 700)


def test_unknown_pid_rejected():
    """未知 pid 拒绝（不在 demand_map 内）。"""
    with pytest.raises(ValueError, match='未知裁片'):
        build_initial_solution([_pl('g99_28')], {'g01_28': 1}, 700)


def test_mirror_rejected():
    """mirror: true 拒绝（sparrow 姿态无反射），消息含「含镜像片，无法热启动」。"""
    with pytest.raises(ValueError, match='含镜像片，无法热启动'):
        build_initial_solution([_pl('g01_28', mirror=True)],
                               {'g01_28': 1}, 700)


def test_mirror_dirty_truthy_rejected():
    """mirror 填脏真值（1）同拒 —— 防御性真值判定，不放行进 Rust。"""
    with pytest.raises(ValueError, match='含镜像片'):
        build_initial_solution([_pl('g01_28', mirror=1)],
                               {'g01_28': 1}, 700)


# ------------------------------------------------------- AC#2 畸形输入矩阵

@pytest.mark.parametrize('placed,demand,width,kw', [
    ({'id': 'g01_28'}, {'g01_28': 1}, 700, {'match': '应为列表'}),
    ('g01_28', {'g01_28': 1}, 700, {'match': '应为列表'}),
    (['g01_28'], {'g01_28': 1}, 700, {'match': '应为对象'}),
    ([None], {'g01_28': 1}, 700, {'match': '应为对象'}),
    ([{'rotation': 0, 'translation': [0, 0]}], {'g01_28': 1}, 700,
     {'match': '缺少字段'}),
    ([{'id': 'g01_28', 'translation': [0, 0]}], {'g01_28': 1}, 700,
     {'match': '缺少字段'}),
    ([{'id': 'g01_28', 'rotation': 0}], {'g01_28': 1}, 700,
     {'match': '缺少字段'}),
    ([_pl(1)], {'g01_28': 1}, 700, {'match': 'id 应为字符串'}),
    ([_pl(None)], {'g01_28': 1}, 700, {'match': 'id 应为字符串'}),
    ([_pl('g01_28', rot='0')], {'g01_28': 1}, 700, {'match': '应为数值'}),
    ([_pl('g01_28', rot=None)], {'g01_28': 1}, 700, {'match': '应为数值'}),
    ([_pl('g01_28', rot=True)], {'g01_28': 1}, 700, {'match': '应为数值'}),
    ([_pl('g01_28', rot=float('nan'))], {'g01_28': 1}, 700,
     {'match': '有限数值'}),
    ([_pl('g01_28', rot=float('inf'))], {'g01_28': 1}, 700,
     {'match': '有限数值'}),
    ([_pl('g01_28', tr=0.0)], {'g01_28': 1}, 700, {'match': 'translation 应为'}),
    ([_pl('g01_28', tr='xy')], {'g01_28': 1}, 700, {'match': 'translation 应为'}),
    ([_pl('g01_28', tr=[1])], {'g01_28': 1}, 700, {'match': '应为 2 元'}),
    ([_pl('g01_28', tr=[1, 2, 3])], {'g01_28': 1}, 700, {'match': '应为 2 元'}),
    ([_pl('g01_28', tr=[1, 'y'])], {'g01_28': 1}, 700, {'match': '应为数值'}),
    ([_pl('g01_28', tr=[True, 2])], {'g01_28': 1}, 700, {'match': '应为数值'}),
    ([_pl('g01_28', tr=[0, float('nan')])], {'g01_28': 1}, 700,
     {'match': '有限数值'}),
])
def test_malformed_placed_matrix(placed, demand, width, kw):
    """placed 侧畸形矩阵：全部 fail-fast ValueError（中文消息）。"""
    with pytest.raises(ValueError, **kw):
        build_initial_solution(placed, demand, width)


@pytest.mark.parametrize('demand', [
    ['g01_28'],                                  # 非字典
    None,
    {'g01_28': '2'},                            # demand 非整数
    {'g01_28': 1.5},
    {'g01_28': True},
    {'g01_28': 0},                              # 非正
    {'g01_28': -1},
])
def test_malformed_demand_map(demand):
    with pytest.raises(ValueError, match='需求映射'):
        build_initial_solution([_pl('g01_28')], demand, 700)


@pytest.mark.parametrize('width', [
    '1500', None, True, [1500], float('nan'), float('inf'), 0, -5.0,
])
def test_malformed_strip_width(width):
    with pytest.raises(ValueError):
        build_initial_solution([_pl('g01_28')], {'g01_28': 1}, width)


def test_shape_checked_before_counting():
    """畸形条目先于条数校验（第 0 条缺键时报形态错而非完整解错）。"""
    with pytest.raises(ValueError, match='缺少字段'):
        build_initial_solution(
            [{'id': 'g01_28', 'rotation': 0}], {'g01_28': 1}, 700)


# ------------------------------------------------ AC#3 能力探测多态矩阵

@pytest.mark.parametrize('version,expected', [
    ('0.9.0', False),              # PyPI 线上版：无 local tag
    ('0.8.2', False),
    ('0.9.0+ms0', False),          # ★回归锁：纯重建 wheel 无 initial_solution
    ('0.9.0+ms1', True),           # A1 落地首版
    ('0.9.0+ms2', True),
    ('0.9.0+ms10', True),          # 两位数 N
    ('0.2.0+ms3', True),           # 版本号无关，只看 local tag
    ('0.9.0+msfoo', False),        # tag 非数字形态
    ('0.9.0+local', False),        # 其他 local tag
    ('0.9.0+MS1', False),          # 大小写敏感（PEP 440 local 归一小写，
                                   # 此处按原串保守不认）
])
def test_warm_start_supported_matrix(monkeypatch, version, expected):
    """版本串多态：+ms<N> 且 N≥1 才 True（含 +ms0 误报回归锁）。"""
    _set_version(monkeypatch, version=version)
    assert warm_start_supported() is expected


def test_warm_start_supported_package_missing(monkeypatch):
    """包不存在（PackageNotFoundError）→ False 绝不抛。"""
    _set_version(monkeypatch,
                 exc=importlib.metadata.PackageNotFoundError('spyrrow'))
    assert warm_start_supported() is False


def test_warm_start_supported_weird_exception(monkeypatch):
    """任何异常（含非预期 RuntimeError）→ False 绝不抛。"""
    _set_version(monkeypatch, exc=RuntimeError('metadata 坏了'))
    assert warm_start_supported() is False


def test_warm_start_supported_real_env_returns_bool():
    """真实装载态（本机 0.9.0+ms0）探测不抛且返回 bool。"""
    assert isinstance(warm_start_supported(), bool)


# --------------------------------------------------------------- AC#5 分层

def test_module_layering_purity():
    """分层未反向：warmstart.py 模块级 import 只 stdlib（无 spyrrow/
    shapely 运行时依赖），禁 import web/cli（AST 守卫，镜像
    tests/test_polish.py 套路）。"""
    src = Path(warmstart.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'importlib', 'json', 'math', 're', 'sys',
               'collections'}
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert not mod.startswith('materialsorting.web'), \
                '模块级禁止 import web（分层单向）'
            assert not mod.startswith('materialsorting.cli'), \
                '模块级禁止 import cli（分层单向）'
            names = {mod.split('.')[0]}
        else:
            continue
        imported |= names
        assert names <= allowed, sorted(names - allowed)
    # 实际 import 了东西（守卫自身有效性哨兵）
    assert imported, 'AST 守卫未扫到任何 import，守卫失效'
    # 源级哨兵：任何 web/cli 引用（含函数内延迟 import）都不允许
    assert 'materialsorting.web' not in src and 'materialsorting.cli' not in src
    assert 'from ..web' not in src and 'from .web' not in src
    assert 'from ..cli' not in src and 'from .cli' not in src


# ------------------------------------------------------------- AC#6 冒烟

def test_smoke_main_pass(capsys):
    """`python -m` 冒烟同一代码路径：合成夹具自检全过 exit 0。"""
    assert warmstart.main([]) == 0
    out = capsys.readouterr().out
    assert 'PASS' in out
    assert 'FAIL' not in out
