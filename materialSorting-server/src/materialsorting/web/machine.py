"""机器对接排料 API（YL 排料对接二期，prd-machine-nesting-api）—— US-003 status/stop/result 三端点。

YLPatternMaking（YL 打版系统）后端经 HTTP 机器接口接入 MS 排料引擎：multipart
提交带编号母版 DXF + config JSON → 按运行模式求解 → 2s 级轮询实时利用率 → 终态
取完整布局 → 会话无关导出 PLT。**机器任务 = strategy 家族第三成员
（``mode='machine'``，常量 ``strategy.MACHINE_MODE``）**：经模块属性访问复用
``strategy.py`` 的每会话状态槽 ``_STRATEGY_STATES`` / marker / run_dir 发现 /
树杀 / 清理骨架 —— 与 se|race / extreme 同构，但**每任务一个 'm' 前缀独立 sid**
（不消费 X-Session-Id，浏览器工作台 default ``_PIECES_STATE`` 零感知）。

端点契约（US-002 solve + 本故事三端点已落地；export/DELETE 自 US-004 起挂载）：

  - ``POST   /api/machine/solve`` —— multipart ``file``（母版 DXF 二进制
    ≤20MB，同 /api/parse-dxf 上限）+ ``config``（JSON 字符串）。config 键集：
    ``gate_mm`` 必填 int>0；``run_mode`` ∈ normal|advanced|extreme 缺省 normal；
    ``sizes`` int[]；``per_type`` {g码:{d,tol}}；``quantities`` {g码:{码号:int≥0}}；
    ``client_ref`` str≤128 幂等键。流程：校验（400/413 结构化早退）→ 同
    ``client_ref`` 在飞 409（返回既有 task_id）→ 铸 sid（'m'+时间戳+rand，满足
    sessions.SID_RE）→ 保存上传 ``out/uploads/<doc_id>.dxf`` → 复用 server
    parse+commit 管线（函数内延迟 import；带 sid 只挂本会话，不碰 default
    ``_PIECES_STATE``；坏 DXF → 422 中文）→ 写 cfg → spawn → 写 marker
    ``.web_strategy_active_<sid>.json``（恰 5 键，mode='machine'）→
    ``202 {task_id, run_name, started_at}``（task_id 即 sid）；run_name =
    ``machine_<task6>_<rand6>``（task6 = task_id 前 6 位，rand6 唯一 —— run_dir
    认领前缀 glob 无歧义，同 strategy 口径）。
  - ``GET    /api/machine/solve/{task_id}/status``（本故事）—— 轮询任务状态：
    ``{state, mode:'machine', run_mode, total_budget_sec, elapsed_sec, incumbent,
    current, per_seed, error, exit_code}``。**无 placed_items（控载荷）**；进度源
    只读 result.json / best_frame_s*.json（mtime + 内容），**绝不读运行中的
    curve_s*.json**（逐帧 append 非合法 JSON）。``incumbent`` = 实时最优（物理
    毛版包络口径 density，``solver._apply_density_dual`` 单一权威，与 result.json
    一致，不可与历史 erode 口径混比）：portfolio.incumbent 优先（race/se 档），
    运行中 / plain（normal）run 回落各 best_frame 边车 density 最大帧 ——
    normal 档 result.json 的 portfolio.incumbent 恒 null 且 per_seed 空（plain
    run 不激活 portfolio 引擎，US-002 实测），四键 ``{density,width_mm,seed,
    frame_index}``。轮询即活性：会话仍在注册表 → ``touch`` 刷 last_active
    （no-op 容错）—— 无人轮询超 MS_SESSION_TTL_SEC+宽限 → 会话逐出，status 仍
    200（本家族**不走会话闸门**，``_STRATEGY_STATES`` 内存态路径）。
  - ``POST   /api/machine/solve/{task_id}/stop``（本故事）—— 树杀
    （Windows ``taskkill /PID /T /F`` / POSIX ``os.killpg``，防 run_config
    spawn 的 solve 孙进程白烧 CPU），run_dir 保留（stopped 态 result 仍可读）；
    orphan marker（MS 重启后遗留）同样可 stop/清理。
  - ``GET    /api/machine/solve/{task_id}/result``（本故事）—— 终态取
    ``{manifest, best, summary}``；running → 409。``best.placed_items`` 为
    solver 原始布局（demand>1 的 g 码 N 条**绝不按 pid 去重** —— YL 前端须建
    N 副本承接）；stopped / plain（normal）档无 portfolio.incumbent → 各
    ``best_frame_s*.json`` 边车 density 最大回落（完整 placed_items 在边车）。
    manifest = ``build_pid_meta``（start 时起始快照 pieces + sizes/per_type/
    quantities），pieces 键集含 raw_polygon/d_mm/demand/color（与 /ws/solve
    manifest 同形）。
  - ``POST   /api/machine/export`` / ``DELETE /api/machine/solve/{task_id}``
    —— 会话无关导出（pieces 直载 run_dir pieces_intermediate.json，独立于会话
    TTL；fmt 缺省 'plt-clean' + 服务端全算表格）与幂等清理（US-004/005）。

任务状态机（同 strategy 口径，复用 ``_status_common`` 状态推进 —— 解析态写回
内存态）：``starting →(run_dir 发现) running → done | stopped | error``。内存态
空 + 本 sid marker 在 → ``orphan``（MS 重启后遗留 run）：pid 存活 → orphan 可
stop；pid 死 + 超 ``RUN_DIR_GRACE_SEC``（30s）宽限 → ``error``（stderr 尾
best-effort —— marker 恰 5 键不含 stderr 路径，重启后无从定位临时文件）。
orphan 态 ``run_mode``/``total_budget_sec`` 经 ``machine_cfg_<sid>_*.json`` 的
time 键反查 ``RUN_MODE_SPECS`` 恢复（时间三档烘焙 MS 侧单一真相源，反查无歧义）。

三端点公共约定：task_id 格式非法（不满足 sessions.SID_RE）→ 400（marker 路径
拼接安全闸）；未知任务（内存态空 + 无 marker / 状态槽非 machine 归属）→ 404；
三端点均**不走会话闸门**（``_status_common``/``_stop_common``/``_result_common``
的 ``gate=False`` 参数化，机器会话可能已被 TTL 逐出）。

运行模式三档映射（时间烘焙 MS 侧单一真相源 ``RUN_MODE_SPECS``，全默认参数零暴露
—— config 不接受 time/seeds/band/prefix 键，在场 400）：normal = plain
``--time 180``（单 seed 0）；advanced = ``--strategy race --time 1200``（race
默认档 race-budget 180 / race-gate 0.5 由 CLI 缺省）；extreme = ``--extreme
--time 7200``（默认 race 臂，不加 --extreme-strategy；extreme-budget 缺省 600）。

分层合规（与 strategy.py 同款红线，AST 守卫见 tests/test_web_machine.py）：
  - **禁 import ``..cli.*``** —— spawn ``python -m materialsorting.cli.run_config``
    子进程是**进程边界**而非 import 边界，判据逻辑单一真相源留在 cli；
  - 对 ``server.py`` 的依赖走**函数内延迟 import**（server 文件尾 import 本模块
    再调用注册函数，模块级互相 import 成环；strategy.py 防环先例）—— 上传保存
    /parse+commit/会话快照构建/orphan cfg 反查均经 ``server`` 模块属性**调用时
    取值**（tests monkeypatch ``server_mod.UPLOADS_DIR`` 生效点）；
  - 机器会话独立 sid（'m' 前缀满足 sessions.SID_RE），commit 快照只挂本会话；
  - ``strategy`` 骨架与三公共实现经 ``strategy_mod.<fn>(...)`` 模块属性访问
    （spawn/状态推进是 tests monkeypatch 单一生效点），``strategy → sessions``
    单向依赖无环。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as _StarletteUploadFile

from . import strategy as strategy_mod
from .sessions import SID_RE, SessionError
from .sessions import registry as session_registry

__all__ = ['register_machine_routes', 'router']

# 端点路径自带全路径（/api/machine/...，与 routes_views / routes_ws 显式风格一致，
# 不用 APIRouter(prefix=...)）；server.py 文件尾在 strategy 注册之后调用
# register_machine_routes(app) 挂载。
router = APIRouter()

# 运行模式三档映射（US-002 金标）：time = 烘焙进 cfg/spawn 的总预算秒；args =
# spawn cmd 策略段（plain / race 默认档 / 极限默认 race 臂）。race 的
# race-budget 180 / race-gate 0.5 与 extreme 的 extreme-budget 600 均由 CLI
# 缺省参数生效（web 侧零重复定义，判据单一真相源留 cli）。
RUN_MODE_SPECS: dict[str, dict] = {
    'normal': {'time': 180, 'args': []},
    'advanced': {'time': 1200, 'args': ['--strategy', 'race']},
    'extreme': {'time': 7200, 'args': ['--extreme']},
}
# config 拒收键（在场 400）：运行时间/种子/成带/前缀由 MS 侧烘焙或机器契约外，
# 机器客户端不得自定（与 strategy/extreme 前端入口的可调面刻意不同）。
_FORBIDDEN_CONFIG_KEYS = ('time', 'seeds', 'band', 'prefix')
_MAX_CLIENT_REF = 128
# 三端点报错文案的运行名（与 strategy._MODE_LABELS[MACHINE_MODE] 同名）。
_MACHINE_LABEL = '机器排料任务'


# ------------------------------------------------------------- config 校验


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({'error': msg}, status_code=status)


def _validate_config(payload: dict):
    """machine config JSON 校验（fail-fast 400 结构化早退）→ ``(gate_mm, run_mode,
    sizes, per_type, quantities, client_ref)`` 元组；非法返回 JSONResponse。

    形状/数值在此层拦下（坏 config 死在 400 而非 spawn 后的 error 态）；g 码正则
    等深度校验单一真相源留在 ``cli.config.load_config``（子进程入口复验）。
    """
    for key in _FORBIDDEN_CONFIG_KEYS:
        if key in payload:
            return _err(f'config 不接受 {key} 键（运行参数由 MS 侧按运行模式烘焙）')
    raw_gate = payload.get('gate_mm')
    if raw_gate is None:
        return _err('gate_mm 必填（门幅 mm，正整数）')
    if (isinstance(raw_gate, bool) or not isinstance(raw_gate, (int, float))
            or not strategy_mod._is_integral_number(raw_gate) or raw_gate <= 0):
        return _err(f'gate_mm 须为正整数（mm），当前为 {raw_gate!r}')
    gate_mm = int(raw_gate)

    run_mode = payload.get('run_mode')
    if run_mode is None:
        run_mode = 'normal'
    if run_mode not in RUN_MODE_SPECS:
        return _err(f'run_mode 须为 normal/advanced/extreme 之一，当前为 {run_mode!r}')

    sizes = payload.get('sizes')
    if sizes is not None:
        if not isinstance(sizes, list) or not sizes:
            return _err('sizes 须为非空码号整数列表（不需要过滤请删除该键）')
        for i, v in enumerate(sizes):
            if isinstance(v, bool) or not isinstance(v, int):
                return _err(f'sizes[{i}] 须为整数（码号），当前为 {v!r}')

    per_type = payload.get('per_type')
    if per_type is not None:
        if not isinstance(per_type, dict):
            return _err('per_type 须为 {g码:{d?,tol?}} 对象')
        for label, over in per_type.items():
            if not isinstance(over, dict):
                return _err(f'per_type.{label} 须为 {{d?,tol?}} 对象，当前为 {over!r}')
            for k, v in over.items():
                if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                    return _err(f'per_type.{label}.{k} 须为非负数字，当前为 {v!r}')

    quantities = payload.get('quantities')
    if quantities is not None:
        if not isinstance(quantities, dict):
            return _err('quantities 须为 {g码:{码号:数量}} 对象')
        for label, size_map in quantities.items():
            if not isinstance(size_map, dict):
                return _err(f'quantities.{label} 须为 {{码号:数量}} 对象，当前为 {size_map!r}')
            for sk, n in size_map.items():
                if (isinstance(n, bool) or not isinstance(n, (int, float)) or n < 0
                        or (isinstance(n, float) and not n.is_integer())):
                    return _err(f'quantities.{label}.{sk} 须为 ≥0 整数（份数），当前为 {n!r}')

    client_ref = payload.get('client_ref')
    if client_ref is not None:
        if not isinstance(client_ref, str) or not client_ref or len(client_ref) > _MAX_CLIENT_REF:
            return _err(f'client_ref 须为 1~{_MAX_CLIENT_REF} 字符的字符串')

    return gate_mm, run_mode, sizes, per_type, quantities, client_ref


def _machine_ref_inflight(client_ref):
    """同 client_ref 的在飞机器任务（内存态非终态）→ 其状态槽；无 → None。

    终态（done/stopped/error）任务不挡新任务（US-005 完善磁盘态口径）；在飞判据
    与 strategy 单飞闸门同源（``_TERMINAL_STATES``）。
    """
    if not client_ref:
        return None
    for st in strategy_mod._STRATEGY_STATES.values():
        if (st.get('mode') == strategy_mod.MACHINE_MODE
                and st.get('client_ref') == client_ref
                and st.get('state') not in strategy_mod._TERMINAL_STATES):
            return st
    return None


# ------------------------------------------------------------- solve 端点


@router.post('/api/machine/solve')
async def machine_solve(req: Request):
    """机器任务提交：multipart 母版 + config → parse+commit → spawn → 202 task_id。

    复用 server 的上传/commit 管线（延迟 import 防环 + ``server`` 模块属性调用时
    取值），会话只挂本任务独立 sid —— default ``_PIECES_STATE`` 不受扰（对拍验收）。
    """
    from . import server as server_mod

    # ---- multipart 解析（file + config 两字段；坏 multipart → 400）。
    try:
        form = await req.form()
    except Exception:
        return _err('请求须为 multipart/form-data（file + config 两字段）')
    file = form.get('file')
    if not isinstance(file, _StarletteUploadFile):
        return _err('缺少 file 字段（multipart 母版 DXF 二进制）')
    fname = file.filename or ''
    if not fname.lower().endswith('.dxf'):
        return _err('仅支持 .dxf 文件')

    data = await file.read()
    max_bytes = server_mod.UPLOAD_MAX_BYTES
    if len(data) > max_bytes:
        return _err(f'文件大小超过上限 {max_bytes // (1024 * 1024)}MB', status=413)

    raw_config = form.get('config')
    if raw_config is None or (isinstance(raw_config, str) and not raw_config.strip()):
        return _err('缺少 config 字段（JSON 字符串）')
    try:
        payload = json.loads(raw_config)
    except (TypeError, json.JSONDecodeError):
        return _err('config 须为合法 JSON 字符串')
    if not isinstance(payload, dict):
        return _err('config 须为 JSON 对象')

    parsed = _validate_config(payload)
    if isinstance(parsed, JSONResponse):
        return parsed
    gate_mm, run_mode, sizes, per_type, quantities, client_ref = parsed

    # ---- client_ref 幂等（在飞 409 返回既有 task_id；终态不挡新任务）。
    inflight = _machine_ref_inflight(client_ref)
    if inflight is not None:
        return JSONResponse(
            {'error': f'client_ref {client_ref!r} 已有在飞任务（task_id='
                      f'{inflight.get("sid")}），请先轮询/停止该任务',
             'task_id': inflight.get('sid')},
            status_code=409)

    # ---- 铸任务 sid（= task_id，'m'+时间戳+rand）+ 落盘上传。
    sid = 'm' + time.strftime('%Y%m%d%H%M%S') + uuid.uuid4().hex[:8]
    if not SID_RE.match(sid):   # 防御（时间戳+hex 恒合法；将来改格式先在此炸出）
        return _err('task_id 生成失败', status_code=500)
    doc_id = uuid.uuid4().hex
    uploads = server_mod.UPLOADS_DIR
    uploads.mkdir(parents=True, exist_ok=True)
    dest = uploads / f'{doc_id}.dxf'
    dest.write_bytes(data)

    # ---- parse+commit 管线（CPU 密集走共享 executor；坏 DXF → 422 中文）。
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            server_mod._executor, server_mod._commit_to_nesting_sync,
            doc_id, str(dest), fname)
    except Exception as e:
        return JSONResponse({'error': f'母版解析失败：{e}'}, status_code=422)

    # ---- 会话注册（只挂本任务 sid，不碰 default _PIECES_STATE / 不触发 reload）。
    try:
        sess = session_registry.resolve(sid, create=True)
        sess.state = server_mod._build_pieces_state(
            str(server_mod._per_doc_intermediate(doc_id)))
        sess.doc_id = doc_id
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)
    pieces = sess.state.get('pieces') or []
    if not pieces:   # 防御：commit 成功但快照构建异常回落空（build_pieces_state 容错）
        return _err('母版解析失败（会话快照为空，请重试）', status_code=422)

    # ---- cfg 落盘（10 键 schema 子集；time/seeds 由运行模式烘焙 —— 全默认零暴露）。
    spec = RUN_MODE_SPECS[run_mode]
    total_sec = spec['time']
    cfg_payload = {
        'gate_mm': float(gate_mm),
        'time': total_sec,
        'seeds': [0],
        'master_dxf': str(dest.resolve()),
    }
    if sizes:
        cfg_payload['sizes'] = sizes
    if per_type:
        cfg_payload['per_type'] = per_type
    if quantities:
        cfg_payload['quantities'] = quantities

    stamp = time.strftime('%Y%m%d-%H%M%S')
    rand6 = uuid.uuid4().hex[:6]
    cfg_path = uploads / f'machine_cfg_{sid}_{stamp}.json'
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg_payload, f, ensure_ascii=False)

    # ---- spawn（strategy 骨架：模块属性访问 = tests monkeypatch 单一生效点）。
    run_name = f'machine_{sid[:6]}_{rand6}'
    stderr_file = tempfile.NamedTemporaryFile(
        prefix=f'machine_err_{sid[:6]}_', suffix='.log', delete=False)
    stderr_file.close()
    cmd = [sys.executable, '-m', 'materialsorting.cli.run_config',
           str(cfg_path), '--name', run_name, *spec['args'],
           '--time', str(total_sec), '--quiet']
    snapshot = strategy_mod._snapshot_config_runs()
    proc = strategy_mod._spawn_run_process(cmd, stderr_file.name)

    started_at = time.strftime('%Y-%m-%dT%H:%M:%S')
    strategy_mod._write_marker(
        {'pid': proc.pid, 'run_dir': None, 'doc_id': doc_id,
         'mode': strategy_mod.MACHINE_MODE, 'started_at': started_at}, sid)

    st = strategy_mod._states(sid, create=True)
    st.clear()
    st.update({
        'sid': sid,
        'state': 'starting',
        'proc': proc,
        'pid': proc.pid,
        'mode': strategy_mod.MACHINE_MODE,
        # machine 专属：run_mode 三档（status 载荷 US-003 透传）+ 幂等键。
        'run_mode': run_mode,
        'client_ref': client_ref,
        'strategy': None,
        'minutes': None,
        'total_budget_sec': total_sec,
        'started_at': started_at,
        'started_ts': time.time(),
        'run_dir': None,
        'snapshot': snapshot,
        'stderr_path': stderr_file.name,
        'doc_id': doc_id,
        # start 时快照（result 组装 manifest 用同口径，不依赖客户端二次回传）。
        'pieces_snapshot': [dict(p) for p in pieces],
        'sizes': sizes or None,
        'per_type': per_type or None,
        'quantities': quantities or None,
        'gate_mm': float(gate_mm),
        'seed': 0,
        'cfg_path': str(cfg_path),
        'run_name': run_name,
        'stopped': False,
        'exit_code': None,
        'error': None,
    })
    return JSONResponse({'task_id': sid, 'run_name': run_name,
                         'started_at': started_at}, status_code=202)


# --------------------------------------------------- US-003 status/stop/result


def _machine_task_ctx(task_id: str):
    """task_id 三端点公共校验闸 → ``(st, marker, None)`` 或 ``(None, None, err)``。

    - 格式非法（不满足 sessions.SID_RE，含路径分隔符等）→ 400 —— marker 路径按
      sid 拼接，格式闸即路径安全闸；
    - 未知任务（内存态空 + 无 marker）或槽/marker 归属非 machine（浏览器会话的
      strategy/extreme run —— 其 sid 若被机器客户端拿到也不冒认）→ 404；
    - ``st`` 空但 marker 在 → orphan（MS 重启后遗留），三端点各自处理。
    """
    if not SID_RE.match(task_id or ''):
        return None, None, _err(f'task_id 非法：{task_id!r}')
    st = strategy_mod._states(task_id)
    # default 槽是浏览器工作台共享槽（_states 恒返回非 None），mode 检查天然拦下。
    marker = None if st else strategy_mod._read_marker(task_id)
    if st is not None and st.get('mode') != strategy_mod.MACHINE_MODE:
        return None, None, _err(f'未知任务（task_id={task_id}）', status=404)
    if st is None and (marker is None
                       or marker.get('mode') != strategy_mod.MACHINE_MODE):
        return None, None, _err(f'未知任务（task_id={task_id}）', status=404)
    return st, marker, None


def _orphan_mode_budget(task_id: str) -> tuple:
    """orphan 态 run_mode/total_budget_sec 恢复 → ``(run_mode, total_budget_sec)``。

    来源 = ``uploads/machine_cfg_<sid>_*.json`` 的 ``time`` 键反查
    ``RUN_MODE_SPECS``（时间三档 180/1200/7200 由 MS 侧烘焙且恰三值互异 ——
    反查无歧义；时间即单一真相源，marker 恒 5 键不带这两字段）。缺 cfg / 坏
    JSON → ``(None, None)``（状态可读优先，字段降级不阻塞）。
    """
    from . import server as server_mod

    try:
        cfg_files = sorted(server_mod.UPLOADS_DIR.glob(
            f'machine_cfg_{task_id}_*.json'))
    except OSError:
        return None, None
    by_time = {spec['time']: mode for mode, spec in RUN_MODE_SPECS.items()}
    for cp in cfg_files:
        cfg = strategy_mod._read_json(cp)
        if isinstance(cfg, dict) and cfg.get('time') is not None:
            return by_time.get(cfg['time']), cfg['time']
    return None, None


def _incumbent_from_best_frames(run_dir):
    """best_frame 边车 → incumbent 摘要（density 最大帧四键，无 placed_items）。

    machine status 的 incumbent 回落源：运行中（result.json 未产出）与 plain
    （normal 档）run（portfolio.incumbent 恒 null，US-002 实测）—— best_frame
    逐 seed 全量在盘（仅改进帧重写），取 density 最大即全局 best-so-far。
    """
    if not run_dir:
        return None
    frames = []
    for fp in Path(run_dir).glob('best_frame_s*.json'):
        rec = strategy_mod._read_json(fp)
        if isinstance(rec, dict) and rec.get('density') is not None:
            frames.append(rec)
    if not frames:
        return None
    best = max(frames, key=lambda r: float(r['density']))
    return {k: best.get(k) for k in ('density', 'width_mm', 'seed',
                                     'frame_index')}


async def _machine_status(task_id: str, request: Request):
    """status 业务内核（handler 只做 HTTP 壳；测试可直调）。

    复用 ``_status_common(sid=task_id, gate=False)``（状态推进写回内存态 + run_dir
    发现 + 终态清 marker 同 strategy 口径），再收口成 machine 契约载荷：
    - incumbent：portfolio.incumbent 优先 → best_frame 边车回落（运行中/plain）；
    - current/per_seed/elapsed/error/exit_code 透传（current 收窄三键）；
    - orphan 收口：pid 死 + 超 RUN_DIR_GRACE_SEC 宽限 → error（重启后无 stderr
      可带，marker 恰 5 键；30s 宽限防「刚重启竞态误报 error」）。
    """
    st, marker, err = _machine_task_ctx(task_id)
    if err is not None:
        return err
    # 轮询即活性（best-effort）：会话仍在注册表 → 刷 last_active（touch 对不在
    # 的 sid no-op）—— 无人轮询超 TTL+宽限 → 会话逐出，但下方状态读取不走会话
    # 闸门，仍 200（内存态路径）。
    session_registry.touch(task_id)

    base = await strategy_mod._status_common(
        request, sid=task_id, gate=False)
    if isinstance(base, JSONResponse):    # 防御（gate=False 不产生；保险透传）
        return base

    state = base.get('state')
    error = base.get('error')
    if state == 'orphan':
        elapsed = base.get('elapsed_sec')
        if (not base.get('alive')) and (
                elapsed is None or elapsed > strategy_mod.RUN_DIR_GRACE_SEC):
            state = 'error'
            error = (f'任务进程已退出且超过 {strategy_mod.RUN_DIR_GRACE_SEC:g}s'
                     f' 宽限（MS 重启后遗留 marker，pid={base.get("pid")}）')

    run_mode = (st or {}).get('run_mode')
    total_budget = (st or {}).get('total_budget_sec')
    if state == 'orphan' and run_mode is None:
        run_mode, total_budget = _orphan_mode_budget(task_id)

    incumbent = base.get('incumbent')
    if incumbent is None:
        incumbent = _incumbent_from_best_frames(base.get('run_dir'))
    else:
        incumbent = {k: incumbent.get(k) for k in
                     ('density', 'width_mm', 'seed', 'frame_index')}
    current = base.get('current')
    payload = {
        'state': state,
        'mode': strategy_mod.MACHINE_MODE,
        'run_mode': run_mode,
        'total_budget_sec': total_budget,
        'elapsed_sec': base.get('elapsed_sec'),
        'incumbent': incumbent,
        'current': ({'seed': current.get('seed'),
                     'density': current.get('density'),
                     'ext': current.get('ext')} if current else None),
        'per_seed': base.get('per_seed') or [],
        'error': error,
        'exit_code': base.get('exit_code'),
    }
    if state == 'orphan':   # 遗留 run 诊断面：客户端据此决定 stop/清理。
        payload['alive'] = base.get('alive')
        payload['pid'] = base.get('pid')
    return payload


@router.get('/api/machine/solve/{task_id}/status')
async def machine_solve_status(task_id: str, request: Request):
    """机器任务状态轮询（2s 级；无 placed_items 控载荷，绝不读运行中 curve）。"""
    return await _machine_status(task_id, request)


@router.post('/api/machine/solve/{task_id}/stop')
async def machine_solve_stop(task_id: str, request: Request):
    """机器任务停止：树杀（含 solve 孙进程）+ 置 stopped + 清 marker。

    复用 ``_stop_common(sid=task_id, gate=False, label='机器排料任务')``：
    in-flight（starting/running）→ 树杀 + run_dir 保留；orphan marker → pid
    存活则树杀 + 清 marker；已终态 → 400（无在飞任务）。未知/非法 task_id 由
    ``_machine_task_ctx`` 前置拦下（400/404）。
    """
    _, _, err = _machine_task_ctx(task_id)
    if err is not None:
        return err
    session_registry.touch(task_id)   # 同 status：轮询动作刷活性（no-op 容错）
    return await strategy_mod._stop_common(
        request, _MACHINE_LABEL, sid=task_id, gate=False)


@router.get('/api/machine/solve/{task_id}/result')
async def machine_solve_result(task_id: str, request: Request):
    """机器任务终态取完整布局：``{manifest, best, summary}``；running → 409。

    复用 ``_result_common(sid=task_id, gate=False, drift=False)``：best =
    portfolio.incumbent 优先（race/se 档完整 placed_items）→ stopped/plain 档
    回落各 best_frame 边车 density 最大；manifest = build_pid_meta（start 快照
    口径，pieces 键集与 /ws/solve manifest 同形）；drift warning 无共享画布概念
    跳过。载荷收窄恰三键（state/mode/run_dir 属 strategy 家族内部面）。
    """
    _, _, err = _machine_task_ctx(task_id)
    if err is not None:
        return err
    session_registry.touch(task_id)   # 同 status：轮询动作刷活性（no-op 容错）
    resp = await strategy_mod._result_common(
        request, _MACHINE_LABEL, sid=task_id, gate=False, drift=False)
    if isinstance(resp, JSONResponse):
        return resp
    return {'manifest': resp['manifest'], 'best': resp['best'],
            'summary': resp['summary']}


def register_machine_routes(app) -> None:
    """把 machine 路由挂到 FastAPI app（server.py 文件尾调用一次，位于 strategy 之后）。

    US-002 solve + US-003 status/stop/result 四端点已挂到本模块 ``router``；后续
    故事（export/DELETE）逐故事挂同一 router，注册点零改动。
    """
    app.include_router(router)

