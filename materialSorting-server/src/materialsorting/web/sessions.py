"""web 多会话注册表与生命周期（PRD web 多会话隔离 US-001）。

ms-web 此前是「单文档单例」：``runtime._PIECES_STATE`` 进程级全局一份，多端同时
使用时任一客户端 commit 即覆盖所有人的当前文档（静默串台）。本模块按
``X-Session-Id``（sid）维护独立会话：

- **SessionRegistry**：``OrderedDict[sid → SessionState]``（进程内单例 ``registry``）。
  所有 sid → 会话归属收敛到单一 ``resolve()``：带合法 sid → 该 sid；不带 → 固定
  常量键 ``DEFAULT_SID='default'``。default 豁免容量上限与空闲过期、不占
  ``MS_SESSION_MAX`` 名额、不参与墓碑；其 pieces 快照与 ``runtime._PIECES_STATE``
  是**同一 dict 对象**（runtime 只原位 clear+update 从不 rebind，commit 自动同步；
  uuid4 hex sid 仅含 0-9a-f，与含非 hex 字符的 ``'default'`` 结构性不可碰撞）。
- **容量闸门**：``MS_SESSION_MAX``（缺省 4）仅计活跃会话，超出 → 429
  ``{code:'session_limit'}``。
- **空闲过期**：``MS_SESSION_TTL_SEC``（缺省 300）请求时惰性检查 + 30s daemon 扫描
  线程（``ws_open>0`` 的会话跳过 —— WS 连接钉住不误杀）。超时逐出为墓碑
  ``{sid, ts}``（丢全部状态只留 sid，FIFO ≤128、存活 1h）；墓碑命中 → 401
  ``{code:'session_expired'}`` —— 保证过期 sid 不被当新会话静默重建。

仅标准库 + 同包 ``runtime``；**不 import server.py**（依赖方向 server → sessions
单向，无环，AST 守卫见 tests/test_web_sessions.py）。sid 字符集单一真相源
``SID_RE`` 在本模块（与 doc_id 同规则），server.py re-export 为 ``_DOC_ID_RE``。
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Callable

from .runtime import _PIECES_STATE

# ---------------------------------------------------------------- 配置（env 可调）

DEFAULT_SID = 'default'


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        print(f'[sessions] 环境变量 {name}={raw!r} 非法，回退缺省 {default}', file=sys.stderr)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        print(f'[sessions] 环境变量 {name}={raw!r} 非法，回退缺省 {default}', file=sys.stderr)
        return default


SESSION_MAX: int = _env_int('MS_SESSION_MAX', 4)             # 活跃会话上限（default 豁免不占额）
SESSION_TTL_SEC: float = _env_float('MS_SESSION_TTL_SEC', 300.0)   # 空闲过期阈值（秒）
TOMBSTONE_TTL_SEC: float = 3600.0    # 墓碑存活 1h：超龄/FIFO 淘汰前该 sid 不可重建
TOMBSTONE_MAX: int = 128             # 墓碑 FIFO 容量上限
SCAN_INTERVAL_SEC: float = 30.0      # daemon 扫描周期（秒）

# sid 合法字符集（``[0-9A-Za-z]{1,128}``，与 doc_id 同规则：防路径逃逸/注入）。
# 单一真相源在本模块（sessions 不能 import server，反向由 server re-export）。
SID_RE = re.compile(r'^[0-9A-Za-z]{1,128}$')


# ---------------------------------------------------------------- 错误类型

class SessionError(Exception):
    """会话解析失败基类：``status`` + 结构化 ``code``/``error``（路由层捕获后统一转
    JSONResponse；400 无 code 键，401/429 带 code —— additive，旧前端可忽略）。"""

    status: int = 500
    code: str | None = None
    message: str = ''

    def __init__(self, message: str | None = None):
        super().__init__(message or self.message)
        self.error = message or self.message

    def payload(self) -> dict:
        if self.code:
            return {'code': self.code, 'error': self.error}
        return {'error': self.error}


class InvalidSidError(SessionError):
    status = 400
    message = 'sid 非法'


class SessionExpiredError(SessionError):
    status = 401
    code = 'session_expired'
    message = '会话已过期（5 分钟无操作），请刷新页面'


class SessionLimitError(SessionError):
    status = 429
    code = 'session_limit'

    def __init__(self, max_sessions: int):
        # 上限文案随实际配置插值（缺省 4 → 与 PRD 定稿文案逐字一致）
        super().__init__(f'当前使用用户过多（最多 {max_sessions} 人同时在线），请稍后尝试')


# ---------------------------------------------------------------- 会话状态

@dataclass
class SessionState:
    """单会话可变状态（registry 内原位更新字段，从不整体 rebind）。

    - ``state``：pieces 快照 dict（``{doc, gate_mm, pieces, pieces_by_id}``，与
      ``runtime._build_pieces_state`` 返回同构）。default 会话持有
      ``runtime._PIECES_STATE`` **同一对象**；非 default 会话由 commit（US-002）填
      per-doc 快照，注册期先置空 dict（未 commit 前无数据，不与 default 共享）。
    - ``doc_id``：commit 落盘母版 id（US-002 写入；US-006 磁盘清理保护集消费）。
    - ``strategy_busy``：策略长跑状态位（US-004 会话化时启用，占位 False）。
    """

    sid: str
    state: dict = field(default_factory=dict)
    doc_id: str | None = None
    last_active: float = 0.0
    ws_open: int = 0
    strategy_busy: bool = False

    @property
    def pieces(self) -> list:
        return self.state.get('pieces') or []

    @property
    def pieces_by_id(self) -> dict:
        return self.state.get('pieces_by_id') or {}

    @property
    def gate_mm(self):
        return self.state.get('gate_mm')


# ---------------------------------------------------------------- 注册表

class SessionRegistry:
    """sid → SessionState 注册表（进程内单例 ``registry``，测试经 ``reset()`` 隔离）。

    时钟可注入（``clock``）：TTL/墓碑测试与 ``__main__`` 冒烟不依赖真实墙钟长等待。
    """

    def __init__(self, *, max_sessions: int | None = None, ttl_sec: float | None = None,
                 tombstone_ttl_sec: float | None = None, tombstone_max: int | None = None,
                 scan_interval_sec: float | None = None,
                 clock: Callable[[], float] | None = None):
        self.max_sessions = SESSION_MAX if max_sessions is None else max_sessions
        self.ttl_sec = SESSION_TTL_SEC if ttl_sec is None else ttl_sec
        self.tombstone_ttl_sec = TOMBSTONE_TTL_SEC if tombstone_ttl_sec is None else tombstone_ttl_sec
        self.tombstone_max = TOMBSTONE_MAX if tombstone_max is None else tombstone_max
        self.scan_interval_sec = SCAN_INTERVAL_SEC if scan_interval_sec is None else scan_interval_sec
        self.clock = clock or time.time
        self._sessions: OrderedDict[str, SessionState] = OrderedDict()
        self._tombstones: deque = deque(maxlen=self.tombstone_max)
        self._lock = threading.Lock()      # 结构性变更（建/逐出/墓碑）串行化
        self._scan_stop = threading.Event()
        self._scan_thread: threading.Thread | None = None
        self._ensure_default()

    # ------------------------------------------------ 单一解析函数（所有路由经此）

    def resolve(self, sid: str | None, *, create: bool = False) -> SessionState:
        """sid → SessionState 归属解析（web 层唯一入口，路由不得自行翻字典）。

        - ``sid`` 缺省（None/空串）→ default 会话（豁免上限/过期/墓碑，惰性重建）；
        - 格式非法 → ``InvalidSidError``（400）；
        - 命中墓碑、惰性检查发现已超时（当场逐出为墓碑）、或合法但从未注册且
          ``create=False``（服务重启丢内存等场景：数据已失，同过期语义）→
          ``SessionExpiredError``（401，不静默重建）；
        - 存活会话 → 刷 ``last_active`` 返回（重复 POST 幂等）；
        - ``create=True`` 且未知合法 sid → 容量未满新建（满 → ``SessionLimitError``
          429）。
        """
        if not sid:
            with self._lock:
                self._ensure_default()
                return self._sessions[DEFAULT_SID]
        if not SID_RE.match(sid):
            raise InvalidSidError()
        now = self.clock()
        with self._lock:
            self._purge_tombstones_locked(now)
            st = self._sessions.get(sid)
            if st is not None:
                if sid != DEFAULT_SID and self._is_expired(st, now):
                    self._evict_locked(sid, now)
                    raise SessionExpiredError()
                st.last_active = now
                return st
            if any(t['sid'] == sid for t in self._tombstones):
                raise SessionExpiredError()
            if not create:
                raise SessionExpiredError()
            if self._active_count_locked() >= self.max_sessions:
                raise SessionLimitError(self.max_sessions)
            st = SessionState(sid=sid, last_active=now)
            self._sessions[sid] = st
            return st

    def touch(self, sid: str | None) -> None:
        """请求外刷新活性（WS 回调 on_manifest/on_report 等，US-003 消费）。

        no-op 不抛：会话已不在（被逐出/从未注册）说明过期路径已由连接入口把关。
        单 float 写 GIL-safe，不加锁。
        """
        st = self._sessions.get(sid or DEFAULT_SID)
        if st is not None:
            st.last_active = self.clock()

    def ws_acquire(self, sid: str | None) -> SessionState:
        """WS 连接钉住会话：resolve 语义（过期/墓碑/非法同抛）+ ``ws_open += 1``。"""
        st = self.resolve(sid)
        with self._lock:
            st.ws_open += 1
        return st

    def ws_release(self, sid: str | None) -> None:
        """WS 断开：``ws_open`` 减 1（下限 0；会话已被逐出 → no-op，finally 友好）。"""
        with self._lock:
            st = self._sessions.get(sid or DEFAULT_SID)
            if st is not None and st.ws_open > 0:
                st.ws_open -= 1

    # ------------------------------------------------ 扫描（惰性检查的兜底）

    def scan_once(self, now: float | None = None) -> list[str]:
        """扫描一轮：逐出超时且 ``ws_open==0`` 的非 default 会话为墓碑 + 清超龄墓碑。

        返回本轮逐出的 sid（测试/冒烟观测用）。daemon 线程周期调用 —— 已死会话若
        不再发请求，容量名额只能由本扫描回收（惰性检查永远等不到那次请求）。
        """
        if now is None:
            now = self.clock()
        evicted: list[str] = []
        with self._lock:
            self._purge_tombstones_locked(now)
            for sid in list(self._sessions):
                if sid == DEFAULT_SID:
                    continue
                if self._is_expired(self._sessions[sid], now):
                    self._evict_locked(sid, now)
                    evicted.append(sid)
        return evicted

    def start_scanner(self) -> None:
        """启动 daemon 扫描线程（幂等；server.py import 时调用一次）。"""
        if self._scan_thread is not None and self._scan_thread.is_alive():
            return
        self._scan_stop.clear()
        t = threading.Thread(target=self._scan_loop, name='ms-session-scan', daemon=True)
        self._scan_thread = t
        t.start()

    def stop_scanner(self) -> None:
        """停扫描线程（测试隔离：防真实线程在 monkeypatch 时钟窗口内并发逐出）。"""
        self._scan_stop.set()
        self._scan_thread = None

    def _scan_loop(self) -> None:
        while not self._scan_stop.wait(self.scan_interval_sec):
            try:
                self.scan_once()
            except Exception as e:      # daemon 兜底：扫描失败不崩进程
                print(f'[sessions] 扫描线程异常（忽略继续）：{e}', file=sys.stderr)

    # ------------------------------------------------ 观测/测试辅助

    def reset(self) -> None:
        """测试隔离：清全部会话与墓碑，重建 default。"""
        with self._lock:
            self._sessions.clear()
            self._tombstones.clear()
            self._ensure_default()

    def peek(self, sid: str | None) -> SessionState | None:
        """非抛式读取（观测/测试用；``'default'`` 字面键同样命中 default 会话）。"""
        return self._sessions.get(sid or DEFAULT_SID)

    def tombstoned(self, sid: str) -> bool:
        with self._lock:
            return any(t['sid'] == sid for t in self._tombstones)

    def tombstones(self) -> list[dict]:
        with self._lock:
            return list(self._tombstones)

    @property
    def active_count(self) -> int:
        """活跃会话数（不含 default —— default 豁免且不占 ``MS_SESSION_MAX`` 名额）。"""
        with self._lock:
            return self._active_count_locked()

    # ------------------------------------------------ 内部（调用方须持 self._lock）

    def _ensure_default(self) -> None:
        if DEFAULT_SID not in self._sessions:
            self._sessions[DEFAULT_SID] = SessionState(
                sid=DEFAULT_SID, state=_PIECES_STATE, last_active=self.clock())

    def _active_count_locked(self) -> int:
        return sum(1 for s in self._sessions if s != DEFAULT_SID)

    def _is_expired(self, st: SessionState, now: float) -> bool:
        return st.ws_open <= 0 and (now - st.last_active) > self.ttl_sec

    def _evict_locked(self, sid: str, now: float) -> None:
        """逐出：丢 SessionState 全部状态（含 pieces 快照内存负载），只留墓碑。"""
        del self._sessions[sid]
        self._tombstones.append({'sid': sid, 'ts': now})   # deque maxlen ⇒ FIFO ≤ tombstone_max

    def _purge_tombstones_locked(self, now: float) -> None:
        """清超龄墓碑（存活 1h）：清除后该 sid 视为全新（可正常新建）。"""
        if any(now - t['ts'] > self.tombstone_ttl_sec for t in self._tombstones):
            self._tombstones = deque(
                (t for t in self._tombstones if now - t['ts'] <= self.tombstone_ttl_sec),
                maxlen=self.tombstone_max)


# 全进程唯一注册表（server.py 路由与后续 US-002~004 各入口共用；测试经 reset() 隔离）。
registry = SessionRegistry()


class _FakeClock:
    """可推进的假时钟（测试 / ``__main__`` 冒烟用，不依赖真实墙钟长等待）。"""

    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


# ---------------------------------------------------------------- 冒烟入口

def _smoke() -> int:
    """``python -m materialsorting.web.sessions``：打印配置 + 模拟建会话/过期/超限生命周期。

    跑在私有 SessionRegistry 上（不动单例 ``registry`` 的真实状态）。
    """
    print(f'[sessions] 配置 MS_SESSION_MAX={SESSION_MAX} MS_SESSION_TTL_SEC={SESSION_TTL_SEC} '
          f'墓碑TTL={TOMBSTONE_TTL_SEC}s FIFO≤{TOMBSTONE_MAX} 扫描周期={SCAN_INTERVAL_SEC}s')
    print(f'[sessions] default 会话豁免：state is runtime._PIECES_STATE = '
          f'{registry.resolve(None).state is _PIECES_STATE}')

    results: list[tuple[str, bool]] = []

    def check(name: str, cond: bool) -> None:
        results.append((name, bool(cond)))

    def _err(fn) -> SessionError | None:
        try:
            fn()
            return None
        except SessionError as e:
            return e

    clk = _FakeClock()
    reg = SessionRegistry(max_sessions=2, ttl_sec=5.0, tombstone_ttl_sec=3600.0,
                          tombstone_max=3, clock=clk)
    reg.resolve('aaaa1111', create=True)
    reg.resolve('bbbb2222', create=True)
    check('建会话 a/b 后 active_count==2（default 不占额）', reg.active_count == 2)
    e = _err(lambda: reg.resolve('cccc3333', create=True))
    check('超限第 3 个新 sid → 429 session_limit',
          e is not None and e.status == 429 and e.code == 'session_limit')

    clk.advance(3.0)
    reg.touch('aaaa1111')          # a 刷活性；b 保持旧时间戳
    clk.advance(3.0)               # now：a 龄 3（活）、b 龄 6（超时）
    e = _err(lambda: reg.resolve('bbbb2222'))
    check('惰性过期：超时 b 再解析 → 401 session_expired',
          e is not None and e.status == 401 and e.code == 'session_expired')
    check('b 逐出为墓碑（丢状态只留 sid/ts）', reg.tombstoned('bbbb2222'))
    e = _err(lambda: reg.resolve('bbbb2222', create=True))
    check('墓碑命中不静默重建 → 401', e is not None and e.status == 401)
    st_c = reg.resolve('cccc3333', create=True)   # b 逐出腾出名额
    check('b 逐出腾名额后 c 新建成功', st_c.sid == 'cccc3333' and reg.active_count == 2)

    reg.ws_acquire('cccc3333')
    clk.advance(600.0)             # WS 钉住：远超 ttl 也不逐出
    evicted = reg.scan_once(clk.now)
    check('ws_open>0 扫描不逐出（c 存活；闲置 a 被逐出）',
          'cccc3333' not in evicted and reg.peek('cccc3333') is not None
          and evicted == ['aaaa1111'])
    reg.ws_release('cccc3333')
    check('ws_open 归零后扫描逐出 c', reg.scan_once(clk.now) == ['cccc3333'])

    clk.advance(3601.0)            # 墓碑全部超 1h 龄 → 清除
    st_b = reg.resolve('bbbb2222', create=True)
    check('墓碑 1h 过期后 sid 可正常重建', st_b.sid == 'bbbb2222')
    check('default 永不被扫描逐出（时钟远超 ttl）',
          reg.scan_once(clk.now) == [] and reg.resolve(None).sid == DEFAULT_SID)
    e = _err(lambda: reg.resolve('bad-sid!'))
    check('非法 sid → 400 {error:"sid 非法"}',
          e is not None and e.status == 400 and e.payload() == {'error': 'sid 非法'})

    n_pass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f'[sessions] {"PASS" if ok else "FAIL"}  {name}')
    print(f'[sessions] 冒烟 {n_pass}/{len(results)} PASS')
    return 0 if n_pass == len(results) else 1


if __name__ == '__main__':
    sys.exit(_smoke())
