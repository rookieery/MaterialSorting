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

阶段 B：density 统一用原面积口径 real_density = total_area/(width*gate_mm)
        （输入门幅即实际幅宽，2026-08-28 起分母与求解约束带同口径单一化），与
        版师/90%生死线一致；erode 后的 sparrow 自报密度保留为 density_sparrow 供参考。

模块结构（行为保持拆分）：本文件保留 app 装配 + 上传解析/commit 路由（含
``_commit_to_nesting_sync`` —— tests monkeypatch ``server_mod.UPLOADS_DIR`` 后直接
调用，函数 ``__globals__`` 必须留在本模块才能吃到 patch）；其余机械拆出：
  - ``runtime.py``        pieces state 快照 + 共享 executor（import 即做启动 reload）；
  - ``parse_payload.py``  解析预览 / label 代表裁片纯函数；
  - ``routes_views.py``   GET / 、GET /api/ptypes 、POST /export；
  - ``routes_ws.py``      WS /ws/solve + 求解子进程终止封装；
  - ``diskclean.py``      US-006 uploads TTL 清理（commit 尾触发 + main() 启动触发）。
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import paths
from ..dxf_parser.collect import collect_pieces_with_details
from ..dxf_parser.export_dxf import write_piece_dxf
from ..nesting_bounds.load_pieces import (
    load_nest_pieces,
    GATE_MM,
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
# US-006（uploads TTL 清理）：diskclean 模块级仅标准库 + paths（sessions/strategy
# 走函数内延迟 import），禁 import 本模块（无环）；commit 触发点在
# ``commit_to_nesting`` 尾部、进程启动触发点在 ``main()``。
from . import diskclean  # noqa: E402
# 编辑排料会话钉住（2026-09-04）：edit_hold → sessions 单向依赖，禁 import 本模块
# （无环，AST 守卫见 tests/test_web_edit_hold.py）。模块级无副作用（install 在
# 文件尾 strategy 注册之后显式调用 —— 单 slot 覆盖式，顺序反了会被覆写丢组合）。
from . import edit_hold  # noqa: E402

app = FastAPI(title='排料可视化工作台')
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')

# US-004：上传解析配置
UPLOAD_MAX_BYTES = 20 * 1024 * 1024   # 20MB 上限（实测生产母版 ~3MB，留足余量）
UPLOADS_DIR = Path(paths.OUT_DIR) / 'uploads'
# US-010：doc_id 合法字符集 —— 已移至 sessions.SID_RE（doc_id/sid 同规则单一真相源），
# 本模块经顶部 ``from .sessions import SID_RE as _DOC_ID_RE`` re-export 保旧名。

# US-002（多会话）：per-doc intermediate 文件名（与全局镜像 paths.INTERMEDIATE 同名
# 同 schema v2），落盘在切片目录内 —— 与 {label}_{size}.dxf / pieces_manifest.json
# 同源同生命周期（commit 先清空重写整个目录，天然 idempotent）。
PIECES_INTERMEDIATE_NAME = 'pieces_intermediate.json'


def _per_doc_intermediate(doc_id: str) -> Path:
    """US-002：per-doc intermediate 路径 ``out/uploads/<doc_id>_pieces/pieces_intermediate.json``。

    commit 双写的主写点（会话快照数据源，schema 与全局镜像一致）；后续读路由
    （US-003）与磁盘清理（US-006）复用同一约定。依赖模块级 ``UPLOADS_DIR``
    （tests monkeypatch ``server_mod.UPLOADS_DIR`` 经 ``__globals__`` 生效）。
    """
    return UPLOADS_DIR / f'{doc_id}_pieces' / PIECES_INTERMEDIATE_NAME


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
    5. US-002 双写：主写 per-doc ``uploads/<doc_id>_pieces/pieces_intermediate.json``
       （schema v2：每母版轮廓恰一条，片内无 ptype/side，顶层 ``label_representatives``），
       镜像写全局 ``paths.INTERMEDIATE``（同一 doc dict 两个文件；顺序先 per-doc 后
       镜像，镜像失败仅 warn 不影响会话；``.bak`` 备份行为保留在镜像侧）。

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
        'gate_mm': GATE_MM,
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

    # US-002 双写（同一 doc dict 写两文件，顺序先 per-doc 后镜像）：
    #   主写 per-doc —— 会话快照的数据源（多会话互不覆盖的磁盘锚点）；
    #   镜像写全局 paths.INTERMEDIATE —— 单文档时代行为的兼容面（无 sid 启动 reload
    #   / CLI 工具链 / 人工排查），失败仅 warn 不影响会话（快照只依赖 per-doc 落盘）。
    per_doc_path = _per_doc_intermediate(doc_id)
    with open(per_doc_path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)

    mirror_error: str | None = None
    # 备份原 intermediate 为 .bak（首次写回时无原文件 → 不备份；备份行为保留在镜像侧）
    intermediate = Path(paths.INTERMEDIATE)
    bak_path = intermediate.with_suffix('.bak')
    try:
        intermediate.parent.mkdir(parents=True, exist_ok=True)
        if intermediate.exists():
            shutil.copy2(intermediate, bak_path)
        with open(intermediate, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False)
    except Exception as e:
        mirror_error = str(e)
        print(f'[server] intermediate 镜像写失败（不影响会话，per-doc 已落盘）：{e}',
              file=sys.stderr)

    result = {
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
    if mirror_error is not None:
        result['mirror_error'] = mirror_error
    return result


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

    US-002（多会话）：读 ``X-Session-Id`` Header —— 带 sid：会话解析先行（fail-fast，
    过期 401 / 超限 429 / 非法 400，不跑 CPU 管线不落盘），commit 成功后用
    ``_build_pieces_state(per-doc 路径)`` 构建快照注册进该会话，**不触碰 default 内存**
    （镜像文件已由 commit_sync 双写刷新，但 default = 最后无 sid commit 者，镜像 =
    最后 commit 者，允许漂移）；无 sid：default 会话更新（现行为；default 与
    ``runtime._PIECES_STATE`` 同一 dict，reload 即同步）。

    US-006：成功响应前 best-effort 触发 ``diskclean.trigger_cleanup``（uploads TTL
    清理，异常仅 warn 不影响响应；本轮 commit 的产物 mtime 新 + 会话 doc_id 在
    保护集，天然不被清）。
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

    sid = (req.headers.get('x-session-id') or '').strip() or None
    if sid:   # 带 sid：解析先行（刷 last_active；SessionError → 结构化错误早退）
        try:
            st = session_registry.resolve(sid, create=True)
        except SessionError as e:
            return JSONResponse(e.payload(), status_code=e.status)
    else:     # 无 sid：default 会话（state = runtime._PIECES_STATE 同一 dict）
        st = session_registry.resolve(None)

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

    # US-020/US-002：intermediate 已写盘 → 快照注册。
    #   带 sid：读 per-doc 落盘构建快照挂到该会话（default 内存不动）；
    #   无 sid：锁内原子重读镜像 → 下次 /ws/solve 拿到新裁片（default 会话 state
    #   即 runtime._PIECES_STATE 同一 dict，自动跟随）。
    # 防御：commit_sync 写盘已成功，正常路径必成功；若因罕见 I/O 竞态失败，记录
    # 日志、保留旧 state、标记 reloaded=false —— 前端 US-021 看到 reloaded=false
    # 可降级提示「需重启 ms-web」。
    try:
        if sid:
            st.state = _build_pieces_state(str(_per_doc_intermediate(doc_id)))
        else:
            # 显式传 paths.INTERMEDIATE（调用时取模块属性）：_reload_pieces_state 的
            # 缺省参数在 import 时已绑定旧值，monkeypatch paths.INTERMEDIATE 后裸调
            # 会重读启动期真实路径（测试隔离 + 路径热更都依赖调用时取值）。
            _reload_pieces_state(paths.INTERMEDIATE)
        st.doc_id = doc_id
        result['reloaded'] = True
    except Exception as e:
        print(f'[server] commit 后会话快照构建失败（保留旧 state）：{e}', file=sys.stderr)
        result['reloaded'] = False
        result['reload_error'] = str(e)

    # US-006：commit 成功后 best-effort TTL 清理 uploads —— executor 里跑不阻塞
    # 事件循环；**显式传 ``UPLOADS_DIR``**（本模块常量被测试 monkeypatch 后清理
    # 范围自动跟随 tmp，不会碰真实 out/）；``trigger_cleanup`` 吞掉一切异常仅
    # warn，绝不影响响应内容（外层 try 再兜一道防御）。
    try:
        await loop.run_in_executor(_executor, diskclean.trigger_cleanup,
                                   str(UPLOADS_DIR))
    except Exception as e:
        print(f'[server] uploads 清理失败（不影响 commit）：{e}', file=sys.stderr)
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


@app.post('/api/edit-hold')
async def post_edit_hold(request: Request):
    """编辑排料会话钉住心跳（2026-09-04）：前端编辑弹窗打开期间滚动调用。

    编辑排料纯前端（拖动/旋转/保存不发任何请求），长编辑（> ``MS_SESSION_TTL_SEC``
    缺省 10min）会被空闲过期逐出 → 保存后导出 401 全局阻断 → 刷新丢全部编辑成果。
    本端点把会话钉住到 ``now + MS_EDIT_HOLD_SEC``（缺省 2h，镜像策略 run 终态宽限
    语义 —— 编辑中睡眠 ≤2h 唤醒恢复、关窗后自然留 2h 宽限；宽限内仍占
    ``MS_SESSION_MAX`` 名额，与策略宽限口径一致）。

    - 无 sid（default 会话）→ ``200 {ok:true}`` no-op（default 豁免一切过期）；
    - 带合法 sid → ``resolve()`` 会话闸门（顺手刷 ``last_active``；过期/墓碑 →
      ``401 {code:'session_expired'}`` 不给死会话续命、非法 → 400）+ 续期钉住表。
    """
    sid = (request.headers.get('x-session-id') or '').strip() or None
    if sid is None:
        return {'ok': True}
    try:
        session_registry.resolve(sid)
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)
    edit_hold.refresh(sid, session_registry.clock())
    return {'ok': True}


@app.post('/api/edit-polish')
async def post_edit_polish(request: Request):
    """编辑排料「智能微调」会话族端点（prd-edit-polish US-002，2026-09-05）。

    前端编辑弹窗「智能微调」按钮 POST 当前编辑 placements（布局态后端不存、随
    body 带上 = /export 同模式，唯一存储在前端 runRegistry），取回确定性后处理
    结果 + 前后对比报告 —— 几何真相源留在 Python（物理毛版轮廓口径与会话
    ``pieces_by_id`` 原始 polygon / /export 同源），多会话经 ``X-Session-Id``
    隔离（编辑 A 的 placed 匹配 A 的母版轮廓）。

    请求 ``{placed:[{id,rotation,translation},...], gate_mm?, exclude?:{labels?,
    pids?}, compact?}``；响应 ``{ok:true, placed, report}``（placed 条数与 pid
    多重集与输入相等 —— polish 出口 Counter 终检 + 本路由入口 pid 全匹配双保险）。

    - sid：缺省 → default 会话；``resolve()`` 闸门（``create=False`` 缺省）：
      过期/墓碑 → ``401 {code:'session_expired'}``、非法 → 400（``SessionError``
      统一 ``JSONResponse(e.payload(), e.status)``，/api/edit-hold 同款）；
    - pid 全匹配才跑：任一 pid 未匹配会话 ``pieces_by_id`` → 400（文案提示
      「母版已变更？请重新求解/上传」，不做部分降级）；``placed`` 空 → 400；
    - ``gate_mm`` 缺省回退会话 ``state['gate_mm']``（与 /export、
      /api/plt-table-preview 同法）；
    - ``exclude`` 透传引擎（labels/pids 双键，缺省 None）；``compact`` = US-005
      预留键位（缺省 false）；
    - polish 构造段经 ``run_in_threadpool`` 执行（prefix-preview 先例，防阻塞
      事件循环）；顺手 ``edit_hold.refresh(sid)``（编辑钉住与心跳同语义，default
      不进钉住表 —— /api/edit-hold 同口径）。
    """
    from ..nesting_engine.polish import PolishError, polish_layout

    sid = (request.headers.get('x-session-id') or '').strip() or None
    try:
        st = session_registry.resolve(sid)   # create=False 缺省：不给未知 sid 建会话
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({'error': '请求体必须是 JSON'}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({'error': '请求体必须是 JSON 对象'}, status_code=400)

    placed = payload.get('placed')
    if not isinstance(placed, list) or not placed:
        return JSONResponse({'error': 'placed 不能为空（无微调输入）'}, status_code=400)
    for i, p in enumerate(placed):
        if (not isinstance(p, dict) or not p.get('id')
                or not isinstance(p.get('translation'), (list, tuple))
                or len(p['translation']) != 2):
            return JSONResponse(
                {'error': f'placed[{i}] 形态非法（需 {{id,rotation,translation}}）'},
                status_code=400)

    pieces_by_id = st.state.get('pieces_by_id') or {}
    unmatched = [p['id'] for p in placed if p['id'] not in pieces_by_id]
    if unmatched:
        return JSONResponse(
            {'error': f'pid {unmatched[0]!r} 不在会话 pieces_by_id'
                      f'（母版已变更？请重新求解/上传）'},
            status_code=400)

    # gate_mm：优先求解口径（前端 manifest.gate_mm），缺省/非法回退会话 state
    # （/export 同法）；两处皆无 → 400（守卫 y∈[0,gate] 无从谈起，fail-fast）。
    try:
        gate_mm = float(payload.get('gate_mm') or 0.0) \
            or float(st.state.get('gate_mm') or 0.0)
    except (TypeError, ValueError):
        return JSONResponse({'error': 'gate_mm 非法'}, status_code=400)
    if not gate_mm > 0.0:      # NaN 也拦（NaN > 0 恒 False）
        return JSONResponse(
            {'error': 'gate_mm 无效（payload 与会话 state 均未提供）'},
            status_code=400)

    exclude = payload.get('exclude')
    if exclude is not None and not isinstance(exclude, dict):
        return JSONResponse(
            {'error': 'exclude 必须是 {labels?, pids?} 对象'}, status_code=400)
    compact = bool(payload.get('compact') or False)

    def _polish():
        return polish_layout(placed, pieces_by_id, gate_mm,
                             exclude=exclude, compact=compact)

    try:
        placed_new, report = await run_in_threadpool(_polish)
    except (PolishError, ValueError, TypeError) as e:
        # PolishError：引擎不变量（pid 守恒终检等）；ValueError/TypeError：placed
        # 数值字段（rotation/translation 分量）非法 —— 都结构化 400 不炸 500。
        return JSONResponse({'error': f'微调失败：{e}'}, status_code=400)

    if sid:   # default 豁免一切过期，不进钉住表（/api/edit-hold 同口径）
        edit_hold.refresh(sid, session_registry.clock())
    return {'ok': True, 'placed': placed_new, 'report': report}


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
    # US-006：进程启动清理一轮超龄 uploads（daemon 线程不阻塞启动）。只在真正
    # server 进程触发 —— TestClient 测试导入 app 不起线程，不碰真实 out/。
    diskclean.start_startup_cleaner()
    uvicorn.run(app, host='127.0.0.1', port=8000)


# US-004：web 策略桥接四路由（start/status/stop/result）+ US-002 极限运行四路由
# （/api/extreme/*，同 strategy.py 内 mode='extreme' 分支、同会话状态槽单飞互斥）。
# strategy 模块对本模块的依赖走函数内延迟 import（本行位于文件尾，此时 server
# 模块已完整初始化），模块级无环。strategy **禁 import ..cli.\***（AST 守卫，见
# tests/test_web_strategy.py）—— spawn 子进程是进程边界而非 import 边界，判据
# 逻辑单一真相源留在 cli。
from .strategy import register_strategy_routes   # noqa: E402

register_strategy_routes(app)

# 编辑排料会话钉住（2026-09-04）：把 edit_hold 的编辑豁免与上面 strategy 注册的
# run 钉住 hook 组合成单 slot 唯一 hook（任一豁免源给出未来时间戳即不逐出）。
# **必须在 register_strategy_routes 之后**（strategy import 时覆写式注册自己的
# hook —— 先装组合体会被覆写丢编辑豁免）；幂等，晚于 start_scanner 也无碍
# （hook 只是逐出前的查询点）。
edit_hold.install(session_registry)

# US-001：会话过期 30s daemon 扫描线程 —— 惰性检查的兜底（已死会话不再发请求，
# 容量名额只能由扫描回收）。daemon=True：进程退出不阻塞；测试经 stop_scanner() 停。
session_registry.start_scanner()


if __name__ == '__main__':
    main()
