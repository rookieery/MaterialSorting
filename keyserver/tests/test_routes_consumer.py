"""routes_consumer 单测（US-003）：token 姿态矩阵 + 四接口 HTTP 契约 + 并发零超扣。

镜像 test_routes_admin 的 token 姿态锁定（无 loopback 兜底：本机来源未配置 token
也 403）。并发测试按 AC：20 线程对 total=5 并发 validate，恰 5×200 + 15×403，
used_uses 终值 = 5 —— 经 TestClient 走完整 HTTP 路径（每请求独立连接 =
真实 SQLite 写并发）。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from keyserver import models, repo

CLIENT = {'X-Client-Token': 'secret-client-token'}
GUID = 'guid-A'


@pytest.fixture
def client(db_env, monkeypatch):
    """默认姿态 = token 已配置（与 CLIENT 头匹配）；未配置/DEV 姿态用例自行覆盖。"""
    monkeypatch.setenv('MS_KEY_CLIENT_TOKEN', 'secret-client-token')
    monkeypatch.delenv('MS_KEY_DEV', raising=False)
    pytest.importorskip('fastapi.testclient')
    from fastapi.testclient import TestClient

    from keyserver import app as app_mod

    with TestClient(app_mod.app) as c:
        yield c


def _mk_count(conn, total=10, **fields) -> dict:
    row = repo.create_key(conn, 'count', total_uses=total)
    if fields:
        repo.update_key(conn, row['id'], **fields)
        row = repo.get_key(conn, row['id'])
    return row


def _bind_here(conn, key_id: int, name='SYS-A') -> None:
    repo.update_key(conn, key_id, bound_machine_guid=GUID, bound_system_name=name)


# ---------------------------------------------------------------------------
# token 姿态矩阵（镜像管理端：无 loopback 放行）
# ---------------------------------------------------------------------------

def test_403_when_token_not_configured_family_wide(client, monkeypatch):
    monkeypatch.delenv('MS_KEY_CLIENT_TOKEN', raising=False)
    cases = [
        ('/api/key/bind', {'key': 'MS-AAAAA-BBBBB-CCCCC', 'machine_guid': GUID,
                           'system_name': 'PC'}),
        ('/api/key/merge', {'target_key': 'MS-AAAAA-BBBBB-CCCCC',
                            'source_keys': ['MS-DDDDD-EEEEE-FFFFF'],
                            'machine_guid': GUID}),
        ('/api/key/info', {'key': 'MS-AAAAA-BBBBB-CCCCC', 'machine_guid': GUID}),
        ('/api/key/validate', {'key': 'MS-AAAAA-BBBBB-CCCCC', 'machine_guid': GUID,
                               'deduct': True}),
    ]
    for url, body in cases:
        resp = client.post(url, headers=CLIENT, json=body)
        assert resp.status_code == 403, (url, resp.text)
        assert resp.json()['error'] == '消费 token 未配置，请设置 MS_KEY_CLIENT_TOKEN'


def test_empty_token_env_treated_as_unconfigured(client, monkeypatch):
    monkeypatch.setenv('MS_KEY_CLIENT_TOKEN', '')
    resp = client.post('/api/key/info', headers=CLIENT,
                       json={'key': 'MS-AAAAA-BBBBB-CCCCC', 'machine_guid': GUID})
    assert resp.status_code == 403


def test_dev_mode_allows_without_token(client, monkeypatch):
    monkeypatch.delenv('MS_KEY_CLIENT_TOKEN', raising=False)
    monkeypatch.setenv('MS_KEY_DEV', '1')
    resp = client.post('/api/key/info', json={'key': 'MS-AAAAA-BBBBB-CCCCC',
                                              'machine_guid': GUID})
    assert resp.status_code == 404          # 逃生放行 → 业务 404（key 不存在）
    assert resp.json()['error'] == 'key 不存在：请检查输入是否正确'


def test_dev_mode_does_not_bypass_configured_token(client):
    resp = client.post('/api/key/info', json={'key': 'MS-AAAAA-BBBBB-CCCCC',
                                              'machine_guid': GUID})
    assert resp.status_code == 401


def test_401_when_token_set_and_header_missing(client):
    resp = client.post('/api/key/info', json={'key': 'MS-AAAAA-BBBBB-CCCCC',
                                              'machine_guid': GUID})
    assert resp.status_code == 401
    assert 'X-Client-Token' in resp.json()['error']


def test_401_when_token_wrong(client):
    resp = client.post('/api/key/info', headers={'X-Client-Token': 'wrong'},
                       json={'key': 'MS-AAAAA-BBBBB-CCCCC', 'machine_guid': GUID})
    assert resp.status_code == 401


def test_health_is_public_without_client_token(client, monkeypatch):
    monkeypatch.delenv('MS_KEY_CLIENT_TOKEN', raising=False)
    assert client.get('/api/key/health').status_code == 200


def test_admin_token_does_not_open_consumer_endpoints(client):
    resp = client.post('/api/key/info', headers={'X-Admin-Token': 'secret-admin-token'},
                       json={'key': 'MS-AAAAA-BBBBB-CCCCC', 'machine_guid': GUID})
    assert resp.status_code == 401          # 双 token 各管各族


# ---------------------------------------------------------------------------
# 入参形状校验（400 中文）
# ---------------------------------------------------------------------------

def test_bind_missing_fields_400(client):
    resp = client.post('/api/key/bind', headers=CLIENT, json={})
    assert resp.status_code == 400
    assert resp.json()['error'] == 'key 不能为空'


def test_bind_blank_machine_guid_400(client, conn):
    row = _mk_count(conn, total=5)
    resp = client.post('/api/key/bind', headers=CLIENT,
                       json={'key': row['key_plaintext'], 'machine_guid': '  ',
                             'system_name': 'PC'})
    assert resp.status_code == 400
    assert resp.json()['error'] == 'machine_guid 不能为空'


def test_merge_source_keys_shape_400(client):
    resp = client.post('/api/key/merge', headers=CLIENT,
                       json={'target_key': 'MS-AAAAA-BBBBB-CCCCC',
                             'source_keys': [], 'machine_guid': GUID})
    assert resp.status_code == 400
    assert resp.json()['error'] == 'source_keys 必须为非空 key 列表'
    resp2 = client.post('/api/key/merge', headers=CLIENT,
                        json={'target_key': 'MS-AAAAA-BBBBB-CCCCC',
                              'source_keys': [7], 'machine_guid': GUID})
    assert resp2.status_code == 400
    assert resp2.json()['error'] == 'source_keys 必须为 key 字符串列表'


def test_validate_deduct_must_be_bool(client, conn):
    row = _mk_count(conn, total=5)
    _bind_here(conn, row['id'])
    resp = client.post('/api/key/validate', headers=CLIENT,
                       json={'key': row['key_plaintext'], 'machine_guid': GUID,
                             'deduct': 'yes'})
    assert resp.status_code == 400
    assert resp.json()['error'] == 'deduct 必须为布尔值'


# ---------------------------------------------------------------------------
# 四接口 HTTP 契约
# ---------------------------------------------------------------------------

def test_bind_flow_over_http(client, conn):
    row = _mk_count(conn, total=6)
    resp = client.post('/api/key/bind', headers=CLIENT,
                       json={'key': row['key_plaintext'], 'machine_guid': GUID,
                             'system_name': 'WIN-PC'})
    assert resp.status_code == 200
    body = resp.json()
    assert body['type'] == 'count'
    assert body['status'] == '正在使用'
    assert body['remaining_uses'] == 6
    assert body['bound_system_name'] == 'WIN-PC'
    assert body['remark'] == 'WIN-PC'
    # 幂等再绑
    resp2 = client.post('/api/key/bind', headers=CLIENT,
                        json={'key': row['key_plaintext'], 'machine_guid': GUID,
                              'system_name': 'OTHER-NAME'})
    assert resp2.status_code == 200


def test_info_over_http(client, conn):
    row = _mk_count(conn, total=6)
    _bind_here(conn, row['id'])
    resp = client.post('/api/key/info', headers=CLIENT,
                       json={'key': row['key_plaintext'], 'machine_guid': GUID})
    assert resp.status_code == 200
    assert resp.json()['remaining_uses'] == 6


def test_validate_over_http_deduct_and_precheck(client, conn):
    row = _mk_count(conn, total=2)
    _bind_here(conn, row['id'])
    resp = client.post('/api/key/validate', headers=CLIENT,
                       json={'key': row['key_plaintext'], 'machine_guid': GUID,
                             'deduct': True})
    assert resp.status_code == 200
    assert resp.json()['remaining_uses'] == 1
    # deduct 缺省 = false 预检不动账
    resp2 = client.post('/api/key/validate', headers=CLIENT,
                        json={'key': row['key_plaintext'], 'machine_guid': GUID})
    assert resp2.status_code == 200
    assert resp2.json()['remaining_uses'] == 1
    resp3 = client.post('/api/key/validate', headers=CLIENT,
                        json={'key': row['key_plaintext'], 'machine_guid': GUID,
                              'deduct': True})
    assert resp3.status_code == 200
    resp4 = client.post('/api/key/validate', headers=CLIENT,
                        json={'key': row['key_plaintext'], 'machine_guid': GUID,
                              'deduct': True})
    assert resp4.status_code == 403
    assert resp4.json() == {'error': '授权次数已用完（共 2 次）'}


def test_merge_over_http(client, conn):
    start = models.now()
    target = repo.create_key(conn, 'duration', duration_days=10)
    src = repo.create_key(conn, 'duration', duration_days=5)
    for row, days in ((target, 10), (src, 5)):
        repo.update_key(
            conn, row['id'], bound_machine_guid=GUID, bound_system_name='SYS-A',
            activated_at=models.format_ts(start),
            expires_at=models.format_ts(start + timedelta(days=days)))
    resp = client.post('/api/key/merge', headers=CLIENT,
                       json={'target_key': target['key_plaintext'],
                             'source_keys': [src['key_plaintext']],
                             'machine_guid': GUID})
    assert resp.status_code == 200
    body = resp.json()
    assert body['target']['type'] == 'duration'
    assert body['target']['status'] == '正在使用'
    assert len(body['sources']) == 1
    assert repo.get_key(conn, src['id'])['merged_into_id'] == target['id']


def test_consumer_error_bodies_use_error_key(client, conn):
    """US-004 keygate 透传契约：业务错误一律 {"error": ...}，无 detail 字段。"""
    for resp in (
        client.post('/api/key/bind', headers=CLIENT,
                    json={'key': 'MS-AAAAA-BBBBB-CCCCC', 'machine_guid': GUID,
                          'system_name': 'PC'}),
        client.post('/api/key/merge', headers=CLIENT,
                    json={'target_key': 'MS-AAAAA-BBBBB-CCCCC',
                          'source_keys': ['MS-DDDDD-EEEEE-FFFFF'],
                          'machine_guid': GUID}),
        client.post('/api/key/info', headers=CLIENT,
                    json={'key': 'MS-AAAAA-BBBBB-CCCCC', 'machine_guid': GUID}),
        client.post('/api/key/validate', headers=CLIENT,
                    json={'key': 'MS-AAAAA-BBBBB-CCCCC', 'machine_guid': GUID,
                          'deduct': True}),
    ):
        assert 'detail' not in resp.json()
        assert resp.json()['error']


# ---------------------------------------------------------------------------
# 并发零超扣（AC：20 线程 × total=5 → 恰 5×200 + 15×403，used_uses 终值 5）
# ---------------------------------------------------------------------------

def test_validate_concurrent_no_oversell(client, conn):
    row = _mk_count(conn, total=5)
    _bind_here(conn, row['id'])
    payload = {'key': row['key_plaintext'], 'machine_guid': GUID, 'deduct': True}

    def hit(_):
        resp = client.post('/api/key/validate', headers=CLIENT, json=payload)
        return resp.status_code, resp.json()

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(hit, range(20)))

    statuses = [code for code, _ in results]
    assert statuses.count(200) == 5
    assert statuses.count(403) == 15
    for code, body in results:
        if code == 403:
            assert body == {'error': '授权次数已用完（共 5 次）'}
    fresh = repo.get_key(conn, row['id'])
    assert fresh['used_uses'] == 5                       # 零超扣终值
    assert repo.list_daily_usage(conn, row['id'])[0]['count'] == 5
    assert len([o for o in repo.list_ops(conn, row['id'])
                if o['op'] == 'validate_deduct']) == 5

