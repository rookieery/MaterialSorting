"""机器对接端点浏览器直连 Origin 白名单（prd machine browser direct US-001）。

YL 前端（HTTPS 页面）跨源直连本地 MS（``/api/machine/*``）的跨域准入配置
单一真相源：**Origin 白名单**（协议+域名+端口，须与浏览器 Origin 请求头逐
字符一致 —— 不带尾斜杠、不做归一化，精确匹配才放行）。浏览器直连是「YL
服务器页面 → 用户本机 MS」的跨源新形态，原「同机 loopback 服务端调用」
假设下的零 CORS 现状保持不变 —— **白名单未配置（三档皆无 → ``None``）时
上层（US-002 中间件）不发任何 CORS 头、不校验 Origin，逐字节现状零回归**。

白名单解析三档链（``resolve_machine_allowed_origins``，请求时读取非
import 期绑定 —— 部署后设 env 无需改代码）：
  1. env ``MS_MACHINE_ALLOWED_ORIGINS``（逗号/分号分隔多值，逐项 strip
     去空、set 去重）；
  2. sidecar ``machine_allowed_origins.txt`` **多行列表**（每行一个
     Origin，strip 空行；某位置文件存在但全空行 = 该位未配置，继续向后
     回落查找）；
  3. 皆无 → ``None``（未配置）。

sidecar 候选位置复用 keygate ``_sidecar_candidates`` 模式（查找序即优先
序，2026-09-29 两档定稿同款）：frozen = exe 旁优先 → ``LICENSE_DIR``
回落（license/（frozen 态 ``%LOCALAPPDATA%\\MaterialSorting\\out\\
license\\``）是机器本地权威位，新构建 dist 不带 sidecar / 安装目录只读 /
覆盖重装场景接线均不丢）；dev = 仅 ``LICENSE_DIR``（out/license/，
gitignored 机器本地；exe 旁 = frozen 专属交付契约 dev 不读）。**sidecar
交付链**（维护位单源 → generate-dist 同步 + 预检硬校验 + launcher
``--check`` 回显）见 US-004。

分层：模块级仅标准库 + ``..paths``（AST 守卫见
tests/test_web_machine_cors.py，镜像 keygate 先例）；**禁 import cli
子包与 server 模块**（本模块被 server 经中间件注册使用，顶层 import 即
成环）。

冒烟：``python -m materialsorting.web.machine_cors`` —— 合成夹具自检
（临时目录，不触碰真实 out/）+ 当前进程实际白名单解析结果打印（三档
来源标注），全过 exit 0。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import paths

__all__ = [
    'MACHINE_ORIGINS_ENV', 'MACHINE_ORIGINS_FILE_NAME',
    'describe_machine_allowed_origins', 'resolve_machine_allowed_origins',
]

MACHINE_ORIGINS_ENV = 'MS_MACHINE_ALLOWED_ORIGINS'          # 档一：env 变量名
MACHINE_ORIGINS_FILE_NAME = 'machine_allowed_origins.txt'   # 档二：sidecar 文件名（多行）


def _license_dir() -> Path:
    """LICENSE_DIR 调用时取值（monkeypatch ``paths.LICENSE_DIR`` 直接生效，
    keygate ``_reload_pieces_state`` 缺省参数坑的同款防御）。"""
    return Path(paths.LICENSE_DIR)


def _sidecar_candidates() -> list[tuple[str, Path]]:
    """sidecar 候选位置单一真相源（查找序即优先序，keygate 两档定稿同款）：

    - **frozen**：``[exe 旁（交付契约，US-004 generate-dist 同步落包）,
      LICENSE_DIR 回落]`` —— 回落档动机同 keygate：license/ 是 key 授权机器
      本地权威目录（key_state.json 落此），新构建 dist 不带 sidecar / 安装
      目录只读 / 覆盖重装场景接线均不丢（exe 旁仍优先，交付契约不变）；
    - **dev**：仅 ``LICENSE_DIR``（out/license/，gitignored 机器本地；exe 旁
      = frozen 专属交付契约 dev 不读）。
    """
    if getattr(sys, 'frozen', False):
        return [(f'{MACHINE_ORIGINS_FILE_NAME}（exe 旁）',
                 Path(sys.executable).resolve().parent / MACHINE_ORIGINS_FILE_NAME),
                (f'{MACHINE_ORIGINS_FILE_NAME}（license/ 回落档）',
                 _license_dir() / MACHINE_ORIGINS_FILE_NAME)]
    return [(f'{MACHINE_ORIGINS_FILE_NAME}（out/license/）',
             _license_dir() / MACHINE_ORIGINS_FILE_NAME)]


def _parse_env_origins(raw: str) -> set[str]:
    """env 值解析：逗号/分号混合分隔 + 逐项 strip + 去空（set 天然去重）。"""
    return {item.strip() for item in raw.replace(';', ',').split(',')
            if item.strip()}


def _parse_sidecar_origins(path: Path) -> set[str]:
    """sidecar 多行列表解析：逐行 strip、空行剔除（set 天然去重）。"""
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return set()
    return {line.strip() for line in lines if line.strip()}


def resolve_machine_allowed_origins() -> set[str] | None:
    """Origin 白名单解析（三档）：env ``MS_MACHINE_ALLOWED_ORIGINS``（逗号/
    分号分隔多值）→ sidecar ``machine_allowed_origins.txt``（多行列表；
    frozen = exe 旁优先 → LICENSE_DIR 回落 / dev = LICENSE_DIR）→ 皆无
    ``None``（未配置 = 浏览器直连 CORS 不生效，上层零回归现状）。

    env/sidecar 均**请求时读取**（非 import 期绑定 —— 部署后设 env 或落
    sidecar 无需改代码）；sidecar 候选序见 :func:`_sidecar_candidates`。
    """
    env_raw = os.environ.get(MACHINE_ORIGINS_ENV)
    if env_raw and env_raw.strip():
        return _parse_env_origins(env_raw)
    for _, path in _sidecar_candidates():
        origins = _parse_sidecar_origins(path)
        if origins:
            return origins
    return None


def _sidecar_origin(origins: set[str]) -> str:
    """定位 ``origins`` 实际来自哪个 sidecar 候选（来源标注专用；与
    :func:`resolve_machine_allowed_origins` 同一候选序，无匹配 → 「来源
    未知」兜底）。"""
    for label, path in _sidecar_candidates():
        if _parse_sidecar_origins(path) == origins:
            return label
    return f'{MACHINE_ORIGINS_FILE_NAME}（来源未知）'


def describe_machine_allowed_origins() -> str:
    """白名单解析结果的人类可读描述（``__main__`` 冒烟打印 / launcher
    ``--check`` 回显专用，US-004 接线）。

    只读无副作用；来源判定与 :func:`resolve_machine_allowed_origins`
    同一真相源 —— env strip 后解析等于解析结果即 env 档，否则按 sidecar
    候选序定位实际命中文件。Origin 值非秘密（生产域名随 ACAO 回显头公开
    给浏览器），可直接回显。
    """
    origins = resolve_machine_allowed_origins()
    if origins is None:
        return ('未配置（浏览器直连 CORS 不生效：不发 CORS 头、不校验 Origin，'
                '与现状逐字节一致；配置 = 设 MS_MACHINE_ALLOWED_ORIGINS env，'
                '或放置 machine_allowed_origins.txt —— frozen：exe 旁或 '
                'license/ 目录（%LOCALAPPDATA%\\MaterialSorting\\out\\license\\）；'
                '源码部署：out/license/）')
    env_raw = (os.environ.get(MACHINE_ORIGINS_ENV) or '').strip()
    if env_raw and _parse_env_origins(env_raw) == origins:
        source = f'{MACHINE_ORIGINS_ENV} env'
    else:
        source = _sidecar_origin(origins)
    return ('、'.join(sorted(origins))
            + f'（来源：{source}，共 {len(origins)} 条）')


# ----------------------------------------------------------------- 冒烟自检

def _smoke() -> int:
    """``python -m materialsorting.web.machine_cors``：合成夹具自检（临时
    目录，不触碰真实 out/；frozen 双位置对拍走 keygate 冒烟同款
    ``sys.frozen`` + 临时 exe 路径写法）+ 当前进程实际解析结果打印（三档
    来源标注），全过 exit 0。"""
    import tempfile

    results: list[tuple[str, bool]] = []
    # 当前（真实机器）解析结果在合成夹具动手**之前**采样 —— 夹具 finally 会
    # 清 env/还原状态，末尾打印须反映真实配置而非被夹具归零后的值。
    current = describe_machine_allowed_origins()

    def check(name: str, cond: bool) -> None:
        results.append((name, bool(cond)))

    with tempfile.TemporaryDirectory(prefix='ms_machine_cors_smoke_') as td:
        root = Path(td)
        old_license = paths.LICENSE_DIR
        old_frozen = getattr(sys, 'frozen', False)
        old_exe = sys.executable
        paths.LICENSE_DIR = str(root / 'license')
        try:
            # ① 档一 env：单值 / 多值（逗号+分号混用）/ 空白串视为未配置
            os.environ[MACHINE_ORIGINS_ENV] = 'https://yl.example.com'
            check('档一 env 单值',
                  resolve_machine_allowed_origins() == {'https://yl.example.com'})
            os.environ[MACHINE_ORIGINS_ENV] = (
                'https://a.example.com, https://b.example.com;'
                'https://c.example.com')
            check('档一 env 多值（逗号/分号混用解析）',
                  resolve_machine_allowed_origins()
                  == {'https://a.example.com', 'https://b.example.com',
                      'https://c.example.com'})
            os.environ[MACHINE_ORIGINS_ENV] = '   '
            check('env 空白串视为未配置（不与 sidecar 抢档）',
                  resolve_machine_allowed_origins() is None)
            del os.environ[MACHINE_ORIGINS_ENV]
            # ② 档二 frozen exe 旁 sidecar（多行列表，strip 空行）
            sys.frozen = True                        # type: ignore[attr-defined]
            sys.executable = str(root / 'app.exe')
            (root / MACHINE_ORIGINS_FILE_NAME).write_text(
                'https://exe.example.com\n\n  https://exe2.example.com  \n\n',
                encoding='utf-8')
            check('档二 frozen exe 旁 sidecar 多行解析（空行剔除）',
                  resolve_machine_allowed_origins()
                  == {'https://exe.example.com', 'https://exe2.example.com'})
            # ②′ exe 旁空文件（全空行）→ license/ 回落
            (root / MACHINE_ORIGINS_FILE_NAME).write_text('  \n \n',
                                                          encoding='utf-8')
            (root / 'license').mkdir(parents=True, exist_ok=True)
            (root / 'license' / MACHINE_ORIGINS_FILE_NAME).write_text(
                'https://lic.example.com\n', encoding='utf-8')
            check('档二-prime exe 旁空文件回落 license/',
                  resolve_machine_allowed_origins()
                  == {'https://lic.example.com'})
            # ②″ 双位置并存 exe 旁优先
            (root / MACHINE_ORIGINS_FILE_NAME).write_text(
                'https://exe.example.com', encoding='utf-8')
            check('frozen 双位置并存 exe 旁优先',
                  resolve_machine_allowed_origins()
                  == {'https://exe.example.com'})
            (root / MACHINE_ORIGINS_FILE_NAME).unlink()
            (root / 'license' / MACHINE_ORIGINS_FILE_NAME).unlink()
            check('frozen 皆无返回 None',
                  resolve_machine_allowed_origins() is None)
            # ③ dev（未冻结）读 out/license/，exe 旁不读
            sys.frozen = False                       # type: ignore[attr-defined]
            (root / MACHINE_ORIGINS_FILE_NAME).write_text(
                'https://exe.example.com', encoding='utf-8')
            (root / 'license' / MACHINE_ORIGINS_FILE_NAME).write_text(
                'https://dev.example.com', encoding='utf-8')
            check('档二-triple dev 读 out/license/ sidecar',
                  resolve_machine_allowed_origins()
                  == {'https://dev.example.com'})
            (root / 'license' / MACHINE_ORIGINS_FILE_NAME).unlink()
            check('dev 不读 exe 旁 sidecar（exe 旁 = frozen 交付契约）',
                  resolve_machine_allowed_origins() is None)
            (root / MACHINE_ORIGINS_FILE_NAME).unlink()
            # ④ 三档皆无 → None
            check('三档皆无返回 None（零回归现状档）',
                  resolve_machine_allowed_origins() is None)
            # ⑤ 档序锁定：env 优先于 sidecar
            os.environ[MACHINE_ORIGINS_ENV] = 'https://env.example.com'
            (root / 'license' / MACHINE_ORIGINS_FILE_NAME).write_text(
                'https://lic.example.com', encoding='utf-8')
            check('档序锁定 env 优先于 sidecar',
                  resolve_machine_allowed_origins()
                  == {'https://env.example.com'})
        finally:
            paths.LICENSE_DIR = old_license
            sys.frozen = old_frozen                  # type: ignore[attr-defined]
            sys.executable = old_exe
            os.environ.pop(MACHINE_ORIGINS_ENV, None)

    n_pass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f'[machine_cors] {"PASS" if ok else "FAIL"}  {name}')
    print(f'[machine_cors] 冒烟 {n_pass}/{len(results)} PASS')
    print(f'[machine_cors] 当前白名单解析结果：{current}')
    return 0 if n_pass == len(results) else 1


if __name__ == '__main__':
    sys.exit(_smoke())
