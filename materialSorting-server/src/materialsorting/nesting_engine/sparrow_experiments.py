"""sparrow 前置实验②③：量化"旋转公差"与"重合公差"的收益上界。

baseline = 实验① 600s {0,180} 不腐蚀 = 85.79%（result_{tag}_t600.json）。

实验② 旋转公差：allowed_orientations 全部放开为 None（自由旋转）。
  → 多姿态杠杆的绝对上界（注意：完全放开布纹线，非工艺可达；回答"+2pp 还是 +5pp"）。
实验③ 重合公差：内部裁片（单排/双排/火机袋/裤耳，v0.3 允许 5-10mm 重合）轮廓向内腐蚀 d mm。
  → "sparrow 白扔的重合空间"多大。density 用**原面积**算（腐蚀只影响排料紧度，不缩面积）。

用法：
  python sparrow_experiments.py --exp free_rot        # 实验②
  python sparrow_experiments.py --exp erode --d 5      # 实验③ 5mm
  python sparrow_experiments.py --exp erode --d 10     # 实验③ 10mm
  python sparrow_experiments.py --exp all              # ② + ③-5 + ③-10 串行
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .. import paths
from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
from .sparrow_baseline import (
    _clean_polygon, _write_svg, _plot_curve, solve_with_progress,
)

OUT = paths.SPARROW_DIR
INTERMEDIATE = paths.INTERMEDIATE

# v0.3 内部裁片（允许 5-10mm 实质重合 / 8-45° 旋转）
INTERNAL_TYPES = {'单排', '双排', '火机袋', '裤耳'}
STEM_ALL = '28_29_30_31_33_34_35_36'


def erode_polygon(poly, d):
    """shapely 向内腐蚀 d mm，返回外环坐标。腐蚀失败/变空则回退原片。"""
    from shapely.geometry import Polygon
    p = Polygon(poly)
    if not p.is_valid:
        p = p.buffer(0)
    eroded = p.buffer(-d)
    if eroded.is_empty or eroded.area < 1.0:
        return [list(c) for c in poly]
    biggest = eroded
    if eroded.geom_type == 'MultiPolygon':
        biggest = max(eroded.geoms, key=lambda x: x.area)
    coords = list(biggest.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]   # 去闭合尾点
    return [list(c) for c in coords]


def build_pieces(doc, exp, erode_d):
    """按实验配置变换 pieces，返回 (items_meta, total_original_area, n_internal_eroded)。

    items_meta = [{pid, ptype, size, polygon(变换后), area_mm2(原), allowed_orientations}]
    正交对照：free_rot 只改旋转不腐蚀；erode 只腐蚀内部、旋转保持 {0,180}；
              erode_rot 组合（阶段0）：内部腐蚀 d mm + 内部自由旋转，外部 {0,180}。
    """
    out, n_eroded = [], 0
    for p in doc['pieces']:
        poly = p['polygon']
        orientations = [0.0, 180.0]
        if exp == 'free_rot':
            orientations = None
        elif exp == 'v0_rot':
            # v0.3 规则：外部{0,180}（布纹线硬约束）+ 内部自由旋转（8-45° 公差上界）
            orientations = None if p['ptype'] in INTERNAL_TYPES else [0.0, 180.0]
        elif exp == 'erode' and p['ptype'] in INTERNAL_TYPES:
            poly = erode_polygon(poly, erode_d)
            n_eroded += 1
        elif exp == 'erode_rot':
            # 阶段0组合实验：内部裁片腐蚀 d mm（=允许重合）+ 自由旋转（v0.3 旋转公差上界）
            if p['ptype'] in INTERNAL_TYPES:
                poly = erode_polygon(poly, erode_d)
                n_eroded += 1
                orientations = None
            # 外部裁片保持 {0,180}
        out.append({
            'pid': p['pid'], 'ptype': p['ptype'], 'size': p['size'],
            'polygon': poly, 'area_mm2': p['area_mm2'],
            'allowed_orientations': orientations,
        })
    total_orig = sum(p['area_mm2'] for p in doc['pieces'])
    return out, total_orig, n_eroded


def run_one(doc, gate, exp, erode_d, time_budget, seed):
    import spyrrow
    if exp == 'free_rot':
        tag = 'free_rot'
    elif exp == 'v0_rot':
        tag = 'v0_rot'
    elif exp == 'erode_rot':
        tag = f'erode{erode_d}_rot'
    else:
        tag = f'erode{erode_d}'
    print(f'\n{"=" * 60}')
    print(f'== 实验 {tag}（预算 {time_budget}s）==')
    items_meta, total_orig, n_eroded = build_pieces(doc, exp, erode_d)
    if exp == 'erode':
        print(f'内部裁片腐蚀 {erode_d}mm：{n_eroded} 片（{", ".join(sorted(INTERNAL_TYPES))}）')
    elif exp == 'erode_rot':
        print(f'阶段0组合：内部裁片腐蚀 {erode_d}mm + 自由旋转（{n_eroded} 片），外部 {{0,180}}')
    elif exp == 'free_rot':
        print('全部自由旋转（多姿态绝对上界，非工艺可达）')
    elif exp == 'v0_rot':
        print('v0.3 旋转规则：外部{0,180}（布纹线硬约束）+ 内部自由旋转（模拟 8-45° 公差上界）')

    items = []
    for m in items_meta:
        poly = _clean_polygon(m['polygon'])
        if len(poly) < 3:
            continue
        items.append(spyrrow.Item(
            id=m['pid'],
            shape=[(float(x), float(y)) for x, y in poly],
            demand=1,
            allowed_orientations=m['allowed_orientations'],
        ))
    # 有效排料宽度 = min(门幅, 绘图仪可写幅宽)（与 web/solver 同口径；密度仍按 gate）
    instance = spyrrow.StripPackingInstance(
        name=f'm1787_{tag}', strip_height=min(gate, PLOT_SAFE_MAX_Y_MM), items=items)
    config = spyrrow.StripPackingConfig(
        total_computation_time=time_budget, seed=seed, num_workers=4)

    sol, curve, dt = solve_with_progress(instance, config)
    used_mm = float(sol.width)
    real_density = total_orig / (used_mm * gate)        # 原面积口径（腐蚀不缩面积）
    sparrow_density = float(sol.density)                # 腐蚀后面积口径（sparrow 自报）

    print(f'\n== {tag} 结果 ==')
    print(f'real density(原面积)      = {real_density*100:.2f}%')
    print(f'sparrow density(腐蚀后面积) = {sparrow_density*100:.2f}%')
    print(f'用布 = {used_mm/10:.1f} cm | 耗时 {dt:.0f}s | 报告 {len(curve)} 条')

    placed = [(pi.id, pi.rotation, pi.translation) for pi in sol.placed_items]
    pid_meta = {m['pid']: m for m in items_meta}
    stem = f'exp_{tag}_t{time_budget}_s{seed}'

    result = {
        'exp': tag, 'density_real': real_density, 'density_sparrow': sparrow_density,
        'used_mm': used_mm, 'time_sec': time_budget, 'elapsed': round(dt, 1),
        'n_pieces': len(items_meta), 'n_eroded': n_eroded,
        'erode_mm': erode_d if exp in ('erode', 'erode_rot') else 0,
        'gate_mm': gate, 'total_area_original_mm2': total_orig, 'seed': seed,
    }
    with open(os.path.join(OUT, f'result_{stem}.json'), 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, f'{stem}_curve.json'), 'w', encoding='utf-8') as f:
        json.dump({'time_budget': time_budget, 'elapsed': round(dt, 1), 'gate_mm': gate,
                   'total_area_mm2': total_orig, 'final_density': real_density,
                   'final_used_mm': used_mm, 'reports': curve},
                  f, ensure_ascii=False, indent=1)
    _write_svg(os.path.join(OUT, f'{stem}.svg'), placed=placed, pid_meta=pid_meta,
               gate_mm=gate, used_mm=used_mm, density=real_density,
               title=f'exp {tag} {real_density*100:.2f}% | 用布{used_mm/10:.1f}cm')
    _plot_curve(os.path.join(OUT, f'{stem}_curve.png'), curve, final_density=real_density,
                final_used_mm=used_mm, total_area_mm2=total_orig, gate_mm=gate,
                time_budget=time_budget,
                title=f'实验{tag} anytime ({len(placed)}片, {time_budget}s)')
    print(f'产物前缀 → {os.path.join(OUT, stem)}.*')
    return result


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--exp', default='all', choices=['free_rot', 'v0_rot', 'erode', 'erode_rot', 'all'])
    ap.add_argument('--d', type=int, default=5, help='腐蚀深度 mm（实验③，--exp erode 时生效）')
    ap.add_argument('--time', type=int, default=600)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--seeds', type=str, default='',
                    help='逗号分隔多 seed（如 0,1,2,3,4）；给定时对 --exp 跑多 seed 并汇总方差/破90比例')
    args = ap.parse_args()

    with open(INTERMEDIATE, encoding='utf-8') as f:
        doc = json.load(f)
    gate = float(doc['gate_mm'])

    baseline_path = os.path.join(OUT, f'result_{STEM_ALL}_t{args.time}.json')
    baseline = json.load(open(baseline_path, encoding='utf-8')) if os.path.exists(baseline_path) else None

    if args.seeds:  # 多 seed 模式：对 args.exp 跑多 seed，汇总方差
        import statistics
        seeds_list = [int(s) for s in args.seeds.split(',')]
        ms_results = []
        for sd in seeds_list:
            print(f'\n>>> seed {sd} / exp={args.exp} <<<')
            ms_results.append(run_one(doc, gate, args.exp, args.d, args.time, sd))
        densities = [r['density_real'] * 100 for r in ms_results]
        used_cm = [r['used_mm'] / 10 for r in ms_results]
        print(f'\n{"=" * 60}')
        print(f'== 多 seed 汇总：{args.exp}（{len(seeds_list)} seeds, {args.time}s）==')
        print(f'{"seed":>6} | {"real密度":>9} | {"用布cm":>7}')
        for sd, d, u in zip(seeds_list, densities, used_cm):
            flag = '  <- 破90' if d >= 90.0 else ''
            print(f'{sd:>6} | {d:>8.2f}% | {u:>6.1f}{flag}')
        print(f'  min {min(densities):.2f}% / max {max(densities):.2f}% / '
              f'mean {statistics.mean(densities):.2f}% / std {statistics.pstdev(densities):.2f}pp')
        n_ge90 = sum(1 for d in densities if d >= 90.0)
        print(f'  破 90% 的 seed：{n_ge90}/{len(seeds_list)}')
        ms_summary = {
            'exp': args.exp, 'erode_d': args.d, 'time_sec': args.time,
            'seeds': seeds_list, 'densities': densities, 'used_cm': used_cm,
            'min': min(densities), 'max': max(densities),
            'mean': statistics.mean(densities), 'std_pp': statistics.pstdev(densities),
            'n_ge90': n_ge90,
        }
        ms_path = os.path.join(OUT, f'multiseed_{args.exp}_d{args.d}_t{args.time}.json')
        with open(ms_path, 'w', encoding='utf-8') as f:
            json.dump(ms_summary, f, ensure_ascii=False, indent=2)
        print(f'  汇总 -> {ms_path}')
        return

    results = []
    if args.exp == 'free_rot':
        results.append(run_one(doc, gate, 'free_rot', 0, args.time, args.seed))
    if args.exp in ('v0_rot', 'all'):
        results.append(run_one(doc, gate, 'v0_rot', 0, args.time, args.seed))
    if args.exp in ('erode', 'all'):
        for d in ([5, 10] if args.exp == 'all' else [args.d]):
            results.append(run_one(doc, gate, 'erode', d, args.time, args.seed))
    if args.exp in ('erode_rot', 'all'):
        # 阶段0组合实验：all 模式用 d=10，单独模式用 --d（默认10）
        d = 10 if args.exp == 'all' else args.d
        results.append(run_one(doc, gate, 'erode_rot', d, args.time, args.seed))

    # 汇总对比
    print(f'\n{"=" * 60}')
    print(f'== 实验②③汇总（baseline = 实验① {args.time}s {{0°,180°}} 不腐蚀）==')
    base_d = (baseline['density'] if baseline else 0.8579) * 100
    base_used = (baseline['used_mm'] if baseline else 7390.0) / 10
    print(f'{"实验":<12} | {"real密度":>9} | {"用布cm":>7} | {"vs base":>9}')
    print(f'{"-" * 12} | {"-" * 9} | {"-" * 7} | {"-" * 9}')
    print(f'{"baseline":<12} | {base_d:>8.2f}% | {base_used:>6.1f} | {"—":>9}')
    for r in results:
        dpp = r['density_real'] * 100 - base_d
        print(f'{r["exp"]:<12} | {r["density_real"]*100:>8.2f}% | {r["used_mm"]/10:>6.1f} | {dpp:+8.2f}pp')

    with open(os.path.join(OUT, f'experiments_summary_t{args.time}.json'), 'w', encoding='utf-8') as f:
        json.dump({'baseline_density': baseline['density'] if baseline else None,
                   'baseline_used_mm': baseline['used_mm'] if baseline else None,
                   'time_budget': args.time,
                   'internal_types': sorted(INTERNAL_TYPES),
                   'experiments': results}, f, ensure_ascii=False, indent=2)
    print(f'\n汇总 → {os.path.join(OUT, f"experiments_summary_t{args.time}.json")}')


if __name__ == '__main__':
    main()
