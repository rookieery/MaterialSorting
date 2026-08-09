# MaterialSorting

牛仔裤排料（marker making）引擎与可视化工作台。从 `D:\Pattern_Making` 的排料模块迁移而来，重构为正经 Python 包（src/ layout），与打板模块解耦独立。

## 目录结构

```
MaterialSorting/
├── .docs/                     排料规划/规则/方案文档（14 篇）
├── data/                      原始数据
│   ├── M1787#直筒...(1)(2).dxf  母版 DXF（dxf_parser 输入）
│   └── m1787_直筒/             110 个单裁片 DXF（排料输入，{类型}_{码号}.dxf）
├── materialSorting-server/    后端：排料引擎 + FastAPI 服务
│   ├── pyproject.toml
│   ├── out/                   运行产物（运行时生成，已 gitignore）
│   └── src/materialsorting/   Python 包
│       ├── paths.py           集中路径常量
│       ├── dxf_parser/        DXF 解析
│       ├── nesting_bounds/    裁片加载
│       ├── nesting_engine/    sparrow 排料 + v0.3 约束
│       └── web/               FastAPI + WebSocket 工作台
└── materialSorting-web/       前端静态资源
    └── static/                index.html / app.js / style.css
```

## 环境要求

- Python ≥ 3.10（开发机为 3.11）
- 第三方库：`spyrrow` / `shapely` / `ezdxf` 需在 Python 环境中已安装（与源项目同环境假设）。其中 `spyrrow` 非 PyPI 主流包，若 `pip install` 装不上需手动处理。

## 安装

```bash
cd D:\code\MaterialSorting\materialSorting-server
pip install -e ".[web]"
```

安装后注册 6 个命令行入口：`ms-explore` / `ms-export-dxf` / `ms-pieces-export` / `ms-sparrow-baseline` / `ms-sparrow-exp` / `ms-web`。

## 启动顺序（重要）

**首次启动 `ms-web` 前，必须先生成中间数据**，否则工作台 import 时找不到 `out/sparrow_baseline/pieces_intermediate.json`：

```bash
# 1. 生成 128 片中间数据（从 data/m1787_直筒/ 读取）
ms-pieces-export

# 2. 启动可视化工作台
ms-web          # → http://127.0.0.1:8000
```

## 数据流

```
data/M1787#...(1)(2).dxf 母版
   ↓ ms-export-dxf（人工 group→类型映射）
data/m1787_直筒/{类型}_{码号}.dxf（110 片）
   ↓ materialsorting.nesting_bounds.load_pieces（布纹对齐 + 归一化 + L/R 镜像展开）
128 个 NestPiece
   ↓ ms-pieces-export
out/sparrow_baseline/pieces_intermediate.json   ← 全流程事实源
   ↓ ms-sparrow-baseline / ms-sparrow-exp（sparrow 求解）
   ↓ ms-web（工作台读取 + 可视化 + 导出 PNG/R12-DXF）
```

## 命令速查

| 命令 | 作用 |
|---|---|
| `ms-export-dxf` | 母版 DXF → 110 个单裁片 DXF（数据流水线起点） |
| `ms-explore` | 母版 DXF 全裁片探索（SVG/JSON/CSV） |
| `ms-pieces-export` | 110 裁片 → `pieces_intermediate.json`（排料前必跑） |
| `ms-sparrow-baseline` | sparrow 基线求解（{0,180}，无 erode） |
| `ms-sparrow-exp` | 旋转公差 / 重合公差 / 组合实验 |
| `ms-web` | 可视化工作台（http://127.0.0.1:8000） |

也可用 `python -m materialsorting.<subpackage>.<module>` 形式运行。

## 路径覆盖

`materialsorting/paths.py` 的数据/产物/前端目录均可通过环境变量覆盖：`MS_DATA_DIR`、`MS_OUT_DIR`、`MS_STATIC_DIR`。

## 架构与约定

详见 [CLAUDE.md](CLAUDE.md)。排料规则与各阶段方案详见 [.docs/](.docs/)。
