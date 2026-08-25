"""US-004 web 后端策略桥接 —— spawn ``ms-run-config --strategy`` 子进程 + HTTP 轮询。

四路由（``register_strategy_routes(app)`` 由 ``server.py`` 文件尾注册）：

  - ``POST /api/strategy/start``：校验（单例 409 / _PIECES_STATE 非空且 doc 含
    doc_id 422 / mode ∈ {se,race} / minutes ∈ {10,20,30,60} / band 经
    ``routes_ws._parse_band`` 同一校验点 / prefix 经 ``routes_ws._parse_prefix``
    同一校验点）→ **清理上一轮 web 产物**
    （``_cleanup_stale_web_artifacts``：web_* run 目录 + 旧 cfg + 旧 stderr，
    磁盘占用收敛到 ≤1 个 run_dir；2026-08-22）→ 写 9 键 config JSON
    到 ``out/uploads/strategy_cfg_<stamp>.json`` → spawn
    ``python -m materialsorting.cli.run_config <cfg> --name web_<mode>_<rand6>
    --strategy <mode> --time <minutes*60> --quiet``（stdout=DEVNULL、stderr=临时文件）
    → 快照 ``out/config_runs/`` → 写 marker ``.web_strategy_active.json`` → 202。
  - ``GET /api/strategy/status``：无状态惰性轮询（不缓存中间态，每次现读 run_dir
    产物；进度源只用 strategy.json / result.json / best_frame_s*.json /
    kill_decisions.jsonl —— ``curve_s*.json`` 运行中非合法 JSON 缺右括号，不读）。
  - ``POST /api/strategy/stop``：树杀（Windows ``taskkill /PID <pid> /T /F``、
    POSIX ``os.killpg`` —— run_config 会再 spawn 多进程 solve 孙进程，单杀父进程
    会留孙进程白烧 CPU）+ 置 stopped + 清 marker。
  - ``GET /api/strategy/result``（done/stopped）：读 result.json
    portfolio.incumbent（完整 placed_items；stopped 态缺失回落各 best_frame 取
    最大）+ ``build_pid_meta``（start 时快照口径）组装 manifest。

分层合规：web 禁 import ``..cli.*`` 是 **import 边界**（AST 守卫，镜像
test_cli_portfolio 写法）；spawn 子进程是**进程边界**，不触发守卫 —— 判据逻辑
（race 门杀 / se 筛延）单一真相源留在 ``cli.portfolio``，零漂移。

状态机：``idle → starting →(run_dir 发现) running → done | stopped | error``；
内存态空 + marker 在 → ``orphan``（server 重启后遗留 run：pid 存活探测，由前端
提供清理动作）。终态（done/stopped/error）清 marker、保留 ``_STRATEGY_STATE``
供 status/result 续读，下一次 start 覆盖。
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from .. import paths
from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
from .solver import build_pid_meta

__all__ = ['register_strategy_routes']

STRATEGY_MODES = ('se', 'race')
ALLOWED_MINUTES = (10, 20, 30, 60)
# run_dir 发现宽限（秒）：spawn 后 CLI 先做 config 校验 + commit（秒级）才建
# run_dir；超过该时长仍未发现且进程已死 → error + stderr 尾部。
RUN_DIR_GRACE_SEC = 30.0
# events 尾部窗口（条）：kill 决策逐条 + 逐 seed 收尾，长跑可积累大量事件，
# status 载荷只保留尾部。
_EVENTS_TAIL = 20
_STDERR_TAIL_CHARS = 2000
_TERMINAL_STATES = ('done', 'stopped', 'error')

# 进程级单例状态（模块级，进程生命周期内唯一）。start 覆写、终态保留（status /
# result 续读）、stop 置 stopped。
_STRATEGY_STATE: dict = {}

_MARKER_NAME = '.web_strategy_active.json'


def _config_runs_dir() -> Path:
    """CLI run 产物根（marker 落点 + run_dir 发现扫描范围）。"""
    return Path(paths.CONFIG_RUNS_DIR)


def _marker_path() -> Path:
    return _config_runs_dir() / _MARKER_NAME


def _uploads_dir() -> Path:
    return Path(paths.OUT_DIR) / 'uploads'


def _read_marker() -> dict | None:
    """读 marker（无 / 坏 JSON → None，容错不抛）。"""
    p = _marker_path()
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding='utf-8'))
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_marker(payload: dict) -> None:
    _config_runs_dir().mkdir(parents=True, exist_ok=True)
    _marker_path().write_text(
        json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def _clear_marker() -> None:
    try:
        _marker_path().unlink(missing_ok=True)
    except OSError:
        pass


def _read_json(path):
    """容错读 JSON（缺文件 / 坏 JSON → None）。"""
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


# ------------------------------------------------------------- 进程存活 / 树杀


def _pid_alive(pid) -> bool:
    """pid 存活探测（orphan 分支用 —— 不是本进程 Popen 的孩子，无法 poll()）。

    Windows：``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`` 句柄探测；POSIX：
    ``os.kill(pid, 0)``（Signal 0 = 探测不发送）。pid 非法 / 已死 → False。
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        k32 = ctypes.windll.kernel32    # type: ignore[attr-defined]
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        k32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_tree(pid) -> None:
    """树杀（防 run_config spawn 的多进程 solve 孙进程白烧 CPU）。

    Windows ``taskkill /PID <pid> /T /F``（/T 整树 /F 强杀）；POSIX 用独立进程组
    ``os.killpg``（spawn 时 ``start_new_session=True``）。pid 非法 / 进程已死 → no-op。
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    if pid <= 0:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                       capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _spawn_run_process(cmd: list[str], stderr_path: str):
    """spawn CLI 子进程（stdout=DEVNULL、stderr=临时文件；测试 monkeypatch 点）。"""
    kwargs: dict = {}
    if os.name != 'nt':
        kwargs['start_new_session'] = True   # 独立进程组 → stop 走 killpg 树杀
    with open(stderr_path, 'w', encoding='utf-8') as err_f:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=err_f,
                                **kwargs)


def _stderr_tail(stderr_path) -> str | None:
    """stderr 临时文件尾部（error 诊断用；无内容 → None）。"""
    if not stderr_path:
        return None
    try:
        text = Path(stderr_path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    text = text.strip()
    return text[-_STDERR_TAIL_CHARS:] if text else None


# ------------------------------------------------------------- 旧产物清理


def _cleanup_stale_web_artifacts() -> None:
    """清理上一轮 web 策略 run 的落盘产物（best-effort，失败不阻塞 start）。

    仅在 start 通过单例闸门（无 in-flight run / 无 marker）后调用，此刻以下产物
    均已无人消费（done/stopped 的 result 已被前端拉走或随下次 start 一并作废）：

      - ``out/config_runs/web_*`` run 目录 —— 本模块 spawn 的 run_name 恒为
        ``web_<mode>_<rand6>`` 前缀，手工 ``ms-run-config`` 的 run 目录不带该
        前缀，不受影响；
      - ``out/uploads/strategy_cfg_*.json`` —— start 写给 CLI 的一次性 config；
      - 系统临时目录 ``web_strategy_err_*.log`` —— spawn stderr 重定向文件
        （本进程前缀唯一；多实例并跑的活动文件在 Windows 下句柄占用 unlink 自然
        失败，best-effort 容错）。

    效果：web 策略产物磁盘占用从无限累积收敛到 ≤1 个 run_dir；done → 下一次
    start 之间 run_dir 仍可被 status/result 复读（页面刷新后重开弹窗拉 result
    的路径不受影响），与前端「下一次 start 清 result store」时点对齐。清理先于
    新 cfg / 新 stderr 创建，不会误删本轮文件。
    """
    for entry in _config_runs_dir().glob('web_*'):
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
    for cfg in _uploads_dir().glob('strategy_cfg_*.json'):
        try:
            cfg.unlink()
        except OSError:
            pass
    for err in Path(tempfile.gettempdir()).glob('web_strategy_err_*.log'):
        try:
            err.unlink()
        except OSError:
            pass


def _pieces_state() -> dict:
    """当前排料裁片状态（对 ``server._get_pieces_state`` 的延迟取用）。

    延迟 import 破环：``server.py`` 在**文件尾**才 import 本模块（注册路由），
    若本模块模块级 import server 则「先 import strategy」路径成环报错；路由调用
    时 server 必已完整初始化，函数内 import 安全。
    """
    from .server import _get_pieces_state
    return _get_pieces_state()


# ------------------------------------------------------------- run_dir 发现


def _snapshot_config_runs() -> set:
    """start 时刻 ``out/config_runs/`` 目录名快照（缺目录 → 空集）。"""
    base = _config_runs_dir()
    try:
        return {e for e in os.listdir(base) if (base / e).is_dir()}
    except OSError:
        return set()


def _discover_run_dir(snapshot) -> str | None:
    """快照 diff 发现新 run_dir（忽略 marker 等非目录项；多个新目录取 mtime 最新）。

    spawn 传入 ``--name web_<mode>_<rand6>``，run_dir = ``<name>_<时间戳>`` 由 CLI
    创建 —— 无法预知时间戳，只能事后 diff。并发手工 CLI run 同期建目录理论上可误
    认（单用户工作台场景概率可忽略；marker 锁进程级单例已挡住第二次 web run）。
    """
    base = _config_runs_dir()
    try:
        entries = os.listdir(base)
    except OSError:
        return None
    candidates = [base / e for e in entries
                  if e not in snapshot and (base / e).is_dir()]
    if not candidates:
        return None
    return str(max(candidates, key=lambda p: p.stat().st_mtime))


# ------------------------------------------------------------- 产物解析


def _parse_plan(run_dir):
    """strategy.json → plan 摘要（planned_seeds + race.gate_seconds | se 三键）。"""
    if not run_dir:
        return None
    sj = _read_json(Path(run_dir) / 'strategy.json')
    if not isinstance(sj, dict):
        return None
    plan = {'planned_seeds': sj.get('planned_seeds')}
    if isinstance(sj.get('race'), dict):
        plan['gate_seconds'] = sj['race'].get('gate_seconds')
    if isinstance(sj.get('se'), dict):
        plan.update({'k_screens': sj['se'].get('k_screens'),
                     'screen_s': sj['se'].get('screen_s'),
                     'ext_s': sj['se'].get('ext_s')})
    return plan


def _parse_incumbent_summary(result_json):
    """result.json portfolio.incumbent → 无 placed_items 的摘要（控载荷）。"""
    if not isinstance(result_json, dict):
        return None
    inc = (result_json.get('portfolio') or {}).get('incumbent')
    if not isinstance(inc, dict):
        return None
    return {k: inc.get(k) for k in
            ('density', 'width_mm', 'seed', 'frame_index', 'elapsed')}


def _parse_per_seed(result_json) -> list:
    if not isinstance(result_json, dict):
        return []
    ps = (result_json.get('portfolio') or {}).get('per_seed')
    return ps if isinstance(ps, list) else []


def _parse_current(run_dir):
    """最新 mtime ``best_frame_s*.json`` → {seed, density, density_sparrow, ext}。"""
    if not run_dir:
        return None
    files = list(Path(run_dir).glob('best_frame_s*.json'))
    if not files:
        return None
    latest = max(files, key=lambda p: p.stat().st_mtime)
    rec = _read_json(latest)
    if not isinstance(rec, dict):
        return None
    return {'seed': rec.get('seed'), 'density': rec.get('density'),
            'density_sparrow': rec.get('density_sparrow'),
            'ext': latest.stem.endswith('_ext')}


def _parse_events(run_dir, result_json) -> list:
    """事件流：kill_decisions R5 门杀 + extension（ext 边车）+ seed_done（per_seed）。

    只保留尾部窗口（``_EVENTS_TAIL`` 条）—— 前端展示「最近 1 条事件行」用，
    长跑不撑爆 status 载荷。
    """
    events: list = []
    if run_dir:
        kd = Path(run_dir) / 'kill_decisions.jsonl'
        try:
            for line in kd.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get('rule') == 'R5_race_gate':
                    events.append({'kind': 'gate', 'seed': rec.get('seed'),
                                   't': rec.get('t'), 'd': rec.get('d'),
                                   'bar': rec.get('S_tau'),
                                   'would_kill': rec.get('would_kill')})
        except OSError:
            pass
        for ext_file in sorted(Path(run_dir).glob('best_frame_s*_ext.json')):
            # 文件名 best_frame_s{seed}_ext → 提取 seed。
            seed_txt = ext_file.stem[len('best_frame_s'):-len('_ext')]
            try:
                events.append({'kind': 'extension', 'seed': int(seed_txt)})
            except ValueError:
                continue
    for entry in _parse_per_seed(result_json):
        events.append({'kind': 'seed_done', 'seed': entry.get('seed'),
                       'phase': entry.get('phase'),
                       'best_density': entry.get('best_density'),
                       'killed': bool(entry.get('killed'))})
    return events[-_EVENTS_TAIL:]


def _elapsed_from_iso(started_at):
    try:
        return time.time() - datetime.fromisoformat(str(started_at)).timestamp()
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------- 路由 handlers


async def strategy_start(req: Request):
    """启动策略 run（进程级单例；spawn CLI 子进程后立即 202 返回）。"""
    try:
        payload = await req.json()
    except Exception:
        return JSONResponse({'error': '请求体须为 JSON'}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({'error': '请求体须为 JSON 对象'}, status_code=400)

    # 进程级单例：内存态非终态（starting/running）或 marker 在（含 orphan 遗留）→ 409。
    in_flight = _STRATEGY_STATE.get('state') not in (None, *_TERMINAL_STATES)
    if in_flight or _read_marker() is not None:
        return JSONResponse(
            {'error': '已有进行中的策略运行（或检测到遗留 marker），请先停止/清理'},
            status_code=409)

    # 排料数据校验：state 空 → 422；doc 缺 doc_id（旧 intermediate）→ 422。
    state = _pieces_state()
    pieces = state.get('pieces') or []
    gate_state = state.get('gate_mm') or 0.0
    if not pieces or gate_state <= 0:
        return JSONResponse(
            {'error': '排料数据为空（请先上传解析母版并 commit）'}, status_code=422)
    doc_id = (state.get('doc') or {}).get('doc_id')
    master = _uploads_dir() / f'{doc_id}.dxf' if doc_id else None
    if not doc_id or master is None or not master.is_file():
        return JSONResponse(
            {'error': '母版信息缺少 doc_id，请重新上传并 commit'}, status_code=422)

    mode = payload.get('mode')
    if mode not in STRATEGY_MODES:
        return JSONResponse(
            {'error': f'mode 须为 se 或 race，当前为 {mode!r}'}, status_code=400)
    minutes = payload.get('minutes')
    if minutes not in ALLOWED_MINUTES:
        return JSONResponse(
            {'error': 'minutes 须为 10/20/30/60 之一，'
                      f'当前为 {minutes!r}'}, status_code=400)

    seed = payload.get('seed', 0)
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        return JSONResponse({'error': f'seed 须为整数，当前为 {seed!r}'},
                            status_code=400)

    # gate_mm：请求值优先（>0 覆盖），非法/未传回退 state（与 /ws/solve 同口径）。
    gate_mm = gate_state
    req_gate = payload.get('gate_mm')
    if req_gate:
        try:
            g = float(req_gate)
            if g > 0:
                gate_mm = g
        except (TypeError, ValueError):
            pass

    sizes = payload.get('sizes')
    if sizes is not None and (not isinstance(sizes, list) or not sizes):
        return JSONResponse({'error': 'sizes 须为非空码号列表'}, status_code=400)
    per_type = payload.get('per_type')
    if per_type is not None and not isinstance(per_type, dict):
        return JSONResponse({'error': 'per_type 须为对象'}, status_code=400)
    quantities = payload.get('quantities')
    if quantities is not None and not isinstance(quantities, dict):
        return JSONResponse({'error': 'quantities 须为对象'}, status_code=400)

    # 腰头成带（2026-08-22 与策略模式解除互斥）：复用 routes_ws._parse_band 单一
    # 校验点（label ^g\d+$ / 存在于当前母版 / 该 g 码 quantities>0），非法 → 400
    # 结构化早退；合法开启 → 以 StartPayload 原形态写进 config JSON（cli.config
    # 9 键 schema 的 band 键）。null / enabled falsy → _parse_band 返回 None，
    # 不写键（旧行为）。延迟 import：routes_ws → runtime → server 链若在模块级
    # import 本模块（server.py 文件尾注册路由）之外再正向引用会成环，函数内取用
    # 安全（同 _pieces_state 模式）。
    band_cfg = None
    if payload.get('band') is not None:
        from .routes_ws import _parse_band
        try:
            worker_band = _parse_band(payload.get('band'), pieces, quantities)
        except ValueError as e:
            return JSONResponse({'error': str(e)}, status_code=400)
        if worker_band is not None:
            band_cfg = {'enabled': True, 'label': worker_band['label']}

    # 起始端成套前后幅（2026-08-25 与策略模式解除互斥，band 同款）：复用
    # routes_ws._parse_prefix 单一校验点（front/back ^g\d+$ 且存在于当前母版且
    # front≠back + **2+2 资格码 ≥1**（sizes = 用户所排尺码过滤）—— start 期
    # 拦下避免 20 分钟长跑空烧），非法 → 400 结构化早退；合法开启 → 以
    # StartPayload 原形态写进 config JSON（cli.config 9 键 schema 的 prefix 键）。
    # null / enabled falsy → _parse_prefix 返回 None，不写键（旧行为）。延迟
    # import 防成环（同上 _parse_band）。
    prefix_cfg = None
    if payload.get('prefix') is not None:
        from .routes_ws import _parse_prefix
        try:
            worker_prefix = _parse_prefix(payload.get('prefix'), pieces,
                                          quantities, sizes)
        except ValueError as e:
            return JSONResponse({'error': str(e)}, status_code=400)
        if worker_prefix is not None:
            prefix_cfg = {'enabled': True, 'front': worker_prefix['front'],
                          'back': worker_prefix['back']}

    # 9 键 config JSON（cli.config.load_config 严格校验；可选键仅在有值时写入 ——
    # None 值会被 load_config 按类型错误拒绝）。
    cfg_payload = {
        'master_dxf': str(master.resolve()),
        'gate_mm': float(gate_mm),
        'time': int(minutes) * 60,
        'seeds': [seed],
    }
    if sizes:
        cfg_payload['sizes'] = sizes
    if per_type:
        cfg_payload['per_type'] = per_type
    if quantities:
        cfg_payload['quantities'] = quantities
    if band_cfg is not None:
        cfg_payload['band'] = band_cfg
    if prefix_cfg is not None:
        cfg_payload['prefix'] = prefix_cfg

    # 上一轮 web 策略 run 的产物清理（2026-08-22）：单例闸门已过 → 无 in-flight
    # run，web_* run 目录 / 旧 cfg / 旧 stderr 均无人消费；清理先于本轮 cfg /
    # stderr / run_dir 创建，不会误删本轮文件。best-effort，失败不阻塞 start。
    _cleanup_stale_web_artifacts()

    stamp = time.strftime('%Y%m%d-%H%M%S')
    rand6 = uuid.uuid4().hex[:6]
    _uploads_dir().mkdir(parents=True, exist_ok=True)
    cfg_path = _uploads_dir() / f'strategy_cfg_{stamp}.json'
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg_payload, f, ensure_ascii=False)

    run_name = f'web_{mode}_{rand6}'
    stderr_file = tempfile.NamedTemporaryFile(
        prefix='web_strategy_err_', suffix='.log', delete=False)
    stderr_file.close()
    cmd = [sys.executable, '-m', 'materialsorting.cli.run_config',
           str(cfg_path), '--name', run_name,
           '--strategy', mode, '--time', str(int(minutes) * 60), '--quiet']
    # 快照先于 spawn：run_dir 基线 = spawn 决策前的目录集 —— CLI 建 run_dir 再快也
    # 必然落在基线之后被发现（若快照晚于 spawn，CLI 抢先建目录会让 diff 扑空）。
    snapshot = _snapshot_config_runs()
    proc = _spawn_run_process(cmd, stderr_file.name)

    started_at = time.strftime('%Y-%m-%dT%H:%M:%S')
    _write_marker({'pid': proc.pid, 'run_dir': None, 'doc_id': doc_id,
                   'mode': mode, 'started_at': started_at})

    _STRATEGY_STATE.clear()
    _STRATEGY_STATE.update({
        'state': 'starting',
        'proc': proc,
        'pid': proc.pid,
        'mode': mode,
        'minutes': int(minutes),
        'total_budget_sec': int(minutes) * 60,
        'started_at': started_at,
        'started_ts': time.time(),
        'run_dir': None,
        'snapshot': snapshot,
        'stderr_path': stderr_file.name,
        'doc_id': doc_id,
        # start 时快照（result 组装 manifest 用同口径，不依赖前端二次回传）。
        'pieces_snapshot': [dict(p) for p in pieces],
        'sizes': sizes or None,
        'per_type': per_type or None,
        'quantities': quantities or None,
        'gate_mm': float(gate_mm),
        'seed': seed,
        'cfg_path': str(cfg_path),
        'run_name': run_name,
        'stopped': False,
        'exit_code': None,
        'error': None,
    })
    return JSONResponse({'started': True, 'pid': proc.pid, 'mode': mode,
                         'minutes': int(minutes), 'run_name': run_name},
                        status_code=202)


def _status_from_active(st: dict) -> dict:
    """内存态（start 后）→ status 载荷；终态顺手清 marker（幂等）。"""
    proc = st.get('proc')
    rc = proc.poll() if proc is not None else None
    elapsed = time.time() - float(st.get('started_ts') or time.time())

    # run_dir 发现（starting 期每轮 status 重试 diff；发现后写回 state + marker）。
    run_dir = st.get('run_dir')
    if not run_dir:
        run_dir = _discover_run_dir(st.get('snapshot') or set())
        if run_dir:
            st['run_dir'] = run_dir
            marker = _read_marker()
            if marker is not None:
                marker['run_dir'] = run_dir
                _write_marker(marker)

    state: str
    error = None
    if st.get('stopped'):
        state = 'stopped'
    elif rc is None:
        # 存活：starting（run_dir 未发现）/ running（已发现，产物可读）。
        state = 'running' if run_dir else 'starting'
    else:
        st['exit_code'] = rc
        result_json = (_read_json(Path(run_dir) / 'result.json')
                       if run_dir else None)
        if result_json is not None:
            state = 'done'
        else:
            state = 'error'
            tail = _stderr_tail(st.get('stderr_path'))
            error = '子进程异常退出（未产出 result.json）'
            if not run_dir and elapsed > RUN_DIR_GRACE_SEC:
                error = (f'启动 {elapsed:.0f}s 后仍未发现 run 目录'
                         f'（>{RUN_DIR_GRACE_SEC:g}s 宽限），子进程已退出')
            if tail:
                error = f'{error}；stderr 尾部: {tail}'
            st['error'] = error

    # 状态写回（终态固化：start 单例检查 / stop 分支按 st['state'] 裁决，若不写回
    # 则「跑完后从未轮询」的内存态永远停在 running）。
    st['state'] = state
    if state in _TERMINAL_STATES:
        _clear_marker()

    result_json = (_read_json(Path(run_dir) / 'result.json')
                   if run_dir else None)
    return {
        'state': state,
        'mode': st.get('mode'),
        'total_budget_sec': st.get('total_budget_sec'),
        'elapsed_sec': round(elapsed, 1),
        'run_dir': run_dir,
        'plan': _parse_plan(run_dir),
        'incumbent': _parse_incumbent_summary(result_json),
        'current': _parse_current(run_dir),
        'per_seed': _parse_per_seed(result_json),
        'events': _parse_events(run_dir, result_json),
        'error': error if state == 'error' else st.get('error'),
        'exit_code': st.get('exit_code'),
    }


async def strategy_status():
    """无状态惰性轮询：每次现读 run_dir 产物组装（不缓存中间态）。"""
    if not _STRATEGY_STATE:
        marker = _read_marker()
        if marker is None:
            return {'state': 'idle'}
        # orphan：内存态空 + marker 在（server 重启后的遗留 run）。pid 存活探测；
        # run_dir 已发现过的（marker 带回）仍可解析产物，前端提供清理动作。
        elapsed = _elapsed_from_iso(marker.get('started_at'))
        run_dir = marker.get('run_dir') or None
        result_json = (_read_json(Path(run_dir) / 'result.json')
                       if run_dir else None)
        return {
            'state': 'orphan',
            'alive': _pid_alive(marker.get('pid')),
            'pid': marker.get('pid'),
            'mode': marker.get('mode'),
            'doc_id': marker.get('doc_id'),
            'run_dir': run_dir,
            'elapsed_sec': None if elapsed is None else round(max(elapsed, 0.0), 1),
            'plan': _parse_plan(run_dir),
            'incumbent': _parse_incumbent_summary(result_json),
            'current': _parse_current(run_dir),
            'per_seed': _parse_per_seed(result_json),
            'events': _parse_events(run_dir, result_json),
            'error': None,
            'exit_code': None,
        }
    return _status_from_active(_STRATEGY_STATE)


async def strategy_stop():
    """树杀进行中的策略 run（或清理 orphan marker）。"""
    st = _STRATEGY_STATE
    if st.get('state') in ('starting', 'running'):
        pid = st.get('pid')
        _kill_tree(pid)
        st['state'] = 'stopped'
        st['stopped'] = True
        _clear_marker()
        return {'stopped': True, 'pid': pid}
    marker = _read_marker()
    if marker is not None:
        pid = marker.get('pid')
        if _pid_alive(pid):
            _kill_tree(pid)
        _clear_marker()
        return {'stopped': True, 'pid': pid, 'orphan': True}
    return JSONResponse({'error': '没有进行中的策略运行'}, status_code=400)


async def strategy_result():
    """done/stopped run → 最优方案 + manifest（US-006 应用到主画布的数据源）。"""
    st = _STRATEGY_STATE
    if not st or st.get('state') not in ('done', 'stopped'):
        if st and st.get('state') in ('starting', 'running'):
            return JSONResponse({'error': '策略运行尚未结束'}, status_code=409)
        return JSONResponse({'error': '暂无已完成的策略运行结果'}, status_code=404)

    run_dir = st.get('run_dir')
    if not run_dir:
        return JSONResponse({'error': '运行未产出 run 目录，无结果可读'},
                            status_code=409)
    result_json = _read_json(Path(run_dir) / 'result.json')

    # best：优先 result.json portfolio.incumbent（完整 placed_items）；stopped 态
    # 缺失（首轮 seed 未完成 → 无 result.json / 空 portfolio 段）→ 回落各
    # best_frame_s*.json 取 density 最大。
    best = None
    if isinstance(result_json, dict):
        inc = (result_json.get('portfolio') or {}).get('incumbent')
        if isinstance(inc, dict):
            best = dict(inc)
    if best is None:
        frames = []
        for fp in Path(run_dir).glob('best_frame_s*.json'):
            rec = _read_json(fp)
            if isinstance(rec, dict) and rec.get('density') is not None:
                frames.append(rec)
        if frames:
            best = max(frames, key=lambda r: float(r['density']))
    if best is None:
        return JSONResponse({'error': '运行未产出任何布局（无 incumbent/best_frame）'},
                            status_code=409)

    # incumbent 无 density_sparrow（帧入账只存原面积口径）→ 从同 seed best_frame 边车补。
    density_sparrow = None
    bf = _read_json(Path(run_dir) / f"best_frame_s{best.get('seed')}.json")
    if isinstance(bf, dict):
        density_sparrow = bf.get('density_sparrow')
    best_out = {
        'seed': best.get('seed'),
        'frame_index': best.get('frame_index'),
        'elapsed': best.get('elapsed'),
        'density': best.get('density'),
        'density_sparrow': density_sparrow,
        'width_mm': best.get('width_mm'),
        'placed_items': best.get('placed_items') or [],
    }

    # manifest：start 时快照口径 build_pid_meta（erode 后几何与 placed_items 对齐、
    # demand 已含），与 /ws/solve manifest.pieces 同形（id/size/color/area_mm2/
    # polygon 5 层/label/demand）。
    pid_meta, total_area, n_eroded = build_pid_meta(
        st.get('pieces_snapshot') or [],
        sizes=st.get('sizes'), per_type=st.get('per_type'),
        quantities=st.get('quantities'))
    gate_mm = float(st.get('gate_mm') or 0.0)
    manifest = {
        'gate_mm': gate_mm,
        'gate_nest_mm': min(gate_mm, PLOT_SAFE_MAX_Y_MM),
        'total_area_mm2': total_area,
        'n_eroded': n_eroded,
        'pieces': [
            {'id': pid, 'size': meta['size'], 'color': meta['color'],
             'area_mm2': meta['area_mm2'], 'polygon': meta['polygon'],
             'label': meta.get('label'), 'demand': meta.get('demand', 1),
             'net_polygon': meta.get('net_polygon', []),
             'internal_lines': meta.get('internal_lines', []),
             'notches': meta.get('notches', []),
             'grain_line': meta.get('grain_line')}
            for pid, meta in pid_meta.items()
        ],
    }

    portfolio = (result_json or {}).get('portfolio') or {}
    summary = {'per_seed': portfolio.get('per_seed') or [],
               'mode': portfolio.get('mode')}
    if portfolio.get('race') is not None:
        summary['race'] = portfolio['race']
    if portfolio.get('se') is not None:
        summary['se'] = portfolio['se']

    payload = {'state': st.get('state'), 'mode': st.get('mode'),
               'run_dir': run_dir, 'manifest': manifest,
               'best': best_out, 'summary': summary}
    # 母版漂移检测：start 快照 doc_id ≠ 当前画布 doc_id → 应用结果可能与当前画布
    # 不一致（前端结果态展示 warning；导出 pid 失配走既有 400 兜底）。
    cur_doc_id = (_pieces_state().get('doc') or {}).get('doc_id')
    if st.get('doc_id') != cur_doc_id:
        payload['warning'] = '母版已变更，应用结果可能与当前画布不一致'
    return payload


def register_strategy_routes(app) -> None:
    """把四路由挂到 FastAPI app（server.py 文件尾调用一次）。"""
    app.post('/api/strategy/start')(strategy_start)
    app.get('/api/strategy/status')(strategy_status)
    app.post('/api/strategy/stop')(strategy_stop)
    app.get('/api/strategy/result')(strategy_result)

