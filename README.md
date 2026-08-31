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

## 多会话机制（web 多端隔离，2026-08-27）

`ms-web` 按 **会话（sid）** 隔离多端数据，解决此前「任一端 commit 即覆盖所有人当前文档」的串台问题：

- **sid 约定**：前端首次加载铸 `uuid4 hex` 存 localStorage（`ms_sid`，刷新不变），全部 HTTP 请求注入 `X-Session-Id` Header，WS `/ws/solve` 走 `?sid=` query（浏览器 WS 不能自定义 Header）。后端各端点经 `sessions.SessionRegistry.resolve()` 单一解析点归属（契约详见 [.docs/technical/agent-api-reference.md](.docs/technical/agent-api-reference.md)）。
- **隔离面**：每会话一份 pieces 快照（commit 主写 `out/uploads/<doc_id>_pieces/pieces_intermediate.json` per-doc 落盘 + 会话绑定）+ 一份策略长跑状态槽（run_name/cfg/marker 按 sid 前缀互斥）；ptypes / 求解 / 导出 / 高级运行全链路互不串台。
- **生命周期**：容量上限 4 个并发会话（第 5 端页面加载即弹「用户过多」）；空闲 10 分钟过期（过期墓碑 1h，任一操作弹「已过期」阻断式弹窗，唯一出口 = 刷新页面铸新 sid）；**求解中（WS 钉住）/ 策略轮询中的会话不被误杀**；**高级/极限运行存活期间与会话终态后宽限窗（缺省 2h，2026-08-30）内同样不逐出** —— 睡眠唤醒、关页、跑完挂机等轮询中断场景不丢结果，宽限窗内任何操作即恢复正常空闲语义（被钉住的会话仍占名额）。
- **无 sid 请求 = default 会话**：豁免上限/过期/墓碑（旧 curl/脚本/单文档时代行为逐字节一致）；`GET /` 响应头 `Cache-Control: no-cache`（防旧 index.html 缓存滞留）。
- **磁盘兜底**：`out/uploads/` 按 TTL 自动清理（超龄 `<doc_id>.dxf` + `<doc_id>_pieces/` 成对删，活跃会话 / 策略 marker 引用 / 未超龄者保护），commit 后与进程启动时双触发 best-effort。

**环境变量**（非法值 warn 回退缺省）：

| 变量 | 缺省 | 作用 |
|---|---|---|
| `MS_SESSION_MAX` | `4` | 并发会话上限（default 不占额；超出 → 429 `session_limit`） |
| `MS_SESSION_TTL_SEC` | `600` | 空闲过期阈值秒数（惰性检查 + 30s daemon 扫描） |
| `MS_RESULT_GRACE_SEC` | `7200` | 策略/极限 run 终态后会话宽限秒数（run 存活期间滚动钉住不逐出；期间会话仍占名额） |
| `MS_UPLOAD_TTL_DAYS` | `14` | uploads 磁盘清理 TTL 天数（按 mtime，成对判龄） |

## 导出与 PLT 唛架信息表格（2026-08-30）

工作台「导出」支持 PNG / R12-DXF / PLT 三格式。**PLT 导出前弹「唛架信息表格」填写窗**（纯取消型：ESC/遮罩/取消只关窗，唯一提交路径 = 「导出 PLT」）。信息表格 14 字段、**key/value 两行网格 + 旋转 90° 版式**（对标前端「裁片设置」表格：第一行 key、第二行 value、行列分隔线 + 外框；文字基线沿门幅方向书写、14 列自唛架右下顶点**垂直向上 3cm（y=30mm）**起沿用布方向排开，生产排料视图（切割视图逆时针旋 90°）里呈现为正常水平可读的两行表：key 行在上、value 行在下、方案名称列最左），附在排料图**外围**（表格外框左缘与唛架右边框**共用一条线**（间隔 0mm，v5 定案）；表宽 36mm = 两条 18mm 行带）——**不占排料区、不计入用料**（仅在 PLT 图纸上展示排料信息，实际裁 cutting 时不处理这块内容；PS 纸长覆盖表格区 =(width+66)×40）。

- **手输 6 字段**（弹窗填写，localStorage `ms_export_table` 跨导出记忆排料师/床次等；默认：床次=A料、经纱缩水=0.0%、纬纱缩水=0.0%、排料师=空、样板号=noname、备注=空；全自由字符串，超长后端截断 + warn）：床次 / 经纱缩水 / 纬纱缩水 / 排料师 / 样板号 / 备注。
- **自动 8 字段**（后端按当前方案计算，`web/plt_table.py`）：方案名称（勾选尺码按系数分组拼式，如 `(30+34+35)+(31+32+33)*1.5+(36)*0.5=8套`；每码系数 = 该码**面积最大裁片**的 pid 计数 ÷2 —— 前后幅数量恒相等，取最大片即前/后幅套数）；本床包含套数（方案名称求和）；利用率 = real_density×100（2 位 + %）；幅宽（m）= gate_mm÷1000；料长（m）= width_mm÷1000 **不含表格**；每套用料（m）= 料长 ÷ 套数；片数 = 总裁片数；绘图时间 = 导出时刻 `YYYY-MM-DD HH:MM`（无秒）。幅宽/料长/每套用料均 3 位小数。
- **列序**（列 0→列 13 自起始 y=30mm 沿用布方向 = 生产视图自左向右）：方案名称 / 床次 / 经纱缩水 / 纬纱缩水 / 利用率 / 幅宽 / 料长 / 本床包含套数 / 每套用料 / 片数 / 排料师 / 绘图时间 / 样板号 / 备注。key 行带最靠唛架（生产视图上排）、value 行带在外（下排）。
- **字体/几何**：**单线矢量字**（v5 默认路径，对拍生产件一笔单线观感）：汉字笔画中线（hanzi-writer-data 9574 字，Arphic PL 许可；文件保留 MMaH y 向下源坐标、加载期镜像翻 y——与 JHF 同一约定，不翻则汉字逐字上下镜像）+ ASCII Hershey Roman Simplex（92 字符；JHF y 自字顶向下，加载期整体翻 y 到基线=0）；未覆盖字符回退捆绑 Noto Sans SC 轮廓（OFL 许可，`resources/fonts/` 内含 `OFL.txt`）+ 每字符一次 warn —— 任何手输汉字 100% 可渲染、Windows/Ubuntu 一致；cmap 未命中画豆腐框 + 日志 warn；入口统一 NFKC 归一（全角→半角、—·。、→ASCII）。PU/PD 折线、全文仍 ASCII、无 LB/VS 指令——「PLT 不加文字」口径指 g 码不进 PLT，表格是文件级元数据。**全字段统一字高 12mm**（含方案名称——36mm 大字版已被否决）；**列宽自适应** = max(key 宽, value 宽) + 2×10mm 内衬（单元格内容**居中**、离左右边 ≥1cm，v5 定案），**表长自适应** = Σ列宽（不与门幅等长，实测 7 码 ≈1020mm @12mm 字高/10mm 内衬），仅受「30mm 起始 + Σ ≤ 门幅−20mm」约束：超限先全表缩字高（下限 7mm）再等比压列宽（单元格尾部截断兜底）并记 warn。文字基 `u=(0,1)/w=(-1,0)` 右手系直接生成，生产排料视图里水平正立可读（已与生产件并排对拍验证方向一致）。
- **门幅框口径（2026-08-31）**：PLT 门幅框满幅 `[0, gate]` 不内缩（撤销旧 Y 双边内缩 5mm——内缩框被切割软件当布料范围、贴门幅边排的裁片视觉穿框 5mm 成「越界布料」；现框=裁剪界=求解约束带三口径合一，贴边裁片平切框线，与生产件观感一致）。需物理留边（布边不裁）按 2026-08-28 定案机制直接输更小门幅。
- **零回归**：不带 `table` 键（旧前端 / 直接 POST）导出的 PLT 与旧版逐字节一致（边框恒到 width_mm、纸长不含表格；2026-08-31 门幅框满幅化后逐字节基线以当日版为界）；带表格时边框仍到 width_mm（表格共线外挂）、PS 纸长 =(width+66)×40 覆盖表格区；PNG/DXF 载荷忽略 `table` 键。
- 载荷契约（`POST /export` 的可选 `table` 对象，snake_case）：`bed_no` / `warp_shrink` / `weft_shrink` / `planner` / `style_no` / `remark`，详见 [.docs/technical/agent-api-reference.md](.docs/technical/agent-api-reference.md)。

## 配置驱动求解（ms-run-config，无需浏览器）

评估配置（码号组合 / 公差 / 数量矩阵 / 多 seed）不必开浏览器工作台，一条命令跑完「commit → 求解」：

```bash
ms-run-config data/configs/5336_coded_sizes32-38.json            # 按 config 里的 time/seeds 求解
ms-run-config data/configs/5336_coded_sizes32-38.json --time 5   # 冒烟：单轮 5s（result.json 回显生效值）
python -m materialsorting.cli.run_config <config.json> --name demo --quiet   # 等价 python -m 形式
```

配置是 **9 键 JSON schema**（除 `seeds` 外字段名与 WS StartPayload 契约 1:1；示例见 `data/configs/`，拼写/类型/路径错误在启动前就地拦下，中文报错含字段名）：

| 键 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `master_dxf` | str | ✓ | 母版 DXF 路径；相对路径先按 CWD 再按仓库根解析 |
| `gate_mm` | num | ✓ | 门幅（mm，>0）；intermediate 口径；密度分母 = gate_mm（2026-08-28 版师定案：输入幅宽即实际幅宽，单一口径，与求解约束带同口径） |
| `sizes` | list | — | 码号过滤（JSON 整数列表，非空）；缺省 = 全部码号 |
| `time` | int | — | 单轮求解时长（秒，正整数），缺省 300 |
| `seeds` | list | — | **串行**种子列表（非负整数、不重复、非空），缺省 `[0]`；≥2 个时逐 seed 串行求解，`best` 取原面积口径 `real_density` 最大轮（消除单 seed 随机性；种子不要求连续）。取代旧 `seed`/`multi_seed`/`seed_count` 三键（旧键按未知键报错） |
| `per_type` | dict | — | `{g码: {d?, tol?}}` 逐 g 码公差覆盖（d=重合 mm、tol=旋转公差 °，≥0；超全局上限不报错但被钳制） |
| `quantities` | dict | — | `{g码: {码号: 数量}}` per-size demand（码号键须数字字符串或 `"null"`，数量 JSON 数字 ≥0 整数） |
| `band` | dict | — | 腰头成带 `{'enabled': bool, 'label': g码}`（enabled=true 时 label 必填、匹配 `^g\d+$`）；`solve_pieces` 经 `solve_with_callback_proc(band=...)` worker 进程内成带+展开；2026-08-22 起与 `--strategy` 兼容（web 策略入口写进 config）；on 时 `--lns` 自动 warn 跳过 |
| `prefix` | dict | — | 起始端成套前后幅 `{'enabled': bool, 'front': g码, 'back': g码}`（enabled=true 时 front/back 必填、匹配 `^g\d+$` 且 front≠back）；资格码（该码 front/back demand 均 ==2）存在性由 worker 求解期 fail-fast，web 策略入口经 `_parse_prefix` start 期 400 早退；2026-08-25 起与 `--strategy` 兼容（逐 seed 资格码 seeded 选取确定性重放）；on 时 `--lns` 自动 warn 跳过 |

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

> 语义过载备注：`--strategy race`（门杀模式）复用同一 `kill_decisions.jsonl` 逐行 schema 记录门判决 —— 其中 `S_tau` 存**门参考值 bar**（非包络 `S(τ)`）、`theta` 恒 `null`（race 不维护 θ）、`rule` 为 `R5_race_gate`；含豁免/通过/门杀三类行，以 `would_kill` 区分。

**策略双模式（US-001/002，`--strategy [se|race]`，给定总预算拿更高利用率）**：词汇表 —— **race 门杀**（方案 B，裸旗标 `--strategy` 即此档）：每 seed 按 `--race-budget`（默认 180s）预算启动，**门时刻**（预算 × `--race-gate` τ，默认 0.5 → 90s）处**严格破纪录**（当前 best 严格 > **bar** 才续跑满程，否则真 terminate + best-so-far 帧交付，省出预算再投资后续 seed；首 seed 豁免 —— 无 bar 参照即锚定交付下限）；**SE 筛延**（方案 A，`--strategy se`）：阶段 1 k 轮 `--se-screen`（默认 90s）串行筛选，阶段 2 **冠军**（筛选 argmax，平手取队列先）同 seed 全新 `--se-extend`（默认 180s）run，边车 `best_frame_s{seed}_ext.json`；**名义记账**：门杀 seed 计 92.5s（90s 门 + 2.5s 启动）、满程 seed 计 182.5s（180s + 2.5s），`--time` 在策略模式 = **总预算秒数且必填**（与两档共享口径对账，T≥275 才可启动）；**确定性重放**：同 seed + 同 time_budget 逐帧一致（求解链路确定性），因此 SE 的延长 = 冠军 180s 潜力的**零方差求值** —— 两模式期望等价是机制保证而非巧合。

```bash
ms-run-config data/configs/5336_coded_really.json --strategy --time 1200 --quiet                     # race 门杀（默认档）
ms-run-config data/configs/5336_coded_really.json --strategy se --time 1200 --quiet                  # SE 筛延
ms-run-config data/configs/5336_coded_really.json --strategy --time 600 --race-gate 0.4              # 调门位置（默认 0.5）
ms-run-config data/configs/5336_coded_really.json --strategy se --time 600 --se-screen 90 --se-extend 180   # 显式双参（即默认值）
```

参数旗标 `--se-screen` / `--se-extend` / `--race-budget` / `--race-gate`（(0,1) 开区间）须与 `--strategy` 同给；种子流无重复（config `seeds` 优先、max+1 补齐）；`--target` 共存时 R0 达标即停优先于模式继续；`--kill` 与 `--strategy` 显式同给退出 1（策略模式判据内建，不叠 kill 引擎）。产物 `run_dir/strategy.json`（`mode`/`total_budget`/`planned_seeds`/`race|se` 参数/kill 统计）；无 `--strategy` 时行为与 result.json 与现版**逐字节一致**（零回归红线）。

**四档速查表（5336 实例；离线对决跨 fork 诚实口径：筛选读 90s 曲线终值、延长/续跑读 300s 曲线 180s 帧，8 配对 seed、bootstrap 3000）**：

| 档位 | 均分 k×90s | 方案 A：SE 延 180 | 方案 B：race180（破纪录门） |
|---|---|---|---|
| 10min | 86.32% | 86.33% | 86.40% |
| 20min | 86.80% | 87.01% | 87.05% |
| 30min | 86.94% | 87.18% | 87.16% |
| 1h | 87.00% | 87.22% | 87.22% |

10min 档三法打平属预期（延长占预算比过高、筛选票过少），20min 起双模式比均分 +0.2pt 量级，1h 达上限 —— 不设 auto 阈值、四档全支持两模式（用户显式选择）。**现场对跑**（live_duel_ab，共享 fresh seed 序列 Random(2026)、同一 commit、各 1200s 名义预算）：**A=B=88.38% 精确平**（冠军 seed221：A 筛选 87.63 → 延长 88.38；B 门值 87.99 → 续跑 88.38，后续 11 seed 全部门杀且事后全部正确；最优帧 88.41% @172s 两臂相同）—— 与确定性重放机制互为印证。

**极限运行（`--extreme`，race 门杀 × 实验结论极限参数）**：一条命令跑 best-of-k 右尾长跑，目标从「期望最优」换为「右尾最优」。内部展开为 `--strategy race --race-budget <extreme-budget> --race-gate 0.5 --solver-opts '{"exploration_pct": 0.7, "early_termination": false, "num_workers": 4}'`（手敲三件套逐字段等价；`quadtree_depth` 不写 = 缺省 4，方案 §2.6 A/B 关闭调优）。**糖衣旗标独占策略与旋钮**：与 `--strategy`/`--kill`/`--solver-opts`/`--rotate-opts` 及 4 个策略参数旗标任一显式同给 → 配置错误退出 1（极限参数是 5336 实验结论固化，不是可调项）；`--extreme-budget` 仅收 **600（默认，门判别力 ρ=0.916 最强、吞吐 ×1.7）/ 1200** 两档（2400s+ 门判别力失效是硬边界）；`--time` = 总预算秒数且必填（600 档最低 905s = 首轮全程 602.5 + 一轮门段 302.5）。门杀判据逐字复用 `decide_race_kill`（门时刻 = 每 seed 预算 × 0.5，严格破纪录才续跑）；`run_stats.jsonl` config 段 additive 加 `"extreme": {"budget": B}`（class_key 组成不变，与历史 run 可比）。band/prefix 2026-08-30 起支持：web 端随高级配置透传（同高级运行，`_parse_band`/`_parse_prefix` 同一校验点），CLI 端走 9 键 config 的 `band`/`prefix` 键本就模式无关。Web 端为独立「极限运行」按钮（`/api/extreme/*` 四路由，与高级运行同会话 409 单飞互斥、跨会话独立）。同总预算 4h 三臂对拍验收（extreme vs race 默认档 vs 均分 600s×24）见 [.docs/business/极限运行_AB验收报告.md](.docs/business/极限运行_AB验收报告.md)。

```bash
ms-run-config data/configs/5336_coded_really.json --extreme --time 7200 --quiet   # 2h 极限长跑（≈20 轮）
ms-run-config data/configs/5336_coded_really.json --extreme --time 14400          # 4h（验收档）
```

**solver_opts 透传与配置轮换（PC-006）**：`--solver-opts '<JSON>'`（spyrrow 求解旋钮，**全 seed 生效**）/ `--rotate-opts`（内置 4 档轮换池逐 seed 取档 `pool[队列序 % 4]`，池首空档 = 默认行为）—— 探索/压缩配比（`exploration_pct` 0.1~0.95，换算两段 int 秒与 total_computation_time 互斥）+ 四叉树深度（`quadtree_depth` 3/4/5）+ 并行核数（`num_workers`，默认 4）让不同 seed 搜索行为**去相关**、上尾更易被摸到。白名单外键忽略、越界 clamp（清洗单一真相源 `web.solver._normalize_solver_opts`）；两旗标互斥 / JSON 坏串 / 非对象 → 退出码 1；不传任何旗标 = 现行行为不变（WS 协议与 web 前端零改动）；旗标给了才在 result.json `config` 段回显 `solver_opts` / `rotate_opts`。

```bash
ms-run-config data/configs/5336_coded_really.json --time 5 --solver-opts '{"exploration_pct": 0.6, "quadtree_depth": 5}'  # 固定档全 seed 生效
ms-run-config data/configs/5336_coded_really.json --time 5 --rotate-opts                                                # 内置池逐 seed 轮换
```

**LNS 波段重排后处理（PC-007）**：`ms-lns --run-dir <run目录> --time 30 --rounds 5 [--band-width 2970]` 对该 run 的最优布局（`portfolio.incumbent`，旧式 run 回退 best / 边车 `best_frame_s{seed}.json`）做波段级 ruin-and-recreate，突破单 seed 收敛分布上限。每轮：按 x 切竖直波段（缺省段宽 1.5×默认门幅 1980=2970）→ 取局部密度（段内原面积和/(段宽×该 run 门幅)）最差段 → 段内裁片构造**同口径子实例**（per_type/sizes/quantities 与母实例一致；demand>1 的 pid 全部副本整段重排禁拆分）多进程重解 → 新段跨度严格更窄才接受（新段压回原足迹内、右侧片左移 splice、总宽缩短），否则拒绝（**无改进时输出与输入逐字节不变**）；空段（纯空洞）无需求解直接让位。结束 `constraints.validate` + `y≤该 run 门幅` 双复检，失败回退输入布局。跨组重叠护栏逐对不劣化（shapely 对比原布局基线，杜绝拼接咬合产生新重叠）。产物落 run_dir：`result_lns.json`（新 placed_items + 前后 width/density 对比 + 逐段明细）+ `lns_compare.svg`（前后双面板对比）。

```bash
ms-lns --run-dir out/config_runs/<run目录> --time 30 --rounds 5            # 缺省段宽 1.5×默认门幅≈2970
ms-lns --run-dir out/config_runs/<run目录> --time 60 --band-width 1500     # 更细波段粒度
```

**LNS 接入编排（PC-008）**：`ms-run-config ... --lns [--lns-time 30] [--lns-rounds 5]` —— portfolio 跑完（含 R0 提前停路径，对达标解也可再压宽度）后**自动**对最优布局（incumbent；单 seed 旧语义回退 best 帧边车）跑 PC-007 核心循环（`lns.postprocess_run_dir`，与 ms-lns 同一条代码路径），无需手工二次命令。**严格更优才回写** result.json：`portfolio.incumbent` 的 density/width_mm/placed_items 更新（seed/frame_index 保持来源帧出处）+ 新增 `lns` 段（前后对比 / Δ / 轮次明细 / 复检；placed_items 不入段控体积），`best` 同步；不优则 result.json **逐字节不变**（LNS 明细仍写 `result_lns.json` + `lns_compare.svg`）。stdout 汇总加 LNS 前后两行（`--quiet` 也打；LNS 逐段接受进度行走 `--quiet` 抑制）。回写只在改进判定后一次性整体重写 —— Ctrl-C 不留半写的 result.json（已完成轮保底落 result_lns.json，退出码 130）；`--lns-time` / `--lns-rounds` 单独给出或值 <1 → 配置错误退出 1；LNS 环节输入错误降级 stderr warn 跳过（退出码 0，不否定求解交付物）。

```bash
ms-run-config data/configs/5336_coded_really.json --time 5 --target 0.5 --lns --lns-time 5   # R0 停后自动 LNS 后处理
ms-run-config data/configs/5336_coded_really.json --time 300 --lns --lns-time 60 --lns-rounds 8
```

**run 统计库与 θ₀ 校准（PC-009）**：每次 run 结束（含 R0 提前停 / kill 路径）自动追加一行 JSONL 到 `out/run_stats.jsonl`：`{ts, source, sizes, class_key, seeds, target, best_density, n_killed, elapsed_total, config: {time, per_type, quantities}}`，`class_key` = sha1(source+sizes+quantities+per_type) 10 位短哈希（实例类指纹：同母版 + 码号集 + 订单配比 + 逐码公差视为同类；band/prefix 开启时各追加 label 组件成新 key，避免 ±2pt 级密度差混同 θ₀ 历史分布）。写盘失败只 stderr warn 不阻塞主流程（统计沉淀是旁路产物）。`--target` 模式启动时读该库做 **θ₀ 校准**：当前 class_key 命中且 ≥5 条历史 → kill 门槛初值 `θ₀ = min(target, 历史最大 best_density + 0.003)`（历史最高 89.6% 的组合不再从 90 起跑 —— 分布越测越准），否则 θ₀ = target；θ₀ **只影响 kill 门槛**（R2/R3 判据锚），R0 停止条件恒用 `--target` 真值，校准说明行 `--quiet` 也打（判据变更不静默）。Ctrl-C / 求解失败的 run 不沉淀（不完整数据会污染历史 max）。

**标定管线（PC-004/005）**：`python -m materialsorting.cli.calibration` 四个子命令，为 kill 引擎产出数据依据（`--params` 消费的 `controller_params.json`）并防过拟合单一订单：
- **batch**：`--config <9键配置> [--tag T] [--short-seeds 20] [--short-time 90] [--full-seeds 8] [--full-time N]`（full-time 缺省用 config 的 `time`）。标定基实例 = `data/configs/5336_coded_really.json`（真实 per_type 公差 + 真实订单配比）。`commit_from_config` 只跑一次，逐 seed 串行 `solve_pieces`；曲线/best 帧落 `out/portfolio_calibration/<tag>/base/{short,full}/`，逐 seed 写 manifest.json（Ctrl-C 安全，重跑跳过已完整 seed）。
- **variants**：确定性订单邻域变体（seeded RNG，RNG seed=i）—— 只抖 `quantities` 的 (g码, 码∈sizes) 条目 `n' = max(1, n±1)`（保底 1 片；惰性条目不动），per_type/gate_mm/master_dxf/sizes 逐字段固定。产出 `variant_{i}.json`（i=0..3）+ 每变体 6 seed × 90s + 1 × 300s 曲线（共享同一 commit）。
- **analyze**：`--tag T --target P [--env-quantile 0.25]` 聚合曲线 → `analysis/`：`summary.json`（每 seed 终值/best/收敛平台 + mean/σ/P(≥target)）、`controller_params.json`（成功包络 S(τ)（τ 网格 0.05~1.0 步长 0.05）+ τ0/W/m/ε/δ/m_streak 推荐值；达标 seed <10 或包络格点不足 → `calibrated: false` 拒绝下发）、`generalization.json`（base 包络套用到各变体的误杀率/可迁移判定）。内部含 train/test 误杀回测 + 短/全秩相关 + uplift q50/q95。
- **simulate**（ETT 离线仿真器）：`--tag T --target P [--budget SEC] [--scenarios 500] [--env-quantile 0.25] [--shadow-log kill_decisions.jsonl]` 用历史轨迹**零求解成本**回放策略网格（单 seed 基线 / 均匀 best-of-k / kill 三档 / θ 衰减两档 / **策略双档 se180·race180**（US-003），**同总预算公平比较** k×B 恒等）→ `analysis/simulation_report.json` + 控制台表格：每策略 ETT（达标 = 首次达标时刻，不可达 = 实际耗时，kill 省时计入）、P(达标|预算内)、误杀率、不可达场景 incumbent 终值（截断轨迹用「kill 时刻 best + 条件期望增量」插值，物理下界 ≥ kill 时刻 best-so-far，无 hindsight）。**策略双档走配对曲线回放**（`base/{short,full}` 同 seed 配对、short 终值 ≥90s 且 full 终值 ≥180s 才合格；跨 fork 诚实口径同现场：筛选读 short 曲线终值、延长/续跑读 full 曲线 180s 帧），judgment 复用 US-001 单一真相源 `decide_race_kill`/`race_plan`/`se_plan`，另出**E[max] 口径**副表（delivered 期望 / 漏 max 率 / 对配对 uniform90 基线的增益）。**变体曲线作 held-out**（kill 包络只源自 base 池、按仿真预算 B 绝对墙钟重采样）：推荐档须 base 与变体 ETT 双不劣于单 seed 基线且两者误杀率 <5%（策略双档同判据纳入候选，`params` 含 `strategy`/`time`/`race_*`/`se_*` 键），`recommendation.params` 键与 controller_params.json 同构可直接抄进 `--params`。场景采样确定性（|pool|^k ≤ 4096 全枚举，否则固定种子 bootstrap）。`--shadow-log` 统计真实 would-kill 决策的假阳性（配同目录 curve_s{seed}.json；决策后才达标 = 假阳性，全程不达标 = 正确 kill）。

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
   ↓ ms-web（工作台读取 + 可视化 + 导出 PNG/R12-DXF/PLT）

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

`materialsorting/paths.py` 的数据/产物/前端目录均可通过环境变量覆盖：`MS_DATA_DIR`、`MS_OUT_DIR`、`MS_STATIC_DIR`（默认指向 `materialSorting-web/static/`，dev 模式下无需 override，前端由 Vite 直接 serve）、`MS_FONT_DIR`（PLT 表格字体目录，默认包内 `resources/fonts/`）。

## 架构与约定

详见 [CLAUDE.md](CLAUDE.md)。排料规则与各阶段方案详见 [.docs/](.docs/)。
