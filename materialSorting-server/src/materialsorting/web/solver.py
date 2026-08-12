"""排料可视化工作台 · 求解封装 —— 把 sparrow 求解过程回调出来（含完整 placed_items）。

阶段 A：复用 sparrow_baseline 的「子线程 solve + 主线程 drain」骨架，每个中间解回调完整 placement。
阶段 B：build_instance 参数化 v0.3 约束（重合 erode 内/外两档 + 旋转公差离散化 + 每片型高级覆盖）。

不改动 sparrow 源码、不改动既有引擎代码，仅 sys.path 引用：
  _clean_polygon / PTYPE_COLORS  (sparrow_baseline)
  erode_polygon / INTERNAL_TYPES (sparrow_experiments)
  MAX_OVERLAP / ROTATION_TOL     (constraints，v0.3 常量表)
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

from .. import paths
from ..nesting_engine.sparrow_baseline import _clean_polygon, PTYPE_COLORS
from ..nesting_engine.sparrow_experiments import erode_polygon, INTERNAL_TYPES
from ..nesting_engine.constraints import MAX_OVERLAP, ROTATION_TOL

DEFAULT_INTERMEDIATE = paths.INTERMEDIATE


def load_pieces(intermediate_path: str = DEFAULT_INTERMEDIATE):
    """读 pieces_intermediate.json。返回 (doc, gate_mm, pieces)。"""
    with open(intermediate_path, encoding='utf-8') as f:
        doc = json.load(f)
    return doc, float(doc['gate_mm']), doc['pieces']


def discretize_orientations(tol: float):
    """v0.3 旋转公差 tol(度) → spyrrow 离散角度集。

    spyrrow 的 allowed_orientations 只接受离散列表或 None（不支持连续公差，见 .pyi）；
    故 v0.3 的「±N° 连续公差」离散化为角度集合。

    tol=0 → [0,180]（严格布纹线，= 阶段 A baseline）。
    tol>0 → 在 0°/180° 附近 ±tol 内按自适应步进离散：tol≤5 用 1°、否则 5°。
      例 tol=2 → [0,1,2,178,179,180,181,182,358,359]（10 个，外部片几乎锁布纹线）
      例 tol=45 → 0/180 附近 ±45°/步进5° ≈ 38 个（接近自由）
    返回 sorted list[float]，归一化到 [0,360)。实测 spyrrow 对大角度集不敏感（72 角度不报错/不降速）。
    """
    if tol <= 0:
        return [0.0, 180.0]
    step = 1.0 if tol <= 5 else 5.0
    angs = set()
    for base in (0.0, 180.0):
        k = 0
        while k * step <= tol + 1e-9:
            for off in (k * step, -k * step):
                angs.add(round((base + off) % 360.0, 2))
            k += 1
    return sorted(angs)


def build_instance(pieces, gate_mm, *, time_budget: int, seed: int,
                   sizes=None, params=None, per_type=None, quantities=None):
    """按码号 + v0.3 参数构造 (instance, config, pid_meta, total_area, n_eroded)。

    params = {d_ext, d_int, tol_ext, tol_int}（内/外两档；默认全 0 = 阶段A baseline）
    per_type = {ptype: {d?, tol?}}（每片型高级覆盖；缺的维度回退两档）
    quantities = {label: {sizeKey(str): N}} | None（US-022 per-size demand）。
        - 按 (piece.label, str(piece.size)) 查 N → ``spyrrow.Item(demand=N)``；
        - **demand=0 跳过该 piece（D2）**（该码该 ptype 不参与排料）；
        - piece 缺 label 或 quantities=None → demand=1（向后兼容旧 intermediate / 旧前端）。

    每片实际 erode = min(申请值, MAX_OVERLAP[ptype])（v0.3 工艺上限兜底）
    每片实际 tol  = min(申请值, ROTATION_TOL[ptype])
    内部片 = 单排/双排/火机袋/裤耳；外部片 = 其余。
    """
    import spyrrow
    pdef = {'d_ext': 0.0, 'd_int': 0.0, 'tol_ext': 0.0, 'tol_int': 0.0}
    if params:
        pdef.update(params)

    if sizes:
        want = {int(s) for s in sizes}
        pieces = [p for p in pieces if p['size'] in want]

    pid_meta = {}
    items = []
    n_eroded = 0
    # total_area 必须按「实际排料面积」累加 = Σ(area × demand)，仅含真正进 sparrow 的片。
    # 旧实现 ``sum(p['area_mm2'] for p in pieces)`` 有两处错：(1) 漏乘 demand —— demand>1
    # 时求解器排 N 份、用布长度变 N 倍，但面积只算 1 份 → real_density 被 demand 整除
    # （demand=2 时 84% 被错报成 ~42%）；(2) 把 demand=0 跳过的片也计入了面积。两者都修。
    total_area = 0.0
    for p in pieces:
        # US-022：先定 demand（demand=0 跳过该 piece，不进 sparrow 实例）。
        # sizeKey 口径与前端 qtyStore 一致：number->String(number)；null->'null'。
        # 旧 intermediate 无 label 或 quantities=None → demand=1（向后兼容）。
        label = p.get('label')
        if quantities and label is not None and label in quantities:
            size_map = quantities[label]
            if not isinstance(size_map, dict):
                size_map = {}
            sk = 'null' if p['size'] is None else str(p['size'])
            demand = int(size_map.get(sk, 0))
        else:
            demand = 1
        if demand <= 0:
            continue   # D2：该 piece 该码 demand=0 → 不排（也不计入 total_area）

        ptype = p['ptype']
        internal = ptype in INTERNAL_TYPES
        base_d = float(pdef['d_int'] if internal else pdef['d_ext'])
        base_tol = float(pdef['tol_int'] if internal else pdef['tol_ext'])

        if per_type and ptype in per_type:
            d = float(per_type[ptype].get('d', base_d))
            tol = float(per_type[ptype].get('tol', base_tol))
        else:
            d, tol = base_d, base_tol

        d = min(d, float(MAX_OVERLAP.get(ptype, 0.0)))       # v0.3 重合上限
        tol = min(tol, float(ROTATION_TOL.get(ptype, 0.0)))  # v0.3 旋转上限

        poly = p['polygon']
        if d > 0:
            poly = erode_polygon(poly, d)
            n_eroded += 1
        poly = _clean_polygon(poly)
        if len(poly) < 3:
            continue

        orientations = discretize_orientations(tol)
        # US-024：5 层细节（net_polygon/internal_lines/notches/grain_line）从 intermediate 透传
        # 到 pid_meta → manifest → 前端 NestSVG + 导出。**不参与 sparrow NFP 碰撞**（碰撞只用
        # 上面 erode 后的 ``poly``）。使用 .get() 兜底，旧 intermediate 无这些字段时各层空/None。
        pid_meta[p['pid']] = {
            'ptype': ptype,
            'size': p['size'],
            'color': PTYPE_COLORS.get(ptype, '#bbbbbb'),
            'polygon': poly,                 # erode 后 base 多边形（与 placement 一致）
            'area_mm2': p['area_mm2'],
            # demand：该 pid 进 sparrow 的副本数（= quantities[label][sizeKey]，缺省 1）。
            # 透传到 manifest → 前端 NestSVG 按 demand 建 N 个 DOM 副本（见下「多副本渲染」）。
            # **必须透传**：demand>1 时 solver 给同一 pid 发 N 条 placed_items（同 id 不同 translation），
            # 若前端只建 1 个 polygon 会被后一条覆盖 → 只剩 1/N 副本可见（视觉稀疏，密度数却正确）。
            'demand': demand,
            'net_polygon': p.get('net_polygon', []),
            'internal_lines': p.get('internal_lines', []),
            'notches': p.get('notches', []),
            'grain_line': p.get('grain_line'),
        }
        items.append(spyrrow.Item(
            id=p['pid'],
            shape=[(float(x), float(y)) for x, y in poly],
            demand=demand,
            allowed_orientations=orientations,
        ))
        total_area += float(p['area_mm2']) * demand
    instance = spyrrow.StripPackingInstance(
        name='workbench', strip_height=gate_mm, items=items)
    config = spyrrow.StripPackingConfig(
        total_computation_time=time_budget, seed=seed, num_workers=4)
    return instance, config, pid_meta, total_area, n_eroded


def solve_with_callback(instance, config, on_report, *, drain_interval: float = 0.2):
    """子线程跑 instance.solve，主线程 drain；每个中间解同步调 on_report(report)。

    report = {type:frame, elapsed, phase, density, width_mm, placed_items}
    （density/width_mm 为 spyrrow 口径；原面积口径 real_density 由 server 侧按 total_area 重算）

    返回 (final_sol, elapsed_sec, err)。
    """
    import spyrrow
    queue = spyrrow.ProgressQueue()
    holder: dict = {}
    t0 = time.time()

    def _solve():
        try:
            holder['sol'] = instance.solve(config, progress=queue)
        except Exception as e:
            holder['err'] = e

    def _emit(rtype, sol):
        placed = []
        for pi in sol.placed_items:
            tx, ty = pi.translation
            placed.append({
                'id': pi.id,
                'rotation': float(pi.rotation),
                'translation': [float(tx), float(ty)],
            })
        on_report({
            'type': 'frame',
            'elapsed': round(time.time() - t0, 3),
            'phase': rtype.phase_name(),
            'density': float(sol.density),     # spyrrow 口径（erode 后面积）
            'width_mm': float(sol.width),
            'placed_items': placed,
        })

    th = threading.Thread(target=_solve, daemon=True)
    th.start()
    while th.is_alive():
        for rtype, sol in queue.drain():
            _emit(rtype, sol)
        time.sleep(drain_interval)
    th.join()
    for rtype, sol in queue.drain():
        _emit(rtype, sol)
    return holder.get('sol'), time.time() - t0, holder.get('err')
