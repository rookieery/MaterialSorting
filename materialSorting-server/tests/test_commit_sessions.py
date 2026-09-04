"""US-002 commit 双写与会话绑定测试（多会话隔离第一消费方，纯后端路由级）。

覆盖（PRD web 多会话 US-002 验收）：
1. 带 sid commit：``out/uploads/<doc_id>_pieces/pieces_intermediate.json`` 存在且与
   全局镜像内容逐字段一致（同一 doc dict 双写两文件）；会话快照 = per-doc 内容、
   doc_id 绑定；
2. 会话 A、B 先后 commit 不同 doc：A 的 state（pieces/pieces_by_id/gate_mm）保持
   自己的 doc 不受 B 影响，两份 per-doc 文件并存（镜像 = 最后 commit 者，漂移允许）；
3. 带 sid commit 不触碰 default 内存：``runtime._PIECES_STATE`` 不被刷新、不被 rebind；
   default 会话 state 与 ``runtime._PIECES_STATE`` 仍是同一 dict 对象（is 锁死）；
4. 无 sid commit → default 会话更新（现行为回归；tests/test_commit_pipeline.py 零
   改动全绿）；
5. sid 解析 fail-fast：过期 → 401 session_expired（CPU 管线不跑、不落盘）、
   非法 → 400；
6. 镜像写失败仅 warn：per-doc 落盘 + 会话注册 + 200 响应均不受影响。

合成母版双档（不同码号 × 不同几何比例）构造「不同 doc」；隔离环境 monkeypatch
``server_mod.UPLOADS_DIR`` / ``paths_mod.INTERMEDIATE`` 到 tmp_path（套路同
tests/test_commit_pipeline.py），单例注册表 autouse 隔离（套路同
tests/test_web_sessions.py）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED
from starlette.testclient import TestClient

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.web import runtime as runtime_mod
from materialsorting.web import server as server_mod
from materialsorting.web import sessions
from materialsorting.web.server import app
from materialsorting.web.sessions import _FakeClock

# 双档合成母版：档 A（码 28/29，1.0x）与档 B（码 30/31，1.4x）→ pid 集合与
# 几何均不同，两档 intermediate 内容逐字段可区分。
_SYNTH_SHAPES = [('blk x', (0, 0, 400, 700)), ('zz 9', (10, 10, 200, 90))]
_DOC_A = {'doc_id': 'docaaaa1', 'sizes': (28, 29), 'scale': 1.0}
_DOC_B = {'doc_id': 'docbbbb2', 'sizes': (30, 31), 'scale': 1.4}
_A_PIDS = {'g01_28', 'g02_28', 'g01_29', 'g02_29'}
_B_PIDS = {'g01_30', 'g02_30', 'g01_31', 'g02_31'}


def _make_master_dxf(path: Path, sizes: tuple, scale: float) -> Path:
    """合成母版：每码 2 片有码号 block（高度 × scale 区分几何）。"""
    doc = ezdxf.new('R12')
    for size in sizes:
        for name, (x, y, w, h) in _SYNTH_SHAPES:
            h2 = h * scale
            blk = doc.blocks.new(name=f'{name}.{size}')
            poly = blk.add_polyline2d(
                [(x, y), (x + w, y), (x + w, y + h2), (x, y + h2)],
                dxfattribs={'layer': '1'})
            poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
            blk.add_line((x + 10, y + h2 / 2), (x + w - 10, y + h2 / 2),
                         dxfattribs={'layer': '7'})
    doc.saveas(str(path))
    return path


@pytest.fixture(autouse=True)
def _isolated_registry():
    """单例注册表隔离（套路同 tests/test_web_sessions.py）：停扫描 + 前后清零。"""
    reg = sessions.registry
    reg.stop_scanner()
    reg.reset()
    yield reg
    reg.reset()


@pytest.fixture
def commit_env(tmp_path, monkeypatch):
    """隔离环境：UPLOADS_DIR 与 paths.INTERMEDIATE 指到 tmp_path。"""
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    mirror = tmp_path / 'mirror_intermediate.json'
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', uploads)
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE', str(mirror))
    return tmp_path, uploads, mirror


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _upload_master(env, doc: dict) -> None:
    """按档位合成母版并落到 uploads/<doc_id>.dxf（commit 路由的输入）。"""
    _, uploads, _ = env
    _make_master_dxf(uploads / f"{doc['doc_id']}.dxf", doc['sizes'], doc['scale'])


def _commit(client, env, doc: dict, sid: str | None = None):
    headers = {'X-Session-Id': sid} if sid else {}
    return client.post('/api/commit-to-nesting', json={'doc_id': doc['doc_id']},
                       headers=headers)


def _per_doc(env, doc_id: str) -> Path:
    _, uploads, _ = env
    return uploads / f'{doc_id}_pieces' / 'pieces_intermediate.json'


# ---------------------------------------------------------------- AC1 双写

def test_sid_commit_double_writes_per_doc_and_mirror(client, commit_env):
    """带 sid commit：per-doc intermediate 存在且与全局镜像逐字段一致（同一 doc dict）。"""
    _upload_master(commit_env, _DOC_A)
    r = _commit(client, commit_env, _DOC_A, sid='sessaaaa')
    assert r.status_code == 200
    body = r.json()
    assert body['reloaded'] is True
    assert body['doc_id'] == _DOC_A['doc_id']

    per_doc, mirror = _per_doc(commit_env, _DOC_A['doc_id']), commit_env[2]
    assert per_doc.exists() and mirror.exists()
    doc_per = json.loads(per_doc.read_text(encoding='utf-8'))
    doc_mirror = json.loads(mirror.read_text(encoding='utf-8'))
    assert doc_per == doc_mirror                       # 逐字段一致（同一 doc dict 双写）
    assert doc_per['doc_id'] == _DOC_A['doc_id']

    # 会话快照 = per-doc 内容 + doc_id 绑定
    st = sessions.registry.resolve('sessaaaa')
    assert st.doc_id == _DOC_A['doc_id']
    assert st.state['doc'] == doc_per
    assert {p['pid'] for p in st.state['pieces']} == _A_PIDS
    assert set(st.state['pieces_by_id']) == _A_PIDS
    assert st.state['gate_mm'] == 1750.0


# ---------------------------------------------------------------- AC2 双会话隔离

def test_dual_session_commit_isolation(client, commit_env):
    """会话 A、B 先后 commit 不同 doc：A 的 state 不受 B 影响，两份 per-doc 并存。"""
    _upload_master(commit_env, _DOC_A)
    _upload_master(commit_env, _DOC_B)
    assert _commit(client, commit_env, _DOC_A, sid='sessaaaa').status_code == 200
    assert _commit(client, commit_env, _DOC_B, sid='sessbbbb').status_code == 200

    a = sessions.registry.resolve('sessaaaa')          # resolve 只刷活性，不切数据
    b = sessions.registry.resolve('sessbbbb')
    assert a.doc_id == _DOC_A['doc_id'] and b.doc_id == _DOC_B['doc_id']
    assert a.state is not b.state
    assert a.state['doc'] is not b.state['doc']
    assert {p['pid'] for p in a.state['pieces']} == _A_PIDS     # A 不受 B 影响
    assert set(a.state['pieces_by_id']) == _A_PIDS
    assert {p['pid'] for p in b.state['pieces']} == _B_PIDS
    assert a.state['gate_mm'] == b.state['gate_mm'] == 1750.0
    assert a.state['doc']['total_area_mm2'] != b.state['doc']['total_area_mm2']

    # 两份 per-doc 文件并存；镜像 = 最后 commit 者（B），漂移允许
    assert _per_doc(commit_env, _DOC_A['doc_id']).exists()
    assert _per_doc(commit_env, _DOC_B['doc_id']).exists()
    mirror_doc = json.loads(commit_env[2].read_text(encoding='utf-8'))
    assert mirror_doc['doc_id'] == _DOC_B['doc_id']
    assert mirror_doc == json.loads(
        _per_doc(commit_env, _DOC_B['doc_id']).read_text(encoding='utf-8'))


# ---------------------------------------------------------------- AC3 default 内存不动

def test_sid_commit_leaves_default_memory_untouched(client, commit_env):
    """带 sid commit 刷新镜像但不刷 default 内存；default state is _PIECES_STATE。"""
    _upload_master(commit_env, _DOC_A)
    _upload_master(commit_env, _DOC_B)
    assert _commit(client, commit_env, _DOC_A).status_code == 200     # default 先有 A

    default_state = runtime_mod._PIECES_STATE
    assert default_state['doc']['doc_id'] == _DOC_A['doc_id']

    assert _commit(client, commit_env, _DOC_B, sid='sessaaaa').status_code == 200
    # default 内存不被刷新、不被 rebind（内容仍 A、同一 dict 对象）
    assert runtime_mod._PIECES_STATE is default_state
    assert runtime_mod._PIECES_STATE['doc']['doc_id'] == _DOC_A['doc_id']
    assert {p['pid'] for p in runtime_mod._PIECES_STATE['pieces']} == _A_PIDS
    # default 会话 state 与 _PIECES_STATE 仍是同一 dict（is 锁死）
    assert sessions.registry.resolve(None).state is runtime_mod._PIECES_STATE
    # 镜像 = 最后 commit 者（B）—— 允许漂移
    mirror_doc = json.loads(commit_env[2].read_text(encoding='utf-8'))
    assert mirror_doc['doc_id'] == _DOC_B['doc_id']


# ---------------------------------------------------------------- AC4 无 sid 回归

def test_no_sid_commit_updates_default_session(client, commit_env):
    """无 sid commit → default 会话更新（现行为）：state is _PIECES_STATE、doc_id 绑定。"""
    _upload_master(commit_env, _DOC_A)
    r = _commit(client, commit_env, _DOC_A)
    assert r.status_code == 200
    assert r.json()['reloaded'] is True

    st = sessions.registry.resolve(None)
    assert st.sid == sessions.DEFAULT_SID
    assert st.state is runtime_mod._PIECES_STATE
    assert st.doc_id == _DOC_A['doc_id']
    assert {p['pid'] for p in runtime_mod._PIECES_STATE['pieces']} == _A_PIDS


def test_default_follows_last_no_sid_committer(client, commit_env):
    """default = 最后无 sid commit 者：sid commit 不改 default，后续无 sid commit 覆盖。"""
    _upload_master(commit_env, _DOC_A)
    _upload_master(commit_env, _DOC_B)
    before_doc = runtime_mod._PIECES_STATE.get('doc')     # 启动期真实 intermediate 内容
    _commit(client, commit_env, _DOC_A, sid='sessaaaa')   # 镜像 = A，default 不动
    assert runtime_mod._PIECES_STATE.get('doc') is before_doc
    _commit(client, commit_env, _DOC_B)                   # 无 sid → default = B
    assert runtime_mod._PIECES_STATE['doc']['doc_id'] == _DOC_B['doc_id']
    # 会话 A 的快照不受 default 更新影响
    a = sessions.registry.resolve('sessaaaa')
    assert a.state is not runtime_mod._PIECES_STATE
    assert {p['pid'] for p in a.state['pieces']} == _A_PIDS


# ---------------------------------------------------------------- AC5 sid 解析 fail-fast

def test_sid_commit_expired_401_fail_fast(client, commit_env, monkeypatch):
    """过期 sid commit → 401 session_expired；CPU 管线不跑、per-doc 不落盘。"""
    clk = _FakeClock()
    monkeypatch.setattr(sessions.registry, 'clock', clk)
    sessions.registry.resolve('sessaaaa', create=True)
    clk.advance(sessions.registry.ttl_sec + 1)
    _upload_master(commit_env, _DOC_A)

    r = _commit(client, commit_env, _DOC_A, sid='sessaaaa')
    assert r.status_code == 401
    assert r.json()['code'] == 'session_expired'
    # fail-fast：会话解析在管线之前，未产生任何落盘
    assert not _per_doc(commit_env, _DOC_A['doc_id']).exists()
    assert not commit_env[2].exists()


def test_sid_commit_invalid_sid_400(client, commit_env):
    """非法 sid commit → 400 {error:'sid 非法'}（未落盘）。"""
    _upload_master(commit_env, _DOC_A)
    r = _commit(client, commit_env, _DOC_A, sid='bad-sid!')
    assert r.status_code == 400
    assert r.json() == {'error': 'sid 非法'}
    assert not _per_doc(commit_env, _DOC_A['doc_id']).exists()


def test_sid_commit_unknown_sid_creates_session(client, commit_env):
    """合法但未注册的 sid（服务重启场景）commit → 建会话并绑定（数据自带，无需先注册）。"""
    _upload_master(commit_env, _DOC_A)
    r = _commit(client, commit_env, _DOC_A, sid='freshsid1')
    assert r.status_code == 200
    st = sessions.registry.resolve('freshsid1')
    assert st.doc_id == _DOC_A['doc_id']
    assert set(st.state['pieces_by_id']) == _A_PIDS


# ---------------------------------------------------------------- AC6 镜像失败仅 warn

def test_mirror_write_failure_warn_only(client, commit_env, monkeypatch, capsys):
    """镜像写失败（父路径被文件占住）仅 warn：per-doc 落盘 + 会话注册 + 200 不受影响。"""
    tmp_path, uploads, mirror = commit_env
    blocker = tmp_path / 'blocker'                    # 普通文件占住镜像父目录
    blocker.write_text('x', encoding='utf-8')
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE', str(blocker / 'x.json'))
    _upload_master(commit_env, _DOC_A)

    r = _commit(client, commit_env, _DOC_A, sid='sessaaaa')
    assert r.status_code == 200
    body = r.json()
    assert body['reloaded'] is True                   # 会话快照只依赖 per-doc 落盘
    assert body['mirror_error']                       # 镜像失败信息 additive 回显
    assert '镜像写失败' in capsys.readouterr().err    # 仅 warn

    per_doc = _per_doc(commit_env, _DOC_A['doc_id'])
    assert per_doc.exists()
    st = sessions.registry.resolve('sessaaaa')
    assert st.doc_id == _DOC_A['doc_id']
    assert set(st.state['pieces_by_id']) == _A_PIDS

