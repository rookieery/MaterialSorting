# .docs/ 索引

> 由 `/sync-docs` skill 维护。本目录分 `technical/`（代码地图·todo）与 `business/`（规则·方案·反馈）两类；`README.md` 是索引根，留在 `.docs/` 根目录。

## technical/（技术文档）
> 代码地图、待办追踪 —— "改 X 找哪里"的速查与工程清单。
- [technical/agent-file-map.md](technical/agent-file-map.md) — 后端 Python 包逐文件索引（dxf_parser / nesting_bounds / nesting_engine / web / cli）
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
- [business/排料利用率_扩展配置项_方案.md](business/排料利用率_扩展配置项_方案.md) — spyrrow 原生旋钮 + 建模层利用率杠杆盘点（2026-08-13，盘点阶段未立项）
- [business/多seed并发与部署架构_分析.md](business/多seed并发与部署架构_分析.md) — 多 seed 并发承载能力 + 三种部署形态并发安全评估（2026-08-14，前瞻分析未实现）
- [business/腰头成带_落地方案.md](business/腰头成带_落地方案.md) — 腰头 g 码聚排成带机制方案（ralph/waist-band 分支，US-009~015；顶部有 2026-08-22 状态注记：v2 链构造重写 + 简化后现行口径）
- [business/腰头成带_AB验收报告_US014.md](business/腰头成带_AB验收报告_US014.md) — US-014 A/B 终验 accept：密度/形态/确定性/导出四判据全过 + 目测截图（2026-08-21；历史留档——v1 口径，验收 CLI 2026-08-22 已删）
- [business/腰头成带_AB验收报告_US015.md](business/腰头成带_AB验收报告_US015.md) — US-015 v1.1 填料混带 A/B accept：带 fill 86.52% ≥ 62.4%、全局均值提升 0.534pt、守恒/泄漏全过 + 浏览器 17/17（2026-08-21；**历史留档——填料混带 2026-08-22 已整体删除**，现行 = 纯腰 v2 链构造）

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
