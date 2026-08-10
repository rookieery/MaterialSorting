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
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from urllib.parse import quote

from .. import paths
from ..dxf_parser.collect import collect_pieces_with_details

STATIC_DIR = paths.STATIC_DIR
from .solver import build_instance, load_pieces, solve_with_callback
from .export import placed_to_world, render_png, write_marker_dxf

# 启动时读一次中间数据（128 片几何），缓存复用
_DOC, GATE_MM, PIECES = load_pieces()
PIECES_BY_ID = {p['pid']: p for p in PIECES}   # pid → 原始轮廓+ptype，导出用

app = FastAPI(title='排料可视化工作台')
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')
_executor = ThreadPoolExecutor(max_workers=6)   # 多 seed 对比最多 6 个并发求解（seed 间同等 CPU 竞争 → 排名仍公平）
_SENTINEL = object()

# US-004：上传解析配置
UPLOAD_MAX_BYTES = 20 * 1024 * 1024   # 20MB 上限（实测生产母版 ~3MB，留足余量）
UPLOADS_DIR = Path(paths.OUT_DIR) / 'uploads'


# ---------------------------------------------------------------- US-004 上传解析

def _label_for(idx: int) -> str:
    """0→A, 1→B, ..., 25→Z, 26→AA, 27→AB ...（每码裁片数实测 ≤10，AA+ 仅兜底）。"""
    s = ''
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(ord('A') + rem) + s
    return s


def _centroid(poly: list[tuple[float, float]]) -> tuple[float, float]:
    """顶点算术质心（用于稳定排序键）。"""
    if not poly:
        return (0.0, 0.0)
    sx = sum(x for x, _ in poly)
    sy = sum(y for _, y in poly)
    return (sx / len(poly), sy / len(poly))


def _size_sort_key(size: int | None) -> tuple[int, int]:
    """码号排序键：None 殿后，其余按数值升序。"""
    return (1, 0) if size is None else (0, size)


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


@app.get('/')
def index():
    return FileResponse(os.path.join(STATIC_DIR, 'index.html'))


@app.post('/export')
async def export(req: Request):
    """导出最优排料方案：前端 POST 最优 run 的最终帧 placed_items → 出 PNG / R12-DXF。

    payload = {fmt:'png'|'dxf', sizes:[..], seed, gate_mm, width_mm, density,
               placed:[{id,rotation,translation},...]}
    返回文件字节流（Content-Disposition 附件下载，中文文件名走 RFC5987）。
    """
    payload = await req.json()
    fmt = payload.get('fmt')
    placed = payload.get('placed') or []
    width_mm = float(payload.get('width_mm') or 0.0)
    density = float(payload.get('density') or 0.0)
    seed = payload.get('seed', 0)
    sizes = payload.get('sizes') or []

    if width_mm <= 0 or not placed:
        return JSONResponse({'error': '无可导出的方案（width=0 或无裁片）'}, status_code=400)

    world = placed_to_world(placed, PIECES_BY_ID)
    if not world:
        return JSONResponse({'error': '导出失败：placed 的 pid 均未匹配到原始轮廓'}, status_code=400)

    sizes_str = '-'.join(str(s) for s in sorted(int(s) for s in sizes)) if sizes else 'all'
    pct = density * 100

    if fmt == 'png':
        title = (f'M1787 直筒 | 码 {sizes_str} | 利用率 {pct:.2f}% | '
                 f'用布 {width_mm / 1000:.2f} m | 门幅 {int(GATE_MM)} mm | seed {seed}')
        data = render_png(world, width_mm=width_mm, gate_mm=GATE_MM, title=title)
        media, ext = 'image/png', 'png'
    elif fmt == 'dxf':
        title = f'M1787 util={pct:.2f}% L={width_mm / 10:.1f}cm gate={int(GATE_MM)} seed={seed}'
        data = write_marker_dxf(world, width_mm=width_mm, gate_mm=GATE_MM, title=title)
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

    sizes = msg.get('sizes') or []
    time_budget = int(msg.get('time', 120))
    seed = int(msg.get('seed', 0))
    params = msg.get('params') or None
    per_type = msg.get('per_type') or None

    try:
        instance, config, pid_meta, total_area, n_eroded = build_instance(
            PIECES, GATE_MM, time_budget=time_budget, seed=seed,
            sizes=sizes, params=params, per_type=per_type)
    except Exception as e:
        await ws.send_json({'type': 'error', 'message': f'构造实例失败: {e}'})
        return

    # 1) manifest：base 几何（erode 后）+ 颜色
    await ws.send_json({
        'type': 'manifest',
        'gate_mm': GATE_MM,
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
        report['density'] = (total_area / (w * GATE_MM)) if w > 0 else 0.0
        loop.call_soon_threadsafe(queue.put_nowait, report)

    def run_solve():
        sol, dt, err = solve_with_callback(instance, config, on_report)
        if err is not None:
            final = {'type': 'error', 'message': f'求解失败: {err}'}
        else:
            sw = float(sol.width) if sol else 0.0
            real = (total_area / (sw * GATE_MM)) if sw > 0 else 0.0
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
