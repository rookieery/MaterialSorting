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
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from urllib.parse import quote

from .. import paths

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
