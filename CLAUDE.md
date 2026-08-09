# CLAUDE.md — MaterialSorting

## 项目定位

牛仔裤排料（marker making）引擎与可视化工作台。从 `D:\Pattern_Making` 迁移而来，与打板模块完全解耦。核心目标：把 M1787 直筒款 8 码套排利用率做到 90%+（版师认可的行业生死线）。

## 分层架构（依赖方向单向，禁反向）

```
web  →  nesting_engine  →  nesting_bounds  →  dxf_parser
                            (sparrow_experiments → sparrow_baseline)
```

- `dxf_parser`：底层 DXF 读写。`reader.py`（ezdxf recover + GBK 块名 + R12 POLYLINE）、`geometry.py`（纯几何算子，无 ezdxf）、`model.py`（PieceOutline dataclass）。仅标准库 + ezdxf，不依赖任何兄弟包。
- `nesting_bounds`：`load_pieces.py` 把单裁片 DXF → 布纹对齐水平 → 归一化到原点 → 成对镜像展开为 L/R。定义 `NestPiece`、`GATE_MM=1980`、`DEFAULT_SIZES`（8 码跳 32）。
- `nesting_engine`：sparrow 求解。`constraints.py`（v0.3 约束常量 MAX_OVERLAP/ROTATION_TOL + 位图腐蚀 + 合法性校验）、`sparrow_baseline.py`（基线 + **共享层**：PTYPE_COLORS/_clean_polygon/solve_with_progress，被 solver/export/sparrow_experiments 复用）、`sparrow_experiments.py`（旋转/重合公差实验）、`pieces_export.py`（生成 intermediate）。
- `web`：`server.py`（FastAPI + WS）、`solver.py`（build_instance + 子线程求解回调）、`export.py`（PNG + R12-DXF marker）。

## 路径约定

所有数据/产物/前端目录集中在 `materialsorting/paths.py`，优先环境变量，默认相对包位置上溯到 repo 根。**不要在代码里硬编码 `..` 上溯或绝对路径**，一律 `from .. import paths` 后用 `paths.XXX`。

## 启动顺序约束

`ms-web` 的 `server.py` 在**模块顶层**调用 `load_pieces()` 读 `out/sparrow_baseline/pieces_intermediate.json`，并 `app.mount('/static', ...)` 指向 `materialSorting-web/static`（前端构建产物）。因此：
1. 首次启动 `ms-web` 前**必须**先 `ms-pieces-export` 生成 intermediate；
2. **prod 模式**：`materialSorting-web/static/` 必须先 `cd materialSorting-web && npm run build` 生成（产物已 gitignore，不入库；旧版 vanilla 三件套已删除）。
3. **dev 模式**：`npm run dev` 启 Vite dev server (:5173)，经 Vite proxy 转发 `/export` 与 `/ws` 到后端 :8000；**不需要 build 产物**（但仍建议先跑一次 `npm run build` 让 `static/` 存在，避免 FastAPI mount 空目录报错）。

## 关键技术决策

- **DXF 导出走 R12 + POLYLINE**（非 LWPOLYLINE）：ET2008 读 LWPOLYLINE 轮廓会消失。导出 marker、单裁片均如此。
- **sparrow 不改源码**：作为 pip 包（spyrrow）引用，v0.3 服装约束（重合/旋转/布纹线）在外层 `constraints.py` + `solver.build_instance` 包装实现。
- **坐标系**：spyrrow 世界坐标 X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上；前端 SVG `scale(1,-1)` 翻转后与 PNG 一致。
- **密度口径**：版师/90% 生死线用**原面积**口径 `real_density = total_area/(width*gate)`，erode 后 sparrow 自报密度仅作参考（density_sparrow）。
- **前端已迁移到 React 18 + TypeScript 5 + Vite 5**（US-001~US-008 落地）。源码在 `materialSorting-web/src/`（Zustand 状态管理 + 命令式 SVG 渲染逃逸 React reconciliation），`npm run build` 产出到 `static/`（gitignore，prod 模式前必须先 build）。旧 vanilla 三件套（index.html + 主脚本 + style.css，原 `legacy/` 归档）已删除，React 应用是唯一真相源。**不引入 CSS 框架**（沿用迁移自旧版的 `style.css`）；**坐标系翻转 `scale(1,-1)` 必须保留**，与 PNG / R12-DXF 导出口径一致。

## 数据流主线

母版 → `ms-export-dxf` → 110 裁片 → `load_pieces` → 128 NestPiece → `ms-pieces-export` → `pieces_intermediate.json`（事实源）→ `ms-sparrow-*` / `ms-web`。详见 [README.md](README.md)。

## 运行方式

重构为正经包后，不能直接 `python file.py`（相对导入）。用 console_scripts（`ms-*`）或 `python -m materialsorting.<sub>.<module>`。6 个入口定义在 `pyproject.toml`。

## 已知问题（待清理，勿在迁移中扩大改动）

- `sparrow_baseline.py` 顶部 `PTYPE_COLORS` 含遗留片型（门头/门里/拉链/表袋/双袋/侧袋），与 v0.3 实际片型（机头/单排/双排/火机袋/裤耳）不一致。当前屏幕灰色即此残留，迁移未修。
- `sparrow_baseline.py` 职责混合（既是 CLI 入口又是共享层），未拆分 `engine_core.py`。

## 规则与方案文档

排料 v0.3 规则、各阶段（0/1/1c/2）规划、DXF 解析架构、工作台实现/导出方案均在 [.docs/](.docs/)。权威约束 spec 是 `.docs/排料规则_详细版.md`。
