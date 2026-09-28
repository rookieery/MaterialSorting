"""统一错误出口：keyserver 业务 4xx/5xx 一律 ``{"error": "中文"}``。

消费端（US-004 ``web/keygate.py`` 的契约）直接透传 ``error`` 字段给排料用户，
因此 keyserver **不得**用 FastAPI 默认 HTTPException 的 ``{"detail": ...}`` 形状
报业务错误 —— 全部走 ``ApiError``（app 级 exception handler 统一转换）。
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """业务错误：status_code + 中文 message → JSONResponse ``{'error': message}``。"""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """app 级注册：ApiError → ``{"error": ...}``（含路由依赖鉴权阶段抛出的）。"""
    return JSONResponse(status_code=exc.status_code, content={'error': exc.message})
