"""WS 求解编排路由（自 server.py 机械拆出，行为不变）。

``/ws/solve`` 端点 + 求解子进程终止封装；共享的 ``_executor`` / pieces state
快照来自 ``web.runtime``（同一单例）。协议详见 server.py 模块 docstring。

US-011（腰头成带）：StartPayload 新增可缺省 ``band`` 键（``{enabled, label, ack?}``，
缺省/null/{}/非 dict = 关闭，旧行为逐字段不变），``_parse_band`` 服务端校验（label
``^g\\d+$`` / 存在于母版 / 该 g 码 quantities>0 / 硬警告形态需显式 ack）非法即结构化
error 早退；band 开启时 WS 依序收到 ``stage`` → ``manifest`` → ``frames/final``
（组合片 WB_ pid 在 solve_worker 帧前展开，永不泄漏）。
"""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
from .runtime import _executor, _get_pieces_state
from .solver import solve_with_callback_proc

router = APIRouter()
_SENTINEL = object()

# US-011 band 服务端校验常量（落地方案 §2.8 误选护栏；参数值可在 US-013 试用后调）。
_BAND_LABEL_RE = re.compile(r'^g\d+$')
# 硬警告形态阈值：成员最小边 <60mm（裤耳类小片）或长宽比 >6（细长条）的 label 需
# payload 显式 ``ack:true`` 才执行成带。
_BAND_ACK_MIN_EDGE_MM = 60.0
_BAND_ACK_MAX_ASPECT = 6.0


class BandAckRequired(ValueError):
    """硬警告形态（最小边 <60 / 长宽比 >6）需显式 ``ack:true``（US-013 预演路由
    据此回结构化 ``hard_warning`` 标记，前端弹窗渲染二次确认勾选框；WS 路径仍按
    ``str(e)`` 报错，行为不变）。"""


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


def _band_piece_wh(p):
    """裁片多边形 bbox → (w, h)（原始存档朝向；硬警告形态判定输入）。"""
    xs = [float(pt[0]) for pt in p['polygon']]
    ys = [float(pt[1]) for pt in p['polygon']]
    return max(xs) - min(xs), max(ys) - min(ys)


def _parse_band(raw, pieces, quantities):
    """StartPayload ``band`` 键 → worker 成带配置 dict | None（US-011 单一校验点）。

    规则（FR-1 / AC#3）：非 dict / 无 ``enabled`` / enabled falsy → None（关闭，
    旧行为）；enabled 时 label 须匹配 ``^g\\d+$`` 且存在于当前母版且该 g 码
    quantities>0；成员最小边 <60mm 或长宽比 >6 的 label 需显式 ``ack:true``。
    非法抛 ``ValueError``（调用方转 ``{type:error}`` 早退，不发 manifest）。

    返回 ``{'label': str, 'time_budget': int|None}``（ack 校验通过后不透传）；
    ``time_budget`` 为可选内部旋钮（缺省 15s = ``DEFAULT_BAND_TIME_BUDGET_S``，
    测试/US-013 预演缩短预算用，非 FR-1 前端契约键）。
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
    wh = [_band_piece_wh(p) for p in members]
    min_edge = min(min(w, h) for w, h in wh)
    aspect = max((max(w, h) / min(w, h)) if min(w, h) > 0 else float('inf') for w, h in wh)
    if (min_edge < _BAND_ACK_MIN_EDGE_MM or aspect > _BAND_ACK_MAX_ASPECT) \
            and raw.get('ack') is not True:
        raise BandAckRequired(
            f'band g 码 {label} 最小边 {min_edge:.0f}mm（<60）或长宽比 {aspect:.1f}（>6），'
            '属硬警告形态，需显式确认（band.ack=true）才执行成带')
    tb = raw.get('time_budget')
    try:
        tb = max(1, int(tb)) if tb is not None else None
    except (TypeError, ValueError):
        tb = None
    return {'label': label, 'time_budget': tb}


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
      1. accept → 读首条消息（必须 ``{action:'start'}``）→ accept 阶段拿 pieces 快照；
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
    msg = await ws.receive_json()
    if msg.get('action') != 'start':
        await ws.send_json({'type': 'error', 'message': '首条消息须为 {action:start}'})
        return

    # US-020：accept 阶段拿一次 state 快照，整连接内 pieces/gate_mm 不变（避免求解
    # 中途 reload 切数据）。state 空时（首次启动未 commit / intermediate 缺失）→ 报错。
    state = _get_pieces_state()
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
        r['index'] = state_box['n_frames']
        state_box['n_frames'] += 1
        loop.call_soon_threadsafe(queue.put_nowait, r)

    def on_stage(m):
        """子进程 stage（band 带内聚排完成统计）→ 前端契约消息（manifest 前唯一一次）。

        FR-2：``{'type':'stage','stage':'band', fill_pct, bbox, fallback:false, elapsed}``
        —— 旧前端 default:break 静默忽略，前向兼容。
        """
        loop.call_soon_threadsafe(queue.put_nowait, {
            'type': 'stage',
            'stage': m.get('stage', 'band'),
            'fill_pct': m.get('fill_pct'),
            'bbox': m.get('bbox'),
            'fallback': bool(m.get('fallback', False)),
            'elapsed': m.get('elapsed'),
        })

    def on_process(proc):
        """子进程 start 后立即回调，把 Process 句柄交给事件循环供 stop/断开 terminate。"""
        state_box['process'] = proc

    def run_solve():
        """executor 线程：阻塞跑 solve_with_callback_proc → 投 final/error/SENTINEL。"""
        _, final_data, elapsed, err = solve_with_callback_proc(
            pieces_snapshot, gate_mm, solve_params,
            on_manifest=on_manifest, on_report=on_report, on_process=on_process,
            on_stage=on_stage, band=band_cfg,
        )
        # stopped 标志由 read_loop 在 stop/断开时置 True → 不再投 final/error（避免
        # 与 stopped 消息冲突；客户端只收 stopped 或 final/error，不会同时收）。
        if not state_box['stopped']:
            if err is not None:
                loop.call_soon_threadsafe(queue.put_nowait,
                    {'type': 'error', 'message': f'求解失败: {err}'})
            elif final_data is not None:
                loop.call_soon_threadsafe(queue.put_nowait, {
                    'type': 'final',
                    'density': final_data['density'],
                    'density_sparrow': final_data['density_sparrow'],
                    'width_mm': final_data['width_mm'],
                    'elapsed': round(elapsed, 2),
                    'n_frames': state_box['n_frames'],
                    'n_eroded': state_box['n_eroded'],
                })
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
