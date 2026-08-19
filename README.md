# MaterialSorting

牛仔裤排料（marker making）引擎与可视化工作台。从 `D:\Pattern_Making` 的排料模块迁移而来，重构为正经 Python 包（src/ layout），与打板模块解耦独立。

## 目录结构

```
MaterialSorting/
├── .docs/                     排料文档（technical/ 代码地图·todo + business/ 规则·方案·反馈，README.md 为索引）
├── data/                      原始数据
│   ├── M1787#直筒...(1)(2).dxf  母版 DXF（离线留档/回归参照；运行时由用户上传）
│   └── configs/               CLI 求解配置（7 键 JSON，ms-run-config 入参）
├── materialSorting-server/    后端：排料引擎 + FastAPI 服务
│   ├── pyproject.toml
│   ├── out/                   运行产物（运行时生成，已 gitignore）
│   └── src/materialsorting/   Python 包
│       ├── paths.py           集中路径常量
│       ├── dxf_parser/        DXF 解析
│       ├── nesting_bounds/    裁片加载
│       ├── nesting_engine/    sparrow 排料 + v0.3 约束
│       ├── web/               FastAPI + WebSocket 工作台
│       └── cli/               配置驱动求解 CLI（ms-run-config，不依赖浏览器）
└── materialSorting-web/       前端 React + TypeScript + Vite（src/ → npm run build → static/）
    ├── src/                   源码（React 18 + TS 5 + Zustand）
    └── static/                构建产物（npm run build 生成，gitignore，由 ms-web serve）
```

## 环境要求

- Python ≥ 3.10（开发机为 3.11）
- 第三方库：`spyrrow` / `shapely` / `ezdxf` 需在 Python 环境中已安装（与源项目同环境假设）。其中 `spyrrow` 非 PyPI 主流包，若 `pip install` 装不上需手动处理。

## 安装

```bash
cd D:\code\MaterialSorting\materialSorting-server
pip install -e ".[web]"
```

安装后注册 5 个命令行入口：`ms-explore` / `ms-sparrow-baseline` / `ms-sparrow-exp` / `ms-web` / `ms-run-config`。

## 启动顺序（重要）

**intermediate 由 Web 上传母版生成**：`ms-web` import 时读 `out/sparrow_baseline/pieces_intermediate.json`，缺失则 `_PIECES_STATE` 为空（不崩，`/api/ptypes` 返空、`/ws/solve` 报「排料数据为空」）；前端上传母版触发 `/api/commit-to-nesting` 后自动 reload 填入。

前端有 **dev / prod 两种模式**（二选一）：

### dev 模式（Vite dev server，热重载，调试用）
```bash
# 终端 A：后端在 :8000
ms-web

# 终端 B：前端 Vite dev server 在 :5173（Vite proxy 转发 /export 与 /ws 到 :8000）
cd materialSorting-web
npm install        # 首次装依赖
npm run dev        # → http://localhost:5173
```

### prod 模式（FastAPI 单服务 serve 构建产物，部署 / 验收用）
```bash
# 1. 构建前端到 materialSorting-web/static/（gitignore，本地生成）
cd materialSorting-web
npm install
npm run build      # tsc --noEmit && vite build → static/

# 2. 后端 serve 构建产物（静态资源挂载在 /static，根路径 / 返回 static/index.html）
cd ..
ms-web             # → http://127.0.0.1:8000
```

## 配置驱动求解（ms-run-config，无需浏览器）

评估配置（码号组合 / 公差 / 数量矩阵 / 多 seed）不必开浏览器工作台，一条命令跑完「commit → 求解」：

```bash
ms-run-config data/configs/5336_coded_sizes32-38.json            # 按 config 里的 time/seeds 求解
ms-run-config data/configs/5336_coded_sizes32-38.json --time 5   # 冒烟：单轮 5s（result.json 回显生效值）
python -m materialsorting.cli.run_config <config.json> --name demo --quiet   # 等价 python -m 形式
```

配置是 **7 键 JSON schema**（除 `seeds` 外字段名与 WS StartPayload 契约 1:1；示例见 `data/configs/`，拼写/类型/路径错误在启动前就地拦下，中文报错含字段名）：

| 键 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `master_dxf` | str | ✓ | 母版 DXF 路径；相对路径先按 CWD 再按仓库根解析 |
| `gate_mm` | num | ✓ | 门幅（mm，>0）；intermediate 与密度分母口径 |
| `sizes` | list | — | 码号过滤（JSON 整数列表，非空）；缺省 = 全部码号 |
| `time` | int | — | 单轮求解时长（秒，正整数），缺省 300 |
| `seeds` | list | — | **串行**种子列表（非负整数、不重复、非空），缺省 `[0]`；≥2 个时逐 seed 串行求解，`best` 取原面积口径 `real_density` 最大轮（消除单 seed 随机性；种子不要求连续）。取代旧 `seed`/`multi_seed`/`seed_count` 三键（旧键按未知键报错） |
| `per_type` | dict | — | `{g码: {d?, tol?}}` 逐 g 码公差覆盖（d=重合 mm、tol=旋转公差 °，≥0；超全局上限不报错但被钳制） |
| `quantities` | dict | — | `{g码: {码号: 数量}}` per-size demand（码号键须数字字符串或 `"null"`，数量 JSON 数字 ≥0 整数） |

**产物只落 `out/config_runs/<run_name>_<YYYYMMDD-HHMMSS>/`**（时间戳目录保留历史互不覆盖；`run_name` 缺省 = 配置文件 stem，`--name` 覆盖）：`pieces/`（切单裁片 + manifest）、`pieces_intermediate.json`（本 run 事实源）、`result.json`（config 回显 + commit 摘要 + 逐 seed solve 指标数组 + `best`）。

**不触碰 web 数据**：CLI 唯一可写目录是 `out/config_runs/`，绝不写 `out/sparrow_baseline/pieces_intermediate.json`（web 事实源）与 `out/uploads/` —— 与 ms-web 同时运行互不干扰（并行回归已验证：web 求解进行中跑 CLI，结束后两者事实源 mtime/内容不变、uploads 无新目录）。

## 数据流

```
用户上传母版 DXF
   ↓ POST /api/parse-dxf（collect_pieces_with_details 取 5 层 → assign_codes 赋 g 码 → 预览）
   ↓ POST /api/commit-to-nesting
       ├─ assign_codes 赋 g 码（label 先行，parse/commit 同源同序）
       ├─ write_piece_dxf 切单裁片 {g码}_{码号}.dxf → out/uploads/<doc_id>_pieces/
       ├─ load_nest_pieces（manifest 驱动布纹对齐 + 归一化，无镜像展开）
       └─ 写回 out/sparrow_baseline/pieces_intermediate.json（事实源，.bak 备份）
   ↓ ms-sparrow-baseline / ms-sparrow-exp（sparrow 求解）
   ↓ ms-web（工作台读取 + 可视化 + 导出 PNG/R12-DXF）

ms-run-config <config.json>（CLI 平行通道，不经过 web）
   └─ load_config 校验 → 独立时间戳 run_dir 内同口径 commit（切片 + intermediate 落 out/config_runs/）
       → 逐 seeds 串行求解 → result.json（best = 原面积口径最优轮）
```

## 命令速查

| 命令 | 作用 |
|---|---|
| `ms-explore` | 母版 DXF 全裁片探索（SVG/JSON/CSV） |
| `ms-sparrow-baseline` | sparrow 基线求解（{0,180}，无 erode） |
| `ms-sparrow-exp` | 旋转公差 / 重合公差 / 组合实验 |
| `ms-web` | 可视化工作台（http://127.0.0.1:8000） |
| `ms-run-config` | 配置驱动排料一条命令（commit → 串行多 seed 求解 → `out/config_runs/` result.json，见上文「配置驱动求解」） |

也可用 `python -m materialsorting.<subpackage>.<module>` 形式运行。

## 路径覆盖

`materialsorting/paths.py` 的数据/产物/前端目录均可通过环境变量覆盖：`MS_DATA_DIR`、`MS_OUT_DIR`、`MS_STATIC_DIR`（默认指向 `materialSorting-web/static/`，dev 模式下无需 override，前端由 Vite 直接 serve）。

## 架构与约定

详见 [CLAUDE.md](CLAUDE.md)。排料规则与各阶段方案详见 [.docs/](.docs/)。
