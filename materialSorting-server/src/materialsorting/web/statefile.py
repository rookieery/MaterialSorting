"""工作台状态文件（.msn）保存/恢复：序列化 + POST /api/state-save、POST /api/state-restore
（prd 状态文件 US-001/US-002）。

状态文件 = 版师工作台**运行状态**的可传递快照（非导出产物）：后端出 doc 块（会话
``state['doc']`` 原样，含 5 层渲染字段 = 与 /export、edit-polish、求解同一真相源），
前端回传 form/quantities/quantities_base/run 四块，本模块聚合并 gzip 序列化。恢复端
（``parse_state_document`` 校验链 + 纯内存会话重建 + manifest 确定性重算）与本
保存端复用同一守恒校验函数 ``check_placed_conservation``。

schema v1（设计 §四，.docs/business/状态文件保存恢复_落地方案.md）：
  {schema_version, app, saved_at, doc, form, quantities, quantities_base?, run?,
   pending_strategy_result?}
  - run 仅 done 态入文件（body 无 run → 整块省略）；placed 同 pid 多副本 = 数组
    多条，绝不 pid 去重；mirror 按 omit-when-false（editStore 同口径）；
    run.stale = 展示级降级标记（2026-09-14 additive 省键式，checkpoint 对守恒
    失败的背景 run 打标）：true → 恢复端跳过 run 守恒终检（逐条形态 + pid 全
    命中保留）—— pending 在场时 run 只是弹窗背景（确认即被 pending 置换、取消
    保留旧布局），与活界面「背景无条件显示旧 run」同口径；.msn 保存端不产此键
    （守恒失败仍 400 指路文案），无需 bump v1。
  - quantities_base = {label:整数} 整列设值基准（qtyStore baseValue，2026-09-12
    additive）：省键式 —— 只存 ≠1 的行，缺席 = 全 1 默认；不参与守恒/manifest
    （纯 UI 基准），无需 bump v1。
  - pending_strategy_result = 待确认的策略/极限 done 结果槽（2026-09-13 additive，
    省键式）：{mode:'se'|'race'|'extreme', best:{seed, frame_index, elapsed,
    density, density_sparrow, width_mm, placed_items}, summary}—— 仅 done 态入槽
    （运行中被 alive hook 钉住不过期、stopped 是人为操作，均不入案）；manifest/
    run_dir 不入档（恢复端 rebuild 已确定性重算 manifest 随响应回传，单份几何；
    run_dir 前端不展示）。守恒与 run 块同一函数/文案；无需 bump v1。
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
from .download_name import sanitize_download_name
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
    'rebuild_session_from_document',
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
                         quantities_base=None,
                         pending_strategy_result=None) -> dict:
    """聚合保存载荷 → 状态文件顶层 dict（doc 块取 state['doc'] 原样含 5 层）。

    - ``form`` / ``quantities``：前端回传原样嵌入（quantities 可为 None = 求解
      未带数量矩阵的旧语义，demand 全 1 —— 与 build_pid_meta 缺省口径一致）；
    - ``quantities_base``：整列设值基准 {label:整数}，None → 整块省略（省键式：
      前端只回传 ≠1 的行，缺席 = 全 1 默认 = 旧文件口径零迁移）；
    - ``run``：None/空 → 整块省略（纯配置档：端点容忍，UI 经 lastFrame 门槛
      不可达 —— 契约注记见 agent-api-reference）；
    - ``pending_strategy_result``：待确认的策略/极限 done 结果槽，None/空 →
      整块省略（省键式 additive：无 pending 的文件逐字节不变 = 旧口径零迁移）。
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
    if pending_strategy_result:
        document['pending_strategy_result'] = pending_strategy_result
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
# pending_strategy_result.mode 三值枚举（槽路由键：恢复端按 mode 分发到 strategy/
# extreme 对应族 store，US-002）。槽内无 state 字段 —— 恒 done（运行中被 alive
# hook 钉住不过期、stopped 是人为操作，两态均不入案，用户定案 2026-09-13）。
_PENDING_MODES = frozenset({'se', 'race', 'extreme'})
# pending.best 数值键（strategy result 端点 best_out 同键集；done 态恒有限数值，
# NaN/±Inf 拒收防密度/料长展示污染）。placed_items 单独逐条校验（与 run.placed
# 同一判据）。
_PENDING_BEST_NUMERIC_KEYS = ('seed', 'frame_index', 'elapsed', 'density',
                              'density_sparrow', 'width_mm')
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


def _validate_placed_list(placed, pieces, *, path: str, form: dict,
                          quantities, skip_conservation: bool = False) -> None:
    """placed 逐条形态 + pid 全命中 doc + 守恒终检（run 块 / pending 槽**同一
    判据**，US-001 抽取共享）。

    ``path`` = 报错文案前缀（``'run.placed'`` /
    ``'pending_strategy_result.best.placed_items'``）。pid 全命中与守恒
    unknown_pid 文案不同（前者「母版外」、后者码选过滤/退化石也算未排料），
    按故事口径分别给文案；守恒与保存端复用同一判定函数。

    ``skip_conservation``（2026-09-14 展示级降级）：``run.stale`` 标记的背景
    run 跳过守恒比对 —— 形态校验与 pid 全命中保留（后者仍是硬门槛：母版外
    引用无论 stale 与否都拒），``form/quantities`` 形态异常同 400（rebuild 的
    manifest 重算消费这两块，不让坏形态漏成 500）。
    """
    if not isinstance(placed, list) or not placed:
        raise StateFileError(f'状态文件损坏（{path} 不能为空）')
    for i, item in enumerate(placed):
        if not isinstance(item, dict):
            raise StateFileError(f'状态文件损坏（{path}[{i}] 须为对象）')
        if not isinstance(item.get('id'), str) or not item['id']:
            raise StateFileError(f'状态文件损坏（{path}[{i}].id 须为非空字符串）')
        if not _finite(item.get('rotation')):
            raise StateFileError(f'状态文件损坏（{path}[{i}].rotation 须为数值）')
        tr = item.get('translation')
        if (not isinstance(tr, (list, tuple)) or len(tr) != 2
                or not _finite(tr[0]) or not _finite(tr[1])):
            raise StateFileError(
                f'状态文件损坏（{path}[{i}].translation 须为 [x,y] 数值对）')
        if 'mirror' in item and not isinstance(item['mirror'], bool):
            raise StateFileError(f'状态文件损坏（{path}[{i}].mirror 须为布尔）')
    # pid 全命中 doc.pieces（镜像 edit-polish 语义：先查母版身份，再谈守恒）。
    pids = {p['pid'] for p in pieces}
    miss = [it['id'] for it in placed if it['id'] not in pids]
    if miss:
        raise StateFileError(
            f'状态文件内部不一致：{path} 引用母版外裁片'
            f'（pid {miss[0]!r} 不在 doc.pieces）')
    # 副本守恒终检（manifest 重算后 demand 口径；保存端同一函数 —— 手改文件让
    # placed ≠ demand 在此拦下，不让内部不一致布局进入恢复会话）。
    try:
        check_placed_conservation(placed, pieces, sizes=form.get('sizes'),
                                  per_type=form.get('per_type'),
                                  quantities=quantities)
    except StateConservationError as e:
        if skip_conservation:
            return   # 展示级降级：背景 run 与现行数量失配容忍（pending 槽仍全量校验）
        if e.kind == 'unknown_pid':
            # pid 在 doc 但不在重算 demand（码选过滤 / erode 退化石）—— 同属
            # 「引用未排料裁片」的内部不一致，文案沿用母版外口径 + detail。
            raise StateFileError(
                f'状态文件内部不一致：{path} 引用母版外裁片（{e.detail}）')
        raise StateFileError(
            f'状态文件内部不一致：{path} 副本数与数量矩阵不符（{e.detail}）')
    except (ValueError, TypeError) as e:
        raise StateFileError(f'状态文件损坏（form/quantities 形态非法：{e}）')


def _validate_run_block(run: dict, pieces, *, form: dict, quantities) -> None:
    """run 块校验：placed（与 pending 槽共用判据）→ final → provenance 枚举。

    ``run.stale`` 展示级降级（2026-09-14，checkpoint 侧打标省键式）：``True``
    → placed 跳过守恒终检（逐条形态 + pid 全命中保留）—— pending 在场时 run
    块只是弹窗背景，恢复后画布先显旧布局、确认才被 pending 置换（与活界面
    「背景无条件显示旧 run」同口径）；非 bool → 400（形态门）。缺省（无键/
    False）守恒终检照旧 —— .msn 保存端不产此键，旧文件/未打标快照零变化。
    """
    if 'stale' in run and not isinstance(run['stale'], bool):
        raise StateFileError('状态文件损坏（run.stale 须为布尔）')
    _validate_placed_list(run.get('placed'), pieces, path='run.placed',
                          form=form, quantities=quantities,
                          skip_conservation=run.get('stale') is True)
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


def _validate_pending_block(pending: dict, pieces, *, form: dict,
                            quantities) -> None:
    """pending_strategy_result 槽校验（恢复端全量形态，在场时 fail-fast）。

    - ``mode`` 枚举（恢复路由键，文案风格同 run.provenance.kind）；
    - ``best`` 数值键有限数值（NaN/±Inf 拒收）+ ``placed_items`` 与 run.placed
      **同一判据**（共用 ``_validate_placed_list``：逐条形态/pid 全命中/守恒
      终检 + 同「内部不一致」文案）；
    - ``summary`` 在场须为 dict（展示级宽松，provenance.config 同款不承重）。

    manifest/run_dir 不入槽不校验：恢复端 rebuild 已用 build_pid_meta 确定性
    重算 manifest 并随响应回传（单份几何）。
    """
    mode = pending.get('mode')
    if mode not in _PENDING_MODES:
        raise StateFileError(
            f'状态文件损坏（pending_strategy_result.mode 非法：{mode!r}；'
            f'须为 se/race/extreme 之一）')
    best = pending.get('best')
    if not isinstance(best, dict):
        raise StateFileError('状态文件损坏（pending_strategy_result.best 须为对象）')
    for key in _PENDING_BEST_NUMERIC_KEYS:
        if not _finite(best.get(key)):
            raise StateFileError(
                f'状态文件损坏（pending_strategy_result.best.{key} 须为有限数值）')
    summary = pending.get('summary')
    if summary is not None and not isinstance(summary, dict):
        raise StateFileError(
            '状态文件损坏（pending_strategy_result.summary 须为对象）')
    _validate_placed_list(best.get('placed_items'), pieces,
                          path='pending_strategy_result.best.placed_items',
                          form=form, quantities=quantities)


def _check_pending_save(pending, pieces, *, form: dict, quantities) -> None:
    """保存/快照端 pending 槽校验（state_save 与 checkpoint._store_checkpoint
    共用；US-001 镜像 run 块保存分叉深度）。

    深度镜像 run 块：dict → mode 枚举 → best dict → placed_items 非空列表 →
    逐条 id 非空 str → 守恒（``StateConservationError`` 由调用方转 400 指路
    文案 / ``{stored:false, reason:'conservation'}``）。rotation/translation/
    mirror/数值键等全量形态由恢复端 ``_validate_pending_block`` 把关（run 块
    同款两端深度不对称）。
    """
    if not isinstance(pending, dict):
        raise StateFileError('pending_strategy_result 须为对象')
    mode = pending.get('mode')
    if mode not in _PENDING_MODES:
        raise StateFileError(
            f'pending_strategy_result.mode 非法：{mode!r}'
            f'（须为 se/race/extreme 之一）')
    best = pending.get('best')
    if not isinstance(best, dict):
        raise StateFileError('pending_strategy_result.best 须为对象')
    placed_items = best.get('placed_items')
    if not isinstance(placed_items, list) or not placed_items:
        raise StateFileError('pending_strategy_result.best.placed_items 不能为空')
    for i, item in enumerate(placed_items):
        if (not isinstance(item, dict)
                or not isinstance(item.get('id'), str) or not item['id']):
            raise StateFileError(
                f'pending_strategy_result.best.placed_items[{i}] 形态非法'
                f'（需 {{id,rotation,translation}}）')
    check_placed_conservation(placed_items, pieces, sizes=form.get('sizes'),
                              per_type=form.get('per_type'),
                              quantities=quantities)


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
    7. run 块（在场时：``_validate_run_block``；``run.stale=True`` → 守恒终检
       展示级降级跳过，形态/pid 命中保留）；
    8. pending_strategy_result 槽（在场时：``_validate_pending_block`` ——
       省键式缺席 = 旧文件零迁移）。

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
    if pending := document.get('pending_strategy_result'):
        if not isinstance(pending, dict):
            raise StateFileError('状态文件损坏（pending_strategy_result 须为对象）')
        _validate_pending_block(pending, document['doc']['pieces'],
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

    请求 ``{form, quantities, quantities_base?, run?, save_as?,
    pending_strategy_result?}``（前端 buildSavePayload，US-003）：form = FormState
    全量原样入文件；quantities_base = 整列设值基准 {label:整数}（省键式，body
    无 → 文件无键）；run 仅 done 态（body 无 run → 文件无 run 键）；
    pending_strategy_result = 待确认的策略/极限 done 结果槽（省键式 additive，
    2026-09-13；形态/守恒校验镜像 run 块分叉）；save_as（2026-09-12 弹窗）=
    确认的名称主体（无扩展名 —— /export 同口径用户定案），清洗 + 补 .msn 后
    覆盖，只影响响应 CD 不入档。响应 200 附件（Content-Disposition 中文/ASCII
    双写，/export 同法），文件名 ``<source 去 .dxf>_状态_<yyyymmdd-HHMMSS>.msn``。

    错误契约（全部结构化 JSON，非文件流）：
    - sid 过期/墓碑 → 401 ``{code:'session_expired'}``、非法 → 400（SessionError
      统一映射，_resolve_session_state 同 routes_views 读路由口径）；
    - 会话空（无 doc/pieces，未 commit）→ 422；
    - body 非 JSON / form 缺失 / quantities·quantities_base·run·
      pending_strategy_result 形态非法 / run.placed·pending.best.placed_items
      条目形态非法 → 400；
    - 保存期守恒校验（run/pending 在场：placed pid 全命中会话 pieces + Counter
      == demand(form.sizes × quantities)，改数量/码选未重解 → 400 指路文案 ——
      改数量未重解场景 run 块与 pending 槽同生共死，用户视角一个错）。
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

    # pending_strategy_result 槽（省键式 additive）：形态/守恒校验镜像 run 块
    # 分叉（_check_pending_save 共享），守恒失败与 run 块同文案 —— 改数量未重解
    # 场景两块同生共死，用户视角一个错。
    pending = payload.get('pending_strategy_result')
    if pending is not None and not isinstance(pending, dict):
        return JSONResponse({'error': 'pending_strategy_result 须为对象'},
                            status_code=400)
    if pending:
        try:
            _check_pending_save(pending, pieces, form=form,
                                quantities=quantities)
        except StateConservationError:
            return JSONResponse({'error': _CONSERVATION_SAVE_MESSAGE},
                                status_code=400)
        except (ValueError, TypeError):
            return JSONResponse(
                {'error': 'form.sizes/per_type/quantities 形态非法，无法核对数量守恒'},
                status_code=400)
        except StateFileError as e:
            return JSONResponse({'error': e.message}, status_code=e.status)

    document = build_state_document(state, form, quantities, run,
                                    quantities_base, pending)
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
    # 2026-09-12 导出文件名弹窗：save_as = 前端弹窗确认的名称主体（无扩展名；
    # /export 同法）。只影响响应 CD，**不入档**（build_state_document 不透传，
    # schema v1 不动）；清洗（非法字符）+ 自动补 .msn 后为空 → 逐字节走上方合成名。
    save_as = sanitize_download_name(str(payload.get('save_as') or ''),
                                     STATE_EXTENSION.lstrip('.'))
    if save_as:
        fname_cn = save_as
        if save_as.isascii():
            fname_ascii = save_as
    cd = f"attachment; filename=\"{fname_ascii}\"; filename*=UTF-8''{quote(fname_cn)}"
    return Response(content=data, media_type='application/gzip',
                    headers={'Content-Disposition': cd})


# ---------------------------------------------------------------- POST /api/state-restore

def rebuild_session_from_document(document: dict, sid: str | None,
                                  *, filename_fallback: str = '') -> dict:
    """纯内存重建会话 + manifest 确定性重算 + 响应组装（US-001 抽取共享函数）。

    ``state_restore`` 内联重建段原样抽取（行为零变更重构）；checkpoint 恢复端点
    （US-002 ``/api/state-recover``）同复用。前置契约：

    - ``document`` 已过 ``parse_state_document`` 校验链（doc_id 由本函数铸新后
      原位改写；调用方接管所有权）；
    - ``sid`` 已过 ``registry.resolve(sid, create=True)``（本函数经 ``peek`` 取
      回同一 ``SessionState`` —— 调用方刚 resolve 过，peek 必命中）。

    重建五步（= state_restore 原内联序）：doc_id 铸新 uuid + ``_state_from_doc``
    + sid/default 双分支写入（sid → ``st.state = state`` 覆盖语义 = 再上传母版
    commit；default → runtime 等价原子重绑，锁内 clear+update 不读盘不写盘）+
    ``build_pid_meta`` manifest 重算（``gate_mm`` 取 ``_form_gate_mm`` form 口径）
    + ``_build_parse_payload`` 经 ``_DocPieceView`` 组 parse 载荷 + sid 在场
    ``edit_hold.refresh``（default 豁免不进钉住表）。

    响应 dict 与 ``/api/state-restore`` 成功响应同形（US-002 恢复端点 additive
    ``recovered_from`` 键由调用方补）：``{doc_id, filename, parse, manifest,
    final, placed, run, pending_strategy_result, quantities_base, form,
    quantities}``。``pending_strategy_result`` additive 回传（省键式文件缺席 →
    None，前端 no-op；在场 → 校验链已过，US-002 恢复编排按 mode 路由写回对应
    族 store 重开弹窗结果态）—— /api/state-restore 与 /api/state-recover 共享
    本函数免费同形增益。
    """
    st = session_registry.peek(sid)
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
    # pending 槽原样回传（校验链已过；manifest/run_dir 不入档 —— 上方确定性重算
    # 的 manifest 单份几何即恢复弹窗/再应用的数据源）。
    pending = document.get('pending_strategy_result') or None

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
    filename = doc.get('source') or filename_fallback
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
        'pending_strategy_result': pending,
        'quantities_base': quantities_base,
        'form': form,
        'quantities': quantities,
    }


async def state_restore(request: Request, file: UploadFile = File(...)):
    """POST /api/state-restore：上传 .msn → 校验 → 纯内存重建当前会话 + manifest 重算。

    multipart 收文件（扩展名 .msn/.json；纯 JSON 也接受）。流程（设计 §五.6/§七）：
    1. 扩展名/大小（raw > 20MB → 413）→ ``run_in_threadpool(parse_state_document)``
       （解压+json+校验链 CPU 密集，不阻塞事件循环；解析在会话解析**之前** —— 坏
       文件不新建会话名额）；
    2. ``registry.resolve(sid, create=True)``（commit 先例：恢复写入**当前 sid**，
       等价「再上传母版 commit」覆盖语义、不占 ``MS_SESSION_MAX`` 名额；过期 401 /
       超限 429 / 非法 400 结构化 JSON）；
    3. ``rebuild_session_from_document``（US-001 抽取共享函数，checkpoint 恢复
       端点同复用）—— 纯内存重建 state：doc_id 铸新 uuid、源文件名保留
       doc.source —— sid 会话
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
    写回来源，无 run 时为 None）；``pending_strategy_result`` = 待确认策略/极限
    done 结果槽 additive 回传（省键式文件缺席 → None → 前端 no-op；在场时校验
    链已过，恢复编排按 mode 路由写回对应族 store）；``quantities_base`` =
    整列设值基准回传（省键式文件缺席 → None → 前端 no-op 保持默认 1）。错误
    契约：校验链失败 → 400/413 ``{error}``（StateFileError 全结构化 JSON，不炸
    500）。
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
        session_registry.resolve(sid, create=True)
    except SessionError as e:
        return JSONResponse(e.payload(), status_code=e.status)

    # 重建 + manifest 重算 + 响应组装（US-001 抽取共享函数 —— 行为零变更；
    # checkpoint 恢复端点 /api/state-recover US-002 同复用）。
    return rebuild_session_from_document(document, sid,
                                         filename_fallback=fname)


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
    # pending_strategy_result 槽（US-001 additive）：done 态 result 端点同形最小面
    # {mode, best(含 placed_items), summary}；manifest/run_dir 不入档。
    pending = {
        'mode': 'se',
        'best': {'seed': 7, 'frame_index': 42, 'elapsed': 311.2,
                 'density': 0.861, 'density_sparrow': 0.843,
                 'width_mm': 7310.5,
                 'placed_items': [dict(p) for p in placed]},
        'summary': {'per_seed': [{'seed': 7, 'killed': False,
                                  'kill_reason': None, 'best_density': 0.861,
                                  'elapsed': 311.2, 'phase': 'extension'}],
                    'mode': 'se',
                    'se': {'k_screens': 3, 'screen_s': 90, 'ext_s': 600,
                           'champion': 7}},
    }

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
    with_pending = build_state_document(state, form, quantities, run,
                                        quantities_base, pending)
    check('pending_strategy_result 槽入档（additive：键在场且原样嵌入）',
          with_pending['pending_strategy_result'] == pending)
    check('pending None/缺席 → 整块省略（省键式，旧文件口径零迁移）',
          'pending_strategy_result' not in build_state_document(
              state, form, quantities, run, quantities_base)
          and 'pending_strategy_result' not in build_state_document(
              state, form, quantities, run, quantities_base, None))

    data = serialize_state(with_run)
    check('serialize 为 gzip（魔数 1f 8b）', data[:2] == b'\x1f\x8b')
    parsed = json.loads(gzip.decompress(data))
    check('往返逐字段一致（doc 5 层原样 / form / quantities / quantities_base / '
          'run.placed 原序）',
          parsed['doc'] == doc and parsed['form'] == form
          and parsed['quantities'] == quantities
          and parsed['quantities_base'] == quantities_base
          and parsed['run']['placed'] == placed)
    pending_bytes = serialize_state(with_pending)
    check('带槽序列化 gzip 往返：pending 逐字段一致（best.placed_items 原序含 '
          'mirror/summary 原样）',
          json.loads(gzip.decompress(pending_bytes))
          ['pending_strategy_result'] == pending)

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
    restored_pending = parse_state_document(pending_bytes)
    check('parse_state_document：带 pending 槽通过且与原件逐字段一致（守恒/形态'
          '全过）',
          restored_pending['pending_strategy_result'] == pending
          and restored_pending['run']['placed'] == placed)
    check('parse_state_document：无 pending 旧口径文件 → 键缺席（零迁移）',
          'pending_strategy_result' not in parse_state_document(data))
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

    # ---------------- 2026-09-14 run.stale 展示级降级（checkpoint 打标宽容）
    def _with_stale(fn):
        d = json.loads(gzip.decompress(data))
        d['run']['stale'] = True
        fn(d)
        return gzip.compress(json.dumps(d, ensure_ascii=False).encode('utf-8'))

    check('恢复校验：run.stale=True + 副本数失配 → 跳过守恒终检照常通过'
          '（背景 run 保留）',
          parse_state_document(_with_stale(
              lambda d: d['quantities']['g01'].__setitem__('30', 5)))
          ['run']['stale'] is True)
    expect_error('恢复校验：run.stale 非布尔 → 400',
                 lambda: parse_state_document(_tamper(
                     lambda d: d['run'].__setitem__('stale', 'yes'))),
                 want='run.stale 须为布尔')
    expect_error('恢复校验：run.stale=True 但 placed 引用母版外 pid → 仍 400'
                 '（pid 命中是硬门槛，不随降级豁免）',
                 lambda: parse_state_document(_with_stale(
                     lambda d: d['run']['placed'][2].__setitem__('id', 'zz_99'))),
                 want='run.placed 引用母版外裁片')

    # ------------------------------------------------ US-001 pending 槽篡改链
    def _tamper_pending(fn):
        d = json.loads(gzip.decompress(pending_bytes))
        fn(d)
        return gzip.compress(json.dumps(d, ensure_ascii=False).encode('utf-8'))

    expect_error('恢复校验：pending.mode 非法枚举 → 400',
                 lambda: parse_state_document(_tamper_pending(
                     lambda d: d['pending_strategy_result'].__setitem__(
                         'mode', 'magic'))),
                 want='pending_strategy_result.mode 非法')
    expect_error('恢复校验：pending.placed_items 引用母版外 pid → 400 内部不一致',
                 lambda: parse_state_document(_tamper_pending(
                     lambda d: d['pending_strategy_result']['best']
                     ['placed_items'][2].__setitem__('id', 'zz_99'))),
                 want='pending_strategy_result.best.placed_items 引用母版外裁片')
    expect_error('恢复校验：pending placed 副本数 ≠ demand → 400 内部不一致',
                 lambda: parse_state_document(_tamper_pending(
                     lambda d: d['pending_strategy_result']['best']
                     ['placed_items'].pop())),
                 want='副本数与数量矩阵不符')
    expect_error('恢复校验：pending.best.density NaN → 400',
                 lambda: parse_state_document(_tamper_pending(
                     lambda d: d['pending_strategy_result']['best'].__setitem__(
                         'density', float('nan')))),
                 want='pending_strategy_result.best.density 须为有限数值')
    expect_error('恢复校验：pending.placed_items 条目 rotation 非数值 → 400',
                 lambda: parse_state_document(_tamper_pending(
                     lambda d: d['pending_strategy_result']['best']
                     ['placed_items'][0].__setitem__('rotation', 'flat'))),
                 want='rotation 须为数值')
    expect_error('恢复校验：pending.summary 非 dict → 400',
                 lambda: parse_state_document(_tamper_pending(
                     lambda d: d['pending_strategy_result'].__setitem__(
                         'summary', 'ok'))),
                 want='pending_strategy_result.summary 须为对象')

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
