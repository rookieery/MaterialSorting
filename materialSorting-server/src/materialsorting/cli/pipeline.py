"""配置驱动的 commit 管线编排（CLI 侧镜像 ``web/server._commit_to_nesting_sync``）。

``commit_from_config(cfg, run_dir)`` 在**独立时间戳 run_dir**（``out/config_runs/
<run_name>_<YYYYMMDD-HHMMSS>/``）内跑通「母版解析 → g 码赋号 → 切单裁片 → manifest
sidecar → load_nest_pieces → intermediate 落盘」全管线，产出与 web commit **同口径**
的排料输入（schema v2），但**不触碰 web 事实源**（``paths.INTERMEDIATE`` 与
``out/uploads/``，FR-5：cli 子包唯一可写目录是 ``paths.CONFIG_RUNS_DIR``）。

与 web commit 的刻意差异（其余逐字段一致，含 rounding 位数）：

  - intermediate 落 ``run_dir/pieces_intermediate.json``（非 ``paths.INTERMEDIATE``），
    **不写 .bak**（时间戳 run_dir 天然全新，无旧产物可备份/清理）；
  - 顶层省略 web 专属 ``label_representatives``（GET /api/ptypes 缩略图用，CLI 无消费方）；
  - ``gate_mm`` 写 ``cfg.gate_mm``（配置驱动，与该 run 求解密度分母同源；web commit
    固定写 ``GATE_MM=1980`` 显示常量 —— 示例配置 gate_mm=1980 时两者同值）。

镜像维护约定：``server._commit_to_nesting_sync`` 的 piece schema（pid/label/size/
polygon/bbox/area_mm2/n_verts/allowed_angles + 5 层透传 + rounding 位数）变更时，
本模块 ``_piece_record`` 必须同步（web 层零改动约束下无法抽共享函数，只能镜像）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import paths
from ..dxf_parser.collect import collect_pieces_with_details
from ..dxf_parser.export_dxf import write_piece_dxf
from ..nesting_bounds.load_pieces import load_nest_pieces, PIECES_MANIFEST_NAME
from ..nesting_engine.labeling import assign_codes, size_sort_key

__all__ = ['new_run_dir', 'commit_from_config']


def new_run_dir(run_name: str) -> Path:
    """创建并返回全新时间戳 run_dir：``CONFIG_RUNS_DIR/<run_name>_<YYYYMMDD-HHMMSS>``。

    时间戳本地时间秒级精度 —— 重跑生成新目录互不覆盖（保留历史），同秒同名并发会
    落同一目录（文档已注明避免）。``run_name`` 由调用方清洗（``run_config`` 负责
    配置 stem / ``--name`` 覆盖 + 非法字符清洗）；本函数只做拼接与 mkdir。
    """
    run_dir = Path(paths.CONFIG_RUNS_DIR) / f'{run_name}_{time.strftime("%Y%m%d-%H%M%S")}'
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _piece_record(p) -> dict:
    """NestPiece → intermediate piece 条目（schema v2，与 server._commit_to_nesting_sync 逐字段一致）。

    rounding 位数与 web 严格对齐：polygon/net_polygon/internal_lines/notches 点 3 位、
    notch 法线 4 位、bbox 2 位、area 1 位。5 层字段（net_polygon/internal_lines/
    notches/grain_line）不参与 sparrow NFP 碰撞，仅渲染/导出透传。
    """
    return {
        'pid': p.pid,
        'label': p.label,
        'size': p.size,
        'polygon': [[round(x, 3), round(y, 3)] for x, y in p.polygon],
        'bbox': [round(v, 2) for v in p.bbox],
        'area_mm2': round(p.area_mm2, 1),
        'n_verts': len(p.polygon),
        'allowed_angles': [0, 180],   # v0.3 布纹线约束（与 web 同口径）
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


def commit_from_config(cfg, run_dir) -> dict:
    """配置驱动的独立 commit 管线：切片 + manifest + intermediate 全落 ``run_dir``。

    编排镜像 ``web/server._commit_to_nesting_sync``（同一 ``collect_pieces_with_details``
    → ``assign_codes`` → ``write_piece_dxf`` → ``load_nest_pieces`` 链路，AC#5 同
    ``(block_name, size, piece_index)`` 必得同 g 码）：

    1. ``collect_pieces_with_details`` 取母版全部 5 层（layer1/14/8/4/7）；
    2. ``assign_codes`` 赋 g 码（label 先行，与 parse/web commit 同源同序）；
    3. ``run_dir/pieces/`` 下写 ``{label}_{size}.dxf`` + ``pieces_manifest.json`` sidecar；
    4. ``load_nest_pieces`` manifest 驱动布纹对齐 + 归一化（无镜像展开）；
    5. intermediate（schema v2）落 ``run_dir/pieces_intermediate.json``。

    只消费 ``cfg.master_dxf`` / ``cfg.gate_mm``（sizes/quantities/per_type/time/seeds
    是**求解期**参数，commit 阶段不过滤、全量切片 —— 与 web commit 同口径）。
    size 为 None 的片跳过（无法落 ``{label}_{size}.dxf`` 文件名），记入 ``skipped``。

    Returns
    -------
    dict
        commit 摘要：``source`` / ``run_dir`` / ``pieces_dir`` / ``intermediate`` /
        ``sizes`` / ``n_pieces`` / ``total_area_mm2`` / ``n_written_dxf`` /
        ``n_skipped`` / ``skipped``（US-003 result.json 的 commit 段数据源）。
    """
    run_dir = Path(run_dir)
    pieces = collect_pieces_with_details(Path(cfg.master_dxf))
    if not pieces:
        raise RuntimeError(f'母版未提取到任何裁片（layer1 POLYLINE 为空）: {cfg.master_dxf}')

    # g 码最先（label 先行）：与 parse / web commit 同一 assign_codes（同 collect、
    # 同排序键、同母版码规则），同一 (block_name, size, piece_index) 必得同码（AC#5）。
    codes_by_size = assign_codes(pieces)

    # 时间戳 run_dir 天然全新 —— 无需清空旧切片（web commit 的 rmtree 幂等清理不适用）。
    pieces_dir = run_dir / 'pieces'
    pieces_dir.mkdir(parents=True, exist_ok=True)

    # 按码升序 × 码内有序写 {label}_{size}.dxf + manifest 条目（manifest 驱动加载的
    # 唯一语义源；文件名仅人读）。
    manifest: list[dict] = []
    skipped: list[str] = []
    for size in sorted(codes_by_size.keys(), key=size_sort_key):
        for p, code in codes_by_size[size]:
            if p.size is None:
                skipped.append(f'{p.block_name}#{p.piece_index}(size 解析为 None)')
                continue
            fname = f'{code}_{p.size}.dxf'
            write_piece_dxf(p, pieces_dir / fname)
            manifest.append({'file': fname, 'label': code, 'size': p.size})

    if not manifest:
        raise RuntimeError('未写出任何单裁片（母版全部裁片 size 解析为 None）')
    with open(pieces_dir / PIECES_MANIFEST_NAME, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)

    nest_pieces = load_nest_pieces(str(pieces_dir))
    if not nest_pieces:
        raise RuntimeError('load_nest_pieces 未返回裁片（pieces_manifest.json 为空）')

    doc = {
        'source': Path(cfg.master_dxf).name,
        'gate_mm': float(cfg.gate_mm),
        'n_pieces': len(nest_pieces),
        'total_area_mm2': round(sum(p.area_mm2 for p in nest_pieces), 1),
        'pieces': [_piece_record(p) for p in nest_pieces],
        # 顶层无 label_representatives（web 专属，见模块 docstring「刻意差异」）。
    }
    intermediate_path = run_dir / 'pieces_intermediate.json'
    with open(intermediate_path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)

    return {
        'source': doc['source'],
        'run_dir': str(run_dir),
        'pieces_dir': str(pieces_dir),
        'intermediate': str(intermediate_path),
        'sizes': sorted({m['size'] for m in manifest}),
        'n_pieces': len(nest_pieces),
        'total_area_mm2': doc['total_area_mm2'],
        'n_written_dxf': len(manifest),
        'n_skipped': len(skipped),
        'skipped': skipped,
    }
