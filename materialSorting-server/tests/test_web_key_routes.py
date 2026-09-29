"""US-005 三入口后端闸门与双豁免 + /api/key/* 四端点测试。

覆盖（prd-key-authorization-system US-005 验收标准）：
1. 四端点契约（TestClient + keyserver 桩 _StubServer 真实 HTTP 往返）：state
   （未绑定三 null / info 透传 / keyserver 失败也 200 带 error / **key 已删
   404 → 自动解绑清盘 + 解释文案 / 5xx 瞬态不解绑** / 无会话闸门
   —— 随机 X-Session-Id 不拦）、save（形状 400 / bind 成功才落盘 / bind 失败
   不覆盖旧 key / 载荷 system_name+machine_guid）、merge（无本地 key 400 /
   source_keys 形状 400 / target=本地 key / keyserver 原样透传）、precheck
   （ok/message 契约 / validate deduct=False / 样例与 off 豁免）；
2. WS 闸门：未绑 key → key_blocked 帧 + 显式 close + 不建求解子进程；绑定有效
   key（桩 validate 200）→ 放行 manifest/final（deduct=True 断言）；样例母版免闸；
3. strategy/extreme 闸门：未绑 key → 403 中文且不 cleanup / 不 spawn / 不写 cfg
   （上一轮 run 产物仍在）；载荷校验先于闸门（400 优先 403）；样例豁免与绑定
   有效 key → 202（validate deduct=True 恰一次 = 扣次唯一锚点）；
4. 机器族豁免回归锁：monkeypatch keygate 抛异常时 /api/machine/solve 仍 202；
5. AST 分层守卫：routes_key 禁 import server / strategy / routes_ws / cli。

既有用例零改动经 conftest autouse ``MS_KEY_MODE=off``（dev 逃生口）放行 ——
本文件用例经 ``key_on`` fixture ``delenv`` 恢复真实判定。
"""
from __future__ import annotations

import ast
import http.server
import json
import os
import sys
import threading
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.web import keygate
from materialsorting.web import routes_ws as routes_ws_mod
from materialsorting.web import server as server_mod
from materialsorting.web import strategy as strategy_mod
from materialsorting.web.server import app


# ------------------------------------------------------------- 测试基础设施

_INFO_OK = {'type': 'count', 'total_uses': 10, 'used_uses': 2, 'remaining_uses': 8,
            'status': '正在使用', 'bound_system_name': '测试机', 'remark': '测试机'}

_SAMPLE_DXF = 'M1787样例.dxf'


class _StubServer:
    """本地 keyserver 桩（真 HTTP 往返）：记录请求、按脚本回包。

    ``script`` 是 ``[(status, body_dict), ...]`` 按序消费（耗尽后重复末条）；
    请求体全部落 ``calls`` 供载荷断言（path / key / machine_guid / deduct）。
    镜像 test_web_keygate._StubServer 写法（跨测试文件不 import，独立持有）。
    """

    def __init__(self, script):
        self.script = script
        self.calls: list[dict] = []
        outer = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):               # noqa: N802 - http.server 约定
                body = json.loads(
                    self.rfile.read(int(self.headers['Content-Length'])))
                outer.calls.append({'path': self.path, 'body': body})
                status, payload = (outer.script[len(outer.calls) - 1]
                                   if len(outer.calls) <= len(outer.script)
                                   else outer.script[-1])
                data = json.dumps(payload).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):    # 静默测试日志
                pass

        self._srv = http.server.HTTPServer(('127.0.0.1', 0), _Handler)

    @property
    def url(self) -> str:
        return f'http://127.0.0.1:{self._srv.server_address[1]}'

    def start(self) -> '_StubServer':
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self._srv.shutdown()
        self._srv.server_close()


class FakeProc:
    """Popen 替身：poll() 返回预置 rc（None = 存活）。"""

    def __init__(self, pid: int = 4321, rc=None):
        self.pid = pid
        self._rc = rc

    def poll(self):
        return self._rc


def _set_url(url: str) -> None:
    """设 keyserver URL（key_on fixture 域内即设即清，用例 finally pop）。"""
    os.environ['MS_KEY_SERVER_URL'] = url


def _client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def license_dir(tmp_path, monkeypatch):
    """LICENSE_DIR 重定向到 tmp（keygate 调用时取 paths.LICENSE_DIR 模块属性）。"""
    target = tmp_path / 'license'
    monkeypatch.setattr(paths_mod, 'LICENSE_DIR', str(target))
    return target


@pytest.fixture
def key_on(monkeypatch, license_dir):
    """恢复真实闸门判定：conftest autouse 的 MS_KEY_MODE=off 移除 + keyserver
    URL 归零 + 未冻结（无本地 key 起点；keyserver URL 由用例/桩自行设置）。"""
    monkeypatch.delenv('MS_KEY_MODE', raising=False)
    monkeypatch.delenv('MS_KEY_SERVER_URL', raising=False)
    monkeypatch.delattr(sys, 'frozen', raising=False)
    return license_dir


@pytest.fixture
def sample_data(tmp_path, monkeypatch):
    """样例声明验证夹具（2026-09-29 改造）：DATA_DIR 指到 tmp 且含一枚真实字节
    的样例 .dxf —— 供 commit ``sample_name`` 声明 sha256 对拍用（闸门侧不再按
    文件名豁免，此夹具只喂哈希对拍路径）。"""
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    (data_dir / _SAMPLE_DXF).write_bytes(b'sample-master-bytes')
    monkeypatch.setattr(paths_mod, 'DATA_DIR', str(data_dir))
    return data_dir


def _bind_key(license_dir, key='MS-TEST-KEY00-00001') -> str:
    """直接落 key_state.json（绕过 save 端点，隔离单测关注点）。"""
    keygate.save_key_state(key)
    return key


# ------------------------------------------------------------- AST 分层守卫

def test_routes_key_layering_guard():
    """routes_key 禁 import server / strategy / routes_ws / cli（被 server 文件尾
    注册 —— import server 即成环；strategy/routes_ws 是闸门消费者不该被反向引用）。
    ``.sessions`` 放行（2026-09-29 precheck 会话 doc peek：纯标准库兄弟模块，
    precheck 数据源偏好，非会话闸门）。"""
    from materialsorting.web import routes_key
    src = Path(routes_key.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert not mod.startswith('materialsorting.web.server')
            assert not mod.startswith('materialsorting.web.strategy')
            assert not mod.startswith('materialsorting.web.routes_ws')
            assert not mod.startswith('materialsorting.cli')
            if node.level:
                assert mod in ('', 'keygate', 'sessions'), \
                    f'相对 import 仅 .keygate / .sessions 允许：{mod}'
    assert 'from .server' not in src
    assert 'import server' not in src


# ------------------------------------------------------------- GET /api/key/state

def test_key_state_unbound_three_nulls(key_on):
    """未绑定 → {key:null, info:null, error:null}，不打 keyserver。"""
    r = _client().get('/api/key/state')
    assert r.status_code == 200
    assert r.json() == {'key': None, 'info': None, 'error': None}


def test_key_state_bound_info_passthrough(key_on):
    """已绑定 → keyserver info 原样透传；载荷 {key, machine_guid} 打到 /api/key/info。"""
    key = _bind_key(key_on)
    stub = _StubServer([(200, _INFO_OK)]).start()
    try:
        _set_url(stub.url)
        r = _client().get('/api/key/state')
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 200
    body = r.json()
    assert body['key'] == key
    assert body['error'] is None
    assert body['info'] == _INFO_OK
    assert stub.calls[0]['path'] == '/api/key/info'
    posted = stub.calls[0]['body']
    assert posted['key'] == key
    assert isinstance(posted['machine_guid'], str) and posted['machine_guid']


def test_key_state_keyserver_down_still_200_with_error(key_on):
    """keyserver 查询失败也 200：error 带 fail-closed 文案（key 仍回显）。"""
    key = _bind_key(key_on)
    _set_url('http://127.0.0.1:1')          # 不可达端口
    try:
        r = _client().get('/api/key/state')
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
    assert r.status_code == 200
    body = r.json()
    assert body['key'] == key
    assert body['info'] is None
    assert body['error'] == keygate.MSG_UNREACHABLE


def test_key_state_keyserver_4xx_transparent(key_on):
    """keyserver 403（绑定他机）→ 200 + error 中文透传。"""
    _bind_key(key_on)
    stub = _StubServer([(403, {'error': '该 key 已绑定其他系统，无法绑定到本机'})]).start()
    try:
        _set_url(stub.url)
        r = _client().get('/api/key/state')
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 200
    assert r.json()['error'] == '该 key 已绑定其他系统，无法绑定到本机'


def test_key_state_key_deleted_autounbind(key_on):
    """key 已在 keyserver 侧删除（404）→ 自动解绑：key_state.json 清掉 +
    未绑定态响应（error 带解释上屏）。"""
    _bind_key(key_on)
    stub = _StubServer([(404, {'error': 'key 不存在：请检查输入是否正确'})]).start()
    try:
        _set_url(stub.url)
        r = _client().get('/api/key/state')
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 200
    body = r.json()
    assert body['key'] is None and body['info'] is None
    assert '自动解除绑定' in body['error']
    assert keygate.load_key_state() == {}          # 本地绑定已清


def test_key_state_5xx_transient_no_autounbind(key_on):
    """keyserver 5xx（瞬态）→ 不解绑：本地 key 保留等重试（误清是灾难）。"""
    _bind_key(key_on)
    stub = _StubServer([(500, {'error': '服务器内部错误'})]).start()
    try:
        _set_url(stub.url)
        r = _client().get('/api/key/state')
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 200
    body = r.json()
    assert body['key'] is not None                # key 仍回显
    assert body['error'] == '服务器内部错误'
    assert keygate.load_key_state().get('key') == body['key']   # 未清盘


def test_key_state_no_session_gate(key_on):
    """机器级全局：随机 X-Session-Id 头不拦（与 /api/edit-hold 的 sid 闸门差异）。"""
    r = _client().get('/api/key/state', headers={'X-Session-Id': 'nosuchsid123'})
    assert r.status_code == 200
    assert r.json()['key'] is None


# ------------------------------------------------------------- POST /api/key/save

@pytest.mark.parametrize('body', [
    {}, {'key': ''}, {'key': '   '}, {'key': 123},
])
def test_key_save_shape_400(key_on, body):
    """key 缺失 / 空 / 非字符串 → 400 中文（keyserver 不被打）。"""
    r = _client().post('/api/key/save', json=body)
    assert r.status_code == 400
    assert 'key' in r.json()['error']


def test_key_save_bad_body_400(key_on):
    """非 JSON 请求体 → 400（请求体须为 JSON）。"""
    r = _client().post('/api/key/save', content=b'not-json',
                       headers={'Content-Type': 'application/json'})
    assert r.status_code == 400
    assert 'JSON' in r.json()['error']


def test_key_save_bind_ok_persists(key_on):
    """bind 成功 → key_state.json 落盘 + 响应 info；载荷带 system_name（hostname）。"""
    import socket
    stub = _StubServer([(200, _INFO_OK)]).start()
    try:
        _set_url(stub.url)
        r = _client().post('/api/key/save', json={'key': ' MS-NEWS-KEY00-0009 '})
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 200
    body = r.json()
    assert body['saved'] is True
    assert body['key'] == 'MS-NEWS-KEY00-0009'          # strip 后落盘
    assert body['info'] == _INFO_OK
    assert keygate.load_key_state() == {'key': 'MS-NEWS-KEY00-0009'}
    posted = stub.calls[0]['body']
    assert posted['key'] == 'MS-NEWS-KEY00-0009'
    assert posted['system_name'] == socket.gethostname()
    assert isinstance(posted['machine_guid'], str) and posted['machine_guid']


def test_key_save_bind_fail_keeps_old_key(key_on):
    """bind 失败（key 不存在）→ 400 中文透传，旧 key 原样保留（不覆盖）。"""
    _bind_key(key_on, 'MS-OLD00-KEY00-0000X')
    stub = _StubServer([(404, {'error': 'key 不存在：请检查输入是否正确'})]).start()
    try:
        _set_url(stub.url)
        r = _client().post('/api/key/save', json={'key': 'MS-BAD00-KEY00-0000X'})
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 400
    assert r.json()['error'] == 'key 不存在：请检查输入是否正确'
    assert keygate.load_key_state() == {'key': 'MS-OLD00-KEY00-0000X'}


def test_key_save_unreachable_400(key_on):
    """keyserver 不可达 → 400 fail-closed 文案，不落盘。"""
    _set_url('http://127.0.0.1:1')
    try:
        r = _client().post('/api/key/save', json={'key': 'MS-ANY00-KEY00-0000X'})
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
    assert r.status_code == 400
    assert r.json()['error'] == keygate.MSG_UNREACHABLE
    assert keygate.load_key_state() == {}


# ------------------------------------------------------------- POST /api/key/merge

@pytest.mark.parametrize('body', [
    {}, {'source_keys': None}, {'source_keys': []},
    {'source_keys': 'MS-X'}, {'source_keys': ['ok', 123]},
])
def test_key_merge_shape_400(key_on, body):
    """source_keys 缺失 / 非列表 / 空 / 非字符串成员 → 400。"""
    r = _client().post('/api/key/merge', json=body)
    assert r.status_code == 400
    assert 'source_keys' in r.json()['error']


def test_key_merge_no_local_key_400(key_on):
    """未绑定本地 key → 400 指路文案（keyserver 不被打）。"""
    stub = _StubServer([(200, {})]).start()
    try:
        _set_url(stub.url)
        r = _client().post('/api/key/merge',
                           json={'source_keys': ['MS-SRC0-KEY00-0000X']})
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 400
    assert r.json()['error'] == keygate.MSG_NO_KEY
    assert stub.calls == []


def test_key_merge_ok_passthrough(key_on):
    """target = 本地当前 key；keyserver 原子合并响应原样透传（sources 明细在内）。"""
    key = _bind_key(key_on)
    merge_resp = {'target': _INFO_OK,
                  'sources': [{'key': 'MS-SRC0-KEY00-0000X', 'transferred_days': 10.5},
                              {'key': 'MS-SRC1-KEY00-0000X', 'transferred_days': 14.5}],
                  'total_transferred_days': 25.0}
    stub = _StubServer([(200, merge_resp)]).start()
    try:
        _set_url(stub.url)
        r = _client().post(
            '/api/key/merge',
            json={'source_keys': [' MS-SRC0-KEY00-0000X',
                                  'MS-SRC1-KEY00-0000X',
                                  'MS-SRC0-KEY00-0000X']})
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 200
    assert r.json() == merge_resp
    posted = stub.calls[0]['body']
    assert posted['target_key'] == key
    # strip 后原样上送（去重保序在 keyserver service 层）
    assert posted['source_keys'] == ['MS-SRC0-KEY00-0000X',
                                     'MS-SRC1-KEY00-0000X',
                                     'MS-SRC0-KEY00-0000X']
    assert isinstance(posted['machine_guid'], str) and posted['machine_guid']


def test_key_merge_keyserver_error_400(key_on):
    """keyserver 400（source 无效）→ 400 中文透传（整体失败无部分合并）。"""
    _bind_key(key_on)
    stub = _StubServer([
        (400, {'error': 'key `MS-SRC0-KEY00-0000X` 不是时长型或未绑定本机，无法合并'})]).start()
    try:
        _set_url(stub.url)
        r = _client().post('/api/key/merge',
                           json={'source_keys': ['MS-SRC0-KEY00-0000X']})
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 400
    assert '无法合并' in r.json()['error']


# ------------------------------------------------------------- POST /api/key/precheck

def test_precheck_no_key_message(key_on):
    """未绑定 → {ok:false, message:指路文案}。"""
    r = _client().post('/api/key/precheck', json={})
    assert r.status_code == 200
    assert r.json() == {'ok': False, 'message': keygate.MSG_NO_KEY}


def test_precheck_valid_key_deduct_false(key_on):
    """绑定有效 key → ok:true；validate 载荷 deduct 恒 False（预检不动账）。"""
    key = _bind_key(key_on)
    stub = _StubServer([(200, _INFO_OK)]).start()
    try:
        _set_url(stub.url)
        r = _client().post('/api/key/precheck', json={'doc_source': 'user.dxf'})
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 200
    assert r.json() == {'ok': True}
    posted = stub.calls[0]['body']
    assert posted['key'] == key
    assert posted['deduct'] is False
    assert isinstance(posted['machine_guid'], str) and posted['machine_guid']


def test_precheck_keyserver_403_message(key_on):
    """keyserver 403（次数用完）→ ok:false + 中文 message（前端 toast 直接消费）。"""
    _bind_key(key_on)
    stub = _StubServer([(403, {'error': '授权次数已用完（共 10 次）'})]).start()
    try:
        _set_url(stub.url)
        r = _client().post('/api/key/precheck', json={})
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.json() == {'ok': False, 'message': '授权次数已用完（共 10 次）'}


def test_precheck_unreachable_message(key_on):
    """断网 → ok:false +「无法连接授权服务器」（后端映射，前端不自行判断网络）。"""
    _bind_key(key_on)
    _set_url('http://127.0.0.1:1')
    try:
        r = _client().post('/api/key/precheck', json={})
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
    assert r.json() == {'ok': False, 'message': keygate.MSG_UNREACHABLE}


def test_precheck_sample_exemption(key_on):
    """会话 doc 带样例标记（commit 期哈希对拍铸成）→ 免 key 放行（reason=sample，
    keyserver 不被打）。precheck 经 X-Session-Id/default 会话读 doc —— 与 WS 闸门
    同数据源（2026-09-29 收紧：不再按 body 文件名判豁免）。"""
    state, saved = _inject_ws_state(source=_SAMPLE_DXF, sample=_SAMPLE_DXF)
    stub = _StubServer([(200, _INFO_OK)]).start()
    try:
        _set_url(stub.url)
        r = _client().post('/api/key/precheck', json={})
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
        _restore_ws_state(state, saved)
    assert r.status_code == 200
    assert r.json() == {'ok': True, 'reason': 'sample'}
    assert stub.calls == []


def test_precheck_filename_alone_not_exempt(key_on):
    """收紧回归锁：body doc_source 撞 data/ 白名单样式文件名（无会话标记）→
    不豁免、未绑 key 即拦（直传工厂原名生产母版不得免 key）。"""
    stub = _StubServer([(200, _INFO_OK)]).start()
    try:
        _set_url(stub.url)
        r = _client().post('/api/key/precheck',
                           json={'doc_source': _SAMPLE_DXF},
                           headers={'X-Session-Id': 'nosuchsid123'})
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.json() == {'ok': False, 'message': keygate.MSG_NO_KEY}
    assert stub.calls == []


def test_precheck_off_mode(monkeypatch, key_on):
    """MS_KEY_MODE=off（dev 逃生口）→ ok:true（reason=off）。"""
    monkeypatch.setenv('MS_KEY_MODE', 'off')
    r = _client().post('/api/key/precheck', json={'doc_source': 'user.dxf'})
    assert r.json() == {'ok': True, 'reason': 'off'}


# ------------------------------------------------------------- WS 闸门

def _ws_pieces():
    """合成 2 片（schema v2 最小字段面，conftest _synthetic_pieces 同构）。"""
    return [
        {'pid': 'g01_28', 'label': 'g01', 'size': 28,
         'polygon': [[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]],
         'bbox': [0.0, 0.0, 500.0, 800.0], 'area_mm2': 400000.0, 'n_verts': 4,
         'allowed_angles': [0, 180],
         'net_polygon': [], 'internal_lines': [], 'notches': [],
         'grain_line': None},
        {'pid': 'g02_28', 'label': 'g02', 'size': 28,
         'polygon': [[0.0, 0.0], [300.0, 0.0], [300.0, 400.0], [0.0, 400.0]],
         'bbox': [0.0, 0.0, 300.0, 400.0], 'area_mm2': 120000.0, 'n_verts': 4,
         'allowed_angles': [0, 180],
         'net_polygon': [], 'internal_lines': [], 'notches': [],
         'grain_line': None},
    ]


def _inject_ws_state(source='user.dxf', sample=None):
    """注入合成 pieces state（_PIECES_STATE 原位 clear+update，返回恢复句柄）。
    ``sample`` = doc['sample'] 样例豁免标记（None = 无标记，str = 样例名）。"""
    pieces = _ws_pieces()
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update({'doc': {'source': source, 'sample': sample}, 'gate_mm': 1980.0,
                  'pieces': pieces,
                  'pieces_by_id': {p['pid']: p for p in pieces}})
    return state, saved


def _restore_ws_state(state, saved):
    state.clear()
    state.update(saved)


def _fake_solve_factory(calls):
    """solve_with_callback_proc 替身：manifest/final 即回（闸门接线测试不跑真
    求解 —— 真求解回归由既有 WS 用例承担）。on_process 交给 terminate 兼容的
    假 proc（is_alive 恒 False → finally terminate no-op）。"""

    class _Proc:
        pid = 9999

        def is_alive(self):
            return False

        def terminate(self):
            pass

        def join(self, timeout=None):
            pass

        def kill(self):
            pass

    def fake(pieces, gate_mm, params, *, on_manifest=None, on_report=None,
             on_process=None, on_stage=None, band=None, prefix=None):
        calls.append({'n_pieces': len(pieces), 'band': band, 'prefix': prefix})
        if on_process is not None:
            on_process(_Proc())
        if on_manifest is not None:
            on_manifest({
                'total_area': 520000.0, 'n_eroded': 0,
                'pid_meta': {
                    p['pid']: {'size': p['size'], 'color': '#ffffff',
                               'area_mm2': p['area_mm2'],
                               'polygon': p['polygon']}
                    for p in pieces}})
        return (None, {'density': 0.5, 'density_sparrow': 0.55,
                       'width_mm': 5000.0}, 0.1, None)

    return fake


def _ws_start_msg():
    """最小合法 WS start payload（band/prefix 缺席 = 旧行为）。"""
    return {'action': 'start', 'sizes': [], 'time': 60, 'seed': 1,
            'params': None, 'per_type': None, 'quantities': None}


def test_ws_gate_blocked_no_subprocess(key_on, monkeypatch):
    """未绑 key → key_blocked 帧 + 显式 close + 不建求解子进程。"""
    state, saved = _inject_ws_state()
    solve_calls = []
    monkeypatch.setattr(routes_ws_mod, 'solve_with_callback_proc',
                        _fake_solve_factory(solve_calls))
    try:
        with _client() as client:
            with client.websocket_connect('/ws/solve') as ws:
                ws.send_json(_ws_start_msg())
                msg = ws.receive_json()
                assert msg['type'] == 'error'
                assert msg['code'] == 'key_blocked'
                assert msg['message'] == keygate.MSG_NO_KEY
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()      # 显式 close（band 早退同款）
    finally:
        _restore_ws_state(state, saved)
    assert solve_calls == []


def test_ws_gate_valid_key_passes_and_deducts(key_on, monkeypatch):
    """绑定有效 key → 闸门放行（manifest/final 正常），validate deduct=True。"""
    _bind_key(key_on)
    state, saved = _inject_ws_state()
    solve_calls = []
    monkeypatch.setattr(routes_ws_mod, 'solve_with_callback_proc',
                        _fake_solve_factory(solve_calls))
    stub = _StubServer([(200, _INFO_OK)]).start()
    try:
        _set_url(stub.url)
        with _client() as client:
            with client.websocket_connect('/ws/solve') as ws:
                ws.send_json(_ws_start_msg())
                m1 = ws.receive_json()
                m2 = ws.receive_json()
        assert 'manifest' in {m1['type'], m2['type']}
        assert 'final' in {m1['type'], m2['type']}
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
        _restore_ws_state(state, saved)
    assert len(solve_calls) == 1
    assert stub.calls[0]['path'] == '/api/key/validate'
    assert stub.calls[0]['body']['deduct'] is True


def test_ws_gate_sample_exempt(key_on, monkeypatch):
    """样例标记母版（doc.sample 在案 = 经「样例」入口加载）→ 免 key 免 keyserver
    放行（2026-09-29 收紧：无标记的同名 source 不豁免，见 keygate 单测回归锁）。"""
    state, saved = _inject_ws_state(source=_SAMPLE_DXF, sample=_SAMPLE_DXF)
    solve_calls = []
    monkeypatch.setattr(routes_ws_mod, 'solve_with_callback_proc',
                        _fake_solve_factory(solve_calls))
    try:
        with _client() as client:
            with client.websocket_connect('/ws/solve') as ws:
                ws.send_json(_ws_start_msg())
                m1 = ws.receive_json()
                m2 = ws.receive_json()
        assert 'manifest' in {m1['type'], m2['type']}
    finally:
        _restore_ws_state(state, saved)
    assert len(solve_calls) == 1


# ------------------------------------------------------------- strategy/extreme 闸门

@pytest.fixture
def strat_key_env(tmp_path, monkeypatch, key_on):
    """strategy 闸门测试环境：隔离 CONFIG_RUNS_DIR / OUT_DIR / tempfile + 状态清零。"""
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(tmp_path / 'config_runs'))
    monkeypatch.setattr(paths_mod, 'OUT_DIR', str(tmp_path / 'out'))
    tmp_dir = tmp_path / 'tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(strategy_mod.tempfile, 'tempdir', str(tmp_dir))
    strategy_mod._STRATEGY_STATE.clear()
    strategy_mod._STRATEGY_STATES.clear()
    yield tmp_path
    strategy_mod._STRATEGY_STATE.clear()
    strategy_mod._STRATEGY_STATES.clear()


def _fake_state(source='user.dxf', sample=None):
    pieces = _ws_pieces()
    return {'doc': {'doc_id': 'deadbeef01', 'source': source, 'gate_mm': 1980.0,
                    'sample': sample},
            'gate_mm': 1980.0, 'pieces': pieces,
            'pieces_by_id': {p['pid']: p for p in pieces}}


def _strategy_start(client):
    return client.post('/api/strategy/start', json={'mode': 'race', 'minutes': 10})


def _extreme_start(client):
    return client.post('/api/extreme/start', json={'time_total_s': 1000})


def _spawn_capture(monkeypatch):
    calls = []

    def fake_spawn(cmd, stderr_path):
        calls.append(list(cmd))
        return FakeProc(pid=4321)

    monkeypatch.setattr(strategy_mod, '_spawn_run_process', fake_spawn)
    return calls


@pytest.mark.parametrize('starter', [_strategy_start, _extreme_start])
def test_strategy_gate_403_no_side_effects(strat_key_env, monkeypatch, starter):
    """未绑 key → 403 中文；不 cleanup / 不 spawn / 不写 cfg（上一轮产物仍在）。"""
    monkeypatch.setattr(strategy_mod, '_pieces_state', lambda: _fake_state())
    spawn_calls = _spawn_capture(monkeypatch)
    cleanup_calls = []
    monkeypatch.setattr(strategy_mod, '_cleanup_stale_web_artifacts',
                        lambda sid=None: cleanup_calls.append(sid))
    # 上一轮 run 产物（内存态空 + marker 无 → 单飞闸门放行，卡点落在 key 闸门）。
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / 'deadbeef01.dxf').write_bytes(b'x')   # 母版在盘（数据源校验先行）
    old_cfg = uploads / 'strategy_cfg_20250101-000000.json'
    old_cfg.write_text('{}', encoding='utf-8')
    old_run = Path(paths_mod.CONFIG_RUNS_DIR) / 'web_race_abc123_old'
    old_run.mkdir(parents=True)

    r = starter(_client())
    assert r.status_code == 403
    assert r.json()['error'] == keygate.MSG_NO_KEY
    assert spawn_calls == []                    # 不 spawn
    assert cleanup_calls == []                  # 不 cleanup
    new_cfgs = [p for p in uploads.glob('strategy_cfg_*.json') if p != old_cfg]
    assert new_cfgs == []                       # 不写 cfg
    assert old_cfg.exists() and old_run.exists()    # 上一轮产物原样保留


def test_strategy_gate_payload_validation_first(strat_key_env, monkeypatch):
    """载荷校验先于 key 闸门：坏 mode + 未绑 key → 400（不是 403）。"""
    monkeypatch.setattr(strategy_mod, '_pieces_state', lambda: _fake_state())
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / 'deadbeef01.dxf').write_bytes(b'x')
    r = _client().post('/api/strategy/start',
                       json={'mode': 'bogus', 'minutes': 10})
    assert r.status_code == 400
    assert 'mode' in r.json()['error']


def test_strategy_gate_sample_exempt_202(strat_key_env, monkeypatch):
    """样例标记母版（doc.sample 在案）→ 免 key 放行 202（spawn 照常；不打
    keyserver）。"""
    monkeypatch.setattr(strategy_mod, '_pieces_state',
                        lambda: _fake_state(source=_SAMPLE_DXF, sample=_SAMPLE_DXF))
    spawn_calls = _spawn_capture(monkeypatch)
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / 'deadbeef01.dxf').write_bytes(b'x')
    stub = _StubServer([(200, _INFO_OK)]).start()
    try:
        _set_url(stub.url)
        r = _strategy_start(_client())
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 202
    assert len(spawn_calls) == 1
    assert stub.calls == []                     # 样例豁免 = 零 keyserver 请求


@pytest.mark.parametrize('starter', [_strategy_start, _extreme_start])
def test_strategy_gate_valid_key_deducts_once(strat_key_env, monkeypatch, starter):
    """绑定有效 key → 202 + validate deduct=True 恰一次（扣次唯一锚点 = start）。"""
    _bind_key(strat_key_env)
    monkeypatch.setattr(strategy_mod, '_pieces_state', lambda: _fake_state())
    _spawn_capture(monkeypatch)
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / 'deadbeef01.dxf').write_bytes(b'x')
    stub = _StubServer([(200, _INFO_OK)]).start()
    try:
        _set_url(stub.url)
        r = starter(_client())
    finally:
        os.environ.pop('MS_KEY_SERVER_URL', None)
        stub.stop()
    assert r.status_code == 202
    validates = [c for c in stub.calls if c['path'] == '/api/key/validate']
    assert len(validates) == 1
    assert validates[0]['body']['deduct'] is True


# ------------------------------------------------------------- 机器族豁免回归锁

def _machine_master_bytes() -> bytes:
    """合成 machine solve 母版（R12 + POLYLINE_CLOSED，block 名 <名称>.<码号>）。"""
    import tempfile as _tf
    doc = ezdxf.new('R12')
    for name, (w, h) in [('blk a', (400, 700)), ('blk b', (300, 500))]:
        blk = doc.blocks.new(name=f'{name}.28')
        poly = blk.add_polyline2d(
            [(0, 0), (w, 0), (w, h), (0, h)], dxfattribs={'layer': '1'})
        poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
    fd, path = _tf.mkstemp(suffix='.dxf')
    os.close(fd)
    try:
        doc.saveas(path)
        with open(path, 'rb') as f:
            return f.read()
    finally:
        os.unlink(path)


def test_machine_solve_exempt_from_key_gate(tmp_path, monkeypatch, key_on):
    """机器族豁免回归锁：keygate 抛异常（闸门若被误接线会炸）machine_solve 仍 202。"""
    from materialsorting.web import machine as machine_mod
    from materialsorting.web import sessions as sessions_mod
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', uploads)
    monkeypatch.setattr(paths_mod, 'OUT_DIR', str(tmp_path / 'out'))
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(tmp_path / 'config_runs'))
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE',
                        str(tmp_path / 'mirror_intermediate.json'))
    tmp_dir = tmp_path / 'tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(strategy_mod.tempfile, 'tempdir', str(tmp_dir))
    strategy_mod._STRATEGY_STATE.clear()
    strategy_mod._STRATEGY_STATES.clear()
    machine_mod._DELETED_TASKS.clear()
    sessions_mod.registry.stop_scanner()
    sessions_mod.registry.reset()
    _spawn_capture(monkeypatch)

    def _explode(*args, **kwargs):
        raise AssertionError('machine_solve 不得触达 key 闸门')

    monkeypatch.setattr(keygate, 'ensure_run_allowed', _explode)
    monkeypatch.delenv('MS_MACHINE_TOKEN', raising=False)
    try:
        r = _client().post(
            '/api/machine/solve',
            files={'file': ('nest.dxf', _machine_master_bytes(),
                            'application/octet-stream')},
            data={'config': json.dumps({'gate_mm': 1750, 'sizes': [28],
                                        'run_mode': 'normal'})})
    finally:
        strategy_mod._STRATEGY_STATE.clear()
        strategy_mod._STRATEGY_STATES.clear()
        machine_mod._DELETED_TASKS.clear()
        sessions_mod.registry.reset()
    assert r.status_code == 202, r.text
