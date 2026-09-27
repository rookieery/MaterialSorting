"""scripts/build_freeze.py 护栏测试（US-003，prd-local-deploy-freeze）。

纯函数级（不真跑 Nuitka / 不起子进程）：jobs 推导矩阵（资源红线③①）、版本
资源双串推导、dist 源码泄漏扫描（红线②）、``--check`` 输出解析、Nuitka 命令
常量段红线旗标（元数据红线①）。导入方式对齐 tests/test_spyrrow_wheel.py
（importlib 按路径加载 scripts/ 下脚本，scripts 非包）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / 'scripts' / 'build_freeze.py'
_GIB = 1024 ** 3


def _load_script():
    spec = importlib.util.spec_from_file_location('ms_build_freeze_script',
                                                  _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def bf():
    return _load_script()


# ---------------------------------------------------------------- jobs 推导（红线③①）

def test_derive_jobs_32core_memory_clamp(bf):
    """本机画像（32 核 / ~23.6GiB 可用）：基线 8 → 内存钳制 7。"""
    jobs, lines = bf.derive_jobs(32, int(23.6 * _GIB))
    assert jobs == 7
    assert any('内存钳制' in ln for ln in lines)


def test_derive_jobs_memory_floor(bf):
    """可用内存不足（<3GiB/job）：降到下限 2 而非 1/0。"""
    jobs, _ = bf.derive_jobs(32, int(4.1 * _GIB))
    assert jobs == 2


def test_derive_jobs_small_cpu(bf):
    """4 核：基线 max(2, 4//4)=2，内存充裕不抬升。"""
    jobs, _ = bf.derive_jobs(4, 32 * _GIB)
    assert jobs == 2


def test_derive_jobs_hard_cap(bf):
    """核数再多也 ≤ 红线锚 8（64 核 / 内存探测失败 → 纯基线 8）。"""
    jobs, lines = bf.derive_jobs(64, None)
    assert jobs == 8
    assert any('跳过' in ln for ln in lines)


@pytest.mark.parametrize('cpu', [8, 16, 32, 64, 128])
def test_derive_jobs_never_full_cores(bf, cpu):
    """防回归：jobs 永不等于全核（2026-09-27 事故形态）。"""
    jobs, _ = bf.derive_jobs(cpu, None)
    assert jobs <= bf.JOBS_HARD_CAP == 8
    assert jobs != cpu


def test_derive_jobs_override_wins_with_warning(bf):
    jobs, lines = bf.derive_jobs(32, int(23.6 * _GIB), override=16)
    assert jobs == 16
    assert any('警告' in ln for ln in lines)


def test_derive_jobs_override_invalid(bf):
    with pytest.raises(SystemExit):
        bf.derive_jobs(32, None, override=0)


# ---------------------------------------------------------------- 版本串推导

def test_compute_versions_tagged_describe(bf):
    fv, disp = bf.compute_versions('0.1.0', 'v0.1.0-3-g0f7a624', 317)
    assert fv == '0.1.0.317'
    assert disp == '0.1.0 g0f7a624'


def test_compute_versions_dirty_suffix(bf):
    _, disp = bf.compute_versions('0.1.0', '0f7a624-dirty', 317)
    assert disp.endswith('g0f7a624 dirty')


def test_compute_versions_no_git(bf):
    fv, disp = bf.compute_versions('0.1.0', None, None)
    assert fv == '0.1.0.0'
    assert disp == '0.1.0'


def test_compute_versions_bare_hash(bf):
    _, disp = bf.compute_versions('0.1.0', '0f7a624abcdef1234', None)
    assert disp == '0.1.0 g0f7a624'


def test_compute_versions_junk_describe_ignored(bf):
    _, disp = bf.compute_versions('0.1.0', 'not-a-hex-token', 5)
    assert disp == '0.1.0'


def test_compute_versions_short_version_padded(bf):
    fv, _ = bf.compute_versions('1.0', 'v1.0-1-gdeadbee', 9)
    assert fv == '1.0.0.9'


# ---------------------------------------------------------------- dist 泄漏扫描（红线②）

def _mk(root: Path, rel: str, is_dir: bool = False) -> Path:
    p = root / rel
    if is_dir:
        p.mkdir(parents=True, exist_ok=True)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'x')
    return p


def test_scan_dist_leaks_clean(bf, tmp_path):
    _mk(tmp_path, 'MaterialSorting.exe')
    _mk(tmp_path, 'static/index.html')
    _mk(tmp_path, 'static/assets/app.js')
    _mk(tmp_path, 'materialsorting/launcher.cp311-win_amd64.pyd')
    _mk(tmp_path, 'testtools/x.bin')            # 相似名不算
    assert bf.scan_dist_leaks(tmp_path) == []


@pytest.mark.parametrize('rel,is_dir', [
    ('materialsorting/leak.py', False),
    ('materialsorting/leak.pyc', False),
    ('.docs/x.json', False),
    ('tests/test_x.py', False),
    ('shapely/tests/y.bin', False),
    ('scripts/tool.exe', False),
])
def test_scan_dist_leaks_hits(bf, tmp_path, rel, is_dir):
    _mk(tmp_path, rel, is_dir)
    hits = bf.scan_dist_leaks(tmp_path)
    assert len(hits) == 1
    leaked = Path(hits[0].split('：', 1)[1]).as_posix()
    # 目录名命中 → 报顶层泄漏目录（rel 位于其下）；后缀命中 → 报文件本体。
    assert rel == leaked or rel.startswith(leaked + '/')


def test_scan_dist_leaks_dir_named_tests(bf, tmp_path):
    _mk(tmp_path, 'pkg/tests', is_dir=True)
    assert len(bf.scan_dist_leaks(tmp_path)) == 1


# ---------------------------------------------------------------- --check 输出解析

def test_parse_check_output(bf):
    text = ('frozen: True\n'
            'version: 0.1.0\n'
            'paths.STATIC_DIR: D:/x/static\n'
            'paths.FONT_DIR: D:/x/resources/fonts\n'
            'warm_start_supported: True\n'
            '无冒号行应被忽略\n')
    info = bf.parse_check_output(text)
    assert info['frozen'] == 'True'
    assert info['version'] == '0.1.0'
    assert info['paths.STATIC_DIR'].endswith('static')
    assert info['warm_start_supported'] == 'True'
    assert '无冒号行应被忽略' not in info


# ---------------------------------------------------------------- Nuitka 命令红线旗标

def _cmd(bf, jobs=7):
    return bf.nuitka_command(
        jobs, '0.1.0.317', '0.1.0 g0f7a624 dirty', bf.ENTRY_FILE, bf.STATIC_DIR,
        bf.SERVER_DIR / 'src' / 'materialsorting' / 'resources', bf.DIST_DIR)


def test_nuitka_cmd_redline_metadata(bf):
    """红线①：spyrrow + materialsorting 元数据旗标必须在。"""
    cmd = _cmd(bf)
    assert '--include-distribution-metadata=spyrrow' in cmd
    assert '--include-distribution-metadata=materialsorting' in cmd


def test_nuitka_cmd_jobs_and_mode(bf):
    """红线③①：--jobs 显式在命令行；standalone（=onedir）+ 控制台保留。"""
    cmd = _cmd(bf)
    assert '--jobs=7' in cmd
    assert '--standalone' in cmd and '--onefile' not in cmd
    assert '--windows-console-mode=force' in cmd


def test_nuitka_cmd_mingw64(bf):
    """编译器强制 MinGW64：MSVC cl 14.3 编巨型 TU 两轮不同模块本体崩溃
    （2026-09-27 实测 C1001 / 0xC0000005），弃 MSVC 定案。"""
    cmd = _cmd(bf)
    assert '--mingw64' in cmd


def test_nuitka_cmd_data_dirs(bf):
    """前端 static / 字体资源两类数据捆绑齐备（.libs DLL 走依赖扫描，见
    nuitka_command docstring）。"""
    cmd = _cmd(bf)
    assert any(c.endswith('=static') and 'materialSorting-web' in c for c in cmd)
    assert any(c.endswith('=materialsorting/resources') for c in cmd)
    assert not any('.libs=' in c for c in cmd)


def test_nuitka_cmd_version_resources(bf):
    cmd = _cmd(bf)
    assert '--file-version=0.1.0.317' in cmd
    assert any(c.startswith('--file-description=') and 'g0f7a624' in c
               for c in cmd)
    assert any(c.startswith('--company-name=') for c in cmd)
    assert any(c.startswith('--product-name=') for c in cmd)


def test_nuitka_cmd_tests_excluded_and_entry(bf):
    cmd = _cmd(bf)
    assert '--nofollow-import-to=*.tests' in cmd
    assert '--include-package=materialsorting' in cmd
    assert str(bf.ENTRY_FILE) in cmd          # 入口适配层


def test_nuitka_cmd_jobs_reflects_argument(bf):
    cmd = _cmd(bf, jobs=2)
    assert '--jobs=2' in cmd and '--jobs=7' not in cmd


def test_entry_adapter_exists(bf):
    """入口适配层与前端 static 真实在场（dev 仓库布局断言）。"""
    assert bf.ENTRY_FILE.is_file()
    assert (bf.STATIC_DIR / 'index.html').is_file()


def test_entry_bridges_sys_frozen_before_launcher_import(bf):
    """frozen 判据桥接：Nuitka 不设 sys.frozen（官方口径 __compiled__），
    launcher/_frozen_spawn 的 getattr(sys,'frozen') 判据靠入口适配层补 ——
    ①仅真编译态设（`'__compiled__' in globals()` 守卫，dev 直跑零变化）；
    ②必须先于 launcher import（晚设 = import 期读取方看不到）。AST 只看真代
    码节点（docstring 里的同名短语不参与断言）。"""
    import ast
    tree = ast.parse(bf.ENTRY_FILE.read_text(encoding='utf-8'))
    guard_idx = import_idx = None
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.If) and any(
                isinstance(sub, ast.Assign)
                and isinstance(sub.targets[0], ast.Attribute)
                and isinstance(sub.targets[0].value, ast.Name)
                and sub.targets[0].value.id == 'sys'
                and sub.targets[0].attr == 'frozen'
                for sub in ast.walk(node)):
            guard_idx = i
        if (isinstance(node, ast.ImportFrom)
                and node.module == 'materialsorting.launcher'):
            import_idx = i
    assert guard_idx is not None, '缺 sys.frozen 桥接（守卫式赋值）'
    assert import_idx is not None, '缺 launcher import'
    assert guard_idx < import_idx, '桥接必须先于 launcher import'
