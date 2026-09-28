"""service 单测（US-003）：bind / merge / info / validate 业务规则矩阵。

直连连接层（不经 HTTP），锁业务规则与响应契约形状；token 姿态与 HTTP 形状在
test_routes_consumer.py。时间敏感断言用固定 now_dt 注入或宽 tolerance。
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from keyserver import models, repo, service
from keyserver.errors import ApiError
from keyserver.service import (
    MSG_BOUND_OTHER_BIND,
    MSG_KEY_NOT_FOUND,
    MSG_MERGED,
    MSG_NOT_BOUND_ANY,
    MSG_NOT_BOUND_THIS,
)

GUID = 'guid-A'
OTHER = 'guid-B'


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
        extra.update(activated_at=models.format_ts(start),
                     expires_at=models.format_ts(end))
    if extra:
        repo.update_key(conn, row['id'], **extra)
        row = repo.get_key(conn, row['id'])
    return row


def _bound_here(conn, row: dict, name='SYS-A') -> None:
    """绑本机 + 未失效（count 未用完 / duration 已激活未过期）→ active。"""
    if row['key_type'] == 'duration':
        start = models.now() - timedelta(days=1)
        repo.update_key(
            conn, row['id'], bound_machine_guid=GUID, bound_system_name=name,
            activated_at=models.format_ts(start),
            expires_at=models.format_ts(start + timedelta(days=int(row['duration_days']))))
    else:
        repo.update_key(conn, row['id'], bound_machine_guid=GUID,
                        bound_system_name=name)


def _exc(call) -> ApiError:
    with pytest.raises(ApiError) as ei:
        call()
    return ei.value


# ---------------------------------------------------------------------------
# bind
# ---------------------------------------------------------------------------

class TestBind:
    def test_bind_unbound_count_key(self, conn):
        row = _mk_count(conn, total=10)
        payload = service.bind(conn, key=row['key_plaintext'],
                               machine_guid=GUID, system_name='WIN-PC')
        fresh = repo.get_key(conn, row['id'])
        assert fresh['bound_machine_guid'] == GUID
        assert fresh['bound_system_name'] == 'WIN-PC'      # 系统名快照
        assert fresh['remark'] == 'WIN-PC'                 # 备注缺省 = 系统名
        assert payload['status'] == '正在使用'
        assert payload['remaining_uses'] == 10
        ops = repo.list_ops(conn, row['id'])
        assert ops[0]['op'] == 'bind'
        assert json.loads(ops[0]['detail'])['system_name'] == 'WIN-PC'

    def test_bind_existing_remark_preserved(self, conn):
        row = _mk_count(conn, total=5, remark='发卡备注')
        service.bind(conn, key=row['key_plaintext'],
                     machine_guid=GUID, system_name='WIN-PC')
        assert repo.get_key(conn, row['id'])['remark'] == '发卡备注'

    def test_bind_unbound_duration_activates_now(self, conn):
        row = _mk_duration(conn, days=30)
        before = models.now()
        payload = service.bind(conn, key=row['key_plaintext'],
                               machine_guid=GUID, system_name='WIN-PC')
        fresh = repo.get_key(conn, row['id'])
        act = models.parse_ts(fresh['activated_at'])
        exp = models.parse_ts(fresh['expires_at'])
        # 落库秒级截断（TS_FORMAT 无亚秒）→ 允许 1s 内偏差
        assert before - timedelta(seconds=1) <= act <= models.now()
        assert (exp - act) == timedelta(days=30)
        assert payload['type'] == 'duration'
        assert payload['status'] == '正在使用'
        assert payload['remaining_days'] == 30

    def test_bind_same_machine_idempotent(self, conn):
        row = _mk_count(conn, total=5)
        first = service.bind(conn, key=row['key_plaintext'],
                             machine_guid=GUID, system_name='NAME-1')
        fresh_after_first = repo.get_key(conn, row['id'])
        second = service.bind(conn, key=row['key_plaintext'],
                              machine_guid=GUID, system_name='NAME-2')
        fresh = repo.get_key(conn, row['id'])
        assert second['status'] == '正在使用'
        assert fresh['bound_system_name'] == 'NAME-1'      # 快照不回写
        assert fresh['updated_at'] == fresh_after_first['updated_at']   # 幂等不动库
        assert len([o for o in repo.list_ops(conn, row['id'])
                    if o['op'] == 'bind']) == 1            # 幂等不重复审计

    def test_bind_other_machine_409(self, conn):
        row = _mk_count(conn, total=5, bound_machine_guid=OTHER,
                        bound_system_name='OTHER-PC')
        err = _exc(lambda: service.bind(conn, key=row['key_plaintext'],
                                        machine_guid=GUID, system_name='WIN-PC'))
        assert (err.status_code, err.message) == (409, MSG_BOUND_OTHER_BIND)

    def test_bind_missing_key_404(self, conn):
        err = _exc(lambda: service.bind(conn, key='MS-AAAAA-BBBBB-CCCCC',
                                        machine_guid=GUID, system_name='WIN-PC'))
        assert (err.status_code, err.message) == (404, MSG_KEY_NOT_FOUND)

    def test_bind_exhausted_409(self, conn):
        row = _mk_count(conn, total=3, bound_machine_guid=GUID, used_uses=3)
        err = _exc(lambda: service.bind(conn, key=row['key_plaintext'],
                                        machine_guid=GUID, system_name='WIN-PC'))
        assert err.status_code == 409
        assert err.message == '授权次数已用完（共 3 次）'

    def test_bind_expired_409(self, conn):
        row = _mk_duration(conn, days=5, activated=True, expired=True,
                           bound_machine_guid=GUID)
        err = _exc(lambda: service.bind(conn, key=row['key_plaintext'],
                                        machine_guid=GUID, system_name='WIN-PC'))
        assert err.status_code == 409
        assert err.message == f'授权已过期（截止 {row["expires_at"]}）'

    def test_bind_merged_409(self, conn):
        target = _mk_duration(conn, days=5)
        row = _mk_duration(conn, days=5, merged_into_id=target['id'])
        err = _exc(lambda: service.bind(conn, key=row['key_plaintext'],
                                        machine_guid=GUID, system_name='WIN-PC'))
        assert (err.status_code, err.message) == (409, MSG_MERGED)


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

class TestMerge:
    def _setup_target_and_sources(self, conn):
        """target（10 天）+ 两个有效 source（5 天 / 20 天，均昨日激活绑本机）。"""
        target = _mk_duration(conn, days=10)
        _bound_here(conn, target)
        sources = []
        for days in (5, 20):
            src = _mk_duration(conn, days=days)
            _bound_here(conn, src)
            sources.append(repo.get_key(conn, src['id']))
        return repo.get_key(conn, target['id']), sources

    def test_merge_transfers_remaining_seconds_exact(self, conn):
        target, sources = self._setup_target_and_sources(conn)
        target_before = repo.get_key(conn, target['id'])
        t0 = models.now()
        service.merge(conn, target_key=target['key_plaintext'],
                      source_keys=[s['key_plaintext'] for s in sources],
                      machine_guid=GUID)
        t1 = models.now()
        fresh = repo.get_key(conn, target['id'])
        got = (models.parse_ts(fresh['expires_at'])
               - models.parse_ts(target_before['expires_at'])).total_seconds()
        # 增量 = Σ(src.expires_at − now)，now ∈ [t0, t1]（调用期内服务器时钟）；
        # 落库秒级截断（TS_FORMAT 无亚秒）允许 1s 下偏
        expected_min = sum((models.parse_ts(s['expires_at']) - t1).total_seconds()
                           for s in sources)
        expected_max = sum((models.parse_ts(s['expires_at']) - t0).total_seconds()
                           for s in sources)
        assert expected_min - 1 <= got <= expected_max

    def test_merge_marks_sources_merged_keeps_rows(self, conn):
        target, sources = self._setup_target_and_sources(conn)
        result = service.merge(conn, target_key=target['key_plaintext'],
                               source_keys=[sources[0]['key_plaintext']],
                               machine_guid=GUID)
        fresh = repo.get_key(conn, sources[0]['id'])
        assert fresh is not None                          # 保留不物理删除（FR-4）
        assert fresh['merged_into_id'] == target['id']
        assert 'merge_source' in [o['op'] for o in repo.list_ops(conn, sources[0]['id'])]
        assert 'merge_target' in [o['op'] for o in repo.list_ops(conn, target['id'])]
        assert [s['key'] for s in result['sources']] == [sources[0]['key_plaintext']]
        assert result['total_transferred_days'] > 0
        assert result['target']['expires_at'] == repo.get_key(conn, target['id'])['expires_at']

    def test_merge_duplicate_sources_counted_once(self, conn):
        target, sources = self._setup_target_and_sources(conn)
        src = sources[0]
        target_before = repo.get_key(conn, target['id'])
        t0 = models.now()
        result = service.merge(conn, target_key=target['key_plaintext'],
                               source_keys=[src['key_plaintext'], src['key_plaintext']],
                               machine_guid=GUID)
        t1 = models.now()
        fresh = repo.get_key(conn, target['id'])
        got = (models.parse_ts(fresh['expires_at'])
               - models.parse_ts(target_before['expires_at'])).total_seconds()
        once_min = (models.parse_ts(src['expires_at']) - t1).total_seconds()
        once_max = (models.parse_ts(src['expires_at']) - t0).total_seconds()
        assert len(result['sources']) == 1                # 去重不双计
        assert once_min - 1 <= got <= once_max            # 恰一份（秒级截断容差）

    def test_merge_target_in_sources_400(self, conn):
        target, sources = self._setup_target_and_sources(conn)
        err = _exc(lambda: service.merge(
            conn, target_key=target['key_plaintext'],
            source_keys=[sources[0]['key_plaintext'], target['key_plaintext']],
            machine_guid=GUID))
        assert err.status_code == 400
        assert err.message == '目标 key 不可同时作为被合并 key'
        assert repo.get_key(conn, sources[0]['id'])['merged_into_id'] is None  # 整体失败不动账

    def test_merge_count_source_400(self, conn):
        target, sources = self._setup_target_and_sources(conn)
        count_key = _mk_count(conn, total=5)
        _bound_here(conn, count_key)
        err = _exc(lambda: service.merge(
            conn, target_key=target['key_plaintext'],
            source_keys=[count_key['key_plaintext']], machine_guid=GUID))
        assert err.status_code == 400
        assert err.message == f'仅时长型 key 可合并：`{count_key["key_plaintext"]}` 为次数型'

    def test_merge_count_target_400(self, conn):
        target = _mk_count(conn, total=5)
        _bound_here(conn, target)
        src = _mk_duration(conn, days=5)
        _bound_here(conn, src)
        err = _exc(lambda: service.merge(
            conn, target_key=target['key_plaintext'],
            source_keys=[src['key_plaintext']], machine_guid=GUID))
        assert err.status_code == 400
        assert err.message == f'仅时长型 key 可合并：`{target["key_plaintext"]}` 为次数型'

    def test_merge_source_bound_other_400(self, conn):
        target, sources = self._setup_target_and_sources(conn)
        repo.update_key(conn, sources[0]['id'], bound_machine_guid=OTHER)
        err = _exc(lambda: service.merge(
            conn, target_key=target['key_plaintext'],
            source_keys=[sources[0]['key_plaintext']], machine_guid=GUID))
        assert err.status_code == 400
        assert err.message == f'`{sources[0]["key_plaintext"]}` 未绑定当前系统，无法合并'

    def test_merge_source_unbound_400_same_message(self, conn):
        target = _mk_duration(conn, days=10)
        _bound_here(conn, target)
        src = _mk_duration(conn, days=5, activated=True)   # 有效但未绑定
        err = _exc(lambda: service.merge(
            conn, target_key=target['key_plaintext'],
            source_keys=[src['key_plaintext']], machine_guid=GUID))
        assert err.status_code == 400
        assert err.message == f'`{src["key_plaintext"]}` 未绑定当前系统，无法合并'

    def test_merge_expired_source_400(self, conn):
        target, sources = self._setup_target_and_sources(conn)
        repo.update_key(
            conn, sources[0]['id'],
            expires_at=models.format_ts(models.now() - timedelta(days=1)))
        err = _exc(lambda: service.merge(
            conn, target_key=target['key_plaintext'],
            source_keys=[sources[0]['key_plaintext']], machine_guid=GUID))
        assert err.status_code == 400
        assert err.message == f'`{sources[0]["key_plaintext"]}` 已失效（过期/已合并），无法合并'

    def test_merge_already_merged_source_400(self, conn):
        target, sources = self._setup_target_and_sources(conn)
        other = _mk_duration(conn, days=99)
        repo.update_key(conn, sources[0]['id'], merged_into_id=other['id'])
        err = _exc(lambda: service.merge(
            conn, target_key=target['key_plaintext'],
            source_keys=[sources[0]['key_plaintext']], machine_guid=GUID))
        assert err.status_code == 400
        assert err.message == f'`{sources[0]["key_plaintext"]}` 已失效（过期/已合并），无法合并'

    def test_merge_expired_target_400(self, conn):
        target = _mk_duration(conn, days=5, activated=True, expired=True)
        repo.update_key(conn, target['id'], bound_machine_guid=GUID,
                        bound_system_name='SYS-A')
        src = _mk_duration(conn, days=5)
        _bound_here(conn, src)
        err = _exc(lambda: service.merge(
            conn, target_key=target['key_plaintext'],
            source_keys=[src['key_plaintext']], machine_guid=GUID))
        assert err.status_code == 400
        assert err.message == f'`{target["key_plaintext"]}` 已失效（过期/已合并），无法合并'

    def test_merge_missing_target_404_and_missing_source_404(self, conn):
        target, sources = self._setup_target_and_sources(conn)
        err = _exc(lambda: service.merge(conn, target_key='MS-AAAAA-BBBBB-CCCCC',
                                         source_keys=[sources[0]['key_plaintext']],
                                         machine_guid=GUID))
        assert (err.status_code, err.message) == (404, MSG_KEY_NOT_FOUND)
        err2 = _exc(lambda: service.merge(
            conn, target_key=target['key_plaintext'],
            source_keys=['MS-AAAAA-BBBBB-CCCCC'], machine_guid=GUID))
        assert (err2.status_code, err2.message) == (404, MSG_KEY_NOT_FOUND)


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

class TestInfo:
    def test_info_count_payload_shape(self, conn):
        row = _mk_count(conn, total=8)
        _bound_here(conn, row)
        repo.update_key(conn, row['id'], used_uses=3)
        payload = service.info(conn, key=row['key_plaintext'], machine_guid=GUID)
        assert payload == {
            'type': 'count', 'total_uses': 8, 'used_uses': 3,
            'remaining_uses': 5, 'status': '正在使用',
            'bound_system_name': 'SYS-A', 'remark': None}

    def test_info_duration_payload_shape(self, conn):
        row = _mk_duration(conn, days=30)
        _bound_here(conn, row)                     # 昨天激活，剩 ≈30 天
        payload = service.info(conn, key=row['key_plaintext'], machine_guid=GUID)
        assert set(payload) == {'type', 'activated_at', 'expires_at',
                                'remaining_days', 'status',
                                'bound_system_name', 'remark'}
        assert payload['remaining_days'] == 29     # 30 天昨日激活 → 恰剩 29 整天
        assert payload['status'] == '正在使用'

    def test_info_duration_unactivated(self, conn):
        row = _mk_duration(conn, days=15)
        payload = service.info(conn, key=row['key_plaintext'], machine_guid=GUID)
        assert payload['activated_at'] is None
        assert payload['expires_at'] is None
        assert payload['remaining_days'] == 15     # 一口未耗 = 完整时长
        assert payload['status'] == '未绑定'

    def test_info_unbound_key_200_with_status(self, conn):
        row = _mk_count(conn, total=5)
        payload = service.info(conn, key=row['key_plaintext'], machine_guid=GUID)
        assert payload['status'] == '未绑定'       # US-005 /api/key/state 对账用

    def test_info_bound_other_403(self, conn):
        row = _mk_count(conn, total=5, bound_machine_guid=OTHER,
                        bound_system_name='OTHER-PC')
        err = _exc(lambda: service.info(conn, key=row['key_plaintext'],
                                        machine_guid=GUID))
        assert (err.status_code, err.message) == (403, MSG_NOT_BOUND_THIS)

    def test_info_missing_404(self, conn):
        err = _exc(lambda: service.info(conn, key='MS-AAAAA-BBBBB-CCCCC',
                                        machine_guid=GUID))
        assert (err.status_code, err.message) == (404, MSG_KEY_NOT_FOUND)

    def test_info_readonly_no_accounting(self, conn):
        row = _mk_count(conn, total=5)
        _bound_here(conn, row)
        service.info(conn, key=row['key_plaintext'], machine_guid=GUID)
        assert repo.get_key(conn, row['id'])['used_uses'] == 0
        assert repo.list_daily_usage(conn, row['id']) == []
        assert repo.list_ops(conn, row['id']) == []   # 只读不动任何账


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

class TestValidate:
    def _active_count(self, conn, total=5, used=0) -> dict:
        row = _mk_count(conn, total=total, bound_machine_guid=GUID,
                        used_uses=used)
        return row

    def _active_duration(self, conn, days=10) -> dict:
        row = _mk_duration(conn, days=days)
        _bound_here(conn, row)
        return repo.get_key(conn, row['id'])

    def test_validate_count_deduct_true(self, conn):
        row = self._active_count(conn, total=5)
        payload = service.validate(conn, key=row['key_plaintext'],
                                   machine_guid=GUID, deduct=True)
        fresh = repo.get_key(conn, row['id'])
        assert fresh['used_uses'] == 1
        assert payload['remaining_uses'] == 4
        assert payload['status'] == '正在使用'
        today = repo.list_daily_usage(conn, row['id'])
        assert today == [{'ymd': models.ymd_of(models.now()), 'count': 1}]
        assert repo.list_ops(conn, row['id'])[0]['op'] == 'validate_deduct'

    def test_validate_count_deduct_false_no_accounting(self, conn):
        row = self._active_count(conn, total=5)
        payload = service.validate(conn, key=row['key_plaintext'],
                                   machine_guid=GUID, deduct=False)
        assert payload['remaining_uses'] == 5
        assert repo.get_key(conn, row['id'])['used_uses'] == 0
        assert repo.list_daily_usage(conn, row['id']) == []
        assert repo.list_ops(conn, row['id']) == []   # 预检不动任何账（含 op_log）

    def test_validate_duration_deduct_true_only_daily(self, conn):
        row = self._active_duration(conn, days=10)
        payload = service.validate(conn, key=row['key_plaintext'],
                                   machine_guid=GUID, deduct=True)
        assert repo.list_daily_usage(conn, row['id'])[0]['count'] == 1
        assert repo.get_key(conn, row['id'])['used_uses'] == 0   # duration 不扣次
        assert payload['remaining_days'] == 9    # 10 天昨日激活 → 剩 9 整天
        assert repo.list_ops(conn, row['id'])[0]['op'] == 'validate_deduct'

    def test_validate_exhausted_403_with_total(self, conn):
        row = self._active_count(conn, total=3, used=3)
        err = _exc(lambda: service.validate(conn, key=row['key_plaintext'],
                                            machine_guid=GUID, deduct=True))
        assert (err.status_code, err.message) == (403, '授权次数已用完（共 3 次）')
        assert repo.list_daily_usage(conn, row['id']) == []   # 拒绝不动账

    def test_validate_expired_403_with_deadline(self, conn):
        row = _mk_duration(conn, days=5, activated=True, expired=True,
                           bound_machine_guid=GUID)
        err = _exc(lambda: service.validate(conn, key=row['key_plaintext'],
                                            machine_guid=GUID, deduct=False))
        assert err.status_code == 403
        assert err.message == f'授权已过期（截止 {row["expires_at"]}）'

    def test_validate_unbound_403(self, conn):
        row = _mk_count(conn, total=5)
        err = _exc(lambda: service.validate(conn, key=row['key_plaintext'],
                                            machine_guid=GUID, deduct=False))
        assert (err.status_code, err.message) == (403, MSG_NOT_BOUND_ANY)

    def test_validate_bound_other_403(self, conn):
        row = _mk_count(conn, total=5, bound_machine_guid=OTHER)
        err = _exc(lambda: service.validate(conn, key=row['key_plaintext'],
                                            machine_guid=GUID, deduct=False))
        assert (err.status_code, err.message) == (403, MSG_NOT_BOUND_THIS)

    def test_validate_merged_bound_here_403(self, conn):
        target = _mk_duration(conn, days=5)
        row = self._active_duration(conn, days=5)
        repo.update_key(conn, row['id'], merged_into_id=target['id'])
        err = _exc(lambda: service.validate(conn, key=row['key_plaintext'],
                                            machine_guid=GUID, deduct=False))
        assert (err.status_code, err.message) == (403, MSG_MERGED)

    def test_validate_missing_404(self, conn):
        err = _exc(lambda: service.validate(conn, key='MS-AAAAA-BBBBB-CCCCC',
                                            machine_guid=GUID, deduct=True))
        assert (err.status_code, err.message) == (404, MSG_KEY_NOT_FOUND)

