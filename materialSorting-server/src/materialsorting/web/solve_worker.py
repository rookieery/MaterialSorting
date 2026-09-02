"""排料求解子进程 worker — 把 build_instance + solve 封装进独立进程（US-025）。

从 daemon threading 模型（旧 ``solver.solve_with_callback``）迁到 ``multiprocessing.Process``
模型，让调用方拿到 ``Process`` 句柄可随时 ``terminate()``（OS 级回收，唯一可靠终止
spyrrow Rust 原生 ``solve()`` 的方式 —— 全包无 cancel/abort/stop/pause/kill/terminate
匹配，threading.Thread 无法安全终止原生代码线程）。

spyrrow 对象不可 pickle，故 ``build_instance`` 必须在子进程内执行，只把 JSON 可序列化
数据（pid_meta / frame / final / error）经 ``multiprocessing.Queue`` 传回主进程。

US-011（腰头成带编排）：``band`` 配置非空时，本 worker 先在**进程内**构造腰头带
（``waist_band.build_band_plan`` v2 构造性链构造 —— 不 spawn 孙进程：
``routes_ws._terminate_solve_process`` 的 terminate 不级联孙进程，同步调用随本进程
一并被 OS 回收，stop 后无存活 python 子进程），投 ``{kind:stage}``（manifest 前唯一
一次），随后主实例以 ``exclude_labels={label}`` 构造并把组合片（WB_ pid）追加进
items；帧/final 发射经 ``_emit_placed`` **单点**把组合片 placement 展开回成员
placement（三处发射点共享该序列化器 → WB_ 永不出现在 manifest/frame/final）。

US-003（起始端成套前后幅编排）：``prefix`` 配置（worker 形态 ``{'front','back'}``，
无 size —— 选码此处确定）非空时，band 之后同样**进程内**同步构造，投
``{kind:stage, stage:'prefix', size, ...}``；主实例以 ``exclude_pids`` **pid 级**
扣减 + PS_ 组合片进 extra_items。final 后置换挂钩（FR-7）：组合片 min_x > 6mm 时
``pin_prefix_layout`` 置换 + 复检（失败回退），≤6mm 跳过（P0 常态锚定）；帧不置换
（final 为权威布局）。双开（band+prefix）时 WB 带位只记录不置换（FR-8）：世界
bbox（min_x/max_x/距布尾）写进 ``prefix_runs`` 工件与 final 统计段。

2026-09-02（异码补片，US-002）：``_build_prefix`` 选码换 ``select_prefix_plan``
（eligible→pick→build 三步内聚的单一真相源，与预览同函数）—— 近满幅几何搜索
产 5 片组合片（4 同码基座 + 顶部异码补片，全流程无 RNG；seed 仅兜底路径消费），
全无可行组合时兜底 4 片 seeded 构造（与旧行为完全一致，``fallback=True``）。
``exclude_pids`` 接线升级 ``Counter(m['pid'] for m in members)``（Mapping 形态
部分扣减）：4 片时 {front:2, back:2} 与集合跳过等价；5 片时异码 pid 扣 1 份、
余量照排主解 ⇒ placed 条数守恒 = 全量 Σdemand。stage/final/工件 additive 回显
选定组合（extra_label/extra_size/residual_mm + extra/residual_mm/fallback）。

**picklable 约束（Windows spawn）**：``solve_worker`` 必须是**顶层函数**、无闭包、参数
全部 JSON 可序列化（list/dict/float/int/str）。子进程 spawn 时会通过 pickle 重建本函数。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import Counter

_log = logging.getLogger(__name__)


def solve_worker(pieces_snapshot, gate_mm, solve_params, result_queue, band=None,
                 prefix=None):
    """子进程入口：[band] → [prefix] → build_instance → manifest → solve → frame* → final | error。

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
        - ``{kind:'stage', stage, fill_pct, bbox, fallback, elapsed}``（US-011：band
          开启时 manifest 前唯一一次，带内聚排完成统计）
        - ``{kind:'stage', stage:'prefix', size, fill_pct, bbox, holes, fallback,
          extra_label, extra_size, residual_mm, elapsed}``（US-003：prefix 开启时
          manifest 前唯一一次；双开时 band→prefix 序；2026-09-02 异码补片 additive
          —— extra_label/extra_size 仅补片在案时非 None，fallback=True 即兜底
          4 片形态）
        - ``{kind:'manifest', pid_meta, total_area, n_eroded, gate_mm}``
        - ``{kind:'frame', report}`` 每个 sparrow 中间解（report 内含 density/width_mm/placed_items）
        - ``{kind:'final', final}`` 末态解（同 frame 但 type=final、无 phase；prefix
          开启时另含 ``prefix`` 统计段：size/pin/band_pos）
        - ``{kind:'error', message}`` 异常路径（成带失败 / 前缀构造失败 /
          build_instance 抛错 / solve 崩溃；band/prefix 失败只投 error 不投
          manifest，与 build 失败同契约）
    band : dict | None
        US-011 成带配置 ``{'label': str}``（routes_ws 服务端校验产物）。None/缺
        label = 关闭，走原五元路径。``BandChunk`` 只在本进程存活，绝不跨进程
        （frame/final 里的组合片条目已展开成成员 placement）。
    prefix : dict | None
        US-003 起始端成套配置 ``{'front': g码, 'back': g码}``（routes_ws
        ``_parse_prefix`` 服务端校验产物，**无 size 键**）。None/缺键 = 关闭。
        选码在本进程内经 ``select_prefix_plan`` 确定（2026-09-02 起近满幅几何
        搜索 + 兜底 seeded，见 ``_build_prefix``），构造/展开/final 置换守卫全在
        本进程（``BandChunk``/pin stats 不跨进程，回放工件经
        ``_write_prefix_artifact`` 落 ``paths.PREFIX_RUNS_DIR``）。

    density 双口径换算（关键不变量 #1）**不在子进程做**：子进程原样透传 sparrow 自报
    density；主进程在处理 frame 时按 ``total_area/(width*gate)`` 换算为原面积口径
    （total_area 由 manifest 数据带入主进程）。
    """
    # 延迟 import：子进程 spawn 时 ``from .solver import build_instance`` 触发整条
    # web 包链（含 sparrow_baseline 等重模块）import；放函数内让父进程 spawn 子进程
    # 的开销与子进程 import 开销分离，也避免主进程 ``from .solve_worker import solve_worker``
    # 时强制 import sparrow_baseline（保持 ``__init__`` 零副作用）。
    from .solver import build_instance

    band_chunk = None
    if isinstance(band, dict) and band.get('label'):
        band_chunk = _build_band(pieces_snapshot, gate_mm, solve_params, band, result_queue)
        if band_chunk is None:
            return   # 成带失败：error 已投（只投 error 不投 manifest）

    # US-003：prefix 构造在 band 之后（双开 stage 序 band→prefix→manifest）。
    prefix_ctx = None
    if isinstance(prefix, dict) and prefix.get('front') and prefix.get('back'):
        prefix_ctx = _build_prefix(pieces_snapshot, gate_mm, solve_params, prefix,
                                   result_queue)
        if prefix_ctx is None:
            return   # 前缀构造失败：error 已投（只投 error 不投 manifest）

    extra_items = None
    if band_chunk is not None:
        # 组合片 demand=1、朝向 [0,180] 顺布纹不带抖动（FR-8）。**必须构造期传入**
        # （extra_items）：spyrrow ``instance.items`` 是 Rust 侧副本 list，构造后
        # append 不生效（实测组合片整解缺席 —— 见 build_instance docstring）。
        from ..nesting_engine.waist_band import COMPOSITE_ORIENTATIONS
        extra_items = [{
            'id': band_chunk.pid,
            'polygon': band_chunk.polygon,
            'demand': 1,
            'orientations': list(COMPOSITE_ORIENTATIONS),
        }]
    if prefix_ctx is not None:
        from ..nesting_engine.prefix import PREFIX_ORIENTATIONS
        ps_item = {
            'id': prefix_ctx['chunk'].pid,
            'polygon': prefix_ctx['chunk'].polygon,
            'demand': 1,
            # FR-5 决策③：[0.,180.] 放开（版师认可整列头尾调换，构造形态不变）。
            'orientations': list(PREFIX_ORIENTATIONS),
        }
        extra_items = ([*extra_items, ps_item] if extra_items else [ps_item])

    prefix_chunk = prefix_ctx['chunk'] if prefix_ctx is not None else None
    try:
        instance, config, pid_meta, total_area, n_eroded = build_instance(
            pieces_snapshot, gate_mm,
            exclude_labels=({band_chunk.label} if band_chunk is not None else None),
            # US-003：pid 级扣减 —— {(front,size),(back,size)} 两 pid 的 2+2 份由
            # PS_ 组合片承载（同码其他码照排；label 级会连其他码全丢）。
            # 2026-09-02 Mapping 形态（成员计数 Counter）：4 片时 {front:2,back:2}
            # 与集合跳过等价；5 片时异码 pid 扣 1 份、余量照排主解（placed 守恒
            # = 全量 Σdemand）。
            exclude_pids=(Counter(m['pid'] for m in prefix_chunk.members)
                          if prefix_chunk is not None else None),
            extra_items=extra_items,
            **solve_params
        )
    except Exception as e:
        result_queue.put({'kind': 'error', 'message': f'构造实例失败: {e}'})
        return

    # 1) manifest：base 几何 + 颜色 + US-024 5 层。total_area 透传到主进程供 density
    #    双口径换算。band 开启时 manifest 与 band off **逐字段一致**（exclude_labels
    #    只跳 Item 层，pid_meta/total_area 原样），pid_meta 恒无 WB_ 条目。
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
        # BaseException：spyrrow Rust panic 抛 pyo3 PanicException（BaseException
        # 子类，非 Exception）—— except Exception 捕不住会静默杀死本线程，holder
        # 保持空 ⇒ 对外误报「solver 返回 None」（2026-09-02 无 per_type prefix
        # 组合片贴线事故）。daemon 求解线程收不到 KeyboardInterrupt（信号只投
        # 主线程），此处捕 BaseException 不吞 Ctrl-C。
        try:
            holder['sol'] = instance.solve(config, progress=progress)
        except BaseException as e:            # noqa: BLE001 见上注
            holder['err'] = f'{type(e).__name__}: {e}'

    th = threading.Thread(target=_solve, daemon=True)
    th.start()
    while th.is_alive():
        for rtype, mid in progress.drain():
            result_queue.put({'kind': 'frame',
                              'report': _emit_frame(rtype, mid, t0, band_chunk,
                                                    prefix_chunk)})
        time.sleep(0.2)
    th.join()
    for rtype, mid in progress.drain():
        result_queue.put({'kind': 'frame',
                          'report': _emit_frame(rtype, mid, t0, band_chunk,
                                                prefix_chunk)})

    err = holder.get('err')
    if err is not None:
        result_queue.put({'kind': 'error', 'message': f'求解失败: {err}'})
        return

    sol = holder.get('sol')
    if sol is None:
        # 防御性兜底：2026-09-02 起 _solve 捕 BaseException（含 pyo3
        # PanicException），err=None 则 sol 必被赋值 —— 真正到达此处只剩
        # solve 正常返回 None（未见先例）。
        result_queue.put({'kind': 'error', 'message': '求解失败: solver 返回 None'})
        return

    # 3) final：末态解。density 仍为 sparrow 自报口径，主进程处理时按 total_area 换算。
    #    US-003：prefix 开启时先过 final 置换挂钩（pin + 带位记录），工件先落盘
    #    （写失败仅 warn）再投 final —— 测试/回放侧收 final 即工件在案。
    if prefix_ctx is not None:
        placed_final, width_final, prefix_record = _finalize_prefix(
            sol, prefix_ctx, band_chunk, pid_meta, pieces_snapshot, gate_mm)
        final = {
            'type': 'final',
            'density': float(sol.density),
            'width_mm': width_final,
            'elapsed': round(time.time() - t0, 3),
            'placed_items': placed_final,
            'prefix': {
                'size': int(prefix_record['size']),
                'pid': prefix_record['pid'],
                'pin': prefix_record['pin'],
                'band_pos': prefix_record['band_pos'],
                # 2026-09-02 异码补片 additive（随 record 整体透传，routes_ws
                # final 段原样转发）：extra=None 即兜底 4 片形态。
                'extra': prefix_record['extra'],
                'residual_mm': prefix_record['residual_mm'],
                'fallback': prefix_record['fallback'],
            },
        }
        _write_prefix_artifact(prefix_record)
    else:
        final = {
            'type': 'final',
            'density': float(sol.density),
            'width_mm': float(sol.width),
            'elapsed': round(time.time() - t0, 3),
            'placed_items': _emit_placed(sol.placed_items, band_chunk, prefix_chunk),
        }
    result_queue.put({'kind': 'final', 'final': final})


# ------------------------------------------------------- US-011 成带（进程内）


def _build_band(pieces_snapshot, gate_mm, solve_params, band, result_queue):
    """成带（US-011 编排层）：本进程内同步跑 ``build_band_plan``（v2 构造性链
    构造，确定性毫秒级 —— 2026-08-21 起替换 v1 spyrrow 带内子求解）。

    进程模型（落地方案 §2.6）：**不 spawn 孙进程** —— 父级 ``terminate()`` 不级联
    孙进程，band 跑在本 worker 进程内（同步调用）则随进程整体被 OS 回收，stop 后
    无存活 python 子进程。

    d_g/tol_g 与主实例同源裁定（``_resolve_d_tol`` 单一真相源 —— FR-3 带内 per_type
    沿用该 g 码的 d/tol）；带高守卫界 = gate_mm（输入门幅即实际幅宽，与主解同口径）。

    失败（BandError/ValueError 等）投 ``{kind:error}``（「成带失败」前缀，只投 error
    不投 manifest —— 与 build_instance 抛错同契约）返回 None；成功投 ``{kind:stage}``
    （fill_pct/bbox/fallback=False/elapsed，manifest 前唯一一次）后返回 ``BandChunk``
    （只在本进程存活，绝不跨队列）。
    """
    from ..nesting_engine.waist_band import BandError, build_band_plan
    from .solver import _resolve_d_tol, build_pid_meta

    label = str(band['label'])
    t0 = time.time()
    try:
        pdef = {'d_ext': 0.0, 'd_int': 0.0, 'tol_ext': 0.0, 'tol_int': 0.0}
        pdef.update(solve_params.get('params') or {})
        d_g, tol_g = _resolve_d_tol(label, pdef, solve_params.get('per_type'))
        pid_meta, _area, _n = build_pid_meta(
            pieces_snapshot,
            sizes=solve_params.get('sizes'),
            per_type=solve_params.get('per_type'),
            quantities=solve_params.get('quantities'),
            params=solve_params.get('params'))
        chunk = build_band_plan(
            pid_meta, {p['pid']: p for p in pieces_snapshot},
            label=label,
            seed=int(solve_params.get('seed', 0)),
            gate_nest=float(gate_mm),
            d_g=d_g, tol_g=tol_g)
    except (BandError, ValueError) as e:
        result_queue.put({'kind': 'error', 'message': f'成带失败: {e}'})
        return None
    except Exception as e:            # noqa: BLE001 进程边界：几何异常也须早退成 error 不崩进程
        result_queue.put({'kind': 'error', 'message': f'成带失败: {e}'})
        return None

    elapsed = time.time() - t0
    result_queue.put({
        'kind': 'stage', 'stage': 'band',
        'fill_pct': round(float(chunk.fill_pct), 2),
        'bbox': {'width_mm': float(chunk.bbox['width_mm']),
                 'height_mm': float(chunk.bbox['height_mm'])},
        'fallback': False,
        'elapsed': round(elapsed, 2),
    })
    return chunk


def _emit_frame(rtype, sol, t0, band=None, prefix=None):
    """把 spyrrow 的 (ReportType, Solution) → JSON 可序列化 frame dict。

    顶层函数（非闭包）；density 为 sparrow 自报口径，主进程再换算为原面积口径。
    ``band`` / ``prefix``（BandChunk）非 None 时组合片条目在 ``_emit_placed``
    单点展开（US-011 / US-003）。帧不置换（FR-6：final 为权威布局）。
    """
    return {
        'type': 'frame',
        'elapsed': round(time.time() - t0, 3),
        'phase': rtype.phase_name(),
        'density': float(sol.density),
        'width_mm': float(sol.width),
        'placed_items': _emit_placed(sol.placed_items, band, prefix),
    }


def _emit_placed(placed_items, band=None, prefix=None):
    """spyrrow PlacedItem 列表 → JSON list[{id, rotation, translation}]。

    US-011 / US-003 **展开单点**：``band`` / ``prefix``（``BandChunk``）非 None 时，
    组合片（WB_ / PS_ pid）条目在此展开回成员 placement（``expand_placements``
    权威式，shape 与本函数产物对齐）—— 帧与 final 发射点共享本序列化器，WB_ /
    PS_ pid 永不出现在跨进程产物。
    """
    from ..nesting_engine.waist_band import expand_placements

    out = []
    for pi in placed_items:
        tx, ty = pi.translation
        if band is not None and pi.id == band.pid:
            out.extend(expand_placements(band, float(pi.rotation), (float(tx), float(ty))))
            continue
        if prefix is not None and pi.id == prefix.pid:
            out.extend(expand_placements(prefix, float(pi.rotation), (float(tx), float(ty))))
            continue
        out.append({
            'id': pi.id,
            'rotation': float(pi.rotation),
            'translation': [float(tx), float(ty)],
        })
    return out


# -------------------------------------------------- US-003 前缀（进程内）


def _build_prefix(pieces_snapshot, gate_mm, solve_params, prefix, result_queue):
    """前缀构造（US-003 编排层）：本进程内同步跑构造管线（确定性毫秒级）。

    管线（2026-09-02 起三步内聚为 ``select_prefix_plan`` 单一真相源，与
    /api/prefix-preview 预览同函数）：资格码 → 近满幅组合搜索（4 片同码基座 +
    顶部异码补片，全流程无 RNG，取 H 最大者）→ ``build_prefix_plan`` 构造 PS_
    组合片；全无可行组合时兜底 ``pick_prefix_size`` seeded 选码 + 4 片构造
    （与旧行为完全一致，``info['fallback']=True``；``seed`` 仅此路径消费）。
    d_g = max(d_front, d_back)（``_resolve_d_tol`` 单一真相源，前后幅 per_type
    d 可能不同取保守端）。

    失败（PrefixError/ValueError 等）投 ``{kind:error}``（「前缀构造失败」前缀，
    只投 error 不投 manifest —— 与 ``_build_band`` 同契约）返回 None；成功投
    ``{kind:stage, stage:'prefix', size, fill_pct, bbox, holes, fallback,
    extra_label, extra_size, residual_mm, elapsed}``（manifest 前唯一一次，
    size 回显选中资格码；2026-09-02 additive —— 补片在案时 extra_label/
    extra_size 非 None、residual_mm = gate − 组合片高、兜底路径 fallback=True）
    后返回上下文 dict::

        {'chunk', 'front', 'back', 'size', 'gaps', 'holes', 'd_g', 'elapsed',
         'extra', 'residual_mm', 'fallback'}

    （``BandChunk`` 只在本进程存活，绝不跨队列。）
    """
    from ..nesting_engine.prefix import PrefixError, select_prefix_plan
    from .solver import _resolve_d_tol, build_pid_meta

    front = str(prefix['front'])
    back = str(prefix['back'])
    t0 = time.time()
    try:
        # sizes 空列表 = 不过滤（与 build_pid_meta 的 if sizes: 口径一致；
        # eligible_sizes 的 None 语义同效）。
        sizes = solve_params.get('sizes') or None
        quantities = solve_params.get('quantities')
        pdef = {'d_ext': 0.0, 'd_int': 0.0, 'tol_ext': 0.0, 'tol_int': 0.0}
        pdef.update(solve_params.get('params') or {})
        d_front, _tf = _resolve_d_tol(front, pdef, solve_params.get('per_type'))
        d_back, _tb = _resolve_d_tol(back, pdef, solve_params.get('per_type'))
        d_g = max(d_front, d_back)
        pid_meta, _area, _n = build_pid_meta(
            pieces_snapshot,
            sizes=solve_params.get('sizes'),
            per_type=solve_params.get('per_type'),
            quantities=quantities,
            params=solve_params.get('params'))
        chunk, gaps, holes, info = select_prefix_plan(
            pid_meta, {p['pid']: p for p in pieces_snapshot},
            front_label=front, back_label=back,
            quantities=quantities, sizes=sizes,
            d_g=d_g, gate_nest=float(gate_mm),
            seed=int(solve_params.get('seed', 0)))
    except (PrefixError, ValueError) as e:
        result_queue.put({'kind': 'error', 'message': f'前缀构造失败: {e}'})
        return None
    except Exception as e:        # noqa: BLE001 进程边界：几何异常也须早退成 error 不崩进程
        result_queue.put({'kind': 'error', 'message': f'前缀构造失败: {e}'})
        return None

    elapsed = time.time() - t0
    extra = info['extra']
    result_queue.put({
        'kind': 'stage', 'stage': 'prefix',
        'size': int(info['size']),
        'fill_pct': round(float(chunk.fill_pct), 2),
        'bbox': {'width_mm': float(chunk.bbox['width_mm']),
                 'height_mm': float(chunk.bbox['height_mm'])},
        'holes': int(holes),
        # 2026-09-02 异码补片 additive：fallback=True 即兜底 4 片形态；
        # extra_label/extra_size 仅补片在案时非 None（routes_ws on_stage 白名单
        # 同步放行三键）。
        'fallback': bool(info['fallback']),
        'extra_label': (extra or {}).get('label'),
        'extra_size': (extra or {}).get('size'),
        'residual_mm': round(float(info['residual_mm']), 3),
        'elapsed': round(elapsed, 2),
    })
    return {'chunk': chunk, 'front': front, 'back': back,
            'size': int(info['size']),
            'gaps': gaps, 'holes': int(holes), 'd_g': float(d_g),
            'elapsed': round(elapsed, 2),
            'extra': extra,
            'residual_mm': float(info['residual_mm']),
            'fallback': bool(info['fallback'])}


def _finalize_prefix(sol, prefix_ctx, band_chunk, pid_meta, pieces_snapshot,
                     gate_mm):
    """final 置换挂钩 + 双开带位记录（FR-6/FR-7/FR-8，US-003 单点）。

    - 展开 PS_ → 4 成员（``expand_placements`` 权威式）+ 其余片序列化 →
      ``pin_prefix_layout`` 终检编排（min_x ≤ 6mm 跳过 / permute+复检失败回退，
      P0 常态锚定零触碰）；
    - width 口径：skip/回退 → ``sol.width``（求解器原样）；置换生效 → 按 pinned
      布局原始轮廓世界 bbox 重算（密度换算在主进程按 width_mm 自动跟随）；
    - 双开（``band_chunk`` 非 None）：WB 组合片归一化轮廓 @ 主解位的世界 bbox
      （min_x/max_x/距布尾）**只记录不置换**（2026-08-25 拍板，FR-8）。

    Returns ``(placed_items, width_mm, record)`` —— record 见
    ``_write_prefix_artifact``。
    """
    from ..nesting_engine.prefix import _world_raw_geom, pin_prefix_layout
    from ..nesting_engine.sparrow_baseline import _transform_polygon
    from ..nesting_engine.waist_band import _valid_geometry, expand_placements

    chunk = prefix_ctx['chunk']
    comp = next((pi for pi in sol.placed_items if pi.id == chunk.pid), None)
    # base = 非 PS_ 全体（双开时 WB_ 同样经 _emit_placed 单点展开 —— pin 布局的
    # pid_meta/pieces_by_id 只有真实 pid，组合片条目混入即 KeyError）。
    base = _emit_placed([pi for pi in sol.placed_items if pi.id != chunk.pid],
                        band_chunk)
    pieces_by_id = {p['pid']: p for p in pieces_snapshot}
    width = float(sol.width)
    if comp is None:
        # 理论不可达（demand=1 组合片必被放置）；防御：不置换、PS_ 无条目即无
        # 泄漏（成员缺席由守恒口径在测试/审计侧暴露），warn 记档。
        _log.warning('前缀组合片 %s 未出现在末态解（placed=%d），跳过置换挂钩',
                     chunk.pid, len(sol.placed_items))
        return base, width, _prefix_record(prefix_ctx, {'skipped': True,
                                                        'rolled_back': False,
                                                        'issues': ['composite missing']},
                                           None, width)

    members = expand_placements(chunk, comp.rotation, comp.translation)
    placements = base + members
    prefix_idx = list(range(len(base), len(placements)))
    pinned, pin_stats = pin_prefix_layout(
        placements, pid_meta, pieces_by_id, chunk,
        float(comp.rotation), [float(comp.translation[0]), float(comp.translation[1])],
        prefix_idx, gate_nest=float(gate_mm))
    if not pin_stats['skipped'] and not pin_stats['rolled_back']:
        geoms = [_world_raw_geom(p, pid_meta, pieces_by_id) for p in pinned]
        width = (max(g.bounds[2] for g in geoms)
                 - min(min(g.bounds[0] for g in geoms), 0.0))

    # 双开带位记录（FR-8：只记录不置换，布局不动）
    band_pos = None
    if band_chunk is not None:
        wb = next((pi for pi in sol.placed_items if pi.id == band_chunk.pid), None)
        if wb is not None:
            g = _valid_geometry(_transform_polygon(
                band_chunk.polygon, wb.rotation, wb.translation))
            minx, _miny, maxx, _maxy = g.bounds
            band_pos = {
                'pid': band_chunk.pid,
                'min_x': round(float(minx), 3),
                'max_x': round(float(maxx), 3),
                'min_y': round(float(g.bounds[1]), 3),
                'max_y': round(float(g.bounds[3]), 3),
                'dist_to_tail_mm': round(float(width - maxx), 3),
            }
    return pinned, width, _prefix_record(prefix_ctx, pin_stats, band_pos, width)


def _prefix_record(prefix_ctx, pin_stats, band_pos, width):
    """prefix_runs 工件 + final 统计段的记录体（纯 JSON；US-005 回放对拍数据源）。

    2026-09-02 异码补片 additive：``extra``（{'pid','label','size','rotation'} |
    None）/ ``residual_mm`` / ``fallback`` —— 工件与 final 统计段同源回显选定
    组合（extra=None 即兜底 4 片形态）。"""
    chunk = prefix_ctx['chunk']
    return {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'pid': chunk.pid,
        'front': prefix_ctx['front'],
        'back': prefix_ctx['back'],
        'size': int(prefix_ctx['size']),
        'fill_pct': round(float(chunk.fill_pct), 2),
        'bbox': {'width_mm': float(chunk.bbox['width_mm']),
                 'height_mm': float(chunk.bbox['height_mm'])},
        'holes': int(prefix_ctx['holes']),
        'gaps': [round(float(g), 3) for g in prefix_ctx['gaps']],
        'd_g': float(prefix_ctx['d_g']),
        'stage_elapsed': float(prefix_ctx['elapsed']),
        # 2026-09-02 异码补片：选定组合回显（final 统计段经 solve_worker 主体
        # 同键透传；工件对拍排除 wall-clock 后含此三键）。
        'extra': prefix_ctx['extra'],
        'residual_mm': round(float(prefix_ctx['residual_mm']), 3),
        'fallback': bool(prefix_ctx['fallback']),
        'chunk': chunk.to_dict(),          # 构造全量（polygon/members/offset）回放用
        'pin': pin_stats,
        'band_pos': band_pos,
        'width_mm': round(float(width), 3),
    }


def _write_prefix_artifact(record):
    """落 ``paths.PREFIX_RUNS_DIR/<时间戳>_<pid>.json``（写失败仅 warn，FR-6）。

    工件是 US-005 确定性回放对拍的数据源（资格码选取 + 构造 + pin stats + 带位
    记录全量在案）；I/O 失败绝不影响 solve 交付物（warn 记档即返回）。
    """
    try:
        from .. import paths
        run_dir = paths.PREFIX_RUNS_DIR
        os.makedirs(run_dir, exist_ok=True)
        fname = f"{record['ts'].replace(':', '').replace('-', '')}_{record['pid']}.json"
        with open(os.path.join(run_dir, fname), 'w', encoding='utf-8') as f:
            json.dump(record, f, ensure_ascii=False, indent=1)
    except Exception as e:          # noqa: BLE001 工件写入失败不影响求解交付物
        _log.warning('prefix 工件写入失败（不影响求解结果）: %s', e)
