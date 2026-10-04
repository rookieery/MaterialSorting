# PRD: 初始布局录入与普通运行热启动（warm-start 二期）

## 概述 (Overview)

把 warm-start 一期（se 延长轮真顺延）已铺好的引擎透传链（`solve_with_callback_proc(initial_solution=...)` + worker 三闸门）向用户界面开放：版师/排料师在「高级配置：设置初始布局」弹窗中生成、编辑一个初始布局，保存后点普通运行即以此布局热启动继续优化——人机协同工作流（手排关键区域 + 机器增量优化）。立项出处 = `.docs/business/sparrow源码定制fork立项盘点_2026-09.md` §A 遗留②「编辑器录入初始布局」。

## 目标 (Goals)

- 用户可从界面获得一个 sparrow 短求解生成的完整初始布局，并复用排料结果编辑弹窗的画布交互进行编辑（手势收窄版）；
- 普通运行可基于该初始布局热启动：运行首帧宽度 == 灌入 strip_width（delta=0）且首帧密度 ≈ 初始布局密度（warm 生效签名，与一期 se 验收同款判据）；
- band/prefix 与初始布局可同开：成员片按组合组**整组拖动**（纯平移），组合视角载荷经 `record_composite` 机制灌入（se 二期机制向 WS 路径推广）；
- 全链 additive：不带 `initial` 键的普通运行、高级/极限运行、导出链行为逐字节零回归；任一 warm 失败路径降级回普通求解不炸轮。

## 用户故事 (User Stories)

### US-001: web 侧 warm 载荷装载点 + 能力探测端点
- **Description**: As a 排料工程师, I want 后端有一个「placed 列表 → spyrrow initial_solution 载荷」的 web 侧装载点与能力探测端点, so that WS 求解入口与前端按钮都能以单一真相源消费热启动能力（镜像 `cli/pipeline._load_warm_payload` 语义；一期结论：web 侧无此装载点）。
- **Acceptance Criteria**:
  1. 新模块 `web/initial_layout.py`：`build_warm_payload(pieces, placed, *, gate_mm, sizes, per_type, quantities, params, demand_map=None) -> tuple[dict|None, str|None]` —— `demand_map=None` 时经 `web.solver.build_pid_meta` 同口径投影（与 worker 实例宇宙一致，防 `instance_mismatch`）；`demand_map` 给定时（band/prefix 组合宇宙）直接采用；`strip_width` 用 `solver._physical_width_mm` 同款物理包络公式（ceil(maxX−1e-9)）计算；内部调 `warmstart.build_initial_solution`，其 ValueError / `warm_start_supported()` False / 形态非法 → 返回 `(None, 中文 reason)` 全降级不抛；
  2. `warm_capability() -> {'supported': bool, 'version': str}` 包装 `warmstart.warm_start_supported()`；`GET /api/warm-capability`（[routes_views.py](materialSorting-server/src/materialsorting/web/routes_views.py)）恒 200 返回该 dict；
  3. 分层：模块仅 import web 兄弟模块（solver/sessions）+ `nesting_engine.warmstart`，**禁 import server/cli**（AST 守卫 tests/test_web_initial_layout.py，镜像 test_web_edit_hold.py 套路）；
  4. pytest：装载点单测（合法 round-trip / mirror 拒绝 reason / 条数不符 reason / 组合 demand_map 直用 / strip_width 公式对拍 / unsupported 降级）+ 端点测试（TestClient）；
  5. `python -m materialsorting.web.initial_layout` 合成夹具冒烟自检 exit 0、分层依赖未反向。
- **Priority**: 1

### US-002: POST /api/initial-layout/generate 生成端点
- **Description**: As a 排料工程师, I want 一个跑 sparrow 短求解生成完整初始布局的端点, so that 弹窗打开/刷新时能拿到合法起点布局（含 band/prefix 组合视角）。
- **Acceptance Criteria**:
  1. `POST /api/initial-layout/generate`（[routes_views.py](materialSorting-server/src/materialsorting/web/routes_views.py)，样板 = `/api/edit-polish` 会话闸门 + `run_in_threadpool` + `prefix_accept.run_arm` 同步求解收集形态）；body 与 WS start 同形子集 `{sizes?, per_type?, quantities?, params?, gate(cm)?, band?, prefix?, seed?}`，gate 走 parseGate 同口径 cm×10；
  2. band/prefix 校验复用 [routes_ws.py](materialSorting-server/src/materialsorting/web/routes_ws.py) `_parse_band`/`_parse_prefix` 单一校验点（函数内延迟 import，band-preview 先例）；非法 → 400 中文；
  3. 求解编排：`solve_with_callback_proc(pieces_snapshot, gate, {time_budget: INITIAL_LAYOUT_GEN_TIME_S=10, seed, sizes, params, per_type, quantities}, band=, prefix=, record_composite=True)`，收集 manifest/可行帧，取密度最大可行帧（`_frame_allowed` 白名单已被 proc 层保证）；**不设 key 闸门**（预览族口径）；成功顺手 `edit_hold.refresh(sid)`；
  4. 响应 `{ok, manifest, placed(展开视图三键条目), width_mm, density, composite?{placed_items, demand_map}, prefix?}`——`composite` 段仅在 band/prefix 开时在场（worker `record_composite` 旁路，`WB_*`/`PS_*` 原始条目 + 组合 demand_map）；响应永无 `WB_`/`PS_` 出现在 `placed`（展开单点保证）；
  5. 错误矩阵：会话空/无母版 400「请先上传母版」；band/prefix 非法 400；同会话生成中再请求 409（per-session 单飞锁）；求解失败（含 worker error 帧）502 `{error: 中文}`；
  6. pytest：错误矩阵 + happy path（monkeypatch proc 收集器注入合成帧）+ 单飞 409 + record_composite 透传断言 + `import materialsorting.web.routes_views` 分层检查。
- **Priority**: 1

### US-003: WS start `initial` 键 + final `warm_state` 透传
- **Description**: As a 排料工程师, I want 普通运行 WS start 可携带初始布局、final 回传实际灌入态, so that 前端能基于保存的布局热启动并在未生效时得到明确反馈。
- **Acceptance Criteria**:
  1. [routes_ws.py](materialSorting-server/src/materialsorting/web/routes_ws.py) `run_solve`：`msg.get('initial')` 可缺省键，形态 `{placed: [{id, rotation, translation}...], demand_map?: {...}}`；band/prefix 解析之后经 US-001 `build_warm_payload` 组载荷（组合宇宙用载荷自带 demand_map）→ `solve_with_callback_proc(initial_solution=payload)`（该参数已存在，**worker/solver 透传链零改动**）；
  2. 装载失败（校验 ValueError / unsupported / 形态非法）→ `initial_solution=None` + 记 reason，**照常起普通求解不炸轮**（五类降级矩阵复用 se 一期语义）；
  3. final 消息 additive `warm_state`：worker 回写的 `{engaged, reason}` 优先（现已在 worker final 中、routes_ws 尚未透传——补上）；routes_ws 侧预丢弃时合成 `{engaged: False, reason}`；
  4. **缺省零回归**：无 `initial` 键时 WS 行为与 final 消息键集逐字节不变（既有 test_web_ws 全绿）；
  5. pytest：monkeypatch `solve_with_callback_proc` 断言 initial_solution kwargs 透传 / 降级路径 final warm_state 合成 / 缺省路径零差异对拍 + `import materialsorting.web.routes_ws` 分层检查。
- **Priority**: 1

### US-004: 前端 initialLayoutStore + API 封装 + 入口按钮
- **Description**: As a 排料工程师, I want 前端有初始布局状态仓与「高级配置：设置初始布局」入口按钮, so that 布局在保存与运行之间可靠持有、失效可感知。
- **Acceptance Criteria**:
  1. 新 `lib/initialLayout.ts`：`fetchWarmCapability()` / `generateInitialLayout(body)`（apiFetch POST JSON，样板 = [lib/editPolish.ts](materialSorting-web/src/lib/editPolish.ts) `postEditPolish`；类型含 `composite?` 段）；
  2. 新 `store/initialLayoutStore.ts`：`{supported, saved, generating, genSeed, error}`；`saved = {displayPlaced(展开视图), warmPlaced(组合宇宙条目), demandMap|null, fingerprint, widthMm, bandUsed, prefixUsed}`；fingerprint = 稳定序列化 `{sizes, per_type, quantities, params, gate_mm, band, prefix}`（组件口径先例 = run_stats class_key 组件法）；提供 `isStale(currentFingerprint)` / `clear()`；
  3. [controlPanelStore.ts](materialSorting-web/src/store/controlPanelStore.ts) `ControlPanelModalId` 增 `'initial_layout'`；[ControlPanel.tsx](materialSorting-web/src/components/ControlPanel/ControlPanel.tsx) 在「设置算法参数」按钮（[PerTypeOverrides.tsx](materialSorting-web/src/components/ControlPanel/PerTypeOverrides.tsx)）下方新增按钮，disabled 条件 = 无母版 || `supported === false`（title 中文提示「当前 spyrrow 版本不支持热启动」）；
  4. vitest：fingerprint 稳定性 / stale 判定（任一组件变更）/ clear / store 类型形态。
- **Priority**: 2

### US-005: EditCanvas 编辑手势收窄 + 整组拖动 props
- **Description**: As a 排料工程师, I want 编辑画布支持「初始布局模式」的手势收窄与 band/prefix 成员整组拖动, so that 编辑产物始终是热启动合法载荷（无镜像/无自由角/组合组刚性平移）。
- **Acceptance Criteria**:
  1. [EditCanvas.tsx](materialSorting-web/src/components/edit/EditCanvas.tsx) 新增可缺省 props（默认值 = 现行编辑弹窗行为**逐字节不变**）：`allowMirror?: boolean=true`（false 时空格四态循环收窄为 {0°,180°} 两态、O/I 镜像键禁用）、`allowFineRotate?: boolean=true`（false 时 L/K ±1° 键禁用）、`pieceGroup?: (pid: string) => string | null`（返回组 id：band 组 = band label 全部副本；prefix 组 = `parsePrefixMemberPids` 解析成员含异码补片；非成员 null）、`onIllegalOverlapCountChange?: (n: number) => void`（`refreshMetrics` 已算红色重叠计数，additive 回调暴露）；
  2. 整组拖动 = 指针命中组成员时整组刚性平移（组内单片不可单独拖/旋/翻/吸附，Alt 吸附对组拖不启用）；钳制按组整体 bbox（y∈[0,gate]、minX≥0）；组位移 delta 同步应用于该组全部展示副本；
  3. 组视觉标记（描边/角标 + 图例一行「组合成员片（整组拖动）」）；
  4. 浏览器验证编辑手势矩阵：空格仅两态、O/I/L/K 无效、组拖全组联动、非成员片拖动/翻转/吸附照常、红色重叠计数回调触发；
  5. vitest：默认 props 回归锁（既有编辑用例全绿）+ 收窄开关行为断言。
- **Priority**: 2

### US-006: InitialLayoutModal 弹窗（生成/编辑/刷新/保存闸）
- **Description**: As a 排料工程师, I want 一个界面与排料结果编辑弹窗一致、但去除了微调相关功能的初始布局弹窗, so that 我能快速编辑出满意的初始布局并保存。
- **Acceptance Criteria**:
  1. 新 `components/edit/InitialLayoutModal.tsx`（外层仿 [EditLayoutModal.tsx](materialSorting-web/src/components/edit/EditLayoutModal.tsx) 单例 + Inner key 重挂载模式；单例挂 [ControlPanel.tsx](materialSorting-web/src/components/ControlPanel/ControlPanel.tsx)）：打开时 `saved` 在场 → 载入续编，否则自动生成（generating busy 态、画布禁交互、进度提示）；
  2. 生成响应 → 合成伪 RunRecord（synthRun 先例）→ `editStore.open(伪run)`；`EditCanvas` props：`allowMirror=false`、`allowFineRotate=false`、`pieceGroup`（band/prefix 开时）、`polish` 不传（微调卡与「利用率增减」对比卡不渲染）；状态条只留料长 + 当前利用率（无 Δ 行）；edit_hold 心跳复用（`refreshEditHold`）；
  3. 「布局刷新」：working 有编辑 → 确认层「将丢弃当前编辑」；确认后 `genSeed+1` 重新生成替换；
  4. 「保存当前布局」：红色（非法）重叠计数 >0 → 按钮 disabled + 提示数量（琥珀压线不限）；守恒由编辑器副本池天然保证（= Σdemand 完整解）；保存 → 组装 `saved`：`displayPlaced` = 当前 working；`warmPlaced` = band/prefix 开时 `composite.placed_items`（各组条目 translation += 组位移 delta）+ 非成员 working 条目，plain 时 = 全条目；`widthMm` = `computeLayoutStats` 当前宽 → 写 initialLayoutStore → runRegistry 挂「初始布局（未求解）」伪卡片（`finalDensity` 留空 → 不进 `bestRun()`，导出/编辑排料选源不受污染）→ 关闭弹窗；
  5. 浏览器验证：生成→编辑→保存闸（构造红色重叠时禁用）→刷新确认→伪卡片出现；vitest：保存组装逻辑（组 delta 记账 / 非成员过滤 / plain 全量）。
- **Priority**: 2

### US-007: 普通运行接线 + warm_state toast + 端到端验收
- **Description**: As a 排料工程师, I want 点普通运行时自动附带初始布局、未生效时得到中文提示, so that 热启动全链路闭环且失败可感知。
- **Acceptance Criteria**:
  1. [types/ws.ts](materialSorting-web/src/types/ws.ts) `StartPayload` additive 可缺省 `initial?`；[useSolveRun.ts](materialSorting-web/src/hooks/useSolveRun.ts) 组装时附带（`{placed: warmPlaced, demand_map}`）；
  2. [ControlPanel.tsx](materialSorting-web/src/components/ControlPanel/ControlPanel.tsx) `handleStart`：`saved && !isStale(当前指纹)` 才附带；stale/清除不附带（不拦截运行）；[SolveControls.tsx](materialSorting-web/src/components/ControlPanel/SolveControls.tsx) 求解按钮旁 chip 三态：「将基于初始布局运行 · 清除」/「初始布局已失效（参数已变更）」/ 无；注记「初始布局仅普通运行生效」（高级/极限忽略）；
  3. final 处理：`warm_state.engaged === false` → toast 中文 reason（映射：`unsupported`/`worker_unsupported`→「当前 spyrrow 版本不支持热启动，已按普通方式运行」、`invalid_*`→「初始布局校验未通过，已按普通方式运行」、`instance_mismatch`→「数量或参数与初始布局不一致，已按普通方式运行」）；engaged=true → 状态行轻提示「已从初始布局热启动」；
  4. 新 UI 冒烟 `materialSorting-web/scripts/smoke_initial_layout.mjs`（playwright Edge 通道，模板 = smoke_edit_polish.mjs / smoke_prefix_extra.mjs）：上传 5336 样例 → 生成 → 拖动一片 → 保存 → 伪卡片 + chip → 普通运行短预算 → **首帧 width_mm == 保存时 widthMm（delta≈0）且首帧 density ≈ 初始布局 density（warm 生效签名）** → final `warm_state.engaged === true` → band 变体（开 band 生成、组拖、保存、运行、engaged）→ 改数量触发 stale → 运行不带 initial 零回归；
  5. `npm run build` 后在 :8010 生产包复跑冒烟（用户入口是生产构建）；全量 pytest + vitest 绿；文档收尾：agent-api-reference.md 新专节（generate/capability 端点 + WS `initial` 键 + `warm_state`）+ README 数据流段 + CLAUDE.md 注记。
- **Priority**: 3

## 功能需求 (Functional Requirements)

- FR-1 入口与能力：按钮位于「高级配置：设置算法参数」下方；无母版或 spyrrow 无 `+ms≥1` 能力时置灰并给原因；`GET /api/warm-capability` 单一探测源。
- FR-2 生成：sparrow 短求解（固定 10s 常量）生成**完整合法**布局；携带当前 sizes/per_type/quantities/params/gate/band/prefix（与普通运行同源采集）；刷新换 seed（0 起递增）产不同方案；per-session 单飞。
- FR-3 编辑（与排料结果编辑弹窗一致部分）：拖动、Alt+左键松手吸附、0°/180° 空格翻转、R 片级重置、红色/琥珀重叠红字、Y 门幅钳制；**不含**：智能微调、微调前后对比（利用率增减）UI、镜像态、L/K 自由微调角。
- FR-4 band/prefix 同开：成员片按组合组整组拖动（纯平移、组内禁单独编辑、无吸附）；组合条目（`WB_*`/`PS_*`）随组位移同步更新；生成响应 `composite` 段作为不透明载荷持有。
- FR-5 保存闸：红色（非法）重叠 >0 禁止保存（琥珀 = 合法压线不受限）；placed 守恒 = Σdemand。
- FR-6 界面应用：主界面出现「初始布局（未求解）」伪卡片（不参与 bestRun/导出/编辑排料选源）+ 求解按钮旁「将热启动」chip（含清除）。
- FR-7 热启动运行：仅普通运行消费；WS start 附 `initial` 载荷；server 侧装载点校验（镜像/完整解/宇宙）；final additive `warm_state`；未生效 toast 中文原因。
- FR-8 失效机制：sizes/per_type/quantities/params/gate/band/prefix 任一变更 → stale（chip 变灰提示、运行不附带）；会话内存态（页面刷新即失，v1 接受）。

## 非目标 (Non-Goals)

- 组合片**整组旋转/翻转**（v1 仅平移；组旋转可作后续增强）——**已于 2026-10-04 后续迭代交付**：空格 = 整组 180° 掉头（绕组包络中心点反射，幂等两态）、R = 整组重置、旋转柄自由角拖 + 松手吸附最近 180° 倍数（组合片合法朝向恒 {0°,180°}，版师认可带整带头尾调换）；L/K 微转与 O/I 镜像保持禁用（镜像 proper-rigid 硬拒）；保存闸记账扩展点反射形态（`groupRigidMap`，非法角/成员不一致防御性拒存）；
- 「从当前求解结果载入初始布局」第二来源（后续可加）；
- 高级运行/极限运行消费初始布局（用户定案：仅普通运行）；
- `.msn` 状态文件持久化初始布局 / checkpoint 快照携带（后续 additive 槽）；
- LNS、机器对接 API 消费初始布局；
- worker/solver 透传链与导出链的任何改动（零改动红线）。

## 设计考虑 (Design Considerations)

- 弹窗视觉与交互全部复用排料结果编辑弹窗（同 NestSVG/EditCanvas 体系、`scale(1,-1)` 坐标系不变）；差异仅三处：无微调卡/Δ 行、按钮组（刷新/保存）、生成 busy 态；
- 组成员片加视觉标记（描边/角标 + 图例），明示「整组拖动」语义；
- 生成 ~10s 为同步 HTTP（run_in_threadpool，edit-polish/band-preview 同族先例），弹窗内 busy 进度提示即可，不引入 WS/异步任务复杂度；
- 伪卡片在普通运行启动时随 `runRegistry.clear()` 消失（既有行为，接受——chip 仍标示热启动态）。

## 技术考虑 (Technical Considerations)

- **warm 载荷契约**（`warmstart.build_initial_solution`）：条目三键 `{id, rotation, translation}`；每 pid 条数 == demand 完整解硬约束；`mirror: true` 硬拒（编辑手势已禁镜像 → 载荷不可能出现）；
- **sparrow 对手工布局的容忍度**（jagua-rs 源码实读结论，2026-09 存档）：重叠输入静默容忍不炸、非法旋转角静默保留、镜像无反射——因此**编辑手势收窄 + 保存闸前置**是质量保障手段，而非求解器校验兜底；
- **demand_map 双口径**：plain = `build_pid_meta(pieces, sizes, per_type, quantities, params)` 投影（与 worker 实例同口径，防 `instance_mismatch`）；band/prefix = 生成响应 `composite.demand_map` 不透明透传（worker 宇宙复检兜底）；
- **strip_width** = 物理毛版包络宽（`solver._physical_width_mm` / 前端 `computeLayoutStats` 同式）；restore 续跑语义（不重新收缩）；
- **record_composite 复用**：CLI best_frame 边车旁路机制原样用于 HTTP 响应（`solve_with_callback_proc(record_composite=True)` 参数已存在，引擎零改动）；
- **降级矩阵**（全不炸轮）：`unsupported` / `worker_unsupported` / 载荷校验失败 / `instance_mismatch` → 回退普通求解 + final `warm_state` 回传 + 前端 toast；
- **组位移记账**：以生成基线 placed 为参照，任一成员当前位移 = 组 delta；`WB_*` 全条目属 band 组、`PS_*` 条目属 prefix 组（pid 前缀判组，`parsePrefixMemberPids` 已有）；
- **分层**：新 `web/initial_layout.py` 禁 import server/cli（AST 守卫）；routes_views 对 routes_ws 解析器走函数内延迟 import（防环先例）；
- **多 seed**：前端普通运行多轮 start 时每轮附同一载荷（同 warm 输入轨迹确定，一期实测）。

## 成功指标 (Success Metrics)

- [ ] warm 生效签名：普通运行首帧 `width_mm` == 保存时 `widthMm`（delta ≈ 0）且首帧 density ≈ 初始布局 density（US-007 冒烟断言）；
- [ ] band/prefix 同开变体：final `warm_state.engaged === true`（组合宇宙灌入成功）；
- [ ] 零回归：无 `initial` 键的普通运行 / 高级运行 / 极限运行 / 导出行为与消息键集逐字节不变；pytest + vitest 全量绿；
- [ ] 保存闸有效：构造红色重叠时保存禁用；降级矩阵任一命中不炸轮回退普通求解；
- [ ] UI 冒烟 `smoke_initial_layout.mjs` 全过（含 :8010 生产包复跑）。

## 待确认问题 (Open Questions)

无（三项均已定案，2026-10-03 用户确认）：

1. 生成时间预算**固定 10s**（`INITIAL_LAYOUT_GEN_TIME_S` 常量），弹窗内不暴露时长选择；
2. **不做** `.msn` 初始布局持久化槽（会话内存态、页面刷新即失，v1 接受；非目标已列）；
3. 「布局刷新」确认层文案定稿 =「将丢弃当前编辑」（US-006 AC 3 已按此写）。
