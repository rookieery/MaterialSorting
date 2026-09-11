"""工作台状态文件（.msn）保存：序列化模块 + POST /api/state-save（prd 状态文件 US-001）。

状态文件 = 版师工作台**运行状态**的可传递快照（非导出产物）：后端出 doc 块（会话
``state['doc']`` 原样，含 5 层渲染字段 = 与 /export、edit-polish、求解同一真相源），
前端回传 form/quantities/run 三块，本模块聚合并 gzip 序列化。恢复端（/api/state-restore
+ 校验链，US-002）与本保存端复用同一守恒校验函数 ``check_placed_conservation``。

schema v1（设计 §四，.docs/business/状态文件保存恢复_落地方案.md）：
  {schema_version, app, saved_at, doc, form, quantities, run?}
  - run 仅 done 态入文件（body 无 run → 整块省略）；placed 同 pid 多副本 = 数组
    多条，绝不 pid 去重；mirror 按 omit-when-false（editStore 同口径）。
  - manifest 不入文件：恢复端用 build_pid_meta 确定性重算（无 RNG），文件只存
    单份几何。

分层：web 层兄弟模块，仅 import .solver（build_pid_meta）/.routes_views
（_resolve_session_state）/.sessions（SessionError），无反向依赖。
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from datetime import datetime
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from .routes_views import _resolve_session_state
from .sessions import SessionError
from .solver import build_pid_meta

__all__ = [
    'STATE_EXTENSION',
    'STATE_MAX_BYTES',
    'STATE_SCHEMA_VERSION',
    'StateConservationError',
    'StateFileError',
    'build_state_document',
    'check_placed_conservation',
    'expected_demand_map',
    'register_statefile_routes',
    'serialize_state',
    'state_save',
]

# schema 版本（恢复端版本门：缺失/非 int/大于本值 → 400「状态文件版本过新」，US-002）。
STATE_SCHEMA_VERSION = 1
# 解压后大小上限（对齐 server.UPLOAD_MAX_BYTES 20MB；保存端生成恒小于此，恢复端核）。
STATE_MAX_BYTES = 20 * 1024 * 1024
# 状态文件扩展名（仅识别/关联用；恢复端也接受 .json，US-002）。
STATE_EXTENSION = '.msn'

# 保存期守恒失败文案（设计 §五.5 定稿：A 当场得到明确报错，不让坏文件流出）。
_CONSERVATION_SAVE_MESSAGE = (
    '数量矩阵/尺码选择与当前结果不一致，请先重新求解或改回数量再保存')


class StateFileError(Exception):
    """状态文件/保存载荷校验失败（路由层转结构化 JSON；US-002 校验链复用）。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class StateConservationError(StateFileError):
    """placed 副本守恒失败：kind = 'unknown_pid'（引用母版外裁片）或
    'count_mismatch'（Counter(placed) ≠ demand）；detail = 人类可读差异
    （保存端统一 400 指路文案、恢复端按 kind 分别文案 —— 两端复用同一判定）。"""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


# ---------------------------------------------------------------- 纯逻辑（构建/序列化）

def build_state_document(state: dict, form: dict, quantities, run) -> dict:
    """聚合保存载荷 → 状态文件顶层 dict（doc 块取 state['doc'] 原样含 5 层）。

    - ``form`` / ``quantities``：前端回传原样嵌入（quantities 可为 None = 求解
      未带数量矩阵的旧语义，demand 全 1 —— 与 build_pid_meta 缺省口径一致）；
    - ``run``：None/空 → 整块省略（纯配置档：端点容忍，UI 经 lastFrame 门槛
      不可达 —— 契约注记见 agent-api-reference）。
    """
    document = {
        'schema_version': STATE_SCHEMA_VERSION,
        'app': 'materialsorting',
        'saved_at': datetime.now().isoformat(timespec='seconds'),
        'doc': state['doc'],
        'form': form,
        'quantities': quantities,
    }
    if run:
        document['run'] = run
    return document


def serialize_state(document: dict) -> bytes:
    """json.dumps(ensure_ascii=False) → utf-8 → gzip（恒开；恢复端按魔数嗅探）。"""
    raw = json.dumps(document, ensure_ascii=False).encode('utf-8')
    return gzip.compress(raw)


# ---------------------------------------------------------------- 守恒校验（保存/恢复共用）

def expected_demand_map(pieces, *, sizes=None, per_type=None, quantities=None) -> dict:
    """demand 映射 {pid: N}（守恒校验单一真相）—— ``build_pid_meta`` 同口径：

    sizes 过滤（int 集合命中）→ quantities 按 (label, str(size)) 查 N（0=跳过、
    quantities/label 缺席 → 1）→ erode 后 <3 顶点跳过（与求解/manifest 重算完全
    同一流水线，退化石片天然两侧一致）。
    """
    pid_meta, _, _ = build_pid_meta(pieces, sizes=sizes, per_type=per_type,
                                    quantities=quantities)
    return {pid: meta['demand'] for pid, meta in pid_meta.items()}


def check_placed_conservation(placed, pieces, *, sizes=None, per_type=None,
                              quantities=None) -> None:
    """placed 副本守恒终检（保存端 / 恢复端复用同一函数，设计 §五.5/§五.4）。

    - placed 各条 ``id`` 须全部命中 demand 映射（= 会话/文件 pieces 经
      build_pid_meta 的 pid 集）：违者 unknown_pid；
    - ``Counter(item['id'])`` 须逐 pid 等于 demand：违者 count_mismatch。

    调用方保证 placed 已过形态校验（逐条 dict 且 'id' 为非空 str）。sizes/
    per_type/quantities 形态非法时 build_pid_meta 抛 ValueError/TypeError，由
    调用方转 400（保存端）/「状态文件损坏」（恢复端）。
    """
    demand = expected_demand_map(pieces, sizes=sizes, per_type=per_type,
                                 quantities=quantities)
    got = Counter(item['id'] for item in placed)
    unknown = sorted(pid for pid in got if pid not in demand)
    if unknown:
        raise StateConservationError(
            'unknown_pid', f'placed 引用母版外裁片 pid: {unknown[:5]}')
    if got != demand:
        diffs = [
            f'{pid}: placed={got.get(pid, 0)} demand={demand.get(pid, 0)}'
            for pid in sorted(set(got) | set(demand))
            if got.get(pid, 0) != demand.get(pid, 0)
        ]
        raise StateConservationError('count_mismatch', '; '.join(diffs[:5]))


# ---------------------------------------------------------------- POST /api/state-save

async def state_save(request: Request):
    """POST /api/state-save：当前会话工作台状态 → gzip JSON 附件（.msn 下载）。

    请求 ``{form, quantities, run?}``（前端 buildSavePayload，US-003）：form =
    FormState 全量原样入文件；run 仅 done 态（body 无 run → 文件无 run 键）。
    响应 200 附件（Content-Disposition 中文/ASCII 双写，/export 同法），文件名
    ``<source 去 .dxf>_状态_<yyyymmdd-HHMMSS>.msn``。

    错误契约（全部结构化 JSON，非文件流）：
    - sid 过期/墓碑 → 401 ``{code:'session_expired'}``、非法 → 400（SessionError
      统一映射，_resolve_session_state 同 routes_views 读路由口径）；
    - 会话空（无 doc/pieces，未 commit）→ 422；
    - body 非 JSON / form 缺失 / quantities·run 形态非法 / run.placed 条目形态
      非法 → 400；
    - 保存期守恒校验（run 在场：placed pid 全命中会话 pieces + Counter ==
      demand(form.sizes × quantities)，改数量/码选未重解 → 400 指路文案）。
    """
    try:
        state = _resolve_session_state(request)
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)

    doc = state.get('doc') or {}
    pieces = state.get('pieces') or []
    if not doc or not pieces:
        return JSONResponse(
            {'error': '排料数据为空（请先上传解析母版并 commit）'}, status_code=422)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({'error': '请求体须为 JSON'}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({'error': '请求体须为 JSON 对象'}, status_code=400)

    form = payload.get('form')
    if not isinstance(form, dict):
        return JSONResponse({'error': '缺少 form 或类型错误'}, status_code=400)
    quantities = payload.get('quantities')
    if quantities is not None and not isinstance(quantities, dict):
        return JSONResponse(
            {'error': 'quantities 须为 {label:{sizeKey:N}} 对象'}, status_code=400)
    run = payload.get('run')
    if run is not None and not isinstance(run, dict):
        return JSONResponse({'error': 'run 须为对象'}, status_code=400)

    if run:
        placed = run.get('placed')
        if not isinstance(placed, list) or not placed:
            return JSONResponse({'error': 'run.placed 不能为空'}, status_code=400)
        for i, item in enumerate(placed):
            if (not isinstance(item, dict)
                    or not isinstance(item.get('id'), str) or not item['id']):
                return JSONResponse(
                    {'error': f'run.placed[{i}] 形态非法'
                              f'（需 {{id,rotation,translation}}）'}, status_code=400)
        # 保存期守恒 fail-fast（与恢复期终检同一函数）：防「改数量未重解」产出
        # 他人无法恢复的内部不一致文件。形态非法（sizes 不可 int 化等）同 400。
        try:
            check_placed_conservation(
                placed, pieces, sizes=form.get('sizes'),
                per_type=form.get('per_type'), quantities=quantities)
        except StateConservationError:
            return JSONResponse({'error': _CONSERVATION_SAVE_MESSAGE},
                                status_code=400)
        except (ValueError, TypeError):
            return JSONResponse(
                {'error': 'form.sizes/per_type/quantities 形态非法，无法核对数量守恒'},
                status_code=400)

    document = build_state_document(state, form, quantities, run)
    data = serialize_state(document)

    # 文件名前缀取 doc.source（母版原上传名，commit 时入 intermediate），去 .dxf
    # 扩展名；ASCII fallback 含中文时回退 'nesting'（/export 同法，防 fallback 名
    # 出现未编码中文）。
    source = doc.get('source') or ''
    stem = source[:-4] if source.lower().endswith('.dxf') else source
    prefix_cn = stem or '排料'
    prefix_ascii = stem if stem and stem.isascii() else 'nesting'
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    fname_cn = f'{prefix_cn}_状态_{ts}{STATE_EXTENSION}'
    fname_ascii = f'{prefix_ascii}_state_{ts}{STATE_EXTENSION}'
    cd = f"attachment; filename=\"{fname_ascii}\"; filename*=UTF-8''{quote(fname_cn)}"
    return Response(content=data, media_type='application/gzip',
                    headers={'Content-Disposition': cd})


def register_statefile_routes(app) -> None:
    """把状态文件路由挂到 FastAPI app（server.py 文件尾调用一次；strategy 同模式）。"""
    app.post('/api/state-save')(state_save)


# ---------------------------------------------------------------- __main__ 自检

def _smoke_piece(pid, w, h):
    """合成 5 层全量裁片（__main__ 自检夹具，schema v2 最小字段面）。"""
    return {
        'pid': pid, 'label': pid.split('_')[0], 'size': 30,
        'polygon': [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]],
        'bbox': [0.0, 0.0, float(w), float(h)], 'area_mm2': float(w * h),
        'n_verts': 4, 'allowed_angles': [0, 180],
        'net_polygon': [[1.0, 1.0], [float(w) - 1, 1.0], [float(w) - 1, float(h) - 1]],
        'internal_lines': [[[0.0, float(h) / 2], [float(w), float(h) / 2]]],
        'notches': [[0.0, float(h) / 2, -1.0, 0.0]],
        'grain_line': [float(w) / 2, 0.0, float(w) / 2, float(h)],
    }


def _smoke() -> int:
    """``python -m materialsorting.web.statefile``：合成夹具 build→serialize→parse 往返自检。

    纯函数链（不经 HTTP/会话）：_state_from_doc 构建 state → build_state_document
    （带 run / 不带 run 双路）→ serialize_state（gzip 魔数）→ gunzip+json.loads
    逐字段对拍（doc 含 5 层）→ 守恒校验通过/篡改 quantities 必败两路。
    """
    from .runtime import _state_from_doc

    pieces = [_smoke_piece('g01_30', 200, 150), _smoke_piece('g02_30', 180, 120)]
    doc = {'doc_id': 'smoke0001', 'source': '5336冒烟母版.dxf', 'gate_mm': 1750.0,
           'n_pieces': len(pieces), 'total_area_mm2': 51600.0, 'pieces': pieces,
           'label_representatives': {}}
    state = _state_from_doc(doc)
    form = {'sizes': [30], 'gate': '175.00', 'time': '120', 'seed': '0',
            'multi_seed': False, 'seed_count': '3', 'per_type': {},
            'band_enabled': False, 'band_label': '', 'prefix_enabled': False,
            'prefix_front': '', 'prefix_back': ''}
    quantities = {'g01': {'30': 2}, 'g02': {'30': 1}}
    placed = [
        {'id': 'g01_30', 'rotation': 0.0, 'translation': [0.0, 0.0]},
        {'id': 'g01_30', 'rotation': 180.0, 'translation': [500.0, 10.0]},
        {'id': 'g02_30', 'rotation': 0.0, 'translation': [260.0, 0.0]},
    ]
    run = {'seed': 0, 'final': {'density': 0.84, 'density_sparrow': 0.82,
                                'width_mm': 7523.0, 'elapsed': 121.4,
                                'n_frames': 87, 'n_eroded': 0}, 'placed': placed}

    results: list[tuple[str, bool]] = []

    def check(name: str, cond: bool) -> None:
        results.append((name, bool(cond)))

    with_run = build_state_document(state, form, quantities, run)
    check('顶层键齐（schema_version=1/app/saved_at/doc/form/quantities/run）',
          set(with_run) == {'schema_version', 'app', 'saved_at', 'doc', 'form',
                            'quantities', 'run'}
          and with_run['schema_version'] == STATE_SCHEMA_VERSION)
    check('body 无 run → 文件无 run 键（纯配置档）',
          'run' not in build_state_document(state, form, quantities, None))

    data = serialize_state(with_run)
    check('serialize 为 gzip（魔数 1f 8b）', data[:2] == b'\x1f\x8b')
    parsed = json.loads(gzip.decompress(data))
    check('往返逐字段一致（doc 5 层原样 / form / quantities / run.placed 原序）',
          parsed['doc'] == doc and parsed['form'] == form
          and parsed['quantities'] == quantities
          and parsed['run']['placed'] == placed)

    try:
        check_placed_conservation(placed, pieces, sizes=form['sizes'],
                                  per_type=form['per_type'], quantities=quantities)
        check('守恒校验：placed 与 demand（g01×2 + g02×1）一致 → 通过', True)
    except StateConservationError:
        check('守恒校验：placed 与 demand（g01×2 + g02×1）一致 → 通过', False)
    try:
        check_placed_conservation(
            placed, pieces, sizes=form['sizes'], per_type=form['per_type'],
            quantities={'g01': {'30': 3}, 'g02': {'30': 1}})
        check('守恒校验：篡改 quantities（g01 demand 3≠2）→ count_mismatch 必败',
              False)
    except StateConservationError as e:
        check('守恒校验：篡改 quantities（g01 demand 3≠2）→ count_mismatch 必败',
              e.kind == 'count_mismatch')
    try:
        check_placed_conservation(
            [dict(placed[0], id='zz_99')], pieces, sizes=form['sizes'],
            per_type=form['per_type'], quantities=quantities)
        check('守恒校验：placed 引用母版外 pid → unknown_pid 必败', False)
    except StateConservationError as e:
        check('守恒校验：placed 引用母版外 pid → unknown_pid 必败',
              e.kind == 'unknown_pid')

    n_pass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f'[statefile] {"PASS" if ok else "FAIL"}  {name}')
    print(f'[statefile] 自检 {n_pass}/{len(results)} PASS')
    return 0 if n_pass == len(results) else 1


if __name__ == '__main__':
    sys.exit(_smoke())
