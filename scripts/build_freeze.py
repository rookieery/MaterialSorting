"""Nuitka 冻结构建脚本（US-003，权威 PRD：tasks/prd-local-deploy-freeze.md）。

一条命令从源码产出可分发 onedir::

    .venv/Scripts/python.exe scripts/build_freeze.py            # 全量构建 + dist 自检
    .venv/Scripts/python.exe scripts/build_freeze.py --dry-run  # 打印命令行/自检/jobs 推导，不编译
    .venv/Scripts/python.exe scripts/build_freeze.py --launch   # 直接拉起 dist 冒烟实例（Ctrl-C 退出）

必须用仓库 venv 的 Python 直跑（nuitka / spyrrow / materialsorting 均装在
venv）。产物 = ``dist/MaterialSorting.dist/MaterialSorting.exe``（standalone
onedir，后端源码真编译为机器码；坚决不用 onefile —— 解压慢 / 杀软误报率高 /
多进程敏感，PRD 定案①）。入口 = scripts/freeze_entry.py 适配层（launcher.py
是相对 import 的包模块，不能直接当脚本编译，见其 docstring），行为 = ms-desktop。

构建机一次性准备（只做一次）：
  - C 编译器：**无需预装** —— 本脚本 ``--mingw64`` 强制走 Nuitka 专配 MinGW64
    （``--assume-yes-for-downloads`` 已开，首次构建自动下载到
    ``%LOCALAPPDATA%/Nuitka`` 缓存）。本机虽装有 MSVC Build Tools，但 cl 14.3
    编 Nuitka 巨型 TU 偶发编译器本体崩溃（2026-09-27 两轮不同模块实测 C1001 /
    0xC0000005，详见 nuitka_command 常量段注释），故弃用。
  - node：前端 ``npm run build`` 产 ``materialSorting-web/static/`` 用（本机已有）。
  - Inno Setup：可选，US-005 安装包线，不在本脚本范围。

运维注记（资源红线③，2026-09-27 整机假死事故复盘）：
  - **Nuitka 版本**：验证基线 4.3rc3（4.2.2 优化器对闭包内 try/except 大模块
    偶发 ``mergeBranches`` 内部 TypeError，同 seed 不同轮不同模块崩 —— 4.3rc3
    实测过；``--version`` 自检行可见实际版本）；
  - 构建前**停 ms-web / 长跑 solver 等常驻 CPU 负载**（叠加 = 双倍风暴）；
  - 全量构建预算 30~90min、先清后建无增量；``%LOCALAPPDATA%/Nuitka`` 的
    clcache 跨重试生效（重试不必从零编）；
  - **硬重启后遗症**：构建中强制断电/重启会留下零填充的 clcache 缓存对象
    （NTFS 已分配未刷盘），下轮 cache「命中」把它还原进 build 目录，链接期
    报 ``CVTRES fatal error CVT1107: xx.obj 已损坏``（2026-09-27 实测）——
    处置 = 删 ``%LOCALAPPDATA%/Nuitka/Nuitka/Cache/clcache`` 全量重编；
  - 本脚本自带三重防护（PRD AC8）：①``--jobs=N`` 显式上限（默认
    ``min(8, max(2, 核数//4))``，再按可用物理内存每 job 预留 ≥3GB 钳制、下限
    2；``--jobs`` 参数 / ``MS_FREEZE_JOBS`` env 可覆盖）；②Nuitka 子进程
    BELOW_NORMAL_PRIORITY_CLASS 低优先级（满载时 UI 仍可响应、保留抢回控制权
    能力）；③孤儿编译进程 fail-fast（硬重启残留叠加 = 双倍风暴，``--force``
    才放行）。

红线速查（构建尾部自检逐条核对）：
  ① ``--include-distribution-metadata=spyrrow`` 必须在 —— 漏 = SE warm 运行期
    静默降级 unsupported；``=materialsorting`` = ``--check`` 版本串（售后识别）。
  ② dist 源码泄漏 grep 零命中（.py/.pyc/.docs/tests/scripts）。
  ③ 资源安全三重防护（见上）。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------- 路径常量
# 脚本位于 <repo>/scripts/ → parents[1] = repo 根（不硬编码 .. 上溯之外的绝对路径）。
ROOT = Path(__file__).resolve().parents[1]
ENTRY_FILE = ROOT / 'scripts' / 'freeze_entry.py'          # Nuitka 入口适配层
STATIC_DIR = ROOT / 'materialSorting-web' / 'static'       # 前端 React 构建产物
SERVER_DIR = ROOT / 'materialSorting-server'
PYPROJECT = SERVER_DIR / 'pyproject.toml'
SPYRROW_PIN_FILE = SERVER_DIR / 'spyrrow_build.json'       # 私有 wheel 钉板（四字段）
DIST_DIR = ROOT / 'dist'
APP_BASENAME = 'MaterialSorting'
DIST_APP_DIR = DIST_DIR / f'{APP_BASENAME}.dist'
EXE_PATH = DIST_APP_DIR / f'{APP_BASENAME}.exe'

# ---------------------------------------------------------------- 版本资源
# 资源串一律 ASCII：中文进 build_definitions.h 后被 cl.exe 按系统代码页(936)
# 误读，UTF-8 多字节错位产生「常量中有换行符 C2001」编译失败（2026-09-27 实
# 测）；中文产品名走 US-005 Inno 安装包/快捷方式，exe 资源页保 ASCII。
COMPANY_NAME = 'MaterialSorting'
PRODUCT_NAME = 'MaterialSorting Workbench'
FILE_DESCRIPTION = 'Jeans marker making workbench'

# ---------------------------------------------------------------- 资源红线③常量
JOBS_HARD_CAP = 8            # PRD AC8：--jobs 显式上限锚（本机 32 核上 ≠ 32）
JOBS_FLOOR = 2               # 钳制下限（再低构建时长不可接受）
BYTES_PER_JOB = 3 * 1024 ** 3  # 每 job 预留 ≥3GB 可用物理内存（事故复盘点测）
BUILD_TIME_HINT = '30~90 分钟'

# 孤儿编译进程画像（tasklist image 名，小写匹配）。python -m nuitka 残留在
# tasklist 里显示为 python.exe，另走命令行扫描（wmic，缺则 powershell 兜底）。
ORPHAN_IMAGE_NAMES = frozenset(
    ('cl.exe', 'ccache.exe', 'clcache.exe', 'scons.exe', 'gcc.exe', 'cc1.exe',
     'nuitka.exe'))

# dist 源码泄漏红线②（AC4）：后缀 + 目录名双口径。
LEAK_SUFFIXES = ('.py', '.pyc')
LEAK_COMPONENT_NAMES = frozenset(('.docs', 'tests', 'scripts'))


def _fail(step: str, msg: str) -> None:
    """失败出口：打印失败步骤名 + 原因，退出 1（PRD AC3）。"""
    print(f'\n[FAIL] 步骤「{step}」：{msg}', file=sys.stderr)
    raise SystemExit(1)


def _run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout)


# ================================================================ 资源推导（纯函数）

def query_available_memory_bytes() -> int | None:
    """可用物理内存（ctypes ``GlobalMemoryStatusEx`` 仅标准库）。

    非 Windows / 结构体调用失败 → None（调用方跳过内存钳制，优雅降级）。
    """
    if sys.platform != 'win32' or not hasattr(ctypes, 'windll'):
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
            ('ullTotalPhys', ctypes.c_ulonglong),
            ('ullAvailPhys', ctypes.c_ulonglong),
            ('ullTotalPageFile', ctypes.c_ulonglong),
            ('ullAvailPageFile', ctypes.c_ulonglong),
            ('ullTotalVirtual', ctypes.c_ulonglong),
            ('ullAvailVirtual', ctypes.c_ulonglong),
            ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return None
    except OSError:
        return None
    return int(stat.ullAvailPhys)


def derive_jobs(cpu_count: int, avail_bytes: int | None,
                override: int | None = None) -> tuple[int, list[str]]:
    """``--jobs`` 推导（资源红线③①，纯函数便于单测矩阵覆盖）。

    基线 ``min(8, max(2, cpu//4))`` → 可用物理内存钳制（每 job ≥3GB，不足降
    jobs 下限 2）；``override``（--jobs 参数 / MS_FREEZE_JOBS env，参数优先）
    直用但仍打印警示。返回 ``(jobs, 推导过程行)``。
    """
    if override is not None:
        if override < 1:
            raise SystemExit('--jobs 须为正整数')
        lines = [f'jobs 推导：显式覆盖 --jobs={override}（跳过基线/内存钳制）']
        if override > JOBS_HARD_CAP:
            lines.append(
                f'  ⚠ 警告：override={override} 高于红线锚 {JOBS_HARD_CAP}'
                '（2026-09-27 事故：全核并发缺页风暴锁死整机，自担风险）')
        return override, lines

    base = min(JOBS_HARD_CAP, max(2, cpu_count // 4))
    lines = [f'jobs 推导：基线 min({JOBS_HARD_CAP}, max(2, {cpu_count}//4))'
             f' = {base}']
    jobs = base
    if avail_bytes is not None:
        mem_cap = int(avail_bytes // BYTES_PER_JOB)
        jobs = max(JOBS_FLOOR, min(base, mem_cap))
        lines.append(
            f'  内存钳制：可用 {avail_bytes / 1024 ** 3:.1f} GiB ÷ '
            f'{BYTES_PER_JOB // 1024 ** 3} GiB/job = {mem_cap} → '
            f'max({JOBS_FLOOR}, min({base}, {mem_cap})) = {jobs}')
    else:
        lines.append('  内存钳制：非 Windows/探测失败，跳过（仅基线）')
    return jobs, lines


# ================================================================ 版本串（纯函数）

def compute_versions(pyproject_version: str, git_describe: str | None,
                     commit_count: int | None) -> tuple[str, str]:
    """版本资源双串：``(file_version 数字四段, display 完整串)``。

    - ``file_version``：Nuitka ``--file-version`` 限 ≤4 段数字（0-65535）——
      pyproject 三段 + git 提交数当第 4 段（build number）；无 git 补 0。
    - ``display``：``pyproject + g<短哈希>[ dirty]``（git describe 短串），
      挂 ``--file-description`` —— exe 属性页可读完整版本（取不到 git 用
      纯版本号，PRD AC2）。
    """
    parts = [p for p in pyproject_version.strip().split('.') if p != '']
    nums: list[int] = []
    for p in parts[:3]:
        try:
            nums.append(min(65535, max(0, int(p))))
        except ValueError:
            nums = [0]
            break
    while len(nums) < 3:
        nums.append(0)
    count = commit_count if commit_count is not None else 0
    file_version = '.'.join(str(n) for n in nums + [min(65535, max(0, count))])

    display = pyproject_version.strip()
    if git_describe:
        m = re.search(r'-g([0-9a-f]{7,})', git_describe)
        short = m.group(1)[:7] if m else (
            git_describe[:7]
            if re.fullmatch(r'[0-9a-f]{7,40}(?:-dirty)?', git_describe) else '')
        if short:
            display = f'{display} g{short}'
            if git_describe.endswith('-dirty'):
                display += ' dirty'
    return file_version, display


def read_pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding='utf-8')
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return m.group(1) if m else '0.0.0'


def query_git() -> tuple[str | None, int | None]:
    """``(git describe 短串, 提交数)``；非 git 环境 → ``(None, None)``。"""
    describe = count = None
    try:
        r = _run(['git', 'describe', '--tags', '--always', '--long', '--dirty'],
                 timeout=15)
        if r.returncode == 0:
            describe = r.stdout.strip()
        r2 = _run(['git', 'rev-list', '--count', 'HEAD'], timeout=15)
        if r2.returncode == 0:
            count = int(r2.stdout.strip())
    except (OSError, ValueError):
        pass
    return describe, count


# ================================================================ Nuitka 命令（常量段）

def nuitka_command(jobs: int, file_version: str, version_display: str,
                   entry: Path, static_dir: Path, resources_dir: Path,
                   dist_dir: Path) -> list[str]:
    """Nuitka 命令行组装（PRD AC2 常量段，逐旗标注释）。

    注：delvewheel ``.libs`` DLL 目录（numpy.libs=OpenBLAS / shapely.libs=GEOS）
    不走 ``--include-data-dir`` —— Nuitka 对纯 DLL 目录报「No data files」，
    扩展模块的 DLL 依赖由其依赖扫描自动收（dist 自检 + 冒烟兜底验证）。
    """
    cmd: list[str] = [
        sys.executable, '-m', 'nuitka',
        # ---- 形态：standalone = onedir 目录形态（真编译机器码；onefile 单文件
        #      解压慢/杀软误报/多进程敏感，PRD 定案①坚决不用 —— Nuitka 4.x 无
        #      --onedir 旗标，standalone 本身即 onedir）
        '--standalone',
        str(entry),
        # ---- 依赖闭包显式声明（AC2「以实际调通为准」的实勘结论）
        '--include-package=materialsorting',   # 后端全包收编（src 零动态 import 实勘；launcher 函数内延迟 import 的 web/cli 子包全覆盖）
        '--nofollow-import-to=*.tests',        # 三方包 tests 子树不进闭包（泄漏红线② + 体积：matplotlib/shapely wheel 均带 tests）
        '--enable-plugin=matplotlib',          # mpl-data（字体/样式数据）+ freetype DLL 捆绑 —— PNG 导出（matplotlib 路径）依赖
        # ---- 元数据红线①（漏 = SE warm 运行期静默降级 unsupported）
        '--include-distribution-metadata=spyrrow',          # warm_start_supported() 读 '+ms<N>' 版本串
        '--include-distribution-metadata=materialsorting',  # launcher --check 版本串（售后识别用户版本）
        # ---- 数据文件
        f'--include-data-dir={static_dir}=static',  # 前端 React 构建产物 → exe 同级 static/（frozen MS_STATIC_DIR 缺省指向）
        f'--include-data-dir={resources_dir}=materialsorting/resources',  # PLT 矢量文字资源（NotoSansSC-Regular.otf 等，paths.FONT_DIR 包内缺省）
        # ---- 版本资源（杀软误报治理：完整 company/product/version 提高启发式信誉）
        f'--company-name={COMPANY_NAME}',
        f'--product-name={PRODUCT_NAME}',
        f'--file-version={file_version}',      # 数字四段（Nuitka 限制）：pyproject 三段 + git 提交数
        f'--file-description={FILE_DESCRIPTION} {version_display}',  # 完整版本串（含 git describe 短串）挂描述
        # ---- Windows 形态
        '--windows-console-mode=force',        # 保留控制台窗口（PRD 定案②：现场排障第一现场就是黑窗日志）
        # ---- 编译器强制 MinGW64（2026-09-27 定案）
        # MSVC cl 14.3 编 Nuitka 巨型 TU 偶发编译器本体崩溃，两轮不同模块实测：
        # ezdxf.render.mleader C1001 内部错误 / matplotlib.font_manager
        # 0xC0000005 访问违例 —— 不可复现不可规避，换 Nuitka 专配 winlibs
        # MinGW64（首次用 --assume-yes-for-downloads 自动下载，稳）。
        '--mingw64',
        # ---- 输出
        f'--output-dir={dist_dir}',            # 仓库根 dist/（构建尾部自检 MaterialSorting.dist/）
        '--output-folder-name=MaterialSorting',   # → dist/MaterialSorting.dist/
        '--output-filename=MaterialSorting.exe',  # → dist/MaterialSorting.dist/MaterialSorting.exe
        '--assume-yes-for-downloads',          # 依赖工具（MinGW 等）下载不交互挂起
        f'--report={dist_dir / "nuitka-report.xml"}',  # 依赖闭包/数据文件清单留档（构建诊断）
        # ---- 资源红线③①：显式并发上限，绝不落回 Nuitka 缺省（= 逻辑核数全核并发）
        f'--jobs={jobs}',
    ]
    return cmd


# ================================================================ dist 自检（纯函数）

def scan_dist_leaks(dist_app_dir: Path) -> list[str]:
    """源码泄漏扫描（红线②）：.py/.pyc 后缀 + .docs/tests/scripts 路径组件。

    命中泄漏目录名的子树整树只记一次（顶层命中目录），不逐文件重复计数。
    """
    violations: list[str] = []
    seen_leak_dirs: set[tuple[str, ...]] = set()
    for path in sorted(dist_app_dir.rglob('*')):
        rel = path.relative_to(dist_app_dir)
        offending_idx = next(
            (i for i, comp in enumerate(rel.parts)
             if comp.lower() in LEAK_COMPONENT_NAMES), None)
        if offending_idx is not None:
            top = rel.parts[:offending_idx + 1]
            if top not in seen_leak_dirs:
                seen_leak_dirs.add(top)
                violations.append('泄漏目录：' + str(Path(*top)))
            continue
        if path.suffix.lower() in LEAK_SUFFIXES:
            violations.append(f'源码文件：{rel}')
    return violations


def parse_check_output(text: str) -> dict[str, str]:
    """``MaterialSorting.exe --check`` 输出 → dict（``key: value`` 行切分）。"""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ':' in line:
            key, _, value = line.partition(':')
            out[key.strip()] = value.strip()
    return out


# ================================================================ 步骤实现

def step_static_check() -> None:
    if STATIC_DIR.is_dir() and (STATIC_DIR / 'index.html').is_file():
        print(f'[1/6] 前端 static 检查：OK（{STATIC_DIR}）')
        return
    _fail('前端 static 检查',
          f'{STATIC_DIR} 缺失或无 index.html —— 先 cd materialSorting-web && '
          'npm run build（--skip-frontend-check 可跳过本检查，但缺 static 的'
          '产物属无效包）')


def step_env_selfcheck() -> None:
    print('[2/6] 环境自检：')
    r = _run([sys.executable, '-m', 'nuitka', '--version'], timeout=120)
    if r.returncode != 0:
        _fail('环境自检',
              'nuitka 不可用（python -m nuitka --version 失败）—— 须用仓库 '
              f'.venv 的 Python 运行本脚本；缺包先装：{sys.executable} -m pip '
              'install nuitka')
    ver_line = next((ln for ln in r.stdout.splitlines() if ln.strip()),
                    '(未知版本)')
    print(f'  Nuitka 版本：{ver_line.strip()}')
    cc = next((ln for ln in r.stdout.splitlines()
               if ln.startswith('Version C compiler:')), '')
    if cc:
        print(f'  {cc.strip()}（本机探测值；实际构建 --mingw64 强制走 Nuitka '
              '专配 MinGW64 —— MSVC 编大 TU 偶发崩溃，见 nuitka_command 注释）')
    else:
        print('  C 编译器：Nuitka 未探测到 —— 无妨，--mingw64 首次构建自动下载'
              ' MinGW64（--assume-yes-for-downloads 已开）')
    probe = _run([sys.executable, '-c', 'import zstandard'], timeout=60)
    if probe.returncode == 0:
        print('  zstandard：OK')
    else:
        print('  zstandard：缺失（onedir 非硬依赖；如需：'
              f'{sys.executable} -m pip install zstandard）')
    # ordered-set：Nuitka 缺它时退回纯 Python OrderedSetsFallback —— 实测该
    # fallback 在本闭包上迭代器损坏（mergeMultipleBranches/variable_escapable
    # 偶发 TypeError，2026-09-27 多轮不同模块崩点）；C 扩展版绕开且优化更快。
    probe = _run([sys.executable, '-c', 'import ordered_set'], timeout=60)
    if probe.returncode == 0:
        print('  ordered-set：OK（Nuitka 容器 C 加速）')
    else:
        _fail('环境自检',
              'ordered-set 缺失 —— Nuitka 会退回纯 Python OrderedSetsFallback，'
              '实测在本闭包上偶发优化器内部崩溃。先装：'
              f'{sys.executable} -m pip install ordered-set')


def step_spyrrow_check() -> None:
    print('[3/6] spyrrow 私有 wheel 钉板校验：')
    try:
        pin = json.loads(SPYRROW_PIN_FILE.read_text(encoding='utf-8'))
        pinned = pin['wheel_version']
    except (OSError, ValueError, KeyError) as e:
        _fail('spyrrow 钉板校验', f'读 {SPYRROW_PIN_FILE} 失败：{e}')
        return
    r = _run([sys.executable, '-c',
              "import importlib.metadata as m; print(m.version('spyrrow'))"],
             timeout=60)
    installed = r.stdout.strip() if r.returncode == 0 else ''
    tag = re.search(r'\+ms(\d+)', installed or '')
    if installed != pinned or not tag or int(tag.group(1)) < 1:
        _fail('spyrrow 钉板校验',
              f'已装 spyrrow={installed or "(不可用)"} ≠ 钉板 {pinned}（或 '
              "'+ms<N>' N<1）—— 打包锁错 wheel 会静默失去 SE warm（A2 红线）。"
              ' 校正：python scripts/spyrrow_wheel.py status && use-local <wheel>')
    warm = _run([sys.executable, '-c',
                 'from materialsorting.nesting_engine.warmstart import '
                 'warm_start_supported; print(warm_start_supported())'],
                timeout=120)
    if warm.returncode != 0 or warm.stdout.strip() != 'True':
        _fail('spyrrow 钉板校验',
              f'dev 态 warm_start_supported() 探测失败（rc={warm.returncode} '
              f'{warm.stdout.strip()}{warm.stderr.strip()[:200]}）—— 冻进去必错')
    print(f'  已装 {installed} = 钉板 {pinned}，warm_start_supported()=True')


def scan_orphan_processes() -> list[tuple[str, str]]:
    """孤儿编译进程扫描（红线③③）：返回 [(名称/命令行, PID)]。"""
    hits: list[tuple[str, str]] = []
    r = _run(['tasklist', '/FO', 'CSV', '/NH'], timeout=60)
    for line in r.stdout.splitlines():
        fields = [f.strip('"') for f in line.split('","')]
        if len(fields) >= 2 and fields[0].lower() in ORPHAN_IMAGE_NAMES:
            hits.append((fields[0], fields[1]))
    # python -m nuitka 残留（tasklist 显示 python.exe）：查命令行，wmic 缺则
    # powershell Get-CimInstance 兜底，两者皆不可用则跳过（best-effort）。
    csv = None
    if shutil.which('wmic'):
        w = _run(['wmic', 'process', 'where', "name='python.exe'", 'get',
                  'CommandLine,ProcessId', '/FORMAT:CSV'], timeout=60)
        if w.returncode == 0:
            csv = w.stdout
    if csv is None and shutil.which('powershell'):
        p = _run(['powershell', '-NoProfile', '-Command',
                  "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
                  '| Select-Object CommandLine,ProcessId | ConvertTo-Csv '
                  '-NoTypeInformation'], timeout=120)
        if p.returncode == 0:
            csv = p.stdout
    if csv is None:
        print('  （python 命令行扫描不可用：wmic/powershell 均缺席，跳过该路）')
    else:
        for line in csv.splitlines():
            low = line.lower()
            if 'nuitka' in low and 'build_freeze' not in low:
                pid = line.rstrip().rsplit(',', 1)[-1].strip('" \r')
                if pid.isdigit():
                    hits.append((line.strip('" ')[:120], pid))
    return hits


def step_orphan_scan(force: bool) -> None:
    print('[4/6] 孤儿编译进程扫描：')
    hits = scan_orphan_processes()
    if hits:
        for name, pid in hits:
            print(f'  发现存活编译进程：{name}  PID={pid}')
        if not force:
            _fail('孤儿编译进程扫描',
                  f'{len(hits)} 个编译进程存活（硬重启残留叠加 = 双倍风暴，'
                  '2026-09-27 事故复盘红线）—— 先确认并结束它们，或 --force 放行')
        print('  --force 放行（自担风险）')
    else:
        print('  干净（无 cl/ccache/clcache/scons/nuitka 残留）')


def step_compile(cmd: list[str], jobs: int) -> None:
    print(f'[5/6] Nuitka 编译启动（jobs={jobs}，BELOW_NORMAL 优先级，预估 '
          f'{BUILD_TIME_HINT}）：')
    print('  ' + ' '.join(str(c) for c in cmd))
    t0 = time.monotonic()
    creationflags = getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)
    # PYTHONHASHSEED=0：Nuitka 4.2.2 优化器对 try/except 分支合并的遍历顺序
    # 受哈希随机化影响，偶发内部 TypeError（实测同命令不同轮崩在不同模块：
    # pydantic.v1.errors / web.export_plt）—— 固定种子 = 可复现构建 + 规避
    # 撞上该 bug 的种子（2026-09-27 实测定案）。
    env = {**os.environ, 'PYTHONHASHSEED': '0'}
    try:
        proc = subprocess.Popen(cmd, creationflags=creationflags, env=env)
        rc = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        _fail('Nuitka 编译', '被 Ctrl-C 中断（clcache 已保留，可直接重跑）')
        return
    except OSError as e:
        _fail('Nuitka 编译', f'启动失败：{e}')
        return
    elapsed = time.monotonic() - t0
    if rc != 0:
        _fail('Nuitka 编译',
              f'Nuitka 退出码 {rc}（elapsed {elapsed / 60:.1f}min；重跑前可查 '
              'dist/nuitka-report.xml 依赖闭包留档）')
    print(f'  编译完成，elapsed {elapsed / 60:.1f} 分钟')


def step_dist_check(expected_version: str) -> None:
    print('[6/6] dist 自检：')
    if not EXE_PATH.is_file():
        _fail('dist 自检', f'{EXE_PATH} 不存在（编译产物缺失）')
    # ① 源码泄漏红线②
    leaks = scan_dist_leaks(DIST_APP_DIR)
    files = [f for f in DIST_APP_DIR.rglob('*') if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    print(f'  泄漏扫描：{len(files)} 个文件 / {total / 1024 ** 2:.0f} MiB，'
          f'命中 {len(leaks)}')
    for v in leaks[:20]:
        print(f'    {v}')
    if leaks:
        _fail('dist 自检', f'源码泄漏 {len(leaks)} 处（红线②：.py/.pyc/.docs/'
              'tests/scripts 零命中）')
    # ② exe --check（frozen/warm/版本串/static/fonts 落点；MS_OUT_DIR 指临时
    # 目录防自检污染真实 %LOCALAPPDATA%）
    with tempfile.TemporaryDirectory(prefix='ms_freeze_check_') as td:
        env = {**os.environ, 'MS_OUT_DIR': td}
        try:
            r = subprocess.run([str(EXE_PATH), '--check'], env=env,
                               capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=300)
        except subprocess.TimeoutExpired:
            _fail('dist 自检', 'MaterialSorting.exe --check 300s 超时')
            return
    info = parse_check_output(r.stdout)
    print(f"  --check frozen={info.get('frozen')} "
          f"warm_start_supported={info.get('warm_start_supported')} "
          f"version={info.get('version')}")
    if r.returncode != 0 or info.get('frozen') != 'True':
        _fail('dist 自检', f'--check 失败（rc={r.returncode}）：'
              f'{r.stdout[-500:]} {r.stderr[-500:]}')
    if info.get('warm_start_supported') != 'True':
        _fail('dist 自检', 'warm_start_supported != True —— spyrrow 元数据未捆绑'
              '（红线①：--include-distribution-metadata=spyrrow 失效，SE warm '
              '会静默降级）')
    if info.get('version') != expected_version:
        _fail('dist 自检', f"--check version={info.get('version')} ≠ pyproject "
              f'{expected_version}（--include-distribution-metadata='
              'materialsorting 失效）')
    static = Path(info.get('paths.STATIC_DIR', ''))
    fonts = Path(info.get('paths.FONT_DIR', ''))
    ok_static = static.is_dir() and (static / 'index.html').is_file()
    ok_fonts = fonts.is_dir() and (fonts / 'NotoSansSC-Regular.otf').is_file()
    print(f'  static 落点：{static}（{"OK" if ok_static else "缺失"}）')
    print(f'  fonts 落点：{fonts}（{"OK" if ok_fonts else "缺失"}）')
    if not (ok_static and ok_fonts):
        _fail('dist 自检', 'static/fonts 路径校验失败（前端产物或字体资源未捆绑）')


def launch_dist() -> int:
    """``--launch``：直接拉起 dist 冒烟实例（打印 URL，Ctrl-C 退出）。"""
    if not EXE_PATH.is_file():
        _fail('--launch', f'{EXE_PATH} 不存在 —— 先跑一次完整构建')
    print(f'拉起 {EXE_PATH}\n（URL 见进程输出；Ctrl-C 退出，进程随本脚本终止）')
    proc = subprocess.Popen([str(EXE_PATH)], cwd=str(EXE_PATH.parent))
    try:
        proc.wait()
        return proc.returncode or 0
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 130


# ================================================================ main

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='build_freeze.py',
        description='Nuitka 冻结构建：源码 → dist/MaterialSorting.dist（US-003，'
                    '权威 PRD tasks/prd-local-deploy-freeze.md）。',
        epilog='示例：.venv/Scripts/python.exe scripts/build_freeze.py --dry-run')
    parser.add_argument('--dry-run', action='store_true',
                        help='打印完整 Nuitka 命令行 + 环境自检 + jobs 推导，'
                             '不清理不编译（快速验证/回归断言入口）')
    parser.add_argument('--jobs', type=int, default=None, metavar='N',
                        help='Nuitka 并发上限显式覆盖（默认 min(8, max(2, 核数'
                             '//4)) 再按可用内存钳制；env MS_FREEZE_JOBS 次之）')
    parser.add_argument('--skip-frontend-check', action='store_true',
                        help='跳过前端 static 存在性检查')
    parser.add_argument('--force', action='store_true',
                        help='孤儿编译进程扫描命中时放行（自担风险）')
    parser.add_argument('--launch', action='store_true',
                        help='不构建，直接拉起既有 dist 冒烟实例（Ctrl-C 退出）')
    return parser


def main(argv: list[str] | None = None) -> int:
    try:   # Windows 管道/重定向默认 GBK，中文输出前强制 UTF-8（scripts/ 惯例）
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError, OSError):
        pass
    args = build_parser().parse_args(argv)
    if args.launch:
        if args.dry_run:
            _fail('参数', '--launch 与 --dry-run 互斥')
        return launch_dist()

    # ---- 版本串与资源画像（启动横幅，PRD AC8：打印核数/可用内存/jobs/预估时长）
    py_ver = read_pyproject_version()
    describe, commit_count = query_git()
    file_version, display = compute_versions(py_ver, describe, commit_count)
    avail = query_available_memory_bytes()
    cpu = os.cpu_count() or 4
    env_jobs = os.environ.get('MS_FREEZE_JOBS', '').strip()
    override = (args.jobs if args.jobs is not None
                else int(env_jobs) if env_jobs.isdigit() else None)
    jobs, job_lines = derive_jobs(cpu, avail, override)
    print(f'MaterialSorting 冻结构建 · 版本 {display}'
          f'（file-version {file_version}）')
    if avail is not None:
        print(f'机器资源：{cpu} 逻辑核 / 可用内存 {avail / 1024 ** 3:.1f} GiB')
    else:
        print(f'机器资源：{cpu} 逻辑核 / 可用内存（探测失败）')
    for line in job_lines:
        print(line)
    print(f'预估全量构建 {BUILD_TIME_HINT}（低优先级 + jobs={jobs}，期间系统应'
          '保持可交互；构建前请停 ms-web/长跑 solver 等常驻负载）\n')

    # ---- 前置检查（dry-run 同样跑，供回归断言）
    if args.skip_frontend_check:
        print('[1/6] 前端 static 检查：SKIP（--skip-frontend-check）')
    else:
        step_static_check()
    step_env_selfcheck()
    step_spyrrow_check()
    step_orphan_scan(args.force)

    cmd = nuitka_command(jobs, file_version, display, ENTRY_FILE, STATIC_DIR,
                         SERVER_DIR / 'src' / 'materialsorting' / 'resources',
                         DIST_DIR)

    if args.dry_run:
        print('\n--dry-run：完整 Nuitka 命令行（不执行编译）：')
        print('  ' + ' '.join(str(c) for c in cmd))
        print('\n--dry-run 结束（未清理 dist、未编译）。')
        return 0

    # ---- 构建（幂等：dist 先清后建，PRD AC3）
    if DIST_DIR.exists():
        print(f'清理既有 {DIST_DIR} ...')
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)
    step_compile(cmd, jobs)
    step_dist_check(py_ver)

    # 构建目录清理（.build 仅中间产物；clcache 在 %LOCALAPPDATA%\Nuitka 跨重试生效）
    build_dir = DIST_DIR / f'{APP_BASENAME}.build'
    if build_dir.is_dir():
        shutil.rmtree(build_dir, ignore_errors=True)
        print('已清理中间构建目录（clcache 保留在 %LOCALAPPDATA%/Nuitka）')
    print(f'\n[DONE] 冻结产物就绪：{EXE_PATH}')
    print('冒烟：.venv/Scripts/python.exe scripts/build_freeze.py --launch')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
