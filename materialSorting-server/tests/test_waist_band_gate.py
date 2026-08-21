"""US-010 waist_band_gate 试点闸门测试。

覆盖（tasks/prd-waist-band.md US-010 验收标准 #4/#5 的可单测部分；三组实验
本体是分钟级真实求解，由 ``python -m materialsorting.nesting_engine.waist_band
_gate`` 现场跑 + ``out/config_runs/_probes/band_gate_report.json`` 落盘验收，
不进 pytest）：
1. 分层纯度：waist_band_gate.py 模块级不 import web/cli（AST 守卫，套路同
   test_waist_band.test_module_layering_purity）；
2. ``decide`` 三态矩阵：go / go-with-chunks / no-go（密度是硬闸门）；
3. ``fill_saturation`` 饱和点：平台 / 未饱和（最大 fill 在最大预算）/ 全失败；
4. 生产配置复现：P0 quantities 表 + 密度公式（87.446% @ 7758.41mm 复算）；
5. ``load_gate_pieces`` 非 5336 母版 fail-fast；``_downsample`` 上限保持尾点。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from materialsorting.nesting_engine import waist_band_gate as gate
from materialsorting.nesting_engine.waist_band_gate import (
    DENSITY_ACCEPT_PT,
    FILL_SATURATION_PT,
    NFP_DEGRADE_ACCEPT_PCT,
    decide,
    fill_saturation,
)


# --------------------------------------------------------------- 分层纯度

def test_module_layering_purity():
    """分层未反向：waist_band_gate.py 模块级 import 只向下/同层，禁 web/cli。"""
    src = Path(gate.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    allowed = {'__future__', 'argparse', 'json', 'os', 'statistics', 'sys',
               'threading', 'time', 'datetime', 'pathlib',
               'shapely', 'materialsorting',
               'nesting_bounds', 'nesting_engine'}
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert not mod.startswith(('materialsorting.web',
                                       'materialsorting.cli')), \
                '模块级禁止 import web/cli（分层单向）'
            # 相对 import（level>=1）解析到本包兄弟/父包 paths，视为同层合法
            names = {'nesting_engine'} if node.level else {mod.split('.')[0]}
        else:
            continue
        assert names <= allowed, sorted(names - allowed)
    # 源级哨兵：任何 web/cli 引用（含函数内延迟 import）都不允许
    assert 'materialsorting.web' not in src and 'materialsorting.cli' not in src
    assert 'from ..web' not in src and 'from ..cli' not in src


# ------------------------------------------------------------- 闸门决策纯函数

def test_decide_matrix():
    """三态：双过 go / 仅 NFP 挂 go-with-chunks / 密度挂（或双挂）no-go。"""
    assert decide(True, True)[0] == 'go'
    assert decide(True, False)[0] == 'go-with-chunks'
    assert decide(False, True)[0] == 'no-go'
    assert decide(False, False)[0] == 'no-go'
    # 结论文案区分路线指向
    assert 'US-011' in decide(True, False)[1]      # 分块路线
    assert 'US-015' in decide(False, True)[1]      # 混填料路线
    # 阈值口径锁定（PRD US-010 验收标准 #1/#2）
    assert DENSITY_ACCEPT_PT == 1.0
    assert NFP_DEGRADE_ACCEPT_PCT == 30.0


def test_fill_saturation_plateau():
    """平台：最大 fill 在非最大预算取得 -> 最小入窗预算即饱和点。"""
    pts = [{'budget_s': 5, 'fill_pct': 68.0},
           {'budget_s': 10, 'fill_pct': 70.1},
           {'budget_s': 15, 'fill_pct': 70.4},
           {'budget_s': 30, 'fill_pct': 70.5},
           {'budget_s': 60, 'fill_pct': 70.3}]
    sat, note = fill_saturation(pts)
    assert sat == 10                      # 70.1 >= 70.5 - 0.5
    assert note == ''
    assert FILL_SATURATION_PT == 0.5


def test_fill_saturation_not_plateaued():
    """未饱和：最大 fill 恰在最大预算取得 -> 该预算 + 上调注记。"""
    pts = [{'budget_s': 5, 'fill_pct': 66.0},
           {'budget_s': 10, 'fill_pct': 68.0},
           {'budget_s': 15, 'fill_pct': 70.0}]
    sat, note = fill_saturation(pts)
    assert sat == 15
    assert '未观测到饱和平台' in note


def test_fill_saturation_all_failed():
    """全失败点（band 构建异常入档）-> 无饱和点 + 错误注记。"""
    sat, note = fill_saturation([{'budget_s': 5, 'error': 'x'},
                                 {'budget_s': 10, 'error': 'y'}])
    assert sat is None
    assert '失败' in note


def test_fill_saturation_skips_error_points():
    """失败点跳过：只在成功点内标饱和。"""
    pts = [{'budget_s': 5, 'error': 'BandQualityError'},
           {'budget_s': 10, 'fill_pct': 70.0},
           {'budget_s': 15, 'fill_pct': 70.2}]
    sat, note = fill_saturation(pts)
    assert sat == 10
    assert '未观测到饱和平台' in note     # 70.2@15s 是最大


# ------------------------------------------------------------- 生产配置复现

def test_prod_config_matches_p0_probe():
    """P0 探针口径复现：119 副本 / total_area 12.958 m² / 密度公式 87.446%。"""
    qt = gate._prod_quantities()
    # 主表 g01~g05/g09/g10：31 码 1 份、36 码 3 份、其余 2 份；g06~g08 全 1 份
    assert qt['g05']['31'] == 1 and qt['g05']['36'] == 3
    assert qt['g05']['30'] == 2 and qt['g05']['40'] == 2
    assert all(v == 1 for v in qt['g06'].values())
    assert set(qt) == set(gate.PROD_PER_TYPE)
    # sizes 过滤后每主 g 码 = 1+2+2+2+2+3+2 = 14 副本，g06~g08 = 7 -> 119 总副本
    want = {int(s) for s in gate.PROD_SIZES}
    n = sum(qt[g][str(s)]
            for g in qt for s in want if str(s) in qt[g])
    assert n == 119
    # 密度公式与 P0（87.45% @ 7758.41mm）复算一致（分母 = min(gate,1910)）
    pct = gate._real_density_pct(12958313.5, 7758.41, 1910.0)
    assert pct == pytest.approx(87.446, abs=0.01)


def test_load_gate_pieces_rejects_non_5336(tmp_path):
    """闸门绑定 5336 母版：其他源 fail-fast（防跨母版误用结论）。"""
    doc = {'source': 'M1787_x.dxf', 'gate_mm': 1980.0, 'pieces': []}
    p = tmp_path / 'other_intermediate.json'
    p.write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(RuntimeError, match='5336'):
        gate.load_gate_pieces(str(p))


def test_downsample_caps_and_keeps_tail():
    """收敛曲线降采样：<=cap 点、保尾点（报告可读性，不参与判据）。"""
    frames = [{'elapsed': float(i), 'density': 0.5 + i / 1000,
               'width_mm': 7000.0 - i} for i in range(1500)]
    out = gate._downsample(frames, cap=200)
    assert len(out) <= 200
    assert out[-1] is frames[-1]
    assert out[0] is frames[0]
    assert gate._downsample(frames[:10], cap=200) == frames[:10]
