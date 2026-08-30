"""US-002 web 极限运行四路由测试（/api/extreme/start|status|stop|result）。

覆盖（spec AC）：
  - start 202 契约：time_total_s → cfg.time / spawn cmd 尾部 --extreme --time <T>
    --quiet / run_name web_extreme_* / marker 5 键 mode='extreme' / 响应体
    {started, pid, mode:'extreme', run_name, time_total_s} / 状态槽 mode +
    total_budget_sec（载荷未带 band/prefix → config 无该键）；
  - time_total_s 四种 400：缺省 / 非整数（字符串·非整浮点·bool） / <905 / >43200；
  - band/prefix 2026-08-30 起与策略族同路径透传（范本 test_web_strategy 同名三
    例）：合法开启 → config 写键 + spawn cmd 尾不变；null / enabled=false → 不写
    键；非法（坏 g 码 / 不存在于母版 / 数量全 0 / front==back / 无 2+2 资格码）→
    400 结构化早退不 spawn；
  - 单飞互斥双向：strategy running → extreme 409（文案点名「策略运行」）；
    extreme running → strategy 409（点名「极限运行」）；跨会话不 409；
  - status/result/stop 同构：starting → running（web_extreme_* 前缀 glob 发现）
    / stop 树杀清 marker / result best+manifest+漂移 warning + 404/409 极限文案；
  - sid 语义同 strategy：未知 → 401 code=session_expired、非法 → 400（不 spawn）；
  - 产物清理按会话前缀隔离：本会话 web_<sid6>_extreme_* 旧 run 被清、他会有
    run 保留。

AST 守卫（strategy.py 禁 import ..cli.*）由 test_web_strategy.py 存量例持续覆盖
（本故事改动同一模块）。所有用例隔离 paths.CONFIG_RUNS_DIR / OUT_DIR 到 tmp_path；
spawn 走 FakeProc 不真起 CLI 子进程。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from materialsorting import paths as paths_mod
from materialsorting.web import strategy as strategy_mod
from materialsorting.web import server as server_mod
from materialsorting.web import sessions as sessions_mod


# ------------------------------------------------------------- 测试基础设施


class FakeProc:
    """Popen 替身：poll() 返回预置 rc（None = 存活）。"""

    def __init__(self, pid: int = 4321, rc=None):
        self.pid = pid
        self._rc = rc

    def poll(self):
        return self._rc


def _synthetic_pieces() -> list[dict]:
    """合成 3 片（与 test_web_strategy 同 schema v2，self-contained 不跨文件 import）。"""
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
    """隔离环境（套路同 test_web_strategy.strat_env）：CONFIG_RUNS_DIR / OUT_DIR /
    tempfile.tempdir 指到 tmp_path + default 状态槽清零。"""
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(tmp_path / 'config_runs'))
    monkeypatch.setattr(paths_mod, 'OUT_DIR', str(tmp_path / 'out'))
    tmp_dir = tmp_path / 'tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(strategy_mod.tempfile, 'tempdir', str(tmp_dir))
    strategy_mod._STRATEGY_STATE.clear()
    yield tmp_path
    strategy_mod._STRATEGY_STATE.clear()


SID_A = 'aaaa1111'
SID_B = 'bbbb2222'


@pytest.fixture
def dual_env(strat_env):
    """双会话环境（套路同 test_web_strategy.dual_env）。"""
    sessions_mod.registry.stop_scanner()
    sessions_mod.registry.reset()
    strategy_mod._STRATEGY_STATES.clear()
    yield strat_env
    strategy_mod._STRATEGY_STATES.clear()
    sessions_mod.registry.reset()


def _patch_state(monkeypatch, state: dict | None):
    monkeypatch.setattr(strategy_mod, '_pieces_state', lambda: state)


def _default_start_env(monkeypatch, doc_id='cafe1234'):
    """default 会话 start 前置：fake pieces state + uploads 母版在盘。"""
    _patch_state(monkeypatch, _fake_state(doc_id=doc_id))
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / f'{doc_id}.dxf').write_bytes(b'DXF')


def _spawn_capture(monkeypatch, pids=(4321,)):
    """打桩 spawn：逐轮记录 cmd + stderr 路径，返回逐轮 FakeProc。"""
    calls = []
    pids_iter = iter(pids)

    def fake_spawn(cmd, stderr_path):
        calls.append({'cmd': list(cmd), 'stderr_path': stderr_path})
        return FakeProc(pid=next(pids_iter))

    monkeypatch.setattr(strategy_mod, '_spawn_run_process', fake_spawn)
    return calls


def _register_session(sid: str, doc_id: str) -> None:
    """注册会话并注入排料快照 + 落 master dxf。"""
    sess = sessions_mod.registry.resolve(sid, create=True)
    sess.state.update(_fake_state(doc_id=doc_id))
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / f'{doc_id}.dxf').write_bytes(b'DXF')


def _write_run_dir(tmp_path: Path, name='web_extreme_abc123_20260829-120000') -> Path:
    """合成已完成 seed 0/1 的 extreme run_dir（strategy.json race 档 + result +
    best_frame 边车 + kill_decisions —— --extreme 内部展开 race 门杀，产物同构）。"""
    run_dir = Path(paths_mod.CONFIG_RUNS_DIR) / name
    run_dir.mkdir(parents=True)
    (run_dir / 'strategy.json').write_text(json.dumps({
        'mode': 'race', 'total_budget': 14400, 'planned_seeds': [0, 1, 2],
        'started_at': '2026-08-29T12:00:00',
        'race': {'gate_seconds': 300, 'budget': 600},
    }), encoding='utf-8')
    (run_dir / 'result.json').write_text(json.dumps({
        'portfolio': {
            'mode': 'race',
            'incumbent': {'density': 0.91, 'width_mm': 7100.5, 'seed': 1,
                          'frame_index': 5, 'elapsed': 620.3,
                          'placed_items': [{'id': 'g01_28', 'rotation': 0.0,
                                            'translation': [1.0, 2.0]}]},
            'per_seed': [
                {'seed': 0, 'killed': True, 'kill_reason': 'race_gate',
                 'best_density': 0.89, 'elapsed': 302.5, 'phase': 'gate'},
                {'seed': 1, 'killed': False, 'kill_reason': None,
                 'best_density': 0.91, 'elapsed': 600.0, 'phase': 'full'},
            ],
        },
    }), encoding='utf-8')
    (run_dir / 'best_frame_s0.json').write_text(json.dumps({
        'seed': 0, 'frame_index': 3, 'elapsed': 300.0, 'phase': 'compression',
        'density': 0.89, 'density_sparrow': 0.92, 'width_mm': 7300.0,
        'n_placed': 3, 'placed_items': []}), encoding='utf-8')
    time.sleep(0.01)   # 保证 s1 边车 mtime 更新（current 取最新）
    (run_dir / 'best_frame_s1.json').write_text(json.dumps({
        'seed': 1, 'frame_index': 5, 'elapsed': 620.3, 'phase': 'compression',
        'density': 0.91, 'density_sparrow': 0.94, 'width_mm': 7100.5,
        'n_placed': 3, 'placed_items': []}), encoding='utf-8')
    (run_dir / 'kill_decisions.jsonl').write_text('\n'.join([
        json.dumps({'t': 300.1, 'seed': 0, 'rule': 'R5_race_gate', 'd': 0.89,
                    'tau': 0.5, 'S_tau': 0.9, 'would_kill': True}),
    ]) + '\n', encoding='utf-8')
    return run_dir


def _extreme_state(tmp_path: Path, run_dir: str | None = None, rc=None,
                   total=14400) -> dict:
    """直装 extreme 内存态（status/result 解析用，不走 start 全流程）。"""
    stderr_path = tmp_path / 'stderr.log'
    stderr_path.write_text('x', encoding='utf-8')
    st = {
        'state': 'running', 'proc': FakeProc(pid=4321, rc=rc), 'pid': 4321,
        'mode': 'extreme', 'minutes': None, 'total_budget_sec': total,
        'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'started_ts': time.time(), 'run_dir': run_dir,
        'snapshot': set(), 'stderr_path': str(stderr_path),
        'doc_id': 'deadbeef01', 'pieces_snapshot': _synthetic_pieces(),
        'sizes': None, 'per_type': None, 'quantities': None,
        'gate_mm': 1980.0, 'seed': 0, 'cfg_path': 'cfg.json',
        'run_name': 'web_extreme_abc123', 'stopped': False,
        'exit_code': None, 'error': None,
    }
    strategy_mod._STRATEGY_STATE.clear()
    strategy_mod._STRATEGY_STATE.update(st)
    return strategy_mod._STRATEGY_STATE


def _client() -> TestClient:
    return TestClient(server_mod.app)


# ------------------------------------------------------------- start 契约


def test_extreme_start_happy_path_202(strat_env, monkeypatch):
    """202 契约：config 7 键（无 band/prefix）+ spawn cmd 尾部 --extreme --time <T>
    --quiet + run_name/marker/状态槽 mode='extreme' + 响应体含 time_total_s。"""
    _default_start_env(monkeypatch)
    calls = _spawn_capture(monkeypatch, pids=(777,))
    r = _client().post('/api/extreme/start', json={
        'time_total_s': 14400, 'seed': 3, 'gate_mm': 1500.0, 'sizes': [28],
        'per_type': {'g01': {'d': 2.0}},
        'quantities': {'g01': {'28': 2, '30': 0}},
    })
    assert r.status_code == 202
    body = r.json()
    assert body['started'] is True and body['pid'] == 777
    assert body['mode'] == 'extreme' and body['time_total_s'] == 14400
    run_name = body['run_name']
    assert run_name.startswith('web_extreme_')

    # config JSON：7 键（master_dxf/gate_mm/time/seeds + sizes/per_type/quantities，
    # 无 band/prefix 键）+ master_dxf 绝对路径 + gate_mm 请求值优先。
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    cfg_files = list(uploads.glob('strategy_cfg_*.json'))
    assert len(cfg_files) == 1
    cfg = json.loads(cfg_files[0].read_text(encoding='utf-8'))
    assert set(cfg) == {'master_dxf', 'sizes', 'gate_mm', 'time', 'seeds',
                        'per_type', 'quantities'}
    assert Path(cfg['master_dxf']).is_absolute()
    assert cfg['time'] == 14400 and cfg['seeds'] == [3]
    assert cfg['gate_mm'] == 1500.0
    assert cfg['sizes'] == [28]

    # spawn cmd：--extreme --time 14400 --quiet 收尾（无 --strategy 段）。
    cmd = calls[0]['cmd']
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ['-m', 'materialsorting.cli.run_config']
    assert cmd[3] == str(cfg_files[0])
    assert cmd[cmd.index('--name') + 1] == run_name
    assert '--strategy' not in cmd
    assert cmd[cmd.index('--extreme') + 1] == '--time'
    assert cmd[cmd.index('--time') + 1] == '14400'
    assert cmd[-1] == '--quiet'

    # marker 5 键（mode='extreme'）+ 状态槽快照。
    marker = json.loads(
        strategy_mod._marker_path().read_text(encoding='utf-8'))
    assert set(marker) == {'pid', 'run_dir', 'doc_id', 'mode', 'started_at'}
    assert marker['mode'] == 'extreme' and marker['pid'] == 777
    st = strategy_mod._STRATEGY_STATE
    assert st['state'] == 'starting' and st['mode'] == 'extreme'
    assert st['total_budget_sec'] == 14400 and st['minutes'] is None
    assert st['run_name'] == run_name


def test_extreme_time_total_s_four_400(strat_env, monkeypatch):
    """time_total_s 四种 400：缺省 / 非整数（字符串·非整浮点·bool） / <905 /
    >43200；全部不落 config / 不写 marker / 不 spawn。"""
    _default_start_env(monkeypatch)
    calls = _spawn_capture(monkeypatch, pids=(777,) * 8)
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    c = _client()
    cases = [
        {},                                       # 缺省
        {'time_total_s': '14400'},                # 非整数：字符串
        {'time_total_s': 14400.5},                # 非整数：非整浮点
        {'time_total_s': True},                   # 非整数：bool（int 子类须拒）
        {'time_total_s': None},                   # 显式 null 同缺省
        {'time_total_s': 904},                    # < 905（race 600 档最低预算）
        {'time_total_s': 43201},                  # > 43200（12h 防呆）
    ]
    # NaN / Infinity（json.loads 默认接受）→ 400 而非 500（int() 抛错被吞）。
    for special in (float('nan'), float('inf')):
        r = c.post('/api/extreme/start', content=json.dumps(
            {'time_total_s': special}),
            headers={'Content-Type': 'application/json'})
        assert r.status_code == 400
    for payload in cases:
        r = c.post('/api/extreme/start', json=payload)
        assert r.status_code == 400, payload
        assert 'time_total_s' in r.json()['error'], payload
    assert not list(uploads.glob('strategy_cfg_*.json'))
    assert strategy_mod._read_marker() is None
    assert len(calls) == 0


def test_extreme_time_bounds_exact_edges_202(strat_env, monkeypatch):
    """值域边界值恰好可过：905（race 最低总预算）与 43200（12h）。"""
    _default_start_env(monkeypatch)
    calls = _spawn_capture(monkeypatch, pids=(777, 778))
    c = _client()
    for i, t in enumerate((905, 43200)):
        if i:
            # 上一轮 202 已置 starting + 写 marker → 手动清（单飞闸门）。
            strategy_mod._STRATEGY_STATE['state'] = 'done'
            strategy_mod._clear_marker()
        assert c.post('/api/extreme/start',
                      json={'time_total_s': t}).status_code == 202
    assert [calls[0]['cmd'][-2], calls[1]['cmd'][-2]] == ['905', '43200']


# ------------------------------------------- band/prefix 透传（2026-08-30 解除拒收）


def _extreme_qty_2plus2() -> dict:
    """g01/g02 各 size28 demand=2 —— _synthetic_pieces 两码均有 28 片 → 资格码 [28]。
    （与 test_web_strategy._prefix_qty_2plus2 同构，self-contained 不跨文件 import。）"""
    return {'g01': {'28': 2}, 'g02': {'28': 2}}


def test_extreme_band_prefix_written_into_config(strat_env, monkeypatch):
    """band/prefix 开启且合法 → 202 + config 写键（StartPayload 原形态）+ spawn cmd
    尾不变（band/prefix 只随 config JSON 走，不进命令行）。"""
    _default_start_env(monkeypatch)
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    calls = _spawn_capture(monkeypatch, pids=(777, 778))
    c = _client()
    r = c.post('/api/extreme/start', json={
        'time_total_s': 14400, 'band': {'enabled': True, 'label': 'g01'}})
    assert r.status_code == 202
    cfg = json.loads(
        list(uploads.glob('strategy_cfg_*.json'))[0].read_text(encoding='utf-8'))
    assert cfg['band'] == {'enabled': True, 'label': 'g01'}
    assert cfg['time'] == 14400 and cfg['seeds'] == [0]
    assert calls[0]['cmd'][-1] == '--quiet'      # cmd 尾 --extreme --time <T> --quiet
    assert '--strategy' not in calls[0]['cmd']

    # 单飞闸门：上一轮 202 已置 starting + 写 marker → 手动清（同策略测试套路）。
    strategy_mod._STRATEGY_STATE['state'] = 'done'
    strategy_mod._clear_marker()
    r = c.post('/api/extreme/start', json={
        'time_total_s': 14400, 'quantities': _extreme_qty_2plus2(),
        'prefix': {'enabled': True, 'front': 'g01', 'back': 'g02'}})
    assert r.status_code == 202
    cfg2 = json.loads(
        sorted(uploads.glob('strategy_cfg_*.json'))[-1].read_text(encoding='utf-8'))
    assert cfg2['prefix'] == {'enabled': True, 'front': 'g01', 'back': 'g02'}
    assert cfg2['quantities'] == _extreme_qty_2plus2()
    assert calls[1]['cmd'][-1] == '--quiet'


def test_extreme_band_prefix_null_and_disabled_not_written(strat_env, monkeypatch):
    """band/prefix = null / enabled=false → _parse_* 返回 None → config 不写键
    （与策略族逐字节同语义）。"""
    _default_start_env(monkeypatch)
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    _spawn_capture(monkeypatch, pids=(777,) * 4)
    c = _client()
    for i, (band, prefix) in enumerate((
            (None, None),
            ({'enabled': False, 'label': 'g01'},
             {'enabled': False, 'front': 'g01', 'back': 'g02'}))):
        if i:
            strategy_mod._STRATEGY_STATE['state'] = 'done'
            strategy_mod._clear_marker()
        assert c.post('/api/extreme/start', json={
            'time_total_s': 14400, 'band': band, 'prefix': prefix,
            'quantities': _extreme_qty_2plus2()}).status_code == 202
        cfg = json.loads(
            sorted(uploads.glob('strategy_cfg_*.json'))[-1]
            .read_text(encoding='utf-8'))
        assert 'band' not in cfg and 'prefix' not in cfg


def test_extreme_band_prefix_invalid_400(strat_env, monkeypatch):
    """band/prefix 非法（坏 g 码 / 不存在于母版 / 数量全 0 / front==back / 无 2+2
    资格码）→ 400 结构化早退（文案与策略族同一校验点逐字一致），不落 config /
    不写 marker / 不 spawn。"""
    _default_start_env(monkeypatch)
    uploads = Path(paths_mod.OUT_DIR) / 'uploads'
    calls = _spawn_capture(monkeypatch, pids=(777,) * 4)
    c = _client()
    qty = _extreme_qty_2plus2()
    # band：坏 g 码 / 不存在于母版（pieces 只有 g01/g02）/ 数量全 0
    r = c.post('/api/extreme/start', json={
        'time_total_s': 14400, 'band': {'enabled': True, 'label': 'waist'}})
    assert r.status_code == 400 and 'g 码' in r.json()['error']
    r = c.post('/api/extreme/start', json={
        'time_total_s': 14400, 'band': {'enabled': True, 'label': 'g05'}})
    assert r.status_code == 400 and '不存在' in r.json()['error']
    r = c.post('/api/extreme/start', json={
        'time_total_s': 14400, 'quantities': {'g01': {'28': 0, '30': 0}},
        'band': {'enabled': True, 'label': 'g01'}})
    assert r.status_code == 400 and '全为 0' in r.json()['error']
    # prefix：front==back / 无 2+2 资格码（g02 demand=1 ≠ 2）
    r = c.post('/api/extreme/start', json={
        'time_total_s': 14400, 'quantities': qty,
        'prefix': {'enabled': True, 'front': 'g01', 'back': 'g01'}})
    assert r.status_code == 400 and '不同 g 码' in r.json()['error']
    r = c.post('/api/extreme/start', json={
        'time_total_s': 14400, 'quantities': {'g01': {'28': 2}, 'g02': {'28': 1}},
        'prefix': {'enabled': True, 'front': 'g01', 'back': 'g02'}})
    assert r.status_code == 400 and '2+2 资格码' in r.json()['error']
    assert not list(uploads.glob('strategy_cfg_*.json'))
    assert strategy_mod._read_marker() is None
    assert len(calls) == 0


# ------------------------------------------------------------- 单飞互斥


def test_mutex_strategy_running_blocks_extreme(strat_env, monkeypatch):
    """strategy running → extreme start 409，文案点名「策略运行」（前端区分对方）。"""
    _default_start_env(monkeypatch)
    _spawn_capture(monkeypatch, pids=(777, 778))
    c = _client()
    assert c.post('/api/strategy/start',
                  json={'mode': 'race', 'minutes': 10}).status_code == 202
    r = c.post('/api/extreme/start', json={'time_total_s': 14400})
    assert r.status_code == 409 and '策略运行' in r.json()['error']
    # 对方 marker 遗留（orphan，模拟 server 重启丢内存态）同样拦 extreme。
    strategy_mod._STRATEGY_STATE.clear()
    r = c.post('/api/extreme/start', json={'time_total_s': 14400})
    assert r.status_code == 409


def test_mutex_extreme_running_blocks_strategy(strat_env, monkeypatch):
    """extreme running → strategy start 409，文案点名「极限运行」；终态后放行。"""
    _default_start_env(monkeypatch)
    _spawn_capture(monkeypatch, pids=(777, 778))
    c = _client()
    assert c.post('/api/extreme/start',
                  json={'time_total_s': 14400}).status_code == 202
    r = c.post('/api/strategy/start', json={'mode': 'race', 'minutes': 10})
    assert r.status_code == 409 and '极限运行' in r.json()['error']
    # 极限终态（done + marker 清）后 strategy 放行 —— 单飞只在 in-flight。
    strategy_mod._STRATEGY_STATE['state'] = 'done'
    strategy_mod._clear_marker()
    assert c.post('/api/strategy/start',
                  json={'mode': 'race', 'minutes': 10}).status_code == 202


def test_mutex_cross_session_independent(dual_env, monkeypatch):
    """跨会话不 409：A extreme in-flight，B strategy 202；B 同会话再 extreme → 409
    （互斥是会话级不是全局）；A 的 extreme 不受 B 影响。"""
    _register_session(SID_A, 'docaaaa1')
    _register_session(SID_B, 'docbbbb2')
    _spawn_capture(monkeypatch, pids=(1111, 2222, 3333))
    c = _client()
    assert c.post('/api/extreme/start', json={'time_total_s': 14400},
                  headers={'X-Session-Id': SID_A}).status_code == 202
    assert c.post('/api/strategy/start', json={'mode': 'se', 'minutes': 10},
                  headers={'X-Session-Id': SID_B}).status_code == 202
    r = c.post('/api/extreme/start', json={'time_total_s': 14400},
               headers={'X-Session-Id': SID_B})
    assert r.status_code == 409
    # A 的 extreme 仍在 starting（mode 透传）；B 的 strategy 同槽 mode='se'。
    pa = c.get('/api/extreme/status', headers={'X-Session-Id': SID_A}).json()
    assert pa['state'] == 'starting' and pa['mode'] == 'extreme'
    pb = c.get('/api/strategy/status', headers={'X-Session-Id': SID_B}).json()
    assert pb['state'] == 'starting' and pb['mode'] == 'se'


# ------------------------------------------------------------- status / stop / result


def test_extreme_status_lifecycle_discovery_and_done(strat_env):
    """starting → run_dir 前缀 glob 发现（web_extreme_*）→ running（mode/
    total_budget_sec 透传 + race plan + 门杀 events）→ 进程死 + result.json → done。"""
    st = _extreme_state(strat_env, run_dir=None, rc=None)
    strategy_mod._write_marker({'pid': 4321, 'run_dir': None, 'doc_id': 'deadbeef01',
                                'mode': 'extreme',
                                'started_at': time.strftime('%Y-%m-%dT%H:%M:%S')})
    c = _client()
    p0 = c.get('/api/extreme/status').json()
    assert p0['state'] == 'starting' and p0['mode'] == 'extreme'
    assert p0['total_budget_sec'] == 14400

    run_dir = _write_run_dir(strat_env, name='web_extreme_abc123_20260829-120000')
    p1 = c.get('/api/extreme/status').json()
    assert p1['state'] == 'running' and p1['run_dir'] == str(run_dir)
    assert p1['plan']['gate_seconds'] == 300          # --extreme 展开 race 门杀
    assert p1['incumbent']['density'] == 0.91
    assert [e['seed'] for e in p1['per_seed']] == [0, 1]
    assert p1['per_seed'][0]['killed'] is True        # 门杀在 per_seed 行可见
    assert p1['events'][0]['kind'] == 'gate' and p1['events'][0]['would_kill'] is True
    # marker.run_dir 随发现回写（mode 保持 extreme）。
    marker = strategy_mod._read_marker()
    assert marker is not None and marker['run_dir'] == str(run_dir)
    assert marker['mode'] == 'extreme'

    # done：进程退出 + result.json 在场 → 终态清 marker、内存态保留。
    st['proc'] = FakeProc(pid=4321, rc=0)
    strategy_mod._write_marker({'pid': 4321, 'run_dir': str(run_dir),
                                'doc_id': 'deadbeef01', 'mode': 'extreme',
                                'started_at': time.strftime('%Y-%m-%dT%H:%M:%S')})
    p2 = c.get('/api/extreme/status').json()
    assert p2['state'] == 'done' and p2['exit_code'] == 0
    assert strategy_mod._read_marker() is None


def test_extreme_stop_tree_kill_and_marker_cleanup(strat_env, monkeypatch):
    """stop：taskkill /PID <pid> /T /F 树杀 + 置 stopped + 清 marker；无 run → 400
    极限文案。"""
    kill_calls = []

    def fake_run(cmd, **kw):
        kill_calls.append(list(cmd))

    monkeypatch.setattr(strategy_mod.subprocess, 'run', fake_run)
    _extreme_state(strat_env, run_dir=None, rc=None)
    strategy_mod._write_marker({'pid': 4321, 'run_dir': None, 'doc_id': 'x',
                                'mode': 'extreme',
                                'started_at': time.strftime('%Y-%m-%dT%H:%M:%S')})
    r = _client().post('/api/extreme/stop')
    assert r.status_code == 200 and r.json() == {'stopped': True, 'pid': 4321}
    if sys.platform == 'win32':
        assert kill_calls == [['taskkill', '/PID', '4321', '/T', '/F']]
    assert strategy_mod._read_marker() is None
    assert strategy_mod._STRATEGY_STATE['state'] == 'stopped'
    r2 = _client().post('/api/extreme/stop')
    assert r2.status_code == 400 and '极限运行' in r2.json()['error']


def test_extreme_result_contract(strat_env, monkeypatch):
    """result：best（incumbent 全量 + density_sparrow 边车补）+ manifest（start
    快照口径 build_pid_meta）+ 漂移 warning；idle → 404 / running → 409 极限文案。"""
    c = _client()
    r404 = c.get('/api/extreme/result')
    assert r404.status_code == 404 and '极限运行' in r404.json()['error']

    _extreme_state(strat_env, run_dir=None, rc=None)
    r = c.get('/api/extreme/result')
    assert r.status_code == 409 and '极限运行尚未结束' in r.json()['error']

    run_dir = _write_run_dir(strat_env)
    st = _extreme_state(strat_env, run_dir=str(run_dir), rc=0)
    st['state'] = 'done'
    _patch_state(monkeypatch, _fake_state(doc_id='deadbeef01'))
    payload = c.get('/api/extreme/result').json()
    assert payload['state'] == 'done' and payload['mode'] == 'extreme'
    assert payload['best']['seed'] == 1 and payload['best']['density'] == 0.91
    assert payload['best']['density_sparrow'] == 0.94
    assert payload['best']['placed_items'] == [{'id': 'g01_28', 'rotation': 0.0,
                                                'translation': [1.0, 2.0]}]
    assert {p['id'] for p in payload['manifest']['pieces']} == \
        {p['pid'] for p in _synthetic_pieces()}
    assert 'warning' not in payload                 # doc_id 未漂移

    # 漂移：start 快照 doc_id ≠ 当前画布 → warning（与 strategy 同文案）。
    _patch_state(monkeypatch, _fake_state(doc_id='newmaster99'))
    payload2 = c.get('/api/extreme/result').json()
    assert payload2['warning'] == '母版已变更，应用结果可能与当前画布不一致'


# ------------------------------------------------------------- sid 语义 / 清理


def test_extreme_session_gate_fail_fast(strat_env, monkeypatch):
    """sid 语义同 strategy：未知 sid → 401 code=session_expired、非法 → 400，
    四路由全拦（闸门先于一切，不 spawn）。"""
    _register_session(SID_A, 'docaaaa1')
    calls = _spawn_capture(monkeypatch, pids=(1111,))
    c = _client()
    for method, path in (('post', '/api/extreme/start'),
                         ('get', '/api/extreme/status'),
                         ('post', '/api/extreme/stop'),
                         ('get', '/api/extreme/result')):
        kwargs = {'json': {'time_total_s': 14400}} if method == 'post' else {}
        r = getattr(c, method)(path, headers={'X-Session-Id': 'cccc3333'}, **kwargs)
        assert r.status_code == 401, path
        assert r.json()['code'] == 'session_expired', path
        r = getattr(c, method)(path, headers={'X-Session-Id': 'bad-sid!'}, **kwargs)
        assert r.status_code == 400 and r.json() == {'error': 'sid 非法'}, path
    assert len(calls) == 0


def test_extreme_cleanup_scoped_to_own_sid_prefix(dual_env, monkeypatch):
    """产物清理按会话前缀隔离：A extreme start 清 web_aaaa11_extreme_* 旧 run，
    B 的 extreme run 目录保留；sid 会话不清 legacy（web_extreme_* 无 sid 段）。"""
    _register_session(SID_A, 'docaaaa1')
    _register_session(SID_B, 'docbbbb2')
    _spawn_capture(monkeypatch, pids=(1111, 2222))
    base = Path(paths_mod.CONFIG_RUNS_DIR)
    dir_a = base / 'web_aaaa11_extreme_111111_20260829-090000'
    dir_b = base / 'web_bbbb22_extreme_222222_20260829-090500'
    legacy = base / 'web_extreme_legacy_20260829-080000'
    manual = base / 'manual_20260829-070000'
    for d in (dir_a, dir_b, legacy, manual):
        d.mkdir(parents=True)
        (d / 'result.json').write_text('{}', encoding='utf-8')

    c = _client()
    assert c.post('/api/extreme/start', json={'time_total_s': 14400},
                  headers={'X-Session-Id': SID_A}).status_code == 202
    assert not dir_a.exists()                        # 本会话前缀旧 run 被清
    assert dir_b.exists() and legacy.exists() and manual.exists()

    assert c.post('/api/extreme/start', json={'time_total_s': 905},
                  headers={'X-Session-Id': SID_B}).status_code == 202
    assert not dir_b.exists()                        # B 清 B 前缀
    assert legacy.exists() and manual.exists()       # legacy / 手工 run 不受影响


def test_extreme_routes_present_in_app():
    """/api/extreme/* 四路由在场（TestClient 探测 status → idle 200）。"""
    r = _client().get('/api/extreme/status')
    assert r.status_code == 200
    assert r.json()['state'] in ('idle', 'orphan')
    paths = {route.path for route in server_mod.app.routes
             if hasattr(route, 'path')}
    assert {'/api/extreme/start', '/api/extreme/status',
            '/api/extreme/stop', '/api/extreme/result'} <= paths


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
