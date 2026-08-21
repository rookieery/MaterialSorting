"""US-014 腰头成带 A/B 验收闭环 —— 同源同构终验 + 形态判据 + 导出验证。

跑批口径（与生产 0.9063 基线**不同构**，只与同配置 off 对照）：
  - **uploads 源**：intermediate 由 web 上传 commit 产生（5336 母版）；
  - **g05 d=0.0**：web 工作台默认口径（params 全 0 + per_type=None —— 版师开 band
    不配 per-type 时即此配置，与前端 ``collectParams`` DEFAULT_FORM 逐字段一致）；
  - **无 kill**：单 seed 全预算跑完（生产基线为 --kill portfolio 跑法）。

四项判据（tasks/prd-waist-band.md US-014）：
  1. 密度 A/B：off vs on × seed {0,1,2}，``real_density`` 均值劣化 <=1.0pt；
  2. 形态：同码成对相邻率（同 pid 副本最近邻**边距** <= eps，与朝向无关 —— PRD
     中心距公式为同朝向并排特例，FR-8 头尾翻转 180° 成对只有边距口径能正确判定，
     见 ``pair_adjacency`` docstring）=100% + 带 span <= 带 bbox+slack（构造性
     不变量：``expand_placements`` 是刚性变换，超限即展开式回归）；off 臂 g05
     成对率作对照参考（不带不成对的实证）；
  3. 确定性：同 seed 重跑 placed_items/density 序列**逐帧相等**（忽略 wall-clock
     elapsed；截止快照尾帧感知 —— 主解按 wall-clock 截断，轨迹确定但截断点漂移
     1~3 帧，见 ``frame_series_equal``）+ band_runs 工件可回放对拍（两次 run 的
     ``BandChunk`` JSON 相等，排除 ``band_elapsed``）；
  4. 导出：PNG/R12-DXF/PLT 三格式成功 + logging 无「导出跳过：pid」（WB_ 泄漏
     哨兵，``export_geometry.placed_to_world``）+ DXF/PLT 字节无 ``b'WB_'``；off
     臂同管线导出成功（band 关闭路径与 HEAD 行为一致的产品级证据）。

产物：报告 JSON + 三格式导出 -> ``out/config_runs/_probes/``（探针惯例，只读 web
事实源 ``pieces_intermediate.json``；band_runs 工件仍由 worker 落 ``OUT_DIR``
产品位置）。分层：本模块属 ``web``（须消费 ``solver``/``export`` 真实产品管线，
非 ``waist_band_gate`` 的探针镜像），不进 ``server`` 路由（零副作用）。

用法::

    python -m materialsorting.web.band_accept [--quick]   # quick=秒级冒烟，结论无意义
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from .. import paths
from ..nesting_engine.waist_band import DEFAULT_BAND_TIME_BUDGET_S, PAIR_ADJ_EPS_MM
from shapely.geometry import Polygon
from .export import (
    apply_transform,
    placed_to_world,
    render_png,
    write_marker_dxf,
    write_marker_plt,
)
from .solver import solve_with_callback_proc

# ---------------------------------------------------------------- 跑批口径
# 5336 生产需求表 P0 镜像（与 waist_band_gate 生产探针同构，码表收窄到 ACCEPT_SIZES）：
# g05 七码中 31->1、36->3、其余->2 => 14 副本（成对判据有分母）；其余 g 码沿用生产
# 双份/单份表，实例规模 ~119 副本与生产同量级。
MASTER_PREFIX = '5336'
BAND_LABEL = 'g05'
AB_SEEDS = (0, 1, 2)
MAIN_TIME_S = 120
ACCEPT_SIZES = (31, 32, 33, 34, 35, 36, 38)
_MAIN_QTY = {31: 1, 32: 2, 33: 2, 34: 2, 35: 2, 36: 3, 38: 2}

# ---------------------------------------------------------------- 判据阈值
DENSITY_ACCEPT_PT = 1.0   # 判据①：on 的 seed 均值劣化 <=1.0pt（PRD 验收线）
PAIR_EPS_MM = PAIR_ADJ_EPS_MM   # 成对相邻边距 eps（单一真相源 waist_band —— 块内
                                # 构造性检查与验收同口径；吸收 spyrrow 贴排缝隙）
SPAN_SLACK_MM = 2.0       # 带 span 对 stage bbox 的浮点/对齐余量（刚性展开不变量）
FRAME_TAIL_TOLERANCE = 8  # 确定性帧列尾差容差：wall-clock 截断快照漂移（实测 1~3）
                          # 帧级上限，超此即非截断抖动（见 frame_series_equal）
DEFAULT_REPORT_NAME = os.path.join('_probes', 'band_accept_report.json')
EXPORT_STEM = 'band_accept_export'


def accept_quantities() -> dict:
    """P0 需求表镜像：g01~g05/g09/g10 双份表、g06~g08 单份表（US-022 结构）。"""
    main = {str(k): v for k, v in _MAIN_QTY.items()}
    out = {}
    for g in ('g01', 'g02', 'g03', 'g04', 'g05', 'g09', 'g10'):
        out[g] = dict(main)
    for g in ('g06', 'g07', 'g08'):
        out[g] = {sk: 1 for sk in main}
    return out


def web_default_params() -> dict:
    """web 工作台默认 params（前端 collectParams 不变量：恒全 0）—— g05 d=0.0 由此。"""
    return {'d_ext': 0.0, 'd_int': 0.0, 'tol_ext': 0.0, 'tol_int': 0.0}


def load_accept_pieces(intermediate_path):
    """读 intermediate（只读 web 事实源）；非 5336 母版 fail-fast（终验绑定 5336）。"""
    with open(intermediate_path, encoding='utf-8') as f:
        doc = json.load(f)
    source = str(doc.get('source', ''))
    if not source.startswith(MASTER_PREFIX):
        raise RuntimeError(
            f'US-014 终验绑定 {MASTER_PREFIX} 母版，当前 intermediate 源为 {source!r}'
            f'（先经 web 上传 commit，或核对 --intermediate 路径）')
    return doc, doc['pieces'], float(doc['gate_mm']), {p['pid']: p for p in doc['pieces']}


# ---------------------------------------------------------------- 单臂求解
def run_arm(pieces, gate_mm, solve_params, band=None):
    """跑一臂（真实产品管线 ``solve_with_callback_proc``，与 WS 路径同一代码）。

    返回 ``{'ok','error','stage','manifest','frames','final'}``；frames 保留逐帧
    ``density/width_mm/placed_items``（确定性判据输入），final 为 worker 末态
    （density 已由主进程换算为原面积口径）。
    """
    stage = manifest = final = None
    frames: list = []

    def on_manifest(m):
        nonlocal manifest
        manifest = m

    def on_report(r):
        frames.append(r)

    def on_stage(m):
        nonlocal stage
        stage = m

    _proc, final_data, _elapsed, err = solve_with_callback_proc(
        [dict(p) for p in pieces], float(gate_mm), dict(solve_params),
        on_manifest=on_manifest, on_report=on_report, on_stage=on_stage, band=band)
    return {'ok': err is None and final_data is not None, 'error': err,
            'stage': stage, 'manifest': manifest, 'frames': frames, 'final': final_data}


# ---------------------------------------------------------------- 形态判据
def _placement_bbox(polygon, rotation, translation):
    """原始轮廓 -> 放置后世界 bbox (minx, miny, maxx, maxy)。"""
    pts = apply_transform(polygon, float(rotation), translation)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def pair_adjacency(placements, pieces_by_id, *, label=None, eps_mm=PAIR_EPS_MM):
    """同码成对相邻率（US-014 判据②）—— 边距口径（与朝向无关）。

    对每个副本数 >=2 的 pid：逐副本找同 pid 最近邻，**放置足迹最近边距**
    （shapely ``distance``）<= eps 判相邻。PRD 公式「中心距 <= (w_i+w_j)/2+ε」是
    同朝向并排的对轴特例（该情形下 中心距 − w == 边距，两口径等价）；对 FR-8
    头尾翻转 180° 成对（腰头行业形态，g05 L/w≈6 长片），中心连线沿长边、中心距
    可达 L 量级而物理边距 ~0（US-014 实测 g05_34 对：边距 1.5mm / 中心距 713mm）
    —— 中心距口径会把物理相邻的成对误判散落，故以边距为权威、中心距仅随报告
    输出供对照。rate = 相邻副本数 / 多副本 pid 副本总数；无多副本 pid 时
    rate=None（判据无分母，pass=False 不误报）。``label`` 给定时只统计该 g 码
    （带成员）；缺省全表（off 臂对照参考）。
    """
    groups: dict = {}
    skipped = 0
    for it in placements:
        pid = str(it.get('id'))
        p = pieces_by_id.get(pid)
        if p is None:
            skipped += 1
            continue
        if label is not None and p.get('label') != label:
            continue
        pts = apply_transform(
            p['polygon'], float(it.get('rotation', 0.0)),
            it.get('translation', [0.0, 0.0]))
        g = Polygon(pts)
        if not g.is_valid:
            g = g.buffer(0)
        if g.geom_type != 'Polygon':
            g = g.convex_hull
        groups.setdefault(pid, []).append(g)
    n_total = n_adj = 0
    worst_gap = None
    worst_center = None
    for copies in groups.values():
        if len(copies) < 2:
            continue
        centers = [(c.centroid.x, c.centroid.y) for c in copies]
        for i, a in enumerate(copies):
            min_edge = min(
                a.distance(b) for j, b in enumerate(copies) if j != i)
            if min_edge <= eps_mm:
                n_adj += 1
            if worst_gap is None or min_edge > worst_gap:
                worst_gap = min_edge
            cd = max(
                math.hypot(centers[i][0] - centers[j][0],
                           centers[i][1] - centers[j][1])
                for j in range(len(copies)) if j != i)
            if worst_center is None or cd > worst_center:
                worst_center = cd
            n_total += 1
    return {
        'rate_pct': None if n_total == 0 else round(100.0 * n_adj / n_total, 2),
        'n_copies': n_total,
        'n_adjacent': n_adj,
        'worst_gap_mm': None if worst_gap is None else round(worst_gap, 2),
        'worst_center_mm': None if worst_center is None else round(worst_center, 2),
        'n_unknown_pid': skipped,
        'pass': bool(n_total > 0 and n_adj == n_total),
    }


def band_span(placements, pieces_by_id, label):
    """带成员（该 label 全部副本）放置后世界 bbox —— 带 span（判据②散落检查）。"""
    minx = miny = math.inf
    maxx = maxy = -math.inf
    n = 0
    for it in placements:
        p = pieces_by_id.get(str(it.get('id')))
        if p is None or p.get('label') != label:
            continue
        x0, y0, x1, y1 = _placement_bbox(
            p['polygon'], it.get('rotation', 0.0), it.get('translation', [0.0, 0.0]))
        minx, miny = min(minx, x0), min(miny, y0)
        maxx, maxy = max(maxx, x1), max(maxy, y1)
        n += 1
    if n == 0:
        return None
    return {'width_mm': round(maxx - minx, 2), 'height_mm': round(maxy - miny, 2),
            'n_members': n}


def span_ok(span, stage_bbox, slack_mm=SPAN_SLACK_MM):
    """带 span <= stage bbox + slack（刚性展开构造性不变量；超限=展开式回归）。"""
    if span is None or stage_bbox is None:
        return False
    return (span['width_mm'] <= float(stage_bbox['width_mm']) + slack_mm
            and span['height_mm'] <= float(stage_bbox['height_mm']) + slack_mm)


# ---------------------------------------------------------------- 确定性判据
def frame_signature(frames):
    """逐帧签名（density/width_mm/placed_items）—— 忽略 wall-clock ``elapsed``。"""
    return [(round(float(f['density']), 9), round(float(f['width_mm']), 6),
             f['placed_items']) for f in frames]


def frame_series_equal(frames_a, frames_b):
    """两次 run 的帧序列「逐帧相等」判定（US-014 判据③，wall-clock 截断感知）。

    主解按 wall-clock 预算截断：改进轨迹/迭代确定（同 seed 逐帧内容一致），但
    **截止时刻的最后一帧**是截止快照 —— 截断点落在哪个迭代由机器时刻决定，两跑
    可差 1~3 帧、且短者末帧与长者同位帧不同（US-014 实测 120s×2：2005/2008 帧
    prefix 全等仅尾 3 帧漂移、final 相等；30s×2：1167/1166 首 divergence=末帧）。
    PRD 口径「非 byte-identity —— 帧嵌 wall-clock elapsed」涵盖此类泄漏。判定：
    两者前 ``min(n)-1`` 帧逐帧相等（核心轨迹）+ 帧数差 <= ``FRAME_TAIL_TOLERANCE``
    （防大面积漂移冒充截断抖动）。
    """
    n = min(len(frames_a), len(frames_b))
    core_equal = frames_a[:max(0, n - 1)] == frames_b[:max(0, n - 1)]
    tail_ok = abs(len(frames_a) - len(frames_b)) <= FRAME_TAIL_TOLERANCE
    return bool(core_equal and tail_ok)


def final_signature(final):
    """末态签名（density/width_mm/placed_items）—— 忽略 ``elapsed``。"""
    if final is None:
        return None
    return (round(float(final['density']), 9), round(float(final['width_mm']), 6),
            final['placed_items'])


def _band_runs_dir() -> Path:
    """band_runs 目录（与 worker 子进程同口径：MS_OUT_DIR 环境变量优先）。"""
    return Path(os.environ.get('MS_OUT_DIR') or paths.OUT_DIR) / 'band_runs'


def _band_artifacts(label, seed):
    d = _band_runs_dir()
    return set(d.glob(f'band_{label}_seed{int(seed)}_*.json')) if d.exists() else set()


def _latest_artifact(label, seed):
    files = sorted(_band_artifacts(label, seed), key=lambda f: f.stat().st_mtime)
    return files[-1] if files else None


def artifact_replay_equal(path_a, path_b):
    """两次 run 的 band_runs 工件对拍（排除 wall-clock ``band_elapsed``）。"""
    if path_a is None or path_b is None:
        return False
    da = json.loads(Path(path_a).read_text(encoding='utf-8'))
    db = json.loads(Path(path_b).read_text(encoding='utf-8'))
    da.pop('band_elapsed', None)
    db.pop('band_elapsed', None)
    return da == db


# ---------------------------------------------------------------- 导出判据
class _WarningCapture(logging.Handler):
    """root logger WARNING+ 捕获（WB_ 泄漏哨兵 = export_geometry「导出跳过」warning）。"""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages: list = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def export_verify(final, pieces_by_id, gate_mm, out_dir, *, seed, stem):
    """三格式导出 + 泄漏哨兵（判据④）。

    placed 里 WB_ 条目（若泄漏）或 ``placed_to_world`` 找不到 pid 时
    「导出跳过：pid」warning 均判 fail；DXF/PLT 是文本字节，直接 grep ``b'WB_'``；
    DXF 头须为 R12（AC1009）且含 POLYLINE（ET2008 兼容口径）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    placed = final['placed_items']
    width_mm = float(final['width_mm'])
    density_pct = float(final['density']) * 100.0
    title = f'band_accept util={density_pct:.2f}% L={width_mm / 10:.1f}cm seed={seed}'

    wb_ids = sorted({str(it['id']) for it in placed if str(it['id']).startswith('WB_')})
    cap = _WarningCapture()
    root = logging.getLogger()
    root.addHandler(cap)
    try:
        world = placed_to_world(placed, pieces_by_id)
        blobs = {
            'png': render_png(world, width_mm=width_mm, gate_mm=gate_mm, title=title),
            'dxf': write_marker_dxf(world, width_mm=width_mm, gate_mm=gate_mm, title=title),
            'plt': write_marker_plt(world, width_mm=width_mm, gate_mm=gate_mm, title=title),
        }
    finally:
        root.removeHandler(cap)
    leak_warnings = [m for m in cap.messages if '导出跳过' in m]
    written = {}
    for ext, blob in blobs.items():
        dest = out_dir / f'{stem}.{ext}'
        dest.write_bytes(blob)
        written[ext] = {'path': str(dest), 'bytes': len(blob)}
    wb_in_bytes = [ext for ext in ('dxf', 'plt') if b'WB_' in blobs[ext]]
    dxf_ok = b'AC1009' in blobs['dxf'] and b'POLYLINE' in blobs['dxf']
    return {
        'files': written,
        'n_world_pieces': len(world),
        'wb_in_placed': wb_ids,
        'leak_warnings': leak_warnings,
        'wb_in_dxf_plt_bytes': wb_in_bytes,
        'dxf_is_r12_polyline': dxf_ok,
        'pass': bool(world and not wb_ids and not leak_warnings and not wb_in_bytes
                     and dxf_ok and all(len(b) > 0 for b in blobs.values())),
    }


# ---------------------------------------------------------------- 编排
def _pct(x):
    return None if x is None else round(float(x) * 100.0, 3)


def run_all(pieces, gate_mm, *, label=BAND_LABEL, quantities=None, per_type=None,
            params=None, sizes=ACCEPT_SIZES, seeds=AB_SEEDS, main_time=MAIN_TIME_S,
            band_time=None, determinism_seed=None, report_path=None, export_dir=None,
            log=print):
    """终验编排：密度 A/B -> 形态 -> 确定性 -> 导出 -> 报告落盘。

    两条 arm 共享同一 ``(pieces, gate_mm, solve_params)``（同源同构）；``band``
    仅 on 臂传 ``{'label', 'time_budget'}``（与 routes_ws 校验产物同构，ack 属
    WS 层职责不进本层）。返回报告 dict（``report_path`` 给定时落盘）。
    """
    quantities = accept_quantities() if quantities is None else quantities
    params = web_default_params() if params is None else params
    band_time = DEFAULT_BAND_TIME_BUDGET_S if band_time is None else int(band_time)
    det_seed = seeds[0] if determinism_seed is None else int(determinism_seed)
    pieces_by_id = {p['pid']: p for p in pieces}
    export_dir = Path(export_dir) if export_dir is not None \
        else Path(paths.CONFIG_RUNS_DIR) / '_probes'

    def solve_params_for(seed):
        return {'time_budget': int(main_time), 'seed': int(seed),
                'sizes': list(sizes), 'params': dict(params),
                'per_type': per_type, 'quantities': quantities}

    # ---- 判据①密度 A/B + 判据②形态（on 臂逐 seed；off 臂 g05 成对率作对照）----
    log(f'-- 判据①/② 密度 A/B + 形态：seeds {list(seeds)} × off/on，'
        f'main {main_time}s，band {band_time}s，label={label}（web 默认口径 d=0.0）')
    rows: list = []
    form_rows: list = []
    off_vals: list = []
    on_vals: list = []
    on_runs: dict = {}      # seed -> {'final','frames','artifact'}（判据③/④输入）
    off_finals: dict = {}
    for seed in seeds:
        seed = int(seed)
        off = run_arm(pieces, gate_mm, solve_params_for(seed), band=None)
        before = _band_artifacts(label, seed)
        on = run_arm(pieces, gate_mm, solve_params_for(seed),
                     band={'label': label, 'time_budget': band_time})
        new_art = sorted(_band_artifacts(label, seed) - before,
                         key=lambda f: f.stat().st_mtime)
        row = {'seed': seed,
               'off': ({'density_pct': _pct(off['final']['density']),
                        'width_mm': round(off['final']['width_mm'], 1),
                        'n_frames': len(off['frames'])} if off['ok']
                       else {'error': off['error']}),
               'on': None, 'deg_pt': None}
        if off['ok']:
            off_vals.append(float(off['final']['density']))
            off_finals[seed] = off['final']
        else:
            rows.append(row)
            log(f'   seed {seed}: off=失败（{off["error"]}）')
            continue
        if not on['ok']:
            row['on'] = {'error': on['error']}
            rows.append(row)
            log(f'   seed {seed}: off={row["off"]["density_pct"]}% | '
                f'on=失败（{on["error"]}）')
            continue
        on_vals.append(float(on['final']['density']))
        stage = on['stage'] or {}
        row['on'] = {'density_pct': _pct(on['final']['density']),
                     'width_mm': round(on['final']['width_mm'], 1),
                     'n_frames': len(on['frames']),
                     'stage': {'fill_pct': stage.get('fill_pct'),
                               'bbox': stage.get('bbox'),
                               'elapsed': stage.get('elapsed')}}
        row['deg_pt'] = round(
            (off['final']['density'] - on['final']['density']) * 100.0, 3)
        rows.append(row)
        on_runs[seed] = {'final': on['final'], 'frames': on['frames'],
                         'artifact': str(new_art[-1]) if new_art else None}

        placed = on['final']['placed_items']
        span = band_span(placed, pieces_by_id, label)
        form_rows.append({
            'seed': seed,
            'band_pair': pair_adjacency(placed, pieces_by_id, label=label),
            'off_band_pair_ref': pair_adjacency(
                off['final']['placed_items'], pieces_by_id, label=label),
            'all_pair_ref': pair_adjacency(placed, pieces_by_id),
            'span': span, 'stage_bbox': stage.get('bbox'),
            'span_ok': span_ok(span, stage.get('bbox')),
        })
        fr = form_rows[-1]
        log(f'   seed {seed}: off={row["off"]["density_pct"]}% | '
            f'on={row["on"]["density_pct"]}% | 劣化 {row["deg_pt"]}pt | '
            f'fill {stage.get("fill_pct")}% | 成对率 '
            f'{fr["band_pair"]["rate_pct"]}%（off 对照 '
            f'{fr["off_band_pair_ref"]["rate_pct"]}%）| span '
            f'{span["width_mm"]}x{span["height_mm"]}mm')

    ok_seeds = len(off_vals) == len(seeds) and len(on_vals) == len(seeds)
    mean_off = statistics.mean(off_vals) if off_vals else None
    mean_on = statistics.mean(on_vals) if on_vals else None
    mean_deg_pt = (round((mean_off - mean_on) * 100.0, 3)
                   if ok_seeds else None)
    density_pass = ok_seeds and mean_deg_pt <= DENSITY_ACCEPT_PT
    form_pass = (len(form_rows) == len(seeds)
                 and all(fr['band_pair']['pass'] and fr['span_ok']
                         for fr in form_rows))
    log(f'   均值 off={_pct(mean_off)}% on={_pct(mean_on)}% | 劣化 {mean_deg_pt}pt'
        f' -> {"PASS" if density_pass else "FAIL"}（<= {DENSITY_ACCEPT_PT}pt）')

    # ---- 判据③确定性：同 seed 重跑逐帧对拍 + band_runs 工件回放 ------------------
    log(f'-- 判据③ 确定性：seed {det_seed} on 臂重跑对拍（frames/final/工件）')
    first = on_runs.get(det_seed)
    if first is None:
        determinism = {'seed': det_seed, 'error': '首跑 on 臂缺失（前序失败）'}
    else:
        rerun = run_arm(pieces, gate_mm, solve_params_for(det_seed),
                        band={'label': label, 'time_budget': band_time})
        if not rerun['ok']:
            determinism = {'seed': det_seed, 'error': rerun['error']}
        else:
            determinism = {
                'seed': det_seed,
                'frames_equal': frame_series_equal(
                    frame_signature(first['frames']),
                    frame_signature(rerun['frames'])),
                'n_frames_run1': len(first['frames']),
                'n_frames_run2': len(rerun['frames']),
                'final_equal': final_signature(first['final'])
                == final_signature(rerun['final']),
                'artifact_replay_equal': artifact_replay_equal(
                    first['artifact'], _latest_artifact(label, det_seed)),
                'artifact': first['artifact'],
            }
    det_pass = bool(determinism.get('frames_equal') and determinism.get('final_equal')
                    and determinism.get('artifact_replay_equal'))
    log(f'   frames_equal={determinism.get("frames_equal")} '
        f'final_equal={determinism.get("final_equal")} '
        f'artifact_replay_equal={determinism.get("artifact_replay_equal")}')

    # ---- 判据④导出（on 臂 det_seed 末态 + off 臂同管线对照）----------------------
    export = {'on': None, 'off': None}
    if det_seed in on_runs:
        export['on'] = export_verify(
            on_runs[det_seed]['final'], pieces_by_id, gate_mm, export_dir,
            seed=det_seed, stem=f'{EXPORT_STEM}_on_seed{det_seed}')
        log(f'-- 判据④ 导出 on 臂: {"PASS" if export["on"]["pass"] else "FAIL"}'
            f'（泄漏哨兵 {export["on"]["leak_warnings"] or "无"}）')
    if det_seed in off_finals:
        export['off'] = export_verify(
            off_finals[det_seed], pieces_by_id, gate_mm, export_dir,
            seed=det_seed, stem=f'{EXPORT_STEM}_off_seed{det_seed}')
        log(f'   导出 off 臂（HEAD 同管线）: '
            f'{"PASS" if export["off"]["pass"] else "FAIL"}')
    export_pass = bool(export['on'] and export['on']['pass']
                       and export['off'] and export['off']['pass'])

    verdict = {'density': density_pass, 'form': form_pass,
               'determinism': det_pass, 'export': export_pass}
    verdict['conclusion'] = 'accept' if all(v for k, v in verdict.items()
                                            if k != 'conclusion') else 'reject'
    report = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'gate_mm': float(gate_mm),
        'config': {
            'label': label, 'sizes': list(sizes), 'params': params,
            'per_type': per_type, 'quantities': quantities,
            'main_time_s': int(main_time), 'band_time_s': int(band_time),
            'seeds': [int(s) for s in seeds], 'determinism_seed': det_seed,
            'density_accept_pt': DENSITY_ACCEPT_PT,
            'pair_eps_mm': PAIR_EPS_MM, 'span_slack_mm': SPAN_SLACK_MM,
        },
        'density_ab': {'per_seed': rows, 'off_mean_pct': _pct(mean_off),
                       'on_mean_pct': _pct(mean_on), 'mean_deg_pt': mean_deg_pt,
                       'pass': density_pass},
        'form': {'per_seed': form_rows, 'pass': form_pass},
        'determinism': determinism,
        'export': export,
        'verdict': verdict,
    }
    if report_path is not None:
        rp = Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        with open(rp, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        log(f'== 结论: {verdict["conclusion"]} == {verdict}')
        log(f'   报告 -> {rp}')
    return report


# ---------------------------------------------------------------------- CLI
def _parse_ints(text):
    return tuple(int(x) for x in str(text).split(',') if x.strip())


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description='US-014 腰头成带 A/B 验收闭环（报告落 '
                    'out/config_runs/_probes/band_accept_report.json）')
    ap.add_argument('--intermediate', default=paths.INTERMEDIATE,
                    help='pieces_intermediate.json 路径（只读；须为 5336 母版）')
    ap.add_argument('--label', default=BAND_LABEL, help='band g 码（默认 g05）')
    ap.add_argument('--seeds', default=','.join(str(s) for s in AB_SEEDS),
                    help='A/B seed 列表（逗号分隔，默认 0,1,2）')
    ap.add_argument('--time', type=int, default=MAIN_TIME_S,
                    help='主解预算秒（默认 120）')
    ap.add_argument('--band-time', type=int, default=DEFAULT_BAND_TIME_BUDGET_S,
                    help='带内构建预算秒（默认 15）')
    ap.add_argument('--report', default=os.path.join(paths.CONFIG_RUNS_DIR,
                                                     DEFAULT_REPORT_NAME),
                    help='报告输出路径')
    ap.add_argument('--quick', action='store_true',
                    help='冒烟档：预算缩到秒级（只验证管线跑通，结论无意义）')
    args = ap.parse_args(argv)

    seeds = (0,) if args.quick else _parse_ints(args.seeds)
    main_time = 2 if args.quick else args.time
    band_time = 2 if args.quick else args.band_time

    doc, pieces, gate_mm, _by_id = load_accept_pieces(args.intermediate)
    log = print
    log('== US-014 腰头成带 A/B 验收闭环 ==')
    log(f'   母版 {doc["source"]} | gate {gate_mm:.0f}mm'
        + ('（quick 冒烟档）' if args.quick else ''))
    report = run_all(pieces, gate_mm, label=args.label, seeds=seeds,
                     main_time=main_time, band_time=band_time,
                     report_path=args.report, log=log)
    return 0 if report['verdict']['conclusion'] == 'accept' else 1


if __name__ == '__main__':
    sys.exit(main())
