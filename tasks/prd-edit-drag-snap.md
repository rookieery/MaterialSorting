# PRD: 编辑弹窗拖动紧贴吸附（右键拖动松手贴合恰 0mm）

## 概述 (Overview)

编辑排料弹窗中**右键**拖动裁片松手时，若落点与其他裁片产生**新增**重叠，自动沿拖动路径回退到首触点（重合恰 0mm）；若落点与邻近裁片留有小缝隙（≤10mm），沿拖动方向吸拢到贴合（P1 档）。**左键拖动保持现状零改动**——版师按工艺参考值压线（想要一点重合）的正常工作流完全不受影响（2026-09-06 用户定案：吸附是显式意图，opt-in 手势而非默认行为）。纯前端实现零后端改动。

## 目标 (Goals)

- 右键拖动松手落点的新增重叠被消除：被拖片 vs 全部邻居布尔交面积 ≤ 1e-9 mm²（工程零），分离 ≥ 1e-9 mm（1nm 微抬，对齐后端 `polish.SEP_NUDGE_MM`）。
- P1 档：右键落点与邻居间隙 ≤ 10mm 时自动吸拢到贴触 − 1nm（2026-09-06 定案：吸附已 opt-in 右键，阈值网放宽到 10mm）。
- **左键拖动行为逐字节不变**（回归红线，冒烟可断言）：落点原样、可自由压线、无任何吸附介入。
- 拖动全程**零新增逐帧计算**（吸附求解只在右键会话 pointerup 一次付费），拖动性能无可测回退。
- 吸附产生的 translation 修正全精度贯通 保存 → /api/edit-polish → PLT/DXF 导出（已核实三处序列化均无取整）。

## 用户故事 (User Stories)

### US-001: 吸附几何算子（contactT + firstContactDistance）
- **Description**: As a 开发者, I want 在 `materialSorting-web/src/lib/editGeometry.ts` 新增两个精确解析算子（`contactT`：顶点沿方向平移到线段上的参数解；`firstContactDistance`：两多边形沿方向的首触距离）so that 吸附引擎无需迭代即可求出贴合平移量。
- **Acceptance Criteria**:
  1. `firstContactDistance(rectA, rectB, dir)` 对矩形夹具返回解析精确 t（±1e-9）。
  2. 凹形 L 夹具首触点落在凹口内角；近平行弧段密集顶点（牛仔裤弧片实况）返回 null 不抛异常。
  3. 镜像+旋转片与直接构造的同物理形态片同 t（口径无关性锁——吸附数学只发生在 worldPolygon 上，与 rot/mirror 无关）。
  4. 纯前端 Story 构建检查（替代后端 `python -m` 检查项，见技术考虑）：`npm run build` 干净 + 既有 vitest 全量通过 + 零后端改动。
- **Priority**: 1

### US-002: 松手吸附引擎纯函数（retreat + attract）
- **Description**: As a 用户, I want 新文件 `materialSorting-web/src/lib/snap.ts` 承载松手吸附引擎纯函数（P0 retreat = 沿拖动路径粗扫+二分回退到首触；P1 attract = 解析首触距离吸拢；clamp 复核守卫 fail-open）so that 右键松手落点自动消除新增重叠并贴合恰 0mm，且引擎全程序确定、无 RNG、异常永不卡交互。
- **Acceptance Criteria**:
  1. P0 retreat：重叠夹具松手修正后全邻居布尔交面积 ≤ 1e-9 mm² 且分离 ≥ 1e-9 mm；回退量与解析值对拍（容差 0.01mm）。
  2. 粗扫防隧道穿越夹具通过（拖动线段跨过窄障碍、凹形使自由区间不连通时，朴素二分会跳过——必须粗扫 20mm 步先括出首个穿越小段再二分，对齐后端 `polish._slide_west_touch` 手法）。
  3. 谓词 = 「全邻居总重叠面积 ≤ 起手基线 + 1e-9」：起手存量重叠（solver 全局容差 `MAX_OVERLAP_MM=10` 构造的布局）不恶化、不误清（对齐 `polish._move_ok` 无新增守卫精神）。
  4. P1 attract：间隙 6mm（< 阈值 10mm）吸附后布尔交 ≤ 1e-9；间隙 15mm（> 阈值）不动；末帧拖动位移方向为零位移时退化用质心连线；多邻居取接触距离最小者、平手取数组下标小。
  5. 吸附结果违反 clamp 不变量（y∈[0,gate]、minX≥0）→ 弃用回落 raw；任何内部异常 → 返回 raw（fail-open）。触发与否是调用方（UI 会话）的职责，引擎不感知按键。
  6. 确定性双跑逐位全等（无 RNG）；邻居寻址全程 `EditPiece.key` 数组下标，同 pid 多副本绝不 pid 去重（仓库红线，测试加锁）。
  7. 纯前端 Story 构建检查：`npm run build` 干净 + 既有 vitest 全量通过 + 零后端改动。
- **Priority**: 2

### US-003: EditCanvas 右键会话接线与视觉反馈
- **Description**: As a 用户, I want 吸附接进 `materialSorting-web/src/components/edit/EditCanvas.tsx` 的 pointerdown 按钮分流 + 右键会话 pointerup 路径（MoveDrag 增 `snap` 标志、`lastSafeTr` 跟踪复用既有每帧 `computeOverlap`、松手单次求解、伙伴片高亮、指南卡文案）so that 右键拖片松手即贴、左键完全照旧、贴附意图有专属手势。
- **Acceptance Criteria**:
  1. `onPointerDown` 增 `e.button` 门控（现行无门控，[EditCanvas.tsx:744](materialSorting-web/src/components/edit/EditCanvas.tsx#L744) 已核实）：`button===2` 且命中毛版 polygon → MoveDrag 带 `snap:true`；`button===0` → 现行 MoveDrag 路径零改动；其余非主键（中键等）不起旋转/平移会话（顺手修掉现状「右键也能平移/转旋转柄」隐性怪癖）。
  2. svg 上 `contextmenu` preventDefault（工具型画布无自定义右键菜单需求，右键已被贴附手势占用）。
  3. 右键会话松手：clamp → `computeSnapCorrection` → 结果经 `commitDragPlacement` 唯一落笔出口写入；吸附只改 translation，永不动 rot/mirror（与 MoveDrag 会话锚点语义一致）。
  4. 左键拖动、键盘变换（L/K/空格/O/I/R）与旋转拖柄**永不吸附**——`applyKeyTransform`/`applyRotateFrame` 与左键路径逐字节不变（回归红线）；吸附引擎只被 `snap:true` 会话的 pointerup 调用。
  5. 拖动帧零新增计算：`lastSafeTr`（会话内最后一个满足谓词的位置）由既有 `refreshMetrics` 的 `computeOverlap` 结果顺带更新（所有会话免费跟踪，仅右键会话消费），rAF 合帧管线不变。
  6. 吸附瞬间伙伴片高亮 + 指标面板重合 0.00 自证（erode 口径与红字告警同真相源）；指南卡新增一行「右键拖动松手贴附」文案。
  7. 通过浏览器验证编辑排料渲染（右键拖动 → 松手吸附 → 高亮 → 左键拖离恢复自由 → 撤销路径不炸）。
  8. 纯前端 Story 构建检查：`npm run build` 干净 + 既有 vitest 全量通过 + 零后端改动。
- **Priority**: 3

### US-004: 冒烟脚本与文档同步
- **Description**: As a 维护者, I want 新增 `materialSorting-web/scripts/smoke_drag_snap.mjs` 冒烟（playwright + Edge 通道，模板 `scripts/smoke_edit_polish.mjs` / `smoke-band-preview.mjs` 套路）+ 文档同步（`materialSorting-web/AGENTS.md`、`.docs/technical/agent-component-map.md`）so that 吸附功能与左键零回归双护栏。
- **Acceptance Criteria**:
  1. 冒烟 ≥25 检查点全过：真实母版上传 → 打开编辑弹窗 → **右键**（`button:2`）pointer 序列把片推向邻居/留小缝松手 → 断言 DOM `points` 与期望吸附坐标（复用键盘用例的数学锚点法）／指标面板重叠 0.00／右键继续拖离恢复自由／**左键拖动压线落点原样零吸附**（回归红线断言）／右键拖动中无 contextmenu 弹出／保存后 placed translation 等于吸附值（全精度）／导出 PLT 回读无回归。
  2. `AGENTS.md` / `agent-component-map.md` 含吸附语义（右键会话触发、松手时一次、只改 translation、左键/键盘/旋转柄永不吸附）、erode 口径脚注（d>0 策略跑批场景与红字告警同口径分歧，**沿用 `overlap.ts` 现有脚注原文引用**——2026-09-06 定案，避免两处文案漂移）。
  3. 纯前端 Story 构建检查：`npm run build` 干净 + 既有 vitest 全量通过 + 零后端改动。
- **Priority**: 4

## 功能需求 (Functional Requirements)

- **FR-1 右键会话松手 retreat（P0）**：右键拖动 pointerup 时若落点使全邻居总重叠面积 > 起手基线，以 lo = 会话内最后安全位（`lastSafeTr`）、hi = 落点，沿拖动路径粗扫（20mm 步防隧道穿越）+ 二分（≤14 轮，0.01mm 精度）+ 1nm 微退，落位到首触点。
- **FR-2 右键会话松手 attract（P1）**：右键落点无新增重叠且与某邻居沿末帧拖动位移方向的解析首触距离 ≤ 10mm 时（`ATTRACT_MAX_GAP_MM=10`，2026-09-06 定案），吸到触点 − 1nm；零位移帧退化用质心连线方向。
- **FR-3 谓词口径**：「无新增重叠」= 被拖片 vs 全体 bbox 相交邻居的总布尔交面积 ≤ 起手基线 + 1e-9（复用 `overlap.ts computeOverlap` 作 oracle，与红字指标同口径）。
- **FR-4 触发区分与守卫**：吸附**仅**由 `snap:true` 的右键拖动会话触发（pointerdown 时 `e.button===2` 决定）；左键拖动/键盘/旋转柄永不吸附；画布 `contextmenu` 抑制；吸附结果违反画布钳制不变量（y∈[0,gate]、minX≥0）弃用回落 raw；引擎任何内部异常 fail-open 返回 raw——吸附是增强，永不破坏既有钳制/拖动/落笔语义。
- **FR-5 不变量**：吸附只改 translation；rot/mirror/数量守恒；邻居寻址按 `EditPiece.key` 数组下标（多副本红线）。
- **FR-6 视觉反馈**：吸附瞬间伙伴片高亮 + 指南卡一行文案（「右键拖动松手贴附」语义）。
- **FR-7 几何口径**：erode 前端口径（manifest polygon；web 上传默认 d=0 时即物理毛版原始轮廓）；d>0 的策略跑批场景沿用既有口径分歧脚注，不引入双口径。

## 非目标 (Non-Goals)

- **左键拖动默认吸附**（2026-09-06 用户定案否决——「想要一点重合」是版师按工艺参考值压线的正常使用，默认吸附会对抗正常工作流；修饰键 Alt 触发/旁路方案同会评估未采用，备档）。
- **拖动过程中的实时吸附/推靠**（用户定案否决——松手时一次；振荡/逐帧性能风险整体回避，代价是拖动中可视觉穿模、松手跳到贴合位）。
- 键盘变换（L/K/空格/O/I/R）与旋转拖柄之后的自动贴靠（保持确定性/质心锚定语义；想贴靠可右键拖一下或用「智能微调」）。
- 画布边界（x=0 布头、y=0/gate 门幅边）的磁吸贴齐（本功能明确是「裁片裁片间」；边界贴齐可作后续独立小功能）。
- 物理毛版双口径（后端 manifest 扩字段方案已否决——与红字告警会互相矛盾）。
- 吸附阈值设置 UI（常量 10mm 常开，不上设置项；沿用项目「最小 UI、显式手势」取向）。
- 触控板等效修饰键触发（暂不实施，观察反馈再定——2026-09-06 定案；桌面鼠标是主用设备）。
- 后端任何改动（`polish.py` / 导出 / WS 零触碰）。

## 设计考虑 (Design Considerations)

- **双按钮双模式**：左键 = 自由放置（现状，压线/重合随意），右键 = 贴附模式（松手 retreat+attract）——手势即意图，可发现性优于修饰键，连续贴附多片无需和弦按键；交互预期（右键拖动中可视觉穿模、松手跳到贴合位）在指南卡文案与文档明示，不作为 bug 处理。
- **视觉反馈克制**：伙伴高亮复用既有交互层（`ensureUiLayers` 增一层），样式与主题一致、松手后短时消退；不做动画轰炸。
- **口径脚注一致性**：吸附判据与编辑画布红字告警、指标面板同一真相源（erode 口径），吸附后指标自证 0.00 是天然验收信号；d>0 场景沿用 `overlap.ts` 既有脚注口径，不新造解释。
- **坐标系**：全部数学发生在世界坐标 worldPolygon（mm）上；前端 SVG `scale(1,-1)` 翻转不影响（吸附不涉屏幕坐标计算，插入点在 clamp 之后、落笔之前）。

## 技术考虑 (Technical Considerations)

- **构建检查项偏差说明**：Story 模板缺省的「Python 模块 `python -m` 入口检查 + 分层依赖」项对本 PRD 不适用——纯前端特性零后端改动，逐条替换为「`npm run build` 干净 + 既有 vitest 全量通过 + 零后端改动」。
- **按钮门控事实**（已核实）：现行 `onPointerDown` 无 `e.button` 门控，右键无专属用途（缩放走滚轮、平移走空白左键拖、contextmenu 未处理）——右键拖动是空闲手势可占用；加门控顺手修掉「右键也能拖片/平移/转柄 + 松手弹浏览器菜单」隐性怪癖（改善非回归；左键路径不受门控影响）。实现 = MoveDrag 会话增 `snap: boolean`（pointerdown 定），移动帧/钳制/落笔管线全复用。
- **算法蓝本**：retreat 粗扫+二分+1nm 微退对齐后端 `nesting_engine/polish.py` 的 `_slide_west_touch` / `_sep_translate`（已验证机制，测试可对拍）；attract 用解析首触距离（顶点-边线性解，精确无迭代）。凹多边形正确性由布尔交 oracle 保证（不怕凹形）。
- **性能**：拖动帧零新增计算（`lastSafeTr` 借既有每帧红字指标顺带跟踪）；右键松手单次求解最坏 = 二分 14 轮 × 全邻居布尔交（生产基线：`computeOverlap` 每帧本就在跑同规模运算，无卡顿报告），谓词 bbox 预筛短路。
- **精度**：JS 浮点下「恰好 0」的工程定义 = 布尔交面积 ≤ 1e-9 mm² + 1nm 微抬（后端 `SEP_NUDGE_MM=1e-9` 同款）；translation 在 store/保存 wire/微调载荷三处全精度无取整（已核实），吸附结果原样贯通。
- **下游兼容**：吸附后的 placement 进入 `/api/edit-polish` 时，若 d=0（web 默认）两口径同一数据零扰动；d>0 场景 polish（毛版口径）可能对腐蚀口径贴 0 的片再做 y 优先最小分离——既有文档级口径约定，不在本期解决。
- **风险预案**：快速甩动拖动的隧道穿越由粗扫缓解；rAF 合帧使帧间位移通常几毫米；谓词取全邻居总量（漏一个邻居也会被总量暴露）。

## 成功指标 (Success Metrics)

- [ ] 右键松手吸附后被拖片 vs 全体邻居布尔交面积 ≤ 1e-9 mm²（vitest 数学锚点 + 冒烟指标面板 0.00 双锁）。
- [ ] **左键拖动行为逐字节不变**：压线落点原样、零吸附介入（冒烟专项断言）。
- [ ] 拖动帧耗时相对基线无可测回退（零新增逐帧计算，冒烟对拍拖动流畅性检查点）。
- [ ] 吸附 translation 经 保存 → /api/edit-polish → PLT 导出全链路原样贯通（冒烟全精度断言）。
- [ ] 既有 vitest 全量（当前 64 文件 1022 用例）通过 + `npm run build` 干净 + 后端 pytest 零触碰零回归。

## 待确认问题 (Open Questions)

- 伙伴高亮具体视觉形态（描边色/线宽/消退时长）：US-003 浏览器验收时与主题对拍定案，不在 PRD 锁死。

> 已收口（2026-09-06 用户定案）：① attract 阈值 = **10mm**（吸附已 opt-in 右键，网放宽；常量收口 `snap.ts` 顶部 `ATTRACT_MAX_GAP_MM`）；② 触控板无右键拖的等效修饰键触发 = 暂不实施、观察反馈再定（入非目标）；③ d>0 口径脚注 = **沿用 `overlap.ts` 现有脚注原文引用**（避免两处文案漂移）。

---

## 附：Story 依赖关系（消费顺序）

```
US-001（editGeometry 算子）→ US-002（snap.ts 引擎）→ US-003（EditCanvas 右键会话接线）→ US-004（冒烟+文档）
```

严格线性：US-002 消费 US-001 的 `firstContactDistance`；US-003 消费 US-002 的引擎纯函数与既有拖动管线；US-004 对 US-003 落地后的真实 UI 做端到端回归。
