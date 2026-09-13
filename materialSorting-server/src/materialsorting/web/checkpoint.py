"""会话过期自动恢复：服务端内存 checkpoint + 写入/清除端点（prd US-001）。

多会话工作台 10 分钟空闲过期后，旧体验是「阻断弹窗 + 强制刷新 + 数据全丢」。
本模块按 sid 维护**工作台状态的内存快照**（复用 ``statefile`` 的
``build_state_document`` + ``serialize_state`` .msn 管线），会话过期后用户刷新
页面时由恢复端点（US-002 ``POST /api/state-recover``）消费 —— 过期前状态有了
恢复来源。恢复只由用户刷新触发；页面停留期间绝不自动恢复（用户定案，见
tasks/prd-session-expiry-auto-recovery.md FR-3）。

- ``_CheckpointStore``：``OrderedDict[sid → {data: gzip bytes, ts}]`` +
  ``threading.Lock`` + 惰性 TTL 清理 + FIFO 容量上限（时钟可注入测试）。纯内存
  不落盘（服务重启 = 丢快照 = FR-5 静默兜底路径，可接受；单条 ≈ gzip 后
  100–200KB，16 条上限 ≈ 3MB）。
- ``POST /api/state-checkpoint``：经 ``registry.peek(sid)`` 读会话快照
  （**绝不 resolve —— 不刷 last_active、不建会话名额**，否则常开 Tab 永不过期，
  破坏 ``MS_SESSION_MAX`` 容量回收语义）。body = state-save 同形
  ``{form, quantities, quantities_base?, run?, save_as?}``（save_as 容忍忽略）。
  会话空（无 doc/pieces）→ ``200 {stored:false, reason:'empty'}``；run 守恒校验
  失败（``check_placed_conservation`` 复用，改数量未重解的中间态）→
  ``200 {stored:false, reason:'conservation'}`` 且**先前好快照字节不变**
  （last-good，FR-2：自动后台任务不打扰用户）；成功 → ``200 {stored:true}``。
- ``DELETE /api/state-checkpoint``：幂等清除（条目不存在也 ``200 {ok:true}``；
  F5 干净重置防「稍后再过期恢复出 F5 前旧状态」幽灵回潮，US-004 消费）。
- ``POST /api/state-recover``（US-002）：刷新后启动期恢复 —— 前端铸新 sid 放
  ``X-Session-Id``，body ``{from_sid: 旧sid}``。闸门序（与 state_restore 同序）：
  from_sid 过 ``SID_RE``（非法/缺失 → 400）→ ``store.get(from_sid)`` 不在 / 超
  TTL → ``404 {code:'checkpoint_not_found'}`` → ``run_in_threadpool(
  parse_state_document)``（解析在会话 resolve **之前**，坏数据不占会话名额；
  校验链失败 → 400/413 同 state_restore 契约）→ ``registry.resolve(new_sid,
  create=True)``（commit 先例；429 session_limit 结构化透传，**checkpoint 不删**
  留待重试）→ ``statefile.rebuild_session_from_document`` 共享重建（sid 在场时
  内含 ``edit_hold.refresh(new_sid)``）+ additive ``recovered_from: from_sid``
  键（响应与 state-restore 成功响应同形，前端直接复用 applyRestorePayload）→
  **恢复成功即删该 checkpoint 条目**（single-use：旧 sid 已入墓碑永不复用，
  防多 Tab 反复恢复放大名额占用）。

env：``MS_CHECKPOINT_TTL_SEC``（缺省 7200，对齐恢复窗 = 过期后墓碑 1h + 会话
TTL 10min + 余量 —— 超窗 checkpoint 无消费方，纯内存浪费）/ ``MS_CHECKPOINT_MAX``
（缺省 16，FIFO）。分层：web 层兄弟模块，仅 import ``.sessions``/``.statefile``
（含 ``statefile._valid_base_map`` 等私有复用，statefile → solver/runtime 同款
兄弟私有先例），**禁 import server**（AST 守卫见 tests/test_web_checkpoint.py，
sessions.py 同款先例）。
"""
from __future__ import annotations

import asyncio
import gzip
import json
import sys
import threading
import time
from collections import OrderedDict
from typing import Callable

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .sessions import (
    DEFAULT_SID,
    SID_RE,
    InvalidSidError,
    SessionError,
    SessionExpiredError,
    _env_float,
    _env_int,
    registry as session_registry,
)
from .statefile import (
    StateConservationError,
    StateFileError,
    _valid_base_map,
    build_state_document,
    check_placed_conservation,
    parse_state_document,
    rebuild_session_from_document,
    serialize_state,
)

__all__ = [
    'CHECKPOINT_MAX',
    'CHECKPOINT_TTL_SEC',
    'register_checkpoint_routes',
    'state_recover',
    'store',
]

# 惰性 TTL 缺省 7200s（恢复窗对齐：过期后墓碑 1h + 会话 TTL 10min + 余量）。
CHECKPOINT_TTL_SEC: float = _env_float('MS_CHECKPOINT_TTL_SEC', 7200.0)
# FIFO 容量上限（≈ 3MB 内存上限，16 × 100–200KB gzip 快照）。
CHECKPOINT_MAX: int = _env_int('MS_CHECKPOINT_MAX', 16)


# ---------------------------------------------------------------- 内存快照存储

class _CheckpointStore:
    """sid → ``{data: gzip bytes, ts}`` 内存快照存储（进程内单例 ``store``）。

    - ``threading.Lock`` 串行化（put/get/delete/reset 原子）；
    - **惰性 TTL 清理**：put/get 时清超龄条目（无 daemon 线程 —— 超窗快照无
      消费方，清理时机不影响正确性，只影响内存驻留；``now - ts > ttl`` 判超，
      sessions 墓碑同款严格不等）；
    - **FIFO 容量上限**：超 ``max_entries`` 逐出最旧（OrderedDict 首键；重复
      put 同 sid 先弹出再尾插 = 刷新新鲜度）；
    - 时钟可注入（``clock``：TTL/FIFO 测试与 ``__main__`` 冒烟不依赖真实墙钟）。
    """

    def __init__(self, *, ttl_sec: float | None = None,
                 max_entries: int | None = None,
                 clock: Callable[[], float] | None = None):
        self.ttl_sec = CHECKPOINT_TTL_SEC if ttl_sec is None else ttl_sec
        self.max_entries = CHECKPOINT_MAX if max_entries is None else max_entries
        self.clock = clock or time.time
        self._entries: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, sid: str, data: bytes) -> None:
        """写入/覆盖快照（尾插刷新新鲜度）+ 惰性清超龄 + 超容量逐出最旧。"""
        now = self.clock()
        with self._lock:
            self._purge_expired_locked(now)
            self._entries.pop(sid, None)
            self._entries[sid] = {'data': data, 'ts': now}
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def get(self, sid: str) -> bytes | None:
        """读快照字节；条目不在 / 超 TTL（惰性清除后）→ None。"""
        now = self.clock()
        with self._lock:
            self._purge_expired_locked(now)
            entry = self._entries.get(sid)
            return None if entry is None else entry['data']

    def delete(self, sid: str) -> bool:
        """删除条目：返回是否真删（不存在 → False；幂等，调用方无需区分）。"""
        with self._lock:
            return self._entries.pop(sid, None) is not None

    def size(self) -> int:
        """当前条目数（观测/测试用；TTL 未清理的超龄条目计入）。"""
        with self._lock:
            return len(self._entries)

    def reset(self) -> None:
        """测试隔离：清全部条目（registry.reset 同款）。"""
        with self._lock:
            self._entries.clear()

    def _purge_expired_locked(self, now: float) -> None:
        """清超龄条目（调用方须持 ``self._lock``）。"""
        expired = [sid for sid, e in self._entries.items()
                   if now - e['ts'] > self.ttl_sec]
        for sid in expired:
            del self._entries[sid]


# 全进程唯一存储（路由与 US-002 恢复端点共用；测试经 reset() 隔离）。
store = _CheckpointStore()


# ---------------------------------------------------------------- 业务内核（可测）

def _store_checkpoint(sid: str | None, payload) -> tuple[dict, int]:
    """POST /api/state-checkpoint 业务内核（handler 委派；测试/__main__ 冒烟直调）。

    返回 ``(body, status)``：
    - sid 非法 → 400 ``{error:'sid 非法'}``（SID_RE，resolve 同判据）；
    - 会话不在（peek None：过期逐出 / 从未注册）→ 401 ``{code:'session_expired'}``
      —— 死会话无快照可打，且旧 sid 已入墓碑，写入无意义；
    - 会话空（无 doc/pieces，未 commit）→ 200 ``{stored:false, reason:'empty'}``
      （前端自动调度容忍、静默跳过，FR-2 同哲学）；
    - 载荷形态非法（body 非 dict / form 缺失 / quantities·quantities_base·run
      形态 / run.placed 条目形态）→ 400（与 state-save 同文案同判据）；
    - run 在场守恒校验失败（``check_placed_conservation`` 复用：改数量未重解的
      中间态）→ 200 ``{stored:false, reason:'conservation'}`` 且先前好快照字节
      不变（last-good —— put 未发生，FR-2）；
    - 成功 → ``build_state_document`` + ``serialize_state`` 入库 →
      200 ``{stored:true}``。

    **绝不 resolve**：peek 口径不刷 ``last_active``、不建会话名额（FR-1）。
    """
    if sid is not None and not SID_RE.match(sid):
        e = InvalidSidError()
        return e.payload(), e.status
    st = session_registry.peek(sid)
    if st is None:
        e = SessionExpiredError()
        return e.payload(), e.status

    doc = st.state.get('doc') or {}
    pieces = st.state.get('pieces') or []
    if not doc or not pieces:
        return {'stored': False, 'reason': 'empty'}, 200

    if not isinstance(payload, dict):
        return {'error': '请求体须为 JSON 对象'}, 400
    form = payload.get('form')
    if not isinstance(form, dict):
        return {'error': '缺少 form 或类型错误'}, 400
    quantities = payload.get('quantities')
    if quantities is not None and not isinstance(quantities, dict):
        return {'error': 'quantities 须为 {label:{sizeKey:N}} 对象'}, 400
    quantities_base = payload.get('quantities_base')
    if quantities_base is not None and not _valid_base_map(quantities_base):
        return {'error': 'quantities_base 须为 {label:整数} 对象'}, 400
    run = payload.get('run')   # save_as 键容忍忽略（仅影响 save 的 CD，不入档）
    if run is not None and not isinstance(run, dict):
        return {'error': 'run 须为对象'}, 400

    if run:
        placed = run.get('placed')
        if not isinstance(placed, list) or not placed:
            return {'error': 'run.placed 不能为空'}, 400
        for i, item in enumerate(placed):
            if (not isinstance(item, dict)
                    or not isinstance(item.get('id'), str) or not item['id']):
                return {'error': f'run.placed[{i}] 形态非法'
                                 f'（需 {{id,rotation,translation}}）'}, 400
        # 守恒 fail-fast（state-save 同一函数）：失败 → stored:false 且不 put
        # （先前好快照字节不变 = last-good）；形态非法同 400。
        try:
            check_placed_conservation(
                placed, pieces, sizes=form.get('sizes'),
                per_type=form.get('per_type'), quantities=quantities)
        except StateConservationError:
            return {'stored': False, 'reason': 'conservation'}, 200
        except (ValueError, TypeError):
            return {'error': 'form.sizes/per_type/quantities 形态非法，'
                             '无法核对数量守恒'}, 400

    document = build_state_document(st.state, form, quantities, run,
                                    quantities_base)
    store.put(sid or DEFAULT_SID, serialize_state(document))
    return {'stored': True}, 200


# ---------------------------------------------------------------- 路由

async def state_checkpoint(request: Request):
    """POST /api/state-checkpoint：当前会话工作台状态 → 内存快照（peek 口径）。

    详见 ``_store_checkpoint``（本 handler 只做 HTTP 壳：sid 头 + JSON body 解析）。
    错误契约全结构化 JSON（401 带 code，FR-10）。
    """
    sid = (request.headers.get('x-session-id') or '').strip() or None
    try:
        payload = await request.json()
    except Exception:
        payload = None   # 非 JSON body → 内核 400（与 state-save 同文案）
    body, status = _store_checkpoint(sid, payload)
    return JSONResponse(body, status_code=status)


async def checkpoint_delete(request: Request):
    """DELETE /api/state-checkpoint：幂等清除该 sid 的内存快照。

    条目不存在也 ``200 {ok:true}``（F5 干净重置路径无序态可依赖）；sid 非法 →
    400（fail-fast 先于业务，FR-10）；**不触碰会话注册表**（peek 都不需要 ——
    死会话的残留快照同样该清，TTL 之外的主动清理面）。
    """
    sid = (request.headers.get('x-session-id') or '').strip() or None
    if sid is not None and not SID_RE.match(sid):
        e = InvalidSidError()
        return JSONResponse(e.payload(), status_code=e.status)
    store.delete(sid or DEFAULT_SID)
    return {'ok': True}


# ---------------------------------------------------------------- POST /api/state-recover（US-002）

# 404 文案：快照不在（从未写入 / TTL 惰性清除 / 已被恢复消费）与超 TTL 同走
# store.get → None 单一判据，语义上都是「无可恢复工作状态」。
_CHECKPOINT_NOT_FOUND_MESSAGE = '未找到可恢复的工作状态（快照不存在或已过期）'


def _recover_session(sid: str | None, from_sid: str, document: dict) -> tuple[dict, int]:
    """恢复内核（解析后段；handler 委派，测试/__main__ 冒烟直调）。

    ``document`` 已过 ``parse_state_document`` 校验链（handler 经 threadpool
    解析后传入）。流程 = ``registry.resolve(sid, create=True)``（commit 先例：
    恢复写入**当前（新）sid**，等价「再上传母版 commit」覆盖语义；过期 401 /
    超限 429 / 非法 400 结构化透传 —— 429 时 **checkpoint 不删**，名额腾出后
    重试仍可恢复）→ ``rebuild_session_from_document`` 共享重建（响应与
    state-restore 成功响应同形；sid 在场时内含 ``edit_hold.refresh(sid)``）→
    additive ``recovered_from: from_sid`` → 恢复成功即删该 checkpoint 条目
    （single-use：防多 Tab 反复恢复放大名额占用）。
    """
    try:
        session_registry.resolve(sid, create=True)
    except SessionError as e:
        return e.payload(), e.status
    res = rebuild_session_from_document(document, sid)
    res['recovered_from'] = from_sid      # additive：state-restore 同形 + 来源回显
    store.delete(from_sid)                # single-use：成功消费即删
    return res, 200


async def state_recover(request: Request):
    """POST /api/state-recover：旧 sid 的 checkpoint → 恢复成当前（新）会话。

    请求 ``X-Session-Id = 新 sid``（前端铸新后携带；缺省 → default 会话，
    state_restore 同语义）+ body ``{from_sid: 旧sid}``。闸门序（state_restore
    同序，详见模块 docstring）：from_sid 校验 → checkpoint 查找 → threadpool
    解析（坏数据不占会话名额）→ 会话 resolve → 共享重建 + 删条目。成功响应 =
    state-restore 成功响应同形 + ``recovered_from``；404/400/413/401/429 全
    结构化 JSON。
    """
    sid = (request.headers.get('x-session-id') or '').strip() or None
    try:
        payload = await request.json()
    except Exception:
        payload = None   # 非 JSON body → from_sid 缺失分支 400
    from_sid = payload.get('from_sid') if isinstance(payload, dict) else None
    if not isinstance(from_sid, str) or not SID_RE.match(from_sid):
        return JSONResponse({'error': 'from_sid 非法'}, status_code=400)

    raw = store.get(from_sid)   # 不在 / 超 TTL（惰性清除）→ None 单一判据
    if raw is None:
        return JSONResponse(
            {'code': 'checkpoint_not_found', 'error': _CHECKPOINT_NOT_FOUND_MESSAGE},
            status_code=404)

    # 解析先行（threadpool，state_restore 同序）：坏快照不触发会话 resolve、
    # 不建会话名额（快照由本服务 serialize_state 产出，校验链失败 ≈ 内存损坏，
    # 但闸门序保证失败路径零副作用）。
    try:
        document = await run_in_threadpool(parse_state_document, raw)
    except StateFileError as e:
        return JSONResponse({'error': e.message}, status_code=e.status)

    body, status = _recover_session(sid, from_sid, document)
    return JSONResponse(body, status_code=status)


def register_checkpoint_routes(app) -> None:
    """把 checkpoint 路由挂到 FastAPI app（server.py 文件尾调用一次；statefile/
    strategy 同模式）。"""
    app.post('/api/state-checkpoint')(state_checkpoint)
    app.delete('/api/state-checkpoint')(checkpoint_delete)
    app.post('/api/state-recover')(state_recover)


# ---------------------------------------------------------------- __main__ 自检

class _FakeRequest:
    """最小 Request 桩（__main__ 冒烟驱动 async handler：headers + json body）。"""

    def __init__(self, headers: dict, json_body):
        self.headers = headers
        self._json_body = json_body

    async def json(self):
        if self._json_body is _NOT_JSON:
            raise ValueError('not json')
        return self._json_body


_NOT_JSON = object()


def _smoke_doc():
    """合成会话 state（statefile._smoke_piece 同款 5 层全量裁片夹具）。"""
    from .runtime import _state_from_doc
    from .statefile import _smoke_piece

    pieces = [_smoke_piece('g01_30', 200, 150), _smoke_piece('g02_30', 180, 120)]
    doc = {'doc_id': 'smoke0001', 'source': '5336冒烟母版.dxf', 'gate_mm': 1750.0,
           'n_pieces': len(pieces), 'total_area_mm2': 51600.0, 'pieces': pieces,
           'label_representatives': {}}
    return doc, _state_from_doc(doc)


def _smoke() -> int:
    """``python -m materialsorting.web.checkpoint``：合成夹具全链自检。

    三段：① ``_CheckpointStore`` 单元生命周期（假时钟：写入→读回逐字节对拍 /
    TTL 惰性清理 / FIFO 逐出 / 重复 put 刷新 / DELETE 幂等）；②
    ``_store_checkpoint`` 端点内核全路径（私有会话注入单例 registry：
    stored:true → gunzip + parse_state_document 对拍 / empty / conservation
    last-good / 非法 sid 400 / 死会话 401 / save_as 容忍 / peek 不刷 last_active
    / DELETE 生命周期）；③ ``state_recover`` 全链（真实 handler 经 _FakeRequest：
    过期逐出 → 新 sid 恢复 200 同形响应 + recovered_from + 守恒 + single-use 删
    条目 + edit_hold 生效；双次恢复 404 / 坏 from_sid 400 / 不在 404 / 坏快照
    400 不占名额）。
    """
    from .sessions import _FakeClock

    results: list[tuple[str, bool]] = []

    def check(name: str, cond: bool) -> None:
        results.append((name, bool(cond)))

    # ------------------------------------------------ ① store 生命周期（假时钟）
    clk = _FakeClock()
    cs = _CheckpointStore(ttl_sec=100.0, max_entries=2, clock=clk)
    cs.put('s1', b'alpha')
    cs.put('s2', b'beta')
    check('store：写入后读回逐字节对拍', cs.get('s1') == b'alpha'
          and cs.get('s2') == b'beta' and cs.size() == 2)
    cs.put('s3', b'gamma')       # FIFO 超 2 → 最旧 s1 逐出
    check('store：FIFO 容量 2 → 第 3 个写入逐出最旧（s1）',
          cs.get('s1') is None and cs.get('s2') == b'beta'
          and cs.get('s3') == b'gamma')
    cs.put('s3', b'gamma2')      # 重复 put 同 sid → 覆盖 + 尾插（s2 仍在）
    check('store：重复 put 同 sid 覆盖且刷新新鲜度',
          cs.get('s3') == b'gamma2' and cs.size() == 2)
    clk.advance(101.0)           # 全部超龄 → get 惰性清除
    check('store：超 TTL → get 视为不存在且惰性清除',
          cs.get('s2') is None and cs.size() == 0)
    check('store：DELETE 幂等（不在也 False 不抛）',
          cs.delete('ghost') is False and cs.delete('ghost') is False)
    cs.put('s4', b'delta')
    check('store：DELETE 在场条目 → True 且读回 None',
          cs.delete('s4') is True and cs.get('s4') is None)

    # ------------------------------------------------ ② 端点内核全路径
    reg = session_registry
    reg.reset()
    store.reset()
    real_clock = reg.clock
    reg.clock = clk          # 复用①的假时钟（③ recover 过期链同一时钟推进）
    try:
        doc, state = _smoke_doc()
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
        run = {'seed': 0, 'final': {'density': 0.84, 'width_mm': 7523.0},
               'placed': placed}

        sid = 'ckpts001'
        st = reg.resolve(sid, create=True)
        st.state = state
        st.last_active = 42.0
        n_active = reg.active_count

        body, status = _store_checkpoint(sid, {'form': form,
                                               'quantities': quantities,
                                               'run': run})
        check('内核：合法载荷 → 200 {stored:true}', status == 200
              and body == {'stored': True})
        parsed = parse_state_document(store.get(sid))
        check('内核：快照 gunzip + parse_state_document 对拍（doc/form/'
              'quantities/run 逐字段）',
              parsed['doc'] == doc and parsed['form'] == form
              and parsed['quantities'] == quantities
              and parsed['run']['placed'] == placed)
        check('内核：peek 口径 —— last_active 不变 + 不建会话名额',
              st.last_active == 42.0 and reg.active_count == n_active)

        body, status = _store_checkpoint(sid, {'form': form,
                                               'quantities': quantities,
                                               'run': run,
                                               'save_as': 'ignored-name'})
        check('内核：save_as 键容忍忽略（照常 stored:true）',
              status == 200 and body == {'stored': True}
              and store.get(sid) is not None)

        good_bytes = store.get(sid)
        body, status = _store_checkpoint(
            sid, {'form': form,
                  'quantities': {'g01': {'30': 5}, 'g02': {'30': 1}}, 'run': run})
        check('内核：守恒失败 → 200 {stored:false, reason:conservation}',
              status == 200 and body == {'stored': False,
                                         'reason': 'conservation'})
        check('内核：last-good —— 守恒失败后先前好快照字节不变',
              store.get(sid) == good_bytes
              and json.loads(gzip.decompress(good_bytes))['quantities']
              == quantities)

        empty_sid = 'ckpts002'
        reg.resolve(empty_sid, create=True)   # 注册未 commit（state 空 dict）
        body, status = _store_checkpoint(empty_sid, {'form': form,
                                                     'quantities': quantities})
        check('内核：会话空（无 doc）→ 200 {stored:false, reason:empty}',
              status == 200 and body == {'stored': False, 'reason': 'empty'}
              and store.get(empty_sid) is None)

        body, status = _store_checkpoint('bad-sid!', {'form': form})
        check('内核：非法 sid → 400 {error:sid 非法}',
              status == 400 and body == {'error': 'sid 非法'})
        body, status = _store_checkpoint('neverreg01', {'form': form})
        check('内核：会话不在（peek None）→ 401 {code:session_expired}',
              status == 401 and body.get('code') == 'session_expired')
        body, status = _store_checkpoint(sid, {'quantities': quantities})
        check('内核：缺 form → 400', status == 400 and 'form' in body.get('error', ''))

        check('DELETE：在场删除后读回 None，再次 DELETE 幂等',
              store.delete(sid) is True and store.get(sid) is None)

        # ------------------------------------------------ ③ recover 全链（US-002）
        from . import edit_hold

        sid_old = 'ckpts010'
        st_old = reg.resolve(sid_old, create=True)
        st_old.state = state
        _store_checkpoint(sid_old, {'form': form, 'quantities': quantities,
                                    'run': run})
        snap_bytes = store.get(sid_old)
        clk.advance(reg.ttl_sec + 1.0)       # 会话超 TTL（checkpoint 不受影响）
        check('recover 前置：过期扫描逐出旧 sid 为墓碑，checkpoint 字节不受会话'
              '逐出影响',
              sid_old in reg.scan_once() and reg.tombstoned(sid_old)
              and reg.peek(sid_old) is None and store.get(sid_old) == snap_bytes)

        sid_new = 'ckpts011'
        resp = asyncio.run(state_recover(
            _FakeRequest({'x-session-id': sid_new}, {'from_sid': sid_old})))
        res = json.loads(resp.body)
        check('recover：过期会话 → 新 sid 恢复 200', resp.status_code == 200)
        check('recover：响应 = state-restore 成功响应同形 + additive recovered_from',
              set(res) == {'doc_id', 'filename', 'parse', 'manifest', 'final',
                           'placed', 'run', 'quantities_base', 'form',
                           'quantities', 'recovered_from'}
              and res['recovered_from'] == sid_old)
        check('recover：新会话 pieces/pieces_by_id 与快照逐字段一致',
              reg.peek(sid_new).state['pieces'] == doc['pieces']
              and set(reg.peek(sid_new).state['pieces_by_id']) == {'g01_30', 'g02_30'})
        check('recover：form/quantities/run 逐字段回显',
              res['form'] == form and res['quantities'] == quantities
              and res['run']['placed'] == placed)
        try:
            check_placed_conservation(
                res['placed'], reg.peek(sid_new).state['pieces'],
                sizes=form.get('sizes'), per_type=form.get('per_type'),
                quantities=quantities)
            check('recover：守恒通过（placed == demand 重算口径）', True)
        except StateConservationError:
            check('recover：守恒通过（placed == demand 重算口径）', False)
        check('recover：checkpoint 已删（single-use）', store.get(sid_old) is None)
        check('recover：edit_hold.refresh(new_sid) 已生效（rebuild 内含）',
              edit_hold.hold_until(sid_new) is not None)

        resp2 = asyncio.run(state_recover(
            _FakeRequest({'x-session-id': 'ckpts012'}, {'from_sid': sid_old})))
        check('recover：双次恢复第二次 → 404 {code:checkpoint_not_found}',
              resp2.status_code == 404
              and json.loads(resp2.body)['code'] == 'checkpoint_not_found')
        resp3 = asyncio.run(state_recover(
            _FakeRequest({'x-session-id': 'ckpts013'}, {'from_sid': 'bad!'})))
        check('recover：坏 from_sid → 400 {error:from_sid 非法}',
              resp3.status_code == 400
              and json.loads(resp3.body) == {'error': 'from_sid 非法'})
        resp4 = asyncio.run(state_recover(
            _FakeRequest({'x-session-id': 'ckpts014'}, {'from_sid': 'neverreg1'})))
        check('recover：checkpoint 不在（从未写入）→ 404',
              resp4.status_code == 404
              and json.loads(resp4.body)['code'] == 'checkpoint_not_found')
        store.put('ckpts015', b'corrupt-bytes')   # 直接注入坏快照字节
        n_before = reg.active_count
        resp5 = asyncio.run(state_recover(
            _FakeRequest({'x-session-id': 'ckpts016'}, {'from_sid': 'ckpts015'})))
        check('recover：坏快照 → 400 状态文件损坏 且不建会话名额（解析在 resolve 前）',
              resp5.status_code == 400
              and '状态文件损坏' in json.loads(resp5.body)['error']
              and reg.active_count == n_before and reg.peek('ckpts016') is None)
    finally:
        reg.clock = real_clock
        store.reset()
        reg.reset()

    n_pass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f'[checkpoint] {"PASS" if ok else "FAIL"}  {name}')
    print(f'[checkpoint] 自检 {n_pass}/{len(results)} PASS')
    return 0 if n_pass == len(results) else 1


if __name__ == '__main__':
    sys.exit(_smoke())
