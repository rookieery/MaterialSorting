"""web 服务共享运行时：排料裁片状态快照 + 求解线程池（自 server.py 机械拆出）。

模块级副作用与拆分前的 server.py 完全一致（import 本模块即生效，且发生在
server.py 创建 FastAPI app 之前，顺序不变）：
  - 启动时读一次 ``paths.INTERMEDIATE`` 填 ``_PIECES_STATE``（失败只 warn 不崩）；
  - 创建共享 ``ThreadPoolExecutor(max_workers=6)``（parse / commit / WS 求解共用）。

``_PIECES_STATE`` 只原位 clear+update、从不 rebind —— server.py 与各 routes_*
模块 re-export 的都是同一 dict 对象，读者（tests 的 ``server_mod._PIECES_STATE``、
strategy.py 延迟 ``from .server import _get_pieces_state``）始终拿到一致快照。
"""
from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from .. import paths
from .solver import load_pieces

# US-020：可 reload 的排料裁片状态。
# `_PIECES_STATE` 是一个 immutable snapshot dict —— `_reload_pieces_state()` 走「在外
# 构建新 dict → 锁内整体替换引用」模式，读者始终拿到一个完整一致的快照（不会读到
# 半状态）。`/ws/solve` 在 accept 阶段拿一次快照，整个 ws 连接内 pieces 不变（避免
# 求解中途数据切）；`/export` 路由同样走 `_get_pieces_state()`。commit 成功后立即调
# `_reload_pieces_state()` 让下一次请求吃到新 intermediate（前端无需重启 ms-web）。
_state_lock = threading.Lock()
_PIECES_STATE: dict = {}


def _build_pieces_state(intermediate_path: str = paths.INTERMEDIATE) -> dict:
    """从 intermediate JSON 构建 pieces state 快照（不在锁内调用，可重入）。

    返回 {doc, gate_mm, pieces, pieces_by_id}；pieces_by_id = {pid: piece_dict}。
    intermediate 缺失或解析异常时返回空 state（{n:0,...}）—— 启动期 allow-empty 由
    `_init_pieces_state()` 决定，本函数纯粹做读取 + 索引。
    """
    doc, gate_mm, pieces = load_pieces(intermediate_path)
    return {
        'doc': doc,
        'gate_mm': gate_mm,
        'pieces': pieces,
        'pieces_by_id': {p['pid']: p for p in pieces},
    }


def _reload_pieces_state(intermediate_path: str = paths.INTERMEDIATE) -> dict:
    """重读 intermediate → 原子替换 `_PIECES_STATE` 引用 → 返回新快照。

    在锁内构建新 dict（load_pieces 是文件 I/O + JSON 解析；commit 频率远低于 ws 读
    取，且锁粒度对 6-worker 池可忽略），保证读者不会看到半状态。返回的 dict 同时被
    `_PIECES_STATE` 引用，调用方可以放心返回给前端 / 后续路由使用。
    """
    with _state_lock:
        new_state = _build_pieces_state(intermediate_path)
        _PIECES_STATE.clear()
        _PIECES_STATE.update(new_state)
        return new_state


def _get_pieces_state() -> dict:
    """锁内返回当前 `_PIECES_STATE` 只读快照（调用方拿到后整连接复用，不再切）。"""
    with _state_lock:
        return _PIECES_STATE


# 启动时读一次中间数据（事实源：paths.INTERMEDIATE）→ 填入 _PIECES_STATE。
# 若 intermediate 不存在（首次启动未上传母版 commit），_PIECES_STATE 保持空 dict；
# 后续 GET /api/ptypes / /ws/solve 会降级返回空数据，commit 成功后 _reload 才真正填入。
try:
    _reload_pieces_state()
except Exception as e:
    print(f'[server] 启动期 load_pieces 失败，_PIECES_STATE 暂为空：{e}', file=sys.stderr)

_executor = ThreadPoolExecutor(max_workers=6)   # 多 seed 对比最多 6 个并发求解（seed 间同等 CPU 竞争 → 排名仍公平）
