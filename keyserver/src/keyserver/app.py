"""keyserver 服务装配 + 入口。

启动：``python -m keyserver.app``（或 console_scripts ``ms-keyserver``）
  → http://127.0.0.1:8110（env ``MS_KEY_PORT`` 可覆盖，host env ``MS_KEY_HOST``
     缺省 127.0.0.1 —— frp 同机部署形态下 frpc 打 127.0.0.1，不裸露 LAN）

环境变量（与 db.py 配合）：
  - ``MS_KEY_DB``    SQLite 路径（缺省 <部署目录>/data/keys.db）
  - ``MS_KEY_PORT``  监听端口（缺省 8110）
  - ``MS_KEY_HOST``  监听地址（缺省 127.0.0.1）

路由族（US-003 起逐故事落地）：
  - ``GET /api/key/health``   存活 + DB 可写探测（幂等建表）
  - 管理端五接口 ``/api/admin/keys*``（X-Admin-Token，US-002）
  - 消费端四接口 ``/api/key/{bind,merge,info,validate}``（X-Client-Token，US-003）
  - ``GET /admin`` 管理后台可视化单页（US-008）

业务错误统一 ``{"error": 中文}``（errors.ApiError → app 级 handler；消费端
US-004 keygate 直接透传该字段）。
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from . import db
from .errors import ApiError, api_error_handler
from .routes_admin import router as admin_router
from .routes_consumer import router as consumer_router

DEFAULT_PORT = 8110
DEFAULT_HOST = '127.0.0.1'

#: 包内静态资源目录（keyserver/static/admin.html，US-008；随包打包，见 pyproject package-data）
_STATIC_DIR = Path(__file__).resolve().parent / 'static'

app = FastAPI(title='VB超排 Key 授权服务', version='0.1.0')
app.add_exception_handler(ApiError, api_error_handler)
app.include_router(admin_router)
app.include_router(consumer_router)


@app.get('/admin', include_in_schema=False)
def admin_page() -> FileResponse:
    """管理后台可视化单页（US-008）：原生 HTML + fetch，同源直出零跨域。

    页面本身是公开壳（不含任何敏感数据）：token 由使用者在登录框输入后存
    sessionStorage，全部数据经 ``/api/admin/*`` 携 ``X-Admin-Token`` 获取；
    未配置 token 的部署首查即 403「未配置」，由页面渲染配置指引文案。
    """
    return FileResponse(_STATIC_DIR / 'admin.html', media_type='text/html; charset=utf-8')


@app.get('/api/key/health')
def health() -> dict:
    """存活探测：幂等建表 + 可写验证（SELECT 1），供部署探活 / 冒烟自举。"""
    conn = db.ensure_schema(db.connect())
    try:
        conn.execute('SELECT 1').fetchone()
    finally:
        conn.close()
    return {'ok': True, 'service': 'keyserver', 'db': str(db.db_path())}


def main() -> None:
    """uvicorn 入口（console_scripts ms-keyserver / python -m keyserver.app）。"""
    import uvicorn

    # 启动即自动迁移建表（幂等）；此处失败 = 配置错误，早于端口监听暴露
    db.ensure_schema(db.connect()).close()
    uvicorn.run(
        app,
        host=os.environ.get('MS_KEY_HOST', DEFAULT_HOST),
        port=int(os.environ.get('MS_KEY_PORT', DEFAULT_PORT)),
    )


if __name__ == '__main__':   # python -m keyserver.app
    main()
