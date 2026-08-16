# 业务概览 — 牛仔裤排料引擎

> 项目"是什么、为谁做、到哪一步"的一页速览。需求/方案/规则细节见同目录其它文档；技术实现见 [technical/](../technical/)。
> 权威约束 spec：[排料规则_详细版.md](排料规则_详细版.md)。

## 产品概述

**MaterialSorting** 是一套牛仔裤排料（marker making）引擎与可视化工作台，从 `D:\Pattern_Making` 的排料模块迁移而来，重构为正经 Python 包并与打板模块完全解耦。

**核心目标**：把 M1787 直筒款 **8 码套排**的布料利用率做到 **90%+** —— 版师认可的"行业生死线"。当前 sparrow 基线（600s、`{0,180}`、无 erode）= **85.79%**，距 90% 仍有约 4 个百分点，是后续 v0.3 约束层（旋转公差 + 内片重合）要攻的主目标。

**用户**：版师 / 排料工程师。交付物是可直接裁剪的 marker（PNG 预览 + R12-DXF 给 ET2008 刻绘）。

## 当前状态

| 模块 | 状态 | 说明 |
|------|------|------|
| DXF 解析（dxf_parser） | ✅ 稳定 | 抗住母版 3 怪癖；`collect.py`（US-003）深度解析 5 层 IR（毛版/净版/内部线/刺口/布纹线） |
| 裁片加载（nesting_bounds） | ✅ 稳定 | 单裁片 → 布纹对齐 → 归一化 → L/R 镜像；**US-024 起 5 层透传**（notch 法线按 outline 最近边读时重算）。8 码 → 128 NestPiece / 母版全码 → 176 |
| intermediate 事实源 | ✅ 稳定 | `pieces_intermediate.json`（每片含 polygon + 5 层字段，全流程事实源；US-022 起 label 字段供 demand 编辑） |
| sparrow 基线求解 | ✅ 跑通 | 85.79%（600s `{0,180}` 无 erode） |
| v0.3 约束层 | ⚠️ 部分 | `MAX_OVERLAP`/`ROTATION_TOL` 常量已定 + 校验已写；旋转公差 solver 侧未主动实施 |
| 实验框架（experiments） | ✅ 跑通 | free_rot / v0_rot / erode / erode_rot 四模式 + 多种子方差 |
| 母版上传 → 解析 → commit | ✅ 落地 | `/api/parse-dxf`（US-004）+ `/api/commit-to-nesting`（US-010 Path A）+ `/api/ptypes`（US-020）；解析成功自动 commit + 解锁超排 Tab（US-021） |
| 求解输入 demand | ✅ 落地 | US-022：per-size 数量编辑（qtyStore），0=该码跳过；前端 qtyStore → WS `quantities` |
| 可视化工作台（web） | ✅ 落地 | FastAPI + WS，React 18 + TS 5 + Vite 5 前端（US-001~US-028：Tab 框架 + 上传预览 + 5 层渲染 + 求解停止/重启状态机） |
| 求解停止 / 重启 | ✅ 落地 | US-025 进程化（`solve_with_callback_proc` + `solve_worker`）+ US-026 WS stop 协议 + US-027 phase 五态状态机 + US-028 SolveControls 按钮组 |
| 导出 PNG / R12-DXF / PLT | ✅ 落地 | 用原始母版轮廓，**US-024 起 5 层叠加**（毛版+净版+内部线+刺口+布纹线），ET2008 兼容；**US-033 起 PLT/HPGL**（WT V8.8 / LIKE 绘图仪原生链路，DXF 在该软件实测无法打印） |
| 90% 利用率目标 | 🎯 进行中 | 距 90% 生死线约 4pp，主攻旋转公差 + 内片重合 |

## 核心业务实体

### 片型（10 类）

| 片型 | 配对? | MAX_OVERLAP (mm) | ROTATION_TOL (°) | 说明 |
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

> 配对片（前/后/腰/前袋/后袋/机头）由单裁片镜像展开为 L+R 两份；内片（单排/双排/火机袋/裤耳）单片放置，是利用率提升的"填充料"。

### 码号

`DEFAULT_SIZES = [28, 29, 30, 31, 33, 34, 35, 36]` —— **8 码套排，刻意跳过 32**（版师要求）。8 码 × 配对展开 = 128 个排料单元（NestPiece）。

> **码号口径**：工作台上传母版经 `/api/commit-to-nesting`（US-010）取**母版实际全码**（M1787 = 11 码 [28-38]）→ 176 NestPiece；`DEFAULT_SIZES`（8 码跳 32）仅作 `load_nest_pieces` 默认兜底。前端 SizePicker（US-017）从上传 doc 动态读码号，demand（US-022）按码可设 0 跳过。

### 门幅

`GATE_MM = 1980`（1.98m）—— 布料有效排料宽，不减布边。spyrrow 世界的 Y 轴上限。

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
out/uploads/<doc_id>_pieces/{类型}_{码号}.dxf（母版全码，每片 5 层 US-024）
   ↓ load_pieces（布纹对齐水平 + 归一化原点 + L/R 镜像展开 + 5 层共享 transform）
NestPiece（母版全码 176）
   ↓ server._commit_to_nesting_sync（GROUP_NAMES 定片型 + labeling 标 label）
out/sparrow_baseline/pieces_intermediate.json   ← 全流程事实源（每片 polygon + 5 层 + label）
   ↓
   ├─ ms-sparrow-baseline / ms-sparrow-exp（sparrow 求解 → result/svg/curve）
   └─ ms-web（启动期 _PIECES_STATE 读取 + commit 后 reload + 实时可视化 5 层 + 导出 PNG/R12-DXF/PLT 5 层）
```

详细函数链见 [technical/agent-file-map.md](../technical/agent-file-map.md#数据流主线)。

## 后端架构

四层单向依赖（`web → nesting_engine → nesting_bounds → dxf_parser`），下层禁 import 上层：

- **dxf_parser**：底层 DXF 读写。`reader`（ezdxf recover + GBK + R12 POLYLINE）、`geometry`（纯几何）、`model`（PieceOutline，US-002 扩 5 层字段）、`explore`（母版探索）、`collect`（US-003 母版深度解析 5 层 IR）、`export_dxf`（单裁片 5 层导出）。仅 stdlib + ezdxf。
- **nesting_bounds**：`load_pieces` 把单裁片 → 布纹对齐 → 归一化 → L/R 镜像；US-024 起 `_read_piece_full` 读 5 层 + notch 法线按 outline 最近边重算。定义 `NestPiece`、`GATE_MM=1980`、`DEFAULT_SIZES`。
- **nesting_engine**：sparrow 求解。`constraints`（v0.3 常量 + 位图腐蚀 + 校验）、`sparrow_baseline`（基线 + ★共享层）、`sparrow_experiments`（公差实验）、`labeling`（US-022 共享 A/B/C 标注）。intermediate 由 `web/server._commit_to_nesting_sync` 生成（US-022 label / US-024 5 层）。
- **web**：`server`（FastAPI + WS + 启动期 `_PIECES_STATE` reload + parse/commit/ptypes 路由 + WS stop 协议）、`solver`（build_instance + demand + 旧 threading / **US-025 多进程** `solve_with_callback_proc`）、`solve_worker`（US-025 子进程入口）、`export`（PNG + R12-DXF marker，US-024 起 5 层叠加）。

文件级细节见 [technical/agent-file-map.md](../technical/agent-file-map.md)；HTTP/WS 契约见 [technical/agent-api-reference.md](../technical/agent-api-reference.md)。

## 工作台交互（用户视角）

双 Tab：**上传预览**（默认入口）+ **超排**（未上传母版时锁定，US-015/016）。

1. **上传母版**（上传预览 Tab）：拖拽/点击上传 `.dxf` → `/api/parse-dxf` 深度解析 → 按码分组 + A/B/C 标注 + 5 层（毛版/净版/内部线/刺口/布纹线）预览（US-004~008）。点裁片卡片图形区放大预览（US-013）。
2. **编辑数量**（US-011/022；矩阵化重构 US-001~005 改「裁片 × 尺码」数量矩阵）：QtyMatrix 每行一个裁片、每列一个尺码，全部码数量分布一屏看全；格内直接编辑每码排料份数（0 = 该码不排此片）、行头「填充」整行设默认值、个别格子改不同值高亮为特例；点列头（码号）切换下方该码图形预览；配对片行头「×2」徽章（1 份 = 左右 2 物理片），每码小计/总片数按物理片数计；数量随求解 start payload 按码下发（demand per-size）。
3. **自动应用**（US-021）：解析成功后台自动 `/api/commit-to-nesting` 把母版转 intermediate（全码 176 片）+ reload 后端 + 解锁超排 Tab（不强制切，用户主动点入）。
4. **求解配置**（超排 Tab）：SizePicker 从上传 doc 动态读码号（US-017）+ 总裁片数量实时显示；per-type 高级配置弹窗（重合/旋转，US-018）+ 片型缩略图/放大预览；时长/种子/多 seed（≤6）。
5. **求解**（US-025~028）：点"开始求解"→ WS 推 manifest（5 层骨架）→ 持续推 frame（每 ~0.2s，利用率实时爬升）→ final。**可随时"停止"**（后端 terminate 子进程 → `{type:'stopped'}`）→ stopped 态保留中间方案可导出 → "重新开始"用上次参数一键重跑。phase 五态：idle/running/stopped/done/error。
6. **多 seed 并发对比**（最多 6 路），自动保留最优 run。
7. **回放**：seekbar 拖动看任意时间点布局（US-006）。
8. **导出最优 run** → PNG（预览）/ R12-DXF（给 ET2008 刻绘，5 层叠加 US-024）/ PLT（US-033，给 WT V8.8 / LIKE 绘图仪，封装口径对齐生产 PLT：PS 纸长 + PW0.08 + PU;PG 收尾 + CRLF），文件名 = 上传母版名前缀 + 码号 + 利用率 + 种子（多款号导出凭前缀区分）。

## 关键技术决策

- **DXF 导出走 R12 + POLYLINE**（非 LWPOLYLINE）：ET2008 读 LWPOLYLINE 轮廓会消失。
- **sparrow 不改源码**：作为 pip 包（`spyrrow`）引用，v0.3 服装约束（重合/旋转/布纹线）在外层 `constraints.py` + `solver.build_instance` 包装实现。
- **坐标系**：spyrrow X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上；前端 SVG `scale(1,-1)` 翻转后与 PNG / R12-DXF 一致。
- **多 seed 并发公平性**：`ThreadPoolExecutor(max_workers=6)` 跑 `run_solve`，每 seed 独立子进程（US-025 进程化），seed 间同等 CPU 竞争 → 排名公平。WS stop / 客户端断开 → `Process.terminate()` 可靠终止 Rust 原生 solve（US-026）。
- **前端 React 18 + TS 5 + Vite 5**：Zustand 状态 + 命令式 SVG 渲染（逃逸 React reconciliation 处理高频帧）。不引入 CSS 框架。坐标系 `scale(1,-1)` 必须保留。

## 验收标准（90% 目标的硬指标）

- ✅ `real_density = total_area/(width×gate)` 达到 90%（非 sparrow 自报密度）。
- ✅ commit-to-nesting 生成的 intermediate 含母版全码 NestPiece（M1787 = 176 片）。
- ✅ 导出 DXF 可被 ET2008 正确读出轮廓（R12 + POLYLINE）。
- ✅ 分层依赖未反向（`web→engine→bounds→parser`）。
- ✅ Python 模块可通过 `python -m materialsorting.<sub>.<module>` 跑通。

## 相关文档

- 权威约束：[排料规则_详细版.md](排料规则_详细版.md)
- 后端文件地图：[technical/agent-file-map.md](../technical/agent-file-map.md)
- 前端组件地图：[technical/agent-component-map.md](../technical/agent-component-map.md)
- API/WS 契约：[technical/agent-api-reference.md](../technical/agent-api-reference.md)
- 各阶段规划/方案/反馈：见本目录其余文档
