"""WS 求解编排路由（自 server.py 机械拆出，行为不变）。

``/ws/solve`` 端点 + 求解子进程终止封装；共享的 ``_executor`` / pieces state
快照来自 ``web.runtime``（同一单例）。协议详见 server.py 模块 docstring。

US-011（腰头成带）：StartPayload 新增可缺省 ``band`` 键（``{enabled, label}``，
缺省/null/{}/非 dict = 关闭，旧行为逐字段不变），``_parse_band`` 服务端校验
（label ``^g\\d+$`` / 存在于母版 / 该 g 码 quantities>0）非法即结构化 error 早退；
band 开启时 WS 依序收到 ``stage`` → ``manifest`` → ``frames/final``（组合片 WB_
pid 在 solve_worker 帧前展开，永不泄漏）。不适合成带的 g 码（裤耳类细长小片）
由 ``waist_band.FILL_FLOOR_PCT`` 灾难守卫在带构造期拦截（fail-fast error）。

US-003（起始端成套前后幅）：StartPayload 新增可缺省 ``prefix`` 键
（``{enabled, front, back}`` —— **无 size 键**，资格码由后端 seeded 随机选取，
决策②），``_parse_prefix`` 单一校验点（``_parse_band`` 同模式）：front/back
``^g\\d+$`` / 存在于母版 / front≠back / **须存在 ≥1 资格码**（两码 demand==2，
``eligible_sizes`` 同口径）—— 无资格码（含 quantities=null 全 demand=1）=
结构化 error 早退 + 显式 close，文案指路数量矩阵。prefix 开启时 WS 依序
``stage('prefix', {size,...})`` → ``manifest`` → ``frames/final``（PS_ 在
solve_worker 帧前展开，永不泄漏；final 消息附 ``prefix`` 统计段）。双开时
stage 两条（band→prefix→manifest）互不干扰，带位只记录不置换（FR-8）。

多会话 US-003（读路由与 WS 接入会话）：``/ws/solve`` 读 ``?sid=`` query（浏览器
WS 不能自定义 Header；缺省/空串 → default 会话）。连接建立即 ``ws_acquire``
钉住会话（``ws_open += 1``，扫描线程对求解中会话不逐出），finally ``ws_release``
减回；accept 阶段的 state 快照来自**会话**而非进程级 ``_PIECES_STATE``（default
会话两者同一 dict，无 sid 行为不变）。``on_manifest`` / ``on_report`` 回调顺手
``touch`` 刷活性（求解期间客户端不发消息也不误杀；单 float 写 GIL-safe）。
会话过期/超限/非法 → ``{'type':'error','code':...,'message'}`` 错误帧（``code``
键 additive，旧前端忽略）+ 显式 close，不发 manifest。
"""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
from .runtime import _executor
from .sessions import SessionError, registry as session_registry
from .solver import solve_with_callback_proc

router = APIRouter()
_SENTINEL = object()

# US-011 band / US-003 prefix 服务端校验共用常量。
_BAND_LABEL_RE = re.compile(r'^g\d+$')


def _band_demand(p, quantities) -> int:
    """该 piece 在 quantities 口径下的 demand（与 ``build_pid_meta`` 同口径镜像）。

    missing→1、显 0→0；sizeKey = str(size)（null→'null'，与前端 qtyStore 一致）。
    """
    label = p.get('label')
    if quantities and isinstance(quantities, dict) and label is not None and label in quantities:
        size_map = quantities[label]
        size_map = size_map if isinstance(size_map, dict) else {}
        return int(size_map.get('null' if p.get('size') is None else str(p.get('size')), 0))
    return 1


def _parse_band(raw, pieces, quantities):
    """StartPayload ``band`` 键 → worker 成带配置 dict | None（单一校验点）。

    规则（FR-1 / AC#3）：非 dict / 无 ``enabled`` / enabled falsy → None（关闭，
    旧行为）；enabled 时 label 须匹配 ``^g\\d+$`` 且存在于当前母版且该 g 码
    quantities>0。非法抛 ``ValueError``（调用方转 ``{type:error}`` 早退，不发
    manifest）。

    返回 ``{'label': str}``。
    """
    if not isinstance(raw, dict) or not raw.get('enabled'):
        return None
    label = raw.get('label')
    if not isinstance(label, str) or not _BAND_LABEL_RE.match(label):
        raise ValueError(f'band.label 须为 g 码（如 g05），收到 {label!r}')
    if not any(p.get('label') == label for p in pieces):
        raise ValueError(f'band.label {label!r} 不存在于当前母版')
    members = [p for p in pieces
               if p.get('label') == label and _band_demand(p, quantities) > 0]
    if not members:
        raise ValueError(f'band g 码 {label} 数量全为 0（QtyMatrix 须至少一个码数量 > 0）')
    return {'label': label}


def _parse_prefix(raw, pieces, quantities, sizes=None):
    """StartPayload ``prefix`` 键 → worker 前缀配置 dict | None（单一校验点）。

    规则（FR-1 / AC#3）：非 dict / 无 ``enabled`` / enabled falsy → None（关闭，
    旧行为）；enabled 时 front/back 须匹配 ``^g\\d+$`` 且存在于当前母版且
    front≠back；**须存在 ≥1 个资格码**（``eligible_sizes`` 同口径：该码 front
    demand==2 且 back demand==2，sizes = 用户所排尺码过滤 —— 资格码必须真实进
    主解实例）—— 无资格码（含 quantities=null 全 demand=1 场景）= 结构化
    error（文案指路数量矩阵，FR-9）。非法抛 ``ValueError``（调用方转
    ``{type:error}`` 早退 + 显式 close，不发 manifest）。

    返回 worker 形态 ``{'front': str, 'back': str}``（**无 size 键** —— 资格码
    在 solve_worker 进程内 seeded 随机选取，决策②；多余键如 size 静默忽略，
    与 ``_parse_band`` 对 ack/fillers 的处理一致）。
    """
    if not isinstance(raw, dict) or not raw.get('enabled'):
        return None
    front = raw.get('front')
    back = raw.get('back')
    for name, v in (('front', front), ('back', back)):
        if not isinstance(v, str) or not _BAND_LABEL_RE.match(v):
            raise ValueError(f'prefix.{name} 须为 g 码（如 g02），收到 {v!r}')
        if not any(p.get('label') == v for p in pieces):
            raise ValueError(f'prefix.{name} {v!r} 不存在于当前母版')
    if front == back:
        raise ValueError(f'prefix.front 与 prefix.back 须为不同 g 码（前/后幅各一），'
                         f'收到同为 {front!r}')
    from ..nesting_engine.prefix import eligible_sizes
    if not eligible_sizes(quantities, front, back, sizes=sizes or None):
        raise ValueError('当前数量无 2+2 资格码（front/back 各码 demand 须恰为 2）—— '
                         '请在数量矩阵把所选码前后幅配成 2+2')
    return {'front': front, 'back': back}


# US-026：process.terminate()+join(timeout=5) 封装 —— read_loop（stop/断开）、write_loop
# （send 失败）、ws_solve finally 三处调用，确保任何路径下都不留孤儿进程。幂等安全：
# process 已死时 terminate/join 是 no-op。state_box 缺 process 键（启动竞态）也无害。
def _terminate_solve_process(state_box: dict) -> None:
    """终止 solve 子进程（幂等）：alive → terminate → join(timeout=5) → kill 兜底。"""
    proc = state_box.get('process')
    if proc is None:
        return
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=5.0)
        # terminate 后仍存活（极端情况：Rust 原生代码 ignore SIGTERM）→ kill 兜底。
        if proc.is_alive():
            try:
                proc.kill()
            except Exception:
                pass
            proc.join(timeout=1.0)


@router.websocket('/ws/solve')
async def ws_solve(ws: WebSocket):
    """排料求解 WebSocket 端点（US-026 进程化 + stop/断开清理）。

    生命周期（双向并发：write loop 内联 + read loop 后台 task）：
      0. accept → ``?sid=`` query 会话解析（多会话 US-003）：``ws_acquire`` 钉住会话
         （``ws_open += 1``，finally 减回）；失败 → 结构化 error 帧（``code`` 键
         additive）+ 显式 close，不发 manifest；
      1. 读首条消息（必须 ``{action:'start'}``）→ accept 阶段拿**会话** pieces 快照；
      2. ``solve_with_callback_proc`` 在 executor 线程阻塞跑（spawn 子进程），通过
         ``on_manifest`` / ``on_report`` 回调把消息经 ``call_soon_threadsafe`` 投入
         asyncio queue；``on_process`` 把 Process 句柄交给本协程供 stop/断开时 terminate；
      3. write loop（内联主流程）drain queue → ``ws.send_json``（manifest/frame/final/error）；
      4. read loop（后台 task）持续 ``await ws.receive_json()``：收到 ``{action:'stop'}`` →
         ``process.terminate()+join(timeout=5)`` → 直发 ``{type:stopped}`` → 投 SENTINEL；
      5. 客户端断开（WebSocketDisconnect / 连接异常）→ terminate+join 防孤儿进程（修旧 bug）。

    write loop 消费 SENTINEL（run_solve 或 read_loop 投）后 break → finally 显式 ``ws.close()``
    + cancel read_task + terminate process 兜底。空 state（intermediate 缺失）行为不变：
    发 error「排料数据为空」并关闭。
    """
    await ws.accept()

    # US-003（多会话）：?sid= query（浏览器 WS 不能自定义 Header；缺省/空串 → default
    # 会话）。连接建立即钉住（ws_open += 1）：扫描线程对求解中会话不逐出；整连接
    # finally 减回（断开后 ws_open 归零）。过期/超限/非法 → error 帧 + 显式 close。
    sid = (ws.query_params.get('sid') or '').strip() or None
    try:
        session_state = session_registry.ws_acquire(sid).state
    except SessionError as e:
        err_frame = {'type': 'error', 'message': e.error}
        if e.code:               # 401 session_expired / 429 session_limit（additive）
            err_frame['code'] = e.code
        await ws.send_json(err_frame)
        try:
            await ws.close()
        except Exception:
            pass
        return

    try:
        msg = await ws.receive_json()
        if msg.get('action') != 'start':
            await ws.send_json({'type': 'error', 'message': '首条消息须为 {action:start}'})
            return

        # US-020：accept 阶段拿一次 state 快照，整连接内 pieces/gate_mm 不变（避免求解
        # 中途 reload 切数据）。state 空时（首次启动未 commit / intermediate 缺失）→ 报错。
        # US-003（多会话）：快照来自会话（带 sid = commit 注册的 per-doc 快照；缺省 =
        # default 会话，其 state 即 runtime._PIECES_STATE 同一 dict，行为不变）。会话
        # state 也从不原位 mutate（commit 整体 rebind st.state），快照语义保持。
        state = session_state
        pieces = state.get('pieces') or []
        gate_mm = state.get('gate_mm') or 0.0
        if not pieces or gate_mm <= 0:
            await ws.send_json({'type': 'error',
                                'message': '排料数据为空（请先上传解析母版并 commit）'})
            return

        sizes = msg.get('sizes') or []
        time_budget = int(msg.get('time', 120))
        # 幅宽：前端 gate_mm（cm×10→mm）优先覆盖 intermediate 的默认门幅；未传/非正/非法 → 沿用 state。
        req_gate = msg.get('gate_mm')
        if req_gate:
            try:
                g = float(req_gate)
                if g > 0:
                    gate_mm = g
            except (TypeError, ValueError):
                pass
        seed = int(msg.get('seed', 0))
        params = msg.get('params') or None
        per_type = msg.get('per_type') or None
        # US-022：quantities = {label: {sizeKey: N}}（per-size demand；0=该 piece 该码不排）。
        # 缺省/None → 全片 demand=1（向后兼容旧前端 / 旧 intermediate 无 label）。
        quantities = msg.get('quantities')
        if not isinstance(quantities, dict):
            quantities = None

        # US-011：band 键解析 + 服务端校验（quantities 解析区后；非法 = 结构化 error 早退，
        # 不发 manifest）。缺省/null/{}/非 dict = 关闭，solve_params 与旧版逐字段一致。
        # 显式 ws.close()：TestClient 下 endpoint 返回不自动关 WS 到 client receive 抛
        # disconnect 的程度（Starlette 实现差异，同 finally 收尾约定）。
        try:
            band_cfg = _parse_band(msg.get('band'), pieces, quantities)
        except ValueError as e:
            await ws.send_json({'type': 'error', 'message': str(e)})
            try:
                await ws.close()
            except Exception:
                pass
            return

        # US-003：prefix 键解析 + 服务端校验（band 之后，同早退契约）。缺省/null/{}/
        # 非 dict/enabled falsy = 关闭；无资格码（含 quantities=null 全 demand=1）=
        # 结构化 error（文案指路数量矩阵）。
        try:
            prefix_cfg = _parse_prefix(msg.get('prefix'), pieces, quantities, sizes)
        except ValueError as e:
            await ws.send_json({'type': 'error', 'message': str(e)})
            try:
                await ws.close()
            except Exception:
                pass
            return

        # US-026：pieces_snapshot = 纯 dict 列表（deep copy 防连接内 mutate），连同 solve_params
        # 传给 solve_with_callback_proc → solve_worker 子进程内 build_instance（spyrrow 对象
        # 不可 pickle，主进程不构造 instance）。
        pieces_snapshot = [dict(p) for p in pieces]
        solve_params = {
            'time_budget': time_budget,
            'seed': seed,
            'sizes': sizes,
            'params': params,
            'per_type': per_type,
            'quantities': quantities,
        }

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        # 跨线程共享状态盒：process 句柄（on_process 填）、stopped 标志（read_loop 填）、
        # 帧计数与 n_eroded（on_report/on_manifest 填，run_solve 读 → final 消息用）。
        # 所有字段仅在 executor 单线程内 mutate（on_manifest/on_report/run_solve 同线程），
        # stopped 标志由事件循环线程写 —— 两者用 bool 简单写读，GIL 下无撕裂风险。
        state_box: dict = {'process': None, 'stopped': False, 'n_frames': 0, 'n_eroded': 0}

        def on_manifest(m):
            """子进程 manifest → 组装前端契约消息 → 投 asyncio queue。"""
            session_registry.touch(sid)   # US-003：求解回调刷活性（客户端求解中不发消息）
            state_box['n_eroded'] = m.get('n_eroded', 0)
            total_area = m.get('total_area', 0.0)
            manifest_msg = {
                'type': 'manifest',
                'gate_mm': gate_mm,
                # 实际排料幅宽（求解约束带口径）：density 分母 + 前端红色虚线（实际范围
                # 边界）唯一数据源；gate_mm 仍为显示口径（viewBox / 导出外框）。
                'gate_nest_mm': min(float(gate_mm), PLOT_SAFE_MAX_Y_MM),
                'total_area_mm2': total_area,
                'n_eroded': m.get('n_eroded', 0),
                'pieces': [
                    # US-002：manifest 全 label 键（无 ptype）；颜色 = size_color(尺码)，
                    # 2026-08-20 起同码同色跨片型一致（此前按 g 码）。
                    {'id': pid, 'size': meta['size'],
                     'color': meta['color'],
                     'area_mm2': meta['area_mm2'], 'polygon': meta['polygon'],
                     # g 码裁片标识（intermediate label 经 build_instance 透传；旧
                     # intermediate 无 → None，前端 NestSVG tooltip 按缺席降级不显示）。
                     'label': meta.get('label'),
                     # demand：该 pid 的副本数（build_instance 透传；缺省 1 = 单副本/旧兼容）。
                     # 前端 NestSVG 按 demand 建 N 个 polygon 副本，避免 demand>1 时同 id 多 placement 互相覆盖。
                     'demand': meta.get('demand', 1),
                     # US-024：5 层透传字段（None-safe；缺字段时各层视为空/None，前端 layer-aware 渲染）。
                     'net_polygon': meta.get('net_polygon', []),
                     'internal_lines': meta.get('internal_lines', []),
                     'notches': meta.get('notches', []),
                     'grain_line': meta.get('grain_line'),
                     }
                    for pid, meta in m['pid_meta'].items()
                ],
            }
            loop.call_soon_threadsafe(queue.put_nowait, manifest_msg)

        def on_report(r):
            """子进程 frame（density 双口径已由 solve_with_callback_proc 换算）→ 加 index 投队列。"""
            session_registry.touch(sid)   # US-003：求解回调刷活性（GIL-safe float 写）
            r['index'] = state_box['n_frames']
            state_box['n_frames'] += 1
            loop.call_soon_threadsafe(queue.put_nowait, r)

        def on_stage(m):
            """子进程 stage → 前端契约消息（各自 manifest 前唯一一次）。

            band（US-011 FR-2）：``{'type':'stage','stage':'band', fill_pct, bbox,
            fallback:false, elapsed}``；prefix（US-003 FR-2）：``{'type':'stage',
            'stage':'prefix', size, fill_pct, bbox, holes, elapsed}``（size 回显选中
            资格码）。键白名单并集透传 —— 旧前端 default:break 静默忽略，前向兼容。
            """
            out = {'type': 'stage', 'stage': m.get('stage', 'band')}
            for k in ('fill_pct', 'bbox', 'fallback', 'elapsed', 'size', 'holes'):
                if k in m:
                    out[k] = m[k]
            loop.call_soon_threadsafe(queue.put_nowait, out)

        def on_process(proc):
            """子进程 start 后立即回调，把 Process 句柄交给事件循环供 stop/断开 terminate。"""
            state_box['process'] = proc

        def run_solve():
            """executor 线程：阻塞跑 solve_with_callback_proc → 投 final/error/SENTINEL。"""
            _, final_data, elapsed, err = solve_with_callback_proc(
                pieces_snapshot, gate_mm, solve_params,
                on_manifest=on_manifest, on_report=on_report, on_process=on_process,
                on_stage=on_stage, band=band_cfg, prefix=prefix_cfg,
            )
            # stopped 标志由 read_loop 在 stop/断开时置 True → 不再投 final/error（避免
            # 与 stopped 消息冲突；客户端只收 stopped 或 final/error，不会同时收）。
            if not state_box['stopped']:
                if err is not None:
                    loop.call_soon_threadsafe(queue.put_nowait,
                        {'type': 'error', 'message': f'求解失败: {err}'})
                elif final_data is not None:
                    final_msg = {
                        'type': 'final',
                        'density': final_data['density'],
                        'density_sparrow': final_data['density_sparrow'],
                        'width_mm': final_data['width_mm'],
                        'elapsed': round(elapsed, 2),
                        'n_frames': state_box['n_frames'],
                        'n_eroded': state_box['n_eroded'],
                    }
                    # US-003：prefix 统计段（size/pin/带位记录；prefix 关闭时键缺席 =
                    # 旧消息逐字段不变）。
                    if 'prefix' in final_data:
                        final_msg['prefix'] = final_data['prefix']
                    loop.call_soon_threadsafe(queue.put_nowait, final_msg)
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        loop.run_in_executor(_executor, run_solve)

        # ---- 双向并发：write loop 内联 await（主流程）；read loop 后台 task 收 stop/断开 ----
        # write loop 消费 SENTINEL 后自然 break → ws_solve 返回 → FastAPI 关闭 WS。read loop
        # 被 cancel（仍在 receive_json 阻塞）或已自行 return（stop/断开）。任一路径 finally
        # 都 terminate+join process，防孤儿。
        async def read_loop():
            """后台持续读客户端消息：{action:'stop'} → terminate + 直发 stopped + 投 SENTINEL；断开 → terminate。"""
            try:
                while True:
                    cmsg = await ws.receive_json()
                    if isinstance(cmsg, dict) and cmsg.get('action') == 'stop':
                        state_box['stopped'] = True
                        _terminate_solve_process(state_box)
                        # stopped 消息由 read_loop 直发（不经 queue），确保是客户端收到的最后
                        # 一条业务消息。先发 stopped 再投 SENTINEL：write loop 在 stopped 标志
                        # 已置 True 时丢弃残余 frame（continue），收到 SENTINEL 后 break → WS 关闭。
                        # 若先投 SENTINEL，write loop 会在 send_json(stopped) 的 await 期间 break
                        # → finally cancel read_task → stopped 可能未发完。
                        try:
                            await ws.send_json({'type': 'stopped', 'reason': 'user_requested'})
                        except Exception:
                            pass   # send 失败（客户端已断开）—— 忽略，finally 兜底清理
                        queue.put_nowait(_SENTINEL)
                        return
            except WebSocketDisconnect:
                # 客户端主动断开 → 清理子进程（修旧 bug：旧版 except:pass 留孤儿进程跑满预算）。
                state_box['stopped'] = True
                _terminate_solve_process(state_box)
            except (asyncio.CancelledError, SystemExit, GeneratorExit):
                raise   # 不吞取消/退出类异常，让上层 finally 处理
            except Exception:
                # 其它连接异常（网络中断等）→ 同样清理。
                state_box['stopped'] = True
                _terminate_solve_process(state_box)

        read_task = asyncio.create_task(read_loop())
        try:
            # write loop 内联（主流程）：drain asyncio queue → ws.send_json；SENTINEL / stopped 收尾。
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                if state_box['stopped']:
                    # stop 已触发：read_loop 已直发 stopped → 丢弃残余 frame，等 SENTINEL。
                    continue
                try:
                    await ws.send_json(item)
                except Exception:
                    # send 失败（客户端已断开）→ 标记 stopped + terminate，让 run_solve 跳过 final。
                    state_box['stopped'] = True
                    _terminate_solve_process(state_box)
                    break
        finally:
            # 兜底清理：无论正常收尾还是异常，确保 process 被终止 + read_task 被 cancel + WS 关闭。
            _terminate_solve_process(state_box)
            if not read_task.done():
                read_task.cancel()
                # 不 await read_task：TestClient（anyio portal）下 ws.receive_json() 阻塞在线程
                # 安全部列上，task.cancel() 的 CancelledError 无法投递到阻塞中的 coroutine ——
                # await read_task / wait_for(read_task) 会永久挂起。uvicorn 生产环境下 cancel
                # 正常生效（receive_json 是真 async，可被中断）。
            # 显式关闭 WS：ws_solve 返回后 FastAPI 自动关 WS，但 TestClient 需要显式 close
            # 才能让 client 端 receive_json 抛 WebSocketDisconnect（Starlette 实现差异）。
            try:
                await ws.close()
            except Exception:
                pass
    finally:
        # US-003（多会话）：解除钉住 —— ws_open 减回（下限 0；会话已被逐出 → no-op）。
        # 任何退出路径（正常 final / error 早退 / stop / 断开）都走到这里。
        session_registry.ws_release(sid)
