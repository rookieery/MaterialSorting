"""Pytest 共享 fixture（US-025）。

测试需要的 intermediate JSON 走 ``real_or_synthetic_pieces`` fixture：优先读真实
``paths.INTERMEDIATE``，缺失则合成小尺寸合成数据，CI 无 intermediate 也能跑。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# 把 ``src/`` 加到 sys.path 让 ``from materialsorting...`` 在未 ``pip install -e .`` 时也能跑。
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _synthetic_pieces():
    """合成 2 个简单矩形裁片（不依赖 intermediate / sparrow 求解结果）。

    用于 multiprocessing 测试：picklable、体积小、求解极快（无旋转、无 erode）。
    """
    return [
        {
            'pid': 'TEST_A_28_L', 'ptype': 'TEST_A', 'size': 28, 'side': 'L', 'label': 'g01',
            'polygon': [[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]],
            'bbox': [0.0, 0.0, 500.0, 800.0], 'area_mm2': 400000.0, 'n_verts': 4,
            'allowed_angles': [0, 180],
            'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
        },
        {
            'pid': 'TEST_B_28_L', 'ptype': 'TEST_B', 'size': 28, 'side': 'L', 'label': 'g02',
            'polygon': [[0.0, 0.0], [300.0, 0.0], [300.0, 400.0], [0.0, 400.0]],
            'bbox': [0.0, 0.0, 300.0, 400.0], 'area_mm2': 120000.0, 'n_verts': 4,
            'allowed_angles': [0, 180],
            'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
        },
    ]


@pytest.fixture
def real_or_synthetic_pieces():
    """优先读真实 intermediate；缺失（CI / 全新 checkout 未上传母版 commit）则合成。

    返回 ``(pieces, gate_mm)``。合成数据 2 片、求解 <1s，适合多进程测试反复启动。
    """
    try:
        from materialsorting import paths
        inter_path = paths.INTERMEDIATE
        if os.path.exists(inter_path):
            with open(inter_path, encoding='utf-8') as f:
                doc = json.load(f)
            pieces = doc['pieces']
            # 取码 28 的子集加速测试（16 片求解 ~2s 内出 frame；多进程测试容忍）
            pieces_28 = [p for p in pieces if p.get('size') == 28]
            if pieces_28:
                return pieces_28, float(doc['gate_mm'])
    except Exception:
        pass
    return _synthetic_pieces(), 1980.0


@pytest.fixture
def synthetic_pieces():
    """总是合成数据（用于错误路径测试，确保不依赖真实 intermediate）。"""
    return _synthetic_pieces(), 1980.0
