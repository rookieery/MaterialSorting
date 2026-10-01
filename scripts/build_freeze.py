"""Nuitka 冻结构建脚本（US-003，权威 PRD：tasks/prd-local-deploy-freeze.md）。

一条命令从源码产出可分发 onedir::

    .venv/Scripts/python.exe scripts/build_freeze.py            # 全量构建 + dist 自检
    .venv/Scripts/python.exe scripts/build_freeze.py --dry-run  # 打印命令行/自检/jobs 推导，不编译
    .venv/Scripts/python.exe scripts/build_freeze.py --launch   # 直接拉起 dist 冒烟实例（Ctrl-C 退出）
    .venv/Scripts/python.exe scripts/build_freeze.py --installer           # 全量构建 + 第 7 步：安装包/绿色 zip
    .venv/Scripts/python.exe scripts/build_freeze.py --installer-only      # 不编译，对既有 dist 补打包（iss 迭代用）

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
  - Inno Setup（可选，``--installer`` 安装包线，缺席自动跳过不失败）：
    ``winget install --id JRSoftware.InnoSetup --scope user``（免管理员，落
    ``%LOCALAPPDATA%\Programs\Inno Setup 6``）或官网安装器
    https://jrsoftware.org/isdl.php；简体中文语言包已随仓 vendor
    （scripts/installer/ChineseSimplified.isl），无需另装。

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
  ④ key 接线 sidecar 双闸 —— ``key_server_url.txt``/``key_client_token.txt``
    必须随包落 exe 旁（漏 = 客户机「授权服务器未配置」/401，2026-09-29 交付
    事故：打包在先、手工铺文件在后，同型于样例 b1f66e3）：闸一预检 = 构建机
    维护位（dev ``paths.LICENSE_DIR`` 同位）两文件非空 fail-closed；闸二 =
    dist 自检入口先从维护位同步再硬校验（``--installer-only`` 补打包路径同样
    覆盖）。逃生口 ``--skip-key-sidecar``（内部测试构建专用）。
  ⑤ 机器直连 Origin 白名单 sidecar（US-004，浏览器直连交付链）——
    ``machine_allowed_origins.txt`` 同款双闸：维护位 ``out/license/`` 单源
    （预填 YL 生产域名占位，交付前运维替换实值；可多行多 Origin）→ 闸一
    预检 + 闸二 dist 同步硬校验（``--installer-only`` 同覆盖）。逃生口
    ``--skip-machine-sidecar``。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

# ---------------------------------------------------------------- 路径常量
# 脚本位于 <repo>/scripts/ → parents[1] = repo 根（不硬编码 .. 上溯之外的绝对路径）。
ROOT = Path(__file__).resolve().parents[1]
ENTRY_FILE = ROOT / 'scripts' / 'freeze_entry.py'          # Nuitka 入口适配层
STATIC_DIR = ROOT / 'materialSorting-web' / 'static'       # 前端 React 构建产物
DATA_DIR = ROOT / 'data'                                   # 样例母版目录（顶层 .dxf 随包）
# key 接线 sidecar 文件名（与 web/keygate.py KEY_URL_FILE_NAME/KEY_TOKEN_FILE_NAME
# 逐条对齐 —— scripts 不 import 业务包（全标准库先例），复制常量 + 对齐锚点测试
# 锁死，sample_dxf_files ↔ routes_views._sample_dxf_names 同款约定）
KEY_SIDECAR_NAMES = ('key_server_url.txt', 'key_client_token.txt')
# 机器直连 Origin 白名单 sidecar 文件名（与 web/machine_cors.py
# MACHINE_ORIGINS_FILE_NAME 逐字对齐 —— scripts 不 import 业务包（全标准库
# 先例），复制常量 + 锚点测试锁死，同 KEY_SIDECAR_NAMES ↔ keygate 约定）
MACHINE_SIDECAR_NAME = 'machine_allowed_origins.txt'
SERVER_DIR = ROOT / 'materialSorting-server'
PYPROJECT = SERVER_DIR / 'pyproject.toml'
SPYRROW_PIN_FILE = SERVER_DIR / 'spyrrow_build.json'       # 私有 wheel 钉板（四字段）
DIST_DIR = ROOT / 'dist'
APP_BASENAME = 'MaterialSorting'
DIST_APP_DIR = DIST_DIR / f'{APP_BASENAME}.dist'
EXE_PATH = DIST_APP_DIR / f'{APP_BASENAME}.exe'

# ---------------------------------------------------------------- 安装包（US-005）
ISS_FILE = ROOT / 'scripts' / 'installer' / 'materialsorting.iss'
ISL_FILE = ROOT / 'scripts' / 'installer' / 'ChineseSimplified.isl'
# 应用图标（2026-09-27 定稿：候选 02「嵌套裁片·冰蓝」，用户从 12 稿中选定；
# 源头可重生成 = scripts/make_app_icon.py --index 2 --ico scripts/installer/app.ico）。
APP_ICON = ROOT / 'scripts' / 'installer' / 'app.ico'
# ISCC 兜底安装位（PATH 缺席时逐个探测）：%LOCALAPPDATA%\Programs（winget
# --scope user 落点）+ Program Files 两个官方默认位。
ISCC_FALLBACK_PATHS = (
    r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    r'C:\Program Files\Inno Setup 6\ISCC.exe',
)
# 绿色 zip 内附一行启动说明（PRD AC4）。
PORTABLE_README_NAME = '启动说明.txt'
PORTABLE_README_LINE = ('解压后双击 MaterialSorting.exe 启动 VB超排（自动打开默认'
                        '浏览器）；用户数据在 %LOCALAPPDATA%\\MaterialSorting，'
                        '与程序目录分离，升级覆盖不丢')

# 六步流水基线；--installer 尾部追加第 7 步（main 里按需置 7，打印口径统一）。
STEP_TOTAL = 6

# ---------------------------------------------------------------- 版本资源
# 资源串一律 ASCII：中文进 build_definitions.h 后被 cl.exe 按系统代码页(936)
# 误读，UTF-8 多字节错位产生「常量中有换行符 C2001」编译失败（2026-09-27 实
# 测）；中文产品名「VB超排」走 US-005 Inno 安装包/快捷方式/前端标题，exe 资源
# 页保 ASCII 对应物（2026-09-27 更名定稿）。
COMPANY_NAME = 'MaterialSorting'
PRODUCT_NAME = 'VB Super Nesting Workbench'
FILE_DESCRIPTION = 'VB Super Nesting (jeans marker making)'

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


# ================================================================ 安装包（US-005，纯函数）

def fs_version(display: str) -> str:
    """display 版本串 → 文件名安全串：空白折叠为 ``-``。

    ``0.1.0 g590375b dirty`` → ``0.1.0-g590375b-dirty`` —— setup.exe 与
    portable zip 的 ``<版本>`` 段共用本函数（单一真相源，两侧命名不漂移）。
    """
    return re.sub(r'\s+', '-', display.strip())


def find_iscc() -> Path | None:
    """ISCC.exe 定位：PATH → winget/官方标准安装位（PRD AC2）。

    全缺席 → None（调用方打印安装指引并跳过安装包编译，不判失败）。
    """
    found = shutil.which('ISCC.exe') or shutil.which('ISCC')
    if found:
        return Path(found)
    localappdata = os.environ.get('LOCALAPPDATA', '')
    candidates = ([Path(localappdata) / 'Programs' / 'Inno Setup 6' / 'ISCC.exe']
                  if localappdata else [])
    candidates += [Path(p) for p in ISCC_FALLBACK_PATHS]
    for c in candidates:
        if c.is_file():
            return c
    return None


def iscc_command(iscc: Path, display: str, file_version: str,
                 iss: Path | None = None) -> list[str]:
    """ISCC 命令行：版本经 ``/D`` 注入（与 Nuitka 冻结资源同源版本串，AC1）。

    三 define 对齐 iss 头 ``#ifndef`` 缺省占位（手工裸编译 iss 不炸）：
    ``MyAppVersion``（AppVersion 属性串，可含空格）/ ``MyAppVersionNumber``
    （数字四段，VersionInfoVersion 限制）/ ``MyAppVersionFS``（文件名安全串，
    OutputBaseFilename）。
    """
    return [str(iscc),
            f'/DMyAppVersion={display}',
            f'/DMyAppVersionNumber={file_version}',
            f'/DMyAppVersionFS={fs_version(display)}',
            str(iss if iss is not None else ISS_FILE)]


def sign_command(target: Path, env: dict[str, str]) -> list[str] | None:
    """signtool 钩子（PRD 定案⑦：签名证书不采购，仅留代码路径）。

    env ``MS_SIGNING_PFX`` 与 ``MS_SIGNING_TS`` **同时在场**才启用（运营采购
    证书后配置 env 即生效）；缺任一 → None（不签名）；env 在场但 signtool
    不在 PATH → SystemExit（配了签名却没签 = 不该静默放过）。
    """
    pfx = env.get('MS_SIGNING_PFX', '').strip()
    ts = env.get('MS_SIGNING_TS', '').strip()
    if not (pfx and ts):
        return None
    tool = shutil.which('signtool.exe') or shutil.which('signtool')
    if not tool:
        raise SystemExit('MS_SIGNING_PFX/MS_SIGNING_TS 已配置但 signtool 不在 '
                         'PATH —— 安装 Windows SDK（Signing Tools）后重试')
    cmd = [tool, 'sign', '/fd', 'SHA256', '/tr', ts, '/td', 'SHA256', '/f', pfx]
    pwd = env.get('MS_SIGNING_PWD', '')
    if pwd:
        cmd += ['/p', pwd]
    return cmd + [str(target)]


def make_portable_zip(dist_app_dir: Path, zip_path: Path,
                      readme_name: str = PORTABLE_README_NAME,
                      readme_line: str = PORTABLE_README_LINE) -> int:
    """绿色 zip（PRD AC4）：dist 整树压缩 + 一行启动说明 txt。

    zip 内统一顶层目录 ``MaterialSorting/``（解压不散一地；``.dist`` 后缀
    不进包名）；启动说明挂顶层目录下。返回打包文件数（说明 txt 不计）。
    """
    count = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(dist_app_dir.rglob('*')):
            if path.is_file():
                zf.write(path, f'{APP_BASENAME}/'
                         f'{path.relative_to(dist_app_dir).as_posix()}')
                count += 1
        zf.writestr(f'{APP_BASENAME}/{readme_name}', readme_line + '\n')
    return count


# ================================================================ 样例母版（纯函数）

def sample_dxf_files(data_dir: Path) -> list[Path]:
    """``data/`` 顶层 ``*.dxf`` 样例文件列表（按文件名排序，非递归）。

    口径与 ``web/routes_views._sample_dxf_names`` 逐条对齐（``/api/samples``
    列表端点的列举白名单）：仅顶层文件、后缀 lower 判 ``.dxf``（大写 ``.DXF``
    也收）、``.plt`` / ``configs/`` 子目录不收 —— 捆绑面 = 样例功能可见面，
    内部实验资产（PLT 参考件 / CLI 配置示例）不进客户包。

    样例文件名含中文与 ``#``/``%``/``（）`` 等 URI/命令行保留字符（如
    ``3069#（2025抓毛靓商11%5%直纹7cm腰埋夹围加8.5）146.dxf``）——
    ``--include-data-file=src=dst`` 以 ``=`` 分隔，**文件名含 ``=`` 即参数解析
    错位**，此处 fail-fast 防将来踩坑（现役样例名均不含 ``=``）。

    目录缺失 → 空列表（调用方 step_static_check 对空列表 fail —— 样例是 UI
    交付功能，静默缺失 = 2026-09-29「exe 无可用样例」事故同型复发）。
    """
    if not data_dir.is_dir():
        return []
    files = [p for p in data_dir.iterdir()
             if p.is_file() and p.name.lower().endswith('.dxf')]
    for p in files:
        if '=' in p.name:
            raise SystemExit(
                f'样例文件名含 = 会破坏 Nuitka --include-data-file 参数解析：'
                f'{p.name}（改名后重试）')
    return sorted(files, key=lambda p: p.name)


# ================================================================ key 接线 sidecar（纯函数）

def key_sidecar_dir() -> Path:
    """构建机 sidecar 维护位 = dev 态 ``paths.LICENSE_DIR`` 同一推导（env
    ``MS_OUT_DIR`` → 缺省 ``materialSorting-server/out``，再接 ``/license``）。

    dev 部署的 keygate 与本脚本打包共用这一处文件 —— 单一维护点：发卡交付物
    （keyserver 基址 / client token）更新时只改这里，dev 重启即生效、下次打包
    自动带上（2026-09-29 交付事故前 sidecar 靠手工分头铺四处，打包时序错位即
    打出坏包）。``MS_OUT_DIR`` 取非空值才生效（空串视同未设，比 paths.py 的
    ``os.environ.get`` 缺省形多一层防御）。
    """
    out_dir = os.environ.get('MS_OUT_DIR') or str(SERVER_DIR / 'out')
    return Path(out_dir) / 'license'


def key_sidecar_missing(sidecar_dir: Path) -> list[str]:
    """sidecar 缺失清单：返回 ``KEY_SIDECAR_NAMES`` 中不在 ``sidecar_dir`` 或
    strip 后为空的文件名（全在场非空 = 空列表）。

    空文件视同缺失 —— keygate ``_read_sidecar`` 同口径（strip 后非空才算配置，
    空文件继续向后回落查找）。闸一（维护位预检）与闸二（dist exe 旁校验）
    共用本函数。
    """
    missing: list[str] = []
    for name in KEY_SIDECAR_NAMES:
        try:
            ok = bool((sidecar_dir / name).read_text(encoding='utf-8').strip())
        except OSError:
            ok = False
        if not ok:
            missing.append(name)
    return missing


def copy_key_sidecars(dist_app_dir: Path,
                      source_dir: Path | None = None) -> list[str]:
    """维护位两文件 → dist exe 旁（源非空在场才拷）；返回实际拷入文件名。

    dist 侧既有同名文件一律覆盖（维护位 = 唯一真相源 —— 覆盖安装/手工铺放的
    旧文件被纠正为维护位现值；彻底缺失由调用方 ``step_dist_check`` 闸二兜底
    报错）。``shutil.copy2`` 保留源 mtime（Inno/zip 同款语义）。**token 是共享
    秘密：本函数与全部调用方打印永不回显内容**（镜像 keygate
    ``describe_client_token`` 口径）。
    """
    src = source_dir if source_dir is not None else key_sidecar_dir()
    copied: list[str] = []
    for name in KEY_SIDECAR_NAMES:
        source = src / name
        try:
            if not source.read_text(encoding='utf-8').strip():
                continue
        except OSError:
            continue
        shutil.copy2(source, dist_app_dir / name)
        copied.append(name)
    return copied


def check_key_sidecar_source() -> None:
    """key 接线 sidecar 预检（红线④闸一）：维护位两文件必须非空在场，缺失
    fail-closed —— 在 30~90 分钟编译**之前**暴露，勿等 dist 自检。
    """
    missing = key_sidecar_missing(key_sidecar_dir())
    if missing:
        _fail('key sidecar 预检',
              f'{key_sidecar_dir()} 缺 {"、".join(missing)} —— 安装包将不带 key '
              '接线，客户机必报「授权服务器未配置」（缺 URL）或 401「消费 token '
              '缺失」（缺 token，生产双 token 姿态）。把两文件放到该目录（内容 = '
              'keyserver 公网基址一行 / client token 一行，与 dev 态 keygate 同位'
              '共用），或内部测试构建加 --skip-key-sidecar')
    print(f'  key 接线 sidecar：OK（{len(KEY_SIDECAR_NAMES)} 个文件 ← '
          f'{key_sidecar_dir()}）')


# ================================================== 机器直连 Origin 白名单 sidecar（US-004，纯函数）

def machine_sidecar_origins(directory: Path) -> list[str]:
    """sidecar 非空行读取（machine_cors ``_parse_sidecar_origins`` 同口径：
    逐行 strip、空行剔除、天然保序）；文件缺失/不可读 → 空列表。

    **不支持注释行** —— 每一非空行都是一条 Origin，占位文件里写说明文字会被
    当白名单条目（构建闸与运行时解析同口径，防「预检过了、运行时白名单被
    污染」的静默漂移）。
    """
    try:
        lines = (directory / MACHINE_SIDECAR_NAME).read_text(
            encoding='utf-8').splitlines()
    except OSError:
        return []
    return [ln.strip() for ln in lines if ln.strip()]


def machine_sidecar_missing(directory: Path) -> list[str]:
    """机器直连 sidecar 缺失检查：文件不在/不可读/全空行（= 该位未配置，
    machine_cors 空行剔除口径）皆视同缺失，返回 ``[MACHINE_SIDECAR_NAME]``；
    ≥1 非空行 → ``[]``。单元素列表形与 :func:`key_sidecar_missing` 一致
    （闸一/闸二报错文案 ``"、".join`` 复用）。
    """
    return [] if machine_sidecar_origins(directory) else [MACHINE_SIDECAR_NAME]


def copy_machine_sidecar(dist_app_dir: Path,
                         source_dir: Path | None = None) -> list[str]:
    """维护位 sidecar → dist exe 旁（源非空行在场才拷）；返回实际拷入文件名。

    dist 侧既有同名文件一律覆盖（维护位 = 唯一真相源 —— 手工铺进 dist 的旧
    白名单被纠正为维护位现值，:func:`copy_key_sidecars` 同语义）；彻底缺失由
    调用方 ``step_dist_check`` 闸二兜底报错。``shutil.copy2`` 保留 mtime。
    打印只报文件名与条数，Origin 值不逐条回显（虽非秘密，日志口径与 key
    sidecar 统一）。"""
    src = source_dir if source_dir is not None else key_sidecar_dir()
    if machine_sidecar_missing(src):
        return []
    shutil.copy2(src / MACHINE_SIDECAR_NAME, dist_app_dir / MACHINE_SIDECAR_NAME)
    return [MACHINE_SIDECAR_NAME]


def check_machine_sidecar_source() -> None:
    """机器直连 Origin 白名单 sidecar 预检（US-004 闸一）：维护位文件须 ≥1
    非空行，缺失/全空 fail-closed —— 在 30~90 分钟编译**之前**暴露。

    维护位 = key sidecar 维护位同一目录（``out/license/``，dev 态
    machine_cors 与打包同位共用单一维护点）；缺文件 = 安装包不带白名单，
    YL 前端（HTTPS 页面）跨源直连本地 MS 的 CORS 预检全被拒（浏览器直连
    交付断链，同 key 接线缺失的事故等级）。"""
    if machine_sidecar_missing(key_sidecar_dir()):
        _fail('机器直连 sidecar 预检',
              f'{key_sidecar_dir() / MACHINE_SIDECAR_NAME} 缺失或无非空行 —— '
              '安装包将不带 Origin 白名单，YL 前端（HTTPS 页面）跨源直连本地 '
              'MS 会被 CORS 拒（浏览器直连交付断链）。把该文件放到维护位'
              '（每行一个 Origin = 协议+域名+端口，与浏览器 Origin 头精确一致、'
              '不带尾斜杠，可多行多 Origin；**只写 Origin 行不放说明文字** —— '
              '每一非空行都是白名单条目；文件预填 YL 生产域名占位值，交付前由'
              '运维替换为实值），或内部测试构建加 --skip-machine-sidecar')
    print(f'  机器直连 Origin 白名单 sidecar：OK'
          f'（{len(machine_sidecar_origins(key_sidecar_dir()))} 条 ← '
          f'{key_sidecar_dir() / MACHINE_SIDECAR_NAME}；交付前运维把占位值替换'
          '为 YL 生产域名实值）')


# ================================================================ Nuitka 命令（常量段）

def nuitka_command(jobs: int, file_version: str, version_display: str,
                   entry: Path, static_dir: Path, resources_dir: Path,
                   dist_dir: Path, data_dir: Path | None = None) -> list[str]:
    """Nuitka 命令行组装（PRD AC2 常量段，逐旗标注释）。

    注：delvewheel ``.libs`` DLL 目录（numpy.libs=OpenBLAS / shapely.libs=GEOS）
    不走 ``--include-data-dir`` —— Nuitka 对纯 DLL 目录报「No data files」，
    扩展模块的 DLL 依赖由其依赖扫描自动收（dist 自检 + 冒烟兜底验证）。

    ``data_dir``（2026-09-29 无样例 bug 修复）：样例母版目录 —— 顶层 ``.dxf``
    逐文件 ``--include-data-file`` 捆绑到 exe 同级 ``data/``（frozen 态
    ``MS_DATA_DIR`` 缺省指向，见 launcher.apply_frozen_env）；``None`` 兼容
    旧调用形（不捆绑，仅测试消费）。**必须逐文件**而非整目录
    ``--include-data-dir``：``data/`` 里的 ``.plt`` 参考件与 ``configs/``
    实验配置是内部开发资产，不进客户安装包。
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
        f'--windows-icon-from-ico={APP_ICON}',  # exe/任务栏图标（02 冰蓝定稿，资源为二进制 .ico 无 936 代码页坑）
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
    # 样例母版逐文件捆绑（=data/<name>，frozen MS_DATA_DIR 缺省落点）
    if data_dir is not None:
        cmd += [f'--include-data-file={p}=data/{p.name}'
                for p in sample_dxf_files(data_dir)]
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
    if not (STATIC_DIR.is_dir() and (STATIC_DIR / 'index.html').is_file()):
        _fail('前端 static 检查',
              f'{STATIC_DIR} 缺失或无 index.html —— 先 cd materialSorting-web && '
              'npm run build（--skip-frontend-check 可跳过本检查，但缺 static 的'
              '产物属无效包）')
    # 样例母版预检（2026-09-29 无样例 bug 修复）：data/ 顶层 .dxf 是「样例」
    # 下拉框的交付内容 —— 空目录静默打出「（无可用样例）」包即本次事故同型，
    # 构建期 fail 早暴露（dist 自检对落点二次硬校验兜底）。
    samples = sample_dxf_files(DATA_DIR)
    if not samples:
        _fail('前端 static 检查',
              f'{DATA_DIR} 无顶层 .dxf 样例 —— 上传预览「样例」下拉框将恒空'
              '（2026-09-29 exe 无样例事故同型）。补样例文件或确认 DATA_DIR 落点')
    print(f'[1/{STEP_TOTAL}] 前端 static 检查：OK（{STATIC_DIR}）')
    print(f'  样例母版：{len(samples)} 个 .dxf（{DATA_DIR}）')


def step_env_selfcheck() -> None:
    print(f'[2/{STEP_TOTAL}] 环境自检：')
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
    print(f'[3/{STEP_TOTAL}] spyrrow 私有 wheel 钉板校验：')
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
    print(f'[4/{STEP_TOTAL}] 孤儿编译进程扫描：')
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
    print(f'[5/{STEP_TOTAL}] Nuitka 编译启动（jobs={jobs}，BELOW_NORMAL 优先级，预估 '
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


def step_dist_check(expected_version: str,
                    skip_key_sidecar: bool = False,
                    skip_machine_sidecar: bool = False) -> None:
    print(f'[6/{STEP_TOTAL}] dist 自检：')
    if not EXE_PATH.is_file():
        _fail('dist 自检', f'{EXE_PATH} 不存在（编译产物缺失）')
    # ⓪ key 接线 sidecar（红线④闸二）：入口先从构建机维护位同步再硬校验 ——
    # 收口在此（而非 Nuitka --include-data-file）使 --installer-only 补打包路径
    # 同样覆盖（2026-09-29 交付事故形态 = 打包时序错位，修复必须不经重编译）
    if skip_key_sidecar:
        print('  key 接线 sidecar：SKIP（--skip-key-sidecar，内部测试构建专用）')
    else:
        copied = copy_key_sidecars(DIST_APP_DIR)
        if copied:
            print(f'  key 接线 sidecar：已从维护位同步 {len(copied)} 个文件到 exe 旁')
        missing = key_sidecar_missing(DIST_APP_DIR)
        if missing:
            _fail('dist 自检',
                  f'key 接线 sidecar 缺失（exe 旁无 {"、".join(missing)}）—— 客户机'
                  '必报「授权服务器未配置」（缺 URL）或 401「消费 token 缺失」'
                  '（2026-09-29 交付事故同型，红线④）。维护位 '
                  f'{key_sidecar_dir()} 补文件后重跑，或内部测试构建加 '
                  '--skip-key-sidecar')
        print(f'  key 接线 sidecar：OK（exe 旁 {"、".join(KEY_SIDECAR_NAMES)}）')
    # ⓪′ 机器直连 Origin 白名单 sidecar（US-004，镜像 key 双闸先例）：同样先从
    # 维护位同步再硬校验，收口在 dist 自检入口 = --installer-only 补打包路径
    # 同样覆盖（交付包缺 sidecar 即构建失败，不经重编译可修复）
    if skip_machine_sidecar:
        print('  机器直连 sidecar：SKIP（--skip-machine-sidecar，内部测试构建专用）')
    else:
        copied = copy_machine_sidecar(DIST_APP_DIR)
        if copied:
            print(f'  机器直连 sidecar：已从维护位同步 {MACHINE_SIDECAR_NAME} 到 exe 旁')
        missing = machine_sidecar_missing(DIST_APP_DIR)
        if missing:
            _fail('dist 自检',
                  f'机器直连 sidecar 缺失（exe 旁无 {"、".join(missing)}）—— YL 前端'
                  '跨源直连本地 MS 会被 CORS 拒（US-004 交付链）。维护位 '
                  f'{key_sidecar_dir() / MACHINE_SIDECAR_NAME} 补文件后重跑，或内部'
                  '测试构建加 --skip-machine-sidecar')
        print(f'  机器直连 sidecar：OK（exe 旁 {MACHINE_SIDECAR_NAME}）')
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
    data = Path(info.get('paths.DATA_DIR', ''))
    ok_static = static.is_dir() and (static / 'index.html').is_file()
    ok_fonts = fonts.is_dir() and (fonts / 'NotoSansSC-Regular.otf').is_file()
    ok_data = data.is_dir() and any(data.glob('*.dxf'))
    print(f'  static 落点：{static}（{"OK" if ok_static else "缺失"}）')
    print(f'  fonts 落点：{fonts}（{"OK" if ok_fonts else "缺失"}）')
    print(f'  data 落点：{data}（{"OK" if ok_data else "缺失"}，'
          f'{len(sample_dxf_files(data))} 个样例）')
    if not (ok_static and ok_fonts):
        _fail('dist 自检', 'static/fonts 路径校验失败（前端产物或字体资源未捆绑）')
    if not ok_data:
        _fail('dist 自检', 'data 路径校验失败（样例母版未捆绑 —— 上传预览'
              '「样例」下拉框恒空 + key 闸门样例豁免 sha256 对拍悬空；'
              '2026-09-29 无样例 bug 修复项）')


def step_installer(display: str, file_version: str) -> None:
    """第 7 步（``--installer`` / ``--installer-only``）：中文安装包 + 绿色 zip。

    - ISCC 缺席 = 打印安装指引并跳过安装包编译，**不判失败**（PRD AC2）；
    - 绿色 zip 恒产（AC4，与 ISCC 在场与否无关）；
    - signtool 钩子仅 env ``MS_SIGNING_PFX``/``MS_SIGNING_TS`` 在场才调用。
    """
    print(f'[{STEP_TOTAL}/{STEP_TOTAL}] 安装包与绿色 zip：')
    if not EXE_PATH.is_file():
        _fail('安装包', f'{EXE_PATH} 缺失 —— 先完整构建（本步骤不打包子集）')
    for asset, label in ((ISS_FILE, 'Inno 脚本'), (ISL_FILE, '中文语言包')):
        if not asset.is_file():
            _fail('安装包', f'{label}资产缺失：{asset}')
    setup_exe = DIST_DIR / f'{APP_BASENAME}-Setup-{fs_version(display)}.exe'
    iscc = find_iscc()
    if iscc is None:
        print('  ISCC.exe 未找到 —— 跳过安装包编译（不判失败，其余产物完整）。'
              '安装指引：')
        print('    winget install --id JRSoftware.InnoSetup --scope user'
              '   # 推荐：免管理员，落 %LOCALAPPDATA%\\Programs\\Inno Setup 6')
        print('    或官网安装器 https://jrsoftware.org/isdl.py'
              '（默认装 C:\\Program Files (x86)\\Inno Setup 6）')
        print('    简体中文语言包已随仓 vendor（scripts/installer/'
              'ChineseSimplified.isl），无需另装')
        print('    装好后补打包：build_freeze.py --installer-only'
              '（复用既有 dist，不重编译）')
    else:
        cmd = iscc_command(iscc, display, file_version)
        print(f'  ISCC：{iscc}')
        print('  ' + ' '.join(cmd))
        r = _run(cmd, timeout=1800)
        if r.returncode != 0 or not setup_exe.is_file():
            _fail('安装包', f'ISCC 退出码 {r.returncode}（或产物 {setup_exe} 未出现）'
                  f'{(r.stdout or "")[-800:]} {(r.stderr or "")[-800:]}')
        print(f'  安装包：{setup_exe.name}'
              f'（{setup_exe.stat().st_size / 1024 ** 2:.0f} MiB）')
        sign = sign_command(setup_exe, dict(os.environ))
        if sign is None:
            print('  签名：跳过（未配置 MS_SIGNING_PFX/MS_SIGNING_TS —— PRD 定案⑦'
                  '证书不采购，误报治理走发版手册申诉指引）')
        else:
            rs = _run(sign, timeout=300)
            if rs.returncode != 0:
                _fail('安装包', f'signtool 退出码 {rs.returncode}：'
                      f'{(rs.stdout or "")[-400:]} {(rs.stderr or "")[-400:]}')
            print('  签名：OK（signtool 钩子）')
    zip_path = DIST_DIR / f'{APP_BASENAME}-portable-{fs_version(display)}.zip'
    n = make_portable_zip(DIST_APP_DIR, zip_path)
    print(f'  绿色 zip：{zip_path.name}（{n} 文件 + 启动说明.txt，'
          f'{zip_path.stat().st_size / 1024 ** 2:.0f} MiB，解压即用）')


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

def _rmtree_force(path: Path) -> None:
    """``shutil.rmtree`` Windows 只读容错版（2026-09-30 实勘）。

    样例母版源文件可带只读位（U 盘/压缩包来源，实测 ``data/`` 两个母版
    ``3069#…146.dxf`` / ``M1787#…(2).dxf`` 只读），Nuitka
    ``--include-data-file`` 拷贝保留属性 → 既有 dist 里躺只读文件，下次
    重建 ``rmtree`` 走 ``os.unlink`` 删只读文件 WinError 5 拒绝访问、构建
    在编译前即炸。onerror 清只读位重试一次，仍失败才抛（真句柄锁/ACL
    问题不该被吞）。
    """
    def _clear_readonly(func, target, exc_info):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onerror=_clear_readonly)


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
    parser.add_argument('--skip-key-sidecar', action='store_true',
                        help='跳过 key 接线 sidecar 预检与 dist 同步/校验（内部'
                             '测试构建专用；交付客户的包必须带 key_server_url.txt '
                             '+ key_client_token.txt 两文件，红线④）')
    parser.add_argument('--skip-machine-sidecar', action='store_true',
                        help='跳过机器直连 Origin 白名单 sidecar 预检与 dist 同步/'
                             '校验（内部测试构建专用；交付客户的包必须带 '
                             'machine_allowed_origins.txt，US-004 浏览器直连'
                             '交付链）')
    parser.add_argument('--force', action='store_true',
                        help='孤儿编译进程扫描命中时放行（自担风险）')
    parser.add_argument('--launch', action='store_true',
                        help='不构建，直接拉起既有 dist 冒烟实例（Ctrl-C 退出）')
    parser.add_argument('--installer', action='store_true',
                        help='构建尾部追加第 7 步：ISCC 中文安装包（ISCC 缺席'
                             '打印安装指引跳过、不判失败）+ 绿色 portable zip'
                             '（恒产）')
    parser.add_argument('--installer-only', action='store_true',
                        help='不重新编译：对既有 dist 直接跑 dist 自检 + 第 7 步'
                             '打包（iss 迭代/补打包用；版本串取当前 git 态，'
                             '与 --dry-run/--launch/--installer 互斥）')
    return parser


def main(argv: list[str] | None = None) -> int:
    global STEP_TOTAL   # --installer 形态下流水扩为 7 步（打印口径统一）
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
    if args.installer_only:
        if args.dry_run or args.launch:
            _fail('参数', '--installer-only 与 --dry-run/--launch 互斥')
        if args.installer:
            _fail('参数', '--installer-only 已含第 7 步打包（不要再给 --installer）')
        STEP_TOTAL = 7
        py_ver = read_pyproject_version()
        describe, commit_count = query_git()
        file_version, display = compute_versions(py_ver, describe, commit_count)
        print(f'MaterialSorting 安装包补打包（--installer-only，不重新编译）· '
              f'版本 {display}')
        print('  注意：版本串取当前 git 状态 —— dist 若构建于其他提交，'
              '正式发版走全量 --installer（发版手册「日常发版三步」）\n')
        step_dist_check(py_ver, skip_key_sidecar=args.skip_key_sidecar,
                        skip_machine_sidecar=args.skip_machine_sidecar)
        step_installer(display, file_version)
        print(f'\n[DONE] 发版产物（{DIST_DIR}）：')
        setup = DIST_DIR / f'{APP_BASENAME}-Setup-{fs_version(display)}.exe'
        if setup.is_file():
            print(f'  安装包：{setup.name}')
        else:
            print('  安装包：（未产出 —— ISCC 未安装，见上方指引；绿色 zip 已完整）')
        print(f'  绿色 zip：{APP_BASENAME}-portable-{fs_version(display)}.zip')
        return 0

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

    if args.installer:
        STEP_TOTAL = 7

    # ---- 前置检查（dry-run 同样跑，供回归断言）
    if args.skip_frontend_check:
        print(f'[1/{STEP_TOTAL}] 前端 static 检查：SKIP（--skip-frontend-check）')
    else:
        step_static_check()
    # key sidecar 预检（红线④闸一）独立于 --skip-frontend-check（前端产物与 key
    # 接线是两个交付关注点，不连坐；内部测试构建用 --skip-key-sidecar 显式跳过）
    if args.skip_key_sidecar:
        print('  key 接线 sidecar：SKIP 预检（--skip-key-sidecar，内部测试构建专用）')
    else:
        check_key_sidecar_source()
    # 机器直连 sidecar 预检（US-004 闸一）同 key 口径独立于 --skip-frontend-check
    # （三个交付关注点不连坐；内部测试构建用 --skip-machine-sidecar 显式跳）
    if args.skip_machine_sidecar:
        print('  机器直连 sidecar：SKIP 预检（--skip-machine-sidecar，内部测试构建专用）')
    else:
        check_machine_sidecar_source()
    step_env_selfcheck()
    step_spyrrow_check()
    step_orphan_scan(args.force)

    cmd = nuitka_command(jobs, file_version, display, ENTRY_FILE, STATIC_DIR,
                         SERVER_DIR / 'src' / 'materialsorting' / 'resources',
                         DIST_DIR, DATA_DIR)

    if args.dry_run:
        print('\n--dry-run：完整 Nuitka 命令行（不执行编译）：')
        print('  ' + ' '.join(str(c) for c in cmd))
        if args.installer:
            iscc = find_iscc()
            print('\n--dry-run：第 7 步安装包命令行（--installer）：')
            if iscc is not None:
                print('  ' + ' '.join(iscc_command(iscc, display, file_version)))
            else:
                print('  （ISCC 未找到 → 实际运行将跳过安装包编译，仅产绿色 zip）')
            print(f'  绿色 zip 目标：'
                  f'{DIST_DIR / f"{APP_BASENAME}-portable-{fs_version(display)}.zip"}')
        print('\n--dry-run 结束（未清理 dist、未编译）。')
        return 0

    # ---- 构建（幂等：dist 先清后建，PRD AC3）
    if DIST_DIR.exists():
        print(f'清理既有 {DIST_DIR} ...')
        _rmtree_force(DIST_DIR)
    DIST_DIR.mkdir(parents=True)
    step_compile(cmd, jobs)
    step_dist_check(py_ver, skip_key_sidecar=args.skip_key_sidecar,
                    skip_machine_sidecar=args.skip_machine_sidecar)

    # 构建目录清理（.build 仅中间产物；clcache 在 %LOCALAPPDATA%\Nuitka 跨重试生效）
    build_dir = DIST_DIR / f'{APP_BASENAME}.build'
    if build_dir.is_dir():
        try:
            _rmtree_force(build_dir)
        except OSError as exc:
            print(f'warn: 中间构建目录清理失败（不影响产物）：{exc}')
        else:
            print('已清理中间构建目录（clcache 保留在 %LOCALAPPDATA%/Nuitka）')
    if args.installer:
        step_installer(display, file_version)
    print(f'\n[DONE] 冻结产物就绪：{EXE_PATH}')
    if args.installer:
        print(f'  安装包：{DIST_DIR / f"{APP_BASENAME}-Setup-{fs_version(display)}.exe"}')
        print(f'  绿色 zip：{DIST_DIR / f"{APP_BASENAME}-portable-{fs_version(display)}.zip"}')
    print('冒烟：.venv/Scripts/python.exe scripts/build_freeze.py --launch')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
