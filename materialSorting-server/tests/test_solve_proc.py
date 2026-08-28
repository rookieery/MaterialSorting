"""US-025 多进程求解 worker + solve_with_callback_proc 单测。

4 项核心场景（spec AC#7）：
  1. 正常求解：收到 manifest + frame* + final，density 双口径正确；
  2. start -> terminate：父进程 5s 内返回、不 hang；
  3. 子进程 build_instance 抛错 -> 父进程收到 error；
  4. 子进程被外部 kill -> 父进程不 hang、err 记 exitcode。

Windows spawn 注意：``solve_worker`` 是顶层函数（无闭包），参数全 JSON 可序列化 ->
可 pickle。测试本身不创建模块级 Process，pytest import 时不触发 spawn。
"""
from __future__ import annotations

import multiprocessing
import time

import pytest

from materialsorting.web.solve_worker import solve_worker
from materialsorting.web.solver import solve_with_callback_proc


# --------------------------------------------- AC#7-(1) 正常求解


def test_normal_solve_manifest_frame_final_density_dual(real_or_synthetic_pieces):
    """正常求解收到 manifest + frame* + final；density 双口径换算正确。

    - manifest 先于 frame 到达（顺序保证）；
    - 每个 frame 同时含 density（原面积口径）与 density_sparrow（sparrow 自报）；
    - final.density 与单进程期望一致：density == total_area / (width * gate)
      （输入门幅口径：求解约束带 = 密度分母）。
    """
    pieces, gate_mm = real_or_synthetic_pieces
    manifests: list = []
    frames: list = []

    def on_manifest(m):
        manifests.append(m)

    def on_report(r):
        frames.append(r)

    proc, final, elapsed, err = solve_with_callback_proc(
        pieces, gate_mm,
        {"time_budget": 2, "seed": 1},
        on_manifest=on_manifest, on_report=on_report,
    )

    assert err is None, f"unexpected error: {err}"
    assert final is not None, "final must be present on normal solve"
    assert len(manifests) == 1, "manifest should arrive exactly once"
    assert len(frames) >= 1, "should receive at least one frame"

    # 顺序：manifest 必须先于 frame（同一 queue，FIFO 保证）
    m = manifests[0]
    total_area = float(m["total_area"])
    assert total_area > 0
    assert m["gate_mm"] == pytest.approx(gate_mm)
    assert isinstance(m["pid_meta"], dict) and len(m["pid_meta"]) >= 1

    # 每个 frame 双口径换算校验：density == total_area/(width*gate)
    for f in frames:
        assert "density" in f and "density_sparrow" in f
        expected = total_area / (f["width_mm"] * gate_mm)
        assert f["density"] == pytest.approx(expected, rel=1e-6), (
            f"density real={f['density']} expected={expected}")
        # sparrow 自报口径非负（无 erode 时与真实口径浮点近似相等；
        # erode 后 sparrow 报更小；不强制排序避免浮点误差误报）
        assert f["density_sparrow"] >= 0.0
        # placed_items 结构可序列化
        for pi in f["placed_items"]:
            assert set(pi.keys()) >= {"id", "rotation", "translation"}
            assert len(pi["translation"]) == 2

    # final 也有双口径
    assert "density" in final and "density_sparrow" in final
    assert final["density"] == pytest.approx(
        total_area / (final["width_mm"] * gate_mm), rel=1e-6)
    # final.width_mm <= 任意中间 frame.width_mm（收敛）
    assert final["width_mm"] <= max(f["width_mm"] for f in frames) + 1e-6
    assert elapsed > 0
    assert proc.exitcode == 0


# --------------------------------------------- AC#7-(2) terminate


def test_terminate_returns_within_5s(real_or_synthetic_pieces):
    """start -> terminate -> 父进程 5s 内返回、不 hang。

    用 on_report 在首帧触发子进程 terminate（模拟 US-026 stop 协议），
    断言 solve_with_callback_proc 在 5s 内返回，final 为 None，err 记录 worker 异常退出。
    """
    pieces, gate_mm = real_or_synthetic_pieces
    terminate_fired = {"v": False}

    def on_manifest(m):
        pass

    def on_report(r):
        if not terminate_fired["v"]:
            terminate_fired["v"] = True
            # 找到 solve 子进程（multiprocessing 仅有这一个 active child）并 terminate
            for child in multiprocessing.active_children():
                child.terminate()

    t0 = time.time()
    proc, final, elapsed, err = solve_with_callback_proc(
        pieces, gate_mm,
        # 长预算确保被终止前不会自然结束
        {"time_budget": 60, "seed": 1},
        on_manifest=on_manifest, on_report=on_report,
    )
    dt = time.time() - t0

    assert dt < 5.0, f"parent did not return within 5s (took {dt:.2f}s)"
    assert final is None, "final must be None on terminate"
    assert err is not None, "err should be set when worker was terminated"
    assert proc.exitcode != 0, f"exitcode should be nonzero on terminate, got {proc.exitcode}"


# --------------------------------------------- AC#7-(3) build_instance 抛错


def test_build_instance_error_returns_error_message(synthetic_pieces):
    """子进程 build_instance 抛错 -> 父进程收到 {kind:error} 消息，err 非空。

    构造 polygon=None 的非法 piece 触发 build_instance 内 len(None) 抛 TypeError。
    断言：5s 内返回、final=None、err 含中文「构造实例失败」前缀（solve_worker 投递）。
    """
    pieces, gate_mm = synthetic_pieces
    bad_pieces = [{**pieces[0], "polygon": None}]

    received_manifest = {"v": False}
    received_frame = {"v": False}

    def on_manifest(m):
        received_manifest["v"] = True

    def on_report(r):
        received_frame["v"] = True

    t0 = time.time()
    proc, final, elapsed, err = solve_with_callback_proc(
        bad_pieces, gate_mm,
        {"time_budget": 1, "seed": 1},
        on_manifest=on_manifest, on_report=on_report,
    )
    dt = time.time() - t0

    assert dt < 5.0, f"parent did not return within 5s (took {dt:.2f}s)"
    assert final is None
    assert received_manifest["v"] is False, "manifest must NOT be sent on build_instance error"
    assert received_frame["v"] is False
    assert err is not None
    # solve_worker 投递的中文前缀
    assert "构造实例失败" in err, f"err should mention build failure, got: {err!r}"


# --------------------------------------------- AC#7-(4) 子进程被外部 kill


def test_external_kill_does_not_hang(real_or_synthetic_pieces):
    """子进程被外部 kill（未投 error，模拟 Rust panic / OS kill）-> 父进程不 hang。

    用 on_report 在首帧调 child.kill() 强杀子进程（比 terminate 更暴力）。
    断言：父进程 5s 内返回、final=None、err 含「unexpectedly」或「exited」。
    """
    pieces, gate_mm = real_or_synthetic_pieces
    killed = {"v": False}

    def on_manifest(m):
        pass

    def on_report(r):
        if not killed["v"]:
            killed["v"] = True
            for child in multiprocessing.active_children():
                try:
                    child.kill()
                except Exception:
                    child.terminate()

    t0 = time.time()
    proc, final, elapsed, err = solve_with_callback_proc(
        pieces, gate_mm,
        {"time_budget": 60, "seed": 1},
        on_manifest=on_manifest, on_report=on_report,
    )
    dt = time.time() - t0

    assert dt < 5.0, f"parent did not return within 5s (took {dt:.2f}s)"
    assert final is None
    assert err is not None
    assert "unexpectedly" in err or "exited" in err, (
        f"err should mention unexpected exit, got: {err!r}")
    assert proc.exitcode != 0


# --------------------------------------------- 附加：solve_worker 可 pickle


def test_solve_worker_is_picklable_top_level_function():
    """solve_worker 是顶层函数（无闭包），Windows spawn 可 pickle。

    multiprocessing.Process 在 spawn 模式下需要 pickle target；这里直接断言可 pickle
    + 模块路径正确（来自 materialsorting.web.solve_worker，非 __main__）。
    """
    import pickle
    blob = pickle.dumps(solve_worker)
    restored = pickle.loads(blob)
    assert restored is solve_worker
    assert solve_worker.__module__ == "materialsorting.web.solve_worker"
    assert solve_worker.__qualname__ == "solve_worker"


# --------------------------------------------- 求解约束带口径（输入门幅即实际幅宽）


def test_build_instance_strip_matches_input_gate(real_or_synthetic_pieces):
    """strip_height = 门幅原样：2026-08-28 版师定案后无 1910 钳制，小门幅不放大。

    输入幅宽 = 实际幅宽单一口径（求解约束带 / density 分母 / 导出边界同源）；
    manifest 仍报传入门幅（gate_mm 字段语义不变）。历史上 1980 曾钳到 1910
    （绘图仪可写幅宽，70mm 内部差），随钳制移除回归「门幅即约束带」。
    """
    from materialsorting.web.solver import build_instance

    pieces, _gate = real_or_synthetic_pieces
    inst, _cfg, _meta, _area, _n_er = build_instance(
        pieces, 1980.0, time_budget=1, seed=0)
    assert inst.strip_height == pytest.approx(1980.0)                # 门幅原样

    inst_small, *_ = build_instance(pieces, 1500.0, time_budget=1, seed=0)
    assert inst_small.strip_height == pytest.approx(1500.0)          # 小门幅不放大


if __name__ == "__main__":
    # Windows multiprocessing 守卫：直接 python tests/test_solve_proc.py 时
    # 走 pytest CLI（不在 __main__ 里直接 Process，避免无限 spawn）。
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
