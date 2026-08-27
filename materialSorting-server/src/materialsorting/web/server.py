"""排料可视化工作台 · FastAPI 服务 + WebSocket。

启动：python server.py  →  http://127.0.0.1:8000

WS 协议（详见 README / 实现计划；US-002 起全 label 键，不再接收/透传 paired/internal）：
  client → {action:start, sizes:[...], time:N, seed:N, gate_mm?:N,
            params:{d_ext,d_int,tol_ext,tol_int}?,          # d_int/tol_int 已无消费方（恒 0）
            per_type:{label:{d?,tol?}}?,                     # g 码逐片覆盖（该码全部码号生效）
            quantities:{label:{sizeKey:N}}?}                 # per-size demand（0=跳过）
  server → {type:manifest, ...} 一次（pieces 条目含 label/color(size_color)/demand/5 层）
         → {type:frame, density(原面积口径), density_sparrow(erode后口径), ...} 每个中间解
         → {type:final,   ...} 收尾  （或 {type:error, message}）

阶段 B：density 统一用原面积口径 real_density = total_area/(width*min(gate, PLOT_SAFE_MAX_Y_MM))
        （实际幅宽口径，2026-08-20 起分母与求解约束带同口径），与版师/90%生死线一致；
        erode 后的 sparrow 自报密度保留为 density_sparrow 供参考。

模块结构（行为保持拆分）：本文件保留 app 装配 + 上传解析/commit 路由（含
``_commit_to_nesting_sync`` —— tests monkeypatch ``server_mod.UPLOADS_DIR`` 后直接
调用，函数 ``__globals__`` 必须留在本模块才能吃到 patch）；其余机械拆出：
  - ``runtime.py``        pieces state 快照 + 共享 executor（import 即做启动 reload）；
  - ``parse_payload.py``  解析预览 / label 代表裁片纯函数；
  - ``routes_views.py``   GET / 、GET /api/ptypes 、POST /export；
  - ``routes_ws.py``      WS /ws/solve + 求解子进程终止封装。
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import paths
from ..dxf_parser.collect import collect_pieces_with_details
from ..dxf_parser.export_dxf import write_piece_dxf
from ..nesting_bounds.load_pieces import (
    load_nest_pieces,
    GATE_MM as NEST_GATE_MM,
    PIECES_MANIFEST_NAME,
)
from ..nesting_engine.labeling import assign_codes

STATIC_DIR = paths.STATIC_DIR
# 共享运行时：import 即触发启动期 `_reload_pieces_state()` 读 intermediate 填
# `_PIECES_STATE`（与拆分前同为 app 创建之前发生的模块级副作用）。下列名字同时在
# server 命名空间 re-export：strategy.py 延迟 `from .server import _get_pieces_state`、
# tests 读 `server_mod._PIECES_STATE` / patch `server_mod.UPLOADS_DIR`（后者定义在
# 本文件，见下）。`_PIECES_STATE` 只原位 clear+update，re-export 的是同一 dict 对象。
from .runtime import (  # noqa: E402（保持与原文件同序：state 副作用先于 app 创建）
    _PIECES_STATE,
    _build_pieces_state,
    _executor,
    _get_pieces_state,
    _reload_pieces_state,
    _state_lock,
)
from .parse_payload import (
    _build_label_representatives,
    _build_parse_payload,
    _size_sort_key,
)
# US-001（web 多会话）：sessions → runtime 单向依赖（sessions 不 import 本模块，无环）。
# sid 字符集单一真相源移至 sessions.SID_RE（doc_id/sid 同规则），此处 re-export 为
# ``_DOC_ID_RE`` 保旧名兼容（US-010 commit 校验继续用）；``session_registry`` 是全
# 进程唯一 SessionRegistry 单例（POST /api/session + 后续 US-002~004 各入口共用）。
from .sessions import (  # noqa: E402
    SID_RE as _DOC_ID_RE,
    SessionError,
    registry as session_registry,
)

app = FastAPI(title='排料可视化工作台')
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')

# US-004：上传解析配置
UPLOAD_MAX_BYTES = 20 * 1024 * 1024   # 20MB 上限（实测生产母版 ~3MB，留足余量）
UPLOADS_DIR = Path(paths.OUT_DIR) / 'uploads'
# US-010：doc_id 合法字符集 —— 已移至 sessions.SID_RE（doc_id/sid 同规则单一真相源），
# 本模块经顶部 ``from .sessions import SID_RE as _DOC_ID_RE`` re-export 保旧名。


# ---------------------------------------------------------------- US-004 上传解析

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
    """US-010 Path A 全管线（同步，跑在 executor 里）—— v2：label 先行、名称清零、零合成。

    1. ``collect.collect_pieces_with_details`` 取母版全部 5 层（layer1/14/8/4/7，US-024）；
    2. ``labeling.assign_codes`` **最先**算 g 码（label 先行，名称无关，驱动后续一切）；
    3. ``write_piece_dxf`` 切单裁片 ``{label}_{size}.dxf``（5 层全写出）+ 写
       ``pieces_manifest.json`` sidecar 到 ``paths.OUT_DIR/uploads/<doc_id>_pieces/``；
    4. ``load_nest_pieces(pieces_dir)`` manifest 驱动对齐布纹线 + 归一化（无镜像展开）；
    5. 备份原 intermediate 为 ``.bak`` 后覆盖写回（schema v2：每母版轮廓恰一条，
       片内无 ptype/side，顶层 ``label_representatives``）。

    未录入名称的组不再 skip（零丢片）；size 为 None 的片仍跳过（无法落
    ``{label}_{size}.dxf`` 文件名，与 parse 响应的 null 码组一致）。
    返回新 intermediate 摘要 dict（码数/裁片数/总面积/备份路径）。
    """
    # US-024：用 collect_pieces_with_details 取代 explore.collect_pieces，让 write_piece_dxf
    # 拿到 PieceOutline 全 5 层（layer1+layer7+layer14+layer8+layer4）。
    pieces = collect_pieces_with_details(Path(src_dxf))
    if not pieces:
        raise RuntimeError('母版未提取到任何裁片（layer1 POLYLINE 为空）')

    # g 码最先（label 先行）：与 parse 同一 ``assign_codes``（同 collect、同排序键、
    # 同母版码规则），同一 (block_name, size, piece_index) 必得同码（AC#5）。
    codes_by_size = assign_codes(pieces)

    # 切单裁片（idempotent：每次 commit 先清空再重写，避免残留旧文件污染）
    pieces_dir = UPLOADS_DIR / f'{doc_id}_pieces'
    if pieces_dir.exists():
        shutil.rmtree(pieces_dir)
    pieces_dir.mkdir(parents=True, exist_ok=True)

    # 按码升序 × 码内有序写 {label}_{size}.dxf + manifest 条目（manifest 驱动加载的
    # 唯一语义源；文件名仅人读）。
    manifest: list[dict] = []
    skipped: list[str] = []
    for size in sorted(codes_by_size.keys(), key=_size_sort_key):
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

    # 每 g 码 RAW 代表裁片（原始坐标，供 /api/ptypes 缩略图与上传预览同朝向）。
    label_representatives = _build_label_representatives(pieces)

    # intermediate schema v2：每母版轮廓恰一条（WYSIWYG），无 ptype/side/paired。
    # US-004（策略 web 桥接）：doc_id 记入 doc —— 策略 start 定位母版原件
    # ``out/uploads/<doc_id>.dxf``（spawn CLI 子进程的 master_dxf）；旧 intermediate
    # 无此键 → 策略 start 422 提示重新上传 commit。
    doc = {
        'doc_id': doc_id,
        'source': source_name,
        'gate_mm': NEST_GATE_MM,
        'n_pieces': len(nest_pieces),
        'total_area_mm2': round(sum(p.area_mm2 for p in nest_pieces), 1),
        'pieces': [
            {
                'pid': p.pid,
                'label': p.label,
                'size': p.size,
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
        # 每 g 码 RAW 代表裁片（原始坐标，与上传预览同朝向；见 _build_label_representatives）。
        'label_representatives': label_representatives,
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
        'sizes': sorted({m['size'] for m in manifest}),
        'n_pieces': len(nest_pieces),
        'total_area_mm2': doc['total_area_mm2'],
        'n_written_dxf': len(manifest),
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


# ---------------------------------------------------------------- US-001 会话注册

@app.post('/api/session')
async def create_session(request: Request):
    """US-001：会话注册 / 幂等刷活性。读 ``X-Session-Id`` Header（缺省 → default 会话）。

    - 合法 sid 且容量未满 → 建会话或刷活性，``200 {ok:true, sid}``；
    - 活跃会话数达 ``MS_SESSION_MAX``（缺省 4，default 不占额）→ ``429
      {code:'session_limit'}``；
    - sid 命中墓碑 / 惰性检查发现已超时 → ``401 {code:'session_expired'}``（不静默
      重建，前端阻断弹窗要求刷新）；
    - sid 格式非法 → ``400 {error:'sid 非法'}``。

    会话生命周期细节（TTL/墓碑/扫描线程）见 ``sessions.py``；本路由只做
    Header 解析 + ``resolve(create=True)`` + 异常 → JSONResponse 映射。
    """
    sid = (request.headers.get('x-session-id') or '').strip() or None
    try:
        st = session_registry.resolve(sid, create=True)
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)
    return {'ok': True, 'sid': st.sid}


# ------------------------------------------------- 视图/导出/WS 路由（机械拆出，路由表顺序与拆分前一致）
from . import routes_views, routes_ws  # noqa: E402

app.include_router(routes_views.router)
app.include_router(routes_ws.router)
# 拆出路由的处理函数与私有符号 re-export（保持 ``from .server import X`` 兼容）：
from .routes_views import (  # noqa: E402,F401
    _LABEL_REPRESENTATIVE_FIELDS,
    export,
    get_ptypes,
    index,
)
from .routes_ws import (  # noqa: E402,F401
    _SENTINEL,
    _terminate_solve_process,
    ws_solve,
)


def main():
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)


# US-004：web 策略桥接四路由（start/status/stop/result）。strategy 模块对本模块
# 的依赖走函数内延迟 import（本行位于文件尾，此时 server 模块已完整初始化），
# 模块级无环。strategy **禁 import ..cli.\***（AST 守卫，见 tests/test_web_strategy.py）
# —— spawn 子进程是进程边界而非 import 边界，判据逻辑单一真相源留在 cli。
from .strategy import register_strategy_routes   # noqa: E402

register_strategy_routes(app)

# US-001：会话过期 30s daemon 扫描线程 —— 惰性检查的兜底（已死会话不再发请求，
# 容量名额只能由扫描回收）。daemon=True：进程退出不阻塞；测试经 stop_scanner() 停。
session_registry.start_scanner()


if __name__ == '__main__':
    main()
