---
name: prd
description: 根据功能描述生成结构化 PRD 文档，产出 Ralph Stories 格式的 User Stories。
allowed-tools: Read, Write, Glob, Grep
---

# PRD Generator Skill

## 上下文
- 项目规范：@CLAUDE.md
- 排料规则（权威约束）：@.docs/business/排料规则_详细版.md
- 架构速查：@.docs/technical/agent-file-map.md（待生成）
- 组件速查：@.docs/technical/agent-component-map.md（已生成）
- API 速查：@.docs/technical/agent-api-reference.md（待生成）
- 业务概览：@.docs/business/business-overview.md（待生成）

## 触发场景

当用户表达以下意图时激活：
- "帮我写一个 PRD"
- "规划一下 XX 功能"
- "把 XX 需求拆成 User Stories"
- "创建 PRD" / "写 PRD" / "需求文档"

## 执行流程

### 阶段 1：澄清需求（必须执行）

向用户提出 3-5 个关键问题，每个问题提供 2-4 个选项（使用字母编号 A/B/C/D），方便用户快速回复（如 "1A, 2C, 3B"）。

问题维度：
1. **核心目标**：这个功能主要解决什么问题？
2. **功能范围**：包含哪些子功能？哪些明确不做？
3. **用户角色**：面向哪类用户？
4. **成功标准**：怎样算"做好了"？
5. **技术偏好**（可选）：前后端分工、是否需要新 API/WS 等

**如果用户已提供了充分信息**（如从 Planner 输出转来），可以跳过提问阶段，直接进入生成。

### 阶段 2：查阅项目上下文（必须执行）

在生成 PRD 前，必须查阅以下项目文件以确保 Story 的可行性：
1. 读取 `.docs/business/排料规则_详细版.md` —— 了解权威约束 spec
2. 读取 `.docs/technical/agent-file-map.md` —— 了解现有文件结构（若已生成）
3. 读取 `.docs/technical/agent-api-reference.md` —— 了解现有 API/WS 端点（若已生成）
4. 根据功能范围，选择性读取 `materialSorting-server/src/materialsorting/` 下相关源码以确认现有模式

### 阶段 3：生成结构化 PRD

输出格式必须严格遵循以下结构：

```markdown
# PRD: [功能名称]

## 概述 (Overview)
[2-3 句话总结功能目标和价值]

## 目标 (Goals)
- [目标 1，可衡量]
- [目标 2，可衡量]

## 用户故事 (User Stories)

### US-001: [Story 标题]
- **Description**: As a [角色], I want [功能] so that [收益]
- **Acceptance Criteria**:
  1. [可验证的具体条件]
  2. [可验证的具体条件]
  3. Python 模块可通过 `python -m materialsorting.<sub>.<module>` 跑通、分层依赖未反向
- **Priority**: 1

### US-002: [Story 标题]
...

## 功能需求 (Functional Requirements)
- FR-1: [需求描述]
- FR-2: [需求描述]

## 非目标 (Non-Goals)
- [明确不在本次范围内的功能]
- [延后处理的事项]

## 设计考虑 (Design Considerations)
- [可视化/交互相关的约束或建议]

## 技术考虑 (Technical Considerations)
- [架构、性能、坐标/约束相关的建议]

## 成功指标 (Success Metrics)
- [ ] [可量化的指标 1]
- [ ] [可量化的指标 2]

## 待确认问题 (Open Questions)
- [需要进一步讨论的决策点]
```

### 阶段 4：保存 PRD

将生成的 PRD 保存到 `tasks/prd-[feature-name].md`（文件名使用 kebab-case）。

## Story 粒度规则（核心）

1. **一个 Story = 一个 Ralph 迭代**：每个 Story 必须在单次 AI 会话（一个 context window）中可完成。
2. **合理的粒度参考**：
   - ✅ "实现 NFP 几何算子模块"
   - ✅ "新增排料导出（R12 DXF + PNG）"
   - ✅ "前端 SVG 渲染裁片重叠校验"
   - ❌ "搭建整个排料引擎"（太大）
   - ❌ "修改一个 CSS 类名"（太小，应合并）
3. **依赖排序**：Priority 数字越小越先执行。顺序：dxf_parser → nesting_bounds → nesting_engine → web → 前端 → 集成。
4. **验收标准可验证**：
   - ✅ "`ms-pieces-export` 生成的 intermediate 含 128 个 NestPiece"
   - ✅ "`real_density = total_area/(width*gate)` 达到 90%"
   - ❌ "排料正常工作"
   - ❌ "效果良好"
5. **构建检查**：每条 Story 最后一条验收标准必须是 Python 模块导入/入口检查通过。
6. **UI Story**：涉及 SVG 可视化变更的 Story 必须包含 "通过浏览器验证排料渲染（裁片布局/利用率）"。

## 从 Planner 输出转换（特殊场景）

当用户明确表示"把 Planner 的方案转为 PRD"或提供了 Planner 的实施计划时：
1. 跳过阶段 1（需求已明确）
2. 直接从 Planner 的实施步骤中提炼 User Stories
3. 每个实施阶段提炼为 1-2 条 Story
4. 保留 Planner 中的文件路径信息在 Story Description 中
5. 验收标准从 Planner 的成功标准和测试策略中提炼

## 输出确认

生成完成后，向用户展示：
1. Story 总数和预计迭代次数
2. 关键依赖关系图（如有跨 Story 依赖）
3. 询问用户是否需要调整 Story 粒度或顺序
4. 提示用户可以运行 `/ralph` 将 PRD 转换为 `prd.json`
