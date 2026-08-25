r"""ms-run-config 入口 —— 一条命令跑完「commit → 求解」，无需浏览器即可评估配置。

用法（console_script 或 ``python -m`` 等价）::

    ms-run-config <config.json> [--name RUN_NAME] [--time N] [--quiet]
                  [--target P] [--params controller_params.json]
                  [--kill shadow|off|on]
                  [--solver-opts '{"exploration_pct":0.7}' | --rotate-opts]
                  [--lns [--lns-time 30] [--lns-rounds 5]]
                  [--strategy [se|race] --time 总预算
                    [--se-screen 90] [--se-extend 180]
                    [--race-budget 180] [--race-gate 0.5]]
    python -m materialsorting.cli.run_config <config.json> --time 5

流程：``load_config``（9 键 schema 校验）→ ``new_run_dir``（时间戳目录保留历史）
→ ``commit_from_config``（切片 + intermediate 落 run_dir，**仅一次**）→ 逐 ``seeds``
元素**经 ``cli.portfolio`` 控制器串行** ``solve_pieces``（每轮重建 build_instance，
复用同一份 commit 产物）→ ``result.json``（config 回显 + commit 摘要 + solve 指标
数组 + **best** + **portfolio** 段）→ stdout 末行人类可读汇总。

多 seed 语义（US-004；PC-002 起经 portfolio 控制器转发）：seeds 列表 ≥2 个时自动
串行逐 seed 求解并汇总最优；种子不要求连续（``[0, 42]`` 合法）；**只做串行，不做
并行**（任一时刻至多 1 个求解进程）。多 seed 启动即打印预计总时长
（``len(seeds) × time``，不含解析/切片）。

PC-002 portfolio 语义（``--target`` / ``--params`` 旗标，7 键 config schema 不动）：

  - **incumbent banking**：逐帧入账全局最优（含被 kill / 中途停止 seed 的最优帧，
    修复旧 best 只看 per-seed 终值的盲区）；``--target`` 给定或 seeds ≥2 时
    ``best`` 升级为 incumbent（帧级全局最优，含完整 ``placed_items``），result.json
    新增 ``portfolio`` 段（target / incumbent / per_seed / theta_history / kill_mode）。
  - **R0 达标即停**：``--target <0..1>``（原面积口径）任一帧达标 → 当前 seed 被
    stop（交付 best-so-far 帧）+ 剩余队列不启动，退出码仍 0；缺省不启用。
  - **单 seed 无 --target**：空 portfolio 段 + ``best`` 保持旧语义（solve 数组
    real_density 最大者）—— 与 PC-001 基线无旗标冒烟对拍兼容。
  - ``--params``：controller 标定参数 JSON（PC-004 产物）；数值阈值（tau0/W/m/
    epsilon/delta/m_streak/uplift_q95）+ envelope（R1 包络 S(τ)）+ calibrated
    在此消费，坏文件按配置错误退出 1。

PC-003 kill 引擎（``--kill shadow|off|on``，默认 **shadow**；仅 ``--target`` 给定时
激活 —— θ 初值 = target 是判据锚点，无 target 引擎恒 off）：

  - **shadow**（默认）：R1/R2 规则照常逐帧评估，但**绝不终止求解**（should_stop
    仅由 R0 触发）；kill 决策逐条 append ``run_dir/kill_decisions.jsonl``
    （``{t, seed, rule, d, tau, S_tau, theta, I, would_kill}``，每 (seed, rule)
    首次触发记一条）—— PC-005 仿真器据此统计 would-kill 假阳性。
  - **on**：kill 判据真正触发 should_stop（必死 seed 提前淘汰省出预算）。**要求
    标定参数就绪**（``--params`` 文件含 ``"calibrated": true``），否则**自动降级
    shadow 并 warn**（stderr）—— 未标定的包络/uplift 不可信，不许真杀。
  - **off**：引擎不评估不落盘。
  - seed 1（队列首）永不 kill（锚定交付下限 + 校准样本）；R0 停止条件恒用
    ``--target`` 真值（R3 θ 衰减只降 kill 门槛）；θ 衰减时经 notify 打一行
    （``--quiet`` 也打，不静默改判据）。

PC-006 solver_opts 透传与配置轮换（``--solver-opts`` / ``--rotate-opts`` 互斥，
7 键 config schema 与 WS 协议均不动、web 前端零改动）：

  - ``--solver-opts '<JSON>'``：spyrrow 求解旋钮（白名单 ``exploration_pct`` /
    ``quadtree_depth`` / ``num_workers``，越界 clamp、非法忽略 —— 清洗在
    ``web.solver._normalize_solver_opts`` 单一真相源），**全 seed 生效**；
  - ``--rotate-opts``（默认 OFF）：按内置轮换池 ``SOLVER_OPTS_POOL`` 逐 seed 取
    档（``pool[seed_index % len]``，seed_index 为 0 起队列序；池首空档 = 默认
    行为）—— 不同探索/压缩配比 + 四叉树深度让样本去相关、上尾更易被摸到；
  - 两旗标同给 / JSON 坏串 / 非 JSON 对象 → 配置错误退出 1；旗标未给时
    solve 调用形与 PC-001 基线一致（result.json config 段不加新键，冒烟对拍
    零回归）；给了旗标则 config 段回显 ``solver_opts`` / ``rotate_opts``。

PC-008 LNS 后处理（``--lns [--lns-time 30] [--lns-rounds 5]``，PC-007 核心循环
接入编排 —— 无需手工二次 ``ms-lns``）：

  - portfolio 跑完后（含 R0 提前停路径 —— 达标解同样可再压宽度）对最优布局
    （engaged：``portfolio.incumbent``；单 seed 无旗标的旧语义 best：回退
    ``best_frame_s{seed}.json`` 边车）跑 ``lns.postprocess_run_dir``（与 ms-lns
    CLI 同一条代码路径），进度行走 ``--quiet`` 抑制、前后两行汇总恒打；
  - **严格更优才回写** result.json：incumbent 的 density / width_mm /
    placed_items 更新（seed / frame_index / elapsed 保持来源帧出处）+ 新增
    ``lns`` 段（前后对比 / Δ / 轮次明细 / 复检，placed_items 不入段控体积）；
    不优则 result.json **逐字节不变**（LNS 明细仍写 ``result_lns.json`` +
    ``lns_compare.svg``）—— 回写只在 LNS 完成判定后一次性整体重写，Ctrl-C 不
    留半写的 result.json（已完成轮次保底落 result_lns.json，退出码 130）；
  - 从属旗标 ``--lns-time`` / ``--lns-rounds`` 须与 ``--lns`` 同给（单独给出 =
    配置错误退出 1，不留空 run_dir）；值域同 ms-lns（≥1）。LNS 环节自身输入
    错误（如旧 run 无布局）降级为 stderr warn 跳过 —— 后处理失败不否定已完成的
    求解交付物（退出码仍 0）。

PC-009 run 统计库与 θ₀ 校准（``--target`` 模式的 kill 门槛按历史可达性起跑）：

  - **写侧**：run 结束（exit 0 收口的完成路径，含 R0 提前停 / kill 路径；Ctrl-C
    / 求解失败不沉淀 —— 不完整数据会污染历史 max）追加一行 JSONL 到
    ``out/run_stats.jsonl``（``paths.RUN_STATS_JSONL``）：``{ts, source, sizes,
    class_key, seeds, target, best_density, n_killed, elapsed_total, config:
    {time, per_type, quantities}}``；``class_key`` = sha1(source + sizes +
    quantities + per_type) 短哈希（``portfolio.run_stats_class_key`` 单一真相
    源）。写盘失败 try/except 只 stderr warn，不阻塞主流程（统计沉淀是旁路
    产物，绝不否定求解交付物）。
  - **读侧**：``--target`` 给定时启动即读统计库 —— 当前 class_key 命中且 ≥5 条
    记录 → ``θ₀ = min(target, 历史最大 best_density + 0.003)``（历史最高 89.6%
    的组合不再从 90 起步），否则 θ₀ = target；θ₀ 经 ``PortfolioController(
    theta0=...)`` 只作 kill 门槛初值，**R0 停止条件恒用 ``--target`` 真值**。
    校准说明行 ``--quiet`` 也打（判据变更不静默，同 R3 θ 衰减口径）。

US-002 策略双模式（``--strategy [se|race]``，给定总预算拿更高利用率）：

  - ``--strategy``（裸旗标 = race = 方案 B 门杀）/ ``--strategy se``（方案 A
    筛延）；策略模式 ``--time N`` = **总预算秒数且必填**（缺省退出 1）。4 个
    参数旗标：``--se-screen 90`` / ``--se-extend 180`` / ``--race-budget 180``
    / ``--race-gate 0.5``（(0,1) 开区间），须与 ``--strategy`` 同给。
  - **race（默认）**：每 seed 按 ``--race-budget`` 预算启动，门时刻（预算 ×
    ``--race-gate``）处严格破纪录才续跑（US-001 ``decide_race_kill``：首 seed
    豁免、bar 含被杀者、每 seed 至多一笔）；判杀走既有 terminate 链交付
    best-so-far，门杀行 ``--quiet`` 也打。名义记账（预算 + ~2.5s 启动开销）：
    被杀记门段、跑满记全程，启动条件 ``spent + 门段 <= T``（被杀省出的预算由
    串行队列自然吸收）。
  - **se**：阶段 1 ``k`` 轮 ``--se-screen`` 串行筛选 + 阶段 2 冠军（solve 记录
    ``real_density`` argmax）同 seed 以 ``--se-extend`` 预算再跑一轮 —— 延长
    轮产物写 ``curve_s{seed}_ext.json`` / ``best_frame_s{seed}_ext.json``（防
    覆盖筛选产物），solve 条目附 ``phase: 'extension'``。
  - 两模式被门杀 / 被筛 seed 的最优帧照常入 incumbent；策略模式下 R1/R2 不评
    估、θ 不维护；``--target`` 共存时 R0 达标即停优先于模式继续。race 决策
    逐条写 ``run_dir/kill_decisions.jsonl``（复用 schema：``S_tau`` = bar 参照
    值、``theta`` = null，README 注明重载）；预算不足（T < 最小配置）退出 1。
  - **R1 增量（US-004 web 桥接前置）**：策略模式 commit 完成后、首轮求解前写
    ``run_dir/strategy.json`` ``{mode, total_budget, planned_seeds, race|se,
    started_at}`` —— run 一启动即暴露模式 / 计划轮数 / 种子流（result.json
    要等首个 seed 完成才首次落盘，race 默认下前 ~180s 无信息）。
  - 无 ``--strategy`` 时行为与 result.json 与现版**逐字节一致**（零回归红线，
    portfolio 段不加 mode 键、config 段不加 strategy 键）。

run_name 缺省 = 配置文件 stem，``--name`` 覆盖；Windows 非法文件名字符
（``<>:"/\|?*`` 与控制字符）替换 ``_``，清洗后为空回退 ``run``。

退出码：0 成功（含 R0 提前停）；1 配置或管线失败（ConfigError / --target 越界 /
--params 坏文件 / commit 抛错）；2 求解失败（solve 抛错 / placed != Σdemand）；
130 Ctrl-C 中断（已完成轮产物已落盘）。

PC-001 落盘口径（逐 seed 写，不攒内存）：每轮 ``solve_pieces`` 完成即把当前
``result.json`` 重写一次（config 回显 + commit 摘要 + 已完成 solve 数组 + best +
portfolio 段），Ctrl-C / 崩溃时 run_dir 内已持有已完成轮的完整产物（curve_s*/
best_frame_s* 由 ``solve_pieces`` 逐帧写，result.json 由本入口逐轮写；
kill_decisions.jsonl 由决策回调逐条 flush 写）。

进度口径（``--quiet`` 全部抑制，仅保留最终汇总与终局事件；行格式由
``cli.portfolio`` 控制器统一实现）：「原面积口径新最优」帧 + 30s 心跳 + 跨 seed
反超的 incumbent 行 + per-seed 轮次头（多 seed 或 ``--target`` 给定时打印）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from .. import paths
from .config import ConfigError, load_config
from .lns import LnsError, postprocess_run_dir
from .pipeline import commit_from_config, new_run_dir, solve_pieces
from .portfolio import (KILL_MODES, RACE_BUDGET_S, RACE_GATE_TAU, SE_EXT_S,
                        SE_SCREEN_S, STRATEGY_MODES, THETA0_MARGIN,
                        StrategyBudgetError, ControllerParamsError,
                        PortfolioController, calibrate_theta0,
                        load_controller_params, load_run_stats, race_plan,
                        run_serial_portfolio, run_stats_class_key, se_plan,
                        strategy_seed_stream)

__all__ = ['SOLVER_OPTS_POOL', 'rotation_opts_for', 'main']

# Windows 文件名非法字符 + 控制字符（run_name 进目录名前清洗）。
_ILLEGAL_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_EXIT_OK = 0
_EXIT_CONFIG_OR_COMMIT = 1
_EXIT_SOLVE = 2
_EXIT_INTERRUPT = 130          # Ctrl-C（SIGINT 惯用码）：已完成轮产物已落盘


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog='ms-run-config',
        description='配置驱动排料：一条命令跑完「commit → 求解」，输出原面积口径利用率',
    )
    p.add_argument('config', help='配置文件路径（9 键 JSON schema，见 data/configs/）')
    p.add_argument('--name', metavar='RUN_NAME',
                   help='覆盖 run_name（缺省 = 配置文件 stem，非法字符清洗）')
    p.add_argument('--time', type=int, metavar='N',
                   help='覆盖单轮求解时长（秒）；策略模式（--strategy）= 总预算秒数'
                        '且必填（race 门杀省出的预算再投资 / se 筛选+延长同口径记账）；'
                        'result.json 回显生效值')
    p.add_argument('--quiet', action='store_true',
                   help='静默：不打进度帧与心跳（最终汇总仍输出）')
    p.add_argument('--target', type=float, metavar='P',
                   help='R0 达标即停阈值（0..1 比例，原面积口径 density ≥ target 即'
                        '停当前 seed 并终止剩余队列）；缺省不启用 R0')
    p.add_argument('--params', metavar='FILE',
                   help='controller 标定参数 JSON（PC-004 产物）：覆盖 kill 阈值默认值'
                        '（tau0/W/m/epsilon/delta/m_streak/uplift_q95）+ envelope 包络'
                        ' S(τ) + calibrated 开关；仅校验可加载，坏文件退出 1')
    p.add_argument('--kill', choices=KILL_MODES, default=None,
                   help='kill 规则引擎模式（PC-003，默认 shadow）：shadow 只记 '
                        'run_dir/kill_decisions.jsonl 不真正 kill；on 真正淘汰必死 seed'
                        '（需 --params 标定就绪 calibrated: true，否则自动降级 shadow）；'
                        'off 关闭。引擎仅 --target 给定时激活，seed 1 永不 kill；'
                        '与 --strategy 显式同给退出 1（策略模式判据内建）')
    p.add_argument('--solver-opts', metavar='JSON',
                   help='spyrrow 求解旋钮 JSON 对象（PC-006，全 seed 生效）：'
                        '{"exploration_pct":0.6, "quadtree_depth":5, "num_workers":4}；'
                        '白名单外键忽略、越界 clamp；与 --rotate-opts 互斥')
    p.add_argument('--rotate-opts', action='store_true',
                   help='逐 seed 按内置轮换池轮换 solver_opts（pool[队列序 %% 池长]，'
                        '池首空档=默认行为；样本去相关）；与 --solver-opts 互斥')
    p.add_argument('--lns', action='store_true',
                   help='portfolio 结束后对最优布局（incumbent）跑 LNS 波段重排后'
                        '处理（PC-008）：严格更优才回写 result.json（incumbent 更新 + '
                        'lns 段），不优则 result.json 不变（明细仍写 result_lns.json）')
    p.add_argument('--lns-time', type=int, default=None, metavar='N',
                   help='LNS 总预算（秒，默认 30；须与 --lns 同给）')
    p.add_argument('--lns-rounds', type=int, default=None, metavar='N',
                   help='LNS 最大轮数（默认 5；须与 --lns 同给）')
    p.add_argument('--strategy', nargs='?', const='race', default=None,
                   metavar='[se|race]',
                   help='策略双模式（US-002，给定总预算拿更高利用率）：裸旗标 = '
                        'race 门杀（方案 B，默认）= 每 seed 全预算启动、门时刻严格'
                        '破纪录才续跑（弱 seed 提前淘汰省出预算再投资）；se = 筛延'
                        '（方案 A）= k 轮短筛选 + 冠军 seed 全预算再战。策略模式 '
                        '--time = 总预算秒数（必填）；20min 起比均分稳定 +0.2pt')
    p.add_argument('--se-screen', type=int, default=None, metavar='N',
                   help='se 阶段 1 每轮筛选预算（秒，默认 90；须与 --strategy 同给）')
    p.add_argument('--se-extend', type=int, default=None, metavar='N',
                   help='se 阶段 2 冠军延长预算（秒，默认 180；须与 --strategy 同给）')
    p.add_argument('--race-budget', type=int, default=None, metavar='N',
                   help='race 每 seed 求解预算（秒，默认 180；须与 --strategy 同给）')
    p.add_argument('--race-gate', type=float, default=None, metavar='TAU',
                   help='race 门时刻占预算比（默认 0.5，(0,1) 开区间；须与 '
                        '--strategy 同给）')
    return p.parse_args(argv)


def _clean_run_name(raw: str) -> str:
    """run_name 清洗：非法文件名字符 → ``_``，去首尾空白/点；清洗后为空回退 ``run``。"""
    cleaned = _ILLEGAL_NAME_RE.sub('_', raw).strip().strip('. ')
    return cleaned or 'run'


# PC-006 --rotate-opts 内置轮换池：探索/压缩配比（exploration_pct）与四叉树深度
# （quadtree_depth）交叉取档 —— 不同 seed 的搜索行为去相关，上尾更易被摸到。池首
# None 空档 = 默认行为（spyrrow total 模式自动 80/20 分段），与无旗标冒烟同形；
# 修改池内容属于实验参数变更，档数（len）变化会改变轮换周期。
SOLVER_OPTS_POOL: list[dict | None] = [
    None,                                            # 空档：默认行为（80/20 自动分段）
    {'exploration_pct': 0.9},                        # 长探索档
    {'exploration_pct': 0.6, 'quadtree_depth': 5},   # 中探索 + 深四叉树
    {'exploration_pct': 0.5, 'quadtree_depth': 3},   # 短探索 + 浅四叉树
]


def rotation_opts_for(seed_index: int) -> dict | None:
    """轮换取档：``SOLVER_OPTS_POOL[seed_index % len]``（seed_index 为 0 起队列序）。"""
    return SOLVER_OPTS_POOL[int(seed_index) % len(SOLVER_OPTS_POOL)]


def _lns_section(out: dict) -> dict:
    """PC-008 result.json 的 ``lns`` 段：前后对比 + 轮次明细 + 复检。

    ``out`` = ``lns.postprocess_run_dir`` 返回的写盘 payload。``placed_items``
    不入段（改进布局在 incumbent / ``result_lns.json``，result.json 控体积）；
    段内记产物文件名与 base_seed 便于溯源。
    """
    src = out.get('source') or {}
    return {
        'time_budget_sec': out['time_budget_sec'],
        'rounds_requested': out['rounds_requested'],
        'rounds_executed': out['rounds_executed'],
        'stop_reason': out['stop_reason'],
        'interrupted': out['interrupted'],
        'elapsed': out['elapsed'],
        'band_width_mm': out['band_width_mm'],
        'improved': out['improved'],
        'before': out['before'],
        'after': out['after'],
        'delta': out['delta'],
        'recheck': out['recheck'],
        'rounds_detail': out['rounds_detail'],
        'base_seed': src.get('incumbent_seed'),
        'result_lns': 'result_lns.json',
        'compare_svg': 'lns_compare.svg',
    }


def _best_summary(best: dict) -> tuple[float, float, int, float]:
    """``best`` 记录 → 汇总行四元组 ``(density, width_mm, n_placed, elapsed)``。

    兼容两种形态：solve 记录（``real_density`` / ``placed_items``=int 计数）与
    incumbent 记录（``density`` / ``placed_items``=完整布局 list）—— 汇总行格式
    不随 best 语义升级而变。
    """
    density = best.get('real_density', best.get('density'))
    n_placed = best['placed_items']
    if isinstance(n_placed, list):
        n_placed = len(n_placed)
    return float(density), float(best['width_mm']), int(n_placed), float(best['elapsed'])


def _append_run_stats(entry: dict, path=None) -> None:
    """PC-009 统计行追加（缺省 ``paths.RUN_STATS_JSONL``）；写盘失败只 warn 不阻塞。

    run_stats.jsonl 是 append-only 统计库（θ₀ 校准数据源，只增不改）：本函数只做
    「一行 JSON + 换行」追加，坏行由读取侧（``portfolio.load_run_stats``）容错
    跳过；任何 OSError（目录只读 / 路径不可建 / 目标是目录等）降级 stderr 警告 ——
    统计沉淀是旁路产物，绝不否定已完成的求解交付物（退出码与末行汇总不受影响）。
    """
    p = Path(paths.RUN_STATS_JSONL if path is None else path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError as e:
        print(f'警告: run 统计落盘失败（{p}）: {e}', file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    # 首行防乱码：Windows 管道/重定向默认 GBK，强制 UTF-8（真实控制台走
    # WindowsConsoleIO 本就 UTF-8，reconfigure 无害）。非常规流（pytest capture）
    # 无 reconfigure 能力，跳过不阻断。
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError, OSError):
        pass

    args = _parse_args(argv)
    t_start = time.monotonic()          # PC-009 elapsed_total 口径：整 run 墙钟

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f'配置错误: {e}', file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    if args.target is not None and not 0.0 < args.target <= 1.0:
        print(f'配置错误: --target 须为 (0,1] 区间内的比例值（如 0.9），'
              f'当前为 {args.target}', file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    # PC-006 solver_opts 旗标裁决（配置错误须在 new_run_dir 之前拦下，不留空目录）：
    # --solver-opts（固定档全 seed 生效）与 --rotate-opts（内置池逐 seed 轮换）互斥；
    # JSON 坏串 / 非 JSON 对象同按配置错误退出 1。旋钮清洗（clamp/白名单）不在 CLI
    # 做 —— web.solver._normalize_solver_opts 是单一真相源。
    if args.solver_opts is not None and args.rotate_opts:
        print('配置错误: --solver-opts 与 --rotate-opts 互斥（固定档 vs 逐 seed 轮换池），'
              '只能给其一', file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    fixed_solver_opts = None
    solver_opts_for = None
    if args.solver_opts is not None:
        try:
            fixed_solver_opts = json.loads(args.solver_opts)
        except json.JSONDecodeError as e:
            print(f'配置错误: --solver-opts 不是合法 JSON: {e}', file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT
        if not isinstance(fixed_solver_opts, dict):
            print('配置错误: --solver-opts 须为 JSON 对象（如 {"exploration_pct": 0.6}）',
                  file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT

        def solver_opts_for(_index, _seed, _fixed=fixed_solver_opts):
            return _fixed
    elif args.rotate_opts:

        def solver_opts_for(index, _seed):
            return rotation_opts_for(index)
    # PC-008 LNS 后处理旗标裁决（配置错误须在 new_run_dir 之前拦下，不留空目录）：
    # --lns-time / --lns-rounds 是 --lns 的从属旗标（单独给出 = 笔误，退出 1）；
    # 值域与 ms-lns CLI 同口径（time >= 1s、rounds >= 1）。
    if (args.lns_time is not None or args.lns_rounds is not None) and not args.lns:
        print('配置错误: --lns-time / --lns-rounds 须与 --lns 同给（LNS 后处理未启用）',
              file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    lns_time = 30 if args.lns_time is None else args.lns_time
    lns_rounds = 5 if args.lns_rounds is None else args.lns_rounds
    if args.lns and args.lns_time is not None and lns_time < 1:
        print(f'配置错误: --lns-time 须 >= 1 秒，当前 {args.lns_time}', file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    if args.lns and args.lns_rounds is not None and lns_rounds < 1:
        print(f'配置错误: --lns-rounds 须 >= 1，当前 {args.lns_rounds}', file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    # ---- US-002 策略双模式旗标裁决（配置错误在 new_run_dir 之前拦下，不留空目录）。
    # --strategy 不走 argparse choices（choices 外退出码是 2）→ 手工校验退出 1；
    # 策略模式 --time = 总预算秒数且必填；与 --kill 显式同给互斥（策略模式判据
    # 内建：race 门杀 R5_race_gate、R1/R2 引擎不评估）；4 个参数旗标是从属旗标
    # （单独给出 = 笔误退出 1，同 --lns-time 口径）；预算不足由 race_plan / se_plan
    # 抛 StrategyBudgetError（同样按配置错误退出 1）。
    strategy = args.strategy
    if strategy is not None and strategy not in ('se', 'race'):
        print(f'配置错误: --strategy 须为 se 或 race，当前为 {strategy!r}', file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    if (args.se_screen is not None or args.se_extend is not None
            or args.race_budget is not None or args.race_gate is not None) \
            and strategy is None:
        print('配置错误: --se-screen / --se-extend / --race-budget / --race-gate '
              '须与 --strategy 同给（策略模式未启用）', file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    if strategy is not None:
        if args.kill is not None:
            print('配置错误: --strategy 与 --kill 互斥（策略模式 kill 判据内建：'
                  'race 门杀 R5_race_gate，R1/R2 引擎不评估）', file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT
        if args.time is None:
            print('配置错误: 策略模式需 --time 总预算（秒），如 --strategy --time 1200',
                  file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT
        if args.time <= 0:
            print(f'配置错误: --time 须为正整数（策略模式 = 总预算秒数），当前 {args.time}',
                  file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT
    se_screen = SE_SCREEN_S if args.se_screen is None else args.se_screen
    se_ext = SE_EXT_S if args.se_extend is None else args.se_extend
    race_budget = RACE_BUDGET_S if args.race_budget is None else args.race_budget
    race_gate_tau = RACE_GATE_TAU if args.race_gate is None else args.race_gate
    k_screens = 1                         # se 阶段 1 筛选轮数（策略模式外不消费）
    gate_seconds: float | None = None
    strategy_seeds: list[int] | None = None
    if strategy == 'race':
        if race_budget < 1:
            print(f'配置错误: --race-budget 须 >= 1 秒，当前 {race_budget}', file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT
        if not 0.0 < race_gate_tau < 1.0:
            print(f'配置错误: --race-gate 须为 (0,1) 开区间内的比例值（如 0.5），'
                  f'当前 {race_gate_tau}', file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT
        try:
            n_planned, gate_seconds = race_plan(args.time, race_budget, race_gate_tau)
        except StrategyBudgetError as e:
            print(f'配置错误: {e}', file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT
        strategy_seeds = strategy_seed_stream(cfg.seeds, n_planned)
    elif strategy == 'se':
        if se_screen < 1:
            print(f'配置错误: --se-screen 须 >= 1 秒，当前 {se_screen}', file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT
        if se_ext < 1:
            print(f'配置错误: --se-extend 须 >= 1 秒，当前 {se_ext}', file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT
        try:
            k_screens, _ext = se_plan(args.time, se_screen, se_ext)
        except StrategyBudgetError as e:
            print(f'配置错误: {e}', file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT
        strategy_seeds = strategy_seed_stream(cfg.seeds, k_screens)
    params = None
    if args.params is not None:
        try:
            params = load_controller_params(args.params)
        except ControllerParamsError as e:
            print(f'配置错误: {e}', file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT
    # PC-003 kill 模式裁决（生效模式）：引擎仅 --target 给定时激活（θ 初值 = target
    # 是判据锚点）；--kill on 需标定就绪（calibrated: true），否则降级 shadow 并 warn
    # —— 未标定的包络/uplift 不可信，不许真杀。US-002：--kill 缺省 None → 生效
    # shadow（显式与否由互斥校验消费）；策略模式 R1/R2 引擎不评估 → 恒 off。
    kill_mode = args.kill or 'shadow'
    if strategy is not None:
        kill_mode = 'off'
    elif args.target is None:
        if kill_mode == 'on':
            print('警告: --kill 需要 --target（θ 初值 = target），本次 kill 引擎未激活',
                  file=sys.stderr)
        kill_mode = 'off'
    elif kill_mode == 'on' and not (params and params.get('calibrated') is True):
        kill_mode = 'shadow'
        print('警告: --kill on 需标定参数就绪（--params 文件含 "calibrated": true），'
              '本次自动降级 shadow（只记 kill_decisions.jsonl，不真正 kill）',
              file=sys.stderr)

    # 策略模式 --time = 总预算（config 回显同值）；legacy 语义不变（单轮求解时长）。
    time_budget = args.time if args.time is not None else cfg.time
    run_name = _clean_run_name(args.name if args.name else Path(args.config).stem)
    run_dir = new_run_dir(run_name)

    print(f'run_dir: {run_dir}')
    print(f'配置: {Path(args.config).resolve()} | 求解时长: {time_budget}s | '
          f'seeds: {cfg.seeds}'
          + (f' | target: {args.target:.2%}' if args.target is not None else ''))
    n_rounds = len(strategy_seeds) if strategy_seeds is not None else len(cfg.seeds)
    if strategy is not None:
        # US-002 策略模式启动行（--quiet 也打：改求解编排的开关不静默，同
        # solver_opts 口径）—— 一条命令即可核对模式 / 门时刻 / 计划轮数 / 种子流。
        if strategy == 'race':
            print(f'[portfolio] 策略模式 race（门杀）：总预算 {args.time}s，每 seed '
                  f'{race_budget:g}s 预算，门时刻 {gate_seconds:g}s'
                  f'（τ={race_gate_tau:g}，严格破纪录才续跑），'
                  f'计划 ≤ {n_rounds} 个 seed（种子流 {strategy_seeds}）')
        else:
            print(f'[portfolio] 策略模式 se（筛延）：总预算 {args.time}s = 阶段 1 '
                  f'{n_rounds} × {se_screen:g}s 筛选 + 阶段 2 冠军 {se_ext:g}s 延长'
                  f'（种子流 {strategy_seeds}）')
    elif n_rounds > 1:
        # 多 seed 启动即给总时长预期（len(seeds) × time，不含解析/切片）——
        # 评估配置前先知道要等多久，避免把长跑误判挂死。
        print(f'多 seed 串行 {n_rounds} 轮 × {time_budget}s，'
              f'预计总时长 ≈ {n_rounds * time_budget}s（不含解析/切片）')
    # PC-006 旋钮生效方式一行说明（--quiet 也打：改求解行为的开关不静默）。
    if fixed_solver_opts is not None:
        print(f"solver_opts: {json.dumps(fixed_solver_opts, ensure_ascii=False)}"
              f'（全 seed 生效）')
    elif args.rotate_opts:
        print(f'rotate_opts: 内置池 {len(SOLVER_OPTS_POOL)} 档逐 seed 轮换'
              f'（pool[队列序 % {len(SOLVER_OPTS_POOL)}]，池首空档=默认行为）')
    # PC-008 后处理开关说明（--quiet 也打：改交付物的开关不静默）。band 开启时
    # LNS 波段重排会拆散版师带形态（链内贴触 + 开口朝左）→ warn 跳过（求解产物
    # 不受影响，与「LNS 输入错误降级 warn」同模式）。
    if args.lns:
        print(f'LNS 后处理: time={lns_time}s rounds={lns_rounds}'
              f'（严格更优才回写 result.json，明细写 result_lns.json）')
        if cfg.band is not None:
            print(f'  ⚠ 腰头成带已开启（band g 码 {cfg.band["label"]}）：'
                  '波段重排会拆散带形态，LNS 环节将跳过', file=sys.stderr)
        # US-003 预埋（2026-08-25 起 9 键 schema 接入即刻生效；FR-11 —— 波段重排
        # 会拆钉位：前缀组合片 x=0 锚定 + 段成员刚体关系被段重排破坏）。
        if cfg.prefix is not None:
            print(f'  ⚠ 起始端成套前后幅已开启（prefix {cfg.prefix.get("front")}'
                  f'/{cfg.prefix.get("back")}）：波段重排会拆布头钉位，'
                  'LNS 环节将跳过', file=sys.stderr)
    # PC-009 θ₀ 校准（读 run 统计库，--target 模式才有 kill 门槛可校准）：当前
    # 实例类（class_key）命中且 ≥5 条历史 → θ 初值 = min(target, 历史最大
    # best_density + 0.003)（贴可达性起跑），否则 θ = target。θ₀ 只影响 kill
    # 门槛（R2/R3 判据锚），R0 停止条件恒用 --target 真值；说明行 --quiet 也打
    # （判据变更不静默，同 R3 θ 衰减口径）。统计库缺失 / 坏行由 load_run_stats
    # 容错（→ 无历史 → 不校准），读失败绝不阻断求解。
    # band label 纳入 class_key（band off → 不加组件 = 与旧口径逐字节一致，历史
    # 样本继续命中；band on → 新 key，+2pt 级密度差不与 band off 混同分布）。
    # prefix 同款（2026-08-25）：'g02+g03' 组件（~0.7pt 偏移 > θ₀ margin 0.3pt）。
    _pf, _pb = (cfg.prefix or {}).get('front'), (cfg.prefix or {}).get('back')
    stats_class_key = run_stats_class_key(str(cfg.master_dxf), cfg.sizes,
                                          cfg.quantities, cfg.per_type,
                                          band_label=(cfg.band or {}).get('label'),
                                          prefix_labels=(f'{_pf}+{_pb}'
                                                         if _pf and _pb else None))
    theta0 = None
    # US-002：策略模式 θ 不维护（R1/R2 不评估），校准无判据可锚 → 跳过。
    if args.target is not None and strategy is None:
        theta0, info = calibrate_theta0(load_run_stats(paths.RUN_STATS_JSONL),
                                        stats_class_key, args.target)
        if info is not None:
            print(f'[portfolio] θ₀ 校准: class_key {stats_class_key} 命中 '
                  f"{info['n_records']} 条历史"
                  f"（最高 best_density={info['max_density']:.2%}）→ "
                  f'θ 初值={theta0:.2%}'
                  f'（= min(target, 历史最高 + {THETA0_MARGIN * 100:.2f}pt)；'
                  f'只影响 kill 门槛，R0 停止条件恒用 --target）')

    try:
        commit = commit_from_config(cfg, run_dir)
    except Exception as e:
        print(f'commit 管线失败: {e}', file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    print(f"commit: n_pieces={commit['n_pieces']} "
          f"total_area={commit['total_area_mm2']:,.1f}mm² "
          f"sizes={commit['sizes']} skipped={commit['n_skipped']}")

    # US-002 R1 增量（US-004 web 桥接前置）：策略模式 commit 完成后、首轮求解前
    # 写 strategy.json —— run 一启动即暴露模式 / 计划轮数 / 种子流（result.json
    # 要等首个 seed 完成才首次落盘，race 默认下前 ~180s 无信息可轮询）。
    if strategy is not None:
        plan_payload = {
            'mode': strategy,
            'total_budget': int(args.time),
            'planned_seeds': list(strategy_seeds),
            'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        if strategy == 'race':
            plan_payload['race'] = {'gate_seconds': round(float(gate_seconds), 3)}
        else:
            plan_payload['se'] = {'k_screens': int(k_screens),
                                  'screen_s': se_screen, 'ext_s': se_ext}
        with open(Path(run_dir) / 'strategy.json', 'w', encoding='utf-8') as f:
            json.dump(plan_payload, f, ensure_ascii=False, indent=2)

    solves: list[dict] = []
    result_path = Path(run_dir) / 'result.json'
    # PC-003 kill 决策日志：引擎激活（shadow/on）即建文件（空文件也在场，路径稳定），
    # 决策逐条 append + flush —— Ctrl-C / 崩溃不丢已记条目；控制器经回调交出记录，
    # 自身不做文件 I/O（呈现层职责）。US-002：race 模式门杀决策（R5_race_gate）
    # 复用同一文件 —— S_tau 重载为 bar 参照值、theta 恒 null（README 注明）。
    kill_log_path = Path(run_dir) / 'kill_decisions.jsonl'
    kill_log = (open(kill_log_path, 'w', encoding='utf-8')
                if kill_mode != 'off' or strategy == 'race' else None)

    def _on_kill_decision(entry: dict) -> None:
        kill_log.write(json.dumps(entry, ensure_ascii=False) + '\n')
        kill_log.flush()

    controller = PortfolioController(
        seeds=list(cfg.seeds) if strategy is None else list(strategy_seeds),
        target=args.target, params=params,
        echo=None if args.quiet else print,
        kill=kill_mode, time_budget=time_budget,
        notify=print, on_decision=_on_kill_decision if kill_log is not None else None,
        theta0=theta0,
        # ---- US-002 策略双模式（legacy 全缺省零回归）----
        mode='legacy' if strategy is None else strategy,
        total_budget=args.time if strategy is not None else None,
        race_budget=race_budget, race_gate_tau=race_gate_tau,
        se_k=k_screens, se_screen=se_screen, se_ext=se_ext)
    current = {'seed': None}       # 求解异常报错定位用（on_seed_start 持续刷新）
    # US-002 策略参数回显（result.json config 段；legacy → None 不加键）。
    if strategy == 'race':
        strategy_echo = {'mode': 'race', 'race_budget': race_budget,
                         'race_gate': race_gate_tau}
    elif strategy == 'se':
        strategy_echo = {'mode': 'se', 'se_screen': se_screen, 'se_extend': se_ext}
    else:
        strategy_echo = None
    # PC-008：LNS 严格更优时的 result.json lns 段（None = 不写该键 —— 无 --lns /
    # LNS 不优的 result.json 与基线逐字节一致，见 _flush_result）。
    lns_state = {'section': None}

    def _flush_result() -> dict:
        """逐轮重写 result.json（solve 数组 + best + portfolio 段）—— Ctrl-C/崩溃
        不丢已完成轮。

        结构与终态完全一致（config 回显 + commit 摘要 + solve 数组 + best +
        portfolio 段），中途落盘只是「solve 数组尚未跑满 len(seeds)」这一维度不同。
        PC-008：LNS 严格更优时额外附 ``lns`` 段（前后对比 + 轮次明细；未改进 /
        未启用时无该键 —— 与无 --lns 运行逐字节一致）。
        """
        best = controller.best_record(solves)
        result = {
            'config': {
                'path': str(Path(args.config).resolve()),
                'master_dxf': str(cfg.master_dxf),
                'sizes': cfg.sizes,
                'gate_mm': cfg.gate_mm,
                # time 回显「实际生效值」（--time 覆盖后的），run 可复现优先于原文件字面。
                'time': time_budget,
                'seeds': list(cfg.seeds),
                'per_type': cfg.per_type,
                'quantities': cfg.quantities,
                # PC-006 旋钮回显（旗标未给时不加键：无旗标冒烟的结构对拍不受扰）。
                **({'solver_opts': fixed_solver_opts}
                   if fixed_solver_opts is not None else {}),
                **({'rotate_opts': True} if args.rotate_opts else {}),
                # US-002 策略回显（旗标未给时不加键：无 --strategy 的 result.json
                # 与现版逐字节一致；time 字段在策略模式 = 总预算，参数在此回显）。
                **({'strategy': strategy_echo} if strategy_echo is not None else {}),
                # band 回显（config 未给 / enabled=false 不加键：与无 band 运行
                # 逐字节一致，冒烟对拍不受扰）。
                **({'band': cfg.band} if cfg.band is not None else {}),
                # prefix 回显（同 band 口径：None 不加键）。
                **({'prefix': cfg.prefix} if cfg.prefix is not None else {}),
            },
            'commit': commit,
            'solve': solves,
            'best': best,
            'portfolio': controller.portfolio_section(),
        }
        if lns_state['section'] is not None:
            result['lns'] = lns_state['section']
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    def _on_seed_start(i: int, seed: int) -> None:
        current['seed'] = seed
        if args.quiet:
            return
        # US-002 se 延长轮专用头（队列序 > 计划筛选数 n_rounds，i/n_rounds 分母
        # 不适用；按序号判定 —— on_seed_start 先于 make_progress 的 phase 刷新）。
        if strategy == 'se' and i > n_rounds:
            print(f'── 延长轮（seed={seed}·筛选冠军）开始 ──')
            return
        # 轮次头：多 seed、R0 模式或策略模式（单 seed 无旗标运行保持旧版零输出增量）。
        if n_rounds > 1 or args.target is not None or strategy is not None:
            print(f'── 第 {i}/{n_rounds} 轮（seed={seed}）开始 ──')

    def _on_seed_done(rec: dict) -> None:
        solves.append(rec)
        _flush_result()

    try:
        run = run_serial_portfolio(
            cfg, run_dir, controller=controller, time_budget=time_budget,
            solve=solve_pieces, on_seed_start=_on_seed_start,
            on_seed_done=_on_seed_done, solver_opts_for=solver_opts_for)
    except Exception as e:
        print(f'求解失败 (seed={current["seed"]}): {e}', file=sys.stderr)
        return _EXIT_SOLVE
    finally:
        if kill_log is not None:
            kill_log.close()

    if run.interrupted:
        i, seed = run.last_round
        if not solves:
            print(f'\n[中断] Ctrl-C：第 {i}/{n_rounds} 轮（seed={seed}）未完成，'
                  f'尚无完整求解轮，run_dir = {run_dir.resolve()}', file=sys.stderr)
            return _EXIT_INTERRUPT
        d, _w, _n, _e = _best_summary(_flush_result()['best'])
        where = ('（延长轮）' if strategy == 'se'
                 and controller.current_phase == 'extension' else '')
        print(f'\n[中断] Ctrl-C：已完成 {len(solves)}/{n_rounds} 轮{where}，'
              f'best real_density（原面积口径）= {d:.2%}，'
              f'产物已落盘 {run_dir.resolve()}', file=sys.stderr)
        return _EXIT_INTERRUPT

    best = _flush_result()['best']

    if controller.queue_stopped:
        # R0 达标即停（终局事件，--quiet 也打；剩余 = 队列长度 − 已启动轮数）。
        executed = run.last_round[0] if run.last_round else 0
        skipped = n_rounds - executed
        inc = controller.incumbent
        print(f'[portfolio] R0 达标即停：target={args.target:.2%}，'
              f'incumbent real_density={inc["density"]:.2%}'
              f'（seed {inc["seed"]} frame {inc["frame_index"]}），'
              f'剩余 {skipped} 个 seed 未启动')
    elif strategy == 'race':
        # race 名义预算收口（终局事件，--quiet 也打）：计划数是全门杀乐观上界，
        # 有 seed 破纪录跑满时队列在此提前收口（被杀省出的预算已自然吸收）。
        executed = run.last_round[0] if run.last_round else 0
        skipped = n_rounds - executed
        if skipped > 0:
            print(f'[portfolio] race 预算收口：{skipped} 个计划 seed 未启动'
                  f'（名义记账 {controller.spent_nominal:g}s / 总预算 {args.time}s）')

    if n_rounds > 1 or strategy is not None:
        digest = ' | '.join(
            f"seed {r['seed']}={r['real_density']:.2%}"
            + ('（延长）' if r.get('phase') == 'extension' else '')
            for r in solves)
        print(f'各 seed real_density（原面积口径）: {digest}')
        if controller.engaged and controller.incumbent is not None:
            print(f"best = seed {best['seed']} frame {best['frame_index']}"
                  f'（incumbent，帧级全局最优）')
        else:
            print(f"best = seed {best['seed']}（real_density 最大者）")
    if controller.kill_mode != 'off' or strategy == 'race':
        # 终局产物行（--quiet 也打）：shadow/on 的判定去向与条数。置于末行汇总前
        # ——「末行 = real_density 汇总」是既有输出契约（冒烟对拍口径）。US-002
        # race：R5 门杀决策同文件（引擎 off 但决策在场，标签如实标 race）。
        tag = 'race' if controller.kill_mode == 'off' else controller.kill_mode
        print(f"[kill] {tag} 模式："
              f"{len(controller.kill_decisions)} 条 kill 判定已写 "
              f"{kill_log_path.resolve()}")
    # ---- PC-008 LNS 后处理（--lns）：对 portfolio 最优布局跑 PC-007 波段重排。
    # R0 提前停（queue_stopped）同样走到这里 —— 对达标解也可再压宽度；Ctrl-C 中断
    # 的 run 不做后处理（portfolio 未跑完，按中断路径 130 收口）。
    # band 开启 → 跳过（启动处已 warn）：波段重排会把落在段内的带成员抽出重排，
    # 破坏版师带形态（链内贴触 + 开口朝左 + 最大码最右）。prefix 开启同理跳过
    # （US-003 预埋，双 warn 点之二：拆布头钉位；FR-11）。
    if args.lns and cfg.band is not None:
        print(f'LNS 后处理跳过: 腰头成带已开启（band g 码 {cfg.band["label"]}），'
              '波段重排会拆散带形态（求解产物不受影响）', file=sys.stderr)
    elif args.lns and cfg.prefix is not None:
        print(f'LNS 后处理跳过: 起始端成套前后幅已开启（prefix '
              f'{cfg.prefix.get("front")}/{cfg.prefix.get("back")}），'
              '波段重排会拆布头钉位（求解产物不受影响）', file=sys.stderr)
    elif args.lns:
        try:
            out = postprocess_run_dir(run_dir, time_budget=lns_time,
                                      rounds=lns_rounds,
                                      echo=None if args.quiet else print)
        except KeyboardInterrupt:
            # run_lns 内部已捕获正常路径的 Ctrl-C；此处兜底读文件/落盘窗口 ——
            # result.json 从未被 LNS 半写（改写只在改进判定后一次性整体重写）。
            print('\n[中断] Ctrl-C：LNS 后处理未产出结果，主 result.json 保持完整',
                  file=sys.stderr)
            return _EXIT_INTERRUPT
        except (LnsError, ValueError, KeyError, TypeError, OSError,
                json.JSONDecodeError) as e:
            # 后处理输入错误（旧 run 无布局 / 中间产物缺失等）不否定已完成的求解
            # 交付物：warn 后按已有产物收尾（退出码 0）。
            print(f'LNS 后处理失败（已有求解产物不受影响）: {e}', file=sys.stderr)
            out = None
        if out is not None:
            b, a, dlt = out['before'], out['after'], out['delta']
            # 前后两行汇总（终局汇总口径，--quiet 也打）。
            print(f'[LNS] 前（portfolio 最优）: width={b["width_mm"]:.0f}mm '
                  f'density={b["density"]:.2%}（原面积口径）')
            print(f'[LNS] 后: width={a["width_mm"]:.0f}mm '
                  f'density={a["density"]:.2%}（原面积口径）'
                  f' | Δwidth={dlt["width_mm"]:+.0f}mm '
                  f'Δdensity={dlt["density"] * 100:+.2f}pt'
                  f' | rounds={out["rounds_executed"]}/{out["rounds_requested"]}'
                  f'（{out["stop_reason"]}）improved={out["improved"]}')
            if out['improved']:
                # 严格更优才回写：incumbent 三字段更新（seed/frame_index/elapsed
                # 保持来源帧出处）+ lns 段，一次性整体重写 result.json（best 与
                # portfolio.incumbent 同源，best_record 返回同一 dict 自动同步）。
                if controller.incumbent is not None:
                    controller.incumbent['density'] = a['density']
                    controller.incumbent['width_mm'] = a['width_mm']
                    controller.incumbent['placed_items'] = out['placed_items']
                lns_state['section'] = _lns_section(out)
                best = _flush_result()['best']
            if out['interrupted']:
                # Ctrl-C 在 LNS 环节：已完成轮次已落 result_lns.json；改进（若有）
                # 已一次性回写，主 result.json 完整 —— 按中断契约退出 130。
                print('\n[中断] Ctrl-C：LNS 已完成轮次已写 result_lns.json，'
                      '主 result.json 保持完整', file=sys.stderr)
                return _EXIT_INTERRUPT
    d, w, n_placed, elapsed = _best_summary(best)
    # PC-009 run 统计库：完成路径（含 R0 提前停 / kill 路径，均 exit 0 收口）追加
    # 一行 —— θ₀ 校准的数据源（分布越测越准）；best_density 取末行汇总同款口径
    # （LNS 改进已并入 best）。写侧失败在 _append_run_stats 内降级 warn。
    _append_run_stats({
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'source': str(cfg.master_dxf),
        'sizes': cfg.sizes,
        'class_key': stats_class_key,
        # US-002：策略模式记计划种子流（strategy_seed_stream 产物，config 原值在
        # result.json config 段回显）；legacy 保持 cfg.seeds 原样。
        'seeds': list(controller.seeds) if strategy is not None else list(cfg.seeds),
        'target': args.target,
        'best_density': round(d, 6),
        'n_killed': sum(1 for e in controller.per_seed if e.get('killed')),
        'elapsed_total': round(time.monotonic() - t_start, 1),
        'config': {'time': time_budget, 'per_type': cfg.per_type,
                   'quantities': cfg.quantities,
                   # band 回显（None 不加键：历史行结构不变，读侧按 class_key 匹配
                   # —— band label 已纳入 class_key，同 class 必同 band 态）。
                   # prefix 同款（labels 已纳入 class_key）。
                   **({'band': cfg.band} if cfg.band is not None else {}),
                   **({'prefix': cfg.prefix} if cfg.prefix is not None else {})},
    })
    print(f"real_density（原面积口径）= {d:.2%} | "
          f"用布长度 = {w:.0f}mm | 片数 = {n_placed} | "
          f"耗时 = {elapsed:.1f}s | run_dir = {run_dir.resolve()}")
    return _EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
