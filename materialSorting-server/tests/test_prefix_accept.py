"""US-005 起始端成套前后幅 A/B 验收闭环测试。

两层：
1. 判据纯函数 —— prefix_form（同码/布头/竖排贴触/头尾 180° 交替四子判据）/
   frame_series_equal（wall-clock 速率截断规则：核心轨迹硬判 + 帧数差相对
   护栏）/ final_best_equal（可达最优密度重现）/ artifact_replay_equal
   （墙钟 + 主解结局字段排除的构造回放对拍）/ export_verify（PS_ 泄漏哨兵）；
2. run_all 冒烟 —— 合成母版（同 test_prefix_ws 的 g02/g03 2+2 结构 + g05 双开）
   秒级预算跑通全管线（A/B → 双开 → 形态 → 确定性 → 导出 → 报告落盘），验
   结构与刚性不变量，不验密度结论（quick 档结论无意义）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from materialsorting.web import prefix_accept as pa


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


_BY_ID = {
    'g02_34': _piece('g02_34', 'g02', 34, 300.0, 400.0),
    'g03_34': _piece('g03_34', 'g03', 34, 320.0, 420.0),
    'g01_34': _piece('g01_34', 'g01', 34, 100.0, 100.0),
}


def _stack_placements(dx=0.0):
    """交错咬合竖排 4 成员（前 2 后 2 同码 34、相邻 y 交集 40mm、rot 0/180 交替）。

    世界 bbox 链（min_y 序）：g02[0,400] / g03[380,800] / g02[760,1160] /
    g03[1120,1540] —— 相邻对 y 交集均 40mm 且 2D 重叠（gaps=0）；rot 沿竖排
    序 0/180/0/180。
    """
    return [
        _place('g02_34', 0 + dx, 0, rot=0.0),
        _place('g03_34', 500 + dx, 800, rot=180.0),
        _place('g02_34', 100 + dx, 760, rot=0.0),
        _place('g03_34', 500 + dx, 1540, rot=180.0),
        _place('g01_34', 900 + dx, 0),            # 干扰片（非成员，须被过滤）
    ]


# ------------------------------------------------------------- prefix_form

def test_prefix_form_pass_interleaved_stack():
    """四子判据全真：同码 2+2 / min_x<=6 / 相邻 y 交集>0 且缝隙<=1mm / rot 差≈180°。"""
    r = pa.prefix_form(_stack_placements(), _BY_ID, 'g02', 'g03', 34)
    assert r['same_code'] is True and r['n_front'] == 2 and r['n_back'] == 2
    assert r['head_ok'] is True and r['min_x_mm'] <= pa.HEAD_EPS_MM
    assert r['stack_ok'] is True
    assert r['y_overlap_mm'] == [20.0, 40.0, 40.0]   # g03 高 420：首对 400-380=20
    assert r['gaps_mm'] == [0.0, 0.0, 0.0]
    assert r['rot_ok'] is True and r['rot_diff_deg'] == [180.0, 180.0, 180.0]
    assert r['interleave'] is True
    assert r['order'] == ['g02_34', 'g03_34', 'g02_34', 'g03_34']  # 构造序保留
    assert r['pass'] is True


def test_prefix_form_head_offset_fails():
    """整簇离布头 50mm（模拟未锚定解）-> head_ok False（其余子判据刚性不变）。"""
    r = pa.prefix_form(_stack_placements(dx=50.0), _BY_ID, 'g02', 'g03', 34)
    assert r['same_code'] and r['stack_ok'] and r['rot_ok']
    assert r['head_ok'] is False and r['min_x_mm'] == pytest.approx(50.0, abs=0.1)
    assert r['pass'] is False


def test_prefix_form_scattered_member_fails():
    """末成员散落 4000mm 外 -> y 交集<0 且缝隙超限 -> stack_ok False。"""
    placed = _stack_placements()
    placed[3] = _place('g03_34', 500, 5400, rot=180.0)
    r = pa.prefix_form(placed, _BY_ID, 'g02', 'g03', 34)
    assert r['same_code'] is True and r['head_ok'] is True
    assert r['stack_ok'] is False
    assert any(g > pa.GAP_EPS for g in r['gaps_mm'])
    assert r['pass'] is False


def test_prefix_form_no_alternation_fails():
    """相邻成员同朝向（rot 差 0）-> rot_ok False（头尾交替判据回归锁）。"""
    placed = _stack_placements()
    # 第二成员转正放（rot 0 @ (200,380)：y[380,800] 与原 rot180 带同区间、
    # 与上下邻 2D 仍重叠 —— 只改朝向不改贴触链）。
    placed[1] = _place('g03_34', 200, 380, rot=0.0)
    r = pa.prefix_form(placed, _BY_ID, 'g02', 'g03', 34)
    assert r['same_code'] and r['head_ok'] and r['stack_ok']
    assert r['rot_ok'] is False and 0.0 in r['rot_diff_deg']
    assert r['pass'] is False


def test_prefix_form_count_and_size_mismatch():
    """副本不齐（前幅仅 1 条）与 size 不符（off 臂无成员）两态。"""
    placed = _stack_placements()[:4]
    placed[2] = _place('g01_34', 100, 760)             # 第 3 成员换成非成员 pid
    r = pa.prefix_form(placed, _BY_ID, 'g02', 'g03', 34)
    assert r['n_front'] == 1 and r['same_code'] is False and r['pass'] is False
    r2 = pa.prefix_form(_stack_placements(), _BY_ID, 'g02', 'g03', 33)
    assert r2['n_front'] == 0 and r2['n_back'] == 0
    assert not (r2['same_code'] or r2['head_ok'] or r2['stack_ok'] or r2['rot_ok'])
    assert r2['pass'] is False


# ------------------------------------------------------------- 确定性签名

def test_signatures_ignore_wall_clock():
    f1 = {'density': 0.5, 'width_mm': 8000.0, 'placed_items': [_place('a', 1, 2)],
          'elapsed': 1.1, 'index': 0}
    f2 = {'density': 0.5, 'width_mm': 8000.0, 'placed_items': [_place('a', 1, 2)],
          'elapsed': 9.9, 'index': 0}
    assert pa.frame_signature([f1]) == pa.frame_signature([f2])
    f3 = {'density': 0.6, 'width_mm': 8000.0, 'placed_items': [], 'elapsed': 1.0}
    assert pa.frame_signature([f1]) != pa.frame_signature([f3])
    assert pa.final_signature(f1) == pa.final_signature(
        {'density': 0.5, 'width_mm': 8000.0, 'placed_items': [_place('a', 1, 2)],
         'elapsed': 77.0})
    assert pa.final_signature(None) is None


def test_frame_series_equal_rate_cutoff_rule():
    """wall-clock 速率截断规则：核心轨迹（min(n)-1 帧）逐帧相等 + 帧数差为
    **相对**护栏（实测背靠背 1038==1038 全等；13 臂连跑热态 972/1036=6.6%
    内容仍对齐 —— 内容确定、只有截断帧位随速率漂移）。"""

    def _frames(n, *, tail=None):
        out = [(round(0.5 + i * 0.001, 9), 8000.0, [_place('a', i, i)])
               for i in range(n)]
        if tail is not None:
            out[-1] = tail
        return out

    assert pa.frame_series_equal(_frames(1038), _frames(1038)) is True
    # 速率漂移实测形态：短列是长列确定前缀（972 vs 1036 = 6.6% <= 12%）
    assert pa.frame_series_equal(_frames(972), _frames(1036)) is True
    a, b = _frames(1167), _frames(1166, tail=(0.99, 8000.0, [_place('z', 9, 9)]))
    assert pa.frame_series_equal(a, b) is True          # 尾帧快照漂移（内容同）
    c = _frames(50)
    c[10] = (0.123, 8000.0, [_place('x', 0, 0)])        # 核心帧分歧行
    assert pa.frame_series_equal(c, _frames(50)) is False
    assert pa.frame_series_equal(_frames(100), _frames(50)) is False  # 差 50% 超护栏
    # 恰在护栏边界内/外（12%）
    assert pa.frame_series_equal(_frames(100), _frames(88)) is True
    assert pa.frame_series_equal(_frames(100), _frames(87)) is False


def test_final_best_equal_snapshot_physics():
    """final 对拍双口径：快照逐字段（信息）与「可达最优密度」重现（判据）。"""

    def _frames(dens):
        return [{'density': d, 'width_mm': 8000.0,
                 'placed_items': [_place('a', 1, 2)], 'elapsed': 1.0}
                for d in dens]

    f_hi = {'density': 0.886, 'width_mm': 8000.0, 'placed_items': [], 'elapsed': 9.0}
    f_lo = {'density': 0.885, 'width_mm': 7900.0, 'placed_items': [], 'elapsed': 9.0}
    # 快照不同（截断落点漂移），best-so-far 一致（0.8860 vs 0.8860）
    assert pa.final_best_equal(f_hi, f_lo, frames_a=_frames([0.88, 0.886]),
                               frames_b=[*_frames([0.88, 0.885]), *_frames([0.886])]) is True
    # best 差 0.15pt > 0.1pt ε —— 可达最优不可重现，FAIL
    assert pa.final_best_equal(f_hi, f_lo, frames_a=_frames([0.886]),
                               frames_b=_frames([0.8845])) is False
    assert pa.final_best_equal(f_hi, None) is False
    assert pa.final_best_equal(f_hi, f_hi, frames_a=[], frames_b=[]) is False


def test_artifact_replay_equal_excludes_wall_clock(tmp_path):
    """prefix_runs 工件构造回放对拍：墙钟（ts/stage_elapsed）与主解结局字段
    （pin/band_pos/width_mm —— 随截断快照漂移）排除，构造段逐键相等。"""
    base = {'pid': 'PS_g02+g03@34', 'size': 34, 'pin': {'skipped': True},
            'chunk': {'members': [1, 2, 3, 4]}}
    a = tmp_path / 'a.json'
    b = tmp_path / 'b.json'
    a.write_text(json.dumps({**base, 'ts': 'T1', 'stage_elapsed': 1.0}),
                 encoding='utf-8')
    b.write_text(json.dumps({**base, 'ts': 'T2', 'stage_elapsed': 2.0}),
                 encoding='utf-8')
    assert pa.artifact_replay_equal(a, b) is True
    # pin.a / band_pos / width_mm = 主解结局快照（速率漂移），不入构造判据
    b.write_text(json.dumps({**base, 'pin': {'skipped': True, 'a': 0.9},
                             'band_pos': {'min_x': 1171.0}, 'width_mm': 7760.5,
                             'ts': 'T2', 'stage_elapsed': 2.0}), encoding='utf-8')
    assert pa.artifact_replay_equal(a, b) is True
    b.write_text(json.dumps({**base, 'size': 35, 'ts': 'T2', 'stage_elapsed': 2.0}),
                 encoding='utf-8')
    assert pa.artifact_replay_equal(a, b) is False
    assert pa.artifact_replay_equal(a, None) is False


# ------------------------------------------------------------- export_verify

def _fake_final(placements, width_mm=5000.0):
    return {'density': 0.85, 'width_mm': width_mm, 'placed_items': placements,
            'elapsed': 1.0}


def test_export_verify_ok_and_ps_leak(tmp_path):
    by_id = {'g02_34': _BY_ID['g02_34']}
    r = pa.export_verify(_fake_final([_place('g02_34', 0, 0)]), by_id, 1980.0,
                         tmp_path, seed=0, stem='ok')
    assert r['pass'] is True and r['leak_warnings'] == [] and r['ps_in_placed'] == []
    assert r['dxf_is_r12_polyline'] is True and r['ps_in_dxf_plt_bytes'] == []
    for ext in ('png', 'dxf', 'plt'):
        assert (tmp_path / f'ok.{ext}').stat().st_size > 0
    # PS_ 泄漏：placed 含 PS_ 条目 -> 哨兵 warning + ps_in_placed 双重 fail
    r2 = pa.export_verify(_fake_final([_place('PS_g02+g03@34', 0, 0)]), by_id,
                          1980.0, tmp_path, seed=0, stem='leak')
    assert r2['pass'] is False and r2['ps_in_placed'] == ['PS_g02+g03@34']
    assert any('PS_g02+g03@34' in w for w in r2['leak_warnings'])


# ------------------------------------------------------------- P0 口径数据源

def test_p0_per_type_loads_and_validates(tmp_path, monkeypatch):
    """P0 口径 per_type：真实配置可读（g02/g03 d=2 —— PRD d_g=max 口径源），
    坏文件/坏条目 fail-fast。"""
    per_type = pa.p0_per_type()
    assert per_type['g02'] == {'d': 2.0, 'tol': 1.0}
    assert per_type['g03'] == {'d': 2.0, 'tol': 1.0}
    assert len(per_type) >= 10                       # g01..g10 全码在场
    bad = tmp_path / 'bad.json'
    for payload in ('{}', '{"per_type": []}', '{"per_type": {"g02": {"d": "x"}}}'):
        bad.write_text(payload, encoding='utf-8')
        with pytest.raises(RuntimeError):
            pa.p0_per_type(bad)
    with pytest.raises(RuntimeError):
        pa.p0_per_type(tmp_path / 'missing.json')


# ------------------------------------------------------------- run_all 冒烟

@pytest.fixture
def accept_env(monkeypatch, tmp_path):
    monkeypatch.setenv('MS_OUT_DIR', str(tmp_path))
    return tmp_path


def test_run_all_quick_smoke(accept_env, tmp_path):
    """秒级预算跑通全管线（合成 g02/g03 两码 2+2 + g05 双开）：验结构与刚性
    不变量（形态/确定性/导出/带位），不验密度结论（quick 档结论无意义）。
    main 6s：主解按 wall-clock 截断，合成实例已收敛、帧列稳定（band_accept
    同款口径）。"""
    pieces = [
        _piece('g02_28', 'g02', 28, 300.0, 400.0),
        _piece('g03_28', 'g03', 28, 320.0, 420.0),
        _piece('g02_29', 'g02', 29, 300.0, 400.0),
        _piece('g03_29', 'g03', 29, 320.0, 420.0),
        _piece('g01_28', 'g01', 28, 400.0, 500.0),
        _piece('g05_28', 'g05', 28, 60.0, 300.0),
        _piece('g05_29', 'g05', 29, 60.0, 300.0),
    ]
    qty = {'g02': {'28': 2, '29': 2}, 'g03': {'28': 2, '29': 2},
           'g01': {'28': 1}, 'g05': {'28': 2, '29': 2}}
    report = pa.run_all(
        pieces, 1980.0, sizes=(28, 29), quantities=qty,
        seeds=(1,), dual_seeds=(1,), main_time=6,
        report_path=tmp_path / 'report.json', export_dir=tmp_path / 'exports',
        log=lambda *_a, **_k: None)
    assert report['config']['front'] == 'g02' and report['config']['back'] == 'g03'
    assert report['config']['params'] == pa.web_default_params()
    rows = report['density_ab']['per_seed']
    assert len(rows) == 1
    assert 'error' not in rows[0]['off'] and 'error' not in rows[0]['on']
    assert rows[0]['on']['size'] in (28, 29)
    form = report['form']['per_seed'][0]
    assert form['same_code'] and form['rot_ok'] and form['interleave'] is True
    # 合成矩形数据贴触形态 = y 恰好邻接（交集 0，真实 5336 几何为交错咬合 >0，
    # 见纯函数用例与 US-005 真实报告）；缝隙与刚性子判据仍须全过。
    assert all(g <= pa.GAP_EPS for g in form['gaps_mm'])
    assert all(ov >= 0.0 for ov in form['y_overlap_mm'])
    assert form['head_ok'] is True         # 布头由 pin 守卫构造性保证（US-002）
    dual = report['dual_open']['per_seed'][0]
    assert 'error' not in dual['band_only'] and 'error' not in dual['dual']
    assert dual['band_pos'] and dual['band_pos']['pid'].startswith('WB_')
    assert dual['dual']['size'] in (28, 29)
    det = report['determinism']
    assert det['size_equal'] is True
    assert det['frames_equal'] is True and det['final_best_equal'] is True
    assert det['best_density_run1'] == pytest.approx(det['best_density_run2'],
                                                    abs=0.1)
    assert det['artifact_replay_equal'] is True
    assert det['artifact'] and Path(det['artifact']).exists()
    assert report['export']['on']['pass'] is True
    assert report['export']['off']['pass'] is True
    assert (tmp_path / 'report.json').exists()
    for arm in ('on', 'off'):
        for ext in ('png', 'dxf', 'plt'):
            assert (tmp_path / 'exports'
                    / f'prefix_accept_export_{arm}_seed1.{ext}').exists()
    # prefix_runs 工件落在 MS_OUT_DIR 隔离区（on 首跑 + 双开 + 重跑各一件）
    arts = sorted((tmp_path / 'prefix_runs').glob('*_PS_g02+g03@*.json'))
    assert len(arts) >= 3
