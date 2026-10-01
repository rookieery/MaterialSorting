"""机器对接浏览器直连 Origin 白名单 machine_cors（US-001）测试。

覆盖：
1. AST 守卫：模块级仅标准库 + ``..paths``（镜像 test_web_keygate 先例），
   禁 import server（依赖方向 server → machine_cors 单向无环）/ 禁 import
   cli 子包（web 禁反向依赖上层）；
2. 三档优先序：env（逗号/分号多值解析）→ sidecar（frozen = exe 旁优先 →
   LICENSE_DIR 回落 / dev = LICENSE_DIR）→ 皆无 ``None``；
3. 多值解析：env 混合分隔符 / sidecar 多行 strip 空行 / set 去重；
4. 空文件回落：某位置文件存在但全空行 = 该位未配置，继续向后回落；
5. frozen 双位置对拍（keygate 冒烟 keygate.py:498-523 先例写法：
   ``sys.frozen=True`` + 临时 exe 路径 monkeypatch）；
6. 请求时读取（非 import 期绑定）+ ``paths.LICENSE_DIR`` 调用时取值；
7. ``describe_machine_allowed_origins`` 三档来源标注；
8. ``python -m materialsorting.web.machine_cors`` 子进程冒烟 exit 0
   （输出含来源标注）。
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.web import machine_cors


# ----------------------------------------------------------------- fixtures

@pytest.fixture
def license_dir(tmp_path, monkeypatch):
    """LICENSE_DIR 重定向到 tmp（machine_cors 调用时取 ``paths.LICENSE_DIR``
    模块属性）。"""
    target = tmp_path / 'license'
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(target))
    return target


@pytest.fixture
def no_origins(tmp_path, monkeypatch):
    """白名单链归零：无 env、未冻结、LICENSE_DIR 指空 tmp（防真实
    out/license/ 漏读串档，keygate no_server_url 同款）。"""
    monkeypatch.delenv(machine_cors.MACHINE_ORIGINS_ENV, raising=False)
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(tmp_path / 'license'))


# ------------------------------------------------------------- AST 守卫（分层）

def test_machine_cors_module_layering_purity():
    """machine_cors 模块级仅标准库 + ``..paths``；禁 import server（依赖方向
    server → machine_cors 单向无环）/ 禁 import cli 子包（镜像 keygate 守卫）。"""
    src = Path(machine_cors.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'os', 'sys', 'pathlib', 'materialsorting'}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue          # 函数/类体内延迟 import（_smoke 的 tempfile）不受顶层约束
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                names = {a.name.split('.')[0] for a in sub.names}
            elif isinstance(sub, ast.ImportFrom):
                mod = sub.module or ''
                assert not mod.startswith('materialsorting.web.server'), \
                    'machine_cors 禁 import server（依赖方向 server → machine_cors）'
                assert not mod.startswith('materialsorting.cli'), \
                    'machine_cors 禁 import cli（web 禁反向依赖上层）'
                if sub.level:                 # 相对 import 解析到上层 paths
                    names = {'materialsorting'}
                else:
                    names = {mod.split('.')[0]}
            else:
                continue
            assert names <= allowed, sorted(names - allowed)
    # 相对 import 白名单（任意位置）：仅顶层 ``..paths``
    for sub in ast.walk(tree):
        if isinstance(sub, ast.ImportFrom) and sub.level:
            # ``from .. import paths``（module=None）与 ``from ..paths import X`` 两形态
            ok = sub.level == 2 and sub.module in (None, 'paths')
            assert ok, f'相对 import 仅 ..paths 允许：{sub.module}'
    # 源级哨兵：任何 server / cli 引用（含函数内延迟 import）都不允许
    assert 'materialsorting.web.server' not in src
    assert 'materialsorting.cli' not in src
    assert 'from .server' not in src


def test_env_names_locked():
    """env 变量名 / sidecar 文件名契约锁定（US-004 交付链与 YL 文档消费）。"""
    assert machine_cors.MACHINE_ORIGINS_ENV == 'MS_MACHINE_ALLOWED_ORIGINS'
    assert machine_cors.MACHINE_ORIGINS_FILE_NAME == 'machine_allowed_origins.txt'


# ------------------------------------------------------------- 档一 env

def test_env_single_value(no_origins, monkeypatch):
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://yl.example.com')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://yl.example.com'}


def test_env_multi_value_comma_and_semicolon(no_origins, monkeypatch):
    """env 多值：逗号/分号混合分隔 + 逐项 strip。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://a.example.com, https://b.example.com;'
                       '  https://c.example.com  ')
    assert machine_cors.resolve_machine_allowed_origins() == {
        'https://a.example.com', 'https://b.example.com',
        'https://c.example.com'}


def test_env_duplicates_deduped(no_origins, monkeypatch):
    """重复 Origin 去重（set 口径）。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://a.example.com,https://a.example.com')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://a.example.com'}


def test_env_blank_is_absent(no_origins, monkeypatch):
    """空白串 env 视为未配置（不与 sidecar 抢档）。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV, '   ')
    assert machine_cors.resolve_machine_allowed_origins() is None


def test_env_beats_sidecar(no_origins, license_dir, monkeypatch):
    """档序锁定：env 优先于 sidecar（两档并存取 env）。"""
    license_dir.mkdir(parents=True, exist_ok=True)
    (license_dir / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://lic.example.com', encoding='utf-8')
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://env.example.com')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://env.example.com'}


def test_env_unset_falls_to_absent(no_origins):
    """无 env 无 sidecar → None（零回归现状档）。"""
    assert machine_cors.resolve_machine_allowed_origins() is None


def test_resolve_request_time_not_import_bound(no_origins, monkeypatch):
    """env 请求时读取（非 import 期绑定）：同一进程改 env 即改解析结果。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://a.example.com')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://a.example.com'}
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://b.example.com')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://b.example.com'}


# ------------------------------------------------------------- 档二 sidecar

def test_frozen_exe_sidecar_multiline(no_origins, tmp_path, monkeypatch):
    """frozen exe 旁 sidecar 多行列表：空行剔除 + 行内 strip + 去重。"""
    exe = tmp_path / 'app.exe'
    exe.write_bytes(b'MZ')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(exe))
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://exe.example.com\n'
        '\n'
        '  https://exe2.example.com  \n'
        'https://exe.example.com\n'
        '\n', encoding='utf-8')
    assert machine_cors.resolve_machine_allowed_origins() == {
        'https://exe.example.com', 'https://exe2.example.com'}


def test_frozen_sidecar_blank_file_falls_back_to_license(no_origins, tmp_path,
                                                         monkeypatch):
    """exe 旁文件存在但全空行 = 该位未配置 → 继续 license/ 回落查找。"""
    lic = tmp_path / 'license'
    lic.mkdir(parents=True)
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(lic))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        '  \n \n', encoding='utf-8')
    assert machine_cors.resolve_machine_allowed_origins() is None
    (lic / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://lic.example.com\n', encoding='utf-8')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://lic.example.com'}


def test_frozen_dual_position_exe_wins(no_origins, tmp_path, monkeypatch):
    """frozen 双位置并存：exe 旁优先（交付契约），license/ 仅回落。"""
    lic = tmp_path / 'license'
    lic.mkdir(parents=True)
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(lic))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://exe.example.com', encoding='utf-8')
    (lic / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://lic.example.com', encoding='utf-8')
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://exe.example.com'}


def test_frozen_missing_everywhere_none(no_origins, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    assert machine_cors.resolve_machine_allowed_origins() is None


def test_dev_sidecar_license_dir(no_origins, license_dir):
    """dev（未冻结）读 LICENSE_DIR 下 sidecar（out/license/）。"""
    license_dir.mkdir(parents=True, exist_ok=True)
    (license_dir / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://dev.example.com\nhttps://dev2.example.com\n',
        encoding='utf-8')
    assert machine_cors.resolve_machine_allowed_origins() == {
        'https://dev.example.com', 'https://dev2.example.com'}


def test_dev_ignores_exe_side(no_origins, tmp_path, monkeypatch):
    """dev 态不读 exe 旁 sidecar（exe 旁 = frozen 专属交付契约）。"""
    assert not hasattr(sys, 'frozen') or not sys.frozen
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://exe.example.com', encoding='utf-8')
    monkeypatch.setattr(sys, 'executable', 'C:/nowhere/python.exe')
    assert machine_cors.resolve_machine_allowed_origins() is None


def test_license_dir_read_at_call_time(no_origins, tmp_path, monkeypatch):
    """``paths.LICENSE_DIR`` 调用时取模块属性（monkeypatch 直接生效，
    keygate ``_reload_pieces_state`` 缺省参数坑的同款防御）。"""
    lic = tmp_path / 'lic2'
    lic.mkdir()
    (lic / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://x.example.com', encoding='utf-8')
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(lic))
    assert machine_cors.resolve_machine_allowed_origins() \
        == {'https://x.example.com'}


# ------------------------------------------------- describe（来源标注）

def test_describe_env_tier(no_origins, monkeypatch):
    """env 档描述：值 + 来源标注 + 条数。"""
    monkeypatch.setenv(machine_cors.MACHINE_ORIGINS_ENV,
                       'https://yl.example.com')
    text = machine_cors.describe_machine_allowed_origins()
    assert 'https://yl.example.com' in text
    assert f'{machine_cors.MACHINE_ORIGINS_ENV} env' in text
    assert '共 1 条' in text


def test_describe_sidecar_tiers(no_origins, tmp_path, monkeypatch):
    """sidecar 档来源标注跟随实际命中文件：exe 旁 / license/ 回落档 /
    dev out/license/ 三标签可区分（--check 售后定位）。"""
    # frozen exe 旁档
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://exe.example.com', encoding='utf-8')
    text = machine_cors.describe_machine_allowed_origins()
    assert 'https://exe.example.com' in text and 'exe 旁' in text
    # frozen license/ 回落档（exe 旁缺失）
    (tmp_path / machine_cors.MACHINE_ORIGINS_FILE_NAME).unlink()
    lic = tmp_path / 'license'
    lic.mkdir(parents=True)
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(lic))
    (lic / machine_cors.MACHINE_ORIGINS_FILE_NAME).write_text(
        'https://lic.example.com', encoding='utf-8')
    text = machine_cors.describe_machine_allowed_origins()
    assert 'https://lic.example.com' in text and '回落' in text
    # dev out/license/ 档
    monkeypatch.delattr(sys, 'frozen', raising=False)
    text = machine_cors.describe_machine_allowed_origins()
    assert 'https://lic.example.com' in text and 'out/license/' in text


def test_describe_unconfigured(no_origins):
    """皆无档描述：未配置 + 零回归语义 + 两条配置路径指引。"""
    text = machine_cors.describe_machine_allowed_origins()
    assert '未配置' in text
    assert machine_cors.MACHINE_ORIGINS_ENV in text
    assert machine_cors.MACHINE_ORIGINS_FILE_NAME in text
    assert '不发 CORS 头' in text


# ------------------------------------------------------------- 子进程冒烟

def test_module_smoke_subprocess():
    """AC：``python -m materialsorting.web.machine_cors`` 合成夹具冒烟 exit 0，
    输出含来源标注（env 档注入使「当前解析结果」行确定性）。"""
    env = {**os.environ, 'PYTHONPATH': str(_SRC)}
    env['PYTHONIOENCODING'] = 'utf-8'   # 子进程管道输出恒 UTF-8（Windows 管道缺省 locale/GBK）
    env[machine_cors.MACHINE_ORIGINS_ENV] = 'https://yl-smoke.example.com'
    result = subprocess.run(
        [sys.executable, '-m', 'materialsorting.web.machine_cors'],
        capture_output=True, env=env, timeout=120,
        cwd=str(_SRC.parent))
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout.decode('utf-8', 'replace')
    assert 'FAIL' not in out
    assert 'PASS' in out and '冒烟' in out
    assert 'https://yl-smoke.example.com' in out
    assert f'{machine_cors.MACHINE_ORIGINS_ENV} env' in out, '输出须含来源标注'
