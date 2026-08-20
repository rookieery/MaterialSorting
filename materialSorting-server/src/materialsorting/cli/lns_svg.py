"""LNS 前后对比 SVG 渲染（lns_compare.svg：双面板 + 尺码图例，坐标/配色与其余排料 SVG 同口径）。"""
from __future__ import annotations

from ..nesting_engine.sparrow_baseline import size_color
from .lns_bands import _world_polygon


# ---------------------------------------------------------------- 对比 SVG


def _fmt(x: float) -> str:
    """浮点 → SVG 紧凑字符串（与 sparrow_baseline._fmt 同口径）。"""
    return ('%.2f' % x).rstrip('0').rstrip('.')


def write_compare_svg(out_path, *, before, after, pieces_by_id, gate_mm,
                      title='LNS 前后对比'):
    """前后双面板对比 SVG（``run_dir/lns_compare.svg``）。

    - 坐标口径与其余排料 SVG 一致：viewBox 毫米、每面板一个
      ``translate(0, 面板底) scale(1,-1)`` 翻转组（数据 y 向上，与 PNG / R12-DXF
      导出同口径）；
    - 配色 ``size_color``（尺码 16 色循环单一真相源，同码同色跨片型一致）；
    - 面板题注（正常 y 坐标系）：caption + width + 原面积口径 density；
    - 两面板共用宽度标尺（取 max(width)），缩短量一眼可对照。

    ``before`` / ``after`` 形如 ``{'placed': [...], 'width_mm': W, 'density': d,
    'caption': 'LNS 前'}``；``pieces_by_id`` 为 intermediate pid → piece 映射
    （原始轮廓渲染，与导出同源）。
    """
    gate = float(gate_mm)
    W = max(float(before['width_mm']), float(after['width_mm']), 1.0)
    cap = gate * 0.075 + 30.0            # 题注带高（mm 画面单位）
    mx = gate * 0.03
    legend_w = gate * 0.24
    font = max(gate * 0.022, 12.0)
    title_h = font * 1.9
    svg_w = W + 2 * mx + legend_w
    svg_h = title_h + 2 * (cap + gate) + 3 * mx

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.1f %.1f" '
        'width="%.0f" height="%.0f" font-family="sans-serif">'
        % (svg_w, svg_h, svg_w / 8, svg_h / 8),
        '<text x="%.1f" y="%.1f" font-size="%.0f" fill="#111" '
        'font-weight="bold">%s</text>' % (mx, title_h * 0.72, font * 1.2, title),
    ]
    for i, lay in enumerate((before, after)):
        oy = title_h + mx + i * (cap + gate + mx) + cap
        ox = mx
        w = max(float(lay['width_mm']), 1.0)
        caption = '%s：width=%.0fmm  density=%.2f%%' % (
            lay.get('caption', ''), float(lay['width_mm']), float(lay['density']) * 100)
        parts.append(
            '<text x="%.1f" y="%.1f" font-size="%.0f" fill="#222" '
            'font-weight="bold">%s</text>' % (ox, oy - cap * 0.45, font, caption))
        parts.append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#fafafa" '
            'stroke="#333" stroke-width="%.1f"/>' % (ox, oy, w, gate, max(W, gate) * 0.002))
        parts.append('<g transform="translate(%.1f,%.1f) scale(1,-1)">' % (ox, oy + gate))
        for it in lay['placed']:
            p = pieces_by_id.get(it['id'])
            if p is None or len(p['polygon']) < 3:
                continue
            world = _world_polygon(p, it.get('rotation', 0.0),
                                   it.get('translation', [0, 0]))
            pts = ' '.join('%s,%s' % (_fmt(x), _fmt(y)) for x, y in world)
            color = size_color(p.get('size'))
            parts.append(
                '<polygon points="%s" fill="%s" fill-opacity="0.55" '
                'stroke="%s" stroke-width="%.1f"/>' % (pts, color, color,
                                                       max(W, gate) * 0.0015))
        parts.append('</g>')

    # 图例（右侧整列，正常 y 坐标系）：两面板出现的尺码并集，数值序
    sizes = sorted({(pieces_by_id.get(it['id']) or {}).get('size')
                    for lay in (before, after) for it in lay['placed']} - {None})
    lx = mx + W + mx * 0.6
    ly = title_h + mx + cap
    step = gate * 0.035
    if sizes:
        parts.append('<text x="%.1f" y="%.1f" font-size="%.0f" '
                     'font-weight="bold" fill="#222">尺码图例</text>' % (lx, ly, font))
        ly += step * 1.4
        for t in sizes:
            color = size_color(t)
            parts.append(
                '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" '
                'fill-opacity="0.55" stroke="%s"/>'
                % (lx, ly - step * 0.7, step * 1.2, step * 1.2, color, color))
            parts.append('<text x="%.1f" y="%.1f" font-size="%.0f" '
                         'fill="#333">%s</text>' % (lx + step * 1.8, ly, font * 0.9, t))
            ly += step
    parts.append('</svg>')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))
