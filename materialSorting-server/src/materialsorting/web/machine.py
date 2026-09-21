"""机器对接排料 API（YL 排料对接二期，prd-machine-nesting-api）—— 骨架模块。

YLPatternMaking（YL 打版系统）后端经 HTTP 机器接口接入 MS 排料引擎：multipart
提交带编号母版 DXF + config JSON → 按运行模式求解 → 2s 级轮询实时利用率 → 终态
取完整布局 → 会话无关导出 PLT。**机器任务 = strategy 家族第三成员
（``mode='machine'``）**：复用 ``strategy.py`` 的每会话状态槽
``_STRATEGY_STATES`` / marker / run_dir 发现 / 树杀 / 清理骨架 —— 与
se|race / extreme 同会话单飞互斥（防双长跑拖垮 CPU），跨会话完全独立。

五端点契约概述（本模块 US-001 仅落骨架 = 空 APIRouter + 注册函数；端点自
US-002 起逐故事挂到本 router）：

  - ``POST   /api/machine/solve``                     —— multipart ``file``（母版
    DXF ≤20MB，同 /api/parse-dxf 上限）+ ``config``（JSON 字符串：``gate_mm``
    必填 int>0；``run_mode`` ∈ normal|advanced|extreme 缺省 normal；``sizes``
    int[]；``per_type`` {g码:{d,tol}}；``quantities`` {g码:{码号:int≥0}}；
    ``client_ref`` str≤128 幂等键）→ 铸 sid（'m'+时间戳+rand）→ 保存上传 →
    复用 server parse+commit 管线（带 sid 只挂本会话，不碰 default）→ 写 cfg →
    spawn → ``202 {task_id, run_name, started_at}``；
  - ``GET    /api/machine/solve/{task_id}/status``    —— 轮询任务状态 + 实时
    利用率（**物理毛版包络口径**，solver._apply_density_dual 单一权威，不可与
    历史 erode 口径混比）+ 阶段；无 placed_items（控载荷）；
  - ``POST   /api/machine/solve/{task_id}/stop``      —— 树杀
    （taskkill /PID /T /F），run_dir 保留（stopped 态 result 仍可读）；
  - ``GET    /api/machine/solve/{task_id}/result``    —— 终态取 manifest
    （pieces 键集含 raw_polygon/d_mm/demand/color，与 /ws/solve manifest 同形）
    + 最优解 placed_items（demand>1 发 N 条**绝不按 pid 去重**）；running → 409；
  - ``POST   /api/machine/export`` / ``DELETE /api/machine/solve/{task_id}``
    —— 会话无关导出（pieces 直载 run_dir pieces_intermediate.json，独立于会话
    TTL；fmt 缺省 'plt-clean' + 服务端全算表格）与幂等清理。

运行模式三档映射（时间烘焙 MS 侧单一真相源，全默认参数零暴露 —— config 不接受
time/seeds/band/prefix）：normal = plain ``--time 180``（单 seed 0）；
advanced = ``--strategy race --time 1200``（race 默认档由 CLI 缺省）；
extreme = ``--extreme --time 7200``（默认 race 臂，extreme-budget 缺省 600）。

分层合规（与 strategy.py 同款红线，AST 守卫见 tests/test_web_machine.py）：
  - **禁 import ``..cli.*``** —— spawn ``python -m materialsorting.cli.run_config``
    子进程是**进程边界**而非 import 边界，判据逻辑单一真相源留在 cli；
  - 对 ``server.py`` 的依赖走**函数内延迟 import**（server 文件尾 import 本模块
    再调用注册函数，模块级互相 import 成环；strategy.py 防环先例）；
  - 机器会话独立 sid（'m' 前缀满足 sessions.SID_RE），commit 快照不碰 default
    ``_PIECES_STATE`` —— 浏览器工作台零感知。
"""
from __future__ import annotations

from fastapi import APIRouter

__all__ = ['register_machine_routes', 'router']

# US-001 骨架：空 router。端点路径自带全路径（/api/machine/...，与 routes_views /
# routes_ws 显式风格一致，不用 APIRouter(prefix=...)）；server.py 文件尾在 strategy
# 注册之后调用 register_machine_routes(app) 挂载。
router = APIRouter()


def register_machine_routes(app) -> None:
    """把 machine 路由挂到 FastAPI app（server.py 文件尾调用一次，位于 strategy 之后）。

    US-001：空骨架（include_router 无副作用）；US-002 起端点逐故事挂到本模块
    ``router``，注册点零改动。
    """
    app.include_router(router)
