"""串行 seed portfolio 控制器（PC-002）：incumbent banking + R0 达标即停 + R4 队列耗尽。

``run_config`` 的多 seed 串行循环自 PC-002 起**经本控制器转发**（不再裸调
``solve_pieces``）：控制器是纯 Python 状态机，持有三类状态 ——
incumbent（全局最优帧）、per-seed best（各 seed 最优帧密度）、队列停止位
（R0 触发后剩余 seed 不再启动）。

规则（PC-002 落地 R0/R4，R1~R3 kill 引擎在 PC-003 扩展）：

  - **incumbent banking（FR-2）**：每帧 real 口径 ``density`` **严格大于**全局最优
    即入账（来源 ``seed`` / ``frame_index`` / ``elapsed`` / ``width_mm`` /
    ``placed_items`` 完整布局一并记录）。被 kill / 中途停止的 seed 的最优帧同样
    参与全局最优 —— 修复旧版 ``best`` 只看 per-seed 终值（final 解）的盲区；
    任何中断（kill / Ctrl-C / 队列耗尽）交付物都是过程中的最好帧。
  - **R0 达标即停**：``--target`` 给定时，任一帧 ``density >= target`` → 对当前
    seed 触发 ``should_stop``（终止链路杀子进程，当前 seed 交付 best-so-far 帧
    ``killed=True``），并**终止剩余队列**（后续 seed 不再启动）。R0 恒用
    ``--target`` 真值（θ 衰减只影响 kill 门槛不影响停止条件，PC-003）。
  - **R4 队列耗尽**：全部 seed 跑满预算 → 正常结束，交付 incumbent。

``--params``（controller_params.json，PC-004 标定产物）经 ``load_controller_params``
加载为 dict 传入控制器 —— PC-002 仅校验可加载（存在 / 合法 JSON 对象）并保存，
阈值消费在 PC-003（R1~R3）接入；7 键 config schema 不动。

进度口径（``echo`` 给定时；``run_config`` 传 ``None if quiet else print``）：
沿用「原面积口径新最优才打 + 30s 心跳」—— per-seed 新最优行与心跳行**逐字保留**
旧版格式（零回归），新增**跨 seed 反超**时的 incumbent 行（同 seed 自我刷新不打，
信息已被 per-seed 行覆盖；单 seed 运行输出与旧版逐字一致）。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .pipeline import solve_pieces

__all__ = ['R0_REASON', 'ControllerParamsError', 'PortfolioController',
           'PortfolioRun', 'load_controller_params', 'run_serial_portfolio']

# R0 触发的 should_stop 返回值（solve_pieces 透传为 kill_reason）。
R0_REASON = 'R0_target_reached'
# 长时求解心跳间隔（秒）—— 与 run_config 旧版 per-seed printer 同值。
_HEARTBEAT_SEC = 30.0


class ControllerParamsError(ValueError):
    """controller 标定参数文件加载失败（不存在 / 非 JSON / 顶层非对象）。"""


def load_controller_params(path: str | Path) -> dict:
    """读取 ``--params`` 标定参数文件 → dict（顶层必须为 JSON 对象）。

    PC-002 只做「可加载」校验并原样保存（阈值默认值在 PC-003 定义、PC-004 产物
    覆盖）；坏文件在管线启动前拦下（run_config 以配置错误退出 1）。
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
    """portfolio 状态机：incumbent banking + per-seed best + R0 停止位。

    由 ``run_serial_portfolio`` 驱动（``make_progress`` / ``make_should_stop`` /
    ``finish_seed``），也可被单测直接驱动（fake solve 注入帧序列）。控制器不做
    I/O（result.json 落盘 / stdout 汇总属 run_config 呈现层），``echo`` 只用于
    进度行（None = 静默，--quiet）。
    """

    def __init__(self, *, seeds, target=None, params=None, echo=None):
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

    def make_progress(self, seed: int):
        """构造该 seed 的 ``on_progress`` 回调（banking + 进度行，逐帧调用）。

        帧序（``frame_index``）由本回调自计数 —— 与 ``solve_pieces._on_report``
        的 curve 写序一致（on_progress 每帧恰一次、先于 should_stop），故与
        ``curve_s{seed}.json`` 下标及 ``best_frame_s{seed}.json`` 的 frame_index
        对齐。心跳计时器每 seed 重置（与旧版 per-seed printer 行为一致）。
        """
        seed = int(seed)
        self._frames_seen[seed] = 0
        self._last_output = time.time()

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

    def make_should_stop(self, seed: int):
        """构造该 seed 的 ``should_stop`` 回调（R0 达标即停，仅 --target 给定时挂载）。

        触发帧已先经 ``on_progress`` 入账（solve_pieces 的调用序：curve →
        best_frame → on_progress → should_stop），故 R0 帧**必在 incumbent 候选
        内** —— 达标即停的 seed 交付的是「达标帧前后的全局最好帧」。
        """

        def should_stop(report: dict):
            if self.target is not None and float(report.get('density', 0.0)) >= self.target:
                self.queue_stopped = True
                return R0_REASON
            return False

        return should_stop

    # -------------------------------------------------------------- 逐 seed 收尾

    def finish_seed(self, rec: dict) -> None:
        """seed 求解返回后入账 per_seed（killed / kill_reason 由 rec 带回）。"""
        seed = int(rec['seed'])
        best = self._seed_best.get(seed)
        self.per_seed.append({
            'seed': seed,
            'killed': bool(rec.get('killed', False)),
            'kill_reason': rec.get('kill_reason') or None,
            'best_density': None if best is None else round(best, 6),
            'elapsed': rec.get('elapsed'),
        })

    # -------------------------------------------------------------- 交付

    def portfolio_section(self) -> dict:
        """result.json 的 ``portfolio`` 段。

        激活：``{target, incumbent, per_seed, theta_history}``（incumbent 含完整
        ``placed_items`` 布局；theta_history 由 PC-003 R3 填充，PC-002 恒空）。
        不激活（单 seed 无 --target）：全空段（target=None、incumbent=None、
        per_seed=[]），best 走旧语义 —— 无旗标冒烟对拍兼容。
        """
        if not self.engaged:
            return {'target': None, 'incumbent': None, 'per_seed': [], 'theta_history': []}
        return {
            'target': self.target,
            'incumbent': dict(self.incumbent) if self.incumbent is not None else None,
            'per_seed': [dict(e) for e in self.per_seed],
            'theta_history': list(self.theta_history),
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
                         on_seed_start=None, on_seed_done=None) -> PortfolioRun:
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
    """
    if solve is None:
        solve = solve_pieces
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
                      'on_progress': controller.make_progress(seed)}
            if controller.target is not None:
                kwargs['should_stop'] = controller.make_should_stop(seed)
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

