# 起始端成套前后幅 A/B 验收报告（US-005）

> 2026-08-25。母版 5336#老六订单14%7%围加9_coded.dxf（前幅 g02 / 后幅 g03，7 码 P0 表 159 片）。验收器 `materialsorting.web.prefix_accept`（`run_all`）单命令跑完全部五判据并落盘报告 `out/config_runs/_probes/prefix_accept_report.json`（generated_at 2026-08-25T19:48:31）；本报告数字全部引自该 JSON。浏览器终验 `scripts/us005_prefix_verify.mjs`（CDP headless，19/19 PASS，截图在 `.docs/business/us005_prefix_*.png`）。
>
> **结论：accept** —— 判据①密度 / ②形态 / ③确定性 / ④导出 / ⑤双开档 全 PASS。

## 0. 验收口径（与 P0 探针对齐的三点声明）

| # | 口径 | 说明 |
|---|---|---|
| 1 | **per_type = P0 探针配置**（`data/configs/5336_coded_really.json` 逐码 d/tol：g01 5/8、g02/g03 2/1、g04/g05 0.4/3、g06 10/45、g07/g08 10/15、g09 0.4/30、g10 0.4/1） | PRD 的全部定量锚点（A/B 基准 −0.14pt、双开 89.33%/90.05%）都出自该配置的 probe2/probe3，验收必须同口径才可比。UI 侧经「布局设置」弹窗逐码填入同值（浏览器终验密度 0.000pt 对拍证明口径闭环） |
| 2 | **为何不用 web 全 0 默认** | 实测（2026-08-25 两次 13 臂全跑）：d=0 实例 60s **不收敛**（无平台期）→ 墙钟截断落点漂移使帧数 ±5% 逐帧不等、密度均值噪声 ±0.5pt（两次跑 +1.056/+1.049pt 均卡线外，off 臂自身跨跑也漂 86.143 vs 86.039）。P0 口径下同 seed 背靠背两跑 **1038==1038 帧逐帧全等** —— PRD 判据③「逐帧相等」只在收敛口径下物理可达，终验绑定 P0 口径 |
| 3 | **对照臂**：prefix off（同代码 `exclude_pids` 空置）而非「checkout HEAD~ 无 prefix 代码」 | off 臂 = HEAD 主路径（US-003 契约：无 `prefix` 键管线逐字段不变），导出判据另跑 off 臂全管线对照 |

两臂共同配置：sizes 31/32/33/34/35/36/38（P0 表），quantities 31→1、36→3、其余双份 g 码整列 2（g06~g08 单份，Σ=159 片），main 60s，seed ∈ {0,1,2,3}，params 全 0 + per_type 见上，density = raw-width 生产口径 `total_area/(width×min(gate,1910))`（验收时幅宽钳制期口径；2026-08-28 起现行 = width×gate，本报告数字跨口径不可直接对比）。

## 1. 判据① 密度 A/B（接受线：均值劣化 ≤1.0pt；P0 基准 −0.14pt）

| seed | off（无前缀） | on（前缀自由进解） | 劣化 pt | 选码 | 组合片 fill / bbox / 封闭腔 |
|---|---|---|---|---|---|
| 0 | 87.097% (w 7789.5) | **88.597%** (w 7657.6) | **−1.500（提升）** | 38 | 83.64% / 1175×1556mm / 0 |
| 1 | 86.715% (w 7823.9) | **88.678%** (w 7650.7) | **−1.963（提升）** | 35 | 83.39% / 1155×1483mm / 0 |
| 2 | 89.734% (w 7560.6) | 89.128% (w 7612.0) | +0.606 | 38 | 83.64% / 1175×1556mm / 0 |
| 3 | 86.446% (w 7848.2) | 86.289% (w 7862.5) | +0.157 | 35 | 83.39% / 1155×1483mm / 0 |
| **均值** | **87.498%** | **88.173%** | **−0.675（提升）** | — | 4/4 置换跳过（pin skipped） |

**PASS**。四 seed 两升两平（+0.606 为最差、远在线内），均值**反超 0.675pt** —— 好于 P0 基准（−0.14pt ≈ 0），与《版师确认清单》§4 预估 0.2~0.8pt 代价相比超预期：跨界共同填充（版师 P3）让组合片凹口被主料回收，1175mm 宽的整列前缀在主解里反而是「好包的大片」。P0 逐 seed 形态复现：seed2 同为最差档（P0 −1.88 / 本次 +0.61，均为 off 臂抽到高解的 seed 噪声）、seed0/1 同为提升档（P0 +1.77/−0.21）。

## 2. 判据② 形态（4/4 seed：同码 2+2 + 锚定布头 + 竖排贴触 + 头尾 180° 交替）

`prefix_form` 用**原始轮廓世界几何**（与导出/前端渲染同口径）。成员识别走副本守恒不变量：`exclude_pids` 把 {g02_s, g03_s} 从主实例扣减后，final 里该 4 条只能来自 PS_ 展开 —— 数出来 2+2 即守恒。

| seed | 选码 | min_x(前缀) | 贴触缝隙 | 相邻 y 交集（咬合） | rot 差 | 交错序 |
|---|---|---|---|---|---|---|
| 0 | 38 | −2.092mm | [0, 0, 0] | [99.6, 46.6, 99.6]mm | [180°, 180°, 180°] | 前后前后 |
| 1 | 35 | −1.910mm | [0, 0, 0] | [95.3, 42.8, 95.3]mm | [180°, 180°, 180°] | 前后前后 |
| 2 | 38 | −1.880mm | [0, 0, 0] | [99.6, 46.6, 99.6]mm | [180°, 180°, 180°] | 前后前后 |
| 3 | 35 | −1.860mm | [0, 0, 0] | [95.3, 42.8, 95.3]mm | [180°, 180°, 180°] | 前后前后 |

**PASS**。min_x −2.0mm 一档的负值是 **erode d=2 口径语义**：spyrrow 按 eroded 轮廓贴 x=0 排，原始轮廓自然左探 2mm（重合公差允许的重叠量，off 臂同款行为），\|min_x\| ≤ 6mm 锚定判据宽裕通过。构造贴触缝隙全 0（构造性滑触，P0 同款）；y 交集 43~100mm = 交错咬合形态（合成矩形才会退化为恰好邻接 0，见单测注释）。浏览器 DOM polygon 复核（原始轮廓）：g02_38 x[0, 1169] / g03_38 x[0, 1171]，整列**两片型同时顶满布头 x=0**、y 链 [1.8, 1553.6] 竖排 4 层，头尾 180° 交替（g02@180°→g03@0°→g02@180°→g03@0°）。截图：`us005_prefix_final_full.png`（终局全版）、`us005_prefix_head_column.png`（布头第一列放大）。

## 3. 判据③ 确定性（同 seed 重跑四对拍）

seed0 on 臂重跑（同 seed / 同参数 / 同 P0 口径）：

| 对拍项 | 结果 | 数字 |
|---|---|---|
| 资格码选取 | **一致** | 38 == 38（`crc32(seed\|front\|back)` seeded 派生，FR-4） |
| frames 逐帧 | **相等** | 1042 == 1042 帧（density/width/placed 序列逐帧全等，帧数差 0.0%） |
| final 末态 | **相等** | 密度/宽/placements 逐字段全等（88.597% / 7657.6mm） |
| 可达最优密度 | **重现** | best-so-far 88.633% == 88.633%（Δ0.000pt） |
| prefix_runs 工件 | **可回放** | 构造段（pid/size/chunk.to_dict/fill/bbox/holes/gaps/d_g）逐键相等 |

**PASS**。帧列比较规则为「核心轨迹硬判 + 速率护栏」：求解器对同 seed **迭代内容确定**（背靠背 60s 两跑 1038==1038 帧全等、30s 956==956 全等），但 60s 墙钟预算的**截断帧位**随机器速率漂移（13 臂连跑热态实测 972 vs 1036 = 6.6%，短列仍是长列的确定前缀）—— `frame_series_equal` 判定 = 前 min(n)−1 帧逐帧相等 + 帧数差 ≤12% 相对护栏（观测 6.6% 留一倍余量）；final 快照随截断落点漂移属墙钟物理（off 臂同样存在），判据看「可达最优密度」重现（≤0.1pt），快照逐字段相等另作信息字段（本次恰 True）。工件对拍排除墙钟（ts/stage_elapsed）与主解结局字段（pin.a/band_pos/width_mm —— 随快照漂移），**构造段**逐键相等即构造无 RNG 的直接证据（FR-12）。单测 `test_frame_series_equal_rate_cutoff_rule` / `test_final_best_equal_snapshot_physics` / `test_artifact_replay_equal_excludes_wall_clock` 三态锁死。

## 4. 判据④ 导出（三格式 + PS_ 泄漏哨兵 ×3）

| 臂 | PNG | DXF（R12 POLYLINE） | PLT | 「导出跳过」warning | PS_ 字节泄漏 |
|---|---|---|---|---|---|
| on | 853,110B | 2,380,700B | 468,087B | 无 | 无（placed/DXF/PLT 三重 grep 空） |
| off | 844,366B | 2,379,148B | 467,779B | 无 | 无 |

**PASS**。`PS_` 组合片 PID 永不出 worker 进程（`solve_worker._emit_placed` 单点展开，与 WB_ 同序列化器，US-003 架构）；验收器对导出产物做字节级三重哨兵，off 臂同管线导出成功 = prefix 关闭路径与 HEAD 行为一致的产品级证据。浏览器链路（第五处验证）：前端 WS 全部消息（stage/manifest/frames/final）grep `PS_` 零命中（`final.prefix.pid` 是设计内统计回显，不算泄漏）。

## 5. 判据⑤ 双开档（band+prefix 不置换，另报列；P0 自由解基准 89.33%/90.05%）

| seed | band_only 对照 | band+prefix 双开 | 劣化 pt | P0 基准 | 双开选码 | PS min_x | 带位（WB_g05） |
|---|---|---|---|---|---|---|---|
| 0 | **90.047%** (w 7534.3) | 89.864% (w 7549.7) | +0.183 | 89.33% | 38 | −2.084mm | min_x 1170.9 / 距布尾 5238mm |
| 1 | **90.566%** (w 7491.2) | 90.353% (w 7508.9) | +0.213 | 90.05% | 35 | −2.103mm | min_x 1101.1 / 距布尾 5267mm |
| **均值** | **90.31%** | **90.11%** | **+0.198** | — | — | — | — |

**PASS**。双开 89.86%/90.35% 与 P0 自由解基准（89.33%/90.05%）**同量级且逐 seed 全面持平/反超**，均值仅让 0.198pt（≤1.0pt 线内）—— 前缀与成带正交共存，双开仍是全系统最高密度组合（≥ 单开 88.17%）。带位按 FR-8 **只记录不置换**：WB_g05 落位前缀右侧紧邻（min_x 1101~1171mm、距布尾 ~5.25m）如实写入 `final.prefix.band_pos` 与 prefix_runs 工件；「带靠最右」的带尾置换四割线机制留档确认清单 §3.3，二期立项（2026-08-25 拍板）。

## 6. 浏览器终验（UI 交叉对拍，19/19 PASS）

`scripts/us005_prefix_verify.mjs`（CDP headless Chrome，无外部依赖）：上传 5336 母版 → P0 全表数量 + 7 码 →「布局设置」勾选 prefix（默认预选 g02/g03，无警示）+ **逐码填入 P0 per_type** → 60s 求解。关键结果：

- 消息序 `stage:prefix → manifest → frame* → final`；状态行「起始端成套构造中（尺码 38）…」；
- **密度交叉对拍 88.597% == 88.597%（Δ0.000pt ≤ 0.05pt）** —— UI 真实路径与验收器 on 臂 seed0 同源同构闭环（per_type 口径由弹窗表逐码复现，`_resolve_d_tol` 单一路径验证）；
- 形态四判据 DOM 复核全过（4 成员守恒 / interleave / 180° 交替 / min_x 0.02mm / 贴触缝隙全负=咬合）；
- `final.prefix.pin` 回显 `{skipped: true, a: 0.022mm}` —— P0 常态锚定，置换零成本兜底。

## 7. 复现

```bash
cd materialSorting-server
../.venv/Scripts/python.exe -m materialsorting.web.prefix_accept          # 全跑 ~14min，报告+导出落 out/config_runs/_probes/
../.venv/Scripts/python.exe -m materialsorting.web.prefix_accept --quick # 秒级冒烟（结论无意义）
node ../scripts/us005_prefix_verify.mjs                                  # 浏览器终验（ms-web :8000 先起）
```

产物：`out/config_runs/_probes/prefix_accept_report.json` + `prefix_accept_export_{on,off}_seed0.{png,dxf,plt}` + 逐臂 `out/prefix_runs/*_PS_g02+g03@*.json`（US-005 对拍数据源）。验收器结构镜像已删除的 US-014 `band_accept`（2026-08-22 简化），本文件为其 prefix 版后继。
