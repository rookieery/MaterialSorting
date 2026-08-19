"""US-001 ``cli/config.py`` 配置加载与校验单测。

覆盖 PRD 验收标准：
  1. 示例配置 data/configs/5336_coded_sizes32-38.json 加载成功（sizes/gate_mm/seeds/
     quantities 键类型/master_dxf 绝对存在路径），且相对路径解析与 CWD 无关（仓库根兜底）。
  2. 各类错误配置抛 ConfigError 且消息含出错字段名：未知顶层键（含旧 seed 三键）、
     master_dxf 不存在（列两个候选绝对路径）、sizes 含字符串、seeds 空列表/负数/非整数/
     重复项、per_type 非 g 码键/未知内键/负值、quantities 字符串数量/坏码号键/负数、
     gate_mm<=0、time 非正整数。
  3. per_type 超全局上限（d>10 / tol>45）不抛错但 UserWarning 引用
     MAX_OVERLAP_MM / MAX_ROTATION_TOL_DEG 并说明将被钳制；恰好等于上限不警告。
  4. 模块纯度：模块级 import 仅标准库（AST 结构断言）、``python -m`` 运行无副作用、
     ConfigError 是 ValueError 子类。
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths
from materialsorting.cli.config import ConfigError, NestRunConfig, load_config

_REPO_ROOT = Path(paths.REPO_DIR)
_EXAMPLE_CFG = _REPO_ROOT / 'data' / 'configs' / '5336_coded_sizes32-38.json'


def _write_cfg(tmp_path: Path, payload) -> Path:
    p = tmp_path / 'cfg.json'
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return p


@pytest.fixture
def base_payload(tmp_path: Path) -> dict:
    """自包含合法基线：master_dxf 指向 tmp 下真实存在的哑文件（不依赖仓库 data/）。"""
    dummy = tmp_path / 'master.dxf'
    dummy.write_text('dummy', encoding='utf-8')
    return {
        'master_dxf': str(dummy),
        'sizes': [32, 33],
        'gate_mm': 1980,
        'time': 5,
        'seeds': [0],
        'per_type': {'g01': {'d': 0, 'tol': 0}},
        'quantities': {'g01': {'32': 1, 'null': 1}},
    }


def _must_fail(payload, tmp_path: Path, field: str, *msg_parts: str):
    with pytest.raises(ConfigError, match=field) as ei:
        load_config(_write_cfg(tmp_path, payload))
    text = str(ei.value)
    for part in msg_parts:
        assert part in text, f'报错消息缺 {part!r}: {text}'
    return text


# ------------------------------------------------------------------ AC#1 成功路径

def test_load_example_config():
    cfg = load_config(_EXAMPLE_CFG)
    assert isinstance(cfg, NestRunConfig)
    assert cfg.sizes == [32, 33, 34, 35, 36, 37, 38]
    assert cfg.gate_mm == 1980
    assert cfg.seeds == [0]
    assert cfg.time == 300
    assert cfg.master_dxf.is_absolute() and cfg.master_dxf.is_file()
    assert cfg.master_dxf.name == '5336#老六订单14%7%围加9_coded.dxf'
    # quantities 键类型 dict[str, dict[str, int]]（sizeKey 全字符串、数量全 int）
    assert isinstance(cfg.quantities, dict)
    for label, size_map in cfg.quantities.items():
        assert isinstance(label, str) and label.startswith('g')
        assert isinstance(size_map, dict)
        for sk, n in size_map.items():
            assert isinstance(sk, str)
            assert isinstance(n, int) and not isinstance(n, bool)
    assert set(cfg.per_type) == {f'g{i:02d}' for i in range(1, 11)}
    assert all(v == {'d': 0.0, 'tol': 0.0} for v in cfg.per_type.values())


def test_master_dxf_relative_resolution_cwd_then_repo_root(tmp_path, monkeypatch):
    """相对路径先试 CWD 再试仓库根：① CWD 命中 ② CWD 未命中但仓库根命中 ③ 均失败报错。"""
    # ① CWD（tmp）下存在 → 用 CWD 候选
    (tmp_path / 'masters').mkdir()
    (tmp_path / 'masters' / 'm.dxf').write_text('x', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    payload = {'master_dxf': 'masters/m.dxf', 'gate_mm': 1980}
    cfg = load_config(_write_cfg(tmp_path, payload))
    assert cfg.master_dxf == (tmp_path / 'masters' / 'm.dxf').resolve()

    # ② CWD 下无 data/… 但仓库根有（示例母版）→ 仓库根候选兜底
    payload = {'master_dxf': 'data/5336#老六订单14%7%围加9_coded.dxf', 'gate_mm': 1980}
    cfg = load_config(_write_cfg(tmp_path, payload))
    assert cfg.master_dxf == (_REPO_ROOT / 'data' /
                              '5336#老六订单14%7%围加9_coded.dxf').resolve()

    # ③ 两候选均失败 → 报错列出两个候选绝对路径
    payload = {'master_dxf': 'data/不存在.dxf', 'gate_mm': 1980}
    with pytest.raises(ConfigError) as ei:
        load_config(_write_cfg(tmp_path, payload))
    msg = str(ei.value)
    assert 'master_dxf' in msg
    assert str((tmp_path / 'data' / '不存在.dxf').resolve()) in msg
    assert str((_REPO_ROOT / 'data' / '不存在.dxf').resolve()) in msg


def test_defaults_for_optional_keys(base_payload, tmp_path):
    """可选键缺省：sizes=None（不过滤）、time=300、seeds=[0]、per_type={}、quantities=None。"""
    for k in ('sizes', 'time', 'seeds', 'per_type', 'quantities'):
        base_payload.pop(k)
    cfg = load_config(_write_cfg(tmp_path, base_payload))
    assert cfg.sizes is None
    assert cfg.time == 300
    assert cfg.seeds == [0]
    assert cfg.per_type == {}
    assert cfg.quantities is None


# ------------------------------------------------------------------ AC#2 错误路径

@pytest.mark.parametrize('bad_key', ['seed', 'multi_seed', 'seed_count', 'multiSeed'])
def test_unknown_top_level_keys(base_payload, tmp_path, bad_key):
    """未知顶层键报错且消息含该键名；旧 seed 三键附迁移提示。"""
    base_payload[bad_key] = 1
    text = _must_fail(base_payload, tmp_path, bad_key, '合法键')
    if bad_key in ('seed', 'multi_seed', 'seed_count'):
        assert 'seeds' in text          # 迁移提示指向新字段


def test_missing_required_keys(base_payload, tmp_path):
    for k in ('master_dxf', 'gate_mm'):
        p = {kk: vv for kk, vv in base_payload.items() if kk != k}
        _must_fail(p, tmp_path, k, '必填')


def test_master_dxf_errors(base_payload, tmp_path):
    _must_fail({**base_payload, 'master_dxf': 123}, tmp_path, 'master_dxf')
    # 绝对路径不存在 → 直接报该路径
    gone = tmp_path / 'gone.dxf'
    text = _must_fail({**base_payload, 'master_dxf': str(gone)}, tmp_path, 'master_dxf')
    assert str(gone) in text


def test_sizes_errors(base_payload, tmp_path):
    _must_fail({**base_payload, 'sizes': [32, '33']}, tmp_path, 'sizes', 'JSON 整数')
    _must_fail({**base_payload, 'sizes': '32-38'}, tmp_path, 'sizes')
    _must_fail({**base_payload, 'sizes': []}, tmp_path, 'sizes', '空列表')
    _must_fail({**base_payload, 'sizes': [32, True]}, tmp_path, 'sizes')
    _must_fail({**base_payload, 'sizes': [32.5]}, tmp_path, 'sizes')


def test_seeds_errors(base_payload, tmp_path):
    _must_fail({**base_payload, 'seeds': []}, tmp_path, 'seeds', '空列表')
    _must_fail({**base_payload, 'seeds': [0, -1]}, tmp_path, 'seeds', '负')
    _must_fail({**base_payload, 'seeds': [0, 1.5]}, tmp_path, 'seeds')
    _must_fail({**base_payload, 'seeds': [0, True]}, tmp_path, 'seeds')
    _must_fail({**base_payload, 'seeds': [0, '1']}, tmp_path, 'seeds')
    _must_fail({**base_payload, 'seeds': [0, 0]}, tmp_path, 'seeds', '重复')
    _must_fail({**base_payload, 'seeds': 0}, tmp_path, 'seeds')


def test_per_type_errors(base_payload, tmp_path):
    _must_fail({**base_payload, 'per_type': {'front': {}}}, tmp_path, 'per_type', 'front')
    _must_fail({**base_payload, 'per_type': {'G01': {}}}, tmp_path, 'per_type', 'G01')
    _must_fail({**base_payload, 'per_type': {'g1234': {}}}, tmp_path, 'per_type')
    _must_fail({**base_payload, 'per_type': {'g01': 5}}, tmp_path, 'per_type.g01')
    _must_fail({**base_payload, 'per_type': {'g01': {'d_ext': 1}}}, tmp_path,
               'per_type.g01', 'd_ext')
    _must_fail({**base_payload, 'per_type': {'g01': {'d': -1}}}, tmp_path, 'per_type.g01')
    _must_fail({**base_payload, 'per_type': {'g01': {'tol': '5'}}}, tmp_path, 'per_type.g01')
    _must_fail({**base_payload, 'per_type': []}, tmp_path, 'per_type')


def test_quantities_errors(base_payload, tmp_path):
    # AC 核心用例：数量为字符串 "1" → 提示 JSON 应写数字
    text = _must_fail({**base_payload, 'quantities': {'g01': {'32': '1'}}}, tmp_path,
                      'quantities', 'JSON 数字', '"1"')
    # 码号键非数字字符串/非 null
    _must_fail({**base_payload, 'quantities': {'g01': {'三二': 1}}}, tmp_path, 'quantities')
    _must_fail({**base_payload, 'quantities': {'g01': {'3a': 1}}}, tmp_path, 'quantities')
    # 负数 / 非整数份数 / 值非对象 / 外层非 g 码键
    _must_fail({**base_payload, 'quantities': {'g01': {'32': -1}}}, tmp_path, 'quantities')
    _must_fail({**base_payload, 'quantities': {'g01': {'32': 1.5}}}, tmp_path, 'quantities')
    _must_fail({**base_payload, 'quantities': {'g01': 3}}, tmp_path, 'quantities.g01')
    _must_fail({**base_payload, 'quantities': {'front': {'32': 1}}}, tmp_path, 'quantities')
    _must_fail({**base_payload, 'quantities': []}, tmp_path, 'quantities')


def test_gate_mm_errors(base_payload, tmp_path):
    _must_fail({**base_payload, 'gate_mm': 0}, tmp_path, 'gate_mm')
    _must_fail({**base_payload, 'gate_mm': -1980}, tmp_path, 'gate_mm')
    _must_fail({**base_payload, 'gate_mm': '1980'}, tmp_path, 'gate_mm')
    _must_fail({**base_payload, 'gate_mm': None}, tmp_path, 'gate_mm')


def test_time_errors(base_payload, tmp_path):
    _must_fail({**base_payload, 'time': 0}, tmp_path, 'time')
    _must_fail({**base_payload, 'time': -5}, tmp_path, 'time')
    _must_fail({**base_payload, 'time': '300'}, tmp_path, 'time')
    _must_fail({**base_payload, 'time': 300.5}, tmp_path, 'time')


def test_config_file_errors(tmp_path):
    with pytest.raises(ConfigError, match='配置文件不存在'):
        load_config(tmp_path / 'nope.json')
    bad = tmp_path / 'bad.json'
    bad.write_text('{"gate_mm": 1980,}', encoding='utf-8')
    with pytest.raises(ConfigError, match='合法 JSON'):
        load_config(bad)
    arr = tmp_path / 'arr.json'
    arr.write_text('[1, 2]', encoding='utf-8')
    with pytest.raises(ConfigError, match='JSON 对象'):
        load_config(arr)


def test_config_error_is_value_error():
    assert issubclass(ConfigError, ValueError)


# ------------------------------------------------------------------ AC#3 上限警告

def test_per_type_over_caps_warns(base_payload, tmp_path):
    """d>10 / tol>45 不抛错，警告引用全局上限常量名并说明将被钳制。"""
    base_payload['per_type'] = {'g03': {'d': 11, 'tol': 46}}
    with pytest.warns(UserWarning) as records:
        cfg = load_config(_write_cfg(tmp_path, base_payload))
    assert cfg.per_type['g03'] == {'d': 11.0, 'tol': 46.0}
    texts = [str(r.message) for r in records]
    assert any('MAX_OVERLAP_MM' in t and '钳制' in t for t in texts)
    assert any('MAX_ROTATION_TOL_DEG' in t and '钳制' in t for t in texts)
    assert any('per_type.g03' in t for t in texts)


def test_per_type_at_caps_no_warn(base_payload, tmp_path):
    """恰好等于全局上限（d=10 / tol=45）不警告（钳制边界含端点）。"""
    base_payload['per_type'] = {'g03': {'d': 10, 'tol': 45}}
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        load_config(_write_cfg(tmp_path, base_payload))


# ------------------------------------------------------------------ AC#4 模块纯度

def test_module_level_imports_stdlib_only():
    """AST 断言：模块级 import 仅标准库、无相对 import、无 materialsorting 包 import。"""
    import materialsorting.cli.config as cli_config
    src = Path(cli_config.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split('.')[0] in sys.stdlib_module_names, alias.name
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, '模块级不允许相对 import（兄弟包依赖走函数内延迟 import）'
            assert (node.module or '').split('.')[0] in sys.stdlib_module_names, node.module


def test_run_as_module_no_side_effects():
    """``python -m materialsorting.cli.config`` 直接运行：退出码 0、零输出（无副作用）。"""
    import os
    env = {**os.environ, 'PYTHONPATH': str(_SRC)}
    r = subprocess.run([sys.executable, '-m', 'materialsorting.cli.config'],
                       capture_output=True, env=env, cwd=str(_REPO_ROOT), timeout=60)
    assert r.returncode == 0
    assert r.stdout == b''
    assert r.stderr == b''
