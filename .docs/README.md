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
- [business/排料利用率_扩展配置项_方案.md](business/排料利用率_扩展配置项_方案.md) — spyrrow 原生旋钮 + 建模层利用率杠杆盘点（2026-08-13 原文；**2026-08-29 注记**：exploration_pct/quadtree_depth/num_workers 已随 PC-006 `--solver-opts` 接线、early_termination 已入 solver_opts 白名单并经 `--extreme` 固定关闭，min_items_separation 仍未暴露）
- [business/多seed并发与部署架构_分析.md](business/多seed并发与部署架构_分析.md) — 多 seed 并发承载能力 + 三种部署形态并发安全评估（2026-08-14，前瞻分析未实现）
- [business/裁片编号化重构_方案.md](business/裁片编号化重构_方案.md) — 裁片标识去名称化：g 码从「显示标识」升级为「全链路主键」（v5 终版 2026-08-18；镜像全删 + internal 一并移除，PRD tasks/prd-label-identity 系列）
- [business/腰头成带_落地方案.md](business/腰头成带_落地方案.md) — 腰头 g 码聚排成带机制方案（ralph/waist-band 分支，US-009~015；顶部有 2026-08-22 状态注记：v2 链构造重写 + 简化后现行口径）
- [business/腰头成带_AB验收报告_US014.md](business/腰头成带_AB验收报告_US014.md) — US-014 A/B 终验 accept：密度/形态/确定性/导出四判据全过 + 目测截图（2026-08-21；历史留档——v1 口径，验收 CLI 2026-08-22 已删）
- [business/腰头成带_AB验收报告_US015.md](business/腰头成带_AB验收报告_US015.md) — US-015 v1.1 填料混带 A/B accept：带 fill 86.52% ≥ 62.4%、全局均值提升 0.534pt、守恒/泄漏全过 + 浏览器 17/17（2026-08-21；**历史留档——填料混带 2026-08-22 已整体删除**，现行 = 纯腰 v2 链构造）
- [business/起始端成套前后幅_版师确认清单.md](business/起始端成套前后幅_版师确认清单.md) — 建议1 v1→v4 演进：版师 P1~P5 答复入档（「空隙跨界共同填充」⇒ 组合片自由进解+段置换钉位路线）→ P0 探针 −0.14pt ≈ 零 → US-005 终验收官全记录（PRD tasks/prd-prefix-head-set.md）
- [business/起始端成套前后幅_AB验收报告_US005.md](business/起始端成套前后幅_AB验收报告_US005.md) — US-005 A/B 终验 **accept**：五判据全 PASS（4-seed 均值 −0.675pt 反超、形态 4/4、确定性逐帧全等、导出 PS_ 零泄漏、双开 89.86%/90.35%）；验收器 `python -m materialsorting.web.prefix_accept` 一条命令复跑（2026-08-25）
- [business/极限利用率实验报告_5336_pct与早终止.md](business/极限利用率实验报告_5336_pct与早终止.md) — exploration_pct 网格 × early_termination A/B（5336，25-seed 600s 曲线池）：**p0.70 + et=false 是最优组合** → `--extreme` 参数来源；判读口径（不可行帧过滤/门判别力）单一真相源 `scripts/pctgrid_analyze.py`（2026-08-29）
- [business/极限运行功能方案_race门杀.md](business/极限运行功能方案_race门杀.md) — 极限运行方案：`--extreme` 糖衣旗标 = race 门杀 × 实验结论参数（预算档 600/1200、门 τ=0.5、p0.70/et0/workers4；quadtree_depth 调优 A/B 否决），目标从「期望最优」换「右尾最优」（PRD tasks/prd-extreme-run.md，2026-08-29）
- [business/极限运行_AB验收报告.md](business/极限运行_AB验收报告.md) — US-004 同总预算 4h 三臂对拍终验 **accept**：extreme 91.7107% ≥ race 默认档 91.3114%、split24 91.8177% 统计打平（归因 §1.1）；离线回放器 `scripts/extreme_ab_replay.py`（2026-08-30）

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
