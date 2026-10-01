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

US-002 中间件（``register_machine_cors(app)``，server.py 文件尾在
``register_machine_routes`` 之后调用一次）：``BaseHTTPMiddleware`` dispatch
(:func:`_machine_cors_dispatch`) 仅作用于 ``/api/machine/*`` 前缀（其余
路径 —— 工作台 /api/*、/ws、/export —— 原样放行零扰动），四分支：
  1. 白名单未配置（``None``）→ 直通零回归：不发 CORS 头、不校验 Origin、
     OPTIONS 落路由 405（逐字节现状档）；
  2. OPTIONS + 白名单内 Origin → **预检自答** 200 五头（ACAO 回显具体值
     禁 ``*`` / Allow-Methods ``GET, POST, DELETE`` / Allow-Headers
     ``x-machine-token, content-type`` / Allow-Private-Network ``true``
     （PNA：Chrome/Edge HTTPS 页面 → 本机 loopback 直连准入，缺头预检即
     败）/ Max-Age ``86400``）—— 中间件先于路由执行，不自答则 405；
  3. 白名单外 Origin（任意方法，含预检 OPTIONS）→ 403 服务端主动拒（防
     恶意网页 CSRF 型 simple request 触发任务），不带任何 CORS 头；
  4. 白名单内 Origin 实际请求（GET/POST/DELETE）→ 路由照常 + 响应附 ACAO
     回显（401/400/404 错误体浏览器可读）+ ``Vary: Origin``。无 Origin 头
     （YL 服务端中转 / curl / loopback 同机）→ 直通不加头。

分层：模块级仅标准库 + ``..paths``（AST 守卫见
tests/test_web_machine_cors.py，镜像 keygate 先例）；**禁 import cli
子包与 server 模块**（本模块被 server 经中间件注册使用，顶层 import 即
成环）；starlette import 全部**函数内延迟**（``register_machine_cors`` 的
``BaseHTTPMiddleware`` / 响应构造的 ``Response``/``JSONResponse``）。

冒烟：``python -m materialsorting.web.machine_cors`` —— 合成夹具自检
（临时目录，不触碰真实 out/）+ US-002 中间件装配冒烟（fresh app + 探针
端点 + ``register_machine_cors``）+ 当前进程实际白名单解析结果打印（三档
来源标注），全过 exit 0。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import paths

__all__ = [
    'MACHINE_ORIGINS_ENV', 'MACHINE_ORIGINS_FILE_NAME', 'register_machine_cors',
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


# --------------------------------------------------- US-002 CORS+PNA 中间件

# 中间件作用面前缀（request.url.path.startswith 判定）：仅机器对接族，其余
# 路径（工作台 /api/*、/ws、/export、静态资源）原样放行不受白名单影响。
MACHINE_API_PREFIX = '/api/machine/'
# 预检应答五头的值域契约（US-002 验收金标）：Methods = 机器族六端点全部方法
# 面（solve POST / status·result·state-file GET / stop POST / DELETE DELETE）；
# Headers = token 闸头 + JSON/f multipart 两类体类型；Max-Age = 预检结果缓存
# 一天（省 YL 页面高频探测的 OPTIONS 往返）。
MACHINE_ALLOW_METHODS = 'GET, POST, DELETE'
MACHINE_ALLOW_HEADERS = 'x-machine-token, content-type'
MACHINE_MAX_AGE = '86400'


def _preflight_response(origin: str):
    """CORS 预检自答（200 空体 + 五头，白名单内 Origin 专用）。

    ACAO 回显请求 Origin **具体值**（禁 ``*`` —— 白名单是精确匹配清单，
    通配会放行白名单外页面）；PNA 头无条件附 ``true``（Chrome/Edge 对
    HTTPS 页面 → loopback 直连强制要求，浏览器未发 PNA 请求头时多带此头
    无害）。另附 ``Vary: Origin``（ACAO 随 Origin 变化，缓存键须含之 ——
    Starlette CORSMiddleware 同款）。
    """
    from starlette.responses import Response
    return Response(status_code=200, headers={
        'Access-Control-Allow-Origin': origin,
        'Access-Control-Allow-Methods': MACHINE_ALLOW_METHODS,
        'Access-Control-Allow-Headers': MACHINE_ALLOW_HEADERS,
        'Access-Control-Allow-Private-Network': 'true',
        'Access-Control-Max-Age': MACHINE_MAX_AGE,
        'Vary': 'Origin',
    })


def _rejected_response(origin: str):
    """白名单外 Origin 拒绝（403，不带任何 CORS 头）。

    服务端主动校验（浏览器侧无 ACAO 头本就判失败，403 是纵深防御）：拦在
    路由前 —— 恶意网页 CSRF 型 **simple request**（表单/img 等不触发预检的
    请求）打不到任务端点，spawn/export/DELETE 全部不可达。中文错误体供
    YL 联调与日志定位（Origin 值非秘密可直接回显）。
    """
    from starlette.responses import JSONResponse
    return JSONResponse(
        {'error': f'Origin {origin} 不在机器对接白名单内，已拒绝该跨源请求'
                  f'（配置 = env {MACHINE_ORIGINS_ENV} 或 sidecar '
                  f'{MACHINE_ORIGINS_FILE_NAME}）'},
        status_code=403)


async def _machine_cors_dispatch(request, call_next):
    """``/api/machine/*`` 跨域准入 dispatch（``register_machine_cors`` 装配）。

    四分支见模块 docstring（前缀外直通 → 未配置直通零回归 → OPTIONS 预检
    自答 → 外域 403），白名单内实际请求经 ``call_next`` 后附 ACAO 回显 +
    ``Vary: Origin``（401/400/404 错误响应同样带 —— 浏览器可读错误体）。
    白名单**请求时读取**（:func:`resolve_machine_allowed_origins`，部署期
    设 env / 落 sidecar 即时生效，无需重启）。无 Origin 头（服务端/工具
    直调）→ 路由照常、不加头（loopback 同机调用现状零变化）。
    """
    if not request.url.path.startswith(MACHINE_API_PREFIX):
        return await call_next(request)
    allowed = resolve_machine_allowed_origins()
    if allowed is None:
        return await call_next(request)          # 未配置 = 零回归现状档
    origin = request.headers.get('origin')
    if request.method == 'OPTIONS' and origin in allowed:
        return _preflight_response(origin)
    if origin is not None and origin not in allowed:
        return _rejected_response(origin)
    response = await call_next(request)
    if origin is not None:                       # 此处 origin ∈ allowed
        response.headers['access-control-allow-origin'] = origin
        response.headers.append('vary', 'Origin')
    return response


def register_machine_cors(app) -> None:
    """把机器对接 CORS 中间件挂到 FastAPI app（server.py 文件尾调用一次，
    位于 ``register_machine_routes`` 之后）。

    ``BaseHTTPMiddleware`` + dispatch=:func:`_machine_cors_dispatch`：用户
    中间件位于 ExceptionMiddleware 之外 —— 路由抛的 ``HTTPException``/
    ``JSONResponse`` 错误（401/400/404）先被内层转成响应、再回到本中间件
    附 ACAO（浏览器可读错误体的机制前提）。starlette import 函数内延迟
    （模块级仅标准库红线不动，machine/server 防环先例同款）。
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    app.add_middleware(BaseHTTPMiddleware, dispatch=_machine_cors_dispatch)


# ----------------------------------------------------------------- 冒烟自检

def _smoke_middleware(check) -> None:
    """US-002 中间件装配冒烟（六查）：fresh FastAPI app + 机器族探针端点 +
    ``register_machine_cors`` → 预检五头 / 外域 403 / 白名单响应 ACAO 回显 /
    无 Origin 直通 / 前缀外零扰动 / 未配置 OPTIONS 落 405。env 与
    ``paths.LICENSE_DIR`` 均套 try-finally（不触碰真实白名单状态，开发者
    本机 sidecar 不串档）。"""
    import tempfile

    from fastapi import FastAPI
    from starlette.testclient import TestClient

    app = FastAPI()

    @app.get('/api/machine/__probe__')
    def _probe():
        return {'ok': True}

    @app.get('/')
    def _index():
        return {'ok': True}

    register_machine_cors(app)
    old_env = os.environ.get(MACHINE_ORIGINS_ENV)
    old_license = paths.LICENSE_DIR
    with tempfile.TemporaryDirectory(prefix='ms_machine_cors_mw_') as td:
        paths.LICENSE_DIR = td          # 未配置查档防本机 sidecar 串入
        try:
            os.environ[MACHINE_ORIGINS_ENV] = 'https://yl-smoke.example.com'
            client = TestClient(app)
            r = client.options('/api/machine/__probe__', headers={
                'Origin': 'https://yl-smoke.example.com',
                'Access-Control-Request-Method': 'GET',
                'Access-Control-Request-Private-Network': 'true'})
            check('中间件预检自答 200 五头精确值',
                  r.status_code == 200
                  and r.headers.get('access-control-allow-origin')
                  == 'https://yl-smoke.example.com'
                  and r.headers.get('access-control-allow-methods')
                  == MACHINE_ALLOW_METHODS
                  and r.headers.get('access-control-allow-headers')
                  == MACHINE_ALLOW_HEADERS
                  and r.headers.get('access-control-allow-private-network')
                  == 'true'
                  and r.headers.get('access-control-max-age') == MACHINE_MAX_AGE)
            r = client.get('/api/machine/__probe__',
                           headers={'Origin': 'https://evil.example'})
            check('中间件白名单外 403 且无 CORS 头',
                  r.status_code == 403
                  and 'access-control-allow-origin' not in r.headers)
            r = client.get('/api/machine/__probe__',
                           headers={'Origin': 'https://yl-smoke.example.com'})
            check('中间件白名单内实际响应 ACAO 回显',
                  r.status_code == 200
                  and r.headers.get('access-control-allow-origin')
                  == 'https://yl-smoke.example.com')
            r = client.get('/api/machine/__probe__')
            check('中间件无 Origin 直通不加头（loopback 服务端同现状）',
                  r.status_code == 200
                  and 'access-control-allow-origin' not in r.headers)
            r = client.get('/', headers={'Origin': 'https://evil.example'})
            check('中间件前缀外路径零扰动（外域 Origin 不 403 不加头）',
                  r.status_code == 200
                  and 'access-control-allow-origin' not in r.headers)
            os.environ.pop(MACHINE_ORIGINS_ENV, None)
            r = client.options('/api/machine/__probe__', headers={
                'Origin': 'https://yl-smoke.example.com',
                'Access-Control-Request-Method': 'GET'})
            check('中间件未配置零回归（OPTIONS 落 405 无 CORS 头）',
                  r.status_code == 405
                  and 'access-control-allow-origin' not in r.headers)
        finally:
            paths.LICENSE_DIR = old_license
            if old_env is None:
                os.environ.pop(MACHINE_ORIGINS_ENV, None)
            else:
                os.environ[MACHINE_ORIGINS_ENV] = old_env


def _smoke() -> int:
    """``python -m materialsorting.web.machine_cors``：合成夹具自检（临时
    目录，不触碰真实 out/；frozen 双位置对拍走 keygate 冒烟同款
    ``sys.frozen`` + 临时 exe 路径写法）+ US-002 中间件装配冒烟（fresh app
    + 探针端点 + ``register_machine_cors``）+ 当前进程实际解析结果打印
    （三档来源标注），全过 exit 0。"""
    import tempfile

    results: list[tuple[str, bool]] = []
    # 当前（真实机器）解析结果在合成夹具动手**之前**采样 —— 夹具 finally 会
    # 清 env/还原状态，末尾打印须反映真实配置而非被夹具归零后的值。
    current = describe_machine_allowed_origins()

    def check(name: str, cond: bool) -> None:
        results.append((name, bool(cond)))

    _smoke_middleware(check)
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
