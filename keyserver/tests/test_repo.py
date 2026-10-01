"""repo.py 三表读写单测（US-001 AC6）+ 依赖方向红线 AST 守卫。"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from keyserver import models, repo

SRC_ROOT = Path(repo.__file__).resolve().parents[1]   # keyserver/src/keyserver


# ---------------------------------------------------------------------------
# 依赖方向红线：keyserver 是独立系统，禁 import materialsorting
# ---------------------------------------------------------------------------

def test_keyserver_never_imports_materialsorting():
    for py in SRC_ROOT.rglob('*.py'):
        if '__pycache__' in py.parts:
            continue
        tree = ast.parse(py.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                assert not name.startswith('materialsorting'), (
                    py.name + ' 违反依赖红线: import ' + name)


# ---------------------------------------------------------------------------
# keys 表
# ---------------------------------------------------------------------------

def test_create_count_key_returns_full_row(conn):
    row = repo.create_key(conn, 'count', total_uses=10, remark='测试卡')
    assert row['key_plaintext'].startswith('MS-')
    assert row['key_type'] == 'count'
    assert row['total_uses'] == 10
    assert row['used_uses'] == 0
    assert row['duration_days'] is None
    assert row['bound_machine_guid'] is None
    assert row['merged_into_id'] is None
    assert row['created_at'] and row['updated_at']


def test_create_duration_key_defaults_unactivated(conn):
    row = repo.create_key(conn, 'duration', duration_days=30)
    assert row['key_type'] == 'duration'
    assert row['duration_days'] == 30
    assert row['activated_at'] is None and row['expires_at'] is None


def test_created_keys_unique_and_fetchable(conn):
    a = repo.create_key(conn, 'count', total_uses=1)
    b = repo.create_key(conn, 'count', total_uses=1)
    assert a['key_plaintext'] != b['key_plaintext']
    assert repo.get_key(conn, a['id'])['id'] == a['id']
    assert repo.get_key_by_plaintext(conn, b['key_plaintext'])['id'] == b['id']
    assert repo.get_key(conn, 99999) is None
    assert repo.get_key_by_plaintext(conn, 'MS-ZZZZZ-ZZZZZ-ZZZZZ') is None


def test_list_keys_newest_first(conn):
    ids = [repo.create_key(conn, 'count', total_uses=1)['id'] for _ in range(3)]
    assert [r['id'] for r in repo.list_keys(conn)] == list(reversed(ids))


def test_list_keys_by_machine_filters_and_orders(conn):
    """US-011：只按 bound_machine_guid 过滤（无状态判定）+ 新→旧；他机/未绑排除。"""
    mine = [repo.create_key(conn, 'count', total_uses=1)['id'] for _ in range(3)]
    repo.update_key(conn, mine[1], bound_machine_guid='guid-1', bound_system_name='PC')
    repo.update_key(conn, mine[2], bound_machine_guid='guid-1', bound_system_name='PC')
    other = repo.create_key(conn, 'count', total_uses=1)['id']
    repo.update_key(conn, other, bound_machine_guid='guid-2', bound_system_name='PC')
    repo.create_key(conn, 'count', total_uses=1)          # 未绑定
    assert [r['id'] for r in repo.list_keys_by_machine(conn, 'guid-1')] == [mine[2], mine[1]]
    assert repo.list_keys_by_machine(conn, 'guid-none') == []


def test_update_key_whitelist_and_updated_at_refresh(conn):
    row = repo.create_key(conn, 'count', total_uses=10)
    past = datetime(2020, 1, 1)
    updated = repo.update_key(
        conn, row['id'], now_dt=past, used_uses=3,
        bound_machine_guid='guid-1', bound_system_name='PC-A', remark='改名')
    assert updated['used_uses'] == 3
    assert updated['bound_machine_guid'] == 'guid-1'
    assert updated['remark'] == '改名'
    assert updated['updated_at'] == models.format_ts(past)
    assert updated['created_at'] == row['created_at']


def test_update_key_rejects_unknown_columns(conn):
    row = repo.create_key(conn, 'count', total_uses=1)
    with pytest.raises(ValueError):
        repo.update_key(conn, row['id'], key_plaintext='MS-HACKD-HACKD-HACKD')
    with pytest.raises(ValueError):
        repo.update_key(conn, row['id'], key_type='duration')


def test_update_missing_key_returns_none(conn):
    assert repo.update_key(conn, 99999, remark='无此人') is None


def test_delete_key_removes_row_and_dependents(conn):
    row = repo.create_key(conn, 'count', total_uses=5)
    repo.bump_daily_usage(conn, row['id'], '2026-09-28')
    repo.log_op(conn, row['id'], 'create')
    assert repo.delete_key(conn, row['id']) is True
    assert repo.get_key(conn, row['id']) is None
    assert repo.list_daily_usage(conn, row['id']) == []
    assert repo.list_ops(conn, row['id']) == []
    assert repo.delete_key(conn, row['id']) is False


# ---------------------------------------------------------------------------
# key_daily_usage
# ---------------------------------------------------------------------------

def test_bump_daily_usage_upsert_accumulates(conn):
    row = repo.create_key(conn, 'count', total_uses=100)
    assert repo.bump_daily_usage(conn, row['id'], '2026-09-27') == 1
    assert repo.bump_daily_usage(conn, row['id'], '2026-09-27') == 2
    assert repo.bump_daily_usage(conn, row['id'], '2026-09-28') == 1
    assert repo.list_daily_usage(conn, row['id']) == [
        {'ymd': '2026-09-27', 'count': 2}, {'ymd': '2026-09-28', 'count': 1}]


def test_bump_daily_usage_defaults_to_server_today(conn):
    row = repo.create_key(conn, 'count', total_uses=100)
    today = models.ymd_of(models.now())
    assert repo.bump_daily_usage(conn, row['id']) == 1
    assert [r['ymd'] for r in repo.list_daily_usage(conn, row['id'])] == [today]


# ---------------------------------------------------------------------------
# usage_stats 三指标（FR-14 口径）
# ---------------------------------------------------------------------------

def _seed_usage(conn, key_id, by_day):
    for ymd, n in by_day.items():
        repo.bump_daily_usage(conn, key_id, ymd, delta=n)


def test_usage_stats_none_without_records(conn):
    row = repo.create_key(conn, 'count', total_uses=100)
    assert repo.usage_stats(conn, row['id']) is None


def test_usage_stats_same_day_denominator_one(conn):
    row = repo.create_key(conn, 'count', total_uses=100)
    _seed_usage(conn, row['id'], {'2026-09-28': 7})
    stats = repo.usage_stats(conn, row['id'], today_ymd='2026-09-28')
    assert stats == {'total': 7, 'max_daily': 7, 'avg_daily': 7.0,
                     'first_used': '2026-09-28'}


def test_usage_stats_avg_over_days_since_first_use(conn):
    row = repo.create_key(conn, 'count', total_uses=100)
    _seed_usage(conn, row['id'], {'2026-09-26': 2, '2026-09-27': 2, '2026-09-28': 6})
    stats = repo.usage_stats(conn, row['id'], today_ymd='2026-09-28')
    assert stats['total'] == 10
    assert stats['max_daily'] == 6
    assert stats['avg_daily'] == 3.3
    assert stats['first_used'] == '2026-09-26'


def test_usage_stats_gap_days_counted(conn):
    row = repo.create_key(conn, 'count', total_uses=100)
    _seed_usage(conn, row['id'], {'2026-09-20': 1, '2026-09-28': 1})
    stats = repo.usage_stats(conn, row['id'], today_ymd='2026-09-28')
    assert stats['total'] == 2
    assert stats['avg_daily'] == 0.2


# ---------------------------------------------------------------------------
# bound_systems（绑定系统名列表：行由 keys 派生，本表只挂靠系统级备注）
# ---------------------------------------------------------------------------

def _mk_bound(conn, system_name, **fields) -> dict:
    row = repo.create_key(conn, 'count', total_uses=100)
    extra = {'bound_machine_guid': f'guid-{row["id"]}',   # 每把不同机器：同名跨机器合并为一行
             'bound_system_name': system_name}
    extra.update(fields)
    repo.update_key(conn, row['id'], **extra)
    return repo.get_key(conn, row['id'])


def test_list_bound_systems_groups_counts_and_joins_remark(conn):
    """派生行按系统名分组（不同机器同名合并）；未绑定 key 不参与；备注 LEFT JOIN。"""
    repo.create_key(conn, 'count', total_uses=5)             # 未绑定 → 不参与
    _mk_bound(conn, 'SYS-A')
    _mk_bound(conn, 'SYS-A')
    _mk_bound(conn, 'SYS-B')
    repo.upsert_system_remark(conn, 'SYS-A', '一号工厂')
    rows = repo.list_bound_systems(conn)
    assert [(r['system_name'], r['key_count'], r['remark']) for r in rows] == [
        ('SYS-B', 1, None),        # 新→旧 = 最新 key id 倒序
        ('SYS-A', 2, '一号工厂'),
    ]


def test_list_bound_systems_counts_unmerged_expired_members(conn):
    """行成员口径 = 未删除的全部 key（已过期/已用完/已合并均算）。"""
    dur = repo.create_key(conn, 'duration', duration_days=1)
    repo.update_key(conn, dur['id'], bound_machine_guid='g', bound_system_name='SYS-C',
                    activated_at='2026-01-01 00:00:00',
                    expires_at='2026-01-02 00:00:00')         # 已过期
    _mk_bound(conn, 'SYS-C', used_uses=100)                   # 已用完
    target = repo.create_key(conn, 'duration', duration_days=5)
    _mk_bound(conn, 'SYS-C', merged_into_id=target['id'])     # 已合并
    rows = repo.list_bound_systems(conn)
    assert rows[0]['system_name'] == 'SYS-C'
    assert rows[0]['key_count'] == 3


def test_system_usage_stats_merges_daily_series(conn):
    """日序列合并：同日多 key 使用相加后按 FR-14 公式算三指标（峰不重复计）。"""
    k1 = _mk_bound(conn, 'SYS-A')
    k2 = _mk_bound(conn, 'SYS-A')
    other = _mk_bound(conn, 'SYS-B')
    _seed_usage(conn, k1['id'], {'2026-09-26': 2, '2026-09-27': 5})
    _seed_usage(conn, k2['id'], {'2026-09-27': 3, '2026-09-28': 1})
    _seed_usage(conn, other['id'], {'2026-09-27': 99})        # 他系统不计入
    stats = repo.system_usage_stats(conn, 'SYS-A', today_ymd='2026-09-28')
    # 合并日序列：09-26=2, 09-27=5+3=8, 09-28=1 → 共11 峰8 均 11/3=3.7
    assert stats == {'total': 11, 'max_daily': 8, 'avg_daily': 3.7,
                     'first_used': '2026-09-26'}


def test_system_usage_stats_none_without_any_records(conn):
    _mk_bound(conn, 'SYS-A')
    assert repo.system_usage_stats(conn, 'SYS-A') is None


def test_upsert_system_remark_insert_update_and_clear(conn):
    _mk_bound(conn, 'SYS-A')
    repo.upsert_system_remark(conn, 'SYS-A', '初值')
    repo.upsert_system_remark(conn, 'SYS-A', '改后')          # 冲突走 UPDATE
    rows = repo.list_bound_systems(conn)
    assert rows[0]['remark'] == '改后'
    repo.upsert_system_remark(conn, 'SYS-A', '')              # 空串 = 清除 → 存 NULL
    assert repo.list_bound_systems(conn)[0]['remark'] is None


def test_system_has_keys_truth_table(conn):
    assert repo.system_has_keys(conn, 'SYS-A') is False
    _mk_bound(conn, 'SYS-A')
    assert repo.system_has_keys(conn, 'SYS-A') is True


def test_delete_system_if_orphaned_only_when_no_keys_left(conn):
    a1 = _mk_bound(conn, 'SYS-A')
    a2 = _mk_bound(conn, 'SYS-A')
    repo.upsert_system_remark(conn, 'SYS-A', '备注')
    assert repo.delete_system_if_orphaned(conn, 'SYS-A') is False   # 仍有 key
    assert repo.list_bound_systems(conn)[0]['remark'] == '备注'
    repo.delete_key(conn, a2['id'])
    assert repo.delete_system_if_orphaned(conn, 'SYS-A') is False   # 还剩 1 把
    repo.delete_key(conn, a1['id'])
    assert repo.delete_system_if_orphaned(conn, 'SYS-A') is True    # 全删 → 行消失
    assert repo.list_bound_systems(conn) == []
    assert repo.delete_system_if_orphaned(conn, 'SYS-A') is False   # 幂等可重入
    assert repo.delete_system_if_orphaned(conn, None) is False      # 未绑定哨兵


# ---------------------------------------------------------------------------
# key_op_log
# ---------------------------------------------------------------------------

def test_log_op_records_json_detail_and_order(conn):
    row = repo.create_key(conn, 'count', total_uses=1)
    dt = datetime(2026, 9, 28, 8, 30, 0)
    repo.log_op(conn, row['id'], 'create',
                {'key_type': 'count', 'total_uses': 1}, now_dt=dt)
    repo.log_op(conn, row['id'], 'validate_deduct', None,
                now_dt=dt + timedelta(seconds=5))
    ops = repo.list_ops(conn, row['id'])
    assert [o['op'] for o in ops] == ['validate_deduct', 'create']
    assert json.loads(ops[1]['detail']) == {'key_type': 'count', 'total_uses': 1}
    assert ops[0]['detail'] is None
    assert ops[0]['ts'] == '2026-09-28 08:30:05'
    assert len(repo.list_ops(conn)) == 2


def test_log_op_allows_null_key_id(conn):
    repo.log_op(conn, None, 'system_note', {'note': '与 key 无关'})
    assert repo.list_ops(conn)[0]['key_id'] is None


def test_last_used_at_none_without_validate_deduct(conn):
    """从未使用（只有 create/bind 等非使用 op）→ None；其他 op 不计入口径。"""
    row = repo.create_key(conn, 'count', total_uses=5)
    repo.log_op(conn, row['id'], 'bind', {'machine_guid': 'g'})
    assert repo.last_used_at(conn, row['id']) is None


def test_last_used_at_returns_latest_validate_deduct_ts(conn):
    """口径 = 最近一条 validate_deduct 的 ts（文本字典序即时序，MAX 即最近）。"""
    row = repo.create_key(conn, 'count', total_uses=5)
    dt = datetime(2026, 9, 28, 8, 30, 0)
    repo.log_op(conn, row['id'], 'validate_deduct', None, now_dt=dt)
    repo.log_op(conn, row['id'], 'renew', None, now_dt=dt + timedelta(days=1))
    repo.log_op(conn, row['id'], 'validate_deduct', None,
                now_dt=dt + timedelta(days=1, seconds=3))
    assert repo.last_used_at(conn, row['id']) == '2026-09-29 08:30:03'


def test_last_used_at_missing_key_and_delete_cleanup(conn):
    assert repo.last_used_at(conn, 999) is None
    row = repo.create_key(conn, 'count', total_uses=5)
    repo.log_op(conn, row['id'], 'validate_deduct', None)
    repo.delete_key(conn, row['id'])   # 连带清 op_log → 复查回 None
    assert repo.last_used_at(conn, row['id']) is None


# ---------------------------------------------------------------------------
# 与 models 联动：库内行直接喂 derive_status（单一真相源贯穿数据层）
# ---------------------------------------------------------------------------

def test_repo_row_feeds_derive_status(conn):
    row = repo.create_key(conn, 'count', total_uses=2, remark='r')
    assert models.derive_status(row, models.now()) == 'unbound'
    repo.update_key(conn, row['id'], bound_machine_guid='g1', used_uses=2)
    assert models.derive_status(
        repo.get_key(conn, row['id']), models.now()) == 'exhausted'


def test_duration_row_lifecycle_through_repo(conn):
    row = repo.create_key(conn, 'duration', duration_days=7)
    repo.update_key(
        conn, row['id'],
        bound_machine_guid='g1', activated_at='2026-09-28 00:00:00',
        expires_at=models.format_ts(models.now() + timedelta(days=7)))
    status = models.derive_status(repo.get_key(conn, row['id']), models.now())
    assert status == 'active'
