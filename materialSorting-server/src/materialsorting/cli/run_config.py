r"""ms-run-config 入口 —— 一条命令跑完「commit → 求解」，无需浏览器即可评估配置。

用法（console_script 或 ``python -m`` 等价）::

    ms-run-config <config.json> [--name RUN_NAME] [--time N] [--quiet]
                  [--target P] [--params controller_params.json]
    python -m materialsorting.cli.run_config <config.json> --time 5

流程：``load_config``（7 键 schema 校验）→ ``new_run_dir``（时间戳目录保留历史）
→ ``commit_from_config``（切片 + intermediate 落 run_dir，**仅一次**）→ 逐 ``seeds``
元素**经 ``cli.portfolio`` 控制器串行** ``solve_pieces``（每轮重建 build_instance，
复用同一份 commit 产物）→ ``result.json``（config 回显 + commit 摘要 + solve 指标
数组 + **best** + **portfolio** 段）→ stdout 末行人类可读汇总。

多 seed 语义（US-004；PC-002 起经 portfolio 控制器转发）：seeds 列表 ≥2 个时自动
串行逐 seed 求解并汇总最优；种子不要求连续（``[0, 42]`` 合法）；**只做串行，不做
并行**（任一时刻至多 1 个求解进程）。多 seed 启动即打印预计总时长
（``len(seeds) × time``，不含解析/切片）。

PC-002 portfolio 语义（``--target`` / ``--params`` 新旗标，7 键 config schema 不动）：

  - **incumbent banking**：逐帧入账全局最优（含被 kill / 中途停止 seed 的最优帧，
    修复旧 best 只看 per-seed 终值的盲区）；``--target`` 给定或 seeds ≥2 时
    ``best`` 升级为 incumbent（帧级全局最优，含完整 ``placed_items``），result.json
    新增 ``portfolio`` 段（target / incumbent / per_seed / theta_history）。
  - **R0 达标即停**：``--target <0..1>``（原面积口径）任一帧达标 → 当前 seed 被
    stop（交付 best-so-far 帧）+ 剩余队列不启动，退出码仍 0；缺省不启用。
  - **单 seed 无 --target**：空 portfolio 段 + ``best`` 保持旧语义（solve 数组
    real_density 最大者）—— 与 PC-001 基线无旗标冒烟对拍兼容。
  - ``--params``：controller 标定参数 JSON（PC-004 产物，PC-003 消费）；仅校验
    可加载（存在 + JSON 对象），坏文件按配置错误退出 1。

run_name 缺省 = 配置文件 stem，``--name`` 覆盖；Windows 非法文件名字符
（``<>:"/\|?*`` 与控制字符）替换 ``_``，清洗后为空回退 ``run``。

退出码：0 成功（含 R0 提前停）；1 配置或管线失败（ConfigError / --target 越界 /
--params 坏文件 / commit 抛错）；2 求解失败（solve 抛错 / placed != Σdemand）；
130 Ctrl-C 中断（已完成轮产物已落盘）。

PC-001 落盘口径（逐 seed 写，不攒内存）：每轮 ``solve_pieces`` 完成即把当前
``result.json`` 重写一次（config 回显 + commit 摘要 + 已完成 solve 数组 + best +
portfolio 段），Ctrl-C / 崩溃时 run_dir 内已持有已完成轮的完整产物（curve_s*/
best_frame_s* 由 ``solve_pieces`` 逐帧写，result.json 由本入口逐轮写）。

进度口径（``--quiet`` 全部抑制，仅保留最终汇总；行格式由 ``cli.portfolio`` 控制器
统一实现）：「原面积口径新最优」帧 + 30s 心跳 + 跨 seed 反超的 incumbent 行 +
per-seed 轮次头（多 seed 或 ``--target`` 给定时打印）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .pipeline import commit_from_config, new_run_dir, solve_pieces
from .portfolio import (ControllerParamsError, PortfolioController,
                        load_controller_params, run_serial_portfolio)

__all__ = ['main']

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
    p.add_argument('config', help='配置文件路径（7 键 JSON schema，见 data/configs/）')
    p.add_argument('--name', metavar='RUN_NAME',
                   help='覆盖 run_name（缺省 = 配置文件 stem，非法字符清洗）')
    p.add_argument('--time', type=int, metavar='N',
                   help='覆盖单轮求解时长（秒）；冒烟/调试用（result.json 回显生效值）')
    p.add_argument('--quiet', action='store_true',
                   help='静默：不打进度帧与心跳（最终汇总仍输出）')
    p.add_argument('--target', type=float, metavar='P',
                   help='R0 达标即停阈值（0..1 比例，原面积口径 density ≥ target 即'
                        '停当前 seed 并终止剩余队列）；缺省不启用 R0')
    p.add_argument('--params', metavar='FILE',
                   help='controller 标定参数 JSON（PC-004 产物，覆盖默认阈值；'
                        'PC-002 仅校验可加载）')
    return p.parse_args(argv)


def _clean_run_name(raw: str) -> str:
    """run_name 清洗：非法文件名字符 → ``_``，去首尾空白/点；清洗后为空回退 ``run``。"""
    cleaned = _ILLEGAL_NAME_RE.sub('_', raw).strip().strip('. ')
    return cleaned or 'run'


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

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f'配置错误: {e}', file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    if args.target is not None and not 0.0 < args.target <= 1.0:
        print(f'配置错误: --target 须为 (0,1] 区间内的比例值（如 0.9），'
              f'当前为 {args.target}', file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    params = None
    if args.params is not None:
        try:
            params = load_controller_params(args.params)
        except ControllerParamsError as e:
            print(f'配置错误: {e}', file=sys.stderr)
            return _EXIT_CONFIG_OR_COMMIT

    time_budget = args.time if args.time is not None else cfg.time
    run_name = _clean_run_name(args.name if args.name else Path(args.config).stem)
    run_dir = new_run_dir(run_name)

    print(f'run_dir: {run_dir}')
    print(f'配置: {Path(args.config).resolve()} | 求解时长: {time_budget}s | '
          f'seeds: {cfg.seeds}'
          + (f' | target: {args.target:.2%}' if args.target is not None else ''))
    n_rounds = len(cfg.seeds)
    if n_rounds > 1:
        # 多 seed 启动即给总时长预期（len(seeds) × time，不含解析/切片）——
        # 评估配置前先知道要等多久，避免把长跑误判挂死。
        print(f'多 seed 串行 {n_rounds} 轮 × {time_budget}s，'
              f'预计总时长 ≈ {n_rounds * time_budget}s（不含解析/切片）')

    try:
        commit = commit_from_config(cfg, run_dir)
    except Exception as e:
        print(f'commit 管线失败: {e}', file=sys.stderr)
        return _EXIT_CONFIG_OR_COMMIT
    print(f"commit: n_pieces={commit['n_pieces']} "
          f"total_area={commit['total_area_mm2']:,.1f}mm² "
          f"sizes={commit['sizes']} skipped={commit['n_skipped']}")

    solves: list[dict] = []
    result_path = Path(run_dir) / 'result.json'
    controller = PortfolioController(
        seeds=list(cfg.seeds), target=args.target, params=params,
        echo=None if args.quiet else print)
    current = {'seed': None}       # 求解异常报错定位用（on_seed_start 持续刷新）

    def _flush_result() -> dict:
        """逐轮重写 result.json（solve 数组 + best + portfolio 段）—— Ctrl-C/崩溃
        不丢已完成轮。

        结构与终态完全一致（config 回显 + commit 摘要 + solve 数组 + best +
        portfolio 段），中途落盘只是「solve 数组尚未跑满 len(seeds)」这一维度不同。
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
            },
            'commit': commit,
            'solve': solves,
            'best': best,
            'portfolio': controller.portfolio_section(),
        }
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    def _on_seed_start(i: int, seed: int) -> None:
        current['seed'] = seed
        # 轮次头：多 seed 或 R0 模式（单 seed 无旗标运行保持旧版零输出增量）。
        if not args.quiet and (n_rounds > 1 or args.target is not None):
            print(f'── 第 {i}/{n_rounds} 轮（seed={seed}）开始 ──')

    def _on_seed_done(rec: dict) -> None:
        solves.append(rec)
        _flush_result()

    try:
        run = run_serial_portfolio(
            cfg, run_dir, controller=controller, time_budget=time_budget,
            solve=solve_pieces, on_seed_start=_on_seed_start,
            on_seed_done=_on_seed_done)
    except Exception as e:
        print(f'求解失败 (seed={current["seed"]}): {e}', file=sys.stderr)
        return _EXIT_SOLVE

    if run.interrupted:
        i, seed = run.last_round
        if not solves:
            print(f'\n[中断] Ctrl-C：第 {i}/{n_rounds} 轮（seed={seed}）未完成，'
                  f'尚无完整求解轮，run_dir = {run_dir.resolve()}', file=sys.stderr)
            return _EXIT_INTERRUPT
        d, _w, _n, _e = _best_summary(_flush_result()['best'])
        print(f'\n[中断] Ctrl-C：已完成 {len(solves)}/{n_rounds} 轮，'
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

    if n_rounds > 1:
        digest = ' | '.join(
            f"seed {r['seed']}={r['real_density']:.2%}" for r in solves)
        print(f'各 seed real_density（原面积口径）: {digest}')
        if controller.engaged and controller.incumbent is not None:
            print(f"best = seed {best['seed']} frame {best['frame_index']}"
                  f'（incumbent，帧级全局最优）')
        else:
            print(f"best = seed {best['seed']}（real_density 最大者）")
    d, w, n_placed, elapsed = _best_summary(best)
    print(f"real_density（原面积口径）= {d:.2%} | "
          f"用布长度 = {w:.0f}mm | 片数 = {n_placed} | "
          f"耗时 = {elapsed:.1f}s | run_dir = {run_dir.resolve()}")
    return _EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
