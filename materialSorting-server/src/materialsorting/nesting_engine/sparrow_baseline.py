"""阶段2 §六：sparrow 基线验证 —— 拿 M1787 的"无约束几何上界"。

把 128 片喂给 sparrow（开源 SOTA，无服装约束、纯几何），拿到 density，
回答：90% 在 M1787 直筒款上到底可达吗。这决定 B 路径的现实目标排序。

输入：_output/sparrow_baseline/pieces_intermediate.json（pieces_export.py 产出）

每次运行除 density 外，还产出（同名前缀）：
  result_*_t{T}.json   —— 结果 + 每片 placement（可离线重画）
  *_t{T}.svg           —— 排料布局可视化（门幅 × 用布长度，按片型着色）
  *_t{T}_curve.json    —— anytime 收敛曲线原始数据（elapsed, phase, density, width）
  *_t{T}_curve.png     —— matplotlib 动态变化图（density vs 时间，区分探索/压缩阶段）

用法：
  python sparrow_baseline.py                  # 全 8 码 128 片 600s
  python sparrow_baseline.py --sizes 28       # 单码 16 片（先验证流程）
  python sparrow_baseline.py --time 3600      # 加长时间（看是否收敛）

参考：sparrow TROUSERS 基准 92.6%、SHIRTS 90.9%（arxiv 2509.13329）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time

from .. import paths

# 片型 → SVG 颜色（v0.3 实际 10 片型，区分度优先；前/后片是主角给深色）
# 色源：d3 category10（前片/后片/腰/前袋/后袋/机头/单排/火机袋/裤耳）+ 双排=#ff1493 deep pink。
# 机头=#bcbd22 橄榄（PRD US-023 仅显式列 单排/双排/火机袋/裤耳 4 色，机头补 d3 category10 末位色以满足
# 「屏幕所有 v0.3 片型彩色正确（无灰色 fallback）」AC；色值待版师屏幕定色）。
PTYPE_COLORS = {
    '前片':   '#1f77b4',   # 蓝（主角）
    '后片':   '#d62728',   # 红（主角）
    '腰':     '#2ca02c',   # 绿
    '前袋':   '#ff7f0e',   # 橙
    '后袋':   '#9467bd',   # 紫
    '机头':   '#bcbd22',   # 橄榄（d3 category10 末位色，PRD US-023 补位）
    '单排':   '#e377c2',   # 粉
    '双排':   '#ff1493',   # 深粉
    '火机袋': '#8c564b',   # 棕
    '裤耳':   '#17becf',   # 青
}
DEFAULT_COLOR = '#bbbbbb'


def _clean_polygon(poly, eps=0.01):
    """轻量预处理：去连续重复点（<eps），避免 sparrow "non-consecutive duplicate" 报错。

    注：sparrow 内部也会去严格连续重复点，这里多一层保险（密集折线可能有微抖动）。
    非连续重复点/自交这里不处理——若报错再针对性修。
    """
    if not poly:
        return poly
    out = [list(poly[0])]
    for x, y in poly[1:]:
        lx, ly = out[-1]
        if (x - lx) ** 2 + (y - ly) ** 2 > eps * eps:
            out.append([x, y])
    # 去首尾重复
    if len(out) > 1 and (out[0][0] - out[-1][0]) ** 2 + (out[0][1] - out[-1][1]) ** 2 < eps * eps:
        out.pop()
    return out


def _transform_polygon(poly, rotation_deg, translation):
    """sparrow 放置变换：先绕原点 (0,0) 旋转 rotation_deg 度，再平移 translation。

    与 PlacedItem 语义一致（rotation 后 apply translation）。0° 不变；180° → (-x,-y)。
    返回 list[(x,y)] 世界坐标（mm）。
    """
    rad = math.radians(rotation_deg)
    c, s = math.cos(rad), math.sin(rad)
    tx, ty = translation
    return [(x * c - y * s + tx, x * s + y * c + ty) for x, y in poly]


def _fmt(x):
    """浮点 → SVG 紧凑字符串（去多余 0）。"""
    return f'{x:.2f}'.rstrip('0').rstrip('.')


def _write_svg(out_path, *, placed, pid_meta, gate_mm, used_mm, density, title):
    """生成排料布局 SVG。

    viewBox = 用布长度(width,x) × 门幅(gate,y)，mm 单位。
    因 SVG y 轴向下而数据 y 轴向上，用一个 group transform translate(0,gate) scale(1,-1) 翻转。
    """
    W, H = used_mm, gate_mm
    # 收集出现的片型（用于图例，按面积排序）
    type_area = {}
    for pid, rotation, translation in placed:
        meta = pid_meta.get(pid, {})
        ptype = meta.get('ptype', '?')
        type_area[ptype] = type_area.get(ptype, 0) + meta.get('area_mm2', 0)
    legend_types = sorted(type_area, key=lambda t: -type_area[t])

    parts = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W:.1f} {H:.1f}" '
        f'width="{max(W/8, 1400):.0f}" height="{max(H/8, 360):.0f}" '
        f'font-family="sans-serif">'
    )
    # 标题块（在 y 翻转 group 外，用正常文字坐标）
    parts.append(
        f'<text x="8" y="-2" font-size="0" >placeholder</text>'  # 占位，避免 linter
    )
    parts = [p for p in parts if 'placeholder' not in p]

    # 背景 + 用布外框
    parts.append(f'<rect x="0" y="0" width="{W:.1f}" height="{H:.1f}" '
                 f'fill="#fafafa" stroke="#333" stroke-width="{max(W,H)*0.002:.1f}"/>')
    # 门幅刻度（左边标注）
    parts.append(f'<text x="4" y="{H*0.5:.1f}" font-size="{H*0.03:.0f}" '
                 f'fill="#666" transform="rotate(-90 4 {H*0.5:.1f})">'
                 f'门幅 {gate_mm:.0f}mm</text>')

    # y 翻转 group：内部直接用数据坐标
    parts.append(f'<g transform="translate(0,{H:.1f}) scale(1,-1)">')
    for pid, rotation, translation in placed:
        meta = pid_meta.get(pid, {})
        base = meta.get('polygon', [])
        if len(base) < 3:
            continue
        world = _transform_polygon(base, rotation, translation)
        pts = ' '.join(f'{_fmt(x)},{_fmt(y)}' for x, y in world)
        ptype = meta.get('ptype', '?')
        color = PTYPE_COLORS.get(ptype, DEFAULT_COLOR)
        parts.append(
            f'<polygon points="{pts}" fill="{color}" fill-opacity="0.55" '
            f'stroke="{color}" stroke-width="{max(W,H)*0.0015:.1f}"/>'
        )
    parts.append('</g>')

    # 图例（右上，正常 y 坐标系）
    lx = max(W - W * 0.18, W - 320)
    ly = 14
    step = H * 0.035
    parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="{H*0.028:.0f}" '
                 f'font-weight="bold" fill="#222">片型图例</text>')
    ly += step * 1.4
    for t in legend_types:
        color = PTYPE_COLORS.get(t, DEFAULT_COLOR)
        parts.append(f'<rect x="{lx:.1f}" y="{ly - step*0.7:.1f}" '
                     f'width="{step*1.2:.1f}" height="{step*1.2:.1f}" '
                     f'fill="{color}" fill-opacity="0.55" stroke="{color}"/>')
        parts.append(f'<text x="{lx + step*1.8:.1f}" y="{ly:.1f}" '
                     f'font-size="{H*0.025:.0f}" fill="#333">{t}</text>')
        ly += step

    parts.append('</svg>')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))


def _plot_curve(out_path, curve, *, final_density, final_used_mm, total_area_mm2, gate_mm,
                time_budget, title):
    """matplotlib 画 anytime 收敛曲线：density(%) vs elapsed(s)，按阶段着色 + best-so-far 包络。"""
    if not curve:
        print('  (曲线为空，ProgressQueue 未推送报告，跳过动态图)')
        return
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f'  (matplotlib 不可用，跳过动态图: {e})')
        return

    # 中文字体兜底（无则英文仍可读，不致命）
    try:
        plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
    except Exception:
        pass

    xs = [c['elapsed'] for c in curve]
    ys = [c['density'] * 100 for c in curve]
    phases = [c['phase'] for c in curve]
    phase_colors = {'exploring': '#1f77b4', 'compressing': '#ff7f0e', 'final': '#2ca02c'}

    fig, ax = plt.subplots(figsize=(11, 6))
    # 散点按阶段着色
    for ph in set(phases):
        px = [x for x, p in zip(xs, phases) if p == ph]
        py = [y for y, p in zip(ys, phases) if p == ph]
        ax.scatter(px, py, s=14, color=phase_colors.get(ph, '#888'),
                   alpha=0.55, label=f'{ph} ({len(px)})', zorder=2)
    # best-so-far 单调包络
    best = []
    cur = -1
    for y in ys:
        cur = max(cur, y)
        best.append(cur)
    ax.plot(xs, best, color='#d62728', linewidth=2.0, label='best-so-far', zorder=3)

    # 参考线
    ax.axhline(90, color='#444', linestyle='--', linewidth=1, alpha=0.7)
    ax.text(max(xs) * 0.02, 90.15, '90% 生死线', fontsize=9, color='#444')
    ax.axhline(final_density * 100, color='#2ca02c', linestyle=':', linewidth=1.2, alpha=0.8)
    ax.text(max(xs) * 0.02, final_density * 100 + 0.25,
            f'最终 {final_density*100:.2f}%', fontsize=9, color='#2ca02c')

    ax.set_xlabel('elapsed (s)')
    ax.set_ylabel('utilization (%)')
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='lower right', fontsize=9)
    # y 轴范围给点上下空间
    ymin = max(0, min(ys) - 3)
    ymax = max(93, max(ys) + 2)
    ax.set_ylim(ymin, ymax)
    ax.set_xlim(0, max(xs) * 1.02 + 1)

    # 右下角注释：用布、收敛信息
    last_t = xs[-1]
    note = (f'final density {final_density*100:.2f}%\n'
            f'用布 {final_used_mm/10:.1f} cm / 门幅 {gate_mm:.0f}mm\n'
            f'最后报告 @ {last_t:.0f}s / 预算 {time_budget}s')
    ax.annotate(note, xy=(0.98, 0.02), xycoords='axes fraction',
                ha='right', va='bottom', fontsize=9,
                bbox=dict(boxstyle='round,pad=0.4', fc='white', ec='#bbb', alpha=0.9))

    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f'  动态变化图 → {out_path}')


def solve_with_progress(instance, config):
    """用 ProgressQueue 在子线程求解，主线程 drain 采集 anytime 曲线。

    供 sparrow_baseline / sparrow_experiments 复用。返回 (sol, curve, elapsed_sec)。
    curve = [{elapsed, phase, report, density, width_mm}, ...]
    """
    import spyrrow
    queue = spyrrow.ProgressQueue()
    holder = {}
    t0 = time.time()

    def _solve():
        holder['sol'] = instance.solve(config, progress=queue)

    th = threading.Thread(target=_solve, daemon=True)
    th.start()

    curve = []
    last_log = 0.0
    while th.is_alive():
        for rtype, sol in queue.drain():
            curve.append({
                'elapsed': round(time.time() - t0, 2),
                'phase': rtype.phase_name(),
                'report': int(rtype),
                'density': float(sol.density),
                'width_mm': float(sol.width),
            })
        now = time.time() - t0
        if now - last_log >= 30:   # 每 30s 打个进度心跳
            if curve:
                cur_best = max(c['density'] for c in curve)
                print(f'  [{now:6.0f}s] 报告 {len(curve):4d} 条 | 当前 best density {cur_best*100:.2f}%')
            else:
                print(f'  [{now:6.0f}s] 报告 0 条（求解器尚未推送）')
            last_log = now
        time.sleep(0.5)
    th.join()
    # 收尾 drain（拿 Final）
    for rtype, sol in queue.drain():
        curve.append({
            'elapsed': round(time.time() - t0, 2),
            'phase': rtype.phase_name(),
            'report': int(rtype),
            'density': float(sol.density),
            'width_mm': float(sol.width),
        })
    return holder['sol'], curve, time.time() - t0


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--sizes', type=str, default='', help='逗号分隔码号，空=全部8码')
    ap.add_argument('--time', type=int, default=600, help='总计算时间(秒)')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--no-svg', action='store_true', help='跳过 SVG 输出')
    ap.add_argument('--no-curve', action='store_true', help='跳过曲线图输出')
    args = ap.parse_args()

    intermediate = paths.INTERMEDIATE
    with open(intermediate, encoding='utf-8') as f:
        doc = json.load(f)
    gate = float(doc['gate_mm'])
    pieces = doc['pieces']
    if args.sizes:
        want = {int(s) for s in args.sizes.split(',')}
        pieces = [p for p in pieces if p['size'] in want]
    total_area = sum(p['area_mm2'] for p in pieces)

    # pid → 元信息（SVG/变换要用原始 polygon + ptype）
    pid_meta = {p['pid']: p for p in pieces}

    print(f'== sparrow 基线验证 ==')
    print(f'{len(pieces)} 片 | 门幅 {gate}mm | 总面积 {total_area/1e6:.3f} m² | '
          f'理论100%用布 {total_area/gate/10:.1f}cm | 时间预算 {args.time}s')

    try:
        import spyrrow
    except ImportError:
        print('ERROR: spyrrow 未安装。pip install spyrrow', file=sys.stderr)
        sys.exit(1)

    items = []
    for p in pieces:
        poly = _clean_polygon(p['polygon'])
        if len(poly) < 3:
            print(f'  跳过 {p["pid"]}（顶点<3）')
            continue
        items.append(spyrrow.Item(
            id=p['pid'],
            shape=[(float(x), float(y)) for x, y in poly],
            demand=1,
            allowed_orientations=[0.0, 180.0],   # v0.3 布纹线 {0°,180°}
        ))
    print(f'构造 {len(items)} 个 item（每片 demand=1，{0}°/{180}° 姿态）')

    instance = spyrrow.StripPackingInstance(
        name=f'm1787_{"_".join(str(p["size"]) for p in pieces[:1]) or "all"}',
        strip_height=gate,
        items=items,
    )
    # num_workers（spyrrow 0.9.0 已修正拼写；旧版拼错成 num_wokers）；>4 反而质量更差（issue #113）
    config = spyrrow.StripPackingConfig(
        total_computation_time=args.time,
        seed=args.seed,
        num_workers=4,
    )

    sizes_tag = '_'.join(str(s) for s in sorted({p['size'] for p in pieces}))
    out_dir = paths.SPARROW_DIR
    os.makedirs(out_dir, exist_ok=True)
    stem = f'{sizes_tag}_t{args.time}'

    # ---- 用 ProgressQueue 在子线程求解，主线程 drain 采集 anytime 曲线 ----
    print(f'\n开始求解（预算 {args.time}s，后台线程跑，主线程采集 anytime 曲线）...')
    sol, curve, dt = solve_with_progress(instance, config)

    density = float(sol.density)
    used_mm = float(sol.width)
    print(f'\n== sparrow 结果 ==')
    print(f'density  = {density*100:.2f}%   ← 无约束几何上界')
    print(f'用布长度 = {used_mm/10:.1f} cm')
    print(f'耗时 {dt:.0f}s | anytime 报告 {len(curve)} 条')

    print(f'\n== 对比 ==')
    print(f'  stage1c(位图+弱SA) : 71.9%')
    print(f'  sparrow(本次)      : {density*100:.2f}%')
    print(f'  人工目标           : 93% = {total_area/(gate*0.93)/10:.1f}cm')
    print(f'  90%                : {total_area/(gate*0.9)/10:.1f}cm')
    print(f'  100%(理论)         : {total_area/gate/10:.1f}cm')

    # ---- 保存 result（含 placements，可离线重画）----
    placed = [(pi.id, pi.rotation, pi.translation) for pi in sol.placed_items]
    # 放置坐标范围检查（验证变换理解）
    if placed:
        all_xy = []
        for pid, rot, tr in placed:
            meta = pid_meta.get(pid)
            if meta:
                all_xy.extend(_transform_polygon(meta['polygon'], rot, tr))
        if all_xy:
            xs = [p[0] for p in all_xy]
            ys = [p[1] for p in all_xy]
            print(f'\n放置坐标范围: x[{min(xs):.0f},{max(xs):.0f}] '
                  f'y[{min(ys):.0f},{max(ys):.0f}]  (应 ≈ [0,{used_mm:.0f}]×[0,{gate:.0f}])')
            if max(ys) > gate + 1 or min(ys) < -1:
                print(f'  ⚠ y 越界门幅，旋转/平移变换理解可能有误')
    result = {
        'density': density, 'used_mm': used_mm, 'time_sec': args.time, 'elapsed': round(dt, 1),
        'n_pieces': len(pieces), 'gate_mm': gate, 'total_area_mm2': total_area,
        'seed': args.seed,
        'n_reports': len(curve),
        'placed_items': [
            {'id': pid, 'rotation': rot, 'translation': list(tr)}
            for pid, rot, tr in placed
        ],
    }
    res_path = os.path.join(out_dir, f'result_{stem}.json')
    with open(res_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'\n结果 → {res_path}')

    # ---- 保存曲线 JSON ----
    curve_path = os.path.join(out_dir, f'{stem}_curve.json')
    with open(curve_path, 'w', encoding='utf-8') as f:
        json.dump({
            'time_budget': args.time, 'elapsed': round(dt, 1),
            'gate_mm': gate, 'total_area_mm2': total_area,
            'final_density': density, 'final_used_mm': used_mm,
            'reports': curve,
        }, f, ensure_ascii=False, indent=1)
    print(f'曲线数据 → {curve_path}')

    # ---- SVG 排料布局 ----
    if not args.no_svg:
        svg_path = os.path.join(out_dir, f'{stem}.svg')
        _write_svg(svg_path, placed=placed, pid_meta=pid_meta, gate_mm=gate,
                   used_mm=used_mm, density=density,
                   title=f'sparrow {len(placed)}片 {density*100:.2f}% | 用布{used_mm/10:.1f}cm')
        print(f'排料布局 SVG → {svg_path}')

    # ---- matplotlib 动态变化图 ----
    if not args.no_curve:
        png_path = os.path.join(out_dir, f'{stem}_curve.png')
        _plot_curve(png_path, curve, final_density=density, final_used_mm=used_mm,
                    total_area_mm2=total_area, gate_mm=gate, time_budget=args.time,
                    title=f'sparrow anytime 收敛 ({len(placed)}片, 预算{args.time}s)')


if __name__ == '__main__':
    main()
