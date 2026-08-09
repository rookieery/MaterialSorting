---
name: todo
description: 管理项目 Todo 追踪系统 (.docs/todo.md)。支持添加/查看/完成/拾取待办事项。
allowed-tools: Read, Edit, Bash(bash .claude/scripts/add-todo.sh)
---

# Todo Management Skill

## 上下文
- Todo 文件：`@.docs/todo.md`
- 辅助脚本：`.claude/scripts/add-todo.sh`
- 当前日期：`2026/05/24`

## 指令解析

根据用户输入的参数（args），判断执行以下哪种操作：

### 1. 添加记录 — `add`

**触发条件**：用户提到"添加/新增/记录 + issue/task/建议"等意图，或参数包含 `add`。

**执行步骤**：
1. 识别类型（`issue` | `task` | `suggest`）和描述内容。
2. 运行脚本写入：
   ```bash
   bash .claude/scripts/add-todo.sh <type> "描述内容" "上下文标签"
   ```
3. 确认写入成功后，向用户报告结果。

**参数映射**：
- 第 1 个参数 = 类型：`issue`（问题/Bug）、`task`（待办任务）、`suggest`（改进建议）
- 第 2 个参数 = 描述：问题的具体内容，用双引号包裹
- 第 3 个参数 = 上下文标签（可选）：如 `backend`、`frontend`、`testing`、`infra` 等

### 2. 标记完成 — `done`

**触发条件**：用户提到"完成/关闭/解决 + 某个事项"，或参数包含 `done`。

**执行步骤**：
1. 读取 `.docs/todo.md`，找到用户指定的条目。
2. 如果是 **ISSUE**（格式 `### [ISSUE-XXX]`）：
   - 将 `Status: **Open**` 改为 `Status: **Closed**`
   - 在 Completed 区域追加一条记录：
     ```bash
     bash .claude/scripts/add-todo.sh done "ISSUE-XXX: 描述内容" "原上下文"
     ```
3. 如果是 **Task**（格式 `- [ ]`）：
   - 将 `- [ ]` 改为 `- [x]`，追加完成日期
   - 在 Completed 区域追加一条记录：
     ```bash
     bash .claude/scripts/add-todo.sh done "任务描述" "原上下文"
     ```
4. 向用户确认完成。

### 3. 查看列表 — `list`

**触发条件**：用户提到"查看/列出/有哪些 + todo/待办/问题"，或参数包含 `list`。

**执行步骤**：
1. 读取 `.docs/todo.md`。
2. 按分区汇总当前状态：
   - **Open Issues**：列出所有 `Status: **Open**` 的 ISSUE。
   - **Pending Tasks**：列出所有 `- [ ]` 未勾选的任务。
   - **Suggestions**：列出所有建议。
   - **Recently Completed**：列出最近 5 条已完成项。
3. 如果所有分区均为空，告知用户"当前无待办事项"。

### 4. 拾取任务 — `pick`

**触发条件**：用户提到"做/实现/讨论/拾取 + 某个待办/issue/task"，或参数包含 `pick`。

**执行步骤**：
1. 读取 `.docs/todo.md`，筛选出所有未完成的条目（Open Issues + Pending Tasks）。
2. 如果用户指定了具体条目（如 ISSUE-001 或任务关键词），定位该条目。
3. 如果未指定，按优先级展示列表让用户选择（Issues 优先于 Tasks）。
4. 选定后：
   - 向用户展示该条目的完整信息（描述、上下文、创建时间）。
   - 分析该任务涉及的项目文件和技术方案。
   - 主动提出实现建议或讨论方向。
5. **不要**修改 `.docs/todo.md` 的状态——仅在完成实现后再调用 `done` 操作。

### 5. 检查状态 — `check`

**触发条件**：用户提到"检查/确认 + 某个事项是否完成"，或参数包含 `check`。

**执行步骤**：
1. 读取 `.docs/todo.md`。
2. 根据用户提供的标识（ISSUE 编号或关键词）搜索匹配条目。
3. 报告该条目的当前状态：
   - 如果是 ISSUE：显示 `Status: **Open/Closed**`。
   - 如果是 Task：显示 `- [ ]`（未完成）或 `- [x]`（已完成）。
4. 如果找不到匹配项，列出所有未完成条目供用户确认。

## 无参数时的默认行为

如果用户只输入 `/todo` 不带任何参数：
1. 执行 `list` 操作，展示当前所有待办事项的概览。
2. 提示用户可以使用的子命令：`add`、`done`、`list`、`pick`、`check`。

## 注意事项
- 所有对 `.docs/todo.md` 的修改必须保留文件的结构（分区标题、占位文本）。
- 使用脚本写入时，确保从项目根目录执行。
- 日期格式统一使用 `YYYY-MM-DD HH:MM`。
- 上下文标签应反映实际的技术领域，避免使用过于宽泛的标签。
