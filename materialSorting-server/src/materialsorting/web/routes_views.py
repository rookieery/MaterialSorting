"""页面 / 只读视图 / 导出路由（自 server.py 机械拆出，行为不变）。

GET ``/``（index.html）、GET ``/api/ptypes``（label 代表裁片）、POST ``/export``
（PNG / R12-DXF / PLT marker 下载）。pieces state 快照来自 ``web.runtime``；
导出几何/渲染走 ``web.export`` 门面（路径不变）。
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from urllib.parse import quote

from .. import paths
from .export import placed_to_world, render_png, write_marker_dxf, write_marker_plt
from .runtime import _get_pieces_state

router = APIRouter()
STATIC_DIR = paths.STATIC_DIR


@router.get('/')
def index():
    return FileResponse(os.path.join(STATIC_DIR, 'index.html'))


# ---------------------------------------------------------------- US-020 GET /api/ptypes

# intermediate piece → label 代表裁片字段白名单（5 层透传：polygon/net_polygon/
# internal_lines/notches/grain_line + label 自身，前端 layer-aware 渲染）。
_LABEL_REPRESENTATIVE_FIELDS = (
    'label', 'polygon', 'net_polygon', 'internal_lines', 'notches', 'grain_line',
)


@router.get('/api/ptypes')
def get_ptypes():
    """US-020 D10：返回当前 ``_PIECES_STATE`` 下每个 g 码（label）的代表裁片。

    响应：``{representatives: Record<label, {label, polygon, net_polygon,
    internal_lines, notches, grain_line}>}`` —— 键 = 裁片 g 码（v2 起 ptype 键删除）。
    选取口径与 ``_build_parse_payload`` 赋号同源同序，保证「编号 → 图形」与上传预览
    列头一致。空 state（首次启动未 commit、intermediate 解析失败）返回
    ``{representatives: {}}``，不阻塞前端配置弹窗降级为文字。

    坐标口径（US-024fix）：优先返 intermediate ``label_representatives`` —— **RAW 母版
    原始坐标**，与 ``/api/parse-dxf`` 上传预览同朝向（未走布纹对齐旋转），让缩略图与
    上传预览一致、可辨认。无此字段时回退到 ``pieces`` 首个代表（变换后坐标）。
    """
    state = _get_pieces_state()
    reps = (state.get('doc') or {}).get('label_representatives')
    if reps is not None:
        return {'representatives': reps}
    pieces = state.get('pieces') or []
    representatives: dict[str, dict] = {}
    for p in pieces:
        label = p.get('label')
        if label is None or label in representatives:
            continue
        rep = {k: p[k] for k in _LABEL_REPRESENTATIVE_FIELDS if k in p}
        representatives[label] = rep
    return {'representatives': representatives}


@router.post('/export')
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
