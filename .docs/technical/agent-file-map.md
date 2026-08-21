# Agent 文件地图 — 后端

> 后端 Python 包 + repo 根维护脚本（`scripts/`）逐文件索引。改任何 `.py` 先看这里定位职责与下游影响，并同步本文件。
> 前端文件地图见 [agent-component-map.md](agent-component-map.md)；HTTP/WS 契约见 [agent-api-reference.md](agent-api-reference.md)。

## 分层架构（依赖单向，禁反向）

```
cli  →  web  →  nesting_engine  →  nesting_bounds  →  dxf_parser
       (sparrow_experiments → sparrow_baseline)
```

每层只依赖下层；下层不得 import 上层。`paths.py` 是所有层的公共路径常量来源。

## 目录树

```
materialSorting-server/
├── pyproject.toml                     包定义 + 8 个 ms-* console_scripts + [web] 可选依赖（fastapi/uvicorn/matplotlib/python-multipart）
└── src/materialsorting/
    ├── paths.py                       集中路径常量（优先环境变量，禁止硬编码 ..）
    ├── dxf_parser/                    底层 DXF 读写（仅 stdlib + ezdxf）
    │   ├── collect.py                 US-003 母版深度解析（collect_pieces_with_details + LAYER_MAPPING）
    │   ├── reader.py                  ezdxf recover + GBK 块名 + R12 POLYLINE 读取
    │   ├── geometry.py                纯几何算子（无 ezdxf，可单测）
    │   ├── model.py                   PieceOutline dataclass（解析期唯一 IR；US-002 扩 internal/notches/net_polygon）
    │   ├── explore.py                 母版全裁片探索 CLI（SVG/JSON/CSV）
    │   └── export_dxf.py              PieceOutline → 单裁片 R12 DXF
    ├── nesting_bounds/
    │   └── load_pieces.py             单裁片（pieces_manifest.json 驱动）→ 布纹对齐 → 归一化（US-001 v2：无镜像展开）；定义 NestPiece（pid={label}_{size}）+ 门幅双口径常量（GATE_MM=1980 显示 / PLOT_SAFE_MAX_Y_MM=1910 绘图仪可写 / NEST_GATE_MM=min 求解约束带）
    ├── nesting_engine/
    │   ├── constraints.py             v0.3 约束常量 + 旋转公差离散化 + 位图腐蚀 + 合法性校验
    │   ├── sparrow_baseline.py        基线求解 + ★共享层（被 experiments/export/solver 复用）
    │   ├── sparrow_experiments.py     旋转/重合公差实验
    │   ├── labeling.py                g01+ 编号单一真相源（assign_codes；parse/commit 两管线共用）
    │   ├── waist_band.py              US-009 腰头成带核心（build_band_plan/expand_placements/BandChunk；禁 import web）
    │   └── waist_band_gate.py         US-010 go/no-go 试点闸门（三组决策实验 CLI；实测 no-go → 转 v1.1 混填料）
    ├── web/                           FastAPI + WS 工作台（详见 agent-api-reference.md）
        ├── server.py                  app + 路由编排（GET /、/static、POST /export、POST /api/parse-dxf、POST /api/commit-to-nesting、GET /api/ptypes、WS /ws/solve）+ US-020 _PIECES_STATE 可 reload（threading.Lock immutable snapshot）+ US-004 上传解析 + US-010 commit-to-intermediate（commit 后 reload）+ US-022 intermediate 加 label + WS quantities 入参；2026-08-20 拆分后 329 行 = app 创建/静态 mount + 两个上传路由（_commit_to_nesting_sync 留守：测试 monkeypatch server 命名空间）+ include routes_views/routes_ws/strategy；state 与线程池在 runtime.py、re-export 全部拆出符号
        ├── runtime.py                 共享运行时单例（2026-08-20 自 server.py 拆出）：_PIECES_STATE 快照机制（_state_lock/_build_pieces_state/_reload_pieces_state/_get_pieces_state）+ 启动期 reload + 共享 _executor（6 workers）；import 即副作用、先于 app 创建
        ├── parse_payload.py           纯函数（2026-08-20 自 server.py 拆出）：_size_sort_key/_build_parse_payload（parse 响应体）/_build_label_representatives（g 码代表裁片）
        ├── routes_views.py            APIRouter（2026-08-20 自 server.py 拆出）：GET / + GET /api/ptypes + POST /export（经 export 门面）
        ├── routes_ws.py               APIRouter（2026-08-20 自 server.py 拆出）：WS /ws/solve + _terminate_solve_process + _SENTINEL；US-011 band 服务端校验 _parse_band（label ^g\d+$ / 存在母版 / quantities>0 / 硬警告形态（min 边<60mm 或长宽比>6）需显式 ack:true；非法=结构化 error 早退+显式 close）+ on_stage 回调（{type:stage,stage:band,fill_pct,bbox,fallback,elapsed}，manifest 前唯一一次）→ run_solve 传 band=band_cfg
        ├── solver.py                  build_instance（US-022 quantities→demand，0 跳过；US-002 per_type[label][sizeKey] 命中即覆盖 + internal 删 + color=size_color(size)（2026-08-20 尺码键）；strip_height=min(gate,PLOT_SAFE_MAX_Y_MM) 求解钳绘图仪可写幅宽；US-006 solver_opts 白名单透传 exploration_pct/quadtree_depth/num_workers；US-011 exclude_labels={label} 只跳 spyrrow Item 层（pid_meta/total_area/manifest 逐字段不变，band on/off 一致性关键）+ extra_items 构造期注入组合片（spyrrow instance.items 是 Rust 侧副本 list，构造后 append 静默失效 —— 实测组合片整解缺席））+ build_pid_meta（US-004 抽出的纯函数管线 demand→per_type→erode/clean→(pid_meta,total_area,n)，不 import sparrow，/api/strategy/result 建 manifest 复用）+ solve_with_callback（threading 旧版，保留）+ solve_with_callback_proc（US-025 多进程版，返回 process 句柄可 terminate；US-011 +on_stage 回调 +band 参数透传 solve_worker）
        ├── strategy.py                US-004 策略桥接四路由（POST /api/strategy/start 子进程 spawn run_config --strategy；GET /status 无状态惰性轮询 + run_dir 快照差分发现 + 孤儿 marker 分支；POST /stop 树杀 taskkill//T /F 或 killpg；GET /result incumbent/best_frame 回退 + build_pid_meta manifest；marker .web_strategy_active.json 落 out/config_runs/；与 server 仅文件尾互相 import，_pieces_state 惰性导入防环）
        ├── solve_worker.py             US-025 子进程入口（顶层 solve_worker，spawn 可 pickle；子进程内 build_instance + solve，仅 JSON 数据跨进程；US-006 solve_params 原样含 solver_opts；US-011 band 参数 → _build_band 进程内同步跑 waist_band.build_band_plan（不 spawn 孙进程：terminate 不级联孙进程，同步调用随本进程 OS 级回收，stop 后无存活 python 子进程；失败=成带失败 error 只投 error 不投 manifest）+ _write_band_artifact（OUT_DIR/band_runs/*.json，写失败仅 warn）+ _emit_placed 展开单点（三处帧/final 发射共享：WB_ 组合片条目 expand_placements 展开回成员 placement，WB_ 永不跨进程））
        ├── export.py                  导出门面（2026-08-20 拆分后 47 行）：re-export 全部旧公共符号（placed_to_world/render_png/write_marker_dxf/write_marker_plt/size_aci/LAYER5_*/PLT 常量等 + size_color/SIZE_ANCHOR/centroid/PLOT_SAFE_MAX_Y_MM 旧模块属性），消费方 import 路径零改动；实现在 export_geometry/png/dxf/plt 四模块（2026-08-20 起颜色/图例/ACI 全尺码键：size_color 16 色循环（锚点 28 稳定绝对映射）+ size_aci=((size-28)%24)+1 + 图例=placed size 并集数值序）
        ├── export_dxf.py              R12-DXF marker 写出（自 export.py 拆出）：write_marker_dxf + _DXF_LAYER_*；模块级 ezdxf 警告抑制副作用原样保留；POLYLINE 写法（ET2008 兼容，绝不 LWPOLYLINE）+ ACI=size_aci(size) + TEXT 层 g 码叠印
        ├── export_geometry.py         导出共享层（自 export.py 拆出）：placed_to_world（placed → 世界坐标 5 层裁片）/apply_transform/size_aci + LAYER5_COLOR_*/NOTCH_LEN_MM 常量；依赖 sparrow_baseline（size_color/SIZE_ANCHOR）
        ├── export_plt.py              HPGL/PLT 文本导出（自 export.py 拆出）：write_marker_plt + 全部 PLT 常量与裁剪/分块算子；内容压进 Y≤1910 可写幅宽 + PD 分块 ≤10点/≤110B + 走纸引导；PLT 永不加文字
        └── export_png.py              matplotlib Agg 渲染（自 export.py 拆出）：render_png；模块级 Agg + CJK rcParams 副作用原样保留；填色 size_color + 尺码图例 + 每片 g 码叠印
    └── cli/                           配置驱动求解 CLI（PRD config-driven-solve-cli；最上层编排，绝不 import web.server，产物只落 out/config_runs/ 与 out/portfolio_calibration/）
        ├── calibration.py             PC-004 标定管线：python -m materialsorting.cli.calibration 四子命令 batch（base 短/全预算组逐 seed 串行 solve_pieces 跑批，commit_from_config 只跑一次，曲线/best 帧落 out/portfolio_calibration/<tag>/base/{short,full}/，manifest.json 逐 seed 落盘 Ctrl-C 安全重跑跳过）/ variants（确定性订单邻域变体生成器 seeded RNG：只抖 quantities 的 (g码,码∈sizes) 条目 n'=max(1,n±1)，工艺四字段逐字段固定，variant_{i}.json + 每变体曲线）/ analyze（聚合 base 曲线 → summary.json + controller_params.json（成功包络 S(τ) τ 网格 0.05~1.0 + kill 参数推荐，<10 达标 seed 拒绝 calibrated:false）+ generalization.json 泛化报告；train/test 误杀回测 + 短全秩相关）/ simulate（PC-005 ETT 离线仿真器：同总预算回放策略网格 → simulation_report.json + 推荐参数档，变体曲线 held-out；US-003 增策略双档 se180/race180 —— base/{short,full} 同 seed 配对回放 + E[max] 口径副表，判据复用 portfolio 单一真相源）
        ├── config.py                  US-001 load_config：7 键 JSON 配置严格校验（ConfigError(ValueError) 中文报错含字段名；seeds 非负整数列表取代旧 seed 三键；master_dxf 相对路径 CWD→仓库根两候选解析；quantities 码号键数字字符串或 'null'、数量 JSON 数字；per_type g 码键 + d/tol，超 MAX_OVERLAP_MM/MAX_ROTATION_TOL_DEG 上限 warn 钳制提示）→ NestRunConfig dataclass；模块级仅标准库（paths/constraints 走函数内延迟 import 保持单一真相源）
        ├── lns.py                      PC-007 LNS 波段重排核心（2026-08-20 拆分后 = 门面 + 编排层）：ms-lns --run-dir <dir> --time 30 --rounds 5 [--band-width mm]，对 result.json incumbent（回退 best/边车 best_frame_s{seed}.json）做波段级 ruin-and-recreate（① 按 x 切竖直波段缺省 1.5×NEST_GATE_MM ② 段局部密度=段内原面积和/(段宽×NEST_GATE_MM) 升序取最差段 ③ 段内裁片构造同口径子实例 build_instance 经 solve_with_callback_proc 多进程重解，pid 组整组归段禁拆分 ④ 新段跨度<原段−ε 接受：新段左缘对齐原足迹 m、完全位于 M 右侧的片左移 splice；否则拒绝幂等 ⑤ rounds/预算循环 + constraints.validate 全版复检 + y≤PLOT_SAFE_MAX_Y_MM 越界复检失败回退输入），跨组重叠护栏逐对不劣化（shapely 比原布局同对基线）；产物 result_lns.json + lns_compare.svg 落 run_dir；PC-008 postprocess_run_dir = 与 run_config --lns 共用的 run_dir 级编排入口；run_lns 主循环 + _solve_band（测试 monkeypatch 锚点，留守本模块）+ CLI 全套驻留，基元见 lns_bands/SVG 见 lns_svg（re-export 保旧 import 路径）
        ├── lns_bands.py                LNS 共享基元底层模块（2026-08-20 自 lns.py 拆出）：全部常量（ACCEPT_EPS_MM/Y_TOLERANCE_MM/GUARD_SLACK_MM2/MIN_SUB_TIME_SEC/DEFAULT_BAND_WIDTH）、LnsError、几何算子（_world_polygon/_layout_geometry）、波段切分（split_bands/band_solve_params）、跨组重叠护栏（_bbox_of/_pair_area/_cross_overlap_ok）、全版复检 recheck_layout；仅依赖 stdlib + nesting_bounds + nesting_engine.constraints
        ├── lns_svg.py                  lns_compare.svg 渲染（2026-08-20 自 lns.py 拆出）：_fmt + write_compare_svg 前后双面板（scale(1,-1) 翻转组 + 尺码图例 size_color）；依赖 lns_bands._world_polygon + sparrow_baseline.size_color
        ├── pipeline.py                US-002 commit_from_config(cfg, run_dir)：镜像 web/server._commit_to_nesting_sync 编排（collect → assign_codes → write_piece_dxf {label}_{size}.dxf + pieces_manifest.json → load_nest_pieces → intermediate 落 run_dir/pieces_intermediate.json），piece 条目与 web 逐字段一致（含 rounding 位数）、顶层省略 label_representatives、不写 .bak、gate_mm 写 cfg.gate_mm（配置驱动）；new_run_dir(run_name) 时间戳目录 <name>_<YYYYMMDD-HHMMSS>；只写 paths.CONFIG_RUNS_DIR 物理隔离 web 事实源。US-003/PC-001 solve_pieces(cfg, run_dir, *, seed, time_budget, on_progress, should_stop)：读 run_dir intermediate → 主进程 web.solver.build_instance 取 meta（demand_sum/total_area/n_items/n_eroded）→ **solve_with_callback_proc 多进程版**（子进程重建 instance 是固有秒级成本，换 terminate 能力）；逐帧落盘 curve_s{seed}.json（增量 append，无 placed_items）+ best_frame_s{seed}.json（最优帧完整布局，严格大于才覆盖写）；should_stop 每帧评估，真值 → terminate 子进程、以 best-so-far 帧交付（killed=True + kill_reason）；密度双口径由 proc 层 _apply_density_dual 换算（density=原面积口径 total_area/(width*gate)，density_sparrow=sparrow 自报）；正常路径校验 placed==Σdemand 不齐即 RuntimeError；US-006 加可选 solver_opts 原样并入 solve_params（JSON spawn 安全），非空时返回记录附带 solver_opts 回显（空档不加键，冒烟对拍零回归）；US-002 加 artifact_suffix='' 参数（se 延长轮传 '_ext' → curve_s{seed}_ext.json / best_frame_s{seed}_ext.json 与缺省名互不覆盖，缺省 '' 行为零回归）
        ├── portfolio.py               PC-002 串行 seed portfolio 控制器：PortfolioController 状态机（incumbent 全局最优帧 banking —— 每帧 density 严格大于即入账，记录 seed/frame_index/elapsed/width_mm/placed_items 完整布局，被 kill/中断 seed 的最优帧同样参与，修复旧 best 只看 per-seed 终值盲区）+ R0 达标即停（--target 给定时任一帧 density≥target → should_stop 返回 'R0_target_reached' + queue_stopped 终止剩余队列；触发帧先入账后停）+ R4 队列耗尽正常结束；make_progress(seed) 产 on_progress 回调（banking + 进度行：per-seed 新最优/心跳逐字保留旧格式、跨 seed 反超打 incumbent 行、echo=None 即 --quiet 全抑制）+ make_should_stop(seed) + finish_seed(rec)（per_seed 汇总 {seed,killed,kill_reason,best_density,elapsed}）；portfolio_section() 产 result.json portfolio 段（engaged=target 给定或 seeds≥2；不激活=单 seed 无 --target → 全空段 {target:null,incumbent:null,per_seed:[],theta_history:[]}）；best_record(solves) —— engaged 且有帧 → incumbent（帧级全局最优），否则旧语义 max(real_density)；run_serial_portfolio(cfg,run_dir,*,controller,time_budget,solve,on_seed_start,on_seed_done) 串行编排（solve 可注入 fake；Ctrl-C 捕获为 interrupted=True、求解异常上抛；should_stop 仅 target 给定时挂载 → 无旗标调用形与旧版一致）；load_controller_params(path) 校验 --params 文件（存在/合法 JSON 对象，ControllerParamsError；PC-002 只加载保存，阈值消费在 PC-003）；PC-009 run 统计库纯函数三件套：run_stats_class_key(source,sizes,quantities,per_type)=sha1(规范化JSON)[:10] 实例类指纹、load_run_stats(path) JSONL 容错读取（缺文件/坏行/非 dict 跳过）、calibrate_theta0(records,class_key,target)=min(target,历史最大 best_density+0.003)（命中且≥5 条才校准；只降 kill 门槛初值 theta0 kwarg，R0 恒用 target）；US-001 策略双模式判据纯函数族（R5_REASON/RACE_BUDGET_S/RACE_GATE_TAU/SE_SCREEN_S/SE_EXT_S/SEED_UNIT_S/FULL_UNIT_S 常量 + strategy_seed_stream 种子流无重复 + race_gate_seconds + decide_race_kill 门杀（严格破纪录才续跑/首 seed 豁免/bar 含被杀者/每 seed 至多一笔）+ se_plan 筛延规划（StrategyBudgetError 预算不足）—— --strategy race|se 的单一真相源，详见下表 portfolio.py 行）；US-002 控制器接线：mode='legacy'|'race'|'se' 构造参数（race 必给 total_budget）+ race_plan 名义规划 + _evaluate_race 门杀（R0 恒先/首 seed 豁免/决策行 theta=None S_tau=bar）+ can_start_next 预算收口 + round_budget 分段预算（se 筛/延两段）+ portfolio 段条件 mode/race/se 子段 + run_serial_portfolio 延长轮编排（冠军 _ext 重跑）
        └── run_config.py              US-003 ms-run-config 入口：argparse（config 位置参数 + --name 覆盖 run_name + --time N 覆盖时长 + --quiet + **PC-002 --target P**（(0,1] 比例，R0 达标即停，缺省不启用）+ **--params FILE**（controller 标定参数 JSON，坏文件退出 1））；run_dir=CONFIG_RUNS_DIR/<run_name 清洗>_<时间戳>（run_name 缺省配置 stem，Windows 非法字符→'_'）；逐 seeds 串行 **经 cli.portfolio 控制器** run_serial_portfolio 转发 solve_pieces（US-004：commit 仅一次复用产物；多 seed 启动打印预计总时长；轮次头在多 seed 或 --target 给定时打印）；进度行由控制器 echo 统一（原面积口径新最优 + 30s 心跳 + 跨 seed 反超 incumbent 行）；写 result.json（config 回显 + commit 摘要 + solve 指标数组 + **best** + **portfolio** 段）—— PC-001 起逐轮重写（Ctrl-C 不丢已完成轮）；**PC-002 best 语义**：engaged（--target 或 seeds≥2）→ best=portfolio.incumbent（帧级全局最优，placed_items=完整布局 list；真实数据验证帧峰 83.11%>两 seed 终值 83.07%/82.36%），单 seed 无 --target → 空 portfolio 段 + best=solve 记录（旧语义，无旗标冒烟对拍兼容）；_best_summary() 把两种 best 形态归一成汇总四元组（末行汇总格式不变）；R0 提前停打「[portfolio] R0 达标即停」终局行（--quiet 也打，退出码仍 0）；退出码 0 成功（含 R0）/1 配置或管线失败（含 --target 越界、--params 坏文件）/2 求解失败/130 Ctrl-C 中断；**PC-006 --solver-opts JSON / --rotate-opts**（互斥、坏 JSON 退出 1，配置错误在 new_run_dir 前拦下不留空目录；SOLVER_OPTS_POOL 4 档含空档 pool[队列序%4] 轮换；result.json config 段条件回显 solver_opts/rotate_opts）；**PC-009 run 统计库**：run 结束（exit 0 完成路径含 R0 提前停/kill；Ctrl-C/失败不沉淀）经 _append_run_stats 追加一行 JSONL 到 paths.RUN_STATS_JSONL（{ts,source,sizes,class_key,seeds,target,best_density,n_killed,elapsed_total,config{time,per_type,quantities}}；写盘 OSError 只 stderr warn 不阻塞）；--target 给定时启动读统计库 θ₀ 校准（calibrate_theta0 + load_run_stats + run_stats_class_key）→ 说明行 --quiet 也打 + PortfolioController(theta0=...) 只降 kill 门槛初值；US-002 --strategy [se|race]（裸旗标=race 缺省 B 方案）+ --time 总预算必填 + --race-budget/--race-gate/--se-screen/--se-extend 从属旗标（值域校验、与 --kill 显式互斥、race_plan/se_plan 预算不足退出 1）+ 种子流回显 + strategy.json 启动落盘 + 门杀行 --quiet 也打 + race 预算收口行 + digest（延长）标记 + 无旗标零回归
```

## paths.py — 路径常量（30 行）

所有数据/产物/前端目录的唯一来源。**禁止在代码里硬编码 `..` 上溯或绝对路径**，一律 `from .. import paths` 后用 `paths.XXX`。

| 常量 | 值（默认） | 环境变量 |
|------|-----------|---------|
| `DATA_DIR` | `<repo>/data` | `MS_DATA_DIR` |
| `OUT_DIR` | `<server>/out` | `MS_OUT_DIR` |
| `SPARROW_DIR` | `OUT_DIR/sparrow_baseline` | — |
| `INTERMEDIATE` | `SPARROW_DIR/pieces_intermediate.json` | — |
| `CONFIG_RUNS_DIR` | `OUT_DIR/config_runs`（US-002 起，CLI 专属产物根：cli 子包主要可写目录，禁写 INTERMEDIATE/uploads） | — |
| `CALIBRATION_DIR` | `OUT_DIR/portfolio_calibration`（PC-004 标定管线产物根：cli.calibration batch/variants/analyze/simulate 的曲线与分析（analysis/{summary,controller_params,generalization,simulation_report}.json），gitignore 区） | — |
| `RUN_STATS_JSONL` | `OUT_DIR/run_stats.jsonl`（PC-009 run 统计库：ms-run-config 完成 run 追加一行（class_key 按实例类聚合）、portfolio θ₀ 校准读取；append-only 单文件，gitignore 区） | — |
| `MASTER_DXF_GLOB` | `DATA_DIR/M1787*(2).dxf` | — |
| `STATIC_DIR` | `<repo>/materialSorting-web/static` | `MS_STATIC_DIR` |

## dxf_parser/ — 底层 DXF 读写

仅依赖标准库 + ezdxf，不依赖任何兄弟包。

### `reader.py`（101 行）— ezdxf 读底层

抗住母版 DXF 的 3 个怪癖：① `ezdxf.recover.readfile` 返回 `(doc, errors)` 元组需解包；② `$DWGCODEPAGE` 标 ANSI_1252 但块名实为 GBK；③ `$INSUNITS` 不可信（实测 6），统一按 mm 解释。

| 函数 | 签名 | 说明 |
|------|------|------|
| `decode_str` | `(s: str) → str` | GBK 解码块名/文本，失败回退原值 |
| `load_doc` | `(path: str)` | 读 DXF，优先 `ezdxf.recover.readfile`，回退 `readfile` |
| `parse_size` | `(block_name: str) → int \| None` | 从块名尾提取码号；失败 None |
| `strip_size` | `(block_name: str) → str` | 去码号 → "类型"部分（分组键） |
| `polyline_points` | `(entity) → list[(x,y)] \| None` | R12 POLYLINE 顶点；非 POLYLINE 返 None；不做抽稀 |
| `is_polyline_closed` | `(entity) → bool` | POLYLINE 闭合标志（优先属性，回退 `flags & 1`） |
| `iter_block_entities` | `(block, layers: set[str] \| None = None) → iterator` | US-002：按可选 layer 白名单迭代 block 内实体（不指定 layer 返全部）；供 US-003 深度解析统一提取入口 |

私有：`_SIZE_RE = re.compile(r"[._](\d+)$")` —— 只匹块名**尾**的 `.<数字>` 或 `_<数字>`，避免误匹 `M1787#28-32小33-38大码`。

### `geometry.py`（85 行）— 纯几何算子

操作 `list[(x,y)]` 多边形，**不依赖 ezdxf**，可独立单测。顶点原样保留。

| 函数 | 签名 | 说明 |
|------|------|------|
| `polygon_perimeter` | `(pts) → float` | 闭合周长（自动首尾相连） |
| `polygon_area` | `(pts) → float` | 鞋带公式面积，绝对值 mm² |
| `bbox_of` | `(pts) → (minx,miny,maxx,maxy)` | 外接框 |
| `point_in_polygon` | `(pt, poly) → bool` | 射线法点在多边形内 |
| `line_midpoint` | `(p1,p2) → (x,y)` | 线段中点 |
| `line_angle_deg` | `(p1,p2) → float` | 线段对水平角（度） |
| `match_grain` | `(grain_lines, polygons) → [line\|None]` | 每条布纹线配中点所在多边形；一对一，首中即取；返回与 `polygons` 平行 |

### `model.py`（39 行）— PieceOutline dataclass

解析期唯一 IR，一条 layer1 POLYLINE 对应一个。**刻意不携带 `piece_type`** —— 语义类型识别留给独立程序。

| 字段 | 类型 | 含义 |
|------|------|------|
| `source_file` | `str` | 母版文件名 |
| `block_name_raw` / `block_name` | `str` | 原始 / GBK 解码后块名 |
| `size` | `int\|None` | 块名尾码号，解析失败 None |
| `piece_index` | `int` | 该块内第几个 layer1（0 基） |
| `group_key` | `str` | `f"{group_base}#{idx}"` |
| `polygon_mm` | `list[(x,y)]` | layer1 轮廓顶点（mm，原样） |
| `is_closed` | `bool` | POLYLINE 闭合标志 |
| `vertex_count` | `int` | 顶点数 |
| `perimeter_mm` / `area_mm2` | `float` | 周长 / 鞋带面积 |
| `bbox_mm` | `(minx,miny,maxx,maxy)` | 外接框 |
| `grain_line` | `(x1,y1,x2,y2)\|None` | 匹配的布纹线 |
| `grain_angle_deg` | `float\|None` | 布纹线对水平角 |
| `grain_orientation` | `str` | `'horizontal'\|'vertical'\|'unknown'`（排料侧旋向依据） |
| `internal_lines` | `list`（默认 `[]`） | US-002：layer8 POLYLINE 内部线 `[[ (x,y), ...], ...]`，由 US-003 填充 |
| `notches` | `list`（默认 `[]`） | US-002：layer4 POINT 刀口 `[(x,y,nx,ny), ...]`（点 + 单位法向量），由 US-003 填充 |
| `net_polygon` | `list`（默认 `[]`） | US-002：layer14 POLYLINE 净版轮廓 `[(x,y), ...]`，由 US-003 填充 |

方法：`to_dict()` → `asdict(self)`（新字段自动序列化；既有调用方 `sparrow_baseline`/`explore.collect_pieces` 默认空 list 零改动可用）。

### `collect.py`（294 行）— US-003 母版深度解析

`collect_pieces_with_details(path)` 还原单片全部信息：复用 `explore.collect_pieces` 拿 layer1 毛版外轮廓 + layer7 布纹线（`match_grain`），二次扫描 layer14/layer8/layer4 实体后按几何归属到 outline。

**layer 映射集中在 `LAYER_MAPPING`** 常量（版师 2026-08-10 确认；5156 与 M1787 一致）：

| 语义 | layer | 实体 | 字段 |
|------|-------|------|------|
| 毛版 outline | `"1"` | POLYLINE | `polygon_mm` |
| 净版 net | `"14"` | POLYLINE | `net_polygon` `[(x,y),...]` |
| 内部线 internal | `"8"` | POLYLINE | `internal_lines` `[[(x,y),...], ...]` |
| 布纹线 grain | `"7"` | LINE | `grain_line` `(x1,y1,x2,y2)` |
| 刀口 notch | `"4"` | POINT | `notches` `[(x,y,nx,ny), ...]` |

> layer 2/3/13 不提取（参考点 / 轮廓密点 / 未定语义，**非刀口**）。

| 函数 | 签名 | 说明 |
|------|------|------|
| `collect_pieces_with_details` | `(path: str\|Path) → list[PieceOutline]` | 主流程：先调 `explore.collect_pieces` 拿 outline+grain，再二次扫描每 block 的 layer14/8/4，按质心/最近边几何归属到 outline |
| `_signed_area` | `(poly) → float` | Shoelace 带符号面积（>0 = CCW） |
| `_nearest_edge_with_normal` | `(pt, poly, signed_area) → (idx, dist, nx, ny)` | 找最近边 + 单位外法线（CCW 取 `(dy,-dx)/len`，CW 取反） |
| `_centroid` | `(pts) → (x, y)` | 顶点算术质心（net/internal POLYLINE 归属用） |
| `_assign_notch` | `(pt, outlines) → (pi, nx, ny)\|None` | Pass 1 严格 point-in-polygon；Pass 2 回退所有 outline 最近边 |
| `main()` | — | CLI 冒烟：`python -m materialsorting.dxf_parser.collect <dxf> [-v]` 打印每码片数 + internal/notch/net 计数 |

**归属策略**：
- layer14 净版：质心 `point_in_polygon` 命中即归属；1:1，每片最多 1 条（多条取首条）。
- layer8 内部线：质心命中归属；多线/片。
- layer4 刀口：先严格 `point_in_polygon`，全部 outline 都不包含则取最近边所属片（边界 / 外贴边点兜底）。

**实测分布（M1787 与 5156 一致）**：110 outline = 110 net = 110 grain（1:1:1）；286/297 internal、704 notch（545 严格 in-polygon + 159 边界点回退最近边）。

### `export_dxf.py`（143 行）— 单裁片 R12 DXF 导出（5 层，US-024）

每个裁片导出为 `<类型>_<码号>.dxf`：layer 1 = 毛版轮廓（闭合 POLYLINE），layer 14 = 净版（闭合 POLYLINE），layer 8 = 内部线（多条 POLYLINE），layer 4 = 刺口（POINT 位置，法线不存盘），layer 7 = 布纹线（LINE）。Richway/ET 兼容。

- **import 时副作用**：`logging.getLogger("ezdxf").setLevel(ERROR)` —— 静默 R12 `$INSUNITS` warning（R12 规范不导出单位变量，单位 mm 隐式）。
- （US-001 v2 已删）`GROUP_NAMES` / `assign_group_no` —— 名称识别整体退场；本模块仅剩 `write_piece_dxf`（文件名 `{label}_{size}.dxf`，g 码由调用方 `labeling.assign_codes` 决定）。
- `write_piece_dxf(piece, out_path)` —— 写单裁片 5 层 DXF。US-024：若 PieceOutline 携带 `net_polygon` / `internal_lines` / `notches`（来自 `collect_pieces_with_details`），同时写 layer14/8/4；notch 仅存 POINT 位置，法线 (nx, ny) 丢弃（读时由 `load_pieces._read_piece_full` 按 outline 最近边重算）。库函数，由 `web/server._commit_to_nesting_sync` 调用切单裁片到 `out/uploads/<doc_id>_pieces/`（原 `ms-export-dxf` CLI 已移除）。

### `explore.py`（335 行）— 母版全裁片探索

遍历每个 block，提取每条 layer1 闭合 POLYLINE 为一个 `PieceOutline`，按 `group_key` 分组，产出分组目录（SVG + JSON）+ 全量 CSV + 总览 SVG。

| 函数 | 签名 | 说明 |
|------|------|------|
| `collect_pieces` | `(path) → list[PieceOutline]` | 核心抽取：跳匿名块（`*`）、滤 layer `"1"` 的 POLYLINE（≥3 点）、配 layer `"7"` 布纹线、算周长/面积/bbox/布纹朝向 |
| `sanitize` | `(s) → str` | 块名 → 合法目录名片段 |
| `group_label` | `(group_base) → str` | 主块 → `"main"`；否则去 `noname.` 前缀 + `sanitize` |
| `group_sort_key` | `(members)` | 主块组优先；再按块名 + piece_index |
| `piece_svg` | `(p, w=520, h=680) → str` | 单片 SVG（翻转 y，虚线红布纹线） |
| `overview_svg` | `(pieces, w=1700, h=1200, pad=50) → str` | 总览 SVG + 分组色例 |
| `write_outputs` | `(pieces, outdir) → [(group_no,label,sample,n)]` | 分组目录 + `pieces.json` + `_all_pieces.csv` + `_overview.svg` |
| `write_csv` | `(path, rows)` | UTF-8-BOM CSV，17 列 |
| `resolve_dxf` | `(arg) → Path\|None` | 路径/glob → 首个存在匹配 |
| `main()` | — | CLI，默认 `--dxf paths.MASTER_DXF_GLOB`，`--out paths.SPARROW_DIR` |

私有：`_flip`、`_color_for`（基于 md5 的稳定 HSL 色，抗 `PYTHONHASHSEED`）。

## nesting_bounds/ — 裁片加载

### `load_pieces.py`（312 行）— 单裁片 → NestPiece（5 层透传，US-024）

读 `pieces_manifest.json`（US-001 v2 manifest 驱动，`[{file,label,size}]`；无 sidecar 明确报错「请重新 commit」）→ 逐文件读单裁片 DXF → 布纹对齐到水平 → 归一化到原点（**无镜像展开**：镜像/`side` 概念已删，每文件恰一条 NestPiece，`pid=f'{label}_{size}'`）。布纹仅用于读取期水平对齐，之后无旋转约束。`_read_piece` 读 5 层（layer1+layer14+layer8+layer4+layer7），notch 法线按 outline 最近边重算（与 `collect._nearest_edge_with_normal` 同算法）；5 层经 `_apply_layer_transforms` 与 polygon 共享 rotate→normalize transform 链。

**模块级常量：**

| 常量 | 值 |
|------|-----|
| `GATE_MM` | `1980.0`（门幅：布幅**显示**口径 —— UI viewBox / PNG·DXF·PLT 外框，不减布边） |
| `PLOT_SAFE_MAX_Y_MM` | `1910.0`（绘图仪 Y 可写幅宽，LIKE + WT「高速网口输出中心 V8.8」现场口径；2026-08 撞机根因 = 旧导出门幅框画到 1980、顶部刺口伸 1983.9mm，Y 超程小车撞导轨硬限位） |
| `NEST_GATE_MM` | `min(GATE_MM, PLOT_SAFE_MAX_Y_MM)`（**求解约束带** strip 高度上限 + **密度分母**实际幅宽口径（2026-08-20 起，单一换算点 `web.solver._apply_density_dual`）；web/solver 与 CLI 引擎同源引用；换机器/换布幅只改上面两个常量，此处自动跟随） |
| （US-001 v2 已删）`PAIR_TYPES` / `ALL_TYPES` —— 镜像展开与片型集合退场 |
| `ALL_TYPES` | `['前片','后片','腰','前袋','后袋','机头','单排','双排','火机袋','裤耳']`（10 类规范序） |
| `DEFAULT_SIZES` | `[28,29,30,31,33,34,35,36]`（8 码，**跳 32**） |

**`NestPiece` dataclass（US-001 v2 label 主键 + US-024 扩 5 层字段；无 ptype/side）：**

| 字段 | 类型 | 含义 |
|------|------|------|
| `pid` | `str` | 唯一 ID = `f'{label}_{size}'`，如 `'g03_28'` |
| `label` | `str` | 裁片 g 码（全链路主键） |
| `size` | `int` | 码号 |
| `polygon` | `list[(x,y)]` | 毛版顶点，bbox 左下归一到原点 |
| `bbox` | `(minx,miny,maxx,maxy)` | 外接框 |
| `area_mm2` | `float` | 多边形面积 |
| `source` | `str` | 源 DXF 文件名 |
| `net_polygon` | `list[(x,y)]`（默认 `[]`） | US-024 净版（layer14） |
| `internal_lines` | `list[list[(x,y)]]`（默认 `[]`） | US-024 内部线（layer8） |
| `notches` | `list[(x,y,nx,ny)]`（默认 `[]`） | US-024 刺口（layer4；法线按 outline 最近边重算） |
| `grain_line` | `(x1,y1,x2,y2) \| None`（默认 `None`） | US-024 布纹线（layer7） |

属性：`width = bbox[2]-bbox[0]`，`height = bbox[3]-bbox[1]`。

私有：`_rotate`（绕原点旋）、`_normalize`（bbox 左下平移到原点）、`_read_piece`（读全 5 层 → `(polygon, grain_deg, net, internal, notches, grain_line)`）、`_align_grain_horizontal`（竖布纹 ±90° → 水平；水平不变）、`_rotate_normal(nx, ny, deg)`（US-024 法线随片旋转）、`_grain_rotation_deg(grain_deg)`（US-024 把 grain_deg 映到 transform 旋角，与 `_align_grain_horizontal` 同语义）、`_apply_layer_transforms(...)`（把 5 层原始数据按 rotate→normalize 链统一变换，US-001 v2 起 **mirror 参数已删**；**notch 点必须随片旋转**——旧实现只转法线不转点，竖直布纹片 rot=±90 时刺口飞出轮廓 3m+（腰/后袋），PLT 导出 600 越界点、PNG/DXF 同源污染，已修复并有 `tests/test_load_pieces_notches.py` 回归）。（US-001 v2 已删：`_mirror_x` / `_read_piece_full` 旧别名 / 镜像分支。）

入口：`load_nest_pieces(data_dir) → list[NestPiece]`（US-001 v2：读 `pieces_manifest.json` 驱动，每条目恰一片；无 sidecar / 旧版目录 → RuntimeError「请重新 commit」）。

## nesting_engine/ — sparrow 求解 + v0.3 约束

### `constraints.py` — v0.3 约束层

重合/旋转**全局**上限（2026-08-17 起，不再按片型钳制）、求解后 `validate`（数量 / 门幅 / 用料长）。版师确认的每片型工艺上限（外片 0.4–2mm / 前袋旋转 30° 等）保留在 `business/排料规则_详细版.md` §3.2/§4 作参考，由用户在高级配置弹窗按片型显式填值控制，默认 0。

**模块级常量：**

```
MAX_OVERLAP_MM       = 10.0   # 全局最大重合深度（mm；UI 高级配置重合输入 max 同值）
MAX_ROTATION_TOL_DEG = 45.0   # 全局最大旋转公差（°，绕 {0°,180°}；旋转输入 max 同值）
# US-001 v2 已删：GROUP_NAMES / PAIR_TYPES / ALL_TYPES（名称识别与镜像展开退场）
# US-002 已删：PAIR_TYPES + 成对齐套校验（L 数=R 数，服务于已删除的合成镜像模型）
```

> 旧 `MAX_OVERLAP`/`ROTATION_TOL` 每片型字典 + `overlap_dpix` 已删（`web/solver.build_instance` 的钳制改 `min(申请值, 全局上限)`）。

| 函数 | 签名 | 说明 |
|------|------|------|
| `erode_bitmap` | `(bm, d_pix) → bm` | 4 邻域形态学腐蚀 `d_pix` 次；`d_pix<=0` 原样返回 |
| `discretize_orientations` | `(tol) → list[float]` | 旋转公差 → spyrrow 离散角度集（tol=0 → [0,180]；tol>0 → 0°/180° 附近 ±tol 自适应步进 1°/5°，归一 [0,360)）。**2026-08-21（US-009）自 `web/solver.py` 移入**（旋转公差离散属约束层职责；`nesting_engine/waist_band` 同口径消费但分层禁 import web）；`web/solver.py` re-export 保旧 import 路径零改动 |
| `validate` | `(placed_world, pieces, used, gate, res) → (ok, issues)` | 校验数量、x∈[0,gate]、used>0（US-002 起不再读 ptype/side —— 成对齐套校验已删） |

### `sparrow_baseline.py` — 基线 + ★共享层

Stage 2 §6：把 intermediate 全片喂给 spyrrow（无服装约束的纯几何）求几何上界。产出 `result_*.json` / `*.svg` / `*_curve.json` / `*_curve.png`。**同时是共享层**：`size_color` / `_clean_polygon` / `_write_svg` / `_plot_curve` / `solve_with_progress` 被 experiments/export/solver 复用。

**模块级常量（US-002 起 g 码配色单一真相源）：**

```
SIZE_PALETTE = ('#1f77b4','#ff7f0e','#2ca02c','#d62728','#9467bd','#8c564b','#e377c2',
                 '#7f7f7f','#bcbd22','#17becf','#aec7e8','#ffbb78','#98df8a','#ff9896',
                 '#c5b0d5','#c49c94')   # 16 色 d3 系循环表（tableau10 + 6 pastel）
DEFAULT_COLOR = '#bbbbbb'               # None / 非数字兜底
SIZE_ANCHOR = DEFAULT_SIZES[0]          # = 28；稳定绝对映射（28 恒表头色，子集 run 不漂移）
# size_color(size) = SIZE_PALETTE[(size - SIZE_ANCHOR) % 16]；同码同色跨片型，44 循环回表头。
# 2026-08-20 由 g 码键 label_color 换键为尺码；solver manifest / PNG / DXF ACI / CLI SVG 四处同源取色。
```

| 函数 | 签名 | 说明 |
|------|------|------|
| `solve_with_progress` | `(instance, config) → (sol, curve, elapsed_sec)` | daemon 线程跑 `instance.solve(config, progress=ProgressQueue)`，主线程 drain 收 anytime 曲线；curve 项 `{elapsed,phase,report,density,width_mm}`；30s 心跳 log。**被 baseline + experiments 共用** |
| `main()` | — | CLI：`--sizes`/`--time`(600)/`--seed`/`--no-svg`/`--no-curve`；读 `INTERMEDIATE`，构 `spyrrow.Item(allowed_orientations=[0,180])` + `StripPackingInstance(strip_height=min(gate, PLOT_SAFE_MAX_Y_MM))`（与 web/solver 同口径钳绘图仪可写幅宽；密度/理论用布仍按 gate）+ `StripPackingConfig(time,seed,num_workers=4)` |

私有：`_clean_polygon(poly,eps=0.01)`（去连续重复点 + 闭合重复点；spyrrow 自身也去重，此为多一层保险，**不**处理非连续重复/自交）、`_transform_polygon`（绕原点旋 + 平移，与 `PlacedItem` 语义一致）、`_fmt`、`_write_svg`（viewBox = used×gate mm，`<g transform="translate(0,H) scale(1,-1)">` 翻 y）、`_plot_curve`（matplotlib anytime 收敛图 + 阶段着色 + best-so-far 包络 + 90% 参考线；无 matplotlib 优雅降级）。

> `num_workers=4`：spyrrow 0.9.0 修了 `num_wokers` 拼写错；**>4 反而质量更差（issue #113）**。

### `sparrow_experiments.py` — 旋转/重合公差实验

实验 ②③ 量化旋转公差与重合公差上界。基线 = 实验 ① 600s `{0,180}` 无 erode = **85.79%**（`result_{tag}_t600.json`）。spyrrow 参考数：TROUSERS 92.6% / SHIRTS 90.9%（arxiv 2509.13329）。

**复用共享层：** `from .sparrow_baseline import _clean_polygon, _write_svg, _plot_curve, solve_with_progress`

**模块级常量：** `STEM_ALL = '28_29_30_31_33_34_35_36'`、`OUT = paths.SPARROW_DIR`、`INTERMEDIATE = paths.INTERMEDIATE`（US-002 起 `INTERNAL_TYPES` 已删 —— intermediate 无片型字段，内片 g 码集合改 `--internal g04,g07` 命令行参数显式给出）。

| 函数 | 签名 | 说明 |
|------|------|------|
| `erode_polygon` | `(poly, d) → poly` | shapely 向内 buffer `d` mm → 外环坐标；失败/空回退原 poly；Multi 取最大 |
| `build_pieces` | `(doc, exp, erode_d, internal_labels=frozenset()) → (items_meta, total_orig_area, n_internal_eroded)` | 4 模式：`free_rot`（全自由旋）/`v0_rot`（内片自由 + 外片 `{0,180}`）/`erode`（仅内片 erode，朝向仍 `{0,180}`）/`erode_rot`（内片 erode+自由旋，外片 `{0,180}`）；内片判定 = `p.get('label') in internal_labels`，items_meta 条目含 `label` 键（无 ptype） |
| `run_one` | `(doc, gate, exp, erode_d, time_budget, seed, internal_labels=frozenset())` | 跑一次；`strip_height=min(gate, PLOT_SAFE_MAX_Y_MM)`（与 web/solver 同口径；密度仍按 gate）；同时报 `real_density`（原面积分母）+ `sparrow_density`（erode 后自报）；写 `result_{stem}.json`/`{stem}_curve.json`/`{stem}.svg`/`{stem}_curve.png`，stem = `exp_{tag}_t{T}_s{seed}` |
| `main()` | — | CLI：`--exp {free_rot\|v0_rot\|erode\|erode_rot\|all}`(默认 all)/`--d`(5)/`--time`(600)/`--seed`(0)/`--internal`(csv g 码集合)/`--seeds`(csv→多种子方差汇总)；写 `experiments_summary_t{T}.json`（含 `internal_labels`）或 `multiseed_{exp}_d{d}_t{T}.json` |

### `labeling.py` — g01+ 编号单一真相源（US-001 v2 label 先行）

parse-dxf 响应（`web/server.py._build_parse_payload`）与 intermediate（`web/server.py._commit_to_nesting_sync`）的**单一真相源** —— 保证两条管线对同一母版产出的 label 按 `(block_name, size, piece_index)` 逐片同码（AC#5；否则 qtyStore 按 label 编辑的数量会配错裁片）。

| 函数 | 说明 |
|------|------|
| `label_for(idx)` | 0→g01, 1→g02, ..., 98→g99（g + 两位零填充，字典序=数值序） |
| `code_sort_key(code)` | g 码 → 数值序键（'g02'→2；非 g 码兜底 0）；labeling 赋码/排序用（颜色图例 2026-08-20 起改尺码数值序，不再消费此键） |
| `master_code_from_block_name(name)` | 母版 block 名显式编号尾缀（`前片g03.30`/`腰G3`/`袋#7`）→ 规范化 `gNN`；纯数字尾缀不识别 |
| `centroid(poly)` | 顶点算术质心（稳定排序键 + 导出 g 码叠印定位共用） |
| `size_sort_key(size)` | 码号排序：None 殿后，其余升序 |
| `parse_member_sort_key(p)` | **码内稳定排序键单一真相源** `(-centroid_y, centroid_x, -area_mm2, block_name, piece_index)`（2026-08-17 收敛；parse 赋号 / label 对齐 / label 代表裁片三处共用，改一处自动三处同步） |
| `sequential_sort_key(p)` | US-001 v2（替代已删 `compute_size_ptype_labels`）：`assign_codes` 顺序赋码排序键 `(group_key,) + parse_member_sort_key(p)` —— T4 group_key 前置保证同一 block 模板跨码同号 |
| `collect_master_codes(pieces)` / `assign_codes(pieces)` | 母版编号 all-or-nothing 收集 / 每码排序 + g 码分配（顺序模式 + 母版复用模式），详见 `nesting_engine/AGENTS.md` |

### `waist_band.py` — US-009 腰头成带核心（带内聚排 + 组合片 + 展开）

依据 `business/腰头成带_落地方案.md` §2（2026-08-21 定稿）。腰头 g 码裁片先在全幅 `NEST_GATE_MM` 带内独立小求解聚排（size-major 保同码相邻）→ 成员**原始轮廓**@带内位 `unary_union` → closing 焊接连通（恒 ⊇ 原 union）→ `erode(d_g)` → `_clean_polygon` → 平移归一化（记录 offset），整带单组合片（`WB_*` pid）投主解；帧发射前 `expand_placements` 展开回成员 placement。**禁 import web**（单一真相源，web US-011 接线 / 未来 CLI 共用；AST 守卫在 `tests/test_waist_band.py`）。

**模块级常量：** `COMPOSITE_PID_PREFIX='WB_'`（泄漏哨兵）/ `COMPOSITE_ORIENTATIONS=(0.,180.)`（FR-8 成带后整块不再旋转，不带 tol 抖动）/ `MAX_COMPOSITE_VERTICES=600` + `SIMPLIFY_TOLERANCE_MM=0.05` / `DEFAULT_BAND_TIME_BUDGET_S=15` / `FILL_FLOOR_PCT=45.0`（低于即 fail-fast，禁止无声兜底）/ `BAND_NUM_WORKERS=1`（**确定性**：实测同 seed num_workers=1 与 =4 结果不同）/ `WELD_RADIUS_MM=1.0` + `WELD_RADIUS_MAX_MM=512.0`。

| 函数 / 类 | 签名 | 说明 |
|------|------|------|
| `build_band_plan` | `(pid_meta, pieces_by_id, *, label, seed, gate_nest=NEST_GATE_MM, d_g=0.4, tol_g=3.0, time_budget=15, fill_floor=45.0) → BandChunk` | 成员 = pid_meta 中该 label 且 demand>0 全部副本（Item 用已腐蚀 polygon 不二次腐蚀、orientations=`discretize_orientations(tol_g)`）；0 副本 ValueError、总副本 1 `DegenerateBand`、守恒失败/解散落/低 fill `BandQualityError`；union 用 **pieces_by_id 原始轮廓**（union bbox minx/miny = offset，减号进展开式）；真实 DXF 自交轮廓经 `buffer(0)` 修复（`_valid_geometry`，实测 M1787 g05 必需） |
| `expand_placements` | `(chunk, rotation, translation) → list[{id,rotation,translation}]` | **展开权威式**（黄金单测锁死）：`rot_f = m.rot + c.rot`；`tr_f = R(c.rot)·(m.tr − offset) + c.tr`（offset **减号**）；输出 shape 与 `solve_worker._emit_placed` 对齐（US-011 单点替换 WB_ 条目）；Σ 条数 == Σ demand |
| `BandChunk` | dataclass | `pid/label/polygon(归一化 erode 后)/offset/members(逐副本带内位 size-major 序)/fill_pct/bbox/seed/d_g/tol_g` + `to_dict()`（纯几何 JSON，同 seed 两跑 `json.dumps` 相等 —— 不含 wall-clock） |
| `band_seed_for` | `(seed, label) → int` | `zlib.crc32(f'{seed}\|{label}')` 派生（勿用 `hash()` —— PYTHONHASHSEED 随机化不可跨进程重放） |
| `DegenerateBand` / `BandQualityError` | `BandError` 子类 | 退化（总副本 1 / 轮廓 <3 顶点）/ 质量不达标（fill 低 / 守恒失败 / 散落不成块） |

### `waist_band_gate.py` — US-010 go/no-go 试点闸门（三组决策实验 CLI）

UI/协议开发（US-011+）前的决策实验编排，复用 `waist_band` 模块、**不改产品代码**。入口 `python -m materialsorting.nesting_engine.waist_band_gate [--quick]`（`--quick` = 秒级冒烟档，只验证管线）。**分层禁 import web/cli**（AST 守卫在 `tests/test_waist_band_gate.py`）：`build_probe_pid_meta(pieces, *, sizes, per_type, quantities)` 是 `web.solver.build_pid_meta` 的探针同构镜像（两 arm 共享同一镜像 = 同源同构，不跨口径对拍生产 0.9063 基线）；`main_items(pid_meta, *, exclude_label, composite)` 是 `build_instance` 的探针镜像（exclude_label 模拟 US-011 exclude_labels 语义）。**只读** `paths.INTERMEDIATE`（非 5336 母版 fail-fast），产物只落 `out/config_runs/_probes/band_gate_report.json`。

| 函数 | 判据 |
|------|------|
| `run_density_ab` | 实验①：5336 P0 同配置（120s、per_type 全表、sizes 31~38、`_prod_quantities()` 同 probe_base.json）band off vs on × seed {0,1,2}，逐 seed `real_density`（`_real_density_pct` = total_area/(width×min(gate,1910))，与 P0 87.45% 同口径）；接受线 = on 的 seed 均值劣化 ≤`DENSITY_ACCEPT_PT`=1.0pt |
| `run_nfp_bench` | 实验②：主实例（band 成员移出基实例）± comb 组合片（真实 build_band_plan 产物，实测 ~700 顶点 > 预估 500）同预算（60s）帧率对跑（`solve_collect` 帧采集）；吞吐劣化 >`NFP_DEGRADE_ACCEPT_PCT`=30% 判不过；收敛曲线降采样（`_downsample` ≤200 点）随报告落盘 |
| `run_fill_curve` + `fill_saturation` | 实验③：band 预算 {5,10,15,30,60}s 扫描 fill_pct；饱和点 = 距序列最大 fill ≤`FILL_SATURATION_PT`=0.5pt 的最小预算（最大 fill 恰在最大预算处 → 未饱和注记） |
| `decide(density_pass, nfp_pass)` | 结论三选一：`go`（双过）/ `go-with-chunks`（仅 NFP 挂 → US-011 pair-atomic 分块）/ `no-go`（密度硬闸门挂 → 转 US-015 v1.1 混填料路线，纯腰 v1 不合入） |

**2026-08-21 实测结论 `no-go`**（报告在案）：① A/B 均值劣化 **1.204pt FAIL**（seed0 +0.19 / seed1 −0.08 / seed2 **+3.49** —— off 臂 seed2 波动到 90.04% 拖垮均值，seed 方差 ≳ 组间差）；② NFP 吞吐劣化 **35.0% FAIL**（27.8 → 18.1 帧/s）；③ fill 曲线 51.8/51.5/**61.1**/54.5/54.8 无稳定平台（15s 局部最优即饱和点，与初值 15s 恰合）。

## web/ — FastAPI + WebSocket 工作台

详见 [agent-api-reference.md](agent-api-reference.md)。此处仅文件级速查：

| 文件 | 行 | 职责 |
|------|----|------|
| `server.py` | 783 | FastAPI app；**启动期 `_reload_pieces_state()`**（US-020 替代旧顶层 `load_pieces()`，allow-empty 不再让 import 崩）；路由 GET `/`、mount `/static`、POST `/export`（文件名前缀取 payload `filename` 上传母版名去 .dxf，缺省回退「排料」/nesting）、POST `/api/parse-dxf`（US-004 上传解析；**US-001 v2 起响应仅 `label` + 5 层字段，`name`/`ptype`/`paired` 删除** —— `_build_parse_payload` 入口先跑 `labeling.assign_codes(pieces)`（无名称参数）g 码先行）、POST `/api/commit-to-nesting`（US-010 + US-020 commit 后 reload `_PIECES_STATE` + US-022 intermediate 加 label；**US-004：intermediate doc dict 首键 `doc_id`**，旧档缺它 → /api/strategy/start 422）、GET `/api/ptypes`（US-020 裁片代表 D10/D11；**US-001 v2 键 = g 码 label**，`_LABEL_REPRESENTATIVE_FIELDS` 白名单，优先 intermediate `label_representatives`）、WS `/ws/solve`（accept 阶段 `_get_pieces_state()` 快照 + US-022 quantities 入参；**US-026 进程化**：`solve_with_callback_proc` 替代旧 threading 桥，write loop 内联 drain queue + read loop 后台 task 收 `{action:'stop'}` → terminate process → 发 `{type:'stopped'}` → 关闭 WS；客户端断开 → terminate+join 防孤儿）；**文件尾 `from .strategy import register_strategy_routes` + `register_strategy_routes(app)`**（US-004 四策略路由，文件尾防循环导入）；`_terminate_solve_process(state_box)` 幂等 terminate+join+kill 兜底；`_state_lock=threading.Lock()` 保护 immutable snapshot；`ThreadPoolExecutor(max_workers=6)` 跑 `run_solve`（US-004 解析 / US-010 commit 也复用此池）；上传常量 `UPLOAD_MAX_BYTES=20MB` / `UPLOADS_DIR=paths.OUT_DIR/uploads` / `_DOC_ID_RE`；`_build_parse_payload` 按码分组 + `assign_codes` g01+ 赋号（T4 group_key 前置排序）；`_commit_to_nesting_sync` Path A 全管线（assign_codes 最先 → `{label}_{size}.dxf` + `pieces_manifest.json` → manifest 驱动加载 → intermediate v2 + `label_representatives`）；`_LABEL_REPRESENTATIVE_FIELDS` 透传白名单。**2026-08-20 拆分**（600 行硬限制，783→329）：state 快照/共享线程池搬 `runtime.py`、parse 响应构造搬 `parse_payload.py`、WS solve 端点搬 `routes_ws.py`、`/`·`/api/ptypes`·`/export` 搬 `routes_views.py`（APIRouter，server.py include）；**`_commit_to_nesting_sync` + 两个上传路由留守 server.py**（9 个测试文件 `monkeypatch.setattr(server_mod, 'UPLOADS_DIR')` 后直调，其 `__globals__` 必须是 server 命名空间）；拆出符号在 server 命名空间全部 re-export（`_PIECES_STATE` 同一 dict 对象原位 clear+update），路由注册顺序与拆分前逐条一致，OpenAPI paths 对拍一致 |
| `runtime.py` | 75 | 共享运行时单例（2026-08-20 自 server.py 拆出）：`_PIECES_STATE` 快照机制（`_state_lock`/`_build_pieces_state`/`_reload_pieces_state`/`_get_pieces_state`）+ 启动期 reload try/except + 共享 `_executor`（ThreadPoolExecutor 6 workers）；**import 即触发模块级副作用，且在 server.py 创建 app 之前**（与拆分前顺序一致） |
| `parse_payload.py` | 105 | 纯函数（2026-08-20 自 server.py 拆出）：`_size_sort_key` / `_build_parse_payload`（parse-dxf 响应体）/ `_build_label_representatives`（g 码 RAW 代表裁片） |
| `routes_views.py` | 130 | APIRouter（2026-08-20 自 server.py 拆出）：`GET /`、`GET /api/ptypes`（含 `_LABEL_REPRESENTATIVE_FIELDS`）、`POST /export`（PNG/DXF/PLT，经 `.export` 门面）；从 runtime 取共享 state |
| `routes_ws.py` | 251 | APIRouter（2026-08-20 自 server.py 拆出）：`/ws/solve` WS 端点 + `_terminate_solve_process` + `_SENTINEL`；从 runtime 取共享 executor/state |
| `solver.py` | 579 | `load_pieces` / `discretize_orientations`（**US-009 起真相源在 `nesting_engine/constraints.py`，此处 re-export 保旧 import 路径**）/ `build_instance`（**erode=min(申, MAX_OVERLAP_MM=10)，tol=min(申, MAX_ROTATION_TOL_DEG=45)，2026-08-17 起全局上限不再按片型**；US-022 quantities→demand，0 跳过；**US-002**：`per_type[label][sizeKey]` 命中即覆盖 d/tol（未命中/旧 ptype 键 no-op）、internal 概念删（`d_int`/`tol_int` 无消费方）、pid_meta 无 ptype 键且 `color=size_color(size)`（2026-08-20 尺码键，同码同色跨片型）；**strip_height=min(gate_mm, PLOT_SAFE_MAX_Y_MM)** —— gate_mm 是显示口径，求解约束带钳绘图仪可写幅宽 1910，密度/导出/前端仍用 gate_mm 原值；US-024 pid_meta 加 5 层字段 `.get()` 向后兼容；**US-004**：片级管线抽纯函数 `build_pid_meta(pieces, *, sizes, per_type, quantities, params) → (pid_meta, total_area, n)`（demand→per_type 覆盖→erode/clean→pid_meta，**不 import sparrow**，/api/strategy/result 建 manifest 复用）+ 共享 `_resolve_d_tol(label, pdef, per_type)` 单一真相源（pid_meta 蚀边与 Item orientations 同 tol）；build_instance 改调它后按 sizes 过滤循环建 Item）/ `solve_with_callback`（**旧** threading 版，保留不删）/ `solve_with_callback_proc`（**US-025** multiprocessing 版 + **US-026 `on_process` 回调**：子进程 `start()` 后回调一次交出 `Process` 句柄供 WS stop/断开 terminate；density 双口径换算在主进程做；terminate 后 `cancel_join_thread + 限时 drain(≤50ms) + join(timeout=5)` 防死锁）+ `_apply_density_dual` 私有换算helper |
| `strategy.py` | 689 | US-004 **新增**。策略桥接四路由 `register_strategy_routes(app)`：**POST /api/strategy/start**（409 单例 —— 内存态非终态或孤儿 marker 在 → 先于一切校验；422 状态 —— pieces 空/commit doc 缺 doc_id/母版 DXF 文件不在；400 参数 —— mode∈{se,race}/minutes∈{10,20,30,60}；7 键配置（master_dxf/sizes/quantities/per_type/gate_mm/seed/time）可选键 truthy 才落，写 `out/uploads/strategy_cfg_<stamp>.json`；**快照先于 spawn** 防竞态 → spawn `[sys.executable, -m, materialsorting.cli.run_config, cfg, --name, web_{mode}_{rand6}, --strategy, mode, --time, ...]` stdout=DEVNULL stderr=临时文件 → marker `.web_strategy_active.json`（pid/run_dir/doc_id/mode/started_at）落 out/config_runs/ → 202）；**GET /api/strategy/status**（无状态惰性轮询：poll proc → run_dir 快照差分发现（写回 marker + st）→ starting→running→done/stopped/error 状态机 + **state 回写 st**（终态后可再 start）；孤儿分支 = 内存空但 marker 在 → pid 存活探活 + ISO elapsed；来源白名单 strategy.json/result.json/best_frame_s*.json/kill_decisions.jsonl，**curve_s{seed}.json 不读**（中途非法 JSON）；run_dir 静默 30s 后 error + stderr 尾巴 2000 字符；终态清 marker）；**POST /api/strategy/stop**（树杀：Windows `taskkill /PID <pid> /T /F`、POSIX `os.killpg`（spawn start_new_session）；孤儿清理分支；内存空 → 400）；**GET /api/strategy/result**（done/stopped 才 200，running→409/idle→404；best = incumbent 有则用否则 best_frame_s*.json max 回退；density_sparrow 补 best_frame 副车；manifest 用 start 时快照 pieces 走 `build_pid_meta` 与 /ws/solve 同形；doc_id 漂移 warning）。`_pieces_state()` 惰性 `from .server import _get_pieces_state` 防循环导入（server 只文件尾 import strategy） |
| `solve_worker.py` | 143 | US-025 **新增**。顶层 `solve_worker(pieces_snapshot, gate_mm, solve_params, result_queue)` —— Windows spawn 可 pickle（无闭包、参数全 JSON）。子进程内 `build_instance(...) → 投 {kind:manifest}` → `instance.solve(config, progress=ProgressQueue)` → drain 出中间解投 `{kind:frame,report}` → 末尾投 `{kind:final,final}` 或 `{kind:error,message}`。所有投递纯 JSON，spyrrow 对象绝不跨进程。US-006：solve_params 原样多带 solver_opts 键（**solve_params 直通 build_instance**，worker 不解释旋钮）。延迟 import build_instance 避免主进程 `from solve_worker import` 时强制拉 sparrow_baseline |
| `export.py` | 614 | `apply_transform` / `placed_to_world`（用**原始**非 eroded 轮廓，pid 直查 intermediate 零重放；US-024 起 5 层一并变换，notch 点按点变换 + 法线按向量旋转；**US-002**：输出无 ptype 键、`color=size_color(size)`（2026-08-20 尺码键）、`size_aci()` 取 ACI）/ `render_png`（matplotlib Agg；US-024 起 5 层叠加：net 绿虚线 / internal 橙 / notch 黄短线段 / grain 红虚线；图例条目 = placed 的尺码并集数值序，标题「尺码」，零中文名）/ `write_marker_dxf`（R12 POLYLINE + ACI 色 + ASCII 标题；ACI = `((size-28)%24)+1`（size_aci，2026-08-20 尺码键；旧 `TYPE_ACI`/`TYPE_ORDER` US-002 已删）；US-024 起多 layer：outline layer1 / net layer14 / internal layer8 / notch layer4 POINT / grain layer7 LINE，各自独立 entity）/ `write_marker_plt`（US-033 HPGL/HP-GL 纯文本，**封装口径对齐生产 PLT** `data/PC-20250508NJIF*.plt`：头部 `IN;PS<纸长>;SP1;PW0.08;` + `SP1-5;` PU/PD + 尾部 `PU;PG;`，CRLF 行尾，无 VS/LB 指令；坐标=mm×40 round；5 层笔号 SP1=outline/SP2=net/SP3=internal/SP4=notch/SP5=grain + 门幅框并入 SP1；空层跳过；纯 ASCII bytes，无临时文件、无新依赖；**2026-08 现场撞机修正**：① 安全幅面 —— 内容按 y ≤ PLOT_SAFE_MAX_Y_MM 半平面裁剪（削平不缩放）、门幅框上沿压进可写幅宽（Y 内缩 PLOT_BORDER_MARGIN_Y_MM=5）、越界裁片记 warning（二道防线，兜旧 intermediate/求解 bug；求解已由 NEST_GATE_MM 一道钳制）；② PD 分块 —— `_plt_polyline` 单条 PD ≤10 点且整行 ≤110B 续画（对齐 ET 生产 ≤11点/≤118B，防国产 HP-GL 解释器行缓冲溢出坐标错位小车乱走）；③ 走纸引导 —— 全体 X + PLOT_LEAD_X_MM=20（贴 0 起画无定位余量），PS 纸长 = 引导 + max(用布长, 内容最大X) + 尾余量 PLOT_TAIL_X_MM=10）/ `_plt_frame_stats`（越界防御 + PS 纸长取值：全层顶点 + notch 点须在门幅框内，非 0 记 warning；notch 法线端点外伸只计入 max_x 不告警）。**2026-08-20 拆分**（600 行硬限制，658→47 门面 + 四模块，产物 PNG/PLT 逐字节等价、DXF 仅 $TDCREATE/$TDUPDATE 时间戳行差异（旧代码自身两次运行也不稳定））：`export_geometry.py`（placed_to_world/apply_transform/size_aci/LAYER5 常量，共享层）/ `export_png.py`（render_png，Agg+CJK rcParams 副作用保留）/ `export_dxf.py`（write_marker_dxf，ezdxf 警告抑制副作用保留）/ `export_plt.py`（write_marker_plt + 全部 PLT 算子常量）；export.py 门面 re-export 上表全部符号（含测试消费的 `_plt_frame_stats`/`_PLT_PD_MAX_PTS` 与旧模块属性 size_color/SIZE_ANCHOR/centroid/PLOT_SAFE_MAX_Y_MM），消费方 import 路径零改动 |
| `export_geometry.py` | 125 | 导出共享层（2026-08-20 自 export.py 拆出）：`placed_to_world` / `apply_transform` / `size_aci` + `LAYER5_COLOR_*` / `NOTCH_LEN_MM`；依赖 `sparrow_baseline`（size_color/SIZE_ANCHOR），被 png/dxf/plt 三模块单向依赖 |
| `export_png.py` | 117 | matplotlib Agg 渲染（2026-08-20 自 export.py 拆出）：`render_png`；模块级 `matplotlib.use('Agg')` + CJK rcParams 副作用原样保留 |
| `export_dxf.py` | 126 | R12-DXF marker（2026-08-20 自 export.py 拆出）：`write_marker_dxf` + `_DXF_LAYER_*`；模块级 ezdxf 警告抑制副作用原样保留 |
| `export_plt.py` | 329 | HPGL/PLT 文本（2026-08-20 自 export.py 拆出）：`write_marker_plt` / `_plt_frame_stats` / `_plt_pt` / `_plt_polyline` / `_clip_closed_y` / `_clip_open_y` / `_y_clip_point` + 全部 PLT 常量（撞机修正注释块整段搬移）；import `nesting_bounds.load_pieces.PLOT_SAFE_MAX_Y_MM` |

US-004 起 `web/server.py` 直接 import `dxf_parser.collect.collect_pieces_with_details`（web → dxf_parser 跨层依赖，合规：web 是上层）。US-010 起新增 import `dxf_parser.explore` / `dxf_parser.export_dxf` / `nesting_bounds.load_pieces`（web → nesting_bounds → dxf_parser 单向，合规）。上传 multipart 依赖 `python-multipart`（已在 `[web]` extra）。

## cli/ — 配置驱动求解 CLI（PRD config-driven-solve-cli，US-001 起；串行 Seed Portfolio PC-001 起进程化求解、PC-002 起控制器转发、PC-003 起 kill 引擎、PC-004 起标定管线、PC-005 起 ETT 离线仿真器、PC-007 起 LNS 波段重排、PC-008 起 LNS 接入编排、PC-009 起 run 统计库与 θ₀ 校准、策略双模式 US-001（strategy PRD）起判据纯函数族、US-002 起 `--strategy race|se` CLI 旗标接线与真实冒烟）

最上层编排者（`cli → web → nesting_engine → nesting_bounds → dxf_parser`）：读 `data/configs/` 下 7 键 JSON 配置跑「parse → commit → solve」全管线，**绝不 import `web.server`**（可 import `web.solver` 等纯求解封装）；产物只落 `out/config_runs/<run_name>_<时间戳>/`，物理隔离 web 事实源（`out/sparrow_baseline/` 与 `out/uploads/` 零触碰）。PC-001（PRD tasks/prd-serial-seed-portfolio.md）起 `solve_pieces` 切多进程求解 + 逐帧轨迹落盘 + `should_stop` 中止能力，为 portfolio 控制器（kill/达标即停）与标定管线提供执行手段与数据。PC-002 起多 seed 串行循环经 `cli/portfolio.py` 控制器转发（incumbent banking + R0 达标即停 + R4 队列耗尽），`--target`/`--params` 新旗标落 `run_config`（7 键 config schema 不动）。PC-003 起控制器内嵌 kill 引擎（R1 包络 / R2 压缩期判决 / R3 θ 衰减 + shadow mode，`--kill` 旗标），决策日志落 `run_dir/kill_decisions.jsonl`。PC-004 起标定管线 `cli/calibration.py`（batch/variants/analyze/simulate 四子命令）为 kill 参数产出数据依据（`--params` 消费的 controller_params.json + 泛化报告 + PC-005 ETT 仿真报告），产物只落 `out/portfolio_calibration/<tag>/`。PC-006 起 `build_instance`/`solve_pieces` 支持可选 `solver_opts`（spyrrow 旋钮白名单 exploration_pct/quadtree_depth/num_workers，`run_config --solver-opts`（全 seed 固定档）/ `--rotate-opts`（内置 4 档池逐 seed 轮换去相关，含默认空档）互斥旗标透传；WS 协议与 web 前端零改动）。PC-007 起 `cli/lns.py` LNS 波段重排核心（对 run_dir 最优布局做波段级 ruin-and-recreate，独立 CLI `ms-lns`，产物 result_lns.json + 前后对比 SVG 落 run_dir；PC-008 起经 `postprocess_run_dir` 共用入口接入 `run_config --lns` 编排 —— portfolio 跑完自动后处理，严格更优才回写 result.json）。PC-009 起 run 统计库与 θ₀ 校准（`run_config` 完成 run 追加一行 JSONL 到 `paths.RUN_STATS_JSONL`（class_key = sha1(source+sizes+quantities+per_type) 短哈希按实例类聚合），`--target` 模式启动读该库把 kill 门槛初值校准为 `min(target, 历史最大 best_density+0.003)`（≥5 条历史才触发；θ₀ 只降 kill 门槛，R0 恒用 --target；写盘失败只 warn 不阻塞）。US-002（strategy PRD）起 `--strategy [se|race]` 双模式旗标接线：`--strategy race`（门杀，B 方案缺省档）逐 seed `race_budget` 预算 + `decide_race_kill` 门杀（被杀 seed 交付 best-so-far 走既有 R5 终止链）；`--strategy se`（筛延，A 方案）k×`se_screen` 串行筛选 + 冠军（argmax real_density）`se_ext` 延长重跑（`_ext` 边车）；`--time` 在策略模式 = 总预算（必填）、名义记账（92.5/182.5）+ `can_start_next` 动态收口、种子流 `strategy_seed_stream`、启动即写 `run_dir/strategy.json`；无 `--strategy` 时 CLI/控制器/result.json 调用形逐字节零回归。

| 文件 | 职责 |
|------|------|
| `config.py` | US-001 `load_config(path)` 严格校验 7 键 schema（`master_dxf/sizes/gate_mm/time/seeds/per_type/quantities`）→ `NestRunConfig` frozen dataclass；`ConfigError(ValueError)` 中文报错含字段名（未知顶层键含旧 `seed`/`multi_seed`/`seed_count` → 提示已被 `seeds` 列表取代；`master_dxf` 相对路径 CWD→`paths.REPO_DIR` 两候选解析、失败列两个绝对路径；quantities 码号键须数字字符串或 `'null'`、数量须 JSON 数字 ≥0；per_type 键 `^g\d{1,3}$`、值仅 `d`/`tol` ≥0，超 `MAX_OVERLAP_MM=10`/`MAX_ROTATION_TOL_DEG=45` 不报错但 UserWarning 钳制提示）。**模块级 import 仅标准库**（paths/constraints 走函数内延迟 import 单一真相源），`python -m materialsorting.cli.config` 零副作用 |
| `portfolio.py` | **PC-002 串行 seed portfolio 控制器**（纯 Python 状态机，`run_config` 串行循环的转发实现）：`PortfolioController(*, seeds, target=None, params=None, echo=None)` 持有 incumbent（全局最优帧）/ per-seed best / `queue_stopped` 停止位。**incumbent banking（FR-2）**：`make_progress(seed)` 产 on_progress 回调 —— 每帧 `density` **严格大于**全局最优即入账 `{density, width_mm, seed, frame_index, elapsed, placed_items}`（完整布局；frame_index 自计数与 curve_s\*.json 下标对齐），被 kill / Ctrl-C 中断 seed 的最优帧同样参与（任何中断交付物都是过程最好帧，修复旧 best 只看 per-seed 终值的盲区）；同回调兼进度行输出（echo=None 即 `--quiet` 全静默）：per-seed「原面积口径新最优」行与 30s 心跳行**逐字保留旧版格式**（单 seed 输出与旧版逐字一致），**跨 seed 反超**时打 incumbent 行（`[portfolio] seed N frame M 反超 → incumbent（全局最优）...`，同 seed 自我刷新不打）。**R0 达标即停**：`make_should_stop(seed)`（仅 `--target` 给定时挂载 → 无旗标 solve 调用形与旧版完全一致）—— 任一帧 `density >= target` → 返回 `'R0_target_reached'`（solve_pieces 透传 kill_reason + terminate 当前 seed）并置 `queue_stopped`（剩余 seed 不再启动，per_seed 对未启动 seed 无记录）；触发帧先入账后停；R4 队列耗尽正常结束。`finish_seed(rec)` 入账 per_seed `{seed, killed, kill_reason, best_density, elapsed}`。`portfolio_section()`：engaged（target 给定或 seeds≥2）→ `{target, incumbent, per_seed, theta_history}`（theta_history PC-003 R3 填充、PC-002 恒空）；不激活（单 seed 无 --target）→ 全空段。`best_record(solves)`：engaged 且有帧 → incumbent（帧级全局最优），否则旧语义 `max(real_density)`。`run_serial_portfolio(cfg, run_dir, *, controller, time_budget, solve=None, on_seed_start, on_seed_done)`：逐 seed 串行编排（solve 可注入 fake 单测；Ctrl-C 捕获为 `interrupted=True` + `last_round=(i, seed)`、求解异常上抛呈现层；每轮完成回调 `on_seed_done` → run_config 逐轮重写 result.json）。`load_controller_params(path)`：`--params` 标定参数文件校验加载（存在 / 合法 JSON / 顶层对象，`ControllerParamsError(ValueError)`、utf-8-sig 容错 BOM）。**PC-003 kill 引擎**：纯函数判据 `r1_below_envelope(d, S(τ), m)`（严格小于；S=None 恒 False）/ `r2_below_threshold(d, uplift, θ, I, ε)`（门槛 `max(θ, I+ε)`，I 缺席退化 θ）/ `make_envelope(params)`（`envelope` dict → S(τ) 阶梯查表，最大网格点 ≤ τ；空/全非法/非 dict → None 即 R1 整体禁用）/ `resolve_kill_params(params)`（`KILL_DEFAULTS` 数值覆盖：tau0=0.3/W=10/m=0.005/epsilon=0.001/delta=0.003/m_streak=3/uplift_q95=0.005；负值/bool/字符串回退默认）。控制器状态：`kill_mode`（生效模式，target 未给定恒 off）、`theta`（初值 = target）、`kill_streak`（连杀计数，非 kill 结束清零）、`time_budget`（τ 分母；`run_serial_portfolio` 在直接驱动未显式给时补齐）、`kill_decisions`（决策副本）。构造签名扩展 `PortfolioController(*, seeds, target, params, echo, kill='shadow', time_budget, notify, on_decision)`：`notify` 用于不可静默的判据事件（R3 θ 衰减 —— run_config 传无条件 print，--quiet 也打）；`on_decision` 决策落盘回调（控制器不做文件 I/O）。`make_progress(seed, index=1)` 兼重置该 seed kill 瞬态（R1 迟滞起表 r1_since / R2 首压缩帧旗标 r2_seen / 已记决策去重集）；`make_should_stop(seed, index=1)`：R0 恒先且恒用 `--target` 真值 → kill_mode!=off 时 `_evaluate_kill`（**队列序号 ≤1 永不 kill**；R1：τ>τ0 且 below 持续 ≥W 秒才杀、追平清零计时（瞬时下探不杀）；R2：首帧 compressing 一次性判决；R1 优先于 R2；每 (seed, rule) 首次触发经 `_record_decision` 记 `{t, seed, rule, d, tau, S_tau, theta, I, would_kill}`（ASCII 键名版））→ shadow 只返回不杀（should_stop 恒 falsy）、on 才把规则名作为 should_stop 返回值真杀。`finish_seed` R3：kill 规则（R1/R2）连杀 ≥ m_streak → `θ := min(θ, I+δ)`（单调只降）+ `theta_history` 条目 `{after_seed, kill_streak, theta_old, theta, incumbent}` + notify 行；R0/跑满/异常清零连杀。`portfolio_section()` 段新增 `kill_mode` 键。**US-006**：`run_serial_portfolio` 加可选 `solver_opts_for(index, seed)`（0 起队列序 → 非空 dict 才以 `solver_opts=` 传该轮 solve，缺省不加键保旧 fake 兼容）。**PC-009 run 统计库纯函数三件套**：`run_stats_class_key(source, sizes, quantities, per_type)` = sha1(规范化 JSON，sort_keys 键序无关)[:10] 实例类指纹（写入侧 run_config 与读取侧 θ₀ 校准共用，class 口径单一真相源）；`load_run_stats(path)` JSONL 容错读取（缺文件/坏 JSON 行/非 dict 行/空行跳过 → []，OSError 视为无历史）；`calibrate_theta0(records, class_key, target, *, min_records=THETA0_MIN_RECORDS=5, margin=THETA0_MARGIN=0.003)` → `(theta0, info)`：当前 class_key 命中且有效记录（best_density 数值非 bool）≥5 条 → `min(target, max+margin)`（min 封顶不抬门槛）+ `info={'n_records','max_density'}`（说明行数据源），否则 `(target, None)`；坏记录不计样本。控制器构造签名扩展 `theta0=None`：只作 `self.theta` 初值（kill 判据锚，R2 判决/R3 衰减起点），**R0 停止条件恒用 self.target**；缺省 None → θ=target 零回归。**US-001 策略双模式判据纯函数族**（`--strategy race|se` 单一真相源，无 I/O 无进程；US-002 控制器接线消费、US-003 simulate 复用同判据）：常量 `R5_REASON='R5_race_gate'` / `RACE_BUDGET_S=180` / `RACE_GATE_TAU=0.5` / `SE_SCREEN_S=90` / `SE_EXT_S=180` / `STRATEGY_STARTUP_S=2.5` / `SEED_UNIT_S=92.5` / `FULL_UNIT_S=182.5`（名义记账 = 求解预算 + ~2.5s 启动开销，与离线对决/ETT 仿真同口径）；`strategy_seed_stream(cfg_seeds, n)` 种子流（config seeds 优先消费、不足按 max+1 递增补齐、去重保序、**保证无重复** —— 确定性重放下同预算重跑同 seed 零信息增益）；`race_gate_seconds(budget, tau)` = 门时刻（默认 180×0.5=90s）；`decide_race_kill(best_so_far, elapsed, state)` race 门杀判据（纯函数 + 显式 state dict：seed/index/gate_seconds/budget/bar/incumbent/judged）—— 门帧 = **首帧** elapsed≥gate_seconds，`best_so_far <= bar` 即判杀（严格破纪录才续跑）、首 seed（index≤1）无条件豁免、bar = 历史所有 seed 门值最大值（**含被杀者**，经 state['bar'] 回写 max 只升）、**每 seed 至多一笔**（judged 置位后同 seed 恒 None，门后不再判 —— 与确定性重放联合保证「同 seed 永不二次续跑」）；返回决策 dict 与 kill_decisions 行同构 `{t,seed,rule,d,tau,S_tau,theta,I,would_kill}`（race 重载：S_tau=bar 参照值、theta=null）；`se_plan(total_budget, screen_s, ext_s)` → `(k, ext_s)`：`k = max(1, (T−full_unit)//seed_unit)`（单位 = 各旗标预算 + 启动开销，默认即 92.5/182.5），`T < full_unit + seed_unit` 连「1 筛 + 1 延」都装不下 → `StrategyBudgetError(ValueError)`（CLI 退出 1）。回归护栏：`tests/fixtures/strategy_curves_8.json`（8 配对 seed 降采样曲线小宇宙，b90s/b180f 跨 fork 结构如实保留）+ `tests/test_cli_strategy.py` 判据单测 + bootstrap 回放（T=1200/3600 两模式 − uniform90 ≥ +0.1pt、T=3600 漏 max 率 ≤5%）。**US-002 控制器双模式接线**：`race_plan(total_budget, race_budget, race_gate_tau)` → `(planned_n, gate_seconds)`（full_unit=budget+2.5、gate_unit=gate+2.5，最小预算 = 1 全程 + 1 门段，不足抛 StrategyBudgetError）。构造签名扩展 mode=legacy|race|se（STRATEGY_MODES）+ total_budget/race_budget/race_gate_tau/se_k/se_screen/se_ext（race 必给 total_budget）；engaged 追加 mode != legacy。`make_should_stop`：R0 恒先 → mode==race 走 `_evaluate_race`（组装 state dict 调 US-001 `decide_race_kill`，bar/incumbent/judged 回写同步；首 seed 豁免；决策行（含豁免/通过/门杀，would_kill 区分）经既有 `_record_decision` 链落 kill_decisions.jsonl；判杀 notify 门杀行 --quiet 也打 + 返回 R5_REASON 走既有 terminate 链交付 best-so-far）；strategy 模式 R1/R2 不评估、θ 不维护（kill_mode=off）。`make_progress` 追加 current_phase（race→race；se→index>se_k 为 extension 否则 screen，兼重置 _frames_seen 对齐 _ext 曲线帧号）。`can_start_next()`：race 名义记账收口（_spent + gate_unit <= total_budget；killed 记 gate_unit、跑满记 full_unit）。`round_budget(index)`：race→race_budget；se→screen/ext 分段；legacy→default（透传旧行为）。`finish_seed` 策略条目附 phase + race 侧 kept_seeds/gated_seeds 记账。`portfolio_section()` 策略模式条件加 mode + race={gate_seconds,kept_seeds,gated_seeds} 或 se={k_screens,screen_s,ext_s,champion}。`run_serial_portfolio`：主循环 `can_start_next()` 拦截未启动 seed（race 收口）；se 模式队列后冠军延长轮（argmax real_density、`_run_round(suffix=_ext)`、rec phase=extension、R0/中断/queue_stopped 跳过）。回归护栏 `tests/test_cli_strategy_wiring.py`（28 用例：旗标裁决/race·se 端到端/零回归哨兵/--help）。分层：模块级仅 import `.pipeline` + 标准库（PC-009 加 hashlib），不 import web |
| `lns.py` | **PC-007 LNS 波段重排核心**（`ms-lns` / `python -m materialsorting.cli.lns`，`--run-dir <dir> --time 30 --rounds 5 [--band-width mm]`）：对 run_dir 最优布局做波段级 ruin-and-recreate，突破单 seed 收敛分布上限。**布局来源** `portfolio.incumbent.placed_items` 优先，回退 `best.placed_items`（旧式多 seed run 只存 int 计数 → 按边车 `best_frame_s{seed}.json` 回填）。**算法**（每轮按段局部密度升序逐段尝试，首个接受即完成该轮）：① 按 x 切竖直波段（缺省段宽 `DEFAULT_BAND_WIDTH=1.5×NEST_GATE_MM`；pid 组按**首副本中心**归段，demand>1 全部副本整段重排禁止拆分）；② 段局部密度 = 段内片**原面积**和/(段宽×NEST_GATE_MM)；③ 段内裁片构造**同口径子实例**（`web.solver.build_instance` 延迟 import：per_type/sizes 按 result.json config 回显透传；quantities 按**段内实际副本数**派生 ≡ 母 quantities 在该 pid 的投影，中间帧 incumbent 也精确成立），`_solve_band` 经 `solve_with_callback_proc` 多进程重解（与 pipeline.solve_pieces 同链路；seed = base_seed+1+round×1000+band_index 确定性；子预算 = 剩余预算/剩余轮数，<MIN_SUB_TIME_SEC 判耗尽）；④ 新段跨度 < 原段跨度 − `ACCEPT_EPS_MM=0.5` → 接受：新段左缘对齐原足迹左缘 m（接受条件保证新足迹 ⊆ [m,M]）、**完全位于 M 右侧**的片（几何判定非段序 —— 跨段散布副本按段序左移会被推出 x<0）左移 splice、总宽缩短；否则拒绝（幂等安全：无任何接受时输出 = 输入列表**原对象**，逐字节不变）；空段（纯空洞）无需求解直接让位；⑤ 循环 rounds/预算，结束 `constraints.validate` 全版复检（**(y,x) 交换**坐标 + Y_TOLERANCE_MM=11 平移放宽，容纳 erode 合法外凸，与 export 削平口径同源）+ `y≤PLOT_SAFE_MAX_Y_MM` 越界复检，失败**回退输入布局**（交付物恒过检）。**跨组重叠护栏**（超验收口径工程加固）：接受前 shapely 精确比较「新段×不动片」「左移段×不动片」**每一对**交集面积，任一对超原布局同对基线 + 1mm² 即拒（逐对不劣化，杜绝净增为零局部恶化的 redistribution；shapely 不可用降级跳过留痕）。**产物**：`run_dir/result_lns.json`（source 回显 incumbent_seed/config_echo + 新 placed_items + before/after/delta（width/density 原面积口径）+ rounds_detail 逐段明细 + recheck 状态）+ `run_dir/lns_compare.svg`（前后双面板 `scale(1,-1)` 翻转组 + g 码图例，口径同排料 SVG）；stdout 汇总前后两行。Ctrl-C 捕获 stop_reason=interrupted 已完成轮照常落盘。退出码 0 成功 / 1 输入错误（result.json/pieces_intermediate.json 缺失、无 incumbent、坏旗标）。**PC-008 `postprocess_run_dir(run_dir, *, time_budget, rounds, band_width, echo, solve)`**：run_dir 级共用编排入口（ms-lns CLI 与 `run_config --lns` 同一条代码路径）—— 读 result.json 选布局 → run_lns → result_lns.json + lns_compare.svg 落盘，返回写盘 payload（source + 全部结果键含 placed_items，调用方据此裁决回写）；输入错误经异常上抛由调用方决定呈现。分层：模块级仅 argparse/json/math/sys/time/pathlib/types + nesting_bounds/nesting_engine，**web 仅函数内延迟 import**（`--help` 冒烟零负担）。**2026-08-20 拆分**（600 行硬限制）：拆后 511 行门面 + 编排层 —— `run_lns` 主循环/`_solve_band`（测试 monkeypatch 锚点，缺省解析须在本模块全局命名空间）/CLI 全套留守；基元与渲染搬 `lns_bands.py`/`lns_svg.py`，门面绝对导入 `from materialsorting.cli.lns_bands import ...` re-export 全部旧公共符号（纯度测试 AST 白名单只认 materialsorting 顶层名，相对导入会挂）；拆分经 AST 逐符号对拍（21/24 逐字节相同，3 差异 = 2 处 docstring 交叉引用 + 1 处为拆分前已在工作区的尺码换键改动） |
| `lns_bands.py` | **LNS 共享基元底层模块**（2026-08-20 自 lns.py 拆出，226 行）：全部 LNS 常量（`ACCEPT_EPS_MM=0.5`/`Y_TOLERANCE_MM=11`/`GUARD_SLACK_MM2=1`/`MIN_SUB_TIME_SEC`/`DEFAULT_BAND_WIDTH=1.5×NEST_GATE_MM`）、`LnsError`、几何算子（`_world_polygon`/`_layout_geometry`）、波段切分（`split_bands`/`band_solve_params`）、跨组重叠护栏（`_bbox_of`/`_pair_area`/`_cross_overlap_ok`）、全版复检 `recheck_layout`；仅依赖 stdlib + nesting_bounds + nesting_engine.constraints，零 web import；被 lns.py（re-export）与 lns_svg.py 共用，依赖链单向无环 |
| `lns_svg.py` | **lns_compare.svg 渲染**（2026-08-20 自 lns.py 拆出，96 行）：`_fmt` + `write_compare_svg` 前后双面板对比图（`scale(1,-1)` 翻转组 + **尺码图例**（2026-08-20 起颜色键 = `size_color(size)`，两面板 placed 的 size 并集数值序），口径同排料 SVG）；依赖 `lns_bands._world_polygon` + `sparrow_baseline.size_color` |
| `run_config.py` | US-003 `ms-run-config` 入口（console_script 与 `python -m materialsorting.cli.run_config` 等价）：argparse（`config` 位置参数 + `--name RUN_NAME` 覆盖 run_name + `--time N` 覆盖单轮时长（冒烟用） + `--quiet` + **PC-002 `--target P`**（(0,1] 比例、原面积口径；越界退出 1）+ **PC-002 `--params FILE`**（controller 标定参数 JSON，`load_controller_params` 坏文件退出 1））；run_dir = `new_run_dir(清洗后的 run_name)`（缺省 = 配置文件 stem，Windows 非法字符与控制字符 → `_`，空回退 `run`）；逐 `cfg.seeds` **经 `run_serial_portfolio` 控制器串行** `solve_pieces`（**US-004 多 seed 语义**：commit 仅一次、每轮重建 build_instance 复用同一份 commit 产物；只串行不并行；种子不要求连续，`[0, 42]` 合法；多 seed 启动即打印预计总时长 `len(seeds)×time` + 每轮「第 i/N 轮（seed=s）」标记 —— PC-002 起**单 seed + `--target` 也打轮次头**，单 seed 无旗标保持零输出增量）；进度行由控制器 echo 统一（`None if quiet else print`）：原面积口径新最优 + 30s 心跳 + 跨 seed 反超 incumbent 行；落 `run_dir/result.json`（config 回显 —— `time` 为 `--time` 覆盖后**生效值** + commit 摘要 + solve 指标数组 + **`best`** + **PC-002 `portfolio` 段**）。**PC-002 best 语义升级**：engaged（`--target` 给定或 seeds≥2）→ `best = portfolio.incumbent`（帧级全局最优、含完整 `placed_items` 布局 list，真实数据验证帧峰可高于全部 seed 终值）；单 seed 无 `--target` → 空 portfolio 段 + best 旧语义（solve 数组 `real_density` 最大者，并列取先执行者）—— 无旗标冒烟对拍兼容；`_best_summary()` 把两种 best 形态归一为汇总四元组（末行汇总 real_density/用布长度/片数/耗时/run_dir 格式不变，incumbent 的 placed_items 取 len）；R0 提前停后打「`[portfolio] R0 达标即停：target=...，incumbent ...，剩余 N 个 seed 未启动`」终局行（`--quiet` 也打，退出码仍 **0**）；**PC-003 `--kill {shadow,off,on}`**（默认 shadow；argparse choices 与 `portfolio.KILL_MODES` 同源）：生效模式裁决 —— 无 `--target` → 恒 off（显式 on 时 stderr 提示「--kill 需要 --target」）；`--kill on` 且 `--params` 不含 `"calibrated": true` → **自动降级 shadow 并 stderr warn**（未标定包络/uplift 不可信不许真杀）；引擎激活（shadow/on）即建 `run_dir/kill_decisions.jsonl`（空文件也在场），决策经 `on_decision` 回调逐条 append+flush（Ctrl-C 不丢）；控制器 `notify=print` 无条件传（θ 衰减行 --quiet 也打）；多 seed 末段先打「各 seed real_density」+ 「best = seed N frame M（incumbent，帧级全局最优）」+ 「`[kill] <mode> 模式：N 条 kill 判定已写 <path>`」（置于末行汇总前 —— 末行 = real_density 汇总是既有输出契约）；`main()` 首行 `sys.stdout/stderr.reconfigure(encoding='utf-8')` 防 Windows GBK 乱码（非常规流无 reconfigure 则跳过）；退出码 **0 成功（含 R0 提前停）/ 1 配置或管线失败（ConfigError / --target 越界 / --params 坏文件 / commit 抛错）/ 2 求解失败 / 130 Ctrl-C 中断**。**PC-001 逐 seed 落盘**：每轮完成即重写当前 `result.json`（结构同终态，solve 数组为已完成轮 + portfolio 段同步），Ctrl-C 时 run_dir 已持有已完成轮的 curve_s\*/best_frame_s\*/result.json。**PC-006 solver_opts 旗标**：`--solver-opts <JSON>`（白名单三键全 seed 生效）/ `--rotate-opts`（内置 `SOLVER_OPTS_POOL` 4 档含空档，`pool[0起队列序 % 4]` 轮换取档去相关）互斥同给退出 1、坏 JSON/非对象退出 1（new_run_dir 之前拦截）；`rotation_opts_for(seed_index)` 模块级 helper；旋钮清洗单一真相源在 `web.solver._normalize_solver_opts`（CLI 不复制）；config 段旗标给了才回显 `solver_opts`/`rotate_opts` 键。**PC-008 `--lns [--lns-time 30] [--lns-rounds 5]`**（从属旗标单独给出/值 <1 → new_run_dir 前拦下退出 1；启动说明行 `--quiet` 也打）：portfolio 跑完（含 R0 提前停，对达标解也可再压宽度；Ctrl-C 中断的 run 不做后处理）后调 `lns.postprocess_run_dir`（布局 = engaged incumbent / 单 seed 旧语义 best 帧边车回填；echo 随 `--quiet` 抑制）；**严格更优才回写** —— `controller.incumbent` 三字段（density/width_mm/placed_items，seed/frame_index/elapsed 保持来源帧出处）更新 + `lns_state` 段（`_lns_section`：前后对比/Δ/轮次明细/复检/base_seed/产物文件名，placed_items 不入段控体积）后 `_flush_result()` 一次性整体重写（best 与 portfolio.incumbent 同一 dict 自动同步，末行汇总取 LNS 后口径）；不优则 result.json 逐字节不变（明细仍写 result_lns.json + lns_compare.svg）；stdout 加 `[LNS] 前/后` 两行（终局口径 `--quiet` 也打）；LNS 环节 Ctrl-C（run_lns 内部捕获 interrupted=True）→ 已完成轮已落 result_lns.json、改进（若有）已回写、退出码 130，窗口外 Ctrl-C 兜底 except 同 130；LNS 输入错误（LnsError/OSError/JSONDecodeError 等）降级 stderr warn 跳过（退出码 0，不否定求解交付物）。**PC-009 run 统计库 + θ₀ 校准**：`main()` 首记 `t_start`（elapsed_total 整 run 墙钟口径）；`--target` 给定时启动即 `stats_class_key = run_stats_class_key(...)` + `calibrate_theta0(load_run_stats(paths.RUN_STATS_JSONL), ...)` → 命中打「`[portfolio] θ₀ 校准: class_key XXX 命中 N 条历史（最高 best_density=…）→ θ 初值=…（只影响 kill 门槛，R0 停止条件恒用 --target）`」说明行（`--quiet` 也打，判据变更不静默）+ `PortfolioController(theta0=...)`；run 结束（exit 0 完成路径，含 R0 提前停/kill；Ctrl-C/求解失败不沉淀 —— 不完整数据污染历史 max）`_append_run_stats({ts, source, sizes, class_key, seeds, target, best_density, n_killed, elapsed_total, config{time,per_type,quantities}})` 追加一行 JSONL 到 `paths.RUN_STATS_JSONL`（best_density 取末行汇总同款口径含 LNS 改进；n_killed = per_seed killed 计数含 R0 停下的 seed；写盘 OSError（目录只读/目标是目录等）降级 stderr「警告: run 统计落盘失败」不阻塞，退出码与末行汇总不受影响）。**US-002 `--strategy [se|race]` 双模式旗标**：nargs='?' const='race'（裸旗标 = 缺省 B 方案门杀）；`--time` 在策略模式 = 总预算秒（**必填**，缺省退出 1）；从属旗标 `--se-screen/--se-extend/--race-budget`（int ≥1）/ `--race-gate`（(0,1) 开区间比例）—— 值域外 / 从属旗标缺主旗标 / `--kill` 显式与 `--strategy` 互斥 / `race_plan`·`se_plan` StrategyBudgetError 预算不足 → 均 new_run_dir 前退出 1；策略模式 kill_mode=off（与 kill 引擎互斥）但 race 决策仍逐行落 kill_decisions.jsonl（schema 复用，S_tau=bar 参照、theta=null 重载，README 有过载备注）；种子流 = `strategy_seed_stream(cfg.seeds, planned_n)`；θ₀ 校准仅 --target 且非 strategy 时执行；启动即写 `run_dir/strategy.json`（{mode,total_budget,planned_seeds,started_at,race|se 计划}，commit 打印后首解前）；门杀/预算收口行 --quiet 也打；digest 含策略轮与「（延长）」标记；run_stats seeds 记实际种子流；result.json config 段条件回显 strategy（mode+旗标值）、portfolio 段条件 mode/race/se；无 `--strategy` 时 CLI 与 result.json 输出**逐字节零回归**（`--kill` 缺省改 None 内部归一 shadow，行为不变）） |
| `calibration.py` | **PC-004 标定管线**（`python -m materialsorting.cli.calibration`，产物只落 `paths.CALIBRATION_DIR=<tag>/`，gitignore 区，不触碰 config_runs/web 目录）：**batch** `--config [--tag] [--short-seeds 20] [--short-time 90] [--full-seeds 8] [--full-time N]` —— 标定基实例 `data/configs/5336_coded_really.json`（真实 per_type+订单配比）；`commit_from_config` 只跑一次落 `<tag>/commit/`，short 组（缺省 20 seed × 90s）与 full 组（缺省 8 seed × config.time=300）**同 seed 值配对分目录** `base/{short,full}/`（供秩相关），逐 seed 串行 `solve_pieces`（≤1 求解子进程不变量），manifest.json 逐 seed flush（Ctrl-C 130 标记 interrupted，重跑按 curve+best_frame 完整性跳过已完成 seed）。**variants** `--config [--variants 4] [--short-seeds 6] [--short-time 90] [--full-seeds 1] [--full-time N]`：`generate_variants(base_raw, n)` 确定性变体（`random.Random(i)`，逐字节可复现）—— 只抖 quantities 的 (g码, 码∈sizes) 条目 `n' = max(1, n+δ)` δ∈{-1,0,+1} 等概率（保底 1 片；惰性条目/null 不动），per_type/gate_mm/master_dxf/sizes 逐字段固定；每变体 load_config 校验后落 `variant_{i}.json` + 共享同一 commit 跑曲线。**analyze** `--tag --target [--env-quantile 0.25]`：聚合 base/short+full 曲线 → `analysis/summary.json`（每 seed final/best/time_to_best/plateau + mean/σ/P(≥target)）+ `controller_params.json`（成功包络 S(τ)：达标 seed best-so-far 轨迹在 τ 网格 0.05~1.0 步长 0.05 的低位分位数、running-max 保证单调；τ0=达标/失败分离度推导（无分离回退 0.3）、W=0.1×median time-to-best 钳 [5,30]、m=0.5×分离 gap 钳 [0.002,0.01]、ε/δ=σ 钳 [0.001,0.005]、m_streak=3；键名与 `--params` 直接对接；达标 seed <10 或包络格点不足 → `calibrated: false` + envelope={} 拒绝下发）+ `generalization.json`（base 包络 replay_r1 套到各变体曲线的误杀率，全部 <5% 才 transferable）；内含 train/test（seed 奇偶切分）误杀回测 + 短/全 Spearman 秩相关 + uplift q50/q95。**复用单一真相源**：判据回放 `replay_r1` 直接调 `portfolio.make_envelope/r1_below_envelope`（含 W 秒迟滞）；`CalibrationError` 配置类错误退出 1 / 求解失败 2 / Ctrl-C 130。分层：模块级 import 仅 `..paths`/`.config`/`.pipeline`/`.portfolio` + 标准库，零 web import。**simulate**（PC-005，`--tag --target [--budget SEC] [--scenarios 500] [--env-quantile 0.25] [--shadow-log FILE]`）：base 曲线（short+full 池）**同总预算公平比较**回放 `SIM_STRATEGY_GRID` 10 档（single/best_of_2/best_of_3 基线与均匀 portfolio + kill 三档 τ0/W/m 保守→激进 + θ 衰减两档 k=4/5 + US-003 策略双档 se180/race180），每档 B=total/k、eligible = 原生时长 ≥ B 的曲线（预算外不外推）；场景 = 有序 k 元组（\|pool\|^k ≤ 4096 全枚举，否则 `random.Random(0)` bootstrap N 个），`simulate_portfolio` 单场景回放直接构造 `PortfolioController`（kill='on'，seed 1 队列首豁免、R0 先判、R1/R2/R3 同生产语义）；ETT 口径：达标 = 前序 seed 耗时 + 首达标帧 elapsed，不可达 = 实际总耗时（kill 省时计入），不可达 incumbent 终值 = max(跑满 best, 被杀者 `interpolate_truncated_final`（kill 时刻 best + `conditional_gain` 条件期望增量，**下界 ≥ best-so-far**，无 hindsight oracle））；kill 包络 = `envelope_at_budget`（成功 = 预算 B 内达标者 best-so-far 在 τ·B 绝对墙钟重采样的低位分位数 + running-max，**只源自 base 池**）；变体池整体 held-out（同包络套变体曲线评 ETT/误杀率）；**US-003 策略双档**（se180/race180）走**配对曲线回放**：`paired_curves`（base/{short,full} 同 seed 值配对 —— short 原生 ≥90s 且 full 原生 ≥180s 才合格；变体 = variant_*/ 池合并）；`simulate_strategy_scenario` 单场景回放 —— race：`race_plan(T)` 计划 seed 数、名义记账收口（启动下一 seed 条件 spent+92.5≤T）、逐帧 R0 先判后 `decide_race_kill`（首 seed 豁免建 bar、严格破纪录才续跑、被杀交付 best-so-far；per_seed outcome full/kill/r0 + false_kill = 「该 seed full 曲线 180s 帧内本可达标」）；se：`se_plan(T)` k 轮筛选 + 冠军（argmax，平手取先）延长一次；**跨 fork 诚实口径**：筛选读 short 曲线截断 90s 终值、延长/续跑读 full 曲线截断 180s 帧；`evaluate_strategy_tier` 产出与 kill 档同构的 ETT 字段（**判据同现有**，场景序列长度取 race/se/uniform 三计划 max 保证跨档可比）+ **E[max] 口径**（delivered_mean/σ、oracle_max_mean、miss_max_rate、配对 uniform90 基线 gain_vs_uniform90、started_mean、n_kills、false_kill_rate）；总预算 <275 或无配对曲线 → metrics None + 中文 note 降级行（不进推荐）；`recommend_strategy` 推荐档 = `_RECOMMEND_KINDS`（kill/θ/strategy）中 base 与变体 ETT 双不劣于单 seed 基线且两者误杀率 <5% 者的 base ETT 最小者（策略档 params 含 `strategy`/`time`/`race_budget`+`race_gate` 或 `se_screen`+`se_extend`），`params` = `resolve_kill_params` 合并 + envelope + `calibrated: true` + n_seeds/per_seed_time/target/source（键与 controller_params.json 同构，可直接抄进 `--params`），无合格档 → strategy None 不硬推；`shadow_log_stats` 消费 ms-run-config 的 kill_decisions.jsonl（配同目录 curve_s{seed}.json）：决策后才达标 = 假阳性、全程不达标 = 正确 kill、缺曲线不进率，按 rule 分桶；产物 `analysis/simulation_report.json`（确定性：除 generated 外同输入逐字节一致） |

## scripts/ — repo 根维护脚本

包外独立工具（非 console_script，repo 根 `python scripts/<name>.py` 直跑；`sys.path` 自引导到 `materialSorting-server/src`，无包安装要求）。`inspect_*` / `_probe_*` / `us003_verify.mjs` 等为一次性探针不入册。

| 脚本 | 职责 |
|------|------|
| `embed_piece_codes.py`（180 行，2026-08-18） | 把 g01+ 编号 TEXT 植入母版 DXF，生成带编号新母版（原文件不动，缺省输出 `<stem>_coded.dxf`）。**解决的问题**：g 码真相源在 `labeling.assign_codes`（Web parse/commit 同源），但编号此前只出现在排料产物（PNG / marker DXF 逐片叠印），版师在 ET2008 打开母版时无法把图面上的片与系统里的 g 码对上。**做法**：对每条 layer1 POLYLINE（同 `collect_pieces_with_details` 口径）在其 **block 定义内**写 TEXT 实体（独立层 `'TEXT'`，不碰裁切层 1/14/8/4/7、不改 layer1 计数与枚举序 → piece_index 不变 → 重解析同码；TEXT 层不在 collect 提取白名单内，对解析管线不可见）；文本 `g03-30`（g 码-码号，size=None 只印 g 码，纯 ASCII 无字库坑）；定位 = 顶点质心（与导出叠印同口径 `labeling.centroid`），凹片（L 形前后片）质心落片外时回退 bbox 中线「最宽内条带中点」（必在片内）。**幂等**：写前清输出文档 TEXT 层既有实体，重复跑不叠字。**自校验**：输出文件重跑 collect + assign_codes 与原母版逐片对拍 `(block, size, piece_index) → g 码`，不一致即报错退出（防 ezdxf 回写副作用）→ 产物是原母版的 drop-in 替换，可直接再上传 Web 走 commit 且 g 码不变。用法：`python scripts/embed_piece_codes.py <母版.dxf> [-o 输出.dxf] [--height 25]`（字高 mm，与 marker DXF 叠印同口径）。示例产物：`data/5336#老六订单14%7%围加9_coded.dxf`（即 `data/configs/5336_coded_sizes32-38.json` 的 `master_dxf`） |

## 数据流主线

```
用户上传母版 DXF
  │ collect.collect_pieces_with_details（5 层 IR）
  ▼ /api/parse-dxf（预览）→ /api/commit-to-nesting
out/uploads/<doc_id>_pieces/{label}_{size}.dxf（如 g03_28.dxf；每片 layer1+14+8+4+7 五层，由 write_piece_dxf 切出）
  │ load_pieces.load_nest_pieces（pieces_manifest.json 驱动；_read_piece 读 5 层 + notch 法线按最近边重算 + _apply_layer_transforms 共享 transform 链 + 布纹对齐 + 归一化；US-001 v2 无镜像）
  ▼
NestPiece（母版全码，每片持 polygon + net_polygon + internal_lines + notches + grain_line 5 层）
  │ _commit_to_nesting_sync（labeling.assign_codes 最先赋 g 码，零丢片零合成，写 intermediate v2 + label_representatives）
  ▼
out/sparrow_baseline/pieces_intermediate.json   ← 全流程事实源（每片 5 层字段）
  │
  ├─ sparrow_baseline.main / sparrow_experiments.main（求解 → result/svg/curve；仅 polygon 参与 NFP，4 层忽略）
  └─ web（server 启动期 _PIECES_STATE 读取 + commit 后 reload + 可视化 + 导出 PNG/R12-DXF 5 层，US-020 + US-024）
```

逐跳函数链：

| hop | 函数（文件） | 输入 → 输出 |
|-----|------------|-----------|
| 母版 → IR 列表 | `explore.collect_pieces` | `Path` → `list[PieceOutline]`（layer1 毛版 + layer7 布纹线） |
| 母版 → 深度 IR 列表 | `collect.collect_pieces_with_details`（US-003） | `str\|Path` → `list[PieceOutline]`（layer1+7+14 净版+8 内部线+4 刀口，按 `LAYER_MAPPING`） |
| 上传母版 → 解析 JSON | `web/server.parse_dxf`（US-004） | `multipart file` → 落盘 `uploads/<uuid>.dxf` + `collect_pieces_with_details` → 按码分组 + `labeling.assign_codes` g 码赋号 JSON（`doc_id` 供 US-010 commit 引用） |
| 上传母版 → intermediate | `web/server.commit_to_nesting` + `_commit_to_nesting_sync`（US-010 Path A） | `{doc_id, filename?}` → `uploads/<doc_id>_pieces/` + `load_nest_pieces(pieces_dir)`（manifest 驱动） → 覆盖 `INTERMEDIATE`（先备份 `.bak`） |
| IR → 单裁片 DXF | `export_dxf.write_piece_dxf` | `PieceOutline` → `out/uploads/<doc_id>_pieces/{label}_{size}.dxf`（`_commit_to_nesting_sync` 调用） |
| IR → 探索产物 | `explore.write_outputs` | `list[PieceOutline]` → 分组目录 + CSV + 总览 SVG |
| 单裁片 DXF → NestPiece | `load_pieces.load_nest_pieces` | `uploads/<doc_id>_pieces/` → `list[NestPiece]`（manifest 驱动、零合成） |
| NestPiece → intermediate | `web/server._commit_to_nesting_sync`（US-010） | → `INTERMEDIATE`（`{source,gate_mm,n_pieces,total_area_mm2,pieces:[…]}`；写回前 `shutil.copy2(.json, .bak)`） |
| intermediate → baseline 解 | `sparrow_baseline.main` | → `result_{tag}_t{T}.json`/`svg`/`curve.json`/`curve.png` |
| intermediate → 实验解 | `sparrow_experiments.main` | → `result_exp_{tag}_t{T}_s{seed}.*` + 汇总 |

## 入口（`pyproject.toml` `[project.scripts]`）

| 命令 | 模块 | 作用 |
|------|------|------|
| `ms-explore` | `dxf_parser.explore:main` | 母版全裁片探索（分组 SVG/JSON + CSV + 总览） |
| `python -m materialsorting.dxf_parser.collect` | `dxf_parser.collect:main`（US-003） | 母版深度解析 CLI 冒烟（每码片数 + internal/notch/net 计数） |
| `ms-sparrow-baseline` | `nesting_engine.sparrow_baseline:main` | sparrow 基线求解（`{0,180}`，无 erode） |
| `ms-sparrow-exp` | `nesting_engine.sparrow_experiments:main` | 旋转/重合公差/组合实验 |
| `ms-web` | `web.server:main` | 可视化工作台（uvicorn :8000） |
| `ms-run-config` | `cli.run_config:main` | 配置驱动排料一条命令（commit → 求解 → result.json，US-003；`out/config_runs/<name>_<时间戳>/`；`--lns` 自动 LNS 后处理（PC-008，严格更优才回写）） |
| `ms-lns` | `cli.lns:main` | LNS 波段重排后处理（PC-007；对 run_dir 最优布局 ruin-and-recreate，产 result_lns.json + 对比 SVG） |

也可 `python -m materialsorting.<sub>.<module>`。`spyrrow` 非 PyPI 主流包，装不上需手动处理；`[web]` extra 拉 `fastapi`/`uvicorn`/`matplotlib`/`python-multipart`（US-004 上传解析需要 multipart）。

## 关键不变量（改后端勿破坏）

1. **分层单向**：`web → engine → bounds → parser`，下层禁 import 上层。
2. **路径走 `paths.py`**：禁硬编码 `..` / 绝对路径。
3. **DXF 走 R12 + POLYLINE**（非 LWPOLYLINE）：ET2008 读 LWPOLYLINE 轮廓消失。单裁片与 marker 导出均如此。
4. **sparrow 不改源码**：作为 `spyrrow` pip 包引用，v0.3 约束在外层 `constraints.py` + `solver.build_instance` 包装实现。
5. **density 双口径**：`real_density = total_area/(width*min(gate_mm, PLOT_SAFE_MAX_Y_MM))`（原面积·实际幅宽口径，2026-08-20 起分母与求解约束带同口径，导出为 `density`，90% 生死线口径）；`density_sparrow`（erode 后 sparrow 自报，仅参考）。
6. **坐标系**：spyrrow X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上；前端 SVG `scale(1,-1)` 翻转后与 PNG / R12-DXF 一致。
7. **导出用原始轮廓非 eroded**：`_PIECES_STATE['pieces_by_id']`（US-020 替代旧 `PIECES_BY_ID`）持原始 polygon，`placed_to_world` 用它变换；eroded 仅用于求解/屏幕。
8. **`server.py` 启动期 `_reload_pieces_state()`**（US-020）：import 时读 intermediate 填 `_PIECES_STATE`；allow-empty 不再让 import 崩；commit 成功后立即 reload，前端无需重启 ms-web。`_state_lock=threading.Lock()` 保护 immutable snapshot 模式（整体替换 dict 内容）。
9. **5 层中 4 层仅渲染透传（US-024）**：`polygon`（layer1 毛版外轮廓，erode 后）是唯一参与 sparrow NFP 碰撞的几何；`net_polygon` / `internal_lines` / `notches` / `grain_line` 4 层仅渲染与 PNG/DXF/PLT 导出透传，不影响求解结果或利用率。改任一层定义需同步 collect.LAYER_MAPPING + export_dxf.write_piece_dxf + load_pieces._read_piece_full + web/server._commit_to_nesting_sync + solver.pid_meta + web/export.py + NestSVG。
10. **notch 法线读时重算（US-024）**：DXF POINT 仅存位置，无法线字段；`_read_piece_full` 读时调 `_collect._nearest_edge_with_normal` 按 outline 最近边重算（与 `collect._assign_notch` 同算法）。退化边（连续重复点）返 (0,0) 法线 → NestSVG / PNG 渲染为 0 长度线段兜底。
11. **求解进程化（US-025 + US-026 接线）**：`solve_with_callback_proc` 是 `solve_with_callback`（threading）的多进程替代 —— spyrrow Rust .pyd 无 cancel/abort/stop API，唯有 `Process.terminate()`（Windows 调 TerminateProcess）可可靠终止原生阻塞 solve；spyrrow 对象不可 pickle，故 `build_instance` 必须在子进程内执行（`solve_worker` 顶层函数 + 参数全 JSON 可序列化），只把 pid_meta/frame/final/error 经 `multiprocessing.Queue` 传回主进程。**US-026 已切换 `ws_solve`**：write loop 内联 + read loop 后台 task 双向并发；`on_process` 回调把 Process 句柄交给 ws_solve；stop/断开 → terminate+join 防孤儿。旧 `solve_with_callback` 保留不删。终止安全：`terminate() → cancel_join_thread() → 限时 drain(≤50ms) → join(timeout=5)`，绝不阻塞。
12. **门幅双口径解耦（2026-08-16 绘图仪撞机修正，1aedc10）**：`GATE_MM=1980` 是布幅**显示**口径（UI / 密度分母 / 导出外框 / WS manifest gate_mm），`PLOT_SAFE_MAX_Y_MM=1910` 是绘图仪 Y 可写幅宽，`NEST_GATE_MM=min(两者)` 是**求解约束带** —— 三常量单一事实源在 `nesting_bounds/load_pieces.py`，`web/solver.build_instance`、`sparrow_baseline.main`、`sparrow_experiments.run_one` 同源引用（1980−1910=70mm 内部差求解时直接不排，marker 顶部不再落进行程外撞导轨）。密度/理论用布仍按 gate 显示口径计算。PLT 导出内容再按 y≤1910 裁剪属二道防线（削平不缩放）。换机器/换布幅只改 nesting_bounds 一处常量，全部口径自动跟随。

## 已知问题（迁移中未修，勿在文档/迁移中扩大）

1. **`sparrow_baseline.py` 职责混合**：既是 CLI 入口又是共享层（导出 4 个 `_` 前缀私有名给 experiments），未拆 `engine_core.py`。
2. **跨 module 用 `_` 前缀名**：`sparrow_experiments` import `sparrow_baseline` 的 `_clean_polygon` 等 4 个下划线名，违反 Python 约定（应提为公共 API 或合并模块）。
3. **旋转公差未主动实施**：`constraints.MAX_ROTATION_TOL_DEG`（2026-08-17 起全局上限）仅作钳制上界，baseline solver 仍 `{0,180}`；多姿态搜索是后续利用率提升点。
4. **`sparrow_baseline.py:110-112` 占位死代码**：`<text>` 元素 append 后过滤，"占位，避免 linter"。
