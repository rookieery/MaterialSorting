"""US-003: 母版深度解析（collect_pieces_with_details）。

复用 ``explore.collect_pieces`` 拿到 layer1 毛版外轮廓 + layer7 布纹线（match_grain），
对每个 block 二次扫描其余 layer 还原单片全部信息：

- layer14 POLYLINE → ``net_polygon``（按顶点质心归属到 outline；1:1，单片单净版）
- layer8  POLYLINE → ``internal_lines``（按质心归属；多线/片）
- layer4  POINT    → ``notches``（先 point-in-polygon，失败回退最近边；沿所属轮廓
  边法线存 (x, y, nx, ny)，渲染时画定长线段）

layer 映射集中在 ``LAYER_MAPPING`` 常量；layer 2/3/13 不提取（语义未定/非刀口密点，
版师 2026-08-10 确认）。仅依赖 dxf_parser 内部模块 + 标准库，**不 import 兄弟包**。

CLI 冒烟::

    python -m materialsorting.dxf_parser.collect <dxf_path> [--verbose]
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

from . import geometry, reader
from .explore import collect_pieces
from .model import PieceOutline


# 母版 layer 语义映射（版师 2026-08-10 确认；5156 与 M1787 一致）。
#   毛版=1, 净版=14, 内部线=8, 布纹线=7, 刀口=4
# layer 2/3/13 不提取（参考点/轮廓密点/未定语义，非刀口）。
LAYER_MAPPING: dict[str, str] = {
    "outline": "1",
    "net": "14",
    "internal": "8",
    "grain": "7",
    "notch": "4",
}


# ---------------------------------------------------------------- 几何算子

def _signed_area(poly: list[tuple[float, float]]) -> float:
    """Shoelace 带符号面积（>0 = CCW，<0 = CW）；用于法线朝向修正。"""
    n = len(poly)
    s = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _nearest_edge_with_normal(
    pt: tuple[float, float],
    poly: list[tuple[float, float]],
    signed_area: float,
) -> tuple[int, float, float, float]:
    """对 ``pt`` 找 ``poly`` 上最近边，返回 (edge_index, distance, nx, ny)。

    ``nx, ny`` 是该边的**单位外法线**：CCW(signed_area>0) 取 (dy,-dx)/len；
    CW 取反。退化边（零长度）返回 (0,0) 法线。
    """
    x, y = pt
    n = len(poly)
    best_idx = 0
    best_dist = float("inf")
    best_nx = 0.0
    best_ny = 0.0
    sign = 1.0 if signed_area > 0 else -1.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        dx = x2 - x1
        dy = y2 - y1
        seg_len2 = dx * dx + dy * dy
        if seg_len2 < 1e-12:
            t = 0.0
            seg_len = 0.0
        else:
            t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / seg_len2))
            seg_len = math.sqrt(seg_len2)
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        d = math.hypot(x - proj_x, y - proj_y)
        if d < best_dist:
            best_dist = d
            best_idx = i
            if seg_len < 1e-9:
                best_nx = 0.0
                best_ny = 0.0
            else:
                best_nx = sign * dy / seg_len
                best_ny = -sign * dx / seg_len
    return best_idx, best_dist, best_nx, best_ny


def _centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    """顶点算术质心（用于 net/internal POLYLINE 归属判断）。"""
    n = len(pts)
    if n == 0:
        return (0.0, 0.0)
    sx = 0.0
    sy = 0.0
    for x, y in pts:
        sx += x
        sy += y
    return (sx / n, sy / n)


def _assign_notch(
    pt: tuple[float, float],
    outlines: list[tuple[int, list[tuple[float, float]], float]],
) -> tuple[int, float, float] | None:
    """把刀口点归属到某个 outline，返回 (piece_index, nx, ny)。

    Pass 1: 严格 point-in-polygon 命中即返回该 outline 最近边法线。
    Pass 2: 全部 outline 都不包含点（边界/外侧点），取所有 outline 中最近边所属片。
    """
    # Pass 1: 严格包含
    for pi, poly, sa in outlines:
        if geometry.point_in_polygon(pt, poly):
            _, _, nx, ny = _nearest_edge_with_normal(pt, poly, sa)
            return pi, nx, ny
    # Pass 2: 最近边
    best_pi: int | None = None
    best_dist = float("inf")
    best_nx = 0.0
    best_ny = 0.0
    for pi, poly, sa in outlines:
        _, dist, nx, ny = _nearest_edge_with_normal(pt, poly, sa)
        if dist < best_dist:
            best_dist = dist
            best_pi = pi
            best_nx = nx
            best_ny = ny
    if best_pi is None:
        return None
    return best_pi, best_nx, best_ny


# ---------------------------------------------------------------- 主流程

def collect_pieces_with_details(path: str | Path) -> list[PieceOutline]:
    """从母版 DXF 还原每片裁片的毛版/净版/内部线/刀口/布纹线。

    Args:
        path: 母版 DXF 路径（str 或 Path）。

    Returns:
        ``PieceOutline`` 列表（顺序与 ``explore.collect_pieces`` 一致），新字段
        ``internal_lines`` / ``notches`` / ``net_polygon`` 已填充。
    """
    path = Path(path)
    # 复用 explore.collect_pieces：layer1 毛版外轮廓 + layer7 布纹线（match_grain）。
    pieces = collect_pieces(path)
    if not pieces:
        return []

    # 索引：(block_name_raw, piece_index) -> PieceOutline（写回新字段用）。
    piece_by_key: dict[tuple[str, int], PieceOutline] = {
        (p.block_name_raw, p.piece_index): p for p in pieces
    }
    # 同 block 内 outline 列表（按 piece_index 升序）：(piece_index, polygon, signed_area)。
    block_outlines: dict[str, list[tuple[int, list[tuple[float, float]], float]]] = defaultdict(list)
    for p in pieces:
        sa = _signed_area(p.polygon_mm)
        block_outlines[p.block_name_raw].append((p.piece_index, p.polygon_mm, sa))
    for k in block_outlines:
        block_outlines[k].sort(key=lambda item: item[0])

    # 二次扫描：每个 block 抽 layer14/layer8/layer4 实体后按几何归属到 outline。
    doc = reader.load_doc(str(path))
    detail_layers = {LAYER_MAPPING["net"], LAYER_MAPPING["internal"], LAYER_MAPPING["notch"]}

    for block in doc.blocks:
        if block.name.startswith("*"):
            continue
        outlines = block_outlines.get(block.name)
        if not outlines:
            continue  # 无 layer1 毛版的 block（collect_pieces 已跳过）

        net_polys: list[list[tuple[float, float]]] = []
        internal_polys: list[list[tuple[float, float]]] = []
        notch_points: list[tuple[float, float]] = []
        for e in reader.iter_block_entities(block, layers=detail_layers):
            layer = str(e.dxf.layer)
            if layer == LAYER_MAPPING["net"] and e.dxftype() == "POLYLINE":
                pts = reader.polyline_points(e)
                if pts and len(pts) >= 2:
                    net_polys.append([(float(x), float(y)) for x, y in pts])
            elif layer == LAYER_MAPPING["internal"] and e.dxftype() == "POLYLINE":
                pts = reader.polyline_points(e)
                if pts and len(pts) >= 2:
                    internal_polys.append([(float(x), float(y)) for x, y in pts])
            elif layer == LAYER_MAPPING["notch"] and e.dxftype() == "POINT":
                try:
                    loc = e.dxf.location
                    notch_points.append((float(loc.x), float(loc.y)))
                except Exception:
                    continue

        # layer14 净版：质心归属；1:1，每片最多 1 条（多条时取首条）。
        net_by_piece: dict[int, list[tuple[float, float]]] = {}
        for pts in net_polys:
            c = _centroid(pts)
            for pi, poly, _sa in outlines:
                if geometry.point_in_polygon(c, poly):
                    net_by_piece.setdefault(pi, pts)
                    break

        # layer8 内部线：质心归属；多线/片。
        internal_by_piece: dict[int, list[list[tuple[float, float]]]] = defaultdict(list)
        for pts in internal_polys:
            c = _centroid(pts)
            for pi, poly, _sa in outlines:
                if geometry.point_in_polygon(c, poly):
                    internal_by_piece[pi].append(pts)
                    break

        # layer4 刀口：先 point-in-polygon，失败回退最近边。
        notch_by_piece: dict[int, list[tuple[float, float, float, float]]] = defaultdict(list)
        for pt in notch_points:
            res = _assign_notch(pt, outlines)
            if res is None:
                continue
            pi, nx, ny = res
            notch_by_piece[pi].append((pt[0], pt[1], nx, ny))

        # 写回 PieceOutline
        for pi, _poly, _sa in outlines:
            piece = piece_by_key.get((block.name, pi))
            if piece is None:
                continue
            piece.internal_lines = internal_by_piece.get(pi, [])
            piece.notches = notch_by_piece.get(pi, [])
            piece.net_polygon = net_by_piece.get(pi, [])

    return pieces


# ---------------------------------------------------------------- CLI

def main() -> None:
    """CLI 冒烟：打印每码裁片数 + 各字段计数。"""
    # Windows 终端默认 GBK，重定向/管道捕获时强制 UTF-8，避免中文乱码。
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="母版深度解析（US-003 collect_pieces_with_details）")
    ap.add_argument("dxf", help="母版 DXF 路径")
    ap.add_argument("--verbose", "-v", action="store_true", help="逐片打印字段计数")
    args = ap.parse_args()

    dxf_path = Path(args.dxf)
    if not dxf_path.exists():
        print(f"[ERROR] 找不到 DXF: {args.dxf}", file=sys.stderr)
        sys.exit(1)

    print(f"读取母版: {dxf_path.name}")
    pieces = collect_pieces_with_details(dxf_path)
    print(f"提取裁片: {len(pieces)} 片\n")

    by_size: dict[int | None, list[PieceOutline]] = defaultdict(list)
    for p in pieces:
        by_size[p.size].append(p)

    header = f"{'码号':<8}{'片数':<6}{'总internal':<14}{'总notch':<10}{'总net':<8}"
    print(header)
    for size in sorted(by_size.keys(), key=lambda s: (s is None, s if s else 0)):
        members = by_size[size]
        n_internal = sum(len(p.internal_lines) for p in members)
        n_notch = sum(len(p.notches) for p in members)
        n_net = sum(1 for p in members if p.net_polygon)
        size_str = str(size) if size is not None else "?"
        print(f"{size_str:<8}{len(members):<6}{n_internal:<14}{n_notch:<10}{n_net:<8}")

    if args.verbose:
        print()
        for p in pieces:
            print(
                f"  - {p.block_name}#{p.piece_index} size={p.size}: "
                f"internal={len(p.internal_lines)} notch={len(p.notches)} "
                f"net={'Y' if p.net_polygon else 'N'} grain={'Y' if p.grain_line else 'N'}"
            )


if __name__ == "__main__":
    main()
