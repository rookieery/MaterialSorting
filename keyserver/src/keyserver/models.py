"""key 领域模型 —— 六态状态机 + 时间口径。

``derive_status(row, now)`` 是状态推导的**单一真相源**（FR-6）：管理台「属性」列
与消费端校验共用，任何一处的状态判定不得另写 if 链。

时间口径（FR-5）：到期判定一律用 **keyserver 服务器时钟**（消费端时钟不可信）；
时间戳落库格式 ``YYYY-MM-DD HH:MM:SS``（本地时区，naive datetime）—— SQLite
TEXT 可读、跨端比较零歧义。

六态优先级（自上而下短路，顺序即规则，改序 = 改语义）：
  1. ``merged``     已合并（merged_into_id 非空，最高优先 —— 合并后其余态无意义）
  2. ``exhausted``  已用完（count 型 used >= total）
  3. ``unbound``    未绑定（bound_machine_guid 为空）
  4. ``unactivated`` 未激活（duration 型已绑定未激活；绑定即激活默认下不出现，
                     留作计时起点切换桩，FR-6）
  5. ``expired``    已过期（duration 型已激活且 now > expires_at，严格大于）
  6. ``active``     正在使用（其余已绑定且未失效）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# 时间口径
# ---------------------------------------------------------------------------

TS_FORMAT = '%Y-%m-%d %H:%M:%S'          # 落库时间戳格式（SQLite TEXT）
YMD_FORMAT = '%Y-%m-%d'                   # key_daily_usage 主键粒度（自然日）


def now() -> datetime:
    """keyserver 服务器本地时钟（naive）—— 全部到期/记账判定的唯一时间源。"""
    return datetime.now()


def format_ts(dt: datetime) -> str:
    """datetime → 落库文本（YYYY-MM-DD HH:MM:SS）。"""
    return dt.strftime(TS_FORMAT)


def parse_ts(text: str) -> datetime:
    """落库文本 → datetime（与 format_ts 互逆）。"""
    return datetime.strptime(text, TS_FORMAT)


def ymd_of(dt: datetime) -> str:
    """datetime → 自然日文本（YYYY-MM-DD，key_daily_usage 主键）。"""
    return dt.strftime(YMD_FORMAT)


# ---------------------------------------------------------------------------
# 六态状态机
# ---------------------------------------------------------------------------

STATUS_MERGED = 'merged'
STATUS_EXHAUSTED = 'exhausted'
STATUS_UNBOUND = 'unbound'
STATUS_UNACTIVATED = 'unactivated'
STATUS_EXPIRED = 'expired'
STATUS_ACTIVE = 'active'

#: 管理台「属性」列中文标签（六态，FR-6；routes_admin / admin.html 共用）
STATUS_LABELS = {
    STATUS_MERGED: '已合并',
    STATUS_EXHAUSTED: '已用完',
    STATUS_UNBOUND: '未绑定',
    STATUS_UNACTIVATED: '未激活',
    STATUS_EXPIRED: '已过期',
    STATUS_ACTIVE: '正在使用',
}

KEY_TYPE_COUNT = 'count'
KEY_TYPE_DURATION = 'duration'
KEY_TYPES = (KEY_TYPE_COUNT, KEY_TYPE_DURATION)


def derive_status(row: Mapping[str, Any], now_dt: datetime) -> str:
    """由 key 行 + 服务器时钟推导六态之一（纯函数，无 IO）。

    ``row`` 为 keys 表行（dict / sqlite3.Row 皆可，键访问即可）；优先级见模块
    docstring，改序即改语义 —— 测试 test_models.py 六态矩阵锁定。
    """
    if row['merged_into_id'] is not None:
        return STATUS_MERGED
    if row['key_type'] == KEY_TYPE_COUNT:
        if row['used_uses'] >= row['total_uses']:
            return STATUS_EXHAUSTED
    if row['bound_machine_guid'] is None:
        return STATUS_UNBOUND
    if row['key_type'] == KEY_TYPE_DURATION:
        if row['activated_at'] is None:
            return STATUS_UNACTIVATED
        if now_dt > parse_ts(row['expires_at']):
            return STATUS_EXPIRED
    return STATUS_ACTIVE
