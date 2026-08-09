"""MaterialSorting —— 牛仔裤排料（marker making）引擎与可视化工作台。

子包：
    dxf_parser      母版/单裁片 DXF 解析（reader/geometry/model + explore/export_dxf CLI）
    nesting_bounds  裁片加载：单裁片 → 布纹对齐 → 归一化 → 成对镜像展开
    nesting_engine  sparrow 排料求解 + v0.3 约束层（constraints）+ 实验
    web             FastAPI + WebSocket 可视化工作台与导出

依赖方向（单向，禁反向）：
    web → nesting_engine → nesting_bounds → dxf_parser

路径常量集中在 paths.py（数据/产物/前端静态目录）。
"""
