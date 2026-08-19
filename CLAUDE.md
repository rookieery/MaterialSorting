# CLAUDE.md — MaterialSorting

## 项目定位

牛仔裤排料（marker making）引擎与可视化工作台。从 `D:\Pattern_Making` 迁移而来，与打板模块完全解耦。核心目标：把 M1787 直筒款 8 码套排利用率做到 90%+（版师认可的行业生死线）。

## 分层架构（依赖方向单向，禁反向）

```
cli  →  web  →  nesting_engine  →  nesting_bounds  →  dxf_parser
              (sparrow_experiments → sparrow_baseline)
```

- `cli`：最上层编排者（`ms-run-config` 配置驱动求解，见下「运行方式」）。只 import 底层原语与 `web.solver` 求解封装，**绝不 import `web.server`**（FastAPI 服务进程副作用）。产物只落 `out/config_runs/`（cli 子包唯一可写目录），物理隔离 web 事实源。`config.py`（7 键 JSON 配置严格校验，模块级仅标准库）、`pipeline.py`（commit 管线镜像 `server._commit_to_nesting_sync` + `solve_pieces` 单 seed 求解封装）、`run_config.py`（入口：逐 seeds 串行多轮 + best 汇总）。
- `dxf_parser`：底层 DXF 读写。`reader.py`（ezdxf recover + GBK 块名 + R12 POLYLINE）、`geometry.py`（纯几何算子，无 ezdxf）、`model.py`（PieceOutline dataclass）。仅标准库 + ezdxf，不依赖任何兄弟包。
- `nesting_bounds`：`load_pieces.py` 把切片目录（`pieces_manifest.json` 驱动）逐文件 → 布纹对齐水平 → 归一化到原点（US-001 v2：**无镜像展开**，每文件恰一条 `NestPiece`，`pid=f'{label}_{size}'`）。定义 `GATE_MM=1980`（布幅显示口径：UI/密度/导出外框）、`PLOT_SAFE_MAX_Y_MM=1910`（绘图仪可写幅宽）、`NEST_GATE_MM=min(两者)`（求解约束带，web/solver 与 CLI 引擎同口径）、`DEFAULT_SIZES`（8 码跳 32）。
- `nesting_engine`：sparrow 求解。`constraints.py`（重合/旋转**全局**上限 `MAX_OVERLAP_MM=10` / `MAX_ROTATION_TOL_DEG=45`（2026-08-17 起不再按片型钳制，版师按片型的工艺参考值在 `.docs/business/排料规则_详细版.md`）+ 位图腐蚀 + 合法性校验（US-002 起成对齐套校验与 `PAIR_TYPES` 已删））、`sparrow_baseline.py`（基线 + **共享层**：`LABEL_PALETTE`/`label_color`（US-002 起 g 码 → 16 色循环表**单一真相源**，solver manifest / PNG / CLI SVG 三处同源取色）/_clean_polygon/solve_with_progress，被 solver/export/sparrow_experiments 复用）、`sparrow_experiments.py`（旋转/重合公差实验；US-002 起内片集合改 `--internal g04,g07` 命令行参数）、`labeling.py`（**g01+ 编号单一真相源**：`assign_codes` 统一赋码（顺序模式 = `sequential_sort_key`（group_key 前置保跨码同号 + 几何稳定序）；母版 block 名自带 `g/G/#`+数字编号且每码内唯一时全量复用），被 parse 赋号/label 代表裁片两处共用；导出 PNG/DXF 逐片叠印 g 码，PLT 永不加文字）。
- `web`：`server.py`（FastAPI + WS）、`solver.py`（build_instance + 子线程求解回调）、`export.py`（PNG + R12-DXF marker）。

## 路径约定

所有数据/产物/前端目录集中在 `materialsorting/paths.py`，优先环境变量，默认相对包位置上溯到 repo 根。**不要在代码里硬编码 `..` 上溯或绝对路径**，一律 `from .. import paths` 后用 `paths.XXX`。

## 启动顺序约束

`ms-web` 的 `server.py` 在**模块顶层**调用 `load_pieces()` 读 `out/sparrow_baseline/pieces_intermediate.json`，并 `app.mount('/static', ...)` 指向 `materialSorting-web/static`（前端构建产物）。因此：
1. intermediate 由 **Web 上传母版 → `/api/commit-to-nesting`** 生成；首次启动 `_PIECES_STATE` 为空属正常（不崩），前端上传母版 commit 后自动 reload；
2. **prod 模式**：`materialSorting-web/static/` 必须先 `cd materialSorting-web && npm run build` 生成（产物已 gitignore，不入库；旧版 vanilla 三件套已删除）。
3. **dev 模式**：`npm run dev` 启 Vite dev server (:5173)，经 Vite proxy 转发 `/export` 与 `/ws` 到后端 :8000；**不需要 build 产物**（但仍建议先跑一次 `npm run build` 让 `static/` 存在，避免 FastAPI mount 空目录报错）。

## 关键技术决策

- **DXF 导出走 R12 + POLYLINE**（非 LWPOLYLINE）：ET2008 读 LWPOLYLINE 轮廓会消失。导出 marker、单裁片均如此。
- **sparrow 不改源码**：作为 pip 包（spyrrow）引用，v0.3 服装约束（重合/旋转/布纹线）在外层 `constraints.py` + `solver.build_instance` 包装实现。
- **坐标系**：spyrrow 世界坐标 X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上；前端 SVG `scale(1,-1)` 翻转后与 PNG 一致。
- **密度口径**：版师/90% 生死线用**原面积**口径 `real_density = total_area/(width*gate)`，erode 后 sparrow 自报密度仅作参考（density_sparrow）。
- **前端已迁移到 React 18 + TypeScript 5 + Vite 5**（US-001~US-008 落地）。源码在 `materialSorting-web/src/`（Zustand 状态管理 + 命令式 SVG 渲染逃逸 React reconciliation），`npm run build` 产出到 `static/`（gitignore，prod 模式前必须先 build）。旧 vanilla 三件套（index.html + 主脚本 + style.css，原 `legacy/` 归档）已删除，React 应用是唯一真相源。**不引入 CSS 框架**（沿用迁移自旧版的 `style.css`）；**坐标系翻转 `scale(1,-1)` 必须保留**，与 PNG / R12-DXF 导出口径一致。

## 数据流主线

上传母版 → `/api/parse-dxf`（解析预览，每片 g 码 label + 5 层字段；「裁片 × 尺码」数量矩阵编辑 quantities，随求解 WS start 按码下发）→ `/api/commit-to-nesting`（US-001 v2：`assign_codes` 最先赋 g 码 → 切单裁片 `{label}_{size}.dxf` + `pieces_manifest.json` 到 `out/uploads/<doc_id>_pieces/` → `load_nest_pieces` manifest 驱动归一化（无镜像）→ 写 `pieces_intermediate.json` 事实源，条数 = 母版轮廓数）→ `ms-sparrow-*` / `ms-web`。详见 [README.md](README.md)。

## 运行方式

重构为正经包后，不能直接 `python file.py`（相对导入）。用 console_scripts（`ms-*`）或 `python -m materialsorting.<sub>.<module>`。5 个入口定义在 `pyproject.toml`：`ms-explore` / `ms-sparrow-baseline` / `ms-sparrow-exp` / `ms-web` / `ms-run-config`。

**配置驱动求解（无需浏览器）**：`ms-run-config <config.json> [--name RUN_NAME] [--time N] [--quiet] [--target P] [--params FILE] [--kill shadow|off|on]` 一条命令跑完「commit → 求解」。配置是 7 键 JSON schema（`master_dxf` / `gate_mm` 必填；`sizes` / `time` / `seeds` / `per_type` / `quantities` 可选，字段语义与 WS StartPayload 1:1；示例 `data/configs/`，加载校验见 `cli/config.py`）。`seeds` 是**串行**种子列表（缺省 `[0]`；≥2 个时逐 seed 串行求解）；取代旧 `seed`/`multi_seed`/`seed_count` 三键。产物只落 `out/config_runs/<run_name>_<时间戳>/`（pieces/ + pieces_intermediate.json + result.json **逐轮重写** + curve_s\{seed\}.json / best_frame_s\{seed\}.json 逐帧轨迹 + kill_decisions.jsonl），**不触碰 web 数据**（不写 `out/sparrow_baseline/` 与 `out/uploads/`，可与 ms-web 并行运行互不干扰）。PC-001 起 `solve_pieces` 走 `solve_with_callback_proc` 多进程求解（主进程先 build_instance 取 meta），支持逐帧 `should_stop` 中止（terminate 杀子进程、best-so-far 帧交付，记录加 `killed`/`kill_reason`）；Ctrl-C 退出码 130 不丢已完成轮。PC-002 起多 seed 串行循环经 `cli/portfolio.py` 控制器转发（incumbent banking 帧级全局最优 + R0 达标即停 `--target`，`best`/`portfolio` 段语义见 README「配置驱动求解」）。PC-003 kill 引擎 `--kill`（默认 shadow 只记 `kill_decisions.jsonl` 不真杀；on 需 `--params` 标定就绪 `calibrated: true` 否则降级 shadow；引擎仅 `--target` 给定时激活，seed 1 永不 kill，R0 恒用真 target）。PC-004 标定管线 `python -m materialsorting.cli.calibration`（batch 跑批 base 28 seed 曲线 / variants 确定性订单邻域变体 ±1 抖动 4 个 / analyze 聚合出 `controller_params.json`（包络 S(τ) + kill 参数推荐，小样本拒绝下发）+ 泛化报告；产物只落 `out/portfolio_calibration/<tag>/`，真实跑批 ≈2h 属运营步骤）。PC-005 simulate ETT 离线仿真器：同总预算（k×B 恒等）回放策略网格（单 seed 基线/best-of-k/kill 三档/θ 衰减两档）→ `analysis/simulation_report.json` + 推荐参数档。PC-006 起 `build_instance`/`solve_pieces` 可选 `solver_opts` （spyrrow 旋钮白名单 exploration_pct/quadtree_depth/num_workers；清洗单一真相源 `web.solver._normalize_solver_opts`）经 `--solver-opts`（全 seed 固定档）/ `--rotate-opts`（内置 4 档池逐 seed 轮换去相关，含默认空档；两旗标互斥，坏 JSON 退出 1）透传，WS 协议与 web 前端零改动（base 与变体 held-out 双达标：ETT 均不劣于单 seed、误杀率均 <5%，`params` 键与 `--params` 同构）；截断轨迹终值用「kill 时刻 best + 条件期望增量」插值（下界 ≥ best-so-far，无 oracle）；`--shadow-log` 统计真实 would-kill 假阳性。PC-007 起 `cli/lns.py` LNS 波段重排核心（`ms-lns --run-dir <dir> --time --rounds [--band-width]`：对 run_dir 最优布局做波段级 ruin-and-recreate，段内同口径子实例多进程重解、新段更窄才接受、validate+y 双复检失败回退、无改进输出逐字节不变；产物 result_lns.json + lns_compare.svg 落 run_dir）。详见 README「配置驱动求解」。

## 已知问题（待清理，勿在迁移中扩大改动）

- `sparrow_baseline.py` 职责混合（既是 CLI 入口又是共享层），未拆分 `engine_core.py`。

## 规则与方案文档

排料 v0.3 规则、各阶段（0/1/1c/2）规划、DXF 解析架构、工作台实现/导出方案均在 [.docs/](.docs/)（技术速查/代码地图在 `technical/`、业务规则/方案/反馈在 `business/`）。权威约束 spec 是 `.docs/business/排料规则_详细版.md`。
