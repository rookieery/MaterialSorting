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
