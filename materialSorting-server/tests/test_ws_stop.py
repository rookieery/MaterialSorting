"""US-026 WS /ws/solve stop 消息 + 进程终止 + 断开清理测试。

3 项核心场景（spec AC: ≥3）：
  1. start → 收到 frame 后发 stop → 收到 stopped 且 WS 关闭、进程终止；
  2. start 后直接断连 → 后端清理不泄漏（进程数回落）；
  3. 不发 stop 正常求解收 final（回归不破坏）。

用 starlette TestClient 驱动 ASGI app。小问题（单码 16 片）在 exploring 阶段
每 ~3ms 吐一帧 → 3s 预算可积攒 ~800+ frame；测试用 deadline 循环而非固定计数。
"""
from __future__ import annotations

import multiprocessing
import time
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from materialsorting.nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
from materialsorting.web import server as server_mod
from materialsorting.web.server import app


def _smallest_loaded_size() -> int:
    """当前 ``_PIECES_STATE`` 最小码号（单码子集加速）。

    真实 intermediate 的码号集随母版漂移（本机 30~40、开发期 28~38），硬编码
    28 会在母版切换后 manifest 0 片 —— 与 conftest「real or synthetic」同哲学：
    从已加载状态动态取码，空状态回退 28。
    """
    pieces = server_mod._PIECES_STATE.get('pieces_by_id') or {}
    sizes = sorted({p['size'] for p in pieces.values()
                    if isinstance(p, dict) and isinstance(p.get('size'), int)})
    return sizes[0] if sizes else 28


def _start_payload(*, time_budget: int = 3, seed: int = 1) -> dict[str, Any]:
    """构造最小合法 start payload（sizes 取最小码子集加速，短预算）。"""
    return {
        'action': 'start',
        'sizes': [_smallest_loaded_size()],
        'time': time_budget,
        'seed': seed,
        'params': {'d_ext': 0, 'd_int': 0, 'tol_ext': 0, 'tol_int': 0},
        'per_type': None,
        'quantities': None,
    }


@pytest.fixture
def ws_client():
    """TestClient + websocket_connect 上下文工厂。"""
    with TestClient(app) as client:
        yield client


# --------------------------------------------- AC-(1) start → frame → stop → stopped

def test_stop_after_frame_terminates_and_sends_stopped(ws_client):
    """发 start → 收到 frame 后发 stop → 收到 {type:stopped} 且 WS 关闭、进程终止。

    - start 后应收到 manifest + ≥1 frame；
    - 发 {action:stop} 后应收到 {type:'stopped', reason:'user_requested'}；
      stop 后 read_loop terminate+join process（事件循环短暂阻塞）→ stopped 入队 →
      write loop 逐条发完残余 frame + stopped + SENTINEL → WS 关闭；
    - solve 子进程在 stop 后应被 terminate（无孤儿）。
    """
    child_before = len(multiprocessing.active_children())
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start_payload(time_budget=60, seed=1))

        # 1) manifest
        manifest = ws.receive_json()
        assert manifest['type'] == 'manifest'
        assert manifest['gate_mm'] > 0
        assert len(manifest['pieces']) >= 1

        # 2) 至少一个 frame（drain_interval=0.2 → ~0.2s 内有）
        frame = ws.receive_json()
        assert frame['type'] == 'frame'
        assert 'density' in frame and 'density_sparrow' in frame

        # 3) 发 stop
        ws.send_json({'action': 'stop'})

        # 4) 收到 stopped —— stop 后 read_loop 阻塞 terminate+join（事件循环暂停），
        #    恢复后 write loop 逐条发完 queue 残余（0~N frame）+ stopped + SENTINEL。
        #    用 deadline 循环 drain（残余 frame 可能很多）。
        stopped = None
        deadline = time.time() + 15.0
        while time.time() < deadline:
            msg = ws.receive_json()
            if msg.get('type') == 'stopped':
                stopped = msg
                break
        assert stopped is not None, 'should receive {type:stopped} after sending stop'
        assert stopped['reason'] == 'user_requested'

        # 5) WS 应关闭（再 receive 抛 WebSocketDisconnect）
        with pytest.raises((WebSocketDisconnect, Exception)):
            ws.receive_json()

    # 6) 进程清理：离开 with 块后等一小会儿，active_children 回落（无孤儿）。
    time.sleep(0.5)
    remaining = len(multiprocessing.active_children())
    assert remaining <= child_before, (
        f'orphan solve process: before={child_before}, after={remaining}')


# --------------------------------------------- AC-(2) 断连 → 清理不泄漏

def test_disconnect_without_stop_terminates_process(ws_client):
    """start 后直接断连 → 后端清理不泄漏（进程数回落，无孤儿）。

    - start 后收到 manifest + frame → 直接关 WS（不发 stop）；
    - 后端 read_loop 捕获 WebSocketDisconnect → terminate+join；
    - 离开 with 块后 active_children 回落到连接前水平。
    """
    child_before = len(multiprocessing.active_children())
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start_payload(time_budget=60, seed=2))
        manifest = ws.receive_json()
        assert manifest['type'] == 'manifest'
        frame = ws.receive_json()
        assert frame['type'] == 'frame'
        # 直接断连（不发 stop）—— 退出 with 块关 WS
    # with 退出后后端 read_loop 应捕获 disconnect → terminate process
    time.sleep(0.5)
    remaining = len(multiprocessing.active_children())
    assert remaining <= child_before, (
        f'orphan process after disconnect: before={child_before}, after={remaining}')


# --------------------------------------------- AC-(3) 回归：正常求解收 final

def test_normal_solve_without_stop_receives_final(ws_client):
    """不发 stop 正常求解 → 收到 manifest → frames → final（回归不破坏）。

    - 短预算（3s）确保测试快速完成；
    - 小问题（16 片）在 exploring 阶段每 ~3ms 吐一帧 → 3s 积攒 ~800+ frame；
      用 deadline 循环 drain frame 直到 final 到达；
    - 最终应收到 {type:'final'}，density 双口径字段齐全；
    - frame/final 字段与改造前一致（density 原面积口径、density_sparrow sparrow 自报）。
    """
    with ws_client.websocket_connect('/ws/solve') as ws:
        ws.send_json(_start_payload(time_budget=3, seed=3))

        manifest = ws.receive_json()
        assert manifest['type'] == 'manifest'
        total_area = manifest['total_area_mm2']
        gate = manifest['gate_mm']
        # 实际排料幅宽（density 分母口径）：= min(门幅, 绘图仪可写幅宽 1910)
        gate_nest = manifest['gate_nest_mm']
        assert total_area > 0 and gate > 0
        assert gate_nest == pytest.approx(min(gate, PLOT_SAFE_MAX_Y_MM))

        final = None
        frame_count = 0
        deadline = time.time() + 30.0
        while time.time() < deadline:
            msg = ws.receive_json()
            if msg['type'] == 'frame':
                frame_count += 1
                # density 双口径校验（抽检前 5 帧 + 后 5 帧，避免 800+ 帧全检拖慢）
                if frame_count <= 5 or frame_count % 100 == 0:
                    w = msg['width_mm']
                    expected = total_area / (w * gate_nest) if w > 0 else 0.0
                    assert msg['density'] == pytest.approx(expected, rel=1e-5)
                    assert msg['density_sparrow'] >= 0.0
            elif msg['type'] == 'final':
                final = msg
                break
            elif msg['type'] == 'error':
                pytest.fail(f'unexpected error: {msg}')

        assert final is not None, 'should receive final within 30s'
        assert frame_count >= 1, 'should receive at least one frame'
        assert final['n_frames'] >= 1
        assert final['n_eroded'] >= 0
        # final density 双口径
        fw = final['width_mm']
        expected = total_area / (fw * gate_nest) if fw > 0 else 0.0
        assert final['density'] == pytest.approx(expected, rel=1e-5)
        assert final['density_sparrow'] >= 0.0


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
