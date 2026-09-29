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
        bf.SERVER_DIR / 'src' / 'materialsorting' / 'resources', bf.DIST_DIR,
        bf.DATA_DIR)


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
    """前端 static / 字体资源 / 样例母版三类数据捆绑齐备（.libs DLL 走依赖
    扫描，见 nuitka_command docstring）。"""
    cmd = _cmd(bf)
    assert any(c.endswith('=static') and 'materialSorting-web' in c for c in cmd)
    assert any(c.endswith('=materialsorting/resources') for c in cmd)
    assert not any('.libs=' in c for c in cmd)
    # 样例母版逐文件捆绑（2026-09-29 无样例 bug 修复）：repo data/ 顶层每个
    # .dxf 恰一条 --include-data-file=<abs>=data/<name>；.plt 与 configs/ 子
    # 目录不进客户包。
    samples = bf.sample_dxf_files(bf.DATA_DIR)
    assert samples, 'repo data/ 应有 git 追踪的样例 .dxf'
    expected = {f'--include-data-file={p}=data/{p.name}' for p in samples}
    assert {c for c in cmd if c.startswith('--include-data-file=')} == expected
    assert not any(c.endswith('.plt') for c in cmd)
    assert not any('configs' in c for c in cmd)


def test_nuitka_cmd_data_dir_none_legacy(bf):
    """data_dir=None 兼容旧调用形：不产 --include-data-file（迁移期参数可选）。"""
    cmd = bf.nuitka_command(
        7, '0.1.0.317', '0.1.0 g0f7a624 dirty', bf.ENTRY_FILE, bf.STATIC_DIR,
        bf.SERVER_DIR / 'src' / 'materialsorting' / 'resources', bf.DIST_DIR)
    assert not any(c.startswith('--include-data-file=') for c in cmd)


def test_sample_dxf_files(bf, tmp_path):
    """样例列举口径与 web/routes_views._sample_dxf_names 对齐：仅顶层 .dxf
    （大写 .DXF 也收）、.plt/子目录/非 dxf 不收、缺目录空列表；文件名含 =
    fail-fast（Nuitka --include-data-file 以 = 分隔，错位 = 静默打错文件）。"""
    (tmp_path / 'a.dxf').write_bytes(b'a')
    (tmp_path / 'B.DXF').write_bytes(b'b')            # 大写后缀也收（lower 判定）
    (tmp_path / 'note.txt').write_text('x')
    (tmp_path / 'ref.plt').write_text('x')            # plt 不收
    sub = tmp_path / 'configs'                        # 子目录不收（非递归）
    sub.mkdir()
    (sub / 'inner.dxf').write_bytes(b'i')
    files = bf.sample_dxf_files(tmp_path)
    assert [p.name for p in files] == ['B.DXF', 'a.dxf']   # sorted 朴素序
    assert bf.sample_dxf_files(tmp_path / 'no_such_dir') == []
    (tmp_path / 'x=y.dxf').write_bytes(b'x')
    with pytest.raises(SystemExit):
        bf.sample_dxf_files(tmp_path)


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


# ---------------------------------------------------------------- 安装包（US-005）

def _iss_text(bf) -> str:
    return bf.ISS_FILE.read_text(encoding='utf-8-sig')


def test_iss_isl_assets_vendored(bf):
    """安装包双资产随仓在场：iss 脚本 + 简体中文语言包（官方发行版不含中文，
    vendor 进仓 = 构建可复现免二次下载）。"""
    assert bf.ISS_FILE.is_file()
    assert bf.ISL_FILE.is_file()
    assert '简体中文' in bf.ISL_FILE.read_text(encoding='utf-8')
    assert '创建桌面快捷方式' in bf.ISL_FILE.read_text(encoding='utf-8')


def test_iss_per_user_no_uac(bf):
    """per-user 免 UAC（PRD 定案③）：lowest + {localappdata}\Programs 安装目录。"""
    text = _iss_text(bf)
    assert 'PrivilegesRequired=lowest' in text
    assert r'DefaultDirName={localappdata}\Programs\{#MyAppName}' in text


def test_iss_version_defines_and_fallback(bf):
    """版本 /D 注入三 define（AC1）+ iss 侧 #ifndef 缺省占位（手工裸编译不炸）。"""
    text = _iss_text(bf)
    for tok in ('#ifndef MyAppVersion',
                '#define MyAppVersion "0.0.0-dev"',
                '#ifndef MyAppVersionNumber',
                '#define MyAppVersionNumber "0.0.0.0"',
                '#ifndef MyAppVersionFS',
                '#define MyAppVersionFS "0.0.0-dev"',
                'AppVersion={#MyAppVersion}',
                'VersionInfoVersion={#MyAppVersionNumber}',
                'OutputBaseFilename=MaterialSorting-Setup-{#MyAppVersionFS}'):
        assert tok in text, tok


def test_iss_chinese_wizard_and_desktop_task(bf):
    """中文向导（单一语言不弹选择）+ 桌面图标任务默认勾选（cm: 取自中文包）。"""
    text = _iss_text(bf)
    assert 'ShowLanguageDialog=no' in text
    assert 'MessagesFile: "ChineseSimplified.isl"' in text
    assert 'Name: "desktopicon"' in text
    assert '{cm:CreateDesktopIcon}' in text
    assert 'unchecked' not in text.split('[Tasks]')[1].split('[')[0]


def test_iss_uninstall_preserves_user_data(bf):
    """卸载保留用户数据（AC1）：无任何 [UninstallDelete] 破坏性条目 —— Inno
    缺省只删 [Files] 装入的文件，%LOCALAPPDATA%\\MaterialSorting 天然幸存；
    Uninstallable 显式 yes（缺省同值，AC 口径明示）。注释行不计（只看指令）。"""
    text = _iss_text(bf)
    directives = '\n'.join(ln for ln in text.splitlines()
                           if not ln.lstrip().startswith(';'))
    assert 'Uninstallable=yes' in directives
    assert '[UninstallDelete]' not in directives
    assert '用户数据' in text    # iss 内注释留档：卸载不触碰 LOCALAPPDATA 数据


def test_iss_running_process_detection(bf):
    """运行中检测（AC1「或等价」）：app 无命名互斥体 → [Code] tasklist 查镜像
    名；安装（InitializeSetup + PrepareToInstall 兜底）与卸载（InitializeUninstall）
    双向。"""
    text = _iss_text(bf)
    assert 'function IsAppRunning(): Boolean;' in text
    assert 'InitializeSetup' in text and 'PrepareToInstall' in text
    assert 'InitializeUninstall' in text
    assert 'tasklist /FI "IMAGENAME eq {#MyAppExeName}"' in text
    # 静默安装/卸载（/VERYSILENT）无界面接「重试/取消」→ 直接中止而非挂死
    # （2026-09-27 实测：RETRYCANCEL 弹窗在无头场景永远等不到点击）
    assert 'WizardSilent()' in text and 'UninstallSilent()' in text


def test_iss_files_pack_dist_tree(bf):
    """[Files] 打包冻结 onedir 整树（dist/MaterialSorting.dist/* → {app}）。"""
    assert r'Source: "..\..\dist\MaterialSorting.dist\*"' in _iss_text(bf)


# ---------------------------------------------------------------- 安装包纯函数

def test_fs_version(bf):
    """display → 文件名安全串：空白折叠 '-'（setup.exe / zip 命名单一真相源）。"""
    assert bf.fs_version('0.1.0 g0f7a624 dirty') == '0.1.0-g0f7a624-dirty'
    assert bf.fs_version('0.1.0') == '0.1.0'
    assert bf.fs_version('  0.2.0  beta ') == '0.2.0-beta'


def test_find_iscc_path_hit(bf, monkeypatch):
    monkeypatch.setattr('shutil.which', lambda n: r'C:\x\ISCC.exe')
    assert str(bf.find_iscc()) == r'C:\x\ISCC.exe'


def test_find_iscc_localappdata_fallback(bf, tmp_path, monkeypatch):
    """PATH 缺席 → %LOCALAPPDATA%\Programs\Inno Setup 6（winget --scope user 落点）。"""
    monkeypatch.setattr('shutil.which', lambda n: None)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    iscc = tmp_path / 'Programs' / 'Inno Setup 6' / 'ISCC.exe'
    iscc.parent.mkdir(parents=True)
    iscc.write_bytes(b'x')
    assert bf.find_iscc() == iscc


def test_find_iscc_absent(bf, tmp_path, monkeypatch):
    monkeypatch.setattr('shutil.which', lambda n: None)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))   # 空目录
    monkeypatch.setattr(bf, 'ISCC_FALLBACK_PATHS', (str(tmp_path / 'none.exe'),))
    assert bf.find_iscc() is None


def test_iscc_command(bf, tmp_path):
    """三 define 同源注入（AC1）：display / 数字四段 / 文件名安全串。"""
    cmd = bf.iscc_command(Path(r'C:\x\ISCC.exe'), '0.1.0 g0f7a624 dirty',
                          '0.1.0.317', tmp_path / 'a.iss')
    assert cmd[0] == r'C:\x\ISCC.exe'
    assert '/DMyAppVersion=0.1.0 g0f7a624 dirty' in cmd
    assert '/DMyAppVersionNumber=0.1.0.317' in cmd
    assert '/DMyAppVersionFS=0.1.0-g0f7a624-dirty' in cmd
    assert cmd[-1].endswith('a.iss')


def test_sign_command_env_absent(bf, tmp_path):
    """钩子门禁（AC2）：MS_SIGNING_PFX/MS_SIGNING_TS 缺任一 → None 不签名。"""
    assert bf.sign_command(tmp_path / 's.exe', {}) is None
    assert bf.sign_command(tmp_path / 's.exe', {'MS_SIGNING_PFX': 'c.pfx'}) is None
    assert bf.sign_command(tmp_path / 's.exe', {'MS_SIGNING_TS': 'http://ts'}) is None


def test_sign_command_env_present(bf, tmp_path, monkeypatch):
    monkeypatch.setattr('shutil.which',
                        lambda n: r'C:\sdk\signtool.exe')
    cmd = bf.sign_command(tmp_path / 's.exe', {
        'MS_SIGNING_PFX': 'c.pfx', 'MS_SIGNING_TS': 'http://ts',
        'MS_SIGNING_PWD': 'pw'})
    assert cmd[0] == r'C:\sdk\signtool.exe'
    assert cmd[1] == 'sign'
    for tok in ('/fd', 'SHA256', '/tr', 'http://ts', '/td', '/f', 'c.pfx',
                '/p', 'pw'):
        assert tok in cmd
    assert cmd[-1] == str(tmp_path / 's.exe')


def test_sign_command_tool_missing_fails(bf, tmp_path, monkeypatch):
    """配了签名 env 但 signtool 缺 → SystemExit（不该静默出未签名包）。"""
    monkeypatch.setattr('shutil.which', lambda n: None)
    with pytest.raises(SystemExit):
        bf.sign_command(tmp_path / 's.exe', {'MS_SIGNING_PFX': 'c.pfx',
                                             'MS_SIGNING_TS': 'http://ts'})


def test_make_portable_zip(bf, tmp_path):
    """绿色 zip（AC4）：单一顶层 MaterialSorting/（.dist 后缀不进包名）+ 一行
    启动说明 txt。"""
    import zipfile
    dist = tmp_path / 'MaterialSorting.dist'
    (dist / 'static').mkdir(parents=True)
    (dist / 'MaterialSorting.exe').write_bytes(b'MZ')
    (dist / 'static' / 'index.html').write_text('<html>')
    zf = tmp_path / 'p.zip'
    n = bf.make_portable_zip(dist, zf)
    assert n == 2
    with zipfile.ZipFile(zf) as z:
        names = z.namelist()
        readme = z.read(f'MaterialSorting/{bf.PORTABLE_README_NAME}').decode('utf-8')
    assert 'MaterialSorting/MaterialSorting.exe' in names
    assert 'MaterialSorting/static/index.html' in names
    assert f'MaterialSorting/{bf.PORTABLE_README_NAME}' in names
    assert not any('.dist' in nm for nm in names)
    assert 'MaterialSorting.exe' in readme and 'LOCALAPPDATA' in readme
    assert readme.count('\n') == 1      # 一行启动说明


# ---------------------------------------------------------------- 第 7 步行为

def _fake_dist(bf, tmp_path, monkeypatch):
    dist_app = tmp_path / 'MaterialSorting.dist'
    dist_app.mkdir()
    (dist_app / 'MaterialSorting.exe').write_bytes(b'MZ')
    monkeypatch.setattr(bf, 'DIST_APP_DIR', dist_app)
    monkeypatch.setattr(bf, 'EXE_PATH', dist_app / 'MaterialSorting.exe')
    monkeypatch.setattr(bf, 'DIST_DIR', tmp_path)
    return dist_app


def test_step_installer_iscc_missing_skips_not_fails(bf, tmp_path, monkeypatch,
                                                    capsys):
    """ISCC 缺席 = 打印安装指引并跳过不失败（AC2 exit 0 语义），绿色 zip 恒产。"""
    _fake_dist(bf, tmp_path, monkeypatch)
    monkeypatch.setattr(bf, 'find_iscc', lambda: None)
    bf.step_installer('0.1.0 g0f7a624 dirty', '0.1.0.317')
    out = capsys.readouterr().out
    assert '跳过安装包编译' in out and 'jrsoftware.org' in out
    assert (tmp_path / 'MaterialSorting-portable-0.1.0-g0f7a624-dirty.zip'
            ).is_file()


def test_step_installer_compiles_then_signs_skip(bf, tmp_path, monkeypatch,
                                                 capsys):
    """ISCC 在场：编译 → 校验产物落位 → 签名 env 缺席打印跳过 → zip 恒产。"""
    import subprocess as sp
    _fake_dist(bf, tmp_path, monkeypatch)
    fake_iscc = tmp_path / 'ISCC.exe'
    fake_iscc.write_bytes(b'x')
    monkeypatch.setattr(bf, 'find_iscc', lambda: fake_iscc)

    def fake_run(cmd, timeout=None):
        (tmp_path / 'MaterialSorting-Setup-0.1.0-g0f7a624-dirty.exe'
         ).write_bytes(b'MZ')          # 模拟 ISCC 落产物
        return sp.CompletedProcess(cmd, 0)

    monkeypatch.setattr(bf, '_run', fake_run)
    monkeypatch.delenv('MS_SIGNING_PFX', raising=False)
    monkeypatch.delenv('MS_SIGNING_TS', raising=False)
    bf.step_installer('0.1.0 g0f7a624 dirty', '0.1.0.317')
    out = capsys.readouterr().out
    assert str(fake_iscc) in out and '/DMyAppVersionFS=0.1.0-g0f7a624-dirty' in out
    assert '签名：跳过' in out
    assert (tmp_path / 'MaterialSorting-Setup-0.1.0-g0f7a624-dirty.exe').is_file()
    assert (tmp_path / 'MaterialSorting-portable-0.1.0-g0f7a624-dirty.zip').is_file()


def test_step_installer_iscc_failure_fails(bf, tmp_path, monkeypatch):
    """ISCC 编译失败（非 0 退出/产物未出现）→ exit 1（步骤名打印）。"""
    import subprocess as sp
    _fake_dist(bf, tmp_path, monkeypatch)
    fake_iscc = tmp_path / 'ISCC.exe'
    fake_iscc.write_bytes(b'x')
    monkeypatch.setattr(bf, 'find_iscc', lambda: fake_iscc)
    monkeypatch.setattr(bf, '_run',
                        lambda cmd, timeout=None: sp.CompletedProcess(cmd, 1))
    with pytest.raises(SystemExit):
        bf.step_installer('0.1.0', '0.1.0.0')


def test_parser_installer_flags(bf):
    """--installer / --installer-only 参数面（纯 argparse，不起子进程）。"""
    args = bf.build_parser().parse_args(['--installer'])
    assert args.installer and not args.installer_only
    args = bf.build_parser().parse_args(['--installer-only'])
    assert args.installer_only and not args.installer
