"""编辑排料会话钉住（alive hook 编辑豁免源，2026-09-04）。

**问题**：编辑排料（编辑弹窗拖动/旋转/保存）是纯前端操作 —— 编辑期间不发任何
HTTP/WS；求解已结束（无 WS 钉住）、无策略轮询（无 touch），后端视角该会话完全
空闲。``MS_SESSION_TTL_SEC``（缺省 600s）空闲过期会在长编辑（版师精修大图 30min+
很常态）中途把会话逐出为墓碑 → 用户保存后导出 / 再求解 → 401 ``session_expired``
→ 全局阻断弹窗刷新 → 前端内存编辑成果全部丢失（编辑态不持久化、不落盘）。

**方案**（镜像 strategy.py 的 run 存活钉住 + 终态宽限语义）：前端编辑弹窗打开期间
滚动 ``POST /api/edit-hold`` 续期本表（``sid → hold_until = clock()+EDIT_HOLD_SEC``，
缺省 2h）；关窗不显式释放 —— 最后一次心跳 + 2h 自然宽限（保存后去吃饭回来导出
不丢，同「跑完挂机不丢结果」语义；宽限内会话仍占 ``MS_SESSION_MAX`` 名额，与策略
宽限口径一致）。编辑中机器睡眠 ≤2h 唤醒后续期恢复也兜得住（纯 ``last_active``
心跳兜不住睡眠：睡眠期间无请求，唤醒前已被逐出）。

**接线**：sessions 的 alive hook 是单 slot 覆盖式、既有生产方 = strategy.py；
``install()`` 在 server.py 文件尾（strategy 注册**之后**）把既有 hook 包一层组合体
（任一豁免源给出未来时间戳即钉住；都给出取 max）。hook 契约不变：纯内存 dict
读写、无锁、异常由调用方吞 —— 本模块 hook 只做一次 dict 查找。

``refresh`` 在路由上下文（不持 ``registry._lock``）调用：GIL 原子的 dict 赋值 /
整体 rebind 与持锁 hook 读并发安全；顺带清扫过期条目防泄漏（表大小 ≤ 活跃编辑
会话数，逐出/关窗后的残留由下一次任意 refresh 收走）。

仅依赖同包 ``sessions``（单向无环，AST 守卫见 tests/test_web_edit_hold.py）；
**禁 import server**（edit_hold 被 server import）。
"""
from __future__ import annotations

from typing import Callable

from .sessions import DEFAULT_SID, _env_float

# 编辑钉住滚动窗（秒）：前端心跳间隔 4min 的 30 倍 —— 任意 2h 窗内一次成功心跳
# 即续命（容忍网络抖动 / 短睡眠）；关窗后同款窗自然宽限。缺省与
# ``MS_RESULT_GRACE_SEC``（策略终态宽限）对齐 = 2h。
EDIT_HOLD_SEC: float = _env_float('MS_EDIT_HOLD_SEC', 7200.0)

# sid → hold_until（``registry.clock()`` 时间戳，与 TTL 比较同一时钟源可注入推进）。
# 模块级单表：进程级接线（reset / 会话逐出不清理 —— hold 过期自然失效，refresh
# 顺带清扫），非会话状态。
_HOLDS: dict[str, float] = {}

_installed = False


def refresh(sid: str, now: float) -> float:
    """续期编辑钉住（路由上下文调用）：``hold_until = now + EDIT_HOLD_SEC``（滚动）。

    顺带清扫已过期条目（防残留泄漏）；返回本 sid 新 hold_until。
    """
    horizon = now + EDIT_HOLD_SEC
    for s in [s for s, until in _HOLDS.items() if until <= now]:
        del _HOLDS[s]
    _HOLDS[sid] = horizon
    return horizon


def hold_until(sid: str) -> float | None:
    """纯读：sid 的钉住截止时间戳（无钉住 → None；测试观测用）。"""
    return _HOLDS.get(sid)


def _edit_hold_hook(sid: str) -> float | None:
    """alive hook 豁免源（``registry._lock`` 持锁上下文内被调）：default → None
    （default 豁免一切永不被问，防御性返回）；否则查表 —— 已过期的 hold 返回
    原值，由 ``_pinned_by_hook`` 的 ``now < hold_until`` 判据自然否决。"""
    if sid == DEFAULT_SID:
        return None
    return _HOLDS.get(sid)


def install(registry) -> None:
    """组合注册：把当前已注册 hook（strategy 的 run 钉住）与本模块编辑钉住包成
    组合体再注册 —— 任一非 None 即豁免、都非 None 取 max（豁免判据只看「是否在
    未来」，两源独立无互斥语义）。幂等；**必须在 strategy 注册之后调用**（单 slot
    覆盖式，顺序反了组合体会被 strategy 覆写丢失编辑豁免）。"""
    global _installed
    if _installed:
        return
    prev: Callable[[str], float | None] | None = registry._alive_hook

    def _combined(sid: str) -> float | None:
        a = _edit_hold_hook(sid)
        b = prev(sid) if prev is not None else None   # strategy 旧 hook 委托保留
        vals = [v for v in (a, b) if v is not None]
        return max(vals) if vals else None

    registry.register_alive_hook(_combined)
    _installed = True
