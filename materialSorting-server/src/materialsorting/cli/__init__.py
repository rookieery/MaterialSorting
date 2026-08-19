"""CLI 子包：配置文件驱动的排料求解（ms-run-config），不依赖浏览器工作台。

分层位置（依赖单向，禁反向）：

    cli  →  web  →  nesting_engine  →  nesting_bounds  →  dxf_parser

cli 是最上层编排者：只 import 底层原语（dxf_parser / nesting_bounds / nesting_engine）
与 web 层的求解封装（web.solver），**绝不 import web.server**（server.py 是 FastAPI
服务进程，携带上传/WS/导出等 Web 事实源副作用）。CLI 产物只落 out/config_runs/
（paths.CONFIG_RUNS_DIR），物理隔离于 web 事实源（out/sparrow_baseline/ 与 out/uploads/）。
"""
