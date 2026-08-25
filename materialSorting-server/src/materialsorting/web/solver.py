"""排料可视化工作台 · 求解封装 —— 把 sparrow 求解过程回调出来（含完整 placed_items）。

阶段 A：复用 sparrow_baseline 的「子线程 solve + 主线程 drain」骨架，每个中间解回调完整 placement。
阶段 B：build_instance 参数化 v0.3 约束（重合 erode + 旋转公差离散化 + 逐 g 码高级覆盖）。

US-002 起全链路 label 键：demand / per_type 均按 ``label`` 命中，internal（内片）
概念删除 —— 旧 ``params`` 的 d_int/tol_int 键仍被接受但不再有消费方（生产链路
params 恒 0）。颜色 2026-08-20 起走 ``size_color``（尺码 → 16 色循环表，同码同色
跨片型一致；此前为 g 码键）。
2026-08-18 回退 US-004 矩阵化：per_type 从 ``(label, sizeKey)`` 两级命中收敛回
单级 ``{label: {d?, tol?}}`` —— 重合/旋转是片型工艺属性、与码号无关，命中 label
即对该 g 码全部码号生效；quantities（数量矩阵）仍按 ``(label, sizeKey)`` 不变。

不改动 sparrow 源码、不改动既有引擎代码，仅 sys.path 引用：
  _clean_polygon / size_color    (sparrow_baseline)
  erode_polygon                   (sparrow_experiments)
  MAX_OVERLAP_MM / MAX_ROTATION_TOL_DEG (constraints，2026-08 起全局上限，不再按片型)

US-025 新增 ``solve_with_callback_proc`` —— 把求解从 daemon 线程模型迁到
``multiprocessing.Process`` 模型，让调用方持有进程句柄可 ``terminate()``（OS 级回收，
唯一可靠终止 spyrrow Rust 原生 solve 的方式）。旧 ``solve_with_callback``（threading 版）
**保留不删**，US-026 才切换 ``ws_solve`` 的调用方，保证本次提交系统行为零变化。

US-006（PC-006）``build_instance`` 新增可选 ``solver_opts``（spyrrow 求解旋钮透传，
additive 白名单）：``exploration_pct`` / ``quadtree_depth`` / ``num_workers`` 三键，
非法值 clamp + 忽略、不传 = 现行行为原样（total_computation_time 模式自动 80/20
分段）。solve_params 全 JSON 可序列化，Windows spawn 安全。

US-004（策略 web 桥接）提取 ``build_pid_meta`` —— ``build_instance`` 内「demand
判定 → per_type 覆盖 → erode/清洗 → pid_meta 构造 → total_area 累计」的裁片级
流水线独立成纯函数（**不 import spyrrow**），web 策略 result 端点用它按 start 时
快照口径组装 manifest（erode 后几何与 placed_items 对齐），不必构造求解实例；
``build_instance`` 改为调用它后补 spyrrow ``Item``/``StripPackingInstance`` 构造
（对拍单测保证提取前后输出逐字段一致）。

US-011（腰头成带编排接线）：``build_instance`` 加 ``exclude_labels`` —— band 成员
只在 **Item 构造层**跳过（组合片由调用方 ``solve_worker`` 以 WB_ pid 追加），
``pid_meta`` / ``total_area`` / manifest 原样保留（**禁**用 quantities=0 移除：
那会连 pid_meta/total_area 一起抹掉，密度掉 ~12pt，见落地方案 §2.2）；
``solve_with_callback_proc`` 加 ``on_stage`` 回调 + ``band`` 透传 —— drain 循环
显式转发 ``{kind:stage}``（此前未知 kind 静默丢弃），band 子配置原样带给
``solve_worker``（带构造在 worker 进程内跑，见其 docstring）。

US-003（起始端成套前后幅编排接线）：``build_instance`` 加 ``exclude_pids`` ——
**pid 级**扣减（区别 band 的 label 级：prefix 只消耗资格码 2+2 份，同码其他码
照排；``exclude_labels`` 会把整码前后幅全排除，密度崩）。两参数并存互不干扰
（band 用 labels、prefix 用 pids）。``solve_with_callback_proc`` 加 ``prefix``
透传 —— worker 形态 ``{'front': g码, 'back': g码}``（资格码在 worker 进程内
seeded 随机选取，见 ``solve_worker._build_prefix``）。
"""
from __future__ import annotations

import json
import math
import multiprocessing
import os
import queue as _queue_mod
import sys
import threading
import time

from .. import paths
from ..nesting_engine.sparrow_baseline import _clean_polygon, size_color
from ..nesting_engine.sparrow_experiments import erode_polygon
from ..nesting_engine.constraints import (
    MAX_OVERLAP_MM, MAX_ROTATION_TOL_DEG,
    discretize_orientations as _discretize_orientations,
)
from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM

DEFAULT_INTERMEDIATE = paths.INTERMEDIATE


def load_pieces(intermediate_path: str = DEFAULT_INTERMEDIATE):
    """读 pieces_intermediate.json（schema v2）。返回 (doc, gate_mm, pieces)。

    FR-9 旧数据不双读：v1 intermediate（片含 ptype/side 或顶层 ptype_representatives，
    含合成镜像的 176 片产物）明确报错「请重新 commit」，不做静默兼容 —— 重新 commit
    即迁移。
    """
    with open(intermediate_path, encoding='utf-8') as f:
        doc = json.load(f)
    pieces = doc['pieces']
    if pieces and any('ptype' in p or 'side' in p for p in pieces)             or 'ptype_representatives' in doc:
        raise RuntimeError(
            'intermediate 为旧版 schema v1（含 ptype/side），请重新 commit 母版生成新数据')
    return doc, float(doc['gate_mm']), pieces


def discretize_orientations(tol: float):
    """v0.3 旋转公差 tol(度) → spyrrow 离散角度集（re-export 保旧 import 路径）。

    US-009（2026-08-21）起真相源在 ``nesting_engine/constraints.py``（旋转公差离散属
    约束层职责，且 ``nesting_engine/waist_band`` 同口径消费但分层禁 import web）。
    语义零改动：tol=0 → [0,180]；tol>0 → 0°/180° 附近 ±tol 自适应步进（≤5° 用 1°，
    否则 5°），返回 sorted list[float] 归一化 [0,360)。
    """
    return _discretize_orientations(tol)


# ------------------------------------------------ US-006 solver_opts 清洗与换算


# exploration_pct 合法域（PRD PC-006：越界 clamp 到边界）。
_EXPLORATION_PCT_RANGE = (0.1, 0.95)
# quadtree_depth 合法域（spyrrow 常用值 3/4/5，越界 clamp）。
_QUADTREE_DEPTH_RANGE = (3, 5)


def _clamp_finite(value, lo, hi):
    """数值清洗：非数值 / NaN / ±inf → None（调用方忽略该键）；有限值 clamp 到 [lo, hi]。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return min(max(f, lo), hi)


def _normalize_solver_opts(solver_opts) -> dict:
    """solver_opts 白名单清洗（US-006）：只保留三键，非法值 clamp（越界）/ 忽略（非数值）。

    - ``exploration_pct``：clamp 到 [0.1, 0.95]；
    - ``quadtree_depth``：clamp 到 [3, 5] 后取整；
    - ``num_workers``：下限 1 后取整（无上限——按机器核数自治）；
    - 其余键一律忽略（additive 白名单，未知旋钮不透传给 spyrrow）。

    None / 非 dict / 空 dict → ``{}``（= 不改现行行为）。
    """
    if not isinstance(solver_opts, dict):
        return {}
    out: dict = {}
    pct = _clamp_finite(solver_opts.get('exploration_pct'), *_EXPLORATION_PCT_RANGE)
    if pct is not None:
        out['exploration_pct'] = pct
    depth = _clamp_finite(solver_opts.get('quadtree_depth'), *_QUADTREE_DEPTH_RANGE)
    if depth is not None:
        out['quadtree_depth'] = int(round(depth))
    workers = _clamp_finite(solver_opts.get('num_workers'), 1, math.inf)
    if workers is not None:
        out['num_workers'] = int(round(workers))
    return out


def _split_time_budget(total: int, pct: float) -> tuple[int, int]:
    """total 秒按 pct 切 (exploration_time, compression_time) 两段 int 秒。

    两段均 ≥1s（压缩段 0s 无意义）、四舍五入取整、和 ≈ total（|和 − total| ≤ 1s；
    total < 2s 的极端预算下为保两段 ≥1s，和可到 total + 1）。
    """
    expl = int(round(total * pct))
    if total >= 2:
        expl = min(max(expl, 1), total - 1)
    else:
        expl = max(expl, 1)
    return expl, max(1, total - expl)


def _resolve_d_tol(label, pdef: dict, per_type) -> tuple[float, float]:
    """单片的 (d, tol) 裁定：params 全局档 → per_type 按 label 覆盖 → 全局上限钳制。

    ``build_pid_meta``（pid_meta 构造，erode 用 d）与 ``build_instance``（spyrrow
    ``Item.allowed_orientations`` 用 tol）两处共用的单一真相源 —— US-004 提取时
    保证两处口径一致（对拍护栏的前提）。
    """
    base_d = float(pdef['d_ext'])
    base_tol = float(pdef['tol_ext'])
    d, tol = base_d, base_tol
    if per_type and label is not None and label in per_type:
        over = per_type[label]
        if isinstance(over, dict):
            d = float(over.get('d', base_d))
            tol = float(over.get('tol', base_tol))
    return min(d, MAX_OVERLAP_MM), min(tol, MAX_ROTATION_TOL_DEG)


def build_pid_meta(pieces, *, sizes=None, per_type=None, quantities=None,
                   params=None) -> tuple[dict, float, int]:
    """裁片级流水线 → ``(pid_meta, total_area, n_eroded)``（US-004 自 build_instance 提取）。

    流水线（与原 ``build_instance`` 内循环逐字段一致，对拍单测护栏）：
    sizes 过滤 → demand 判定（quantities 按 (label, str(size)) 查 N；0 = 跳过该
    piece）→ per_type 覆盖 + 全局上限钳制（``_resolve_d_tol``）→ erode/清洗
    （<3 顶点跳过）→ pid_meta 条目（含 5 层透传字段）→ ``total_area = Σ(area×demand)``。

    **不 import spyrrow、不构造求解对象** —— web 策略 result 端点组装 manifest 用
    （erode 后几何与 run 的 placed_items 对齐、demand 已含，前端 NestSVG 副本池按
    demand 建 N 份承接多副本 placement）。``params`` 为全局档
    （{d_ext, tol_ext, ...}，缺省全 0），语义与 ``build_instance`` 同名参数一致。

    返回：pid_meta = {pid: {size, color, polygon(erode后), area_mm2, label, demand,
    net_polygon, internal_lines, notches, grain_line}}。
    """
    pdef = {'d_ext': 0.0, 'd_int': 0.0, 'tol_ext': 0.0, 'tol_int': 0.0}
    if params:
        pdef.update(params)

    if sizes:
        want = {int(s) for s in sizes}
        pieces = [p for p in pieces if p['size'] in want]

    pid_meta = {}
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
        sk = 'null' if p['size'] is None else str(p['size'])
        if quantities and label is not None and label in quantities:
            size_map = quantities[label]
            if not isinstance(size_map, dict):
                size_map = {}
            demand = int(size_map.get(sk, 0))
        else:
            demand = 1
        if demand <= 0:
            continue   # D2：该 piece 该码 demand=0 → 不排（也不计入 total_area）

        # US-002：per_type 按 label 命中即覆盖（缺维度回退全局档）。2026-08-18 回退
        # US-004 矩阵化：单级 {label: {d?, tol?}}，命中即对该 g 码全部码号生效。
        # 旧两级 payload（{label: {sizeKey: {...}}}）在 label 层取不到 d/tol → 回退
        # 默认，no-op 不崩（对称向后兼容）。
        d, tol = _resolve_d_tol(label, pdef, per_type)

        poly = p['polygon']
        if d > 0:
            poly = erode_polygon(poly, d)
            n_eroded += 1
        poly = _clean_polygon(poly)
        if len(poly) < 3:
            continue

        # US-024：5 层细节（net_polygon/internal_lines/notches/grain_line）从 intermediate 透传
        # 到 pid_meta → manifest → 前端 NestSVG + 导出。**不参与 sparrow NFP 碰撞**（碰撞只用
        # 上面 erode 后的 ``poly``）。使用 .get() 兜底，旧 intermediate 无这些字段时各层空/None。
        pid_meta[p['pid']] = {
            'size': p['size'],
            # 尺码配色（size_color 单一真相源：同码同色跨片型一致，manifest → 前端
            # NestSVG fill / 导出 PNG 同源；旧 g 码配色 2026-08-20 换键为尺码）。
            'color': size_color(p['size']),
            'polygon': poly,                 # erode 后 base 多边形（与 placement 一致）
            'area_mm2': p['area_mm2'],
            # g 码裁片标识（intermediate label 透传 → manifest → 前端 NestSVG tooltip /
            # 导出逐片叠印；旧 intermediate 无 label → None，消费方按缺席降级）。
            'label': label,
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
        total_area += float(p['area_mm2']) * demand
    return pid_meta, total_area, n_eroded


def build_instance(pieces, gate_mm, *, time_budget: int, seed: int,
                   sizes=None, params=None, per_type=None, quantities=None,
                   solver_opts: dict | None = None, exclude_labels=None,
                   exclude_pids=None, extra_items=None):
    """按码号 + v0.3 参数构造 (instance, config, pid_meta, total_area, n_eroded)。

    params = {d_ext, d_int, tol_ext, tol_int}（默认全 0 = 阶段A baseline。US-002 起
    内/外两档已删，全片统一走 d_ext/tol_ext；d_int/tol_int 仍被接受但无消费方 ——
    生产链路 params 恒 0，仅为旧前端 payload 兼容保留键位）
    per_type = {label: {d?, tol?}}（US-002 起 label 级逐片覆盖；2026-08-18 回退 US-004
        矩阵化后单级——命中 label 即对该 g 码**全部码号**覆盖，缺维度回退 params 的
        d_ext/tol_ext；旧 ptype 键 / 旧两级 {label:{sizeKey:...}} 键不命中为 no-op）
    quantities = {label: {sizeKey(str): N}} | None（US-022 per-size demand）。
        - 按 (piece.label, str(piece.size)) 查 N → ``spyrrow.Item(demand=N)``；
        - **demand=0 跳过该 piece（D2）**（该码该裁片不参与排料）；
        - piece 缺 label 或 quantities=None → demand=1（向后兼容旧 intermediate / 旧前端）。
    solver_opts = {exploration_pct?, quadtree_depth?, num_workers?} | None
        （US-006 spyrrow 求解旋钮透传，additive 白名单、未知键忽略）：
        - exploration_pct ∈ [0.1, 0.95]（越界 clamp、非数值忽略）：把 time_budget
          换算为 exploration_time / compression_time 两段 int 秒（**与
          total_computation_time 互斥**传入 spyrrow —— 两键同给 spyrrow 直接
          ValueError；不传时 spyrrow total 模式自动 80/20 分段 = 现行行为）；
        - quadtree_depth ∈ [3, 5]（缺省 4）；num_workers ≥ 1（缺省 4）。
        PC-006 消费方：CLI ``--solver-opts`` / ``--rotate-opts``（seed 间轮换去相关）；
        WS 协议本期不加字段（web 前端零改动）。
    exclude_labels = iterable[str] | None（US-011 腰头成带）：该 label 集合的裁片
        **只在 Item 构造层跳过**（不进 sparrow 实例），``pid_meta`` / ``total_area``
        / manifest 逐字段不变 —— band on/off 的 manifest 一致性即由此保证。
        **禁**用 quantities=0 达成同效：那会在 ``build_pid_meta`` 把 pid_meta /
        total_area / manifest 一起抹掉（密度口径事故，落地方案 §2.2）。
    exclude_pids = iterable[str] | None（US-003 起始端成套）：**pid 级** Item 层
        跳过（与 ``exclude_labels`` 同层、并存互不干扰）。prefix 只消耗资格码
        {(front,size),(back,size)} 两 pid 的 2+2 份 —— 同码其他码照排，故必须
        pid 级（label 级会把整码前后幅全丢，5336 其他码 10+ 份即密度崩）；
        同样禁 quantities=0 方式（口径事故同上）。
    extra_items = list[dict] | None（US-011）：构造期追加进 items 的补充 Item
        （JSON 可序列化 dict：``{id, polygon, demand=1, orientations}``）—— 成带
        组合片（WB_ pid）由此进主解。**必须构造期传入**：``instance.items`` 是
        spyrrow Rust 侧暴露的副本 list，构造后 append 不生效（实测验证）。

    每片实际 erode = min(申请值, MAX_OVERLAP_MM=10)（全局上限兜底，2026-08 起不再按片型）
    每片实际 tol  = min(申请值, MAX_ROTATION_TOL_DEG=45)

    求解约束带 strip_height = min(gate_mm, PLOT_SAFE_MAX_Y_MM)：gate_mm（门幅，
    如 1980）只是布幅**显示**口径（viewBox / 导出外框），排料压进绘图仪可写幅宽
    1910 才能完整打印（顶部 70mm 内部差）。密度分母同取 min(gate_mm, 1910)
    （实际幅宽口径，见 ``_apply_density_dual``）；导出外框 / 前端 viewBox 仍用 gate_mm。

    US-004 起裁片级流水线（sizes/demand/per_type/erode/pid_meta/total_area）委托
    ``build_pid_meta``（单一真相源，见其 docstring）；本函数补 spyrrow 侧构造：
    ``Item``（shape 用 pid_meta 的 erode 后 polygon、orientations 用同口径
    ``_resolve_d_tol`` 的 tol 离散化 —— 提取前后逐字段一致，对拍护栏见
    ``test_web_strategy.py``）。
    """
    import spyrrow
    pdef = {'d_ext': 0.0, 'd_int': 0.0, 'tol_ext': 0.0, 'tol_int': 0.0}
    if params:
        pdef.update(params)

    pid_meta, total_area, n_eroded = build_pid_meta(
        pieces, sizes=sizes, per_type=per_type, quantities=quantities, params=params)

    if sizes:
        want = {int(s) for s in sizes}
        pieces = [p for p in pieces if p['size'] in want]

    items = []
    exclude = {str(l) for l in exclude_labels} if exclude_labels else frozenset()
    # US-003：pid 级排除（与 label 级同层并存；语义见 docstring）。
    exclude_pid_set = {str(p) for p in exclude_pids} if exclude_pids else frozenset()
    for p in pieces:
        meta = pid_meta.get(p['pid'])
        if meta is None:
            continue   # demand=0 跳过 / 清洗后 <3 顶点（build_pid_meta 已滤）
        # US-011：band 成员只在 Item 层跳过（pid_meta/total_area/manifest 不动 ——
        # 组合片由 solve_worker 追加；quantities=0 移除是口径事故，见 docstring）。
        if p.get('label') in exclude:
            continue
        # US-003：prefix 资格码两 pid 同层跳过（2+2 由组合片 PS_ 承载）。
        if p['pid'] in exclude_pid_set:
            continue
        # tol 与 pid_meta 的 erode 同口径裁定（_resolve_d_tol 单一真相源）→ 离散角度集。
        _d, tol = _resolve_d_tol(p.get('label'), pdef, per_type)
        orientations = discretize_orientations(tol)
        items.append(spyrrow.Item(
            id=p['pid'],
            shape=[(float(x), float(y)) for x, y in meta['polygon']],
            demand=meta['demand'],
            allowed_orientations=orientations,
        ))
    # US-011：补充 Item（成带组合片等）必须**构造期**进 items —— instance.items 是
    # Rust 侧暴露的副本 list，构造后 append 不生效（实测验证，见 docstring）。
    for ex in (extra_items or []):
        items.append(spyrrow.Item(
            id=str(ex['id']),
            shape=[(float(x), float(y)) for x, y in ex['polygon']],
            demand=int(ex.get('demand', 1)),
            allowed_orientations=[float(a) for a in ex.get('orientations', (0.0,))],
        ))
    # 有效排料宽度：求解约束带 = min(门幅, 绘图仪可写幅宽)。门幅超出可写幅宽的部分
    # （1980−1910=70mm 内部差）求解时直接不排，marker 顶部不再落进行程外。
    gate_nest = min(float(gate_mm), PLOT_SAFE_MAX_Y_MM)
    instance = spyrrow.StripPackingInstance(
        name='workbench', strip_height=gate_nest, items=items)
    # US-006 求解旋钮：白名单清洗（越界 clamp / 非法忽略）后按需改写 config 构造。
    # 不传 solver_opts（或清洗后为空）时与旧版构造逐字段一致（total 模式 + 默认
    # quadtree_depth=4 + num_workers=4），无旗标冒烟零回归。
    opts = _normalize_solver_opts(solver_opts)
    total = int(time_budget)
    if 'exploration_pct' in opts:
        # 两段模式与 total_computation_time 互斥：spyrrow 的 total 键缺省 600（非
        # None），两段模式必须显式传 total_computation_time=None，否则触发
        # "not all 3 or some other combination" ValueError。
        expl, cmpr = _split_time_budget(total, opts['exploration_pct'])
        config = spyrrow.StripPackingConfig(
            total_computation_time=None,
            exploration_time=expl, compression_time=cmpr,
            seed=seed,
            quadtree_depth=opts.get('quadtree_depth', 4),
            num_workers=opts.get('num_workers', 4))
    else:
        config = spyrrow.StripPackingConfig(
            total_computation_time=total, seed=seed,
            quadtree_depth=opts.get('quadtree_depth', 4),
            num_workers=opts.get('num_workers', 4))
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


# --------------------------------------------------------------- US-025 进程版


# 限时 drain 累计上限（秒）：terminate() 后父进程做 cancel_join_thread + 限时 drain，
# 防止 multiprocessing.Queue 的 background feeder thread 阻塞 join（风险 R1）。
_POST_TERMINATE_DRAIN_MAX_SEC = 0.05
# process.join() 上限（秒）：spec 要求 terminate 后父进程 5s 内返回、无 hang。
_JOIN_TIMEOUT_SEC = 5.0


def solve_with_callback_proc(pieces_snapshot, gate_mm, solve_params, *,
                             on_manifest, on_report, on_process=None,
                             on_stage=None, drain_interval: float = 0.2,
                             band=None, prefix=None):
    """多进程版求解：spawn 子进程跑 ``build_instance + solve``，主进程 drain queue 分发。

    与旧 ``solve_with_callback``（threading 版）的关键区别：
      - **可终止**：返回 ``(process, final_data, elapsed, err)``，调用方持有 ``process``
        句柄可随时 ``terminate()``（OS 级回收，唯一可靠终止 spyrrow Rust solve 的方式）；
      - **build_instance 移入子进程**：spyrrow 对象不可 pickle，故**不在主进程**构造
        instance/config，子进程构造完后只把 JSON 可序列化的 manifest/frame/final/error
        投回 result_queue；
      - **density 双口径换算在主进程做**（关键不变量 #1）：``total_area`` 由 manifest
        数据带入主进程，``on_report`` 收到 frame 时按
        ``total_area/(width*min(gate_mm, PLOT_SAFE_MAX_Y_MM))`` 换算（实际幅宽口径，
        见 ``_apply_density_dual``）；``density_sparrow`` 保留 sparrow 自报口径。

    Parameters
    ----------
    pieces_snapshot : list[dict]
        intermediate 的 pieces 字段（纯 JSON；尚未构造 spyrrow 对象）。
    gate_mm : float
        门幅（mm）。同时用于 ``solve_worker`` 入参与 density 换算分母。
    solve_params : dict
        拆给 ``build_instance`` 的关键字参数（time_budget/seed/sizes/params/per_type/quantities）。
    on_manifest : callable(dict)
        收到 manifest 消息时回调（参数：manifest dict，含 ``pid_meta`` / ``total_area``
        / ``n_eroded`` / ``gate_mm``）。
    on_report : callable(dict)
        收到 frame 消息时回调（参数：frame dict，已做 density 双口径换算 ——
        ``density`` 为原面积口径、``density_sparrow`` 为 sparrow 自报）。
    on_process : callable(multiprocessing.Process) | None
        **US-026**：子进程 ``start()`` 后立即回调一次，把 ``Process`` 句柄交给调用方，
        让调用方可以在 solve 完成前调 ``terminate()``（WS stop / 客户端断开场景）。
        缺省 None（向后兼容旧调用方）。
    on_stage : callable(dict) | None
        **US-011**：收到 ``{kind:stage}`` 消息时回调（参数含 ``stage`` / ``fill_pct``
        / ``bbox`` / ``fallback`` / ``elapsed``）。band 开启时 worker 在 manifest 前
        投一次（带内聚排完成）；缺省 None = 丢弃（与旧版未知 kind 行为一致，
        CLI 调用方无 stage 消费方）。
    drain_interval : float
        主进程 drain result_queue 的轮询间隔（秒，默认 0.2）。
    band : dict | None
        **US-011**：腰头成带配置 ``{'label': str}``（routes_ws
        服务端校验后产物）。原样传给 ``solve_worker`` —— 带内聚排 + 组合片构造 +
        帧前展开都在 worker 进程内做（组合片 ``BandChunk`` 不跨进程）。缺省 None =
        关闭，worker 走原五元路径（manifest → frame* → final/error）。
    prefix : dict | None
        **US-003**：起始端成套配置 ``{'front': g码, 'back': g码}``（routes_ws
        ``_parse_prefix`` 服务端校验后产物，**无 size 键** —— 资格码在 worker
        进程内 seeded 随机选取）。原样传给 ``solve_worker``，构造/展开/final
        置换守卫都在 worker 进程内做（``BandChunk``/pin stats 不跨进程，工件
        经 ``prefix_runs`` 落盘）。缺省 None = 关闭。

    Returns
    -------
    (process, final_data, elapsed, err)
        - ``process``：``multiprocessing.Process`` 句柄（已 join，但调用方仍可查
          ``exitcode`` / 再次 ``terminate`` 兜底）；
        - ``final_data``：末态 dict（含 ``density`` / ``density_sparrow`` / ``width_mm``
          / ``elapsed`` / ``placed_items``）；异常或被终止时为 ``None``；
        - ``elapsed``：主进程 wall-clock 秒；
        - ``err``：错误消息字符串，无错误为 ``None``。子进程意外 crash（未投 error）
          时记为 ``'worker process exited unexpectedly (code=<exitcode>)'``。

    终止安全（防死锁）：finally 块必执行 —— 若子进程还活着则 ``terminate()``，然后
    ``result_queue.cancel_join_thread()`` + 限时 drain（≤50ms）+ ``join(timeout=5)``，
    绝不无限阻塞。
    """
    from .solve_worker import solve_worker   # 延迟 import：避免主进程 import solver 时强制拉 solve_worker

    result_queue: multiprocessing.Queue = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=solve_worker,
        args=(pieces_snapshot, gate_mm, solve_params, result_queue, band, prefix),
        name='solve_worker',
    )
    process.start()
    # US-026：把 process 句柄交给调用方（WS 层需要在 solve 完成前能 terminate）。
    if on_process is not None:
        try:
            on_process(process)
        except Exception:
            # on_process 回调失败不影响 solve（防御性，正常路径不触发）
            pass

    final_data: dict | None = None
    err: str | None = None
    total_area = 0.0
    gate = float(gate_mm)
    t0 = time.time()

    try:
        # 循环不变量：进程死了但 queue 还有数据时继续 drain（避免漏 manifest/frame/final）。
        # 仅当「进程死 AND queue 空」时退出。get(timeout=...) 在 timeout 到期且无数据时
        # 抛 queue.Empty —— 此时若进程还活着继续轮询，否则退出。
        while True:
            alive = process.is_alive()
            try:
                msg = result_queue.get(timeout=drain_interval if alive else 0.05)
            except _queue_mod.Empty:
                if not alive:
                    break
                continue

            kind = msg.get('kind')
            if kind == 'manifest':
                total_area = float(msg.get('total_area', 0.0))
                # gate_mm 以 manifest 为准（与子进程口径一致；缺省回退入参 gate_mm）。
                gate = float(msg.get('gate_mm', gate))
                on_manifest(msg)
            elif kind == 'frame':
                report = msg['report']
                _apply_density_dual(report, total_area, gate)
                on_report(report)
            elif kind == 'final':
                final = msg['final']
                _apply_density_dual(final, total_area, gate)
                final_data = final
                # final 后子进程会自然退出；继续 drain 残余 frame（如有）直到「进程死 + queue 空」。
            elif kind == 'error':
                err = msg.get('message', 'unknown error')
                # error 后子进程会自然退出；继续 drain 残余 frame（如有）直到「进程死 + queue 空」。
            elif kind == 'stage':
                # US-011 band / US-003 prefix 构造完成统计（manifest 前，各自唯一
                # 一次，band→prefix 序）；显式转发，无消费方（on_stage=None，CLI
                # 路径）时静默丢弃 = 旧行为。
                if on_stage is not None:
                    on_stage(msg)
            # 未知 kind 忽略（前向兼容）
    finally:
        # 防死锁清理（spec AC#4）：terminate → cancel_join_thread → 限时 drain → join
        # 无论正常退出还是异常（KeyboardInterrupt 等），必走此清理路径。
        if process.is_alive():
            process.terminate()
        # cancel_join_thread 让 queue 的 background feeder thread 不再 join，否则
        # 子进程被强杀时残留半写入数据可能让 join 永久阻塞。
        try:
            result_queue.cancel_join_thread()
        except Exception:
            pass
        # 限时 drain 残余（≤50ms）：drain 完 break，drain 不完也 break（不阻塞）。
        drain_t0 = time.time()
        while time.time() - drain_t0 < _POST_TERMINATE_DRAIN_MAX_SEC:
            try:
                result_queue.get_nowait()
            except _queue_mod.Empty:
                break
            except Exception:
                break
        # join 限时（spec：terminate 后 5s 内返回，无 hang）
        process.join(timeout=_JOIN_TIMEOUT_SEC)
        # 若 join 超时进程还活着 → 最后一次 kill 兜底（极端情况，正常路径不触发）。
        if process.is_alive():
            try:
                process.kill()
            except Exception:
                pass
            process.join(timeout=1.0)

    elapsed = time.time() - t0

    # 子进程意外 crash（未投 error 也没投 final）→ err 记录原因 + exitcode。
    # process.exitcode==0 表示正常退出但没投 final（理论上不可达，防御性记 unknown）。
    if err is None and final_data is None:
        code = process.exitcode
        if code is None:
            err = 'worker process did not complete (still alive)'
        elif code == 0:
            err = 'worker process exited without final or error'
        else:
            err = f'worker process exited unexpectedly (code={code})'

    return process, final_data, elapsed, err


def _apply_density_dual(report, total_area, gate_mm):
    """density 双口径换算（关键不变量 #1，主进程做，不在子进程做）。

    输入 ``report`` 的 ``density`` 为 sparrow 自报（erode 后面积口径）；本函数：
      - ``density_sparrow`` ← 原 sparrow 自报值；
      - ``density`` ← 原面积口径 ``total_area/(width*gate_den)``（90% 生死线口径），
        其中 ``gate_den = min(gate_mm, PLOT_SAFE_MAX_Y_MM)``（实际幅宽：求解约束带
        钳到 1910，2026-08-20 起密度分母同口径，钳制在函数内 = web/CLI 所有调用方
        自动一致；gate_mm ≤ 1910 时不放大，即用户门幅即实际幅宽）。
    """
    w = float(report.get('width_mm', 0.0))
    gate_den = min(float(gate_mm), PLOT_SAFE_MAX_Y_MM)
    report['density_sparrow'] = report['density']
    report['density'] = (total_area / (w * gate_den)) if w > 0 else 0.0
