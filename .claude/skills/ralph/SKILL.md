---
name: ralph
description: 将 PRD 文档转换为 prd.json，供 Ralph 自动循环消费执行。
allowed-tools: Read, Write, Glob, Grep
---

# Ralph PRD-to-JSON Converter Skill

## 上下文
- 项目 PRD 数据文件：@prd.json
- PRD 归档文件：@prd_archive.json
- 归档脚本：@archive.js
- Ralph 循环脚本：@ralph.sh
- 项目规范：@CLAUDE.md

## 触发场景

当用户表达以下意图时激活：
- "把这个 PRD 转成 prd.json"
- "转换为 Ralph 格式"
- "生成 prd.json"
- "启动 Ralph"（前提是有 PRD 文件存在）
- "/ralph"

## 输入来源（按优先级）

1. **用户直接提供了 Planner 的实施计划文本**：从 "Ralph Stories" 段提取 Stories
2. **用户指定了 PRD 文件路径**（如 `tasks/prd-xxx.md`）：读取该文件
3. **项目中已有 PRD 文件**：自动扫描 `tasks/` 目录下的 `prd-*.md` 文件
4. **用户粘贴了 PRD 文本**：直接解析

## 目标格式（当前项目 prd.json 格式）

输出必须严格遵循以下 JSON 结构，与 `ralph.sh`、`prompt.md`、`archive.js` 完全兼容：

```json
{
  "branchName": "feature/[kebab-case-name]",
  "stories": [
    {
      "id": "US-001",
      "title": "[简洁标题，中文]",
      "description": "[详细描述，包含：\n1. 要做什么\n2. 涉及哪些文件\n3. 具体实现要求\n4. 验收标准]",
      "passes": false
    }
  ]
}
```

### 格式约束（红线）

| 字段 | 规则 |
|------|------|
| `branchName` | 必须以 `feature/` 前缀开头，使用 kebab-case |
| `stories` | 数组名必须是 `stories`（不是 `userStories`） |
| `id` | 格式 `US-XXX`，三位数字，按执行顺序递增 |
| `title` | 简洁中文标题，不超过 30 字 |
| `description` | 详细的中文描述，包含文件路径和验收标准 |
| `passes` | 所有新 Story 一律为 `false` |
| **禁止字段** | 不允许出现 `acceptanceCriteria`、`priority`、`notes`、`project`、`description`（顶层） |

## 转换规则

### 1. Story 粒度检查

在转换前，先检查每条 Story 的粒度：

| 粒度 | 判断依据 | 处理方式 |
|------|---------|---------|
| 合适 | 单文件或 2-3 个强相关文件的变更 | 直接转换 |
| 太大 | 涉及 ≥ 4 个文件或 ≥ 2 个层级（如 DB+Service+UI） | 拆分为多条 Story |
| 太小 | 仅修改 1-2 行代码 | 合并到相邻 Story |

### 2. 依赖排序

Story 数组中的顺序即为执行顺序，必须遵循：

```
1. 数据模型 / Schema 定义
2. 数据库迁移
3. Repository / DAO 层
4. Service 业务逻辑层
5. Controller / API 路由层
6. 前端组件 / 页面
7. 集成测试 / 端到端验证
```

### 3. Description 编写规范

将 PRD 中的 User Story 和 Acceptance Criteria 合并到 `description` 字段：

```
[User Story 概述]

具体任务：
1. [文件路径] — [具体操作]
2. [文件路径] — [具体操作]

验收标准：
- [可验证条件 1]
- [可验证条件 2]
- TypeScript 项目构建通过 / Python 类型检查通过
```

### 4. 归档保护（必须执行）

写入新 `prd.json` 前，必须检查是否存在已有的 `prd.json`：

1. **如果存在且 `branchName` 不同**：
   - 读取当前 `prd.json`
   - 将其整体追加到 `prd_archive.json`（保留原结构）
   - 通知用户：`已将旧分支 [旧分支名] 的数据归档`
2. **如果存在且 `branchName` 相同**：
   - 合并新旧 Stories（去重，保留已有 passes 状态）
   - 新 Story 追加到末尾
3. **如果不存在**：直接创建新文件

### 5. Branch 命名

从功能名称推导 branch 名称：
- 移除特殊字符，转为 kebab-case
- 添加 `feature/` 前缀
- 示例：`比赛预测功能` → `feature/match-prediction`

## 执行流程

### Step 1：定位输入

扫描用户提供的来源，提取所有 User Stories 信息。如果输入是 Planner 输出，优先从 "Ralph Stories" 段提取。

### Step 2：校验粒度

逐条检查 Story 粒度，对不符合要求的提出拆分/合并建议。

### Step 3：格式转换

将 PRD 内容转换为目标 JSON 格式，严格按照上面的格式约束。

### Step 4：归档保护

执行归档保护逻辑（见上方规则），确保不丢失已有数据。

### Step 5：写入文件

将生成的 JSON 写入项目根目录的 `prd.json`。

### Step 6：输出确认

向用户展示：
1. 分支名称和 Story 总数
2. Story 列表概览（ID + 标题）
3. 依赖关系提示（如有跨 Story 依赖）
4. 提示下一步操作：
   - 如需调整：修改 `prd.json` 后重新运行
   - 如确认无误：运行 `bash ralph.sh` 启动自动循环

## 边界情况处理

| 情况 | 处理方式 |
|------|---------|
| PRD 中没有明确的 User Stories | 从 Functional Requirements 中提炼，每个 FR 转为一条 Story |
| Story 之间有循环依赖 | 报错并要求用户调整 PRD |
| Story 涉及前端 + 后端 | 拆分为后端 Story 和前端 Story，后端在前 |
| PRD 文件内容模糊 | 向用户提出 2-3 个澄清问题后再转换 |
| 用户只提供了功能描述（无 PRD 文件） | 建议先运行 `/prd` 生成结构化 PRD |
