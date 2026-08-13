# PRD: 排料结果 PLT（HPGL/HP-GL/2）格式导出

## 概述 (Overview)

为排料结果新增 **PLT/HPGL** 格式导出，与现有 PNG / R12-DXF 平行。后端新增 `write_marker_plt()` HPGL 生成器，复用 `placed_to_world()` 几何数据源（保证三种格式同口径）；`/export` 路由加 `fmt=='plt'` 分支；前端导出下拉框加 PLT 选项。

目标驱动设备：现场 LIKE 牌「惠普兼容喷头」服装绘图仪，经 WT「高速绘图 V8.8 网络版」软件驱动。该软件原生吃 PLT/HPGL（ET 排料软件输出的就是 PLT），DXF 仅是 2024 年才补的辅助功能。**已实测现有 DXF 导出在该软件上无法正常打印**，故必须新增 PLT 导出，与 ET 同口径走原生 PLT 链路。

## 目标 (Goals)

- 排料结果可导出为合法 HPGL/PLT 文本，能被 WT V8.8 软件 + LIKE 绘图仪识别并 1:1 打印。
- PLT 导出与 PNG / DXF 共享同一几何数据源 `placed_to_world()`，三种格式几何口径完全一致。
- 5 层全量导出（毛版裁切轮廓 + 净版 + 内部线 + 刺口 + 布纹线 + 门幅框），用 HPGL 笔号（SP）区分，满足裁床裁切 + 缝制参考的生产刚需。
- 现有 PNG / DXF 导出零回归，前后端单测全绿，TS 构建通过。

## 用户故事 (User Stories)

### US-033: 后端 PLT/HPGL 导出（生成器 + /export 路由分支 + 单测）
- **Description**: As a 排料引擎开发者, I want a `write_marker_plt()` function that converts placed world pieces to HPGL/PLT text, and a `/export` route branch that serves it, so that 排料结果可输出给 LIKE 绘图仪 / WT V8.8 软件的原生 PLT 链路. 涉及文件：`materialSorting-server/src/materialsorting/web/export.py`（新增 `write_marker_plt()` + HPGL 常量）、`materialSorting-server/src/materialsorting/web/server.py`（import + `/export` 路由 `elif fmt=='plt'` 分支）、`materialSorting-server/tests/test_export_plt.py`（新建单测）。
- **Acceptance Criteria**:
  1. `export.py` 新增 `write_marker_plt(world_pieces, *, width_mm: float, gate_mm: float, title: str) -> bytes`，签名与 `write_marker_dxf` 对齐；模块顶部新增 HPGL 常量：缩放因子 `_PLT_SCALE = 40`（1mm=40 绘图单位）、笔号 `_PEN_OUTLINE=1/_PEN_NET=2/_PEN_INTERNAL=3/_PEN_NOTCH=4/_PEN_GRAIN=5/_PEN_BORDER=6`、速度常量 `_PLT_VELOCITY=80`。
  2. 输出首条指令为 `IN;`（Initialize），含 `VS80;`（或 `_PLT_VELOCITY`）速度设置。
  3. 坐标缩放正确：裁片/门幅框的世界坐标(mm) `× 40` 后 `round` 取整（输入 100.0mm → 输出 4000）；HPGL 坐标为非负整数。
  4. 门幅边框（SP6）一组 `PU`+`PD` 画出闭合矩形，PD 含四角 `(0,0) (width×40,0) (width×40,gate×40) (0,gate×40)` 并回到 `(0,0)`。
  5. 逐片毛版 polygon（SP1）：每组为 `PU x0,y0;`（抬笔到首点）+ `PD x1,y1,...,xN,x0,y0;`（落笔画完所有边，**首尾点相同保证物理闭合**，与 DXF 闭合策略一致）。
  6. 5 层各有独立笔号（有数据时）：SP1=毛版 polygon / SP2=净版 net_polygon（闭合）/ SP3=内部线 internal_lines（逐条不闭合）/ SP4=刺口 notches（沿法线 `NOTCH_LEN_MM` 短线段）/ SP5=布纹线 grain_line（两端点直线）。
  7. 空数据层安全跳过：`net_polygon` 为空 → 不出现 SP2；`internal_lines` 空 → 不出现 SP3；其余类推。
  8. 多片正确：N 个 polygon → SP1 的 `PU`+`PD` 组出现 N 次。
  9. `title` 非空 → 输出 `LB<title>` 文字指令，以 ETX `chr(3)` 终止；`title` 为 ASCII（不引入中文编码风险）。
  10. 返回类型 `bytes`，`.decode('ascii')` 不抛异常（全 ASCII 输出）。
  11. `server.py` 第 47 行 import 扩为 `from .export import placed_to_world, render_png, write_marker_dxf, write_marker_plt`；`/export` 路由在 `elif fmt == 'dxf':` 之后、`else:` 之前新增 `elif fmt == 'plt':` 分支，`title` 复用 DXF 同款 ASCII（`f'M1787 util={pct:.2f}% L={width_mm / 10:.1f}cm gate={int(gate_mm)} seed={seed}'`），`media, ext = 'application/plt', 'plt'`。
  12. 回归不破坏：`fmt=='png'` / `fmt=='dxf'` 行为完全不变；`fmt` 为未知值仍返回 400 `{error: '未知格式 <fmt>'}`。
  13. 新建 `tests/test_export_plt.py` 覆盖：闭合不变量、坐标×40 缩放、首条 `IN;`、6 个笔号各至少出现一次（有对应数据时）、空层跳过、多片计数、`LB`+ETX 终止、`bytes`+ASCII、门幅框四角；`pytest tests/test_export_plt.py` 全绿。
  14. Python 模块可通过 `python -m materialsorting.web.server` import 跑通、分层依赖未反向（`web→engine→bounds→parser`，PLT 导出属 web 层）。
- **Priority**: 1

### US-034: 前端 PLT 格式选项（download.ts 类型 + 测试更新）
- **Description**: As a 版师, I want to select "PLT" from the export format dropdown and click export to download a .plt file, so that I can feed it to the WT V8.8 / LIKE 绘图仪. 涉及文件：`materialSorting-web/src/lib/download.ts`（`ExportFmt` 加 `'plt'` + `EXPORT_FORMATS` 加一项）；验证点（应零改动）：`useExport.ts`（fmt 透传）、`ExportButtons.tsx`（数据驱动下拉框）；测试更新：`lib/__tests__/download.test.ts`、`__tests__/useExport.test.tsx`、`components/ControlPanel/__tests__/ExportButtons.test.tsx`。
- **Acceptance Criteria**:
  1. `download.ts` 的 `ExportFmt` 联合类型扩展为 `'png' | 'dxf' | 'plt'`。
  2. `EXPORT_FORMATS` 数组新增 `{ value: 'plt', label: 'PLT' }`（DXF 保持第一项，`DEFAULT_EXPORT_FMT` 仍为 `'dxf'`）。
  3. `useExport.ts` **零代码改动**：`exportAs(fmt, sizes)` 的 `fmt: ExportFmt` 类型随步骤 1 自动含 `'plt'`；状态行 `` `正在生成 ${fmt.toUpperCase()} …` `` 对 `'plt'` → `'正在生成 PLT …'` 自动命中。
  4. `ExportButtons.tsx` **零代码改动**：下拉框 options 由 `EXPORT_FORMATS.map(...)` 驱动，扩容后 PLT 自动出现；`useState<ExportFmt>(DEFAULT_EXPORT_FMT)` 默认仍 DXF。
  5. `lib/__tests__/download.test.ts`：`parseContentDisposition` 兜底测试组加 `expect(parseContentDisposition('', 'plt')).toBe('nesting.plt')`。
  6. `__tests__/useExport.test.tsx`：参照现有 DXF `onStatus` 用例，加一条 `exportAs('plt', [...])` → `onStatus` 被调 `'正在生成 PLT …'`。
  7. `components/ControlPanel/__tests__/ExportButtons.test.tsx`：原"select 有 2 个选项 (DXF/PNG)"断言改为 3 个（DXF/PLT/PNG）；加一条"切到 PLT + 点导出 → onExport('plt')"用例。
  8. 前端全部单测通过（`npm test`），TypeScript 项目构建通过（`npm run build` 无错误）。
- **Priority**: 2

## 功能需求 (Functional Requirements)

- FR-1: 后端新增 HPGL/PLT 文本生成器 `write_marker_plt()`，输入 `world_pieces`（复用 `placed_to_world` 输出）+ `width_mm/gate_mm/title`，输出全 ASCII 的 `bytes`。
- FR-2: HPGL 指令集：`IN;`（初始化）→ `VS;`（速度）→ `SP6;` 门幅框 → 逐片 `SP1..SP5` 各层 `PU`/`PD` → `SP1; LB<title>chr(3);` 标题 → `SP0;` 收尾。
- FR-3: 坐标 = 世界坐标(mm) × 40（HPGL 绘图单位 0.025mm），`round` 取整；多边形首尾点闭合。
- FR-4: 5 层笔号映射：SP1=毛版裁切轮廓 / SP2=净版 / SP3=内部线 / SP4=刺口 / SP5=布纹线 / SP6=门幅框；空层跳过。
- FR-5: `/export` 路由识别 `fmt=='plt'`，返回 `media_type='application/plt'`、`ext='plt'`，文件名走现有 `ext` 变量拼接逻辑（`排料_码<sizes>_<pct>pct_seed<seed>.plt`）。
- FR-6: 前端 `ExportFmt` 扩 `'plt'`，`EXPORT_FORMATS` 加 PLT 选项；导出下拉框数据驱动出现第三项；下载链路与 PNG/DXF 复用同一 `useExport.exportAs`。

## 非目标 (Non-Goals)

- **不做** 门幅溢出裁剪/平移：MVP 忠实传求解结果，门幅控制责任在求解阶段（前端设 `gate_mm` = 绘图仪实际可印宽度）。若 `gate_mm=1980` 但绘图仪只能印 ~1898，边缘裁片出界是配置问题，非导出问题。
- **不做** 后验门幅 warning header / `X-Export-Warning`（未来增强）。
- **不做** LB 中文标题：标题走 ASCII（与 DXF 一致），中文留给 WT V8.8 字库（其更新日志专门修过 ET 的 PLT 文字）。
- **不做** 物理设备验收（本 PRD 覆盖到"生成合法 PLT + 前后端单测"，现场 WT V8.8 + LIKE 绘图仪实测由用户在落地后进行）。
- **不做** HPGL 高级指令（`AA` 画弧 / `CI` 画圆 / `PW` 笔宽 / `DT` 自定义文字终止符）——裁片轮廓是直线段 POLYLINE，`PU`/`PD` 足够；文字用默认 ETX 终止。

## 设计考虑 (Design Considerations)

- **坐标不翻转**：PLT 在后端纯 Python 生成，直接用 `placed_to_world()` 的世界坐标（X=用布长度 Y 向上），与绘图仪走纸/幅宽天然一致。**绝不能带入前端 SVG 的 `scale(1,-1)` 翻转**（那只是屏幕显示口径）。`write_marker_plt` docstring 须显式标注此约束。
- **笔号语义可见性**：建议在生成的 PLT 文本中用 LB 注释行（如 `;SP1=outline SP2=net SP3=internal SP4=notch SP5=grain SP6=border`）或 docstring 明示笔号语义，方便用户在 WT V8.8 中按笔号分配不同物理笔 / 切割刀。注意 HPGL 注释不能干扰指令解析（用 `;` 行或 LB 走文字）。
- **换行可读性**：HPGL 指令以 `;` 分隔，坐标以 `,` 分隔；输出用 `\n` 分行增强可读性（ET / WT V8.8 均容忍换行），便于现场用文本编辑器肉眼核对。
- **导出区提示文案**：可在前端导出区补充一句提示"PLT 用于绘图仪直连打印，DXF 用于 ET 刻绘"，降低版师选错格式的概率（可选，非阻塞）。

## 技术考虑 (Technical Considerations)

- **几何一致性**：PNG / DXF / PLT 三者共用 `placed_to_world(placed, pieces_by_id)` 返回的同一 `world_pieces`。`write_marker_plt` 只做坐标 ×40 取整 + HPGL 指令封装，不做任何几何变换。×40 取整误差 ≤ 0.025mm（绘图单位精度），远小于服装公差。
- **纯文本直出 bytes**：PLT 是纯文本，`write_marker_plt` 直接 `'\n'.join(commands).encode('ascii')` 返回 bytes，**无需临时文件**（比 `write_marker_dxf` 的 ezdxf 写文件再读字节流程更简单）。
- **闭合策略与 DXF 对齐**：`pts[0] != pts[-1]` 时追加首点到 PD 序列末尾，保证物理闭合。刺口/布纹线/内部线是线段不闭合。
- **门幅物理约束**：`GATE_MM=1980`，绘图仪实际可印门幅约 1698~1898mm。PLT 忠实传递，文档（docstring + 前端提示）标注"门幅应设为绘图仪实际可印宽度"。
- **坐标系贯穿**：sparrow 世界坐标 X=用布长度(0..width)、Y=门幅(0..gate) Y 向上；前端 SVG `scale(1,-1)`；DXF 同世界坐标 Y 向上。PLT 同世界坐标 Y 向上，四者几何口径一致（见 [agent-api-reference.md 坐标系](../.docs/technical/agent-api-reference.md)）。
- **分层依赖**：PLT 导出属 `web` 层，复用 `nesting_engine.sparrow_baseline` 的配色（`PTYPE_COLORS`，若需要按片型着色笔号——MVP 按层固定笔号，不按片型）。`dxf_parser` / `nesting_bounds` 不受影响。
- **无新依赖**：纯标准库字符串拼接，不引入任何新 pip 包。

## 成功指标 (Success Metrics)

- [ ] `write_marker_plt()` 生成合法 HPGL 文本（首条 `IN;`，含 `PU`/`PD`/`SP` 指令，坐标 = mm×40）。
- [ ] PLT 文件全 ASCII，`.decode('ascii')` 不抛异常。
- [ ] 裁片多边形闭合（PD 首尾坐标相同）；5 层各有独立 SP 笔号（有数据时）。
- [ ] 后端 `/export` 接受 `fmt='plt'` 返回 `application/plt` 字节流；现有 PNG/DXF 回归不破坏。
- [ ] 前端下拉框显示 PLT 选项，选 PLT + 导出 → 下载 `排料_码.._..pct_seed..plt`。
- [ ] 后端 `tests/test_export_plt.py` 全绿；前端单测全绿；TS 构建通过。

## 待确认问题 (Open Questions)

1. **笔号 → 物理笔/切割刀映射**：WT V8.8 中 SP1（毛版裁切轮廓）是否应配切割刀、SP2-SP5 配绘图笔？需版师/现场确认 WT V8.8 的笔号配置惯例（本 PRD 只生成 SP1-SP6 语义，物理映射在设备端）。
2. **标题内容**：PLT 标题是否需要比 DXF 的 `M1787 util=... L=...cm gate=... seed=...` 更多信息（如日期、款号、码号列表）？MVP 复用 DXF 同款，可后续按现场反馈调整。
3. **速度 VS 值**：默认 `VS80`（80cm/s）是否适配 LIKE 绘图仪？若现场出现飞墨/抖动可下调（常量 `_PLT_VELOCITY` 易调）。
4. **现场实测反馈闭环**：US-033/034 落地后，用户拿 PLT 到 WT V8.8 + LIKE 绘图仪实测，若仍有问题（如幅面比例、文字位置、刺口长度）需回灌调整——这是物理设备验收，超出本 PRD 单测范围。
