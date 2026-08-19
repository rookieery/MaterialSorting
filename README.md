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
├── scripts/                   repo 根维护脚本（embed_piece_codes.py 母版植入 g 码编号等）
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

**产物只落 `out/config_runs/<run_name>_<YYYYMMDD-HHMMSS>/`**（时间戳目录保留历史互不覆盖；`run_name` 缺省 = 配置文件 stem，`--name` 覆盖）：`pieces/`（切单裁片 + manifest）、`pieces_intermediate.json`（本 run 事实源）、`result.json`（config 回显 + commit 摘要 + 逐 seed solve 指标数组 + `best`；**逐轮重写**，Ctrl-C 不丢已完成轮）、`curve_s{seed}.json`（逐帧轨迹 `{elapsed, phase, density, density_sparrow, width_mm}`，不含布局控体积）、`best_frame_s{seed}.json`（该 seed 最优帧完整 `placed_items`）。

**求解进程化（PC-001）**：每 seed 经 `solve_with_callback_proc` 多进程满血求解（子进程重建实例是固有秒级成本），`solve_pieces` 支持逐帧 `should_stop` 中止（OS 级 terminate，以 best-so-far 帧交付）—— 是串行 seed portfolio 控制器（kill / 达标即停）与标定管线的执行手段。Ctrl-C 退出码 130，已完成轮产物已落盘。

**串行 seed portfolio 控制器（PC-002）**：多 seed 串行循环经 `cli/portfolio.py` 控制器转发 —— **incumbent banking**（逐帧入账全局最优帧，被 kill/中断 seed 的最优帧同样参与，`best` 升级为帧级全局最优且含完整 `placed_items` 布局，result.json 新增 `portfolio` 段 `{target, incumbent, per_seed, theta_history, kill_mode}`）+ **R0 达标即停** + R4 队列耗尽交付。新旗标：`--target <0..1>`（原面积口径任一帧达标 → 当前 seed 被 stop（`killed=True`）+ 剩余队列不启动，退出码仍 0；缺省不启用）与 `--params <controller_params.json>`（标定参数文件：kill 阈值 + envelope 包络 + calibrated 开关）。单 seed 且不带 `--target` 时 result.json 为空 portfolio 段、`best` 保持旧语义（solve 数组 `real_density` 最大轮）—— 与 PC-001 基线无旗标冒烟对拍兼容：

```bash
ms-run-config data/configs/5336_coded_really.json --time 5 --target 0.9 --quiet   # R0 达标即停
ms-run-config data/configs/5336_coded_really.json --time 5 --target 0.9 --params controller_params.json
```

**kill 规则引擎 + shadow mode（PC-003）**：`--kill shadow|off|on`（默认 **shadow**；仅 `--target` 给定时激活 —— θ 初值 = target 是判据锚点）。必死 seed 提前淘汰省出预算：**R1 包络 kill**（队列序号 >1 且 τ>τ0 且 best-so-far 低于成功包络 `S(τ)−m` 持续 W 秒；`S(τ)` 来自 `--params` 的 `envelope`，无标定时 R1 整体禁用）、**R2 压缩期判决**（首帧 `phase=='compressing'` 时 `d + uplift_q95 < max(θ, I+ε)` → 必死；无标定用保守默认 0.005）、**R3 θ 衰减**（连杀 ≥ m_streak → `θ := I + δ` 单调只降，只降 kill 门槛，**R0 恒用 --target 真值**；衰减打一行不静默）；**seed 1（队列首）永不 kill**（锚定交付下限 + 校准样本）。保守默认 τ0=0.3、W=10s、m=0.5pt、ε=0.1pt、δ=0.3pt、m_streak=3（`--params` 数值键可覆盖）。**shadow 只记不杀**：kill 决策逐条 append `run_dir/kill_decisions.jsonl`（`{t, seed, rule, d, tau, S_tau, theta, I, would_kill}`，每 (seed, rule) 首次触发一条），`should_stop` 仅由 R0 触发；**on 才真杀**，且要求标定就绪（`--params` 含 `"calibrated": true`），否则自动降级 shadow 并 stderr warn：

```bash
ms-run-config data/configs/5336_coded_really.json --time 5 --target 0.9   # 默认 shadow：只记 kill_decisions.jsonl 不真杀
ms-run-config data/configs/5336_coded_really.json --time 5 --target 0.9 --kill on --params controller_params.json  # 标定就绪才真杀
```

**solver_opts 透传与配置轮换（PC-006）**：`--solver-opts '<JSON>'`（spyrrow 求解旋钮，**全 seed 生效**）/ `--rotate-opts`（内置 4 档轮换池逐 seed 取档 `pool[队列序 % 4]`，池首空档 = 默认行为）—— 探索/压缩配比（`exploration_pct` 0.1~0.95，换算两段 int 秒与 total_computation_time 互斥）+ 四叉树深度（`quadtree_depth` 3/4/5）+ 并行核数（`num_workers`，默认 4）让不同 seed 搜索行为**去相关**、上尾更易被摸到。白名单外键忽略、越界 clamp（清洗单一真相源 `web.solver._normalize_solver_opts`）；两旗标互斥 / JSON 坏串 / 非对象 → 退出码 1；不传任何旗标 = 现行行为不变（WS 协议与 web 前端零改动）；旗标给了才在 result.json `config` 段回显 `solver_opts` / `rotate_opts`。

```bash
ms-run-config data/configs/5336_coded_really.json --time 5 --solver-opts '{"exploration_pct": 0.6, "quadtree_depth": 5}'  # 固定档全 seed 生效
ms-run-config data/configs/5336_coded_really.json --time 5 --rotate-opts                                                # 内置池逐 seed 轮换
```

**LNS 波段重排后处理（PC-007）**：`ms-lns --run-dir <run目录> --time 30 --rounds 5 [--band-width 2865]` 对该 run 的最优布局（`portfolio.incumbent`，旧式 run 回退 best / 边车 `best_frame_s{seed}.json`）做波段级 ruin-and-recreate，突破单 seed 收敛分布上限。每轮：按 x 切竖直波段（缺省段宽 1.5×NEST_GATE_MM）→ 取局部密度（段内原面积和/(段宽×1910)）最差段 → 段内裁片构造**同口径子实例**（per_type/sizes/quantities 与母实例一致；demand>1 的 pid 全部副本整段重排禁拆分）多进程重解 → 新段跨度严格更窄才接受（新段压回原足迹内、右侧片左移 splice、总宽缩短），否则拒绝（**无改进时输出与输入逐字节不变**）；空段（纯空洞）无需求解直接让位。结束 `constraints.validate` + `y≤1910` 双复检，失败回退输入布局。跨组重叠护栏逐对不劣化（shapely 对比原布局基线，杜绝拼接咬合产生新重叠）。产物落 run_dir：`result_lns.json`（新 placed_items + 前后 width/density 对比 + 逐段明细）+ `lns_compare.svg`（前后双面板对比）。

```bash
ms-lns --run-dir out/config_runs/<run目录> --time 30 --rounds 5            # 缺省段宽 1.5×门幅有效宽
ms-lns --run-dir out/config_runs/<run目录> --time 60 --band-width 1500     # 更细波段粒度
```

**LNS 接入编排（PC-008）**：`ms-run-config ... --lns [--lns-time 30] [--lns-rounds 5]` —— portfolio 跑完（含 R0 提前停路径，对达标解也可再压宽度）后**自动**对最优布局（incumbent；单 seed 旧语义回退 best 帧边车）跑 PC-007 核心循环（`lns.postprocess_run_dir`，与 ms-lns 同一条代码路径），无需手工二次命令。**严格更优才回写** result.json：`portfolio.incumbent` 的 density/width_mm/placed_items 更新（seed/frame_index 保持来源帧出处）+ 新增 `lns` 段（前后对比 / Δ / 轮次明细 / 复检；placed_items 不入段控体积），`best` 同步；不优则 result.json **逐字节不变**（LNS 明细仍写 `result_lns.json` + `lns_compare.svg`）。stdout 汇总加 LNS 前后两行（`--quiet` 也打；LNS 逐段接受进度行走 `--quiet` 抑制）。回写只在改进判定后一次性整体重写 —— Ctrl-C 不留半写的 result.json（已完成轮保底落 result_lns.json，退出码 130）；`--lns-time` / `--lns-rounds` 单独给出或值 <1 → 配置错误退出 1；LNS 环节输入错误降级 stderr warn 跳过（退出码 0，不否定求解交付物）。

```bash
ms-run-config data/configs/5336_coded_really.json --time 5 --target 0.5 --lns --lns-time 5   # R0 停后自动 LNS 后处理
ms-run-config data/configs/5336_coded_really.json --time 300 --lns --lns-time 60 --lns-rounds 8
```

**run 统计库与 θ₀ 校准（PC-009）**：每次 run 结束（含 R0 提前停 / kill 路径）自动追加一行 JSONL 到 `out/run_stats.jsonl`：`{ts, source, sizes, class_key, seeds, target, best_density, n_killed, elapsed_total, config: {time, per_type, quantities}}`，`class_key` = sha1(source+sizes+quantities+per_type) 10 位短哈希（实例类指纹：同母版 + 码号集 + 订单配比 + 逐码公差视为同类）。写盘失败只 stderr warn 不阻塞主流程（统计沉淀是旁路产物）。`--target` 模式启动时读该库做 **θ₀ 校准**：当前 class_key 命中且 ≥5 条历史 → kill 门槛初值 `θ₀ = min(target, 历史最大 best_density + 0.003)`（历史最高 89.6% 的组合不再从 90 起跑 —— 分布越测越准），否则 θ₀ = target；θ₀ **只影响 kill 门槛**（R2/R3 判据锚），R0 停止条件恒用 `--target` 真值，校准说明行 `--quiet` 也打（判据变更不静默）。Ctrl-C / 求解失败的 run 不沉淀（不完整数据会污染历史 max）。

**标定管线（PC-004/005）**：`python -m materialsorting.cli.calibration` 四个子命令，为 kill 引擎产出数据依据（`--params` 消费的 `controller_params.json`）并防过拟合单一订单：
- **batch**：`--config <7键配置> [--tag T] [--short-seeds 20] [--short-time 90] [--full-seeds 8] [--full-time N]`（full-time 缺省用 config 的 `time`）。标定基实例 = `data/configs/5336_coded_really.json`（真实 per_type 公差 + 真实订单配比）。`commit_from_config` 只跑一次，逐 seed 串行 `solve_pieces`；曲线/best 帧落 `out/portfolio_calibration/<tag>/base/{short,full}/`，逐 seed 写 manifest.json（Ctrl-C 安全，重跑跳过已完整 seed）。
- **variants**：确定性订单邻域变体（seeded RNG，RNG seed=i）—— 只抖 `quantities` 的 (g码, 码∈sizes) 条目 `n' = max(1, n±1)`（保底 1 片；惰性条目不动），per_type/gate_mm/master_dxf/sizes 逐字段固定。产出 `variant_{i}.json`（i=0..3）+ 每变体 6 seed × 90s + 1 × 300s 曲线（共享同一 commit）。
- **analyze**：`--tag T --target P [--env-quantile 0.25]` 聚合曲线 → `analysis/`：`summary.json`（每 seed 终值/best/收敛平台 + mean/σ/P(≥target)）、`controller_params.json`（成功包络 S(τ)（τ 网格 0.05~1.0 步长 0.05）+ τ0/W/m/ε/δ/m_streak 推荐值；达标 seed <10 或包络格点不足 → `calibrated: false` 拒绝下发）、`generalization.json`（base 包络套用到各变体的误杀率/可迁移判定）。内部含 train/test 误杀回测 + 短/全秩相关 + uplift q50/q95。
- **simulate**（ETT 离线仿真器）：`--tag T --target P [--budget SEC] [--scenarios 500] [--env-quantile 0.25] [--shadow-log kill_decisions.jsonl]` 用历史轨迹**零求解成本**回放策略网格（单 seed 基线 / 均匀 best-of-k / kill 三档 / θ 衰减两档，**同总预算公平比较** k×B 恒等）→ `analysis/simulation_report.json` + 控制台表格：每策略 ETT（达标 = 首次达标时刻，不可达 = 实际耗时，kill 省时计入）、P(达标|预算内)、误杀率、不可达场景 incumbent 终值（截断轨迹用「kill 时刻 best + 条件期望增量」插值，物理下界 ≥ kill 时刻 best-so-far，无 hindsight）。**变体曲线作 held-out**（kill 包络只源自 base 池、按仿真预算 B 绝对墙钟重采样）：推荐档须 base 与变体 ETT 双不劣于单 seed 基线且两者误杀率 <5%，`recommendation.params` 键与 controller_params.json 同构可直接抄进 `--params`。场景采样确定性（|pool|^k ≤ 4096 全枚举，否则固定种子 bootstrap）。`--shadow-log` 统计真实 would-kill 决策的假阳性（配同目录 curve_s{seed}.json；决策后才达标 = 假阳性，全程不达标 = 正确 kill）。

```bash
python -m materialsorting.cli.calibration batch --config data/configs/5336_coded_really.json
python -m materialsorting.cli.calibration variants --config data/configs/5336_coded_really.json
python -m materialsorting.cli.calibration analyze --tag 5336_coded_really --target 0.85
python -m materialsorting.cli.calibration simulate --tag 5336_coded_really --target 0.85   # 参数选型零真实求解成本
```

真实跑批 ≈2 小时机器时间（28 base seed + 4 变体 × 7 seed），产物全部落 `out/portfolio_calibration/`（gitignore 区），不触碰 `out/config_runs/` 与 web 数据目录。`controller_params.json` 的键名与 `--params` 直接对接（`ms-run-config ... --params out/portfolio_calibration/<tag>/analysis/controller_params.json`）。

**不触碰 web 数据**：CLI 唯一可写目录是 `out/config_runs/`（标定管线为 `out/portfolio_calibration/`，PC-009 统计库为 `out/run_stats.jsonl` 单文件），绝不写 `out/sparrow_baseline/pieces_intermediate.json`（web 事实源）与 `out/uploads/` —— 与 ms-web 同时运行互不干扰（并行回归已验证：web 求解进行中跑 CLI，结束后两者事实源 mtime/内容不变、uploads 无新目录）。

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
| `ms-run-config` | 配置驱动排料一条命令（commit → 串行多 seed 求解 → `out/config_runs/` result.json；`--lns` 自动 LNS 后处理（PC-008）；run 结束沉淀统计 + θ₀ 按实例类校准（PC-009），见上文「配置驱动求解」） |
| `ms-lns` | LNS 波段重排后处理（对 run 目录最优布局波段级 ruin-and-recreate，产 result_lns.json + 前后对比 SVG，PC-007） |
| `python scripts/embed_piece_codes.py <母版.dxf>` | 把 g01+ 编号植入母版 DXF 生成 `_coded.dxf`（与 Web 解析同源编号，幂等 + 自校验，版师在 ET2008 可对上 g 码） |

也可用 `python -m materialsorting.<subpackage>.<module>` 形式运行。

## 路径覆盖

`materialsorting/paths.py` 的数据/产物/前端目录均可通过环境变量覆盖：`MS_DATA_DIR`、`MS_OUT_DIR`、`MS_STATIC_DIR`（默认指向 `materialSorting-web/static/`，dev 模式下无需 override，前端由 Vite 直接 serve）。

## 架构与约定

详见 [CLAUDE.md](CLAUDE.md)。排料规则与各阶段方案详见 [.docs/](.docs/)。
