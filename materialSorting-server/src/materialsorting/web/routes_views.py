"""页面 / 只读视图 / 导出路由（自 server.py 机械拆出）。

GET ``/``（index.html）、GET ``/api/ptypes``（label 代表裁片）、POST ``/export``
（PNG / R12-DXF / PLT marker 下载）、POST ``/api/plt-table-preview``（PLT 唛架
信息表格 14 字段预览，2026-08-31）。导出几何/渲染走 ``web.export`` 门面（路径不变）。

多会话 US-003：全部读数据端点经 ``_resolve_session_state`` 从 SessionRegistry 解析
pieces state —— ``X-Session-Id`` Header → 该会话 commit（US-002）注册的 per-doc
快照；缺省 → default 会话（state 即 ``runtime._PIECES_STATE`` 同一 dict，无 sid
行为不变）。会话过期/超限/非法 → SessionError → 结构化 JSONResponse（401/429 带
``code`` 键，additive）。
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from urllib.parse import quote

from .. import paths
from .export import (
    placed_to_world,
    parse_table_payload,
    build_info_table,
    preview_rows,
    render_png,
    write_marker_dxf,
    write_marker_plt,
)
from .plt_table import TablePayloadError
from .sessions import SessionError, registry as session_registry

router = APIRouter()
STATIC_DIR = paths.STATIC_DIR


def _resolve_session_state(request: Request) -> dict:
    """US-003：读路由 pieces state 单一解析点（``X-Session-Id`` → SessionRegistry）。

    缺省/空串 → default 会话；带 sid → 该会话快照（commit 双写的主写 per-doc
    内容）。读路径 ``resolve()`` 缺省 ``create=False``：命中墓碑 / 惰性超时 /
    合法但未注册（服务重启丢内存）→ ``SessionExpiredError`` 401（不静默重建），
    满员未知 sid 不占新名额。调用方捕获 ``SessionError`` → ``e.payload()``。
    """
    sid = (request.headers.get('x-session-id') or '').strip() or None
    return session_registry.resolve(sid).state


@router.get('/')
def index():
    # US-003：no-cache —— index.html 必须每次重验证（FastAPI FileResponse 缺省不发
    # 缓存头，浏览器启发式缓存会让部署新 bundle 后旧 index 引用已删 hash 资源，
    # 旧前端滞留 default 会话语义的迁移窗口）；带 hash 的 /static 资源自身可长缓存。
    return FileResponse(os.path.join(STATIC_DIR, 'index.html'),
                        headers={'Cache-Control': 'no-cache'})


# ---------------------------------------------------------------- US-020 GET /api/ptypes

# intermediate piece → label 代表裁片字段白名单（5 层透传：polygon/net_polygon/
# internal_lines/notches/grain_line + label 自身，前端 layer-aware 渲染）。
_LABEL_REPRESENTATIVE_FIELDS = (
    'label', 'polygon', 'net_polygon', 'internal_lines', 'notches', 'grain_line',
)


@router.get('/api/ptypes')
def get_ptypes(request: Request):
    """US-020 D10：返回当前会话下每个 g 码（label）的代表裁片。

    响应：``{representatives: Record<label, {label, polygon, net_polygon,
    internal_lines, notches, grain_line}>}`` —— 键 = 裁片 g 码（v2 起 ptype 键删除）。
    选取口径与 ``_build_parse_payload`` 赋号同源同序，保证「编号 → 图形」与上传预览
    列头一致。空 state（首次启动未 commit、intermediate 解析失败）返回
    ``{representatives: {}}``，不阻塞前端配置弹窗降级为文字。

    坐标口径（US-024fix）：优先返 intermediate ``label_representatives`` —— **RAW 母版
    原始坐标**，与 ``/api/parse-dxf`` 上传预览同朝向（未走布纹对齐旋转），让缩略图与
    上传预览一致、可辨认。无此字段时回退到 ``pieces`` 首个代表（变换后坐标）。

    US-003（多会话）：``X-Session-Id`` → 各会话自己的 representatives；缺省 →
    default 会话（``_PIECES_STATE``）。sid 过期/非法 → 401/400 结构化 JSON。
    """
    try:
        state = _resolve_session_state(request)
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)
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


# ------------------------------------------------------- POST /api/band-preview 成带预览


@router.post('/api/band-preview')
async def band_preview(req: Request):
    """腰头成带预览（高级配置弹窗「布局设置」缩略图数据源，2026-08-24）。

    选中腰头 g 码后，缩略图从「原始代表裁片」（与下方裁片设置表格同源同图，纯
    冗余）改为**成带形态预览** —— 求解前即可见版师验收判据（链内贴触 / 码序降序
    / 开口朝左 / 最大码在最右），成带失败（fill 守卫 / 带高超幅等）也从 solve
    报错前置到选码时刻。

    payload 与 WS StartPayload 同源字段子集（band 校验直接复用 ``_parse_band``
    单一校验点）：``{band:{enabled,label}, sizes?, quantities?, per_type?,
    params?, gate_mm?}``。

    主进程同步跑 ``build_pid_meta + build_band_plan``（v2 链构造无 RNG、毫秒级、
    seed 不影响几何 ⇒ 预览 = 求解时带的精确形态；spyrrow 不参与）。成员 polygon
    由后端变换到带内归一坐标（减 ``chunk.offset``）返回 —— 前端无码级轮廓
    （/api/ptypes 每 g 码仅一个代表裁片），无法前端构造；颜色取 pid_meta['color']
    （``size_color`` 单一真相源，同码同色跨片型，与 manifest/NestSVG 同口径）。
    **不返回组合片 WB_ pid**（哨兵约定：WB_ 永不出现在前端/manifest/导出）。

    响应（失败也 200、``ok:false`` 包络 —— 选错 g 码是预期内常态而非异常，前端
    单条路径渲染错误文案，不区分网络/业务错误）::

        {ok:true, label, fill_pct, bbox:{width_mm,height_mm}, n_members,
         members:[{pid, size, color, polygon:[[x,y],...]}],   # 原始轮廓@带内归一位
         outline:[[x,y],...]}                                  # erode 后组合片外轮廓

    US-003（多会话）：``X-Session-Id`` → 该会话的 pieces/pieces_by_id；缺省 →
    default。sid 过期/非法 → 401/400 结构化 JSON（早于业务校验）。
    """
    from ..nesting_bounds.load_pieces import GATE_MM
    from ..nesting_engine.waist_band import BandError, build_band_plan
    from ..nesting_engine.sparrow_baseline import _transform_polygon
    from .routes_ws import _parse_band
    from .solver import _resolve_d_tol, build_pid_meta

    try:
        state = _resolve_session_state(req)
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)
    payload = await req.json()

    pieces = state.get('pieces') or []
    if not pieces:
        return {'ok': False, 'error': '排料数据为空（请先上传母版 commit）'}

    # band 校验：与 WS start 同一检查点（label ^g\d+$ / 存在于母版 / quantities>0）
    try:
        band_cfg = _parse_band(payload.get('band'), pieces, payload.get('quantities'))
    except ValueError as e:
        return {'ok': False, 'error': str(e)}
    if band_cfg is None:
        return {'ok': False, 'error': 'band 未开启或缺腰头编号'}
    label = band_cfg['label']

    # gate_mm：优先求解口径（前端 parseGate），缺省/非法回退 intermediate（与 /export 同法）
    gate = float(payload.get('gate_mm') or 0.0) or float(state.get('gate_mm') or 0.0)

    try:
        pdef = {'d_ext': 0.0, 'd_int': 0.0, 'tol_ext': 0.0, 'tol_int': 0.0}
        pdef.update(payload.get('params') or {})
        d_g, tol_g = _resolve_d_tol(label, pdef, payload.get('per_type'))
        pid_meta, _area, _n = build_pid_meta(
            pieces,
            sizes=payload.get('sizes'),
            per_type=payload.get('per_type'),
            quantities=payload.get('quantities'),
            params=payload.get('params'))
        chunk = build_band_plan(
            pid_meta, state.get('pieces_by_id') or {},
            label=label,
            seed=0,                       # 链构造无 RNG：seed 只进 chunk.seed 记录，几何无关
            gate_nest=float(gate) if gate > 0 else GATE_MM,
            d_g=d_g, tol_g=tol_g)
    except (BandError, ValueError) as e:
        return {'ok': False, 'error': f'成带失败: {e}'}

    pieces_by_id = state.get('pieces_by_id') or {}
    ox, oy = chunk.offset
    members = []
    for m in chunk.members:
        meta = pid_meta[m['pid']]
        # 原始轮廓@带内位 − offset（与 chunk.polygon 同一归一系；原始轮廓缺席时
        # 回退 erode 后轮廓 —— 与 build_band_plan 的 union 口径一致，包络安全方向）
        orig = pieces_by_id.get(m['pid'], {}).get('polygon') or meta['polygon']
        placed = _transform_polygon(orig, m['rotation'], m['translation'])
        members.append({
            'pid': m['pid'],
            'size': meta['size'],
            'color': meta['color'],
            'polygon': [[round(x - ox, 2), round(y - oy, 2)] for x, y in placed],
        })

    return {
        'ok': True,
        'label': label,
        'fill_pct': round(float(chunk.fill_pct), 2),
        'bbox': {'width_mm': round(float(chunk.bbox['width_mm']), 1),
                 'height_mm': round(float(chunk.bbox['height_mm']), 1)},
        'n_members': chunk.n_members,
        'members': members,
        'outline': [[round(x, 2), round(y, 2)] for x, y in chunk.polygon],
    }


# ---------------------------------------------------- POST /api/prefix-preview 前缀预览


@router.post('/api/prefix-preview')
async def prefix_preview(req: Request):
    """起始端成套前后幅预览（布局设置 prefix 行缩略图数据源，2026-08-25）。

    与成带预览同套路：选完前/后幅 g 码后不展示两张原始单片缩略（与下方裁片设置
    表格同源同图，纯冗余），改展示**求解时 PS_ 组合片的精确形态**（4 片同码
    interleave 竖排贴靠，或 2026-09-02 选码搜索加顶部异码补片的 5 片近满幅
    形态），构造失败（无资格码 / 竖排超高 / 贴触失败等）也从 solve 报错前置
    到选码时刻。

    payload 与 WS StartPayload 同源字段子集（prefix 校验直接复用 ``_parse_prefix``
    单一校验点）：``{prefix:{enabled,front,back}, sizes?, quantities?, per_type?,
    params?, gate_mm?, seed?}``。选码确定性化（``select_prefix_plan`` 近满幅
    几何搜索，无 RNG，2026-09-02）后预览**不再依赖 seed 对齐** —— 搜索路径与
    seed 无关恒与求解同选；seed 仅兜底 4 片路径的 ``pick_prefix_size`` 消费
    （缺省 0 = 与求解同参同选）。

    构造段（``build_pid_meta`` → ``select_prefix_plan``，与 solve_worker
    ``_build_prefix`` 同一真相源；选码搜索秒级 —— 5336 规模 ~120 组合实测
    ~4.3s < 5s 红线）经 ``run_in_threadpool`` 在工作线程执行，防阻塞事件循环
    （多会话并发下主进程卡顿）；会话解析/校验仍主线程先行（401/400 早退语义
    不变）。成员 polygon 由后端变换到组合片归一坐标（减 ``chunk.offset``）
    返回，``tag`` = 成员 g 码（前后幅区分标注）；颜色取 pid_meta['color']
    （``size_color`` 单一真相源）。**不返回组合片 PS_ pid**（哨兵约定：PS_
    永不出现在前端/manifest/导出）。

    响应（失败也 200、``ok:false`` 包络，band-preview 同约定）::

        {ok:true, front, back, size, fill_pct, bbox:{width_mm,height_mm},
         n_members,                    # 4（兜底）或 5（顶部异码补片，2026-09-02）
         members:[{pid, size, color, tag, polygon:[[x,y],...]}],
         extra:{label,size}|null,      # 补片在案时非 null（兜底 4 片 = null）
         residual_mm,                  # gate_mm − 组合片高（近满幅残余缝隙）
         gate_mm,                      # 实际参与构造的门幅（payload > intermediate 回退）
         fallback,                     # true = 无可行 5 片组合 → 兜底 4 片 seeded
         outline:[[x,y],...]}

    US-003（多会话）：``X-Session-Id`` → 该会话的 pieces/pieces_by_id；缺省 →
    default。sid 过期/非法 → 401/400 结构化 JSON（早于业务校验）。
    """
    from ..nesting_bounds.load_pieces import GATE_MM
    from ..nesting_engine.prefix import PrefixError, select_prefix_plan
    from ..nesting_engine.sparrow_baseline import _transform_polygon
    from .routes_ws import _parse_prefix
    from .solver import _resolve_d_tol, build_pid_meta

    try:
        state = _resolve_session_state(req)
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)
    payload = await req.json()

    pieces = state.get('pieces') or []
    if not pieces:
        return {'ok': False, 'error': '排料数据为空（请先上传母版 commit）'}

    # prefix 校验：与 WS start 同一检查点（g 码格式 / 存在于母版 / front≠back /
    # ≥1 个 2+2 资格码，sizes = 用户所排尺码过滤）
    sizes = payload.get('sizes')
    try:
        prefix_cfg = _parse_prefix(payload.get('prefix'), pieces,
                                   payload.get('quantities'), sizes)
    except ValueError as e:
        return {'ok': False, 'error': str(e)}
    if prefix_cfg is None:
        return {'ok': False, 'error': 'prefix 未开启或缺前/后幅 g 码'}
    front = prefix_cfg['front']
    back = prefix_cfg['back']

    # gate_mm：优先求解口径（前端 parseGate），缺省/非法回退 intermediate（band-preview 同法）
    gate = float(payload.get('gate_mm') or 0.0) or float(state.get('gate_mm') or 0.0)
    gate_nest = float(gate) if gate > 0 else GATE_MM
    quantities = payload.get('quantities')
    per_type = payload.get('per_type')
    params = payload.get('params')
    seed = int(payload.get('seed') or 0)

    def _construct():
        # 构造段（选码搜索秒级）整体入工作线程（US-003 线程池化）：与
        # solve_worker._build_prefix 同参同源 —— 同 payload ⇒ 与求解同选
        # （A/片型/B/rot），预览 = 求解时第一列的精确形态。
        pdef = {'d_ext': 0.0, 'd_int': 0.0, 'tol_ext': 0.0, 'tol_int': 0.0}
        pdef.update(params or {})
        d_front, _tf = _resolve_d_tol(front, pdef, per_type)
        d_back, _tb = _resolve_d_tol(back, pdef, per_type)
        pid_meta, _area, _n = build_pid_meta(
            pieces,
            sizes=sizes,
            per_type=per_type,
            quantities=quantities,
            params=params)
        chunk, gaps, holes, info = select_prefix_plan(
            pid_meta, state.get('pieces_by_id') or {},
            front_label=front, back_label=back,
            quantities=quantities, sizes=sizes or None,
            d_g=max(d_front, d_back), gate_nest=gate_nest, seed=seed)
        return pid_meta, chunk, gaps, holes, info

    try:
        pid_meta, chunk, _gaps, _holes, info = await run_in_threadpool(_construct)
    except (PrefixError, ValueError) as e:
        return {'ok': False, 'error': f'前缀构造失败: {e}'}

    size = int(info['size'])
    pieces_by_id = state.get('pieces_by_id') or {}
    ox, oy = chunk.offset
    members = []
    for m in chunk.members:
        meta = pid_meta[m['pid']]
        # 原始轮廓@组合片位 − offset（与 chunk.polygon 同一归一系；原始轮廓缺席时
        # 回退 erode 后轮廓 —— 与 build_prefix_plan 的 union 口径一致）
        orig = pieces_by_id.get(m['pid'], {}).get('polygon') or meta['polygon']
        placed = _transform_polygon(orig, m['rotation'], m['translation'])
        members.append({
            'pid': m['pid'],
            'size': meta['size'],
            'color': meta['color'],
            'tag': str(meta.get('label') or m['pid'].split('_')[0]),  # 前/后幅区分标注
            'polygon': [[round(x - ox, 2), round(y - oy, 2)] for x, y in placed],
        })

    extra = info.get('extra')
    return {
        'ok': True,
        'front': front,
        'back': back,
        'size': size,
        'fill_pct': round(float(chunk.fill_pct), 2),
        'bbox': {'width_mm': round(float(chunk.bbox['width_mm']), 1),
                 'height_mm': round(float(chunk.bbox['height_mm']), 1)},
        'n_members': chunk.n_members,
        # 2026-09-02 US-003 additive：选码搜索结果回显（旧前端零消费零变化；
        # PS_ 哨兵不变 —— extra 只带 label/size，组合片 pid 永不出前端契约）。
        'extra': ({'label': extra['label'], 'size': extra['size']}
                  if extra else None),
        'residual_mm': round(float(info['residual_mm']), 3),
        'gate_mm': gate_nest,
        'fallback': bool(info['fallback']),
        'members': members,
        'outline': [[round(x, 2), round(y, 2)] for x, y in chunk.polygon],
    }


@router.post('/export')
async def export(req: Request):
    """导出最优排料方案：前端 POST 最优 run 的最终帧 placed_items → 出 PNG / R12-DXF。

    payload = {fmt:'png'|'dxf'|'plt'|'plt-clean', sizes:[..], seed, gate_mm, width_mm,
               density, placed:[{id,rotation,translation},...], filename?, table?}
    filename 为上传母版名（用作导出文件名前缀，去 .dxf）；缺省回退「排料」。
    fmt='plt-clean'（2026-08-31 毛版，命名与裁片 layer1「毛版轮廓」同口径）：裁片仅最外层毛版轮廓 + 尺码*数量标注、
    带表格时唛架左右两端各一份同内容表格（详见 export_plt 模块注释）。
    返回文件字节流（Content-Disposition 附件下载，中文文件名走 RFC5987）。

    US-003（多会话）：``X-Session-Id`` → 该会话的 ``pieces_by_id``（A 的 placed 匹配
    A 的原始轮廓）；缺省 → default。sid 过期/超限/非法 → 401/429/400 结构化 JSON
    响应**非文件流**（会话解析先于一切导出逻辑，fail-fast）。
    """
    try:
        state = _resolve_session_state(req)
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)
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
        # 2026-08-28 版师两位小数 cm 口径：用布/门幅均 cm 两位（与前端 NestLabel、DXF/PLT
        # 标题同口径；此前 m 两位 + 门幅 int mm，int 截断在小数幅宽下会显示错值）。
        title = (f'M1787 直筒 | 码 {sizes_str} | 利用率 {pct:.2f}% | '
                 f'用布 {width_mm / 10:.2f} cm | 门幅 {gate_mm / 10:.2f} cm | seed {seed}')
        data = render_png(world, width_mm=width_mm, gate_mm=gate_mm, title=title)
        media, ext = 'image/png', 'png'
    elif fmt == 'dxf':
        title = f'M1787 util={pct:.2f}% L={width_mm / 10:.2f}cm gate={gate_mm / 10:.2f}cm seed={seed}'
        data = write_marker_dxf(world, width_mm=width_mm, gate_mm=gate_mm, title=title)
        media, ext = 'application/dxf', 'dxf'
    elif fmt in ('plt', 'plt-clean'):
        # US-033：PLT/HPGL 文本导出（LIKE 绘图仪 / WT V8.8 原生链路）；title 复用 DXF 同款
        # ASCII（格式：M1787 util=<pct>% L=<L>cm gate=<gate>cm seed=<seed>，两位小数），
        # 避免中文编码风险。
        # fmt='plt-clean'（2026-08-31 毛版变体，对齐生产参考件 PC-20250508NJIF_5028-
        # 1#_29223513.plt）：裁片只画最外层毛版轮廓 + 尺码*数量标注（净版线/内部线/
        # 刀口/布纹杆羽不画），带表格时唛架左端再画一份同内容表格（文件名加 _clean/
        # 毛版 后缀防与全量版混淆；前端格式下拉「PLT（毛版）」直传此值）。
        clean = fmt == 'plt-clean'
        title = f'M1787 util={pct:.2f}% L={width_mm / 10:.2f}cm gate={gate_mm / 10:.2f}cm seed={seed}'
        # 唛架信息表格（2026-08-30）：payload 可选 table 对象（前端导出弹窗 6 手输
        # 字段）→ 系统补全自动字段后随 PLT 输出（缺省不带表格，旧前端零变化）。
        info_table = None
        if payload.get('table') is not None:
            try:
                table_in = parse_table_payload(payload.get('table'))
            except TablePayloadError as e:
                return JSONResponse({'error': f'信息表格字段非法：{e}'},
                                    status_code=400)
            info_table = build_info_table(world, width_mm=width_mm, gate_mm=gate_mm,
                                          density=density, table_in=table_in)
        data = write_marker_plt(world, width_mm=width_mm, gate_mm=gate_mm, title=title,
                                info_table=info_table, clean=clean)
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
    # 毛版后缀（2026-08-31；当日由「净版」更名，与裁片毛版轮廓口径统一）：同一方案
    # 常先后导出全量/毛版两份，后缀防同名覆盖（ascii 侧沿用 _clean 与 fmt 值一致）
    suffix_ascii = '_clean' if fmt == 'plt-clean' else ''
    suffix_cn = '_毛版' if fmt == 'plt-clean' else ''
    fname_ascii = f'{prefix_ascii}_{sizes_str}_{pct:.2f}pct_seed{seed}{suffix_ascii}.{ext}'
    fname_cn = f'{prefix_cn}_码{sizes_str}_{pct:.2f}pct_seed{seed}{suffix_cn}.{ext}'
    cd = f"attachment; filename=\"{fname_ascii}\"; filename*=UTF-8''{quote(fname_cn)}"
    return Response(content=data, media_type=media,
                    headers={'Content-Disposition': cd})


# ------------------------------------------- POST /api/plt-table-preview 表格预览


@router.post('/api/plt-table-preview')
async def plt_table_preview(req: Request):
    """PLT 唛架信息表格 14 字段预览（导出弹窗只读展示，2026-08-31）。

    前端 ExportInfoModal 打开时 POST 最优 run 的几何子集，取回 14 行成品
    字符串按最终表格列序展示（8 自动只读 + 6 手输可编辑交错）——列序/格式
    权威在 ``plt_table._row_texts`` 单一真相源，前端零公式镜像（方案名称/
    套数/demand 多副本计数不在 TS 复刻）。

    payload = ``/export`` 几何子集 ``{gate_mm, width_mm, density, placed}``
    （前端 bestRun 同源；gate_mm 缺省回退 intermediate，与 /export 同口径）。
    响应 ``{rows: [{key, label, value, manual}]}`` —— manual 行 value = 默认
    值仅供参考（弹窗手输由前端本地草稿渲染，预览不消费）；绘图时间 = 本次
    请求时刻，最终 PLT 以导出时刻重算（分钟精度通常一致）。

    US-003（多会话）：``X-Session-Id`` → 该会话 pieces_by_id（与 /export 同源
    fail-fast）；sid 过期/超限/非法 → 401/429/400 结构化 JSON。
    """
    try:
        state = _resolve_session_state(req)
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)
    pieces_by_id = state.get('pieces_by_id') or {}

    payload = await req.json()
    placed = payload.get('placed') or []
    width_mm = float(payload.get('width_mm') or 0.0)
    gate_mm = float(payload.get('gate_mm') or 0.0) or (state.get('gate_mm') or 0.0)
    density = float(payload.get('density') or 0.0)

    if width_mm <= 0 or not placed:
        return JSONResponse({'error': '无可预览的方案（width=0 或无裁片）'},
                            status_code=400)

    world = placed_to_world(placed, pieces_by_id)
    if not world:
        return JSONResponse({'error': '预览失败：placed 的 pid 均未匹配到原始轮廓'},
                            status_code=400)

    # 手输用默认值（弹窗手输 = 前端本地草稿，预览端点不消费）；自动字段与
    # /export 完全同一代码路径（build_info_table → _row_texts）。
    info = build_info_table(world, width_mm=width_mm, gate_mm=gate_mm,
                            density=density, table_in=parse_table_payload({}))
    return {'rows': preview_rows(info)}
