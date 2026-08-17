"""排料可视化工作台 · FastAPI 服务 + WebSocket。

启动：python server.py  →  http://127.0.0.1:8000

WS 协议（详见 README / 实现计划）：
  client → {action:start, sizes:[...], time:N, seed:N,
            params:{d_ext,d_int,tol_ext,tol_int}, per_type:{ptype:{d?,tol?}}?}
  server → {type:manifest, ...} 一次
         → {type:frame, density(原面积口径), density_sparrow(erode后口径), ...} 每个中间解
         → {type:final,   ...} 收尾  （或 {type:error, message}）

阶段 B：density 统一用原面积口径 real_density = total_area/(width*gate)，与版师/90%生死线一致；
        erode 后的 sparrow 自报密度保留为 density_sparrow 供参考。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from urllib.parse import quote

from .. import paths
from ..dxf_parser import explore
from ..dxf_parser.collect import collect_pieces_with_details
from ..dxf_parser.export_dxf import assign_group_no, GROUP_NAMES, write_piece_dxf
from ..nesting_bounds.load_pieces import load_nest_pieces, GATE_MM as NEST_GATE_MM, PAIR_TYPES
from ..nesting_engine.labeling import (
    label_for,
    size_sort_key,
    parse_member_sort_key,
    compute_size_ptype_labels,
)

STATIC_DIR = paths.STATIC_DIR
from .solver import build_instance, load_pieces, solve_with_callback, solve_with_callback_proc
from .export import placed_to_world, render_png, write_marker_dxf, write_marker_plt

# US-020：可 reload 的排料裁片状态。
# `_PIECES_STATE` 是一个 immutable snapshot dict —— `_reload_pieces_state()` 走「在外
# 构建新 dict → 锁内整体替换引用」模式，读者始终拿到一个完整一致的快照（不会读到
# 半状态）。`/ws/solve` 在 accept 阶段拿一次快照，整个 ws 连接内 pieces 不变（避免
# 求解中途数据切）；`/export` 路由同样走 `_get_pieces_state()`。commit 成功后立即调
# `_reload_pieces_state()` 让下一次请求吃到新 intermediate（前端无需重启 ms-web）。
_state_lock = threading.Lock()
_PIECES_STATE: dict = {}


def _build_pieces_state(intermediate_path: str = paths.INTERMEDIATE) -> dict:
    """从 intermediate JSON 构建 pieces state 快照（不在锁内调用，可重入）。

    返回 {doc, gate_mm, pieces, pieces_by_id}；pieces_by_id = {pid: piece_dict}。
    intermediate 缺失或解析异常时返回空 state（{n:0,...}）—— 启动期 allow-empty 由
    `_init_pieces_state()` 决定，本函数纯粹做读取 + 索引。
    """
    doc, gate_mm, pieces = load_pieces(intermediate_path)
    return {
        'doc': doc,
        'gate_mm': gate_mm,
        'pieces': pieces,
        'pieces_by_id': {p['pid']: p for p in pieces},
    }


def _reload_pieces_state(intermediate_path: str = paths.INTERMEDIATE) -> dict:
    """重读 intermediate → 原子替换 `_PIECES_STATE` 引用 → 返回新快照。

    在锁内构建新 dict（load_pieces 是文件 I/O + JSON 解析；commit 频率远低于 ws 读
    取，且锁粒度对 6-worker 池可忽略），保证读者不会看到半状态。返回的 dict 同时被
    `_PIECES_STATE` 引用，调用方可以放心返回给前端 / 后续路由使用。
    """
    with _state_lock:
        new_state = _build_pieces_state(intermediate_path)
        _PIECES_STATE.clear()
        _PIECES_STATE.update(new_state)
        return new_state


def _get_pieces_state() -> dict:
    """锁内返回当前 `_PIECES_STATE` 只读快照（调用方拿到后整连接复用，不再切）。"""
    with _state_lock:
        return _PIECES_STATE


# 启动时读一次中间数据（事实源：paths.INTERMEDIATE）→ 填入 _PIECES_STATE。
# 若 intermediate 不存在（首次启动未上传母版 commit），_PIECES_STATE 保持空 dict；
# 后续 GET /api/ptypes / /ws/solve 会降级返回空数据，commit 成功后 _reload 才真正填入。
try:
    _reload_pieces_state()
except Exception as e:
    print(f'[server] 启动期 load_pieces 失败，_PIECES_STATE 暂为空：{e}', file=sys.stderr)

app = FastAPI(title='排料可视化工作台')
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')
_executor = ThreadPoolExecutor(max_workers=6)   # 多 seed 对比最多 6 个并发求解（seed 间同等 CPU 竞争 → 排名仍公平）
_SENTINEL = object()

# US-004：上传解析配置
UPLOAD_MAX_BYTES = 20 * 1024 * 1024   # 20MB 上限（实测生产母版 ~3MB，留足余量）
UPLOADS_DIR = Path(paths.OUT_DIR) / 'uploads'
# US-010：doc_id 合法字符集（仅允许字母数字，防路径逃逸；uuid.uuid4().hex 自然命中）
_DOC_ID_RE = re.compile(r'^[0-9A-Za-z]{1,128}$')


# ---------------------------------------------------------------- US-004 上传解析

def _label_for(idx: int) -> str:
    """0→A, 1→B, ..., 25→Z, 26→AA, 27→AB ...（转发 ``nesting_engine.labeling``）。"""
    return label_for(idx)


def _size_sort_key(size: int | None) -> tuple[int, int]:
    """码号排序键：None 殿后，其余按数值升序（转发 ``nesting_engine.labeling``）。"""
    return size_sort_key(size)


def _build_parse_payload(doc_id: str, filename: str, pieces) -> dict:
    """把 collect_pieces_with_details 结果按码号分组 + 质心/面积稳定排序 + 赋 A/B/C 标签。

    响应结构与 US-005 前端契约一致：每片含 label/name/ptype/paired/polygon/internal_lines/
    notches/net_polygon/grain_line。polygon / net_polygon = [[x,y], ...]；internal_lines =
    [[[x,y], ...], ...]；notches = [[x,y,nx,ny], ...]；grain_line = [x1,y1,x2,y2] 或 null。

    矩阵化重构 US-004：每片 additive 附加 ptype（group_key → assign_group_no → g00..g09 →
    GROUP_NAMES，与 ``_commit_to_nesting_sync`` 完全同链路）与 paired（ptype ∈ PAIR_TYPES，
    配对片型 demand=1 份实际排 L+R 2 物理片）。字段纯新增：排序 / A/B/C 标注 /
    ``labeling.compute_size_ptype_labels`` 的 parse↔intermediate label 对齐不变量全部不动，
    旧前端忽略新字段无害。
    """
    # 与 commit 同一 gmap（对全码 pieces 整体 assign，group_key → g00..g09 稳定）
    gmap = assign_group_no(pieces)

    by_size: dict[int | None, list] = {}
    for p in pieces:
        by_size.setdefault(p.size, []).append(p)

    sizes_out = []
    for size in sorted(by_size.keys(), key=_size_sort_key):
        members = by_size[size]
        # 稳定排序：DXF 数学系下质心 Y 大者（视觉上方）优先 → X 小者（视觉左）优先 → 面积大者优先
        # （排序键 = labeling.parse_member_sort_key 单一真相源，与 label 对齐 / ptype 代表裁片同键）
        members_sorted = sorted(members, key=parse_member_sort_key)
        pieces_out = []
        for idx, p in enumerate(members_sorted):
            ptype = GROUP_NAMES.get(gmap.get(p.group_key))
            pieces_out.append({
                'label': _label_for(idx),
                'name': p.block_name,
                'ptype': ptype,
                'paired': ptype in PAIR_TYPES,
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


def _build_ptype_representatives(pieces, gmap, group_names) -> dict:
    """每片型 RAW 代表裁片 + 编号 label（与 ``_build_parse_payload`` 上传预览同口径）。

    供 GET /api/ptypes 渲染高级配置缩略图 / 放大预览。**刻意取原始坐标**（不走
    ``load_nest_pieces`` 的布纹对齐旋转）—— 否则纵向布纹线裁片（如腰 992×166）被
    旋转 ±90° 后在 64×64 方形缩略格里缩成 ~11px 细竖线，与上传预览不一致且不可辨认
    （US-018 AC#9 缩略图用于片型识别，应与上传预览同朝向）。布纹对齐是**排料求解**
    的需要（intermediate ``pieces`` 仍存变换后几何供 sparrow），与缩略图展示无关。

    代表选取 + 编号（2026-08-17 起，与上传预览严格一致）：按码升序、码内
    ``parse_member_sort_key`` 稳定排序（与 ``_build_parse_payload`` 赋号同键同序），
    每片型取**最小码内首个**有效片（ptype/size 均非 None，与 ``write_piece_dxf``
    写出条件一致），``label`` = 该片在其码内的 A/B/C 编号 —— 高级配置弹窗列头显示
    该编号徽章，与上传预览 QtyMatrix 列头（同编号缩略图）所指同一片。
    返回 ``{ptype: {label, polygon, net_polygon, internal_lines, notches, grain_line}}``。
    """
    by_size: dict[int | None, list] = {}
    for p in pieces:
        by_size.setdefault(p.size, []).append(p)

    reps: dict[str, dict] = {}
    for size in sorted(by_size.keys(), key=_size_sort_key):
        members_sorted = sorted(by_size[size], key=parse_member_sort_key)
        for idx, p in enumerate(members_sorted):
            if p.size is None:
                continue
            ptype = group_names.get(gmap.get(p.group_key))
            if ptype is None or ptype in reps:
                continue
            reps[ptype] = {
                'label': _label_for(idx),
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


def _parse_dxf_sync(path: str):
    """同步包装：在 executor 里调用 collect_pieces_with_details。"""
    return collect_pieces_with_details(path)


@app.post('/api/parse-dxf')
async def parse_dxf(file: UploadFile = File(...)):
    """US-004：接收 DXF 母版上传 → 落盘 → 深度解析 → 返回按码分组 + A/B/C 标注的 JSON。

    - 非 .dxf → 400；超 20MB → 413；ezdxf 解析异常 → 422（中文错误）。
    - doc_id = 落盘 uuid（无扩展名），供 US-010 /api/commit-to-nesting 引用。
    - CPU 密集解析走 loop.run_in_executor(_executor,...) 复用现有线程池防阻塞 WS。
    """
    fname = file.filename or ''
    if not fname.lower().endswith('.dxf'):
        return JSONResponse({'error': '仅支持 .dxf 文件'}, status_code=400)

    data = await file.read()
    if len(data) > UPLOAD_MAX_BYTES:
        return JSONResponse(
            {'error': f'文件大小超过上限 {UPLOAD_MAX_BYTES // (1024 * 1024)}MB'},
            status_code=413,
        )

    doc_id = uuid.uuid4().hex
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOADS_DIR / f'{doc_id}.dxf'
    dest.write_bytes(data)

    loop = asyncio.get_running_loop()
    try:
        pieces = await loop.run_in_executor(_executor, _parse_dxf_sync, str(dest))
    except Exception as e:
        return JSONResponse({'error': f'DXF 解析失败：{e}'}, status_code=422)

    return _build_parse_payload(doc_id, fname, pieces)


# ---------------------------------------------------------------- US-010 commit-to-nesting

def _commit_to_nesting_sync(doc_id: str, src_dxf: str, source_name: str) -> dict:
    """US-010 Path A 全管线（同步，跑在 executor 里）：

    1. ``collect.collect_pieces_with_details`` 取母版全部 5 层（layer1/14/8/4/7，US-024）；
    2. ``export_dxf.assign_group_no`` + ``GROUP_NAMES`` 定片型；
    3. ``write_piece_dxf`` 切单裁片（5 层全写出）到 ``paths.OUT_DIR/uploads/<doc_id>_pieces/``；
    4. ``load_nest_pieces(pieces_dir, sizes=母版全码)`` 对齐布纹线 + 归一化 + L/R 镜像
       （5 层跟随同一变换链）；
    5. 备份原 intermediate 为 ``.bak`` 后覆盖写回（schema 与历史 CLI 产物一致）。

    返回新 intermediate 摘要 dict（码数/裁片数/总面积/备份路径）。
    """
    # US-024：用 collect_pieces_with_details 取代 explore.collect_pieces，让 write_piece_dxf
    # 拿到 PieceOutline 全 5 层（layer1+layer7+layer14+layer8+layer4）。assign_group_no 与
    # compute_size_ptype_labels 仅依赖 group_key / block_name 等基础字段，对深度解析结果
    # 兼容（PieceOutline 字段是 additive 扩展）。
    pieces = collect_pieces_with_details(Path(src_dxf))
    if not pieces:
        raise RuntimeError('母版未提取到任何裁片（layer1 POLYLINE 为空）')

    gmap = assign_group_no(pieces)

    # 切单裁片（idempotent：每次 commit 先清空再重写，避免残留旧文件污染）
    pieces_dir = UPLOADS_DIR / f'{doc_id}_pieces'
    if pieces_dir.exists():
        shutil.rmtree(pieces_dir)
    pieces_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped: list[str] = []
    for p in pieces:
        gno = gmap[p.group_key]
        ptype = GROUP_NAMES.get(gno)
        if ptype is None:
            skipped.append(f'{p.block_name}#{p.piece_index}(gno={gno} 无 GROUP_NAMES 映射)')
            continue
        if p.size is None:
            skipped.append(f'{p.block_name}#{p.piece_index}(size 解析为 None)')
            continue
        write_piece_dxf(p, pieces_dir / f'{ptype}_{p.size}.dxf')
        written += 1

    if written == 0:
        raise RuntimeError('未写出任何单裁片（请检查 GROUP_NAMES 映射或母版 layer1 结构）')

    # 母版实际全码（覆盖 DEFAULT_SIZES 8 码）
    all_sizes = sorted({p.size for p in pieces if p.size is not None})
    nest_pieces = load_nest_pieces(str(pieces_dir), sizes=all_sizes)
    if not nest_pieces:
        raise RuntimeError('load_nest_pieces 未返回裁片（单裁片文件名/片型与 ALL_TYPES 不匹配）')

    # US-022：计算 (size, ptype) → label 映射（与 parse-dxf 响应同排序同标注）。
    # commit 走 NestPiece（归一化+镜像），parse 走 PieceOutline（原始坐标），两者坐标
    # 系不同不能直接排序对齐；但两者均源自同一母版的 ``explore.collect_pieces``，故对
    # 原始 pieces 施行与 _build_parse_payload 完全一致的排序 + _label_for 标注，再经
    # gmap/GROUP_NAMES 链路把 label 关联到 ptype，即得与 parse 响应按 (size, ptype)
    # 严格对齐的 label 字典（关键不变量 AC#5）。
    size_ptype_label = compute_size_ptype_labels(pieces, gmap, GROUP_NAMES)

    # 每片型 RAW 代表裁片（原始坐标，供 /api/ptypes 缩略图与上传预览同朝向）。
    ptype_representatives = _build_ptype_representatives(pieces, gmap, GROUP_NAMES)

    # intermediate schema 与历史 CLI 产物（pieces_export.py，已移除）完全一致
    doc = {
        'source': source_name,
        'gate_mm': NEST_GATE_MM,
        'n_pieces': len(nest_pieces),
        'total_area_mm2': round(sum(p.area_mm2 for p in nest_pieces), 1),
        'pieces': [
            {
                'pid': p.pid,
                'ptype': p.ptype,
                'size': p.size,
                'side': p.side,
                # US-022：label 供前端 qtyStore（按 label 编辑数量）与 build_instance
                # （按 (label, sizeKey) 查 demand）对齐配对。L/R 同 ptype 共享 label。
                'label': size_ptype_label.get((p.size, p.ptype)),
                'polygon': [[round(x, 3), round(y, 3)] for x, y in p.polygon],
                'bbox': [round(v, 2) for v in p.bbox],
                'area_mm2': round(p.area_mm2, 1),
                'n_verts': len(p.polygon),
                'allowed_angles': [0, 180],   # v0.3 布纹线约束
                # US-024：5 层渲染/导出透传字段（不参与 sparrow NFP 碰撞）。
                # 与 parse-dxf 响应同 schema：net_polygon=[[x,y],...]、internal_lines=[[[x,y],...],...]、
                # notches=[[x,y,nx,ny],...]、grain_line=[x1,y1,x2,y2]|null。
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
            for p in nest_pieces
        ],
        # 每片型 RAW 代表裁片（原始坐标，与上传预览同朝向；见 _build_ptype_representatives）。
        'ptype_representatives': ptype_representatives,
    }

    # 备份原 intermediate 为 .bak（首次写回时无原文件 → 不备份）
    intermediate = Path(paths.INTERMEDIATE)
    bak_path = intermediate.with_suffix('.bak')
    intermediate.parent.mkdir(parents=True, exist_ok=True)
    if intermediate.exists():
        shutil.copy2(intermediate, bak_path)
    with open(intermediate, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)

    return {
        'doc_id': doc_id,
        'source': source_name,
        'sizes': all_sizes,
        'n_pieces': len(nest_pieces),
        'total_area_mm2': doc['total_area_mm2'],
        'n_written_dxf': written,
        'n_skipped': len(skipped),
        'skipped': skipped[:10],   # 截断，避免响应过大
        'bak': str(bak_path),
    }


@app.post('/api/commit-to-nesting')
async def commit_to_nesting(req: Request):
    """US-010 Path A：上传母版 → 单裁片切分 → NestPiece 全码 → 覆盖 intermediate。

    payload: ``{doc_id, filename?}``
      - ``doc_id``：US-004 落盘的 uuid（无扩展名），定位 ``uploads/<doc_id>.dxf``；
      - ``filename``：可选，覆盖 intermediate ``source`` 字段；缺省用 ``<doc_id>.dxf``。

    CPU 密集管线跑在 ``_executor`` 里防阻塞 WS。写回前备份原 intermediate 为
    ``paths.INTERMEDIATE.with_suffix('.bak')``；返回新 intermediate 摘要。

    US-020：commit 成功后立即 ``_reload_pieces_state()`` —— 下一次 ``/ws/solve`` /
    ``/export`` 路由调用 ``_get_pieces_state()`` 即拿到新 intermediate（前端无需重启
    ``ms-web``）。返回 payload 加 ``reloaded: true`` 标记 reload 已生效。
    """
    try:
        payload = await req.json()
    except Exception:
        return JSONResponse({'error': '请求体须为 JSON'}, status_code=400)

    doc_id = payload.get('doc_id') if isinstance(payload, dict) else None
    if not doc_id or not isinstance(doc_id, str):
        return JSONResponse({'error': '缺少 doc_id 或类型错误'}, status_code=400)
    if not _DOC_ID_RE.match(doc_id):
        return JSONResponse({'error': 'doc_id 非法（仅允许字母数字，1-128 字符）'}, status_code=400)

    src = UPLOADS_DIR / f'{doc_id}.dxf'
    if not src.exists():
        return JSONResponse({'error': f'未找到上传文件: {doc_id}'}, status_code=404)

    source_name = payload.get('filename') or src.name
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            _executor, _commit_to_nesting_sync, doc_id, str(src), source_name
        )
    except Exception as e:
        return JSONResponse({'error': f'commit 失败：{e}'}, status_code=422)

    # US-020：intermediate 已写盘 → 锁内原子重读，下次 /ws/solve 拿到新裁片。
    # 防御：commit_sync 写盘已成功，正常路径 reload 必成功；若 reload 因罕见的 I/O
    # 竞态（如并发外部进程改 intermediate）失败，记录日志、保持旧 state、标记
    # reloaded=false —— 前端 US-021 看到 reloaded=false 可降级提示「需重启 ms-web」。
    try:
        _reload_pieces_state()
        result['reloaded'] = True
    except Exception as e:
        print(f'[server] commit 后 reload 失败（保留旧 state）：{e}', file=sys.stderr)
        result['reloaded'] = False
        result['reload_error'] = str(e)
    return result


@app.get('/')
def index():
    return FileResponse(os.path.join(STATIC_DIR, 'index.html'))


# ---------------------------------------------------------------- US-020 GET /api/ptypes

# intermediate piece → ptype 代表裁片字段白名单（v1 仅 polygon；US-024 后 intermediate
# 扩 5 层后自动带 net_polygon/internal_lines/notches/grain_line，前端 layer-aware 渲染；
# label = 该片 A/B/C 编号，2026-08-17 起随代表裁片一起下发，供高级配置弹窗显示编号徽章）。
_PTYPE_REPRESENTATIVE_FIELDS = (
    'label', 'polygon', 'net_polygon', 'internal_lines', 'notches', 'grain_line',
)


@app.get('/api/ptypes')
def get_ptypes():
    """US-020 D10：返回当前 ``_PIECES_STATE`` 下每个 ptype 的代表裁片（首个出现）。

    响应：``{representatives: Record<ptype, {label?, polygon, net_polygon?,
    internal_lines?, notches?, grain_line?}>}``。``label`` = 代表裁片在上传预览里的
    A/B/C 编号（2026-08-17 起；选取口径与 ``_build_parse_payload`` 赋号同键同序，
    保证「编号 → 图形」与上传预览列头一致）。旧 intermediate 无该字段 → 前端兜底
    显示片型名。空 state（首次启动未 commit、intermediate 解析失败）返回
    ``{representatives: {}}``，不阻塞前端配置弹窗降级为片型名文字。

    坐标口径（US-024fix）：优先返 intermediate ``ptype_representatives`` —— **RAW 母版
    原始坐标**，与 ``/api/parse-dxf`` 上传预览同朝向（未走布纹对齐旋转），让缩略图与
    上传预览一致、可辨认。旧 intermediate 无此字段时回退到 ``pieces`` 首个代表（变换后
    坐标），re-commit 后自动切 RAW 口径。
    """
    state = _get_pieces_state()
    # 优先用 intermediate 的 ptype_representatives（RAW 原始坐标，与上传预览同朝向）——
    # 避免纵向布纹片被 load_nest_pieces 布纹对齐旋转让缩略图缩成不可辨认的细竖线。
    # 旧 intermediate（commit 前生成、无此字段）回退到从 pieces 取首个代表（变换后坐标，
    # 行为同前，向后兼容；re-commit 后自动切到 RAW 口径）。
    reps = (state.get('doc') or {}).get('ptype_representatives')
    if reps is not None:
        return {'representatives': reps}
    pieces = state.get('pieces') or []
    representatives: dict[str, dict] = {}
    for p in pieces:
        ptype = p.get('ptype')
        if ptype is None or ptype in representatives:
            continue
        rep = {k: p[k] for k in _PTYPE_REPRESENTATIVE_FIELDS if k in p}
        representatives[ptype] = rep
    return {'representatives': representatives}


@app.post('/export')
async def export(req: Request):
    """导出最优排料方案：前端 POST 最优 run 的最终帧 placed_items → 出 PNG / R12-DXF。

    payload = {fmt:'png'|'dxf', sizes:[..], seed, gate_mm, width_mm, density,
               placed:[{id,rotation,translation},...], filename?}
    filename 为上传母版名（用作导出文件名前缀，去 .dxf）；缺省回退「排料」。
    返回文件字节流（Content-Disposition 附件下载，中文文件名走 RFC5987）。
    """
    state = _get_pieces_state()
    pieces_by_id = state.get('pieces_by_id') or {}

    payload = await req.json()
    fmt = payload.get('fmt')
    placed = payload.get('placed') or []
    width_mm = float(payload.get('width_mm') or 0.0)
    # 幅宽优先取求解时实际值（前端 ExportPayload.gate_mm = manifest.gate_mm，与求解/渲染口径一致）；
    # 缺省/非法 → 回退 intermediate 的 gate_mm（旧行为）。
    gate_mm = float(payload.get('gate_mm') or 0.0) or (state.get('gate_mm') or 0.0)
    density = float(payload.get('density') or 0.0)
    seed = payload.get('seed', 0)
    sizes = payload.get('sizes') or []

    if width_mm <= 0 or not placed:
        return JSONResponse({'error': '无可导出的方案（width=0 或无裁片）'}, status_code=400)

    world = placed_to_world(placed, pieces_by_id)
    if not world:
        return JSONResponse({'error': '导出失败：placed 的 pid 均未匹配到原始轮廓'}, status_code=400)

    sizes_str = '-'.join(str(s) for s in sorted(int(s) for s in sizes)) if sizes else 'all'
    pct = density * 100

    if fmt == 'png':
        title = (f'M1787 直筒 | 码 {sizes_str} | 利用率 {pct:.2f}% | '
                 f'用布 {width_mm / 1000:.2f} m | 门幅 {int(gate_mm)} mm | seed {seed}')
        data = render_png(world, width_mm=width_mm, gate_mm=gate_mm, title=title)
        media, ext = 'image/png', 'png'
    elif fmt == 'dxf':
        title = f'M1787 util={pct:.2f}% L={width_mm / 10:.1f}cm gate={int(gate_mm)} seed={seed}'
        data = write_marker_dxf(world, width_mm=width_mm, gate_mm=gate_mm, title=title)
        media, ext = 'application/dxf', 'dxf'
    elif fmt == 'plt':
        # US-033：PLT/HPGL 文本导出（LIKE 绘图仪 / WT V8.8 原生链路）；title 复用 DXF 同款
        # ASCII（格式：M1787 util=<pct>% L=<L>cm gate=<gate> seed=<seed>），避免中文编码风险。
        title = f'M1787 util={pct:.2f}% L={width_mm / 10:.1f}cm gate={int(gate_mm)} seed={seed}'
        data = write_marker_plt(world, width_mm=width_mm, gate_mm=gate_mm, title=title)
        media, ext = 'application/plt', 'plt'
    else:
        return JSONResponse({'error': f'未知格式 {fmt}'}, status_code=400)

    # 文件名前缀优先用前端透传的上传母版名（uploadStore.doc.filename，与界面「当前文件」
    # 同源），去 .dxf 扩展名；前端未传（旧前端）回退「排料」——多个款号同时排料导出后凭前缀区分。
    # 不读 intermediate `source`：_build_pieces_state 构建的 state 不含该字段（恒 None）。
    upload_name = (payload.get('filename') or '').strip()
    stem = upload_name[:-4] if upload_name.lower().endswith('.dxf') else upload_name
    prefix_cn = stem or '排料'
    # ASCII fallback（filename="..."，老浏览器不支持 filename* 时显示）：文件名纯 ASCII 时
    # 直接用，含中文则回退 nesting（避免 fallback 名出现未编码中文）。
    prefix_ascii = stem if stem and stem.isascii() else 'nesting'
    fname_ascii = f'{prefix_ascii}_{sizes_str}_{pct:.2f}pct_seed{seed}.{ext}'
    fname_cn = f'{prefix_cn}_码{sizes_str}_{pct:.2f}pct_seed{seed}.{ext}'
    cd = f"attachment; filename=\"{fname_ascii}\"; filename*=UTF-8''{quote(fname_cn)}"
    return Response(content=data, media_type=media,
                    headers={'Content-Disposition': cd})


# US-026：process.terminate()+join(timeout=5) 封装 —— read_loop（stop/断开）、write_loop
# （send 失败）、ws_solve finally 三处调用，确保任何路径下都不留孤儿进程。幂等安全：
# process 已死时 terminate/join 是 no-op。state_box 缺 process 键（启动竞态）也无害。
def _terminate_solve_process(state_box: dict) -> None:
    """终止 solve 子进程（幂等）：alive → terminate → join(timeout=5) → kill 兜底。"""
    proc = state_box.get('process')
    if proc is None:
        return
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=5.0)
        # terminate 后仍存活（极端情况：Rust 原生代码 ignore SIGTERM）→ kill 兜底。
        if proc.is_alive():
            try:
                proc.kill()
            except Exception:
                pass
            proc.join(timeout=1.0)


@app.websocket('/ws/solve')
async def ws_solve(ws: WebSocket):
    """排料求解 WebSocket 端点（US-026 进程化 + stop/断开清理）。

    生命周期（双向并发：write loop 内联 + read loop 后台 task）：
      1. accept → 读首条消息（必须 ``{action:'start'}``）→ accept 阶段拿 pieces 快照；
      2. ``solve_with_callback_proc`` 在 executor 线程阻塞跑（spawn 子进程），通过
         ``on_manifest`` / ``on_report`` 回调把消息经 ``call_soon_threadsafe`` 投入
         asyncio queue；``on_process`` 把 Process 句柄交给本协程供 stop/断开时 terminate；
      3. write loop（内联主流程）drain queue → ``ws.send_json``（manifest/frame/final/error）；
      4. read loop（后台 task）持续 ``await ws.receive_json()``：收到 ``{action:'stop'}`` →
         ``process.terminate()+join(timeout=5)`` → 直发 ``{type:stopped}`` → 投 SENTINEL；
      5. 客户端断开（WebSocketDisconnect / 连接异常）→ terminate+join 防孤儿进程（修旧 bug）。

    write loop 消费 SENTINEL（run_solve 或 read_loop 投）后 break → finally 显式 ``ws.close()``
    + cancel read_task + terminate process 兜底。空 state（intermediate 缺失）行为不变：
    发 error「排料数据为空」并关闭。
    """
    await ws.accept()
    msg = await ws.receive_json()
    if msg.get('action') != 'start':
        await ws.send_json({'type': 'error', 'message': '首条消息须为 {action:start}'})
        return

    # US-020：accept 阶段拿一次 state 快照，整连接内 pieces/gate_mm 不变（避免求解
    # 中途 reload 切数据）。state 空时（首次启动未 commit / intermediate 缺失）→ 报错。
    state = _get_pieces_state()
    pieces = state.get('pieces') or []
    gate_mm = state.get('gate_mm') or 0.0
    if not pieces or gate_mm <= 0:
        await ws.send_json({'type': 'error',
                            'message': '排料数据为空（请先上传解析母版并 commit）'})
        return

    sizes = msg.get('sizes') or []
    time_budget = int(msg.get('time', 120))
    # 幅宽：前端 gate_mm（cm×10→mm）优先覆盖 intermediate 的默认门幅；未传/非正/非法 → 沿用 state。
    req_gate = msg.get('gate_mm')
    if req_gate:
        try:
            g = float(req_gate)
            if g > 0:
                gate_mm = g
        except (TypeError, ValueError):
            pass
    seed = int(msg.get('seed', 0))
    params = msg.get('params') or None
    per_type = msg.get('per_type') or None
    # US-022：quantities = {label: {sizeKey: N}}（per-size demand；0=该 piece 该码不排）。
    # 缺省/None → 全片 demand=1（向后兼容旧前端 / 旧 intermediate 无 label）。
    quantities = msg.get('quantities')
    if not isinstance(quantities, dict):
        quantities = None

    # US-026：pieces_snapshot = 纯 dict 列表（deep copy 防连接内 mutate），连同 solve_params
    # 传给 solve_with_callback_proc → solve_worker 子进程内 build_instance（spyrrow 对象
    # 不可 pickle，主进程不构造 instance）。
    pieces_snapshot = [dict(p) for p in pieces]
    solve_params = {
        'time_budget': time_budget,
        'seed': seed,
        'sizes': sizes,
        'params': params,
        'per_type': per_type,
        'quantities': quantities,
    }

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    # 跨线程共享状态盒：process 句柄（on_process 填）、stopped 标志（read_loop 填）、
    # 帧计数与 n_eroded（on_report/on_manifest 填，run_solve 读 → final 消息用）。
    # 所有字段仅在 executor 单线程内 mutate（on_manifest/on_report/run_solve 同线程），
    # stopped 标志由事件循环线程写 —— 两者用 bool 简单写读，GIL 下无撕裂风险。
    state_box: dict = {'process': None, 'stopped': False, 'n_frames': 0, 'n_eroded': 0}

    def on_manifest(m):
        """子进程 manifest → 组装前端契约消息 → 投 asyncio queue。"""
        state_box['n_eroded'] = m.get('n_eroded', 0)
        total_area = m.get('total_area', 0.0)
        manifest_msg = {
            'type': 'manifest',
            'gate_mm': gate_mm,
            'total_area_mm2': total_area,
            'n_eroded': m.get('n_eroded', 0),
            'pieces': [
                {'id': pid, 'ptype': meta['ptype'], 'size': meta['size'], 'color': meta['color'],
                 'area_mm2': meta['area_mm2'], 'polygon': meta['polygon'],
                 # demand：该 pid 的副本数（build_instance 透传；缺省 1 = 单副本/旧兼容）。
                 # 前端 NestSVG 按 demand 建 N 个 polygon 副本，避免 demand>1 时同 id 多 placement 互相覆盖。
                 'demand': meta.get('demand', 1),
                 # US-024：5 层透传字段（None-safe；缺字段时各层视为空/None，前端 layer-aware 渲染）。
                 'net_polygon': meta.get('net_polygon', []),
                 'internal_lines': meta.get('internal_lines', []),
                 'notches': meta.get('notches', []),
                 'grain_line': meta.get('grain_line'),
                 }
                for pid, meta in m['pid_meta'].items()
            ],
        }
        loop.call_soon_threadsafe(queue.put_nowait, manifest_msg)

    def on_report(r):
        """子进程 frame（density 双口径已由 solve_with_callback_proc 换算）→ 加 index 投队列。"""
        r['index'] = state_box['n_frames']
        state_box['n_frames'] += 1
        loop.call_soon_threadsafe(queue.put_nowait, r)

    def on_process(proc):
        """子进程 start 后立即回调，把 Process 句柄交给事件循环供 stop/断开 terminate。"""
        state_box['process'] = proc

    def run_solve():
        """executor 线程：阻塞跑 solve_with_callback_proc → 投 final/error/SENTINEL。"""
        _, final_data, elapsed, err = solve_with_callback_proc(
            pieces_snapshot, gate_mm, solve_params,
            on_manifest=on_manifest, on_report=on_report, on_process=on_process,
        )
        # stopped 标志由 read_loop 在 stop/断开时置 True → 不再投 final/error（避免
        # 与 stopped 消息冲突；客户端只收 stopped 或 final/error，不会同时收）。
        if not state_box['stopped']:
            if err is not None:
                loop.call_soon_threadsafe(queue.put_nowait,
                    {'type': 'error', 'message': f'求解失败: {err}'})
            elif final_data is not None:
                loop.call_soon_threadsafe(queue.put_nowait, {
                    'type': 'final',
                    'density': final_data['density'],
                    'density_sparrow': final_data['density_sparrow'],
                    'width_mm': final_data['width_mm'],
                    'elapsed': round(elapsed, 2),
                    'n_frames': state_box['n_frames'],
                    'n_eroded': state_box['n_eroded'],
                })
        loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    loop.run_in_executor(_executor, run_solve)

    # ---- 双向并发：write loop 内联 await（主流程）；read loop 后台 task 收 stop/断开 ----
    # write loop 消费 SENTINEL 后自然 break → ws_solve 返回 → FastAPI 关闭 WS。read loop
    # 被 cancel（仍在 receive_json 阻塞）或已自行 return（stop/断开）。任一路径 finally
    # 都 terminate+join process，防孤儿。
    async def read_loop():
        """后台持续读客户端消息：{action:'stop'} → terminate + 直发 stopped + 投 SENTINEL；断开 → terminate。"""
        try:
            while True:
                cmsg = await ws.receive_json()
                if isinstance(cmsg, dict) and cmsg.get('action') == 'stop':
                    state_box['stopped'] = True
                    _terminate_solve_process(state_box)
                    # stopped 消息由 read_loop 直发（不经 queue），确保是客户端收到的最后
                    # 一条业务消息。先发 stopped 再投 SENTINEL：write loop 在 stopped 标志
                    # 已置 True 时丢弃残余 frame（continue），收到 SENTINEL 后 break → WS 关闭。
                    # 若先投 SENTINEL，write loop 会在 send_json(stopped) 的 await 期间 break
                    # → finally cancel read_task → stopped 可能未发完。
                    try:
                        await ws.send_json({'type': 'stopped', 'reason': 'user_requested'})
                    except Exception:
                        pass   # send 失败（客户端已断开）—— 忽略，finally 兜底清理
                    queue.put_nowait(_SENTINEL)
                    return
        except WebSocketDisconnect:
            # 客户端主动断开 → 清理子进程（修旧 bug：旧版 except:pass 留孤儿进程跑满预算）。
            state_box['stopped'] = True
            _terminate_solve_process(state_box)
        except (asyncio.CancelledError, SystemExit, GeneratorExit):
            raise   # 不吞取消/退出类异常，让上层 finally 处理
        except Exception:
            # 其它连接异常（网络中断等）→ 同样清理。
            state_box['stopped'] = True
            _terminate_solve_process(state_box)

    read_task = asyncio.create_task(read_loop())
    try:
        # write loop 内联（主流程）：drain asyncio queue → ws.send_json；SENTINEL / stopped 收尾。
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            if state_box['stopped']:
                # stop 已触发：read_loop 已直发 stopped → 丢弃残余 frame，等 SENTINEL。
                continue
            try:
                await ws.send_json(item)
            except Exception:
                # send 失败（客户端已断开）→ 标记 stopped + terminate，让 run_solve 跳过 final。
                state_box['stopped'] = True
                _terminate_solve_process(state_box)
                break
    finally:
        # 兜底清理：无论正常收尾还是异常，确保 process 被终止 + read_task 被 cancel + WS 关闭。
        _terminate_solve_process(state_box)
        if not read_task.done():
            read_task.cancel()
            # 不 await read_task：TestClient（anyio portal）下 ws.receive_json() 阻塞在线程
            # 安全部列上，task.cancel() 的 CancelledError 无法投递到阻塞中的 coroutine ——
            # await read_task / wait_for(read_task) 会永久挂起。uvicorn 生产环境下 cancel
            # 正常生效（receive_json 是真 async，可被中断）。
        # 显式关闭 WS：ws_solve 返回后 FastAPI 自动关 WS，但 TestClient 需要显式 close
        # 才能让 client 端 receive_json 抛 WebSocketDisconnect（Starlette 实现差异）。
        try:
            await ws.close()
        except Exception:
            pass


def main():
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)


if __name__ == '__main__':
    main()
