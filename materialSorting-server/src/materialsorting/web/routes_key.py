"""Key 授权管理端五端点（prd-key-authorization-system US-005 + US-011 list）。

消费端（本系统）对 keygate 的 HTTP 化封装 —— 三入口闸门（/ws/solve 与
/api/strategy|extreme/start 直接调 ``keygate.ensure_run_allowed``）之外，
用户自助管理本机授权的五个端点（US-006 前端「系统key」弹窗数据源）：

  - ``GET  /api/key/list``：本机可用 key 列表（US-011 弹窗表格数据源）。
    keyserver ``/api/key/list`` 只读透传（仅「正在使用」态 + 明文/类型/剩余）；
    keyserver 失败也 200（``keys`` 置空 + ``error`` 文案，镜像 state 容错）。
  - ``GET  /api/key/state``：本地 key + keyserver ``/api/key/info`` 只读现查。
    **keyserver 查询失败也 200**，失败文案进 ``error`` 字段（弹窗仍能展示本地
    key + 引导重试）；未绑定 → ``{key:null, info:null, error:null}``。key 已在
    keyserver 侧删除（404）→ 自动解绑（清 ``key_state.json``）+ 未绑定态响应
    带 ``error`` 解释（详见 :func:`get_key_state`）。
  - ``POST /api/key/save`` ``{key}``：先 keyserver ``/api/key/bind``（绑定
    MachineGuid + system_name=hostname 快照；业务失败中文透传 400，**不落盘**）
    → 成功才 ``save_key_state`` 落 ``key_state.json``（后端文件权威）。
  - ``POST /api/key/merge`` ``{source_keys:[...]}``：target = 本地当前 key
    （未绑定 → 400 指路文案）；keyserver 原子合并（任一 source 违反前置 →
    整体失败无部分合并），成功原样透传 ``{target, sources, total_transferred_
    days}``（sources = 每个 key 的转移天数明细）。
  - ``POST /api/key/precheck``：``keygate.ensure_run_allowed(..., deduct=False)``
    —— 判定序与真跑闸门完全一致（off / 样例标记豁免 / 无 key / validate 预检），
    唯一差异是不扣次不动账。数据源优先**会话 doc**（``X-Session-Id`` peek —— 与
    WS / 策略闸门读同一份 state，``sample`` 标记天然同源；2026-09-29 豁免收紧后
    precheck 不再按文件名自判）；会话失败/无 doc → 回落 body ``{doc_source}``
    （sample 恒 False）。响应 ``{ok:true[, reason]}`` | ``{ok:false, message}``
    （断网文案 = keygate ``MSG_UNREACHABLE``，前端不自行判断网络）。

关键约定：
  - **机器级全局，不加会话闸门**（与 ``/api/edit-hold`` 的差异：edit_hold 是
    sid 级编辑钉住，须 X-Session-Id 且过期 401；key 绑定的是 MachineGuid 机器
    身份 —— 本机全部会话/浏览器共享同一 key，随机 X-Session-Id 头也不拦）。
    precheck 读会话 doc 属**数据源偏好**而非闸门：解析失败静默回落 body，绝不
    401/429（``sessions`` 是纯标准库兄弟模块，无 fastapi 依赖面）。
  - 全部 keyserver 通信走 ``keygate._key_post`` 唯一 HTTP 出口（超时 5s、无自动
    重试、4xx 中文 ``{"error"}`` 透传），阻塞调用统一 ``asyncio.to_thread``
    （validate 最长 5s，不卡事件循环 —— machine_guid 注册表读/兜底首铸文件写
    一并在工作线程完成）。
  - 本模块失败文案 = ``str(KeyGateError)``（可直接上屏），HTTP 400 结构化
    ``{'error': 文案}``（save/merge）；state/precheck 恒 200（读/预检语义，
    结果自描述）。

分层：只依赖 keygate（兄弟模块私有复用先例）+ 标准库 + fastapi；**禁 import
本包 server / strategy / routes_ws / cli**（AST 守卫见 tests/test_web_key_routes.py，
被 server 文件尾注册 —— 反向 import 上游即成环）。注册：``register_key_routes(app)``
由 server.py 文件尾（checkpoint 注册之后）调用一次。
"""
from __future__ import annotations

import asyncio
import socket

from fastapi import Request
from fastapi.responses import JSONResponse

from . import keygate
from .sessions import SessionError, registry as session_registry

__all__ = ['register_key_routes']


def _post_keyserver(path: str, payload: dict) -> dict:
    """同步 keyserver 出口（handler 经 ``asyncio.to_thread`` 调用）。

    ``machine_guid`` 一并在工作线程取（注册表读 / 兜底首铸文件写都是阻塞面，
    不在事件循环线程做）；失败抛 :class:`keygate.KeyGateError`（文案可直接上屏）。
    """
    body = dict(payload)
    body.setdefault('machine_guid', keygate.machine_guid())
    return keygate._key_post(path, body)


def _local_key() -> str | None:
    """本地当前 key（strip 后非空）；未绑定 → None。"""
    key = keygate.load_key_state().get('key')
    if isinstance(key, str) and key.strip():
        return key.strip()
    return None


async def _json_body(request: Request):
    """请求体解析（非 JSON / 非对象 → JSONResponse 400；调用方先判 err）。"""
    try:
        payload = await request.json()
    except Exception:                                # noqa: BLE001 - 坏请求体统一 400
        return None, JSONResponse({'error': '请求体须为 JSON'}, status_code=400)
    if not isinstance(payload, dict):
        return None, JSONResponse({'error': '请求体须为 JSON 对象'}, status_code=400)
    return payload, None


async def get_key_state() -> dict:
    """本地 key + keyserver info 只读现查（keyserver 失败也 200 带 error）。

    key 已在 keyserver 侧删除（404）→ **自动解绑**：本地绑定失去意义，清
    ``key_state.json`` 后按未绑定态响应（``error`` 带一句解释上屏，用户知道
    发生了什么而不是疑惑 key 去哪了）。瞬态失败（网络/5xx/401）不清 —— 本地
    key 可能仍有效，保留等重试。
    """
    key = _local_key()
    if key is None:
        return {'key': None, 'info': None, 'error': None}
    try:
        info = await asyncio.to_thread(_post_keyserver, '/api/key/info',
                                       {'key': key})
    except keygate.KeyGateError as exc:
        if getattr(exc, 'code', None) == 404:
            await asyncio.to_thread(keygate.clear_key_state)
            return {
                'key': None, 'info': None,
                'error': '本地 key 已失效（key 不存在，可能已被删除），已自动'
                         '解除绑定；请输入新 key 并保存',
            }
        return {'key': key, 'info': None, 'error': str(exc)}
    return {'key': key, 'info': info, 'error': None}


async def get_key_list() -> dict:
    """本机可用 key 列表（US-011 弹窗「系统可使用的key」表格数据源）。

    keyserver ``/api/key/list``（仅「正在使用」态 + 明文/类型/剩余）原样透传；
    **keyserver 失败也 200**（镜像 :func:`get_key_state` 容错模式）：``keys``
    置空 + 失败文案进 ``error``（表格区红字，① 输入/保存不受影响）。
    """
    try:
        keys = await asyncio.to_thread(_post_keyserver, '/api/key/list', {})
    except keygate.KeyGateError as exc:
        return {'keys': [], 'error': str(exc)}
    return {'keys': keys.get('keys', []), 'error': None}


async def post_key_save(request: Request):
    """``{key}`` → bind 成功才落 key_state.json（bind 失败不覆盖旧 key）。"""
    payload, err = await _json_body(request)
    if err is not None:
        return err
    key = payload.get('key')
    if not isinstance(key, str) or not key.strip():
        return JSONResponse({'error': 'key 不能为空'}, status_code=400)
    key = key.strip()
    try:
        info = await asyncio.to_thread(
            _post_keyserver, '/api/key/bind',
            {'key': key, 'system_name': socket.gethostname()})
    except keygate.KeyGateError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)
    # bind 成功才落盘（原子写；fsync 阻塞面同样走工作线程）。
    await asyncio.to_thread(keygate.save_key_state, key)
    return {'saved': True, 'key': key, 'info': info}


async def post_key_merge(request: Request):
    """``{source_keys:[...]}`` → target = 本地当前 key，keyserver 原子合并。"""
    payload, err = await _json_body(request)
    if err is not None:
        return err
    raw_sources = payload.get('source_keys')
    if not isinstance(raw_sources, list) or not raw_sources:
        return JSONResponse({'error': 'source_keys 必须为非空 key 列表'},
                            status_code=400)
    if not all(isinstance(k, str) and k.strip() for k in raw_sources):
        return JSONResponse({'error': 'source_keys 必须为 key 字符串列表'},
                            status_code=400)
    key = _local_key()
    if key is None:
        return JSONResponse({'error': keygate.MSG_NO_KEY}, status_code=400)
    try:
        result = await asyncio.to_thread(
            _post_keyserver, '/api/key/merge',
            {'target_key': key, 'source_keys': [k.strip() for k in raw_sources]})
    except keygate.KeyGateError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)
    # keyserver 契约原样透传：{target: info, sources: [{key, transferred_days}],
    # total_transferred_days}（sources 即 US-006 弹窗「每个 key 成功天数」明细）。
    return result


async def post_key_precheck(request: Request) -> dict:
    """运行前预检（validate deduct=false）：与真跑闸门同判定序、不动账。

    数据源优先会话 doc（``X-Session-Id`` peek —— WS / 策略闸门读同一份 state，
    ``sample`` 标记同源不漂移）；会话不存在/过期/非法 sid → 静默回落 body
    ``doc_source``（sample 恒 False）。会话解析失败不拦请求（机器级全局无会话
    闸门，仅数据源偏好，见文件头）。
    """
    payload, _ = await _json_body(request)   # 空/坏 body 容忍为无 doc_source
    doc_source = payload.get('doc_source') if isinstance(payload, dict) else None
    sample = False
    try:
        # resolve(sid)（缺省 = default 会话，state 即 runtime._PIECES_STATE 同一
        # dict —— 与 WS 闸门口径一致）；SessionError（未知/过期/非法）→ 回落。
        state = session_registry.resolve(
            (request.headers.get('x-session-id') or '').strip() or None).state
        doc = state.get('doc') or {}
        if doc:
            doc_source = doc.get('source')
            sample = bool(doc.get('sample'))
    except SessionError:
        pass
    ok, message = await asyncio.to_thread(
        keygate.ensure_run_allowed, doc_source, False, sample)
    if not ok:
        return {'ok': False, 'message': message}
    out = {'ok': True}
    if message:               # 豁免原因（'off'/'sample'）：debug 可观测，前端忽略
        out['reason'] = message
    return out


def register_key_routes(app) -> None:
    """五端点挂到 FastAPI app（server.py 文件尾 checkpoint 注册之后调用一次）。"""
    app.get('/api/key/state')(get_key_state)
    app.get('/api/key/list')(get_key_list)
    app.post('/api/key/save')(post_key_save)
    app.post('/api/key/merge')(post_key_merge)
    app.post('/api/key/precheck')(post_key_precheck)
