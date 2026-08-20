"""DXF 解析预览 / label 代表裁片纯函数（自 server.py 机械拆出，行为不变）。

三个函数都是「参数进、dict 出」的纯转换（无 server 模块全局依赖）：
  - ``_size_sort_key``：码号排序键（转发 ``nesting_engine.labeling``）；
  - ``_build_parse_payload``：``/api/parse-dxf`` 上传预览响应体；
  - ``_build_label_representatives``：每 g 码 RAW 代表裁片（intermediate
    ``label_representatives`` 与 ``/api/ptypes`` 的数据源）。

消费方：server.py（parse 路由 / commit 管线）与 tests（经 server re-import）。
"""
from __future__ import annotations

from ..nesting_engine.labeling import (
    size_sort_key,
    assign_codes,
)


def _size_sort_key(size: int | None) -> tuple[int, int]:
    """码号排序键：None 殿后，其余按数值升序（转发 ``nesting_engine.labeling``）。"""
    return size_sort_key(size)


def _build_parse_payload(doc_id: str, filename: str, pieces) -> dict:
    """把 collect_pieces_with_details 结果按码号分组 + 排序 + 赋 g01+ 裁片码。

    响应结构与前端契约（v2 label-only）一致：每片含 label/polygon/internal_lines/
    notches/net_polygon/grain_line，**无 name/ptype/paired**（中文名与配对概念已从
    契约删除）。polygon / net_polygon = [[x,y], ...]；internal_lines = [[[x,y], ...], ...]；
    notches = [[x,y,nx,ny], ...]；grain_line = [x1,y1,x2,y2] 或 null。

    排序 + 编号收敛到 ``labeling.assign_codes`` 单一真相源（g01+ 零填充；顺序赋码
    group_key 前置保证跨码同号；母版 block 名带显式编号时整体复用）。parse 与
    commit 各自对同一母版跑 ``assign_codes``，同一 ``(block_name, size, piece_index)``
    必得同码（AC#5），不再经 (size, ptype) 中转。
    """
    # g 码最先算（label 先行）；每码有序 [(piece, code), ...]。
    codes_by_size = assign_codes(pieces)

    sizes_out = []
    for size in sorted(codes_by_size.keys(), key=_size_sort_key):
        pieces_out = []
        for p, code in codes_by_size[size]:
            pieces_out.append({
                'label': code,
                'polygon': [[float(x), float(y)] for x, y in p.polygon_mm],
                'internal_lines': [
                    [[float(x), float(y)] for x, y in line]
                    for line in p.internal_lines
                ],
                'notches': [
                    [float(x), float(y), float(nx), float(ny)]
                    for x, y, nx, ny in p.notches
                ],
                'net_polygon': [[float(x), float(y)] for x, y in p.net_polygon],
                'grain_line': (
                    [float(v) for v in p.grain_line] if p.grain_line is not None else None
                ),
            })
        sizes_out.append({'size': size, 'pieces': pieces_out})

    return {'doc_id': doc_id, 'filename': filename, 'sizes': sizes_out}


def _build_label_representatives(pieces) -> dict:
    """每 g 码 RAW 代表裁片（与 ``_build_parse_payload`` 上传预览同口径）。

    供 GET /api/ptypes 渲染高级配置缩略图 / 放大预览。**刻意取原始坐标**（不走
    ``load_nest_pieces`` 的布纹对齐旋转）—— 否则纵向布纹线裁片（如腰 992×166）被
    旋转 ±90° 后在 64×64 方形缩略格里缩成 ~11px 细竖线，与上传预览不一致且不可辨认
    （US-018 AC#9 缩略图用于片型识别，应与上传预览同朝向）。布纹对齐是**排料求解**
    的需要（intermediate ``pieces`` 仍存变换后几何供 sparrow），与缩略图展示无关。

    代表选取 + 编号（与上传预览严格一致）：按码升序迭代 ``labeling.assign_codes``
    的每码有序（piece, code）列表（与 ``_build_parse_payload`` 赋号同源同序），每
    g 码取**最小码内首个**有效片（size 非 None，与 ``write_piece_dxf`` 写出条件
    一致）。返回 ``{label: {label, polygon, net_polygon, internal_lines, notches,
    grain_line}}``（键 = g 码）。
    """
    codes_by_size = assign_codes(pieces)

    reps: dict[str, dict] = {}
    for size in sorted(codes_by_size.keys(), key=_size_sort_key):
        for p, code in codes_by_size[size]:
            if p.size is None:
                continue
            if code in reps:
                continue
            reps[code] = {
                'label': code,
                'polygon': [[round(float(x), 3), round(float(y), 3)] for x, y in p.polygon_mm],
                'net_polygon': [[round(float(x), 3), round(float(y), 3)] for x, y in p.net_polygon],
                'internal_lines': [
                    [[round(float(x), 3), round(float(y), 3)] for x, y in line]
                    for line in p.internal_lines
                ],
                'notches': [
                    [round(float(x), 3), round(float(y), 3), round(float(nx), 4), round(float(ny), 4)]
                    for x, y, nx, ny in p.notches
                ],
                'grain_line': (
                    [round(float(v), 3) for v in p.grain_line] if p.grain_line is not None else None
                ),
            }
    return reps
