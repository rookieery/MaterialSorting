"""排料求解子进程 worker — 把 build_instance + solve 封装进独立进程（US-025）。

从 daemon threading 模型（旧 ``solver.solve_with_callback``）迁到 ``multiprocessing.Process``
模型，让调用方拿到 ``Process`` 句柄可随时 ``terminate()``（OS 级回收，唯一可靠终止
spyrrow Rust 原生 ``solve()`` 的方式 —— 全包无 cancel/abort/stop/pause/kill/terminate
匹配，threading.Thread 无法安全终止原生代码线程）。

spyrrow 对象不可 pickle，故 ``build_instance`` 必须在子进程内执行，只把 JSON 可序列化
数据（pid_meta / frame / final / error）经 ``multiprocessing.Queue`` 传回主进程。

**picklable 约束（Windows spawn）**：``solve_worker`` 必须是**顶层函数**、无闭包、参数
全部 JSON 可序列化（list/dict/float/int/str）。子进程 spawn 时会通过 pickle 重建本函数。
"""
from __future__ import annotations

import threading
import time


def solve_worker(pieces_snapshot, gate_mm, solve_params, result_queue):
    """子进程入口：build_instance → manifest → solve → frame* → final | error。

    Parameters
    ----------
    pieces_snapshot : list[dict]
        intermediate 的 pieces 字段（纯 JSON；spyrrow 对象尚未构造）。
    gate_mm : float
        门幅（mm，spyrrow 世界坐标 Y 范围）。
    solve_params : dict
        拆给 ``build_instance`` 的关键字参数 —— ``time_budget`` / ``seed`` / ``sizes``
        / ``params`` / ``per_type`` / ``quantities`` / ``solver_opts``（US-006，全部
        JSON 可序列化；``solver_opts`` 原样透传给 ``build_instance`` 做白名单清洗，
        本 worker 不解释旋钮语义）。
    result_queue : multiprocessing.Queue
        子进程 → 主进程的消息队列。投递内容全部 JSON 可序列化，spyrrow 对象绝不跨进程：
        - ``{kind:'manifest', pid_meta, total_area, n_eroded, gate_mm}``（首条）
        - ``{kind:'frame', report}`` 每个 sparrow 中间解（report 内含 density/width_mm/placed_items）
        - ``{kind:'final', final}`` 末态解（同 frame 但 type=final、无 phase）
        - ``{kind:'error', message}`` 异常路径（build_instance 抛错 / solve 崩溃）

    density 双口径换算（关键不变量 #1）**不在子进程做**：子进程原样透传 sparrow 自报
    density；主进程在处理 frame 时按 ``total_area/(width*gate)`` 换算为原面积口径
    （total_area 由 manifest 数据带入主进程）。
    """
    # 延迟 import：子进程 spawn 时 ``from .solver import build_instance`` 触发整条
    # web 包链（含 sparrow_baseline 等重模块）import；放函数内让父进程 spawn 子进程
    # 的开销与子进程 import 开销分离，也避免主进程 ``from .solve_worker import solve_worker``
    # 时强制 import sparrow_baseline（保持 ``__init__`` 零副作用）。
    from .solver import build_instance

    try:
        instance, config, pid_meta, total_area, n_eroded = build_instance(
            pieces_snapshot, gate_mm, **solve_params
        )
    except Exception as e:
        result_queue.put({'kind': 'error', 'message': f'构造实例失败: {e}'})
        return

    # 1) manifest：base 几何 + 颜色 + US-024 5 层。total_area 透传到主进程供 density 双口径换算。
    result_queue.put({
        'kind': 'manifest',
        'pid_meta': pid_meta,
        'total_area': total_area,
        'n_eroded': n_eroded,
        'gate_mm': float(gate_mm),
    })

    # 2) solve + drain 投递 frame。sparrow 的 instance.solve 是阻塞调用，ProgressQueue
    #    thread-safe —— 复用旧 threading 骨架：子进程内再开一个 daemon 子线程跑 solve，
    #    主线程 drain；如此才能在 solve 阻塞期间持续投递 frame。terminate() 整个子进程
    #    时这些线程随进程一起回收（OS 级），无遗留。
    import spyrrow

    progress = spyrrow.ProgressQueue()
    holder: dict = {}
    t0 = time.time()

    def _solve():
        try:
            holder['sol'] = instance.solve(config, progress=progress)
        except Exception as e:
            holder['err'] = e

    th = threading.Thread(target=_solve, daemon=True)
    th.start()
    while th.is_alive():
        for rtype, mid in progress.drain():
            result_queue.put({'kind': 'frame', 'report': _emit_frame(rtype, mid, t0)})
        time.sleep(0.2)
    th.join()
    for rtype, mid in progress.drain():
        result_queue.put({'kind': 'frame', 'report': _emit_frame(rtype, mid, t0)})

    err = holder.get('err')
    if err is not None:
        result_queue.put({'kind': 'error', 'message': f'求解失败: {err}'})
        return

    sol = holder.get('sol')
    if sol is None:
        # 理论上不可达（err 为 None 则 sol 必被赋值）；防御性兜底。
        result_queue.put({'kind': 'error', 'message': '求解失败: solver 返回 None'})
        return

    # 3) final：末态解。density 仍为 sparrow 自报口径，主进程处理时按 total_area 换算。
    result_queue.put({
        'kind': 'final',
        'final': {
            'type': 'final',
            'density': float(sol.density),
            'width_mm': float(sol.width),
            'elapsed': round(time.time() - t0, 3),
            'placed_items': _emit_placed(sol.placed_items),
        },
    })


def _emit_frame(rtype, sol, t0):
    """把 spyrrow 的 (ReportType, Solution) → JSON 可序列化 frame dict。

    顶层函数（非闭包）；density 为 sparrow 自报口径，主进程再换算为原面积口径。
    """
    return {
        'type': 'frame',
        'elapsed': round(time.time() - t0, 3),
        'phase': rtype.phase_name(),
        'density': float(sol.density),
        'width_mm': float(sol.width),
        'placed_items': _emit_placed(sol.placed_items),
    }


def _emit_placed(placed_items):
    """spyrrow PlacedItem 列表 → JSON list[{id, rotation, translation}]。"""
    out = []
    for pi in placed_items:
        tx, ty = pi.translation
        out.append({
            'id': pi.id,
            'rotation': float(pi.rotation),
            'translation': [float(tx), float(ty)],
        })
    return out
