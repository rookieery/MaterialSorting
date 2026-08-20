"""串行 seed portfolio 控制器（PC-002）：incumbent banking + R0 达标即停 + R4 队列耗尽；
PC-003 扩展 kill 引擎（R1 包络 / R2 压缩期判决 / R3 θ 衰减 + shadow mode）；
PC-009 扩展 run 统计库读取与 θ₀ 按实例类校准；
US-001 扩展策略双模式判据纯函数族（race 门杀 / SE 筛延 + 种子流 + 名义记账规划）。

``run_config`` 的多 seed 串行循环自 PC-002 起**经本控制器转发**（不再裸调
``solve_pieces``）：控制器是纯 Python 状态机，持有三类状态 ——
incumbent（全局最优帧）、per-seed best（各 seed 最优帧密度）、队列停止位
（R0 触发后剩余 seed 不再启动）。

规则：

  - **incumbent banking（FR-2）**：每帧 real 口径 ``density`` **严格大于**全局最优
    即入账（来源 ``seed`` / ``frame_index`` / ``elapsed`` / ``width_mm`` /
    ``placed_items`` 完整布局一并记录）。被 kill / 中途停止的 seed 的最优帧同样
    参与全局最优 —— 修复旧版 ``best`` 只看 per-seed 终值（final 解）的盲区；
    任何中断（kill / Ctrl-C / 队列耗尽）交付物都是过程中的最好帧。
  - **R0 达标即停**：``--target`` 给定时，任一帧 ``density >= target`` → 对当前
    seed 触发 ``should_stop``（终止链路杀子进程，当前 seed 交付 best-so-far 帧
    ``killed=True``），并**终止剩余队列**（后续 seed 不再启动）。R0 恒用
    ``--target`` 真值（θ 衰减只影响 kill 门槛不影响停止条件）。
  - **R4 队列耗尽**：全部 seed 跑满预算 → 正常结束，交付 incumbent。

PC-003 kill 引擎（``kill='shadow'|'off'|'on'``，仅 ``--target`` 给定时激活 ——
θ 初值 = target 是判据锚点）：必死 seed 提前淘汰省出预算。逐帧评估
（τ = elapsed/time_budget、d = 该 seed best-so-far、I = incumbent、θ 初值 = target）：

  - **R1 包络 kill**：seed 序号（队列 1 起）> 1 且 τ > τ0 且 ``d < S(τ) − m``
    **持续 W 秒**（迟滞防瞬时下探误杀）→ kill。S 来自标定参数 ``envelope``
    （PC-004 analyze 产物）；**无标定时 R1 整体禁用**。
  - **R2 压缩期判决**：该 seed **首帧** ``phase == 'compressing'`` 时
    ``d + uplift_q95 < max(θ, I + ε)`` → kill —— 即使压缩期 uplift 全部兑现也
    追不上门槛即必死；无标定用保守默认 uplift_q95 = 0.005。
  - **R3 θ 衰减**：``kill_streak ≥ m_streak`` → ``θ := I + δ``（单调只降，
    ``min`` 防回升）—— 只降 kill 门槛，**R0 恒用真 target**；衰减时经
    ``notify`` 打一行（不静默改判据）并记 ``theta_history``。
  - **seed 1（队列首）永不 kill**：锚定交付下限 + 校准样本。
  - 保守默认（``--params`` 可覆盖，pt = 密度百分点，fraction 口径 0.005 = 0.5pt）：
    τ0=0.3、W=10s、m=0.5pt、ε=0.1pt、δ=0.3pt、m_streak=3。

kill 决策落盘：shadow / on 模式下每个 ``(seed, rule)`` **首次**触发经
``on_decision`` 回调交出一条记录（ASCII 键名对应 PRD 的
``{t, seed, rule, d, τ, S(τ), θ, I, would_kill}``）；shadow 只记不杀
（``should_stop`` 仅由 R0 触发），on 才真正触发 ``should_stop``（且 CLI 层要求
标定参数 ``calibrated: true``，否则降级 shadow 并 warn —— 见 run_config）。

``--params``（controller_params.json，PC-004 标定产物）经 ``load_controller_params``
加载为 dict 传入控制器 —— 数值阈值（tau0/W/m/epsilon/delta/m_streak/uplift_q95）
与 ``envelope``（S(τ) 阶梯）/ ``calibrated`` 在此消费；7 键 config schema 不动。

PC-009 run 统计库与 θ₀ 校准（``run_config`` 结束时向 ``paths.RUN_STATS_JSONL``
追加一行，本模块提供读取与校准纯函数）：

  - ``run_stats_class_key(source, sizes, quantities, per_type)``：实例类指纹 =
    sha1(规范化 JSON) 前 10 位十六进制 —— 同一母版 + 码号集 + 订单配比 + 逐码
    公差的组合视为同一「实例类」（工艺维度不变、订单漂移内的历史可互相参考）；
  - ``load_run_stats(path)``：读 JSONL → 记录列表（缺文件 / 坏行 / 非 dict 行
    静默跳过 —— 统计库 append-only，坏行不阻断校准）；
  - ``calibrate_theta0(records, class_key, target)``：当前实例类命中且 ≥
    ``THETA0_MIN_RECORDS``(5) 条 → ``θ₀ = min(target, 历史最大 best_density +
    THETA0_MARGIN 0.003)``（历史最高 89.6% 的组合不再从 90 起跑 —— kill 门槛贴
    着可达性走，省下注定追不上的预算），否则 θ₀ = target。θ₀ **只影响 kill
    门槛**（R2/R3 判据锚），R0 停止条件恒用 ``--target`` 真值。

US-001 策略双模式判据（``--strategy race|se`` 的单一真相源，纯函数无 I/O 无进程；
US-002 由 ``PortfolioController`` 接线消费，US-003 simulate 复用同一判据）：

  - **race 门杀（方案 B，默认）**：每 seed 带 ``RACE_BUDGET_S``(180s) 预算启动，
    ``race_gate_seconds``(默认 90s) 门帧处 ``decide_race_kill`` 判定 ——
    ``best_so_far <= bar`` 即杀（严格破纪录才续跑）、首 seed 豁免、bar = 历史
    所有 seed 门值最大值（含被杀者）、每 seed 至多一笔（门后不再判）；
  - **SE 筛延（方案 A）**：``se_plan`` 名义记账规划 k 轮 ``SE_SCREEN_S``(90s)
    筛选 + 冠军 ``SE_EXT_S``(180s) 延长（预算不足 ``StrategyBudgetError``）；
  - **种子流** ``strategy_seed_stream``：config seeds 优先、max+1 补齐、保证
    无重复（同预算重跑同 seed 是纯浪费 —— 确定性重放下零信息增益）。

进度口径（``echo`` 给定时；``run_config`` 传 ``None if quiet else print``）：
沿用「原面积口径新最优才打 + 30s 心跳」—— per-seed 新最优行与心跳行**逐字保留**
旧版格式（零回归），新增**跨 seed 反超**时的 incumbent 行（同 seed 自我刷新不打，
信息已被 per-seed 行覆盖；单 seed 运行输出与旧版逐字一致）。
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from .pipeline import solve_pieces

__all__ = ['R0_REASON', 'R1_REASON', 'R2_REASON', 'R5_REASON', 'KILL_DEFAULTS',
           'KILL_MODES', 'THETA0_MIN_RECORDS', 'THETA0_MARGIN',
           'RACE_BUDGET_S', 'RACE_GATE_TAU', 'SE_SCREEN_S', 'SE_EXT_S',
           'SEED_UNIT_S', 'FULL_UNIT_S', 'STRATEGY_STARTUP_S',
           'ControllerParamsError', 'StrategyBudgetError', 'PortfolioController',
           'PortfolioRun', 'calibrate_theta0', 'decide_race_kill',
           'load_controller_params', 'load_run_stats', 'make_envelope',
           'r1_below_envelope', 'race_gate_seconds', 'r2_below_threshold',
           'resolve_kill_params', 'run_serial_portfolio', 'run_stats_class_key',
           'se_plan', 'strategy_seed_stream']

# R0 / R1 / R2 触发的 should_stop 返回值（solve_pieces 透传为 kill_reason）。
R0_REASON = 'R0_target_reached'
R1_REASON = 'R1_envelope'
R2_REASON = 'R2_compression_verdict'
# 长时求解心跳间隔（秒）—— 与 run_config 旧版 per-seed printer 同值。
_HEARTBEAT_SEC = 30.0

# --kill 旗标取值（run_config argparse choices 同源）。
KILL_MODES = ('shadow', 'off', 'on')

# kill 引擎保守默认（--params 数值键可覆盖；pt = 密度百分点，0.005 = 0.5pt）。
KILL_DEFAULTS: dict = {
    'tau0': 0.3,          # R1 最早评估预算占比（τ > τ0 才看包络）
    'W': 10.0,            # R1 迟滞窗（秒）：包络下方持续 W 秒才杀
    'm': 0.005,           # R1 包络余量（0.5pt）
    'epsilon': 0.001,     # R2 incumbent 余量（0.1pt）
    'delta': 0.003,       # R3 θ 衰减幅度（0.3pt）
    'm_streak': 3,        # R3 连杀阈值（连续被 kill 的 seed 数）
    'uplift_q95': 0.005,  # R2 压缩期 uplift 无标定保守默认
}

# PC-009 θ₀ 校准参数：当前实例类历史样本量与贴边余量（与 R3 δ 同值 —— θ 系
# 列判据统一用 0.3pt 步进）。
THETA0_MIN_RECORDS = 5    # 触发校准的最少历史 run 数（不足 → θ₀ = target 不动）
THETA0_MARGIN = 0.003     # θ₀ = min(target, 历史最大 best_density + margin)


# -------------------------------------------------------------- run 统计库（PC-009）


def run_stats_class_key(source, sizes, quantities, per_type) -> str:
    """实例类指纹：``sha1(规范化 JSON)[:10]``（十六进制短哈希）。

    组件 = ``(source, sizes, quantities, per_type)`` —— 母版（绝对路径字符串）+
    码号过滤 + 订单配比 + 逐 g 码公差，即「工艺维度固定、订单邻域内」的组合键；
    dict 组件经 ``sort_keys`` 规范化（键序无关），同输入必同 key。写入侧
    （``run_config`` 结束追加）与读取侧（θ₀ 校准）共用本函数，class 口径单一
    真相源。
    """
    payload = json.dumps(
        {'source': str(source), 'sizes': sizes, 'quantities': quantities,
         'per_type': per_type},
        ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha1(payload.encode('utf-8')).hexdigest()[:10]


def load_run_stats(path) -> list[dict]:
    """读 run 统计库 JSONL → 记录列表（缺文件 / 坏 JSON 行 / 非 dict 行静默跳过）。

    统计库 append-only 且只增不改（PC-005 kill 引擎决策日志同款容错哲学）：单行
    损坏只损失该行样本，不让 θ₀ 校准整体失败。空行剔除；文件不可读（OSError）
    视为无历史。
    """
    try:
        text = Path(path).read_text(encoding='utf-8-sig')
    except OSError:
        return []
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def calibrate_theta0(records, class_key: str, target: float,
                     *, min_records: int = THETA0_MIN_RECORDS,
                     margin: float = THETA0_MARGIN) -> tuple[float, dict | None]:
    """θ₀ 校准（纯）：按实例类聚合历史 best_density，贴可达性定 kill 门槛初值。

    当前 ``class_key`` 命中且有效记录 ≥ ``min_records`` 条 →
    ``θ₀ = min(target, 历史最大 best_density + margin)``（``min`` 封顶防历史最高
    + 余量反超 target 抬门槛）；否则 ``θ₀ = target``（新款首次排料 / 样本不足的
    回退语义）。返回 ``(theta0, info)``：``info`` 为 None（未校准）或
    ``{'n_records', 'max_density'}``（命中说明行的数据源）。

    θ₀ **只影响 kill 门槛**（控制器 ``self.theta`` 的初值，R2 判据锚 / R3 衰减
    起点）；R0 停止条件恒用 ``--target`` 真值（回归由 ``make_should_stop`` 保证）。
    记录里缺 ``best_density`` / 非数值 / bool 的行不计入样本（写侧坏行防御）。
    """
    target = float(target)
    densities: list[float] = []
    for rec in records if isinstance(records, list) else []:
        if not isinstance(rec, dict) or rec.get('class_key') != class_key:
            continue
        v = rec.get('best_density')
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        densities.append(float(v))
    if len(densities) < min_records:
        return target, None
    hist_max = max(densities)
    theta0 = min(target, hist_max + float(margin))
    return round(theta0, 6), {'n_records': len(densities),
                              'max_density': round(hist_max, 6)}


# -------------------------------------------------------------- kill 纯函数


def r1_below_envelope(d: float, s_tau: float | None, m: float) -> bool:
    """R1 判据（纯）：seed best-so-far ``d`` 低于成功包络 ``S(τ) − m``。

    ``s_tau`` 为 None（无标定 / τ 早于包络网格首格点）时 R1 不可评估 → 恒 False。
    等值不算 below（严格小于）。
    """
    return s_tau is not None and d < s_tau - m


def r2_below_threshold(d: float, uplift_q95: float, theta: float,
                       incumbent: float | None, epsilon: float) -> bool:
    """R2 判据（纯）：压缩期首帧 ``d + uplift_q95 < max(θ, I + ε)``。

    即使压缩期 uplift（q95 保守上界）全部兑现也追不上 kill 门槛 → 必死。
    ``incumbent`` 为 None（尚无全局最优帧）时门槛退化为 θ。
    """
    threshold = theta if incumbent is None else max(theta, incumbent + epsilon)
    return d + uplift_q95 < threshold


def make_envelope(params: dict):
    """标定参数 → S(τ) 阶梯查询函数（无 ``envelope`` 键 / 空 / 全非法 → None，R1 禁用）。

    ``envelope`` 形如 ``{"0.3": 0.71, "0.35": 0.735, ...}``（PC-004 analyze 产物，
    τ 网格 0.05~1.0 步长 0.05 的低位分位数）；``S(τ)`` = 最大网格点 ≤ τ 的值
    （包络随 τ 单调不降的阶梯近似）；τ 早于首格点返回 None（该帧不可评估 → 不杀）。
    """
    raw = params.get('envelope')
    if not isinstance(raw, dict) or not raw:
        return None
    grid: list[tuple[float, float]] = []
    for k, v in raw.items():
        if isinstance(v, bool):
            continue
        try:
            grid.append((float(k), float(v)))
        except (TypeError, ValueError):
            continue                      # 非数值格点静默剔除（PC-004 产物容错）
    if not grid:
        return None
    grid.sort()

    def s_of(tau: float) -> float | None:
        val: float | None = None
        for t, s in grid:
            if t <= tau + 1e-12:
                val = s
            else:
                break
        return val

    return s_of


def resolve_kill_params(params: dict) -> dict:
    """保守默认 + ``--params`` 数值覆盖（未知键 / 非数值 / 负值一律回退默认）。"""
    merged = dict(KILL_DEFAULTS)
    for key in KILL_DEFAULTS:
        v = params.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if v >= 0:
            merged[key] = float(v)
    return merged


# -------------------------------------------------------------- 策略双模式判据（US-001）

# race 门杀 should_stop 返回值（solve_pieces 透传为 kill_reason；kill_decisions
# 行的 rule 字段同值）。
R5_REASON = 'R5_race_gate'
# 策略双模式实测默认（PRD 2026-08-20 四重证据链；--strategy 旗标的缺省值同源）。
RACE_BUDGET_S = 180.0   # race：每 seed 求解预算（秒）
RACE_GATE_TAU = 0.5     # race：门时刻占预算比（τ_gate，(0,1) 开区间）
SE_SCREEN_S = 90.0      # se：阶段 1 每轮筛选预算（秒）
SE_EXT_S = 180.0        # se：阶段 2 冠军延长预算（秒）
# 名义记账单位（秒）：求解预算 + ~2.5s 启动开销（build_instance 取 meta + 子进程
# 冷启动），与离线对决 / ETT 仿真同口径；solver 收敛早退按名义记账（两臂对称）。
STRATEGY_STARTUP_S = 2.5
SEED_UNIT_S = 92.5      # 单轮筛选名义成本 = SE_SCREEN_S + STRATEGY_STARTUP_S
FULL_UNIT_S = 182.5     # 单轮全程名义成本 = SE_EXT_S + STRATEGY_STARTUP_S


class StrategyBudgetError(ValueError):
    """策略模式总预算不足（se：T < 全程 + 单轮筛选的名义成本）。"""


def strategy_seed_stream(cfg_seeds, n: int) -> list[int]:
    """策略模式种子流：config seeds 优先消费，不足按 ``max+1`` 递增补齐。

    **保证无重复** —— 同预算重跑同一 seed 是纯浪费（确定性重放：同 seed + 同
    time_budget 逐帧一致，零信息增益），重复 seed 只烧预算不产生新样本。config
    seeds 自带重复时去重（保序取首个）；``n`` 截断消费（config seeds 多于所需时
    取前缀）；空 config 从 1 起补齐（基线 0 = max(∅)+1 的约定）。
    """
    n = int(n)
    if n <= 0:
        return []
    stream: list[int] = []
    seen: set[int] = set()
    for s in cfg_seeds or []:
        if len(stream) >= n:
            break
        s = int(s)
        if s not in seen:
            seen.add(s)
            stream.append(s)
    nxt = max(seen) if seen else 0
    while len(stream) < n:
        nxt += 1                    # max+1 递增：必不在 seen（无重复补齐）
        seen.add(nxt)
        stream.append(nxt)
    return stream


def race_gate_seconds(budget: float, tau: float = RACE_GATE_TAU) -> float:
    """race 门时刻（秒）= 每轮预算 ``budget`` × 门占比 ``tau``（默认 180×0.5=90）。"""
    return float(budget) * float(tau)


def decide_race_kill(best_so_far: float, elapsed: float, state: dict) -> dict | None:
    """race 门杀判据（纯函数 + 显式 ``state`` 字典，无 I/O 无进程）。

    门帧 = **首帧** ``elapsed >= gate_seconds``：该 seed 的 ``best_so_far <= bar``
    即判杀（**严格破纪录才续跑**）；首 seed（``state['index'] <= 1``）无条件豁免
    （无参照值 + 锚定交付下限，与 kill 引擎 seed 1 永不 kill 同哲学）。
    ``bar`` = 历史所有 seed 门值最大值（**含被杀者** —— 弱 seed 的门值同样是
    判杀参照）；门值经 ``state['bar']`` 回写（单调只升）。**每 seed 至多一笔**：
    门帧评估后置 ``state['judged'] = True``，此后同 seed 任意帧直接返回 None
    （门后不再判）—— 与确定性重放联合保证「同 seed 永不二次续跑后再杀」。

    ``state`` 契约（调用方按 seed 重建 judged，跨 seed 线程 bar / incumbent）：
    ``seed`` / ``index``（队列序 1 起）/ ``gate_seconds`` / ``budget``（τ 分母，
    可 None）/ ``bar``（None = 尚无门值历史）/ ``incumbent``（全局最优密度，可
    None）/ ``judged``（bool）。返回决策 dict（与 kill_decisions 行同构：
    ``{t, seed, rule, d, tau, S_tau, theta, I, would_kill}``；race 重载：
    ``S_tau`` = bar 参照值、``theta`` = None）；门帧未到 / 已判过返回 None。
    """
    if state.get('judged'):
        return None                          # 门后不再判（每 seed 至多一笔）
    gate = float(state.get('gate_seconds') or 0.0)
    elapsed = float(elapsed)
    if elapsed < gate:
        return None                          # 门帧 = 首帧 elapsed >= gate_seconds
    state['judged'] = True
    d = float(best_so_far)
    bar = state.get('bar')
    if bar is None or d > bar:
        state['bar'] = d                     # bar 含被杀者 / 豁免者的门值（max 只升）
    kill = state.get('index', 1) > 1 and bar is not None and d <= bar
    budget = state.get('budget')
    inc = state.get('incumbent')
    return {
        't': round(elapsed, 3),
        'seed': int(state.get('seed', 0)),
        'rule': R5_REASON,
        'd': round(d, 6),
        'tau': None if not budget else round(elapsed / float(budget), 4),
        'S_tau': None if bar is None else round(float(bar), 6),
        'theta': None,
        'I': None if inc is None else round(float(inc), 6),
        'would_kill': kill,
    }


def se_plan(total_budget: float, screen_s: float = SE_SCREEN_S,
            ext_s: float = SE_EXT_S) -> tuple[int, float]:
    """SE 两段式规划（纯）：``(k, ext_s)`` = 阶段 1 筛选轮数 + 阶段 2 延长预算。

    名义成本口径：单轮筛选 ``screen_s + STRATEGY_STARTUP_S``（默认 = SEED_UNIT_S
    92.5）、冠军全程 ``ext_s + STRATEGY_STARTUP_S``（默认 = FULL_UNIT_S 182.5）——
    与 race 记账同口径（solver 收敛早退按名义记账）。算术：
    ``k = max(1, (T − full_unit) // seed_unit)``；``T < full_unit + seed_unit``
    （连「1 轮筛选 + 1 轮延长」的最小配置都装不下）→ ``StrategyBudgetError``
    （CLI 层以退出 1 呈现）。返回延长预算原样（180s 实测即最优：冠军类曲线
    120~180s 进平台，再砍到 120s 开始亏）。
    """
    t = float(total_budget)
    seed_unit = float(screen_s) + STRATEGY_STARTUP_S
    full_unit = float(ext_s) + STRATEGY_STARTUP_S
    if t < full_unit + seed_unit:
        raise StrategyBudgetError(
            f'预算不足：SE 模式至少需要全程 {full_unit:g}s + 单轮筛选 {seed_unit:g}s '
            f'= {full_unit + seed_unit:g}s 名义预算，当前 --time={t:g}s')
    k = max(1, int((t - full_unit) // seed_unit))
    return k, float(ext_s)


class ControllerParamsError(ValueError):
    """controller 标定参数文件加载失败（不存在 / 非 JSON / 顶层非对象）。"""


def load_controller_params(path: str | Path) -> dict:
    """读取 ``--params`` 标定参数文件 → dict（顶层必须为 JSON 对象）。

    PC-002 只做「可加载」校验并原样保存；PC-003 起消费数值阈值 + envelope +
    calibrated；坏文件在管线启动前拦下（run_config 以配置错误退出 1）。
    """
    p = Path(path)
    if not p.is_file():
        raise ControllerParamsError(f'参数文件不存在: {p.resolve()}')
    try:
        raw = json.loads(p.read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError as e:
        raise ControllerParamsError(
            f'参数文件不是合法 JSON（{p}）: 第 {e.lineno} 行第 {e.colno} 列 {e.msg}') from e
    except OSError as e:
        raise ControllerParamsError(f'参数文件不可读（{p}）: {e}') from e
    if not isinstance(raw, dict):
        raise ControllerParamsError(
            f'参数文件顶层须为 JSON 对象 {{...}}，当前为 {type(raw).__name__}')
    return raw


@dataclass
class PortfolioRun:
    """``run_serial_portfolio`` 的编排结果（run_config 消费）。

    ``last_round`` = 最后一个**已启动**轮次的 ``(第几轮, seed)``（轮次 1 起）——
    中断报错消息定位「第几轮未完成」用；未启动任何轮（空队列，理论不可达）为 None。
    """

    solves: list[dict]                 # 已完成 seed 的 solve 记录（result.json solve 数组）
    controller: 'PortfolioController'  # 控制器（incumbent / per_seed / portfolio 段数据源）
    interrupted: bool                  # Ctrl-C 中断（已完成轮产物已逐轮落盘）
    last_round: tuple[int, int] | None


class PortfolioController:
    """portfolio 状态机：incumbent banking + per-seed best + R0 停止位 + kill 引擎。

    由 ``run_serial_portfolio`` 驱动（``make_progress`` / ``make_should_stop`` /
    ``finish_seed``），也可被单测直接驱动（fake solve 注入帧序列）。控制器不做
    文件 I/O（result.json / kill_decisions.jsonl 落盘属 run_config 呈现层，经
    ``on_decision`` 回调交出决策记录）；``echo`` 只用于进度行（None = 静默，
    --quiet），``notify`` 用于不可静默的判据事件（R3 θ 衰减 —— run_config 传
    无条件 print）。

    PC-003 kill 引擎状态：``theta``（kill 门槛锚，初值 = target）、``kill_streak``
    （连续被 kill 的 seed 数，非 kill 结束即清零）、``kill_decisions``（决策记录
    副本）。``kill_mode`` 为**生效**模式：target 未给定时引擎不激活（恒 'off'，
    即便调用方传了 shadow/on）。

    PC-009：``theta0``（run 统计库校准的门槛初值，``calibrate_theta0`` 产物）——
    只作 ``self.theta`` 初值（kill 判据锚），**R0 停止条件恒用 ``self.target``
    真值**；缺省 None → θ = target（旧行为，零回归）。
    """

    def __init__(self, *, seeds, target=None, params=None, echo=None,
                 kill='shadow', time_budget=None, notify=None, on_decision=None,
                 theta0=None):
        self.seeds = [int(s) for s in seeds]
        self.target = None if target is None else float(target)
        self.params = dict(params) if params else {}
        self.incumbent: dict | None = None
        self.per_seed: list[dict] = []
        self.theta_history: list[dict] = []
        self.queue_stopped = False
        self._seed_best: dict[int, float] = {}
        self._frames_seen: dict[int, int] = {}
        self._echo = echo
        self._last_output = time.time()
        # ---- PC-003 kill 引擎 ----
        if kill not in KILL_MODES:
            raise ValueError(f'kill 模式须为 {KILL_MODES} 之一，当前为 {kill!r}')
        self.kill_mode = kill if self.target is not None else 'off'
        self.time_budget = None if time_budget is None else float(time_budget)
        # θ 初值 = target；PC-009 起可由 run 统计库校准覆盖（只影响 kill 门槛，
        # R0 停止条件恒用 target）。
        self.theta = self.target if theta0 is None else float(theta0)
        self.kill_streak = 0
        self.kill_decisions: list[dict] = []
        self._notify = notify
        self._on_decision = on_decision
        self._kp = resolve_kill_params(self.params)
        self._envelope = make_envelope(self.params)
        self._kill: dict | None = None      # 当前 seed 的 kill 判定瞬态

    # -------------------------------------------------------------- 判定

    @property
    def engaged(self) -> bool:
        """portfolio 交付语义是否激活：给了 ``--target`` 或队列 ≥2 seed。

        不激活（单 seed 且无 --target）时 result.json 写**空 portfolio 段**、
        ``best`` 保持旧语义（solve 数组 real_density 最大者）—— 与 PC-001 基线
        无旗标冒烟对拍兼容；激活时 ``best`` 升级为 incumbent（帧级全局最优）。
        """
        return self.target is not None or len(self.seeds) > 1

    # -------------------------------------------------------------- 逐帧 hooks

    def make_progress(self, seed: int, index: int = 1):
        """构造该 seed 的 ``on_progress`` 回调（banking + 进度行，逐帧调用）。

        帧序（``frame_index``）由本回调自计数 —— 与 ``solve_pieces._on_report``
        的 curve 写序一致（on_progress 每帧恰一次、先于 should_stop），故与
        ``curve_s{seed}.json`` 下标及 ``best_frame_s{seed}.json`` 的 frame_index
        对齐。心跳计时器每 seed 重置（与旧版 per-seed printer 行为一致）。
        ``index`` = 队列序号（1 起）：seed 1 永不 kill，同时重置该 seed 的 kill
        判定瞬态（R1 迟滞计时 / R2 首压缩帧旗标 / 已记决策去重集）。
        """
        seed = int(seed)
        self._frames_seen[seed] = 0
        self._last_output = time.time()
        self._kill = {'seed': seed, 'index': int(index), 'r1_since': None,
                      'r2_seen': False, 'logged': set()}

        def on_frame(report: dict) -> None:
            idx = self._frames_seen.get(seed, 0)
            self._frames_seen[seed] = idx + 1
            d = float(report.get('density', 0.0))
            seed_best = self._seed_best.get(seed)
            seed_new = seed_best is None or d > seed_best
            if seed_new:
                self._seed_best[seed] = d
            prev = self.incumbent
            inc_new = prev is None or d > prev['density']
            if inc_new:
                self.incumbent = {
                    'density': round(d, 6),
                    'width_mm': round(float(report.get('width_mm', 0.0)), 2),
                    'seed': seed,
                    'frame_index': int(idx),
                    'elapsed': round(float(report.get('elapsed', 0.0)), 3),
                    'placed_items': list(report.get('placed_items') or []),
                }
            # 跨 seed 反超才打 incumbent 行（首个 seed 的入账由 per-seed 行覆盖，
            # 单 seed 运行输出与旧版逐字一致 —— 零回归）。
            takeover = inc_new and prev is not None and prev['seed'] != seed
            if self._echo is not None:
                self._emit(report, seed, d, seed_new, takeover)

        return on_frame

    def _emit(self, report: dict, seed: int, d: float,
              seed_new: bool, takeover: bool) -> None:
        """进度行（echo 给定时）：incumbent 反超 / per-seed 新最优 / 30s 心跳。

        per-seed 行与心跳行逐字保留旧版 ``run_config._make_progress_printer``
        格式（冒烟对拍口径）；incumbent 行是 PC-002 新增。
        """
        now = time.time()
        if takeover:
            inc = self.incumbent
            self._last_output = now
            self._echo(f"[portfolio] seed {seed} frame {inc['frame_index']} 反超 → "
                       f"incumbent（全局最优）real_density={d:.2%}（原面积口径） "
                       f"width={inc['width_mm']:.0f}mm")
        elif seed_new:
            self._last_output = now
            self._echo(f"[seed {seed}] {report.get('elapsed', 0.0):7.1f}s "
                       f"{report.get('phase', ''):<14} "
                       f"real_density={d:.2%}（原面积口径新最优） "
                       f"width={report.get('width_mm', 0.0):.0f}mm")
        elif now - self._last_output >= _HEARTBEAT_SEC:
            self._last_output = now
            self._echo(f"[seed {seed}] {report.get('elapsed', 0.0):7.1f}s 心跳 "
                       f"phase={report.get('phase', '')} real_density={d:.2%}（原面积口径） "
                       f"width={report.get('width_mm', 0.0):.0f}mm")

    def make_should_stop(self, seed: int, index: int = 1):
        """构造该 seed 的 ``should_stop`` 回调（R0 + kill 判定，仅 --target 给定时挂载）。

        触发帧已先经 ``on_progress`` 入账（solve_pieces 的调用序：curve →
        best_frame → on_progress → should_stop），故 R0 / kill 帧**必在 incumbent
        候选内** —— 达标即停与被 kill 的 seed 交付的都是「全局最好帧」。

        判定序：R0 恒先且恒用 ``--target`` 真值（θ 衰减不影响停止条件）；随后
        kill 引擎（``kill_mode == 'off'`` 时不评估）—— shadow 只记决策不终止
        求解，on 才把 kill 判据作为 should_stop 返回值真正触发。
        """

        def should_stop(report: dict):
            if self.target is not None and float(report.get('density', 0.0)) >= self.target:
                self.queue_stopped = True
                return R0_REASON
            if self.kill_mode == 'off':
                return False
            reason = self._evaluate_kill(report, seed, index)
            if reason and self.kill_mode == 'on':
                return reason
            return False

        return should_stop

    # -------------------------------------------------------------- kill 引擎

    def _kill_state(self, seed: int, index: int) -> dict:
        """当前 seed 的 kill 判定瞬态（make_progress 已重置；直接驱动时惰性重建）。"""
        st = self._kill
        if st is None or st.get('seed') != seed or st.get('index') != int(index):
            st = {'seed': int(seed), 'index': int(index), 'r1_since': None,
                  'r2_seen': False, 'logged': set()}
            self._kill = st
        return st

    def _evaluate_kill(self, report: dict, seed: int, index: int) -> str | None:
        """R1/R2 逐帧判定（纯函数规则 + 控制器状态 θ / 迟滞计时）。

        ``index`` = 队列序号（1 起）：**seed 1 永不 kill**（锚定交付下限 + 校准
        样本）。τ = elapsed / time_budget（预算缺失 / 非正 → 不可评估）；d = 该
        seed best-so-far、I = incumbent（均已在 on_progress 先行更新）。返回触发
        规则名（R1 优先于 R2），未触发返回 None —— shadow 模式由调用方只记不杀。
        """
        if index <= 1:
            return None
        tb = self.time_budget
        if not tb or tb <= 0:
            return None
        elapsed = float(report.get('elapsed', 0.0))
        tau = elapsed / tb
        d = self._seed_best.get(seed)
        if d is None:
            return None
        st = self._kill_state(seed, index)
        kp = self._kp
        i_val = self.incumbent['density'] if self.incumbent is not None else None

        reason: str | None = None
        s_tau: float | None = None
        # R1 包络 kill：τ > τ0 且 d < S(τ) − m 持续 W 秒（无标定 envelope → 整体禁用）。
        if self._envelope is not None and tau > kp['tau0']:
            s_tau = self._envelope(tau)
            if r1_below_envelope(d, s_tau, kp['m']):
                if st['r1_since'] is None:
                    st['r1_since'] = elapsed       # 进入包络下方，起表
                elif elapsed - st['r1_since'] >= kp['W']:
                    reason = R1_REASON             # 持续 W 秒仍 below → kill
            else:
                st['r1_since'] = None              # 追平包络 → 迟滞计时清零
        # R2 压缩期判决：首帧 compressing 一次性评估（此后不再复审）。
        if reason is None and not st['r2_seen'] \
                and str(report.get('phase', '')) == 'compressing':
            st['r2_seen'] = True
            if r2_below_threshold(d, kp['uplift_q95'], self.theta, i_val, kp['epsilon']):
                reason = R2_REASON

        if reason is None:
            return None
        if (seed, reason) not in st['logged']:
            st['logged'].add((seed, reason))       # 每 (seed, rule) 首次触发记一条
            self._record_decision(seed, elapsed, tau, d, s_tau, i_val, reason)
        return reason

    def _record_decision(self, seed: int, elapsed: float, tau: float, d: float,
                         s_tau: float | None, i_val: float | None, reason: str) -> None:
        """kill 决策记录（PRD 字段 ``{t, seed, rule, d, τ, S(τ), θ, I, would_kill}``
        的 ASCII 键名版）→ ``kill_decisions`` 副本 + ``on_decision`` 回调（run_config
        写 ``run_dir/kill_decisions.jsonl``）。"""
        entry = {
            't': round(elapsed, 3),
            'seed': int(seed),
            'rule': reason,
            'd': round(float(d), 6),
            'tau': round(tau, 4),
            'S_tau': None if s_tau is None else round(float(s_tau), 6),
            'theta': None if self.theta is None else round(float(self.theta), 6),
            'I': None if i_val is None else round(float(i_val), 6),
            'would_kill': True,
        }
        self.kill_decisions.append(entry)
        if self._on_decision is not None:
            self._on_decision(dict(entry))

    def _notify_line(self, msg: str) -> None:
        """判据事件输出：``notify`` 优先（run_config 传无条件 print，--quiet 也打），
        缺省回落 ``echo``，两者皆无则静默（theta_history 仍落 result.json）。"""
        sink = self._notify if self._notify is not None else self._echo
        if sink is not None:
            sink(msg)

    # -------------------------------------------------------------- 逐 seed 收尾

    def finish_seed(self, rec: dict) -> None:
        """seed 求解返回后入账 per_seed（killed / kill_reason 由 rec 带回）。

        PC-003 R3 θ 衰减：连续 ≥ m_streak 个 seed 被 kill 规则（R1/R2）淘汰 →
        ``θ := min(θ, I + δ)``（单调只降，防 incumbent 回升抬门槛）—— 只降 kill
        门槛，**R0 停止条件恒用 --target 真值**；衰减经 ``notify`` 打一行 + 记
        ``theta_history``（不静默改判据）。非 kill 结束（跑满 / R0 / 异常）清零
        连杀计数。
        """
        seed = int(rec['seed'])
        best = self._seed_best.get(seed)
        self.per_seed.append({
            'seed': seed,
            'killed': bool(rec.get('killed', False)),
            'kill_reason': rec.get('kill_reason') or None,
            'best_density': None if best is None else round(best, 6),
            'elapsed': rec.get('elapsed'),
        })
        if self.kill_mode == 'off':
            return
        if rec.get('killed') and rec.get('kill_reason') in (R1_REASON, R2_REASON):
            self.kill_streak += 1
        else:
            self.kill_streak = 0
        if self.kill_streak >= self._kp['m_streak'] and self.incumbent is not None:
            i_val = self.incumbent['density']
            new_theta = min(self.theta, i_val + self._kp['delta'])
            if new_theta < self.theta:
                old = self.theta
                self.theta = new_theta
                self.theta_history.append({
                    'after_seed': seed,
                    'kill_streak': self.kill_streak,
                    'theta_old': round(old, 6),
                    'theta': round(new_theta, 6),
                    'incumbent': round(i_val, 6),
                })
                self._notify_line(
                    f'[portfolio] 连杀 {self.kill_streak} 个 seed → θ 衰减 '
                    f'{old:.2%} → {new_theta:.2%}（= incumbent {i_val:.2%} + δ，'
                    f'只降 kill 门槛；R0 停止条件恒用 --target）')

    # -------------------------------------------------------------- 交付

    def portfolio_section(self) -> dict:
        """result.json 的 ``portfolio`` 段。

        激活：``{target, incumbent, per_seed, theta_history, kill_mode}``（incumbent
        含完整 ``placed_items`` 布局；theta_history 记 R3 θ 衰减事件；kill_mode =
        生效模式）。不激活（单 seed 无 --target）：全空段 + ``kill_mode='off'``
        （引擎未激活），best 走旧语义 —— 无旗标冒烟对拍兼容。
        """
        if not self.engaged:
            return {'target': None, 'incumbent': None, 'per_seed': [],
                    'theta_history': [], 'kill_mode': 'off'}
        return {
            'target': self.target,
            'incumbent': dict(self.incumbent) if self.incumbent is not None else None,
            'per_seed': [dict(e) for e in self.per_seed],
            'theta_history': list(self.theta_history),
            'kill_mode': self.kill_mode,
        }

    def best_record(self, solves: list[dict]) -> dict:
        """result.json 的 ``best``：激活且已见帧 → incumbent（帧级全局最优，含完整
        placed_items）；否则旧语义（solve 数组 real_density 最大者，并列取先执行
        者）。solves 为空时由调用方保证不进入本分支。"""
        if self.engaged and self.incumbent is not None:
            return self.incumbent
        return max(solves, key=lambda r: r['real_density'])


def run_serial_portfolio(cfg, run_dir, *, controller: PortfolioController,
                         time_budget: int | None = None, solve=None,
                         on_seed_start=None, on_seed_done=None,
                         solver_opts_for=None) -> PortfolioRun:
    """经控制器串行跑完 seed 队列（run_config 现有串行循环的转发实现）。

    每轮：R0 已触发则剩余 seed 不启动（AC：per_seed 对未启动 seed 无记录）→
    ``on_seed_start(i, seed)``（轮次头打印）→ ``solve_pieces``（on_progress 挂
    banking/进度、仅 ``--target`` 给定时挂 should_stop —— 无旗标调用形与旧版
    完全一致）→ ``finish_seed`` 入账 → ``on_seed_done(rec)``（run_config 逐轮
    重写 result.json）。Ctrl-C 捕获为 ``interrupted=True``（求解异常向上传播给
    呈现层）；无论何种终止，已收帧均已入账 incumbent（中断交付不变量）。

    Parameters
    ----------
    controller : PortfolioController
        由调用方构造并持有（run_config 需要在逐轮回调里读它写 result.json）。
    solve : callable | None
        单 seed 求解函数（缺省 ``pipeline.solve_pieces``；测试注入 fake solve）。
    on_seed_start / on_seed_done : callable | None
        每轮开始 / 完成回调（打印轮次头 / 逐轮落盘）。
    solver_opts_for : callable(index, seed) -> dict | None | None
        US-006 求解旋钮解析器（``run_config`` 由 ``--solver-opts`` / ``--rotate-opts``
        构造）：``index`` 为 **0 起队列序**（轮换池下标口径），返回非空 dict 时以
        ``solver_opts=...`` 传入该轮 solve（None / 空档 = 现行行为）。缺省 None
        全程不加该键（无旗标调用形与旧版一致，fake solve 兼容）。
    """
    if solve is None:
        solve = solve_pieces
    # kill 引擎的 τ = elapsed / time_budget：直接驱动（单测）未显式给预算时在此
    # 补齐（--time 覆盖 > cfg.time；都缺失则保持 None → 引擎不可评估、恒不 kill）。
    if controller.time_budget is None:
        eff = time_budget if time_budget is not None else (
            cfg.time if cfg is not None else None)
        if eff:
            controller.time_budget = float(eff)
    solves: list[dict] = []
    interrupted = False
    last_round: tuple[int, int] | None = None
    for i, seed in enumerate(controller.seeds, start=1):
        if controller.queue_stopped:           # R0：剩余队列不启动（R4 耗尽则自然结束）
            break
        last_round = (i, seed)
        if on_seed_start is not None:
            on_seed_start(i, seed)
        try:
            kwargs = {'seed': seed, 'time_budget': time_budget,
                      'on_progress': controller.make_progress(seed, index=i)}
            if controller.target is not None:
                kwargs['should_stop'] = controller.make_should_stop(seed, index=i)
            if solver_opts_for is not None:
                # i 为 1 起队列序 → 转 0 起轮换下标（pool[seed_index % len] 口径）。
                opts = solver_opts_for(i - 1, seed)
                if opts:
                    kwargs['solver_opts'] = dict(opts)
            rec = solve(cfg, run_dir, **kwargs)
        except KeyboardInterrupt:
            interrupted = True
            break
        solves.append(rec)
        controller.finish_seed(rec)
        if on_seed_done is not None:
            on_seed_done(rec)
    return PortfolioRun(solves=solves, controller=controller,
                        interrupted=interrupted, last_round=last_round)

