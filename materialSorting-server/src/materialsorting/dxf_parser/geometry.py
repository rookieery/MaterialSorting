"""纯几何算子（不依赖 ezdxf，可独立单测）。

所有函数对 list[tuple[float,float]] 多边形操作。顶点原样保留，不做抽稀/合并/平滑。
"""
from __future__ import annotations

import math


def polygon_perimeter(pts: list[tuple[float, float]]) -> float:
    """闭合多边形周长（自动连接首尾）。"""
    n = len(pts)
    if n < 2:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def polygon_area(pts: list[tuple[float, float]]) -> float:
    """多边形面积(mm²)，shoelace 取绝对值。"""
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def bbox_of(pts: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """(minx, miny, maxx, maxy)。"""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def point_in_polygon(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    """射线法判断点是否在多边形内。"""
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_inter = (xj - xi) * (y - yi) / (yj - yi + 1e-18) + xi
            if x < x_inter:
                inside = not inside
        j = i
    return inside


def line_midpoint(p1: tuple[float, float], p2: tuple[float, float]) -> tuple[float, float]:
    return ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)


def line_angle_deg(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """线段与水平夹角(度, atan2)。"""
    return math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))


def match_grain(
    grain_lines: list[tuple[float, float, float, float]],
    polygons: list[list[tuple[float, float]]],
) -> list[tuple[float, float, float, float] | None]:
    """把每条布纹线按"中点落在哪片多边形内"配给该片。

    返回与 polygons 等长的列表，每项为配对的 grain_line 或 None。
    一条布纹线只配给第一个命中的、且尚未配对的多边形。
    """
    result: list[tuple[float, float, float, float] | None] = [None] * len(polygons)
    for gl in grain_lines:
        mid = line_midpoint((gl[0], gl[1]), (gl[2], gl[3]))
        for i, poly in enumerate(polygons):
            if result[i] is None and point_in_polygon(mid, poly):
                result[i] = gl
                break
    return result
