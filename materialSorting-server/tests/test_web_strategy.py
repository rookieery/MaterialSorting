"""US-004 web 策略桥接测试（strategy.py 四路由 + doc_id + build_pid_meta 提取）。

覆盖（spec AC ≥ 12）：
  - start 校验（409 单例 ×2 / 422 数据空 / 422 缺 doc_id / 422 母版丢失 / 400
    mode / 400 minutes / 202 落盘对拍：config 7 键 + master_dxf 绝对路径 + spawn
    cmd + marker 5 键 + _STRATEGY_STATE 快照）；
  - status（run_dir 快照 diff 发现 + marker 回写 / 30s 超时 error 带 stderr 尾部 /
    fixture run_dir 逐字段解析 / 缺文件降级 null / done 清 marker）；
  - stop（mock subprocess.run 断言 taskkill 参数 + marker 清理 + 置 stopped）；
  - orphan（marker 在 + 内存空 → pid 存活探测 / 清理）；
  - result（incumbent → manifest 与 build_pid_meta 对拍 —— 提取回归护栏 +
    build_instance 输出一致性 + doc_id 漂移 warning + stopped 回落 best_frame）；
  - commit doc_id（_commit_to_nesting_sync 落 intermediate）；
  - AST 守卫：strategy.py 全模块禁 import ..cli.*（镜像 test_cli_portfolio 写法）；
  - ms-web 四路由在场（TestClient 探测）。

所有用例隔离 paths.CONFIG_RUNS_DIR / paths.OUT_DIR 到 tmp_path，不触碰真实
out/ 产物；spawn 走 FakeProc（不真起 CLI 子进程）。
"""
from __future__ import annotations

import ast
import json
import sys
import time
from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.const import POLYLINE_CLOSED
from starlette.testclient import TestClient

from materialsorting import paths as paths_mod
from materialsorting.web import strategy as strategy_mod
from materialsorting.web import server as server_mod
from materialsorting.web import sessions as sessions_mod
from materialsorting.web.sessions import _FakeClock


# ------------------------------------------------------------- 测试基础设施


class FakeProc:
    """Popen 替身：poll() 返回预置 rc（None = 存活）。"""

    def __init__(self, pid: int = 4321, rc=None):
        self.pid = pid
        self._rc = rc

    def poll(self):
        return self._rc


def _synthetic_pieces() -> list[dict]:
    """合成 3 片（schema v2）—— build_pid_meta 对拍 / result manifest 组装用。"""
    return [
        {'pid': 'g01_28', 'label': 'g01', 'size': 28,
         'polygon': [[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]],
         'bbox': [0.0, 0.0, 500.0, 800.0], 'area_mm2': 400000.0, 'n_verts': 4,
         'allowed_angles': [0, 180],
         'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None},
        {'pid': 'g02_28', 'label': 'g02', 'size': 28,
         'polygon': [[0.0, 0.0], [300.0, 0.0], [300.0, 400.0], [0.0, 400.0]],
         'bbox': [0.0, 0.0, 300.0, 400.0], 'area_mm2': 120000.0, 'n_verts': 4,
         'allowed_angles': [0, 180],
         'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None},
        {'pid': 'g01_30', 'label': 'g01', 'size': 30,
         'polygon': [[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]],
         'bbox': [0.0, 0.0, 500.0, 800.0], 'area_mm2': 400000.0, 'n_verts': 4,
         'allowed_angles': [0, 180],
         'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None},
    ]


def _fake_state(doc_id='deadbeef01', pieces=None, gate_mm=1980.0) -> dict:
    pieces = _synthetic_pieces() if pieces is None else pieces
    return {'doc': {'doc_id': doc_id, 'source': 'm.dxf', 'gate_mm': gate_mm},
            'gate_mm': gate_mm, 'pieces': pieces,
            'pieces_by_id': {p['pid']: p for p in pieces}}


@pytest.fixture
def strat_env(tmp_path, monkeypatch):
    """隔离环境：CONFIG_RUNS_DIR / OUT_DIR / tempfile.tempdir 指到 tmp_path + 状态清零。

    yields (client, tmp_path)；client 走 TestClient（真 FastAPI app），四路由已由
    server.py 文件尾注册。_pieces_state 打桩为可控 fake state（默认 None = 由
    用例自行 monkeypatch）。tempdir 一并隔离：start 的 stderr 临时文件与
    _cleanup_stale_web_artifacts 的清理范围都不触碰真实系统临时目录。
    """
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(tmp_path / 'config_runs'))
    monkeypatch.setattr(paths_mod, 'OUT_DIR', str(tmp_path / 'out'))
    # tempdir 一并隔离（须先建目录：gettempdir 不自动创建，NamedTemporaryFile
    # 直接在其下 open 会 FileNotFoundError）。
    tmp_dir = tmp_path / 'tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(strategy_mod.tempfile, 'tempdir', str(tmp_dir))
    strategy_mod._STRATEGY_STATE.clear()
    yield tmp_path
    strategy_mod._STRATEGY_STATE.clear()


def _patch_state(monkeypatch, state: dict | None):
    monkeypatch.setattr(strategy_mod, '_pieces_state', lambda: state)


def _spawn_capture(monkeypatch, pid=4321, rc=None):
    """打桩 spawn：记录 cmd + stderr 路径，返回 FakeProc。"""
    calls: dict = {}

    def fake_spawn(cmd, stderr_path):
        calls['cmd'] = list(cmd)
        calls['stderr_path'] = stderr_path
        return FakeProc(pid=pid, rc=rc)

    monkeypatch.setattr(strategy_mod, '_spawn_run_process', fake_spawn)
    return calls


def _active_state(tmp_path: Path, run_dir: str | None = None, rc=None,
                  stderr_text='配置错误: master_dxf 不存在\n') -> dict:
    """直装内存态（status/result 解析用，不走 start 全流程）。"""
    stderr_path = tmp_path / 'stderr.log'
    stderr_path.write_text(stderr_text, encoding='utf-8')
    st = {
        'state': 'running', 'proc': FakeProc(pid=4321, rc=rc), 'pid': 4321,
        'mode': 'race', 'minutes': 10, 'total_budget_sec': 600,
        'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'started_ts': time.time(), 'run_dir': run_dir,
        'snapshot': set(), 'stderr_path': str(stderr_path),
        'doc_id': 'deadbeef01', 'pieces_snapshot': _synthetic_pieces(),
        'sizes': None, 'per_type': None, 'quantities': None,
        'gate_mm': 1980.0, 'seed': 0, 'cfg_path': 'cfg.json',
        'run_name': 'web_race_abc123', 'stopped': False,
        'exit_code': None, 'error': None,
    }
    strategy_mod._STRATEGY_STATE.clear()
    strategy_mod._STRATEGY_STATE.update(st)
    return strategy_mod._STRATEGY_STATE


def _write_run_dir(tmp_path: Path, name='web_race_abc123_20260820-120000') -> Path:
    """合成一个已完成 seed 0/1 的 run_dir（strategy.json + result.json + 边车）。"""
    run_dir = Path(paths_mod.CONFIG_RUNS_DIR) / name
    run_dir.mkdir(parents=True)
    (run_dir / 'strategy.json').write_text(json.dumps({
        'mode': 'se', 'total_budget': 600, 'planned_seeds': [0, 1, 2],
        'started_at': '2026-08-20T12:00:00',
        'se': {'k_screens': 3, 'screen_s': 90, 'ext_s': 180},
    }), encoding='utf-8')
    (run_dir / 'result.json').write_text(json.dumps({
        'portfolio': {
            'mode': 'se',
            'incumbent': {'density': 0.88, 'width_mm': 7100.5, 'seed': 1,
                          'frame_index': 5, 'elapsed': 120.3,
                          'placed_items': [{'id': 'g01_28', 'rotation': 0.0,
                                            'translation': [1.0, 2.0]}]},
            'per_seed': [
                {'seed': 0, 'killed': False, 'kill_reason': None,
                 'best_density': 0.86, 'elapsed': 91.0, 'phase': 'screen'},
                {'seed': 1, 'killed': False, 'kill_reason': None,
                 'best_density': 0.87, 'elapsed': 91.2, 'phase': 'screen'},
            ],
        },
    }), encoding='utf-8')
    (run_dir / 'best_frame_s0.json').write_text(json.dumps({
        'seed': 0, 'frame_index': 3, 'elapsed': 30.0, 'phase': 'compression',
        'density': 0.86, 'density_sparrow': 0.9, 'width_mm': 7300.0,
        'n_placed': 3, 'placed_items': []}), encoding='utf-8')
    time.sleep(0.01)   # 保证 ext 边车 mtime 更新（current 取最新）
    (run_dir / 'best_frame_s1_ext.json').write_text(json.dumps({
        'seed': 1, 'frame_index': 5, 'elapsed': 120.3, 'phase': 'compression',
        'density': 0.88, 'density_sparrow': 0.92, 'width_mm': 7100.5,
        'n_placed': 3, 'placed_items': []}), encoding='utf-8')
    (run_dir / 'kill_decisions.jsonl').write_text('\n'.join([
        json.dumps({'t': 30.1, 'seed': 0, 'rule': 'R5_race_gate', 'd': 0.86,
                    'tau': 0.5, 'S_tau': None, 'theta': None, 'I': 0.86,
                    'would_kill': False}),
        json.dumps({'t': 31.0, 'seed': 1, 'rule': 'R5_race_gate', 'd': 0.85,
                    'tau': 0.5, 'S_tau': 0.86, 'theta': None, 'I': 0.86,
                    'would_kill': True}),
        json.dumps({'t': 32.0, 'seed': 2, 'rule': 'R1_envelope', 'd': 0.5,
                    'would_kill': True}),   # 非 R5 行必须被滤掉
    ]) + '\n', encoding='utf-8')
    return run_dir


def _client() -> TestClient:
    return TestClient(server_mod.app)


# ------------------------------------------------------------- commit doc_id


def test_commit_writes_doc_id_into_intermediate(tmp_path, monkeypatch):
    """US-004 AC1：_commit_to_nesting_sync 落盘的 doc dict 带 doc_id 键。"""
    from materialsorting.web.server import _commit_to_nesting_sync
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', tmp_path)
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE',
                        str(tmp_path / 'pieces_intermediate.json'))
    doc = ezdxf.new('R12')
    for name, (w, h) in [('blk a.28', (400, 700)), ('blk a.30', (400, 720))]:
        blk = doc.blocks.new(name=name)
        poly = blk.add_polyline2d(
            [(0, 0), (w, 0), (w, h), (0, h)], dxfattribs={'layer': '1'})
        poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
    master = tmp_path / 'master.dxf'
    doc.saveas(str(master))

    summary = _commit_to_nesting_sync('cafe1234', str(master), master.name)
    assert summary['doc_id'] == 'cafe1234'   # 响应体语义不变（键本就在场）
    written = json.loads((tmp_path / 'pieces_intermediate.json')
                         .read_text(encoding='utf-8'))
    assert written['doc_id'] == 'cafe1234'   # 新增：doc dict 落盘带 doc_id


# ------------------------------------------------------------- start 校验


def test_start_conflict_409_when_active(strat_env, monkeypatch):
    """内存态 starting/running → 409（进程级单例）。"""
    _patch_state(monkeypatch, _fake_state())
    strategy_mod._STRATEGY_STATE.update({'state': 'running'})
    r = _client().post('/api/strategy/start', json={'mode': 'race', 'minutes': 10})
    assert r.status_code == 409


def test_start_conflict_409_when_marker_present(strat_env, monkeypatch):
    """orphan marker 在（即使内存态空）→ 409，须先清理。"""
    _patch_state(monkeypatch, _fake_state())
    strategy_mod._write_marker({'pid': 999, 'run_dir': None, 'doc_id': 'x',
                                'mode': 'race', 'started_at': '2026-08-20T12:00:00'})
    r = _client().post('/api/strategy/start', json={'mode': 'race', 'minutes': 10})
    assert r.status_code == 409


def test_start_empty_pieces_422(strat_env, monkeypatch):
    """_PIECES_STATE 空 → 422（先上传母版 commit）。"""
    _patch_state(monkeypatch, {'doc': {}, 'gate_mm': 0.0, 'pieces': [],
                               'pieces_by_id': {}})
    r = _client().post('/api/strategy/start', json={'mode': 'race', 'minutes': 10})
    assert r.status_code == 422
    assert '排料数据为空' in r.json()['error']


def test_start_missing_doc_id_422(strat_env, monkeypatch):
    """旧 intermediate doc 无 doc_id → 422 中文提示重新上传 commit。"""
    state = _fake_state()
    state['doc'] = {'source': 'm.dxf', 'gate_mm': 1980.0}   # 无 doc_id
    _patch_state(monkeypatch, state)
    r = _client().post('/api/strategy/start', json={'mode': 'race', 'minutes': 10})
    assert r.status_code == 422
    assert 'doc_id' in r.json()['error'] and '重新上传' in r.json()['error']


def test_start_master_dxf_missing_422(strat_env, monkeypatch):
    """doc_id 在但 uploads/<doc_id>.dxf 已失（清理过）→ 422。"""
    _patch_state(monkeypatch, _fake_state(doc_id='ghost000000'))
    r = _client().post('/api/strategy/start', json={'mode': 'race', 'minutes': 10})
    assert r.status_code == 422


def test_start_invalid_mode_and_minutes_400(strat_env, monkeypatch):
    """mode ∉ {se,race} / minutes ∉ {10,20,30,60}（含字符串分钟）→ 400。"""
    _patch_state(monkeypatch, _fake_state(doc_id='cafe1234'))
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True)
    (uploads / 'cafe1234.dxf').write_bytes(b'DXF')
    c = _client()
    assert c.post('/api/strategy/start',
                  json={'mode': 'auto', 'minutes': 10}).status_code == 400
    assert c.post('/api/strategy/start',
                  json={'mode': 'race', 'minutes': 15}).status_code == 400
    assert c.post('/api/strategy/start',
                  json={'mode': 'race', 'minutes': '20'}).status_code == 400


def test_start_happy_path_config_marker_spawn_202(strat_env, monkeypatch):
    """202：config 7 键对拍（master_dxf 绝对路径 / seeds=[seed] / gate 回退 state）
    + spawn cmd + marker 5 键 + 内存快照（sizes/per_type/quantities/seed/gate_mm）。"""
    _patch_state(monkeypatch, _fake_state(doc_id='cafe1234'))
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True)
    master = uploads / 'cafe1234.dxf'
    master.write_bytes(b'DXF')
    calls = _spawn_capture(monkeypatch, pid=777)

    r = _client().post('/api/strategy/start', json={
        'mode': 'se', 'minutes': 20, 'seed': 7, 'sizes': [28],
        'per_type': {'g01': {'d': 2.0}},
        'quantities': {'g01': {'28': 2, '30': 0}},
    })
    assert r.status_code == 202
    body = r.json()
    assert body['mode'] == 'se' and body['minutes'] == 20 and body['pid'] == 777

    # config JSON 落盘对拍：7 键（band 未传 → 不写键，与旧版结构一致）+
    # master_dxf 绝对路径。
    cfg_files = list(uploads.glob('strategy_cfg_*.json'))
    assert len(cfg_files) == 1
    cfg = json.loads(cfg_files[0].read_text(encoding='utf-8'))
    assert set(cfg) == {'master_dxf', 'sizes', 'gate_mm', 'time', 'seeds',
                        'per_type', 'quantities'}
    assert Path(cfg['master_dxf']).is_absolute()
    assert Path(cfg['master_dxf']) == master.resolve()
    assert cfg['gate_mm'] == 1980.0          # 请求未传 gate → 回退 state
    assert cfg['time'] == 1200
    assert cfg['seeds'] == [7]
    assert cfg['sizes'] == [28]
    assert cfg['per_type'] == {'g01': {'d': 2.0}}
    assert cfg['quantities'] == {'g01': {'28': 2, '30': 0}}

    # spawn cmd：run_config + --name web_se_* + --strategy se + --time 1200 + --quiet。
    cmd = calls['cmd']
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ['-m', 'materialsorting.cli.run_config']
    assert cmd[3] == str(cfg_files[0])
    assert cmd[cmd.index('--name') + 1].startswith('web_se_')
    assert cmd[cmd.index('--strategy') + 1] == 'se'
    assert cmd[cmd.index('--time') + 1] == '1200'
    assert cmd[-1] == '--quiet'

    # marker 5 键。
    marker = json.loads(
        strategy_mod._marker_path().read_text(encoding='utf-8'))
    assert set(marker) == {'pid', 'run_dir', 'doc_id', 'mode', 'started_at'}
    assert marker['pid'] == 777 and marker['doc_id'] == 'cafe1234'
    assert marker['mode'] == 'se' and marker['run_dir'] is None

    # 内存快照（result 组装 manifest 用同口径）。
    st = strategy_mod._STRATEGY_STATE
    assert st['state'] == 'starting' and st['pid'] == 777
    assert st['sizes'] == [28] and st['per_type'] == {'g01': {'d': 2.0}}
    assert st['quantities'] == {'g01': {'28': 2, '30': 0}}
    assert st['seed'] == 7 and st['gate_mm'] == 1980.0
    assert st['total_budget_sec'] == 1200
    assert len(st['pieces_snapshot']) == 3


# ---------------------------------------------------- band（2026-08-22 解除互斥）


def _band_start_env(monkeypatch, tmp_path):
    """band 用例公共环境：state（g01/g02 在场）+ uploads 母版 + spawn 打桩。"""
    _patch_state(monkeypatch, _fake_state(doc_id='cafe1234'))
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True)
    (uploads / 'cafe1234.dxf').write_bytes(b'DXF')
    _spawn_capture(monkeypatch, pid=778)
    return uploads


def test_start_band_written_into_config(strat_env, monkeypatch):
    """band 开启且合法 → config JSON 含 band 键（StartPayload 原形态）。"""
    uploads = _band_start_env(monkeypatch, strat_env)
    r = _client().post('/api/strategy/start', json={
        'mode': 'race', 'minutes': 10, 'band': {'enabled': True, 'label': 'g01'},
    })
    assert r.status_code == 202
    cfg = json.loads(
        list(uploads.glob('strategy_cfg_*.json'))[0].read_text(encoding='utf-8'))
    assert cfg['band'] == {'enabled': True, 'label': 'g01'}
    # 其余 7 键不受扰（time/seeds 由 minutes/seed 派生）。
    assert cfg['time'] == 600 and cfg['seeds'] == [0]


def test_start_band_null_and_disabled_not_written(strat_env, monkeypatch):
    """band=null / enabled=false → _parse_band 关闭 → config 不写 band 键。"""
    uploads = _band_start_env(monkeypatch, strat_env)
    c = _client()
    for i, band in enumerate((None, {'enabled': False, 'label': 'g01'})):
        if i:
            # 前一次 202 已置 starting + 写 marker → 手动清（单例闸门 / orphan 检查）。
            strategy_mod._STRATEGY_STATE['state'] = 'done'
            strategy_mod._clear_marker()
        assert c.post('/api/strategy/start', json={
            'mode': 'race', 'minutes': 10, 'band': band}).status_code == 202
        cfg = json.loads(
            sorted(uploads.glob('strategy_cfg_*.json'))[-1]
            .read_text(encoding='utf-8'))
        assert 'band' not in cfg


def test_start_band_invalid_400(strat_env, monkeypatch):
    """band 非法（坏 g 码 / 不存在于母版 / 数量全 0）→ 400 结构化 error，不 spawn config。"""
    uploads = _band_start_env(monkeypatch, strat_env)
    c = _client()
    # 坏 g 码
    r = c.post('/api/strategy/start', json={
        'mode': 'race', 'minutes': 10, 'band': {'enabled': True, 'label': 'waist'}})
    assert r.status_code == 400 and 'g 码' in r.json()['error']
    # 不存在于当前母版（pieces 只有 g01/g02）
    r = c.post('/api/strategy/start', json={
        'mode': 'race', 'minutes': 10, 'band': {'enabled': True, 'label': 'g05'}})
    assert r.status_code == 400 and '不存在' in r.json()['error']
    # 该 g 码 quantities 全 0（missing→1 反例：显式全 0）
    r = c.post('/api/strategy/start', json={
        'mode': 'race', 'minutes': 10, 'quantities': {'g01': {'28': 0, '30': 0}},
        'band': {'enabled': True, 'label': 'g01'}})
    assert r.status_code == 400 and '全为 0' in r.json()['error']
    # 全部被拒 → 无 config 落盘、无 marker。
    assert not list(uploads.glob('strategy_cfg_*.json'))
    assert strategy_mod._read_marker() is None


# ------------------------------------------- prefix（2026-08-25 解除互斥，band 同款）


def _prefix_qty_2plus2() -> dict:
    """g01/g02 各 size28 demand=2 —— _synthetic_pieces 两码均有 28 片 → 资格码 [28]。"""
    return {'g01': {'28': 2}, 'g02': {'28': 2}}


def test_start_prefix_written_into_config(strat_env, monkeypatch):
    """prefix 开启且合法（含 2+2 资格码）→ config JSON 含 prefix 键（原形态）。"""
    uploads = _band_start_env(monkeypatch, strat_env)
    r = _client().post('/api/strategy/start', json={
        'mode': 'race', 'minutes': 10, 'quantities': _prefix_qty_2plus2(),
        'prefix': {'enabled': True, 'front': 'g01', 'back': 'g02'},
    })
    assert r.status_code == 202
    cfg = json.loads(
        list(uploads.glob('strategy_cfg_*.json'))[0].read_text(encoding='utf-8'))
    assert cfg['prefix'] == {'enabled': True, 'front': 'g01', 'back': 'g02'}
    assert cfg['quantities'] == _prefix_qty_2plus2()


def test_start_prefix_null_and_disabled_not_written(strat_env, monkeypatch):
    """prefix=null / enabled=false → _parse_prefix 关闭 → config 不写 prefix 键。"""
    uploads = _band_start_env(monkeypatch, strat_env)
    c = _client()
    for i, prefix in enumerate((None, {'enabled': False, 'front': 'g01', 'back': 'g02'})):
        if i:
            strategy_mod._STRATEGY_STATE['state'] = 'done'
            strategy_mod._clear_marker()
        assert c.post('/api/strategy/start', json={
            'mode': 'race', 'minutes': 10, 'quantities': _prefix_qty_2plus2(),
            'prefix': prefix}).status_code == 202
        cfg = json.loads(
            sorted(uploads.glob('strategy_cfg_*.json'))[-1]
            .read_text(encoding='utf-8'))
        assert 'prefix' not in cfg


def test_start_prefix_invalid_400(strat_env, monkeypatch):
    """prefix 非法（坏 g 码 / 不存在 / front==back / 无 2+2 资格码）→ 400 不 spawn。"""
    uploads = _band_start_env(monkeypatch, strat_env)
    c = _client()
    qty = _prefix_qty_2plus2()
    # 坏 g 码
    r = c.post('/api/strategy/start', json={
        'mode': 'race', 'minutes': 10, 'quantities': qty,
        'prefix': {'enabled': True, 'front': 'front', 'back': 'g02'}})
    assert r.status_code == 400 and 'g 码' in r.json()['error']
    # 不存在于当前母版（pieces 只有 g01/g02）
    r = c.post('/api/strategy/start', json={
        'mode': 'race', 'minutes': 10, 'quantities': qty,
        'prefix': {'enabled': True, 'front': 'g01', 'back': 'g03'}})
    assert r.status_code == 400 and '不存在' in r.json()['error']
    # front == back
    r = c.post('/api/strategy/start', json={
        'mode': 'race', 'minutes': 10, 'quantities': qty,
        'prefix': {'enabled': True, 'front': 'g01', 'back': 'g01'}})
    assert r.status_code == 400 and '不同 g 码' in r.json()['error']
    # 无 2+2 资格码（demand=1 → 不合格；文案指路数量矩阵）
    r = c.post('/api/strategy/start', json={
        'mode': 'race', 'minutes': 10,
        'prefix': {'enabled': True, 'front': 'g01', 'back': 'g02'}})
    assert r.status_code == 400 and '资格码' in r.json()['error']
    # 资格码被 sizes 过滤掉（32 不在母版 → 资格码空）
    r = c.post('/api/strategy/start', json={
        'mode': 'race', 'minutes': 10, 'sizes': [30], 'quantities': qty,
        'prefix': {'enabled': True, 'front': 'g01', 'back': 'g02'}})
    assert r.status_code == 400 and '资格码' in r.json()['error']
    # 全部被拒 → 无 config 落盘、无 marker。
    assert not list(uploads.glob('strategy_cfg_*.json'))
    assert strategy_mod._read_marker() is None


def test_start_cleans_previous_web_artifacts(strat_env, monkeypatch):
    """start 通过闸门后清理上一轮 web 产物：web_* run 目录 / 旧 cfg / 旧 stderr
    临时文件全清；非 web_ 前缀目录（手工 ms-run-config run）不受影响（2026-08-22）。"""
    _patch_state(monkeypatch, _fake_state(doc_id='cafe1234'))
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True)
    (uploads / 'cafe1234.dxf').write_bytes(b'DXF')
    _spawn_capture(monkeypatch, pid=779)

    # 旧产物在场：web_ run 目录 + 手工 run 目录 + 旧 cfg + 旧 stderr 临时文件
    # （tempdir 指到 tmp_path，不触碰真实系统临时目录）。
    base = Path(paths_mod.CONFIG_RUNS_DIR)
    old_web = base / 'web_race_old_20260820-120000'
    manual = base / 'manual_20260820-130000'
    for d in (old_web, manual):
        d.mkdir(parents=True)
        (d / 'result.json').write_text('{}', encoding='utf-8')
    (uploads / 'strategy_cfg_20260801-000000.json').write_text('{}',
                                                               encoding='utf-8')
    tmpdir = Path(strategy_mod.tempfile.gettempdir())   # fixture 已隔离 tempdir
    (tmpdir / 'web_strategy_err_stale.log').write_text('boom', encoding='utf-8')

    r = _client().post('/api/strategy/start', json={'mode': 'race', 'minutes': 10})
    assert r.status_code == 202
    assert not old_web.exists()                     # web_ 前缀 run 目录被清
    assert manual.exists()                          # 手工 run 目录不受影响
    new_cfgs = list(uploads.glob('strategy_cfg_*.json'))
    assert len(new_cfgs) == 1                       # 只剩本轮新写的 cfg
    errs = list(tmpdir.glob('web_strategy_err_*.log'))
    assert len(errs) == 1                           # 只剩本轮 spawn 的 stderr


# ------------------------------------------------------------- status


def test_status_run_dir_discovery_and_plan(strat_env):
    """快照 diff 发现 run_dir（空快照 → CLI 建目录）→ running + plan 解析。"""
    st = _active_state(strat_env, run_dir=None, rc=None)   # starting，待发现
    st['snapshot'] = set()   # start 时刻 config_runs 尚无任何目录
    run_dir = _write_run_dir(strat_env, name='web_se_abc123_20260820-120000')

    payload = _client().get('/api/strategy/status').json()
    assert payload['state'] == 'running'
    assert payload['run_dir'] == str(run_dir)
    # se plan：planned_seeds + k_screens/screen_s/ext_s。
    assert payload['plan']['planned_seeds'] == [0, 1, 2]
    assert payload['plan']['k_screens'] == 3
    assert payload['plan']['screen_s'] == 90 and payload['plan']['ext_s'] == 180
    assert payload['mode'] == 'race' and payload['total_budget_sec'] == 600
    assert payload['elapsed_sec'] >= 0.0


def test_status_run_dir_discovery_writes_back_marker(strat_env, monkeypatch):
    """start 全流程：spawn 后 CLI 建目录 → status 发现 → marker.run_dir 回写。"""
    _patch_state(monkeypatch, _fake_state(doc_id='cafe1234'))
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True)
    (uploads / 'cafe1234.dxf').write_bytes(b'DXF')
    _spawn_capture(monkeypatch, pid=777)
    c = _client()
    assert c.post('/api/strategy/start',
                  json={'mode': 'race', 'minutes': 10}).status_code == 202
    assert c.get('/api/strategy/status').json()['state'] == 'starting'
    _write_run_dir(strat_env, name='web_race_ffff00_20260820-120500')
    payload = c.get('/api/strategy/status').json()
    assert payload['state'] == 'running'
    marker = strategy_mod._read_marker()
    assert marker is not None and marker['run_dir'] == payload['run_dir']


def test_status_discovery_timeout_error_stderr_tail(strat_env):
    """进程死 + run_dir 未发现（>30s 宽限）→ error + stderr 尾部 + 清 marker。"""
    st = _active_state(strat_env, run_dir=None, rc=1,
                       stderr_text='配置错误: master_dxf 不存在 boom')
    st['started_ts'] = time.time() - 40.0
    strategy_mod._write_marker({'pid': 4321, 'run_dir': None, 'doc_id': 'x',
                                'mode': 'race',
                                'started_at': time.strftime('%Y-%m-%dT%H:%M:%S')})
    payload = _client().get('/api/strategy/status').json()
    assert payload['state'] == 'error'
    assert 'run 目录' in payload['error'] and 'stderr 尾部' in payload['error']
    assert 'boom' in payload['error']
    assert payload['exit_code'] == 1
    assert strategy_mod._read_marker() is None       # 终态清 marker
    assert strategy_mod._STRATEGY_STATE['state'] == 'error'


def test_status_parses_fixture_run_dir_fields(strat_env):
    """fixture run_dir 逐字段：incumbent 摘要（无 placed_items）/ current（最新 mtime
    + ext 位）/ per_seed / events（R5 门杀 + extension + seed_done，非 R5 滤除）。"""
    run_dir = _write_run_dir(strat_env)
    _active_state(strat_env, run_dir=str(run_dir), rc=None)

    payload = _client().get('/api/strategy/status').json()
    assert payload['state'] == 'running'
    inc = payload['incumbent']
    assert inc == {'density': 0.88, 'width_mm': 7100.5, 'seed': 1,
                   'frame_index': 5, 'elapsed': 120.3}
    assert 'placed_items' not in inc                 # 控载荷
    cur = payload['current']
    assert cur['seed'] == 1 and cur['density'] == 0.88
    assert cur['ext'] is True and cur['density_sparrow'] == 0.92
    assert [e['seed'] for e in payload['per_seed']] == [0, 1]
    kinds = [e['kind'] for e in payload['events']]
    assert kinds.count('gate') == 2                  # R1 行被滤
    assert 'extension' in kinds and 'seed_done' in kinds
    gate_kill = [e for e in payload['events'] if e['kind'] == 'gate'
                 and e['would_kill']]
    assert gate_kill[0]['bar'] == 0.86               # S_tau 重载为 bar 参照值


def test_status_missing_files_degrade_null(strat_env):
    """run_dir 空（CLI 已建目录但尚无产物）+ 进程存活 → running，产物字段全降级。"""
    run_dir = Path(paths_mod.CONFIG_RUNS_DIR) / 'web_race_x_20260820-130000'
    run_dir.mkdir(parents=True)
    _active_state(strat_env, run_dir=str(run_dir), rc=None)
    payload = _client().get('/api/strategy/status').json()
    assert payload['state'] == 'running'
    assert payload['plan'] is None and payload['incumbent'] is None
    assert payload['current'] is None
    assert payload['per_seed'] == [] and payload['events'] == []
    assert payload['error'] is None and payload['exit_code'] is None


def test_status_done_retains_state_and_clears_marker(strat_env):
    """进程死 + result.json 在场 → done；marker 清、内存态保留（result 可读）。"""
    run_dir = _write_run_dir(strat_env)
    _active_state(strat_env, run_dir=str(run_dir), rc=0)
    strategy_mod._write_marker({'pid': 4321, 'run_dir': str(run_dir),
                                'doc_id': 'deadbeef01', 'mode': 'se',
                                'started_at': time.strftime('%Y-%m-%dT%H:%M:%S')})
    payload = _client().get('/api/strategy/status').json()
    assert payload['state'] == 'done' and payload['exit_code'] == 0
    assert strategy_mod._read_marker() is None
    assert strategy_mod._STRATEGY_STATE['state'] == 'done'
    # done 后再 start 不再 409（终态放行；marker 已清）。


# ------------------------------------------------------------- stop / orphan


def test_stop_taskkill_tree_and_marker_cleanup(strat_env, monkeypatch):
    """stop：Windows taskkill /PID <pid> /T /F 树杀 + 置 stopped + 清 marker。"""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))

    monkeypatch.setattr(strategy_mod.subprocess, 'run', fake_run)
    _active_state(strat_env, run_dir=None, rc=None)
    strategy_mod._write_marker({'pid': 4321, 'run_dir': None, 'doc_id': 'x',
                                'mode': 'race',
                                'started_at': time.strftime('%Y-%m-%dT%H:%M:%S')})
    r = _client().post('/api/strategy/stop')
    assert r.status_code == 200 and r.json()['stopped'] is True
    if sys.platform == 'win32':
        assert calls == [['taskkill', '/PID', '4321', '/T', '/F']]
    assert strategy_mod._read_marker() is None
    assert strategy_mod._STRATEGY_STATE['state'] == 'stopped'
    # stopped 后 status 稳定报 stopped。
    payload = _client().get('/api/strategy/status').json()
    assert payload['state'] == 'stopped'


def test_orphan_marker_with_empty_memory(strat_env, monkeypatch):
    """内存态空 + marker 在 → orphan（pid 存活探测）；stop 清理。"""
    monkeypatch.setattr(strategy_mod, '_pid_alive', lambda pid: False)
    run_dir = _write_run_dir(strat_env)
    strategy_mod._write_marker({'pid': 555, 'run_dir': str(run_dir),
                                'doc_id': 'old0', 'mode': 'se',
                                'started_at': '2026-08-20T11:00:00'})
    payload = _client().get('/api/strategy/status').json()
    assert payload['state'] == 'orphan'
    assert payload['alive'] is False and payload['pid'] == 555
    assert payload['mode'] == 'se' and payload['doc_id'] == 'old0'
    assert payload['elapsed_sec'] >= 0.0            # started_at 解析成功
    # 孤儿态仍解析产物（run_dir 在 marker 带回）。
    assert payload['plan']['k_screens'] == 3

    r = _client().post('/api/strategy/stop')
    assert r.status_code == 200 and r.json()['orphan'] is True
    assert strategy_mod._read_marker() is None
    assert _client().get('/api/strategy/status').json()['state'] == 'idle'


# ------------------------------------------------------------- result


def test_result_manifest_parity_with_build_pid_meta(strat_env, monkeypatch):
    """提取回归护栏：result manifest.pieces 与 build_pid_meta 逐字段对拍 +
    build_instance pid_meta/total_area/n_eroded 三元组与 build_pid_meta 一致。"""
    from materialsorting.web.solver import build_pid_meta, build_instance
    run_dir = _write_run_dir(strat_env)
    st = _active_state(strat_env, run_dir=str(run_dir), rc=0)
    st['state'] = 'done'
    st['per_type'] = {'g01': {'d': 2.0}}
    st['quantities'] = {'g01': {'28': 2, '30': 0}}
    _patch_state(monkeypatch, _fake_state(doc_id='deadbeef01'))

    payload = _client().get('/api/strategy/result').json()
    assert payload['state'] == 'done'
    # best：incumbent 全量 + density_sparrow 从 best_frame 边车补。
    assert payload['best']['seed'] == 1 and payload['best']['density'] == 0.88
    assert payload['best']['density_sparrow'] == 0.9 or \
        payload['best']['density_sparrow'] is None   # 边车缺该 seed 时降级
    assert payload['best']['placed_items'] == [{'id': 'g01_28', 'rotation': 0.0,
                                                'translation': [1.0, 2.0]}]
    assert 'warning' not in payload                  # doc_id 未漂移

    # manifest 对拍 build_pid_meta（同口径 sizes/per_type/quantities）。
    pid_meta, total_area, n_eroded = build_pid_meta(
        st['pieces_snapshot'], sizes=st['sizes'], per_type=st['per_type'],
        quantities=st['quantities'])
    pieces = {p['id']: p for p in payload['manifest']['pieces']}
    assert set(pieces) == set(pid_meta)
    for pid, meta in pid_meta.items():
        got = pieces[pid]
        assert got['color'] == meta['color']
        assert got['polygon'] == meta['polygon']      # erode 后几何与 placement 对齐
        assert got['demand'] == meta['demand']
        assert got['label'] == meta['label']
    assert payload['manifest']['total_area_mm2'] == total_area
    assert payload['manifest']['n_eroded'] == n_eroded
    assert payload['manifest']['gate_nest_mm'] == 1910.0

    # build_instance 输出一致性（提取前后口径不变 → 三元组与 build_pid_meta 相同）。
    _inst, _cfg, meta2, area2, eroded2 = build_instance(
        st['pieces_snapshot'], 1980.0, time_budget=1, seed=0,
        per_type=st['per_type'], quantities=st['quantities'])
    assert meta2 == pid_meta and area2 == total_area and eroded2 == n_eroded

    # summary：per_seed + mode 段透传。
    assert payload['summary']['mode'] == 'se'
    assert [e['seed'] for e in payload['summary']['per_seed']] == [0, 1]


def test_result_doc_id_drift_warning(strat_env, monkeypatch):
    """start 快照 doc_id ≠ 当前画布 doc_id → warning（母版漂移提示）。"""
    run_dir = _write_run_dir(strat_env)
    st = _active_state(strat_env, run_dir=str(run_dir), rc=0)
    st['state'] = 'done'
    _patch_state(monkeypatch, _fake_state(doc_id='newmaster99'))
    payload = _client().get('/api/strategy/result').json()
    assert payload['warning'] == '母版已变更，应用结果可能与当前画布不一致'


def test_result_stopped_falls_back_to_best_frames(strat_env):
    """stopped 且无 result.json（首轮未完成）→ 各 best_frame 取 density 最大。"""
    run_dir = Path(paths_mod.CONFIG_RUNS_DIR) / 'web_race_x_20260820-140000'
    run_dir.mkdir(parents=True)
    for seed, dens in ((0, 0.80), (1, 0.85)):
        (run_dir / f'best_frame_s{seed}.json').write_text(json.dumps({
            'seed': seed, 'frame_index': 2, 'elapsed': 10.0, 'phase': 'exploring',
            'density': dens, 'density_sparrow': dens + 0.02, 'width_mm': 8000.0,
            'n_placed': 3, 'placed_items': [
                {'id': f'g0{seed + 1}_28', 'rotation': 0.0,
                 'translation': [0.0, 0.0]}]}), encoding='utf-8')
    st = _active_state(strat_env, run_dir=str(run_dir), rc=1)
    st['stopped'] = True
    st['state'] = 'stopped'
    payload = _client().get('/api/strategy/result').json()
    assert payload['state'] == 'stopped'
    assert payload['best']['seed'] == 1 and payload['best']['density'] == 0.85
    assert payload['best']['density_sparrow'] == 0.87


def test_result_rejects_idle_and_running(strat_env):
    """idle → 404；running → 409（运行尚未结束）。"""
    assert _client().get('/api/strategy/result').status_code == 404
    _active_state(strat_env, run_dir=None, rc=None)
    r = _client().get('/api/strategy/result')
    assert r.status_code == 409 and '尚未结束' in r.json()['error']


# --------------------------------------------------- US-004 多会话（2026-08-27）

SID_A = 'aaaa1111'
SID_B = 'bbbb2222'


@pytest.fixture
def dual_env(strat_env):
    """双会话环境：strat_env 之上隔离 SessionRegistry（停扫描 + 前后清零，套路同
    tests/test_commit_sessions.py）+ 清 ``_STRATEGY_STATES`` 每会话策略状态槽。"""
    sessions_mod.registry.stop_scanner()
    sessions_mod.registry.reset()
    strategy_mod._STRATEGY_STATES.clear()
    yield strat_env
    strategy_mod._STRATEGY_STATES.clear()
    sessions_mod.registry.reset()


def _register_session(sid: str, doc_id: str) -> None:
    """注册会话并注入排料快照（start 的数据源）+ 落 master dxf（422 校验输入）。"""
    sess = sessions_mod.registry.resolve(sid, create=True)
    sess.state.update(_fake_state(doc_id=doc_id))
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / f'{doc_id}.dxf').write_bytes(b'DXF')


def _spawn_capture_multi(monkeypatch, pids=(1111, 2222)):
    """spawn 打桩（多轮）：每轮返回下一个 pid，逐轮记录 cmd + stderr 路径。"""
    calls = []
    pids_iter = iter(pids)

    def fake_spawn(cmd, stderr_path):
        calls.append({'cmd': list(cmd), 'stderr_path': stderr_path})
        return FakeProc(pid=next(pids_iter))

    monkeypatch.setattr(strategy_mod, '_spawn_run_process', fake_spawn)
    return calls


def test_dual_session_start_and_status_isolated(dual_env, monkeypatch):
    """AC1/AC2：A、B 先后 start 均 202（跨会话不 409）；run_name 嵌 sid 短缀；
    status 前缀 glob 认领各自 run_dir（B 目录 mtime 更新也不串台——不依赖 mtime）。"""
    _register_session(SID_A, 'docaaaa1')
    _register_session(SID_B, 'docbbbb2')
    calls = _spawn_capture_multi(monkeypatch, pids=(1111, 2222))
    c = _client()
    ra = c.post('/api/strategy/start', json={'mode': 'se', 'minutes': 10},
                headers={'X-Session-Id': SID_A})
    assert ra.status_code == 202
    rb = c.post('/api/strategy/start', json={'mode': 'race', 'minutes': 10},
                headers={'X-Session-Id': SID_B})
    assert rb.status_code == 202                    # A in-flight 不拦 B（每会话闸门）
    name_a, name_b = ra.json()['run_name'], rb.json()['run_name']
    assert name_a.startswith('web_aaaa11_se_')
    assert name_b.startswith('web_bbbb22_race_')
    assert calls[0]['cmd'][calls[0]['cmd'].index('--name') + 1] == name_a
    assert calls[1]['cmd'][calls[1]['cmd'].index('--name') + 1] == name_b

    # 各自 run_dir：B 的目录 mtime 更新（旧「diff + mtime」口径 A 会误认领 B 的）。
    dir_a = _write_run_dir(dual_env, name=f'{name_a}_20260827-100000')
    time.sleep(0.01)
    dir_b = _write_run_dir(dual_env, name=f'{name_b}_20260827-100001')
    rj = json.loads((dir_b / 'result.json').read_text(encoding='utf-8'))
    rj['portfolio']['incumbent']['density'] = 0.91   # B 档可区分密度
    (dir_b / 'result.json').write_text(json.dumps(rj), encoding='utf-8')

    pa = c.get('/api/strategy/status', headers={'X-Session-Id': SID_A}).json()
    pb = c.get('/api/strategy/status', headers={'X-Session-Id': SID_B}).json()
    assert pa['state'] == 'running' and pa['run_dir'] == str(dir_a)
    assert pb['state'] == 'running' and pb['run_dir'] == str(dir_b)
    assert pa['incumbent']['density'] == 0.88        # A 读 A 的产物
    assert pb['incumbent']['density'] == 0.91        # B 读 B 的产物
    # marker / 状态槽各归各（互不串台）。
    assert strategy_mod._read_marker(SID_A)['pid'] == 1111
    assert strategy_mod._read_marker(SID_B)['pid'] == 2222
    assert strategy_mod._states(SID_A)['doc_id'] == 'docaaaa1'
    assert strategy_mod._states(SID_B)['doc_id'] == 'docbbbb2'


def test_cleanup_scoped_to_own_sid_prefix(dual_env, monkeypatch):
    """AC3：B start 只清 web_<B_sid6>_* 前缀产物（A 的 run 目录/cfg/stderr 保留）；
    default start 清 legacy web_* 但保护并行会话前缀（含终态 result 复读窗口）。"""
    _register_session(SID_A, 'docaaaa1')
    _register_session(SID_B, 'docbbbb2')
    _spawn_capture_multi(monkeypatch, pids=(1111, 2222, 3333))
    base = Path(paths_mod.CONFIG_RUNS_DIR)
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    legacy = base / 'web_race_legacy_20260827-080000'   # 无 sid 旧产物
    manual = base / 'manual_20260827-070000'            # 手工 CLI run
    for d in (legacy, manual):
        d.mkdir(parents=True)
        (d / 'result.json').write_text('{}', encoding='utf-8')
    cfg_legacy = uploads / 'strategy_cfg_20260827-080000.json'
    cfg_legacy.write_text('{}', encoding='utf-8')
    tmpdir = Path(strategy_mod.tempfile.gettempdir())
    err_legacy = tmpdir / 'web_strategy_err_stale.log'
    err_legacy.write_text('x', encoding='utf-8')

    c = _client()
    # A start（A 在册 → 之后一切清理跳过 web_aaaa11_* 前缀）。
    assert c.post('/api/strategy/start', json={'mode': 'se', 'minutes': 10},
                  headers={'X-Session-Id': SID_A}).status_code == 202
    cfg_a = list(uploads.glob('strategy_cfg_aaaa11_*.json'))[0]
    err_a = list(tmpdir.glob('web_strategy_err_aaaa11_*.log'))[0]
    dir_a = base / f"{strategy_mod._states(SID_A)['run_name']}_20260827-090000"
    dir_a.mkdir(parents=True)
    (dir_a / 'result.json').write_text('{}', encoding='utf-8')
    dir_b = base / 'web_bbbb22_race_222222_20260827-090500'
    dir_b.mkdir(parents=True)
    (dir_b / 'result.json').write_text('{}', encoding='utf-8')

    # B start：只清 B 前缀（dir_b 没了；A 的 dir/cfg/err 与 legacy 均保留）。
    assert c.post('/api/strategy/start', json={'mode': 'race', 'minutes': 10},
                  headers={'X-Session-Id': SID_B}).status_code == 202
    assert not dir_b.exists()
    assert dir_a.exists() and cfg_a.exists() and err_a.exists()
    assert legacy.exists() and cfg_legacy.exists()      # sid 会话不清 legacy
    assert manual.exists()

    # default start：清 legacy web_*/旧名 cfg/err，但保护 A/B 的 sid 前缀产物。
    _patch_state(monkeypatch, _fake_state(doc_id='cafe1234'))
    (uploads / 'cafe1234.dxf').write_bytes(b'DXF')
    assert c.post('/api/strategy/start',
                  json={'mode': 'race', 'minutes': 10}).status_code == 202
    assert not legacy.exists() and not cfg_legacy.exists() and not err_legacy.exists()
    assert manual.exists()
    assert dir_a.exists() and cfg_a.exists() and err_a.exists()   # A 前缀受保护


def test_stop_and_result_scoped_per_session(dual_env, monkeypatch):
    """AC4：A stop 只树杀 A 的 pid（B 的 run/marker 不受影响）；A result 只读 A 的
    run_dir；B running → result 409。"""
    _register_session(SID_A, 'docaaaa1')
    _register_session(SID_B, 'docbbbb2')
    _spawn_capture_multi(monkeypatch, pids=(1111, 2222))
    kill_calls = []
    monkeypatch.setattr(strategy_mod.subprocess, 'run',
                        lambda cmd, **kw: kill_calls.append(list(cmd)))
    c = _client()
    ra = c.post('/api/strategy/start', json={'mode': 'se', 'minutes': 10},
                headers={'X-Session-Id': SID_A})
    assert c.post('/api/strategy/start', json={'mode': 'race', 'minutes': 10},
                  headers={'X-Session-Id': SID_B}).status_code == 202
    name_a = ra.json()['run_name']

    # A stop：只杀 A 的 pid 1111；B 的 marker 与 running 态原封不动。
    r = c.post('/api/strategy/stop', headers={'X-Session-Id': SID_A})
    assert r.status_code == 200 and r.json() == {'stopped': True, 'pid': 1111}
    if sys.platform == 'win32':
        assert kill_calls == [['taskkill', '/PID', '1111', '/T', '/F']]
    assert strategy_mod._read_marker(SID_B)['pid'] == 2222
    assert c.get('/api/strategy/status',
                 headers={'X-Session-Id': SID_B}).json()['state'] == 'starting'

    # A result：直装 done + A 的 run_dir → 读 A 的产物；B 仍在跑 → 409。
    dir_a = _write_run_dir(dual_env, name=f'{name_a}_20260827-110000')
    st_a = strategy_mod._states(SID_A)
    st_a['run_dir'] = str(dir_a)
    st_a['state'] = 'done'
    pa = c.get('/api/strategy/result', headers={'X-Session-Id': SID_A}).json()
    assert pa['state'] == 'done' and pa['run_dir'] == str(dir_a)
    assert pa['best']['density'] == 0.88
    rb = c.get('/api/strategy/result', headers={'X-Session-Id': SID_B})
    assert rb.status_code == 409 and '尚未结束' in rb.json()['error']


def test_same_sid_second_start_409_cross_session_ok(dual_env, monkeypatch):
    """AC5：同 sid 二次 start（前场未终态）→ 409；跨会话（B / default）不 409；
    会话闸门 fail-fast：未知 sid → 401、非法 sid → 400（不 spawn）。"""
    _register_session(SID_A, 'docaaaa1')
    _register_session(SID_B, 'docbbbb2')
    calls = _spawn_capture_multi(monkeypatch, pids=(1111, 2222, 3333))
    c = _client()
    ha = {'X-Session-Id': SID_A}
    assert c.post('/api/strategy/start', json={'mode': 'se', 'minutes': 10},
                  headers=ha).status_code == 202
    assert c.post('/api/strategy/start', json={'mode': 'se', 'minutes': 10},
                  headers=ha).status_code == 409       # 同 sid 二次 → 409
    assert c.post('/api/strategy/start', json={'mode': 'race', 'minutes': 10},
                  headers={'X-Session-Id': SID_B}).status_code == 202
    # default 会话（零 sid）与 sid 会话互不 409。
    _patch_state(monkeypatch, _fake_state(doc_id='cafe1234'))
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / 'cafe1234.dxf').write_bytes(b'DXF')
    assert c.post('/api/strategy/start',
                  json={'mode': 'race', 'minutes': 10}).status_code == 202
    # 闸门先于一切：未知 sid → 401（code 键）；非法 sid → 400；均不 spawn。
    n = len(calls)
    r = c.post('/api/strategy/start', json={'mode': 'se', 'minutes': 10},
               headers={'X-Session-Id': 'cccc3333'})
    assert r.status_code == 401 and r.json()['code'] == 'session_expired'
    r = c.post('/api/strategy/start', json={'mode': 'se', 'minutes': 10},
               headers={'X-Session-Id': 'bad-sid!'})
    assert r.status_code == 400 and r.json() == {'error': 'sid 非法'}
    assert len(calls) == n


def test_orphan_scoped_per_sid_marker(dual_env, monkeypatch):
    """orphan 检测按本 sid marker：A 的 marker 在（内存空）→ A orphan / B idle；
    B stop 400（B 视角无 run）；A stop 清理自己的 marker。"""
    _register_session(SID_A, 'docaaaa1')
    _register_session(SID_B, 'docbbbb2')
    monkeypatch.setattr(strategy_mod, '_pid_alive', lambda pid: False)
    strategy_mod._write_marker({'pid': 999, 'run_dir': None, 'doc_id': 'old0',
                                'mode': 'se',
                                'started_at': '2026-08-27T11:00:00'}, SID_A)
    c = _client()
    pa = c.get('/api/strategy/status', headers={'X-Session-Id': SID_A}).json()
    assert pa['state'] == 'orphan' and pa['pid'] == 999 and pa['doc_id'] == 'old0'
    pb = c.get('/api/strategy/status', headers={'X-Session-Id': SID_B}).json()
    assert pb['state'] == 'idle'                        # B 无 marker 不串台
    assert c.post('/api/strategy/stop',
                  headers={'X-Session-Id': SID_B}).status_code == 400
    r = c.post('/api/strategy/stop', headers={'X-Session-Id': SID_A})
    assert r.status_code == 200 and r.json()['orphan'] is True
    assert strategy_mod._read_marker(SID_A) is None
    assert c.get('/api/strategy/status',
                 headers={'X-Session-Id': SID_A}).json()['state'] == 'idle'


def test_expired_session_blocks_then_same_sid_recovers(dual_env, monkeypatch):
    """会话过期 → 四路由 401 fail-fast（闸门先于 409）；墓碑 1h 过龄后同 sid 重建
    → 内存态仍在（本进程未重启）→ status 继续 starting、stop 可清理（PRD「用户
    过期后同 sid 回来仍能发现/清理自己的遗留 run」）。"""
    clk = _FakeClock()
    monkeypatch.setattr(sessions_mod.registry, 'clock', clk)
    _register_session(SID_A, 'docaaaa1')
    _spawn_capture_multi(monkeypatch, pids=(1111,))
    kill_calls = []
    monkeypatch.setattr(strategy_mod.subprocess, 'run',
                        lambda cmd, **kw: kill_calls.append(list(cmd)))
    c = _client()
    ha = {'X-Session-Id': SID_A}
    assert c.post('/api/strategy/start', json={'mode': 'se', 'minutes': 10},
                  headers=ha).status_code == 202
    assert strategy_mod._read_marker(SID_A)['pid'] == 1111

    # 过期（惰性逐出为墓碑）：四路由全部 401（start 的 401 证明闸门先于 409 ——
    # 此刻内存态 starting 本会 409）。
    clk.advance(sessions_mod.registry.ttl_sec + 1)
    assert c.get('/api/strategy/status', headers=ha).status_code == 401
    assert c.post('/api/strategy/start', json={'mode': 'se', 'minutes': 10},
                  headers=ha).status_code == 401
    assert c.post('/api/strategy/stop', headers=ha).status_code == 401
    assert c.get('/api/strategy/result', headers=ha).status_code == 401

    # 墓碑 1h 过龄 → 同 sid 可重建（POST /api/session）；策略状态槽未随会话逐出
    # 清理 → status 直接回到 starting（内存态优先于 marker 的 orphan 路径），
    # stop 清理成功。
    clk.advance(sessions_mod.registry.tombstone_ttl_sec + 1)
    assert c.post('/api/session', headers=ha).status_code == 200
    pa = c.get('/api/strategy/status', headers=ha).json()
    assert pa['state'] == 'starting'
    r = c.post('/api/strategy/stop', headers=ha)
    assert r.status_code == 200 and r.json()['pid'] == 1111
    assert strategy_mod._read_marker(SID_A) is None


# ------------------------------------------------------------- 守卫 / 冒烟


def test_ast_guard_strategy_no_cli_import():
    """分层守卫：web/strategy.py 全模块（含函数内）不 import cli —— spawn 是进程
    边界而非 import 边界（镜像 test_cli_portfolio.py AST 写法）。"""
    src = Path(strategy_mod.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parts = [p for p in (node.module or '').split('.') if p]
            assert 'cli' not in parts, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert 'cli' not in alias.name.split('.'), alias.name


def test_web_app_strategy_routes_present():
    """ms-web 四路由在场（TestClient 探测 status → idle 200）。"""
    with TestClient(server_mod.app) as client:
        r = client.get('/api/strategy/status')
        assert r.status_code == 200
        assert r.json()['state'] in ('idle', 'orphan')
        paths = {route.path for route in server_mod.app.routes
                 if hasattr(route, 'path')}
        assert {'/api/strategy/start', '/api/strategy/status',
                '/api/strategy/stop', '/api/strategy/result'} <= paths


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

