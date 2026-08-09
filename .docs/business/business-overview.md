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
| DXF 解析（dxf_parser） | ✅ 稳定 | 抗住母版 3 怪癖（recover 元组 / GBK 块名 / `$INSUNITS` 不可信） |
| 裁片加载（nesting_bounds） | ✅ 稳定 | 110 裁片 → 布纹对齐 → 归一化 → L/R 镜像 → 128 NestPiece |
| intermediate 事实源 | ✅ 稳定 | `pieces_intermediate.json`（128 片，全流程事实源） |
| sparrow 基线求解 | ✅ 跑通 | 85.79%（600s `{0,180}` 无 erode） |
| v0.3 约束层 | ⚠️ 部分 | `MAX_OVERLAP`/`ROTATION_TOL` 常量已定 + 校验已写；旋转公差 solver 侧未主动实施 |
| 实验框架（experiments） | ✅ 跑通 | free_rot / v0_rot / erode / erode_rot 四模式 + 多种子方差 |
| 可视化工作台（web） | ✅ 落地 | FastAPI + WS，React 18 + TS 5 + Vite 5 前端（US-001~US-008） |
| 导出 PNG / R12-DXF | ✅ 落地 | 用原始母版轮廓，ET2008 兼容 |
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
data/M1787#...(2).dxf 母版
   ↓ ms-export-dxf（人工 group→类型映射，GROUP_NAMES）
data/m1787_直筒/{类型}_{码号}.dxf（110 片）
   ↓ load_pieces（布纹对齐水平 + 归一化原点 + L/R 镜像展开）
128 NestPiece
   ↓ ms-pieces-export
out/sparrow_baseline/pieces_intermediate.json   ← 全流程事实源
   ↓
   ├─ ms-sparrow-baseline / ms-sparrow-exp（sparrow 求解 → result/svg/curve）
   └─ ms-web（工作台读取 + 实时可视化 + 导出 PNG/R12-DXF）
```

详细函数链见 [technical/agent-file-map.md](../technical/agent-file-map.md#数据流主线)。

## 后端架构

四层单向依赖（`web → nesting_engine → nesting_bounds → dxf_parser`），下层禁 import 上层：

- **dxf_parser**：底层 DXF 读写。`reader`（ezdxf recover + GBK + R12 POLYLINE）、`geometry`（纯几何）、`model`（PieceOutline）、`explore`（母版探索）、`export_dxf`（单裁片导出）。仅 stdlib + ezdxf。
- **nesting_bounds**：`load_pieces` 把单裁片 → 布纹对齐 → 归一化 → L/R 镜像。定义 `NestPiece`、`GATE_MM=1980`、`DEFAULT_SIZES`。
- **nesting_engine**：sparrow 求解。`constraints`（v0.3 常量 + 位图腐蚀 + 校验）、`sparrow_baseline`（基线 + ★共享层）、`sparrow_experiments`（公差实验）、`pieces_export`（生 intermediate）。
- **web**：`server`（FastAPI + WS）、`solver`（build_instance + 子线程求解回调）、`export`（PNG + R12-DXF marker）。

文件级细节见 [technical/agent-file-map.md](../technical/agent-file-map.md)；HTTP/WS 契约见 [technical/agent-api-reference.md](../technical/agent-api-reference.md)。

## 工作台交互（用户视角）

1. 选码号集合（默认全 8 码）+ 时间预算 + 种子。
2. 点"开始"→ WS 推 manifest（128 片骨架）→ 持续推 frame（每 ~0.2s 一个中间解，利用率实时爬升）→ final。
3. 多 seed 并发对比（最多 6 路），自动保留最优 run。
4. 回放：seekbar 拖动看任意时间点布局（US-006）。
5. 导出最优 run → PNG（预览）/ R12-DXF（给 ET2008 刻绘），文件名含码号+利用率+种子。

## 关键技术决策

- **DXF 导出走 R12 + POLYLINE**（非 LWPOLYLINE）：ET2008 读 LWPOLYLINE 轮廓会消失。
- **sparrow 不改源码**：作为 pip 包（`spyrrow`）引用，v0.3 服装约束（重合/旋转/布纹线）在外层 `constraints.py` + `solver.build_instance` 包装实现。
- **坐标系**：spyrrow X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上；前端 SVG `scale(1,-1)` 翻转后与 PNG / R12-DXF 一致。
- **多 seed 并发公平性**：`ThreadPoolExecutor(max_workers=6)`，seed 间同等 CPU 竞争 → 排名公平。
- **前端 React 18 + TS 5 + Vite 5**：Zustand 状态 + 命令式 SVG 渲染（逃逸 React reconciliation 处理高频帧）。不引入 CSS 框架。坐标系 `scale(1,-1)` 必须保留。

## 验收标准（90% 目标的硬指标）

- ✅ `real_density = total_area/(width×gate)` 达到 90%（非 sparrow 自报密度）。
- ✅ `ms-pieces-export` 生成的 intermediate 含 128 个 NestPiece。
- ✅ 导出 DXF 可被 ET2008 正确读出轮廓（R12 + POLYLINE）。
- ✅ 分层依赖未反向（`web→engine→bounds→parser`）。
- ✅ Python 模块可通过 `python -m materialsorting.<sub>.<module>` 跑通。

## 相关文档

- 权威约束：[排料规则_详细版.md](排料规则_详细版.md)
- 后端文件地图：[technical/agent-file-map.md](../technical/agent-file-map.md)
- 前端组件地图：[technical/agent-component-map.md](../technical/agent-component-map.md)
- API/WS 契约：[technical/agent-api-reference.md](../technical/agent-api-reference.md)
- 各阶段规划/方案/反馈：见本目录其余文档
