# PRD: 编辑排料键盘变换与片级重置

## 概述 (Overview)

为编辑排料弹窗新增两类交互：①选中裁片的**键盘快捷键变换**（L/K 微转、空格 180° 掉头、O/I 镜像、支持按住连发），让排料师脱离鼠标做精确微调；②**裁片级重置**（R 键把单片恢复到算法基线原始布局），补齐「全局重置之外救回单片」的能力。核心工程难点是镜像：它是 det=−1 的反射，现有 `PlacedItem {id, rotation, translation}` 表达不了，需要 additive 的 `mirror?: boolean` 字段沿「画布渲染 → 保存 → NestSVG 主视图 → /export 三格式 → /api/edit-polish 引擎」全链贯穿，并以 omit-when-false 保证不带镜像时逐字节零回归。

## 已定案决策（2026-09-05 用户拍板，实现不再询问）

1. **重置交互 = R 键**（右键菜单/双击/工具区按钮均不做，右键菜单可作后续独立迭代）。
2. **微转步长 = 1°/次，Shift+L/K = 10°/次**；连续按住用浏览器 keydown auto-repeat（不建 rAF hold 循环）。
3. **重置语义 = 恢复算法基线**（与全局重置同一锚点：本会话首次打开弹窗时的算法原始布局；含 mirror 清零），不是「本次打开弹窗时快照」。
4. **本期不引入撤销栈**：键盘变换与拖动/旋转手势同口径无撤销，安全网 = ✕ 关闭 dirty 确认 + 全局重置 + R 片级重置；通用撤销栈留独立 story。

## 目标 (Goals)

- 选中裁片后 L/K/空格/O/I 五键全部生效，片绕质心变换不漂移，Y 出门幅自动钳制
- 按住 L/K 连续旋转（系统 auto-repeat ≈20~30 次/秒），幂等键（空格/O/I/R）忽略 repeat 零抖动
- 镜像片在画布、保存后主视图、PLT/DXF/PNG 导出、智能微调六处几何一致（WYSIWYG 端到端）
- R 键把单片恢复到算法基线（位置/旋转/镜像全清），其余片与 lastFrame 不动
- mirror 不出现时全链逐字节不变：既有 vitest（64 文件 966 项）+ pytest（681 项）+ smoke_edit_polish（29 检查）复跑全绿

## 用户故事 (User Stories)

### US-001: mirror 数据模型与前端纯函数层
- **Description**: As a developer, I want `PlacedItem` 加 additive `mirror?: boolean`（局部坐标系 x 翻转，`world = R(rot)·diag(−1,1)·p + t`），并让 `pointsStr`/`transformPolygon`/`overlap.ts` 变换函数吃可选 mirror 参数（`materialSorting-web/src/types/piece.ts`、`src/lib/geometry.ts`、`src/lib/editGeometry.ts`、`src/lib/overlap.ts`），so that 镜像裁片可被数据模型表达，且 mirror=false 路径与今日逐字节相同。
- **Acceptance Criteria**:
  1. `pointsStr(poly, rot, tr, true)` 输出 = 无镜像输出的 x 分量取负（手算方块用例锁死）；`transformPolygon` mirror 用例与 pointsStr 逐点对拍相等
  2. mirror 缺省 false 时两函数输出与改动前逐字节一致（既有 lib 单测零改动全绿）
  3. `EditPiece` 携带 mirror 且 `applyEditPlacement(ep, rot, tr, mirror)` 增量覆写正确；`precomputeEditPiecesFromItems` 读 `it.mirror === true`
  4. `lib/__tests__/` 三个测试文件各加 mirror 分支用例（含 mirror=false 回归对拍）全过
  5. TypeScript 构建通过（`cd materialSorting-web && npm run build`，tsc+vite）
- **Priority**: 1

### US-002: editStore mirror 贯穿 + resetItem action
- **Description**: As a user, I want mirror 在 store 拷贝/相等/写回/统计全链不丢（`materialSorting-web/src/store/editStore.ts` 的 `deepCopyItems`/`itemsEqual`/`applyToRun`/`setWorkingItem`/`computeLayoutStats` 五处显式字段 map），并新增 `resetItem(index)` 从基线恢复单片，so that 镜像编辑保存后不蒸发、单片可一键复位。
- **Acceptance Criteria**:
  1. mirror:true 项经 `deepCopyItems`/save（`applyToRun`）写回后 `run.lastFrame.placed_items[i].mirror === true`；mirror 缺省项写回**不含该键**（omit-when-false）
  2. `itemsEqual` 对 mirror 布尔差异返回 false（dirty 判定触发）；`computeLayoutStats` 的 transformPolygon 传 mirror
  3. `resetItem(index)`：baseline 在案且 `baseline.placedItems[index].id === working[index].id` 时恢复该下标为基线项深拷贝（mirror 天然清零，算法基线永无 mirror）；越界 / baseline 缺席 / id 错位 → 返回 false 且 working 不动（同 pid 多副本绝不能按 pid 寻址——AGENTS.md 红线②）
  4. resetItem 只写 working 草稿不写 run（与 setWorkingItem 同语义，保存才落盘）
  5. editStore 单测新增用例全过（含 resetItem 三态：正常/越界/id 错位）+ `npm run build` 过
- **Priority**: 2

### US-003: 画布与主视图渲染贯穿
- **Description**: As a user, I want 镜像片在编辑画布 5 层（毛版/净版/内部线/刺口/布纹线）与保存后的 NestSVG 主视图正确渲染，且微调载荷与撤销快照不丢 mirror（`materialSorting-web/src/components/edit/EditCanvas.tsx` 的 `applyPlacement`/`placementSig`/`clampPlacement`/`transformPt`、`src/components/nests/NestSVG.tsx` frame 渲染、`src/components/edit/EditLayoutModal.tsx` 的 prePolish 快照、`src/lib/editPolish.ts` 的 buildPolishPayload），so that 所见即所得端到端成立。
- **Acceptance Criteria**:
  1. working 项 mirror:true → EditCanvas 毛版/净版/内部线/刺口/布纹线 5 层 points 全部 x 取负（单测锁）；`placementSig` 含 mirror 段（池增量失效判定正确）
  2. 保存后 NestSVG 主视图该副本渲染为镜像形态（solver 原生帧无 mirror 键，缺省路径逐字节不变）
  3. `buildPolishPayload`：mirror:false 载荷**不含键**（既有 `EditLayoutModal.polish.test.tsx` 的 `expect(body.placed).toEqual([{id, rotation, translation}, ...])` 精确锁键集用例零改动保持绿）、mirror:true 载荷带 `mirror:true`
  4. prePolish 快照（微调撤销）含 mirror，撤销微调不丢镜像标志
  5. 新增单测全过 + `npm run build` 过；通过浏览器验证镜像片画布渲染观感
- **Priority**: 3

### US-004: 后端导出与微调引擎 mirror 支持
- **Description**: As a 版师, I want 镜像片在 PLT/DXF/PNG 导出几何正确、智能微调（诊断/障碍/derotate/compact/出口）按镜像几何计算并透传 mirror（`materialSorting-server/src/materialsorting/web/export_geometry.py` 的 `apply_transform`/`_transform_normal`/`placed_to_world`、`materialSorting-server/src/materialsorting/nesting_engine/polish.py`、`web/server.py` /api/edit-polish docstring），so that 镜像布局可裁剪、微调不破坏镜像状态。
- **Acceptance Criteria**:
  1. `apply_transform(poly, rot, tr, mirror=True)` 与前端 `transformPolygon` 同输入输出逐点相等；notch 法线 `_transform_normal` 镜像时 nx 取负再旋转；`placed_to_world` 读 `it.get('mirror')` 贯穿 5 层（/export 路由零改动，placed 键直通）
  2. polish.py：镜像片进入 `_world_geom`/derotate 前先局部 x 取负预处理（`local = [(-x, y) ...]`，`c_local` 用镜像后质心）；诊断/pass ③分离/pass ④compact 基于正确镜像几何；items 重建（:369-371）与出口（:570-572）均 omit-when-false 透传 mirror；无改进路径返回输入 list 原对象（含 mirror）不变
  3. derotate 对镜像片照常回正 {0°,180°}（M 不改 x 轴方向合法性，基线集不变）；守卫①-⑤与 Counter 终检零改动仍过
  4. `tests/test_polish.py` 加镜像 L 形非对称片夹具（世界多边形手算对拍 + derotate 透传 + 无改进不变量）+ `tests/test_web_edit_polish.py` 加 mirror 载荷→响应逐位透传 + export 侧 apply_transform/_transform_normal/placed_to_world mirror 对拍，全部通过；AST 禁 import web/cli 守卫不动
  5. `python -m materialsorting.nesting_engine.polish` 冒烟 exit 0 + `python -c "from materialsorting.web.server import app"` 导入通过、分层依赖未反向
- **Priority**: 4

### US-005: 键盘变换交互（L/K/空格/O/I + 守卫链 + 指南行）
- **Description**: As a 排料师, I want 选中片后用键盘精确变换——L 顺时针 +1°、K 逆时针 −1°（Shift+L/K = ±10°）、空格 180° 掉头、O 水平镜像、I 垂直镜像（= toggle mirror + rot+180 复合，数学等价真垂直镜像、质心锚定不漂移）——按住 L/K 借 keydown auto-repeat 连续旋转（`materialSorting-web/src/components/edit/EditCanvas.tsx` 新增 keydown effect + `EditLayoutModal.tsx` 传 `interactionEnabled`），so that 无鼠标也能微调。
- **Acceptance Criteria**:
  1. 按一次 L：rotation +1、translation 按质心锚定通式 `t' = c_world − R(rot')·M(m')·c_local` 补偿（单测精确值断言，片不漂移）；K 反向 −1；Shift+L/K = ±10；`e.repeat` 放行 ⇒ 按住连续步进；随后 `clampPlacement`（带 mirror 参）做 Y∈[0,gate] 与 minX<0 钳制（与拖动同口径，右界永不钳）
  2. 空格 = rot+180（质心锚定同式）；O = `mirror = !mirror`（rot 不变）；I = `mirror = !mirror` + rot+180；空格/O/I 均忽略 `e.repeat` 零抖动；空格 `preventDefault()`（防 body 滚动与聚焦按钮激活）
  3. 守卫链（单测逐条锁）：keydown target ∈ INPUT/SELECT/TEXTAREA/BUTTON 或 isContentEditable → 跳过（形态 select 聚焦按 L 零变换）；无选中片 → 跳过；`interactionEnabled=false`（EditConfirmLayer dirty 确认层打开，prop 缺省 true）→ 跳过
  4. 落笔复用 `commitDragPlacement` 泛化路径（DOM 5 层 setAttribute + setWorkingItem + 池增量 + 指标/手柄刷新），O(单片)
  5. 指南卡（右下）新增键盘行，建议文案：`键盘：L/K 微转 · 空格 180° · O 水平镜像 · I 垂直镜像 · R 重置此片`（不得含「形态」「保存」二词——EditCanvas.test 反向锁）；该测试关键词数组同步更新（正向加「键盘」，反向锁维持）
  6. EditCanvas.test 新增键盘 describe（dispatchEvent KeyboardEvent）覆盖上述全部断言，全过 + `npm run build` 过 + 通过浏览器验证按键交互与镜像渲染（连发不卡顿）
- **Priority**: 5

### US-006: R 键片级重置
- **Description**: As a 排料师, I want 选中片按 R 恢复到算法基线原始布局（复用 US-002 `resetItem`，交互入口在 EditCanvas keydown 分支），so that 单片过度编辑可救回而不丢其他片的编辑。
- **Acceptance Criteria**:
  1. 编辑某片（拖动+旋转+O 镜像）后按 R：该片 working 项逐字段回基线（rotation/translation/mirror 全清），其余片与 run.lastFrame 不动；画布该片 5 层 points 回基线值、指标/手柄同帧刷新
  2. R 忽略 `e.repeat`；未选中 / 确认层打开 / target 为表单控件 → 无效；resetItem 返回 false（id 错位守卫命中）时静默不动
  3. 单测覆盖：正常恢复 / repeat 忽略 / 未选中 / 确认层禁用四态，全过
  4. `npm run build` 过 + 通过浏览器验证 R 键复位（含镜像片复位）
- **Priority**: 6

### US-007: 端到端冒烟扩展 + 文档同步
- **Description**: As a maintainer, I want E2E 冒烟加键盘/镜像/重置段并同步三份技术文档（`materialSorting-web/scripts/smoke_edit_polish.mjs` 新段、`materialSorting-web/AGENTS.md`、`.docs/technical/agent-component-map.md`、`.docs/technical/agent-api-reference.md`），so that 新不变量被回归锁死、文档与实现一致。
- **Acceptance Criteria**:
  1. 冒烟新增段全 PASS：O 镜像一片 → 保存 → 导出 PLT 与 DXF 的 POST placed 含 `mirror:true` 且导出正文几何为镜像（坐标对拍）；微调请求/响应 mirror 逐位透传；R 键重置该片 points 回基线
  2. 既有 29 检查复跑全绿（mirror=false 路径零回归）
  3. 三份文档含 2026-09-05 之后 dated fragment：AGENTS.md（edit/ 树 + 「编辑键盘/镜像关键约定」节）、agent-component-map.md（编辑弹窗节 dated 注记）、agent-api-reference.md（/api/edit-polish 专节补 mirror 键 + /export placed mirror 说明）
  4. 全量回归：`cd materialSorting-web && npx vitest run` 全过 + `cd materialSorting-server && python -m pytest` 全过 + `npm run build` 过、static/ 已重建
- **Priority**: 7

## 功能需求 (Functional Requirements)

- FR-1: 键盘家族六键（选中片生效）：L=+1°、K=−1°、Shift+L/K=±10°、空格=180°、O=水平镜像、I=垂直镜像、R=片级重置；全部质心锚定（变换后片不漂移）、Y∈[0,gate] 与 minX<0 钳制（clampPlacement 与拖动同口径）。
- FR-2: 连续性：L/K 放行 `e.repeat`（按住 auto-repeat 连转）；空格/O/I/R 幂等键忽略 `e.repeat`。
- FR-3: 焦点与冲突守卫：target ∈ INPUT/SELECT/TEXTAREA/BUTTON/contentEditable 跳过；空格 preventDefault；dirty 确认层打开时 `interactionEnabled=false` 全键禁用；编辑弹窗不挂 ESC 关闭（红线①不破）。
- FR-4: `mirror?: boolean` additive 字段（omit-when-false）：语义 = 局部坐标系 x 翻转（`world = R(rot)·diag(−1,1)·p + t`）；O/I 共用单标志，I = toggle mirror + rot+180（`diag(1,−1) = R(180°)·diag(−1,1)` 复合律），不引入第二个正交标志。
- FR-5: mirror 全链贯穿：前端画布 5 层渲染 / placementSig / clampPlacement / NestSVG 主视图 / editStore 五处显式拷贝点 / 微调载荷 / 微调撤销快照 / 后端 export_geometry（含 notch 法线 nx 取负）/ polish 引擎（诊断/障碍/derotate/出口）/ /api/edit-polish 与 /export 契约文档。
- FR-6: `resetItem(index)`：下标寻址 + `baseline.placedItems[index].id === working[index].id` 对齐守卫；恢复为基线项深拷贝（mirror 清零）；只写 working 草稿。
- FR-7: 指南卡加键盘行（文案见 US-005 AC5），不得触发「形态」「保存」反向锁。
- FR-8: 智能微调引擎对镜像片按镜像几何计算（诊断/分离障碍/compact 滑贴）且响应透传 mirror；derotate 基线集 {0°,180°} 对镜像片不变。

## 非目标 (Non-Goals)

- 右键上下文菜单（重置/变换菜单项 + 快捷键说明入口）——用户已定案 R 键，菜单留后续独立迭代
- 通用编辑撤销栈（Ctrl+Z 逐条回退）——本期不建（已定案），键盘/手动编辑与拖动同口径无撤销
- rAF hold 循环平滑旋转 / 旋转动画过渡——原生 keydown auto-repeat 已满足
- 「重置此片」回本次打开弹窗时快照的口径——已定案回算法基线
- 求解器侧镜像姿态支持——mirror 仅存在于编辑态/导出/微调链路，solver 构造（build_instance/orientations）零改动
- 改动画布既有手势（拖动/旋转柄/滚轮缩放/平移/取消选中）、按钮行为、DOM 结构与 testid
- 画布重合指标改用物理毛版口径（erode 口径差异是既有文档级约定，不动）

## 设计考虑 (Design Considerations)

- **键盘家族一致性**：六键全字母/空格单键无修饰（Shift 仅作步长放大），与指南卡一行说明配套；R 键语义与全局重置同锚（「回到算法给的答案」），用户已被提示：R 会连上次保存的编辑一起抹掉该片（定案接受）。
- **镜像的业务注记**：引擎不合成镜像（US-001 v2 口径）是求解侧约束；编辑态手动镜像是排料师的显式覆盖（成对片需求由数量表达的现行口径下，镜像用于人工对贴/救急），保存/导出/微调必须如实尊重该覆盖。布纹合法性：mirror（diag(−1,1)）保持 x 轴，rot∈{0°,180°} 的镜像片布纹仍水平合法；编辑画布对任意 rot 本就只显示偏差不拦截（现行语义不变）。
- **PLT 文字方向**：镜像片布纹标注基 (u=(±1,0), w) 变换后 det 仍 +1 右手系，plt_text 防镜像守卫天然通过；PLT 仍无 g 码文字（口径不动）。
- **性能**：每次按键走与拖动帧同一落笔链 `commitDragPlacement`（O(单片)）；110 片 × ~30 顶点 ≈ 3300 点变换/次、30 次/秒 ≈ 10 万点变换/秒，JS 可承受（拖动 60fps 已实证同量级）；若实测卡顿，退化方案 = 复用 scheduleFrame 合帧（实现期裁量，不必提前建）。

## 技术考虑 (Technical Considerations)

- **omit-when-false 是硬约束**：`EditLayoutModal.polish.test.tsx:207-210` 的 `expect(body.placed).toEqual([...])` 精确锁键集，恒发 `mirror:false` 会红；前端载荷/快照/store 写回、后端 polish items 重建与出口全部「有镜像才带键」。
- **显式字段拷贝点清单（mirror 静默丢失风险点，逐一同步 + 各设透传单测）**：`deepCopyItems` / `itemsEqual` / `applyToRun` / `setWorkingItem`（editStore.ts）、`prePolish`（EditLayoutModal.tsx）、`buildPolishPayload`（editPolish.ts）、polish.py items 重建与出口。
- **变换公式三方锁**：前端 `pointsStr`/`transformPolygon`、后端 `apply_transform` 同一公式加 mirror 前置取负（`const x0 = mirror ? -x : x` 一行式），缺省路径逐字节不变。
- **同 pid 多副本不变量**：键盘与 resetItem 全程按 selRef 下标寻址（AGENTS.md 红线②、polish.py 多重集守卫同源）。
- **后端源码路径**：`materialSorting-server/src/materialsorting/`（tests 同目录树），非 CLAUDE.md 旧描述的根目录包；前端 `materialSorting-web/src/`。
- **测试策略**：单测（vitest：纯函数手算对拍 + 键盘守卫链逐条 + store 三态；pytest：镜像夹具 + 透传 + AST 守卫不动）→ E2E（smoke 新段 + 既有 29 检查复跑）→ 全量回归（vitest + pytest + npm run build）。
- **文档同步点**：`materialSorting-web/AGENTS.md`（dated fragment 惯例）、`.docs/technical/agent-component-map.md`、`.docs/technical/agent-api-reference.md`（/api/edit-polish 专节 + /export placed 说明）。

## 成功指标 (Success Metrics)

- [ ] 选中片后 L/K（含 Shift ±10°）/空格/O/I/R 六键全部生效，绕质心不漂移，Y 出布边自动钳制
- [ ] 按住 L 连续旋转无卡顿；空格/O/I/R 无 repeat 抖动；select/按钮聚焦、确认层打开时按键零变换
- [ ] 镜像片六处几何一致：画布 / 保存后主视图 / PLT / DXF / PNG / 智能微调（诊断、derotate、分离、compact、响应透传）
- [ ] R 键单片复位（含 mirror 清零），其余片不动；id 错位守卫拒绝时不炸
- [ ] mirror=false 全链逐字节零回归：vitest 全量 + pytest 全量 + smoke_edit_polish 29 检查 + npm run build 全绿
- [ ] 指南卡新行不含「形态」「保存」，反向锁维持
- [ ] 分层依赖未反向（polish 仍禁 import web/cli，AST 守卫在）

## 待确认问题 (Open Questions)

- 指南卡键盘行最终文案（默认按 US-005 AC5 建议，用户可在验收时改字——不影响结构）
- ET2008 真机读镜像 DXF / 绘图仪读镜像 PLT 的物理验收（版师人工环节，不阻塞合入；导出几何已有单测/冒烟坐标对拍锁死）
