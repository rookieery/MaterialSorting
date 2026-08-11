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

from fastapi import FastAPI, Request, UploadFile, File, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from urllib.parse import quote

from .. import paths
from ..dxf_parser import explore
from ..dxf_parser.collect import collect_pieces_with_details
from ..dxf_parser.export_dxf import assign_group_no, GROUP_NAMES, write_piece_dxf
from ..nesting_bounds.load_pieces import load_nest_pieces, GATE_MM as NEST_GATE_MM
from ..nesting_engine.labeling import (
    label_for,
    centroid as _centroid_pts,
    size_sort_key,
    compute_size_ptype_labels,
)

STATIC_DIR = paths.STATIC_DIR
from .solver import build_instance, load_pieces, solve_with_callback
from .export import placed_to_world, render_png, write_marker_dxf

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
# 若 intermediate 不存在（首次启动未跑 ms-pieces-export），_PIECES_STATE 保持空 dict；
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


def _centroid(poly: list[tuple[float, float]]) -> tuple[float, float]:
    """顶点算术质心（转发 ``nesting_engine.labeling``，用于稳定排序键）。"""
    return _centroid_pts(poly)


def _size_sort_key(size: int | None) -> tuple[int, int]:
    """码号排序键：None 殿后，其余按数值升序（转发 ``nesting_engine.labeling``）。"""
    return size_sort_key(size)


def _build_parse_payload(doc_id: str, filename: str, pieces) -> dict:
    """把 collect_pieces_with_details 结果按码号分组 + 质心/面积稳定排序 + 赋 A/B/C 标签。

    响应结构与 US-005 前端契约一致：每片含 label/name/polygon/internal_lines/notches/
    net_polygon/grain_line。polygon / net_polygon = [[x,y], ...]；internal_lines =
    [[[x,y], ...], ...]；notches = [[x,y,nx,ny], ...]；grain_line = [x1,y1,x2,y2] 或 null。
    """
    by_size: dict[int | None, list] = {}
    for p in pieces:
        by_size.setdefault(p.size, []).append(p)

    sizes_out = []
    for size in sorted(by_size.keys(), key=_size_sort_key):
        members = by_size[size]
        # 稳定排序：DXF 数学系下质心 Y 大者（视觉上方）优先 → X 小者（视觉左）优先 → 面积大者优先
        members_sorted = sorted(
            members,
            key=lambda p: (
                -_centroid(p.polygon_mm)[1],
                _centroid(p.polygon_mm)[0],
                -p.area_mm2,
                p.block_name,
                p.piece_index,
            ),
        )
        pieces_out = []
        for idx, p in enumerate(members_sorted):
            pieces_out.append({
                'label': _label_for(idx),
                'name': p.block_name,
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

    1. ``explore.collect_pieces`` 取母版全部 layer1 毛版外轮廓；
    2. ``export_dxf.assign_group_no`` + ``GROUP_NAMES`` 定片型；
    3. ``write_piece_dxf`` 切单裁片到 ``paths.OUT_DIR/uploads/<doc_id>_pieces/``；
    4. ``load_nest_pieces(pieces_dir, sizes=母版全码)`` 对齐布纹线 + 归一化 + L/R 镜像；
    5. 备份原 intermediate 为 ``.bak`` 后覆盖写回（schema 与 ``ms-pieces-export`` 一致）。

    返回新 intermediate 摘要 dict（码数/裁片数/总面积/备份路径）。
    """
    pieces = explore.collect_pieces(Path(src_dxf))
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

    # intermediate schema 与 ms-pieces-export（pieces_export.py）完全一致
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
            }
            for p in nest_pieces
        ],
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
# 扩 5 层后自动带 net_polygon/internal_lines/notches/grain_line，前端 layer-aware 渲染）。
_PTYPE_REPRESENTATIVE_FIELDS = (
    'polygon', 'net_polygon', 'internal_lines', 'notches', 'grain_line',
)


@app.get('/api/ptypes')
def get_ptypes():
    """US-020 D10：返回当前 ``_PIECES_STATE`` 下每个 ptype 的代表裁片（首个出现）。

    响应：``{representatives: Record<ptype, {polygon, net_polygon?, internal_lines?,
    notches?, grain_line?}>}``。v1 intermediate 只有 polygon → 仅返 polygon 字段；
    US-024 intermediate 扩 5 层后自动带 net_polygon/internal_lines/notches/grain_line
    （前端 layer-aware 渲染，无需改本端点）。空 state（首次启动未 commit、intermediate
    解析失败）返回 ``{representatives: {}}``，不阻塞前端配置弹窗降级为片型名文字。
    """
    state = _get_pieces_state()
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
               placed:[{id,rotation,translation},...]}
    返回文件字节流（Content-Disposition 附件下载，中文文件名走 RFC5987）。
    """
    state = _get_pieces_state()
    pieces_by_id = state.get('pieces_by_id') or {}
    gate_mm = state.get('gate_mm') or 0.0

    payload = await req.json()
    fmt = payload.get('fmt')
    placed = payload.get('placed') or []
    width_mm = float(payload.get('width_mm') or 0.0)
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
    else:
        return JSONResponse({'error': f'未知格式 {fmt}'}, status_code=400)

    fname_ascii = f'nesting_{sizes_str}_{pct:.2f}pct_seed{seed}.{ext}'
    fname_cn = f'排料_码{sizes_str}_{pct:.2f}pct_seed{seed}.{ext}'
    cd = f"attachment; filename=\"{fname_ascii}\"; filename*=UTF-8''{quote(fname_cn)}"
    return Response(content=data, media_type=media,
                    headers={'Content-Disposition': cd})


@app.websocket('/ws/solve')
async def ws_solve(ws: WebSocket):
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
    seed = int(msg.get('seed', 0))
    params = msg.get('params') or None
    per_type = msg.get('per_type') or None
    # US-022：quantities = {label: {sizeKey: N}}（per-size demand；0=该 piece 该码不排）。
    # 缺省/None → 全片 demand=1（向后兼容旧前端 / 旧 intermediate 无 label）。
    quantities = msg.get('quantities')
    if not isinstance(quantities, dict):
        quantities = None

    try:
        instance, config, pid_meta, total_area, n_eroded = build_instance(
            pieces, gate_mm, time_budget=time_budget, seed=seed,
            sizes=sizes, params=params, per_type=per_type, quantities=quantities)
    except Exception as e:
        await ws.send_json({'type': 'error', 'message': f'构造实例失败: {e}'})
        return

    # 1) manifest：base 几何（erode 后）+ 颜色
    await ws.send_json({
        'type': 'manifest',
        'gate_mm': gate_mm,
        'total_area_mm2': total_area,
        'n_eroded': n_eroded,
        'pieces': [
            {'id': pid, 'ptype': m['ptype'], 'size': m['size'], 'color': m['color'],
             'area_mm2': m['area_mm2'], 'polygon': m['polygon']}
            for pid, m in pid_meta.items()
        ],
    })

    # 2) 同步求解线程 → 异步事件循环 桥接
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    counter = {'n': 0}

    def on_report(report):
        report['index'] = counter['n']
        counter['n'] += 1
        # density 口径换算：sparrow 自报(erode后面积) → 原面积口径（与 90% 生死线一致）
        w = report['width_mm']
        report['density_sparrow'] = report['density']
        report['density'] = (total_area / (w * gate_mm)) if w > 0 else 0.0
        loop.call_soon_threadsafe(queue.put_nowait, report)

    def run_solve():
        sol, dt, err = solve_with_callback(instance, config, on_report)
        if err is not None:
            final = {'type': 'error', 'message': f'求解失败: {err}'}
        else:
            sw = float(sol.width) if sol else 0.0
            real = (total_area / (sw * gate_mm)) if sw > 0 else 0.0
            final = {
                'type': 'final',
                'density': real,
                'density_sparrow': float(sol.density) if sol else 0.0,
                'width_mm': sw,
                'elapsed': round(dt, 2),
                'n_frames': counter['n'],
                'n_eroded': n_eroded,
            }
        loop.call_soon_threadsafe(queue.put_nowait, final)
        loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    loop.run_in_executor(_executor, run_solve)

    # 3) 协程侧消费队列 → 推 WS
    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            await ws.send_json(item)
    except Exception:
        pass   # 客户端中途断开等，忽略；求解线程会自行跑完收尾


def main():
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)


if __name__ == '__main__':
    main()
