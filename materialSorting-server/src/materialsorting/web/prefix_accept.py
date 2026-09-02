"""US-005 起始端成套前后幅 A/B 验收闭环 —— 同源同构终验 + 形态判据 + 导出验证。

跑批口径（与 P0 探针 ``out/tmp_probe/`` 同构、与生产 real 密度同分母）：
  - **uploads 源**：intermediate 由 web 上传 commit 产生（5336 母版）；
  - **P0 口径 per_type**：d/tol 逐码覆盖取自 ``data/configs/5336_coded_really.json``
    （probe2/probe3 即此配置，PRD 基准 −0.14pt 与双开 89.33%/90.05% 均出自它，
    见 ``p0_per_type``）；params 仍全 0（前端 collectParams 不变量，per_type
    命中即覆盖 —— 与 UI 布局设置弹窗逐码覆盖同一条 ``_resolve_d_tol`` 路径）。
    **2026-08-25 实测教训：web 默认 d=0 口径下 60s 解不收敛**（无平台期，墙钟
    截断落点漂移 → 帧数 ±5% 逐帧不等、密度均值噪声 ±0.5pt）；P0 口径下同
    seed 两跑 956==956 帧逐帧全等 —— PRD 判据③的「逐帧相等」只在收敛口径
    下物理可达，故终验绑定 P0 口径；
  - **density = raw-width 生产口径**：主进程 ``_apply_density_dual`` 已换算为
    ``total_area/(width*gate)``（输入门幅即实际幅宽，90% 生死线口径），本模块
    直接读 final/frame 的 ``density`` 字段。

五项判据（tasks/prd-prefix-head-set.md US-005）：
  1. 密度 A/B：off vs on × seed {0,1,2,3}，均值劣化 <=1.0pt（P0 基准 −0.14pt）；
  2. 形态：4 成员同码（前 2 后 2）+ min_x(前缀) <=6mm（4/4 seed）+ 竖排贴触
     （相邻成员 y 区间交集 >0 且缝隙 <=1mm）+ 头尾 180° 交替（相邻成员 rot
     差 ≈180°）—— ``prefix_form``（原始轮廓世界几何口径，与导出/前端渲染
     一致）；截图另经浏览器验证落 ``.docs/business/``；
  3. 确定性：同 seed 重跑资格码选取一致 + placed_items/density 序列**核心
     轨迹逐帧相等**（忽略 wall-clock ``elapsed``；帧数差随机器速率漂移属墙钟
     物理非机制不确定 —— 2026-08-25 实测背靠背 1038==1038 全等、13 臂连跑
     热态 972/1036 内容仍逐帧对齐，见 ``frame_series_equal``）+ 末态「可达
     最优密度」重现（``final_best_equal``；final 快照随截断落点漂移为信息
     字段不 gate）+ ``prefix_runs`` 工件**构造回放**对拍（排除墙钟
     ``ts``/``stage_elapsed`` 与主解结局 ``pin``/``band_pos``/``width_mm``）；
  4. 导出：PNG/R12-DXF/PLT 三格式成功 + logging 无「导出跳过：pid」（``PS_``
     泄漏哨兵，``export_geometry.placed_to_world``）+ DXF/PLT 字节无 ``b'PS_'``
     + off 臂同管线导出成功（prefix 关闭路径 = HEAD 行为的产品级证据）；
  5. 双开档（band+prefix，不置换）另报一列：同源 band-only 对照 + 带位记录
     （``final.prefix.band_pos``，FR-8）+ P0 自由解基准（89.33%/90.05%）对照。

产物：报告 JSON + 三格式导出 -> ``out/config_runs/_probes/``（探针惯例，只读
web 事实源 ``pieces_intermediate.json``；prefix_runs 工件仍由 worker 落
``OUT_DIR`` 产品位置）。分层：本模块属 ``web``（须消费 ``solver``/``export``
真实产品管线），不进 ``server`` 路由（零副作用；结构镜像已删除的 US-014
``band_accept``，本文件是其 prefix 版后继）。

用法::

    python -m materialsorting.web.prefix_accept [--quick]   # quick=秒级冒烟，结论无意义
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from .. import paths
from ..nesting_engine.prefix import (
    GAP_EPS_MM,
    PIN_SKIP_AT_HEAD_MM,
    PREFIX_PID_PREFIX,
)
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
# P0 探针镜像（tasks/prd-prefix-head-set.md P0 节 + 确认清单 §7）：前/后幅 =
# g02/g03（1153×484 / 1155×360 两大片，面积最大两片 = US-004 默认预选）；7 码
# 数量表 31->1、36->3、其余->2 => 资格码 {32,33,34,35,38}、实例 ~119 副本与
# 生产同量级。
MASTER_PREFIX = '5336'
FRONT_LABEL = 'g02'
BACK_LABEL = 'g03'
BAND_LABEL = 'g05'
AB_SEEDS = (0, 1, 2, 3)
DUAL_SEEDS = (0, 1)
MAIN_TIME_S = 60
ACCEPT_SIZES = (31, 32, 33, 34, 35, 36, 38)
_MAIN_QTY = {31: 1, 32: 2, 33: 2, 34: 2, 35: 2, 36: 3, 38: 2}
# P0 口径 per_type 源（probe2/probe3 同款；quantities 限 ACCEPT_SIZES 后与
# accept_quantities() 逐字段相等 —— 2026-08-25 对拍确认）。
P0_CONFIG_PATH = os.path.join(paths.DATA_DIR, 'configs', '5336_coded_really.json')
# P0 探针双开自由解基准（确认清单 §7 ④，60s × seed{0,1}）—— 对照参考值。
P0_DUAL_FREE_PCT = {0: 89.33, 1: 90.05}

# ---------------------------------------------------------------- 判据阈值
DENSITY_ACCEPT_PT = 1.0   # 判据①：on 的 seed 均值劣化 <=1.0pt（PRD 验收线）
HEAD_EPS_MM = PIN_SKIP_AT_HEAD_MM   # 前缀锚定布头线 6mm（单一真相源 prefix）
GAP_EPS = GAP_EPS_MM                 # 相邻成员贴触缝隙 1mm（构造同口径）
ROT_ALT_EPS_DEG = 5.0    # 头尾交替 rot 差 |Δ-180°| 容差（朝向离散化噪声）
# 确定性帧数差相对容差：迭代内容确定（同 seed 逐帧一致），60s 墙钟截断落点
# 随机器速率漂移（P0 口径实测：背靠背两跑 1038==1038 全等；13 臂连跑热态
# 漂移 972 vs 1036 = 6.6% —— 内容仍逐帧对齐，只是截断帧位不同）。12% 为
# 观测 6.6% 留一倍余量的 sanity 护栏，防大面积轨迹漂移冒充速率差。
FRAME_COUNT_REL_TOL = 0.12
# 末态对拍 ε：final 是截断时刻快照（随速率漂移），判据看「可达最优密度」
# 重现性 —— best-so-far 帧密度差 <=0.1pt（实测背靠背 0.000pt）。
FINAL_BEST_EPS_PT = 0.1
DEFAULT_REPORT_NAME = os.path.join('_probes', 'prefix_accept_report.json')
EXPORT_STEM = 'prefix_accept_export'


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
    """web 工作台默认 params（前端 collectParams 不变量：恒全 0）。"""
    return {'d_ext': 0.0, 'd_int': 0.0, 'tol_ext': 0.0, 'tol_int': 0.0}


def p0_per_type(config_path=P0_CONFIG_PATH) -> dict:
    """读 P0 口径 per_type（d/tol 逐码覆盖；直接读 JSON，不 import cli —— 分层）。

    fail-fast：文件缺失 / 非 dict / per_type 键缺失 / 条目非 {d,tol} 数值对
    均抛 RuntimeError（终验数据源不对齐时立刻暴露，不带病跑 15 分钟）。
    """
    try:
        with open(config_path, encoding='utf-8') as f:
            doc = json.load(f)
    except OSError as e:
        raise RuntimeError(f'P0 口径配置不可读：{config_path}（{e}）') from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f'P0 口径配置非法 JSON：{config_path}（{e}）') from e
    per_type = doc.get('per_type')
    if not isinstance(per_type, dict) or not per_type:
        raise RuntimeError(f'P0 口径配置缺 per_type 段：{config_path}')
    out = {}
    for g, ov in per_type.items():
        if (not isinstance(ov, dict) or not isinstance(ov.get('d'), (int, float))
                or not isinstance(ov.get('tol'), (int, float))):
            raise RuntimeError(
                f'P0 口径 per_type.{g} 须为 {{d, tol}} 数值对，实际 {ov!r}')
        out[g] = {'d': float(ov['d']), 'tol': float(ov['tol'])}
    return out


def load_accept_pieces(intermediate_path):
    """读 intermediate（只读 web 事实源）；非 5336 母版 fail-fast（终验绑定 5336）。"""
    with open(intermediate_path, encoding='utf-8') as f:
        doc = json.load(f)
    source = str(doc.get('source', ''))
    if not source.startswith(MASTER_PREFIX):
        raise RuntimeError(
            f'US-005 终验绑定 {MASTER_PREFIX} 母版，当前 intermediate 源为 {source!r}'
            f'（先经 web 上传 commit，或核对 --intermediate 路径）')
    return doc, doc['pieces'], float(doc['gate_mm']), {p['pid']: p for p in doc['pieces']}


# ---------------------------------------------------------------- 单臂求解
def run_arm(pieces, gate_mm, solve_params, band=None, prefix=None):
    """跑一臂（真实产品管线 ``solve_with_callback_proc``，与 WS 路径同一代码）。

    返回 ``{'ok','error','stage','stages','manifest','frames','final'}``；frames
    保留逐帧 ``density/width_mm/placed_items``（确定性判据输入，density 已是
    主进程换算的原面积口径），final 为 worker 末态（prefix 臂另含 ``prefix``
    统计段）。
    """
    stage = None
    stages: list = []
    manifest = None
    final = None
    frames: list = []

    def on_manifest(m):
        nonlocal manifest
        manifest = m

    def on_report(r):
        frames.append(r)

    def on_stage(m):
        nonlocal stage
        stage = m
        stages.append(m)

    _proc, final_data, _elapsed, err = solve_with_callback_proc(
        [dict(p) for p in pieces], float(gate_mm), dict(solve_params),
        on_manifest=on_manifest, on_report=on_report, on_stage=on_stage,
        band=band, prefix=prefix)
    return {'ok': err is None and final_data is not None, 'error': err,
            'stage': stage, 'stages': stages, 'manifest': manifest,
            'frames': frames, 'final': final_data}


# ---------------------------------------------------------------- 形态判据
def _world_geom(piece, placement):
    """placement -> 原始轮廓 shapely 几何（世界系；与导出/前端渲染同口径）。"""
    pts = apply_transform(piece['polygon'], float(placement.get('rotation', 0.0)),
                          placement.get('translation', [0.0, 0.0]))
    g = Polygon(pts)
    if not g.is_valid:
        g = g.buffer(0)
    if g.geom_type != 'Polygon':
        g = g.convex_hull
    return g


def prefix_form(placed, pieces_by_id, front, back, size, *,
                head_eps_mm=HEAD_EPS_MM, gap_eps_mm=GAP_EPS,
                rot_eps_deg=ROT_ALT_EPS_DEG):
    """US-005 判据②形态：4 成员同码 + 锚定布头 + 竖排贴触 + 头尾 180° 交替。

    成员识别 = pid ∈ ``{f'{front}_{size}', f'{back}_{size}'}``（主实例
    ``exclude_pids`` 已扣减该两 pid 的成员计数份数 ⇒ final 中这 4 条**只能**来自
    ``PS_`` 组合片展开 —— 计数即守恒口径。2026-09-02 异码补片：``stack_ok`` /
    ``interleave`` 长度口径放宽 in (4,5) 兼容第 5 片（顶部异码，不属 want 集合、
    不参与 same_code 2+2 计数 —— US-005 回放护栏新形态）。子判据（PRD 逐字）：

    - ``same_code``：前 2 后 2 恰 4 条；
    - ``head_ok``：成员原始轮廓世界 bbox ``min_x`` <= 6mm（版师 P5「严格顶到
      布头零位」—— pin 守卫同阈值，自然锚定常态 ~0.1mm）；
    - ``stack_ok``：按世界 bbox min_y 排序后**相邻对** y 区间交集 >0（交错
      咬合竖排，US-004 实测缝隙为负 = 重叠）且 shapely 边距 <=1mm（构造贴触
      口径 ``GAP_EPS_MM``；重叠时 distance=0）。注：真实 5336 几何贴触即咬合
      （>0）；合成矩形退化形态是 y 恰好邻接（=0，缝隙口径仍全过 —— 冒烟测试
      的放宽断言口径，真实终验仍按 >0 严格判）；
    - ``rot_ok``：相邻对 rot 差（mod 360）≈180°（头尾相对，版师 P1 参照图；
      阈值 ±5° 吸收朝向离散化噪声）。

    另随报告输出 interleave 交错序（placed 构造序 = ``expand_placements``
    展开序，前后交替）供形态审计。``pass`` = 四子判据全真；无成员（off 臂 /
    size 不符）时四项全 False 不误报。
    """
    want = {f'{front}_{size}', f'{back}_{size}'}
    rows = []
    for it in placed:
        pid = str(it.get('id'))
        if pid not in want:
            continue
        p = pieces_by_id.get(pid)
        if p is None:
            continue
        g = _world_geom(p, it)
        b = g.bounds
        rows.append({'pid': pid, 'rot': float(it.get('rotation', 0.0)),
                     'geom': g, 'minx': b[0], 'maxx': b[2],
                     'miny': b[1], 'maxy': b[3]})
    n_front = sum(1 for r in rows if r['pid'].startswith(f'{front}_'))
    n_back = sum(1 for r in rows if r['pid'].startswith(f'{back}_'))
    same_code = n_front == 2 and n_back == 2
    min_x = round(min((r['minx'] for r in rows), default=float('nan')), 3)
    head_ok = bool(rows) and min_x <= head_eps_mm

    stack = sorted(rows, key=lambda r: r['miny'])
    y_overlaps, gaps, rot_diffs = [], [], []
    for a, b in zip(stack, stack[1:]):
        y_overlaps.append(round(min(a['maxy'], b['maxy']) - max(a['miny'], b['miny']), 3))
        gaps.append(round(a['geom'].distance(b['geom']), 3))
        d = abs((a['rot'] - b['rot']) % 360.0)
        rot_diffs.append(round(min(d, 360.0 - d), 2))
    # 2026-09-02 异码补片：长度口径放宽 in (4,5) —— 4 = 基座成员，5 = 调用方
    # 把顶部异码补片并入成员集时（US-005 回放护栏兼容新形态）；same_code 仍按
    # want 集合 2+2 计数不受影响。
    stack_ok = (len(stack) in (4, 5)
                and all(ov > 0.0 for ov in y_overlaps)
                and all(g <= gap_eps_mm for g in gaps))
    rot_ok = (len(rot_diffs) == 3
              and all(abs(d - 180.0) <= rot_eps_deg for d in rot_diffs))

    def _is_front(r):
        return r['pid'].startswith(f'{front}_')

    interleave = (len(rows) in (4, 5)
                  and all((_is_front(a) != _is_front(b))
                          for a, b in zip(rows, rows[1:])))
    return {
        'size': size, 'n_front': n_front, 'n_back': n_back,
        'same_code': same_code,
        'min_x_mm': min_x, 'head_ok': head_ok,
        'y_overlap_mm': y_overlaps, 'gaps_mm': gaps,
        'stack_ok': stack_ok,
        'rot_diff_deg': rot_diffs, 'rot_ok': rot_ok,
        'interleave': interleave,
        'order': [r['pid'] for r in rows],
        'pass': bool(same_code and head_ok and stack_ok and rot_ok),
    }


# ---------------------------------------------------------------- 确定性判据
def frame_signature(frames):
    """逐帧签名（density/width_mm/placed_items）—— 忽略 wall-clock ``elapsed``。"""
    return [(round(float(f['density']), 9), round(float(f['width_mm']), 6),
             f['placed_items']) for f in frames]


def frame_series_equal(frames_a, frames_b):
    """两次 run 的帧序列「逐帧相等」判定（US-005 判据③，wall-clock 速率感知）。

    求解器对同 seed **迭代内容确定**（2026-08-25 P0 口径实测：背靠背两跑
    1038==1038 帧逐帧全等），但 60s 墙钟预算的**截断帧位**随机器速率漂移
    （连跑热态 972 vs 1036 = 6.6%，短列是长列的确定前缀 —— 内容逐帧对齐、
    只是少跑了几帧）。PRD 口径「非 byte-identity —— 帧嵌 wall-clock」涵盖
    此类漂移。判定 = 两者前 ``min(n)-1`` 帧逐帧相等（核心轨迹硬判据）
    + 帧数差 ``FRAME_COUNT_REL_TOL`` 相对护栏（防大面积轨迹漂移冒充速率差；
    US-014 band 收敛口径实测 0%，本口径连跑热态 6.6%）。
    """
    n = min(len(frames_a), len(frames_b))
    core_equal = frames_a[:max(0, n - 1)] == frames_b[:max(0, n - 1)]
    denom = max(1, max(len(frames_a), len(frames_b)))
    rate_ok = abs(len(frames_a) - len(frames_b)) / denom <= FRAME_COUNT_REL_TOL
    return bool(core_equal and rate_ok)


def final_signature(final):
    """末态签名（density/width_mm/placed_items）—— 忽略 ``elapsed``。"""
    if final is None:
        return None
    return (round(float(final['density']), 9), round(float(final['width_mm']), 6),
            final['placed_items'])


def final_best_equal(final_a, final_b, *, frames_a=None, frames_b=None):
    """末态「可达最优」对拍（判据③ final 臂，截断快照感知）。

    ``final`` 是截断时刻的**当前解快照**（随机器速率落点漂移，density 可比
    另一跑差零点几 pt —— 属墙钟物理非机制不确定，off 臂同样存在）。确定性
    判据看求解器**可达最优密度**重现：两跑帧列 best-so-far 最大帧密度差
    <= ``FINAL_BEST_EPS_PT``。``final_equal``（快照逐字段）另作信息字段
    报告但不 gate 判据③。
    """
    if final_a is None or final_b is None:
        return False
    ba = [float(f['density']) for f in (frames_a or [])]
    bb = [float(f['density']) for f in (frames_b or [])]
    if not ba or not bb:
        return False
    return abs(max(ba) - max(bb)) * 100.0 <= FINAL_BEST_EPS_PT


def _prefix_runs_dir() -> Path:
    """prefix_runs 目录（与 worker 子进程同口径：MS_OUT_DIR 环境变量优先）。"""
    return Path(os.environ.get('MS_OUT_DIR') or paths.OUT_DIR) / 'prefix_runs'


def _prefix_artifacts(front, back):
    d = _prefix_runs_dir()
    pat = f'*_{PREFIX_PID_PREFIX}{front}+{back}@*.json'
    return set(d.glob(pat)) if d.exists() else set()


def _latest_artifact(front, back):
    files = sorted(_prefix_artifacts(front, back), key=lambda f: f.stat().st_mtime)
    return files[-1] if files else None


_ARTIFACT_WALL_CLOCK_KEYS = ('ts', 'stage_elapsed')
# 求解结局依赖字段（pin.a = 组合片在主解的 min_x、band_pos = WB 主解落位、
# width_mm = 主解宽）—— 随截断快照漂移（同 final 物理），不入构造回放判据。
_ARTIFACT_SOLVE_STATE_KEYS = ('pin', 'band_pos', 'width_mm')


def artifact_replay_equal(path_a, path_b):
    """两次 run 的 prefix_runs 工件**构造回放**对拍（判据③，速率物理感知）。

    工件是 FR-6 全量回放体；其中**构造段**（资格码/chunk.to_dict/fill/bbox/
    holes/gaps/d_g）无 RNG 同 seed 确定，逐键相等即构造确定性；``ts``/
    ``stage_elapsed`` 是墙钟、``pin``/``band_pos``/``width_mm`` 是主解结局
    快照（随截断落点漂移，与 final 同物理）—— 三类字段不入判据。
    """
    if path_a is None or path_b is None:
        return False
    da = json.loads(Path(path_a).read_text(encoding='utf-8'))
    db = json.loads(Path(path_b).read_text(encoding='utf-8'))
    for k in _ARTIFACT_WALL_CLOCK_KEYS + _ARTIFACT_SOLVE_STATE_KEYS:
        da.pop(k, None)
        db.pop(k, None)
    return da == db


# ---------------------------------------------------------------- 导出判据
class _WarningCapture(logging.Handler):
    """root logger WARNING+ 捕获（PS_ 泄漏哨兵 = export_geometry「导出跳过」warning）。"""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages: list = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def export_verify(final, pieces_by_id, gate_mm, out_dir, *, seed, stem):
    """三格式导出 + 泄漏哨兵（判据④）。

    placed 里 PS_ 条目（若泄漏）或 ``placed_to_world`` 找不到 pid 时
    「导出跳过：pid」warning 均判 fail；DXF/PLT 是文本字节，直接 grep ``b'PS_'``；
    DXF 头须为 R12（AC1009）且含 POLYLINE（ET2008 兼容口径）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    placed = final['placed_items']
    width_mm = float(final['width_mm'])
    density_pct = float(final['density']) * 100.0
    # 2026-08-28 版师两位小数 cm 口径（与 /export 标题、前端 NestLabel 同口径）。
    title = f'prefix_accept util={density_pct:.2f}% L={width_mm / 10:.2f}cm seed={seed}'

    ps_ids = sorted({str(it['id']) for it in placed
                     if str(it['id']).startswith(PREFIX_PID_PREFIX)})
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
    ps_in_bytes = [ext for ext in ('dxf', 'plt') if b'PS_' in blobs[ext]]
    dxf_ok = b'AC1009' in blobs['dxf'] and b'POLYLINE' in blobs['dxf']
    return {
        'files': written,
        'n_world_pieces': len(world),
        'ps_in_placed': ps_ids,
        'leak_warnings': leak_warnings,
        'ps_in_dxf_plt_bytes': ps_in_bytes,
        'dxf_is_r12_polyline': dxf_ok,
        'pass': bool(world and not ps_ids and not leak_warnings and not ps_in_bytes
                     and dxf_ok and all(len(b) > 0 for b in blobs.values())),
    }


# ---------------------------------------------------------------- 编排
def _pct(x):
    return None if x is None else round(float(x) * 100.0, 3)


def run_all(pieces, gate_mm, *, front=FRONT_LABEL, back=BACK_LABEL,
            band_label=BAND_LABEL, quantities=None, per_type=None,
            params=None, sizes=ACCEPT_SIZES, seeds=AB_SEEDS, dual_seeds=DUAL_SEEDS,
            main_time=MAIN_TIME_S, determinism_seed=None, report_path=None,
            export_dir=None, log=print):
    """终验编排：密度 A/B -> 双开档 -> 确定性 -> 导出 -> 报告落盘。

    各臂共享同一 ``(pieces, gate_mm, solve_params)``（同源同构）；``prefix`` /
    ``band`` 仅相应臂传 ``{'front','back'}`` / ``{'label'}``（routes_ws 校验
    产物同构形态）。off 臂 = prefix 代码在库但未激活 = HEAD 主路径（US-003 #1
    契约：无 prefix 键管线逐字节不变）。返回报告 dict（``report_path`` 给定时
    落盘）。
    """
    quantities = accept_quantities() if quantities is None else quantities
    params = web_default_params() if params is None else params
    det_seed = seeds[0] if determinism_seed is None else int(determinism_seed)
    pieces_by_id = {p['pid']: p for p in pieces}
    export_dir = Path(export_dir) if export_dir is not None \
        else Path(paths.CONFIG_RUNS_DIR) / '_probes'

    def solve_params_for(seed):
        return {'time_budget': int(main_time), 'seed': int(seed),
                'sizes': list(sizes), 'params': dict(params),
                'per_type': per_type, 'quantities': quantities}

    # ---- 判据① 密度 A/B + 判据② 形态（on 臂逐 seed）-----------------------
    log(f'-- 判据①/② 密度 A/B + 形态：seeds {list(seeds)} × off/on，'
        f'main {main_time}s，prefix {front}/{back}（P0 口径 per_type '
        f'{len(per_type or {})} 码）')
    rows: list = []
    form_rows: list = []
    off_vals: list = []
    on_vals: list = []
    on_runs: dict = {}      # seed -> {'final','frames','artifact','size'}（判据③/④输入）
    off_finals: dict = {}
    for seed in seeds:
        seed = int(seed)
        off = run_arm(pieces, gate_mm, solve_params_for(seed))
        before = _prefix_artifacts(front, back)
        on = run_arm(pieces, gate_mm, solve_params_for(seed),
                     prefix={'front': front, 'back': back})
        new_art = sorted(_prefix_artifacts(front, back) - before,
                         key=lambda f: f.stat().st_mtime)
        row = {'seed': seed,
               'off': ({'density_pct': _pct(off['final']['density']),
                        'width_mm': round(off['final']['width_mm'], 1),
                        'n_frames': len(off['frames'])} if off['ok']
                       else {'error': off['error']}),
               'on': None, 'deg_pt': None}
        if not off['ok']:
            rows.append(row)
            log(f'   seed {seed}: off=失败（{off["error"]}）')
            continue
        off_vals.append(float(off['final']['density']))
        off_finals[seed] = off['final']
        if not on['ok']:
            row['on'] = {'error': on['error']}
            rows.append(row)
            log(f'   seed {seed}: off={row["off"]["density_pct"]}% | '
                f'on=失败（{on["error"]}）')
            continue
        on_vals.append(float(on['final']['density']))
        pf = (on['final'].get('prefix') or {})
        size = pf.get('size')
        stage = next((s for s in on['stages'] if s.get('stage') == 'prefix'), None)
        row['on'] = {'density_pct': _pct(on['final']['density']),
                     'width_mm': round(on['final']['width_mm'], 1),
                     'n_frames': len(on['frames']), 'size': size,
                     'pin_skipped': bool((pf.get('pin') or {}).get('skipped')),
                     'stage': ({'size': stage.get('size'),
                                'fill_pct': stage.get('fill_pct'),
                                'bbox': stage.get('bbox'),
                                'holes': stage.get('holes'),
                                'elapsed': stage.get('elapsed')}
                               if stage else None)}
        row['deg_pt'] = round(
            (off['final']['density'] - on['final']['density']) * 100.0, 3)
        rows.append(row)
        on_runs[seed] = {'final': on['final'], 'frames': on['frames'],
                         'artifact': str(new_art[-1]) if new_art else None,
                         'size': size}
        form = None
        if size is not None:
            form = prefix_form(on['final']['placed_items'], pieces_by_id,
                               front, back, int(size))
            form['pin'] = pf.get('pin')
            form_rows.append(form)
        log(f'   seed {seed}: off={row["off"]["density_pct"]}% | '
            f'on={row["on"]["density_pct"]}% | 劣化 {row["deg_pt"]}pt | '
            f'码 {size}'
            + (f' min_x {form["min_x_mm"]}mm 形态 '
               f'{"PASS" if form["pass"] else "FAIL"}' if form else ''))

    ok_seeds = len(off_vals) == len(seeds) and len(on_vals) == len(seeds)
    mean_off = statistics.mean(off_vals) if off_vals else None
    mean_on = statistics.mean(on_vals) if on_vals else None
    mean_deg_pt = (round((mean_off - mean_on) * 100.0, 3)
                   if ok_seeds else None)
    density_pass = ok_seeds and mean_deg_pt <= DENSITY_ACCEPT_PT
    form_pass = (len(form_rows) == len(seeds)
                 and all(fr['pass'] for fr in form_rows))
    log(f'   均值 off={_pct(mean_off)}% on={_pct(mean_on)}% | 劣化 {mean_deg_pt}pt'
        f' -> {"PASS" if density_pass else "FAIL"}（<= {DENSITY_ACCEPT_PT}pt）'
        f'；形态 {len(form_rows)}/{len(seeds)} '
        f'{"PASS" if form_pass else "FAIL"}')

    # ---- 双开档另报列（band-only 对照 vs band+prefix，不置换 + 带位记录）----
    dual_rows: list = []
    band_vals: list = []
    dual_vals: list = []
    if dual_seeds:
        log(f'-- 双开档：seeds {list(dual_seeds)} × band_only/dual（band '
            f'{band_label} + prefix {front}/{back}，不置换）')
    for seed in dual_seeds:
        seed = int(seed)
        b_only = run_arm(pieces, gate_mm, solve_params_for(seed),
                         band={'label': band_label})
        dual = run_arm(pieces, gate_mm, solve_params_for(seed),
                       band={'label': band_label},
                       prefix={'front': front, 'back': back})
        row = {'seed': seed,
               'band_only': ({'density_pct': _pct(b_only['final']['density']),
                              'width_mm': round(b_only['final']['width_mm'], 1)}
                             if b_only['ok'] else {'error': b_only['error']}),
               'dual': None, 'deg_pt': None, 'band_pos': None,
               'p0_free_ref_pct': P0_DUAL_FREE_PCT.get(seed)}
        if not b_only['ok'] or not dual['ok']:
            row['dual'] = ({'error': dual['error']} if not dual['ok']
                           else {'density_pct': _pct(dual['final']['density'])})
            dual_rows.append(row)
            log(f'   双开 seed {seed}: '
                f'band_only={"ok" if b_only["ok"] else b_only["error"]} | '
                f'dual={"ok" if dual["ok"] else dual["error"]}')
            continue
        band_vals.append(float(b_only['final']['density']))
        dual_vals.append(float(dual['final']['density']))
        pf = dual['final'].get('prefix') or {}
        size = pf.get('size')
        form = (prefix_form(dual['final']['placed_items'], pieces_by_id,
                            front, back, int(size))
                if size is not None else None)
        row['dual'] = {'density_pct': _pct(dual['final']['density']),
                       'width_mm': round(dual['final']['width_mm'], 1),
                       'size': size,
                       'min_x_mm': form['min_x_mm'] if form else None,
                       'form_pass': form['pass'] if form else False}
        row['deg_pt'] = round((float(b_only['final']['density'])
                               - float(dual['final']['density'])) * 100.0, 3)
        row['band_pos'] = pf.get('band_pos')
        dual_rows.append(row)
        bp = pf.get('band_pos') or {}
        log(f'   双开 seed {seed}: band_only={row["band_only"]["density_pct"]}% | '
            f'dual={row["dual"]["density_pct"]}%（P0 基准 {row["p0_free_ref_pct"]}%）'
            f' | 码 {size} min_x {row["dual"]["min_x_mm"]}mm | 带位 min_x '
            f'{bp.get("min_x")}mm 距布尾 {bp.get("dist_to_tail_mm")}mm')
    dual_ok = bool(dual_seeds) and len(dual_rows) == len(dual_seeds) \
        and len(band_vals) == len(dual_seeds) and len(dual_vals) == len(dual_seeds)
    dual_mean_deg = (round((statistics.mean(band_vals) - statistics.mean(dual_vals))
                           * 100.0, 3) if dual_ok else None)
    dual_band_pos_ok = bool(dual_rows) and all(r.get('band_pos') for r in dual_rows)
    dual_pass = bool(dual_ok and dual_mean_deg <= DENSITY_ACCEPT_PT
                     and dual_band_pos_ok)
    if dual_seeds:
        log(f'   双开均值 band_only={_pct(statistics.mean(band_vals) if band_vals else None)}%'
            f' dual={_pct(statistics.mean(dual_vals) if dual_vals else None)}%'
            f' | 劣化 {dual_mean_deg}pt | 带位记录 {dual_band_pos_ok}'
            f' -> {"PASS" if dual_pass else "FAIL"}')

    # ---- 判据③ 确定性：同 seed 重跑选码/逐帧/final/工件四对拍 --------------
    log(f'-- 判据③ 确定性：seed {det_seed} on 臂重跑对拍（选码/frames/final/工件）')
    first = on_runs.get(det_seed)
    if first is None:
        determinism = {'seed': det_seed, 'error': '首跑 on 臂缺失（前序失败）'}
    else:
        rerun = run_arm(pieces, gate_mm, solve_params_for(det_seed),
                        prefix={'front': front, 'back': back})
        if not rerun['ok']:
            determinism = {'seed': det_seed, 'error': rerun['error']}
        else:
            rsize = (rerun['final'].get('prefix') or {}).get('size')
            nf1, nf2 = len(first['frames']), len(rerun['frames'])
            determinism = {
                'seed': det_seed,
                'size_run1': first['size'], 'size_run2': rsize,
                'size_equal': first['size'] == rsize,
                'frames_equal': frame_series_equal(
                    frame_signature(first['frames']),
                    frame_signature(rerun['frames'])),
                'n_frames_run1': nf1,
                'n_frames_run2': nf2,
                'frame_count_diff_pct': round(
                    abs(nf1 - nf2) / max(1, max(nf1, nf2)) * 100.0, 2),
                # final 快照随截断落点漂移（墙钟物理，off 臂同款）—— 信息字段
                # 不 gate；判据看「可达最优密度」重现（final_best_equal）。
                'final_equal': final_signature(first['final'])
                == final_signature(rerun['final']),
                'final_best_equal': final_best_equal(
                    first['final'], rerun['final'],
                    frames_a=first['frames'], frames_b=rerun['frames']),
                'best_density_run1': round(max(
                    float(f['density']) for f in first['frames']) * 100.0, 3),
                'best_density_run2': round(max(
                    float(f['density']) for f in rerun['frames']) * 100.0, 3),
                'artifact_replay_equal': artifact_replay_equal(
                    first['artifact'], _latest_artifact(front, back)),
                'artifact': first['artifact'],
            }
    det_pass = bool(determinism.get('size_equal') and determinism.get('frames_equal')
                    and determinism.get('final_best_equal')
                    and determinism.get('artifact_replay_equal'))
    log(f'   选码一致={determinism.get("size_equal")} '
        f'frames_equal={determinism.get("frames_equal")}'
        f'（帧数 {determinism.get("n_frames_run1")}/'
        f'{determinism.get("n_frames_run2")}，差 '
        f'{determinism.get("frame_count_diff_pct")}% = 速率截断漂移）'
        f' best密度重现={determinism.get("final_best_equal")}'
        f'（{determinism.get("best_density_run1")}%/'
        f'{determinism.get("best_density_run2")}%）'
        f' artifact_replay_equal={determinism.get("artifact_replay_equal")}'
        f' | final快照逐字段={determinism.get("final_equal")}（信息字段）')

    # ---- 判据④ 导出（on 臂 det_seed 末态 + off 臂同管线对照）----------------
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

    verdict = {'density': density_pass, 'form': form_pass, 'dual': dual_pass,
               'determinism': det_pass, 'export': export_pass}
    verdict['conclusion'] = 'accept' if all(v for k, v in verdict.items()
                                            if k != 'conclusion') else 'reject'
    report = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'gate_mm': float(gate_mm),
        'config': {
            'front': front, 'back': back, 'band_label': band_label,
            'sizes': list(sizes), 'params': params, 'per_type': per_type,
            'quantities': quantities, 'main_time_s': int(main_time),
            'seeds': [int(s) for s in seeds],
            'dual_seeds': [int(s) for s in dual_seeds],
            'determinism_seed': det_seed,
            'density_accept_pt': DENSITY_ACCEPT_PT,
            'head_eps_mm': HEAD_EPS_MM, 'gap_eps_mm': GAP_EPS,
            'rot_eps_deg': ROT_ALT_EPS_DEG,
            'p0_dual_free_ref_pct': dict(P0_DUAL_FREE_PCT),
        },
        'density_ab': {'per_seed': rows, 'off_mean_pct': _pct(mean_off),
                       'on_mean_pct': _pct(mean_on), 'mean_deg_pt': mean_deg_pt,
                       'pass': density_pass},
        'form': {'per_seed': form_rows, 'pass': form_pass},
        'dual_open': {'per_seed': dual_rows,
                      'band_only_mean_pct': _pct(statistics.mean(band_vals)
                                                 if band_vals else None),
                      'dual_mean_pct': _pct(statistics.mean(dual_vals)
                                            if dual_vals else None),
                      'mean_deg_pt': dual_mean_deg, 'pass': dual_pass},
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
        description='US-005 起始端成套前后幅 A/B 验收闭环（报告落 '
                    'out/config_runs/_probes/prefix_accept_report.json）')
    ap.add_argument('--intermediate', default=paths.INTERMEDIATE,
                    help='pieces_intermediate.json 路径（只读；须为 5336 母版）')
    ap.add_argument('--front', default=FRONT_LABEL, help='前幅 g 码（默认 g02）')
    ap.add_argument('--back', default=BACK_LABEL, help='后幅 g 码（默认 g03）')
    ap.add_argument('--band-label', default=BAND_LABEL,
                    help='双开档 band g 码（默认 g05）')
    ap.add_argument('--seeds', default=','.join(str(s) for s in AB_SEEDS),
                    help='A/B seed 列表（逗号分隔，默认 0,1,2,3）')
    ap.add_argument('--dual-seeds', default=','.join(str(s) for s in DUAL_SEEDS),
                    help='双开档 seed 列表（逗号分隔，默认 0,1）')
    ap.add_argument('--time', type=int, default=MAIN_TIME_S,
                    help='主解预算秒（默认 60）')
    ap.add_argument('--report', default=os.path.join(paths.CONFIG_RUNS_DIR,
                                                     DEFAULT_REPORT_NAME),
                    help='报告输出路径')
    ap.add_argument('--quick', action='store_true',
                    help='冒烟档：预算缩到秒级（只验证管线跑通，结论无意义）')
    args = ap.parse_args(argv)

    seeds = (0,) if args.quick else _parse_ints(args.seeds)
    dual_seeds = () if args.quick else _parse_ints(args.dual_seeds)
    main_time = 2 if args.quick else args.time

    doc, pieces, gate_mm, _by_id = load_accept_pieces(args.intermediate)
    per_type = p0_per_type()
    log = print
    log('== US-005 起始端成套前后幅 A/B 验收闭环 ==')
    log(f'   母版 {doc["source"]} | gate {gate_mm:.0f}mm | 前后幅 '
        f'{args.front}/{args.back}'
        + ('（quick 冒烟档）' if args.quick else ''))
    log(f'   P0 口径 per_type {sorted(per_type)}（{P0_CONFIG_PATH}）')
    t0 = time.time()
    report = run_all(pieces, gate_mm, front=args.front, back=args.back,
                     band_label=args.band_label, per_type=per_type,
                     seeds=seeds, dual_seeds=dual_seeds, main_time=main_time,
                     report_path=args.report, log=log)
    log(f'   总耗时 {round(time.time() - t0, 1)}s')
    return 0 if report['verdict']['conclusion'] == 'accept' else 1


if __name__ == '__main__':
    sys.exit(main())

