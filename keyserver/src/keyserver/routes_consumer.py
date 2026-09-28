"""消费端四接口（US-003）：X-Client-Token 鉴权 + service 业务规则装配。

四接口（业务错误一律 ``{"error": 中文}``，US-004 keygate 透传该字段）：
  - ``POST /api/key/bind``     ``{key, machine_guid, system_name}``
  - ``POST /api/key/merge``    ``{target_key, source_keys: [...], machine_guid}``
  - ``POST /api/key/info``     ``{key, machine_guid}``
  - ``POST /api/key/validate`` ``{key, machine_guid, deduct}``

鉴权姿态镜像管理端（routes_admin，frp 修正版）：``MS_KEY_CLIENT_TOKEN`` 未设置
且无 ``MS_KEY_DEV=1`` → 消费端点族整体 403（**无 loopback 放行**——frpc 与
keyserver 同机时公网流量来源恒 127.0.0.1）；已设置缺失/错 → 401
（``secrets.compare_digest`` 常量时间）；``MS_KEY_DEV=1`` 仅在 token 未配置时
逃生。``GET /api/key/health`` 不在本族（公开探活，见 app.py）。

本层只做入参形状校验（400 中文）与连接生命周期；业务规则全在 service.py。
"""
from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Body, Depends, Header

from . import db, service
from .errors import ApiError

router = APIRouter(prefix='/api/key', tags=['consumer'])


# ---------------------------------------------------------------------------
# X-Client-Token 鉴权（请求时读 env —— 部署后设 token 无需改代码）
# ---------------------------------------------------------------------------

def require_client_token(
    x_client_token: str | None = Header(default=None, alias='X-Client-Token'),
) -> None:
    """消费端点族统一鉴权依赖（镜像 require_admin_token 姿态，见模块 docstring）。"""
    expected = os.environ.get('MS_KEY_CLIENT_TOKEN')
    if not expected:
        if os.environ.get('MS_KEY_DEV') == '1':
            return   # 本地开发逃生
        raise ApiError(403, '消费 token 未配置，请设置 MS_KEY_CLIENT_TOKEN')
    if x_client_token is None:
        raise ApiError(401, '消费 token 缺失：请携带 X-Client-Token 请求头')
    if not secrets.compare_digest(
            x_client_token.encode('utf-8'), expected.encode('utf-8')):
        raise ApiError(401, '消费 token 错误')


# ---------------------------------------------------------------------------
# 入参形状校验
# ---------------------------------------------------------------------------

def _require_str(payload: dict, field: str) -> str:
    """必填非空字符串字段（strip 后非空；缺失/类型错 → 400 中文）。"""
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f'{field} 不能为空')
    return value


# ---------------------------------------------------------------------------
# 四接口
# ---------------------------------------------------------------------------

@router.post('/bind')
def bind_key(payload: dict = Body(...), _: None = Depends(require_client_token)) -> dict:
    """绑定：``{key, machine_guid, system_name}``（system_name = hostname 快照）。"""
    key = _require_str(payload, 'key')
    machine_guid = _require_str(payload, 'machine_guid')
    system_name = _require_str(payload, 'system_name')
    conn = db.ensure_schema(db.connect())
    try:
        return service.bind(conn, key=key, machine_guid=machine_guid,
                            system_name=system_name)
    finally:
        conn.close()


@router.post('/merge')
def merge_keys(payload: dict = Body(...), _: None = Depends(require_client_token)) -> dict:
    """合并：``{target_key, source_keys: [...], machine_guid}`` —— 剩余时长秒级
    转移进 target，source 置 merged 保留；任一前置违反整体 400/404（无部分合并）。"""
    target_key = _require_str(payload, 'target_key')
    machine_guid = _require_str(payload, 'machine_guid')
    raw_sources = payload.get('source_keys')
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ApiError(400, 'source_keys 必须为非空 key 列表')
    if not all(isinstance(k, str) and k.strip() for k in raw_sources):
        raise ApiError(400, 'source_keys 必须为 key 字符串列表')
    conn = db.ensure_schema(db.connect())
    try:
        return service.merge(conn, target_key=target_key,
                             source_keys=raw_sources, machine_guid=machine_guid)
    finally:
        conn.close()


@router.post('/info')
def key_info(payload: dict = Body(...), _: None = Depends(require_client_token)) -> dict:
    """只读现查：``{key, machine_guid}``（绑定他机 403；未绑定 200 带 status）。"""
    key = _require_str(payload, 'key')
    machine_guid = _require_str(payload, 'machine_guid')
    conn = db.ensure_schema(db.connect())
    try:
        return service.info(conn, key=key, machine_guid=machine_guid)
    finally:
        conn.close()


@router.post('/validate')
def validate_key(payload: dict = Body(...), _: None = Depends(require_client_token)) -> dict:
    """校验扣次：``{key, machine_guid, deduct}``（deduct 缺省 false = 预检不动账）。"""
    key = _require_str(payload, 'key')
    machine_guid = _require_str(payload, 'machine_guid')
    deduct = payload.get('deduct', False)
    if not isinstance(deduct, bool):
        raise ApiError(400, 'deduct 必须为布尔值')
    conn = db.ensure_schema(db.connect())
    try:
        return service.validate(conn, key=key, machine_guid=machine_guid, deduct=deduct)
    finally:
        conn.close()

