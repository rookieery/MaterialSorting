"""工作台状态文件（.msn）保存/恢复：序列化 + POST /api/state-save、POST /api/state-restore
（prd 状态文件 US-001/US-002）。

状态文件 = 版师工作台**运行状态**的可传递快照（非导出产物）：后端出 doc 块（会话
``state['doc']`` 原样，含 5 层渲染字段 = 与 /export、edit-polish、求解同一真相源），
前端回传 form/quantities/quantities_base/run 四块，本模块聚合并 gzip 序列化。恢复端
（``parse_state_document`` 校验链 + 纯内存会话重建 + manifest 确定性重算）与本
保存端复用同一守恒校验函数 ``check_placed_conservation``。

schema v1（设计 §四，.docs/business/状态文件保存恢复_落地方案.md）：
  {schema_version, app, saved_at, doc, form, quantities, quantities_base?, run?}
  - run 仅 done 态入文件（body 无 run → 整块省略）；placed 同 pid 多副本 = 数组
    多条，绝不 pid 去重；mirror 按 omit-when-false（editStore 同口径）。
  - quantities_base = {label:整数} 整列设值基准（qtyStore baseValue，2026-09-12
    additive）：省键式 —— 只存 ≠1 的行，缺席 = 全 1 默认；不参与守恒/manifest
    （纯 UI 基准），无需 bump v1。
  - manifest 不入文件：恢复端用 build_pid_meta 确定性重算（无 RNG），文件只存
    单份几何。

分层：web 层兄弟模块，仅 import .solver（build_pid_meta）/.routes_views
（_resolve_session_state）/.parse_payload（_build_parse_payload）/.runtime
（_state_from_doc/_PIECES_STATE/_state_lock）/.sessions/.edit_hold，无反向依赖。
"""
from __future__ import annotations

import gzip
import json
import math
import re
import sys
import uuid
import zlib
from collections import Counter
from datetime import datetime
from urllib.parse import quote

from fastapi import File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from . import edit_hold
from .parse_payload import _build_parse_payload
from .routes_views import _resolve_session_state
from .runtime import _PIECES_STATE, _state_from_doc, _state_lock
from .sessions import SessionError, registry as session_registry
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
    'parse_state_document',
    'register_statefile_routes',
    'serialize_state',
    'state_restore',
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


def _form_gate_mm(form: dict, doc_gate: float) -> float:
    """恢复端 manifest 幅宽（mm）：``form.gate``（cm 字符串 ×10）优先，缺省/非法/
    非正回退 doc.gate_mm。

    与求解路径同口径（routes_ws：前端 ``gate_mm = parseGate(form)`` cm×10 覆盖
    intermediate 默认门幅；lib/params.ts parseGate 同式）—— 保存会话若改过幅宽再
    求解，doc.gate_mm（母版 commit 时快照）与实际求解幅宽已分歧，manifest 重算取
    form 侧才与 run.final 密度/PLT 导出幅宽一致（2026-09-11 E2E 冒烟实测：gate
    180cm 求解 + 175cm 母版 → 恢复 manifest 1750 导致导出幅宽 1750 ≠ 布局实际 1800）。
    """
    try:
        v = float(form.get('gate'))
    except (TypeError, ValueError):
        return float(doc_gate)
    return v * 10.0 if v > 0 else float(doc_gate)


# ---------------------------------------------------------------- 纯逻辑（构建/序列化）

def build_state_document(state: dict, form: dict, quantities, run,
                         quantities_base=None) -> dict:
    """聚合保存载荷 → 状态文件顶层 dict（doc 块取 state['doc'] 原样含 5 层）。

    - ``form`` / ``quantities``：前端回传原样嵌入（quantities 可为 None = 求解
      未带数量矩阵的旧语义，demand 全 1 —— 与 build_pid_meta 缺省口径一致）；
    - ``quantities_base``：整列设值基准 {label:整数}，None → 整块省略（省键式：
      前端只回传 ≠1 的行，缺席 = 全 1 默认 = 旧文件口径零迁移）；
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
    if quantities_base is not None:
        document['quantities_base'] = quantities_base
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


# ---------------------------------------------------------------- 恢复端校验链（US-002）

# provenance.kind 四值枚举（设计 §四：'solve'|'strategy_se'|'strategy_race'|'extreme'）。
# v1 内 run 块可省 provenance 键 = 缺省 'solve'（向后兼容手改文件）；config 形态
# 宽松纯展示不承重（策略族 {minutes} / 极限族 {time_total_s}，仅来源小字回显）。
_PROVENANCE_KINDS = frozenset({'solve', 'strategy_se', 'strategy_race', 'extreme'})
# doc.pieces[].label 形态 = label_for 产物 gNN（1-3 位数字）。既挡手改乱码，更保证
# _DocPieceView 的 parse 载荷复用走 assign_codes 母版码模式必中（label 即 g 码），
# parse 载荷 label 与 doc/manifest/quantities 键同源零漂移（4 位以上数字母版码正则
# 不识别 → 顺序重排赋号，会让预览 Tab label 与数量矩阵键错位，故 fail-fast）。
_G_LABEL_RE = re.compile(r'g\d{1,3}')


def _finite(x) -> bool:
    """数值形态判据：int/float（bool 除外）且有限（NaN/±Inf 拒收，防几何污染）。"""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _valid_base_map(v) -> bool:
    """quantities_base 形态判据：{label: 整数}（bool 除外，doc.pieces[].size 同款
    整数判据）。UI 基准值不承重（不参与守恒/manifest），但无后端消费方兜底 ——
    逐值 fail-fast 挡手改乱值，前端 hydrateFlat 另有 clampQty 防御纵深。"""
    return (isinstance(v, dict)
            and all(isinstance(x, int) and not isinstance(x, bool)
                    for x in v.values()))


def _validate_doc_block(doc) -> None:
    """doc 块逐片形态校验（设计 §五.4）：违者 StateFileError 400「状态文件损坏」。"""
    if not isinstance(doc, dict):
        raise StateFileError('状态文件损坏（缺少 doc 块）')
    gate = doc.get('gate_mm')
    if not _finite(gate) or gate <= 0:
        raise StateFileError('状态文件损坏（gate_mm 须为正数）')
    pieces = doc.get('pieces')
    if not isinstance(pieces, list) or not pieces:
        raise StateFileError('状态文件损坏（doc.pieces 不能为空）')
    seen: set[str] = set()
    for i, p in enumerate(pieces):
        if not isinstance(p, dict):
            raise StateFileError(f'状态文件损坏（pieces[{i}] 须为对象）')
        pid = p.get('pid')
        if not isinstance(pid, str) or not pid:
            raise StateFileError(f'状态文件损坏（pieces[{i}].pid 须为非空字符串）')
        if pid in seen:
            raise StateFileError(f'状态文件损坏（pieces[{i}].pid 重复：{pid}）')
        seen.add(pid)
        label = p.get('label')
        if not isinstance(label, str) or not _G_LABEL_RE.fullmatch(label):
            raise StateFileError(f'状态文件损坏（pieces[{i}].label 须为 gNN 码）')
        size = p.get('size')
        if not isinstance(size, int) or isinstance(size, bool):
            raise StateFileError(f'状态文件损坏（pieces[{i}].size 须为整数码号）')
        poly = p.get('polygon')
        if (not isinstance(poly, list) or len(poly) < 3
                or not all(isinstance(pt, (list, tuple)) and len(pt) == 2
                           and _finite(pt[0]) and _finite(pt[1]) for pt in poly)):
            raise StateFileError(
                f'状态文件损坏（pieces[{i}].polygon 须为 ≥3 个有限数值顶点）')
        bbox = p.get('bbox')
        if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4
                or not all(_finite(v) for v in bbox)):
            raise StateFileError(f'状态文件损坏（pieces[{i}].bbox 须为 4 个有限数值）')
        if not _finite(p.get('area_mm2')):
            raise StateFileError(f'状态文件损坏（pieces[{i}].area_mm2 须为有限数值）')


def _validate_run_block(run: dict, pieces, *, form: dict, quantities) -> None:
    """run 块校验：placed 逐条形态 → pid 全命中 doc → 守恒终检 → provenance 枚举。

    pid 全命中与守恒 unknown_pid 文案不同（前者「母版外」、后者码选过滤/退化石
    也算未排料），按故事口径分别给文案；守恒与保存端复用同一判定函数。
    """
    placed = run.get('placed')
    if not isinstance(placed, list) or not placed:
        raise StateFileError('状态文件损坏（run.placed 不能为空）')
    for i, item in enumerate(placed):
        if not isinstance(item, dict):
            raise StateFileError(f'状态文件损坏（run.placed[{i}] 须为对象）')
        if not isinstance(item.get('id'), str) or not item['id']:
            raise StateFileError(
                f'状态文件损坏（run.placed[{i}].id 须为非空字符串）')
        if not _finite(item.get('rotation')):
            raise StateFileError(f'状态文件损坏（run.placed[{i}].rotation 须为数值）')
        tr = item.get('translation')
        if (not isinstance(tr, (list, tuple)) or len(tr) != 2
                or not _finite(tr[0]) or not _finite(tr[1])):
            raise StateFileError(
                f'状态文件损坏（run.placed[{i}].translation 须为 [x,y] 数值对）')
        if 'mirror' in item and not isinstance(item['mirror'], bool):
            raise StateFileError(f'状态文件损坏（run.placed[{i}].mirror 须为布尔）')
    # pid 全命中 doc.pieces（镜像 edit-polish 语义：先查母版身份，再谈守恒）。
    pids = {p['pid'] for p in pieces}
    miss = [it['id'] for it in placed if it['id'] not in pids]
    if miss:
        raise StateFileError(
            f'状态文件内部不一致：placed 引用母版外裁片（pid {miss[0]!r} 不在 doc.pieces）')
    final = run.get('final')
    if final is not None and not isinstance(final, dict):
        raise StateFileError('状态文件损坏（run.final 须为对象）')
    provenance = run.get('provenance')
    if provenance is not None:
        if not isinstance(provenance, dict):
            raise StateFileError('状态文件损坏（run.provenance 须为对象）')
        kind = provenance.get('kind')
        if kind not in _PROVENANCE_KINDS:
            raise StateFileError(
                f'状态文件损坏（run.provenance.kind 非法：{kind!r}；'
                f'须为 solve/strategy_se/strategy_race/extreme 之一）')
    # 副本守恒终检（manifest 重算后 demand 口径；保存端同一函数 —— 手改文件让
    # placed ≠ demand 在此拦下，不让内部不一致布局进入恢复会话）。
    try:
        check_placed_conservation(placed, pieces, sizes=form.get('sizes'),
                                  per_type=form.get('per_type'),
                                  quantities=quantities)
    except StateConservationError as e:
        if e.kind == 'unknown_pid':
            # pid 在 doc 但不在重算 demand（码选过滤 / erode 退化石）—— 同属
            # 「引用未排料裁片」的内部不一致，文案沿用母版外口径 + detail。
            raise StateFileError(
                f'状态文件内部不一致：placed 引用母版外裁片（{e.detail}）')
        raise StateFileError(
            f'状态文件内部不一致：placed 副本数与数量矩阵不符（{e.detail}）')
    except (ValueError, TypeError) as e:
        raise StateFileError(f'状态文件损坏（form/quantities 形态非法：{e}）')


def parse_state_document(raw: bytes) -> dict:
    """状态文件字节 → 校验通过的顶层 document dict（恢复端校验链单一真相，US-002）。

    纯函数（无会话/无 I/O），handler 经 ``run_in_threadpool`` 调用防阻塞事件循环。
    全 fail-fast（``StateFileError`` 400/413，路由层转结构化 JSON）：

    1. gzip 魔数 ``1f 8b`` 嗅探（纯 JSON 也接受，开发期手改友好）；坏 gzip → 400；
    2. 解压后 > ``STATE_MAX_BYTES`` → 413（gzip 炸弹防线）；
    3. ``json.loads`` 容错（DecodeError/Unicode/RecursionError → 400「状态文件损坏」）；
    4. ``schema_version`` 缺失/非 int/过新 → 400（文案含双版本号；v1 内未知顶层
       键忽略、可选块缺席容忍 —— 新读老宽松，老读新明确报错）；
    5. form/quantities/quantities_base 块形态（doc/run 前置：守恒校验消费
       form/quantities 这两块；quantities_base 纯 UI 基准缺席容忍）；
    6. doc 块逐片形态（``_validate_doc_block``）；
    7. run 块（在场时：``_validate_run_block``）。

    返回 document 本体（doc_id 由 handler 铸新后原位改写；调用方接管所有权）。
    """
    if raw[:2] == b'\x1f\x8b':
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError, zlib.error):
            raise StateFileError('状态文件损坏（gzip 解压失败）')
    if len(raw) > STATE_MAX_BYTES:
        raise StateFileError(
            f'状态文件解压后超过上限 {STATE_MAX_BYTES // (1024 * 1024)}MB',
            status=413)
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError):
        raise StateFileError('状态文件损坏（JSON 解析失败）')
    if not isinstance(document, dict):
        raise StateFileError('状态文件损坏（顶层须为 JSON 对象）')

    v = document.get('schema_version')
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        raise StateFileError(
            f'状态文件损坏（schema_version 缺失或非法，本程序支持至'
            f' v{STATE_SCHEMA_VERSION}）')
    if v > STATE_SCHEMA_VERSION:
        raise StateFileError(
            f'状态文件版本过新（v{v}，本程序支持至 v{STATE_SCHEMA_VERSION}）')

    form = document.get('form')
    if not isinstance(form, dict):
        raise StateFileError('状态文件损坏（缺少 form 或类型错误）')
    quantities = document.get('quantities')
    if quantities is not None and not isinstance(quantities, dict):
        raise StateFileError('状态文件损坏（quantities 须为 {label:{sizeKey:N}} 对象）')
    if (quantities_base := document.get('quantities_base')) is not None \
            and not _valid_base_map(quantities_base):
        raise StateFileError('状态文件损坏（quantities_base 须为 {label:整数} 对象）')

    _validate_doc_block(document.get('doc'))
    if run := document.get('run'):
        if not isinstance(run, dict):
            raise StateFileError('状态文件损坏（run 须为对象）')
        _validate_run_block(run, document['doc']['pieces'],
                            form=form, quantities=quantities)
    return document


class _DocPieceView:
    """doc piece dict → collect_pieces_with_details 属性视图（parse 载荷复用适配器）。

    ``_build_parse_payload`` 消费 PieceOutline 属性（polygon_mm/5 层/size 等）并经
    ``assign_codes`` 赋 g 码 —— 恢复端没有 PieceOutline，用本视图以 doc piece dict
    喂同一函数。**block_name = 已存 label**（校验链保证 gNN 形态）→ ``assign_codes``
    走母版码复用模式必中且码内唯一（pid = {label}_{size} 唯一 → 码内 label 唯一），
    parse 载荷 label 与 doc/manifest/quantities 键同源零漂移；排序键
    （centroid/area/block_name/piece_index）仅决定码内展示顺序（与原上传预览可能
    不同序，展示级差异不承重）。
    """
    __slots__ = ('size', 'polygon_mm', 'area_mm2', 'net_polygon', 'internal_lines',
                 'notches', 'grain_line', 'block_name', 'piece_index', 'group_key')

    def __init__(self, p: dict):
        self.size = p['size']
        self.polygon_mm = p['polygon']
        self.area_mm2 = p['area_mm2']
        self.net_polygon = p.get('net_polygon') or []
        self.internal_lines = p.get('internal_lines') or []
        self.notches = p.get('notches') or []
        self.grain_line = p.get('grain_line')
        self.block_name = p['label']
        self.piece_index = 0
        self.group_key = p['label']


# ---------------------------------------------------------------- POST /api/state-save

async def state_save(request: Request):
    """POST /api/state-save：当前会话工作台状态 → gzip JSON 附件（.msn 下载）。

    请求 ``{form, quantities, quantities_base?, run?}``（前端 buildSavePayload，
    US-003）：form = FormState 全量原样入文件；quantities_base = 整列设值基准
    {label:整数}（省键式，body 无 → 文件无键）；run 仅 done 态（body 无 run →
    文件无 run 键）。响应 200 附件（Content-Disposition 中文/ASCII 双写，/export
    同法），文件名 ``<source 去 .dxf>_状态_<yyyymmdd-HHMMSS>.msn``。

    错误契约（全部结构化 JSON，非文件流）：
    - sid 过期/墓碑 → 401 ``{code:'session_expired'}``、非法 → 400（SessionError
      统一映射，_resolve_session_state 同 routes_views 读路由口径）；
    - 会话空（无 doc/pieces，未 commit）→ 422；
    - body 非 JSON / form 缺失 / quantities·quantities_base·run 形态非法 /
      run.placed 条目形态非法 → 400；
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
    quantities_base = payload.get('quantities_base')
    if quantities_base is not None and not _valid_base_map(quantities_base):
        return JSONResponse(
            {'error': 'quantities_base 须为 {label:整数} 对象'}, status_code=400)
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

    document = build_state_document(state, form, quantities, run, quantities_base)
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


# ---------------------------------------------------------------- POST /api/state-restore

async def state_restore(request: Request, file: UploadFile = File(...)):
    """POST /api/state-restore：上传 .msn → 校验 → 纯内存重建当前会话 + manifest 重算。

    multipart 收文件（扩展名 .msn/.json；纯 JSON 也接受）。流程（设计 §五.6/§七）：
    1. 扩展名/大小（raw > 20MB → 413）→ ``run_in_threadpool(parse_state_document)``
       （解压+json+校验链 CPU 密集，不阻塞事件循环；解析在会话解析**之前** —— 坏
       文件不新建会话名额）；
    2. ``registry.resolve(sid, create=True)``（commit 先例：恢复写入**当前 sid**，
       等价「再上传母版 commit」覆盖语义、不占 ``MS_SESSION_MAX`` 名额；过期 401 /
       超限 429 / 非法 400 结构化 JSON）；
    3. 纯内存重建 state：doc_id 铸新 uuid、源文件名保留 doc.source —— sid 会话
       ``st.state = 新 dict``、default 会话走 runtime 等价原子重绑（锁内 clear+update，
       ``_reload_pieces_state`` 同法但不读盘）；**不镜像写 paths.INTERMEDIATE、不落盘
       uploads**（他人文件不污染本机事实源，设计 §一.7）；
    4. ``build_pid_meta(doc.pieces, sizes, per_type, quantities)`` 确定性重算 manifest
       （params 缺省全 0 = web 口径；含 raw_polygon/d_mm 物理毛版，routes_ws.on_manifest
       / strategy result 同形）；``gate_mm`` 取 ``form.gate``（cm×10，与求解路径
       parseGate/前端覆盖同口径，缺省回退 doc.gate_mm —— 见 ``_form_gate_mm``）；
       ``_build_parse_payload`` 经 ``_DocPieceView`` 组 parse
       载荷（PreviewPage 零解析改动）；
    5. 成功 ``edit_hold.refresh(sid)``（编辑钉住与 /api/edit-polish 同口径；default
       豁免不进钉住表）。

    响应 ``{doc_id, filename, parse, manifest, final, placed, run?, form,
    quantities, quantities_base}``：final/placed = run 块摘出（无 run → None 纯
    配置档）；``run`` 块 additive 整块透传（seed/provenance 供前端 US-004 恢复编排
    写回来源，无 run 时为 None）；``quantities_base`` = 整列设值基准回传（省键式
    文件缺席 → None → 前端 no-op 保持默认 1）。错误契约：校验链失败 → 400/413
    ``{error}``（StateFileError 全结构化 JSON，不炸 500）。
    """
    fname = file.filename or ''
    if not (fname.lower().endswith(STATE_EXTENSION) or fname.lower().endswith('.json')):
        return JSONResponse({'error': '仅支持 .msn / .json 状态文件'}, status_code=400)
    data = await file.read()
    if len(data) > STATE_MAX_BYTES:
        return JSONResponse(
            {'error': f'文件大小超过上限 {STATE_MAX_BYTES // (1024 * 1024)}MB'},
            status_code=413)

    # 解析先行（threadpool）：坏文件不触发会话解析/名额。
    try:
        document = await run_in_threadpool(parse_state_document, data)
    except StateFileError as e:
        return JSONResponse({'error': e.message}, status_code=e.status)

    sid = (request.headers.get('x-session-id') or '').strip() or None
    try:
        st = session_registry.resolve(sid, create=True)
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)

    doc = document['doc']
    doc_id = uuid.uuid4().hex      # 每次恢复铸新文档身份（链式传递无原文件依赖）
    doc['doc_id'] = doc_id
    state = _state_from_doc(doc)
    if sid:
        st.state = state           # 覆盖语义 = 再上传母版 commit（server.py 先例）
    else:
        # default 会话：st.state 即 runtime._PIECES_STATE 同一 dict —— 走 runtime
        # 等价原子重绑（锁内 clear+update；不读盘不写盘 = 与 commit 双写有意分歧）。
        with _state_lock:
            _PIECES_STATE.clear()
            _PIECES_STATE.update(state)
    st.doc_id = doc_id

    form = document['form']
    quantities = document.get('quantities')
    quantities_base = document.get('quantities_base')
    run = document.get('run') or None

    # manifest 确定性重算（与保存会话同 form → 与原解 manifest 逐字段一致；纯函数
    # 无 RNG，策略 result 端点同一先例）。on_manifest 同形含 raw_polygon/d_mm。
    pid_meta, total_area, n_eroded = build_pid_meta(
        doc['pieces'], sizes=form.get('sizes'), per_type=form.get('per_type'),
        quantities=quantities)
    manifest = {
        'gate_mm': _form_gate_mm(form, state['gate_mm']),
        'total_area_mm2': total_area,
        'n_eroded': n_eroded,
        'pieces': [
            {'id': pid, 'size': meta['size'], 'color': meta['color'],
             'area_mm2': meta['area_mm2'], 'polygon': meta['polygon'],
             'raw_polygon': meta.get('raw_polygon') or meta['polygon'],
             'd_mm': meta.get('d_mm', 0.0),
             'label': meta.get('label'), 'demand': meta.get('demand', 1),
             'net_polygon': meta.get('net_polygon', []),
             'internal_lines': meta.get('internal_lines', []),
             'notches': meta.get('notches', []),
             'grain_line': meta.get('grain_line')}
            for pid, meta in pid_meta.items()
        ],
    }
    filename = doc.get('source') or fname
    parse = _build_parse_payload(doc_id, filename,
                                 [_DocPieceView(p) for p in doc['pieces']])

    if sid:   # default 豁免一切过期，不进钉住表（/api/edit-hold 同口径）
        edit_hold.refresh(sid, session_registry.clock())
    return {
        'doc_id': doc_id,
        'filename': filename,
        'parse': parse,
        'manifest': manifest,
        'final': (run or {}).get('final'),
        'placed': (run or {}).get('placed'),
        'run': run,
        'quantities_base': quantities_base,
        'form': form,
        'quantities': quantities,
    }


def register_statefile_routes(app) -> None:
    """把状态文件路由挂到 FastAPI app（server.py 文件尾调用一次；strategy 同模式）。"""
    app.post('/api/state-save')(state_save)
    app.post('/api/state-restore')(state_restore)


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
    """``python -m materialsorting.web.statefile``：合成夹具 save/restore 全链自检。

    纯函数链（不经 HTTP/会话）：_state_from_doc 构建 state → build_state_document
    （带 run / 不带 run 双路）→ serialize_state（gzip 魔数）→ gunzip+json.loads
    逐字段对拍（doc 含 5 层）→ 守恒校验通过/篡改 quantities 必败两路 → US-002
    恢复链：parse_state_document（gzip/纯 JSON 双嗅探 + 校验链必败四路）→
    _DocPieceView 组 parse 载荷（label 同源）+ build_pid_meta manifest 重算。
    """
    from .parse_payload import _build_parse_payload
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
    quantities_base = {'g01': 2}   # g01 整列设值 2 场景（g02 未设 → 省键）
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

    def expect_error(name: str, fn, *, want: str, status: int = 400) -> None:
        try:
            fn()
        except StateFileError as e:
            check(name, want in e.message and e.status == status)
        else:
            check(name, False)

    with_run = build_state_document(state, form, quantities, run, quantities_base)
    check('顶层键齐（schema_version=1/app/saved_at/doc/form/quantities/'
          'quantities_base/run）',
          set(with_run) == {'schema_version', 'app', 'saved_at', 'doc', 'form',
                            'quantities', 'quantities_base', 'run'}
          and with_run['schema_version'] == STATE_SCHEMA_VERSION)
    check('body 无 run → 文件无 run 键（纯配置档）',
          'run' not in build_state_document(state, form, quantities, None))
    check('quantities_base None/缺席 → 省键（省键式，全 1 默认口径）',
          'quantities_base' not in build_state_document(
              state, form, quantities, None, None)
          and 'quantities_base' not in build_state_document(
              state, form, quantities, None))

    data = serialize_state(with_run)
    check('serialize 为 gzip（魔数 1f 8b）', data[:2] == b'\x1f\x8b')
    parsed = json.loads(gzip.decompress(data))
    check('往返逐字段一致（doc 5 层原样 / form / quantities / quantities_base / '
          'run.placed 原序）',
          parsed['doc'] == doc and parsed['form'] == form
          and parsed['quantities'] == quantities
          and parsed['quantities_base'] == quantities_base
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

    # ------------------------------------------------ US-002 恢复链（parse/重算）
    restored = parse_state_document(data)
    check('parse_state_document：gzip 文件解析 → 与原件逐字段一致',
          {k: restored[k] for k in ('doc', 'form', 'quantities',
                                    'quantities_base', 'run')}
          == {k: parsed[k] for k in ('doc', 'form', 'quantities',
                                     'quantities_base', 'run')})
    plain = json.dumps(with_run, ensure_ascii=False).encode('utf-8')
    check('parse_state_document：纯 JSON（无 gzip）同通过',
          parse_state_document(plain)['run']['placed'] == placed)
    check('parse_state_document：无 run 纯配置档同通过',
          'run' not in parse_state_document(
              serialize_state(build_state_document(state, form, quantities, None))))
    expect_error('恢复校验：坏 gzip → 400 状态文件损坏',
                 lambda: parse_state_document(b'\x1f\x8b' + b'garbage!'),
                 want='状态文件损坏')
    expect_error('恢复校验：坏 JSON → 400 状态文件损坏',
                 lambda: parse_state_document(b'not-json'), want='状态文件损坏')

    def _bump_version(v):
        d = json.loads(gzip.decompress(data))
        d['schema_version'] = v
        return gzip.compress(json.dumps(d, ensure_ascii=False).encode('utf-8'))

    expect_error('恢复校验：版本过新 v99 → 400 文案含双版本号',
                 lambda: parse_state_document(_bump_version(99)),
                 want='v99，本程序支持至 v1')

    def _tamper(fn):
        d = json.loads(gzip.decompress(data))
        fn(d)
        return gzip.compress(json.dumps(d, ensure_ascii=False).encode('utf-8'))

    expect_error('恢复校验：placed 引用母版外 pid → 400 内部不一致',
                 lambda: parse_state_document(
                     _tamper(lambda d: d['run']['placed'][2].__setitem__('id', 'zz_99'))),
                 want='placed 引用母版外裁片')
    expect_error('恢复校验：副本数 ≠ demand → 400 内部不一致',
                 lambda: parse_state_document(
                     _tamper(lambda d: d['quantities']['g01'].__setitem__('30', 5))),
                 want='副本数与数量矩阵不符')
    expect_error('恢复校验：provenance.kind 非法 → 400',
                 lambda: parse_state_document(_tamper(
                     lambda d: d['run'].__setitem__(
                         'provenance', {'kind': 'magic'}))),
                 want='provenance.kind 非法')
    expect_error('恢复校验：quantities_base 值非整数 → 400',
                 lambda: parse_state_document(_tamper(
                     lambda d: d.__setitem__('quantities_base', {'g01': 'x'}))),
                 want='quantities_base')

    parse_payload = _build_parse_payload(
        'newdoc0001', doc['source'], [_DocPieceView(p) for p in doc['pieces']])
    labels = [pc['label'] for s in parse_payload['sizes'] for pc in s['pieces']]
    check('恢复 parse 载荷：_DocPieceView 复用赋号（label 与 doc 同源 + 5 层透传）',
          sorted(labels) == ['g01', 'g02']
          and parse_payload['sizes'][0]['pieces'][0]['net_polygon']
          == pieces[0]['net_polygon']
          and parse_payload['sizes'][0]['pieces'][0]['grain_line']
          == pieces[0]['grain_line'])
    pid_meta, total_area, n_eroded = build_pid_meta(
        doc['pieces'], sizes=form['sizes'], per_type=form['per_type'],
        quantities=quantities)
    check('manifest 重算：demand（g01×2/g02×1）+ total_area 含 demand 乘数 + 无腐蚀',
          pid_meta['g01_30']['demand'] == 2 and pid_meta['g02_30']['demand'] == 1
          and total_area == 2 * 200 * 150 + 1 * 180 * 120 and n_eroded == 0)

    n_pass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f'[statefile] {"PASS" if ok else "FAIL"}  {name}')
    print(f'[statefile] 自检 {n_pass}/{len(results)} PASS')
    return 0 if n_pass == len(results) else 1


if __name__ == '__main__':
    sys.exit(_smoke())
