"""POST /api/prefix-preview 前缀组合形态预览端点测试（镜像 test_band_preview_api）。

覆盖（2026-08-25 布局设置 prefix 行缩略图换组合形态预览）：
1. ok:true 全链路：4 成员同码（前×2 + 后×2 interleave）、polygon 已减 offset
   归一（≥0）、tag = 成员 g 码（前/后幅区分）、颜色 = size_color 同码同色、
   outline = erode 后组合片外轮廓、响应全文无 PS_（哨兵）；
2. sizes 过滤 + seed 缺省 0 确定性（同载荷重放逐字节一致）；
3. prefix 校验复用 _parse_prefix：未开启 / g 码不存在 / front==back / 无 2+2
   资格码 → ok:false + 原文案；
4. 构造失败（竖排超高）→ ok:false「前缀构造失败」前置（不抛 500）；
5. 空 state → ok:false「排料数据为空」。

合成数据：g02（前幅 300×350）/ g03（后幅 320×330）两码 ×demand 2 —— 2+2 资格。
"""
from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from materialsorting.web import server as server_mod
from materialsorting.web.server import app


def _piece(pid, label, size, w, h):
    """合成 v2 schema 裁片（矩形原轮廓，与 test_band_preview_api 同构）。"""
    return {
        'pid': pid, 'label': label, 'size': size,
        'polygon': [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]],
        'bbox': [0.0, 0.0, float(w), float(h)], 'area_mm2': float(w) * float(h),
        'n_verts': 4, 'allowed_angles': [0, 180],
        'net_polygon': [], 'internal_lines': [], 'notches': [], 'grain_line': None,
    }


def _prefix_pieces():
    """合成母版：g02 前幅 300×350 / g03 后幅 320×330 各两码（2+2 资格主角）。"""
    return [
        _piece('g02_28', 'g02', 28, 300.0, 350.0),
        _piece('g02_29', 'g02', 29, 300.0, 350.0),
        _piece('g03_28', 'g03', 28, 320.0, 330.0),
        _piece('g03_29', 'g03', 29, 320.0, 330.0),
    ]


@pytest.fixture
def prefix_client(monkeypatch):
    """注入合成 pieces state（原位 clear+update，teardown 恢复真实 state）。"""
    pieces = _prefix_pieces()
    state = server_mod._PIECES_STATE
    saved = dict(state)
    state.clear()
    state.update({
        'doc': {'source': 'synthetic_prefix.dxf'},
        'gate_mm': 1980.0,
        'pieces': pieces,
        'pieces_by_id': {p['pid']: p for p in pieces},
    })
    with TestClient(app) as client:
        yield client
    state.clear()
    state.update(saved)


def _preview(client, **payload):
    """POST /api/prefix-preview（prefix 键默认开启 g02/g03）。"""
    body = {'prefix': {'enabled': True, 'front': 'g02', 'back': 'g03'}, **payload}
    return client.post('/api/prefix-preview', json=body)


# ------------------------------------------------------------- ok:true 全链路


def test_prefix_preview_ok_full_payload(prefix_client):
    resp = _preview(prefix_client,
                    quantities={'g02': {'28': 2, '29': 2}, 'g03': {'28': 2, '29': 2}})
    assert resp.status_code == 200
    data = resp.json()
    assert data['ok'] is True
    assert data['front'] == 'g02' and data['back'] == 'g03'
    assert data['size'] in (28, 29)
    assert data['n_members'] == 4
    # 副本守恒 + 同码：前×2（tag=g02）+ 后×2（tag=g03），4 成员同 size
    pids = [m['pid'] for m in data['members']]
    assert pids.count(f"g02_{data['size']}") == 2
    assert pids.count(f"g03_{data['size']}") == 2
    tags = [m['tag'] for m in data['members']]
    assert tags.count('g02') == 2 and tags.count('g03') == 2
    assert {m['size'] for m in data['members']} == {data['size']}
    # 颜色 = size_color 同码同色（4 成员同 size ⇒ 同色；单一真相源口径）
    assert len({m['color'] for m in data['members']}) == 1
    # polygon 已减 offset 归一（min ≥ -0.01 容浮点噪声）；顶点数 = 原轮廓 4 点
    for m in data['members']:
        assert len(m['polygon']) == 4
        assert min(x for x, _y in m['polygon']) >= -0.01
        assert min(y for _x, y in m['polygon']) >= -0.01
    # outline 非空闭合轮廓；bbox 与统计字段在场（竖排 → 高 > 宽）
    assert len(data['outline']) >= 3
    assert data['bbox']['width_mm'] > 0 and data['bbox']['height_mm'] > data['bbox']['width_mm']
    assert data['fill_pct'] > 0
    # 哨兵：响应全文无 PS_（组合片 pid 永不出现在前端契约）
    assert 'PS_' not in json.dumps(data)


def test_prefix_preview_sizes_filter_and_determinism(prefix_client):
    """sizes 过滤（唯一资格码 28 → size=28）+ 同载荷 seed 缺省 0 重放一致。"""
    kwargs = {'sizes': [28],
              'quantities': {'g02': {'28': 2, '29': 2}, 'g03': {'28': 2, '29': 2}}}
    r1 = _preview(prefix_client, **kwargs).json()
    r2 = _preview(prefix_client, **kwargs).json()
    assert r1['ok'] is True and r1['size'] == 28
    assert r1 == r2                      # 构造无 RNG + seed=0：预览确定性重放


# ------------------------------------------------------------- ok:false 分支


@pytest.mark.parametrize('prefix,quantities,frag', [
    ({'enabled': False, 'front': 'g02', 'back': 'g03'}, None, 'prefix 未开启'),
    ({'enabled': True, 'front': 'g99', 'back': 'g03'}, None, '不存在于当前母版'),
    ({'enabled': True, 'front': 'g02', 'back': 'g02'}, None, '须为不同 g 码'),
    ({'enabled': True, 'front': 'g02', 'back': 'g03'}, {'g02': {'28': 1}, 'g03': {'28': 1}},
     '无 2+2 资格码'),
])
def test_prefix_preview_validation(prefix_client, prefix, quantities, frag):
    """prefix 校验复用 _parse_prefix 单一校验点 → ok:false + 同款文案（200 包络）。"""
    resp = prefix_client.post('/api/prefix-preview',
                              json={'prefix': prefix, 'quantities': quantities})
    assert resp.status_code == 200
    data = resp.json()
    assert data['ok'] is False and frag in data['error']


def test_prefix_preview_construction_failure(prefix_client):
    """构造失败（gate 过小 → 竖排超高）→ ok:false「前缀构造失败」前置（不抛 500）。"""
    resp = _preview(prefix_client, gate_mm=600,
                    quantities={'g02': {'28': 2, '29': 2}, 'g03': {'28': 2, '29': 2}})
    data = resp.json()
    assert resp.status_code == 200
    assert data['ok'] is False
    assert '前缀构造失败' in data['error'] and '竖排高' in data['error']


def test_prefix_preview_empty_state(prefix_client):
    """空 state（首次启动未 commit）→ ok:false「排料数据为空」（不炸不 500）。"""
    state = server_mod._PIECES_STATE          # prefix_client 已存快照，teardown 恢复
    saved = dict(state)
    state.clear()
    try:
        resp = _preview(prefix_client)
        data = resp.json()
        assert resp.status_code == 200
        assert data['ok'] is False and '排料数据为空' in data['error']
    finally:
        state.clear()
        state.update(saved)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
