"""管理端五接口（US-002）：X-Admin-Token 鉴权 + key 全生命周期管理。

鉴权姿态（frp 修正版）：
  - ``MS_KEY_ADMIN_TOKEN`` 未设置且无 ``MS_KEY_DEV=1`` → 管理端点族整体 403
    「管理 token 未配置，请设置 MS_KEY_ADMIN_TOKEN」。**不做 loopback 放行兜底**：
    frpc 与 keyserver 同机部署时公网流量来源 IP 恒为 127.0.0.1，loopback 兜底
    等于公网裸奔（决策台账 2026-09-28）。
  - token 已设置时缺失/错误 → 401（``secrets.compare_digest`` 常量时间比较，
    防时序侧信道逐字节猜 token）。
  - ``MS_KEY_DEV=1`` = 本地开发逃生（跳过管理 token 校验，仅限本机调试）。

五接口 + 系统级两接口（响应体业务错误一律 ``{"error": 中文}``，见 errors.py）：
  - ``GET    /api/admin/keys``            全量列表（新→旧）
  - ``POST   /api/admin/keys``            新建（count/duration）→ 201 返回明文
  - ``POST   /api/admin/keys/{id}/renew`` 续期（count 加次数 / duration 加天数）
  - ``PUT    /api/admin/keys/{id}``       改备注名（保存即生效；UI 已不再调用，兼容保留）
  - ``DELETE /api/admin/keys/{id}``       删除（active 态需 ``?force=true`` 二次确认；
                                          删后级联清理无 key 系统的 bound_systems 行）
  - ``GET    /api/admin/systems``         绑定系统名列表（keys 分组派生 + 系统级备注
                                          + 合并日序列使用统计，绑定系统名列表表格）
  - ``PUT    /api/admin/systems/{name}``  改系统级备注（系统名下无 key → 404）

每操作写 ``key_op_log``（create/renew/edit/delete/edit_system_remark，FR-16）。
"""
from __future__ import annotations

import os
import secrets
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Query

from . import db, repo
from .errors import ApiError
from .models import (
    KEY_TYPE_COUNT,
    KEY_TYPE_DURATION,
    STATUS_ACTIVE,
    STATUS_LABELS,
    derive_status,
    format_ts,
    now,
    parse_ts,
)

router = APIRouter(prefix='/api/admin', tags=['admin'])


# ---------------------------------------------------------------------------
# X-Admin-Token 鉴权（请求时读 env —— 部署后设 token 无需改代码）
# ---------------------------------------------------------------------------

def require_admin_token(
    x_admin_token: str | None = Header(default=None, alias='X-Admin-Token'),
) -> None:
    """管理端点族统一鉴权依赖（frp 修正版姿态，见模块 docstring）。"""
    expected = os.environ.get('MS_KEY_ADMIN_TOKEN')
    if not expected:
        if os.environ.get('MS_KEY_DEV') == '1':
            return   # 本地开发逃生
        raise ApiError(403, '管理 token 未配置，请设置 MS_KEY_ADMIN_TOKEN')
    if x_admin_token is None:
        raise ApiError(401, '管理 token 缺失：请携带 X-Admin-Token 请求头')
    if not secrets.compare_digest(
            x_admin_token.encode('utf-8'), expected.encode('utf-8')):
        raise ApiError(401, '管理 token 错误')


# ---------------------------------------------------------------------------
# 入参校验 / 行序列化
# ---------------------------------------------------------------------------

def _positive_int(value: Any) -> bool:
    """正整数判定（bool 是 int 子类，True 会伪装成 1 —— 显式排除）。"""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _detail_of(row: dict[str, Any]) -> str:
    """「详细信息」列文本：次数 N/M；时长 未激活 N天 / 已激活 起 ~ 止。"""
    if row['key_type'] == KEY_TYPE_COUNT:
        return f"{row['used_uses']}/{row['total_uses']}"
    if row['activated_at'] is None:
        return f"{row['duration_days']}天"
    return f"{row['activated_at']} ~ {row['expires_at']}"


def _summarize(conn, row: dict[str, Any]) -> dict[str, Any]:
    """key 行 → 管理台列表/单条契约（status = 六态中文标签，FR-6 单一真相源）。"""
    return {
        'id': row['id'],
        'key_plaintext': row['key_plaintext'],
        'key_type': row['key_type'],
        'detail': _detail_of(row),
        'status': STATUS_LABELS[derive_status(row, now())],
        'last_used_at': repo.last_used_at(conn, row['id']),  # 最近一次 validate_deduct；从未使用 → None → null
        'bound_system_name': row['bound_system_name'],
        'remark': row['remark'],
        'usage_stats': repo.usage_stats(conn, row['id']),   # 无使用记录 → None → null
        'created_at': row['created_at'],
    }


def _get_key_or_404(conn, key_id: int) -> dict[str, Any]:
    row = repo.get_key(conn, key_id)
    if row is None:
        raise ApiError(404, 'key 不存在')
    return row


# ---------------------------------------------------------------------------
# 五接口
# ---------------------------------------------------------------------------

@router.get('/keys')
def list_keys(_: None = Depends(require_admin_token)) -> dict:
    """全量 key 列表（新→旧）。"""
    conn = db.ensure_schema(db.connect())
    try:
        return {'keys': [_summarize(conn, row) for row in repo.list_keys(conn)]}
    finally:
        conn.close()


@router.post('/keys', status_code=201)
def create_key(
    payload: dict = Body(...),
    _: None = Depends(require_admin_token),
) -> dict:
    """新建 key：``{key_type:'count', total_uses:N}`` 或
    ``{key_type:'duration', duration_days:N}``，可选 ``remark``。返回含此刻生成的明文。"""
    conn = db.ensure_schema(db.connect())
    try:
        key_type = payload.get('key_type')
        if key_type not in (KEY_TYPE_COUNT, KEY_TYPE_DURATION):
            raise ApiError(400, 'key_type 必须为 count 或 duration')
        remark = payload.get('remark')
        if remark is not None and not isinstance(remark, str):
            raise ApiError(400, 'remark 必须为字符串')
        if key_type == KEY_TYPE_COUNT:
            total_uses = payload.get('total_uses')
            if not _positive_int(total_uses):
                raise ApiError(400, 'total_uses 必须为正整数')
            row = repo.create_key(conn, key_type, total_uses=total_uses, remark=remark)
            op_detail = {'key_type': key_type, 'total_uses': total_uses, 'remark': remark}
        else:
            duration_days = payload.get('duration_days')
            if not _positive_int(duration_days):
                raise ApiError(400, 'duration_days 必须为正整数')
            row = repo.create_key(conn, key_type, duration_days=duration_days, remark=remark)
            op_detail = {'key_type': key_type, 'duration_days': duration_days, 'remark': remark}
        repo.log_op(conn, row['id'], 'create', op_detail)
        return _summarize(conn, row)
    finally:
        conn.close()


@router.post('/keys/{key_id}/renew')
def renew_key(
    key_id: int,
    payload: dict = Body(...),
    _: None = Depends(require_admin_token),
) -> dict:
    """续期：count → ``total_uses += add_uses``；duration 未激活 →
    ``duration_days += add_days``；已激活 → ``expires_at += add_days`` 天。"""
    conn = db.ensure_schema(db.connect())
    try:
        row = _get_key_or_404(conn, key_id)
        if row['key_type'] == KEY_TYPE_COUNT:
            add = payload.get('add_uses')
            if not _positive_int(add):
                raise ApiError(400, 'add_uses 必须为正整数')
            new_total = int(row['total_uses']) + add
            updated = repo.update_key(conn, key_id, total_uses=new_total)
            op_detail = {'add_uses': add, 'total_uses': new_total}
        else:
            add = payload.get('add_days')
            if not _positive_int(add):
                raise ApiError(400, 'add_days 必须为正整数')
            if row['activated_at'] is None:
                new_days = int(row['duration_days']) + add
                updated = repo.update_key(conn, key_id, duration_days=new_days)
                op_detail = {'add_days': add, 'activated': False, 'duration_days': new_days}
            else:
                new_expires = format_ts(parse_ts(row['expires_at']) + timedelta(days=add))
                updated = repo.update_key(conn, key_id, expires_at=new_expires)
                op_detail = {'add_days': add, 'activated': True, 'expires_at': new_expires}
        repo.log_op(conn, key_id, 'renew', op_detail)
        return _summarize(conn, updated or row)
    finally:
        conn.close()


@router.put('/keys/{key_id}')
def edit_key(
    key_id: int,
    payload: dict = Body(...),
    _: None = Depends(require_admin_token),
) -> dict:
    """改备注名 ``{remark}``（保存即生效；空串 = 清除备注）。"""
    conn = db.ensure_schema(db.connect())
    try:
        _get_key_or_404(conn, key_id)
        remark = payload.get('remark')
        if not isinstance(remark, str):
            raise ApiError(400, 'remark 必须为字符串')
        updated = repo.update_key(conn, key_id, remark=remark)
        repo.log_op(conn, key_id, 'edit', {'remark': remark})
        return _summarize(conn, updated or {})
    finally:
        conn.close()


@router.delete('/keys/{key_id}')
def delete_key(
    key_id: int,
    force: str | None = Query(default=None),
    _: None = Depends(require_admin_token),
) -> dict:
    """删除：非 active 态直接删；active 且无 ``?force=true`` → 409 二次确认。

    delete 的 op_log 在物理删除**之后**落账（repo.delete_key 会连带清该 key 的
    既有日志，先写即被抹掉；后写留一条悬空 key_id 的审计痕迹是有意为之）。"""
    conn = db.ensure_schema(db.connect())
    try:
        row = _get_key_or_404(conn, key_id)
        status = derive_status(row, now())
        forced = force == 'true'
        if status == STATUS_ACTIVE and not forced:
            raise ApiError(409, '该 key 正在使用，确认删除请再次确认')
        repo.delete_key(conn, key_id)
        repo.log_op(conn, key_id, 'delete', {'force': forced, 'status': status})
        # 级联：该系统名下 key 已全删 → bound_systems 行（含系统级备注）连带清理
        repo.delete_system_if_orphaned(conn, row['bound_system_name'])
        return {'ok': True, 'id': key_id}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 绑定系统名列表（系统级两接口）
# ---------------------------------------------------------------------------

@router.get('/systems')
def list_systems(_: None = Depends(require_admin_token)) -> dict:
    """绑定系统名列表（keys 按 bound_system_name 分组派生，新→旧）。

    行成员口径 = 未删除的全部 key（含已合并/已过期/已用完）；未绑定 key 无系统
    名不参与；不同机器同名系统合并为一行。``usage_stats`` = 该系统全部 key 的
    逐日使用**合并日序列**（同日相加）后按 FR-14 公式计算的三指标。
    """
    conn = db.ensure_schema(db.connect())
    try:
        systems = []
        for row in repo.list_bound_systems(conn):
            systems.append({
                'system_name': row['system_name'],
                'remark': row['remark'],
                'key_count': int(row['key_count']),
                'usage_stats': repo.system_usage_stats(conn, row['system_name']),
            })
        return {'systems': systems}
    finally:
        conn.close()


@router.put('/systems/{system_name}')
def edit_system_remark(
    system_name: str,
    payload: dict = Body(...),
    _: None = Depends(require_admin_token),
) -> dict:
    """改系统级备注 ``{remark}``（保存即生效；空串 = 清除备注）。

    系统名在 keys 表已无任何 key → 404（行存在性由 keys 派生，不允许给
    已消失的系统留备注；删除 key 的级联清理亦同口径）。
    """
    conn = db.ensure_schema(db.connect())
    try:
        if not repo.system_has_keys(conn, system_name):
            raise ApiError(404, '该系统名下已无 key，无法编辑备注')
        remark = payload.get('remark')
        if not isinstance(remark, str):
            raise ApiError(400, 'remark 必须为字符串')
        repo.upsert_system_remark(conn, system_name, remark)
        repo.log_op(conn, None, 'edit_system_remark',
                    {'system_name': system_name, 'remark': remark})
        return {'ok': True, 'system_name': system_name,
                'remark': remark if remark else None}
    finally:
        conn.close()

