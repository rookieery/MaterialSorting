r"""ms-run-config 入口 —— 一条命令跑完「commit → 求解」，无需浏览器即可评估配置。

用法（console_script 或 ``python -m`` 等价）::

    ms-run-config <config.json> [--name RUN_NAME] [--time N] [--quiet]
    python -m materialsorting.cli.run_config <config.json> --time 5

流程：``load_config``（7 键 schema 校验）→ ``new_run_dir``（时间戳目录保留历史）
→ ``commit_from_config``（切片 + intermediate 落 run_dir，**仅一次**）→ 逐 ``seeds``
元素**串行** ``solve_pieces``（每轮重建 build_instance，复用同一份 commit 产物）
→ ``result.json``（config 回显 + commit 摘要 + solve 指标数组 + **best**）→
stdout 末行人类可读汇总。

多 seed 语义（US-004）：seeds 列表 ≥2 个时自动串行逐 seed 求解并汇总最优 ——
``best`` 取 per-seed 解中 ``real_density``（原面积口径）最大者（并列取先执行者），
消除单 seed 随机性对配置评估的干扰。种子不要求连续（``[0, 42]`` 合法，供复现
历史 seed 对比）；**只做串行，不做并行**（确定性 + 零进程管理复杂度）。多 seed
启动即打印预计总时长（``len(seeds) × time``，不含解析/切片）。

run_name 缺省 = 配置文件 stem，``--name`` 覆盖；Windows 非法文件名字符
（``<>:"/\|?*`` 与控制字符）替换 ``_``，清洗后为空回退 ``run``。

退出码：0 成功；1 配置或管线失败（ConfigError / commit 抛错）；2 求解失败
（solve 抛错 / placed != Σdemand）；130 Ctrl-C 中断（已完成轮产物已落盘）。

PC-001 落盘口径（逐 seed 写，不攒内存）：每轮 ``solve_pieces`` 完成即把当前
``result.json`` 重写一次（config 回显 + commit 摘要 + 已完成 solve 数组 + best），
Ctrl-C / 崩溃时 run_dir 内已持有已完成轮的完整产物（curve_s*/best_frame_s* 由
``solve_pieces`` 逐帧写，result.json 由本入口逐轮写）。

进度口径（``--quiet`` 全部抑制，仅保留最终汇总）：
  - 「原面积口径新最优」帧：每帧 real_density 刷新历史最优才打一行；
  - 30s 心跳：≥30s 无任何输出时打一行当前进度（长时求解防「静默被误判挂死」）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from .config import ConfigError, load_config
from .pipeline import commit_from_config, new_run_dir, solve_pieces

__all__ = ['main']

# Windows 文件名非法字符 + 控制字符（run_name 进目录名前清洗）。
_ILLEGAL_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# 长时求解心跳间隔（秒）。
_HEARTBEAT_SEC = 30.0

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
    return p.parse_args(argv)


def _clean_run_name(raw: str) -> str:
    """run_name 清洗：非法文件名字符 → ``_``，去首尾空白/点；清洗后为空回退 ``run``。"""
    cleaned = _ILLEGAL_NAME_RE.sub('_', raw).strip().strip('. ')
    return cleaned or 'run'


def _make_progress_printer(seed: int, quiet: bool):
    """构造 on_progress 回调：只打「原面积口径新最优」帧 + 30s 心跳。

    新最优判定基于 **real_density（原面积口径）**（``solve_pieces`` 已换算好
    ``density`` 键），与 result.json / 最终汇总同口径。
    """
    state = {'best': -1.0, 'last_output': time.time()}

    def on_frame(report: dict) -> None:
        if quiet:
            return
        d = float(report.get('density', 0.0))
        now = time.time()
        if d > state['best']:
            state['best'] = d
            state['last_output'] = now
            print(f"[seed {seed}] {report.get('elapsed', 0.0):7.1f}s "
                  f"{report.get('phase', ''):<14} "
                  f"real_density={d:.2%}（原面积口径新最优） "
                  f"width={report.get('width_mm', 0.0):.0f}mm")
        elif now - state['last_output'] >= _HEARTBEAT_SEC:
            state['last_output'] = now
            print(f"[seed {seed}] {report.get('elapsed', 0.0):7.1f}s 心跳 "
                  f"phase={report.get('phase', '')} real_density={d:.2%}（原面积口径） "
                  f"width={report.get('width_mm', 0.0):.0f}mm")

    return on_frame


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

    time_budget = args.time if args.time is not None else cfg.time
    run_name = _clean_run_name(args.name if args.name else Path(args.config).stem)
    run_dir = new_run_dir(run_name)

    print(f'run_dir: {run_dir}')
    print(f'配置: {Path(args.config).resolve()} | 求解时长: {time_budget}s | '
          f'seeds: {cfg.seeds}')
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

    def _flush_result() -> dict:
        """逐轮重写 result.json（已完成 solve 数组 + best）—— Ctrl-C/崩溃不丢已完成轮。

        结构与终态完全一致（config 回显 + commit 摘要 + solve 数组 + best），中途
        落盘只是「solve 数组尚未跑满 len(seeds)」这一维度不同。
        """
        # best = per-seed 解中 real_density（原面积口径）最大者；并列取先执行者
        # （max 首个极大值）—— 多轮消除单 seed 随机性，配置评估取最优口径。
        best = max(solves, key=lambda r: r['real_density'])
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
        }
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    interrupted = False
    for i, seed in enumerate(cfg.seeds, start=1):
        if not args.quiet and n_rounds > 1:
            print(f'── 第 {i}/{n_rounds} 轮（seed={seed}）开始 ──')
        try:
            rec = solve_pieces(
                cfg, run_dir, seed=seed, time_budget=time_budget,
                on_progress=_make_progress_printer(seed, args.quiet))
        except KeyboardInterrupt:
            # Ctrl-C：当前轮弃，已完成轮的 curve/best_frame/result 已逐轮落盘
            # （solve_pieces finally 保证在飞 seed 的 curve 也写全）。
            interrupted = True
            break
        except Exception as e:
            print(f'求解失败 (seed={seed}): {e}', file=sys.stderr)
            return _EXIT_SOLVE
        solves.append(rec)
        _flush_result()

    if interrupted:
        if not solves:
            print(f'\n[中断] Ctrl-C：第 {i}/{n_rounds} 轮（seed={seed}）未完成，'
                  f'尚无完整求解轮，run_dir = {run_dir.resolve()}', file=sys.stderr)
            return _EXIT_INTERRUPT
        best = _flush_result()['best']
        print(f'\n[中断] Ctrl-C：已完成 {len(solves)}/{n_rounds} 轮，'
              f'best real_density（原面积口径）= {best["real_density"]:.2%}，'
              f'产物已落盘 {run_dir.resolve()}', file=sys.stderr)
        return _EXIT_INTERRUPT

    best = _flush_result()['best']

    if n_rounds > 1:
        digest = ' | '.join(
            f"seed {r['seed']}={r['real_density']:.2%}" for r in solves)
        print(f'各 seed real_density（原面积口径）: {digest}')
        print(f"best = seed {best['seed']}（real_density 最大者）")
    print(f"real_density（原面积口径）= {best['real_density']:.2%} | "
          f"用布长度 = {best['width_mm']:.0f}mm | 片数 = {best['placed_items']} | "
          f"耗时 = {best['elapsed']:.1f}s | run_dir = {run_dir.resolve()}")
    return _EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
