---
name: code-stats
description: 统计项目代码行数，区分前端和后端（含单测拆分），排除依赖、构建产物与实验产物。
allowed-tools: Bash
---

# Code Statistics Skill

## 上下文（2026-09-12 核对的实际结构）

- 项目根目录：`d:/code/MaterialSorting`
- 后端项目：`materialSorting-server/`（FastAPI + Python 排料引擎）
  - 源码包：`src/materialsorting/`（子包 cli / web / nesting_engine / nesting_bounds / dxf_parser / resources）
  - 测试：`tests/`（pytest，规模与源码约 1:1，**单列展示**）
  - `out/` 是跑批/实验产物目录（内含 .py 实验脚本），**排除**
- 前端项目：`materialSorting-web/`（**React 18 + TypeScript 5 + Vite 5**，非旧版原生三件套）
  - 源码：`src/`（.ts / .tsx / .css）+ 根 `index.html`（Vite 入口，十几行）
  - 单测：`src/**/__tests__/`（vitest，占 src 一半以上，**单列展示**）
  - `static/` 是 `npm run build` 产物（gitignore）——**绝不统计**（旧版统计 static 属历史错误）
  - `scripts/*.mjs`（Playwright 冒烟）不计

## 执行步骤

1. **统计后端**（src 源码与 tests 分开）：

   ```bash
   cd "d:/code/MaterialSorting/materialSorting-server" && for scope in src tests; do find "$scope" -type f -name "*.py" ! -path "*__pycache__*" ! -path "*/.venv/*" ! -path "*.egg-info*" 2>/dev/null | while read f; do wc -l < "$f"; done | awk -v s="$scope" '{total+=$1; n++} END {if(n>0) printf "  %-6s %3d 文件 %7d 行\n", s, n, total; else printf "  %-6s (空)\n", s}'; done
   ```

2. **统计前端**（src 按扩展名 + 单测拆分）：

   ```bash
   cd "d:/code/MaterialSorting/materialSorting-web" && find src -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.css" \) | while read f; do e="${f##*.}"; echo "$e $(wc -l < "$f")"; done | awk '{arr[$1]+=$2; total+=$2} END {for(k in arr) printf "  .%-4s %6d 行\n", k, arr[k]; printf "  TOTAL(src) %6d 行\n", total}' && find src -type f \( -name "*.ts" -o -name "*.tsx" \) -path "*__tests__*" | while read f; do wc -l < "$f"; done | awk '{t+=$1; n++} END {printf "  其中 __tests__ 单测: %d 文件 %d 行\n", n, t}'
   ```

3. **汇总输出**（数字以上述命令实际输出为准，格式如下）：

   ```
   📊 项目代码统计

   ━━━ 后端 (materialSorting-server / Python) ━━━
     src/materialsorting   xx 文件  xxxxx 行
     tests（pytest）       xx 文件  xxxxx 行

   ━━━ 前端 (materialSorting-web / React+TS) ━━━
     .tsx                  xxxxx 行
     .ts                   xxxxx 行
     .css                   xxxx 行
     index.html（Vite 入口）  xx 行
     其中 __tests__ 单测    xx 文件 xxxxx 行
     业务源码               xxxxx 行

   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   纯源码合计（不含两端测试）: xxxx 行
   含测试总计:               xxxx 行
   ```

## 注意事项

- **Git Bash cwd 跨调用持久化**（本机实测陷阱）：`cd` 与统计必须在**同一条命令**内完成；分开跑会 find 到错误目录，且 `2>/dev/null` 会吞掉 "No such file or directory"，表现为 0 文件 0 行的假结果。两条统计命令各自带 `cd` 即可。
- 后端排除：`__pycache__`、`.venv`、`*.pyc`、`*.egg-info`、`.mypy_cache`、`out/`（跑批/实验产物）
- 前端排除：`node_modules`、`static/`（构建产物）、`*.min.*`、`*.log`、`scripts/`（冒烟脚本）
- 只统计源码文件，不统计配置文件（pyproject.toml / package.json 等）
- 如果用户只关心某一端，可以只运行对应步骤
