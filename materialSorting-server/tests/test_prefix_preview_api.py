"""POST /api/prefix-preview 前缀组合形态预览端点测试（镜像 test_band_preview_api）。

覆盖（2026-08-25 布局设置 prefix 行缩略图换组合形态预览）：
1. ok:true 全链路：4 成员同码（前×2 + 后×2 interleave）、polygon 已减 offset
   归一（≥0）、tag = 成员 g 码（前/后幅区分）、颜色 = size_color 同码同色、
   outline = erode 后组合片外轮廓、响应全文无 PS_（哨兵）；
2. sizes 过滤 + seed 缺省 0 确定性（同载荷重放逐字节一致）；
3. prefix 校验复用 _parse_prefix：未开启 / g 码不存在 / front==back / 无 2+2
   资格码 → ok:false + 原文案；
4. 构造失败（竖排超高）→ ok:false「前缀构造失败」前置（不抛 500）；
5. 空 state → ok:false「排料数据为空」；
6. 2026-09-02（prd-prefix-extra-piece US-003：选码换 select_prefix_plan 真相源
   + 构造段线程池化 + 响应 additive）：
   - 5 片补片形态（gate 2400）：n_members=5（4 同码 + 顶部异码）、extra=
     {label,size}、fallback=False、residual_mm/gate_mm 回显、异码片 tag/颜色
     （size_color 同码同色跨片型）、5 片形态确定性重放；
   - 兜底形态（默认 gate 1980，5 片组合均竖排超高 → 无可行）：extra=null、
     fallback=True、n_members=4（既有 4 片断言语义在 1~5 号用例零改动延续）；
   - 预览与求解同选对拍：同 payload 直调 select_prefix_plan（与 solve_worker
     _build_prefix 同参）—— size/extra/fallback/residual_mm/成员 pid 序逐项一致。

合成数据：g02（前幅 300×450）/ g03（后幅 320×420）两码 ×demand 2 —— 2+2 资格
（2026-09-02 US-003 高度 350/330→450/420：矩形竖排高手算基座 1740mm、5 片
2160~2190mm ⇒ 默认 gate 1980 下任何 5 片组合竖排超高 → 选码搜索必兜底 4 片，
既有用例 4 片断言语义零改动；gate 2400 下最大 H=1740+450=2190 ⇒ 确定性选定
套装@28 + 顶部 g02@29（residual 210mm））。
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
    """合成母版：g02 前幅 300×450 / g03 后幅 320×420 各两码（2+2 资格主角）。

    高度取 450/420（2026-09-02 US-003 调整，原 350/330）：基座 1740 < 默认 gate
    1980 < 最矮 5 片 2160 ⇒ 默认门幅下近满幅搜索必兜底 4 片 —— 既有用例（写于
    seeded 随机 4 片时代）的 4 片断言语义零改动延续；5 片新形态用 gate_mm=2400
    显式触发（手算见模块 docstring）。
    """
    return [
        _piece('g02_28', 'g02', 28, 300.0, 450.0),
        _piece('g02_29', 'g02', 29, 300.0, 450.0),
        _piece('g03_28', 'g03', 28, 320.0, 420.0),
        _piece('g03_29', 'g03', 29, 320.0, 420.0),
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


# --------------------------------------- 2026-09-02 US-003：新字段 / 双形态 / 同选对拍

_QTY_FULL = {'g02': {'28': 2, '29': 2}, 'g03': {'28': 2, '29': 2}}


def test_prefix_preview_extra_piece_five_members(prefix_client):
    """5 片补片形态（gate 2400 > 最大 H 2190）：n_members=5 + 新字段回显。

    矩形手算（模块 docstring）：基座 1740 + 顶部 g02 补片 450 = H 2190 ⇒
    确定性选定 套装@28 + g02@29（front 先 / B 升序 / rot0 先的迭代序裁决，
    两码几何同形平手不改先序胜者）；residual = 2400 − 2190 = 210。
    """
    r1 = _preview(prefix_client, gate_mm=2400, quantities=_QTY_FULL).json()
    r2 = _preview(prefix_client, gate_mm=2400, quantities=_QTY_FULL).json()
    assert r1['ok'] is True
    assert r1['size'] == 28
    assert r1['n_members'] == 5
    # 新字段（additive）：补片在案 / 非兜底 / 残余缝隙与门幅回显
    assert r1['extra'] == {'label': 'g02', 'size': 29}
    assert r1['fallback'] is False
    assert r1['residual_mm'] == pytest.approx(210.0, abs=1e-6)
    assert r1['gate_mm'] == pytest.approx(2400.0)
    # 5 成员 = 4 同码基座（paired 序：后×2 + 前×2 @28，2026-09-03 改判）+
    # 顶部异码 g02@29；bbox 高 = H
    pids = [m['pid'] for m in r1['members']]
    assert pids == ['g03_28', 'g03_28', 'g02_28', 'g02_28', 'g02_29']
    tags = [m['tag'] for m in r1['members']]
    assert tags.count('g02') == 3 and tags.count('g03') == 2
    assert r1['bbox']['height_mm'] == pytest.approx(2190.0, abs=0.2)
    # 异码片颜色 = size_color 同码同色跨片型：g02@29 与基座同 28 码同色、29 码异色
    colors = {m['size']: m['color'] for m in r1['members']}
    assert len(colors) == 2 and colors[28] != colors[29]
    # 第 5 成员在顶部（y 最大）且 polygon 归一 ≥0
    top = max(r1['members'], key=lambda m: max(y for _x, y in m['polygon']))
    assert top['pid'] == 'g02_29'
    for m in r1['members']:
        assert min(x for x, _y in m['polygon']) >= -0.01
        assert min(y for _x, y in m['polygon']) >= -0.01
    # 搜索路径无 RNG：5 片形态同样确定性重放
    assert r1 == r2
    # 哨兵：响应全文无 PS_
    assert 'PS_' not in json.dumps(r1)


def test_prefix_preview_fallback_shape(prefix_client):
    """兜底形态（默认 gate 1980 < 最矮 5 片 2160）：extra=null + fallback=True。

    无可行 5 片组合 → pick_prefix_size seeded 4 片构造（与旧行为完全一致）；
    新字段 additive 回显：extra=null（JSON null）/ fallback=True / n_members=4 /
    residual = 1980 − 基座 1740 = 240 / gate_mm 回退 intermediate 1980。
    """
    data = _preview(prefix_client, quantities=_QTY_FULL).json()
    assert data['ok'] is True
    assert data['fallback'] is True
    assert data['extra'] is None
    assert data['n_members'] == 4
    assert {m['size'] for m in data['members']} == {data['size']}
    assert data['residual_mm'] == pytest.approx(240.0, abs=1e-6)
    assert data['gate_mm'] == pytest.approx(1980.0)


def test_prefix_preview_same_selection_as_select_prefix_plan(prefix_client):
    """预览与求解同选对拍：同 payload 直调 select_prefix_plan（与 solve_worker
    ``_build_prefix`` 同参同源）—— size/extra/fallback/residual/成员 pid 序
    逐项一致（5 片与兜底双形态）。"""
    from materialsorting.nesting_engine.prefix import select_prefix_plan
    from materialsorting.web.solver import build_pid_meta

    pieces = _prefix_pieces()            # 与 prefix_client 注入 state 同一构造
    pieces_by_id = {p['pid']: p for p in pieces}
    pid_meta, _area, _n = build_pid_meta(
        pieces, sizes=None, per_type=None, quantities=_QTY_FULL, params=None)
    for gate in (2400.0, 1980.0):        # 5 片补片 / 兜底 4 片
        resp = _preview(prefix_client, gate_mm=gate,
                        quantities=_QTY_FULL).json()
        chunk, _gaps, _holes, info = select_prefix_plan(
            pid_meta, pieces_by_id, front_label='g02', back_label='g03',
            quantities=_QTY_FULL, sizes=None, d_g=0.0, gate_nest=gate, seed=0)
        assert resp['ok'] is True
        assert resp['size'] == info['size']
        assert resp['fallback'] == info['fallback']
        assert resp['residual_mm'] == pytest.approx(info['residual_mm'], abs=1e-3)
        ex = info['extra']
        assert resp['extra'] == (None if ex is None
                                 else {'label': ex['label'], 'size': ex['size']})
        # 成员 pid 序逐条一致：预览缩略 = 求解时 PS_ 组合片的精确形态
        assert [m['pid'] for m in resp['members']] == [m['pid'] for m in chunk.members]


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
