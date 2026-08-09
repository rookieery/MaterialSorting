---
name: sync-docs
description: 扫描项目改动并自动同步更新 .docs/ 目录下的文档。
allowed-tools: Bash(git diff), Read, Write
---

# Sync Project Documentation Skill

## 上下文
- 变更分析：!`git diff --name-only`
- 关键参考：@.docs/README.md
- 排料规则（权威约束）：@.docs/排料规则_详细版.md

## 执行步骤
1. **分析改动**：运行 `git diff` 查看代码的具体变化。
2. **定位文档**（注：`agent-*.md` 速查文档尚未建立，首次同步时按需创建）：
    - 若修改了 `materialSorting-server/src/materialsorting/dxf_parser` -> 更新 `agent-file-map.md`（解析层结构）
    - 若修改了 `materialSorting-server/src/materialsorting/nesting_bounds` 或 `nesting_engine` -> 更新 `agent-file-map.md` 和 `business-overview.md`（排料核心逻辑）
    - 若修改了 `materialSorting-server/src/materialsorting/web`（server.py / solver.py / export.py）或 API/WS 路由 -> 更新 `agent-api-reference.md`
    - 若修改了 `materialSorting-web/static`（前端三件套 / SVG 可视化） -> 更新 `agent-component-map.md`
    - 若修改了 `CLAUDE.md` -> 检查 `.docs/` 下所有文档是否需要同步
    - 若修改了业务逻辑（排料规则 / 约束 / 导出） -> 更新 `business-overview.md` 和 `agent-file-map.md`
3. **静默更新**：直接修改对应的 Markdown 文件，确保"改 X 找哪里"的索引依然准确。
4. **汇报**：简洁告知用户："已根据本次改动同步更新了 N 个文档文件"。
