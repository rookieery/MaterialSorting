# PRD: 腰头成带（版师建议2 · web 主线 v1）

> 依据：[.docs/business/腰头成带_落地方案.md](../.docs/business/腰头成带_落地方案.md)（2026-08-21 定稿，planner 规划 + 11-agent 分析 + 6-agent 对抗核验三线合成）。Story 编号 US-009 起与方案文档对齐。

## 概述 (Overview)

把版师「腰头要排在一起，大小穿插缝隙会大」的经验固化为可开关的求解编排：用户在高级配置弹窗指定腰头 g 码后，该 g 码裁片先在带内独立聚排成高密度簇，整簇 union 轮廓作为一片虚拟组合片投入主求解，帧发射前在子进程内展开回成员 placement。**性质是业务规则（确定性聚排形态），不是利用率优化器**——验收线是形态保证 + 密度不显著劣化（A/B ≤1.0pt），不承诺提升。

## 目标 (Goals)

- 用户可指认任意 g 码（跨母版漂移：5336=g05、M1787=g09）成带，带形态构造性保证（聚排 + 同码成对相邻），不依赖求解器自发涌现（实测 seed1 即打散）。
- 组合片 pid（`WB_*`）在全链路（manifest/frame/final/前端/导出）零泄漏，下游渲染导出零改动。
- band 关闭路径与主干 HEAD 行为一致（既有测试零回归）；band 开启路径同 seed 可确定性重放。
- 开发风险前置收敛：UI/协议开工前先过 go/no-go 试点闸门（密度 A/B + comb Item NFP 微基准 + 带内 fill 曲线）。

## 用户故事 (User Stories)

### US-009: waist_band 核心模块（带内聚排 + 组合片构造 + 展开纯函数）
- **Description**: As a developer, I want `materialSorting-server/src/materialsorting/nesting_engine/waist_band.py`（`build_band_plan` / `expand_placements` / `BandChunk` / 常量）so that 组合片构造与展开有单一真相源，web 与未来 CLI 共用。机制按定稿方案：全幅 `NEST_GATE_MM` 带内子求解（**不是**窄条带——1161mm 长成员 + grain ±3° 锁定下窄条带不可行）→ 裁剪实际占用 bbox → `shapely.unary_union`（成员**原始**轮廓@带内位）→ `erode(d_g)` → `_clean_polygon` → 平移归一化（记录 offset）。
- **Acceptance Criteria**:
  1. `build_band_plan(pid_meta, pieces_by_id, *, label, seed, gate_nest)`：成员 = 该 label 在 quantities 口径下 demand>0 的全部副本（size-major 排序保证同码相邻）；默认产出**整带单组合片**（顶点数超阈值时 `simplify(0.05)`）；成员 Item 用 pid_meta 已腐蚀多边形（不二次腐蚀）、orientations = `discretize_orientations(tol_g)`；组合片 orientations=[0.,180.]（不带 tol 抖动）
  2. `expand_placements` 权威式黄金用例：`rot_f = m.rot + c.rot`；`tr_f = R(c.rot)·(m.tr − offset) + c.tr`（offset=(minx,miny) 为 union bbox 最小角，**减号**），composite rot=180 + 带偏移成员手算对拍通过；包络断言 union(成员原轮廓@展开位) ⊆ composite@主解位 ⊕ d_g（容差 0.5mm）
  3. 副本守恒：展开后 Σ 成员条数 == Σ demand（5336 g05 → 14/14）；0 副本抛 ValueError、总副本 1 抛 DegenerateBand；带内 fill < 45% 抛 BandQualityError（禁止无声 shelf 兜底）
  4. 确定性：band seed = `zlib.crc32(f'{seed}|{label}')` 派生，同 seed 两跑 `build_band_plan` 输出 JSON 相等
  5. `tests/test_waist_band.py` 全绿且既有 pytest 套件零回归；模块仅依赖 stdlib + shapely + nesting_bounds/nesting_engine（不 import web，分层依赖未反向）
- **Priority**: 1

### US-010: go/no-go 试点闸门（UI/协议开工前的决策实验）
- **Description**: As a 项目负责人, I want 一个试点脚本（复用 US-009 模块，不改产品代码）跑三组实验 so that 在投入 UI/协议开发前量化组合片机制的真实代价。产物只落 `out/config_runs/`（探针惯例），报告 JSON + 结论行。
- **Acceptance Criteria**:
  1. 密度 A/B：5336 同配置（120s、per_type g05={d:0.4,tol:3}）band off vs on × seed {0,1,2}，输出逐 seed `real_density` 对比表；**接受线 = on 的 3 seed 均值劣化 ≤1.0pt**
  2. NFP 吞吐微基准：主实例含 ~500 顶点 comb 组合片 vs 不含，同预算主解帧数/收敛曲线对比，吞吐劣化 >30% 判不过
  3. 带内 fill-预算曲线：band 预算 {5,10,15,30,60}s 的 fill_pct 序列，标注饱和点（推荐生产预算）
  4. 闸门结论三选一明示：`go` / `go-with-chunks`（NFP 不过→US-011 起用 pair-atomic 分块）/ `no-go`（**已决策：直接转 US-015 v1.1 混填料路线**，纯腰 v1 不合入）；报告落 `out/config_runs/_probes/band_gate_report.json`
  5. 试点脚本可通过 `python -m materialsorting.nesting_engine.waist_band_gate`（或 scripts/ 下入口）跑通、不写 web 事实源目录
- **Priority**: 2

### US-011: 后端编排接线（exclude_labels + 帧前展开 + stage + WS 校验）
- **Description**: As a user, I want `web/solver.py` 的 `build_instance` 加 `exclude_labels` 参数（**Item 构造层**跳过 band 成员——禁用 quantities=0 方式，那会连 pid_meta/total_area/manifest 一起抹掉）、`web/solve_worker.py` 在 `_emit_placed` **单点**挂展开（三处发射点 :88/:92/:113 共享该序列化器）、band 子求解**以线程方式**跑在 worker 进程内（`_terminate_solve_process` 不级联孙进程）、`web/routes_ws.py` 解析 StartPayload `band` 键并服务端校验、新增 stage 消息 so that WS solve 全链路支持成带。
- **Acceptance Criteria**:
  1. band 缺省/null：`solve_worker` 走原五元路径，`test_solve_proc.py` / `test_ws_stop.py` **零改动通过**；band on/off 下 manifest 的 `total_area` 与 pieces 列表逐字段一致（一致性单测）
  2. band 开启：WS 依序收到 `stage('band', {fill_pct, bbox, elapsed})` → manifest（无 `WB_`）→ frames/final（placed_items 无 `WB_`、成员 pid 按 demand 出现 N 次）；stage 经 `solve_with_callback_proc` drain 循环显式转发（现未知 kind 被丢弃）
  3. 服务端校验：band 非 dict→None；enabled 时 label 须匹配 `^g\d+$` 且存在于当前母版且该 g 码 quantities>0，否则结构化 error 早退；最小边 <60mm 或长宽比 >6 的 label 需 payload 显式 `ack:true` 才执行；build 失败维持「只投 error 不投 manifest」契约（test_solve_proc.py:155 断言）
  4. band 阶段 stop/断开：`_terminate_solve_process` 回收后无存活 python 子进程（线程化验证用例）；band 几何工件落 `paths.OUT_DIR/band_runs/*.json`（分块轮廓 + 成员带内位 + fill + band_elapsed；写失败仅 warn）
  5. 新增 `tests/test_waist_band_ws.py`（TestClient 套路）全绿；`ms-web` 启动无回归、分层依赖未反向
- **Priority**: 3

### US-012: 前端参数链路（form/params/WS 类型/useSolveRun）
- **Description**: As a user, I want `lib/params.ts`（`FormState.band_enabled/band_label` + `collectStartContext` band 三态解析 + `bandMemberCount` 校验函数，missing→1 口径与后端对齐）、`types/ws.ts`（`BandConfig` + `StageMsg`）、`useSolveRun.ts`（band 透传 + stage 分支写 `rec.stage`）、`NestingPage.tsx`（onStage → 状态行「腰头成带中…」）so that 前端能把成带配置发到后端并呈现带内进度。
- **Acceptance Criteria**:
  1. `collectStartContext`：band 关 / 开但未选编号 → null；开且有效 → `{enabled:true,label}`；`bandMemberCount` 对 missing→1、显式 0、未选码过滤三态正确
  2. StartPayload 含 `band`；收到 `stage` 消息时状态行更新且 run 不 finish；未知消息类型仍 default:break 静默忽略（旧后端不发 stage 也安全）
  3. `params.test.ts` / `useSolveRun.test.tsx` 扩展用例全绿；`npm run build`（tsc --noEmit && vite build）通过
- **Priority**: 4

### US-013: 高级配置弹窗「布局设置」UI + 校验 + 互斥
- **Description**: As a 版师, I want `PerTypeOverridesModal.tsx` 新增「布局设置」分区——子标题「开启腰头成带」+ 勾选框，右侧子标题「腰头编号」+ 下拉框（值域 = `/api/ptypes` representatives 动态 g 码，80×80 缩略图 + 徽章复用现有模式）——draft+confirm 语义、未勾选禁用下拉、`ControlPanel.tsx` 启动校验与策略互斥、新增 `POST /api/band/preview` 预求解回显 so that 我能安全指认腰头 g 码。
- **Acceptance Criteria**:
  1. 下拉值域动态（fetch 失败降级纯文字 g 码列表不阻塞）；未勾选时下拉 disabled；confirm 写回 `form.band_*`，取消/遮罩/ESC 丢弃草稿（既有双层 modal 约定不破坏）
  2. 确认时调 `POST /api/band/preview`（body 同 band 配置，executor 线程跑 5s 预算 `build_band_plan`）回显实测 `{fill_pct, bbox}` 对照 break-even 参考线（62.4~63.6%）提示；预览失败不阻塞确认（降级提示）
  3. 勾选未选编号 / 选中 g 码数量全 0 → 开始求解按钮置灰 + StatusLine 具体文案；band 开启时「高级运行」入口 disabled 且 title 说明原因；QtyMatrix 该 g 码某码数量为奇数时警告「该码不成对」
  4. `PerTypeOverridesModal.test.tsx` / `ControlPanel.test.tsx` 扩展全绿；`npm run build` 通过；**通过浏览器验证**：弹窗布局与暗色主题一致、勾选→下拉→确认→状态行 stage 提示全链路目检
- **Priority**: 5

### US-014: A/B 验收与形态判据闭环
- **Description**: As a 项目负责人, I want 5336 同源同构 on/off 3-seed 终验 + 形态判据 + 导出验证 + 文档更新 so that 成带功能以可证方式达到验收线后合入。
- **Acceptance Criteria**:
  1. 形态：同码成对相邻率（同 pid 副本中心距 ≤ (w_i+w_j)/2+ε）= 100%；带 span ≤ 阈值（整带形态目测清晰、无散落，截图落 `.docs/`）
  2. 密度：A/B 同源对照（注意与生产 0.9063 基线不同构——uploads 源、g05 d=0.0、kill 跑法；只与同配置 off 对照）劣化 ≤1.0pt
  3. 确定性：同 seed 重跑 placed_items/density 序列逐帧相等（**非 byte-identity**，帧含 wall-clock elapsed）；band_runs 工件可回放对拍
  4. 导出：PNG/R12-DXF/PLT 三格式成功，后端日志 grep 无「导出跳过：pid」（`WB_` 泄漏哨兵）；band 关闭路径产物与 HEAD 行为一致
  5. CLAUDE.md 数据流主线补 band 支线一句 + `.docs/business/` A/B 报告落盘；`pytest` + `npm run build` + `npm test` 全绿
- **Priority**: 6

### US-015: v1.1 填料混带（唯一实测过 break-even 线的形态）
- **Description**: As a 版师, I want band 配置支持填料多选（协议 `band.fillers: [labels]` + UI 任意 g 码多选——版师确认无白名单约束，带数量上限）so that 带内效率突破 break-even 线（实测混带 72.5% > 63.6%，纯腰 54.8~60.9% 不过线）。填料进 band 子求解并进 union、主实例同步扣减（同一 exclude_labels 路径）；band 内 d 适度放大（2~4mm）把肋间切口端部开到小件可入宽度。
- **Acceptance Criteria**:
  1. `band.fillers` 协议 + 服务端校验（填料 g 码存在、数量上限、与主 g 码不同）；填料成员与腰成员同一展开/守恒/泄漏口径
  2. UI 多选（缩略图同源）；主实例扣减后 total_area/manifest 仍与 off 口径一致（一致性单测沿用 US-011 #1）
  3. A/B：混带 on 的带区域效率（带板 bbox 内腰+填料面积/占用）≥ break-even 参考线，全局劣化 ≤1.0pt
  4. 全量测试零回归 + 浏览器目检多选交互
- **Priority**: 7

### US-016: v2 构造性链构造（版师形态：开口朝左 + 最大码在最右）
- **Description**: 2026-08-21 用户实测「成带后布局乱象」（6 码×1 少副本配置主解 -3.81pt），诊断闭环（`out/tmp_probe/exp_*.py`）：① v1 spyrrow StripPacking 带内目标 = 最短用布 X 而非贴触 → 48.2% 对角阶梯坏带形（预算 ×30 仅 +4.1pt，结构性卡死）；② US-014 成对重试 `_pairs_complete` 在每 pid 单副本时空真无牙口；③ 紧带组合片（607×1326）进主解实测 87.51% > OFF 86.08% —— 劣化是坏带形的代价、非成带固有代价。版师指正真实构造：**N 条单副本异码链**（每码第 k 副本一条链），链内片片贴触、缝隙只在链间，无需同码成对。用户建议1（本 story）：带开口朝**左**、最大尺码在**最右**；建议2（带置布料最右）实测结构性右置 -2.10pt，用户拍板暂缓。
- **实现**: `waist_band.py` 重写第 2 步：链拆分（chain_k=每码第 k 副本）→ 链内 size 降序 `_chain_nest` 构造性滑移贴靠贪心（rot{0,180}×5 y 对齐 × `_slide_touch` 右起 20mm 粗扫+40 次二分贴触，union bbox 增长最小，无 RNG 毫秒级）→ `_flip_chain` 整链点对称翻转（rot+180/tr 取负，合法布纹无镜像）⇒ 开口左+最大码右 → 形态自检（`_chain_gap`≤`CHAIN_GAP_EPS_MM`=1.0 贴触口径 + `_opening_side`∈{left,flat} + 最大码质心 x 最大）→ `_stack_chains` 堆叠（不翻链保开口）+ 带高守卫 ≤min(gate_nest,1910)。删除 spyrrow 求解/成对重试（`_pairs_complete`/`_slot_fallback`/`BAND_MAX_TRIES`/`BAND_NUM_WORKERS`）；`time_budget`/`fill_floor`/`PAIR_ADJ_EPS_MM` deprecated 保留（外部 import 兼容）。第 3-5 步管线（原始轮廓 union→焊接→erode(d_g)→归一化）与 BandChunk/expand_placements 契约零改动；solve_worker/routes_band/band_accept/CLI/前端零改动。
- **Acceptance Criteria**:
  1. 真实 5336 g05 两配置形态：链内缝隙 0.00mm、开口左、最大码右、fill ≥71.8%（6 码×1）/ ≥79.5%（P0 14 副本）
  2. 端到端 A/B（30s seed0 生产 WS 链路）：band on 密度 ≥ off；无 WB_ 泄漏；成员守恒；成员紧贴链形态（相邻 x 区间交集 >0）
  3. 确定性：同 seed 两跑 `to_dict()` JSON 相等
  4. pytest 全绿（band 四套件）
- **实测**: 6×1 fill 71.8%（537×1326）缝隙 0.00mm；P0 79.5%（1153×1271）；A/B **ON 88.35% vs OFF 86.08%（+2.27pt）**；stage fill/bbox/elapsed 与直测逐字段一致（71.77%/537×1326/0.21s）；pytest 60 项全绿。
- **Priority**: 8

## 功能需求 (Functional Requirements)

- FR-1: StartPayload 新增可缺省 `band: {enabled: bool, label: string, ack?: bool} | null`，缺省/null/{} = 关闭，旧行为逐字节不变；服务端校验 label 合法性与数量非零。
- FR-2: 新增 server→client 消息 `{'type':'stage','stage':'band', fill_pct, bbox, fallback:false, elapsed}`，仅 band 开启时在 manifest 前发一次；旧前端 default:break 静默忽略。
- FR-3: band 成员 = 选中 label 在 QtyMatrix 数量>0 的码全部副本（数量即一切，引擎不合成镜像）；带内 per_type 沿用该 g 码的 d/tol。
- FR-4: 展开发生在 `solve_worker` 的 `_emit_placed` 单点（帧发射之前），组合片 pid 永不出现在任何对前端可见数据。
- FR-5: 前端「布局设置」分区遵循弹窗既有 draft+confirm 模式；尺码范围不新增勾选 UI（语义 = QtyMatrix 数量>0）。
- FR-6: band 与策略运行（/api/strategy/*）v1 互斥：前端禁用入口 + 双方 API 契约注明（strategy_start 只拷白名单键，band 天然不进 CLI config）。
- FR-7: `POST /api/band/preview`：预求解回显 fill/bbox 供确认弹窗对照 break-even（失败降级不阻塞）。
- FR-8: 成带后组合片在主解中**不支持旋转**（版师确认 2026-08-21）：朝向固定为顺布纹 0°/180°（180° 仅整带头尾调换、布纹方向不变），旋转自由度只存在于带内成员贴排（各自 grain tol 内）；如需绝对锁死可配置为仅 0°。
- FR-9: 成带边缘间隙分两类（版师确认 2026-08-21 口径）：**外轮廓凹口/切口端部开口**可被主解其他裁片经 NFP 邻接填充（v1 密度回收主要来源）；**完全封闭的肋间内腔**在 v1 为死区（spyrrow 无洞支持，union 外轮廓封死，约占板 bbox 25~30%），由 v1.1 填料在带构造期填充。

## 非目标 (Non-Goals)

- CLI（ms-run-config 7 键 schema）band 支持、策略运行 band 支持、LNS frozen 概念、run_stats band 字段——均为二期接口备注，本期不实现。
- 建议1（起始端成套前后幅）前缀机制——独立需求，另行立项。
- 带位置约束（版师确认 2026-08-21：无布头/布尾位置要求，只有布纹方向要求——见 FR-8；组合片位置由主解自由决定）。
- 引擎合成镜像/左右手判定（数量即一切口径不变）。
- 镜像、成对强制代码约束（成对以带内排序 + 验收指标实现，不写求解硬约束）。

## 设计考虑 (Design Considerations)

- 弹窗暗色主题（#26282e 背景 / #2ea06c 强调色系），不引入 CSS 框架，样式进现有 `style.css`（`.per-type-band` 分区 + 下拉弹层复用 `.qty-fill-popover` 定位方案与 `PiecePreviewSVG compact` 缩略图）。
- 下拉项 = 缩略图 + g 码徽章（与 QtyMatrix 列头同模式），点击可开 `PtypePreviewModal` 放大预览（双层 modal 既有约定）。
- stage 期间前端状态行提示「腰头成带中：带内聚排…」（秒级，不进 phase 五态状态机）。
- 坐标系 `scale(1,-1)` 翻转约定不变；导出三格式对展开后 placements 零改动。

## 技术考虑 (Technical Considerations)

- **带几何**：band 子求解用全幅 `NEST_GATE_MM`（唯一实测配置 P3=54.80%），解完裁剪实际 bbox；h_band/rows 是输出不是输入。窄条带与 1161mm 成员 + grain ±3° 锁定矛盾，已否决。
- **展开权威式**：`rot_f = m.rot + c.rot`；`tr_f = R(c.rot)·(m.tr − offset) + c.tr`——offset 是**减号**（对抗核验驳倒过加号表述），黄金单测锁死；与 PlacedItem docstring / `_transform_polygon` / `apply_transform` / 前端 `geometry.ts` 四处同构。
- **移成员禁用 quantities=0**：会在 `build_pid_meta` 连 total_area/manifest 一起抹掉（密度掉 ~12pt）；必须在 `build_instance` Item 构造层 exclude。
- **进程模型**：band 子求解线程化跑在 solve_worker 内（`solve_with_callback_proc` 的 terminate 不级联孙进程）。
- **确定性**：band seed 用 `zlib.crc32` 派生（勿用 `hash()`）；验收口径是 placed/density 序列相等而非 byte-identity（帧嵌 wall-clock）。
- **泄漏哨兵**：`export_geometry.py:82-84` 服务端 warning（不进 HTTP 响应），A/B 时 grep 后端日志。
- 组合片 orientations=[0.,180.] 不带抖动（±3° 使块 bbox 膨胀 + 斜缝；工艺公差属于裁片不属于带；版师确认：成带后整块不再旋转，0°/180° 均严格顺布纹，如需锁死改 `[0.]`）；成员在带内保留各自 tol 离散角。
- spyrrow Item 无洞支持：union 取外轮廓后肋间空腔为主解死区——这是 v1.1 混填料的定量依据，v1 接受。

## 成功指标 (Success Metrics)

- [ ] A/B 同源对照（5336、120s、seed 0/1/2）：band on 劣化 ≤1.0pt（off 均值 87.2% 量级）
- [ ] 同码成对相邻率 100%；带形态目测成簇无散落（截图在案）
- [ ] 组合片 pid 全链路零泄漏（manifest/frame/final/前端/导出日志五处验证）
- [ ] 同 seed 重放 placed_items/density 序列逐帧相等
- [ ] band 关闭路径：既有 pytest（test_solve_proc/test_ws_stop 等）+ 前端 vitest 全绿，产物与 HEAD 行为一致
- [ ] go/no-go 闸门报告在案且结论为 go（或 go-with-chunks）后才合入 US-011+

## 待确认问题 (Open Questions)

已决策（2026-08-21 版师确认）：
- 填料**无白名单要求**——US-015 UI 开放任意 g 码多选（仍保留数量上限与「不可选主 g 码」校验）。
- 成带**无位置要求，有布纹线方向要求**——组合片在主解只允许顺布纹 0°/180°（FR-8），绝无 90° 或任意角。
- US-010 闸门若 no-go：**直接上 v1.1 混填料**（纯腰 v1 不合入）。
- 成带边缘间隙利用口径：外轮廓凹口可被主解填充、封闭内腔 v1 死区由 v1.1 填料填充（FR-9）。

仍开放：
- ack 硬警告阈值（最小边 <60mm、长宽比 >6）的参数值是否合适——可在 US-013 试用后调。
- 奇数 demand 的成对警告文案与阈值（单码数量=1 时提示还是拦截）。
- preview 预求解的预算（5s？）与结果缓存策略（同 label 短时间去重）。
