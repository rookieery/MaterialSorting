"""US-022 共享：裁片 A/B/C 标注 + (size, ptype) → label 映射。

供 ``web/server.py``（parse-dxf 响应 + commit-to-nesting intermediate）与
``nesting_engine/pieces_export.py``（baseline intermediate）共用，保证两条管线对同一
母版产出的 label 集合一致 —— 前端 ``qtyStore`` 以 label 为 key，后端 intermediate 的
label 必须与 parse 响应的 label 按 (size, ptype) 严格对齐，否则 demand 数量配错片型。

依赖方向合规：本模块仅 import 标准库，不依赖任何兄弟包（PieceOutline 是 duck-typed，
只读 ``polygon_mm / area_mm2 / block_name / piece_index / group_key / size`` 属性）。
上层 ``web`` 与同层 ``nesting_engine`` 均可 import。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable


def label_for(idx: int) -> str:
    """0→A, 1→B, ..., 25→Z, 26→AA, 27→AB ...（每码裁片数实测 ≤10，AA+ 仅兜底）。

    与 ``web/server.py._label_for`` 字节级一致 —— 本函数是该实现的单一真相源，
    server.py 的 ``_label_for`` 改为转发此处。
    """
    s = ''
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(ord('A') + rem) + s
    return s


def centroid(poly: list[tuple[float, float]]) -> tuple[float, float]:
    """顶点算术质心（用于稳定排序键）。空 polygon 兜底 (0,0)。"""
    if not poly:
        return (0.0, 0.0)
    sx = sum(x for x, _ in poly)
    sy = sum(y for _, y in poly)
    return (sx / len(poly), sy / len(poly))


def size_sort_key(size: int | None) -> tuple[int, int]:
    """码号排序键：None 殿后，其余按数值升序。"""
    return (1, 0) if size is None else (0, size)


def compute_size_ptype_labels(
    pieces: Iterable,
    gmap: dict[str, str],
    group_names: dict[str, str],
) -> dict[tuple[int | None, str], str]:
    """对 ``explore.collect_pieces`` 返回的 PieceOutline 列表计算 (size, ptype) → label。

    排序键与 ``web/server.py._build_parse_payload`` 完全一致：
        ``(-centroid_y, centroid_x, -area_mm2, block_name, piece_index)``
    → 上方 / 左 / 大片优先。每码内独立编号（不跨码续编）。

    gmap / group_names 与 ``dxf_parser.export_dxf.assign_group_no`` /
    ``GROUP_NAMES`` 同源 —— 同一 (group_key → gno → ptype) 链路。

    返回 ``{(size, ptype): label}``；ptype 为 None（gno 无 GROUP_NAMES 映射）的 piece
    不入字典（与 commit 路径 skip 语义一致）。同一 (size, ptype) 多 piece 时取首片
    的 label（M1787 实测 1:1，此处兜底防御）。
    """
    by_size: dict[int | None, list] = defaultdict(list)
    for p in pieces:
        by_size[p.size].append(p)

    out: dict[tuple[int | None, str], str] = {}
    for size in sorted(by_size.keys(), key=size_sort_key):
        members = by_size[size]
        members_sorted = sorted(
            members,
            key=lambda p: (
                -centroid(p.polygon_mm)[1],
                centroid(p.polygon_mm)[0],
                -p.area_mm2,
                p.block_name,
                p.piece_index,
            ),
        )
        for idx, p in enumerate(members_sorted):
            gno = gmap.get(p.group_key)
            if gno is None:
                continue
            ptype = group_names.get(gno)
            if ptype is None:
                continue
            key = (size, ptype)
            if key not in out:  # 同 (size, ptype) 多 piece 时取首片 label
                out[key] = label_for(idx)
    return out
