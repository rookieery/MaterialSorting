"""消费端业务规则（US-003）：bind / merge / info / validate + list（US-011）。

路由层（routes_consumer）只做入参形状校验与连接生命周期；本模块持有全部业务
规则 —— 六态判定一律经 ``models.derive_status`` 单一真相源，到期/记账时间一律
``models.now()``（**keyserver 服务器时钟**，消费端时钟不可信，FR-5）。

响应契约（info / bind / validate 成功共用 ``_info_payload``，US-005 ``/api/key/state``
与 US-006 弹窗直接渲染；status 为六态中文标签）：
  - count 型:    ``{type, total_uses, used_uses, remaining_uses, status,
                   bound_system_name, remark}``
  - duration 型: ``{type, activated_at, expires_at, remaining_days, status,
                   bound_system_name, remark}``

规则要点（错误文案被消费端 keygate 原样透传给排料用户，勿随意改字）：
  - bind：未绑 → 绑定（system_name 快照 + 备注缺省=系统名）且 duration 型**绑定
    即激活起算**（activated_at=now、expires_at=now+duration_days）；已绑本机 →
    幂等 200；已绑他机 409；已用完/已过期/已合并 409。
  - merge：target 与全部 source 均须 duration 型 + 绑定本机 + 有效（未过期未合
    并）；source 剩余时长**秒级精确**转移（target.expires_at += src.expires_at
    − now），source 置 merged_into_id **保留不物理删除**（FR-4）；前置全过才动
    账，任一违反 400/404 整体失败（无部分合并）。
  - info：只读不动账；绑定他机 403；未绑定 200（status=未绑定，US-005 对账用）。
  - validate：存在 + 绑定本机 + 状态有效才通过；deduct=true 时 count 型走
    ``repo.atomic_deduct_once`` 单条原子 SQL（并发零超扣）+ 当日记账 +1（duration
    型仅记日）；deduct=false 预检专用，不动任何账（含 op_log）。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from . import repo
from .errors import ApiError
from .models import (
    KEY_TYPE_COUNT,
    KEY_TYPE_DURATION,
    STATUS_ACTIVE,
    STATUS_EXHAUSTED,
    STATUS_EXPIRED,
    STATUS_MERGED,
    STATUS_UNACTIVATED,
    STATUS_UNBOUND,
    STATUS_LABELS,
    derive_status,
    format_ts,
    now,
    parse_ts,
)

MSG_KEY_NOT_FOUND = 'key 不存在：请检查输入是否正确'
MSG_BOUND_OTHER_BIND = '该 key 已绑定其他系统，无法绑定到本机'
MSG_NOT_BOUND_ANY = '该 key 尚未绑定任何系统'
MSG_NOT_BOUND_THIS = '该 key 未绑定当前系统'
MSG_MERGED = '该 key 已合并至其他 key，无法使用'
MSG_UNACTIVATED = '该 key 尚未激活，请联系发卡方'
MSG_MERGE_SELF = '目标 key 不可同时作为被合并 key'


def _msg_exhausted(total_uses: int) -> str:
    return f'授权次数已用完（共 {total_uses} 次）'


def _msg_expired(expires_at: str) -> str:
    return f'授权已过期（截止 {expires_at}）'


def _msg_merge_not_duration(key_plaintext: str) -> str:
    return f'仅时长型 key 可合并：`{key_plaintext}` 为次数型'


def _msg_merge_not_bound_here(key_plaintext: str) -> str:
    return f'`{key_plaintext}` 未绑定当前系统，无法合并'


def _msg_merge_invalid(key_plaintext: str) -> str:
    return f'`{key_plaintext}` 已失效（过期/已合并），无法合并'


# ---------------------------------------------------------------------------
# 行 → 响应契约
# ---------------------------------------------------------------------------

def _get_key_or_404(conn, key: str) -> dict[str, Any]:
    row = repo.get_key_by_plaintext(conn, key)
    if row is None:
        raise ApiError(404, MSG_KEY_NOT_FOUND)
    return row


def _info_payload(row: dict[str, Any], now_dt: datetime) -> dict[str, Any]:
    """key 行 → info/bind/validate 响应契约（形状见模块 docstring）。"""
    payload: dict[str, Any] = {
        'type': row['key_type'],
        'status': STATUS_LABELS[derive_status(row, now_dt)],
        'bound_system_name': row['bound_system_name'],
        'remark': row['remark'],
    }
    if row['key_type'] == KEY_TYPE_COUNT:
        total = int(row['total_uses'])
        used = int(row['used_uses'])
        payload['total_uses'] = total
        payload['used_uses'] = used
        payload['remaining_uses'] = max(total - used, 0)
    else:
        if row['activated_at'] is None:
            # 未激活：时长一口未耗，剩余 = 完整 duration_days（无起止可报）
            payload['activated_at'] = None
            payload['expires_at'] = None
            payload['remaining_days'] = int(row['duration_days'])
        else:
            remaining_days = math.ceil(
                (parse_ts(row['expires_at']) - now_dt).total_seconds() / 86400.0)
            payload['activated_at'] = row['activated_at']
            payload['expires_at'] = row['expires_at']
            payload['remaining_days'] = max(remaining_days, 0)
    return payload


# ---------------------------------------------------------------------------
# bind
# ---------------------------------------------------------------------------

def bind(conn, *, key: str, machine_guid: str, system_name: str) -> dict[str, Any]:
    """绑定（FR-3）：未绑 → 绑定 + duration 型即刻激活；已绑本机 → 幂等 200。"""
    row = _get_key_or_404(conn, key)
    dt = now()
    status = derive_status(row, dt)
    if status == STATUS_MERGED:
        raise ApiError(409, MSG_MERGED)
    if status == STATUS_EXHAUSTED:
        raise ApiError(409, _msg_exhausted(int(row['total_uses'])))
    if status == STATUS_EXPIRED:
        raise ApiError(409, _msg_expired(row['expires_at']))
    if row['bound_machine_guid'] is not None:
        if row['bound_machine_guid'] != machine_guid:
            raise ApiError(409, MSG_BOUND_OTHER_BIND)
        return _info_payload(row, dt)          # 已绑本机 → 幂等（快照不回写）
    fields: dict[str, Any] = {
        'bound_machine_guid': machine_guid,
        'bound_system_name': system_name,      # 绑定时刻快照（此后改名不跟随）
    }
    if row['remark'] is None:
        fields['remark'] = system_name         # 备注缺省 = 系统名
    if row['key_type'] == KEY_TYPE_DURATION:
        fields['activated_at'] = format_ts(dt)   # 绑定即激活起算（FR 决策台账）
        fields['expires_at'] = format_ts(
            dt + timedelta(days=int(row['duration_days'])))
    updated = repo.update_key(conn, row['id'], **fields)
    repo.log_op(conn, row['id'], 'bind', {
        'machine_guid': machine_guid, 'system_name': system_name,
        'activated': row['key_type'] == KEY_TYPE_DURATION})
    return _info_payload(updated or row, dt)


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

def _assert_mergeable(row: dict[str, Any], dt: datetime, machine_guid: str) -> None:
    """merge 参与方（target 与每个 source 共用）前置校验，违反即 400 中止整体。

    unactivated（绑定未激活）经 HTTP 不可达（bind 即激活），此处按「已失效」拒
    绝 —— 无起止窗口即无可转移时长。
    """
    plaintext = row['key_plaintext']
    if row['key_type'] != KEY_TYPE_DURATION:
        raise ApiError(400, _msg_merge_not_duration(plaintext))
    if row['bound_machine_guid'] != machine_guid:   # 含未绑定（无 guid ≠ 本机）
        raise ApiError(400, _msg_merge_not_bound_here(plaintext))
    if (row['merged_into_id'] is not None or row['activated_at'] is None
            or dt > parse_ts(row['expires_at'])):
        raise ApiError(400, _msg_merge_invalid(plaintext))


def merge(
    conn, *, target_key: str, source_keys: list[str], machine_guid: str,
) -> dict[str, Any]:
    """剩余时长秒级转移（FR-4）：前置全过才动账；source 置 merged 保留不物理删除。"""
    deduped: list[str] = []            # 去重保序：同 key 贴两次不双计
    seen: set[str] = set()
    for k in source_keys:
        if k not in seen:
            seen.add(k)
            deduped.append(k)
    if target_key in seen:
        raise ApiError(400, MSG_MERGE_SELF)

    target = _get_key_or_404(conn, target_key)
    dt = now()
    _assert_mergeable(target, dt, machine_guid)

    sources: list[dict[str, Any]] = []
    for k in deduped:
        src = repo.get_key_by_plaintext(conn, k)
        if src is None:
            raise ApiError(404, MSG_KEY_NOT_FOUND)
        _assert_mergeable(src, dt, machine_guid)
        sources.append(src)

    total_seconds = 0.0
    sources_out: list[dict[str, Any]] = []
    for src in sources:
        remaining = (parse_ts(src['expires_at']) - dt).total_seconds()
        total_seconds += remaining
        repo.update_key(conn, src['id'], merged_into_id=target['id'])
        repo.log_op(conn, src['id'], 'merge_source',
                    {'into_key_id': target['id'], 'remaining_seconds': remaining})
        sources_out.append({
            'key': src['key_plaintext'],
            'transferred_days': round(remaining / 86400.0, 1),
        })
    new_expires = parse_ts(target['expires_at']) + timedelta(seconds=total_seconds)
    updated = repo.update_key(conn, target['id'], expires_at=format_ts(new_expires))
    repo.log_op(conn, target['id'], 'merge_target', {
        'from_key_ids': [s['id'] for s in sources],
        'total_seconds': total_seconds,
        'new_expires_at': format_ts(new_expires)})
    return {
        'target': _info_payload(updated or target, dt),
        'sources': sources_out,
        'total_transferred_days': round(total_seconds / 86400.0, 1),
    }


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

def info(conn, *, key: str, machine_guid: str) -> dict[str, Any]:
    """只读现查：不动任何账（无 daily_usage / op_log 写入）。"""
    row = _get_key_or_404(conn, key)
    if row['bound_machine_guid'] is not None and row['bound_machine_guid'] != machine_guid:
        raise ApiError(403, MSG_NOT_BOUND_THIS)
    return _info_payload(row, now())


# ---------------------------------------------------------------------------
# list（按机器）
# ---------------------------------------------------------------------------

def list_for_machine(conn, *, machine_guid: str) -> dict[str, Any]:
    """本机绑定的可用 key 列表（US-011）：仅供消费端「系统可使用的key」表格。

    行 = ``_info_payload`` 契约 + ``key``（明文，表格名称列）；**只保留
    ``derive_status == active``（正在使用）**——已过期/已用完/已合并/绑定他机
    的行不出（口径定案 2026-09-29：表格只展示有效 key）。只读不动账（无
    daily_usage / op_log 写入）；排序新→旧（repo.list_keys_by_machine）。
    """
    dt = now()
    keys = []
    for row in repo.list_keys_by_machine(conn, machine_guid):
        if derive_status(row, dt) != STATUS_ACTIVE:
            continue
        payload = _info_payload(row, dt)
        payload['key'] = row['key_plaintext']
        keys.append(payload)
    return {'keys': keys}


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def validate(
    conn, *, key: str, machine_guid: str, deduct: bool = False,
) -> dict[str, Any]:
    """运行前校验（FR-12）：通过 = 存在 + 绑定本机 + 状态有效；deduct=true 扣次记账。"""
    row = _get_key_or_404(conn, key)
    dt = now()
    status = derive_status(row, dt)
    if status == STATUS_UNBOUND:
        raise ApiError(403, MSG_NOT_BOUND_ANY)
    if row['bound_machine_guid'] != machine_guid:
        raise ApiError(403, MSG_NOT_BOUND_THIS)
    if status == STATUS_MERGED:
        raise ApiError(403, MSG_MERGED)
    if status == STATUS_EXHAUSTED:
        raise ApiError(403, _msg_exhausted(int(row['total_uses'])))
    if status == STATUS_EXPIRED:
        raise ApiError(403, _msg_expired(row['expires_at']))
    if status == STATUS_UNACTIVATED:      # 经 HTTP 不可达（bind 即激活），防御保留
        raise ApiError(403, MSG_UNACTIVATED)
    if not deduct:
        return _info_payload(row, dt)     # 预检专用：不动任何账（含 op_log）
    if row['key_type'] == KEY_TYPE_COUNT:
        if not repo.atomic_deduct_once(conn, row['id']):
            # 并发败者：预检读到余额后被抢扣 —— 同一「次数已用完」语义
            raise ApiError(403, _msg_exhausted(int(row['total_uses'])))
        fresh = repo.get_key(conn, row['id'])
        repo.bump_daily_usage(conn, row['id'])
        repo.log_op(conn, row['id'], 'validate_deduct', {
            'key_type': KEY_TYPE_COUNT,
            'remaining_uses': int(fresh['total_uses']) - int(fresh['used_uses'])})
        return _info_payload(fresh, dt)
    repo.bump_daily_usage(conn, row['id'])   # duration 型仅记日（used_uses 不动）
    repo.log_op(conn, row['id'], 'validate_deduct', {'key_type': KEY_TYPE_DURATION})
    return _info_payload(row, dt)

