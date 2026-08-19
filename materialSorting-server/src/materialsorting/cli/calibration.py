r"""PC-004 标定管线：batch / variants / analyze 三子命令（kill 规则的数据依据）。

用**生产真实配置**（基实例 = ``data/configs/5336_coded_really.json``：真实 per_type
公差 + 真实订单配比；不用 per_type 全 0/数量全 1 的退化样例 —— 密度分布对生产失真）
及其**订单邻域变体**跑批标定 controller 参数：kill 规则既有本实例的精确包络、又
不过拟合单一订单。产物只落 ``out/portfolio_calibration/<tag>/``（gitignore 区），
不触碰 ``out/config_runs/`` 与 web 数据目录（FR-5）。

用法（``python -m`` 形式；``--tag`` 缺省 = 配置文件 stem，batch/variants/analyze
三个子命令用同一 tag 共享产物树）::

    python -m materialsorting.cli.calibration batch \
        --config data/configs/5336_coded_really.json \
        [--short-seeds 20] [--short-time 90] [--full-seeds 8] [--full-time N]
    python -m materialsorting.cli.calibration variants --config <同上> \
        [--variants 4] [--short-seeds 6] [--short-time 90] [--full-seeds 1] [--full-time N]
    python -m materialsorting.cli.calibration analyze --tag <tag> --target 0.88 \
        [--env-quantile 0.25]

目录结构（稳定契约，analyze / PC-005 simulate 依赖）::

    out/portfolio_calibration/<tag>/
    ├── base_config.json          基配置原样副本（provenance + variants 母本）
    ├── commit/                   唯一一次 commit（pieces/ + pieces_intermediate.json）
    ├── base/
    │   ├── short/                短预算组：默认 20 seed × 90s（seed 0..19）
    │   │   ├── pieces_intermediate.json（commit 副本）
    │   │   ├── curve_s{seed}.json / best_frame_s{seed}.json（solve_pieces 逐帧落盘）
    │   │   └── manifest.json     {group, time, seeds{seed: status/指标}, status}
    │   └── full/                 全预算组：默认 8 seed × config.time=300（seed 0..7，
    │                               与 short 组同值配对 → 短/全秩相关的配对样本）
    ├── variant_{i}.json          变体配置（确定性生成，RNG seed=i；i=0..N-1）
    ├── variant_{i}/
    │   ├── short/                默认 6 seed × 90s（seed 0..5）
    │   └── full/                 默认 1 seed × config.time（seed 0，与 short 配对）
    └── analysis/                 analyze 产物
        ├── summary.json          每 seed 终值/best/time-to-best/收敛平台 + mean/σ/
        │                           P(≥target) + 短/全秩相关 + uplift + 分离度
        ├── controller_params.json  ``--params`` 直读：calibrated + tau0/W/m/epsilon/
        │                           delta/m_streak/uplift_q95 + envelope（键名与
        │                           portfolio.KILL_DEFAULTS 一致，抄进 ms-run-config 即用）
        └── generalization.json   base 包络 × 变体误杀率 / 可迁移性判定

子命令语义：

  - **batch**：``commit_from_config`` 一次 + 逐 seed 串行 ``solve_pieces``（与
    ``ms-run-config`` 同链路同口径；不挂 target/kill —— 标定曲线必须是**无干扰**
    的裸求解轨迹）。**串行不变量**：任一时刻至多 1 个求解子进程。**续跑安全**：
    curve + best_frame 都在且曲线为非空合法 JSON 数组的 seed 视为完成、直接跳过
    （Ctrl-C 后重跑同一命令只补缺）。Ctrl-C 退出码 130，已完成 seed 产物已落盘。
  - **variants**：确定性变体生成器（seeded RNG，同参数两次生成逐字节一致）——
    **只抖订单维度**：quantities 每 (g 码, 码 ∈ sizes) 条目 ``n' = max(1, n + δ)``、
    δ ∈ {-1, 0, +1} 等概率（保底 1 片防整 g 码消失；sizes 子集外惰性条目与
    ``"null"`` 键不动）；工艺维度逐字段固定（per_type / gate_mm / master_dxf /
    sizes 不随订单漂移）。产出 ``variant_{i}.json``（过 ``load_config`` 7 键校验）
    → 逐变体串行 6 seed × 90s + 1 × 300s 全预算对照。
  - **analyze**：聚合 base 曲线 → summary + 成功包络 S(τ)（达标 seed best-so-far
    轨迹低位分位数，τ 网格 0.05~1.0 步长 0.05，**单调不降**：网格点间跑累积最大
    防分位数抖动）+ compression uplift 分布（q50/q95）+ 短/全秩相关（同 seed 值
    配对的 Spearman）+ train/test 误杀回测（R1 判据离线重放，复用 ``portfolio``
    的 ``make_envelope`` / ``r1_below_envelope`` 单一真相源）→ controller_params；
    聚合变体曲线 → 泛化报告（base 包络套用到各变体的误杀率 / 可迁移性判定）。
    **小样本拒绝下发**：base 曲线 < 10 条或达标 seed < 3 → ``calibrated: false`` +
    空 envelope（R1 整体禁用，不许真杀）。

退出码：0 成功；1 配置/输入错误（ConfigError / --target 越界 / tag 无曲线）；
2 求解失败；130 Ctrl-C（已完成 seed 产物已落盘）。

真实跑批 ≈ 2 小时机器时间（base 20×90s + 8×300s + 4 变体 × (6×90s + 1×300s)）
属运营步骤：代码落地后由用户/代理会话内执行，本模块只保证编排/续跑/分析正确。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import shutil
import statistics
import sys
import time
from pathlib import Path

from .. import paths
from .config import ConfigError, load_config
from .pipeline import commit_from_config, solve_pieces
from .portfolio import KILL_DEFAULTS, make_envelope, r1_below_envelope

__all__ = ['CalibrationError', 'TAU_GRID', 'backtest', 'calibration_dir',
           'curve_stats', 'envelope_from_curves', 'generate_variants',
           'jitter_quantities', 'load_curve', 'load_group_curves', 'main',
           'rank_correlation', 'replay_r1', 'run_batch', 'run_variants',
           'separation_tau0', 'split_train_test', 'spearman', 'uplift_distribution']

# 退出码（与 run_config 同风格）。
_EXIT_OK = 0
_EXIT_CONFIG = 1
_EXIT_SOLVE = 2
_EXIT_INTERRUPT = 130

# τ 网格：0.05 ~ 1.0 步长 0.05（PRD PC-004 包络口径）。
TAU_GRID = tuple(round(0.05 * i, 2) for i in range(1, 21))
# 小样本闸：base 曲线不足 10 条或达标 seed 不足 3 → 拒绝下发 calibrated。
_MIN_SEEDS_CALIBRATED = 10
_MIN_SUCCESS_ENVELOPE = 3
# 误杀率闸（PRD 目标 < 5%，泛化/回测共用）。
_FALSE_KILL_THRESHOLD = 0.05
# 长时求解心跳间隔（秒）—— 与 portfolio 控制器同值。
_HEARTBEAT_SEC = 30.0

# batch / variants 子命令的预算组缺省（PRD：base 20×90s + 8×300s；变体 6×90s + 1×300s）。
DEFAULT_SHORT_SEEDS = 20
DEFAULT_SHORT_TIME = 90
DEFAULT_FULL_SEEDS = 8
DEFAULT_VARIANTS = 4
VARIANT_SHORT_SEEDS = 6
VARIANT_FULL_SEEDS = 1

# curve 文件名（solve_pieces 落盘契约）。
_CURVE_RE = re.compile(r'^curve_s(\d+)\.json$')
_INTERMEDIATE_NAME = 'pieces_intermediate.json'


class CalibrationError(ValueError):
    """标定管线输入/产物问题（tag 目录无曲线、曲线文件损坏等）。"""


# -------------------------------------------------------------- 通用小工具


def calibration_dir(tag: str) -> Path:
    """标定 tag → 产物根目录（``paths.CALIBRATION_DIR/<tag>``，调用方负责 mkdir）。"""
    return Path(paths.CALIBRATION_DIR) / tag


def _dump_json(path: Path, payload) -> None:
    """JSON 落盘（UTF-8、ensure_ascii=False、缩进 2，与 result.json 同风格）。"""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _quantile(values, q: float) -> float | None:
    """线性插值分位数（inclusive 口径；n=1 返回该值；空返回 None）。"""
    vals = sorted(float(v) for v in values)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = q * (len(vals) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(vals) - 1)
    frac = pos - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def _best_density(curve: list[dict]) -> float:
    """曲线内最大帧 density（best 帧口径）。"""
    return max(float(fr.get('density', 0.0)) for fr in curve)


def _final_elapsed(curve: list[dict]) -> float:
    """末帧 elapsed（该 seed 的实际总时长 = τ 归一化分母）。"""
    return float(curve[-1].get('elapsed', 0.0))


# -------------------------------------------------------------- 曲线读取与统计


def load_curve(path: str | Path) -> list[dict]:
    """读单个 ``curve_s{seed}.json`` → 帧数组（损坏/空数组 → CalibrationError）。"""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as e:
        raise CalibrationError(f'曲线文件不可读（{p}）: {e}') from e
    if not isinstance(raw, list) or not raw:
        raise CalibrationError(f'曲线文件须为非空 JSON 数组: {p}')
    return raw


def load_group_curves(group_dir: str | Path) -> dict[int, list[dict]]:
    """组目录 → ``{seed: 曲线}``（glob ``curve_s*.json``，seed 从文件名解析）。"""
    out: dict[int, list[dict]] = {}
    for p in sorted(Path(group_dir).glob('curve_s*.json')):
        m = _CURVE_RE.match(p.name)
        if m:
            out[int(m.group(1))] = load_curve(p)
    return out


def curve_stats(curve: list[dict]) -> dict:
    """单曲线统计：终值 / best 帧 / time-to-best / 收敛平台 / 压缩期 uplift。

    - ``time_to_best``：best 帧（首个最大 density 帧）的 elapsed；
    - ``plateau_sec``/``plateau_ratio``：末帧时刻 − best 时刻（此后再无改进的
      平台时长及其占预算比）；
    - ``uplift``：首帧 ``phase == 'compressing'`` 时的 best-so-far → 该 seed 最终
      best 的增量（R2 判据「压缩期还能涨多少」的实证样本；无压缩帧为 None）。
    """
    best_i = 0
    for i, fr in enumerate(curve):
        if float(fr.get('density', 0.0)) > float(curve[best_i].get('density', 0.0)):
            best_i = i
    final = curve[-1]
    final_elapsed = float(final.get('elapsed', 0.0))
    time_to_best = float(curve[best_i].get('elapsed', 0.0))
    plateau = max(0.0, final_elapsed - time_to_best)
    uplift = None
    best_so_far = -math.inf
    for fr in curve:
        d = float(fr.get('density', 0.0))
        if d > best_so_far:
            best_so_far = d
        if str(fr.get('phase', '')) == 'compressing':
            uplift = round(float(curve[best_i].get('density', 0.0)) - best_so_far, 6)
            break
    return {
        'n_frames': len(curve),
        'final_density': round(float(final.get('density', 0.0)), 6),
        'best_density': round(float(curve[best_i].get('density', 0.0)), 6),
        'time_to_best': round(time_to_best, 3),
        'final_elapsed': round(final_elapsed, 3),
        'plateau_sec': round(plateau, 3),
        'plateau_ratio': round(plateau / final_elapsed, 4) if final_elapsed > 0 else None,
        'uplift': uplift,
    }


def _best_so_far_at_grid(curve: list[dict], grid=TAU_GRID) -> dict[float, float]:
    """best-so-far 轨迹在 τ 网格采样（τ = elapsed / 末帧 elapsed）。

    网格点 τ 取「elapsed ≤ τ·T 的最后一帧处的 best-so-far」；网格点早于首帧
    （首帧 elapsed 已越过 τ·T）时该点无样本、不出现在返回 dict 中。
    """
    total = _final_elapsed(curve)
    if total <= 0:
        return {}
    out: dict[float, float] = {}
    gi = 0
    best = -math.inf
    for fr in curve:
        d = float(fr.get('density', 0.0))
        if d > best:
            best = d
        t = float(fr.get('elapsed', 0.0))
        while gi < len(grid) and grid[gi] * total <= t + 1e-9:
            if best > -math.inf:
                out[grid[gi]] = best
            gi += 1
    return out


def envelope_from_curves(curves: list[list[dict]], target: float,
                         q: float = 0.25) -> dict[str, float]:
    """成功包络 S(τ)：达标 seed（best_density ≥ target）best-so-far 轨迹的低位分位数。

    返回 ``{"0.05": s, "0.10": s, ..., "1.00": s}``（τ 两位小数字符串键，与
    ``portfolio.make_envelope`` 的 ``--params envelope`` 消费格式一致）。**单调不降**
    保证：沿网格做累积最大 —— 分位数跨 seed 采样本身可能因样本集变动回退（某 τ
    段个别 seed 尚无帧），而包络语义（成功轨迹的下界）要求不降。无达标 seed → {}。
    """
    success = [c for c in curves if _best_density(c) >= target]
    if not success:
        return {}
    sampled = [_best_so_far_at_grid(c) for c in success]
    env: dict[str, float] = {}
    running = -math.inf
    for tau in TAU_GRID:
        vals = [s[tau] for s in sampled if tau in s]
        if not vals:
            continue
        v = _quantile(vals, q)
        if v is not None and v > running:
            running = v
        if running > -math.inf:
            env[f'{tau:.2f}'] = round(running, 6)
    return env


def uplift_distribution(curves: list[list[dict]]) -> dict:
    """compression uplift 分布（q50/q95 + 样本数；无压缩帧的曲线不计入）。"""
    vals = [u for u in (curve_stats(c)['uplift'] for c in curves) if u is not None]
    if not vals:
        return {'q50': None, 'q95': None, 'n': 0}
    return {'q50': round(_quantile(vals, 0.50), 6),
            'q95': round(_quantile(vals, 0.95), 6),
            'n': len(vals)}


def _ranks(vals: list[float]) -> list[float]:
    """平均秩（并列取平均），Spearman 用。"""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman 秩相关（n < 3 或任一侧零方差 → None）。"""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks([float(v) for v in xs]), _ranks([float(v) for v in ys])
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return None if den == 0 else num / den


def rank_correlation(short_curves: dict[int, list[dict]],
                     full_curves: dict[int, list[dict]]) -> dict:
    """短/全秩相关：同 seed 值配对（base 两组 seed 同值采样）的 best_density
    Spearman —— 「90s 探针能否预测 300s 结局」的量化（配对 < 3 → None）。"""
    common = sorted(set(short_curves) & set(full_curves))
    rho = None
    if len(common) >= 3:
        rho = spearman([_best_density(short_curves[s]) for s in common],
                       [_best_density(full_curves[s]) for s in common])
    return {'n_pairs': len(common),
            'spearman_best': None if rho is None else round(rho, 4)}


# -------------------------------------------------------------- R1 离线重放


def replay_r1(curve: list[dict], envelope: dict, kp: dict) -> bool:
    """R1 包络判据离线重放：该曲线若在 ``envelope`` + ``kp`` 下会被 R1 kill 吗。

    与 ``portfolio.PortfolioController._evaluate_kill`` 同语义（复用其纯函数
    ``make_envelope`` / ``r1_below_envelope``）：τ = elapsed/末帧 elapsed，
    d = best-so-far，τ ≤ τ0 不评估；低于 ``S(τ) − m`` **持续 W 秒**（追平清零）
    → would-kill。标定回测不区分队列序号（seed 1 豁免是运行期策略，非判据本身）。
    """
    fn = make_envelope({'envelope': envelope})
    if fn is None:
        return False
    total = _final_elapsed(curve)
    if total <= 0:
        return False
    best = -math.inf
    below_since: float | None = None
    for fr in curve:
        d = float(fr.get('density', 0.0))
        if d > best:
            best = d
        t = float(fr.get('elapsed', 0.0))
        tau = t / total
        if tau <= kp['tau0']:
            continue
        s_tau = fn(tau)
        if r1_below_envelope(best, s_tau, kp['m']):
            if below_since is None:
                below_since = t
            elif t - below_since >= kp['W']:
                return True
        else:
            below_since = None
    return False


def backtest(curves: list[list[dict]], target: float, kp: dict,
             envelope: dict) -> dict:
    """误杀回测：would-kill 的 seed 中「跑完本可达标」（best_density ≥ target）
    的占比 —— kill 引擎安全性的离线证据（PRD 目标 < 5%）。无 would-kill 时率记 0。"""
    would = 0
    false_kill = 0
    for c in curves:
        if replay_r1(c, envelope, kp):
            would += 1
            if _best_density(c) >= target:
                false_kill += 1
    return {'n': len(curves), 'would_kill': would, 'false_kill': false_kill,
            'false_kill_rate': round(false_kill / would, 4) if would else 0.0}


def split_train_test(items: dict[str, list[dict]]) -> tuple[list[list[dict]], list[list[dict]]]:
    """曲线集确定性二分（键字典序排序后奇偶交替）：even → train，odd → test。

    train 包络在 test 上回测 = 包络泛化能力的诚实评估（issued 包络用全部 base
    曲线，回测是方法学验证而非交付物）。
    """
    ordered = sorted(items.items(), key=lambda kv: kv[0])
    train = [v for i, (_k, v) in enumerate(ordered) if i % 2 == 0]
    test = [v for i, (_k, v) in enumerate(ordered) if i % 2 == 1]
    return train, test


def separation_tau0(curves: list[list[dict]], target: float,
                    q_env: float = 0.25, q_fail: float = 0.75) -> dict:
    """达标/失败轨迹分离度 → τ0 推荐：首个「成功包络 − 失败轨迹上分位 ≥ m」的网格点。

    gap(τ) = quantile_q_env(达标 best-so-far) − quantile_q_fail(失败 best-so-far)。
    分离出现得越早，R1 可以越早开始评估；两侧样本 < 2 或全程无分离 → 回退
    ``KILL_DEFAULTS['tau0']``（保守默认 0.3）。
    """
    success = [c for c in curves if _best_density(c) >= target]
    fail = [c for c in curves if _best_density(c) < target]
    if len(success) < 2 or len(fail) < 2:
        return {'tau0_recommended': KILL_DEFAULTS['tau0'], 'gap_at_tau0': None}
    s_grid = [_best_so_far_at_grid(c) for c in success]
    f_grid = [_best_so_far_at_grid(c) for c in fail]
    for tau in TAU_GRID:
        sv = [s[tau] for s in s_grid if tau in s]
        fv = [f[tau] for f in f_grid if tau in f]
        if not sv or not fv:
            continue
        gap = _quantile(sv, q_env) - _quantile(fv, q_fail)
        if gap is not None and gap >= KILL_DEFAULTS['m']:
            return {'tau0_recommended': tau, 'gap_at_tau0': round(gap, 6)}
    return {'tau0_recommended': KILL_DEFAULTS['tau0'], 'gap_at_tau0': None}


# -------------------------------------------------------------- 变体生成器（纯）


def jitter_quantities(quantities: dict, sizes: list[int] | None,
                      rng: random.Random) -> dict:
    """quantities 订单抖动（纯函数）：每 (g 码, 码 ∈ sizes) 条目 ``n_new = max(1, n+delta)``。

    delta ∈ {-1, 0, +1} 等概率（``rng`` 注入保证确定性）；保底 1 片防整 g 码消失。
    **sizes 子集外的惰性条目与 ``"null"`` 键不动**（码号键非数字或不在 sizes 内）；
    ``sizes`` 为 None（不过滤）时全部数字码号条目参与抖动。键序原样保留
    （同参数两次生成逐字节一致）。
    """
    allowed = None if sizes is None else {int(s) for s in sizes}
    out: dict = {}
    for g, size_map in quantities.items():
        new_map: dict = {}
        for sk, n in size_map.items():
            try:
                sk_int = int(sk)
            except (TypeError, ValueError):
                sk_int = None
            jitter = allowed is None or (sk_int is not None and sk_int in allowed)
            if jitter:
                new_map[sk] = max(1, int(n) + rng.choice((-1, 0, 1)))
            else:
                new_map[sk] = int(n)
        out[g] = new_map
    return out


def generate_variants(base_raw: dict, n_variants: int = DEFAULT_VARIANTS) -> list[dict]:
    """基配置（7 键原始 dict）→ N 个变体（确定性：变体 i 的 RNG seed = i）。

    只抖订单维度（quantities）；工艺维度 per_type / gate_mm / master_dxf / sizes /
    time / seeds 逐字段与基配置相同（浅拷贝 + 仅替换 quantities）。
    """
    variants: list[dict] = []
    for i in range(int(n_variants)):
        rng = random.Random(i)
        v = dict(base_raw)
        v['quantities'] = jitter_quantities(base_raw.get('quantities') or {},
                                            base_raw.get('sizes'), rng)
        variants.append(v)
    return variants


# -------------------------------------------------------------- 跑批编排


def _seed_complete(group_dir: Path, seed: int) -> bool:
    """seed 续跑判定：curve + best_frame 都在、且 curve 是非空合法 JSON 数组。

    ``solve_pieces`` 的 finally 保证 Ctrl-C 收口右括号 —— 半截曲线不会误判完成
    （JSON 解析失败即未完成）。
    """
    curve = group_dir / f'curve_s{seed}.json'
    best = group_dir / f'best_frame_s{seed}.json'
    if not (curve.is_file() and best.is_file()):
        return False
    try:
        raw = json.loads(curve.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(raw, list) and len(raw) > 0


def _ensure_commit(cfg, tag_dir: Path, echo=None) -> Path:
    """tag 树内唯一一次 commit（已存在 intermediate 则复用 —— commit 确定性幂等）。"""
    commit_dir = tag_dir / 'commit'
    if (commit_dir / _INTERMEDIATE_NAME).is_file():
        if echo:
            echo(f'commit: 复用已有 {commit_dir / _INTERMEDIATE_NAME}')
        return commit_dir
    summary = commit_from_config(cfg, commit_dir)
    if echo:
        echo(f"commit: n_pieces={summary['n_pieces']} "
             f"total_area={summary['total_area_mm2']:,.1f}mm² "
             f"sizes={summary['sizes']} skipped={summary['n_skipped']}")
    return commit_dir


def _prepare_group(commit_dir: Path, group_dir: Path) -> Path:
    """建组目录 + 拷 intermediate（solve_pieces 的 run_dir 契约：读同目录 intermediate）。"""
    group_dir.mkdir(parents=True, exist_ok=True)
    dst = group_dir / _INTERMEDIATE_NAME
    if not dst.is_file():
        shutil.copyfile(commit_dir / _INTERMEDIATE_NAME, dst)
    return group_dir


def _run_group(cfg, tag_dir: Path, group_dir: Path, seeds: list[int],
               time_budget: int, *, echo=None, solve=None,
               config_ref: str | None = None) -> dict:
    """一个预算组（组目录内逐 seed 串行求解 + manifest 逐 seed 落盘）。

    串行不变量：本循环逐 seed 调 ``solve``（默认 ``solve_pieces``，内部单子进程），
    上一 seed 返回前不启动下一个 —— 任一时刻至多 1 个求解子进程。已完成 seed
    （curve+best_frame 在场）跳过（续跑）；Ctrl-C 时 manifest 记 ``interrupted``
    后向上传播（CLI 转 130）。
    """
    if solve is None:
        solve = solve_pieces
    _prepare_group(tag_dir / 'commit', group_dir)
    rel = group_dir.relative_to(tag_dir).as_posix()
    manifest_path = group_dir / 'manifest.json'
    manifest: dict = {'group': rel, 'time': int(time_budget),
                      'config': config_ref, 'seeds': {}, 'status': 'running'}
    if manifest_path.is_file():
        try:
            prev = json.loads(manifest_path.read_text(encoding='utf-8'))
            if isinstance(prev, dict):
                prev['status'] = 'running'
                prev['time'] = int(time_budget)
                manifest = prev
        except (OSError, json.JSONDecodeError):
            pass                       # 旧 manifest 损坏：重建（曲线文件才是事实源）

    def _flush() -> None:
        _dump_json(manifest_path, manifest)

    _flush()
    for seed in seeds:
        key = str(int(seed))
        if _seed_complete(group_dir, int(seed)):
            old = manifest['seeds'].get(key) or {}
            old.update({'seed': int(seed), 'status': 'skipped'})
            manifest['seeds'][key] = old
            if echo:
                echo(f'[{rel}] seed={seed} 已完成，跳过')
            _flush()
            continue
        if echo:
            echo(f'[{rel}] seed={seed} 开始（{int(time_budget)}s）')
        last_beat = time.time()

        def on_progress(report: dict) -> None:
            nonlocal last_beat
            if echo is not None and time.time() - last_beat >= _HEARTBEAT_SEC:
                last_beat = time.time()
                echo(f"[{rel}] seed={seed} {report.get('elapsed', 0.0):7.1f}s 心跳 "
                     f"phase={report.get('phase', '')} "
                     f"real_density={float(report.get('density', 0.0)):.2%}（原面积口径）")

        try:
            rec = solve(cfg, group_dir, seed=int(seed),
                        time_budget=int(time_budget), on_progress=on_progress)
        except KeyboardInterrupt:
            manifest['status'] = 'interrupted'
            _flush()
            raise
        manifest['seeds'][key] = {
            'seed': int(seed), 'status': 'done',
            'real_density': rec.get('real_density'),
            'width_mm': rec.get('width_mm'),
            'elapsed': rec.get('elapsed'),
        }
        if echo:
            echo(f"[{rel}] seed={seed} 完成 best={float(rec.get('real_density', 0.0)):.2%} "
                 f"elapsed={float(rec.get('elapsed', 0.0)):.1f}s")
        _flush()
    manifest['status'] = 'complete'
    _flush()
    return manifest


def run_batch(cfg, tag_dir, *, short_seeds: int = DEFAULT_SHORT_SEEDS,
              short_time: int = DEFAULT_SHORT_TIME,
              full_seeds: int = DEFAULT_FULL_SEEDS, full_time: int,
              echo=None, solve=None) -> dict:
    """base 跑批编排：commit 一次 + short 组（seed 0..N-1 × T_s）+ full 组
    （seed 0..M-1 × T_f，与 short 同值配对 → 秩相关样本）。

    Returns
    -------
    dict
        ``{'short': manifest, 'full': manifest}``（manifest 含每组逐 seed 状态）。
    """
    tag_dir = Path(tag_dir)
    _ensure_commit(cfg, tag_dir, echo=echo)
    return {
        'short': _run_group(cfg, tag_dir, tag_dir / 'base' / 'short',
                            list(range(int(short_seeds))), int(short_time),
                            echo=echo, solve=solve),
        'full': _run_group(cfg, tag_dir, tag_dir / 'base' / 'full',
                           list(range(int(full_seeds))), int(full_time),
                           echo=echo, solve=solve),
    }


def run_variants(cfg, tag_dir, *, n_variants: int = DEFAULT_VARIANTS,
                 short_seeds: int = VARIANT_SHORT_SEEDS,
                 short_time: int = DEFAULT_SHORT_TIME,
                 full_seeds: int = VARIANT_FULL_SEEDS, full_time: int,
                 echo=None, solve=None, base_raw: dict | None = None) -> dict:
    """变体跑批编排：生成 variant_{i}.json（确定性）→ 逐变体 short + full 组串行。

    变体配置先写盘再 ``load_config`` 校验（7 键 schema，AC：生成物必须可加载），
    求解用校验后的 ``NestRunConfig``（quantities 已抖动）。变体间共用同一份
    commit（commit 不消费 quantities，产物逐字节相同 —— 拷贝复用，省解析时间）。
    """
    tag_dir = Path(tag_dir)
    if base_raw is None:
        raw_path = tag_dir / 'base_config.json'
        try:
            base_raw = json.loads(raw_path.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError) as e:
            raise CalibrationError(f'基配置不可读（{raw_path}）: {e}') from e
    _ensure_commit(cfg, tag_dir, echo=echo)
    variants = generate_variants(base_raw, int(n_variants))
    out: dict = {}
    for i, v_raw in enumerate(variants):
        v_path = tag_dir / f'variant_{i}.json'
        _dump_json(v_path, v_raw)
        cfg_v = load_config(v_path)
        v_dir = tag_dir / f'variant_{i}'
        if echo:
            changed = sum(
                1 for g, m in (v_raw.get('quantities') or {}).items()
                for sk, n in m.items()
                if n != (base_raw.get('quantities') or {}).get(g, {}).get(sk))
            echo(f'[variant_{i}] 配置就绪（{changed} 条订单条目抖动）')
        out[f'variant_{i}'] = {
            'short': _run_group(cfg_v, tag_dir, v_dir / 'short',
                                list(range(int(short_seeds))), int(short_time),
                                echo=echo, solve=solve, config_ref=str(v_path)),
            'full': _run_group(cfg_v, tag_dir, v_dir / 'full',
                               list(range(int(full_seeds))), int(full_time),
                               echo=echo, solve=solve, config_ref=str(v_path)),
        }
    return out


# -------------------------------------------------------------- analyze 聚合


def _group_summary(curves_by_seed: dict[int, list[dict]], target: float) -> dict:
    """一组曲线的聚合：逐 seed 统计 + best/final 的 mean/σ + P(≥target)。"""
    stats = {seed: curve_stats(c) for seed, c in sorted(curves_by_seed.items())}
    bests = [s['best_density'] for s in stats.values()]
    finals = [s['final_density'] for s in stats.values()]
    n = len(stats)
    reach = sum(1 for d in bests if d >= target)
    return {
        'n_seeds': n,
        'best_density': {'mean': round(statistics.fmean(bests), 6) if bests else None,
                         'sigma': round(statistics.stdev(bests), 6) if n >= 2 else 0.0},
        'final_density': {'mean': round(statistics.fmean(finals), 6) if finals else None,
                          'sigma': round(statistics.stdev(finals), 6) if n >= 2 else 0.0},
        'p_reach': round(reach / n, 4) if n else None,
        'seeds': [{'seed': seed, **s} for seed, s in stats.items()],
    }


def recommend_controller_params(base_curves: list[list[dict]], target: float,
                                env_q: float) -> dict:
    """base 曲线 → controller 参数推荐（数据驱动 + 保守钳制）。

    - ``tau0``：分离度推荐（首个成功包络高于失败上分位的网格点），clamp [0.05, 0.5]；
    - ``W``：0.1 × time-to-best 中位数，clamp [5, 30]s（迟滞窗 ≈ 十分之一典型收敛时延）；
    - ``m``：分离 gap 的一半，clamp [0.002, 0.01]（包络余量不超过实证分离度）；
    - ``delta``：best_density 的 σ（seed 间典型散布），clamp [0.001, 0.005]；
    - ``epsilon`` / ``m_streak``：无数据依据，保守默认；
    - ``uplift_q95``：压缩期 uplift 实证 q95（无样本回退默认 0.005）；
    - ``calibrated``：base 曲线 ≥ 10 且达标 seed ≥ 3 且包络非空，否则 false + 空
      envelope（小样本拒绝下发 —— R1 整体禁用，不许真杀）。

    数值键名与 ``portfolio.KILL_DEFAULTS`` 一致（``ms-run-config --params`` 直读）。
    """
    stats_all = [curve_stats(c) for c in base_curves]
    bests = [s['best_density'] for s in stats_all]
    n = len(base_curves)
    n_success = sum(1 for d in bests if d >= target)
    envelope = envelope_from_curves(base_curves, target, env_q)
    sep = separation_tau0(base_curves, target, q_env=env_q)
    calibrated = (n >= _MIN_SEEDS_CALIBRATED
                  and n_success >= _MIN_SUCCESS_ENVELOPE and bool(envelope))
    tau0 = min(0.5, max(0.05, float(sep['tau0_recommended'])))
    ttbs = [s['time_to_best'] for s in stats_all if s['time_to_best'] > 0]
    w_rec = (min(30.0, max(5.0, 0.1 * statistics.median(ttbs)))
             if ttbs else float(KILL_DEFAULTS['W']))
    gap = sep['gap_at_tau0']
    m_rec = (min(0.01, max(0.002, 0.5 * gap)) if gap else float(KILL_DEFAULTS['m']))
    sigma = statistics.stdev(bests) if n >= 2 else None
    delta_rec = (min(0.005, max(0.001, sigma)) if sigma is not None
                 else float(KILL_DEFAULTS['delta']))
    up = uplift_distribution(base_curves)
    params = {
        'calibrated': bool(calibrated),
        'tau0': round(tau0, 2),
        'W': round(w_rec, 1),
        'm': round(m_rec, 4),
        'epsilon': float(KILL_DEFAULTS['epsilon']),
        'delta': round(delta_rec, 4),
        'm_streak': int(KILL_DEFAULTS['m_streak']),
        'uplift_q95': (up['q95'] if up['q95'] is not None
                       else float(KILL_DEFAULTS['uplift_q95'])),
        'envelope': envelope if calibrated else {},
        # ---- 标定依据（load_controller_params 只要求顶层对象，多余键透传无害）----
        'target': target,
        'env_quantile': env_q,
        'n_base_seeds': n,
        'n_success_seeds': n_success,
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    return {'params': params, 'separation': sep, 'uplift': up,
            'n_base': n, 'n_success': n_success, 'calibrated': calibrated}


def generalization_report(variant_curves: dict[str, list[list[dict]]], target: float,
                          kp: dict, envelope: dict) -> dict:
    """泛化报告：base 包络套用到各变体曲线的 R1 误杀率 / 可迁移性判定。

    变体是 held-out（包络从未见过）；``transferable`` = 全部变体误杀率 < 5%
    （无变体曲线时为 None，报告注明）。误杀口径与 backtest 一致：would-kill 的
    变体 seed 中「本可达标」的占比。
    """
    variants: dict = {}
    pooled: list[list[dict]] = []
    for name in sorted(variant_curves):
        curves = variant_curves[name]
        pooled.extend(curves)
        bt = backtest(curves, target, kp, envelope)
        bests = [_best_density(c) for c in curves]
        variants[name] = {
            **bt,
            'p_reach': round(sum(1 for d in bests if d >= target) / len(bests), 4)
            if bests else None,
            'best_density_mean': round(statistics.fmean(bests), 6) if bests else None,
        }
    report: dict = {
        'target': target,
        'threshold': _FALSE_KILL_THRESHOLD,
        'envelope_source': 'base',
        'variants': variants,
    }
    if pooled:
        report['overall'] = backtest(pooled, target, kp, envelope)
        report['transferable'] = all(
            v['false_kill_rate'] < _FALSE_KILL_THRESHOLD for v in variants.values())
    else:
        report['overall'] = None
        report['transferable'] = None
        report['note'] = '无变体曲线（先跑 variants 子命令）'
    return report


def analyze_tag(tag_dir, target: float, env_q: float = 0.25) -> dict:
    """聚合 ``<tag>/`` 内 base + 变体曲线 → analysis/ 三产物（返回写盘内容）。

    Raises
    ------
    CalibrationError
        base/short 无曲线（batch 未跑或产物损坏）。
    """
    tag_dir = Path(tag_dir)
    short_curves = load_group_curves(tag_dir / 'base' / 'short')
    if not short_curves:
        raise CalibrationError(
            f'base/short 无曲线（{tag_dir / "base" / "short"}）—— 先跑 batch 子命令')
    full_curves = load_group_curves(tag_dir / 'base' / 'full')
    base_pooled = list(short_curves.values()) + list(full_curves.values())
    rec = recommend_controller_params(base_pooled, target, env_q)
    params = rec['params']
    kp = {k: params[k] for k in ('tau0', 'W', 'm', 'epsilon', 'delta',
                                 'm_streak', 'uplift_q95')}

    # train/test 误杀回测：train 包络（只见一半 base 曲线）在 train / test 上各评一次。
    keyed = {f'base_full_s{s}': c for s, c in full_curves.items()}
    keyed.update({f'base_short_s{s}': c for s, c in short_curves.items()})
    train, test = split_train_test(keyed)
    env_train = envelope_from_curves(train, target, env_q)
    params['backtest'] = {
        'split': 'even/odd（键字典序）',
        'train': backtest(train, target, kp, env_train),
        'test': backtest(test, target, kp, env_train),
    }

    variant_curves: dict[str, list[list[dict]]] = {}
    variants_present: dict = {}
    for vd in sorted(tag_dir.glob('variant_*')):
        if not vd.is_dir():
            continue
        pooled_v: list[list[dict]] = []
        vsum: dict = {}
        for grp in ('short', 'full'):
            cs = load_group_curves(vd / grp)
            vsum[grp] = _group_summary(cs, target)
            pooled_v.extend(cs.values())
        variants_present[vd.name] = vsum
        if pooled_v:
            variant_curves[vd.name] = pooled_v
    general = generalization_report(variant_curves, target, kp, params['envelope'])

    summary = {
        'target': target,
        'env_quantile': env_q,
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'tag_dir': str(tag_dir.resolve()),
        'base': {'short': _group_summary(short_curves, target),
                 'full': _group_summary(full_curves, target)},
        'rank_correlation': rank_correlation(short_curves, full_curves),
        'uplift': rec['uplift'],
        'separation': rec['separation'],
        'n_success_seeds': rec['n_success'],
        'variants': variants_present,
    }
    analysis_dir = tag_dir / 'analysis'
    analysis_dir.mkdir(parents=True, exist_ok=True)
    _dump_json(analysis_dir / 'summary.json', summary)
    _dump_json(analysis_dir / 'controller_params.json', params)
    _dump_json(analysis_dir / 'generalization.json', general)
    return {'summary': summary, 'params': params, 'generalization': general,
            'paths': {'summary': str(analysis_dir / 'summary.json'),
                      'controller_params': str(analysis_dir / 'controller_params.json'),
                      'generalization': str(analysis_dir / 'generalization.json')}}


# -------------------------------------------------------------- CLI


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog='python -m materialsorting.cli.calibration',
        description='PC-004 标定管线：生产真实配置跑批（batch）/ 订单邻域变体'
                    '（variants）/ 包络与误杀回测分析（analyze）；产物只落 '
                    'out/portfolio_calibration/<tag>/')
    sub = p.add_subparsers(dest='command', required=True)

    def _add_budget_flags(sp, *, short_seeds, full_seeds):
        sp.add_argument('--short-seeds', type=int, default=short_seeds, metavar='N',
                        help=f'短预算组 seed 数（默认 {short_seeds}，seed 0..N-1）')
        sp.add_argument('--short-time', type=int, default=DEFAULT_SHORT_TIME,
                        metavar='SEC',
                        help=f'短预算组单 seed 时长（默认 {DEFAULT_SHORT_TIME}s）')
        sp.add_argument('--full-seeds', type=int, default=full_seeds, metavar='N',
                        help=f'全预算组 seed 数（默认 {full_seeds}，与短组同值配对）')
        sp.add_argument('--full-time', type=int, default=None, metavar='SEC',
                        help='全预算组单 seed 时长（缺省 = config 的 time）')

    b = sub.add_parser(
        'batch', help='基实例跑批：commit 一次 + 短/全预算组逐 seed 串行求解')
    b.add_argument('--config', required=True,
                   help='7 键 config 路径（标定基实例，生产用 '
                        'data/configs/5336_coded_really.json）')
    b.add_argument('--tag',
                   help='标定 tag（产物根 out/portfolio_calibration/<tag>/，'
                        '缺省 = 配置文件 stem）')
    _add_budget_flags(b, short_seeds=DEFAULT_SHORT_SEEDS, full_seeds=DEFAULT_FULL_SEEDS)

    v = sub.add_parser(
        'variants', help='订单邻域变体：确定性生成 variant_{i}.json + 逐变体串行跑批')
    v.add_argument('--config', required=True,
                   help='基实例 config 路径（工艺维度逐字段固定，只抖 quantities）')
    v.add_argument('--tag',
                   help='标定 tag（须与 batch 同 tag 共享产物树，缺省 = 配置文件 stem）')
    v.add_argument('--variants', type=int, default=DEFAULT_VARIANTS, metavar='N',
                   help=f'变体数（默认 {DEFAULT_VARIANTS}，RNG seed=i 确定性生成）')
    _add_budget_flags(v, short_seeds=VARIANT_SHORT_SEEDS, full_seeds=VARIANT_FULL_SEEDS)

    a = sub.add_parser('analyze',
                       help='聚合曲线：summary + controller_params + 泛化报告')
    a.add_argument('--tag', required=True,
                   help='标定 tag（读 out/portfolio_calibration/<tag>/ 的曲线）')
    a.add_argument('--target', type=float, required=True, metavar='P',
                   help='达标阈值（(0,1] 原面积口径；P(≥target)/包络/误杀回测的锚点）')
    a.add_argument('--env-quantile', type=float, default=0.25, metavar='Q',
                   help='成功包络 S(τ) 的低位分位数（默认 0.25）')
    return p.parse_args(argv)


def _check_positive(name: str, v: int) -> None:
    if v < 1:
        raise CalibrationError(f'--{name} 须为正整数，当前为 {v}')


def _cmd_batch(args) -> int:
    cfg = load_config(args.config)
    for flag in ('short-seeds', 'short-time', 'full-seeds'):
        _check_positive(flag, getattr(args, flag.replace('-', '_')))
    if args.full_time is not None:
        _check_positive('full-time', args.full_time)
    tag = args.tag or Path(args.config).stem
    tag_dir = calibration_dir(tag)
    tag_dir.mkdir(parents=True, exist_ok=True)
    if not (tag_dir / 'base_config.json').is_file():
        shutil.copyfile(args.config, tag_dir / 'base_config.json')
    print(f'标定根目录: {tag_dir.resolve()}')
    full_time = args.full_time if args.full_time is not None else cfg.time
    est = args.short_seeds * args.short_time + args.full_seeds * full_time
    print(f'batch: short {args.short_seeds}×{args.short_time}s + full '
          f'{args.full_seeds}×{full_time}s，预计求解总时长 ≈ {est}s（不含解析/切片）')
    run_batch(cfg, tag_dir, short_seeds=args.short_seeds,
              short_time=args.short_time, full_seeds=args.full_seeds,
              full_time=full_time, echo=print)
    print(f'[batch] 完成：base short {args.short_seeds} seed + full '
          f'{args.full_seeds} seed 曲线已落盘 {tag_dir.resolve()}')
    return _EXIT_OK


def _cmd_variants(args) -> int:
    cfg = load_config(args.config)
    for flag in ('variants', 'short-seeds', 'short-time', 'full-seeds'):
        _check_positive(flag, getattr(args, flag.replace('-', '_')))
    if args.full_time is not None:
        _check_positive('full-time', args.full_time)
    tag = args.tag or Path(args.config).stem
    tag_dir = calibration_dir(tag)
    tag_dir.mkdir(parents=True, exist_ok=True)
    if not (tag_dir / 'base_config.json').is_file():
        shutil.copyfile(args.config, tag_dir / 'base_config.json')
    print(f'标定根目录: {tag_dir.resolve()}')
    full_time = args.full_time if args.full_time is not None else cfg.time
    est = args.variants * (args.short_seeds * args.short_time
                           + args.full_seeds * full_time)
    print(f'variants: {args.variants} 个变体 × (short {args.short_seeds}×'
          f'{args.short_time}s + full {args.full_seeds}×{full_time}s)，'
          f'预计求解总时长 ≈ {est}s（不含解析/切片）')
    run_variants(cfg, tag_dir, n_variants=args.variants,
                 short_seeds=args.short_seeds, short_time=args.short_time,
                 full_seeds=args.full_seeds, full_time=full_time, echo=print)
    print(f'[variants] 完成：{args.variants} 个变体曲线已落盘 {tag_dir.resolve()}')
    return _EXIT_OK


def _cmd_analyze(args) -> int:
    if not 0.0 < args.target <= 1.0:
        print(f'配置错误: --target 须为 (0,1] 区间内的比例值（如 0.88），'
              f'当前为 {args.target}', file=sys.stderr)
        return _EXIT_CONFIG
    if not 0.0 < args.env_quantile < 0.5:
        print(f'配置错误: --env-quantile 须为 (0, 0.5)（低位分位数），'
              f'当前为 {args.env_quantile}', file=sys.stderr)
        return _EXIT_CONFIG
    tag_dir = calibration_dir(args.tag)
    result = analyze_tag(tag_dir, args.target, env_q=args.env_quantile)
    s, p, g = result['summary'], result['params'], result['generalization']
    for grp in ('short', 'full'):
        sec = s['base'][grp]
        if sec['n_seeds']:
            print(f"[analyze] base/{grp}: n={sec['n_seeds']} "
                  f"best mean/σ={sec['best_density']['mean']:.2%}/"
                  f"{sec['best_density']['sigma']:.2%} "
                  f"P(≥{s['target']:.0%})={sec['p_reach']:.0%}")
    rho = s['rank_correlation']['spearman_best']
    rho_txt = 'n/a' if rho is None else f'{rho:.2f}'
    up = s['uplift']
    up_txt = ('n/a' if up['q95'] is None
              else f"{up['q50']:.2%}/{up['q95']:.2%}（n={up['n']}）")
    sep = s['separation']
    print(f'[analyze] 短/全秩相关 ρ={rho_txt}'
          f'（{s["rank_correlation"]["n_pairs"]} 对） | '
          f'uplift q50/q95={up_txt} | τ0 推荐={sep["tau0_recommended"]:.2f}'
          + (f'（gap={sep["gap_at_tau0"]:.2%}）' if sep['gap_at_tau0'] is not None
             else '（无分离，回退默认）'))
    bt = p['backtest']
    print(f"[analyze] 误杀回测 train={bt['train']['false_kill_rate']:.0%}"
          f"（would_kill {bt['train']['would_kill']}/{bt['train']['n']}） "
          f"test={bt['test']['false_kill_rate']:.0%}"
          f"（would_kill {bt['test']['would_kill']}/{bt['test']['n']}）")
    print(f"[analyze] controller_params: calibrated={str(p['calibrated']).lower()} "
          f"（{len(p['envelope'])} 个包络格点）"
          f" → {result['paths']['controller_params']}")
    if g['overall'] is not None:
        print(f"[analyze] 泛化: {len(g['variants'])} 个变体 | 总体误杀率 "
              f"{g['overall']['false_kill_rate']:.0%} | "
              f"可迁移={str(g['transferable']).lower()}"
              f" → {result['paths']['generalization']}")
    else:
        print(f"[analyze] 泛化: 无变体曲线（{g.get('note', '')}）")
    return _EXIT_OK


def main(argv: list[str] | None = None) -> int:
    # 首行防乱码：Windows 管道/重定向默认 GBK，强制 UTF-8（与 run_config 同款守卫）。
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError, OSError):
        pass

    args = _parse_args(argv)
    handlers = {'batch': _cmd_batch, 'variants': _cmd_variants,
                'analyze': _cmd_analyze}
    try:
        return handlers[args.command](args)
    except ConfigError as e:
        print(f'配置错误: {e}', file=sys.stderr)
        return _EXIT_CONFIG
    except CalibrationError as e:
        print(f'标定错误: {e}', file=sys.stderr)
        return _EXIT_CONFIG
    except KeyboardInterrupt:
        print('\n[中断] Ctrl-C：已完成 seed 的曲线/best 帧与 manifest 已落盘，'
              '重跑同一命令可续跑（跳过已完成 seed）', file=sys.stderr)
        return _EXIT_INTERRUPT
    except Exception as e:  # 求解/commit 抛错（与 run_config 的兜底口径一致）
        print(f'求解失败: {e}', file=sys.stderr)
        return _EXIT_SOLVE


if __name__ == '__main__':
    sys.exit(main())
