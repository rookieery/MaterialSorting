"""US-014 腰头成带 A/B 验收闭环测试。

两层：
1. 判据纯函数 —— pair_adjacency / band_span / span_ok / frame_signature /
   final_signature / artifact_replay_equal / export_verify（含 WB_ 泄漏哨兵）；
2. run_all 冒烟 —— 合成母版（同 test_waist_band_ws 的 g05 两码成对形态）秒级预算
   跑通全管线（A/B → 形态 → 确定性 → 导出 → 报告落盘），只验结构不验结论。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from materialsorting.web import band_accept as ba


def _piece(pid, label, size, w, h):
    return {
        'pid': pid, 'label': label, 'size': size,
        'polygon': [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]],
        'bbox': [0.0, 0.0, float(w), float(h)], 'area_mm2': float(w) * float(h),
        'n_verts': 4, 'allowed_angles': [0, 180],
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
    }


def _place(pid, x, y, rot=0.0):
    return {'id': pid, 'rotation': rot, 'translation': [float(x), float(y)]}


# ------------------------------------------------------------- pair_adjacency

def test_pair_adjacency_adjacent_along_short_axis():
    """100x50 片（w=短边 50）：短轴相邻（竖向叠放，边距 0）<= eps -> 100%。"""
    by_id = {'g05_31': _piece('g05_31', 'g05', 31, 100.0, 50.0)}
    placements = [_place('g05_31', 0, 0), _place('g05_31', 0, 50)]
    r = ba.pair_adjacency(placements, by_id)
    assert r['rate_pct'] == 100.0 and r['n_copies'] == 2 and r['pass'] is True
    assert r['worst_gap_mm'] <= ba.PAIR_EPS_MM


def test_pair_adjacency_head_to_tail_180_passes():
    """FR-8 头尾翻转 180° 成对（US-014 实测 g05_34 形态）：长片 (180x1100)
    上下头尾相接、物理边距 ~0 而中心距 ~1100 —— 边距口径必须判相邻（中心距
    口径的误判回归锁）。"""
    by_id = {'g05_34': _piece('g05_34', 'g05', 34, 180.0, 1100.0)}
    # 下片 rot=0 @ (0,0)：y 0..1100；上片 rot=180 @ (180, 2200)：y 1100..2200（头尾相接，边距 0）
    placements = [_place('g05_34', 0, 0), _place('g05_34', 180, 2200, rot=180.0)]
    r = ba.pair_adjacency(placements, by_id)
    assert r['rate_pct'] == 100.0 and r['pass'] is True
    assert r['worst_gap_mm'] <= ba.PAIR_EPS_MM
    assert r['worst_center_mm'] > 1000.0        # 中心距口径会误判（对照字段）


def test_pair_adjacency_scattered_fails():
    """同 pid 副本散落（边距远超 eps）-> 0% + worst_gap 量化超限。"""
    by_id = {'g05_31': _piece('g05_31', 'g05', 31, 100.0, 50.0)}
    placements = [_place('g05_31', 0, 0), _place('g05_31', 0, 5000)]
    r = ba.pair_adjacency(placements, by_id)
    assert r['rate_pct'] == 0.0 and r['pass'] is False
    assert r['worst_gap_mm'] == pytest.approx(4950.0, abs=0.1)


def test_pair_adjacency_three_copy_cluster_and_label_filter():
    """3 副本成簇（两两短轴相邻）-> 100%；label 过滤排除非带成员。"""
    by_id = {
        'g05_31': _piece('g05_31', 'g05', 31, 100.0, 50.0),
        'g01_31': _piece('g01_31', 'g01', 31, 100.0, 50.0),
    }
    placements = [
        _place('g05_31', 0, 0), _place('g05_31', 0, 50), _place('g05_31', 0, 100),
        _place('g01_31', 0, 0), _place('g01_31', 0, 9000),   # 散落但非带成员
    ]
    r = ba.pair_adjacency(placements, by_id, label='g05')
    assert r['n_copies'] == 3 and r['rate_pct'] == 100.0 and r['pass'] is True
    r_all = ba.pair_adjacency(placements, by_id)             # 全表口径含 g01 散落
    assert r_all['n_copies'] == 5 and r_all['rate_pct'] == 60.0


def test_pair_adjacency_no_pairs_vacuous():
    """全 demand=1（无多副本 pid）-> rate=None、pass=False（判据无分母不误报）。"""
    by_id = {'g05_31': _piece('g05_31', 'g05', 31, 100.0, 50.0)}
    r = ba.pair_adjacency([_place('g05_31', 0, 0)], by_id)
    assert r['rate_pct'] is None and r['n_copies'] == 0 and r['pass'] is False


def test_pair_adjacency_rotation_180_same_bbox():
    """180° 旋转副本 bbox 尺寸不变（中心距口径与朝向无关；旋转绕原点再平移，
    平移量需按旋转后 footprint 取，与 apply_transform 权威式一致）。"""
    by_id = {'g05_31': _piece('g05_31', 'g05', 31, 100.0, 50.0)}
    placements = [_place('g05_31', 0, 0), _place('g05_31', 100, 100, rot=180.0)]
    assert ba.pair_adjacency(placements, by_id)['pass'] is True


# ------------------------------------------------------------- band_span

def test_band_span_and_span_ok():
    by_id = {
        'g05_31': _piece('g05_31', 'g05', 31, 100.0, 50.0),
        'g01_31': _piece('g01_31', 'g01', 31, 800.0, 400.0),
    }
    placements = [
        _place('g05_31', 100, 200), _place('g05_31', 300, 200),
        _place('g01_31', 0, 0),                                # 非 label 不计
        _place('g05_31', 200, 500, rot=180.0),
    ]
    span = ba.band_span(placements, by_id, 'g05')
    assert span['width_mm'] == pytest.approx(300.0)
    assert span['height_mm'] == pytest.approx(300.0)   # y: 200..500（180° 片 [450,500]）
    assert span['n_members'] == 3
    assert ba.span_ok(span, {'width_mm': 300.0, 'height_mm': 300.0}) is True
    assert ba.span_ok(span, {'width_mm': 100.0, 'height_mm': 100.0}) is False
    assert ba.span_ok(None, None) is False


# ------------------------------------------------------------- 确定性签名

def test_signatures_ignore_wall_clock():
    f1 = {'density': 0.5, 'width_mm': 8000.0, 'placed_items': [_place('a', 1, 2)],
          'elapsed': 1.1, 'index': 0}
    f2 = {'density': 0.5, 'width_mm': 8000.0, 'placed_items': [_place('a', 1, 2)],
          'elapsed': 9.9, 'index': 0}
    assert ba.frame_signature([f1]) == ba.frame_signature([f2])
    f3 = {'density': 0.6, 'width_mm': 8000.0, 'placed_items': [], 'elapsed': 1.0}
    assert ba.frame_signature([f1]) != ba.frame_signature([f3])
    f1f = {'density': 0.5, 'width_mm': 8000.0, 'placed_items': [_place('a', 1, 2)],
           'elapsed': 3.0}
    assert ba.final_signature(f1f) == ba.final_signature(
        {'density': 0.5, 'width_mm': 8000.0, 'placed_items': [_place('a', 1, 2)],
         'elapsed': 77.0})
    assert ba.final_signature(None) is None


def test_frame_series_equal_tail_cutoff_rule():
    """wall-clock 截断尾帧规则：核心轨迹（min(n)-1 帧）相等 + 帧数差 <= 容差。

    US-014 实测形态：两跑 prefix 全等、仅截止快照尾帧漂移 1~3 帧（final 相等）。
    """
    def _frames(n, *, tail=None):
        out = [(round(0.5 + i * 0.001, 9), 8000.0, [_place('a', i, i)])
               for i in range(n)]
        if tail is not None:
            out[-1] = tail
        return out
    a, b = _frames(1167), _frames(1166, tail=(0.99, 8000.0, [_place('z', 9, 9)]))
    assert ba.frame_series_equal(a, b) is True            # 尾帧快照漂移（实测形态）
    assert ba.frame_series_equal(_frames(50), _frames(50)) is True
    # 核心帧分歧行（非末帧）→ False
    c = _frames(50); c[10] = (0.123, 8000.0, [_place('x', 0, 0)])
    assert ba.frame_series_equal(c, _frames(50)) is False
    # 帧数差超容差（大面积漂移）→ False
    assert ba.frame_series_equal(_frames(100), _frames(50)) is False


def test_artifact_replay_equal_excludes_band_elapsed(tmp_path):
    base = {'pid': 'WB_g05', 'members': [1, 2], 'fill_pct': 60.0}
    a = tmp_path / 'a.json'
    b = tmp_path / 'b.json'
    a.write_text(json.dumps({**base, 'band_elapsed': 1.0}), encoding='utf-8')
    b.write_text(json.dumps({**base, 'band_elapsed': 2.0}), encoding='utf-8')
    assert ba.artifact_replay_equal(a, b) is True
    b.write_text(json.dumps({**base, 'fill_pct': 61.0, 'band_elapsed': 2.0}),
                 encoding='utf-8')
    assert ba.artifact_replay_equal(a, b) is False
    assert ba.artifact_replay_equal(a, None) is False


# ------------------------------------------------------------- export_verify

def _fake_final(placements, width_mm=5000.0):
    return {'density': 0.85, 'width_mm': width_mm, 'placed_items': placements,
            'elapsed': 1.0}


def test_export_verify_ok_and_wb_leak(tmp_path):
    by_id = {'g05_31': _piece('g05_31', 'g05', 31, 100.0, 50.0)}
    r = ba.export_verify(_fake_final([_place('g05_31', 0, 0)]), by_id, 1980.0,
                         tmp_path, seed=0, stem='ok')
    assert r['pass'] is True and r['leak_warnings'] == [] and r['wb_in_placed'] == []
    assert r['dxf_is_r12_polyline'] is True and r['wb_in_dxf_plt_bytes'] == []
    for ext in ('png', 'dxf', 'plt'):
        assert (tmp_path / f'ok.{ext}').stat().st_size > 0
    # WB_ 泄漏：placed 含 WB_ 条目 -> 哨兵 warning + wb_in_placed 双重 fail
    r2 = ba.export_verify(_fake_final([_place('WB_g05', 0, 0)]), by_id, 1980.0,
                          tmp_path, seed=0, stem='leak')
    assert r2['pass'] is False and r2['wb_in_placed'] == ['WB_g05']
    assert any('WB_g05' in w for w in r2['leak_warnings'])


# ------------------------------------------------------------- run_all 冒烟

@pytest.fixture
def accept_env(monkeypatch, tmp_path):
    monkeypatch.setenv('MS_OUT_DIR', str(tmp_path))
    return tmp_path


def test_run_all_quick_smoke(accept_env, tmp_path):
    """秒级预算跑通全管线（合成 g05 两码 × demand2 成对形态）：只验结构与工件，
    不验验收结论（quick 档结论无意义）。main 6s：主解按 wall-clock 截断，2s 时
    小实例仍在改进中、两跑帧列可因机器负载漂移（确定性验收线在产品预算档 ——
    US-014 全量跑 120s×2 对拍 2015 帧全等）；6s 该 2 片实例已收敛、帧列稳定。"""
    pieces = [
        _piece('g05_28', 'g05', 28, 60.0, 300.0),
        _piece('g05_29', 'g05', 29, 60.0, 300.0),
        _piece('g01_28', 'g01', 28, 400.0, 500.0),
    ]
    report = ba.run_all(
        pieces, 1980.0, label='g05', sizes=(28, 29),
        quantities={'g05': {'28': 2, '29': 2}},
        seeds=(1,), main_time=6, band_time=2,
        report_path=tmp_path / 'report.json', export_dir=tmp_path / 'exports',
        log=lambda *_a, **_k: None)
    assert report['config']['label'] == 'g05'
    assert report['config']['params'] == ba.web_default_params()
    rows = report['density_ab']['per_seed']
    assert len(rows) == 1
    assert 'error' not in rows[0]['off'] and 'error' not in rows[0]['on']
    assert rows[0]['on']['stage']['fill_pct'] > 45
    form = report['form']['per_seed'][0]
    assert form['band_pair']['n_copies'] == 4            # 2 码 × demand 2
    assert form['span']['n_members'] == 4
    det = report['determinism']
    assert det['frames_equal'] is True and det['final_equal'] is True
    assert det['artifact_replay_equal'] is True
    assert det['artifact'] and Path(det['artifact']).exists()
    assert report['export']['on']['pass'] is True
    assert report['export']['off']['pass'] is True
    assert (tmp_path / 'report.json').exists()
    for arm in ('on', 'off'):
        for ext in ('png', 'dxf', 'plt'):
            assert (tmp_path / 'exports'
                    / f'band_accept_export_{arm}_seed1.{ext}').exists()
    # band_runs 工件落在 MS_OUT_DIR 隔离区（首跑 + 重跑各一件）
    arts = sorted((tmp_path / 'band_runs').glob('band_g05_seed1_*.json'))
    assert len(arts) >= 2
