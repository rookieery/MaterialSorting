---
name: code-stats
description: 统计项目代码行数，区分前端和后端，排除依赖文件和生成文件。
allowed-tools: Bash
---

# Code Statistics Skill

## 上下文
- 项目根目录：`d:/code/MaterialSorting`
- 后端项目：`materialSorting-server/` (FastAPI + Python，排料引擎主体)
- 前端项目：`materialSorting-web/` (原生 HTML/CSS/JS + SVG，无框架)

## 执行步骤

1. **统计后端代码行数**（Python，项目主体）：排除 `__pycache__`、`.venv`、`.egg-info` 等，按文件类型统计。

   ```bash
   cd "d:/code/MaterialSorting/materialSorting-server" && find src -type f -name "*.py" ! -path "*/__pycache__/*" ! -path "*/.venv/*" ! -path "*.egg-info/*" 2>/dev/null | while read f; do lines=$(wc -l < "$f"); printf "py %d\n" "$lines"; done | awk '{arr[$1]+=$2; total+=$2} END {if(total>0) {for(k in arr) printf "  %-8s %6d 行\n", k, arr[k]; printf "  %-8s %6d 行\n", "TOTAL", total} else print "  (后端尚未搭建)"}'
   ```

2. **统计前端代码行数**（原生 HTML/CSS/JS + SVG）：

   ```bash
   cd "d:/code/MaterialSorting/materialSorting-web" && find static -type f \( -name "*.js" -o -name "*.html" -o -name "*.css" \) 2>/dev/null | while read f; do ext="${f##*.}"; lines=$(wc -l < "$f"); printf "%s %d\n" "$ext" "$lines"; done | awk '{arr[$1]+=$2; total+=$2} END {if(total>0) {for(k in arr) printf "  %-8s %6d 行\n", k, arr[k]; printf "  %-8s %6d 行\n", "TOTAL", total} else print "  (前端尚未搭建)"}'
   ```

3. **汇总输出**：将上述结果整理为如下格式展示给用户：

   ```
   📊 项目代码统计

   ━━━ 后端 (materialSorting-server / Python) ━━━
     .py        xxxx 行
     TOTAL      xxxx 行

   ━━━ 前端 (materialSorting-web / 原生 JS+SVG) ━━━
     .js        xxxx 行
     .html      xxxx 行
     .css       xxxx 行
     TOTAL      xxxx 行

   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   项目总计: xxxx 行
   ```

## 注意事项
- 后端排除：`__pycache__`、`.venv`、`*.pyc`、`*.egg-info`、`.mypy_cache`
- 前端排除：`node_modules`、`dist`、`build`、`*.min.*`、`*.log`
- 只统计源码文件，不统计配置文件（pyproject.toml 等）
- 如果用户只关心某一端，可以只运行对应步骤
