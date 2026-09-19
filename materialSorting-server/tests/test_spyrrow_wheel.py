# -*- coding: utf-8 -*-
"""scripts/spyrrow_wheel.py 双源切换助手护栏（US-004，prd-warm-start-phase1）。

纯桩测试（不真跑 pip、不动 .venv）：subprocess.run 桩 + importlib.metadata
version 桩（共享模块对象 monkeypatch，test_warmstart.py 同款套路）。真 pip
happy path 已在 US-004 验收窗口用 ms0 wheel 实装走查（同版本重装，终态与
钉板一致），此处只锁命令形态与分支行为：
- status：repo 根直跑 exit 0 + 关键诊断行齐（解释器/版本/源/warm 探测/钉板）；
- use-local：路径不存在/非 .whl/非 spyrrow 发行版三类清晰报错 exit 1 且
  **绝不触碰 pip**（PRD AC）；pip 桩下安装参数精确对拍（--force-reinstall
  --no-deps + 绝对路径）、读回 invalidate 缓存、钉板漂移提示块；
- use-pypi：安装参数精确对拍（--force-reinstall spyrrow==0.9.0）、回退口径
  提示、钉板不动口径。
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / 'scripts' / 'spyrrow_wheel.py'


def _load_script():
    spec = importlib.util.spec_from_file_location('ms_spyrrow_wheel_script',
                                                  _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def sw():
    return _load_script()


@pytest.fixture()
def no_pip(monkeypatch):
    """哨兵：任何 pip 子进程调用都视为测试失败（错误路径绝不装东西）。"""
    def _boom(run_cmd, **kw):
        raise AssertionError(f'错误路径不应触发 pip：{run_cmd}')
    monkeypatch.setattr(subprocess, 'run', _boom)


class _FakeRun:
    """subprocess.run 桩：记录调用、按剧本返回退出码、输出不入终端。"""

    def __init__(self, rc=0):
        self.rc = rc
        self.calls = []

    def __call__(self, run_cmd, **kw):
        self.calls.append(run_cmd)
        return subprocess.CompletedProcess(args=run_cmd, returncode=self.rc)


# ------------------------------------------------- 纯函数：解析与判源

@pytest.mark.parametrize('filename,expect', [
    ('spyrrow-0.9.0+ms1-cp311-cp311-win_amd64.whl', '0.9.0+ms1'),
    ('spyrrow-0.9.0+ms0-cp311-cp311-win_amd64.whl', '0.9.0+ms0'),
    ('spyrrow-0.2.0+ms3-cp311-cp311-win_amd64.whl', '0.2.0+ms3'),
    ('spyrrow-1.0.0-py3-none-any.whl', '1.0.0'),
    ('spyrrow-0.9.0+ms1-cp311-cp311-win_amd64.tar.gz', None),   # 非 wheel
    ('shapely-2.1.2-cp311-cp311-win_amd64.whl', None),          # 非发行版
    ('spyrrow-0.9.0.whl', None),                                # 段数不足
    ('spyrrow.whl', None),
])
def test_parse_wheel_version(sw, filename, expect):
    assert sw._parse_wheel_version(filename) == expect


@pytest.mark.parametrize('version,src_frag,tag', [
    ('0.9.0', 'PyPI 线上版', None),
    ('0.9.1', 'PyPI 线上版', None),
    ('0.9.0+ms0', '私有 wheel', '0'),
    ('0.9.0+ms1', '私有 wheel', '1'),
    ('0.2.0+ms3', '私有 wheel', '3'),
    ('0.9.0+msfoo', 'PyPI 线上版', None),   # 非数值 tag 不算私有源
    ('0.9.0+local', 'PyPI 线上版', None),
    (None, '未安装', None),
])
def test_classify(sw, version, src_frag, tag):
    src, got_tag = sw._classify(version)
    assert src_frag in src
    assert got_tag == tag


def test_pin_path_points_into_repo(sw):
    assert sw.PIN_PATH.name == 'spyrrow_build.json'
    assert sw.PIN_PATH.parent.name == 'materialSorting-server'
    pin = sw._load_pin()
    assert pin is not None                      # 入库态：钉板恒可读
    for key in ('spyrrow_ms_commit', 'sparrow_rev', 'wheel_version',
                'built_at'):
        assert key in pin


# ------------------------------------------------- status（真环境，结构性断言）

def test_status_repo_root_exit0(sw, capsys):
    assert sw.cmd_status() == 0
    out = capsys.readouterr().out
    for needle in ('解释器', '已装版本', '安装源', 'warm_start_supported()',
                   '钉板 spyrrow_build.json', 'wheel_version', '一致性'):
        assert needle in out


def test_main_no_args_defaults_to_status(sw, capsys):
    assert sw.main([]) == 0
    assert 'spyrrow 双源状态' in capsys.readouterr().out


# ------------------------------------------------- use-local 错误路径（绝不碰 pip）

def test_use_local_missing_path(sw, capsys, no_pip, tmp_path):
    rc = sw.main(['use-local', str(tmp_path / 'nope' / 'missing.whl')])
    assert rc == 1
    err = capsys.readouterr().err
    assert 'wheel 路径不存在' in err
    assert '用法' in err                                # 指路真实 wheel 路径示例


def test_use_local_not_a_whl(sw, capsys, no_pip, tmp_path):
    bad = tmp_path / 'notes.txt'
    bad.write_text('x', encoding='utf-8')
    rc = sw.main(['use-local', str(bad)])
    assert rc == 1
    assert '不是 wheel 文件' in capsys.readouterr().err


def test_use_local_wrong_distribution(sw, capsys, no_pip, tmp_path):
    bad = tmp_path / 'shapely-2.1.2-cp311-cp311-win_amd64.whl'
    bad.write_bytes(b'')
    rc = sw.main(['use-local', str(bad)])
    assert rc == 1
    err = capsys.readouterr().err
    assert '不是 spyrrow 发行版的 wheel' in err
    assert '破坏 .venv' in err                          # 说明拒装理由


# ------------------------------------------------- use-local / use-pypi 桩剧本

def _pin(sw, monkeypatch, tmp_path, wheel_version):
    """把钉板 mock 成临时文件（钉板是仓库真实状态 —— ms1 交付后与测试剧本
    写死的 ms0 态脱钩，不 mock 会环境耦合误报；对齐 no_pip/_FakeRun 桩套路）。"""
    pin = tmp_path / 'spyrrow_build.json'
    pin.write_text(json.dumps({
        'spyrrow_ms_commit': '0' * 40,
        'sparrow_rev': '881cdcbd' + '0' * 32,
        'wheel_version': wheel_version,
        'built_at': '2026-09-19T00:00:00+08:00',
    }), encoding='utf-8')
    monkeypatch.setattr(sw, 'PIN_PATH', pin)


def test_use_local_happy_path_and_pin_prompt(sw, capsys, monkeypatch, tmp_path):
    wheel = tmp_path / 'spyrrow-0.9.0+ms1-cp311-cp311-win_amd64.whl'
    wheel.write_bytes(b'')
    _pin(sw, monkeypatch, tmp_path, '0.9.0+ms0')       # 钉板旧 → 装 ms1 漂移提示
    fake = _FakeRun(rc=0)
    monkeypatch.setattr(subprocess, 'run', fake)
    monkeypatch.setattr(importlib.metadata, 'version',
                        lambda name: '0.9.0+ms1' if name == 'spyrrow' else '?')
    rc = sw.main(['use-local', str(wheel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert fake.calls == [[sys.executable, '-m', 'pip', 'install',
                           '--force-reinstall', '--no-deps', str(wheel)]]
    assert '读回版本：0.9.0+ms1' in out                  # invalidate 缓存后读回
    assert 'warm_start_supported() = True' in out        # 探测跟随假 ms1
    assert '真顺延已可用' in out
    assert '[提示更新钉板]' in out                        # 钉板仍 ms0 → 漂移提示
    assert '"wheel_version": "0.9.0+ms1"' in out         # 模板带新版本
    assert 'spyrrow_ms_commit' in out                    # 四字段模板齐全


def test_use_local_same_version_no_prompt(sw, capsys, monkeypatch, tmp_path):
    wheel = tmp_path / 'spyrrow-0.9.0+ms0-cp311-cp311-win_amd64.whl'
    wheel.write_bytes(b'')
    _pin(sw, monkeypatch, tmp_path, '0.9.0+ms0')       # 钉板同版 → 一致无提示
    monkeypatch.setattr(subprocess, 'run', _FakeRun(rc=0))
    monkeypatch.setattr(importlib.metadata, 'version',
                        lambda name: '0.9.0+ms0' if name == 'spyrrow' else '?')
    rc = sw.main(['use-local', str(wheel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '无需更新' in out
    assert '[提示更新钉板]' not in out


def test_use_local_pip_failure_propagates(sw, capsys, monkeypatch, tmp_path):
    wheel = tmp_path / 'spyrrow-0.9.0+ms1-cp311-cp311-win_amd64.whl'
    wheel.write_bytes(b'')
    monkeypatch.setattr(subprocess, 'run', _FakeRun(rc=3))
    monkeypatch.setattr(importlib.metadata, 'version',
                        lambda name: '0.9.0+ms0' if name == 'spyrrow' else '?')
    rc = sw.main(['use-local', str(wheel)])
    assert rc == 3                                       # pip 退出码透传
    assert 'pip 失败' in capsys.readouterr().err


def test_use_pypi_command_shape(sw, capsys, monkeypatch):
    fake = _FakeRun(rc=0)
    monkeypatch.setattr(subprocess, 'run', fake)
    monkeypatch.setattr(importlib.metadata, 'version',
                        lambda name: '0.9.0' if name == 'spyrrow' else '?')
    rc = sw.main(['use-pypi'])
    assert rc == 0
    out = capsys.readouterr().out
    assert fake.calls == [[sys.executable, '-m', 'pip', 'install',
                           '--force-reinstall', 'spyrrow==0.9.0']]
    assert '读回版本：0.9.0' in out
    assert '回退' in out and 'unsupported' in out         # warm 降级口径提示
    assert '钉板不动' in out


def test_use_pypi_failure_propagates(sw, capsys, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', _FakeRun(rc=2))
    rc = sw.main(['use-pypi'])
    assert rc == 2
    assert 'pip 失败' in capsys.readouterr().err
