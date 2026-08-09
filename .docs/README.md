# .docs/ 索引

> 由 `/sync-docs` skill 维护。本目录分 `technical/`（代码地图·todo）与 `business/`（规则·方案·反馈）两类；`README.md` 是索引根，留在 `.docs/` 根目录。

## technical/（技术文档）
> 代码地图、待办追踪 —— "改 X 找哪里"的速查与工程清单。
- [technical/agent-file-map.md](technical/agent-file-map.md) — 后端 Python 包逐文件索引（dxf_parser / nesting_bounds / nesting_engine / web）
- [technical/agent-component-map.md](technical/agent-component-map.md) — 前端（materialSorting-web/）组件/模块地图
- [technical/agent-api-reference.md](technical/agent-api-reference.md) — HTTP 路由 + WS `/ws/solve` 协议 + 导出契约
- [technical/todo.md](technical/todo.md) — `/todo` skill 维护

## business/（业务文档）
> 排料规则、各阶段方案、版师反馈 —— 工艺与算法的权威原文。

### 概览
- [business/business-overview.md](business/business-overview.md) — 产品概述 / 当前状态 / 核心实体 / 数据流 / 90% 目标（业务一页速览）

### 规则与方案（权威原文）
- [business/排料规则_详细版.md](business/排料规则_详细版.md) — v0.3 工艺约束（**权威 spec**）
- [business/排料规则.md](business/排料规则.md) — 规则速览
- [business/排料可视化工作台_实现计划.md](business/排料可视化工作台_实现计划.md) — WS / 渲染 / 节流 / 回放设计
- [business/排料工作台_导出功能_方案.md](business/排料工作台_导出功能_方案.md) — PNG / R12-DXF 导出
- [business/排料DXF解析架构_方案.md](business/排料DXF解析架构_方案.md) — dxf_parser 三模块拆分
- [business/排料引擎技术分析.md](business/排料引擎技术分析.md) — sparrow + 自研约束层

### 阶段规划
- [business/阶段0_利用率上界估算_规划.md](business/阶段0_利用率上界估算_规划.md)
- [business/阶段1_NFP排料引擎_规划.md](business/阶段1_NFP排料引擎_规划.md)
- [business/阶段1c_在线排料引擎_规划.md](business/阶段1c_在线排料引擎_规划.md)
- [business/阶段2_90利用率突破_方案.md](business/阶段2_90利用率突破_方案.md)
- [business/阶段2_方向选择与建议_总结.md](business/阶段2_方向选择与建议_总结.md)
- [business/阶段2_排料90利用率攻坚_思路与流程总结.md](business/阶段2_排料90利用率攻坚_思路与流程总结.md)

### 反馈
- [business/版师确认问题清单_阶段2.md](business/版师确认问题清单_阶段2.md)
- [business/用户需求.md](business/用户需求.md)
