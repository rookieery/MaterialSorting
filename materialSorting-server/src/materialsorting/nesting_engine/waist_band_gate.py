"""go/no-go 试点闸门（US-010）—— 组合片机制真实代价的三组决策实验。

在 UI/协议开发（US-011+）**之前**量化腰头成带（US-009 ``waist_band``）的真实
代价，复用 ``build_band_plan`` 等既有模块、**不改任何产品代码**。三组实验：

1. **密度 A/B**：5336 同配置（生产探针 P0 口径：120s 主解、per_type 全表、
   sizes 31~38、quantities 同 ``probe_base.json``）band off vs on × seed {0,1,2}，
   逐 seed ``real_density``（原面积口径 ``total_area/(width*min(gate,1910))``）
   对比表；**接受线 = on 的 seed 均值劣化 ≤1.0pt**。
2. **NFP 吞吐微基准**：主实例（band 成员移出后）含 ~500 顶点 comb 组合片 vs
   不含，同预算主解帧数/收敛曲线对比；**吞吐劣化 >30% 判不过**（不过 → US-011
   起用 pair-atomic 分块）。
3. **带内 fill-预算曲线**：band 预算 {5,10,15,30,60}s 的 fill_pct 序列，标注饱和
   点（fill 不随预算增长即停 → 推荐生产预算，对照初值 ``DEFAULT_BAND_TIME_BUDGET_S``）。

闸门结论三选一：``go``（两项全过）/ ``go-with-chunks``（仅 NFP 不过）/
``no-go``（密度不过 —— 已决策：直接转 US-015 v1.1 混填料路线，纯腰 v1 不合入）。

产物只落 ``out/config_runs/_probes/band_gate_report.json``（探针惯例），
**只读** ``out/sparrow_baseline/pieces_intermediate.json``，不写 web 事实源目录。

分层约束：本模块属 ``nesting_engine``，禁 import web/cli —— ``web.solver.build_
pid_meta`` 的裁片级流水线在此以**探针同构镜像**复刻（两 arm 共享同一镜像 =
同源同构对照；A/B 内部自洽，不跨口径对拍生产 0.9063 基线）。

用法::

    python -m materialsorting.nesting_engine.waist_band_gate [--quick]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .. import paths
from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
from .constraints import (
    MAX_OVERLAP_MM,
    MAX_ROTATION_TOL_DEG,
    discretize_orientations,
)
from .sparrow_baseline import _clean_polygon
from .sparrow_experiments import erode_polygon
from .waist_band import (
    COMPOSITE_ORIENTATIONS,
    DEFAULT_BAND_TIME_BUDGET_S,
    build_band_plan,
)

# ------------------------------------------------------------- 生产探针配置
# 5336 生产全集 P0 口径（与 out/config_runs/_probes/probe_base.json 同构；基线
# 87.45% / 7758.41mm / 119 片即由此复现）。band label = g05（5336 真腰：bbox
# 183×1161mm 弧形、demand 2×7 码 = 14 条、per_type {d:0.4, tol:3}、grain ±3° 锁定）。
MASTER_PREFIX = '5336'
BAND_LABEL = 'g05'
PROD_SIZES = (31, 32, 33, 34, 35, 36, 38)
_MAIN_QTY = {s: (1 if s == 31 else 3 if s == 36 else 2) for s in range(30, 41)}
PROD_PER_TYPE = {
    'g01': {'d': 5.0, 'tol': 8.0},
    'g02': {'d': 2.0, 'tol': 1.0},
    'g03': {'d': 2.0, 'tol': 1.0},
    'g04': {'d': 0.4, 'tol': 3.0},
    'g05': {'d': 0.4, 'tol': 3.0},    # <- 腰头（band label）
    'g06': {'d': 10.0, 'tol': 45.0},
    'g07': {'d': 10.0, 'tol': 15.0},
    'g08': {'d': 10.0, 'tol': 15.0},
    'g09': {'d': 0.4, 'tol': 30.0},
    'g10': {'d': 0.4, 'tol': 1.0},
}


def _prod_quantities() -> dict:
    """P0 quantities 深拷贝（g01~g05/g09/g10 双份表、g06~g08 单份表）。"""
    main = {str(k): v for k, v in _MAIN_QTY.items()}
    fill = {str(s): 1 for s in range(30, 41)}
    out = {}
    for g in ('g01', 'g02', 'g03', 'g04', 'g05', 'g09', 'g10'):
        out[g] = dict(main)
    for g in ('g06', 'g07', 'g08'):
        out[g] = dict(fill)
    return out


# ------------------------------------------------------------------- 闸门阈值
MAIN_SEEDS = (0, 1, 2)
MAIN_TIME_BUDGET_S = 120
BENCH_TIME_BUDGET_S = 60
BAND_BUDGETS_S = (5, 10, 15, 30, 60)
DENSITY_ACCEPT_PT = 1.0        # 实验① 接受线：on 的 seed 均值劣化 <=1.0pt
NFP_DEGRADE_ACCEPT_PCT = 30.0  # 实验② 判不过线：吞吐劣化 >30%
FILL_SATURATION_PT = 0.5       # 实验③ 饱和判据：fill 距序列最大值 <=0.5pt 即饱和
DEFAULT_REPORT_NAME = os.path.join('_probes', 'band_gate_report.json')


# ----------------------------------------------------------------- 装载与镜像
def load_gate_pieces(intermediate_path):
    """读 intermediate（**只读** web 事实源）；非 5336 母版 fail-fast。

    闸门结论只对 5336 生产配置负责（落地方案 §1.1 探针数字均为 5336），换母版
    重跑前须显式确认（--intermediate 指路仍要求 5336 前缀，防误用）。
    """
    with open(intermediate_path, encoding='utf-8') as f:
        doc = json.load(f)
    source = str(doc.get('source', ''))
    if not source.startswith(MASTER_PREFIX):
        raise RuntimeError(
            f'闸门实验绑定 {MASTER_PREFIX} 母版，当前 intermediate 源为 {source!r}'
            f'（先 commit 5336 母版，或核对 --intermediate 路径）')
    pieces = doc['pieces']
    return doc, pieces, float(doc['gate_mm']), {p['pid']: p for p in pieces}


def build_probe_pid_meta(pieces, *, sizes, per_type, quantities):
    """``web.solver.build_pid_meta`` 的探针同构镜像（分层禁 import web）。

    保留其关键语义：sizes 过滤 -> demand=quantities[label][str(size)]（缺 1、
    显 0 跳过且不计 total_area）-> per_type 覆盖 + 全局上限钳制 -> erode/清洗
    -> pid_meta + total_area=Σ(area×demand)。两 arm 共享同一镜像 = 同源同构；
    条目含 d/tol（Item 构造与 ``build_band_plan`` 的 d_g/tol_g 同源裁定）。
    """
    want = {int(s) for s in sizes}
    pid_meta: dict = {}
    total_area = 0.0
    for p in pieces:
        if p['size'] not in want:
            continue
        label = p.get('label')
        sk = 'null' if p['size'] is None else str(p['size'])
        if quantities and label is not None and label in quantities:
            size_map = quantities[label]
            size_map = size_map if isinstance(size_map, dict) else {}
            demand = int(size_map.get(sk, 0))
        else:
            demand = 1
        if demand <= 0:
            continue
        over = (per_type or {}).get(label) if label is not None else None
        d = float(over.get('d', 0.0)) if isinstance(over, dict) else 0.0
        tol = float(over.get('tol', 0.0)) if isinstance(over, dict) else 0.0
        d = min(d, MAX_OVERLAP_MM)
        tol = min(tol, MAX_ROTATION_TOL_DEG)
        poly = p['polygon']
        if d > 0:
            poly = erode_polygon(poly, d)
        poly = _clean_polygon(poly)
        if len(poly) < 3:
            continue
        pid_meta[p['pid']] = {
            'label': label, 'size': p['size'], 'demand': demand,
            'polygon': poly, 'area_mm2': p['area_mm2'], 'd': d, 'tol': tol,
        }
        total_area += float(p['area_mm2']) * demand
    return pid_meta, total_area


def main_items(pid_meta, *, exclude_label=None, composite=None):
    """主解 ``spyrrow.Item`` 列表（``build_instance`` 的探针镜像）。

    ``exclude_label`` 非空 = 该 label 成员只跳 Item 不动 pid_meta（US-011
    ``exclude_labels`` 同语义 —— 禁 quantities=0 的探针对齐）；``composite``
    （``BandChunk``）以 demand=1、orientations=[0,180]（FR-8 顺布纹）追加在
    **列表尾部**。每 arm 现构（spyrrow Item 不跨 solve 复用）。
    """
    import spyrrow

    items = []
    for pid, meta in pid_meta.items():
        if exclude_label is not None and meta.get('label') == exclude_label:
            continue
        items.append(spyrrow.Item(
            id=pid,
            shape=[(float(x), float(y)) for x, y in meta['polygon']],
            demand=int(meta['demand']),
            allowed_orientations=discretize_orientations(meta['tol']),
        ))
    if composite is not None:
        items.append(spyrrow.Item(
            id=composite.pid,
            shape=[(float(x), float(y)) for x, y in composite.polygon],
            demand=1,
            allowed_orientations=list(COMPOSITE_ORIENTATIONS),
        ))
    return items


def solve_collect(items, *, name, strip_height, seed, time_budget,
                  num_workers=4, drain_interval=0.2):
    """跑一次主解并采集帧轨迹（``solve_with_progress`` 探针变体）。

    差异：求解异常入档不炸整闸门；帧记录 (elapsed, density_sparrow, width_mm)
    供吞吐计数与收敛曲线。返回 dict：``ok`` / ``error`` / ``n_frames`` /
    ``elapsed_s`` / ``final_*`` / ``frames``。
    """
    import spyrrow

    instance = spyrrow.StripPackingInstance(
        name=name, strip_height=float(strip_height), items=items)
    config = spyrrow.StripPackingConfig(
        total_computation_time=int(time_budget), seed=int(seed),
        quadtree_depth=4, num_workers=int(num_workers))
    queue = spyrrow.ProgressQueue()
    holder: dict = {}
    t0 = time.time()

    def _solve():
        try:
            holder['sol'] = instance.solve(config, progress=queue)
        except Exception as exc:             # noqa: BLE001 探针需扛求解异常入报告
            holder['err'] = exc

    th = threading.Thread(target=_solve, daemon=True)
    th.start()
    frames: list = []

    def _drain():
        for _rtype, sol in queue.drain():
            frames.append({'elapsed': round(time.time() - t0, 2),
                           'density': float(sol.density),
                           'width_mm': float(sol.width)})

    while th.is_alive():
        _drain()
        time.sleep(drain_interval)
    th.join()
    _drain()
    elapsed = time.time() - t0
    base = {'n_frames': len(frames), 'elapsed_s': round(elapsed, 2)}
    err = holder.get('err')
    if err is not None:
        return {**base, 'ok': False, 'error': f'{type(err).__name__}: {err}'}
    sol = holder.get('sol')
    if sol is None:
        return {**base, 'ok': False, 'error': 'solver returned no solution'}
    return {**base, 'ok': True,
            'final_density_sparrow': float(sol.density),
            'final_width_mm': float(sol.width),
            'frames': frames}


def _real_density_pct(total_area, width_mm, gate_den) -> float:
    """原面积口径密度（%）：total_area/(width*min(gate,1910))，生死线同口径。"""
    if width_mm <= 0:
        return 0.0
    return total_area / (width_mm * gate_den) * 100.0


# ------------------------------------------------------------------- 实验编排
def run_density_ab(pid_meta, pieces_by_id, *, label, d_g, tol_g, seeds,
                   main_time, band_budget, gate_nest, gate_den, total_area,
                   log=print):
    """实验①：密度 A/B —— band off vs on × seeds，逐 seed real_density 对比表。

    on arm = 带内聚排（``band_budget`` 秒，wall-clock 另计）-> 成员移出主实例 +
    组合片（demand=1）。主解预算两 arm 同为 ``main_time``（band 预算是独立阶段，
    生产编排同样叠加，见 US-011 stage）。
    """
    rows: list = []
    off_vals: list = []
    on_vals: list = []
    log(f'-- 实验① 密度 A/B：main {main_time}s × seeds {list(seeds)}，'
        f'band {band_budget}s，label={label}（d={d_g}, tol={tol_g}）')
    for seed in seeds:
        off = solve_collect(
            main_items(pid_meta), name=f'gate_ab_off_s{seed}',
            strip_height=gate_nest, seed=seed, time_budget=main_time)
        off_pct = (_real_density_pct(total_area, off['final_width_mm'], gate_den)
                   if off['ok'] else None)
        row = {'seed': seed,
               'off': ({'density_pct': round(off_pct, 3),
                        'width_mm': off['final_width_mm'],
                        'n_frames': off['n_frames']} if off['ok']
                       else {'error': off['error']}),
               'on': None}
        if off['ok']:
            off_vals.append(off_pct)
        # on：带内聚排（fail-fast 异常入档 -> 实验① 判不过）
        try:
            t_band = time.time()
            chunk = build_band_plan(
                pid_meta, pieces_by_id, label=label, seed=seed,
                gate_nest=gate_nest, d_g=d_g, tol_g=tol_g,
                time_budget=band_budget)
            band_elapsed = round(time.time() - t_band, 2)
        except Exception as exc:             # noqa: BLE001 入报告
            row['on'] = {'error': f'{type(exc).__name__}: {exc}'}
            rows.append(row)
            log(f'   seed {seed}: off={off_pct and round(off_pct, 3)}% | '
                f'on=BAND 构建失败（{type(exc).__name__}）')
            continue
        on = solve_collect(
            main_items(pid_meta, exclude_label=label, composite=chunk),
            name=f'gate_ab_on_s{seed}',
            strip_height=gate_nest, seed=seed, time_budget=main_time)
        if on['ok']:
            on_pct = _real_density_pct(total_area, on['final_width_mm'], gate_den)
            on_vals.append(on_pct)
            row['on'] = {'density_pct': round(on_pct, 3),
                         'width_mm': on['final_width_mm'],
                         'n_frames': on['n_frames'],
                         'band': {'fill_pct': round(chunk.fill_pct, 2),
                                  'bbox': chunk.bbox,
                                  'n_members': chunk.n_members,
                                  'n_verts': len(chunk.polygon),
                                  'band_elapsed_s': band_elapsed}}
            deg = off_pct - on_pct if off_pct is not None else None
            row['deg_pt'] = None if deg is None else round(deg, 3)
            log(f'   seed {seed}: off={off_pct:.3f}% | on={on_pct:.3f}% | '
                f'劣化 {deg:.2f}pt（band fill {chunk.fill_pct:.1f}%，'
                f'{band_elapsed}s）')
        else:
            row['on'] = {'error': on['error'],
                         'band': {'band_elapsed_s': band_elapsed}}
            log(f'   seed {seed}: off={off_pct and round(off_pct, 3)}% | '
                f'on=主解失败（{on["error"]}）')
        rows.append(row)

    mean_off = statistics.mean(off_vals) if off_vals else None
    mean_on = statistics.mean(on_vals) if on_vals else None
    ok_seeds = len(off_vals) == len(seeds) and len(on_vals) == len(seeds)
    mean_deg = (mean_off - mean_on) if ok_seeds else None
    passed = ok_seeds and mean_deg <= DENSITY_ACCEPT_PT
    return {
        'per_seed': rows,
        'off_mean_pct': None if mean_off is None else round(mean_off, 3),
        'on_mean_pct': None if mean_on is None else round(mean_on, 3),
        'mean_deg_pt': None if mean_deg is None else round(mean_deg, 3),
        'accept_pt': DENSITY_ACCEPT_PT,
        'pass': passed,
    }


def _base_item_copies(pid_meta, exclude_label) -> int:
    """基实例副本计数（Σdemand，排除 band 成员 label）—— 报告口径用。"""
    return sum(int(m['demand']) for m in pid_meta.values()
               if m.get('label') != exclude_label)


def _downsample(frames, cap=200):
    """收敛曲线降采样（<=cap 点，保尾点）—— 报告可读性，不参与判据。"""
    if len(frames) <= cap:
        return frames
    step = (len(frames) - 1) / (cap - 1)
    idx = sorted({int(i * step) for i in range(cap)} | {len(frames) - 1})
    return [frames[i] for i in idx]


def run_nfp_bench(pid_meta, composite, *, label, seed, bench_time, gate_nest,
                  log=print):
    """实验②：NFP 吞吐微基准 —— 主实例（band 成员移出）± comb 组合片同预算对跑。

    对照口径：两 arm 共享同一「成员移出后」基实例，唯一差异 = ~500 顶点 comb
    Item 是否在场（隔离组合片 NFP 的边际代价，不混入成员移出效应）。判据 =
    帧吞吐（帧/秒）劣化 <=30%；收敛曲线（帧密度轨迹）随报告落盘备查。
    """
    log(f'-- 实验② NFP 吞吐微基准：{bench_time}s，seed {seed}，'
        f'comb {len(composite.polygon)} 顶点')
    without = solve_collect(
        main_items(pid_meta, exclude_label=label), name='gate_nfp_without',
        strip_height=gate_nest, seed=seed, time_budget=bench_time)
    with_cmp = solve_collect(
        main_items(pid_meta, exclude_label=label, composite=composite),
        name='gate_nfp_with', strip_height=gate_nest, seed=seed,
        time_budget=bench_time)
    if not (without['ok'] and with_cmp['ok']):
        return {'pass': False,
                'error': f"without={without.get('error')} | "
                         f"with={with_cmp.get('error')}"}
    fps_wo = without['n_frames'] / without['elapsed_s']
    fps_wi = with_cmp['n_frames'] / with_cmp['elapsed_s']
    degrade = (1.0 - fps_wi / fps_wo) * 100.0
    passed = degrade <= NFP_DEGRADE_ACCEPT_PCT
    n_base = _base_item_copies(pid_meta, label)
    log(f'   不含: {without["n_frames"]} 帧 / {without["elapsed_s"]}s = '
        f'{fps_wo:.2f} 帧/s')
    log(f'   含  : {with_cmp["n_frames"]} 帧 / {with_cmp["elapsed_s"]}s = '
        f'{fps_wi:.2f} 帧/s')
    log(f'   吞吐劣化 {degrade:.1f}% -> {"PASS" if passed else "FAIL"}'
        f'（<= {NFP_DEGRADE_ACCEPT_PCT:.0f}%）')
    return {
        'budget_s': bench_time,
        'seed': seed,
        'without': {'n_item_copies': n_base,
                    'n_frames': without['n_frames'],
                    'elapsed_s': without['elapsed_s'],
                    'frames_per_sec': round(fps_wo, 3),
                    'final_density_sparrow': without['final_density_sparrow'],
                    'curve': _downsample(without['frames'])},
        'with': {'n_item_copies': n_base + 1,
                 'composite_verts': len(composite.polygon),
                 'composite_bbox': composite.bbox,
                 'n_frames': with_cmp['n_frames'],
                 'elapsed_s': with_cmp['elapsed_s'],
                 'frames_per_sec': round(fps_wi, 3),
                 'final_density_sparrow': with_cmp['final_density_sparrow'],
                 'curve': _downsample(with_cmp['frames'])},
        'throughput_degrade_pct': round(degrade, 2),
        'accept_pct': NFP_DEGRADE_ACCEPT_PCT,
        'pass': passed,
    }


def run_fill_curve(pid_meta, pieces_by_id, *, label, d_g, tol_g, seed,
                   budgets, gate_nest, log=print):
    """实验③：带内 fill-预算曲线 —— 预算扫描 + 饱和点标注（推荐生产预算）。"""
    log(f'-- 实验③ 带内 fill-预算曲线：budgets {list(budgets)}s，seed {seed}')
    points: list = []
    for budget in budgets:
        try:
            chunk = build_band_plan(
                pid_meta, pieces_by_id, label=label, seed=seed,
                gate_nest=gate_nest, d_g=d_g, tol_g=tol_g, time_budget=budget)
            points.append({'budget_s': budget,
                           'fill_pct': round(chunk.fill_pct, 2),
                           'bbox': chunk.bbox,
                           'n_members': chunk.n_members,
                           'n_verts': len(chunk.polygon)})
            log(f'   {budget:>2}s -> fill {chunk.fill_pct:5.2f}% | '
                f'bbox {chunk.bbox["width_mm"]:.0f}'
                f'x{chunk.bbox["height_mm"]:.0f}mm'
                f' | {len(chunk.polygon)} 顶点')
        except Exception as exc:             # noqa: BLE001 入报告
            points.append({'budget_s': budget,
                           'error': f'{type(exc).__name__}: {exc}'})
            log(f'   {budget:>2}s -> 构建失败（{type(exc).__name__}）')
    sat_budget, note = fill_saturation(points)
    if sat_budget is not None:
        log(f'   饱和点 {sat_budget}s（推荐生产预算；初值 '
            f'{DEFAULT_BAND_TIME_BUDGET_S}s）{note}')
    return {'points': points,
            'saturation_budget_s': sat_budget,
            'recommended_budget_s': sat_budget,
            'default_budget_s': DEFAULT_BAND_TIME_BUDGET_S,
            'note': note}


def fill_saturation(points):
    """fill 曲线饱和点：距序列最大 fill <= ``FILL_SATURATION_PT`` 的最小预算。

    返回 ``(budget|None, note)``。全部点失败 -> (None, 错误注记)；最大 fill 恰在
    最大预算处取得（未观测到平台）-> 该预算 + 未饱和注记（继续加预算可能仍有
    收益，生产预算按需上调）。
    """
    ok = [p for p in points if 'fill_pct' in p]
    if not ok:
        return None, '全部预算构建失败，无饱和点可标'
    max_fill = max(p['fill_pct'] for p in ok)
    sat = min(p['budget_s'] for p in ok
              if p['fill_pct'] >= max_fill - FILL_SATURATION_PT)
    max_budget = max(p['budget_s'] for p in ok)
    best_points = [p for p in ok if p['fill_pct'] == max_fill]
    if best_points and best_points[0]['budget_s'] >= max_budget:
        return sat, ('（未观测到饱和平台：最大 fill 在最大预算处取得，'
                     '生产预算可按需上调）')
    return sat, ''


def decide(density_pass, nfp_pass) -> tuple:
    """闸门结论三选一：go / go-with-chunks / no-go（密度是硬闸门）。"""
    if density_pass and nfp_pass:
        return 'go', ('密度 A/B 与 NFP 微基准双过线：纯腰组合片 v1 可合入'
                      '（US-011 起后端接线）')
    if density_pass:
        return 'go-with-chunks', ('NFP 吞吐劣化超线：US-011 起用 pair-atomic '
                                  '分块（块边界永不切开同码对）')
    return 'no-go', ('密度 A/B 劣化超线（或 band 构建/主解失败）：纯腰 v1 不合入，'
                     '直接转 US-015 v1.1 混填料路线')


# ---------------------------------------------------------------------- CLI
def _parse_ints(text):
    return tuple(int(x) for x in str(text).split(',') if x.strip())


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description='US-010 go/no-go 试点闸门（三组决策实验，'
                    '报告落 out/config_runs/_probes/band_gate_report.json）')
    ap.add_argument('--intermediate', default=paths.INTERMEDIATE,
                    help='pieces_intermediate.json 路径（只读；须为 5336 母版）')
    ap.add_argument('--label', default=BAND_LABEL, help='band g 码（默认 g05）')
    ap.add_argument('--seeds', default=','.join(str(s) for s in MAIN_SEEDS),
                    help='实验① seed 列表（逗号分隔，默认 0,1,2）')
    ap.add_argument('--main-time', type=int, default=MAIN_TIME_BUDGET_S,
                    help='实验① 主解预算秒（默认 120）')
    ap.add_argument('--band-budget', type=int,
                    default=DEFAULT_BAND_TIME_BUDGET_S,
                    help='实验①/② 带内构建预算秒（默认 15）')
    ap.add_argument('--bench-time', type=int, default=BENCH_TIME_BUDGET_S,
                    help='实验② 吞吐基准预算秒（默认 60）')
    ap.add_argument('--band-budgets',
                    default=','.join(str(b) for b in BAND_BUDGETS_S),
                    help='实验③ 预算扫描列表（默认 5,10,15,30,60）')
    ap.add_argument('--report',
                    default=os.path.join(paths.CONFIG_RUNS_DIR,
                                         DEFAULT_REPORT_NAME),
                    help='报告输出路径（默认 out/config_runs/_probes/'
                         'band_gate_report.json）')
    ap.add_argument('--quick', action='store_true',
                    help='冒烟档：预算全缩到秒级（只验证管线跑通，结论无意义）')
    args = ap.parse_args(argv)

    seeds = (0,) if args.quick else _parse_ints(args.seeds)
    main_time = 8 if args.quick else args.main_time
    band_budget = 3 if args.quick else args.band_budget
    bench_time = 8 if args.quick else args.bench_time
    band_budgets = (1, 2, 4) if args.quick else _parse_ints(args.band_budgets)
    if args.label not in PROD_PER_TYPE:
        ap.error(f'--label {args.label} 不在生产 per_type 表内')
    d_g = PROD_PER_TYPE[args.label]['d']
    tol_g = PROD_PER_TYPE[args.label]['tol']

    doc, pieces, gate_mm, pieces_by_id = load_gate_pieces(args.intermediate)
    gate_den = min(gate_mm, PLOT_SAFE_MAX_Y_MM)
    pid_meta, total_area = build_probe_pid_meta(
        pieces, sizes=PROD_SIZES, per_type=PROD_PER_TYPE,
        quantities=_prod_quantities())
    n_items = sum(int(m['demand']) for m in pid_meta.values())
    band_demand = sum(int(m['demand']) for m in pid_meta.values()
                      if m.get('label') == args.label)
    log = print
    log('== US-010 go/no-go 试点闸门 ==')
    log(f'   母版 {doc["source"]} | gate {gate_mm:.0f}mm'
        f'（密度分母 {gate_den:.0f}mm） | {n_items} 副本'
        f' / total_area {total_area/1e6:.3f} m²')
    log(f'   band {args.label}: {band_demand} 副本，d={d_g} tol={tol_g}'
        + ('（quick 冒烟档）' if args.quick else ''))

    # ---- 实验①：密度 A/B ---------------------------------------------------
    density_ab = run_density_ab(
        pid_meta, pieces_by_id, label=args.label, d_g=d_g, tol_g=tol_g,
        seeds=seeds, main_time=main_time, band_budget=band_budget,
        gate_nest=gate_den, gate_den=gate_den, total_area=total_area, log=log)
    log(f'   均值 off={density_ab["off_mean_pct"]}% '
        f'on={density_ab["on_mean_pct"]}% | 劣化 {density_ab["mean_deg_pt"]}pt'
        f' -> {"PASS" if density_ab["pass"] else "FAIL"}'
        f'（<= {DENSITY_ACCEPT_PT}pt）')

    # ---- 实验②：NFP 吞吐微基准（组合片同 seed 同预算确定性重建）-----------
    try:
        t_band = time.time()
        composite = build_band_plan(
            pid_meta, pieces_by_id, label=args.label, seed=seeds[0],
            gate_nest=gate_den, d_g=d_g, tol_g=tol_g, time_budget=band_budget)
        log(f'   （实验② 组合片重建：seed {seeds[0]}，'
            f'{round(time.time() - t_band, 1)}s，{len(composite.polygon)} 顶点）')
        nfp = run_nfp_bench(
            pid_meta, composite, label=args.label, seed=seeds[0],
            bench_time=bench_time, gate_nest=gate_den, log=log)
    except Exception as exc:                 # noqa: BLE001 入报告
        nfp = {'pass': False, 'error': f'{type(exc).__name__}: {exc}'}
        log(f'   实验② 失败：{nfp["error"]}')

    # ---- 实验③：带内 fill-预算曲线 -----------------------------------------
    fill_curve = run_fill_curve(
        pid_meta, pieces_by_id, label=args.label, d_g=d_g, tol_g=tol_g,
        seed=seeds[0], budgets=band_budgets, gate_nest=gate_den, log=log)

    # ---- 结论 + 报告落盘 ---------------------------------------------------
    conclusion, reason = decide(density_ab['pass'], nfp['pass'])
    report = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'quick_smoke': bool(args.quick),
        'master_source': doc['source'],
        'intermediate': str(args.intermediate),
        'gate_den_mm': gate_den,
        'config': {
            'label': args.label, 'd_g': d_g, 'tol_g': tol_g,
            'sizes': list(PROD_SIZES), 'per_type': PROD_PER_TYPE,
            'quantities': _prod_quantities(),
            'main_time_s': main_time, 'band_build_budget_s': band_budget,
            'bench_time_s': bench_time, 'seeds': list(seeds),
            'band_budgets_s': list(band_budgets),
            'n_items_total': n_items, 'band_demand': band_demand,
            'total_area_mm2': round(total_area, 1),
        },
        'density_ab': density_ab,
        'nfp_bench': nfp,
        'fill_curve': fill_curve,
        'conclusion': conclusion,
        'conclusion_reason': reason,
    }
    out_path = Path(args.report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log(f'== 闸门结论: {conclusion} ==')
    log(f'   {reason}')
    log(f'   报告 -> {out_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
