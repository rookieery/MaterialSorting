"""prd-warm-start-phase1 US-002 —— initial_solution 求解链透传桩测试。

五步链 ``cli.pipeline.solve_pieces → web.solver.solve_with_callback_proc →
Process args(7 位) → web.solve_worker → instance.solve(initial_solution=<JSON>)``
的 warm 载荷通道。**PyPI 0.9.0 态可跑**：全程 monkeypatch 假 spyrrow 模块
（sys.modules 注入 Item/StripPackingInstance/StripPackingConfig/ProgressQueue/
ReportType 桩 —— build_instance 与 _frame_allowed 均可无真 wheel 运行）+ 假
``warm_start_supported``，不依赖私有 wheel 装载态。

覆盖（PRD AC 四向 + 二期 2026-09-19 band/prefix 解禁）：
  - worker 直调（进程内）：None 缺省 solve 调用形零变化 / 载荷在场
    ``json.dumps`` 后进 solve 关键字 / 不支持丢弃降级（warn + 普通重放不炸轮）/
    序列化失败防御降级 / 二期组合视角：band + 组合宇宙载荷（含 WB_）→ 宇宙
    复检通过照常灌入 + final ``warm_state`` engaged=True；band + 成员级载荷
    （pid 宇宙错位）→ 复检丢弃降级（engaged=False + 'instance_mismatch'）；
    ``record_composite`` 帧旁路（band 开 → 帧附 ``composite`` 段含 WB_ 与
    组合 demand_map；缺省 False → 无该键 = WS 前端契约哨兵）；
  - ``solve_with_callback_proc``：Process args 元组恰 8 位（默认 None / 载荷
    dict 原样第 7 位、record_composite 第 8 位、band/prefix 第 5/6 位不动）——
    假 Process+假 Queue 进程内同步闭环（Windows spawn 不继承 monkeypatch，
    闭环必须在当前进程完成）；
  - ``solve_pieces``：kwarg 纯透传（dict 原样 / None 缺省）。

真 spyrrow 回归（initial_solution=None 走新 7 位元组的真实 spawn 链路）由既有
``test_solve_proc.py`` / ``test_cli_solve_pieces_proc.py`` 全量覆盖（零逻辑改动），
此处不重复。
"""
from __future__ import annotations

import json
import logging
import multiprocessing
import queue as _queue_mod
import sys
import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import materialsorting.web.solver as web_solver
from materialsorting.web.solve_worker import solve_worker


# ------------------------------------------------------------- 合成夹具（自足）


def _pieces() -> list[dict]:
    """2 片合成裁片（与 conftest synthetic 同构，本文件自足不跨文件取 fixture）。"""
    return [
        {'pid': 'g01_28', 'label': 'g01', 'size': 28,
         'polygon': [[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]],
         'bbox': [0.0, 0.0, 500.0, 800.0], 'area_mm2': 400000.0, 'n_verts': 4,
         'allowed_angles': [0, 180], 'net_polygon': [], 'internal_lines': [],
         'notches': [], 'grain_line': None},
        {'pid': 'g02_28', 'label': 'g02', 'size': 28,
         'polygon': [[0.0, 0.0], [300.0, 0.0], [300.0, 400.0], [0.0, 400.0]],
         'bbox': [0.0, 0.0, 300.0, 400.0], 'area_mm2': 120000.0, 'n_verts': 4,
         'allowed_angles': [0, 180], 'net_polygon': [], 'internal_lines': [],
         'notches': [], 'grain_line': None},
    ]


# warm 载荷样例（US-001 build_initial_solution 产物形态，恰为 2 片完整解）。
_PAYLOAD = {
    'strip_width': 1500.0,
    'placed_items': [
        {'id': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]},
        {'id': 'g02_28', 'rotation': 180.0, 'translation': [600.0, 100.0]},
    ],
}

_SOLVE_PARAMS = {'time_budget': 1, 'seed': 0}


# --------------------------------------------------------------- 假 spyrrow 模块


class _RTMember:
    """ReportType 成员桩：``_frame_allowed`` 白名单按同一性命中；phase_name 对齐。"""

    def __init__(self, name: str):
        self._name = name

    def phase_name(self) -> str:
        return self._name


class _FakeReportType:
    ExplFeas = _RTMember('exploring')
    ExplInfeas = _RTMember('exploring')
    ExplImproving = _RTMember('exploring')
    CmprFeas = _RTMember('compressing')
    Final = _RTMember('final')


class _FakePlaced:
    def __init__(self, pid: str):
        self.id = pid
        self.rotation = 0.0
        self.translation = (10.0, 20.0)


class _FakeSolution:
    density = 0.42
    width = 1234.5

    def __init__(self, pids: list):
        self.placed_items = [_FakePlaced(p) for p in pids]


class _FakeProgressQueue:
    """ProgressQueue 桩：put/drain 缓冲语义（worker 只消费 drain）。"""

    def __init__(self):
        self._buf: list = []

    def put(self, item) -> None:
        self._buf.append(item)

    def drain(self) -> list:
        out, self._buf = self._buf, []
        return out


def _fake_spyrrow_module(capture: list, pids: list):
    """假 spyrrow 模块：build_instance 可构造（Item/Instance/Config）、solve 捕获
    超出 (config, progress) 的关键字并投一帧可行解 + 返回末态。"""
    mod = types.ModuleType('spyrrow')

    class Item:
        def __init__(self, *, id, shape, demand, allowed_orientations):
            self.id = id
            self.demand = int(demand)

    class StripPackingInstance:
        def __init__(self, *, name, strip_height, items):
            self.strip_height = float(strip_height)
            self.items = list(items)

        def solve(self, config, progress=None, **kwargs):
            capture.append(dict(kwargs))
            sol = _FakeSolution(pids)
            if progress is not None:
                progress.put((_FakeReportType.ExplFeas, sol))
                progress.put((_FakeReportType.Final, sol))
            return sol

    class StripPackingConfig:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    mod.Item = Item
    mod.StripPackingInstance = StripPackingInstance
    mod.StripPackingConfig = StripPackingConfig
    mod.ProgressQueue = _FakeProgressQueue
    mod.ReportType = _FakeReportType
    return mod


@pytest.fixture
def fake_spyrrow(monkeypatch):
    """``sys.modules['spyrrow']`` 换假模块；返回 capture（每元素 = 一次 solve 的
    附加关键字 dict，空 dict 即现行调用形）。"""
    capture: list = []
    monkeypatch.setitem(sys.modules, 'spyrrow',
                        _fake_spyrrow_module(capture, ['g01_28', 'g02_28']))
    return capture


def _set_warm(monkeypatch, value: bool) -> None:
    """假能力探测（worker 函数内延迟 import → 按调用时模块属性取到本桩）。"""
    import materialsorting.nesting_engine.warmstart as warmstart_mod
    monkeypatch.setattr(warmstart_mod, 'warm_start_supported', lambda: value)


def _drain(q) -> list:
    msgs: list = []
    while True:
        try:
            msgs.append(q.get_nowait())
        except _queue_mod.Empty:
            return msgs
        except Exception:                       # noqa: BLE001 队列枯竭即返回
            return msgs


# --------------------------------------------- worker 直调（进程内，无 spawn）


def test_worker_default_none_solve_call_unchanged(fake_spyrrow):
    """None 缺省零变化：solve 恰被调一次、无 initial_solution 关键字（PyPI
    0.9.0 的 solve 不认该键，缺省路径绝不带它）；消息序 manifest→frame*→final。"""
    q = _FakeQueue()   # 同步队列：真 Queue 的 feeder 线程异步落管，get_nowait 有竞态
    solve_worker(_pieces(), 1980.0, dict(_SOLVE_PARAMS), q)
    kinds = [m['kind'] for m in _drain(q)]
    assert kinds[0] == 'manifest'
    assert 'frame' in kinds
    assert kinds[-1] == 'final'
    assert 'error' not in kinds
    assert fake_spyrrow == [{}]


def test_worker_payload_json_dumps_at_consumption(fake_spyrrow, monkeypatch):
    """载荷透传到位：支持态下 worker 在最终消费点 json.dumps 后传入 solve
    （关键字值恰为 ``json.dumps(payload)`` 字符串），final 照常交付。"""
    _set_warm(monkeypatch, True)
    q = _FakeQueue()   # 同步队列：真 Queue 的 feeder 线程异步落管，get_nowait 有竞态
    solve_worker(_pieces(), 1980.0, dict(_SOLVE_PARAMS), q,
                 initial_solution=_PAYLOAD)
    kinds = [m['kind'] for m in _drain(q)]
    assert 'error' not in kinds and kinds[-1] == 'final'
    assert fake_spyrrow == [{'initial_solution': json.dumps(_PAYLOAD)}]


def test_worker_drops_payload_when_unsupported(fake_spyrrow, monkeypatch, caplog):
    """不支持丢弃降级：``warm_start_supported()`` False + 载荷在场 → solve 收到
    initial_solution=None（调用形与现行一致）、warn 一行、普通重放不炸轮
    （manifest→frame*→final 全链照常）。"""
    _set_warm(monkeypatch, False)
    q = _FakeQueue()   # 同步队列：真 Queue 的 feeder 线程异步落管，get_nowait 有竞态
    with caplog.at_level(logging.WARNING, logger='materialsorting.web.solve_worker'):
        solve_worker(_pieces(), 1980.0, dict(_SOLVE_PARAMS), q,
                     initial_solution=_PAYLOAD)
    kinds = [m['kind'] for m in _drain(q)]
    assert kinds == ['manifest', 'frame', 'frame', 'final']
    assert fake_spyrrow == [{}]
    assert fake_spyrrow[0].get('initial_solution') is None
    assert any('降级为普通重放' in r.message for r in caplog.records)


# ------------------------------------ 二期（2026-09-19）band/prefix warm 解禁
#
# worker 级组合视角用 band 桩全覆盖（prefix 与 band 在 warm 闸门/宇宙复检/帧旁路
# 的生产代码路径完全同构 —— extra item + exclude + _emit_placed 展开，异构面只剩
# _build_prefix/_finalize_prefix 编排，那两块由 test_prefix.py 与 portfolio 级
# test_se_warm_band_prefix_on_engages / 装载点测试覆盖）。


def _band_chunk():
    """合成 BandChunk（矩形，members/offset 齐全 —— expand_placements 可真跑）。"""
    from materialsorting.nesting_engine.waist_band import BandChunk
    return BandChunk(
        pid='WB_g01', label='g01',
        polygon=[[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]],
        offset=(0.0, 0.0),
        members=[{'pid': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]}],
        fill_pct=100.0, bbox={'width_mm': 500.0, 'height_mm': 800.0},
        seed=0, d_g=0.0, tol_g=0.0)


def _stub_band(monkeypatch, capture: list):
    """band 构造桩：假 spyrrow（解含 WB_g01 条目）+ ``_build_band`` 直返合成
    BandChunk（真 build_band_plan 需弧片几何，合成矩形夹具会 BandError）。"""
    import materialsorting.web.solve_worker as sw
    chunk = _band_chunk()
    monkeypatch.setitem(sys.modules, 'spyrrow',
                        _fake_spyrrow_module(capture, ['WB_g01', 'g02_28']))

    def _band(pieces, gate, params, band_cfg, rq, _chunk=chunk):
        rq.put({'kind': 'stage', 'stage': 'band'})
        return _chunk

    monkeypatch.setattr(sw, '_build_band', _band)
    return chunk


# 组合宇宙：band on（label g01 整排除 + WB_g01 demand=1）下的完整解载荷。
_COMPOSITE_PAYLOAD = {
    'strip_width': 1500.0,
    'placed_items': [
        {'id': 'WB_g01', 'rotation': 0.0, 'translation': [0.0, 0.0]},
        {'id': 'g02_28', 'rotation': 180.0, 'translation': [600.0, 100.0]},
    ],
}


def test_worker_band_composite_payload_engages(monkeypatch):
    """二期主路径：band 开 + **组合视角**载荷（pid 宇宙 = {WB_g01, g02_28}）→
    宇宙复检通过、solve 收 ``json.dumps(payload)``、final 附 ``warm_state``
    engaged=True / reason=None；一期此处是硬 ``{kind:error}``（已删）。"""
    _set_warm(monkeypatch, True)
    capture: list = []
    _stub_band(monkeypatch, capture)
    q = _FakeQueue()
    solve_worker(_pieces(), 1980.0, dict(_SOLVE_PARAMS), q,
                 band={'label': 'g01'}, initial_solution=_COMPOSITE_PAYLOAD)
    msgs = _drain(q)
    kinds = [m['kind'] for m in msgs]
    assert 'error' not in kinds and kinds[-1] == 'final'
    assert capture == [{'initial_solution': json.dumps(_COMPOSITE_PAYLOAD)}]
    assert msgs[-1]['final']['warm_state'] == {'engaged': True, 'reason': None}


def test_worker_band_member_view_payload_degrades(monkeypatch, caplog):
    """二期防御：band 开 + **成员级**载荷（pid 宇宙错位 —— g01_28 已被整排除、
    WB_g01 缺席）→ worker 宇宙复检丢弃 + warn 降级普通重放（manifest→frame*→
    final 全链照常、solve 调用形与现行一致）+ final ``warm_state`` engaged=False
    / 'instance_mismatch'。"""
    _set_warm(monkeypatch, True)
    capture: list = []
    _stub_band(monkeypatch, capture)
    q = _FakeQueue()
    with caplog.at_level(logging.WARNING,
                         logger='materialsorting.web.solve_worker'):
        solve_worker(_pieces(), 1980.0, dict(_SOLVE_PARAMS), q,
                     band={'label': 'g01'}, initial_solution=_PAYLOAD)
    msgs = _drain(q)
    kinds = [m['kind'] for m in msgs]
    assert 'error' not in kinds and kinds[-1] == 'final'
    assert capture == [{}]                       # 载荷被丢弃：普通重放
    assert msgs[-1]['final']['warm_state'] == {'engaged': False,
                                               'reason': 'instance_mismatch'}
    assert any('载荷与本实例不匹配' in r.message for r in caplog.records)


def test_worker_record_composite_frame_bypass(monkeypatch):
    """record_composite 帧旁路：True + band 开 → 帧附 ``composite`` 段（展开前
    solver 原始条目含 WB_g01 + 组合 demand_map == 重建实例 {pid: demand}）；
    缺省 False（WS 路径形态）→ 帧**无该键** —— WB_/PS_ 不出进程哨兵。"""
    _set_warm(monkeypatch, True)
    capture: list = []
    _stub_band(monkeypatch, capture)
    q = _FakeQueue()
    solve_worker(_pieces(), 1980.0, dict(_SOLVE_PARAMS), q,
                 band={'label': 'g01'}, record_composite=True)
    frames = [m['report'] for m in _drain(q) if m['kind'] == 'frame']
    assert frames
    for fr in frames:
        # 对外契约面：placed_items 仍成员级（无 WB_ 泄漏）
        assert all(e['id'] != 'WB_g01' for e in fr['placed_items'])
        comp = fr['composite']
        assert [e['id'] for e in comp['placed_items']] == ['WB_g01', 'g02_28']
        assert comp['demand_map'] == {'WB_g01': 1, 'g02_28': 1}

    # WS 形态（缺省）：帧无 composite 键（哨兵）
    q2 = _FakeQueue()
    solve_worker(_pieces(), 1980.0, dict(_SOLVE_PARAMS), q2,
                 band={'label': 'g01'})
    frames2 = [m['report'] for m in _drain(q2) if m['kind'] == 'frame']
    assert frames2 and all('composite' not in fr for fr in frames2)


def test_worker_plain_payload_warm_state_engaged(fake_spyrrow, monkeypatch):
    """plain 路径（无 band/prefix）也回报 warm_state：装载点已校验过的载荷 →
    宇宙复检天然通过（worker 重建实例与主进程确定性同构）→ engaged=True；
    final 附键仅在 initial_solution 在场时（缺省 None 无键，零回归）。"""
    _set_warm(monkeypatch, True)
    q = _FakeQueue()
    solve_worker(_pieces(), 1980.0, dict(_SOLVE_PARAMS), q,
                 initial_solution=_PAYLOAD)
    msgs = _drain(q)
    assert msgs[-1]['kind'] == 'final'
    assert msgs[-1]['final']['warm_state'] == {'engaged': True, 'reason': None}

    q2 = _FakeQueue()
    solve_worker(_pieces(), 1980.0, dict(_SOLVE_PARAMS), q2)
    msgs2 = _drain(q2)
    assert msgs2[-1]['kind'] == 'final'
    assert 'warm_state' not in msgs2[-1]['final']


def test_worker_serialization_failure_degrades(fake_spyrrow, monkeypatch, caplog):
    """序列化失败防御降级（理论不可达 —— US-001 构造点保证纯 JSON）：非
    JSON 值混入 → 丢弃 + warn，普通重放照常，绝不带崩 worker。"""
    _set_warm(monkeypatch, True)
    bad_payload = {'strip_width': 1500.0, 'oops': {1, 2}}   # set 不可 JSON 序列化
    q = _FakeQueue()   # 同步队列：真 Queue 的 feeder 线程异步落管，get_nowait 有竞态
    with caplog.at_level(logging.WARNING, logger='materialsorting.web.solve_worker'):
        solve_worker(_pieces(), 1980.0, dict(_SOLVE_PARAMS), q,
                     initial_solution=bad_payload)
    kinds = [m['kind'] for m in _drain(q)]
    assert 'error' not in kinds and kinds[-1] == 'final'
    assert fake_spyrrow == [{}]
    assert any('序列化失败' in r.message for r in caplog.records)


# ------------------------------- solve_with_callback_proc（假 Process 进程内闭环）


class _FakeProcess:
    """伪 ``multiprocessing.Process``：``start()`` 在当前进程内同步执行 target
    （Windows spawn 不继承 monkeypatch，闭环必须在当前进程完成）；同步完成即
    ``is_alive()`` 恒 False。记录 args 供断言第 7 位。"""

    def __init__(self, *, target, args, name):
        self.target = target
        self.args = args
        self.name = name
        self.exitcode = 0

    def start(self) -> None:
        self.target(*self.args)

    def is_alive(self) -> bool:
        return False

    def terminate(self) -> None:
        pass

    def join(self, timeout=None) -> None:
        pass

    def kill(self) -> None:
        pass


class _FakeQueue:
    """伪 ``multiprocessing.Queue``：同步 list（无 feeder 线程 → drain 时序确定），
    Empty 语义与 solver 捕获的 ``queue.Empty`` 一致。"""

    def __init__(self):
        self._msgs: list = []

    def put(self, item) -> None:
        self._msgs.append(item)

    def get(self, timeout=None):
        return self.get_nowait()

    def get_nowait(self):
        if not self._msgs:
            raise _queue_mod.Empty()
        return self._msgs.pop(0)

    def cancel_join_thread(self) -> None:
        pass


@pytest.fixture
def fake_proc_runtime(monkeypatch):
    """Process + Queue 全换进程内桩：solve_with_callback_proc 全链（drain/终止
    finally/exitcode 兜底）在当前进程确定性闭环。"""
    monkeypatch.setattr(multiprocessing, 'Process', _FakeProcess)
    monkeypatch.setattr(multiprocessing, 'Queue', _FakeQueue)


def test_proc_args_tuple_carries_payload(fake_spyrrow, monkeypatch,
                                         fake_proc_runtime):
    """Process args 元组恰 8 位：第 5/6 位 band/prefix 缺省 None、第 7 位载荷
    **原样 dict**（dumps 在 worker 消费点）、第 8 位 record_composite（二期，
    缺省 False）；载荷经 args 抵达 worker 并以 JSON 字符串进 solve。"""
    _set_warm(monkeypatch, True)
    proc, final, _elapsed, err = web_solver.solve_with_callback_proc(
        _pieces(), 1980.0, dict(_SOLVE_PARAMS),
        on_manifest=lambda _m: None, on_report=lambda _r: None,
        initial_solution=_PAYLOAD)
    assert err is None and final is not None
    assert len(proc.args) == 8
    assert proc.args[4] is None and proc.args[5] is None
    assert proc.args[6] == _PAYLOAD                    # dict 原样，非字符串
    assert proc.args[7] is False                       # record_composite 缺省
    assert fake_spyrrow == [{'initial_solution': json.dumps(_PAYLOAD)}]


def test_proc_args_tuple_default_none(fake_spyrrow, fake_proc_runtime):
    """缺省不传 → args 第 7 位 None、第 8 位 False、solve 调用形零变化
    （现行回归锚点）。"""
    proc, final, _elapsed, err = web_solver.solve_with_callback_proc(
        _pieces(), 1980.0, dict(_SOLVE_PARAMS),
        on_manifest=lambda _m: None, on_report=lambda _r: None)
    assert err is None and final is not None
    assert len(proc.args) == 8
    assert proc.args[6] is None and proc.args[7] is False
    assert fake_spyrrow == [{}]


# ------------------------------------------- pipeline.solve_pieces 纯透传


class _FakeProcHandle:
    def is_alive(self) -> bool:
        return False

    def terminate(self) -> None:
        pass

    def join(self, timeout=None) -> None:
        pass

    @property
    def exitcode(self):
        return 0


def _fake_solver(captured: dict):
    """伪 solve_with_callback_proc：捕获 initial_solution/band/prefix 关键字，
    投一帧 + 完整 final（placed == Σdemand=2 过完整性校验）。"""
    def _impl(pieces, gate_mm, solve_params, *, on_manifest, on_report,
              on_process=None, band=None, prefix=None, initial_solution=None,
              **kw):
        captured['initial_solution'] = initial_solution
        captured['band'] = band
        captured['prefix'] = prefix
        if on_process is not None:
            on_process(_FakeProcHandle())
        on_manifest({'pid_meta': {}, 'total_area': 0.0, 'n_eroded': 0,
                     'gate_mm': float(gate_mm)})
        placed = [{'id': p['pid'], 'rotation': 0.0, 'translation': [0.0, 0.0]}
                  for p in pieces]
        fr = {'type': 'frame', 'elapsed': 0.1, 'phase': 'exploring',
              'density': 0.5, 'density_sparrow': 0.52, 'width_mm': 1000.0,
              'placed_items': placed}
        on_report(dict(fr))
        final = {'type': 'final', 'density': fr['density'],
                 'density_sparrow': fr['density_sparrow'],
                 'width_mm': fr['width_mm'], 'elapsed': fr['elapsed'],
                 'placed_items': placed}
        return _FakeProcHandle(), final, 42.0, None
    return _impl


def _run_dir_with_intermediate(tmp_path: Path) -> Path:
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    doc = {'source': 'synthetic.dxf', 'gate_mm': 1980.0, 'n_pieces': 2,
           'total_area_mm2': 520000.0, 'pieces': _pieces()}
    (run_dir / 'pieces_intermediate.json').write_text(
        json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return run_dir


def test_solve_pieces_passes_initial_solution(tmp_path, monkeypatch, fake_spyrrow):
    """solve_pieces 纯透传：dict 原样到达 solve 调用形（无 dumps、无校验 ——
    装载/校验单一装载点在 US-003 portfolio 层）；缺省 None 与现行调用形一致。"""
    from materialsorting.cli.pipeline import solve_pieces

    run_dir = _run_dir_with_intermediate(tmp_path)
    cfg = types.SimpleNamespace(time=2, sizes=None, per_type=None,
                                 quantities=None, band=None, prefix=None)
    captured: dict = {}
    monkeypatch.setattr(web_solver, 'solve_with_callback_proc',
                        _fake_solver(captured))

    rec = solve_pieces(cfg, run_dir, seed=0, initial_solution=_PAYLOAD)
    assert captured['initial_solution'] == _PAYLOAD
    assert captured['band'] is None and captured['prefix'] is None
    assert rec['placed_items'] == 2                          # 完整解照常交付

    solve_pieces(cfg, run_dir, seed=1)
    assert captured['initial_solution'] is None


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))

