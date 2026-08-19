# 业务概览 — 牛仔裤排料引擎

> 项目"是什么、为谁做、到哪一步"的一页速览。需求/方案/规则细节见同目录其它文档；技术实现见 [technical/](../technical/)。
> 权威约束 spec：[排料规则_详细版.md](排料规则_详细版.md)。

## 产品概述

**MaterialSorting** 是一套牛仔裤排料（marker making）引擎与可视化工作台，从 `D:\Pattern_Making` 的排料模块迁移而来，重构为正经 Python 包并与打板模块完全解耦。

**核心目标**：把 M1787 直筒款套排的布料利用率做到 **90%+** —— 版师认可的"行业生死线"。**当前对拍基线（US-005，2026-08-18）**：110 片（母版全码 g01–g10 × 11 码、全 demand=1、无合成镜像）600s `{0,180}` 无 erode seed 0 → **real 85.59%**（原面积口径 `total_area/(width×1980)`，用布 5459.4mm；sparrow 自报 88.72% 是 1910 约束带口径）。旧基线 85.79%（176 片、含 L/R 合成镜像，实例口径已废）**归档不再对拍**。距 90% 仍有约 4 个百分点，是后续 v0.3 约束层（旋转公差 + 内片重合）要攻的主目标。

**用户**：版师 / 排料工程师。交付物是可直接裁剪的 marker（PNG 预览 + R12-DXF 给 ET2008 刻绘）。

## 当前状态

| 模块 | 状态 | 说明 |
|------|------|------|
| DXF 解析（dxf_parser） | ✅ 稳定 | 抗住母版 3 怪癖；`collect.py`（US-003）深度解析 5 层 IR（毛版/净版/内部线/刺口/布纹线） |
| 裁片加载（nesting_bounds） | ✅ 稳定 | manifest 驱动：单裁片 → 布纹对齐 → 归一化（**US-001 v2 起无 L/R 镜像展开，引擎不合成任何片**）；**US-024 起 5 层透传**（notch 法线按 outline 最近边读时重算）。母版全码 → 110 NestPiece（M1787 = 10 片 × 11 码） |
| intermediate 事实源 | ✅ 稳定 | `pieces_intermediate.json`（schema v2：每片 polygon + 5 层 + label（g 码），无 ptype/side；全流程事实源，US-022 起 label 字段供 demand 编辑） |
| sparrow 基线求解 | ✅ 跑通 | **新基线 85.59%**（US-005：110 片全 demand=1，600s `{0,180}` 无 erode seed 0，real 口径）；旧 85.79%（176 片含合成镜像）已归档 |
| v0.3 约束层 | ⚠️ 部分 | 2026-08-17 起重合/旋转改**全局上限**（`MAX_OVERLAP_MM=10` / `MAX_ROTATION_TOL_DEG=45`，每片型钳制表已删，版师按片型的工艺参考值留在排料规则文档）+ 校验已写；旋转公差 solver 侧未主动实施 |
| 实验框架（experiments） | ✅ 跑通 | free_rot / v0_rot / erode / erode_rot 四模式 + 多种子方差 |
| 母版上传 → 解析 → commit | ✅ 落地 | `/api/parse-dxf`（US-004）+ `/api/commit-to-nesting`（US-010 Path A）+ `/api/ptypes`（US-020）；解析成功自动 commit + 解锁超排 Tab（US-021） |
| 求解输入 demand | ✅ 落地 | US-022：per-size 数量编辑（qtyStore），0=该码跳过；前端 qtyStore → WS `quantities` |
| 可视化工作台（web） | ✅ 落地 | FastAPI + WS，React 18 + TS 5 + Vite 5 前端（US-001~US-028：Tab 框架 + 上传预览 + 5 层渲染 + 求解停止/重启状态机） |
| 求解停止 / 重启 | ✅ 落地 | US-025 进程化（`solve_with_callback_proc` + `solve_worker`）+ US-026 WS stop 协议 + US-027 phase 五态状态机 + US-028 SolveControls 按钮组 |
| 导出 PNG / R12-DXF / PLT | ✅ 落地 | 用原始母版轮廓，**US-024 起 5 层叠加**（毛版+净版+内部线+刺口+布纹线），ET2008 兼容；**US-033 起 PLT/HPGL**（WT V8.8 / LIKE 绘图仪原生链路，DXF 在该软件实测无法打印）；**2026-08 撞机修正**：PLT 内容压进绘图仪 Y 可写幅宽 1910 + PD 分块 ≤10点/≤110B + 走纸引导（设备级差异详见 [technical/agent-api-reference.md](../technical/agent-api-reference.md)） |
| 配置驱动求解 CLI（cli 子包） | ✅ 落地 | 2026-08-19：`ms-run-config <config.json>`（7 键配置：master_dxf/gate_mm 必填 + sizes/time/seeds/per_type/quantities）→ 独立 commit → **串行**多 seed 求解 + best 汇总（real 口径）；产物只落 `out/config_runs/<run>_<时间戳>/`（pieces/ + intermediate + result.json + curve_s\*/best_frame_s\* 逐帧轨迹），物理隔离 web 事实源，与 ms-web 可并行互不干扰，无需浏览器。**PC-001（2026-08-19）起求解进程化**：`solve_pieces` 走多进程 + 逐帧 `should_stop` 中止（terminate 杀子进程、best-so-far 帧交付）+ `curve_s{seed}.json`/`best_frame_s{seed}.json` 落盘（标定/kill 规则数据源），Ctrl-C（退出码 130）不丢已完成轮。**PC-002（2026-08-19）起串行 seed portfolio 控制器**（`cli/portfolio.py`）：逐帧 incumbent banking（`best` 升级为帧级全局最优、含完整布局，被 kill/中断 seed 的最优帧同样参与）+ R0 达标即停（`--target`，任一帧达标 → 当前 seed 被 stop + 剩余队列不启动，退出码 0）+ R4 队列耗尽交付；result.json 新增 `portfolio` 段；`--params` 标定参数文件旗标（PC-003/004 消费）；单 seed 无 `--target` 保持旧 best 语义（冒烟对拍兼容） |
| 母版编号植入脚本 | ✅ 可用 | 2026-08-18：`python scripts/embed_piece_codes.py <母版.dxf>` 把 g01+ 编号 TEXT 植入母版（与 Web parse 同源 `assign_codes`，幂等 + 自校验）—— 版师在 ET2008 打开母版即可把图面片对上 g 码；`_coded.dxf` 产物可直接再上传 Web，g 码不变 |
| 90% 利用率目标 | 🎯 进行中 | 距 90% 生死线约 4pp，主攻旋转公差 + 内片重合 |

## 核心业务实体

### 片型（10 类）

> **口径注记（US-005，2026-08-18）**：本表是**版师工艺参考表**，不是代码数据模型 —— 现行实现中片型中文名（GROUP_NAMES/PAIR_TYPES/INTERNAL_TYPES）已全部删除，代码/界面/导出对单片一律用 **g 码**（g01+，单一真相源 `nesting_engine/labeling.py`）标识；「配对?」「重合/旋转参考值」列仅为工艺范围参考（求解钳制是全局上限，见下注）。M1787 每码 10 片 = g01..g10（跨码同号同片型，由母版 block 编号复用/几何稳定排序保证）。

| 片型（工艺参考名） | 配对? | 重合参考值 (mm) | 旋转参考值 (°) | 说明 |
|------|------|------------------|------------------|------|
| 前片 | L+R | 2.0 | 1 | 主片，严格布纹 |
| 后片 | L+R | 2.0 | 1 | 主片，严格布纹 |
| 腰 | L+R | 0.4 | 3 | |
| 前袋 | L+R | 0.4 | 30 | 允许较大旋转 |
| 后袋 | L+R | 0.4 | 1 | |
| 机头 | L+R | 0.4 | 3 | |
| 单排 | 单片 | 10.0 | 15 | 内片，可重合可旋 |
| 双排 | 单片 | 10.0 | 15 | 内片 |
| 火机袋 | 单片 | 5.0 | 8 | 内片 |
| 裤耳 | 单片 | 10.0 | 45 | 内片，几乎任意角 |

> **2026-08-17 起本表降为版师参考值**：求解钳制不再按片型 —— 后端全局上限 `MAX_OVERLAP_MM=10` / `MAX_ROTATION_TOL_DEG=45`（`constraints.py`），用户在高级配置弹窗按 g 码逐片显式填 0–10mm / 0–45°（默认 0 = 不重合 / 锁布纹线；2026-08-18 回退 US-004 矩阵化后不再按码号细分），solver 按 `min(申请值, 全局上限)` 收边。上表数值作为各片型工艺合理范围的参考保留。

> **引擎不合成镜像（US-001 v2 起，数量即一切）**：旧口径"配对片由单裁片镜像展开为 L+R 两份"已删除 —— 引擎对母版轮廓零合成、零丢弃（WYSIWYG：母版 N 个轮廓 → intermediate N 条 NestPiece）。要排左右两片就在数量矩阵把该（g 码 × 码号）数量填 2；母版本身自带左右两片轮廓的（如 M1787），两片各自有独立 g 码。内片（单排/双排/火机袋/裤耳等小片）仍是利用率提升的"填充料"。

### 码号

`DEFAULT_SIZES = [28, 29, 30, 31, 33, 34, 35, 36]` —— 8 码套排（刻意跳过 32，版师要求），仅作 `load_nest_pieces` 默认兜底，**不是现行排料口径**。

> **码号口径（US-001 v2 起）**：工作台上传母版经 `/api/commit-to-nesting`（US-010）取**母版实际全码**（M1787 = 11 码 [28-38]）→ **110 NestPiece**（每码 10 片 × 11 码；= 母版 size≠None 轮廓数，无镜像合成）。前端 SizePicker（US-017）从上传 doc 动态读码号，demand（US-022）按码可设 0 跳过、按（g 码 × 码号）可设 N 份。

### 门幅（双口径，2026-08 绘图仪撞机修正后解耦）

| 常量 | 值 | 口径 |
|------|-----|------|
| `GATE_MM` | 1980 | **布幅显示口径**：UI / 密度分母 / PNG·DXF·PLT 外框 / WS manifest `gate_mm`。不减布边 |
| `PLOT_SAFE_MAX_Y_MM` | 1910 | **绘图仪 Y 可写幅宽**（LIKE + WT「高速网口输出中心 V8.8」现场口径）。旧口径把门幅框画到 1980、顶部刺口伸到 1983.9mm，Y 超程小车撞导轨硬限位 —— 2026-08 现场撞机根因 |
| `NEST_GATE_MM` | min(两者)=1910 | **求解约束带**（spyrrow strip 高度上限）：1980−1910=70mm 内部差求解时直接不排。web/solver 与 CLI 引擎（baseline/experiments）同源引用 |

三常量单一事实源在 `nesting_bounds/load_pieces.py`，换机器/换布幅只改一处。PLT 导出内容再按 y≤1910 裁剪属二道防线（削平不缩放）。

### 利用率（双口径，关键）

| 口径 | 公式 | 用途 |
|------|------|------|
| **real（原面积）** | `total_area / (width × gate)` | ★ 90% 生死线判定；导出为 `density`；版师口径 |
| sparrow（erode 后） | spyrrow 自报 | 仅参考，偏低（erode 缩小了分子） |

**任何对版师的汇报、前端显示、目标判定都用 real 口径。**

## 数据流主线

```
用户上传母版 DXF
   ↓ /api/parse-dxf + /api/commit-to-nesting（US-004/010）
out/uploads/<doc_id>_pieces/{g码}_{码号}.dxf + pieces_manifest.json sidecar（母版全码，每片 5 层 US-024）
   ↓ load_nest_pieces（manifest 驱动：布纹对齐水平 + 归一化原点 + 5 层共享 transform，无镜像展开）
NestPiece（母版全码 110 = 母版 size≠None 轮廓数，WYSIWYG）
   ↓ server._commit_to_nesting_sync（labeling.assign_codes 最先赋 g 码，名称无关、零丢片零合成）
out/sparrow_baseline/pieces_intermediate.json   ← 全流程事实源（schema v2：每片 polygon + 5 层 + label，无 ptype/side）
   ↓
   ├─ ms-sparrow-baseline / ms-sparrow-exp（sparrow 求解 → result/svg/curve）
   └─ ms-web（启动期 _PIECES_STATE 读取 + commit 后 reload + 实时可视化 5 层 + 导出 PNG/R12-DXF/PLT 5 层）
```

> **CLI 平行通道**（2026-08-19）：`ms-run-config <config.json>` 从 `data/configs/` 7 键配置出发，走同一编排链独立 commit 到 `out/config_runs/<run>_<时间戳>/` 再串行多 seed 求解 —— **不经上述 web 事实源**（不写 `out/sparrow_baseline/` 与 `out/uploads/`），可与 ms-web 并行互不干扰。

详细函数链见 [technical/agent-file-map.md](../technical/agent-file-map.md#数据流主线)。

## 后端架构

五层单向依赖（`cli → web → nesting_engine → nesting_bounds → dxf_parser`），下层禁 import 上层：

- **cli**：最上层编排者（2026-08-19 新增）。`config`（7 键 JSON 严格校验，中文报错含字段名）、`pipeline`（commit 管线镜像 `server._commit_to_nesting_sync` + `solve_pieces` 求解封装：复用 `web.solver.build_instance` 与 web 同代码路径；PC-001 起多进程求解 + 逐帧 `should_stop` 中止 + curve/best_frame 落盘）、`portfolio`（PC-002 串行 seed 控制器：incumbent banking + R0 达标即停 + R4 队列耗尽）、`run_config`（`ms-run-config` 入口：逐 seeds 经控制器串行多轮 + best/portfolio 汇总，result.json 逐轮重写，`--target`/`--params` 旗标）；绝不 import `web.server`，产物只落 `out/config_runs/`。
- **dxf_parser**：底层 DXF 读写。`reader`（ezdxf recover + GBK + R12 POLYLINE）、`geometry`（纯几何）、`model`（PieceOutline，US-002 扩 5 层字段）、`explore`（母版探索）、`collect`（US-003 母版深度解析 5 层 IR）、`export_dxf`（单裁片 5 层导出）。仅 stdlib + ezdxf。
- **nesting_bounds**：`load_pieces` 把单裁片 → 布纹对齐 → 归一化（US-001 v2 起 manifest 驱动、无 L/R 镜像展开）；US-024 起 `_read_piece` 读 5 层 + notch 法线按 outline 最近边重算。定义 `NestPiece`、`GATE_MM=1980`、`DEFAULT_SIZES`。
- **nesting_engine**：sparrow 求解。`constraints`（v0.3 常量 + 位图腐蚀 + 校验）、`sparrow_baseline`（基线 + ★共享层）、`sparrow_experiments`（公差实验）、`labeling`（**g 码赋号单一真相源**，US-001 v2：assign_codes + 母版编号复用，无名称映射）。intermediate 由 `web/server._commit_to_nesting_sync` 生成（US-001 v2 label 先行 / US-024 5 层，schema v2）。
- **web**：`server`（FastAPI + WS + 启动期 `_PIECES_STATE` reload + parse/commit/ptypes 路由 + WS stop 协议）、`solver`（build_instance + demand + 旧 threading / **US-025 多进程** `solve_with_callback_proc`）、`solve_worker`（US-025 子进程入口）、`export`（PNG + R12-DXF marker，US-024 起 5 层叠加）。

文件级细节见 [technical/agent-file-map.md](../technical/agent-file-map.md)；HTTP/WS 契约见 [technical/agent-api-reference.md](../technical/agent-api-reference.md)。

## 工作台交互（用户视角）

双 Tab：**上传预览**（默认入口）+ **超排**（未上传母版时锁定，US-015/016）。

1. **上传母版**（上传预览 Tab）：拖拽/点击上传 `.dxf` → `/api/parse-dxf` 深度解析 → 按码分组 + **g 码标注**（g01+，`labeling.py` 单一真相源，无中文名）+ 5 层（毛版/净版/内部线/刺口/布纹线）数据（US-004~008；裁片编号化 US-001~005）。
2. **编辑数量**（US-011/022；矩阵化重构 + 裁片编号化后 =「码号 × g 码」数量矩阵；图形预览区已拆除）：QtyMatrix 行 = 码号、列 = g 码（列头缩略图 + 序号徽章 + 「≡」整列设值），全部码数量分布一屏看全；格内直接编辑每（g 码 × 码号）排料份数（0 = 该码不排此片）、「≡」整列设统一值（个别码不同 = 应用后单格再改，高亮为特例）；点列头缩略图放大查看裁片图形（US-013 PieceZoomModal，5 层）、点行头（码号）切换列头缩略图显示的码；每码小计/底部合计/总片数 = **Σ 数量口径**（一份 = 母版一个轮廓，引擎不合成镜像）；数量随求解 start payload 按（g 码 × 码号）下发（demand per-size）。
3. **自动应用**（US-021）：解析成功后台自动 `/api/commit-to-nesting` 把母版转 intermediate（母版全码 110 片，无合成）+ reload 后端 + 解锁超排 Tab（不强制切，用户主动点入）。
4. **求解配置**（超排 Tab）：SizePicker 从上传 doc 动态读码号（US-017）+ 总裁片数量实时显示（Σ 数量口径）；高级配置弹窗（重合/旋转，US-018；按 g 码逐片 d/tol —— 2026-08-18 回退 US-004 码号矩阵化）+ g 码缩略图/放大预览；时长/种子/多 seed（≤6）。
5. **求解**（US-025~028）：点"开始求解"→ WS 推 manifest（5 层骨架）→ 持续推 frame（每 ~0.2s，利用率实时爬升）→ final。**可随时"停止"**（后端 terminate 子进程 → `{type:'stopped'}`）→ stopped 态保留中间方案可导出 → "重新开始"用上次参数一键重跑。phase 五态：idle/running/stopped/done/error。
6. **多 seed 并发对比**（最多 6 路），自动保留最优 run。
7. **回放**：seekbar 拖动看任意时间点布局（US-006）。
8. **导出最优 run** → PNG（预览）/ R12-DXF（给 ET2008 刻绘，5 层叠加 US-024）/ PLT（US-033，给 WT V8.8 / LIKE 绘图仪，封装口径对齐生产 PLT：PS 纸长 + PW0.08 + PU;PG 收尾 + CRLF；内容压进绘图仪可写幅宽 1910 + PD 分块 ≤10点/≤110B + 走纸引导），文件名 = 上传母版名前缀 + 码号 + 利用率 + 种子（多款号导出凭前缀区分）。

## 关键技术决策

- **DXF 导出走 R12 + POLYLINE**（非 LWPOLYLINE）：ET2008 读 LWPOLYLINE 轮廓会消失。
- **sparrow 不改源码**：作为 pip 包（`spyrrow`）引用，v0.3 服装约束（重合/旋转/布纹线）在外层 `constraints.py` + `solver.build_instance` 包装实现。
- **坐标系**：spyrrow X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上；前端 SVG `scale(1,-1)` 翻转后与 PNG / R12-DXF 一致。
- **多 seed 并发公平性**：`ThreadPoolExecutor(max_workers=6)` 跑 `run_solve`，每 seed 独立子进程（US-025 进程化），seed 间同等 CPU 竞争 → 排名公平。WS stop / 客户端断开 → `Process.terminate()` 可靠终止 Rust 原生 solve（US-026）。
- **前端 React 18 + TS 5 + Vite 5**：Zustand 状态 + 命令式 SVG 渲染（逃逸 React reconciliation 处理高频帧）。不引入 CSS 框架。坐标系 `scale(1,-1)` 必须保留。

## 验收标准（90% 目标的硬指标）

- ✅ `real_density = total_area/(width×gate)` 达到 90%（非 sparrow 自报密度）。
- ✅ commit-to-nesting 生成的 intermediate 含母版全码 NestPiece（M1787 = 110 片 = 母版 size≠None 轮廓数，无镜像合成；每片 label = g 码）。
- ✅ 基线对拍（US-005）：同 seed（0）重跑 110 片基线 density 一致；新基线 **real 85.59%** 记录在案（旧 176 片/85.79% 基线随镜像概念归档，不再对拍）。
- ✅ 导出 DXF 可被 ET2008 正确读出轮廓（R12 + POLYLINE）。
- ✅ 分层依赖未反向（`web→engine→bounds→parser`）。
- ✅ Python 模块可通过 `python -m materialsorting.<sub>.<module>` 跑通。

## 相关文档

- 权威约束：[排料规则_详细版.md](排料规则_详细版.md)
- 后端文件地图：[technical/agent-file-map.md](../technical/agent-file-map.md)
- 前端组件地图：[technical/agent-component-map.md](../technical/agent-component-map.md)
- API/WS 契约：[technical/agent-api-reference.md](../technical/agent-api-reference.md)
- 各阶段规划/方案/反馈：见本目录其余文档
