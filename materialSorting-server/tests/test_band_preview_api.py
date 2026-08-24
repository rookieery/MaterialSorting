"""POST /api/band-preview 成带预览端点测试（TestClient 套路，镜像 test_waist_band_ws）。

覆盖（2026-08-24 布局设置缩略图换成带预览）：
1. ok:true 全链路：members 逐副本（demand 守恒）、polygon 已减 offset 归一（≥0）、
   颜色 = size_color 同码同色、outline = erode 后组合片外轮廓、响应全文无 WB_（哨兵）；
2. sizes 过滤 + quantities 副本数生效（2 副本 → 该 pid 出现 2 条）；
3. band 校验复用 _parse_band：未开启 / label 不存在 / 数量全 0 → ok:false + 原文案；
4. DegenerateBand（总副本 1）/ 灾难守卫 → ok:false「成带失败」前置（不抛 500）；
5. 空 state → ok:false「排料数据为空」。

合成数据同 test_waist_band_ws（g05 两码 60×300 矩形腰片 × demand 2 + g06 单片）。
"""
from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from materialsorting.web import server as server_mod
from materialsorting.web.server import app


def _piece(pid, label, size, w, h):
    """合成 v2 schema 裁片（矩形原轮廓，与 test_waist_band_ws 同构）。"""
    return {
        'pid': pid, 'label': label, 'size': size,
        'polygon': [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]],
        'bbox': [0.0, 0.0, float(w), float(h)], 'area_mm2': float(w) * float(h),
        'n_verts': 4, 'allowed_angles': [0, 180],
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
    }


def _band_pieces():
    """合成母版：g05 两码 60×300 腰片（成带主角）、g01 普通大片、g06 30×559 裤耳类。"""
    return [
        _piece('g05_28', 'g05', 28, 60.0, 300.0),
        _piece('g05_29', 'g05', 29, 60.0, 300.0),
        _piece('g01_28', 'g01', 28, 400.0, 500.0),
        _piece('g06_28', 'g06', 28, 30.0, 559.0),
    ]


@pytest.fixture
def band_client(monkeypatch):
    """注入合成 pieces state（原位 clear+update，teardown 恢复真实 state）。"""
    pieces = _band_pieces()
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update({
        'doc': {'source': 'synthetic_band.dxf'},
        'gate_mm': 1980.0,
        'pieces': pieces,
        'pieces_by_id': {p['pid']: p for p in pieces},
    })
    with TestClient(app) as client:
        yield client
    state.clear()
    state.update(saved)


def _preview(client, **payload):
    """POST /api/band-preview（band 键默认开启 g05）。"""
    body = {'band': {'enabled': True, 'label': 'g05'}, **payload}
    return client.post('/api/band-preview', json=body)


# ------------------------------------------------------------- ok:true 全链路


def test_band_preview_ok_full_payload(band_client):
    resp = _preview(band_client, quantities={'g05': {'28': 2, '29': 2}})
    assert resp.status_code == 200
    data = resp.json()
    assert data['ok'] is True
    assert data['label'] == 'g05'
    assert data['n_members'] == 4
    # 副本守恒：demand=2 → 每 pid 恰 2 条成员（尺寸重复出现）
    pids = [m['pid'] for m in data['members']]
    assert pids.count('g05_28') == 2 and pids.count('g05_29') == 2
    # 颜色 = size_color 同码同色（跨成员一致），且 28/29 两码不同色（16 色循环表）
    colors = {m['size']: m['color'] for m in data['members']}
    assert len({m['color'] for m in data['members'] if m['size'] == 28}) == 1
    assert colors[28] != colors[29]
    # polygon 已减 offset 归一（min ≥ -0.01 容浮点噪声）；顶点数 = 原轮廓 4 点
    for m in data['members']:
        assert len(m['polygon']) == 4
        assert min(x for x, _y in m['polygon']) >= -0.01
        assert min(y for _x, y in m['polygon']) >= -0.01
    # outline 非空闭合轮廓；bbox 与统计字段在场
    assert len(data['outline']) >= 3
    assert data['bbox']['width_mm'] > 0 and data['bbox']['height_mm'] > 0
    assert data['fill_pct'] > 0
    # 哨兵：响应全文无 WB_（组合片 pid 永不出现在前端契约）
    assert 'WB_' not in json.dumps(data)


def test_band_preview_sizes_filter_and_gate(band_client):
    """sizes 过滤生效（sizes=['28'] → 只 28 码成员）+ gate_mm 透传不炸。"""
    resp = _preview(band_client,
                    sizes=[28],
                    quantities={'g05': {'28': 2, '29': 2}},
                    gate_mm=1500)
    data = resp.json()
    assert data['ok'] is True
    assert {m['size'] for m in data['members']} == {28}


# ------------------------------------------------------------- ok:false 分支


@pytest.mark.parametrize('band,quantities,frag', [
    ({'enabled': False, 'label': 'g05'}, None, 'band 未开启'),
    ({'enabled': True, 'label': 'g99'}, None, '不存在于当前母版'),
    ({'enabled': True, 'label': 'g05'}, {'g05': {'28': 0, '29': 0}}, '数量全为 0'),
])
def test_band_preview_validation(band_client, band, quantities, frag):
    """band 校验复用 _parse_band 单一校验点 → ok:false + 同款文案（200 包络）。"""
    resp = band_client.post('/api/band-preview',
                            json={'band': band, 'quantities': quantities})
    assert resp.status_code == 200
    data = resp.json()
    assert data['ok'] is False and frag in data['error']


def test_band_preview_degenerate_single_copy(band_client):
    """总副本 1（DegenerateBand）→ ok:false「成带失败」前置到选码时刻（不抛 500）。"""
    resp = band_client.post('/api/band-preview', json={
        'band': {'enabled': True, 'label': 'g06'},
        'quantities': {'g06': {'28': 1}},
    })
    data = resp.json()
    assert data['ok'] is False
    assert '成带失败' in data['error'] and '总副本 1' in data['error']


def test_band_preview_empty_state(band_client):
    """空 state（首次启动未 commit）→ ok:false「排料数据为空」（不炸不 500）。"""
    state = server_mod._PIECES_STATE          # band_client 已存快照，teardown 恢复
    saved = dict(state)
    state.clear()
    try:
        resp = _preview(band_client)
        data = resp.json()
        assert resp.status_code == 200
        assert data['ok'] is False and '排料数据为空' in data['error']
    finally:
        state.clear()
        state.update(saved)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
