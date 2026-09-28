"""derive_status 六态矩阵单测（US-001 AC4）—— 状态机单一真相源的行为锁。"""
from __future__ import annotations

from datetime import datetime, timedelta

from keyserver import models
from keyserver.models import derive_status


NOW = datetime(2026, 9, 28, 12, 0, 0)


def _count_row(**over):
    row = {
        'key_type': 'count', 'total_uses': 5, 'used_uses': 0,
        'duration_days': None, 'activated_at': None, 'expires_at': None,
        'bound_machine_guid': None, 'merged_into_id': None,
    }
    row.update(over)
    return row


def _duration_row(**over):
    row = _count_row(
        key_type='duration', total_uses=None, duration_days=30,
        activated_at='2026-09-01 00:00:00', expires_at='2026-10-01 00:00:00',
    )
    row.update(over)
    return row


# --- merged（最高优先，压过其余一切态） -----------------------------------

def test_merged_beats_everything():
    assert derive_status(_count_row(merged_into_id=7), NOW) == 'merged'
    assert derive_status(_duration_row(merged_into_id=7), NOW) == 'merged'
    # 已用完 + 已合并 → merged 优先
    assert derive_status(
        _count_row(total_uses=5, used_uses=5, merged_into_id=7), NOW) == 'merged'


# --- exhausted（count 型 used >= total） -----------------------------------

def test_count_exhausted():
    assert derive_status(
        _count_row(bound_machine_guid='guid-1', total_uses=5, used_uses=5), NOW
    ) == 'exhausted'
    assert derive_status(
        _count_row(bound_machine_guid='guid-1', total_uses=5, used_uses=6), NOW
    ) == 'exhausted'   # 超扣保护口径下不应出现，但推导需稳


def test_count_active_when_remaining():
    assert derive_status(
        _count_row(bound_machine_guid='guid-1', total_uses=5, used_uses=4), NOW
    ) == 'active'


def test_count_unbound_when_never_bound():
    assert derive_status(_count_row(), NOW) == 'unbound'
    assert derive_status(
        _count_row(total_uses=5, used_uses=0), NOW) == 'unbound'


# --- unbound（duration 型同理） ---------------------------------------------

def test_duration_unbound():
    assert derive_status(_duration_row(activated_at=None, expires_at=None), NOW) == 'unbound'


# --- unactivated（已绑定未激活；绑定即激活默认下不出现，FR-6 留桩） ----------

def test_duration_unactivated():
    assert derive_status(
        _duration_row(activated_at=None, expires_at=None, bound_machine_guid='guid-1'),
        NOW) == 'unactivated'


# --- expired（严格大于；恰好到期那一刻仍 active） ---------------------------

def test_duration_expired():
    assert derive_status(
        _duration_row(bound_machine_guid='guid-1',
                      expires_at='2026-09-27 23:59:59'), NOW) == 'expired'


def test_duration_active_before_expiry():
    row = _duration_row(bound_machine_guid='guid-1')
    assert derive_status(row, NOW) == 'active'
    # now == expires_at（恰好到期）→ 未越界，仍 active（严格大于口径）
    assert derive_status(row, datetime(2026, 10, 1, 0, 0, 0)) == 'active'
    assert derive_status(row, datetime(2026, 10, 1, 0, 0, 1)) == 'expired'


# --- 状态常量与中文标签 -------------------------------------------------------

def test_status_labels_cover_six_states():
    assert set(models.STATUS_LABELS) == {
        'merged', 'exhausted', 'unbound', 'unactivated', 'expired', 'active'}
    assert models.STATUS_LABELS['active'] == '正在使用'
    assert models.STATUS_LABELS['merged'] == '已合并'


def test_ts_format_roundtrip():
    assert models.format_ts(NOW) == '2026-09-28 12:00:00'
    assert models.parse_ts('2026-09-28 12:00:00') == NOW
    assert models.ymd_of(NOW) == '2026-09-28'
    assert (NOW + timedelta(days=1)).strftime(models.YMD_FORMAT) == '2026-09-29'
