"""消费端 key 授权闸门（key 授权系统 US-004：机器身份 + 本地状态 + 运行校验）。

消费端（排料系统）与 keyserver（独立顶层系统，US-001~003 已落地四消费接口
``/api/key/bind|merge|info|validate``）的全部通信收口在本模块 —— 上层路由
（US-005 ``routes_key`` / WS / 策略闸门）只调本模块函数，不直接碰 HTTP。

能力四件：
  - **机器身份** ``machine_guid()``：Windows 注册表
    ``HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid``（系统重装才变，
    与 CPU/网卡方案相比不受换硬件影响）；读失败（非 Windows / 权限 / 键缺失）
    → ``LICENSE_DIR/machine_id.txt`` 铸 uuid4 兜底（首铸 stderr warn，此后恒读
    同一值 = 稳定机器身份）。
  - **本地状态** ``load_key_state`` / ``save_key_state``：
    ``LICENSE_DIR/key_state.json`` 持久保存当前绑定 key（后端文件权威 ——
    清浏览器缓存/换浏览器不丢 key）；写盘**原子**（tmp + ``os.replace``，防
    断电/被杀留下半截 JSON）；损坏/缺失 → 空 dict（视为未绑定）。
  - **HTTP 出口** ``_key_post(path, payload, timeout=5.0)``：``urllib.request``
    冻结面零新增依赖（keyserver 契约：业务 4xx 恒 ``{"error": 中文}`` 原样
    透传；超时/``URLError`` → 「无法连接授权服务器…」fail-closed；
    **无自动重试** —— ``deduct=true`` 响应丢失时服务端可能已扣次，重试会双扣）。
  - **运行闸门** ``ensure_run_allowed(doc_source) -> (ok, message)``：
    ① ``MS_KEY_MODE=off`` 仅未冻结（dev）生效 —— 冻结生产 exe 不可绕
    （``getattr(sys,'frozen',False)`` 为真时该开关无效）；② 样例母版豁免
    （``doc.source`` 命中 ``routes_views._sample_dxf_names()`` 实时白名单 →
    免 key 跑通，延迟 import 保持本模块冻结面纯标准库）；③ 本地无 key →
    中文指路文案；④ ``/api/key/validate`` ``deduct=true`` 真扣次校验。

keyserver URL 解析链（``resolve_key_server_url``，请求时读 env 非 import 期
绑定 —— 部署后设 env 无需改代码）：``MS_KEY_SERVER_URL`` env → frozen exe 旁
``key_server_url.txt``（zip 解压部署免设 env）→ 皆无 → ``None``（fail-closed，
调用方一律拒绝运行）。client token 解析链同构（US-009，``resolve_client_token``）：
``MS_KEY_CLIENT_TOKEN`` env → frozen exe 旁 ``key_client_token.txt`` → 皆无不带
header（keyserver 已设 token 而本机未配 → 401 中文透传；frp 双 token 部署契约
见发版手册 §7）。

分层：模块级仅标准库 + ``..paths``（AST 守卫见 tests/test_web_keygate.py，
镜像 edit_hold 先例）；**禁 import cli 子包与 server 模块**（本模块被 server
间接经路由层使用，顶层 import 即成环）。样例白名单走函数内延迟 import
routes_views（同包兄弟，其携带 fastapi —— 不进本模块冻结 import 面）。

冒烟：``python -m materialsorting.web.keygate`` —— 合成夹具自检（临时目录，
不触碰真实 out/ 与注册表；含真 HTTP 服务对拍），全过 exit 0。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .. import paths

try:                                    # Windows 专属标准库（非 Windows 导入即失败）
    import winreg
except ImportError:                     # pragma: no cover - 非 Windows 平台
    winreg = None                       # type: ignore[assignment]

__all__ = [
    'KEY_HTTP_TIMEOUT_S', 'KeyGateError', 'MSG_NO_KEY', 'MSG_NO_SERVER',
    'MSG_UNREACHABLE', 'describe_client_token', 'describe_key_server_url',
    'describe_machine_guid', 'ensure_run_allowed', 'key_state_path',
    'load_key_state', 'machine_guid', 'resolve_client_token',
    'resolve_key_server_url', 'save_key_state',
]

KEY_HTTP_TIMEOUT_S = 5.0              # 单请求超时（PRD 定案：5s，禁自动重试）
KEY_STATE_NAME = 'key_state.json'     # 当前绑定 key 的本地权威文件（LICENSE_DIR 下）
MACHINE_ID_NAME = 'machine_id.txt'    # 注册表读取失败时的兜底机 ID（首铸后稳定）
KEY_URL_FILE_NAME = 'key_server_url.txt'   # frozen exe 旁 URL sidecar（免 env 部署）
KEY_TOKEN_FILE_NAME = 'key_client_token.txt'   # frozen exe 旁 client token sidecar（US-009）
_MACHINE_GUID_KEY = r'SOFTWARE\Microsoft\Cryptography'   # 注册表键（HKLM 下）
_MACHINE_GUID_VALUE = 'MachineGuid'                       # 键内值名（系统 GUID）

MSG_NO_KEY = '未绑定授权 key：请在「当前系统 key 属性」中输入并保存'
MSG_NO_SERVER = '授权服务器未配置：请设置 MS_KEY_SERVER_URL 或在程序目录放置 key_server_url.txt'
MSG_UNREACHABLE = '无法连接授权服务器，请检查网络后重试'


class KeyGateError(Exception):
    """keygate 业务失败 —— ``str(exc)`` 即可直接上屏的中文文案（调用方不再包装）。"""


# ------------------------------------------------------------- keyserver URL 解析链

def resolve_key_server_url() -> str | None:
    """keyserver 基址解析（三档）：``MS_KEY_SERVER_URL`` env → frozen exe 旁
    ``key_server_url.txt``（strip 后非空）→ ``None``（未配置，fail-closed）。

    env 请求时读取（非 import 期绑定）；sidecar 仅 frozen 态生效（dev 态 repo 内
    ``key_server_url.txt`` 是部署配置不是开发配置）。
    """
    env_url = os.environ.get('MS_KEY_SERVER_URL')
    if env_url and env_url.strip():
        return env_url.strip()
    if getattr(sys, 'frozen', False):
        sidecar = Path(sys.executable).resolve().parent / KEY_URL_FILE_NAME
        try:
            text = sidecar.read_text(encoding='utf-8').strip()
        except OSError:
            return None
        return text or None
    return None


def resolve_client_token() -> str | None:
    """``X-Client-Token`` 解析链（US-009，与 URL 链同构）：env
    ``MS_KEY_CLIENT_TOKEN`` → frozen exe 旁 ``key_client_token.txt``（strip 后
    非空；dev 态不读）→ 皆无 ``None``（请求不带该 header —— keyserver 未设
    token 时不影响；keyserver 已设而本机未配 → keyserver 401 中文透传上屏）。

    背景：frp 部署 runbook 双 token 必设（US-009 契约定稿）—— 管理口令护发卡
    财务面，共享 client token 防公网任意调用方打消费端（bind 他机抢绑/扣次烧
    key）。token 值**不回显**（--check 只报已配置/未配置）。
    """
    env_tok = os.environ.get('MS_KEY_CLIENT_TOKEN')
    if env_tok and env_tok.strip():
        return env_tok.strip()
    if getattr(sys, 'frozen', False):
        sidecar = Path(sys.executable).resolve().parent / KEY_TOKEN_FILE_NAME
        try:
            text = sidecar.read_text(encoding='utf-8').strip()
        except OSError:
            return None
        return text or None
    return None


def describe_client_token() -> str:
    """client token 配置态描述（launcher ``--check`` 回显专用，US-009）。

    **不回显 token 值**（共享秘密不进日志/截图）；来源标注同 URL 链口径。
    """
    token = resolve_client_token()
    if token is None:
        return ('未配置（keyserver 未设 MS_KEY_CLIENT_TOKEN 时不影响；'
                '已设而未配 → 消费请求 401）')
    env_tok = (os.environ.get('MS_KEY_CLIENT_TOKEN') or '').strip()
    source = ('MS_KEY_CLIENT_TOKEN env' if env_tok == token
              else 'key_client_token.txt（exe 旁）')
    return f'已配置（来源：{source}，不回显值）'


def describe_key_server_url() -> str:
    """URL 解析结果的人类可读描述（launcher ``--check`` 回显专用，US-009）。

    只读无副作用（不触发任何 HTTP）；来源判定与 :func:`resolve_key_server_url`
    同一真相源 —— env strip 后等于解析结果即 env 档，否则为 frozen sidecar 档。
    """
    url = resolve_key_server_url()
    if url is None:
        return '未配置（fail-closed：设 MS_KEY_SERVER_URL 或在 exe 旁放置 key_server_url.txt）'
    env = (os.environ.get('MS_KEY_SERVER_URL') or '').strip()
    source = 'MS_KEY_SERVER_URL env' if env == url else 'key_server_url.txt（exe 旁）'
    return f'{url}（来源：{source}）'


# ----------------------------------------------------------------- HTTP 出口

def _key_post(path: str, payload: dict, timeout: float = KEY_HTTP_TIMEOUT_S) -> dict:
    """POST JSON 到 keyserver（唯一 HTTP 出口），返回解析后的响应 dict。

    已配置 client token（:func:`resolve_client_token`）时附 ``X-Client-Token``
    请求头（US-009；未配置不带 —— keyserver 双 token 姿态下由其 401 兜底）。

    失败恒抛 :class:`KeyGateError`（文案可直接上屏）：
      - URL 未配置 → ``MSG_NO_SERVER``；
      - 超时 / ``URLError`` / 连接拒绝 → ``MSG_UNREACHABLE``（fail-closed，
        **不自动重试** —— deduct=true 响应丢失时服务端可能已扣次）；
      - HTTP 4xx/5xx 带 ``{"error": ...}`` → 中文 error 原样透传（keyserver
        errors.py 契约）；无 error 字段 / 非 JSON → 通用异常文案。
    """
    base = resolve_key_server_url()
    if not base:
        raise KeyGateError(MSG_NO_SERVER)
    url = base.rstrip('/') + path
    headers = {'Content-Type': 'application/json; charset=utf-8'}
    token = resolve_client_token()
    if token:
        headers['X-Client-Token'] = token
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode('utf-8'), method='POST',
        headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:            # 先于 URLError（其子类）
        message = None
        try:
            decoded = json.loads(exc.read().decode('utf-8'))
            if isinstance(decoded, dict) and isinstance(decoded.get('error'), str):
                message = decoded['error']
        except Exception:                            # noqa: BLE001 - 坏响应体走通用文案
            message = None
        if message:
            raise KeyGateError(message) from None
        raise KeyGateError(f'授权服务器响应异常（HTTP {exc.code}）') from None
    except Exception:                                # noqa: BLE001 - URLError/timeout/OSError 统一口径
        raise KeyGateError(MSG_UNREACHABLE) from None
    try:
        parsed = json.loads(body.decode('utf-8'))
    except Exception:                                # noqa: BLE001
        raise KeyGateError('授权服务器响应异常（非 JSON）') from None
    if not isinstance(parsed, dict):
        raise KeyGateError('授权服务器响应异常（非 JSON 对象）') from None
    return parsed


# ----------------------------------------------------------------- 机器身份

def _license_dir() -> Path:
    """LICENSE_DIR 调用时取值（monkeypatch ``paths.LICENSE_DIR`` 直接生效，
    ``_reload_pieces_state`` 缺省参数坑的同款防御）。"""
    return Path(paths.LICENSE_DIR)


def _read_registry_guid() -> str | None:
    """注册表 MachineGuid 只读探测（非 Windows / 键缺失 / 权限不足 → None 不抛）。"""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_GUID_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _MACHINE_GUID_VALUE)
    except OSError:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _fallback_machine_id() -> str:
    """注册表不可读时的文件兜底：``LICENSE_DIR/machine_id.txt`` 首铸 uuid4，
    此后恒读同一值（稳定机器身份 —— 每次铸新值会把本机变「他机」致绑定失效）。"""
    path = _license_dir() / MACHINE_ID_NAME
    try:
        existing = path.read_text(encoding='utf-8').strip()
    except OSError:
        existing = ''
    if existing:
        return existing
    guid = str(uuid.uuid4())
    _atomic_write_text(path, guid)
    print(f'[keygate] warn: 注册表 MachineGuid 读取失败，已生成本机兜底 ID：{path}',
          file=sys.stderr)
    return guid


def machine_guid() -> str:
    """本机稳定身份：注册表 MachineGuid 优先，失败落文件兜底（首铸 warn）。"""
    return _read_registry_guid() or _fallback_machine_id()


def describe_machine_guid() -> str:
    """机器身份来源只读探测（launcher ``--check`` 回显专用，US-009）。

    与 :func:`machine_guid` 的差异：**不铸兜底文件**（--check 无副作用口径），
    注册表不可读时仅描述「将走文件兜底」的运行时行为。
    """
    guid = _read_registry_guid()
    if guid:
        return f'注册表 MachineGuid 读取成功（{guid[:8]}…）'
    return '注册表 MachineGuid 读取失败（运行时将铸 license/machine_id.txt 文件兜底）'


# ----------------------------------------------------------------- 本地状态

def _atomic_write_text(path: Path, text: str) -> None:
    """原子写（tmp + ``os.replace``）：断电/进程被杀不留半截文件；
    replace 同目录同盘保证原子性，失败清理 tmp 不留残屑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def key_state_path() -> Path:
    """key_state.json 落点（``paths.LICENSE_DIR`` 调用时取值，测试可重定向）。"""
    return _license_dir() / KEY_STATE_NAME


def load_key_state() -> dict:
    """读本地 key 状态：``{'key': <明文>}``；缺失/损坏/非对象 → ``{}``（视为
    未绑定 —— fail-closed 由 :func:`ensure_run_allowed` 第③步接管）。"""
    try:
        raw = key_state_path().read_text(encoding='utf-8')
    except OSError:
        return {}
    try:
        state = json.loads(raw)
    except ValueError:
        return {}
    return state if isinstance(state, dict) else {}


def save_key_state(key: str) -> dict:
    """保存当前绑定 key（原子写）；返回落盘的 state dict。

    明文格式校验不在本层（bind 时 keyserver 404「key 不存在…」即校验）——
    本函数只做持久化，调用方（US-005 ``/api/key/save``）先 bind 成功再保存。
    """
    state = {'key': key}
    _atomic_write_text(
        key_state_path(), json.dumps(state, ensure_ascii=False, indent=2))
    return state


# ----------------------------------------------------------------- 运行闸门

def ensure_run_allowed(doc_source, deduct: bool = True) -> tuple[bool, str]:
    """运行前授权闸门（三入口共用，US-005 接线）：返回 ``(ok, message)``。

    判定序（PRD US-004）：① ``MS_KEY_MODE=off`` 且**未冻结**（dev 逃生口；
    冻结生产 exe 恒不可绕）→ ``(True, 'off')``；② 样例母版豁免
    （``doc.source`` basename 命中 ``data/`` 实时 ``*.dxf`` 白名单 → 免 key
    跑通）→ ``(True, 'sample')``；③ 本地无 key → ``(False, MSG_NO_KEY)``；
    ④ ``validate deduct=true`` 真扣次（扣次唯一锚点 = MS 后端 start）—— 任何
    失败 fail-closed，文案直接上屏，**无自动重试**。

    ``deduct=False``（US-005 ``/api/key/precheck`` 专用）：判定序完全一致、
    唯一差异是 ④ 走 keyserver 预检口径（不动任何账，含 op_log）—— 前端运行
    前拦截（US-007）与本函数共用单一真相源，两口径永不漂移。
    """
    if (os.environ.get('MS_KEY_MODE') == 'off'
            and not getattr(sys, 'frozen', False)):
        return True, 'off'
    from .routes_views import _sample_dxf_names     # 延迟 import：routes_views 带 fastapi，不进本模块冻结 import 面
    source_name = os.path.basename(str(doc_source or ''))
    if source_name and source_name in _sample_dxf_names():
        return True, 'sample'
    key = load_key_state().get('key')
    if not isinstance(key, str) or not key.strip():
        return False, MSG_NO_KEY
    try:
        _key_post('/api/key/validate',
                  {'key': key.strip(), 'machine_guid': machine_guid(),
                   'deduct': bool(deduct)})
    except KeyGateError as exc:
        return False, str(exc)
    return True, ''


# ----------------------------------------------------------------- 冒烟自检

def _smoke() -> int:
    """``python -m materialsorting.web.keygate``：合成夹具自检（临时目录 + 真
    HTTP 服务对拍，不触碰真实 out/ 与注册表写路径），全过 exit 0。"""
    import http.server
    import threading

    results: list[tuple[str, bool]] = []

    def check(name: str, cond: bool) -> None:
        results.append((name, bool(cond)))

    calls: list[dict] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:               # noqa: N802 - http.server 约定
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append({'path': self.path, 'body': body,
                          'token': self.headers.get('X-Client-Token')})
            if body.get('key') == 'MS-BAD00-KEY00-0000X':
                payload, status = {'error': 'key 不存在：请检查输入是否正确'}, 404
            else:
                payload, status = {
                    'type': 'count', 'total_uses': 10, 'used_uses': 1,
                    'remaining_uses': 9, 'status': '正在使用',
                    'bound_system_name': 'smoke', 'remark': 'smoke'}, 200
            data = json.dumps(payload).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:    # 静默测试日志
            pass

    srv = http.server.HTTPServer(('127.0.0.1', 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory(prefix='ms_keygate_smoke_') as td:
            root = Path(td)
            old_license, old_data = paths.LICENSE_DIR, paths.DATA_DIR
            old_reg_guid = _read_registry_guid
            paths.LICENSE_DIR = str(root / 'license')
            paths.DATA_DIR = str(root / 'data')
            (root / 'data').mkdir()
            (root / 'data' / 'M1787样例.dxf').write_bytes(b'x')
            globals()['_read_registry_guid'] = lambda: None
            try:
                # ① 本地状态：原子写 / 重启可读 / 损坏容忍
                save_key_state('MS-SMOK-E0000-00000')
                check('key_state 原子写重启可读',
                      load_key_state() == {'key': 'MS-SMOK-E0000-00000'})
                check('无 tmp 残屑',
                      not list((root / 'license').glob('*.tmp')))
                key_state_path().write_text('{broken', encoding='utf-8')
                check('损坏 key_state 视为未绑定', load_key_state() == {})
                key_state_path().unlink()
                # ② 机器身份：兜底首铸 + 稳定
                first = machine_guid()
                second = machine_guid()
                check('机 ID 兜底稳定', first == second and first)
                # ③ URL 链三档
                os.environ['MS_KEY_SERVER_URL'] = f'http://127.0.0.1:{port}'
                check('URL 档一 env',
                      resolve_key_server_url() == f'http://127.0.0.1:{port}')
                del os.environ['MS_KEY_SERVER_URL']
                old_frozen = getattr(sys, 'frozen', False)
                old_exe = sys.executable
                sys.frozen = True                        # type: ignore[attr-defined]
                sys.executable = str(root / 'app.exe')
                (root / 'key_server_url.txt').write_text(
                    f'http://127.0.0.1:{port}', encoding='utf-8')
                check('URL 档二 frozen sidecar',
                      resolve_key_server_url() == f'http://127.0.0.1:{port}')
                (root / 'key_server_url.txt').unlink()
                check('URL 档三 皆无 fail-closed',
                      resolve_key_server_url() is None)
                sys.frozen = old_frozen                  # type: ignore[attr-defined]
                sys.executable = old_exe
                # ④ 闸门四分支（HTTP 真对拍）
                os.environ['MS_KEY_MODE'] = 'off'
                check('闸门① off 放行', ensure_run_allowed('任意.dxf') == (True, 'off'))
                del os.environ['MS_KEY_MODE']
                check('闸门② 样例豁免',
                      ensure_run_allowed(str(root / 'data' / 'M1787样例.dxf'))
                      == (True, 'sample'))
                check('闸门③ 无 key 指路文案',
                      ensure_run_allowed('user.dxf') == (False, MSG_NO_KEY))
                save_key_state('MS-SMOK-E0000-00000')
                os.environ['MS_KEY_SERVER_URL'] = f'http://127.0.0.1:{port}'
                ok, msg = ensure_run_allowed('user.dxf')
                check('闸门④ validate 放行', ok and calls[-1]['body']['deduct'] is True)
                check('未配 client token 不附头', calls[-1]['token'] is None)
                os.environ['MS_KEY_CLIENT_TOKEN'] = 'smoke-tok'
                check('client token 档一 env 解析',
                      resolve_client_token() == 'smoke-tok')
                _key_post('/api/key/info', {'key': 'MS-SMOK-E0000-00000'})
                check('已配 client token 自动附头',
                      calls[-1]['token'] == 'smoke-tok')
                del os.environ['MS_KEY_CLIENT_TOKEN']
                save_key_state('MS-BAD00-KEY00-0000X')
                n_before = len(calls)
                ok, msg = ensure_run_allowed('user.dxf')
                check('闸门④ keyserver 4xx 中文透传',
                      (ok, msg) == (False, 'key 不存在：请检查输入是否正确'))
                check('无自动重试（恰 1 次请求）', len(calls) - n_before == 1)
                del os.environ['MS_KEY_SERVER_URL']
                n_before = len(calls)
                ok, msg = ensure_run_allowed('user.dxf')
                check('URL 未配置 fail-closed',
                      (ok, msg) == (False, MSG_NO_SERVER) and len(calls) == n_before)
                os.environ['MS_KEY_SERVER_URL'] = 'http://127.0.0.1:1'   # 不可达端口
                ok, msg = ensure_run_allowed('user.dxf')
                check('连接失败 fail-closed',
                      (ok, msg) == (False, MSG_UNREACHABLE))
                del os.environ['MS_KEY_SERVER_URL']
            finally:
                paths.LICENSE_DIR, paths.DATA_DIR = old_license, old_data
                globals()['_read_registry_guid'] = old_reg_guid
                for name in ('MS_KEY_MODE', 'MS_KEY_SERVER_URL',
                             'MS_KEY_CLIENT_TOKEN'):
                    os.environ.pop(name, None)
    finally:
        srv.shutdown()
        srv.server_close()

    n_pass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f'[keygate] {"PASS" if ok else "FAIL"}  {name}')
    print(f'[keygate] 冒烟 {n_pass}/{len(results)} PASS')
    return 0 if n_pass == len(results) else 1


if __name__ == '__main__':
    sys.exit(_smoke())

