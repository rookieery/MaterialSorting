# PRD: 编辑排料「智能微调」（polish 后处理）

## 概述 (Overview)

求解终局布局带有大量「负面重合与旋转」：spyrrow 目标函数只有料长，重合（per_type d 腐蚀位图放行的工艺余量）与旋转（离散角度集 ±45°）只是可行性维度，求解器不会花任何预算把斜片回正或把公差内重合滑进旁边空位——版师手动局部微调补的正是这个结构性缺口。本功能新增**引擎层确定性后处理模块** `nesting_engine/polish.py`（无 RNG、逐 move 守卫、无改进逐字节不变，LNS 同款哲学），经 `POST /api/edit-polish` 会话族端点暴露，编辑排料弹窗新增「智能微调」按钮一键触发，产出前后对比报告 + 一级撤销，应用到编辑草稿（working）不自动保存。

## 目标 (Goals)

- 终局布局中**可解的重合清零、可回正的旋转回正**（判定标准 = 物理毛版轮廓口径，与 /export 同源），且料长不增、密度不降（逐 move 守卫单调）。
- 结构性必要重合（无空位可解）如实进 residual 报告，不硬凑零、不付出宽度代价强行归零。
- 编辑弹窗一键触发、秒级返回（≤5s @ ~120 片）、可撤销（一级快照）、前后指标可验收。
- 引擎层纯函数模块（禁 import web/cli、确定性可回放），为 v2 worker 终帧自动 pass 与 CLI `--polish` 复用打基础。

## 用户故事 (User Stories)

### US-001: 引擎层 polish 核心模块（诊断 + 去旋转 + 去重叠 + 守卫 + 报告）
- **Description**: As a 排料工程师, I want 引擎层确定性后处理模块把终局布局的可解重合/可回正旋转自动清理 so that 不必手动逐片微调且导出布局更安全。
  新建 `materialSorting-server/src/materialsorting/nesting_engine/polish.py`：核心函数 `polish_layout(placed, pieces_by_id, gate_mm, *, exclude=None) → (placed_new, report)`，纯函数无 RNG。四个部分：
  ① **诊断**（物理毛版轮廓口径 = `pieces_by_id` 原始 polygon，与 /export `placed_to_world` 同源）：全图两两重合（bbox 预筛 + shapely 交集面积/穿透深度）+ 旋转偏差审计（每片 `dev = min(rot mod 180, 180 − rot mod 180)`）；
  ② **去旋转**：dev>0 的片按 dev 降序（平手按下标），沿 `discretize_orientations` 同款离散角度集向最近基线 {0°,180°} 步进试放（先试基线，无可行位逐步回退），质心锚定旋转（`t' = c_world − R(rot')·c_local`，变换公式与 `_transform_polygon`/`pointsStr` 同式）+ 邻域可行位搜索取**位移最小**可行位（落位搜索实现自由度：shapely 邻域候选或 constraints.py 位图腐蚀可行域，验收只锁行为与性能）；
  ③ **去重叠**：重叠对按穿透深度降序，最小分离平移（复用/改造 `waist_band._slide_touch` 粗扫+二分滑移机器，方向优先 ±y、−x 不增料长）+ 回贴；一片失败换动另一片；都失败记 residual；
  ④ **报告**：`{before/after: {overlap_pairs, max_penetration_mm, total_overlap_area_mm2, rotated_pieces(dev>0), rotation_dev_sum_deg, width_mm, density}, moves:[{index,pid,kind,from,to,detail}], residual:[...], excluded, elapsed_sec}`，density = real 口径 `Σ(area×multiplicity)/(width×gate)`。
  **逐 move 五道守卫**（任一不过弃该 move，最坏全 no-op）：y∈[0,gate] / 全图物理包络 maxX ≤ width_before(+0.5mm 容差) / 位移片 vs 全图物理轮廓零新重合（shapely 精确复核） / pid 多重集守恒（demand>1 同 pid N 条按**数组下标**逐实例寻址，绝不 pid 去重）/ exclude 集片永不被移动（仍作为障碍参与他人检查）。**无改进时返回输入 list 原对象（逐字节不变量，LNS 同款）**。
- **Acceptance Criteria**:
  1. 夹具「空白旁斜片」：单片 rot=25° 居空场 → polish 后 rotation 精确 ∈ {0,180}、dev=0、零重合、质心位移为可行位最小。
  2. 夹具「可分离重合对」：两片叠 5mm 且右侧有 ≥ 分离量空位 → polish 后 shapely 交集面积 = 0。
  3. 夹具「紧密布局」：全贴触无空位 → 输出与输入逐元素相同（list 原对象）、`report.moves == []`、residual 如实记录。
  4. 守卫夹具：唯一分离方向越门幅 / 唯一空位在 +x 尾部外（包络增长）两种构造各一 → move 均被拒。
  5. 多副本夹具：同 pid 3 副本仅第 2 副本需要微调 → 其余两条 from/to 逐字段不变（按 index 寻址断言）。
  6. 排除集夹具：exclude 命中的实例零移动，但第三片朝它滑移时仍被它挡住（障碍语义）。
  7. 确定性：同输入连跑两次，placed_new 与 report 数值全等。
  8. AST 守卫单测：`polish.py` 禁 import `web`/`cli`（对齐 test_waist_band/test_prefix 先例）。
  9. `python -m materialsorting.nesting_engine.polish` 冒烟（合成夹具自检 + PASS 输出，`--demo` 形态对齐 prefix `--pin-demo` 先例）exit 0；pytest 全量通过。
- **Priority**: 1

### US-002: POST /api/edit-polish 会话族端点
- **Description**: As a 前端编辑弹窗, I want 一个会话族端点接收当前编辑 placements 返回微调结果 so that 几何真相源留在 Python 且多会话隔离。
  `materialSorting-server/src/materialsorting/web/server.py` 新增路由，紧邻 `/api/edit-hold`（server.py:410）同款样板：读 `X-Session-Id`（缺省 → default 会话）→ `session_registry.resolve(create=False)`（过期/墓碑 → 401 `session_expired`、非法 → 400，`SessionError` 统一 `JSONResponse(e.payload(), e.status)`）→ 会话 `pieces_by_id` 取**物理毛版轮廓**（原始 polygon 非 eroded，/export 关键不变量 #2 同源）→ polish 构造段经 `run_in_threadpool` 执行（prefix-preview 先例，防阻塞事件循环）→ 顺手 `edit_hold.refresh(sid)`（编辑钉住与心跳同语义）。
  请求 `{placed: [{id,rotation,translation},...], gate_mm?, exclude?: {labels?: [g码], pids?: [pid]}}`（placements 随 body 带上 = /export routes_views.py:381 同款模式——后端不存布局态，唯一存储在前端 runRegistry）；响应 `{ok: true, placed, report}`（placed 条数与 pid 多重集与输入相等）。
- **Acceptance Criteria**:
  1. 200：TestClient 带 default 会话 state → 响应结构完整、placed 守恒（条数 + pid 多重集）、report 含 before/after/moves/residual 四段。
  2. 401/400：sid 过期/墓碑 → 401 `code=session_expired`；sid 非法 → 400（结构化 JSON，对齐 /api/edit-hold 用例）。
  3. 400：`placed` 空；任一 pid 未匹配会话 `pieces_by_id` → 400（文案提示「母版已变更？请重新求解/上传」——pid 全匹配才跑，不做部分降级）。
  4. `gate_mm` 缺省回退会话 state['gate_mm']（与 /export、/api/plt-table-preview 同法）。
  5. exclude 透传引擎（labels/pids 双键，缺省 None）；polish 在 `run_in_threadpool` 内执行（代码级断言 + 既有慢任务不阻塞事件循环的测试形态）。
  6. `python -m materialsorting.web.server` 可启动（路由注册无 import 错）；pytest 全量通过（新增 `tests/test_web_edit_polish.py`）。
- **Priority**: 2

### US-003: 前端「智能微调」按钮 + 对比卡 + 一级撤销
- **Description**: As a 版师, I want 编辑弹窗里一键智能微调并看到前后对比、不满意可撤销 so that 手动微调工作量大幅下降且结果可控。
  `materialSorting-web/src/components/EditLayoutModal.tsx` 画布左上工具区（「全览」按钮/形态 select 同区竖排）新增「智能微调」按钮：点击 → `lib/api.ts` `apiFetch` POST `/api/edit-polish`（载荷 = 当前 working placements + `run.manifest.gate_mm` + exclude best-effort 组装：run 记录有 band 配置 → `{labels:[band.label]}`；final 带 `prefix.pid`/`prefix.extra` → 成员 pid 集合；无记录省略键）→ 成功后 `editStore` 新 action 把返回 placed 写入 working（**不调用 save、不自动保存**，✕ 关窗即弃的既有语义不变）。
  **对比卡**：右下 `.edit-metrics` 同款悬浮卡样式（同盒观感、卡体可交互不遮画布拖动热区），展示前后五指标（重叠对数/最大穿透 mm/旋转偏差片数与 Σ偏差/料长 mm/密度 %）+ 口径脚注「物理毛版轮廓口径（与导出一致；画布红字为腐蚀后轮廓口径，数值可能偏小）」+ 「撤销微调」按钮。**一级撤销**：modal state 存 pre-polish working 快照（再次微调覆盖、关闭/重置清空）；失败（网络/4xx）→ 卡内错误文案、working 不变、编辑态不炸（401 session code 走既有全局阻断弹窗，正确行为）。
- **Acceptance Criteria**:
  1. vitest：点击微调 → 请求载荷形态正确（placed/gate_mm/exclude）→ 成功后 working 替换、画布数据源更新；按钮 loading 态期间禁用重复点击。
  2. vitest：撤销微调恢复快照 working；再次微调覆盖快照；关闭/重置后快照清空（撤销按钮消失）。
  3. vitest：接口失败 → 错误文案进卡、working 逐字段不变。
  4. exclude 组装：run 带 band → labels 命中；run 带 prefix → pids 命中（front_size/back_size/extra pid）；两者皆无 → 载荷无 exclude 键。
  5. vitest 全量 + `npm run build`（tsc+vite）通过。
  6. 通过浏览器验证编辑弹窗微调交互（按钮/报告卡数值/撤销/失败文案，截图目检）。
- **Priority**: 3

### US-004: 端到端冒烟与文档闭环
- **Description**: As a 项目维护者, I want 端到端冒烟与文档同步 so that 智能微调整条链路可回归验证、口径差异留档。
  新增 `materialSorting-web/scripts/smoke_edit_polish.mjs`（playwright Edge 通道，模板对齐 `smoke_edit_layout.mjs`/`smoke_prefix_extra.mjs`）：上传真实母版（data/ 5336）→ 高级配置 per_type 放开 d/tol（制造重合与旋转）→ 短时求解 → 打开编辑弹窗 → 触发智能微调 → 断言：`report.after.overlap_pairs < report.before.overlap_pairs`（或布局可解时 =0）、`rotation_dev_sum_deg` 下降、`after.width_mm ≤ before.width_mm`、`after.density ≥ before.density − 1e-6` → 撤销恢复 → 再微调 + 保存 → 导出 DXF/PLT placed 条数守恒（=Σdemand）。
  文档同步：`.docs/technical/agent-api-reference.md`（新端点节 + 会话速查表加行）、`agent-file-map.md`（polish.py 行 + 补 edit 树缺行）、`agent-component-map.md`（EditLayoutModal 微调区 dated 注记）、`web/AGENTS.md`（文件分工表/端点）、`CLAUDE.md`（nesting_engine 模块清单 polish.py 行）；**红字口径差异**（编辑画布 = erode 后轮廓、polish 报告 = 物理毛版）写入 api-reference 新节。
- **Acceptance Criteria**:
  1. 冒烟脚本全 PASS（含撤销路径与导出守恒断言），连跑两次微调结果一致（确定性）。
  2. band on 场景抽验（冒烟或手工）：exclude 生效，带形态区域 bbox 前后不变。
  3. 文档五处同步完成，红字口径注记在案。
  4. pytest 全量 + vitest 全量 + `npm run build` 通过；`python -m materialsorting.nesting_engine.polish` 冒烟 exit 0。
- **Priority**: 4

### US-005: 压缩回收档（compact pass，可选低优先级）
- **Description**: As a 排料工程师, I want 微调可选「回收空隙缩短料长」档 so that 去旋释放的空隙收进料长、密度不降反升。
  引擎 pass ④：自布头方向逐片滑贴（`_slide_touch` 粗扫+二分，−x 方向），接受条件 = 全图物理包络 maxX 严格变小且零新重合；无改进逐字节不变。端点 payload additive `compact: true`（缺省 false = US-001 行为逐字节不变）；前端报告卡内「回收空隙缩短料长」checkbox（默认不勾，随下次微调请求发出）。
- **Acceptance Criteria**:
  1. 夹具：去旋后留 ≥30mm 横向空隙 → compact 后包络减少 ≥29mm、零新重合。
  2. 夹具：无空隙可收 → compact=true 输出与 compact=false 逐元素相同。
  3. 端点/前端旗标 additive：缺省路径回归零变化（既有用例不改全过）。
  4. 冒烟脚本补 compact 分支断言（width ≤ 非 compact 档）。
  5. pytest/vitest/build 全绿。
- **Priority**: 5

## 功能需求 (Functional Requirements)

- FR-1: `nesting_engine/polish.py` 确定性后处理（无 RNG、排序平手按下标裁决、同输入同输出），禁 import web/cli（AST 守卫）。
- FR-2: 重合/旋转测量与守卫全部用**物理毛版轮廓**（会话 `pieces_by_id` 原始 polygon，/export 同源）；画布红字（erode 口径）不改，差异文档注明。
- FR-3: 去旋转目标 = 最近基线 {0°,180°}（180° 布纹等价合法），候选角取自 `discretize_orientations` 同款离散集。
- FR-4: 去重叠只在「免费」时做（不增料长、零新重合），版师 per_type d 工艺余量语义不受影响（不强行动归零 d 预算内的必要贴触）。
- FR-5: 逐 move 五道守卫 + 无改进逐字节不变（LNS 先例哲学：`_cross_overlap_ok`/`recheck_layout`/严格更优才回写）。
- FR-6: `POST /api/edit-polish` 会话族端点（X-Session-Id + resolve 闸门 + run_in_threadpool + edit_hold.refresh），placements 随 body、pid 全匹配才跑。
- FR-7: 前端按钮 + 对比卡（五指标 + 口径脚注）+ 一级撤销；应用 working 不自动保存。
- FR-8: exclude 载荷（band label / prefix 成员 pid，best-effort、over-conservative 可接受——同 pid 其他主解副本一并跳过）。
- FR-9 (US-005): compact 旗标 additive，缺省行为逐字节不变。

## 非目标 (Non-Goals)

- 不改 spyrrow 求解行为与 d/tol 求解语义（公差仍是搜索自由度，polish 只清洗终态）。
- worker 终帧自动 polish（v2，另立 PRD + prefix_accept 式 A/B 闸门 + frames 确定性对拍）。
- CLI `--polish`（v3，与 `--lns` 并列）。
- 前端红字告警切换物理口径（仅文档注明差异，不动既有编辑告警语义与拖动性能预算）。
- 多级撤销栈（编辑弹窗仍只有基线恢复点 + 本期一级微调快照）。
- 不追求重合全归零（结构性必要重合 residual 如实上报）。
- LNS 式 d=0 子实例波段重解清残留（v2.5 升级武器，另立 PRD）。

## 设计考虑 (Design Considerations)

- 按钮位：画布左上工具区竖排（全览/形态下方），与既有控件同观感；loading 期间禁用重复点击。
- 对比卡：`.edit-metrics` 同款悬浮卡；卡体 pointer-events 可交互但不得覆盖画布拖动热区；微调后常驻显示直到关闭/再次微调/撤销清空。
- 快照生命周期：再次微调覆盖、✕/重置清空；「撤销微调」仅在快照在案时可见。
- 口径脚注必须出现（版师看到卡数值与画布红字不一致时的解释锚点）。

## 技术考虑 (Technical Considerations)

- 病根机理：spyrrow 目标只有料长，重合/旋转是可行性维度（d 腐蚀 + 离散角度集构造期一次性注入）——终态整洁度无人负责，polish 是标准的解抛光后处理。
- 变换公式三方同源：`world = R(rot)·local + t`（后端 `_transform_polygon` / 前端 `pointsStr` / polish 同式）；去旋质心锚定 `t' = c_world − R(rot')·c_local`。
- 复用清单：`waist_band._slide_touch`（轴向滑贴粗扫+二分，prefix.py 已跨模块 import 先例）、`lns_bands._layout_geometry/_world_polygon`（布局几何）、`constraints.erode_bitmap`（位图备选）、shapely（既有依赖，erode_polygon/lns_bands 已用，不新增依赖）。
- demand 多副本按**数组下标**逐实例寻址（与 editStore「同 pid 第 k 次出现 = 第 k 副本」同口径）。
- 性能预算 ≤5s @ ~120 片（bbox 预筛 + 逐 move 局部检查）；超预算再启用位图可行域，验收锁行为不锁实现。
- 守卫容差：包络比较 +0.5mm；shapely 零新重合判定交集面积 ≤0.1mm²。
- 排除语义：exclude 实例不动但仍作障碍；缺 exclude 时靠「带内贴触零空位 → 无可行 move 天然 no-op」双保险。
- 后端不存布局态：polish 输入输出全走请求/响应（/export 同模式），无新会话状态。

## 成功指标 (Success Metrics)

- [ ] 构造夹具三类（斜片回正/重合清零/紧密 no-op）单测全过，守卫拒绝路径全覆盖。
- [ ] 真实母版端到端：微调后 overlap_pairs 下降、rotation_dev_sum 下降、width ≤ before、density ≥ before − 1e-6。
- [ ] 同输入两次微调输出全等（确定性，冒烟断言）。
- [ ] pytest 全量 / vitest 全量 / `npm run build` 全绿；`python -m materialsorting.nesting_engine.polish` exit 0。
- [ ] 编辑弹窗撤销微调恢复点击前 working（vitest + 浏览器目检）。

## 待确认问题 (Open Questions)

✅ 全部定案（2026-09-05 用户确认）：

1. **US-005 压缩回收档**：保留为独立低优先级 story，验收前可整体砍掉、不影响 US-001~004。
2. **对比卡形态**：常驻卡 + 撤销按钮（微调后常驻显示，直到关闭/再次微调/撤销清空）。
3. **exclude 口径**：v1 over-conservative（涉及 pid 的全部副本跳过）；精确实例下标需 worker 在 final 携带成员实例信息，v2 再议。
4. **红字口径**：本期不切换（编辑画布红字保持 erode 口径），差异仅在文档注明；观察 polish 上线后版师反馈再决定是否立独立 PRD。
