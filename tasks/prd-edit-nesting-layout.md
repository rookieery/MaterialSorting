# PRD: 编辑排料（排料结果手工微调编辑器）

> 依据：2026-09-04 用户需求（主界面「导出最优方案」区块上方新增「编辑排料」标题区 + 编辑/重置两按钮 + 大编辑弹窗，截图确认落点）+ planner 深度调研（60 次工具调用，架构结论全部落文件行号）+ 用户两轮交互定案（AskUserQuestion 四项 + 二次修订两项，见「已决策」节）。
>
> **需求核心**：版师对求解结果做**单片级手工微调**（拖动 + 旋转），拖动中实时看到与邻片的重合区域 / 重合量 / 离布纹角度；保存同步主视图与导出；重置一键回算法原始布局。**利用率随编辑如实重算**：x 向拖超原长 → 保存自动扩 `width_mm`（利用率降）；尾部腾空 → 自动缩短 `width_mm`（利用率升）；弹窗顶部实时显示当前料长与利用率。
>
> **2026-09-04 二次修订（用户确认）**：① 废弃右下「取消」按钮 → 弹窗右上角 ✕ 关闭（dirty 时二次确认后弃稿，语义同旧取消）；② 利用率从「不动」升级为「实时重算」（见上）。
>
> **零后端改动**：`/export` 与 `/api/plt-table-preview` 的 placed / density 全部来自前端请求体（[useExport.ts:80-91](../materialSorting-web/src/hooks/useExport.ts#L80-L91)、[routes_views.py:381](../materialSorting-server/src/materialsorting/web/routes_views.py#L381)），编辑保存只需原地改写 `bestRun().lastFrame`（placed_items + width_mm + density），PNG/DXF/PLT 三格式导出 + PLT 表格预览（含利用率字段）自动继承。

## 概述 (Overview)

在控制面板「导出最优方案」上方新增「编辑排料」区块（编辑 / 重置两按钮，有求解结果才可点）；点「编辑」弹出全屏编辑弹窗：中心命令式 SVG 画布复用主视图 5 层渲染（完整版 / 毛板两形态），支持单片拖动、旋转手柄（自由角度）、滚轮缩放 + 空白拖动平移；拖动中实时显示与邻居的交集高亮 + 重合面积 / 穿透深度 / 旋转偏离角三指标；顶部状态条实时显示当前料长与利用率（随编辑伸缩重算）。保存 = 原地写回 `lastFrame`（placed_items + `width_mm = ceil(包络 maxX)` 双向伸缩 + density 族重算）；关闭 = 右上 ✕（dirty 二次确认后弃稿）——弹窗唯一关闭路径 = ✕ 与保存（禁 ESC / 遮罩）。弹窗外「重置」经自定义 confirm 恢复算法基线（含利用率）。重解 / 应用策略(极限)结果时编辑态自动失效。

## 目标 (Goals)

- **微调能力**：单片拖动 + 旋转手柄（自由角度），拖动中重合高亮与三指标（面积 mm² / 深度 mm / 偏离角 °）实时显示、阈值着色。
- **利用率如实重算**：料长随编辑包络双向伸缩（扩长 → 利用率降 / 缩短 → 升），弹窗实时显示，保存后主视图与导出口径一致。
- **所见即所得闭环**：保存 → 主视图重绘（含利用率/料长）+ PNG/DXF/PLT 导出 + PLT 表格预览同步吃编辑（零后端改动）。
- **可逆性**：✕ 关闭 = 弃稿（dirty 二次确认）、重置 = 回算法基线（confirm）；重解 / 策略应用自动失效编辑态。
- **现状零回归**：主渲染仅做 `createPieceEntry` 机械提取共享（pieceDom.ts），NestSVG 现有单测全绿。

## 用户故事 (User Stories)

### US-001: 编辑几何与状态基础（editGeometry + overlap + editStore）
- **Description**: As a developer, I want 多边形变换 / 布尔交 / 穿透深度纯函数库 + 重合计算器 + 编辑态 store so that 编辑弹窗有计算与状态地基。文件：`materialSorting-web/src/lib/editGeometry.ts`（新）、`src/lib/overlap.ts`（新）、`src/store/editStore.ts`（新）、`package.json`（+ `polygon-clipping`）、[lib/params.ts:374-382](../materialSorting-web/src/lib/params.ts#L374-L382)（私有 `polygonArea` 导出复用）。
- **Acceptance Criteria**:
  1. `transformPolygon(poly, rot, tr)` 输出与 [lib/geometry.ts:30-43](../materialSorting-web/src/lib/geometry.ts#L30-L43) `pointsStr` 同公式逐点一致（单测对拍）
  2. `computeOverlap(dragged, others)`：两矩形交面积精确值、凹多边形交 ring 数、bbox 预筛只对相交邻居布尔交、穿透深度 = 「A 内顶点落入 B / B 内顶点落入 A 的点到对方各边距离最大值」——矩形 / 三角 / 凹形夹具单测锁死
  3. `editStore`：`open` 快照**不可变基线全套**（`placed_items` 深拷贝 + `frameIndex` / `widthMm` / `density` / `finalDensity` / `viewBoxMaxW`）/ `computeLayoutStats(working, manifest)` 纯函数 = `width = ceil(全布局包络 maxX)`（下限 1mm）+ `density = total_area_mm2/(width×gate_mm)`（real 口径）/ `save` 原地写回指定 `RunRecord.lastFrame.placed_items`（多副本按 placed_items 数组下标寻址、保序写回）+ `lastFrame.width_mm` / `lastFrame.density` / `run.finalDensity` / `run.viewBoxMaxW` 按 `computeLayoutStats` 重算更新 + `bumpRenderTick()` + `savedDirty=true` / `reset` 恢复基线全套 / `invalidate` 清态；保存防御校验 run 仍在 `runRegistry.list()`
  4. 引入 `polygon-clipping`（Martinez 算法，MIT，纯 TS）；不引入其它新依赖
  5. 前端门：vitest 新增套件全绿 + `npm run typecheck` + `npm run build` 通过（后端零改动）
- **Priority**: 1

### US-002: 编辑弹窗渲染与查看（EditLayoutModal + EditCanvas 只读态）
- **Description**: As a 版师, I want 一个大弹窗全量展示当前排料布局、顶部实时显示料长与利用率、可切完整版/毛板、可缩放平移 so that 我能先看清再动手微调。文件：`src/components/nests/pieceDom.ts`（自 [NestSVG.tsx:273-347](../materialSorting-web/src/components/nests/NestSVG.tsx#L273-L347) 机械提取 `createPieceEntry`，NestSVG 改 import）、`src/components/edit/EditLayoutModal.tsx`（新）、`src/components/edit/EditCanvas.tsx`（新）、[controlPanelStore.ts:25](../materialSorting-web/src/store/controlPanelStore.ts#L25)（`ControlPanelModalId` 加 `'edit_layout'`）、`style.css`（`.edit-layout-*` 族，z-index 1250）。
- **Acceptance Criteria**:
  1. `pieceDom.ts` 纯机械提取后 [NestSVG 现有单测] 全绿（提取零行为变化；`scale(1,-1)` 翻转组 + `setAttribute` 命令式更新范式原样保留）
  2. 弹窗渲染 5 层全量（毛版 polygon / 净版虚线 / 内部线 / 刀口 / 布纹线 + 尺码色），完整版与主视图同构同观感；demand 多副本按「出现序」渲染（与 [NestSVG.tsx:188-199](../materialSorting-web/src/components/nests/NestSVG.tsx#L188-L199) reached 计数器同语义）
  3. 弹窗结构：**顶部状态条**（料长 mm + 利用率 % + 相对基线 Δpt，初始 = 基线值，经 US-001 `computeLayoutStats` 同一真相源）；**右上角 ✕ 关闭按钮**；左下 select 切「毛板」：4 层工艺节点隐藏（display 切换）、毛版 polygon + 尺码色保留，切回「完整版」恢复；**右下仅「保存当前布局」单按钮**（取消按钮已废弃，2026-09-04 二次修订）
  4. 缩放平移：滚轮以指针为锚缩放 + 按住空白处拖动平移 + 「重置视图」/ ± 按钮；指针→世界坐标走 `flipGroup.getScreenCTM().inverse()`（涵盖 viewBox letterbox + y 翻转），单测锁 clientToWorld 在 viewBox 变化下取值正确
  5. 关闭路径唯一性：ESC keydown 与遮罩 mousedown 均不关闭（单测 dispatch 断言弹窗仍在）；关闭仅有两条路径 = 右上 ✕（dirty 时二次确认后弃稿）与右下「保存当前布局」
  6. 通过浏览器验证排料渲染（完整版 / 毛板两形态与主视图布局一致性、顶部状态条初值 = 主视图利用率）；前端门 vitest + typecheck + build 通过
- **Priority**: 2

### US-003: 拖动、旋转与重合指标
- **Description**: As a 版师, I want 拖动 / 旋转单个裁片并实时看到重合区域、重合量、布纹角度与利用率变化 so that 我能安全地微调每片的位置与姿态并直观感受用料代价。文件：`EditCanvas.tsx` 扩展（消费 US-001 的 `overlap.ts` 与 `computeLayoutStats`）。
- **Acceptance Criteria**:
  1. 拖动：毛版 polygon `pointerdown` + `setPointerCapture` → pointermove 只 `setAttribute` 被拖片 5 层节点 → working 下标项 translation 更新；**Y 硬钳制 [0, gate]**（按被拖片 bbox，gate = `manifest.gate_mm`）、x<0 钳 0、x 超原布局右界自由拖（保存时双向伸缩 width_mm）；被拖片渲染提层（置顶不闪藏）
  2. 旋转：选中片质心上方显示旋转手柄，拖柄转角；**自由角度、不做 0°/180° 吸附**（2026-09-04 定案）；布纹线随片同步旋转
  3. 拖动 / 旋转中（rAF 节流）：bbox 相交邻居渲染红色半透明交集 polygon（polygon-clipping 交区域）；画布右上固定指标面板显示——**重合面积 mm²（括注 cm²，÷100 站内惯例）+ 最大穿透深度 mm + 旋转偏离角 °**（= 相对 {0°,180°} 的最小偏差 `min(|rot|,|rot−180|,|rot−360|)`）
  4. 阈值着色：穿透深度 ≤10mm 琥珀（solver 合法上限 `MAX_OVERLAP_MM=10`）、>10mm 红；偏离角 >45° 红（`MAX_ROTATION_TOL_DEG`）——既有布局合法含 ≤10mm 重合，口径 = 如实展示 + 阈值着色，不「见重合即报警」
  5. **顶部状态条实时更新**：料长 = `ceil(当前包络 maxX)`、利用率 = `total_area/(料长×gate)`、Δ 相对基线——与保存口径同公式同真相源（`computeLayoutStats`），rAF 同帧刷新；拖片右移超界 → 料长增 / 利用率降，拖片左移腾空尾部 → 料长缩 / 利用率升
  6. 指标基于 manifest（erode 后）多边形计算（与 solver 碰撞判定同口径），面板脚注注明「按算法碰撞口径」；布尔交异常降级「bbox 交高亮 + 面积按 bbox 估算」不阻塞拖动
  7. jsdom PointerEvent polyfill（`window.PointerEvent = class extends MouseEvent {}`）下单测：拖动 / 旋转后 working 下标项 translation / rotation 精确断言；通过浏览器验证拖动流畅、指标与状态条实时性；前端门 vitest + typecheck + build 通过
- **Priority**: 3

### US-004: 保存 / 关闭 / 重置与主界面集成 + 导出闭环
- **Description**: As a 版师, I want 保存把微调（布局 + 料长 + 利用率）同步到主视图与导出、✕ 关闭弃稿、重置一键回算法结果 so that 编辑始终可控可逆。文件：`src/components/ControlPanel/EditLayoutControls.tsx`（新，插 [ControlPanel.tsx:420-421](../materialSorting-web/src/components/ControlPanel.tsx#L420-L421) StatusLine 与 ExportButtons 之间）、`NestingPage.tsx`（`handleStart` / `applyStrategyResult` 各加 invalidate）、`editStore.ts` 接线。
- **Acceptance Criteria**:
  1. 「编辑排料」区块位于「导出最优方案」上方（`.field-label` 标题 + 两按钮，三层 disabled 防御同站内惯例）；激活口径与导出按钮一致：`runRegistry.list().some(r => r.lastFrame !== null) && phase !== 'running'`（含 stopped best-so-far 中间方案与策略 / 极限合成 record——它们本就可导出，可编辑语义一致）
  2. 保存：working → `run.lastFrame.placed_items` 原地保序写回 + **`width_mm = ceil(包络 maxX)`（双向伸缩：扩长或缩短）+ `lastFrame.density` / `run.finalDensity` 重算（real 口径）+ `run.viewBoxMaxW` 跟随新料长**（NestSVG `W = max(viewBoxMaxW, f.width_mm)` 主视图画布随之收缩 / 扩展）+ `bumpRenderTick()` → 主视图被拖片重绘、NestLabel 利用率与长度同步变化；`density_sparrow` 不动（solver erode 参考值）
  3. 导出闭环：保存后 `useExport.exportAs` POST `/export` payload 的 placed 与 density 反映新值（[useExport.test.tsx] 集成断言）；ExportInfoModal 的 `/api/plt-table-preview` 同源 bestRun 自动吃编辑（利用率字段 = 编辑后值）
  4. ✕ 关闭：working ≠ 已保存布局时先弹自定义小确认层「放弃未保存的修改？」，确认后弃稿关窗；纯查看未改动直接关；ESC / 遮罩仍永不关闭
  5. 重置：弹窗外按钮 → 自定义暗色 confirm（文案「确认将当前更新后的排料布局重置回初始布局」）→ 确认后恢复**基线全套**（placed_items + width_mm + density / finalDensity + viewBoxMaxW + `savedDirty=false` + bump）；无编辑时确认后幂等无变化
  6. 失效：`handleStart`（重解）与 `applyStrategyResult`（策略 / 极限结果应用）触发 `invalidate()`（单测覆盖两挂点）；弹窗打开期间全屏 overlay 阻断主界面；刷新 / 切会话编辑态自然消失（纯前端内存，不持久化）
  7. 通过浏览器验证保存后主视图同步（布局 + 利用率 + 料长）；前端门 vitest + typecheck + build 通过
- **Priority**: 4

### US-005: 端到端冒烟与文档闭环
- **Description**: As a developer, I want 浏览器冒烟覆盖 上传→求解→编辑→保存→导出→重置 全链路 + 文档红线入册 so that 功能被回归锁死。文件：`scripts/smoke_edit_layout.mjs`（repo 根，范本 [smoke_plt_table_preview.mjs](../scripts/smoke_plt_table_preview.mjs)）、`materialSorting-web/AGENTS.md`、`.docs/technical/agent-component-map.md`。
- **Acceptance Criteria**:
  1. 冒烟：上传 5336 → 短求解 final → 编辑弹窗打开（完整版 5 层 / 毛板纯轮廓两形态断言 + 顶部状态条初值 = 主视图利用率）→ 拖动一片右移超界 + 旋转 → 指标面板出现（面积 / 深度 / 角度）+ 状态条料长增 / 利用率降 → 保存 → 主视图被拖片 points 变化 + NestLabel 利用率 / 长度同步 → 导出 PLT 抓包 placed 与 density 均与基线 diff 非空 → ✕ 重开弹窗拖片左移腾空 → 状态条料长缩 / 利用率升 → 保存 → 弹窗外重置 → 恢复算法布局与基线利用率
  2. 报告落 `out/smoke_edit_layout/report.json`，退出码 0 = 全 PASS
  3. AGENTS.md 新增「编辑排料关键约定」节，四条红线：①禁 ESC / 遮罩关闭（唯一关闭路径 = 右上 ✕ 与保存，与全站弹窗惯例的有意偏离）②多副本按 placed_items 数组寻址保序写回 ③width_mm 随编辑包络双向伸缩 + density 族同口径重算（real 口径 `total_area/(width×gate)` 单一真相源；density_sparrow 不动；PLT 表格 / 导出标题 pct 自动跟随）④重合指标按 erode 几何口径（物理毛版重合最多大 ~2·d_g）；agent-component-map.md 补组件条目
  4. 前端门：vitest 全绿 + `npm run build` 通过；progress.txt 记条
- **Priority**: 5

## 功能需求 (Functional Requirements)

- **FR-1 区块与激活**：「编辑排料」标题区（`.field-label`）置于「导出最优方案」上方；编辑 / 重置两按钮仅当 `some(r.lastFrame) && phase !== 'running'` 时高亮可点，否则三层防御置灰。
- **FR-2 弹窗结构**：顶部状态条（料长 + 利用率 + Δ基线，实时）；右上 ✕ 关闭；中心 = 排料布局画布；左下 = 形态 select（完整版 / 毛板）；右下 = 「保存当前布局」单按钮（取消按钮已废弃）；**唯一关闭路径 = ✕ 与保存**（不挂 ESC listener、遮罩 mousedown 不关闭，单测固化）。
- **FR-3 两形态**：完整版 = 5 层全量 + 尺码色（与主视图同构，`pieceDom` 单一真相源）；毛板 = 仅毛版轮廓 + 尺码色（净版 / 内部线 / 刀口 / 布纹线全隐藏）。
- **FR-4 单片拖动**：pointerdown + capture；Y 硬钳制 [0, gate]（bbox 口径）、x<0 钳 0、x 超右界自由（保存时双向伸缩 width_mm）；多副本各自独立编辑（下标寻址）。
- **FR-5 旋转**：选中片质心上方旋转手柄拖动转角；自由角度、无吸附；角度偏离 {0°,180°} 如实显示（>45° 红）。
- **FR-6 拖动指标**：交集区域红色半透明高亮 + 右上固定面板（面积 mm² 附 cm² / 最大穿透深度 mm / 旋转偏离角 °）+ 阈值着色（≤10mm 琥珀 / >10mm 红；>45° 红）；erode 几何口径 + 脚注注明；rAF 节流；计算失败降级不阻塞拖动。
- **FR-7 缩放平移**：滚轮以指针为锚缩放 viewBox + 空白拖动平移 + 重置视图 / ± 按钮。
- **FR-8 利用率与料长（实时 + 保存同口径）**：`computeLayoutStats(working, manifest)` 单一真相源 —— `width = ceil(全布局包络 maxX)`（下限 1mm，双向伸缩）+ `density = manifest.total_area_mm2/(width×gate_mm)`（real 口径）；弹窗顶部实时显示（rAF 同帧）；保存时写 `lastFrame.width_mm` / `lastFrame.density` / `run.finalDensity` / `run.viewBoxMaxW`；`density_sparrow` 不动；重置恢复基线全套。
- **FR-9 ✕ 关闭**：dirty（working ≠ 已保存布局）时自定义确认层「放弃未保存的修改？」后弃稿关窗；非 dirty 直接关。
- **FR-10 重置**：自定义 confirm（暗色、文案按需求原文）→ 恢复算法基线全套（placed_items + width_mm + density 族 + viewBoxMaxW）。
- **FR-11 编辑态失效**：重解 start / 应用策略(极限)结果 → invalidate；保存防御校验 run 在册；刷新 / 切会话自然消失（不持久化、不落盘）。
- **FR-12 导出闭环**：`/export`（PNG/DXF/PLT/plt-clean）与 `/api/plt-table-preview` 的 placed 与 density 均取自 `bestRun().lastFrame`，保存后自动继承（PLT 表格利用率字段 / 导出文件名 pct 同步编辑后值），后端零改动。

## 非目标 (Non-Goals)

- **后端任何改动**（导出链路天然吃编辑与重算密度，见 FR-12）。
- **density_sparrow 重算**：保持 solver 自报 erode 参考值不动（real 口径已是版师 / 生死线单一口径）。
- **undo / redo 与单片复位**：弹窗草稿制（✕ 关闭 = 全弃、重置 = 回基线）两档回退已覆盖主诉求；二期再议。
- **键盘角度微调（[ / ] ±1°）**：定案只选「手柄 + 自由角度」交互；若实现成本极低可附带，但不作验收项。
- **多片框选批量移动 / 复制 / 删除**：单片微调定位，不做批量编辑。
- **右键框选放大**：缩放定案为滚轮 + 空白拖动；框选放大列二期增强。
- **0°/180° 吸附**：定案明确不吸附（自由角度，全靠偏离角显示自控）。
- **编辑结果持久化**：纯前端内存态，刷新即失（重解也失效）；不做 localStorage / 服务端存档。

## 设计考虑 (Design Considerations)

- **渲染技术 = 命令式 SVG 复用现有渲染**（用户重点关切项）：完整版要求与主界面全量一致 → `createPieceEntry` 5 层构建提取为 `pieceDom.ts` 共享；SVG 命中测试免费（`e.target.closest('polygon')`，NestSVG hover 已验证）；缩放 = 改 viewBox 单属性零 DOM 重建；拖动 = 每帧只 setAttribute 被拖片。React 受控 SVG（reconciliation 覆盖命令式写入，项目已踩坑）与 Canvas（5 层样式 / 命中测试全手写、0 复用）均否决。
- **指标面板固定画布右上**（不跟随光标，避免遮挡拖动区）；顶部状态条 = 料长 / 利用率 / Δ基线（利用率是编辑的核心反馈信号，置顶不藏）；拖动中被拖片渲染提层置顶。
- **confirm / 二次确认 = 自定义暗色小确认层**：全站无 `window.confirm` 先例，观感与现弹窗族一致（✕ 的「放弃未保存的修改？」与重置的确认层同组件复用）。
- **弹窗 z-index = 1250**（per-type-preview 1200 与 toast 1500 之间）；全屏 overlay 阻断主界面交互。
- **毛板模式是轻量交互形态**：纯轮廓渲染更轻，重布局卡顿时可手动切换（不自动切换，保持用户可控）。

## 技术考虑 (Technical Considerations)

- **polygon-clipping 选型**（Martinez–Rueda 纯 TS，MIT，gzip ~10KB，输入输出均为 `number[][]` 与本仓 `Polygon = [number,number][]` 零适配）：裁片是凹多边形，Sutherland–Hodgman 仅凸-凸不可用；clipper 系整数坐标需缩放、API 老。裁片为 DXF 简单多边形无自交，Martinez 安全域内。
- **指针换算**：`flipGroup.getScreenCTM().inverse()` + `svg.createSVGPoint()` 直接得世界坐标（自动涵盖 `preserveAspectRatio="xMinYMid meet"` letterbox 与 `translate(0,gate) scale(1,-1)` 翻转两处坑）；手写 `gate−y` 会漏 letterbox 偏移。
- **多副本寻址**：编辑 key = `placed_items` 数组下标（同 pid 第 k 次出现 = 第 k 副本），与 NestSVG「出现序」副本池同语义；保存原地保序写回 ⇒ 副本映射稳定。弹窗打开期间 registry 无人写（overlay 阻断 + phase≠running 才能打开），下标安全。
- **利用率重算口径（2026-09-04 二次修订核心）**：real 口径单一真相源 `total_area/(width×gate)`——`total_area = manifest.total_area_mm2`（常量，Σdemand 原面积）、`gate = manifest.gate_mm`、`width = ceil(全布局包络 maxX)` 双向伸缩（下限 1mm）；包络 = 全部 placed 片世界多边形 bbox 的 maxX 最大值（复用 overlap 预计算的 bbox，拖动帧增量更新被拖片一项，零额外遍历）。保存同步 `lastFrame.width_mm` / `lastFrame.density` / `run.finalDensity` / `run.viewBoxMaxW`（主视图 `W = max(viewBoxMaxW, f.width_mm)` 随之收缩，回放 seek 帧用各自 f.width_mm 自守恒）；`density_sparrow` 不动；bestRun 选择按 finalDensity 自然跟随（界面单 seed 常态无影响）；PLT 表格预览 / 导出标题 pct 读 payload density 自动一致。缩料长无下限保护之外的特判：布局物理上不可能为空（编辑不删片），density 上界自然 ≤ 布局真实密排。
- **性能预算**：典型 105 片 × ≤300 顶点/片（DXF R12 POLYLINE 顶点原样保留不抽稀）；弹窗打开时预计算全部片世界坐标，拖动帧只变换被拖片 + 对 bbox 相交邻居（通常 0~5 片）布尔交 + 包络 maxX 增量更新，毫秒级 / 帧。
- **重合几何口径**：manifest = erode 后几何 = 与 solver 碰撞判定同口径；原始毛版物理重合比显示值最多大 ~2·d_g（per_type d≤10，默认 0~2mm），弹窗脚注注明。
- **jsdom 无 PointerEvent**（现有测试全用 MouseEvent）：测试 `beforeEach` 一行 polyfill（`window.PointerEvent = class extends MouseEvent {}`）。
- **pieceDom 提取回归锁**：唯一动现有渲染代码的点，靠 NestSVG 现有单测（渲染 / seek 系列）锁行为，纯机械搬移不改逻辑。
- **strategy / extreme 合成 record 可编辑**：合成 manifest 的 pieces 含 demand 与 total_area_mm2，副本下标寻址与密度重算同样成立，无特判（与「可导出 ⇒ 可编辑」语义一致）。

## 成功指标 (Success Metrics)

- [ ] 有求解结果时编辑 / 重置可点，无结果 / 求解中置灰（与导出同口径，含策略 / 极限合成结果）
- [ ] 弹窗完整版与主视图同构、毛板仅轮廓 + 色；两形态即时切换
- [ ] 单片可拖动 / 旋转（自由角度），拖动中实时：交集高亮 + 面积 mm²(cm²) + 深度 mm + 偏离角 °，阈值着色正确
- [ ] 顶部状态条实时：拖片右移超界 → 料长增 / 利用率降；左移腾空 → 料长缩 / 利用率升（与保存口径同真相源）
- [ ] 滚轮缩放（指针锚）+ 空白平移 + 重置视图可用，指针拾取在世界坐标下准确
- [ ] 保存后主视图同步（布局 + 利用率 + 料长）、三种导出 + PLT 表格预览 placed / density 反映编辑（文件名 pct 一致）
- [ ] ESC / 遮罩不关闭弹窗（单测 + 冒烟双锁）；✕ 关闭 dirty 二次确认
- [ ] 重置 confirm 后恢复算法原始布局与基线利用率（冒烟 placed / density diff 回零）
- [ ] 重解 / 应用策略结果后编辑态失效；刷新后无编辑残留
- [ ] vitest 全绿（含 pieceDom 提取零回归）+ `npm run typecheck` + `npm run build` 通过 + 冒烟 report.json 全 PASS（退出码 0）

## 已决策（2026-09-04 用户两轮确认，开放问题清零）

**第一轮（AskUserQuestion 四项）**：
1. **旋转交互 = 旋转手柄 + 自由角度**（不吸附 0°/180°）：选中片质心上方柄点拖动转角，偏离角显示辅助自控；键盘微调不作验收项（见非目标）。
2. **缩放平移 = 滚轮指针锚缩放 + 空白拖动平移**：附「重置视图」+ ± 按钮；右键框选放大列二期。
3. **越界处理 = Y 钳制 + x 超界自由拖**：门幅方向（y）按 bbox 硬钳 [0, gate]；长度方向（x）不钳，width_mm 伸缩与密度重算见 ⑥。
4. **关闭时 dirty 二次确认**：有未保存改动先确认「放弃未保存的修改？」；纯查看直接关；ESC / 遮罩永不关闭。

**随分析采纳的推荐默认**：指标 = 面积 + 深度双指标阈值着色（≤10mm 琥珀 / >10mm 红，`MAX_OVERLAP_MM` 口径）；重合指标面板固定画布右上；erode 几何口径 + 脚注；激活口径与导出一致；自定义 confirm 层；undo 不做；编辑态失效挂点 = 重解 + 策略应用。

**第二轮（二次修订）**：
5. **废弃右下「取消」按钮**：弹窗关闭收敛为右上角 ✕（dirty 二次确认后弃稿，语义 = 旧取消）；右下仅存「保存当前布局」；ESC / 遮罩仍永不关闭——更简洁。
6. **利用率实时重算（取代初版「不影响利用率」口径）**：弹窗顶部实时显示当前料长 + 利用率（real 口径 `total_area/(width×gate)`，`width = ceil(包络 maxX)`）；x 向拖超原长 → 保存自动扩 `width_mm` → 利用率降；识别到尾部腾空 → 自动缩短 `width_mm` → 利用率升；保存同步 `lastFrame.width_mm` / `lastFrame.density` / `run.finalDensity` / `viewBoxMaxW`，重置恢复基线全套；`density_sparrow` 保持 solver 参考值不动。
