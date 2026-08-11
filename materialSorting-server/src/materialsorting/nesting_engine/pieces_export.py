"""把 128 片排料裁片 dump 成中间 JSON，供后续转 sparrow 输入格式。

不依赖 sparrow 格式：先导出全部信息（pid/ptype/size/side/polygon/bbox/area/顶点数/姿态），
sparrow 输入格式确认后，再写 intermediate → sparrow JSON 的映射。

用法：python pieces_export.py
输出：_output/sparrow_baseline/pieces_intermediate.json
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

from .. import paths
from ..nesting_bounds.load_pieces import load_nest_pieces, GATE_MM
from ..dxf_parser import explore
from ..dxf_parser.export_dxf import assign_group_no, GROUP_NAMES
from .labeling import compute_size_ptype_labels


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    out = paths.INTERMEDIATE
    os.makedirs(paths.SPARROW_DIR, exist_ok=True)

    pieces = load_nest_pieces(paths.PIECES_DIR)

    # US-022：为每片 NestPiece 标注 label（与 parse-dxf 响应同排序同标注）。
    # baseline CLI 解析母版 → 走与 _commit_to_nesting_sync 完全一致的 labeling 管线：
    # explore.collect_pieces → assign_group_no + GROUP_NAMES → compute_size_ptype_labels。
    # 母版缺失（paths.MASTER_DXF_GLOB 找不到）→ label 字段为 None，build_instance 回退
    # demand=1（向后兼容；dev 环境可能只有单裁片目录无母版）。
    size_ptype_label: dict[tuple[int | None, str], str] = {}
    master_path = explore.resolve_dxf(paths.MASTER_DXF_GLOB)
    if master_path is not None and master_path.exists():
        master_pieces = explore.collect_pieces(master_path)
        gmap = assign_group_no(master_pieces)
        size_ptype_label = compute_size_ptype_labels(master_pieces, gmap, GROUP_NAMES)

    doc = {
        'source': 'M1787 直筒款 8 码套排',
        'gate_mm': GATE_MM,
        'n_pieces': len(pieces),
        'total_area_mm2': round(sum(p.area_mm2 for p in pieces), 1),
        'pieces': [
            {
                'pid': p.pid,
                'ptype': p.ptype,
                'size': p.size,
                'side': p.side,
                'label': size_ptype_label.get((p.size, p.ptype)),
                'polygon': [[round(x, 3), round(y, 3)] for x, y in p.polygon],
                'bbox': [round(v, 2) for v in p.bbox],
                'area_mm2': round(p.area_mm2, 1),
                'n_verts': len(p.polygon),
                'allowed_angles': [0, 180],   # v0.3 布纹线约束
                # US-024：5 层渲染/导出透传字段（与 web/server._commit_to_nesting_sync 同 schema）。
                # data/m1787_直筒/*.dxf 由 ms-export-dxf 重新生成后含 layer14/8/4；旧 DXF 5 层为
                # 空/None，向后兼容（前端 layer-aware 渲染）。
                'net_polygon': [[round(x, 3), round(y, 3)] for x, y in p.net_polygon],
                'internal_lines': [
                    [[round(x, 3), round(y, 3)] for x, y in line]
                    for line in p.internal_lines
                ],
                'notches': [
                    [round(x, 3), round(y, 3), round(nx, 4), round(ny, 4)]
                    for x, y, nx, ny in p.notches
                ],
                'grain_line': (
                    [round(v, 3) for v in p.grain_line] if p.grain_line is not None else None
                ),
            }
            for p in pieces
        ],
    }
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)

    print(f'dumped {len(pieces)} pieces → {out}')
    print(f'gate {GATE_MM}mm | total_area {doc["total_area_mm2"]/1e6:.3f} m² '
          f'| 理论100%用布 {doc["total_area_mm2"]/GATE_MM/10:.1f}cm')
    # 顶点数分布：sparrow 要简单多边形，提前看有无异常（极多顶点/退化）
    vc = Counter(p['n_verts'] for p in doc['pieces'])
    print(f'顶点数分布: {sorted(vc.items())}')
    # 各片型最大 bbox（看大裁片尺寸，判断 sparrow 容器设置）
    by_type = {}
    for p in doc['pieces']:
        w = p['bbox'][2] - p['bbox'][0]
        h = p['bbox'][3] - p['bbox'][1]
        by_type.setdefault(p['ptype'], []).append((w, h))
    print('各片型 bbox(w×h mm) 代表值:')
    for t, wh in by_type.items():
        w = max(x[0] for x in wh)
        h = max(x[1] for x in wh)
        print(f'  {t:<6} 最大宽 {w:.0f} × 最大高 {h:.0f}  ({len(wh)} 片)')


if __name__ == '__main__':
    main()
