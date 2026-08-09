# 排料 DXF 解析架构 · 规划方案 v0.3

> 状态：**已确认，待开工**。
> v0.3 相对 v0.2：新增"按类型分组输出"——程序利用母版 block 结构聚类（block 名 + layer1 序号为分组键），**不做语义命名**；跨码同类裁片归到同一文件夹，由人工重命名文件夹完成识别。
> 独立性：排料专属，**不 import** 项目里 `tools/`、`front_piece/`、`back_piece/` 任何代码。几何算子独立实现。

---

## 1. 目标

在 `material sorting/` 下搭建排料自己的 DXF 解析能力，**忠实地、无遗漏地**把全码母版里**每一个裁片**的毛版几何提取出来，附结构信息（码号、所在 block、布纹线、度量），**按类型分组到文件夹**供人工辨认与命名。

- **要做**：全裁片几何提取（约 110 片/母版）、几何保真、按 group_key 分组输出、可视化人工识别友好。
- **不做**：裁片类型语义识别（程序不赋"前/后/腰"名）、排料算法、镜像副本、去重。
- 类型识别是独立后续任务；排料算法是后续阶段。

## 2. 母版真实结构（实测依据）

以 `data/M1787#直筒14%7%大货围加9）双针30码脚口8英寸(1)(2).dxf` 为样本：

- **格式**：R12/AC1009，几何全部在 BLOCK 定义里，modelspace 只放 INSERT 引用 + 6 个 TEXT。
- **码号**：28-38 共 11 码，等差放码；28-32 / 33-38 是两个放码段。
- **block 组织**：`noname.<类型中文>.<码号>`，共 55 块 = 11 码 × 5 类：
  | block 名模式 | layer1 数 | 备注 |
  |---|---|---|
  | `noname..XX`（类型为空） | 6 | 前/后片 + 4 个小片，bbox 互不重叠 → 6 个独立裁片 |
  | `noname.腰.XX` | 1 | 随码递增 |
  | `noname.双.XX` | 1 | 每码几何相同（固定片） |
  | `noname.单.XX` | 1 | 每码几何相同（固定片） |
  | `noname.M1787#28-32小33-38大码.XX` | 1 | 33 起跳变 |
- **每码裁片数 = 10**，11 码 ≈ **110 个裁片轮廓**（以实测为准，不去重）。
- **裁片定义**：一条 layer1（毛版层）闭合 POLYLINE = 一个裁片的外轮廓。
- **图层语义**：`1`=毛版外轮廓（**提取目标**）、`14`=净版（本阶段不提）、`3`=剪口(POINT)、`7`=**布纹线(LINE，每片一条，方向因裁片而异)**、`2/4/8/13`=辅助/工艺。
- **布纹线**：layer7 的水平 LINE，每片 1 条，排料旋转基准。
- **单位坑**：`$INSUNITS=6`（不可信），实测 mm。
- **编码坑**：`$DWGCODEPAGE=ANSI_1252`，块名实际 GBK，需 GBK 解码。
- **缩水**：文件名 `14%7%`，几何已含补偿，只读不重算。

## 3. 目录结构

```
material sorting/
  排料规则.md
  排料规则_详细版.md
  排料DXF解析架构_方案.md          ← 本文档
  dxf_parser/                      ← 排料专属解析包（新建）
    __init__.py
    reader.py        # 底层读取：recover 回退、GBK 块名解码、单位判定(mm)、遍历 block 定义
    geometry.py      # 几何算子(独立实现)：poly_pts / 闭合判定 / 周长 / 面积 / bbox / 布纹线中点配对
    model.py         # IR dataclass：PieceOutline
    explore.py       # 探索 CLI：提取所有裁片 → 按 group_key 分组到文件夹 + 摘要 csv + 总览 SVG
  _output/                         # 探索产出，加入 .gitignore
```

**职责边界**（4 文件）：
- `reader.py`：把 DXF 读成可信的实体集合，扛住 recover/编码/单位三个坑；遍历所有 block 定义。
- `geometry.py`：对多边形算度量 + 布纹线配对，纯几何不碰 DXF，可单测。
- `model.py`：数据结构。
- `explore.py`：CLI 消费者，串起来产出分组可视化。

## 4. IR（全裁片、无类型）

```python
@dataclass
class PieceOutline:
    source_file: str
    block_name_raw: str                                # block 原始名
    block_name: str                                    # GBK 解码后块名
    size: int | None                                   # 码号（块名末尾数字；提取失败为 None）
    piece_index: int                                   # 该 block 内第几条 layer1（0-based）
    group_key: str                                     # 分组键 = 去码号的block名 + "#" + piece_index
    polygon_mm: list[tuple[float, float]]              # layer1 毛版外轮廓顶点(mm)，原样保留
    is_closed: bool                                    # POLYLINE 闭合标志
    vertex_count: int
    perimeter_mm: float
    area_mm2: float
    bbox_mm: tuple[float, float, float, float]         # (minx,miny,maxx,maxy)
    grain_line: tuple[float, float, float, float] | None  # 配对到的布纹线起止(x1,y1,x2,y2)
    grain_angle_deg: float | None                      # 布纹线与水平夹角(度)
    grain_orientation: str                             # 'horizontal' | 'vertical'，排料统一水平时的旋转依据
    # piece_type: str  ← 故意不加，等独立识别程序
```

## 5. 提取逻辑（忠实、无遗漏）

1. **遍历所有 block 定义**（非匿名 `*` 块），跳过 modelspace 的 INSERT（INSERT 只是摆放，裁片形状在 block 内坐标）。
2. 每个 block 内取**所有 layer1 的 POLYLINE**，每条 → 一个 `PieceOutline`：
   - `polygon_mm` = POLYLINE 的 `.vertices` 顶点（**原样保留，不抽稀、不合并、不平滑**）。
   - `is_closed` = POLYLINE 闭合标志（`flags & 1`）。
   - `piece_index` = 该 block 内 layer1 的顺序号。
3. **码号**：block 名末尾数字（正则 `[._](\d+)$`，只取末尾，避开 `M1787#28-32...` 中的数字），失败置 None。
4. **分组键**：`group_key = <去码号的block名>#<piece_index>`。
   例：`noname..28` idx0 与 `noname..29` idx0 同键 → 归一组（跨码同结构位置）。
   主片 block 6 个 idx → 6 组；腰/双/单/机头各 1 组 → **共 10 组，每组 11 码**。
5. **布纹线配对**：block 内取所有 layer7 LINE，按"LINE 中点落在哪个 layer1 多边形内"配给该片。布纹线方向因裁片而异（多数水平，机头/腰为竖直），用 `grain_orientation` 标准化为 horizontal/vertical——排料时 vertical 片旋转 90° 统一水平。
6. **去重/类型识别：一律不做**，原样保留 110 条，仅按 group_key 归类输出。

## 6. 已知坑的处理

| 坑 | 处理 |
|---|---|
| `ezdxf.recover.readfile` 返回 `(doc, errors)` 元组 | reader 正确解包；失败回退 `ezdxf.readfile` |
| 块名 GBK 被 `$DWGCODEPAGE=ANSI_1252` 误标 | reader 用 GBK 解码块名/文字，失败回退原值 |
| `$INSUNITS=6` 不可信 | 固定按 mm 解释（实测），探索输出附 cm/cm² 辅助 |
| POLYLINE 闭合标志 / 顶点顺序 | 记录 `is_closed`；面积取绝对值；顶点保持原始顺序不翻转（保真优先） |
| 相邻重复点 / 退化边 | 仅告警，不删点（保真优先） |
| R12 无 LWPOLYLINE/SPLINE/ARC | 只处理 POLYLINE（顶点在 `.vertices`）+ LINE |

## 7. 探索产出（按类型分组、人工识别友好）

`explore.py` 读母版后，**按 group_key 分组**，每组一个文件夹，落到 `_output/`：

```
_output/
  g00_noname__idx0/          # 主片 idx0（11 码）；文件夹名=编号_block名_idx，可人工重命名
    28.svg 29.svg ... 38.svg # 每码一片的 SVG（含布纹线、标注 area/perim）
    pieces.json              # 该组 11 码的 PieceOutline
  g01_noname__idx1/          # 主片 idx1
  g02_noname__idx2/ ... g05_noname__idx5/   # 4 个小片组
  g06_腰__idx0/
  g07_双__idx0/
  g08_单__idx0/
  g09_机头__idx0/
  _overview.svg              # 全裁片总览（按 block 配色叠合）
  _all_pieces.csv            # 全量摘要表（110 行）
```

1. **每组文件夹**：同 group_key 的所有码归此（跨码同结构位置 = 同一类）。文件夹内每码一个 SVG + 该组 JSON。**用户可直接重命名文件夹**（`g00_...` → `后片`）即完成人工识别。
2. **_all_pieces.csv**：全 110 片摘要 `group_key|block_name|size|idx|closed|verts|peri(cm)|area(cm²)|bbox|grain°`。
3. **_overview.svg**：所有裁片按 block 配色叠合总览。

> 分组依据是母版现成的 block 结构 + layer1 序号，**不是语义识别**——程序不知道"g00 是后片"，只把跨码同结构位置的裁片归一起。语义命名由人工重命名文件夹完成。

## 8. 第一阶段完成的判据（验证标准）

- [ ] 从 M1787 母版提取 **约 110 个裁片**（11 码 × 约 10 片），无遗漏、无重复
- [ ] 每片 `polygon_mm` 顶点数 = 原始 POLYLINE 顶点数（保真，不抽稀不合并）
- [ ] `is_closed` 正确反映 POLYLINE 闭合标志
- [ ] **分组正确**：10 组，每组 11 码；跨码同 idx 归同组
- [ ] 主片 block 的前后片 area 落在实测区间（后≈2894-3651 / 前≈2236-2965 cm²）
- [ ] 放码片（前后片/腰/机头）面积随码单调递增；固定片（单/双）面积恒定
- [ ] 布纹线：110 片全部配到；多数 horizontal(≈0°)，机头/腰 vertical(-90°)，中点配对正确
- [ ] SVG 分组清晰，人工能辨认每片归属
- [ ] 换码号母版（同目录 `(1)(1).dxf`）同样跑通

## 9. 已确认决策 + 剩余风险

**已确认决策**：
1. 裁片定义：layer1（毛版）闭合多边形 = 一个裁片；不提取 layer14 净版。
2. 款型范围：第一阶段只 M1787 一个母版。
3. 布纹线配对：按"中点落在哪片多边形内"配对到片。
4. 几何保真：顶点完全原样保留，不合并重合点。
5. 输出分组：按 group_key（去码号 block 名 + layer1 序号）分组到文件夹，跨码同类归一起。
6. 布纹线方向：如实提取 layer7 布纹线角度，`grain_orientation` 标准化（horizontal/vertical）；机头/腰=vertical，排料时旋转 90° 统一水平。

**剩余风险（跨款型时复核）**：
- 其它款型（`5015#...`、`GSP07A...`、`松紧直筒...`）block 名规律、layer 分布可能不同 → reader 的 block 遍历通用，"码号正则/布纹线图层/分组键"做成可配置常量，第一阶段硬编码 M1787 实测值。
- "一条 layer1 = 一个裁片"假设换款型需复核 → 探索输出让人工抽检。
- 布纹线"水平=经向"假设需版师确认（不阻塞编码，影响后续排料姿态）。

## 10. 依赖

- `ezdxf`（项目已用，无版本锁定；本阶段沿用，不新增依赖）
- 标准库：`math / dataclasses / re / json / pathlib / argparse / csv`
- **不依赖**项目内任何其它 Python 模块

## 11. 工作量预估

4 个文件、约 350-450 行（含注释）。第一阶段聚焦全裁片提取 + 分组可视化，预计一次提交完成主体 + 用 M1787 验证判据通过。
