"""US-006 uploads 磁盘 TTL 清理测试（diskclean.py + commit/启动触发点）。

覆盖（PRD web 多会话 US-006 验收）：
1. 临时目录新旧混合：超龄 ``<doc_id>.dxf`` + ``<doc_id>_pieces/`` 成对删除、
   未超龄保留；孤儿单边（只有 dxf / 只有 pieces 目录）按同 TTL 清理；混龄对
   （dxf 超龄 / pieces 新）整对保留 —— commit 会重写 pieces 不刷新 dxf mtime，
   按单侧判龄会误删仍可被同 doc commit 引用的母版；
2. 保护集：活跃会话 doc_id（含 ``state['doc']['doc_id']`` 启动 reload 形态）不删；
   会话 A 活跃 + 会话 B 已过期但 B 的策略 run 仍在跑（marker 在）→ B 的 master
   doc 不删（marker 移除后才可清）；
3. ``strategy_cfg_*.json`` 按 TTL 清理；非 web 命名文件一律不动；
4. dry-run 只列清单不动文件；目录缺失 → 空结果；
5. 容错：单条目删除失败 warn 跳过继续；``trigger_cleanup`` 吞掉一切异常；
   commit 路由触发的清理失败不影响响应（200 照常返回）；
6. env 旋钮 ``MS_UPLOAD_TTL_DAYS`` 解析（合法 float / 非法回退 14）；
7. 分层纯度 AST 守卫：模块级仅标准库 + ``..paths``，禁 import server / cli。

隔离：单测全参数注入（目录 / TTL / 时钟 / 私有注册表）；路由级测试 monkeypatch
``server_mod.UPLOADS_DIR`` + ``paths.OUT_DIR/CONFIG_RUNS_DIR/INTERMEDIATE`` 到
tmp_path（commit 路由显式传 ``UPLOADS_DIR`` 给清理，patch 后自动跟随 tmp，不碰
真实 ``out/``）。
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting import paths as paths_mod
from materialsorting.web import diskclean as diskclean_mod
from materialsorting.web import server as server_mod
from materialsorting.web import sessions
from materialsorting.web.sessions import _FakeClock
from materialsorting.web.server import app

DAY = 86400.0
NOW = 1_000_000.0


# ---------------------------------------------------------------- 测试基础设施

def _set_age(path: Path, now: float, days: float) -> None:
    t = now - days * DAY
    os.utime(path, (t, t))


def _mk_dxf(uploads: Path, doc_id: str, *, now: float = NOW,
            age_days: float = 20.0) -> Path:
    p = uploads / f'{doc_id}.dxf'
    p.write_bytes(b'x')
    _set_age(p, now, age_days)
    return p


def _mk_pieces(uploads: Path, doc_id: str, *, now: float = NOW,
               age_days: float = 20.0) -> Path:
    p = uploads / f'{doc_id}_pieces'
    p.mkdir()
    (p / 'pieces_intermediate.json').write_text('{}', encoding='utf-8')
    _set_age(p, now, age_days)
    return p


def _mk_registry(now: float = NOW, *doc_ids: str) -> sessions.SessionRegistry:
    """私有注册表（不动单例）：每个 doc_id 一个活跃会话。"""
    reg = sessions.SessionRegistry(clock=_FakeClock(now))
    for i, doc_id in enumerate(doc_ids):
        reg.resolve(f'sesssid{i:04d}', create=True).doc_id = doc_id
    return reg


def _mk_marker(cfg_runs: Path, sid: str, doc_id: str) -> Path:
    name = ('.web_strategy_active.json' if sid == sessions.DEFAULT_SID
            else f'.web_strategy_active_{sid}.json')
    p = cfg_runs / name
    p.write_text(json.dumps({'pid': 1, 'run_dir': None, 'doc_id': doc_id,
                             'mode': 'se', 'started_at': 'x'}), encoding='utf-8')
    return p


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """单测隔离：paths.OUT_DIR / CONFIG_RUNS_DIR 指到 tmp（diskclean 调用时取属性）。"""
    out = tmp_path / 'out'
    uploads = out / 'uploads'
    uploads.mkdir(parents=True)
    cfg_runs = out / 'config_runs'
    cfg_runs.mkdir(parents=True)
    monkeypatch.setattr(paths_mod, 'OUT_DIR', str(out))
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(cfg_runs))
    return SimpleNamespace(uploads=uploads, cfg_runs=cfg_runs, now=NOW)


@pytest.fixture(autouse=True)
def _isolated_registry():
    """单例注册表隔离（套路同 test_web_sessions.py）：停扫描 + 前后清零。"""
    reg = sessions.registry
    reg.stop_scanner()
    reg.reset()
    yield reg
    reg.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------- AC1 新旧混合 + 孤儿

def test_old_pair_deleted_fresh_kept(clean_env):
    """超龄成对目录被删；未超龄保留；混龄对（dxf 旧 / pieces 新）整对保留。"""
    up = clean_env.uploads
    old_dxf, old_pieces = _mk_dxf(up, 'olddoc01'), _mk_pieces(up, 'olddoc01')
    new_dxf, new_pieces = _mk_dxf(up, 'newdoc02', age_days=1.0), \
        _mk_pieces(up, 'newdoc02', age_days=1.0)
    mix_dxf, mix_pieces = _mk_dxf(up, 'mixdoc03'), _mk_pieces(up, 'mixdoc03', age_days=1.0)

    removed = diskclean_mod.scan_uploads(
        uploads_dir=up, config_runs_dir=clean_env.cfg_runs,
        ttl_days=14.0, now=NOW, registry=_mk_registry(NOW))

    assert not old_dxf.exists() and not old_pieces.exists()
    assert new_dxf.exists() and new_pieces.exists()
    assert mix_dxf.exists() and mix_pieces.exists()   # 混龄整对保留
    assert removed == ['olddoc01.dxf', 'olddoc01_pieces']


def test_orphan_single_sides_cleaned(clean_env):
    """孤儿单边（只有 dxf / 只有 pieces 目录）按同 TTL 清理；未超龄孤儿保留。"""
    up = clean_env.uploads
    orphan_dxf = _mk_dxf(up, 'orphdoc04')             # 孤儿 dxf（无 pieces）
    orphan_pieces = _mk_pieces(up, 'orphdoc05')       # 孤儿 pieces（无 dxf）
    fresh_orphan = _mk_dxf(up, 'freshd06', age_days=1.0)

    removed = diskclean_mod.scan_uploads(
        uploads_dir=up, config_runs_dir=clean_env.cfg_runs,
        ttl_days=14.0, now=NOW, registry=_mk_registry(NOW))

    assert not orphan_dxf.exists() and not orphan_pieces.exists()
    assert fresh_orphan.exists()
    assert removed == ['orphdoc04.dxf', 'orphdoc05_pieces']


def test_strategy_cfg_ttl_and_unknown_names_untouched(clean_env):
    """超龄 strategy_cfg_*.json 清理、新 cfg 保留；非 web 命名文件一律不动。"""
    up = clean_env.uploads
    old_cfg = up / 'strategy_cfg_20260101-000000.json'
    old_cfg.write_text('{}', encoding='utf-8')
    _set_age(old_cfg, NOW, 20.0)
    new_cfg = up / 'strategy_cfg_20260202-000000.json'
    new_cfg.write_text('{}', encoding='utf-8')
    stray_txt = up / 'strategy_cfg_notes.txt'          # 前缀对但非 .json
    stray_txt.write_text('keep', encoding='utf-8')
    _set_age(stray_txt, NOW, 20.0)
    weird_dxf = up / 'has-dash-不合法.dxf'             # doc_id 不匹配 SID_RE
    weird_dxf.write_bytes(b'x')
    _set_age(weird_dxf, NOW, 20.0)
    weird_dir = up / 'has dash_pieces'
    weird_dir.mkdir()

    removed = diskclean_mod.scan_uploads(
        uploads_dir=up, config_runs_dir=clean_env.cfg_runs,
        ttl_days=14.0, now=NOW, registry=_mk_registry(NOW))

    assert not old_cfg.exists() and new_cfg.exists()
    assert stray_txt.exists() and weird_dxf.exists() and weird_dir.exists()
    assert removed == ['strategy_cfg_20260101-000000.json']


# ---------------------------------------------------------------- AC2 保护集

def test_active_session_doc_protected(clean_env):
    """活跃会话 doc_id（st.doc_id）不删 —— 即使超龄。"""
    up = clean_env.uploads
    dxf, pieces = _mk_dxf(up, 'sessdoc07'), _mk_pieces(up, 'sessdoc07')

    removed = diskclean_mod.scan_uploads(
        uploads_dir=up, config_runs_dir=clean_env.cfg_runs,
        ttl_days=14.0, now=NOW, registry=_mk_registry(NOW, 'sessdoc07'))

    assert dxf.exists() and pieces.exists()
    assert removed == []



def test_session_state_doc_id_protected_startup_reload_shape(clean_env):
    """会话快照 state['doc']['doc_id']（启动 reload 形态，st.doc_id=None）也进保护集。"""
    up = clean_env.uploads
    dxf = _mk_dxf(up, 'startd08')
    reg = sessions.SessionRegistry(clock=_FakeClock(NOW))
    st = reg.resolve('sesssid0000', create=True)
    st.state = {'doc': {'doc_id': 'startd08'}}         # 启动 reload：只填 state['doc']

    removed = diskclean_mod.scan_uploads(
        uploads_dir=up, config_runs_dir=clean_env.cfg_runs,
        ttl_days=14.0, now=NOW, registry=reg)

    assert dxf.exists()
    assert removed == []


def test_marker_protects_expired_session_running_strategy(clean_env):
    """AC 核心：会话 A 活跃 + 会话 B 已过期（不在注册表）但 B 的策略 run 仍在跑
    （marker 在）→ B 的 master doc 不删；marker 移除后（run 结束）才可清。"""
    up = clean_env.uploads
    a_dxf, a_pieces = _mk_dxf(up, 'sessaadoc'), _mk_pieces(up, 'sessaadoc')
    b_dxf, b_pieces = _mk_dxf(up, 'sessbbdoc'), _mk_pieces(up, 'sessbbdoc')

    _mk_marker(clean_env.cfg_runs, 'bbbbbbbb1111', 'sessbbdoc')
    removed = diskclean_mod.scan_uploads(
        uploads_dir=up, config_runs_dir=clean_env.cfg_runs,
        ttl_days=14.0, now=NOW, registry=_mk_registry(NOW, 'sessaadoc'))

    assert a_dxf.exists() and a_pieces.exists()       # A：活跃会话保护
    assert b_dxf.exists() and b_pieces.exists()       # B：marker 保护（run 在跑）
    assert removed == []

    # run 结束（marker 清除）→ B 不再被保护，可按 TTL 清理。
    (clean_env.cfg_runs / '.web_strategy_active_bbbbbbbb1111.json').unlink()
    removed2 = diskclean_mod.scan_uploads(
        uploads_dir=up, config_runs_dir=clean_env.cfg_runs,
        ttl_days=14.0, now=NOW, registry=_mk_registry(NOW, 'sessaadoc'))
    assert not b_dxf.exists() and not b_pieces.exists()
    assert a_dxf.exists()                              # A 始终不动
    assert removed2 == ['sessbbdoc.dxf', 'sessbbdoc_pieces']


def test_default_marker_and_bad_marker_tolerated(clean_env):
    """default 旧名 marker 同样进保护集；坏 JSON / 缺 doc_id marker 容错跳过。"""
    up = clean_env.uploads
    d_dxf = _mk_dxf(up, 'dfltdoc09')
    _mk_marker(clean_env.cfg_runs, sessions.DEFAULT_SID, 'dfltdoc09')
    bad = clean_env.cfg_runs / '.web_strategy_active_cccccccc2222.json'
    bad.write_text('{not json', encoding='utf-8')       # 坏 JSON → 跳过

    assert diskclean_mod._marker_doc_ids(clean_env.cfg_runs) == {'dfltdoc09'}
    removed = diskclean_mod.scan_uploads(
        uploads_dir=up, config_runs_dir=clean_env.cfg_runs,
        ttl_days=14.0, now=NOW, registry=_mk_registry(NOW))
    assert d_dxf.exists()
    assert removed == []


# ---------------------------------------------------------------- AC3 dry-run / 容错

def test_dry_run_lists_without_deleting(clean_env):
    """dry-run：返回「将删」清单但不动任何文件。"""
    up = clean_env.uploads
    old_dxf = _mk_dxf(up, 'olddoc11')
    new_dxf = _mk_dxf(up, 'newdoc12', age_days=1.0)

    planned = diskclean_mod.scan_uploads(
        uploads_dir=up, config_runs_dir=clean_env.cfg_runs,
        ttl_days=14.0, now=NOW, registry=_mk_registry(NOW), dry_run=True)

    assert planned == ['olddoc11.dxf']
    assert old_dxf.exists() and new_dxf.exists()


def test_missing_uploads_dir_returns_empty(clean_env):
    """uploads 目录不存在（从未上传）→ 空结果不抛。"""
    assert diskclean_mod.scan_uploads(
        uploads_dir=clean_env.uploads.parent / 'nope', dry_run=True) == []


def test_default_paths_read_at_call_time(clean_env):
    """缺省路径调用时取 paths.OUT_DIR 属性（monkeypatch 生效 —— strategy._uploads_dir 同套路）。"""
    _mk_dxf(clean_env.uploads, 'olddoc13')
    removed = diskclean_mod.scan_uploads(
        config_runs_dir=clean_env.cfg_runs, ttl_days=14.0, now=NOW,
        registry=_mk_registry(NOW))
    assert removed == ['olddoc13.dxf']
    assert not (clean_env.uploads / 'olddoc13.dxf').exists()


def test_delete_failure_warns_and_continues(clean_env, monkeypatch, capsys):
    """单条目删除失败（目录被占用等）只 warn 跳过继续，其余条目照删。"""
    up = clean_env.uploads
    pair_dxf = _mk_dxf(up, 'pairdoc14')
    pair_pieces = _mk_pieces(up, 'pairdoc14')
    other_dxf = _mk_dxf(up, 'otherd15')               # 另一 doc，删除不受影响

    def _boom(path):
        raise OSError('dir in use')
    monkeypatch.setattr(diskclean_mod.shutil, 'rmtree', _boom)

    removed = diskclean_mod.scan_uploads(
        uploads_dir=up, config_runs_dir=clean_env.cfg_runs,
        ttl_days=14.0, now=NOW, registry=_mk_registry(NOW))

    assert not pair_dxf.exists()                       # dxf（unlink）照删
    assert pair_pieces.exists()                        # rmtree 失败 → 保留 + warn
    assert not other_dxf.exists()
    assert removed == ['otherd15.dxf', 'pairdoc14.dxf']
    assert '删除失败' in capsys.readouterr().err


def test_trigger_cleanup_swallows_exceptions(monkeypatch, capsys):
    """trigger_cleanup 兜底吞掉扫描阶段的一切异常：返回 []，仅 warn。"""
    def _boom(**kwargs):
        raise RuntimeError('scan exploded')
    monkeypatch.setattr(diskclean_mod, 'scan_uploads', _boom)

    assert diskclean_mod.trigger_cleanup() == []
    assert '清理异常' in capsys.readouterr().err


# ---------------------------------------------------------------- env 旋钮

def test_env_ttl_parsing(monkeypatch):
    """MS_UPLOAD_TTL_DAYS：合法 float 生效；非法回退缺省 14。"""
    try:
        monkeypatch.setenv('MS_UPLOAD_TTL_DAYS', '0.5')
        mod = importlib.reload(diskclean_mod)
        assert mod.UPLOAD_TTL_DAYS == 0.5
        monkeypatch.setenv('MS_UPLOAD_TTL_DAYS', 'bogus')
        mod = importlib.reload(diskclean_mod)
        assert mod.UPLOAD_TTL_DAYS == 14.0
        monkeypatch.setenv('MS_UPLOAD_TTL_DAYS', '-3')     # 非正 = 非法
        mod = importlib.reload(diskclean_mod)
        assert mod.UPLOAD_TTL_DAYS == 14.0
    finally:
        monkeypatch.delenv('MS_UPLOAD_TTL_DAYS', raising=False)
        importlib.reload(diskclean_mod)                     # 还原模块态
    assert diskclean_mod.UPLOAD_TTL_DAYS == 14.0


# ---------------------------------------------------------------- commit 触发点（路由级）

def _fake_commit_sync_factory():
    """打桩 _commit_to_nesting_sync：写最小合法 intermediate（per-doc + 镜像）。"""
    def _fake(doc_id, src_dxf, source_name):
        doc = {'doc_id': doc_id, 'source': source_name, 'gate_mm': 1980.0,
               'n_pieces': 1, 'total_area_mm2': 120000.0,
               'pieces': [{'pid': 'g01_28', 'label': 'g01', 'size': 28,
                            'polygon': [[0.0, 0.0], [300.0, 0.0], [300.0, 400.0],
                                        [0.0, 400.0]],
                            'allowed_angles': [0, 180]}],
               'pieces_by_id': {}}
        per_doc = Path(server_mod.UPLOADS_DIR) / f'{doc_id}_pieces'
        per_doc.mkdir(parents=True, exist_ok=True)
        (per_doc / 'pieces_intermediate.json').write_text(
            json.dumps(doc, ensure_ascii=False), encoding='utf-8')
        Path(paths_mod.INTERMEDIATE).write_text(
            json.dumps(doc, ensure_ascii=False), encoding='utf-8')
        return {'doc_id': doc_id, 'source': source_name, 'sizes': ['28'],
                'n_pieces': 1, 'total_area_mm2': 1.0, 'n_written_dxf': 1,
                'n_skipped': 0, 'skipped': [], 'bak': 'unused'}
    return _fake


@pytest.fixture
def commit_clean_env(tmp_path, monkeypatch):
    """路由级隔离：server_mod.UPLOADS_DIR + paths.OUT_DIR/CONFIG_RUNS_DIR/INTERMEDIATE
    全指 tmp_path（commit 路由把 UPLOADS_DIR 显式传给清理，patch 后自动跟随）。"""
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    cfg_runs = tmp_path / 'config_runs'
    cfg_runs.mkdir()
    mirror = tmp_path / 'mirror_intermediate.json'
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', uploads)
    monkeypatch.setattr(paths_mod, 'OUT_DIR', str(tmp_path))
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(cfg_runs))
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE', str(mirror))
    monkeypatch.setattr(server_mod, '_commit_to_nesting_sync', _fake_commit_sync_factory())
    # 无 sid commit 会 ``_reload_pieces_state`` 原位改写共享 ``_PIECES_STATE`` ——
    # 快照/恢复隔离，不污染后续测试（test_ws_stop 等依赖已加载状态）。
    snap = dict(server_mod._PIECES_STATE)
    yield SimpleNamespace(uploads=uploads, cfg_runs=cfg_runs, mirror=mirror)
    server_mod._PIECES_STATE.clear()
    server_mod._PIECES_STATE.update(snap)


def test_commit_success_triggers_ttl_cleanup(client, commit_clean_env):
    """commit 成功后顺带清理超龄孤儿；本轮 commit 的母版 / 未超龄文件不动。"""
    up = commit_clean_env.uploads
    master = up / 'feed0001.dxf'
    master.write_bytes(b'x')                            # 本轮 commit 输入（mtime 新）
    real_now = time.time()                              # 路由触发的清理走真实墙钟
    old_orphan = _mk_dxf(up, 'orphdoc16', now=real_now)          # 超龄孤儿 → 被清
    new_orphan = _mk_dxf(up, 'newdoc17', now=real_now, age_days=1.0)  # 未超龄 → 保留

    r = client.post('/api/commit-to-nesting', json={'doc_id': 'feed0001'})
    assert r.status_code == 200
    body = r.json()
    assert body['reloaded'] is True and body['doc_id'] == 'feed0001'

    assert not old_orphan.exists()                      # commit 触发的 TTL 清理
    assert new_orphan.exists() and master.exists()
    assert (up / 'feed0001_pieces').exists()            # 本轮 commit 产物完好


def test_cleanup_failure_does_not_affect_commit(client, commit_clean_env,
                                                monkeypatch, capsys):
    """清理抛异常（目录被占用等极端场景）只 warn：commit 照常 200、响应不受影响。"""
    def _boom(uploads_dir=None, **kwargs):
        raise RuntimeError('disk on fire')
    monkeypatch.setattr(diskclean_mod, 'trigger_cleanup', _boom)

    (commit_clean_env.uploads / 'feed0002.dxf').write_bytes(b'x')
    r = client.post('/api/commit-to-nesting', json={'doc_id': 'feed0002'})
    assert r.status_code == 200
    assert r.json()['reloaded'] is True
    assert 'uploads 清理失败' in capsys.readouterr().err


def test_commit_cleanup_runs_isolated_from_real_out(client, commit_clean_env):
    """commit 触发的清理范围 = 路由显式传入的 UPLOADS_DIR（tmp），真实 out/ 不受影响。"""
    up = commit_clean_env.uploads
    (up / 'feed0003.dxf').write_bytes(b'x')
    real_now = time.time()
    old_pair_dxf = _mk_dxf(up, 'olddoc18', now=real_now)
    old_pair_pieces = _mk_pieces(up, 'olddoc18', now=real_now)

    r = client.post('/api/commit-to-nesting', json={'doc_id': 'feed0003'})
    assert r.status_code == 200
    assert not old_pair_dxf.exists() and not old_pair_pieces.exists()


# ---------------------------------------------------------------- 分层纯度（AST 守卫）

def test_diskclean_module_layering_purity():
    """diskclean 模块级仅标准库 + ``..paths``；禁 import server（server → diskclean
    单向无环）/ 禁 import cli（进程边界而非 import 边界，同 strategy 守卫）。"""
    src = Path(diskclean_mod.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'json', 'os', 'shutil', 'sys', 'tempfile',
               'threading', 'time', 'pathlib', 'materialsorting'}
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert not mod.startswith('materialsorting.web.server'), \
                'diskclean 禁 import server（依赖方向 server → diskclean）'
            assert not mod.startswith('materialsorting.cli'), \
                'web 层禁 import cli（spawn 是进程边界，同 strategy AST 守卫）'
            if node.level:                      # 相对 import 解析到本包/上层 paths
                names = {'materialsorting'}
            else:
                names = {mod.split('.')[0]}
        else:
            continue
        assert names <= allowed, sorted(names - allowed)
    # 源级哨兵：任何 server / cli 引用（含函数内延迟 import）都不允许。
    assert 'materialsorting.web.server' not in src
    assert 'from .server' not in src
    assert 'materialsorting.cli' not in src and 'from ..cli' not in src
