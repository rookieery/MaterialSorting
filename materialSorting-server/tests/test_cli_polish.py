"""自动智能微调后处理测试（2026-10-07）：polish_post.polish_run_result 单测 +
run_config ``--polish`` 旗标接线 + web /api/strategy·extreme start ``polish`` 载荷。

分层：
1. ``polish_run_result``（合成 run_dir：result.json + pieces_intermediate.json，
   真引擎确定性矩形布局）——改进回写门槛 / snug 不改进 / exclude label 冻结 /
   无布局 ValueError / result_polish.json 恒落盘；
2. ``run_config --polish``（iso_env + fake solve + monkeypatch polish_run_result）
   —— 旗标 → 调用 → result.json polish 段 → incumbent 回写 → run_stats 行
   ``polish:true``；无旗标零新增键零调用；
3. strategy/extreme start 载荷 ``polish`` 严格 bool → spawn cmd ``--polish``
   （镜像 test_start_full_cores_flag）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from materialsorting.cli import polish_post
from materialsorting.cli import run_config as rc_mod
from materialsorting.cli.polish_post import polish_run_result


# ------------------------------------------------------------- 合成 run_dir 夹具


def _pieces() -> list[dict]:
    """3 片合成矩形（g01 500×800 / g02 300×400 / g05 300×400）。"""
    out = []
    for pid, label, w, h in (('g01_28', 'g01', 500.0, 800.0),
                             ('g02_28', 'g02', 300.0, 400.0),
                             ('g05_28', 'g05', 300.0, 400.0)):
        out.append({
            'pid': pid, 'label': label, 'size': 28,
            'polygon': [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]],
            'bbox': [0.0, 0.0, w, h], 'area_mm2': w * h, 'n_verts': 4,
            'allowed_angles': [0, 180], 'net_polygon': [], 'internal_lines': [],
            'notches': [], 'grain_line': None})
    return out


def _mk_run_dir(tmp_path: Path, placed: list[dict], *, incumbent=True,
                band=None, prefix=None) -> Path:
    """合成 run_dir：result.json（portfolio.incumbent 或旧式 best+int 计数形态）+
    pieces_intermediate.json。placed 同时写进 incumbent 与 best_frame 边车
    （两源等价，回退路径可测）。"""
    rd = tmp_path / 'run'
    rd.mkdir()
    inter = {'gate_mm': 1980.0, 'pieces': _pieces()}
    (rd / 'pieces_intermediate.json').write_text(
        json.dumps(inter, ensure_ascii=False), encoding='utf-8')
    seed = 0
    layout = [dict(p) for p in placed]
    frame = {'seed': seed, 'frame_index': 3, 'density': 0.5, 'width_mm': 1000.0,
             'placed_items': layout}
    (rd / 'best_frame_s0.json').write_text(
        json.dumps(frame, ensure_ascii=False), encoding='utf-8')
    config: dict = {'gate_mm': 1980.0, 'time': 30, 'seeds': [seed]}
    if band is not None:
        config['band'] = band
    if prefix is not None:
        config['prefix'] = prefix
    result: dict = {'config': config, 'commit': {}, 'solve': []}
    if incumbent:
        result['portfolio'] = {'incumbent': dict(frame)}
        result['best'] = dict(frame)
    else:
        # 旧式 best：placed_items = int 计数（布局只在边车）。
        result['best'] = {'seed': seed, 'density': 0.5, 'width_mm': 1000.0,
                          'placed_items': len(layout), 'elapsed': 30.0}
    (rd / 'result.json').write_text(
        json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return rd


_GAP = [
    {'id': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]},
    {'id': 'g02_28', 'rotation': 0.0, 'translation': [700.0, 0.0]},
]
_SNUG = [
    {'id': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]},
    {'id': 'g02_28', 'rotation': 0.0, 'translation': [500.0, 0.0]},
]


# ------------------------------------------------------- polish_run_result 单测


def test_improved_rewrite_payload(tmp_path):
    """有缝布局 → west 贴附收缝：improved=True、placed_items 携带新布局、
    result_polish.json 落盘、delta 为正。"""
    rd = _mk_run_dir(tmp_path, _GAP)
    out = polish_run_result(rd)
    assert out['improved'] is True
    assert out['moves'] >= 1
    assert 'placed_items' in out
    g02 = next(p for p in out['placed_items'] if p['id'] == 'g02_28')
    assert g02['translation'][0] == pytest.approx(500.0, abs=0.01)
    # 物理口径前后：宽 1000 → 801（贴附 1nm 微抬 ceil），密度升。
    assert out['before']['width_mm'] == pytest.approx(1000.0, abs=0.01)
    assert out['after']['width_mm'] == pytest.approx(801.0, abs=0.01)
    assert out['delta']['density_pt'] > 0
    detail = json.loads((rd / 'result_polish.json').read_text(encoding='utf-8'))
    assert detail['improved'] is True and detail['placed_items']


def test_snug_not_improved(tmp_path):
    """snug 布局零 move → improved=False、无 placed_items 键（不回写）、明细仍落盘。"""
    rd = _mk_run_dir(tmp_path, _SNUG)
    out = polish_run_result(rd)
    assert out['improved'] is False
    assert out['moves'] == 0
    assert 'placed_items' not in out
    assert (rd / 'result_polish.json').is_file()


def test_moved_but_not_better_not_improved(tmp_path):
    """有 move 但宽度不变（south 贴地，x 向无缝）→ 严格更优门槛拦截：
    improved=False 不回写（moves ≥1 如实记）。"""
    placed = [
        {'id': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]},
        # x 向已贴触 g01（500），y 悬空 500 —— south 贴附下滑到 y=0，宽度不变。
        {'id': 'g02_28', 'rotation': 0.0, 'translation': [500.0, 500.0]},
    ]
    rd = _mk_run_dir(tmp_path, placed)
    out = polish_run_result(rd)
    assert out['moves'] >= 1
    assert out['improved'] is False
    assert 'placed_items' not in out


def test_exclude_labels_from_config(tmp_path):
    """band/prefix config 回显 → label 级保守排除：带成员（g05）有缝也不动
    （exclude 冻结为障碍），exclude_labels 如实回显。"""
    placed = [
        {'id': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]},
        {'id': 'g05_28', 'rotation': 0.0, 'translation': [700.0, 0.0]},
    ]
    rd = _mk_run_dir(tmp_path, placed,
                     band={'enabled': True, 'label': 'g05'},
                     prefix={'enabled': True, 'front': 'g01', 'back': 'g02'})
    out = polish_run_result(rd)
    assert sorted(out['source']['exclude_labels']) == ['g01', 'g02', 'g05']
    # g05 被冻结 → 缝不收 → 无改进（g01 前缀 label 也冻结，但本布局 g01 已贴头）。
    assert out['improved'] is False
    assert out['excluded_pieces'] == 2     # g01_28 + g05_28 两实例
    detail = json.loads((rd / 'result_polish.json').read_text(encoding='utf-8'))
    assert detail['source']['exclude_labels'] == ['g05', 'g01', 'g02']


def test_legacy_best_falls_back_to_sidecar(tmp_path):
    """旧式 best（placed_items=int 计数）→ best_frame_s{seed}.json 边车回退
    （LNS _incumbent 同款源解析）。"""
    rd = _mk_run_dir(tmp_path, _GAP, incumbent=False)
    out = polish_run_result(rd)
    assert out['improved'] is True
    assert out['source']['seed'] == 0


def test_no_layout_raises(tmp_path):
    """result.json 无 incumbent/best 布局且无 seed 边车 → ValueError（调用方
    降级 warn 跳过）。"""
    rd = _mk_run_dir(tmp_path, _GAP)
    (rd / 'result.json').write_text(
        json.dumps({'config': {}, 'solve': [], 'best': {}}), encoding='utf-8')
    (rd / 'best_frame_s0.json').unlink()
    with pytest.raises(ValueError):
        polish_run_result(rd)


# ------------------------------------------------ run_config --polish 旗标接线


class _FakeSolve:
    """test_cli_extreme._FakeSolve 同构（够用子集）：单 seed 两帧 + incumbent
    侧车；placed 为伪形态（polish_run_result 由 monkeypatch 替换，不触引擎）。"""

    def __init__(self, traj):
        self.traj = traj
        self.calls: list[tuple] = []

    def __call__(self, cfg, run_dir, *, seed, time_budget=None, on_progress=None,
                 should_stop=None, solver_opts=None, artifact_suffix='', **kw):
        self.calls.append((int(seed), time_budget, artifact_suffix))
        rd = Path(run_dir)
        frames = self.traj[(int(seed), artifact_suffix)]
        walked = []
        best = None
        for idx, (elapsed, density) in enumerate(frames):
            report = {'elapsed': elapsed, 'phase': 'exploring', 'density': density,
                      'density_sparrow': density - 0.01, 'width_mm': 5000.0,
                      'placed_items': [{'pid': 'g01_28'}]}
            walked.append({'elapsed': elapsed, 'phase': 'exploring',
                           'density': density, 'width_mm': 5000.0})
            if on_progress is not None:
                on_progress(report)
            if best is None or density > best[2]:
                best = (idx, elapsed, density)
        (rd / f'curve_s{seed}{artifact_suffix}.json').write_text(
            json.dumps(walked), encoding='utf-8')
        (rd / f'best_frame_s{seed}{artifact_suffix}.json').write_text(
            json.dumps({'seed': int(seed), 'frame_index': best[0],
                        'density': best[2], 'width_mm': 5000.0,
                        'placed_items': [{'pid': 'g01_28'}]}), encoding='utf-8')
        return {'seed': int(seed), 'n_items': 6, 'n_eroded': 0,
                'total_area_mm2': 1.0, 'width_mm': 5000.0,
                'density_sparrow': best[2] - 0.01,
                'placed_items': len(walked), 'elapsed': float(frames[-1][0]),
                'real_density': frames[-1][1]}


@pytest.fixture
def iso_env(tmp_path, monkeypatch):
    """隔离环境（test_cli_extreme.iso_env 同构子集）+ 合成母版。"""
    import ezdxf
    from ezdxf.lldxf.const import POLYLINE_CLOSED
    from materialsorting import paths as paths_mod
    from materialsorting.web import server as server_mod

    runs = tmp_path / 'config_runs'
    runs.mkdir()
    inter = tmp_path / 'web_intermediate.json'
    inter.write_text('{"sentinel": true}', encoding='utf-8')
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    stats = tmp_path / 'run_stats.jsonl'
    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(runs))
    monkeypatch.setattr(paths_mod, 'INTERMEDIATE', str(inter))
    monkeypatch.setattr(paths_mod, 'RUN_STATS_JSONL', str(stats))
    monkeypatch.setattr(server_mod, 'UPLOADS_DIR', uploads)
    master = tmp_path / 'synthetic_master.dxf'
    doc = ezdxf.new('R12')
    for name, (x, y, w, h) in (('blk x.28', (0.1, 0.2, 400.0, 700.0)),
                                ('blk x.29', (0.1, 0.2, 400.0, 720.0))):
        blk = doc.blocks.new(name=name)
        poly = blk.add_polyline2d(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
            dxfattribs={'layer': '1'})
        poly.dxf.flags = poly.dxf.flags | POLYLINE_CLOSED
    doc.saveas(str(master))
    return tmp_path, runs, stats, master


def _write_config(path: Path, master: Path, **extra) -> Path:
    cfg = {'master_dxf': str(master), 'gate_mm': 1980, 'time': 2}
    cfg.update(extra)
    path.write_text(json.dumps(cfg), encoding='utf-8')
    return path


_TRAJ = {(0, ''): [(1.0, 0.80), (2.0, 0.82)], (1, ''): [(1.0, 0.81), (2.0, 0.83)]}


def _patch_solve(monkeypatch, traj=_TRAJ):
    fake = _FakeSolve(traj)
    monkeypatch.setattr(rc_mod, 'solve_pieces', fake)
    return fake


def _fake_polish_out(improved: bool, density=0.84, width=4900.0) -> dict:
    return {
        'improved': improved,
        'before': {'density': 0.82, 'width_mm': 5000.0, 'n_placed': 2},
        'after': {'density': density if improved else 0.82,
                  'width_mm': width if improved else 5000.0, 'n_placed': 2},
        'delta': {'density_pt': 2.0 if improved else 0.0},
        'rounds': 2, 'moves': 4 if improved else 0, 'attach_moves': 3,
        'excluded_pieces': 0, 'elapsed_sec': 0.5,
        'source': {'result': 'result.json', 'intermediate':
                   'pieces_intermediate.json', 'seed': 1, 'exclude_labels': []},
        **({'placed_items': [{'id': 'g01_28', 'rotation': 0.0,
                              'translation': [0.0, 0.0]}]} if improved else {}),
    }


def _run_dirs(runs: Path) -> list[Path]:
    return sorted(p for p in runs.iterdir() if p.is_dir())


def test_polish_flag_improved_rewrites(iso_env, monkeypatch, capsys):
    """--polish + 微调改进 → polish_run_result 被调、incumbent 三字段回写、
    result.json 附 polish 段（无 placed_items）、run_stats 行 polish:true。"""
    tmp, runs, stats, master = iso_env
    cfg = _write_config(tmp / 'cfg.json', master, seeds=[0, 1])
    _patch_solve(monkeypatch)
    calls: list = []

    def fake_polish(run_dir, *, echo=None):
        calls.append(run_dir)
        return _fake_polish_out(improved=True)

    monkeypatch.setattr(polish_post, 'polish_run_result', fake_polish)
    assert rc_mod.main([str(cfg), '--polish', '--quiet', '--name', 'pl_on']) == 0
    assert len(calls) == 1
    out = capsys.readouterr().out
    assert '[polish] ' in out and 'improved=True' in out
    rd = _run_dirs(runs)[-1]
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    inc = result['portfolio']['incumbent']
    assert inc['density'] == pytest.approx(0.84)
    assert inc['width_mm'] == pytest.approx(4900.0)
    assert inc['placed_items'] == [{'id': 'g01_28', 'rotation': 0.0,
                                    'translation': [0.0, 0.0]}]
    sec = result['polish']
    assert sec['improved'] is True and 'placed_items' not in sec
    rows = [json.loads(l) for l in
            stats.read_text(encoding='utf-8').strip().splitlines()]
    assert rows[-1]['config'].get('polish') is True


def test_polish_flag_not_improved_section_only(iso_env, monkeypatch, capsys):
    """--polish + 微调不改进 → 布局不变、polish 段仍落（improved:false）、
    run_stats 行 polish:true（开启即记）。"""
    tmp, runs, stats, master = iso_env
    cfg = _write_config(tmp / 'cfg.json', master, seeds=[0, 1])
    _patch_solve(monkeypatch)
    monkeypatch.setattr(polish_post, 'polish_run_result',
                        lambda rd, *, echo=None: _fake_polish_out(improved=False))
    assert rc_mod.main([str(cfg), '--polish', '--quiet', '--name', 'pl_off']) == 0
    out = capsys.readouterr().out
    assert 'improved=False' in out
    rd = _run_dirs(runs)[-1]
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert result['polish']['improved'] is False
    # 布局未被改写（incumbent 密度保持帧值 0.83 —— seed1 帧级最优）。
    assert result['portfolio']['incumbent']['density'] == pytest.approx(0.83)
    rows = [json.loads(l) for l in
            stats.read_text(encoding='utf-8').strip().splitlines()]
    assert rows[-1]['config'].get('polish') is True


def test_no_polish_flag_zero_keys(iso_env, monkeypatch, capsys):
    """无 --polish → polish_run_result 不被调、result.json 无 polish 键、
    run_stats 行无 polish 键（零回归）。"""
    tmp, runs, stats, master = iso_env
    cfg = _write_config(tmp / 'cfg.json', master, seeds=[0, 1])
    _patch_solve(monkeypatch)
    calls: list = []
    monkeypatch.setattr(polish_post, 'polish_run_result',
                        lambda rd, *, echo=None: calls.append(rd) or {})
    assert rc_mod.main([str(cfg), '--quiet', '--name', 'pl_none']) == 0
    capsys.readouterr()
    assert calls == []
    rd = _run_dirs(runs)[-1]
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert 'polish' not in result
    rows = [json.loads(l) for l in
            stats.read_text(encoding='utf-8').strip().splitlines()]
    assert 'polish' not in rows[-1]['config']


def test_polish_failure_degrades(iso_env, monkeypatch, capsys):
    """polish 环节抛错（旧 run 无布局等）→ warn 跳过不否定交付物（退出码 0、
    result.json 无 polish 段）。"""
    tmp, runs, stats, master = iso_env
    cfg = _write_config(tmp / 'cfg.json', master, seeds=[0, 1])
    _patch_solve(monkeypatch)

    def boom(rd, *, echo=None):
        raise ValueError('result.json 无 incumbent/best placed_items')

    monkeypatch.setattr(polish_post, 'polish_run_result', boom)
    assert rc_mod.main([str(cfg), '--polish', '--quiet', '--name', 'pl_err']) == 0
    err = capsys.readouterr().err
    assert '智能微调后处理失败' in err
    rd = _run_dirs(runs)[-1]
    result = json.loads((rd / 'result.json').read_text(encoding='utf-8'))
    assert 'polish' not in result


# ------------------------------------------- web /api/strategy·extreme start 载荷


@pytest.fixture
def strat_env(tmp_path, monkeypatch):
    from materialsorting import paths as paths_mod
    from materialsorting.web import strategy as strategy_mod

    monkeypatch.setattr(paths_mod, 'CONFIG_RUNS_DIR', str(tmp_path / 'config_runs'))
    monkeypatch.setattr(paths_mod, 'OUT_DIR', str(tmp_path / 'out'))
    tmp_dir = tmp_path / 'tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(strategy_mod.tempfile, 'tempdir', str(tmp_dir))
    strategy_mod._STRATEGY_STATE.clear()
    yield tmp_path
    strategy_mod._STRATEGY_STATE.clear()


def _synthetic_pieces() -> list[dict]:
    return [
        {'pid': 'g01_28', 'label': 'g01', 'size': 28,
         'polygon': [[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]],
         'bbox': [0.0, 0.0, 500.0, 800.0], 'area_mm2': 400000.0, 'n_verts': 4,
         'allowed_angles': [0, 180], 'net_polygon': [], 'internal_lines': [],
         'notches': [], 'grain_line': None},
    ]


def _client():
    from starlette.testclient import TestClient
    from materialsorting.web.server import app
    return TestClient(app)


def _patch_state(monkeypatch, state):
    from materialsorting.web import strategy as strategy_mod
    monkeypatch.setattr(strategy_mod, '_pieces_state', lambda: state)


def _spawn_capture(monkeypatch):
    from materialsorting.web import strategy as strategy_mod
    calls: dict = {}

    class _Proc:
        pid = 4321

        def poll(self):
            return None

    def fake_spawn(cmd, stderr_path):
        calls['cmd'] = list(cmd)
        return _Proc()

    monkeypatch.setattr(strategy_mod, '_spawn_run_process', fake_spawn)
    return calls


def test_strategy_start_polish_flag(strat_env, monkeypatch):
    """polish 严格 bool（int/字符串 → 400）；true → spawn cmd 含 --polish
    （--quiet 仍末位）；缺省不带。极限族同款。"""
    from materialsorting.web import strategy as strategy_mod

    _patch_state(monkeypatch, {
        'doc': {'doc_id': 'cafe1234', 'source': 'm.dxf', 'gate_mm': 1980.0},
        'gate_mm': 1980.0, 'pieces': _synthetic_pieces(),
        'pieces_by_id': {p['pid']: p for p in _synthetic_pieces()}})
    uploads = strat_env / 'out' / 'uploads'
    uploads.mkdir(parents=True)
    (uploads / 'cafe1234.dxf').write_bytes(b'DXF')
    c = _client()

    assert c.post('/api/strategy/start',
                  json={'mode': 'race', 'minutes': 10,
                        'polish': 1}).status_code == 400
    assert c.post('/api/strategy/start',
                  json={'mode': 'race', 'minutes': 10,
                        'polish': 'on'}).status_code == 400

    calls = _spawn_capture(monkeypatch)
    assert c.post('/api/strategy/start',
                  json={'mode': 'race', 'minutes': 10}).status_code == 202
    assert '--polish' not in calls['cmd']

    strategy_mod._STRATEGY_STATE.clear()
    strategy_mod._clear_marker()
    calls2 = _spawn_capture(monkeypatch)
    assert c.post('/api/strategy/start',
                  json={'mode': 'race', 'minutes': 10,
                        'polish': True}).status_code == 202
    assert '--polish' in calls2['cmd']
    assert calls2['cmd'][-1] == '--quiet'

    # 极限族同款（/api/extreme/start）
    strategy_mod._STRATEGY_STATE.clear()
    strategy_mod._clear_marker()
    calls3 = _spawn_capture(monkeypatch)
    assert c.post('/api/extreme/start',
                  json={'time_total_s': 960, 'polish': True}).status_code == 202
    assert '--polish' in calls3['cmd']
    assert calls3['cmd'][-1] == '--quiet'
