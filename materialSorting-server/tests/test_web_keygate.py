"""消费端 key 授权闸门 keygate（US-004：机器身份 / 本地状态 / URL 链 / 运行闸门）测试。

覆盖：
1. AST 守卫：模块级仅标准库 + ``..paths``（冻结面零新增依赖），禁 import
   server / cli 子包（镜像 test_web_edit_hold 先例；``_smoke`` 内的
   ``http.server``/``threading`` 是函数级延迟 import 不受顶层约束）；
2. ``LICENSE_DIR``：``paths`` 常量 = ``OUT_DIR/license``（frozen 态随 MS_OUT_DIR
   落 %LOCALAPPDATA%）；
3. key_state.json：原子写（tmp+rename 无残屑）/ 重启可读 / 损坏与非对象容忍；
4. ``machine_guid``：注册表优先（真机 winreg 实测）/ 兜底文件首铸 + 稳定；
5. URL 链三档：env → frozen exe 旁 sidecar（dev 不读）→ 皆无 fail-closed；
6. ``_key_post``（真 http.server 对拍）：200 解析 / 4xx 中文 error 透传 /
   5xx 通用文案 / 非 JSON / 超时 / 连接拒绝 / **无自动重试**（计数恰 1）；
7. ``ensure_run_allowed`` 四分支：off 仅 dev / 样例标记豁免（2026-09-29 收紧：
   ``sample=True`` 标记才免 key，文件名不再豁免）/ 无 key 指路文案 / validate
   deduct=true 放行与失败透传；
8. ``python -m materialsorting.web.keygate`` 子进程冒烟 exit 0。
"""
from __future__ import annotations

import ast
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.web import keygate


# ----------------------------------------------------------------- fixtures

@pytest.fixture
def license_dir(tmp_path, monkeypatch):
    """LICENSE_DIR 重定向到 tmp（keygate 调用时取 ``paths.LICENSE_DIR`` 模块属性）。"""
    target = tmp_path / 'license'
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(target))
    return target


@pytest.fixture
def no_server_url(monkeypatch):
    """URL 链归零：无 env、未冻结（三档 fail-closed 起点）。"""
    monkeypatch.delenv('MS_KEY_SERVER_URL', raising=False)
    monkeypatch.delattr(sys, 'frozen', raising=False)


@pytest.fixture
def set_server_url(monkeypatch):
    """设 MS_KEY_SERVER_URL（monkeypatch 域内，测后自动清 —— 不泄漏到其他用例）。"""
    def _set(url: str) -> None:
        monkeypatch.setenv('MS_KEY_SERVER_URL', url)
    return _set


class _StubServer:
    """本地 keyserver 桩（真 HTTP 往返）：记录请求、按脚本回包。

    ``script`` 是 ``[(status, body_dict_or_bytes), ...]`` 循环消费；请求体全部
    落 ``calls`` 供载荷断言（deduct=True / key / machine_guid）。
    """

    def __init__(self, script, *, delay_s: float = 0.0):
        self.script = script
        self.delay_s = delay_s
        self.calls: list[dict] = []
        outer = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):               # noqa: N802 - http.server 约定
                body = json.loads(
                    self.rfile.read(int(self.headers['Content-Length'])))
                outer.calls.append({'path': self.path, 'body': body,
                                    'token': self.headers.get('X-Client-Token')})
                if outer.delay_s:
                    time.sleep(outer.delay_s)
                status, payload = outer.script[len(outer.calls) - 1
                                                ] if len(outer.calls) <= len(outer.script) \
                    else outer.script[-1]
                data = (payload if isinstance(payload, bytes)
                        else json.dumps(payload).encode('utf-8'))
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):    # 静默测试日志
                pass

        self._srv = http.server.HTTPServer(('127.0.0.1', 0), _Handler)
        self.port = self._srv.server_address[1]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f'http://127.0.0.1:{self.port}'

    def __enter__(self) -> '_StubServer':
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._srv.shutdown()
        self._srv.server_close()
        self._thread.join(timeout=2)


_INFO_OK = {'type': 'count', 'total_uses': 10, 'used_uses': 2, 'remaining_uses': 8,
            'status': '正在使用', 'bound_system_name': '测试机', 'remark': '测试机'}


# ------------------------------------------------------------- AST 守卫（分层）

def test_keygate_module_layering_purity():
    """keygate 模块级仅标准库 + ``..paths``；禁 import server（server → 路由 →
    keygate 单向无环）/ 禁 import cli 子包（镜像 edit_hold 守卫）。"""
    src = Path(keygate.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'json', 'os', 'sys', 'tempfile', 'urllib', 'uuid',
               'pathlib', 'winreg', 'materialsorting'}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue          # 函数/类体内延迟 import（routes_views / http.server）不受顶层约束
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                names = {a.name.split('.')[0] for a in sub.names}
            elif isinstance(sub, ast.ImportFrom):
                mod = sub.module or ''
                assert not mod.startswith('materialsorting.web.server'), \
                    'keygate 禁 import server（依赖方向 server → keygate）'
                assert not mod.startswith('materialsorting.cli'), \
                    'keygate 禁 import cli（web 禁反向依赖上层）'
                if sub.level:                 # 相对 import 解析到上层 paths
                    names = {'materialsorting'}
                else:
                    names = {mod.split('.')[0]}
            else:
                continue
            assert names <= allowed, sorted(names - allowed)
    # 相对 import 白名单（任意位置）：仅顶层 ``..paths``（2026-09-29 样例豁免
    # 标记化后 keygate 不再延迟 import .routes_views —— 样例标记由 commit 期
    # server._verify_sample_claim 铸成，闸门只读参数）
    for sub in ast.walk(tree):
        if isinstance(sub, ast.ImportFrom) and sub.level:
            # ``from .. import paths``（module=None）与 ``from ..paths import X`` 两形态
            ok = sub.level == 2 and sub.module in (None, 'paths')
            assert ok, f'相对 import 仅 ..paths 允许：{sub.module}'
    # 源级哨兵：任何 server / cli 引用（含函数内延迟 import）都不允许
    assert 'materialsorting.web.server' not in src
    assert 'materialsorting.cli' not in src
    assert 'from .server' not in src


# ------------------------------------------------------------- paths 常量

def test_license_dir_under_out_dir():
    """LICENSE_DIR = OUT_DIR/license（frozen 态 launcher 重定向 MS_OUT_DIR 后随之
    落 %LOCALAPPDATA%/MaterialSorting/out/license/）。"""
    assert paths_mod.LICENSE_DIR == os.path.join(paths_mod.OUT_DIR, 'license')


# ------------------------------------------------------------- key_state 本地状态

def test_key_state_save_load_roundtrip(license_dir):
    """原子写（tmp+rename）+ 重启可读（load 从盘上重新解析）。"""
    keygate.save_key_state('MS-AAAAA-BBBBB-CCCCC')
    assert license_dir.joinpath('key_state.json').exists()
    assert keygate.load_key_state() == {'key': 'MS-AAAAA-BBBBB-CCCCC'}
    assert not list(license_dir.glob('*.tmp')), '原子写不得留 tmp 残屑'


def test_key_state_overwrite_and_json_shape(license_dir):
    """重复保存覆盖（换 key 生效）；落盘 JSON 形态可被人读改。"""
    keygate.save_key_state('MS-AAAAA-BBBBB-CCCCC')
    keygate.save_key_state('MS-DDDDD-EEEEE-FFFFF')
    assert keygate.load_key_state() == {'key': 'MS-DDDDD-EEEEE-FFFFF'}
    raw = json.loads(license_dir.joinpath('key_state.json').read_text('utf-8'))
    assert raw == {'key': 'MS-DDDDD-EEEEE-FFFFF'}


def test_key_state_load_tolerant(license_dir):
    """缺失 / 损坏 / 非对象 JSON → 空 dict（视为未绑定，fail-closed 由闸门接管）。"""
    assert keygate.load_key_state() == {}
    license_dir.mkdir(parents=True, exist_ok=True)
    keygate.key_state_path().write_text('{broken', encoding='utf-8')
    assert keygate.load_key_state() == {}
    keygate.key_state_path().write_text('[1, 2]', encoding='utf-8')
    assert keygate.load_key_state() == {}


# ------------------------------------------------------------- 机器身份

def test_machine_guid_registry_priority(license_dir, monkeypatch):
    """注册表可读 → 直接用其值，不落兜底文件。"""
    monkeypatch.setattr(keygate, '_read_registry_guid', lambda: 'reg-guid-42')
    assert keygate.machine_guid() == 'reg-guid-42'
    assert not license_dir.joinpath('machine_id.txt').exists()


def test_machine_guid_fallback_stable(license_dir, monkeypatch):
    """注册表不可读 → machine_id.txt 首铸 uuid4，此后恒读同值（稳定机器身份：
    每次铸新值会把本机变「他机」致绑定失效）。"""
    monkeypatch.setattr(keygate, '_read_registry_guid', lambda: None)
    first = keygate.machine_guid()
    second = keygate.machine_guid()
    assert first == second and first
    uuid.UUID(first)   # 铸的是 uuid4
    text = license_dir.joinpath('machine_id.txt').read_text('utf-8').strip()
    assert text == first


@pytest.mark.skipif(sys.platform != 'win32' or keygate.winreg is None,
                    reason='真机注册表读取仅 Windows 可验')
def test_machine_guid_real_registry_read():
    """AC：machine_guid() Windows 注册表读取成功（真机 HKLM MachineGuid）。"""
    assert keygate._read_registry_guid()


# ------------------------------------------------------------- URL 解析链

def test_url_chain_env(no_server_url, monkeypatch):
    monkeypatch.setenv('MS_KEY_SERVER_URL', '  http://ks.example.com:8110/  ')
    assert keygate.resolve_key_server_url() == 'http://ks.example.com:8110/'


def test_url_chain_env_empty_is_absent(no_server_url, monkeypatch):
    """空串 env 视为未配置（不与 sidecar 抢档）。"""
    monkeypatch.setenv('MS_KEY_SERVER_URL', '   ')
    assert keygate.resolve_key_server_url() is None


def test_url_chain_frozen_sidecar(no_server_url, tmp_path, monkeypatch):
    """frozen 态 exe 旁 key_server_url.txt 生效（zip 解压部署免设 env）。"""
    exe = tmp_path / 'MaterialSorting.exe'
    exe.write_bytes(b'MZ')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(exe))
    (tmp_path / 'key_server_url.txt').write_text(
        'http://127.0.0.1:8110\n', encoding='utf-8')
    assert keygate.resolve_key_server_url() == 'http://127.0.0.1:8110'


def test_url_chain_frozen_sidecar_missing(no_server_url, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    assert keygate.resolve_key_server_url() is None


def test_url_chain_dev_ignores_sidecar(no_server_url, tmp_path, monkeypatch):
    """dev（未冻结）不读 sidecar —— repo 内该文件是部署配置不是开发配置。"""
    assert not hasattr(sys, 'frozen') or not sys.frozen
    (tmp_path / 'key_server_url.txt').write_text('http://x', encoding='utf-8')
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'python.exe'))
    assert keygate.resolve_key_server_url() is None


# ------------------------------------------------- describe_*（--check 回显，US-009）

def test_describe_url_three_tiers(no_server_url, tmp_path, monkeypatch):
    """describe_key_server_url 三档描述与 resolve 同一真相源（US-009 --check 回显）。"""
    # 档一 env：URL + 来源标注
    monkeypatch.setenv('MS_KEY_SERVER_URL', 'http://ks.example.com:8110')
    text = keygate.describe_key_server_url()
    assert 'http://ks.example.com:8110' in text and 'MS_KEY_SERVER_URL env' in text
    # 档二 frozen sidecar：strip 后 env 为空 → 来源标注 sidecar
    monkeypatch.delenv('MS_KEY_SERVER_URL')
    exe = tmp_path / 'app.exe'
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(exe))
    (tmp_path / 'key_server_url.txt').write_text(
        'http://127.0.0.1:8110', encoding='utf-8')
    text = keygate.describe_key_server_url()
    assert 'http://127.0.0.1:8110' in text and 'key_server_url.txt' in text


def test_describe_url_unconfigured(no_server_url):
    """档三 皆无：fail-closed 描述（含两条配置路径指引）。"""
    text = keygate.describe_key_server_url()
    assert '未配置' in text and 'MS_KEY_SERVER_URL' in text \
        and 'key_server_url.txt' in text


def test_describe_machine_guid_registry_ok(monkeypatch):
    monkeypatch.setattr(keygate, '_read_registry_guid', lambda: '55223278-1234-5678')
    text = keygate.describe_machine_guid()
    assert '注册表' in text and '55223278' in text


def test_describe_machine_guid_no_mint(license_dir, monkeypatch):
    """注册表不可读：仅描述兜底行为，**不铸 machine_id.txt**（--check 无副作用）。"""
    monkeypatch.setattr(keygate, '_read_registry_guid', lambda: None)
    text = keygate.describe_machine_guid()
    assert 'machine_id.txt' in text
    assert not license_dir.exists() or not license_dir.joinpath(
        'machine_id.txt').exists()


# ------------------------------------------------- client token 链（US-009）

def test_client_token_env(no_server_url, monkeypatch):
    """档一 env：strip 后非空即用。"""
    monkeypatch.delenv('MS_KEY_CLIENT_TOKEN', raising=False)
    monkeypatch.setenv('MS_KEY_CLIENT_TOKEN', '  tok-42  ')
    assert keygate.resolve_client_token() == 'tok-42'


def test_client_token_frozen_sidecar(no_server_url, tmp_path, monkeypatch):
    """档二 frozen exe 旁 key_client_token.txt；空文件 = 未配置；dev 不读。"""
    monkeypatch.delenv('MS_KEY_CLIENT_TOKEN', raising=False)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'app.exe'))
    (tmp_path / 'key_client_token.txt').write_text('tok-side\n', encoding='utf-8')
    assert keygate.resolve_client_token() == 'tok-side'
    (tmp_path / 'key_client_token.txt').write_text('   \n', encoding='utf-8')
    assert keygate.resolve_client_token() is None
    monkeypatch.delattr(sys, 'frozen', raising=False)
    (tmp_path / 'key_client_token.txt').write_text('tok-side', encoding='utf-8')
    assert keygate.resolve_client_token() is None, 'dev 态不读 sidecar'


def test_key_post_sends_client_token_header(set_server_url, monkeypatch):
    """_key_post：已配置 token → 附 X-Client-Token；未配置 → 不带 header
    （keyserver 未设 token 时不影响，401 由 keyserver 兜底透传）。"""
    with _StubServer([(200, {'ok': True})]) as srv:
        set_server_url(srv.url)
        monkeypatch.delenv('MS_KEY_CLIENT_TOKEN', raising=False)
        keygate._key_post('/api/key/info', {'key': 'K'})
        assert srv.calls[-1]['token'] is None
        monkeypatch.setenv('MS_KEY_CLIENT_TOKEN', 'tok-42')
        keygate._key_post('/api/key/info', {'key': 'K'})
        assert srv.calls[-1]['token'] == 'tok-42'


def test_describe_client_token_no_value_leak(no_server_url, monkeypatch):
    """describe：已配置报来源不回显值；未配置报 401 影响。"""
    monkeypatch.delenv('MS_KEY_CLIENT_TOKEN', raising=False)
    assert '401' in keygate.describe_client_token()
    monkeypatch.setenv('MS_KEY_CLIENT_TOKEN', 'secret-tok-xyz')
    text = keygate.describe_client_token()
    assert '已配置' in text and 'MS_KEY_CLIENT_TOKEN env' in text
    assert 'secret-tok-xyz' not in text, 'token 值不得进日志'


# ------------------------------------------------------------- _key_post（真 HTTP）

def test_key_post_roundtrip_200(no_server_url, set_server_url):
    with _StubServer([(200, _INFO_OK)]) as srv:
        set_server_url(srv.url)
        out = keygate._key_post('/api/key/validate', {'key': 'K', 'deduct': False})
    assert out == _INFO_OK
    assert srv.calls[0]['path'] == '/api/key/validate'
    assert srv.calls[0]['body'] == {'key': 'K', 'deduct': False}


def test_key_post_4xx_error_passthrough(no_server_url, set_server_url):
    """keyserver 4xx 的中文 error 原样透传（errors.py 契约 —— 用户直接可读）。"""
    with _StubServer([(404, {'error': 'key 不存在：请检查输入是否正确'})]) as srv:
        set_server_url(srv.url)
        with pytest.raises(keygate.KeyGateError, match='key 不存在：请检查输入是否正确'):
            keygate._key_post('/api/key/bind', {})


def test_key_post_5xx_without_error_field(no_server_url, set_server_url):
    with _StubServer([(500, {'oops': 1})]) as srv:
        set_server_url(srv.url)
        with pytest.raises(keygate.KeyGateError, match='HTTP 500'):
            keygate._key_post('/api/key/info', {})


def test_key_post_non_json_body(no_server_url, set_server_url):
    with _StubServer([(200, b'<html>proxy</html>')]) as srv:
        set_server_url(srv.url)
        with pytest.raises(keygate.KeyGateError, match='非 JSON'):
            keygate._key_post('/api/key/info', {})


def test_key_post_url_unconfigured_fail_closed(no_server_url):
    with pytest.raises(keygate.KeyGateError, match=keygate.MSG_NO_SERVER):
        keygate._key_post('/api/key/validate', {})


def test_key_post_unreachable(no_server_url, set_server_url):
    """连接拒绝（关闭端口）→ fail-closed 统一文案。"""
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]            # bind 未 listen → 连接拒绝
    set_server_url(f'http://127.0.0.1:{port}')
    with pytest.raises(keygate.KeyGateError, match=keygate.MSG_UNREACHABLE):
        keygate._key_post('/api/key/validate', {})


def test_key_post_timeout_fail_closed(no_server_url, set_server_url):
    """超时（默认 5s 档以小 timeout 模拟）→ fail-closed 统一文案。"""
    with _StubServer([(200, _INFO_OK)], delay_s=1.0) as srv:
        set_server_url(srv.url)
        t0 = time.monotonic()
        with pytest.raises(keygate.KeyGateError, match=keygate.MSG_UNREACHABLE):
            keygate._key_post('/api/key/validate', {}, timeout=0.2)
        assert time.monotonic() - t0 < 0.9, '必须按 timeout 截断而非跑满服务端延迟'


def test_key_post_no_auto_retry(no_server_url, set_server_url):
    """无自动重试：失败恰发 1 个请求（deduct=true 响应丢失时服务端可能已扣次，
    重试会双扣 —— PRD 定案）。"""
    with _StubServer([(404, {'error': 'key 不存在：请检查输入是否正确'})]) as srv:
        set_server_url(srv.url)
        with pytest.raises(keygate.KeyGateError):
            keygate._key_post('/api/key/validate', {'deduct': True})
        assert len(srv.calls) == 1


def test_key_post_default_timeout_constant():
    """默认超时 = 5s（PRD 定案口径锁定）。"""
    assert keygate.KEY_HTTP_TIMEOUT_S == 5.0


# ------------------------------------------------------------- ensure_run_allowed

@pytest.fixture
def gate_env(license_dir, tmp_path, monkeypatch, no_server_url):
    """闸门测试基态：本地 key 可控 + 机器身份可控（样例豁免走 sample 标记参数，
    不再依赖 data/ 目录 —— 2026-09-29 收紧后闸门不读文件名）。"""
    monkeypatch.setattr(keygate, '_read_registry_guid', lambda: 'reg-guid-42')
    monkeypatch.delenv('MS_KEY_MODE', raising=False)
    return tmp_path


def test_gate_ms_key_mode_off_dev_only(gate_env, monkeypatch):
    """MS_KEY_MODE=off 且未冻结（dev）→ 全放行（不看样例/key）。"""
    monkeypatch.setenv('MS_KEY_MODE', 'off')
    assert not getattr(sys, 'frozen', False)
    assert keygate.ensure_run_allowed(None) == (True, 'off')
    assert keygate.ensure_run_allowed('任意上传.dxf') == (True, 'off')


def test_gate_ms_key_mode_off_ignored_when_frozen(gate_env, monkeypatch):
    """MS_KEY_MODE=off 在 frozen 态无效（冻结生产 exe 不可绕）→ 走后续判定。"""
    monkeypatch.setenv('MS_KEY_MODE', 'off')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert keygate.ensure_run_allowed('用户上传.dxf') == (False, keygate.MSG_NO_KEY)


def test_gate_sample_flag_exemption(gate_env):
    """样例标记豁免（2026-09-29 收紧）：``sample=True``（commit 期哈希对拍铸成
    的 doc 标记透传）→ 免 key 放行，与 doc_source 文件名无关。"""
    assert keygate.ensure_run_allowed('样例M1787.dxf', sample=True) == (True, 'sample')
    assert keygate.ensure_run_allowed('任意上传.dxf', sample=True) == (True, 'sample')


def test_gate_sample_filename_no_longer_exempts(gate_env):
    """旧口径回归锁：doc.source 命中 data/ 白名单样式的文件名**不再豁免**（data/
    放的是真实生产母版，按名豁免 = 客户直传工厂原名母版永久免 key）。"""
    assert keygate.ensure_run_allowed('样例M1787.dxf') == (False, keygate.MSG_NO_KEY)
    assert keygate.ensure_run_allowed('M1787#直筒14%7%大货围加9.dxf') == \
        (False, keygate.MSG_NO_KEY)


def test_gate_non_sample_no_key(gate_env):
    """非样例 + 本地无 key → 中文指路文案（原文锁定）。"""
    assert keygate.ensure_run_allowed('用户上传.dxf') == (False, keygate.MSG_NO_KEY)
    assert keygate.MSG_NO_KEY == '未绑定授权 key：请在「当前系统 key 属性」中输入并保存'


def test_gate_validate_ok_deducts(gate_env, set_server_url):
    """绑定 key + keyserver validate 200 → 放行；载荷 deduct=True 且带本机身份。"""
    keygate.save_key_state('MS-AAAAA-BBBBB-CCCCC')
    with _StubServer([(200, _INFO_OK)]) as srv:
        set_server_url(srv.url)
        ok, msg = keygate.ensure_run_allowed('用户上传.dxf')
    assert (ok, msg) == (True, '')
    assert srv.calls[-1]['body'] == {'key': 'MS-AAAAA-BBBBB-CCCCC',
                                     'machine_guid': 'reg-guid-42', 'deduct': True}


def test_gate_validate_reject_passthrough(gate_env, set_server_url):
    """validate 4xx（次数用完）→ (False, keyserver 中文文案透传)。"""
    keygate.save_key_state('MS-AAAAA-BBBBB-CCCCC')
    with _StubServer([(403, {'error': '授权次数已用完（共 3 次）'})]) as srv:
        set_server_url(srv.url)
        assert keygate.ensure_run_allowed('用户上传.dxf') == \
            (False, '授权次数已用完（共 3 次）')


def test_gate_key_present_but_no_url(gate_env):
    """key 在场 + URL 皆无 → fail-closed（授权服务器未配置）。"""
    keygate.save_key_state('MS-AAAAA-BBBBB-CCCCC')
    assert keygate.ensure_run_allowed('用户上传.dxf') == (False, keygate.MSG_NO_SERVER)


def test_gate_key_present_unreachable(gate_env, set_server_url):
    keygate.save_key_state('MS-AAAAA-BBBBB-CCCCC')
    set_server_url('http://127.0.0.1:9')   # 不可达
    assert keygate.ensure_run_allowed('用户上传.dxf') == (False, keygate.MSG_UNREACHABLE)


def test_gate_corrupt_key_state_treated_as_unbound(gate_env):
    """损坏 key_state.json → 视为未绑定（不向 keyserver 发请求）。"""
    license_path = keygate.key_state_path()
    license_path.parent.mkdir(parents=True, exist_ok=True)
    license_path.write_text('{broken', encoding='utf-8')
    assert keygate.ensure_run_allowed('用户上传.dxf') == (False, keygate.MSG_NO_KEY)


# ------------------------------------------------------------- 子进程冒烟

def test_module_smoke_subprocess():
    """AC：``python -m materialsorting.web.keygate`` 合成夹具冒烟 exit 0。"""
    env = {**os.environ, 'PYTHONPATH': str(_SRC)}
    env.pop('MS_KEY_MODE', None)
    env.pop('MS_KEY_SERVER_URL', None)
    result = subprocess.run(
        [sys.executable, '-m', 'materialsorting.web.keygate'],
        capture_output=True, env=env, timeout=120,
        cwd=str(_SRC.parent))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'FAIL' not in result.stdout.decode('utf-8', 'replace')

