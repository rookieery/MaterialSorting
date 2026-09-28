"""routes_admin 单测（US-002）：token 姿态矩阵 + 五接口 CRUD/force/续期矩阵。

frp 修正版要点：TestClient 请求来源 host 即本机等价（``testclient``），若实现里
存在任何 loopback 放行兜底，本组 token 用例会全数假绿 —— 用例因此**同时**断言
未配置 token 时本机请求也 403，锁定「无 loopback 兜底」。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from keyserver import models, repo
from keyserver.keygen import KEY_RE

ADMIN = {'X-Admin-Token': 'secret-admin-token'}


@pytest.fixture
def client(db_env, monkeypatch):
    """默认姿态 = token 已配置（与 ADMIN 头匹配）；未配置/DEV 姿态用例自行覆盖。"""
    monkeypatch.setenv('MS_KEY_ADMIN_TOKEN', 'secret-admin-token')
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


def _mk_duration(conn, days=30, *, activated=False, expired=False, **fields) -> dict:
    row = repo.create_key(conn, 'duration', duration_days=days)
    extra = dict(fields)
    if activated:
        start = models.now() - timedelta(days=10)
        end = models.now() - timedelta(days=1) if expired else models.now() + timedelta(days=days)
        extra.update(activated_at=models.format_ts(start), expires_at=models.format_ts(end))
    if extra:
        repo.update_key(conn, row['id'], **extra)
        row = repo.get_key(conn, row['id'])
    return row


def _bind(conn, key_id: int) -> None:
    """绑本机 + count 未用完 / duration 已激活未过期 → active 态。"""
    repo.update_key(conn, key_id, bound_machine_guid='guid-local',
                    bound_system_name='SYS-LOCAL')


def _bind_active_duration(conn, key_id: int, days=30) -> None:
    start = models.now()
    repo.update_key(
        conn, key_id, bound_machine_guid='guid-local', bound_system_name='SYS-LOCAL',
        activated_at=models.format_ts(start),
        expires_at=models.format_ts(start + timedelta(days=days)))


# ---------------------------------------------------------------------------
# token 姿态矩阵（frp 修正版：不做 loopback 放行）
# ---------------------------------------------------------------------------

def test_403_when_token_not_configured(client, monkeypatch):
    monkeypatch.delenv('MS_KEY_ADMIN_TOKEN', raising=False)
    resp = client.get('/api/admin/keys', headers=ADMIN)
    assert resp.status_code == 403
    assert resp.json() == {'error': '管理 token 未配置，请设置 MS_KEY_ADMIN_TOKEN'}


def test_403_family_wide_all_five_endpoints(client, monkeypatch):
    """未配置 token → 管理端点族整体 403（含写接口；本机来源也拒 = 无 loopback 兜底）。"""
    monkeypatch.delenv('MS_KEY_ADMIN_TOKEN', raising=False)
    cases = [
        ('get', '/api/admin/keys', None),
        ('post', '/api/admin/keys', {'key_type': 'count', 'total_uses': 5}),
        ('post', '/api/admin/keys/1/renew', {'add_uses': 1}),
        ('put', '/api/admin/keys/1', {'remark': 'x'}),
        ('delete', '/api/admin/keys/1', None),
    ]
    for method, url, body in cases:
        resp = client.request(method, url, json=body)
        assert resp.status_code == 403, (method, url, resp.text)
        assert resp.json()['error'] == '管理 token 未配置，请设置 MS_KEY_ADMIN_TOKEN'


def test_empty_token_env_treated_as_unconfigured(client, monkeypatch):
    monkeypatch.setenv('MS_KEY_ADMIN_TOKEN', '')
    assert client.get('/api/admin/keys').status_code == 403


def test_dev_mode_allows_without_token(client, monkeypatch):
    """DEV=1 仅在 token 未配置时逃生（AC 字面语义：token 已设置仍须带头）。"""
    monkeypatch.delenv('MS_KEY_ADMIN_TOKEN', raising=False)
    monkeypatch.setenv('MS_KEY_DEV', '1')
    assert client.get('/api/admin/keys').status_code == 200


def test_dev_mode_does_not_bypass_configured_token(client):
    assert client.get('/api/admin/keys').status_code == 401


def test_401_when_token_set_and_header_missing(client, monkeypatch):
    monkeypatch.setenv('MS_KEY_ADMIN_TOKEN', 'secret-admin-token')
    resp = client.get('/api/admin/keys')
    assert resp.status_code == 401
    assert 'X-Admin-Token' in resp.json()['error']


def test_401_when_token_wrong(client, monkeypatch):
    monkeypatch.setenv('MS_KEY_ADMIN_TOKEN', 'secret-admin-token')
    resp = client.get('/api/admin/keys', headers={'X-Admin-Token': 'wrong'})
    assert resp.status_code == 401


def test_200_when_token_correct(client, monkeypatch):
    monkeypatch.setenv('MS_KEY_ADMIN_TOKEN', 'secret-admin-token')
    assert client.get('/api/admin/keys', headers=ADMIN).status_code == 200


def test_health_is_public_without_token(client):
    assert client.get('/api/key/health').status_code == 200


# ---------------------------------------------------------------------------
# POST /api/admin/keys 新建
# ---------------------------------------------------------------------------

def test_create_count_key(client, conn):
    resp = client.post('/api/admin/keys', headers=ADMIN,
                       json={'key_type': 'count', 'total_uses': 5, 'remark': '测试卡'})
    assert resp.status_code == 201
    body = resp.json()
    assert KEY_RE.fullmatch(body['key_plaintext'])
    assert body['key_type'] == 'count'
    assert body['detail'] == '0/5'
    assert body['status'] == '未绑定'
    assert body['remark'] == '测试卡'
    assert body['usage_stats'] is None
    assert body['bound_system_name'] is None
    assert body['created_at']
    ops = repo.list_ops(conn, body['id'])
    assert ops[0]['op'] == 'create'


def test_create_duration_key(client, conn):
    resp = client.post('/api/admin/keys', headers=ADMIN,
                       json={'key_type': 'duration', 'duration_days': 30})
    assert resp.status_code == 201
    body = resp.json()
    assert body['key_type'] == 'duration'
    assert body['detail'] == '30天'
    row = repo.get_key(conn, body['id'])
    assert row['activated_at'] is None and row['expires_at'] is None   # 建卡不激活（bind 激活，US-003）


def test_create_invalid_key_type(client):
    for bad in (None, 'free', 1):
        resp = client.post('/api/admin/keys', headers=ADMIN,
                           json={'key_type': bad, 'total_uses': 5})
        assert resp.status_code == 400, bad
        assert resp.json()['error'] == 'key_type 必须为 count 或 duration'


@pytest.mark.parametrize('bad', [0, -1, '5', 2.5, True, None])
def test_create_count_rejects_non_positive_total(client, bad):
    resp = client.post('/api/admin/keys', headers=ADMIN,
                       json={'key_type': 'count', 'total_uses': bad})
    assert resp.status_code == 400
    assert resp.json()['error'] == 'total_uses 必须为正整数'


@pytest.mark.parametrize('bad', [0, -3, '30', True, None])
def test_create_duration_rejects_non_positive_days(client, bad):
    resp = client.post('/api/admin/keys', headers=ADMIN,
                       json={'key_type': 'duration', 'duration_days': bad})
    assert resp.status_code == 400
    assert resp.json()['error'] == 'duration_days 必须为正整数'


def test_create_rejects_non_string_remark(client):
    resp = client.post('/api/admin/keys', headers=ADMIN,
                       json={'key_type': 'count', 'total_uses': 5, 'remark': 7})
    assert resp.status_code == 400
    assert resp.json()['error'] == 'remark 必须为字符串'


# ---------------------------------------------------------------------------
# GET /api/admin/keys 列表
# ---------------------------------------------------------------------------

def test_list_contract_fields_and_order(client, conn):
    older = _mk_count(conn, total=10)
    newer = _mk_duration(conn, days=7)
    resp = client.get('/api/admin/keys', headers=ADMIN)
    assert resp.status_code == 200
    keys = resp.json()['keys']
    assert [k['id'] for k in keys[:2]] == [newer['id'], older['id']]   # 新→旧
    assert set(keys[0].keys()) == {
        'id', 'key_plaintext', 'key_type', 'detail', 'status',
        'bound_system_name', 'remark', 'usage_stats', 'created_at'}


def test_list_usage_stats_with_records(client, conn):
    row = _mk_count(conn, total=10)
    today = models.ymd_of(models.now())
    repo.bump_daily_usage(conn, row['id'], today, delta=3)
    resp = client.get('/api/admin/keys', headers=ADMIN)
    stats = resp.json()['keys'][0]['usage_stats']
    assert stats == {'total': 3, 'max_daily': 3, 'avg_daily': 3.0, 'first_used': today}


def test_list_status_six_state_labels(client, conn):
    """六态上屏口径：status 字段 = STATUS_LABELS 中文标签（derive_status 单一真相源）。"""
    unbound = _mk_count(conn, total=5)
    active = _mk_count(conn, total=5)
    _bind(conn, active['id'])
    exhausted = _mk_count(conn, total=3)
    repo.update_key(conn, exhausted['id'], bound_machine_guid='g', used_uses=3)
    expired = _mk_duration(conn, days=5, activated=True, expired=True,
                           bound_machine_guid='g')
    unactivated = _mk_duration(conn, days=5, bound_machine_guid='g')
    merged_target = _mk_duration(conn, days=5)
    merged_src = _mk_duration(conn, days=5, bound_machine_guid='g')
    repo.update_key(conn, merged_src['id'], merged_into_id=merged_target['id'])

    by_id = {k['id']: k['status'] for k in
             client.get('/api/admin/keys', headers=ADMIN).json()['keys']}
    assert by_id[unbound['id']] == '未绑定'
    assert by_id[active['id']] == '正在使用'
    assert by_id[exhausted['id']] == '已用完'
    assert by_id[expired['id']] == '已过期'
    assert by_id[unactivated['id']] == '未激活'
    assert by_id[merged_src['id']] == '已合并'


# ---------------------------------------------------------------------------
# POST /api/admin/keys/{id}/renew 续期矩阵
# ---------------------------------------------------------------------------

def test_renew_count_adds_total(client, conn):
    row = _mk_count(conn, total=5)
    resp = client.post(f"/api/admin/keys/{row['id']}/renew", headers=ADMIN,
                       json={'add_uses': 5})
    assert resp.status_code == 200
    assert resp.json()['detail'] == '0/10'
    assert repo.list_ops(conn, row['id'])[0]['op'] == 'renew'


def test_renew_count_on_partially_used(client, conn):
    row = _mk_count(conn, total=5)
    repo.update_key(conn, row['id'], used_uses=3)
    resp = client.post(f"/api/admin/keys/{row['id']}/renew", headers=ADMIN,
                       json={'add_uses': 2})
    assert resp.json()['detail'] == '3/7'


def test_renew_duration_unactivated_adds_days(client, conn):
    row = _mk_duration(conn, days=30)
    resp = client.post(f"/api/admin/keys/{row['id']}/renew", headers=ADMIN,
                       json={'add_days': 10})
    assert resp.status_code == 200
    assert resp.json()['detail'] == '40天'
    fresh = repo.get_key(conn, row['id'])
    assert fresh['duration_days'] == 40
    assert fresh['activated_at'] is None and fresh['expires_at'] is None   # 未激活不动起止


def test_renew_duration_activated_shifts_expires_exact(client, conn):
    row = _mk_duration(conn, days=30)
    _bind_active_duration(conn, row['id'], days=30)
    before = repo.get_key(conn, row['id'])
    resp = client.post(f"/api/admin/keys/{row['id']}/renew", headers=ADMIN,
                       json={'add_days': 10})
    assert resp.status_code == 200
    after = repo.get_key(conn, row['id'])
    assert (models.parse_ts(after['expires_at'])
            - models.parse_ts(before['expires_at'])) == timedelta(days=10)
    assert after['duration_days'] == 30          # 激活后续期不动 duration_days
    assert after['activated_at'] == before['activated_at']
    assert resp.json()['detail'] == f"{after['activated_at']} ~ {after['expires_at']}"


@pytest.mark.parametrize('bad', [0, -1, '3', 1.5, True, None])
def test_renew_rejects_non_positive_add(client, conn, bad):
    row = _mk_count(conn, total=5)
    resp = client.post(f"/api/admin/keys/{row['id']}/renew", headers=ADMIN,
                       json={'add_uses': bad})
    assert resp.status_code == 400
    assert resp.json()['error'] == 'add_uses 必须为正整数'
    dur = _mk_duration(conn, days=5)
    resp2 = client.post(f"/api/admin/keys/{dur['id']}/renew", headers=ADMIN,
                        json={'add_days': bad})
    assert resp2.status_code == 400
    assert resp2.json()['error'] == 'add_days 必须为正整数'


def test_renew_wrong_field_for_type(client, conn):
    """count 型只认 add_uses / duration 型只认 add_days —— 传错字段 = 缺字段。"""
    row = _mk_count(conn, total=5)
    resp = client.post(f"/api/admin/keys/{row['id']}/renew", headers=ADMIN,
                       json={'add_days': 5})
    assert resp.status_code == 400
    assert resp.json()['error'] == 'add_uses 必须为正整数'


def test_renew_missing_key_404(client):
    resp = client.post('/api/admin/keys/999/renew', headers=ADMIN,
                       json={'add_uses': 1})
    assert resp.status_code == 404
    assert resp.json()['error'] == 'key 不存在'


# ---------------------------------------------------------------------------
# PUT /api/admin/keys/{id} 改备注
# ---------------------------------------------------------------------------

def test_edit_remark_persists(client, conn):
    row = _mk_count(conn, total=5)
    resp = client.put(f"/api/admin/keys/{row['id']}", headers=ADMIN,
                      json={'remark': '新版师工位'})
    assert resp.status_code == 200
    assert resp.json()['remark'] == '新版师工位'
    assert repo.get_key(conn, row['id'])['remark'] == '新版师工位'
    assert repo.list_ops(conn, row['id'])[0]['op'] == 'edit'


def test_edit_empty_remark_clears(client, conn):
    row = _mk_count(conn, total=5, remark='旧备注')
    resp = client.put(f"/api/admin/keys/{row['id']}", headers=ADMIN,
                      json={'remark': ''})
    assert resp.status_code == 200
    assert repo.get_key(conn, row['id'])['remark'] == ''


@pytest.mark.parametrize('bad', [None, 7, ['x']])
def test_edit_rejects_non_string_remark(client, conn, bad):
    row = _mk_count(conn, total=5)
    resp = client.put(f"/api/admin/keys/{row['id']}", headers=ADMIN,
                      json={'remark': bad})
    assert resp.status_code == 400
    assert resp.json()['error'] == 'remark 必须为字符串'


def test_edit_missing_key_404(client):
    resp = client.put('/api/admin/keys/999', headers=ADMIN, json={'remark': 'x'})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/admin/keys/{id} 删除 + force 二次确认
# ---------------------------------------------------------------------------

def test_delete_non_active_direct_without_force(client, conn):
    row = _mk_count(conn, total=5)                       # 未绑定 → 非 active
    resp = client.delete(f"/api/admin/keys/{row['id']}", headers=ADMIN)
    assert resp.status_code == 200
    assert resp.json() == {'ok': True, 'id': row['id']}
    assert repo.get_key(conn, row['id']) is None


def test_delete_active_without_force_409_and_kept(client, conn):
    row = _mk_count(conn, total=5)
    _bind(conn, row['id'])
    resp = client.delete(f"/api/admin/keys/{row['id']}", headers=ADMIN)
    assert resp.status_code == 409
    assert resp.json() == {'error': '该 key 正在使用，确认删除请再次确认'}
    assert repo.get_key(conn, row['id']) is not None      # 未删


def test_delete_active_with_force(client, conn):
    row = _mk_count(conn, total=5)
    _bind(conn, row['id'])
    resp = client.delete(f"/api/admin/keys/{row['id']}?force=true", headers=ADMIN)
    assert resp.status_code == 200
    assert repo.get_key(conn, row['id']) is None


def test_delete_force_other_values_still_409(client, conn):
    """>?force=1 / ?force=yes 不算确认 —— 契约只认 force=true。"""
    row = _mk_count(conn, total=5)
    _bind(conn, row['id'])
    for pseudo in ('1', 'yes', 'True'):
        resp = client.delete(
            f"/api/admin/keys/{row['id']}?force={pseudo}", headers=ADMIN)
        assert resp.status_code == 409, pseudo
    assert repo.get_key(conn, row['id']) is not None


def test_delete_expired_and_exhausted_direct(client, conn):
    expired = _mk_duration(conn, days=5, activated=True, expired=True,
                           bound_machine_guid='g')
    resp = client.delete(f"/api/admin/keys/{expired['id']}", headers=ADMIN)
    assert resp.status_code == 200
    exhausted = _mk_count(conn, total=3)
    repo.update_key(conn, exhausted['id'], bound_machine_guid='g', used_uses=3)
    resp2 = client.delete(f"/api/admin/keys/{exhausted['id']}", headers=ADMIN)
    assert resp2.status_code == 200


def test_delete_op_log_survives(client, conn):
    """delete 审计在物理删除后落账（悬空 key_id 有意保留，FR-16）。"""
    row = _mk_count(conn, total=5, remark='待删')
    repo.log_op(conn, row['id'], 'create', {'n': 1})      # 既有历史日志
    resp = client.delete(f"/api/admin/keys/{row['id']}", headers=ADMIN)
    assert resp.status_code == 200
    ops = repo.list_ops(conn, row['id'])
    assert len(ops) == 1 and ops[0]['op'] == 'delete'     # 既有日志被清，delete 审计留痕


def test_delete_missing_key_404(client):
    resp = client.delete('/api/admin/keys/999', headers=ADMIN)
    assert resp.status_code == 404
    assert resp.json()['error'] == 'key 不存在'


def test_all_error_bodies_use_error_key(client, monkeypatch):
    """US-004 keygate 透传契约：业务错误一律 {"error": ...}，无 detail 字段。"""
    monkeypatch.setenv('MS_KEY_ADMIN_TOKEN', 'secret-admin-token')
    for resp in (
        client.post('/api/admin/keys', headers=ADMIN, json={'key_type': 'bad'}),
        client.post('/api/admin/keys/999/renew', headers=ADMIN, json={'add_uses': 1}),
        client.delete('/api/admin/keys/999', headers=ADMIN),
        client.get('/api/admin/keys'),
    ):
        assert 'detail' not in resp.json()
        assert resp.json()['error']

